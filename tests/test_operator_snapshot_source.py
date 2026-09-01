from __future__ import annotations

import hashlib
from io import BytesIO
import json
from pathlib import Path
from typing import Iterator
import zipfile

import pytest
from fastapi.testclient import TestClient
from PIL import Image

from visiondata_gate.api import create_app
from visiondata_gate.capa import (
    ApproveRemediationPlanRequest,
    ExecuteRemediationPlanRequest,
    SelectRemediationPlanRequest,
)
from visiondata_gate.product_models import (
    CreateTaskRequest,
    DataSourceKind,
    TaskExecutionStatus,
)
from visiondata_gate.product_service import ProductService


ACTOR = "usr_local_demo"
WORKSPACE = "wsp_local_demo"
HEADERS = {"X-Actor-User-Id": ACTOR}


@pytest.fixture
def snapshot_client(tmp_path: Path) -> Iterator[tuple[TestClient, ProductService]]:
    service = ProductService(tmp_path / "product", recover_interrupted=False)
    with TestClient(create_app(service, ensure_demo_tenant=True)) as client:
        yield client, service
    service.close(wait=True)


def _png_bytes() -> bytes:
    image = Image.new("RGB", (48, 32), (32, 96, 160))
    buffer = BytesIO()
    image.save(buffer, format="PNG")
    return buffer.getvalue()


def _create_project_asset_and_annotation(client: TestClient) -> tuple[str, dict, dict]:
    project = client.post(
        "/v1/projects",
        headers=HEADERS,
        json={
            "workspace_id": WORKSPACE,
            "name": "Operator snapshot project",
            "description": "server-derived immutable task source",
            "scenario_profile": "industrial",
            "source_kind": "local_authorized_directory",
        },
    )
    assert project.status_code == 201, project.text
    project_id = project.json()["project_id"]
    upload = client.post(
        f"/v1/operator-workspaces/{WORKSPACE}/assets",
        params={"project_id": project_id},
        headers=HEADERS,
        files=[("files", ("frame.png", _png_bytes(), "image/png"))],
    )
    assert upload.status_code == 201, upload.text
    asset = upload.json()["assets"][0]
    annotation = client.put(
        f"/v1/operator-workspaces/{WORKSPACE}/assets/{asset['asset_id']}/annotations",
        headers=HEADERS,
        json={
            "expected_revision": 0,
            "annotations": [
                {
                    "annotation_id": "bbox-1",
                    "label": "weld-defect",
                    "x": 0.2,
                    "y": 0.25,
                    "width": 0.3,
                    "height": 0.4,
                    "source": "MANUAL",
                }
            ],
        },
    )
    assert annotation.status_code == 200, annotation.text
    return project_id, asset, annotation.json()


def _snapshot(client: TestClient, project_id: str) -> dict:
    response = client.post(
        "/v1/data-sources/operator-project-snapshots",
        headers=HEADERS,
        json={
            "workspace_id": WORKSPACE,
            "project_id": project_id,
            "display_name": "Line A frozen workbook",
            "operator_attests_authorized_use": True,
        },
    )
    assert response.status_code == 201, response.text
    return response.json()


def _complete_visual_snapshot_task(
    client: TestClient,
    service: ProductService,
) -> tuple[str, dict, dict]:
    project_id, asset, _annotation = _create_project_asset_and_annotation(client)
    source = _snapshot(client, project_id)
    task = service.create_task(
        ACTOR,
        CreateTaskRequest(
            project_id=project_id,
            goal="核验冻结工作簿图像、标注和确定性测量并生成只读视觉证据",
            source_kind=DataSourceKind.LOCAL_AUTHORIZED_DIRECTORY,
            source_id=source["source_id"],
            plan_approval_required=False,
            allowed_tools=[
                "image_quality",
                "duplicate_leakage",
                "annotation_integrity",
                "coverage_matrix",
            ],
        ),
        idempotency_key="operator-snapshot-visual-evidence-001",
        auto_start=False,
    )
    completed = service.run_task_sync(task.task_id)
    assert completed.execution_status is TaskExecutionStatus.COMPLETED
    return task.task_id, source, asset


def test_snapshot_task_binds_server_verified_asset_annotation_and_plan_preflight(
    snapshot_client: tuple[TestClient, ProductService],
) -> None:
    client, service = snapshot_client
    project_id, asset, annotation = _create_project_asset_and_annotation(client)
    source = _snapshot(client, project_id)

    assert source["adapter_kind"] == "operator_project_snapshot"
    profile = source["data_profile"]
    assert profile["workspace_id"] == WORKSPACE
    assert profile["project_id"] == project_id
    assert profile["actor_id"] == ACTOR
    assert profile["asset_count"] == 1
    assert profile["source_assets_copied_into_product"] is True
    assert profile["raw_images_transmitted"] is False
    assert len(profile["operator_snapshot_receipt_sha256"]) == 64

    snapshot_root = (
        service.product_root / "operator_project_snapshots" / profile["snapshot_id"]
    )
    receipt = json.loads(
        (snapshot_root / "operator_project_snapshot_receipt.json").read_text(
            encoding="utf-8"
        )
    )
    frozen_asset = receipt["assets"][0]
    assert frozen_asset["asset_id"] == asset["asset_id"]
    assert frozen_asset["source_sha256"] == asset["source_sha256"]
    assert frozen_asset["preview_sha256"] == asset["preview_sha256"]
    assert frozen_asset["annotation_revision"] == annotation["revision"] == 1
    assert frozen_asset["annotation_document_sha256"] == annotation["document_sha256"]

    task = client.post(
        "/v1/tasks",
        headers=HEADERS,
        json={
            "project_id": project_id,
            "goal": "审核当前工作簿冻结快照并生成可追溯门禁裁决",
            "source_kind": "local_authorized_directory",
            "source_id": source["source_id"],
            "plan_approval_required": True,
            "allowed_tools": [
                "image_quality",
                "duplicate_leakage",
                "annotation_integrity",
                "coverage_matrix",
            ],
        },
    )
    assert task.status_code == 202, task.text
    task_id = task.json()["task_id"]
    plan = client.get(f"/v1/tasks/{task_id}/plan", headers=HEADERS)
    assert plan.status_code == 200, plan.text
    assert plan.json()["source_id"] == source["source_id"]
    assert (
        plan.json()["source_binding_sha256"]
        == profile["operator_snapshot_receipt_sha256"]
    )
    preflight = client.get(f"/v1/tasks/{task_id}/preflight", headers=HEADERS)
    assert preflight.status_code == 200, preflight.text
    assert preflight.json()["source_id"] == source["source_id"]
    assert (
        preflight.json()["source_binding_sha256"]
        == profile["operator_snapshot_receipt_sha256"]
    )
    assert preflight.json()["source_profile_status"] == "MATCHED"


def test_live_annotation_change_does_not_mutate_frozen_snapshot_and_repeat_is_versioned(
    snapshot_client: tuple[TestClient, ProductService],
) -> None:
    client, service = snapshot_client
    project_id, asset, first_annotation = _create_project_asset_and_annotation(client)
    first_source = _snapshot(client, project_id)
    first_profile = first_source["data_profile"]

    updated = client.put(
        f"/v1/operator-workspaces/{WORKSPACE}/assets/{asset['asset_id']}/annotations",
        headers=HEADERS,
        json={
            "expected_revision": 1,
            "annotations": [
                {
                    "annotation_id": "bbox-1",
                    "label": "weld-defect",
                    "x": 0.1,
                    "y": 0.1,
                    "width": 0.5,
                    "height": 0.5,
                    "source": "MANUAL",
                }
            ],
        },
    )
    assert updated.status_code == 200, updated.text
    second_source = _snapshot(client, project_id)
    second_profile = second_source["data_profile"]
    assert second_source["source_id"] != first_source["source_id"]
    assert second_profile["snapshot_id"] != first_profile["snapshot_id"]

    first_receipt = json.loads(
        (
            service.product_root
            / "operator_project_snapshots"
            / first_profile["snapshot_id"]
            / "operator_project_snapshot_receipt.json"
        ).read_text(encoding="utf-8")
    )
    assert first_receipt["assets"][0]["annotation_revision"] == 1
    assert (
        first_receipt["assets"][0]["annotation_document_sha256"]
        == first_annotation["document_sha256"]
    )
    assert (
        second_profile["operator_snapshot_receipt_sha256"]
        != first_profile["operator_snapshot_receipt_sha256"]
    )


def test_snapshot_tamper_and_cross_scope_requests_fail_closed(
    snapshot_client: tuple[TestClient, ProductService],
) -> None:
    client, service = snapshot_client
    project_id, _asset, _annotation = _create_project_asset_and_annotation(client)
    source = _snapshot(client, project_id)
    profile = source["data_profile"]
    task = client.post(
        "/v1/tasks",
        headers=HEADERS,
        json={
            "project_id": project_id,
            "goal": "冻结快照篡改后必须在运行前门禁失败关闭",
            "source_kind": "local_authorized_directory",
            "source_id": source["source_id"],
            "plan_approval_required": True,
            "allowed_tools": ["image_quality"],
        },
    )
    assert task.status_code == 202, task.text
    task_id = task.json()["task_id"]
    manifest_path = (
        service.product_root
        / "operator_project_snapshots"
        / profile["snapshot_id"]
        / "batch_manifest.json"
    )
    manifest_path.write_bytes(manifest_path.read_bytes() + b" ")
    preflight = client.get(f"/v1/tasks/{task_id}/preflight", headers=HEADERS)
    assert preflight.status_code == 200, preflight.text
    assert preflight.json()["overall_status"] == "BLOCKED"
    assert preflight.json()["source_profile_status"] == "UNAVAILABLE"

    other_project = client.post(
        "/v1/projects",
        headers=HEADERS,
        json={
            "workspace_id": WORKSPACE,
            "name": "Other project",
            "description": "must not inherit the first project assets",
            "scenario_profile": "industrial",
            "source_kind": "local_authorized_directory",
        },
    )
    assert other_project.status_code == 201
    cross = client.post(
        "/v1/data-sources/operator-project-snapshots",
        headers=HEADERS,
        json={
            "workspace_id": WORKSPACE,
            "project_id": other_project.json()["project_id"],
            "operator_attests_authorized_use": True,
        },
    )
    assert cross.status_code == 409


def test_identical_snapshot_request_is_idempotent(
    snapshot_client: tuple[TestClient, ProductService],
) -> None:
    client, _service = snapshot_client
    project_id, _asset, _annotation = _create_project_asset_and_annotation(client)
    first = _snapshot(client, project_id)
    second = _snapshot(client, project_id)
    assert second["source_id"] == first["source_id"]
    assert second["source_archive_sha256"] == first["source_archive_sha256"]
    assert second["data_profile"] == first["data_profile"]
    assert len(hashlib.sha256(first["source_id"].encode()).hexdigest()) == 64


def test_operator_snapshot_executes_as_native_product_task_and_seals_evidence(
    snapshot_client: tuple[TestClient, ProductService],
) -> None:
    client, service = snapshot_client
    project_id, _asset, annotation = _create_project_asset_and_annotation(client)
    source = _snapshot(client, project_id)
    task = service.create_task(
        ACTOR,
        CreateTaskRequest(
            project_id=project_id,
            goal="对当前工作簿不可变快照执行确定性审核并封存完整证据",
            source_kind=DataSourceKind.LOCAL_AUTHORIZED_DIRECTORY,
            source_id=source["source_id"],
            plan_approval_required=False,
            allowed_tools=[
                "image_quality",
                "duplicate_leakage",
                "annotation_integrity",
                "coverage_matrix",
            ],
        ),
        idempotency_key="operator-snapshot-native-run-001",
        auto_start=False,
    )

    completed = service.run_task_sync(task.task_id)
    assert completed.execution_status is TaskExecutionStatus.COMPLETED, (
        completed.model_dump_json(indent=2)
    )
    assert completed.evidence_sha256 is not None
    assert completed.trace_sha256 is not None
    assert completed.error_code is None

    evidence_zip = service.evidence_path(ACTOR, task.task_id)
    with zipfile.ZipFile(evidence_zip) as archive:
        names = set(archive.namelist())
        assert {
            "operator_project_snapshot_receipt.json",
            "operator_snapshot_gate_receipt.json",
            "product_kernel_run_receipt.json",
            "agent_core_execution_receipt.json",
            "agent_runtime_trace.json",
            "task_summary.json",
            "task_plan_preview.json",
            "initial/gate_result.json",
            "final/gate_result.json",
            "gate_result.json",
        }.issubset(names)
        kernel = json.loads(
            archive.read("product_kernel_run_receipt.json").decode("utf-8")
        )
        summary = json.loads(archive.read("task_summary.json").decode("utf-8"))
        snapshot_receipt = json.loads(
            archive.read("operator_project_snapshot_receipt.json").decode("utf-8")
        )
        trace = json.loads(archive.read("agent_runtime_trace.json").decode("utf-8"))

    assert kernel["runtime_kind"] == "operator_project_snapshot"
    assert summary["source_id"] == source["source_id"]
    assert summary["source_binding_sha256"] == source["source_archive_sha256"]
    assert summary["raw_images_transmitted"] is False
    assert summary["production_release_allowed"] is False
    assert (
        snapshot_receipt["assets"][0]["annotation_revision"] == annotation["revision"]
    )
    assert [
        event["stage"]
        for event in trace["events"]
        if event["stage"]
        in {"intake", "planner", "tool", "council", "judge", "delivery"}
    ][0] == "intake"
    assert trace["events"][-1]["stage"] == "delivery"
    assert trace["approval_handoff"]["status"] == "pending"


def test_operator_snapshot_capa_uses_frozen_asset_count_and_runs_fail_closed(
    snapshot_client: tuple[TestClient, ProductService],
) -> None:
    client, service = snapshot_client
    project_id, _asset, _annotation = _create_project_asset_and_annotation(client)
    source = _snapshot(client, project_id)
    task = service.create_task(
        ACTOR,
        CreateTaskRequest(
            project_id=project_id,
            goal="对模糊工作簿快照建立受控 CAPA，并验证没有替换证据时保持失败关闭",
            source_kind=DataSourceKind.LOCAL_AUTHORIZED_DIRECTORY,
            source_id=source["source_id"],
            plan_approval_required=False,
            allowed_tools=[
                "image_quality",
                "duplicate_leakage",
                "annotation_integrity",
                "coverage_matrix",
            ],
        ),
        idempotency_key="operator-snapshot-capa-001",
        auto_start=False,
    )
    completed = service.run_task_sync(task.task_id)
    assert completed.execution_status is TaskExecutionStatus.COMPLETED
    parent_evidence_sha256 = completed.evidence_sha256
    delivery = service.industrial_delivery_receipt(ACTOR, task.task_id)
    plan = next(
        item
        for item in delivery.remediation_plans
        if item.strategy == "containment_first"
    )
    selected = service.select_remediation_plan(
        ACTOR,
        task.task_id,
        SelectRemediationPlanRequest(
            plan_id=plan.plan_id,
            plan_sha256=plan.plan_sha256,
            note="选择最小隔离方案并保留物理重采证据缺口。",
        ),
    )
    approved = service.approve_remediation_plan(
        ACTOR,
        task.task_id,
        selected.case_id,
        ApproveRemediationPlanRequest(
            note="批准只在私有派生副本执行；没有新图像时不得伪造重采闭环。",
            approved_work_order_ids=plan.selected_work_order_ids,
            operator_attests_derived_processing=True,
            max_copied_images=1,
        ),
    )
    assert approved.approval is not None
    assert approved.approval.planned_copy_count == 1

    executed = service.execute_remediation_plan(
        ACTOR,
        task.task_id,
        selected.case_id,
        ExecuteRemediationPlanRequest(
            reviewer_identity="QA-RC3-001 本地验收员",
            note="确认来源未漂移，仅复制冻结快照并执行同合同 Child Run。",
            expected_approval_binding_sha256=approved.approval.binding_sha256,
            operator_attests_derived_processing=True,
        ),
    )
    assert executed.derived_version is not None
    assert executed.execution is not None
    assert executed.recovery is not None
    assert executed.execution.parent_immutable is True
    assert executed.derived_version.original_selection_count == 1
    assert executed.derived_version.unresolved_work_order_ids == (
        plan.selected_work_order_ids
    )
    assert executed.recovery.recovery_success is False
    assert executed.recovery.remaining_work_order_count == len(
        plan.selected_work_order_ids
    )
    assert executed.recovery.production_release_allowed is False
    assert service.get_task(ACTOR, task.task_id).evidence_sha256 == (
        parent_evidence_sha256
    )
    child_source = service.store.get_local_source_authorization(
        ACTOR, executed.execution.derived_source_id
    )
    assert child_source.adapter_kind.value == "operator_project_snapshot"
    assert child_source.derived_version_id == executed.derived_version.version_id
    assert child_source.data_profile["profile_sha256"] == (
        executed.derived_version.derived_source_profile_sha256
    )


def test_task_visual_evidence_manifest_and_images_are_sha_bound(
    snapshot_client: tuple[TestClient, ProductService],
) -> None:
    client, service = snapshot_client
    task_id, source, asset = _complete_visual_snapshot_task(client, service)

    response = client.get(
        f"/v1/tasks/{task_id}/visual-evidence",
        headers={**HEADERS, "Origin": "http://127.0.0.1:4173"},
    )
    assert response.status_code == 200, response.text
    manifest = response.json()
    assert response.headers["x-visual-evidence-sha256"] == manifest["manifest_sha256"]
    assert response.headers["etag"] == f'"{manifest["manifest_sha256"]}"'
    assert "X-Visual-Evidence-SHA256" in {
        item.strip()
        for item in response.headers["access-control-expose-headers"].split(",")
    }
    assert manifest["task_id"] == task_id
    assert manifest["workspace_id"] == WORKSPACE
    assert manifest["project_id"] == source["data_profile"]["project_id"]
    assert manifest["source_id"] == source["source_id"]
    assert manifest["source_profile_sha256"] == source["data_profile"]["profile_sha256"]
    assert (
        manifest["operator_snapshot_receipt_sha256"] == source["source_archive_sha256"]
    )
    assert manifest["visual_count"] == len(manifest["items"]) == 1
    assert manifest["read_only"] is True
    assert manifest["raw_images_transmitted"] is False
    assert manifest["production_release_allowed"] is False

    item = manifest["items"][0]
    assert item["sample_id"] == asset["asset_id"]
    assert item["source_sha256"] == asset["source_sha256"]
    assert item["preview_sha256"] == asset["preview_sha256"]
    preview = client.get(item["preview_url"], headers=HEADERS)
    assert preview.status_code == 200, preview.text
    assert preview.headers["x-content-sha256"] == item["preview_sha256"]
    assert hashlib.sha256(preview.content).hexdigest() == item["preview_sha256"]
    assert preview.headers["content-type"].startswith("image/jpeg")

    assert item["mask_url"] is not None
    assert item["mask_sha256"] is not None
    mask = client.get(item["mask_url"], headers=HEADERS)
    assert mask.status_code == 200, mask.text
    assert mask.headers["x-content-sha256"] == item["mask_sha256"]
    assert hashlib.sha256(mask.content).hexdigest() == item["mask_sha256"]
    assert mask.headers["content-type"].startswith("image/png")

    missing = client.get(
        f"/v1/tasks/{task_id}/visual-evidence/asset_missing/preview",
        headers=HEADERS,
    )
    assert missing.status_code == 404
    assert missing.json()["error"]["code"] == "not_found"


def test_task_visual_evidence_rejects_non_snapshot_source(
    snapshot_client: tuple[TestClient, ProductService],
) -> None:
    client, service = snapshot_client
    project = client.post(
        "/v1/projects",
        headers=HEADERS,
        json={"workspace_id": WORKSPACE, "name": "Synthetic-only project"},
    )
    assert project.status_code == 201, project.text
    task = service.create_task(
        ACTOR,
        CreateTaskRequest(
            project_id=project.json()["project_id"],
            goal="合成来源不得伪装成真实 Operator Snapshot 视觉证据",
        ),
        auto_start=False,
    )
    completed = service.run_task_sync(task.task_id)
    assert completed.execution_status is TaskExecutionStatus.COMPLETED

    response = client.get(
        f"/v1/tasks/{task.task_id}/visual-evidence",
        headers=HEADERS,
    )
    assert response.status_code == 409
    assert response.json()["error"]["code"] == "artifact_unavailable"


def test_task_visual_evidence_preview_tamper_fails_closed(
    snapshot_client: tuple[TestClient, ProductService],
) -> None:
    client, service = snapshot_client
    task_id, source, _asset = _complete_visual_snapshot_task(client, service)
    manifest = client.get(
        f"/v1/tasks/{task_id}/visual-evidence",
        headers=HEADERS,
    ).json()
    snapshot_root = (
        service.product_root
        / "operator_project_snapshots"
        / source["data_profile"]["snapshot_id"]
    )
    receipt = json.loads(
        (snapshot_root / "operator_project_snapshot_receipt.json").read_text(
            encoding="utf-8"
        )
    )
    preview_path = snapshot_root / receipt["assets"][0]["preview_relative_path"]
    preview_path.write_bytes(preview_path.read_bytes() + b"tampered")

    response = client.get(manifest["items"][0]["preview_url"], headers=HEADERS)
    assert response.status_code == 409
    assert response.json()["error"]["code"] == "artifact_unavailable"
