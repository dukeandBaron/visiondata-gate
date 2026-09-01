"""Normalized product-run envelopes for synthetic and authorized real-data tasks."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
import hashlib
import hmac
import json
from pathlib import Path
import shutil
from typing import Callable, Literal

from pydantic import Field

from .agent_core import (
    AgentCoreExecutionReceipt,
    AgentRuntimeSignal,
    build_agent_core_execution_receipt,
    verify_agent_core_execution_receipt,
)
from .agent_runtime import AgenticDemoRun
from .agents import build_council
from .contracts import (
    BatchContract,
    BatchManifest,
    Finding,
    GateDecision,
    GateResult,
    ToolTrace,
)
from .evidence import (
    canonical_json_bytes,
    sha256_file,
    write_canonical_json,
    write_evidence_artifacts,
)
from .omni_adapter import run_omni_readonly_gate
from .operator_snapshot import (
    OperatorProjectSnapshotReceipt,
    profile_operator_project_snapshot,
)
from .pipeline import compute_batch_digest
from .policy import apply_policy
from .product_models import (
    LocalSourceAdapterKind,
    LocalSourceAuthorizationReceipt,
    ProductModel,
)
from .runtime_models import (
    AgentTask,
    ApprovalHandoff,
    MemorySnapshot,
    RuntimeConfig,
    RuntimeEvent,
    RuntimeStage,
    RuntimeStatus,
    RuntimeTrace,
    ScenarioProfile,
)
from .tools import run_tool, tool_catalog


_KERNEL_RECEIPT_NAME = "product_kernel_run_receipt.json"

SYNTHETIC_CORE_EVIDENCE = (
    "agent_runtime_trace.json",
    "demo_summary.json",
    "proof_index.json",
    "claim_scope_receipt.json",
    "llm_grounding_receipt.json",
    "model_transport_receipt.json",
    "prompt_injection_runtime_receipt.json",
    "backend_identity_runtime_receipt.json",
    "acceptance_scorecard.json",
    "initial/gate_result.json",
    "initial/evidence_matrix.csv",
    "repaired/gate_result.json",
    "repaired/evidence_matrix.csv",
)
SYNTHETIC_REQUIRED_EVIDENCE = (*SYNTHETIC_CORE_EVIDENCE, _KERNEL_RECEIPT_NAME)

OMNI_CORE_EVIDENCE = (
    "agent_runtime_trace.json",
    "agent_core_execution_receipt.json",
    "task_summary.json",
    "claim_scope_receipt.json",
    "local_source_authorization_receipt.json",
    "source_profile.json",
    "initial/gate_result.json",
    "final/gate_result.json",
    "gate_result.json",
    "dynamic_leader_plan.json",
    "omni_gate_receipt.json",
    "evidence_matrix.csv",
    "findings.csv",
)
OMNI_REQUIRED_EVIDENCE = (*OMNI_CORE_EVIDENCE, _KERNEL_RECEIPT_NAME)

OPERATOR_SNAPSHOT_CORE_EVIDENCE = (
    "agent_runtime_trace.json",
    "agent_core_execution_receipt.json",
    "task_summary.json",
    "claim_scope_receipt.json",
    "local_source_authorization_receipt.json",
    "source_profile.json",
    "operator_project_snapshot_receipt.json",
    "initial/gate_result.json",
    "final/gate_result.json",
    "gate_result.json",
    "dynamic_leader_plan.json",
    "operator_snapshot_gate_receipt.json",
    "evidence_matrix.csv",
    "findings.csv",
)
OPERATOR_SNAPSHOT_REQUIRED_EVIDENCE = (
    *OPERATOR_SNAPSHOT_CORE_EVIDENCE,
    _KERNEL_RECEIPT_NAME,
)


class ProductKernelRunReceipt(ProductModel):
    """Semantic completion contract between an Agent runtime and ProductService."""

    schema_version: Literal[
        "visiondata-gate.product-kernel-run.v1",
        "visiondata-gate.product-kernel-run.v2",
    ] = "visiondata-gate.product-kernel-run.v2"
    runtime_kind: Literal[
        "synthetic_demo",
        "authorized_local_readonly",
        "operator_project_snapshot",
    ]
    run_id: str = Field(min_length=1)
    runtime_status: RuntimeStatus
    initial_decision: GateDecision
    final_decision: GateDecision
    runtime_trace_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    initial_gate_result_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    final_gate_result_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    event_count: int = Field(ge=1)
    tool_call_count: int = Field(ge=0)
    required_artifact_sha256: dict[str, str] = Field(min_length=1)
    completion_contract: Literal["TYPED_RUNTIME_AND_GATE_RESULTS_VERIFIED"] = (
        "TYPED_RUNTIME_AND_GATE_RESULTS_VERIFIED"
    )
    receipt_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")


@dataclass(frozen=True)
class ProductTaskRun:
    """Source-agnostic result consumed by the product lifecycle service."""

    evidence_dir: Path
    runtime_trace_path: Path
    initial_decision: GateDecision
    final_decision: GateDecision
    runtime_status: RuntimeStatus
    events: tuple[RuntimeEvent, ...]
    required_evidence_paths: tuple[str, ...]
    kernel_receipt: ProductKernelRunReceipt
    kernel_receipt_path: Path


def _load_typed_gate_result(path: Path) -> GateResult:
    try:
        return GateResult.model_validate_json(path.read_bytes())
    except (OSError, ValueError) as error:
        raise ValueError(f"kernel GateResult is invalid: {path.name}") from error


def _kernel_artifact_hashes(
    evidence_dir: Path, required_paths: tuple[str, ...]
) -> dict[str, str]:
    root = evidence_dir.resolve(strict=True)
    hashes: dict[str, str] = {}
    for relative in required_paths:
        candidate = (root / relative).resolve(strict=True)
        try:
            candidate.relative_to(root)
        except ValueError as error:
            raise ValueError("kernel evidence path escaped evidence root") from error
        if not candidate.is_file():
            raise ValueError(f"kernel evidence artifact is not a file: {relative}")
        hashes[relative] = sha256_file(candidate)
    return hashes


def _build_product_kernel_receipt(
    *,
    runtime_kind: Literal[
        "synthetic_demo",
        "authorized_local_readonly",
        "operator_project_snapshot",
    ],
    evidence_dir: Path,
    runtime_trace_path: Path,
    initial_gate_result_path: Path,
    final_gate_result_path: Path,
    required_core_paths: tuple[str, ...],
) -> ProductKernelRunReceipt:
    trace = RuntimeTrace.model_validate_json(runtime_trace_path.read_bytes())
    initial = _load_typed_gate_result(initial_gate_result_path)
    final = _load_typed_gate_result(final_gate_result_path)
    stable = {
        "schema_version": "visiondata-gate.product-kernel-run.v2",
        "runtime_kind": runtime_kind,
        "run_id": trace.run_id,
        "runtime_status": trace.status,
        "initial_decision": initial.decision,
        "final_decision": final.decision,
        "runtime_trace_sha256": sha256_file(runtime_trace_path),
        "initial_gate_result_sha256": sha256_file(initial_gate_result_path),
        "final_gate_result_sha256": sha256_file(final_gate_result_path),
        "event_count": len(trace.events),
        "tool_call_count": trace.tool_call_count,
        "required_artifact_sha256": _kernel_artifact_hashes(
            evidence_dir, required_core_paths
        ),
        "completion_contract": "TYPED_RUNTIME_AND_GATE_RESULTS_VERIFIED",
    }
    return ProductKernelRunReceipt(
        **stable,
        receipt_sha256=hashlib.sha256(canonical_json_bytes(stable)).hexdigest(),
    )


def _write_product_kernel_receipt(
    *,
    runtime_kind: Literal[
        "synthetic_demo",
        "authorized_local_readonly",
        "operator_project_snapshot",
    ],
    evidence_dir: Path,
    runtime_trace_path: Path,
    initial_gate_result_path: Path,
    final_gate_result_path: Path,
    required_core_paths: tuple[str, ...],
) -> tuple[ProductKernelRunReceipt, Path]:
    receipt = _build_product_kernel_receipt(
        runtime_kind=runtime_kind,
        evidence_dir=evidence_dir,
        runtime_trace_path=runtime_trace_path,
        initial_gate_result_path=initial_gate_result_path,
        final_gate_result_path=final_gate_result_path,
        required_core_paths=required_core_paths,
    )
    path = evidence_dir / _KERNEL_RECEIPT_NAME
    write_canonical_json(path, receipt)
    return receipt, path


def seal_product_task_run(
    *,
    runtime_kind: Literal[
        "synthetic_demo",
        "authorized_local_readonly",
        "operator_project_snapshot",
    ],
    evidence_dir: str | Path,
    runtime_trace_path: str | Path,
    initial_gate_result_path: str | Path,
    final_gate_result_path: str | Path,
) -> ProductTaskRun:
    """Seal one adapter result against the fixed production completion contract."""

    root = Path(evidence_dir).expanduser().resolve(strict=True)
    trace_path = Path(runtime_trace_path).expanduser().resolve(strict=True)
    initial_path = Path(initial_gate_result_path).expanduser().resolve(strict=True)
    final_path = Path(final_gate_result_path).expanduser().resolve(strict=True)
    required_core_paths_by_runtime = {
        "synthetic_demo": SYNTHETIC_CORE_EVIDENCE,
        "authorized_local_readonly": OMNI_CORE_EVIDENCE,
        "operator_project_snapshot": OPERATOR_SNAPSHOT_CORE_EVIDENCE,
    }
    required_paths_by_runtime = {
        "synthetic_demo": SYNTHETIC_REQUIRED_EVIDENCE,
        "authorized_local_readonly": OMNI_REQUIRED_EVIDENCE,
        "operator_project_snapshot": OPERATOR_SNAPSHOT_REQUIRED_EVIDENCE,
    }
    required_core_paths = required_core_paths_by_runtime[runtime_kind]
    required_paths = required_paths_by_runtime[runtime_kind]
    receipt, receipt_path = _write_product_kernel_receipt(
        runtime_kind=runtime_kind,
        evidence_dir=root,
        runtime_trace_path=trace_path,
        initial_gate_result_path=initial_path,
        final_gate_result_path=final_path,
        required_core_paths=required_core_paths,
    )
    trace = RuntimeTrace.model_validate_json(trace_path.read_bytes())
    initial = _load_typed_gate_result(initial_path)
    final = _load_typed_gate_result(final_path)
    sealed = ProductTaskRun(
        evidence_dir=root,
        runtime_trace_path=trace_path,
        initial_decision=initial.decision,
        final_decision=final.decision,
        runtime_status=trace.status,
        events=tuple(trace.events),
        required_evidence_paths=required_paths,
        kernel_receipt=receipt,
        kernel_receipt_path=receipt_path,
    )
    verify_product_task_run(sealed)
    return sealed


def normalize_agentic_run(run: AgenticDemoRun) -> ProductTaskRun:
    """Adapt only a real typed ``AgenticDemoRun`` into the product contract."""

    if not isinstance(run, AgenticDemoRun):
        raise TypeError("synthetic product runner must return AgenticDemoRun")
    return seal_product_task_run(
        runtime_kind="synthetic_demo",
        evidence_dir=run.evidence_dir,
        runtime_trace_path=run.runtime_trace_path,
        initial_gate_result_path=run.evidence_dir / "initial" / "gate_result.json",
        final_gate_result_path=run.evidence_dir / "repaired" / "gate_result.json",
    )


_DYNAMIC_TASK_RUNTIME_STATUS = {
    "completed": RuntimeStatus.SUCCESS,
    "skipped": RuntimeStatus.WARNING,
    "deferred": RuntimeStatus.WARNING,
    "failed": RuntimeStatus.ERROR,
    "budget_exhausted": RuntimeStatus.ERROR,
}


def _verified_dynamic_task_binding(
    item: object,
) -> tuple[str, str, str, RuntimeStatus, list[str], str]:
    """Return one typed plan-to-event binding or reject the plan item."""

    if not isinstance(item, dict):
        raise ValueError("authorized dynamic task must be an object")

    task_id = item.get("task_id")
    worker_id = item.get("worker_id")
    raw_status = item.get("status")
    input_refs = item.get("input_refs")
    result_sha256 = item.get("result_sha256")
    trace_result_sha256 = item.get("tool_trace_result_sha256")
    tool_trace_ref = item.get("tool_trace_ref")
    if not isinstance(task_id, str) or not task_id:
        raise ValueError("authorized dynamic task has invalid task_id")
    if not isinstance(worker_id, str) or not worker_id:
        raise ValueError("authorized dynamic task has invalid worker_id")
    if (
        not isinstance(raw_status, str)
        or raw_status not in _DYNAMIC_TASK_RUNTIME_STATUS
    ):
        raise ValueError("authorized dynamic task has invalid status")
    if (
        not isinstance(input_refs, list)
        or any(
            not isinstance(reference, str) or not reference for reference in input_refs
        )
        or len(input_refs) != len(set(input_refs))
    ):
        raise ValueError("authorized dynamic task has invalid input_refs")
    if not (
        isinstance(result_sha256, str)
        and len(result_sha256) == 64
        and all(character in "0123456789abcdef" for character in result_sha256)
        and trace_result_sha256 == result_sha256
    ):
        raise ValueError("authorized dynamic task has invalid result SHA-256 binding")
    if not isinstance(tool_trace_ref, str):
        raise ValueError("authorized dynamic task has invalid tool trace reference")
    trace_parts = tool_trace_ref.split(":")
    if not (
        len(trace_parts) == 3
        and trace_parts[0] == "trace"
        and trace_parts[1].isdigit()
        and int(trace_parts[1]) >= 1
        and trace_parts[2]
    ):
        raise ValueError("authorized dynamic task has invalid tool trace reference")
    tool_name = trace_parts[2]
    explicit_tool_name = item.get("tool_name")
    if explicit_tool_name is not None and explicit_tool_name != tool_name:
        raise ValueError("authorized dynamic task tool_name drifted from tool trace")
    return (
        task_id,
        worker_id,
        tool_name,
        _DYNAMIC_TASK_RUNTIME_STATUS[raw_status],
        input_refs,
        result_sha256,
    )


def _verify_dynamic_task_event_bindings(
    dynamic_tasks: Sequence[object],
    events: Sequence[RuntimeEvent],
) -> None:
    """Bind every Dynamic Leader task to its live verification Tool event."""

    expected_by_task: dict[str, tuple[str, str, RuntimeStatus, list[str], str]] = {}
    for item in dynamic_tasks:
        task_id, worker_id, tool_name, status, input_refs, result_sha256 = (
            _verified_dynamic_task_binding(item)
        )
        if task_id in expected_by_task:
            raise ValueError("authorized dynamic plan contains duplicate task_id")
        expected_by_task[task_id] = (
            worker_id,
            tool_name,
            status,
            input_refs,
            result_sha256,
        )

    events_by_task: dict[str, list[RuntimeEvent]] = {}
    for event in events:
        if event.phase != "verification" or event.stage is not RuntimeStage.TOOL:
            continue
        if not event.task_id:
            raise ValueError("authorized dynamic Tool event has no task_id")
        events_by_task.setdefault(event.task_id, []).append(event)

    if set(events_by_task) != set(expected_by_task):
        raise ValueError("authorized dynamic task IDs differ from live Tool events")

    for task_id, expected in expected_by_task.items():
        worker_id, tool_name, status, input_refs, result_sha256 = expected
        task_events = events_by_task[task_id]
        if any(
            event.actor != worker_id or event.tool_name != tool_name
            for event in task_events
        ):
            raise ValueError(
                f"authorized dynamic task identity binding mismatch: {task_id}"
            )
        terminal_event = task_events[-1]
        expected_evidence_refs = [
            *input_refs,
            f"result_sha256:{result_sha256}",
        ]
        if not (
            terminal_event.status is status
            and terminal_event.evidence_refs == expected_evidence_refs
        ):
            raise ValueError(
                f"authorized dynamic task result binding mismatch: {task_id}"
            )


def _verify_authorized_agent_core_binding(
    *,
    evidence_root: Path,
    kernel_receipt: ProductKernelRunReceipt,
    trace: RuntimeTrace,
    initial: GateResult,
    final: GateResult,
) -> None:
    """Bind the live Agent-core receipt to the typed product completion receipt."""

    core_receipt_path = evidence_root / "agent_core_execution_receipt.json"
    try:
        core_receipt = AgentCoreExecutionReceipt.model_validate_json(
            core_receipt_path.read_bytes()
        )
    except (OSError, ValueError) as error:
        raise ValueError("authorized Agent-core receipt is invalid") from error
    verify_agent_core_execution_receipt(core_receipt, events=trace.events)

    leader_plan_path = evidence_root / "dynamic_leader_plan.json"
    try:
        leader_plan = json.loads(leader_plan_path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as error:
        raise ValueError("authorized dynamic leader plan is invalid") from error
    dynamic_tasks = leader_plan.get("dynamic_tasks")
    if not isinstance(dynamic_tasks, list):
        raise ValueError("authorized dynamic leader plan has invalid tasks")
    if leader_plan.get("dynamic_task_count") != len(dynamic_tasks):
        raise ValueError("authorized dynamic leader plan task count mismatch")
    _verify_dynamic_task_event_bindings(dynamic_tasks, trace.events)

    if not (
        core_receipt.run_id == trace.run_id == kernel_receipt.run_id
        and hmac.compare_digest(
            core_receipt.runtime_trace_sha256,
            kernel_receipt.runtime_trace_sha256,
        )
        and hmac.compare_digest(
            core_receipt.initial_gate_result_sha256,
            kernel_receipt.initial_gate_result_sha256,
        )
        and hmac.compare_digest(
            core_receipt.final_gate_result_sha256,
            kernel_receipt.final_gate_result_sha256,
        )
        and hmac.compare_digest(
            core_receipt.dynamic_leader_plan_sha256,
            sha256_file(leader_plan_path),
        )
        and core_receipt.runtime_event_count == kernel_receipt.event_count
        and core_receipt.model_call_count == trace.model_call_count
        and core_receipt.tool_call_count == trace.tool_call_count
        and core_receipt.dynamic_task_count == len(dynamic_tasks)
        and core_receipt.planner_backend == str(leader_plan.get("planner"))
        and core_receipt.council_backend == final.council_trace.backend
        and initial.decision is kernel_receipt.initial_decision
        and final.decision is kernel_receipt.final_decision
    ):
        raise ValueError("authorized Agent-core receipt binding mismatch")


def verify_product_task_run(run: ProductTaskRun) -> None:
    """Verify runtime semantics before ProductService may mark a task complete."""

    evidence_root = run.evidence_dir.resolve(strict=True)
    trace_path = run.runtime_trace_path.resolve(strict=True)
    receipt_path = run.kernel_receipt_path.resolve(strict=True)
    if trace_path != evidence_root / "agent_runtime_trace.json":
        raise ValueError("kernel runtime trace is outside its canonical location")
    if receipt_path != evidence_root / _KERNEL_RECEIPT_NAME:
        raise ValueError("kernel receipt is outside its canonical location")

    persisted_receipt = ProductKernelRunReceipt.model_validate_json(
        receipt_path.read_bytes()
    )
    if persisted_receipt != run.kernel_receipt:
        raise ValueError("in-memory and persisted kernel receipts differ")
    stable = persisted_receipt.model_dump(mode="json", exclude={"receipt_sha256"})
    expected_receipt_sha256 = hashlib.sha256(canonical_json_bytes(stable)).hexdigest()
    if not hmac.compare_digest(
        expected_receipt_sha256, persisted_receipt.receipt_sha256
    ):
        raise ValueError("product kernel receipt digest mismatch")

    expected_required = {
        *persisted_receipt.required_artifact_sha256,
        _KERNEL_RECEIPT_NAME,
    }
    if set(run.required_evidence_paths) != expected_required or len(
        run.required_evidence_paths
    ) != len(expected_required):
        raise ValueError("product run required-evidence contract drifted")
    for relative, expected_sha256 in persisted_receipt.required_artifact_sha256.items():
        candidate = (evidence_root / relative).resolve(strict=True)
        try:
            candidate.relative_to(evidence_root)
        except ValueError as error:
            raise ValueError("kernel artifact escaped evidence root") from error
        if not candidate.is_file() or not hmac.compare_digest(
            sha256_file(candidate), expected_sha256
        ):
            raise ValueError(f"kernel artifact integrity failed: {relative}")

    trace = RuntimeTrace.model_validate_json(trace_path.read_bytes())
    if not (
        hmac.compare_digest(
            sha256_file(trace_path), persisted_receipt.runtime_trace_sha256
        )
        and trace.run_id == persisted_receipt.run_id
        and trace.status is persisted_receipt.runtime_status
        and len(trace.events) == persisted_receipt.event_count
        and trace.tool_call_count == persisted_receipt.tool_call_count
        and tuple(trace.events) == run.events
        and run.runtime_status is trace.status
    ):
        raise ValueError("runtime trace does not satisfy the kernel receipt")

    final_relative = (
        "repaired/gate_result.json"
        if persisted_receipt.runtime_kind == "synthetic_demo"
        else "final/gate_result.json"
    )
    initial = _load_typed_gate_result(evidence_root / "initial/gate_result.json")
    final = _load_typed_gate_result(evidence_root / final_relative)
    if not (
        hmac.compare_digest(
            sha256_file(evidence_root / "initial/gate_result.json"),
            persisted_receipt.initial_gate_result_sha256,
        )
        and hmac.compare_digest(
            sha256_file(evidence_root / final_relative),
            persisted_receipt.final_gate_result_sha256,
        )
        and initial.decision is persisted_receipt.initial_decision
        and final.decision is persisted_receipt.final_decision
        and run.initial_decision is initial.decision
        and run.final_decision is final.decision
        and initial.contract_id == final.contract_id
    ):
        raise ValueError("typed GateResult pair does not satisfy the kernel receipt")
    if persisted_receipt.runtime_kind in {
        "authorized_local_readonly",
        "operator_project_snapshot",
    }:
        _verify_authorized_agent_core_binding(
            evidence_root=evidence_root,
            kernel_receipt=persisted_receipt,
            trace=trace,
            initial=initial,
            final=final,
        )


def run_omni_product_task(
    output_dir: str | Path,
    *,
    source_root: str | Path,
    source_receipt: LocalSourceAuthorizationReceipt,
    seed: int,
    goal: str,
    config: RuntimeConfig,
    event_sink: Callable[[RuntimeEvent], None] | None = None,
    per_bucket: int = 2,
    rulepack_path: str | Path | None = None,
    expected_rulepack_source_sha256: str | None = None,
) -> ProductTaskRun:
    """Execute an authorized Omni source through the same product task lifecycle."""

    if (rulepack_path is None) != (expected_rulepack_source_sha256 is None):
        raise ValueError(
            "rulepack_path and expected_rulepack_source_sha256 must be configured "
            "together"
        )

    task_root = Path(output_dir).expanduser().resolve()
    evidence_dir = task_root / "evidence"
    events: list[RuntimeEvent] = []

    def emit(
        *,
        phase: str,
        stage: RuntimeStage,
        actor: str,
        action: str,
        status: RuntimeStatus,
        summary: str,
        task_id: str | None = None,
        tool_name: str | None = None,
        evidence_refs: list[str] | None = None,
        duration_ms: float = 0.0,
    ) -> None:
        event = RuntimeEvent(
            sequence=len(events) + 1,
            phase=phase,
            stage=stage,
            actor=actor,
            action=action,
            status=status,
            summary=summary,
            task_id=task_id,
            tool_name=tool_name,
            duration_ms=duration_ms,
            evidence_refs=evidence_refs or [],
        )
        events.append(event)
        if event_sink is not None:
            event_sink(event)

    def accept_core_signal(signal: AgentRuntimeSignal) -> None:
        emit(
            phase=signal.phase,
            stage=signal.stage,
            actor=signal.actor,
            action=signal.action,
            status=signal.status,
            summary=signal.summary,
            task_id=signal.task_id,
            tool_name=signal.tool_name,
            evidence_refs=signal.evidence_refs,
            duration_ms=signal.duration_ms,
        )

    emit(
        phase="initial",
        stage=RuntimeStage.INTAKE,
        actor="Source Authorization Gate",
        action="verify_local_source_receipt",
        status=RuntimeStatus.SUCCESS,
        summary="已验证只读来源授权回执与服务器允许目录。",
        evidence_refs=[f"source:{source_receipt.source_id}"],
    )
    run = run_omni_readonly_gate(
        source_root,
        evidence_dir,
        source_archive_sha256=source_receipt.source_archive_sha256,
        per_bucket=per_bucket,
        seed=seed,
        rulepack_path=rulepack_path,
        agent_signal_sink=accept_core_signal,
    )
    leader_plan = json.loads(run.leader_plan_path.read_text(encoding="utf-8"))
    if rulepack_path is not None:
        assert expected_rulepack_source_sha256 is not None
        resolved_rulepack = Path(rulepack_path).expanduser().resolve(strict=True)
        current_rulepack_source_sha256 = sha256_file(resolved_rulepack)
        if not (
            leader_plan.get("rule_pack_source_sha256")
            == expected_rulepack_source_sha256
            == current_rulepack_source_sha256
        ):
            raise ValueError(
                "Omni Rule Pack source drifted during ProductService task execution"
            )
    write_canonical_json(
        evidence_dir / "initial" / "gate_result.json", run.initial_result
    )
    write_canonical_json(evidence_dir / "final" / "gate_result.json", run.gate_result)
    write_canonical_json(
        evidence_dir / "local_source_authorization_receipt.json", source_receipt
    )
    write_canonical_json(
        evidence_dir / "source_profile.json", source_receipt.data_profile
    )
    write_canonical_json(
        evidence_dir / "claim_scope_receipt.json",
        {
            "schema_version": "visiondata-gate.real-data-claim-scope.v1",
            "source_kind": source_receipt.source_kind.value,
            "adapter_kind": source_receipt.adapter_kind.value,
            "real_source_bytes_read": True,
            "source_assets_copied_into_product": (
                source_receipt.source_assets_copied_into_product
            ),
            "derived_version_id": source_receipt.derived_version_id,
            "derived_from_source_id": source_receipt.derived_from_source_id,
            "customer_acceptance": "NOT_AVAILABLE",
            "factory_deployment": "NOT_AVAILABLE",
            "production_approval": "NOT_AVAILABLE",
            "raw_redistribution": "FORBIDDEN_BY_PRODUCT_CONTRACT",
            "boundary": (
                "The run proves a bounded read-only gate on an authorized local source. "
                "It is not complete dataset certification or a production safety decision."
            ),
        },
    )
    write_canonical_json(
        evidence_dir / "task_summary.json",
        {
            "schema_version": "visiondata-gate.product-omni-task.v1",
            "source_id": source_receipt.source_id,
            "source_profile_sha256": source_receipt.data_profile["profile_sha256"],
            "initial_decision": run.initial_result.decision.value,
            "final_decision": run.gate_result.decision.value,
            "static_tool_count": len(run.initial_result.tool_trace),
            "final_tool_trace_count": len(run.gate_result.tool_trace),
            "dynamic_task_count": int(leader_plan["dynamic_task_count"]),
            "replan_count": int(leader_plan["replan_count"]),
            "agent_core_signal_capture": "LIVE_CORE_SIGNALS",
            "posthoc_event_synthesis": False,
            "runtime_trace_materialization": "POST_EXECUTION_FROM_LIVE_SIGNALS",
            "planner_backend": str(leader_plan["planner"]),
            "council_backend": run.gate_result.council_trace.backend,
            "model_call_count": 0,
            "finding_count": len(run.gate_result.findings),
            "work_order_count": len(run.gate_result.work_orders),
            "raw_source_path_serialized": False,
        },
    )

    static_tasks = [
        AgentTask(
            task_id=f"tool.{trace.tool}",
            title=f"执行 {trace.tool}",
            stage=RuntimeStage.TOOL,
            actor=f"worker.{trace.tool}",
            capability="read_only_measurement",
            permission_scope=["authorized_source:read"],
            status=(
                RuntimeStatus.SUCCESS if trace.status == "ok" else RuntimeStatus.ERROR
            ),
            output_refs=[f"trace:{trace.sequence}:{trace.result_sha256}"],
        )
        for trace in run.initial_result.tool_trace
    ]
    static_task_ids = {task.task_id for task in static_tasks}
    dynamic_tasks: list[AgentTask] = []
    for item in leader_plan["dynamic_tasks"]:
        dependencies = {"plan.dynamic-followups"}
        for reference in item["input_refs"]:
            parts = str(reference).split(":")
            if len(parts) >= 3 and parts[0] == "trace":
                candidate = f"tool.{parts[2]}"
                if candidate in static_task_ids:
                    dependencies.add(candidate)
        raw_status = str(item["status"])
        task_status = (
            RuntimeStatus.SUCCESS
            if raw_status == "completed"
            else RuntimeStatus.WARNING
            if raw_status in {"skipped", "deferred"}
            else RuntimeStatus.ERROR
        )
        dynamic_tasks.append(
            AgentTask(
                task_id=str(item["task_id"]),
                title=str(item["trigger"]),
                stage=RuntimeStage.TOOL,
                actor=str(item["worker_id"]),
                dependencies=sorted(dependencies),
                capability="evidence_followup",
                permission_scope=["authorized_source:read", "evidence:append"],
                status=task_status,
                output_refs=[f"sha256:{item['result_sha256']}"],
            )
        )
    dynamic_task_ids = [task.task_id for task in dynamic_tasks]
    control_tasks = [
        AgentTask(
            task_id="intake.authorized-source",
            title="冻结授权来源与只读抽样清单",
            stage=RuntimeStage.INTAKE,
            actor="authorized-source-intake",
            capability="source_authorization_and_snapshot_binding",
            permission_scope=["authorized_source:read"],
            status=RuntimeStatus.SUCCESS,
            output_refs=[f"source:{source_receipt.source_id}"],
        ),
        AgentTask(
            task_id="plan.initial-evidence",
            title="规划首轮确定性证据工具",
            stage=RuntimeStage.PLANNER,
            actor="deterministic-leader",
            dependencies=["intake.authorized-source"],
            capability="bounded_evidence_planning",
            permission_scope=["tool_registry:read"],
            status=RuntimeStatus.SUCCESS,
            output_refs=["plan:initial-evidence"],
        ),
        *[
            task.model_copy(update={"dependencies": ["plan.initial-evidence"]})
            for task in static_tasks
        ],
        AgentTask(
            task_id="council.initial-evidence",
            title="解释并交叉质询首轮证据",
            stage=RuntimeStage.COUNCIL,
            actor="deterministic-evidence-council",
            dependencies=sorted(static_task_ids),
            capability="typed_evidence_interpretation",
            permission_scope=["evidence:read"],
            status=RuntimeStatus.SUCCESS,
            output_refs=[f"council:{run.initial_result.council_trace.backend}"],
        ),
        AgentTask(
            task_id="judge.initial",
            title="签发首轮冻结策略裁决",
            stage=RuntimeStage.JUDGE,
            actor="frozen-policy-judge",
            dependencies=["council.initial-evidence"],
            capability="frozen_policy_evaluation",
            permission_scope=["gate_decision:write"],
            status=RuntimeStatus.SUCCESS,
            output_refs=["initial/gate_result.json"],
        ),
        AgentTask(
            task_id="plan.dynamic-followups",
            title="按中间证据和预算规划动态补证",
            stage=RuntimeStage.PLANNER,
            actor="dynamic-leader",
            dependencies=["judge.initial"],
            capability="evidence_triggered_replanning",
            permission_scope=["tool_registry:read", "evidence:read"],
            status=RuntimeStatus.SUCCESS,
            output_refs=["dynamic_leader_plan.json"],
        ),
        *dynamic_tasks,
        AgentTask(
            task_id="council.verification",
            title="复核首轮与动态补证证据",
            stage=RuntimeStage.COUNCIL,
            actor="deterministic-evidence-council",
            dependencies=(dynamic_task_ids or ["plan.dynamic-followups"]),
            capability="typed_evidence_interpretation",
            permission_scope=["evidence:read"],
            status=RuntimeStatus.SUCCESS,
            output_refs=[f"council:{run.gate_result.council_trace.backend}"],
        ),
        AgentTask(
            task_id="judge.final",
            title="签发最终冻结策略裁决",
            stage=RuntimeStage.JUDGE,
            actor="frozen-policy-judge",
            dependencies=["council.verification"],
            capability="frozen_policy_evaluation",
            permission_scope=["gate_decision:write"],
            status=RuntimeStatus.SUCCESS,
            output_refs=["gate_result.json"],
        ),
        AgentTask(
            task_id="delivery.gate-evidence",
            title="封存脱敏证据与运行回执",
            stage=RuntimeStage.DELIVERY,
            actor="evidence-delivery",
            dependencies=["judge.final"],
            capability="canonical_evidence_packaging",
            permission_scope=["evidence_output:write"],
            status=RuntimeStatus.SUCCESS,
            output_refs=["agent_runtime_trace.json", "gate_result.json"],
        ),
    ]
    execution_config_sha256 = hashlib.sha256(
        canonical_json_bytes(
            {
                "source_id": source_receipt.source_id,
                "source_profile_sha256": source_receipt.data_profile["profile_sha256"],
                "seed": seed,
                "per_bucket": per_bucket,
                "rule_pack_source_sha256": expected_rulepack_source_sha256,
                "config": config,
            }
        )
    ).hexdigest()
    runtime_status = (
        RuntimeStatus.WARNING
        if any(
            task.status in {RuntimeStatus.WARNING, RuntimeStatus.ERROR}
            for task in control_tasks
        )
        else RuntimeStatus.SUCCESS
    )
    trace = RuntimeTrace(
        run_id=run.gate_result.run_id,
        execution_config_sha256=execution_config_sha256,
        goal=goal,
        intent="authorized_industrial_dataset_release_gate",
        backend="local-deterministic-agent-core-v1",
        backend_connected=True,
        fallback_used=False,
        status=runtime_status,
        tasks=control_tasks,
        events=events,
        memory=MemorySnapshot(
            working={
                "source_id": source_receipt.source_id,
                "initial_decision": run.initial_result.decision.value,
                "final_decision": run.gate_result.decision.value,
            }
        ),
        model_call_count=0,
        tool_call_count=len(run.gate_result.tool_trace),
        judge_decisions=[
            run.initial_result.decision.value,
            run.gate_result.decision.value,
        ],
        unresolved=sorted({item.code for item in run.gate_result.findings}),
        boundary_notice=(
            "Read-only local industrial-data pilot. Final production and safety authority "
            "remains with an authorized human role."
        ),
        scenario_profile=ScenarioProfile.INDUSTRIAL,
        approval_handoff=ApprovalHandoff(
            scope="production_system",
            mode="external_authorization_required",
            status="pending",
            required_role="industrial_data_owner_or_safety_responsible_person",
            reason="The Agent may recommend work orders but cannot authorize production use.",
            evidence_refs=[
                "gate_result.json",
                "local_source_authorization_receipt.json",
            ],
        ),
    )
    runtime_trace_path = evidence_dir / "agent_runtime_trace.json"
    runtime_trace_sha256 = write_canonical_json(runtime_trace_path, trace)
    core_receipt = build_agent_core_execution_receipt(
        run_id=run.gate_result.run_id,
        events=events,
        runtime_trace_sha256=runtime_trace_sha256,
        initial_gate_result_sha256=run.initial_gate_result_sha256,
        final_gate_result_sha256=run.gate_result_sha256,
        dynamic_leader_plan_sha256=run.leader_plan_sha256,
        planner_backend=str(leader_plan["planner"]),
        council_backend=run.gate_result.council_trace.backend,
        model_call_count=0,
        tool_call_count=len(run.gate_result.tool_trace),
        dynamic_task_count=len(dynamic_tasks),
        final_gate_decision=run.gate_result.decision,
    )
    verify_agent_core_execution_receipt(core_receipt, events=events)
    write_canonical_json(
        evidence_dir / "agent_core_execution_receipt.json", core_receipt
    )
    return seal_product_task_run(
        runtime_kind="authorized_local_readonly",
        evidence_dir=evidence_dir,
        runtime_trace_path=runtime_trace_path,
        initial_gate_result_path=evidence_dir / "initial" / "gate_result.json",
        final_gate_result_path=evidence_dir / "final" / "gate_result.json",
    )


def run_operator_snapshot_product_task(
    output_dir: str | Path,
    *,
    source_root: str | Path,
    source_receipt: LocalSourceAuthorizationReceipt,
    seed: int,
    goal: str,
    config: RuntimeConfig,
    event_sink: Callable[[RuntimeEvent], None] | None = None,
) -> ProductTaskRun:
    """Run one immutable Operator workbook snapshot through the Agent core.

    The adapter consumes the snapshot's native ``BatchManifest`` and
    ``BatchContract``.  It does not route workbook assets through the Omni
    sampler or infer a synthetic repair.  Any remediation remains a separate,
    human-approved CAPA/Child-Run operation.
    """

    if (
        source_receipt.adapter_kind
        is not LocalSourceAdapterKind.OPERATOR_PROJECT_SNAPSHOT
    ):
        raise ValueError("operator snapshot runner requires its dedicated adapter")

    task_root = Path(output_dir).expanduser().resolve()
    evidence_dir = task_root / "evidence"
    snapshot_root = Path(source_root).expanduser().resolve(strict=True)
    profile = profile_operator_project_snapshot(
        snapshot_root,
        expected_receipt_sha256=source_receipt.source_archive_sha256,
    )
    if source_receipt.derived_version_id is not None:
        frozen_profile = source_receipt.data_profile
        profile.pop("profile_sha256", None)
        for key in (
            "source_assets_copied_into_product",
            "derived_version_id",
            "derived_from_source_id",
            "derived_manifest_sha256",
        ):
            if key in frozen_profile:
                profile[key] = frozen_profile[key]
        profile["profile_sha256"] = hashlib.sha256(
            canonical_json_bytes(profile)
        ).hexdigest()
    if profile != source_receipt.data_profile:
        raise ValueError("operator snapshot profile differs from its authorization")

    snapshot_receipt_path = snapshot_root / "operator_project_snapshot_receipt.json"
    snapshot_receipt = OperatorProjectSnapshotReceipt.model_validate_json(
        snapshot_receipt_path.read_bytes()
    )
    manifest = BatchManifest.model_validate_json(
        (snapshot_root / snapshot_receipt.batch_manifest_relative_path).read_bytes()
    )
    contract = BatchContract.model_validate_json(
        (snapshot_root / snapshot_receipt.batch_contract_relative_path).read_bytes()
    )
    batch_root = snapshot_root / "batch"
    batch_digest = compute_batch_digest(batch_root, manifest, contract)
    if not hmac.compare_digest(batch_digest, snapshot_receipt.batch_digest_sha256):
        raise ValueError("operator snapshot batch digest changed before execution")

    events: list[RuntimeEvent] = []

    def emit(
        *,
        phase: Literal["initial", "verification"],
        stage: RuntimeStage,
        actor: str,
        action: str,
        status: RuntimeStatus,
        summary: str,
        task_id: str,
        tool_name: str | None = None,
        evidence_refs: list[str] | None = None,
    ) -> None:
        event = RuntimeEvent(
            sequence=len(events) + 1,
            phase=phase,
            stage=stage,
            actor=actor,
            action=action,
            status=status,
            summary=summary,
            task_id=task_id,
            tool_name=tool_name,
            evidence_refs=evidence_refs or [],
        )
        events.append(event)
        if event_sink is not None:
            event_sink(event)

    emit(
        phase="initial",
        stage=RuntimeStage.INTAKE,
        actor="Operator Snapshot Intake",
        action="verify_immutable_project_snapshot",
        status=RuntimeStatus.SUCCESS,
        summary="已核验工作簿快照、图片、预览、标注 revision、mask 与批次合同摘要。",
        task_id="intake.operator-snapshot",
        evidence_refs=[
            f"source:{source_receipt.source_id}",
            f"snapshot_receipt_sha256:{snapshot_receipt.receipt_sha256}",
            f"batch_digest_sha256:{batch_digest}",
        ],
    )

    include_optional = (
        config.scenario_profile is not ScenarioProfile.GENERIC
        or "governance_audit" in config.allowed_tools
    )
    catalog = tool_catalog(include_optional=include_optional)
    selected_tools = [
        str(item["name"])
        for item in catalog
        if str(item["name"]) in config.allowed_tools
    ][: config.max_tool_calls]
    if not selected_tools:
        raise ValueError("operator snapshot task has no executable allowlisted tools")
    emit(
        phase="initial",
        stage=RuntimeStage.PLANNER,
        actor="Deterministic Snapshot Planner",
        action="plan_allowlisted_evidence_wave",
        status=RuntimeStatus.SUCCESS,
        summary=f"已规划 {len(selected_tools)} 个只读确定性工具；不允许源资产写回。",
        task_id="plan.snapshot-tools",
        evidence_refs=[f"tool:{name}" for name in selected_tools],
    )

    findings: list[Finding] = []
    traces: list[ToolTrace] = []
    metrics: dict[str, int | float | str] = {
        "sample_count": len(manifest.samples),
        "tool_count": len(selected_tools),
        "tool_error_count": 0,
    }
    for tool_name in selected_tools:
        tool_findings, trace, tool_metrics = run_tool(
            tool_name,
            batch_root,
            manifest,
            contract,
            include_optional=include_optional,
        )
        findings.extend(tool_findings)
        traces.append(trace)
        metrics.update(tool_metrics)
        if trace.status != "ok":
            metrics["tool_error_count"] = int(metrics["tool_error_count"]) + 1
        emit(
            phase="initial",
            stage=RuntimeStage.TOOL,
            actor=f"Worker/{tool_name}",
            action="invoke_allowlisted_snapshot_tool",
            status=(
                RuntimeStatus.SUCCESS if trace.status == "ok" else RuntimeStatus.ERROR
            ),
            summary=(
                f"{tool_name} 完成，生成 {len(tool_findings)} 条 Finding。"
                if trace.status == "ok"
                else f"{tool_name} 返回失败状态；最终 Judge 必须 fail-closed。"
            ),
            task_id=f"tool.{tool_name}",
            tool_name=tool_name,
            evidence_refs=[
                f"trace:{trace.sequence}:{trace.tool}",
                f"result_sha256:{trace.result_sha256}",
            ],
        )

    findings.sort(key=lambda item: (item.tool, item.finding_id))
    traces.sort(key=lambda item: item.sequence)
    metrics["finding_count"] = len(findings)
    council = build_council(findings, traces, metrics)
    emit(
        phase="initial",
        stage=RuntimeStage.COUNCIL,
        actor="Deterministic Evidence Council",
        action="interpret_cited_snapshot_evidence",
        status=RuntimeStatus.SUCCESS,
        summary="证据委员会仅解释 ToolTrace 与 Finding；未读取私有思维链或调用外部模型。",
        task_id="council.snapshot",
        evidence_refs=sorted(
            {
                reference
                for opinion in council.independent_opinions
                for reference in opinion.evidence_refs
            }
        ),
    )
    result = apply_policy(
        manifest,
        contract,
        findings,
        traces,
        metrics,
        council,
        scenario_profile=config.scenario_profile,
        input_sha256=batch_digest,
        run_id=(
            f"operator-snapshot-{snapshot_receipt.snapshot_id.removeprefix('opsnap_')}-"
            f"{hashlib.sha256(canonical_json_bytes(config)).hexdigest()[:10]}"
        ),
    )
    emit(
        phase="initial",
        stage=RuntimeStage.JUDGE,
        actor="Frozen Policy Judge",
        action="apply_fail_closed_snapshot_policy",
        status=RuntimeStatus.SUCCESS,
        summary=(
            f"冻结策略签发 {result.decision.value}；生成 "
            f"{len(result.work_orders)} 张可追溯工单。"
        ),
        task_id="judge.snapshot",
        evidence_refs=[
            f"decision:{result.decision.value}",
            *[item.work_order_id for item in result.work_orders],
        ],
    )

    initial_dir = evidence_dir / "initial"
    final_dir = evidence_dir / "final"
    write_evidence_artifacts(
        initial_dir,
        result,
        scenario_profile=config.scenario_profile,
    )
    write_evidence_artifacts(
        final_dir,
        result,
        scenario_profile=config.scenario_profile,
    )
    write_evidence_artifacts(
        evidence_dir,
        result,
        scenario_profile=config.scenario_profile,
    )
    write_canonical_json(
        evidence_dir / "local_source_authorization_receipt.json", source_receipt
    )
    write_canonical_json(evidence_dir / "source_profile.json", profile)
    shutil.copyfile(
        snapshot_receipt_path,
        evidence_dir / "operator_project_snapshot_receipt.json",
    )
    write_canonical_json(
        evidence_dir / "claim_scope_receipt.json",
        {
            "schema_version": "visiondata-gate.operator-snapshot-claim-scope.v1",
            "source_kind": source_receipt.source_kind.value,
            "adapter_kind": source_receipt.adapter_kind.value,
            "real_source_bytes_read": True,
            "source_assets_copied_into_product": True,
            "raw_images_transmitted": False,
            "machine_write_permitted": False,
            "production_release_allowed": False,
            "factory_shadow_validation": "NOT_AVAILABLE",
            "customer_acceptance": "NOT_AVAILABLE",
            "boundary": snapshot_receipt.claim_boundary,
        },
    )
    planner_backend = "deterministic-operator-snapshot-v1"
    dynamic_plan = {
        "schema_version": "visiondata-gate.operator-snapshot-dynamic-plan.v1",
        "planner": planner_backend,
        "snapshot_id": snapshot_receipt.snapshot_id,
        "snapshot_receipt_sha256": snapshot_receipt.receipt_sha256,
        "dynamic_task_count": 0,
        "replan_count": 0,
        "dynamic_tasks": [],
        "reason": (
            "The first evidence wave completed without a tool failure. Findings are "
            "routed to human-approved CAPA and a separate Child Run instead of an "
            "unapproved source mutation."
        ),
    }
    dynamic_plan_path = evidence_dir / "dynamic_leader_plan.json"
    dynamic_plan_sha256 = write_canonical_json(dynamic_plan_path, dynamic_plan)
    initial_gate_path = initial_dir / "gate_result.json"
    final_gate_path = final_dir / "gate_result.json"
    operator_gate_stable = {
        "schema_version": "visiondata-gate.operator-snapshot-gate-receipt.v1",
        "source_id": source_receipt.source_id,
        "snapshot_id": snapshot_receipt.snapshot_id,
        "snapshot_receipt_sha256": snapshot_receipt.receipt_sha256,
        "source_profile_sha256": profile["profile_sha256"],
        "batch_digest_sha256": batch_digest,
        "initial_gate_result_sha256": sha256_file(initial_gate_path),
        "final_gate_result_sha256": sha256_file(final_gate_path),
        "dynamic_leader_plan_sha256": dynamic_plan_sha256,
        "tool_result_sha256": {trace.tool: trace.result_sha256 for trace in traces},
        "source_mutation_permitted": False,
        "machine_write_permitted": False,
        "production_release_allowed": False,
    }
    write_canonical_json(
        evidence_dir / "operator_snapshot_gate_receipt.json",
        {
            **operator_gate_stable,
            "receipt_sha256": hashlib.sha256(
                canonical_json_bytes(operator_gate_stable)
            ).hexdigest(),
        },
    )
    write_canonical_json(
        evidence_dir / "task_summary.json",
        {
            "schema_version": "visiondata-gate.product-operator-snapshot-task.v1",
            "source_id": source_receipt.source_id,
            "snapshot_id": snapshot_receipt.snapshot_id,
            "snapshot_receipt_sha256": snapshot_receipt.receipt_sha256,
            "source_profile_sha256": profile["profile_sha256"],
            "source_binding_sha256": snapshot_receipt.receipt_sha256,
            "initial_decision": result.decision.value,
            "final_decision": result.decision.value,
            "tool_call_count": len(traces),
            "finding_count": len(result.findings),
            "work_order_count": len(result.work_orders),
            "dynamic_task_count": 0,
            "replan_count": 0,
            "raw_source_path_serialized": False,
            "raw_images_transmitted": False,
            "production_release_allowed": False,
        },
    )

    # Recompute every source binding after the tools finish.  A snapshot that
    # changed during execution is never sealed into a successful Product Task.
    final_profile = profile_operator_project_snapshot(
        snapshot_root,
        expected_receipt_sha256=source_receipt.source_archive_sha256,
    )
    if source_receipt.derived_version_id is not None:
        final_profile.pop("profile_sha256", None)
        for key in (
            "source_assets_copied_into_product",
            "derived_version_id",
            "derived_from_source_id",
            "derived_manifest_sha256",
        ):
            if key in source_receipt.data_profile:
                final_profile[key] = source_receipt.data_profile[key]
        final_profile["profile_sha256"] = hashlib.sha256(
            canonical_json_bytes(final_profile)
        ).hexdigest()
    if final_profile != profile:
        raise ValueError("operator snapshot changed during Agent execution")

    emit(
        phase="verification",
        stage=RuntimeStage.DELIVERY,
        actor="Evidence Delivery",
        action="seal_operator_snapshot_evidence",
        status=RuntimeStatus.SUCCESS,
        summary="已封存快照回执、ToolTrace、GateResult、动态计划与只读边界。",
        task_id="delivery.snapshot-evidence",
        evidence_refs=[
            "operator_project_snapshot_receipt.json",
            "operator_snapshot_gate_receipt.json",
            "gate_result.json",
        ],
    )
    task_status_by_id = {
        event.task_id: event.status for event in events if event.task_id is not None
    }
    task_defs = [
        ("intake.operator-snapshot", RuntimeStage.INTAKE, []),
        ("plan.snapshot-tools", RuntimeStage.PLANNER, ["intake.operator-snapshot"]),
        *[
            (f"tool.{name}", RuntimeStage.TOOL, ["plan.snapshot-tools"])
            for name in selected_tools
        ],
        (
            "council.snapshot",
            RuntimeStage.COUNCIL,
            [f"tool.{name}" for name in selected_tools],
        ),
        ("judge.snapshot", RuntimeStage.JUDGE, ["council.snapshot"]),
        (
            "delivery.snapshot-evidence",
            RuntimeStage.DELIVERY,
            ["judge.snapshot"],
        ),
    ]
    tasks = [
        AgentTask(
            task_id=task_id,
            title=task_id.replace(".", " "),
            stage=stage,
            actor=next(event.actor for event in events if event.task_id == task_id),
            dependencies=dependencies,
            capability="operator_snapshot_readonly_gate",
            permission_scope=[
                "operator_snapshot:read",
                "evidence:append",
            ],
            status=task_status_by_id[task_id],
            output_refs=next(
                event.evidence_refs
                for event in reversed(events)
                if event.task_id == task_id
            ),
        )
        for task_id, stage, dependencies in task_defs
    ]
    execution_config_sha256 = hashlib.sha256(
        canonical_json_bytes(
            {
                "source_id": source_receipt.source_id,
                "snapshot_receipt_sha256": snapshot_receipt.receipt_sha256,
                "seed": seed,
                "config": config,
            }
        )
    ).hexdigest()
    runtime_status = (
        RuntimeStatus.SUCCESS
        if result.decision is GateDecision.PASS
        else RuntimeStatus.WARNING
    )
    trace = RuntimeTrace(
        run_id=result.run_id,
        execution_config_sha256=execution_config_sha256,
        goal=goal,
        intent="operator_project_snapshot_release_gate",
        backend="local-deterministic-agent-core-v1",
        backend_connected=True,
        fallback_used=False,
        status=runtime_status,
        tasks=tasks,
        events=events,
        memory=MemorySnapshot(
            working={
                "source_id": source_receipt.source_id,
                "snapshot_id": snapshot_receipt.snapshot_id,
                "snapshot_receipt_sha256": snapshot_receipt.receipt_sha256,
                "decision": result.decision.value,
            }
        ),
        model_call_count=0,
        tool_call_count=len(traces),
        judge_decisions=[result.decision.value],
        unresolved=sorted({item.code for item in result.findings}),
        boundary_notice=(
            "Private local workbook snapshot only. This result is not factory shadow "
            "validation, customer acceptance, equipment authority, or production release."
        ),
        scenario_profile=config.scenario_profile,
        approval_handoff=ApprovalHandoff(
            scope="production_system",
            mode="external_authorization_required",
            status="pending",
            required_role="industrial_data_owner_or_safety_responsible_person",
            reason="The Agent may recommend CAPA but cannot authorize production use.",
            evidence_refs=[
                "gate_result.json",
                "operator_project_snapshot_receipt.json",
            ],
        ),
    )
    runtime_trace_path = evidence_dir / "agent_runtime_trace.json"
    runtime_trace_sha256 = write_canonical_json(runtime_trace_path, trace)
    core_receipt = build_agent_core_execution_receipt(
        run_id=result.run_id,
        events=events,
        runtime_trace_sha256=runtime_trace_sha256,
        initial_gate_result_sha256=sha256_file(initial_gate_path),
        final_gate_result_sha256=sha256_file(final_gate_path),
        dynamic_leader_plan_sha256=sha256_file(dynamic_plan_path),
        planner_backend=planner_backend,
        council_backend=result.council_trace.backend,
        model_call_count=0,
        tool_call_count=len(traces),
        dynamic_task_count=0,
        final_gate_decision=result.decision,
    )
    verify_agent_core_execution_receipt(core_receipt, events=events)
    write_canonical_json(
        evidence_dir / "agent_core_execution_receipt.json", core_receipt
    )
    return seal_product_task_run(
        runtime_kind="operator_project_snapshot",
        evidence_dir=evidence_dir,
        runtime_trace_path=runtime_trace_path,
        initial_gate_result_path=initial_gate_path,
        final_gate_result_path=final_gate_path,
    )


__all__ = [
    "OMNI_REQUIRED_EVIDENCE",
    "ProductKernelRunReceipt",
    "ProductTaskRun",
    "SYNTHETIC_REQUIRED_EVIDENCE",
    "normalize_agentic_run",
    "run_omni_product_task",
    "run_operator_snapshot_product_task",
    "seal_product_task_run",
    "verify_product_task_run",
]
