from __future__ import annotations

import hashlib
import json

from visiondata_gate.runtime_memory import (
    LocalMemoryStore,
    memory_record_sha256,
)
from visiondata_gate.runtime_models import MemoryRecord


def _record(
    run_id: str,
    *,
    phase: str = "initial",
    batch_id: str = "batch-a",
    decision: str = "RECAPTURE",
    summary: str = "工业视觉数据发布审核：发现重复泄漏，等待复验",
) -> MemoryRecord:
    return MemoryRecord(
        run_id=run_id,
        phase=phase,
        batch_id=batch_id,
        decision=decision,
        finding_codes=["CROSS_SPLIT_DUPLICATE"],
        completed_tools=["duplicate_leakage", "image_quality"],
        backend="deterministic",
        summary=summary,
    )


def test_memory_write_receipts_cover_write_duplicate_replace_and_hashes(
    tmp_path,
) -> None:
    path = tmp_path / "memory.json"
    store = LocalMemoryStore(path, max_records=2)
    original = _record("run-1")

    records, written, warning = store.append_with_receipt(original)

    assert warning is None
    assert written.action == "write"
    assert written.candidate_record_sha256 == memory_record_sha256(original)
    assert written.store_before_sha256 == hashlib.sha256(b"").hexdigest()
    assert written.store_after_sha256 == hashlib.sha256(path.read_bytes()).hexdigest()
    assert len(records) == 1
    assert written.reasoning_content_retained is False
    assert written.raw_prompt_retained is False
    assert written.raw_media_retained is False
    assert written.tool_history_scope == "completed_tool_names_only"

    _records, duplicate, warning = store.append_with_receipt(original)

    assert warning is None
    assert duplicate.action == "skip_duplicate"
    assert duplicate.store_before_sha256 == duplicate.store_after_sha256

    replacement = _record(
        "run-1",
        decision="PASS",
        summary="工业视觉数据发布审核：同一运行完成复验",
    )
    records, replaced, warning = store.append_with_receipt(replacement)

    assert warning is None
    assert replaced.action == "replace_same_run_phase"
    assert replaced.replaced_record_sha256 == memory_record_sha256(original)
    assert records == [replacement]

    store.append_with_receipt(_record("run-2", batch_id="batch-b"))
    records, evicted, warning = store.append_with_receipt(
        _record("run-3", batch_id="batch-c")
    )

    assert warning is None
    assert evicted.action == "write"
    assert evicted.evicted_count == 1
    assert [item.run_id for item in records] == ["run-2", "run-3"]


def test_memory_recall_is_deterministic_source_bound_and_advisory_only(
    tmp_path,
) -> None:
    store = LocalMemoryStore(tmp_path / "memory.json")
    relevant = _record("run-relevant", batch_id="batch-target")
    irrelevant = _record(
        "run-other",
        batch_id="batch-other",
        summary="音频行程推荐记录",
    )
    store.append(relevant)
    store.append(irrelevant)
    query = "工业视觉数据发布审核 batch_id=batch-target 复验重复泄漏"

    first_hits, first_receipt, first_warning = store.recall(query, limit=2)
    second_hits, second_receipt, second_warning = store.recall(query, limit=2)

    assert first_warning is None
    assert second_warning is None
    assert first_hits == second_hits
    assert first_receipt == second_receipt
    assert first_receipt.candidate_count == 2
    assert first_receipt.selected[0].run_id == "run-relevant"
    assert first_hits[0].source.startswith("local-memory://run-relevant/")
    assert first_hits[0].permission_scope == "council-advisory-only"
    assert first_receipt.policy_judge_input is False
    assert first_receipt.tool_measurement_input is False
    assert first_receipt.raw_query_retained is False
    serialized = json.dumps(first_receipt.model_dump(mode="json"), ensure_ascii=False)
    assert query not in serialized


def test_invalid_memory_is_ignored_and_never_overwritten(tmp_path) -> None:
    path = tmp_path / "memory.json"
    tampered = b'{"unexpected":"shape"}\n'
    path.write_bytes(tampered)
    store = LocalMemoryStore(path)

    hits, recall, warning = store.recall("工业视觉数据发布", limit=4)
    records, write, write_warning = store.append_with_receipt(_record("run-new"))

    assert hits == []
    assert records == []
    assert warning is not None
    assert write_warning == warning
    assert recall.warning == warning
    assert write.action == "skip_invalid_store"
    assert write.store_before_sha256 == write.store_after_sha256
    assert path.read_bytes() == tampered
