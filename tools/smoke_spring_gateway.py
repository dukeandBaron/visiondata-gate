from __future__ import annotations

import argparse
import hashlib
import hmac
import json
import os
import socket
import subprocess
import sys
import tempfile
import time
import uuid
from pathlib import Path

import httpx


def _free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as probe:
        probe.bind(("127.0.0.1", 0))
        return int(probe.getsockname()[1])


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _prepare_product(product_root: Path) -> None:
    preparer = Path(__file__).resolve().with_name("prepare_semifinal_demo.py")
    completed = subprocess.run(
        [sys.executable, str(preparer), "--product-root", str(product_root)],
        stdin=subprocess.DEVNULL,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        encoding="utf-8",
        timeout=120,
        check=False,
    )
    if completed.returncode != 0:
        detail = completed.stderr.strip() or completed.stdout.strip()
        raise RuntimeError(f"product preparation failed: {detail[-1000:]}")


def _wait_for_json_health(
    process: subprocess.Popen[bytes],
    url: str,
    *,
    timeout: float,
) -> dict[str, object]:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if process.poll() is not None:
            raise RuntimeError(f"service exited during startup: {process.returncode}")
        try:
            response = httpx.get(url, timeout=0.75)
            if response.status_code == 200:
                payload = response.json()
                if isinstance(payload, dict):
                    return payload
        except (httpx.HTTPError, ValueError):
            pass
        time.sleep(0.2)
    raise TimeoutError(f"service did not become healthy: {url}")


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Smoke the packaged Spring Boot and FastAPI local stack"
    )
    parser.add_argument("--backend-executable", required=True, type=Path)
    parser.add_argument("--java-executable", required=True, type=Path)
    parser.add_argument("--gateway-jar", required=True, type=Path)
    parser.add_argument("--output", type=Path)
    return parser


def _stop_process(process: subprocess.Popen[bytes] | None) -> int | None:
    if process is None:
        return None
    if process.poll() is None:
        process.kill()
        process.wait(timeout=10)
    return process.returncode


def main() -> int:
    args = _parser().parse_args()
    backend_executable = args.backend_executable.expanduser().resolve(strict=True)
    java_executable = args.java_executable.expanduser().resolve(strict=True)
    gateway_jar = args.gateway_jar.expanduser().resolve(strict=True)
    creation_flags = subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0

    backend: subprocess.Popen[bytes] | None = None
    gateway: subprocess.Popen[bytes] | None = None
    receipt: dict[str, object] | None = None
    with tempfile.TemporaryDirectory(prefix="visiondata-gate-spring-smoke-") as temp:
        root = Path(temp)
        product_root = root / "product"
        _prepare_product(product_root)
        fastapi_port = _free_port()
        gateway_port = _free_port()
        if fastapi_port == gateway_port:
            gateway_port = _free_port()
        token = uuid.uuid4().hex + uuid.uuid4().hex
        startup_secret = uuid.uuid4().hex + uuid.uuid4().hex

        backend_environment = os.environ.copy()
        backend_environment.pop("VISIONDATA_RESOURCE_ROOT", None)
        backend_environment.update(
            {
                "VISIONDATA_DESKTOP_SESSION_TOKEN": token,
                "VISIONDATA_DESKTOP_STARTUP_SECRET": startup_secret,
                "VISIONDATA_PRODUCT_ROOT": str(product_root),
                "VISIONDATA_DESKTOP_CONFIG_FILE": str(root / ".env.local"),
                "VISIONDATA_DESKTOP_LOG_FILE": str(root / "fastapi.log"),
                "VISIONDATA_WEB_ORIGINS": "http://tauri.localhost",
            }
        )
        gateway_environment = os.environ.copy()
        gateway_environment.update(
            {
                "VISIONDATA_GATEWAY_PORT": str(gateway_port),
                "VISIONDATA_FASTAPI_BASE_URL": f"http://127.0.0.1:{fastapi_port}",
            }
        )

        try:
            backend = subprocess.Popen(
                [str(backend_executable), "--port", str(fastapi_port)],
                env=backend_environment,
                stdin=subprocess.DEVNULL,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                creationflags=creation_flags,
            )
            _wait_for_json_health(
                backend,
                f"http://127.0.0.1:{fastapi_port}/v1/health",
                timeout=30,
            )

            gateway = subprocess.Popen(
                [str(java_executable), "-jar", str(gateway_jar)],
                env=gateway_environment,
                stdin=subprocess.DEVNULL,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                creationflags=creation_flags,
            )
            gateway_health = _wait_for_json_health(
                gateway,
                f"http://127.0.0.1:{gateway_port}/gateway/v1/health",
                timeout=40,
            )
            if gateway_health.get("status") != "READY":
                raise RuntimeError("Spring gateway did not verify its FastAPI upstream")
            if gateway_health.get("production_release_allowed") is not False:
                raise RuntimeError("Spring gateway widened production authority")
            if gateway_health.get("machine_write_permitted") is not False:
                raise RuntimeError("Spring gateway widened machine authority")

            challenge = uuid.uuid4().hex + uuid.uuid4().hex
            expected_proof = hmac.new(
                startup_secret.encode("utf-8"),
                challenge.encode("utf-8"),
                hashlib.sha256,
            ).hexdigest()
            readiness = httpx.get(
                f"http://127.0.0.1:{gateway_port}/v1/desktop/readiness",
                params={"challenge": challenge},
                timeout=5,
            )
            readiness.raise_for_status()
            if readiness.text.strip() != expected_proof:
                raise RuntimeError("proxied FastAPI HMAC readiness proof drifted")

            denied = httpx.get(
                f"http://127.0.0.1:{gateway_port}/v1/workspaces",
                headers={"X-Actor-User-Id": "usr_local_demo"},
                timeout=5,
            )
            if denied.status_code != 401:
                raise RuntimeError(
                    f"desktop session guard returned {denied.status_code}"
                )

            shutdown = httpx.post(
                f"http://127.0.0.1:{gateway_port}/v1/desktop/shutdown",
                headers={"X-VisionData-Desktop-Token": token},
                timeout=5,
            )
            if shutdown.status_code != 202:
                raise RuntimeError(f"FastAPI shutdown returned {shutdown.status_code}")
            backend.wait(timeout=10)

            receipt = {
                "schema_version": "visiondata-gate.spring-fastapi-smoke.v1",
                "status": "PASS",
                "backend_executable_sha256": _sha256(backend_executable),
                "gateway_jar_sha256": _sha256(gateway_jar),
                "runtime_java_sha256": _sha256(java_executable),
                "gateway_health_status": gateway_health["status"],
                "fastapi_health_status": gateway_health["fastapi"],
                "hmac_readiness_verified": True,
                "unauthorized_request_status": denied.status_code,
                "fastapi_graceful_exit_code": backend.returncode,
                "bind_scope": "LOOPBACK_ONLY",
                "production_release_allowed": False,
                "machine_write_permitted": False,
                "installer_release_status": "NOT_CLAIMED",
            }
        finally:
            _stop_process(gateway)
            _stop_process(backend)

    if receipt is None:
        raise RuntimeError("joint smoke did not produce a receipt")
    serialized = json.dumps(receipt, ensure_ascii=False, indent=2) + "\n"
    if args.output is not None:
        output = args.output.expanduser().resolve()
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(serialized, encoding="utf-8", newline="\n")
    print(serialized, end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
