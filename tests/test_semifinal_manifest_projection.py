from __future__ import annotations

import hashlib
import json
from pathlib import Path

from fastapi.testclient import TestClient
import pytest

from tools.prepare_semifinal_demo import prepare_demo
from visiondata_gate.api import create_app
from visiondata_gate.audit_envelope import canonical_jcs_bytes
from visiondata_gate.evidence import canonical_json_bytes
from visiondata_gate.product_service import ProductService


pytestmark = pytest.mark.tier_integration


def _rewrite_manifest(path: Path, payload: dict[str, object]) -> None:
    stable = {key: value for key, value in payload.items() if key != "manifest_sha256"}
    payload["manifest_sha256"] = hashlib.sha256(
        canonical_json_bytes(stable)
    ).hexdigest()
    path.write_bytes(canonical_json_bytes(payload))


def _projection_digest(payload: dict[str, object]) -> str:
    stable = {
        key: value for key, value in payload.items() if key != "projection_sha256"
    }
    return hashlib.sha256(canonical_jcs_bytes(stable)).hexdigest()


def test_semifinal_manifest_api_reverifies_product_state_and_seals_projection(
    tmp_path: Path,
) -> None:
    product_root = tmp_path / "product"
    prepared = prepare_demo(product_root)
    service = ProductService(product_root, recover_interrupted=False)
    try:
        client = TestClient(create_app(service, ensure_demo_tenant=False))
        response = client.get("/v1/review/semifinal-demo-manifest")

        assert response.status_code == 200
        projection = response.json()
        assert projection["status"] == "PASS_LOCAL_DEMO_VERIFIED"
        assert projection["availability"] == "AVAILABLE"
        assert projection["verification_status"] == "VERIFIED"
        assert projection["failure_code"] is None
        assert projection["manifest_sha256"] == prepared["manifest_sha256"]
        assert projection["projection_sha256"] == _projection_digest(projection)
        assert response.headers["etag"] == f'"{projection["projection_sha256"]}"'
        assert response.headers["x-content-sha256"] == projection["projection_sha256"]
        assert (
            response.headers["x-semifinal-manifest-sha256"]
            == prepared["manifest_sha256"]
        )
        assert response.headers["cache-control"] == "private, no-store"

        manifest = projection["manifest"]
        assert manifest["task_final_decision"] == "PASS"
        assert manifest["task_release_readiness_status"] == "DEMO_ONLY"
        assert (
            manifest["task_release_readiness_sha256"]
            == prepared["task_release_readiness_sha256"]
        )
        assert manifest["decision_kind"] == "CONTINUE_HOLD"
        assert manifest["child_incident_status"] == "INVESTIGATION_REQUIRED"
        assert manifest["child_incident_recommendation"] == "CONTINUE_HOLD"
        assert "product_root" not in manifest
        assert projection["product_root_exposed"] is False
        assert projection["production_release_allowed"] is False
        assert projection["machine_write_permitted"] is False
        assert projection["submission_eligible"] is False
        assert projection["customer_validation"] == "NOT_CLAIMED"
        assert (
            projection["factory_shadow_metrics"] == "NOT_MEASURED_PENDING_ADJUDICATION"
        )
        assert client.post("/v1/review/semifinal-demo-manifest").status_code == 405
    finally:
        service.close(wait=True)


def test_semifinal_manifest_api_returns_sha_bound_hold_when_manifest_is_missing(
    tmp_path: Path,
) -> None:
    service = ProductService(tmp_path / "product", recover_interrupted=False)
    try:
        client = TestClient(create_app(service, ensure_demo_tenant=False))
        response = client.get("/v1/review/semifinal-demo-manifest")

        assert response.status_code == 200
        projection = response.json()
        assert projection["status"] == "HOLD"
        assert projection["availability"] == "UNAVAILABLE"
        assert projection["verification_status"] == "FAILED_CLOSED"
        assert projection["failure_code"] == "MANIFEST_MISSING"
        assert projection["manifest"] is None
        assert projection["manifest_sha256"] is None
        assert projection["projection_sha256"] == _projection_digest(projection)
        assert "x-semifinal-manifest-sha256" not in response.headers
        assert response.headers["x-content-sha256"] == projection["projection_sha256"]
        assert projection["production_release_allowed"] is False
        assert projection["submission_eligible"] is False
    finally:
        service.close(wait=True)


def test_semifinal_manifest_api_rejects_duplicate_json_members(
    tmp_path: Path,
) -> None:
    product_root = tmp_path / "product"
    prepare_demo(product_root)
    manifest_path = product_root / "semifinal_demo_manifest.json"
    original = manifest_path.read_bytes()
    assert original.startswith(b"{")
    manifest_path.write_bytes(b'{"status":"ATTEMPTED_OVERRIDE",' + original[1:])
    # The standard decoder silently keeps the later, valid-looking member.
    assert json.loads(manifest_path.read_text(encoding="utf-8"))["status"] == (
        "PASS_LOCAL_DEMO_PREPARED"
    )

    service = ProductService(product_root, recover_interrupted=False)
    try:
        client = TestClient(create_app(service, ensure_demo_tenant=False))
        projection = client.get("/v1/review/semifinal-demo-manifest").json()

        assert projection["status"] == "HOLD"
        assert projection["failure_code"] == "MANIFEST_INVALID_JSON"
        assert projection["manifest"] is None
        assert projection["production_release_allowed"] is False
        assert projection["machine_write_permitted"] is False
        assert projection["submission_eligible"] is False
    finally:
        service.close(wait=True)


def test_semifinal_manifest_api_rejects_each_missing_browser_contract_field(
    tmp_path: Path,
) -> None:
    product_root = tmp_path / "product"
    original = prepare_demo(product_root)
    manifest_path = product_root / "semifinal_demo_manifest.json"
    service = ProductService(product_root, recover_interrupted=False)
    try:
        client = TestClient(create_app(service, ensure_demo_tenant=False))
        for field in (
            "task_final_decision",
            "task_release_readiness_status",
            "task_release_readiness_sha256",
            "decision_kind",
            "child_incident_status",
            "child_incident_recommendation",
        ):
            drifted = dict(original)
            drifted.pop(field)
            _rewrite_manifest(manifest_path, drifted)

            projection = client.get("/v1/review/semifinal-demo-manifest").json()
            assert projection["status"] == "HOLD", field
            assert projection["failure_code"] == "MANIFEST_CONTRACT_INVALID", field
            assert projection["manifest"] is None, field

        _rewrite_manifest(manifest_path, dict(original))
        restored = client.get("/v1/review/semifinal-demo-manifest").json()
        assert restored["status"] == "PASS_LOCAL_DEMO_VERIFIED"
    finally:
        service.close(wait=True)


def test_semifinal_manifest_api_rejects_self_resealed_claim_and_product_drift(
    tmp_path: Path,
) -> None:
    product_root = tmp_path / "product"
    original = prepare_demo(product_root)
    manifest_path = product_root / "semifinal_demo_manifest.json"
    service = ProductService(product_root, recover_interrupted=False)
    try:
        client = TestClient(create_app(service, ensure_demo_tenant=False))

        extra_claim = {**original, "factory_validated": True}
        _rewrite_manifest(manifest_path, extra_claim)
        claim_response = client.get("/v1/review/semifinal-demo-manifest").json()
        assert claim_response["status"] == "HOLD"
        assert claim_response["failure_code"] == "MANIFEST_CONTRACT_INVALID"

        ledger_drift = {**original, "event_count": int(original["event_count"]) + 1}
        _rewrite_manifest(manifest_path, ledger_drift)
        state_response = client.get("/v1/review/semifinal-demo-manifest").json()
        assert state_response["status"] == "HOLD"
        assert state_response["failure_code"] == "PRODUCT_STATE_INVALID"
        assert state_response["manifest"] is None
        assert state_response["production_release_allowed"] is False
        assert state_response["submission_eligible"] is False
    finally:
        service.close(wait=True)
