from __future__ import annotations

from datetime import UTC, datetime

import pytest

from visiondata_gate.governed_context import (
    ApprovedMemoryContent,
    ClockedMemoryQueryV3,
    MemoryProcessingTimeSource,
    MemoryScope,
    build_approved_memory_card,
    retrieve_approved_memories_v3,
    verify_memory_retrieval_receipt,
)


EVENT_TIME = datetime(2026, 8, 10, tzinfo=UTC)
PROCESSING_TIME = datetime(2026, 8, 29, tzinfo=UTC)


def _memory(
    *,
    pattern: str,
    valid_from: datetime,
    valid_until: datetime | None = None,
):
    return build_approved_memory_card(
        memory_type="INVESTIGATION_HINT",
        scope=MemoryScope(
            site_id="factory-a-line-01",
            product_family="metal-part",
            line_id="LINE-03",
            camera_id="CAM-02",
        ),
        content=ApprovedMemoryContent(
            pattern=pattern,
            recommended_first_check="compare current exposure reference",
            avoid_first_action="reuse historical result as current fact",
            advisory_summary="Historical exposure evidence is advisory only.",
        ),
        source_case_ids=["incident_0123456789abcdefabcd"],
        approval_sha256="a" * 64,
        valid_from=valid_from,
        valid_until=valid_until,
    )


def _query(*, processing_time: datetime = PROCESSING_TIME) -> ClockedMemoryQueryV3:
    return ClockedMemoryQueryV3(
        site_id="factory-a-line-01",
        current_case_sha256="b" * 64,
        event_time=EVENT_TIME,
        processing_time=processing_time,
        processing_time_source=MemoryProcessingTimeSource(
            source_kind="EXPLICIT_CALLER_BINDING",
            source_id="dual-clock-test",
            source_sha256="c" * 64,
        ),
        product_family="metal-part",
        line_id="LINE-03",
        camera_id="CAM-02",
        terms=["exposure", "reference"],
    )


def test_processing_clock_rejects_now_expired_memory_and_allows_late_approval() -> None:
    expired_after_event = _memory(
        pattern="exposure drift reference that expired after the incident",
        valid_from=datetime(2026, 8, 1, tzinfo=UTC),
        valid_until=datetime(2026, 8, 20, tzinfo=UTC),
    )
    approved_after_event = _memory(
        pattern="exposure drift reference approved before investigation",
        valid_from=datetime(2026, 8, 25, tzinfo=UTC),
    )

    selected, receipt = retrieve_approved_memories_v3(
        [expired_after_event, approved_after_event],
        _query(),
    )

    assert [card.memory_id for card in selected] == [approved_after_event.memory_id]
    assert {item.memory_id: item.reason_code for item in receipt.rejected} == {
        expired_after_event.memory_id: "EXPIRED"
    }
    assert receipt.event_time == EVENT_TIME
    assert receipt.processing_time == PROCESSING_TIME
    assert receipt.authorization_clock == "PROCESSING_TIME"
    assert receipt.stale_memory_selected_count == 0
    verify_memory_retrieval_receipt(receipt)


def test_dual_clock_order_and_receipt_binding_fail_closed() -> None:
    with pytest.raises(ValueError, match="processing_time must not precede"):
        _query(processing_time=datetime(2026, 8, 9, tzinfo=UTC))

    card = _memory(
        pattern="exposure reference with current authorization",
        valid_from=datetime(2026, 8, 1, tzinfo=UTC),
    )
    _selected, receipt = retrieve_approved_memories_v3([card], _query())
    tampered = receipt.model_copy(update={"processing_time": EVENT_TIME})
    with pytest.raises(ValueError, match="SHA-256"):
        verify_memory_retrieval_receipt(tampered)
