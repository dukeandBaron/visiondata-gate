"""Strict product-layer contracts for the local enterprise workspace prototype."""

from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

from .runtime_models import ScenarioProfile


PUBLIC_TOOL_NAMES = frozenset(
    {
        "image_quality",
        "duplicate_leakage",
        "annotation_integrity",
        "coverage_matrix",
        "governance_audit",
    }
)


class ProductModel(BaseModel):
    """Reject silent API and persistence schema drift."""

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


class ErrorDetail(ProductModel):
    code: str = Field(min_length=1)
    message: str = Field(min_length=1)


class ErrorEnvelope(ProductModel):
    error: ErrorDetail


class TaskExecutionStatus(str, Enum):
    CREATED = "CREATED"
    PLANNED = "PLANNED"
    RUNNING = "RUNNING"
    VERIFYING = "VERIFYING"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"
    CANCELLED = "CANCELLED"
    ARCHIVED = "ARCHIVED"


class TaskInterventionAction(str, Enum):
    """Human actions that are persisted in the append-only task audit log."""

    APPROVE_PLAN = "approve_plan"
    CANCEL_PLAN = "cancel_plan"
    ACKNOWLEDGE_RESULT = "acknowledge_result"
    REQUEST_CHANGES = "request_changes"


class DataSourceKind(str, Enum):
    SYNTHETIC_DEMO = "synthetic_demo"
    LOCAL_AUTHORIZED_DIRECTORY = "local_authorized_directory"
    EXTERNAL_RESIDENCY_REFERENCE = "external_residency_reference"


class LocalSourceAdapterKind(str, Enum):
    """Allowlisted adapters that may inspect a server-local source read-only."""

    OMNI_AD_30_RELEASE = "omni_ad_30_release"
    OPERATOR_PROJECT_SNAPSHOT = "operator_project_snapshot"


class SourceAuthorizationEventType(str, Enum):
    """Immutable lifecycle events for a server-local source authorization."""

    GRANTED = "GRANTED"
    REVOKED = "REVOKED"
    EXPIRED = "EXPIRED"


def _validate_aware_timestamp(value: str | None) -> str | None:
    if value is None:
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ValueError("timestamp must be ISO-8601") from exc
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ValueError("timestamp must include an explicit UTC offset")
    return parsed.isoformat(timespec="milliseconds")


class AuthorizeLocalSourceRequest(ProductModel):
    """Operator attestation for one allowlisted, server-local data source.

    ``root_path`` is an input-only server path.  Public responses and task
    evidence expose only its digest and never serialize the path itself.
    """

    workspace_id: str = Field(min_length=1)
    display_name: str = Field(min_length=1, max_length=120)
    root_path: str = Field(min_length=1, max_length=2048)
    source_archive_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    adapter_kind: LocalSourceAdapterKind = LocalSourceAdapterKind.OMNI_AD_30_RELEASE
    purpose: str = Field(min_length=8, max_length=500)
    rights_basis: str = Field(min_length=8, max_length=500)
    residency: str = Field(
        default="server_local_in_place", min_length=3, max_length=120
    )
    operator_attests_authorized_use: Literal[True]
    read_only: Literal[True] = True
    raw_redistribution_allowed: Literal[False] = False
    authorization_valid_until: str | None = None
    source_path_retention_policy: Literal[
        "private_binding_retained_until_operator_cleanup"
    ] = "private_binding_retained_until_operator_cleanup"
    redacted_receipt_retention_days: int = Field(default=3650, ge=30, le=36500)
    derived_artifact_retention_days: int = Field(default=90, ge=1, le=3650)
    post_revocation_source_bytes: Literal["operator_managed_in_place_not_deleted"] = (
        "operator_managed_in_place_not_deleted"
    )

    @field_validator("authorization_valid_until")
    @classmethod
    def validate_authorization_valid_until(cls, value: str | None) -> str | None:
        return _validate_aware_timestamp(value)


class AuthorizeOperatorProjectSnapshotRequest(ProductModel):
    """Create a server-derived source grant from one local Operator project.

    Asset and annotation digests are intentionally absent: the server reads and
    verifies those identities from ``OperatorImageStore`` instead of trusting a
    browser-provided aggregate.
    """

    workspace_id: str = Field(min_length=1)
    project_id: str = Field(min_length=1)
    display_name: str = Field(default="工作簿受控快照", min_length=1, max_length=120)
    purpose: str = Field(
        default="用于本地工业视觉数据治理 Agent 的只读确定性审核。",
        min_length=8,
        max_length=500,
    )
    rights_basis: str = Field(
        default="操作者确认其有权在本机项目范围内处理这些资产。",
        min_length=8,
        max_length=500,
    )
    operator_attests_authorized_use: Literal[True]


class RevokeLocalSourceAuthorizationRequest(ProductModel):
    """Optimistic-concurrency request that permanently closes one grant chain."""

    reason: str = Field(min_length=8, max_length=1000)
    expected_latest_event_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")


class SourceAuthorizationEventReceipt(ProductModel):
    """One hash-chained, append-only source authorization lifecycle event."""

    schema_version: Literal["visiondata-gate.source-authorization-event.v1"] = (
        "visiondata-gate.source-authorization-event.v1"
    )
    event_id: str
    source_id: str
    workspace_id: str
    sequence: int = Field(ge=1)
    event_type: SourceAuthorizationEventType
    actor_kind: Literal["operator", "system"]
    actor_id: str
    reason: str
    effective_at: str
    created_at: str
    previous_event_sha256: str | None = Field(default=None, pattern=r"^[0-9a-f]{64}$")
    fail_closed_task_ids: list[str] = Field(default_factory=list)
    event_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    claim_boundary: str = (
        "This event records control-plane authorization state. Revocation or expiry "
        "blocks future source reads but does not assert deletion of operator-managed "
        "bytes, legal ownership, or production approval."
    )


class LocalSourceAuthorizationReceipt(ProductModel):
    """Path-redacted receipt returned to product clients and evidence packages."""

    schema_version: Literal[
        "visiondata-gate.local-source-authorization.v1",
        "visiondata-gate.local-source-authorization.v2",
        "visiondata-gate.local-source-authorization.v3",
    ] = "visiondata-gate.local-source-authorization.v3"
    source_id: str
    workspace_id: str
    source_kind: Literal[DataSourceKind.LOCAL_AUTHORIZED_DIRECTORY] = (
        DataSourceKind.LOCAL_AUTHORIZED_DIRECTORY
    )
    adapter_kind: LocalSourceAdapterKind
    display_name: str
    root_path_sha256: str = Field(min_length=64, max_length=64)
    source_archive_sha256: str = Field(min_length=64, max_length=64)
    purpose: str
    rights_basis: str
    residency: str
    operator_attests_authorized_use: Literal[True]
    read_only: Literal[True]
    raw_redistribution_allowed: Literal[False]
    source_assets_copied_into_product: bool = False
    derived_from_source_id: str | None = None
    derived_version_id: str | None = None
    data_profile: dict[str, Any]
    status: Literal["active", "revoked", "expired"] = "active"
    authorization_valid_until: str | None = None
    source_path_retention_policy: Literal[
        "private_binding_retained_until_operator_cleanup"
    ] = "private_binding_retained_until_operator_cleanup"
    redacted_receipt_retention_days: int = Field(default=3650, ge=30, le=36500)
    derived_artifact_retention_days: int = Field(default=90, ge=1, le=3650)
    post_revocation_source_bytes: Literal["operator_managed_in_place_not_deleted"] = (
        "operator_managed_in_place_not_deleted"
    )
    authorization_event_count: int = Field(default=1, ge=1)
    latest_authorization_event_type: SourceAuthorizationEventType = (
        SourceAuthorizationEventType.GRANTED
    )
    latest_authorization_event_sha256: str = Field(
        default="0" * 64, pattern=r"^[0-9a-f]{64}$"
    )
    created_at: str
    claim_boundary: str = (
        "This receipt records a local operator attestation and allowlist check; it is "
        "not legal ownership, organizer endorsement, customer acceptance, or production "
        "authorization."
    )


class CreateUserRequest(ProductModel):
    display_name: str = Field(min_length=1, max_length=80)
    email: str | None = Field(default=None, max_length=254)

    @field_validator("email")
    @classmethod
    def normalize_email(cls, value: str | None) -> str | None:
        if value is None or not value:
            return None
        normalized = value.casefold()
        if "@" not in normalized or normalized.startswith("@"):
            raise ValueError("email must contain a local part and @")
        return normalized


class UserRecord(ProductModel):
    user_id: str
    display_name: str
    email: str | None = None
    created_at: str


class CreateWorkspaceRequest(ProductModel):
    name: str = Field(min_length=1, max_length=100)
    owner_user_id: str = Field(min_length=1)


class WorkspaceRecord(ProductModel):
    workspace_id: str
    name: str
    owner_user_id: str
    role: str = "owner"
    created_at: str


class CreateProjectRequest(ProductModel):
    workspace_id: str = Field(min_length=1)
    name: str = Field(min_length=1, max_length=120)
    description: str = Field(default="", max_length=500)
    scenario_profile: ScenarioProfile = ScenarioProfile.INDUSTRIAL
    source_kind: DataSourceKind = DataSourceKind.SYNTHETIC_DEMO


class ProjectRecord(ProductModel):
    project_id: str
    workspace_id: str
    name: str
    description: str
    scenario_profile: ScenarioProfile
    source_kind: DataSourceKind
    created_at: str
    updated_at: str


class CreateTaskRequest(ProductModel):
    project_id: str = Field(min_length=1)
    goal: str = Field(min_length=8, max_length=1200)
    seed: int = Field(default=20_260_809, ge=0, le=99_999_999)
    scenario_profile: ScenarioProfile | None = None
    source_kind: DataSourceKind = DataSourceKind.SYNTHETIC_DEMO
    source_id: str | None = Field(default=None, min_length=1)
    plan_approval_required: bool = False
    allowed_tools: list[str] = Field(
        default_factory=lambda: [
            "image_quality",
            "duplicate_leakage",
            "annotation_integrity",
            "coverage_matrix",
        ],
        min_length=1,
        max_length=8,
    )

    @field_validator("allowed_tools")
    @classmethod
    def unique_tools(cls, values: list[str]) -> list[str]:
        if len(values) != len(set(values)):
            raise ValueError("allowed_tools must be unique")
        unknown = sorted(set(values) - PUBLIC_TOOL_NAMES)
        if unknown:
            raise ValueError(f"unknown public tools: {', '.join(unknown)}")
        return values


class SubmitHostedAgentTeamsTaskRequest(ProductModel):
    """Explicit human gate for submitting one existing task to Hosted AgentTeams."""

    approval_id: str = Field(
        min_length=1,
        max_length=128,
        pattern=r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$",
    )
    wait_for_remote_execution: bool = False


class TaskRecord(ProductModel):
    task_id: str
    workspace_id: str
    project_id: str
    created_by: str
    goal: str
    seed: int
    scenario_profile: ScenarioProfile
    source_kind: DataSourceKind
    source_id: str | None = None
    plan_approval_required: bool = False
    allowed_tools: list[str]
    request_sha256: str
    idempotency_key: str | None = None
    execution_status: TaskExecutionStatus
    current_phase: str
    initial_decision: str | None = None
    final_decision: str | None = None
    runtime_status: str | None = None
    artifact_root_rel: str | None = None
    trace_rel: str | None = None
    trace_sha256: str | None = None
    evidence_zip_rel: str | None = None
    evidence_sha256: str | None = None
    error_code: str | None = None
    error_message: str | None = None
    created_at: str
    updated_at: str
    started_at: str | None = None
    completed_at: str | None = None


class TaskPlanStep(ProductModel):
    step_id: str = Field(min_length=1)
    phase: str = Field(min_length=1)
    agent_role: str = Field(min_length=1)
    objective: str = Field(min_length=1)
    tool_names: list[str] = Field(default_factory=list)
    human_gate: bool = False


class TaskPlanPreview(ProductModel):
    """Deterministic execution preview bound to the immutable task request."""

    schema_version: Literal[
        "visiondata-gate.task-plan-preview.v1",
        "visiondata-gate.task-plan-preview.v2",
    ] = "visiondata-gate.task-plan-preview.v2"
    task_id: str
    request_sha256: str = Field(min_length=64, max_length=64)
    before_snapshot_sha256: str = Field(min_length=64, max_length=64)
    plan_sha256: str = Field(min_length=64, max_length=64)
    goal: str
    scenario_profile: ScenarioProfile
    source_kind: DataSourceKind
    source_id: str | None = None
    source_binding_sha256: str | None = Field(default=None, pattern=r"^[0-9a-f]{64}$")
    allowed_tools: list[str]
    approval_required: bool
    steps: list[TaskPlanStep] = Field(min_length=1)
    dynamic_replanning_policy: str
    production_authority: Literal["human_only"] = "human_only"
    claim_boundary: str


class TaskPlanApprovalBinding(ProductModel):
    """Hash-sealed facts that a human actually approved before execution.

    The binding is deliberately separate from the free-text approval note.  It
    freezes the task request, rendered plan, current task snapshot, source
    profile, and policy-bearing re-verification contract so a later source or
    rule drift cannot silently reuse an old approval.
    """

    schema_version: Literal[
        "visiondata-gate.task-plan-approval-binding.v1",
        "visiondata-gate.task-plan-approval-binding.v2",
    ] = "visiondata-gate.task-plan-approval-binding.v2"
    request_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    before_snapshot_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    plan_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    contract_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    source_profile_status: Literal["MATCHED", "NOT_APPLICABLE"]
    source_profile_sha256: str | None = Field(default=None, pattern=r"^[0-9a-f]{64}$")
    source_authorization_event_sha256: str | None = Field(
        default=None, pattern=r"^[0-9a-f]{64}$"
    )
    binding_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")


class TaskInterventionRequest(ProductModel):
    action: TaskInterventionAction
    note: str = Field(min_length=2, max_length=1000)


class TaskInterventionRecord(ProductModel):
    """One immutable operator action with its pre-change task snapshot."""

    schema_version: Literal["visiondata-gate.task-intervention.v1"] = (
        "visiondata-gate.task-intervention.v1"
    )
    intervention_id: str
    task_id: str
    sequence: int = Field(ge=1)
    actor_user_id: str
    action: TaskInterventionAction
    note: str
    before_status: TaskExecutionStatus
    before_phase: str
    before_snapshot_sha256: str = Field(min_length=64, max_length=64)
    plan_sha256: str = Field(min_length=64, max_length=64)
    approval_binding: TaskPlanApprovalBinding | None = None
    created_at: str


class TaskEventRecord(ProductModel):
    task_id: str
    sequence: int
    phase: str
    stage: str
    status: str
    summary: str
    payload_json: str
    created_at: str


class HealthResponse(ProductModel):
    status: Literal["ok"] = "ok"
    service: Literal["visiondata-gate"] = "visiondata-gate"
    mode: Literal["local_multi_workspace_prototype"] = "local_multi_workspace_prototype"
    api_ready: bool = True
    production_ready: bool = False
    authentication: Literal[
        "session_token_bound_principal",
        "test_actor_header_bypass",
        "not_configured_fail_closed",
    ] = "not_configured_fail_closed"
    agentteams_connection: Literal["mapped_not_connected"] = "mapped_not_connected"
    data_sources: dict[str, str]


__all__ = [
    "AuthorizeLocalSourceRequest",
    "AuthorizeOperatorProjectSnapshotRequest",
    "CreateProjectRequest",
    "CreateTaskRequest",
    "CreateUserRequest",
    "CreateWorkspaceRequest",
    "DataSourceKind",
    "ErrorDetail",
    "ErrorEnvelope",
    "HealthResponse",
    "LocalSourceAdapterKind",
    "LocalSourceAuthorizationReceipt",
    "RevokeLocalSourceAuthorizationRequest",
    "SourceAuthorizationEventReceipt",
    "SourceAuthorizationEventType",
    "SubmitHostedAgentTeamsTaskRequest",
    "ProductModel",
    "PUBLIC_TOOL_NAMES",
    "ProjectRecord",
    "TaskEventRecord",
    "TaskExecutionStatus",
    "TaskInterventionAction",
    "TaskPlanApprovalBinding",
    "TaskInterventionRecord",
    "TaskInterventionRequest",
    "TaskPlanPreview",
    "TaskPlanStep",
    "TaskRecord",
    "UserRecord",
    "WorkspaceRecord",
]
