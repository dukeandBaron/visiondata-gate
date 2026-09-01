"""Deterministic evidence-acquisition Worker prioritization.

The selector uses an explicit lexicographic contract after an eligibility
guard.  It does not claim calibrated information gain, learned utility, or
probabilistic active sensing.  Every selection is sealed in a replayable
receipt containing the complete normalized candidate set.
"""

from __future__ import annotations

import hashlib
import hmac
from enum import Enum
from typing import Literal

import rfc8785
from pydantic import ConfigDict, Field, field_validator, model_validator

from .product_models import ProductModel


class BlockingSeverity(str, Enum):
    NONE = "NONE"
    WARNING = "WARNING"
    BLOCKING = "BLOCKING"


class MeasuredCostBucket(str, Enum):
    LOW = "LOW"
    MEDIUM = "MEDIUM"
    HIGH = "HIGH"
    UNKNOWN = "UNKNOWN"


SEVERITY_RANK = {
    BlockingSeverity.NONE: 0,
    BlockingSeverity.WARNING: 1,
    BlockingSeverity.BLOCKING: 2,
}

COST_RANK = {
    MeasuredCostBucket.LOW: 0,
    MeasuredCostBucket.MEDIUM: 1,
    MeasuredCostBucket.HIGH: 2,
    MeasuredCostBucket.UNKNOWN: 3,
}

WORKER_ID_PATTERN = r"^[A-Za-z0-9][A-Za-z0-9_.:-]{0,119}$"
BEHAVIOR_FRAME_MAGIC = b"visiondata-gate.agent-behavior-receipt.v1\x00"


class WorkerCandidate(ProductModel):
    """Measured inputs accepted by the deterministic selector."""

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True, frozen=True)

    worker_id: str = Field(pattern=WORKER_ID_PATTERN)
    eligible: bool
    ineligibility_reasons: list[str] = Field(default_factory=list)
    blocking_severity: BlockingSeverity
    discriminated_hypothesis_ids: list[str] = Field(default_factory=list)
    unresolved_evidence_refs: list[str] = Field(default_factory=list)
    measured_cost_bucket: MeasuredCostBucket

    @field_validator(
        "ineligibility_reasons",
        "discriminated_hypothesis_ids",
        "unresolved_evidence_refs",
    )
    @classmethod
    def normalize_string_sets(cls, value: list[str]) -> list[str]:
        return sorted({item.strip() for item in value if item.strip()})

    @model_validator(mode="after")
    def validate_eligibility_reason(self) -> WorkerCandidate:
        if self.eligible and self.ineligibility_reasons:
            raise ValueError("eligible Worker cannot have ineligibility reasons")
        if not self.eligible and not self.ineligibility_reasons:
            raise ValueError("ineligible Worker requires at least one reason")
        return self


class WorkerRankingEntry(ProductModel):
    worker_id: str
    eligible: bool
    selected: bool
    rank: int | None = Field(default=None, ge=1)
    blocking_severity_rank: int = Field(ge=0, le=2)
    hypothesis_discrimination_count: int = Field(ge=0)
    unresolved_evidence_count: int = Field(ge=0)
    measured_cost_rank: int = Field(ge=0, le=3)
    exclusion_reasons: list[str] = Field(default_factory=list)


class WorkerSelectionReceipt(ProductModel):
    """Self-contained receipt for one bounded selection decision."""

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True, frozen=True)

    schema_version: Literal["visiondata-gate.worker-selection-receipt.v1"] = (
        "visiondata-gate.worker-selection-receipt.v1"
    )
    policy_id: Literal["deterministic-evidence-acquisition-priority.v1"] = (
        "deterministic-evidence-acquisition-priority.v1"
    )
    ordering_contract: Literal[
        "eligible > blocking_severity > hypothesis_discrimination_count > "
        "unresolved_evidence_count > measured_cost_bucket > stable_worker_id"
    ] = (
        "eligible > blocking_severity > hypothesis_discrimination_count > "
        "unresolved_evidence_count > measured_cost_bucket > stable_worker_id"
    )
    worker_budget: int = Field(ge=0, strict=True)
    candidates: list[WorkerCandidate]
    input_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    ranking: list[WorkerRankingEntry]
    selected_worker_ids: list[str]
    receipt_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")


class AgentBehaviorDecisionV1(ProductModel):
    """Interface-facing explanation for one selected or rejected Worker."""

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True, frozen=True)

    worker_id: str = Field(pattern=WORKER_ID_PATTERN)
    disposition: Literal["SELECTED", "REJECTED"]
    eligible: bool
    rank: int | None = Field(default=None, ge=1)
    reason_codes: list[str] = Field(min_length=1)
    evidence_refs: list[str] = Field(default_factory=list)
    discriminated_hypothesis_ids: list[str] = Field(default_factory=list)


class AgentBehaviorReceiptV1(ProductModel):
    """Read-only behavior projection over a frozen Worker selection receipt.

    This artifact describes why Workers were selected or rejected.  It does not
    claim that a selected Worker executed successfully or changed the final
    policy decision.
    """

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True, frozen=True)

    schema_version: Literal["visiondata-gate.agent-behavior-receipt.v1"] = (
        "visiondata-gate.agent-behavior-receipt.v1"
    )
    digest_contract: Literal["RFC8785_JCS_SHA256_LENGTH_PREFIX_DOMAIN_V1"] = (
        "RFC8785_JCS_SHA256_LENGTH_PREFIX_DOMAIN_V1"
    )
    behavior_scope: Literal["WORKER_SELECTION_DECISION_ONLY"] = (
        "WORKER_SELECTION_DECISION_ONLY"
    )
    selection_policy_id: str = Field(min_length=1, max_length=160)
    source_selection_receipt_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    worker_budget: int = Field(ge=0, strict=True)
    used_worker_budget: int = Field(ge=0, strict=True)
    unused_worker_budget: int = Field(ge=0, strict=True)
    eligible_worker_count: int = Field(ge=0, strict=True)
    selected_worker_ids: list[str]
    rejected_worker_ids: list[str]
    selected: list[AgentBehaviorDecisionV1]
    rejected: list[AgentBehaviorDecisionV1]
    evidence_ref_count: int = Field(ge=0, strict=True)
    execution_outcomes_included: Literal[False] = False
    model_decision_authority: Literal[False] = False
    production_release_allowed: Literal[False] = False
    claim_boundary: str = (
        "This receipt explains the deterministic Worker selection decision only. "
        "Selected does not mean executed, successful, root-cause proven, or authorized "
        "for production release."
    )
    receipt_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")

    @model_validator(mode="after")
    def validate_behavior_counts(self) -> AgentBehaviorReceiptV1:
        if self.used_worker_budget != len(self.selected):
            raise ValueError("used Worker budget does not match selected decisions")
        if self.used_worker_budget > self.worker_budget:
            raise ValueError("used Worker budget exceeds the frozen budget")
        if self.unused_worker_budget != self.worker_budget - self.used_worker_budget:
            raise ValueError("unused Worker budget does not reconcile")
        if self.eligible_worker_count < len(self.selected):
            raise ValueError("selected Workers exceed eligible Workers")
        if self.selected_worker_ids != [item.worker_id for item in self.selected]:
            raise ValueError("selected Worker IDs do not match behavior decisions")
        if self.rejected_worker_ids != [item.worker_id for item in self.rejected]:
            raise ValueError("rejected Worker IDs do not match behavior decisions")
        all_decisions = [*self.selected, *self.rejected]
        all_worker_ids = [item.worker_id for item in all_decisions]
        if len(all_worker_ids) != len(set(all_worker_ids)):
            raise ValueError("Agent behavior receipt contains duplicate Worker IDs")
        if any(not item.eligible for item in self.selected):
            raise ValueError("selected behavior decisions must remain eligible")
        if self.eligible_worker_count != sum(item.eligible for item in all_decisions):
            raise ValueError("eligible Worker count does not reconcile")
        observed_evidence_refs = {
            evidence_ref
            for item in all_decisions
            for evidence_ref in item.evidence_refs
        }
        if self.evidence_ref_count != len(observed_evidence_refs):
            raise ValueError("evidence reference count does not reconcile")
        if any(item.disposition != "SELECTED" for item in self.selected):
            raise ValueError("selected behavior list contains a rejected disposition")
        if any(item.disposition != "REJECTED" for item in self.rejected):
            raise ValueError("rejected behavior list contains a selected disposition")
        return self


def _canonical_jcs_bytes(value: object) -> bytes:
    try:
        return rfc8785.dumps(value)
    except (rfc8785.CanonicalizationError, TypeError, UnicodeError) as error:
        raise ValueError(
            f"worker selection payload cannot be canonicalized: {error}"
        ) from error


def _sha256(value: object) -> str:
    return hashlib.sha256(_canonical_jcs_bytes(value)).hexdigest()


def _domain_sha256(domain: str, value: object) -> str:
    domain_bytes = domain.encode("utf-8")
    payload = _canonical_jcs_bytes(value)
    frame = b"".join(
        (
            BEHAVIOR_FRAME_MAGIC,
            len(domain_bytes).to_bytes(2, "big"),
            domain_bytes,
            len(payload).to_bytes(8, "big"),
            payload,
        )
    )
    return hashlib.sha256(frame).hexdigest()


def _priority_key(candidate: WorkerCandidate) -> tuple[int, int, int, int, str]:
    return (
        -SEVERITY_RANK[candidate.blocking_severity],
        -len(candidate.discriminated_hypothesis_ids),
        -len(candidate.unresolved_evidence_refs),
        COST_RANK[candidate.measured_cost_bucket],
        candidate.worker_id,
    )


def build_worker_selection_receipt(
    candidates: list[WorkerCandidate],
    *,
    worker_budget: int,
) -> WorkerSelectionReceipt:
    """Apply the frozen eligibility and lexicographic ordering contract."""

    if type(worker_budget) is not int or worker_budget < 0:
        raise ValueError("worker_budget must be a non-negative integer")
    normalized = sorted(candidates, key=lambda item: item.worker_id)
    worker_ids = [item.worker_id for item in normalized]
    if len(worker_ids) != len(set(worker_ids)):
        raise ValueError("worker candidate IDs must be unique")

    eligible = sorted((item for item in normalized if item.eligible), key=_priority_key)
    selected = eligible[:worker_budget]
    selected_ids = [item.worker_id for item in selected]
    rank_by_worker = {
        item.worker_id: index for index, item in enumerate(eligible, start=1)
    }
    ranking: list[WorkerRankingEntry] = []
    for candidate in eligible:
        is_selected = candidate.worker_id in selected_ids
        ranking.append(
            WorkerRankingEntry(
                worker_id=candidate.worker_id,
                eligible=True,
                selected=is_selected,
                rank=rank_by_worker[candidate.worker_id],
                blocking_severity_rank=SEVERITY_RANK[candidate.blocking_severity],
                hypothesis_discrimination_count=len(
                    candidate.discriminated_hypothesis_ids
                ),
                unresolved_evidence_count=len(candidate.unresolved_evidence_refs),
                measured_cost_rank=COST_RANK[candidate.measured_cost_bucket],
                exclusion_reasons=[] if is_selected else ["WORKER_BUDGET_EXHAUSTED"],
            )
        )
    for candidate in normalized:
        if candidate.eligible:
            continue
        ranking.append(
            WorkerRankingEntry(
                worker_id=candidate.worker_id,
                eligible=False,
                selected=False,
                blocking_severity_rank=SEVERITY_RANK[candidate.blocking_severity],
                hypothesis_discrimination_count=len(
                    candidate.discriminated_hypothesis_ids
                ),
                unresolved_evidence_count=len(candidate.unresolved_evidence_refs),
                measured_cost_rank=COST_RANK[candidate.measured_cost_bucket],
                exclusion_reasons=candidate.ineligibility_reasons,
            )
        )

    input_payload = {
        "worker_budget": worker_budget,
        "candidates": [item.model_dump(mode="json") for item in normalized],
    }
    draft = WorkerSelectionReceipt(
        worker_budget=worker_budget,
        candidates=normalized,
        input_sha256=_sha256(input_payload),
        ranking=ranking,
        selected_worker_ids=selected_ids,
        receipt_sha256="0" * 64,
    )
    receipt_payload = draft.model_dump(mode="json", exclude={"receipt_sha256"})
    return draft.model_copy(update={"receipt_sha256": _sha256(receipt_payload)})


def verify_worker_selection_receipt(receipt: WorkerSelectionReceipt) -> None:
    """Replay the selection and compare all digest and decision fields."""

    expected = build_worker_selection_receipt(
        receipt.candidates, worker_budget=receipt.worker_budget
    )
    if not hmac.compare_digest(receipt.input_sha256, expected.input_sha256):
        raise ValueError("worker selection input digest mismatch")
    if receipt.ranking != expected.ranking:
        raise ValueError("worker selection ranking mismatch")
    if receipt.selected_worker_ids != expected.selected_worker_ids:
        raise ValueError("worker selection disposition mismatch")
    if not hmac.compare_digest(receipt.receipt_sha256, expected.receipt_sha256):
        raise ValueError("worker selection receipt digest mismatch")


def build_agent_behavior_receipt(
    selection: WorkerSelectionReceipt,
) -> AgentBehaviorReceiptV1:
    """Create an explicit selected/rejected/reason/budget/evidence projection."""

    verify_worker_selection_receipt(selection)
    candidates = {item.worker_id: item for item in selection.candidates}
    rankings = {item.worker_id: item for item in selection.ranking}

    selected: list[AgentBehaviorDecisionV1] = []
    for worker_id in selection.selected_worker_ids:
        candidate = candidates[worker_id]
        ranking = rankings[worker_id]
        selected.append(
            AgentBehaviorDecisionV1(
                worker_id=worker_id,
                disposition="SELECTED",
                eligible=True,
                rank=ranking.rank,
                reason_codes=[
                    "ELIGIBLE_BY_POLICY",
                    "SELECTED_WITHIN_WORKER_BUDGET",
                ],
                evidence_refs=candidate.unresolved_evidence_refs,
                discriminated_hypothesis_ids=(candidate.discriminated_hypothesis_ids),
            )
        )

    selected_ids = set(selection.selected_worker_ids)
    rejected: list[AgentBehaviorDecisionV1] = []
    for ranking in selection.ranking:
        if ranking.worker_id in selected_ids:
            continue
        candidate = candidates[ranking.worker_id]
        reason_codes = list(ranking.exclusion_reasons)
        if not reason_codes:
            reason_codes = ["NOT_SELECTED_BY_FROZEN_POLICY"]
        rejected.append(
            AgentBehaviorDecisionV1(
                worker_id=ranking.worker_id,
                disposition="REJECTED",
                eligible=ranking.eligible,
                rank=ranking.rank,
                reason_codes=reason_codes,
                evidence_refs=candidate.unresolved_evidence_refs,
                discriminated_hypothesis_ids=(candidate.discriminated_hypothesis_ids),
            )
        )

    evidence_refs = {
        ref for item in (*selected, *rejected) for ref in item.evidence_refs
    }
    stable = {
        "schema_version": "visiondata-gate.agent-behavior-receipt.v1",
        "digest_contract": "RFC8785_JCS_SHA256_LENGTH_PREFIX_DOMAIN_V1",
        "behavior_scope": "WORKER_SELECTION_DECISION_ONLY",
        "selection_policy_id": selection.policy_id,
        "source_selection_receipt_sha256": selection.receipt_sha256,
        "worker_budget": selection.worker_budget,
        "used_worker_budget": len(selected),
        "unused_worker_budget": selection.worker_budget - len(selected),
        "eligible_worker_count": sum(item.eligible for item in selection.candidates),
        "selected_worker_ids": [item.worker_id for item in selected],
        "rejected_worker_ids": [item.worker_id for item in rejected],
        "selected": [item.model_dump(mode="json") for item in selected],
        "rejected": [item.model_dump(mode="json") for item in rejected],
        "evidence_ref_count": len(evidence_refs),
        "execution_outcomes_included": False,
        "model_decision_authority": False,
        "production_release_allowed": False,
        "claim_boundary": AgentBehaviorReceiptV1.model_fields["claim_boundary"].default,
    }
    return AgentBehaviorReceiptV1(
        **stable,
        receipt_sha256=_domain_sha256("agent-behavior-receipt", stable),
    )


def verify_agent_behavior_receipt(
    receipt: AgentBehaviorReceiptV1,
    *,
    selection: WorkerSelectionReceipt,
) -> None:
    """Replay the projection and reject any behavior or digest drift."""

    expected = build_agent_behavior_receipt(selection)
    if receipt != expected:
        raise ValueError("Agent behavior receipt failed deterministic replay")
    if not hmac.compare_digest(receipt.receipt_sha256, expected.receipt_sha256):
        raise ValueError("Agent behavior receipt digest mismatch")


__all__ = [
    "AgentBehaviorDecisionV1",
    "AgentBehaviorReceiptV1",
    "BlockingSeverity",
    "MeasuredCostBucket",
    "WorkerCandidate",
    "WorkerRankingEntry",
    "WorkerSelectionReceipt",
    "build_agent_behavior_receipt",
    "build_worker_selection_receipt",
    "verify_agent_behavior_receipt",
    "verify_worker_selection_receipt",
]
