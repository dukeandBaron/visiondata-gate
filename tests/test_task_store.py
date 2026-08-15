from __future__ import annotations

import json
import sqlite3
from pathlib import Path

import pytest

from visiondata_gate.product_models import (
    CreateProjectRequest,
    CreateTaskRequest,
    CreateUserRequest,
    CreateWorkspaceRequest,
    TaskExecutionStatus,
)
from visiondata_gate.product_service import ProductService
from visiondata_gate.task_store import (
    ConflictError,
    InvalidTransitionError,
    NotFoundError,
    TaskStore,
)


def _tenant(service: ProductService, name: str = "Owner") -> tuple[str, str, str]:
    user = service.create_user(CreateUserRequest(display_name=name))
    workspace = service.create_workspace(
        CreateWorkspaceRequest(name=f"{name} Workspace", owner_user_id=user.user_id)
    )
    project = service.create_project(
        user.user_id,
        CreateProjectRequest(
            workspace_id=workspace.workspace_id,
            name=f"{name} Project",
        ),
    )
    return user.user_id, workspace.workspace_id, project.project_id


def test_store_enables_foreign_keys_wal_and_persists(tmp_path: Path) -> None:
    path = tmp_path / "product.sqlite3"
    service = ProductService(path.parent, recover_interrupted=False)
    actor, workspace_id, project_id = _tenant(service)
    service.close()

    reopened = TaskStore(path)
    assert reopened.get_user(actor).display_name == "Owner"
    assert reopened.list_projects(actor, workspace_id)[0].project_id == project_id
    connection = sqlite3.connect(path)
    try:
        assert connection.execute("PRAGMA journal_mode").fetchone()[0] == "wal"
    finally:
        connection.close()


def test_workspace_creation_is_atomic_when_owner_missing(tmp_path: Path) -> None:
    store = TaskStore(tmp_path / "product.sqlite3")
    with pytest.raises(NotFoundError):
        store.create_workspace(
            CreateWorkspaceRequest(name="Invisible", owner_user_id="usr_missing")
        )
    assert store.list_users() == []


def test_cross_workspace_objects_are_hidden(tmp_path: Path) -> None:
    service = ProductService(tmp_path / "product", recover_interrupted=False)
    actor_a, workspace_a, project_a = _tenant(service, "A")
    actor_b, workspace_b, project_b = _tenant(service, "B")

    assert service.list_projects(actor_a, workspace_a)[0].project_id == project_a
    assert service.list_projects(actor_b, workspace_b)[0].project_id == project_b
    with pytest.raises(NotFoundError):
        service.get_project(actor_b, project_a)
    with pytest.raises(NotFoundError):
        service.list_projects(actor_b, workspace_a)


def test_idempotency_reuses_same_request_and_rejects_conflict(tmp_path: Path) -> None:
    service = ProductService(tmp_path / "product", recover_interrupted=False)
    actor, _, project_id = _tenant(service)
    request = CreateTaskRequest(
        project_id=project_id,
        goal="审核本地合成数据并交付可复核证据。",
    )
    first = service.create_task(
        actor, request, idempotency_key="demo-001", auto_start=False
    )
    second = service.create_task(
        actor, request, idempotency_key="demo-001", auto_start=False
    )
    assert first.task_id == second.task_id
    assert second.execution_status is TaskExecutionStatus.PLANNED

    changed = request.model_copy(update={"seed": request.seed + 1})
    with pytest.raises(ConflictError):
        service.create_task(
            actor, changed, idempotency_key="demo-001", auto_start=False
        )


def test_task_inputs_are_frozen_and_status_transitions_are_guarded(
    tmp_path: Path,
) -> None:
    service = ProductService(tmp_path / "product", recover_interrupted=False)
    actor, _, project_id = _tenant(service)
    tools = ["image_quality"]
    request = CreateTaskRequest(
        project_id=project_id,
        goal="执行负路径检查并确保缺证据时安全暂缓。",
        allowed_tools=tools,
    )
    task = service.create_task(actor, request, auto_start=False)
    tools.append("coverage_matrix")

    frozen = service.get_task(actor, task.task_id)
    assert frozen.allowed_tools == ["image_quality", "governance_audit"]
    assert frozen.execution_status is TaskExecutionStatus.PLANNED
    with pytest.raises(InvalidTransitionError):
        service.store.transition_task(
            task.task_id,
            TaskExecutionStatus.COMPLETED,
            current_phase="completed",
        )


def test_list_tasks_is_scoped_to_membership(tmp_path: Path) -> None:
    service = ProductService(tmp_path / "product", recover_interrupted=False)
    actor_a, workspace_a, project_a = _tenant(service, "A")
    actor_b, workspace_b, project_b = _tenant(service, "B")
    task_a = service.create_task(
        actor_a,
        CreateTaskRequest(project_id=project_a, goal="为 A 工作区执行数据审核任务。"),
        auto_start=False,
    )
    task_b = service.create_task(
        actor_b,
        CreateTaskRequest(project_id=project_b, goal="为 B 工作区执行数据审核任务。"),
        auto_start=False,
    )

    assert [item.task_id for item in service.list_tasks(actor_a)] == [task_a.task_id]
    assert [item.task_id for item in service.list_tasks(actor_b)] == [task_b.task_id]
    assert service.list_tasks(actor_a, workspace_id=workspace_b) == []
    with pytest.raises(NotFoundError):
        service.get_task(actor_b, task_a.task_id)


def test_recover_interrupted_never_promotes_stale_runs(tmp_path: Path) -> None:
    service = ProductService(tmp_path / "product", recover_interrupted=False)
    actor, _, project_id = _tenant(service)
    task = service.create_task(
        actor,
        CreateTaskRequest(project_id=project_id, goal="模拟服务中断前的运行状态。"),
        auto_start=False,
    )
    assert service.store.claim_task(task.task_id)
    assert service.store.recover_interrupted() == 1
    recovered = service.get_task(actor, task.task_id)
    assert recovered.execution_status is TaskExecutionStatus.FAILED
    assert recovered.error_code == "interrupted"


def test_duplicate_event_sequence_cannot_rewrite_audit_projection(
    tmp_path: Path,
) -> None:
    from visiondata_gate.runtime_models import RuntimeEvent, RuntimeStage, RuntimeStatus

    service = ProductService(tmp_path / "product", recover_interrupted=False)
    actor, _, project_id = _tenant(service)
    task = service.create_task(
        actor,
        CreateTaskRequest(project_id=project_id, goal="验证事件序号不可被静默覆盖。"),
        auto_start=False,
    )
    event = RuntimeEvent(
        sequence=1,
        phase="initial",
        stage=RuntimeStage.INTAKE,
        actor="Task Trigger",
        action="accept",
        status=RuntimeStatus.SUCCESS,
        summary="原始事件",
    )
    service.store.append_event(task.task_id, event)
    with pytest.raises(sqlite3.IntegrityError):
        service.store.append_event(
            task.task_id, event.model_copy(update={"summary": "篡改事件"})
        )
    assert service.list_events(actor, task.task_id)[0].summary == "原始事件"


def test_reconcile_events_only_appends_a_matching_canonical_suffix(
    tmp_path: Path,
) -> None:
    from visiondata_gate.runtime_models import RuntimeEvent, RuntimeStage, RuntimeStatus

    service = ProductService(tmp_path / "product", recover_interrupted=False)
    actor, _, project_id = _tenant(service)
    task = service.create_task(
        actor,
        CreateTaskRequest(project_id=project_id, goal="验证事件投影只能校验或追加。"),
        auto_start=False,
    )
    first = RuntimeEvent(
        sequence=1,
        phase="initial",
        stage=RuntimeStage.INTAKE,
        actor="Task Trigger",
        action="accept",
        status=RuntimeStatus.SUCCESS,
        summary="第一条规范事件",
    )
    second = RuntimeEvent(
        sequence=2,
        phase="verification",
        stage=RuntimeStage.VERIFY,
        actor="Verification",
        action="verify",
        status=RuntimeStatus.SUCCESS,
        summary="第二条规范事件",
    )
    service.store.append_event(task.task_id, first)
    with service.store._connection(immediate=True) as connection:
        original = connection.execute(
            "SELECT payload_json, created_at FROM task_events "
            "WHERE task_id = ? AND sequence = 1",
            (task.task_id,),
        ).fetchone()
        assert original is not None
        equivalent_json = json.dumps(
            json.loads(str(original["payload_json"])),
            ensure_ascii=False,
            indent=2,
        )
        connection.execute(
            "UPDATE task_events SET payload_json = ? "
            "WHERE task_id = ? AND sequence = 1",
            (equivalent_json, task.task_id),
        )

    service.store.reconcile_events(task.task_id, [first, second])
    service.store.reconcile_events(task.task_id, [first, second])
    projected = service.list_events(actor, task.task_id)
    assert [event.sequence for event in projected] == [1, 2]
    assert projected[0].payload_json == equivalent_json
    assert projected[0].created_at == str(original["created_at"])

    for conflicting_trace in (
        [first.model_copy(update={"summary": "改写第一条"}), second],
        [first.model_copy(update={"actor": "Impostor"}), second],
        [first],
        [second, first],
    ):
        with pytest.raises(ConflictError):
            service.store.reconcile_events(task.task_id, conflicting_trace)
        assert [
            event.summary for event in service.list_events(actor, task.task_id)
        ] == [
            "第一条规范事件",
            "第二条规范事件",
        ]


def test_reconcile_events_rejects_tampered_projection_or_stored_json(
    tmp_path: Path,
) -> None:
    from visiondata_gate.runtime_models import RuntimeEvent, RuntimeStage, RuntimeStatus

    service = ProductService(tmp_path / "product", recover_interrupted=False)
    actor, _, project_id = _tenant(service)
    task = service.create_task(
        actor,
        CreateTaskRequest(project_id=project_id, goal="验证存量事件异常时关闭失败。"),
        auto_start=False,
    )
    event = RuntimeEvent(
        sequence=1,
        phase="initial",
        stage=RuntimeStage.INTAKE,
        actor="Task Trigger",
        action="accept",
        status=RuntimeStatus.SUCCESS,
        summary="不可改写事件",
    )
    service.store.append_event(task.task_id, event)
    with service.store._connection() as connection:
        original = connection.execute(
            "SELECT phase, payload_json FROM task_events "
            "WHERE task_id = ? AND sequence = 1",
            (task.task_id,),
        ).fetchone()
    assert original is not None
    original_payload = str(original["payload_json"])

    tampered_rows = (
        ("verification", original_payload),
        (str(original["phase"]), "{"),
        (str(original["phase"]), '{"duration_ms": NaN}'),
        (
            str(original["phase"]),
            '{"sequence": 999,' + original_payload[1:],
        ),
    )
    for tampered_phase, tampered_payload in tampered_rows:
        with service.store._connection(immediate=True) as connection:
            connection.execute(
                "UPDATE task_events SET phase = ?, payload_json = ? "
                "WHERE task_id = ? AND sequence = 1",
                (tampered_phase, tampered_payload, task.task_id),
            )
        with pytest.raises(ConflictError):
            service.store.reconcile_events(task.task_id, [event])
        with service.store._connection(immediate=True) as connection:
            connection.execute(
                "UPDATE task_events SET phase = ?, payload_json = ? "
                "WHERE task_id = ? AND sequence = 1",
                (str(original["phase"]), original_payload, task.task_id),
            )

    service.store.reconcile_events(task.task_id, [event])
    assert service.list_events(actor, task.task_id)[0].summary == "不可改写事件"


def test_legacy_database_is_migrated_with_trace_digest_column(
    tmp_path: Path,
) -> None:
    database = tmp_path / "legacy.sqlite3"
    store = TaskStore(database)
    with store._connection(immediate=True) as connection:
        connection.execute("ALTER TABLE agent_tasks RENAME TO agent_tasks_current")
        connection.execute(
            """
            CREATE TABLE agent_tasks AS
            SELECT task_id, workspace_id, project_id, created_by, goal, seed,
                   scenario_profile, source_kind, allowed_tools_json,
                   request_sha256, idempotency_key, execution_status,
                   current_phase, initial_decision, final_decision,
                   runtime_status, artifact_root_rel, trace_rel,
                   evidence_zip_rel, evidence_sha256, error_code, error_message,
                   created_at, updated_at, started_at, completed_at
            FROM agent_tasks_current
            """
        )
        connection.execute("DROP TABLE agent_tasks_current")
    reopened = TaskStore(database)
    with reopened._connection() as connection:
        columns = {
            str(row[1]) for row in connection.execute("PRAGMA table_info(agent_tasks)")
        }
    assert "trace_sha256" in columns
