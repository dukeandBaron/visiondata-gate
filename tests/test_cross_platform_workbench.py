"""Portable launcher regressions; real services only use explicit tmp roots."""

from __future__ import annotations

import importlib.util
from io import BytesIO
import json
import os
from pathlib import Path
import socket
import subprocess

import pytest


def launcher():
    path = Path(__file__).resolve().parents[1] / "tools/run_cross_platform_workbench.py"
    assert path.is_file(), "The cross-platform workbench launcher is missing"
    spec = importlib.util.spec_from_file_location("portable_workbench", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_safe_environment_separates_api_and_web_session(tmp_path):
    tool = launcher()
    source = {
        "PATH": "/usr/bin",
        "SystemRoot": "C:/Windows",
        "OPENAI_API_KEY": "private",
        "HTTP_PROXY": "private-proxy",
        "NODE_OPTIONS": "--require private.js",
        "PYTHONPATH": "private-code",
        "VISIONDATA_SESSION_TOKEN": "inherited-token",
        "VISIONDATA_INCIDENT_MODEL_MODE": "live",
        "VISIONDATA_INSECURE_TEST_ACTOR_HEADER_BYPASS": "true",
        "VITE_PRIVATE_KEY": "private",
    }
    api, web = tool.child_environments(
        tmp_path, tmp_path / "runtime", "s" * 43, 9011, 9012, source
    )
    assert api["VISIONDATA_SESSION_TOKEN"] == "s" * 43
    assert "VISIONDATA_SESSION_TOKEN" not in web
    for environment in (api, web):
        assert (
            not {
                "OPENAI_API_KEY",
                "HTTP_PROXY",
                "NODE_OPTIONS",
                "PYTHONPATH",
                "VITE_PRIVATE_KEY",
            }
            & environment.keys()
        )
        assert "private" not in json.dumps(environment)
    assert api["VISIONDATA_INCIDENT_MODEL_MODE"] == "off"
    assert api["VISIONDATA_INSECURE_TEST_ACTOR_HEADER_BYPASS"] == "false"
    assert api["VISIONDATA_PRODUCT_ROOT"] == str(tmp_path)
    assert web["VISIONDATA_WEB_API_TARGET"] == "http://127.0.0.1:9011"
    assert api["VISIONDATA_WEB_ORIGINS"] == "http://127.0.0.1:9012"


@pytest.mark.parametrize(
    "value",
    [
        "https://outside.invalid",
        "//outside.invalid",
        "/\\outside.invalid",
        "/workspace#secret",
        "/workspace?redirect=https://outside.invalid",
        "/workspace%23x",
        "/workspace\n",
    ],
)
def test_start_path_rejects_external_or_ambiguous_targets(value):
    tool = launcher()
    with pytest.raises(tool.WorkbenchError, match="START_PATH"):
        tool.validate_start_path(value)


@pytest.mark.parametrize("value", ["/workspace", "/review", "/learning-loop", "/"])
def test_start_path_accepts_internal_paths(value):
    assert launcher().validate_start_path(value) == value


def test_occupied_port_is_rejected_before_launch():
    tool = launcher()
    with socket.socket() as listener:
        listener.bind(("127.0.0.1", 0))
        listener.listen()
        with pytest.raises(tool.WorkbenchError, match="PORT_IN_USE"):
            tool.require_free_port(listener.getsockname()[1])


def test_check_does_not_create_product_state(tmp_path, monkeypatch, capsys):
    tool = launcher()
    root = tmp_path / "must-not-exist"
    monkeypatch.setattr(tool, "preflight", lambda args: Path("node"))
    monkeypatch.setattr(
        tool, "run_workbench", lambda *args: pytest.fail("check started services")
    )
    assert tool.main(["--check", "--product-root", str(root)]) == 0
    assert not root.exists()
    assert "PREFLIGHT_PASS" in capsys.readouterr().out


def test_vite_config_disables_dotenv_and_uses_owned_lifecycle(tmp_path):
    tool = launcher()
    config = tool.vite_configuration(tmp_path, "web-public-marker")
    assert "envDir: false" in config
    assert "configureServer" in config
    assert "process.stdin.resume()" in config
    assert "server.close()" in config
    assert "web-public-marker" in config
    assert "VISIONDATA_SESSION_TOKEN" not in config


def test_identity_mismatch_refuses_session_disclosure(monkeypatch):
    tool = launcher()
    child = type("Child", (), {"poll": lambda self: None})()
    calls = []

    def request(port, path, token=None):
        calls.append(token)
        return 200, {"service": "web", "identity": "foreign-listener"}

    monkeypatch.setattr(tool, "request_json", request)
    with pytest.raises(tool.WorkbenchError, match="IDENTITY_MISMATCH"):
        tool.wait_identity(child, 9900, "web", "owned-marker", 1)
    assert calls == [None]


def test_authentication_checks_missing_wrong_and_valid_token(monkeypatch):
    tool = launcher()
    calls = []

    def request(port, path, token=None):
        calls.append((path, token))
        if path == "/v1/health":
            return 200, {
                "service": "visiondata-gate",
                "authentication": "session_token_bound_principal",
            }
        return (200, []) if token == "session" else (401, {})

    monkeypatch.setattr(tool, "request_json", request)
    tool.verify_session(1234, "session")
    assert ("/v1/projects?workspace_id=wsp_local_demo", None) in calls
    assert ("/v1/projects?workspace_id=wsp_local_demo", "session") in calls
    assert any(token and token != "session" for _, token in calls)


def test_stop_only_closes_owned_stdin_and_never_kills():
    tool = launcher()

    class Child:
        stdin = BytesIO()

        def poll(self):
            return None

        def wait(self, timeout):
            assert self.stdin.closed
            return 0

    assert tool.stop_owned_child(Child()) is True


def test_shutdown_timeout_is_reported_without_forced_termination():
    tool = launcher()

    class Child:
        stdin = BytesIO()

        def poll(self):
            return None

        def wait(self, timeout):
            raise subprocess.TimeoutExpired("owned child", timeout)

    assert tool.stop_owned_child(Child()) is False


def test_browser_receives_fragment_but_children_and_console_never_receive_it(
    tmp_path, monkeypatch, capsys
):
    tool = launcher()
    token = "secret-session-" + "s" * 40
    monkeypatch.setattr(tool.secrets, "token_urlsafe", lambda n: token)
    starts, opened = [], []

    class Child:
        def __init__(self, command, **kwargs):
            self.stdin = BytesIO()
            starts.append((command, kwargs))

        def poll(self):
            return None

        def wait(self, timeout):
            return 0

    monkeypatch.setattr(tool.subprocess, "Popen", Child)
    monkeypatch.setattr(tool, "wait_identity", lambda *args: None)
    monkeypatch.setattr(tool, "verify_session", lambda *args: None)
    monkeypatch.setattr(tool.webbrowser, "open", lambda url: opened.append(url) or True)
    args = tool.parse_args(
        ["--product-root", str(tmp_path / "product"), "--smoke-seconds", "0.01"]
    )
    assert tool.run_workbench(args, Path("node")) == 0
    assert opened == ["http://127.0.0.1:5173/workspace#visiondata_session=" + token]
    assert token not in capsys.readouterr().out
    assert len(starts) == 2
    assert token not in json.dumps([command for command, _ in starts])
    assert starts[0][1]["env"]["VISIONDATA_SESSION_TOKEN"] == token
    assert token not in json.dumps(starts[1][1]["env"])
    assert all(
        kwargs["stdout"] == subprocess.DEVNULL
        and kwargs["stderr"] == subprocess.DEVNULL
        for _, kwargs in starts
    )
    assert (tmp_path / "product").exists()


def test_no_browser_does_not_disclose_session(tmp_path, monkeypatch, capsys):
    tool = launcher()
    monkeypatch.setattr(
        tool.webbrowser, "open", lambda *args: pytest.fail("browser opened")
    )
    monkeypatch.setattr(tool, "start_children", lambda *args: [])
    args = tool.parse_args(
        [
            "--product-root",
            str(tmp_path / "product"),
            "--no-browser",
            "--smoke-seconds",
            "0.01",
        ]
    )
    assert tool.run_workbench(args, Path("node")) == 0
    output = capsys.readouterr().out
    assert "visiondata_session=" not in output
    assert "no session capability was printed" in output


def test_browser_helper_cannot_echo_capability(monkeypatch, capfd):
    tool = launcher()
    assert callable(getattr(tool, "open_browser", None)), (
        "Quiet browser dispatch is missing"
    )
    url = "http://127.0.0.1:5173/workspace#visiondata_session=secret"

    def noisy_browser(value):
        print(value)
        os.write(2, value.encode())
        return True

    monkeypatch.setattr(tool.webbrowser, "open", noisy_browser)
    assert tool.open_browser(url) is True
    output = capfd.readouterr()
    assert "secret" not in output.out + output.err


def test_failed_startup_never_claims_all_services_stopped(
    tmp_path, monkeypatch, capsys
):
    tool = launcher()

    def failed_start(*args):
        raise tool.WorkbenchError("OWNED_CHILD_SHUTDOWN_TIMEOUT")

    monkeypatch.setattr(tool, "start_children", failed_start)
    args = tool.parse_args(
        ["--product-root", str(tmp_path / "product"), "--no-browser"]
    )
    with pytest.raises(tool.WorkbenchError, match="OWNED_CHILD_SHUTDOWN_TIMEOUT"):
        tool.run_workbench(args, Path("node"))
    assert "OWNED_SERVICES_STOPPED" not in capsys.readouterr().out


def test_malformed_health_is_safely_rejected(monkeypatch):
    tool = launcher()
    monkeypatch.setattr(tool, "request_json", lambda *args: (200, []))
    with pytest.raises(tool.WorkbenchError, match="SESSION_AUTHENTICATION_NOT_BOUND"):
        tool.verify_session(1234, "session")


def test_failed_second_spawn_closes_first_owned_process(tmp_path, monkeypatch):
    tool = launcher()

    class Child:
        stdin = BytesIO()

        def poll(self):
            return None

        def wait(self, timeout):
            return 0

    child = Child()
    calls = []

    def spawn(command, **kwargs):
        calls.append(kwargs)
        if len(calls) == 2:
            raise OSError("synthetic spawn failure")
        return child

    monkeypatch.setattr(tool.subprocess, "Popen", spawn)
    monkeypatch.setattr(tool, "wait_identity", lambda *args: None)
    monkeypatch.setattr(tool, "verify_session", lambda *args: None)
    args = tool.parse_args(["--product-root", str(tmp_path)])
    with pytest.raises(OSError, match="synthetic spawn failure"):
        tool.start_children(args, Path("node"), tmp_path, "s" * 43)
    assert child.stdin.closed
    assert calls[0].get("start_new_session") is (os.name != "nt")


def test_product_path_refuses_files_and_filesystem_root(tmp_path):
    tool = launcher()
    existing = tmp_path / "file.txt"
    existing.write_text("user contents", encoding="utf-8")
    for path in (existing, Path(tmp_path.anchor)):
        with pytest.raises(
            tool.WorkbenchError, match="PRODUCT_ROOT_MUST_BE_A_DATA_DIRECTORY"
        ):
            tool.product_path(path)
    assert existing.read_text(encoding="utf-8") == "user contents"


def test_missing_python_dependency_points_to_locked_uv_setup(tmp_path, monkeypatch):
    tool = launcher()
    monkeypatch.setattr(tool.importlib.util, "find_spec", lambda name: None)
    args = tool.parse_args(["--product-root", str(tmp_path / "absent")])
    with pytest.raises(
        tool.WorkbenchError,
        match="MISSING_PYTHON_DEPENDENCIES_RUN_UV_SYNC_EXTRA_API_LOCKED",
    ):
        tool.preflight(args)
    assert not args.product_root.exists()


def test_child_argument_validation_preserves_custom_port_pair(tmp_path, monkeypatch):
    tool = launcher()
    commands = []

    class Child:
        def __init__(self, command, **kwargs):
            commands.append(command)
            self.stdin = BytesIO()

        def poll(self):
            return None

        def wait(self, timeout):
            return 0

    monkeypatch.setattr(tool.subprocess, "Popen", Child)
    monkeypatch.setattr(tool, "wait_identity", lambda *args: None)
    monkeypatch.setattr(tool, "verify_session", lambda *args: None)
    args = tool.parse_args(
        ["--api-port", "5173", "--web-port", "5174", "--product-root", str(tmp_path)]
    )
    children = tool.start_children(args, Path("node"), tmp_path, "s" * 43)
    child_args = tool.parse_args(commands[0][2:])
    assert child_args.api_port == 5173
    assert child_args.web_port == 5174
    for child in children:
        tool.stop_owned_child(child)
