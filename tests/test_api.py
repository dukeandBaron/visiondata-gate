from __future__ import annotations

import hashlib
import hmac
from pathlib import Path
from types import SimpleNamespace

from fastapi.testclient import TestClient

from visiondata_gate.api import create_app
from visiondata_gate.evidence import canonical_json_bytes
from visiondata_gate.product_models import (
    CreateTaskRequest,
    ErrorEnvelope,
    TaskExecutionStatus,
)
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
    assert payload["authentication"] == "test_actor_header_bypass"
    assert payload["agentteams_connection"] == "mapped_not_connected"
    assert payload["data_sources"]["synthetic_demo"] == "connected"
    assert payload["data_sources"]["local_authorized_directory"] == "not_connected"
    assert payload["data_sources"]["cvat_annotation"] == "contract_ready_not_connected"
    assert (
        payload["data_sources"]["fiftyone_annotation"] == "contract_ready_not_connected"
    )


def test_private_api_fails_closed_without_a_configured_session(
    tmp_path: Path,
    monkeypatch,
) -> None:
    monkeypatch.setenv("VISIONDATA_INSECURE_TEST_ACTOR_HEADER_BYPASS", "false")
    client, service = _client(tmp_path, ensure_demo_tenant=True)

    health = client.get("/v1/health")
    denied = client.get(
        "/v1/workspaces",
        headers={"X-Actor-User-Id": "usr_local_demo"},
    )

    assert health.status_code == 200
    assert health.json()["authentication"] == "not_configured_fail_closed"
    assert denied.status_code == 503
    assert denied.json()["error"]["code"] == "local_session_not_configured"
    service.close(wait=True)


def test_bound_session_rejects_wrong_token_and_actor_without_mutation(
    tmp_path: Path,
    monkeypatch,
) -> None:
    token = "api-session-token-with-at-least-32-characters"
    monkeypatch.setenv("VISIONDATA_INSECURE_TEST_ACTOR_HEADER_BYPASS", "false")
    monkeypatch.setenv("VISIONDATA_SESSION_TOKEN", token)
    monkeypatch.setenv("VISIONDATA_SESSION_ACTOR_USER_ID", "usr_local_demo")
    client, service = _client(tmp_path, ensure_demo_tenant=True)
    endpoint = "/v1/workspaces"

    missing = client.get(endpoint)
    wrong_token = client.get(
        endpoint,
        headers={"X-VisionData-Session-Token": "x" * 40},
    )
    wrong_actor = client.post(
        endpoint,
        headers={
            "X-VisionData-Session-Token": token,
            "X-Actor-User-Id": "usr_attacker",
        },
        json={"name": "Forged Workspace", "owner_user_id": "usr_local_demo"},
    )
    allowed = client.get(
        endpoint,
        headers={"X-VisionData-Session-Token": token},
    )

    assert missing.status_code == 401
    assert wrong_token.status_code == 401
    assert wrong_actor.status_code == 403
    assert [row["workspace_id"] for row in allowed.json()] == ["wsp_local_demo"]
    assert client.get("/v1/health").json()["authentication"] == (
        "session_token_bound_principal"
    )
    service.close(wait=True)


def test_bound_session_rejects_cross_site_form_before_business_handler(
    tmp_path: Path,
    monkeypatch,
) -> None:
    token = "api-session-token-with-at-least-32-characters"
    monkeypatch.setenv("VISIONDATA_INSECURE_TEST_ACTOR_HEADER_BYPASS", "false")
    monkeypatch.setenv("VISIONDATA_SESSION_TOKEN", token)
    monkeypatch.setenv("VISIONDATA_SESSION_ACTOR_USER_ID", "usr_local_demo")
    client, service = _client(tmp_path, ensure_demo_tenant=True)
    calls: list[tuple[str, str]] = []

    def unexpected_probe(actor_user_id: str, workspace_id: str):
        calls.append((actor_user_id, workspace_id))
        raise AssertionError("cross-site request reached the business handler")

    monkeypatch.setattr(service, "probe_hosted_agentteams", unexpected_probe)
    response = client.post(
        "/v1/workspaces/wsp_local_demo/hosted-agentteams/probes",
        headers={
            "X-VisionData-Session-Token": token,
            "X-Actor-User-Id": "usr_local_demo",
            "Origin": "https://attacker.invalid",
            "Sec-Fetch-Site": "cross-site",
            "Content-Type": "application/x-www-form-urlencoded",
        },
    )

    assert response.status_code == 403
    assert response.json()["error"]["code"] == "cross_site_request_rejected"
    assert calls == []
    service.close(wait=True)


def test_bound_session_allows_same_origin_state_change(
    tmp_path: Path,
    monkeypatch,
) -> None:
    token = "api-session-token-with-at-least-32-characters"
    monkeypatch.setenv("VISIONDATA_INSECURE_TEST_ACTOR_HEADER_BYPASS", "false")
    monkeypatch.setenv("VISIONDATA_SESSION_TOKEN", token)
    monkeypatch.setenv("VISIONDATA_SESSION_ACTOR_USER_ID", "usr_local_demo")
    client, service = _client(tmp_path, ensure_demo_tenant=True)

    response = client.post(
        "/v1/projects",
        headers={
            "X-VisionData-Session-Token": token,
            "X-Actor-User-Id": "usr_local_demo",
            "Origin": "http://127.0.0.1:4173",
            "Sec-Fetch-Site": "same-origin",
        },
        json={
            "workspace_id": "wsp_local_demo",
            "name": "Same-origin project",
        },
    )

    assert response.status_code == 201
    assert response.json()["workspace_id"] == "wsp_local_demo"
    service.close(wait=True)


def test_bound_session_keeps_cors_preflight_public(
    tmp_path: Path,
    monkeypatch,
) -> None:
    token = "api-session-token-with-at-least-32-characters"
    monkeypatch.setenv("VISIONDATA_SESSION_TOKEN", token)
    client, service = _client(tmp_path, ensure_demo_tenant=True)

    response = client.options(
        "/v1/workspaces",
        headers={
            "Origin": "http://127.0.0.1:4173",
            "Access-Control-Request-Method": "GET",
            "Access-Control-Request-Headers": "X-VisionData-Session-Token",
        },
    )

    assert response.status_code == 200
    assert response.headers["access-control-allow-origin"] == ("http://127.0.0.1:4173")
    service.close(wait=True)


def test_desktop_readiness_uses_challenge_proof_without_disclosing_authority(
    tmp_path: Path,
    monkeypatch,
) -> None:
    session_token = "desktop-session-token-with-at-least-32-characters"
    startup_secret = "desktop-startup-secret-with-at-least-32-characters"
    challenge = "a" * 64
    monkeypatch.setenv("VISIONDATA_INSECURE_TEST_ACTOR_HEADER_BYPASS", "false")
    monkeypatch.setenv("VISIONDATA_DESKTOP_SESSION_TOKEN", session_token)
    monkeypatch.setenv("VISIONDATA_DESKTOP_STARTUP_SECRET", startup_secret)
    client, service = _client(tmp_path, ensure_demo_tenant=True)

    proof = client.get(
        "/v1/desktop/readiness",
        params={"challenge": challenge},
    )
    denied = client.get("/v1/workspaces")

    assert proof.status_code == 200
    assert (
        proof.text
        == hmac.new(
            startup_secret.encode("ascii"),
            challenge.encode("ascii"),
            hashlib.sha256,
        ).hexdigest()
    )
    assert startup_secret not in proof.text
    assert session_token not in proof.text
    assert denied.status_code == 401
    service.close(wait=True)


def test_browser_artifact_headers_are_exposed_and_trace_is_sha_bound(
    tmp_path: Path,
) -> None:
    client, service = _client(tmp_path)
    user_id, _, project_id = _tenant(client)
    task = service.create_task(
        user_id,
        CreateTaskRequest(
            project_id=project_id,
            goal="生成可由浏览器核验 SHA 的运行 Trace。",
        ),
        auto_start=False,
    )
    completed = service.run_task_sync(task.task_id)
    assert completed.trace_sha256 is not None

    origin = "http://127.0.0.1:4173"
    trace = client.get(
        f"/v1/tasks/{task.task_id}/trace",
        headers={"X-Actor-User-Id": user_id, "Origin": origin},
    )
    assert trace.status_code == 200
    assert trace.headers["x-trace-sha256"] == completed.trace_sha256
    exposed = {
        item.strip()
        for item in trace.headers["access-control-expose-headers"].split(",")
    }
    assert {
        "ETag",
        "X-Content-SHA256",
        "X-Evidence-SHA256",
        "X-Trace-SHA256",
        "X-Incident-Case-SHA256",
        "X-Incident-Decision-SHA256",
        "X-Incident-Interaction-SHA256",
        "X-Decision-Packet-SHA256",
        "X-Audit-Bundle-SHA256",
        "X-Audit-Root-SHA256",
        "X-Signature-Status",
        "X-Incident-Command-Id",
        "X-Visual-Evidence-SHA256",
        "X-Goal3-Handoff-SHA256",
    }.issubset(exposed)


def test_decision_packet_html_separates_packet_identity_from_content_digest(
    tmp_path: Path,
    monkeypatch,
) -> None:
    client, service = _client(tmp_path)
    packet_sha256 = "a" * 64
    html_bytes = b"<!doctype html><html><body>sealed packet</body></html>"
    content_sha256 = hashlib.sha256(html_bytes).hexdigest()
    monkeypatch.setattr(
        service,
        "get_industrial_incident_decision_packet_exports",
        lambda _actor, _task_id, _case_id: SimpleNamespace(
            decision_packet_html=html_bytes,
            receipt=SimpleNamespace(packet_sha256=packet_sha256),
        ),
    )

    response = client.get(
        "/v1/tasks/tsk_00000000000000000000/industrial-incidents/"
        "incident_00000000000000000000/decision-packet.html",
        headers={"X-Actor-User-Id": "usr_html_digest_test"},
    )

    assert response.status_code == 200
    assert response.content == html_bytes
    assert response.headers["x-decision-packet-sha256"] == packet_sha256
    assert response.headers["x-content-sha256"] == content_sha256
    assert response.headers["etag"] == f'"{content_sha256}"'
    assert response.headers["cache-control"] == "private, no-store"


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
    assert "/v1/tasks/{task_id}/plan" in paths
    assert "/v1/tasks/{task_id}/preflight" in paths
    assert "/v1/tasks/{task_id}/reverifications" in paths
    assert "/v1/tasks/{task_id}/lineage" in paths
    assert "/v1/tasks/{task_id}/interventions" in paths
    assert "/v1/tasks/{task_id}/industrial-delivery" in paths
    assert "/v1/tasks/{task_id}/visual-evidence" in paths
    assert "/v1/tasks/{task_id}/visual-evidence/{sample_id}/preview" in paths
    assert "/v1/tasks/{task_id}/visual-evidence/{sample_id}/mask" in paths
    assert "/v1/tasks/{task_id}/capa-cases" in paths
    assert "/v1/tasks/{task_id}/capa-cases/{case_id}" in paths
    assert "/v1/tasks/{task_id}/capa-cases/{case_id}/causal-replay" in paths
    assert "/v1/tasks/{task_id}/capa-cases/{case_id}/outcome-assessment" in paths
    assert "/v1/tasks/{task_id}/capa-cases/{case_id}/approval" in paths
    assert "/v1/tasks/{task_id}/capa-cases/{case_id}/execute" in paths
    assert (
        "/v1/tasks/{task_id}/industrial-incidents/{case_id}/review-projection" in paths
    )
    assert "/v1/tasks/{task_id}/release-readiness" in paths
    assert "/v1/tasks/{task_id}/goal3-handoff" in paths
    assert "/v1/tasks/{task_id}/annotation-exports/{provider}" in paths
    assert "/v1/tasks/{task_id}/annotation-imports" in paths
    assert "/v1/tasks/{task_id}/annotation-roundtrips" in paths
    assert "/v1/tasks/{task_id}/acceptance-scorecard" in paths
    assert "/v1/data-sources/{source_id}/authorization-events" in paths
    assert "/v1/data-sources/{source_id}/revocations" in paths

    components = schema.json()["components"]["schemas"]
    assert "ErrorEnvelope" in components
    expected_errors = {
        ("/v1/users", "post"): {"409"},
        ("/v1/workspaces", "post"): {"404"},
        ("/v1/projects", "post"): {"404"},
        ("/v1/projects", "get"): {"404"},
        ("/v1/tasks", "post"): {"404", "409"},
        ("/v1/tasks/{task_id}", "get"): {"404"},
        ("/v1/tasks/{task_id}/plan", "get"): {"404"},
        ("/v1/tasks/{task_id}/preflight", "get"): {"404"},
        ("/v1/tasks/{task_id}/reverifications", "post"): {"404", "409"},
        ("/v1/tasks/{task_id}/lineage", "get"): {"404", "409"},
        (
            "/v1/tasks/{task_id}/industrial-incidents/{case_id}/review-projection",
            "get",
        ): {"404", "409"},
        ("/v1/tasks/{task_id}/interventions", "post"): {"404", "409"},
        ("/v1/tasks/{task_id}/interventions", "get"): {"404"},
        ("/v1/tasks/{task_id}/events", "get"): {"404"},
        ("/v1/tasks/{task_id}/trace", "get"): {"404", "409"},
        ("/v1/tasks/{task_id}/evidence", "get"): {"404", "409"},
        ("/v1/tasks/{task_id}/industrial-delivery", "get"): {"404", "409"},
        ("/v1/tasks/{task_id}/visual-evidence", "get"): {"404", "409"},
        (
            "/v1/tasks/{task_id}/visual-evidence/{sample_id}/preview",
            "get",
        ): {"404", "409"},
        (
            "/v1/tasks/{task_id}/visual-evidence/{sample_id}/mask",
            "get",
        ): {"404", "409"},
        ("/v1/tasks/{task_id}/capa-cases", "post"): {"404", "409"},
        ("/v1/tasks/{task_id}/capa-cases", "get"): {"404"},
        ("/v1/tasks/{task_id}/capa-cases/{case_id}", "get"): {
            "404",
            "409",
        },
        (
            "/v1/tasks/{task_id}/capa-cases/{case_id}/causal-replay",
            "get",
        ): {"404", "409"},
        (
            "/v1/tasks/{task_id}/capa-cases/{case_id}/outcome-assessment",
            "get",
        ): {"404", "409"},
        ("/v1/tasks/{task_id}/capa-cases/{case_id}/approval", "post"): {
            "404",
            "409",
        },
        ("/v1/tasks/{task_id}/capa-cases/{case_id}/execute", "post"): {
            "404",
            "409",
        },
        ("/v1/tasks/{task_id}/release-readiness", "get"): {"404", "409"},
        ("/v1/tasks/{task_id}/goal3-handoff", "get"): {"404", "409"},
        ("/v1/tasks/{task_id}/annotation-exports/{provider}", "post"): {
            "404",
            "409",
        },
        ("/v1/tasks/{task_id}/annotation-imports", "post"): {"404", "409"},
        ("/v1/tasks/{task_id}/annotation-roundtrips", "get"): {"404"},
        ("/v1/tasks/{task_id}/acceptance-scorecard", "get"): {"404", "409"},
        ("/v1/data-sources/{source_id}/authorization-events", "get"): {
            "404",
            "409",
        },
        ("/v1/data-sources/{source_id}/revocations", "post"): {
            "404",
            "409",
        },
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


def test_capa_and_authorization_routes_return_structured_responses(
    tmp_path: Path,
) -> None:
    client, service = _client(tmp_path)
    user_id, _, project_id = _tenant(client)
    headers = {"X-Actor-User-Id": user_id}
    created = client.post(
        "/v1/tasks",
        headers=headers,
        json={
            "project_id": project_id,
            "goal": "验证 CAPA 与授权生命周期接口不是仅存在于 OpenAPI。",
        },
    )
    assert created.status_code == 202
    task_id = created.json()["task_id"]

    empty_cases = client.get(
        f"/v1/tasks/{task_id}/capa-cases",
        headers=headers,
    )
    assert empty_cases.status_code == 200
    assert empty_cases.json() == []
    empty_cases_sha256 = hashlib.sha256(canonical_json_bytes([])).hexdigest()
    assert empty_cases.headers["x-content-sha256"] == empty_cases_sha256
    assert empty_cases.headers["etag"] == f'"{empty_cases_sha256}"'

    missing_review_projection = client.get(
        f"/v1/tasks/{task_id}/industrial-incidents/"
        "incident_00000000000000000000/review-projection",
        headers=headers,
    )
    assert missing_review_projection.status_code == 404
    assert missing_review_projection.json()["error"]["code"] == "not_found"
    ErrorEnvelope.model_validate(missing_review_projection.json())

    missing_case = client.get(
        f"/v1/tasks/{task_id}/capa-cases/capa_missing",
        headers=headers,
    )
    assert missing_case.status_code == 404
    assert missing_case.json()["error"]["code"] == "not_found"
    ErrorEnvelope.model_validate(missing_case.json())

    missing_replay = client.get(
        f"/v1/tasks/{task_id}/capa-cases/capa_missing/causal-replay",
        headers=headers,
    )
    assert missing_replay.status_code == 404
    assert missing_replay.json()["error"]["code"] == "not_found"
    ErrorEnvelope.model_validate(missing_replay.json())

    missing_events = client.get(
        "/v1/data-sources/src_missing/authorization-events",
        headers=headers,
    )
    assert missing_events.status_code == 404
    assert missing_events.json()["error"]["code"] == "not_found"
    ErrorEnvelope.model_validate(missing_events.json())
    service.close(wait=True)


def test_plan_approval_api_supports_preview_cancel_and_append_only_audit(
    tmp_path: Path,
) -> None:
    client, _ = _client(tmp_path)
    user_id, _, project_id = _tenant(client)
    headers = {"X-Actor-User-Id": user_id}
    created = client.post(
        "/v1/tasks",
        headers=headers,
        json={
            "project_id": project_id,
            "goal": "先审核计划，在工具运行前允许操作者取消。",
            "plan_approval_required": True,
        },
    )
    assert created.status_code == 202
    task = created.json()
    assert task["execution_status"] == "PLANNED"
    assert task["plan_approval_required"] is True

    plan = client.get(f"/v1/tasks/{task['task_id']}/plan", headers=headers)
    assert plan.status_code == 200
    assert plan.json()["approval_required"] is True
    assert len(plan.json()["plan_sha256"]) == 64
    empty = client.get(f"/v1/tasks/{task['task_id']}/interventions", headers=headers)
    assert empty.status_code == 200
    assert empty.json() == []

    cancelled = client.post(
        f"/v1/tasks/{task['task_id']}/interventions",
        headers=headers,
        json={
            "action": "cancel_plan",
            "note": "数据授权范围尚需复核，本次停止。",
        },
    )
    assert cancelled.status_code == 201
    assert cancelled.json()["before_status"] == "PLANNED"
    assert (
        cancelled.json()["before_snapshot_sha256"]
        == plan.json()["before_snapshot_sha256"]
    )
    current = client.get(f"/v1/tasks/{task['task_id']}", headers=headers)
    assert current.json()["execution_status"] == "CANCELLED"
    timeline = client.get(f"/v1/tasks/{task['task_id']}/interventions", headers=headers)
    assert [item["action"] for item in timeline.json()] == ["cancel_plan"]
    late_approval = client.post(
        f"/v1/tasks/{task['task_id']}/interventions",
        headers=headers,
        json={"action": "approve_plan", "note": "不得恢复已取消计划。"},
    )
    assert late_approval.status_code == 409
    assert late_approval.json()["error"]["code"] == "conflict"


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
