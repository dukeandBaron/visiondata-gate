"""Real storage bridge contracts; synthetic inference evidence is not model execution."""

import hashlib
import importlib
import json
from io import BytesIO

import pytest
from fastapi import FastAPI, Header, HTTPException
from fastapi.responses import JSONResponse
from fastapi.testclient import TestClient
from PIL import Image

from visiondata_gate import local_model_registry as registry
from visiondata_gate.operator_workspace import (
    BoundingBoxAnnotation,
    OperatorImageStore,
    SaveAnnotationsRequest,
)
from visiondata_gate.product_service import ProductService
from visiondata_gate.task_store import NotFoundError
from visiondata_gate.vision_model_api import install_vision_model_routes


def _module():
    assert importlib.util.find_spec("visiondata_gate.normality_followup_service"), (
        "two-stage Normality followup service must exist"
    )
    return importlib.import_module("visiondata_gate.normality_followup_service")


@pytest.fixture
def setup(tmp_path):
    module = _module()
    product = ProductService(tmp_path / "product", recover_interrupted=False)
    user, workspace, project = product.ensure_default_tenant()
    actor, wid, pid = user.user_id, workspace.workspace_id, project.project_id
    store = OperatorImageStore(product.product_root / "operator_workspace")
    service = module.NormalityFollowupService(product, store)
    source = tmp_path / "synthetic.png"
    Image.new("RGB", (48, 32), (25, 50, 80)).save(source)
    asset = service.register_inference_asset(
        actor,
        pid,
        registry.RegisterVisionInferenceAsset(
            request_key="register-source-001",
            reviewer_identity="Named reviewer",
            note="Synthetic source for storage contract only.",
            display_name="Test image",
            image_path=str(source),
            expected_image_sha256=hashlib.sha256(source.read_bytes()).hexdigest(),
            operator_attests_read_authorized=True,
        ),
    )
    inference_id = "vision_inference_" + "a" * 24
    heatmap = service.root / "inferences" / inference_id / "artifacts" / "heatmap.png"
    heatmap.parent.mkdir(parents=True)
    Image.new("L", (64, 64), 100).save(heatmap)
    raw = heatmap.read_bytes()
    with product.store._connection(immediate=True) as conn:
        inference = service._put(
            conn,
            {
                "schema_version": "visiondata-gate.vision_inference.v1",
                "resource_id": inference_id,
                "inference_id": inference_id,
                "project_id": pid,
                "model_id": "vision_model_" + "b" * 24,
                "asset_id": asset["asset_id"],
                "image_sha256": asset["image_sha256"],
                "model_pack_sha256": "1" * 64,
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
            },
            "inference",
            {"output_root": str(heatmap.parent.parent), "heatmap_path": str(heatmap)},
        )
    feedback = service.review_normality_inference(
        actor,
        pid,
        inference_id,
        registry.ReviewNormalityInference(
            request_key="feedback-review-001",
            reviewer_identity="Named reviewer",
            note="Synthetic source requires human label review.",
            expected_inference_sha256=inference["receipt_sha256"],
            operator_attests_reviewed=True,
            classification="NEEDS_LABEL_REVIEW",
        ),
    )
    app = FastAPI()

    def actor_dep(x_test_actor: str | None = Header(default=None)):
        if x_test_actor is None:
            raise HTTPException(status_code=401)
        return x_test_actor

    @app.exception_handler(NotFoundError)
    def missing(_request, _error):
        return JSONResponse(status_code=404, content={"error": "not_found"})

    install_vision_model_routes(app, actor_dep, lambda: product)
    api = importlib.import_module("visiondata_gate.normality_followup_api")
    api.install_normality_followup_routes(
        app, actor_dep, lambda: product, lambda: store
    )
    with TestClient(
        app, client=("127.0.0.1", 50000), raise_server_exceptions=True
    ) as client:
        yield dict(
            module=module,
            product=product,
            actor=actor,
            workspace=wid,
            project=pid,
            store=store,
            service=service,
            asset=asset,
            inference=inference,
            feedback=feedback,
            client=client,
            headers={"X-Test-Actor": actor},
        )
    product.close(wait=True)


def _base(s):
    return (
        f"/v1/projects/{s['project']}/normality-feedback/{s['feedback']['feedback_id']}"
    )


def _request(s, **changes):
    return (
        dict(
            request_key="followup-import-001",
            reviewer_identity="Named reviewer",
            note="Import exact source for separate human annotation.",
            expected_feedback_sha256=s["feedback"]["receipt_sha256"],
            expected_inference_sha256=s["inference"]["receipt_sha256"],
            expected_asset_sha256=s["asset"]["receipt_sha256"],
            expected_image_sha256=s["asset"]["image_sha256"],
            operator_attests_import_authorized=True,
            operator_attests_no_label_or_training_authority=True,
        )
        | changes
    )


def _sealed(response, status=200):
    assert response.status_code == status, response.text
    value = response.json()
    assert registry._seal(value) == value
    assert response.headers["etag"] == f'"{value["receipt_sha256"]}"'
    assert response.headers["x-content-sha256"] == value["receipt_sha256"]
    assert response.headers["cache-control"] == "private, no-store"
    return value


def _import(s):
    return _sealed(
        s["client"].post(
            _base(s) + "/followup-import", headers=s["headers"], json=_request(s)
        ),
        201,
    )


def _annotate(s, imported, source="MANUAL"):
    return s["store"].save_annotations(
        s["actor"],
        s["workspace"],
        imported["operator_asset_id"],
        SaveAnnotationsRequest(
            expected_revision=0,
            annotations=[
                BoundingBoxAnnotation(
                    annotation_id="manual-box-1",
                    label="human review region",
                    x=0.1,
                    y=0.2,
                    width=0.3,
                    height=0.4,
                    source=source,
                )
            ],
        ),
    )


def _order_request(s, imported, annotation):
    value = _request(s)
    value.pop("operator_attests_import_authorized")
    return value | dict(
        request_key="followup-order-001",
        import_id=imported["import_id"],
        expected_import_sha256=imported["receipt_sha256"],
        annotation_id="manual-box-1",
        expected_annotation_revision=annotation.revision,
        expected_annotation_document_sha256=annotation.document_sha256,
        assignee="Named label reviewer",
        operator_attests_create_work_order=True,
        operator_attests_reviewed_evidence=True,
    )


def test_import_then_real_manual_order_and_sealed_readback(setup):
    s = setup
    imported = _import(s)
    assert imported["status"] == "ASSET_IMPORTED_AWAITING_HUMAN_ANNOTATION"
    assert imported["operator_asset_id"].startswith("img_")
    assert (
        s["store"]
        .get_annotations(s["actor"], s["workspace"], imported["operator_asset_id"])
        .revision
        == 0
    )
    assert s["store"].list_work_orders(s["actor"], s["workspace"]) == []
    assert _import(s) == imported
    annotation = _annotate(s, imported)
    projection = _sealed(
        s["client"].get(
            _base(s) + f"/followup-imports/{imported['import_id']}/annotations",
            headers=s["headers"],
        )
    )
    assert projection["document_sha256"] == annotation.document_sha256
    assert projection["annotations"][0]["source"] == "MANUAL"
    request = _order_request(s, imported, annotation)
    order = _sealed(
        s["client"].post(
            _base(s) + "/followup-work-orders", headers=s["headers"], json=request
        ),
        201,
    )
    assert order["status"] == "OPEN"
    actual = s["store"].get_work_order(
        s["actor"], s["workspace"], order["work_order_id"]
    )
    assert actual.status == "OPEN"
    assert actual.document_sha256 == order["work_order_document_sha256"]
    assert actual.crop_sha256 == order["crop_sha256"]
    assert actual.asset_sha256 == imported["image_sha256"]
    for record in (imported, order):
        for key in (
            "issue_closed",
            "label_truth_authority",
            "training_ingestion_allowed",
            "production_release_allowed",
            "machine_write_permitted",
            "annotation_created",
        ):
            assert record[key] is False
    listing = _sealed(s["client"].get(_base(s) + "/followup", headers=s["headers"]))
    assert listing["imports"] == [imported]
    assert listing["work_orders"] == [order]
    assert s["service"].list_normality_feedback(
        s["actor"], s["project"], s["inference"]["inference_id"]
    )["items"] == [s["feedback"]]
    assert (
        s["store"].get_annotations(
            s["actor"], s["workspace"], imported["operator_asset_id"]
        )
        == annotation
    )


@pytest.mark.parametrize(
    "field",
    [
        "expected_feedback_sha256",
        "expected_inference_sha256",
        "expected_asset_sha256",
        "expected_image_sha256",
    ],
)
def test_stale_receipt_prevents_import(setup, field):
    s = setup
    response = s["client"].post(
        _base(s) + "/followup-import",
        headers=s["headers"],
        json=_request(s, **{field: "0" * 64}),
    )
    assert response.status_code == 409
    assert s["store"].list_assets(s["actor"], s["workspace"]) == []


@pytest.mark.parametrize(
    "mutation",
    ["no_box", "imported", "revision", "document", "annotation_id", "assignee_blank"],
)
def test_work_order_requires_current_saved_manual_annotation(setup, mutation):
    s = setup
    imported = _import(s)
    if mutation == "no_box":
        annotation = s["store"].get_annotations(
            s["actor"], s["workspace"], imported["operator_asset_id"]
        )
    else:
        annotation = _annotate(
            s, imported, "IMPORTED" if mutation == "imported" else "MANUAL"
        )
    request = _order_request(s, imported, annotation)
    if mutation == "revision":
        request["expected_annotation_revision"] = 2
    if mutation == "document":
        request["expected_annotation_document_sha256"] = "0" * 64
    if mutation == "annotation_id":
        request["annotation_id"] = "missing-manual-box"
    if mutation == "assignee_blank":
        request["assignee"] = "   "
    assert s["client"].post(
        _base(s) + "/followup-work-orders", headers=s["headers"], json=request
    ).status_code in {409, 422}
    assert s["store"].list_work_orders(s["actor"], s["workspace"]) == []


def test_auth_scope_and_boolean_authority(setup):
    s = setup
    client, route = s["client"], _base(s) + "/followup-import"
    assert client.post(route, json=_request(s)).status_code == 401
    assert (
        client.post(
            route, headers={"X-Test-Actor": "outsider"}, json=_request(s)
        ).status_code
        == 404
    )
    assert (
        client.post(
            route.replace(s["project"], "other-project"),
            headers=s["headers"],
            json=_request(s),
        ).status_code
        == 404
    )
    for change in (
        {"operator_attests_import_authorized": 1},
        {"operator_asset_id": "img_injected"},
        {"workspace_id": "other"},
    ):
        assert (
            client.post(
                route, headers=s["headers"], json=_request(s, **change)
            ).status_code
            == 422
        )


@pytest.mark.parametrize("phase", ["import", "order"])
def test_fs_success_sql_loss_recovers_by_get_without_second_write(
    setup, monkeypatch, phase
):
    s = setup
    if phase == "order":
        imported = _import(s)
        request = _order_request(s, imported, _annotate(s, imported))
        suffix, operation = (
            "/followup-work-orders",
            "create_normality_followup_work_order:",
        )
        write_method = "create_work_order"
    else:
        request, suffix, operation = (
            _request(s),
            "/followup-import",
            "import_normality_followup:",
        )
        write_method = "add_image"
    original = s["module"].NormalityFollowupService._finish

    def fail(*args, **kwargs):
        raise OSError("synthetic process failure after filesystem success")

    monkeypatch.setattr(s["module"].NormalityFollowupService, "_finish", fail)
    assert (
        s["client"]
        .post(_base(s) + suffix, headers=s["headers"], json=request)
        .status_code
        == 503
    )
    monkeypatch.setattr(s["module"].NormalityFollowupService, "_finish", original)

    def no_write(*args, **kwargs):
        pytest.fail("GET reconciliation must never create another filesystem object")

    monkeypatch.setattr(s["store"], write_method, no_write)
    operation += s["feedback"]["feedback_id"]
    read = f"/v1/projects/{s['project']}/normality-followup-operations/{operation}/{request['request_key']}"
    recovered = _sealed(s["client"].get(read, headers=s["headers"]))
    assert recovered["auto_replayed"] is False
    assert (
        _sealed(
            s["client"].post(_base(s) + suffix, headers=s["headers"], json=request), 201
        )
        == recovered["resource"]
    )
    assert len(s["store"].list_assets(s["actor"], s["workspace"])) == 1
    assert len(s["store"].list_work_orders(s["actor"], s["workspace"])) == (
        1 if phase == "order" else 0
    )
    assert (
        s["client"]
        .post(
            _base(s) + suffix,
            headers=s["headers"],
            json=request | {"note": "Changed under original request key."},
        )
        .status_code
        == 409
    )


def test_internal_import_idempotency(tmp_path):
    store = OperatorImageStore(tmp_path / "operator")
    buffer = BytesIO()
    Image.new("RGB", (48, 32)).save(buffer, format="PNG")
    kwargs = dict(
        project_id="project-1",
        filename="source.png",
        data=buffer.getvalue(),
        _idempotency_token="a" * 64,
        _created_at="2026-09-19T00:00:00+00:00",
    )
    first = store.add_image("actor-1", "workspace-1", **kwargs)
    assert store.add_image("actor-1", "workspace-1", **kwargs) == first
    assert len(store.list_assets("actor-1", "workspace-1")) == 1


def test_host_mount_and_real_operator_http_visibility(setup):
    from visiondata_gate.api import create_app

    s = setup
    app = create_app(s["product"], ensure_demo_tenant=False)
    assert (
        "/v1/projects/{project_id}/normality-feedback/{feedback_id}/followup-import"
        in app.openapi()["paths"]
    )
    with TestClient(
        app, client=("127.0.0.1", 50000), headers={"X-Actor-User-Id": s["actor"]}
    ) as client:
        imported = _sealed(
            client.post(_base(s) + "/followup-import", json=_request(s)), 201
        )
        listing = client.get(
            f"/v1/operator-workspaces/{s['workspace']}/assets",
            params={"project_id": s["project"]},
        )
        assert listing.status_code == 200, listing.text
        item = next(
            item
            for item in listing.json()
            if item["asset_id"] == imported["operator_asset_id"]
        )
        assert (item["width"], item["height"]) == (48, 32)
        assert item["annotation_revision"] == 0 and item["annotation_count"] == 0
        image = client.get(item["source_url"])
        assert image.status_code == 200
        assert hashlib.sha256(image.content).hexdigest() == s["asset"]["image_sha256"]
        assert image.headers["x-content-sha256"] == s["asset"]["image_sha256"]


@pytest.mark.parametrize("orientation", [1, 6, 8])
def test_exif_identity_only(setup, tmp_path, orientation):
    s = setup
    source = tmp_path / "oriented.jpg"
    exif = Image.Exif()
    exif[274] = orientation
    Image.new("RGB", (48, 32)).save(source, exif=exif)
    raw = source.read_bytes()
    digest = hashlib.sha256(raw).hexdigest()
    cas = registry._cas_copy(s["service"].root, source, digest)
    asset = s["asset"] | {
        "image_sha256": digest,
        "image_bytes": len(raw),
        "format": "jpg",
    }
    with s["product"].store._connection(immediate=True) as conn:
        s["asset"] = s["service"]._put(conn, asset, "inference_asset", replace=True)
        conn.execute(
            "UPDATE vision_records SET private_body=? WHERE id=?",
            (json.dumps({"cas_path": str(cas)}), asset["asset_id"]),
        )
        s["inference"] = s["service"]._put(
            conn, s["inference"] | {"image_sha256": digest}, "inference", replace=True
        )
        s["feedback"] = s["service"]._put(
            conn,
            s["feedback"]
            | {
                "image_sha256": digest,
                "inference_sha256": s["inference"]["receipt_sha256"],
            },
            "normality_feedback",
            replace=True,
        )
    response = s["client"].post(
        _base(s) + "/followup-import", headers=s["headers"], json=_request(s)
    )
    if orientation == 1:
        imported = _sealed(response, 201)
        assert imported["coordinate_frame"] == "DECODED_PIXELS_EXIF_IDENTITY"
        actual, _ = s["store"]._asset(
            s["actor"], s["workspace"], imported["operator_asset_id"]
        )
        assert actual.original_name.endswith(".jpg")
    else:
        assert response.status_code == 409
        assert "normalized new asset" in response.text
        assert s["store"].list_assets(s["actor"], s["workspace"]) == []


@pytest.mark.parametrize(
    "mutation", ["bytes", "outside_cas", "classification", "operator_bytes", "crop"]
)
def test_live_readback_rejects_changed_source_or_storage(setup, tmp_path, mutation):
    s = setup
    if mutation in {"operator_bytes", "crop"}:
        imported = _import(s)
        if mutation == "operator_bytes":
            path, _, _ = s["store"].file_variant(
                s["actor"], s["workspace"], imported["operator_asset_id"], "source"
            )
            path.write_bytes(b"changed")
        else:
            request = _order_request(s, imported, _annotate(s, imported))
            order = _sealed(
                s["client"].post(
                    _base(s) + "/followup-work-orders",
                    headers=s["headers"],
                    json=request,
                ),
                201,
            )
            (
                s["store"].root
                / s["actor"]
                / s["workspace"]
                / "work_orders"
                / order["work_order_id"]
                / "crop.jpg"
            ).write_bytes(b"changed")
        response = s["client"].get(_base(s) + "/followup", headers=s["headers"])
    else:
        with s["product"].store._connection(immediate=True) as conn:
            if mutation == "classification":
                s["feedback"] = s["service"]._put(
                    conn,
                    s["feedback"] | {"classification": "MODEL_SIGNAL_CONFIRMED"},
                    "normality_feedback",
                    replace=True,
                )
            else:
                _, private = s["service"]._read(
                    conn, s["project"], s["asset"]["asset_id"]
                )
                if mutation == "bytes":
                    from pathlib import Path

                    Path(private["cas_path"]).write_bytes(b"changed")
                else:
                    secret = tmp_path / "private-secret.png"
                    Image.new("RGB", (48, 32)).save(secret)
                    conn.execute(
                        "UPDATE vision_records SET private_body=? WHERE id=?",
                        (json.dumps({"cas_path": str(secret)}), s["asset"]["asset_id"]),
                    )
        response = s["client"].post(
            _base(s) + "/followup-import", headers=s["headers"], json=_request(s)
        )
    assert response.status_code == 409
    assert str(tmp_path) not in response.text and "private-secret" not in response.text
    assert "etag" not in response.headers


def test_same_project_colleague_cannot_read_or_use_other_actor_import(setup):
    from visiondata_gate.product_models import CreateUserRequest

    s = setup
    imported = _import(s)
    annotation = _annotate(s, imported)
    colleague = s["product"].create_user(
        CreateUserRequest(display_name="Other named reviewer")
    )
    with s["product"].store._connection(immediate=True) as conn:
        conn.execute(
            "INSERT INTO workspace_members VALUES (?, ?, 'member', ?)",
            (s["workspace"], colleague.user_id, registry._now()),
        )
    headers = {"X-Test-Actor": colleague.user_id}
    listing = _sealed(s["client"].get(_base(s) + "/followup", headers=headers))
    assert listing["imports"] == [] and listing["work_orders"] == []
    assert (
        s["client"]
        .get(
            _base(s) + f"/followup-imports/{imported['import_id']}/annotations",
            headers=headers,
        )
        .status_code
        == 404
    )
    assert (
        s["client"]
        .post(
            _base(s) + "/followup-work-orders",
            headers=headers,
            json=_order_request(s, imported, annotation),
        )
        .status_code
        == 404
    )
    route = f"/v1/projects/{s['project']}/normality-followup-operations/import_normality_followup:{s['feedback']['feedback_id']}/followup-import-001"
    assert s["client"].get(route, headers=headers).status_code == 404


def test_pending_intent_get_never_executes_write(setup, monkeypatch):
    s = setup

    def interrupted(*args, **kwargs):
        raise OSError("process interrupted before creating image")

    monkeypatch.setattr(s["store"], "add_image", interrupted)
    assert (
        s["client"]
        .post(_base(s) + "/followup-import", headers=s["headers"], json=_request(s))
        .status_code
        == 503
    )

    def no_write(*args, **kwargs):
        pytest.fail("GET attempted to import a new asset")

    monkeypatch.setattr(s["store"], "add_image", no_write)
    route = f"/v1/projects/{s['project']}/normality-followup-operations/import_normality_followup:{s['feedback']['feedback_id']}/followup-import-001"
    assert s["client"].get(route, headers=s["headers"]).status_code == 404
    assert s["store"].list_assets(s["actor"], s["workspace"]) == []


def test_internal_import_recovers_partial_directory_without_duplicate(
    tmp_path, monkeypatch
):
    from visiondata_gate import operator_workspace as operator

    store = OperatorImageStore(tmp_path / "operator")
    buffer = BytesIO()
    Image.new("RGB", (48, 32)).save(buffer, format="PNG")
    kwargs = dict(
        project_id="project-1",
        filename="source.png",
        data=buffer.getvalue(),
        _idempotency_token="b" * 64,
        _created_at="2026-09-19T00:00:00+00:00",
    )
    original = operator._atomic_write

    def interrupt_preview(path, data, **options):
        if path.name == "preview.jpg":
            raise OSError("synthetic crash after source bytes")
        return original(path, data, **options)

    monkeypatch.setattr(operator, "_atomic_write", interrupt_preview)
    with pytest.raises(OSError):
        store.add_image("actor-1", "workspace-1", **kwargs)
    monkeypatch.setattr(operator, "_atomic_write", original)
    first = store.add_image("actor-1", "workspace-1", **kwargs)
    assert store.add_image("actor-1", "workspace-1", **kwargs) == first
    assert len(store.list_assets("actor-1", "workspace-1")) == 1


def test_followup_schema_export_matches_request_contracts():
    from pathlib import Path

    module = _module()
    path = (
        Path(__file__).resolve().parents[1]
        / "schemas"
        / "normality_followup_requests.v1.json"
    )
    assert path.is_file(), "followup request contracts must have an exported schema"
    value = json.loads(path.read_text(encoding="utf-8"))
    assert value["requests"] == {
        name: getattr(module, name).model_json_schema()
        for name in ("ImportNormalityFollowup", "CreateNormalityFollowupWorkOrder")
    }


def test_existing_intent_drift_stays_unknown(setup, monkeypatch):
    s = setup
    original = s["module"].NormalityFollowupService._finish

    def interrupted(*args, **kwargs):
        raise OSError("synthetic response gap")

    monkeypatch.setattr(s["module"].NormalityFollowupService, "_finish", interrupted)
    assert (
        s["client"]
        .post(_base(s) + "/followup-import", headers=s["headers"], json=_request(s))
        .status_code
        == 503
    )
    monkeypatch.setattr(s["module"].NormalityFollowupService, "_finish", original)
    with s["product"].store._connection(immediate=True) as conn:
        _, private = s["service"]._read(conn, s["project"], s["asset"]["asset_id"])
    from pathlib import Path

    Path(private["cas_path"]).write_bytes(b"changed after durable import")
    assert (
        s["client"]
        .post(_base(s) + "/followup-import", headers=s["headers"], json=_request(s))
        .status_code
        == 503
    )


def export_contract_fixture():
    """Generate public-only real HTTP/store receipts for independent Web validation."""
    from pathlib import Path
    from tempfile import TemporaryDirectory

    with TemporaryDirectory(prefix="normality-followup-contract-") as directory:
        fixtures = setup.__wrapped__(Path(directory))
        s = next(fixtures)
        try:
            imported = _import(s)
            annotation = _annotate(s, imported)
            request = _order_request(s, imported, annotation)
            order = _sealed(
                s["client"].post(
                    _base(s) + "/followup-work-orders",
                    headers=s["headers"],
                    json=request,
                ),
                201,
            )
            listing = _sealed(
                s["client"].get(_base(s) + "/followup", headers=s["headers"])
            )
            annotations = _sealed(
                s["client"].get(
                    _base(s) + f"/followup-imports/{imported['import_id']}/annotations",
                    headers=s["headers"],
                )
            )
            operations = {}
            for label, operation, key in (
                ("import", "import_normality_followup:", "followup-import-001"),
                (
                    "order",
                    "create_normality_followup_work_order:",
                    "followup-order-001",
                ),
            ):
                route = f"/v1/projects/{s['project']}/normality-followup-operations/{operation}{s['feedback']['feedback_id']}/{key}"
                operations[label] = _sealed(
                    s["client"].get(route, headers=s["headers"])
                )
            return {
                "evidence_origin": "SYNTHETIC_INFERENCE_REAL_SERVICE_DB_OPERATOR_STORE_HTTP_NOT_MODEL_EXECUTION",
                "scope": {
                    "actorUserId": s["actor"],
                    "workspaceId": s["workspace"],
                    "projectId": s["project"],
                },
                "feedback": s["feedback"],
                "inference": s["inference"],
                "asset": s["asset"],
                "import_request": _request(s),
                "order_request": request,
                "import": imported,
                "order": order,
                "list": listing,
                "annotations": annotations,
                "operations": operations,
            }
        finally:
            fixtures.close()


def test_internal_order_recovers_partial_files_and_remains_idempotent(setup, monkeypatch):
    from visiondata_gate import operator_workspace as operator

    s = setup
    imported = _import(s)
    annotation = _annotate(s, imported)
    request = operator.CreateOperatorWorkOrderRequest(annotation_id="manual-box-1",
        expected_annotation_revision=annotation.revision, assignee="Named reviewer",
        note="Synthetic storage recovery only.", operator_attests_reviewed_evidence=True)
    options = dict(_idempotency_token="c" * 64, _created_at="2026-09-19T00:00:00+00:00",
                   _expected_annotation_sha256=annotation.document_sha256)
    original = operator._atomic_write
    def interrupt_revision(path, data, **kwargs):
        if path.name == "rev_000001.json":
            raise OSError("synthetic crash after real crop")
        return original(path, data, **kwargs)
    monkeypatch.setattr(operator, "_atomic_write", interrupt_revision)
    with pytest.raises(OSError):
        s["store"].create_work_order(s["actor"], s["workspace"], imported["operator_asset_id"], request, **options)
    monkeypatch.setattr(operator, "_atomic_write", original)
    first = s["store"].create_work_order(s["actor"], s["workspace"], imported["operator_asset_id"], request, **options)
    assert s["store"].create_work_order(s["actor"], s["workspace"], imported["operator_asset_id"], request, **options) == first
    assert len(s["store"].list_work_orders(s["actor"], s["workspace"])) == 1
    assert s["store"].get_annotations(s["actor"], s["workspace"], imported["operator_asset_id"]) == annotation
