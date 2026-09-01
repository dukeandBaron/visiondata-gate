"""Read-only T0-T4 replay projection over verified product evidence.

The projection is deliberately built from immutable Gate ZIP members and
hash-sealed CAPA records.  It is not an event-sourcing replacement and never
turns a missing stage into a successful one.
"""

from __future__ import annotations

import hashlib
import hmac
from typing import Any, Literal

from pydantic import Field, model_validator

from .capa import CapaCaseReport, ResponsibilityStatus
from .contracts import GateResult
from .evidence import canonical_json_bytes
from .product_models import ProductModel, TaskRecord


class CausalReplayStep(ProductModel):
    step_id: Literal["T0", "T1", "T2", "T3", "T4"]
    sequence: int = Field(ge=0, le=4)
    label: str
    status: Literal["COMPLETED", "PENDING", "BLOCKED"]
    occurred: bool
    actor: str
    decision: str | None = None
    finding_count: int | None = Field(default=None, ge=0)
    work_order_count: int | None = Field(default=None, ge=0)
    responsibility_closed: int | None = Field(default=None, ge=0)
    responsibility_open: int | None = Field(default=None, ge=0)
    dynamic_worker_count: int | None = Field(default=None, ge=0)
    regressed_atomic_finding_count: int | None = Field(default=None, ge=0)
    evidence_refs: list[str] = Field(min_length=1)
    evidence_digests: dict[str, str]
    summary: str
    source_scope: Literal["SHA_VERIFIED_LOCAL_PRODUCT_EVIDENCE"] = (
        "SHA_VERIFIED_LOCAL_PRODUCT_EVIDENCE"
    )


class CausalReplayReport(ProductModel):
    schema_version: Literal["visiondata-gate.causal-replay.v1"] = (
        "visiondata-gate.causal-replay.v1"
    )
    parent_task_id: str
    capa_case_id: str
    child_task_id: str | None = None
    current_step_id: Literal["T0", "T1", "T2", "T3", "T4"]
    steps: list[CausalReplayStep] = Field(min_length=5, max_length=5)
    read_only: Literal[True] = True
    production_release_allowed: Literal[False] = False
    report_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    claim_boundary: str = (
        "This report replays observable, hash-bound product states. Finding counts and "
        "responsibility counts keep their own denominators. It does not expose private "
        "reasoning, prove root cause, or authorize production release."
    )

    @model_validator(mode="after")
    def validate_report_sha256(self) -> CausalReplayReport:
        payload = self.model_dump(mode="json", exclude={"report_sha256"})
        observed = hashlib.sha256(canonical_json_bytes(payload)).hexdigest()
        if not hmac.compare_digest(observed, self.report_sha256):
            raise ValueError("causal replay report seal mismatch")
        return self


def _digest(value: object) -> str:
    return hashlib.sha256(canonical_json_bytes(value)).hexdigest()


def _dynamic_tasks(leader_plan: dict[str, Any]) -> list[dict[str, Any]]:
    raw = leader_plan.get("dynamic_tasks", [])
    if not isinstance(raw, list) or any(not isinstance(item, dict) for item in raw):
        raise ValueError("dynamic leader plan has an invalid task list")
    return raw


def build_causal_replay_report(
    *,
    parent_task: TaskRecord,
    parent_initial_gate: GateResult,
    parent_final_gate: GateResult,
    dynamic_leader_plan: dict[str, Any],
    capa_report: CapaCaseReport,
    child_task: TaskRecord | None = None,
    child_final_gate: GateResult | None = None,
) -> CausalReplayReport:
    """Build five observable stages without inventing unavailable measurements."""

    if capa_report.parent_task_id != parent_task.task_id:
        raise ValueError("CAPA replay parent task binding failed")
    if capa_report.selection.parent_task_id != parent_task.task_id:
        raise ValueError("CAPA replay selection binding failed")
    if parent_initial_gate.contract_id != parent_final_gate.contract_id:
        raise ValueError("parent Gate contract drifted between replay stages")
    tasks = _dynamic_tasks(dynamic_leader_plan)
    parent_evidence_sha256 = parent_task.evidence_sha256
    if parent_evidence_sha256 is None:
        raise ValueError("causal replay requires sealed parent evidence")

    t0 = CausalReplayStep(
        step_id="T0",
        sequence=0,
        label="批次送检与合同冻结",
        status="COMPLETED",
        occurred=True,
        actor="Source Authorization Gate",
        finding_count=None,
        evidence_refs=["task.request", "task.request_sha256"],
        evidence_digests={"request_sha256": parent_task.request_sha256},
        summary="任务与只读来源已登记；此时尚未执行测量，finding 数为 NOT_EVALUATED。",
    )
    t1 = CausalReplayStep(
        step_id="T1",
        sequence=1,
        label="首轮确定性扫描",
        status="COMPLETED",
        occurred=True,
        actor="Deterministic Tool Gateway",
        decision=parent_initial_gate.decision.value,
        finding_count=len(parent_initial_gate.findings),
        work_order_count=len(parent_initial_gate.work_orders),
        dynamic_worker_count=0,
        evidence_refs=["initial/gate_result.json", "initial.tool_trace"],
        evidence_digests={
            "parent_evidence_sha256": parent_evidence_sha256,
            "initial_input_sha256": parent_initial_gate.input_sha256,
            "initial_gate_sha256": _digest(parent_initial_gate),
        },
        summary=(
            f"{len(parent_initial_gate.tool_trace)} 个首轮 ToolTrace 产生 "
            f"{len(parent_initial_gate.findings)} 条 finding；裁决为 "
            f"{parent_initial_gate.decision.value}。"
        ),
    )
    replan_count = int(dynamic_leader_plan.get("replan_count", bool(tasks)))
    t2 = CausalReplayStep(
        step_id="T2",
        sequence=2,
        label="证据触发动态补证",
        status="COMPLETED",
        occurred=True,
        actor="Dynamic Leader",
        decision=parent_final_gate.decision.value,
        finding_count=len(parent_final_gate.findings),
        work_order_count=len(parent_final_gate.work_orders),
        dynamic_worker_count=len(tasks),
        evidence_refs=["dynamic_leader_plan.json", "final/gate_result.json"],
        evidence_digests={
            "parent_evidence_sha256": parent_evidence_sha256,
            "final_input_sha256": parent_final_gate.input_sha256,
            "final_gate_sha256": _digest(parent_final_gate),
            "dynamic_plan_sha256": _digest(dynamic_leader_plan),
        },
        summary=(
            f"中间证据触发 {replan_count} 次 replan、{len(tasks)} 个受限 Worker；"
            f"补证后 finding 数为 {len(parent_final_gate.findings)}。"
        ),
    )

    approval = capa_report.approval
    execution = capa_report.execution
    t3_refs = ["capa.selection", "capa.responsibility_queue.initial"]
    t3_digests = {
        "selection_sha256": capa_report.selection.selection_sha256,
        "initial_queue_sha256": capa_report.initial_queue.queue_sha256,
    }
    if approval is not None:
        t3_refs.append("capa.approval")
        t3_digests["approval_binding_sha256"] = approval.binding_sha256
    if capa_report.derived_version is not None:
        t3_refs.append("capa.derived_version")
        t3_digests["derived_version_receipt_sha256"] = (
            capa_report.derived_version.receipt_sha256
        )
    if execution is not None:
        t3_refs.append("capa.execution")
        t3_digests["execution_receipt_sha256"] = execution.receipt_sha256
    t3 = CausalReplayStep(
        step_id="T3",
        sequence=3,
        label="具名人工 CAPA 与私有派生",
        status="COMPLETED" if execution is not None else "PENDING",
        occurred=True,
        actor="Named Quality Owner",
        decision=(
            "DERIVED_EXECUTION_COMPLETED"
            if execution is not None
            else "HUMAN_APPROVED"
            if approval is not None
            else "PLAN_SELECTED_AWAITING_APPROVAL"
        ),
        finding_count=None,
        work_order_count=len(capa_report.initial_queue.items),
        responsibility_closed=0,
        responsibility_open=capa_report.initial_queue.open_count,
        evidence_refs=t3_refs,
        evidence_digests=t3_digests,
        summary=("CAPA 只改变私有派生版本和责任状态，不把整改动作伪装成一次新测量。"),
    )

    recovery = capa_report.recovery
    final_queue = capa_report.final_queue
    if recovery is None:
        if (
            child_task is not None
            or child_final_gate is not None
            or final_queue is not None
        ):
            raise ValueError("partial child replay artifacts are inconsistent")
        t4 = CausalReplayStep(
            step_id="T4",
            sequence=4,
            label="Child Run 同合同复验",
            status="PENDING",
            occurred=False,
            actor="Policy Judge",
            evidence_refs=["capa.recovery:pending"],
            evidence_digests={},
            summary=(
                "尚无完成且通过哈希完整性校验的 Child Run；"
                "不展示推测性 finding 或关闭数量。"
            ),
        )
        child_task_id = None
        current_step = "T3"
    else:
        if child_task is None or child_final_gate is None or final_queue is None:
            raise ValueError("completed CAPA replay requires child evidence and queue")
        if recovery.child_task_id != child_task.task_id:
            raise ValueError("CAPA replay child task binding failed")
        if child_task.evidence_sha256 != recovery.child_evidence_sha256:
            raise ValueError("CAPA replay child evidence binding failed")
        if child_final_gate.contract_id != parent_final_gate.contract_id:
            raise ValueError("CAPA replay child Gate contract drifted")
        if (
            child_final_gate.decision.value != recovery.child_decision
            or len(child_final_gate.findings) != recovery.child_finding_count
        ):
            raise ValueError("CAPA replay child Gate summary drifted")
        verification = recovery.child_verification
        if verification is None:
            raise ValueError(
                "CAPA replay requires an atomic zero-regression verification"
            )
        if (
            recovery.parent_decision != parent_final_gate.decision.value
            or recovery.parent_finding_count != len(parent_final_gate.findings)
        ):
            raise ValueError("CAPA replay parent Gate summary drifted")
        if (
            verification.parent_contract_id != parent_final_gate.contract_id
            or verification.child_contract_id != child_final_gate.contract_id
            or verification.parent_evidence_sha256 != recovery.parent_evidence_sha256
            or verification.child_evidence_sha256 != recovery.child_evidence_sha256
        ):
            raise ValueError("CAPA replay zero-regression binding drifted")
        selected_count = sum(item.selected for item in final_queue.items)
        verified_closed_count = sum(
            item.selected and item.status is ResponsibilityStatus.VERIFIED_CLOSED
            for item in final_queue.items
        )
        if (
            final_queue.open_count + final_queue.closed_count != len(final_queue.items)
            or recovery.selected_work_order_count != selected_count
            or recovery.verified_closed_work_order_count != verified_closed_count
            or recovery.remaining_work_order_count != final_queue.open_count
        ):
            raise ValueError("CAPA replay responsibility counts drifted")
        expected_recovery_success = (
            child_final_gate.decision.value == "PASS"
            and final_queue.open_count == 0
            and verification.is_zero_regression
        )
        if recovery.recovery_success != expected_recovery_success:
            raise ValueError("CAPA replay recovery status drifted")
        t4 = CausalReplayStep(
            step_id="T4",
            sequence=4,
            label="Child Run 同合同复验",
            status=("COMPLETED" if recovery.recovery_success else "BLOCKED"),
            occurred=True,
            actor="Policy Judge",
            decision=recovery.status,
            finding_count=recovery.child_finding_count,
            work_order_count=len(final_queue.items),
            responsibility_closed=recovery.verified_closed_work_order_count,
            responsibility_open=recovery.remaining_work_order_count,
            regressed_atomic_finding_count=verification.regressed_count,
            evidence_refs=[
                "child/final/gate_result.json",
                "capa.responsibility_queue.final",
                "capa.recovery",
                "task.lineage",
            ],
            evidence_digests={
                "child_evidence_sha256": recovery.child_evidence_sha256,
                "child_gate_sha256": _digest(child_final_gate),
                "recovery_receipt_sha256": recovery.receipt_sha256,
                "responsibility_queue_sha256": final_queue.queue_sha256,
                "child_verification_sha256": verification.verification_sha256,
            },
            summary=(
                f"Child Run 观察到 {recovery.child_finding_count} 条 finding；"
                f"责任项关闭 {recovery.verified_closed_work_order_count}、"
                f"仍开 {recovery.remaining_work_order_count}。"
            ),
        )
        child_task_id = child_task.task_id
        current_step = "T4"

    stable = {
        "schema_version": "visiondata-gate.causal-replay.v1",
        "parent_task_id": parent_task.task_id,
        "capa_case_id": capa_report.case_id,
        "child_task_id": child_task_id,
        "current_step_id": current_step,
        "steps": [t0, t1, t2, t3, t4],
        "read_only": True,
        "production_release_allowed": False,
        "claim_boundary": CausalReplayReport.model_fields["claim_boundary"].default,
    }
    return CausalReplayReport(
        **stable,
        report_sha256=_digest(stable),
    )


__all__ = [
    "CausalReplayReport",
    "CausalReplayStep",
    "build_causal_replay_report",
]
