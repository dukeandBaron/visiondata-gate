"""SQLite persistence for users, workspaces, projects, and immutable task inputs."""

from __future__ import annotations

import hashlib
import hmac
import json
import sqlite3
import uuid
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from typing import Any

from .evidence import canonical_json_text
from .lineage import (
    TaskLineageEdge,
    seal_task_lineage_edge,
    task_contract_sha256,
    task_contract_sha256_from_values,
    verify_task_lineage_edge,
)
from .product_models import (
    AuthorizeLocalSourceRequest,
    CreateProjectRequest,
    CreateTaskRequest,
    CreateUserRequest,
    CreateWorkspaceRequest,
    LocalSourceAuthorizationReceipt,
    ProjectRecord,
    RevokeLocalSourceAuthorizationRequest,
    SourceAuthorizationEventReceipt,
    SourceAuthorizationEventType,
    TaskEventRecord,
    TaskExecutionStatus,
    TaskInterventionAction,
    TaskInterventionRecord,
    TaskInterventionRequest,
    TaskPlanApprovalBinding,
    TaskRecord,
    UserRecord,
    WorkspaceRecord,
)


@dataclass(frozen=True)
class LocalSourceBinding:
    """Internal source record; ``root_path`` must never enter public evidence."""

    receipt: LocalSourceAuthorizationReceipt
    root_path: Path


class IncidentCommandOperation(str, Enum):
    """Mutating incident operations admitted by the transactional command gate."""

    CREATE_CASE = "CREATE_CASE"
    RECORD_DECISION = "RECORD_DECISION"
    RESUME_CASE = "RESUME_CASE"


class IncidentCommandStatus(str, Enum):
    """Fail-closed lifecycle for one admitted incident command."""

    EXECUTING = "EXECUTING"
    COMPLETED = "COMPLETED"
    REJECTED = "REJECTED"
    UNCERTAIN = "UNCERTAIN"


@dataclass(frozen=True)
class IncidentCommandRecord:
    """Immutable view of one SQLite-backed incident command claim."""

    command_id: str
    task_id: str
    scope_key: str
    operation: IncidentCommandOperation
    actor_user_id: str
    idempotency_key_sha256: str
    request_sha256: str
    expected_case_sha256: str | None
    admission_sha256: str
    status: IncidentCommandStatus
    resource_type: str | None
    resource_id: str | None
    resource_sha256: str | None
    error_code: str | None
    error_message: str | None
    created_at: str
    updated_at: str
    completed_at: str | None


class ProductStoreError(RuntimeError):
    """Base persistence error with a stable public error code."""

    code = "store_error"


class NotFoundError(ProductStoreError):
    code = "not_found"


class ConflictError(ProductStoreError):
    code = "conflict"


class IncidentCommandBindingConflict(ConflictError):
    """A command or idempotency identity was reused for another admission."""

    code = "incident_command_binding_conflict"


class IncidentCommandScopeOccupied(ConflictError):
    """Another command already owns the same fail-closed effect scope."""

    code = "incident_command_scope_occupied"


class IncidentCommandStateConflict(ConflictError):
    """A command lifecycle transition conflicts with its persisted state."""

    code = "incident_command_state_conflict"


class InvalidTransitionError(ProductStoreError):
    code = "invalid_transition"


_TRANSITIONS: dict[TaskExecutionStatus, set[TaskExecutionStatus]] = {
    TaskExecutionStatus.CREATED: {
        TaskExecutionStatus.PLANNED,
        TaskExecutionStatus.FAILED,
    },
    TaskExecutionStatus.PLANNED: {
        TaskExecutionStatus.RUNNING,
        TaskExecutionStatus.FAILED,
        TaskExecutionStatus.CANCELLED,
    },
    TaskExecutionStatus.RUNNING: {
        TaskExecutionStatus.VERIFYING,
        TaskExecutionStatus.COMPLETED,
        TaskExecutionStatus.FAILED,
    },
    TaskExecutionStatus.VERIFYING: {
        TaskExecutionStatus.COMPLETED,
        TaskExecutionStatus.FAILED,
    },
    TaskExecutionStatus.COMPLETED: {TaskExecutionStatus.ARCHIVED},
    TaskExecutionStatus.FAILED: {TaskExecutionStatus.ARCHIVED},
    TaskExecutionStatus.CANCELLED: {TaskExecutionStatus.ARCHIVED},
    TaskExecutionStatus.ARCHIVED: set(),
}


def _now() -> str:
    from datetime import UTC, datetime

    return datetime.now(UTC).isoformat(timespec="milliseconds")


def _new_id(prefix: str) -> str:
    return f"{prefix}_{uuid.uuid4().hex[:20]}"


def _require_sha256(value: str, *, field_name: str) -> None:
    if len(value) != 64 or any(
        character not in "0123456789abcdef" for character in value
    ):
        raise ValueError(f"{field_name} must be a lowercase SHA-256 digest")


def _incident_command_admission_sha256(
    *,
    command_id: str,
    task_id: str,
    scope_key: str,
    operation: IncidentCommandOperation,
    actor_user_id: str,
    idempotency_key_sha256: str,
    request_sha256: str,
    expected_case_sha256: str | None,
) -> str:
    stable = {
        "command_id": command_id,
        "task_id": task_id,
        "scope_key": scope_key,
        "operation": operation.value,
        "actor_user_id": actor_user_id,
        "idempotency_key_sha256": idempotency_key_sha256,
        "request_sha256": request_sha256,
        "expected_case_sha256": expected_case_sha256,
    }
    return hashlib.sha256(
        canonical_json_text(stable, trailing_newline=False).encode("utf-8")
    ).hexdigest()


def _seal_source_authorization_event(
    *,
    event_id: str,
    source_id: str,
    workspace_id: str,
    sequence: int,
    event_type: SourceAuthorizationEventType,
    actor_kind: str,
    actor_id: str,
    reason: str,
    effective_at: str,
    created_at: str,
    previous_event_sha256: str | None,
    fail_closed_task_ids: list[str],
) -> SourceAuthorizationEventReceipt:
    stable = {
        "schema_version": "visiondata-gate.source-authorization-event.v1",
        "event_id": event_id,
        "source_id": source_id,
        "workspace_id": workspace_id,
        "sequence": sequence,
        "event_type": event_type.value,
        "actor_kind": actor_kind,
        "actor_id": actor_id,
        "reason": reason,
        "effective_at": effective_at,
        "created_at": created_at,
        "previous_event_sha256": previous_event_sha256,
        "fail_closed_task_ids": sorted(fail_closed_task_ids),
        "claim_boundary": SourceAuthorizationEventReceipt.model_fields[
            "claim_boundary"
        ].default,
    }
    digest = hashlib.sha256(
        canonical_json_text(stable, trailing_newline=False).encode("utf-8")
    ).hexdigest()
    return SourceAuthorizationEventReceipt(**stable, event_sha256=digest)


def _verify_source_authorization_event(
    event: SourceAuthorizationEventReceipt,
) -> bool:
    stable = event.model_dump(mode="json", exclude={"event_sha256"})
    observed = hashlib.sha256(
        canonical_json_text(stable, trailing_newline=False).encode("utf-8")
    ).hexdigest()
    return hmac.compare_digest(observed, event.event_sha256)


def _reject_json_constant(value: str) -> None:
    raise ValueError(f"non-finite JSON value is forbidden: {value}")


def _reject_duplicate_json_keys(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    payload: dict[str, Any] = {}
    for key, value in pairs:
        if key in payload:
            raise ValueError(f"duplicate JSON object key is forbidden: {key}")
        payload[key] = value
    return payload


def _strict_canonical_json(value: str) -> str:
    payload = json.loads(
        value,
        parse_constant=_reject_json_constant,
        object_pairs_hook=_reject_duplicate_json_keys,
    )
    return canonical_json_text(payload, trailing_newline=False)


class TaskStore:
    """Small transactional store; every call opens an isolated SQLite connection."""

    def __init__(self, database_path: str | Path) -> None:
        self.database_path = Path(database_path).expanduser().resolve()
        self.database_path.parent.mkdir(parents=True, exist_ok=True)
        self._initialize()

    @contextmanager
    def _connection(self, *, immediate: bool = False) -> Iterator[sqlite3.Connection]:
        connection = sqlite3.connect(self.database_path, timeout=10.0)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys = ON")
        connection.execute("PRAGMA busy_timeout = 10000")
        try:
            if immediate:
                connection.execute("BEGIN IMMEDIATE")
            yield connection
            connection.commit()
        except Exception:
            connection.rollback()
            raise
        finally:
            connection.close()

    def _initialize(self) -> None:
        with self._connection() as connection:
            connection.execute("PRAGMA journal_mode = WAL")
            connection.executescript(
                """
                CREATE TABLE IF NOT EXISTS users (
                    user_id TEXT PRIMARY KEY,
                    display_name TEXT NOT NULL,
                    email TEXT UNIQUE,
                    created_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS workspaces (
                    workspace_id TEXT PRIMARY KEY,
                    name TEXT NOT NULL,
                    owner_user_id TEXT NOT NULL REFERENCES users(user_id),
                    created_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS workspace_members (
                    workspace_id TEXT NOT NULL REFERENCES workspaces(workspace_id),
                    user_id TEXT NOT NULL REFERENCES users(user_id),
                    role TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    PRIMARY KEY (workspace_id, user_id)
                );
                CREATE TABLE IF NOT EXISTS projects (
                    project_id TEXT PRIMARY KEY,
                    workspace_id TEXT NOT NULL REFERENCES workspaces(workspace_id),
                    name TEXT NOT NULL,
                    description TEXT NOT NULL,
                    scenario_profile TEXT NOT NULL,
                    source_kind TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS agent_tasks (
                    task_id TEXT PRIMARY KEY,
                    workspace_id TEXT NOT NULL REFERENCES workspaces(workspace_id),
                    project_id TEXT NOT NULL REFERENCES projects(project_id),
                    created_by TEXT NOT NULL REFERENCES users(user_id),
                    goal TEXT NOT NULL,
                    seed INTEGER NOT NULL,
                    scenario_profile TEXT NOT NULL,
                    source_kind TEXT NOT NULL,
                    source_id TEXT,
                    plan_approval_required INTEGER NOT NULL DEFAULT 0,
                    allowed_tools_json TEXT NOT NULL,
                    request_sha256 TEXT NOT NULL,
                    idempotency_key TEXT,
                    execution_status TEXT NOT NULL,
                    current_phase TEXT NOT NULL,
                    initial_decision TEXT,
                    final_decision TEXT,
                    runtime_status TEXT,
                    artifact_root_rel TEXT,
                    trace_rel TEXT,
                    trace_sha256 TEXT,
                    evidence_zip_rel TEXT,
                    evidence_sha256 TEXT,
                    error_code TEXT,
                    error_message TEXT,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    started_at TEXT,
                    completed_at TEXT,
                    UNIQUE(project_id, idempotency_key)
                );
                CREATE TABLE IF NOT EXISTS incident_commands (
                    command_id TEXT PRIMARY KEY,
                    task_id TEXT NOT NULL REFERENCES agent_tasks(task_id),
                    scope_key TEXT NOT NULL,
                    operation TEXT NOT NULL CHECK(operation IN (
                        'CREATE_CASE', 'RECORD_DECISION', 'RESUME_CASE'
                    )),
                    actor_user_id TEXT NOT NULL REFERENCES users(user_id),
                    idempotency_key_sha256 TEXT NOT NULL,
                    request_sha256 TEXT NOT NULL,
                    expected_case_sha256 TEXT,
                    admission_sha256 TEXT NOT NULL,
                    status TEXT NOT NULL CHECK(status IN (
                        'EXECUTING', 'COMPLETED', 'REJECTED', 'UNCERTAIN'
                    )),
                    resource_type TEXT,
                    resource_id TEXT,
                    resource_sha256 TEXT,
                    error_code TEXT,
                    error_message TEXT,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    completed_at TEXT,
                    UNIQUE (
                        task_id, scope_key, operation, actor_user_id,
                        idempotency_key_sha256
                    )
                );
                CREATE TABLE IF NOT EXISTS task_events (
                    task_id TEXT NOT NULL REFERENCES agent_tasks(task_id),
                    sequence INTEGER NOT NULL,
                    phase TEXT NOT NULL,
                    stage TEXT NOT NULL,
                    status TEXT NOT NULL,
                    summary TEXT NOT NULL,
                    payload_json TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    PRIMARY KEY (task_id, sequence)
                );
                CREATE TABLE IF NOT EXISTS task_interventions (
                    intervention_id TEXT PRIMARY KEY,
                    task_id TEXT NOT NULL REFERENCES agent_tasks(task_id),
                    sequence INTEGER NOT NULL,
                    actor_user_id TEXT NOT NULL REFERENCES users(user_id),
                    action TEXT NOT NULL,
                    note TEXT NOT NULL,
                    before_status TEXT NOT NULL,
                    before_phase TEXT NOT NULL,
                    before_snapshot_sha256 TEXT NOT NULL,
                    plan_sha256 TEXT NOT NULL,
                    approval_binding_json TEXT,
                    created_at TEXT NOT NULL,
                    UNIQUE(task_id, sequence)
                );
                CREATE TABLE IF NOT EXISTS task_lineage (
                    child_task_id TEXT PRIMARY KEY REFERENCES agent_tasks(task_id),
                    parent_task_id TEXT NOT NULL REFERENCES agent_tasks(task_id),
                    root_task_id TEXT NOT NULL REFERENCES agent_tasks(task_id),
                    relation TEXT NOT NULL,
                    depth INTEGER NOT NULL CHECK(depth >= 1),
                    parent_request_sha256 TEXT NOT NULL,
                    parent_evidence_sha256 TEXT NOT NULL,
                    contract_sha256 TEXT NOT NULL,
                    created_by TEXT NOT NULL REFERENCES users(user_id),
                    note TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    edge_sha256 TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS local_source_authorizations (
                    source_id TEXT PRIMARY KEY,
                    workspace_id TEXT NOT NULL REFERENCES workspaces(workspace_id),
                    adapter_kind TEXT NOT NULL,
                    display_name TEXT NOT NULL,
                    root_path TEXT NOT NULL,
                    root_path_sha256 TEXT NOT NULL,
                    source_archive_sha256 TEXT NOT NULL,
                    purpose TEXT NOT NULL,
                    rights_basis TEXT NOT NULL,
                    residency TEXT NOT NULL,
                    operator_attests_authorized_use INTEGER NOT NULL,
                    read_only INTEGER NOT NULL,
                    raw_redistribution_allowed INTEGER NOT NULL,
                    authorization_valid_until TEXT,
                    source_path_retention_policy TEXT NOT NULL DEFAULT 'private_binding_retained_until_operator_cleanup',
                    redacted_receipt_retention_days INTEGER NOT NULL DEFAULT 3650,
                    derived_artifact_retention_days INTEGER NOT NULL DEFAULT 90,
                    post_revocation_source_bytes TEXT NOT NULL DEFAULT 'operator_managed_in_place_not_deleted',
                    data_profile_json TEXT NOT NULL,
                    status TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    UNIQUE(workspace_id, root_path_sha256, source_archive_sha256)
                );
                CREATE TABLE IF NOT EXISTS source_authorization_events (
                    event_id TEXT PRIMARY KEY,
                    source_id TEXT NOT NULL REFERENCES local_source_authorizations(source_id),
                    workspace_id TEXT NOT NULL REFERENCES workspaces(workspace_id),
                    sequence INTEGER NOT NULL CHECK(sequence >= 1),
                    event_type TEXT NOT NULL,
                    actor_kind TEXT NOT NULL,
                    actor_id TEXT NOT NULL,
                    reason TEXT NOT NULL,
                    effective_at TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    previous_event_sha256 TEXT,
                    fail_closed_task_ids_json TEXT NOT NULL,
                    event_sha256 TEXT NOT NULL,
                    UNIQUE(source_id, sequence),
                    UNIQUE(source_id, event_sha256)
                );
                CREATE INDEX IF NOT EXISTS idx_projects_workspace
                    ON projects(workspace_id);
                CREATE INDEX IF NOT EXISTS idx_tasks_project_created
                    ON agent_tasks(project_id, created_at DESC);
                CREATE INDEX IF NOT EXISTS idx_tasks_workspace_created
                    ON agent_tasks(workspace_id, created_at DESC);
                CREATE INDEX IF NOT EXISTS idx_incident_commands_task_created
                    ON incident_commands(task_id, created_at, command_id);
                CREATE UNIQUE INDEX IF NOT EXISTS idx_incident_commands_effect_scope
                    ON incident_commands(
                        task_id, scope_key, operation, expected_case_sha256
                    )
                    WHERE operation IN ('RECORD_DECISION', 'RESUME_CASE')
                      AND status IN ('EXECUTING', 'COMPLETED', 'UNCERTAIN');
                CREATE INDEX IF NOT EXISTS idx_sources_workspace_created
                    ON local_source_authorizations(workspace_id, created_at DESC);
                CREATE INDEX IF NOT EXISTS idx_source_authorization_events_source
                    ON source_authorization_events(source_id, sequence);
                CREATE INDEX IF NOT EXISTS idx_interventions_task_sequence
                    ON task_interventions(task_id, sequence);
                CREATE INDEX IF NOT EXISTS idx_task_lineage_root_depth
                    ON task_lineage(root_task_id, depth, created_at);
                CREATE TRIGGER IF NOT EXISTS task_interventions_no_update
                BEFORE UPDATE ON task_interventions
                BEGIN
                    SELECT RAISE(ABORT, 'task interventions are append-only');
                END;
                CREATE TRIGGER IF NOT EXISTS task_interventions_no_delete
                BEFORE DELETE ON task_interventions
                BEGIN
                    SELECT RAISE(ABORT, 'task interventions are append-only');
                END;
                CREATE TRIGGER IF NOT EXISTS task_lineage_no_update
                BEFORE UPDATE ON task_lineage
                BEGIN
                    SELECT RAISE(ABORT, 'task lineage is append-only');
                END;
                CREATE TRIGGER IF NOT EXISTS task_lineage_no_delete
                BEFORE DELETE ON task_lineage
                BEGIN
                    SELECT RAISE(ABORT, 'task lineage is append-only');
                END;
                CREATE TRIGGER IF NOT EXISTS source_authorization_events_no_update
                BEFORE UPDATE ON source_authorization_events
                BEGIN
                    SELECT RAISE(ABORT, 'source authorization events are append-only');
                END;
                CREATE TRIGGER IF NOT EXISTS source_authorization_events_no_delete
                BEFORE DELETE ON source_authorization_events
                BEGIN
                    SELECT RAISE(ABORT, 'source authorization events are append-only');
                END;
                """
            )
            task_columns = {
                str(row[1])
                for row in connection.execute("PRAGMA table_info(agent_tasks)")
            }
            if "trace_sha256" not in task_columns:
                connection.execute(
                    "ALTER TABLE agent_tasks ADD COLUMN trace_sha256 TEXT"
                )
            if "source_id" not in task_columns:
                connection.execute("ALTER TABLE agent_tasks ADD COLUMN source_id TEXT")
            if "plan_approval_required" not in task_columns:
                connection.execute(
                    "ALTER TABLE agent_tasks ADD COLUMN "
                    "plan_approval_required INTEGER NOT NULL DEFAULT 0"
                )
            intervention_columns = {
                str(row[1])
                for row in connection.execute("PRAGMA table_info(task_interventions)")
            }
            if "approval_binding_json" not in intervention_columns:
                connection.execute(
                    "ALTER TABLE task_interventions "
                    "ADD COLUMN approval_binding_json TEXT"
                )
            source_columns = {
                str(row[1])
                for row in connection.execute(
                    "PRAGMA table_info(local_source_authorizations)"
                )
            }
            source_migrations = {
                "authorization_valid_until": "TEXT",
                "source_path_retention_policy": (
                    "TEXT NOT NULL DEFAULT "
                    "'private_binding_retained_until_operator_cleanup'"
                ),
                "redacted_receipt_retention_days": "INTEGER NOT NULL DEFAULT 3650",
                "derived_artifact_retention_days": "INTEGER NOT NULL DEFAULT 90",
                "post_revocation_source_bytes": (
                    "TEXT NOT NULL DEFAULT 'operator_managed_in_place_not_deleted'"
                ),
            }
            for column, declaration in source_migrations.items():
                if column not in source_columns:
                    connection.execute(
                        f"ALTER TABLE local_source_authorizations "
                        f"ADD COLUMN {column} {declaration}"
                    )
            self._seed_legacy_authorization_events(connection)
            connection.execute("PRAGMA user_version = 7")

    @staticmethod
    def _insert_source_authorization_event(
        connection: sqlite3.Connection,
        event: SourceAuthorizationEventReceipt,
    ) -> None:
        connection.execute(
            """
            INSERT INTO source_authorization_events (
                event_id, source_id, workspace_id, sequence, event_type,
                actor_kind, actor_id, reason, effective_at, created_at,
                previous_event_sha256, fail_closed_task_ids_json, event_sha256
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                event.event_id,
                event.source_id,
                event.workspace_id,
                event.sequence,
                event.event_type.value,
                event.actor_kind,
                event.actor_id,
                event.reason,
                event.effective_at,
                event.created_at,
                event.previous_event_sha256,
                canonical_json_text(event.fail_closed_task_ids, trailing_newline=False),
                event.event_sha256,
            ),
        )

    @classmethod
    def _seed_legacy_authorization_events(cls, connection: sqlite3.Connection) -> None:
        rows = connection.execute(
            """
            SELECT source.*, workspace.owner_user_id
            FROM local_source_authorizations AS source
            JOIN workspaces AS workspace
                ON workspace.workspace_id = source.workspace_id
            WHERE NOT EXISTS (
                SELECT 1 FROM source_authorization_events AS event
                WHERE event.source_id = source.source_id
            )
            ORDER BY source.created_at, source.source_id
            """
        ).fetchall()
        for row in rows:
            granted = _seal_source_authorization_event(
                event_id=_new_id("sae"),
                source_id=str(row["source_id"]),
                workspace_id=str(row["workspace_id"]),
                sequence=1,
                event_type=SourceAuthorizationEventType.GRANTED,
                actor_kind="system",
                actor_id="system:migration-v6",
                reason=(
                    "Migrated pre-v6 authorization into the append-only lifecycle ledger."
                ),
                effective_at=str(row["created_at"]),
                created_at=str(row["created_at"]),
                previous_event_sha256=None,
                fail_closed_task_ids=[],
            )
            cls._insert_source_authorization_event(connection, granted)
            if str(row["status"]).casefold() == "revoked":
                revoked = _seal_source_authorization_event(
                    event_id=_new_id("sae"),
                    source_id=str(row["source_id"]),
                    workspace_id=str(row["workspace_id"]),
                    sequence=2,
                    event_type=SourceAuthorizationEventType.REVOKED,
                    actor_kind="system",
                    actor_id="system:migration-v6",
                    reason="Migrated legacy revoked state without reopening source access.",
                    effective_at=str(row["created_at"]),
                    created_at=str(row["created_at"]),
                    previous_event_sha256=granted.event_sha256,
                    fail_closed_task_ids=[],
                )
                cls._insert_source_authorization_event(connection, revoked)

    @staticmethod
    def _source_authorization_event(
        row: sqlite3.Row,
    ) -> SourceAuthorizationEventReceipt:
        event = SourceAuthorizationEventReceipt(
            event_id=str(row["event_id"]),
            source_id=str(row["source_id"]),
            workspace_id=str(row["workspace_id"]),
            sequence=int(row["sequence"]),
            event_type=str(row["event_type"]),
            actor_kind=str(row["actor_kind"]),
            actor_id=str(row["actor_id"]),
            reason=str(row["reason"]),
            effective_at=str(row["effective_at"]),
            created_at=str(row["created_at"]),
            previous_event_sha256=(
                str(row["previous_event_sha256"])
                if row["previous_event_sha256"] is not None
                else None
            ),
            fail_closed_task_ids=json.loads(str(row["fail_closed_task_ids_json"])),
            event_sha256=str(row["event_sha256"]),
        )
        if not _verify_source_authorization_event(event):
            raise ConflictError("source authorization event integrity check failed")
        return event

    @classmethod
    def _source_authorization_events(
        cls, connection: sqlite3.Connection, source_id: str
    ) -> list[SourceAuthorizationEventReceipt]:
        rows = connection.execute(
            """
            SELECT * FROM source_authorization_events
            WHERE source_id = ? ORDER BY sequence
            """,
            (source_id,),
        ).fetchall()
        events = [cls._source_authorization_event(row) for row in rows]
        previous: str | None = None
        for expected_sequence, event in enumerate(events, start=1):
            if (
                event.sequence != expected_sequence
                or event.previous_event_sha256 != previous
            ):
                raise ConflictError("source authorization event chain is incomplete")
            previous = event.event_sha256
        if (
            not events
            or events[0].event_type is not SourceAuthorizationEventType.GRANTED
        ):
            raise ConflictError("source authorization grant event is missing")
        return events

    @staticmethod
    def _user(row: sqlite3.Row) -> UserRecord:
        return UserRecord(**dict(row))

    @staticmethod
    def _workspace(row: sqlite3.Row) -> WorkspaceRecord:
        return WorkspaceRecord(**dict(row))

    @staticmethod
    def _project(row: sqlite3.Row) -> ProjectRecord:
        return ProjectRecord(**dict(row))

    @staticmethod
    def _task(row: sqlite3.Row) -> TaskRecord:
        payload = dict(row)
        payload["allowed_tools"] = json.loads(payload.pop("allowed_tools_json"))
        payload["plan_approval_required"] = bool(
            payload.get("plan_approval_required", 0)
        )
        return TaskRecord(**payload)

    @staticmethod
    def _incident_command(row: sqlite3.Row) -> IncidentCommandRecord:
        try:
            record = IncidentCommandRecord(
                command_id=str(row["command_id"]),
                task_id=str(row["task_id"]),
                scope_key=str(row["scope_key"]),
                operation=IncidentCommandOperation(str(row["operation"])),
                actor_user_id=str(row["actor_user_id"]),
                idempotency_key_sha256=str(row["idempotency_key_sha256"]),
                request_sha256=str(row["request_sha256"]),
                expected_case_sha256=(
                    str(row["expected_case_sha256"])
                    if row["expected_case_sha256"] is not None
                    else None
                ),
                admission_sha256=str(row["admission_sha256"]),
                status=IncidentCommandStatus(str(row["status"])),
                resource_type=(
                    str(row["resource_type"])
                    if row["resource_type"] is not None
                    else None
                ),
                resource_id=(
                    str(row["resource_id"]) if row["resource_id"] is not None else None
                ),
                resource_sha256=(
                    str(row["resource_sha256"])
                    if row["resource_sha256"] is not None
                    else None
                ),
                error_code=(
                    str(row["error_code"]) if row["error_code"] is not None else None
                ),
                error_message=(
                    str(row["error_message"])
                    if row["error_message"] is not None
                    else None
                ),
                created_at=str(row["created_at"]),
                updated_at=str(row["updated_at"]),
                completed_at=(
                    str(row["completed_at"])
                    if row["completed_at"] is not None
                    else None
                ),
            )
        except (KeyError, TypeError, ValueError) as error:
            raise ConflictError("incident command record is invalid") from error
        expected_admission = _incident_command_admission_sha256(
            command_id=record.command_id,
            task_id=record.task_id,
            scope_key=record.scope_key,
            operation=record.operation,
            actor_user_id=record.actor_user_id,
            idempotency_key_sha256=record.idempotency_key_sha256,
            request_sha256=record.request_sha256,
            expected_case_sha256=record.expected_case_sha256,
        )
        if not hmac.compare_digest(record.admission_sha256, expected_admission):
            raise ConflictError("incident command admission integrity check failed")
        resource_fields = (
            record.resource_type,
            record.resource_id,
            record.resource_sha256,
        )
        if record.status is IncidentCommandStatus.EXECUTING:
            if (
                any(value is not None for value in resource_fields)
                or record.error_code is not None
                or record.error_message is not None
                or record.completed_at is not None
            ):
                raise ConflictError("executing incident command has terminal fields")
        elif record.status is IncidentCommandStatus.COMPLETED:
            if (
                not all(resource_fields)
                or record.error_code is not None
                or record.error_message is not None
                or record.completed_at is None
            ):
                raise ConflictError(
                    "completed incident command is missing its resource"
                )
        elif (
            any(value is not None for value in resource_fields)
            or not record.error_code
            or record.completed_at is None
        ):
            raise ConflictError(
                "failed incident command has an invalid terminal outcome"
            )
        return record

    @staticmethod
    def _intervention(row: sqlite3.Row) -> TaskInterventionRecord:
        payload = dict(row)
        raw_binding = payload.pop("approval_binding_json", None)
        payload["approval_binding"] = (
            json.loads(raw_binding) if isinstance(raw_binding, str) else None
        )
        return TaskInterventionRecord(**payload)

    @staticmethod
    def _lineage_edge(row: sqlite3.Row) -> TaskLineageEdge:
        edge = TaskLineageEdge(**dict(row))
        if not verify_task_lineage_edge(edge):
            raise ConflictError("task lineage edge integrity check failed")
        return edge

    @staticmethod
    def task_snapshot_sha256(task: TaskRecord) -> str:
        payload = task.model_dump(mode="json")
        return hashlib.sha256(
            canonical_json_text(payload, trailing_newline=False).encode("utf-8")
        ).hexdigest()

    @staticmethod
    def _local_source_receipt(
        row: sqlite3.Row,
        events: list[SourceAuthorizationEventReceipt],
    ) -> LocalSourceAuthorizationReceipt:
        data_profile = json.loads(str(row["data_profile_json"]))
        derived_version_id = data_profile.get("derived_version_id")
        derived_from_source_id = data_profile.get("derived_from_source_id")
        latest_event = events[-1]
        status_by_event = {
            SourceAuthorizationEventType.GRANTED: "active",
            SourceAuthorizationEventType.REVOKED: "revoked",
            SourceAuthorizationEventType.EXPIRED: "expired",
        }
        return LocalSourceAuthorizationReceipt(
            schema_version="visiondata-gate.local-source-authorization.v3",
            source_id=str(row["source_id"]),
            workspace_id=str(row["workspace_id"]),
            adapter_kind=str(row["adapter_kind"]),
            display_name=str(row["display_name"]),
            root_path_sha256=str(row["root_path_sha256"]),
            source_archive_sha256=str(row["source_archive_sha256"]),
            purpose=str(row["purpose"]),
            rights_basis=str(row["rights_basis"]),
            residency=str(row["residency"]),
            operator_attests_authorized_use=bool(
                row["operator_attests_authorized_use"]
            ),
            read_only=bool(row["read_only"]),
            raw_redistribution_allowed=bool(row["raw_redistribution_allowed"]),
            source_assets_copied_into_product=bool(
                data_profile.get("source_assets_copied_into_product", False)
            ),
            derived_from_source_id=(
                str(derived_from_source_id)
                if derived_from_source_id is not None
                else None
            ),
            derived_version_id=(
                str(derived_version_id) if derived_version_id is not None else None
            ),
            data_profile=data_profile,
            status=status_by_event[latest_event.event_type],
            authorization_valid_until=(
                str(row["authorization_valid_until"])
                if row["authorization_valid_until"] is not None
                else None
            ),
            source_path_retention_policy=str(row["source_path_retention_policy"]),
            redacted_receipt_retention_days=int(row["redacted_receipt_retention_days"]),
            derived_artifact_retention_days=int(row["derived_artifact_retention_days"]),
            post_revocation_source_bytes=str(row["post_revocation_source_bytes"]),
            authorization_event_count=len(events),
            latest_authorization_event_type=latest_event.event_type,
            latest_authorization_event_sha256=latest_event.event_sha256,
            created_at=str(row["created_at"]),
        )

    def create_user(self, request: CreateUserRequest) -> UserRecord:
        user_id = _new_id("usr")
        created_at = _now()
        try:
            with self._connection(immediate=True) as connection:
                connection.execute(
                    "INSERT INTO users VALUES (?, ?, ?, ?)",
                    (user_id, request.display_name, request.email, created_at),
                )
        except sqlite3.IntegrityError as exc:
            raise ConflictError("a user with this email already exists") from exc
        return UserRecord(
            user_id=user_id,
            display_name=request.display_name,
            email=request.email,
            created_at=created_at,
        )

    def ensure_default_tenant(
        self,
    ) -> tuple[UserRecord, WorkspaceRecord, ProjectRecord]:
        """Atomically create the deterministic local demo tenant once."""

        user_id = "usr_local_demo"
        workspace_id = "wsp_local_demo"
        project_id = "prj_industrial_vision"
        timestamp = _now()
        with self._connection(immediate=True) as connection:
            connection.execute(
                "INSERT OR IGNORE INTO users VALUES (?, ?, ?, ?)",
                (user_id, "本地演示用户", None, timestamp),
            )
            connection.execute(
                "INSERT OR IGNORE INTO workspaces VALUES (?, ?, ?, ?)",
                (workspace_id, "Vision Lab", user_id, timestamp),
            )
            connection.execute(
                "INSERT OR IGNORE INTO workspace_members VALUES (?, ?, 'owner', ?)",
                (workspace_id, user_id, timestamp),
            )
            connection.execute(
                """
                INSERT OR IGNORE INTO projects VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    project_id,
                    workspace_id,
                    "工业视觉数据门禁",
                    "审核进入实验训练池前的图像、标注、重复泄漏与覆盖完整性。",
                    "industrial",
                    "synthetic_demo",
                    timestamp,
                    timestamp,
                ),
            )
            user_row = connection.execute(
                "SELECT * FROM users WHERE user_id = ?", (user_id,)
            ).fetchone()
            workspace_row = connection.execute(
                """
                SELECT w.*, m.role FROM workspaces w
                JOIN workspace_members m ON m.workspace_id = w.workspace_id
                WHERE w.workspace_id = ? AND m.user_id = ?
                """,
                (workspace_id, user_id),
            ).fetchone()
            project_row = connection.execute(
                "SELECT * FROM projects WHERE project_id = ?", (project_id,)
            ).fetchone()
        assert user_row is not None
        assert workspace_row is not None
        assert project_row is not None
        return (
            self._user(user_row),
            self._workspace(workspace_row),
            self._project(project_row),
        )

    def list_users(self) -> list[UserRecord]:
        with self._connection() as connection:
            rows = connection.execute(
                "SELECT * FROM users ORDER BY created_at, user_id"
            ).fetchall()
        return [self._user(row) for row in rows]

    def get_user(self, user_id: str) -> UserRecord:
        with self._connection() as connection:
            row = connection.execute(
                "SELECT * FROM users WHERE user_id = ?", (user_id,)
            ).fetchone()
        if row is None:
            raise NotFoundError("user not found")
        return self._user(row)

    def create_workspace(self, request: CreateWorkspaceRequest) -> WorkspaceRecord:
        workspace_id = _new_id("wsp")
        created_at = _now()
        try:
            with self._connection(immediate=True) as connection:
                connection.execute(
                    "INSERT INTO workspaces VALUES (?, ?, ?, ?)",
                    (
                        workspace_id,
                        request.name,
                        request.owner_user_id,
                        created_at,
                    ),
                )
                connection.execute(
                    "INSERT INTO workspace_members VALUES (?, ?, 'owner', ?)",
                    (workspace_id, request.owner_user_id, created_at),
                )
        except sqlite3.IntegrityError as exc:
            raise NotFoundError("workspace owner does not exist") from exc
        return WorkspaceRecord(
            workspace_id=workspace_id,
            name=request.name,
            owner_user_id=request.owner_user_id,
            role="owner",
            created_at=created_at,
        )

    def list_workspaces(self, actor_user_id: str) -> list[WorkspaceRecord]:
        with self._connection() as connection:
            rows = connection.execute(
                """
                SELECT w.*, m.role
                FROM workspaces w
                JOIN workspace_members m ON m.workspace_id = w.workspace_id
                WHERE m.user_id = ?
                ORDER BY w.created_at, w.workspace_id
                """,
                (actor_user_id,),
            ).fetchall()
        return [self._workspace(row) for row in rows]

    def _require_membership(
        self, connection: sqlite3.Connection, workspace_id: str, actor_user_id: str
    ) -> None:
        row = connection.execute(
            "SELECT 1 FROM workspace_members WHERE workspace_id = ? AND user_id = ?",
            (workspace_id, actor_user_id),
        ).fetchone()
        if row is None:
            raise NotFoundError("workspace not found")

    def create_project(
        self, actor_user_id: str, request: CreateProjectRequest
    ) -> ProjectRecord:
        project_id = _new_id("prj")
        timestamp = _now()
        with self._connection(immediate=True) as connection:
            self._require_membership(connection, request.workspace_id, actor_user_id)
            connection.execute(
                """
                INSERT INTO projects VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    project_id,
                    request.workspace_id,
                    request.name,
                    request.description,
                    request.scenario_profile.value,
                    request.source_kind.value,
                    timestamp,
                    timestamp,
                ),
            )
        return ProjectRecord(
            project_id=project_id,
            workspace_id=request.workspace_id,
            name=request.name,
            description=request.description,
            scenario_profile=request.scenario_profile,
            source_kind=request.source_kind,
            created_at=timestamp,
            updated_at=timestamp,
        )

    def list_projects(
        self, actor_user_id: str, workspace_id: str
    ) -> list[ProjectRecord]:
        with self._connection() as connection:
            self._require_membership(connection, workspace_id, actor_user_id)
            rows = connection.execute(
                "SELECT * FROM projects WHERE workspace_id = ? ORDER BY created_at DESC",
                (workspace_id,),
            ).fetchall()
        return [self._project(row) for row in rows]

    def get_project(self, actor_user_id: str, project_id: str) -> ProjectRecord:
        with self._connection() as connection:
            row = connection.execute(
                "SELECT * FROM projects WHERE project_id = ?", (project_id,)
            ).fetchone()
            if row is None:
                raise NotFoundError("project not found")
            self._require_membership(
                connection, str(row["workspace_id"]), actor_user_id
            )
        return self._project(row)

    def create_local_source_authorization(
        self,
        actor_user_id: str,
        request: AuthorizeLocalSourceRequest,
        *,
        resolved_root: Path,
        root_path_sha256: str,
        data_profile: dict[str, Any],
    ) -> LocalSourceAuthorizationReceipt:
        source_id = _new_id("src")
        created_at = _now()
        canonical_profile = canonical_json_text(data_profile, trailing_newline=False)
        with self._connection(immediate=True) as connection:
            self._require_membership(connection, request.workspace_id, actor_user_id)
            existing = connection.execute(
                """
                SELECT * FROM local_source_authorizations
                WHERE workspace_id = ? AND root_path_sha256 = ?
                    AND source_archive_sha256 = ?
                """,
                (
                    request.workspace_id,
                    root_path_sha256,
                    request.source_archive_sha256,
                ),
            ).fetchone()
            if existing is not None:
                self._expire_source_if_due(connection, existing)
                events = self._source_authorization_events(
                    connection, str(existing["source_id"])
                )
                return self._local_source_receipt(existing, events)
            connection.execute(
                """
                INSERT INTO local_source_authorizations (
                    source_id, workspace_id, adapter_kind, display_name,
                    root_path, root_path_sha256, source_archive_sha256,
                    purpose, rights_basis, residency,
                    operator_attests_authorized_use, read_only,
                    raw_redistribution_allowed, authorization_valid_until,
                    source_path_retention_policy,
                    redacted_receipt_retention_days,
                    derived_artifact_retention_days,
                    post_revocation_source_bytes,
                    data_profile_json, status, created_at
                ) VALUES (
                    ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?
                )
                """,
                (
                    source_id,
                    request.workspace_id,
                    request.adapter_kind.value,
                    request.display_name,
                    str(resolved_root),
                    root_path_sha256,
                    request.source_archive_sha256,
                    request.purpose,
                    request.rights_basis,
                    request.residency,
                    int(request.operator_attests_authorized_use),
                    int(request.read_only),
                    int(request.raw_redistribution_allowed),
                    request.authorization_valid_until,
                    request.source_path_retention_policy,
                    request.redacted_receipt_retention_days,
                    request.derived_artifact_retention_days,
                    request.post_revocation_source_bytes,
                    canonical_profile,
                    "active",
                    created_at,
                ),
            )
            granted = _seal_source_authorization_event(
                event_id=_new_id("sae"),
                source_id=source_id,
                workspace_id=request.workspace_id,
                sequence=1,
                event_type=SourceAuthorizationEventType.GRANTED,
                actor_kind="operator",
                actor_id=actor_user_id,
                reason=(
                    "Operator granted bounded read-only use for the declared purpose, "
                    "rights basis, residency, retention, and no-redistribution policy."
                ),
                effective_at=created_at,
                created_at=created_at,
                previous_event_sha256=None,
                fail_closed_task_ids=[],
            )
            self._insert_source_authorization_event(connection, granted)
            row = connection.execute(
                "SELECT * FROM local_source_authorizations WHERE source_id = ?",
                (source_id,),
            ).fetchone()
        assert row is not None
        return self._local_source_receipt(row, [granted])

    @staticmethod
    def _fail_pending_tasks_for_source(
        connection: sqlite3.Connection,
        *,
        source_id: str,
        error_code: str,
        error_message: str,
        timestamp: str,
    ) -> list[str]:
        rows = connection.execute(
            """
            SELECT task_id FROM agent_tasks
            WHERE source_id = ? AND execution_status IN (?, ?)
            ORDER BY created_at, task_id
            """,
            (
                source_id,
                TaskExecutionStatus.CREATED.value,
                TaskExecutionStatus.PLANNED.value,
            ),
        ).fetchall()
        task_ids = [str(row["task_id"]) for row in rows]
        if task_ids:
            placeholders = ",".join("?" for _ in task_ids)
            connection.execute(
                f"""
                UPDATE agent_tasks
                SET execution_status = ?, current_phase = ?, error_code = ?,
                    error_message = ?, updated_at = ?, completed_at = ?
                WHERE task_id IN ({placeholders})
                """,
                (
                    TaskExecutionStatus.FAILED.value,
                    "failed_authorization",
                    error_code,
                    error_message[:500],
                    timestamp,
                    timestamp,
                    *task_ids,
                ),
            )
        return task_ids

    @classmethod
    def _append_terminal_source_authorization_event(
        cls,
        connection: sqlite3.Connection,
        *,
        source_row: sqlite3.Row,
        event_type: SourceAuthorizationEventType,
        actor_kind: str,
        actor_id: str,
        reason: str,
        expected_latest_event_sha256: str | None,
        timestamp: str,
    ) -> SourceAuthorizationEventReceipt:
        events = cls._source_authorization_events(
            connection, str(source_row["source_id"])
        )
        latest = events[-1]
        if latest.event_type is not SourceAuthorizationEventType.GRANTED:
            raise ConflictError("source authorization is already terminal")
        if expected_latest_event_sha256 is not None and not hmac.compare_digest(
            latest.event_sha256, expected_latest_event_sha256
        ):
            raise ConflictError(
                "source authorization changed; refresh the event chain before retrying"
            )
        error_code = (
            "SOURCE_AUTHORIZATION_REVOKED"
            if event_type is SourceAuthorizationEventType.REVOKED
            else "SOURCE_AUTHORIZATION_EXPIRED"
        )
        failed_tasks = cls._fail_pending_tasks_for_source(
            connection,
            source_id=str(source_row["source_id"]),
            error_code=error_code,
            error_message=(
                "The bound source authorization became terminal before execution; "
                "the pending task was failed closed without reading source bytes."
            ),
            timestamp=timestamp,
        )
        event = _seal_source_authorization_event(
            event_id=_new_id("sae"),
            source_id=str(source_row["source_id"]),
            workspace_id=str(source_row["workspace_id"]),
            sequence=latest.sequence + 1,
            event_type=event_type,
            actor_kind=actor_kind,
            actor_id=actor_id,
            reason=reason,
            effective_at=timestamp,
            created_at=timestamp,
            previous_event_sha256=latest.event_sha256,
            fail_closed_task_ids=failed_tasks,
        )
        cls._insert_source_authorization_event(connection, event)
        return event

    @classmethod
    def _expire_source_if_due(
        cls,
        connection: sqlite3.Connection,
        source_row: sqlite3.Row,
        *,
        now: str | None = None,
    ) -> SourceAuthorizationEventReceipt | None:
        valid_until = source_row["authorization_valid_until"]
        if valid_until is None:
            return None
        events = cls._source_authorization_events(
            connection, str(source_row["source_id"])
        )
        if events[-1].event_type is not SourceAuthorizationEventType.GRANTED:
            return None
        from datetime import datetime

        observed_now = now or _now()
        deadline = datetime.fromisoformat(str(valid_until).replace("Z", "+00:00"))
        observed = datetime.fromisoformat(observed_now.replace("Z", "+00:00"))
        if observed < deadline:
            return None
        return cls._append_terminal_source_authorization_event(
            connection,
            source_row=source_row,
            event_type=SourceAuthorizationEventType.EXPIRED,
            actor_kind="system",
            actor_id="system:authorization-expiry",
            reason="The declared authorization validity window expired.",
            expected_latest_event_sha256=events[-1].event_sha256,
            timestamp=observed_now,
        )

    def expire_due_local_source_authorizations(
        self, *, now: str | None = None
    ) -> list[SourceAuthorizationEventReceipt]:
        expired: list[SourceAuthorizationEventReceipt] = []
        with self._connection(immediate=True) as connection:
            rows = connection.execute(
                """
                SELECT * FROM local_source_authorizations
                WHERE authorization_valid_until IS NOT NULL
                ORDER BY created_at, source_id
                """
            ).fetchall()
            for row in rows:
                event = self._expire_source_if_due(connection, row, now=now)
                if event is not None:
                    expired.append(event)
        return expired

    def revoke_local_source_authorization(
        self,
        actor_user_id: str,
        source_id: str,
        request: RevokeLocalSourceAuthorizationRequest,
    ) -> SourceAuthorizationEventReceipt:
        with self._connection(immediate=True) as connection:
            row = connection.execute(
                "SELECT * FROM local_source_authorizations WHERE source_id = ?",
                (source_id,),
            ).fetchone()
            if row is None:
                raise NotFoundError("data source not found")
            self._require_membership(
                connection, str(row["workspace_id"]), actor_user_id
            )
            self._expire_source_if_due(connection, row)
            event = self._append_terminal_source_authorization_event(
                connection,
                source_row=row,
                event_type=SourceAuthorizationEventType.REVOKED,
                actor_kind="operator",
                actor_id=actor_user_id,
                reason=request.reason,
                expected_latest_event_sha256=(request.expected_latest_event_sha256),
                timestamp=_now(),
            )
        return event

    def list_source_authorization_events(
        self, actor_user_id: str, source_id: str
    ) -> list[SourceAuthorizationEventReceipt]:
        with self._connection(immediate=True) as connection:
            row = connection.execute(
                "SELECT * FROM local_source_authorizations WHERE source_id = ?",
                (source_id,),
            ).fetchone()
            if row is None:
                raise NotFoundError("data source not found")
            self._require_membership(
                connection, str(row["workspace_id"]), actor_user_id
            )
            self._expire_source_if_due(connection, row)
            return self._source_authorization_events(connection, source_id)

    def get_local_source_authorization(
        self, actor_user_id: str, source_id: str
    ) -> LocalSourceAuthorizationReceipt:
        with self._connection(immediate=True) as connection:
            row = connection.execute(
                "SELECT * FROM local_source_authorizations WHERE source_id = ?",
                (source_id,),
            ).fetchone()
            if row is None:
                raise NotFoundError("data source not found")
            self._require_membership(
                connection, str(row["workspace_id"]), actor_user_id
            )
            self._expire_source_if_due(connection, row)
            events = self._source_authorization_events(connection, source_id)
        return self._local_source_receipt(row, events)

    def get_local_source_binding_unscoped(self, source_id: str) -> LocalSourceBinding:
        with self._connection(immediate=True) as connection:
            row = connection.execute(
                "SELECT * FROM local_source_authorizations WHERE source_id = ?",
                (source_id,),
            ).fetchone()
            if row is None:
                raise NotFoundError("data source not found")
            self._expire_source_if_due(connection, row)
            events = self._source_authorization_events(connection, source_id)
        return LocalSourceBinding(
            receipt=self._local_source_receipt(row, events),
            root_path=Path(str(row["root_path"])).resolve(strict=False),
        )

    def list_local_source_authorizations(
        self, actor_user_id: str, workspace_id: str
    ) -> list[LocalSourceAuthorizationReceipt]:
        with self._connection(immediate=True) as connection:
            self._require_membership(connection, workspace_id, actor_user_id)
            rows = connection.execute(
                """
                SELECT * FROM local_source_authorizations
                WHERE workspace_id = ? ORDER BY created_at DESC, source_id DESC
                """,
                (workspace_id,),
            ).fetchall()
            for row in rows:
                self._expire_source_if_due(connection, row)
            receipts = [
                self._local_source_receipt(
                    row,
                    self._source_authorization_events(
                        connection, str(row["source_id"])
                    ),
                )
                for row in rows
            ]
        return receipts

    def create_task(
        self,
        actor_user_id: str,
        request: CreateTaskRequest,
        *,
        scenario_profile: str,
        request_sha256: str,
        idempotency_key: str | None,
        lineage_parent_task_id: str | None = None,
        lineage_contract_sha256: str | None = None,
        lineage_note: str | None = None,
    ) -> tuple[TaskRecord, bool]:
        task_id = _new_id("tsk")
        timestamp = _now()
        with self._connection(immediate=True) as connection:
            project = connection.execute(
                "SELECT * FROM projects WHERE project_id = ?", (request.project_id,)
            ).fetchone()
            if project is None:
                raise NotFoundError("project not found")
            workspace_id = str(project["workspace_id"])
            self._require_membership(connection, workspace_id, actor_user_id)
            parent: TaskRecord | None = None
            parent_edge: TaskLineageEdge | None = None
            if lineage_parent_task_id is not None:
                if not lineage_contract_sha256 or not lineage_note:
                    raise ValueError("lineage contract and note are required")
                parent_row = connection.execute(
                    "SELECT * FROM agent_tasks WHERE task_id = ?",
                    (lineage_parent_task_id,),
                ).fetchone()
                if parent_row is None:
                    raise NotFoundError("parent task not found")
                parent = self._task(parent_row)
                if (
                    parent.workspace_id != workspace_id
                    or parent.project_id != request.project_id
                ):
                    raise ConflictError(
                        "re-verification parent must belong to the same project"
                    )
                if parent.execution_status is not TaskExecutionStatus.COMPLETED:
                    raise ConflictError(
                        "re-verification parent must be a completed task"
                    )
                if not parent.evidence_sha256:
                    raise ConflictError(
                        "re-verification parent has no immutable evidence digest"
                    )
                if not request.plan_approval_required:
                    raise ConflictError(
                        "re-verification requires explicit human plan approval"
                    )
                parent_contract = task_contract_sha256(parent)
                child_contract = task_contract_sha256_from_values(
                    project_id=request.project_id,
                    scenario_profile=scenario_profile,
                    source_kind=request.source_kind.value,
                    allowed_tools=request.allowed_tools,
                    seed=request.seed,
                )
                if not hmac.compare_digest(
                    parent_contract, lineage_contract_sha256
                ) or not hmac.compare_digest(child_contract, lineage_contract_sha256):
                    raise ConflictError(
                        "re-verification task changed the inherited execution contract"
                    )
                parent_edge_row = connection.execute(
                    "SELECT * FROM task_lineage WHERE child_task_id = ?",
                    (parent.task_id,),
                ).fetchone()
                if parent_edge_row is not None:
                    parent_edge = self._lineage_edge(parent_edge_row)
            elif lineage_contract_sha256 is not None or lineage_note is not None:
                raise ValueError("lineage parent is required")
            if idempotency_key:
                existing = connection.execute(
                    """
                    SELECT * FROM agent_tasks
                    WHERE project_id = ? AND idempotency_key = ?
                    """,
                    (request.project_id, idempotency_key),
                ).fetchone()
                if existing is not None:
                    if str(existing["request_sha256"]) != request_sha256:
                        raise ConflictError(
                            "idempotency key was already used with a different request"
                        )
                    existing_edge_row = connection.execute(
                        "SELECT * FROM task_lineage WHERE child_task_id = ?",
                        (str(existing["task_id"]),),
                    ).fetchone()
                    if lineage_parent_task_id is not None:
                        if existing_edge_row is None:
                            raise ConflictError(
                                "idempotent re-verification task lost its lineage edge"
                            )
                        existing_edge = self._lineage_edge(existing_edge_row)
                        if (
                            existing_edge.parent_task_id != lineage_parent_task_id
                            or existing_edge.contract_sha256 != lineage_contract_sha256
                        ):
                            raise ConflictError(
                                "idempotency key was already used for another lineage"
                            )
                    elif existing_edge_row is not None:
                        raise ConflictError(
                            "idempotency key resolves to a re-verification task"
                        )
                    return self._task(existing), False
            connection.execute(
                """
                INSERT INTO agent_tasks (
                    task_id, workspace_id, project_id, created_by, goal, seed,
                    scenario_profile, source_kind, source_id,
                    plan_approval_required, allowed_tools_json, request_sha256,
                    idempotency_key, execution_status, current_phase, created_at,
                    updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    task_id,
                    workspace_id,
                    request.project_id,
                    actor_user_id,
                    request.goal,
                    request.seed,
                    scenario_profile,
                    request.source_kind.value,
                    request.source_id,
                    int(request.plan_approval_required),
                    json.dumps(request.allowed_tools, ensure_ascii=False),
                    request_sha256,
                    idempotency_key,
                    TaskExecutionStatus.PLANNED.value,
                    "planned",
                    timestamp,
                    timestamp,
                ),
            )
            if parent is not None:
                root_task_id = (
                    parent_edge.root_task_id if parent_edge else parent.task_id
                )
                depth = parent_edge.depth + 1 if parent_edge else 1
                edge = seal_task_lineage_edge(
                    child_task_id=task_id,
                    parent_task_id=parent.task_id,
                    root_task_id=root_task_id,
                    depth=depth,
                    parent_request_sha256=parent.request_sha256,
                    parent_evidence_sha256=parent.evidence_sha256,
                    contract_sha256=lineage_contract_sha256,
                    created_by=actor_user_id,
                    note=lineage_note,
                    created_at=timestamp,
                )
                connection.execute(
                    """
                    INSERT INTO task_lineage (
                        child_task_id, parent_task_id, root_task_id, relation,
                        depth, parent_request_sha256, parent_evidence_sha256,
                        contract_sha256, created_by, note, created_at, edge_sha256
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        edge.child_task_id,
                        edge.parent_task_id,
                        edge.root_task_id,
                        edge.relation,
                        edge.depth,
                        edge.parent_request_sha256,
                        edge.parent_evidence_sha256,
                        edge.contract_sha256,
                        edge.created_by,
                        edge.note,
                        edge.created_at,
                        edge.edge_sha256,
                    ),
                )
            row = connection.execute(
                "SELECT * FROM agent_tasks WHERE task_id = ?", (task_id,)
            ).fetchone()
        assert row is not None
        return self._task(row), True

    def get_task(self, actor_user_id: str, task_id: str) -> TaskRecord:
        with self._connection() as connection:
            row = connection.execute(
                "SELECT * FROM agent_tasks WHERE task_id = ?", (task_id,)
            ).fetchone()
            if row is None:
                raise NotFoundError("task not found")
            self._require_membership(
                connection, str(row["workspace_id"]), actor_user_id
            )
        return self._task(row)

    def claim_incident_command(
        self,
        actor_user_id: str,
        *,
        command_id: str,
        task_id: str,
        scope_key: str,
        operation: IncidentCommandOperation | str,
        idempotency_key_sha256: str,
        request_sha256: str,
        expected_case_sha256: str | None,
    ) -> tuple[IncidentCommandRecord, bool]:
        """Atomically admit one incident mutation or return its exact prior claim.

        ``RECORD_DECISION`` and ``RESUME_CASE`` are single-writer operations for
        the same task, scope, operation, and expected case digest. ``CREATE_CASE``
        deliberately relies only on command/idempotency binding because identical
        evidence may validly resolve to the same immutable case.
        """

        if not command_id.strip() or len(command_id) > 160:
            raise ValueError("command_id must be non-empty and at most 160 characters")
        if not task_id.strip() or not scope_key.strip() or len(scope_key) > 240:
            raise ValueError("task_id and scope_key must be non-empty")
        operation = IncidentCommandOperation(operation)
        _require_sha256(idempotency_key_sha256, field_name="idempotency_key_sha256")
        _require_sha256(request_sha256, field_name="request_sha256")
        if expected_case_sha256 is not None:
            _require_sha256(expected_case_sha256, field_name="expected_case_sha256")
        if operation is IncidentCommandOperation.CREATE_CASE:
            if expected_case_sha256 is not None:
                raise ValueError("CREATE_CASE must not bind an existing case digest")
        elif expected_case_sha256 is None:
            raise ValueError(f"{operation.value} requires expected_case_sha256")

        admission_sha256 = _incident_command_admission_sha256(
            command_id=command_id,
            task_id=task_id,
            scope_key=scope_key,
            operation=operation,
            actor_user_id=actor_user_id,
            idempotency_key_sha256=idempotency_key_sha256,
            request_sha256=request_sha256,
            expected_case_sha256=expected_case_sha256,
        )
        timestamp = _now()
        with self._connection(immediate=True) as connection:
            task_row = connection.execute(
                "SELECT workspace_id FROM agent_tasks WHERE task_id = ?", (task_id,)
            ).fetchone()
            if task_row is None:
                raise NotFoundError("task not found")
            self._require_membership(
                connection, str(task_row["workspace_id"]), actor_user_id
            )

            command_row = connection.execute(
                "SELECT * FROM incident_commands WHERE command_id = ?",
                (command_id,),
            ).fetchone()
            if command_row is not None:
                existing = self._incident_command(command_row)
                if hmac.compare_digest(existing.admission_sha256, admission_sha256):
                    return existing, False
                raise IncidentCommandBindingConflict(
                    "command_id is already bound to another incident command"
                )

            idempotency_row = connection.execute(
                """
                SELECT * FROM incident_commands
                WHERE task_id = ? AND scope_key = ? AND operation = ?
                  AND actor_user_id = ? AND idempotency_key_sha256 = ?
                """,
                (
                    task_id,
                    scope_key,
                    operation.value,
                    actor_user_id,
                    idempotency_key_sha256,
                ),
            ).fetchone()
            if idempotency_row is not None:
                raise IncidentCommandBindingConflict(
                    "idempotency key is already bound to another command_id"
                )

            if operation in {
                IncidentCommandOperation.RECORD_DECISION,
                IncidentCommandOperation.RESUME_CASE,
            }:
                occupied = connection.execute(
                    """
                    SELECT command_id FROM incident_commands
                    WHERE task_id = ? AND scope_key = ? AND operation = ?
                      AND expected_case_sha256 = ?
                      AND status IN ('EXECUTING', 'COMPLETED', 'UNCERTAIN')
                    LIMIT 1
                    """,
                    (
                        task_id,
                        scope_key,
                        operation.value,
                        expected_case_sha256,
                    ),
                ).fetchone()
                if occupied is not None:
                    raise IncidentCommandScopeOccupied(
                        "incident effect scope is already owned by another command"
                    )

            connection.execute(
                """
                INSERT INTO incident_commands (
                    command_id, task_id, scope_key, operation, actor_user_id,
                    idempotency_key_sha256, request_sha256,
                    expected_case_sha256, admission_sha256, status,
                    resource_type, resource_id, resource_sha256,
                    error_code, error_message, created_at, updated_at,
                    completed_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, NULL, NULL, NULL,
                          NULL, NULL, ?, ?, NULL)
                """,
                (
                    command_id,
                    task_id,
                    scope_key,
                    operation.value,
                    actor_user_id,
                    idempotency_key_sha256,
                    request_sha256,
                    expected_case_sha256,
                    admission_sha256,
                    IncidentCommandStatus.EXECUTING.value,
                    timestamp,
                    timestamp,
                ),
            )
            stored = connection.execute(
                "SELECT * FROM incident_commands WHERE command_id = ?",
                (command_id,),
            ).fetchone()
        assert stored is not None
        return self._incident_command(stored), True

    def get_incident_command(
        self, actor_user_id: str, task_id: str, command_id: str
    ) -> IncidentCommandRecord:
        """Read a command through the owning task's workspace boundary."""

        with self._connection() as connection:
            task_row = connection.execute(
                "SELECT workspace_id FROM agent_tasks WHERE task_id = ?", (task_id,)
            ).fetchone()
            if task_row is None:
                raise NotFoundError("task not found")
            self._require_membership(
                connection, str(task_row["workspace_id"]), actor_user_id
            )
            row = connection.execute(
                """
                SELECT * FROM incident_commands
                WHERE task_id = ? AND command_id = ?
                """,
                (task_id, command_id),
            ).fetchone()
        if row is None:
            raise NotFoundError("incident command not found")
        return self._incident_command(row)

    def get_completed_incident_case_binding(
        self,
        actor_user_id: str,
        task_id: str,
        case_id: str,
    ) -> IncidentCommandRecord | None:
        """Return the immutable command result that first bound a persisted case."""

        with self._connection() as connection:
            task_row = connection.execute(
                "SELECT workspace_id FROM agent_tasks WHERE task_id = ?", (task_id,)
            ).fetchone()
            if task_row is None:
                raise NotFoundError("task not found")
            self._require_membership(
                connection, str(task_row["workspace_id"]), actor_user_id
            )
            rows = connection.execute(
                """
                SELECT * FROM incident_commands
                WHERE task_id = ? AND status = 'COMPLETED'
                  AND resource_type = 'incident_case' AND resource_id = ?
                ORDER BY completed_at, command_id
                """,
                (task_id, case_id),
            ).fetchall()
        if not rows:
            return None
        records = [self._incident_command(row) for row in rows]
        bound_digests = {record.resource_sha256 for record in records}
        if len(bound_digests) != 1:
            raise ConflictError(
                "completed incident commands disagree on the case resource digest"
            )
        return records[0]

    def finish_incident_command(
        self,
        actor_user_id: str,
        task_id: str,
        command_id: str,
        *,
        status: IncidentCommandStatus | str,
        resource_type: str | None = None,
        resource_id: str | None = None,
        resource_sha256: str | None = None,
        error_code: str | None = None,
        error_message: str | None = None,
    ) -> IncidentCommandRecord:
        """Finish an executing command with one proven outcome."""

        status = IncidentCommandStatus(status)
        if status not in {
            IncidentCommandStatus.COMPLETED,
            IncidentCommandStatus.REJECTED,
        }:
            raise ValueError("finish status must be COMPLETED or REJECTED")
        resources = (resource_type, resource_id, resource_sha256)
        if status is IncidentCommandStatus.COMPLETED:
            if (
                not all(resources)
                or error_code is not None
                or error_message is not None
            ):
                raise ValueError(
                    "COMPLETED requires all resource fields and forbids error fields"
                )
            assert resource_sha256 is not None
            _require_sha256(resource_sha256, field_name="resource_sha256")
        elif any(value is not None for value in resources) or not error_code:
            raise ValueError("REJECTED requires error_code and forbids resource fields")

        timestamp = _now()
        with self._connection(immediate=True) as connection:
            task_row = connection.execute(
                "SELECT workspace_id FROM agent_tasks WHERE task_id = ?", (task_id,)
            ).fetchone()
            if task_row is None:
                raise NotFoundError("task not found")
            self._require_membership(
                connection, str(task_row["workspace_id"]), actor_user_id
            )
            row = connection.execute(
                """
                SELECT * FROM incident_commands
                WHERE task_id = ? AND command_id = ?
                """,
                (task_id, command_id),
            ).fetchone()
            if row is None:
                raise NotFoundError("incident command not found")
            existing = self._incident_command(row)
            expected_terminal = (
                status,
                resource_type,
                resource_id,
                resource_sha256,
                error_code,
                error_message,
            )
            observed_terminal = (
                existing.status,
                existing.resource_type,
                existing.resource_id,
                existing.resource_sha256,
                existing.error_code,
                existing.error_message,
            )
            if existing.status is not IncidentCommandStatus.EXECUTING:
                if observed_terminal == expected_terminal:
                    return existing
                raise IncidentCommandStateConflict(
                    "incident command already has another terminal outcome"
                )
            connection.execute(
                """
                UPDATE incident_commands
                SET status = ?, resource_type = ?, resource_id = ?,
                    resource_sha256 = ?, error_code = ?, error_message = ?,
                    updated_at = ?, completed_at = ?
                WHERE task_id = ? AND command_id = ? AND status = 'EXECUTING'
                """,
                (
                    status.value,
                    resource_type,
                    resource_id,
                    resource_sha256,
                    error_code,
                    error_message,
                    timestamp,
                    timestamp,
                    task_id,
                    command_id,
                ),
            )
            stored = connection.execute(
                "SELECT * FROM incident_commands WHERE command_id = ?",
                (command_id,),
            ).fetchone()
        assert stored is not None
        return self._incident_command(stored)

    def mark_incident_command_uncertain(
        self,
        actor_user_id: str,
        task_id: str,
        command_id: str,
        *,
        error_code: str,
        error_message: str | None = None,
    ) -> IncidentCommandRecord:
        """Fail closed when an executing command's external outcome is unknown."""

        if not error_code.strip():
            raise ValueError("UNCERTAIN requires a non-empty error_code")
        timestamp = _now()
        with self._connection(immediate=True) as connection:
            task_row = connection.execute(
                "SELECT workspace_id FROM agent_tasks WHERE task_id = ?", (task_id,)
            ).fetchone()
            if task_row is None:
                raise NotFoundError("task not found")
            self._require_membership(
                connection, str(task_row["workspace_id"]), actor_user_id
            )
            row = connection.execute(
                """
                SELECT * FROM incident_commands
                WHERE task_id = ? AND command_id = ?
                """,
                (task_id, command_id),
            ).fetchone()
            if row is None:
                raise NotFoundError("incident command not found")
            existing = self._incident_command(row)
            if existing.status is not IncidentCommandStatus.EXECUTING:
                if (
                    existing.status is IncidentCommandStatus.UNCERTAIN
                    and existing.error_code == error_code
                    and existing.error_message == error_message
                ):
                    return existing
                raise IncidentCommandStateConflict(
                    "incident command cannot transition to UNCERTAIN"
                )
            connection.execute(
                """
                UPDATE incident_commands
                SET status = 'UNCERTAIN', error_code = ?, error_message = ?,
                    updated_at = ?, completed_at = ?
                WHERE task_id = ? AND command_id = ? AND status = 'EXECUTING'
                """,
                (
                    error_code,
                    error_message,
                    timestamp,
                    timestamp,
                    task_id,
                    command_id,
                ),
            )
            stored = connection.execute(
                "SELECT * FROM incident_commands WHERE command_id = ?",
                (command_id,),
            ).fetchone()
        assert stored is not None
        return self._incident_command(stored)

    def get_task_unscoped(self, task_id: str) -> TaskRecord:
        with self._connection() as connection:
            row = connection.execute(
                "SELECT * FROM agent_tasks WHERE task_id = ?", (task_id,)
            ).fetchone()
        if row is None:
            raise NotFoundError("task not found")
        return self._task(row)

    def list_tasks(
        self,
        actor_user_id: str,
        *,
        workspace_id: str | None = None,
        project_id: str | None = None,
        limit: int = 100,
    ) -> list[TaskRecord]:
        clauses = ["m.user_id = ?"]
        parameters: list[Any] = [actor_user_id]
        if workspace_id is not None:
            clauses.append("t.workspace_id = ?")
            parameters.append(workspace_id)
        if project_id is not None:
            clauses.append("t.project_id = ?")
            parameters.append(project_id)
        parameters.append(max(1, min(limit, 200)))
        query = f"""
            SELECT t.* FROM agent_tasks t
            JOIN workspace_members m ON m.workspace_id = t.workspace_id
            WHERE {" AND ".join(clauses)}
            ORDER BY t.created_at DESC, t.task_id DESC
            LIMIT ?
        """
        with self._connection() as connection:
            rows = connection.execute(query, parameters).fetchall()
        return [self._task(row) for row in rows]

    def get_task_lineage(
        self, actor_user_id: str, task_id: str
    ) -> tuple[list[TaskRecord], list[TaskLineageEdge]]:
        """Read one complete run family through the actor's workspace boundary."""

        with self._connection() as connection:
            focus_row = connection.execute(
                "SELECT * FROM agent_tasks WHERE task_id = ?", (task_id,)
            ).fetchone()
            if focus_row is None:
                raise NotFoundError("task not found")
            self._require_membership(
                connection, str(focus_row["workspace_id"]), actor_user_id
            )
            focus_edge_row = connection.execute(
                "SELECT * FROM task_lineage WHERE child_task_id = ?", (task_id,)
            ).fetchone()
            root_task_id = (
                str(focus_edge_row["root_task_id"])
                if focus_edge_row is not None
                else task_id
            )
            task_rows = connection.execute(
                """
                SELECT t.* FROM agent_tasks t
                WHERE t.task_id = ? OR EXISTS (
                    SELECT 1 FROM task_lineage l
                    WHERE l.root_task_id = ? AND l.child_task_id = t.task_id
                )
                ORDER BY t.created_at, t.task_id
                """,
                (root_task_id, root_task_id),
            ).fetchall()
            edge_rows = connection.execute(
                """
                SELECT * FROM task_lineage
                WHERE root_task_id = ?
                ORDER BY depth, created_at, child_task_id
                """,
                (root_task_id,),
            ).fetchall()
        tasks = [self._task(row) for row in task_rows]
        edges = [self._lineage_edge(row) for row in edge_rows]
        if task_id not in {task.task_id for task in tasks}:
            raise ConflictError("task lineage projection lost the focus task")
        return tasks, edges

    def transition_task(
        self,
        task_id: str,
        target: TaskExecutionStatus,
        *,
        current_phase: str,
        fields: dict[str, Any] | None = None,
    ) -> TaskRecord:
        updates = dict(fields or {})
        allowed_fields = {
            "initial_decision",
            "final_decision",
            "runtime_status",
            "artifact_root_rel",
            "trace_rel",
            "trace_sha256",
            "evidence_zip_rel",
            "evidence_sha256",
            "error_code",
            "error_message",
            "started_at",
            "completed_at",
        }
        if not set(updates) <= allowed_fields:
            raise ValueError("unsupported task update field")
        with self._connection(immediate=True) as connection:
            row = connection.execute(
                "SELECT * FROM agent_tasks WHERE task_id = ?", (task_id,)
            ).fetchone()
            if row is None:
                raise NotFoundError("task not found")
            current = TaskExecutionStatus(str(row["execution_status"]))
            if target not in _TRANSITIONS[current]:
                raise InvalidTransitionError(f"cannot transition {current} to {target}")
            assignments = [
                "execution_status = ?",
                "current_phase = ?",
                "updated_at = ?",
            ]
            values: list[Any] = [target.value, current_phase, _now()]
            for key, value in updates.items():
                assignments.append(f"{key} = ?")
                values.append(value)
            values.append(task_id)
            connection.execute(
                f"UPDATE agent_tasks SET {', '.join(assignments)} WHERE task_id = ?",
                values,
            )
            updated = connection.execute(
                "SELECT * FROM agent_tasks WHERE task_id = ?", (task_id,)
            ).fetchone()
        assert updated is not None
        return self._task(updated)

    def claim_task(self, task_id: str) -> bool:
        timestamp = _now()
        with self._connection(immediate=True) as connection:
            cursor = connection.execute(
                """
                UPDATE agent_tasks
                SET execution_status = ?, current_phase = 'running',
                    started_at = ?, updated_at = ?
                WHERE task_id = ? AND execution_status = ?
                  AND (
                    plan_approval_required = 0 OR EXISTS (
                        SELECT 1 FROM task_interventions i
                        WHERE i.task_id = agent_tasks.task_id AND i.action = ?
                          AND i.approval_binding_json IS NOT NULL
                    )
                  )
                """,
                (
                    TaskExecutionStatus.RUNNING.value,
                    timestamp,
                    timestamp,
                    task_id,
                    TaskExecutionStatus.PLANNED.value,
                    TaskInterventionAction.APPROVE_PLAN.value,
                ),
            )
        return cursor.rowcount == 1

    def record_intervention(
        self,
        actor_user_id: str,
        task_id: str,
        request: TaskInterventionRequest,
        *,
        plan_sha256: str,
        expected_snapshot_sha256: str,
        approval_binding: TaskPlanApprovalBinding | None = None,
    ) -> TaskInterventionRecord:
        """Append one human action and atomically apply any state transition."""

        intervention_id = _new_id("int")
        created_at = _now()
        with self._connection(immediate=True) as connection:
            row = connection.execute(
                "SELECT * FROM agent_tasks WHERE task_id = ?", (task_id,)
            ).fetchone()
            if row is None:
                raise NotFoundError("task not found")
            self._require_membership(
                connection, str(row["workspace_id"]), actor_user_id
            )
            task = self._task(row)
            action = request.action
            if action is TaskInterventionAction.APPROVE_PLAN:
                if approval_binding is None:
                    raise ConflictError(
                        "plan approval requires a sealed approval binding"
                    )
                if (
                    approval_binding.plan_sha256 != plan_sha256
                    or approval_binding.before_snapshot_sha256
                    != expected_snapshot_sha256
                    or approval_binding.request_sha256 != task.request_sha256
                ):
                    raise ConflictError("plan approval binding does not match the task")
            elif approval_binding is not None:
                raise ConflictError("only plan approval may carry an approval binding")
            if action in {
                TaskInterventionAction.APPROVE_PLAN,
                TaskInterventionAction.CANCEL_PLAN,
            }:
                if task.execution_status is not TaskExecutionStatus.PLANNED:
                    raise ConflictError("plan intervention requires a planned task")
                existing = connection.execute(
                    """
                    SELECT action FROM task_interventions
                    WHERE task_id = ? AND action IN (?, ?)
                    ORDER BY sequence LIMIT 1
                    """,
                    (
                        task_id,
                        TaskInterventionAction.APPROVE_PLAN.value,
                        TaskInterventionAction.CANCEL_PLAN.value,
                    ),
                ).fetchone()
                if existing is not None:
                    raise ConflictError("the plan already has a terminal intervention")
                if (
                    action is TaskInterventionAction.APPROVE_PLAN
                    and not task.plan_approval_required
                ):
                    raise ConflictError("this task does not require plan approval")
            elif action is TaskInterventionAction.REQUEST_CHANGES:
                if task.execution_status not in {
                    TaskExecutionStatus.COMPLETED,
                    TaskExecutionStatus.FAILED,
                }:
                    raise ConflictError(
                        "change request requires a completed or failed task"
                    )
            elif task.execution_status is not TaskExecutionStatus.COMPLETED:
                raise ConflictError("result acknowledgement requires a completed task")

            before_snapshot_sha256 = self.task_snapshot_sha256(task)
            if before_snapshot_sha256 != expected_snapshot_sha256:
                raise ConflictError(
                    "task state changed before intervention was recorded"
                )
            sequence = int(
                connection.execute(
                    """
                    SELECT COALESCE(MAX(sequence), 0) + 1
                    FROM task_interventions WHERE task_id = ?
                    """,
                    (task_id,),
                ).fetchone()[0]
            )
            connection.execute(
                """
                INSERT INTO task_interventions (
                    intervention_id, task_id, sequence, actor_user_id, action,
                    note, before_status, before_phase, before_snapshot_sha256,
                    plan_sha256, approval_binding_json, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    intervention_id,
                    task_id,
                    sequence,
                    actor_user_id,
                    action.value,
                    request.note,
                    task.execution_status.value,
                    task.current_phase,
                    before_snapshot_sha256,
                    plan_sha256,
                    (
                        canonical_json_text(
                            approval_binding.model_dump(mode="json"),
                            trailing_newline=False,
                        )
                        if approval_binding is not None
                        else None
                    ),
                    created_at,
                ),
            )
            if action is TaskInterventionAction.CANCEL_PLAN:
                connection.execute(
                    """
                    UPDATE agent_tasks
                    SET execution_status = ?, current_phase = 'cancelled',
                        completed_at = ?, updated_at = ?
                    WHERE task_id = ? AND execution_status = ?
                    """,
                    (
                        TaskExecutionStatus.CANCELLED.value,
                        created_at,
                        created_at,
                        task_id,
                        TaskExecutionStatus.PLANNED.value,
                    ),
                )
            stored = connection.execute(
                "SELECT * FROM task_interventions WHERE intervention_id = ?",
                (intervention_id,),
            ).fetchone()
        assert stored is not None
        return self._intervention(stored)

    def list_interventions(
        self, actor_user_id: str, task_id: str
    ) -> list[TaskInterventionRecord]:
        self.get_task(actor_user_id, task_id)
        with self._connection() as connection:
            rows = connection.execute(
                """
                SELECT * FROM task_interventions
                WHERE task_id = ? ORDER BY sequence
                """,
                (task_id,),
            ).fetchall()
        return [self._intervention(row) for row in rows]

    def set_verifying_if_running(self, task_id: str) -> None:
        with self._connection(immediate=True) as connection:
            connection.execute(
                """
                UPDATE agent_tasks SET execution_status = ?, current_phase = 'verification',
                    updated_at = ? WHERE task_id = ? AND execution_status = ?
                """,
                (
                    TaskExecutionStatus.VERIFYING.value,
                    _now(),
                    task_id,
                    TaskExecutionStatus.RUNNING.value,
                ),
            )

    def append_event(self, task_id: str, event: Any) -> None:
        payload = event.model_dump(mode="json")
        with self._connection() as connection:
            connection.execute(
                """
                INSERT INTO task_events
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    task_id,
                    int(payload["sequence"]),
                    str(payload["phase"]),
                    str(payload["stage"]),
                    str(payload["status"]),
                    str(payload["summary"]),
                    json.dumps(payload, ensure_ascii=False, sort_keys=True),
                    _now(),
                ),
            )

    def reconcile_events(self, task_id: str, events: list[Any]) -> None:
        """Validate an existing event prefix and append only a missing suffix."""

        canonical_events: list[dict[str, Any]] = []
        timestamp = _now()
        for expected_sequence, event in enumerate(events, start=1):
            payload = event.model_dump(mode="json")
            sequence = int(payload["sequence"])
            if sequence != expected_sequence:
                raise ConflictError(
                    "canonical task events must be contiguous and ordered"
                )
            canonical_json_text(payload, trailing_newline=False)
            canonical_events.append(payload)

        with self._connection(immediate=True) as connection:
            existing_rows = connection.execute(
                "SELECT * FROM task_events WHERE task_id = ? ORDER BY sequence",
                (task_id,),
            ).fetchall()
            if len(existing_rows) > len(canonical_events):
                raise ConflictError(
                    "canonical task events cannot remove existing events"
                )

            for expected_sequence, row in enumerate(existing_rows, start=1):
                payload = canonical_events[expected_sequence - 1]
                expected_projection = (
                    int(payload["sequence"]),
                    str(payload["phase"]),
                    str(payload["stage"]),
                    str(payload["status"]),
                    str(payload["summary"]),
                )
                stored_projection = (
                    int(row["sequence"]),
                    str(row["phase"]),
                    str(row["stage"]),
                    str(row["status"]),
                    str(row["summary"]),
                )
                if stored_projection[0] != expected_sequence:
                    raise ConflictError(
                        "stored task events are not contiguous and ordered"
                    )
                try:
                    stored_payload = _strict_canonical_json(str(row["payload_json"]))
                except (json.JSONDecodeError, TypeError, ValueError) as exc:
                    raise ConflictError("stored task event payload is invalid") from exc
                expected_payload = canonical_json_text(payload, trailing_newline=False)
                if (
                    stored_projection != expected_projection
                    or stored_payload != expected_payload
                ):
                    raise ConflictError(
                        "canonical task event conflicts with stored event"
                    )

            missing_rows = [
                (
                    task_id,
                    int(payload["sequence"]),
                    str(payload["phase"]),
                    str(payload["stage"]),
                    str(payload["status"]),
                    str(payload["summary"]),
                    json.dumps(payload, ensure_ascii=False, sort_keys=True),
                    timestamp,
                )
                for payload in canonical_events[len(existing_rows) :]
            ]
            if missing_rows:
                connection.executemany(
                    "INSERT INTO task_events VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                    missing_rows,
                )

    def list_events(self, actor_user_id: str, task_id: str) -> list[TaskEventRecord]:
        self.get_task(actor_user_id, task_id)
        with self._connection() as connection:
            rows = connection.execute(
                "SELECT * FROM task_events WHERE task_id = ? ORDER BY sequence",
                (task_id,),
            ).fetchall()
        return [TaskEventRecord(**dict(row)) for row in rows]

    def recover_interrupted(self) -> int:
        timestamp = _now()
        with self._connection(immediate=True) as connection:
            cursor = connection.execute(
                """
                UPDATE agent_tasks SET execution_status = ?, current_phase = 'interrupted',
                    error_code = 'interrupted',
                    error_message = 'The local service stopped before the run completed.',
                    completed_at = ?, updated_at = ?
                WHERE execution_status IN (?, ?)
                """,
                (
                    TaskExecutionStatus.FAILED.value,
                    timestamp,
                    timestamp,
                    TaskExecutionStatus.RUNNING.value,
                    TaskExecutionStatus.VERIFYING.value,
                ),
            )
        return cursor.rowcount


__all__ = [
    "ConflictError",
    "IncidentCommandBindingConflict",
    "IncidentCommandOperation",
    "IncidentCommandRecord",
    "IncidentCommandScopeOccupied",
    "IncidentCommandStateConflict",
    "IncidentCommandStatus",
    "InvalidTransitionError",
    "LocalSourceBinding",
    "NotFoundError",
    "ProductStoreError",
    "TaskStore",
]
