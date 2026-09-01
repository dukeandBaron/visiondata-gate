from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from pydantic import ValidationError

import visiondata_gate.industrial_incident as industrial_incident_core
from visiondata_gate.demo_fixtures import build_fixture_industrial_incident_request
from visiondata_gate.evidence import canonical_json_bytes
from visiondata_gate.incident_canvas import build_incident_canvas
from visiondata_gate.incident_runtime_profile import IncidentRuntimeProfile
from visiondata_gate.industrial_incident import (
    GOVERNED_AUDIT_ENVELOPE_REQUIREMENT,
    GOVERNED_INCIDENT_CASE_SCHEMA_VERSION,
    IncidentCapaEvidence,
    IncidentHumanDecision,
    IncidentPhaseEvent,
    IncidentRecommendation,
    IncidentStatus,
    IncidentTriggerKind,
    IncidentWorkerExecutionError,
    IncidentWorkerRegistry,
    IndustrialGateContext,
    IndustrialIncidentCase,
    IndustrialIncidentDecisionRequest,
    IndustrialIncidentRequest,
    IndustrialIncidentRequestV1,
    IndustrialIncidentRequestV2,
    IndustrialIncidentRequestV3,
    IndustrialIncidentTrigger,
    ManufacturingRecordAuthorityStatus,
    OfflineVisionRunReceipt,
    OPCUAMachineVisionContext,
    OPCUANodeObservation,
    OPCUAOfflineSnapshot,
    OPCUASnapshotMode,
    OPCUAValueSeverity,
    ProcessSignalExpectation,
    ProductionChangeKind,
    VisionSolutionManifest,
    build_batch_trace_record,
    build_incident_phase_events,
    build_industrial_incident_case,
    build_industrial_incident_decision_receipt,
    build_production_change_record,
    incident_case_requires_governed_audit_envelope,
    incident_case_verification_scope,
    parse_industrial_incident_case,
    parse_industrial_incident_case_json,
    parse_industrial_incident_request,
    verify_incident_worker_receipt,
    verify_incident_phase_events,
    verify_industrial_incident_case,
    verify_industrial_incident_decision_receipt,
)


def _digest(label: str) -> str:
    return hashlib.sha256(label.encode("utf-8")).hexdigest()


def test_fixture_builder_is_not_exposed_by_industrial_incident_core() -> None:
    assert not hasattr(
        industrial_incident_core,
        "build_fixture_industrial_incident_request",
    )
    assert (
        "build_fixture_industrial_incident_request"
        not in industrial_incident_core.__all__
    )


def _reseal_batch(record, **updates):
    payload = record.model_dump(mode="python", exclude={"record_binding_sha256"})
    payload.update(updates)
    return build_batch_trace_record(**payload)


def _reseal_change(record, **updates):
    payload = record.model_dump(mode="python", exclude={"record_binding_sha256"})
    payload.update(updates)
    return build_production_change_record(**payload)


def _solution(*, configuration_id: str = "cfg-17") -> VisionSolutionManifest:
    return VisionSolutionManifest(
        source_profile="VISIONMASTER_COMPATIBLE_OFFLINE_EXPORT",
        solution_id="connector-pin-v2",
        solution_version="2.4.1",
        product_id="product-A",
        recipe_id="recipe-A-17",
        configuration_id=configuration_id,
        exported_at=datetime(2026, 8, 26, 8, 0, tzinfo=UTC),
        algorithm_graph_sha256=_digest("graph"),
        model_artifact_sha256=_digest("model"),
        camera_config_sha256=_digest("camera"),
        lighting_config_sha256=_digest("light"),
        calibration_receipt_sha256=_digest("calibration"),
        rulepack_sha256=_digest("rulepack"),
        dataset_version_id="omni-derived-v1",
    )


def _request(
    *,
    severity: OPCUAValueSeverity = OPCUAValueSeverity.GOOD,
    observation_unit: str = "mm/s",
    observation_value: float = 82.0,
    source_timestamp: datetime | None = None,
    snapshot_configuration_id: str = "cfg-17",
    run_configuration_id: str = "cfg-17",
    solution: VisionSolutionManifest | None = None,
    baseline_solution_manifest_sha256: str | None = None,
    run_manifest_sha256: str | None = None,
) -> IndustrialIncidentRequest:
    triggered_at = datetime(2026, 8, 26, 8, 10, tzinfo=UTC)
    source_timestamp = source_timestamp or triggered_at - timedelta(seconds=2)
    solution = solution or _solution()
    solution_sha256 = hashlib.sha256(canonical_json_bytes(solution)).hexdigest()
    snapshot = OPCUAOfflineSnapshot(
        source_mode=OPCUASnapshotMode.OFFLINE_EXPORT,
        captured_at=triggered_at,
        server_application_uri_sha256=_digest("server-app-uri"),
        node_whitelist_sha256=_digest("node-whitelist"),
        allowlisted_aliases=["line.speed"],
        machine_vision_context=OPCUAMachineVisionContext(
            product_id="product-A",
            part_id="part-00042",
            recipe_id="recipe-A-17",
            configuration_id=snapshot_configuration_id,
            job_id="job-20260826-42",
            result_id="result-20260826-42",
            creation_time=triggered_at - timedelta(seconds=1),
            result_state="Completed",
            is_partial=False,
            is_simulated=False,
            lot_reference="lot-20260826-A",
            lot_reference_authority="BARCODE_SCAN",
        ),
        observations=[
            OPCUANodeObservation(
                semantic_alias="line.speed",
                namespace_uri="urn:factory:line-a",
                browse_path="LineA/Process/Speed",
                node_id_sha256=_digest("nsu=line-a;s=process.speed"),
                data_type="Double",
                engineering_unit=observation_unit,
                value=observation_value,
                status_code="Good",
                severity=severity,
                source_timestamp=source_timestamp,
                server_timestamp=source_timestamp + timedelta(seconds=1),
            )
        ],
        operator_attests_authorized_export=True,
    )
    run = OfflineVisionRunReceipt(
        source_profile="VISIONMASTER_COMPATIBLE_OFFLINE_EXPORT",
        run_id="run-20260826-42",
        solution_manifest_sha256=run_manifest_sha256 or solution_sha256,
        product_id="product-A",
        part_id="part-00042",
        recipe_id="recipe-A-17",
        configuration_id=run_configuration_id,
        job_id="job-20260826-42",
        result_id="result-20260826-42",
        batch_id="batch-20260826-A",
        lot_reference="lot-20260826-A",
        work_order_id="work-order-20260826-42",
        line_id="line-A",
        started_at=triggered_at - timedelta(seconds=8),
        completed_at=triggered_at - timedelta(seconds=1),
        execution_state="Completed",
        input_count=100,
        ok_count=89,
        ng_count=11,
        sample_index_sha256=_digest("sample-index"),
        result_summary_sha256=_digest("result-summary"),
    )
    batch_trace = build_batch_trace_record(
        record_id="batch-record-20260826-42",
        source_kind="MES_EXPORT",
        source_system_id_sha256=_digest("mes-system"),
        source_record_sha256=_digest("batch-source-record"),
        source_authorization_sha256=_digest("batch-authorization"),
        authority_status=ManufacturingRecordAuthorityStatus.VERIFIED,
        batch_id="batch-20260826-A",
        lot_reference="lot-20260826-A",
        work_order_id="work-order-20260826-42",
        line_id="line-A",
        product_id="product-A",
        part_id="part-00042",
        recipe_id="recipe-A-17",
        configuration_id="cfg-17",
        production_window_start=triggered_at - timedelta(minutes=30),
        production_window_end=triggered_at,
        exported_at=triggered_at + timedelta(seconds=1),
        operator_attests_authorized_export=True,
    )
    production_change = build_production_change_record(
        record_id="change-record-20260826-42",
        change_order_id="change-order-20260826-42",
        change_kind=ProductionChangeKind.PRODUCT_CHANGEOVER,
        change_status="APPROVED_EFFECTIVE",
        source_kind="MES_CHANGELOG_EXPORT",
        source_system_id_sha256=_digest("mes-system"),
        source_record_sha256=_digest("change-source-record"),
        source_authorization_sha256=_digest("change-authorization"),
        authority_status=ManufacturingRecordAuthorityStatus.VERIFIED,
        line_id="line-A",
        work_order_id="work-order-20260826-42",
        batch_id="batch-20260826-A",
        lot_reference="lot-20260826-A",
        effective_at=triggered_at - timedelta(minutes=20),
        recorded_at=triggered_at - timedelta(minutes=19),
        exported_at=triggered_at - timedelta(minutes=18),
        previous_product_id="product-legacy",
        new_product_id="product-A",
        operator_attests_authorized_export=True,
    )
    return IndustrialIncidentRequestV3(
        trigger=IndustrialIncidentTrigger(
            trigger_kind=IncidentTriggerKind.NG_RATE_DRIFT,
            triggered_at=triggered_at,
            operator_message="换型后 NG 率由 2% 上升到 11%，请判断下一步补证与复验动作。",
            product_id="product-A",
            part_id="part-00042",
            recipe_id="recipe-A-17",
            configuration_id="cfg-17",
            batch_id="batch-20260826-A",
            lot_reference="lot-20260826-A",
            work_order_id="work-order-20260826-42",
            line_id="line-A",
            baseline_ng_rate=0.02,
            observed_ng_rate=0.11,
            sample_count=100,
        ),
        opcua_snapshot=snapshot,
        vision_solution=solution,
        offline_run=run,
        batch_trace_record=batch_trace,
        production_change_records=[production_change],
        process_signal_expectations=[
            ProcessSignalExpectation(
                semantic_alias="line.speed",
                engineering_unit="mm/s",
                minimum=75.0,
                maximum=90.0,
            )
        ],
        baseline_solution_manifest_sha256=baseline_solution_manifest_sha256,
        runtime_profile=IncidentRuntimeProfile(),
        operator_attests_inputs_authorized=True,
    )


def _gate_context(*, decision: str = "PASS") -> IndustrialGateContext:
    return IndustrialGateContext(
        task_id="task_0123456789abcdef",
        gate_final_decision=decision,
        task_evidence_sha256=_digest("task-evidence"),
        industrial_delivery_sha256=_digest("industrial-delivery"),
        source_profile_sha256=_digest("source-profile"),
        source_authorization_event_sha256=_digest("source-authorization"),
        dynamic_response_count=3,
        open_work_order_count=49 if decision != "PASS" else 0,
        remediation_plan_ids=(
            ["plan-containment", "plan-actionable", "plan-full"]
            if decision != "PASS"
            else []
        ),
        model_call_count=0,
    )


def test_clean_offline_incident_reaches_only_human_review() -> None:
    case = build_industrial_incident_case(_request(), _gate_context())

    assert case.status is IncidentStatus.READY_FOR_HUMAN_REVIEW
    assert case.recommendation is IncidentRecommendation.CONTINUE_OBSERVATION
    assert case.production_release_allowed is False
    assert case.machine_write_permitted is False
    assert case.direct_equipment_control_permitted is False
    assert case.opcua_connection_status == "OPC_UA_REAL_ENDPOINT_NOT_CONNECTED"
    assert case.visionmaster_connection_status == "VISIONMASTER_SDK_NOT_CONNECTED"
    assert case.external_model_call_count == 0
    assert len(case.evidence_refs) == 9
    assert [step.phase for step in case.loop_steps] == [
        "PLAN",
        "ACT",
        "OBSERVE",
        "EVALUATE",
        "INTERRUPT",
    ]
    assert case.loop_steps[-1].status == "PAUSED"
    assert case.planning_mode == "bounded_evidence_agent_loop_v2"
    assert case.root_cause_status == "NOT_ESTABLISHED"
    verify_industrial_incident_case(case)


@pytest.mark.parametrize(
    ("incident_request", "expected_code", "expected_worker"),
    [
        (
            _request(severity=OPCUAValueSeverity.BAD),
            "OPC_VALUE_BAD",
            "SignalIntegrityAgent",
        ),
        (
            _request(observation_unit="m/s"),
            "OPC_ENGINEERING_UNIT_MISMATCH",
            "SignalIntegrityAgent",
        ),
        (
            _request(source_timestamp=datetime(2026, 8, 26, 7, 0, tzinfo=UTC)),
            "OPC_SIGNAL_STALE",
            "SignalIntegrityAgent",
        ),
        (
            _request(snapshot_configuration_id="cfg-stale"),
            "CORRELATION_CONFIGURATION_ID_MISMATCH",
            "TraceabilityAgent",
        ),
        (
            _request(run_manifest_sha256=_digest("wrong-manifest")),
            "OFFLINE_RUN_MANIFEST_HASH_MISMATCH",
            "VisionRecipeAgent",
        ),
    ],
)
def test_unqualified_or_unmatched_evidence_fails_closed(
    incident_request: IndustrialIncidentRequest,
    expected_code: str,
    expected_worker: str,
) -> None:
    case = build_industrial_incident_case(incident_request, _gate_context())

    assert case.status is IncidentStatus.EVIDENCE_INCOMPLETE
    assert case.recommendation is IncidentRecommendation.COLLECT_MORE_EVIDENCE
    assert expected_code in [item.issue_code for item in case.evidence_issues]
    assert expected_worker in [item.agent_role for item in case.agent_actions]
    assert case.production_release_allowed is False


def test_gate_block_creates_real_capa_entry_without_claiming_recovery() -> None:
    case = build_industrial_incident_case(
        _request(), _gate_context(decision="QUARANTINE")
    )

    assert case.status is IncidentStatus.CAPA_READY
    assert case.recommendation is IncidentRecommendation.EXECUTE_APPROVED_CAPA
    assert case.linked_remediation_plan_ids == [
        "plan-containment",
        "plan-actionable",
        "plan-full",
    ]
    assert "VisualDataQualityAgent" in [item.agent_role for item in case.agent_actions]
    assert case.root_cause_status == "NOT_ESTABLISHED"


def test_solution_drift_and_gate_finding_trigger_multiple_dynamic_workers() -> None:
    request = _request(baseline_solution_manifest_sha256=_digest("approved-baseline"))
    case = build_industrial_incident_case(request, _gate_context(decision="QUARANTINE"))
    roles = [item.agent_role for item in case.agent_actions if item.dynamic]

    assert case.status is IncidentStatus.SOLUTION_REVERIFICATION_REQUIRED
    assert "VisionRecipeAgent" in roles
    assert "VisualDataQualityAgent" in roles
    assert "CounterevidenceAuditorAgent" in roles
    assert case.dynamic_branch_count == len(roles)


def test_same_inputs_produce_same_case_and_plan_hashes() -> None:
    first = build_industrial_incident_case(_request(), _gate_context())
    second = build_industrial_incident_case(_request(), _gate_context())

    assert first.case_id == second.case_id
    assert first.case_sha256 == second.case_sha256
    assert canonical_json_bytes(first) == canonical_json_bytes(second)


def test_tampered_case_fails_integrity_validation() -> None:
    case = build_industrial_incident_case(_request(), _gate_context())
    tampered = case.model_copy(update={"recommendation_reason": "tampered"})

    with pytest.raises(ValueError, match="integrity"):
        verify_industrial_incident_case(tampered)


def test_case_verification_scope_is_object_local_and_request_bounded(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    case = build_industrial_incident_case(_request(), _gate_context())
    equivalent_case = case.model_copy(deep=True)
    original_model_dump = IndustrialIncidentCase.model_dump
    full_dump_count = 0

    def counting_model_dump(self, *args, **kwargs):
        nonlocal full_dump_count
        if self is case or self is equivalent_case:
            full_dump_count += 1
        return original_model_dump(self, *args, **kwargs)

    monkeypatch.setattr(IndustrialIncidentCase, "model_dump", counting_model_dump)

    with incident_case_verification_scope():
        verify_industrial_incident_case(case)
        verify_industrial_incident_case(case)
        with incident_case_verification_scope():
            verify_industrial_incident_case(case)
            verify_industrial_incident_case(equivalent_case)
            verify_industrial_incident_case(equivalent_case)

    assert full_dump_count == 2

    verify_industrial_incident_case(case)
    assert full_dump_count == 3


def test_case_verification_scope_rechecks_a_changed_seal() -> None:
    case = build_industrial_incident_case(_request(), _gate_context())

    with incident_case_verification_scope():
        verify_industrial_incident_case(case)
        case.case_sha256 = "f" * 64
        with pytest.raises(ValueError, match="integrity"):
            verify_industrial_incident_case(case)


def test_contract_rejects_naive_timestamps_and_unknown_fields() -> None:
    payload = _request().model_dump(mode="json")
    payload["trigger"]["triggered_at"] = "2026-08-26T08:10:00"
    with pytest.raises(ValidationError, match="UTC offset"):
        parse_industrial_incident_request(payload)

    payload = _request().model_dump(mode="json")
    payload["opcua_snapshot"]["endpoint_url"] = "opc.tcp://secret-factory:4840"
    with pytest.raises(ValidationError, match="Extra inputs"):
        parse_industrial_incident_request(payload)


def test_fixture_request_is_visibly_simulated_and_dispatches_multiple_workers() -> None:
    incident_request = build_fixture_industrial_incident_request()
    case = build_industrial_incident_case(
        incident_request, _gate_context(decision="QUARANTINE")
    )

    assert (
        incident_request.opcua_snapshot.source_mode is OPCUASnapshotMode.FIXTURE_REPLAY
    )
    assert incident_request.offline_run.is_simulated is True
    assert case.opcua_connection_status == "OPC_UA_FIXTURE_REPLAY_ONLY"
    assert "只验证产品闭环" in " ".join(case.decision_summary.observed_facts)
    dynamic_roles = {
        action.agent_role
        for action in case.agent_actions
        if action.dynamic and action.status == "COMPLETED"
    }
    assert {
        "EvidenceQualificationAgent",
        "ProcessContextAgent",
        "VisionRecipeAgent",
        "VisualDataQualityAgent",
        "CounterevidenceAuditorAgent",
    }.issubset(dynamic_roles)


def test_resume_creates_new_immutable_case_version_and_preserves_loop_budget() -> None:
    parent = build_industrial_incident_case(
        _request(severity=OPCUAValueSeverity.BAD), _gate_context()
    )
    decision = build_industrial_incident_decision_receipt(
        parent,
        IndustrialIncidentDecisionRequest(
            bound_case_sha256=parent.case_sha256,
            decision=IncidentHumanDecision.CONTINUE_HOLD,
            note="已复核坏质量码，继续 HOLD 并提交刷新后的只读快照。",
            operator_attests_reviewed_evidence=True,
        ),
        actor_user_id="usr_fixture_quality_owner",
        decided_at=datetime(2026, 8, 26, 9, 0, tzinfo=UTC),
    )
    resumed_request = _request().model_copy(
        update={
            "supersedes_case_id": parent.case_id,
            "expected_parent_case_sha256": parent.case_sha256,
            "authorizing_decision_id": decision.decision_id,
        }
    )
    child = build_industrial_incident_case(
        resumed_request,
        _gate_context(),
        parent_case=parent,
        authorizing_decision=decision,
    )

    assert child.parent_case_id == parent.case_id
    assert child.parent_case_sha256 == parent.case_sha256
    assert child.authorizing_decision_sha256 == decision.decision_sha256
    assert child.case_id != parent.case_id
    assert child.case_version == 2
    assert child.loop_control.dynamic_workers_executed >= (
        parent.loop_control.dynamic_workers_executed
    )
    assert parent.case_version == 1
    verify_industrial_incident_case(parent)
    verify_industrial_incident_case(child)


def test_worker_budget_blocks_unevaluated_branches_without_leaking_findings() -> None:
    fixture = build_fixture_industrial_incident_request().model_copy(
        update={"max_dynamic_workers": 1}
    )
    case = build_industrial_incident_case(fixture, _gate_context(decision="QUARANTINE"))

    completed_roles = {
        item.agent_role
        for item in case.agent_actions
        if item.dynamic and item.status == "COMPLETED"
    }
    stopped_roles = {
        item.agent_role
        for item in case.agent_actions
        if item.dynamic and item.status == "STOPPED"
    }
    assert completed_roles == {"EvidenceQualificationAgent"}
    assert {
        "ProcessContextAgent",
        "VisionRecipeAgent",
        "VisualDataQualityAgent",
    } <= stopped_roles
    issue_codes = {item.issue_code for item in case.evidence_issues}
    assert "EVIDENCE_NOT_EVALUATED_DUE_TO_BUDGET" in issue_codes
    assert "PROCESS_SIGNAL_OUT_OF_RANGE" not in issue_codes
    assert "VISION_SOLUTION_MANIFEST_DRIFT" not in issue_codes
    assert "GATE_DECISION_NOT_PASS" not in issue_codes
    assert case.status is IncidentStatus.EVIDENCE_INCOMPLETE
    assert len(case.worker_receipts) == 1
    assert case.worker_receipts[0].worker_role == "EvidenceQualificationAgent"
    assert case.worker_selection_receipt is not None
    assert case.worker_selection_receipt.selected_worker_ids == [
        "EvidenceQualificationAgent"
    ]
    assert completed_roles == set(case.worker_selection_receipt.selected_worker_ids)


def test_external_unverified_source_fails_closed() -> None:
    context = _gate_context().model_copy(
        update={
            "source_kind": "external_residency_reference",
            "source_authorization_status": "UNAVAILABLE",
        }
    )
    case = build_industrial_incident_case(_request(), context)

    assert case.status is IncidentStatus.EVIDENCE_INCOMPLETE
    assert "EXTERNAL_SOURCE_AUTHORIZATION_UNVERIFIED" in {
        item.issue_code for item in case.evidence_issues
    }
    source_ref = next(
        item
        for item in case.evidence_refs
        if item.evidence_type == "source_authorization"
    )
    assert source_ref.qualification.value == "NOT_QUALIFIED"


class _FailingIncidentWorkerRegistry(IncidentWorkerRegistry):
    def __init__(self) -> None:
        super().__init__(set())

    def execute(self, **kwargs):
        raise IncidentWorkerExecutionError(
            "TOOL_TIMEOUT",
            retryable=True,
        )


def test_selected_worker_failure_is_sealed_and_judge_fails_closed() -> None:
    fixture = build_fixture_industrial_incident_request().model_copy(
        update={"max_dynamic_workers": 1}
    )
    case = build_industrial_incident_case(
        fixture,
        _gate_context(decision="QUARANTINE"),
        worker_registry=_FailingIncidentWorkerRegistry(),
    )

    assert case.status is IncidentStatus.EVIDENCE_INCOMPLETE
    assert case.recommendation is IncidentRecommendation.COLLECT_MORE_EVIDENCE
    assert {item.issue_code for item in case.evidence_issues} >= {
        "WORKER_EXECUTION_FAILED",
        "EVIDENCE_NOT_EVALUATED_DUE_TO_BUDGET",
    }
    assert len(case.worker_receipts) == 1
    failed_receipt = case.worker_receipts[0]
    assert failed_receipt.status == "FAILED"
    assert failed_receipt.error_code == "TOOL_TIMEOUT"
    assert failed_receipt.retryable is True
    assert failed_receipt.output_issues == []
    failed_action = next(
        item for item in case.agent_actions if item.dynamic and item.status == "FAILED"
    )
    assert failed_action.output_receipt_sha256 == failed_receipt.receipt_sha256
    assert case.loop_control.dynamic_workers_executed == 1
    assert case.loop_control.remaining_worker_budget == 0

    phase_events = build_incident_phase_events(case)
    failed_event = next(item for item in phase_events if item.status == "FAILED")
    assert failed_event.actor == failed_receipt.worker_role
    assert failed_event.error_code == "TOOL_TIMEOUT"
    verify_industrial_incident_case(case)


def test_resume_rejects_unchanged_evidence_and_cross_product_identity() -> None:
    parent = build_industrial_incident_case(_request(), _gate_context())
    decision = build_industrial_incident_decision_receipt(
        parent,
        IndustrialIncidentDecisionRequest(
            bound_case_sha256=parent.case_sha256,
            decision=IncidentHumanDecision.CONTINUE_HOLD,
            note="已复核证据，保持 HOLD；只有新证据才能创建下一版本。",
            operator_attests_reviewed_evidence=True,
        ),
        actor_user_id="usr_fixture_quality_owner",
        decided_at=datetime(2026, 8, 26, 9, 10, tzinfo=UTC),
    )
    controls = {
        "supersedes_case_id": parent.case_id,
        "expected_parent_case_sha256": parent.case_sha256,
        "authorizing_decision_id": decision.decision_id,
    }
    unchanged = _request().model_copy(update=controls)
    with pytest.raises(ValueError, match="NO_NEW_EVIDENCE"):
        build_industrial_incident_case(
            unchanged,
            _gate_context(),
            parent_case=parent,
            authorizing_decision=decision,
        )

    changed_trigger = _request().trigger.model_copy(update={"product_id": "product-B"})
    cross_product = _request().model_copy(
        update={**controls, "trigger": changed_trigger}
    )
    with pytest.raises(ValueError, match="frozen event identity"):
        build_industrial_incident_case(
            cross_product,
            _gate_context(),
            parent_case=parent,
            authorizing_decision=decision,
        )


def test_future_snapshot_and_inconsistent_incident_statistics_fail_closed() -> None:
    base = _request()
    future_snapshot = base.opcua_snapshot.model_copy(
        update={"captured_at": base.trigger.triggered_at + timedelta(hours=2)}
    )
    inconsistent_trigger = base.trigger.model_copy(
        update={"sample_count": 999, "observed_ng_rate": 0.91}
    )
    request = base.model_copy(
        update={"opcua_snapshot": future_snapshot, "trigger": inconsistent_trigger}
    )
    case = build_industrial_incident_case(request, _gate_context())
    codes = {item.issue_code for item in case.evidence_issues}

    assert case.status is IncidentStatus.EVIDENCE_INCOMPLETE
    assert {
        "SNAPSHOT_TIME_WINDOW_MISMATCH",
        "INCIDENT_SAMPLE_COUNT_MISMATCH",
        "INCIDENT_NG_RATE_MISMATCH",
    } <= codes


def test_exact_capa_recovery_chain_moves_only_to_human_review_candidate() -> None:
    parent = build_industrial_incident_case(
        _request(), _gate_context(decision="QUARANTINE")
    )
    decision_request = IndustrialIncidentDecisionRequest(
        bound_case_sha256=parent.case_sha256,
        decision=IncidentHumanDecision.SELECT_REMEDIATION_PLAN,
        note="选择已绑定证据的最小 CAPA；child Run 恢复后仍只进入人工复核。",
        selected_remediation_plan_id="plan-containment",
        operator_attests_reviewed_evidence=True,
    )
    decision = build_industrial_incident_decision_receipt(
        parent,
        decision_request,
        actor_user_id="usr_fixture_quality_owner",
        decided_at=datetime(2026, 8, 26, 9, 20, tzinfo=UTC),
        linked_capa_case_id="capa_0123456789abcdefabcd",
    )
    refreshed = _request()
    refreshed_context = refreshed.opcua_snapshot.machine_vision_context.model_copy(
        update={"job_id": "job-20260826-43", "result_id": "result-20260826-43"}
    )
    refreshed_snapshot = refreshed.opcua_snapshot.model_copy(
        update={"machine_vision_context": refreshed_context}
    )
    refreshed_run = refreshed.offline_run.model_copy(
        update={
            "run_id": "run-20260826-43",
            "job_id": "job-20260826-43",
            "result_id": "result-20260826-43",
            "sample_index_sha256": _digest("sample-index-43"),
            "result_summary_sha256": _digest("result-summary-43"),
        }
    )
    resumed_request = refreshed.model_copy(
        update={
            "opcua_snapshot": refreshed_snapshot,
            "offline_run": refreshed_run,
            "supersedes_case_id": parent.case_id,
            "expected_parent_case_sha256": parent.case_sha256,
            "authorizing_decision_id": decision.decision_id,
        }
    )
    capa = IncidentCapaEvidence(
        capa_case_id="capa_0123456789abcdefabcd",
        remediation_plan_id="plan-containment",
        selection_sha256=_digest("selection"),
        approval_binding_sha256=_digest("approval"),
        derived_version_receipt_sha256=_digest("derived"),
        execution_receipt_sha256=_digest("execution"),
        recovery_receipt_sha256=_digest("recovery"),
        child_task_id="task_child_43",
        child_evidence_sha256=_digest("child-evidence"),
        recovery_status="RECOVERED_TO_HUMAN_REVIEW",
        recovery_success=True,
    )
    context = _gate_context(decision="QUARANTINE").model_copy(
        update={"child_run_status": "COMPLETED", "capa_evidence": capa}
    )
    child = build_industrial_incident_case(
        resumed_request,
        context,
        parent_case=parent,
        authorizing_decision=decision,
    )

    assert child.status is IncidentStatus.READY_FOR_HUMAN_DECISION
    assert child.recommendation is IncidentRecommendation.RECOVERY_CANDIDATE
    assert child.production_release_allowed is False
    assert child.gate_context.capa_evidence == capa
    assert "capa_recovery" in {item.evidence_type for item in child.evidence_refs}


def test_human_decision_receipt_is_case_bound_and_tamper_evident() -> None:
    case = build_industrial_incident_case(_request(), _gate_context())
    request = IndustrialIncidentDecisionRequest(
        bound_case_sha256=case.case_sha256,
        decision=IncidentHumanDecision.CONTINUE_HOLD,
        note="已复核当前证据，继续保持 HOLD 并补充现场责任人记录。",
        operator_attests_reviewed_evidence=True,
    )
    receipt = build_industrial_incident_decision_receipt(
        case,
        request,
        actor_user_id="usr_fixture_quality_owner",
        decided_at=datetime(2026, 8, 26, 9, 0, tzinfo=UTC),
    )

    verify_industrial_incident_decision_receipt(receipt, case=case)
    assert receipt.production_release_allowed is False
    assert receipt.equipment_control_allowed is False

    tampered = receipt.model_copy(update={"note": "tampered decision"})
    with pytest.raises(ValueError, match="integrity"):
        verify_industrial_incident_decision_receipt(tampered, case=case)


def test_plan_selection_decision_requires_a_real_linked_capa_case() -> None:
    case = build_industrial_incident_case(
        _request(), _gate_context(decision="QUARANTINE")
    )
    request = IndustrialIncidentDecisionRequest(
        bound_case_sha256=case.case_sha256,
        decision=IncidentHumanDecision.SELECT_REMEDIATION_PLAN,
        note="选择最小整改方案，后续仍需独立批准、执行与 child Run 复验。",
        selected_remediation_plan_id="plan-containment",
        operator_attests_reviewed_evidence=True,
    )

    with pytest.raises(ValueError, match="requires a created CAPA case"):
        build_industrial_incident_decision_receipt(
            case,
            request,
            actor_user_id="usr_fixture_quality_owner",
            decided_at=datetime(2026, 8, 26, 9, 5, tzinfo=UTC),
        )

    receipt = build_industrial_incident_decision_receipt(
        case,
        request,
        actor_user_id="usr_fixture_quality_owner",
        decided_at=datetime(2026, 8, 26, 9, 5, tzinfo=UTC),
        linked_capa_case_id="capa_0123456789abcdefabcd",
    )
    verify_industrial_incident_decision_receipt(receipt, case=case)


def test_v2_requires_and_hash_binds_all_four_industrial_sources() -> None:
    request = _request()
    payload = request.model_dump(mode="json")
    payload["schema_version"] = "visiondata-gate.industrial-incident-request.v2"
    payload.pop("runtime_profile")
    payload.pop("expected_parent_case_sha256")
    payload.pop("authorizing_decision_id")
    payload.pop("batch_trace_record")
    with pytest.raises(ValidationError, match="batch_trace_record"):
        parse_industrial_incident_request(payload)

    payload = request.model_dump(mode="json")
    payload["schema_version"] = "visiondata-gate.industrial-incident-request.v2"
    payload.pop("runtime_profile")
    payload.pop("expected_parent_case_sha256")
    payload.pop("authorizing_decision_id")
    payload["production_change_records"] = []
    with pytest.raises(ValidationError, match="production_change_records"):
        parse_industrial_incident_request(payload)

    case = build_industrial_incident_case(request, _gate_context())
    evidence_types = {item.evidence_type for item in case.evidence_refs}
    assert {
        "quality_inspection_result",
        "batch_trace_record",
        "production_change_record",
        "opcua_snapshot",
    } <= evidence_types
    manufacturing_receipt = next(
        item
        for item in case.worker_receipts
        if item.worker_role == "ManufacturingContextAgent"
    )
    assert manufacturing_receipt.status == "SUCCEEDED"
    assert case.root_cause_status == "NOT_ESTABLISHED"


def test_legacy_v1_without_manufacturing_records_is_readable_but_fails_closed() -> None:
    payload = _legacy_request_payload("visiondata-gate.industrial-incident-request.v1")
    request = parse_industrial_incident_request(payload)

    case = build_industrial_incident_case(request, _gate_context())
    codes = {item.issue_code for item in case.evidence_issues}
    assert case.status is IncidentStatus.EVIDENCE_INCOMPLETE
    assert {
        "BATCH_TRACE_RECORD_MISSING",
        "PRODUCTION_CHANGE_RECORD_MISSING",
        "WORK_ORDER_CORRELATION_MISSING",
    } <= codes


def test_manufacturing_context_detects_identity_quality_and_time_conflicts() -> None:
    base = _request()
    conflicting_batch = _reseal_batch(
        base.batch_trace_record,
        batch_id="batch-conflict",
        production_window_start=base.trigger.triggered_at - timedelta(hours=3),
        production_window_end=base.trigger.triggered_at - timedelta(hours=2),
        exported_at=base.trigger.triggered_at - timedelta(hours=1, minutes=59),
    )
    request = base.model_copy(update={"batch_trace_record": conflicting_batch})

    case = build_industrial_incident_case(request, _gate_context())
    codes = {item.issue_code for item in case.evidence_issues}
    assert case.status is IncidentStatus.EVIDENCE_INCOMPLETE
    assert {
        "BATCH_IDENTITY_CONFLICT",
        "QUALITY_RESULT_BATCH_MISMATCH",
        "PRODUCTION_RECORD_TIME_WINDOW_MISMATCH",
    } <= codes


def test_manufacturing_context_requires_unique_work_order_and_authority() -> None:
    base = _request()
    unbound_change = _reseal_change(
        base.production_change_records[0],
        change_status="DRAFT",
        authority_status=ManufacturingRecordAuthorityStatus.NOT_VERIFIED,
        source_authorization_sha256=None,
    )
    run = base.offline_run.model_copy(update={"work_order_id": None})
    request = base.model_copy(
        update={
            "offline_run": run,
            "production_change_records": [unbound_change],
        }
    )

    case = build_industrial_incident_case(request, _gate_context())
    codes = {item.issue_code for item in case.evidence_issues}
    assert case.status is IncidentStatus.EVIDENCE_INCOMPLETE
    assert {
        "WORK_ORDER_CORRELATION_MISSING",
        "CHANGEOVER_RECORD_NOT_AUTHORITY_BOUND",
    } <= codes


def test_production_change_only_updates_hypothesis_edges_not_root_cause() -> None:
    contradicted = build_industrial_incident_case(_request(), _gate_context())
    contradicted_process = next(
        item
        for item in contradicted.hypotheses
        if item.hypothesis_id == "H-PROCESS-DEVIATION"
    )
    assert "PRODUCTION_CHANGE_CONTRADICTS_PROCESS_HYPOTHESIS" in (
        contradicted_process.contradicting_issue_codes
    )
    assert any(
        edge.hypothesis_id == "H-PROCESS-DEVIATION" and edge.relation == "CONTRADICTS"
        for edge in contradicted.evidence_edges
    )

    supported = build_industrial_incident_case(
        _request(observation_value=96.0), _gate_context()
    )
    supported_process = next(
        item
        for item in supported.hypotheses
        if item.hypothesis_id == "H-PROCESS-DEVIATION"
    )
    assert "PRODUCTION_CHANGE_SUPPORTS_PROCESS_HYPOTHESIS" in (
        supported_process.supporting_issue_codes
    )
    assert supported.status is IncidentStatus.INVESTIGATION_REQUIRED
    assert supported.root_cause_status == "NOT_ESTABLISHED"
    assert supported.production_release_allowed is False


def test_tampered_manufacturing_record_and_failed_worker_are_rejected() -> None:
    base = _request()
    tampered_batch = base.batch_trace_record.model_copy(
        update={"lot_reference": "tampered-lot"}
    )
    with pytest.raises(ValueError, match="batch trace record.*integrity"):
        build_industrial_incident_case(
            base.model_copy(update={"batch_trace_record": tampered_batch}),
            _gate_context(),
        )

    case = build_industrial_incident_case(base, _gate_context())
    receipt = next(item for item in case.worker_receipts if item.output_issues)
    failed = receipt.model_copy(
        update={"status": "FAILED", "error_code": "TOOL_EXECUTION_FAILED"}
    )
    receipt_payload = failed.model_dump(mode="json")
    receipt_payload.pop("receipt_sha256")
    failed = failed.model_copy(
        update={
            "receipt_sha256": hashlib.sha256(
                canonical_json_bytes(receipt_payload)
            ).hexdigest()
        }
    )
    with pytest.raises(ValueError, match="failed incident Worker"):
        verify_incident_worker_receipt(failed)


def _legacy_request_payload(schema_version: str) -> dict:
    payload = _request().model_dump(mode="json")
    payload["schema_version"] = schema_version
    payload.pop("runtime_profile", None)
    payload.pop("expected_parent_case_sha256", None)
    payload.pop("authorizing_decision_id", None)
    if schema_version == "visiondata-gate.industrial-incident-request.v1":
        payload.pop("batch_trace_record", None)
        payload.pop("production_change_records", None)
        payload.pop("max_production_record_skew_seconds", None)
        payload.pop("max_change_lookback_seconds", None)
    return payload


@pytest.mark.parametrize(
    ("schema_version", "expected_type"),
    [
        (
            "visiondata-gate.industrial-incident-request.v1",
            IndustrialIncidentRequestV1,
        ),
        (
            "visiondata-gate.industrial-incident-request.v2",
            IndustrialIncidentRequestV2,
        ),
    ],
)
def test_legacy_request_roundtrip_preserves_field_set_and_canonical_sha(
    schema_version: str,
    expected_type: type,
) -> None:
    payload = _legacy_request_payload(schema_version)
    expected_sha = hashlib.sha256(canonical_json_bytes(payload)).hexdigest()

    request = parse_industrial_incident_request(payload)
    roundtrip = request.model_dump(mode="json")

    assert isinstance(request, expected_type)
    assert roundtrip == payload
    assert "runtime_profile" not in roundtrip
    assert hashlib.sha256(canonical_json_bytes(roundtrip)).hexdigest() == expected_sha


def test_legacy_v1_allows_original_single_resume_pointer() -> None:
    payload = _legacy_request_payload("visiondata-gate.industrial-incident-request.v1")
    payload["supersedes_case_id"] = "incident_aaaaaaaaaaaaaaaaaaaa"

    request = parse_industrial_incident_request(payload)

    assert isinstance(request, IndustrialIncidentRequestV1)
    assert request.supersedes_case_id == "incident_aaaaaaaaaaaaaaaaaaaa"
    assert request.model_dump(mode="json") == payload


def test_v3_request_requires_explicit_runtime_profile() -> None:
    payload = _request().model_dump(mode="json")
    payload.pop("runtime_profile", None)

    with pytest.raises(ValidationError, match="runtime_profile"):
        parse_industrial_incident_request(payload)


def test_legacy_case_roundtrip_does_not_inject_new_version_fields() -> None:
    current = build_industrial_incident_case(_request(), _gate_context())
    payload = current.model_dump(mode="json")
    payload["schema_version"] = "visiondata-gate.industrial-incident-case.v2"
    for field_name in (
        "incident_root_id",
        "audit_envelope_requirement",
        "parent_case_sha256",
        "authorizing_decision_id",
        "authorizing_decision_sha256",
        "evidence_bundle_sha256",
        "evidence_edges",
        "planning_belief_ledger",
        "worker_selection_receipt",
        "parent_belief_revision_receipt",
        "worker_execution_plan_receipt",
        "council_arbitration_receipt",
        "autonomy_guard_receipt",
        "worker_receipts",
        "model_planner_receipt",
        "progress_ledger",
    ):
        payload.pop(field_name, None)
    payload["request"] = _legacy_request_payload(
        "visiondata-gate.industrial-incident-request.v1"
    )
    stable = dict(payload)
    stable.pop("case_sha256")
    payload["case_sha256"] = hashlib.sha256(canonical_json_bytes(stable)).hexdigest()

    case = parse_industrial_incident_case(payload)
    verify_industrial_incident_case(case)

    assert case.model_dump(mode="json") == payload
    assert isinstance(case.request, IndustrialIncidentRequestV1)
    assert case.schema_version == "visiondata-gate.industrial-incident-case.v2"


def test_case_audit_requirement_is_explicitly_schema_versioned() -> None:
    governed = build_industrial_incident_case(_request(), _gate_context())

    assert governed.schema_version == GOVERNED_INCIDENT_CASE_SCHEMA_VERSION
    assert governed.audit_envelope_requirement == GOVERNED_AUDIT_ENVELOPE_REQUIREMENT
    assert governed.planning_belief_ledger is not None
    assert governed.planning_belief_ledger.case_id == governed.case_id
    assert governed.worker_selection_receipt is not None
    assert incident_case_requires_governed_audit_envelope(governed) is True

    v4_payload = governed.model_dump(mode="json")
    v4_payload["schema_version"] = "visiondata-gate.industrial-incident-case.v4"
    v4_payload.pop("planning_belief_ledger")
    v4_payload.pop("worker_selection_receipt")
    v4_payload.pop("parent_belief_revision_receipt")
    v4_payload.pop("worker_execution_plan_receipt")
    v4_payload.pop("council_arbitration_receipt")
    v4_payload.pop("autonomy_guard_receipt")
    v4_stable = dict(v4_payload)
    v4_stable.pop("case_sha256")
    v4_payload["case_sha256"] = hashlib.sha256(
        canonical_json_bytes(v4_stable)
    ).hexdigest()
    governed_v4 = parse_industrial_incident_case(v4_payload)
    assert incident_case_requires_governed_audit_envelope(governed_v4) is True
    verify_industrial_incident_case(governed_v4)

    fixture_root = (
        Path(__file__).parent / "fixtures" / "runtime_workbench" / "legacy_cases"
    )
    legacy = parse_industrial_incident_case_json(
        (fixture_root / "case_v3_transition_real_20260826.json").read_bytes()
    )
    assert legacy.audit_envelope_requirement is None
    assert incident_case_requires_governed_audit_envelope(legacy) is False


@pytest.mark.parametrize(
    ("fixture_name", "expected_case_sha256", "expected_request_sha256"),
    [
        (
            "case_v2_root_real_20260826.json",
            "7c781fd1330c837a8dd3d9141a16b89fa1ee0ba2d7a1bd8067d30d4100302b69",
            "356849006ee0ecae5dff7519148b079586d16e9376abb1eed6b6345e85008614",
        ),
        (
            "case_v2_resume_real_20260826.json",
            "59db352ec1414d93712987548f7cbbe86b1a322a2324d53b72a98f5d4d0c40cd",
            "09031c687bcf7d64a0ba3c5a2de0c322c40969df531eae5fa5c3c98835a797c5",
        ),
        (
            "case_v3_transition_real_20260826.json",
            "1b6803cc9946d9e5fafe684a2b211fd05e037a40ee07925c202a663d63263c5c",
            "76b8a3cb6087df8571a38411d2f7828d6b0cf74b37d8a519cae4b6f50ddbc4a4",
        ),
    ],
)
def test_real_legacy_case_goldens_keep_original_shape_and_sha(
    fixture_name: str,
    expected_case_sha256: str,
    expected_request_sha256: str,
) -> None:
    fixture_path = (
        Path(__file__).parent
        / "fixtures"
        / "runtime_workbench"
        / "legacy_cases"
        / fixture_name
    )
    raw = json.loads(fixture_path.read_text(encoding="utf-8"))

    case = parse_industrial_incident_case(raw)
    roundtrip = case.model_dump(mode="json")

    assert roundtrip == raw
    assert case.case_sha256 == expected_case_sha256
    assert "runtime_profile" not in roundtrip["request"]
    assert (
        hashlib.sha256(canonical_json_bytes(roundtrip["request"])).hexdigest()
        == expected_request_sha256
    )
    stable = dict(roundtrip)
    stable.pop("case_sha256")
    assert hashlib.sha256(canonical_json_bytes(stable)).hexdigest() == (
        expected_case_sha256
    )


def test_unknown_request_schema_fails_closed() -> None:
    payload = _request().model_dump(mode="json")
    payload["schema_version"] = "visiondata-gate.industrial-incident-request.v99"

    with pytest.raises(ValidationError, match="union_tag_invalid"):
        parse_industrial_incident_request(payload)


def test_real_transition_case_phase_event_chain_still_verifies() -> None:
    fixture_root = (
        Path(__file__).parent / "fixtures" / "runtime_workbench" / "legacy_cases"
    )
    case = parse_industrial_incident_case_json(
        (fixture_root / "case_v3_transition_real_20260826.json").read_bytes()
    )
    raw_events = json.loads(
        (fixture_root / "case_v3_transition_phase_events_real_20260826.json").read_text(
            encoding="utf-8"
        )
    )
    events = [IncidentPhaseEvent.model_validate(item) for item in raw_events]

    verify_incident_phase_events(case, events)

    assert len(events) == 9
    assert events[-1].event_sha256 == (
        "02057118642b6d7e74d21d3f5f7a8edb3c350abdd0a06a6b86e9fd48318969cc"
    )


def test_incident_canvas_shows_bounded_loop_without_hidden_or_competitor_copy() -> None:
    case = build_industrial_incident_case(
        build_fixture_industrial_incident_request(),
        _gate_context(decision="QUARANTINE"),
    )
    rendered = build_incident_canvas(case)

    assert "理解异常" in rendered
    assert "专业补证" in rendered
    assert "人工决定" in rendered
    assert "FIXTURE，仅验证闭环" in rendered
    assert "LingxiGraph" not in rendered
    assert "Agentero" not in rendered
    assert "C:\\" not in rendered
