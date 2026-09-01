from __future__ import annotations

from pathlib import Path

import pytest

from visiondata_gate.evidence_state import (
    EvidenceFreshnessStatusV2,
    EvidenceFreshnessStatus,
    EvidenceSupportStatus,
    build_case_evidence_belief_ledger,
    build_case_evidence_belief_ledger_v2,
    build_evidence_belief_snapshot,
    build_source_authorization_freshness_facts_v2,
    verify_evidence_belief_ledger,
    verify_evidence_belief_ledger_v2,
    verify_evidence_belief_snapshot,
    verify_source_authorization_freshness_facts_v2,
)
from visiondata_gate.industrial_incident import (
    EvidenceQualification,
    HypothesisStatus,
    IncidentEvidenceEdge,
    IncidentHypothesis,
    parse_industrial_incident_case_json,
)


SHA256_ZERO = "0" * 64
SHA256_ONE = "1" * 64
CASE_ID = "incident_" + "a" * 20


def _hypothesis() -> IncidentHypothesis:
    return IncidentHypothesis(
        hypothesis_id="H-MIXED",
        category="process_deviation",
        statement="Competing evidence remains.",
        status=HypothesisStatus.PLAUSIBLE,
        supporting_issue_codes=["PROCESS_HIGH"],
        contradicting_issue_codes=["PROCESS_NORMAL"],
        unresolved_evidence_refs=["process-owner-attestation"],
        next_discriminating_test="Obtain an independent process-owner receipt.",
    )


def _edge(
    edge_id: str,
    relation: str,
    evidence_ref: str,
    issue_code: str,
) -> IncidentEvidenceEdge:
    return IncidentEvidenceEdge(
        edge_id="edge_" + edge_id * 16,
        hypothesis_id="H-MIXED",
        relation=relation,
        issue_code=issue_code,
        evidence_ref=evidence_ref,
        qualification=EvidenceQualification.QUALIFIED_WITH_WARNING,
        producer_receipt_sha256=SHA256_ONE,
    )


def test_snapshot_separates_support_from_freshness_and_is_order_stable() -> None:
    support = _edge("1", "SUPPORTS", "process-window", "PROCESS_HIGH")
    contradiction = _edge("2", "CONTRADICTS", "change-record", "PROCESS_NORMAL")
    common = {
        "source_case_id": CASE_ID,
        "source_case_sha256": SHA256_ZERO,
        "hypothesis": _hypothesis(),
        "evidence_bundle_sha256": SHA256_ONE,
        "source_freshness_epoch_sha256": SHA256_ZERO,
        "current_freshness_epoch_sha256": SHA256_ZERO,
    }

    first = build_evidence_belief_snapshot(
        **common, evidence_edges=[support, contradiction]
    )
    second = build_evidence_belief_snapshot(
        **common, evidence_edges=[contradiction, support]
    )

    assert first == second
    assert first.support_status is EvidenceSupportStatus.UNRESOLVED
    assert first.freshness_status is EvidenceFreshnessStatus.CURRENT
    assert first.unresolved_evidence_count == 1
    verify_evidence_belief_snapshot(first)


def test_snapshot_marks_stale_and_revoked_without_changing_support_status() -> None:
    support = _edge("1", "SUPPORTS", "process-window", "PROCESS_HIGH")
    common = {
        "source_case_id": CASE_ID,
        "source_case_sha256": SHA256_ZERO,
        "hypothesis": _hypothesis(),
        "evidence_edges": [support],
        "evidence_bundle_sha256": SHA256_ONE,
        "source_freshness_epoch_sha256": SHA256_ZERO,
        "current_freshness_epoch_sha256": SHA256_ONE,
    }

    stale = build_evidence_belief_snapshot(**common)
    revoked = build_evidence_belief_snapshot(
        **common, revoked_evidence_refs=["process-window"]
    )

    assert stale.support_status is EvidenceSupportStatus.SUPPORTED
    assert stale.freshness_status is EvidenceFreshnessStatus.STALE
    assert revoked.support_status is EvidenceSupportStatus.SUPPORTED
    assert revoked.freshness_status is EvidenceFreshnessStatus.REVOKED


def test_case_ledger_is_derived_from_legacy_case_without_schema_mutation() -> None:
    fixture = (
        Path(__file__).parent
        / "fixtures"
        / "runtime_workbench"
        / "legacy_cases"
        / "case_v3_transition_real_20260826.json"
    )
    case = parse_industrial_incident_case_json(fixture.read_text(encoding="utf-8"))

    first = build_case_evidence_belief_ledger(case)
    second = build_case_evidence_belief_ledger(case)

    assert first == second
    assert len(first.snapshots) == len(case.hypotheses)
    assert first.source_case_sha256 == case.case_sha256
    verify_evidence_belief_ledger(first)
    assert "belief" not in case.model_dump(mode="json")

    tampered = first.model_copy(update={"ledger_sha256": "f" * 64})
    with pytest.raises(ValueError, match="ledger digest mismatch"):
        verify_evidence_belief_ledger(tampered)


def test_v2_ledger_is_case_embeddable_without_final_case_digest() -> None:
    fixture = (
        Path(__file__).parent
        / "fixtures"
        / "runtime_workbench"
        / "legacy_cases"
        / "case_v3_transition_real_20260826.json"
    )
    case = parse_industrial_incident_case_json(fixture.read_text(encoding="utf-8"))
    assert case.evidence_bundle_sha256 is not None

    common = {
        "case_id": case.case_id,
        "evidence_bundle_sha256": case.evidence_bundle_sha256,
        "hypotheses": case.hypotheses,
        "evidence_edges": case.evidence_edges,
        "source_authorization_event_sha256": (
            case.gate_context.source_authorization_event_sha256
        ),
        "source_authorization_status": case.gate_context.source_authorization_status,
    }
    first = build_case_evidence_belief_ledger_v2(**common)
    second = build_case_evidence_belief_ledger_v2(**common)

    assert first == second
    assert first.case_id == case.case_id
    assert first.hypothesis_count == len(case.hypotheses)
    assert first.evidence_edge_count == len(case.evidence_edges)
    serialized = first.model_dump_json()
    assert "source_case_sha256" not in serialized
    assert case.case_sha256 not in serialized
    verify_evidence_belief_ledger_v2(first)

    tampered_snapshot = first.snapshots[0].model_copy(
        update={
            "unresolved_evidence_count": (
                first.snapshots[0].unresolved_evidence_count + 1
            )
        }
    )
    tampered = first.model_copy(
        update={"snapshots": [tampered_snapshot, *first.snapshots[1:]]}
    )
    with pytest.raises(ValueError, match="unresolved evidence count mismatch"):
        verify_evidence_belief_ledger_v2(tampered)


def test_v2_ledger_records_authorization_staleness_and_scoped_revocation() -> None:
    fixture = (
        Path(__file__).parent
        / "fixtures"
        / "runtime_workbench"
        / "legacy_cases"
        / "case_v3_transition_real_20260826.json"
    )
    case = parse_industrial_incident_case_json(fixture.read_text(encoding="utf-8"))
    assert case.evidence_bundle_sha256 is not None
    common = {
        "case_id": case.case_id,
        "evidence_bundle_sha256": case.evidence_bundle_sha256,
        "hypotheses": case.hypotheses,
        "evidence_edges": case.evidence_edges,
        "source_authorization_event_sha256": (
            case.gate_context.source_authorization_event_sha256
        ),
        "source_authorization_status": case.gate_context.source_authorization_status,
    }

    stale = build_case_evidence_belief_ledger_v2(
        **common,
        current_authorization_event_sha256="f" * 64,
    )
    assert stale.source_authorization_freshness.freshness_status is (
        EvidenceFreshnessStatusV2.STALE
    )
    assert {item.freshness_status for item in stale.snapshots} == {
        EvidenceFreshnessStatusV2.STALE
    }
    verify_evidence_belief_ledger_v2(stale)

    revoked_ref = case.evidence_edges[0].evidence_ref
    revoked_hypothesis_id = case.evidence_edges[0].hypothesis_id
    revoked = build_case_evidence_belief_ledger_v2(
        **common,
        revoked_evidence_refs=[revoked_ref],
    )
    affected = next(
        item
        for item in revoked.snapshots
        if item.hypothesis_id == revoked_hypothesis_id
    )
    assert affected.freshness_status is EvidenceFreshnessStatusV2.REVOKED
    verify_evidence_belief_ledger_v2(revoked)


def test_v2_not_applicable_authorization_is_unknown_not_current() -> None:
    facts = build_source_authorization_freshness_facts_v2(
        source_authorization_event_sha256=SHA256_ZERO,
        source_authorization_status="NOT_APPLICABLE",
    )

    assert facts.freshness_status is EvidenceFreshnessStatusV2.UNKNOWN
    verify_source_authorization_freshness_facts_v2(facts)
