"""Install and exercise the governed normality Model Pack through Spring HTTP.

The tool deliberately keeps the trained model, public dataset and external
Python runtime outside the installer.  It installs one exact NSIS artifact,
starts only the installed FastAPI executable and bundled JRE/Spring JAR, builds
fresh isolated product state, and sends every business operation through the
Spring gateway.  It never grants a Gate or production decision.
"""

from __future__ import annotations

import argparse
import hashlib
import hmac
import importlib.util
import json
import math
import os
from pathlib import Path
import re
import secrets
import socket
import sqlite3
import subprocess
import sys
import time
from typing import Any

import httpx
import rfc8785


PROJECT_ROOT = Path(__file__).resolve().parents[1]
EXPECTED_INFERENCE_BACKEND_SHA256 = (
    "516b31e2dd7a8e8fac8a25d7aaa234e1ef70c4624d907d7f75b6793300eef549"
)
_SHA256 = re.compile(r"^[0-9a-f]{64}$")
_WINDOWS_ABSOLUTE = re.compile(r"(?i)^(?:[a-z]:[\\/]|\\\\)")


class SmokeError(ValueError):
    """A stable failure code that never includes a secret or private path."""


def require(condition: bool, code: str) -> None:
    if not condition:
        raise SmokeError(code)


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _sealed(body: dict[str, Any]) -> dict[str, Any]:
    stable = {key: value for key, value in body.items() if key != "receipt_sha256"}
    return stable | {"receipt_sha256": hashlib.sha256(rfc8785.dumps(stable)).hexdigest()}


def _walk_strings(value: Any):
    if isinstance(value, str):
        yield value
    elif isinstance(value, dict):
        for key, item in value.items():
            yield from _walk_strings(key)
            yield from _walk_strings(item)
    elif isinstance(value, (list, tuple)):
        for item in value:
            yield from _walk_strings(item)


def write_public_receipt_new(
    output: Path,
    body: dict[str, Any],
    *,
    forbidden_values: tuple[str, ...] = (),
) -> dict[str, Any]:
    """Write a new JCS receipt after rejecting secrets and absolute paths."""

    output = Path(output)
    require(not output.exists(), "FRESH_RECEIPT_PATH_REQUIRED")
    receipt = _sealed(body)
    for value in _walk_strings(receipt):
        require(not _WINDOWS_ABSOLUTE.match(value), "ABSOLUTE_PATH_IN_RECEIPT")
        require(not value.startswith("file://"), "ABSOLUTE_PATH_IN_RECEIPT")
    serialized = rfc8785.dumps(receipt) + b"\n"
    for forbidden in forbidden_values:
        if forbidden:
            require(forbidden.encode("utf-8") not in serialized, "SECRET_IN_RECEIPT")
    output.parent.mkdir(parents=True, exist_ok=True)
    with output.open("xb") as stream:
        stream.write(serialized)
    return receipt


def installer_uninstall_helpers() -> dict[str, Any]:
    """Load the single authoritative NSIS convergence implementation."""

    path = Path(__file__).resolve().with_name("smoke_windows_installer.py")
    spec = importlib.util.spec_from_file_location("windows_installer_smoke_shared", path)
    require(spec is not None and spec.loader is not None, "INSTALLER_HELPERS_UNAVAILABLE")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return {
        "find_uninstaller": module._find_uninstaller,
        "wait_for_uninstall_completion": module._wait_for_uninstall_completion,
    }


def _safe_installed_file(root: Path, relative: str) -> Path:
    candidate = root / Path(relative)
    require(candidate.is_file(), "INSTALLED_RUNTIME_RESOURCE_MISSING")
    require(not candidate.is_symlink(), "INSTALLED_RUNTIME_RESOURCE_LINK_FORBIDDEN")
    resolved_root = root.resolve(strict=True)
    resolved = candidate.resolve(strict=True)
    require(resolved.is_relative_to(resolved_root), "INSTALLED_RUNTIME_RESOURCE_SCOPE")
    return candidate


def installed_runtime_resources(install_root: Path) -> dict[str, Path]:
    """Resolve only the exact Tauri resource layout from one install root."""

    root = Path(install_root)
    require(root.is_dir() and not root.is_symlink(), "INSTALLED_ROOT_REQUIRED")
    if hasattr(root, "is_junction"):
        require(not root.is_junction(), "INSTALLED_ROOT_LINK_FORBIDDEN")
    return {
        "backend": _safe_installed_file(
            root, "backend/visiondata-gate-backend.exe"
        ),
        "java": _safe_installed_file(root, "gateway/runtime/bin/java.exe"),
        "gateway_jar": _safe_installed_file(
            root, "gateway/visiondata-gate-gateway.jar"
        ),
    }


def _require_gateway(response: httpx.Response) -> None:
    require(
        response.headers.get("X-VisionData-Gateway") == "spring-webflux",
        "GATEWAY_HEADER_REQUIRED",
    )


def governed_payload(
    response: httpx.Response,
    *,
    expected_status: int,
) -> dict[str, Any]:
    """Validate transport, status, JCS body receipt, ETag and digest header."""

    _require_gateway(response)
    if response.status_code != expected_status:
        public_code = "unknown"
        try:
            error_body = response.json()
            candidate = (error_body.get("error") or {}).get("code")
            if isinstance(candidate, str) and re.fullmatch(r"[a-z0-9_]{1,80}", candidate):
                public_code = candidate
        except (json.JSONDecodeError, UnicodeDecodeError, AttributeError):
            pass
        raise SmokeError(
            f"GOVERNED_HTTP_STATUS_{response.status_code}_{public_code}"
        )
    try:
        payload = response.json()
    except (json.JSONDecodeError, UnicodeDecodeError) as error:
        raise SmokeError("GOVERNED_JSON_REQUIRED") from error
    require(isinstance(payload, dict), "GOVERNED_OBJECT_REQUIRED")
    digest = payload.get("receipt_sha256")
    require(isinstance(digest, str) and _SHA256.fullmatch(digest), "JCS_RECEIPT_INVALID")
    stable = {key: value for key, value in payload.items() if key != "receipt_sha256"}
    actual = hashlib.sha256(rfc8785.dumps(stable)).hexdigest()
    require(hmac.compare_digest(digest, actual), "JCS_RECEIPT_INVALID")
    require(
        response.headers.get("X-Content-SHA256") == digest,
        "JCS_CONTENT_HEADER_MISMATCH",
    )
    require(response.headers.get("ETag") == f'"{digest}"', "JCS_ETAG_MISMATCH")
    return payload


def _sha_identity(value: Any) -> bool:
    return isinstance(value, str) and _SHA256.fullmatch(value) is not None


def validate_inference(
    inference: dict[str, Any], expected: dict[str, str]
) -> None:
    """Bind an inference to all governed identities and threshold semantics."""

    require(
        inference.get("status") == "COMPLETED_LOCAL_SANDBOX_INFERENCE",
        "INFERENCE_NOT_COMPLETED",
    )
    for key, digest in expected.items():
        require(_sha_identity(digest), "EXPECTED_IDENTITY_INVALID")
        require(inference.get(key) == digest, "INFERENCE_IDENTITY_MISMATCH")
    score = inference.get("image_score")
    threshold = inference.get("image_threshold")
    require(
        type(score) in {int, float}
        and type(threshold) in {int, float}
        and math.isfinite(score)
        and math.isfinite(threshold),
        "INFERENCE_SCORE_INVALID",
    )
    predicted = inference.get("predicted_anomaly")
    require(type(predicted) is bool, "INFERENCE_PREDICTION_INVALID")
    require(predicted is (score >= threshold), "PREDICTION_SEMANTIC_MISMATCH")
    require(
        inference.get("production_release_allowed") is False,
        "PRODUCTION_AUTHORITY_WIDENED",
    )
    require(
        inference.get("machine_write_permitted") is False,
        "MACHINE_AUTHORITY_WIDENED",
    )
    require(
        inference.get("decision_scope")
        == "MODEL_SIGNAL_ONLY_NOT_GATE_OR_PRODUCTION_DECISION"
        and inference.get("gate_decision") == "NOT_ISSUED",
        "INFERENCE_DECISION_SCOPE_WIDENED",
    )
    heatmap = inference.get("heatmap")
    require(
        isinstance(heatmap, dict)
        and _sha_identity(heatmap.get("sha256"))
        and type(heatmap.get("bytes")) is int
        and heatmap["bytes"] > 0
        and heatmap.get("width") == 64
        and heatmap.get("height") == 64
        and heatmap.get("format") == "png",
        "HEATMAP_CONTRACT_INVALID",
    )


def validate_runtime_probe(runtime: dict[str, Any], executable_sha256: str) -> str:
    """Keep executable bytes distinct from the broader environment fingerprint."""

    probe = runtime.get("probe")
    runtime_sha256 = runtime.get("runtime_sha256")
    require(
        runtime.get("status") == "PROBED"
        and isinstance(probe, dict)
        and runtime.get("executable_sha256") == executable_sha256
        and probe.get("executable_sha256") == executable_sha256
        and _sha_identity(runtime_sha256)
        and probe.get("runtime_sha256") == runtime_sha256
        and probe.get("import_status") == "PASSED"
        and runtime.get("production_release_allowed") is False
        and runtime.get("machine_write_permitted") is False,
        "EXTERNAL_RUNTIME_PROBE_FAILED",
    )
    return runtime_sha256


def _free_loopback_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as probe:
        probe.bind(("127.0.0.1", 0))
        return int(probe.getsockname()[1])


def _stop_owned_process(process: subprocess.Popen | None) -> dict[str, Any]:
    if process is None:
        return {"started": False, "exit_code": None, "exited": True}
    forced = False
    if process.poll() is None:
        forced = True
        process.terminate()
        try:
            process.wait(timeout=15)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait(timeout=15)
    return {
        "started": True,
        "exit_code": process.returncode,
        "exited": process.poll() is not None,
        "forced_stop": forced,
    }


def _wait_gateway_ready(
    process: subprocess.Popen,
    base_url: str,
    *,
    deadline: float,
) -> dict[str, Any]:
    with httpx.Client(trust_env=False, follow_redirects=False) as client:
        while time.monotonic() < deadline:
            require(process.poll() is None, "GATEWAY_EXITED_BEFORE_READY")
            try:
                response = client.get(base_url + "/gateway/v1/health", timeout=1.5)
                if response.status_code == 200:
                    payload = response.json()
                    if payload.get("status") == "READY":
                        require(
                            payload.get("gateway") == "SPRING_BOOT_WEBFLUX"
                            and payload.get("fastapi") == "READY",
                            "GATEWAY_HEALTH_IDENTITY_MISMATCH",
                        )
                        require(
                            payload.get("production_release_allowed") is False
                            and payload.get("machine_write_permitted") is False,
                            "GATEWAY_HEALTH_AUTHORITY_WIDENED",
                        )
                        return payload
            except (httpx.HTTPError, ValueError):
                pass
            time.sleep(0.2)
    raise SmokeError("GATEWAY_READINESS_TIMEOUT")


class SpringWorkflow:
    def __init__(self, base_url: str, deadline: float):
        self.client = httpx.Client(
            base_url=base_url,
            trust_env=False,
            follow_redirects=False,
            timeout=httpx.Timeout(600.0, connect=5.0),
        )
        self.deadline = deadline
        self.stage = "NOT_STARTED"
        self.request_count = 0
        self.gateway_header_count = 0
        self.jcs_receipt_count = 0

    def close(self) -> None:
        self.client.close()

    def request(
        self,
        method: str,
        path: str,
        *,
        expected_status: int,
        headers: dict[str, str] | None = None,
        payload: dict[str, Any] | None = None,
        params: dict[str, str] | None = None,
        sealed: bool = False,
        stage: str,
    ) -> Any:
        self.stage = stage
        require(time.monotonic() < self.deadline, "SMOKE_TOTAL_TIMEOUT")
        response = self.client.request(
            method,
            path,
            headers=headers,
            json=payload,
            params=params,
        )
        self.request_count += 1
        _require_gateway(response)
        self.gateway_header_count += 1
        if sealed:
            result = governed_payload(response, expected_status=expected_status)
            self.jcs_receipt_count += 1
            return result
        require(response.status_code == expected_status, "HTTP_STATUS_MISMATCH")
        try:
            return response.json()
        except (json.JSONDecodeError, UnicodeDecodeError) as error:
            raise SmokeError("HTTP_JSON_REQUIRED") from error


def _runtime_environment(
    root: Path, product_root: Path, token: str, startup_secret: str
) -> dict[str, str]:
    environment = os.environ.copy()
    for key in tuple(environment):
        if key.startswith("VISIONDATA_"):
            del environment[key]
    environment.update(
        {
            "APPDATA": str(root / "appdata"),
            "LOCALAPPDATA": str(root / "localappdata"),
            "PYTHONUTF8": "1",
            "VISIONDATA_DESKTOP_SESSION_TOKEN": token,
            "VISIONDATA_DESKTOP_STARTUP_SECRET": startup_secret,
            "VISIONDATA_PRODUCT_ROOT": str(product_root),
            "VISIONDATA_DESKTOP_CONFIG_FILE": str(root / "absent.env"),
            "VISIONDATA_DESKTOP_LOG_FILE": str(root / "logs" / "backend.log"),
            "VISIONDATA_WEB_ORIGINS": "http://tauri.localhost",
            "VISIONDATA_PRODUCT_MODEL_KEYS_ENABLED": "false",
        }
    )
    return environment


def _gateway_environment(root: Path, gateway_port: int, backend_port: int) -> dict[str, str]:
    environment = os.environ.copy()
    for key in tuple(environment):
        if key.startswith("VISIONDATA_"):
            del environment[key]
    environment.update(
        {
            "APPDATA": str(root / "appdata"),
            "LOCALAPPDATA": str(root / "localappdata"),
            "VISIONDATA_GATEWAY_PORT": str(gateway_port),
            "VISIONDATA_FASTAPI_BASE_URL": f"http://127.0.0.1:{backend_port}",
        }
    )
    return environment


def _existing_file(value: Path, code: str) -> Path:
    path = value.expanduser().resolve(strict=True)
    require(path.is_file() and not path.is_symlink(), code)
    return path


def _existing_directory(value: Path, code: str) -> Path:
    path = value.expanduser().resolve(strict=True)
    require(path.is_dir() and not path.is_symlink(), code)
    if hasattr(path, "is_junction"):
        require(not path.is_junction(), code)
    return path


def _fresh_project_output_root(value: Path) -> Path:
    output_root = (PROJECT_ROOT / "output").resolve(strict=True)
    path = value.expanduser().resolve()
    require(path.is_relative_to(output_root), "WORK_ROOT_MUST_BE_UNDER_PROJECT_OUTPUT")
    require(not path.exists(), "FRESH_WORK_ROOT_REQUIRED")
    path.mkdir(parents=True, exist_ok=False)
    return path


def _body_identity(path: Path, field: str) -> str:
    value = json.loads(path.read_text(encoding="utf-8"))
    digest = value.get(field)
    require(_sha_identity(digest), "SOURCE_IDENTITY_INVALID")
    return digest


def _sqlite_integrity(database: Path) -> str:
    require(database.is_file(), "ISOLATED_DATABASE_MISSING")
    with sqlite3.connect(database) as connection:
        return str(connection.execute("PRAGMA integrity_check").fetchone()[0])


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--installer", required=True, type=Path)
    parser.add_argument("--work-root", required=True, type=Path)
    parser.add_argument("--run-dir", required=True, action="append", type=Path)
    parser.add_argument("--target-run-dir", required=True, type=Path)
    parser.add_argument("--stability-summary", required=True, type=Path)
    parser.add_argument("--source-binding", required=True, type=Path)
    parser.add_argument("--source-index", required=True, type=Path)
    parser.add_argument("--backbone-weights", required=True, type=Path)
    parser.add_argument("--runtime-python", required=True, type=Path)
    parser.add_argument("--normal-image", required=True, type=Path)
    parser.add_argument("--anomaly-image", required=True, type=Path)
    parser.add_argument("--reviewer-identity", required=True)
    parser.add_argument("--timeout-seconds", type=int, default=1200)
    return parser


def run(args: argparse.Namespace) -> tuple[int, dict[str, Any], Path]:
    require(os.name == "nt", "WINDOWS_REQUIRED")
    require(300 <= args.timeout_seconds <= 1800, "TIMEOUT_BUDGET_INVALID")
    root = _fresh_project_output_root(args.work_root)
    receipt_path = root / "INSTALLED_NORMALITY_HTTP_SMOKE_RECEIPT.json"
    stage = "INPUT_VALIDATION"
    started = time.monotonic()
    deadline = started + args.timeout_seconds
    token = secrets.token_hex(32)
    startup_secret = secrets.token_hex(32)
    password = "S-" + secrets.token_urlsafe(32)
    install_root = root / "installed"
    product_root = root / "product"
    for directory in (
        root / "appdata",
        root / "localappdata",
        root / "logs",
        product_root,
    ):
        directory.mkdir(parents=True, exist_ok=True)

    backend = gateway = None
    backend_log = gateway_log = None
    workflow: SpringWorkflow | None = None
    install_exit_code = uninstall_exit_code = None
    backend_cleanup = gateway_cleanup = None
    uninstall_completion = {
        "complete": False,
        "owned_uninstaller_process_count": -1,
        "uninstall_registry_entry_count": -1,
        "installer_shortcut_count": -1,
        "install_root_exists": True,
    }
    graceful_shutdown_status = None
    database_integrity = "NOT_RUN"
    database_retained = False
    result: dict[str, Any] = {
        "schema_version": "visiondata-gate.installed-normality-http-smoke.v1",
        "status": "HOLD",
        "failure_stage": None,
        "failure_code": None,
        "transport": "INSTALLED_SPRING_WEBFLUX_TO_INSTALLED_FASTAPI_HTTP_ONLY",
        "source_server_fallback": False,
        "model_or_runtime_bundled": False,
        "identity_setup_completed": False,
        "production_release_allowed": False,
        "machine_write_permitted": False,
        "clean_machine_validation": "NOT_RUN",
        "industrial_performance_verified": False,
    }
    try:
        stage = "INPUT_VALIDATION"
        installer = _existing_file(args.installer, "INSTALLER_REQUIRED")
        runs = [
            _existing_directory(path, "STABILITY_RUN_REQUIRED")
            for path in args.run_dir
        ]
        require(len(runs) == 3 and len(set(runs)) == 3, "THREE_UNIQUE_RUNS_REQUIRED")
        target_run = _existing_directory(args.target_run_dir, "TARGET_RUN_REQUIRED")
        require(target_run in runs, "TARGET_RUN_NOT_IN_STABILITY_RUNS")
        stability = _existing_file(args.stability_summary, "STABILITY_SUMMARY_REQUIRED")
        source_binding = _existing_file(args.source_binding, "SOURCE_BINDING_REQUIRED")
        source_index = _existing_file(args.source_index, "SOURCE_INDEX_REQUIRED")
        backbone = _existing_file(args.backbone_weights, "BACKBONE_WEIGHTS_REQUIRED")
        runtime_python = _existing_file(args.runtime_python, "EXTERNAL_RUNTIME_REQUIRED")
        normal_image = _existing_file(args.normal_image, "NORMAL_IMAGE_REQUIRED")
        anomaly_image = _existing_file(args.anomaly_image, "ANOMALY_IMAGE_REQUIRED")
        model_pack = _existing_file(
            target_run / "private" / "worker" / "best_normality_model_pack.pt",
            "MODEL_PACK_REQUIRED",
        )
        hashes = {
            "installer": _sha256_file(installer),
            "model_pack_sha256": _sha256_file(model_pack),
            "stability_summary_sha256": _sha256_file(stability),
            "source_binding_file_sha256": _sha256_file(source_binding),
            "source_binding_sha256": _body_identity(source_binding, "binding_sha256"),
            "source_index_file_sha256": _sha256_file(source_index),
            "source_index_sha256": _body_identity(source_index, "index_sha256"),
            "backbone_weights_sha256": _sha256_file(backbone),
            "runtime_executable_sha256": _sha256_file(runtime_python),
            "normal_image_sha256": _sha256_file(normal_image),
            "anomaly_image_sha256": _sha256_file(anomaly_image),
        }

        stage = "NSIS_INSTALL"
        installer_environment = os.environ.copy()
        installer_environment.update(
            {"APPDATA": str(root / "appdata"), "LOCALAPPDATA": str(root / "localappdata")}
        )
        installed = subprocess.run(
            [str(installer), "/S", f"/D={install_root}"],
            env=installer_environment,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            timeout=240,
            check=False,
        )
        install_exit_code = installed.returncode
        require(install_exit_code == 0, "NSIS_INSTALL_FAILED")
        resources = installed_runtime_resources(install_root)
        installed_hashes = {key + "_sha256": _sha256_file(path) for key, path in resources.items()}

        stage = "INSTALLED_RUNTIME_STARTUP"
        backend_port = _free_loopback_port()
        gateway_port = _free_loopback_port()
        while gateway_port == backend_port:
            gateway_port = _free_loopback_port()
        creation_flags = subprocess.CREATE_NO_WINDOW
        backend_log = (root / "logs" / "backend-process.log").open("wb")
        gateway_log = (root / "logs" / "gateway-process.log").open("wb")
        backend = subprocess.Popen(
            [str(resources["backend"]), "--port", str(backend_port)],
            cwd=root,
            env=_runtime_environment(root, product_root, token, startup_secret),
            stdin=subprocess.DEVNULL,
            stdout=backend_log,
            stderr=subprocess.STDOUT,
            creationflags=creation_flags,
        )
        gateway = subprocess.Popen(
            [
                str(resources["java"]),
                "-Dfile.encoding=UTF-8",
                "-XX:ActiveProcessorCount=2",
                "-Xms32m",
                "-Xmx256m",
                "-jar",
                str(resources["gateway_jar"]),
            ],
            cwd=root,
            env=_gateway_environment(root, gateway_port, backend_port),
            stdin=subprocess.DEVNULL,
            stdout=gateway_log,
            stderr=subprocess.STDOUT,
            creationflags=creation_flags,
        )
        base_url = f"http://127.0.0.1:{gateway_port}"
        gateway_health = _wait_gateway_ready(
            gateway, base_url, deadline=min(deadline, time.monotonic() + 90)
        )
        workflow = SpringWorkflow(base_url, deadline)

        stage = "PROXIED_HMAC_READINESS"
        challenge = secrets.token_hex(32)
        expected_proof = hmac.new(
            startup_secret.encode("utf-8"), challenge.encode("utf-8"), hashlib.sha256
        ).hexdigest()
        readiness = workflow.client.get(
            "/v1/desktop/readiness", params={"challenge": challenge}, timeout=5
        )
        workflow.request_count += 1
        _require_gateway(readiness)
        workflow.gateway_header_count += 1
        require(
            readiness.status_code == 200
            and hmac.compare_digest(readiness.text.strip(), expected_proof),
            "PROXIED_HMAC_READINESS_FAILED",
        )

        status = workflow.request(
            "GET",
            "/v1/identity/status",
            expected_status=200,
            stage="IDENTITY_STATUS",
        )
        require(status.get("setup_required") is True, "FRESH_IDENTITY_SETUP_REQUIRED")
        setup = workflow.request(
            "POST",
            "/v1/identity/setup",
            expected_status=201,
            headers={"X-VisionData-Desktop-Token": token},
            payload={
                "login_name": "installed-normality-admin",
                "display_name": "Installed normality smoke reviewer",
                "password": password,
            },
            stage="IDENTITY_SETUP",
        )
        access_token = setup.get("access_token")
        user = setup.get("user")
        require(
            isinstance(access_token, str)
            and len(access_token) >= 32
            and isinstance(user, dict)
            and isinstance(user.get("user_id"), str),
            "IDENTITY_SETUP_RESPONSE_INVALID",
        )
        bearer = {"Authorization": "Bearer " + access_token}
        workspace = workflow.request(
            "POST",
            "/v1/workspaces",
            expected_status=201,
            headers=bearer,
            payload={
                "name": "Installed Model Pack Smoke",
                "owner_user_id": user["user_id"],
            },
            stage="WORKSPACE_CREATE",
        )
        project = workflow.request(
            "POST",
            "/v1/projects",
            expected_status=201,
            headers=bearer,
            payload={
                "workspace_id": workspace["workspace_id"],
                "name": "Installed Normality HTTP Project",
                "description": "Fresh isolated installed-stack Model Pack validation",
                "scenario_profile": "industrial",
                "source_kind": "local_authorized_directory",
            },
            stage="PROJECT_CREATE",
        )
        project_id = project["project_id"]
        base = f"/v1/projects/{project_id}"
        result["identity_setup_completed"] = True

        runtime = workflow.request(
            "POST",
            base + "/vision-runtimes",
            expected_status=201,
            headers=bearer,
            payload={
                "request_key": "installed-normality-runtime-register-0001",
                "reviewer_identity": args.reviewer_identity,
                "note": "Register the explicit external runtime for installed HTTP smoke",
                "display_name": "External YOLO26 normality runtime",
                "executable_path": str(runtime_python),
                "expected_executable_sha256": hashes["runtime_executable_sha256"],
                "operator_attests_trusted_runtime": True,
                "operator_attests_execution_authorized": True,
            },
            sealed=True,
            stage="RUNTIME_REGISTER",
        )
        runtime = workflow.request(
            "POST",
            base + f"/vision-runtimes/{runtime['runtime_id']}/probe",
            expected_status=200,
            headers=bearer,
            payload={
                "request_key": "installed-normality-runtime-probe-0001",
                "reviewer_identity": args.reviewer_identity,
                "note": "Import probe the exact external runtime before Model Pack loading",
                "expected_runtime_sha256": runtime["runtime_sha256"],
                "operator_attests_trusted_runtime": True,
                "operator_attests_execution_authorized": True,
                "import_check": True,
            },
            sealed=True,
            stage="RUNTIME_IMPORT_PROBE",
        )
        validate_runtime_probe(runtime, hashes["runtime_executable_sha256"])

        model = workflow.request(
            "POST",
            base + "/vision-model-packs",
            expected_status=201,
            headers=bearer,
            payload={
                "request_key": "installed-normality-pack-register-0001",
                "reviewer_identity": args.reviewer_identity,
                "note": "Recompute three nativeprep runs and internalize the v2 Model Pack",
                "display_name": "YOLO26 normality fixed-split seed13 Model Pack",
                "model_pack_path": str(model_pack),
                "expected_model_pack_sha256": hashes["model_pack_sha256"],
                "run_directory": str(target_run),
                "stability_run_directories": [str(path) for path in runs],
                "target_model_seed": 20260913,
                "stability_summary_path": str(stability),
                "expected_stability_summary_sha256": hashes[
                    "stability_summary_sha256"
                ],
                "source_binding_path": str(source_binding),
                "expected_source_binding_file_sha256": hashes[
                    "source_binding_file_sha256"
                ],
                "expected_source_binding_sha256": hashes["source_binding_sha256"],
                "source_index_path": str(source_index),
                "expected_source_index_file_sha256": hashes[
                    "source_index_file_sha256"
                ],
                "expected_source_index_sha256": hashes["source_index_sha256"],
                "backbone_weights_path": str(backbone),
                "expected_backbone_weights_sha256": hashes[
                    "backbone_weights_sha256"
                ],
                "operator_attests_read_authorized": True,
                "operator_attests_weights_only_load_authorized": True,
                "ultralytics_license_acknowledged": True,
            },
            sealed=True,
            stage="MODEL_PACK_REGISTER",
        )
        require(
            model.get("stability_schema_version")
            == "visiondata-gate.model-stability.v4"
            and model.get("stability_status") == "PUBLIC_PROXY_STABLE"
            and model.get("model_pack_sha256") == hashes["model_pack_sha256"]
            and model.get("production_release_allowed") is False,
            "MODEL_PACK_REGISTRATION_CONTRACT_FAILED",
        )

        approved = workflow.request(
            "POST",
            base + f"/vision-models/{model['model_id']}/sandbox-approval",
            expected_status=200,
            headers=bearer,
            payload={
                "request_key": "installed-normality-sandbox-approve-0001",
                "reviewer_identity": args.reviewer_identity,
                "note": "Approve this exact Model Pack for local sandbox inference only",
                "action": "APPROVE_SANDBOX",
                "expected_model_receipt_sha256": model["receipt_sha256"],
                "expected_model_pack_sha256": model["model_pack_sha256"],
                "expected_backbone_weights_sha256": model[
                    "backbone_weights_sha256"
                ],
                "expected_source_binding_sha256": model["source_binding_sha256"],
                "expected_source_index_sha256": model["source_index_sha256"],
                "runtime_id": runtime["runtime_id"],
                "expected_runtime_sha256": runtime["runtime_sha256"],
                "operator_attests_reviewed": True,
                "operator_attests_trusted_runtime": True,
                "operator_attests_execution_authorized": True,
                "operator_attests_trusted_weights": True,
                "operator_attests_weights_only_load_authorized": True,
                "ultralytics_license_acknowledged": True,
            },
            sealed=True,
            stage="MODEL_PACK_APPROVE_SANDBOX",
        )
        require(
            approved.get("status") == "APPROVE_SANDBOX"
            and approved.get("sandbox_validation", {}).get(
                "inference_backend_sha256"
            )
            == EXPECTED_INFERENCE_BACKEND_SHA256
            and approved.get("production_release_allowed") is False,
            "SANDBOX_APPROVAL_IDENTITY_MISMATCH",
        )

        projections: dict[str, dict[str, Any]] = {}
        for label, image, image_sha in (
            ("normal", normal_image, hashes["normal_image_sha256"]),
            ("anomaly", anomaly_image, hashes["anomaly_image_sha256"]),
        ):
            asset = workflow.request(
                "POST",
                base + "/vision-inference-assets",
                expected_status=201,
                headers=bearer,
                payload={
                    "request_key": f"installed-normality-{label}-asset-0001",
                    "reviewer_identity": args.reviewer_identity,
                    "note": f"Freeze the predeclared {label} public-proxy image in registry CAS",
                    "display_name": f"Predeclared {label} public-proxy image",
                    "image_path": str(image),
                    "expected_image_sha256": image_sha,
                    "operator_attests_read_authorized": True,
                },
                sealed=True,
                stage=f"{label.upper()}_ASSET_REGISTER",
            )
            require(asset.get("image_sha256") == image_sha, "ASSET_IDENTITY_MISMATCH")
            inference = workflow.request(
                "POST",
                base + f"/vision-models/{approved['model_id']}/inferences",
                expected_status=201,
                headers=bearer,
                payload={
                    "request_key": f"installed-normality-{label}-inference-0001",
                    "reviewer_identity": args.reviewer_identity,
                    "note": f"Run one bounded {label} signal through the installed stack",
                    "expected_model_receipt_sha256": approved["receipt_sha256"],
                    "expected_model_pack_sha256": approved["model_pack_sha256"],
                    "expected_backbone_weights_sha256": approved[
                        "backbone_weights_sha256"
                    ],
                    "expected_source_binding_sha256": approved[
                        "source_binding_sha256"
                    ],
                    "expected_source_index_sha256": approved["source_index_sha256"],
                    "expected_runtime_sha256": approved["sandbox_runtime_sha256"],
                    "asset_id": asset["asset_id"],
                    "expected_asset_receipt_sha256": asset["receipt_sha256"],
                    "expected_image_sha256": asset["image_sha256"],
                    "max_seconds": 120,
                    "operator_attests_execution_authorized": True,
                    "operator_attests_trusted_runtime": True,
                    "operator_attests_trusted_weights": True,
                    "operator_attests_weights_only_load_authorized": True,
                },
                sealed=True,
                stage=f"{label.upper()}_INFERENCE",
            )
            expected = {
                "model_pack_sha256": approved["model_pack_sha256"],
                "backbone_weights_sha256": approved["backbone_weights_sha256"],
                "source_binding_sha256": approved["source_binding_sha256"],
                "source_index_sha256": approved["source_index_sha256"],
                "runtime_sha256": approved["sandbox_runtime_sha256"],
                "inference_backend_sha256": EXPECTED_INFERENCE_BACKEND_SHA256,
                "image_sha256": image_sha,
            }
            validate_inference(inference, expected)
            projections[label] = {
                "reference_label": label,
                "label_truth_authority": False,
                "asset_id": asset["asset_id"],
                "inference_id": inference["inference_id"],
                "image_sha256": image_sha,
                "image_score": inference["image_score"],
                "image_threshold": inference["image_threshold"],
                "predicted_anomaly": inference["predicted_anomaly"],
                "heatmap_sha256": inference["heatmap"]["sha256"],
                "inference_receipt_sha256": inference["receipt_sha256"],
                "production_release_allowed": False,
            }

        result.update(
            {
                "status": "PASS_INSTALLED_NORMALITY_HTTP_SMOKE",
                "installer_sha256": hashes["installer"],
                "installed_artifact_sha256": installed_hashes,
                "gateway_health": {
                    "status": gateway_health["status"],
                    "gateway": gateway_health["gateway"],
                    "fastapi": gateway_health["fastapi"],
                },
                "proxied_hmac_readiness_verified": True,
                "workspace_id": workspace["workspace_id"],
                "project_id": project_id,
                "runtime": {
                    "runtime_id": runtime["runtime_id"],
                    "runtime_sha256": runtime["runtime_sha256"],
                    "import_status": runtime["probe"]["import_status"],
                },
                "model": {
                    "model_id": approved["model_id"],
                    "status": approved["status"],
                    "model_pack_sha256": approved["model_pack_sha256"],
                    "backbone_weights_sha256": approved[
                        "backbone_weights_sha256"
                    ],
                    "source_binding_sha256": approved["source_binding_sha256"],
                    "source_index_sha256": approved["source_index_sha256"],
                    "stability_schema_version": approved[
                        "stability_schema_version"
                    ],
                    "stability_status": approved["stability_status"],
                    "inference_backend_sha256": EXPECTED_INFERENCE_BACKEND_SHA256,
                    "production_release_allowed": False,
                },
                "results": projections,
                "reference_label_boundary": (
                    "The two public-proxy labels are retained for transparency, "
                    "not treated as factory governance truth. Observed false "
                    "positive or false negative outcomes are preserved."
                ),
            }
        )
    except (
        SmokeError,
        httpx.HTTPError,
        OSError,
        ValueError,
        KeyError,
        subprocess.TimeoutExpired,
    ) as error:
        result["status"] = "HOLD"
        result["failure_stage"] = workflow.stage if workflow is not None else stage
        result["failure_code"] = (
            str(error) if isinstance(error, SmokeError) else type(error).__name__
        )
    finally:
        if workflow is not None:
            if backend is not None and backend.poll() is None:
                try:
                    shutdown = workflow.client.post(
                        "/v1/desktop/shutdown",
                        headers={"X-VisionData-Desktop-Token": token},
                        timeout=10,
                    )
                    workflow.request_count += 1
                    _require_gateway(shutdown)
                    workflow.gateway_header_count += 1
                    graceful_shutdown_status = shutdown.status_code
                    if shutdown.status_code == 202:
                        backend.wait(timeout=30)
                except (SmokeError, httpx.HTTPError, subprocess.TimeoutExpired):
                    pass
            workflow.close()
        backend_cleanup = _stop_owned_process(backend)
        gateway_cleanup = _stop_owned_process(gateway)
        if backend_log is not None:
            backend_log.close()
        if gateway_log is not None:
            gateway_log.close()

        database = product_root / "product.sqlite3"
        try:
            database_integrity = _sqlite_integrity(database)
        except (SmokeError, OSError, sqlite3.Error):
            database_integrity = "FAILED_OR_MISSING"

        if install_root.exists():
            try:
                helpers = installer_uninstall_helpers()
                uninstaller = helpers["find_uninstaller"](install_root)
                uninstalled = subprocess.run(
                    [str(uninstaller), "/S"],
                    stdin=subprocess.DEVNULL,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                    timeout=240,
                    check=False,
                )
                uninstall_exit_code = uninstalled.returncode
                if uninstall_exit_code == 0:
                    uninstall_completion = helpers[
                        "wait_for_uninstall_completion"
                    ](install_root)
            except (OSError, RuntimeError, subprocess.TimeoutExpired):
                uninstall_completion["complete"] = False
        else:
            uninstall_completion = {
                "complete": True,
                "owned_uninstaller_process_count": 0,
                "uninstall_registry_entry_count": 0,
                "installer_shortcut_count": 0,
                "install_root_exists": False,
                "poll_count": 0,
                "elapsed_seconds": 0.0,
            }
        database_retained = database.is_file()

    process_cleanup = {
        "backend_shutdown_http_status": graceful_shutdown_status,
        "backend": backend_cleanup,
        "gateway": gateway_cleanup,
        "all_owned_processes_exited": bool(
            backend_cleanup
            and gateway_cleanup
            and backend_cleanup["exited"]
            and gateway_cleanup["exited"]
        ),
    }
    result.update(
        {
            "installer_exit_code": install_exit_code,
            "uninstaller_exit_code": uninstall_exit_code,
            "process_cleanup": process_cleanup,
            "uninstall_completion": uninstall_completion,
            "sqlite_integrity_check": database_integrity,
            "isolated_database_retained_after_uninstall": database_retained,
            "http": {
                "request_count": workflow.request_count if workflow else 0,
                "gateway_header_verified_count": (
                    workflow.gateway_header_count if workflow else 0
                ),
                "jcs_receipt_verified_count": (
                    workflow.jcs_receipt_count if workflow else 0
                ),
            },
            "elapsed_seconds": round(time.monotonic() - started, 4),
        }
    )
    completion_ok = (
        result["status"] == "PASS_INSTALLED_NORMALITY_HTTP_SMOKE"
        and process_cleanup["all_owned_processes_exited"] is True
        and uninstall_exit_code == 0
        and uninstall_completion.get("complete") is True
        and uninstall_completion.get("owned_uninstaller_process_count") == 0
        and uninstall_completion.get("uninstall_registry_entry_count") == 0
        and uninstall_completion.get("installer_shortcut_count") == 0
        and uninstall_completion.get("install_root_exists") is False
        and database_integrity == "ok"
        and database_retained
        and result["http"]["request_count"]
        == result["http"]["gateway_header_verified_count"]
    )
    if not completion_ok:
        result["status"] = "HOLD"
        result["failure_stage"] = result.get("failure_stage") or "FINAL_CONVERGENCE"
        result["failure_code"] = result.get("failure_code") or (
            "INSTALLED_SMOKE_OR_UNINSTALL_NOT_CONVERGED"
        )
    receipt = write_public_receipt_new(
        receipt_path,
        result,
        forbidden_values=(token, startup_secret, password),
    )
    return (0 if completion_ok else 2), receipt, receipt_path


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        exit_code, receipt, _path = run(args)
        print(
            json.dumps(
                {
                    "status": receipt["status"],
                    "failure_stage": receipt.get("failure_stage"),
                    "failure_code": receipt.get("failure_code"),
                    "receipt_sha256": receipt["receipt_sha256"],
                    "production_release_allowed": False,
                },
                sort_keys=True,
            )
        )
        return exit_code
    except (SmokeError, OSError, ValueError) as error:
        print(
            json.dumps(
                {
                    "status": "HOLD",
                    "failure_code": (
                        str(error) if isinstance(error, SmokeError) else type(error).__name__
                    ),
                    "production_release_allowed": False,
                },
                sort_keys=True,
            ),
            file=sys.stderr,
        )
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
