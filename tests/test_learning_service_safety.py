"""Focused negative cases using only fixture-owned synthetic data and records."""

from pathlib import Path

import pytest

from tests.test_learning_lifecycle import ACTOR, learning_input as learning_input
from visiondata_gate.learning_contracts import (
    CreateLearningCycle,
    CycleAction,
    FeedbackReview,
    ModelSelection,
    RunLearningRound,
)
from visiondata_gate.learning_dataset import freeze_dataset, load_dataset
from visiondata_gate.learning_service import LearningError, LearningService
import visiondata_gate.learning_service as learning_service_module
from visiondata_gate.product_models import RevokeLocalSourceAuthorizationRequest


def _create_cycle(learning_input):
    _client, product, (task_id, preflight, groups) = learning_input
    service = LearningService(product)
    request = CreateLearningCycle(
        request_key="safety-create-cycle-01",
        expected_preflight_sha256=preflight["receipt_sha256"],
        groups=groups,
        review_note="Authorize synthetic CPU safety regression only",
        operator_attests_training_authorized=True,
        training={"epochs": 250, "learning_rate": 1.5},
        max_total_epochs=800,
    )
    cycle = service.create_cycle(ACTOR, task_id, request)
    round_request = RunLearningRound(
        request_key="safety-train-round-01",
        task_id=task_id,
        expected_preflight_sha256=preflight["receipt_sha256"],
        expected_cycle_sha256=cycle["receipt_sha256"],
        groups=groups,
        review_note="Approve one bounded synthetic training run",
        operator_attests_training_authorized=True,
    )
    return service, cycle, round_request


def _replace_self_consistent_receipt(learning_input, service, cycle, tmp_path: Path):
    _client, product, (task_id, preflight, groups) = learning_input
    _task, source_root, manifest, _contract, _gate = product._annotation_context(
        ACTOR, task_id
    )
    replacement_root = tmp_path / "synthetic-replacement-only"
    replacement = freeze_dataset(
        source_root,
        manifest,
        preflight["binding"],
        {sample_id: "changed-" + group for sample_id, group in groups.items()},
        replacement_root,
    )
    copied_root = service._path(cycle["cycle_id"], cycle["dataset_storage_key"])
    # Images/masks are identical, so this changes only the self-sealed group contract.
    (copied_root / "dataset.json").write_bytes(
        (replacement_root / "dataset.json").read_bytes()
    )
    loaded, _samples = load_dataset(copied_root)
    assert loaded == replacement
    assert loaded["receipt_sha256"] != cycle["dataset"]["receipt_sha256"]


def _train_and_approve(service, cycle, request):
    run = service.run_round(ACTOR, cycle["cycle_id"], request)
    assert run["status"] == "COMPLETED", run
    assert run["evaluation"]["decision"] == "ELIGIBLE", run["evaluation"]
    for feedback in run["feedback"]:
        cycle = service.get_cycle(ACTOR, cycle["cycle_id"])
        service.review_feedback(
            ACTOR,
            cycle["cycle_id"],
            run["run_id"],
            feedback["feedback_id"],
            FeedbackReview(
                request_key="review-" + feedback["feedback_id"],
                expected_cycle_sha256=cycle["receipt_sha256"],
                review_note="Human triages synthetic hard sample; no automatic ingestion",
                classification="HARD_SAMPLE",
                operator_attests_reviewed=True,
            ),
        )
    cycle = service.get_cycle(ACTOR, cycle["cycle_id"])
    run = service.get_run(ACTOR, run["run_id"])
    selected = service.select_model(
        ACTOR,
        cycle["cycle_id"],
        run["run_id"],
        ModelSelection(
            request_key="safety-approve-model-01",
            expected_cycle_sha256=cycle["receipt_sha256"],
            expected_run_sha256=run["receipt_sha256"],
            action="APPROVE_SANDBOX",
            review_note="Approve only the evaluated synthetic sandbox model",
            operator_attests_reviewed=True,
        ),
    )
    return selected, run


def test_initial_round_rejects_valid_but_unanchored_dataset_receipt(
    learning_input, tmp_path
):
    service, cycle, request = _create_cycle(learning_input)
    _replace_self_consistent_receipt(learning_input, service, cycle, tmp_path)
    with pytest.raises(LearningError, match="DATASET"):
        service.run_round(ACTOR, cycle["cycle_id"], request)


def test_final_test_rejects_valid_but_unanchored_dataset_receipt(
    learning_input, tmp_path
):
    service, cycle, request = _create_cycle(learning_input)
    cycle, _run = _train_and_approve(service, cycle, request)
    _replace_self_consistent_receipt(learning_input, service, cycle, tmp_path)
    with pytest.raises(LearningError, match="DATASET"):
        service.finalize(
            ACTOR,
            cycle["cycle_id"],
            CycleAction(
                request_key="safety-final-test-01",
                expected_cycle_sha256=cycle["receipt_sha256"],
                review_note="Consume only the originally bound final test protocol",
                operator_attests_reviewed=True,
            ),
        )


def test_model_bytes_tamper_is_rejected(learning_input):
    service, cycle, _request = _create_cycle(learning_input)
    model_id = cycle["initial_model_id"]
    path = service._path(cycle["cycle_id"], model_id + ".json")
    path.write_bytes(path.read_bytes() + b" ")
    with pytest.raises(LearningError, match="MODEL_ARTIFACT_INTEGRITY_HOLD"):
        service.get_model(ACTOR, model_id)


def test_revoked_source_cannot_start_training(learning_input):
    service, cycle, request = _create_cycle(learning_input)
    _client, product, (_task, preflight, _groups) = learning_input
    source_id = preflight["binding"]["source_id"]
    source = product.get_local_source_authorization(ACTOR, source_id)
    product.revoke_local_source_authorization(
        ACTOR,
        source_id,
        RevokeLocalSourceAuthorizationRequest(
            reason="Revoke synthetic data before any parameter update",
            expected_latest_event_sha256=source.latest_authorization_event_sha256,
        ),
    )
    with pytest.raises(LearningError, match="INPUT_GATE_HOLD"):
        service.run_round(ACTOR, cycle["cycle_id"], request)


def test_baseline_artifact_changed_during_real_training_cannot_publish(
    learning_input, monkeypatch
):
    service, cycle, request = _create_cycle(learning_input)
    path = service._path(cycle["cycle_id"], cycle["champion_model_id"] + ".json")
    original_train = learning_service_module.train_model

    def train_then_change_checkpoint(*args, **kwargs):
        result = original_train(*args, **kwargs)
        path.write_bytes(path.read_bytes() + b" ")
        return result

    monkeypatch.setattr(
        learning_service_module, "train_model", train_then_change_checkpoint
    )
    run = service.run_round(ACTOR, cycle["cycle_id"], request)
    assert run["status"] == "FAILED", run["status"]
    assert "model_id" not in run


def test_candidate_artifact_changed_during_final_test_cannot_finalize(
    learning_input, monkeypatch
):
    service, cycle, request = _create_cycle(learning_input)
    cycle, _run = _train_and_approve(service, cycle, request)
    path = service._path(cycle["cycle_id"], cycle["champion_model_id"] + ".json")
    original_evaluate = learning_service_module.evaluate_models

    def evaluate_then_change_checkpoint(*args, **kwargs):
        result = original_evaluate(*args, **kwargs)
        path.write_bytes(path.read_bytes() + b" ")
        return result

    monkeypatch.setattr(
        learning_service_module, "evaluate_models", evaluate_then_change_checkpoint
    )
    result = service.finalize(
        ACTOR,
        cycle["cycle_id"],
        CycleAction(
            request_key="safety-final-model-01",
            expected_cycle_sha256=cycle["receipt_sha256"],
            review_note="Final test must remain bound to the actual candidate artifact",
            operator_attests_reviewed=True,
        ),
    )
    assert result["status"] == "STOPPED", result["status"]
    assert "final_evaluation" not in result


def test_cancel_before_model_publication_never_selects_candidate(
    learning_input, monkeypatch
):
    service, cycle, request = _create_cycle(learning_input)
    original_write = service._write_model

    def cancel_before_write(*args, **kwargs):
        current = service.get_cycle(ACTOR, cycle["cycle_id"])
        service.cancel(
            ACTOR,
            cycle["cycle_id"],
            CycleAction(
                request_key="safety-cancel-race-01",
                expected_cycle_sha256=current["receipt_sha256"],
                review_note="Cancel this synthetic run just before candidate publication",
                operator_attests_reviewed=True,
            ),
        )
        return original_write(*args, **kwargs)

    monkeypatch.setattr(service, "_write_model", cancel_before_write)
    run = service.run_round(ACTOR, cycle["cycle_id"], request)
    assert run["status"] == "CANCELLED", run["status"]
    current = service.get_cycle(ACTOR, cycle["cycle_id"])
    assert current["champion_model_id"] == cycle["initial_model_id"]
    assert "model_id" not in run
