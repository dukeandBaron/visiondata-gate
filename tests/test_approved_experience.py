from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from visiondata_gate.approved_experience import (
    ExperienceCandidateType,
    ExperienceState,
    MemoryAdmissionEnvelope,
    build_memory_admission_envelope,
    build_source_case_evidence_binding,
    build_experience_candidate,
    decide_experience_approval,
    initialize_experience,
    load_memory_admission_store,
    memory_admission_envelope_jsonl,
    promote_experience,
    promoted_memory_jsonl,
    record_experience_replay,
    record_experience_shadow,
    rollback_experience,
    verify_approved_experience_record,
    verify_memory_admission_envelope,
)
from visiondata_gate.governed_context import ApprovedMemoryContent, MemoryScope

NOW = datetime(2026, 8, 26, 9, 0, tzinfo=UTC)


def _digest(label: str) -> str:
    return hashlib.sha256(label.encode("utf-8")).hexdigest()


def _candidate():
    return build_experience_candidate(
        candidate_type=ExperienceCandidateType.WORKER_PRIORITY_HINT,
        source_case_ids=["incident_0123456789abcdefabcd"],
        proposal=ApprovedMemoryContent(
            pattern="固定图像坐标重复出现高亮区域",
            recommended_first_check="retrieve_current_normal_reference",
            avoid_first_action="declare_process_root_cause",
            advisory_summary="历史案件只改变补证顺序，当前案件仍须独立验证。",
        ),
        affected_scope=MemoryScope(
            site_id="factory-a-line-01",
            product_family="metal-part",
            camera_id="CAM-02",
        ),
        required_replay_suite="industrial-incident-bench-v1",
    )


def _replay(record, **overrides):
    values = {
        "replay_suite_sha256": _digest("frozen-suite"),
        "case_count": 15,
        "passed_case_count": 15,
        "deterministic_replay_rate": 1.0,
        "unsafe_closure_count": 0,
        "false_root_cause_count": 0,
        "premature_production_recovery_count": 0,
        "cross_site_memory_leakage_count": 0,
        "historical_memory_used_as_fact_count": 0,
        "evaluated_at": NOW + timedelta(minutes=1),
    }
    values.update(overrides)
    return record_experience_replay(record, **values)


def _approved_record():
    record = initialize_experience(_candidate(), created_at=NOW)
    record = _replay(record)
    return decide_experience_approval(
        record,
        approve=True,
        actor_user_id="quality-manager-01",
        actor_role="QualityManager",
        note="批准进入影子观察，但不授予生产放行或设备控制权限。",
        approval_evidence_sha256=_digest("signed-human-review"),
        decided_at=NOW + timedelta(minutes=2),
    )


def _promoted_record():
    record = _approved_record()
    record = record_experience_shadow(
        record,
        observed_case_count=6,
        changed_worker_order_count=2,
        unsafe_closure_count=0,
        cross_site_memory_leakage_count=0,
        historical_memory_used_as_fact_count=0,
        observed_at=NOW + timedelta(minutes=3),
    )
    return promote_experience(
        record,
        promoted_at=NOW + timedelta(minutes=4),
        actor="quality-governance-owner",
    )


def _source_binding(*, site_id: str = "factory-a-line-01"):
    return build_source_case_evidence_binding(
        workspace_id="workspace-a",
        project_id="project-a",
        task_id="task-a",
        case_id="incident_0123456789abcdefabcd",
        case_sha256=_digest("source-case"),
        case_audit_root_sha256=_digest("source-case-audit-root"),
        scope=MemoryScope(
            site_id=site_id,
            product_family="metal-part",
            camera_id="CAM-02",
        ),
        verification_status="VERIFIED_LOCAL_CASE",
        verified_at=NOW + timedelta(minutes=4),
    )


def test_full_experience_loop_promotes_only_historical_memory() -> None:
    record = _promoted_record()

    verify_approved_experience_record(record)
    assert record.state is ExperienceState.PROMOTED
    assert [event.to_state.value for event in record.events] == [
        "CANDIDATE",
        "REPLAY_TESTED",
        "HUMAN_APPROVED",
        "SHADOW",
        "PROMOTED",
    ]
    assert record.promoted_memory is not None
    assert record.promoted_memory.historical_reference_only is True
    assert record.promoted_memory.may_set_current_case_fact is False
    assert record.online_model_update_performed is False
    assert record.frozen_policy_mutated is False
    serialized = json.loads(promoted_memory_jsonl(record))
    assert serialized["status"] == "APPROVED"
    assert serialized["policy_judge_input"] is False


def test_strict_admission_store_verifies_full_chain_and_source_registry(
    tmp_path: Path,
) -> None:
    record = _promoted_record()
    binding = _source_binding()
    envelope = build_memory_admission_envelope(
        record,
        workspace_id="workspace-a",
        project_id="project-a",
        source_case_bindings=[binding],
        admitted_at=NOW + timedelta(minutes=5),
        admitted_by_actor_user_id="quality-governance-owner",
        admitted_by_actor_role="QualityGovernanceOwner",
    )
    verify_memory_admission_envelope(envelope)
    path = tmp_path / "strict-memory-admission.jsonl"
    path.write_text(memory_admission_envelope_jsonl(envelope), encoding="utf-8")

    cards, receipt = load_memory_admission_store(
        path,
        expected_workspace_id="workspace-a",
        expected_project_id="project-a",
        source_case_registry={binding.case_id: binding},
    )

    assert isinstance(envelope, MemoryAdmissionEnvelope)
    assert cards == [record.promoted_memory]
    assert receipt.admission_status == "STRICT_PROMOTION_CHAIN_VERIFIED"
    assert receipt.entry_count == 1
    assert receipt.envelope_sha256 == [envelope.envelope_sha256]


def test_strict_admission_rejects_bare_card_and_unresolved_source(
    tmp_path: Path,
) -> None:
    record = _promoted_record()
    assert record.promoted_memory is not None
    bare = tmp_path / "bare-memory.jsonl"
    bare.write_text(promoted_memory_jsonl(record), encoding="utf-8")

    with pytest.raises(ValueError, match="failed at line 1"):
        load_memory_admission_store(
            bare,
            expected_workspace_id="workspace-a",
            expected_project_id="project-a",
            source_case_registry={},
        )

    binding = _source_binding()
    envelope = build_memory_admission_envelope(
        record,
        workspace_id="workspace-a",
        project_id="project-a",
        source_case_bindings=[binding],
        admitted_at=NOW + timedelta(minutes=5),
        admitted_by_actor_user_id="quality-governance-owner",
        admitted_by_actor_role="QualityGovernanceOwner",
    )
    strict = tmp_path / "strict-memory.jsonl"
    strict.write_text(memory_admission_envelope_jsonl(envelope), encoding="utf-8")
    with pytest.raises(ValueError, match="absent from registry"):
        load_memory_admission_store(
            strict,
            expected_workspace_id="workspace-a",
            expected_project_id="project-a",
            source_case_registry={},
        )


def test_strict_admission_rejects_cross_scope_source_case() -> None:
    record = _promoted_record()
    with pytest.raises(ValueError, match="escaped memory scope"):
        build_memory_admission_envelope(
            record,
            workspace_id="workspace-a",
            project_id="project-a",
            source_case_bindings=[_source_binding(site_id="factory-b-cell-07")],
            admitted_at=NOW + timedelta(minutes=5),
            admitted_by_actor_user_id="quality-governance-owner",
            admitted_by_actor_role="QualityGovernanceOwner",
        )


def test_replay_safety_failure_is_fail_closed() -> None:
    record = initialize_experience(_candidate(), created_at=NOW)
    failed = _replay(record, historical_memory_used_as_fact_count=1)

    assert failed.state is ExperienceState.REJECTED
    assert failed.replay_receipt is not None
    assert failed.replay_receipt.outcome == "FAIL"
    with pytest.raises(ValueError, match="passed replay"):
        decide_experience_approval(
            failed,
            approve=True,
            actor_user_id="quality-manager-01",
            actor_role="QualityManager",
            note="This approval must not be accepted after replay failure.",
            approval_evidence_sha256=_digest("invalid-approval"),
            decided_at=NOW + timedelta(minutes=2),
        )


def test_human_approval_is_mandatory_before_shadow_or_promotion() -> None:
    record = _replay(initialize_experience(_candidate(), created_at=NOW))

    with pytest.raises(ValueError, match="HUMAN_APPROVED"):
        record_experience_shadow(
            record,
            observed_case_count=1,
            changed_worker_order_count=0,
            unsafe_closure_count=0,
            cross_site_memory_leakage_count=0,
            historical_memory_used_as_fact_count=0,
            observed_at=NOW + timedelta(minutes=2),
        )
    with pytest.raises(ValueError, match="passed SHADOW"):
        promote_experience(
            record,
            promoted_at=NOW + timedelta(minutes=3),
            actor="system",
        )


def test_promoted_experience_can_be_revoked_without_rewriting_history() -> None:
    record = _approved_record()
    record = record_experience_shadow(
        record,
        observed_case_count=3,
        changed_worker_order_count=1,
        unsafe_closure_count=0,
        cross_site_memory_leakage_count=0,
        historical_memory_used_as_fact_count=0,
        observed_at=NOW + timedelta(minutes=3),
    )
    promoted = promote_experience(
        record,
        promoted_at=NOW + timedelta(minutes=4),
        actor="quality-governance-owner",
    )
    rolled_back = rollback_experience(
        promoted,
        rolled_back_at=NOW + timedelta(days=1),
        actor="quality-governance-owner",
        reason="A later approved review invalidated this investigation hint.",
    )

    verify_approved_experience_record(rolled_back)
    assert rolled_back.state is ExperienceState.ROLLED_BACK
    assert rolled_back.promoted_memory is not None
    assert rolled_back.promoted_memory.status == "APPROVED"
    assert rolled_back.revoked_memory is not None
    assert rolled_back.revoked_memory.status == "REVOKED"
    assert rolled_back.events[-2].to_state is ExperienceState.PROMOTED
    assert rolled_back.events[-1].to_state is ExperienceState.ROLLED_BACK
