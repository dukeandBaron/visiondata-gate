"""Contracts for the installed Spring/FastAPI normality HTTP smoke."""

from __future__ import annotations

import hashlib
import importlib.util
from pathlib import Path

import httpx
import pytest
import rfc8785


TOOL = (
    Path(__file__).resolve().parents[1]
    / "tools"
    / "smoke_installed_normality.py"
)
NORMALITY_SOURCE = (
    Path(__file__).resolve().parents[1]
    / "src"
    / "visiondata_gate"
    / "normality_inference.py"
)


def _load_tool():
    spec = importlib.util.spec_from_file_location("installed_normality_smoke", TOOL)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _sealed_response(path: str, body: dict) -> httpx.Response:
    stable = {key: value for key, value in body.items() if key != "receipt_sha256"}
    digest = hashlib.sha256(rfc8785.dumps(stable)).hexdigest()
    payload = stable | {"receipt_sha256": digest}
    return httpx.Response(
        200,
        json=payload,
        headers={
            "X-VisionData-Gateway": "spring-webflux",
            "X-Content-SHA256": digest,
            "ETag": f'"{digest}"',
        },
        request=httpx.Request("GET", "http://127.0.0.1:49321" + path),
    )


def test_installed_resource_discovery_requires_packaged_exe_jre_and_jar(
    tmp_path: Path,
) -> None:
    tool = _load_tool()
    install = tmp_path / "installed"
    backend = install / "backend" / "visiondata-gate-backend.exe"
    java = install / "gateway" / "runtime" / "bin" / "java.exe"
    jar = install / "gateway" / "visiondata-gate-gateway.jar"
    for path in (backend, java, jar):
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(path.name.encode("ascii"))

    resources = tool.installed_runtime_resources(install)

    assert resources == {"backend": backend, "java": java, "gateway_jar": jar}


def test_expected_inference_backend_identity_matches_current_reviewed_source() -> None:
    tool = _load_tool()

    assert tool.EXPECTED_INFERENCE_BACKEND_SHA256 == hashlib.sha256(
        NORMALITY_SOURCE.read_bytes()
    ).hexdigest()


def test_governed_response_requires_gateway_and_valid_jcs_receipt() -> None:
    tool = _load_tool()
    response = _sealed_response(
        "/v1/projects/project-1/vision-capabilities",
        {"schema_version": "example.v1", "production_release_allowed": False},
    )

    payload = tool.governed_payload(response, expected_status=200)

    assert payload["production_release_allowed"] is False


def test_governed_response_rejects_gateway_bypass_and_receipt_drift() -> None:
    tool = _load_tool()
    bypass = _sealed_response("/v1/projects/project-1/vision-models", {"value": 1})
    del bypass.headers["X-VisionData-Gateway"]
    with pytest.raises(tool.SmokeError, match="GATEWAY_HEADER_REQUIRED"):
        tool.governed_payload(bypass, expected_status=200)

    drift = _sealed_response("/v1/projects/project-1/vision-models", {"value": 1})
    drift._content = drift.content.replace(b'"value":1', b'"value":2')
    with pytest.raises(tool.SmokeError, match="JCS_RECEIPT_INVALID"):
        tool.governed_payload(drift, expected_status=200)

    denied = httpx.Response(
        409,
        json={"error": {"code": "vision_model_hold", "message": "redacted"}},
        headers={"X-VisionData-Gateway": "spring-webflux"},
        request=httpx.Request(
            "POST", "http://127.0.0.1:49321/v1/projects/project-1/vision-model-packs"
        ),
    )
    with pytest.raises(
        tool.SmokeError,
        match="GOVERNED_HTTP_STATUS_409_vision_model_hold",
    ):
        tool.governed_payload(denied, expected_status=201)


def test_prediction_contract_binds_every_identity_and_score_semantics() -> None:
    tool = _load_tool()
    expected = {
        "model_pack_sha256": "1" * 64,
        "backbone_weights_sha256": "2" * 64,
        "source_binding_sha256": "3" * 64,
        "source_index_sha256": "4" * 64,
        "runtime_sha256": "5" * 64,
        "inference_backend_sha256": tool.EXPECTED_INFERENCE_BACKEND_SHA256,
        "image_sha256": "6" * 64,
    }
    inference = {
        **expected,
        "status": "COMPLETED_LOCAL_SANDBOX_INFERENCE",
        "image_score": 0.75,
        "image_threshold": 0.5,
        "predicted_anomaly": True,
        "production_release_allowed": False,
        "machine_write_permitted": False,
        "decision_scope": "MODEL_SIGNAL_ONLY_NOT_GATE_OR_PRODUCTION_DECISION",
        "gate_decision": "NOT_ISSUED",
        "heatmap": {"sha256": "7" * 64, "bytes": 100, "width": 64, "height": 64, "format": "png"},
    }

    tool.validate_inference(inference, expected)

    inference["predicted_anomaly"] = False
    with pytest.raises(tool.SmokeError, match="PREDICTION_SEMANTIC_MISMATCH"):
        tool.validate_inference(inference, expected)


def test_runtime_probe_distinguishes_executable_hash_from_environment_fingerprint() -> None:
    tool = _load_tool()
    executable_sha = "8" * 64
    runtime_sha = "9" * 64
    runtime = {
        "executable_sha256": executable_sha,
        "runtime_sha256": runtime_sha,
        "status": "PROBED",
        "probe": {
            "executable_sha256": executable_sha,
            "runtime_sha256": runtime_sha,
            "import_status": "PASSED",
        },
        "production_release_allowed": False,
        "machine_write_permitted": False,
    }

    assert tool.validate_runtime_probe(runtime, executable_sha) == runtime_sha


def test_receipt_is_self_sealed_redacted_and_new(tmp_path: Path) -> None:
    tool = _load_tool()
    output = tmp_path / "receipt.json"
    receipt = tool.write_public_receipt_new(
        output,
        {
            "schema_version": "visiondata-gate.installed-normality-http-smoke.v1",
            "status": "PASS_INSTALLED_NORMALITY_HTTP_SMOKE",
            "production_release_allowed": False,
        },
        forbidden_values=("desktop-secret-value",),
    )
    stable = {key: value for key, value in receipt.items() if key != "receipt_sha256"}
    assert receipt["receipt_sha256"] == hashlib.sha256(rfc8785.dumps(stable)).hexdigest()
    assert output.read_bytes() == rfc8785.dumps(receipt) + b"\n"

    with pytest.raises(tool.SmokeError, match="ABSOLUTE_PATH_IN_RECEIPT"):
        tool.write_public_receipt_new(
            tmp_path / "unsafe.json",
            {
                "schema_version": "unsafe.v1",
                "source": r"E:\private\model.pt",
            },
        )


def test_uninstall_completion_is_reused_from_installer_smoke() -> None:
    tool = _load_tool()

    helpers = tool.installer_uninstall_helpers()

    assert callable(helpers["find_uninstaller"])
    assert callable(helpers["wait_for_uninstall_completion"])
