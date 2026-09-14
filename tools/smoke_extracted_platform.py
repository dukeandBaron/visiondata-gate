"""Validate one NSIS-extracted packaged platform without source-service fallback.

The driver installs an exact NSIS artifact into a fresh project-output root,
binds the extracted backend/JRE/JAR to the exact BUILD_MANIFEST, performs 120
proxied Spring HTTP requests, executes the existing two-round packaged-learning
contract, then invokes the authoritative NSIS uninstall convergence checks.
"""

from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import secrets
import subprocess
import sys
import time
from typing import Any

import httpx
import rfc8785


PROJECT_ROOT = Path(__file__).resolve().parents[1]
HTTP_REQUEST_COUNT = 120


class PostValidationError(ValueError):
    """Stable post-build failure code with no private path or secret."""


def require(condition: bool, code: str) -> None:
    if not condition:
        raise PostValidationError(code)


def _sibling(name: str):
    path = Path(__file__).resolve().with_name(name + ".py")
    spec = importlib.util.spec_from_file_location("postvalidation_" + name, path)
    require(spec is not None and spec.loader is not None, "SIBLING_TOOL_UNAVAILABLE")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def http_request_plan(project_id: str) -> list[dict[str, str]]:
    cycle = (
        {"kind": "health", "path": "/v1/health"},
        {"kind": "workspaces", "path": "/v1/workspaces"},
        {
            "kind": "projects",
            "path": "/v1/projects?workspace_id=wsp_local_demo",
        },
        {
            "kind": "vision_capabilities",
            "path": f"/v1/projects/{project_id}/vision-capabilities",
        },
    )
    return [dict(cycle[index % len(cycle)]) for index in range(HTTP_REQUEST_COUNT)]


def resource_binding_projection(
    inputs: dict[str, Any],
    *,
    build_manifest_sha256: str,
    installer_sha256: str,
) -> dict[str, Any]:
    backend = inputs["backend_resources"]
    java = inputs["java_runtime"]
    return {
        "schema_version": "visiondata-gate.extracted-resource-binding.v1",
        "status": "PASS_EXTRACTED_RESOURCES_BOUND",
        "installer_sha256": installer_sha256,
        "build_manifest_sha256": build_manifest_sha256,
        "backend_executable": {
            "sha256": inputs["backend_executable"]["sha256"],
            "size": inputs["backend_executable"]["size"],
        },
        "backend": {
            "content_sha256": backend["content_sha256"],
            "file_count": backend["file_count"],
            "total_bytes": backend["total_bytes"],
        },
        "gateway_jar": {
            "sha256": inputs["gateway_jar"]["sha256"],
            "size": inputs["gateway_jar"]["size"],
        },
        "java_runtime": {
            "content_sha256": java["content_sha256"],
            "file_count": java["file_count"],
            "total_bytes": java["total_bytes"],
        },
        "model_pack_bundled": False,
        "source_fallback": False,
        "production_release_allowed": False,
        "machine_write_permitted": False,
    }


def validate_packaged_learning(
    payload: dict[str, Any], expected_manifest_sha256: str
) -> dict[str, Any]:
    require(payload.get("source_fallback") is False, "SOURCE_FALLBACK_FORBIDDEN")
    require(
        payload.get("bound_build_manifest_sha256") == expected_manifest_sha256,
        "BUILD_MANIFEST_BINDING_MISMATCH",
    )
    rounds = payload.get("rounds")
    require(
        isinstance(rounds, list)
        and len(rounds) == 2
        and [item.get("round_number") for item in rounds] == [1, 2]
        and all(item.get("status") == "COMPLETED" for item in rounds)
        and payload.get("round_two_continued_first_candidate") is True,
        "TWO_LEARNING_ROUNDS_REQUIRED",
    )
    require(
        payload.get("status") == "PASS_PACKAGED_LEARNING"
        and payload.get("runtime_execution")
        == "SPECIFIED_PACKAGED_EXE_JRE_JAR_ONLY"
        and payload.get("workflow_transport")
        == "SPRING_WEBFLUX_GATEWAY_HTTP_ONLY"
        and type(payload.get("http_request_count")) is int
        and payload["http_request_count"] > 0
        and payload.get("holdout_fingerprints_preserved") is True
        and payload.get("runtime_artifact_bytes_unchanged") is True
        and payload.get("process_cleanup", {}).get("all_owned_processes_exited")
        is True,
        "PACKAGED_LEARNING_CONTRACT_FAILED",
    )
    require(
        payload.get("production_release_allowed") is False
        and payload.get("machine_write_permitted") is False
        and payload.get("industrial_performance_verified") is False,
        "PACKAGED_LEARNING_AUTHORITY_WIDENED",
    )
    return {
        "schema_version": "visiondata-gate.packaged-learning-projection.v1",
        "status": payload["status"],
        "source_fallback": False,
        "build_manifest_sha256": expected_manifest_sha256,
        "round_count": 2,
        "round_two_continued_first_candidate": True,
        "holdout_fingerprints_preserved": True,
        "http_request_count": payload["http_request_count"],
        "runtime_artifact_bytes_unchanged": True,
        "all_owned_processes_exited": True,
        "production_release_allowed": False,
        "machine_write_permitted": False,
        "industrial_performance_verified": False,
    }


def _fresh_root(value: Path) -> Path:
    output_root = (PROJECT_ROOT / "output").resolve(strict=True)
    root = value.expanduser().resolve()
    require(root.is_relative_to(output_root), "WORK_ROOT_MUST_BE_PROJECT_OUTPUT")
    require(not root.exists(), "FRESH_WORK_ROOT_REQUIRED")
    root.mkdir(parents=True, exist_ok=False)
    return root


def _expected_installer(manifest: dict[str, Any], installer: Path) -> None:
    expected = manifest.get("artifacts", {}).get("installer")
    require(isinstance(expected, dict), "BUILD_INSTALLER_BINDING_REQUIRED")
    require(
        expected.get("sha256") == _sha256(installer)
        and expected.get("size") == installer.stat().st_size,
        "INSTALLER_BUILD_MANIFEST_MISMATCH",
    )


def _start_http_runtime(
    packaged,
    artifact_root: Path,
    resources: dict[str, Path],
    root: Path,
    build_manifest: Path,
    installer_sha256: str,
) -> tuple[dict[str, Any], Path]:
    state = root / "http-120"
    state.mkdir(parents=True, exist_ok=False)
    token, startup_secret = secrets.token_hex(32), secrets.token_hex(32)
    backend_port = packaged.demo.free_loopback_port()
    gateway_port = packaged.demo.free_loopback_port()
    while gateway_port == backend_port:
        gateway_port = packaged.demo.free_loopback_port()
    commands = packaged.runtime_commands(
        artifact_root,
        resources["backend"].parent,
        resources["java"].parents[1],
        resources["gateway_jar"],
        backend_port,
    )
    backend_environment = packaged.runtime_environment(state, token, startup_secret)
    gateway_environment = packaged.demo.child_environment(
        state, "unused-no-gateway-authority"
    )
    for key in tuple(gateway_environment):
        if key.startswith("VISIONDATA_"):
            del gateway_environment[key]
    gateway_environment.update(
        VISIONDATA_GATEWAY_PORT=str(gateway_port),
        VISIONDATA_FASTAPI_BASE_URL=f"http://127.0.0.1:{backend_port}",
    )
    flags = subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0
    backend = gateway = None
    graceful_status = None
    result: dict[str, Any] | None = None
    before = packaged.artifact_inputs(
        resources["backend"].parent,
        resources["java"].parents[1],
        resources["gateway_jar"],
    )
    manifest_sha = packaged._bind_expected(before, build_manifest)
    deadline = time.monotonic() + 240
    try:
        backend = subprocess.Popen(
            commands["backend"],
            cwd=state,
            env=backend_environment,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            creationflags=flags,
        )
        gateway = subprocess.Popen(
            commands["gateway"],
            cwd=state,
            env=gateway_environment,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            creationflags=flags,
        )
        base_url = f"http://127.0.0.1:{gateway_port}"
        health = packaged._wait_json(
            gateway, base_url + "/gateway/v1/health", deadline
        )
        require(
            health.get("status") == "READY"
            and health.get("gateway") == "SPRING_BOOT_WEBFLUX"
            and health.get("fastapi") == "READY",
            "PACKAGED_GATEWAY_NOT_READY",
        )
        packaged._proof(base_url, startup_secret, gateway=True)
        headers = {
            "X-VisionData-Desktop-Token": token,
            "X-Actor-User-Id": "usr_local_demo",
        }
        stable_digest: dict[str, str] = {}
        counts: dict[str, int] = {}
        gateway_headers = jcs_receipts = 0
        with httpx.Client(
            base_url=base_url,
            headers=headers,
            trust_env=False,
            follow_redirects=False,
            timeout=15,
        ) as client:
            denied = client.get(
                "/v1/workspaces",
                headers={"X-VisionData-Desktop-Token": "invalid"},
            )
            packaged.require_gateway_response(denied)
            require(denied.status_code == 401, "INVALID_TOKEN_NOT_REJECTED")
            for item in http_request_plan("prj_industrial_vision"):
                response = client.get(item["path"])
                packaged.require_gateway_response(response)
                gateway_headers += 1
                require(response.status_code == 200, "HTTP_120_STATUS_MISMATCH")
                if item["kind"] == "vision_capabilities":
                    payload = _sibling("smoke_installed_normality").governed_payload(
                        response, expected_status=200
                    )
                    jcs_receipts += 1
                    require(
                        payload.get("production_release_allowed") is False,
                        "HTTP_120_AUTHORITY_WIDENED",
                    )
                else:
                    payload = response.json()
                if item["kind"] == "health":
                    require(payload.get("production_ready") is False, "HEALTH_FALSE_PASS")
                elif item["kind"] == "workspaces":
                    require(
                        isinstance(payload, list)
                        and any(row.get("workspace_id") == "wsp_local_demo" for row in payload),
                        "DEFAULT_WORKSPACE_MISSING",
                    )
                elif item["kind"] == "projects":
                    require(
                        isinstance(payload, list)
                        and any(
                            row.get("project_id") == "prj_industrial_vision"
                            for row in payload
                        ),
                        "DEFAULT_PROJECT_MISSING",
                    )
                digest = hashlib.sha256(rfc8785.dumps(payload)).hexdigest()
                expected = stable_digest.setdefault(item["kind"], digest)
                require(expected == digest, "HTTP_120_RESPONSE_DRIFT")
                counts[item["kind"]] = counts.get(item["kind"], 0) + 1
        result = {
            "schema_version": "visiondata-gate.extracted-http-120-smoke.v1",
            "status": "PASS_EXTRACTED_HTTP_120",
            "installer_sha256": installer_sha256,
            "build_manifest_sha256": manifest_sha,
            "runtime_execution": "EXTRACTED_PACKAGED_EXE_JRE_JAR_ONLY",
            "workflow_transport": "SPRING_WEBFLUX_GATEWAY_HTTP_ONLY",
            "source_fallback": False,
            "request_count": HTTP_REQUEST_COUNT,
            "request_counts_by_kind": counts,
            "gateway_header_verified_count": gateway_headers,
            "jcs_receipt_verified_count": jcs_receipts,
            "response_digest_by_kind": stable_digest,
            "invalid_token_status": denied.status_code,
            "proxied_hmac_readiness_verified": True,
            "runtime_artifact_bytes_unchanged": False,
            "production_release_allowed": False,
            "machine_write_permitted": False,
            "industrial_performance_verified": False,
            "clean_machine_validation": "NOT_RUN",
        }
    finally:
        if backend is not None and backend.poll() is None and gateway is not None:
            try:
                with httpx.Client(
                    base_url=f"http://127.0.0.1:{gateway_port}",
                    trust_env=False,
                    follow_redirects=False,
                ) as client:
                    shutdown = client.post(
                        "/v1/desktop/shutdown",
                        headers={"X-VisionData-Desktop-Token": token},
                        timeout=10,
                    )
                    packaged.require_gateway_response(shutdown)
                    graceful_status = shutdown.status_code
                if graceful_status == 202:
                    backend.wait(timeout=20)
            except (httpx.HTTPError, subprocess.TimeoutExpired, ValueError):
                pass
        backend_forced = backend is not None and backend.poll() is None
        backend_exit = packaged.stop_owned_process(backend)
        gateway_exit = packaged.stop_owned_process(gateway)
    require(result is not None, "HTTP_120_RESULT_MISSING")
    after = packaged.artifact_inputs(
        resources["backend"].parent,
        resources["java"].parents[1],
        resources["gateway_jar"],
    )
    result["runtime_artifact_bytes_unchanged"] = before == after
    result["process_cleanup"] = {
        "backend_shutdown_http_status": graceful_status,
        "backend_exit_code": backend_exit,
        "backend_graceful_shutdown": backend_exit == 0 and not backend_forced,
        "gateway_exit_code": gateway_exit,
        "all_owned_processes_exited": (
            backend is None or backend.poll() is not None
        )
        and (gateway is None or gateway.poll() is not None),
    }
    require(
        result["request_count"] == result["gateway_header_verified_count"] == 120
        and result["jcs_receipt_verified_count"] == 30
        and result["runtime_artifact_bytes_unchanged"] is True
        and result["process_cleanup"]["backend_graceful_shutdown"] is True
        and result["process_cleanup"]["all_owned_processes_exited"] is True,
        "HTTP_120_FINAL_CONTRACT_FAILED",
    )
    output = state / "EXTRACTED_HTTP_120_SMOKE.json"
    receipt = _sibling("smoke_installed_normality").write_public_receipt_new(
        output,
        result,
        forbidden_values=(token, startup_secret),
    )
    return receipt, output


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--installer", required=True, type=Path)
    parser.add_argument("--build-manifest", required=True, type=Path)
    parser.add_argument("--work-root", required=True, type=Path)
    return parser


def run(args: argparse.Namespace) -> tuple[int, dict[str, Any]]:
    require(os.name == "nt", "WINDOWS_REQUIRED")
    packaged = _sibling("smoke_packaged_learning")
    installed = _sibling("smoke_installed_normality")
    root = _fresh_root(args.work_root)
    extracted = root / "extracted"
    for name in ("appdata", "localappdata", "temp"):
        (root / name).mkdir()
    installer = args.installer.expanduser().resolve(strict=True)
    manifest_path = args.build_manifest.expanduser().resolve(strict=True)
    require(installer.is_file() and manifest_path.is_file(), "BUILD_INPUT_REQUIRED")
    installer_sha = _sha256(installer)
    manifest_sha = _sha256(manifest_path)
    manifest = packaged.build.read_json(manifest_path)
    _expected_installer(manifest, installer)
    stage = "NSIS_EXTRACTION"
    install_exit = uninstall_exit = None
    uninstall_completion: dict[str, Any] = {"complete": False}
    summary: dict[str, Any] = {
        "schema_version": "visiondata-gate.extracted-platform-postvalidation.v1",
        "status": "HOLD",
        "failure_stage": None,
        "failure_code": None,
        "installer_sha256": installer_sha,
        "build_manifest_sha256": manifest_sha,
        "source_fallback": False,
        "production_release_allowed": False,
        "machine_write_permitted": False,
        "industrial_performance_verified": False,
        "clean_machine_validation": "NOT_RUN",
    }
    try:
        environment = os.environ.copy()
        environment.update(
            {
                "APPDATA": str(root / "appdata"),
                "LOCALAPPDATA": str(root / "localappdata"),
                "TEMP": str(root / "temp"),
                "TMP": str(root / "temp"),
            }
        )
        installed_result = subprocess.run(
            [str(installer), "/S", f"/D={extracted}"],
            env=environment,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            timeout=240,
            check=False,
        )
        install_exit = installed_result.returncode
        require(install_exit == 0, "NSIS_EXTRACTION_FAILED")
        resources = installed.installed_runtime_resources(extracted)
        stage = "EXTRACTED_RESOURCE_BINDING"
        inputs = packaged.artifact_inputs(
            resources["backend"].parent,
            resources["java"].parents[1],
            resources["gateway_jar"],
        )
        bound_manifest_sha = packaged._bind_expected(inputs, manifest_path)
        require(bound_manifest_sha == manifest_sha, "BUILD_MANIFEST_BINDING_MISMATCH")
        binding = resource_binding_projection(
            inputs,
            build_manifest_sha256=manifest_sha,
            installer_sha256=installer_sha,
        )
        binding_path = root / "EXTRACTED_RESOURCE_BINDING.json"
        binding_receipt = installed.write_public_receipt_new(binding_path, binding)

        stage = "EXTRACTED_HTTP_120"
        http_receipt, http_path = _start_http_runtime(
            packaged,
            extracted,
            resources,
            root,
            manifest_path,
            installer_sha,
        )

        stage = "EXTRACTED_PACKAGED_LEARNING"
        learning_root = root / "packaged-learning"
        learning_exit = packaged.run_smoke(
            extracted,
            resources["backend"].parent,
            resources["java"].parents[1],
            resources["gateway_jar"],
            learning_root,
            timeout_seconds=300,
            build_manifest=manifest_path,
        )
        require(learning_exit == 0, "PACKAGED_LEARNING_FAILED")
        learning_path = learning_root / "PACKAGED_LEARNING_SMOKE.json"
        learning = packaged.build.read_json(learning_path)
        learning_projection = validate_packaged_learning(learning, manifest_sha)
        learning_projection["packaged_learning_file_sha256"] = _sha256(learning_path)
        learning_projection_path = root / "PACKAGED_LEARNING_PROJECTION.json"
        learning_projection_receipt = installed.write_public_receipt_new(
            learning_projection_path, learning_projection
        )
        summary.update(
            {
                "status": "PASS_EXTRACTED_PLATFORM_POSTVALIDATION",
                "resource_binding": {
                    "status": binding_receipt["status"],
                    "receipt_sha256": binding_receipt["receipt_sha256"],
                    "file_sha256": _sha256(binding_path),
                },
                "http_120": {
                    "status": http_receipt["status"],
                    "request_count": http_receipt["request_count"],
                    "gateway_header_verified_count": http_receipt[
                        "gateway_header_verified_count"
                    ],
                    "receipt_sha256": http_receipt["receipt_sha256"],
                    "file_sha256": _sha256(http_path),
                },
                "packaged_learning": {
                    "status": learning_projection_receipt["status"],
                    "source_fallback": False,
                    "round_count": 2,
                    "http_request_count": learning_projection_receipt[
                        "http_request_count"
                    ],
                    "raw_file_sha256": _sha256(learning_path),
                    "projection_receipt_sha256": learning_projection_receipt[
                        "receipt_sha256"
                    ],
                    "projection_file_sha256": _sha256(learning_projection_path),
                },
            }
        )
    except (
        PostValidationError,
        installed.SmokeError,
        packaged.SmokeError,
        packaged.build.BuildError,
        httpx.HTTPError,
        OSError,
        ValueError,
        KeyError,
        subprocess.TimeoutExpired,
    ) as error:
        summary["status"] = "HOLD"
        summary["failure_stage"] = stage
        summary["failure_code"] = (
            str(error)
            if isinstance(
                error,
                (
                    PostValidationError,
                    installed.SmokeError,
                    packaged.SmokeError,
                    packaged.build.BuildError,
                ),
            )
            else type(error).__name__
        )
    finally:
        if extracted.exists():
            try:
                helpers = installed.installer_uninstall_helpers()
                uninstaller = helpers["find_uninstaller"](extracted)
                uninstalled = subprocess.run(
                    [str(uninstaller), "/S"],
                    env=environment,
                    stdin=subprocess.DEVNULL,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                    timeout=240,
                    check=False,
                )
                uninstall_exit = uninstalled.returncode
                if uninstall_exit == 0:
                    uninstall_completion = helpers[
                        "wait_for_uninstall_completion"
                    ](extracted)
            except (OSError, RuntimeError, subprocess.TimeoutExpired):
                uninstall_completion = {"complete": False}
        else:
            uninstall_completion = {
                "complete": True,
                "owned_uninstaller_process_count": 0,
                "uninstall_registry_entry_count": 0,
                "installer_shortcut_count": 0,
                "install_root_exists": False,
            }
    temp_files = [path for path in (root / "temp").rglob("*") if path.is_file()]
    summary.update(
        {
            "installer_exit_code": install_exit,
            "uninstaller_exit_code": uninstall_exit,
            "uninstall_completion": uninstall_completion,
            "isolated_temp_residue_file_count": len(temp_files),
            "isolated_temp_residue_bytes": sum(path.stat().st_size for path in temp_files),
        }
    )
    complete = (
        summary["status"] == "PASS_EXTRACTED_PLATFORM_POSTVALIDATION"
        and uninstall_exit == 0
        and uninstall_completion.get("complete") is True
        and uninstall_completion.get("owned_uninstaller_process_count") == 0
        and uninstall_completion.get("uninstall_registry_entry_count") == 0
        and uninstall_completion.get("installer_shortcut_count") == 0
        and uninstall_completion.get("install_root_exists") is False
    )
    if not complete:
        summary["status"] = "HOLD"
        summary["failure_stage"] = summary.get("failure_stage") or "NSIS_UNINSTALL"
        summary["failure_code"] = summary.get("failure_code") or (
            "POSTVALIDATION_NOT_CONVERGED"
        )
    final_path = root / "EXTRACTED_PLATFORM_POSTVALIDATION.json"
    receipt = installed.write_public_receipt_new(final_path, summary)
    return (0 if complete else 2), receipt


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        code, receipt = run(args)
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
        return code
    except (PostValidationError, OSError, ValueError) as error:
        print(
            json.dumps(
                {
                    "status": "HOLD",
                    "failure_code": (
                        str(error)
                        if isinstance(error, PostValidationError)
                        else type(error).__name__
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
