"""Cycle-free contracts for evidence-belief state embedded in incident cases.

This module deliberately does not import :mod:`industrial_incident`.  The
incident builder can therefore construct and verify the v2 ledger before the
final case SHA-256 exists, then embed the ledger in the case's canonical
payload without creating a circular hash dependency.
"""

from __future__ import annotations

import hashlib
import hmac
from enum import Enum
from typing import Iterable, Literal, Protocol

import rfc8785
from pydantic import ConfigDict, Field

from .product_models import ProductModel


class EvidenceSupportStatusV2(str, Enum):
    SUPPORTED = "SUPPORTED"
    CONTRADICTED = "CONTRADICTED"
    UNRESOLVED = "UNRESOLVED"
    NOT_SUPPORTED = "NOT_SUPPORTED"


class EvidenceFreshnessStatusV2(str, Enum):
    CURRENT = "CURRENT"
    STALE = "STALE"
    REVOKED = "REVOKED"
    UNKNOWN = "UNKNOWN"


HypothesisStatusV2 = Literal["SUPPORTED", "PLAUSIBLE", "UNRESOLVED", "REJECTED"]
SourceAuthorizationStatusV2 = Literal[
    "ACTIVE", "REVOKED", "EXPIRED", "UNAVAILABLE", "NOT_APPLICABLE"
]


class _HypothesisLike(Protocol):
    hypothesis_id: str
    status: object
    unresolved_evidence_refs: list[str]

    def model_dump(self, *, mode: str) -> dict[str, object]: ...


class _EvidenceEdgeLike(Protocol):
    edge_id: str
    hypothesis_id: str
    relation: str
    evidence_ref: str
    issue_code: str | None

    def model_dump(self, *, mode: str) -> dict[str, object]: ...


class SourceAuthorizationFreshnessFactsV2(ProductModel):
    """Frozen authorization facts used to decide evidence freshness."""

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True, frozen=True)

    schema_version: Literal[
        "visiondata-gate.source-authorization-freshness-facts.v2"
    ] = "visiondata-gate.source-authorization-freshness-facts.v2"
    source_authorization_event_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    source_authorization_status: SourceAuthorizationStatusV2
    current_authorization_event_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    current_authorization_status: SourceAuthorizationStatusV2
    freshness_status: EvidenceFreshnessStatusV2
    revoked_evidence_refs: list[str] = Field(default_factory=list)
    facts_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")


class EvidenceBeliefSnapshotV2(ProductModel):
    """Complete support/freshness projection for one incident hypothesis."""

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True, frozen=True)

    schema_version: Literal["visiondata-gate.evidence-belief-snapshot.v2"] = (
        "visiondata-gate.evidence-belief-snapshot.v2"
    )
    case_id: str = Field(pattern=r"^incident_[0-9a-f]{20}$")
    hypothesis_id: str = Field(min_length=1)
    source_hypothesis_status: HypothesisStatusV2
    support_status: EvidenceSupportStatusV2
    freshness_status: EvidenceFreshnessStatusV2
    supporting_evidence_refs: list[str] = Field(default_factory=list)
    contradicting_evidence_refs: list[str] = Field(default_factory=list)
    unresolved_evidence_refs: list[str] = Field(default_factory=list)
    unresolved_evidence_count: int = Field(ge=0)
    evidence_bundle_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    source_authorization_freshness_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    source_hypothesis_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    source_edge_sha256s: list[str] = Field(default_factory=list)
    derived_evidence_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    snapshot_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")


class EvidenceBeliefLedgerV2(ProductModel):
    """Case-embeddable belief ledger with no dependency on final case SHA."""

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True, frozen=True)

    schema_version: Literal["visiondata-gate.evidence-belief-ledger.v2"] = (
        "visiondata-gate.evidence-belief-ledger.v2"
    )
    case_id: str = Field(pattern=r"^incident_[0-9a-f]{20}$")
    evidence_bundle_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    source_authorization_freshness: SourceAuthorizationFreshnessFactsV2
    hypothesis_count: int = Field(ge=1)
    evidence_edge_count: int = Field(ge=0)
    hypothesis_projection_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    evidence_edge_projection_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    snapshots: list[EvidenceBeliefSnapshotV2] = Field(min_length=1)
    ledger_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")


def _canonical_jcs_bytes(value: object) -> bytes:
    try:
        return rfc8785.dumps(value)
    except (rfc8785.CanonicalizationError, TypeError, UnicodeError) as error:
        raise ValueError(
            f"evidence belief v2 payload cannot be canonicalized: {error}"
        ) from error


def _digest(domain: str, value: object) -> str:
    framed = {"domain": domain, "payload": value}
    return hashlib.sha256(_canonical_jcs_bytes(framed)).hexdigest()


def _enum_text(value: object) -> str:
    enum_value = getattr(value, "value", value)
    if not isinstance(enum_value, str):
        raise ValueError("evidence belief enum value must be a string")
    return enum_value


def _support_status_v2(
    *,
    source_hypothesis_status: str,
    supporting_refs: list[str],
    contradicting_refs: list[str],
    unresolved_refs: list[str],
) -> EvidenceSupportStatusV2:
    if supporting_refs and contradicting_refs:
        return EvidenceSupportStatusV2.UNRESOLVED
    if supporting_refs:
        return EvidenceSupportStatusV2.SUPPORTED
    if contradicting_refs:
        return EvidenceSupportStatusV2.CONTRADICTED
    if unresolved_refs or source_hypothesis_status in {"PLAUSIBLE", "UNRESOLVED"}:
        return EvidenceSupportStatusV2.UNRESOLVED
    return EvidenceSupportStatusV2.NOT_SUPPORTED


def _authorization_freshness_status_v2(
    *,
    source_event_sha256: str,
    source_status: str,
    current_event_sha256: str,
    current_status: str,
) -> EvidenceFreshnessStatusV2:
    if source_status == "REVOKED" or current_status == "REVOKED":
        return EvidenceFreshnessStatusV2.REVOKED
    if source_status in {"UNAVAILABLE", "NOT_APPLICABLE"} or current_status in {
        "UNAVAILABLE",
        "NOT_APPLICABLE",
    }:
        return EvidenceFreshnessStatusV2.UNKNOWN
    if source_status == "EXPIRED" or current_status == "EXPIRED":
        return EvidenceFreshnessStatusV2.STALE
    if not hmac.compare_digest(source_event_sha256, current_event_sha256):
        return EvidenceFreshnessStatusV2.STALE
    if source_status == "ACTIVE" and current_status == "ACTIVE":
        return EvidenceFreshnessStatusV2.CURRENT
    return EvidenceFreshnessStatusV2.UNKNOWN


def build_source_authorization_freshness_facts_v2(
    *,
    source_authorization_event_sha256: str,
    source_authorization_status: SourceAuthorizationStatusV2,
    current_authorization_event_sha256: str | None = None,
    current_authorization_status: SourceAuthorizationStatusV2 | None = None,
    revoked_evidence_refs: Iterable[str] = (),
) -> SourceAuthorizationFreshnessFactsV2:
    """Freeze source/current authorization facts and their freshness verdict."""

    current_event = (
        current_authorization_event_sha256 or source_authorization_event_sha256
    )
    current_status = current_authorization_status or source_authorization_status
    stable = {
        "source_authorization_event_sha256": source_authorization_event_sha256,
        "source_authorization_status": source_authorization_status,
        "current_authorization_event_sha256": current_event,
        "current_authorization_status": current_status,
        "freshness_status": _authorization_freshness_status_v2(
            source_event_sha256=source_authorization_event_sha256,
            source_status=source_authorization_status,
            current_event_sha256=current_event,
            current_status=current_status,
        ).value,
        "revoked_evidence_refs": sorted(set(revoked_evidence_refs)),
    }
    draft = SourceAuthorizationFreshnessFactsV2(
        **stable,
        facts_sha256="0" * 64,
    )
    payload = draft.model_dump(mode="json", exclude={"facts_sha256"})
    return draft.model_copy(
        update={
            "facts_sha256": _digest(
                "VDG_SOURCE_AUTHORIZATION_FRESHNESS_FACTS_V2", payload
            )
        }
    )


def verify_source_authorization_freshness_facts_v2(
    facts: SourceAuthorizationFreshnessFactsV2,
) -> None:
    """Verify authorization ordering, semantics, and canonical digest."""

    if facts.revoked_evidence_refs != sorted(set(facts.revoked_evidence_refs)):
        raise ValueError("revoked evidence references must be sorted and unique")
    expected_status = _authorization_freshness_status_v2(
        source_event_sha256=facts.source_authorization_event_sha256,
        source_status=facts.source_authorization_status,
        current_event_sha256=facts.current_authorization_event_sha256,
        current_status=facts.current_authorization_status,
    )
    if facts.freshness_status is not expected_status:
        raise ValueError("source authorization freshness status mismatch")
    payload = facts.model_dump(mode="json", exclude={"facts_sha256"})
    expected_digest = _digest("VDG_SOURCE_AUTHORIZATION_FRESHNESS_FACTS_V2", payload)
    if not hmac.compare_digest(facts.facts_sha256, expected_digest):
        raise ValueError("source authorization freshness facts digest mismatch")


def build_evidence_belief_snapshot_v2(
    *,
    case_id: str,
    hypothesis: _HypothesisLike,
    evidence_edges: Iterable[_EvidenceEdgeLike],
    evidence_bundle_sha256: str,
    source_authorization_freshness: SourceAuthorizationFreshnessFactsV2,
) -> EvidenceBeliefSnapshotV2:
    """Build one case-embeddable snapshot from normalized incident objects."""

    verify_source_authorization_freshness_facts_v2(source_authorization_freshness)
    edges = sorted(
        list(evidence_edges),
        key=lambda item: (
            item.relation,
            item.evidence_ref,
            item.issue_code or "",
            item.edge_id,
        ),
    )
    edge_ids = [item.edge_id for item in edges]
    if len(edge_ids) != len(set(edge_ids)):
        raise ValueError("evidence belief v2 received duplicate edge IDs")
    foreign_edges = [
        item.edge_id for item in edges if item.hypothesis_id != hypothesis.hypothesis_id
    ]
    if foreign_edges:
        raise ValueError(
            "evidence belief v2 received edge(s) for another hypothesis: "
            + ", ".join(foreign_edges)
        )

    source_status = _enum_text(hypothesis.status)
    if source_status not in {"SUPPORTED", "PLAUSIBLE", "UNRESOLVED", "REJECTED"}:
        raise ValueError(f"unsupported hypothesis status: {source_status}")
    supporting_refs = sorted(
        {item.evidence_ref for item in edges if item.relation == "SUPPORTS"}
    )
    contradicting_refs = sorted(
        {item.evidence_ref for item in edges if item.relation == "CONTRADICTS"}
    )
    unresolved_refs = {
        item.evidence_ref for item in edges if item.relation == "UNRESOLVED"
    }
    if source_status != "REJECTED":
        unresolved_refs.update(hypothesis.unresolved_evidence_refs)
    normalized_unresolved_refs = sorted(unresolved_refs)
    all_refs = (
        set(supporting_refs) | set(contradicting_refs) | set(normalized_unresolved_refs)
    )

    freshness_status = source_authorization_freshness.freshness_status
    if all_refs & set(source_authorization_freshness.revoked_evidence_refs):
        freshness_status = EvidenceFreshnessStatusV2.REVOKED
    hypothesis_sha256 = _digest(
        "VDG_INCIDENT_HYPOTHESIS_V2", hypothesis.model_dump(mode="json")
    )
    edge_sha256s = sorted(
        _digest("VDG_INCIDENT_EVIDENCE_EDGE_V2", item.model_dump(mode="json"))
        for item in edges
    )
    derived_evidence_sha256 = _digest(
        "VDG_DERIVED_EVIDENCE_V2",
        {
            "case_id": case_id,
            "evidence_bundle_sha256": evidence_bundle_sha256,
            "source_authorization_freshness_sha256": (
                source_authorization_freshness.facts_sha256
            ),
            "source_hypothesis_sha256": hypothesis_sha256,
            "source_edge_sha256s": edge_sha256s,
        },
    )
    stable = {
        "case_id": case_id,
        "hypothesis_id": hypothesis.hypothesis_id,
        "source_hypothesis_status": source_status,
        "support_status": _support_status_v2(
            source_hypothesis_status=source_status,
            supporting_refs=supporting_refs,
            contradicting_refs=contradicting_refs,
            unresolved_refs=normalized_unresolved_refs,
        ).value,
        "freshness_status": freshness_status.value,
        "supporting_evidence_refs": supporting_refs,
        "contradicting_evidence_refs": contradicting_refs,
        "unresolved_evidence_refs": normalized_unresolved_refs,
        "unresolved_evidence_count": len(normalized_unresolved_refs),
        "evidence_bundle_sha256": evidence_bundle_sha256,
        "source_authorization_freshness_sha256": (
            source_authorization_freshness.facts_sha256
        ),
        "source_hypothesis_sha256": hypothesis_sha256,
        "source_edge_sha256s": edge_sha256s,
        "derived_evidence_sha256": derived_evidence_sha256,
    }
    draft = EvidenceBeliefSnapshotV2(**stable, snapshot_sha256="0" * 64)
    payload = draft.model_dump(mode="json", exclude={"snapshot_sha256"})
    return draft.model_copy(
        update={"snapshot_sha256": _digest("VDG_EVIDENCE_BELIEF_SNAPSHOT_V2", payload)}
    )


def verify_evidence_belief_snapshot_v2(
    snapshot: EvidenceBeliefSnapshotV2,
    *,
    source_authorization_freshness: SourceAuthorizationFreshnessFactsV2,
) -> None:
    """Verify one v2 snapshot without requiring the final case digest."""

    verify_source_authorization_freshness_facts_v2(source_authorization_freshness)
    if not hmac.compare_digest(
        snapshot.source_authorization_freshness_sha256,
        source_authorization_freshness.facts_sha256,
    ):
        raise ValueError("evidence belief v2 authorization facts digest mismatch")
    for refs in (
        snapshot.supporting_evidence_refs,
        snapshot.contradicting_evidence_refs,
        snapshot.unresolved_evidence_refs,
        snapshot.source_edge_sha256s,
    ):
        if refs != sorted(set(refs)):
            raise ValueError("evidence belief v2 references must be sorted and unique")
    if snapshot.unresolved_evidence_count != len(snapshot.unresolved_evidence_refs):
        raise ValueError("evidence belief v2 unresolved evidence count mismatch")
    expected_support = _support_status_v2(
        source_hypothesis_status=snapshot.source_hypothesis_status,
        supporting_refs=snapshot.supporting_evidence_refs,
        contradicting_refs=snapshot.contradicting_evidence_refs,
        unresolved_refs=snapshot.unresolved_evidence_refs,
    )
    if snapshot.support_status is not expected_support:
        raise ValueError("evidence belief v2 support status mismatch")
    all_refs = (
        set(snapshot.supporting_evidence_refs)
        | set(snapshot.contradicting_evidence_refs)
        | set(snapshot.unresolved_evidence_refs)
    )
    expected_freshness = source_authorization_freshness.freshness_status
    if all_refs & set(source_authorization_freshness.revoked_evidence_refs):
        expected_freshness = EvidenceFreshnessStatusV2.REVOKED
    if snapshot.freshness_status is not expected_freshness:
        raise ValueError("evidence belief v2 freshness status mismatch")
    expected_derived = _digest(
        "VDG_DERIVED_EVIDENCE_V2",
        {
            "case_id": snapshot.case_id,
            "evidence_bundle_sha256": snapshot.evidence_bundle_sha256,
            "source_authorization_freshness_sha256": (
                snapshot.source_authorization_freshness_sha256
            ),
            "source_hypothesis_sha256": snapshot.source_hypothesis_sha256,
            "source_edge_sha256s": snapshot.source_edge_sha256s,
        },
    )
    if not hmac.compare_digest(snapshot.derived_evidence_sha256, expected_derived):
        raise ValueError("evidence belief v2 derived evidence digest mismatch")
    payload = snapshot.model_dump(mode="json", exclude={"snapshot_sha256"})
    expected_snapshot = _digest("VDG_EVIDENCE_BELIEF_SNAPSHOT_V2", payload)
    if not hmac.compare_digest(snapshot.snapshot_sha256, expected_snapshot):
        raise ValueError("evidence belief v2 snapshot digest mismatch")


def build_case_evidence_belief_ledger_v2(
    *,
    case_id: str,
    evidence_bundle_sha256: str,
    hypotheses: Iterable[_HypothesisLike],
    evidence_edges: Iterable[_EvidenceEdgeLike],
    source_authorization_event_sha256: str,
    source_authorization_status: SourceAuthorizationStatusV2,
    current_authorization_event_sha256: str | None = None,
    current_authorization_status: SourceAuthorizationStatusV2 | None = None,
    revoked_evidence_refs: Iterable[str] = (),
) -> EvidenceBeliefLedgerV2:
    """Build a v2 ledger before the enclosing incident case is hashed."""

    normalized_hypotheses = sorted(
        list(hypotheses), key=lambda item: item.hypothesis_id
    )
    hypothesis_ids = [item.hypothesis_id for item in normalized_hypotheses]
    if not hypothesis_ids:
        raise ValueError("evidence belief v2 requires at least one hypothesis")
    if len(hypothesis_ids) != len(set(hypothesis_ids)):
        raise ValueError("evidence belief v2 received duplicate hypothesis IDs")
    normalized_edges = list(evidence_edges)
    edge_ids = [item.edge_id for item in normalized_edges]
    if len(edge_ids) != len(set(edge_ids)):
        raise ValueError("evidence belief v2 received duplicate edge IDs")
    known_hypotheses = set(hypothesis_ids)
    foreign_edges = sorted(
        item.edge_id
        for item in normalized_edges
        if item.hypothesis_id not in known_hypotheses
    )
    if foreign_edges:
        raise ValueError(
            "evidence belief v2 received edge(s) for unknown hypothesis: "
            + ", ".join(foreign_edges)
        )

    authorization_freshness = build_source_authorization_freshness_facts_v2(
        source_authorization_event_sha256=source_authorization_event_sha256,
        source_authorization_status=source_authorization_status,
        current_authorization_event_sha256=current_authorization_event_sha256,
        current_authorization_status=current_authorization_status,
        revoked_evidence_refs=revoked_evidence_refs,
    )
    edges_by_hypothesis: dict[str, list[_EvidenceEdgeLike]] = {}
    for edge in normalized_edges:
        edges_by_hypothesis.setdefault(edge.hypothesis_id, []).append(edge)
    snapshots = [
        build_evidence_belief_snapshot_v2(
            case_id=case_id,
            hypothesis=hypothesis,
            evidence_edges=edges_by_hypothesis.get(hypothesis.hypothesis_id, []),
            evidence_bundle_sha256=evidence_bundle_sha256,
            source_authorization_freshness=authorization_freshness,
        )
        for hypothesis in normalized_hypotheses
    ]
    hypothesis_sha256s = [item.source_hypothesis_sha256 for item in snapshots]
    edge_sha256s = sorted(
        edge_sha256
        for snapshot in snapshots
        for edge_sha256 in snapshot.source_edge_sha256s
    )
    stable = {
        "case_id": case_id,
        "evidence_bundle_sha256": evidence_bundle_sha256,
        "source_authorization_freshness": authorization_freshness,
        "hypothesis_count": len(snapshots),
        "evidence_edge_count": len(edge_sha256s),
        "hypothesis_projection_sha256": _digest(
            "VDG_HYPOTHESIS_PROJECTION_V2", hypothesis_sha256s
        ),
        "evidence_edge_projection_sha256": _digest(
            "VDG_EVIDENCE_EDGE_PROJECTION_V2", edge_sha256s
        ),
        "snapshots": snapshots,
    }
    draft = EvidenceBeliefLedgerV2(**stable, ledger_sha256="0" * 64)
    payload = draft.model_dump(mode="json", exclude={"ledger_sha256"})
    return draft.model_copy(
        update={"ledger_sha256": _digest("VDG_EVIDENCE_BELIEF_LEDGER_V2", payload)}
    )


def verify_evidence_belief_ledger_v2(ledger: EvidenceBeliefLedgerV2) -> None:
    """Verify the complete embedded v2 ledger and all aggregate projections."""

    verify_source_authorization_freshness_facts_v2(
        ledger.source_authorization_freshness
    )
    hypothesis_ids = [item.hypothesis_id for item in ledger.snapshots]
    if hypothesis_ids != sorted(set(hypothesis_ids)):
        raise ValueError("evidence belief v2 hypothesis order is invalid")
    if ledger.hypothesis_count != len(ledger.snapshots):
        raise ValueError("evidence belief v2 hypothesis count mismatch")
    for snapshot in ledger.snapshots:
        verify_evidence_belief_snapshot_v2(
            snapshot,
            source_authorization_freshness=ledger.source_authorization_freshness,
        )
        if snapshot.case_id != ledger.case_id:
            raise ValueError("evidence belief v2 snapshot case ID mismatch")
        if not hmac.compare_digest(
            snapshot.evidence_bundle_sha256, ledger.evidence_bundle_sha256
        ):
            raise ValueError("evidence belief v2 snapshot bundle digest mismatch")

    hypothesis_sha256s = [item.source_hypothesis_sha256 for item in ledger.snapshots]
    expected_hypothesis_projection = _digest(
        "VDG_HYPOTHESIS_PROJECTION_V2", hypothesis_sha256s
    )
    if not hmac.compare_digest(
        ledger.hypothesis_projection_sha256, expected_hypothesis_projection
    ):
        raise ValueError("evidence belief v2 hypothesis projection digest mismatch")
    edge_sha256s = sorted(
        edge_sha256
        for snapshot in ledger.snapshots
        for edge_sha256 in snapshot.source_edge_sha256s
    )
    if ledger.evidence_edge_count != len(edge_sha256s):
        raise ValueError("evidence belief v2 edge count mismatch")
    expected_edge_projection = _digest("VDG_EVIDENCE_EDGE_PROJECTION_V2", edge_sha256s)
    if not hmac.compare_digest(
        ledger.evidence_edge_projection_sha256, expected_edge_projection
    ):
        raise ValueError("evidence belief v2 edge projection digest mismatch")
    payload = ledger.model_dump(mode="json", exclude={"ledger_sha256"})
    expected_ledger = _digest("VDG_EVIDENCE_BELIEF_LEDGER_V2", payload)
    if not hmac.compare_digest(ledger.ledger_sha256, expected_ledger):
        raise ValueError("evidence belief v2 ledger digest mismatch")


__all__ = [
    "EvidenceBeliefLedgerV2",
    "EvidenceBeliefSnapshotV2",
    "EvidenceFreshnessStatusV2",
    "EvidenceSupportStatusV2",
    "SourceAuthorizationFreshnessFactsV2",
    "build_case_evidence_belief_ledger_v2",
    "build_evidence_belief_snapshot_v2",
    "build_source_authorization_freshness_facts_v2",
    "verify_evidence_belief_ledger_v2",
    "verify_evidence_belief_snapshot_v2",
    "verify_source_authorization_freshness_facts_v2",
]
