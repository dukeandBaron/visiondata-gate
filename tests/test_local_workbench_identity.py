"""Real main API + loopback forwarding seam, with isolated product data.

OS ownership observations are fixtures. HTTP, readiness HMAC, setup, Bearer
enforcement and persisted identity are real; this is not an installed/Vite UI test.
"""

from __future__ import annotations

import argparse
from contextlib import contextmanager
import json
from pathlib import Path
import socket
import threading
import time

import httpx
import pytest
from starlette.applications import Starlette
from starlette.responses import Response
from starlette.routing import Route
import uvicorn

from visiondata_gate import local_workbench as launcher
from visiondata_gate.api import create_app
from visiondata_gate.product_service import ProductService

CAPABILITY = "synthetic-launcher-identity-capability-20260913"
PROOF = "synthetic-launcher-child-only-proof-20260913"
ACCOUNT = {
    "login_name": "local-owner",
    "display_name": "Local owner",
    "password": "synthetic launch password 20260913",
}


@contextmanager
def listener(app):
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        port = sock.getsockname()[1]
        server = uvicorn.Server(
            uvicorn.Config(
                app,
                host="127.0.0.1",
                port=port,
                access_log=False,
                log_level="critical",
                proxy_headers=False,
            )
        )
        thread = threading.Thread(
            target=server.run, kwargs={"sockets": [sock]}, daemon=True
        )
        thread.start()
        try:
            deadline = time.monotonic() + 10
            while (
                not server.started and thread.is_alive() and time.monotonic() < deadline
            ):
                time.sleep(0.01)
            assert server.started, "Isolated test listener did not start"
            yield port
        finally:
            server.should_exit = True
            thread.join(timeout=10)
            assert not thread.is_alive(), "Isolated test listener did not stop"


@pytest.fixture
def endpoints(tmp_path, monkeypatch):
    monkeypatch.setenv("VISIONDATA_SESSION_TOKEN", CAPABILITY)
    monkeypatch.setenv("VISIONDATA_DESKTOP_SESSION_TOKEN", CAPABILITY)
    monkeypatch.setenv("VISIONDATA_DESKTOP_STARTUP_SECRET", PROOF)
    monkeypatch.setenv("VISIONDATA_INSECURE_TEST_ACTOR_HEADER_BYPASS", "false")
    product = ProductService(tmp_path / "product", recover_interrupted=False)
    state = {
        "repo_root": str(Path(__file__).resolve().parents[1]),
        "product_root": str(product.product_root),
    }
    credentials = {"session_token": CAPABILITY, "startup_secret": PROOF}
    requests = []
    try:
        app = create_app(product)
        with listener(app) as api_port:
            base = f"http://127.0.0.1:{api_port}"

            async def forward(request):
                headers = {
                    k: v
                    for k, v in request.headers.items()
                    if k not in {"host", "content-length"}
                }
                async with httpx.AsyncClient(
                    trust_env=False, follow_redirects=False, timeout=15.0
                ) as client:
                    upstream = await client.request(
                        request.method,
                        base + request.url.path,
                        params=request.url.query,
                        headers=headers,
                        content=await request.body(),
                    )
                return Response(
                    upstream.content,
                    status_code=upstream.status_code,
                    media_type=upstream.headers.get("content-type"),
                )

            proxy = Starlette(
                routes=[Route("/{rest:path}", forward, methods=["GET", "POST"])]
            )
            with listener(proxy) as web_port:
                state["services"] = {
                    "api": {
                        "pid": 101,
                        "port": api_port,
                        "created": "fixture",
                        "command_line": "fixture-api",
                    },
                    "web": {
                        "pid": 102,
                        "port": web_port,
                        "created": "fixture",
                        "command_line": "fixture-proxy",
                    },
                }
                monkeypatch.setattr(
                    launcher,
                    "process_snapshot",
                    lambda: {r["pid"]: dict(r) for r in state["services"].values()},
                )
                monkeypatch.setattr(
                    launcher,
                    "listener_pids",
                    lambda: {r["port"]: {r["pid"]} for r in state["services"].values()},
                )
                real_get = launcher.http_get

                def observed(url, *, token=None):
                    requests.append((url, token))
                    return real_get(url, token=token)

                monkeypatch.setattr(launcher, "http_get", observed)
                with httpx.Client(base_url=base, trust_env=False) as client:
                    yield state, credentials, client, requests
    finally:
        product.close(wait=True)


def setup(client):
    response = client.post(
        "/v1/identity/setup",
        headers={"X-VisionData-Session-Token": CAPABILITY},
        json=ACCOUNT,
    )
    assert response.status_code == 201, response.text
    return response.json()


def test_initialized_main_api_launcher_checks_status_without_business_capability(
    endpoints,
):
    state, credentials, client, requests = endpoints
    account = setup(client)
    assert (
        client.get(
            "/v1/workspaces", headers={"X-VisionData-Session-Token": CAPABILITY}
        ).status_code
        == 401
    )
    result = launcher.verify_session(state, credentials)
    assert result["authentication_mode"] == "USER_SESSION"
    assert result["login_required"] is True and result["user_authenticated"] is False
    assert result["next_action"] == "LOGIN"
    assert len(requests) == 4
    assert all("/v1/desktop/readiness?" in url for url, _ in requests[:2])
    assert all(url.endswith("/v1/identity/status") for url, _ in requests[2:])
    assert all(token is None for _, token in requests)
    assert account["access_token"] not in json.dumps(result)
    assert credentials == {"session_token": CAPABILITY, "startup_secret": PROOF}


def test_uninitialized_main_api_keeps_legacy_workspace_probe(endpoints):
    state, credentials, _client, requests = endpoints
    result = launcher.verify_session(state, credentials)
    assert result["authentication_mode"] == "SETUP_REQUIRED"
    assert (
        result["setup_required"] is True
        and result["next_action"] == "INITIALIZE_ACCOUNT"
    )
    assert result["login_required"] is False and result["user_authenticated"] is False
    assert len(requests) == 6
    assert all(token is None for _, token in requests[:4])
    assert all(
        url.endswith("/v1/workspaces") and token == CAPABILITY
        for url, token in requests[4:]
    )


@pytest.mark.parametrize("action", ["status", "open"])
def test_initialized_launcher_entrypoints_report_waiting_for_login(
    endpoints, tmp_path, monkeypatch, capsys, action
):
    state, credentials, client, requests = endpoints
    setup(client)
    monkeypatch.setattr(launcher, "read_session", lambda root: (state, credentials))
    opened = []
    monkeypatch.setattr(launcher, "_open", lambda *args: opened.append(True))
    args = argparse.Namespace(action=action, product_root=None)
    assert launcher._execute(args, Path(state["repo_root"]), tmp_path / "state") == 0
    report = json.loads(capsys.readouterr().out)
    assert report["status"] == "READY"
    assert report["login_required"] is True and report["user_authenticated"] is False
    assert report["next_action"] == "LOGIN"
    assert bool(opened) == (action == "open")
    assert all(token is None for _, token in requests)
    assert CAPABILITY not in json.dumps(report) and PROOF not in json.dumps(report)


@pytest.mark.parametrize(
    "bad", [b"not-json", b"[]", b"{}", b'{"identity_required":true}']
)
def test_invalid_identity_status_never_falls_back_to_business_probe(
    endpoints, monkeypatch, bad
):
    state, credentials, client, requests = endpoints
    setup(client)
    observed = launcher.http_get

    def invalid_status(url, *, token=None):
        if url.endswith("/v1/identity/status"):
            requests.append((url, token))
            return bad
        return observed(url, token=token)

    monkeypatch.setattr(launcher, "http_get", invalid_status)
    with pytest.raises(launcher.LauncherError, match="identity status"):
        launcher.verify_session(state, credentials)
    assert not any(url.endswith("/v1/workspaces") for url, _ in requests)
    assert all(token is None for _, token in requests)


def test_mismatched_direct_proxy_identity_status_fails_closed(endpoints, monkeypatch):
    state, credentials, client, requests = endpoints
    setup(client)
    observed = launcher.http_get

    def changed_status(url, *, token=None):
        if (
            url
            == f"http://127.0.0.1:{state['services']['web']['port']}/v1/identity/status"
        ):
            requests.append((url, token))
            return json.dumps(
                {
                    "setup_required": True,
                    "identity_required": False,
                    "authentication_mode": "SETUP_REQUIRED",
                    "registration_policy": "ADMIN_APPROVAL",
                    "startup_capability_required": True,
                }
            ).encode()
        return observed(url, token=token)

    monkeypatch.setattr(launcher, "http_get", changed_status)
    with pytest.raises(launcher.LauncherError, match="identity status.*match"):
        launcher.verify_session(state, credentials)
    assert not any(url.endswith("/v1/workspaces") for url, _ in requests)


def test_fresh_main_api_instance_reuses_initialized_database(endpoints):
    state, credentials, client, requests = endpoints
    setup(client)
    reopened = ProductService(Path(state["product_root"]), recover_interrupted=False)
    try:
        app = create_app(reopened)
        with listener(app) as first, listener(app) as second:
            state["services"]["api"]["port"] = first
            state["services"]["web"]["port"] = second
            verification = launcher.wait_verified_session(state, credentials, timeout=2)
        assert verification["login_required"] is True
        assert verification["user_authenticated"] is False
        assert all(token is None for _, token in requests)
        assert not any(url.endswith("/v1/workspaces") for url, _ in requests)
    finally:
        reopened.close(wait=True)


@pytest.mark.parametrize("no_browser", [False, True])
def test_start_reports_existing_account_login_requirement(
    endpoints, tmp_path, monkeypatch, capsys, no_browser
):
    state, credentials, client, requests = endpoints
    setup(client)
    monkeypatch.setattr(launcher, "_port_free", lambda port: True)
    monkeypatch.setattr(launcher.subprocess, "Popen", lambda *args, **kwargs: object())
    monkeypatch.setattr(
        launcher, "wait_startup_result", lambda *args, **kwargs: (state, credentials)
    )
    opened = []
    monkeypatch.setattr(launcher, "_open", lambda *args: opened.append(True))
    args = argparse.Namespace(
        action="start",
        product_root=Path(state["product_root"]),
        initialize=False,
        api_port=state["services"]["api"]["port"],
        web_port=state["services"]["web"]["port"],
        mode="Dev",
        actor="usr_local_demo",
        no_browser=no_browser,
    )
    assert launcher._execute(args, Path(state["repo_root"]), tmp_path / "state") == 0
    report = json.loads(capsys.readouterr().out)
    assert report["status"] == "READY" and report["next_action"] == "LOGIN"
    assert report["login_required"] is True and report["user_authenticated"] is False
    assert report["business_access_verified"] is False
    assert bool(opened) is not no_browser
    assert all(token is None for _, token in requests)
