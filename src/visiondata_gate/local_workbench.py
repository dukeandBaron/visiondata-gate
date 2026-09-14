"""Explicit Windows local start/status/open, independent of terminal lifetime.

The services are ordinary user processes. This is not a Windows service, a
scheduler, an auto-restart daemon, or a production identity system.
"""

from __future__ import annotations

import argparse
import ctypes
import hashlib
import hmac
import json
import os
import secrets
import shutil
import socket
import subprocess
import sys
import time
import urllib.error
import urllib.request
import webbrowser
from contextlib import contextmanager
from datetime import UTC, datetime, timedelta
from pathlib import Path

from visiondata_gate.provider_profiles import _dpapi_transform


class LauncherError(RuntimeError):
    """An actionable launcher failure whose message contains no capability."""


class EndpointUnavailable(LauncherError):
    """Startup can retry a transport timeout, but never identity/auth failures."""


def validate_product_root(root: Path, *, initialize: bool) -> Path:
    root = root.resolve()
    if not initialize and not root.is_dir():
        raise LauncherError(
            "Product directory does not exist; choose the original root or explicitly initialize a new one."
        )
    if not initialize and not (root / "product.sqlite3").is_file():
        raise LauncherError(
            "Product database does not exist; refusing to replace missing data with an empty workspace."
        )
    if initialize and root.exists() and any(root.iterdir()):
        raise LauncherError("Initialize requires an empty new product directory.")
    return root


def _canonical(value: object) -> bytes:
    return json.dumps(
        value, sort_keys=True, separators=(",", ":"), ensure_ascii=True
    ).encode()


def write_session(root: Path, state: dict, credentials: dict) -> None:
    root.mkdir(parents=True, exist_ok=True)
    state_bytes = _canonical(state)
    digest = hashlib.sha256(state_bytes).hexdigest()
    encrypted = _dpapi_transform(
        _canonical(
            {
                "state_sha256": digest,
                "credentials": credentials,
            }
        ),
        protect=True,
    )
    # Each ciphertext is immutable; state.json is the single atomic commit.
    (root / f"session-{digest}.dpapi").write_bytes(encrypted)
    staged = root / f"state-{digest}.tmp"
    staged.write_bytes(state_bytes)
    os.replace(staged, root / "state.json")


def read_session(root: Path) -> tuple[dict, dict]:
    try:
        state = json.loads((root / "state.json").read_bytes())
        digest = hashlib.sha256(_canonical(state)).hexdigest()
        ciphertext = root / f"session-{digest}.dpapi"
        if not ciphertext.is_file():
            raise LauncherError(
                "Saved state has changed or its encrypted session is missing."
            )
        payload = json.loads(_dpapi_transform(ciphertext.read_bytes(), protect=False))
        if not hmac.compare_digest(
            payload["state_sha256"], hashlib.sha256(_canonical(state)).hexdigest()
        ):
            raise LauncherError(
                "Saved state has changed; refusing to disclose the session."
            )
        return state, payload["credentials"]
    except LauncherError:
        raise
    except (OSError, ValueError, KeyError, TypeError) as exc:
        raise LauncherError(
            "Saved local session is absent or cannot be decrypted by this Windows account."
        ) from exc


@contextmanager
def start_lock(root: Path, *, caller: bool = False):
    import msvcrt

    root.mkdir(parents=True, exist_ok=True)
    filename = "caller.lock" if caller else "startup.lock"
    with (root / filename).open("a+b") as stream:
        stream.seek(0)
        try:
            msvcrt.locking(stream.fileno(), msvcrt.LK_NBLCK, 1)
        except OSError as exc:
            raise LauncherError(
                "This workbench root is already starting; wait for its result."
            ) from exc
        try:
            yield
        finally:
            stream.seek(0)
            msvcrt.locking(stream.fileno(), msvcrt.LK_UNLCK, 1)


def _powershell_json(command: str) -> object:
    executable = str(
        Path(os.environ.get("SystemRoot", r"C:\Windows"))
        / "System32/WindowsPowerShell/v1.0/powershell.exe"
    )
    result = subprocess.run(
        [executable, "-NoProfile", "-NonInteractive", "-Command", command],
        capture_output=True,
        check=False,
        encoding="utf-8-sig",
        timeout=30,
        creationflags=subprocess.CREATE_NO_WINDOW,
    )
    if result.returncode:
        raise LauncherError("Windows process identity could not be inspected.")
    return json.loads(result.stdout or "[]")


def process_snapshot() -> dict[int, dict]:
    rows = _powershell_json(
        "[Console]::OutputEncoding=[Text.UTF8Encoding]::new(); "
        "$rows=@(Get-CimInstance Win32_Process -Filter \"Name='python.exe' OR Name='node.exe'\" | "
        "ForEach-Object { [pscustomobject]@{pid=[int]$_.ProcessId;parent=[int]$_.ParentProcessId;"
        "created=$_.CreationDate.ToUniversalTime().ToString('o');command_line=$_.CommandLine} }); "
        "ConvertTo-Json -InputObject $rows -Compress"
    )
    return {row["pid"]: row for row in rows}


def listener_pids() -> dict[int, set[int]]:
    rows = _powershell_json(
        "[Console]::OutputEncoding=[Text.UTF8Encoding]::new(); "
        "$rows=@(Get-NetTCPConnection -State Listen -ErrorAction SilentlyContinue | "
        "Select-Object LocalAddress,LocalPort,OwningProcess); ConvertTo-Json -InputObject $rows -Compress"
    )
    result: dict[int, set[int]] = {}
    for row in rows:
        result.setdefault(row["LocalPort"], set()).add(row["OwningProcess"])
    return result


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def http_get(url: str, *, token: str | None = None) -> bytes:
    # Ignore machine-wide proxy settings for loopback and never redirect a token.
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}), NoRedirect())
    request = urllib.request.Request(url)
    if token:
        request.add_header("X-VisionData-Session-Token", token)
    try:
        # A freshly started local API may still be warming imports and its
        # loopback proxy. Keep the request bounded, but allow the verified
        # child more than the default five-second HTTP client budget.
        with opener.open(request, timeout=15) as response:
            return response.read(2_000_000)
    except urllib.error.HTTPError as exc:
        raise LauncherError(
            f"Local endpoint returned HTTP {exc.code}: {url.split('?')[0]}"
        ) from exc
    except (urllib.error.URLError, OSError) as exc:
        raise EndpointUnavailable(
            f"Local endpoint is unreachable: {url.split('?')[0]}"
        ) from exc


def verify_session(state: dict, credentials: dict) -> dict:
    current = process_snapshot()
    listeners = listener_pids()
    for record in state["services"].values():
        observed = current.get(record["pid"], {})
        if any(
            observed.get(key) != record[key]
            for key in ("pid", "created", "command_line")
        ):
            raise LauncherError(
                "Service process identity changed or ended; restart explicitly."
            )
        if listeners.get(record["port"]) != {record["pid"]}:
            raise LauncherError(
                "Port listener identity changed; refusing to reuse this endpoint."
            )
    # Both sockets must prove the child-only startup secret before either sees
    # a session capability. No token is sent in the readiness query.
    for record in state["services"].values():
        challenge = secrets.token_hex(32)
        proof = http_get(
            f"http://127.0.0.1:{record['port']}/v1/desktop/readiness?challenge={challenge}"
        )
        expected = hmac.new(
            credentials["startup_secret"].encode("ascii"),
            challenge.encode("ascii"),
            hashlib.sha256,
        ).hexdigest()
        if not hmac.compare_digest(proof.strip(), expected.encode("ascii")):
            raise LauncherError(
                "Local listener startup proof failed; no session was sent."
            )
    identity_statuses = []
    identity_fields = {
        "setup_required", "identity_required", "authentication_mode",
        "registration_policy", "startup_capability_required",
    }
    for record in state["services"].values():
        raw = http_get(f"http://127.0.0.1:{record['port']}/v1/identity/status")
        try:
            identity = json.loads(raw)
        except (ValueError, UnicodeError):
            raise LauncherError("Local identity status is not valid JSON.") from None
        if (
            not isinstance(identity, dict)
            or set(identity) != identity_fields
            or type(identity["setup_required"]) is not bool
            or type(identity["identity_required"]) is not bool
            or identity["startup_capability_required"] is not True
            or identity["registration_policy"] != "ADMIN_APPROVAL"
            or identity["identity_required"] is identity["setup_required"]
            or identity["authentication_mode"] != (
                "SETUP_REQUIRED" if identity["setup_required"] else "USER_SESSION"
            )
        ):
            raise LauncherError("Local identity status does not satisfy its contract.")
        identity_statuses.append(identity)
    if len(identity_statuses) != 2 or identity_statuses[0] != identity_statuses[1]:
        raise LauncherError("API and web proxy identity status responses do not match.")
    identity = identity_statuses[0]
    verification = {
        "authentication_mode": identity["authentication_mode"],
        "setup_required": identity["setup_required"],
        "login_required": identity["identity_required"],
        "user_authenticated": False,
        "business_access_verified": False,
        "next_action": "INITIALIZE_ACCOUNT" if identity["setup_required"] else "LOGIN",
    }
    # A child-process capability is not a user session. Once accounts exist,
    # readiness ends here; the browser obtains its own in-memory Bearer at login.
    if identity["identity_required"]:
        return verification
    responses = [
        http_get(
            f"http://127.0.0.1:{record['port']}/v1/workspaces",
            token=credentials["session_token"],
        )
        for record in state["services"].values()
    ]
    if json.loads(responses[0]) != json.loads(responses[1]):
        raise LauncherError("API and web proxy workspace responses do not match.")
    return verification


def wait_verified_session(
    state: dict, credentials: dict, *, timeout: float = 60
) -> dict:
    deadline = time.monotonic() + timeout
    while True:
        try:
            return verify_session(state, credentials)
        except EndpointUnavailable:
            if time.monotonic() >= deadline:
                raise
            time.sleep(0.5)


def _port_free(port: int) -> bool:
    try:
        with socket.socket() as probe:
            probe.setsockopt(socket.SOL_SOCKET, socket.SO_EXCLUSIVEADDRUSE, 1)
            probe.bind(("127.0.0.1", port))
        return True
    except OSError:
        return False


def _descendant(pid: int, ancestor: int, records: dict[int, dict]) -> bool:
    seen: set[int] = set()
    while pid and pid not in seen:
        if pid == ancestor:
            return True
        seen.add(pid)
        pid = records.get(pid, {}).get("parent", 0)
    return False


def _service_record(port: int, process: subprocess.Popen, expected_marker: str) -> dict:
    records = process_snapshot()
    owners = listener_pids().get(port, set())
    if len(owners) != 1:
        raise LauncherError("A local service did not obtain its exclusive port.")
    pid = next(iter(owners))
    record = records.get(pid, {})
    if not _descendant(pid, process.pid, records) or expected_marker not in record.get(
        "command_line", ""
    ):
        raise LauncherError(
            "A different process took the requested port; session remains undisclosed."
        )
    return {key: record[key] for key in ("pid", "created", "command_line")} | {
        "port": port
    }


def _wait_listener(port: int, process: subprocess.Popen, timeout: float = 90) -> None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if process.poll() is not None:
            raise LauncherError(
                "Service exited during startup; inspect the local service log."
            )
        try:
            with socket.create_connection(("127.0.0.1", port), timeout=0.3):
                return
        except OSError:
            time.sleep(0.3)
    raise LauncherError("Local service startup timed out.")


def terminate_verified_process(record: dict) -> bool:
    """Pin one process handle and recheck its creation time before termination."""
    from ctypes import wintypes

    kernel = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
    kernel.OpenProcess.restype = wintypes.HANDLE
    kernel.GetProcessTimes.argtypes = [wintypes.HANDLE] + [
        ctypes.POINTER(wintypes.FILETIME)
    ] * 4
    kernel.GetProcessTimes.restype = wintypes.BOOL
    kernel.TerminateProcess.argtypes = [wintypes.HANDLE, wintypes.UINT]
    kernel.TerminateProcess.restype = wintypes.BOOL
    kernel.CloseHandle.argtypes = [wintypes.HANDLE]
    handle = kernel.OpenProcess(0x1000 | 0x0001, False, record["pid"])
    if not handle:
        return False
    try:
        times = [wintypes.FILETIME() for _ in range(4)]
        if not kernel.GetProcessTimes(handle, *(ctypes.byref(item) for item in times)):
            return False
        ticks = (times[0].dwHighDateTime << 32) | times[0].dwLowDateTime
        created = datetime(1601, 1, 1, tzinfo=UTC) + timedelta(microseconds=ticks // 10)
        if created != datetime.fromisoformat(record["created"]):
            return False
        return bool(kernel.TerminateProcess(handle, 1))
    finally:
        kernel.CloseHandle(handle)


def _cleanup_owned_children(children: list[subprocess.Popen]) -> None:
    records = process_snapshot()
    for process in reversed(children):
        if process.poll() is not None:
            continue
        descendants = [
            record
            for pid, record in records.items()
            if pid != process.pid and _descendant(pid, process.pid, records)
        ]
        for record in reversed(descendants):
            terminate_verified_process(record)
        process.terminate()
        process.wait(timeout=5)


def web_environment(config: dict) -> dict[str, str]:
    env = {
        key: value
        for key, value in os.environ.items()
        if not key.startswith(("VISIONDATA_", "AGENTTEAMS_"))
        and "API_KEY" not in key
        and "TOKEN" not in key
    }
    env.update(
        {
            "VISIONDATA_WEB_API_TARGET": f"http://127.0.0.1:{config['api_port']}",
            "VISIONDATA_WEB_BASE_PATH": "/",
            "VITE_VISIONDATA_API_BASE_URL": "",
            "VITE_VISIONDATA_PUBLIC_REPLAY": "false",
            "VITE_VISIONDATA_ACTOR_USER_ID": config["actor"],
        }
    )
    return env


def _run_startup(config: dict, state_root: Path) -> None:
    repo = Path(config["repo_root"])
    product = Path(config["product_root"])
    if config["initialize"]:
        product.mkdir(parents=True, exist_ok=True)
    for port in (config["api_port"], config["web_port"]):
        if not _port_free(port):
            raise LauncherError(
                f"Port {port} is already occupied; no listener was reused."
            )
    token, proof_key = secrets.token_urlsafe(32), secrets.token_hex(32)
    api_env = dict(os.environ)
    api_env.update(
        {
            "PYTHONPATH": str(repo / "src"),
            "VISIONDATA_PRODUCT_ROOT": str(product),
            "VISIONDATA_SESSION_TOKEN": token,
            "VISIONDATA_DESKTOP_SESSION_TOKEN": token,
            "VISIONDATA_DESKTOP_STARTUP_SECRET": proof_key,
            "VISIONDATA_SESSION_ACTOR_USER_ID": config["actor"],
            "VISIONDATA_WEB_ORIGINS": f"http://127.0.0.1:{config['web_port']}",
        }
    )
    api_env.pop("VISIONDATA_INSECURE_TEST_ACTOR_HEADER_BYPASS", None)
    node = shutil.which("node")
    vite = repo / "web/node_modules/vite/bin/vite.js"
    if not node or not vite.is_file():
        raise LauncherError(
            "Node.js or installed web dependencies are missing; run the existing setup first."
        )
    # Node receives no model/session credentials. It remains an ordinary proxy.
    web_env = web_environment(config)
    web_args = [node, str(vite)]
    if config["mode"] == "Preview":
        bundle = state_root / "bundles" / config["instance"]
        npm = shutil.which("npm.cmd")
        if not npm:
            raise LauncherError("npm.cmd is unavailable.")
        with (state_root / "build.log").open("wb") as stream:
            completed = subprocess.run(
                [npm, "run", "build", "--", "--outDir", str(bundle)],
                check=False,
                cwd=repo / "web",
                env=web_env,
                stdout=stream,
                stderr=subprocess.STDOUT,
                creationflags=subprocess.CREATE_NO_WINDOW,
            )
        if completed.returncode:
            raise LauncherError("Web build failed; inspect build.log.")
        web_args += ["preview", "--outDir", str(bundle)]
    web_args += [
        "--host",
        "127.0.0.1",
        "--port",
        str(config["web_port"]),
        "--strictPort",
    ]
    api_args = [
        sys.executable,
        "-m",
        "uvicorn",
        "visiondata_gate.api:app",
        "--app-dir",
        str(repo / "src"),
        "--host",
        "127.0.0.1",
        "--port",
        str(config["api_port"]),
        "--no-access-log",
    ]
    children: list[subprocess.Popen] = []
    try:
        for name, args, cwd, env in (
            ("api", api_args, repo, api_env),
            ("web", web_args, repo / "web", web_env),
        ):
            with (state_root / f"{name}.log").open("wb") as stream:
                children.append(
                    subprocess.Popen(
                        args,
                        cwd=cwd,
                        env=env,
                        stdin=subprocess.DEVNULL,
                        stdout=stream,
                        stderr=subprocess.STDOUT,
                        creationflags=subprocess.CREATE_NO_WINDOW,
                        close_fds=True,
                    )
                )
        _wait_listener(config["api_port"], children[0])
        _wait_listener(config["web_port"], children[1])
        state = {
            "schema": 1,
            "repo_root": str(repo),
            "product_root": str(product),
            "mode": config["mode"],
            "instance": config["instance"],
            "services": {
                "api": _service_record(
                    config["api_port"], children[0], str(repo / "src")
                ),
                "web": _service_record(config["web_port"], children[1], str(vite)),
            },
        }
        credentials = {"session_token": token, "startup_secret": proof_key}
        wait_verified_session(state, credentials)
        write_session(state_root, state, credentials)
    except BaseException:
        _cleanup_owned_children(children)
        raise


def _state_root(repo: Path) -> Path:
    base = os.environ.get("LOCALAPPDATA")
    if not base:
        raise LauncherError("LOCALAPPDATA is unavailable.")
    identity = hashlib.sha256(str(repo).casefold().encode()).hexdigest()[:16]
    return Path(base) / "VisionData Gate/workbench" / identity


def _open(state: dict, credentials: dict) -> None:
    # The fragment is consumed by browserSession.ts and never sent over HTTP.
    url = f"http://127.0.0.1:{state['services']['web']['port']}/workspace#visiondata_session={credentials['session_token']}"
    webbrowser.open(url)


def _report(state: dict, *, opened: bool, verification: dict) -> None:
    print(
        json.dumps(
            {
                "status": "READY",
                **verification,
                "repo_root": state["repo_root"],
                "product_root": state["product_root"],
                "api_url": f"http://127.0.0.1:{state['services']['api']['port']}",
                "web_url": f"http://127.0.0.1:{state['services']['web']['port']}/workspace",
                "browser_open_requested": opened,
                "session_values_exposed": False,
                "lifetime": "independent_user_processes_until_exit_or_windows_shutdown",
            },
            ensure_ascii=True,
        )
    )


_HELPER_BOOTSTRAP = """import json, os, sys
from pathlib import Path
repo, location, instance = sys.argv[1:]
root = Path(location)
def note(stage, code=None, exception_type=None):
    value = {'instance': instance, 'stage': stage, 'pid': os.getpid(),
             'exit_code': code, 'exception_type': exception_type}
    staged = root / ('startup-diagnostic-' + instance + '.tmp')
    staged.write_text(json.dumps(value), encoding='utf-8')
    os.replace(staged, root / ('startup-diagnostic-' + instance + '.json'))
note('PYTHON_STARTED')
try:
    from visiondata_gate.local_workbench import main
    note('HELPER_IMPORTED')
    code = main(['_startup', '--repo-root', repo, '--state-root', location,
                 '--instance', instance])
except BaseException as error:
    allowed = {'SystemExit', 'ModuleNotFoundError', 'ImportError', 'SyntaxError',
               'IndentationError', 'FileNotFoundError', 'PermissionError',
               'OSError', 'RuntimeError', 'ValueError', 'TypeError'}
    name = type(error).__name__
    code = error.code if isinstance(error, SystemExit) and type(error.code) is int else 1
    note('HELPER_FAILED', code, name if name in allowed else 'Exception')
else:
    note('HELPER_EXITED', code)
raise SystemExit(code)
"""


def helper_command(repo: Path, root: Path, instance: str) -> list[str]:
    """Record safe stages even when importing the application fails early."""
    return [sys.executable, "-c", _HELPER_BOOTSTRAP, str(repo), str(root), instance]


def _startup_result(root: Path, instance: str) -> tuple[dict, dict] | None:
    if (root / "state.json").exists():
        state, credentials = read_session(root)
        if state.get("instance") == instance:
            return state, credentials
    error_path = root / f"startup-error-{instance}.json"
    if error_path.exists():
        error = json.loads(error_path.read_bytes())
        if error.get("instance") == instance:
            raise LauncherError(error["error"])
    return None


def _record_helper_exit(root: Path, instance: str, code: int) -> LauncherError:
    stage = "NO_PYTHON_DIAGNOSTIC"
    diagnostic_path = root / f"startup-diagnostic-{instance}.json"
    if diagnostic_path.is_file():
        try:
            diagnostic = json.loads(diagnostic_path.read_bytes())
            if diagnostic.get("instance") == instance and diagnostic.get("stage") in {
                "PYTHON_STARTED",
                "HELPER_IMPORTED",
                "HELPER_FAILED",
                "HELPER_EXITED",
            }:
                stage = diagnostic["stage"]
        except (OSError, ValueError, TypeError, AttributeError):
            stage = "DIAGNOSTIC_UNAVAILABLE"
    message = (
        f"Independent startup exited before becoming ready (exit code {code}, "
        f"last stage {stage}); no automatic restart was performed."
    )
    staged = root / f"startup-error-{instance}.tmp"
    staged.write_bytes(
        _canonical(
            {
                "instance": instance,
                "error": message,
                "process_exit_code": code,
                "last_stage": stage,
                "raw_stderr_retained": False,
            }
        )
    )
    os.replace(staged, root / f"startup-error-{instance}.json")
    return LauncherError(message)


def wait_startup_result(process, root: Path, instance: str, *, timeout: float):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        result = _startup_result(root, instance)
        if result is not None:
            return result
        code = process.poll()
        if code is not None:
            # The helper may have published state after our preceding read and
            # before poll observed its exit. Re-read both terminal artifacts.
            result = _startup_result(root, instance)
            if result is not None:
                return result
            raise _record_helper_exit(root, instance, code)
        time.sleep(0.5)
    raise LauncherError(
        "Startup has not completed; inspect status/logs before retrying."
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=("start", "status", "open", "_startup"))
    parser.add_argument(
        "--repo-root", type=Path, default=Path(__file__).resolve().parents[2]
    )
    parser.add_argument("--product-root", type=Path)
    parser.add_argument("--state-root", type=Path)
    parser.add_argument("--instance")
    parser.add_argument("--api-port", type=int, default=8787)
    parser.add_argument("--web-port", type=int, default=5173)
    parser.add_argument("--mode", choices=("Dev", "Preview"), default="Dev")
    parser.add_argument("--actor", default="usr_local_demo")
    parser.add_argument("--initialize", action="store_true")
    parser.add_argument("--no-browser", action="store_true")
    args = parser.parse_args(argv)
    if os.name != "nt":
        parser.error(
            "This launcher requires Windows DPAPI and native process isolation."
        )
    repo = args.repo_root.resolve()
    root = (args.state_root or _state_root(repo)).resolve()
    try:
        if args.action == "start":
            with start_lock(root, caller=True):
                # A detached helper owns this lock even if its caller exits.
                with start_lock(root):
                    pass
                return _execute(args, repo, root)
        return _execute(args, repo, root)
    except LauncherError as exc:
        print(
            json.dumps(
                {
                    "status": "NOT_READY",
                    "error": str(exc),
                    "session_values_exposed": False,
                }
            )
        )
        return 1


def _execute(args, repo: Path, root: Path) -> int:
    try:
        if args.action == "_startup":
            if (
                not args.instance
                or len(args.instance) != 24
                or any(c not in "0123456789abcdef" for c in args.instance)
            ):
                raise LauncherError("An explicit startup instance is required.")
            config = json.loads((root / f"startup-{args.instance}.json").read_bytes())
            try:
                with start_lock(root):
                    _run_startup(config, root)
            except Exception as exc:  # noqa: BLE001 - redact all startup failure details
                message = (
                    str(exc)
                    if isinstance(exc, LauncherError)
                    else f"Startup failed ({type(exc).__name__}); inspect local logs."
                )
                staged = root / f"startup-error-{args.instance}.tmp"
                staged.write_text(
                    json.dumps({"instance": config["instance"], "error": message}),
                    encoding="utf-8",
                )
                os.replace(staged, root / f"startup-error-{args.instance}.json")
                return 1
            return 0
        if args.action != "start":
            state, credentials = read_session(root)
            if Path(state["repo_root"]).resolve() != repo:
                raise LauncherError(
                    "Saved repository root does not match this launcher."
                )
            if (
                args.product_root
                and Path(state["product_root"]).resolve() != args.product_root.resolve()
            ):
                raise LauncherError(
                    "Saved product root does not match the requested data."
                )
            validate_product_root(Path(state["product_root"]), initialize=False)
            verification = verify_session(state, credentials)
            if args.action == "open":
                _open(state, credentials)
            _report(state, opened=args.action == "open", verification=verification)
            return 0
        product = validate_product_root(
            args.product_root or repo / "output/product", initialize=args.initialize
        )
        if not (repo / "src/visiondata_gate/api.py").is_file():
            raise LauncherError("The repository API source is missing.")
        if (
            not 1024 <= args.api_port <= 65535
            or not 1024 <= args.web_port <= 65535
            or args.api_port == args.web_port
        ):
            raise LauncherError("Choose distinct ports between 1024 and 65535.")
        if any(not _port_free(port) for port in (args.api_port, args.web_port)):
            raise LauncherError(
                "Requested port is occupied. Use open for an owned session; unrelated listeners are never reused."
            )
        root.mkdir(parents=True, exist_ok=True)
        if (root / "state.json").exists():
            old, _ = read_session(root)
            records = process_snapshot()
            if any(
                records.get(item["pid"], {}).get("created") == item["created"]
                for item in old["services"].values()
            ):
                raise LauncherError(
                    "A saved service is still running. Use status/open; no duplicate session was started."
                )
        config = {
            "repo_root": str(repo),
            "product_root": str(product),
            "mode": args.mode,
            "api_port": args.api_port,
            "web_port": args.web_port,
            "initialize": args.initialize,
            "actor": args.actor,
            "instance": secrets.token_hex(12),
        }
        (root / f"startup-{config['instance']}.json").write_bytes(_canonical(config))
        flags = (
            subprocess.DETACHED_PROCESS
            | subprocess.CREATE_NEW_PROCESS_GROUP
            | subprocess.CREATE_BREAKAWAY_FROM_JOB
        )
        env = dict(os.environ, PYTHONPATH=str(repo / "src"))
        try:
            process = subprocess.Popen(
                helper_command(repo, root, config["instance"]),
                cwd=repo,
                env=env,
                stdin=subprocess.DEVNULL,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                close_fds=True,
                creationflags=flags,
            )
        except OSError as exc:
            raise LauncherError(
                "Windows refused independent process creation; run this launcher from your own PowerShell window."
            ) from exc
        state, credentials = wait_startup_result(
            process,
            root,
            config["instance"],
            timeout=240 if args.mode == "Preview" else 120,
        )
        verification = verify_session(state, credentials)
        if not args.no_browser:
            _open(state, credentials)
        _report(state, opened=not args.no_browser, verification=verification)
        return 0
    except LauncherError as exc:
        print(
            json.dumps(
                {
                    "status": "NOT_READY",
                    "error": str(exc),
                    "session_values_exposed": False,
                }
            )
        )
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
