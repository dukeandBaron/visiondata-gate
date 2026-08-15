"""Typed contracts for the observable VisionData Gate agent runtime."""

from __future__ import annotations

from enum import Enum
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator


class RuntimeModel(BaseModel):
    """Base model that prevents silent runtime-trace schema drift."""

    model_config = ConfigDict(extra="forbid")


class RuntimeStage(str, Enum):
    INTAKE = "intake"
    ROUTER = "router"
    MEMORY = "memory"
    PLANNER = "planner"
    TOOL = "tool"
    COUNCIL = "council"
    JUDGE = "judge"
    REPAIR = "repair"
    VERIFY = "verify"
    DELIVERY = "delivery"


class RuntimeStatus(str, Enum):
    QUEUED = "queued"
    RUNNING = "running"
    SUCCESS = "success"
    WARNING = "warning"
    ERROR = "error"
    SKIPPED = "skipped"


class ModelBackendKind(str, Enum):
    DETERMINISTIC = "deterministic"
    OPENAI_COMPATIBLE = "openai_compatible"


class ScenarioProfile(str, Enum):
    GENERIC = "generic"
    INDUSTRIAL = "industrial"
    AUTOMOTIVE = "automotive"
    FINANCE = "finance"
    EDUCATION = "education"
    WEARABLE = "wearable"


class RuntimeConfig(RuntimeModel):
    """Execution budget, permissions, and model-provider selection."""

    backend: ModelBackendKind = ModelBackendKind.DETERMINISTIC
    model: str = "local-evidence-reasoner-v2"
    endpoint: str | None = None
    allow_remote_model: bool = False
    model_timeout_seconds: float = Field(default=30.0, ge=2.0, le=120.0)
    max_model_calls: int = Field(default=5, ge=1, le=10)
    max_tool_calls: int = Field(default=8, ge=1, le=16)
    max_retries: int = Field(default=1, ge=0, le=2)
    parallel_workers: int = Field(default=4, ge=1, le=4)
    persist_memory: bool = True
    scenario_profile: ScenarioProfile = ScenarioProfile.GENERIC
    allowed_tools: list[str] = Field(
        default_factory=lambda: [
            "image_quality",
            "duplicate_leakage",
            "annotation_integrity",
            "coverage_matrix",
        ]
    )

    @field_validator("allowed_tools")
    @classmethod
    def unique_tools(cls, values: list[str]) -> list[str]:
        if not values:
            raise ValueError("at least one tool must be allowed")
        if len(values) != len(set(values)):
            raise ValueError("allowed_tools must be unique")
        return values


class AgentTask(RuntimeModel):
    task_id: str = Field(min_length=1)
    title: str = Field(min_length=1)
    stage: RuntimeStage
    actor: str = Field(min_length=1)
    dependencies: list[str] = Field(default_factory=list)
    capability: str = Field(min_length=1)
    permission_scope: list[str] = Field(default_factory=list)
    status: RuntimeStatus = RuntimeStatus.QUEUED
    output_refs: list[str] = Field(default_factory=list)


class ContextTransfer(RuntimeModel):
    """Auditable hand-off between two identities in one task run."""

    sequence: int = Field(ge=1)
    recorded_event_sequence: int = Field(ge=1)
    capture_mode: Literal["runtime_event"] = "runtime_event"
    phase: Literal["system", "initial", "verification"]
    source_agent_id: str = Field(min_length=1)
    target_agent_id: str = Field(min_length=1)
    source_task_id: str = Field(min_length=1)
    task_id: str = Field(min_length=1)
    payload_kind: str = Field(min_length=1)
    input_refs: list[str] = Field(default_factory=list)
    output_refs: list[str] = Field(default_factory=list)
    source_status: RuntimeStatus
    target_status: RuntimeStatus
    source_output_digest: str = Field(min_length=64, max_length=64)
    target_output_digest: str = Field(min_length=64, max_length=64)
    acceptance_basis: Literal[
        "source_success_target_success",
        "source_success_target_warning",
        "source_not_success",
        "target_not_runnable",
        "source_success_without_output_refs",
    ]
    payload_sha256: str = Field(min_length=64, max_length=64)
    status: Literal["accepted", "rejected", "deferred"]
    rejection_reason: str | None = None


class AgentIdentity(RuntimeModel):
    """AgentTeams identity contract for a domain team member."""

    agent_id: str = Field(min_length=1)
    display_name: str = Field(min_length=1)
    role_type: Literal[
        "manager", "team_leader", "worker", "reviewer", "judge", "operator"
    ]
    purpose: str = Field(min_length=1)
    capabilities: list[str] = Field(default_factory=list)
    allowed_tools: list[str] = Field(default_factory=list)
    permission_scope: list[str] = Field(default_factory=list)
    failure_policy: str = Field(min_length=1)


class SkillContract(RuntimeModel):
    """Reusable Skill metadata required by the Agent Infra track."""

    skill_id: str = Field(min_length=1)
    name: str = Field(min_length=1)
    version: str = Field(min_length=1)
    owner_agent_id: str = Field(min_length=1)
    purpose: str = Field(min_length=1)
    input_contract: list[str] = Field(default_factory=list)
    output_contract: list[str] = Field(default_factory=list)
    call_conditions: list[str] = Field(default_factory=list)
    dependencies: list[str] = Field(default_factory=list)
    failure_modes: list[str] = Field(default_factory=list)
    safety_boundary: str = Field(min_length=1)
    reusable_value: str = Field(min_length=1)
    quality_metrics: list[str] = Field(default_factory=list)
    version_history: list[str] = Field(default_factory=list)
    rollback_strategy: str = Field(default="pin_previous_contract", min_length=1)


class SkillExecution(RuntimeModel):
    """Run-bound receipt proving that a declared Skill was actually invoked."""

    sequence: int = Field(ge=1)
    recorded_event_sequence: int = Field(ge=1)
    phase: Literal["system", "initial", "verification"]
    task_id: str = Field(min_length=1)
    agent_id: str = Field(min_length=1)
    skill_id: str = Field(min_length=1)
    skill_version: str = Field(min_length=1)
    skill_contract_digest: str = Field(min_length=64, max_length=64)
    task_status: RuntimeStatus
    qualification_status: Literal["qualified", "deferred", "rejected"]
    input_refs: list[str] = Field(default_factory=list)
    output_refs: list[str] = Field(default_factory=list)
    input_digest: str = Field(min_length=64, max_length=64)
    output_digest: str = Field(min_length=64, max_length=64)
    qualification_checks: dict[str, bool] = Field(default_factory=dict)
    rollback_action: str = Field(min_length=1)
    rejection_reason: str | None = None


class ApprovalHandoff(RuntimeModel):
    """Explicit boundary between a local evidence run and human authorization.

    The runtime never fabricates an approval receipt.  A PASS in the local
    demo is only a sandbox eligibility result; production or customer-data
    actions stay in this pending handoff state until an authorized person
    records an external decision.
    """

    schema_version: Literal["visiondata-gate.approval-handoff.v1"] = (
        "visiondata-gate.approval-handoff.v1"
    )
    scope: Literal["sandbox_experiment_training_pool", "production_system"]
    mode: Literal[
        "simulation_only",
        "external_authorization_required",
        "human_review_pending",
        "approved_for_sandbox",
    ]
    status: Literal["not_requested", "pending", "blocked", "recorded"]
    required_role: str = Field(min_length=1)
    reason: str = Field(min_length=1)
    evidence_refs: list[str] = Field(default_factory=list)
    receipt_ref: str | None = None


class AgentTeamsSnapshot(RuntimeModel):
    """Inspectable Team/Room/Task/Identity/Skill mapping.

    This model records protocol alignment separately from transport
    connectivity, so a local run cannot be mistaken for a hosted Matrix run.
    """

    schema_version: Literal["agentteams.mapping.v1"] = "agentteams.mapping.v1"
    protocol: str = Field(min_length=1)
    team_id: str = Field(min_length=1)
    team_name: str = Field(min_length=1)
    room_id: str = Field(min_length=1)
    task_id: str = Field(min_length=1)
    scenario_profile: ScenarioProfile
    runtime_adapter: str = Field(min_length=1)
    connection_status: Literal["mapped_not_connected", "connected", "degraded"]
    matrix_connected: bool = False
    manager_agent_id: str = Field(min_length=1)
    leader_agent_id: str = Field(min_length=1)
    worker_agent_ids: list[str] = Field(min_length=3)
    identities: list[AgentIdentity] = Field(min_length=3)
    skills: list[SkillContract] = Field(min_length=1)
    context_flow: list[dict[str, str]] = Field(default_factory=list)
    failure_routes: list[str] = Field(default_factory=list)
    task_binding_count: int = Field(ge=0)
    collaboration_event_count: int = Field(ge=0)
    boundary_notice: str = Field(min_length=1)


class RuntimeEvent(RuntimeModel):
    sequence: int = Field(ge=1)
    phase: Literal["system", "initial", "verification"]
    stage: RuntimeStage
    actor: str = Field(min_length=1)
    action: str = Field(min_length=1)
    status: RuntimeStatus
    summary: str = Field(min_length=1)
    task_id: str | None = None
    tool_name: str | None = None
    duration_ms: float = Field(default=0.0, ge=0.0)
    evidence_refs: list[str] = Field(default_factory=list)
    retry: int = Field(default=0, ge=0)
    collaboration: dict[str, str] = Field(default_factory=dict)


class KnowledgeHit(RuntimeModel):
    card_id: str
    title: str
    scope: str
    excerpt: str
    source: str
    score: float = Field(ge=0.0)
    source_type: str = Field(default="project-policy", min_length=1)
    source_version: str = Field(default="2026-08-12", min_length=1)
    last_verified: str = Field(default="2026-08-12", min_length=1)
    permission_scope: str = Field(default="local-read-only", min_length=1)
    freshness: str = Field(default="frozen", min_length=1)


class MemoryRecord(RuntimeModel):
    run_id: str
    phase: Literal["initial", "verification"]
    batch_id: str
    decision: str
    finding_codes: list[str]
    completed_tools: list[str]
    backend: str
    summary: str


class MemorySnapshot(RuntimeModel):
    working: dict[str, Any] = Field(default_factory=dict)
    session: list[str] = Field(default_factory=list)
    long_term: list[MemoryRecord] = Field(default_factory=list)
    semantic: list[KnowledgeHit] = Field(default_factory=list)
    role: dict[str, str] = Field(default_factory=dict)


class RuntimeTrace(RuntimeModel):
    schema_version: Literal["visiondata-gate.agent-runtime.v2"] = (
        "visiondata-gate.agent-runtime.v2"
    )
    run_id: str
    execution_config_sha256: str = Field(min_length=64, max_length=64)
    goal: str
    intent: str
    backend: str
    backend_connected: bool
    fallback_used: bool
    status: RuntimeStatus
    tasks: list[AgentTask]
    events: list[RuntimeEvent]
    memory: MemorySnapshot
    model_call_count: int = Field(default=0, ge=0)
    tool_call_count: int = Field(default=0, ge=0)
    judge_decisions: list[str] = Field(default_factory=list)
    unresolved: list[str] = Field(default_factory=list)
    boundary_notice: str
    scenario_profile: ScenarioProfile = ScenarioProfile.GENERIC
    agentteams: AgentTeamsSnapshot | None = None
    approval_handoff: ApprovalHandoff | None = None
    context_transfers: list[ContextTransfer] = Field(default_factory=list)
    skill_executions: list[SkillExecution] = Field(default_factory=list)


__all__ = [
    "AgentTask",
    "ContextTransfer",
    "AgentIdentity",
    "AgentTeamsSnapshot",
    "ApprovalHandoff",
    "KnowledgeHit",
    "MemoryRecord",
    "MemorySnapshot",
    "ModelBackendKind",
    "ScenarioProfile",
    "RuntimeConfig",
    "RuntimeEvent",
    "RuntimeStage",
    "RuntimeStatus",
    "RuntimeTrace",
    "SkillContract",
    "SkillExecution",
]
