from __future__ import annotations

import json

import numpy as np
import pytest
import rfc8785
from pydantic import ValidationError

from visiondata_gate import learning_evaluation as evaluation
from visiondata_gate.learning_engine import PixelSample
from visiondata_gate.learning_evaluation import EvaluationPolicy, evaluate_models


def model(red_weight: float = 0.0) -> dict:
    return {
        "schema_version": "visiondata-gate.pixel-logistic.v1",
        "feature_version": "rgb_xy_v1",
        "weights": [red_weight, 0.0, 0.0, 0.0, 0.0, -5.0 if red_weight else 0.0],
    }


def sample(
    sample_id: str = "sample-a",
    category: str = "part-a",
    split: str = "val",
    mask: np.ndarray | None = None,
) -> PixelSample:
    if mask is None:
        mask = np.array([[1, 1, 0, 0], [1, 1, 0, 0]], dtype=np.uint8)
    image = np.zeros((*mask.shape, 3), dtype=np.uint8)
    image[..., 0] = mask * 255
    return PixelSample(
        sample_id=sample_id,
        split=split,
        category=category,
        group_id="capture-" + sample_id,
        image=image,
        mask=mask,
    )


def patch_predictions(monkeypatch, candidate: np.ndarray, baseline: np.ndarray):
    def predict(current_model, image):
        return candidate.copy() if current_model["weights"][0] else baseline.copy()

    monkeypatch.setattr(evaluation, "predict", predict)


def test_real_predict_improvement_is_eligible_and_evidence_is_canonical_json():
    result = evaluate_models(model(10.0), model(), [sample()], EvaluationPolicy())
    metrics = result["aggregate"]["candidate"]
    assert result["schema_version"] == "visiondata-gate.learning-evaluation.v1"
    assert result["decision"] == "ELIGIBLE"
    assert result["blockers"] == []
    assert {key: metrics[key] for key in ("tp", "fp", "tn", "fn")} == {
        "tp": 4, "fp": 0, "tn": 4, "fn": 0,
    }
    assert metrics["dice"] == 1.0
    assert metrics["false_negative_rate"] == 0.0
    assert metrics["false_positive_rate"] == 0.0
    assert result["aggregate"]["baseline"]["false_positive_rate"] == 1.0
    assert result["latency"]["scope"] == "LOCAL_CPU_OBSERVATION_ONLY"
    assert result["latency"]["candidate"]["p95_ms"] >= 0
    assert result["observed_elapsed_seconds"] >= 0
    rfc8785.dumps(result)
    json.dumps(result, allow_nan=False)


def test_val_sample_results_bind_predictions_and_truth_without_label_blame():
    result = evaluate_models(model(), model(10), [sample()], EvaluationPolicy())
    item = result["sample_results"][0]
    assert item["sample_id"] == "sample-a"
    assert item["category"] == "part-a"
    assert item["group_id"] == "capture-sample-a"
    assert item["review_status"] == "PENDING_HUMAN_REVIEW"
    assert item["annotation_error_confirmed"] is False
    assert item["error_candidate"] is True
    assert len(item["truth_mask_sha256"]) == 64
    assert len(item["candidate"]["prediction_sha256"]) == 64
    assert len(item["baseline"]["prediction_sha256"]) == 64
    assert item["candidate"]["fp"] == 4
    assert item["candidate"]["fn"] == 0
    assert item["candidate"]["error_rate"] == 0.5
    assert not {"image", "mask", "path", "image_path", "mask_path"} & item.keys()
    assert result["decision"] == "HOLD"


@pytest.mark.parametrize("gain", [0.0, 0.001])
def test_zero_gain_is_hold_even_when_both_models_are_perfect(gain):
    result = evaluate_models(
        model(10), model(10), [sample()], EvaluationPolicy(min_dice_gain=gain)
    )
    assert result["aggregate"]["candidate"]["dice"] == 1.0
    assert result["decision"] == "HOLD"
    assert "INSUFFICIENT_DICE_GAIN" in result["blockers"]


def test_threshold_is_identical_for_candidate_and_baseline(monkeypatch):
    probabilities = np.array([[0.75, 0.75, 0.70, 0.70]] * 2)
    patch_predictions(monkeypatch, probabilities, probabilities)
    result = evaluate_models(
        model(10), model(), [sample()], EvaluationPolicy(threshold=0.75)
    )
    assert result["aggregate"]["candidate"] == result["aggregate"]["baseline"]
    assert result["aggregate"]["candidate"]["dice"] == 1.0


@pytest.mark.parametrize("fill,missing_metric", [(0, "false_negative_rate"), (1, "false_positive_rate")])
def test_missing_overall_positive_or_negative_denominator_is_none_and_hold(fill, missing_metric):
    item = sample(mask=np.full((2, 4), fill, dtype=np.uint8))
    result = evaluate_models(model(10), model(), [item], EvaluationPolicy())
    assert result["aggregate"]["candidate"][missing_metric] is None
    assert result["decision"] == "HOLD"
    assert any(code.startswith("AGGREGATE_METRIC_NOT_MEASURED") for code in result["blockers"])
    if fill == 0:
        assert result["aggregate"]["candidate"]["dice"] is None
    rfc8785.dumps(result)


def test_a_category_without_positives_holds_even_when_aggregate_is_measured():
    rows = [sample(), sample("sample-b", "background", mask=np.zeros((2, 4), dtype=np.uint8))]
    result = evaluate_models(model(10), model(), rows, EvaluationPolicy())
    assert result["aggregate"]["candidate"]["false_negative_rate"] == 0.0
    assert result["categories"]["background"]["candidate"]["false_negative_rate"] is None
    assert result["decision"] == "HOLD"
    assert any(code.startswith("CATEGORY_METRIC_NOT_MEASURED") for code in result["blockers"])


def test_category_regression_holds_despite_good_aggregate_gain(monkeypatch):
    rows = [sample("a", "part-a"), sample("b", "part-b")]
    rows[1].image[..., 1] = 255

    def predict(current_model, image):
        truth = (image[..., 0] > 0).astype(float)
        if image[0, 0, 1]:
            return truth if current_model["weights"][0] else 1.0 - truth
        if current_model["weights"][0]:
            truth[0, 0] = 0.0
        return truth

    monkeypatch.setattr(evaluation, "predict", predict)
    result = evaluate_models(model(10), model(), rows, EvaluationPolicy())
    assert result["aggregate"]["candidate"]["dice"] > result["aggregate"]["baseline"]["dice"]
    assert result["aggregate"]["candidate"]["false_negative_rate"] < 0.2
    assert "CATEGORY_DICE_REGRESSION:part-a" in result["blockers"]
    assert result["decision"] == "HOLD"


def test_false_negative_and_false_positive_limits_are_independent(monkeypatch):
    truth = sample().mask.astype(float)
    bad = truth.copy()
    bad[0, 0] = 0
    bad[0, 2] = 1
    patch_predictions(monkeypatch, bad, 1.0 - truth)
    result = evaluate_models(model(10), model(), [sample()], EvaluationPolicy(min_dice=0.5))
    assert "FALSE_NEGATIVE_RATE_EXCEEDED" in result["blockers"]
    assert "FALSE_POSITIVE_RATE_EXCEEDED" in result["blockers"]
    assert result["decision"] == "HOLD"


def test_minimum_dice_and_required_gain_are_enforced(monkeypatch):
    truth = sample().mask.astype(float)
    candidate = truth.copy()
    candidate[0, 0] = 0
    patch_predictions(monkeypatch, candidate, 1.0 - truth)
    result = evaluate_models(model(10), model(), [sample()], EvaluationPolicy(min_dice=0.95, min_dice_gain=0.99))
    assert "MIN_DICE_NOT_MET" in result["blockers"]
    assert "INSUFFICIENT_DICE_GAIN" in result["blockers"]


def test_cpu_latency_over_budget_holds_without_benchmark_claim(monkeypatch):
    ticks = iter([0.0, 1.0, 1.1, 2.0, 2.001, 3.0])
    monkeypatch.setattr(evaluation.time, "perf_counter", lambda: next(ticks))
    result = evaluate_models(
        model(10), model(), [sample()], EvaluationPolicy(max_p95_latency_ms=50)
    )
    assert result["latency"]["candidate"]["p95_ms"] == pytest.approx(100)
    assert result["latency"]["baseline"]["p95_ms"] == pytest.approx(1)
    assert "CANDIDATE_LATENCY_BUDGET_EXCEEDED" in result["blockers"]
    assert result["latency"]["benchmark_claim"] is False
    assert result["decision"] == "HOLD"


def test_test_split_never_returns_sample_feedback_or_mining_tasks():
    result = evaluate_models(model(), model(10), [sample(split="test")], EvaluationPolicy(), split="test")
    assert result["sample_results"] == []
    assert result["decision"] == "HOLD"
    assert "hard_mining_tasks" not in result
    assert "sample-a" not in json.dumps(result)


@pytest.mark.parametrize("split", ["train", "validation", "", "VAL"])
def test_only_val_and_test_are_accepted(split):
    with pytest.raises(ValueError, match="EVALUATION_SPLIT_INVALID"):
        evaluate_models(model(10), model(), [sample()], EvaluationPolicy(), split=split)


def test_all_sample_splits_are_checked_before_any_prediction(monkeypatch):
    def forbidden(*_args):
        raise AssertionError("predict must not run before split validation")

    monkeypatch.setattr(evaluation, "predict", forbidden)
    with pytest.raises(ValueError, match="SAMPLE_SPLIT_MISMATCH"):
        evaluate_models(model(10), model(), [sample(), sample("train-row", split="train")], EvaluationPolicy())


@pytest.mark.parametrize("rows", [[], [sample(" ")], [sample(), sample()]])
def test_empty_or_duplicate_sample_identity_is_rejected(rows):
    with pytest.raises(ValueError, match="EVALUATION_SAMPLES_EMPTY|SAMPLE_ID_INVALID|SAMPLE_ID_DUPLICATE"):
        evaluate_models(model(10), model(), rows, EvaluationPolicy())


@pytest.mark.parametrize("field,value", [
    ("threshold", 0), ("threshold", 1), ("threshold", float("nan")),
    ("max_false_negative_rate", -0.1), ("max_false_positive_rate", 1.1),
    ("min_dice", 1.1), ("min_dice_gain", -0.1),
    ("max_category_dice_regression", -0.1),
    ("max_p95_latency_ms", 0), ("max_p95_latency_ms", 60001),
    ("max_p95_latency_ms", float("inf")),
])
def test_policy_bounds_and_finiteness(field, value):
    with pytest.raises(ValidationError):
        EvaluationPolicy(**{field: value})


def test_policy_forbids_extra_fields():
    with pytest.raises(ValidationError, match="extra_forbidden"):
        EvaluationPolicy(untracked_override=True)


@pytest.mark.parametrize("bad", [np.full((2, 4), np.nan), np.full((2, 4), np.inf), np.full((2, 4), 1.1), np.zeros((1, 2))])
def test_invalid_prediction_cannot_become_json_evidence(monkeypatch, bad):
    monkeypatch.setattr(evaluation, "predict", lambda *_: bad)
    with pytest.raises(ValueError, match="PREDICTION_INVALID"):
        evaluate_models(model(10), model(), [sample()], EvaluationPolicy())


def test_prediction_digest_changes_when_probabilities_change_without_mask_change(monkeypatch):
    truth = sample().mask.astype(float)
    patch_predictions(monkeypatch, truth * 0.8 + 0.1, 1.0 - truth)
    first = evaluate_models(model(10), model(), [sample()], EvaluationPolicy())
    patch_predictions(monkeypatch, truth * 0.6 + 0.2, 1.0 - truth)
    second = evaluate_models(model(10), model(), [sample()], EvaluationPolicy())
    left, right = first["sample_results"][0], second["sample_results"][0]
    assert left["truth_mask_sha256"] == right["truth_mask_sha256"]
    assert left["candidate"]["prediction_mask_sha256"] == right["candidate"]["prediction_mask_sha256"]
    assert left["candidate"]["prediction_sha256"] != right["candidate"]["prediction_sha256"]
