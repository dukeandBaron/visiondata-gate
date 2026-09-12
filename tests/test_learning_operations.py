from __future__ import annotations

import hashlib
import json

import pytest
from fastapi.testclient import TestClient

from tests.test_learning_lifecycle import ACTOR, HEADERS, WORKSPACE, make_task
from visiondata_gate.api import create_app
from visiondata_gate.audit_envelope import canonical_jcs_bytes
from visiondata_gate.learning_contracts import (
    CreateLearningCycle,
    FeedbackReview,
    ModelSelection,
    RunLearningRound,
)
from visiondata_gate.learning_operations import read_learning_operation
from visiondata_gate.learning_service import LearningError, LearningService
from visiondata_gate.product_service import ProductService
from visiondata_gate.task_store import NotFoundError


def sha(value):
    return hashlib.sha256(canonical_jcs_bytes(value)).hexdigest()


def verify_receipt(value):
    assert value["receipt_sha256"] == sha(
        {key: item for key, item in value.items() if key != "receipt_sha256"}
    )
    assert value["result_semantics"] == "CURRENT_RESULT"
    assert value["automatic_retry_allowed"] is False


@pytest.fixture(scope="module")
def operation_records(tmp_path_factory):
    """Create/train/review/select once with real synthetic local service data."""
    product = ProductService(
        tmp_path_factory.mktemp("operation-records") / "product",
        recover_interrupted=False,
    )
    with pytest.MonkeyPatch.context() as environment:
        for name in (
            "VISIONDATA_SESSION_TOKEN",
            "VISIONDATA_DESKTOP_SESSION_TOKEN",
            "VISIONDATA_SESSION_ACTOR_USER_ID",
        ):
            environment.delenv(name, raising=False)
        environment.setenv("VISIONDATA_INSECURE_TEST_ACTOR_HEADER_BYPASS", "true")
        try:
            with TestClient(create_app(product)) as client:
                task_id, preflight, groups = make_task(client, product)
                service = LearningService(product)
                create = CreateLearningCycle(
                    request_key="operation-create-0001",
                    expected_preflight_sha256=preflight["receipt_sha256"],
                    groups=groups,
                    operator_attests_training_authorized=True,
                    review_note="Authorize one synthetic local operation lookup fixture",
                    training={"epochs": 250, "learning_rate": 1.5},
                    max_total_epochs=800,
                )
                original_cycle = service.create_cycle(ACTOR, task_id, create)
                cycle_id = original_cycle["cycle_id"]
                train = RunLearningRound(
                    request_key="operation-train-0001",
                    task_id=task_id,
                    groups=groups,
                    expected_preflight_sha256=preflight["receipt_sha256"],
                    expected_cycle_sha256=original_cycle["receipt_sha256"],
                    operator_attests_training_authorized=True,
                    review_note="Execute real local model training for operation evidence",
                )
                run = service.run_round(ACTOR, cycle_id, train)
                assert run["status"] == "COMPLETED", run
                assert run["evaluation"]["decision"] == "ELIGIBLE"
                assert run["feedback"], (
                    "the fixture must exercise actual feedback review"
                )
                feedback_requests = []
                for item in list(run["feedback"]):
                    cycle = service.get_cycle(ACTOR, cycle_id)
                    review = FeedbackReview(
                        request_key="operation-" + item["feedback_id"],
                        expected_cycle_sha256=cycle["receipt_sha256"],
                        operator_attests_reviewed=True,
                        classification="HARD_SAMPLE",
                        review_note="Generated masks reviewed; no automatic training ingestion",
                    )
                    run = service.review_feedback(
                        ACTOR, cycle_id, run["run_id"], item["feedback_id"], review
                    )
                    feedback_requests.append((item["feedback_id"], review))
                cycle = service.get_cycle(ACTOR, cycle_id)
                select = ModelSelection(
                    request_key="operation-select-0001",
                    expected_cycle_sha256=cycle["receipt_sha256"],
                    expected_run_sha256=run["receipt_sha256"],
                    operator_attests_reviewed=True,
                    action="APPROVE_SANDBOX",
                    review_note="Review this candidate only for local sandbox use",
                )
                selected = service.select_model(ACTOR, cycle_id, run["run_id"], select)
                other = client.post(
                    "/v1/projects",
                    headers=HEADERS,
                    json={
                        "workspace_id": WORKSPACE,
                        "name": "Separate lookup project",
                        "source_kind": "local_authorized_directory",
                        "scenario_profile": "industrial",
                    },
                )
                assert other.status_code == 201
                yield {
                    "product": product,
                    "service": service,
                    "task_id": task_id,
                    "project_id": selected["project_id"],
                    "other_project_id": other.json()["project_id"],
                    "cycle_id": cycle_id,
                    "run_id": run["run_id"],
                    "original_cycle": original_cycle,
                    "create": create,
                    "train": train,
                    "feedback": feedback_requests[0],
                    "select": select,
                }
        finally:
            product.close(wait=True)


def lookup(records, operation, request_key, target_id, **overrides):
    return read_learning_operation(
        records["product"],
        overrides.get("actor", ACTOR),
        overrides.get("project_id", records["project_id"]),
        operation,
        request_key,
        target_id,
    )


@pytest.mark.parametrize(
    "operation,target_field,result_kind",
    [
        ("create", "task_id", "cycle"),
        ("train", "cycle_id", "run"),
        ("select", "run_id", "cycle"),
    ],
)
def test_real_operations_return_server_request_digest_and_current_record(
    operation_records, operation, target_field, result_kind
):
    records = operation_records
    request = records[operation]
    result = lookup(records, operation, request.request_key, records[target_field])
    verify_receipt(result)
    assert result["lookup_status"] == "FOUND"
    assert result["request_sha256"] == sha(request.model_dump(mode="json"))
    assert result["request_digest_semantics"] == "SERVER_CANONICAL_VALIDATED_REQUEST"
    assert result["result_kind"] == result_kind
    assert result["execution_status"] == "RESULT_AVAILABLE"
    current = (
        records["service"].get_cycle(ACTOR, records["cycle_id"])
        if result_kind == "cycle"
        else records["service"].get_run(ACTOR, records["run_id"])
    )
    assert result["current_result"] == current
    assert result["result_receipt_sha256"] == current["receipt_sha256"]
    if operation == "create":
        assert (
            result["current_result"]["receipt_sha256"]
            != records["original_cycle"]["receipt_sha256"]
        )
        assert "evaluation" in result["current_result"]["request"]


def test_real_feedback_scope_is_feedback_id_not_cycle_id(operation_records):
    records = operation_records
    feedback_id, request = records["feedback"]
    result = lookup(records, "feedback", request.request_key, feedback_id)
    verify_receipt(result)
    assert result["lookup_status"] == "FOUND"
    assert result["result_kind"] == "run"
    assert result["result_id"] == records["run_id"]
    assert result["request_sha256"] == sha(request.model_dump(mode="json"))
    assert any(
        item["feedback_id"] == feedback_id
        and item["status"] == "TRIAGED_NOT_AUTO_INGESTED"
        for item in result["current_result"]["feedback"]
    )
    wrong_scope = lookup(records, "feedback", request.request_key, records["cycle_id"])
    assert wrong_scope["lookup_status"] == "NOT_FOUND"
    assert wrong_scope["execution_status"] == "UNKNOWN_NOT_PROOF_OF_NO_WRITE"


@pytest.mark.parametrize(
    "operation",
    [
        "create",
        "train",
        "feedback",
        "select",
        "rollback",
        "cancel",
        "recover",
        "finalize",
        "followup",
    ],
)
def test_unknown_request_never_proves_absence_or_allows_replay(
    operation_records, operation
):
    result = lookup(
        operation_records,
        operation,
        "not-observed-request-001",
        "target-not-yet-remembered",
    )
    verify_receipt(result)
    assert result["lookup_status"] == "NOT_FOUND"
    assert result["execution_status"] == "UNKNOWN_NOT_PROOF_OF_NO_WRITE"
    assert result["request_sha256"] is None
    assert result["current_result"] is None
    assert result["result_id"] is None
    assert result["result_receipt_sha256"] is None


def test_foreign_actor_and_foreign_project_do_not_leak_request_results(
    operation_records,
):
    records = operation_records
    with pytest.raises(NotFoundError):
        lookup(
            records,
            "create",
            records["create"].request_key,
            records["task_id"],
            actor="outsider",
        )
    result = lookup(
        records,
        "create",
        records["create"].request_key,
        records["task_id"],
        project_id=records["other_project_id"],
    )
    assert result["lookup_status"] == "NOT_FOUND"
    assert result["current_result"] is None
    assert records["cycle_id"] not in json.dumps(result)


@pytest.mark.parametrize("status", ["RUNNING", "FINALIZING"])
def test_pending_current_result_is_not_fabricated_as_completed(
    operation_records, status
):
    records = operation_records
    service, product = records["service"], records["product"]
    original = service.get_cycle(ACTOR, records["cycle_id"])
    try:
        with product.store._connection(immediate=True) as connection:
            service._put(
                connection, "cycle", original | {"status": status}, replace=True
            )
        result = lookup(
            records, "create", records["create"].request_key, records["task_id"]
        )
        verify_receipt(result)
        assert result["execution_status"] == "PENDING"
        assert result["current_result"]["status"] == status
    finally:
        with product.store._connection(immediate=True) as connection:
            service._put(connection, "cycle", original, replace=True)


def test_tampered_current_record_is_rejected(operation_records):
    records = operation_records
    product = records["product"]
    with product.store._connection() as connection:
        original = connection.execute(
            "SELECT record_json FROM learning_records WHERE id=?",
            (records["cycle_id"],),
        ).fetchone()[0]
    try:
        changed = json.loads(original)
        changed["status"] = "FINALIZED"
        with product.store._connection(immediate=True) as connection:
            connection.execute(
                "UPDATE learning_records SET record_json=? WHERE id=?",
                (json.dumps(changed), records["cycle_id"]),
            )
        with pytest.raises(LearningError, match="LEARNING_RECORD_INTEGRITY_HOLD"):
            lookup(records, "create", records["create"].request_key, records["task_id"])
    finally:
        with product.store._connection(immediate=True) as connection:
            connection.execute(
                "UPDATE learning_records SET record_json=? WHERE id=?",
                (original, records["cycle_id"]),
            )


@pytest.mark.parametrize("digest", ["not-a-digest", "0" * 64])
def test_invalid_or_mismatching_create_request_digest_is_rejected(
    operation_records, digest
):
    records = operation_records
    request = records["create"]
    try:
        with records["product"].store._connection(immediate=True) as connection:
            connection.execute(
                "UPDATE learning_requests SET request_sha=? WHERE scope=? AND operation=? AND actor=? AND request_key=?",
                (digest, records["task_id"], "create", ACTOR, request.request_key),
            )
        with pytest.raises(
            LearningError, match="LEARNING_OPERATION_REQUEST_INTEGRITY_HOLD"
        ):
            lookup(records, "create", request.request_key, records["task_id"])
    finally:
        with records["product"].store._connection(immediate=True) as connection:
            connection.execute(
                "UPDATE learning_requests SET request_sha=? WHERE scope=? AND operation=? AND actor=? AND request_key=?",
                (
                    sha(request.model_dump(mode="json")),
                    records["task_id"],
                    "create",
                    ACTOR,
                    request.request_key,
                ),
            )


@pytest.mark.parametrize(
    "operation,key,target",
    [
        ("drop_table", "valid-request-001", "target"),
        ("create", "short", "target"),
        ("create", "x" * 101, "target"),
        ("create", "valid-request-001", "../private"),
        ("create", "valid-request-001", "x" * 121),
        ("create", "x' OR 1=1 --", "target"),
    ],
)
def test_lookup_identifiers_are_bounded_and_not_sql_fragments(
    operation_records, operation, key, target
):
    with pytest.raises(LearningError, match="LEARNING_OPERATION_INPUT_INVALID"):
        lookup(operation_records, operation, key, target)


def test_project_authorization_happens_before_learning_storage_is_read():
    class Store:
        def get_project(self, actor, project_id):
            raise NotFoundError("project not found")

        def _connection(self):
            raise AssertionError("learning lookup must follow project authorization")

    class Product:
        store = Store()

    with pytest.raises(NotFoundError):
        read_learning_operation(
            Product(),
            "outsider",
            "unknown-project",
            "create",
            "unknown-request-001",
            "target",
        )


def test_lookup_before_learning_tables_exist_remains_read_only_unknown(tmp_path):
    product = ProductService(tmp_path / "product", recover_interrupted=False)
    try:
        with TestClient(create_app(product)) as client:
            project = client.post(
                "/v1/projects",
                headers=HEADERS,
                json={
                    "workspace_id": WORKSPACE,
                    "name": "Lookup without learning initialization",
                    "source_kind": "local_authorized_directory",
                    "scenario_profile": "industrial",
                },
            ).json()
            result = read_learning_operation(
                product,
                ACTOR,
                project["project_id"],
                "create",
                "future-create-0001",
                "task-pending-freeze",
            )
            verify_receipt(result)
            assert result["execution_status"] == "UNKNOWN_NOT_PROOF_OF_NO_WRITE"
            assert not (product.product_root / "learning").exists()
            with product.store._connection() as connection:
                assert (
                    connection.execute(
                        "SELECT COUNT(*) FROM sqlite_master WHERE name IN ('learning_requests','learning_records')"
                    ).fetchone()[0]
                    == 0
                )
    finally:
        product.close(wait=True)
