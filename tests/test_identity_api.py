"""Identity contract regression through HTTP and a real isolated ProductService."""

from __future__ import annotations

from datetime import datetime, timedelta
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from visiondata_gate.api import create_app
from visiondata_gate.product_models import CreateWorkspaceRequest
from visiondata_gate.product_service import ProductService

pytestmark = pytest.mark.tier_integration

STARTUP_CAPABILITY = "synthetic-identity-test-startup-capability-47"
PASSWORD = "synthetic correct password 42"
NEW_PASSWORD = "replacement synthetic password 73"
ALLOWED_ORIGIN = "http://127.0.0.1:5173"
PUBLIC_USER_FIELDS = {
    "user_id",
    "login_name",
    "display_name",
    "email",
    "platform_role",
    "status",
    "created_at",
}


def account(name: str = "administrator") -> dict[str, str]:
    return {"login_name": name, "display_name": name, "password": PASSWORD}


def bearer(token_response: dict) -> dict[str, str]:
    return {"Authorization": f"Bearer {token_response['access_token']}"}


def assert_error(response, code: str, status_code: int) -> None:
    assert response.status_code == status_code, response.text
    assert response.json()["error"]["code"] == code
    assert response.headers["cache-control"] == "private, no-store"
    assert PASSWORD not in response.text
    assert STARTUP_CAPABILITY not in response.text


@pytest.fixture
def identity_app(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("VISIONDATA_SESSION_TOKEN", STARTUP_CAPABILITY)
    monkeypatch.setenv("VISIONDATA_SESSION_ACTOR_USER_ID", "usr_local_demo")
    monkeypatch.setenv("VISIONDATA_INSECURE_TEST_ACTOR_HEADER_BYPASS", "false")
    product = ProductService(tmp_path / "product", recover_interrupted=False)
    app = create_app(product, enable_account_bootstrap=True)
    with TestClient(app, client=("127.0.0.1", 49321)) as client:
        yield client, product
    product.close(wait=True)


def setup(client: TestClient) -> dict:
    response = client.post(
        "/v1/identity/setup",
        json=account(),
        headers={"X-VisionData-Session-Token": STARTUP_CAPABILITY},
    )
    assert response.status_code == 201, response.text
    return response.json()


@pytest.mark.parametrize(
    "origin,token,expected",
    [
        ("http://tauri.localhost", STARTUP_CAPABILITY, 201),
        ("http://tauri.localhost", "incorrect-desktop-token", 403),
        ("http://tauri.localhost", "", 403),
        ("https://untrusted.example", STARTUP_CAPABILITY, 403),
    ],
)
def test_native_cross_site_setup_requires_origin_and_desktop_capability(
    tmp_path, monkeypatch, origin, token, expected
):
    monkeypatch.setenv("VISIONDATA_DESKTOP_SESSION_TOKEN", STARTUP_CAPABILITY)
    monkeypatch.setenv("VISIONDATA_WEB_ORIGINS", "http://tauri.localhost")
    monkeypatch.setenv("VISIONDATA_INSECURE_TEST_ACTOR_HEADER_BYPASS", "false")
    product = ProductService(tmp_path / "native-product", recover_interrupted=False)
    try:
        with TestClient(
            create_app(product), client=("127.0.0.1", 49321)
        ) as client:
            response = client.post(
                "/v1/identity/setup",
                json=account(),
                headers={
                    "Origin": origin,
                    "Sec-Fetch-Site": "cross-site",
                    "X-VisionData-Desktop-Token": token,
                },
            )
            assert response.status_code == expected
    finally:
        product.close(wait=True)


def register(client: TestClient, name: str = "ordinary-user") -> dict:
    response = client.post("/v1/identity/register", json=account(name))
    assert response.status_code == 201, response.text
    return response.json()


def approve(client: TestClient, admin: dict, user: dict) -> None:
    response = client.post(
        f"/v1/identity/admin/users/{user['user_id']}/approve",
        headers=bearer(admin),
    )
    assert response.status_code == 200, response.text
    assert response.json()["status"] == "ACTIVE"


def login(client: TestClient, name: str, password: str = PASSWORD) -> dict:
    response = client.post(
        "/v1/identity/login",
        json={"login_name": name, "password": password},
    )
    assert response.status_code == 200, response.text
    return response.json()


def test_status_is_public_and_setup_binds_existing_actor(identity_app) -> None:
    client, product = identity_app
    response = client.get("/v1/identity/status")
    assert response.status_code == 200, response.text
    assert response.json() == {
        "setup_required": True,
        "identity_required": False,
        "registration_policy": "ADMIN_APPROVAL",
        "authentication_mode": "SETUP_REQUIRED",
        "startup_capability_required": True,
    }
    assert response.headers["cache-control"] == "private, no-store"
    admin = setup(client)
    assert set(admin) == {"user", "access_token", "token_type", "expires_at"}
    assert set(admin["user"]) == PUBLIC_USER_FIELDS
    assert admin["user"]["user_id"] == "usr_local_demo"
    assert admin["user"]["platform_role"] == "ADMIN"
    assert admin["token_type"] == "Bearer"
    assert admin["user"]["status"] == "ACTIVE"
    assert [
        item.workspace_id for item in product.list_workspaces("usr_local_demo")
    ] == ["wsp_local_demo"]
    after = client.get("/v1/identity/status")
    assert after.json() == {
        "setup_required": False,
        "identity_required": True,
        "registration_policy": "ADMIN_APPROVAL",
        "authentication_mode": "USER_SESSION",
        "startup_capability_required": True,
    }
    me = client.get("/v1/identity/me", headers=bearer(admin))
    assert me.status_code == 200
    assert me.json() == admin["user"]


@pytest.mark.parametrize(
    "capability_header",
    [
        "X-VisionData-Session-Token",
        "X-VisionData-Desktop-Token",
    ],
)
def test_setup_accepts_either_startup_capability_header(
    identity_app,
    capability_header: str,
) -> None:
    client, _ = identity_app
    response = client.post(
        "/v1/identity/setup",
        json=account(),
        headers={capability_header: STARTUP_CAPABILITY},
    )
    assert response.status_code == 201, response.text


@pytest.mark.parametrize("host", ["192.0.2.27", "localhost", "testclient"])
def test_setup_rejects_non_numeric_loopback_client(identity_app, host: str) -> None:
    client, _ = identity_app
    with TestClient(client.app, client=(host, 49322)) as remote:
        denied = remote.post(
            "/v1/identity/setup",
            json=account(),
            headers={"X-VisionData-Session-Token": STARTUP_CAPABILITY},
        )
    assert_error(denied, "identity_forbidden", 403)
    assert client.get("/v1/identity/status").json()["setup_required"] is True


@pytest.mark.parametrize(
    "extra_headers",
    [
        {},
        {"X-VisionData-Session-Token": "incorrect-synthetic-capability"},
        {
            "X-VisionData-Session-Token": STARTUP_CAPABILITY,
            "X-VisionData-Desktop-Token": "conflicting-synthetic-capability",
        },
        {
            "X-VisionData-Session-Token": STARTUP_CAPABILITY,
            "Forwarded": "for=127.0.0.1",
        },
        {
            "X-VisionData-Session-Token": STARTUP_CAPABILITY,
            "X-Forwarded-For": "127.0.0.1",
        },
        {
            "X-VisionData-Session-Token": STARTUP_CAPABILITY,
            "X-Forwarded-Host": "localhost",
        },
        {"X-VisionData-Session-Token": STARTUP_CAPABILITY, "X-Forwarded-Proto": "http"},
    ],
)
def test_setup_requires_unforwarded_startup_capability(
    identity_app, extra_headers
) -> None:
    client, _ = identity_app
    response = client.post("/v1/identity/setup", json=account(), headers=extra_headers)
    assert_error(response, "identity_forbidden", 403)


def test_setup_cannot_choose_actor_or_role_and_duplicate_is_conflict(
    identity_app,
) -> None:
    client, _ = identity_app
    for extra in ({"user_id": "usr_attacker"}, {"platform_role": "USER"}):
        rejected = client.post(
            "/v1/identity/setup",
            json={**account(), **extra},
            headers={"X-VisionData-Session-Token": STARTUP_CAPABILITY},
        )
        assert rejected.status_code == 422, rejected.text
        assert PASSWORD not in rejected.text
    setup(client)
    duplicate = client.post(
        "/v1/identity/setup",
        json=account("second-admin"),
        headers={"X-VisionData-Session-Token": STARTUP_CAPABILITY},
    )
    assert_error(duplicate, "identity_conflict", 409)


@pytest.mark.parametrize(
    "path",
    [
        "/v1/workspaces",
        "/v1/review/semifinal-demo-manifest",
        "/v1/review/evaluation-evidence/dynamicbench",
    ],
)
def test_after_setup_every_private_route_requires_bearer(
    identity_app, path: str
) -> None:
    client, _ = identity_app
    admin = setup(client)
    for headers in (
        {},
        {"X-Actor-User-Id": "usr_local_demo"},
        {"X-VisionData-Session-Token": STARTUP_CAPABILITY},
    ):
        denied = client.get(path, headers=headers)
        assert_error(denied, "identity_authentication_failed", 401)
    response = client.get(path, headers=bearer(admin))
    assert response.status_code == 200, response.text


def test_actor_header_cannot_select_a_different_user(identity_app) -> None:
    client, _ = identity_app
    admin = setup(client)
    mismatch = client.get(
        "/v1/workspaces",
        headers={**bearer(admin), "X-Actor-User-Id": "usr_other"},
    )
    assert_error(mismatch, "identity_forbidden", 403)
    matching = client.get(
        "/v1/workspaces",
        headers={**bearer(admin), "X-Actor-User-Id": admin["user"]["user_id"]},
    )
    assert matching.status_code == 200


def test_registration_and_approval_never_grant_workspace_membership(
    identity_app,
) -> None:
    client, product = identity_app
    admin = setup(client)
    pending = register(client)
    assert set(pending) == PUBLIC_USER_FIELDS
    assert pending["status"] == "PENDING"
    assert pending["platform_role"] == "USER"
    with product.store._connection() as connection:
        assert (
            connection.execute(
                "SELECT COUNT(*) FROM workspace_members WHERE user_id = ?",
                (pending["user_id"],),
            ).fetchone()[0]
            == 0
        )
    approve(client, admin, pending)
    user_session = login(client, pending["login_name"])
    assert client.get("/v1/workspaces", headers=bearer(user_session)).json() == []
    denied = client.get("/v1/identity/admin/users", headers=bearer(user_session))
    assert_error(denied, "identity_forbidden", 403)


def test_login_unknown_pending_disabled_and_wrong_password_are_uniform(
    identity_app,
) -> None:
    client, _ = identity_app
    admin = setup(client)
    pending = register(client, "pending-user")
    active = register(client, "disabled-user")
    approve(client, admin, active)
    disabled = client.put(
        f"/v1/identity/admin/users/{active['user_id']}/status",
        headers=bearer(admin),
        json={"status": "DISABLED"},
    )
    assert disabled.status_code == 200
    attempts = [
        ("nonexistent-user", PASSWORD),
        (pending["login_name"], PASSWORD),
        (active["login_name"], PASSWORD),
        ("administrator", "wrong password 17"),
    ]
    errors = []
    for name, password in attempts:
        response = client.post(
            "/v1/identity/login",
            json={"login_name": name, "password": password},
        )
        assert_error(response, "identity_authentication_failed", 401)
        errors.append(response.json())
    assert errors.count(errors[0]) == len(errors)


def test_last_active_admin_cannot_be_disabled_or_demoted(identity_app) -> None:
    client, _ = identity_app
    admin = setup(client)
    root = f"/v1/identity/admin/users/{admin['user']['user_id']}"
    for suffix, payload in (
        ("status", {"status": "DISABLED"}),
        ("role", {"platform_role": "USER"}),
    ):
        response = client.put(f"{root}/{suffix}", headers=bearer(admin), json=payload)
        assert_error(response, "identity_conflict", 409)
    assert (
        client.get("/v1/identity/me", headers=bearer(admin)).json()["status"]
        == "ACTIVE"
    )


def test_legacy_user_bootstrap_is_blocked_after_setup_even_when_enabled(
    identity_app,
) -> None:
    client, product = identity_app
    admin = setup(client)
    before = len(product.list_users())
    response = client.post(
        "/v1/users",
        headers=bearer(admin),
        json={"display_name": "Unapproved user"},
    )
    assert response.status_code in {403, 404, 409}, response.text
    assert len(product.list_users()) == before


def test_cors_preflight_allows_authorization_and_auth_errors_remain_readable(
    identity_app,
) -> None:
    client, _ = identity_app
    setup(client)
    preflight = client.options(
        "/v1/workspaces",
        headers={
            "Origin": ALLOWED_ORIGIN,
            "Access-Control-Request-Method": "GET",
            "Access-Control-Request-Headers": "authorization",
        },
    )
    assert preflight.status_code == 200, preflight.text
    assert preflight.headers["access-control-allow-origin"] == ALLOWED_ORIGIN
    assert "authorization" in preflight.headers["access-control-allow-headers"].lower()
    denied = client.get("/v1/workspaces", headers={"Origin": ALLOWED_ORIGIN})
    assert_error(denied, "identity_authentication_failed", 401)
    assert denied.headers["access-control-allow-origin"] == ALLOWED_ORIGIN


@pytest.mark.parametrize("endpoint", ["setup", "register", "login"])
@pytest.mark.parametrize(
    "browser_headers",
    [
        {"Origin": "https://untrusted.example"},
        {"Sec-Fetch-Site": "cross-site"},
    ],
)
def test_public_identity_writes_still_reject_cross_site_requests(
    identity_app,
    endpoint: str,
    browser_headers: dict,
) -> None:
    client, _ = identity_app
    payload = (
        account()
        if endpoint != "login"
        else {
            "login_name": "administrator",
            "password": PASSWORD,
        }
    )
    response = client.post(
        f"/v1/identity/{endpoint}",
        json=payload,
        headers={"X-VisionData-Session-Token": STARTUP_CAPABILITY, **browser_headers},
    )
    assert response.status_code == 403, response.text
    assert PASSWORD not in response.text


def test_logout_revokes_only_the_current_session(identity_app) -> None:
    client, _ = identity_app
    first = setup(client)
    second = login(client, "administrator")
    response = client.post("/v1/identity/logout", headers=bearer(first))
    assert response.status_code == 204
    assert not response.content
    assert_error(
        client.get("/v1/identity/me", headers=bearer(first)),
        "identity_authentication_failed",
        401,
    )
    assert client.get("/v1/identity/me", headers=bearer(second)).status_code == 200


def test_password_change_revokes_all_sessions_and_preserves_exact_password(
    identity_app,
) -> None:
    client, _ = identity_app
    first = setup(client)
    second = login(client, "administrator")
    new_password = f"  {NEW_PASSWORD}  "
    response = client.post(
        "/v1/identity/password",
        headers=bearer(first),
        json={"current_password": PASSWORD, "new_password": new_password},
    )
    assert response.status_code == 204, response.text
    for token in (first, second):
        assert_error(
            client.get("/v1/identity/me", headers=bearer(token)),
            "identity_authentication_failed",
            401,
        )
    for password in (PASSWORD, NEW_PASSWORD):
        rejected = client.post(
            "/v1/identity/login",
            json={"login_name": "administrator", "password": password},
        )
        assert_error(rejected, "identity_authentication_failed", 401)
    login(client, "administrator", new_password)


def test_session_list_contains_metadata_only_and_current_session_can_be_revoked(
    identity_app,
) -> None:
    client, _ = identity_app
    admin = setup(client)
    sessions = client.get("/v1/identity/sessions", headers=bearer(admin))
    assert sessions.status_code == 200, sessions.text
    assert set(sessions.json()) == {"sessions"}
    current = [item for item in sessions.json()["sessions"] if item["is_current"]]
    assert len(current) == 1
    assert set(current[0]) == {
        "session_id",
        "created_at",
        "expires_at",
        "revoked_at",
        "is_current",
    }
    lifetime = datetime.fromisoformat(
        current[0]["expires_at"]
    ) - datetime.fromisoformat(current[0]["created_at"])
    assert lifetime == timedelta(hours=8)
    assert admin["access_token"] not in sessions.text
    deleted = client.delete(
        f"/v1/identity/sessions/{current[0]['session_id']}",
        headers=bearer(admin),
    )
    assert deleted.status_code == 204
    assert_error(
        client.get("/v1/identity/me", headers=bearer(admin)),
        "identity_authentication_failed",
        401,
    )


def test_workspace_membership_requires_actual_owner_not_platform_admin(
    identity_app,
) -> None:
    client, product = identity_app
    admin = setup(client)
    owner = register(client, "independent-owner")
    member = register(client, "member-user")
    for user in (owner, member):
        approve(client, admin, user)
    owner_session = login(client, owner["login_name"])
    workspace = product.create_workspace(
        CreateWorkspaceRequest(
            name="Independent workspace",
            owner_user_id=owner["user_id"],
        )
    )
    path = f"/v1/identity/workspaces/{workspace.workspace_id}/members"
    for method, target, kwargs in (
        ("GET", path, {}),
        ("PUT", f"{path}/{member['user_id']}", {"json": {"role": "member"}}),
        ("DELETE", f"{path}/{owner['user_id']}", {}),
    ):
        denied = client.request(method, target, headers=bearer(admin), **kwargs)
        assert_error(denied, "identity_forbidden", 403)
    joined = client.put(
        f"{path}/{member['user_id']}",
        headers=bearer(owner_session),
        json={"role": "member"},
    )
    assert joined.status_code == 200, joined.text
    assert {item["user_id"]: item["role"] for item in joined.json()["members"]} == {
        owner["user_id"]: "owner",
        member["user_id"]: "member",
    }
    owner_removal = client.delete(
        f"{path}/{owner['user_id']}", headers=bearer(owner_session)
    )
    assert owner_removal.status_code in {403, 409}
    removed = client.delete(
        f"{path}/{member['user_id']}", headers=bearer(owner_session)
    )
    assert removed.status_code == 204
    assert product.list_workspaces(member["user_id"]) == []


def test_expired_session_is_rejected_at_absolute_expiry(
    identity_app,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import visiondata_gate.identity_service as identity_service

    client, _ = identity_app
    admin = setup(client)
    monkeypatch.setattr(identity_service, "_now", lambda: admin["expires_at"])
    response = client.get("/v1/identity/me", headers=bearer(admin))
    assert_error(response, "identity_authentication_failed", 401)


def test_disabling_revokes_sessions_and_reactivation_does_not_revive_them(
    identity_app,
) -> None:
    client, _ = identity_app
    admin = setup(client)
    user = register(client)
    approve(client, admin, user)
    old_session = login(client, user["login_name"])
    path = f"/v1/identity/admin/users/{user['user_id']}/status"
    disabled = client.put(path, headers=bearer(admin), json={"status": "DISABLED"})
    assert disabled.status_code == 200
    assert_error(
        client.get("/v1/identity/me", headers=bearer(old_session)),
        "identity_authentication_failed",
        401,
    )
    reactivated = client.put(path, headers=bearer(admin), json={"status": "ACTIVE"})
    assert reactivated.status_code == 200
    assert_error(
        client.get("/v1/identity/me", headers=bearer(old_session)),
        "identity_authentication_failed",
        401,
    )
    login(client, user["login_name"])


def test_even_platform_admin_cannot_revoke_another_users_session(identity_app) -> None:
    client, _ = identity_app
    admin = setup(client)
    user = register(client)
    approve(client, admin, user)
    user_session = login(client, user["login_name"])
    listing = client.get("/v1/identity/sessions", headers=bearer(user_session))
    assert listing.status_code == 200
    session_id = next(
        item["session_id"] for item in listing.json()["sessions"] if item["is_current"]
    )
    denied = client.delete(f"/v1/identity/sessions/{session_id}", headers=bearer(admin))
    assert_error(denied, "identity_forbidden", 403)
    assert (
        client.get("/v1/identity/me", headers=bearer(user_session)).status_code == 200
    )


def test_wrong_current_password_does_not_revoke_or_change_credentials(
    identity_app,
) -> None:
    client, _ = identity_app
    admin = setup(client)
    denied = client.post(
        "/v1/identity/password",
        headers=bearer(admin),
        json={
            "current_password": "incorrect synthetic password",
            "new_password": NEW_PASSWORD,
        },
    )
    assert_error(denied, "identity_authentication_failed", 401)
    assert client.get("/v1/identity/me", headers=bearer(admin)).status_code == 200
    login(client, "administrator")


def test_pending_account_cannot_skip_approval_or_receive_membership(
    identity_app,
) -> None:
    client, _ = identity_app
    admin = setup(client)
    pending = register(client)
    root = f"/v1/identity/admin/users/{pending['user_id']}"
    for suffix, body in (
        ("status", {"status": "ACTIVE"}),
        ("role", {"platform_role": "ADMIN"}),
    ):
        denied = client.put(f"{root}/{suffix}", headers=bearer(admin), json=body)
        assert_error(denied, "identity_conflict", 409)
    membership = client.put(
        f"/v1/identity/workspaces/wsp_local_demo/members/{pending['user_id']}",
        headers=bearer(admin),
        json={"role": "member"},
    )
    assert_error(membership, "identity_conflict", 409)
    assert client.get("/v1/identity/me", headers=bearer(admin)).status_code == 200


@pytest.mark.parametrize(
    ("method", "path", "body"),
    [
        ("POST", "/v1/identity/admin/users/usr_missing/approve", None),
        ("PUT", "/v1/identity/admin/users/usr_missing/status", {"status": "ACTIVE"}),
        ("PUT", "/v1/identity/admin/users/usr_missing/role", {"platform_role": "USER"}),
        (
            "PUT",
            "/v1/identity/workspaces/wsp_local_demo/members/usr_missing",
            {"role": "member"},
        ),
    ],
)
def test_unknown_managed_target_does_not_invalidate_callers_session(
    identity_app,
    method: str,
    path: str,
    body: dict | None,
) -> None:
    client, _ = identity_app
    admin = setup(client)
    response = client.request(method, path, headers=bearer(admin), json=body)
    assert_error(response, "identity_conflict", 409)
    assert client.get("/v1/identity/me", headers=bearer(admin)).status_code == 200


def test_login_rate_limit_has_safe_error_and_retry_after(identity_app) -> None:
    client, _ = identity_app
    setup(client)
    responses = [
        client.post(
            "/v1/identity/login",
            json={
                "login_name": "nonexistent-user",
                "password": "incorrect synthetic password",
            },
        )
        for _ in range(11)
    ]
    for response in responses[:10]:
        assert_error(response, "identity_authentication_failed", 401)
    assert_error(responses[-1], "identity_rate_limited", 429)
    assert int(responses[-1].headers["retry-after"]) > 0


def test_insecure_test_bypass_cannot_authorize_after_setup(
    identity_app,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client, product = identity_app
    setup(client)
    monkeypatch.setenv("VISIONDATA_INSECURE_TEST_ACTOR_HEADER_BYPASS", "true")
    monkeypatch.delenv("VISIONDATA_SESSION_TOKEN")
    app = create_app(product, enable_account_bootstrap=True)
    with TestClient(app, client=("127.0.0.1", 49324)) as insecure_client:
        denied = insecure_client.get(
            "/v1/workspaces",
            headers={"X-Actor-User-Id": "usr_local_demo"},
        )
    assert_error(denied, "identity_authentication_failed", 401)


@pytest.mark.parametrize("host", ["127.0.0.2", "::1"])
def test_setup_accepts_numeric_loopback_addresses(identity_app, host: str) -> None:
    client, _ = identity_app
    with TestClient(client.app, client=(host, 49323)) as loopback:
        response = loopback.post(
            "/v1/identity/setup",
            json=account(),
            headers={"X-VisionData-Session-Token": STARTUP_CAPABILITY},
        )
    assert response.status_code == 201, response.text


def test_default_app_allows_only_authenticated_self_owned_workspace_creation(
    identity_app,
) -> None:
    _, product = identity_app
    app = create_app(product, enable_account_bootstrap=False)
    with TestClient(app, client=("127.0.0.1", 49325)) as client:
        before = client.post(
            "/v1/workspaces",
            headers={"X-VisionData-Session-Token": STARTUP_CAPABILITY},
            json={"name": "Not initialized", "owner_user_id": "usr_local_demo"},
        )
        assert before.status_code == 404, before.text
        admin = setup(client)
        user = register(client, "independent-user")
        approve(client, admin, user)
        session = login(client, user["login_name"])
        assert client.get("/v1/workspaces", headers=bearer(session)).json() == []
        created = client.post(
            "/v1/workspaces",
            headers=bearer(session),
            json={"name": "My isolated workspace", "owner_user_id": user["user_id"]},
        )
        assert created.status_code == 201, created.text
        workspace = created.json()
        assert workspace["owner_user_id"] == user["user_id"]
        members = client.get(
            f"/v1/identity/workspaces/{workspace['workspace_id']}/members",
            headers=bearer(session),
        )
        assert members.status_code == 200, members.text
        assert members.json()["members"] == [
            {
                "user_id": user["user_id"],
                "display_name": user["display_name"],
                "role": "owner",
            }
        ]
        workspaces = client.get("/v1/workspaces", headers=bearer(session)).json()
        assert [item["workspace_id"] for item in workspaces] == [
            workspace["workspace_id"]
        ]
        assert workspace["workspace_id"] not in {
            item["workspace_id"]
            for item in client.get(
                "/v1/workspaces",
                headers=bearer(admin),
            ).json()
        }
        cross_owner = client.post(
            "/v1/workspaces",
            headers=bearer(session),
            json={"name": "Spoofed owner", "owner_user_id": admin["user"]["user_id"]},
        )
        assert cross_owner.status_code == 404, cross_owner.text
        with product.store._connection() as connection:
            assert (
                connection.execute("SELECT COUNT(*) FROM workspaces").fetchone()[0] == 2
            )


def test_workspace_create_rechecks_active_actor_after_http_authentication(
    identity_app,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from visiondata_gate.identity_service import IdentityService

    client, product = identity_app
    admin = setup(client)
    user = register(client, "workspace-creator")
    approve(client, admin, user)
    session = login(client, user["login_name"])
    identity = IdentityService(product)
    original_create = product.create_workspace
    with product.store._connection() as connection:
        before_workspaces = connection.execute(
            "SELECT COUNT(*) FROM workspaces"
        ).fetchone()[0]
        before_members = connection.execute(
            "SELECT COUNT(*) FROM workspace_members"
        ).fetchone()[0]

    def disable_before_transaction(request):
        identity.set_status(admin["user"]["user_id"], user["user_id"], "DISABLED")
        return original_create(request)

    monkeypatch.setattr(product, "create_workspace", disable_before_transaction)
    response = client.post(
        "/v1/workspaces",
        headers=bearer(session),
        json={"name": "Must not be created", "owner_user_id": user["user_id"]},
    )
    assert_error(response, "identity_authentication_failed", 401)
    with product.store._connection() as connection:
        assert (
            connection.execute("SELECT COUNT(*) FROM workspaces").fetchone()[0]
            == before_workspaces
        )
        assert (
            connection.execute("SELECT COUNT(*) FROM workspace_members").fetchone()[0]
            == before_members
        )
