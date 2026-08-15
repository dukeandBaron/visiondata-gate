"""End-to-end orchestration over deterministic tools and fail-closed policy."""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from pathlib import Path
from typing import Any, TypeVar

from pydantic import BaseModel

from .agents import build_council
from .contracts import (
    BatchContract,
    BatchManifest,
    CorruptionManifest,
    EvaluationResult,
    GateResult,
)
from .evaluation import evaluate_gate
from .evidence import (
    canonical_json_bytes,
    sha256_file,
    write_canonical_json,
    write_evidence_artifacts,
)
from .generator import generate_demo_dataset
from .policy import apply_policy
from .repair import RepairResult, simulate_repair
from .reporting import write_offline_html
from .tools import run_all_tools
from .runtime_models import ScenarioProfile


ModelT = TypeVar("ModelT", bound=BaseModel)


@dataclass(frozen=True)
class DemoRun:
    output_root: Path
    dataset_paths: dict[str, Path]
    initial_result: GateResult
    repair: RepairResult
    repaired_result: GateResult
    evaluation: EvaluationResult
    evidence_dir: Path
    summary_path: Path


def _load_model(value: str | Path | ModelT, model_type: type[ModelT]) -> ModelT:
    if isinstance(value, model_type):
        return model_type.model_validate(value.model_dump(mode="json"))
    path = Path(value).expanduser().resolve(strict=True)
    return model_type.model_validate_json(path.read_text(encoding="utf-8"))


def _safe_member(root: Path, relative: str) -> Path:
    root_resolved = root.expanduser().resolve(strict=True)
    candidate = root_resolved.joinpath(*relative.replace("\\", "/").split("/")).resolve(
        strict=False
    )
    try:
        candidate.relative_to(root_resolved)
    except ValueError as exc:
        raise ValueError(f"manifest path escapes batch root: {relative}") from exc
    return candidate


def compute_batch_digest(
    batch_root: str | Path,
    manifest: BatchManifest | str | Path,
    contract: BatchContract | str | Path,
) -> str:
    """Hash the frozen contract, manifest, and every referenced input byte."""

    root = Path(batch_root).expanduser().resolve(strict=True)
    if not root.is_dir():
        raise NotADirectoryError(root)
    manifest_model = _load_model(manifest, BatchManifest)
    contract_model = _load_model(contract, BatchContract)

    records: list[dict[str, Any]] = []
    for sample in sorted(manifest_model.samples, key=lambda item: item.sample_id):
        members = [("image", sample.relative_path)]
        if sample.annotation_path is not None:
            members.append(("annotation", sample.annotation_path))
        for kind, relative in members:
            path = _safe_member(root, relative)
            records.append(
                {
                    "kind": kind,
                    "sample_id": sample.sample_id,
                    "path": relative.replace("\\", "/"),
                    "exists": path.is_file(),
                    "sha256": sha256_file(path) if path.is_file() else None,
                }
            )
    payload = {
        "contract": contract_model.model_dump(mode="json"),
        "manifest": manifest_model.model_dump(mode="json"),
        "files": records,
    }
    return hashlib.sha256(canonical_json_bytes(payload)).hexdigest()


def run_gate(
    batch_root: str | Path,
    manifest: BatchManifest | str | Path,
    contract: BatchContract | str | Path | None = None,
    *,
    scenario_profile: ScenarioProfile = ScenarioProfile.GENERIC,
) -> GateResult:
    """Run all allowlisted tools, AI Council trace, and deterministic policy."""

    manifest_model = _load_model(manifest, BatchManifest)
    contract_model = (
        BatchContract() if contract is None else _load_model(contract, BatchContract)
    )
    digest = compute_batch_digest(batch_root, manifest_model, contract_model)
    findings, traces, metrics = run_all_tools(
        batch_root,
        manifest_model,
        contract_model,
        include_optional_tools=scenario_profile is not ScenarioProfile.GENERIC,
    )
    council = build_council(findings, traces, metrics)
    return apply_policy(
        manifest_model,
        contract_model,
        findings,
        traces,
        metrics,
        council,
        scenario_profile=scenario_profile,
        input_sha256=digest,
        run_id=f"gate-{digest[:16]}",
    )


def run_full_demo(
    output_dir: str | Path,
    *,
    seed: int = 20260809,
    contract: BatchContract | None = None,
    scenario_profile: ScenarioProfile = ScenarioProfile.GENERIC,
) -> DemoRun:
    """Generate, gate, repair, re-gate, evaluate, and write inspectable evidence."""

    output_root = Path(output_dir).expanduser().resolve()
    output_root.mkdir(parents=True, exist_ok=True)
    dataset_paths = generate_demo_dataset(output_root / "dataset", seed=seed)
    contract_model = contract or BatchContract()
    manifest = _load_model(dataset_paths["batch_manifest"], BatchManifest)
    truth = _load_model(dataset_paths["corruption_manifest"], CorruptionManifest)

    initial = run_gate(
        dataset_paths["batch_root"],
        manifest,
        contract_model,
        scenario_profile=scenario_profile,
    )
    repair = simulate_repair(
        dataset_paths["batch_root"],
        manifest,
        dataset_paths["reserve_manifest"],
        initial.work_orders,
        output_root=output_root / "repaired_batch",
    )
    repaired = run_gate(
        repair.output_root,
        repair.manifest,
        contract_model,
        scenario_profile=scenario_profile,
    )
    evaluation = evaluate_gate(truth, initial, repaired)

    evidence_dir = output_root / "evidence"
    initial_dir = evidence_dir / "initial"
    repaired_dir = evidence_dir / "repaired"
    write_evidence_artifacts(initial_dir, initial, evaluation)
    write_offline_html(initial_dir / "report.html", initial, evaluation)
    write_evidence_artifacts(repaired_dir, repaired)
    write_offline_html(repaired_dir / "report.html", repaired)

    summary = {
        "schema_version": "visiondata-gate.demo-summary.v1",
        "seed": seed,
        "initial": {
            "decision": initial.decision.value,
            "finding_count": len(initial.findings),
            "run_id": initial.run_id,
        },
        "repair": {
            "completed_work_order_count": len(repair.completed_work_orders),
            "replacement_count": len(repair.replacement_map),
        },
        "repaired": {
            "decision": repaired.decision.value,
            "finding_count": len(repaired.findings),
            "run_id": repaired.run_id,
        },
        "evaluation": evaluation.model_dump(mode="json"),
        "boundary": initial.boundary_notice,
    }
    summary_path = evidence_dir / "demo_summary.json"
    write_canonical_json(summary_path, summary)
    return DemoRun(
        output_root=output_root,
        dataset_paths=dataset_paths,
        initial_result=initial,
        repair=repair,
        repaired_result=repaired,
        evaluation=evaluation,
        evidence_dir=evidence_dir,
        summary_path=summary_path,
    )


__all__ = ["DemoRun", "compute_batch_digest", "run_full_demo", "run_gate"]
