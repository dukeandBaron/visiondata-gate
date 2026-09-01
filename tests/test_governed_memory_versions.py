from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime
from pathlib import Path

import pytest

from visiondata_gate.evidence import canonical_json_bytes
from visiondata_gate.governed_context import (
    ApprovedMemoryCard,
    ApprovedMemoryContent,
    ClockedMemoryQueryV3,
    HybridMemoryRetrievalReceiptV3,
    LegacyHybridMemoryQueryV2,
    LegacyHybridMemoryRetrievalReceiptV2,
    LegacyMemoryQueryV1,
    LegacyMemoryRetrievalReceiptV1,
    MemoryProcessingTimeSource,
    MemoryScope,
    build_approved_memory_card,
    parse_memory_retrieval_receipt,
    retrieve_approved_memories,
    retrieve_approved_memories_v2,
    retrieve_approved_memories_v3,
    verify_memory_retrieval_command_admission_binding,
    verify_memory_retrieval_receipt,
)


FIXTURE = Path(__file__).parent / "fixtures" / "legacy_memory_v1_golden.json"
EVENT_TIME = datetime(2026, 8, 10, tzinfo=UTC)
PROCESSING_TIME = datetime(2026, 8, 29, tzinfo=UTC)
V3_DOMAIN = b"visiondata-gate/industrial-memory-retrieval/audit/v3\x00"
COMMAND_ID = "incident_command_0123456789abcdef01234567"


def _digest(label: str) -> str:
    return hashlib.sha256(label.encode("utf-8")).hexdigest()


ADMISSION_SHA256 = _digest("command-admission")


def _memory(*, valid_from: datetime, valid_until: datetime | None = None):
    return build_approved_memory_card(
        memory_type="INVESTIGATION_HINT",
        scope=MemoryScope(
            site_id="factory-a-line-01",
            product_family="metal-part",
            line_id="LINE-03",
            camera_id="CAM-02",
        ),
        content=ApprovedMemoryContent(
            pattern="exposure drift approved reference",
            recommended_first_check="compare current exposure reference",
            avoid_first_action="reuse historical result as current fact",
            advisory_summary="Historical exposure evidence is advisory only.",
        ),
        source_case_ids=["incident_0123456789abcdefabcd"],
        approval_sha256=_digest(
            f"memory-version-fixture:{valid_from.isoformat()}:{valid_until}"
        ),
        valid_from=valid_from,
        valid_until=valid_until,
    )


def _source() -> MemoryProcessingTimeSource:
    return MemoryProcessingTimeSource(
        source_kind="EXPLICIT_CALLER_BINDING",
        source_id="version-contract-test",
        source_sha256=_digest("version-contract-test"),
    )


def _v3_query() -> ClockedMemoryQueryV3:
    return ClockedMemoryQueryV3(
        site_id="factory-a-line-01",
        current_case_sha256=_digest("clocked-current-case"),
        event_time=EVENT_TIME,
        processing_time=PROCESSING_TIME,
        processing_time_source=_source(),
        product_family="metal-part",
        line_id="LINE-03",
        camera_id="CAM-02",
        terms=["exposure", "reference"],
    )


def _reseal_v3(receipt: HybridMemoryRetrievalReceiptV3, **updates: object):
    tampered = receipt.model_copy(update=updates)
    payload = tampered.model_dump(mode="json", exclude={"receipt_sha256"})
    seal = hashlib.sha256(
        V3_DOMAIN + canonical_json_bytes(payload, trailing_newline=False)
    ).hexdigest()
    return tampered.model_copy(update={"receipt_sha256": seal})


def test_legacy_v1_portable_golden_remains_byte_contract_compatible() -> None:
    fixture = json.loads(FIXTURE.read_text(encoding="utf-8"))
    cards = [ApprovedMemoryCard.model_validate(item) for item in fixture["cards"]]
    query = LegacyMemoryQueryV1.model_validate(fixture["query"])

    selected, generated = retrieve_approved_memories(cards, query)
    parsed = parse_memory_retrieval_receipt(fixture["receipt"])

    assert isinstance(parsed, LegacyMemoryRetrievalReceiptV1)
    assert generated.model_dump(mode="json") == fixture["receipt"]
    assert generated.receipt_sha256 == (
        "371f38cb04ae254b41b33d88b2835c67c68f39b3d2943aaebb9d9b27c29e7e95"
    )
    assert [item.memory_id for item in selected] == ["memory_1a8f7d204ad80e86e2e8"]
    assert set(parsed.model_dump(mode="json")) == set(fixture["receipt"])
    verification = verify_memory_retrieval_receipt(parsed)
    assert verification.dual_clock_authorization == "NOT_PROVABLE"
    assert verification.processing_time_source_verified is False

    tampered = parsed.model_copy(update={"current_case_sha256": "f" * 64})
    with pytest.raises(ValueError, match="SHA-256"):
        verify_memory_retrieval_receipt(tampered)


def test_legacy_hybrid_v2_remains_single_clock_and_not_provable() -> None:
    card = _memory(valid_from=datetime(2026, 8, 1, tzinfo=UTC))
    query = LegacyHybridMemoryQueryV2(
        site_id="factory-a-line-01",
        current_case_sha256=_digest("legacy-hybrid-current-case"),
        as_of=PROCESSING_TIME,
        product_family="metal-part",
        line_id="LINE-03",
        camera_id="CAM-02",
        terms=["exposure", "reference"],
    )

    selected, receipt = retrieve_approved_memories_v2([card], query)
    dumped = receipt.model_dump(mode="json")

    assert isinstance(receipt, LegacyHybridMemoryRetrievalReceiptV2)
    assert [item.memory_id for item in selected] == [card.memory_id]
    assert {"event_time", "processing_time", "processing_time_source"}.isdisjoint(
        dumped
    )
    verification = verify_memory_retrieval_receipt(receipt)
    assert verification.dual_clock_authorization == "NOT_PROVABLE"
    assert isinstance(
        parse_memory_retrieval_receipt(dumped),
        LegacyHybridMemoryRetrievalReceiptV2,
    )


def test_v3_uses_processing_time_for_authorization_and_proves_source_structure() -> (
    None
):
    approved_after_event = _memory(valid_from=datetime(2026, 8, 25, tzinfo=UTC))
    expired_before_processing = _memory(
        valid_from=datetime(2026, 8, 1, tzinfo=UTC),
        valid_until=datetime(2026, 8, 20, tzinfo=UTC),
    )

    selected, receipt = retrieve_approved_memories_v3(
        [approved_after_event, expired_before_processing],
        _v3_query(),
    )
    verification = verify_memory_retrieval_receipt(receipt)

    assert [item.memory_id for item in selected] == [approved_after_event.memory_id]
    assert {item.memory_id: item.reason_code for item in receipt.rejected} == {
        expired_before_processing.memory_id: "EXPIRED"
    }
    assert receipt.event_time == EVENT_TIME
    assert receipt.processing_time == PROCESSING_TIME
    assert receipt.processing_time_source == _source()
    assert verification.dual_clock_authorization == "PROVABLE"
    assert verification.source_structure_verified is True
    assert verification.processing_time_source_verified is False
    assert verification.source_binding_evidence == "RECEIPT_STRUCTURE_ONLY"
    assert isinstance(
        parse_memory_retrieval_receipt(receipt.model_dump(mode="json")),
        HybridMemoryRetrievalReceiptV3,
    )


def test_v3_command_admission_binding_requires_external_identity_sha_and_time() -> None:
    card = _memory(valid_from=datetime(2026, 8, 1, tzinfo=UTC))
    query = _v3_query().model_copy(
        update={
            "processing_time_source": MemoryProcessingTimeSource(
                source_kind="INCIDENT_COMMAND_ADMISSION",
                source_id=COMMAND_ID,
                source_sha256=ADMISSION_SHA256,
            )
        }
    )
    _selected, receipt = retrieve_approved_memories_v3([card], query)

    verified = verify_memory_retrieval_command_admission_binding(
        receipt,
        command_id=COMMAND_ID,
        admission_sha256=ADMISSION_SHA256,
        admitted_at=PROCESSING_TIME,
    )

    assert verified.dual_clock_authorization == "PROVABLE"
    assert verified.source_structure_verified is True
    assert verified.processing_time_source_verified is True
    assert verified.source_binding_evidence == "COMMAND_ADMISSION_VERIFIED"

    with pytest.raises(ValueError, match="command ID binding"):
        verify_memory_retrieval_command_admission_binding(
            receipt,
            command_id="incident_command_ffffffffffffffffffffffff",
            admission_sha256=ADMISSION_SHA256,
            admitted_at=PROCESSING_TIME,
        )
    with pytest.raises(ValueError, match="admission SHA binding"):
        verify_memory_retrieval_command_admission_binding(
            receipt,
            command_id=COMMAND_ID,
            admission_sha256=_digest("tampered-admission"),
            admitted_at=PROCESSING_TIME,
        )
    with pytest.raises(ValueError, match="differs from admission time"):
        verify_memory_retrieval_command_admission_binding(
            receipt,
            command_id=COMMAND_ID,
            admission_sha256=ADMISSION_SHA256,
            admitted_at=datetime(2026, 8, 29, 0, 0, 1, tzinfo=UTC),
        )


def test_v3_rechecks_clock_order_awareness_and_source_after_reseal() -> None:
    card = _memory(valid_from=datetime(2026, 8, 1, tzinfo=UTC))
    _selected, receipt = retrieve_approved_memories_v3([card], _v3_query())

    bad_order = _reseal_v3(
        receipt,
        processing_time=datetime(2026, 8, 9, tzinfo=UTC),
    )
    with pytest.raises(ValueError, match="must not precede"):
        verify_memory_retrieval_receipt(bad_order)

    naive = _reseal_v3(receipt, processing_time=datetime(2026, 8, 29))
    with pytest.raises(ValueError, match="explicit UTC offset"):
        verify_memory_retrieval_receipt(naive)

    invalid_source = MemoryProcessingTimeSource.model_construct(
        source_kind="INCIDENT_COMMAND_ADMISSION",
        source_id="fabricated-command",
        source_sha256="a" * 64,
    )
    bad_source = _reseal_v3(receipt, processing_time_source=invalid_source)
    with pytest.raises(ValueError, match="command ID"):
        verify_memory_retrieval_receipt(bad_source)
