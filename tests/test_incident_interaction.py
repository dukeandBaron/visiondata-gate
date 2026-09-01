from __future__ import annotations

from datetime import UTC, datetime

import pytest

from visiondata_gate.demo_fixtures import build_fixture_industrial_incident_request
from visiondata_gate.incident_interaction import (
    build_incident_interaction_receipt,
    verify_incident_interaction_receipt,
)
from visiondata_gate.industrial_incident import (
    IncidentHumanDecision,
    IndustrialIncidentDecisionRequest,
    build_incident_decision_consumption_receipt,
    build_industrial_incident_case,
    build_industrial_incident_decision_receipt,
)
from visiondata_gate.industrial_incident_benchmark import _gate_context


def _interaction_fixture():
    context = _gate_context(decision="QUARANTINE")
    parent_request = build_fixture_industrial_incident_request()
    parent = build_industrial_incident_case(parent_request, context)
    decision = build_industrial_incident_decision_receipt(
        parent,
        IndustrialIncidentDecisionRequest(
            bound_case_sha256=parent.case_sha256,
            decision=IncidentHumanDecision.CONTINUE_HOLD,
            note="具名质量负责人允许在保持 HOLD 的前提下接纳新证据并续跑。",
            operator_attests_reviewed_evidence=True,
        ),
        actor_user_id="quality-owner-01",
        decided_at=datetime(2026, 8, 26, 10, 0, tzinfo=UTC),
    )
    child_request = build_fixture_industrial_incident_request(revision=2).model_copy(
        update={
            "supersedes_case_id": parent.case_id,
            "expected_parent_case_sha256": parent.case_sha256,
            "authorizing_decision_id": decision.decision_id,
        }
    )
    child = build_industrial_incident_case(
        child_request,
        context,
        parent_case=parent,
        authorizing_decision=decision,
    )
    consumption = build_incident_decision_consumption_receipt(
        parent_case=parent,
        decision=decision,
        child_case=child,
    )
    return parent, decision, child, consumption


def test_interaction_receipt_proves_observable_pause_decision_resume() -> None:
    parent, decision, child, consumption = _interaction_fixture()

    receipt = build_incident_interaction_receipt(
        parent_case=parent,
        decision=decision,
        child_case=child,
        consumption=consumption,
    )

    assert [turn.sequence for turn in receipt.turns] == [1, 2, 3]
    assert [turn.actor_kind for turn in receipt.turns] == ["AGENT", "HUMAN", "AGENT"]
    assert receipt.turns[1].actor_id == "quality-owner-01"
    assert receipt.admitted_evidence_refs
    assert receipt.answered_by_evidence_count > 0
    assert all(
        not item.auto_closed_from_free_text for item in receipt.question_resolutions
    )
    assert receipt.multi_turn_state_transition_verified is True
    assert receipt.hidden_chain_of_thought_retained is False
    assert receipt.production_release_allowed is False
    verify_incident_interaction_receipt(
        receipt,
        parent_case=parent,
        decision=decision,
        child_case=child,
        consumption=consumption,
    )


def test_interaction_verifier_rejects_question_resolution_drift() -> None:
    parent, decision, child, consumption = _interaction_fixture()
    receipt = build_incident_interaction_receipt(
        parent_case=parent,
        decision=decision,
        child_case=child,
        consumption=consumption,
    )
    tampered = receipt.model_copy(
        update={
            "remaining_open_question_count": receipt.remaining_open_question_count + 1
        }
    )

    with pytest.raises(ValueError, match="diverged from source artifacts"):
        verify_incident_interaction_receipt(
            tampered,
            parent_case=parent,
            decision=decision,
            child_case=child,
            consumption=consumption,
        )
