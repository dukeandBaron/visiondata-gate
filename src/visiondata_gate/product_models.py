"""Strict product-layer contracts for the local enterprise workspace prototype."""

from __future__ import annotations

from enum import Enum
from typing import Literal

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
    ARCHIVED = "ARCHIVED"


class DataSourceKind(str, Enum):
    SYNTHETIC_DEMO = "synthetic_demo"
    LOCAL_AUTHORIZED_DIRECTORY = "local_authorized_directory"
    EXTERNAL_RESIDENCY_REFERENCE = "external_residency_reference"


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


class TaskRecord(ProductModel):
    task_id: str
    workspace_id: str
    project_id: str
    created_by: str
    goal: str
    seed: int
    scenario_profile: ScenarioProfile
    source_kind: DataSourceKind
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
    authentication: Literal["not_configured"] = "not_configured"
    agentteams_connection: Literal["mapped_not_connected"] = "mapped_not_connected"
    data_sources: dict[str, str]


__all__ = [
    "CreateProjectRequest",
    "CreateTaskRequest",
    "CreateUserRequest",
    "CreateWorkspaceRequest",
    "DataSourceKind",
    "ErrorDetail",
    "ErrorEnvelope",
    "HealthResponse",
    "ProductModel",
    "PUBLIC_TOOL_NAMES",
    "ProjectRecord",
    "TaskEventRecord",
    "TaskExecutionStatus",
    "TaskRecord",
    "UserRecord",
    "WorkspaceRecord",
]
