from __future__ import annotations

import hashlib
import json
from io import BytesIO
from pathlib import Path
from typing import Iterator

import pytest
from fastapi.testclient import TestClient
from PIL import Image

from visiondata_gate.api import create_app
from visiondata_gate.audit_envelope import canonical_jcs_bytes
from visiondata_gate.operator_workspace import StoredOperatorWorkOrderRevision
from visiondata_gate.product_service import ProductService


ACTOR = "usr_local_demo"
WORKSPACE = "wsp_local_demo"
HEADERS = {"X-Actor-User-Id": ACTOR}


@pytest.fixture
def operator_client(tmp_path: Path) -> Iterator[tuple[TestClient, ProductService]]:
    service = ProductService(tmp_path / "product", recover_interrupted=False)
    with TestClient(create_app(service, ensure_demo_tenant=True)) as client:
        yield client, service
    service.close(wait=True)


def _png_bytes(color: tuple[int, int, int] = (32, 96, 160)) -> bytes:
    image = Image.new("RGB", (48, 32), color)
    buffer = BytesIO()
    image.save(buffer, format="PNG")
    return buffer.getvalue()


def _upload(client: TestClient, data: bytes, name: str = "frame.png") -> dict:
    response = client.post(
        f"/v1/operator-workspaces/{WORKSPACE}/assets",
        headers=HEADERS,
        files=[("files", (name, data, "image/png"))],
    )
    assert response.status_code == 201, response.text
    payload = response.json()
    assert payload["uploaded_count"] == 1
    assert payload["raw_images_transmitted"] is False
    return payload["assets"][0]


def test_real_image_upload_is_exact_local_and_sha_bound(
    operator_client: tuple[TestClient, ProductService],
) -> None:
    client, service = operator_client
    data = _png_bytes()
    asset = _upload(client, data, "../camera-A/frame-001.png")

    assert asset["original_name"] == "frame-001.png"
    assert asset["format"] == "PNG"
    assert asset["content_type"] == "image/png"
    assert asset["width"] == 48
    assert asset["height"] == 32
    assert asset["source_sha256"] == hashlib.sha256(data).hexdigest()
    assert asset["local_only"] is True
    assert asset["external_transmission"] is False
    assert asset["inspection"]["sample_width"] == 48
    assert asset["inspection"]["sample_height"] == 32

    listing = client.get(f"/v1/operator-workspaces/{WORKSPACE}/assets", headers=HEADERS)
    assert listing.status_code == 200
    assert [item["asset_id"] for item in listing.json()] == [asset["asset_id"]]

    source = client.get(asset["source_url"], headers=HEADERS)
    assert source.status_code == 200
    assert source.content == data
    assert source.headers["x-content-sha256"] == asset["source_sha256"]

    preview = client.get(asset["preview_url"], headers=HEADERS)
    assert preview.status_code == 200
    assert preview.headers["content-type"].startswith("image/jpeg")
    assert preview.headers["x-content-sha256"] == asset["preview_sha256"]

    asset_root = (
        service.product_root
        / "operator_workspace"
        / ACTOR
        / WORKSPACE
        / asset["asset_id"]
    )
    assert len(list(asset_root.glob("source.*"))) == 1
    assert (
        hashlib.sha256(next(asset_root.glob("source.*")).read_bytes()).hexdigest()
        == asset["source_sha256"]
    )


def test_operator_assets_are_project_scoped_with_explicit_legacy_compatibility(
    operator_client: tuple[TestClient, ProductService],
) -> None:
    client, _service = operator_client
    legacy = _upload(client, _png_bytes((24, 48, 72)), "legacy-unassigned.png")
    project_response = client.post(
        "/v1/projects",
        headers=HEADERS,
        json={
            "workspace_id": WORKSPACE,
            "name": "Line 03 inspection",
            "description": "empty operator project",
            "scenario_profile": "industrial",
            "source_kind": "local_authorized_directory",
        },
    )
    assert project_response.status_code == 201, project_response.text
    project_id = project_response.json()["project_id"]

    scoped_upload = client.post(
        f"/v1/operator-workspaces/{WORKSPACE}/assets",
        params={"project_id": project_id},
        headers=HEADERS,
        files=[
            ("files", ("project-frame.png", _png_bytes((80, 90, 100)), "image/png"))
        ],
    )
    assert scoped_upload.status_code == 201, scoped_upload.text
    scoped_asset = scoped_upload.json()["assets"][0]
    assert scoped_asset["project_id"] == project_id

    project_listing = client.get(
        f"/v1/operator-workspaces/{WORKSPACE}/assets",
        params={"project_id": project_id},
        headers=HEADERS,
    )
    assert project_listing.status_code == 200
    assert [item["asset_id"] for item in project_listing.json()] == [
        scoped_asset["asset_id"]
    ]

    sample_listing = client.get(
        f"/v1/operator-workspaces/{WORKSPACE}/assets",
        params={
            "project_id": "prj_industrial_vision",
            "include_unassigned": "true",
        },
        headers=HEADERS,
    )
    assert sample_listing.status_code == 200
    assert [item["asset_id"] for item in sample_listing.json()] == [legacy["asset_id"]]


def test_invalid_images_and_cross_workspace_access_fail_closed(
    operator_client: tuple[TestClient, ProductService],
) -> None:
    client, _service = operator_client
    invalid = client.post(
        f"/v1/operator-workspaces/{WORKSPACE}/assets",
        headers=HEADERS,
        files=[("files", ("not-an-image.png", b"not an image", "image/png"))],
    )
    assert invalid.status_code == 415
    assert invalid.json()["error"]["code"] == "invalid_image"

    invisible = client.get(
        "/v1/operator-workspaces/wsp_not_visible/assets", headers=HEADERS
    )
    assert invisible.status_code == 404
    assert invisible.json()["error"]["code"] == "not_found"


def test_multi_image_upload_preflights_whole_batch_before_commit(
    operator_client: tuple[TestClient, ProductService],
) -> None:
    client, _service = operator_client
    before = client.get(
        f"/v1/operator-workspaces/{WORKSPACE}/assets",
        headers=HEADERS,
    )
    assert before.status_code == 200

    response = client.post(
        f"/v1/operator-workspaces/{WORKSPACE}/assets",
        headers=HEADERS,
        files=[
            ("files", ("valid-first.png", _png_bytes(), "image/png")),
            ("files", ("invalid-second.png", b"not an image", "image/png")),
        ],
    )

    assert response.status_code == 415
    assert response.json()["error"]["code"] == "invalid_image"
    after = client.get(
        f"/v1/operator-workspaces/{WORKSPACE}/assets",
        headers=HEADERS,
    )
    assert after.status_code == 200
    assert after.json() == before.json()


def test_duplicate_upload_is_visible_without_silently_deduplicating(
    operator_client: tuple[TestClient, ProductService],
) -> None:
    client, _service = operator_client
    data = _png_bytes((60, 80, 100))
    first = _upload(client, data, "camera-01.png")
    second = _upload(client, data, "camera-01-copy.png")

    assert first["asset_id"] != second["asset_id"]
    assert first["duplicate_of_asset_id"] is None
    assert second["duplicate_of_asset_id"] == first["asset_id"]
    assert second["source_sha256"] == first["source_sha256"]


def test_annotation_revisions_are_append_only_and_optimistic(
    operator_client: tuple[TestClient, ProductService],
) -> None:
    client, service = operator_client
    asset = _upload(client, _png_bytes(), "annotate.png")
    endpoint = (
        f"/v1/operator-workspaces/{WORKSPACE}/assets/{asset['asset_id']}/annotations"
    )

    empty = client.get(endpoint, headers=HEADERS)
    assert empty.status_code == 200
    assert empty.json()["revision"] == 0
    assert empty.json()["annotations"] == []

    annotation = {
        "annotation_id": "box_001",
        "label": "solder-bridge",
        "x": 0.1,
        "y": 0.2,
        "width": 0.3,
        "height": 0.25,
        "source": "MANUAL",
    }
    saved = client.put(
        endpoint,
        headers=HEADERS,
        json={"expected_revision": 0, "annotations": [annotation]},
    )
    assert saved.status_code == 200
    assert saved.json()["revision"] == 1
    assert saved.json()["annotations"] == [annotation]
    assert len(saved.json()["document_sha256"]) == 64

    loaded = client.get(endpoint, headers=HEADERS)
    assert loaded.json() == saved.json()
    revision_path = (
        service.product_root
        / "operator_workspace"
        / ACTOR
        / WORKSPACE
        / asset["asset_id"]
        / "annotations"
        / "rev_000001.json"
    )
    assert revision_path.is_file()
    assert (
        hashlib.sha256(revision_path.read_bytes()).hexdigest()
        == saved.json()["document_sha256"]
    )
    assert len(saved.json()["previous_revision_sha256"]) == 64
    assert len(saved.json()["revision_payload_sha256"]) == 64

    stale = client.put(
        endpoint,
        headers=HEADERS,
        json={"expected_revision": 0, "annotations": []},
    )
    assert stale.status_code == 409
    assert stale.json()["error"]["code"] == "annotation_revision_conflict"

    outside = client.put(
        endpoint,
        headers=HEADERS,
        json={
            "expected_revision": 1,
            "annotations": [
                {
                    **annotation,
                    "annotation_id": "box_outside",
                    "x": 0.9,
                    "width": 0.2,
                }
            ],
        },
    )
    assert outside.status_code == 422

    tampered_payload = json.loads(revision_path.read_text(encoding="utf-8"))
    tampered_payload["annotations"][0]["label"] = "tampered-label"
    revision_path.write_text(
        json.dumps(tampered_payload, ensure_ascii=False),
        encoding="utf-8",
    )
    tampered = client.get(endpoint, headers=HEADERS)
    assert tampered.status_code == 409
    assert tampered.json()["error"]["code"] == "annotation_chain_integrity_failed"


def test_operator_analysis_run_is_local_immutable_and_evidence_bound(
    operator_client: tuple[TestClient, ProductService],
) -> None:
    client, service = operator_client
    data = _png_bytes((20, 20, 20))
    first = _upload(client, data, "gear-analysis.png")
    duplicate = _upload(client, data, "gear-analysis-copy.png")
    annotation = {
        "annotation_id": "box_analysis_001",
        "label": "gear-tooth-review",
        "x": 0.1,
        "y": 0.2,
        "width": 0.3,
        "height": 0.25,
        "source": "MANUAL",
    }
    saved = client.put(
        (
            f"/v1/operator-workspaces/{WORKSPACE}/assets/"
            f"{duplicate['asset_id']}/annotations"
        ),
        headers=HEADERS,
        json={"expected_revision": 0, "annotations": [annotation]},
    )
    assert saved.status_code == 200

    endpoint = (
        f"/v1/operator-workspaces/{WORKSPACE}/assets/"
        f"{duplicate['asset_id']}/analysis-runs"
    )
    created = client.post(endpoint, headers=HEADERS)
    assert created.status_code == 201, created.text
    run = created.json()
    assert run["schema_version"] == "visiondata-gate.operator-analysis-run.v1"
    assert run["asset_id"] == duplicate["asset_id"]
    assert run["asset_sha256"] == hashlib.sha256(data).hexdigest()
    assert run["annotation_revision"] == 1
    assert run["annotation_document_sha256"] == saved.json()["document_sha256"]
    assert run["backend"] == "local-deterministic"
    assert run["model_call_count"] == 0
    assert run["tool_call_count"] == 5
    assert run["raw_images_transmitted"] is False
    assert run["workflow_status"] == "AWAITING_HUMAN_REVIEW"
    assert run["recommendation"]["code"] == "DUPLICATE_REVIEW"
    assert run["recommendation"]["decision_authority"] == "none"
    assert run["human_gate"]["production_authority"] == "human_only"
    assert len(run["events"]) == 9
    assert [event["sequence"] for event in run["events"]] == list(range(1, 10))
    assert all(len(event["receipt_sha256"]) == 64 for event in run["events"])
    assert any(
        first["asset_id"] in event["summary"]
        for event in run["events"]
        if event["action"] == "lookup_duplicate_ledger"
    )

    asset_root = (
        service.product_root
        / "operator_workspace"
        / ACTOR
        / WORKSPACE
        / duplicate["asset_id"]
    )
    trace_path = asset_root / "analysis_runs" / f"{run['analysis_run_id']}.json"
    assert trace_path.is_file()
    assert hashlib.sha256(trace_path.read_bytes()).hexdigest() == run["document_sha256"]
    assert (
        hashlib.sha256(next(asset_root.glob("source.*")).read_bytes()).hexdigest()
        == (duplicate["source_sha256"])
    )

    listed = client.get(endpoint, headers=HEADERS)
    assert listed.status_code == 200
    assert listed.json() == [run]

    copilot_endpoint = f"{endpoint}/{run['analysis_run_id']}/copilot-turns"
    duplicate_answer = client.post(
        copilot_endpoint,
        headers=HEADERS,
        json={"question": "这张图是否存在重复或泄漏风险？"},
    )
    assert duplicate_answer.status_code == 201, duplicate_answer.text
    first_turn = duplicate_answer.json()
    assert first_turn["answer_mode"] == "LOCAL_EVIDENCE_GROUNDED"
    assert first_turn["model_call_count"] == 0
    assert first["asset_id"] in first_turn["answer"]
    assert first_turn["raw_images_transmitted"] is False
    assert len(first_turn["document_sha256"]) == 64

    unsupported_answer = client.post(
        copilot_endpoint,
        headers=HEADERS,
        json={"question": "供应商是谁，之前有维修记录吗？"},
    )
    assert unsupported_answer.status_code == 201
    second_turn = unsupported_answer.json()
    assert "没有已授权" in second_turn["answer"]
    assert "不能回答" in second_turn["answer"]

    turns = client.get(copilot_endpoint, headers=HEADERS)
    assert turns.status_code == 200
    assert turns.json() == [first_turn, second_turn]
    turn_path = (
        asset_root
        / "copilot_turns"
        / run["analysis_run_id"]
        / f"{first_turn['turn_id']}.json"
    )
    assert (
        hashlib.sha256(turn_path.read_bytes()).hexdigest()
        == (first_turn["document_sha256"])
    )

    event_without_receipt = {
        key: value for key, value in run["events"][1].items() if key != "receipt_sha256"
    }
    assert (
        hashlib.sha256(canonical_jcs_bytes(event_without_receipt)).hexdigest()
        == (run["events"][1]["receipt_sha256"])
    )


def test_pixel_work_order_is_crop_bound_append_only_and_actionable(
    operator_client: tuple[TestClient, ProductService],
) -> None:
    client, service = operator_client
    asset = _upload(client, _png_bytes((90, 120, 150)), "gear-station-03.png")
    annotation = {
        "annotation_id": "box_gear_001",
        "label": "gear-tooth-defect",
        "x": 0.1,
        "y": 0.2,
        "width": 0.3,
        "height": 0.25,
        "source": "MANUAL",
    }
    annotations_endpoint = (
        f"/v1/operator-workspaces/{WORKSPACE}/assets/{asset['asset_id']}/annotations"
    )
    saved = client.put(
        annotations_endpoint,
        headers=HEADERS,
        json={"expected_revision": 0, "annotations": [annotation]},
    )
    assert saved.status_code == 200

    create_endpoint = (
        f"/v1/operator-workspaces/{WORKSPACE}/assets/{asset['asset_id']}/work-orders"
    )
    missing_attestation = client.post(
        create_endpoint,
        headers=HEADERS,
        json={
            "annotation_id": annotation["annotation_id"],
            "expected_annotation_revision": 1,
            "assignee": "Annotation Lead",
        },
    )
    assert missing_attestation.status_code == 422

    created = client.post(
        create_endpoint,
        headers=HEADERS,
        json={
            "annotation_id": annotation["annotation_id"],
            "expected_annotation_revision": 1,
            "assignee": "Annotation Lead",
            "note": "verify the shifted gear-tooth box",
            "operator_attests_reviewed_evidence": True,
        },
    )
    assert created.status_code == 201, created.text
    work_order = created.json()
    assert work_order["status"] == "OPEN"
    assert work_order["annotation"] == annotation
    assert work_order["annotation_revision"] == 1
    assert work_order["operator_attests_reviewed_evidence"] is True
    assert work_order["production_authority"] == "human_only"
    assert work_order["asset_sha256"] == asset["source_sha256"]
    assert work_order["pixel_bbox"] == {
        "x": 4,
        "y": 6,
        "width": 16,
        "height": 9,
    }
    assert len(work_order["crop_sha256"]) == 64
    assert len(work_order["document_sha256"]) == 64

    listing = client.get(
        f"/v1/operator-workspaces/{WORKSPACE}/work-orders", headers=HEADERS
    )
    assert listing.status_code == 200
    assert listing.json() == [work_order]

    crop = client.get(work_order["crop_url"], headers=HEADERS)
    assert crop.status_code == 200
    assert crop.headers["x-content-sha256"] == work_order["crop_sha256"]
    with Image.open(BytesIO(crop.content)) as crop_image:
        assert crop_image.size == (16, 9)

    update_endpoint = (
        f"/v1/operator-workspaces/{WORKSPACE}/work-orders/{work_order['work_order_id']}"
    )
    missing_transition_attestation = client.put(
        update_endpoint,
        headers=HEADERS,
        json={
            "expected_revision": 1,
            "status": "IN_CAPA",
            "assignee": "Annotation Lead",
            "note": "accepted into the local CAPA queue",
        },
    )
    assert missing_transition_attestation.status_code == 422

    false_transition_attestation = client.put(
        update_endpoint,
        headers=HEADERS,
        json={
            "expected_revision": 1,
            "status": "IN_CAPA",
            "assignee": "Annotation Lead",
            "note": "accepted into the local CAPA queue",
            "operator_attests_reviewed_evidence": False,
        },
    )
    assert false_transition_attestation.status_code == 422

    blank_transition_basis = client.put(
        update_endpoint,
        headers=HEADERS,
        json={
            "expected_revision": 1,
            "status": "IN_CAPA",
            "assignee": "Annotation Lead",
            "note": "   ",
            "operator_attests_reviewed_evidence": True,
        },
    )
    assert blank_transition_basis.status_code == 422
    unchanged_after_rejected_requests = client.get(
        f"/v1/operator-workspaces/{WORKSPACE}/work-orders", headers=HEADERS
    )
    assert unchanged_after_rejected_requests.status_code == 200
    assert unchanged_after_rejected_requests.json()[0]["revision"] == 1
    assert unchanged_after_rejected_requests.json()[0]["status"] == "OPEN"

    updated = client.put(
        update_endpoint,
        headers=HEADERS,
        json={
            "expected_revision": 1,
            "status": "IN_CAPA",
            "assignee": "Annotation Lead",
            "note": "accepted into the local CAPA queue",
            "operator_attests_reviewed_evidence": True,
        },
    )
    assert updated.status_code == 200
    assert updated.json()["revision"] == 2
    assert updated.json()["status"] == "IN_CAPA"
    assert updated.json()["assignee"] == "Annotation Lead"
    assert updated.json()["note"] == "accepted into the local CAPA queue"
    assert updated.json()["operator_attests_reviewed_evidence"] is True
    assert updated.json()["document_sha256"] != work_order["document_sha256"]

    stale = client.put(
        update_endpoint,
        headers=HEADERS,
        json={
            "expected_revision": 1,
            "status": "REJECTED",
            "assignee": "Local Operator",
            "note": "stale update must not win",
            "operator_attests_reviewed_evidence": True,
        },
    )
    assert stale.status_code == 409
    assert stale.json()["error"]["code"] == "work_order_revision_conflict"

    work_order_root = (
        service.product_root
        / "operator_workspace"
        / ACTOR
        / WORKSPACE
        / "work_orders"
        / work_order["work_order_id"]
    )
    assert sorted(
        path.name for path in (work_order_root / "revisions").glob("*.json")
    ) == [
        "rev_000001.json",
        "rev_000002.json",
    ]
    persisted_transition = json.loads(
        (work_order_root / "revisions" / "rev_000002.json").read_text(encoding="utf-8")
    )
    assert persisted_transition["assignee"] == "Annotation Lead"
    assert persisted_transition["note"] == "accepted into the local CAPA queue"
    assert persisted_transition["operator_attests_reviewed_evidence"] is True
    legacy_revision_payload = json.loads(
        (work_order_root / "revisions" / "rev_000001.json").read_text(encoding="utf-8")
    )
    legacy_revision_payload.pop("operator_attests_reviewed_evidence")
    legacy_revision = StoredOperatorWorkOrderRevision.model_validate(
        legacy_revision_payload
    )
    assert legacy_revision.operator_attests_reviewed_evidence is False
    assert (
        hashlib.sha256((work_order_root / "crop.jpg").read_bytes()).hexdigest()
        == work_order["crop_sha256"]
    )

    stale_annotation = client.post(
        create_endpoint,
        headers=HEADERS,
        json={
            "annotation_id": annotation["annotation_id"],
            "expected_annotation_revision": 2,
            "assignee": "Annotation Lead",
            "operator_attests_reviewed_evidence": True,
        },
    )
    assert stale_annotation.status_code == 409
    assert (
        stale_annotation.json()["error"]["code"]
        == "work_order_annotation_revision_conflict"
    )

    close_without_verification = client.put(
        update_endpoint,
        headers=HEADERS,
        json={
            "expected_revision": 2,
            "status": "CLOSED",
            "assignee": "Annotation Lead",
            "note": "closure requires a server-bound verification revision",
            "operator_attests_reviewed_evidence": True,
        },
    )
    assert close_without_verification.status_code == 422

    close_against_unchanged_revision = client.put(
        update_endpoint,
        headers=HEADERS,
        json={
            "expected_revision": 2,
            "status": "CLOSED",
            "assignee": "Annotation Lead",
            "note": "the original annotation revision cannot prove remediation",
            "operator_attests_reviewed_evidence": True,
            "verification_annotation_revision": 1,
            "verification_annotation_sha256": saved.json()["document_sha256"],
        },
    )
    assert close_against_unchanged_revision.status_code == 409
    assert (
        close_against_unchanged_revision.json()["error"]["code"]
        == "work_order_reverification_required"
    )

    remediated_annotation = {**annotation, "x": 0.15, "width": 0.25}
    verification = client.put(
        annotations_endpoint,
        headers=HEADERS,
        json={
            "expected_revision": 1,
            "annotations": [remediated_annotation],
        },
    )
    assert verification.status_code == 200
    assert verification.json()["revision"] == 2

    forged_verification = client.put(
        update_endpoint,
        headers=HEADERS,
        json={
            "expected_revision": 2,
            "status": "CLOSED",
            "assignee": "Annotation Lead",
            "note": "a forged digest must not close the work order",
            "operator_attests_reviewed_evidence": True,
            "verification_annotation_revision": 2,
            "verification_annotation_sha256": "f" * 64,
        },
    )
    assert forged_verification.status_code == 409
    assert (
        forged_verification.json()["error"]["code"]
        == "work_order_verification_binding_conflict"
    )

    closed = client.put(
        update_endpoint,
        headers=HEADERS,
        json={
            "expected_revision": 2,
            "status": "CLOSED",
            "assignee": "Annotation Lead",
            "note": "verified against the corrected annotation revision",
            "operator_attests_reviewed_evidence": True,
            "verification_annotation_revision": verification.json()["revision"],
            "verification_annotation_sha256": verification.json()["document_sha256"],
        },
    )
    assert closed.status_code == 200, closed.text
    assert closed.json()["status"] == "CLOSED"
    assert closed.json()["revision"] == 3
    assert closed.json()["verification_annotation_revision"] == 2
    assert (
        closed.json()["verification_annotation_sha256"]
        == verification.json()["document_sha256"]
    )
