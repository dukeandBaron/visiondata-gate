import pytest
from pydantic import ValidationError


def test_learning_authorization_and_budgets_are_explicit():
    from visiondata_gate.learning_contracts import CreateLearningCycle

    payload = dict(
        request_key="learning-create-0001",
        expected_preflight_sha256="a" * 64,
        groups={"sample-a": "part-a"},
        review_note="Approved local CPU sandbox",
        operator_attests_training_authorized=True,
    )
    request = CreateLearningCycle.model_validate(payload)
    assert request.max_rounds == 3
    for changes in (
        {"operator_attests_training_authorized": False},
        {"max_rounds": 1000},
        {"command": "run-anything"},
        {"max_total_epochs": 0},
    ):
        with pytest.raises(ValidationError):
            CreateLearningCycle.model_validate(payload | changes)


def test_round_feedback_association_is_explicit_not_all_previous_errors():
    from visiondata_gate.learning_contracts import RunLearningRound
    payload={"request_key":"explicit-feedback-001","expected_preflight_sha256":"a"*64,
        "groups":{"sample":"group"},"review_note":"New data does not implicitly resolve every previous error",
        "operator_attests_training_authorized":True,"task_id":"task","expected_cycle_sha256":"b"*64}
    assert RunLearningRound.model_validate(payload).responds_to_feedback_ids == []


def test_selection_cannot_claim_production_or_skip_review():
    from visiondata_gate.learning_contracts import ModelSelection

    payload = dict(
        request_key="learning-select-0001",
        expected_cycle_sha256="a" * 64,
        expected_run_sha256="b" * 64,
        action="APPROVE_SANDBOX",
        review_note="Independent result reviewed",
        operator_attests_reviewed=True,
    )
    assert ModelSelection.model_validate(payload).action == "APPROVE_SANDBOX"
    for changes in (
        {"action": "APPROVE_PRODUCTION"},
        {"operator_attests_reviewed": False},
    ):
        with pytest.raises(ValidationError):
            ModelSelection.model_validate(payload | changes)


def test_empty_annotation_is_not_implicitly_a_normal_training_mask():
    from visiondata_gate.learning_contracts import NormalMaskAttestation
    payload={"reviewer_name":"Named synthetic reviewer","review_note":"Explicitly reviewed no foreground in this synthetic image",
             "expected_asset_sha256":"a"*64,"expected_annotation_revision":0,
             "expected_annotation_sha256":"b"*64,"operator_attests_no_foreground":True}
    assert NormalMaskAttestation.model_validate(payload).operator_attests_no_foreground is True
    for changes in ({"operator_attests_no_foreground":False},{"reviewer_name":""},{"expected_annotation_sha256":"stale"}):
        with pytest.raises(ValidationError):
            NormalMaskAttestation.model_validate(payload|changes)
