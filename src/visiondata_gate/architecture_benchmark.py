"""Same-protocol benchmark for traditional, single-Agent, and multi-Agent paths.

The benchmark deliberately freezes the data, contract, tool implementations,
and deterministic Policy Judge.  Only orchestration and advisory review change.
This makes it possible to reject, rather than assume, a multi-Agent advantage
on fixed-SOP work.
"""

from __future__ import annotations

from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from enum import Enum
import hashlib
import math
import os
from pathlib import Path
import platform
import statistics
import time
from typing import Any, Sequence

from .agents import (
    build_council,
    build_single_agent_review,
    build_traditional_pipeline_receipt,
)
from .contracts import (
    BatchContract,
    BatchManifest,
    CorruptionManifest,
    Finding,
    GateDecision,
    GateResult,
    ToolTrace,
)
from .evidence import canonical_json_bytes, write_canonical_json
from .evaluation import evaluate_gate
from .generator import generate_demo_dataset
from .pipeline import compute_batch_digest
from .policy import apply_policy
from .runtime_models import ScenarioProfile
from .tools import run_all_tools, run_tool, tool_catalog


class ArchitectureMode(str, Enum):
    TRADITIONAL = "traditional_pipeline"
    SINGLE_AGENT = "single_agent"
    MULTI_AGENT = "multi_agent"


class EvidencePerturbation(str, Enum):
    CANONICAL = "canonical"
    REVERSE_FINDINGS = "reverse_findings"
    REVERSE_TRACES = "reverse_traces"
    ROTATE_EQUIVALENT_EVIDENCE = "rotate_equivalent_evidence"


@dataclass(frozen=True)
class ArchitectureBenchmarkRun:
    report_path: Path
    report_sha256: str
    report: dict[str, Any]


def _percentile(values: Sequence[float], percentile: float) -> float:
    ordered = sorted(values)
    if not ordered:
        return 0.0
    if len(ordered) == 1:
        return ordered[0]
    position = (len(ordered) - 1) * percentile
    lower = math.floor(position)
    upper = math.ceil(position)
    if lower == upper:
        return ordered[lower]
    fraction = position - lower
    return ordered[lower] * (1 - fraction) + ordered[upper] * fraction


def _parallel_tools(
    batch_root: Path,
    manifest: BatchManifest,
    contract: BatchContract,
) -> tuple[list[Finding], list[ToolTrace], dict[str, int | float | str]]:
    catalog = tool_catalog(include_optional=True)
    with ThreadPoolExecutor(max_workers=len(catalog)) as pool:
        futures = [
            pool.submit(
                run_tool,
                str(item["name"]),
                batch_root,
                manifest,
                contract,
                include_optional=True,
            )
            for item in catalog
        ]
        results = [future.result() for future in futures]
    results.sort(key=lambda item: item[1].sequence)
    findings = sorted(
        [
            finding
            for tool_findings, _trace, _metrics in results
            for finding in tool_findings
        ],
        key=lambda item: (item.tool, item.finding_id),
    )
    traces = [trace for _findings, trace, _metrics in results]
    metrics: dict[str, int | float | str] = {
        "sample_count": len(manifest.samples),
        "tool_count": len(traces),
        "tool_error_count": sum(trace.status != "ok" for trace in traces),
    }
    for _findings, _trace, tool_metrics in results:
        metrics.update(tool_metrics)
    metrics["finding_count"] = len(findings)
    return findings, traces, metrics


def _perturb(
    findings: list[Finding],
    traces: list[ToolTrace],
    perturbation: EvidencePerturbation,
) -> tuple[list[Finding], list[ToolTrace]]:
    perturbed_findings = list(findings)
    perturbed_traces = list(traces)
    if perturbation is EvidencePerturbation.REVERSE_FINDINGS:
        perturbed_findings.reverse()
    elif perturbation is EvidencePerturbation.REVERSE_TRACES:
        perturbed_traces.reverse()
    elif perturbation is EvidencePerturbation.ROTATE_EQUIVALENT_EVIDENCE:
        if perturbed_findings:
            perturbed_findings = perturbed_findings[1:] + perturbed_findings[:1]
        if perturbed_traces:
            perturbed_traces = perturbed_traces[1:] + perturbed_traces[:1]
    return perturbed_findings, perturbed_traces


def _result_signature(result: GateResult) -> str:
    payload = {
        "decision": result.decision.value,
        "finding_ids": sorted(item.finding_id for item in result.findings),
        "work_orders": sorted(
            (
                item.action,
                tuple(sorted(item.reason_codes)),
                tuple(sorted(item.sample_ids)),
            )
            for item in result.work_orders
        ),
        "rule_checks": sorted(
            (item.check_id, item.status.value) for item in result.rule_checks
        ),
    }
    return hashlib.sha256(canonical_json_bytes(payload)).hexdigest()


def _review_cost_units(
    architecture: ArchitectureMode,
    findings: list[Finding],
    traces: list[ToolTrace],
    metrics: dict[str, int | float | str],
) -> tuple[int, int]:
    review_count = {
        ArchitectureMode.TRADITIONAL: 0,
        ArchitectureMode.SINGLE_AGENT: 1,
        ArchitectureMode.MULTI_AGENT: 6,
    }[architecture]
    evidence_bytes = len(
        canonical_json_bytes(
            {
                "findings": findings,
                "traces": traces,
                "metrics": metrics,
            }
        )
    )
    return review_count, math.ceil(evidence_bytes / 4) * review_count


def _one_run(
    *,
    architecture: ArchitectureMode,
    perturbation: EvidencePerturbation,
    batch_root: Path,
    manifest: BatchManifest,
    contract: BatchContract,
    truth: CorruptionManifest,
    repeat: int,
) -> dict[str, Any]:
    started = time.perf_counter()
    if architecture in {
        ArchitectureMode.TRADITIONAL,
        ArchitectureMode.MULTI_AGENT,
    }:
        findings, traces, metrics = _parallel_tools(batch_root, manifest, contract)
    else:
        findings, traces, metrics = run_all_tools(
            batch_root,
            manifest,
            contract,
            include_optional_tools=True,
        )
    findings, traces = _perturb(findings, traces, perturbation)
    if architecture is ArchitectureMode.TRADITIONAL:
        council = build_traditional_pipeline_receipt()
    elif architecture is ArchitectureMode.SINGLE_AGENT:
        council = build_single_agent_review(findings, traces, metrics)
    else:
        council = build_council(findings, traces, metrics)
    digest = compute_batch_digest(batch_root, manifest, contract)
    result = apply_policy(
        manifest,
        contract,
        findings,
        traces,
        metrics,
        council,
        scenario_profile=ScenarioProfile.INDUSTRIAL,
        input_sha256=digest,
        run_id=(
            f"benchmark-{architecture.value}-{manifest.seed}-{repeat}-"
            f"{perturbation.value}"
        ),
    )
    evaluation = evaluate_gate(truth, result)
    latency_ms = (time.perf_counter() - started) * 1000
    review_count, token_units = _review_cost_units(
        architecture, findings, traces, metrics
    )
    unsafe_release = bool(
        result.decision is GateDecision.PASS and evaluation.false_negative_count
    )
    return {
        "architecture": architecture.value,
        "seed": manifest.seed,
        "repeat": repeat,
        "perturbation": perturbation.value,
        "decision": result.decision.value,
        "result_signature": _result_signature(result),
        "unsafe_release": unsafe_release,
        "task_success": not unsafe_release
        and all(trace.status == "ok" for trace in traces),
        "precision": evaluation.precision,
        "recall": evaluation.recall,
        "f1": evaluation.f1,
        "false_negative_count": evaluation.false_negative_count,
        "latency_ms": round(latency_ms, 3),
        "tool_call_count": len(traces),
        "agent_review_count": review_count,
        "estimated_input_token_units": token_units,
        "actual_model_call_count": 0,
        "actual_model_cost_cny": 0.0,
        "relative_compute_units": len(traces) + review_count,
        "finding_count": len(findings),
        "work_order_count": len(result.work_orders),
    }


def _summaries(records: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for record in records:
        grouped[str(record["architecture"])].append(record)
    summaries: dict[str, dict[str, Any]] = {}
    for architecture, items in sorted(grouped.items()):
        latencies = [float(item["latency_ms"]) for item in items]
        stable = 0
        comparable = 0
        by_trial: dict[tuple[int, int], list[dict[str, Any]]] = defaultdict(list)
        for item in items:
            by_trial[(int(item["seed"]), int(item["repeat"]))].append(item)
        for trial_items in by_trial.values():
            canonical = next(
                item
                for item in trial_items
                if item["perturbation"] == EvidencePerturbation.CANONICAL.value
            )
            for item in trial_items:
                comparable += 1
                stable += int(item["result_signature"] == canonical["result_signature"])
        summaries[architecture] = {
            "record_count": len(items),
            "error_release_rate": sum(bool(item["unsafe_release"]) for item in items)
            / len(items),
            "task_success_rate": sum(bool(item["task_success"]) for item in items)
            / len(items),
            "perturbation_stability_rate": stable / comparable,
            "mean_precision": statistics.fmean(
                float(item["precision"]) for item in items
            ),
            "mean_recall": statistics.fmean(float(item["recall"]) for item in items),
            "mean_f1": statistics.fmean(float(item["f1"]) for item in items),
            "latency_ms_mean": round(statistics.fmean(latencies), 3),
            "latency_ms_p50": round(_percentile(latencies, 0.5), 3),
            "latency_ms_p95": round(_percentile(latencies, 0.95), 3),
            "mean_tool_calls": statistics.fmean(
                int(item["tool_call_count"]) for item in items
            ),
            "mean_agent_reviews": statistics.fmean(
                int(item["agent_review_count"]) for item in items
            ),
            "mean_relative_compute_units": statistics.fmean(
                int(item["relative_compute_units"]) for item in items
            ),
            "mean_estimated_input_token_units": statistics.fmean(
                int(item["estimated_input_token_units"]) for item in items
            ),
            "actual_model_cost_cny": 0.0,
        }
    return summaries


def run_architecture_benchmark(
    output: str | Path,
    *,
    seeds: Sequence[int] = (20260809, 20260810, 20260811, 20260812),
    repeats: int = 1,
) -> ArchitectureBenchmarkRun:
    """Execute and persist the frozen same-protocol architecture comparison."""

    if not seeds or len(set(seeds)) != len(seeds) or any(seed < 0 for seed in seeds):
        raise ValueError(
            "seeds must be a non-empty unique sequence of non-negative ints"
        )
    if repeats < 1 or repeats > 20:
        raise ValueError("repeats must be between 1 and 20")
    output_path = Path(output).expanduser().resolve()
    output_path.parent.mkdir(parents=True, exist_ok=True)
    configured_fixture_root = os.environ.get(
        "VISIONDATA_BENCHMARK_FIXTURE_ROOT", ""
    ).strip()
    fixture_root = (
        Path(configured_fixture_root).expanduser().resolve() / output_path.stem
        if configured_fixture_root
        else output_path.parent / f".{output_path.stem}-fixtures"
    )
    fixture_root.mkdir(parents=True, exist_ok=True)
    records: list[dict[str, Any]] = []
    contract = BatchContract()
    architecture_order = list(ArchitectureMode)
    perturbation_order = list(EvidencePerturbation)
    for seed in seeds:
        paths = generate_demo_dataset(fixture_root / f"seed-{seed}", seed=seed)
        manifest = BatchManifest.model_validate_json(
            paths["batch_manifest"].read_text(encoding="utf-8")
        )
        truth = CorruptionManifest.model_validate_json(
            paths["corruption_manifest"].read_text(encoding="utf-8")
        )
        # Warm both execution shapes before recording latency.  The first image
        # decode and module path on Windows is otherwise systematically charged
        # to whichever architecture happens to run first.
        run_all_tools(
            paths["batch_root"],
            manifest,
            contract,
            include_optional_tools=True,
        )
        _parallel_tools(paths["batch_root"], manifest, contract)
        for repeat in range(repeats):
            for perturbation_index, perturbation in enumerate(perturbation_order):
                offset = (seed + repeat + perturbation_index) % len(architecture_order)
                balanced_architectures = (
                    architecture_order[offset:] + architecture_order[:offset]
                )
                for architecture in balanced_architectures:
                    records.append(
                        _one_run(
                            architecture=architecture,
                            perturbation=perturbation,
                            batch_root=paths["batch_root"],
                            manifest=manifest,
                            contract=contract,
                            truth=truth,
                            repeat=repeat,
                        )
                    )
    summaries = _summaries(records)
    traditional = summaries[ArchitectureMode.TRADITIONAL.value]
    multi = summaries[ArchitectureMode.MULTI_AGENT.value]
    quality_gain = float(multi["mean_f1"]) - float(traditional["mean_f1"])
    success_gain = float(multi["task_success_rate"]) - float(
        traditional["task_success_rate"]
    )
    stability_gain = float(multi["perturbation_stability_rate"]) - float(
        traditional["perturbation_stability_rate"]
    )
    necessity_supported = any(
        gain > 1e-9 for gain in (quality_gain, success_gain, stability_gain)
    )
    payload = {
        "schema_version": "visiondata-gate.architecture-benchmark.v1",
        "status": "PASS",
        "protocol": {
            "same_inputs": True,
            "same_batch_contract": True,
            "same_tool_implementations": True,
            "same_policy_judge": True,
            "orchestration": {
                "traditional_pipeline": "parallel deterministic DAG, no Agent review",
                "single_agent": "one controller executes tools sequentially, one advisory review",
                "multi_agent": "parallel evidence Workers, six advisory role reviews",
            },
            "scenario_profile": ScenarioProfile.INDUSTRIAL.value,
            "architectures": [item.value for item in ArchitectureMode],
            "perturbations": [item.value for item in EvidencePerturbation],
            "seeds": list(seeds),
            "repeats": repeats,
            "latency_method": (
                "per-seed sequential and parallel warm-up, then deterministic rotated "
                "architecture order for every repeat and perturbation"
            ),
            "latency_boundary": (
                "Wall-clock values are local single-machine observations, not a "
                "production SLO or cross-host throughput benchmark."
            ),
            "cost_boundary": (
                "All paths use local deterministic reviewers, so actual model calls and "
                "monetary model cost are zero. Token units are an input-size proxy, not billing."
            ),
        },
        "environment": {
            "python": platform.python_version(),
            "platform": platform.platform(),
        },
        "summaries": summaries,
        "multi_agent_vs_traditional": {
            "mean_f1_gain": quality_gain,
            "task_success_rate_gain": success_gain,
            "perturbation_stability_gain": stability_gain,
            "fixed_sop_multi_agent_necessity_supported": necessity_supported,
            "interpretation": (
                "Multi-Agent improved at least one frozen quality/stability metric."
                if necessity_supported
                else "No quality, task-success, or perturbation-stability gain was measured; "
                "the fixed SOP alone does not justify Multi-Agent."
            ),
        },
        "records": records,
        "claim_boundary": (
            "This is a deterministic synthetic benchmark of orchestration choices. It is "
            "not customer ROI, production SLO, external-model cost, or industrial validation."
        ),
    }
    digest = write_canonical_json(output_path, payload)
    return ArchitectureBenchmarkRun(output_path, digest, payload)


__all__ = [
    "ArchitectureBenchmarkRun",
    "ArchitectureMode",
    "EvidencePerturbation",
    "run_architecture_benchmark",
]
