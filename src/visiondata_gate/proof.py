"""Reviewer-facing proof and observability artifacts.

The runtime already emits a detailed trace, but a reviewer should not need to
read an entire event log to answer the basic questions: what ran, which
evidence supports the decision, where is the approval boundary, and what is
still only a local/synthetic claim.  This module creates two small, canonical
JSON artifacts from the same typed runtime objects:

* ``observability_summary.json`` contains trace-derived counts and health
  checks.  It intentionally does not pretend to be a live OTel collector.
* ``reviewer_readiness.json`` is a five-dimension, evidence-bounded readiness
  matrix.  It makes gaps visible without fabricating a judge score.
* ``proof_index.json`` is a claim-to-artifact index.  Every claim is tagged
  with its support level and bounded evidence references.

Neither artifact grants release authority or upgrades a local deterministic
run into a hosted AgentTeams deployment.
"""

from __future__ import annotations

from collections import Counter
from pathlib import Path
from typing import Any, Mapping

from .contracts import EvaluationResult, GateResult
from .evidence import canonical_json_bytes, sha256_bytes, sha256_file
from .reviewer_audit import (
    build_reviewer_feedback_audit,
    build_runtime_contract_audit,
    build_skill_qualification_receipt,
    build_tool_contract_snapshot,
)
from .runtime_models import RuntimeTrace


_VALIDATION_ARTIFACT_KEYS = frozenset(
    {
        "agent_eval_intervention_receipt",
        "tool_fault_intervention_receipt",
        "tool_replay_receipt",
        "tool_ablation_receipt",
    }
)


def _relative_path(path: Path, root: Path) -> str:
    try:
        return path.resolve().relative_to(root.resolve()).as_posix()
    except ValueError:
        return path.name


def build_observability_summary(trace: RuntimeTrace) -> dict[str, Any]:
    """Build a deterministic, trace-derived observability summary.

    Durations are retained because they are useful for local performance
    inspection, but no SLO or production latency claim is inferred from them.
    """

    stage_counts = Counter(event.stage.value for event in trace.events)
    status_counts = Counter(event.status.value for event in trace.events)
    actor_counts = Counter(event.actor for event in trace.events)
    tool_counts = Counter(
        event.tool_name for event in trace.events if event.tool_name is not None
    )
    durations = [float(event.duration_ms) for event in trace.events]
    sequences = [event.sequence for event in trace.events]
    task_ids = {task.task_id for task in trace.tasks}
    bound_tasks = {event.task_id for event in trace.events if event.task_id is not None}
    collaboration_bound = sum(
        bool(event.collaboration.get("team_id")) for event in trace.events
    )
    task_map = {task.task_id: task for task in trace.tasks}
    dependency_refs = {
        dependency for task in trace.tasks for dependency in task.dependencies
    }
    transfer_edges = [
        (item.source_task_id, item.task_id) for item in trace.context_transfers
    ]
    declared_edges = [
        (dependency, task.task_id)
        for task in trace.tasks
        for dependency in task.dependencies
    ]
    # Kahn's algorithm keeps this check deterministic and avoids introducing a
    # second scheduler: the runtime's explicit task graph is the source of
    # truth for coordination.
    indegree = {task_id: 0 for task_id in task_map}
    children: dict[str, set[str]] = {task_id: set() for task_id in task_map}
    for task in trace.tasks:
        for dependency in task.dependencies:
            if dependency in task_map:
                indegree[task.task_id] += 1
                children[dependency].add(task.task_id)
    ready = sorted(task_id for task_id, degree in indegree.items() if degree == 0)
    visited = 0
    while ready:
        current = ready.pop(0)
        visited += 1
        for child in sorted(children[current]):
            indegree[child] -= 1
            if indegree[child] == 0:
                ready.append(child)
                ready.sort()

    return {
        "schema_version": "visiondata-gate.observability-summary.v1",
        "run_id": trace.run_id,
        "adapter": "local-trace-derived",
        "channels": {
            "trace": "available",
            "metrics": "derived_from_trace",
            "logs": "embedded_event_summaries",
            "otel_collector": "not_connected",
        },
        "counts": {
            "events": len(trace.events),
            "tasks": len(trace.tasks),
            "task_statuses": dict(
                sorted(Counter(task.status.value for task in trace.tasks).items())
            ),
            "tool_calls": trace.tool_call_count,
            "model_calls": trace.model_call_count,
            "context_transfers": len(trace.context_transfers),
            "accepted_context_transfers": sum(
                item.status == "accepted" for item in trace.context_transfers
            ),
            "deferred_context_transfers": sum(
                item.status == "deferred" for item in trace.context_transfers
            ),
            "collaboration_bound_events": collaboration_bound,
            "unresolved_items": len(trace.unresolved),
        },
        "events_by_stage": dict(sorted(stage_counts.items())),
        "events_by_status": dict(sorted(status_counts.items())),
        "events_by_actor": dict(sorted(actor_counts.items())),
        "tool_event_counts": dict(sorted(tool_counts.items())),
        "duration_ms": {
            "sum": round(sum(durations), 3),
            "max": round(max(durations, default=0.0), 3),
            "nonzero_events": sum(value > 0 for value in durations),
        },
        "health_checks": {
            "event_sequence_contiguous": sequences
            == list(range(1, len(sequences) + 1)),
            "all_event_tasks_declared": bound_tasks <= task_ids,
            "all_task_dependencies_declared": dependency_refs <= task_ids,
            "task_dependency_graph_acyclic": visited == len(task_map),
            "all_events_have_agentteams_binding": collaboration_bound
            == len(trace.events),
            "agentteams_mapping_present": trace.agentteams is not None,
            "approval_handoff_present": trace.approval_handoff is not None,
            "decision_chain_present": len(trace.judge_decisions) >= 2,
            "context_transfer_edges_complete": (
                sorted(transfer_edges) == sorted(declared_edges)
            ),
            "context_transfer_hashes_present": all(
                len(item.payload_sha256) == 64 for item in trace.context_transfers
            ),
            "context_transfer_acceptance_basis_valid": all(
                item.acceptance_basis
                in {
                    "source_success_target_success",
                    "source_success_target_warning",
                    "source_not_success",
                    "target_not_runnable",
                    "source_success_without_output_refs",
                }
                for item in trace.context_transfers
            ),
            "context_transfer_runtime_event_bound": all(
                item.capture_mode == "runtime_event"
                and any(
                    event.sequence == item.recorded_event_sequence
                    and event.task_id == item.task_id
                    and event.status is item.target_status
                    for event in trace.events
                )
                for item in trace.context_transfers
            ),
        },
        "boundary": (
            "Counts are derived from one local run trace. They are not a live "
            "production SLO, hosted telemetry receipt, or industrial KPI."
        ),
    }


def _artifact_record(path: Path, root: Path, role: str) -> dict[str, Any]:
    if not path.is_file():
        return {
            "path": _relative_path(path, root),
            "role": role,
            "status": "missing",
        }
    return {
        "path": _relative_path(path, root),
        "role": role,
        "status": "present",
        "bytes": path.stat().st_size,
        "sha256": sha256_file(path),
    }


def build_reviewer_readiness(
    trace: RuntimeTrace,
    initial: GateResult,
    repaired: GateResult,
    evaluation: EvaluationResult,
) -> dict[str, Any]:
    """Build a reviewer-facing readiness matrix without estimating a score.

    The official rubric is represented as five weighted dimensions, but the
    weights are descriptive only.  ``local_status`` answers whether the
    deterministic project evidence is present; ``external_status`` records
    evidence that cannot be manufactured locally (for example a hosted
    AgentTeams receipt, customer validation, or a licence-owner confirmation).
    The top-level ``status`` is therefore deliberately conservative: a local
    pass with an external gap becomes ``PARTIAL`` rather than a guessed score.
    """

    health = build_observability_summary(trace)["health_checks"]
    snapshot = trace.agentteams
    identities = snapshot.identities if snapshot is not None else []
    skills = snapshot.skills if snapshot is not None else []
    role_types = {item.role_type for item in identities}
    local_multi_agent = bool(
        snapshot
        and len(identities) >= 3
        and {"manager", "team_leader", "worker", "reviewer", "judge"} <= role_types
        and snapshot.task_binding_count == len(trace.tasks)
        and snapshot.collaboration_event_count == len(trace.events)
        and all(event.collaboration.get("team_id") for event in trace.events)
    )
    local_skill = bool(
        skills
        and all(
            skill.input_contract
            and skill.output_contract
            and skill.call_conditions
            and skill.dependencies
            and skill.failure_modes
            and skill.safety_boundary
            and skill.reusable_value
            and skill.quality_metrics
            and skill.version_history
            and skill.rollback_strategy
            for skill in skills
        )
    )
    local_scene = bool(
        initial.work_orders
        and initial.tool_trace
        and initial.rule_checks
        and repaired.decision.value in {"PASS", "DEFER", "RECAPTURE", "QUARANTINE"}
    )
    local_engineering = bool(
        evaluation.post_repair_correct_pass
        and evaluation.work_order_recall >= 1.0
        and health["event_sequence_contiguous"]
        and health["all_event_tasks_declared"]
        and health["all_events_have_agentteams_binding"]
        and health["approval_handoff_present"]
        and len(trace.judge_decisions) >= 2
    )

    def dimension(
        *,
        dimension_id: str,
        label: str,
        weight: int,
        local_ok: bool,
        external_status: str,
        evidence_refs: list[str],
        verified_now: list[str],
        gaps: list[str],
        reviewer_check: list[str],
        local_basis: str,
    ) -> dict[str, Any]:
        if not local_ok:
            status = "OPEN"
        elif external_status == "PASS":
            status = "PASS"
        else:
            status = "PARTIAL"
        return {
            "dimension_id": dimension_id,
            "label": label,
            "weight_percent": weight,
            "status": status,
            "local_status": "PASS" if local_ok else "OPEN",
            "external_status": external_status,
            "evidence_layer": "local_artifact_plus_external_boundary",
            "local_basis": local_basis,
            "evidence_refs": evidence_refs,
            "verified_now": verified_now,
            "gaps": gaps,
            "reviewer_check": reviewer_check,
            "score_policy": (
                "This status is a readiness label, not an official score or a "
                "prediction of ranking."
            ),
        }

    dimensions = [
        dimension(
            dimension_id="scene_value",
            label="场景价值与行业可复制性",
            weight=25,
            local_ok=local_scene,
            external_status="OPEN",
            evidence_refs=[
                "docs/GOAI_material_alignment_20260812.md",
                "initial/gate_result.json",
                "repaired/gate_result.json",
                "initial/evidence_matrix.csv",
                "repaired/evidence_matrix.csv",
            ],
            verified_now=[
                "工业视觉图像与标注进入沙箱训练池前的发布门禁闭环可运行",
                "finding → work order → rule check → recheck 链路可追溯",
                "场景边界明确为数据发布门禁，不冒充设备运维或产线验收",
            ],
            gaps=[
                "尚无经授权的真实工业数据、客户 shadow test 或现场 KPI",
                "跨企业/跨工厂复制价值仍需外部案例验证",
            ],
            reviewer_check=[
                "核对目标用户、输入合同、放行边界与实际工单是否一致",
                "要求查看一份脱敏真实数据或现场 shadow test 回执",
            ],
            local_basis="typed contract + deterministic closed-loop run",
        ),
        dimension(
            dimension_id="multi_agent_collaboration",
            label="多 Agent 协同与自主闭环",
            weight=25,
            local_ok=local_multi_agent,
            external_status="OPEN",
            evidence_refs=[
                "agentteams_mapping.json#/context_flow",
                "agent_runtime_trace.json#/tasks",
                "agent_runtime_trace.json#/events",
                "docs/AGENTTEAMS_ALIGNMENT.md",
            ],
            verified_now=[
                "Manager → Leader → Worker → Council → Judge → Operator 有 typed task/context 绑定",
                "并行 Worker 的结果按冻结序号汇总，缺证据时 fail-closed",
                "AgentTeams Team/Room/Task/Identity/Skill 契约已映射并可审计",
            ],
            gaps=[
                "当前 connection_status=mapped_not_connected，不是 hosted AgentTeams/Matrix 回执",
            ],
            reviewer_check=[
                "抽查一条 task binding 是否能跳到对应 ToolTrace、RuleCheck 和交付文件",
                "如声称 hosted 运行，要求提供平台登录/运行 receipt",
            ],
            local_basis="AgentTeams contract mapping + complete runtime trace",
        ),
        dimension(
            dimension_id="skill_engineering",
            label="Skill 工程体系与生态复用",
            weight=25,
            local_ok=local_skill,
            external_status="OPEN",
            evidence_refs=[
                "agentteams_mapping.json#/skills",
                "skills/manifest.json",
                "docs/AGENTTEAMS_ALIGNMENT.md",
            ],
            verified_now=[
                "五类 Skill 均声明输入、输出、调用条件、依赖、失败模式和安全边界",
                "Skill 具备质量指标、版本历史与回滚策略，能被不同场景规则包复用",
            ],
            gaps=[
                "尚未提交独立生态仓库、外部复用案例或第三方贡献回执",
            ],
            reviewer_check=[
                "任选一个 Skill，按输入 → 输出 → 失败 → 回滚路径复跑",
                "核对版本演进是否会改变 Policy Judge 的输入契约",
            ],
            local_basis="versioned SkillContract snapshot",
        ),
        dimension(
            dimension_id="engineering_safety",
            label="工程落地、运行验证与安全审计",
            weight=20,
            local_ok=local_engineering,
            external_status="OPEN",
            evidence_refs=[
                "observability_summary.json",
                "proof_index.json",
                "approval_handoff.json",
                "initial/evaluation.json",
                "docs/REVIEWER_SCENARIO_MATRIX.md",
            ],
            verified_now=[
                "默认闭环为 RECAPTURE → PASS，缺 Worker/工具异常/篡改/审批缺失均有负路径",
                "reserve-only repair、同合同复验、SHA-256 证据包和 Approval Handoff 已落盘",
                "0..31 seed truth match、AppTest 与静态 QA 均有独立记录",
            ],
            gaps=[
                "尚无生产系统接入、真实部署 SLO、企业身份审批或安全认证",
            ],
            reviewer_check=[
                "先跑 missing-worker、tool-error、evidence-tamper、approval-missing 四类负路径",
                "核对 PASS 只代表 sandbox eligibility，不是生产授权",
            ],
            local_basis="trace health + deterministic QA + explicit authorization boundary",
        ),
        dimension(
            dimension_id="open_source_contribution",
            label="开放/开源贡献",
            weight=5,
            local_ok=True,
            external_status="OPEN",
            evidence_refs=[
                "LICENSE",
                "NOTICE",
                "docs/SBOM.cdx.json",
                "docs/THIRD_PARTY_LICENSE_INVENTORY.generated.md",
                "docs/data_privacy_license_boundaries.md",
            ],
            verified_now=[
                "顶层 Apache-2.0 LICENSE、NOTICE、SBOM 与第三方依赖许可清单均已纳入版本控制",
                "锁定组件（含根项目）的 REVIEW_REQUIRED 为 0，精确数量由 SBOM 生成物给出；提交包排除密钥和运行痕迹",
            ],
            gaps=[
                "本地许可证与供应链清单不构成独立法律意见，也不授权外部数据、模型或客户资产",
                "尚无第三方复用案例、外部贡献或生态采用回执",
                "公开远程仓库与 tag 的在线可达性需在提交时另存实时回执",
            ],
            reviewer_check=[
                "核对 Apache-2.0、NOTICE、依赖许可证与代码/外部资产可再分发边界",
                "在线核验公开仓库、版本 tag 与提交版本 SHA",
            ],
            local_basis="tracked Apache-2.0/NOTICE + deterministic SBOM with zero REVIEW_REQUIRED",
        ),
    ]
    status_counts = Counter(item["status"] for item in dimensions)
    return {
        "schema_version": "visiondata-gate.reviewer-readiness.v1",
        "run_id": trace.run_id,
        "decision_chain": [initial.decision.value, repaired.decision.value],
        "dimensions": dimensions,
        "status_counts": dict(sorted(status_counts.items())),
        "local_verified_dimension_count": sum(
            item["local_status"] == "PASS" for item in dimensions
        ),
        "external_open_dimension_count": sum(
            item["external_status"] == "OPEN" for item in dimensions
        ),
        "reviewer_reading_order": [
            "reviewer_readiness.json#/dimensions",
            "observability_summary.json#/health_checks",
            "proof_index.json#/claims",
            "initial/evidence_matrix.csv",
            "repaired/evidence_matrix.csv",
            "approval_handoff.json",
        ],
        "comparison_basis": [
            "official rubric and track material",
            "public competitor self-descriptions used only as engineering-pattern references",
            "local deterministic runtime artifacts",
        ],
        "boundary": (
            "This matrix is a reviewer navigation and gap disclosure artifact. "
            "It is not an official judge evaluation, score prediction, hosted "
            "AgentTeams receipt, customer validation, or production certification."
        ),
    }


def build_proof_index(
    trace: RuntimeTrace,
    initial: GateResult,
    repaired: GateResult,
    evaluation: EvaluationResult,
    *,
    artifact_paths: Mapping[str, Path],
    artifact_root: Path,
) -> dict[str, Any]:
    """Map reviewer-facing claims to bounded, inspectable evidence."""

    initial_tool_refs = [
        f"initial/gate_result.json#/tool_trace/{item.sequence - 1}"
        for item in initial.tool_trace
    ]
    claims = [
        {
            "claim_id": "reviewer_readiness_matrix",
            "statement": "五个官方评审维度被映射到本地可核验产物，并把 hosted、真实客户、许可证等外部缺口显式标为 PARTIAL/OPEN。",
            "support_level": "reviewer_navigation",
            "evidence_refs": [
                "reviewer_readiness.json#/dimensions",
                "docs/REVIEWER_READINESS_MATRIX.md",
            ],
        },
        {
            "claim_id": "task_decomposition",
            "statement": "任务被拆解为有依赖关系的 typed tasks，并保留任务状态。",
            "support_level": "verified_local",
            "evidence_refs": [
                "agent_runtime_trace.json#/tasks",
                "observability_summary.json#/health_checks/all_event_tasks_declared",
            ],
        },
        {
            "claim_id": "context_transfer",
            "statement": "上下文在 Manager、Leader、Worker、Council、Judge 与 Operator 之间显式传递。",
            "support_level": "verified_local",
            "evidence_refs": [
                "agentteams_mapping.json#/context_flow",
                "agent_runtime_trace.json#/context_transfers",
                "runtime_contract_audit.json#/checks/context_transfer_edges_complete",
            ],
        },
        {
            "claim_id": "allowlisted_measurement",
            "statement": "测量来自白名单工具回执；工具异常或缺失不被模型补写。",
            "support_level": "verified_local",
            "evidence_refs": initial_tool_refs
            + [
                "initial/gate_result.json#/tool_trace",
                "initial/gate_result.json#/metrics",
            ],
        },
        {
            "claim_id": "policy_authority",
            "statement": "Policy Judge 产生唯一 GateDecision，Council 仅提供 advisory 解释。",
            "support_level": "verified_local",
            "evidence_refs": [
                "initial/gate_result.json#/decision",
                "initial/gate_result.json#/rule_checks",
                "initial/gate_result.json#/council_trace",
            ],
        },
        {
            "claim_id": "repair_recheck",
            "statement": "工单在 reserve 副本执行，并用同一合同复验后才形成复核结果。",
            "support_level": "verified_local",
            "evidence_refs": [
                "initial/evidence_matrix.csv",
                "repaired/evidence_matrix.csv",
                "repaired/gate_result.json#/decision",
                "initial/evaluation.json",
            ],
        },
        {
            "claim_id": "negative_path",
            "statement": "必需 Worker 缺失时，系统保持 DEFER，不复用历史 PASS 或伪造修复。",
            "support_level": "verified_local_contract",
            "evidence_refs": [
                "agentteams_mapping.json#/failure_routes",
                "approval_handoff.json#/status",
                "docs/REVIEWER_SCENARIO_MATRIX.md",
            ],
        },
        {
            "claim_id": "authorization_boundary",
            "statement": "生产写回仍需外部授权；本地 PASS 只允许进入沙箱实验训练池。",
            "support_level": "verified_boundary",
            "evidence_refs": [
                "approval_handoff.json",
                "agent_runtime_trace.json#/boundary_notice",
            ],
        },
        {
            "claim_id": "scope_boundary",
            "statement": "当前指标来自合成数据与本地 deterministic adapter，不外推为真实工业效果。",
            "support_level": "explicit_limitation",
            "evidence_refs": [
                "initial/evaluation.json#/notes",
                "README.md#边界",
                "docs/GOAI_REVIEWER_FEEDBACK_AUDIT_20260812.md",
            ],
        },
        {
            "claim_id": "reviewer_feedback_audit",
            "statement": (
                "官方/导师口径、他队公开自述与本地工程证据被分层记录，并将评审追问映射到可核验的缺口与下一步。"
            ),
            "support_level": "reviewer_navigation",
            "evidence_refs": [
                "reviewer_feedback_audit.json#/items",
                "docs/GOAI_REVIEWER_FEEDBACK_AUDIT_20260812.md",
            ],
        },
        {
            "claim_id": "tool_contract_necessity_and_migration",
            "statement": (
                "每个被观察工具均有输入输出契约、权限/副作用、幂等、失败处理、可替换性与 MCP 迁移门。"
            ),
            "support_level": "verified_local_contract",
            "evidence_refs": [
                "tool_contract_snapshot.json#/tools",
                "docs/TOOLS_AND_MCP_CONTRACT.md",
            ],
        },
        {
            "claim_id": "runtime_skill_qualification",
            "statement": (
                "每个终态任务均绑定实际 Skill ID/版本/合约摘要与 terminal event；"
                "输入输出引用可复算，失败调用进入带回滚动作的 deferred。"
            ),
            "support_level": "verified_local_skill_execution",
            "evidence_refs": [
                "agent_runtime_trace.json#/skill_executions",
                "skill_qualification_receipt.json#/checks",
                "runtime_contract_audit.json#/skill_qualification",
            ],
        },
        {
            "claim_id": "runtime_contract_integrity",
            "statement": (
                "本次运行的任务 DAG、AgentTeams 绑定、工具契约摘要、Policy Judge 唯一权限、同合同复验和证据链通过独立一致性审计。"
            ),
            "support_level": "verified_local_contract",
            "evidence_refs": [
                "runtime_contract_audit.json#/checks",
                "agent_runtime_trace.json#/tasks",
                "agent_runtime_trace.json#/events",
            ],
        },
        {
            "claim_id": "context_transfer_receipt",
            "statement": (
                "本次运行将 DAG 依赖边物化为 ContextTransfer 台账，记录源/目标 Agent、"
                "任务、源/目标状态、产出 digest、接受依据和 payload hash；失败上游不会伪装成已接受上下文。"
            ),
            "support_level": "verified_local_contract",
            "evidence_refs": [
                "agent_runtime_trace.json#/context_transfers",
                "runtime_contract_audit.json#/context_transfers",
                "runtime_contract_audit.json#/checks/context_transfer_task_refs_match",
            ],
        },
    ]
    if "tool_ablation_receipt" in artifact_paths:
        claims.append(
            {
                "claim_id": "tool_ablation_necessity",
                "statement": (
                    "显式验证阶段的逐工具消融回执显示：删除任一观测工具不会让"
                    "冻结策略变得更宽松，并暴露新增失败规则与丢失的 finding 证据。"
                ),
                "support_level": "verified_local_ablation",
                "evidence_refs": [
                    "tool_ablation_receipt.json#/phases",
                    "runtime_contract_audit.json#/checks/typed_tool_contracts_bound",
                ],
            }
        )
    if "agent_eval_intervention_receipt" in artifact_paths:
        claims.append(
            {
                "claim_id": "agent_evaluator_sensitivity",
                "statement": (
                    "显式验证阶段的本地规则评测器通过固定故障干预反测，并用一条"
                    "保持结果与合同不变的并行 Worker 调度变体检查误报；该回执"
                    "不等同于 Agent 能力分数。"
                ),
                "support_level": "verified_local_evaluator_sensitivity",
                "evidence_refs": [
                    "agent_eval_intervention_receipt.json#/summary",
                    "agent_eval_intervention_receipt.json#/interventions",
                    "agent_eval_intervention_receipt.json#/valid_trajectory_controls",
                ],
            }
        )
    if "tool_fault_intervention_receipt" in artifact_paths:
        claims.append(
            {
                "claim_id": "runtime_tool_fault_fail_closed",
                "statement": (
                    "运行时 Tool Gateway 对 timeout、stale response、malformed payload、"
                    "permission denied 与 poisoned contract 五类故障逐项生成 typed error "
                    "trace，冻结 Policy Judge 均保持 DEFER。"
                ),
                "support_level": "verified_local_fault_intervention",
                "evidence_refs": [
                    "tool_fault_intervention_receipt.json#/summary",
                    "tool_fault_intervention_receipt.json#/interventions",
                ],
            }
        )

    if "model_transport_receipt" in artifact_paths:
        claims.append(
            {
                "claim_id": "bounded_model_transport",
                "statement": (
                    "可选模型调用使用 host allowlist、显式 deadline、有限重试、"
                    "熔断状态和禁重定向回执；本次未调用时保持 NOT_ATTEMPTED。"
                ),
                "support_level": "verified_runtime_transport_boundary",
                "evidence_refs": [
                    "model_transport_receipt.json#/status",
                    "model_transport_receipt.json#/requests",
                ],
            }
        )
    if "prompt_injection_runtime_receipt" in artifact_paths:
        claims.append(
            {
                "claim_id": "prompt_injection_preflight",
                "statement": (
                    "所有进入可选模型上下文的 evidence/tool/memory 文本先经过本地"
                    "注入前置门；命中时模型调用被阻断并确定性回退，Judge 权限不变。"
                ),
                "support_level": "verified_runtime_guard_boundary",
                "evidence_refs": [
                    "prompt_injection_runtime_receipt.json#/status",
                    "prompt_injection_runtime_receipt.json#/phases",
                ],
            }
        )
    if "backend_identity_runtime_receipt" in artifact_paths:
        claims.append(
            {
                "claim_id": "external_backend_identity_boundary",
                "statement": (
                    "LongCat/OpenAI-compatible 后端身份与真实连接状态单独记录；"
                    "contract fixture、token 或代码存在不升级为真实后端已连接。"
                ),
                "support_level": "verified_connection_claim_boundary",
                "evidence_refs": [
                    "backend_identity_runtime_receipt.json#/status",
                    "backend_identity_runtime_receipt.json#/phases",
                ],
            }
        )

    artifact_records = [
        _artifact_record(path, artifact_root, role)
        for role, path in sorted(artifact_paths.items())
    ]
    indexed_validations = sorted(
        key
        for key in _VALIDATION_ARTIFACT_KEYS
        if key in artifact_paths and artifact_paths[key].is_file()
    )
    health = build_observability_summary(trace)["health_checks"]
    return {
        "schema_version": "visiondata-gate.proof-index.v1",
        "proof_id": f"proof-{trace.run_id}",
        "run_id": trace.run_id,
        "decision_chain": [initial.decision.value, repaired.decision.value],
        "evaluation": {
            "precision": evaluation.precision,
            "recall": evaluation.recall,
            "f1": evaluation.f1,
            "work_order_recall": evaluation.work_order_recall,
            "post_repair_correct_pass": evaluation.post_repair_correct_pass,
        },
        "claims": claims,
        "artifact_index": artifact_records,
        "validation_boundary": {
            "execution_mode": "separate_explicit_only",
            "runtime_writer_executes_interventions": False,
            "indexed_validation_artifacts": indexed_validations,
            "commands": ["agent-eval", "tool-fault-eval"],
            "completion_rule": (
                "Validation receipts may support a later validation report, but they are "
                "not generated by or required to complete this runtime evidence write."
            ),
        },
        "integrity": {
            "all_declared_artifacts_present": all(
                item["status"] == "present" for item in artifact_records
            ),
            "trace_health_checks": health,
        },
        "boundary": (
            "A proof index is a reviewer navigation and integrity aid. It is not "
            "an electronic signature, production authorization, hosted AgentTeams "
            "receipt, or real-customer validation."
        ),
    }


def build_claim_scope_receipt(
    trace: RuntimeTrace,
    *,
    validation_artifacts: Mapping[str, Path] | None = None,
) -> dict[str, Any]:
    """Freeze allowed claims and explicit non-claims for downstream materials."""

    snapshot = trace.agentteams
    agentteams_connected = bool(
        snapshot
        and snapshot.connection_status == "connected"
        and snapshot.matrix_connected
    )
    validation_artifacts = validation_artifacts or {}
    indexed_validations = sorted(
        key
        for key in _VALIDATION_ARTIFACT_KEYS
        if key in validation_artifacts and validation_artifacts[key].is_file()
    )
    allowed_claims = [
        {
            "claim_id": "local_closed_loop",
            "status": "VERIFIED_LOCAL",
            "statement": "本地确定性运行完成合同、工具、Council、门禁、工单、reserve 修复、同合同复验与证据交付。",
            "evidence_refs": [
                "agent_runtime_trace.json",
                "runtime_contract_audit.json",
                "proof_index.json",
            ],
        },
        {
            "claim_id": "agentteams_contract_conformance",
            "status": "VERIFIED_LOCAL_CONTRACT",
            "statement": "已导出 AgentTeams v1.2.2 Worker/Team 资源与 Skill 分发契约，并通过静态 conformance。",
            "evidence_refs": [
                "agentteams_v122_resources.yaml",
                "agentteams_v122_skill_distribution.json",
                "agentteams_v122_conformance.json#/static_status",
            ],
        },
        {
            "claim_id": "synthetic_demo_metrics",
            "status": "VERIFIED_SYNTHETIC_ONLY",
            "statement": "冻结指标只来自程序化合成隐藏真值与本地 deterministic adapter。",
            "evidence_refs": [
                "initial/evaluation.json",
                "demo_summary.json#/evaluation",
            ],
        },
        {
            "claim_id": "transcript_reviewed",
            "status": "SOURCE_REVIEWED_AUDIO_TRANSCRIPT",
            "statement": "已完整审阅用户提供的头脑风暴会录音转写 1111.docx；该回放没有画面，未据此核验任何视觉内容。",
            "evidence_refs": [
                "docs/GOAI_material_alignment_20260812.md",
                "docs/GOAI_REVIEWER_FEEDBACK_AUDIT_20260812.md",
            ],
        },
    ]
    if "tool_fault_intervention_receipt" in indexed_validations:
        allowed_claims.append(
            {
                "claim_id": "runtime_tool_fault_fail_closed",
                "status": "VERIFIED_LOCAL_SYNTHETIC",
                "statement": "显式验证阶段的五类冻结工具响应故障在本地合成 fixture 上均生成 typed error trace，并由 Policy Judge 保持 DEFER。",
                "evidence_refs": [
                    "tool_fault_intervention_receipt.json",
                    "proof_index.json#/claims",
                ],
            }
        )
    return {
        "schema_version": "visiondata-gate.claim-scope-receipt.v1",
        "run_id": trace.run_id,
        "allowed_claims": allowed_claims,
        "validation_boundary": {
            "execution_mode": "separate_explicit_only",
            "runtime_writer_executes_interventions": False,
            "indexed_validation_artifacts": indexed_validations,
        },
        "prohibited_claims": [
            {
                "claim_id": "hosted_agentteams_connected",
                "status": "VERIFIED" if agentteams_connected else "NOT_VERIFIED",
                "observed": agentteams_connected,
                "statement": "不得宣称 hosted AgentTeams/Matrix 已连接，除非真实 runtime receipt 通过原始文件哈希门禁。",
            },
            {
                "claim_id": "real_customer_validation",
                "status": "NOT_AVAILABLE",
                "observed": False,
                "statement": "不得宣称已有真实客户、企业访谈、shadow test 或客户收益。",
            },
            {
                "claim_id": "real_industrial_data",
                "status": "NOT_AVAILABLE",
                "observed": False,
                "statement": "不得将合成数据指标表述为真实工业数据效果。",
            },
            {
                "claim_id": "production_deployment",
                "status": "NOT_AVAILABLE",
                "observed": False,
                "statement": "不得宣称生产部署、生产授权、安全认证或产线验收。",
            },
            {
                "claim_id": "official_submission_receipt",
                "status": "NOT_AVAILABLE",
                "observed": False,
                "statement": "不得宣称官网已提交、已晋级或已获得官方评分。",
            },
            {
                "claim_id": "human_expert_council",
                "status": "FALSE_BY_DESIGN",
                "observed": False,
                "statement": "不得把 AI Council 写成真人专家或多个独立模型；角色共享后端且只有 advisory 权限。",
            },
            {
                "claim_id": "visual_replay_reviewed",
                "status": "NOT_APPLICABLE_NO_VIDEO",
                "observed": False,
                "statement": "1111 是录音转写且没有画面，不得声称审阅过回放视觉内容。",
            },
        ],
        "guard": {
            "all_unavailable_claims_unobserved": not agentteams_connected,
            "material_rule": (
                "PPT、PDF、视频、表单文案和 UI 必须从 allowed_claims 取证；"
                "prohibited_claims 只能作为缺口或边界出现。"
            ),
        },
    }


def write_proof_artifacts(
    output_dir: str | Path,
    trace: RuntimeTrace,
    initial: GateResult,
    repaired: GateResult,
    evaluation: EvaluationResult,
    *,
    artifact_paths: Mapping[str, Path],
    artifact_root: Path,
) -> dict[str, str]:
    """Write passive, run-derived proof artifacts and return their hashes.

    This writer never mutates evidence, replays tools, injects faults, or runs
    ablations.  Explicit validation commands own those activities and may pass
    already-materialized receipts through ``artifact_paths`` for indexing.
    """

    root = Path(output_dir)
    root.mkdir(parents=True, exist_ok=True)
    readiness = build_reviewer_readiness(trace, initial, repaired, evaluation)
    readiness_path = root / "reviewer_readiness.json"
    readiness_bytes = canonical_json_bytes(readiness)
    readiness_path.write_bytes(readiness_bytes)
    observability = build_observability_summary(trace)
    observability_path = root / "observability_summary.json"
    observability_bytes = canonical_json_bytes(observability)
    observability_path.write_bytes(observability_bytes)

    reviewer_audit = build_reviewer_feedback_audit(trace, initial, repaired, evaluation)
    reviewer_audit_path = root / "reviewer_feedback_audit.json"
    reviewer_audit_bytes = canonical_json_bytes(reviewer_audit)
    reviewer_audit_path.write_bytes(reviewer_audit_bytes)
    tool_contract = build_tool_contract_snapshot(trace, initial, repaired)
    tool_contract_path = root / "tool_contract_snapshot.json"
    tool_contract_bytes = canonical_json_bytes(tool_contract)
    tool_contract_path.write_bytes(tool_contract_bytes)
    runtime_audit = build_runtime_contract_audit(trace, initial, repaired)
    runtime_audit_path = root / "runtime_contract_audit.json"
    runtime_audit_bytes = canonical_json_bytes(runtime_audit)
    runtime_audit_path.write_bytes(runtime_audit_bytes)
    skill_qualification = build_skill_qualification_receipt(trace)
    skill_qualification_path = root / "skill_qualification_receipt.json"
    skill_qualification_bytes = canonical_json_bytes(skill_qualification)
    skill_qualification_path.write_bytes(skill_qualification_bytes)
    claim_scope = build_claim_scope_receipt(
        trace,
        validation_artifacts=artifact_paths,
    )
    claim_scope_path = root / "claim_scope_receipt.json"
    claim_scope_bytes = canonical_json_bytes(claim_scope)
    claim_scope_path.write_bytes(claim_scope_bytes)

    proof_paths = dict(artifact_paths)
    proof_paths["reviewer_readiness"] = readiness_path
    proof_paths["observability_summary"] = observability_path
    proof_paths["reviewer_feedback_audit"] = reviewer_audit_path
    proof_paths["tool_contract_snapshot"] = tool_contract_path
    proof_paths["runtime_contract_audit"] = runtime_audit_path
    proof_paths["skill_qualification_receipt"] = skill_qualification_path
    proof_paths["claim_scope_receipt"] = claim_scope_path
    proof = build_proof_index(
        trace,
        initial,
        repaired,
        evaluation,
        artifact_paths=proof_paths,
        artifact_root=artifact_root,
    )
    proof_path = root / "proof_index.json"
    proof_bytes = canonical_json_bytes(proof)
    proof_path.write_bytes(proof_bytes)
    return {
        "reviewer_readiness.json": sha256_bytes(readiness_bytes),
        "observability_summary.json": sha256_bytes(observability_bytes),
        "reviewer_feedback_audit.json": sha256_bytes(reviewer_audit_bytes),
        "tool_contract_snapshot.json": sha256_bytes(tool_contract_bytes),
        "runtime_contract_audit.json": sha256_bytes(runtime_audit_bytes),
        "skill_qualification_receipt.json": sha256_bytes(skill_qualification_bytes),
        "claim_scope_receipt.json": sha256_bytes(claim_scope_bytes),
        "proof_index.json": sha256_bytes(proof_bytes),
    }


__all__ = [
    "build_claim_scope_receipt",
    "build_observability_summary",
    "build_reviewer_readiness",
    "build_proof_index",
    "write_proof_artifacts",
    "build_reviewer_feedback_audit",
    "build_tool_contract_snapshot",
    "build_runtime_contract_audit",
    "build_skill_qualification_receipt",
]
