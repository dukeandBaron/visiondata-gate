"""Version-pinned Hosted AgentTeams v1.2.3 transport and evidence bundle.

The Controller REST API is an internal, version-pinned control-plane API.  A
successful ``POST /projects`` only registers project metadata; it does not
prove TeamHarness delegated work.  This adapter therefore records Controller
readiness, project registration, the idempotent Matrix ingress event, and
observed workflow execution as separate facts.  It never upgrades the local
runtime's ``mapped_not_connected`` claim.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
import hashlib
import hmac
import json
import os
from pathlib import Path
import re
import time
from typing import Any, Callable, Literal, Mapping
import urllib.parse

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    ValidationError,
    field_validator,
    model_validator,
)

from .agentteams_v122 import build_skill_distribution_plan
from .evidence import canonical_json_bytes, sha256_bytes
from .network_resilience import (
    HTTPClientPolicy,
    HTTPExchangeReceipt,
    HTTPJSONResult,
    HTTPTransportError,
    ResilientJSONClient,
)


HOSTED_AGENTTEAMS_VERSION = "v1.2.3"
HOSTED_AGENTTEAMS_COMMIT = "223ddc2b8073e4c8b93bcbb15e1d717f196c04d9"
HOSTED_AGENTTEAMS_REPOSITORY = "https://github.com/agentscope-ai/AgentTeams"

_SAFE_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$")
_SHA256 = re.compile(r"^[0-9a-f]{64}$")
_REMOTE_EXECUTION_STATES = frozenset({"in-progress", "completed"})
_PROJECTION_FILENAMES = {
    "version": "version.json",
    "team": "team.json",
    "workers": "workers.json",
    "project": "project.json",
    "matrix_ingress": "matrix-ingress.json",
    "workflow": "workflow.json",
}
_PROJECTION_CHECK_KEYS: dict[str, frozenset[str]] = {
    "version": frozenset({"controller_version_endpoint_observed"}),
    "team": frozenset(
        {
            "controller_team_observed",
            "team_name_matches",
            "team_phase_active",
            "team_members_match_expected",
            "team_leader_matches_expected",
            "team_room_observed",
            "leader_dm_room_observed",
            "leader_ready",
            "all_team_workers_ready",
        }
    ),
    "workers": frozenset(
        {
            "controller_workers_observed",
            "worker_names_unique",
            "expected_workers_observed",
            "workers_phase_running",
            "workers_team_matches",
            "workers_roles_match",
            "workers_matrix_identities_observed",
            "worker_skill_specs_cover_expected",
        }
    ),
    "project": frozenset({"project_registration_observed"}),
    "matrix_ingress": frozenset({"leader_matrix_ingress_observed"}),
    "workflow": frozenset(
        {
            "workflow_project_observed",
            "project_registration_observed",
            "remote_task_execution_observed",
        }
    ),
}
_PROJECTION_COUNT_KEYS: dict[str, frozenset[str]] = {
    "version": frozenset(),
    "team": frozenset({"member_count", "ready_worker_count", "total_worker_count"}),
    "workers": frozenset({"reported_total", "worker_count"}),
    "project": frozenset(),
    "matrix_ingress": frozenset(),
    "workflow": frozenset({"node_count"}),
}
_WORKFLOW_STATUS_KEYS = (
    "pending",
    "delegated",
    "blocked",
    "revision",
    "in-progress",
    "completed",
    "other",
)


class AgentTeamsTransportMode(str, Enum):
    OFF = "off"
    SHADOW = "shadow"
    GATED = "gated"


class _StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class _ExternalModel(BaseModel):
    model_config = ConfigDict(extra="forbid", populate_by_name=True, strict=True)


def _normalize_base_url(value: str, *, field_name: str) -> str:
    candidate = value.strip().rstrip("/")
    parsed = urllib.parse.urlsplit(candidate)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        raise ValueError(f"{field_name} must be an absolute HTTP(S) URL")
    if parsed.username or parsed.password or parsed.query or parsed.fragment:
        raise ValueError(f"{field_name} cannot contain credentials, query, or fragment")
    return urllib.parse.urlunsplit(
        (parsed.scheme, parsed.netloc, parsed.path.rstrip("/"), "", "")
    )


class HostedAgentTeamsConfig(_StrictModel):
    mode: AgentTeamsTransportMode = AgentTeamsTransportMode.OFF
    controller_base_url: str
    controller_allowed_hosts: list[str] = Field(min_length=1)
    controller_allow_local: bool = False
    matrix_base_url: str | None = None
    matrix_allowed_hosts: list[str] = Field(default_factory=list)
    matrix_allow_local: bool = False
    team_name: str = "visiondata-gate"
    write_enabled: bool = False
    timeout_seconds: float = Field(default=10.0, ge=0.05, le=120.0)
    read_max_retries: int = Field(default=1, ge=0, le=3)
    poll_timeout_seconds: float = Field(default=60.0, ge=0.0, le=900.0)
    poll_interval_seconds: float = Field(default=1.0, ge=0.01, le=30.0)
    max_response_bytes: int = Field(default=2_000_000, ge=1, le=20_000_000)
    provider_version: Literal["v1.2.3"] = HOSTED_AGENTTEAMS_VERSION
    provider_commit: Literal["223ddc2b8073e4c8b93bcbb15e1d717f196c04d9"] = (
        HOSTED_AGENTTEAMS_COMMIT
    )

    @field_validator("controller_base_url")
    @classmethod
    def validate_controller_url(cls, value: str) -> str:
        return _normalize_base_url(value, field_name="controller_base_url")

    @field_validator("matrix_base_url")
    @classmethod
    def validate_matrix_url(cls, value: str | None) -> str | None:
        if value is None or not value.strip():
            return None
        return _normalize_base_url(value, field_name="matrix_base_url")

    @field_validator("controller_allowed_hosts", "matrix_allowed_hosts")
    @classmethod
    def normalize_hosts(cls, values: list[str]) -> list[str]:
        normalized = [value.strip().casefold().rstrip(".") for value in values]
        if any(not value for value in normalized):
            raise ValueError("host allowlists cannot contain blank values")
        if len(normalized) != len(set(normalized)):
            raise ValueError("host allowlists must contain unique values")
        return normalized

    @field_validator("team_name")
    @classmethod
    def validate_team_name(cls, value: str) -> str:
        if not _SAFE_ID.fullmatch(value):
            raise ValueError("team_name must be a plain AgentTeams token")
        return value

    @model_validator(mode="after")
    def validate_matrix_policy(self) -> "HostedAgentTeamsConfig":
        if self.matrix_base_url and not self.matrix_allowed_hosts:
            raise ValueError(
                "matrix_allowed_hosts is required when matrix_base_url is set"
            )
        return self


class ControllerVersion(_ExternalModel):
    controller: str = Field(min_length=1, max_length=128)


class ControllerTeamMember(_ExternalModel):
    name: str = Field(min_length=1, max_length=128)
    role: str = Field(min_length=1, max_length=64)


class ControllerTeam(_ExternalModel):
    name: str = Field(min_length=1, max_length=128)
    phase: str = Field(min_length=1, max_length=64)
    worker_members: list[ControllerTeamMember] = Field(
        alias="workerMembers", max_length=128
    )
    leader_name: str = Field(alias="leaderName", min_length=1, max_length=128)
    team_room_id: str = Field(alias="teamRoomID", default="", max_length=512)
    leader_dm_room_id: str = Field(alias="leaderDMRoomID", default="", max_length=512)
    leader_ready: bool = Field(alias="leaderReady")
    ready_workers: int = Field(alias="readyWorkers", ge=0)
    total_workers: int = Field(alias="totalWorkers", ge=0)


class ControllerWorker(_ExternalModel):
    name: str = Field(min_length=1, max_length=128)
    phase: str = Field(min_length=1, max_length=64)
    skills: list[str] = Field(default_factory=list, max_length=128)
    container_state: str = Field(alias="containerState", default="", max_length=64)
    matrix_user_id: str = Field(alias="matrixUserID", default="", max_length=512)
    room_id: str = Field(alias="roomID", default="", max_length=512)
    team: str = Field(default="", max_length=128)
    role: str = Field(default="", max_length=64)

    @field_validator("skills")
    @classmethod
    def bound_skills(cls, values: list[str]) -> list[str]:
        if any(not value or len(value) > 128 for value in values):
            raise ValueError("worker skill identifiers are invalid")
        return values


class ControllerWorkerList(_ExternalModel):
    workers: list[ControllerWorker] = Field(max_length=128)
    total: int = Field(ge=0)


class ControllerProject(_ExternalModel):
    project_id: str = Field(min_length=1, max_length=128)
    title: str = Field(min_length=1, max_length=200)
    status: str = Field(min_length=1, max_length=64)
    team_id: str = Field(default="", max_length=128)
    plan_type: str = Field(default="dag", max_length=64)


class ControllerWorkflowNode(_ExternalModel):
    id: str = Field(min_length=1, max_length=128)
    name: str = Field(min_length=1, max_length=200)
    status: str = Field(min_length=1, max_length=64)
    assignee: str = Field(default="", max_length=512)


class ControllerWorkflow(_ExternalModel):
    project_id: str = Field(min_length=1, max_length=128)
    title: str = Field(min_length=1, max_length=200)
    status: str = Field(min_length=1, max_length=64)
    team_id: str = Field(default="", max_length=128)
    plan_type: str = Field(default="dag", max_length=64)
    nodes: list[ControllerWorkflowNode] = Field(default_factory=list, max_length=512)
    next: list[str] = Field(default_factory=list, max_length=512)

    @field_validator("next")
    @classmethod
    def bound_next_ids(cls, values: list[str]) -> list[str]:
        if any(not value or len(value) > 128 for value in values):
            raise ValueError("workflow next identifiers are invalid")
        return values


class MatrixSendResponse(_ExternalModel):
    event_id: str = Field(min_length=1, max_length=512)


class HostedProjectSubmission(_StrictModel):
    source_run_id: str = Field(min_length=1, max_length=256)
    title: str = Field(min_length=1, max_length=200)
    goal: str = Field(min_length=1, max_length=8_000)
    project_id: str | None = None
    requester: str | None = Field(default=None, max_length=256)
    wait_for_remote_execution: bool = False

    @field_validator("project_id")
    @classmethod
    def validate_project_id(cls, value: str | None) -> str | None:
        if value is not None and not _SAFE_ID.fullmatch(value):
            raise ValueError("project_id must match the AgentTeams safe-id contract")
        return value


class EvidenceProjectionRef(_StrictModel):
    path: str = Field(min_length=1)
    projection_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    projection_bytes: int = Field(ge=1)
    source_response_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    source_response_bytes: int = Field(ge=1)
    evidence_kind: Literal[
        "version", "team", "workers", "project", "matrix_ingress", "workflow"
    ]
    media_type: Literal["application/json"] = "application/json"


class ObservedHostedWorker(_StrictModel):
    name: str
    phase: Literal["Running", "UNEXPECTED"]
    role: Literal["team_leader", "worker", "UNEXPECTED"]
    team: str
    skills: list[str]
    matrix_user_id_present: bool
    room_id_present: bool


class WorkflowStatusCounts(_StrictModel):
    pending: int = Field(default=0, ge=0)
    delegated: int = Field(default=0, ge=0)
    blocked: int = Field(default=0, ge=0)
    revision: int = Field(default=0, ge=0)
    in_progress: int = Field(default=0, ge=0)
    completed: int = Field(default=0, ge=0)
    other: int = Field(default=0, ge=0)


class HostedEvidenceProjection(_StrictModel):
    schema_version: Literal["visiondata-gate.agentteams-evidence-projection.v1"] = (
        "visiondata-gate.agentteams-evidence-projection.v1"
    )
    evidence_kind: Literal[
        "version", "team", "workers", "project", "matrix_ingress", "workflow"
    ]
    source_response_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    source_response_bytes: int = Field(ge=1)
    checks: dict[str, bool]
    counts: dict[str, int] = Field(default_factory=dict)
    observed_workers: list[ObservedHostedWorker] = Field(default_factory=list)
    observed_skill_assignments: dict[str, list[str]] = Field(default_factory=dict)
    workflow_status_counts: WorkflowStatusCounts = Field(
        default_factory=WorkflowStatusCounts
    )

    @model_validator(mode="after")
    def validate_allowlisted_projection(self) -> "HostedEvidenceProjection":
        if set(self.checks) != set(_PROJECTION_CHECK_KEYS[self.evidence_kind]):
            raise ValueError("projection check keys do not match its evidence kind")
        if set(self.counts) != set(_PROJECTION_COUNT_KEYS[self.evidence_kind]):
            raise ValueError("projection count keys do not match its evidence kind")
        if any(value < 0 for value in self.counts.values()):
            raise ValueError("projection counts cannot be negative")
        if self.evidence_kind != "workers" and (
            self.observed_workers or self.observed_skill_assignments
        ):
            raise ValueError("only the workers projection can contain worker facts")
        if self.evidence_kind != "workflow" and any(
            self.workflow_status_counts.model_dump(by_alias=True).values()
        ):
            raise ValueError("only the workflow projection can contain status counts")
        return self


class HostedAgentTeamsReceipt(_StrictModel):
    schema_version: Literal["visiondata-gate.agentteams-hosted-receipt.v2"] = (
        "visiondata-gate.agentteams-hosted-receipt.v2"
    )
    observed_at: str
    operation: Literal["probe", "submit_project"]
    status: Literal["PASS", "PARTIAL", "FAIL"]
    operation_status: Literal[
        "CONFIGURED_NOT_CONNECTED",
        "CONTROLLER_CONNECTED",
        "CONTROL_PLANE_READY",
        "PROJECT_REGISTERED",
        "LEADER_INGRESS_SENT",
        "REMOTE_EXECUTION_OBSERVED",
    ]
    provider_repository: Literal["https://github.com/agentscope-ai/AgentTeams"] = (
        HOSTED_AGENTTEAMS_REPOSITORY
    )
    provider_version: Literal["v1.2.3"] = HOSTED_AGENTTEAMS_VERSION
    provider_commit: Literal["223ddc2b8073e4c8b93bcbb15e1d717f196c04d9"] = (
        HOSTED_AGENTTEAMS_COMMIT
    )
    controller_reported_version: None = None
    mode: AgentTeamsTransportMode
    team_name: str
    expected_workers: list[str]
    observed_workers: list[ObservedHostedWorker]
    expected_skill_assignments: dict[str, list[str]]
    observed_skill_assignments: dict[str, list[str]]
    checks: dict[str, bool]
    controller_connected: bool
    team_ready: bool
    workers_ready: bool
    skill_specs_verified: bool
    skill_files_verified: Literal[False] = False
    skill_runtime_verified: Literal[False] = False
    project_registered: bool = False
    leader_ingress_sent: bool = False
    workflow_observed: bool = False
    remote_task_execution_observed: bool = False
    matrix_assignment_verified: Literal[False] = False
    hosted_runtime_verified: Literal[False] = False
    project_id: str | None = None
    source_run_id: str | None = None
    goal_sha256: str | None = Field(default=None, pattern=r"^[0-9a-f]{64}$")
    approval_id: str | None = None
    wait_for_remote_execution: bool = False
    leader_ingress_event_id: None = None
    matrix_transaction_sha256: str | None = Field(
        default=None, pattern=r"^[0-9a-f]{64}$"
    )
    workflow_status_counts: WorkflowStatusCounts = Field(
        default_factory=WorkflowStatusCounts
    )
    evidence_projections: dict[str, EvidenceProjectionRef]
    transport_receipts: list[HTTPExchangeReceipt]
    reasons: list[str]
    boundary: str
    secrets_retained: Literal[False] = False
    evidence_mode: Literal["allowlisted_projection"] = "allowlisted_projection"
    exact_wire_retained: Literal[False] = False
    opaque_remote_values_retained: Literal[False] = False
    local_runtime_connection_status: Literal["mapped_not_connected"] = (
        "mapped_not_connected"
    )
    receipt_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")


class HostedReceiptValidation(_StrictModel):
    schema_version: Literal["visiondata-gate.agentteams-hosted-validation.v1"] = (
        "visiondata-gate.agentteams-hosted-validation.v1"
    )
    status: Literal["PASS", "FAIL"]
    checks: dict[str, bool]
    reasons: list[str]
    receipt_sha256: str
    connection_status: Literal["mapped_not_connected"] = "mapped_not_connected"


def _expected_skill_assignments() -> dict[str, list[str]]:
    rows = build_skill_distribution_plan()["worker_assignments"]
    assert isinstance(rows, list)
    return {
        str(row["worker"]): sorted(str(skill) for skill in row["skills"])
        for row in rows
        if isinstance(row, Mapping)
    }


def _expected_roles() -> dict[str, str]:
    return {
        name: "team_leader" if name == "visiondata-release-lead" else "worker"
        for name in _expected_skill_assignments()
    }


def _safe_project_id(submission: HostedProjectSubmission, team_name: str) -> str:
    if submission.project_id:
        return submission.project_id
    digest = hashlib.sha256(
        canonical_json_bytes(
            {
                "source_run_id": submission.source_run_id,
                "team_name": team_name,
                "title": submission.title,
            }
        )
    ).hexdigest()
    return f"vdg-{digest[:24]}"


def _matrix_transaction_id(
    *,
    project_id: str,
    source_run_id: str,
    goal_sha256: str,
    approval_id: str,
) -> str:
    """Derive the idempotent Matrix transaction used by producer and verifier."""

    digest = sha256_bytes(
        canonical_json_bytes(
            {
                "project_id": project_id,
                "source_run_id": source_run_id,
                "goal_sha256": goal_sha256,
                "approval_id": approval_id,
            }
        )
    )
    return f"vdg-{digest[:40]}"


def _workflow_status_proves_execution(status: str) -> bool:
    """Return true only for states that necessarily imply task execution.

    ``pending`` is queued, ``delegated`` is assignment-only, and ``blocked``
    proves that progress cannot currently continue. ``revision`` is also not
    execution evidence: it can be a requested state transition without a new
    work attempt. Only active or completed work crosses this evidence boundary.
    """

    return status.strip().casefold() in _REMOTE_EXECUTION_STATES


def _http_status(error: HTTPTransportError) -> int | None:
    if not error.receipt.attempts:
        return None
    return error.receipt.attempts[-1].http_status


def _validate_external_response(
    model_type: type[_ExternalModel],
    payload: Mapping[str, Any],
    *,
    label: str,
) -> _ExternalModel:
    try:
        return model_type.model_validate(payload)
    except (ValidationError, ValueError, TypeError):
        raise RuntimeError(f"{label} response schema rejected") from None


@dataclass
class _ProbeState:
    version: ControllerVersion | None = None
    team: ControllerTeam | None = None
    workers: ControllerWorkerList | None = None
    raw_results: dict[str, HTTPJSONResult] = field(default_factory=dict)
    transport_receipts: list[HTTPExchangeReceipt] = field(default_factory=list)
    reasons: list[str] = field(default_factory=list)


def _assess_control_plane(
    version: ControllerVersion | None,
    team: ControllerTeam | None,
    workers: ControllerWorkerList | None,
    *,
    team_name: str,
) -> tuple[dict[str, bool], list[ObservedHostedWorker], dict[str, list[str]]]:
    expected_assignments = _expected_skill_assignments()
    expected_roles = _expected_roles()
    expected_names = set(expected_assignments)
    selected: dict[str, ControllerWorker] = {}
    worker_names_unique = False
    if workers is not None:
        names = [worker.name for worker in workers.workers]
        worker_names_unique = len(names) == len(set(names))
        selected = {
            worker.name: worker
            for worker in workers.workers
            if worker.name in expected_names
        }
    observed = [
        ObservedHostedWorker(
            name=name,
            phase=("Running" if selected[name].phase == "Running" else "UNEXPECTED"),
            role=(
                expected_roles[name]
                if selected[name].role == expected_roles[name]
                else "UNEXPECTED"
            ),
            team=(team_name if selected[name].team == team_name else "UNEXPECTED"),
            skills=sorted(set(selected[name].skills) & set(expected_assignments[name])),
            matrix_user_id_present=selected[name].matrix_user_id.startswith("@"),
            room_id_present=selected[name].room_id.startswith("!"),
        )
        for name in sorted(selected)
    ]
    observed_assignments = {
        name: sorted(set(worker.skills) & set(expected_assignments[name]))
        for name, worker in sorted(selected.items())
    }
    member_map = (
        {member.name: member.role for member in team.worker_members}
        if team is not None
        else {}
    )
    checks = {
        "controller_version_endpoint_observed": version is not None,
        "controller_team_observed": team is not None,
        "controller_workers_observed": workers is not None,
        "team_name_matches": team is not None and team.name == team_name,
        "team_phase_active": team is not None and team.phase == "Active",
        "team_members_match_expected": team is not None
        and member_map == expected_roles,
        "team_leader_matches_expected": team is not None
        and team.leader_name == "visiondata-release-lead",
        "team_room_observed": team is not None and team.team_room_id.startswith("!"),
        "leader_dm_room_observed": team is not None
        and team.leader_dm_room_id.startswith("!"),
        "leader_ready": team is not None and team.leader_ready,
        "all_team_workers_ready": team is not None
        and team.total_workers == len(expected_names)
        and team.ready_workers == team.total_workers,
        "worker_names_unique": worker_names_unique,
        "expected_workers_observed": set(selected) == expected_names,
        "workers_phase_running": bool(selected)
        and all(worker.phase == "Running" for worker in selected.values()),
        "workers_team_matches": bool(selected)
        and all(worker.team == team_name for worker in selected.values()),
        "workers_roles_match": bool(selected)
        and all(
            worker.role == expected_roles[name] for name, worker in selected.items()
        ),
        "workers_matrix_identities_observed": bool(selected)
        and all(
            worker.matrix_user_id.startswith("@") and worker.room_id.startswith("!")
            for worker in selected.values()
        ),
        "worker_skill_specs_cover_expected": set(selected) == expected_names
        and all(
            set(expected_assignments[name]) <= set(selected[name].skills)
            for name in expected_names
        ),
    }
    return checks, observed, observed_assignments


def _workers_ready(checks: Mapping[str, bool]) -> bool:
    keys = (
        "worker_names_unique",
        "expected_workers_observed",
        "workers_phase_running",
        "workers_team_matches",
        "workers_roles_match",
        "workers_matrix_identities_observed",
    )
    return all(checks.get(key, False) for key in keys)


def _team_ready(checks: Mapping[str, bool]) -> bool:
    keys = (
        "team_name_matches",
        "team_phase_active",
        "team_members_match_expected",
        "team_leader_matches_expected",
        "team_room_observed",
        "leader_dm_room_observed",
        "leader_ready",
        "all_team_workers_ready",
    )
    return all(checks.get(key, False) for key in keys) and _workers_ready(checks)


def _sign_receipt(payload: Mapping[str, Any]) -> HostedAgentTeamsReceipt:
    unsigned = dict(payload)
    unsigned.pop("receipt_sha256", None)
    unsigned["receipt_sha256"] = "0" * 64
    normalized = HostedAgentTeamsReceipt.model_validate(unsigned)
    normalized_payload = normalized.model_dump(mode="json")
    normalized_payload.pop("receipt_sha256")
    return normalized.model_copy(
        update={
            "receipt_sha256": sha256_bytes(canonical_json_bytes(normalized_payload))
        }
    )


def _receipt_digest(receipt: HostedAgentTeamsReceipt) -> str:
    payload = receipt.model_dump(mode="json")
    payload.pop("receipt_sha256")
    return sha256_bytes(canonical_json_bytes(payload))


def _write_new(path: Path, data: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("xb") as handle:
        handle.write(data)


def _prepare_output_dir(output_dir: Path) -> None:
    output_dir.mkdir(parents=True, exist_ok=True)
    reserved = [
        output_dir / "agentteams_hosted_receipt.json",
        output_dir / "agentteams_hosted_validation.json",
        *(
            output_dir / "agentteams_hosted_projection" / name
            for name in _PROJECTION_FILENAMES.values()
        ),
    ]
    conflicts = [path for path in reserved if path.exists()]
    if conflicts:
        raise FileExistsError(
            "Hosted evidence output already contains reserved artifacts"
        )


def _sanitized_exchange_receipt(
    receipt: HTTPExchangeReceipt,
    *,
    evidence_kind: str,
) -> HTTPExchangeReceipt:
    if evidence_kind not in _PROJECTION_FILENAMES:
        raise ValueError("unknown Hosted transport evidence kind")
    return receipt.model_copy(update={"endpoint_id": f"agentteams://{evidence_kind}"})


def _workflow_counts(workflow: ControllerWorkflow | None) -> WorkflowStatusCounts:
    counts = {key: 0 for key in _WORKFLOW_STATUS_KEYS}
    if workflow is not None:
        for node in workflow.nodes:
            normalized = node.status.strip().casefold()
            key = normalized if normalized in counts else "other"
            counts[key] += 1
    return WorkflowStatusCounts(
        pending=counts["pending"],
        delegated=counts["delegated"],
        blocked=counts["blocked"],
        revision=counts["revision"],
        in_progress=counts["in-progress"],
        completed=counts["completed"],
        other=counts["other"],
    )


def _projection_for_result(
    label: str,
    result: HTTPJSONResult,
    *,
    state: _ProbeState,
    team_name: str,
    project: ControllerProject | None,
    workflow: ControllerWorkflow | None,
    matrix_response: MatrixSendResponse | None,
    submission: HostedProjectSubmission | None,
    project_id: str | None,
) -> HostedEvidenceProjection:
    response_sha256 = sha256_bytes(result.raw_bytes)
    if result.receipt.response_sha256 is None or not hmac.compare_digest(
        response_sha256, result.receipt.response_sha256
    ):
        raise RuntimeError("Hosted response bytes drifted from their transport receipt")
    assessed, observed_workers, observed_assignments = _assess_control_plane(
        state.version,
        state.team,
        state.workers,
        team_name=team_name,
    )
    checks: dict[str, bool]
    counts: dict[str, int]
    projected_workers: list[ObservedHostedWorker] = []
    projected_assignments: dict[str, list[str]] = {}
    status_counts = WorkflowStatusCounts()
    if label == "version":
        checks = {
            "controller_version_endpoint_observed": state.version is not None,
        }
        counts = {}
    elif label == "team":
        checks = {key: assessed[key] for key in _PROJECTION_CHECK_KEYS[label]}
        counts = {
            "member_count": len(state.team.worker_members) if state.team else 0,
            "ready_worker_count": state.team.ready_workers if state.team else 0,
            "total_worker_count": state.team.total_workers if state.team else 0,
        }
    elif label == "workers":
        checks = {key: assessed[key] for key in _PROJECTION_CHECK_KEYS[label]}
        counts = {
            "reported_total": state.workers.total if state.workers else 0,
            "worker_count": len(state.workers.workers) if state.workers else 0,
        }
        projected_workers = observed_workers
        projected_assignments = observed_assignments
    elif label == "project":
        registered = bool(
            project is not None
            and project.project_id == project_id
            and project.team_id == team_name
            and (submission is None or project.title == submission.title)
        )
        checks = {"project_registration_observed": registered}
        counts = {}
    elif label == "matrix_ingress":
        checks = {
            "leader_matrix_ingress_observed": bool(
                matrix_response is not None and matrix_response.event_id.startswith("$")
            )
        }
        counts = {}
    elif label == "workflow":
        workflow_observed = bool(
            workflow is not None and workflow.project_id == project_id
        )
        registered = bool(
            workflow is not None
            and workflow.project_id == project_id
            and workflow.team_id == team_name
            and (submission is None or workflow.title == submission.title)
        )
        remote_execution = bool(
            workflow is not None
            and any(
                _workflow_status_proves_execution(node.status)
                for node in workflow.nodes
            )
        )
        checks = {
            "workflow_project_observed": workflow_observed,
            "project_registration_observed": registered,
            "remote_task_execution_observed": remote_execution,
        }
        counts = {"node_count": len(workflow.nodes) if workflow else 0}
        status_counts = _workflow_counts(workflow)
    else:
        raise ValueError("unknown Hosted projection label")
    return HostedEvidenceProjection(
        evidence_kind=label,
        source_response_sha256=response_sha256,
        source_response_bytes=len(result.raw_bytes),
        checks=checks,
        counts=counts,
        observed_workers=projected_workers,
        observed_skill_assignments=projected_assignments,
        workflow_status_counts=status_counts,
    )


def _write_evidence_projections(
    output_dir: Path,
    results: Mapping[str, HTTPJSONResult],
    *,
    state: _ProbeState,
    team_name: str,
    project: ControllerProject | None = None,
    workflow: ControllerWorkflow | None = None,
    matrix_response: MatrixSendResponse | None = None,
    submission: HostedProjectSubmission | None = None,
    project_id: str | None = None,
) -> dict[str, EvidenceProjectionRef]:
    selected = {
        label: result
        for label, result in results.items()
        if label in _PROJECTION_FILENAMES
    }
    projections = {
        label: _projection_for_result(
            label,
            result,
            state=state,
            team_name=team_name,
            project=project,
            workflow=workflow,
            matrix_response=matrix_response,
            submission=submission,
            project_id=project_id,
        )
        for label, result in selected.items()
    }
    references: dict[str, EvidenceProjectionRef] = {}
    for label, projection in projections.items():
        payload = canonical_json_bytes(projection.model_dump(mode="json"))
        relative = Path("agentteams_hosted_projection") / _PROJECTION_FILENAMES[label]
        destination = output_dir / relative
        _write_new(destination, payload)
        references[label] = EvidenceProjectionRef(
            path=relative.as_posix(),
            projection_sha256=sha256_bytes(payload),
            projection_bytes=len(payload),
            source_response_sha256=projection.source_response_sha256,
            source_response_bytes=projection.source_response_bytes,
            evidence_kind=projection.evidence_kind,
        )
    return references


class HostedAgentTeamsTransport:
    """Controller + Matrix transport with explicit read/write authority."""

    def __init__(
        self,
        config: HostedAgentTeamsConfig,
        *,
        controller_token: str,
        matrix_token: str | None = None,
        sleeper: Callable[[float], None] = time.sleep,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        if config.mode is AgentTeamsTransportMode.OFF:
            raise ValueError("off mode does not construct a Hosted transport")
        if not controller_token.strip():
            raise PermissionError("Hosted Controller requires an authorization token")
        self.config = config
        self._controller_token = controller_token.strip()
        self._matrix_token = matrix_token.strip() if matrix_token else None
        self._sleep = sleeper
        self._clock = clock
        read_policy = HTTPClientPolicy(
            allowed_hosts=config.controller_allowed_hosts,
            allow_local=config.controller_allow_local,
            timeout_seconds=config.timeout_seconds,
            max_retries=config.read_max_retries,
            max_response_bytes=config.max_response_bytes,
        )
        write_policy = read_policy.model_copy(update={"max_retries": 0})
        self._controller_read = ResilientJSONClient(
            read_policy, sleeper=sleeper, clock=clock
        )
        self._controller_write = ResilientJSONClient(
            write_policy, sleeper=sleeper, clock=clock
        )
        self._matrix_write: ResilientJSONClient | None = None
        if config.matrix_base_url:
            self._matrix_write = ResilientJSONClient(
                HTTPClientPolicy(
                    allowed_hosts=config.matrix_allowed_hosts,
                    allow_local=config.matrix_allow_local,
                    timeout_seconds=config.timeout_seconds,
                    # Matrix PUT carries a stable transaction id and is safe to retry.
                    max_retries=config.read_max_retries,
                    max_response_bytes=config.max_response_bytes,
                ),
                sleeper=sleeper,
                clock=clock,
            )

    def _controller_endpoint(self, suffix: str) -> str:
        base = self.config.controller_base_url
        parsed = urllib.parse.urlsplit(base)
        root_path = parsed.path.rstrip("/")
        if root_path.endswith("/api/v1"):
            path = f"{root_path}/{suffix.lstrip('/')}"
        else:
            path = f"{root_path}/api/v1/{suffix.lstrip('/')}"
        return urllib.parse.urlunsplit((parsed.scheme, parsed.netloc, path, "", ""))

    def _matrix_endpoint(self, room_id: str, txn_id: str) -> str:
        if not self.config.matrix_base_url:
            raise PermissionError("Matrix base URL is not configured")
        parsed = urllib.parse.urlsplit(self.config.matrix_base_url)
        root_path = parsed.path.rstrip("/")
        prefix = (
            root_path
            if root_path.endswith("/_matrix/client/v3")
            else f"{root_path}/_matrix/client/v3"
        )
        room = urllib.parse.quote(room_id, safe="")
        txn = urllib.parse.quote(txn_id, safe="")
        path = f"{prefix}/rooms/{room}/send/m.room.message/{txn}"
        return urllib.parse.urlunsplit((parsed.scheme, parsed.netloc, path, "", ""))

    def _controller_headers(self) -> dict[str, str]:
        return {"Authorization": f"Bearer {self._controller_token}"}

    def _matrix_headers(self) -> dict[str, str]:
        if not self._matrix_token:
            raise PermissionError("Matrix ingress requires a separate access token")
        return {"Authorization": f"Bearer {self._matrix_token}"}

    def _read_controller(self, suffix: str) -> HTTPJSONResult:
        return self._controller_read.request_json(
            self._controller_endpoint(suffix),
            method="GET",
            headers=self._controller_headers(),
        )

    def _post_controller(
        self, suffix: str, payload: Mapping[str, Any]
    ) -> HTTPJSONResult:
        return self._controller_write.request_json(
            self._controller_endpoint(suffix),
            method="POST",
            payload=payload,
            headers=self._controller_headers(),
        )

    def _authorize_write(self, approval_id: str) -> str:
        if self.config.mode is not AgentTeamsTransportMode.GATED:
            raise PermissionError("Hosted writes require mode=gated")
        if not self.config.write_enabled:
            raise PermissionError("Hosted writes are disabled by configuration")
        normalized = approval_id.strip()
        if not _SAFE_ID.fullmatch(normalized):
            raise PermissionError("a named, plain-token approval_id is required")
        return normalized

    def probe(self) -> _ProbeState:
        state = _ProbeState()
        calls: tuple[tuple[str, str, type[_ExternalModel]], ...] = (
            ("version", "version", ControllerVersion),
            (
                "team",
                f"teams/{urllib.parse.quote(self.config.team_name, safe='')}",
                ControllerTeam,
            ),
            ("workers", "workers", ControllerWorkerList),
        )
        for label, suffix, model_type in calls:
            try:
                result = self._read_controller(suffix)
                state.transport_receipts.append(
                    _sanitized_exchange_receipt(
                        result.receipt,
                        evidence_kind=label,
                    )
                )
                model = model_type.model_validate(result.payload)
                state.raw_results[label] = result
            except HTTPTransportError as error:
                state.transport_receipts.append(
                    _sanitized_exchange_receipt(
                        error.receipt,
                        evidence_kind=label,
                    )
                )
                state.reasons.append(f"{label}: controller transport failed")
                break
            except (ValidationError, ValueError, TypeError):
                state.reasons.append(f"{label}: controller response schema rejected")
                break
            except (ConnectionError, PermissionError) as error:
                state.reasons.append(f"{label}: {type(error).__name__}")
                break
            if label == "version":
                state.version = ControllerVersion.model_validate(model)
            elif label == "team":
                state.team = ControllerTeam.model_validate(model)
            else:
                state.workers = ControllerWorkerList.model_validate(model)
        return state

    def _build_receipt(
        self,
        state: _ProbeState,
        *,
        operation: Literal["probe", "submit_project"],
        evidence_projections: dict[str, EvidenceProjectionRef],
        project: ControllerProject | None = None,
        workflow: ControllerWorkflow | None = None,
        matrix_response: MatrixSendResponse | None = None,
        submission: HostedProjectSubmission | None = None,
        project_id: str | None = None,
        approval_id: str | None = None,
    ) -> HostedAgentTeamsReceipt:
        checks, observed_workers, observed_assignments = _assess_control_plane(
            state.version,
            state.team,
            state.workers,
            team_name=self.config.team_name,
        )
        controller_connected = all(
            checks[key]
            for key in (
                "controller_version_endpoint_observed",
                "controller_team_observed",
                "controller_workers_observed",
            )
        )
        workers_ready = _workers_ready(checks)
        team_ready = _team_ready(checks)
        skill_specs_verified = checks["worker_skill_specs_cover_expected"]
        project_registered = bool(
            project is not None
            and project.project_id == project_id
            and project.team_id == self.config.team_name
            and (submission is None or project.title == submission.title)
        ) or bool(
            workflow is not None
            and workflow.project_id == project_id
            and workflow.team_id == self.config.team_name
            and (submission is None or workflow.title == submission.title)
        )
        leader_ingress_sent = bool(
            matrix_response is not None and matrix_response.event_id.startswith("$")
        )
        workflow_observed = bool(
            workflow is not None and workflow.project_id == project_id
        )
        workflow_status_counts = _workflow_counts(workflow)
        remote_execution = bool(
            workflow is not None
            and any(
                _workflow_status_proves_execution(node.status)
                for node in workflow.nodes
            )
        )
        checks.update(
            {
                "project_registration_observed": project_registered,
                "leader_matrix_ingress_observed": leader_ingress_sent,
                "workflow_project_observed": workflow_observed,
                "remote_task_execution_observed": remote_execution,
                # Controller workflow does not expose TeamHarness assignment eventId.
                "matrix_worker_assignment_event_verified": False,
            }
        )
        reasons = list(state.reasons)
        failed_control_checks = [
            key
            for key, value in checks.items()
            if not value
            and key
            not in {
                "project_registration_observed",
                "leader_matrix_ingress_observed",
                "workflow_project_observed",
                "remote_task_execution_observed",
                "matrix_worker_assignment_event_verified",
            }
        ]
        reasons.extend(failed_control_checks)
        if operation == "probe":
            status: Literal["PASS", "PARTIAL", "FAIL"] = (
                "PASS"
                if controller_connected and team_ready and skill_specs_verified
                else "FAIL"
            )
        else:
            if leader_ingress_sent and workflow_observed:
                status = "PASS"
            elif project_registered:
                status = "PARTIAL"
            else:
                status = "FAIL"
            if (
                submission is not None
                and submission.wait_for_remote_execution
                and not remote_execution
            ):
                status = "PARTIAL"
                reasons.append(
                    "No in-progress/completed workflow node was observed "
                    "before the bounded polling deadline."
                )

        if remote_execution:
            operation_status = "REMOTE_EXECUTION_OBSERVED"
        elif leader_ingress_sent:
            operation_status = "LEADER_INGRESS_SENT"
        elif project_registered:
            operation_status = "PROJECT_REGISTERED"
        elif controller_connected and team_ready and skill_specs_verified:
            operation_status = "CONTROL_PLANE_READY"
        elif controller_connected:
            operation_status = "CONTROLLER_CONNECTED"
        else:
            operation_status = "CONFIGURED_NOT_CONNECTED"

        expected_assignments = _expected_skill_assignments()
        return _sign_receipt(
            {
                "observed_at": datetime.now(timezone.utc)
                .isoformat()
                .replace("+00:00", "Z"),
                "operation": operation,
                "status": status,
                "operation_status": operation_status,
                "controller_reported_version": None,
                "mode": self.config.mode,
                "team_name": self.config.team_name,
                "expected_workers": sorted(expected_assignments),
                "observed_workers": observed_workers,
                "expected_skill_assignments": expected_assignments,
                "observed_skill_assignments": observed_assignments,
                "checks": checks,
                "controller_connected": controller_connected,
                "team_ready": team_ready,
                "workers_ready": workers_ready,
                "skill_specs_verified": skill_specs_verified,
                "project_registered": project_registered,
                "leader_ingress_sent": leader_ingress_sent,
                "workflow_observed": workflow_observed,
                "remote_task_execution_observed": remote_execution,
                "project_id": project_id,
                "source_run_id": submission.source_run_id if submission else None,
                "goal_sha256": (
                    sha256_bytes(submission.goal.encode("utf-8"))
                    if submission
                    else None
                ),
                "approval_id": approval_id,
                "wait_for_remote_execution": (
                    submission.wait_for_remote_execution if submission else False
                ),
                "leader_ingress_event_id": None,
                "matrix_transaction_sha256": (
                    sha256_bytes(
                        _matrix_transaction_id(
                            project_id=project_id,
                            source_run_id=submission.source_run_id,
                            goal_sha256=sha256_bytes(submission.goal.encode("utf-8")),
                            approval_id=approval_id,
                        ).encode("utf-8")
                    )
                    if submission is not None
                    and project_id is not None
                    and approval_id is not None
                    else None
                ),
                "workflow_status_counts": workflow_status_counts,
                "evidence_projections": evidence_projections,
                "transport_receipts": state.transport_receipts,
                "reasons": list(dict.fromkeys(reasons)),
                "boundary": (
                    "Controller project registration is not Worker delegation. "
                    "Pending, delegated, blocked, and revision workflow states do not prove "
                    "execution; only in-progress or completed does. Leader ingress plus "
                    "workflow nodes can prove the hosted request was observed, but this v2 "
                    "receipt stores allowlisted semantic projections and wire SHA-256/length "
                    "commitments, never exact response bytes or opaque remote identifiers. "
                    "It cannot independently replay exact wire content and does not capture "
                    "TeamHarness' Worker assignment eventId, Skill files/runtime loading, "
                    "production authority, or customer acceptance. "
                    "The local runtime remains mapped_not_connected."
                ),
            }
        )

    def collect_runtime_evidence(self, output_dir: Path) -> HostedAgentTeamsReceipt:
        output = output_dir.resolve()
        _prepare_output_dir(output)
        state = self.probe()
        evidence_projections = _write_evidence_projections(
            output,
            state.raw_results,
            state=state,
            team_name=self.config.team_name,
        )
        receipt = self._build_receipt(
            state,
            operation="probe",
            evidence_projections=evidence_projections,
        )
        receipt_path = output / "agentteams_hosted_receipt.json"
        _write_new(receipt_path, canonical_json_bytes(receipt.model_dump(mode="json")))
        validation = verify_hosted_agentteams_receipt(receipt_path)
        _write_new(
            output / "agentteams_hosted_validation.json",
            canonical_json_bytes(validation.model_dump(mode="json")),
        )
        if validation.status != "PASS":
            raise RuntimeError(
                "Generated Hosted probe receipt failed offline validation: "
                + ", ".join(validation.reasons)
            )
        return receipt

    def submit_project(
        self,
        output_dir: Path,
        submission: HostedProjectSubmission,
        *,
        approval_id: str,
    ) -> HostedAgentTeamsReceipt:
        approval = self._authorize_write(approval_id)
        if self._matrix_write is None or not self._matrix_token:
            raise PermissionError(
                "submit_project requires an explicitly configured Matrix transport"
            )
        output = output_dir.resolve()
        _prepare_output_dir(output)
        state = self.probe()
        checks, _, _ = _assess_control_plane(
            state.version,
            state.team,
            state.workers,
            team_name=self.config.team_name,
        )
        if not (_team_ready(checks) and checks["worker_skill_specs_cover_expected"]):
            raise RuntimeError("Hosted control plane is not ready; write refused")
        assert state.team is not None
        assert state.workers is not None
        leader = next(
            (
                worker
                for worker in state.workers.workers
                if worker.name == state.team.leader_name
            ),
            None,
        )
        if leader is None or not leader.matrix_user_id.startswith("@"):
            raise RuntimeError("Team Leader Matrix identity is unavailable")
        project_id = _safe_project_id(submission, self.config.team_name)
        project: ControllerProject | None = None
        workflow: ControllerWorkflow | None = None

        # Read and write clients have separate circuit breakers: an expected
        # 404 preflight can never suppress the subsequent authorized POST.
        try:
            existing = self._read_controller(
                f"projects/{urllib.parse.quote(project_id, safe='')}/workflow"
            )
            state.transport_receipts.append(
                _sanitized_exchange_receipt(
                    existing.receipt,
                    evidence_kind="workflow",
                )
            )
            workflow = ControllerWorkflow.model_validate(
                _validate_external_response(
                    ControllerWorkflow,
                    existing.payload,
                    label="workflow",
                )
            )
            state.raw_results["workflow"] = existing
        except HTTPTransportError as error:
            state.transport_receipts.append(
                _sanitized_exchange_receipt(
                    error.receipt,
                    evidence_kind="workflow",
                )
            )
            if _http_status(error) != 404:
                raise
        if workflow is not None:
            if (
                workflow.team_id != self.config.team_name
                or workflow.title != submission.title
            ):
                raise RuntimeError("existing project identity does not match request")
        else:
            create_payload: dict[str, Any] = {
                "title": submission.title,
                "source": "visiondata-gate",
                "team_id": self.config.team_name,
                "project_id": project_id,
                "source_room_id": state.team.leader_dm_room_id,
            }
            if submission.requester:
                create_payload["requester"] = submission.requester
            try:
                created = self._post_controller("projects", create_payload)
                state.transport_receipts.append(
                    _sanitized_exchange_receipt(
                        created.receipt,
                        evidence_kind="project",
                    )
                )
                project = ControllerProject.model_validate(
                    _validate_external_response(
                        ControllerProject,
                        created.payload,
                        label="project",
                    )
                )
                state.raw_results["project"] = created
            except HTTPTransportError as error:
                state.transport_receipts.append(
                    _sanitized_exchange_receipt(
                        error.receipt,
                        evidence_kind="project",
                    )
                )
                if _http_status(error) != 409:
                    raise
                existing = self._read_controller(
                    f"projects/{urllib.parse.quote(project_id, safe='')}/workflow"
                )
                state.transport_receipts.append(
                    _sanitized_exchange_receipt(
                        existing.receipt,
                        evidence_kind="workflow",
                    )
                )
                workflow = ControllerWorkflow.model_validate(
                    _validate_external_response(
                        ControllerWorkflow,
                        existing.payload,
                        label="workflow",
                    )
                )
                state.raw_results["workflow"] = existing
                if (
                    workflow.team_id != self.config.team_name
                    or workflow.title != submission.title
                ):
                    raise RuntimeError(
                        "conflicting project cannot be reused idempotently"
                    )

        goal_sha = sha256_bytes(submission.goal.encode("utf-8"))
        transaction_id = _matrix_transaction_id(
            project_id=project_id,
            source_run_id=submission.source_run_id,
            goal_sha256=goal_sha,
            approval_id=approval,
        )
        matrix_payload = {
            "msgtype": "m.text",
            "body": (
                f"{leader.matrix_user_id} VisionData Gate hosted request\n"
                f"Project: {project_id}\n"
                f"Goal: {submission.goal}\n"
                "Use TeamHarness projectflow/taskflow for planning and delegation; "
                "do not treat Controller project registration as task assignment."
            ),
            "m.mentions": {"user_ids": [leader.matrix_user_id]},
            "org.visiondata_gate.request": {
                "schema_version": "visiondata-gate.agentteams-ingress.v1",
                "project_id": project_id,
                "source_run_id": submission.source_run_id,
                "goal_sha256": goal_sha,
                "approval_id": approval,
            },
        }
        matrix_result = self._matrix_write.request_json(
            self._matrix_endpoint(state.team.leader_dm_room_id, transaction_id),
            method="PUT",
            payload=matrix_payload,
            headers=self._matrix_headers(),
        )
        state.transport_receipts.append(
            _sanitized_exchange_receipt(
                matrix_result.receipt,
                evidence_kind="matrix_ingress",
            )
        )
        matrix_response = MatrixSendResponse.model_validate(
            _validate_external_response(
                MatrixSendResponse,
                matrix_result.payload,
                label="matrix ingress",
            )
        )
        state.raw_results["matrix_ingress"] = matrix_result

        deadline = self._clock() + self.config.poll_timeout_seconds
        while True:
            workflow_result = self._read_controller(
                f"projects/{urllib.parse.quote(project_id, safe='')}/workflow"
            )
            state.transport_receipts.append(
                _sanitized_exchange_receipt(
                    workflow_result.receipt,
                    evidence_kind="workflow",
                )
            )
            candidate = ControllerWorkflow.model_validate(
                _validate_external_response(
                    ControllerWorkflow,
                    workflow_result.payload,
                    label="workflow",
                )
            )
            if (
                candidate.project_id != project_id
                or candidate.team_id != self.config.team_name
            ):
                raise RuntimeError("workflow identity does not match submitted project")
            workflow = candidate
            state.raw_results["workflow"] = workflow_result
            execution_observed = any(
                _workflow_status_proves_execution(node.status)
                for node in workflow.nodes
            )
            if not submission.wait_for_remote_execution or execution_observed:
                break
            remaining = deadline - self._clock()
            if remaining <= 0:
                break
            self._sleep(min(self.config.poll_interval_seconds, remaining))

        evidence_projections = _write_evidence_projections(
            output,
            state.raw_results,
            state=state,
            team_name=self.config.team_name,
            project=project,
            workflow=workflow,
            matrix_response=matrix_response,
            submission=submission,
            project_id=project_id,
        )
        receipt = self._build_receipt(
            state,
            operation="submit_project",
            evidence_projections=evidence_projections,
            project=project,
            workflow=workflow,
            matrix_response=matrix_response,
            submission=submission,
            project_id=project_id,
            approval_id=approval,
        )
        receipt_path = output / "agentteams_hosted_receipt.json"
        _write_new(receipt_path, canonical_json_bytes(receipt.model_dump(mode="json")))
        validation = verify_hosted_agentteams_receipt(receipt_path)
        _write_new(
            output / "agentteams_hosted_validation.json",
            canonical_json_bytes(validation.model_dump(mode="json")),
        )
        if validation.status != "PASS":
            raise RuntimeError(
                "Generated Hosted submission receipt failed offline validation: "
                + ", ".join(validation.reasons)
            )
        return receipt


def _parse_evidence_projections(
    receipt: HostedAgentTeamsReceipt,
    receipt_path: Path,
) -> tuple[dict[str, bool], dict[str, HostedEvidenceProjection]]:
    base = receipt_path.resolve().parent
    checks: dict[str, bool] = {}
    projections: dict[str, HostedEvidenceProjection] = {}
    resolved_paths: set[Path] = set()
    for label, reference in receipt.evidence_projections.items():
        try:
            if "\x00" in reference.path:
                raise ValueError("projection path contains a NUL byte")
            lexical = base / reference.path
            reparse = bool(
                lexical.is_symlink()
                or getattr(os.path, "isjunction", lambda _path: False)(lexical)
            )
            candidate = lexical.resolve()
            try:
                candidate.relative_to(base)
                contained = not reparse
            except ValueError:
                contained = False
        except (OSError, RuntimeError, ValueError):
            checks[f"projection_{label}_path_contained"] = False
            checks[f"projection_{label}_path_unique"] = False
            checks[f"projection_{label}_present"] = False
            checks[f"projection_{label}_hash_matches"] = False
            checks[f"projection_{label}_size_matches"] = False
            checks[f"projection_{label}_schema_valid"] = False
            continue
        checks[f"projection_{label}_path_contained"] = contained
        checks[f"projection_{label}_path_unique"] = candidate not in resolved_paths
        resolved_paths.add(candidate)
        try:
            present = contained and candidate.is_file()
        except OSError:
            present = False
        checks[f"projection_{label}_present"] = present
        raw: bytes | None = None
        if present:
            try:
                raw = candidate.read_bytes()
            except OSError:
                raw = None
        checks[f"projection_{label}_hash_matches"] = bool(
            raw is not None
            and hmac.compare_digest(sha256_bytes(raw), reference.projection_sha256)
        )
        checks[f"projection_{label}_size_matches"] = bool(
            raw is not None and len(raw) == reference.projection_bytes
        )
        parsed: HostedEvidenceProjection | None = None
        if raw is not None:
            try:
                parsed = HostedEvidenceProjection.model_validate_json(raw)
            except (ValidationError, ValueError):
                parsed = None
        checks[f"projection_{label}_schema_valid"] = parsed is not None
        checks[f"projection_{label}_reference_matches"] = bool(
            parsed is not None
            and parsed.evidence_kind == label
            and reference.evidence_kind == label
            and hmac.compare_digest(
                parsed.source_response_sha256,
                reference.source_response_sha256,
            )
            and parsed.source_response_bytes == reference.source_response_bytes
        )
        if parsed is not None:
            projections[label] = parsed
    return checks, projections


def _failed_hosted_validation(
    *, raw_receipt: bytes, check: str
) -> HostedReceiptValidation:
    return HostedReceiptValidation(
        status="FAIL",
        checks={check: False},
        reasons=[check],
        receipt_sha256=sha256_bytes(raw_receipt),
    )


def _endpoint_has_semantic_path(
    endpoint_id: str,
    *,
    marker: str,
    expected_path: str,
) -> bool:
    try:
        parsed = urllib.parse.urlsplit(endpoint_id)
    except ValueError:
        return False
    if (
        parsed.scheme not in {"http", "https"}
        or not parsed.netloc
        or parsed.query
        or parsed.fragment
    ):
        return False
    marker_index = parsed.path.rfind(marker)
    return marker_index >= 0 and parsed.path[marker_index:] == expected_path


def verify_hosted_agentteams_receipt(
    receipt_path: Path,
) -> HostedReceiptValidation:
    try:
        path = receipt_path.resolve()
        raw_receipt = path.read_bytes()
    except (OSError, RuntimeError, ValueError):
        return _failed_hosted_validation(raw_receipt=b"", check="receipt_readable")
    try:
        untyped = json.loads(raw_receipt.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError):
        return _failed_hosted_validation(
            raw_receipt=raw_receipt,
            check="receipt_schema_valid",
        )
    if (
        isinstance(untyped, dict)
        and untyped.get("schema_version")
        == "visiondata-gate.agentteams-hosted-receipt.v1"
    ):
        return _failed_hosted_validation(
            raw_receipt=raw_receipt,
            check="legacy_exact_wire_security_unverifiable",
        )
    try:
        receipt = HostedAgentTeamsReceipt.model_validate(untyped)
    except (ValidationError, ValueError):
        return _failed_hosted_validation(
            raw_receipt=raw_receipt,
            check="receipt_schema_valid",
        )

    checks: dict[str, bool] = {
        "receipt_sha256_matches": hmac.compare_digest(
            _receipt_digest(receipt), receipt.receipt_sha256
        ),
        "provider_version_pinned": receipt.provider_version
        == HOSTED_AGENTTEAMS_VERSION,
        "provider_commit_pinned": receipt.provider_commit == HOSTED_AGENTTEAMS_COMMIT,
        "local_runtime_boundary_preserved": receipt.local_runtime_connection_status
        == "mapped_not_connected",
        "allowlisted_projection_mode": receipt.evidence_mode
        == "allowlisted_projection",
        "exact_wire_not_retained": receipt.exact_wire_retained is False,
        "opaque_remote_values_not_retained": (
            receipt.opaque_remote_values_retained is False
            and receipt.controller_reported_version is None
            and receipt.leader_ingress_event_id is None
        ),
        "secrets_not_retained": receipt.secrets_retained is False,
        "transport_receipt_secret_flags_clear": all(
            exchange.secrets_retained is False
            for exchange in receipt.transport_receipts
        ),
        "transport_endpoints_sanitized": all(
            exchange.endpoint_id
            in {f"agentteams://{label}" for label in _PROJECTION_FILENAMES}
            for exchange in receipt.transport_receipts
        ),
        "worker_assignment_not_overclaimed": receipt.matrix_assignment_verified
        is False,
        "hosted_runtime_not_overclaimed": receipt.hosted_runtime_verified is False,
    }
    projection_checks, projections = _parse_evidence_projections(receipt, path)
    checks.update(projection_checks)
    known_labels = set(_PROJECTION_FILENAMES)
    checks["projection_labels_known"] = (
        set(receipt.evidence_projections) <= known_labels
    )
    checks["projection_labels_match_payloads"] = set(
        receipt.evidence_projections
    ) == set(projections)

    expected_methods = {
        "version": "GET",
        "team": "GET",
        "workers": "GET",
        "project": "POST",
        "matrix_ingress": "PUT",
        "workflow": "GET",
    }
    successful_statuses = {"SUCCESS", "RECOVERED"}
    bound_exchanges: dict[str, list[HTTPExchangeReceipt]] = {}
    for label, reference in receipt.evidence_projections.items():
        matches = [
            exchange
            for exchange in receipt.transport_receipts
            if exchange.method == expected_methods.get(label)
            and exchange.endpoint_id == f"agentteams://{label}"
            and exchange.status in successful_statuses
            and exchange.response_sha256 == reference.source_response_sha256
        ]
        bound_exchanges[label] = matches
        checks[f"projection_{label}_bound_to_transport_receipt"] = bool(matches)

    successful_matrix_puts = [
        exchange
        for exchange in receipt.transport_receipts
        if exchange.method == "PUT" and exchange.status in successful_statuses
    ]
    if "matrix_ingress" in receipt.evidence_projections:
        checks["matrix_ingress_unique_successful_put"] = bool(
            len(successful_matrix_puts) == 1
            and len(bound_exchanges.get("matrix_ingress", [])) == 1
            and successful_matrix_puts[0] == bound_exchanges["matrix_ingress"][0]
        )
    else:
        checks["matrix_ingress_unique_successful_put"] = not successful_matrix_puts

    assessed: dict[str, bool] = {}
    for label in ("version", "team", "workers"):
        projection = projections.get(label)
        if projection is not None:
            assessed.update(projection.checks)
    control_keys = set().union(
        _PROJECTION_CHECK_KEYS["version"],
        _PROJECTION_CHECK_KEYS["team"],
        _PROJECTION_CHECK_KEYS["workers"],
    )
    for key in control_keys:
        assessed.setdefault(key, False)

    worker_projection = projections.get("workers")
    projected_workers = (
        worker_projection.observed_workers if worker_projection is not None else []
    )
    projected_assignments = (
        worker_projection.observed_skill_assignments
        if worker_projection is not None
        else {}
    )
    expected_assignments = _expected_skill_assignments()
    expected_roles = _expected_roles()
    checks["projected_worker_values_allowlisted"] = all(
        worker.name in expected_assignments
        and worker.phase in {"Running", "UNEXPECTED"}
        and worker.role in {expected_roles[worker.name], "UNEXPECTED"}
        and worker.team in {receipt.team_name, "UNEXPECTED"}
        and set(worker.skills) <= set(expected_assignments[worker.name])
        for worker in projected_workers
    ) and all(
        name in expected_assignments and set(skills) <= set(expected_assignments[name])
        for name, skills in projected_assignments.items()
    )
    checks["observed_workers_match_projection"] = (
        receipt.observed_workers == projected_workers
    )
    checks["observed_skill_assignments_match_projection"] = (
        receipt.observed_skill_assignments == projected_assignments
    )
    checks["expected_contract_matches_local"] = (
        receipt.expected_skill_assignments == expected_assignments
        and receipt.expected_workers == sorted(expected_assignments)
    )
    checks["control_plane_checks_match_projections"] = all(
        receipt.checks.get(key) == assessed[key] for key in control_keys
    )

    project_projection = projections.get("project")
    workflow_projection = projections.get("workflow")
    matrix_projection = projections.get("matrix_ingress")
    derived_project_registered = bool(
        (
            project_projection is not None
            and project_projection.checks["project_registration_observed"]
        )
        or (
            workflow_projection is not None
            and workflow_projection.checks["project_registration_observed"]
        )
    )
    derived_ingress = bool(
        matrix_projection is not None
        and matrix_projection.checks["leader_matrix_ingress_observed"]
    )
    derived_workflow = bool(
        workflow_projection is not None
        and workflow_projection.checks["workflow_project_observed"]
    )
    derived_execution = bool(
        workflow_projection is not None
        and workflow_projection.checks["remote_task_execution_observed"]
    )
    derived_status_counts = (
        workflow_projection.workflow_status_counts
        if workflow_projection is not None
        else WorkflowStatusCounts()
    )
    checks["workflow_status_count_total_matches"] = bool(
        workflow_projection is None
        or sum(derived_status_counts.model_dump(mode="json").values())
        == workflow_projection.counts["node_count"]
    )
    derived_controller_connected = all(
        assessed[key]
        for key in (
            "controller_version_endpoint_observed",
            "controller_team_observed",
            "controller_workers_observed",
        )
    )
    derived_workers_ready = _workers_ready(assessed)
    derived_team_ready = _team_ready(assessed)
    derived_skill_specs = assessed["worker_skill_specs_cover_expected"]
    checks["project_registration_matches_projection"] = (
        receipt.project_registered == derived_project_registered
    )
    checks["leader_ingress_matches_projection"] = (
        receipt.leader_ingress_sent == derived_ingress
    )
    checks["workflow_observation_matches_projection"] = (
        receipt.workflow_observed == derived_workflow
        and receipt.workflow_status_counts == derived_status_counts
        and receipt.remote_task_execution_observed == derived_execution
    )
    checks["receipt_control_flags_match_projections"] = (
        receipt.controller_connected == derived_controller_connected
        and receipt.workers_ready == derived_workers_ready
        and receipt.team_ready == derived_team_ready
        and receipt.skill_specs_verified == derived_skill_specs
    )
    operation_facts = {
        "project_registration_observed": derived_project_registered,
        "leader_matrix_ingress_observed": derived_ingress,
        "workflow_project_observed": derived_workflow,
        "remote_task_execution_observed": derived_execution,
        "matrix_worker_assignment_event_verified": False,
    }
    checks["operation_checks_not_drifted"] = all(
        receipt.checks.get(key) == value for key, value in operation_facts.items()
    )
    expected_check_names = control_keys | set(operation_facts)
    checks["no_unknown_receipt_check_names"] = (
        set(receipt.checks) == expected_check_names
    )

    required: set[str] = set()
    if receipt.controller_connected:
        required.update({"version", "team", "workers"})
    if receipt.project_registered:
        required.add("workflow" if project_projection is None else "project")
    if receipt.leader_ingress_sent:
        required.add("matrix_ingress")
    if receipt.workflow_observed:
        required.add("workflow")
    checks["required_projections_present"] = required <= set(projections)

    expected_transaction_sha256: str | None = None
    if (
        receipt.project_id
        and receipt.source_run_id
        and receipt.goal_sha256
        and receipt.approval_id
    ):
        expected_transaction_sha256 = sha256_bytes(
            _matrix_transaction_id(
                project_id=receipt.project_id,
                source_run_id=receipt.source_run_id,
                goal_sha256=receipt.goal_sha256,
                approval_id=receipt.approval_id,
            ).encode("utf-8")
        )
    checks["matrix_transaction_commitment_matches"] = (
        receipt.matrix_transaction_sha256 == expected_transaction_sha256
    )

    if derived_execution:
        derived_operation_status = "REMOTE_EXECUTION_OBSERVED"
    elif derived_ingress:
        derived_operation_status = "LEADER_INGRESS_SENT"
    elif derived_project_registered:
        derived_operation_status = "PROJECT_REGISTERED"
    elif derived_controller_connected and derived_team_ready and derived_skill_specs:
        derived_operation_status = "CONTROL_PLANE_READY"
    elif derived_controller_connected:
        derived_operation_status = "CONTROLLER_CONNECTED"
    else:
        derived_operation_status = "CONFIGURED_NOT_CONNECTED"
    checks["operation_status_matches_projections"] = (
        receipt.operation_status == derived_operation_status
    )

    if receipt.operation == "probe":
        derived_receipt_status = (
            "PASS"
            if derived_controller_connected
            and derived_team_ready
            and derived_skill_specs
            else "FAIL"
        )
        checks["probe_has_no_write_claims"] = not any(
            (
                receipt.project_registered,
                receipt.leader_ingress_sent,
                receipt.workflow_observed,
                bool(receipt.project_id),
                bool(receipt.approval_id),
                bool(receipt.matrix_transaction_sha256),
            )
        )
    else:
        if derived_ingress and derived_workflow:
            derived_receipt_status = "PASS"
        elif derived_project_registered:
            derived_receipt_status = "PARTIAL"
        else:
            derived_receipt_status = "FAIL"
        if receipt.wait_for_remote_execution and not derived_execution:
            derived_receipt_status = "PARTIAL"
        checks["write_authority_fields_present"] = bool(
            receipt.mode is AgentTeamsTransportMode.GATED
            and receipt.project_id
            and receipt.source_run_id
            and receipt.goal_sha256
            and receipt.approval_id
            and receipt.matrix_transaction_sha256
        )
    checks["receipt_status_matches_projections"] = (
        receipt.status == derived_receipt_status
    )
    passed = all(checks.values())
    return HostedReceiptValidation(
        status="PASS" if passed else "FAIL",
        checks=checks,
        reasons=[] if passed else [key for key, value in checks.items() if not value],
        receipt_sha256=receipt.receipt_sha256,
    )


def _parse_bool(value: str | None) -> bool:
    if value is None or not value.strip():
        return False
    normalized = value.strip().casefold()
    if normalized in {"1", "true", "yes", "on"}:
        return True
    if normalized in {"0", "false", "no", "off"}:
        return False
    raise ValueError("boolean environment values must be true or false")


def _read_secret(
    source: Mapping[str, str],
    *,
    value_names: tuple[str, ...],
    file_names: tuple[str, ...],
    label: str,
) -> str | None:
    direct_values = [source[name].strip() for name in value_names if source.get(name)]
    file_values = [source[name].strip() for name in file_names if source.get(name)]
    if (
        len(direct_values) > 1
        or len(file_values) > 1
        or (direct_values and file_values)
    ):
        raise ValueError(f"{label} must come from exactly one environment source")
    if direct_values:
        value = direct_values[0]
    elif file_values:
        path = Path(file_values[0]).expanduser().resolve()
        if not path.is_file() or path.stat().st_size > 65_536:
            raise ValueError(f"{label} file is missing or too large")
        value = path.read_text(encoding="utf-8").strip()
    else:
        return None
    if not value or any(character.isspace() for character in value):
        raise ValueError(f"{label} must be one nonblank token")
    if "REPLACE_WITH" in value.upper() or value in {"<token>", "changeme"}:
        raise ValueError(f"{label} still contains a placeholder")
    return value


def hosted_agentteams_from_environment(
    environment: Mapping[str, str] | None = None,
) -> HostedAgentTeamsTransport | None:
    """Build an explicitly enabled transport without placing tokens in config."""

    source = os.environ if environment is None else environment
    mode = AgentTeamsTransportMode(
        source.get("VISIONDATA_AGENTTEAMS_MODE", "off").strip().casefold()
    )
    if mode is AgentTeamsTransportMode.OFF:
        return None
    if not _parse_bool(source.get("VISIONDATA_AGENTTEAMS_CREDENTIALS_ENABLED")):
        raise PermissionError(
            "Hosted AgentTeams credentials are suppressed until explicitly enabled"
        )
    controller_base_url = source.get("VISIONDATA_AGENTTEAMS_BASE_URL", "").strip()
    allowed_hosts = [
        value.strip()
        for value in source.get("VISIONDATA_AGENTTEAMS_ALLOWED_HOSTS", "").split(",")
        if value.strip()
    ]
    if not controller_base_url or not allowed_hosts:
        raise ValueError(
            "Hosted AgentTeams requires BASE_URL and an explicit host allowlist"
        )
    matrix_base_url = (
        source.get("VISIONDATA_AGENTTEAMS_MATRIX_BASE_URL", "").strip() or None
    )
    matrix_hosts = [
        value.strip()
        for value in source.get("VISIONDATA_AGENTTEAMS_MATRIX_ALLOWED_HOSTS", "").split(
            ","
        )
        if value.strip()
    ]
    config = HostedAgentTeamsConfig(
        mode=mode,
        controller_base_url=controller_base_url,
        controller_allowed_hosts=allowed_hosts,
        controller_allow_local=_parse_bool(
            source.get("VISIONDATA_AGENTTEAMS_ALLOW_LOCAL")
        ),
        matrix_base_url=matrix_base_url,
        matrix_allowed_hosts=matrix_hosts,
        matrix_allow_local=_parse_bool(
            source.get("VISIONDATA_AGENTTEAMS_MATRIX_ALLOW_LOCAL")
        ),
        team_name=source.get("VISIONDATA_AGENTTEAMS_TEAM_NAME", "visiondata-gate"),
        write_enabled=_parse_bool(source.get("VISIONDATA_AGENTTEAMS_WRITE_ENABLED")),
        timeout_seconds=float(
            source.get("VISIONDATA_AGENTTEAMS_TIMEOUT_SECONDS", "10")
        ),
        read_max_retries=int(source.get("VISIONDATA_AGENTTEAMS_READ_MAX_RETRIES", "1")),
        poll_timeout_seconds=float(
            source.get("VISIONDATA_AGENTTEAMS_POLL_TIMEOUT_SECONDS", "60")
        ),
        poll_interval_seconds=float(
            source.get("VISIONDATA_AGENTTEAMS_POLL_INTERVAL_SECONDS", "1")
        ),
    )
    controller_token = _read_secret(
        source,
        value_names=(
            "VISIONDATA_AGENTTEAMS_AUTH_TOKEN",
            "AGENTTEAMS_AUTH_TOKEN",
        ),
        file_names=(
            "VISIONDATA_AGENTTEAMS_AUTH_TOKEN_FILE",
            "AGENTTEAMS_AUTH_TOKEN_FILE",
        ),
        label="Controller token",
    )
    if not controller_token:
        raise PermissionError("Hosted Controller token is not configured")
    matrix_token = _read_secret(
        source,
        value_names=("VISIONDATA_AGENTTEAMS_MATRIX_ACCESS_TOKEN",),
        file_names=("VISIONDATA_AGENTTEAMS_MATRIX_ACCESS_TOKEN_FILE",),
        label="Matrix access token",
    )
    return HostedAgentTeamsTransport(
        config,
        controller_token=controller_token,
        matrix_token=matrix_token,
    )


__all__ = [
    "AgentTeamsTransportMode",
    "HOSTED_AGENTTEAMS_COMMIT",
    "HOSTED_AGENTTEAMS_REPOSITORY",
    "HOSTED_AGENTTEAMS_VERSION",
    "HostedAgentTeamsConfig",
    "HostedAgentTeamsReceipt",
    "HostedAgentTeamsTransport",
    "HostedProjectSubmission",
    "HostedReceiptValidation",
    "hosted_agentteams_from_environment",
    "verify_hosted_agentteams_receipt",
]
