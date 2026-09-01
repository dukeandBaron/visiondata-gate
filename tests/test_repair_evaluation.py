from __future__ import annotations

from pathlib import Path

import pytest

from visiondata_gate.agents import build_council
from visiondata_gate.contracts import (
    BatchContract,
    BatchManifest,
    CorruptionManifest,
    Finding,
    GateDecision,
    SampleRecord,
    Severity,
    ToolTrace,
    TruthIssue,
    WorkOrder,
)
from visiondata_gate.evaluation import evaluate_gate
from visiondata_gate.policy import apply_policy
from visiondata_gate import repair as repair_module
from visiondata_gate.repair import RepairError, simulate_repair


SHA256_ZERO = "0" * 64
SHA256_ONE = "1" * 64


def _sample(
    sample_id: str,
    image_path: str,
    annotation_path: str,
    *,
    source_sample_id: str | None = None,
) -> SampleRecord:
    return SampleRecord(
        sample_id=sample_id,
        relative_path=image_path,
        annotation_path=annotation_path,
        split="train",
        category="bearing",
        view="front",
        condition="bright",
        source_sample_id=source_sample_id,
    )


def _write(path: Path, content: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(content)


def _trace() -> ToolTrace:
    return ToolTrace(
        sequence=1,
        tool="fixture",
        status="ok",
        input_sha256=SHA256_ZERO,
        result_sha256=SHA256_ONE,
    )


def _finding(code: str, sample_id: str, severity: Severity) -> Finding:
    return Finding(
        finding_id=f"finding-{code}-{sample_id}",
        code=code,
        severity=severity,
        tool="fixture",
        sample_ids=[sample_id],
        summary=f"Detected {code}",
        recommended_action="recapture" if "SHARPNESS" in code else "repartition",
    )


def _gate(findings: list[Finding], decision: GateDecision | None = None):
    manifest = BatchManifest(
        batch_id="dirty-batch",
        seed=7,
        samples=[_sample("sample-1", "images/1.png", "masks/1.png")],
    )
    traces = [_trace()]
    council = build_council(findings, traces, {})
    result = apply_policy(manifest, BatchContract(), findings, traces, {}, council)
    if decision is not None:
        result = result.model_copy(update={"decision": decision})
    return result


def test_simulated_repair_replaces_sample_and_annotation_from_reserve(
    tmp_path: Path,
) -> None:
    source_root = tmp_path / "dirty-batch"
    _write(source_root / "images/1.png", b"bad-image")
    _write(source_root / "masks/1.png", b"bad-mask")
    _write(source_root / "corruption_manifest.json", b"hidden truth")
    manifest = BatchManifest(
        batch_id="dirty-batch",
        seed=7,
        samples=[_sample("sample-1", "images/1.png", "masks/1.png")],
    )
    (source_root / "manifest.json").write_text(
        manifest.model_dump_json(indent=2), encoding="utf-8"
    )

    reserve_root = tmp_path / "reserve"
    _write(reserve_root / "images/r1.png", b"good-image")
    _write(reserve_root / "masks/r1.png", b"good-mask")
    reserve = BatchManifest(
        batch_id="reserve-batch",
        seed=8,
        samples=[
            _sample(
                "reserve-1",
                "images/r1.png",
                "masks/r1.png",
                source_sample_id="sample-1",
            )
        ],
    )
    reserve_path = reserve_root / "reserve_manifest.json"
    reserve_path.write_text(reserve.model_dump_json(indent=2), encoding="utf-8")
    order = WorkOrder(
        work_order_id="wo-recapture-1",
        action="RECAPTURE",
        priority=Severity.HIGH,
        reason_codes=["LOW_SHARPNESS"],
        sample_ids=["sample-1"],
    )

    result = simulate_repair(
        source_root,
        manifest,
        reserve_path,
        [order],
        output_root=tmp_path / "repaired-batch",
    )

    assert (result.output_root / "images/1.png").read_bytes() == b"good-image"
    assert (result.output_root / "masks/1.png").read_bytes() == b"good-mask"
    assert (source_root / "images/1.png").read_bytes() == b"bad-image"
    assert not (result.output_root / "corruption_manifest.json").exists()
    assert result.manifest.samples[0].sample_id == "sample-1"
    assert result.manifest.samples[0].source_sample_id == "reserve-1"
    assert result.replacement_map == {"sample-1": "reserve-1"}
    assert result.completed_work_orders[0].status == "simulated_complete"
    loaded = BatchManifest.model_validate_json(
        result.manifest_path.read_text(encoding="utf-8")
    )
    assert loaded == result.manifest


def test_simulated_repair_fails_closed_without_matching_reserve(
    tmp_path: Path,
) -> None:
    source_root = tmp_path / "dirty-batch"
    _write(source_root / "images/1.png", b"bad-image")
    manifest = BatchManifest(
        batch_id="dirty-batch",
        seed=7,
        samples=[_sample("sample-1", "images/1.png", "masks/1.png")],
    )
    reserve_root = tmp_path / "reserve"
    reserve_root.mkdir()
    reserve = BatchManifest(
        batch_id="reserve-batch",
        seed=8,
        samples=[
            _sample(
                "reserve-other",
                "images/other.png",
                "masks/other.png",
                source_sample_id="different-target",
            )
        ],
    )
    reserve_path = reserve_root / "reserve_manifest.json"
    reserve_path.write_text(reserve.model_dump_json(), encoding="utf-8")
    order = WorkOrder(
        work_order_id="wo-recapture-1",
        action="RECAPTURE",
        priority=Severity.HIGH,
        reason_codes=["LOW_SHARPNESS"],
        sample_ids=["sample-1"],
    )

    with pytest.raises(RepairError, match="reserve"):
        simulate_repair(
            source_root,
            manifest,
            reserve_path,
            [order],
            output_root=tmp_path / "repaired-batch",
        )


def test_simulated_repair_does_not_overwrite_existing_output(
    tmp_path: Path,
) -> None:
    source_root = tmp_path / "dirty-batch"
    _write(source_root / "images/1.png", b"bad-image")
    _write(source_root / "masks/1.png", b"bad-mask")
    manifest = BatchManifest(
        batch_id="dirty-batch",
        seed=7,
        samples=[_sample("sample-1", "images/1.png", "masks/1.png")],
    )
    reserve_root = tmp_path / "reserve"
    _write(reserve_root / "images/r1.png", b"good-image")
    _write(reserve_root / "masks/r1.png", b"good-mask")
    reserve = BatchManifest(
        batch_id="reserve-batch",
        seed=8,
        samples=[
            _sample(
                "reserve-1",
                "images/r1.png",
                "masks/r1.png",
                source_sample_id="sample-1",
            )
        ],
    )
    reserve_path = reserve_root / "reserve_manifest.json"
    reserve_path.write_text(reserve.model_dump_json(), encoding="utf-8")
    output_root = tmp_path / "repaired-batch"
    _write(output_root / "sentinel.txt", b"preserve-me")
    order = WorkOrder(
        work_order_id="wo-recapture-1",
        action="RECAPTURE",
        priority=Severity.HIGH,
        reason_codes=["LOW_SHARPNESS"],
        sample_ids=["sample-1"],
    )

    with pytest.raises(RepairError, match="already exists"):
        simulate_repair(
            source_root,
            manifest,
            reserve_path,
            [order],
            output_root=output_root,
        )

    assert (output_root / "sentinel.txt").read_bytes() == b"preserve-me"


def test_windows_transient_publish_denial_is_retried_without_partial_output(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    staging = tmp_path / ".staging"
    staging.mkdir()
    (staging / "payload.txt").write_text("complete", encoding="utf-8")
    destination = tmp_path / "published"
    real_rename = repair_module.os.rename
    calls = 0

    def deny_once(source: Path, target: Path) -> None:
        nonlocal calls
        calls += 1
        if calls == 1:
            error = PermissionError(13, "transient scanner lock", source, target)
            error.winerror = 5
            raise error
        real_rename(source, target)

    monkeypatch.setattr(repair_module.os, "name", "nt")
    monkeypatch.setattr(repair_module.os, "rename", deny_once)
    monkeypatch.setattr(repair_module.time, "sleep", lambda _seconds: None)

    repair_module._publish_staging_directory(staging, destination)

    assert calls == 2
    assert not staging.exists()
    assert (destination / "payload.txt").read_text(encoding="utf-8") == "complete"


def test_publish_denial_remains_fail_closed_after_bounded_retries(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    staging = tmp_path / ".staging"
    staging.mkdir()
    destination = tmp_path / "published"
    calls = 0

    def always_deny(source: Path, target: Path) -> None:
        nonlocal calls
        calls += 1
        error = PermissionError(13, "persistent scanner lock", source, target)
        error.winerror = 5
        raise error

    monkeypatch.setattr(repair_module.os, "name", "nt")
    monkeypatch.setattr(repair_module.os, "rename", always_deny)
    monkeypatch.setattr(repair_module.time, "sleep", lambda _seconds: None)

    with pytest.raises(RepairError, match="bounded Windows retries"):
        repair_module._publish_staging_directory(staging, destination)

    assert calls == 5
    assert staging.is_dir()
    assert not destination.exists()


def test_simulated_repair_rejects_symlinked_reserve_payload(
    tmp_path: Path,
) -> None:
    source_root = tmp_path / "dirty-batch"
    _write(source_root / "images/1.png", b"bad-image")
    _write(source_root / "masks/1.png", b"bad-mask")
    manifest = BatchManifest(
        batch_id="dirty-batch",
        seed=7,
        samples=[_sample("sample-1", "images/1.png", "masks/1.png")],
    )
    reserve_root = tmp_path / "reserve"
    reserve_image = reserve_root / "images/r1.png"
    reserve_image.parent.mkdir(parents=True)
    outside = tmp_path / "outside.png"
    outside.write_bytes(b"outside-image")
    try:
        reserve_image.symlink_to(outside)
    except OSError:
        pytest.skip("file symlinks are unavailable in this Windows environment")
    _write(reserve_root / "masks/r1.png", b"good-mask")
    reserve = BatchManifest(
        batch_id="reserve-batch",
        seed=8,
        samples=[
            _sample(
                "reserve-1",
                "images/r1.png",
                "masks/r1.png",
                source_sample_id="sample-1",
            )
        ],
    )
    reserve_path = reserve_root / "reserve_manifest.json"
    reserve_path.write_text(reserve.model_dump_json(), encoding="utf-8")
    order = WorkOrder(
        work_order_id="wo-recapture-1",
        action="RECAPTURE",
        priority=Severity.HIGH,
        reason_codes=["LOW_SHARPNESS"],
        sample_ids=["sample-1"],
    )

    with pytest.raises(RepairError, match="symlink"):
        simulate_repair(
            source_root,
            manifest,
            reserve_path,
            [order],
            output_root=tmp_path / "repaired-batch",
        )


def test_simulated_repair_adds_unlinked_reserve_for_coverage_gap(
    tmp_path: Path,
) -> None:
    source_root = tmp_path / "dirty-batch"
    _write(source_root / "images/1.png", b"existing-image")
    _write(source_root / "masks/1.png", b"existing-mask")
    manifest = BatchManifest(
        batch_id="dirty-batch",
        seed=7,
        samples=[_sample("sample-1", "images/1.png", "masks/1.png")],
    )
    reserve_root = tmp_path / "reserve"
    _write(reserve_root / "images/coverage.png", b"coverage-image")
    _write(reserve_root / "masks/coverage.png", b"coverage-mask")
    reserve = BatchManifest(
        batch_id="reserve-batch",
        seed=8,
        samples=[
            SampleRecord(
                sample_id="reserve-coverage",
                relative_path="images/coverage.png",
                annotation_path="masks/coverage.png",
                split="train",
                category="gear",
                view="side",
                condition="dim",
            )
        ],
    )
    reserve_path = reserve_root / "reserve_manifest.json"
    reserve_path.write_text(reserve.model_dump_json(), encoding="utf-8")
    order = WorkOrder(
        work_order_id="wo-coverage",
        action="RECAPTURE",
        priority=Severity.HIGH,
        reason_codes=["COVERAGE_GAP"],
        replacement_requirements={
            "missing_cells": [
                {
                    "split": "train",
                    "category": "gear",
                    "view": "side",
                    "condition": "dim",
                    "observed_count": 0,
                    "required_count": 1,
                }
            ]
        },
    )

    result = simulate_repair(
        source_root,
        manifest,
        reserve_path,
        [order],
        output_root=tmp_path / "repaired-batch",
    )

    added = result.manifest.samples[-1]
    assert (added.split, added.category, added.view, added.condition) == (
        "train",
        "gear",
        "side",
        "dim",
    )
    assert added.source_sample_id == "reserve-coverage"
    assert (result.output_root / added.relative_path).read_bytes() == b"coverage-image"
    assert result.replacement_map[added.sample_id] == "reserve-coverage"
    assert result.completed_work_orders[0].status == "simulated_complete"


def test_simulated_repair_replaces_only_linked_duplicate_member(
    tmp_path: Path,
) -> None:
    source_root = tmp_path / "dirty-batch"
    _write(source_root / "images/source.png", b"duplicate-image")
    _write(source_root / "masks/source.png", b"source-mask")
    _write(source_root / "images/copy.png", b"duplicate-image")
    _write(source_root / "masks/copy.png", b"copy-mask")
    manifest = BatchManifest(
        batch_id="dirty-batch",
        seed=7,
        samples=[
            _sample("source", "images/source.png", "masks/source.png"),
            _sample("copy", "images/copy.png", "masks/copy.png"),
        ],
    )
    reserve_root = tmp_path / "reserve"
    _write(reserve_root / "images/copy.png", b"replacement-image")
    _write(reserve_root / "masks/copy.png", b"replacement-mask")
    reserve = BatchManifest(
        batch_id="reserve-batch",
        seed=8,
        samples=[
            _sample(
                "reserve-copy",
                "images/copy.png",
                "masks/copy.png",
                source_sample_id="copy",
            )
        ],
    )
    reserve_path = reserve_root / "reserve_manifest.json"
    reserve_path.write_text(reserve.model_dump_json(), encoding="utf-8")
    order = WorkOrder(
        work_order_id="wo-duplicate",
        action="REMOVE_OR_REPARTITION",
        priority=Severity.HIGH,
        reason_codes=["EXACT_DUPLICATE"],
        sample_ids=["copy", "source"],
    )

    result = simulate_repair(
        source_root,
        manifest,
        reserve_path,
        [order],
        output_root=tmp_path / "repaired-batch",
    )

    assert (result.output_root / "images/source.png").read_bytes() == b"duplicate-image"
    assert (result.output_root / "images/copy.png").read_bytes() == b"replacement-image"
    assert result.replacement_map == {"copy": "reserve-copy"}


def test_evaluation_reports_issue_level_errors_and_bad_release() -> None:
    truth = CorruptionManifest(
        seed=7,
        batch_id="dirty-batch",
        reserve_manifest="reserve/reserve_manifest.json",
        issues=[
            TruthIssue(
                issue_id="truth-1",
                code="LOW_SHARPNESS",
                severity=Severity.HIGH,
                sample_ids=["sample-1"],
                detectable_by=["image_quality"],
            ),
            TruthIssue(
                issue_id="truth-2",
                code="CROSS_SPLIT_NEAR_DUPLICATE",
                severity=Severity.CRITICAL,
                sample_ids=["sample-2"],
                detectable_by=["duplicate_leakage"],
            ),
        ],
    )
    findings = [
        _finding("LOW_SHARPNESS", "sample-1", Severity.HIGH),
        _finding("EMPTY_MASK", "sample-3", Severity.MEDIUM),
    ]
    released = _gate(findings, GateDecision.PASS)
    post_repair = _gate([], GateDecision.PASS)

    result = evaluate_gate(truth, released, post_repair)

    assert result.true_positive_count == 1
    assert result.false_positive_count == 1
    assert result.false_negative_count == 1
    assert result.precision == pytest.approx(0.5)
    assert result.recall == pytest.approx(0.5)
    assert result.f1 == pytest.approx(0.5)
    assert result.critical_bad_release_rate == pytest.approx(1.0)
    assert result.work_order_recall == pytest.approx(0.5)
    assert result.post_repair_correct_pass is False


def test_evaluation_accepts_only_fully_covered_post_repair_pass() -> None:
    truth = CorruptionManifest(
        seed=7,
        batch_id="dirty-batch",
        reserve_manifest="reserve/reserve_manifest.json",
        issues=[
            TruthIssue(
                issue_id="truth-1",
                code="LOW_SHARPNESS",
                severity=Severity.HIGH,
                sample_ids=["sample-1"],
            ),
            TruthIssue(
                issue_id="truth-2",
                code="CROSS_SPLIT_NEAR_DUPLICATE",
                severity=Severity.CRITICAL,
                sample_ids=["sample-2"],
            ),
        ],
    )
    findings = [
        _finding("LOW_SHARPNESS", "sample-1", Severity.HIGH),
        _finding("CROSS_SPLIT_NEAR_DUPLICATE", "sample-2", Severity.CRITICAL),
    ]
    dirty_result = _gate(findings)
    post_repair = _gate([], GateDecision.PASS)

    result = evaluate_gate(truth, dirty_result, post_repair)

    assert result.precision == pytest.approx(1.0)
    assert result.recall == pytest.approx(1.0)
    assert result.f1 == pytest.approx(1.0)
    assert result.work_order_recall == pytest.approx(1.0)
    assert result.irrelevant_work_order_rate == pytest.approx(0.0)
    assert result.post_repair_correct_pass is True


def test_evaluation_does_not_reuse_one_finding_for_two_truth_issues() -> None:
    truth = CorruptionManifest(
        seed=7,
        batch_id="dirty-batch",
        reserve_manifest="reserve/reserve_manifest.json",
        issues=[
            TruthIssue(
                issue_id="truth-1",
                code="LOW_SHARPNESS",
                severity=Severity.HIGH,
                sample_ids=["sample-1"],
            ),
            TruthIssue(
                issue_id="truth-2",
                code="LOW_SHARPNESS",
                severity=Severity.HIGH,
                sample_ids=["sample-2"],
            ),
        ],
    )
    finding = _finding("LOW_SHARPNESS", "sample-1", Severity.HIGH).model_copy(
        update={"sample_ids": ["sample-1", "sample-2"]}
    )

    result = evaluate_gate(truth, _gate([finding]))

    assert result.true_positive_count == 1
    assert result.false_positive_count == 0
    assert result.false_negative_count == 1


def test_evaluation_rejects_post_repair_pass_with_failed_tool_trace() -> None:
    truth = CorruptionManifest(
        seed=7,
        batch_id="dirty-batch",
        reserve_manifest="reserve/reserve_manifest.json",
        issues=[
            TruthIssue(
                issue_id="truth-1",
                code="LOW_SHARPNESS",
                severity=Severity.HIGH,
                sample_ids=["sample-1"],
            )
        ],
    )
    dirty_result = _gate([_finding("LOW_SHARPNESS", "sample-1", Severity.HIGH)])
    failed_trace = _trace().model_copy(
        update={"status": "error", "error": "recheck failed"}
    )
    post_repair = _gate([], GateDecision.PASS).model_copy(
        update={"tool_trace": [failed_trace]}
    )

    result = evaluate_gate(truth, dirty_result, post_repair)

    assert result.work_order_recall == pytest.approx(1.0)
    assert result.post_repair_correct_pass is False
