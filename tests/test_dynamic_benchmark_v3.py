from __future__ import annotations

from copy import deepcopy

import pytest

from visiondata_gate.dynamic_benchmark_v3 import (
    _HASH_DOMAINS,
    _frame_bytes,
    _framed_sha256,
    _seal_report,
    DynamicBenchmarkV3ValidationError,
    build_dynamic_replanning_benchmark_report,
    build_dynamic_replanning_fixtures,
    load_dynamic_replanning_benchmark_report,
    validate_dynamic_replanning_benchmark_report,
    write_dynamic_replanning_benchmark_report,
)
from visiondata_gate.evidence_state_contracts import (
    EvidenceBeliefLedgerV2,
    verify_evidence_belief_ledger_v2,
)
from visiondata_gate.incident_agent_kernel import (
    EvidenceBeliefRevisionReceiptV1,
    verify_evidence_belief_revision_receipt_v1,
)


pytestmark = pytest.mark.tier_benchmark


def _reseal(report: dict[str, object]) -> dict[str, object]:
    payload = {
        key: value for key, value in report.items() if key != "sealed_report_sha256"
    }
    return _seal_report(payload)


def test_dynamic_benchmark_v3_has_fixed_fair_grid_and_metrics() -> None:
    report = build_dynamic_replanning_benchmark_report()

    assert report["status"] == "PASS"
    assert len(report["fixture_manifest"]) == 8
    assert len(report["records"]) == 16
    assert report["protocol"]["tool_budget_per_fixture"] == 3
    assert report["actual_model_call_count"] == 0
    assert report["industrial_effectiveness_status"] == "NOT_EVALUATED"

    fixed = report["metrics"]["fixed_rule_baseline"]
    dynamic = report["metrics"]["dynamic_replanning_contract"]
    assert fixed["correct_terminal_disposition_count"] == 4
    assert dynamic["correct_terminal_disposition_count"] == 8
    assert fixed["unsafe_release_count"] == 0
    assert dynamic["unsafe_release_count"] == 0
    assert fixed["necessary_evidence_fixed_denominator"] == 12
    assert dynamic["necessary_evidence_fixed_denominator"] == 12
    assert fixed["necessary_evidence_covered_count"] == 6
    assert dynamic["necessary_evidence_covered_count"] == 10
    assert fixed["unnecessary_tool_call_count"] == 14
    assert dynamic["unnecessary_tool_call_count"] == 0
    assert fixed["total_tool_call_count"] == 24
    assert dynamic["total_tool_call_count"] == 14
    assert fixed["tool_budget_violation_count"] == 0
    assert dynamic["tool_budget_violation_count"] == 0
    assert fixed["tool_failure_recovery_rate"] == 0.0
    assert dynamic["tool_failure_recovery_rate"] == 1.0
    assert fixed["evidence_changed_next_step_adaptation_rate"] == 0.0
    assert dynamic["evidence_changed_next_step_adaptation_rate"] == 1.0
    assert fixed["indeterminate_correct_rate"] == 1.0
    assert dynamic["indeterminate_correct_rate"] == 1.0
    validate_dynamic_replanning_benchmark_report(report)


def test_dynamic_benchmark_v3_has_two_fixtures_per_required_scenario() -> None:
    fixtures = build_dynamic_replanning_fixtures()

    assert {
        scenario: sum(item["scenario_class"] == scenario for item in fixtures)
        for scenario in {
            "conflicting_evidence",
            "tool_failure",
            "indeterminate",
            "evidence_changed_next_step",
        }
    } == {
        "conflicting_evidence": 2,
        "tool_failure": 2,
        "indeterminate": 2,
        "evidence_changed_next_step": 2,
    }


def test_dynamic_benchmark_v3_shares_inputs_results_and_budget() -> None:
    report = build_dynamic_replanning_benchmark_report()

    for fixture in report["fixture_manifest"]:
        records = [
            item
            for item in report["records"]
            if item["fixture_id"] == fixture["fixture_id"]
        ]
        assert len(records) == 2
        assert {item["tool_budget"] for item in records} == {3}
        assert len({item["shared_initial_input_sha256"] for item in records}) == 1
        assert len({item["shared_tool_result_mapping_sha256"] for item in records}) == 1


def test_dynamic_benchmark_v3_replan_events_use_production_contracts() -> None:
    report = build_dynamic_replanning_benchmark_report()
    dynamic_records = [
        item
        for item in report["records"]
        if item["strategy"] == "dynamic_replanning_contract"
    ]
    events = [event for record in dynamic_records for event in record["replan_events"]]

    assert len(events) == 6
    for event in events:
        ledger = EvidenceBeliefLedgerV2.model_validate(event["source_ledger"])
        revision = EvidenceBeliefRevisionReceiptV1.model_validate(
            event["revision_receipt"]
        )
        verify_evidence_belief_ledger_v2(ledger)
        verify_evidence_belief_revision_receipt_v1(revision)
        assert revision.source_ledger_sha256 == ledger.ledger_sha256
        assert revision.evidence_bundle_changed is True
        assert revision.fresh_replan_required is True
        assert revision.disposition == "STALE_REPLAN_REQUIRED"


@pytest.mark.parametrize("tool_budget", [True, 0, 2, 4])
def test_dynamic_benchmark_v3_rejects_non_frozen_tool_budget(
    tool_budget: int,
) -> None:
    with pytest.raises(DynamicBenchmarkV3ValidationError, match="frozen tool budget 3"):
        build_dynamic_replanning_benchmark_report(tool_budget=tool_budget)


def test_dynamic_benchmark_v3_length_framing_prevents_boundary_ambiguity() -> None:
    assert _frame_bytes("ab", "c") != _frame_bytes("a", "bc")
    assert _framed_sha256("ab", "c") != _framed_sha256("a", "bc")
    assert _framed_sha256("domain-a", {"x": 1}) != _framed_sha256("domain-b", {"x": 1})


def test_dynamic_benchmark_v3_rejects_self_rehashed_fixture_drift() -> None:
    tampered = deepcopy(build_dynamic_replanning_benchmark_report())
    tampered["fixture_manifest"][0]["summary"] = "forged fixture"
    tampered["fixture_manifest_sha256"] = _framed_sha256(
        _HASH_DOMAINS["fixture_manifest"], tampered["fixture_manifest"]
    )
    tampered = _reseal(tampered)

    with pytest.raises(
        DynamicBenchmarkV3ValidationError, match="fixture manifest drifted"
    ):
        validate_dynamic_replanning_benchmark_report(tampered)


def test_dynamic_benchmark_v3_rejects_self_rehashed_record_drift() -> None:
    tampered = deepcopy(build_dynamic_replanning_benchmark_report())
    record = tampered["records"][0]
    record["terminal_disposition"] = "HOLD"
    record_payload = {
        key: value for key, value in record.items() if key != "record_sha256"
    }
    record["record_sha256"] = _framed_sha256(_HASH_DOMAINS["record"], record_payload)
    tampered["records_sha256"] = _framed_sha256(
        _HASH_DOMAINS["records"], tampered["records"]
    )
    tampered = _reseal(tampered)

    with pytest.raises(DynamicBenchmarkV3ValidationError, match="deterministic replay"):
        validate_dynamic_replanning_benchmark_report(tampered)


def test_dynamic_benchmark_v3_rejects_self_rehashed_metric_drift() -> None:
    tampered = deepcopy(build_dynamic_replanning_benchmark_report())
    tampered["metrics"]["fixed_rule_baseline"]["correct_terminal_disposition_count"] = 8
    tampered["metrics_sha256"] = _framed_sha256(
        _HASH_DOMAINS["metrics"], tampered["metrics"]
    )
    tampered = _reseal(tampered)

    with pytest.raises(DynamicBenchmarkV3ValidationError, match="metrics do not match"):
        validate_dynamic_replanning_benchmark_report(tampered)


def test_dynamic_benchmark_v3_rejects_self_rehashed_protocol_drift() -> None:
    tampered = deepcopy(build_dynamic_replanning_benchmark_report())
    tampered["protocol"]["tool_budget_per_fixture"] = 2
    tampered["protocol_sha256"] = _framed_sha256(
        _HASH_DOMAINS["protocol"], tampered["protocol"]
    )
    tampered = _reseal(tampered)

    with pytest.raises(
        DynamicBenchmarkV3ValidationError, match="fixed protocol drifted"
    ):
        validate_dynamic_replanning_benchmark_report(tampered)


def test_dynamic_benchmark_v3_writes_and_reloads_canonical_report(tmp_path) -> None:
    output = write_dynamic_replanning_benchmark_report(tmp_path / "report.json")
    loaded = load_dynamic_replanning_benchmark_report(output)

    assert loaded["status"] == "PASS"
    assert output.read_bytes().endswith(b"\n")
