"""Read-only belief snapshots derived from industrial incident evidence.

The incident case remains the sole source of truth.  This module copies no
mutable business state back into the case; it derives frozen support and
freshness views from ``IncidentHypothesis`` and ``IncidentEvidenceEdge`` and
binds each view to the source case and evidence-bundle digests.
"""

from __future__ import annotations

import hashlib
import hmac
from enum import Enum
from typing import Iterable, Literal

import rfc8785
from pydantic import ConfigDict, Field

from .evidence_state_contracts import (
    EvidenceBeliefLedgerV2,
    EvidenceBeliefSnapshotV2,
    EvidenceFreshnessStatusV2,
    EvidenceSupportStatusV2,
    SourceAuthorizationFreshnessFactsV2,
    build_case_evidence_belief_ledger_v2,
    build_evidence_belief_snapshot_v2,
    build_source_authorization_freshness_facts_v2,
    verify_evidence_belief_ledger_v2,
    verify_evidence_belief_snapshot_v2,
    verify_source_authorization_freshness_facts_v2,
)
from .industrial_incident import (
    HypothesisStatus,
    IncidentEvidenceEdge,
    IncidentHypothesis,
    IndustrialIncidentCase,
    industrial_incident_evidence_bundle_sha256,
)
from .product_models import ProductModel


class EvidenceSupportStatus(str, Enum):
    SUPPORTED = "SUPPORTED"
    CONTRADICTED = "CONTRADICTED"
    UNRESOLVED = "UNRESOLVED"
    NOT_SUPPORTED = "NOT_SUPPORTED"


class EvidenceFreshnessStatus(str, Enum):
    CURRENT = "CURRENT"
    STALE = "STALE"
    REVOKED = "REVOKED"
    UNKNOWN = "UNKNOWN"


class EvidenceBeliefSnapshot(ProductModel):
    """Frozen projection of one hypothesis at one evidence epoch."""

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True, frozen=True)

    schema_version: Literal["visiondata-gate.evidence-belief-snapshot.v1"] = (
        "visiondata-gate.evidence-belief-snapshot.v1"
    )
    source_case_id: str = Field(pattern=r"^incident_[0-9a-f]{20}$")
    source_case_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    hypothesis_id: str = Field(min_length=1)
    source_hypothesis_status: HypothesisStatus
    support_status: EvidenceSupportStatus
    freshness_status: EvidenceFreshnessStatus
    supporting_evidence_refs: list[str] = Field(default_factory=list)
    contradicting_evidence_refs: list[str] = Field(default_factory=list)
    unresolved_evidence_refs: list[str] = Field(default_factory=list)
    unresolved_evidence_count: int = Field(ge=0)
    evidence_bundle_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    source_freshness_epoch_sha256: str | None = Field(
        default=None, pattern=r"^[0-9a-f]{64}$"
    )
    current_freshness_epoch_sha256: str | None = Field(
        default=None, pattern=r"^[0-9a-f]{64}$"
    )
    source_hypothesis_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    source_edge_sha256s: list[str] = Field(default_factory=list)
    derived_evidence_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    snapshot_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")


class EvidenceBeliefLedger(ProductModel):
    """Frozen set of belief snapshots for one incident case."""

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True, frozen=True)

    schema_version: Literal["visiondata-gate.evidence-belief-ledger.v1"] = (
        "visiondata-gate.evidence-belief-ledger.v1"
    )
    source_case_id: str = Field(pattern=r"^incident_[0-9a-f]{20}$")
    source_case_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    evidence_bundle_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    snapshots: list[EvidenceBeliefSnapshot] = Field(min_length=1)
    ledger_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")


def _canonical_jcs_bytes(value: object) -> bytes:
    try:
        return rfc8785.dumps(value)
    except (rfc8785.CanonicalizationError, TypeError, UnicodeError) as error:
        raise ValueError(
            f"evidence belief payload cannot be canonicalized: {error}"
        ) from error


def _sha256(value: object) -> str:
    return hashlib.sha256(_canonical_jcs_bytes(value)).hexdigest()


def _edge_sha256(edge: IncidentEvidenceEdge) -> str:
    return _sha256(edge.model_dump(mode="json"))


def _support_status(
    hypothesis: IncidentHypothesis,
    supporting_refs: list[str],
    contradicting_refs: list[str],
    unresolved_refs: list[str],
) -> EvidenceSupportStatus:
    if supporting_refs and contradicting_refs:
        return EvidenceSupportStatus.UNRESOLVED
    if supporting_refs:
        return EvidenceSupportStatus.SUPPORTED
    if contradicting_refs:
        return EvidenceSupportStatus.CONTRADICTED
    if unresolved_refs or hypothesis.status in {
        HypothesisStatus.UNRESOLVED,
        HypothesisStatus.PLAUSIBLE,
    }:
        return EvidenceSupportStatus.UNRESOLVED
    return EvidenceSupportStatus.NOT_SUPPORTED


def _freshness_status(
    *,
    all_evidence_refs: set[str],
    revoked_evidence_refs: set[str],
    source_epoch: str | None,
    current_epoch: str | None,
) -> EvidenceFreshnessStatus:
    if all_evidence_refs & revoked_evidence_refs:
        return EvidenceFreshnessStatus.REVOKED
    if source_epoch is None or current_epoch is None:
        return EvidenceFreshnessStatus.UNKNOWN
    if hmac.compare_digest(source_epoch, current_epoch):
        return EvidenceFreshnessStatus.CURRENT
    return EvidenceFreshnessStatus.STALE


def build_evidence_belief_snapshot(
    *,
    source_case_id: str,
    source_case_sha256: str,
    hypothesis: IncidentHypothesis,
    evidence_edges: Iterable[IncidentEvidenceEdge],
    evidence_bundle_sha256: str,
    source_freshness_epoch_sha256: str | None,
    current_freshness_epoch_sha256: str | None,
    revoked_evidence_refs: Iterable[str] = (),
) -> EvidenceBeliefSnapshot:
    """Derive one immutable snapshot without changing the incident case."""

    edges = sorted(
        list(evidence_edges),
        key=lambda item: (
            item.relation,
            item.evidence_ref,
            item.issue_code or "",
            item.edge_id,
        ),
    )
    foreign_edges = [
        item.edge_id for item in edges if item.hypothesis_id != hypothesis.hypothesis_id
    ]
    if foreign_edges:
        raise ValueError(
            "evidence belief snapshot received edge(s) for another hypothesis: "
            + ", ".join(foreign_edges)
        )

    supporting_refs = sorted(
        {item.evidence_ref for item in edges if item.relation == "SUPPORTS"}
    )
    contradicting_refs = sorted(
        {item.evidence_ref for item in edges if item.relation == "CONTRADICTS"}
    )
    unresolved_refs = {
        item.evidence_ref for item in edges if item.relation == "UNRESOLVED"
    }
    if hypothesis.status is not HypothesisStatus.REJECTED:
        unresolved_refs.update(hypothesis.unresolved_evidence_refs)
    normalized_unresolved_refs = sorted(unresolved_refs)
    all_refs = set(supporting_refs) | set(contradicting_refs) | unresolved_refs

    hypothesis_sha256 = _sha256(hypothesis.model_dump(mode="json"))
    edge_sha256s = sorted(_edge_sha256(item) for item in edges)
    derived_evidence_sha256 = _sha256(
        {
            "source_hypothesis_sha256": hypothesis_sha256,
            "source_edge_sha256s": edge_sha256s,
            "evidence_bundle_sha256": evidence_bundle_sha256,
        }
    )
    stable = {
        "source_case_id": source_case_id,
        "source_case_sha256": source_case_sha256,
        "hypothesis_id": hypothesis.hypothesis_id,
        "source_hypothesis_status": hypothesis.status.value,
        "support_status": _support_status(
            hypothesis,
            supporting_refs,
            contradicting_refs,
            normalized_unresolved_refs,
        ).value,
        "freshness_status": _freshness_status(
            all_evidence_refs=all_refs,
            revoked_evidence_refs=set(revoked_evidence_refs),
            source_epoch=source_freshness_epoch_sha256,
            current_epoch=current_freshness_epoch_sha256,
        ).value,
        "supporting_evidence_refs": supporting_refs,
        "contradicting_evidence_refs": contradicting_refs,
        "unresolved_evidence_refs": normalized_unresolved_refs,
        "unresolved_evidence_count": len(normalized_unresolved_refs),
        "evidence_bundle_sha256": evidence_bundle_sha256,
        "source_freshness_epoch_sha256": source_freshness_epoch_sha256,
        "current_freshness_epoch_sha256": current_freshness_epoch_sha256,
        "source_hypothesis_sha256": hypothesis_sha256,
        "source_edge_sha256s": edge_sha256s,
        "derived_evidence_sha256": derived_evidence_sha256,
    }
    draft = EvidenceBeliefSnapshot(**stable, snapshot_sha256="0" * 64)
    payload = draft.model_dump(mode="json", exclude={"snapshot_sha256"})
    return draft.model_copy(update={"snapshot_sha256": _sha256(payload)})


def verify_evidence_belief_snapshot(snapshot: EvidenceBeliefSnapshot) -> None:
    """Verify the snapshot's internal digest bindings."""

    payload = snapshot.model_dump(mode="json")
    stored_snapshot_sha256 = payload.pop("snapshot_sha256")
    if not hmac.compare_digest(stored_snapshot_sha256, _sha256(payload)):
        raise ValueError("evidence belief snapshot digest mismatch")
    expected_derived = _sha256(
        {
            "source_hypothesis_sha256": snapshot.source_hypothesis_sha256,
            "source_edge_sha256s": snapshot.source_edge_sha256s,
            "evidence_bundle_sha256": snapshot.evidence_bundle_sha256,
        }
    )
    if not hmac.compare_digest(snapshot.derived_evidence_sha256, expected_derived):
        raise ValueError("derived evidence digest mismatch")


def build_case_evidence_belief_ledger(
    case: IndustrialIncidentCase,
    *,
    current_freshness_epoch_sha256: str | None = None,
    revoked_evidence_refs: Iterable[str] = (),
) -> EvidenceBeliefLedger:
    """Derive a complete frozen ledger from an existing verified case."""

    evidence_bundle_sha256 = (
        case.evidence_bundle_sha256
        or industrial_incident_evidence_bundle_sha256(case.request)
    )
    source_epoch = case.gate_context.source_authorization_event_sha256
    current_epoch = current_freshness_epoch_sha256 or source_epoch
    revoked = tuple(sorted(set(revoked_evidence_refs)))
    edges_by_hypothesis: dict[str, list[IncidentEvidenceEdge]] = {}
    for edge in case.evidence_edges:
        edges_by_hypothesis.setdefault(edge.hypothesis_id, []).append(edge)
    snapshots = [
        build_evidence_belief_snapshot(
            source_case_id=case.case_id,
            source_case_sha256=case.case_sha256,
            hypothesis=hypothesis,
            evidence_edges=edges_by_hypothesis.get(hypothesis.hypothesis_id, []),
            evidence_bundle_sha256=evidence_bundle_sha256,
            source_freshness_epoch_sha256=source_epoch,
            current_freshness_epoch_sha256=current_epoch,
            revoked_evidence_refs=revoked,
        )
        for hypothesis in sorted(case.hypotheses, key=lambda item: item.hypothesis_id)
    ]
    stable = {
        "source_case_id": case.case_id,
        "source_case_sha256": case.case_sha256,
        "evidence_bundle_sha256": evidence_bundle_sha256,
        "snapshots": [item.model_dump(mode="json") for item in snapshots],
    }
    draft = EvidenceBeliefLedger(**stable, ledger_sha256="0" * 64)
    payload = draft.model_dump(mode="json", exclude={"ledger_sha256"})
    return draft.model_copy(update={"ledger_sha256": _sha256(payload)})


def verify_evidence_belief_ledger(ledger: EvidenceBeliefLedger) -> None:
    """Verify all snapshots and the aggregate ledger digest."""

    hypothesis_ids = [item.hypothesis_id for item in ledger.snapshots]
    if hypothesis_ids != sorted(set(hypothesis_ids)):
        raise ValueError("evidence belief ledger hypothesis order is invalid")
    for snapshot in ledger.snapshots:
        verify_evidence_belief_snapshot(snapshot)
        if snapshot.source_case_id != ledger.source_case_id:
            raise ValueError("evidence belief snapshot case ID mismatch")
        if not hmac.compare_digest(
            snapshot.source_case_sha256, ledger.source_case_sha256
        ):
            raise ValueError("evidence belief snapshot case digest mismatch")
        if not hmac.compare_digest(
            snapshot.evidence_bundle_sha256, ledger.evidence_bundle_sha256
        ):
            raise ValueError("evidence belief snapshot bundle digest mismatch")
    payload = ledger.model_dump(mode="json")
    stored = payload.pop("ledger_sha256")
    if not hmac.compare_digest(stored, _sha256(payload)):
        raise ValueError("evidence belief ledger digest mismatch")


__all__ = [
    "EvidenceBeliefLedger",
    "EvidenceBeliefLedgerV2",
    "EvidenceBeliefSnapshot",
    "EvidenceBeliefSnapshotV2",
    "EvidenceFreshnessStatus",
    "EvidenceFreshnessStatusV2",
    "EvidenceSupportStatus",
    "EvidenceSupportStatusV2",
    "SourceAuthorizationFreshnessFactsV2",
    "build_case_evidence_belief_ledger",
    "build_case_evidence_belief_ledger_v2",
    "build_evidence_belief_snapshot",
    "build_evidence_belief_snapshot_v2",
    "build_source_authorization_freshness_facts_v2",
    "verify_evidence_belief_ledger",
    "verify_evidence_belief_ledger_v2",
    "verify_evidence_belief_snapshot",
    "verify_evidence_belief_snapshot_v2",
    "verify_source_authorization_freshness_facts_v2",
]
