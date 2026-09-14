import hashlib

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from tests import test_learning_lifecycle as lifecycle
from visiondata_gate.api import create_app
from visiondata_gate.audit_envelope import canonical_jcs_bytes
from visiondata_gate.learning_api import install_learning_routes
from visiondata_gate.learning_dataset import DatasetError
from visiondata_gate.learning_service import LearningError

HEADERS = lifecycle.HEADERS
learning_input = lifecycle.learning_input


def _create_payload(preflight, groups, **overrides):
    return {
        "request_key": "api-cycle-create-0001",
        "expected_preflight_sha256": preflight["receipt_sha256"],
        "groups": groups,
        "operator_attests_training_authorized": True,
        "review_note": "Authorize the synthetic local CPU learning protocol",
        **overrides,
    }


def _sealed(response, expected_status=200):
    assert response.status_code == expected_status, response.text
    value = response.json()
    digest = hashlib.sha256(canonical_jcs_bytes({
        key: item for key, item in value.items() if key != "receipt_sha256"
    })).hexdigest()
    assert value["receipt_sha256"] == digest
    assert response.headers["etag"] == f'"{digest}"'
    assert response.headers["x-content-sha256"] == digest
    assert response.headers["cache-control"] == "private, no-store"
    return value


def _action(cycle, key, **extra):
    return {
        "request_key": key,
        "expected_cycle_sha256": cycle["receipt_sha256"],
        "review_note": "Reviewed the synthetic local sandbox operation",
        "operator_attests_reviewed": True,
        **extra,
    }


def test_learning_routes_use_real_authentication_and_etag(learning_input):
    client, product, (task_id, preflight, groups) = learning_input
    endpoint = f"/v1/tasks/{task_id}/learning-cycles"
    payload = {"request_key":"api-learning-create-001", "expected_preflight_sha256":preflight["receipt_sha256"],
               "groups":groups,"operator_attests_training_authorized":True,
               "review_note":"Explicit local CPU reference run authorization"}
    outsider=client.post(endpoint,headers={"X-Actor-User-Id":"outsider"},json=payload)
    assert outsider.status_code == 404
    response=client.post(endpoint,headers=HEADERS,json=payload)
    assert response.status_code==201,response.text
    cycle=response.json()
    read=client.get(f"/v1/learning-cycles/{cycle['cycle_id']}",headers=HEADERS)
    assert read.status_code==200
    assert read.headers["etag"]==f'"{read.json()["receipt_sha256"]}"'
    assert client.get(f"/v1/learning-cycles/{cycle['cycle_id']}",headers={"X-Actor-User-Id":"outsider"}).status_code==404
    invalid=client.post(endpoint,headers=HEADERS,json=payload|{"command":"arbitrary command"})
    assert invalid.status_code==422


def test_learning_http_real_train_feedback_selection_rollback_and_finalize(learning_input):
    client, _product, (task_id, preflight, groups) = learning_input
    cycle = _sealed(client.post(
        f"/v1/tasks/{task_id}/learning-cycles", headers=HEADERS,
        json=_create_payload(preflight, groups, training={"epochs": 250, "learning_rate": 1.5}, max_total_epochs=800),
    ), 201)
    cycle_path = f"/v1/learning-cycles/{cycle['cycle_id']}"
    listing = client.get(f"/v1/projects/{cycle['project_id']}/learning-cycles", headers=HEADERS)
    assert listing.status_code == 200
    assert [item["cycle_id"] for item in listing.json()] == [cycle["cycle_id"]]
    assert listing.headers["cache-control"] == "private, no-store"
    initial = _sealed(client.get(f"/v1/learning-models/{cycle['initial_model_id']}", headers=HEADERS))
    assert initial["weights"]["weights"] == [0.0] * 6
    execute = {
        **_create_payload(preflight, groups, request_key="api-round-execute-001"),
        "task_id": task_id,
        "expected_cycle_sha256": cycle["receipt_sha256"],
    }
    run = _sealed(client.post(cycle_path + "/rounds", headers=HEADERS, json=execute))
    assert run["status"] == "COMPLETED", run
    assert run["training"]["loss_after"] < run["training"]["loss_before"]
    assert run["evaluation"]["decision"] == "ELIGIBLE"
    assert _sealed(client.post(cycle_path + "/rounds", headers=HEADERS, json=execute)) == run
    assert _sealed(client.get(f"/v1/learning-runs/{run['run_id']}", headers=HEADERS)) == run
    trained = _sealed(client.get(f"/v1/learning-models/{run['model_id']}", headers=HEADERS))
    assert trained["model_sha256"] == hashlib.sha256(canonical_jcs_bytes(trained["weights"])).hexdigest()
    assert trained["model_sha256"] != initial["model_sha256"]

    outsider = {"X-Actor-User-Id": "outsider"}
    for endpoint in (
        f"/v1/learning-runs/{run['run_id']}",
        f"/v1/learning-models/{run['model_id']}",
        f"/v1/projects/{cycle['project_id']}/learning-cycles",
    ):
        assert client.get(endpoint, headers=outsider).status_code == 404
    assert run["feedback"], "fixture must exercise real prediction-error review through HTTP"
    for item in list(run["feedback"]):
        cycle = _sealed(client.get(cycle_path, headers=HEADERS))
        review = _action(cycle, "review-" + item["feedback_id"], classification="HARD_SAMPLE")
        review_path = cycle_path + f"/runs/{run['run_id']}/feedback/{item['feedback_id']}"
        assert client.post(review_path, headers=outsider, json=review).status_code == 404
        run = _sealed(client.post(review_path, headers=HEADERS, json=review))
        reviewed = next(row for row in run["feedback"] if row["feedback_id"] == item["feedback_id"])
        assert reviewed["status"] == "TRIAGED_NOT_AUTO_INGESTED"
        assert reviewed["training_ingestion_allowed"] is False

    cycle = _sealed(client.get(cycle_path, headers=HEADERS))
    selection = _action(cycle, "api-model-select-001", expected_run_sha256=run["receipt_sha256"], action="APPROVE_SANDBOX")
    selection_path = cycle_path + f"/runs/{run['run_id']}/selection"
    assert client.post(selection_path, headers=outsider, json=selection).status_code == 404
    cycle = _sealed(client.post(selection_path, headers=HEADERS, json=selection))
    assert cycle["champion_model_id"] == run["model_id"]
    cycle = _sealed(client.post(cycle_path + "/rollback", headers=HEADERS,
        json=_action(cycle, "api-model-rollback-001", model_id=cycle["initial_model_id"])))
    assert cycle["champion_model_id"] == cycle["initial_model_id"]
    cycle = _sealed(client.post(cycle_path + "/rollback", headers=HEADERS,
        json=_action(cycle, "api-model-restore-001", model_id=run["model_id"])))
    finalized = _sealed(client.post(cycle_path + "/finalize", headers=HEADERS,
        json=_action(cycle, "api-cycle-finalize-001")))
    assert finalized["status"] == "FINALIZED"
    assert finalized["final_evaluation"]["split"] == "test"
    assert finalized["final_evaluation"]["sample_results"] == []
    assert finalized["production_release_allowed"] is False
    assert finalized["remote_execution_verified"] is False


def test_learning_auth_reuses_bound_session_and_never_trusts_actor_header(learning_input, monkeypatch):
    _client, product, (task_id, preflight, groups) = learning_input
    token = "synthetic-learning-session-token-over-32-characters"
    monkeypatch.setenv("VISIONDATA_INSECURE_TEST_ACTOR_HEADER_BYPASS", "false")
    monkeypatch.setenv("VISIONDATA_SESSION_TOKEN", token)
    monkeypatch.setenv("VISIONDATA_SESSION_ACTOR_USER_ID", "usr_local_demo")
    endpoint = f"/v1/tasks/{task_id}/learning-cycles"
    payload = _create_payload(preflight, groups)
    with TestClient(create_app(product)) as client:
        assert client.post(endpoint, headers=HEADERS, json=payload).status_code == 401
        assert client.post(endpoint, headers={"X-VisionData-Session-Token": "wrong"}, json=payload).status_code == 401
        assert client.post(endpoint, headers={"X-VisionData-Session-Token": token, "X-Actor-User-Id": "outsider"}, json=payload).status_code == 403
        assert not (product.product_root / "learning").exists()
        cycle = _sealed(client.post(endpoint, headers={"X-VisionData-Session-Token": token}, json=payload), 201)
        assert cycle["created_by"] == "usr_local_demo"


@pytest.mark.parametrize("error_type,code", [(LearningError, "learning_hold"), (DatasetError, "learning_dataset_hold")])
def test_learning_errors_are_fixed_409_without_local_path_echo(learning_input, monkeypatch, error_type, code):
    client, _product, (task_id, preflight, groups) = learning_input
    from visiondata_gate import learning_api

    def fail(_product):
        error = error_type("E:/synthetic-private-root/secret-file.json must never be echoed")
        error.code = "untrusted-error-code-with-private-path"
        raise error

    monkeypatch.setattr(learning_api, "LearningService", fail)
    response = client.post(f"/v1/tasks/{task_id}/learning-cycles", headers=HEADERS,
        json=_create_payload(preflight, groups))
    assert response.status_code == 409
    assert response.json()["error"]["code"] == code
    assert "synthetic-private-root" not in response.text
    assert "secret-file" not in response.text
    assert "untrusted-error-code" not in response.text
    assert response.headers["cache-control"] == "private, no-store"


def test_learning_model_get_checks_actual_artifact_bytes(learning_input):
    client, product, (task_id, preflight, groups) = learning_input
    cycle = _sealed(client.post(f"/v1/tasks/{task_id}/learning-cycles", headers=HEADERS,
        json=_create_payload(preflight, groups)), 201)
    endpoint = f"/v1/learning-models/{cycle['initial_model_id']}"
    _sealed(client.get(endpoint, headers=HEADERS))
    artifact = product.product_root / "learning" / cycle["cycle_id"] / (cycle["initial_model_id"] + ".json")
    artifact.write_text("{}", encoding="utf-8")
    response = client.get(endpoint, headers=HEADERS)
    assert response.status_code == 409
    assert response.json()["error"]["code"] == "learning_hold"
    assert str(artifact) not in response.text


def test_learning_cancel_recover_and_schema_boundaries(learning_input):
    client, _product, (task_id, preflight, groups) = learning_input
    cycle = _sealed(client.post(f"/v1/tasks/{task_id}/learning-cycles", headers=HEADERS,
        json=_create_payload(preflight, groups)), 201)
    cycle_path = f"/v1/learning-cycles/{cycle['cycle_id']}"
    extra = client.post(cycle_path + "/cancel", headers=HEADERS,
        json=_action(cycle, "api-cancel-extra-001", command="do-not-execute"))
    assert extra.status_code == 422
    assert "do-not-execute" not in extra.text
    assert _sealed(client.get(cycle_path, headers=HEADERS))["receipt_sha256"] == cycle["receipt_sha256"]
    recovery = client.post(cycle_path + "/recover", headers=HEADERS,
        json=_action(cycle, "api-recover-none-001"))
    assert recovery.status_code == 409
    assert recovery.json()["error"]["code"] == "learning_hold"
    stopped = _sealed(client.post(cycle_path + "/cancel", headers=HEADERS,
        json=_action(cycle, "api-cancel-valid-001")))
    assert stopped["status"] == "STOPPED"
    schema = client.get("/openapi.json").json()
    for name in ("CreateLearningCycle", "RunLearningRound", "CycleAction", "ModelSelection", "FeedbackReview", "RollbackModel"):
        assert schema["components"]["schemas"][name]["additionalProperties"] is False
    assert schema["paths"]["/v1/tasks/{task_id}/learning-cycles"]["post"]["requestBody"]["content"]["application/json"]["schema"]["$ref"].endswith("/CreateLearningCycle")


def test_learning_route_installation_is_lazy_and_uses_supplied_dependencies(monkeypatch):
    from visiondata_gate import learning_api

    product = object()
    observations = []

    class ServiceProbe:
        def __init__(self, supplied_product):
            assert supplied_product is product
            observations.append("constructed")

        def list_cycles(self, actor, project_id):
            observations.append((actor, project_id))
            return []

    monkeypatch.setattr(learning_api, "LearningService", ServiceProbe)
    app = FastAPI()
    install_learning_routes(app, lambda: "injected-principal", lambda: product)
    assert observations == []
    with TestClient(app) as client:
        for _ in range(2):
            response = client.get("/v1/projects/project-probe/learning-cycles", headers={"X-Actor-User-Id": "forged-principal"})
            assert response.status_code == 200
            assert response.json() == []
    assert observations == ["constructed", ("injected-principal", "project-probe")] * 2
