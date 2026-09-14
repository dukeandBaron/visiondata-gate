"""Actual JRE + Spring JAR + frozen FastAPI learning workflow, no installation.

Only explicitly supplied package artifacts execute. The existing HTTP workflow
is a test client, never a source-server fallback. All synthetic state is new.
"""

from __future__ import annotations

import argparse
import hashlib
import hmac
import importlib.util
import json
import os
from pathlib import Path
import secrets
import subprocess
import sys
import time

import httpx


def _sibling(name):
    path = Path(__file__).resolve().with_name(name + ".py")
    spec = importlib.util.spec_from_file_location("packaged_" + name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


build = _sibling("build_learning_installer")
demo = _sibling("run_learning_demo")


class SmokeError(ValueError):
    """A safe code, not a response body, token or private filesystem path."""


def require(condition, code):
    if not condition:
        raise SmokeError(code)


def new_smoke_root(value: Path) -> Path:
    try:
        return demo.new_output_root(value)
    except demo.DemoError as error:
        raise SmokeError(str(error)) from error


def runtime_environment(root: Path, token: str, startup_secret: str, original=None):
    environment = demo.child_environment(root, token, original)
    # The frozen entrypoint alone must choose its _MEIPASS resource directory.
    environment.pop("VISIONDATA_RESOURCE_ROOT", None)
    environment.update(
        {
            "VISIONDATA_DESKTOP_SESSION_TOKEN": token,
            "VISIONDATA_DESKTOP_STARTUP_SECRET": startup_secret,
            "VISIONDATA_DESKTOP_CONFIG_FILE": str(root / "absent-isolated-config.env"),
            "VISIONDATA_DESKTOP_LOG_FILE": str(root / "fastapi.log"),
            "VISIONDATA_PRODUCT_MODEL_KEYS_ENABLED": "false",
        }
    )
    return environment


def runtime_commands(
    artifact_root, backend_root, java_runtime, gateway_jar, backend_port
):
    root = build.safe_root(artifact_root)
    backend = build.safe_root(backend_root)
    java_root = build.safe_root(java_runtime)
    jar = Path(gateway_jar)
    build.no_links(jar)
    jar = jar.resolve(strict=True)
    if not all(path.is_relative_to(root) for path in (backend, java_root, jar)):
        raise SmokeError("ARTIFACT_ROOT_SCOPE")
    require(jar.is_file() and jar.suffix == ".jar", "GATEWAY_JAR_REQUIRED")
    executable = build.safe_file(backend, "visiondata-gate-backend.exe")
    java = build.safe_file(java_root, "bin/java.exe")
    return {
        "backend": [str(executable), "--port", str(backend_port)],
        "gateway": [
            str(java),
            "-Dfile.encoding=UTF-8",
            "-XX:ActiveProcessorCount=2",
            "-Xms32m",
            "-Xmx256m",
            "-jar",
            str(jar),
        ],
    }


def require_gateway_response(response):
    if response.request.url.path.startswith("/v1/"):
        require(
            response.headers.get("X-VisionData-Gateway") == "spring-webflux",
            "GATEWAY_HEADER_REQUIRED",
        )


def stop_owned_process(process):
    if process is None:
        return None
    if process.poll() is None:
        process.terminate()
        try:
            process.wait(timeout=10)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait(timeout=10)
    return process.returncode


def _wait_json(process, url, deadline):
    with httpx.Client(trust_env=False, follow_redirects=False) as client:
        while time.monotonic() < deadline:
            require(process.poll() is None, "OWNED_RUNTIME_EXITED_BEFORE_READY")
            try:
                response = client.get(url, timeout=1.0)
                if response.status_code == 200:
                    return response.json()
            except (httpx.ConnectError, httpx.TimeoutException):
                pass
            time.sleep(0.15)
    raise SmokeError("OWNED_RUNTIME_READINESS_TIMEOUT")


def _proof(base_url, secret, *, gateway=False):
    challenge = secrets.token_hex(32)
    expected = hmac.new(secret.encode(), challenge.encode(), hashlib.sha256).hexdigest()
    with httpx.Client(
        base_url=base_url, trust_env=False, follow_redirects=False
    ) as client:
        response = client.get(
            "/v1/desktop/readiness", params={"challenge": challenge}, timeout=5.0
        )
    require(
        response.status_code == 200
        and hmac.compare_digest(response.text.strip(), expected),
        "PACKAGED_BACKEND_HMAC_IDENTITY_FAILED",
    )
    if gateway:
        require_gateway_response(response)


def artifact_inputs(backend_root, java_runtime, gateway_jar):
    backend_root = build.safe_root(backend_root)
    java_runtime = build.safe_root(java_runtime)
    return {
        "backend_executable": build.hash_file(
            backend_root / "visiondata-gate-backend.exe",
            "backend/visiondata-gate-backend.exe",
        ),
        "backend_resources": build.inventory_tree(backend_root),
        "gateway_jar": build.hash_file(
            Path(gateway_jar), "gateway/visiondata-gate-gateway.jar"
        ),
        "java_runtime": build.inventory_tree(java_runtime),
    }


def _bind_expected(inputs, path):
    if path is None:
        return None
    manifest = build.read_json(path)
    expected = manifest["artifacts"]
    require(
        inputs["backend_resources"]["content_sha256"]
        == expected["backend"]["content_sha256"],
        "BUILD_BACKEND_DIGEST_MISMATCH",
    )
    require(
        inputs["gateway_jar"]["sha256"] == expected["gateway_jar"]["sha256"],
        "BUILD_GATEWAY_DIGEST_MISMATCH",
    )
    require(
        inputs["java_runtime"]["content_sha256"]
        == expected["java_runtime"]["content_sha256"],
        "BUILD_JRE_DIGEST_MISMATCH",
    )
    return build.hash_file(path, "BUILD_MANIFEST.json")["sha256"]


def run_smoke(
    artifact_root,
    backend_root,
    java_runtime,
    gateway_jar,
    output_root,
    *,
    timeout_seconds=300,
    build_manifest=None,
):
    artifact_root = build.safe_root(artifact_root)
    output_path = Path(os.path.abspath(output_root))
    require(
        not output_path.is_relative_to(artifact_root),
        "SMOKE_STATE_MUST_BE_OUTSIDE_PACKAGE_RESOURCES",
    )
    root = new_smoke_root(output_path)
    token, startup_secret = secrets.token_hex(32), secrets.token_hex(32)
    backend_port = demo.free_loopback_port()
    gateway_port = demo.free_loopback_port()
    while gateway_port == backend_port:
        gateway_port = demo.free_loopback_port()
    commands = runtime_commands(
        artifact_root, backend_root, java_runtime, gateway_jar, backend_port
    )
    backend_base, gateway_base = (
        f"http://127.0.0.1:{backend_port}",
        f"http://127.0.0.1:{gateway_port}",
    )
    backend_env = runtime_environment(root, token, startup_secret)
    gateway_env = demo.child_environment(root, "unused-no-gateway-authority")
    for key in tuple(gateway_env):
        if key.startswith("VISIONDATA_"):
            del gateway_env[key]
    gateway_env.update(
        VISIONDATA_GATEWAY_PORT=str(gateway_port),
        VISIONDATA_FASTAPI_BASE_URL=backend_base,
    )
    result = {
        "schema_version": "visiondata-gate.packaged-learning-smoke.v1",
        "scope": "PACKAGED_SPRING_FASTAPI_SYNTHETIC_REFERENCE_LEARNING",
        "status": "STARTING",
        "source_fallback": False,
        "runtime_execution": "SPECIFIED_PACKAGED_EXE_JRE_JAR_ONLY",
        "workflow_transport": "SPRING_WEBFLUX_GATEWAY_HTTP_ONLY",
        "human_review_actor_kind": demo.TEST_ACTOR,
        "real_human_acceptance": False,
        "raw_images_transmitted": False,
        "raw_image_boundary": "Generated images use owned loopback only; no external model or remote transfer",
        "remote_execution_verified": False,
        "remote_job_submitted": False,
        "production_release_allowed": False,
        "machine_write_permitted": False,
        "industrial_performance_verified": False,
        "native_gui_validation": "NOT_RUN",
        "installer_install_validation": "NOT_RUN",
        "clean_machine_validation": "NOT_RUN",
        "gate_tasks": [],
        "rounds": [],
        "training_configuration": demo.TRAINING,
    }
    backend = gateway = flow = None
    backend_proven = gateway_proven = False
    inputs = None
    started = time.monotonic()
    deadline = started + timeout_seconds
    try:
        inputs = artifact_inputs(backend_root, java_runtime, gateway_jar)
        result["artifact_inputs"] = inputs
        result["bound_build_manifest_sha256"] = _bind_expected(inputs, build_manifest)
        result["module_archive_check"] = build.verify_archive(
            Path(sys.executable), Path(commands["backend"][0]), root, backend_env
        )
        flags = subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0
        backend = subprocess.Popen(
            commands["backend"],
            cwd=root,
            env=backend_env,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            creationflags=flags,
        )
        health = _wait_json(
            backend, backend_base + "/v1/health", min(deadline, time.monotonic() + 45)
        )
        require(
            health.get("authentication") == "session_token_bound_principal",
            "PACKAGED_SESSION_NOT_BOUND",
        )
        _proof(backend_base, startup_secret)
        backend_proven = True
        gateway = subprocess.Popen(
            commands["gateway"],
            cwd=root,
            env=gateway_env,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            creationflags=flags,
        )
        health = _wait_json(
            gateway,
            gateway_base + "/gateway/v1/health",
            min(deadline, time.monotonic() + 60),
        )
        require(
            health.get("status") == "READY"
            and health.get("gateway") == "SPRING_BOOT_WEBFLUX"
            and health.get("production_release_allowed") is False,
            "GATEWAY_HEALTH_NOT_READY",
        )
        _proof(gateway_base, startup_secret, gateway=True)
        gateway_proven = True
        result["proxied_hmac_readiness_verified"] = True
        with httpx.Client(
            base_url=gateway_base,
            headers={
                "X-VisionData-Desktop-Token": token,
                "X-Actor-User-Id": demo.ACTOR,
            },
            trust_env=False,
            follow_redirects=False,
            event_hooks={"response": [require_gateway_response]},
        ) as client:
            denied = client.get(
                "/v1/projects",
                headers={"X-VisionData-Desktop-Token": "incorrect-token"},
                timeout=5,
            )
            require(denied.status_code == 401, "PACKAGED_INVALID_TOKEN_NOT_REJECTED")
            flow = demo.HttpWorkflow(client, deadline)
            flow.request("GET", "/v1/projects", params={"workspace_id": demo.WORKSPACE})
            result["session_authentication"] = (
                "VALID_TOKEN_ACCEPTED_INVALID_TOKEN_REJECTED_THROUGH_GATEWAY"
            )
            demo.execute_workflow(flow, result, "pkg-" + secrets.token_hex(12))
    except (
        SmokeError,
        build.BuildError,
        demo.DemoError,
        httpx.HTTPError,
        OSError,
        ValueError,
        KeyError,
        subprocess.TimeoutExpired,
    ) as error:
        result["status"] = "FAILED"
        result["failure_stage"] = (
            flow.current_stage if flow else "PACKAGED_RUNTIME_STARTUP"
        )
        result["failure_code"] = (
            str(error)
            if isinstance(error, (SmokeError, build.BuildError, demo.DemoError))
            else type(error).__name__
        )
    finally:
        shutdown_status = None
        if backend is not None and backend.poll() is None and backend_proven:
            try:
                with httpx.Client(
                    base_url=gateway_base if gateway_proven else backend_base,
                    trust_env=False,
                    follow_redirects=False,
                ) as client:
                    response = client.post(
                        "/v1/desktop/shutdown",
                        headers={"X-VisionData-Desktop-Token": token},
                        timeout=5,
                    )
                    shutdown_status = response.status_code
                if shutdown_status == 202:
                    backend.wait(timeout=20)
            except (httpx.HTTPError, subprocess.TimeoutExpired):
                pass
        forced_backend = backend is not None and backend.poll() is None
        backend_exit = stop_owned_process(backend)
        gateway_exit = stop_owned_process(gateway)
        result["process_cleanup"] = {
            "backend_shutdown_http_status": shutdown_status,
            "backend_exit_code": backend_exit,
            "backend_graceful_shutdown": backend_exit == 0 and not forced_backend,
            "gateway_exit_code": gateway_exit,
            "gateway_stop_method": "TERMINATE_ONLY_OWNED_JAVA_PROCESS_NO_PUBLIC_SHUTDOWN_ENDPOINT",
            "all_owned_processes_exited": (
                backend is None or backend.poll() is not None
            )
            and (gateway is None or gateway.poll() is not None),
        }
        result["elapsed_seconds"] = time.monotonic() - started
        result["http_request_count"] = flow.http_request_count if flow else 0
    try:
        stable = (
            inputs is not None
            and artifact_inputs(backend_root, java_runtime, gateway_jar) == inputs
        )
    except (OSError, ValueError):
        stable = False
    result["runtime_artifact_bytes_unchanged"] = stable
    if not stable or result["process_cleanup"]["backend_graceful_shutdown"] is not True:
        result["status"] = "FAILED"
        result.setdefault(
            "failure_code", "PACKAGE_DRIFT_OR_UNGRACEFUL_BACKEND_SHUTDOWN"
        )
    if result["status"] == "COMPLETED_REFERENCE_WORKFLOW":
        result["status"] = "PASS_PACKAGED_LEARNING"
    serialized = build.canonical(result)
    require(
        token.encode() not in serialized and startup_secret.encode() not in serialized,
        "SECRET_IN_SMOKE_RECEIPT",
    )
    output = root / "PACKAGED_LEARNING_SMOKE.json"
    build.write_json_new(output, result)
    print(
        json.dumps(
            {
                "status": result["status"],
                "source_fallback": False,
                "round_count": len(result["rounds"]),
                "receipt_sha256": build.hash_file(output, output.name)["sha256"],
                "failure_stage": result.get("failure_stage"),
                "failure_code": result.get("failure_code"),
            },
            sort_keys=True,
        )
    )
    return 0 if result["status"] == "PASS_PACKAGED_LEARNING" else 2


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    for name in (
        "artifact-root",
        "backend-root",
        "java-runtime",
        "gateway-jar",
        "output-root",
    ):
        parser.add_argument("--" + name, type=Path, required=True)
    parser.add_argument("--build-manifest", type=Path)
    parser.add_argument("--timeout-seconds", type=int, default=300)
    args = parser.parse_args(argv)
    if not 60 <= args.timeout_seconds <= 600:
        parser.error("timeout must be 60..600 seconds")
    try:
        return run_smoke(
            args.artifact_root,
            args.backend_root,
            args.java_runtime,
            args.gateway_jar,
            args.output_root,
            timeout_seconds=args.timeout_seconds,
            build_manifest=args.build_manifest,
        )
    except (ValueError, OSError) as error:
        print(
            json.dumps(
                {
                    "status": "HOLD",
                    "error_code": str(error)
                    if isinstance(error, (SmokeError, build.BuildError))
                    else type(error).__name__,
                }
            ),
            file=sys.stderr,
        )
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
