"""Explicit AgentTeams/TeamHarness mapping for the VisionData Gate domain team.

This module is deliberately a contract layer, not a second orchestration
framework.  The local runtime remains deterministic and executable on a clean
machine; the returned manifest makes the mapping to AgentTeams' Team / Room /
Task / Identity / Skill semantics explicit and auditable.  A future Matrix or
remote-runtime adapter can consume the same manifest without changing the
domain workers or the fail-closed policy judge.
"""

from __future__ import annotations

import hashlib
import json
from typing import Literal

from .runtime_models import (
    AgentIdentity,
    AgentTeamsSnapshot,
    ScenarioProfile,
    SkillContract,
)


TEAM_ID = "team.visiondata-gate"
ROOM_ID = "room.visiondata-gate.runtime"
PROTOCOL = "agentteams-teamharness.v1"


def skill_contract_digest(skill: SkillContract) -> str:
    """Return a stable digest for the executable Skill contract."""

    payload = skill.model_dump(mode="json")
    encoded = json.dumps(
        payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def skill_for_task(task_id: str) -> str:
    """Map a runtime task to the domain Skill that owns its execution."""

    if task_id.endswith(".intake"):
        return "skill.contract-intake.v1"
    if (
        task_id.endswith(".route")
        or task_id.endswith(".memory")
        or task_id.endswith(".plan")
        or ".tool." in task_id
    ):
        return "skill.parallel-evidence-audit.v1"
    if task_id.endswith(".council"):
        return "skill.evidence-grounded-council.v1"
    if task_id.endswith(".judge"):
        return "skill.fail-closed-policy.v1"
    if task_id == "system.repair" or task_id.startswith("verification."):
        # Verification tasks keep their specific audit/review/policy Skills;
        # only the repair operator is owned by the reserve Skill.
        if task_id == "system.repair":
            return "skill.reserve-recheck-delivery.v1"
    if task_id == "system.delivery":
        return "skill.reserve-recheck-delivery.v1"
    raise KeyError(f"no Skill contract mapped for task: {task_id}")


def _identity(
    agent_id: str,
    display_name: str,
    role_type: Literal[
        "manager", "team_leader", "worker", "reviewer", "judge", "operator"
    ],
    purpose: str,
    capabilities: tuple[str, ...],
    allowed_tools: tuple[str, ...] = (),
) -> AgentIdentity:
    return AgentIdentity(
        agent_id=agent_id,
        display_name=display_name,
        role_type=role_type,
        purpose=purpose,
        capabilities=list(capabilities),
        allowed_tools=list(allowed_tools),
        permission_scope=[
            f"agent:{agent_id}",
            "room:read",
            "task:read",
            "event:write",
        ],
        failure_policy="fail-closed; emit a typed event and defer release authority",
    )


def _skill(
    skill_id: str,
    name: str,
    owner_agent_id: str,
    purpose: str,
    inputs: tuple[str, ...],
    outputs: tuple[str, ...],
    dependencies: tuple[str, ...],
    failure_modes: tuple[str, ...],
    safety_boundary: str,
    quality_metrics: tuple[str, ...],
    version_history: tuple[str, ...] = ("1.0.0: initial frozen contract",),
    rollback_strategy: str = "pin_previous_contract_and_replay_same_input",
) -> SkillContract:
    return SkillContract(
        skill_id=skill_id,
        name=name,
        version="1.0.0",
        owner_agent_id=owner_agent_id,
        purpose=purpose,
        input_contract=list(inputs),
        output_contract=list(outputs),
        call_conditions=[
            "Task is assigned by the Team Leader",
            "Input manifest and contract pass schema validation",
        ],
        dependencies=list(dependencies),
        failure_modes=list(failure_modes),
        safety_boundary=safety_boundary,
        reusable_value="portable domain Skill; callable from another Team/Room through the same contract",
        quality_metrics=list(quality_metrics),
        version_history=list(version_history),
        rollback_strategy=rollback_strategy,
    )


def build_agentteams_contract(
    profile: ScenarioProfile,
    *,
    allowed_tools: list[str] | tuple[str, ...],
    include_optional: bool,
    run_id: str | None = None,
) -> AgentTeamsSnapshot:
    """Build a stable AgentTeams mapping for one runtime configuration.

    ``matrix_connected`` is always false for the local deterministic runtime;
    this is intentional so a manifest cannot be mistaken for a real Matrix
    deployment receipt.
    """

    allowed = tuple(dict.fromkeys(str(item) for item in allowed_tools))
    worker_specs = [
        (
            "worker.image-quality",
            "Quality Worker",
            "image_quality",
            "decode, luma, sharpness and geometry evidence",
        ),
        (
            "worker.duplicate-leakage",
            "Leakage Worker",
            "duplicate_leakage",
            "exact/near duplicate and cross-split evidence",
        ),
        (
            "worker.annotation-integrity",
            "Annotation Worker",
            "annotation_integrity",
            "annotation path, mask shape and mask fraction evidence",
        ),
        (
            "worker.coverage-matrix",
            "Coverage Worker",
            "coverage_matrix",
            "coverage cell and split completeness evidence",
        ),
    ]
    if include_optional:
        worker_specs.append(
            (
                "worker.governance-audit",
                "Governance Worker",
                "governance_audit",
                "contract/manifest scope and governance evidence",
            )
        )

    identities = [
        _identity(
            "manager.gate",
            "Manager Agent",
            "manager",
            "accept goal, create the team task, enforce lifecycle and permission boundaries",
            ("goal-intake", "lifecycle", "permission-gate"),
        ),
        _identity(
            "leader.release-gate",
            "Release Gate Team Leader",
            "team_leader",
            "decompose the release-gate task, dispatch workers, collect outputs and route exceptions",
            (
                "task-decomposition",
                "dispatch",
                "context-assembly",
                "acceptance-routing",
            ),
            tuple(
                name
                for name in allowed
                if name
                in {
                    "image_quality",
                    "duplicate_leakage",
                    "annotation_integrity",
                    "coverage_matrix",
                    "governance_audit",
                }
            ),
        ),
    ]
    identities.extend(
        _identity(
            agent_id,
            display_name,
            "worker",
            purpose,
            ("typed-tool-execution", "evidence-emission"),
            (tool_name,),
        )
        for agent_id, display_name, tool_name, purpose in worker_specs
    )
    identities.extend(
        [
            _identity(
                "reviewer.ai-council",
                "Evidence Council Reviewer",
                "reviewer",
                "interpret cited tool evidence, cross-examine claims and disclose model limitations",
                (
                    "evidence-grounded-review",
                    "cross-examination",
                    "uncertainty-disclosure",
                ),
            ),
            _identity(
                "judge.policy",
                "Policy Judge",
                "judge",
                "apply frozen, fail-closed release rules; model output has advisory authority only",
                ("rule-evaluation", "defer", "decision-audit"),
            ),
            _identity(
                "operator.repair",
                "Repair Orchestrator",
                "operator",
                "execute only allowlisted reserve work orders and preserve the original batch",
                ("work-order-execution", "reserve-repair", "rollback-boundary"),
            ),
            _identity(
                "operator.audit-clerk",
                "Evidence Delivery Clerk",
                "operator",
                "write canonical trace, evidence matrix, hashes and delivery manifest",
                ("canonical-serialization", "hashing", "artifact-audit"),
            ),
        ]
    )

    skills = [
        _skill(
            "skill.contract-intake.v1",
            "Contract Intake",
            "manager.gate",
            "validate goal, manifest, contract and release scope before trust transfer",
            ("goal", "BatchManifest", "BatchContract"),
            ("input_sha256", "validated_context", "defer_on_schema_error"),
            ("Pydantic contract",),
            ("schema error", "path traversal", "missing input"),
            "read-only; never grants production release authority",
            ("schema_pass_rate", "input_hash_reproducibility", "defer_precision"),
        ),
        _skill(
            "skill.parallel-evidence-audit.v1",
            "Parallel Evidence Audit",
            "leader.release-gate",
            "dispatch independent domain workers under a bounded tool allowlist",
            ("validated_context", "tool_allowlist", "worker_budget"),
            ("ToolTrace[]", "Finding[]", "metric_summary"),
            ("TeamHarness task binding", "allowlisted tools"),
            ("tool error", "permission denied", "budget exhausted"),
            "workers cannot write decisions, contracts or arbitrary files",
            ("tool_success_rate", "finding_trace_completeness", "parallel_latency_ms"),
        ),
        _skill(
            "skill.evidence-grounded-council.v1",
            "Evidence-Grounded Council Review",
            "reviewer.ai-council",
            "produce role-scoped interpretations and challenges that cite tool evidence",
            ("Finding[]", "ToolTrace[]", "knowledge_hits"),
            ("AgentOpinion[]", "cross_examination", "limitations"),
            ("parallel evidence audit", "bounded knowledge cards"),
            ("unreferenced claim", "invalid JSON", "model timeout"),
            "advisory only; cannot override tool facts or Policy Judge",
            (
                "evidence_reference_coverage",
                "fallback_rate",
                "unresolved_objection_count",
            ),
        ),
        _skill(
            "skill.fail-closed-policy.v1",
            "Fail-Closed Policy Judge",
            "judge.policy",
            "evaluate release rules, counterfactual stability and governance thresholds",
            ("Finding[]", "ToolTrace[]", "CouncilTrace", "scenario profile"),
            ("GateDecision", "RuleCheck[]", "WorkOrder[]"),
            ("frozen policy", "scenario rule package"),
            ("missing evidence", "tool skipped", "counterfactual drift"),
            "only this identity may write the release decision; failures become DEFER/RECAPTURE",
            (
                "decision_determinism",
                "defer_on_missing_evidence",
                "counterfactual_flip_rate",
            ),
        ),
        _skill(
            "skill.reserve-recheck-delivery.v1",
            "Reserve Repair and Recheck",
            "operator.repair",
            "apply bounded work orders to a reserve copy and rerun the same contract",
            ("WorkOrder[]", "reserve_manifest", "original contract"),
            ("repaired_manifest", "verification GateResult", "evidence package"),
            ("fail-closed policy", "repair allowlist", "canonical serializer"),
            ("investigate-only order", "repair mismatch", "verification failure"),
            "never mutates the original batch; production actions remain human-approved",
            (
                "work_order_recall",
                "same_contract_recheck_rate",
                "original_batch_immutability",
            ),
        ),
    ]

    binding_count = 2 + len(worker_specs) + 4
    return AgentTeamsSnapshot(
        schema_version="agentteams.mapping.v1",
        protocol=PROTOCOL,
        team_id=TEAM_ID,
        team_name="VisionData Release Gate Team",
        room_id=ROOM_ID,
        task_id=f"task.release-gate.{run_id or 'local'}",
        scenario_profile=profile,
        runtime_adapter="local-deterministic",
        connection_status="mapped_not_connected",
        matrix_connected=False,
        manager_agent_id="manager.gate",
        leader_agent_id="leader.release-gate",
        worker_agent_ids=[item[0] for item in worker_specs],
        identities=identities,
        skills=skills,
        context_flow=[
            {
                "from": "manager.gate",
                "to": "leader.release-gate",
                "payload": "goal + manifest + contract + input_sha256",
            },
            {
                "from": "leader.release-gate",
                "to": "worker.*",
                "payload": "typed task + allowlisted tool + budget + context refs",
            },
            {
                "from": "worker.*",
                "to": "reviewer.ai-council",
                "payload": "ToolTrace + Finding + evidence refs",
            },
            {
                "from": "reviewer.ai-council",
                "to": "judge.policy",
                "payload": "advisory opinions + objections; no authority transfer",
            },
            {
                "from": "judge.policy",
                "to": "operator.repair",
                "payload": "typed decision + work orders + rule checks",
            },
            {
                "from": "operator.repair",
                "to": "operator.audit-clerk",
                "payload": "recheck result + evidence matrix + hashes",
            },
        ],
        failure_routes=[
            "missing/failed/skipped required tool -> DEFER; never reuse historical PASS",
            "unreferenced model claim -> deterministic fallback and unresolved warning",
            "investigate-only work order -> preserve original batch; human review pending",
            "production scope -> external authorization required; no local receipt fabrication",
        ],
        task_binding_count=binding_count,
        collaboration_event_count=0,
        boundary_notice=(
            "This is an AgentTeams/TeamHarness contract mapping for the local runtime. "
            "It is not a Matrix login, hosted AgentTeams receipt, or production deployment."
        ),
    )


def agentteams_task_binding(task_id: str, stage: str, actor: str) -> dict[str, str]:
    """Map a local runtime task to Team/Room/Task/Identity semantics."""

    if task_id.endswith(".intake") or actor in {"Trigger", "Task Trigger"}:
        agent_id = "manager.gate"
        task_kind = "goal_intake"
    elif (
        task_id.endswith(".route")
        or task_id.endswith(".memory")
        or task_id.endswith(".plan")
    ):
        agent_id = "leader.release-gate"
        task_kind = "coordination"
    elif ".tool." in task_id:
        tool_name = task_id.split(".tool.", 1)[1]
        agent_id = f"worker.{tool_name.replace('_', '-')}"
        task_kind = "worker_execution"
    elif task_id.endswith(".council"):
        agent_id = "reviewer.ai-council"
        task_kind = "advisory_review"
    elif task_id.endswith(".judge"):
        agent_id = "judge.policy"
        task_kind = "policy_decision"
    elif "repair" in task_id:
        agent_id = "operator.repair"
        task_kind = "bounded_repair"
    elif "delivery" in task_id:
        agent_id = "operator.audit-clerk"
        task_kind = "evidence_delivery"
    else:
        agent_id = "manager.gate"
        task_kind = "lifecycle"
    return {
        "agent_id": agent_id,
        "team_id": TEAM_ID,
        "room_id": ROOM_ID,
        "protocol": PROTOCOL,
        "task_kind": task_kind,
        "stage": stage,
    }


__all__ = [
    "PROTOCOL",
    "ROOM_ID",
    "TEAM_ID",
    "agentteams_task_binding",
    "build_agentteams_contract",
    "skill_contract_digest",
    "skill_for_task",
]
