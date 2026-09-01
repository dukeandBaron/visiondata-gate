"""Replayable governance-boundary contract matrix for industrial memory.

This artifact is an author-constructed contract stress test.  It does not
measure embedding quality, vector-database quality, independent human
relevance, or real-factory effectiveness.  Both paths receive the same ordered
cards and the same query.  The baseline ranks every candidate lexically; the
governed path verifies each card's SHA-256-sealed content integrity/approved
status and applies
scope, revocation, and processing-time gates before running the frozen hybrid
sparse ranker.  It does not execute the ProductService strict promotion and
command-admission chain, and it does not configure semantic retrieval.
"""

from __future__ import annotations

import hashlib
import hmac
import re
from datetime import UTC, datetime, timedelta
from typing import Literal, Mapping, Sequence

from .evidence import canonical_json_bytes
from .governed_context import (
    ApprovedMemoryCard,
    ApprovedMemoryContent,
    ClockedMemoryQueryV3,
    HybridMemoryRetrievalReceiptV3,
    MemoryProcessingTimeSource,
    MemoryScope,
    build_approved_memory_card,
    parse_memory_retrieval_receipt,
    retrieve_approved_memories_v3,
    verify_approved_memory_card,
    verify_memory_retrieval_receipt,
)


_EVENT_TIME = datetime(2026, 8, 10, tzinfo=UTC)
_PROCESSING_TIME = datetime(2026, 8, 29, tzinfo=UTC)
_MATRIX_HASH_DOMAIN = "visiondata-gate/governance-boundary-contract-matrix/v2"
_CANDIDATE_HASH_DOMAIN = (
    "visiondata-gate/governance-boundary-contract-matrix/candidates/v2"
)
_PROTOCOL_HASH_DOMAIN = (
    "visiondata-gate/governance-boundary-contract-matrix/protocol/v2"
)
_TRUTH_PROVENANCE = "AUTHOR_CONSTRUCTED_DETERMINISTIC_PROTOCOL_V2"
_BOUNDARY_REASONS: tuple[str, ...] = (
    *(("CROSS_SITE_SCOPE",) * 3),
    *(("PRODUCT_SCOPE_MISMATCH",) * 3),
    *(("LINE_SCOPE_MISMATCH",) * 3),
    *(("STATION_SCOPE_MISMATCH",) * 3),
    *(("CAMERA_SCOPE_MISMATCH",) * 2),
    *(("NOT_YET_VALID",) * 2),
    *(("EXPIRED",) * 2),
    *(("REVOKED",) * 2),
)


def _domain_sha256(domain: str, value: object) -> str:
    return hashlib.sha256(
        domain.encode("utf-8")
        + b"\x00"
        + canonical_json_bytes(value, trailing_newline=False)
    ).hexdigest()


def _tokens(value: str) -> set[str]:
    return set(re.findall(r"[a-z0-9_.-]+", value.casefold()))


def _card_text(card: ApprovedMemoryCard) -> str:
    return " ".join(
        [
            card.memory_type,
            card.content.pattern,
            card.content.recommended_first_check,
            card.content.avoid_first_action or "",
            card.content.advisory_summary,
        ]
    )


def _ungoverned_lexical_evidence(
    cards: Sequence[ApprovedMemoryCard],
    query: ClockedMemoryQueryV3,
) -> dict[str, object]:
    """Return complete ranking evidence without governance hard gates."""

    query_tokens = _tokens(" ".join(query.terms))
    ranked = [(len(query_tokens & _tokens(_card_text(card))), card) for card in cards]
    ranked = [item for item in ranked if item[0] > 0]
    ranked.sort(
        key=lambda item: (-item[0], -item[1].memory_version, item[1].memory_sha256)
    )
    return {
        "schema_version": "visiondata-gate.ungoverned-lexical-evidence.v1",
        "algorithm": "UNGOVERNED_LEXICAL_TOP1_PROXY",
        "candidate_count": len(cards),
        "query_token_sha256": _domain_sha256(
            _PROTOCOL_HASH_DOMAIN,
            sorted(query_tokens),
        ),
        "ranked": [
            {
                "rank": rank,
                "memory_id": card.memory_id,
                "memory_sha256": card.memory_sha256,
                "overlap_score": score,
                "memory_version": card.memory_version,
            }
            for rank, (score, card) in enumerate(ranked, start=1)
        ],
        "selected_memory_id": ranked[0][1].memory_id if ranked else None,
    }


def _memory(
    *,
    case_number: int,
    pattern: str,
    scope: MemoryScope,
    valid_from: datetime = _EVENT_TIME - timedelta(days=30),
    valid_until: datetime | None = None,
    status: Literal["APPROVED", "REVOKED"] = "APPROVED",
) -> ApprovedMemoryCard:
    return build_approved_memory_card(
        memory_type="INVESTIGATION_HINT",
        scope=scope,
        content=ApprovedMemoryContent(
            pattern=pattern,
            recommended_first_check="compare current exposure reference",
            avoid_first_action="reuse history as a current measurement",
            advisory_summary="Historical exposure evidence is advisory only.",
        ),
        source_case_ids=[f"incident_{case_number:020x}"],
        approval_sha256=hashlib.sha256(
            f"approved-memory-{case_number}".encode("utf-8")
        ).hexdigest(),
        valid_from=valid_from,
        valid_until=valid_until,
        status=status,
    )


def _expected_scope() -> MemoryScope:
    return MemoryScope(
        site_id="factory-a-line-01",
        product_family="metal-part",
        line_id="LINE-03",
        station_id="STATION-AOI-02",
        camera_id="CAM-02",
    )


def _processing_time_source() -> MemoryProcessingTimeSource:
    return MemoryProcessingTimeSource(
        source_kind="EXPLICIT_CALLER_BINDING",
        source_id="governance-boundary-contract-matrix-v2",
        source_sha256=hashlib.sha256(
            b"governance-boundary-contract-matrix-v2"
        ).hexdigest(),
    )


def _boundary_card(
    *,
    case_number: int,
    reason: str,
    pattern: str,
) -> ApprovedMemoryCard:
    scope_payload = _expected_scope().model_dump()
    valid_from = _EVENT_TIME - timedelta(days=30)
    valid_until = None
    status: Literal["APPROVED", "REVOKED"] = "APPROVED"
    if reason == "CROSS_SITE_SCOPE":
        scope_payload["site_id"] = "factory-b-cell-07"
    elif reason == "PRODUCT_SCOPE_MISMATCH":
        scope_payload["product_family"] = "polymer-cap"
    elif reason == "LINE_SCOPE_MISMATCH":
        scope_payload["line_id"] = "LINE-09"
    elif reason == "STATION_SCOPE_MISMATCH":
        scope_payload["station_id"] = "STATION-AOI-09"
    elif reason == "CAMERA_SCOPE_MISMATCH":
        scope_payload["camera_id"] = "CAM-09"
    elif reason == "NOT_YET_VALID":
        valid_from = _PROCESSING_TIME + timedelta(days=1)
    elif reason == "EXPIRED":
        valid_until = _PROCESSING_TIME - timedelta(days=1)
    elif reason == "REVOKED":
        status = "REVOKED"
    else:  # pragma: no cover - frozen protocol
        raise ValueError(f"unsupported boundary reason: {reason}")
    return _memory(
        case_number=case_number,
        pattern=pattern,
        scope=MemoryScope(**scope_payload),
        valid_from=valid_from,
        valid_until=valid_until,
        status=status,
    )


def _episode_inputs(
    index: int,
) -> tuple[ClockedMemoryQueryV3, list[ApprovedMemoryCard], dict[str, object]]:
    if index < 1 or index > 40:
        raise ValueError("contract-matrix episode index is outside 1..40")
    expected_scope = _expected_scope()
    case_token = f"case{index:02d}"
    detail_token = f"hotspot{index:02d}"
    query = ClockedMemoryQueryV3(
        site_id=expected_scope.site_id,
        current_case_sha256=hashlib.sha256(
            f"memory-contract-query-{index}".encode("utf-8")
        ).hexdigest(),
        event_time=_EVENT_TIME,
        processing_time=_PROCESSING_TIME,
        processing_time_source=_processing_time_source(),
        product_family=expected_scope.product_family,
        line_id=expected_scope.line_id,
        station_id=expected_scope.station_id,
        camera_id=expected_scope.camera_id,
        terms=["exposure drift reference", case_token, detail_token],
        limit=1,
    )
    eligible = _memory(
        case_number=index,
        pattern=f"exposure drift reference {case_token}",
        scope=expected_scope,
    )
    expected_rejection: str | None = None
    forbidden_id: str | None = None
    if index > 20:
        expected_rejection = _BOUNDARY_REASONS[index - 21]
        distractor = _boundary_card(
            case_number=100 + index,
            reason=expected_rejection,
            pattern=f"exposure drift reference {case_token} {detail_token}",
        )
        forbidden_id = distractor.memory_id
    else:
        distractor = _memory(
            case_number=100 + index,
            pattern=f"packaging barcode typography unrelated{index:02d}",
            scope=expected_scope,
        )
    truth = {
        "provenance": _TRUTH_PROVENANCE,
        "construction_rule": "ELIGIBLE_CARD_IS_EXPECTED;BOUNDARY_CARD_IS_FORBIDDEN",
        "expected_memory_id": eligible.memory_id,
        "forbidden_memory_id": forbidden_id,
        "expected_rejection_reason": expected_rejection,
        "independent_human_relevance_adjudication": False,
    }
    return query, [eligible, distractor], truth


def _episode(index: int) -> dict[str, object]:
    query, cards, truth = _episode_inputs(index)
    baseline = _ungoverned_lexical_evidence(cards, query)
    governed_cards, receipt = retrieve_approved_memories_v3(cards, query)
    verify_memory_retrieval_receipt(receipt)
    governed_selected = governed_cards[0].memory_id if governed_cards else None
    expected = truth["expected_memory_id"]
    forbidden = truth["forbidden_memory_id"]
    expected_rejection = truth["expected_rejection_reason"]
    rejection = {item.memory_id: item.reason_code for item in receipt.rejected}.get(
        forbidden or ""
    )
    baseline_selected = baseline["selected_memory_id"]
    return {
        "schema_version": "visiondata-gate.governance-boundary-episode.v2",
        "episode_id": f"governance-boundary-{index:02d}",
        "challenge_kind": expected_rejection or "CLEAN_RELEVANCE",
        "query": query.model_dump(mode="json"),
        "ordered_candidate_cards": [card.model_dump(mode="json") for card in cards],
        "candidate_cards_sha256": _domain_sha256(
            _CANDIDATE_HASH_DOMAIN,
            [card.model_dump(mode="json") for card in cards],
        ),
        "truth": truth,
        "baseline_evidence": baseline,
        "governed_receipt": receipt.model_dump(mode="json"),
        "outcome": {
            "baseline_selected_memory_id": baseline_selected,
            "governed_selected_memory_id": governed_selected,
            "governed_rejection_reason": rejection,
            "baseline_correct": baseline_selected == expected,
            "governed_correct": governed_selected == expected,
            "baseline_unsafe_selection": (
                forbidden is not None and baseline_selected == forbidden
            ),
            "governed_unsafe_selection": (
                forbidden is not None and governed_selected == forbidden
            ),
            "rejection_reason_correct": (
                expected_rejection is None or rejection == expected_rejection
            ),
        },
    }


def _protocol_definition() -> dict[str, object]:
    return {
        "version": "GOVERNANCE_BOUNDARY_CONTRACT_MATRIX_V2",
        "episode_count": 40,
        "clean_episode_count": 20,
        "boundary_reasons": list(_BOUNDARY_REASONS),
        "event_time": _EVENT_TIME.isoformat(),
        "processing_time": _PROCESSING_TIME.isoformat(),
        "processing_time_source": _processing_time_source().model_dump(mode="json"),
        "truth_provenance": _TRUTH_PROVENANCE,
        "baseline_algorithm": "UNGOVERNED_LEXICAL_TOP1_PROXY",
        "governed_algorithm": "GOVERNED_HYBRID_SPARSE_RRF_V3_RECEIPT",
        "composition_boundary": ("RETRIEVAL_CONTRACT_ONLY_NOT_PRODUCT_ADMISSION_CHAIN"),
    }


def _matrix_stable() -> dict[str, object]:
    episodes = [_episode(index) for index in range(1, 41)]
    outcomes = [item["outcome"] for item in episodes]
    baseline_correct = sum(bool(item["baseline_correct"]) for item in outcomes)
    governed_correct = sum(bool(item["governed_correct"]) for item in outcomes)
    baseline_unsafe = sum(bool(item["baseline_unsafe_selection"]) for item in outcomes)
    governed_unsafe = sum(bool(item["governed_unsafe_selection"]) for item in outcomes)
    correct_rejections = sum(
        bool(item["rejection_reason_correct"])
        for episode, item in zip(episodes, outcomes, strict=True)
        if episode["challenge_kind"] != "CLEAN_RELEVANCE"
    )
    denominator = len(episodes)
    protocol = _protocol_definition()
    return {
        "schema_version": ("visiondata-gate.governance-boundary-contract-matrix.v2"),
        "artifact_name": "Governance Boundary Contract Matrix",
        "protocol_scope": "AUTHOR_CURATED_GOVERNANCE_BOUNDARY_STRESS_TEST",
        "protocol_definition": protocol,
        "protocol_definition_sha256": _domain_sha256(
            _PROTOCOL_HASH_DOMAIN,
            protocol,
        ),
        "hash_domain": _MATRIX_HASH_DOMAIN,
        "denominator": denominator,
        "clean_episode_count": 20,
        "boundary_conflict_episode_count": 20,
        "same_candidate_and_query_protocol": True,
        "composition_boundary": ("RETRIEVAL_CONTRACT_ONLY_NOT_PRODUCT_ADMISSION_CHAIN"),
        "card_integrity_and_governance_gates_evaluated": True,
        "strict_memory_admission_chain_evaluated": False,
        "command_admission_clock_binding_evaluated": False,
        "baseline": {
            "name": "UNGOVERNED_LEXICAL_TOP1_PROXY",
            "correct_top1_count": baseline_correct,
            "correct_top1_rate": baseline_correct / denominator,
            "unsafe_selection_count": baseline_unsafe,
            "unsafe_selection_rate": baseline_unsafe / denominator,
        },
        "governed": {
            "name": "GOVERNED_HYBRID_SPARSE_RRF_V3_RECEIPT",
            "correct_top1_count": governed_correct,
            "correct_top1_rate": governed_correct / denominator,
            "unsafe_selection_count": governed_unsafe,
            "unsafe_selection_rate": governed_unsafe / denominator,
            "boundary_rejection_denominator": 20,
            "correct_boundary_rejection_count": correct_rejections,
        },
        "episodes": episodes,
        "verifier_replays_baseline": True,
        "verifier_replays_governed": True,
        "semantic_model_evaluated": False,
        "vector_database_evaluated": False,
        "real_factory_effectiveness_evaluated": False,
        "independent_human_relevance_adjudication": False,
        "claim_boundary": (
            "Measures deterministic governance-boundary enforcement on an "
            "author-constructed contract matrix. It is not a vector-model quality "
            "comparison, real-factory effectiveness measurement, or independent "
            "human relevance evaluation."
        ),
    }


def run_memory_governance_benchmark() -> dict[str, object]:
    """Build, seal, and independently replay the 40-episode contract matrix."""

    stable = _matrix_stable()
    result = stable | {"matrix_sha256": _domain_sha256(_MATRIX_HASH_DOMAIN, stable)}
    verify_memory_governance_benchmark(result)
    return result


def verify_memory_governance_benchmark(result: Mapping[str, object]) -> None:
    """Verify the seal, parse embedded evidence, and replay both paths."""

    payload = dict(result)
    stored_sha256 = payload.pop("matrix_sha256", None)
    if not isinstance(stored_sha256, str) or not re.fullmatch(
        r"[0-9a-f]{64}", stored_sha256
    ):
        raise ValueError("governance boundary matrix seal is missing or invalid")
    expected_sha256 = _domain_sha256(_MATRIX_HASH_DOMAIN, payload)
    if not hmac.compare_digest(stored_sha256, expected_sha256):
        raise ValueError("governance boundary matrix failed SHA-256 validation")

    episodes = payload.get("episodes")
    if not isinstance(episodes, list) or len(episodes) != 40:
        raise ValueError("governance boundary matrix episode denominator drifted")
    for row in episodes:
        if not isinstance(row, dict):
            raise ValueError("governance boundary matrix episode is malformed")
        cards_payload = row.get("ordered_candidate_cards")
        if not isinstance(cards_payload, list):
            raise ValueError("governance boundary episode lost candidate cards")
        cards = [ApprovedMemoryCard.model_validate(item) for item in cards_payload]
        for card in cards:
            verify_approved_memory_card(card)
        query = ClockedMemoryQueryV3.model_validate(row.get("query"))
        receipt = parse_memory_retrieval_receipt(row.get("governed_receipt"))
        if not isinstance(receipt, HybridMemoryRetrievalReceiptV3):
            raise ValueError(
                "governance boundary episode did not preserve a v3 receipt"
            )
        verify_memory_retrieval_receipt(receipt)
        if receipt.memory_admission_status != "DIRECT_CALL_NOT_ADMISSION_VERIFIED":
            raise ValueError(
                "governance boundary matrix exceeded its memory-admission scope"
            )
        if receipt.processing_time_source.source_kind != "EXPLICIT_CALLER_BINDING":
            raise ValueError(
                "governance boundary matrix exceeded its clock-binding scope"
            )
        if receipt.semantic_status != "NOT_CONFIGURED":
            raise ValueError(
                "governance boundary matrix exceeded its sparse-retrieval scope"
            )
        if receipt.current_case_sha256 != query.current_case_sha256:
            raise ValueError("governance boundary episode lost query-receipt binding")

    replayed = _matrix_stable()
    if payload != replayed:
        raise ValueError(
            "governance boundary matrix differs from deterministic two-path replay"
        )


__all__ = [
    "run_memory_governance_benchmark",
    "verify_memory_governance_benchmark",
]
