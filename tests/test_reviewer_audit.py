from __future__ import annotations

import json

import pytest

from visiondata_gate.agent_runtime import AgenticDemoRun, run_agentic_demo
from visiondata_gate.contracts import BatchContract, BatchManifest
from visiondata_gate.reviewer_audit import (
    build_reviewer_feedback_audit,
    build_runtime_contract_audit,
    build_skill_qualification_receipt,
    build_tool_ablation_receipt,
    build_tool_replay_receipt,
    build_tool_contract_snapshot,
)
from visiondata_gate.runtime_models import RuntimeConfig, ScenarioProfile


@pytest.fixture(scope="module")
def industrial_reviewer_run(
    tmp_path_factory: pytest.TempPathFactory,
) -> AgenticDemoRun:
    root = tmp_path_factory.mktemp("reviewer-audit-industrial")
    return run_agentic_demo(
        root / "run",
        seed=20260812,
        config=RuntimeConfig(scenario_profile=ScenarioProfile.INDUSTRIAL),
        memory_path=root / "memory.json",
    )


@pytest.fixture(scope="module")
def default_reviewer_run(
    tmp_path_factory: pytest.TempPathFactory,
) -> AgenticDemoRun:
    root = tmp_path_factory.mktemp("reviewer-audit-default")
    return run_agentic_demo(
        root / "run",
        seed=20260814,
        config=RuntimeConfig(),
        memory_path=root / "memory.json",
    )


@pytest.fixture(scope="module")
def restricted_reviewer_run(
    tmp_path_factory: pytest.TempPathFactory,
) -> AgenticDemoRun:
    root = tmp_path_factory.mktemp("reviewer-audit-restricted")
    return run_agentic_demo(
        root / "run",
        seed=20260818,
        config=RuntimeConfig(
            scenario_profile=ScenarioProfile.INDUSTRIAL,
            allowed_tools=["image_quality"],
            persist_memory=False,
        ),
        memory_path=root / "memory.json",
    )


def test_reviewer_audit_separates_official_competitor_and_local_layers(
    industrial_reviewer_run: AgenticDemoRun,
) -> None:
    run = industrial_reviewer_run
    path = run.evidence_dir / "reviewer_feedback_audit.json"
    assert path.is_file()
    payload = json.loads(path.read_text(encoding="utf-8"))
    assert payload["schema_version"] == "visiondata-gate.reviewer-feedback-audit.v1"
    assert payload["source_layers"]["official_boundless_agents"]
    assert payload["source_layers"]["cross_track_infra_reference"]
    assert payload["source_layers"]["public_competitor_reference"]
    assert payload["status_counts"]["PARTIAL"] >= 1
    rights = next(
        item
        for item in payload["items"]
        if item["audit_id"] == "open_source_and_rights"
    )
    assert rights["status"] == "PARTIAL"
    assert "LICENSE" in rights["local_evidence"]
    assert all(
        item["source_layer"] != "official_judge_score" for item in payload["items"]
    )
    assert (
        build_reviewer_feedback_audit(
            run.runtime_trace, run.initial_result, run.repaired_result, run.evaluation
        )
        == payload
    )


def test_tool_contract_snapshot_is_complete_and_run_bound(
    industrial_reviewer_run: AgenticDemoRun,
) -> None:
    run = industrial_reviewer_run
    path = run.evidence_dir / "tool_contract_snapshot.json"
    assert path.is_file()
    payload = json.loads(path.read_text(encoding="utf-8"))
    assert payload["schema_version"] == "visiondata-gate.tool-contract-snapshot.v1"
    assert payload["run_id"] == run.runtime_trace.run_id
    assert payload["connection_status"] == "mapped_not_connected"
    assert len(payload["tools"]) >= 5
    required = {
        "input_schema",
        "output_schema",
        "permission_scope",
        "read_only",
        "side_effect_level",
        "error_and_retry",
        "idempotency",
        "audit_fields",
        "mcp_migration",
        "migration_cost",
        "necessity_basis",
        "replaceability_basis",
        "verification_status",
    }
    for tool in payload["tools"]:
        assert required <= set(tool)
        assert tool["read_only"] is True
        assert tool["side_effect_level"] == "L0_none"
    assert (
        build_tool_contract_snapshot(
            run.runtime_trace, run.initial_result, run.repaired_result
        )
        == payload
    )


def test_proof_index_includes_reviewer_comparison_artifacts(
    default_reviewer_run: AgenticDemoRun,
) -> None:
    run = default_reviewer_run
    proof = json.loads(
        (run.evidence_dir / "proof_index.json").read_text(encoding="utf-8")
    )
    paths = {item["path"] for item in proof["artifact_index"]}
    assert "evidence/reviewer_feedback_audit.json" in paths
    assert "evidence/tool_contract_snapshot.json" in paths
    claim_ids = {claim["claim_id"] for claim in proof["claims"]}
    assert "reviewer_feedback_audit" in claim_ids
    assert "tool_contract_necessity_and_migration" in claim_ids


def test_runtime_contract_audit_checks_the_executable_core(
    industrial_reviewer_run: AgenticDemoRun,
) -> None:
    run = industrial_reviewer_run
    path = run.evidence_dir / "runtime_contract_audit.json"
    assert path.is_file()
    payload = json.loads(path.read_text(encoding="utf-8"))
    assert payload["schema_version"] == "visiondata-gate.runtime-contract-audit.v1"
    assert payload["status"] == "PASS"
    assert all(payload["checks"].values())
    assert payload["checks"]["typed_tool_contracts_bound"] is True
    assert payload["checks"]["one_policy_authority_per_pass"] is True
    assert payload["checks"]["same_contract_recheck"] is True
    assert payload["checks"]["context_transfer_edges_complete"] is True
    assert payload["checks"]["context_transfer_hashes_valid"] is True
    assert payload["checks"]["context_transfer_task_refs_match"] is True
    assert payload["checks"]["context_transfer_runtime_event_bound"] is True
    assert payload["checks"]["skill_execution_coverage_complete"] is True
    assert payload["checks"]["skill_qualification_passed"] is True
    assert (
        payload["context_transfers"]["count"]
        == payload["task_graph"]["dependency_count"]
    )
    assert (
        build_runtime_contract_audit(
            run.runtime_trace, run.initial_result, run.repaired_result
        )
        == payload
    )


def test_context_transfer_receipt_marks_missing_worker_as_deferred(
    restricted_reviewer_run: AgenticDemoRun,
) -> None:
    run = restricted_reviewer_run

    assert run.initial_result.decision.value == "DEFER"
    assert run.repaired_result.decision.value == "DEFER"
    assert run.runtime_trace.context_transfers
    assert all(
        item.capture_mode == "runtime_event" and item.recorded_event_sequence >= 1
        for item in run.runtime_trace.context_transfers
    )
    assert any(
        item.status == "deferred" for item in run.runtime_trace.context_transfers
    )
    assert all(
        item.rejection_reason
        for item in run.runtime_trace.context_transfers
        if item.status == "deferred"
    )
    audit = json.loads(
        (run.evidence_dir / "runtime_contract_audit.json").read_text(encoding="utf-8")
    )
    assert audit["checks"]["context_transfer_failure_safe"] is True
    receipt = json.loads(
        (run.evidence_dir / "skill_qualification_receipt.json").read_text(
            encoding="utf-8"
        )
    )
    assert receipt["status"] == "PASS"
    assert receipt["deferred_count"] >= 1
    assert receipt == build_skill_qualification_receipt(run.runtime_trace)


def test_tool_replay_receipt_matches_both_gate_phases(
    industrial_reviewer_run: AgenticDemoRun,
) -> None:
    run = industrial_reviewer_run
    path = run.evidence_dir / "tool_replay_receipt.json"
    assert not path.exists()
    manifest = BatchManifest.model_validate_json(
        run.dataset_paths["batch_manifest"].read_text(encoding="utf-8")
    )
    payload = build_tool_replay_receipt(
        run.runtime_trace,
        initial_root=run.dataset_paths["batch_root"],
        initial_manifest=manifest,
        repaired_root=run.repair.output_root,
        repaired_manifest=run.repair.manifest,
        contract=BatchContract(),
        initial=run.initial_result,
        repaired=run.repaired_result,
    )
    assert payload["schema_version"] == "visiondata-gate.tool-replay-receipt.v1"
    assert payload["status"] == "PASS"
    assert [item["phase"] for item in payload["phases"]] == [
        "initial",
        "verification",
    ]
    assert all(
        comparison["status"] == "PASS"
        for phase in payload["phases"]
        for comparison in phase["comparisons"]
    )
    regenerated = build_tool_replay_receipt(
        run.runtime_trace,
        initial_root=run.dataset_paths["batch_root"],
        initial_manifest=manifest,
        repaired_root=run.repair.output_root,
        repaired_manifest=run.repair.manifest,
        contract=BatchContract(),
        initial=run.initial_result,
        repaired=run.repaired_result,
    )
    assert regenerated == payload


def test_tool_ablation_receipt_is_fail_closed_and_run_bound(
    industrial_reviewer_run: AgenticDemoRun,
) -> None:
    run = industrial_reviewer_run
    path = run.evidence_dir / "tool_ablation_receipt.json"
    assert not path.exists()
    manifest = BatchManifest.model_validate_json(
        run.dataset_paths["batch_manifest"].read_text(encoding="utf-8")
    )
    payload = build_tool_ablation_receipt(
        run.runtime_trace,
        initial_manifest=manifest,
        repaired_manifest=run.repair.manifest,
        contract=BatchContract(),
        initial=run.initial_result,
        repaired=run.repaired_result,
    )
    assert payload["schema_version"] == "visiondata-gate.tool-ablation-receipt.v1"
    assert payload["run_id"] == run.runtime_trace.run_id
    assert payload["status"] == "PASS"
    assert len(payload["phases"]) == 2
    assert all(
        item["disabled_trace_status"] == "skipped"
        and item["ablated_decision"] == "DEFER"
        and item["more_permissive"] is False
        and "RC-TRACE-OK" in item["new_failed_rule_checks"]
        for phase in payload["phases"]
        for item in phase["ablations"]
    )
    regenerated = build_tool_ablation_receipt(
        run.runtime_trace,
        initial_manifest=manifest,
        repaired_manifest=run.repair.manifest,
        contract=BatchContract(),
        initial=run.initial_result,
        repaired=run.repaired_result,
    )
    assert regenerated == payload


def test_skill_qualification_rejects_version_tampering(
    industrial_reviewer_run: AgenticDemoRun,
) -> None:
    run = industrial_reviewer_run
    executions = list(run.runtime_trace.skill_executions)
    executions[0] = executions[0].model_copy(update={"skill_version": "9.9.9"})
    tampered_trace = run.runtime_trace.model_copy(
        update={"skill_executions": executions}
    )

    receipt = build_skill_qualification_receipt(tampered_trace)

    assert receipt["status"] == "PARTIAL"
    assert receipt["checks"]["all_execution_receipts_valid"] is False
    assert receipt["executions"][0]["receipt_checks"]["version_matches"] is False
