"""Lifecycle regressions use only temporary products and synthetic Gate inputs."""

from datetime import UTC, datetime, timedelta
import json
import os
from pathlib import Path
import subprocess
import sys

import pytest
from pydantic import ValidationError

from tests.test_learning_lifecycle import (
    ACTOR,
    HEADERS,
    learning_input as learning_input,
)
from tests.test_learning_service_safety import _create_cycle, _train_and_approve
from visiondata_gate.learning_contracts import CreateLearningCycle, CycleAction
from visiondata_gate.learning_service import LearningError, LearningService
import visiondata_gate.learning_service as learning_module


def _action(cycle, key):
    return CycleAction(
        request_key=key,
        expected_cycle_sha256=cycle["receipt_sha256"],
        review_note="Explicit review of this synthetic recovery regression",
        operator_attests_reviewed=True,
    )


def _creation_payload(**overrides):
    return {
        "request_key": "audit-cycle-budget-001",
        "expected_preflight_sha256": "a" * 64,
        "groups": {"sample": "group"},
        "review_note": "Authorize only the bounded synthetic CPU protocol",
        "operator_attests_training_authorized": True,
        **overrides,
    }


@pytest.mark.parametrize(
    "overrides",
    [{"max_total_epochs": 1}, {"max_total_wall_seconds": 1.0}],
)
def test_cycle_budget_must_admit_the_first_round(overrides):
    with pytest.raises(ValidationError, match="first round"):
        CreateLearningCycle.model_validate(_creation_payload(**overrides))


def test_cycle_budget_may_equal_exactly_one_round():
    request = CreateLearningCycle.model_validate(
        _creation_payload(max_total_epochs=80, max_total_wall_seconds=20.0)
    )
    assert request.training.epochs == request.max_total_epochs
    assert request.training.max_wall_seconds == request.max_total_wall_seconds


def test_impossible_cycle_budget_is_rejected_before_learning_storage(learning_input):
    client, product, (task_id, preflight, groups) = learning_input
    assert not (product.product_root / "learning").exists()
    response = client.post(
        f"/v1/tasks/{task_id}/learning-cycles",
        headers=HEADERS,
        json=_creation_payload(
            expected_preflight_sha256=preflight["receipt_sha256"],
            groups=groups,
            max_total_epochs=1,
        ),
    )
    assert response.status_code == 422
    assert not (product.product_root / "learning").exists()


@pytest.mark.parametrize("status", ["RUNNING", "FAILED", "CANCELLED", "INTERRUPTED"])
def test_selection_without_a_completed_candidate_returns_controlled_409(
    learning_input, monkeypatch, status
):
    client, _product, _input = learning_input
    service, cycle, request = _create_cycle(learning_input)

    def fail_training(*_args, **_kwargs):
        raise ValueError("Synthetic execution failed before model creation")

    monkeypatch.setattr(learning_module, "train_model", fail_training)
    run = service.run_round(ACTOR, cycle["cycle_id"], request)
    assert run["status"] == "FAILED" and "model_id" not in run
    with service.product.store._connection(immediate=True) as connection:
        run["status"] = status
        run = service._put(connection, "run", run, replace=True)
        current = service._read(connection, cycle["cycle_id"], "cycle")
        current["status"] = "RUNNING" if status == "RUNNING" else "AWAITING_DATA"
        cycle = service._put(connection, "cycle", current, replace=True)
    response = client.post(
        f"/v1/learning-cycles/{cycle['cycle_id']}/runs/{run['run_id']}/selection",
        headers=HEADERS,
        json={
            **_action(cycle, "audit-invalid-select-001").model_dump(mode="json"),
            "expected_run_sha256": run["receipt_sha256"],
            "action": "APPROVE_SANDBOX",
        },
    )
    assert response.status_code == 409
    assert response.json()["error"]["code"] == "learning_hold"
    assert response.headers["cache-control"] == "private, no-store"


def _external_lock_is_available(product_root, cycle_id):
    """A separate interpreter probes the actual named OS lock, not a mock."""
    source = (
        "from pathlib import Path\n"
        "import sys\n"
        "from visiondata_gate.execution_recovery import task_execution_lock\n"
        "with task_execution_lock(Path(sys.argv[1]), 'learning:' + sys.argv[2]) as acquired:\n"
        "    print('AVAILABLE' if acquired else 'HELD')\n"
    )
    environment = os.environ.copy()
    environment["PYTHONPATH"] = str(Path(__file__).resolve().parents[1] / "src")
    environment["VISIONDATA_PRODUCT_ROOT"] = str(product_root / "probe-isolated")
    result = subprocess.run(
        [sys.executable, "-c", source, str(product_root), cycle_id],
        env=environment,
        capture_output=True,
        text=True,
        encoding="utf-8",
        timeout=20,
        check=True,
    )
    return result.stdout.strip() == "AVAILABLE"


def _recovery_result(service, cycle):
    try:
        service.recover(ACTOR, cycle["cycle_id"], _action(cycle, "audit-recover-0001"))
    except LearningError as error:
        return str(error)
    return "RECOVER_ACCEPTED"


def _consume_count(service):
    with service.product.store._connection() as connection:
        return connection.execute(
            "SELECT COUNT(*) FROM learning_consumed_tests"
        ).fetchone()[0]


def test_active_training_owns_cross_process_lock_even_after_lease_expiry(
    learning_input, monkeypatch
):
    service, cycle, request = _create_cycle(learning_input)
    other = LearningService(service.product)
    original_train = learning_module.train_model
    observed = {}

    def inspect_active_training(*args, **kwargs):
        current = other.get_cycle(ACTOR, cycle["cycle_id"])
        with service.product.store._connection(immediate=True) as connection:
            run = service._read(connection, current["round_ids"][-1], "run")
            run["started_at"] = (datetime.now(UTC) - timedelta(hours=1)).isoformat()
            service._put(connection, "run", run, replace=True)
        observed["external_lock_available"] = _external_lock_is_available(
            service.product.product_root, cycle["cycle_id"]
        )
        observed["recovery"] = _recovery_result(other, current)
        return original_train(*args, **kwargs)

    monkeypatch.setattr(learning_module, "train_model", inspect_active_training)
    result = service.run_round(ACTOR, cycle["cycle_id"], request)
    assert observed == {
        "external_lock_available": False,
        "recovery": "EXECUTION_OWNER_ACTIVE",
    }
    assert result["status"] == "COMPLETED"
    assert _external_lock_is_available(service.product.product_root, cycle["cycle_id"])


def test_active_final_test_cannot_be_recovered_or_lose_consumed_evidence(
    learning_input, monkeypatch
):
    service, cycle, request = _create_cycle(learning_input)
    cycle, _run = _train_and_approve(service, cycle, request)
    other = LearningService(service.product)
    original_evaluate = learning_module.evaluate_models
    observed = {}

    def inspect_final_test(*args, **kwargs):
        current = other.get_cycle(ACTOR, cycle["cycle_id"])
        assert current["status"] == "FINALIZING"
        observed["consumed_before"] = _consume_count(service)
        observed["external_lock_available"] = _external_lock_is_available(
            service.product.product_root, cycle["cycle_id"]
        )
        observed["recovery"] = _recovery_result(other, current)
        observed["consumed_after"] = _consume_count(service)
        return original_evaluate(*args, **kwargs)

    monkeypatch.setattr(learning_module, "evaluate_models", inspect_final_test)
    result = service.finalize(
        ACTOR, cycle["cycle_id"], _action(cycle, "audit-finalize-active-001")
    )
    assert observed["recovery"] == "EXECUTION_OWNER_ACTIVE"
    assert observed["external_lock_available"] is False
    assert observed["consumed_before"] == observed["consumed_after"] > 0
    assert result["status"] == "FINALIZED"
    assert _external_lock_is_available(service.product.product_root, cycle["cycle_id"])


@pytest.mark.parametrize("status", ["RUNNING", "FINALIZING"])
def test_legacy_learning_without_execution_owner_is_not_assumed_interrupted(
    learning_input, status
):
    service, cycle, _request = _create_cycle(learning_input)
    with service.product.store._connection(immediate=True) as connection:
        cycle["status"] = status
        if status == "RUNNING":
            cycle["round_ids"] = ["run_legacy_owned_fixture"]
            service._put(
                connection,
                "run",
                {
                    "run_id": cycle["round_ids"][0],
                    "cycle_id": cycle["cycle_id"],
                    "project_id": cycle["project_id"],
                    "configuration": cycle["request"]["training"],
                    "started_at": (datetime.now(UTC) - timedelta(hours=1)).isoformat(),
                    "status": "RUNNING",
                },
            )
        cycle = service._put(connection, "cycle", cycle, replace=True)
    with pytest.raises(LearningError, match="EXECUTION_OWNERSHIP_UNKNOWN"):
        service.recover(
            ACTOR, cycle["cycle_id"], _action(cycle, "audit-legacy-recover-001")
        )
    assert service.get_cycle(ACTOR, cycle["cycle_id"])["status"] == status


def test_interrupted_managed_final_test_stops_without_releasing_test_holdout(
    learning_input, monkeypatch
):
    service, cycle, request = _create_cycle(learning_input)
    cycle, _run = _train_and_approve(service, cycle, request)

    def interrupt_evaluation(*_args, **_kwargs):
        raise KeyboardInterrupt("Synthetic interrupted owner")

    monkeypatch.setattr(learning_module, "evaluate_models", interrupt_evaluation)
    with pytest.raises(KeyboardInterrupt, match="Synthetic interrupted owner"):
        service.finalize(
            ACTOR, cycle["cycle_id"], _action(cycle, "audit-finalize-interrupt-001")
        )
    current = service.get_cycle(ACTOR, cycle["cycle_id"])
    assert current["status"] == "FINALIZING"
    assert _external_lock_is_available(service.product.product_root, cycle["cycle_id"])
    before = _consume_count(service)
    result = service.recover(
        ACTOR, cycle["cycle_id"], _action(current, "audit-interrupted-recover-001")
    )
    assert result["status"] == "STOPPED"
    assert "final_evaluation" not in result
    assert _consume_count(service) == before > 0


def test_interrupted_training_preserves_lease_owner_binding_budget_and_replay(
    learning_input, monkeypatch
):
    service, cycle, request = _create_cycle(learning_input)

    def interrupt_training(*_args, **_kwargs):
        raise KeyboardInterrupt("Synthetic interrupted trainer")

    monkeypatch.setattr(learning_module, "train_model", interrupt_training)
    with pytest.raises(KeyboardInterrupt, match="Synthetic interrupted trainer"):
        service.run_round(ACTOR, cycle["cycle_id"], request)
    current = service.get_cycle(ACTOR, cycle["cycle_id"])
    assert current["status"] == "RUNNING"
    assert "execution_owner" not in current
    recovery = _action(current, "audit-managed-training-recover-001")
    with pytest.raises(LearningError, match="EXECUTION_LEASE_NOT_EXPIRED"):
        service.recover(ACTOR, cycle["cycle_id"], recovery)

    with service.product.store._connection(immediate=True) as connection:
        row = connection.execute(
            "SELECT owner_json FROM learning_execution_owners WHERE cycle_id=?",
            (cycle["cycle_id"],),
        ).fetchone()
        owner = json.loads(row["owner_json"])
        assert owner["operation"] == "train"
        assert owner["run_id"] == current["round_ids"][-1]
        changed = learning_module._seal({**owner, "operation": "finalize"})
        connection.execute(
            "UPDATE learning_execution_owners SET owner_json=? WHERE cycle_id=?",
            (json.dumps(changed), cycle["cycle_id"]),
        )
    with pytest.raises(LearningError, match="EXECUTION_OWNERSHIP_INVALID"):
        service.recover(ACTOR, cycle["cycle_id"], recovery)

    with service.product.store._connection(immediate=True) as connection:
        connection.execute(
            "UPDATE learning_execution_owners SET owner_json=? WHERE cycle_id=?",
            (json.dumps(owner), cycle["cycle_id"]),
        )
        run = service._read(connection, current["round_ids"][-1], "run")
        run["started_at"] = (datetime.now(UTC) - timedelta(hours=1)).isoformat()
        service._put(connection, "run", run, replace=True)
    recovered = service.recover(ACTOR, cycle["cycle_id"], recovery)
    assert recovered["status"] == "AWAITING_DATA"
    assert recovered["epochs_reserved"] == current["epochs_reserved"]
    assert recovered["wall_seconds_reserved"] == current["wall_seconds_reserved"]
    run = service.get_run(ACTOR, current["round_ids"][-1])
    assert run["status"] == "INTERRUPTED" and run["cancel_requested"] is True
    assert "execution_owner" not in run
    assert service.recover(ACTOR, cycle["cycle_id"], recovery) == recovered
