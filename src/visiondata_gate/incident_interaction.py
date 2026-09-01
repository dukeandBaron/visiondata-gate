"""Observable multi-turn interaction receipts for industrial Incident Cases.

The Incident runtime already pauses for structured operator questions and can
resume only after a named human decision.  This module makes that state change
independently replayable without storing hidden chain-of-thought or treating a
free-text reply as evidence.
"""

from __future__ import annotations

import hashlib
from typing import Literal

from pydantic import Field

from .evidence import canonical_json_bytes
from .industrial_incident import (
    IncidentEvidenceRef,
    IndustrialIncidentCase,
    IndustrialIncidentDecisionConsumptionReceipt,
    IndustrialIncidentDecisionReceipt,
    verify_incident_decision_consumption_receipt,
    verify_industrial_incident_case,
    verify_industrial_incident_decision_receipt,
)
from .product_models import ProductModel


_INTERACTION_HASH_DOMAIN = b"visiondata-gate/incident-interaction-receipt/v1"

_QUESTION_EVIDENCE_TYPES: dict[str, frozenset[str]] = {
    "opcua_snapshot": frozenset({"opcua_snapshot"}),
    "traceability_receipt": frozenset(
        {"batch_trace_record", "production_change_record"}
    ),
    "batch_trace_record": frozenset({"batch_trace_record"}),
    "production_change_record": frozenset({"production_change_record"}),
    "vision_solution_manifest": frozenset({"vision_solution_manifest"}),
    "offline_vision_run": frozenset({"offline_vision_run"}),
}


def _receipt_digest(value: object) -> str:
    payload = canonical_json_bytes(value)
    framed = (
        b"VDG-INTERACTION-V1\x00"
        + len(_INTERACTION_HASH_DOMAIN).to_bytes(2, "big")
        + _INTERACTION_HASH_DOMAIN
        + len(payload).to_bytes(8, "big")
        + payload
    )
    return hashlib.sha256(framed).hexdigest()


class IncidentInteractionTurn(ProductModel):
    sequence: int = Field(ge=1)
    actor_kind: Literal["AGENT", "HUMAN"]
    actor_id: str = Field(min_length=1, max_length=160)
    action: str = Field(min_length=1, max_length=160)
    input_refs: list[str]
    output_refs: list[str]
    observable_only: Literal[True] = True


class IncidentQuestionResolution(ProductModel):
    question_id: str = Field(pattern=r"^question_[0-9a-f]{12}$")
    expected_evidence_type: str = Field(min_length=1, max_length=80)
    disposition: Literal[
        "ANSWERED_BY_ADMITTED_EVIDENCE",
        "SATISFIED_BY_NAMED_HUMAN_DECISION",
        "REMAINS_OPEN",
    ]
    supporting_refs: list[str]
    auto_closed_from_free_text: Literal[False] = False


class IncidentInteractionReceipt(ProductModel):
    """Three-turn pause/decision/resume proof derived from immutable artifacts."""

    schema_version: Literal["visiondata-gate.incident-interaction-receipt.v1"] = (
        "visiondata-gate.incident-interaction-receipt.v1"
    )
    interaction_id: str = Field(pattern=r"^interaction_[0-9a-f]{20}$")
    task_id: str = Field(min_length=1)
    parent_case_id: str = Field(pattern=r"^incident_[0-9a-f]{20}$")
    parent_case_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    decision_id: str = Field(pattern=r"^incident_decision_[0-9a-f]{20}$")
    decision_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    child_case_id: str = Field(pattern=r"^incident_[0-9a-f]{20}$")
    child_case_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    consumption_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    turns: list[IncidentInteractionTurn] = Field(min_length=3, max_length=3)
    admitted_evidence_refs: list[str]
    question_resolutions: list[IncidentQuestionResolution]
    answered_by_evidence_count: int = Field(ge=0)
    satisfied_by_human_decision_count: int = Field(ge=0)
    remaining_open_question_count: int = Field(ge=0)
    interaction_status: Literal[
        "RESUMED_ALL_QUESTIONS_RESOLVED",
        "RESUMED_WITH_OPEN_QUESTIONS",
    ]
    multi_turn_state_transition_verified: Literal[True] = True
    hidden_chain_of_thought_retained: Literal[False] = False
    production_release_allowed: Literal[False] = False
    machine_write_permitted: Literal[False] = False
    receipt_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    claim_boundary: str = (
        "This receipt proves one observable pause, named-human decision, and immutable "
        "resume transition. It does not prove that every operator question was answered, "
        "that free text is evidence, that root cause was established, or that production "
        "release or equipment control was authorized."
    )


def _admitted_child_evidence(
    parent_case: IndustrialIncidentCase,
    child_case: IndustrialIncidentCase,
) -> list[IncidentEvidenceRef]:
    parent_tokens = {
        (item.evidence_type, item.evidence_ref, item.evidence_sha256)
        for item in parent_case.evidence_refs
    }
    return sorted(
        (
            item
            for item in child_case.evidence_refs
            if (item.evidence_type, item.evidence_ref, item.evidence_sha256)
            not in parent_tokens
        ),
        key=lambda item: (item.evidence_type, item.evidence_ref, item.evidence_sha256),
    )


def build_incident_interaction_receipt(
    *,
    parent_case: IndustrialIncidentCase,
    decision: IndustrialIncidentDecisionReceipt,
    child_case: IndustrialIncidentCase,
    consumption: IndustrialIncidentDecisionConsumptionReceipt,
) -> IncidentInteractionReceipt:
    """Build a replayable multi-turn receipt from already-verified artifacts."""

    verify_industrial_incident_case(parent_case)
    verify_industrial_incident_decision_receipt(decision, case=parent_case)
    verify_industrial_incident_case(child_case)
    verify_incident_decision_consumption_receipt(consumption)
    if not (
        consumption.parent_case_id == parent_case.case_id
        and consumption.parent_case_sha256 == parent_case.case_sha256
        and consumption.decision_id == decision.decision_id
        and consumption.decision_sha256 == decision.decision_sha256
        and consumption.child_case_id == child_case.case_id
        and consumption.child_case_sha256 == child_case.case_sha256
        and child_case.parent_case_id == parent_case.case_id
        and child_case.authorizing_decision_id == decision.decision_id
    ):
        raise ValueError("incident interaction lost pause/decision/resume lineage")

    admitted = _admitted_child_evidence(parent_case, child_case)
    admitted_refs = sorted({item.evidence_ref for item in admitted})
    admitted_by_type: dict[str, list[str]] = {}
    for item in admitted:
        admitted_by_type.setdefault(item.evidence_type, []).append(item.evidence_ref)

    resolutions: list[IncidentQuestionResolution] = []
    for question in sorted(
        parent_case.operator_questions, key=lambda item: item.question_id
    ):
        if question.expected_evidence_type == "quality_owner_decision":
            disposition = "SATISFIED_BY_NAMED_HUMAN_DECISION"
            supporting_refs = [decision.decision_id]
        else:
            accepted_types = _QUESTION_EVIDENCE_TYPES.get(
                question.expected_evidence_type,
                frozenset(),
            )
            supporting_refs = sorted(
                {
                    evidence_ref
                    for evidence_type in accepted_types
                    for evidence_ref in admitted_by_type.get(evidence_type, [])
                }
            )
            disposition = (
                "ANSWERED_BY_ADMITTED_EVIDENCE" if supporting_refs else "REMAINS_OPEN"
            )
        resolutions.append(
            IncidentQuestionResolution(
                question_id=question.question_id,
                expected_evidence_type=question.expected_evidence_type,
                disposition=disposition,
                supporting_refs=supporting_refs,
            )
        )

    answered_count = sum(
        item.disposition == "ANSWERED_BY_ADMITTED_EVIDENCE" for item in resolutions
    )
    human_count = sum(
        item.disposition == "SATISFIED_BY_NAMED_HUMAN_DECISION" for item in resolutions
    )
    open_count = sum(item.disposition == "REMAINS_OPEN" for item in resolutions)
    turns = [
        IncidentInteractionTurn(
            sequence=1,
            actor_kind="AGENT",
            actor_id="IncidentCoordinatorAgent",
            action="PAUSE_FOR_STRUCTURED_HUMAN_INPUT",
            input_refs=[parent_case.case_sha256],
            output_refs=[item.question_id for item in parent_case.operator_questions]
            or [parent_case.case_id],
        ),
        IncidentInteractionTurn(
            sequence=2,
            actor_kind="HUMAN",
            actor_id=decision.actor_user_id,
            action=decision.decision.value,
            input_refs=[parent_case.case_sha256],
            output_refs=[decision.decision_sha256],
        ),
        IncidentInteractionTurn(
            sequence=3,
            actor_kind="AGENT",
            actor_id="IncidentCoordinatorAgent",
            action="RESUME_WITH_BOUND_DECISION",
            input_refs=[
                parent_case.case_sha256,
                decision.decision_sha256,
                *admitted_refs,
            ],
            output_refs=[child_case.case_sha256],
        ),
    ]
    identity_payload = {
        "parent_case_sha256": parent_case.case_sha256,
        "decision_sha256": decision.decision_sha256,
        "child_case_sha256": child_case.case_sha256,
        "consumption_sha256": consumption.consumption_sha256,
    }
    stable = {
        "schema_version": "visiondata-gate.incident-interaction-receipt.v1",
        "interaction_id": f"interaction_{_receipt_digest(identity_payload)[:20]}",
        "task_id": child_case.task_id,
        "parent_case_id": parent_case.case_id,
        "parent_case_sha256": parent_case.case_sha256,
        "decision_id": decision.decision_id,
        "decision_sha256": decision.decision_sha256,
        "child_case_id": child_case.case_id,
        "child_case_sha256": child_case.case_sha256,
        "consumption_sha256": consumption.consumption_sha256,
        "turns": turns,
        "admitted_evidence_refs": admitted_refs,
        "question_resolutions": resolutions,
        "answered_by_evidence_count": answered_count,
        "satisfied_by_human_decision_count": human_count,
        "remaining_open_question_count": open_count,
        "interaction_status": (
            "RESUMED_WITH_OPEN_QUESTIONS"
            if open_count
            else "RESUMED_ALL_QUESTIONS_RESOLVED"
        ),
        "multi_turn_state_transition_verified": True,
        "hidden_chain_of_thought_retained": False,
        "production_release_allowed": False,
        "machine_write_permitted": False,
        "claim_boundary": IncidentInteractionReceipt.model_fields[
            "claim_boundary"
        ].default,
    }
    return IncidentInteractionReceipt(
        **stable,
        receipt_sha256=_receipt_digest(stable),
    )


def verify_incident_interaction_receipt(
    receipt: IncidentInteractionReceipt,
    *,
    parent_case: IndustrialIncidentCase,
    decision: IndustrialIncidentDecisionReceipt,
    child_case: IndustrialIncidentCase,
    consumption: IndustrialIncidentDecisionConsumptionReceipt,
) -> None:
    """Rebuild the observable interaction and reject semantic or digest drift."""

    expected = build_incident_interaction_receipt(
        parent_case=parent_case,
        decision=decision,
        child_case=child_case,
        consumption=consumption,
    )
    if receipt != expected:
        raise ValueError("incident interaction receipt diverged from source artifacts")


__all__ = [
    "IncidentInteractionReceipt",
    "IncidentInteractionTurn",
    "IncidentQuestionResolution",
    "build_incident_interaction_receipt",
    "verify_incident_interaction_receipt",
]
