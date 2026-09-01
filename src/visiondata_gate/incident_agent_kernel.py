"""Governed Agent-kernel receipts for industrial incident case v6.

The contracts in this module make four previously implicit runtime boundaries
replayable without claiming probabilistic belief inference, causal root-cause
proof, or formal model checking:

* parent belief freshness revision against the current source epoch;
* selected-Worker dependency barriers and deterministic execution order;
* evidence-only Council cross-examination before the frozen Judge;
* bounded planner autonomy with zero production and finding authority.

The module intentionally depends only on cycle-free contracts.  The incident
builder can therefore seal these receipts before the enclosing Case SHA exists.
"""

from __future__ import annotations

import hashlib
import hmac
from enum import Enum
from typing import Iterable, Literal, Mapping, Protocol, Sequence

import rfc8785
from pydantic import ConfigDict, Field, model_validator

from .evidence_state_contracts import (
    EvidenceBeliefLedgerV2,
    EvidenceFreshnessStatusV2,
    SourceAuthorizationStatusV2,
    verify_evidence_belief_ledger_v2,
)
from .incident_model_planner import (
    IncidentModelMode,
    IncidentModelPlannerReceipt,
    verify_incident_model_planner_receipt,
)
from .incident_runtime_profile import IncidentRuntimeProfile
from .product_models import ProductModel
from .worker_selection import (
    WorkerSelectionReceipt,
    verify_worker_selection_receipt,
)


def _canonical_jcs_bytes(value: object) -> bytes:
    def json_value(item: object) -> object:
        if isinstance(item, ProductModel):
            return item.model_dump(mode="json")
        if isinstance(item, Enum):
            return item.value
        if isinstance(item, Mapping):
            return {str(key): json_value(nested) for key, nested in item.items()}
        if isinstance(item, (list, tuple)):
            return [json_value(nested) for nested in item]
        return item

    try:
        return rfc8785.dumps(json_value(value))
    except (rfc8785.CanonicalizationError, TypeError, UnicodeError) as error:
        raise ValueError(
            f"Agent-kernel payload cannot be canonicalized: {error}"
        ) from error


def _digest(domain: str, value: object) -> str:
    domain_bytes = domain.encode("ascii")
    payload = _canonical_jcs_bytes(value)
    framed = (
        b"VDG_AGENT_KERNEL_V1\x00"
        + len(domain_bytes).to_bytes(2, "big")
        + domain_bytes
        + len(payload).to_bytes(8, "big")
        + payload
    )
    return hashlib.sha256(framed).hexdigest()


class _HypothesisLike(Protocol):
    hypothesis_id: str
    supporting_issue_codes: list[str]
    contradicting_issue_codes: list[str]
    unresolved_evidence_refs: list[str]


class _WorkerReceiptLike(Protocol):
    worker_role: str
    status: str
    receipt_sha256: str
    input_evidence_sha256: list[str]


class BeliefFreshnessTransitionV1(ProductModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True, frozen=True)

    hypothesis_id: str = Field(min_length=1)
    previous_freshness: EvidenceFreshnessStatusV2
    effective_freshness: EvidenceFreshnessStatusV2
    reason_codes: list[str] = Field(min_length=1)


class EvidenceBeliefRevisionReceiptV1(ProductModel):
    """Immutable parent-ledger freshness assessment for one resumed Case."""

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True, frozen=True)

    schema_version: Literal["visiondata-gate.evidence-belief-revision-receipt.v1"] = (
        "visiondata-gate.evidence-belief-revision-receipt.v1"
    )
    parent_case_id: str = Field(pattern=r"^incident_[0-9a-f]{20}$")
    parent_case_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    source_ledger_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    observed_authorization_event_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    observed_authorization_status: SourceAuthorizationStatusV2
    observed_evidence_bundle_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    authorization_event_changed: bool
    evidence_bundle_changed: bool
    transitions: list[BeliefFreshnessTransitionV1] = Field(min_length=1)
    disposition: Literal[
        "CURRENT",
        "STALE_REPLAN_REQUIRED",
        "REVOKED_FAIL_CLOSED",
        "UNKNOWN_FAIL_CLOSED",
        "NOT_APPLICABLE",
    ]
    fresh_replan_required: bool
    fail_closed: bool
    receipt_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    claim_boundary: str = (
        "This receipt revises only evidence freshness against the observed source "
        "epoch. It does not mutate the parent Case, establish root cause, or grant "
        "production authority."
    )


def build_evidence_belief_revision_receipt_v1(
    *,
    parent_case_id: str,
    parent_case_sha256: str,
    source_ledger: EvidenceBeliefLedgerV2,
    observed_authorization_event_sha256: str,
    observed_authorization_status: SourceAuthorizationStatusV2,
    observed_evidence_bundle_sha256: str,
) -> EvidenceBeliefRevisionReceiptV1:
    """Assess a frozen parent ledger against the source facts seen on resume."""

    verify_evidence_belief_ledger_v2(source_ledger)
    source_facts = source_ledger.source_authorization_freshness
    authorization_changed = not hmac.compare_digest(
        source_facts.current_authorization_event_sha256,
        observed_authorization_event_sha256,
    )
    bundle_changed = not hmac.compare_digest(
        source_ledger.evidence_bundle_sha256,
        observed_evidence_bundle_sha256,
    )

    if observed_authorization_status == "REVOKED":
        effective = EvidenceFreshnessStatusV2.REVOKED
        disposition = "REVOKED_FAIL_CLOSED"
        fail_closed = True
    elif observed_authorization_status in {"EXPIRED", "UNAVAILABLE"}:
        effective = (
            EvidenceFreshnessStatusV2.STALE
            if observed_authorization_status == "EXPIRED"
            else EvidenceFreshnessStatusV2.UNKNOWN
        )
        disposition = "UNKNOWN_FAIL_CLOSED"
        fail_closed = True
    elif observed_authorization_status == "NOT_APPLICABLE":
        effective = EvidenceFreshnessStatusV2.UNKNOWN
        disposition = "NOT_APPLICABLE"
        fail_closed = False
    elif authorization_changed or bundle_changed:
        effective = EvidenceFreshnessStatusV2.STALE
        disposition = "STALE_REPLAN_REQUIRED"
        fail_closed = False
    else:
        effective = EvidenceFreshnessStatusV2.CURRENT
        disposition = "CURRENT"
        fail_closed = False

    transitions: list[BeliefFreshnessTransitionV1] = []
    for snapshot in source_ledger.snapshots:
        snapshot_effective = effective
        reason_codes: list[str] = []
        if observed_authorization_status == "REVOKED":
            reason_codes.append("AUTHORIZATION_REVOKED")
        elif observed_authorization_status == "EXPIRED":
            reason_codes.append("AUTHORIZATION_EXPIRED")
        elif observed_authorization_status == "UNAVAILABLE":
            reason_codes.append("AUTHORIZATION_UNAVAILABLE")
        elif observed_authorization_status == "NOT_APPLICABLE":
            reason_codes.append("AUTHORIZATION_NOT_APPLICABLE")
        if authorization_changed:
            reason_codes.append("AUTHORIZATION_EVENT_CHANGED")
        if bundle_changed:
            reason_codes.append("EVIDENCE_BUNDLE_CHANGED")
        if not reason_codes:
            snapshot_effective = snapshot.freshness_status
            reason_codes.append("SOURCE_EPOCH_UNCHANGED")
        transitions.append(
            BeliefFreshnessTransitionV1(
                hypothesis_id=snapshot.hypothesis_id,
                previous_freshness=snapshot.freshness_status,
                effective_freshness=snapshot_effective,
                reason_codes=sorted(set(reason_codes)),
            )
        )

    stable = {
        "schema_version": "visiondata-gate.evidence-belief-revision-receipt.v1",
        "parent_case_id": parent_case_id,
        "parent_case_sha256": parent_case_sha256,
        "source_ledger_sha256": source_ledger.ledger_sha256,
        "observed_authorization_event_sha256": observed_authorization_event_sha256,
        "observed_authorization_status": observed_authorization_status,
        "observed_evidence_bundle_sha256": observed_evidence_bundle_sha256,
        "authorization_event_changed": authorization_changed,
        "evidence_bundle_changed": bundle_changed,
        "transitions": transitions,
        "disposition": disposition,
        "fresh_replan_required": authorization_changed or bundle_changed or fail_closed,
        "fail_closed": fail_closed,
        "claim_boundary": EvidenceBeliefRevisionReceiptV1.model_fields[
            "claim_boundary"
        ].default,
    }
    return EvidenceBeliefRevisionReceiptV1(
        **stable,
        receipt_sha256=_digest("VDG_BELIEF_REVISION_RECEIPT_V1", stable),
    )


def verify_evidence_belief_revision_receipt_v1(
    receipt: EvidenceBeliefRevisionReceiptV1,
) -> None:
    hypothesis_ids = [item.hypothesis_id for item in receipt.transitions]
    if hypothesis_ids != sorted(set(hypothesis_ids)):
        raise ValueError("belief revision transitions must be sorted and unique")
    if receipt.disposition.endswith("FAIL_CLOSED") != receipt.fail_closed:
        raise ValueError("belief revision fail-closed disposition mismatch")
    if (
        receipt.authorization_event_changed or receipt.evidence_bundle_changed
    ) and not (receipt.fresh_replan_required):
        raise ValueError("belief revision drift requires a fresh replan")
    payload = receipt.model_dump(mode="json", exclude={"receipt_sha256"})
    expected = _digest("VDG_BELIEF_REVISION_RECEIPT_V1", payload)
    if not hmac.compare_digest(receipt.receipt_sha256, expected):
        raise ValueError("belief revision receipt digest mismatch")


class WorkerExecutionPlanNodeV1(ProductModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True, frozen=True)

    worker_id: str = Field(min_length=1)
    selection_rank: int = Field(ge=1)
    dependency_worker_ids: list[str] = Field(default_factory=list)
    requires_successful_dependencies: Literal[True] = True


class WorkerExecutionPlanReceiptV1(ProductModel):
    """Replayable execution DAG over the already selected Worker set."""

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True, frozen=True)

    schema_version: Literal["visiondata-gate.worker-execution-plan-receipt.v1"] = (
        "visiondata-gate.worker-execution-plan-receipt.v1"
    )
    selection_receipt_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    worker_budget: int = Field(ge=0)
    requested_priority_order: list[str]
    nodes: list[WorkerExecutionPlanNodeV1]
    execution_order: list[str]
    dependency_barrier_count: int = Field(ge=0)
    receipt_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")


def build_worker_execution_plan_receipt_v1(
    selection: WorkerSelectionReceipt,
    *,
    dependency_map: Mapping[str, Sequence[str]] | None = None,
    priority_order: Sequence[str] | None = None,
) -> WorkerExecutionPlanReceiptV1:
    verify_worker_selection_receipt(selection)
    selected = list(selection.selected_worker_ids)
    selected_set = set(selected)
    normalized_priority = list(priority_order or ())
    if len(normalized_priority) != len(set(normalized_priority)):
        raise ValueError("Worker execution priority contains duplicate Workers")
    unknown_priority = sorted(set(normalized_priority) - selected_set)
    if unknown_priority:
        raise ValueError(
            "Worker execution priority escaped the selected set: "
            + ", ".join(unknown_priority)
        )
    scheduling_order = normalized_priority + [
        worker_id for worker_id in selected if worker_id not in normalized_priority
    ]
    rank_by_worker = {
        item.worker_id: item.rank
        for item in selection.ranking
        if item.selected and item.rank is not None
    }
    normalized_dependencies: dict[str, list[str]] = {}
    for worker_id in selected:
        dependencies = sorted(set((dependency_map or {}).get(worker_id, ())))
        if worker_id in dependencies:
            raise ValueError("Worker execution plan cannot self-depend")
        unknown = sorted(set(dependencies) - selected_set)
        if unknown:
            raise ValueError(
                "Worker execution dependency was not selected: " + ", ".join(unknown)
            )
        normalized_dependencies[worker_id] = dependencies

    remaining = set(selected)
    completed: list[str] = []
    while remaining:
        ready = [
            worker_id
            for worker_id in scheduling_order
            if worker_id in remaining
            and set(normalized_dependencies[worker_id]) <= set(completed)
        ]
        if not ready:
            raise ValueError("Worker execution plan contains a dependency cycle")
        next_worker = ready[0]
        completed.append(next_worker)
        remaining.remove(next_worker)

    nodes = [
        WorkerExecutionPlanNodeV1(
            worker_id=worker_id,
            selection_rank=int(rank_by_worker[worker_id]),
            dependency_worker_ids=normalized_dependencies[worker_id],
        )
        for worker_id in selected
    ]
    stable = {
        "schema_version": "visiondata-gate.worker-execution-plan-receipt.v1",
        "selection_receipt_sha256": selection.receipt_sha256,
        "worker_budget": selection.worker_budget,
        "requested_priority_order": normalized_priority,
        "nodes": nodes,
        "execution_order": completed,
        "dependency_barrier_count": sum(
            len(item.dependency_worker_ids) for item in nodes
        ),
    }
    return WorkerExecutionPlanReceiptV1(
        **stable,
        receipt_sha256=_digest("VDG_WORKER_EXECUTION_PLAN_RECEIPT_V1", stable),
    )


def verify_worker_execution_plan_receipt_v1(
    receipt: WorkerExecutionPlanReceiptV1,
    *,
    selection: WorkerSelectionReceipt | None = None,
) -> None:
    worker_ids = [item.worker_id for item in receipt.nodes]
    if worker_ids != list(dict.fromkeys(worker_ids)):
        raise ValueError("Worker execution plan contains duplicate nodes")
    if set(receipt.execution_order) != set(worker_ids) or len(
        receipt.execution_order
    ) != len(worker_ids):
        raise ValueError("Worker execution order does not cover the selected nodes")
    observed: set[str] = set()
    node_by_id = {item.worker_id: item for item in receipt.nodes}
    for worker_id in receipt.execution_order:
        node = node_by_id[worker_id]
        if not set(node.dependency_worker_ids) <= observed:
            raise ValueError("Worker execution order violates a dependency barrier")
        observed.add(worker_id)
    if receipt.dependency_barrier_count != sum(
        len(item.dependency_worker_ids) for item in receipt.nodes
    ):
        raise ValueError("Worker dependency barrier count mismatch")
    if len(receipt.requested_priority_order) != len(
        set(receipt.requested_priority_order)
    ) or not set(receipt.requested_priority_order) <= set(worker_ids):
        raise ValueError("Worker execution priority escaped the plan")
    payload = receipt.model_dump(mode="json", exclude={"receipt_sha256"})
    expected = _digest("VDG_WORKER_EXECUTION_PLAN_RECEIPT_V1", payload)
    if not hmac.compare_digest(receipt.receipt_sha256, expected):
        raise ValueError("Worker execution plan receipt digest mismatch")
    if selection is not None:
        expected_plan = build_worker_execution_plan_receipt_v1(
            selection,
            dependency_map={
                item.worker_id: item.dependency_worker_ids for item in receipt.nodes
            },
            priority_order=receipt.requested_priority_order,
        )
        if expected_plan != receipt:
            raise ValueError("Worker execution plan diverged from selection")


class CouncilHypothesisExaminationV1(ProductModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True, frozen=True)

    hypothesis_id: str = Field(min_length=1)
    supporting_issue_codes: list[str]
    contradicting_issue_codes: list[str]
    unresolved_evidence_refs: list[str]
    examination_status: Literal[
        "CONFLICT",
        "UNRESOLVED",
        "SUPPORTED_ONLY",
        "CONTRADICTED_ONLY",
        "NO_QUALIFIED_EVIDENCE",
    ]
    root_cause_established: Literal[False] = False


class CouncilArbitrationReceiptV1(ProductModel):
    """Deterministic cross-tool examination; never a causal diagnosis."""

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True, frozen=True)

    schema_version: Literal["visiondata-gate.council-arbitration-receipt.v1"] = (
        "visiondata-gate.council-arbitration-receipt.v1"
    )
    case_id: str = Field(pattern=r"^incident_[0-9a-f]{20}$")
    belief_ledger_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    worker_execution_plan_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    worker_receipt_sha256s: list[str]
    failed_worker_ids: list[str]
    examinations: list[CouncilHypothesisExaminationV1] = Field(min_length=1)
    conflict_count: int = Field(ge=0)
    unresolved_hypothesis_count: int = Field(ge=0)
    disposition: Literal[
        "BLOCKED_INCOMPLETE_EVIDENCE",
        "HUMAN_INVESTIGATION_REQUIRED",
        "PROCEED_WITH_OPEN_GAPS",
        "PROCEED_NO_CONFLICT",
    ]
    policy_directive: Literal["FAIL_CLOSED", "CONTINUE_HOLD", "ADVISORY_ONLY"]
    root_cause_status: Literal["NOT_ESTABLISHED"] = "NOT_ESTABLISHED"
    receipt_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    claim_boundary: str = (
        "The Council receipt classifies support, contradiction, and unresolved gaps "
        "from existing deterministic evidence. It does not infer physical causality, "
        "label a root cause, or override the frozen Policy Judge."
    )


def build_council_arbitration_receipt_v1(
    *,
    case_id: str,
    belief_ledger: EvidenceBeliefLedgerV2,
    worker_execution_plan: WorkerExecutionPlanReceiptV1,
    worker_receipts: Iterable[_WorkerReceiptLike],
    hypotheses: Iterable[_HypothesisLike],
) -> CouncilArbitrationReceiptV1:
    verify_evidence_belief_ledger_v2(belief_ledger)
    verify_worker_execution_plan_receipt_v1(worker_execution_plan)
    receipts = sorted(list(worker_receipts), key=lambda item: item.worker_role)
    receipt_roles = [item.worker_role for item in receipts]
    if receipt_roles != sorted(set(receipt_roles)):
        raise ValueError("Council received duplicate Worker roles")
    failed_worker_ids = sorted(
        item.worker_role for item in receipts if item.status != "SUCCEEDED"
    )
    examinations: list[CouncilHypothesisExaminationV1] = []
    for hypothesis in sorted(hypotheses, key=lambda item: item.hypothesis_id):
        supports = sorted(set(hypothesis.supporting_issue_codes))
        contradicts = sorted(set(hypothesis.contradicting_issue_codes))
        unresolved = sorted(set(hypothesis.unresolved_evidence_refs))
        if supports and contradicts:
            status = "CONFLICT"
        elif unresolved:
            status = "UNRESOLVED"
        elif supports:
            status = "SUPPORTED_ONLY"
        elif contradicts:
            status = "CONTRADICTED_ONLY"
        else:
            status = "NO_QUALIFIED_EVIDENCE"
        examinations.append(
            CouncilHypothesisExaminationV1(
                hypothesis_id=hypothesis.hypothesis_id,
                supporting_issue_codes=supports,
                contradicting_issue_codes=contradicts,
                unresolved_evidence_refs=unresolved,
                examination_status=status,
            )
        )

    freshness = belief_ledger.source_authorization_freshness
    freshness_blocks = (
        freshness.current_authorization_status != "NOT_APPLICABLE"
        and freshness.freshness_status is not EvidenceFreshnessStatusV2.CURRENT
    )
    conflict_count = sum(item.examination_status == "CONFLICT" for item in examinations)
    unresolved_count = sum(
        item.examination_status in {"UNRESOLVED", "NO_QUALIFIED_EVIDENCE"}
        for item in examinations
    )
    if failed_worker_ids or freshness_blocks:
        disposition = "BLOCKED_INCOMPLETE_EVIDENCE"
        directive = "FAIL_CLOSED"
    elif conflict_count:
        disposition = "HUMAN_INVESTIGATION_REQUIRED"
        directive = "CONTINUE_HOLD"
    elif unresolved_count:
        disposition = "PROCEED_WITH_OPEN_GAPS"
        directive = "ADVISORY_ONLY"
    else:
        disposition = "PROCEED_NO_CONFLICT"
        directive = "ADVISORY_ONLY"

    stable = {
        "schema_version": "visiondata-gate.council-arbitration-receipt.v1",
        "case_id": case_id,
        "belief_ledger_sha256": belief_ledger.ledger_sha256,
        "worker_execution_plan_sha256": worker_execution_plan.receipt_sha256,
        "worker_receipt_sha256s": sorted(item.receipt_sha256 for item in receipts),
        "failed_worker_ids": failed_worker_ids,
        "examinations": examinations,
        "conflict_count": conflict_count,
        "unresolved_hypothesis_count": unresolved_count,
        "disposition": disposition,
        "policy_directive": directive,
        "root_cause_status": "NOT_ESTABLISHED",
        "claim_boundary": CouncilArbitrationReceiptV1.model_fields[
            "claim_boundary"
        ].default,
    }
    return CouncilArbitrationReceiptV1(
        **stable,
        receipt_sha256=_digest("VDG_COUNCIL_ARBITRATION_RECEIPT_V1", stable),
    )


def verify_council_arbitration_receipt_v1(
    receipt: CouncilArbitrationReceiptV1,
) -> None:
    hypothesis_ids = [item.hypothesis_id for item in receipt.examinations]
    if hypothesis_ids != sorted(set(hypothesis_ids)):
        raise ValueError("Council examinations must be sorted and unique")
    if receipt.worker_receipt_sha256s != sorted(set(receipt.worker_receipt_sha256s)):
        raise ValueError("Council Worker receipt references must be sorted and unique")
    if receipt.failed_worker_ids != sorted(set(receipt.failed_worker_ids)):
        raise ValueError("Council failed Worker IDs must be sorted and unique")
    if receipt.conflict_count != sum(
        item.examination_status == "CONFLICT" for item in receipt.examinations
    ):
        raise ValueError("Council conflict count mismatch")
    if receipt.unresolved_hypothesis_count != sum(
        item.examination_status in {"UNRESOLVED", "NO_QUALIFIED_EVIDENCE"}
        for item in receipt.examinations
    ):
        raise ValueError("Council unresolved count mismatch")
    if receipt.disposition == "BLOCKED_INCOMPLETE_EVIDENCE" and (
        receipt.policy_directive != "FAIL_CLOSED"
    ):
        raise ValueError("Council incomplete evidence must fail closed")
    payload = receipt.model_dump(mode="json", exclude={"receipt_sha256"})
    expected = _digest("VDG_COUNCIL_ARBITRATION_RECEIPT_V1", payload)
    if not hmac.compare_digest(receipt.receipt_sha256, expected):
        raise ValueError("Council arbitration receipt digest mismatch")


class AutonomyGuardReceiptV1(ProductModel):
    """Sealed proof of the narrow authority available to the optional planner."""

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True, frozen=True)

    schema_version: Literal["visiondata-gate.autonomy-guard-receipt.v1"] = (
        "visiondata-gate.autonomy-guard-receipt.v1"
    )
    case_id: str = Field(pattern=r"^incident_[0-9a-f]{20}$")
    runtime_profile_sha256: str | None = Field(default=None, pattern=r"^[0-9a-f]{64}$")
    planner_mode: IncidentModelMode
    selection_receipt_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    worker_budget: int = Field(ge=0)
    selected_worker_ids: list[str]
    applied_worker_priority_ids: list[str]
    model_call_count: int = Field(ge=0, le=1)
    context_budget_enforced: Literal[True] = True
    context_budget_exceeded: bool
    deterministic_fallback_used: bool
    allowed_model_effect: Literal["NONE", "ADVISORY_ONLY", "WORKER_PRIORITY_ONLY"]
    model_may_create_findings: Literal[False] = False
    model_may_approve_capa: Literal[False] = False
    model_may_release_production: Literal[False] = False
    model_may_write_machine: Literal[False] = False
    receipt_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")

    @model_validator(mode="after")
    def validate_authority(self) -> AutonomyGuardReceiptV1:
        if not set(self.applied_worker_priority_ids) <= set(self.selected_worker_ids):
            raise ValueError("model priority escaped the selected Worker set")
        if self.context_budget_exceeded and self.model_call_count != 0:
            raise ValueError("context budget excess must short-circuit model calls")
        if self.planner_mode is IncidentModelMode.OFF and (
            self.model_call_count != 0 or self.allowed_model_effect != "NONE"
        ):
            raise ValueError("off mode cannot retain model authority")
        if (
            self.planner_mode is IncidentModelMode.SHADOW
            and self.applied_worker_priority_ids
        ):
            raise ValueError("shadow mode cannot change Worker priority")
        return self


def build_autonomy_guard_receipt_v1(
    *,
    case_id: str,
    runtime_profile: IncidentRuntimeProfile | None,
    selection: WorkerSelectionReceipt,
    planner_receipt: IncidentModelPlannerReceipt | None,
) -> AutonomyGuardReceiptV1:
    verify_worker_selection_receipt(selection)
    mode = (
        runtime_profile.planner_mode
        if runtime_profile is not None
        else IncidentModelMode.OFF
    )
    if planner_receipt is not None:
        verify_incident_model_planner_receipt(planner_receipt)
        if planner_receipt.mode is not mode:
            raise ValueError("planner receipt mode diverged from the runtime profile")
        applied = list(planner_receipt.applied_worker_order)
        model_call_count = planner_receipt.model_call_count
        context_exceeded = "CONTEXT_BUDGET_EXCEEDED" in (
            planner_receipt.validation_errors
        )
        fallback = planner_receipt.gating_effect == "DETERMINISTIC_FALLBACK"
    else:
        if mode is not IncidentModelMode.OFF:
            raise ValueError("enabled planner mode requires a planner receipt")
        applied = []
        model_call_count = 0
        context_exceeded = False
        fallback = False

    if mode is IncidentModelMode.OFF:
        allowed_effect = "NONE"
    elif mode is IncidentModelMode.SHADOW:
        allowed_effect = "ADVISORY_ONLY"
    else:
        allowed_effect = "WORKER_PRIORITY_ONLY"
    stable = {
        "schema_version": "visiondata-gate.autonomy-guard-receipt.v1",
        "case_id": case_id,
        "runtime_profile_sha256": (
            runtime_profile.profile_sha256() if runtime_profile is not None else None
        ),
        "planner_mode": mode,
        "selection_receipt_sha256": selection.receipt_sha256,
        "worker_budget": selection.worker_budget,
        "selected_worker_ids": list(selection.selected_worker_ids),
        "applied_worker_priority_ids": applied,
        "model_call_count": model_call_count,
        "context_budget_enforced": True,
        "context_budget_exceeded": context_exceeded,
        "deterministic_fallback_used": fallback,
        "allowed_model_effect": allowed_effect,
        "model_may_create_findings": False,
        "model_may_approve_capa": False,
        "model_may_release_production": False,
        "model_may_write_machine": False,
    }
    return AutonomyGuardReceiptV1(
        **stable,
        receipt_sha256=_digest("VDG_AUTONOMY_GUARD_RECEIPT_V1", stable),
    )


def verify_autonomy_guard_receipt_v1(
    receipt: AutonomyGuardReceiptV1,
    *,
    selection: WorkerSelectionReceipt | None = None,
    planner_receipt: IncidentModelPlannerReceipt | None = None,
    require_planner_binding: bool = False,
) -> None:
    payload = receipt.model_dump(mode="json", exclude={"receipt_sha256"})
    expected = _digest("VDG_AUTONOMY_GUARD_RECEIPT_V1", payload)
    if not hmac.compare_digest(receipt.receipt_sha256, expected):
        raise ValueError("autonomy guard receipt digest mismatch")
    if selection is not None:
        if (
            not hmac.compare_digest(
                receipt.selection_receipt_sha256, selection.receipt_sha256
            )
            or receipt.selected_worker_ids != selection.selected_worker_ids
        ):
            raise ValueError("autonomy guard lost Worker selection binding")
    if planner_receipt is not None:
        verify_incident_model_planner_receipt(planner_receipt)
        if (
            receipt.model_call_count != planner_receipt.model_call_count
            or receipt.applied_worker_priority_ids
            != planner_receipt.applied_worker_order
        ):
            raise ValueError("autonomy guard lost planner receipt binding")
    elif require_planner_binding and receipt.planner_mode is not IncidentModelMode.OFF:
        raise ValueError("enabled autonomy guard lacks a planner receipt")


__all__ = [
    "AutonomyGuardReceiptV1",
    "BeliefFreshnessTransitionV1",
    "CouncilArbitrationReceiptV1",
    "CouncilHypothesisExaminationV1",
    "EvidenceBeliefRevisionReceiptV1",
    "WorkerExecutionPlanNodeV1",
    "WorkerExecutionPlanReceiptV1",
    "build_autonomy_guard_receipt_v1",
    "build_council_arbitration_receipt_v1",
    "build_evidence_belief_revision_receipt_v1",
    "build_worker_execution_plan_receipt_v1",
    "verify_autonomy_guard_receipt_v1",
    "verify_council_arbitration_receipt_v1",
    "verify_evidence_belief_revision_receipt_v1",
    "verify_worker_execution_plan_receipt_v1",
]
