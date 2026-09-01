from __future__ import annotations

import base64
import hashlib
import io
import json
from pathlib import Path
import zipfile

import pytest
from PIL import Image
from fastapi.testclient import TestClient

from visiondata_gate.api import create_app
from visiondata_gate.annotation_roundtrip import (
    AnnotationImportPackage,
    AnnotationProvider,
    AnnotationRevision,
)
from visiondata_gate.product_models import (
    CreateProjectRequest,
    CreateTaskRequest,
    CreateUserRequest,
    CreateWorkspaceRequest,
    TaskExecutionStatus,
)
from visiondata_gate.product_service import ArtifactUnavailableError, ProductService


def test_real_runtime_is_reachable_through_product_service(tmp_path: Path) -> None:
    service = ProductService(tmp_path / "product", recover_interrupted=False)
    user = service.create_user(CreateUserRequest(display_name="E2E Operator"))
    workspace = service.create_workspace(
        CreateWorkspaceRequest(name="E2E Workspace", owner_user_id=user.user_id)
    )
    project = service.create_project(
        user.user_id,
        CreateProjectRequest(workspace_id=workspace.workspace_id, name="E2E Gate"),
    )
    task = service.create_task(
        user.user_id,
        CreateTaskRequest(
            project_id=project.project_id,
            goal="通过统一产品服务真实执行门禁、修复、复验和证据交付。",
            seed=20_260_809,
        ),
        auto_start=False,
    )

    completed = service.run_task_sync(task.task_id)
    assert completed.execution_status is TaskExecutionStatus.COMPLETED
    assert completed.initial_decision == "RECAPTURE"
    assert completed.final_decision == "PASS"
    assert completed.runtime_status == "success"
    assert completed.evidence_sha256
    assert service.trace_path(user.user_id, task.task_id).is_file()
    evidence_path = service.evidence_path(user.user_id, task.task_id)
    assert evidence_path.is_file()
    assert (
        completed.evidence_sha256
        == hashlib.sha256(evidence_path.read_bytes()).hexdigest()
    )
    with zipfile.ZipFile(evidence_path) as archive:
        assert "industrial_delivery_receipt.json" in archive.namelist()
        delivery = json.loads(archive.read("industrial_delivery_receipt.json"))
    assert delivery["task_id"] == task.task_id
    assert delivery["final_decision"] == "PASS"
    readiness = service.task_release_readiness(user.user_id, task.task_id)
    assert readiness.overall_status == "DEMO_ONLY"
    assert readiness.evidence_integrity == "VERIFIED"
    assert readiness.production_release_allowed is False
    events = service.list_events(user.user_id, task.task_id)
    assert len(events) >= 30
    assert any(event.phase == "verification" for event in events)

    export = service.create_annotation_export(
        user.user_id, task.task_id, AnnotationProvider.CVAT
    )
    export_again = service.create_annotation_export(
        user.user_id, task.task_id, AnnotationProvider.CVAT
    )
    assert export_again == export
    annotation_task = next(
        item for item in export.bundle.tasks if item.eligible_for_annotation_return
    )
    sample = next(
        item
        for item in export.bundle.samples
        if item.internal_sample_id in annotation_task.sample_ids
    )
    payload = io.BytesIO()
    Image.new("L", (128, 128), color=255).save(payload, format="PNG")
    package = AnnotationImportPackage(
        export_id=export.bundle.export_id,
        provider=export.bundle.provider,
        revisions=[
            AnnotationRevision(
                work_order_id=annotation_task.work_order_id,
                internal_sample_id=sample.internal_sample_id,
                external_sample_key=sample.external_sample_key,
                source_image_sha256=sample.image_sha256,
                prior_annotation_sha256=sample.prior_annotation_sha256,
                annotation_version="e2e-review-v2",
                annotation_content_base64=base64.b64encode(payload.getvalue()).decode(
                    "ascii"
                ),
            )
        ],
    )
    receipt = service.import_annotation_revisions(user.user_id, task.task_id, package)
    assert receipt.external_connected is False
    assert receipt.same_contract_recheck_performed is True
    assert receipt.accepted_revision_count == 1
    assert service.list_annotation_roundtrips(user.user_id, task.task_id) == [receipt]
    scorecard = service.acceptance_scorecard(user.user_id, task.task_id)
    assert scorecard.external_connections["cvat"] == (
        "local_contract_verified_not_connected"
    )
    assert any(
        item.key == "work_order_roundtrip_fidelity" and item.value == 1.0
        for item in scorecard.metrics
    )
    recheck_metric = next(
        item
        for item in scorecard.metrics
        if item.key == "annotation_recheck_gate_outcome"
    )
    assert recheck_metric.value == receipt.recheck_decision
    assert recheck_metric.status == (
        "PASS" if receipt.recheck_decision == "PASS" else "FAIL"
    )

    client = TestClient(
        create_app(service, ensure_demo_tenant=False),
        raise_server_exceptions=True,
    )
    headers = {"X-Actor-User-Id": user.user_id}
    api_export = client.post(
        f"/v1/tasks/{task.task_id}/annotation-exports/cvat", headers=headers
    )
    api_receipts = client.get(
        f"/v1/tasks/{task.task_id}/annotation-roundtrips", headers=headers
    )
    api_scorecard = client.get(
        f"/v1/tasks/{task.task_id}/acceptance-scorecard",
        headers=headers,
        params={"roundtrip_receipt_id": receipt.receipt_id},
    )
    assert api_export.status_code == 201
    assert api_export.json()["export_sha256"] == export.export_sha256
    assert api_receipts.status_code == 200
    assert [item["receipt_id"] for item in api_receipts.json()] == [receipt.receipt_id]
    assert api_scorecard.status_code == 200
    assert api_scorecard.json()["production_acceptance"] == "not_claimed"

    receipt_path = next(
        (tmp_path / "product" / "annotation_roundtrips").rglob("*.receipt.json")
    )
    receipt_path.write_bytes(receipt_path.read_bytes() + b" ")
    with pytest.raises(ArtifactUnavailableError, match="integrity"):
        service.list_annotation_roundtrips(user.user_id, task.task_id)
