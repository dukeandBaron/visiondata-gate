from __future__ import annotations

from pathlib import Path

from fastapi.testclient import TestClient

from visiondata_gate.api import create_app
from visiondata_gate.product_models import ErrorEnvelope, TaskExecutionStatus
from visiondata_gate.product_service import ProductService


def _client(
    tmp_path: Path,
    *,
    enable_account_bootstrap: bool = True,
    ensure_demo_tenant: bool = False,
) -> tuple[TestClient, ProductService]:
    service = ProductService(tmp_path / "product", recover_interrupted=False)
    return (
        TestClient(
            create_app(
                service,
                enable_account_bootstrap=enable_account_bootstrap,
                ensure_demo_tenant=ensure_demo_tenant,
            )
        ),
        service,
    )


def _tenant(client: TestClient, name: str = "API Owner") -> tuple[str, str, str]:
    user = client.post("/v1/users", json={"display_name": name})
    assert user.status_code == 201
    user_id = user.json()["user_id"]
    headers = {"X-Actor-User-Id": user_id}
    workspace = client.post(
        "/v1/workspaces",
        headers=headers,
        json={"name": f"{name} Workspace", "owner_user_id": user_id},
    )
    assert workspace.status_code == 201
    workspace_id = workspace.json()["workspace_id"]
    project = client.post(
        "/v1/projects",
        headers=headers,
        json={"workspace_id": workspace_id, "name": f"{name} Project"},
    )
    assert project.status_code == 201
    return user_id, workspace_id, project.json()["project_id"]


def test_health_is_truthful_about_local_prototype(tmp_path: Path) -> None:
    client, _ = _client(tmp_path)
    response = client.get("/v1/health")
    assert response.status_code == 200
    payload = response.json()
    assert payload["api_ready"] is True
    assert payload["production_ready"] is False
    assert payload["authentication"] == "not_configured"
    assert payload["agentteams_connection"] == "mapped_not_connected"
    assert payload["data_sources"]["synthetic_demo"] == "connected"
    assert payload["data_sources"]["local_authorized_directory"] == "not_connected"


def test_account_bootstrap_api_is_disabled_by_default_without_breaking_service(
    tmp_path: Path,
) -> None:
    client, service = _client(
        tmp_path,
        enable_account_bootstrap=False,
        ensure_demo_tenant=True,
    )
    paths = client.get("/openapi.json").json()["paths"]

    assert "/v1/users" not in paths
    assert "post" not in paths["/v1/workspaces"]
    missing_user_route = client.post("/v1/users", json={"display_name": "Blocked"})
    assert missing_user_route.status_code == 404
    ErrorEnvelope.model_validate(missing_user_route.json())
    assert client.get("/v1/users").status_code == 404
    method_not_allowed = client.post(
        "/v1/workspaces",
        json={"name": "Blocked", "owner_user_id": "usr_unknown"},
    )
    assert method_not_allowed.status_code == 405
    assert method_not_allowed.json()["error"]["code"] == "method_not_allowed"
    ErrorEnvelope.model_validate(method_not_allowed.json())

    user, workspace, project = service.ensure_default_tenant()
    assert workspace.owner_user_id == user.user_id
    assert project.workspace_id == workspace.workspace_id


def test_default_api_bootstraps_fixed_demo_objects_without_public_account_routes(
    tmp_path: Path,
) -> None:
    client, service = _client(
        tmp_path,
        enable_account_bootstrap=False,
        ensure_demo_tenant=True,
    )
    headers = {"X-Actor-User-Id": "usr_local_demo"}

    workspaces = client.get("/v1/workspaces", headers=headers)
    projects = client.get(
        "/v1/projects",
        params={"workspace_id": "wsp_local_demo"},
        headers=headers,
    )

    assert workspaces.status_code == 200
    assert [item["workspace_id"] for item in workspaces.json()] == ["wsp_local_demo"]
    assert projects.status_code == 200
    assert [item["project_id"] for item in projects.json()] == ["prj_industrial_vision"]
    assert "/v1/users" not in client.get("/openapi.json").json()["paths"]
    service.close(wait=True)


def test_explicit_bootstrap_scopes_users_and_requires_workspace_owner_actor(
    tmp_path: Path,
) -> None:
    client, service = _client(tmp_path)
    user_a = client.post("/v1/users", json={"display_name": "A"}).json()
    user_b = client.post("/v1/users", json={"display_name": "B"}).json()

    assert client.get("/v1/users").status_code == 422
    scoped = client.get("/v1/users", headers={"X-Actor-User-Id": user_a["user_id"]})
    assert scoped.status_code == 200
    assert [item["user_id"] for item in scoped.json()] == [user_a["user_id"]]

    payload = {
        "name": "A Workspace",
        "owner_user_id": user_a["user_id"],
    }
    assert client.post("/v1/workspaces", json=payload).status_code == 422
    mismatch = client.post(
        "/v1/workspaces",
        headers={"X-Actor-User-Id": user_b["user_id"]},
        json=payload,
    )
    assert mismatch.status_code == 404
    ErrorEnvelope.model_validate(mismatch.json())
    assert service.list_workspaces(user_a["user_id"]) == []
    assert service.list_workspaces(user_b["user_id"]) == []

    created = client.post(
        "/v1/workspaces",
        headers={"X-Actor-User-Id": user_a["user_id"]},
        json=payload,
    )
    assert created.status_code == 201
    assert created.json()["owner_user_id"] == user_a["user_id"]


def test_openapi_exposes_enterprise_task_contract(tmp_path: Path) -> None:
    client, _ = _client(tmp_path)
    schema = client.get("/openapi.json")
    assert schema.status_code == 200
    paths = schema.json()["paths"]
    assert "/v1/users" in paths
    assert "/v1/workspaces" in paths
    assert "/v1/projects" in paths
    assert "/v1/tasks" in paths
    assert "/v1/tasks/{task_id}/trace" in paths
    assert "/v1/tasks/{task_id}/evidence" in paths

    components = schema.json()["components"]["schemas"]
    assert "ErrorEnvelope" in components
    expected_errors = {
        ("/v1/users", "post"): {"409"},
        ("/v1/workspaces", "post"): {"404"},
        ("/v1/projects", "post"): {"404"},
        ("/v1/projects", "get"): {"404"},
        ("/v1/tasks", "post"): {"404", "409"},
        ("/v1/tasks/{task_id}", "get"): {"404"},
        ("/v1/tasks/{task_id}/events", "get"): {"404"},
        ("/v1/tasks/{task_id}/trace", "get"): {"404", "409"},
        ("/v1/tasks/{task_id}/evidence", "get"): {"404", "409"},
    }
    for (path, method), error_statuses in expected_errors.items():
        responses = paths[path][method]["responses"]
        for error_status in error_statuses:
            assert (
                responses[error_status]["content"]["application/json"]["schema"]["$ref"]
                == "#/components/schemas/ErrorEnvelope"
            )

    trace_responses = paths["/v1/tasks/{task_id}/trace"]["get"]["responses"]
    evidence_responses = paths["/v1/tasks/{task_id}/evidence"]["get"]["responses"]
    assert set(trace_responses["200"]["content"]) == {"application/json"}
    assert set(evidence_responses["200"]["content"]) == {"application/zip"}
    assert trace_responses["200"]["content"]["application/json"]["schema"] == {
        "type": "string",
        "format": "binary",
    }
    assert evidence_responses["200"]["content"]["application/zip"]["schema"] == {
        "type": "string",
        "format": "binary",
    }
    for responses in (trace_responses, evidence_responses):
        for error_status in ("404", "409"):
            assert (
                responses[error_status]["content"]["application/json"]["schema"]["$ref"]
                == "#/components/schemas/ErrorEnvelope"
            )


def test_create_task_returns_202_location_and_idempotency(tmp_path: Path) -> None:
    client, service = _client(tmp_path)
    user_id, _, project_id = _tenant(client)
    headers = {
        "X-Actor-User-Id": user_id,
        "Idempotency-Key": "api-demo-001",
    }
    payload = {
        "project_id": project_id,
        "goal": "通过 API 提交可持久化且可查询的 Agent 审核任务。",
    }
    first = client.post("/v1/tasks", headers=headers, json=payload)
    assert first.status_code == 202
    task_id = first.json()["task_id"]
    assert first.headers["location"] == f"/v1/tasks/{task_id}"
    second = client.post("/v1/tasks", headers=headers, json=payload)
    assert second.status_code == 202
    assert second.json()["task_id"] == task_id

    service.close(wait=True)


def test_cross_workspace_task_is_not_visible(tmp_path: Path) -> None:
    client, _ = _client(tmp_path)
    user_a, _, project_a = _tenant(client, "A")
    user_b, _, _ = _tenant(client, "B")
    task = client.post(
        "/v1/tasks",
        headers={"X-Actor-User-Id": user_a},
        json={
            "project_id": project_a,
            "goal": "创建一个只能被所属工作区成员读取的任务。",
        },
    )
    assert task.status_code == 202
    hidden = client.get(
        f"/v1/tasks/{task.json()['task_id']}",
        headers={"X-Actor-User-Id": user_b},
    )
    assert hidden.status_code == 404
    assert hidden.json()["error"]["code"] == "not_found"
    assert hidden.headers["content-type"] == "application/json"
    ErrorEnvelope.model_validate(hidden.json())


def test_unfinished_artifacts_return_409(tmp_path: Path) -> None:
    client, service = _client(tmp_path)
    user_id, _, project_id = _tenant(client)
    task = service.create_task(
        user_id,
        __import__(
            "visiondata_gate.product_models", fromlist=["CreateTaskRequest"]
        ).CreateTaskRequest(
            project_id=project_id,
            goal="保持计划状态以验证证据下载不会提前开放。",
        ),
        auto_start=False,
    )
    response = client.get(
        f"/v1/tasks/{task.task_id}/evidence",
        headers={"X-Actor-User-Id": user_id},
    )
    assert response.status_code == 409
    assert response.json()["error"]["code"] == "artifact_unavailable"
    assert response.headers["content-type"] == "application/json"
    ErrorEnvelope.model_validate(response.json())
    assert task.execution_status is TaskExecutionStatus.PLANNED


def test_api_rejects_extra_fields_and_unconnected_sources(tmp_path: Path) -> None:
    client, _ = _client(tmp_path)
    user_id, _, project_id = _tenant(client)
    headers = {"X-Actor-User-Id": user_id}
    extra = client.post(
        "/v1/tasks",
        headers=headers,
        json={
            "project_id": project_id,
            "goal": "请求中不允许携带任意模型端点或密钥。",
            "api_key": "must-not-be-accepted",
        },
    )
    assert extra.status_code == 422
    disconnected = client.post(
        "/v1/tasks",
        headers=headers,
        json={
            "project_id": project_id,
            "goal": "外部驻留数据未连接时必须拒绝执行。",
            "source_kind": "external_residency_reference",
        },
    )
    assert disconnected.status_code == 409
    assert disconnected.json()["error"]["code"] == "source_not_connected"

    unknown_tool = client.post(
        "/v1/tasks",
        headers=headers,
        json={
            "project_id": project_id,
            "goal": "未知或内部工具名称不得进入公开任务配置。",
            "allowed_tools": ["totally_unknown"],
        },
    )
    assert unknown_tool.status_code == 422
