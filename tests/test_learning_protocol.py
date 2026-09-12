"""Protocol-level guards: test consumption, model HOLD, and feedback authority."""
# Ruff cannot see pytest's fixture injection when a fixture is imported.
# ruff: noqa: F401, F811

import pytest

from tests.test_learning_lifecycle import (
    ACTOR,
    create_and_run,
    learning_input,
    review_and_select,
)
from visiondata_gate.learning_contracts import (
    CreateLearningCycle,
    CycleAction,
    FeedbackReview,
)
from visiondata_gate.learning_service import LearningError, LearningService


def test_consumed_final_test_cannot_be_reused_by_creating_another_cycle(learning_input):
    _, product, (task_id, preflight, groups) = learning_input
    service = LearningService(product)
    cycle, run = create_and_run(service, task_id, preflight, groups)
    cycle = review_and_select(service, cycle["cycle_id"], run)
    final = service.finalize(
        ACTOR,
        cycle["cycle_id"],
        CycleAction(
            request_key="final-test-consume-001",
            expected_cycle_sha256=cycle["receipt_sha256"],
            review_note="Final holdout is consumed once for this protocol",
            operator_attests_reviewed=True,
        ),
    )
    assert final["status"] == "FINALIZED"
    with pytest.raises(LearningError, match="FINAL_TEST_ALREADY_CONSUMED"):
        service.create_cycle(
            ACTOR,
            task_id,
            CreateLearningCycle(
                request_key="new-cycle-same-test-002",
                expected_preflight_sha256=preflight["receipt_sha256"],
                groups=groups,
                review_note="Cannot bypass test closure by creating another cycle",
                operator_attests_training_authorized=True,
            ),
        )


def test_undertrained_model_stays_hold_and_old_model_is_retained(learning_input):
    _, product, (task_id, preflight, groups) = learning_input
    service = LearningService(product)
    cycle, run = create_and_run(service, task_id, preflight, groups, epochs=1)
    assert run["status"] == "COMPLETED"
    assert run["evaluation"]["decision"] == "HOLD"
    assert (
        service.get_cycle(ACTOR, cycle["cycle_id"])["champion_model_id"]
        == cycle["initial_model_id"]
    )
    selected = review_and_select(service, cycle["cycle_id"], run)
    assert selected["champion_model_id"] == cycle["initial_model_id"]


def test_confirmed_validation_label_problem_stops_protocol_not_silent_relabel(
    learning_input,
):
    _, product, (task_id, preflight, groups) = learning_input
    service = LearningService(product)
    cycle, run = create_and_run(service, task_id, preflight, groups, epochs=1)
    item = run["feedback"][0]
    current = service.get_cycle(ACTOR, cycle["cycle_id"])
    reviewed = service.review_feedback(
        ACTOR,
        cycle["cycle_id"],
        run["run_id"],
        item["feedback_id"],
        FeedbackReview(
            request_key="label-error-review-001",
            expected_cycle_sha256=current["receipt_sha256"],
            review_note="Protocol negative test: adjudicated validation label is unreliable",
            operator_attests_reviewed=True,
            classification="LABEL_ERROR",
        ),
    )
    assert (
        reviewed["feedback"][0]["next_action"] == "RELABEL_AND_NEW_EVALUATION_PROTOCOL"
    )
    assert reviewed["feedback"][0]["training_ingestion_allowed"] is False
    assert (
        service.get_cycle(ACTOR, cycle["cycle_id"])["status"]
        == "HOLD_REQUIRES_NEW_PROTOCOL"
    )


def test_failed_run_can_retry_same_approved_input_with_new_authorization(
    learning_input, monkeypatch
):
    import visiondata_gate.learning_service as module
    from visiondata_gate.learning_contracts import RunLearningRound

    _, product, (task_id, preflight, groups) = learning_input
    service = LearningService(product)
    actual = module.train_model

    def unavailable(*args, **kwargs):
        raise RuntimeError("SIMULATED_LOCAL_EXECUTOR_FAILURE")

    monkeypatch.setattr(module, "train_model", unavailable)
    cycle, failed = create_and_run(service, task_id, preflight, groups)
    assert failed["status"] == "FAILED"
    assert (
        service.get_cycle(ACTOR, cycle["cycle_id"])["champion_model_id"]
        == cycle["initial_model_id"]
    )
    monkeypatch.setattr(module, "train_model", actual)
    current = service.get_cycle(ACTOR, cycle["cycle_id"])
    retried = service.run_round(
        ACTOR,
        cycle["cycle_id"],
        RunLearningRound(
            request_key="explicit-retry-after-failure",
            task_id=task_id,
            groups=groups,
            expected_cycle_sha256=current["receipt_sha256"],
            expected_preflight_sha256=preflight["receipt_sha256"],
            review_note="Authorize a fresh attempt after inspecting executor failure",
            operator_attests_training_authorized=True,
        ),
    )
    assert retried["status"] == "COMPLETED", retried
    assert retried["retry_of_run_id"] == failed["run_id"]
    assert service.get_run(ACTOR, failed["run_id"])["status"] == "FAILED"
