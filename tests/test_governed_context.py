from __future__ import annotations

import hashlib
from datetime import UTC, datetime
from pathlib import Path
from typing import Sequence

import pytest

from visiondata_gate.demo_fixtures import build_fixture_industrial_incident_request
from visiondata_gate.evidence import canonical_json_bytes
from visiondata_gate.governed_context import (
    ApprovedMemoryContent,
    EmbeddingIdentity,
    HybridMemoryRetrievalReceiptV3,
    HybridMemoryRetrievalReceiptV2,
    LegacyHybridMemoryQueryV2,
    MemoryProcessingTimeSource,
    MemoryQuery,
    MemoryScope,
    assemble_incident_context,
    build_approved_memory_card,
    build_governed_memory_planning_input,
    build_hybrid_retrieval_profile_v2,
    governed_memory_planner_payload,
    load_approved_memory_store,
    retrieve_approved_memories,
    retrieve_approved_memories_v2,
    verify_assembled_incident_context,
    verify_governed_memory_planning_input,
    verify_memory_retrieval_receipt,
)
from visiondata_gate.industrial_incident import (
    build_industrial_incident_case,
    industrial_incident_planning_subject_sha256,
)
from visiondata_gate.industrial_incident_benchmark import _gate_context
from visiondata_gate.site_pack import load_factory_site_pack

SITE_PACK_ROOT = Path(__file__).parents[1] / "examples" / "site_packs"
NOW = datetime(2026, 8, 26, 8, 0, tzinfo=UTC)


def _sha256(value: object) -> str:
    return hashlib.sha256(canonical_json_bytes(value)).hexdigest()


def _processing_time_source(label: str = "governed-context-test"):
    return MemoryProcessingTimeSource(
        source_kind="EXPLICIT_CALLER_BINDING",
        source_id=label,
        source_sha256=_sha256(label),
    )


def _card(
    *,
    site_id: str,
    pattern: str,
    recommended: str,
    valid_from: datetime = datetime(2026, 8, 1, tzinfo=UTC),
    valid_until: datetime | None = None,
    status: str = "APPROVED",
    product_family: str | None = "metal-part",
    line_id: str | None = None,
    station_id: str | None = None,
    camera_id: str | None = "CAM-02",
):
    return build_approved_memory_card(
        memory_type="INVESTIGATION_HINT",
        scope=MemoryScope(
            site_id=site_id,
            product_family=product_family,
            line_id=line_id,
            station_id=station_id,
            camera_id=camera_id,
        ),
        content=ApprovedMemoryContent(
            pattern=pattern,
            recommended_first_check=recommended,
            avoid_first_action="process_context_investigation",
            advisory_summary=(
                "历史案件仅提示调查顺序；当前案件必须重新取得正常参考证据。"
            ),
        ),
        source_case_ids=["incident_0123456789abcdefabcd"],
        approval_sha256=_sha256([site_id, pattern, "named-owner-approval"]),
        valid_from=valid_from,
        valid_until=valid_until,
        status=status,
    )


def test_memory_retrieval_rejects_cross_site_stale_and_revoked_cards() -> None:
    active = _card(
        site_id="factory-a-line-01",
        pattern="固定图像坐标出现高亮区域",
        recommended="retrieve_normal_reference",
    )
    cross_site = _card(
        site_id="factory-b-cell-07",
        pattern="固定图像坐标出现高亮区域",
        recommended="retrieve_normal_reference",
    )
    expired = _card(
        site_id="factory-a-line-01",
        pattern="历史过期高亮经验",
        recommended="retrieve_old_reference",
        valid_until=datetime(2026, 8, 20, tzinfo=UTC),
    )
    revoked = _card(
        site_id="factory-a-line-01",
        pattern="已撤销高亮经验",
        recommended="do_not_use",
        status="REVOKED",
    )
    query = MemoryQuery(
        site_id="factory-a-line-01",
        current_case_sha256=_sha256("current-case"),
        as_of=NOW,
        product_family="metal-part",
        camera_id="CAM-02",
        terms=["固定坐标", "高亮", "正常参考"],
    )

    selected, receipt = retrieve_approved_memories(
        [active, cross_site, expired, revoked],
        query,
    )

    assert [item.memory_id for item in selected] == [active.memory_id]
    reasons = {item.memory_id: item.reason_code for item in receipt.rejected}
    assert reasons[cross_site.memory_id] == "CROSS_SITE_SCOPE"
    assert reasons[expired.memory_id] == "EXPIRED"
    assert reasons[revoked.memory_id] == "REVOKED"
    assert receipt.cross_site_memory_selected_count == 0
    assert receipt.stale_memory_selected_count == 0
    assert receipt.historical_memory_used_as_fact_count == 0


def test_retrieval_receipt_accounts_for_site_line_station_camera_and_status() -> None:
    shared = {
        "site_id": "factory-a-line-01",
        "product_family": "metal-part",
        "line_id": "LINE-03",
        "station_id": "STATION-AOI-02",
        "camera_id": "CAM-02",
    }
    active = _card(
        **shared,
        pattern="fixed-coordinate highlight on the inspected part",
        recommended="retrieve_current_normal_reference",
    )
    cross_site = _card(
        **(shared | {"site_id": "factory-b-cell-07"}),
        pattern="fixed-coordinate highlight from another site",
        recommended="retrieve_current_normal_reference",
    )
    cross_line = _card(
        **(shared | {"line_id": "LINE-01"}),
        pattern="fixed-coordinate highlight from another line",
        recommended="retrieve_current_normal_reference",
    )
    cross_station = _card(
        **(shared | {"station_id": "STATION-AOI-09"}),
        pattern="fixed-coordinate highlight from another station",
        recommended="retrieve_current_normal_reference",
    )
    cross_camera = _card(
        **(shared | {"camera_id": "CAM-09"}),
        pattern="fixed-coordinate highlight from another camera",
        recommended="retrieve_current_normal_reference",
    )
    expired = _card(
        **shared,
        pattern="fixed-coordinate highlight in expired history",
        recommended="retrieve_old_reference",
        valid_until=datetime(2026, 8, 20, tzinfo=UTC),
    )
    revoked = _card(
        **shared,
        pattern="fixed-coordinate highlight in revoked history",
        recommended="do_not_use",
        status="REVOKED",
    )
    query = LegacyHybridMemoryQueryV2(
        **shared,
        current_case_sha256=_sha256("scope-bound-current-case"),
        as_of=NOW,
        terms=["fixed-coordinate", "highlight"],
    )

    selected, receipt = retrieve_approved_memories_v2(
        [
            active,
            cross_site,
            cross_line,
            cross_station,
            cross_camera,
            expired,
            revoked,
        ],
        query,
    )
    verify_memory_retrieval_receipt(receipt)

    assert [item.memory_id for item in selected] == [active.memory_id]
    assert receipt.query_scope == MemoryScope(**shared)
    assert receipt.candidate_count == 7
    assert receipt.selected_count == 1
    assert receipt.rejected_count == 6
    accepted = receipt.selected[0]
    assert accepted.accepted == "historical_reference_only"
    assert accepted.historical_reference_only is True
    assert accepted.may_set_current_case_fact is False
    assert receipt.accepted_usage == "historical_reference_only"
    assert receipt.may_set_current_case_fact is False
    reasons = {item.memory_id: item.reason_code for item in receipt.rejected}
    assert reasons == {
        cross_site.memory_id: "CROSS_SITE_SCOPE",
        cross_line.memory_id: "LINE_SCOPE_MISMATCH",
        cross_station.memory_id: "STATION_SCOPE_MISMATCH",
        cross_camera.memory_id: "CAMERA_SCOPE_MISMATCH",
        expired.memory_id: "EXPIRED",
        revoked.memory_id: "REVOKED",
    }


def test_retrieval_receipt_rejects_eligible_overflow_with_an_explicit_reason() -> None:
    cards = [
        _card(
            site_id="factory-a-line-01",
            pattern=f"fixed-coordinate highlight candidate {index}",
            recommended="retrieve_current_normal_reference",
        )
        for index in range(2)
    ]
    query = LegacyHybridMemoryQueryV2(
        site_id="factory-a-line-01",
        current_case_sha256=_sha256("rank-limited-current-case"),
        as_of=NOW,
        product_family="metal-part",
        camera_id="CAM-02",
        terms=["fixed-coordinate", "highlight"],
        limit=1,
    )

    _selected, receipt = retrieve_approved_memories_v2(cards, query)
    verify_memory_retrieval_receipt(receipt)

    assert receipt.candidate_count == 2
    assert receipt.selected_count == 1
    assert receipt.rejected_count == 1
    assert receipt.rejected[0].reason_code == "RANK_LIMIT_EXCEEDED"


def test_context_assembly_keeps_history_below_current_case_evidence() -> None:
    case = build_industrial_incident_case(
        build_fixture_industrial_incident_request(),
        _gate_context(),
    )
    pack = load_factory_site_pack(SITE_PACK_ROOT / "factory_a_line_01")
    card = _card(
        site_id=pack.manifest.site_id,
        pattern="固定图像坐标出现高亮区域",
        recommended="retrieve_normal_reference",
        line_id=case.request.trigger.line_id,
    )

    assembled = assemble_incident_context(
        case=case,
        site_pack=pack,
        memory_cards=[card],
        as_of=NOW,
        query_terms=["高亮", "正常参考"],
        product_family="metal-part",
        camera_id="CAM-02",
        legacy_only=True,
    )
    verify_assembled_incident_context(assembled, case=case, site_pack=pack)

    assert assembled.context.precedence == [
        "FROZEN_POLICY",
        "CURRENT_VERIFIED_EVIDENCE",
        "CURRENT_SITE_PROFILE",
        "APPROVED_HISTORICAL_EXPERIENCE",
        "MODEL_SUGGESTION",
    ]
    assert assembled.context.current_case_facts == case.decision_summary.observed_facts
    assert len(assembled.context.relevant_approved_memories) == 1
    reference = assembled.context.relevant_approved_memories[0]
    assert reference.memory_id == card.memory_id
    assert reference.historical_reference_only is True
    assert reference.may_set_current_case_fact is False
    assert reference.current_case_fact_eligible is False
    assert assembled.context.historical_memory_used_as_current_fact is False
    assert assembled.receipt.cross_site_memory_leakage_count == 0
    assert assembled.receipt.historical_memory_used_as_fact_count == 0


def test_preplanning_memory_is_retrieved_once_and_bound_without_fact_authority() -> (
    None
):
    request = build_fixture_industrial_incident_request()
    gate_context = _gate_context()
    pack = load_factory_site_pack(SITE_PACK_ROOT / "factory_a_line_01")
    accepted = _card(
        site_id=pack.manifest.site_id,
        pattern="fixture recipe change investigation hint",
        recommended="prioritize current recipe manifest countercheck",
        product_family=None,
        line_id=request.trigger.line_id,
        camera_id=None,
    )
    cross_line = _card(
        site_id=pack.manifest.site_id,
        pattern="fixture recipe change from another line",
        recommended="do not expose this content to the Planner",
        product_family=None,
        line_id="another-line",
        camera_id=None,
    )
    revoked = _card(
        site_id=pack.manifest.site_id,
        pattern="fixture recipe revoked history",
        recommended="do not expose revoked content",
        product_family=None,
        line_id=request.trigger.line_id,
        camera_id=None,
        status="REVOKED",
    )
    planning_subject = industrial_incident_planning_subject_sha256(
        request,
        gate_context,
    )
    planning_input = build_governed_memory_planning_input(
        planning_subject_sha256=planning_subject,
        site_pack=pack,
        memory_cards=[accepted, cross_line, revoked],
        line_id=request.trigger.line_id,
        as_of=NOW,
        processing_time=NOW,
        processing_time_source=_processing_time_source("preplanning-test"),
        query_terms=["fixture", "recipe", "change"],
    )
    verify_governed_memory_planning_input(planning_input)

    assert [
        item.memory_id for item in planning_input.accepted_historical_references
    ] == [accepted.memory_id]
    assert {
        item.memory_id: item.reason_code
        for item in planning_input.retrieval_receipt.rejected
    } == {
        cross_line.memory_id: "LINE_SCOPE_MISMATCH",
        revoked.memory_id: "REVOKED",
    }
    planner_payload = governed_memory_planner_payload(planning_input)
    serialized_payload = str(planner_payload)
    assert cross_line.content.pattern not in serialized_payload
    assert revoked.content.pattern not in serialized_payload
    assert planner_payload["current_case_fact_authority"] == "none"
    assert planner_payload["root_cause_authority"] == "none"
    assert planner_payload["decision_authority"] == "none"

    case = build_industrial_incident_case(
        request,
        gate_context,
        governed_memory=planning_input,
    )
    assembled = assemble_incident_context(
        case=case,
        site_pack=pack,
        memory_cards=[],
        planning_input=planning_input,
    )
    verify_assembled_incident_context(assembled, case=case, site_pack=pack)

    assert (
        case.governed_memory_retrieval_receipt_sha256
        == planning_input.retrieval_receipt.receipt_sha256
        == assembled.retrieval_receipt.receipt_sha256
    )
    assert assembled.planning_input == planning_input
    assert assembled.context.current_case_facts == case.decision_summary.observed_facts
    assert assembled.context.historical_memory_used_as_current_fact is False


class _SpyLocalEmbeddingAdapter:
    def __init__(self) -> None:
        self.seen_texts: list[str] = []

    @property
    def identity(self) -> EmbeddingIdentity:
        return EmbeddingIdentity(
            model_id="fixture-local-embedding",
            model_files_sha256="a" * 64,
            tokenizer_sha256="b" * 64,
            dimension=2,
        )

    def embed(self, texts: Sequence[str]) -> Sequence[Sequence[float]]:
        self.seen_texts = list(texts)
        return [[1.0, 0.0], *([[1.0, 0.0]] * (len(texts) - 1))]


class _FailingLocalEmbeddingAdapter(_SpyLocalEmbeddingAdapter):
    def embed(self, texts: Sequence[str]) -> Sequence[Sequence[float]]:
        self.seen_texts = list(texts)
        raise RuntimeError("fixture embedding failure")


def test_hybrid_v2_filters_before_local_embedding_and_seals_semantic_identity() -> None:
    allowed = _card(
        site_id="factory-a-line-01",
        pattern="曝光度漂移造成图像质量变化",
        recommended="compare approved exposure reference",
    )
    forbidden = _card(
        site_id="factory-b-cell-07",
        pattern="CROSS_SITE_PRIVATE_SENTINEL must never reach retrieval channels",
        recommended="do not disclose",
    )
    query = LegacyHybridMemoryQueryV2(
        site_id="factory-a-line-01",
        current_case_sha256=_sha256("hybrid-current-case"),
        as_of=NOW,
        product_family="metal-part",
        camera_id="CAM-02",
        terms=["曝光漂移", "exposure reference"],
    )
    profile = build_hybrid_retrieval_profile_v2(embedding_policy="optional")
    adapter = _SpyLocalEmbeddingAdapter()

    selected, receipt = retrieve_approved_memories_v2(
        [allowed, forbidden],
        query,
        profile=profile,
        embedding_adapter=adapter,
    )

    assert [item.memory_id for item in selected] == [allowed.memory_id]
    assert isinstance(receipt, HybridMemoryRetrievalReceiptV2)
    assert receipt.selection_algorithm == "HYBRID_SPARSE_RRF_V2"
    assert receipt.semantic_status == "USED"
    assert receipt.fallback == "NONE"
    assert receipt.embedding_model_identity.startswith("fixture-local-embedding@")
    assert all("CROSS_SITE_PRIVATE_SENTINEL" not in text for text in adapter.seen_texts)
    assert {item.memory_id: item.reason_code for item in receipt.rejected}[
        forbidden.memory_id
    ] == "CROSS_SITE_SCOPE"
    assert receipt.cross_site_memory_selected_count == 0
    assert receipt.historical_memory_used_as_fact_count == 0
    verify_memory_retrieval_receipt(receipt)


def test_hybrid_v2_optional_embedding_failure_has_deterministic_sparse_fallback() -> (
    None
):
    card = _card(
        site_id="factory-a-line-01",
        pattern="train validation duplicate leakage",
        recommended="compare content fingerprints",
    )
    query = LegacyHybridMemoryQueryV2(
        site_id="factory-a-line-01",
        current_case_sha256=_sha256("fallback-current-case"),
        as_of=NOW,
        product_family="metal-part",
        camera_id="CAM-02",
        terms=["duplicate leakage"],
    )
    profile = build_hybrid_retrieval_profile_v2(embedding_policy="optional")

    first_selected, first = retrieve_approved_memories_v2(
        [card],
        query,
        profile=profile,
        embedding_adapter=_FailingLocalEmbeddingAdapter(),
    )
    second_selected, second = retrieve_approved_memories_v2(
        [card],
        query,
        profile=profile,
        embedding_adapter=_FailingLocalEmbeddingAdapter(),
    )

    assert [item.memory_id for item in first_selected] == [card.memory_id]
    assert first_selected == second_selected
    assert first.semantic_status == "FAILED_FALLBACK"
    assert first.fallback == "DETERMINISTIC_LEXICAL"
    assert first.embedding_model_identity == "none"
    assert first.receipt_sha256 == second.receipt_sha256
    embedding = next(
        item for item in first.channel_receipts if item.channel == "embedding"
    )
    assert embedding.status == "UNAVAILABLE_FALLBACK"
    assert embedding.warning_code == "EMBEDDING_FAILED:RuntimeError"


def test_hybrid_v2_required_embedding_fails_closed_when_not_configured() -> None:
    card = _card(
        site_id="factory-a-line-01",
        pattern="annotation geometry mismatch",
        recommended="inspect current annotation receipt",
    )
    query = LegacyHybridMemoryQueryV2(
        site_id="factory-a-line-01",
        current_case_sha256=_sha256("required-embedding-current-case"),
        as_of=NOW,
        product_family="metal-part",
        camera_id="CAM-02",
        terms=["annotation mismatch"],
    )
    profile = build_hybrid_retrieval_profile_v2(embedding_policy="required")

    with pytest.raises(ValueError, match="required local embedding adapter"):
        retrieve_approved_memories_v2([card], query, profile=profile)


def test_hybrid_v2_receipt_detects_rank_or_status_tampering() -> None:
    card = _card(
        site_id="factory-a-line-01",
        pattern="mask image mismatch",
        recommended="verify mask image pairing",
    )
    query = LegacyHybridMemoryQueryV2(
        site_id="factory-a-line-01",
        current_case_sha256=_sha256("tamper-current-case"),
        as_of=NOW,
        product_family="metal-part",
        camera_id="CAM-02",
        terms=["mask mismatch"],
    )
    _selected, receipt = retrieve_approved_memories_v2([card], query)

    tampered = receipt.model_copy(update={"semantic_status": "USED"})
    with pytest.raises(ValueError, match="SHA-256"):
        verify_memory_retrieval_receipt(tampered)


def test_v2_planning_input_keeps_planner_authority_frozen() -> None:
    request = build_fixture_industrial_incident_request()
    pack = load_factory_site_pack(SITE_PACK_ROOT / "factory_a_line_01")
    card = _card(
        site_id=pack.manifest.site_id,
        pattern="fixture recipe drift historical hint",
        recommended="compare the current recipe manifest",
        product_family=None,
        line_id=request.trigger.line_id,
        camera_id=None,
    )
    planning = build_governed_memory_planning_input(
        planning_subject_sha256=_sha256("v2-planning-subject"),
        site_pack=pack,
        memory_cards=[card],
        line_id=request.trigger.line_id,
        as_of=NOW,
        processing_time=NOW,
        processing_time_source=_processing_time_source("planning-v3-test"),
        query_terms=["fixture recipe drift"],
        retrieval_profile=build_hybrid_retrieval_profile_v2(),
    )

    assert isinstance(planning.retrieval_receipt, HybridMemoryRetrievalReceiptV3)
    payload = governed_memory_planner_payload(planning)
    assert payload["current_case_fact_authority"] == "none"
    assert payload["root_cause_authority"] == "none"
    assert payload["decision_authority"] == "none"
    assert payload["policy_judge_input"] is False
    assert payload["machine_action_permitted"] is False


def test_irrelevant_memory_is_not_forced_into_context() -> None:
    case = build_industrial_incident_case(
        build_fixture_industrial_incident_request(),
        _gate_context(),
    )
    pack = load_factory_site_pack(SITE_PACK_ROOT / "factory_a_line_01")
    card = _card(
        site_id=pack.manifest.site_id,
        pattern="包装标签文字偏移",
        recommended="inspect_label_template",
    )

    assembled = assemble_incident_context(
        case=case,
        site_pack=pack,
        memory_cards=[card],
        as_of=NOW,
        query_terms=["曝光", "视觉配方"],
        product_family="metal-part",
        camera_id="CAM-02",
        legacy_only=True,
    )

    assert not assembled.context.relevant_approved_memories
    assert assembled.retrieval_receipt.rejected[0].reason_code == "NO_QUERY_RELEVANCE"


def test_direct_context_assembly_fails_closed_without_explicit_legacy_mode() -> None:
    case = build_industrial_incident_case(
        build_fixture_industrial_incident_request(),
        _gate_context(),
    )
    pack = load_factory_site_pack(SITE_PACK_ROOT / "factory_a_line_01")

    with pytest.raises(ValueError, match="planning input or legacy_only"):
        assemble_incident_context(
            case=case,
            site_pack=pack,
            memory_cards=[],
            as_of=NOW,
        )

    with pytest.raises(ValueError, match="explicit as_of"):
        assemble_incident_context(
            case=case,
            site_pack=pack,
            memory_cards=[],
            legacy_only=True,
        )


def test_example_site_packs_ship_only_valid_scoped_approved_memories() -> None:
    expected = {
        "factory_a_line_01": "factory-a-line-01",
        "factory_b_cell_07": "factory-b-cell-07",
    }
    for directory, site_id in expected.items():
        cards = load_approved_memory_store(
            SITE_PACK_ROOT / directory / "approved_memory.jsonl"
        )
        assert len(cards) == 1
        assert cards[0].scope.site_id == site_id
        assert cards[0].scope.station_id is None
        assert cards[0].status == "APPROVED"
        assert cards[0].historical_reference_only is True
        assert cards[0].may_set_current_case_fact is False
        assert cards[0].policy_judge_input is False
