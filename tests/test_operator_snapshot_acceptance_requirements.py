"""Explicit snapshot requirements must bind real inputs without changing v1."""

from __future__ import annotations

import copy
import hashlib
from io import BytesIO

from fastapi.testclient import TestClient
from PIL import Image
import pytest

from visiondata_gate.api import create_app
from visiondata_gate.audit_envelope import canonical_jcs_bytes
from visiondata_gate.contracts import BatchContract, BatchManifest
from visiondata_gate.annotations import inspect_annotations
from visiondata_gate.operator_snapshot import (
    OperatorProjectSnapshotReceipt,
    materialize_operator_snapshot_subset,
    profile_operator_project_snapshot,
)
from visiondata_gate.product_models import (
    CreateTaskRequest,
    DataSourceKind,
    TaskExecutionStatus,
)
from visiondata_gate.product_service import ProductService
from visiondata_gate.tools import inspect_contract_governance, run_tool


ACTOR = "usr_local_demo"
WORKSPACE = "wsp_local_demo"
HEADERS = {"X-Actor-User-Id": ACTOR}


@pytest.fixture
def inputs(tmp_path):
    service = ProductService(tmp_path / "product", recover_interrupted=False)
    try:
        with TestClient(create_app(service, ensure_demo_tenant=True)) as client:
            response = client.post(
                "/v1/projects",
                headers=HEADERS,
                json={
                    "workspace_id": WORKSPACE,
                    "name": "Explicit snapshot requirements",
                    "source_kind": "local_authorized_directory",
                    "scenario_profile": "industrial",
                },
            )
            assert response.status_code == 201, response.text
            project_id = response.json()["project_id"]
            assets, annotations = [], []
            for index in range(2):
                buffer = BytesIO()
                Image.new("RGB", (48, 32), (50 + index * 60, 90, 120)).save(
                    buffer, format="PNG"
                )
                upload = client.post(
                    f"/v1/operator-workspaces/{WORKSPACE}/assets",
                    headers=HEADERS,
                    params={"project_id": project_id},
                    files=[
                        (
                            "files",
                            (f"input-{index}.png", buffer.getvalue(), "image/png"),
                        )
                    ],
                )
                assert upload.status_code == 201, upload.text
                asset = upload.json()["assets"][0]
                assets.append(asset)
                url = f"/v1/operator-workspaces/{WORKSPACE}/assets/{asset['asset_id']}/annotations"
                if index == 0:
                    saved = client.put(
                        url,
                        headers=HEADERS,
                        json={
                            "expected_revision": 0,
                            "annotations": [
                                {
                                    "annotation_id": "box-1",
                                    "label": "defect",
                                    "x": 0.1,
                                    "y": 0.1,
                                    "width": 0.3,
                                    "height": 0.3,
                                }
                            ],
                        },
                    )
                    assert saved.status_code == 200, saved.text
                state = client.get(url, headers=HEADERS)
                assert state.status_code == 200, state.text
                annotations.append(state.json())
            requirements = {
                "schema_version": "visiondata-gate.operator-acceptance-requirements.v1",
                "purpose_description": "Review a mixed annotated and good-image delivery batch",
                "category_vocabulary": ["defect", "good"],
                "samples": [
                    {
                        "asset_id": asset["asset_id"],
                        "split": "train" if index == 0 else "val",
                        "category": "defect" if index == 0 else "good",
                        "annotation_requirement": "REQUIRED"
                        if index == 0
                        else "NOT_APPLICABLE",
                        "human_review": {
                            "reviewer_name": "Synthetic reviewer",
                            "note": "Reviewed the current image and annotation state for this task",
                            "expected_asset_sha256": asset["source_sha256"],
                            "expected_annotation_revision": annotations[index][
                                "revision"
                            ],
                            "expected_annotation_sha256": annotations[index][
                                "document_sha256"
                            ],
                            "operator_attests_reviewed": True,
                        },
                    }
                    for index, asset in enumerate(assets)
                ],
            }
            request = {
                "workspace_id": WORKSPACE,
                "project_id": project_id,
                "operator_attests_authorized_use": True,
                "acceptance_requirements": requirements,
            }
            yield client, service, request, assets, annotations
    finally:
        service.close(wait=True)


def _freeze(client, request):
    return client.post(
        "/v1/data-sources/operator-project-snapshots", headers=HEADERS, json=request
    )


def _root(service, response):
    return (
        service.product_root
        / "operator_project_snapshots"
        / response.json()["data_profile"]["snapshot_id"]
    )


def test_explicit_requirements_freeze_splits_categories_reviews_and_parent_bytes(
    inputs,
):
    client, service, request, assets, states = inputs
    before = [
        client.get(
            f"/v1/operator-workspaces/{WORKSPACE}/assets/{a['asset_id']}/content",
            headers=HEADERS,
        ).content
        for a in assets
    ]
    response = _freeze(client, request)
    assert response.status_code == 201, response.text
    root = _root(service, response)
    receipt = OperatorProjectSnapshotReceipt.model_validate_json(
        (root / "operator_project_snapshot_receipt.json").read_bytes()
    )
    assert receipt.schema_version == "visiondata-gate.operator-project-snapshot.v2"
    manifest = BatchManifest.model_validate_json(
        (root / "batch_manifest.json").read_bytes()
    )
    actual = {s.sample_id: (s.split, s.category) for s in manifest.samples}
    assert actual == {
        assets[0]["asset_id"]: ("train", "defect"),
        assets[1]["asset_id"]: ("val", "good"),
    }
    contract = BatchContract.model_validate_json(
        (root / "batch_contract.json").read_bytes()
    )
    assert contract.schema_version == "2.0"
    assert contract.intended_use == "sandbox_experiment_training_pool"
    assert contract.sample_annotation_requirements == {
        assets[0]["asset_id"]: "REQUIRED",
        assets[1]["asset_id"]: "NOT_APPLICABLE",
    }
    requirements = receipt.acceptance_requirements.model_dump(mode="json")
    assert (
        contract.acceptance_requirements_sha256
        == hashlib.sha256(canonical_jcs_bytes(requirements)).hexdigest()
    )
    by_id = {s["asset_id"]: s for s in requirements["samples"]}
    assert (
        by_id[assets[0]["asset_id"]]["human_review"]["expected_annotation_sha256"]
        == states[0]["document_sha256"]
    )
    assert (
        response.json()["data_profile"]["acceptance_requirements_sha256"]
        == contract.acceptance_requirements_sha256
    )
    assert (
        profile_operator_project_snapshot(root)["operator_snapshot_receipt_sha256"]
        == response.json()["source_archive_sha256"]
    )
    assert before == [
        client.get(
            f"/v1/operator-workspaces/{WORKSPACE}/assets/{a['asset_id']}/content",
            headers=HEADERS,
        ).content
        for a in assets
    ]
    assert (
        _freeze(client, request).json()["source_archive_sha256"]
        == response.json()["source_archive_sha256"]
    )


def test_legacy_serialization_and_snapshot_replay_remain_unchanged(inputs):
    assert (
        hashlib.sha256(
            canonical_jcs_bytes(BatchContract().model_dump(mode="json"))
        ).hexdigest()
        == "fe303d0595eea5e98fd5bebfb70dc7859403de9853f95ba3cc64c9d2957e3462"
    )
    client, service, request, _assets, _states = inputs
    request.pop("acceptance_requirements")
    response = _freeze(client, request)
    assert response.status_code == 201, response.text
    root = _root(service, response)
    path = root / "operator_project_snapshot_receipt.json"
    original = path.read_bytes()
    parsed = OperatorProjectSnapshotReceipt.model_validate_json(original)
    assert parsed.schema_version.endswith(".v1")
    assert "acceptance_requirements" not in parsed.model_dump(mode="json")
    assert canonical_jcs_bytes(parsed.model_dump(mode="json")) == original
    assert (
        _freeze(client, request).json()["source_archive_sha256"]
        == response.json()["source_archive_sha256"]
    )
    assert path.read_bytes() == original
    contract = BatchContract.model_validate_json(
        (root / "batch_contract.json").read_bytes()
    )
    manifest = BatchManifest.model_validate_json(
        (root / "batch_manifest.json").read_bytes()
    )
    _, annotation_trace, _ = run_tool(
        "annotation_integrity", root / "batch", manifest, contract
    )
    assert set(annotation_trace.parameters) == {
        "annotations_required",
        "expected_width",
        "expected_height",
        "min_mask_fraction",
        "max_mask_fraction",
    }
    _, governance_trace, _ = run_tool(
        "governance_audit", root / "batch", manifest, contract, include_optional=True
    )
    assert set(governance_trace.parameters) == {
        "required_splits",
        "annotations_required",
        "coverage_cells",
    }


@pytest.mark.parametrize(
    "problem",
    [
        "unknown",
        "required_missing",
        "not_applicable_present",
        "category",
        "label",
        "missing_asset",
        "extra_asset",
        "duplicate_asset",
        "asset_sha",
        "review_sha",
        "review_revision",
        "blank_reviewer",
        "blank_note",
        "not_attested",
    ],
)
def test_explicit_invalid_requirements_do_not_create_snapshots(inputs, problem):
    client, service, request, _assets, _states = inputs
    requirements = request["acceptance_requirements"]
    first, second = requirements["samples"]
    if problem == "unknown":
        second["annotation_requirement"] = "UNKNOWN"
    elif problem == "required_missing":
        second["annotation_requirement"] = "REQUIRED"
    elif problem == "not_applicable_present":
        first["annotation_requirement"] = "NOT_APPLICABLE"
    elif problem == "category":
        first["category"] = "undeclared"
    elif problem == "label":
        requirements["category_vocabulary"] = ["other", "good"]
        first["category"] = "other"
    elif problem == "missing_asset":
        requirements["samples"].pop()
    elif problem == "extra_asset":
        item = copy.deepcopy(second)
        item["asset_id"] = "foreign-asset"
        requirements["samples"].append(item)
    elif problem == "duplicate_asset":
        requirements["samples"].append(copy.deepcopy(first))
    elif problem == "asset_sha":
        first["human_review"]["expected_asset_sha256"] = "0" * 64
    elif problem == "review_sha":
        first["human_review"]["expected_annotation_sha256"] = "0" * 64
    elif problem == "review_revision":
        first["human_review"]["expected_annotation_revision"] = 0
    elif problem == "blank_reviewer":
        first["human_review"]["reviewer_name"] = "   "
    elif problem == "blank_note":
        first["human_review"]["note"] = "   "
    elif problem == "not_attested":
        first["human_review"]["operator_attests_reviewed"] = False
    response = _freeze(client, request)
    assert response.status_code in {409, 422}, response.text
    assert not list(
        (service.product_root / "operator_project_snapshots").glob("opsnap_*")
    )


def test_review_becomes_stale_after_a_real_annotation_edit(inputs):
    client, service, request, assets, states = inputs
    saved = client.put(
        f"/v1/operator-workspaces/{WORKSPACE}/assets/{assets[0]['asset_id']}/annotations",
        headers=HEADERS,
        json={
            "expected_revision": states[0]["revision"],
            "annotations": [
                {
                    "annotation_id": "box-1",
                    "label": "defect",
                    "x": 0.2,
                    "y": 0.1,
                    "width": 0.3,
                    "height": 0.3,
                }
            ],
        },
    )
    assert saved.status_code == 200, saved.text
    assert _freeze(client, request).status_code == 409
    assert not list(
        (service.product_root / "operator_project_snapshots").glob("opsnap_*")
    )


def test_requirements_change_produces_a_new_snapshot_identity(inputs):
    client, _service, request, _assets, _states = inputs
    first = _freeze(client, request)
    assert first.status_code == 201, first.text
    request["acceptance_requirements"]["purpose_description"] = (
        "A different declared use under the same sandbox permissions"
    )
    second = _freeze(client, request)
    assert second.status_code == 201, second.text
    assert (
        first.json()["source_archive_sha256"] != second.json()["source_archive_sha256"]
    )
    assert (
        first.json()["data_profile"]["snapshot_id"]
        != second.json()["data_profile"]["snapshot_id"]
    )


def test_optional_without_annotations_is_explicitly_allowed(inputs):
    client, _service, request, _assets, _states = inputs
    request["acceptance_requirements"]["samples"][1]["annotation_requirement"] = (
        "OPTIONAL"
    )
    response = _freeze(client, request)
    assert response.status_code == 201, response.text


@pytest.mark.parametrize("remove_required", [False, True])
def test_governance_respects_optional_and_required_samples(inputs, remove_required):
    client, service, request, assets, _states = inputs
    response = _freeze(client, request)
    assert response.status_code == 201, response.text
    root = _root(service, response)
    contract = BatchContract.model_validate_json(
        (root / "batch_contract.json").read_bytes()
    )
    manifest = BatchManifest.model_validate_json(
        (root / "batch_manifest.json").read_bytes()
    )
    if remove_required:
        manifest = manifest.model_copy(
            update={
                "samples": [
                    s.model_copy(update={"annotation_path": None})
                    for s in manifest.samples
                ]
            }
        )
    findings, metrics = inspect_contract_governance(root / "batch", manifest, contract)
    missing = [f for f in findings if f.code == "GOVERNANCE_ANNOTATION_PATH_MISSING"]
    assert metrics["annotation_path_missing_count"] == int(remove_required)
    assert [f.sample_ids for f in missing] == (
        [[assets[0]["asset_id"]]] if remove_required else []
    )
    _, trace, _ = run_tool(
        "governance_audit", root / "batch", manifest, contract, include_optional=True
    )
    assert (
        trace.parameters["acceptance_requirements_sha256"]
        == contract.acceptance_requirements_sha256
    )
    assert (
        trace.parameters["sample_annotation_requirements"]
        == contract.sample_annotation_requirements
    )


def test_v2_task_executes_real_manifest_and_frozen_contract(inputs):
    client, service, request, _assets, _states = inputs
    response = _freeze(client, request)
    assert response.status_code == 201, response.text
    task = service.create_task(
        ACTOR,
        CreateTaskRequest(
            project_id=request["project_id"],
            goal="Verify explicitly reviewed uploaded sample requirements",
            source_kind=DataSourceKind.LOCAL_AUTHORIZED_DIRECTORY,
            source_id=response.json()["source_id"],
            plan_approval_required=False,
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
    assert completed.execution_status is TaskExecutionStatus.COMPLETED, (
        completed.error_message
    )
    gate = service.read_evidence_zip_json(
        ACTOR, task.task_id, "initial/gate_result.json"
    )
    assert gate["contract_id"] == "visiondata-operator-project-snapshot-v2"
    assert "MISSING_ANNOTATION" not in {f["code"] for f in gate["findings"]}
    assert "GOVERNANCE_ANNOTATION_PATH_MISSING" not in {
        f["code"] for f in gate["findings"]
    }
    _, _, receipt, _ = service._operator_snapshot_visual_context(ACTOR, task.task_id)
    assert receipt.acceptance_requirements is not None
    assert receipt.production_release_allowed is False


def test_annotation_tool_enforces_per_sample_requirement_in_mixed_batch(inputs):
    client, service, request, assets, _states = inputs
    response = _freeze(client, request)
    assert response.status_code == 201, response.text
    root = _root(service, response)
    contract = BatchContract.model_validate_json(
        (root / "batch_contract.json").read_bytes()
    )
    manifest = BatchManifest.model_validate_json(
        (root / "batch_manifest.json").read_bytes()
    )
    missing = manifest.model_copy(
        update={
            "samples": [
                s.model_copy(update={"annotation_path": None}) for s in manifest.samples
            ]
        }
    )
    findings, _ = inspect_annotations(root / "batch", missing, contract)
    assert [(f.code, f.sample_ids) for f in findings] == [
        ("MISSING_ANNOTATION", [assets[0]["asset_id"]])
    ]
    _, trace, _ = run_tool("annotation_integrity", root / "batch", missing, contract)
    assert (
        trace.parameters["acceptance_requirements_sha256"]
        == contract.acceptance_requirements_sha256
    )
    assert (
        trace.parameters["sample_annotation_requirements"]
        == contract.sample_annotation_requirements
    )


def test_v2_derived_subset_keeps_parent_contract_and_review_bindings(inputs, tmp_path):
    client, service, request, assets, _states = inputs
    response = _freeze(client, request)
    assert response.status_code == 201, response.text
    root = _root(service, response)
    before = (root / "batch_contract.json").read_bytes()
    subset_root = tmp_path / "isolated-derived-subsets"
    subset_root.mkdir()
    derived = materialize_operator_snapshot_subset(
        root,
        snapshots_root=subset_root,
        retained_asset_ids={assets[0]["asset_id"]},
        expected_receipt_sha256=response.json()["source_archive_sha256"],
        created_at="2026-09-11T00:00:00Z",
    )
    assert derived.receipt.schema_version.endswith(".v2")
    assert derived.receipt.asset_count == 1
    assert (derived.root / "batch_contract.json").read_bytes() == before
    assert (root / "batch_contract.json").read_bytes() == before
    assert (
        profile_operator_project_snapshot(derived.root)[
            "acceptance_requirements_sha256"
        ]
        == response.json()["data_profile"]["acceptance_requirements_sha256"]
    )
