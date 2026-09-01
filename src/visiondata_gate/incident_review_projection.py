"""Read-only reviewer projection over already verified Incident artifacts.

This module does not plan, call tools, or create new evidence.  It only projects
persisted Incident, human-decision, CAPA, and Task-lineage facts into one
frontend-oriented contract whose own SHA-256 can be checked at the HTTP edge.
"""

from __future__ import annotations

import hashlib
import hmac
from enum import Enum
from typing import Literal

from pydantic import Field

from .capa import CapaCaseReport
from .evidence import canonical_json_bytes
from .incident_control_plane import (
    IncidentControlPlaneBundle,
    IncidentHypothesisContrast,
    verify_incident_control_plane,
)
from .industrial_incident import (
    OPCUASnapshotMode,
    IndustrialIncidentCase,
    IndustrialIncidentDecisionReceipt,
    verify_industrial_incident_case,
)
from .lineage import TaskLineageReport
from .product_models import ProductModel
from .worker_selection import (
    build_agent_behavior_receipt,
    verify_agent_behavior_receipt,
    verify_worker_selection_receipt,
)


def _sha256(value: object) -> str:
    return hashlib.sha256(canonical_json_bytes(value)).hexdigest()


def _enum_value(value: object) -> str:
    return str(value.value) if isinstance(value, Enum) else str(value)


class IncidentReviewWorker(ProductModel):
    worker_id: str
    eligible: bool
    selected: bool
    rank: int | None
    reason_codes: list[str] = Field(min_length=1)
    blocking_severity: Literal["NONE", "WARNING", "BLOCKING"]
    discriminated_hypothesis_ids: list[str]
    unresolved_evidence_refs: list[str]
    measured_cost_bucket: Literal["LOW", "MEDIUM", "HIGH", "UNKNOWN"]
    exclusion_reasons: list[str]


class IncidentReviewWorkerTrigger(ProductModel):
    worker_role: str
    invocation_id: str
    status: Literal["SUCCEEDED", "FAILED"]
    trigger_reason_codes: list[str] = Field(min_length=1)
    input_evidence_sha256: list[str] = Field(min_length=1)
    receipt_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")


class IncidentReviewCaseLink(ProductModel):
    case_id: str
    case_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    case_version: int = Field(ge=1)
    status: str
    recommendation: str
    parent_case_id: str | None
    parent_case_sha256: str | None = Field(default=None, pattern=r"^[0-9a-f]{64}$")
    authorizing_decision_id: str | None
    authorizing_decision_sha256: str | None = Field(
        default=None,
        pattern=r"^[0-9a-f]{64}$",
    )


class IncidentReviewHumanDecision(ProductModel):
    decision_id: str
    case_id: str
    case_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    actor_user_id: str
    decision: str
    linked_capa_case_id: str | None
    decision_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    production_release_allowed: Literal[False] = False
    equipment_control_allowed: Literal[False] = False


class IncidentReviewCapaLink(ProductModel):
    case_id: str
    status: str
    selection_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    approval_binding_sha256: str | None = Field(
        default=None,
        pattern=r"^[0-9a-f]{64}$",
    )
    child_task_id: str | None
    child_evidence_sha256: str | None = Field(
        default=None,
        pattern=r"^[0-9a-f]{64}$",
    )
    child_lineage_report_sha256: str | None = Field(
        default=None,
        pattern=r"^[0-9a-f]{64}$",
    )
    execution_receipt_sha256: str | None = Field(
        default=None,
        pattern=r"^[0-9a-f]{64}$",
    )
    recovery_receipt_sha256: str | None = Field(
        default=None,
        pattern=r"^[0-9a-f]{64}$",
    )


class IncidentReviewTaskNode(ProductModel):
    task_id: str
    parent_task_id: str | None
    depth: int = Field(ge=0)
    execution_status: str
    final_decision: str | None
    evidence_sha256: str | None = Field(default=None, pattern=r"^[0-9a-f]{64}$")


class IncidentReviewProjection(ProductModel):
    schema_version: Literal["visiondata-gate.incident-review-projection.v1"] = (
        "visiondata-gate.incident-review-projection.v1"
    )
    task_id: str
    case_id: str
    case_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    transport_source_mode: Literal["LIVE"] = "LIVE"
    evidence_source_mode: Literal["REPLAY", "OFFLINE_EXPORT"]
    factory_live_connection_claimed: Literal[False] = False
    worker_budget: int = Field(ge=0)
    selected_workers: list[IncidentReviewWorker]
    rejected_workers: list[IncidentReviewWorker]
    triggering_evidence: list[IncidentReviewWorkerTrigger]
    competing_hypotheses: list[IncidentHypothesisContrast] = Field(min_length=6)
    missing_evidence_refs: list[str]
    what_would_change_decision: list[str] = Field(min_length=1)
    current_case: IncidentReviewCaseLink
    parent_case: IncidentReviewCaseLink | None
    child_cases: list[IncidentReviewCaseLink]
    human_decisions: list[IncidentReviewHumanDecision]
    capa_cases: list[IncidentReviewCapaLink]
    missing_linked_capa_case_ids: list[str]
    task_lineage_nodes: list[IncidentReviewTaskNode] = Field(min_length=1)
    task_lineage_report_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    worker_selection_receipt_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    agent_behavior_receipt_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    control_plane_bundle_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    contrastive_decision_packet_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    production_release_allowed: Literal[False] = False
    machine_write_permitted: Literal[False] = False
    projection_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    claim_boundary: str = (
        "LIVE means this projection was read from the current local API, not that a "
        "factory endpoint is connected. REPLAY remains fixture evidence; OFFLINE_EXPORT "
        "remains authorized offline input. Missing linked CAPA records are named in "
        "missing_linked_capa_case_ids; absent Parent, human, or Child records remain "
        "empty. Missing lifecycle facts never imply PASS or production release."
    )


def _case_link(case: IndustrialIncidentCase) -> IncidentReviewCaseLink:
    return IncidentReviewCaseLink(
        case_id=case.case_id,
        case_sha256=case.case_sha256,
        case_version=case.case_version,
        status=_enum_value(case.status),
        recommendation=case.recommendation,
        parent_case_id=case.parent_case_id,
        parent_case_sha256=case.parent_case_sha256,
        authorizing_decision_id=case.authorizing_decision_id,
        authorizing_decision_sha256=case.authorizing_decision_sha256,
    )


def build_incident_review_projection(
    *,
    case: IndustrialIncidentCase,
    related_cases: list[IndustrialIncidentCase],
    decisions: list[IndustrialIncidentDecisionReceipt],
    control_plane: IncidentControlPlaneBundle,
    capa_cases: list[CapaCaseReport],
    task_lineage: TaskLineageReport,
) -> IncidentReviewProjection:
    """Project verified product facts without filling absent lifecycle records."""

    verify_industrial_incident_case(case)
    verify_worker_selection_receipt(case.worker_selection_receipt)
    behavior = build_agent_behavior_receipt(case.worker_selection_receipt)
    verify_agent_behavior_receipt(
        behavior,
        selection=case.worker_selection_receipt,
    )
    verify_incident_control_plane(control_plane, case=case)
    if task_lineage.focus_task_id != case.task_id:
        raise ValueError("review projection task lineage lost focus-task binding")

    cases_by_id = {item.case_id: item for item in related_cases}
    if cases_by_id.get(case.case_id) != case:
        raise ValueError("review projection related-case set omitted the current case")
    parent = cases_by_id.get(case.parent_case_id) if case.parent_case_id else None
    if case.parent_case_id is not None and parent is None:
        raise ValueError("review projection cannot resolve the declared parent case")
    if parent is not None and not hmac.compare_digest(
        case.parent_case_sha256 or "",
        parent.case_sha256,
    ):
        raise ValueError("review projection parent Case SHA binding failed")
    for related in related_cases:
        verify_industrial_incident_case(related)
        if related.parent_case_id == case.case_id and not hmac.compare_digest(
            related.parent_case_sha256 or "",
            case.case_sha256,
        ):
            raise ValueError("review projection Child Case SHA binding failed")

    candidate_by_id = {
        item.worker_id: item for item in case.worker_selection_receipt.candidates
    }
    behavior_by_id = {
        item.worker_id: item for item in (*behavior.selected, *behavior.rejected)
    }
    workers: list[IncidentReviewWorker] = []
    for ranking in case.worker_selection_receipt.ranking:
        candidate = candidate_by_id.get(ranking.worker_id)
        behavior_decision = behavior_by_id.get(ranking.worker_id)
        if candidate is None or behavior_decision is None:
            raise ValueError("review projection Worker ranking lost behavior binding")
        workers.append(
            IncidentReviewWorker(
                worker_id=ranking.worker_id,
                eligible=ranking.eligible,
                selected=ranking.selected,
                rank=ranking.rank,
                reason_codes=behavior_decision.reason_codes,
                blocking_severity=candidate.blocking_severity.value,
                discriminated_hypothesis_ids=(candidate.discriminated_hypothesis_ids),
                unresolved_evidence_refs=candidate.unresolved_evidence_refs,
                measured_cost_bucket=candidate.measured_cost_bucket.value,
                exclusion_reasons=ranking.exclusion_reasons,
            )
        )

    decision_scope_case_id = case.parent_case_id or case.case_id
    decision_scope_sha256 = (
        parent.case_sha256 if parent is not None else case.case_sha256
    )
    for decision in decisions:
        if decision.case_id != decision_scope_case_id or not hmac.compare_digest(
            decision.case_sha256,
            decision_scope_sha256,
        ):
            raise ValueError("review projection human decision lost case binding")
    if case.authorizing_decision_id is not None:
        authorizing_decision = next(
            (
                item
                for item in decisions
                if item.decision_id == case.authorizing_decision_id
            ),
            None,
        )
        if authorizing_decision is None or not hmac.compare_digest(
            authorizing_decision.decision_sha256,
            case.authorizing_decision_sha256 or "",
        ):
            raise ValueError("review projection Child Case lost Human decision binding")
    linked_capa_ids = {
        item.linked_capa_case_id
        for item in decisions
        if item.linked_capa_case_id is not None
    }
    linked_capas = [item for item in capa_cases if item.case_id in linked_capa_ids]
    linked_capa_case_ids = {item.case_id for item in linked_capas}
    missing_linked_capa_case_ids = sorted(linked_capa_ids - linked_capa_case_ids)
    lineage_nodes_by_id = {item.task_id: item for item in task_lineage.nodes}
    for item in linked_capas:
        if item.execution is None:
            continue
        child_node = lineage_nodes_by_id.get(item.execution.child_task_id)
        if (
            child_node is None
            or child_node.parent_task_id != case.task_id
            or not hmac.compare_digest(
                child_node.evidence_sha256 or "",
                item.execution.child_evidence_sha256,
            )
        ):
            raise ValueError("review projection CAPA Child Task lineage binding failed")

    packet = control_plane.decision_packet
    stable = {
        "schema_version": "visiondata-gate.incident-review-projection.v1",
        "task_id": case.task_id,
        "case_id": case.case_id,
        "case_sha256": case.case_sha256,
        "transport_source_mode": "LIVE",
        "evidence_source_mode": (
            "REPLAY"
            if case.request.opcua_snapshot.source_mode
            is OPCUASnapshotMode.FIXTURE_REPLAY
            else "OFFLINE_EXPORT"
        ),
        "factory_live_connection_claimed": False,
        "worker_budget": case.worker_selection_receipt.worker_budget,
        "selected_workers": [item for item in workers if item.selected],
        "rejected_workers": [item for item in workers if not item.selected],
        "triggering_evidence": [
            IncidentReviewWorkerTrigger(
                worker_role=item.worker_role,
                invocation_id=item.invocation_id,
                status=item.status,
                trigger_reason_codes=item.trigger_reason_codes,
                input_evidence_sha256=item.input_evidence_sha256,
                receipt_sha256=item.receipt_sha256,
            )
            for item in case.worker_receipts
        ],
        "competing_hypotheses": packet.hypothesis_contrasts,
        "missing_evidence_refs": packet.missing_evidence_refs,
        "what_would_change_decision": packet.what_would_change_decision,
        "current_case": _case_link(case),
        "parent_case": _case_link(parent) if parent is not None else None,
        "child_cases": [
            _case_link(item)
            for item in sorted(related_cases, key=lambda value: value.case_version)
            if item.parent_case_id == case.case_id
        ],
        "human_decisions": [
            IncidentReviewHumanDecision(
                decision_id=item.decision_id,
                case_id=item.case_id,
                case_sha256=item.case_sha256,
                actor_user_id=item.actor_user_id,
                decision=_enum_value(item.decision),
                linked_capa_case_id=item.linked_capa_case_id,
                decision_sha256=item.decision_sha256,
                production_release_allowed=False,
                equipment_control_allowed=False,
            )
            for item in decisions
        ],
        "capa_cases": [
            IncidentReviewCapaLink(
                case_id=item.case_id,
                status=_enum_value(item.status),
                selection_sha256=item.selection.selection_sha256,
                approval_binding_sha256=(
                    item.approval.binding_sha256 if item.approval is not None else None
                ),
                child_task_id=(
                    item.execution.child_task_id if item.execution is not None else None
                ),
                child_evidence_sha256=(
                    item.execution.child_evidence_sha256
                    if item.execution is not None
                    else None
                ),
                child_lineage_report_sha256=(
                    item.execution.child_lineage_report_sha256
                    if item.execution is not None
                    else None
                ),
                execution_receipt_sha256=(
                    item.execution.receipt_sha256
                    if item.execution is not None
                    else None
                ),
                recovery_receipt_sha256=(
                    item.recovery.receipt_sha256 if item.recovery is not None else None
                ),
            )
            for item in sorted(linked_capas, key=lambda value: value.case_id)
        ],
        "missing_linked_capa_case_ids": missing_linked_capa_case_ids,
        "task_lineage_nodes": [
            IncidentReviewTaskNode(
                task_id=item.task_id,
                parent_task_id=item.parent_task_id,
                depth=item.depth,
                execution_status=_enum_value(item.execution_status),
                final_decision=(
                    _enum_value(item.final_decision)
                    if item.final_decision is not None
                    else None
                ),
                evidence_sha256=item.evidence_sha256,
            )
            for item in task_lineage.nodes
        ],
        "task_lineage_report_sha256": task_lineage.report_sha256,
        "worker_selection_receipt_sha256": (
            case.worker_selection_receipt.receipt_sha256
        ),
        "agent_behavior_receipt_sha256": behavior.receipt_sha256,
        "control_plane_bundle_sha256": control_plane.bundle_sha256,
        "contrastive_decision_packet_sha256": packet.packet_sha256,
        "production_release_allowed": False,
        "machine_write_permitted": False,
        "claim_boundary": IncidentReviewProjection.model_fields[
            "claim_boundary"
        ].default,
    }
    projection = IncidentReviewProjection(
        **stable,
        projection_sha256=_sha256(stable),
    )
    verify_incident_review_projection(projection, case=case)
    return projection


def verify_incident_review_projection(
    projection: IncidentReviewProjection,
    *,
    case: IndustrialIncidentCase,
) -> None:
    payload = projection.model_dump(mode="json", exclude={"projection_sha256"})
    if not hmac.compare_digest(projection.projection_sha256, _sha256(payload)):
        raise ValueError("incident review projection failed SHA-256 validation")
    if (
        projection.task_id != case.task_id
        or projection.case_id != case.case_id
        or not hmac.compare_digest(projection.case_sha256, case.case_sha256)
    ):
        raise ValueError("incident review projection failed current-case binding")
    selection = case.worker_selection_receipt
    verify_worker_selection_receipt(selection)
    behavior = build_agent_behavior_receipt(selection)
    verify_agent_behavior_receipt(behavior, selection=selection)
    projected_workers = [*projection.selected_workers, *projection.rejected_workers]
    projected_by_id = {item.worker_id: item for item in projected_workers}
    behavior_decisions = [*behavior.selected, *behavior.rejected]
    if (
        projection.worker_budget != selection.worker_budget
        or projection.worker_selection_receipt_sha256 != selection.receipt_sha256
        or projection.agent_behavior_receipt_sha256 != behavior.receipt_sha256
        or [item.worker_id for item in projection.selected_workers]
        != selection.selected_worker_ids
        or len(projected_by_id) != len(projected_workers)
        or set(projected_by_id) != {item.worker_id for item in behavior_decisions}
        or any(
            projected_by_id[item.worker_id].reason_codes != item.reason_codes
            for item in behavior_decisions
        )
    ):
        raise ValueError("incident review projection failed Worker behavior binding")
    if projection.production_release_allowed or projection.machine_write_permitted:
        raise ValueError("incident review projection exceeded read-only authority")


__all__ = [
    "IncidentReviewProjection",
    "build_incident_review_projection",
    "verify_incident_review_projection",
]
