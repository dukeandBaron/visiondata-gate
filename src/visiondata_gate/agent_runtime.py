"""Observable Router/Planner/Worker/Council/Judge runtime.

The runtime keeps measurement and release authority outside the language model:
Workers execute an allowlisted tool gateway, AI roles interpret cited evidence,
and the frozen Judge remains fail-closed.
"""

from __future__ import annotations

import hashlib
import json
import time
from collections.abc import Callable, Sequence
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .contracts import (
    BatchContract,
    BatchManifest,
    CorruptionManifest,
    EvaluationResult,
    Finding,
    GateResult,
    ToolTrace,
)
from .agentteams_contract import (
    agentteams_task_binding,
    build_agentteams_contract,
    skill_contract_digest,
    skill_for_task,
)
from .agentteams_v122 import write_agentteams_v122_bundle
from .acceptance import build_acceptance_scorecard
from .evaluation import evaluate_gate
from .evidence import write_canonical_json, write_evidence_artifacts
from .generator import generate_demo_dataset
from .grounding import build_llm_grounding_receipt
from .knowledge import retrieve_knowledge, role_memory
from .model_backends import CouncilBuild, build_council_with_backend
from .pipeline import DemoRun, compute_batch_digest
from .proof import write_proof_artifacts
from .policy import apply_policy
from .repair import RepairResult, simulate_repair
from .reporting import write_offline_html
from .runtime_memory import (
    LocalMemoryStore,
    MemoryGovernanceReceipt,
    MemoryRecallReceipt,
    MemoryWriteReceipt,
)
from .runtime_hardening_receipts import (
    build_backend_identity_runtime_receipt,
    build_model_transport_runtime_receipt,
    build_prompt_guard_runtime_receipt,
)
from .runtime_models import (
    AgentTask,
    ApprovalHandoff,
    ContextTransfer,
    KnowledgeHit,
    MemoryRecord,
    MemorySnapshot,
    RuntimeConfig,
    ScenarioProfile,
    RuntimeEvent,
    RuntimeStage,
    RuntimeStatus,
    RuntimeTrace,
    SkillContract,
    SkillExecution,
)
from .tools import (
    ToolResult,
    ToolRunner,
    build_batch_fingerprint,
    execute_tool_gateway,
    run_tool,
    tool_catalog,
    tool_contract_catalog,
    tool_contract_digest,
)


EventSink = Callable[[RuntimeEvent], None]


_RETRYABLE_TOOL_ERROR_PREFIXES = ("TimeoutError:", "ConnectionError:")


def _effective_allowed_tools(config: RuntimeConfig) -> tuple[list[str], bool]:
    """Resolve allowlist with scenario-aware optional tool enabling."""

    allowlist = list(dict.fromkeys(config.allowed_tools))
    include_optional = config.scenario_profile is not ScenarioProfile.GENERIC
    if "governance_audit" in allowlist:
        include_optional = True

    if include_optional and "governance_audit" not in allowlist:
        allowlist.append("governance_audit")

    return allowlist, include_optional


def execute_tool_with_bounded_retry(
    tool_name: str,
    batch_root: str | Path,
    manifest: BatchManifest,
    contract: BatchContract,
    *,
    include_optional: bool,
    runner: ToolRunner,
    batch_fingerprint: str,
    configured_max_retries: int,
) -> tuple[ToolResult, int]:
    """Execute one tool with a contract-capped transient retry budget.

    The gateway still owns response validation and fail-closed conversion.  A
    retry is allowed only when the gateway produced a typed error trace for a
    transient timeout/connection failure.  Permission, schema, stale-response,
    contract-digest, and other integrity failures are never retried.
    """

    tool_contract = next(
        item
        for item in tool_contract_catalog(include_optional=include_optional)
        if item.name == tool_name
    )
    retry_budget = min(configured_max_retries, tool_contract.max_retries)
    retry_count = 0
    while True:
        result = execute_tool_gateway(
            tool_name,
            batch_root,
            manifest,
            contract,
            include_optional=include_optional,
            runner=runner,
            batch_fingerprint=batch_fingerprint,
        )
        bind_gateway_response = getattr(runner, "bind_gateway_response", None)
        if callable(bind_gateway_response):
            bind_gateway_response(result)
        trace = result[1]
        transient = bool(
            trace.status == "error"
            and trace.error
            and trace.error.startswith(_RETRYABLE_TOOL_ERROR_PREFIXES)
        )
        if not transient or retry_count >= retry_budget:
            return result, retry_count
        retry_count += 1


@dataclass(frozen=True)
class GateAgentOutcome:
    result: GateResult
    knowledge: list[KnowledgeHit]
    council_build: CouncilBuild
    tool_call_count: int
    memory_recall_receipt: MemoryRecallReceipt
    memory_write_receipt: MemoryWriteReceipt | None


@dataclass(frozen=True)
class AgenticDemoRun:
    base: DemoRun
    runtime_trace: RuntimeTrace
    runtime_trace_path: Path
    memory_path: Path

    @property
    def output_root(self) -> Path:
        return self.base.output_root

    @property
    def dataset_paths(self) -> dict[str, Path]:
        return self.base.dataset_paths

    @property
    def initial_result(self) -> GateResult:
        return self.base.initial_result

    @property
    def repair(self) -> RepairResult:
        return self.base.repair

    @property
    def repaired_result(self) -> GateResult:
        return self.base.repaired_result

    @property
    def evaluation(self) -> EvaluationResult:
        return self.base.evaluation

    @property
    def evidence_dir(self) -> Path:
        return self.base.evidence_dir

    @property
    def summary_path(self) -> Path:
        return self.base.summary_path


class _Recorder:
    def __init__(
        self,
        sink: EventSink | None = None,
        *,
        tasks: list[AgentTask] | None = None,
        skills: Sequence[SkillContract] = (),
    ) -> None:
        self.events: list[RuntimeEvent] = []
        self.context_transfers: list[ContextTransfer] = []
        self.skill_executions: list[SkillExecution] = []
        self.sink = sink
        self.tasks = tasks
        self.skills = {item.skill_id: item for item in skills}

    def emit(
        self,
        *,
        phase: str,
        stage: RuntimeStage,
        actor: str,
        action: str,
        status: RuntimeStatus,
        summary: str,
        task_id: str | None = None,
        tool_name: str | None = None,
        duration_ms: float = 0.0,
        evidence_refs: Sequence[str] = (),
        retry: int = 0,
        collaboration: dict[str, str] | None = None,
    ) -> RuntimeEvent:
        event = RuntimeEvent(
            sequence=len(self.events) + 1,
            phase=phase,
            stage=stage,
            actor=actor,
            action=action,
            status=status,
            summary=summary,
            task_id=task_id,
            tool_name=tool_name,
            duration_ms=round(duration_ms, 3),
            evidence_refs=list(evidence_refs),
            retry=retry,
            collaboration=collaboration
            or (
                agentteams_task_binding(
                    task_id or "system.lifecycle", stage.value, actor
                )
            ),
        )
        self.events.append(event)
        if task_id is not None and self.tasks is not None:
            self._capture_dependency_transfers(task_id, event.sequence)
            self._capture_skill_execution(task_id, event.sequence)
        if self.sink is not None:
            try:
                self.sink(event)
            except Exception:
                # A UI callback must never change the gate result.
                pass
        return event

    def _capture_skill_execution(
        self,
        task_id: str,
        event_sequence: int,
    ) -> None:
        """Record the executable Skill binding at the task terminal event."""

        task_by_id = {task.task_id: task for task in self.tasks or []}
        task = task_by_id.get(task_id)
        if task is None or task.status in {RuntimeStatus.QUEUED, RuntimeStatus.RUNNING}:
            return
        if any(item.task_id == task_id for item in self.skill_executions):
            return

        try:
            skill_id = skill_for_task(task_id)
        except KeyError:
            return
        skill = self.skills.get(skill_id)
        if skill is None:
            return
        binding = agentteams_task_binding(task_id, task.stage.value, task.actor)
        agent_id = binding["agent_id"]
        authorized_agents = {skill.owner_agent_id}
        if skill_id == "skill.parallel-evidence-audit.v1":
            authorized_agents.update(
                item
                for item in (
                    "leader.release-gate",
                    "worker.image-quality",
                    "worker.duplicate-leakage",
                    "worker.annotation-integrity",
                    "worker.coverage-matrix",
                    "worker.governance-audit",
                )
            )
        if skill_id == "skill.reserve-recheck-delivery.v1":
            authorized_agents.update({"operator.repair", "operator.audit-clerk"})

        dependencies = [
            dependency
            for dependency in (self.tasks or [])
            if dependency.task_id in task.dependencies
        ]
        input_refs = sorted(
            {ref for dependency in dependencies for ref in dependency.output_refs}
        )
        if not input_refs:
            terminal_event = self.events[event_sequence - 1]
            input_refs = list(terminal_event.evidence_refs)
        output_refs = list(task.output_refs)
        checks = {
            "contract_declared": True,
            "version_pinned": bool(skill.version),
            "task_skill_binding_valid": skill_for_task(task_id) == skill.skill_id,
            "agent_authorized": agent_id in authorized_agents,
            "terminal_event_bound": (
                self.events[event_sequence - 1].task_id == task_id
                and self.events[event_sequence - 1].status is task.status
            ),
            "output_receipt_present_or_failure": (
                bool(output_refs)
                or task.status in {RuntimeStatus.ERROR, RuntimeStatus.SKIPPED}
            ),
        }
        if not all(checks.values()):
            qualification_status = "rejected"
            rejection_reason = ";".join(
                key for key, passed in checks.items() if not passed
            )
            rollback_action = skill.rollback_strategy
        elif task.status in {RuntimeStatus.ERROR, RuntimeStatus.SKIPPED}:
            qualification_status = "deferred"
            rejection_reason = f"task_status={task.status.value}"
            rollback_action = skill.rollback_strategy
        else:
            qualification_status = "qualified"
            rejection_reason = None
            rollback_action = "none_required"

        self.skill_executions.append(
            SkillExecution(
                sequence=len(self.skill_executions) + 1,
                recorded_event_sequence=event_sequence,
                phase=(
                    task_id.split(".", 1)[0]
                    if task_id.split(".", 1)[0] in {"system", "initial", "verification"}
                    else "system"
                ),
                task_id=task_id,
                agent_id=agent_id,
                skill_id=skill.skill_id,
                skill_version=skill.version,
                skill_contract_digest=skill_contract_digest(skill),
                task_status=task.status,
                qualification_status=qualification_status,
                input_refs=input_refs,
                output_refs=output_refs,
                input_digest=_refs_digest(input_refs),
                output_digest=_refs_digest(output_refs),
                qualification_checks=checks,
                rollback_action=rollback_action,
                rejection_reason=rejection_reason,
            )
        )

    def _capture_dependency_transfers(
        self,
        target_task_id: str,
        event_sequence: int,
    ) -> None:
        """Capture hand-offs when the target task emits its terminal event."""

        task_by_id = {task.task_id: task for task in self.tasks or []}
        target = task_by_id.get(target_task_id)
        if target is None or target.status in {
            RuntimeStatus.QUEUED,
            RuntimeStatus.RUNNING,
        }:
            return
        existing = {
            (item.source_task_id, item.task_id) for item in self.context_transfers
        }
        phase = target.task_id.split(".", 1)[0]
        if phase not in {"system", "initial", "verification"}:
            phase = "system"
        for source_id in sorted(target.dependencies):
            if (source_id, target.task_id) in existing:
                continue
            source = task_by_id.get(source_id)
            if source is None:
                continue
            status, acceptance_basis, reason = _transfer_outcome(source, target)
            self.context_transfers.append(
                _context_transfer(
                    phase=phase,
                    source_task_id=source.task_id,
                    target_task_id=target.task_id,
                    payload_kind=f"{source.stage.value}_to_{target.stage.value}",
                    input_refs=list(source.output_refs),
                    output_refs=list(target.output_refs),
                    source_status=source.status,
                    target_status=target.status,
                    acceptance_basis=acceptance_basis,
                    status=status,
                    rejection_reason=reason,
                    sequence=len(self.context_transfers) + 1,
                    recorded_event_sequence=event_sequence,
                )
            )


def _task_id(phase: str, suffix: str) -> str:
    return f"{phase}.{suffix}"


def _payload_sha256(payload: object) -> str:
    """Hash only the typed hand-off summary, never hidden model reasoning."""

    encoded = json.dumps(
        payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=str
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _refs_digest(refs: Sequence[str]) -> str:
    """Digest the canonical reference list carried by one task output."""

    return _payload_sha256(sorted(str(item) for item in refs))


def _context_transfer(
    *,
    phase: str,
    source_task_id: str,
    target_task_id: str,
    payload_kind: str,
    input_refs: Sequence[str],
    output_refs: Sequence[str],
    source_status: RuntimeStatus,
    target_status: RuntimeStatus,
    acceptance_basis: str,
    status: str = "accepted",
    rejection_reason: str | None = None,
    sequence: int = 1,
    recorded_event_sequence: int = 1,
) -> ContextTransfer:
    source_binding = agentteams_task_binding(source_task_id, "transfer", source_task_id)
    target_binding = agentteams_task_binding(target_task_id, "transfer", target_task_id)
    payload = {
        "kind": payload_kind,
        "input_refs": sorted(str(item) for item in input_refs),
        "output_refs": sorted(str(item) for item in output_refs),
        "source_status": source_status.value,
        "target_status": target_status.value,
        "source_output_digest": _refs_digest(input_refs),
        "target_output_digest": _refs_digest(output_refs),
        "acceptance_basis": acceptance_basis,
        "status": status,
    }
    return ContextTransfer(
        sequence=sequence,
        recorded_event_sequence=recorded_event_sequence,
        phase=phase,
        source_agent_id=source_binding["agent_id"],
        target_agent_id=target_binding["agent_id"],
        source_task_id=source_task_id,
        task_id=target_task_id,
        payload_kind=payload_kind,
        input_refs=list(input_refs),
        output_refs=list(output_refs),
        source_status=source_status,
        target_status=target_status,
        source_output_digest=_refs_digest(input_refs),
        target_output_digest=_refs_digest(output_refs),
        acceptance_basis=acceptance_basis,
        payload_sha256=_payload_sha256(payload),
        status=status,
        rejection_reason=rejection_reason,
    )


def _transfer_outcome(
    source: AgentTask,
    target: AgentTask,
) -> tuple[str, str, str | None]:
    """Return the fail-closed outcome for one dependency hand-off."""

    if source.status is not RuntimeStatus.SUCCESS:
        return (
            "deferred",
            "source_not_success",
            f"source={source.status.value};target={target.status.value}",
        )
    if target.status in {RuntimeStatus.ERROR, RuntimeStatus.SKIPPED}:
        return (
            "deferred",
            "target_not_runnable",
            f"source={source.status.value};target={target.status.value}",
        )
    if not source.output_refs:
        return (
            "deferred",
            "source_success_without_output_refs",
            "source=success;output_refs=empty",
        )
    return (
        "accepted",
        (
            "source_success_target_warning"
            if target.status is RuntimeStatus.WARNING
            else "source_success_target_success"
        ),
        None,
    )


def _assert_context_transfer_coverage(
    tasks: Sequence[AgentTask],
    transfers: Sequence[ContextTransfer],
) -> None:
    """Fail the run if the runtime ledger missed or duplicated a DAG edge.

    ``AgentTeamsSnapshot.context_flow`` is the reusable protocol description;
    this ledger is captured from terminal runtime events.  It contains
    references and digests only, never prompts or hidden reasoning.
    """

    declared = sorted(
        (dependency, task.task_id) for task in tasks for dependency in task.dependencies
    )
    captured = sorted((item.source_task_id, item.task_id) for item in transfers)
    if declared != captured:
        raise RuntimeError(
            "runtime context ledger does not match declared DAG dependencies"
        )


def build_task_graph(phase: str, *, include_optional: bool = False) -> list[AgentTask]:
    """Return the explicit dependency graph for one gate pass."""

    if phase not in {"initial", "verification"}:
        raise ValueError("phase must be initial or verification")
    prefix = phase
    tool_tasks = [
        AgentTask(
            task_id=_task_id(prefix, f"tool.{item['name']}"),
            title=str(item["description"]),
            stage=RuntimeStage.TOOL,
            actor=f"Worker/{item['name']}",
            dependencies=[_task_id(prefix, "plan")],
            capability=str(item["name"]),
            permission_scope=[str(item["permission"])],
        )
        for item in tool_catalog(include_optional=include_optional)
    ]
    return [
        AgentTask(
            task_id=_task_id(prefix, "intake"),
            title="验证任务输入与冻结合同",
            stage=RuntimeStage.INTAKE,
            actor="Trigger",
            capability="strict-contract-validation",
            permission_scope=["manifest:read", "contract:read"],
        ),
        AgentTask(
            task_id=_task_id(prefix, "route"),
            title="识别工业数据发布意图",
            stage=RuntimeStage.ROUTER,
            actor="Router",
            dependencies=[_task_id(prefix, "intake")],
            capability="intent-routing",
            permission_scope=["context:read"],
        ),
        AgentTask(
            task_id=_task_id(prefix, "memory"),
            title="召回长期记录与语义知识",
            stage=RuntimeStage.MEMORY,
            actor="Memory Broker",
            dependencies=[_task_id(prefix, "route")],
            capability="bounded-memory-retrieval",
            permission_scope=["memory:read", "knowledge:read"],
        ),
        AgentTask(
            task_id=_task_id(prefix, "plan"),
            title="拆分 Worker 与证据依赖",
            stage=RuntimeStage.PLANNER,
            actor="Planner",
            dependencies=[_task_id(prefix, "memory")],
            capability="dependency-planning",
            permission_scope=["tool-catalog:read"],
        ),
        *tool_tasks,
        AgentTask(
            task_id=_task_id(prefix, "council"),
            title="五角色证据解读与交叉质询",
            stage=RuntimeStage.COUNCIL,
            actor="AI Expert Council",
            dependencies=[task.task_id for task in tool_tasks],
            capability="evidence-grounded-review",
            permission_scope=["findings:read", "knowledge:read", "model:advisory"],
        ),
        AgentTask(
            task_id=_task_id(prefix, "judge"),
            title="执行冻结 fail-closed 门禁",
            stage=RuntimeStage.JUDGE,
            actor="Policy Judge",
            dependencies=[_task_id(prefix, "council")],
            capability="deterministic-policy",
            permission_scope=["decision:write", "work-order:write"],
        ),
    ]


def _set_task_status(
    tasks: list[AgentTask],
    task_id: str,
    status: RuntimeStatus,
    *,
    output_refs: Sequence[str] = (),
) -> None:
    for index, task in enumerate(tasks):
        if task.task_id == task_id:
            tasks[index] = task.model_copy(
                update={"status": status, "output_refs": list(output_refs)}
            )
            return
    raise KeyError(task_id)


def _sha256_payload(payload: dict[str, Any]) -> str:
    encoded = json.dumps(
        payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _execution_config_digest(config: RuntimeConfig) -> str:
    """Bind run identity to permissions, budgets, backend and scenario settings."""

    payload = config.model_dump(mode="json")
    payload["allowed_tools"] = sorted(payload["allowed_tools"])
    return _sha256_payload(payload)


def _error_trace(
    tool_name: str,
    sequence: int,
    message: str,
    *,
    skipped: bool,
    include_optional: bool = False,
) -> ToolTrace:
    status = "skipped" if skipped else "error"
    payload = {"tool": tool_name, "status": status, "message": message}
    digest = _sha256_payload(payload)
    return ToolTrace(
        sequence=sequence,
        tool=tool_name,
        status=status,
        input_sha256=digest,
        parameters={},
        result_sha256=digest,
        error=message,
        contract_version=next(
            item.version
            for item in tool_contract_catalog(include_optional=include_optional)
            if item.name == tool_name
        ),
        contract_digest=tool_contract_digest(
            tool_name, include_optional=include_optional
        ),
        adapter="local-deterministic",
    )


def _load_manifest(path: Path) -> BatchManifest:
    return BatchManifest.model_validate_json(path.read_text(encoding="utf-8"))


def _runtime_gate(
    batch_root: Path,
    manifest: BatchManifest,
    contract: BatchContract,
    *,
    phase: str,
    goal: str,
    config: RuntimeConfig,
    recorder: _Recorder,
    tasks: list[AgentTask],
    memory_store: LocalMemoryStore,
    api_key: str | None,
    execution_config_sha256: str,
    tool_runner: ToolRunner,
) -> GateAgentOutcome:
    intake_id = _task_id(phase, "intake")
    _set_task_status(tasks, intake_id, RuntimeStatus.RUNNING)
    started = time.perf_counter()
    digest = compute_batch_digest(batch_root, manifest, contract)
    batch_fingerprint = build_batch_fingerprint(batch_root, manifest)
    _set_task_status(tasks, intake_id, RuntimeStatus.SUCCESS, output_refs=[digest])
    recorder.emit(
        phase=phase,
        stage=RuntimeStage.INTAKE,
        actor="Trigger",
        action="validate_input",
        status=RuntimeStatus.SUCCESS,
        summary=f"合同、manifest 与文件边界验证完成；输入指纹 {digest[:12]}…",
        task_id=intake_id,
        duration_ms=(time.perf_counter() - started) * 1000,
        evidence_refs=[f"sha256:{digest}"],
    )

    route_id = _task_id(phase, "route")
    _set_task_status(tasks, route_id, RuntimeStatus.RUNNING)
    intent = "industrial_vision_data_release_gate"
    _set_task_status(tasks, route_id, RuntimeStatus.SUCCESS, output_refs=[intent])
    recorder.emit(
        phase=phase,
        stage=RuntimeStage.ROUTER,
        actor="Router",
        action="route_intent",
        status=RuntimeStatus.SUCCESS,
        summary="任务已收束为工业视觉数据发布审核；禁止扩展到产品质检和生产授权。",
        task_id=route_id,
        evidence_refs=[f"contract:{contract.contract_id}"],
    )

    memory_id = _task_id(phase, "memory")
    _set_task_status(tasks, memory_id, RuntimeStatus.RUNNING)
    memory_query = f"{goal}\nbatch_id={manifest.batch_id}\nphase={phase}"
    memory_hits, memory_recall_receipt, memory_warning = memory_store.recall(
        memory_query,
        limit=4,
    )
    initial_knowledge = retrieve_knowledge(goal, limit=6)
    recalled_context = [*initial_knowledge, *memory_hits]
    memory_status = RuntimeStatus.WARNING if memory_warning else RuntimeStatus.SUCCESS
    _set_task_status(
        tasks,
        memory_id,
        memory_status,
        output_refs=[item.source for item in recalled_context],
    )
    recorder.emit(
        phase=phase,
        stage=RuntimeStage.MEMORY,
        actor="Memory Broker",
        action="recall_context",
        status=memory_status,
        summary=(
            f"从 {memory_recall_receipt.candidate_count} 条候选记录中选择 "
            f"{len(memory_hits)} 条历史摘要，并召回 {len(initial_knowledge)} 张项目知识卡。"
            + (f" {memory_warning}" if memory_warning else "")
        ),
        task_id=memory_id,
        evidence_refs=[item.source for item in recalled_context],
    )

    plan_id = _task_id(phase, "plan")
    _set_task_status(tasks, plan_id, RuntimeStatus.RUNNING)
    allowed_tools, include_optional = _effective_allowed_tools(config)
    catalog = tool_catalog(include_optional=include_optional)
    required_names = [str(item["name"]) for item in catalog]
    selected = [name for name in required_names if name in allowed_tools][
        : config.max_tool_calls
    ]
    _set_task_status(tasks, plan_id, RuntimeStatus.SUCCESS, output_refs=selected)
    recorder.emit(
        phase=phase,
        stage=RuntimeStage.PLANNER,
        actor="Planner",
        action="build_dependency_graph",
        status=RuntimeStatus.SUCCESS,
        summary=f"生成 {len(selected)} 个并行 Worker 任务；Judge 等待全部必需工具回传。",
        task_id=plan_id,
        evidence_refs=[f"tool:{name}" for name in selected],
    )

    results: list[tuple[list[Finding], ToolTrace, dict[str, int | float | str]]] = []
    physical_tool_call_count = 0
    catalog_by_name = {str(item["name"]): item for item in catalog}
    with ThreadPoolExecutor(
        max_workers=min(config.parallel_workers, len(selected) or 1)
    ) as pool:
        futures = {}
        for name in selected:
            task_id = _task_id(phase, f"tool.{name}")
            _set_task_status(tasks, task_id, RuntimeStatus.RUNNING)
            submitted_at = time.perf_counter()
            future = pool.submit(
                execute_tool_with_bounded_retry,
                name,
                batch_root,
                manifest,
                contract,
                include_optional=include_optional,
                runner=tool_runner,
                batch_fingerprint=batch_fingerprint,
                configured_max_retries=config.max_retries,
            )
            futures[future] = (name, task_id, submitted_at)
        for future in as_completed(futures):
            name, task_id, submitted_at = futures[future]
            retry_count = 0
            try:
                tool_result, retry_count = future.result()
            except Exception as error:
                sequence = int(catalog_by_name[name]["sequence"])
                trace = _error_trace(
                    name,
                    sequence,
                    f"{type(error).__name__}: tool execution failed",
                    skipped=False,
                    include_optional=include_optional,
                )
                results.append(([], trace, {}))
                status = RuntimeStatus.ERROR
                refs: list[str] = []
                summary = f"{name} 执行失败，Judge 将 fail-closed。"
            else:
                findings, trace, _metrics = tool_result
                if trace.status != "ok":
                    status = RuntimeStatus.ERROR
                    refs = [f"trace:{trace.sequence}:{trace.tool}"]
                    summary = (
                        f"{name} response rejected after {retry_count} bounded "
                        "retries; Judge will fail closed."
                    )
                else:
                    status = RuntimeStatus.SUCCESS
                    refs = [item.finding_id for item in findings] or [
                        f"trace:{trace.sequence}:{trace.tool}"
                    ]
                    summary = (
                        f"{name} completed with {len(findings)} findings after "
                        f"{retry_count} bounded retries."
                    )
                results.append((findings, trace, _metrics))
            physical_tool_call_count += retry_count + 1
            _set_task_status(tasks, task_id, status, output_refs=refs)
            recorder.emit(
                phase=phase,
                stage=RuntimeStage.TOOL,
                actor=f"Worker/{name}",
                action="invoke_allowlisted_tool",
                status=status,
                summary=summary,
                task_id=task_id,
                tool_name=name,
                duration_ms=(time.perf_counter() - submitted_at) * 1000,
                evidence_refs=refs,
                retry=retry_count,
            )

    for name in required_names:
        if name in selected:
            continue
        item = catalog_by_name[name]
        message = "tool blocked by allowlist or tool-call budget"
        trace = _error_trace(
            name,
            int(item["sequence"]),
            message,
            skipped=True,
            include_optional=include_optional,
        )
        results.append(([], trace, {}))
        task_id = _task_id(phase, f"tool.{name}")
        _set_task_status(tasks, task_id, RuntimeStatus.SKIPPED)
        recorder.emit(
            phase=phase,
            stage=RuntimeStage.TOOL,
            actor=f"Worker/{name}",
            action="permission_check",
            status=RuntimeStatus.SKIPPED,
            summary=f"{name} 被权限或预算阻止；不会沿用旧结果。",
            task_id=task_id,
            tool_name=name,
        )

    results.sort(key=lambda item: item[1].sequence)
    findings: list[Finding] = []
    traces: list[ToolTrace] = []
    metrics: dict[str, int | float | str] = {
        "sample_count": len(manifest.samples),
        "tool_count": len(required_names),
        "tool_error_count": sum(item[1].status != "ok" for item in results),
    }
    for tool_findings, trace, tool_metrics in results:
        findings.extend(tool_findings)
        traces.append(trace)
        metrics.update(tool_metrics)
    findings.sort(key=lambda item: (item.tool, item.finding_id))
    metrics["finding_count"] = len(findings)

    policy_knowledge = retrieve_knowledge(goal, findings, limit=8)
    knowledge = list(
        {item.card_id: item for item in [*policy_knowledge, *memory_hits]}.values()
    )
    council_id = _task_id(phase, "council")
    _set_task_status(tasks, council_id, RuntimeStatus.RUNNING)
    council_started = time.perf_counter()
    council_build = build_council_with_backend(
        config,
        findings,
        traces,
        metrics,
        knowledge,
        api_key=api_key,
    )
    council_status = (
        RuntimeStatus.WARNING if council_build.fallback_used else RuntimeStatus.SUCCESS
    )
    council_refs = sorted(
        {
            ref
            for opinion in council_build.council.independent_opinions
            for ref in opinion.evidence_refs
        }
    )
    _set_task_status(tasks, council_id, council_status, output_refs=council_refs)
    recorder.emit(
        phase=phase,
        stage=RuntimeStage.COUNCIL,
        actor="AI Expert Council",
        action="review_and_cross_examine",
        status=council_status,
        summary=(
            f"五个 AI 角色完成证据解读与交叉质询；模型调用 {council_build.model_calls} 次"
            + ("，部分或全部使用确定性回退。" if council_build.fallback_used else "。")
        ),
        task_id=council_id,
        duration_ms=(time.perf_counter() - council_started) * 1000,
        evidence_refs=council_refs,
    )
    for opinion in council_build.council.independent_opinions:
        recorder.emit(
            phase=phase,
            stage=RuntimeStage.COUNCIL,
            actor=opinion.display_name,
            action="publish_advisory_opinion",
            status=RuntimeStatus.SUCCESS,
            summary=f"建议 {opinion.recommendation.value}；引用 {len(opinion.evidence_refs)} 项证据。",
            task_id=council_id,
            evidence_refs=opinion.evidence_refs,
        )

    judge_id = _task_id(phase, "judge")
    _set_task_status(tasks, judge_id, RuntimeStatus.RUNNING)
    judge_started = time.perf_counter()
    result = apply_policy(
        manifest,
        contract,
        findings,
        traces,
        metrics,
        council_build.council,
        scenario_profile=config.scenario_profile,
        input_sha256=digest,
        run_id=(f"agent-{phase}-{digest[:12]}-{execution_config_sha256[:12]}"),
    )
    output_refs = [f"decision:{result.decision.value}"] + [
        order.work_order_id for order in result.work_orders
    ]
    _set_task_status(tasks, judge_id, RuntimeStatus.SUCCESS, output_refs=output_refs)
    recorder.emit(
        phase=phase,
        stage=RuntimeStage.JUDGE,
        actor="Policy Judge",
        action="apply_fail_closed_policy",
        status=RuntimeStatus.SUCCESS,
        summary=f"冻结策略输出 {result.decision.value}，生成 {len(result.work_orders)} 份工单。",
        task_id=judge_id,
        duration_ms=(time.perf_counter() - judge_started) * 1000,
        evidence_refs=output_refs,
    )

    memory_write_receipt: MemoryWriteReceipt | None = None
    if config.persist_memory:
        _records, memory_write_receipt, _memory_write_warning = (
            memory_store.append_with_receipt(
                MemoryRecord(
                    run_id=result.run_id,
                    phase=phase,
                    batch_id=result.batch_id,
                    decision=result.decision.value,
                    finding_codes=sorted({item.code for item in findings}),
                    completed_tools=[
                        trace.tool for trace in traces if trace.status == "ok"
                    ],
                    backend=council_build.council.backend,
                    summary=(
                        f"工业视觉数据发布审核 {phase}: {result.decision.value}; "
                        f"{len(findings)} findings; "
                        f"{len(result.work_orders)} work orders"
                    ),
                )
            )
        )
    return GateAgentOutcome(
        result=result,
        knowledge=knowledge,
        council_build=council_build,
        tool_call_count=physical_tool_call_count,
        memory_recall_receipt=memory_recall_receipt,
        memory_write_receipt=memory_write_receipt,
    )


def run_agentic_demo(
    output_dir: str | Path,
    *,
    seed: int = 20260809,
    goal: str = (
        "审核工业视觉数据批次能否进入沙箱实验训练池；若阻断，生成可执行工单并在同合同下复验。"
    ),
    contract: BatchContract | None = None,
    config: RuntimeConfig | None = None,
    memory_path: str | Path | None = None,
    api_key: str | None = None,
    event_sink: EventSink | None = None,
    tool_runner: ToolRunner = run_tool,
) -> AgenticDemoRun:
    """Run the complete agentic closed loop and persist an inspectable trace."""

    output_root = Path(output_dir).expanduser().resolve()
    output_root.mkdir(parents=True, exist_ok=True)
    runtime_config = config or RuntimeConfig()
    execution_config_sha256 = _execution_config_digest(runtime_config)
    include_optional_tools = (
        runtime_config.scenario_profile is not ScenarioProfile.GENERIC
        or "governance_audit" in runtime_config.allowed_tools
    )
    resolved_memory = (
        Path(memory_path).expanduser().resolve()
        if memory_path is not None
        else output_root / "runtime_memory.json"
    )
    memory_store = LocalMemoryStore(resolved_memory)
    agentteams_contract = build_agentteams_contract(
        runtime_config.scenario_profile,
        allowed_tools=runtime_config.allowed_tools,
        include_optional=include_optional_tools,
        run_id=f"seed-{seed}",
    )
    verification_tasks = build_task_graph(
        "verification", include_optional=include_optional_tools
    )
    # The recheck must be causally downstream of the reserve operator.  Keeping
    # this edge in the typed DAG prevents a second pass from looking like an
    # unrelated clean run and makes a failed repair explicitly defer the
    # verification context.
    verification_tasks[0] = verification_tasks[0].model_copy(
        update={"dependencies": ["system.repair"]}
    )
    tasks = (
        build_task_graph("initial", include_optional=include_optional_tools)
        + [
            AgentTask(
                task_id="system.repair",
                title="执行 reserve 工单并准备复验",
                stage=RuntimeStage.REPAIR,
                actor="Repair Orchestrator",
                dependencies=["initial.judge"],
                capability="non-destructive-reserve-repair",
                permission_scope=["repair-output:write"],
            )
        ]
        + verification_tasks
        + [
            AgentTask(
                task_id="system.delivery",
                title="写入审计证据与运行时轨迹",
                stage=RuntimeStage.DELIVERY,
                actor="Evidence Delivery",
                dependencies=["verification.judge"],
                capability="canonical-evidence-packaging",
                permission_scope=["evidence-output:write"],
            )
        ]
    )
    recorder = _Recorder(
        event_sink,
        tasks=tasks,
        skills=agentteams_contract.skills,
    )

    started = time.perf_counter()
    recorder.emit(
        phase="system",
        stage=RuntimeStage.INTAKE,
        actor="Task Trigger",
        action="accept_goal",
        status=RuntimeStatus.SUCCESS,
        summary="接收目标并启动有界工业数据发布任务；不进入开放域聊天。",
        evidence_refs=["intent:industrial_vision_data_release_gate"],
    )
    dataset_paths = generate_demo_dataset(output_root / "dataset", seed=seed)
    contract_model = contract or BatchContract()
    manifest = _load_manifest(dataset_paths["batch_manifest"])
    truth = CorruptionManifest.model_validate_json(
        dataset_paths["corruption_manifest"].read_text(encoding="utf-8")
    )

    initial = _runtime_gate(
        dataset_paths["batch_root"],
        manifest,
        contract_model,
        phase="initial",
        goal=goal,
        config=runtime_config,
        recorder=recorder,
        tasks=tasks,
        memory_store=memory_store,
        api_key=api_key,
        execution_config_sha256=execution_config_sha256,
        tool_runner=tool_runner,
    )

    _set_task_status(tasks, "system.repair", RuntimeStatus.RUNNING)
    repair_started = time.perf_counter()
    investigation_orders = [
        item for item in initial.result.work_orders if item.action == "INVESTIGATE"
    ]
    if investigation_orders:
        repair = RepairResult(
            output_root=dataset_paths["batch_root"],
            manifest_path=dataset_paths["batch_manifest"],
            manifest=manifest,
            completed_work_orders=[],
            replacement_map={},
        )
        repair_refs = [item.work_order_id for item in investigation_orders]
        repair_status = RuntimeStatus.WARNING
        repair_summary = f"{len(investigation_orders)} 份调查工单不可自动执行；保持原批次并进入 fail-closed 复验。"
    else:
        repair = simulate_repair(
            dataset_paths["batch_root"],
            manifest,
            dataset_paths["reserve_manifest"],
            initial.result.work_orders,
            output_root=output_root / "repaired_batch",
        )
        repair_refs = [item.work_order_id for item in repair.completed_work_orders]
        if not repair_refs:
            # A clean batch still produces an explicit no-op receipt; an empty
            # list must not be confused with a missing upstream hand-off.
            repair_refs = ["repair:no_work_orders"]
        repair_status = RuntimeStatus.SUCCESS
        repair_summary = f"reserve 模拟完成 {len(repair.completed_work_orders)} 份工单，并生成独立修复目录。"
    _set_task_status(
        tasks,
        "system.repair",
        repair_status,
        output_refs=repair_refs,
    )
    recorder.emit(
        phase="system",
        stage=RuntimeStage.REPAIR,
        actor="Repair Orchestrator",
        action="execute_work_orders",
        status=repair_status,
        summary=repair_summary,
        task_id="system.repair",
        duration_ms=(time.perf_counter() - repair_started) * 1000,
        evidence_refs=repair_refs,
    )

    verification = _runtime_gate(
        repair.output_root,
        repair.manifest,
        contract_model,
        phase="verification",
        goal=f"复验：{goal}",
        config=runtime_config,
        recorder=recorder,
        tasks=tasks,
        memory_store=memory_store,
        api_key=api_key,
        execution_config_sha256=execution_config_sha256,
        tool_runner=tool_runner,
    )
    evaluation = evaluate_gate(truth, initial.result, verification.result)

    _set_task_status(tasks, "system.delivery", RuntimeStatus.RUNNING)
    evidence_dir = output_root / "evidence"
    initial_dir = evidence_dir / "initial"
    repaired_dir = evidence_dir / "repaired"
    write_evidence_artifacts(
        initial_dir,
        initial.result,
        evaluation,
        scenario_profile=runtime_config.scenario_profile,
    )
    write_offline_html(initial_dir / "report.html", initial.result, evaluation)
    write_evidence_artifacts(
        repaired_dir,
        verification.result,
        scenario_profile=runtime_config.scenario_profile,
    )
    write_offline_html(repaired_dir / "report.html", verification.result)

    phase_grounding_receipts = []
    endpoint_scopes: list[str] = []
    for phase_name, outcome in (
        ("initial", initial),
        ("verification", verification),
    ):
        receipt = outcome.council_build.grounding_receipt
        if receipt is None:
            continue
        endpoint_scopes.append(receipt.endpoint_scope)
        phase_grounding_receipts.extend(
            item.model_copy(update={"phase": phase_name})
            for item in receipt.role_receipts
        )
    endpoint_scope = (
        "remote"
        if "remote" in endpoint_scopes
        else "local"
        if "local" in endpoint_scopes
        else "none"
    )
    grounding_receipt = build_llm_grounding_receipt(
        backend=(
            initial.council_build.council.backend
            if initial.council_build.council.backend
            == verification.council_build.council.backend
            else (
                f"{initial.council_build.council.backend} -> "
                f"{verification.council_build.council.backend}"
            )
        ),
        model=runtime_config.model,
        endpoint_scope=endpoint_scope,
        role_receipts=phase_grounding_receipts,
        warnings=[
            *initial.council_build.warnings,
            *verification.council_build.warnings,
        ],
    )
    grounding_receipt_path = evidence_dir / "llm_grounding_receipt.json"
    write_canonical_json(grounding_receipt_path, grounding_receipt)
    phase_builds = (
        ("initial", initial.council_build),
        ("verification", verification.council_build),
    )
    model_transport_receipt_path = evidence_dir / "model_transport_receipt.json"
    write_canonical_json(
        model_transport_receipt_path,
        build_model_transport_runtime_receipt(phase_builds),
    )
    prompt_injection_receipt_path = (
        evidence_dir / "prompt_injection_runtime_receipt.json"
    )
    write_canonical_json(
        prompt_injection_receipt_path,
        build_prompt_guard_runtime_receipt(phase_builds),
    )
    backend_identity_receipt_path = (
        evidence_dir / "backend_identity_runtime_receipt.json"
    )
    write_canonical_json(
        backend_identity_receipt_path,
        build_backend_identity_runtime_receipt(phase_builds),
    )

    long_term, memory_warning = memory_store.load()
    semantic_by_id = {
        item.card_id: item for item in initial.knowledge + verification.knowledge
    }
    unresolved = list(initial.council_build.warnings) + list(
        verification.council_build.warnings
    )
    memory_receipts = [
        initial.memory_recall_receipt,
        verification.memory_recall_receipt,
        initial.memory_write_receipt,
        verification.memory_write_receipt,
    ]
    for receipt in memory_receipts:
        if (
            receipt is not None
            and receipt.warning
            and receipt.warning not in unresolved
        ):
            unresolved.append(receipt.warning)
    if memory_warning and memory_warning not in unresolved:
        unresolved.append(memory_warning)
    fallback_used = (
        initial.council_build.fallback_used or verification.council_build.fallback_used
    )
    trace_status = (
        RuntimeStatus.WARNING
        if fallback_used or unresolved or verification.result.decision.value != "PASS"
        else RuntimeStatus.SUCCESS
    )
    runtime_run_id = (
        f"runtime-{seed}-{initial.result.input_sha256[:10]}-"
        f"{execution_config_sha256[:10]}"
    )
    runtime_trace = RuntimeTrace(
        run_id=runtime_run_id,
        execution_config_sha256=execution_config_sha256,
        goal=goal,
        intent="industrial_vision_data_release_gate",
        backend=(
            initial.council_build.council.backend
            if initial.council_build.council.backend
            == verification.council_build.council.backend
            else f"{initial.council_build.council.backend} -> {verification.council_build.council.backend}"
        ),
        backend_connected=(
            initial.council_build.backend_connected
            and verification.council_build.backend_connected
        ),
        fallback_used=fallback_used,
        status=trace_status,
        tasks=tasks,
        events=recorder.events,
        memory=MemorySnapshot(
            working={
                "goal": goal,
                "seed": seed,
                "batch_id": manifest.batch_id,
                "initial_decision": initial.result.decision.value,
                "verification_decision": verification.result.decision.value,
                "elapsed_ms": round((time.perf_counter() - started) * 1000, 3),
            },
            session=[event.summary for event in recorder.events[-40:]],
            long_term=long_term,
            semantic=list(semantic_by_id.values()),
            role=role_memory(),
        ),
        model_call_count=(
            initial.council_build.model_calls + verification.council_build.model_calls
        ),
        tool_call_count=initial.tool_call_count + verification.tool_call_count,
        judge_decisions=[
            initial.result.decision.value,
            verification.result.decision.value,
        ],
        unresolved=unresolved,
        boundary_notice=initial.result.boundary_notice,
        scenario_profile=runtime_config.scenario_profile,
        agentteams=agentteams_contract,
        approval_handoff=ApprovalHandoff(
            scope="production_system",
            mode="external_authorization_required",
            status="blocked",
            required_role="真实授权主体 / 数据责任人 / 产线安全负责人",
            reason=(
                "本地运行只证明冻结合同下的沙箱资格与审计链；生产写回、客户数据使用和正式发布 "
                "不能由 Agent 或本地 PASS 代替授权。"
            ),
            evidence_refs=[
                f"initial_decision:{initial.result.decision.value}",
                f"verification_decision:{verification.result.decision.value}",
                "boundary:production_authorization_required",
            ],
        ),
        context_transfers=[],
        skill_executions=[],
    )
    runtime_trace_path = evidence_dir / "agent_runtime_trace.json"
    agentteams_path = evidence_dir / "agentteams_mapping.json"
    agentteams_runtime_receipt_path = (
        output_root / "agentteams_runtime_receipt.external.json"
    )
    approval_path = evidence_dir / "approval_handoff.json"
    memory_governance_path = evidence_dir / "memory_governance_receipt.json"
    final_memory_receipt = (
        verification.memory_write_receipt
        or initial.memory_write_receipt
        or verification.memory_recall_receipt
    )
    memory_governance = MemoryGovernanceReceipt(
        run_id=runtime_run_id,
        persist_memory=runtime_config.persist_memory,
        max_records=memory_store.max_records,
        final_store_existed=(
            final_memory_receipt.store_existed_before
            if isinstance(final_memory_receipt, MemoryWriteReceipt)
            and final_memory_receipt.action == "skip_invalid_store"
            else (
                True
                if isinstance(final_memory_receipt, MemoryWriteReceipt)
                and final_memory_receipt.action
                in {"write", "replace_same_run_phase", "skip_duplicate"}
                else final_memory_receipt.store_existed
            )
        ),
        final_store_sha256=(
            final_memory_receipt.store_after_sha256
            if isinstance(final_memory_receipt, MemoryWriteReceipt)
            else final_memory_receipt.store_sha256
        ),
        recall_receipts=[
            initial.memory_recall_receipt,
            verification.memory_recall_receipt,
        ],
        write_receipts=[
            item
            for item in (
                initial.memory_write_receipt,
                verification.memory_write_receipt,
            )
            if item is not None
        ],
    )
    write_canonical_json(memory_governance_path, memory_governance)
    approval_handoff = runtime_trace.approval_handoff
    if approval_handoff is not None:
        write_canonical_json(approval_path, approval_handoff)
    write_canonical_json(agentteams_path, agentteams_contract)
    agentteams_v122_paths = write_agentteams_v122_bundle(
        evidence_dir,
        agentteams_contract,
        runtime_receipt_path=(
            agentteams_runtime_receipt_path
            if agentteams_runtime_receipt_path.is_file()
            else None
        ),
    )

    summary = {
        "schema_version": "visiondata-gate.agentic-demo-summary.v2",
        "seed": seed,
        "runtime": {
            "run_id": runtime_trace.run_id,
            "execution_config_sha256": runtime_trace.execution_config_sha256,
            "backend": runtime_trace.backend,
            "model_call_count": runtime_trace.model_call_count,
            "tool_call_count": runtime_trace.tool_call_count,
            "event_count": len(runtime_trace.events),
            "trace": str(runtime_trace_path.relative_to(output_root)).replace(
                "\\", "/"
            ),
            "agentteams_mapping": str(agentteams_path.relative_to(output_root)).replace(
                "\\", "/"
            ),
            "agentteams_v122_resources": str(
                agentteams_v122_paths["resources"].relative_to(output_root)
            ).replace("\\", "/"),
            "agentteams_v122_skill_distribution": str(
                agentteams_v122_paths["skill_distribution"].relative_to(output_root)
            ).replace("\\", "/"),
            "agentteams_v122_conformance": str(
                agentteams_v122_paths["conformance"].relative_to(output_root)
            ).replace("\\", "/"),
            "approval_handoff": str(approval_path.relative_to(output_root)).replace(
                "\\", "/"
            ),
            "llm_grounding_receipt": str(
                grounding_receipt_path.relative_to(output_root)
            ).replace("\\", "/"),
            "memory_governance_receipt": str(
                memory_governance_path.relative_to(output_root)
            ).replace("\\", "/"),
            "model_transport_receipt": str(
                model_transport_receipt_path.relative_to(output_root)
            ).replace("\\", "/"),
            "prompt_injection_runtime_receipt": str(
                prompt_injection_receipt_path.relative_to(output_root)
            ).replace("\\", "/"),
            "backend_identity_runtime_receipt": str(
                backend_identity_receipt_path.relative_to(output_root)
            ).replace("\\", "/"),
        },
        "initial": {
            "decision": initial.result.decision.value,
            "finding_count": len(initial.result.findings),
            "run_id": initial.result.run_id,
        },
        "repair": {
            "completed_work_order_count": len(repair.completed_work_orders),
            "replacement_count": len(repair.replacement_map),
        },
        "repaired": {
            "decision": verification.result.decision.value,
            "finding_count": len(verification.result.findings),
            "run_id": verification.result.run_id,
        },
        "evaluation": evaluation.model_dump(mode="json"),
        "boundary": initial.result.boundary_notice,
    }
    summary_path = evidence_dir / "demo_summary.json"
    write_canonical_json(summary_path, summary)
    delivery_refs = [
        str(runtime_trace_path.relative_to(output_root)).replace("\\", "/"),
        str(summary_path.relative_to(output_root)).replace("\\", "/"),
        str(agentteams_path.relative_to(output_root)).replace("\\", "/"),
        str(agentteams_v122_paths["resources"].relative_to(output_root)).replace(
            "\\", "/"
        ),
        str(
            agentteams_v122_paths["skill_distribution"].relative_to(output_root)
        ).replace("\\", "/"),
        str(agentteams_v122_paths["conformance"].relative_to(output_root)).replace(
            "\\", "/"
        ),
        str(approval_path.relative_to(output_root)).replace("\\", "/"),
        str(grounding_receipt_path.relative_to(output_root)).replace("\\", "/"),
        str(memory_governance_path.relative_to(output_root)).replace("\\", "/"),
        str(model_transport_receipt_path.relative_to(output_root)).replace("\\", "/"),
        str(prompt_injection_receipt_path.relative_to(output_root)).replace("\\", "/"),
        str(backend_identity_receipt_path.relative_to(output_root)).replace("\\", "/"),
    ]
    _set_task_status(
        tasks,
        "system.delivery",
        RuntimeStatus.SUCCESS,
        output_refs=delivery_refs,
    )
    recorder.emit(
        phase="system",
        stage=RuntimeStage.DELIVERY,
        actor="Evidence Delivery",
        action="write_canonical_trace",
        status=RuntimeStatus.SUCCESS,
        summary="GateResult、报告、运行时事件、记忆快照和 canonical JSON 已落盘。",
        task_id="system.delivery",
        evidence_refs=delivery_refs,
    )
    # The final delivery event and task status are material, so rewrite the trace once.
    agentteams_contract = agentteams_contract.model_copy(
        update={
            "task_binding_count": len(tasks),
            "collaboration_event_count": sum(
                1 for event in recorder.events if event.collaboration
            ),
        }
    )
    _assert_context_transfer_coverage(tasks, recorder.context_transfers)
    runtime_trace = runtime_trace.model_copy(
        update={
            "tasks": tasks,
            "events": recorder.events,
            "agentteams": agentteams_contract,
            "context_transfers": recorder.context_transfers,
            "skill_executions": recorder.skill_executions,
        }
    )
    # Materialize the final trace before hashing/indexing it.  The proof packet
    # must never point at a pre-delivery or missing trace.
    write_canonical_json(runtime_trace_path, runtime_trace)
    acceptance_scorecard_path = evidence_dir / "acceptance_scorecard.json"
    acceptance_scorecard = build_acceptance_scorecard(
        task_id=runtime_trace.run_id,
        runtime_trace=runtime_trace,
        evaluation=evaluation,
        grounding_receipt=grounding_receipt,
    )
    write_canonical_json(acceptance_scorecard_path, acceptance_scorecard)
    # Build the reviewer proof packet only after the final delivery event is
    # present in the canonical trace.  The packet is navigation/integrity
    # evidence, not a new decision authority.
    proof_paths = {
        "runtime_trace": runtime_trace_path,
        "agentteams_mapping": agentteams_path,
        "agentteams_v122_resources": agentteams_v122_paths["resources"],
        "agentteams_v122_skill_distribution": agentteams_v122_paths[
            "skill_distribution"
        ],
        "agentteams_v122_conformance": agentteams_v122_paths["conformance"],
        "approval_handoff": approval_path,
        "llm_grounding_receipt": grounding_receipt_path,
        "memory_governance_receipt": memory_governance_path,
        "model_transport_receipt": model_transport_receipt_path,
        "prompt_injection_runtime_receipt": prompt_injection_receipt_path,
        "backend_identity_runtime_receipt": backend_identity_receipt_path,
        "acceptance_scorecard": acceptance_scorecard_path,
        "initial_gate_result": initial_dir / "gate_result.json",
        "initial_evidence_matrix": initial_dir / "evidence_matrix.csv",
        "repaired_gate_result": repaired_dir / "gate_result.json",
        "repaired_evidence_matrix": repaired_dir / "evidence_matrix.csv",
        "evaluation": initial_dir / "evaluation.json",
    }
    proof_hashes = write_proof_artifacts(
        evidence_dir,
        runtime_trace,
        initial.result,
        verification.result,
        evaluation,
        artifact_paths=proof_paths,
        artifact_root=output_root,
    )
    summary["runtime"]["proof_index"] = "evidence/proof_index.json"
    summary["runtime"]["observability_summary"] = "evidence/observability_summary.json"
    summary["runtime"]["reviewer_readiness"] = "evidence/reviewer_readiness.json"
    summary["runtime"]["reviewer_feedback_audit"] = (
        "evidence/reviewer_feedback_audit.json"
    )
    summary["runtime"]["tool_contract_snapshot"] = (
        "evidence/tool_contract_snapshot.json"
    )
    summary["runtime"]["runtime_contract_audit"] = (
        "evidence/runtime_contract_audit.json"
    )
    summary["runtime"]["validation_boundary"] = {
        "execution_mode": "separate_explicit_only",
        "automatic_intervention_evaluation": False,
        "commands": ["agent-eval", "tool-fault-eval"],
        "completion_rule": (
            "Runtime completion depends on this run's trace, GateResults and passive "
            "proof artifacts; intervention receipts belong to a later validation run."
        ),
    }
    summary["runtime"]["skill_qualification_receipt"] = (
        "evidence/skill_qualification_receipt.json"
    )
    summary["runtime"]["claim_scope_receipt"] = "evidence/claim_scope_receipt.json"
    summary["runtime"]["acceptance_scorecard"] = "evidence/acceptance_scorecard.json"
    summary["runtime"]["memory_governance_receipt"] = (
        "evidence/memory_governance_receipt.json"
    )
    summary["runtime"]["model_transport_receipt"] = (
        "evidence/model_transport_receipt.json"
    )
    summary["runtime"]["prompt_injection_runtime_receipt"] = (
        "evidence/prompt_injection_runtime_receipt.json"
    )
    summary["runtime"]["backend_identity_runtime_receipt"] = (
        "evidence/backend_identity_runtime_receipt.json"
    )
    summary["runtime"]["proof_artifact_hashes"] = proof_hashes
    # The delivery event is part of the final trace.  Rewrite the summary
    # after that event so its denormalized event count cannot lag the
    # canonical runtime trace by one entry.
    summary["runtime"]["event_count"] = len(runtime_trace.events)
    summary["runtime"]["task_binding_count"] = agentteams_contract.task_binding_count
    summary["runtime"]["collaboration_event_count"] = (
        agentteams_contract.collaboration_event_count
    )
    summary["runtime"]["skill_execution_count"] = len(runtime_trace.skill_executions)
    write_canonical_json(summary_path, summary)
    write_canonical_json(agentteams_path, agentteams_contract)
    if approval_handoff is not None:
        write_canonical_json(approval_path, approval_handoff)
    write_canonical_json(runtime_trace_path, runtime_trace)

    base = DemoRun(
        output_root=output_root,
        dataset_paths=dataset_paths,
        initial_result=initial.result,
        repair=repair,
        repaired_result=verification.result,
        evaluation=evaluation,
        evidence_dir=evidence_dir,
        summary_path=summary_path,
    )
    return AgenticDemoRun(
        base=base,
        runtime_trace=runtime_trace,
        runtime_trace_path=runtime_trace_path,
        memory_path=resolved_memory,
    )


__all__ = [
    "AgenticDemoRun",
    "GateAgentOutcome",
    "build_task_graph",
    "execute_tool_with_bounded_retry",
    "run_agentic_demo",
]
