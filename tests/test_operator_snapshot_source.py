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
from visiondata_gate.audit_envelope import canonical_jcs_bytes
from visiondata_gate.capa import (
    ApproveRemediationPlanRequest,
    ExecuteRemediationPlanRequest,
    SelectRemediationPlanRequest,
    _operator_duplicate_exclusions,
    build_operator_snapshot_derived_version,
)
from visiondata_gate.contracts import BatchContract, BatchManifest
from visiondata_gate.operator_snapshot import (
    OperatorProjectSnapshotReceipt,
    profile_operator_project_snapshot,
)
from visiondata_gate.pipeline import compute_batch_digest
from visiondata_gate.product_models import (
    CreateTaskRequest,
    DataSourceKind,
    TaskExecutionStatus,
)
from visiondata_gate.product_service import ProductService
from visiondata_gate.task_store import ConflictError


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


def _duplicate_snapshot_capa(
    client: TestClient, service: ProductService, *, annotate_one: bool = False
):
    project = client.post(
        "/v1/projects",
        headers=HEADERS,
        json={
            "workspace_id": WORKSPACE,
            "name": "Exact duplicate remediation",
            "source_kind": "local_authorized_directory",
        },
    )
    assert project.status_code == 201, project.text
    project_id = project.json()["project_id"]
    image = Image.frombytes(
        "L",
        (64, 64),
        bytes(64 if (x + y) % 2 else 192 for y in range(64) for x in range(64)),
    ).convert("RGB")
    buffer = BytesIO()
    image.save(buffer, format="PNG")
    upload = client.post(
        f"/v1/operator-workspaces/{WORKSPACE}/assets",
        params={"project_id": project_id},
        headers=HEADERS,
        files=[
            ("files", ("same.png", buffer.getvalue(), "image/png")),
            ("files", ("same-copy.png", buffer.getvalue(), "image/png")),
        ],
    )
    assert upload.status_code == 201, upload.text
    assets = upload.json()["assets"]
    assert len(assets) == 2
    if annotate_one:
        response = client.put(
            f"/v1/operator-workspaces/{WORKSPACE}/assets/"
            f"{assets[1]['asset_id']}/annotations",
            headers=HEADERS,
            json={
                "expected_revision": 0,
                "annotations": [
                    {
                        "annotation_id": "different-semantics",
                        "label": "unlabeled",
                        "x": 0.2,
                        "y": 0.2,
                        "width": 0.2,
                        "height": 0.2,
                        "source": "MANUAL",
                    }
                ],
            },
        )
        assert response.status_code == 200, response.text
    source = _snapshot(client, project_id)
    task = service.create_task(
        ACTOR,
        CreateTaskRequest(
            project_id=project_id,
            goal="Verify byte-identical data, approve deduplication and recheck.",
            source_kind=DataSourceKind.LOCAL_AUTHORIZED_DIRECTORY,
            source_id=source["source_id"],
            allowed_tools=[
                "image_quality",
                "duplicate_leakage",
                "annotation_integrity",
                "coverage_matrix",
                "governance_audit",
            ],
        ),
        auto_start=False,
    )
    completed = service.run_task_sync(task.task_id)
    assert completed.execution_status is TaskExecutionStatus.COMPLETED
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
            note="Keep one byte-identical same-semantic sample in a derived copy.",
        ),
    )
    return completed, source, plan, selected, assets


def _approve_duplicate_capa(service, task, plan, selected):
    approved = service.approve_remediation_plan(
        ACTOR,
        task.task_id,
        selected.case_id,
        ApproveRemediationPlanRequest(
            note="Approve the frozen exact-duplicate plan for local derivation.",
            approved_work_order_ids=plan.selected_work_order_ids,
            operator_attests_derived_processing=True,
            max_copied_images=2,
        ),
    )
    assert approved.approval is not None
    return approved


def _duplicate_execution_request(approved):
    return ExecuteRemediationPlanRequest(
        reviewer_identity="Synthetic QA owner",
        note="Confirm approved same-contract duplicate recheck.",
        expected_approval_binding_sha256=approved.approval.binding_sha256,
        operator_attests_derived_processing=True,
    )


def _approve_and_execute_duplicate_capa(service, task, plan, selected):
    approved = _approve_duplicate_capa(service, task, plan, selected)
    return service.execute_remediation_plan(
        ACTOR,
        task.task_id,
        selected.case_id,
        _duplicate_execution_request(approved),
    )


def test_exact_duplicate_capa_removes_only_derived_copy_and_child_rechecks(
    snapshot_client: tuple[TestClient, ProductService],
) -> None:
    client, service = snapshot_client
    task, source, plan, selected, assets = _duplicate_snapshot_capa(client, service)
    parent_root = (
        service.product_root
        / "operator_project_snapshots"
        / source["data_profile"]["snapshot_id"]
    )
    before = {
        path.relative_to(parent_root).as_posix(): hashlib.sha256(
            path.read_bytes()
        ).hexdigest()
        for path in parent_root.rglob("*")
        if path.is_file()
    }
    executed = _approve_and_execute_duplicate_capa(service, task, plan, selected)

    assert executed.derived_version is not None
    assert executed.derived_version.original_selection_count == 2
    assert executed.derived_version.derived_image_count == 1
    assert executed.derived_version.unresolved_work_order_ids == []
    operation = executed.derived_version.operations[0]
    assert operation.action == "EXCLUDE_EXACT_DUPLICATE"
    assert operation.status == "EXECUTED"
    assert operation.before_sample_ids == sorted(item["asset_id"] for item in assets)
    assert operation.after_sample_ids == [min(item["asset_id"] for item in assets)]
    assert executed.recovery is not None
    assert executed.recovery.parent_decision == "QUARANTINE"
    assert executed.recovery.child_decision == "PASS"
    assert "EXACT_DUPLICATE" in executed.recovery.resolved_finding_codes
    assert executed.recovery.child_finding_codes == []
    assert executed.recovery.verified_closed_work_order_count == 1
    assert executed.recovery.production_release_allowed is False
    assert executed.execution is not None and executed.execution.parent_immutable
    assert service.get_task(ACTOR, task.task_id).evidence_sha256 == task.evidence_sha256
    assert before == {
        path.relative_to(parent_root).as_posix(): hashlib.sha256(
            path.read_bytes()
        ).hexdigest()
        for path in parent_root.rglob("*")
        if path.is_file()
    }
    child_source = service.store.get_local_source_authorization(
        ACTOR, executed.execution.derived_source_id
    )
    assert child_source.source_archive_sha256 != source["source_archive_sha256"]
    assert (
        child_source.source_archive_sha256
        == (child_source.data_profile["operator_snapshot_receipt_sha256"])
    )
    assert child_source.data_profile["asset_count"] == 1
    child_snapshot = service.read_evidence_zip_json(
        ACTOR,
        executed.execution.child_task_id,
        "operator_project_snapshot_receipt.json",
    )
    assert child_snapshot["asset_count"] == 1
    assert child_snapshot["receipt_sha256"] == child_source.source_archive_sha256
    assert (
        child_snapshot["batch_contract_sha256"]
        == (source["data_profile"]["batch_contract_sha256"])
    )
    assert (
        child_snapshot["batch_manifest_sha256"]
        != (source["data_profile"]["batch_manifest_sha256"])
    )
    assert (
        child_snapshot["snapshot_binding_sha256"]
        != (source["data_profile"]["snapshot_binding_sha256"])
    )
    assert (
        child_snapshot["batch_digest_sha256"]
        != (source["data_profile"]["batch_digest_sha256"])
    )
    assert service.get_capa_case(ACTOR, task.task_id, selected.case_id) == executed
    assert service.list_capa_cases(ACTOR, task.task_id) == [executed]


def test_exact_duplicate_capa_blocks_conflicting_frozen_annotations(
    snapshot_client: tuple[TestClient, ProductService],
) -> None:
    client, service = snapshot_client
    task, source, plan, selected, _ = _duplicate_snapshot_capa(
        client, service, annotate_one=True
    )
    executed = _approve_and_execute_duplicate_capa(service, task, plan, selected)
    assert executed.derived_version is not None
    assert executed.derived_version.derived_image_count == 2
    assert executed.derived_version.operations[0].status == "BLOCKED"
    assert "标注文档身份不一致" in executed.derived_version.operations[0].reason
    assert (
        executed.derived_version.unresolved_work_order_ids
        == plan.selected_work_order_ids
    )
    assert executed.recovery is not None
    assert "EXACT_DUPLICATE" in executed.recovery.child_finding_codes
    assert executed.recovery.recovery_success is False
    assert executed.recovery.verified_closed_work_order_count == 0
    child_source = service.store.get_local_source_authorization(
        ACTOR, executed.execution.derived_source_id
    )
    assert child_source.source_archive_sha256 == source["source_archive_sha256"]


def test_exact_duplicate_capa_requires_current_human_approval(
    snapshot_client: tuple[TestClient, ProductService],
    tmp_path: Path,
) -> None:
    client, service = snapshot_client
    task, source, plan, selected, _ = _duplicate_snapshot_capa(client, service)
    with pytest.raises(ConflictError, match="hash-bound human approval"):
        service.execute_remediation_plan(ACTOR, task.task_id, selected.case_id)
    approved = _approve_duplicate_capa(service, task, plan, selected)
    request = _duplicate_execution_request(approved).model_copy(
        update={
            "expected_approval_binding_sha256": "0" * 64,
        }
    )
    with pytest.raises(ConflictError, match="does not bind the current approval"):
        service.execute_remediation_plan(ACTOR, task.task_id, selected.case_id, request)
    parent_root = (
        service.product_root
        / "operator_project_snapshots"
        / source["data_profile"]["snapshot_id"]
    )
    delivery = service.industrial_delivery_receipt(ACTOR, task.task_id)
    with pytest.raises(ValueError, match="CAPA seal mismatch"):
        build_operator_snapshot_derived_version(
            source_root=parent_root,
            output_version_root=tmp_path / "must-not-publish",
            parent_source_id=source["source_id"],
            parent_source_archive_sha256=source["source_archive_sha256"],
            parent_task_id=task.task_id,
            case_id=selected.case_id,
            version_id="drv_synthetic_tamper",
            plan=plan,
            approval=approved.approval.model_copy(update={"approval_note": "forged"}),
            work_orders=delivery.executable_work_orders,
            created_at="2026-09-09T00:00:00Z",
        )
    assert not (tmp_path / "must-not-publish").exists()
    assert not (service.product_root / "derived_versions").exists()


def test_exact_duplicate_capa_rechecks_source_bytes_before_deriving(
    snapshot_client: tuple[TestClient, ProductService],
) -> None:
    client, service = snapshot_client
    task, source, plan, selected, _ = _duplicate_snapshot_capa(client, service)
    approved = _approve_duplicate_capa(service, task, plan, selected)
    root = (
        service.product_root
        / "operator_project_snapshots"
        / source["data_profile"]["snapshot_id"]
    )
    receipt = OperatorProjectSnapshotReceipt.model_validate_json(
        (root / "operator_project_snapshot_receipt.json").read_bytes()
    )
    image_path = root / receipt.assets[0].source_relative_path
    image_path.write_bytes(image_path.read_bytes() + b"synthetic-tamper")
    with pytest.raises(ConflictError, match="source drift"):
        service.execute_remediation_plan(
            ACTOR,
            task.task_id,
            selected.case_id,
            _duplicate_execution_request(approved),
        )
    assert not (service.product_root / "derived_versions").exists()


def test_exact_duplicate_exclusion_preserves_frozen_coverage_minimum(
    snapshot_client: tuple[TestClient, ProductService],
) -> None:
    client, service = snapshot_client
    task, source, _plan, _selected, assets = _duplicate_snapshot_capa(client, service)
    root = (
        service.product_root
        / "operator_project_snapshots"
        / source["data_profile"]["snapshot_id"]
    )
    receipt_path = root / "operator_project_snapshot_receipt.json"
    receipt = OperatorProjectSnapshotReceipt.model_validate_json(
        receipt_path.read_bytes()
    )
    contract = BatchContract.model_validate_json(
        (root / "batch_contract.json").read_bytes()
    )
    contract.coverage.min_per_cell = 2
    # Isolate the policy calculation with a newly sealed synthetic contract.
    # The old Product source authorization is deliberately not used after this edit.
    (root / "batch_contract.json").write_bytes(canonical_jcs_bytes(contract))
    manifest = BatchManifest.model_validate_json(
        (root / "batch_manifest.json").read_bytes()
    )
    stable = receipt.model_dump(mode="json", exclude={"receipt_sha256"})
    stable.update(
        {
            "batch_contract_sha256": hashlib.sha256(
                canonical_jcs_bytes(contract)
            ).hexdigest(),
            "batch_digest_sha256": compute_batch_digest(
                root / "batch", manifest, contract
            ),
        }
    )
    updated = OperatorProjectSnapshotReceipt(
        **stable, receipt_sha256=hashlib.sha256(canonical_jcs_bytes(stable)).hexdigest()
    )
    receipt_path.write_bytes(canonical_jcs_bytes(updated))
    profile_operator_project_snapshot(
        root, expected_receipt_sha256=updated.receipt_sha256
    )
    delivery = service.industrial_delivery_receipt(ACTOR, task.task_id)
    retained_ids, operations, unresolved = _operator_duplicate_exclusions(
        root, updated, delivery.executable_work_orders
    )
    assert retained_ids == {asset["asset_id"] for asset in assets}
    assert operations[0].status == "BLOCKED"
    assert "覆盖数量" in operations[0].reason
    assert unresolved == [delivery.executable_work_orders[0].work_order_id]


def test_exact_duplicate_capa_resumes_published_subset_and_verifies_binding(
    snapshot_client: tuple[TestClient, ProductService],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client, service = snapshot_client
    task, source, plan, selected, _ = _duplicate_snapshot_capa(client, service)
    approved = _approve_duplicate_capa(service, task, plan, selected)
    request = _duplicate_execution_request(approved)
    original_create_child = service.create_reverification_task

    def interrupt_child_creation(*args, **kwargs):
        raise RuntimeError("synthetic interruption after subset publication")

    monkeypatch.setattr(service, "create_reverification_task", interrupt_child_creation)
    with pytest.raises(RuntimeError, match="synthetic interruption"):
        service.execute_remediation_plan(ACTOR, task.task_id, selected.case_id, request)
    interrupted = service.get_capa_case(ACTOR, task.task_id, selected.case_id)
    assert interrupted.derived_version.derived_image_count == 1
    assert interrupted.execution is None
    assert interrupted.recovery is None
    monkeypatch.setattr(service, "create_reverification_task", original_create_child)
    completed = service.execute_remediation_plan(
        ACTOR, task.task_id, selected.case_id, request
    )
    assert completed.derived_version == interrupted.derived_version
    assert completed.recovery.child_decision == "PASS"
    assert service.get_capa_case(ACTOR, task.task_id, selected.case_id) == completed
    assert service.list_capa_cases(ACTOR, task.task_id) == [completed]
    child_source = service.store.get_local_source_authorization(
        ACTOR, completed.execution.derived_source_id
    )
    assert child_source.source_archive_sha256 != source["source_archive_sha256"]
    parent_binding = service.store.get_local_source_binding_unscoped(
        source["source_id"]
    )
    recovered = service._recover_published_derived_version(
        parent=task,
        parent_binding=parent_binding,
        case_id=selected.case_id,
        version_id=completed.derived_version.version_id,
        approval=approved.approval,
        expected_receipt=completed.derived_version,
    )
    assert recovered.source_profile == child_source.data_profile
    receipt_path = recovered.derived_root / "operator_project_snapshot_receipt.json"
    receipt_path.write_bytes(receipt_path.read_bytes() + b" ")
    with pytest.raises(ValueError, match="not canonical JCS"):
        service._recover_published_derived_version(
            parent=task,
            parent_binding=parent_binding,
            case_id=selected.case_id,
            version_id=completed.derived_version.version_id,
            approval=approved.approval,
            expected_receipt=completed.derived_version,
        )


@pytest.mark.parametrize(
    "invalid_evidence", ["unknown_sample", "wrong_finding", "near_duplicate"]
)
def test_exact_duplicate_policy_rejects_unbound_or_unsupported_evidence(
    snapshot_client: tuple[TestClient, ProductService],
    invalid_evidence: str,
) -> None:
    client, service = snapshot_client
    task, source, _plan, _selected, assets = _duplicate_snapshot_capa(client, service)
    root = (
        service.product_root
        / "operator_project_snapshots"
        / source["data_profile"]["snapshot_id"]
    )
    receipt = OperatorProjectSnapshotReceipt.model_validate_json(
        (root / "operator_project_snapshot_receipt.json").read_bytes()
    )
    delivery = service.industrial_delivery_receipt(ACTOR, task.task_id)
    order = delivery.executable_work_orders[0]
    span = order.evidence_span[0]
    if invalid_evidence == "unknown_sample":
        changed = span.model_copy(
            update={"sample_ids": [assets[0]["asset_id"], "unknown"]}
        )
    elif invalid_evidence == "wrong_finding":
        changed = span.model_copy(update={"finding_id": "not-the-measured-finding"})
    else:
        changed = span.model_copy(update={"code": "CROSS_SPLIT_NEAR_DUPLICATE"})
    retained, operations, unresolved = _operator_duplicate_exclusions(
        root, receipt, [order.model_copy(update={"evidence_span": [changed]})]
    )
    assert retained == {asset["asset_id"] for asset in assets}
    assert operations[0].action == "INVESTIGATION_HOLD"
    assert operations[0].status == "BLOCKED"
    assert unresolved == [order.work_order_id]
