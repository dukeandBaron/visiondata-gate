from __future__ import annotations

import hashlib
from datetime import UTC, datetime

import pytest

from visiondata_gate.demo_fixtures import build_fixture_industrial_incident_request
from visiondata_gate.incident_agent_kernel import (
    verify_worker_execution_plan_receipt_v1,
)
from visiondata_gate.industrial_incident import (
    AGENT_KERNEL_INCIDENT_CASE_SCHEMA_VERSION,
    IncidentHumanDecision,
    IncidentWorkerExecutionError,
    IncidentWorkerRegistry,
    IndustrialGateContext,
    IndustrialIncidentDecisionRequest,
    build_industrial_incident_case,
    build_industrial_incident_decision_receipt,
    verify_industrial_incident_case,
)


def _digest(label: str) -> str:
    return hashlib.sha256(label.encode("utf-8")).hexdigest()


def _gate_context(
    *, authorization_event: str = "authorization-v1"
) -> IndustrialGateContext:
    return IndustrialGateContext(
        task_id="task_0123456789abcdef",
        gate_final_decision="HOLD",
        task_evidence_sha256=_digest("task-evidence"),
        industrial_delivery_sha256=_digest("industrial-delivery"),
        source_profile_sha256=_digest("source-profile"),
        source_authorization_event_sha256=_digest(authorization_event),
        source_authorization_status="ACTIVE",
        dynamic_response_count=3,
        open_work_order_count=49,
        remediation_plan_ids=["plan-containment"],
        model_call_count=0,
    )


def test_v6_seals_execution_council_and_autonomy_contracts() -> None:
    case = build_industrial_incident_case(
        build_fixture_industrial_incident_request(),
        _gate_context(),
    )

    assert case.schema_version == AGENT_KERNEL_INCIDENT_CASE_SCHEMA_VERSION
    assert case.parent_belief_revision_receipt is None
    assert case.worker_execution_plan_receipt is not None
    assert case.council_arbitration_receipt is not None
    assert case.autonomy_guard_receipt is not None
    assert case.autonomy_guard_receipt.allowed_model_effect == "NONE"
    assert case.autonomy_guard_receipt.model_call_count == 0
    assert case.council_arbitration_receipt.root_cause_status == "NOT_ESTABLISHED"

    plan = case.worker_execution_plan_receipt
    counter_node = next(
        item for item in plan.nodes if item.worker_id == "CounterevidenceAuditorAgent"
    )
    assert plan.execution_order[-1] == "CounterevidenceAuditorAgent"
    assert set(counter_node.dependency_worker_ids) == (
        set(case.worker_selection_receipt.selected_worker_ids)
        - {"CounterevidenceAuditorAgent"}
    )
    verify_industrial_incident_case(case)


def test_resume_seals_parent_belief_epoch_revision_without_mutating_parent() -> None:
    parent = build_industrial_incident_case(
        build_fixture_industrial_incident_request(revision=1),
        _gate_context(),
    )
    decision = build_industrial_incident_decision_receipt(
        parent,
        IndustrialIncidentDecisionRequest(
            bound_case_sha256=parent.case_sha256,
            decision=IncidentHumanDecision.CONTINUE_HOLD,
            note="具名复核后继续 HOLD，并以新的离线证据创建 child Case。",
            operator_attests_reviewed_evidence=True,
        ),
        actor_user_id="usr_fixture_quality_owner",
        decided_at=datetime(2026, 8, 26, 9, 0, tzinfo=UTC),
    )
    request = build_fixture_industrial_incident_request(revision=2).model_copy(
        update={
            "supersedes_case_id": parent.case_id,
            "expected_parent_case_sha256": parent.case_sha256,
            "authorizing_decision_id": decision.decision_id,
        }
    )

    child = build_industrial_incident_case(
        request,
        _gate_context(),
        parent_case=parent,
        authorizing_decision=decision,
    )

    revision = child.parent_belief_revision_receipt
    assert revision is not None
    assert revision.parent_case_sha256 == parent.case_sha256
    assert revision.source_ledger_sha256 == parent.planning_belief_ledger.ledger_sha256
    assert revision.evidence_bundle_changed is True
    assert revision.disposition == "STALE_REPLAN_REQUIRED"
    assert revision.fresh_replan_required is True
    assert parent.parent_belief_revision_receipt is None
    verify_industrial_incident_case(parent)
    verify_industrial_incident_case(child)


def test_counterevidence_dependency_failure_is_sealed_and_fail_closed() -> None:
    roles = {
        "EvidenceQualificationAgent",
        "ManufacturingContextAgent",
        "SignalIntegrityAgent",
        "TraceabilityAgent",
        "ProcessContextAgent",
        "VisionRecipeAgent",
        "VisualDataQualityAgent",
        "CounterevidenceAuditorAgent",
    }

    class FailingRegistry(IncidentWorkerRegistry):
        def execute(self, **values):  # type: ignore[no-untyped-def]
            if values["worker_role"] == "ProcessContextAgent":
                raise IncidentWorkerExecutionError("PROCESS_TOOL_UNAVAILABLE")
            return super().execute(**values)

    case = build_industrial_incident_case(
        build_fixture_industrial_incident_request(),
        _gate_context(),
        worker_registry=FailingRegistry(roles),
    )

    receipts = {item.worker_role: item for item in case.worker_receipts}
    process_receipt = receipts["ProcessContextAgent"]
    counter_receipt = receipts["CounterevidenceAuditorAgent"]
    assert process_receipt.status == "FAILED"
    assert counter_receipt.status == "FAILED"
    assert counter_receipt.error_code == "DEPENDENCY_BARRIER_FAILED"
    assert process_receipt.receipt_sha256 in counter_receipt.input_evidence_sha256
    assert case.council_arbitration_receipt.policy_directive == "FAIL_CLOSED"
    verify_industrial_incident_case(case)


def test_execution_plan_digest_rejects_dependency_tampering() -> None:
    case = build_industrial_incident_case(
        build_fixture_industrial_incident_request(),
        _gate_context(),
    )
    plan = case.worker_execution_plan_receipt
    assert plan is not None
    tampered_node = plan.nodes[-1].model_copy(update={"dependency_worker_ids": []})
    tampered = plan.model_copy(update={"nodes": [*plan.nodes[:-1], tampered_node]})

    with pytest.raises(ValueError, match="barrier count|digest mismatch"):
        verify_worker_execution_plan_receipt_v1(tampered)
