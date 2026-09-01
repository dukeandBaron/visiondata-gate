from __future__ import annotations

from tools.build_reviewer_scenario_suite import build_suite


def test_reviewer_scenario_suite_persists_comparable_failure_evidence(tmp_path) -> None:
    payload = build_suite(tmp_path / "suite", seed=20260812)

    assert payload["status"] == "PASS"
    assert all(payload["checks"].values())
    assert [item["scenario"] for item in payload["scenarios"]] == [
        "happy_path",
        "missing_worker_fail_closed",
    ]
    negative = payload["scenarios"][1]
    assert negative["initial_decision"] == "DEFER"
    assert negative["verification_decision"] == "DEFER"
    assert negative["completed_work_order_count"] == 0
    assert negative["deferred_context_transfer_count"] > 0
    assert negative["deferred_skill_execution_count"] > 0
    for scenario in payload["scenarios"]:
        assert scenario["agentteams_static_status"] == "PASS"
        assert scenario["agentteams_runtime_status"] == "OPEN"
        assert scenario["agentteams_connection_status"] == "mapped_not_connected"
        assert scenario["hosted_agentteams_connected_observed"] is False
        assert scenario["posthoc_validation_artifacts_present"] == []
