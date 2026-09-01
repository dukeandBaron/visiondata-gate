"""Evidence-bounded reviewer comparison artifacts.

This module turns Boundless Agents reviewer signals plus explicitly labelled
cross-track Agent Infra engineering references into two machine-readable snapshots:

* ``reviewer_feedback_audit.json`` separates current-track official signals,
  cross-track references, and public competitor self-descriptions before
  mapping them to local evidence.
* ``tool_contract_snapshot.json`` makes tool necessity, replaceability,
  permissions, failure handling and MCP migration cost inspectable.

The snapshots are deliberately conservative.  A public project description is
an engineering-pattern reference, never an official score; a local PASS is a
run-level verification, never customer validation or production approval.
"""

from __future__ import annotations

from collections import Counter
import hashlib
import json
from typing import Any

from .agentteams_contract import skill_contract_digest, skill_for_task
from .contracts import (
    BatchContract,
    BatchManifest,
    EvaluationResult,
    GateDecision,
    GateResult,
)
from .policy import apply_policy
from .runtime_models import RuntimeStatus, RuntimeTrace
from .tools import run_all_tools, tool_contract_catalog, tool_contract_digest


def build_skill_qualification_receipt(trace: RuntimeTrace) -> dict[str, Any]:
    """Qualify run-bound Skill executions against the frozen declarations."""

    snapshot = trace.agentteams
    declared = {
        item.skill_id: item
        for item in (snapshot.skills if snapshot is not None else [])
    }
    tasks = {item.task_id: item for item in trace.tasks}
    events = {item.sequence: item for item in trace.events}
    rows: list[dict[str, Any]] = []
    for execution in trace.skill_executions:
        skill = declared.get(execution.skill_id)
        task = tasks.get(execution.task_id)
        event = events.get(execution.recorded_event_sequence)
        expected_skill_id: str | None
        try:
            expected_skill_id = skill_for_task(execution.task_id)
        except KeyError:
            expected_skill_id = None
        checks = {
            "skill_declared": skill is not None,
            "task_declared": task is not None,
            "task_skill_binding_matches": expected_skill_id == execution.skill_id,
            "version_matches": (
                skill is not None and execution.skill_version == skill.version
            ),
            "contract_digest_matches": (
                skill is not None
                and execution.skill_contract_digest == skill_contract_digest(skill)
            ),
            "terminal_event_matches": (
                event is not None
                and event.task_id == execution.task_id
                and event.status is execution.task_status
            ),
            "task_status_matches": (
                task is not None and task.status is execution.task_status
            ),
            "reference_digests_match": (
                execution.input_digest
                == hashlib.sha256(
                    json.dumps(
                        sorted(execution.input_refs),
                        ensure_ascii=False,
                        sort_keys=True,
                        separators=(",", ":"),
                    ).encode("utf-8")
                ).hexdigest()
                and execution.output_digest
                == hashlib.sha256(
                    json.dumps(
                        sorted(execution.output_refs),
                        ensure_ascii=False,
                        sort_keys=True,
                        separators=(",", ":"),
                    ).encode("utf-8")
                ).hexdigest()
            ),
            "embedded_qualification_checks_pass": all(
                execution.qualification_checks.values()
            ),
            "failure_has_rollback": (
                execution.qualification_status == "qualified"
                or (
                    execution.rollback_action != "none_required"
                    and bool(execution.rejection_reason)
                )
            ),
        }
        rows.append(
            {
                **execution.model_dump(mode="json"),
                "receipt_checks": checks,
                "receipt_status": "PASS" if all(checks.values()) else "FAIL",
            }
        )

    observed_tasks = [item.task_id for item in trace.skill_executions]
    expected_tasks = sorted(tasks)
    coverage_complete = sorted(observed_tasks) == expected_tasks and len(
        observed_tasks
    ) == len(set(observed_tasks))
    checks = {
        "all_terminal_tasks_skill_bound": coverage_complete,
        "all_declared_skills_observed": set(declared)
        <= {item.skill_id for item in trace.skill_executions},
        "all_execution_receipts_valid": bool(rows)
        and all(item["receipt_status"] == "PASS" for item in rows),
        "no_rejected_skill_execution": all(
            item.qualification_status != "rejected" for item in trace.skill_executions
        ),
        "failed_tasks_defer_with_rollback": all(
            (
                item.task_status not in {RuntimeStatus.ERROR, RuntimeStatus.SKIPPED}
                and item.qualification_status == "qualified"
            )
            or (
                item.task_status in {RuntimeStatus.ERROR, RuntimeStatus.SKIPPED}
                and item.qualification_status == "deferred"
                and item.rollback_action != "none_required"
            )
            for item in trace.skill_executions
        ),
    }
    return {
        "schema_version": "visiondata-gate.skill-qualification-receipt.v1",
        "run_id": trace.run_id,
        "execution_config_sha256": trace.execution_config_sha256,
        "status": "PASS" if all(checks.values()) else "PARTIAL",
        "checks": checks,
        "declared_skill_count": len(declared),
        "task_count": len(tasks),
        "execution_count": len(trace.skill_executions),
        "qualified_count": sum(
            item.qualification_status == "qualified" for item in trace.skill_executions
        ),
        "deferred_count": sum(
            item.qualification_status == "deferred" for item in trace.skill_executions
        ),
        "rejected_count": sum(
            item.qualification_status == "rejected" for item in trace.skill_executions
        ),
        "executions": rows,
        "boundary": (
            "PASS proves run-bound local Skill declarations, versions, task bindings, "
            "event bindings, reference digests and rollback semantics are coherent. It "
            "is not a hosted registry attestation or production qualification."
        ),
    }


_TOOL_CONTRACTS: dict[str, dict[str, Any]] = {
    "image_quality": {
        "role_in_closed_loop": "测量图像尺寸、亮度、清晰度和可解码性，向 Policy Judge 提供质量 finding",
        "input_schema": "BatchManifest + BatchContract.thresholds",
        "output_schema": "ToolTrace + Finding[] + quality metrics",
        "permission_scope": "dataset:read / read_batch_emit_finding",
        "read_only": True,
        "side_effect_level": "L0_none",
        "error_and_retry": "typed error or fail-closed; bounded max_retries from RuntimeConfig",
        "idempotency": "input_manifest_digest + contract parameters",
        "audit_fields": [
            "sequence",
            "input_sha256",
            "parameters",
            "result_sha256",
            "finding_ids",
        ],
        "mcp_migration": "Expose the same JSON Schema through an MCP transport adapter; preserve ToolTrace and Finding IDs",
        "migration_cost": "medium",
    },
    "duplicate_leakage": {
        "role_in_closed_loop": "检测跨 split 精确/近重复和来源泄漏，阻断不可接受的数据发布",
        "input_schema": "BatchManifest + BatchContract.thresholds.near_duplicate_hamming",
        "output_schema": "ToolTrace + Finding[] + duplicate metrics",
        "permission_scope": "dataset:read / read_batch_emit_finding",
        "read_only": True,
        "side_effect_level": "L0_none",
        "error_and_retry": "typed error or fail-closed; bounded max_retries from RuntimeConfig",
        "idempotency": "input_manifest_digest + contract parameters",
        "audit_fields": [
            "sequence",
            "input_sha256",
            "parameters",
            "result_sha256",
            "finding_ids",
        ],
        "mcp_migration": "Keep duplicate policy and canonical result digest stable behind a replaceable MCP adapter",
        "migration_cost": "medium",
    },
    "annotation_integrity": {
        "role_in_closed_loop": "检查标注路径、尺寸和 mask fraction，确保下游训练池输入可解释",
        "input_schema": "BatchManifest + BatchContract.annotation policy",
        "output_schema": "ToolTrace + Finding[] + annotation metrics",
        "permission_scope": "annotation:read / read_batch_emit_finding",
        "read_only": True,
        "side_effect_level": "L0_none",
        "error_and_retry": "typed error or fail-closed; bounded max_retries from RuntimeConfig",
        "idempotency": "input_manifest_digest + contract parameters",
        "audit_fields": [
            "sequence",
            "input_sha256",
            "parameters",
            "result_sha256",
            "finding_ids",
        ],
        "mcp_migration": "Map annotation provider output to the same Finding evidence contract; unknown fields are rejected",
        "migration_cost": "medium",
    },
    "coverage_matrix": {
        "role_in_closed_loop": "核对类别、视角、工况和 split 覆盖，生成可执行补采工单",
        "input_schema": "BatchManifest + BatchContract.coverage",
        "output_schema": "ToolTrace + Finding[] + coverage metrics",
        "permission_scope": "manifest:read / read_batch_emit_finding",
        "read_only": True,
        "side_effect_level": "L0_none",
        "error_and_retry": "typed error or fail-closed; bounded max_retries from RuntimeConfig",
        "idempotency": "input_manifest_digest + contract parameters",
        "audit_fields": [
            "sequence",
            "input_sha256",
            "parameters",
            "result_sha256",
            "finding_ids",
        ],
        "mcp_migration": "Replace only the coverage provider; preserve cell semantics, evidence refs and policy input shape",
        "migration_cost": "low",
    },
    "governance_audit": {
        "role_in_closed_loop": "按场景规则包检查 contract 与 manifest 边界，再把治理 finding 交给 Policy Judge",
        "input_schema": "BatchManifest + BatchContract + ScenarioProfile",
        "output_schema": "ToolTrace + Finding[] + governance metrics",
        "permission_scope": "contract:read / read_contract_emit_finding",
        "read_only": True,
        "side_effect_level": "L0_none",
        "error_and_retry": "typed error or fail-closed; bounded max_retries from RuntimeConfig",
        "idempotency": "input_contract_digest + manifest digest",
        "audit_fields": [
            "sequence",
            "input_sha256",
            "parameters",
            "result_sha256",
            "finding_ids",
        ],
        "mcp_migration": "Keep scenario profile and rule-package version in the remote request; no remote policy override",
        "migration_cost": "medium",
    },
}


def _all_traces(initial: GateResult, repaired: GateResult) -> list[Any]:
    return [*initial.tool_trace, *repaired.tool_trace]


def build_tool_contract_snapshot(
    trace: RuntimeTrace,
    initial: GateResult,
    repaired: GateResult,
) -> dict[str, Any]:
    """Build a deterministic, run-bound contract table for observed tools."""

    traces = _all_traces(initial, repaired)
    registered = {
        item.name: item
        for item in tool_contract_catalog(
            include_optional=trace.scenario_profile.value != "generic"
            or any(item.tool == "governance_audit" for item in traces)
        )
    }
    names = sorted({item.tool for item in traces})
    records: list[dict[str, Any]] = []
    for name in names:
        base = dict(_TOOL_CONTRACTS.get(name, {}))
        typed_contract = registered.get(name)
        if typed_contract is None:
            raise ValueError(f"observed tool has no typed contract: {name}")
        tool_traces = [item for item in traces if item.tool == name]
        finding_count = sum(len(item.finding_ids) for item in tool_traces)
        phases = []
        if any(item.tool == name for item in initial.tool_trace):
            phases.append("initial")
        if any(item.tool == name for item in repaired.tool_trace):
            phases.append("verification")
        records.append(
            {
                "name": name,
                "version": "1.0.0",
                "contract_digest": next(
                    item.contract_digest
                    for item in traces
                    if item.tool == name and item.contract_digest
                ),
                "role_in_closed_loop": base.get(
                    "role_in_closed_loop", "allowlisted typed finding producer"
                ),
                "input_schema": typed_contract.input_schema,
                "output_schema": typed_contract.output_schema,
                "permission_scope": typed_contract.permission_scope,
                "read_only": typed_contract.read_only,
                "side_effect_level": typed_contract.side_effect_level,
                "error_and_retry": base.get(
                    "error_and_retry",
                    f"{typed_contract.failure_policy}; max_retries={typed_contract.max_retries}",
                ),
                "failure_policy": typed_contract.failure_policy,
                "max_retries": typed_contract.max_retries,
                "idempotency": typed_contract.idempotency,
                "audit_fields": list(
                    base.get("audit_fields", ["input_sha256", "result_sha256"])
                ),
                "mcp_migration": base.get(
                    "mcp_migration",
                    f"transport target {typed_contract.mcp_migration_target}; preserve ToolTrace and Finding schemas",
                ),
                "mcp_migration_target": typed_contract.mcp_migration_target,
                "migration_cost": typed_contract.migration_cost,
                "observed_phases": phases,
                "observed_call_count": len(tool_traces),
                "observed_finding_count": finding_count,
                "necessity_basis": (
                    "Observed in the allowlisted worker trace and its typed output is "
                    "consumed by the Policy Judge; necessity is not inferred from tool count."
                ),
                "replaceability_basis": (
                    "Replaceable behind the declared input/output contract; replacing the "
                    "implementation requires a canonical-result and failure-parity check."
                ),
                "verification_status": "verified_local_trace",
                "contract_validation": {
                    "typed_contract_registered": True,
                    "trace_contract_versions": sorted(
                        {item.contract_version for item in tool_traces}
                    ),
                    "trace_contract_digests": sorted(
                        {
                            item.contract_digest
                            for item in tool_traces
                            if item.contract_digest
                        }
                    ),
                    "schema_version": typed_contract.version,
                    "typed_fields_are_source_of_truth": True,
                },
            }
        )

    return {
        "schema_version": "visiondata-gate.tool-contract-snapshot.v1",
        "run_id": trace.run_id,
        "scenario_profile": trace.scenario_profile.value,
        "transport": "local-deterministic",
        "connection_status": (
            trace.agentteams.connection_status
            if trace.agentteams is not None
            else "not_mapped"
        ),
        "tools": records,
        "source_basis": [
            "initial and verification GateResult.tool_trace",
            "local allowlist and typed ToolTrace contract",
            "AgentTeams mapping snapshot when present",
        ],
        "migration_gate": [
            "same input schema and policy version",
            "same canonical result digest for a replay fixture",
            "typed timeout/auth/schema errors map to fail-closed or DEFER",
            "no credentials or raw sensitive payloads in the trace",
        ],
        "boundary": (
            "This is a local contract and migration-readiness snapshot. It is not a live "
            "MCP connection, hosted AgentTeams receipt, vendor SLA, or production approval."
        ),
    }


def _replay_phase(
    *,
    phase: str,
    batch_root: Any,
    manifest: BatchManifest,
    contract: BatchContract,
    observed: GateResult,
    include_optional: bool,
) -> dict[str, Any]:
    """Replay successful allowlisted tools and compare canonical trace fields."""

    observed_ok = {
        item.tool: item for item in observed.tool_trace if item.status == "ok"
    }
    try:
        findings, replay_traces, metrics = run_all_tools(
            batch_root,
            manifest,
            contract,
            include_optional_tools=include_optional,
        )
    except Exception as error:
        return {
            "phase": phase,
            "status": "ERROR",
            "error_type": type(error).__name__,
            "error": str(error),
            "observed_ok_tools": sorted(observed_ok),
            "replayed_tools": [],
            "comparisons": [],
        }

    replay_by_tool = {item.tool: item for item in replay_traces}
    findings_by_tool: dict[str, list[str]] = {}
    for finding in findings:
        findings_by_tool.setdefault(finding.tool, []).append(finding.finding_id)
    comparisons: list[dict[str, Any]] = []
    for tool_name, observed_trace in sorted(observed_ok.items()):
        replay_trace = replay_by_tool.get(tool_name)
        if replay_trace is None:
            comparisons.append(
                {
                    "tool": tool_name,
                    "status": "FAIL",
                    "reason": "tool_missing_from_replay",
                }
            )
            continue
        same = (
            observed_trace.input_sha256 == replay_trace.input_sha256
            and observed_trace.result_sha256 == replay_trace.result_sha256
            and sorted(observed_trace.finding_ids) == sorted(replay_trace.finding_ids)
            and observed_trace.contract_digest == replay_trace.contract_digest
            and observed_trace.contract_digest
            == tool_contract_digest(tool_name, include_optional=include_optional)
        )
        comparisons.append(
            {
                "tool": tool_name,
                "status": "PASS" if same else "FAIL",
                "observed_input_sha256": observed_trace.input_sha256,
                "replay_input_sha256": replay_trace.input_sha256,
                "observed_result_sha256": observed_trace.result_sha256,
                "replay_result_sha256": replay_trace.result_sha256,
                "observed_finding_ids": sorted(observed_trace.finding_ids),
                "replay_finding_ids": sorted(replay_trace.finding_ids),
                "contract_digest": replay_trace.contract_digest,
                "replay_metric_keys": sorted(metrics),
                "replay_finding_count": len(findings_by_tool.get(tool_name, [])),
            }
        )
    missing_tools = sorted(set(replay_by_tool) - set(observed_ok))
    all_pass = bool(comparisons) and all(
        item["status"] == "PASS" for item in comparisons
    )
    return {
        "phase": phase,
        "status": "PASS" if all_pass else "PARTIAL",
        "observed_ok_tools": sorted(observed_ok),
        "replayed_tools": sorted(replay_by_tool),
        "not_compared_observed_non_ok": sorted(
            {item.tool for item in observed.tool_trace if item.status != "ok"}
        ),
        "replay_only_tools": missing_tools,
        "comparisons": comparisons,
        "boundary": (
            "Only successful observed tools are compared. A skipped/error tool is not "
            "silently upgraded by replay; the original Policy Judge result remains authoritative."
        ),
    }


def build_tool_replay_receipt(
    trace: RuntimeTrace,
    *,
    initial_root: Any,
    initial_manifest: BatchManifest,
    repaired_root: Any,
    repaired_manifest: BatchManifest,
    contract: BatchContract,
    initial: GateResult,
    repaired: GateResult,
) -> dict[str, Any]:
    """Create a deterministic replay receipt for local-to-remote migration."""

    include_optional = trace.scenario_profile.value != "generic" or any(
        item.tool == "governance_audit"
        for result in (initial, repaired)
        for item in result.tool_trace
    )
    phases = [
        _replay_phase(
            phase="initial",
            batch_root=initial_root,
            manifest=initial_manifest,
            contract=contract,
            observed=initial,
            include_optional=include_optional,
        ),
        _replay_phase(
            phase="verification",
            batch_root=repaired_root,
            manifest=repaired_manifest,
            contract=contract,
            observed=repaired,
            include_optional=include_optional,
        ),
    ]
    status = "PASS" if all(item["status"] == "PASS" for item in phases) else "PARTIAL"
    return {
        "schema_version": "visiondata-gate.tool-replay-receipt.v1",
        "run_id": trace.run_id,
        "adapter": "local-deterministic-replay",
        "status": status,
        "scenario_profile": trace.scenario_profile.value,
        "phases": phases,
        "migration_use": (
            "A future MCP/remote adapter must reproduce these canonical input/result "
            "digests for the same fixture, or return a typed error/DEFER instead of "
            "silently changing the Policy Judge input."
        ),
        "boundary": (
            "This receipt proves a local replay against the same code and fixture. It is "
            "not a hosted service health check, remote equivalence proof, customer result, "
            "or production SLO."
        ),
    }


def _decision_rank(decision: GateDecision) -> int:
    """Order decisions from least to most permissive for ablation checks."""

    return {
        GateDecision.DEFER: 0,
        GateDecision.QUARANTINE: 1,
        GateDecision.RECAPTURE: 2,
        GateDecision.PASS: 3,
    }[decision]


def _ablate_phase(
    *,
    phase: str,
    observed: GateResult,
    manifest: BatchManifest,
    contract: BatchContract,
    scenario_profile: Any,
) -> dict[str, Any]:
    """Remove one observed tool at a time and re-run the frozen policy.

    This is a policy/evidence ablation, not a claim about a production tool
    outage.  The fixture and contract stay fixed; only one typed tool trace and
    its finding references are removed.  The output makes tool necessity and
    fail-closed behaviour directly reviewable.
    """

    tools = sorted({item.tool for item in observed.tool_trace})
    rows: list[dict[str, Any]] = []
    for tool_name in tools:
        removed_traces = [
            item for item in observed.tool_trace if item.tool == tool_name
        ]
        removed_finding_ids = sorted(
            {finding_id for item in removed_traces for finding_id in item.finding_ids}
        )
        # Keep a typed receipt for the disabled tool.  Silently deleting the
        # trace would make the policy unable to distinguish "not required"
        # from "required but unavailable" and could hide a fail-closed path.
        disabled_traces = [
            item.model_copy(
                update={
                    "status": "skipped",
                    "error": "ablation: required tool disabled",
                    "finding_ids": [],
                }
            )
            for item in removed_traces
        ]
        candidate_traces = sorted(
            [item for item in observed.tool_trace if item.tool != tool_name]
            + disabled_traces,
            key=lambda item: item.sequence,
        )
        candidate_findings = [
            item
            for item in observed.findings
            if item.finding_id not in set(removed_finding_ids)
        ]
        candidate_metrics = dict(observed.metrics)
        candidate_metrics["tool_error_count"] = (
            int(candidate_metrics.get("tool_error_count", 0)) + 1
        )
        candidate = apply_policy(
            manifest,
            contract,
            candidate_findings,
            candidate_traces,
            candidate_metrics,
            scenario_profile=scenario_profile,
            input_sha256=observed.input_sha256,
            run_id=f"ablation-{phase}-{tool_name}-{observed.input_sha256[:12]}",
        )
        base_rank = _decision_rank(observed.decision)
        candidate_rank = _decision_rank(candidate.decision)
        if candidate_rank > base_rank:
            effect = "MORE_PERMISSIVE"
        elif candidate_rank < base_rank:
            effect = "MORE_RESTRICTIVE"
        else:
            effect = "UNCHANGED"
        base_failed = sorted(
            item.check_id
            for item in observed.rule_checks
            if item.status.value == "FAIL"
        )
        candidate_failed = sorted(
            item.check_id
            for item in candidate.rule_checks
            if item.status.value == "FAIL"
        )
        rows.append(
            {
                "tool": tool_name,
                "removed_trace_count": len(removed_traces),
                "disabled_trace_status": "skipped",
                "removed_finding_ids": removed_finding_ids,
                "base_decision": observed.decision.value,
                "ablated_decision": candidate.decision.value,
                "decision_effect": effect,
                "more_permissive": candidate_rank > base_rank,
                "base_failed_rule_checks": base_failed,
                "ablated_failed_rule_checks": candidate_failed,
                "new_failed_rule_checks": sorted(
                    set(candidate_failed) - set(base_failed)
                ),
                "resolved_failed_rule_checks": sorted(
                    set(base_failed) - set(candidate_failed)
                ),
                "evidence_loss": bool(removed_finding_ids),
                "policy_input_sha256": observed.input_sha256,
            }
        )
    return {
        "phase": phase,
        "base_decision": observed.decision.value,
        "tool_count": len(tools),
        "ablations": rows,
        "status": (
            "PASS"
            if rows and not any(item["more_permissive"] for item in rows)
            else "PARTIAL"
        ),
        "boundary": (
            "Removing one local tool trace is a bounded policy/evidence ablation. "
            "It does not simulate a vendor outage or prove production reliability."
        ),
    }


def build_tool_ablation_receipt(
    trace: RuntimeTrace,
    *,
    initial_manifest: BatchManifest,
    repaired_manifest: BatchManifest,
    contract: BatchContract,
    initial: GateResult,
    repaired: GateResult,
) -> dict[str, Any]:
    """Build a run-bound receipt showing what each tool contributes."""

    phases = [
        _ablate_phase(
            phase="initial",
            observed=initial,
            manifest=initial_manifest,
            contract=contract,
            scenario_profile=trace.scenario_profile,
        ),
        _ablate_phase(
            phase="verification",
            observed=repaired,
            manifest=repaired_manifest,
            contract=contract,
            scenario_profile=trace.scenario_profile,
        ),
    ]
    return {
        "schema_version": "visiondata-gate.tool-ablation-receipt.v1",
        "run_id": trace.run_id,
        "adapter": "local-deterministic-policy-ablation",
        "status": "PASS"
        if all(item["status"] == "PASS" for item in phases)
        else "PARTIAL",
        "scenario_profile": trace.scenario_profile.value,
        "phases": phases,
        "interpretation": (
            "PASS means no single-tool removal made the frozen policy more permissive. "
            "UNCHANGED can still carry evidence_loss when the removed worker produced findings; "
            "new failed checks expose the fail-closed dependency."
        ),
        "boundary": (
            "This receipt is a deterministic local ablation over the same fixture and contract. "
            "It is not a customer A/B test, vendor SLA, hosted MCP result, or production outage statistic."
        ),
    }


def build_reviewer_feedback_audit(
    trace: RuntimeTrace,
    initial: GateResult,
    repaired: GateResult,
    evaluation: EvaluationResult,
) -> dict[str, Any]:
    """Map reviewer signals to local evidence without fabricating scores."""

    health = {
        "decision_chain": [initial.decision.value, repaired.decision.value],
        "post_repair_correct_pass": evaluation.post_repair_correct_pass,
        "work_order_recall": evaluation.work_order_recall,
        "tool_trace_count": len(initial.tool_trace) + len(repaired.tool_trace),
        "rule_check_count": len(initial.rule_checks) + len(repaired.rule_checks),
        "context_transfer_count": len(trace.context_transfers),
        "context_transfer_deferred_count": sum(
            item.status == "deferred" for item in trace.context_transfers
        ),
    }
    snapshot = trace.agentteams
    skill_count = len(snapshot.skills) if snapshot is not None else 0
    local_multi_agent = bool(
        snapshot
        and snapshot.task_binding_count == len(trace.tasks)
        and snapshot.collaboration_event_count == len(trace.events)
    )
    official = "official_boundless_agents"
    cross_track = "cross_track_infra_reference"
    competitor = "public_competitor_reference"
    local = "local_engineering"
    rows = [
        {
            "audit_id": "scene_value_and_transfer",
            "source_layer": official,
            "source_ref": "https://www.goaihz.com/tracks?track=apps#行业场景价值",
            "signal": "真实、明确、具有代表性的场景问题，以及可复制/迁移价值",
            "reviewer_question": "为什么这个不是泛聊天或单点工具？相似工厂能否迁移？",
            "current_risk": (
                "本地已有冻结 Synthetic fixture 与操作者声明授权的 Omni 离线 Pilot；"
                "尚无客户级 shadow adjudication、岗位访谈或现场 KPI。"
            ),
            "local_evidence": [
                "initial/gate_result.json",
                "repaired/gate_result.json",
                "initial/evidence_matrix.csv",
                "repaired/evidence_matrix.csv",
            ],
            "status": "PARTIAL",
            "status_basis": local,
            "missing_external_evidence": (
                "客户书面授权、双人或 QMS 案件级真值、岗位访谈、现场 KPI，"
                "以及两个独立环境的同内核 clean-run。"
            ),
            "verification_command": ".venv\\Scripts\\python.exe -m pytest -q tests/test_agent_runtime.py tests/test_evidence_package.py",
            "next_action": (
                "按预注册观察窗封存客户 shadow 包，并把 Site Pack、输入合同、"
                "真值回执、分子分母、运营指标和责任人签署绑定到同一验证包。"
            ),
            "overclaim_boundary": "不得把合成数据 precision/recall 写成工业现场准确率或客户收益。",
        },
        {
            "audit_id": "agentteams_mapping_and_context",
            "source_layer": cross_track,
            "source_ref": "Agent_Infra赛道分享-杨翊.txt#AgentTeams协同/上下文传递",
            "signal": "跨赛道工程参考要求 AgentTeams 协作可核验；在本项目中它是可信后台能力，不是无界应用赛道硬性接入声明。",
            "reviewer_question": "角色名之外，Task、ToolTrace、RuleCheck 和交付物是否能串起来？",
            "current_risk": "当前是本地契约映射，未连接 hosted AgentTeams/Matrix。",
            "local_evidence": [
                "agentteams_mapping.json#/context_flow",
                "agent_runtime_trace.json#/tasks",
                "agent_runtime_trace.json#/events",
                "agent_runtime_trace.json#/context_transfers",
            ],
            "status": "PARTIAL" if not local_multi_agent else "PARTIAL",
            "status_basis": local,
            "missing_external_evidence": "hosted AgentTeams/Matrix 登录运行 receipt；在此之前必须保持 mapped_not_connected。",
            "verification_command": ".venv\\Scripts\\python.exe -m pytest -q tests/test_agent_runtime.py tests/test_proof.py",
            "next_action": "若后续取得平台授权，单独保存 hosted receipt 并与本地 canonical digest 对照。",
            "overclaim_boundary": "不能把 AgentTeams 映射快照写成 hosted 连接或官方验收。",
        },
        {
            "audit_id": "skill_reuse_and_lifecycle",
            "source_layer": official,
            "source_ref": "https://www.goaihz.com/tracks?track=apps#技术实现深度与工程可复现性",
            "signal": "Skill 必须说明输入输出、调用条件、依赖、失败处理、版本、回滚和复用价值。",
            "reviewer_question": "Skill 是可迁移能力还是一次性脚本？版本升级会不会改变门禁？",
            "current_risk": "本地契约完整；外部生态复用和第三方复现尚未取得证据。",
            "local_evidence": [
                "agentteams_mapping.json#/skills",
                "skills/manifest.json",
                "docs/AGENTTEAMS_ALIGNMENT.md",
            ],
            "status": "PASS" if skill_count >= 5 else "PARTIAL",
            "status_basis": local,
            "missing_external_evidence": "独立仓库/第三方复用回执和版本演进后的 replay fixture。",
            "verification_command": ".venv\\Scripts\\python.exe -m pytest -q tests/test_proof.py",
            "next_action": "为每个 Skill 固化输入 fixture、失败 fixture 和版本回滚对照。",
            "overclaim_boundary": "不能因 manifest 存在就声称已形成开源生态或第三方采用。",
        },
        {
            "audit_id": "tool_necessity_replaceability",
            "source_layer": cross_track,
            "source_ref": "goai_infra_live.txt#工具不按数量评分",
            "signal": "重点看工具必要性、接口契约、可替换性、权限边界、端到端证据和迁移成本。",
            "reviewer_question": "删掉这个工具会失去哪条决策证据？换成 MCP/远程服务需要改什么？",
            "current_risk": "已有 ToolTrace 和白名单；尚未连接真实远程工具，迁移成本仍是契约估计。",
            "local_evidence": [
                "tool_contract_snapshot.json",
                "initial/gate_result.json#/tool_trace",
                "repaired/gate_result.json#/tool_trace",
                "docs/TOOLS_AND_MCP_CONTRACT.md",
            ],
            "status": "PASS",
            "status_basis": local,
            "missing_external_evidence": "远程 adapter replay、超时/鉴权/去重 fixture 和服务健康回执。",
            "verification_command": ".venv\\Scripts\\python.exe -m pytest -q tests/test_reviewer_audit.py",
            "next_action": "逐工具补一条删除/替换扰动记录，并比较 canonical result digest。",
            "overclaim_boundary": "工具契约快照不等于 MCP 已连接，也不等于供应商 SLA。",
        },
        {
            "audit_id": "closed_loop_and_correct_failure",
            "source_layer": cross_track,
            "source_ref": "Agent_Infra赛道分享-杨翊.txt#端到端闭环/失败处理",
            "signal": "任务拆解→工具调用→结果验证→证据沉淀；异常、冲突、多方案和正确失败必须可追踪。",
            "reviewer_question": "只有成功修复吗？工具缺失、证据篡改或审批缺失时会不会错误放行？",
            "current_risk": "默认冻结运行是 RECAPTURE→PASS；负路径有契约/测试，但当前快照不是一次 DEFER 运行。",
            "local_evidence": [
                "initial/evidence_matrix.csv",
                "repaired/evidence_matrix.csv",
                "proof_index.json",
                "docs/REVIEWER_SCENARIO_MATRIX.md",
            ],
            "status": "PARTIAL",
            "status_basis": local,
            "missing_external_evidence": "独立保存的 missing-worker/tool-error/evidence-tamper/approval-missing DEFER 工件。",
            "verification_command": ".venv\\Scripts\\python.exe -m pytest -q tests/test_agent_runtime.py tests/test_policy.py",
            "next_action": "把四类负路径各生成一份小型 trace fixture，并纳入提交包审计。",
            "overclaim_boundary": "不能用单次 PASS 运行证明所有异常分支均已现场验证。",
        },
        {
            "audit_id": "authorization_and_audit_boundary",
            "source_layer": official,
            "source_ref": "https://www.goaihz.com/tracks?track=apps#安全合规与任务闭环",
            "signal": "高风险动作需要权限、审批、回滚、降级和全链路审计。",
            "reviewer_question": "谁能批准生产写回？本地 PASS 是否会越权？",
            "current_risk": "生产 scope 已明确 blocked；尚无真实企业身份审批或生产系统回执。",
            "local_evidence": [
                "approval_handoff.json",
                "agent_runtime_trace.json#/boundary_notice",
                "proof_index.json#/claims/authorization_boundary",
            ],
            "status": "PARTIAL",
            "status_basis": local,
            "missing_external_evidence": "企业身份、审批系统 receipt、生产回滚演练和安全评估。",
            "verification_command": ".venv\\Scripts\\python.exe -m pytest -q tests/test_proof.py tests/test_app_source.py",
            "next_action": "保持 external_authorization_required/blocked，若接入审批系统再追加不可伪造 receipt。",
            "overclaim_boundary": "本地 PASS 只表示 sandbox contract eligibility，不是生产授权。",
        },
        {
            "audit_id": "competitor_pattern_reference",
            "source_layer": competitor,
            "source_ref": "processpilot/goai_boundless_20260816/README.md#自述与QA",
            "signal": "公开他队自述把 PASS/PARTIAL/OPEN、正确失败、基线、回滚、人工审批和交付哈希作为一等材料。",
            "reviewer_question": "我们是否也能让失败、基线和交付完整性被直接核验？",
            "current_risk": "他队材料不是官方评分；只能作为工程模式参考。",
            "local_evidence": [
                "reviewer_feedback_audit.json",
                "proof_index.json",
                "approval_handoff.json",
                "docs/REVIEWER_READINESS_MATRIX.md",
            ],
            "status": "PASS",
            "status_basis": local,
            "missing_external_evidence": "无；但该行不构成官方认可或与他队分数的比较。",
            "verification_command": ".venv\\Scripts\\python.exe -m pytest -q tests/test_reviewer_audit.py",
            "next_action": "保留负结果、哈希和权限边界；不要把他队自评改写成评委意见。",
            "overclaim_boundary": "public_competitor_reference 不能被称为 official_judge_feedback。",
        },
        {
            "audit_id": "open_source_and_rights",
            "source_layer": official,
            "source_ref": "https://www.goaihz.com/tracks?track=apps#安全合规与开放复用价值",
            "signal": "开放/开源贡献与可复用价值是独立评审维度，需要清楚许可和分发边界。",
            "reviewer_question": "哪些代码、Skill、数据和第三方依赖可分发？许可证是否已确认？",
            "current_risk": "Apache-2.0、NOTICE 与零 REVIEW_REQUIRED 供应链清单已完成；独立法律意见、外部资产授权和第三方生态采用仍未取得。",
            "local_evidence": [
                "LICENSE",
                "NOTICE",
                "docs/SBOM.cdx.json",
                "docs/THIRD_PARTY_LICENSE_INVENTORY.generated.md",
                "docs/data_privacy_license_boundaries.md",
            ],
            "status": "PARTIAL",
            "status_basis": local,
            "missing_external_evidence": "第三方复用/贡献回执、独立法律意见，以及提交时公开 remote/tag 的在线可达性回执。",
            "verification_command": ".venv\\Scripts\\python.exe -m pytest -q tests/test_supply_chain_artifacts.py",
            "next_action": "提交时在线核验公开仓库和 tag，并继续保持代码许可与数据/模型/客户资产授权分离。",
            "overclaim_boundary": "Apache-2.0 只覆盖本项目代码，不构成外部数据、模型、客户资产授权或独立法律审查。",
        },
    ]
    counts = Counter(item["status"] for item in rows)
    return {
        "schema_version": "visiondata-gate.reviewer-feedback-audit.v1",
        "run_id": trace.run_id,
        "comparison_basis": [
            "official Boundless Agents track wording",
            "cross-track Agent Infra material used only as an engineering reference",
            "public competitor self-description used only as an engineering-pattern reference",
            "local deterministic runtime artifacts",
        ],
        "source_layers": {
            official: "当前无界应用赛道官方公开口径",
            cross_track: "Agent Infra 跨赛道工程参考，不是当前赛道硬要求",
            competitor: "他队公开自述/工程材料，不是官方评分",
            local: "本地运行、测试和可下载证据",
        },
        "health_snapshot": health,
        "status_counts": dict(sorted(counts.items())),
        "items": rows,
        "boundary": (
            "This audit is a reviewer-question navigation artifact. It does not claim official "
            "judge scores, private replay content, customer validation, hosted AgentTeams "
            "connectivity, production certification, independent legal review, or rights over "
            "external datasets, models, and customer assets."
        ),
    }


def build_runtime_contract_audit(
    trace: RuntimeTrace,
    initial: GateResult,
    repaired: GateResult,
) -> dict[str, Any]:
    """Audit the executable core rather than only its descriptive mapping.

    This is intentionally a local integrity check.  It answers whether the
    current trace contains a coherent task DAG, typed tool-contract bindings,
    one policy authority per gate pass, same-contract recheck metadata and a
    finding-to-work-order evidence chain.
    """

    task_ids = {task.task_id for task in trace.tasks}
    dependencies = [
        dependency for task in trace.tasks for dependency in task.dependencies
    ]
    event_task_ids = {
        event.task_id for event in trace.events if event.task_id is not None
    }
    judge_events = [
        event
        for event in trace.events
        if event.actor == "Policy Judge" and event.action == "apply_fail_closed_policy"
    ]
    expected_passes = [initial, repaired]
    traces_by_phase = {
        "initial": initial.tool_trace,
        "verification": repaired.tool_trace,
    }
    include_optional = trace.scenario_profile.value != "generic" or any(
        item.tool == "governance_audit"
        for result in expected_passes
        for item in result.tool_trace
    )
    registered = {
        item.name: item
        for item in tool_contract_catalog(include_optional=include_optional)
    }
    contract_checks: list[dict[str, Any]] = []
    for phase, traces in traces_by_phase.items():
        for item in traces:
            expected = registered.get(item.tool)
            expected_digest = None
            if expected is not None:
                from .tools import tool_contract_digest

                expected_digest = tool_contract_digest(
                    item.tool, include_optional=include_optional
                )
            contract_checks.append(
                {
                    "phase": phase,
                    "sequence": item.sequence,
                    "tool": item.tool,
                    "status": item.status,
                    "registered": expected is not None,
                    "contract_version_present": bool(item.contract_version),
                    "contract_digest_present": bool(item.contract_digest),
                    "contract_digest_matches": (
                        expected_digest is not None
                        and item.contract_digest == expected_digest
                    ),
                    "adapter": item.adapter,
                }
            )

    findings = [
        (phase, finding)
        for phase, result in (("initial", initial), ("verification", repaired))
        for finding in result.findings
    ]
    finding_ids = {finding.finding_id for _, finding in findings}
    trace_finding_ids = {
        finding_id
        for traces in traces_by_phase.values()
        for item in traces
        for finding_id in item.finding_ids
    }
    work_orders = [
        (phase, order)
        for phase, result in (("initial", initial), ("verification", repaired))
        for order in result.work_orders
    ]
    work_order_reason_bound = all(bool(order.reason_codes) for _, order in work_orders)
    phase_contracts = [
        {
            "phase": phase,
            "contract_id": result.contract_id,
            "policy_version": result.policy_version,
            "input_sha256": result.input_sha256,
            "decision": result.decision.value,
        }
        for phase, result in (("initial", initial), ("verification", repaired))
    ]
    transfer_edges = [
        (item.source_task_id, item.task_id) for item in trace.context_transfers
    ]
    declared_edges = [
        (dependency, task.task_id)
        for task in trace.tasks
        for dependency in task.dependencies
    ]

    def transfer_digest(item: Any) -> str:
        payload = {
            "kind": item.payload_kind,
            "input_refs": sorted(item.input_refs),
            "output_refs": sorted(item.output_refs),
            "source_status": item.source_status.value,
            "target_status": item.target_status.value,
            "source_output_digest": item.source_output_digest,
            "target_output_digest": item.target_output_digest,
            "acceptance_basis": item.acceptance_basis,
            "status": item.status,
        }
        encoded = json.dumps(
            payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")
        ).encode("utf-8")
        return hashlib.sha256(encoded).hexdigest()

    transfer_hashes_valid = all(
        item.payload_sha256 == transfer_digest(item)
        and item.source_output_digest
        == hashlib.sha256(
            json.dumps(
                sorted(item.input_refs),
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
            ).encode("utf-8")
        ).hexdigest()
        and item.target_output_digest
        == hashlib.sha256(
            json.dumps(
                sorted(item.output_refs),
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
            ).encode("utf-8")
        ).hexdigest()
        and all(
            isinstance(ref, str) and ref
            for ref in (*item.input_refs, *item.output_refs)
        )
        for item in trace.context_transfers
    )
    transfer_acceptance_basis_valid = all(
        (
            item.status == "accepted"
            and item.source_status is RuntimeStatus.SUCCESS
            and item.target_status not in {RuntimeStatus.ERROR, RuntimeStatus.SKIPPED}
            and bool(item.input_refs)
            and item.acceptance_basis
            in {"source_success_target_success", "source_success_target_warning"}
        )
        or (
            item.status == "deferred"
            and bool(item.rejection_reason)
            and item.acceptance_basis
            in {
                "source_not_success",
                "target_not_runnable",
                "source_success_without_output_refs",
            }
        )
        for item in trace.context_transfers
    )
    transfer_status_safe = all(
        (item.status == "accepted" and item.rejection_reason is None)
        or (item.status == "deferred" and bool(item.rejection_reason))
        or (item.status == "rejected" and bool(item.rejection_reason))
        for item in trace.context_transfers
    )
    task_map = {task.task_id: task for task in trace.tasks}
    event_map = {event.sequence: event for event in trace.events}
    transfer_task_refs_match = all(
        item.source_task_id in task_map
        and item.task_id in task_map
        and item.input_refs == task_map[item.source_task_id].output_refs
        and item.output_refs == task_map[item.task_id].output_refs
        and item.source_status is task_map[item.source_task_id].status
        and item.target_status is task_map[item.task_id].status
        for item in trace.context_transfers
    )
    transfer_runtime_event_bound = all(
        item.capture_mode == "runtime_event"
        and item.recorded_event_sequence in event_map
        and event_map[item.recorded_event_sequence].task_id == item.task_id
        and event_map[item.recorded_event_sequence].status is item.target_status
        for item in trace.context_transfers
    )
    skill_qualification = build_skill_qualification_receipt(trace)
    checks = {
        "task_graph_declared": bool(task_ids),
        "task_dependencies_declared": all(item in task_ids for item in dependencies),
        "event_tasks_declared": event_task_ids <= task_ids,
        "all_events_agentteams_bound": all(
            bool(event.collaboration.get("team_id")) for event in trace.events
        ),
        "typed_tool_contracts_bound": bool(contract_checks)
        and all(
            item["registered"]
            and item["contract_version_present"]
            and item["contract_digest_present"]
            and item["contract_digest_matches"]
            and item["adapter"] == "local-deterministic"
            for item in contract_checks
        ),
        "one_policy_authority_per_pass": len(judge_events) == len(expected_passes),
        "same_contract_recheck": (
            len(phase_contracts) == 2
            and phase_contracts[0]["contract_id"] == phase_contracts[1]["contract_id"]
            and phase_contracts[0]["policy_version"]
            == phase_contracts[1]["policy_version"]
        ),
        "finding_tool_refs_closed": finding_ids <= trace_finding_ids,
        "work_order_reason_refs_present": work_order_reason_bound,
        "decision_chain_present": len(trace.judge_decisions) == len(expected_passes),
        "context_transfer_edges_complete": (
            sorted(transfer_edges) == sorted(declared_edges)
            and len(transfer_edges) == len(set(transfer_edges))
        ),
        "context_transfer_hashes_valid": transfer_hashes_valid,
        "context_transfer_acceptance_basis_valid": transfer_acceptance_basis_valid,
        "context_transfer_task_refs_match": transfer_task_refs_match,
        "context_transfer_runtime_event_bound": transfer_runtime_event_bound,
        "context_transfer_failure_safe": transfer_status_safe,
        "skill_execution_coverage_complete": skill_qualification["checks"][
            "all_terminal_tasks_skill_bound"
        ],
        "skill_qualification_passed": skill_qualification["status"] == "PASS",
        "execution_config_bound_to_run_id": (
            trace.execution_config_sha256[:10] in trace.run_id
        ),
    }
    return {
        "schema_version": "visiondata-gate.runtime-contract-audit.v1",
        "run_id": trace.run_id,
        "execution_config_sha256": trace.execution_config_sha256,
        "status": "PASS" if all(checks.values()) else "PARTIAL",
        "checks": checks,
        "task_graph": {
            "task_count": len(trace.tasks),
            "dependency_count": len(dependencies),
            "event_count": len(trace.events),
            "task_ids": sorted(task_ids),
        },
        "policy_authority": {
            "judge_event_count": len(judge_events),
            "judge_actor": "Policy Judge",
            "council_is_advisory": True,
            "decision_chain": trace.judge_decisions,
        },
        "tool_contracts": {
            "registered_tool_count": len(registered),
            "observed_trace_count": len(contract_checks),
            "traces": contract_checks,
        },
        "evidence_chain": {
            "finding_count": len(finding_ids),
            "tool_bound_finding_count": len(finding_ids & trace_finding_ids),
            "work_order_count": len(work_orders),
            "all_work_orders_have_reason_codes": work_order_reason_bound,
            "phase_contracts": phase_contracts,
        },
        "context_transfers": {
            "count": len(trace.context_transfers),
            "declared_dependency_count": len(declared_edges),
            "accepted_count": sum(
                item.status == "accepted" for item in trace.context_transfers
            ),
            "deferred_count": sum(
                item.status == "deferred" for item in trace.context_transfers
            ),
            "acceptance_basis_counts": dict(
                sorted(
                    Counter(
                        item.acceptance_basis for item in trace.context_transfers
                    ).items()
                )
            ),
            "edges": [item.model_dump(mode="json") for item in trace.context_transfers],
        },
        "skill_qualification": {
            "status": skill_qualification["status"],
            "declared_skill_count": skill_qualification["declared_skill_count"],
            "execution_count": skill_qualification["execution_count"],
            "qualified_count": skill_qualification["qualified_count"],
            "deferred_count": skill_qualification["deferred_count"],
            "rejected_count": skill_qualification["rejected_count"],
            "checks": skill_qualification["checks"],
        },
        "boundary": (
            "PASS means the local runtime contract is internally coherent for this run. "
            "It is not a hosted AgentTeams receipt, customer validation, production SLO, "
            "or production authorization."
        ),
    }


__all__ = [
    "build_skill_qualification_receipt",
    "build_reviewer_feedback_audit",
    "build_runtime_contract_audit",
    "build_tool_contract_snapshot",
    "build_tool_ablation_receipt",
]
