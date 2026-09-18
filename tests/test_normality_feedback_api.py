"""Real local PNG and persistent human-only Normality review API contracts."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
import struct
import zlib

import pytest
from fastapi import FastAPI, Header, HTTPException
from fastapi.responses import JSONResponse
from fastapi.testclient import TestClient
from PIL import Image

from visiondata_gate import local_model_registry as registry
from visiondata_gate import vision_model_api
from visiondata_gate.product_service import ProductService
from visiondata_gate.task_store import NotFoundError


OWNER_HEADERS = {"X-Test-Session": "synthetic-owner-session"}


@pytest.fixture
def vision_app(tmp_path):
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
    assert registry._seal(value) == value
    digest = value["receipt_sha256"]
    assert response.headers["etag"] == f'"{digest}"'
    assert response.headers["x-content-sha256"] == digest
    assert response.headers["cache-control"] == "private, no-store"
    return value


@pytest.fixture
def inference_fixture(vision_app):
    app, product, project_id = vision_app
    user, _workspace, _project = product.ensure_default_tenant()
    service = registry.LocalVisionModelService(product)
    service._authorize(user.user_id, project_id)
    identifier = "vision_inference_" + "a" * 24
    output = service.root / "inferences" / identifier
    heatmap = output / "artifacts" / "heatmap.png"
    heatmap.parent.mkdir(parents=True)
    Image.new("L", (64, 64), 127).save(heatmap)
    raw = heatmap.read_bytes()
    value = {
        "schema_version": "visiondata-gate.vision_inference.v1",
        "resource_id": identifier,
        "inference_id": identifier,
        "project_id": project_id,
        "model_id": "vision_model_" + "b" * 24,
        "asset_id": "vision_inference_asset_" + "c" * 24,
        "model_pack_sha256": "1" * 64,
        "image_sha256": "2" * 64,
        "status": "COMPLETED_LOCAL_SANDBOX_INFERENCE",
        "heatmap_artifact_id": "normality_heatmap_" + "d" * 24,
        "heatmap": {
            "sha256": hashlib.sha256(raw).hexdigest(),
            "bytes": len(raw),
            "width": 64,
            "height": 64,
            "format": "png",
        },
        "production_release_allowed": False,
        "machine_write_permitted": False,
        "evidence_origin": "SYNTHETIC_HTTP_CONTRACT_FIXTURE_NOT_MODEL_EXECUTION",
    }
    with product.store._connection(immediate=True) as conn:
        record = service._put(
            conn,
            value,
            "inference",
            {"output_root": str(output), "heatmap_path": str(heatmap)},
        )
    return app, product, user.user_id, project_id, record, heatmap, raw


def _route(fixture, suffix):
    return (
        f"/v1/projects/{fixture[3]}/vision-inferences/"
        f"{fixture[4]['inference_id']}/{suffix}"
    )


def _review(fixture, **changes):
    return {
        "request_key": "normality-review-0001",
        "reviewer_identity": "Named inspection reviewer",
        "note": "Inspected the actual heatmap; needs human follow-up only.",
        "expected_inference_sha256": fixture[4]["receipt_sha256"],
        "operator_attests_reviewed": True,
        "classification": "MODEL_SIGNAL_CONFIRMED",
    } | changes


def _change_private(fixture, **changes):
    with fixture[1].store._connection(immediate=True) as conn:
        row = conn.execute(
            "SELECT private_body FROM vision_records WHERE id=?",
            (fixture[4]["inference_id"],),
        ).fetchone()
        value = json.loads(row[0]) | changes
        conn.execute(
            "UPDATE vision_records SET private_body=? WHERE id=?",
            (json.dumps(value), fixture[4]["inference_id"]),
        )


def test_heatmap_is_real_png_with_strong_byte_identity(inference_fixture):
    app, _product, _actor, _project, record, _path, raw = inference_fixture
    with TestClient(app, client=("127.0.0.1", 50000)) as client:
        response = client.get(
            _route(inference_fixture, "heatmap"), headers=OWNER_HEADERS
        )
    assert response.status_code == 200, response.text
    assert response.content == raw
    assert response.content.startswith(b"\x89PNG\r\n\x1a\n")
    assert response.headers["content-type"] == "image/png"
    assert response.headers["content-length"] == str(len(raw))
    assert response.headers["etag"] == f'"{record["heatmap"]["sha256"]}"'
    assert response.headers["x-content-sha256"] == record["heatmap"]["sha256"]
    assert response.headers["cache-control"] == "private, no-store"
    assert response.headers["x-content-type-options"] == "nosniff"


@pytest.mark.parametrize("suffix", ["heatmap", "feedback"])
def test_reads_require_authentication_and_project_membership(inference_fixture, suffix):
    with TestClient(inference_fixture[0]) as client:
        path = _route(inference_fixture, suffix)
        assert client.get(path).status_code == 401
        assert (
            client.get(
                path, headers={"X-Test-Session": "synthetic-outsider-session"}
            ).status_code
            == 404
        )
        assert (
            client.get(
                path.replace(inference_fixture[3], "other-project"),
                headers=OWNER_HEADERS,
            ).status_code
            == 404
        )


@pytest.mark.parametrize(
    "mutation", ["bytes", "record", "outside_path", "other_path", "symlink"]
)
def test_heatmap_rejects_tamper_and_private_path_escape(
    inference_fixture, tmp_path, mutation
):
    app, product, _actor, _project, record, path, raw = inference_fixture
    if mutation == "bytes":
        path.write_bytes(b"tampered artifact")
    elif mutation == "record":
        with product.store._connection(immediate=True) as conn:
            changed = record | {"image_sha256": "9" * 64}
            conn.execute(
                "UPDATE vision_records SET body=? WHERE id=?",
                (json.dumps(changed), record["inference_id"]),
            )
    elif mutation in {"outside_path", "other_path"}:
        other = tmp_path / "private-secret-heatmap.png"
        if mutation == "other_path":
            other = path.parent / "unbound.png"
        other.write_bytes(raw)
        _change_private(inference_fixture, heatmap_path=str(other))
    else:
        other = tmp_path / "private-secret-heatmap.png"
        other.write_bytes(raw)
        path.unlink()
        try:
            path.symlink_to(other)
        except OSError:
            pytest.skip("local account does not allow symlink creation")
    with TestClient(app, raise_server_exceptions=False) as client:
        response = client.get(
            _route(inference_fixture, "heatmap"), headers=OWNER_HEADERS
        )
        outsider = client.get(
            _route(inference_fixture, "heatmap"),
            headers={"X-Test-Session": "synthetic-outsider-session"},
        )
    assert response.status_code == 409, response.text
    assert response.json()["error"]["code"] == "vision_model_hold"
    assert response.headers["cache-control"] == "private, no-store"
    assert "etag" not in response.headers
    assert str(tmp_path) not in response.text
    assert "private-secret" not in response.text
    assert outsider.status_code == 404


@pytest.mark.parametrize(
    "classification,followup",
    [
        ("MODEL_SIGNAL_CONFIRMED", "MODEL_SIGNAL_REVIEW"),
        ("LIKELY_FALSE_POSITIVE", "FALSE_POSITIVE_INVESTIGATION"),
        ("NEEDS_LABEL_REVIEW", "LABEL_REVIEW"),
        ("INSUFFICIENT_EVIDENCE", "EVIDENCE_COLLECTION"),
    ],
)
def test_named_review_is_persisted_hash_bound_and_idempotent(
    inference_fixture, classification, followup
):
    app, product, actor, project, inference, _path, _raw = inference_fixture
    request = _review(inference_fixture, classification=classification)
    operation = "review_normality_inference:" + inference["inference_id"]
    route = _route(inference_fixture, "feedback")
    with TestClient(app, client=("127.0.0.1", 50000)) as client:
        empty = _sealed(client.get(route, headers=OWNER_HEADERS))
        assert empty["schema_version"] == "visiondata-gate.vision-list.v1"
        assert empty["inference_id"] == inference["inference_id"]
        assert empty["items"] == []
        receipt = _sealed(client.post(route, headers=OWNER_HEADERS, json=request), 201)
        assert receipt["schema_version"] == "visiondata-gate.normality-feedback.v1"
        assert receipt["resource_id"] == receipt["feedback_id"]
        assert receipt["created_by"] == actor
        assert receipt["reviewer_identity"] == request["reviewer_identity"]
        assert receipt["note"] == request["note"]
        assert receipt["classification"] == classification
        assert receipt["followup_work_item_type"] == followup
        assert receipt["status"] == "RECORDED_FOR_HUMAN_FOLLOWUP"
        for field in (
            "project_id",
            "inference_id",
            "model_id",
            "asset_id",
            "image_sha256",
            "model_pack_sha256",
            "heatmap_artifact_id",
        ):
            assert receipt[field] == inference[field]
        assert receipt["inference_sha256"] == inference["receipt_sha256"]
        assert receipt["heatmap_sha256"] == inference["heatmap"]["sha256"]
        for field in (
            "followup_work_item_created",
            "issue_closed",
            "label_truth_authority",
            "training_ingestion_allowed",
            "production_release_allowed",
            "machine_write_permitted",
        ):
            assert receipt[field] is False
        assert (
            _sealed(client.post(route, headers=OWNER_HEADERS, json=request), 201)
            == receipt
        )
        assert (
            client.post(
                route,
                headers=OWNER_HEADERS,
                json=request | {"note": "Changed request under the same key."},
            ).status_code
            == 409
        )
        fetched = _sealed(client.get(route, headers=OWNER_HEADERS))
        assert fetched["items"] == [receipt]
        reconciled = _sealed(
            client.get(
                f"/v1/projects/{project}/vision-operations/{operation}/{request['request_key']}",
                headers=OWNER_HEADERS,
            )
        )
        assert reconciled["resource"] == receipt
        assert reconciled["auto_replayed"] is False
    # A fresh service reads durable SQL records, not a response-only side effect.
    fresh = registry.LocalVisionModelService(product)
    assert fresh.list_normality_feedback(actor, project, inference["inference_id"])[
        "items"
    ] == [receipt]
    assert fresh.get_inference(actor, project, inference["inference_id"]) == inference


@pytest.mark.parametrize(
    "changes,status",
    [
        ({"expected_inference_sha256": "0" * 64}, 409),
        ({"operator_attests_reviewed": False}, 422),
        ({"operator_attests_reviewed": 1}, 422),
        ({"classification": "LABEL_TRUTH"}, 422),
        ({"heatmap_path": "E:/private-secret.png"}, 422),
        ({"training_ingestion_allowed": True}, 422),
    ],
)
def test_review_contract_holds_do_not_create_feedback(
    inference_fixture, changes, status
):
    with TestClient(inference_fixture[0], client=("127.0.0.1", 50000)) as client:
        response = client.post(
            _route(inference_fixture, "feedback"),
            headers=OWNER_HEADERS,
            json=_review(inference_fixture, **changes),
        )
        assert response.status_code == status, response.text
        assert "private-secret" not in response.text
        assert (
            _sealed(
                client.get(_route(inference_fixture, "feedback"), headers=OWNER_HEADERS)
            )["items"]
            == []
        )


def test_review_rejects_changed_heatmap_before_persisting(inference_fixture):
    inference_fixture[5].write_bytes(b"changed after inspection")
    with TestClient(inference_fixture[0], client=("127.0.0.1", 50000)) as client:
        response = client.post(
            _route(inference_fixture, "feedback"),
            headers=OWNER_HEADERS,
            json=_review(inference_fixture),
        )
        assert response.status_code == 409
        assert (
            _sealed(
                client.get(_route(inference_fixture, "feedback"), headers=OWNER_HEADERS)
            )["items"]
            == []
        )


@pytest.mark.parametrize(
    "host,headers,status",
    [
        ("127.0.0.1", {}, 401),
        ("127.0.0.1", {"X-Test-Session": "synthetic-outsider-session"}, 404),
        ("203.0.113.8", OWNER_HEADERS, 403),
    ],
)
def test_review_requires_named_authorized_local_session(
    inference_fixture, host, headers, status
):
    with TestClient(inference_fixture[0], client=(host, 50000)) as client:
        response = client.post(
            _route(inference_fixture, "feedback"),
            headers=headers,
            json=_review(inference_fixture),
        )
    assert response.status_code == status, response.text


def test_feedback_request_export_matches_runtime_schema():
    schema = json.loads(
        (
            Path(__file__).resolve().parents[1]
            / "schemas/vision_model_requests.v1.json"
        ).read_text("utf-8")
    )
    assert "ReviewNormalityInference" in schema["requests"]
    assert (
        schema["requests"]["ReviewNormalityInference"]
        == registry.ReviewNormalityInference.model_json_schema()
    )


@pytest.mark.parametrize(
    "column,value", [("body", "not-json"), ("body", "null"), ("private_body", "[]")]
)
def test_malformed_registry_rows_fail_closed_without_path_leak(
    inference_fixture, column, value
):
    with inference_fixture[1].store._connection(immediate=True) as conn:
        conn.execute(
            f"UPDATE vision_records SET {column}=? WHERE id=?",
            (value, inference_fixture[4]["inference_id"]),
        )
    with TestClient(inference_fixture[0], raise_server_exceptions=False) as client:
        response = client.get(
            _route(inference_fixture, "heatmap"), headers=OWNER_HEADERS
        )
    assert response.status_code == 409, response.text
    assert response.json()["error"]["code"] == "vision_model_hold"
    assert response.headers["cache-control"] == "private, no-store"


def test_png_header_bomb_is_rejected_safely(inference_fixture):
    app, product, _actor, project, inference, path, raw = inference_fixture
    # Keep a valid PNG header CRC but claim an enormous image. The server must
    # reject it before the image parser allocates or raises an uncaught bomb error.
    ihdr = raw[12:16] + struct.pack(">II", 1000000, 1000000) + raw[24:29]
    crafted = raw[:12] + ihdr + struct.pack(">I", zlib.crc32(ihdr)) + raw[33:]
    path.write_bytes(crafted)
    service = registry.LocalVisionModelService(product)
    with product.store._connection(immediate=True) as conn:
        service._put(
            conn,
            inference
            | {
                "heatmap": inference["heatmap"]
                | {
                    "sha256": hashlib.sha256(crafted).hexdigest(),
                    "bytes": len(crafted),
                }
            },
            "inference",
            replace=True,
        )
    with TestClient(app, raise_server_exceptions=False) as client:
        response = client.get(
            _route(inference_fixture, "heatmap"), headers=OWNER_HEADERS
        )
    assert response.status_code == 409, response.text
    assert "etag" not in response.headers


@pytest.mark.parametrize("member", ["artifact", "parent"])
def test_windows_junction_or_reparse_artifact_is_rejected(
    inference_fixture, monkeypatch, member
):
    target = (
        inference_fixture[5] if member == "artifact" else inference_fixture[5].parent
    )
    actual = Path.is_junction
    monkeypatch.setattr(
        Path, "is_junction", lambda path: path == target or actual(path)
    )
    with TestClient(inference_fixture[0]) as client:
        response = client.get(
            _route(inference_fixture, "heatmap"), headers=OWNER_HEADERS
        )
    assert response.status_code == 409


def test_operation_reconciliation_is_actor_scoped_and_has_no_auto_replay(
    inference_fixture,
):
    from visiondata_gate.product_models import CreateUserRequest

    _app, product, actor, project, inference, _path, _raw = inference_fixture
    service = registry.LocalVisionModelService(product)
    request = registry.ReviewNormalityInference.model_validate(
        _review(inference_fixture)
    )
    reviewed = service.review_normality_inference(
        actor, project, inference["inference_id"], request
    )
    colleague = product.create_user(
        CreateUserRequest(display_name="Second named reviewer")
    )
    with product.store._connection(immediate=True) as conn:
        workspace = conn.execute(
            "SELECT workspace_id FROM projects WHERE project_id=?", (project,)
        ).fetchone()[0]
        conn.execute(
            "INSERT INTO workspace_members VALUES (?, ?, 'member', ?)",
            (workspace, colleague.user_id, registry._now()),
        )
    operation = "review_normality_inference:" + inference["inference_id"]
    with pytest.raises(NotFoundError):
        service.get_operation(
            colleague.user_id, project, operation, request.request_key
        )
    assert service.list_normality_feedback(
        colleague.user_id, project, inference["inference_id"]
    )["items"] == [reviewed]
    second = service.review_normality_inference(
        colleague.user_id, project, inference["inference_id"], request
    )
    assert second["feedback_id"] != reviewed["feedback_id"]
    assert second["created_by"] == colleague.user_id
    reopened = ProductService(product.product_root, recover_interrupted=False)
    try:
        persisted = registry.LocalVisionModelService(reopened).get_operation(
            actor,
            project,
            operation,
            request.request_key,
        )
        assert persisted["resource"] == reviewed
        assert persisted["auto_replayed"] is False
    finally:
        reopened.close(wait=True)


def test_png_chunk_crc_failure_is_a_safe_hold(inference_fixture):
    app, product, _actor, _project, inference, path, raw = inference_fixture
    offset = raw.index(b"IDAT")
    length = int.from_bytes(raw[offset - 4 : offset], "big")
    crc = offset + 4 + length
    crafted = raw[:crc] + bytes([raw[crc] ^ 255]) + raw[crc + 1 :]
    path.write_bytes(crafted)
    service = registry.LocalVisionModelService(product)
    with product.store._connection(immediate=True) as conn:
        service._put(
            conn,
            inference
            | {
                "heatmap": inference["heatmap"]
                | {
                    "sha256": hashlib.sha256(crafted).hexdigest(),
                }
            },
            "inference",
            replace=True,
        )
    with TestClient(app, raise_server_exceptions=False) as client:
        response = client.get(
            _route(inference_fixture, "heatmap"), headers=OWNER_HEADERS
        )
    assert response.status_code == 409, response.text
    assert response.json()["error"]["code"] == "vision_model_hold"
