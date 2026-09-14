"""Boundaries for the persistent, Windows-only local workbench launcher."""

from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path

import pytest

from visiondata_gate import local_workbench as launcher


def test_missing_product_root_is_not_silently_initialized(tmp_path: Path) -> None:
    root = tmp_path / "missing"
    with pytest.raises(launcher.LauncherError, match="does not exist"):
        launcher.validate_product_root(root, initialize=False)
    assert not root.exists()
    assert launcher.validate_product_root(root, initialize=True) == root.resolve()


@pytest.mark.skipif(os.name != "nt", reason="Windows DPAPI")
def test_saved_session_is_encrypted_and_bound_to_public_state(tmp_path: Path) -> None:
    state = {"schema": 1, "repo_root": str(tmp_path), "api_port": 8787}
    secret = "private-session-" + "a" * 40
    launcher.write_session(tmp_path, state, {"session_token": secret})
    plain = (tmp_path / "state.json").read_text(encoding="utf-8")
    encrypted = next(tmp_path.glob("session-*.dpapi")).read_bytes()
    assert secret not in plain
    assert secret.encode() not in encrypted
    assert launcher.read_session(tmp_path) == (state, {"session_token": secret})
    modified = json.loads(plain)
    modified["api_port"] = 9999
    (tmp_path / "state.json").write_text(json.dumps(modified), encoding="utf-8")
    with pytest.raises(launcher.LauncherError, match="state.*changed"):
        launcher.read_session(tmp_path)


def test_listener_identity_mismatch_rejected_before_any_network(monkeypatch) -> None:
    state = {
        "repo_root": "R",
        "product_root": "P",
        "services": {
            "api": {
                "pid": 10,
                "created": "old",
                "command_line": "correct",
                "port": 9001,
            },
            "web": {"pid": 20, "created": "ok", "command_line": "web", "port": 9002},
        },
    }
    monkeypatch.setattr(
        launcher,
        "process_snapshot",
        lambda: {
            10: {"pid": 10, "created": "new", "command_line": "correct"},
            20: {"pid": 20, "created": "ok", "command_line": "web"},
        },
    )
    monkeypatch.setattr(launcher, "listener_pids", lambda: {9001: {10}, 9002: {20}})
    requests = []
    monkeypatch.setattr(launcher, "http_get", lambda *a, **kw: requests.append((a, kw)))
    with pytest.raises(launcher.LauncherError, match="identity"):
        launcher.verify_session(
            state, {"session_token": "secret", "startup_secret": "proof"}
        )
    assert requests == []


def test_failed_startup_proof_never_transmits_session_token(monkeypatch) -> None:
    services = {
        "api": {"pid": 10, "created": "t", "command_line": "api", "port": 9001},
        "web": {"pid": 20, "created": "t", "command_line": "web", "port": 9002},
    }
    state = {"services": services}
    monkeypatch.setattr(
        launcher, "process_snapshot", lambda: {x["pid"]: x for x in services.values()}
    )
    monkeypatch.setattr(launcher, "listener_pids", lambda: {9001: {10}, 9002: {20}})
    headers = []

    def fake_get(url, *, token=None):
        headers.append(token)
        return b"untrusted-listener"

    monkeypatch.setattr(launcher, "http_get", fake_get)
    with pytest.raises(launcher.LauncherError, match="proof"):
        launcher.verify_session(
            state, {"session_token": "DO-NOT-SEND", "startup_secret": "proof"}
        )
    assert headers == [None]


def test_workspace_identity_must_match_between_direct_and_proxy(monkeypatch) -> None:
    import hmac

    services = {
        "api": {"pid": 10, "created": "t", "command_line": "api", "port": 9001},
        "web": {"pid": 20, "created": "t", "command_line": "web", "port": 9002},
    }
    monkeypatch.setattr(
        launcher, "process_snapshot", lambda: {x["pid"]: x for x in services.values()}
    )
    monkeypatch.setattr(launcher, "listener_pids", lambda: {9001: {10}, 9002: {20}})

    def fake_get(url, *, token=None):
        if "challenge=" in url:
            challenge = url.split("challenge=", 1)[1]
            return (
                hmac.new(b"proof", challenge.encode(), hashlib.sha256)
                .hexdigest()
                .encode()
            )
        if url.endswith("/v1/identity/status"):
            return json.dumps(
                {
                    "setup_required": True,
                    "identity_required": False,
                    "authentication_mode": "SETUP_REQUIRED",
                    "registration_policy": "ADMIN_APPROVAL",
                    "startup_capability_required": True,
                }
            ).encode()
        return b'{"workspaces":[1]}' if ":9001/" in url else b'{"workspaces":[2]}'

    monkeypatch.setattr(launcher, "http_get", fake_get)
    with pytest.raises(launcher.LauncherError, match="workspace"):
        launcher.verify_session(
            {"services": services},
            {"session_token": "secret", "startup_secret": "proof"},
        )


def _verified_listener_fixture(monkeypatch, identity_status):
    import hmac

    services = {
        "api": {"pid": 10, "created": "t", "command_line": "api", "port": 9001},
        "web": {"pid": 20, "created": "t", "command_line": "web", "port": 9002},
    }
    monkeypatch.setattr(
        launcher, "process_snapshot", lambda: {x["pid"]: x for x in services.values()}
    )
    monkeypatch.setattr(launcher, "listener_pids", lambda: {9001: {10}, 9002: {20}})
    requests = []

    def get(url, *, token=None):
        requests.append((url, token))
        if "challenge=" in url:
            challenge = url.split("challenge=", 1)[1]
            return (
                hmac.new(b"proof", challenge.encode(), hashlib.sha256)
                .hexdigest()
                .encode()
            )
        return json.dumps(identity_status).encode()

    monkeypatch.setattr(launcher, "http_get", get)
    return (
        {"services": services},
        {"session_token": "NEVER-SEND", "startup_secret": "proof"},
        requests,
    )


@pytest.mark.parametrize(
    "change",
    [
        {"setup_required": 0},
        {"identity_required": 1},
        {"setup_required": "false"},
        {"setup_required": True},
        {"authentication_mode": "UNKNOWN"},
        {"registration_policy": "OPEN"},
        {"startup_capability_required": False},
        {"extra": "not allowed"},
    ],
)
def test_identity_status_rejects_invalid_types_and_contradictions(monkeypatch, change):
    identity = {
        "setup_required": False,
        "identity_required": True,
        "authentication_mode": "USER_SESSION",
        "registration_policy": "ADMIN_APPROVAL",
        "startup_capability_required": True,
    }
    state, credentials, requests = _verified_listener_fixture(
        monkeypatch, {**identity, **change}
    )
    with pytest.raises(launcher.LauncherError, match="identity status"):
        launcher.verify_session(state, credentials)
    assert all(token is None for _, token in requests)
    assert not any(url.endswith("/v1/workspaces") for url, _ in requests)


def test_second_proof_failure_blocks_status_queries_and_capability(monkeypatch):
    state, credentials, requests = _verified_listener_fixture(monkeypatch, {})
    observed = launcher.http_get

    def second_invalid(url, *, token=None):
        if ":9002/" in url:
            requests.append((url, token))
            return b"invalid-second-proof"
        return observed(url, token=token)

    monkeypatch.setattr(launcher, "http_get", second_invalid)
    with pytest.raises(launcher.LauncherError, match="proof"):
        launcher.verify_session(state, credentials)
    assert len(requests) == 2
    assert all(
        "/v1/desktop/readiness?" in url and token is None for url, token in requests
    )


@pytest.mark.parametrize("code", [401, 403, 404, 500])
def test_identity_http_error_never_falls_back_to_legacy_authority(monkeypatch, code):
    state, credentials, requests = _verified_listener_fixture(monkeypatch, {})
    observed = launcher.http_get

    def failed_status(url, *, token=None):
        if url.endswith("/v1/identity/status"):
            requests.append((url, token))
            raise launcher.LauncherError(f"Local endpoint returned HTTP {code}")
        return observed(url, token=token)

    monkeypatch.setattr(launcher, "http_get", failed_status)
    with pytest.raises(launcher.LauncherError, match=f"HTTP {code}"):
        launcher.wait_verified_session(state, credentials, timeout=2)
    assert all(token is None for _, token in requests)
    assert not any(url.endswith("/v1/workspaces") for url, _ in requests)


def test_cross_origin_redirect_is_not_followed() -> None:
    request = launcher.NoRedirect()
    assert (
        request.redirect_request(None, None, 302, "Found", {}, "http://example.org")
        is None
    )


@pytest.mark.skipif(os.name != "nt", reason="Windows file lock")
def test_concurrent_start_for_same_root_is_rejected(tmp_path: Path) -> None:
    with (
        launcher.start_lock(tmp_path),
        pytest.raises(launcher.LauncherError, match="already starting"),
        launcher.start_lock(tmp_path),
    ):
        pytest.fail("a second startup acquired the same root")
    with launcher.start_lock(tmp_path):
        pass


@pytest.mark.skipif(os.name != "nt", reason="Windows DPAPI")
def test_old_session_remains_readable_while_new_ciphertext_is_staged(
    tmp_path: Path, monkeypatch
) -> None:
    old = {"instance": "old"}
    launcher.write_session(tmp_path, old, {"session_token": "old-token"})
    replace = os.replace
    observed = []

    def verify_before_publication(source, target):
        observed.append(True)
        assert launcher.read_session(tmp_path) == (old, {"session_token": "old-token"})
        replace(source, target)

    monkeypatch.setattr(launcher.os, "replace", verify_before_publication)
    launcher.write_session(
        tmp_path, {"instance": "new"}, {"session_token": "new-token"}
    )
    assert observed == [True]
    assert launcher.read_session(tmp_path)[1]["session_token"] == "new-token"


def test_startup_retries_transient_transport_but_never_bad_identity(
    monkeypatch,
) -> None:
    observations = []

    def delayed(state, credentials):
        observations.append(True)
        if len(observations) == 1:
            raise launcher.EndpointUnavailable("not ready")
        return {"workspaces": []}

    monkeypatch.setattr(launcher, "verify_session", delayed)
    monkeypatch.setattr(launcher.time, "sleep", lambda seconds: None)
    assert launcher.wait_verified_session({}, {}, timeout=2) == {"workspaces": []}
    assert len(observations) == 2

    def untrusted(state, credentials):
        raise launcher.LauncherError("proof failed")

    monkeypatch.setattr(launcher, "verify_session", untrusted)
    with pytest.raises(launcher.LauncherError, match="proof failed"):
        launcher.wait_verified_session({}, {}, timeout=2)


def test_local_browser_config_cannot_forward_capability_to_stale_remote_api(
    monkeypatch,
) -> None:
    monkeypatch.setenv("VITE_VISIONDATA_API_BASE_URL", "https://untrusted.example")
    monkeypatch.setenv("VITE_VISIONDATA_PUBLIC_REPLAY", "true")
    monkeypatch.setenv("VITE_VISIONDATA_ACTOR_USER_ID", "different-user")
    monkeypatch.setenv("VISIONDATA_WEB_BASE_PATH", "/old/")
    monkeypatch.setenv("VISIONDATA_INCIDENT_MODEL_API_KEY", "private-key")
    env = launcher.web_environment({"api_port": 8787, "actor": "actual-user"})
    assert env["VITE_VISIONDATA_API_BASE_URL"] == ""
    assert env["VITE_VISIONDATA_PUBLIC_REPLAY"] == "false"
    assert env["VITE_VISIONDATA_ACTOR_USER_ID"] == "actual-user"
    assert env["VISIONDATA_WEB_BASE_PATH"] == "/"
    assert "VISIONDATA_INCIDENT_MODEL_API_KEY" not in env


def test_failed_start_cleans_only_its_live_descendants(monkeypatch) -> None:
    records = {
        10: {"pid": 10, "parent": 1},
        11: {"pid": 11, "parent": 10},
        12: {"pid": 12, "parent": 11},
        99: {"pid": 99, "parent": 2},
    }
    terminated = []

    class OwnedProcess:
        pid = 10

        def poll(self):
            return None

        def terminate(self):
            terminated.append(10)

        def wait(self, timeout):
            return 1

    monkeypatch.setattr(launcher, "process_snapshot", lambda: records)
    monkeypatch.setattr(
        launcher,
        "terminate_verified_process",
        lambda record: terminated.append(record["pid"]),
    )
    launcher._cleanup_owned_children([OwnedProcess()])
    assert terminated == [12, 11, 10]


@pytest.mark.skipif(os.name != "nt", reason="Windows native process identity")
def test_native_cleanup_handles_windows_venv_redirector() -> None:
    import subprocess
    import sys

    process = subprocess.Popen(
        [sys.executable, "-c", "import time; time.sleep(60)"],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        creationflags=subprocess.CREATE_NO_WINDOW,
    )
    try:
        before = launcher.process_snapshot()
        descendants = [
            pid for pid in before if launcher._descendant(pid, process.pid, before)
        ]
        assert descendants
        launcher._cleanup_owned_children([process])
        after = launcher.process_snapshot()
        assert not any(
            pid in after and before[pid]["created"] == after[pid]["created"]
            for pid in descendants
        )
    finally:
        if process.poll() is None:
            launcher._cleanup_owned_children([process])


@pytest.mark.skipif(os.name != "nt", reason="Windows DPAPI")
def test_helper_exit_rechecks_state_published_after_the_last_poll(tmp_path):
    instance = "a" * 24

    class CompletedProcess:
        def poll(self):
            launcher.write_session(
                tmp_path, {"instance": instance}, {"fixture": "sealed"}
            )
            return 0

    state, credentials = launcher.wait_startup_result(
        CompletedProcess(), tmp_path, instance, timeout=2
    )
    assert state["instance"] == instance
    assert credentials == {"fixture": "sealed"}
    assert not (tmp_path / f"startup-error-{instance}.json").exists()


@pytest.mark.skipif(os.name != "nt", reason="Windows native helper bootstrap")
def test_detached_import_failure_records_type_without_sensitive_exception_text(
    tmp_path,
):
    import subprocess

    package = tmp_path / "import-root" / "visiondata_gate"
    package.mkdir(parents=True)
    secret = "fixture-sensitive-exception-value"
    (package / "__init__.py").write_text(
        f"raise RuntimeError({secret!r})", encoding="utf-8"
    )
    root = tmp_path / "state"
    root.mkdir()
    instance = "b" * 24
    command = launcher.helper_command(
        Path(__file__).resolve().parents[1], root, instance
    )
    env = dict(os.environ, PYTHONPATH=str(package.parent))
    result = subprocess.run(
        command,
        env=env,
        stdin=subprocess.DEVNULL,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        creationflags=subprocess.DETACHED_PROCESS
        | subprocess.CREATE_NEW_PROCESS_GROUP
        | subprocess.CREATE_BREAKAWAY_FROM_JOB,
        timeout=30,
        check=False,
    )
    assert result.returncode == 1
    raw = (root / f"startup-diagnostic-{instance}.json").read_text(encoding="utf-8")
    assert secret not in raw
    diagnostic = json.loads(raw)
    assert diagnostic["stage"] == "HELPER_FAILED"
    assert diagnostic["exception_type"] == "RuntimeError"
    assert diagnostic["exit_code"] == 1


def test_native_early_exit_retains_code_and_does_not_invent_an_import_diagnosis(
    tmp_path,
):
    instance = "c" * 24

    class EarlyExit:
        def poll(self):
            return 73

    with pytest.raises(launcher.LauncherError, match="exit code 73"):
        launcher.wait_startup_result(EarlyExit(), tmp_path, instance, timeout=2)
    error = json.loads((tmp_path / f"startup-error-{instance}.json").read_bytes())
    assert error["process_exit_code"] == 73
    assert error["last_stage"] == "NO_PYTHON_DIAGNOSTIC"
