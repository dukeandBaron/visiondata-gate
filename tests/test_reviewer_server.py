from __future__ import annotations

import json
from pathlib import Path

from fastapi.testclient import TestClient

from visiondata_gate.reviewer_server import (
    DEFAULT_RELEASE_ROOT,
    DEFAULT_SYNTHETIC_ROOT,
    build_reviewer_snapshot,
    create_reviewer_app,
)


def test_reviewer_snapshot_preserves_evidence_and_decision_boundaries() -> None:
    snapshot, before_path, after_path = build_reviewer_snapshot(
        release_root=DEFAULT_RELEASE_ROOT,
        synthetic_root=DEFAULT_SYNTHETIC_ROOT,
        environment={
            "VISIONDATA_INCIDENT_MODEL_BASE_URL": "https://gw.opentoken.io",
            "VISIONDATA_INCIDENT_MODEL_MODE": "off",
            "VISIONDATA_INCIDENT_MODEL_API_KEY": "",
        },
    )

    assert snapshot["mode"] == "READ_ONLY_REVIEWER"
    assert snapshot["public_pilot"]["fixed_image_denominator"] == 180
    assert snapshot["public_pilot"]["finding_count"] == 45
    assert snapshot["public_pilot"]["replan_count"] == 1
    assert snapshot["public_pilot"]["dynamic_worker_count"] == 3
    assert snapshot["public_pilot"]["actual_model_call_count"] == 0
    assert snapshot["case"]["parent"]["findings"] == 49
    assert snapshot["case"]["child"]["findings"] == 33
    assert snapshot["case"]["child"]["verified_closed"] == 6
    assert snapshot["case"]["child"]["open_responsibilities"] == 43
    assert snapshot["case"]["production_release_allowed"] is False
    assert snapshot["synthetic_visual"]["measurement"]["observed"] == 1.858528
    assert snapshot["synthetic_visual"]["measurement"]["minimum"] == 18.0
    assert snapshot["synthetic_visual"]["evidence_class"] == "synthetic_injected_truth"
    assert before_path.is_file()
    assert after_path.is_file()
    assert snapshot["external_model"] == {
        "provider_kind": "openai_compatible",
        "base_url": "https://gw.opentoken.io",
        "base_url_source": "environment",
        "provider_host": "gw.opentoken.io",
        "mode": "off",
        "key_configured": False,
        "connection_status": "NOT_CONFIGURED",
        "decision_authority": "none",
        "raw_key_exposed": False,
        "boundary": snapshot["external_model"]["boundary"],
    }
    serialized = json.dumps(snapshot, ensure_ascii=False)
    assert str(Path.cwd()) not in serialized
    assert "YOUR_API_KEY" not in serialized
    assert snapshot["snapshot_integrity"]["signature"] == "NOT_CONFIGURED"


def test_reviewer_snapshot_never_exposes_configured_api_key() -> None:
    secret = "test-secret-that-must-not-leave-the-process"
    snapshot, _, _ = build_reviewer_snapshot(
        release_root=DEFAULT_RELEASE_ROOT,
        synthetic_root=DEFAULT_SYNTHETIC_ROOT,
        environment={
            "VISIONDATA_INCIDENT_MODEL_BASE_URL": "https://gw.opentoken.io",
            "VISIONDATA_INCIDENT_MODEL_MODE": "gated",
            "VISIONDATA_INCIDENT_MODEL_API_KEY": secret,
        },
    )
    assert snapshot["external_model"]["key_configured"] is True
    assert snapshot["external_model"]["connection_status"] == "CONFIGURED_NOT_PROBED"
    assert secret not in json.dumps(snapshot, ensure_ascii=False)


def test_reviewer_snapshot_rejects_secret_bearing_provider_url() -> None:
    embedded_secret = "embedded-secret-that-must-not-leave-the-process"
    snapshot, _, _ = build_reviewer_snapshot(
        release_root=DEFAULT_RELEASE_ROOT,
        synthetic_root=DEFAULT_SYNTHETIC_ROOT,
        environment={
            "VISIONDATA_INCIDENT_MODEL_BASE_URL": (
                f"https://operator:{embedded_secret}@gw.opentoken.io/v1"
            ),
            "VISIONDATA_INCIDENT_MODEL_MODE": "gated",
            "VISIONDATA_INCIDENT_MODEL_API_KEY": "separate-fixture-key",
        },
    )

    serialized = json.dumps(snapshot, ensure_ascii=False)
    assert snapshot["external_model"]["base_url"] == ""
    assert snapshot["external_model"]["provider_host"] == ""
    assert snapshot["external_model"]["connection_status"] == "NOT_CONFIGURED"
    assert embedded_secret not in serialized
    assert "operator" not in serialized


def test_reviewer_server_is_read_only_and_security_headered(
    tmp_path: Path, monkeypatch: object
) -> None:
    frontend = tmp_path / "frontend"
    frontend.mkdir()
    (frontend / "index.html").write_text(
        "<!doctype html><title>Reviewer</title>", encoding="utf-8"
    )
    (frontend / "styles.css").write_text("body{}", encoding="utf-8")
    (frontend / "app.js").write_text(
        "document.body.dataset.ready='true';", encoding="utf-8"
    )
    monkeypatch.setenv("VISIONDATA_REVIEWER_FRONTEND_ROOT", str(frontend))
    monkeypatch.setenv("VISIONDATA_REVIEWER_RELEASE_ROOT", str(DEFAULT_RELEASE_ROOT))
    monkeypatch.setenv(
        "VISIONDATA_REVIEWER_SYNTHETIC_ROOT", str(DEFAULT_SYNTHETIC_ROOT)
    )
    monkeypatch.setenv("VISIONDATA_INCIDENT_MODEL_BASE_URL", "https://gw.opentoken.io")
    monkeypatch.setenv("VISIONDATA_INCIDENT_MODEL_MODE", "off")
    monkeypatch.delenv("VISIONDATA_INCIDENT_MODEL_API_KEY", raising=False)

    client = TestClient(create_reviewer_app())
    response = client.get("/api/reviewer/snapshot")
    assert response.status_code == 200
    assert response.json()["mode"] == "READ_ONLY_REVIEWER"
    assert response.headers["x-evidence-sha256"]
    assert "frame-ancestors 'none'" in response.headers["content-security-policy"]
    assert response.headers["x-content-type-options"] == "nosniff"
    assert client.get("/").status_code == 200
    assert client.get("/styles.css").status_code == 200
    assert client.get("/app.js").status_code == 200

    before = client.get("/api/reviewer/assets/before")
    assert before.status_code == 200
    assert before.headers["content-type"] == "image/png"
    assert before.headers["x-evidence-sha256"]

    health = client.get("/health")
    assert health.status_code == 200
    assert health.json()["submission_eligible"] is False
    assert client.post("/api/reviewer/snapshot").status_code == 405
    untrusted_host = client.get(
        "/health",
        headers={"host": "untrusted.invalid"},
    )
    assert untrusted_host.status_code == 400
