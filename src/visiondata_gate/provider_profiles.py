"""Workspace-scoped BYOK provider profiles with an OS-protected secret boundary.

Provider metadata is safe to persist and return through the API. API keys are
kept in a separate secret store and never enter SQLite, profile responses,
runtime receipts, or evidence bundles. The production desktop target uses
Windows DPAPI so ciphertext is bound to the current Windows user.
"""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
import ctypes
from ctypes import wintypes
from datetime import datetime, timezone
from enum import Enum
import hashlib
import os
from pathlib import Path
import re
import secrets
import sqlite3
import stat
from typing import Literal, Protocol
import urllib.parse

from pydantic import Field, SecretStr, field_validator, model_validator

from .evidence import canonical_json_bytes
from .network_resilience import (
    HTTPClientPolicy,
    HTTPTransportError,
    ResilientJSONClient,
)
from .product_models import ProductModel
from .provider_config import resolve_chat_completions_endpoint


_PROFILE_ID_PATTERN = re.compile(r"^prv_[0-9a-f]{20}$")
_MODEL_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:/-]{0,159}$")
_DPAPI_MAGIC = b"VDG-PROVIDER-SECRET-V1\x00"
_DPAPI_ENTROPY = b"VisionData Gate provider secret v1"
_CRYPTPROTECT_UI_FORBIDDEN = 0x1


def _now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def new_provider_profile_id() -> str:
    return f"prv_{secrets.token_hex(10)}"


def _config_sha256(payload: dict[str, object]) -> str:
    return hashlib.sha256(canonical_json_bytes(payload)).hexdigest()


class ProviderKind(str, Enum):
    DEEPSEEK = "deepseek"
    OPENAI = "openai"
    OPENTOKEN = "opentoken"
    OPENAI_COMPATIBLE = "openai_compatible"
    OLLAMA_LOCAL = "ollama_local"


class ProviderProfileStatus(str, Enum):
    ACTIVE = "ACTIVE"
    REVOKED = "REVOKED"


class ProviderProfileCreateRequest(ProductModel):
    workspace_id: str = Field(min_length=1, max_length=160)
    display_name: str = Field(min_length=2, max_length=100)
    provider_kind: ProviderKind
    base_url: str | None = Field(default=None, max_length=500)
    model: str = Field(min_length=1, max_length=160)
    api_key: SecretStr | None = None
    default_planner_mode: Literal["shadow", "gated"] = "shadow"
    timeout_seconds: float = Field(default=20.0, ge=1.0, le=120.0)
    max_retries: int = Field(default=1, ge=0, le=3)
    max_output_tokens: int = Field(default=900, ge=200, le=2_000)
    context_budget_tokens: int = Field(default=8_192, ge=1_024, le=32_768)
    make_default: bool = True

    @field_validator("model")
    @classmethod
    def validate_model(cls, value: str) -> str:
        normalized = value.strip()
        if not _MODEL_PATTERN.fullmatch(normalized):
            raise ValueError("model contains unsupported characters")
        return normalized

    @model_validator(mode="after")
    def validate_secret_requirement(self) -> ProviderProfileCreateRequest:
        key = self.api_key.get_secret_value().strip() if self.api_key else ""
        if self.provider_kind is not ProviderKind.OLLAMA_LOCAL and not key:
            raise ValueError("remote provider requires an API key")
        if self.provider_kind is ProviderKind.OLLAMA_LOCAL and key:
            raise ValueError("local Ollama does not accept an API key")
        if len(key) > 16_384:
            raise ValueError("API key exceeds the accepted length")
        return self


class ProviderProfileRecord(ProductModel):
    schema_version: Literal["visiondata-gate.provider-profile.v1"] = (
        "visiondata-gate.provider-profile.v1"
    )
    profile_id: str = Field(pattern=r"^prv_[0-9a-f]{20}$")
    workspace_id: str
    owner_user_id: str
    display_name: str
    provider_kind: ProviderKind
    base_url: str
    endpoint_host: str
    model: str
    default_planner_mode: Literal["shadow", "gated"]
    timeout_seconds: float
    max_retries: int
    max_output_tokens: int
    context_budget_tokens: int
    is_default: bool
    secret_configured: bool
    status: ProviderProfileStatus
    config_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    last_test_status: Literal["NOT_TESTED", "CONNECTED", "FAILED", "BLOCKED"]
    last_tested_at: str | None = None
    created_at: str
    revoked_at: str | None = None


class ProviderConnectionTestRequest(ProviderProfileCreateRequest):
    make_default: bool = False


class ProviderConnectionTestResult(ProductModel):
    schema_version: Literal["visiondata-gate.provider-connection-test.v1"] = (
        "visiondata-gate.provider-connection-test.v1"
    )
    status: Literal["CONNECTED", "FAILED", "BLOCKED"]
    reason_code: str
    provider_kind: ProviderKind
    endpoint_host: str
    model: str
    latency_ms: float = Field(ge=0.0)
    tested_at: str
    exchange_receipt_sha256: str | None = Field(default=None, pattern=r"^[0-9a-f]{64}$")
    secrets_retained: Literal[False] = False


class ResolvedProviderConfig(ProductModel):
    provider_kind: ProviderKind
    base_url: str
    endpoint: str
    endpoint_host: str
    model: str
    default_planner_mode: Literal["shadow", "gated"]
    timeout_seconds: float
    max_retries: int
    max_output_tokens: int
    context_budget_tokens: int
    allow_local: bool

    def secret_free_payload(self) -> dict[str, object]:
        return self.model_dump(mode="json")

    def config_sha256(self) -> str:
        return _config_sha256(self.secret_free_payload())


_PROVIDER_DEFAULTS: dict[ProviderKind, tuple[str, str]] = {
    ProviderKind.DEEPSEEK: ("https://api.deepseek.com", "api.deepseek.com"),
    ProviderKind.OPENAI: ("https://api.openai.com", "api.openai.com"),
    ProviderKind.OPENTOKEN: ("https://gw.opentoken.io", "gw.opentoken.io"),
    ProviderKind.OLLAMA_LOCAL: ("http://127.0.0.1:11434", "127.0.0.1"),
}


def resolve_provider_config(
    request: ProviderProfileCreateRequest,
) -> ResolvedProviderConfig:
    configured_base = (request.base_url or "").strip()
    preset = _PROVIDER_DEFAULTS.get(request.provider_kind)
    if not configured_base:
        if preset is None:
            raise ValueError("custom OpenAI-compatible provider requires a base URL")
        configured_base = preset[0]
    endpoint = resolve_chat_completions_endpoint(
        explicit_endpoint=None,
        base_url=configured_base,
        default_endpoint=configured_base,
    )
    parsed = urllib.parse.urlsplit(endpoint)
    host = (parsed.hostname or "").casefold().rstrip(".")
    if not host:
        raise ValueError("provider endpoint host is missing")
    if preset is not None and host != preset[1]:
        raise ValueError("selected provider must use its approved endpoint host")
    allow_local = request.provider_kind is ProviderKind.OLLAMA_LOCAL
    if allow_local:
        if parsed.scheme != "http" or host not in {"127.0.0.1", "localhost", "::1"}:
            raise ValueError("local Ollama must use an HTTP loopback endpoint")
    elif parsed.scheme != "https":
        raise ValueError("remote providers require HTTPS")
    return ResolvedProviderConfig(
        provider_kind=request.provider_kind,
        base_url=configured_base.rstrip("/"),
        endpoint=endpoint,
        endpoint_host=host,
        model=request.model,
        default_planner_mode=request.default_planner_mode,
        timeout_seconds=request.timeout_seconds,
        max_retries=request.max_retries,
        max_output_tokens=request.max_output_tokens,
        context_budget_tokens=request.context_budget_tokens,
        allow_local=allow_local,
    )


class ProviderSecretStore(Protocol):
    @property
    def available(self) -> bool: ...

    def put(self, profile_id: str, secret_value: str) -> None: ...

    def get(self, profile_id: str) -> str | None: ...

    def delete(self, profile_id: str) -> None: ...


class SecretStoreUnavailableError(RuntimeError):
    pass


class _DataBlob(ctypes.Structure):
    _fields_ = [("cbData", wintypes.DWORD), ("pbData", ctypes.POINTER(ctypes.c_byte))]


def _input_blob(value: bytes) -> tuple[_DataBlob, ctypes.Array[ctypes.c_char]]:
    buffer = ctypes.create_string_buffer(value)
    blob = _DataBlob(len(value), ctypes.cast(buffer, ctypes.POINTER(ctypes.c_byte)))
    return blob, buffer


def _dpapi_transform(value: bytes, *, protect: bool) -> bytes:
    if os.name != "nt":
        raise SecretStoreUnavailableError("Windows DPAPI is not available")
    crypt32 = ctypes.WinDLL("crypt32", use_last_error=True)
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    in_blob, in_buffer = _input_blob(value)
    entropy_blob, entropy_buffer = _input_blob(_DPAPI_ENTROPY)
    out_blob = _DataBlob()
    if protect:
        function = crypt32.CryptProtectData
        function.argtypes = [
            ctypes.POINTER(_DataBlob),
            wintypes.LPCWSTR,
            ctypes.POINTER(_DataBlob),
            ctypes.c_void_p,
            ctypes.c_void_p,
            wintypes.DWORD,
            ctypes.POINTER(_DataBlob),
        ]
        ok = function(
            ctypes.byref(in_blob),
            "VisionData Gate provider secret",
            ctypes.byref(entropy_blob),
            None,
            None,
            _CRYPTPROTECT_UI_FORBIDDEN,
            ctypes.byref(out_blob),
        )
    else:
        function = crypt32.CryptUnprotectData
        function.argtypes = [
            ctypes.POINTER(_DataBlob),
            ctypes.POINTER(wintypes.LPWSTR),
            ctypes.POINTER(_DataBlob),
            ctypes.c_void_p,
            ctypes.c_void_p,
            wintypes.DWORD,
            ctypes.POINTER(_DataBlob),
        ]
        description = wintypes.LPWSTR()
        ok = function(
            ctypes.byref(in_blob),
            ctypes.byref(description),
            ctypes.byref(entropy_blob),
            None,
            None,
            _CRYPTPROTECT_UI_FORBIDDEN,
            ctypes.byref(out_blob),
        )
        if description:
            kernel32.LocalFree(description)
    if not ok:
        error_code = ctypes.get_last_error()
        raise OSError(error_code, "Windows DPAPI operation failed")
    try:
        # Keep both ctypes buffers referenced until the native call is complete.
        _ = in_buffer, entropy_buffer
        return ctypes.string_at(out_blob.pbData, out_blob.cbData)
    finally:
        kernel32.LocalFree(out_blob.pbData)


class WindowsDPAPIProviderSecretStore:
    def __init__(self, root: str | Path) -> None:
        self.root = Path(root).expanduser().resolve()
        self.root.mkdir(parents=True, exist_ok=True)

    @property
    def available(self) -> bool:
        return os.name == "nt"

    @staticmethod
    def _validate_profile_id(profile_id: str) -> None:
        if not _PROFILE_ID_PATTERN.fullmatch(profile_id):
            raise ValueError("invalid provider profile ID")

    def _path(self, profile_id: str) -> Path:
        self._validate_profile_id(profile_id)
        return self.root / f"{profile_id}.dpapi"

    def put(self, profile_id: str, secret_value: str) -> None:
        if not self.available:
            raise SecretStoreUnavailableError("secure provider storage is unavailable")
        normalized = secret_value.strip()
        if not normalized:
            raise ValueError("provider secret cannot be blank")
        if len(normalized) > 16_384:
            raise ValueError("provider secret exceeds the accepted length")
        ciphertext = _dpapi_transform(
            _DPAPI_MAGIC + normalized.encode("utf-8"), protect=True
        )
        target = self._path(profile_id)
        temporary = target.with_suffix(f".tmp-{secrets.token_hex(6)}")
        try:
            temporary.write_bytes(ciphertext)
            os.chmod(temporary, stat.S_IRUSR | stat.S_IWUSR)
            os.replace(temporary, target)
        finally:
            if temporary.exists():
                temporary.unlink()

    def get(self, profile_id: str) -> str | None:
        target = self._path(profile_id)
        if not target.is_file():
            return None
        plaintext = _dpapi_transform(target.read_bytes(), protect=False)
        if not plaintext.startswith(_DPAPI_MAGIC):
            raise ValueError("provider secret envelope is invalid")
        return plaintext[len(_DPAPI_MAGIC) :].decode("utf-8")

    def delete(self, profile_id: str) -> None:
        target = self._path(profile_id)
        if target.is_file():
            target.unlink()


class InMemoryProviderSecretStore:
    """Explicit test double; never selected by production configuration."""

    def __init__(self) -> None:
        self._values: dict[str, str] = {}

    @property
    def available(self) -> bool:
        return True

    def put(self, profile_id: str, secret_value: str) -> None:
        if not _PROFILE_ID_PATTERN.fullmatch(profile_id):
            raise ValueError("invalid provider profile ID")
        self._values[profile_id] = secret_value

    def get(self, profile_id: str) -> str | None:
        return self._values.get(profile_id)

    def delete(self, profile_id: str) -> None:
        self._values.pop(profile_id, None)


class ProviderProfileRegistry:
    """Secret-free, user-private profile metadata registry."""

    def __init__(self, database_path: str | Path) -> None:
        self.database_path = Path(database_path).expanduser().resolve()
        self.database_path.parent.mkdir(parents=True, exist_ok=True)
        self._initialize()

    @contextmanager
    def _connection(self, *, immediate: bool = False) -> Iterator[sqlite3.Connection]:
        connection = sqlite3.connect(self.database_path, timeout=30.0)
        connection.row_factory = sqlite3.Row
        try:
            if immediate:
                connection.execute("BEGIN IMMEDIATE")
            yield connection
            connection.commit()
        except Exception:
            connection.rollback()
            raise
        finally:
            connection.close()

    def _initialize(self) -> None:
        # journal_mode must be selected before SQLite opens a write transaction.
        # The schema DDL that follows starts and commits its own transaction.
        with self._connection() as connection:
            connection.execute("PRAGMA journal_mode = WAL")
            connection.executescript(
                """
                CREATE TABLE IF NOT EXISTS provider_profiles (
                    profile_id TEXT PRIMARY KEY,
                    workspace_id TEXT NOT NULL,
                    owner_user_id TEXT NOT NULL,
                    display_name TEXT NOT NULL,
                    provider_kind TEXT NOT NULL,
                    base_url TEXT NOT NULL,
                    endpoint TEXT NOT NULL,
                    endpoint_host TEXT NOT NULL,
                    model TEXT NOT NULL,
                    default_planner_mode TEXT NOT NULL,
                    timeout_seconds REAL NOT NULL,
                    max_retries INTEGER NOT NULL,
                    max_output_tokens INTEGER NOT NULL,
                    context_budget_tokens INTEGER NOT NULL,
                    is_default INTEGER NOT NULL,
                    secret_configured INTEGER NOT NULL,
                    status TEXT NOT NULL,
                    config_sha256 TEXT NOT NULL,
                    last_test_status TEXT NOT NULL,
                    last_tested_at TEXT,
                    created_at TEXT NOT NULL,
                    revoked_at TEXT
                );
                CREATE INDEX IF NOT EXISTS idx_provider_profiles_owner_workspace
                    ON provider_profiles(owner_user_id, workspace_id, status);
                CREATE UNIQUE INDEX IF NOT EXISTS idx_provider_profiles_default
                    ON provider_profiles(owner_user_id, workspace_id)
                    WHERE is_default = 1 AND status = 'ACTIVE';
                """
            )

    @staticmethod
    def _record(row: sqlite3.Row) -> ProviderProfileRecord:
        return ProviderProfileRecord(
            profile_id=str(row["profile_id"]),
            workspace_id=str(row["workspace_id"]),
            owner_user_id=str(row["owner_user_id"]),
            display_name=str(row["display_name"]),
            provider_kind=ProviderKind(str(row["provider_kind"])),
            base_url=str(row["base_url"]),
            endpoint_host=str(row["endpoint_host"]),
            model=str(row["model"]),
            default_planner_mode=str(row["default_planner_mode"]),
            timeout_seconds=float(row["timeout_seconds"]),
            max_retries=int(row["max_retries"]),
            max_output_tokens=int(row["max_output_tokens"]),
            context_budget_tokens=int(row["context_budget_tokens"]),
            is_default=bool(row["is_default"]),
            secret_configured=bool(row["secret_configured"]),
            status=ProviderProfileStatus(str(row["status"])),
            config_sha256=str(row["config_sha256"]),
            last_test_status=str(row["last_test_status"]),
            last_tested_at=(
                str(row["last_tested_at"])
                if row["last_tested_at"] is not None
                else None
            ),
            created_at=str(row["created_at"]),
            revoked_at=(str(row["revoked_at"]) if row["revoked_at"] else None),
        )

    def create(
        self,
        *,
        owner_user_id: str,
        request: ProviderProfileCreateRequest,
        resolved: ResolvedProviderConfig,
        secret_configured: bool,
        profile_id: str | None = None,
    ) -> ProviderProfileRecord:
        profile_id = profile_id or new_provider_profile_id()
        if not _PROFILE_ID_PATTERN.fullmatch(profile_id):
            raise ValueError("invalid provider profile ID")
        created_at = _now()
        config_sha256 = resolved.config_sha256()
        with self._connection(immediate=True) as connection:
            if request.make_default:
                connection.execute(
                    """
                    UPDATE provider_profiles SET is_default = 0
                    WHERE owner_user_id = ? AND workspace_id = ?
                    """,
                    (owner_user_id, request.workspace_id),
                )
            connection.execute(
                """
                INSERT INTO provider_profiles VALUES (
                    ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?,
                    'ACTIVE', ?, 'NOT_TESTED', NULL, ?, NULL
                )
                """,
                (
                    profile_id,
                    request.workspace_id,
                    owner_user_id,
                    request.display_name,
                    resolved.provider_kind.value,
                    resolved.base_url,
                    resolved.endpoint,
                    resolved.endpoint_host,
                    resolved.model,
                    resolved.default_planner_mode,
                    resolved.timeout_seconds,
                    resolved.max_retries,
                    resolved.max_output_tokens,
                    resolved.context_budget_tokens,
                    int(request.make_default),
                    int(secret_configured),
                    config_sha256,
                    created_at,
                ),
            )
            row = connection.execute(
                "SELECT * FROM provider_profiles WHERE profile_id = ?",
                (profile_id,),
            ).fetchone()
            assert row is not None
            record = self._record(row)
        return record

    def list_for_owner(
        self, owner_user_id: str, workspace_id: str
    ) -> list[ProviderProfileRecord]:
        with self._connection() as connection:
            rows = connection.execute(
                """
                SELECT * FROM provider_profiles
                WHERE owner_user_id = ? AND workspace_id = ? AND status = 'ACTIVE'
                ORDER BY is_default DESC, created_at DESC, profile_id DESC
                """,
                (owner_user_id, workspace_id),
            ).fetchall()
        return [self._record(row) for row in rows]

    def get_for_owner(
        self, owner_user_id: str, profile_id: str, *, include_revoked: bool = False
    ) -> ProviderProfileRecord | None:
        query = (
            "SELECT * FROM provider_profiles WHERE owner_user_id = ? AND profile_id = ?"
        )
        parameters: list[object] = [owner_user_id, profile_id]
        if not include_revoked:
            query += " AND status = 'ACTIVE'"
        with self._connection() as connection:
            row = connection.execute(query, parameters).fetchone()
        return self._record(row) if row is not None else None

    def get_default(
        self, owner_user_id: str, workspace_id: str
    ) -> ProviderProfileRecord | None:
        with self._connection() as connection:
            row = connection.execute(
                """
                SELECT * FROM provider_profiles
                WHERE owner_user_id = ? AND workspace_id = ?
                    AND status = 'ACTIVE' AND is_default = 1
                """,
                (owner_user_id, workspace_id),
            ).fetchone()
        return self._record(row) if row is not None else None

    def endpoint_for_profile(self, owner_user_id: str, profile_id: str) -> str | None:
        with self._connection() as connection:
            row = connection.execute(
                """
                SELECT endpoint FROM provider_profiles
                WHERE owner_user_id = ? AND profile_id = ? AND status = 'ACTIVE'
                """,
                (owner_user_id, profile_id),
            ).fetchone()
        return str(row["endpoint"]) if row is not None else None

    def set_default(
        self, owner_user_id: str, profile_id: str
    ) -> ProviderProfileRecord | None:
        with self._connection(immediate=True) as connection:
            target = connection.execute(
                """
                SELECT * FROM provider_profiles
                WHERE owner_user_id = ? AND profile_id = ? AND status = 'ACTIVE'
                """,
                (owner_user_id, profile_id),
            ).fetchone()
            if target is None:
                return None
            connection.execute(
                """
                UPDATE provider_profiles SET is_default = 0
                WHERE owner_user_id = ? AND workspace_id = ?
                """,
                (owner_user_id, str(target["workspace_id"])),
            )
            connection.execute(
                "UPDATE provider_profiles SET is_default = 1 WHERE profile_id = ?",
                (profile_id,),
            )
            row = connection.execute(
                "SELECT * FROM provider_profiles WHERE profile_id = ?", (profile_id,)
            ).fetchone()
        assert row is not None
        return self._record(row)

    def record_test(
        self, owner_user_id: str, profile_id: str, status_value: str
    ) -> ProviderProfileRecord | None:
        with self._connection(immediate=True) as connection:
            connection.execute(
                """
                UPDATE provider_profiles SET last_test_status = ?, last_tested_at = ?
                WHERE owner_user_id = ? AND profile_id = ? AND status = 'ACTIVE'
                """,
                (status_value, _now(), owner_user_id, profile_id),
            )
            row = connection.execute(
                """
                SELECT * FROM provider_profiles
                WHERE owner_user_id = ? AND profile_id = ? AND status = 'ACTIVE'
                """,
                (owner_user_id, profile_id),
            ).fetchone()
        return self._record(row) if row is not None else None

    def revoke(
        self, owner_user_id: str, profile_id: str
    ) -> ProviderProfileRecord | None:
        with self._connection(immediate=True) as connection:
            target = connection.execute(
                """
                SELECT * FROM provider_profiles
                WHERE owner_user_id = ? AND profile_id = ? AND status = 'ACTIVE'
                """,
                (owner_user_id, profile_id),
            ).fetchone()
            if target is None:
                return None
            connection.execute(
                """
                UPDATE provider_profiles
                SET status = 'REVOKED', is_default = 0, revoked_at = ?
                WHERE profile_id = ?
                """,
                (_now(), profile_id),
            )
            row = connection.execute(
                "SELECT * FROM provider_profiles WHERE profile_id = ?", (profile_id,)
            ).fetchone()
        assert row is not None
        return self._record(row)


def _chat_probe_payload(config: ResolvedProviderConfig) -> dict[str, object]:
    return {
        "model": config.model,
        "messages": [
            {
                "role": "user",
                "content": "Return only the word OK. This is a connection test.",
            }
        ],
        "temperature": 0,
        "max_tokens": 8,
        "stream": False,
    }


def probe_provider_connection(
    config: ResolvedProviderConfig,
    *,
    api_key: str | None,
) -> ProviderConnectionTestResult:
    headers = {"Authorization": f"Bearer {api_key}"} if api_key else {}
    client = ResilientJSONClient(
        HTTPClientPolicy(
            allowed_hosts=[config.endpoint_host],
            allow_local=config.allow_local,
            timeout_seconds=config.timeout_seconds,
            max_retries=config.max_retries,
            max_response_bytes=1_000_000,
        )
    )
    tested_at = _now()
    try:
        result = client.request_json(
            config.endpoint,
            method="POST",
            headers=headers,
            payload=_chat_probe_payload(config),
        )
    except HTTPTransportError as error:
        receipt = error.receipt
        digest = _config_sha256(receipt.model_dump(mode="json"))
        return ProviderConnectionTestResult(
            status="FAILED",
            reason_code=f"PROVIDER_{receipt.status}",
            provider_kind=config.provider_kind,
            endpoint_host=config.endpoint_host,
            model=config.model,
            latency_ms=sum(item.duration_ms for item in receipt.attempts),
            tested_at=tested_at,
            exchange_receipt_sha256=digest,
        )
    except (ConnectionError, PermissionError, ValueError):
        return ProviderConnectionTestResult(
            status="BLOCKED",
            reason_code="DESTINATION_POLICY_REJECTED",
            provider_kind=config.provider_kind,
            endpoint_host=config.endpoint_host,
            model=config.model,
            latency_ms=0.0,
            tested_at=tested_at,
        )
    choices = result.payload.get("choices")
    connected = isinstance(choices, list) and bool(choices)
    receipt_digest = _config_sha256(result.receipt.model_dump(mode="json"))
    return ProviderConnectionTestResult(
        status="CONNECTED" if connected else "FAILED",
        reason_code="PROVIDER_CHAT_COMPLETION_OK"
        if connected
        else "PROVIDER_RESPONSE_CONTRACT_INVALID",
        provider_kind=config.provider_kind,
        endpoint_host=config.endpoint_host,
        model=config.model,
        latency_ms=sum(item.duration_ms for item in result.receipt.attempts),
        tested_at=tested_at,
        exchange_receipt_sha256=receipt_digest,
    )


def profile_to_resolved_config(
    profile: ProviderProfileRecord,
    *,
    endpoint: str,
) -> ResolvedProviderConfig:
    parsed = urllib.parse.urlsplit(endpoint)
    allow_local = profile.provider_kind is ProviderKind.OLLAMA_LOCAL
    return ResolvedProviderConfig(
        provider_kind=profile.provider_kind,
        base_url=profile.base_url,
        endpoint=endpoint,
        endpoint_host=profile.endpoint_host,
        model=profile.model,
        default_planner_mode=profile.default_planner_mode,
        timeout_seconds=profile.timeout_seconds,
        max_retries=profile.max_retries,
        max_output_tokens=profile.max_output_tokens,
        context_budget_tokens=profile.context_budget_tokens,
        allow_local=allow_local
        and (parsed.hostname or "").casefold()
        in {
            "127.0.0.1",
            "localhost",
            "::1",
        },
    )


__all__ = [
    "InMemoryProviderSecretStore",
    "ProviderConnectionTestRequest",
    "ProviderConnectionTestResult",
    "ProviderKind",
    "ProviderProfileCreateRequest",
    "ProviderProfileRecord",
    "ProviderProfileRegistry",
    "ProviderProfileStatus",
    "ProviderSecretStore",
    "ResolvedProviderConfig",
    "SecretStoreUnavailableError",
    "WindowsDPAPIProviderSecretStore",
    "new_provider_profile_id",
    "probe_provider_connection",
    "profile_to_resolved_config",
    "resolve_provider_config",
]
