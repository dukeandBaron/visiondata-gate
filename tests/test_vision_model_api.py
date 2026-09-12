"""HTTP authority and privacy contracts for optional local vision management."""

from __future__ import annotations

import hashlib
from pathlib import Path

import pytest
from fastapi import FastAPI, Header, HTTPException
from fastapi.responses import JSONResponse
from fastapi.testclient import TestClient
from starlette.requests import Request

from visiondata_gate import vision_model_api
from visiondata_gate.api import create_app
from visiondata_gate.audit_envelope import canonical_jcs_bytes
from visiondata_gate.local_model_registry import VisionModelError
from visiondata_gate.product_service import ProductService
from visiondata_gate.task_store import NotFoundError

GET_PATHS = (
    "vision-capabilities",
    "vision-models",
    "vision-models/model-missing",
    "vision-runtimes",
    "vision-datasets",
    "vision-training-runs",
    "vision-training-runs/run-missing",
    "vision-training-runs/run-missing/feedback",
    "vision-operations/register_model/request-key-missing",
)
POST_PATHS = (
    "vision-models",
    "vision-runtimes",
    "vision-runtimes/runtime-missing/probe",
    "vision-datasets",
    "vision-datasets/from-data-pool",
    "vision-training-runs",
    "vision-training-runs/run-missing/cancel",
    "vision-training-runs/run-missing/recover",
    "vision-training-runs/run-missing/selection",
    "vision-training-runs/run-missing/feedback/feedback-missing/triage",
)
OWNER_HEADERS = {"X-Test-Session": "synthetic-owner-session"}


@pytest.fixture
def vision_app(tmp_path: Path):
    product = ProductService(tmp_path / "product", recover_interrupted=False)
    user, _workspace, project = product.ensure_default_tenant()
    app = FastAPI()

    def actor(x_test_session: str | None = Header(default=None)) -> str:
        if x_test_session == "synthetic-owner-session":
            return user.user_id
        if x_test_session == "synthetic-outsider-session":
            return "unauthorized-outsider"
        raise HTTPException(status_code=401, detail="session required")

    @app.exception_handler(NotFoundError)
    def missing(_request, _error):
        return JSONResponse(status_code=404, content={"error": "not_found"})

    vision_model_api.install_vision_model_routes(app, actor, lambda: product)
    yield app, product, project.project_id
    product.close(wait=True)


def _sealed(response, expected_status=200):
    assert response.status_code == expected_status, response.text
    value = response.json()
    digest = hashlib.sha256(
        canonical_jcs_bytes(
            {key: item for key, item in value.items() if key != "receipt_sha256"}
        )
    ).hexdigest()
    assert value["receipt_sha256"] == digest
    assert response.headers["etag"] == f'"{digest}"'
    assert response.headers["x-content-sha256"] == digest
    assert response.headers["cache-control"] == "private, no-store"
    return value


def test_real_service_lists_are_sealed_and_project_scoped(vision_app):
    app, _product, project_id = vision_app
    with TestClient(app, client=("127.0.0.1", 50000)) as client:
        for name in (
            "vision-models",
            "vision-runtimes",
            "vision-datasets",
            "vision-training-runs",
        ):
            path = f"/v1/projects/{project_id}/{name}"
            result = _sealed(client.get(path, headers=OWNER_HEADERS))
            assert result["items"] == []
            assert (
                client.get(
                    path, headers={"X-Test-Session": "synthetic-outsider-session"}
                ).status_code
                == 404
            )
        _sealed(
            client.get(
                f"/v1/projects/{project_id}/vision-capabilities", headers=OWNER_HEADERS
            )
        )


def test_host_mount_uses_bound_session_and_rejects_actor_spoofing(
    vision_app, monkeypatch
):
    _app, product, project_id = vision_app
    token = "synthetic-vision-bound-session-token-over-32-characters"
    monkeypatch.setenv("VISIONDATA_INSECURE_TEST_ACTOR_HEADER_BYPASS", "false")
    monkeypatch.setenv("VISIONDATA_SESSION_TOKEN", token)
    monkeypatch.setenv("VISIONDATA_SESSION_ACTOR_USER_ID", "usr_local_demo")
    endpoint = f"/v1/projects/{project_id}/vision-capabilities"
    with TestClient(create_app(product), client=("127.0.0.1", 50000)) as client:
        assert client.get(endpoint).status_code == 401
        assert (
            client.get(
                endpoint, headers={"X-VisionData-Session-Token": "wrong"}
            ).status_code
            == 401
        )
        assert (
            client.get(
                endpoint,
                headers={
                    "X-VisionData-Session-Token": token,
                    "X-Actor-User-Id": "unauthorized-outsider",
                },
            ).status_code
            == 403
        )
        _sealed(client.get(endpoint, headers={"X-VisionData-Session-Token": token}))


def test_real_model_registration_hashes_without_loading_and_recovers_by_request_key(
    vision_app, tmp_path: Path
):
    app, _product, project_id = vision_app
    # Deliberately not a torch checkpoint: registration must never deserialize it.
    weights = tmp_path / "synthetic-private-weights.pt"
    weights.write_bytes(b"opaque synthetic checkpoint fixture\x00" * 257)
    digest = hashlib.sha256(weights.read_bytes()).hexdigest()
    payload = {
        "request_key": "register-model-http-0001",
        "reviewer_identity": "Synthetic model owner",
        "note": "Register authorized local fixture bytes without loading",
        "display_name": "Synthetic fixture model",
        "weights_path": str(weights),
        "expected_weights_sha256": digest,
        "task_type": "detect",
        "license_id": "TEST-FIXTURE-ONLY",
        "source_description": "Locally generated arbitrary bytes for registration test",
        "operator_attests_read_authorized": True,
    }
    base = f"/v1/projects/{project_id}"
    with TestClient(app, client=("127.0.0.1", 50000)) as client:
        response = client.post(
            base + "/vision-models", headers=OWNER_HEADERS, json=payload
        )
        model = _sealed(response, 201)
        assert model["weights_sha256"] == digest
        assert model["file_bytes"] == weights.stat().st_size
        assert model["status"] == "REGISTERED_NOT_LOADED"
        assert model["loaded"] is False
        assert model["production_release_allowed"] is False
        assert str(weights) not in response.text
        assert weights.name not in response.text
        assert (
            _sealed(
                client.post(
                    base + "/vision-models", headers=OWNER_HEADERS, json=payload
                ),
                201,
            )
            == model
        )
        model_path = base + "/vision-models/" + model["model_id"]
        assert _sealed(client.get(model_path, headers=OWNER_HEADERS)) == model
        listing = _sealed(client.get(base + "/vision-models", headers=OWNER_HEADERS))
        assert listing["items"] == [model]
        operation_path = (
            base + "/vision-operations/register_model/" + payload["request_key"]
        )
        operation = _sealed(client.get(operation_path, headers=OWNER_HEADERS))
        assert operation["resource"] == model
        assert operation["auto_replayed"] is False
        for path in (model_path, operation_path):
            assert (
                client.get(
                    path, headers={"X-Test-Session": "synthetic-outsider-session"}
                ).status_code
                == 404
            )
        assert (
            client.post(
                base + "/vision-models",
                headers=OWNER_HEADERS,
                json=payload | {"display_name": "Changed request under identical key"},
            ).status_code
            == 409
        )
        assert (
            client.post(
                base + "/vision-models",
                headers={"X-Test-Session": "synthetic-outsider-session"},
                json=payload | {"request_key": "outsider-registration-0001"},
            ).status_code
            == 404
        )


def test_changed_weights_cannot_be_registered_under_stale_digest(vision_app, tmp_path):
    app, _product, project_id = vision_app
    weights = tmp_path / "synthetic-private-stale.pt"
    weights.write_bytes(b"changed model bytes")
    payload = {
        "request_key": "register-stale-model-0001",
        "reviewer_identity": "Synthetic model owner",
        "note": "Attempt to register a fixture using an obsolete checksum",
        "display_name": "Changed fixture",
        "weights_path": str(weights),
        "expected_weights_sha256": hashlib.sha256(b"original model bytes").hexdigest(),
        "task_type": "detect",
        "license_id": "TEST-FIXTURE-ONLY",
        "source_description": "Local test fixture",
        "operator_attests_read_authorized": True,
    }
    base = f"/v1/projects/{project_id}"
    with TestClient(app, client=("127.0.0.1", 50000)) as client:
        response = client.post(
            base + "/vision-models", headers=OWNER_HEADERS, json=payload
        )
        assert response.status_code == 409
        assert "synthetic-private" not in response.text
        assert (
            _sealed(client.get(base + "/vision-models", headers=OWNER_HEADERS))["items"]
            == []
        )


def test_invalid_detection_manifest_returns_safe_contract_hold(vision_app, tmp_path):
    app, _product, project_id = vision_app
    payload = {
        "request_key": "register-invalid-detection-0001",
        "reviewer_identity": "Synthetic dataset reviewer",
        "note": "Explicit test of invalid detection data contract",
        "source_root": str(tmp_path),
        "manifest": {"private_path": "E:/synthetic-private/manifest-secret.json"},
        "expected_manifest_sha256": "0" * 64,
        "operator_attests_data_authorized": True,
    }
    with TestClient(
        app, client=("127.0.0.1", 50000), raise_server_exceptions=False
    ) as client:
        response = client.post(
            f"/v1/projects/{project_id}/vision-datasets",
            headers=OWNER_HEADERS,
            json=payload,
        )
    assert response.status_code == 409, response.text
    assert response.json()["error"]["code"] == "vision_model_hold"
    assert "synthetic-private" not in response.text


@pytest.mark.parametrize("path", GET_PATHS)
def test_all_get_routes_require_supplied_authentication(vision_app, path):
    app, _product, project_id = vision_app
    with TestClient(app, client=("127.0.0.1", 50000)) as client:
        response = client.get(
            f"/v1/projects/{project_id}/{path}",
            headers={"X-Actor-User-Id": "usr_local_demo"},
        )
    assert response.status_code == 401


@pytest.mark.parametrize("path", POST_PATHS)
def test_all_post_routes_require_supplied_authentication(vision_app, path):
    app, _product, project_id = vision_app
    with TestClient(app, client=("127.0.0.1", 50000)) as client:
        response = client.post(
            f"/v1/projects/{project_id}/{path}",
            headers={"X-Actor-User-Id": "usr_local_demo"},
            json={},
        )
    assert response.status_code == 401


@pytest.mark.parametrize("path", POST_PATHS)
def test_all_post_routes_reject_remote_peer_before_service_or_input_validation(
    vision_app, monkeypatch, path
):
    app, _product, project_id = vision_app

    def forbidden_service(_product):
        pytest.fail("a remote request reached the local vision service")

    monkeypatch.setattr(vision_model_api, "LocalVisionModelService", forbidden_service)
    with TestClient(app, client=("203.0.113.8", 50000)) as client:
        response = client.post(
            f"/v1/projects/{project_id}/{path}",
            headers=OWNER_HEADERS | {"X-Forwarded-For": "127.0.0.1"},
            json={"private_path": "E:/synthetic-private/secret.pt"},
        )
    assert response.status_code == 403
    assert response.headers["cache-control"] == "private, no-store"
    assert "synthetic-private" not in response.text


@pytest.mark.parametrize("host", ["127.0.0.1", "127.0.0.2", "::1", "::ffff:127.0.0.1"])
def test_literal_loopback_addresses_are_supported(host):
    request = Request({"type": "http", "client": (host, 50000)})
    vision_model_api._require_loopback(request)


@pytest.mark.parametrize(
    "host", ["testclient", "localhost", "0.0.0.0", "::", "10.0.0.8"]
)
def test_non_loopback_and_hostnames_fail_closed(host):
    request = Request({"type": "http", "client": (host, 50000)})
    with pytest.raises(HTTPException) as raised:
        vision_model_api._require_loopback(request)
    assert raised.value.status_code == 403


def test_absent_peer_fails_closed():
    with pytest.raises(HTTPException) as raised:
        vision_model_api._require_loopback(Request({"type": "http", "client": None}))
    assert raised.value.status_code == 403


def test_schema_errors_redact_inputs_without_host_exception_handler(vision_app):
    app, _product, project_id = vision_app
    with TestClient(app, client=("127.0.0.1", 50000)) as client:
        response = client.post(
            f"/v1/projects/{project_id}/vision-models",
            headers=OWNER_HEADERS,
            json={
                "local_path": "E:/synthetic-private/secret.pt",
                "arbitrary_command": "private-command-must-not-echo",
            },
        )
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "vision_request_invalid"
    assert response.headers["cache-control"] == "private, no-store"
    assert "synthetic-private" not in response.text
    assert "private-command" not in response.text


def test_vision_contract_error_does_not_echo_arbitrary_message_or_code(
    vision_app, monkeypatch
):
    app, _product, project_id = vision_app

    def fail(_product):
        error = VisionModelError("E:/synthetic-private/secret.pt was unavailable")
        error.code = "private-error-code-must-not-echo"
        raise error

    monkeypatch.setattr(vision_model_api, "LocalVisionModelService", fail)
    with TestClient(app, client=("127.0.0.1", 50000)) as client:
        response = client.get(
            f"/v1/projects/{project_id}/vision-capabilities", headers=OWNER_HEADERS
        )
    assert response.status_code == 409
    assert response.json()["error"]["code"] == "vision_model_hold"
    assert response.headers["cache-control"] == "private, no-store"
    assert "synthetic-private" not in response.text
    assert "private-error-code" not in response.text


@pytest.mark.parametrize("digest", [None, "invalid", "0" * 64])
def test_response_binding_rejects_missing_invalid_or_mismatched_seal(
    vision_app, monkeypatch, digest
):
    app, _product, project_id = vision_app

    class CorruptService:
        def __init__(self, _product):
            pass

        def capabilities(self, _actor, _project_id):
            return {"items": [], "receipt_sha256": digest}

    monkeypatch.setattr(vision_model_api, "LocalVisionModelService", CorruptService)
    with TestClient(app, client=("127.0.0.1", 50000)) as client:
        response = client.get(
            f"/v1/projects/{project_id}/vision-capabilities", headers=OWNER_HEADERS
        )
    assert response.status_code == 409
    assert "etag" not in response.headers


def test_installation_is_lazy_and_request_uses_injected_principal(monkeypatch):
    supplied_product = object()
    observations = []
    value = {"items": []}
    value["receipt_sha256"] = hashlib.sha256(canonical_jcs_bytes(value)).hexdigest()

    class ServiceProbe:
        def __init__(self, product):
            assert product is supplied_product
            observations.append("constructed")

        def list_models(self, actor, project_id):
            observations.append((actor, project_id))
            return value

    monkeypatch.setattr(vision_model_api, "LocalVisionModelService", ServiceProbe)
    app = FastAPI()
    vision_model_api.install_vision_model_routes(
        app, lambda: "injected-principal", lambda: supplied_product
    )
    assert observations == []
    with TestClient(app, client=("127.0.0.1", 50000)) as client:
        _sealed(
            client.get(
                "/v1/projects/project-probe/vision-models",
                headers={"X-Actor-User-Id": "forged-principal"},
            )
        )
        schema = client.get("/openapi.json").json()
    assert observations == ["constructed", ("injected-principal", "project-probe")]
    for name in (
        "RegisterVisionModel",
        "RegisterVisionRuntime",
        "ProbeVisionRuntime",
        "RegisterDetectionDataset",
        "RegisterPoolDetectionDataset",
        "CreateVisionTrainingRun",
        "VisionRunAction",
        "SelectVisionModel",
        "ReviewVisionFeedback",
    ):
        assert schema["components"]["schemas"][name]["additionalProperties"] is False
    create = schema["paths"]["/v1/projects/{project_id}/vision-training-runs"]["post"]
    assert "202" in create["responses"]
