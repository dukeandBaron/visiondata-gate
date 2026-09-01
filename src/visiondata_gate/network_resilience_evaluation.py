"""Fixed-denominator loopback evaluation for the resilient HTTP transport."""

from __future__ import annotations

from contextlib import contextmanager
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import threading
import time
from typing import Any, Iterator

from .evidence import canonical_json_bytes, sha256_bytes
from .network_resilience import (
    HTTPClientPolicy,
    HTTPExchangeReceipt,
    HTTPTransportError,
    ResilientJSONClient,
)


class _EvaluationHandler(BaseHTTPRequestHandler):
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
        if self.path == "/deadline":
            time.sleep(0.12)
            self._json(200, {"ok": True})
            return
        if self.path == "/flaky" and self.server.counts[self.path] == 1:
            self._json(503, {"error": "transient"})
            return
        if self.path == "/recover" and self.server.fail_recover:
            self._json(503, {"error": "unavailable"})
            return
        if self.path == "/redirect":
            self.send_response(302)
            self.send_header("Location", "/redirect-target")
            self.end_headers()
            return
        self._json(200, {"ok": True})


@contextmanager
def _loopback_server() -> Iterator[tuple[ThreadingHTTPServer, str]]:
    server = ThreadingHTTPServer(("127.0.0.1", 0), _EvaluationHandler)
    server.counts = {}
    server.fail_recover = True
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield server, f"http://127.0.0.1:{server.server_port}"
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)


def _policy(**updates: Any) -> HTTPClientPolicy:
    values: dict[str, Any] = {
        "allowed_hosts": ["127.0.0.1"],
        "allow_local": True,
        "timeout_seconds": 0.03,
        "max_retries": 0,
        "backoff_seconds": 0.0,
        "circuit_failure_threshold": 2,
        "circuit_recovery_seconds": 0.05,
    }
    values.update(updates)
    return HTTPClientPolicy(**values)


def _dump(receipt: HTTPExchangeReceipt) -> dict[str, Any]:
    return receipt.model_dump(mode="json")


def build_network_resilience_evaluation_receipt() -> dict[str, Any]:
    """Exercise four real HTTP behaviors against one local socket server."""

    cases: list[dict[str, Any]] = []
    with _loopback_server() as (server, root):
        deadline_client = ResilientJSONClient(_policy(circuit_failure_threshold=5))
        try:
            deadline_client.request_json(f"{root}/deadline", method="GET")
        except HTTPTransportError as error:
            deadline_receipt = error.receipt
        else:
            raise AssertionError("deadline fixture unexpectedly succeeded")
        cases.append(
            {
                "case_id": "real-socket-deadline",
                "expected": "TIMEOUT",
                "observed": deadline_receipt.status,
                "passed": deadline_receipt.status == "TIMEOUT",
                "transport_receipts": [_dump(deadline_receipt)],
            }
        )

        retry_client = ResilientJSONClient(_policy(max_retries=1))
        retried = retry_client.request_json(f"{root}/flaky", method="GET")
        cases.append(
            {
                "case_id": "transient-503-bounded-retry",
                "expected": "RECOVERED_WITH_ONE_RETRY",
                "observed": f"{retried.receipt.status}_WITH_{retried.receipt.retry_count}_RETRY",
                "passed": (
                    retried.receipt.status == "RECOVERED"
                    and retried.receipt.retry_count == 1
                    and server.counts.get("/flaky") == 2
                ),
                "transport_receipts": [_dump(retried.receipt)],
            }
        )

        breaker_client = ResilientJSONClient(
            _policy(circuit_failure_threshold=1, circuit_recovery_seconds=0.05)
        )
        try:
            breaker_client.request_json(f"{root}/recover", method="GET")
        except HTTPTransportError as error:
            opening = error.receipt
        else:
            raise AssertionError("circuit opening fixture unexpectedly succeeded")
        try:
            breaker_client.request_json(f"{root}/recover", method="GET")
        except HTTPTransportError as error:
            rejected = error.receipt
        else:
            raise AssertionError("open circuit unexpectedly called the server")
        server.fail_recover = False
        time.sleep(0.12)
        try:
            recovered = breaker_client.request_json(f"{root}/recover", method="GET")
        except HTTPTransportError as error:
            recovery_receipt = error.receipt
            recovery_succeeded = False
        else:
            recovery_receipt = recovered.receipt
            recovery_succeeded = True
        cases.append(
            {
                "case_id": "circuit-open-half-open-auto-recovery",
                "expected": "OPEN_FAST_REJECT_HALF_OPEN_CLOSED",
                "observed": (
                    f"{opening.circuit_after}_{rejected.status}_"
                    f"{recovery_receipt.circuit_after}"
                ),
                "passed": (
                    opening.circuit_after == "open"
                    and rejected.status == "CIRCUIT_OPEN"
                    and rejected.attempt_count == 0
                    and recovery_succeeded
                    and recovery_receipt.circuit_before == "open"
                    and recovery_receipt.circuit_after == "closed"
                    and server.counts.get("/recover") == 2
                ),
                "transport_receipts": [
                    _dump(opening),
                    _dump(rejected),
                    _dump(recovery_receipt),
                ],
            }
        )

        redirect_client = ResilientJSONClient(_policy())
        try:
            redirect_client.request_json(f"{root}/redirect", method="GET")
        except HTTPTransportError as error:
            redirect = error.receipt
        else:
            raise AssertionError("redirect fixture unexpectedly followed redirect")
        cases.append(
            {
                "case_id": "redirect-denied",
                "expected": "REDIRECT_BLOCKED_NO_FOLLOW",
                "observed": redirect.status,
                "passed": (
                    redirect.status == "REDIRECT_BLOCKED"
                    and server.counts.get("/redirect-target", 0) == 0
                ),
                "transport_receipts": [_dump(redirect)],
            }
        )

    passed_count = sum(bool(item["passed"]) for item in cases)
    fixed_denominator = len(cases)
    receipt = {
        "schema_version": "visiondata-gate.network-resilience-evaluation.v1",
        "status": "PASS_LOCAL" if passed_count == fixed_denominator else "FAIL_LOCAL",
        "scope": "real_loopback_http_no_external_backend",
        "fixed_denominator": fixed_denominator,
        "passed_count": passed_count,
        "detection_and_recovery_rate": passed_count / fixed_denominator,
        "real_socket_timeout_verified": bool(cases[0]["passed"]),
        "bounded_retry_recovery_verified": bool(cases[1]["passed"]),
        "circuit_auto_recovery_verified": bool(cases[2]["passed"]),
        "redirect_block_verified": bool(cases[3]["passed"]),
        "cases": cases,
        "source_evidence_unchanged": True,
        "boundary_notice": (
            "This proves the local transport implementation against a real loopback HTTP "
            "server. It does not prove behavior of an unavailable LongCat/VGGT/OmniVGGT service."
        ),
    }
    receipt["case_set_sha256"] = sha256_bytes(
        canonical_json_bytes(
            [
                {"case_id": item["case_id"], "expected": item["expected"]}
                for item in cases
            ]
        )
    )
    return receipt


__all__ = ["build_network_resilience_evaluation_receipt"]
