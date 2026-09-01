from __future__ import annotations

import hashlib

import pytest

from visiondata_gate.capa import (
    CapaCaseReport,
    CapaCaseSelection,
    CapaExecutionReceipt,
    CapaRecoveryReceipt,
    CapaResponsibilityItem,
    CapaResponsibilityQueue,
    CapaStatus,
    ResponsibilityStatus,
    verify_child_run_closure,
)
from visiondata_gate.case_replay import build_causal_replay_report
from visiondata_gate.contracts import (
    CouncilTrace,
    EvidenceStatus,
    Finding,
    GateDecision,
    GateResult,
    Severity,
    ToolTrace,
    WorkOrder,
)
from visiondata_gate.evidence import canonical_json_bytes
from visiondata_gate.industrial_delivery import (
    IndustrialRemediationPlan,
    IndustrialRemediationWave,
)
from visiondata_gate.product_models import (
    DataSourceKind,
    TaskExecutionStatus,
    TaskRecord,
)
from visiondata_gate.runtime_models import ScenarioProfile


MAGIC_DEMO_COUNTS = {33, 48, 49}


def _sha(label: str) -> str:
    return hashlib.sha256(label.encode("utf-8")).hexdigest()


def _task(task_id: str, *, evidence_label: str) -> TaskRecord:
    timestamp = "2026-08-28T08:00:00+00:00"
    return TaskRecord(
        task_id=task_id,
        workspace_id="workspace-replay",
        project_id="project-replay",
        created_by="quality-owner",
        goal="Replay one bounded industrial evidence chain.",
        seed=20_260_828,
        scenario_profile=ScenarioProfile.INDUSTRIAL,
        source_kind=DataSourceKind.SYNTHETIC_DEMO,
        source_id=None,
        plan_approval_required=False,
        allowed_tools=["image_quality", "duplicate_leakage"],
        request_sha256=_sha(f"request-{task_id}"),
        execution_status=TaskExecutionStatus.COMPLETED,
        current_phase="DELIVER",
        initial_decision="RECAPTURE",
        final_decision="QUARANTINE",
        runtime_status="COMPLETED",
        evidence_sha256=_sha(evidence_label),
        created_at=timestamp,
        updated_at=timestamp,
        started_at=timestamp,
        completed_at=timestamp,
    )


def _finding(index: int, *, run_label: str) -> Finding:
    return Finding(
        finding_id=f"{run_label}-finding-{index:02d}",
        code=f"BOUNDED_CODE_{index:02d}",
        severity=Severity.HIGH,
        tool="deterministic-replay-fixture",
        sample_ids=[f"sample-redacted-{index:02d}"],
        summary=f"Bounded finding {index}.",
        evidence={"bounded_measurement": index},
        evidence_status=EvidenceStatus.VERIFIED,
        recommended_action="INVESTIGATE",
    )


def _gate_result(
    *,
    run_label: str,
    finding_count: int,
    work_order_count: int,
    decision: GateDecision,
) -> GateResult:
    findings = [_finding(index, run_label=run_label) for index in range(finding_count)]
    work_orders = [
        WorkOrder(
            work_order_id=f"{run_label}-work-order-{index:02d}",
            action="INVESTIGATE",
            priority=Severity.HIGH,
            reason_codes=[findings[index % len(findings)].code],
            sample_ids=findings[index % len(findings)].sample_ids,
            replacement_requirements={"human_recheck": True},
        )
        for index in range(work_order_count)
    ]
    return GateResult(
        run_id=f"run-{run_label}",
        batch_id="batch-replay",
        contract_id="frozen-replay-contract-v7",
        input_sha256=_sha(f"input-{run_label}"),
        policy_version="policy-replay-v7",
        decision=decision,
        decision_reason="Bounded replay fixture decision.",
        metrics={"finding_count": finding_count, "sample_count": 17},
        findings=findings,
        tool_trace=[
            ToolTrace(
                sequence=1,
                tool="deterministic-replay-fixture",
                status="ok",
                input_sha256=_sha(f"tool-input-{run_label}"),
                parameters={"fixture": run_label},
                result_sha256=_sha(f"tool-result-{run_label}"),
                finding_ids=[item.finding_id for item in findings],
            )
        ],
        council_trace=CouncilTrace(
            backend="deterministic-fixture",
            shared_model_disclosure="No model was invoked.",
            independent_opinions=[],
            cross_examination=[],
            unresolved_objections=[],
        ),
        work_orders=work_orders,
    )


def _remediation_plan(
    parent_task_id: str, work_order_count: int
) -> IndustrialRemediationPlan:
    work_order_ids = [
        f"responsibility-{index:02d}" for index in range(work_order_count)
    ]
    return IndustrialRemediationPlan(
        task_id=parent_task_id,
        run_id="run-parent-final",
        plan_id="plan-replay",
        strategy="full_evidence_closure",
        title="Bounded replay remediation",
        objective="Preserve responsibility and finding denominators independently.",
        selected_work_order_ids=work_order_ids,
        deferred_work_order_ids=[],
        targeted_finding_ids=["parent-final-finding-00"],
        evidence_coverage_ratio=1.0,
        relative_effort_points=17,
        waves=[
            IndustrialRemediationWave(
                wave_id="wave-replay-01",
                sequence=1,
                objective="Named human review on a private derived version.",
                work_order_ids=work_order_ids,
                owner_roles=["quality_owner"],
                prerequisite_wave_ids=[],
                acceptance_gate="Same-contract Child Run is required.",
            )
        ],
        residual_risk_codes=[],
        review_eligibility="full_closure_recheck_required",
        plan_sha256=_sha(f"plan-{parent_task_id}-{work_order_count}"),
    )


def _selection(parent_task: TaskRecord, work_order_count: int) -> CapaCaseSelection:
    plan = _remediation_plan(parent_task.task_id, work_order_count)
    return CapaCaseSelection(
        case_id="case-replay",
        parent_task_id=parent_task.task_id,
        parent_request_sha256=parent_task.request_sha256,
        parent_evidence_sha256=parent_task.evidence_sha256 or "",
        industrial_delivery_sha256=_sha("industrial-delivery"),
        plan=plan,
        selected_by="quality-owner",
        selection_note="Selected for bounded replay coverage.",
        created_at="2026-08-28T08:05:00+00:00",
        selection_sha256=_sha("selection-replay"),
    )


def _queue(
    parent_task_id: str,
    *,
    phase: str,
    item_count: int,
    closed_count: int,
) -> CapaResponsibilityQueue:
    items: list[CapaResponsibilityItem] = []
    for index in range(item_count):
        is_closed = index < closed_count
        items.append(
            CapaResponsibilityItem(
                queue_item_id=f"queue-item-{index:02d}",
                work_order_id=f"responsibility-{index:02d}",
                action="INVESTIGATE",
                priority="high",
                owner_role="quality_owner",
                required_skill="bounded-replay-review",
                status=(
                    ResponsibilityStatus.VERIFIED_CLOSED
                    if is_closed
                    else ResponsibilityStatus.OPEN
                ),
                selected=True,
                affected_sample_ids=[f"sample-redacted-{index:02d}"],
                finding_ids=[f"parent-final-finding-{index:02d}"],
                acceptance_criteria=["Hash-bound evidence is independently reviewed."],
                evidence_refs=[f"evidence-{index:02d}"],
                result_refs=[f"result-{index:02d}"] if is_closed else [],
                status_reason="Verified in Child Run." if is_closed else "Still open.",
            )
        )
    return CapaResponsibilityQueue(
        case_id="case-replay",
        parent_task_id=parent_task_id,
        phase=phase,
        items=items,
        open_count=item_count - closed_count,
        closed_count=closed_count,
        queue_sha256=_sha(f"queue-{phase}-{item_count}-{closed_count}"),
    )


def _selected_case(
    parent_task: TaskRecord, *, responsibility_count: int
) -> CapaCaseReport:
    return CapaCaseReport(
        case_id="case-replay",
        parent_task_id=parent_task.task_id,
        status=CapaStatus.SELECTED,
        selection=_selection(parent_task, responsibility_count),
        initial_queue=_queue(
            parent_task.task_id,
            phase="initial",
            item_count=responsibility_count,
            closed_count=0,
        ),
    )


def _completed_case(
    *,
    parent_task: TaskRecord,
    parent_final_gate: GateResult,
    child_task: TaskRecord,
    child_final_gate: GateResult,
    responsibility_count: int,
    closed_count: int,
) -> CapaCaseReport:
    initial_queue = _queue(
        parent_task.task_id,
        phase="initial",
        item_count=responsibility_count,
        closed_count=0,
    )
    final_queue = _queue(
        parent_task.task_id,
        phase="final",
        item_count=responsibility_count,
        closed_count=closed_count,
    )
    verification = verify_child_run_closure(
        parent_findings=parent_final_gate.findings,
        child_findings=child_final_gate.findings,
        parent_contract_id=parent_final_gate.contract_id,
        child_contract_id=child_final_gate.contract_id,
        child_decision=child_final_gate.decision.value,
        parent_evidence_sha256=parent_task.evidence_sha256 or "",
        child_evidence_sha256=child_task.evidence_sha256 or "",
    )
    execution = CapaExecutionReceipt(
        case_id="case-replay",
        parent_task_id=parent_task.task_id,
        child_task_id=child_task.task_id,
        derived_version_id="derived-replay-v1",
        derived_source_id="source-derived-replay",
        remediation_plan_sha256=_sha(
            f"plan-{parent_task.task_id}-{responsibility_count}"
        ),
        capa_approval_binding_sha256=_sha("approval-replay"),
        child_plan_approval_binding_sha256=_sha("child-approval-replay"),
        parent_evidence_sha256_before=parent_task.evidence_sha256 or "",
        parent_evidence_sha256_after=parent_task.evidence_sha256 or "",
        parent_source_profile_sha256_before=_sha("parent-profile"),
        parent_source_profile_sha256_after=_sha("parent-profile"),
        parent_immutable=True,
        child_evidence_sha256=child_task.evidence_sha256 or "",
        child_lineage_report_sha256=_sha("child-lineage"),
        executed_at="2026-08-28T08:20:00+00:00",
        receipt_sha256=_sha("execution-replay"),
    )
    recovery = CapaRecoveryReceipt(
        case_id="case-replay",
        parent_task_id=parent_task.task_id,
        child_task_id=child_task.task_id,
        status="STILL_BLOCKED",
        parent_decision=parent_final_gate.decision.value,
        child_decision=child_final_gate.decision.value,
        parent_finding_count=len(parent_final_gate.findings),
        child_finding_count=len(child_final_gate.findings),
        parent_finding_codes=sorted({item.code for item in parent_final_gate.findings}),
        child_finding_codes=sorted({item.code for item in child_final_gate.findings}),
        resolved_finding_codes=sorted(
            {item.code for item in parent_final_gate.findings}
            - {item.code for item in child_final_gate.findings}
        ),
        new_finding_codes=[],
        child_verification=verification,
        selected_work_order_count=responsibility_count,
        verified_closed_work_order_count=closed_count,
        remaining_work_order_count=responsibility_count - closed_count,
        recovery_success=False,
        required_human_action="Investigate the remaining responsibility items.",
        parent_evidence_sha256=parent_task.evidence_sha256 or "",
        child_evidence_sha256=child_task.evidence_sha256 or "",
        derived_version_receipt_sha256=_sha("derived-version-replay"),
        responsibility_queue_sha256=final_queue.queue_sha256,
        recovered_at="2026-08-28T08:30:00+00:00",
        receipt_sha256=_sha("recovery-replay"),
    )
    return CapaCaseReport(
        case_id="case-replay",
        parent_task_id=parent_task.task_id,
        status=CapaStatus.STILL_BLOCKED,
        selection=_selection(parent_task, responsibility_count),
        initial_queue=initial_queue,
        execution=execution,
        final_queue=final_queue,
        recovery=recovery,
    )


def test_causal_replay_keeps_unapproved_missing_child_state_truthful() -> None:
    parent_task = _task("parent-task-replay", evidence_label="parent-evidence")
    initial_gate = _gate_result(
        run_label="parent-initial",
        finding_count=7,
        work_order_count=5,
        decision=GateDecision.RECAPTURE,
    )
    final_gate = _gate_result(
        run_label="parent-final",
        finding_count=11,
        work_order_count=9,
        decision=GateDecision.QUARANTINE,
    )
    dynamic_plan = {
        "replan_count": 2,
        "dynamic_tasks": [
            {"task_id": "worker-exposure"},
            {"task_id": "worker-duplicate"},
            {"task_id": "worker-annotation"},
        ],
    }
    capa_report = _selected_case(parent_task, responsibility_count=13)

    first = build_causal_replay_report(
        parent_task=parent_task,
        parent_initial_gate=initial_gate,
        parent_final_gate=final_gate,
        dynamic_leader_plan=dynamic_plan,
        capa_report=capa_report,
    )
    second = build_causal_replay_report(
        parent_task=parent_task,
        parent_initial_gate=initial_gate,
        parent_final_gate=final_gate,
        dynamic_leader_plan=dynamic_plan,
        capa_report=capa_report,
    )

    t0, t1, t2, t3, t4 = first.steps
    assert t0.finding_count is None
    assert "NOT_EVALUATED" in t0.summary
    assert t1.finding_count == 7
    assert t2.finding_count == 11
    assert {t1.finding_count, t2.finding_count}.isdisjoint(MAGIC_DEMO_COUNTS)
    assert t3.decision == "PLAN_SELECTED_AWAITING_APPROVAL"
    assert t3.status == "PENDING"
    assert t3.responsibility_open == 13
    assert t4.status == "PENDING"
    assert t4.occurred is False
    assert t4.finding_count is None
    assert t4.responsibility_closed is None
    assert t4.responsibility_open is None
    assert first.current_step_id == "T3"
    assert first.child_task_id is None
    assert first == second
    assert (
        t1.evidence_digests["initial_gate_sha256"]
        == hashlib.sha256(canonical_json_bytes(initial_gate)).hexdigest()
    )
    assert (
        t2.evidence_digests["dynamic_plan_sha256"]
        == hashlib.sha256(canonical_json_bytes(dynamic_plan)).hexdigest()
    )
    assert (
        first.report_sha256
        == hashlib.sha256(
            canonical_json_bytes(
                first.model_dump(mode="json", exclude={"report_sha256"})
            )
        ).hexdigest()
    )


def test_causal_replay_keeps_finding_and_responsibility_denominators_independent() -> (
    None
):
    parent_task = _task("parent-task-replay", evidence_label="parent-evidence")
    child_task = _task("child-task-replay", evidence_label="child-evidence")
    initial_gate = _gate_result(
        run_label="parent-initial",
        finding_count=7,
        work_order_count=5,
        decision=GateDecision.RECAPTURE,
    )
    final_gate = _gate_result(
        run_label="parent-final",
        finding_count=11,
        work_order_count=9,
        decision=GateDecision.QUARANTINE,
    )
    child_gate = _gate_result(
        run_label="child-final",
        finding_count=4,
        work_order_count=3,
        decision=GateDecision.QUARANTINE,
    )
    capa_report = _completed_case(
        parent_task=parent_task,
        parent_final_gate=final_gate,
        child_task=child_task,
        child_final_gate=child_gate,
        responsibility_count=13,
        closed_count=9,
    )

    replay = build_causal_replay_report(
        parent_task=parent_task,
        parent_initial_gate=initial_gate,
        parent_final_gate=final_gate,
        dynamic_leader_plan={
            "replan_count": 1,
            "dynamic_tasks": [{"task_id": "worker-recheck"}],
        },
        capa_report=capa_report,
        child_task=child_task,
        child_final_gate=child_gate,
    )

    t4 = replay.steps[4]
    assert replay.current_step_id == "T4"
    assert replay.child_task_id == child_task.task_id
    assert t4.status == "BLOCKED"
    assert t4.finding_count == 4
    assert t4.work_order_count == 13
    assert t4.responsibility_closed == 9
    assert t4.responsibility_open == 4
    assert t4.responsibility_closed + t4.responsibility_open == t4.work_order_count
    assert t4.finding_count != t4.work_order_count
    assert t4.regressed_atomic_finding_count == 0
    assert t4.evidence_digests["child_evidence_sha256"] == child_task.evidence_sha256
    assert t4.evidence_digests["responsibility_queue_sha256"] == (
        capa_report.final_queue.queue_sha256 if capa_report.final_queue else None
    )
    assert {t4.finding_count, t4.work_order_count}.isdisjoint(MAGIC_DEMO_COUNTS)

    assert capa_report.recovery is not None
    missing_verification = capa_report.model_copy(
        update={
            "recovery": capa_report.recovery.model_copy(
                update={"child_verification": None}
            )
        }
    )
    with pytest.raises(ValueError, match="zero-regression verification"):
        build_causal_replay_report(
            parent_task=parent_task,
            parent_initial_gate=initial_gate,
            parent_final_gate=final_gate,
            dynamic_leader_plan={"replan_count": 0, "dynamic_tasks": []},
            capa_report=missing_verification,
            child_task=child_task,
            child_final_gate=child_gate,
        )

    drifted_counts = capa_report.model_copy(
        update={
            "recovery": capa_report.recovery.model_copy(
                update={"remaining_work_order_count": 3}
            )
        }
    )
    with pytest.raises(ValueError, match="responsibility counts drifted"):
        build_causal_replay_report(
            parent_task=parent_task,
            parent_initial_gate=initial_gate,
            parent_final_gate=final_gate,
            dynamic_leader_plan={"replan_count": 0, "dynamic_tasks": []},
            capa_report=drifted_counts,
            child_task=child_task,
            child_final_gate=child_gate,
        )
