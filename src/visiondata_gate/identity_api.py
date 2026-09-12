"""Typed HTTP boundary for local identity; authority stays in the host/service."""

from __future__ import annotations

from collections.abc import Callable
import re
from typing import Annotated, Literal

from fastapi import Depends, FastAPI, Request, Response
from pydantic import (
    AfterValidator,
    BaseModel,
    BeforeValidator,
    ConfigDict,
    Field,
    SecretStr,
)

from .identity_service import IdentityError
from .product_models import ErrorEnvelope


_IDENTITY_ERRORS = {
    401: {"model": ErrorEnvelope, "description": "Authentication failed"},
    403: {"model": ErrorEnvelope, "description": "Identity authority required"},
    409: {"model": ErrorEnvelope, "description": "Identity state conflict"},
    422: {"model": ErrorEnvelope, "description": "Invalid request schema"},
    429: {
        "model": ErrorEnvelope,
        "description": "Identity request rate limited",
        "headers": {"Retry-After": {"schema": {"type": "integer", "minimum": 1}}},
    },
}


def _trim(value: object) -> object:
    return value.strip() if isinstance(value, str) else value


def _login_name(value: object) -> object:
    if not isinstance(value, str):
        return value
    value = value.strip()
    # Validate ASCII before lowercasing: Unicode case folding must not create IDs.
    if re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]{2,63}", value) is None:
        raise ValueError("invalid login name")
    return value.lower()


def _password_bytes(value: SecretStr) -> SecretStr:
    try:
        encoded = value.get_secret_value().encode("utf-8")
    except UnicodeEncodeError:
        raise ValueError("invalid password encoding") from None
    if len(encoded) > 1024:
        raise ValueError("password exceeds the accepted size")
    return value


def _email(value: str | None) -> str | None:
    if value is None:
        return None
    # This is bounded syntactic validation only; no DNS or email verification.
    if (
        re.fullmatch(
            r"[^\s@\x00-\x1f\x7f]{1,64}@[^\s@\x00-\x1f\x7f.]+(?:\.[^\s@\x00-\x1f\x7f.]+)+",
            value,
        )
        is None
    ):
        raise ValueError("invalid email address")
    return value


LoginName = Annotated[
    str,
    Field(min_length=3, max_length=64, pattern=r"^[a-z0-9][a-z0-9_.-]{2,63}$"),
    BeforeValidator(_login_name),
]
Password = Annotated[
    SecretStr, Field(min_length=12, max_length=256), AfterValidator(_password_bytes)
]
ExistingPassword = Annotated[
    SecretStr, Field(min_length=1, max_length=256), AfterValidator(_password_bytes)
]
DisplayName = Annotated[
    str, Field(min_length=1, max_length=120), BeforeValidator(_trim)
]
Email = Annotated[
    str | None, Field(max_length=254), BeforeValidator(_trim), AfterValidator(_email)
]


class IdentityModel(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, hide_input_in_errors=True)


class AccountInput(IdentityModel):
    login_name: LoginName
    display_name: DisplayName
    password: Password
    email: Email = None


class LoginInput(IdentityModel):
    login_name: LoginName
    password: ExistingPassword


class PasswordChangeInput(IdentityModel):
    current_password: ExistingPassword
    new_password: Password


class UserStatusInput(IdentityModel):
    status: Literal["ACTIVE", "DISABLED"]


class UserRoleInput(IdentityModel):
    platform_role: Literal["ADMIN", "USER"]


class WorkspaceMemberInput(IdentityModel):
    role: Literal["member"]


class PublicUser(IdentityModel):
    user_id: str
    login_name: str
    display_name: str
    email: str | None
    platform_role: Literal["ADMIN", "USER"]
    status: Literal["PENDING", "ACTIVE", "DISABLED"]
    created_at: str


class TokenResponse(IdentityModel):
    user: PublicUser
    access_token: str
    token_type: Literal["Bearer"]
    expires_at: str


class IdentityStatusResponse(IdentityModel):
    setup_required: bool
    identity_required: bool
    registration_policy: Literal["ADMIN_APPROVAL"]
    authentication_mode: Literal["SETUP_REQUIRED", "USER_SESSION"]
    startup_capability_required: Literal[True]


class PublicSession(IdentityModel):
    session_id: str
    created_at: str
    expires_at: str
    revoked_at: str | None
    is_current: bool


class SessionsResponse(IdentityModel):
    sessions: list[PublicSession]


class UsersResponse(IdentityModel):
    users: list[PublicUser]


class WorkspaceMember(IdentityModel):
    user_id: str
    display_name: str
    role: Literal["owner", "member"]


class MembersResponse(IdentityModel):
    members: list[WorkspaceMember]


def _account_values(payload: AccountInput) -> dict[str, str | None]:
    # Never serialize a credential model wholesale or log this internal mapping.
    return {
        "login_name": payload.login_name,
        "display_name": payload.display_name,
        "password": payload.password.get_secret_value(),
        "email": payload.email,
    }


def _peer(request: Request) -> str:
    # Forwarded headers are not trusted client identity; absent peers share a bucket.
    return request.client.host if request.client is not None else "unknown-peer"


def _current_session_id(request: Request, actor: str) -> str:
    principal = getattr(request.state, "identity_principal", None)
    if (
        not isinstance(principal, dict)
        or principal.get("user_id") != actor
        or not isinstance(principal.get("session_id"), str)
        or not principal["session_id"]
    ):
        raise IdentityError("identity_authentication_failed", 401)
    return principal["session_id"]


def install_identity_routes(
    app: FastAPI,
    actor_dependency: Callable,
    identity_dependency: Callable,
    setup_dependency: Callable,
) -> None:
    """Install routes without initializing storage or duplicating authentication.

    Host dependencies authenticate actors and enforce loopback startup capability.
    The host also owns safe exceptions, no-store, Origin and global private-route
    protections. Handlers stay synchronous so password KDFs run off the event loop.
    """

    @app.get(
        "/v1/identity/status",
        response_model=IdentityStatusResponse,
        tags=["identity"],
        responses=_IDENTITY_ERRORS,
    )
    def identity_status(identity=Depends(identity_dependency)) -> dict:
        return identity.status()

    @app.post(
        "/v1/identity/setup",
        response_model=TokenResponse,
        status_code=201,
        responses=_IDENTITY_ERRORS,
        tags=["identity"],
    )
    def setup(
        payload: AccountInput,
        request: Request,
        bootstrap_actor: str = Depends(setup_dependency),
        identity=Depends(identity_dependency),
    ) -> dict:
        identity.throttle("setup", _peer(request), 5, 600)
        return identity.setup(bootstrap_actor, **_account_values(payload))

    @app.post(
        "/v1/identity/register",
        response_model=PublicUser,
        status_code=201,
        responses=_IDENTITY_ERRORS,
        tags=["identity"],
    )
    def register(
        payload: AccountInput,
        request: Request,
        identity=Depends(identity_dependency),
    ) -> dict:
        identity.throttle("register", _peer(request), 5, 600)
        return identity.register(**_account_values(payload))

    @app.post(
        "/v1/identity/login",
        response_model=TokenResponse,
        tags=["identity"],
        responses=_IDENTITY_ERRORS,
    )
    def login(
        payload: LoginInput,
        request: Request,
        identity=Depends(identity_dependency),
    ) -> dict:
        identity.throttle("login", _peer(request), 30, 60)
        return identity.login(
            login_name=payload.login_name, password=payload.password.get_secret_value()
        )

    @app.get(
        "/v1/identity/me",
        response_model=PublicUser,
        tags=["identity"],
        responses=_IDENTITY_ERRORS,
    )
    def me(
        actor: str = Depends(actor_dependency), identity=Depends(identity_dependency)
    ) -> dict:
        return identity.get_user(actor)

    @app.post(
        "/v1/identity/logout",
        status_code=204,
        tags=["identity"],
        responses=_IDENTITY_ERRORS,
    )
    def logout(
        request: Request,
        actor: str = Depends(actor_dependency),
        identity=Depends(identity_dependency),
    ) -> Response:
        identity.revoke_session(actor, _current_session_id(request, actor))
        return Response(status_code=204)

    @app.post(
        "/v1/identity/password",
        status_code=204,
        tags=["identity"],
        responses=_IDENTITY_ERRORS,
    )
    def change_password(
        payload: PasswordChangeInput,
        request: Request,
        actor: str = Depends(actor_dependency),
        identity=Depends(identity_dependency),
    ) -> Response:
        identity.throttle("password", _peer(request), 10, 600)
        identity.change_password(
            actor,
            payload.current_password.get_secret_value(),
            payload.new_password.get_secret_value(),
        )
        return Response(status_code=204)

    @app.get(
        "/v1/identity/sessions",
        response_model=SessionsResponse,
        tags=["identity"],
        responses=_IDENTITY_ERRORS,
    )
    def sessions(
        request: Request,
        actor: str = Depends(actor_dependency),
        identity=Depends(identity_dependency),
    ) -> dict:
        return {
            "sessions": identity.list_sessions(
                actor, _current_session_id(request, actor)
            )
        }

    @app.delete(
        "/v1/identity/sessions/{session_id}",
        status_code=204,
        tags=["identity"],
        responses=_IDENTITY_ERRORS,
    )
    def revoke_session(
        session_id: str,
        actor: str = Depends(actor_dependency),
        identity=Depends(identity_dependency),
    ) -> Response:
        identity.revoke_session(actor, session_id)
        return Response(status_code=204)

    @app.get(
        "/v1/identity/admin/users",
        response_model=UsersResponse,
        tags=["identity"],
        responses=_IDENTITY_ERRORS,
    )
    def users(
        actor: str = Depends(actor_dependency), identity=Depends(identity_dependency)
    ) -> dict:
        return {"users": identity.list_users(actor)}

    @app.post(
        "/v1/identity/admin/users/{user_id}/approve",
        response_model=PublicUser,
        responses=_IDENTITY_ERRORS,
        tags=["identity"],
    )
    def approve_user(
        user_id: str,
        actor: str = Depends(actor_dependency),
        identity=Depends(identity_dependency),
    ) -> dict:
        return identity.approve(actor, user_id)

    @app.put(
        "/v1/identity/admin/users/{user_id}/status",
        response_model=PublicUser,
        responses=_IDENTITY_ERRORS,
        tags=["identity"],
    )
    def set_user_status(
        user_id: str,
        payload: UserStatusInput,
        actor: str = Depends(actor_dependency),
        identity=Depends(identity_dependency),
    ) -> dict:
        return identity.set_status(actor, user_id, payload.status)

    @app.put(
        "/v1/identity/admin/users/{user_id}/role",
        response_model=PublicUser,
        responses=_IDENTITY_ERRORS,
        tags=["identity"],
    )
    def set_user_role(
        user_id: str,
        payload: UserRoleInput,
        actor: str = Depends(actor_dependency),
        identity=Depends(identity_dependency),
    ) -> dict:
        return identity.set_role(actor, user_id, payload.platform_role)

    @app.get(
        "/v1/identity/workspaces/{workspace_id}/members",
        response_model=MembersResponse,
        responses=_IDENTITY_ERRORS,
        tags=["identity"],
    )
    def members(
        workspace_id: str,
        actor: str = Depends(actor_dependency),
        identity=Depends(identity_dependency),
    ) -> dict:
        return {"members": identity.list_members(actor, workspace_id)}

    @app.put(
        "/v1/identity/workspaces/{workspace_id}/members/{user_id}",
        response_model=MembersResponse,
        tags=["identity"],
        responses=_IDENTITY_ERRORS,
    )
    def add_member(
        workspace_id: str,
        user_id: str,
        payload: WorkspaceMemberInput,
        actor: str = Depends(actor_dependency),
        identity=Depends(identity_dependency),
    ) -> dict:
        return {"members": identity.add_member(actor, workspace_id, user_id)}

    @app.delete(
        "/v1/identity/workspaces/{workspace_id}/members/{user_id}",
        status_code=204,
        responses=_IDENTITY_ERRORS,
        tags=["identity"],
    )
    def remove_member(
        workspace_id: str,
        user_id: str,
        actor: str = Depends(actor_dependency),
        identity=Depends(identity_dependency),
    ) -> Response:
        identity.remove_member(actor, workspace_id, user_id)
        return Response(status_code=204)
