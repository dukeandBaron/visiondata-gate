"""Local accounts and revocable opaque sessions; never a production IAM claim.

Credentials share the product transaction boundary, not its legacy users schema.
Passwords use the standard-library PBKDF2 implementation; bearer tokens are random
capabilities whose digests alone are persisted. No model or network is involved.
"""

from __future__ import annotations

import hashlib
import math
import re
import secrets
import sqlite3
import threading
import time
from datetime import datetime, timedelta, timezone
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .product_service import ProductService

KDF_ITERATIONS = 600_000
SESSION_HOURS = 8
_KDF_SLOTS = threading.BoundedSemaphore(4)
_DUMMY_SALT = secrets.token_bytes(32)
_LOGIN_PATTERN = re.compile(r"[a-zA-Z0-9][a-zA-Z0-9_.-]{2,63}", re.ASCII)
_PUBLIC_COLUMNS = (
    "user_id",
    "login_name",
    "display_name",
    "email",
    "platform_role",
    "status",
    "created_at",
)


class IdentityError(RuntimeError):
    """Only stable, non-sensitive codes may cross the identity boundary."""

    def __init__(self, code: str, status_code: int, *, retry_after: int = 0):
        super().__init__(code)
        self.code = code
        self.status_code = status_code
        self.retry_after = retry_after


def _auth_failed() -> IdentityError:
    return IdentityError("identity_authentication_failed", 401)


def _conflict() -> IdentityError:
    return IdentityError("identity_conflict", 409)


def _forbidden() -> IdentityError:
    return IdentityError("identity_forbidden", 403)


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def normalize_login_name(value: str) -> str:
    if not isinstance(value, str) or not _LOGIN_PATTERN.fullmatch(value.strip()):
        raise IdentityError("invalid_request", 422)
    return value.strip().lower()


def _password_bytes(value: str, *, minimum: int = 12) -> bytes:
    if not isinstance(value, str) or not minimum <= len(value) <= 256:
        raise IdentityError("invalid_request", 422)
    try:
        encoded = value.encode("utf-8")
    except UnicodeEncodeError:
        raise IdentityError("invalid_request", 422) from None
    if len(encoded) > 1024:
        raise IdentityError("invalid_request", 422)
    return encoded


def _derive(password: bytes, salt: bytes) -> bytes:
    if not _KDF_SLOTS.acquire(blocking=False):
        raise IdentityError("identity_rate_limited", 429, retry_after=1)
    try:
        return hashlib.pbkdf2_hmac("sha256", password, salt, KDF_ITERATIONS, dklen=32)
    finally:
        _KDF_SLOTS.release()


def identity_enabled_in_connection(connection: sqlite3.Connection) -> bool:
    """Read-only, safe for a caller's existing transaction and legacy databases."""
    exists = connection.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name='identity_state'"
    ).fetchone()
    return bool(
        exists
        and connection.execute(
            "SELECT 1 FROM identity_state WHERE singleton=1"
        ).fetchone()
    )


def assert_active_in_connection(connection: sqlite3.Connection, actor: str) -> None:
    """Account revocation gate; session rotation does not cancel approved work."""
    if not identity_enabled_in_connection(connection):
        return
    row = connection.execute(
        "SELECT status FROM identity_credentials WHERE user_id=?", (actor,)
    ).fetchone()
    if row is None or row["status"] != "ACTIVE":
        raise _auth_failed()


def require_active_actor(product: ProductService, actor: str) -> None:
    with product.store._connection() as connection:
        assert_active_in_connection(connection, actor)


class IdentityService:
    def __init__(self, product: ProductService):
        self.store = product.store
        with self.store._connection() as connection:
            connection.executescript("""
                CREATE TABLE IF NOT EXISTS identity_state (
                    singleton INTEGER PRIMARY KEY CHECK(singleton=1),
                    bootstrap_user_id TEXT NOT NULL REFERENCES users(user_id),
                    schema_version INTEGER NOT NULL CHECK(schema_version=1),
                    initialized_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS identity_credentials (
                    user_id TEXT PRIMARY KEY REFERENCES users(user_id),
                    login_name TEXT NOT NULL UNIQUE,
                    password_salt BLOB NOT NULL,
                    password_hash BLOB NOT NULL,
                    kdf_name TEXT NOT NULL,
                    kdf_iterations INTEGER NOT NULL,
                    credential_version INTEGER NOT NULL,
                    platform_role TEXT NOT NULL CHECK(platform_role IN ('ADMIN','USER')),
                    status TEXT NOT NULL CHECK(status IN ('PENDING','ACTIVE','DISABLED'))
                );
                CREATE TABLE IF NOT EXISTS identity_sessions (
                    session_id TEXT PRIMARY KEY,
                    token_sha256 TEXT NOT NULL UNIQUE,
                    user_id TEXT NOT NULL REFERENCES identity_credentials(user_id),
                    credential_version INTEGER NOT NULL,
                    created_at TEXT NOT NULL,
                    expires_at TEXT NOT NULL,
                    revoked_at TEXT
                );
                CREATE INDEX IF NOT EXISTS identity_sessions_user
                    ON identity_sessions(user_id);
                CREATE TABLE IF NOT EXISTS identity_throttle (
                    scope TEXT NOT NULL,
                    key_sha256 TEXT NOT NULL,
                    expires_at REAL NOT NULL,
                    hits INTEGER NOT NULL,
                    PRIMARY KEY(scope,key_sha256)
                );
                CREATE TABLE IF NOT EXISTS identity_events (
                    event_id TEXT PRIMARY KEY,
                    actor_user_id TEXT NOT NULL,
                    target_user_id TEXT NOT NULL,
                    action TEXT NOT NULL,
                    created_at TEXT NOT NULL
                );
            """)

    def status(self) -> dict:
        with self.store._connection() as connection:
            enabled = identity_enabled_in_connection(connection)
        return {
            "setup_required": not enabled,
            "identity_required": enabled,
            "registration_policy": "ADMIN_APPROVAL",
            "authentication_mode": "USER_SESSION" if enabled else "SETUP_REQUIRED",
            "startup_capability_required": True,
        }

    @staticmethod
    def _event(connection, actor: str, target: str, action: str) -> None:
        connection.execute(
            "INSERT INTO identity_events VALUES (?,?,?,?,?)",
            (
                "ide_" + secrets.token_hex(16),
                actor,
                target,
                action,
                _now(),
            ),
        )

    @staticmethod
    def _user(connection, user_id: str) -> sqlite3.Row:
        row = connection.execute(
            """
            SELECT u.*, c.login_name, c.platform_role, c.status,
                   c.credential_version, c.password_salt, c.password_hash,
                   c.kdf_iterations, c.kdf_name
            FROM users u JOIN identity_credentials c ON c.user_id=u.user_id
            WHERE u.user_id=?
        """,
            (user_id,),
        ).fetchone()
        if row is None:
            raise _auth_failed()
        return row

    @staticmethod
    def _public(row) -> dict:
        return {key: row[key] for key in _PUBLIC_COLUMNS}

    def _active(self, connection, actor: str):
        row = self._user(connection, actor)
        if row["status"] != "ACTIVE":
            raise _auth_failed()
        return row

    def _target(self, connection, user_id: str):
        # An unavailable management target is not an expired caller session.
        try:
            return self._user(connection, user_id)
        except IdentityError:
            raise _conflict() from None

    def _admin(self, connection, actor: str):
        row = self._active(connection, actor)
        if row["platform_role"] != "ADMIN":
            raise _forbidden()
        return row

    @staticmethod
    def _account(login_name, display_name, password, email):
        login = normalize_login_name(login_name)
        encoded = _password_bytes(password)
        if (
            not isinstance(display_name, str)
            or not 1 <= len(display_name.strip()) <= 120
        ):
            raise IdentityError("invalid_request", 422)
        if email is not None:
            if not isinstance(email, str):
                raise IdentityError("invalid_request", 422)
            email = email.strip()
            if len(email) > 254 or not re.fullmatch(r"[^\s@]+@[^\s@]+\.[^\s@]+", email):
                raise IdentityError("invalid_request", 422)
        return login, display_name.strip(), encoded, email

    @staticmethod
    def _credential(connection, uid, login, salt, digest, role, account_status):
        connection.execute(
            """
            INSERT INTO identity_credentials VALUES (?,?,?,?,?,?,1,?,?)
        """,
            (
                uid,
                login,
                salt,
                digest,
                "pbkdf2-hmac-sha256",
                KDF_ITERATIONS,
                role,
                account_status,
            ),
        )

    def _issue_session(self, connection, row) -> dict:
        token = secrets.token_urlsafe(32)
        now = datetime.now(timezone.utc)
        expires = (now + timedelta(hours=SESSION_HOURS)).isoformat()
        connection.execute(
            "INSERT INTO identity_sessions VALUES (?,?,?,?,?,?,NULL)",
            (
                "ids_" + secrets.token_hex(16),
                hashlib.sha256(token.encode("ascii")).hexdigest(),
                row["user_id"],
                row["credential_version"],
                now.isoformat(),
                expires,
            ),
        )
        return {
            "user": self._public(row),
            "access_token": token,
            "token_type": "Bearer",
            "expires_at": expires,
        }

    def setup(
        self,
        bootstrap_actor: str,
        *,
        login_name: str,
        display_name: str,
        password: str,
        email: str | None = None,
    ) -> dict:
        login, display, encoded, email = self._account(
            login_name, display_name, password, email
        )
        salt = secrets.token_bytes(32)
        digest = _derive(encoded, salt)
        try:
            with self.store._connection(immediate=True) as connection:
                if identity_enabled_in_connection(connection):
                    raise _conflict()
                if (
                    connection.execute(
                        "SELECT 1 FROM users WHERE user_id=?", (bootstrap_actor,)
                    ).fetchone()
                    is None
                ):
                    raise _conflict()
                connection.execute(
                    "UPDATE users SET display_name=?,email=? WHERE user_id=?",
                    (display, email, bootstrap_actor),
                )
                self._credential(
                    connection, bootstrap_actor, login, salt, digest, "ADMIN", "ACTIVE"
                )
                connection.execute(
                    "INSERT INTO identity_state VALUES (1,?,1,?)",
                    (bootstrap_actor, _now()),
                )
                self._event(connection, bootstrap_actor, bootstrap_actor, "SETUP")
                return self._issue_session(
                    connection, self._user(connection, bootstrap_actor)
                )
        except sqlite3.IntegrityError:
            raise _conflict() from None

    def register(
        self,
        *,
        login_name: str,
        display_name: str,
        password: str,
        email: str | None = None,
    ) -> dict:
        login, display, encoded, email = self._account(
            login_name, display_name, password, email
        )
        salt = secrets.token_bytes(32)
        digest = _derive(encoded, salt)
        uid = "usr_" + secrets.token_hex(16)
        try:
            with self.store._connection(immediate=True) as connection:
                if not identity_enabled_in_connection(connection):
                    raise _conflict()
                connection.execute(
                    "INSERT INTO users VALUES (?,?,?,?)", (uid, display, email, _now())
                )
                self._credential(
                    connection, uid, login, salt, digest, "USER", "PENDING"
                )
                self._event(connection, uid, uid, "REGISTER_PENDING")
                return self._public(self._user(connection, uid))
        except sqlite3.IntegrityError:
            raise _conflict() from None

    def throttle(self, scope: str, key: str, limit: int, window_seconds: int) -> None:
        key_hash = hashlib.sha256(key.encode("utf-8")).hexdigest()
        now = time.time()
        retry = 0
        with self.store._connection(immediate=True) as connection:
            connection.execute(
                "DELETE FROM identity_throttle WHERE expires_at<=?", (now,)
            )
            row = connection.execute(
                "SELECT * FROM identity_throttle WHERE scope=? AND key_sha256=?",
                (scope, key_hash),
            ).fetchone()
            if row is not None and row["hits"] >= limit:
                retry = max(1, math.ceil(row["expires_at"] - now))
            elif row is None:
                connection.execute(
                    "INSERT INTO identity_throttle VALUES (?,?,?,1)",
                    (scope, key_hash, now + window_seconds),
                )
            else:
                connection.execute(
                    "UPDATE identity_throttle SET hits=hits+1 WHERE scope=? AND key_sha256=?",
                    (scope, key_hash),
                )
        if retry:
            raise IdentityError("identity_rate_limited", 429, retry_after=retry)

    def login(self, *, login_name: str, password: str) -> dict:
        login = normalize_login_name(login_name)
        encoded = _password_bytes(password, minimum=1)
        self.throttle("login-total", "local", 60, 60)
        self.throttle("login-account", login, 10, 60)
        with self.store._connection() as connection:
            row = connection.execute(
                "SELECT * FROM identity_credentials WHERE login_name=?", (login,)
            ).fetchone()
        salt = bytes(row["password_salt"]) if row is not None else _DUMMY_SALT
        digest = _derive(encoded, salt)
        expected = bytes(row["password_hash"]) if row is not None else bytes(32)
        matched = secrets.compare_digest(digest, expected)
        if (
            row is None
            or not matched
            or row["kdf_name"] != "pbkdf2-hmac-sha256"
            or row["kdf_iterations"] != KDF_ITERATIONS
        ):
            raise _auth_failed()
        # Recheck after the slow KDF inside the session-issuing transaction.
        with self.store._connection(immediate=True) as connection:
            current = self._active(connection, row["user_id"])
            if current["credential_version"] != row["credential_version"]:
                raise _auth_failed()
            self._event(connection, current["user_id"], current["user_id"], "LOGIN")
            return self._issue_session(connection, current)

    def authenticate(self, token: str) -> dict:
        if not isinstance(token, str) or not re.fullmatch(
            r"[A-Za-z0-9_-]{43}", token, re.ASCII
        ):
            raise _auth_failed()
        digest = hashlib.sha256(token.encode("ascii")).hexdigest()
        with self.store._connection() as connection:
            session = connection.execute(
                "SELECT * FROM identity_sessions WHERE token_sha256=?", (digest,)
            ).fetchone()
            if (
                session is None
                or session["revoked_at"] is not None
                or session["expires_at"] <= _now()
            ):
                raise _auth_failed()
            user = self._active(connection, session["user_id"])
            if user["credential_version"] != session["credential_version"]:
                raise _auth_failed()
            return {**self._public(user), "session_id": session["session_id"]}

    def get_user(self, actor: str) -> dict:
        with self.store._connection() as connection:
            return self._public(self._active(connection, actor))

    def list_sessions(self, actor: str, current_session_id: str) -> list[dict]:
        with self.store._connection() as connection:
            self._active(connection, actor)
            rows = connection.execute(
                """
                SELECT session_id,created_at,expires_at,revoked_at FROM identity_sessions
                WHERE user_id=? ORDER BY created_at,session_id
            """,
                (actor,),
            ).fetchall()
            return [
                {**dict(row), "is_current": row["session_id"] == current_session_id}
                for row in rows
            ]

    def revoke_session(self, actor: str, session_id: str) -> None:
        with self.store._connection(immediate=True) as connection:
            self._active(connection, actor)
            row = connection.execute(
                "SELECT user_id FROM identity_sessions WHERE session_id=?",
                (session_id,),
            ).fetchone()
            if row is None or row["user_id"] != actor:
                raise _forbidden()
            connection.execute(
                "UPDATE identity_sessions SET revoked_at=COALESCE(revoked_at,?) WHERE session_id=?",
                (_now(), session_id),
            )
            self._event(connection, actor, actor, "REVOKE_SESSION")

    def change_password(
        self, actor: str, current_password: str, new_password: str
    ) -> None:
        current_bytes = _password_bytes(current_password, minimum=1)
        new_bytes = _password_bytes(new_password)
        self.throttle("password-account", actor, 10, 600)
        with self.store._connection() as connection:
            old = self._active(connection, actor)
        if not secrets.compare_digest(
            _derive(current_bytes, bytes(old["password_salt"])),
            bytes(old["password_hash"]),
        ):
            raise _auth_failed()
        salt = secrets.token_bytes(32)
        digest = _derive(new_bytes, salt)
        with self.store._connection(immediate=True) as connection:
            current = self._active(connection, actor)
            if current["credential_version"] != old["credential_version"]:
                raise _auth_failed()
            connection.execute(
                """UPDATE identity_credentials SET password_salt=?,password_hash=?,
                credential_version=credential_version+1 WHERE user_id=?""",
                (salt, digest, actor),
            )
            connection.execute(
                "UPDATE identity_sessions SET revoked_at=COALESCE(revoked_at,?) WHERE user_id=?",
                (_now(), actor),
            )
            self._event(connection, actor, actor, "CHANGE_PASSWORD")

    def list_users(self, actor: str) -> list[dict]:
        with self.store._connection() as connection:
            self._admin(connection, actor)
            rows = connection.execute(
                "SELECT user_id FROM identity_credentials ORDER BY login_name"
            ).fetchall()
            return [
                self._public(self._user(connection, row["user_id"])) for row in rows
            ]

    def approve(self, actor: str, target: str) -> dict:
        with self.store._connection(immediate=True) as connection:
            self._admin(connection, actor)
            row = self._target(connection, target)
            if row["status"] != "PENDING":
                raise _conflict()
            connection.execute(
                "UPDATE identity_credentials SET status='ACTIVE' WHERE user_id=?",
                (target,),
            )
            self._event(connection, actor, target, "APPROVE")
            return self._public(self._user(connection, target))

    @staticmethod
    def _protect_last_admin(connection, row):
        if row["platform_role"] == "ADMIN" and row["status"] == "ACTIVE":
            count = connection.execute(
                "SELECT COUNT(*) FROM identity_credentials WHERE platform_role='ADMIN' AND status='ACTIVE'"
            ).fetchone()[0]
            if count <= 1:
                raise _conflict()

    def set_status(self, actor: str, target: str, account_status: str) -> dict:
        if account_status not in {"ACTIVE", "DISABLED"}:
            raise IdentityError("invalid_request", 422)
        with self.store._connection(immediate=True) as connection:
            self._admin(connection, actor)
            row = self._target(connection, target)
            if row["status"] == "PENDING":
                raise _conflict()
            if account_status == "DISABLED":
                self._protect_last_admin(connection, row)
                connection.execute(
                    "UPDATE identity_credentials SET credential_version=credential_version+1 WHERE user_id=?",
                    (target,),
                )
                connection.execute(
                    "UPDATE identity_sessions SET revoked_at=COALESCE(revoked_at,?) WHERE user_id=?",
                    (_now(), target),
                )
            connection.execute(
                "UPDATE identity_credentials SET status=? WHERE user_id=?",
                (account_status, target),
            )
            self._event(connection, actor, target, "STATUS_" + account_status)
            return self._public(self._user(connection, target))

    def set_role(self, actor: str, target: str, role: str) -> dict:
        if role not in {"ADMIN", "USER"}:
            raise IdentityError("invalid_request", 422)
        with self.store._connection(immediate=True) as connection:
            self._admin(connection, actor)
            row = self._target(connection, target)
            if row["status"] != "ACTIVE":
                raise _conflict()
            if role == "USER":
                self._protect_last_admin(connection, row)
            connection.execute(
                "UPDATE identity_credentials SET platform_role=? WHERE user_id=?",
                (role, target),
            )
            self._event(connection, actor, target, "ROLE_" + role)
            return self._public(self._user(connection, target))

    def _owner(self, connection, actor, workspace_id):
        self._active(connection, actor)
        row = connection.execute(
            """
            SELECT w.owner_user_id,m.role FROM workspaces w
            JOIN workspace_members m ON m.workspace_id=w.workspace_id AND m.user_id=?
            WHERE w.workspace_id=?
        """,
            (actor, workspace_id),
        ).fetchone()
        if row is None or row["owner_user_id"] != actor or row["role"] != "owner":
            raise _forbidden()

    @staticmethod
    def _members(connection, workspace_id):
        rows = connection.execute(
            """
            SELECT m.user_id,u.display_name,m.role FROM workspace_members m
            JOIN users u ON u.user_id=m.user_id WHERE m.workspace_id=?
            ORDER BY m.role DESC,m.user_id
        """,
            (workspace_id,),
        ).fetchall()
        return [dict(row) for row in rows]

    def list_members(self, actor: str, workspace_id: str) -> list[dict]:
        with self.store._connection() as connection:
            self._owner(connection, actor, workspace_id)
            return self._members(connection, workspace_id)

    def add_member(self, actor: str, workspace_id: str, target: str) -> list[dict]:
        with self.store._connection(immediate=True) as connection:
            self._owner(connection, actor, workspace_id)
            if target == actor:
                raise _conflict()
            if self._target(connection, target)["status"] != "ACTIVE":
                raise _conflict()
            connection.execute(
                "INSERT OR IGNORE INTO workspace_members VALUES (?,?,'member',?)",
                (workspace_id, target, _now()),
            )
            self._event(connection, actor, target, "ADD_MEMBER:" + workspace_id)
            return self._members(connection, workspace_id)

    def remove_member(self, actor: str, workspace_id: str, target: str) -> None:
        with self.store._connection(immediate=True) as connection:
            self._owner(connection, actor, workspace_id)
            if target == actor:
                raise _conflict()
            connection.execute(
                "DELETE FROM workspace_members WHERE workspace_id=? AND user_id=?",
                (workspace_id, target),
            )
            self._event(connection, actor, target, "REMOVE_MEMBER:" + workspace_id)
