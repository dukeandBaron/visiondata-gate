"""Real host Bearer isolation across mounted vision-model and data-pool routes.

These are integration checks of landed modules, not model-training or pool-quality
evidence. Synthetic task records are created with auto_start=False; no weights,
datasets, executable runtimes, worker processes, or approved pools are fabricated.
"""

from __future__ import annotations

import hashlib
import importlib
import sys
from dataclasses import dataclass

from fastapi.testclient import TestClient
import pytest


pytestmark = pytest.mark.tier_integration

PASSWORD = "synthetic integration password 47"
STARTUP_CAPABILITY = "synthetic-platform-integration-startup-capability-63"
VISION_LISTS = (
    "vision-models",
    "vision-runtimes",
    "vision-datasets",
    "vision-training-runs",
)


@dataclass(frozen=True)
class AccountScope:
    user_id: str
    token: str
    workspace_id: str
    project_id: str
    task_id: str

    @property
    def headers(self) -> dict[str, str]:
        return {"Authorization": f"Bearer {self.token}"}


def _account(login_name: str) -> dict[str, str]:
    return {
        "login_name": login_name,
        "display_name": login_name,
        "password": PASSWORD,
    }


def _create_scope(client, product, session: dict, label: str) -> AccountScope:
    from visiondata_gate.product_models import CreateTaskRequest

    user_id = session["user"]["user_id"]
    headers = {"Authorization": f"Bearer {session['access_token']}"}
    workspace_response = client.post(
        "/v1/workspaces",
        headers=headers,
        json={"name": f"{label} isolated workspace", "owner_user_id": user_id},
    )
    assert workspace_response.status_code == 201, workspace_response.text
    workspace_id = workspace_response.json()["workspace_id"]
    assert workspace_response.json()["owner_user_id"] == user_id
    project_response = client.post(
        "/v1/projects",
        headers=headers,
        json={
            "workspace_id": workspace_id,
            "name": f"{label} isolated synthetic project",
            "description": "HTTP identity integration; no task execution authorized",
        },
    )
    assert project_response.status_code == 201, project_response.text
    project_id = project_response.json()["project_id"]
    task = product.create_task(
        user_id,
        CreateTaskRequest(
            project_id=project_id,
            goal="Create an unstarted synthetic task for identity isolation only",
        ),
        auto_start=False,
    )
    return AccountScope(
        user_id=user_id,
        token=session["access_token"],
        workspace_id=workspace_id,
        project_id=project_id,
        task_id=task.task_id,
    )


@pytest.fixture
def platform_identity(tmp_path, monkeypatch):
    # The api module creates a default app at import time. Confine that side effect
    # as well as the test's explicit ProductService before any import of api.
    monkeypatch.setenv("VISIONDATA_PRODUCT_ROOT", str(tmp_path / "import-product"))
    monkeypatch.setenv("VISIONDATA_SESSION_TOKEN", STARTUP_CAPABILITY)
    monkeypatch.setenv("VISIONDATA_SESSION_ACTOR_USER_ID", "usr_local_demo")
    monkeypatch.setenv("VISIONDATA_INSECURE_TEST_ACTOR_HEADER_BYPASS", "false")
    monkeypatch.setenv("VISIONDATA_AGENTTEAMS_MODE", "off")
    imported_here = "visiondata_gate.api" not in sys.modules
    api = importlib.import_module("visiondata_gate.api")
    from visiondata_gate.product_service import ProductService

    product = ProductService(tmp_path / "product", recover_interrupted=False)
    app = api.create_app(product, enable_account_bootstrap=False)
    try:
        with TestClient(app, client=("127.0.0.1", 49347)) as client:
            setup = client.post(
                "/v1/identity/setup",
                json=_account("integration-admin"),
                headers={"X-VisionData-Session-Token": STARTUP_CAPABILITY},
            )
            assert setup.status_code == 201, setup.text
            admin_session = setup.json()
            registered = client.post(
                "/v1/identity/register", json=_account("integration-owner")
            )
            assert registered.status_code == 201, registered.text
            ordinary = registered.json()
            assert ordinary["status"] == "PENDING"
            assert ordinary["platform_role"] == "USER"
            assert "access_token" not in ordinary
            with product.store._connection() as connection:
                assert (
                    connection.execute(
                        "SELECT COUNT(*) FROM workspace_members WHERE user_id=?",
                        (ordinary["user_id"],),
                    ).fetchone()[0]
                    == 0
                )
            approval = client.post(
                f"/v1/identity/admin/users/{ordinary['user_id']}/approve",
                headers={"Authorization": f"Bearer {admin_session['access_token']}"},
            )
            assert approval.status_code == 200, approval.text
            login = client.post(
                "/v1/identity/login",
                json={"login_name": ordinary["login_name"], "password": PASSWORD},
            )
            assert login.status_code == 200, login.text
            ordinary_session = login.json()
            before = client.get(
                "/v1/workspaces",
                headers={"Authorization": f"Bearer {ordinary_session['access_token']}"},
            )
            assert before.status_code == 200, before.text
            assert before.json() == []
            admin = _create_scope(client, product, admin_session, "Admin")
            owner = _create_scope(client, product, ordinary_session, "Ordinary owner")
            yield client, product, admin, owner
    finally:
        product.close(wait=True)
        if imported_here:
            api.app.state.product_service.close(wait=True)


def _paths(scope: AccountScope) -> list[str]:
    return [
        *(f"/v1/projects/{scope.project_id}/{suffix}" for suffix in VISION_LISTS),
        f"/v1/projects/{scope.project_id}/vision-capabilities",
        f"/v1/tasks/{scope.task_id}/data-pools",
        f"/v1/projects/{scope.project_id}/data-pool-operations/create/"
        f"integration-missing-request?target_id={scope.task_id}",
    ]


def _assert_receipt(response) -> dict:
    from visiondata_gate.audit_envelope import canonical_jcs_bytes

    assert response.status_code == 200, (response.request.url, response.text)
    body = response.json()
    digest = body["receipt_sha256"]
    actual = hashlib.sha256(
        canonical_jcs_bytes(
            {name: value for name, value in body.items() if name != "receipt_sha256"}
        )
    ).hexdigest()
    assert digest == actual
    assert response.headers["ETag"] == f'"{digest}"'
    assert response.headers["X-Content-SHA256"] == digest
    assert response.headers["Cache-Control"] == "private, no-store"
    return body


def _assert_denied(response, expected_status: int, expected_code: str) -> None:
    assert response.status_code == expected_status, (
        response.request.url,
        response.text,
    )
    assert response.json()["error"]["code"] == expected_code
    assert response.headers["Cache-Control"] == "private, no-store"
    assert PASSWORD not in response.text
    assert STARTUP_CAPABILITY not in response.text


def test_real_host_owner_lists_and_empty_operations_have_verified_receipts(
    platform_identity,
):
    client, product, admin, owner = platform_identity
    for scope in (admin, owner):
        for suffix in VISION_LISTS:
            body = _assert_receipt(
                client.get(
                    f"/v1/projects/{scope.project_id}/{suffix}", headers=scope.headers
                )
            )
            assert body["project_id"] == scope.project_id
            assert body["items"] == []
        capabilities = _assert_receipt(
            client.get(
                f"/v1/projects/{scope.project_id}/vision-capabilities",
                headers=scope.headers,
            )
        )
        assert capabilities["registered_model_count"] == 0
        assert capabilities["registered_runtime_count"] == 0
        assert capabilities["training_ready"] is False
        assert capabilities["industrial_effectiveness_status"] == "NOT_EVALUATED"
        pools = _assert_receipt(
            client.get(f"/v1/tasks/{scope.task_id}/data-pools", headers=scope.headers)
        )
        assert pools["task_id"] == scope.task_id
        assert pools["project_id"] == scope.project_id
        assert pools["workspace_id"] == scope.workspace_id
        assert pools["items"] == []
        operation = _assert_receipt(
            client.get(_paths(scope)[-1], headers=scope.headers)
        )
        assert operation["lookup_status"] == "NOT_FOUND"
        assert operation["execution_status"] == "UNKNOWN_NOT_PROOF_OF_NO_WRITE"
        assert operation["automatic_retry_allowed"] is False
        assert operation["target_id"] == scope.task_id
        task = product.store.get_task(scope.user_id, scope.task_id)
        assert task.evidence_sha256 is None
        assert task.execution_status.value != "completed"


def test_platform_admin_has_no_cross_workspace_visibility_in_either_module(
    platform_identity,
):
    client, _, admin, owner = platform_identity
    for caller, target in ((admin, owner), (owner, admin)):
        for path in _paths(target):
            _assert_denied(client.get(path, headers=caller.headers), 404, "not_found")
        for suffix in (
            "vision-models/vision_model_nonexistent",
            "vision-training-runs/vision_run_nonexistent",
            "vision-operations/register_model/integration-missing-request",
        ):
            _assert_denied(
                client.get(
                    f"/v1/projects/{target.project_id}/{suffix}", headers=caller.headers
                ),
                404,
                "not_found",
            )


def test_startup_capability_and_spoofed_actor_cannot_authorize_mounted_modules(
    platform_identity,
):
    client, _, admin, owner = platform_identity
    for path in _paths(owner):
        for capability_name in (
            "X-VisionData-Session-Token",
            "X-VisionData-Desktop-Token",
        ):
            response = client.get(
                path,
                headers={
                    capability_name: STARTUP_CAPABILITY,
                    "X-Actor-User-Id": owner.user_id,
                },
            )
            _assert_denied(response, 401, "identity_authentication_failed")
            assert response.headers["WWW-Authenticate"] == "Bearer"
        _assert_denied(
            client.get(
                path,
                headers={**admin.headers, "X-Actor-User-Id": owner.user_id},
            ),
            403,
            "identity_forbidden",
        )


def test_membership_removal_immediately_revokes_both_module_accesses(
    platform_identity,
):
    client, _, admin, owner = platform_identity
    membership_path = (
        f"/v1/identity/workspaces/{admin.workspace_id}/members/{owner.user_id}"
    )
    added = client.put(membership_path, headers=admin.headers, json={"role": "member"})
    assert added.status_code == 200, added.text
    assert {item["user_id"]: item["role"] for item in added.json()["members"]} == {
        admin.user_id: "owner",
        owner.user_id: "member",
    }
    for path in _paths(admin):
        _assert_receipt(client.get(path, headers=owner.headers))
    removed = client.delete(membership_path, headers=admin.headers)
    assert removed.status_code == 204, removed.text
    for path in _paths(admin):
        _assert_denied(client.get(path, headers=owner.headers), 404, "not_found")
    for path in _paths(owner):
        _assert_receipt(client.get(path, headers=owner.headers))


def test_disabled_account_token_is_rejected_by_both_mounted_modules(
    platform_identity,
):
    client, _, admin, owner = platform_identity
    for path in _paths(owner):
        _assert_receipt(client.get(path, headers=owner.headers))
    disabled = client.put(
        f"/v1/identity/admin/users/{owner.user_id}/status",
        headers=admin.headers,
        json={"status": "DISABLED"},
    )
    assert disabled.status_code == 200, disabled.text
    for path in _paths(owner):
        _assert_denied(
            client.get(path, headers=owner.headers),
            401,
            "identity_authentication_failed",
        )
    for path in _paths(admin):
        _assert_receipt(client.get(path, headers=admin.headers))
