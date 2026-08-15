"""SQLite persistence for users, workspaces, projects, and immutable task inputs."""

from __future__ import annotations

import json
import sqlite3
import uuid
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import Any

from .evidence import canonical_json_text
from .product_models import (
    CreateProjectRequest,
    CreateTaskRequest,
    CreateUserRequest,
    CreateWorkspaceRequest,
    ProjectRecord,
    TaskEventRecord,
    TaskExecutionStatus,
    TaskRecord,
    UserRecord,
    WorkspaceRecord,
)


class ProductStoreError(RuntimeError):
    """Base persistence error with a stable public error code."""

    code = "store_error"


class NotFoundError(ProductStoreError):
    code = "not_found"


class ConflictError(ProductStoreError):
    code = "conflict"


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
    TaskExecutionStatus.ARCHIVED: set(),
}


def _now() -> str:
    from datetime import UTC, datetime

    return datetime.now(UTC).isoformat(timespec="milliseconds")


def _new_id(prefix: str) -> str:
    return f"{prefix}_{uuid.uuid4().hex[:20]}"


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
                CREATE INDEX IF NOT EXISTS idx_projects_workspace
                    ON projects(workspace_id);
                CREATE INDEX IF NOT EXISTS idx_tasks_project_created
                    ON agent_tasks(project_id, created_at DESC);
                CREATE INDEX IF NOT EXISTS idx_tasks_workspace_created
                    ON agent_tasks(workspace_id, created_at DESC);
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
            connection.execute("PRAGMA user_version = 1")

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
        return TaskRecord(**payload)

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

    def create_task(
        self,
        actor_user_id: str,
        request: CreateTaskRequest,
        *,
        scenario_profile: str,
        request_sha256: str,
        idempotency_key: str | None,
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
                    return self._task(existing), False
            connection.execute(
                """
                INSERT INTO agent_tasks (
                    task_id, workspace_id, project_id, created_by, goal, seed,
                    scenario_profile, source_kind, allowed_tools_json,
                    request_sha256, idempotency_key, execution_status,
                    current_phase, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
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
                    json.dumps(request.allowed_tools, ensure_ascii=False),
                    request_sha256,
                    idempotency_key,
                    TaskExecutionStatus.PLANNED.value,
                    "planned",
                    timestamp,
                    timestamp,
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
                """,
                (
                    TaskExecutionStatus.RUNNING.value,
                    timestamp,
                    timestamp,
                    task_id,
                    TaskExecutionStatus.PLANNED.value,
                ),
            )
        return cursor.rowcount == 1

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
    "InvalidTransitionError",
    "NotFoundError",
    "ProductStoreError",
    "TaskStore",
]
