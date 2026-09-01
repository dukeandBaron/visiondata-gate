from __future__ import annotations

from pathlib import Path

from fastapi.testclient import TestClient

from visiondata_gate.api import create_app
from visiondata_gate.incident_interaction import (
    IncidentInteractionReceipt,
    IncidentInteractionTurn,
    IncidentQuestionResolution,
)
from visiondata_gate.product_service import ProductService


def _interaction_receipt() -> IncidentInteractionReceipt:
    parent_sha = "1" * 64
    decision_sha = "2" * 64
    child_sha = "3" * 64
    consumption_sha = "4" * 64
    return IncidentInteractionReceipt(
        interaction_id="interaction_0123456789abcdefabcd",
        task_id="tsk_0123456789abcdefabcd",
        parent_case_id="incident_0123456789abcdefabcd",
        parent_case_sha256=parent_sha,
        decision_id="incident_decision_0123456789abcdefabcd",
        decision_sha256=decision_sha,
        child_case_id="incident_abcdef0123456789abcd",
        child_case_sha256=child_sha,
        consumption_sha256=consumption_sha,
        turns=[
            IncidentInteractionTurn(
                sequence=1,
                actor_kind="AGENT",
                actor_id="IncidentCoordinatorAgent",
                action="PAUSE_FOR_STRUCTURED_HUMAN_INPUT",
                input_refs=[parent_sha],
                output_refs=["question_012345abcdef"],
            ),
            IncidentInteractionTurn(
                sequence=2,
                actor_kind="HUMAN",
                actor_id="usr_quality_owner",
                action="CONTINUE_HOLD",
                input_refs=[parent_sha],
                output_refs=[decision_sha],
            ),
            IncidentInteractionTurn(
                sequence=3,
                actor_kind="AGENT",
                actor_id="IncidentCoordinatorAgent",
                action="RESUME_WITH_BOUND_DECISION",
                input_refs=[parent_sha, decision_sha],
                output_refs=[child_sha],
            ),
        ],
        admitted_evidence_refs=[],
        question_resolutions=[
            IncidentQuestionResolution(
                question_id="question_012345abcdef",
                expected_evidence_type="opcua_snapshot",
                disposition="REMAINS_OPEN",
                supporting_refs=[],
            )
        ],
        answered_by_evidence_count=0,
        satisfied_by_human_decision_count=0,
        remaining_open_question_count=1,
        interaction_status="RESUMED_WITH_OPEN_QUESTIONS",
        receipt_sha256="5" * 64,
    )


def test_interaction_receipt_route_is_read_only_and_sha_bound(
    tmp_path: Path,
    monkeypatch,
) -> None:
    service = ProductService(tmp_path / "product", recover_interrupted=False)
    receipt = _interaction_receipt()
    monkeypatch.setattr(
        service,
        "get_industrial_incident_interaction_receipt",
        lambda actor, task_id, child_case_id: receipt,
    )
    client = TestClient(create_app(service, ensure_demo_tenant=False))

    response = client.get(
        f"/v1/tasks/{receipt.task_id}/industrial-incidents/"
        f"{receipt.child_case_id}/interaction-receipt",
        headers={
            "X-Actor-User-Id": "usr_quality_owner",
            "Origin": "http://127.0.0.1:4173",
        },
    )

    assert response.status_code == 200
    assert response.json()["interaction_id"] == receipt.interaction_id
    assert response.headers["etag"] == f'"{receipt.receipt_sha256}"'
    assert response.headers["x-incident-interaction-sha256"] == receipt.receipt_sha256
    assert response.headers["cache-control"] == "private, no-store"
    exposed = {
        item.strip()
        for item in response.headers["access-control-expose-headers"].split(",")
    }
    assert "X-Incident-Interaction-SHA256" in exposed
    assert response.request.method == "GET"
    service.close(wait=True)


def test_interaction_receipt_route_is_declared_in_openapi(tmp_path: Path) -> None:
    service = ProductService(tmp_path / "product", recover_interrupted=False)
    client = TestClient(create_app(service, ensure_demo_tenant=False))
    path = "/v1/tasks/{task_id}/industrial-incidents/{case_id}/interaction-receipt"

    operation = client.get("/openapi.json").json()["paths"][path]

    assert set(operation) == {"get"}
    assert (
        operation["get"]["responses"]["200"]["content"]["application/json"]["schema"][
            "$ref"
        ]
        == "#/components/schemas/IncidentInteractionReceipt"
    )
    service.close(wait=True)
