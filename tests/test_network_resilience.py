from __future__ import annotations

from contextlib import contextmanager
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import threading
import time
from typing import Any, Iterator

import pytest

from visiondata_gate.network_resilience import (
    HTTPClientPolicy,
    HTTPTransportError,
    ResilientJSONClient,
)


class _Handler(BaseHTTPRequestHandler):
    server: Any

    def log_message(self, *_args: object) -> None:
        return None

    def _json(self, status: int, payload: dict[str, Any]) -> None:
        raw = json.dumps(payload).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(raw)))
        self.end_headers()
        try:
            self.wfile.write(raw)
        except (BrokenPipeError, ConnectionAbortedError, ConnectionResetError):
            pass

    def do_GET(self) -> None:
        self.server.counts[self.path] = self.server.counts.get(self.path, 0) + 1
        if self.path == "/slow" and self.server.slow:
            time.sleep(0.12)
            self._json(200, {"ok": True})
            return
        if self.path == "/flaky" and self.server.counts[self.path] == 1:
            self._json(503, {"error": "transient"})
            return
        if self.path == "/redirect":
            self.send_response(302)
            self.send_header("Location", "/ok")
            self.end_headers()
            return
        self._json(200, {"ok": True, "path": self.path})

    def do_PUT(self) -> None:
        self.server.counts[self.path] = self.server.counts.get(self.path, 0) + 1
        length = int(self.headers.get("Content-Length", "0"))
        payload = json.loads(self.rfile.read(length).decode("utf-8"))
        self._json(200, {"ok": True, "payload": payload})


@contextmanager
def _server() -> Iterator[tuple[ThreadingHTTPServer, str]]:
    server = ThreadingHTTPServer(("127.0.0.1", 0), _Handler)
    server.counts = {}
    server.slow = False
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield server, f"http://127.0.0.1:{server.server_port}"
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)


def _policy(**updates: Any) -> HTTPClientPolicy:
    values = {
        "allowed_hosts": ["127.0.0.1"],
        "allow_local": True,
        "timeout_seconds": 0.03,
        "max_retries": 1,
        "backoff_seconds": 0.0,
        "circuit_failure_threshold": 1,
        "circuit_recovery_seconds": 0.05,
    }
    values.update(updates)
    return HTTPClientPolicy(**values)


def test_real_http_503_recovers_with_one_bounded_retry() -> None:
    with _server() as (server, root):
        client = ResilientJSONClient(_policy())
        result = client.request_json(f"{root}/flaky", method="GET")

    assert result.payload["ok"] is True
    assert result.receipt.status == "RECOVERED"
    assert result.receipt.attempt_count == 2
    assert result.receipt.retry_count == 1
    assert server.counts["/flaky"] == 2


def test_put_is_supported_and_preserves_exact_wire_response() -> None:
    with _server() as (server, root):
        client = ResilientJSONClient(_policy(max_retries=0))
        result = client.request_json(
            f"{root}/matrix-send",
            method="PUT",
            payload={"body": "bounded assignment"},
        )

    assert result.payload == {
        "ok": True,
        "payload": {"body": "bounded assignment"},
    }
    assert json.loads(result.raw_bytes) == result.payload
    assert result.receipt.method == "PUT"
    assert server.counts["/matrix-send"] == 1


def test_real_socket_timeout_opens_circuit_then_half_open_recovers() -> None:
    clock = [100.0]
    with _server() as (server, root):
        server.slow = True
        client = ResilientJSONClient(_policy(max_retries=0), clock=lambda: clock[0])
        with pytest.raises(HTTPTransportError) as timed_out:
            client.request_json(f"{root}/slow", method="GET")
        assert timed_out.value.receipt.status == "TIMEOUT"
        assert timed_out.value.receipt.circuit_after == "open"

        server.slow = False
        with pytest.raises(HTTPTransportError) as short_circuit:
            client.request_json(f"{root}/slow", method="GET")
        assert short_circuit.value.receipt.status == "CIRCUIT_OPEN"
        assert short_circuit.value.receipt.attempt_count == 0

        clock[0] += 0.06
        recovered = client.request_json(f"{root}/slow", method="GET")

    assert recovered.receipt.status == "SUCCESS"
    assert recovered.receipt.circuit_before == "open"
    assert recovered.receipt.circuit_after == "closed"
    assert server.counts["/slow"] == 2


def test_redirect_is_blocked_and_target_is_not_followed() -> None:
    with _server() as (server, root):
        client = ResilientJSONClient(_policy(max_retries=0))
        with pytest.raises(HTTPTransportError) as blocked:
            client.request_json(f"{root}/redirect", method="GET")

    assert blocked.value.receipt.status == "REDIRECT_BLOCKED"
    assert blocked.value.receipt.redirects_followed is False
    assert server.counts.get("/ok", 0) == 0


def test_endpoint_host_must_be_allowlisted_before_request() -> None:
    client = ResilientJSONClient(
        HTTPClientPolicy(allowed_hosts=["127.0.0.1"], allow_local=True)
    )
    with pytest.raises(PermissionError, match="allowlisted"):
        client.request_json("http://localhost:12345/test", method="GET")
