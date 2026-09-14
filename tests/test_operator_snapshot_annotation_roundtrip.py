"""Real upload/snapshot tasks must reuse their frozen annotation context."""

from __future__ import annotations

import base64
import hashlib
from io import BytesIO
import json
from pathlib import Path
from typing import Iterator

from fastapi.testclient import TestClient
from PIL import Image
import pytest

from visiondata_gate.annotation_roundtrip import AnnotationExportRecord
from visiondata_gate.api import create_app
from visiondata_gate.contracts import BatchContract, BatchManifest, GateResult
from visiondata_gate.pipeline import compute_batch_digest
from visiondata_gate.product_models import (
    CreateTaskRequest,
    DataSourceKind,
    RevokeLocalSourceAuthorizationRequest,
    TaskExecutionStatus,
)
from visiondata_gate.product_service import ProductService


ACTOR = "usr_local_demo"
WORKSPACE = "wsp_local_demo"
HEADERS = {"X-Actor-User-Id": ACTOR}


def _png(size: tuple[int, int], mode: str = "RGB") -> bytes:
    buffer = BytesIO()
    Image.new(mode, size, 96).save(buffer, format="PNG")
    return buffer.getvalue()


@pytest.fixture
def uploaded_task(
    tmp_path: Path,
) -> Iterator[tuple[TestClient, ProductService, str, Path, dict]]:
    service = ProductService(tmp_path / "product", recover_interrupted=False)
    try:
        with TestClient(create_app(service, ensure_demo_tenant=True)) as client:
            project = client.post(
                "/v1/projects",
                headers=HEADERS,
                json={
                    "workspace_id": WORKSPACE,
                    "name": "Annotation return context regression",
                    "scenario_profile": "industrial",
                    "source_kind": "local_authorized_directory",
                },
            )
            assert project.status_code == 201, project.text
            project_id = project.json()["project_id"]
            # Mixed image dimensions produce a real mask-dimension work order.
            # The frozen contract is 48x32, deliberately not the 128x128 default.
            for index, size in enumerate(((48, 32), (64, 48))):
                upload = client.post(
                    f"/v1/operator-workspaces/{WORKSPACE}/assets",
                    params={"project_id": project_id},
                    headers=HEADERS,
                    files=[("files", (f"frame-{index}.png", _png(size), "image/png"))],
                )
                assert upload.status_code == 201, upload.text
                asset = upload.json()["assets"][0]
                saved = client.put(
                    f"/v1/operator-workspaces/{WORKSPACE}/assets/{asset['asset_id']}/annotations",
                    headers=HEADERS,
                    json={
                        "expected_revision": 0,
                        "annotations": [
                            {
                                "annotation_id": "manual-region",
                                "label": "review-region",
                                "x": 0.2,
                                "y": 0.2,
                                "width": 0.3,
                                "height": 0.3,
                            }
                        ],
                    },
                )
                assert saved.status_code == 200, saved.text
            snapshot = client.post(
                "/v1/data-sources/operator-project-snapshots",
                headers=HEADERS,
                json={
                    "workspace_id": WORKSPACE,
                    "project_id": project_id,
                    "display_name": "Frozen annotation return batch",
                    "operator_attests_authorized_use": True,
                },
            )
            assert snapshot.status_code == 201, snapshot.text
            source = snapshot.json()
            task = service.create_task(
                ACTOR,
                CreateTaskRequest(
                    project_id=project_id,
                    goal="Check the uploaded annotations under the frozen contract",
                    source_kind=DataSourceKind.LOCAL_AUTHORIZED_DIRECTORY,
                    source_id=source["source_id"],
                    plan_approval_required=False,
                    allowed_tools=["image_quality", "annotation_integrity"],
                ),
                auto_start=False,
            )
            completed = service.run_task_sync(task.task_id)
            assert completed.execution_status is TaskExecutionStatus.COMPLETED
            root = (
                service.product_root
                / "operator_project_snapshots"
                / source["data_profile"]["snapshot_id"]
            )
            yield client, service, task.task_id, root, source
    finally:
        service.close(wait=True)


def _export(
    client: TestClient, task_id: str, provider: str = "cvat"
) -> AnnotationExportRecord:
    response = client.post(
        f"/v1/tasks/{task_id}/annotation-exports/{provider}",
        headers=HEADERS,
    )
    assert response.status_code == 201, response.text
    return AnnotationExportRecord.model_validate(response.json())


def _returned_package(export: AnnotationExportRecord, size: tuple[int, int]) -> dict:
    work = next(
        item for item in export.bundle.tasks if item.eligible_for_annotation_return
    )
    sample = next(
        item
        for item in export.bundle.samples
        if item.internal_sample_id in work.sample_ids
    )
    return {
        "export_id": export.bundle.export_id,
        "provider": export.bundle.provider.value,
        "revisions": [
            {
                "work_order_id": work.work_order_id,
                "internal_sample_id": sample.internal_sample_id,
                "external_sample_key": sample.external_sample_key,
                "source_image_sha256": sample.image_sha256,
                "prior_annotation_sha256": sample.prior_annotation_sha256,
                "annotation_version": "manual-review-v2",
                "annotation_content_base64": base64.b64encode(_png(size, "L")).decode(
                    "ascii"
                ),
            }
        ],
    }


@pytest.mark.parametrize("provider", ["cvat", "fiftyone"])
def test_upload_annotation_export_uses_frozen_nondefault_contract(
    uploaded_task, provider
):
    client, service, task_id, root, _source = uploaded_task
    export = _export(client, task_id, provider)
    manifest = BatchManifest.model_validate_json(
        (root / "batch_manifest.json").read_bytes()
    )
    contract = BatchContract.model_validate_json(
        (root / "batch_contract.json").read_bytes()
    )
    gate = GateResult.model_validate(
        service.read_evidence_zip_json(ACTOR, task_id, "initial/gate_result.json")
    )
    assert contract.contract_id != BatchContract().contract_id
    assert export.bundle.contract_id == contract.contract_id == gate.contract_id
    assert export.bundle.source_input_sha256 == gate.input_sha256
    assert export.bundle.source_input_sha256 == compute_batch_digest(
        root / "batch", manifest, contract
    )
    assert export.bundle.external_connected is False
    assert any(item.eligible_for_annotation_return for item in export.bundle.tasks)
    assert _export(client, task_id, provider) == export


@pytest.mark.parametrize("provider", ["cvat", "fiftyone"])
def test_upload_mask_return_rechecks_frozen_contract_and_keeps_parent(
    uploaded_task, provider
):
    client, service, task_id, root, _source = uploaded_task
    contract = BatchContract.model_validate_json(
        (root / "batch_contract.json").read_bytes()
    )
    before = {
        p.relative_to(root).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest()
        for p in root.rglob("*")
        if p.is_file()
    }
    parent = service.get_task(ACTOR, task_id)
    export = _export(client, task_id, provider)
    package = _returned_package(
        export,
        (contract.thresholds.expected_width, contract.thresholds.expected_height),
    )
    response = client.post(
        f"/v1/tasks/{task_id}/annotation-imports", headers=HEADERS, json=package
    )
    assert response.status_code == 200, response.text
    receipt = response.json()
    assert receipt["accepted_revision_count"] == 1
    assert receipt["same_contract_recheck_performed"] is True
    assert receipt["recheck_contract_id"] == contract.contract_id
    assert receipt["original_input_unchanged"] is True
    assert receipt["external_connected"] is False
    # Fixing mask dimensions alone does not fix the remaining image problems.
    assert receipt["recheck_decision"] != "PASS"
    assert before == {
        p.relative_to(root).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest()
        for p in root.rglob("*")
        if p.is_file()
    }
    assert service.get_task(ACTOR, task_id).evidence_sha256 == parent.evidence_sha256
    assert len(service.list_annotation_roundtrips(ACTOR, task_id)) == 1
    assert (
        client.post(
            f"/v1/tasks/{task_id}/annotation-imports", headers=HEADERS, json=package
        ).json()
        == receipt
    )
    artifact = next(
        (service.product_root / "annotation_roundtrips").rglob(
            "recheck_gate_result.json"
        )
    )
    recheck = json.loads(artifact.read_text(encoding="utf-8"))
    assert recheck["contract_id"] == contract.contract_id
    assert (
        hashlib.sha256(artifact.read_bytes()).hexdigest()
        == receipt["recheck_gate_result_sha256"]
    )


def test_upload_return_rejects_default_contract_mask_size(uploaded_task):
    client, _service, task_id, _root, _source = uploaded_task
    export = _export(client, task_id)
    response = client.post(
        f"/v1/tasks/{task_id}/annotation-imports",
        headers=HEADERS,
        json=_returned_package(export, (128, 128)),
    )
    assert response.status_code == 200, response.text
    assert response.json()["accepted_revision_count"] == 0
    assert response.json()["same_contract_recheck_performed"] is False
    assert "annotation_dimensions_mismatch" in response.json()["checks"][0]["issues"]


@pytest.mark.parametrize(
    "member", ["batch_contract.json", "batch_manifest.json", "image", "evidence"]
)
def test_upload_return_rejects_frozen_input_tampering(uploaded_task, member):
    client, service, task_id, root, _source = uploaded_task
    export = _export(client, task_id)
    contract = BatchContract.model_validate_json(
        (root / "batch_contract.json").read_bytes()
    )
    if member == "evidence":
        target = service.evidence_path(ACTOR, task_id)
    elif member == "image":
        manifest = BatchManifest.model_validate_json(
            (root / "batch_manifest.json").read_bytes()
        )
        target = root / "batch" / manifest.samples[0].relative_path
    else:
        target = root / member
    target.write_bytes(target.read_bytes() + b" ")
    response = client.post(
        f"/v1/tasks/{task_id}/annotation-imports",
        headers=HEADERS,
        json=_returned_package(
            export,
            (contract.thresholds.expected_width, contract.thresholds.expected_height),
        ),
    )
    assert response.status_code == 409, response.text
    assert not list(
        (service.product_root / "annotation_roundtrips").rglob(
            "recheck_gate_result.json"
        )
    )


def test_upload_annotation_export_is_workspace_scoped(uploaded_task):
    client, _service, task_id, _root, _source = uploaded_task
    response = client.post(
        f"/v1/tasks/{task_id}/annotation-exports/cvat",
        headers={"X-Actor-User-Id": "usr_outside_workspace"},
    )
    assert response.status_code == 404, response.text


def test_upload_annotation_export_rejects_revoked_source(uploaded_task):
    client, service, task_id, _root, source = uploaded_task
    service.revoke_local_source_authorization(
        ACTOR,
        source["source_id"],
        RevokeLocalSourceAuthorizationRequest(
            reason="Stop annotation processing",
            expected_latest_event_sha256=service.list_source_authorization_events(
                ACTOR, source["source_id"]
            )[-1].event_sha256,
        ),
    )
    response = client.post(
        f"/v1/tasks/{task_id}/annotation-exports/cvat", headers=HEADERS
    )
    assert response.status_code == 409, response.text
