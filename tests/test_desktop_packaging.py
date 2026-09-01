from __future__ import annotations

import ast
import os
from pathlib import Path

from fastapi.testclient import TestClient

from visiondata_gate.api import create_app
from visiondata_gate.desktop_backend import load_desktop_environment
from visiondata_gate.evaluation_evidence import (
    DEFAULT_V3_REPORT_PATH,
    DEFAULT_V4_REPORT_PATH,
    DYNAMICBENCH_V3_REPORT_NAME,
    DYNAMICBENCH_V4_REPORT_NAME,
    DynamicBenchEvaluationEvidenceSource,
    global_evaluation_evidence_scope,
)
from visiondata_gate.product_service import ProductService


PROJECT_ROOT = Path(__file__).resolve().parents[1]


def test_desktop_environment_loader_is_allowlisted_and_url_validated(
    tmp_path: Path, monkeypatch
) -> None:
    keys = {
        "VISIONDATA_INCIDENT_MODEL_BASE_URL",
        "VISIONDATA_INCIDENT_MODEL_ENDPOINT",
        "VISIONDATA_INCIDENT_MODEL_API_KEY",
        "VISIONDATA_PRODUCT_ROOT",
    }
    for key in keys:
        monkeypatch.delenv(key, raising=False)

    config = tmp_path / ".env.local"
    config.write_text(
        "\n".join(
            [
                "VISIONDATA_INCIDENT_MODEL_BASE_URL=https://gw.example.invalid",
                "VISIONDATA_INCIDENT_MODEL_ENDPOINT=credential-shaped-not-a-url",
                "VISIONDATA_INCIDENT_MODEL_API_KEY=local-test-credential",
                "VISIONDATA_PRODUCT_ROOT=C:/must-not-be-overridden",
                "UNRELATED_KEY=ignored",
            ]
        ),
        encoding="utf-8",
    )

    loaded = load_desktop_environment(config)

    assert loaded == (
        "VISIONDATA_INCIDENT_MODEL_BASE_URL",
        "VISIONDATA_INCIDENT_MODEL_API_KEY",
    )
    assert os.environ["VISIONDATA_INCIDENT_MODEL_BASE_URL"] == (
        "https://gw.example.invalid"
    )
    assert os.environ["VISIONDATA_INCIDENT_MODEL_API_KEY"] == ("local-test-credential")
    assert "VISIONDATA_INCIDENT_MODEL_ENDPOINT" not in os.environ
    assert "VISIONDATA_PRODUCT_ROOT" not in os.environ


def test_desktop_session_token_guards_local_api_and_shutdown(
    tmp_path: Path, monkeypatch
) -> None:
    token = "desktop-session-test-token-32-bytes-minimum"
    monkeypatch.setenv("VISIONDATA_DESKTOP_SESSION_TOKEN", token)
    monkeypatch.setenv("VISIONDATA_WEB_ORIGINS", "http://tauri.localhost")
    service = ProductService(tmp_path / "product", recover_interrupted=False)
    app = create_app(service, ensure_demo_tenant=True)
    shutdown_requested: list[bool] = []
    app.state.desktop_shutdown_callback = lambda: shutdown_requested.append(True)

    with TestClient(app) as client:
        assert client.get("/v1/health").status_code == 200

        assets_path = "/v1/operator-workspaces/wsp_local_demo/assets"
        actor_headers = {"X-Actor-User-Id": "usr_local_demo"}
        denied = client.get(assets_path, headers=actor_headers)
        assert denied.status_code == 401
        assert denied.json()["error"]["code"] == "local_session_required"

        allowed = client.get(
            assets_path,
            headers={
                **actor_headers,
                "X-VisionData-Desktop-Token": token,
            },
        )
        assert allowed.status_code == 200

        preflight = client.options(
            assets_path,
            headers={
                "Origin": "http://tauri.localhost",
                "Access-Control-Request-Method": "GET",
                "Access-Control-Request-Headers": (
                    "X-Actor-User-Id,X-VisionData-Desktop-Token"
                ),
            },
        )
        assert preflight.status_code == 200
        assert preflight.headers["access-control-allow-origin"] == (
            "http://tauri.localhost"
        )

        generic_session_cannot_shutdown = client.post(
            "/v1/desktop/shutdown",
            headers={"X-VisionData-Session-Token": token},
        )
        assert generic_session_cannot_shutdown.status_code == 403
        assert generic_session_cannot_shutdown.json()["error"]["code"] == (
            "desktop_session_required"
        )
        assert shutdown_requested == []

        shutdown = client.post(
            "/v1/desktop/shutdown",
            headers={"X-VisionData-Desktop-Token": token},
        )
        assert shutdown.status_code == 202
        assert shutdown.json() == {"status": "SHUTTING_DOWN"}
        assert shutdown_requested == [True]

    service.close(wait=True)


def test_generic_local_session_does_not_register_desktop_shutdown(
    tmp_path: Path, monkeypatch
) -> None:
    token = "generic-session-test-token-32-bytes-minimum"
    monkeypatch.setenv("VISIONDATA_SESSION_TOKEN", token)
    service = ProductService(tmp_path / "product", recover_interrupted=False)
    app = create_app(service, ensure_demo_tenant=True)
    shutdown_requested: list[bool] = []
    app.state.desktop_shutdown_callback = lambda: shutdown_requested.append(True)

    with TestClient(app) as client:
        response = client.post(
            "/v1/desktop/shutdown",
            headers={"X-VisionData-Session-Token": token},
        )
        assert response.status_code == 404
        assert shutdown_requested == []

    service.close(wait=True)


def test_desktop_dynamicbench_source_uses_the_bound_resource_root(
    tmp_path: Path, monkeypatch
) -> None:
    resource_root = tmp_path / "packaged-resources"
    reports_root = resource_root / "10_reports"
    reports_root.mkdir(parents=True)
    packaged_v3 = reports_root / DYNAMICBENCH_V3_REPORT_NAME
    packaged_v4 = reports_root / DYNAMICBENCH_V4_REPORT_NAME
    packaged_v3.write_bytes(DEFAULT_V3_REPORT_PATH.read_bytes())
    packaged_v4.write_bytes(DEFAULT_V4_REPORT_PATH.read_bytes())
    monkeypatch.setenv("VISIONDATA_RESOURCE_ROOT", str(resource_root))

    source = DynamicBenchEvaluationEvidenceSource()
    assert source.v3_report_path == packaged_v3
    assert source.v4_report_path == packaged_v4

    projection = source.project(scope=global_evaluation_evidence_scope())
    assert projection.status == "PASS_LOCAL_EVIDENCE"
    assert projection.verification_status == "VERIFIED"
    assert projection.pair_binding_status == "VERIFIED"
    assert {report.source_artifact_name for report in projection.reports} == {
        DYNAMICBENCH_V3_REPORT_NAME,
        DYNAMICBENCH_V4_REPORT_NAME,
    }
    assert projection.production_release_allowed is False
    assert projection.machine_write_permitted is False


def test_pyinstaller_spec_allowlists_only_the_two_runtime_reports() -> None:
    spec_path = PROJECT_ROOT / "desktop" / "visiondata_gate_backend.spec"
    source = spec_path.read_text(encoding="utf-8")
    tree = ast.parse(source, filename=str(spec_path))
    report_names_node = next(
        node.value
        for node in tree.body
        if isinstance(node, ast.Assign)
        and any(
            isinstance(target, ast.Name)
            and target.id == "FROZEN_EVALUATION_REPORT_NAMES"
            for target in node.targets
        )
    )
    report_names = ast.literal_eval(report_names_node)

    assert report_names == (
        DYNAMICBENCH_V3_REPORT_NAME,
        DYNAMICBENCH_V4_REPORT_NAME,
    )
    assert "*frozen_evaluation_report_datas" in source
    assert ".resolve(strict=True)" in source
    assert '(str(project_root / "10_reports"), "10_reports")' not in source
    assert {
        path.name
        for path in (PROJECT_ROOT / "10_reports").glob("DYNAMICBENCH_*.json")
        if path.name in source
    } == set(report_names)


def test_windows_build_runs_the_evidence_aware_packaged_sidecar_smoke() -> None:
    build_source = (PROJECT_ROOT / "build_windows_installer.ps1").read_text(
        encoding="utf-8"
    )
    smoke_source = (PROJECT_ROOT / "tools" / "smoke_windows_sidecar.py").read_text(
        encoding="utf-8"
    )

    assert "$BackendSmoke" in build_source
    assert "--executable $BackendExe" in build_source
    assert "--output $BackendSmokeReceipt" in build_source
    assert "/v1/review/evaluation-evidence/dynamicbench" in smoke_source
    assert "/v1/review/semifinal-demo-manifest" in smoke_source
    assert '"PASS_LOCAL_EVIDENCE"' in smoke_source
    assert '"PASS_LOCAL_DEMO_VERIFIED"' in smoke_source
    assert '"desktop_release_status": "NOT_CLAIMED"' in smoke_source
