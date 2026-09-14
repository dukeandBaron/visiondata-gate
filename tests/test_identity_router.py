"""HTTP-only identity contract tests; storage policy is tested in the service suite."""

from __future__ import annotations

import importlib
import importlib.util
import inspect

from fastapi import FastAPI, HTTPException, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from fastapi.routing import APIRoute
from fastapi.testclient import TestClient
import pytest

from visiondata_gate.identity_service import IdentityError


PASSWORD = "  synthetic password 42  "
USER = {
    "user_id": "usr_authenticated",
    "login_name": "alice",
    "display_name": "Alice",
    "email": None,
    "platform_role": "USER",
    "status": "ACTIVE",
    "created_at": "2026-09-12T00:00:00+00:00",
}
TOKEN = {
    "user": USER,
    "access_token": "synthetic-token",
    "token_type": "Bearer",
    "expires_at": "2026-09-12T08:00:00+00:00",
}
STATUS = {
    "setup_required": False,
    "identity_required": True,
    "registration_policy": "ADMIN_APPROVAL",
    "authentication_mode": "USER_SESSION",
    "startup_capability_required": True,
}
SESSION = {
    "session_id": "sid_current",
    "created_at": USER["created_at"],
    "expires_at": TOKEN["expires_at"],
    "revoked_at": None,
    "is_current": True,
}
MEMBER = {"user_id": "usr_target", "display_name": "Target", "role": "member"}


class RecordingIdentityService:
    """Boundary double: return contract records and capture route dispatch only."""

    def __init__(self):
        self.calls = []
        self.responses = {
            "status": STATUS,
            "setup": TOKEN,
            "register": {**USER, "platform_role": "USER", "status": "PENDING"},
            "login": TOKEN,
            "get_user": USER,
            "list_sessions": [SESSION],
            "list_users": [USER],
            "approve": USER,
            "set_status": USER,
            "set_role": USER,
            "list_members": [MEMBER],
            "add_member": [MEMBER],
        }

    def __getattr__(self, name):
        def operation(*args, **kwargs):
            self.calls.append((name, args, kwargs))
            return self.responses.get(name)

        return operation


@pytest.fixture
def router_module():
    assert importlib.util.find_spec("visiondata_gate.identity_api") is not None, (
        "The identity HTTP router has not been implemented"
    )
    return importlib.import_module("visiondata_gate.identity_api")


@pytest.fixture
def harness(router_module):
    app = FastAPI()
    service = RecordingIdentityService()
    state = {
        "dependencies": [],
        "deny_actor": False,
        "deny_setup": False,
        "principal": {"user_id": USER["user_id"], "session_id": "sid_current"},
    }

    @app.middleware("http")
    async def host_principal(request, call_next):
        request.state.identity_principal = state["principal"]
        response = await call_next(request)
        response.headers["Cache-Control"] = "private, no-store"
        return response

    @app.exception_handler(RequestValidationError)
    def safe_validation(_request, _error):
        return JSONResponse(
            status_code=422,
            content={"error": {"code": "invalid_request", "message": "invalid schema"}},
        )

    @app.exception_handler(IdentityError)
    def safe_identity_error(_request, error):
        headers = {"Retry-After": str(error.retry_after)} if error.retry_after else {}
        return JSONResponse(
            status_code=error.status_code,
            content={
                "error": {"code": error.code, "message": "identity request rejected"}
            },
            headers=headers,
        )

    def identity_dependency(request: Request):
        state["dependencies"].append(("service", request.url.path))
        return service

    def actor_dependency(request: Request):
        state["dependencies"].append(("actor", request.url.path))
        if state["deny_actor"]:
            raise HTTPException(401)
        return USER["user_id"]

    def setup_dependency(request: Request):
        state["dependencies"].append(("setup", request.url.path))
        if state["deny_setup"]:
            raise HTTPException(403)
        return "usr_startup_bound"

    router_module.install_identity_routes(
        app, actor_dependency, identity_dependency, setup_dependency
    )
    with TestClient(app, client=("127.0.0.1", 43210)) as client:
        yield app, client, service, state


def account(**changes):
    return {
        "login_name": "  ALICE  ",
        "display_name": "  Alice  ",
        "password": PASSWORD,
        **changes,
    }


def test_status_is_public_exact_and_does_not_initialize_storage(harness):
    _, client, service, state = harness
    assert service.calls == []
    response = client.get("/v1/identity/status")
    assert response.status_code == 200
    assert response.json() == STATUS
    assert state["dependencies"] == [("service", "/v1/identity/status")]


@pytest.mark.parametrize("route", ["setup", "register"])
def test_account_creation_normalizes_only_non_secrets_and_uses_bound_actor(
    harness, route
):
    _, client, service, state = harness
    response = client.post(f"/v1/identity/{route}", json=account())
    assert response.status_code == 201
    expected = {
        "login_name": "alice",
        "display_name": "Alice",
        "password": PASSWORD,
        "email": None,
    }
    expected_args = ("usr_startup_bound",) if route == "setup" else ()
    assert service.calls == [
        ("throttle", (route, "127.0.0.1", 5, 600), {}),
        (route, expected_args, expected),
    ]
    assert all(kind != "actor" for kind, _ in state["dependencies"])
    assert (
        ("setup", f"/v1/identity/{route}") in state["dependencies"]
        if route == "setup"
        else all(kind != "setup" for kind, _ in state["dependencies"])
    )
    assert response.json() == (TOKEN if route == "setup" else service.responses[route])


def test_login_preserves_password_and_throttles_actual_peer_not_forwarded(harness):
    _, client, service, state = harness
    response = client.post(
        "/v1/identity/login",
        json={"login_name": "  ALICE  ", "password": PASSWORD},
        headers={"X-Forwarded-For": "198.51.100.9", "X-Real-IP": "203.0.113.5"},
    )
    assert response.status_code == 200
    assert response.json() == TOKEN
    assert service.calls == [
        ("throttle", ("login", "127.0.0.1", 30, 60), {}),
        ("login", (), {"login_name": "alice", "password": PASSWORD}),
    ]
    assert all(kind == "service" for kind, _ in state["dependencies"])


@pytest.mark.parametrize(
    "method,path,body,operation,args,expected,status_code",
    [
        ("GET", "/me", None, "get_user", (), USER, 200),
        ("POST", "/logout", None, "revoke_session", ("sid_current",), None, 204),
        (
            "GET",
            "/sessions",
            None,
            "list_sessions",
            ("sid_current",),
            {"sessions": [SESSION]},
            200,
        ),
        (
            "DELETE",
            "/sessions/sid_target",
            None,
            "revoke_session",
            ("sid_target",),
            None,
            204,
        ),
        ("GET", "/admin/users", None, "list_users", (), {"users": [USER]}, 200),
        (
            "POST",
            "/admin/users/usr_target/approve",
            None,
            "approve",
            ("usr_target",),
            USER,
            200,
        ),
        (
            "PUT",
            "/admin/users/usr_target/status",
            {"status": "DISABLED"},
            "set_status",
            ("usr_target", "DISABLED"),
            USER,
            200,
        ),
        (
            "PUT",
            "/admin/users/usr_target/role",
            {"platform_role": "ADMIN"},
            "set_role",
            ("usr_target", "ADMIN"),
            USER,
            200,
        ),
        (
            "GET",
            "/workspaces/wsp_target/members",
            None,
            "list_members",
            ("wsp_target",),
            {"members": [MEMBER]},
            200,
        ),
        (
            "PUT",
            "/workspaces/wsp_target/members/usr_target",
            {"role": "member"},
            "add_member",
            ("wsp_target", "usr_target"),
            {"members": [MEMBER]},
            200,
        ),
        (
            "DELETE",
            "/workspaces/wsp_target/members/usr_target",
            None,
            "remove_member",
            ("wsp_target", "usr_target"),
            None,
            204,
        ),
    ],
)
def test_private_routes_use_host_actor_and_exact_service_contract(
    harness, method, path, body, operation, args, expected, status_code
):
    _, client, service, state = harness
    response = client.request(
        method,
        "/v1/identity" + path,
        json=body,
        headers={"X-Actor-User-Id": "usr_spoofed"},
    )
    assert response.status_code == status_code
    assert (
        response.json() == expected if expected is not None else response.content == b""
    )
    assert service.calls == [(operation, (USER["user_id"], *args), {})]
    assert ("actor", "/v1/identity" + path) in state["dependencies"]


def test_password_change_uses_secret_fields_and_peer_limit(harness):
    _, client, service, _ = harness
    response = client.post(
        "/v1/identity/password",
        json={"current_password": PASSWORD, "new_password": PASSWORD + " new"},
    )
    assert response.status_code == 204
    assert response.content == b""
    assert service.calls == [
        ("throttle", ("password", "127.0.0.1", 10, 600), {}),
        ("change_password", (USER["user_id"], PASSWORD, PASSWORD + " new"), {}),
    ]


@pytest.mark.parametrize(
    "change",
    [
        {"actor_user_id": "usr_victim"},
        {"platform_role": "ADMIN"},
        {"status": "ACTIVE"},
        {"login_name": "ab"},
        {"login_name": "a" * 65},
        {"login_name": ".alice"},
        {"login_name": "Ａlice"},
        {"login_name": "aKice"},
        {"login_name": "alice/name"},
        {"login_name": 12345},
        {"display_name": "  "},
        {"display_name": "a" * 121},
        {"password": "short"},
        {"password": "x" * 257},
        {"password": 123456789012},
        {"email": "invalid"},
        {"email": "x@localhost"},
        {"email": "x@example.com\r\nInjected:value"},
        {"email": "x" * 255 + "@example.com"},
    ],
)
def test_account_rejects_unexpected_or_invalid_values_without_secret_echo(
    harness, change
):
    _, client, service, _ = harness
    response = client.post("/v1/identity/register", json=account(**change))
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "invalid_request"
    assert PASSWORD not in response.text
    assert service.calls == []


@pytest.mark.parametrize("password", ["x" * 12, " " * 12, "😀" * 256])
def test_password_valid_boundaries_are_not_trimmed(harness, password):
    _, client, service, _ = harness
    response = client.post("/v1/identity/register", json=account(password=password))
    assert response.status_code == 201
    assert service.calls[-1][2]["password"] == password


@pytest.mark.parametrize(
    "path,payload",
    [
        ("/login", {"login_name": "alice", "password": PASSWORD, "user_id": "other"}),
        ("/password", {"current_password": PASSWORD, "new_password": "short"}),
        (
            "/password",
            {
                "current_password": PASSWORD,
                "new_password": PASSWORD,
                "session_id": "other",
            },
        ),
        ("/admin/users/usr_target/status", {"status": "PENDING"}),
        ("/admin/users/usr_target/role", {"platform_role": "OWNER"}),
        ("/workspaces/wsp_target/members/usr_target", {"role": "owner"}),
        (
            "/workspaces/wsp_target/members/usr_target",
            {"role": "member", "actor": "other"},
        ),
    ],
)
def test_other_mutation_bodies_reject_invalid_and_extra_fields(harness, path, payload):
    _, client, service, _ = harness
    method = "POST" if path in {"/login", "/password"} else "PUT"
    response = client.request(method, "/v1/identity" + path, json=payload)
    assert response.status_code == 422
    assert service.calls == []


def test_setup_dependency_denial_prevents_any_service_operation(harness):
    _, client, service, state = harness
    state["deny_setup"] = True
    response = client.post("/v1/identity/setup", json=account())
    assert response.status_code == 403
    assert service.calls == []


@pytest.mark.parametrize(
    "method,path,body",
    [
        ("GET", "/me", None),
        ("POST", "/logout", None),
        ("POST", "/password", {"current_password": PASSWORD, "new_password": PASSWORD}),
        ("GET", "/sessions", None),
        ("DELETE", "/sessions/sid_target", None),
        ("GET", "/admin/users", None),
        ("POST", "/admin/users/usr_target/approve", None),
        ("PUT", "/admin/users/usr_target/status", {"status": "ACTIVE"}),
        ("PUT", "/admin/users/usr_target/role", {"platform_role": "USER"}),
        ("GET", "/workspaces/wsp_target/members", None),
        ("PUT", "/workspaces/wsp_target/members/usr_target", {"role": "member"}),
        ("DELETE", "/workspaces/wsp_target/members/usr_target", None),
    ],
)
def test_every_private_route_honors_host_authentication_denial(
    harness, method, path, body
):
    _, client, service, state = harness
    state["deny_actor"] = True
    response = client.request(method, "/v1/identity" + path, json=body)
    assert response.status_code == 401
    assert service.calls == []


def test_openapi_response_shapes_are_explicit_and_have_no_credential_internals(harness):
    app, _, _, _ = harness
    schema = app.openapi()
    models = schema["components"]["schemas"]
    assert set(models["PublicUser"]["properties"]) == set(USER)
    assert set(models["TokenResponse"]["properties"]) == set(TOKEN)
    assert set(models["IdentityStatusResponse"]["properties"]) == set(STATUS)
    assert set(models["PublicSession"]["properties"]) == set(SESSION)
    for name in (
        "PublicUser",
        "TokenResponse",
        "IdentityStatusResponse",
        "PublicSession",
        "AccountInput",
        "LoginInput",
        "PasswordChangeInput",
        "UserStatusInput",
        "UserRoleInput",
        "WorkspaceMemberInput",
    ):
        assert models[name]["additionalProperties"] is False
    for name, fields in (
        ("AccountInput", ("password",)),
        ("LoginInput", ("password",)),
        ("PasswordChangeInput", ("current_password", "new_password")),
    ):
        for field in fields:
            assert models[name]["properties"][field]["writeOnly"] is True
            assert models[name]["properties"][field]["format"] == "password"
    assert schema["paths"]["/v1/identity/me"]["get"]["responses"]["200"]["content"][
        "application/json"
    ]["schema"] == {"$ref": "#/components/schemas/PublicUser"}
    routes = [route for route in app.routes if isinstance(route, APIRoute)]
    assert len(routes) == 16
    assert all(not inspect.iscoroutinefunction(route.endpoint) for route in routes)
    for route in routes:
        if route.status_code != 204:
            assert route.response_model is not None


def test_secret_dto_representation_is_redacted(router_module):
    payload = router_module.AccountInput(**account())
    assert PASSWORD not in repr(payload)
    assert PASSWORD not in payload.model_dump_json()
    assert payload.password.get_secret_value() == PASSWORD


@pytest.mark.parametrize(
    "principal",
    [
        None,
        {},
        {"user_id": "usr_other", "session_id": "sid_other"},
        {"user_id": USER["user_id"], "session_id": ""},
        {"user_id": USER["user_id"], "session_id": 123},
    ],
)
@pytest.mark.parametrize("method,path", [("POST", "/logout"), ("GET", "/sessions")])
def test_current_session_routes_fail_closed_for_invalid_host_principal(
    harness, principal, method, path
):
    _, client, service, state = harness
    state["principal"] = principal
    response = client.request(method, "/v1/identity" + path)
    assert response.status_code == 401
    assert response.json()["error"]["code"] == "identity_authentication_failed"
    assert service.calls == []


def test_throttling_rejection_prevents_password_operation(harness, monkeypatch):
    _, client, service, _ = harness

    def deny(*_args):
        raise IdentityError("identity_rate_limited", 429, retry_after=37)

    monkeypatch.setattr(service, "throttle", deny)
    response = client.post(
        "/v1/identity/login", json={"login_name": "alice", "password": PASSWORD}
    )
    assert response.status_code == 429
    assert response.headers["Retry-After"] == "37"
    assert service.calls == []
    assert PASSWORD not in response.text


def test_response_contract_rejects_internal_credential_fields_without_exposure(harness):
    app, _, service, _ = harness
    service.responses["get_user"] = {
        **USER,
        "password_hash": "synthetic-sensitive-internal",
    }
    with TestClient(app, raise_server_exceptions=False) as client:
        response = client.get("/v1/identity/me")
    assert response.status_code == 500
    assert "synthetic-sensitive-internal" not in response.text


def test_optional_email_is_trimmed_without_claiming_verification(harness):
    _, client, service, _ = harness
    response = client.post(
        "/v1/identity/register", json=account(email="  Alice@example.com  ")
    )
    assert response.status_code == 201
    assert service.calls[-1][2]["email"] == "Alice@example.com"
    assert "verified" not in response.text


def test_invalid_unicode_password_is_rejected_with_safe_validation(router_module):
    with pytest.raises(ValueError) as error:
        router_module.AccountInput(**account(password="unpaired synthetic \ud800"))
    assert "unpaired synthetic" not in str(error.value)


def test_openapi_documents_safe_error_envelope_instead_of_input_echo(harness):
    app, _, _, _ = harness
    for path, methods in app.openapi()["paths"].items():
        if not path.startswith("/v1/identity/"):
            continue
        for operation in methods.values():
            for code in ("401", "403", "409", "422", "429"):
                response = operation["responses"][code]
                assert response["content"]["application/json"]["schema"] == {
                    "$ref": "#/components/schemas/ErrorEnvelope"
                }
            assert "Retry-After" in operation["responses"]["429"]["headers"]


@pytest.mark.parametrize(
    "path,payload,method",
    [
        ("login", {"login_name": "alice", "password": "x"}, "login"),
        (
            "password",
            {"current_password": "x", "new_password": PASSWORD},
            "change_password",
        ),
    ],
)
def test_short_incorrect_existing_passwords_reach_uniform_authentication_failure(
    harness, monkeypatch, path, payload, method
):
    _, client, service, _ = harness

    def fail_credentials(*_args, **_kwargs):
        raise IdentityError("identity_authentication_failed", 401)

    monkeypatch.setattr(service, method, fail_credentials)
    response = client.post("/v1/identity/" + path, json=payload)
    assert response.status_code == 401
    assert response.json()["error"]["code"] == "identity_authentication_failed"
