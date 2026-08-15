from __future__ import annotations

from pathlib import Path

from visiondata_gate.product_models import (
    CreateProjectRequest,
    CreateTaskRequest,
    CreateUserRequest,
    CreateWorkspaceRequest,
    TaskExecutionStatus,
)
from visiondata_gate.product_service import ProductService


def test_real_runtime_is_reachable_through_product_service(tmp_path: Path) -> None:
    service = ProductService(tmp_path / "product", recover_interrupted=False)
    user = service.create_user(CreateUserRequest(display_name="E2E Operator"))
    workspace = service.create_workspace(
        CreateWorkspaceRequest(name="E2E Workspace", owner_user_id=user.user_id)
    )
    project = service.create_project(
        user.user_id,
        CreateProjectRequest(workspace_id=workspace.workspace_id, name="E2E Gate"),
    )
    task = service.create_task(
        user.user_id,
        CreateTaskRequest(
            project_id=project.project_id,
            goal="通过统一产品服务真实执行门禁、修复、复验和证据交付。",
            seed=20_260_809,
        ),
        auto_start=False,
    )

    completed = service.run_task_sync(task.task_id)
    assert completed.execution_status is TaskExecutionStatus.COMPLETED
    assert completed.initial_decision == "RECAPTURE"
    assert completed.final_decision == "PASS"
    assert completed.runtime_status == "success"
    assert completed.evidence_sha256
    assert service.trace_path(user.user_id, task.task_id).is_file()
    assert service.evidence_path(user.user_id, task.task_id).is_file()
    events = service.list_events(user.user_id, task.task_id)
    assert len(events) >= 30
    assert any(event.phase == "verification" for event in events)
