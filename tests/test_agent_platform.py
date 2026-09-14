from __future__ import annotations

import hashlib

import pytest
from fastapi.testclient import TestClient

from visiondata_gate.api import create_app
from visiondata_gate.evidence import canonical_json_bytes
from visiondata_gate.product_models import CreateProjectRequest, CreateTaskRequest
from visiondata_gate.product_service import ProductService


ACTOR = "usr_local_demo"
WORKSPACE = "wsp_local_demo"
HEADERS = {"X-Actor-User-Id": ACTOR}


@pytest.fixture
def platform_client(tmp_path):
    service = ProductService(tmp_path / "product")
    with TestClient(create_app(service, ensure_demo_tenant=True)) as client:
        yield client, service
    service.close(wait=True)


def test_platform_catalog_is_scoped_sha_bound_and_does_not_probe_models(
    platform_client,
):
    client, service = platform_client
    response = client.get(f"/v1/workspaces/{WORKSPACE}/agent-platform", headers=HEADERS)
    assert response.status_code == 200
    report = response.json()
    sha = report.pop("receipt_sha256")
    assert hashlib.sha256(canonical_json_bytes(report)).hexdigest() == sha
    assert response.headers["etag"] == f'"{sha}"'
    assert response.headers["x-agent-platform-sha256"] == sha
    assert report["scope"]["production_authentication"] is False
    assert report["providers"]["connection_status"] == "NOT_PROBED"
    assert report["providers"]["configured_count"] == 0
    assert report["tasks"] == []
    assert {row["capability_id"] for row in report["capabilities"]} >= {
        "image_quality",
        "duplicate_leakage",
        "annotation_integrity",
        "coverage_matrix",
        "governance_audit",
    }
    assert all("base_url" not in row for row in report["capabilities"])
    assert "private" not in canonical_json_bytes(report).decode().lower()


def test_platform_rejects_foreign_workspace_and_project_mismatch(platform_client):
    client, service = platform_client
    assert (
        client.get("/v1/workspaces/foreign/agent-platform", headers=HEADERS).status_code
        == 404
    )
    assert (
        client.get(
            f"/v1/workspaces/{WORKSPACE}/agent-platform?project_id=foreign",
            headers=HEADERS,
        ).status_code
        == 404
    )
    assert (
        client.get(
            f"/v1/workspaces/{WORKSPACE}/agent-platform",
            headers={"X-Actor-User-Id": "foreign"},
        ).status_code
        == 404
    )


def test_platform_filters_tasks_by_selected_project_without_starting_them(
    platform_client,
):
    client, service = platform_client
    first = service.create_project(
        ACTOR, CreateProjectRequest(workspace_id=WORKSPACE, name="first")
    )
    second = service.create_project(
        ACTOR, CreateProjectRequest(workspace_id=WORKSPACE, name="second")
    )
    tasks = []
    for project in (first, second):
        tasks.append(
            service.create_task(
                ACTOR,
                CreateTaskRequest(
                    project_id=project.project_id,
                    goal="Inspect the selected project only",
                    plan_approval_required=True,
                ),
                auto_start=False,
            )
        )
    result = client.get(
        f"/v1/workspaces/{WORKSPACE}/agent-platform",
        params={"project_id": first.project_id},
        headers=HEADERS,
    )
    assert result.status_code == 200
    assert [task["task_id"] for task in result.json()["tasks"]] == [tasks[0].task_id]
    assert result.json()["tasks"][0]["execution_status"] == "PLANNED"
    assert result.json()["task_count"] == 1
    assert result.json()["tasks_truncated"] is False
    assert service.list_events(ACTOR, tasks[0].task_id) == []


def test_task_usage_and_recovery_are_authenticated_and_hash_bound(platform_client):
    client, service = platform_client
    task = service.create_task(
        ACTOR,
        CreateTaskRequest(
            project_id="prj_industrial_vision",
            goal="Inspect without any automatic run",
            plan_approval_required=True,
        ),
        auto_start=False,
    )
    for suffix, header in [
        ("model-usage", "x-model-usage-sha256"),
        ("execution-recovery", "x-execution-recovery-sha256"),
    ]:
        route = f"/v1/tasks/{task.task_id}/{suffix}"
        response = client.get(route, headers=HEADERS)
        assert response.status_code == 200, response.text
        payload = response.json()
        digest = payload.pop("receipt_sha256")
        assert hashlib.sha256(canonical_json_bytes(payload)).hexdigest() == digest
        assert response.headers[header] == digest
        assert response.headers["etag"] == f'"{digest}"'
        assert (
            client.get(route, headers={"X-Actor-User-Id": "foreign"}).status_code == 404
        )
    usage = client.get(f"/v1/tasks/{task.task_id}/model-usage", headers=HEADERS).json()
    assert usage["summary"]["call_status"] == "UNKNOWN"
    assert usage["summary"]["cost"] is None
    assert usage["summary"]["total_tokens"] is None
    denied = client.post(
        f"/v1/tasks/{task.task_id}/execution-recovery",
        headers=HEADERS,
        json={
            "expected_snapshot_sha256": "0" * 64,
            "reviewer_identity": "Reviewer",
            "note": "Must never approve a planned task as a recovery",
            "operator_attests_recovery": True,
        },
    )
    assert denied.status_code == 409


def test_platform_task_limit_reports_actual_total(platform_client):
    client, service = platform_client
    # Populate only synthetic task requests; no model, tool or runner is invoked.
    for number in range(201):
        service.create_task(
            ACTOR,
            CreateTaskRequest(
                project_id="prj_industrial_vision",
                goal=f"Planned synthetic inventory item {number}",
                plan_approval_required=True,
            ),
            auto_start=False,
        )
    result = client.get(
        f"/v1/workspaces/{WORKSPACE}/agent-platform", headers=HEADERS
    ).json()
    assert result["task_count"] == 201
    assert len(result["tasks"]) == 200
    assert result["tasks_truncated"] is True


def test_recovery_http_creates_one_unapproved_replacement(platform_client):
    from visiondata_gate.execution_recovery import new_execution_owner

    client, service = platform_client
    task = service.create_task(
        ACTOR,
        CreateTaskRequest(
            project_id="prj_industrial_vision",
            goal="Synthetic orphan for HTTP recovery",
            plan_approval_required=False,
        ),
        auto_start=False,
    )
    assert service.store.claim_task(
        task.task_id, execution_owner=new_execution_owner(task)
    )
    route = f"/v1/tasks/{task.task_id}/execution-recovery"
    projection = client.get(route, headers=HEADERS).json()
    assert projection["classification"] == "INTERRUPTED"
    request = {
        "expected_snapshot_sha256": projection["task_snapshot_sha256"],
        "reviewer_identity": "Synthetic recovery reviewer",
        "note": "Reviewed interrupted execution",
        "operator_attests_recovery": True,
    }
    response = client.post(route, headers=HEADERS, json=request)
    assert response.status_code == 200, response.text
    receipt = response.json()
    assert response.headers["etag"] == f'"{receipt["receipt_sha256"]}"'
    replacement = service.get_task(ACTOR, receipt["replacement_task_id"])
    assert replacement.plan_approval_required is True
    assert replacement.execution_status.value == "PLANNED"
    assert receipt["auto_started"] is False
    assert client.post(route, headers=HEADERS, json=request).json() == receipt
    assert service.list_events(ACTOR, replacement.task_id) == []
