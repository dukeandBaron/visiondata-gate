"""Bounded, auditable JSON-over-HTTP transport for optional backends.

The client deliberately exposes a small contract instead of wrapping every
``urllib`` feature.  Destinations are allowlisted, redirects and URL
credentials are rejected, remote clear-text HTTP is forbidden, response size
is capped, and retries/circuit state are recorded without retaining secrets or
payload contents.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
import ipaddress
import json
import socket
import threading
import time
from typing import Any, Callable, Literal
import urllib.error
import urllib.parse
import urllib.request

from pydantic import BaseModel, ConfigDict, Field, field_validator

from .evidence import canonical_json_bytes, sha256_bytes


_RETRYABLE_STATUS = {408, 425, 429, 500, 502, 503, 504}


class NetworkModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class HTTPClientPolicy(NetworkModel):
    """Explicit outbound policy shared by model and geometry connectors."""

    allowed_hosts: list[str] = Field(min_length=1)
    allow_local: bool = False
    timeout_seconds: float = Field(default=10.0, ge=0.01, le=120.0)
    max_retries: int = Field(default=1, ge=0, le=3)
    backoff_seconds: float = Field(default=0.05, ge=0.0, le=10.0)
    circuit_failure_threshold: int = Field(default=2, ge=1, le=10)
    circuit_recovery_seconds: float = Field(default=5.0, ge=0.01, le=300.0)
    max_response_bytes: int = Field(default=2_000_000, ge=1, le=20_000_000)

    @field_validator("allowed_hosts")
    @classmethod
    def normalize_hosts(cls, values: list[str]) -> list[str]:
        normalized = [value.strip().casefold().rstrip(".") for value in values]
        if any(not value for value in normalized):
            raise ValueError("allowed_hosts cannot contain blank values")
        if len(normalized) != len(set(normalized)):
            raise ValueError("allowed_hosts must be unique")
        return normalized


class HTTPAttemptReceipt(NetworkModel):
    attempt: int = Field(ge=1)
    status: Literal[
        "success",
        "http_error",
        "timeout",
        "transport_error",
        "redirect_blocked",
        "invalid_response",
    ]
    duration_ms: float = Field(ge=0.0)
    retryable: bool
    http_status: int | None = None
    error_type: str | None = None
    backoff_ms: float = Field(default=0.0, ge=0.0)


class HTTPExchangeReceipt(NetworkModel):
    schema_version: Literal["visiondata-gate.http-exchange.v1"] = (
        "visiondata-gate.http-exchange.v1"
    )
    request_id: str = Field(min_length=16, max_length=64)
    endpoint_id: str = Field(min_length=1)
    endpoint_scope: Literal["local", "remote"]
    method: Literal["GET", "POST", "PUT"]
    status: Literal[
        "SUCCESS",
        "RECOVERED",
        "TIMEOUT",
        "HTTP_ERROR",
        "TRANSPORT_ERROR",
        "REDIRECT_BLOCKED",
        "INVALID_RESPONSE",
        "CIRCUIT_OPEN",
    ]
    request_sha256: str = Field(min_length=64, max_length=64)
    response_sha256: str | None = Field(default=None, min_length=64, max_length=64)
    attempts: list[HTTPAttemptReceipt] = Field(default_factory=list)
    attempt_count: int = Field(ge=0)
    retry_count: int = Field(ge=0)
    circuit_before: Literal["closed", "open", "half_open"]
    circuit_after: Literal["closed", "open", "half_open"]
    secrets_retained: Literal[False] = False
    redirects_followed: Literal[False] = False


@dataclass(frozen=True)
class HTTPJSONResult:
    payload: dict[str, Any]
    receipt: HTTPExchangeReceipt
    raw_bytes: bytes


class HTTPTransportError(RuntimeError):
    """Transport failure with a safe, payload-free receipt."""

    def __init__(self, message: str, receipt: HTTPExchangeReceipt) -> None:
        super().__init__(message)
        self.receipt = receipt


class _NoRedirectHandler(urllib.request.HTTPRedirectHandler):
    def redirect_request(
        self,
        req: urllib.request.Request,
        fp: Any,
        code: int,
        msg: str,
        headers: Any,
        newurl: str,
    ) -> None:
        del req, fp, code, msg, headers, newurl
        return None


class CircuitBreaker:
    """Thread-safe closed/open/half-open state machine."""

    def __init__(
        self,
        *,
        failure_threshold: int,
        recovery_seconds: float,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self.failure_threshold = failure_threshold
        self.recovery_seconds = recovery_seconds
        self._clock = clock
        self._state: Literal["closed", "open", "half_open"] = "closed"
        self._failures = 0
        self._opened_at: float | None = None
        self._lock = threading.Lock()

    @property
    def state(self) -> Literal["closed", "open", "half_open"]:
        with self._lock:
            return self._state

    def allow(self) -> tuple[bool, Literal["closed", "open", "half_open"]]:
        with self._lock:
            if self._state == "open":
                assert self._opened_at is not None
                if self._clock() - self._opened_at >= self.recovery_seconds:
                    self._state = "half_open"
                else:
                    return False, "open"
            return True, self._state

    def success(self) -> None:
        with self._lock:
            self._state = "closed"
            self._failures = 0
            self._opened_at = None

    def failure(self) -> None:
        with self._lock:
            if self._state == "half_open":
                self._state = "open"
                self._opened_at = self._clock()
                return
            self._failures += 1
            if self._failures >= self.failure_threshold:
                self._state = "open"
                self._opened_at = self._clock()


def _is_forbidden_remote_ip(address: str) -> bool:
    value = ipaddress.ip_address(address)
    return bool(
        value.is_private
        or value.is_loopback
        or value.is_link_local
        or value.is_multicast
        or value.is_reserved
        or value.is_unspecified
    )


def _endpoint_metadata(
    endpoint: str, policy: HTTPClientPolicy
) -> tuple[str, Literal["local", "remote"], str]:
    parsed = urllib.parse.urlsplit(endpoint)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        raise ValueError("endpoint must be an absolute http(s) URL")
    if parsed.username or parsed.password:
        raise ValueError("endpoint URL credentials are forbidden")
    if parsed.query or parsed.fragment:
        raise ValueError("endpoint query strings and fragments are forbidden")
    host = (parsed.hostname or "").casefold().rstrip(".")
    if host not in set(policy.allowed_hosts):
        raise PermissionError("endpoint host is not allowlisted")

    try:
        addresses = {
            item[4][0]
            for item in socket.getaddrinfo(
                host,
                parsed.port or (443 if parsed.scheme == "https" else 80),
                type=socket.SOCK_STREAM,
            )
        }
    except socket.gaierror as error:
        raise ConnectionError("endpoint DNS resolution failed") from error
    local = bool(addresses) and all(
        ipaddress.ip_address(item).is_loopback for item in addresses
    )
    if local:
        if not policy.allow_local:
            raise PermissionError("loopback endpoints are disabled by policy")
        scope: Literal["local", "remote"] = "local"
    else:
        if parsed.scheme != "https":
            raise PermissionError("remote endpoints require HTTPS")
        if any(_is_forbidden_remote_ip(item) for item in addresses):
            raise PermissionError(
                "remote endpoint resolved to a forbidden address range"
            )
        scope = "remote"
    port = f":{parsed.port}" if parsed.port is not None else ""
    endpoint_id = f"{parsed.scheme}://{host}{port}{parsed.path or '/'}"
    origin = f"{parsed.scheme}://{host}{port}"
    return endpoint_id, scope, origin


def _request_digest(method: str, endpoint_id: str, body: bytes | None) -> str:
    return sha256_bytes(
        canonical_json_bytes(
            {
                "method": method,
                "endpoint_id": endpoint_id,
                "body_sha256": sha256_bytes(body or b""),
            }
        )
    )


class ResilientJSONClient:
    """JSON client with bounded retry and per-origin circuit breakers."""

    def __init__(
        self,
        policy: HTTPClientPolicy,
        *,
        sleeper: Callable[[float], None] = time.sleep,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self.policy = policy
        self._sleep = sleeper
        self._clock = clock
        self._opener = urllib.request.build_opener(
            urllib.request.ProxyHandler({}), _NoRedirectHandler()
        )
        self._breakers: dict[str, CircuitBreaker] = {}
        self._breakers_lock = threading.Lock()

    def _breaker(self, origin: str) -> CircuitBreaker:
        with self._breakers_lock:
            if origin not in self._breakers:
                self._breakers[origin] = CircuitBreaker(
                    failure_threshold=self.policy.circuit_failure_threshold,
                    recovery_seconds=self.policy.circuit_recovery_seconds,
                    clock=self._clock,
                )
            return self._breakers[origin]

    def request_json(
        self,
        endpoint: str,
        *,
        method: Literal["GET", "POST", "PUT"],
        payload: Mapping[str, Any] | None = None,
        headers: Mapping[str, str] | None = None,
    ) -> HTTPJSONResult:
        endpoint_id, scope, origin = _endpoint_metadata(endpoint, self.policy)
        body = canonical_json_bytes(dict(payload)) if payload is not None else None
        request_sha256 = _request_digest(method, endpoint_id, body)
        request_id = request_sha256[:32]
        breaker = self._breaker(origin)
        circuit_before = breaker.state
        allowed, _state = breaker.allow()
        if not allowed:
            receipt = HTTPExchangeReceipt(
                request_id=request_id,
                endpoint_id=endpoint_id,
                endpoint_scope=scope,
                method=method,
                status="CIRCUIT_OPEN",
                request_sha256=request_sha256,
                attempts=[],
                attempt_count=0,
                retry_count=0,
                circuit_before=circuit_before,
                circuit_after=breaker.state,
            )
            raise HTTPTransportError("circuit breaker is open", receipt)

        safe_headers = {
            "Accept": "application/json",
            "Content-Type": "application/json",
            "Idempotency-Key": request_id,
            **dict(headers or {}),
        }
        attempts: list[HTTPAttemptReceipt] = []
        response_sha256: str | None = None
        final_status: Literal[
            "SUCCESS",
            "RECOVERED",
            "TIMEOUT",
            "HTTP_ERROR",
            "TRANSPORT_ERROR",
            "REDIRECT_BLOCKED",
            "INVALID_RESPONSE",
        ] = "TRANSPORT_ERROR"
        last_error = "request failed"
        for index in range(self.policy.max_retries + 1):
            started = self._clock()
            request = urllib.request.Request(
                endpoint,
                data=body,
                headers=safe_headers,
                method=method,
            )
            retryable = False
            http_status: int | None = None
            error_type: str | None = None
            attempt_status: Literal[
                "success",
                "http_error",
                "timeout",
                "transport_error",
                "redirect_blocked",
                "invalid_response",
            ]
            try:
                with self._opener.open(
                    request, timeout=self.policy.timeout_seconds
                ) as response:
                    http_status = int(response.status)
                    raw = response.read(self.policy.max_response_bytes + 1)
                    if len(raw) > self.policy.max_response_bytes:
                        raise ValueError("response exceeds size limit")
                    content_type = response.headers.get_content_type()
                    if content_type != "application/json":
                        raise ValueError(
                            "response content type is not application/json"
                        )
                    parsed = json.loads(raw.decode("utf-8"))
                    if not isinstance(parsed, dict):
                        raise ValueError("JSON response must be one object")
                response_sha256 = sha256_bytes(raw)
                attempt_status = "success"
                duration_ms = (self._clock() - started) * 1000
                attempts.append(
                    HTTPAttemptReceipt(
                        attempt=index + 1,
                        status=attempt_status,
                        duration_ms=max(duration_ms, 0.0),
                        retryable=False,
                        http_status=http_status,
                    )
                )
                breaker.success()
                final_status = "SUCCESS" if index == 0 else "RECOVERED"
                receipt = HTTPExchangeReceipt(
                    request_id=request_id,
                    endpoint_id=endpoint_id,
                    endpoint_scope=scope,
                    method=method,
                    status=final_status,
                    request_sha256=request_sha256,
                    response_sha256=response_sha256,
                    attempts=attempts,
                    attempt_count=len(attempts),
                    retry_count=index,
                    circuit_before=circuit_before,
                    circuit_after=breaker.state,
                )
                return HTTPJSONResult(
                    payload=parsed,
                    receipt=receipt,
                    raw_bytes=raw,
                )
            except urllib.error.HTTPError as error:
                http_status = int(error.code)
                redirect = 300 <= http_status < 400
                retryable = http_status in _RETRYABLE_STATUS
                attempt_status = "redirect_blocked" if redirect else "http_error"
                final_status = "REDIRECT_BLOCKED" if redirect else "HTTP_ERROR"
                error_type = "HTTPError"
                last_error = "redirect blocked" if redirect else "HTTP status failure"
            except (TimeoutError, socket.timeout) as error:
                retryable = True
                attempt_status = "timeout"
                final_status = "TIMEOUT"
                error_type = type(error).__name__
                last_error = "request deadline exceeded"
            except urllib.error.URLError as error:
                is_timeout = isinstance(error.reason, (TimeoutError, socket.timeout))
                retryable = True
                attempt_status = "timeout" if is_timeout else "transport_error"
                final_status = "TIMEOUT" if is_timeout else "TRANSPORT_ERROR"
                error_type = type(error.reason).__name__
                last_error = (
                    "request deadline exceeded" if is_timeout else "transport failure"
                )
            except (UnicodeDecodeError, json.JSONDecodeError, ValueError) as error:
                retryable = False
                attempt_status = "invalid_response"
                final_status = "INVALID_RESPONSE"
                error_type = type(error).__name__
                last_error = "invalid JSON response"

            should_retry = retryable and index < self.policy.max_retries
            backoff = self.policy.backoff_seconds * (2**index) if should_retry else 0.0
            duration_ms = (self._clock() - started) * 1000
            attempts.append(
                HTTPAttemptReceipt(
                    attempt=index + 1,
                    status=attempt_status,
                    duration_ms=max(duration_ms, 0.0),
                    retryable=retryable,
                    http_status=http_status,
                    error_type=error_type,
                    backoff_ms=backoff * 1000,
                )
            )
            if not should_retry:
                break
            self._sleep(backoff)

        breaker.failure()
        receipt = HTTPExchangeReceipt(
            request_id=request_id,
            endpoint_id=endpoint_id,
            endpoint_scope=scope,
            method=method,
            status=final_status,
            request_sha256=request_sha256,
            response_sha256=response_sha256,
            attempts=attempts,
            attempt_count=len(attempts),
            retry_count=max(len(attempts) - 1, 0),
            circuit_before=circuit_before,
            circuit_after=breaker.state,
        )
        raise HTTPTransportError(last_error, receipt)


__all__ = [
    "CircuitBreaker",
    "HTTPAttemptReceipt",
    "HTTPClientPolicy",
    "HTTPExchangeReceipt",
    "HTTPJSONResult",
    "HTTPTransportError",
    "ResilientJSONClient",
]
