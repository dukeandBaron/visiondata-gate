from __future__ import annotations

import pytest
from pydantic import ValidationError
from fastapi.testclient import TestClient
from PIL import Image
from io import BytesIO
import random
import json
from pathlib import Path

from visiondata_gate.api import create_app
from visiondata_gate.product_service import ProductService
from visiondata_gate.product_models import CreateTaskRequest
from visiondata_gate.contracts import OperatorAcceptanceRequirements

from visiondata_gate.compute_handoff import (
    ComputeHandoffError,
    ComputeHandoffRequest,
    OfflineComputeAdapter,
)


def request_payload():
    return {
        "request_key": "test-handoff-0001",
        "expected_preflight_sha256": "a" * 64,
        "review_note": "Reviewed this frozen dataset for a sandbox compute handoff",
        "operator_attests_reviewed": True,
        "workload": "TRAINING",
        "resources": {
            "runtime_image": "example.invalid/ascend/runtime@sha256:" + "b" * 64,
            "cann_version": "unverified-9.0",
            "npu_count": 1,
            "cpu_cores": 4,
            "memory_gib": 16,
            "max_wall_seconds": 3600,
        },
    }


def test_compute_request_has_explicit_bounded_resources_and_no_execution_fields():
    request = ComputeHandoffRequest.model_validate(request_payload())
    assert request.resources.npu_count == 1
    for changes in ({"operator_attests_reviewed": False}, {"command": "run"}):
        with pytest.raises(ValidationError):
            ComputeHandoffRequest.model_validate({**request_payload(), **changes})
    for field, value in (
        ("npu_count", 0),
        ("memory_gib", -1),
        ("runtime_image", "unversioned:latest"),
    ):
        payload = request_payload()
        payload["resources"][field] = value
        with pytest.raises(ValidationError):
            ComputeHandoffRequest.model_validate(payload)


def test_offline_adapter_never_submits_polls_or_cancels_remote_jobs():
    adapter = OfflineComputeAdapter()
    assert adapter.capabilities()["live_submission_available"] is False
    for operation in (
        lambda: adapter.submit({}),
        lambda: adapter.poll("job"),
        lambda: adapter.cancel("job"),
    ):
        with pytest.raises(ComputeHandoffError, match="CONNECTOR_NOT_CONFIGURED"):
            operation()


ACTOR = "usr_local_demo"
WORKSPACE = "wsp_local_demo"
HEADERS = {"X-Actor-User-Id": ACTOR}


def test_published_request_schemas_match_current_runtime_contracts():
    root = Path(__file__).resolve().parents[1] / "schemas"
    for name, model in (
        ("compute_handoff_request.v1.json", ComputeHandoffRequest),
        ("operator_acceptance_requirements.v1.json", OperatorAcceptanceRequirements),
    ):
        assert (
            json.loads((root / name).read_text(encoding="utf-8"))
            == model.model_json_schema()
        )


@pytest.fixture
def reviewed_task(tmp_path, request):
    options = getattr(request, "param", {})
    service = ProductService(tmp_path / "product", recover_interrupted=False)
    try:
        with TestClient(create_app(service, ensure_demo_tenant=True)) as client:
            created = client.post(
                "/v1/projects",
                headers=HEADERS,
                json={
                    "workspace_id": WORKSPACE,
                    "name": "Compute contract test",
                    "source_kind": "local_authorized_directory",
                    "scenario_profile": "industrial",
                },
            )
            assert created.status_code == 201, created.text
            project_id = created.json()["project_id"]
            rng = random.Random(71)
            image = Image.frombytes(
                "RGB",
                (64, 64),
                bytes(rng.randrange(60, 190) for _ in range(64 * 64 * 3)),
            )
            if options.get("dark"):
                image = Image.new("RGB", (64, 64), 0)
            buffer = BytesIO()
            image.save(buffer, format="PNG")
            uploaded = client.post(
                f"/v1/operator-workspaces/{WORKSPACE}/assets",
                params={"project_id": project_id},
                headers=HEADERS,
                files=[("files", ("compute-test.png", buffer.getvalue(), "image/png"))],
            )
            assert uploaded.status_code == 201, uploaded.text
            asset = uploaded.json()["assets"][0]
            response = client.put(
                f"/v1/operator-workspaces/{WORKSPACE}/assets/{asset['asset_id']}/annotations",
                headers=HEADERS,
                json={
                    "expected_revision": 0,
                    "annotations": [
                        {
                            "annotation_id": "box-test",
                            "label": "defect",
                            "x": 0.2,
                            "y": 0.2,
                            "width": 0.3,
                            "height": 0.3,
                        }
                    ],
                },
            )
            assert response.status_code == 200, response.text
            state = response.json()
            payload = {
                "workspace_id": WORKSPACE,
                "project_id": project_id,
                "operator_attests_authorized_use": True,
            }
            if not options.get("legacy"):
                payload["acceptance_requirements"] = {
                    "schema_version": "visiondata-gate.operator-acceptance-requirements.v1",
                    "purpose_description": "Prepare a reviewed sandbox dataset for compute handoff",
                    "category_vocabulary": ["defect"],
                    "samples": [
                        {
                            "asset_id": asset["asset_id"],
                            "split": "train",
                            "category": "defect",
                            "annotation_requirement": "REQUIRED",
                            "human_review": {
                                "reviewer_name": "Test Reviewer",
                                "note": "Reviewed under synthetic test labeling requirements",
                                "expected_asset_sha256": asset["source_sha256"],
                                "expected_annotation_revision": state["revision"],
                                "expected_annotation_sha256": state["document_sha256"],
                                "operator_attests_reviewed": True,
                            },
                        }
                    ],
                }
            frozen = client.post(
                "/v1/data-sources/operator-project-snapshots",
                headers=HEADERS,
                json=payload,
            )
            assert frozen.status_code == 201, frozen.text
            source = frozen.json()
            task = service.create_task(
                ACTOR,
                CreateTaskRequest(
                    project_id=project_id,
                    goal="Check all deterministic evidence before compute handoff",
                    source_kind="local_authorized_directory",
                    source_id=source["source_id"],
                    plan_approval_required=False,
                ),
                auto_start=False,
            )
            service.run_task_sync(task.task_id)
            yield client, service, task.task_id, source
    finally:
        service.close(wait=True)


def prepared(client, task_id):
    response = client.get(f"/v1/tasks/{task_id}/compute-preflight", headers=HEADERS)
    assert response.status_code == 200, response.text
    preflight = response.json()
    assert preflight["eligibility"] == "READY_FOR_OFFLINE_HANDOFF", preflight
    payload = request_payload()
    payload["expected_preflight_sha256"] = preflight["receipt_sha256"]
    result = client.post(
        f"/v1/tasks/{task_id}/compute-handoffs", headers=HEADERS, json=payload
    )
    assert result.status_code == 201, result.text
    return payload, result.json()


def test_real_reviewed_snapshot_prepares_and_reconciles_without_remote_execution(
    reviewed_task,
):
    client, service, task_id, source = reviewed_task
    before = service._annotation_context(ACTOR, task_id)[4].input_sha256
    payload, record = prepared(client, task_id)
    assert record["binding"]["source_id"] == source["source_id"]
    assert record["status"] == "PREPARED_NOT_SUBMITTED"
    assert record["remote_job_id"] is None and record["dataset_bytes_exported"] is False
    again = client.post(
        f"/v1/tasks/{task_id}/compute-handoffs", headers=HEADERS, json=payload
    )
    assert again.json() == record
    conflict = client.post(
        f"/v1/tasks/{task_id}/compute-handoffs",
        headers=HEADERS,
        json={
            **payload,
            "review_note": "A conflicting changed request must not silently replace the first",
        },
    )
    assert conflict.status_code == 409 and "IDEMPOTENCY_CONFLICT" in conflict.text
    listed = client.get(f"/v1/tasks/{task_id}/compute-handoffs", headers=HEADERS).json()
    assert len(listed["items"]) == 1 and listed["items"][0]["read_status"] == "VERIFIED"
    export = client.get(
        f"/v1/tasks/{task_id}/compute-handoffs/{record['handoff_id']}/export",
        headers=HEADERS,
    )
    assert export.json() == record
    assert service._annotation_context(ACTOR, task_id)[4].input_sha256 == before


def test_compute_rejects_foreign_actor_and_revoked_source(reviewed_task):
    client, service, task_id, source = reviewed_task
    _, record = prepared(client, task_id)
    assert (
        client.get(
            f"/v1/tasks/{task_id}/compute-preflight",
            headers={"X-Actor-User-Id": "outsider"},
        ).status_code
        == 404
    )
    from visiondata_gate.product_models import RevokeLocalSourceAuthorizationRequest

    service.revoke_local_source_authorization(
        ACTOR,
        source["source_id"],
        RevokeLocalSourceAuthorizationRequest(
            reason="Revoke synthetic compute source authorization",
            expected_latest_event_sha256=service.list_source_authorization_events(
                ACTOR, source["source_id"]
            )[-1].event_sha256,
        ),
    )
    listed = client.get(f"/v1/tasks/{task_id}/compute-handoffs", headers=HEADERS)
    assert listed.status_code == 200, listed.text
    assert listed.json()["items"][0]["read_status"] == "STALE_HOLD"
    assert (
        client.get(
            f"/v1/tasks/{task_id}/compute-handoffs/{record['handoff_id']}/export",
            headers=HEADERS,
        ).status_code
        == 409
    )


@pytest.mark.parametrize(
    "reviewed_task", [{"legacy": True}, {"dark": True}], indirect=True
)
def test_legacy_or_nonpassing_snapshot_cannot_prepare_compute(reviewed_task):
    client, _service, task_id, _source = reviewed_task
    preflight = client.get(
        f"/v1/tasks/{task_id}/compute-preflight", headers=HEADERS
    ).json()
    assert preflight["eligibility"] == "HOLD"
    payload = request_payload()
    payload["expected_preflight_sha256"] = preflight["receipt_sha256"]
    assert (
        client.post(
            f"/v1/tasks/{task_id}/compute-handoffs", headers=HEADERS, json=payload
        ).status_code
        == 409
    )


def test_persisted_compute_record_tamper_is_not_exportable(reviewed_task):
    client, service, task_id, _source = reviewed_task
    prepared(client, task_id)
    with service.store._connection() as connection:
        connection.execute(
            "UPDATE compute_handoffs SET record_json = replace(record_json, 'PREPARED_NOT_SUBMITTED', 'RUNNING') WHERE task_id=?",
            (task_id,),
        )
    response = client.get(f"/v1/tasks/{task_id}/compute-handoffs", headers=HEADERS)
    assert response.status_code == 409 and "HANDOFF_INTEGRITY_HOLD" in response.text
