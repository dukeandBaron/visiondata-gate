from __future__ import annotations

from pathlib import Path

from fastapi.testclient import TestClient

from tests.support.product_run_stub import make_product_lifecycle_stub_runner
from visiondata_gate.api import create_app
from visiondata_gate.demo_fixtures import build_fixture_industrial_incident_request
from visiondata_gate.goal3_bridge import verify_goal3_handoff_receipt
from visiondata_gate.product_models import CreateTaskRequest
from visiondata_gate.product_service import ProductService


def _completed_task(service: ProductService):
    actor, _, project = service.ensure_default_tenant()
    task = service.create_task(
        actor.user_id,
        CreateTaskRequest(
            project_id=project.project_id,
            goal="验证 Goal 任务到 Goal3 工业案件入口的真实交接状态。",
        ),
        auto_start=False,
    )
    return actor.user_id, service.run_task_sync(task.task_id)


def test_goal3_handoff_waits_for_completed_sha_verified_task(tmp_path: Path) -> None:
    service = ProductService(
        tmp_path / "product",
        runner=make_product_lifecycle_stub_runner(),
        recover_interrupted=False,
    )
    actor, _, project = service.ensure_default_tenant()
    task = service.create_task(
        actor.user_id,
        CreateTaskRequest(
            project_id=project.project_id,
            goal="先建立任务合同，但不在证据包形成前开放 Goal3 入口。",
        ),
        auto_start=False,
    )

    receipt = service.goal3_handoff_receipt(actor.user_id, task.task_id)

    assert receipt.handoff_status == "WAITING_FOR_TASK_COMPLETION"
    assert receipt.task_evidence_integrity == "UNAVAILABLE"
    assert receipt.incident_intake_permitted is False
    assert receipt.incident_count == 0
    assert receipt.production_release_allowed is False
    assert receipt.machine_write_permitted is False
    verify_goal3_handoff_receipt(receipt)


def test_goal3_handoff_binds_ready_task_and_latest_incident(tmp_path: Path) -> None:
    service = ProductService(
        tmp_path / "product",
        runner=make_product_lifecycle_stub_runner(),
        recover_interrupted=False,
    )
    actor, task = _completed_task(service)

    ready = service.goal3_handoff_receipt(actor, task.task_id)
    assert ready.handoff_status == "READY_FOR_INCIDENT_INTAKE"
    assert ready.task_evidence_integrity == "VERIFIED"
    assert ready.task_evidence_sha256 == task.evidence_sha256
    assert ready.incident_intake_permitted is True
    verify_goal3_handoff_receipt(ready)

    incident = service.create_industrial_incident_case(
        actor,
        task.task_id,
        build_fixture_industrial_incident_request(),
    )
    active = service.goal3_handoff_receipt(actor, task.task_id)

    assert active.handoff_status == "INCIDENT_CHAIN_ACTIVE"
    assert active.incident_count == 1
    assert active.latest_case_id == incident.case_id
    assert active.latest_case_sha256 == incident.case_sha256
    assert active.latest_case_version == incident.case_version
    assert active.latest_case_status == incident.status.value
    assert active.latest_case_recommendation == incident.recommendation.value
    verify_goal3_handoff_receipt(active)


def test_goal3_handoff_fails_closed_when_task_evidence_drifts(tmp_path: Path) -> None:
    service = ProductService(
        tmp_path / "product",
        runner=make_product_lifecycle_stub_runner(),
        recover_interrupted=False,
    )
    actor, task = _completed_task(service)
    evidence_path = service.product_root / str(task.evidence_zip_rel)
    evidence_path.write_bytes(evidence_path.read_bytes() + b"drift")

    receipt = service.goal3_handoff_receipt(actor, task.task_id)

    assert receipt.handoff_status == "BLOCKED_EVIDENCE_INTEGRITY"
    assert receipt.task_evidence_integrity == "FAILED"
    assert receipt.incident_intake_permitted is False
    verify_goal3_handoff_receipt(receipt)


def test_goal3_handoff_api_exposes_bound_receipt(tmp_path: Path) -> None:
    service = ProductService(
        tmp_path / "product",
        runner=make_product_lifecycle_stub_runner(),
        recover_interrupted=False,
    )
    actor, task = _completed_task(service)
    client = TestClient(create_app(service, ensure_demo_tenant=False))

    response = client.get(
        f"/v1/tasks/{task.task_id}/goal3-handoff",
        headers={"X-Actor-User-Id": actor},
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["handoff_status"] == "READY_FOR_INCIDENT_INTAKE"
    assert response.headers["x-goal3-handoff-sha256"] == payload["receipt_sha256"]
    assert response.headers["etag"] == f'"{payload["receipt_sha256"]}"'
    assert response.headers["cache-control"] == "private, no-store"


def test_incident_intake_can_bind_expected_goal3_handoff_and_rejects_stale_receipt(
    tmp_path: Path,
) -> None:
    service = ProductService(
        tmp_path / "product",
        runner=make_product_lifecycle_stub_runner(),
        recover_interrupted=False,
    )
    actor, task = _completed_task(service)
    client = TestClient(create_app(service, ensure_demo_tenant=False))
    ready = service.goal3_handoff_receipt(actor, task.task_id)
    payload = build_fixture_industrial_incident_request().model_dump(mode="json")

    created = client.post(
        f"/v1/tasks/{task.task_id}/industrial-incidents",
        headers={
            "X-Actor-User-Id": actor,
            "Idempotency-Key": "goal3-bound-intake-1",
            "X-Goal3-Handoff-SHA256": ready.receipt_sha256,
        },
        json=payload,
    )

    assert created.status_code == 201
    assert created.json()["task_id"] == task.task_id

    stale = client.post(
        f"/v1/tasks/{task.task_id}/industrial-incidents",
        headers={
            "X-Actor-User-Id": actor,
            "Idempotency-Key": "goal3-bound-intake-2",
            "X-Goal3-Handoff-SHA256": ready.receipt_sha256,
        },
        json=payload,
    )

    assert stale.status_code == 409
    assert "handoff receipt changed" in stale.json()["error"]["message"]
    assert len(service.list_industrial_incident_cases(actor, task.task_id)) == 1
