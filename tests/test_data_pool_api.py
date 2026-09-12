from __future__ import annotations

from fastapi import FastAPI
from fastapi.testclient import TestClient

from tests.test_data_pool import _qualified_request
from tests.test_learning_lifecycle import ACTOR


pytest_plugins = ("tests.test_learning_lifecycle",)


def test_data_pool_routes_use_host_identity_and_emit_strong_receipts(
    learning_input,
) -> None:
    from visiondata_gate.data_pool_api import install_data_pool_routes

    _host_client, product, (task_id, _preflight, _groups) = learning_input
    app = FastAPI()
    install_data_pool_routes(app, lambda: ACTOR, lambda: product)
    request = _qualified_request(product, task_id, request_key="pool-api-create-0001")

    with TestClient(app) as client:
        response = client.post(
            f"/v1/tasks/{task_id}/data-pools",
            headers={"X-Actor-User-Id": "must-not-be-trusted"},
            json=request.model_dump(mode="json"),
        )
        assert response.status_code == 201, response.text
        created = response.json()
        assert response.headers["etag"] == f'"{created["receipt_sha256"]}"'
        assert response.headers["x-content-sha256"] == created["receipt_sha256"]
        pool_id = created["pool"]["pool_id"]
        version_id = created["current_version"]["version_id"]
        listed = client.get(f"/v1/tasks/{task_id}/data-pools")
        assert listed.status_code == 200
        assert listed.json()["items"][0]["pool"]["pool_id"] == pool_id
        version = client.get(f"/v1/data-pool-versions/{version_id}")
        assert version.status_code == 200
        assert version.json()["version"]["version_id"] == version_id
        found = client.get(
            f"/v1/projects/{created['pool']['project_id']}/"
            "data-pool-operations/create/pool-api-create-0001",
            params={"target_id": task_id},
        )
        assert found.status_code == 200
        assert found.json()["lookup_status"] == "FOUND"
        assert found.json()["result_type"] == "pool"
        missing = client.get(
            f"/v1/projects/{created['pool']['project_id']}/"
            "data-pool-operations/create/pool-api-missing-001",
            params={"target_id": task_id},
        )
        assert missing.status_code == 200
        assert missing.json()["lookup_status"] == "NOT_FOUND"
        assert missing.json()["execution_status"] == "UNKNOWN_NOT_PROOF_OF_NO_WRITE"
        assert missing.json()["automatic_retry_allowed"] is False
        assert response.headers["cache-control"] == "private, no-store"

        pool_id = created["pool"]["pool_id"]
        current = client.get(
            f"/v1/data-pools/{pool_id}",
            headers={"X-Actor-User-Id": "still-not-trusted"},
        )
        assert current.status_code == 200, current.text
        assert current.json()["pool"]["created_by"] == ACTOR

        lookup = client.get(
            f"/v1/projects/{created['pool']['project_id']}/data-pool-operations/create/"
            "pool-api-create-0001",
            params={"target_id": task_id},
        )
        assert lookup.status_code == 200, lookup.text
        assert lookup.json()["lookup_status"] == "FOUND"
        assert lookup.json()["automatic_retry_allowed"] is False
