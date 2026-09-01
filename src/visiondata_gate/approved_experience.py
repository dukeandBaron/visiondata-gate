"""Human-governed experience promotion for industrial incident handling.

The loop evolves reviewed configuration and historical investigation hints.  It
never trains a model, mutates Frozen Policy, grants equipment-control authority,
or turns historical experience into a fact about the current incident.
"""

from __future__ import annotations

import hashlib
import hmac
import json
from datetime import UTC, datetime
from enum import Enum
from pathlib import Path
from typing import Mapping
from typing import Literal

from pydantic import Field, field_validator, model_validator

from .evidence import canonical_json_bytes
from .governed_context import (
    ApprovedMemoryCard,
    ApprovedMemoryContent,
    MemoryScope,
    build_approved_memory_card,
    verify_approved_memory_card,
)
from .product_models import ProductModel


def _sha256(value: object) -> str:
    return hashlib.sha256(canonical_json_bytes(value)).hexdigest()


def _aware(value: datetime) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("experience timestamps must include an explicit UTC offset")
    return value.astimezone(UTC)


class ExperienceState(str, Enum):
    CANDIDATE = "CANDIDATE"
    REPLAY_TESTED = "REPLAY_TESTED"
    HUMAN_APPROVED = "HUMAN_APPROVED"
    SHADOW = "SHADOW"
    PROMOTED = "PROMOTED"
    REJECTED = "REJECTED"
    ROLLED_BACK = "ROLLED_BACK"


class ExperienceCandidateType(str, Enum):
    INVESTIGATION_HINT = "INVESTIGATION_HINT"
    QUESTION_TEMPLATE = "QUESTION_TEMPLATE"
    OUTPUT_TEMPLATE = "OUTPUT_TEMPLATE"
    FIELD_ALIAS = "FIELD_ALIAS"
    WORKER_PRIORITY_HINT = "WORKER_PRIORITY_HINT"


class ExperienceCandidate(ProductModel):
    schema_version: Literal["visiondata-gate.experience-candidate.v1"] = (
        "visiondata-gate.experience-candidate.v1"
    )
    candidate_id: str = Field(pattern=r"^experience_[0-9a-f]{20}$")
    candidate_type: ExperienceCandidateType
    source_case_ids: list[str] = Field(min_length=1, max_length=32)
    proposal: ApprovedMemoryContent
    affected_scope: MemoryScope
    required_replay_suite: str = Field(min_length=1, max_length=160)
    safety_policy_mutation: Literal[False] = False
    evidence_schema_mutation: Literal[False] = False
    equipment_control_enabled: Literal[False] = False
    production_release_enabled: Literal[False] = False
    candidate_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")

    @field_validator("source_case_ids")
    @classmethod
    def unique_source_cases(cls, values: list[str]) -> list[str]:
        if len(values) != len(set(values)):
            raise ValueError("experience source_case_ids must be unique")
        return values


class ExperienceReplayReceipt(ProductModel):
    schema_version: Literal["visiondata-gate.experience-replay.v1"] = (
        "visiondata-gate.experience-replay.v1"
    )
    candidate_id: str
    candidate_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    replay_suite_id: str
    replay_suite_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    evaluated_at: datetime
    case_count: int = Field(ge=1)
    passed_case_count: int = Field(ge=0)
    deterministic_replay_rate: float = Field(ge=0.0, le=1.0)
    unsafe_closure_count: int = Field(ge=0)
    false_root_cause_count: int = Field(ge=0)
    premature_production_recovery_count: int = Field(ge=0)
    cross_site_memory_leakage_count: int = Field(ge=0)
    historical_memory_used_as_fact_count: int = Field(ge=0)
    outcome: Literal["PASS", "FAIL"]
    receipt_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")

    @field_validator("evaluated_at")
    @classmethod
    def validate_evaluated_at(cls, value: datetime) -> datetime:
        return _aware(value)

    @model_validator(mode="after")
    def validate_replay_outcome(self) -> ExperienceReplayReceipt:
        if self.passed_case_count > self.case_count:
            raise ValueError("passed replay cases cannot exceed the fixed denominator")
        passed = (
            self.passed_case_count == self.case_count
            and self.deterministic_replay_rate == 1.0
            and self.unsafe_closure_count == 0
            and self.false_root_cause_count == 0
            and self.premature_production_recovery_count == 0
            and self.cross_site_memory_leakage_count == 0
            and self.historical_memory_used_as_fact_count == 0
        )
        if (self.outcome == "PASS") != passed:
            raise ValueError("experience replay outcome contradicts its hard gates")
        return self


class ExperienceApprovalReceipt(ProductModel):
    schema_version: Literal["visiondata-gate.experience-approval.v1"] = (
        "visiondata-gate.experience-approval.v1"
    )
    candidate_id: str
    candidate_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    replay_receipt_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    actor_user_id: str = Field(min_length=1, max_length=160)
    actor_role: str = Field(min_length=1, max_length=160)
    decided_at: datetime
    decision: Literal["APPROVE", "REJECT"]
    note: str = Field(min_length=8, max_length=1200)
    approval_evidence_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    production_release_authorized: Literal[False] = False
    equipment_control_authorized: Literal[False] = False
    receipt_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")

    @field_validator("decided_at")
    @classmethod
    def validate_decided_at(cls, value: datetime) -> datetime:
        return _aware(value)


class ExperienceShadowReceipt(ProductModel):
    schema_version: Literal["visiondata-gate.experience-shadow.v1"] = (
        "visiondata-gate.experience-shadow.v1"
    )
    candidate_id: str
    candidate_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    approval_receipt_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    observed_at: datetime
    observed_case_count: int = Field(ge=1)
    changed_worker_order_count: int = Field(ge=0)
    unsafe_closure_count: int = Field(ge=0)
    cross_site_memory_leakage_count: int = Field(ge=0)
    historical_memory_used_as_fact_count: int = Field(ge=0)
    outcome: Literal["PASS", "FAIL"]
    receipt_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")

    @field_validator("observed_at")
    @classmethod
    def validate_observed_at(cls, value: datetime) -> datetime:
        return _aware(value)

    @model_validator(mode="after")
    def validate_shadow_outcome(self) -> ExperienceShadowReceipt:
        passed = (
            self.unsafe_closure_count == 0
            and self.cross_site_memory_leakage_count == 0
            and self.historical_memory_used_as_fact_count == 0
        )
        if (self.outcome == "PASS") != passed:
            raise ValueError("experience shadow outcome contradicts its safety gates")
        return self


class ExperienceStateEvent(ProductModel):
    schema_version: Literal["visiondata-gate.experience-state-event.v1"] = (
        "visiondata-gate.experience-state-event.v1"
    )
    event_id: str = Field(pattern=r"^experience_event_[0-9a-f]{20}$")
    sequence: int = Field(ge=1)
    from_state: ExperienceState | None
    to_state: ExperienceState
    actor: str = Field(min_length=1, max_length=160)
    occurred_at: datetime
    reason: str = Field(min_length=3, max_length=1200)
    evidence_sha256: list[str] = Field(default_factory=list, max_length=12)
    previous_event_sha256: str | None = Field(default=None, pattern=r"^[0-9a-f]{64}$")
    event_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")

    @field_validator("occurred_at")
    @classmethod
    def validate_occurred_at(cls, value: datetime) -> datetime:
        return _aware(value)


class ApprovedExperienceRecord(ProductModel):
    schema_version: Literal["visiondata-gate.approved-experience-record.v1"] = (
        "visiondata-gate.approved-experience-record.v1"
    )
    candidate: ExperienceCandidate
    state: ExperienceState
    replay_receipt: ExperienceReplayReceipt | None = None
    approval_receipt: ExperienceApprovalReceipt | None = None
    shadow_receipt: ExperienceShadowReceipt | None = None
    promoted_memory: ApprovedMemoryCard | None = None
    revoked_memory: ApprovedMemoryCard | None = None
    events: list[ExperienceStateEvent] = Field(min_length=1)
    online_model_update_performed: Literal[False] = False
    frozen_policy_mutated: Literal[False] = False
    record_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    claim_boundary: str = (
        "This record governs approved historical experience and configuration hints. "
        "It is not model training, a current-case fact, root-cause proof, CAPA approval, "
        "production release, or equipment-control authority."
    )


class SourceCaseEvidenceBinding(ProductModel):
    schema_version: Literal["visiondata-gate.source-case-evidence-binding.v1"] = (
        "visiondata-gate.source-case-evidence-binding.v1"
    )
    workspace_id: str = Field(min_length=1, max_length=160)
    project_id: str = Field(min_length=1, max_length=160)
    task_id: str = Field(min_length=1, max_length=160)
    case_id: str = Field(min_length=1, max_length=160)
    case_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    case_audit_root_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    scope: MemoryScope
    verification_status: Literal[
        "VERIFIED_LOCAL_CASE", "VERIFIED_ARCHIVED_CASE_RECEIPT"
    ]
    verified_at: datetime
    binding_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")

    @field_validator("verified_at")
    @classmethod
    def validate_verified_at(cls, value: datetime) -> datetime:
        return _aware(value)


class MemoryAdmissionEnvelope(ProductModel):
    schema_version: Literal["visiondata-gate.memory-admission-envelope.v1"] = (
        "visiondata-gate.memory-admission-envelope.v1"
    )
    workspace_id: str = Field(min_length=1, max_length=160)
    project_id: str = Field(min_length=1, max_length=160)
    card: ApprovedMemoryCard
    experience_record: ApprovedExperienceRecord
    source_case_bindings: list[SourceCaseEvidenceBinding] = Field(min_length=1)
    admission_policy_id: Literal["VISIONDATA_STRICT_PROMOTION_CHAIN_V1"] = (
        "VISIONDATA_STRICT_PROMOTION_CHAIN_V1"
    )
    admission_policy_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    admitted_at: datetime
    admitted_by_actor_user_id: str = Field(min_length=1, max_length=160)
    admitted_by_actor_role: str = Field(min_length=1, max_length=160)
    admission_receipt_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    envelope_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    historical_reference_only: Literal[True] = True
    current_case_fact_authority: Literal["none"] = "none"
    production_authority: Literal["none"] = "none"

    @field_validator("admitted_at")
    @classmethod
    def validate_admitted_at(cls, value: datetime) -> datetime:
        return _aware(value)


class MemoryAdmissionStoreReceipt(ProductModel):
    schema_version: Literal["visiondata-gate.memory-admission-store-receipt.v1"] = (
        "visiondata-gate.memory-admission-store-receipt.v1"
    )
    store_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    workspace_id: str = Field(min_length=1, max_length=160)
    project_id: str = Field(min_length=1, max_length=160)
    entry_count: int = Field(ge=0)
    envelope_sha256: list[str]
    memory_sha256: list[str]
    source_case_binding_count: int = Field(ge=0)
    admission_status: Literal["STRICT_PROMOTION_CHAIN_VERIFIED"] = (
        "STRICT_PROMOTION_CHAIN_VERIFIED"
    )
    receipt_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")


_ALLOWED_TRANSITIONS: set[tuple[ExperienceState | None, ExperienceState]] = {
    (None, ExperienceState.CANDIDATE),
    (ExperienceState.CANDIDATE, ExperienceState.REPLAY_TESTED),
    (ExperienceState.CANDIDATE, ExperienceState.REJECTED),
    (ExperienceState.REPLAY_TESTED, ExperienceState.HUMAN_APPROVED),
    (ExperienceState.REPLAY_TESTED, ExperienceState.REJECTED),
    (ExperienceState.HUMAN_APPROVED, ExperienceState.SHADOW),
    (ExperienceState.HUMAN_APPROVED, ExperienceState.REJECTED),
    (ExperienceState.SHADOW, ExperienceState.PROMOTED),
    (ExperienceState.SHADOW, ExperienceState.REJECTED),
    (ExperienceState.SHADOW, ExperienceState.ROLLED_BACK),
    (ExperienceState.PROMOTED, ExperienceState.ROLLED_BACK),
}

_STRICT_ADMISSION_POLICY = {
    "policy_id": "VISIONDATA_STRICT_PROMOTION_CHAIN_V1",
    "required_terminal_state": "PROMOTED",
    "required_replay_outcome": "PASS",
    "required_human_decision": "APPROVE",
    "required_shadow_outcome": "PASS",
    "source_case_resolution": "EXACT_REGISTRY_MATCH",
    "tenant_scope": ["workspace_id", "project_id"],
    "historical_reference_only": True,
    "current_case_fact_authority": "none",
    "production_authority": "none",
}


def _seal(model: ProductModel, field: str) -> str:
    return _sha256(model.model_dump(mode="json", exclude={field}))


def _verify_seal(model: ProductModel, field: str, message: str) -> None:
    stored = getattr(model, field)
    if not hmac.compare_digest(stored, _seal(model, field)):
        raise ValueError(message)


def _sealed_model(
    model_class: type[ProductModel],
    field: str,
    stable: dict[str, object],
) -> ProductModel:
    """Seal the normalized Pydantic representation, including datetimes."""

    draft = model_class(**stable, **{field: "0" * 64})
    return draft.model_copy(update={field: _seal(draft, field)})


def build_experience_candidate(
    *,
    candidate_type: ExperienceCandidateType,
    source_case_ids: list[str],
    proposal: ApprovedMemoryContent,
    affected_scope: MemoryScope,
    required_replay_suite: str,
) -> ExperienceCandidate:
    identity = _sha256(
        {
            "candidate_type": candidate_type,
            "source_case_ids": source_case_ids,
            "proposal": proposal,
            "affected_scope": affected_scope,
            "required_replay_suite": required_replay_suite,
        }
    )
    stable = {
        "schema_version": "visiondata-gate.experience-candidate.v1",
        "candidate_id": f"experience_{identity[:20]}",
        "candidate_type": candidate_type,
        "source_case_ids": source_case_ids,
        "proposal": proposal,
        "affected_scope": affected_scope,
        "required_replay_suite": required_replay_suite,
        "safety_policy_mutation": False,
        "evidence_schema_mutation": False,
        "equipment_control_enabled": False,
        "production_release_enabled": False,
    }
    return _sealed_model(ExperienceCandidate, "candidate_sha256", stable)  # type: ignore[return-value]


def _event(
    *,
    sequence: int,
    from_state: ExperienceState | None,
    to_state: ExperienceState,
    actor: str,
    occurred_at: datetime,
    reason: str,
    evidence_sha256: list[str],
    previous_event_sha256: str | None,
) -> ExperienceStateEvent:
    if (from_state, to_state) not in _ALLOWED_TRANSITIONS:
        raise ValueError(
            f"experience transition is not allowed: {from_state}->{to_state}"
        )
    stable = {
        "schema_version": "visiondata-gate.experience-state-event.v1",
        "sequence": sequence,
        "from_state": from_state,
        "to_state": to_state,
        "actor": actor,
        "occurred_at": _aware(occurred_at),
        "reason": reason,
        "evidence_sha256": evidence_sha256,
        "previous_event_sha256": previous_event_sha256,
    }
    identity = _sha256(stable)
    stable_with_id = {
        **stable,
        "event_id": f"experience_event_{identity[:20]}",
    }
    return _sealed_model(  # type: ignore[return-value]
        ExperienceStateEvent,
        "event_sha256",
        stable_with_id,
    )


def _record(
    candidate: ExperienceCandidate,
    state: ExperienceState,
    events: list[ExperienceStateEvent],
    *,
    replay_receipt: ExperienceReplayReceipt | None = None,
    approval_receipt: ExperienceApprovalReceipt | None = None,
    shadow_receipt: ExperienceShadowReceipt | None = None,
    promoted_memory: ApprovedMemoryCard | None = None,
    revoked_memory: ApprovedMemoryCard | None = None,
) -> ApprovedExperienceRecord:
    stable = {
        "schema_version": "visiondata-gate.approved-experience-record.v1",
        "candidate": candidate,
        "state": state,
        "replay_receipt": replay_receipt,
        "approval_receipt": approval_receipt,
        "shadow_receipt": shadow_receipt,
        "promoted_memory": promoted_memory,
        "revoked_memory": revoked_memory,
        "events": events,
        "online_model_update_performed": False,
        "frozen_policy_mutated": False,
        "claim_boundary": ApprovedExperienceRecord.model_fields[
            "claim_boundary"
        ].default,
    }
    record = _sealed_model(  # type: ignore[assignment]
        ApprovedExperienceRecord,
        "record_sha256",
        stable,
    )
    verify_approved_experience_record(record)
    return record


def initialize_experience(
    candidate: ExperienceCandidate,
    *,
    created_at: datetime,
    actor: str = "ExperienceCandidateGenerator",
) -> ApprovedExperienceRecord:
    _verify_seal(candidate, "candidate_sha256", "experience candidate SHA failed")
    event = _event(
        sequence=1,
        from_state=None,
        to_state=ExperienceState.CANDIDATE,
        actor=actor,
        occurred_at=created_at,
        reason="Experience candidate created; no runtime authority granted.",
        evidence_sha256=[candidate.candidate_sha256],
        previous_event_sha256=None,
    )
    return _record(candidate, ExperienceState.CANDIDATE, [event])


def record_experience_replay(
    record: ApprovedExperienceRecord,
    *,
    replay_suite_sha256: str,
    case_count: int,
    passed_case_count: int,
    deterministic_replay_rate: float,
    unsafe_closure_count: int,
    false_root_cause_count: int,
    premature_production_recovery_count: int,
    cross_site_memory_leakage_count: int,
    historical_memory_used_as_fact_count: int,
    evaluated_at: datetime,
) -> ApprovedExperienceRecord:
    verify_approved_experience_record(record)
    if record.state is not ExperienceState.CANDIDATE:
        raise ValueError("only CANDIDATE experience may enter replay evaluation")
    passed = (
        passed_case_count == case_count
        and deterministic_replay_rate == 1.0
        and unsafe_closure_count == 0
        and false_root_cause_count == 0
        and premature_production_recovery_count == 0
        and cross_site_memory_leakage_count == 0
        and historical_memory_used_as_fact_count == 0
    )
    stable = {
        "schema_version": "visiondata-gate.experience-replay.v1",
        "candidate_id": record.candidate.candidate_id,
        "candidate_sha256": record.candidate.candidate_sha256,
        "replay_suite_id": record.candidate.required_replay_suite,
        "replay_suite_sha256": replay_suite_sha256,
        "evaluated_at": _aware(evaluated_at),
        "case_count": case_count,
        "passed_case_count": passed_case_count,
        "deterministic_replay_rate": deterministic_replay_rate,
        "unsafe_closure_count": unsafe_closure_count,
        "false_root_cause_count": false_root_cause_count,
        "premature_production_recovery_count": (premature_production_recovery_count),
        "cross_site_memory_leakage_count": cross_site_memory_leakage_count,
        "historical_memory_used_as_fact_count": historical_memory_used_as_fact_count,
        "outcome": "PASS" if passed else "FAIL",
    }
    replay = _sealed_model(  # type: ignore[assignment]
        ExperienceReplayReceipt,
        "receipt_sha256",
        stable,
    )
    target = ExperienceState.REPLAY_TESTED if passed else ExperienceState.REJECTED
    event = _event(
        sequence=len(record.events) + 1,
        from_state=record.state,
        to_state=target,
        actor="FrozenReplayEvaluator",
        occurred_at=evaluated_at,
        reason=(
            "Frozen replay and all safety gates passed."
            if passed
            else "Frozen replay or a mandatory safety gate failed."
        ),
        evidence_sha256=[replay.receipt_sha256],
        previous_event_sha256=record.events[-1].event_sha256,
    )
    return _record(
        record.candidate,
        target,
        [*record.events, event],
        replay_receipt=replay,
    )


def decide_experience_approval(
    record: ApprovedExperienceRecord,
    *,
    approve: bool,
    actor_user_id: str,
    actor_role: str,
    note: str,
    approval_evidence_sha256: str,
    decided_at: datetime,
) -> ApprovedExperienceRecord:
    verify_approved_experience_record(record)
    if (
        record.state is not ExperienceState.REPLAY_TESTED
        or record.replay_receipt is None
    ):
        raise ValueError("experience approval requires a passed replay receipt")
    stable = {
        "schema_version": "visiondata-gate.experience-approval.v1",
        "candidate_id": record.candidate.candidate_id,
        "candidate_sha256": record.candidate.candidate_sha256,
        "replay_receipt_sha256": record.replay_receipt.receipt_sha256,
        "actor_user_id": actor_user_id,
        "actor_role": actor_role,
        "decided_at": _aware(decided_at),
        "decision": "APPROVE" if approve else "REJECT",
        "note": note,
        "approval_evidence_sha256": approval_evidence_sha256,
        "production_release_authorized": False,
        "equipment_control_authorized": False,
    }
    approval = _sealed_model(  # type: ignore[assignment]
        ExperienceApprovalReceipt,
        "receipt_sha256",
        stable,
    )
    target = ExperienceState.HUMAN_APPROVED if approve else ExperienceState.REJECTED
    event = _event(
        sequence=len(record.events) + 1,
        from_state=record.state,
        to_state=target,
        actor=actor_user_id,
        occurred_at=decided_at,
        reason=note,
        evidence_sha256=[approval.receipt_sha256],
        previous_event_sha256=record.events[-1].event_sha256,
    )
    return _record(
        record.candidate,
        target,
        [*record.events, event],
        replay_receipt=record.replay_receipt,
        approval_receipt=approval,
    )


def record_experience_shadow(
    record: ApprovedExperienceRecord,
    *,
    observed_case_count: int,
    changed_worker_order_count: int,
    unsafe_closure_count: int,
    cross_site_memory_leakage_count: int,
    historical_memory_used_as_fact_count: int,
    observed_at: datetime,
) -> ApprovedExperienceRecord:
    verify_approved_experience_record(record)
    if (
        record.state is not ExperienceState.HUMAN_APPROVED
        or record.approval_receipt is None
    ):
        raise ValueError("shadow evaluation requires HUMAN_APPROVED experience")
    passed = (
        unsafe_closure_count == 0
        and cross_site_memory_leakage_count == 0
        and historical_memory_used_as_fact_count == 0
    )
    stable = {
        "schema_version": "visiondata-gate.experience-shadow.v1",
        "candidate_id": record.candidate.candidate_id,
        "candidate_sha256": record.candidate.candidate_sha256,
        "approval_receipt_sha256": record.approval_receipt.receipt_sha256,
        "observed_at": _aware(observed_at),
        "observed_case_count": observed_case_count,
        "changed_worker_order_count": changed_worker_order_count,
        "unsafe_closure_count": unsafe_closure_count,
        "cross_site_memory_leakage_count": cross_site_memory_leakage_count,
        "historical_memory_used_as_fact_count": historical_memory_used_as_fact_count,
        "outcome": "PASS" if passed else "FAIL",
    }
    shadow = _sealed_model(  # type: ignore[assignment]
        ExperienceShadowReceipt,
        "receipt_sha256",
        stable,
    )
    target = ExperienceState.SHADOW if passed else ExperienceState.REJECTED
    event = _event(
        sequence=len(record.events) + 1,
        from_state=record.state,
        to_state=target,
        actor="ShadowSafetyEvaluator",
        occurred_at=observed_at,
        reason=(
            "Shadow observation passed without safety or memory-boundary regression."
            if passed
            else "Shadow observation violated a mandatory safety or memory boundary."
        ),
        evidence_sha256=[shadow.receipt_sha256],
        previous_event_sha256=record.events[-1].event_sha256,
    )
    return _record(
        record.candidate,
        target,
        [*record.events, event],
        replay_receipt=record.replay_receipt,
        approval_receipt=record.approval_receipt,
        shadow_receipt=shadow,
    )


def promote_experience(
    record: ApprovedExperienceRecord,
    *,
    promoted_at: datetime,
    actor: str,
) -> ApprovedExperienceRecord:
    verify_approved_experience_record(record)
    if (
        record.state is not ExperienceState.SHADOW
        or record.shadow_receipt is None
        or record.shadow_receipt.outcome != "PASS"
        or record.approval_receipt is None
    ):
        raise ValueError("promotion requires a passed SHADOW record and human approval")
    memory = build_approved_memory_card(
        memory_type=record.candidate.candidate_type.value,
        scope=record.candidate.affected_scope,
        content=record.candidate.proposal,
        source_case_ids=record.candidate.source_case_ids,
        approval_sha256=record.approval_receipt.receipt_sha256,
        valid_from=_aware(promoted_at),
        status="APPROVED",
    )
    event = _event(
        sequence=len(record.events) + 1,
        from_state=record.state,
        to_state=ExperienceState.PROMOTED,
        actor=actor,
        occurred_at=promoted_at,
        reason="Approved experience promoted as historical-reference-only memory.",
        evidence_sha256=[memory.memory_sha256, record.shadow_receipt.receipt_sha256],
        previous_event_sha256=record.events[-1].event_sha256,
    )
    return _record(
        record.candidate,
        ExperienceState.PROMOTED,
        [*record.events, event],
        replay_receipt=record.replay_receipt,
        approval_receipt=record.approval_receipt,
        shadow_receipt=record.shadow_receipt,
        promoted_memory=memory,
    )


def rollback_experience(
    record: ApprovedExperienceRecord,
    *,
    rolled_back_at: datetime,
    actor: str,
    reason: str,
) -> ApprovedExperienceRecord:
    verify_approved_experience_record(record)
    if record.state not in {ExperienceState.SHADOW, ExperienceState.PROMOTED}:
        raise ValueError("only SHADOW or PROMOTED experience may be rolled back")
    revoked: ApprovedMemoryCard | None = None
    if record.promoted_memory is not None:
        promoted = record.promoted_memory
        revoked = build_approved_memory_card(
            memory_type=promoted.memory_type,
            scope=promoted.scope,
            content=promoted.content,
            source_case_ids=promoted.source_case_ids,
            approval_sha256=promoted.approval_sha256,
            valid_from=promoted.valid_from,
            valid_until=_aware(rolled_back_at),
            status="REVOKED",
            memory_version=promoted.memory_version,
        )
    evidence = [record.events[-1].event_sha256]
    if revoked is not None:
        evidence.append(revoked.memory_sha256)
    event = _event(
        sequence=len(record.events) + 1,
        from_state=record.state,
        to_state=ExperienceState.ROLLED_BACK,
        actor=actor,
        occurred_at=rolled_back_at,
        reason=reason,
        evidence_sha256=evidence,
        previous_event_sha256=record.events[-1].event_sha256,
    )
    return _record(
        record.candidate,
        ExperienceState.ROLLED_BACK,
        [*record.events, event],
        replay_receipt=record.replay_receipt,
        approval_receipt=record.approval_receipt,
        shadow_receipt=record.shadow_receipt,
        promoted_memory=record.promoted_memory,
        revoked_memory=revoked,
    )


def build_source_case_evidence_binding(
    *,
    workspace_id: str,
    project_id: str,
    task_id: str,
    case_id: str,
    case_sha256: str,
    case_audit_root_sha256: str,
    scope: MemoryScope,
    verification_status: Literal[
        "VERIFIED_LOCAL_CASE", "VERIFIED_ARCHIVED_CASE_RECEIPT"
    ],
    verified_at: datetime,
) -> SourceCaseEvidenceBinding:
    stable = {
        "schema_version": "visiondata-gate.source-case-evidence-binding.v1",
        "workspace_id": workspace_id,
        "project_id": project_id,
        "task_id": task_id,
        "case_id": case_id,
        "case_sha256": case_sha256,
        "case_audit_root_sha256": case_audit_root_sha256,
        "scope": scope,
        "verification_status": verification_status,
        "verified_at": _aware(verified_at),
    }
    binding = _sealed_model(  # type: ignore[assignment]
        SourceCaseEvidenceBinding,
        "binding_sha256",
        stable,
    )
    verify_source_case_evidence_binding(binding)
    return binding


def verify_source_case_evidence_binding(binding: SourceCaseEvidenceBinding) -> None:
    _verify_seal(
        binding,
        "binding_sha256",
        "source case evidence binding failed SHA-256 validation",
    )


def _binding_matches_memory_scope(
    binding: SourceCaseEvidenceBinding,
    scope: MemoryScope,
) -> bool:
    if binding.scope.site_id != scope.site_id:
        return False
    for field in ("product_family", "line_id", "station_id", "camera_id"):
        required = getattr(scope, field)
        if required is not None and getattr(binding.scope, field) != required:
            return False
    return True


def build_memory_admission_envelope(
    record: ApprovedExperienceRecord,
    *,
    workspace_id: str,
    project_id: str,
    source_case_bindings: list[SourceCaseEvidenceBinding],
    admitted_at: datetime,
    admitted_by_actor_user_id: str,
    admitted_by_actor_role: str,
) -> MemoryAdmissionEnvelope:
    verify_approved_experience_record(record)
    if record.state is not ExperienceState.PROMOTED or record.promoted_memory is None:
        raise ValueError("strict memory admission requires a PROMOTED experience")
    if (
        record.replay_receipt is None
        or record.replay_receipt.outcome != "PASS"
        or record.approval_receipt is None
        or record.approval_receipt.decision != "APPROVE"
        or record.shadow_receipt is None
        or record.shadow_receipt.outcome != "PASS"
    ):
        raise ValueError(
            "strict memory admission requires replay, approval, and shadow PASS"
        )
    expected_ids = sorted(record.candidate.source_case_ids)
    observed_ids = sorted(binding.case_id for binding in source_case_bindings)
    if expected_ids != observed_ids or len(observed_ids) != len(set(observed_ids)):
        raise ValueError(
            "memory admission source cases do not match the promoted candidate"
        )
    for binding in source_case_bindings:
        verify_source_case_evidence_binding(binding)
        if binding.workspace_id != workspace_id or binding.project_id != project_id:
            raise ValueError("memory admission source case escaped tenant scope")
        if not _binding_matches_memory_scope(binding, record.promoted_memory.scope):
            raise ValueError("memory admission source case escaped memory scope")
    policy_sha256 = _sha256(_STRICT_ADMISSION_POLICY)
    admitted = _aware(admitted_at)
    receipt_payload = {
        "admission_policy_sha256": policy_sha256,
        "experience_record_sha256": record.record_sha256,
        "promoted_memory_sha256": record.promoted_memory.memory_sha256,
        "source_case_binding_sha256": [
            item.binding_sha256 for item in source_case_bindings
        ],
        "workspace_id": workspace_id,
        "project_id": project_id,
        "admitted_at": admitted,
        "admitted_by_actor_user_id": admitted_by_actor_user_id,
        "admitted_by_actor_role": admitted_by_actor_role,
    }
    stable = {
        "schema_version": "visiondata-gate.memory-admission-envelope.v1",
        "workspace_id": workspace_id,
        "project_id": project_id,
        "card": record.promoted_memory,
        "experience_record": record,
        "source_case_bindings": source_case_bindings,
        "admission_policy_id": "VISIONDATA_STRICT_PROMOTION_CHAIN_V1",
        "admission_policy_sha256": policy_sha256,
        "admitted_at": admitted,
        "admitted_by_actor_user_id": admitted_by_actor_user_id,
        "admitted_by_actor_role": admitted_by_actor_role,
        "admission_receipt_sha256": _sha256(receipt_payload),
        "historical_reference_only": True,
        "current_case_fact_authority": "none",
        "production_authority": "none",
    }
    envelope = _sealed_model(  # type: ignore[assignment]
        MemoryAdmissionEnvelope,
        "envelope_sha256",
        stable,
    )
    verify_memory_admission_envelope(envelope)
    return envelope


def verify_memory_admission_envelope(envelope: MemoryAdmissionEnvelope) -> None:
    verify_approved_experience_record(envelope.experience_record)
    payload = envelope.model_dump(mode="json")
    stored = payload.pop("envelope_sha256")
    if not hmac.compare_digest(stored, _sha256(payload)):
        raise ValueError("memory admission envelope failed SHA-256 validation")
    if not hmac.compare_digest(
        envelope.admission_policy_sha256,
        _sha256(_STRICT_ADMISSION_POLICY),
    ):
        raise ValueError("memory admission policy digest is not trusted")
    record = envelope.experience_record
    if record.state is not ExperienceState.PROMOTED or record.promoted_memory is None:
        raise ValueError(
            "memory admission envelope is not backed by PROMOTED experience"
        )
    if envelope.card != record.promoted_memory:
        raise ValueError("memory admission card differs from promoted experience")
    if (
        record.replay_receipt is None
        or record.replay_receipt.outcome != "PASS"
        or record.approval_receipt is None
        or record.approval_receipt.decision != "APPROVE"
        or record.shadow_receipt is None
        or record.shadow_receipt.outcome != "PASS"
    ):
        raise ValueError("memory admission envelope lost its approved lifecycle chain")
    expected_ids = sorted(record.candidate.source_case_ids)
    observed_ids = sorted(binding.case_id for binding in envelope.source_case_bindings)
    if expected_ids != observed_ids or len(observed_ids) != len(set(observed_ids)):
        raise ValueError("memory admission envelope lost source case binding")
    for binding in envelope.source_case_bindings:
        verify_source_case_evidence_binding(binding)
        if (
            binding.workspace_id != envelope.workspace_id
            or binding.project_id != envelope.project_id
        ):
            raise ValueError(
                "memory admission envelope contains cross-tenant source case"
            )
        if not _binding_matches_memory_scope(binding, envelope.card.scope):
            raise ValueError(
                "memory admission envelope contains cross-scope source case"
            )
    receipt_payload = {
        "admission_policy_sha256": envelope.admission_policy_sha256,
        "experience_record_sha256": record.record_sha256,
        "promoted_memory_sha256": envelope.card.memory_sha256,
        "source_case_binding_sha256": [
            item.binding_sha256 for item in envelope.source_case_bindings
        ],
        "workspace_id": envelope.workspace_id,
        "project_id": envelope.project_id,
        "admitted_at": envelope.admitted_at,
        "admitted_by_actor_user_id": envelope.admitted_by_actor_user_id,
        "admitted_by_actor_role": envelope.admitted_by_actor_role,
    }
    if not hmac.compare_digest(
        envelope.admission_receipt_sha256,
        _sha256(receipt_payload),
    ):
        raise ValueError("memory admission receipt failed SHA-256 validation")


def memory_admission_envelope_jsonl(envelope: MemoryAdmissionEnvelope) -> str:
    verify_memory_admission_envelope(envelope)
    return (
        json.dumps(
            envelope.model_dump(mode="json"),
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        )
        + "\n"
    )


def load_memory_admission_store(
    path: str | Path,
    *,
    expected_workspace_id: str,
    expected_project_id: str,
    source_case_registry: Mapping[str, SourceCaseEvidenceBinding],
) -> tuple[list[ApprovedMemoryCard], MemoryAdmissionStoreReceipt]:
    source = Path(path).expanduser().resolve(strict=True)
    raw = source.read_bytes()
    envelopes: list[MemoryAdmissionEnvelope] = []
    for line_number, raw_line in enumerate(raw.decode("utf-8").splitlines(), start=1):
        if not raw_line.strip():
            continue
        try:
            envelope = MemoryAdmissionEnvelope.model_validate_json(raw_line)
            verify_memory_admission_envelope(envelope)
        except ValueError as error:
            raise ValueError(
                f"memory admission store failed at line {line_number}"
            ) from error
        if (
            envelope.workspace_id != expected_workspace_id
            or envelope.project_id != expected_project_id
        ):
            raise ValueError(
                "memory admission store escaped workspace or project scope"
            )
        for binding in envelope.source_case_bindings:
            trusted = source_case_registry.get(binding.case_id)
            if trusted is None:
                raise ValueError("memory admission source case is absent from registry")
            verify_source_case_evidence_binding(trusted)
            if trusted != binding:
                raise ValueError("memory admission source case differs from registry")
        envelopes.append(envelope)
    envelope_ids = [item.envelope_sha256 for item in envelopes]
    memory_ids = [item.card.memory_id for item in envelopes]
    if len(envelope_ids) != len(set(envelope_ids)):
        raise ValueError("memory admission store contains duplicate envelopes")
    if len(memory_ids) != len(set(memory_ids)):
        raise ValueError("memory admission store contains duplicate memory IDs")
    stable = {
        "schema_version": "visiondata-gate.memory-admission-store-receipt.v1",
        "store_sha256": hashlib.sha256(raw).hexdigest(),
        "workspace_id": expected_workspace_id,
        "project_id": expected_project_id,
        "entry_count": len(envelopes),
        "envelope_sha256": envelope_ids,
        "memory_sha256": [item.card.memory_sha256 for item in envelopes],
        "source_case_binding_count": sum(
            len(item.source_case_bindings) for item in envelopes
        ),
        "admission_status": "STRICT_PROMOTION_CHAIN_VERIFIED",
    }
    receipt = _sealed_model(  # type: ignore[assignment]
        MemoryAdmissionStoreReceipt,
        "receipt_sha256",
        stable,
    )
    return [item.card for item in envelopes], receipt


def promoted_memory_jsonl(record: ApprovedExperienceRecord) -> str:
    verify_approved_experience_record(record)
    if record.state is not ExperienceState.PROMOTED or record.promoted_memory is None:
        raise ValueError("only PROMOTED experience has an active memory JSONL record")
    return (
        json.dumps(
            record.promoted_memory.model_dump(mode="json"),
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        )
        + "\n"
    )


def verify_approved_experience_record(record: ApprovedExperienceRecord) -> None:
    _verify_seal(
        record.candidate,
        "candidate_sha256",
        "experience candidate failed SHA-256 validation",
    )
    _verify_seal(
        record,
        "record_sha256",
        "approved experience record failed SHA-256 validation",
    )
    if record.events[-1].to_state is not record.state:
        raise ValueError("approved experience state differs from its terminal event")
    previous: str | None = None
    prior_state: ExperienceState | None = None
    for sequence, event in enumerate(record.events, start=1):
        _verify_seal(
            event,
            "event_sha256",
            "experience state event failed SHA-256 validation",
        )
        if event.sequence != sequence or event.previous_event_sha256 != previous:
            raise ValueError("experience event chain is incomplete or reordered")
        if (
            event.from_state is not prior_state
            or (
                event.from_state,
                event.to_state,
            )
            not in _ALLOWED_TRANSITIONS
        ):
            raise ValueError("experience event contains an illegal state transition")
        previous = event.event_sha256
        prior_state = event.to_state
    if any(
        later.occurred_at < earlier.occurred_at
        for earlier, later in zip(record.events, record.events[1:], strict=False)
    ):
        raise ValueError("experience event timestamps are not monotonic")
    for receipt, field, message in (
        (
            record.replay_receipt,
            "receipt_sha256",
            "experience replay receipt failed SHA-256 validation",
        ),
        (
            record.approval_receipt,
            "receipt_sha256",
            "experience approval receipt failed SHA-256 validation",
        ),
        (
            record.shadow_receipt,
            "receipt_sha256",
            "experience shadow receipt failed SHA-256 validation",
        ),
    ):
        if receipt is not None:
            _verify_seal(receipt, field, message)
    if record.replay_receipt is not None and (
        record.replay_receipt.candidate_sha256 != record.candidate.candidate_sha256
    ):
        raise ValueError("experience replay lost candidate binding")
    if record.replay_receipt is not None and (
        record.replay_receipt.candidate_id != record.candidate.candidate_id
        or record.replay_receipt.replay_suite_id
        != record.candidate.required_replay_suite
    ):
        raise ValueError("experience replay lost candidate identity or suite binding")
    if record.approval_receipt is not None and (
        record.replay_receipt is None
        or record.approval_receipt.replay_receipt_sha256
        != record.replay_receipt.receipt_sha256
    ):
        raise ValueError("experience approval lost replay binding")
    if record.approval_receipt is not None and (
        record.approval_receipt.candidate_id != record.candidate.candidate_id
        or record.approval_receipt.candidate_sha256 != record.candidate.candidate_sha256
    ):
        raise ValueError("experience approval lost candidate binding")
    if record.shadow_receipt is not None and (
        record.approval_receipt is None
        or record.shadow_receipt.approval_receipt_sha256
        != record.approval_receipt.receipt_sha256
    ):
        raise ValueError("experience shadow lost approval binding")
    if record.shadow_receipt is not None and (
        record.shadow_receipt.candidate_id != record.candidate.candidate_id
        or record.shadow_receipt.candidate_sha256 != record.candidate.candidate_sha256
    ):
        raise ValueError("experience shadow lost candidate binding")
    if record.state is ExperienceState.REPLAY_TESTED and (
        record.replay_receipt is None or record.replay_receipt.outcome != "PASS"
    ):
        raise ValueError("REPLAY_TESTED experience requires a passed replay receipt")
    if record.state is ExperienceState.HUMAN_APPROVED and (
        record.replay_receipt is None
        or record.replay_receipt.outcome != "PASS"
        or record.approval_receipt is None
        or record.approval_receipt.decision != "APPROVE"
    ):
        raise ValueError("HUMAN_APPROVED experience requires replay and approval PASS")
    if record.state in {ExperienceState.SHADOW, ExperienceState.PROMOTED} and (
        record.replay_receipt is None
        or record.replay_receipt.outcome != "PASS"
        or record.approval_receipt is None
        or record.approval_receipt.decision != "APPROVE"
        or record.shadow_receipt is None
        or record.shadow_receipt.outcome != "PASS"
    ):
        raise ValueError(
            "SHADOW/PROMOTED experience requires the complete passed chain"
        )
    if (
        record.replay_receipt is not None
        and record.approval_receipt is not None
        and record.approval_receipt.decided_at < record.replay_receipt.evaluated_at
    ):
        raise ValueError("experience approval predates replay")
    if (
        record.approval_receipt is not None
        and record.shadow_receipt is not None
        and record.shadow_receipt.observed_at < record.approval_receipt.decided_at
    ):
        raise ValueError("experience shadow predates approval")
    if record.promoted_memory is not None:
        verify_approved_memory_card(record.promoted_memory)
        if record.promoted_memory.may_set_current_case_fact:
            raise ValueError("promoted history escaped into current-case facts")
        if record.approval_receipt is None or (
            record.promoted_memory.approval_sha256
            != record.approval_receipt.receipt_sha256
        ):
            raise ValueError("promoted memory lost named human approval binding")
        if (
            record.promoted_memory.memory_type != record.candidate.candidate_type.value
            or record.promoted_memory.scope != record.candidate.affected_scope
            or record.promoted_memory.content != record.candidate.proposal
            or record.promoted_memory.source_case_ids
            != record.candidate.source_case_ids
        ):
            raise ValueError("promoted memory differs from the replayed candidate")
    if record.revoked_memory is not None:
        verify_approved_memory_card(record.revoked_memory)
        if record.revoked_memory.status != "REVOKED":
            raise ValueError("rolled-back memory must be explicitly revoked")
        if record.promoted_memory is None or (
            record.revoked_memory.memory_id != record.promoted_memory.memory_id
        ):
            raise ValueError("revoked memory lost the promoted memory identity")
    if record.state is ExperienceState.PROMOTED and record.promoted_memory is None:
        raise ValueError("PROMOTED experience lacks an approved memory artifact")
    if record.state is ExperienceState.PROMOTED:
        promotion = record.events[-1]
        assert record.promoted_memory is not None
        assert record.shadow_receipt is not None
        if set(promotion.evidence_sha256) != {
            record.promoted_memory.memory_sha256,
            record.shadow_receipt.receipt_sha256,
        }:
            raise ValueError("promotion event lost memory or shadow evidence binding")
    promoted_in_history = any(
        event.to_state is ExperienceState.PROMOTED for event in record.events
    )
    if record.state is ExperienceState.ROLLED_BACK and promoted_in_history:
        if record.revoked_memory is None or record.promoted_memory is None:
            raise ValueError(
                "rolled-back promoted experience lacks revocation artifact"
            )
        promoted = record.promoted_memory
        revoked = record.revoked_memory
        if (
            revoked.memory_id != promoted.memory_id
            or revoked.memory_type != promoted.memory_type
            or revoked.memory_version != promoted.memory_version
            or revoked.scope != promoted.scope
            or revoked.content != promoted.content
            or revoked.source_case_ids != promoted.source_case_ids
            or revoked.approval_sha256 != promoted.approval_sha256
            or revoked.valid_from != promoted.valid_from
            or revoked.valid_until != record.events[-1].occurred_at
            or revoked.historical_reference_only is not True
            or revoked.may_set_current_case_fact is not False
            or revoked.policy_judge_input is not False
            or revoked.machine_action_permitted is not False
        ):
            raise ValueError("revoked memory differs from promoted memory lineage")
        if revoked.memory_sha256 not in record.events[-1].evidence_sha256:
            raise ValueError("rollback event lost revoked memory evidence binding")


__all__ = [
    "ApprovedExperienceRecord",
    "ExperienceApprovalReceipt",
    "ExperienceCandidate",
    "ExperienceCandidateType",
    "ExperienceReplayReceipt",
    "ExperienceShadowReceipt",
    "ExperienceState",
    "MemoryAdmissionEnvelope",
    "MemoryAdmissionStoreReceipt",
    "SourceCaseEvidenceBinding",
    "build_experience_candidate",
    "build_memory_admission_envelope",
    "build_source_case_evidence_binding",
    "decide_experience_approval",
    "initialize_experience",
    "load_memory_admission_store",
    "memory_admission_envelope_jsonl",
    "promote_experience",
    "promoted_memory_jsonl",
    "record_experience_replay",
    "record_experience_shadow",
    "rollback_experience",
    "verify_approved_experience_record",
    "verify_memory_admission_envelope",
    "verify_source_case_evidence_binding",
]
