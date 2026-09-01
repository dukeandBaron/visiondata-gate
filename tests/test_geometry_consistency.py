from __future__ import annotations

import json
from pathlib import Path

from PIL import Image

from visiondata_gate.contracts import (
    BatchContract,
    BatchManifest,
    CoverageContract,
    SampleRecord,
)
from visiondata_gate.evidence import write_canonical_json
from visiondata_gate.geometry_consistency import (
    GeometryEvidenceBundle,
    GeometryThresholds,
    build_geometry_followup_plan,
    run_geometry_consistency,
    run_geometry_gate,
)
from visiondata_gate.pipeline import compute_batch_digest
from visiondata_gate.tools import validate_tool_contract_trace


def _fixture(tmp_path: Path) -> tuple[Path, BatchManifest, BatchContract, str]:
    root = tmp_path / "batch"
    root.mkdir()
    samples = []
    for index in range(2):
        relative = f"images/view-{index}.png"
        path = root / relative
        path.parent.mkdir(exist_ok=True)
        image = Image.new("RGB", (128, 128), color=(80 + index * 20, 110, 140))
        image.save(path)
        samples.append(
            SampleRecord(
                sample_id=f"sample-{index}",
                relative_path=relative,
                split="train",
                category="part",
                view="front",
                condition="bright",
            )
        )
    manifest = BatchManifest(batch_id="geometry-fixture", seed=7, samples=samples)
    contract = BatchContract(
        required_splits=["train"],
        annotations_required=False,
        coverage=CoverageContract(
            categories=["part"],
            views=["front"],
            conditions=["bright"],
            splits=["train"],
        ),
    )
    return root, manifest, contract, compute_batch_digest(root, manifest, contract)


def _bundle(batch_sha256: str, *, bad: bool = False) -> GeometryEvidenceBundle:
    return GeometryEvidenceBundle(
        backend="vggt",
        backend_version="fixture-v1",
        input_batch_sha256=batch_sha256,
        image_count=2,
        views=[
            {
                "sample_id": "sample-0",
                "width": 128,
                "height": 128,
                "depth_width": 64 if bad else 128,
                "depth_height": 128,
                "depth_valid_fraction": 0.91,
                "depth_outlier_fraction": 0.11 if bad else 0.02,
                "depth_confidence_mean": 0.8,
                "reprojection_error_px": 4.0 if bad else 1.2,
                "track_count": 20,
                "track_visibility_fraction": 0.8,
            },
            {
                "sample_id": "sample-1",
                "width": 128,
                "height": 128,
                "depth_width": 128,
                "depth_height": 128,
                "depth_valid_fraction": 0.95,
                "depth_outlier_fraction": 0.01,
                "depth_confidence_mean": 0.82,
                "reprojection_error_px": 1.0,
                "track_count": 24,
                "track_visibility_fraction": 0.82,
            },
        ],
    )


def test_valid_geometry_receipt_is_repeatable_and_contract_bound(
    tmp_path: Path,
) -> None:
    root, manifest, contract, batch_sha256 = _fixture(tmp_path)
    first = run_geometry_consistency(root, manifest, contract, _bundle(batch_sha256))
    second = run_geometry_consistency(root, manifest, contract, _bundle(batch_sha256))

    assert first.status == "PASS_LOCAL"
    assert first.findings == ()
    assert first.trace.status == "ok"
    assert first.trace.result_sha256 == second.trace.result_sha256
    assert first.metrics["geometry_view_coverage"] == 1.0
    assert (
        validate_tool_contract_trace(
            first.trace, include_optional=True, include_geometry=True
        )
        is None
    )


def test_geometry_failures_emit_actionable_findings_and_followups(
    tmp_path: Path,
) -> None:
    root, manifest, contract, batch_sha256 = _fixture(tmp_path)
    run = run_geometry_consistency(
        root,
        manifest,
        contract,
        _bundle(batch_sha256, bad=True),
        thresholds=GeometryThresholds(max_reprojection_error_px=2.0),
    )

    codes = {finding.code for finding in run.findings}
    assert {
        "GEOMETRY_DEPTH_SHAPE_MISMATCH",
        "GEOMETRY_DEPTH_OUTLIER_HIGH",
        "GEOMETRY_REPROJECTION_ERROR_HIGH",
    } <= codes
    plan = build_geometry_followup_plan(run.findings)
    assert plan["mode"] == "evidence_triggered_plan"
    assert "depth-alignment-reconciliation" in plan["branch_types"]
    assert all(task["status"] == "planned" for task in plan["dynamic_tasks"])


def test_hash_mismatch_is_unsupported_and_final_gate_defers(tmp_path: Path) -> None:
    root, manifest, contract, _ = _fixture(tmp_path)
    evidence = _bundle("0" * 64)
    run = run_geometry_consistency(root, manifest, contract, evidence)

    assert run.status == "FINDINGS"
    assert any(item.code == "GEOMETRY_INPUT_HASH_MISMATCH" for item in run.findings)
    assert any(item.evidence_status.value == "unsupported" for item in run.findings)
    merged = run_geometry_gate(
        root,
        manifest,
        contract,
        evidence,
        tmp_path / "evidence" / "hash-mismatch",
    )
    assert merged.gate_result.decision.value == "DEFER"
    receipt = json.loads(merged.receipt_path.read_text(encoding="utf-8"))
    assert receipt["geometry_finding_count"] >= 1
    assert receipt["geometry_backend"] == "vggt"


def test_missing_optional_backend_is_not_tested_without_changing_base_gate(
    tmp_path: Path,
) -> None:
    root, manifest, contract, _ = _fixture(tmp_path)
    run = run_geometry_consistency(root, manifest, contract, None, required=False)
    assert run.status == "OPTIONAL_BACKEND_NOT_CONNECTED"
    assert run.trace.status == "skipped"

    merged = run_geometry_gate(
        root,
        manifest,
        contract,
        None,
        tmp_path / "evidence" / "optional",
        required=False,
    )
    assert merged.geometry.status == "OPTIONAL_BACKEND_NOT_CONNECTED"
    assert merged.gate_result.run_id == merged.base_gate_result.run_id
    receipt = json.loads(merged.receipt_path.read_text(encoding="utf-8"))
    assert receipt["status"] == "OPTIONAL_BACKEND_NOT_CONNECTED"


def test_geometry_receipt_can_be_written_as_portable_json(tmp_path: Path) -> None:
    root, manifest, contract, batch_sha256 = _fixture(tmp_path)
    path = tmp_path / "geometry.json"
    write_canonical_json(path, _bundle(batch_sha256))
    run = run_geometry_consistency(root, manifest, contract, path)
    assert run.evidence_path == path.resolve()
    assert run.evidence_sha256 is not None
    assert run.status == "PASS_LOCAL"
