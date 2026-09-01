from __future__ import annotations

import json
import hashlib
from pathlib import Path

import pytest

from visiondata_gate.cli import main
from visiondata_gate.dynamic_benchmark import (
    DynamicBenchmarkValidationError,
    load_dynamic_benchmark_report,
    run_dynamic_benchmark,
)
from visiondata_gate.evidence import canonical_json_bytes


def test_dynamic_benchmark_has_fixed_denominators_and_honest_comparison(
    tmp_path: Path,
) -> None:
    run = run_dynamic_benchmark(tmp_path / "dynamic_benchmark.json", repeats=2)
    assert run.report_path.exists()
    assert len(run.report_sha256) == 64
    report = json.loads(run.report_path.read_text(encoding="utf-8"))
    assert report["status"] == "PASS"
    assert report["fixed_denominators"] == {
        "fixture_count": 24,
        "positive_fixture_count": 12,
        "negative_fixture_count": 12,
        "architecture_count": 4,
        "branch_label_count_per_architecture": 72,
        "record_count": 192,
    }
    summaries = report["summaries"]
    assert set(summaries) == {
        "traditional_pipeline",
        "single_agent",
        "fixed_multi_agent",
        "dynamic_leader",
    }
    traditional = summaries["traditional_pipeline"]
    single = summaries["single_agent"]
    fixed = summaries["fixed_multi_agent"]
    dynamic = summaries["dynamic_leader"]
    assert traditional["dynamic_trigger_precision"] is None
    assert traditional["dynamic_trigger_precision_status"] == (
        "NOT_DEFINED_NO_PREDICTED_POSITIVES"
    )
    assert traditional["dynamic_trigger_recall"] == 0.0
    assert traditional["incorrect_release_rate"] == 1.0
    assert traditional["task_success_rate"] == 0.5
    assert single["dynamic_trigger_precision"] == 1.0
    assert single["dynamic_trigger_recall"] == 1.0
    assert single["incorrect_release_rate"] == 0.0
    assert single["task_success_rate"] == 1.0
    assert dynamic["dynamic_trigger_precision"] == 1.0
    assert dynamic["dynamic_trigger_recall"] == 1.0
    assert dynamic["recovery_success_rate"] == 1.0
    assert dynamic["evidence_coverage_rate"] == 1.0
    assert dynamic["unresolved_conflict_count"] == 0
    assert dynamic["redundant_or_duplicate_tool_call_count"] == 0
    assert fixed["dynamic_trigger_recall"] == 1.0
    assert fixed["dynamic_trigger_precision"] < 1.0
    assert fixed["redundant_or_duplicate_tool_call_count"] > 0
    assert report["comparisons"]["single_agent_and_dynamic_leader_quality_tied"]
    assert report["comparisons"][
        "dynamic_leader_reduces_redundant_calls_vs_fixed_multi"
    ]
    assert report["actual_model_call_count"] == 0
    assert report["actual_model_token_count"] == 0
    assert report["model_execution_status"] == "NOT_CONNECTED"
    assert all(item["semantic_repeat_stability"] for item in summaries.values())
    assert load_dynamic_benchmark_report(run.report_path) == report


def test_dynamic_benchmark_loader_rejects_tampered_metrics_and_grid(
    tmp_path: Path,
) -> None:
    run = run_dynamic_benchmark(tmp_path / "dynamic_benchmark.json", repeats=1)
    report = json.loads(run.report_path.read_text(encoding="utf-8"))
    report["summaries"]["dynamic_leader"]["dynamic_trigger_precision"] = 0.5
    run.report_path.write_text(json.dumps(report, ensure_ascii=False), encoding="utf-8")
    with pytest.raises(DynamicBenchmarkValidationError, match="summaries"):
        load_dynamic_benchmark_report(run.report_path)

    report = run.report
    report["records"][0]["fixture_id"] = "UNKNOWN"
    report["records_sha256"] = hashlib.sha256(
        canonical_json_bytes(report["records"])
    ).hexdigest()
    run.report_path.write_text(json.dumps(report, ensure_ascii=False), encoding="utf-8")
    with pytest.raises(DynamicBenchmarkValidationError, match="record grid"):
        load_dynamic_benchmark_report(run.report_path)


def test_dynamic_benchmark_loader_rejects_self_rehashed_labels_and_semantics(
    tmp_path: Path,
) -> None:
    run = run_dynamic_benchmark(tmp_path / "dynamic_benchmark.json", repeats=1)
    report = json.loads(run.report_path.read_text(encoding="utf-8"))
    report["fixture_manifest"][0]["label"] = "negative"
    report["fixture_manifest_sha256"] = hashlib.sha256(
        canonical_json_bytes(report["fixture_manifest"])
    ).hexdigest()
    run.report_path.write_text(json.dumps(report, ensure_ascii=False), encoding="utf-8")
    with pytest.raises(DynamicBenchmarkValidationError, match="frozen labels"):
        load_dynamic_benchmark_report(run.report_path)

    report = run.report
    report["records"][0]["output_digests"] = ["0" * 64]
    report["records_sha256"] = hashlib.sha256(
        canonical_json_bytes(report["records"])
    ).hexdigest()
    run.report_path.write_text(json.dumps(report, ensure_ascii=False), encoding="utf-8")
    with pytest.raises(DynamicBenchmarkValidationError, match="semantic mismatch"):
        load_dynamic_benchmark_report(run.report_path)


def test_dynamic_benchmark_rejects_invalid_protocol(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="repeats"):
        run_dynamic_benchmark(tmp_path / "bad.json", repeats=0)
    with pytest.raises(ValueError, match="tool_budget"):
        run_dynamic_benchmark(tmp_path / "bad.json", tool_budget=4)
    with pytest.raises(ValueError, match="timeout_ms"):
        run_dynamic_benchmark(tmp_path / "bad.json", timeout_ms=0)


def test_dynamic_benchmark_cli(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    output = tmp_path / "dynamic.json"
    assert (
        main(
            [
                "dynamic-benchmark",
                "--output",
                str(output),
                "--repeats",
                "1",
            ]
        )
        == 0
    )
    payload = json.loads(capsys.readouterr().out)
    assert payload["status"] == "PASS"
    assert payload["report"] == str(output.resolve())
    assert payload["fixed_denominators"]["record_count"] == 96
