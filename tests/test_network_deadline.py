from __future__ import annotations

from contextlib import contextmanager
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
import os
import shutil
import socket
import ssl
import subprocess
import threading
import time
from typing import Any, Iterator

import pytest

from visiondata_gate.network_resilience import (
    HTTPClientPolicy,
    HTTPTransportError,
    ResilientJSONClient,
)


class _DripHandler(BaseHTTPRequestHandler):
    server: Any

    def log_message(self, *_args: object) -> None:
        pass

    def do_GET(self) -> None:
        self.server.requests.append((self.command, self.path))
        self.server.host_headers.append(self.headers.get("Host"))
        raw = b'{"ok":true,"padding":"' + b"x" * 60 + b'"}'
        try:
            if self.path == "/headers":
                self.connection.sendall(b"HTTP/1.1 200 OK\r\nX-Drip: ")
                for _ in range(60):
                    if self.server.stop.wait(0.01):
                        return
                    self.connection.sendall(b"x")
                self.connection.sendall(
                    b"\r\nContent-Type: application/json\r\nContent-Length: "
                    + str(len(raw)).encode("ascii")
                    + b"\r\n\r\n"
                    + raw
                )
                return
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            if self.path == "/chunked":
                self.send_header("Transfer-Encoding", "chunked")
            else:
                self.send_header("Content-Length", str(len(raw)))
            self.end_headers()
            for value in raw:
                chunk = bytes([value])
                if self.path == "/chunked":
                    chunk = b"1\r\n" + chunk + b"\r\n"
                self.wfile.write(chunk)
                self.wfile.flush()
                if self.path != "/ok" and self.server.stop.wait(0.01):
                    return
            if self.path == "/chunked":
                self.wfile.write(b"0\r\n\r\n")
        except OSError:
            pass

    def do_POST(self) -> None:
        length = int(self.headers.get("Content-Length", "0"))
        self.rfile.read(length)
        self.do_GET()


@contextmanager
def _server(
    tls_context: ssl.SSLContext | None = None,
) -> Iterator[tuple[Any, str]]:
    server = ThreadingHTTPServer(("127.0.0.1", 0), _DripHandler)
    server.requests = []
    server.host_headers = []
    server.stop = threading.Event()
    if tls_context is not None:
        server.socket = tls_context.wrap_socket(server.socket, server_side=True)
    thread = threading.Thread(
        target=server.serve_forever, kwargs={"poll_interval": 0.01}, daemon=True
    )
    thread.start()
    try:
        scheme = "https" if tls_context is not None else "http"
        yield server, f"{scheme}://127.0.0.1:{server.server_port}"
    finally:
        server.stop.set()
        server.shutdown()
        server.server_close()
        thread.join(timeout=1)


def _policy(**updates: Any) -> HTTPClientPolicy:
    return HTTPClientPolicy(
        **{
            "allowed_hosts": ["127.0.0.1"],
            "allow_local": True,
            "timeout_seconds": 0.08,
            "max_retries": 0,
            **updates,
        }
    )


@pytest.mark.parametrize("path", ["/body", "/chunked", "/headers"])
def test_dripping_response_obeys_whole_attempt_deadline(path: str) -> None:
    with _server() as (_instance, root):
        client = ResilientJSONClient(_policy())
        started = time.monotonic()
        with pytest.raises(HTTPTransportError) as failed:
            client.request_json(root + path, method="GET")
        elapsed = time.monotonic() - started
    assert failed.value.receipt.status == "TIMEOUT"
    assert failed.value.receipt.attempt_count == 1
    assert elapsed < 0.35


def test_slow_dns_times_out_without_a_late_post(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    real_lookup = socket.getaddrinfo
    entered = threading.Event()
    release = threading.Event()
    finished = threading.Event()

    def slow_lookup(*args: Any, **kwargs: Any) -> Any:
        entered.set()
        release.wait(0.4)
        try:
            return real_lookup(*args, **kwargs)
        finally:
            finished.set()

    with _server() as (instance, root):
        monkeypatch.setattr(socket, "getaddrinfo", slow_lookup)
        client = ResilientJSONClient(_policy())
        started = time.monotonic()
        try:
            with pytest.raises(HTTPTransportError) as failed:
                client.request_json(root + "/ok", method="POST", payload={"ok": True})
            elapsed = time.monotonic() - started
            assert entered.is_set()
            assert failed.value.receipt.status == "TIMEOUT"
            assert elapsed < 0.35
        finally:
            release.set()
            assert finished.wait(1)
        assert instance.requests == []


def test_expired_dns_jobs_are_bounded_and_never_send(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    real_lookup = socket.getaddrinfo
    release = threading.Event()
    lock = threading.Lock()
    active = 0
    peak = 0
    completed = 0

    def stuck_lookup(*args: Any, **kwargs: Any) -> Any:
        nonlocal active, peak, completed
        with lock:
            active += 1
            peak = max(peak, active)
        try:
            release.wait(3)
            return real_lookup(*args, **kwargs)
        finally:
            with lock:
                active -= 1
                completed += 1

    with _server() as (instance, root):
        monkeypatch.setattr(socket, "getaddrinfo", stuck_lookup)
        try:
            for _ in range(12):
                client = ResilientJSONClient(_policy(timeout_seconds=0.02))
                with pytest.raises(HTTPTransportError) as failed:
                    client.request_json(root + "/ok", method="POST", payload={})
                assert failed.value.receipt.status == "TIMEOUT"
            assert peak <= 4
            assert (
                sum(
                    thread.name.startswith("visiondata-dns-")
                    for thread in threading.enumerate()
                )
                <= 4
            )
        finally:
            release.set()
            stop = time.monotonic() + 1
            while active and time.monotonic() < stop:
                time.sleep(0.01)
        assert active == 0
        assert completed <= 4
        assert instance.requests == []


def test_connect_uses_validated_addresses_without_resolving_again(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    real_lookup = socket.getaddrinfo
    lookups: list[str] = []

    def resolve_once(host: str, port: int, **kwargs: Any) -> Any:
        lookups.append(host)
        if len(lookups) > 1:
            raise socket.gaierror("unexpected second resolution")
        return real_lookup("127.0.0.1", port, **kwargs)

    with _server() as (instance, root):
        endpoint = root.replace("127.0.0.1", "localhost")
        monkeypatch.setattr(socket, "getaddrinfo", resolve_once)
        result = ResilientJSONClient(_policy(allowed_hosts=["localhost"])).request_json(
            endpoint + "/ok", method="GET"
        )
    assert result.payload["ok"] is True
    assert lookups == ["localhost"]
    assert instance.host_headers == [endpoint.removeprefix("http://")]


def test_attempt_retries_remain_bounded_with_a_frozen_circuit_clock() -> None:
    with _server() as (instance, root):
        client = ResilientJSONClient(
            _policy(max_retries=1, backoff_seconds=0, circuit_failure_threshold=1),
            clock=lambda: 100.0,
        )
        started = time.monotonic()
        with pytest.raises(HTTPTransportError) as failed:
            client.request_json(root + "/body", method="GET")
        assert time.monotonic() - started < 0.5
        assert failed.value.receipt.status == "TIMEOUT"
        assert failed.value.receipt.attempt_count == 2
        assert failed.value.receipt.retry_count == 1
        assert failed.value.receipt.circuit_after == "open"
        with pytest.raises(HTTPTransportError) as blocked:
            client.request_json(root + "/ok", method="GET")
        assert blocked.value.receipt.status == "CIRCUIT_OPEN"
        assert len(instance.requests) == 2


def test_environment_proxy_is_not_used(monkeypatch: pytest.MonkeyPatch) -> None:
    with _server() as (proxy, proxy_root), _server() as (_target, target_root):
        for name in ("HTTP_PROXY", "HTTPS_PROXY", "ALL_PROXY"):
            monkeypatch.setenv(name, proxy_root)
            monkeypatch.setenv(name.lower(), proxy_root)
        monkeypatch.setenv("NO_PROXY", "")
        monkeypatch.setenv("no_proxy", "")
        result = ResilientJSONClient(_policy()).request_json(
            target_root + "/ok", method="GET"
        )
        assert result.payload["ok"] is True
        assert proxy.requests == []


def test_response_size_limit_is_still_fail_closed() -> None:
    with _server() as (instance, root):
        with pytest.raises(HTTPTransportError) as failed:
            ResilientJSONClient(_policy(max_response_bytes=10)).request_json(
                root + "/ok", method="GET"
            )
    assert failed.value.receipt.status == "INVALID_RESPONSE"
    assert failed.value.receipt.attempt_count == 1
    assert instance.requests == [("GET", "/ok")]


def test_local_tls_preserves_ca_hostname_and_sni(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # No repository key material: generate an ephemeral, untrusted fixture.
    executable = shutil.which("openssl")
    if executable is None:
        pytest.skip("OpenSSL fixture generator is unavailable")
    cert_path = tmp_path / "localhost-cert.pem"
    key_path = tmp_path / "localhost-key.pem"
    subprocess.run(
        [
            executable,
            "req",
            "-config",
            os.devnull,
            "-x509",
            "-newkey",
            "ec",
            "-pkeyopt",
            "ec_paramgen_curve:prime256v1",
            "-nodes",
            "-keyout",
            str(key_path),
            "-out",
            str(cert_path),
            "-subj",
            "/CN=localhost",
            "-addext",
            "subjectAltName=DNS:localhost",
            "-days",
            "1",
        ],
        check=True,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.PIPE,
        timeout=10,
    )
    server_context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    server_context.load_cert_chain(cert_path, key_path)
    server_names: list[str | None] = []
    server_context.set_servername_callback(
        lambda _socket, name, _context: server_names.append(name)
    )
    trusted_context = ssl.create_default_context()
    assert trusted_context.check_hostname is True
    assert trusted_context.verify_mode == ssl.CERT_REQUIRED
    trusted_context.load_verify_locations(cafile=str(cert_path))

    # This fixture listens on IPv4. Pin its DNS answer to IPv4 so an unrelated
    # platform IPv6 connection timeout does not hide the TLS validation result.
    real_lookup = socket.getaddrinfo
    monkeypatch.setattr(
        socket,
        "getaddrinfo",
        lambda host, port, **kwargs: real_lookup("127.0.0.1", port, **kwargs),
    )

    with _server(server_context) as (instance, root):
        endpoint = root.replace("127.0.0.1", "localhost")
        policy = _policy(allowed_hosts=["localhost"], timeout_seconds=2)
        with pytest.raises(HTTPTransportError) as untrusted:
            ResilientJSONClient(policy).request_json(endpoint + "/ok", method="GET")
        assert untrusted.value.receipt.status == "TRANSPORT_ERROR"
        assert instance.requests == []

        monkeypatch.setattr(
            "visiondata_gate.network_deadline.ssl.create_default_context",
            lambda: trusted_context,
        )
        result = ResilientJSONClient(policy).request_json(
            endpoint + "/ok", method="GET"
        )
        assert result.payload["ok"] is True
        assert "localhost" in server_names
        assert instance.host_headers == [endpoint.removeprefix("https://")]

        with pytest.raises(HTTPTransportError) as wrong_host:
            ResilientJSONClient(_policy(timeout_seconds=2)).request_json(
                root + "/ok", method="GET"
            )
        assert wrong_host.value.receipt.status == "TRANSPORT_ERROR"
        assert instance.requests == [("GET", "/ok")]
