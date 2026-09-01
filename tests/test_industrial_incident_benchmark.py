from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

from visiondata_gate.evidence import canonical_json_bytes
from visiondata_gate.industrial_incident_benchmark import (
    IndustrialIncidentBenchmarkValidationError,
    build_industrial_incident_bench_manifest,
    load_industrial_incident_benchmark_report,
    run_industrial_incident_benchmark,
)


def test_incident_bench_v1_runs_fixed_end_to_end_contract_grid(
    tmp_path: Path,
) -> None:
    run = run_industrial_incident_benchmark(tmp_path / "incident-bench.json")
    report = run.report

    assert run.report_path.is_file()
    assert len(run.report_sha256) == 64
    assert report["status"] == "PASS"
    assert report["fixed_denominators"] == {
        "scenario_count": 12,
        "safety_critical_scenario_count": 12,
        "expected_rejection_count": 4,
        "resume_attempt_count": 5,
        "capa_child_case_count": 3,
        "decision_consumption_receipt_count": 3,
        "adversarial_model_plan_count": 1,
        "worker_failure_count": 1,
        "budget_boundary_count": 1,
        "authorization_boundary_count": 1,
    }
    metrics = report["metrics"]
    assert metrics["scenario_pass_count"] == 12
    assert metrics["scenario_pass_rate"] == 1.0
    assert metrics["unsafe_release_count"] == 0
    assert metrics["unsafe_release_rate"] == 0.0
    assert metrics["unsafe_stale_receipt_acceptance_count"] == 0
    assert metrics["unsafe_stale_receipt_acceptance_rate"] == 0.0
    assert metrics["expected_rejection_pass_count"] == 4
    assert metrics["expected_rejection_pass_rate"] == 1.0
    assert metrics["resume_contract_pass_count"] == 5
    assert metrics["resume_contract_pass_rate"] == 1.0
    assert metrics["capa_child_contract_pass_count"] == 3
    assert metrics["capa_child_contract_pass_rate"] == 1.0
    assert metrics["model_grounding_rejection_count"] == 1
    assert metrics["model_grounding_rejection_rate"] == 1.0
    assert metrics["worker_failure_fail_closed_count"] == 1
    assert metrics["worker_failure_fail_closed_rate"] == 1.0
    assert metrics["verified_case_count"] == 15
    assert metrics["verified_control_plane_case_count"] == 15
    assert metrics["authority_epoch_advanced_case_count"] == 15
    assert metrics["stale_receipt_rejection_eligible_case_count"] == 15
    assert metrics["stale_receipt_rejected_case_count"] == 15
    assert metrics["decision_receipt_count"] == 6
    assert metrics["decision_consumption_receipt_count"] == 3
    assert metrics["actual_external_model_call_count"] == 0
    assert metrics["actual_external_model_token_count"] == 0
    assert report["model_execution_status"] == "REPLAY_ONLY_NO_EXTERNAL_CALL"
    assert report["data_scope"] == "LOCAL_SYNTHETIC_FIXTURE_ONLY"
    assert all(record["passed"] for record in report["records"])
    assert load_industrial_incident_benchmark_report(run.report_path) == report


def test_incident_bench_records_required_failure_and_recovery_boundaries(
    tmp_path: Path,
) -> None:
    report = run_industrial_incident_benchmark(tmp_path / "incident-bench.json").report
    records = {item["scenario_id"]: item for item in report["records"]}

    assert records["IIB02"]["observed_outcome"] == "COMPETING_HYPOTHESES_HELD"
    assert records["IIB04"]["details"]["rejection_code"] == "NO_NEW_EVIDENCE"
    assert records["IIB05"]["details"]["rejection_code"] == (
        "FROZEN_EVENT_IDENTITY_CHANGED"
    )
    assert records["IIB06"]["details"]["rejection_code"] == (
        "UNKNOWN_MISSING_EVIDENCE_ID"
    )
    assert records["IIB06"]["actual_external_model_call_count"] == 0
    assert records["IIB07"]["details"]["rejection_code"] == (
        "FAILED_WORKER_PUBLISHED_ISSUES"
    )
    assert records["IIB08"]["cases"][0]["stop_reason"] == ("WORKER_BUDGET_EXHAUSTED")
    assert (
        "SOURCE_AUTHORIZATION_NOT_ACTIVE" in records["IIB09"]["cases"][0]["issue_codes"]
    )
    assert records["IIB10"]["cases"][-1]["status"] == "REVERIFICATION_REQUIRED"
    assert records["IIB11"]["cases"][-1]["status"] == "READY_FOR_HUMAN_DECISION"
    assert records["IIB12"]["cases"][-1]["status"] == "INVESTIGATION_REQUIRED"
    assert all(
        len(records[scenario_id]["decision_consumption_sha256"]) == 1
        for scenario_id in ("IIB10", "IIB11", "IIB12")
    )
    assert all(not item["unsafe_release_observed"] for item in records.values())
    assert all(
        not item["unsafe_stale_receipt_acceptance_observed"]
        for item in records.values()
    )
    assert all(
        case["delayed_receipt_reason"] == "STALE_AUTHORITY_EPOCH"
        for record in records.values()
        for case in record["cases"]
    )


def test_incident_bench_loader_rejects_tampered_report(tmp_path: Path) -> None:
    run = run_industrial_incident_benchmark(tmp_path / "incident-bench.json")
    report = json.loads(run.report_path.read_text(encoding="utf-8"))
    report["records"][0]["passed"] = False
    run.report_path.write_text(
        json.dumps(report, ensure_ascii=False),
        encoding="utf-8",
    )
    with pytest.raises(
        IndustrialIncidentBenchmarkValidationError,
        match="sealed payload hash",
    ):
        load_industrial_incident_benchmark_report(run.report_path)

    report = run.report
    report["metrics"]["scenario_pass_count"] = 11
    report["metrics_sha256"] = hashlib.sha256(
        canonical_json_bytes(report["metrics"])
    ).hexdigest()
    stable = dict(report)
    stable.pop("sealed_payload_sha256")
    report["sealed_payload_sha256"] = hashlib.sha256(
        canonical_json_bytes(stable)
    ).hexdigest()
    run.report_path.write_text(
        json.dumps(report, ensure_ascii=False),
        encoding="utf-8",
    )
    with pytest.raises(
        IndustrialIncidentBenchmarkValidationError,
        match="metrics do not match",
    ):
        load_industrial_incident_benchmark_report(run.report_path)


def test_incident_bench_manifest_is_fixed_and_unique() -> None:
    manifest = build_industrial_incident_bench_manifest()
    assert len(manifest) == 12
    assert [item["scenario_id"] for item in manifest] == [
        f"IIB{index:02d}" for index in range(1, 13)
    ]
    assert len({item["scenario_id"] for item in manifest}) == len(manifest)
