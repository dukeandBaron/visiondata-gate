"""Start the local API and Vite development workbench without PowerShell.

Use the current Python environment and already installed web dependencies. No
installation, dotenv loading, model calls, or deletion is performed. Product
data and per-run runtime/cache directories are retained under --product-root.
This is a local development launcher, not a packaged desktop application.
"""

from __future__ import annotations

import argparse
from contextlib import redirect_stderr, redirect_stdout
import http.client
import importlib.util
import json
import os
from pathlib import Path
import re
import secrets
import shutil
import socket
import stat
import subprocess
import sys
import tempfile
import threading
import time
import webbrowser


PROJECT = Path(__file__).resolve().parents[1]
IDENTITY_PATH = "/__visiondata_workbench_identity__"
ENV_ALLOWLIST = {
    "PATH",
    "SYSTEMROOT",
    "WINDIR",
    "COMSPEC",
    "SYSTEMDRIVE",
    "PATHEXT",
    "NUMBER_OF_PROCESSORS",
    "LANG",
    "LC_ALL",
    "LC_CTYPE",
}


class WorkbenchError(RuntimeError):
    """A fixed error code, never a secret or untrusted child response."""


def validate_start_path(value: str) -> str:
    # Keep navigation deliberately simple: no query, fragment, encoded paths,
    # backslashes, dot segments, or user-supplied authority/redirect parameters.
    if value != "/" and not re.fullmatch(r"/[A-Za-z0-9_-]+(?:/[A-Za-z0-9_-]+)*", value):
        raise WorkbenchError("START_PATH_MUST_BE_A_PLAIN_INTERNAL_PATH")
    return value


def require_free_port(port: int) -> None:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as listener:
        if os.name == "nt":
            listener.setsockopt(socket.SOL_SOCKET, socket.SO_EXCLUSIVEADDRUSE, 1)
        try:
            listener.bind(("127.0.0.1", port))
        except OSError as error:
            raise WorkbenchError(f"PORT_IN_USE_OR_UNAVAILABLE_{port}") from error


def product_path(value: Path) -> Path:
    root = Path(os.path.abspath(value))
    for component in (root, *root.parents):
        try:
            metadata = component.lstat()
        except FileNotFoundError:
            continue
        if stat.S_ISLNK(metadata.st_mode) or getattr(
            metadata, "st_file_attributes", 0
        ) & getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0x400):
            raise WorkbenchError("PRODUCT_ROOT_LINK_OR_REPARSE_NOT_ALLOWED")
    if (
        root == Path(root.anchor)
        or root == PROJECT
        or (root.exists() and not root.is_dir())
    ):
        raise WorkbenchError("PRODUCT_ROOT_MUST_BE_A_DATA_DIRECTORY")
    return root


def child_environments(
    product: Path, runtime: Path, token: str, api_port: int, web_port: int, source=None
):
    source = os.environ if source is None else source
    base = {key: value for key, value in source.items() if key.upper() in ENV_ALLOWLIST}
    base.update(
        {
            "HOME": str(runtime),
            "USERPROFILE": str(runtime),
            "TEMP": str(runtime),
            "TMP": str(runtime),
            "TMPDIR": str(runtime),
            "APPDATA": str(runtime / "appdata"),
            "LOCALAPPDATA": str(runtime / "localappdata"),
            "XDG_CONFIG_HOME": str(runtime / "config"),
            "XDG_CACHE_HOME": str(runtime / "cache"),
            "PYTHONUTF8": "1",
            "PYTHONIOENCODING": "utf-8",
            "PYTHONNOUSERSITE": "1",
            "PYTHONDONTWRITEBYTECODE": "1",
            "NO_COLOR": "1",
        }
    )
    api = {
        **base,
        "VISIONDATA_PRODUCT_ROOT": str(product),
        "VISIONDATA_RESOURCE_ROOT": str(runtime / "resources"),
        "VISIONDATA_SESSION_TOKEN": token,
        "VISIONDATA_SESSION_ACTOR_USER_ID": "usr_local_demo",
        "VISIONDATA_INSECURE_TEST_ACTOR_HEADER_BYPASS": "false",
        "VISIONDATA_AGENTTEAMS_MODE": "off",
        "VISIONDATA_INCIDENT_MODEL_MODE": "off",
        "VISIONDATA_MEMORY_ADMISSION_MODE": "strict_envelope_v1",
        "VISIONDATA_WEB_ORIGINS": f"http://127.0.0.1:{web_port}",
    }
    web = {**base, "VISIONDATA_WEB_API_TARGET": f"http://127.0.0.1:{api_port}"}
    return api, web


def preflight(args) -> Path:
    if not (3, 12) <= sys.version_info[:2] < (3, 14):
        raise WorkbenchError("PYTHON_3_12_OR_3_13_REQUIRED")
    missing = [
        name
        for name in (
            "fastapi",
            "uvicorn",
            "multipart",
            "numpy",
            "PIL",
            "pydantic",
            "yaml",
            "rfc8785",
        )
        if importlib.util.find_spec(name) is None
    ]
    if missing:
        raise WorkbenchError("MISSING_PYTHON_DEPENDENCIES_RUN_UV_SYNC_EXTRA_API_LOCKED")
    if not (PROJECT / "web/node_modules/vite/bin/vite.js").is_file():
        raise WorkbenchError("MISSING_WEB_DEPENDENCIES_RUN_NPM_CI_IN_WEB")
    node = shutil.which("node")
    if not node:
        raise WorkbenchError("NODE_NOT_FOUND_ON_PATH")
    # Only a version query: no app import, server, database, or output directory.
    clean = {
        key: value for key, value in os.environ.items() if key.upper() in ENV_ALLOWLIST
    }
    result = subprocess.run(
        [node, "--version"],
        env=clean,
        capture_output=True,
        timeout=10,
        check=False,
        creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0,
    )
    match = re.fullmatch(rb"v(\d+)\.(\d+)\.(\d+)\s*", result.stdout)
    version = tuple(map(int, match.groups())) if match else (0, 0, 0)
    if result.returncode or not (
        version >= (22, 12, 0) or (20, 19, 0) <= version < (21, 0, 0)
    ):
        raise WorkbenchError("NODE_20_19_OR_22_12_PLUS_REQUIRED")
    product_path(args.product_root)
    require_free_port(args.api_port)
    require_free_port(args.web_port)
    return Path(node)


def vite_configuration(runtime: Path, identity: str) -> str:
    # Existing config calls loadEnv(mode, '.', ''). Child cwd is this fresh
    # directory; envDir:false additionally disables Vite's automatic root .env.
    original = json.dumps((PROJECT / "web/vite.config.ts").as_posix())
    cache = json.dumps((runtime / "vite-cache").as_posix())
    body = json.dumps({"service": "web", "identity": identity})
    return f"""import original from {original};
export default async (environment) => {{
  const config = await original(environment);
  return {{ ...config, envDir: false, cacheDir: {cache},
    server: {{ ...config.server, open: false }},
    plugins: [...config.plugins, {{ name: 'owned-workbench-lifecycle',
      configureServer(server) {{
        server.middlewares.use((request, response, next) => {{
          if (request.url !== {json.dumps(IDENTITY_PATH)}) return next();
          response.setHeader('Content-Type', 'application/json');
          response.setHeader('Cache-Control', 'no-store');
          response.end({json.dumps(body)});
        }});
        process.stdin.once('end', () => {{
          server.close().then(() => process.exit(0)).catch(() => process.exit(1));
        }});
        process.stdin.resume();
      }}
    }}]
  }};
}};
"""


def serve_api(port: int) -> int:
    """Own one actual API app; stdin EOF requests normal lifespan shutdown."""
    import uvicorn

    sys.path.insert(0, str(PROJECT / "src"))
    from visiondata_gate.api import app

    marker = os.environ["VISIONDATA_WORKBENCH_STARTUP_ID"]
    body = json.dumps({"service": "api", "identity": marker}).encode("utf-8")

    async def identified_app(scope, receive, send):
        if scope["type"] == "http" and scope["path"] == IDENTITY_PATH:
            await send(
                {
                    "type": "http.response.start",
                    "status": 200,
                    "headers": [
                        (b"content-type", b"application/json"),
                        (b"cache-control", b"no-store"),
                    ],
                }
            )
            await send({"type": "http.response.body", "body": body})
            return
        await app(scope, receive, send)

    server = uvicorn.Server(
        uvicorn.Config(
            identified_app,
            host="127.0.0.1",
            port=port,
            log_level="critical",
            access_log=False,
            timeout_graceful_shutdown=30,
        )
    )

    def shutdown_on_eof():
        sys.stdin.buffer.read()
        server.should_exit = True

    threading.Thread(target=shutdown_on_eof, daemon=True).start()
    server.run()
    return 0 if server.started else 2


def request_json(port: int, path: str, token: str | None = None):
    # HTTPConnection goes directly to loopback, never through inherited proxies.
    connection = http.client.HTTPConnection("127.0.0.1", port, timeout=2)
    try:
        headers = {"X-VisionData-Session-Token": token} if token else {}
        connection.request("GET", path, headers=headers)
        response = connection.getresponse()
        data = response.read(1024 * 1024 + 1)
        if len(data) > 1024 * 1024:
            raise WorkbenchError("STARTUP_RESPONSE_TOO_LARGE")
        return response.status, json.loads(data)
    finally:
        connection.close()


def wait_identity(
    child, port: int, service: str, identity: str, timeout: float
) -> None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if child.poll() is not None:
            raise WorkbenchError(f"OWNED_{service.upper()}_EXITED_BEFORE_READY")
        try:
            status, data = request_json(port, IDENTITY_PATH)
        except (OSError, http.client.HTTPException):
            time.sleep(0.1)
            continue
        except (ValueError, UnicodeError) as error:
            raise WorkbenchError("STARTUP_IDENTITY_MISMATCH") from error
        if status != 200 or data != {"service": service, "identity": identity}:
            raise WorkbenchError("STARTUP_IDENTITY_MISMATCH")
        if child.poll() is not None:
            raise WorkbenchError("OWNED_SERVICE_EXITED_AFTER_IDENTITY")
        return
    raise WorkbenchError(f"OWNED_{service.upper()}_READINESS_TIMEOUT")


def verify_session(port: int, token: str) -> None:
    status, health = request_json(port, "/v1/health")
    if (
        status != 200
        or not isinstance(health, dict)
        or health.get("service") != "visiondata-gate"
        or health.get("authentication") != "session_token_bound_principal"
    ):
        raise WorkbenchError("SESSION_AUTHENTICATION_NOT_BOUND")
    path = "/v1/projects?workspace_id=wsp_local_demo"
    for supplied in (None, secrets.token_hex(32)):
        if request_json(port, path, supplied)[0] != 401:
            raise WorkbenchError("UNAUTHORIZED_SESSION_NOT_REJECTED")
    status, projects = request_json(port, path, token)
    if status != 200 or not isinstance(projects, list):
        raise WorkbenchError("VALID_SESSION_NOT_ACCEPTED")


def stop_owned_child(child) -> bool:
    if child.poll() is None:
        try:
            child.stdin.close()
        except (BrokenPipeError, OSError, ValueError):
            pass
        try:
            child.wait(timeout=40)
        except subprocess.TimeoutExpired:
            return False
    return True


def start_children(args, node: Path, runtime: Path, token: str):
    api_identity, web_identity = secrets.token_hex(24), secrets.token_hex(24)
    api_env, web_env = child_environments(
        args.product_root, runtime, token, args.api_port, args.web_port
    )
    api_env["VISIONDATA_WORKBENCH_STARTUP_ID"] = api_identity
    config = runtime / "vite.workbench.config.mjs"
    config.write_text(vite_configuration(runtime, web_identity), encoding="utf-8")
    commands = [
        (
            [
                sys.executable,
                str(Path(__file__).resolve()),
                "--api-child",
                "--api-port",
                str(args.api_port),
                "--web-port",
                str(args.web_port),
            ],
            api_env,
            args.api_port,
            "api",
            api_identity,
        ),
        (
            [
                str(node),
                str(PROJECT / "web/node_modules/vite/bin/vite.js"),
                str(PROJECT / "web"),
                "--config",
                str(config),
                "--host",
                "127.0.0.1",
                "--port",
                str(args.web_port),
                "--strictPort",
                "--clearScreen",
                "false",
                "--logLevel",
                "silent",
            ],
            web_env,
            args.web_port,
            "web",
            web_identity,
        ),
    ]
    children = []
    try:
        for command, environment, port, service, identity in commands:
            child = subprocess.Popen(
                command,
                cwd=runtime,
                env=environment,
                stdin=subprocess.PIPE,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0,
                start_new_session=os.name != "nt",
            )
            children.append(child)
            wait_identity(child, port, service, identity, args.startup_timeout)
            # A listener must prove this launch's identity before it sees a token.
            verify_session(port, token)
        return children
    except BaseException:
        clean = [stop_owned_child(child) for child in reversed(children)]
        if all(clean):
            print("OWNED_STARTUP_SERVICES_STOPPED; product data were not deleted.")
        else:
            print(
                "OWNED_CHILD_SHUTDOWN_TIMEOUT: no process was forcibly killed.",
                file=sys.stderr,
            )
        raise


def open_browser(url: str) -> bool:
    """Suppress Python and inherited browser-helper output, including failures."""
    saved = {}
    with open(os.devnull, "w", encoding="utf-8") as silent:
        try:
            for descriptor in (1, 2):
                saved[descriptor] = os.dup(descriptor)
                os.dup2(silent.fileno(), descriptor)
            with redirect_stdout(silent), redirect_stderr(silent):
                return bool(webbrowser.open(url))
        except Exception:
            return False
        finally:
            for descriptor, original in saved.items():
                os.dup2(original, descriptor)
                os.close(original)


def run_workbench(args, node: Path) -> int:
    args.product_root = product_path(args.product_root)
    args.product_root.mkdir(parents=True, exist_ok=True)
    runtime = Path(tempfile.mkdtemp(prefix=".workbench-", dir=args.product_root))
    for name in ("appdata", "localappdata", "config", "cache", "resources"):
        (runtime / name).mkdir()
    token = secrets.token_urlsafe(32)
    children = []
    result = 0
    try:
        children = start_children(args, node, runtime, token)
        base = f"http://127.0.0.1:{args.web_port}{args.start_path}"
        print("WORKBENCH_READY: " + base)
        print(
            "Session verified: valid accepted; missing/invalid rejected on API and web proxy."
        )
        print(
            "Local-only profile: dotenv ignored; model/AgentTeams configuration disabled."
        )
        print(
            "Product data and runtime caches retained under: " + str(args.product_root)
        )
        if args.no_browser:
            print(
                "Browser launch disabled; no session capability was printed. Restart without --no-browser to open an authenticated session."
            )
        else:
            if not open_browser(base + "#visiondata_session=" + token):
                print(
                    "BROWSER_NOT_OPENED: restart with a configured default browser; no session capability was printed."
                )
        print("Press Ctrl+C to gracefully stop only this launcher's services.")
        deadline = time.monotonic() + args.smoke_seconds if args.smoke_seconds else None
        while deadline is None or time.monotonic() < deadline:
            if any(child.poll() is not None for child in children):
                raise WorkbenchError("OWNED_SERVICE_EXITED_UNEXPECTEDLY")
            time.sleep(0.1)
    except KeyboardInterrupt:
        print("Stopping owned services...")
    finally:
        clean = [stop_owned_child(child) for child in reversed(children)]
        if children and all(clean):
            print(
                "OWNED_SERVICES_STOPPED; product data and runtime caches were not deleted."
            )
        elif not all(clean):
            print(
                "OWNED_CHILD_SHUTDOWN_TIMEOUT: no process was forcibly killed.",
                file=sys.stderr,
            )
            result = 2
    return result


def parse_args(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--api-port", type=int, default=8787)
    parser.add_argument("--web-port", type=int, default=5173)
    parser.add_argument(
        "--start-path",
        default="/workspace",
        help="Plain internal path only; no query or fragment",
    )
    parser.add_argument(
        "--product-root",
        type=Path,
        default=PROJECT / "output/cross-platform-product",
        help="Retained local product data; default: output/cross-platform-product",
    )
    parser.add_argument(
        "--no-browser",
        action="store_true",
        help="Do not open or print an authenticated session URL",
    )
    parser.add_argument(
        "--check",
        action="store_true",
        help="Read-only dependency/port/path preflight; no app import or output directory",
    )
    parser.add_argument(
        "--smoke-seconds",
        type=float,
        default=0,
        help="Stop after 0.01..60 seconds once ready; 0 means wait for Ctrl+C",
    )
    parser.add_argument(
        "--startup-timeout",
        type=float,
        default=45,
        help="Per-service readiness budget: 1..120 seconds",
    )
    parser.add_argument("--api-child", action="store_true", help=argparse.SUPPRESS)
    args = parser.parse_args(argv)
    if (
        not (1 <= args.api_port <= 65535 and 1 <= args.web_port <= 65535)
        or args.api_port == args.web_port
    ):
        parser.error("API and web ports must be distinct values in 1..65535")
    if not 1 <= args.startup_timeout <= 120:
        parser.error("--startup-timeout must be 1..120 seconds")
    if args.smoke_seconds != 0 and not 0.01 <= args.smoke_seconds <= 60:
        parser.error("--smoke-seconds must be 0 (interactive) or 0.01..60")
    validate_start_path(args.start_path)
    return args


def main(argv=None) -> int:
    try:
        args = parse_args(argv)
        if args.api_child:
            if len(
                os.environ.get("VISIONDATA_SESSION_TOKEN", "")
            ) < 32 or not os.environ.get("VISIONDATA_WORKBENCH_STARTUP_ID"):
                raise WorkbenchError("PRIVATE_CHILD_REQUIRES_PARENT_ENVIRONMENT")
            return serve_api(args.api_port)
        node = preflight(args)
        if args.check:
            print(
                "PREFLIGHT_PASS: dependencies, loopback ports and product path checked; no services or product state created."
            )
            return 0
        return run_workbench(args, node)
    except (
        WorkbenchError,
        OSError,
        ValueError,
        http.client.HTTPException,
        subprocess.SubprocessError,
    ) as error:
        code = str(error) if isinstance(error, WorkbenchError) else type(error).__name__
        print("WORKBENCH_REFUSED: " + code, file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
