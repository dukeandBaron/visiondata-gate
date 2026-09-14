"""Actual CPU learning, input boundaries, and interrupted-run failure checks."""

from __future__ import annotations

from dataclasses import FrozenInstanceError, replace
import hashlib
import importlib
import importlib.util
import json

import numpy as np
import pytest
from pydantic import ValidationError

from visiondata_gate.audit_envelope import canonical_jcs_bytes


def _engine():
    name = "visiondata_gate.learning_engine"
    assert importlib.util.find_spec(name) is not None, (
        "Real NumPy training engine missing"
    )
    return importlib.import_module(name)


def _sample(engine, *, sample_id="train-1", split="train", size=16):
    mask = np.indices((size, size)).sum(axis=0) % 2 == 0
    image = np.zeros((size, size, 3), dtype=np.uint8)
    image[..., 0] = mask.astype(np.uint8) * 255
    image[..., 1] = (~mask).astype(np.uint8) * 255
    image[..., 2] = 64
    return engine.PixelSample(sample_id, split, "synthetic", sample_id, image, mask)


def test_real_training_changes_weights_and_reduces_loss():
    engine = _engine()
    sample = _sample(engine)
    initial = engine.initial_model()
    original_image, original_mask = sample.image.copy(), sample.mask.copy()
    result = engine.train_model([sample], engine.TrainingConfig())
    report = result["training"]
    assert result["model"]["weights"] != initial["weights"]
    assert report["loss_before"] == pytest.approx(np.log(2))
    assert report["loss_after"] < report["loss_before"] * 0.3
    assert report["epochs_completed"] == 80
    assert report["training_sample_ids"] == [sample.sample_id]
    assert report["training_pixel_count"] == 256
    assert report["optimizer"] == "full_batch_gradient_descent"
    assert report["device"] == "CPU"
    assert 0 <= report["elapsed_seconds"] <= 20
    assert (
        report["initial_model_sha256"]
        == hashlib.sha256(canonical_jcs_bytes(initial)).hexdigest()
    )
    probabilities = engine.predict(result["model"], sample.image)
    assert probabilities.shape == sample.mask.shape
    assert np.array_equal(probabilities >= 0.5, sample.mask)
    assert np.array_equal(sample.image, original_image)
    assert np.array_equal(sample.mask, original_mask)
    json.dumps(result, allow_nan=False)


def test_initial_model_is_independent_and_pixel_sample_is_frozen():
    engine = _engine()
    model = engine.initial_model()
    assert model == {
        "schema_version": "visiondata-gate.pixel-logistic.v1",
        "feature_version": "rgb_xy_v1",
        "weights": [0.0] * 6,
    }
    model["weights"][0] = 2.0
    assert engine.initial_model()["weights"] == [0.0] * 6
    sample = _sample(engine)
    with pytest.raises(FrozenInstanceError):
        sample.split = "test"
    assert np.all(engine.predict(engine.initial_model(), sample.image) == 0.5)


def test_one_epoch_matches_analytic_full_batch_gradient():
    engine = _engine()
    image = np.array([[[0, 0, 0], [255, 0, 0]]], dtype=np.uint8)
    sample = engine.PixelSample(
        "one", "train", "synthetic", "g", image, np.array([[0, 1]])
    )
    result = engine.train_model(
        [sample], engine.TrainingConfig(epochs=1, learning_rate=0.5)
    )
    assert result["model"]["weights"] == pytest.approx([0.125, 0, 0, 0.125, 0, 0])


def test_resume_and_reproducibility_do_not_mutate_initial_checkpoint():
    engine = _engine()
    samples = [_sample(engine)]
    config = engine.TrainingConfig(epochs=20, seed=7)
    first = engine.train_model(samples, config)
    repeated = engine.train_model(samples, config)
    assert first["model"] == repeated["model"]
    frozen = json.dumps(first["model"], sort_keys=True)
    resumed = engine.train_model(samples, config, initial=first["model"])
    full = engine.train_model(samples, engine.TrainingConfig(epochs=40, seed=7))
    assert resumed["model"] == full["model"]
    assert resumed["training"]["loss_before"] == first["training"]["loss_after"]
    assert resumed["training"]["loss_after"] < first["training"]["loss_after"]
    assert (
        resumed["training"]["initial_model_sha256"]
        == hashlib.sha256(canonical_jcs_bytes(first["model"])).hexdigest()
    )
    assert json.dumps(first["model"], sort_keys=True) == frozen


@pytest.mark.parametrize("split", ["val", "test", "TRAIN", "unknown"])
def test_nontraining_split_is_rejected_even_in_mixed_input(split):
    engine = _engine()
    with pytest.raises(ValueError, match="TRAIN_SPLIT_REQUIRED"):
        engine.train_model(
            [_sample(engine), _sample(engine, sample_id="held-out", split=split)],
            engine.TrainingConfig(),
        )


@pytest.mark.parametrize("encoding", ["bool", "01", "0255"])
def test_explicit_binary_mask_encodings_train_identically(encoding):
    engine = _engine()
    sample = _sample(engine)
    mask = (
        sample.mask
        if encoding == "bool"
        else sample.mask.astype(np.uint8) * (255 if encoding == "0255" else 1)
    )
    config = engine.TrainingConfig(epochs=2)
    expected = engine.train_model([sample], config)["model"]
    assert engine.train_model([replace(sample, mask=mask)], config)["model"] == expected


@pytest.mark.parametrize(
    "bad_mask",
    [
        np.array([[0, 2]]),
        np.array([[1, 255]]),
        np.array([[0.0, np.nan]]),
        np.array([[0.0, np.inf]]),
        np.array([[0.0, 0.5]]),
        np.zeros((2, 2)),
    ],
)
def test_invalid_masks_rejected(bad_mask):
    engine = _engine()
    sample = engine.PixelSample(
        "bad", "train", "c", "g", np.zeros((1, 2, 3), dtype=np.uint8), bad_mask
    )
    with pytest.raises(ValueError, match="MASK_"):
        engine.train_model([sample], engine.TrainingConfig())


@pytest.mark.parametrize(
    "image",
    [
        np.zeros((0, 2, 3), dtype=np.uint8),
        np.zeros((2, 2), dtype=np.uint8),
        np.zeros((257, 2, 3), dtype=np.uint8),
        np.full((2, 2, 3), np.nan),
        np.zeros((2, 2, 3), dtype=np.float64),
    ],
)
def test_invalid_images_rejected_for_prediction(image):
    engine = _engine()
    with pytest.raises(ValueError, match="IMAGE_"):
        engine.predict(engine.initial_model(), image)


@pytest.mark.parametrize(
    "weights", [[0.0] * 5, [0.0] * 7, [np.nan] * 6, [np.inf] * 6, [True] * 6, ["0"] * 6]
)
def test_invalid_checkpoint_weights_rejected(weights):
    engine = _engine()
    model = engine.initial_model()
    model["weights"] = weights
    with pytest.raises(ValueError, match="MODEL_"):
        engine.predict(model, _sample(engine).image)


def test_stable_prediction_handles_large_logits():
    engine = _engine()
    model = engine.initial_model()
    model["weights"] = [10000.0, -10000.0, 0.0, 0.0, 0.0, 0.0]
    with np.errstate(over="raise", invalid="raise"):
        result = engine.predict(model, _sample(engine).image)
    assert np.isfinite(result).all()
    assert result.min() >= 0 and result.max() <= 1


@pytest.mark.parametrize(
    "values",
    [
        {"epochs": 0},
        {"epochs": 501},
        {"epochs": True},
        {"learning_rate": 0},
        {"learning_rate": 2.01},
        {"l2": -1},
        {"l2": 1.1},
        {"seed": -1},
        {"max_wall_seconds": 0.001},
        {"max_wall_seconds": 121},
        {"learning_rate": np.nan},
        {"l2": np.inf},
        {"max_wall_seconds": np.inf},
        {"extra": 1},
    ],
)
def test_config_constraints_and_nonfinite_rejected(values):
    engine = _engine()
    with pytest.raises(ValidationError):
        engine.TrainingConfig(**values)


def test_empty_single_class_and_sample_limits_rejected():
    engine = _engine()
    sample = _sample(engine)
    config = engine.TrainingConfig(epochs=1)
    for samples, code in [
        ([], "SAMPLE_COUNT"),
        (
            [replace(sample, mask=np.zeros_like(sample.mask))],
            "BOTH_PIXEL_CLASSES_REQUIRED",
        ),
        ([replace(sample, sample_id=str(i)) for i in range(65)], "SAMPLE_COUNT"),
        ([sample, sample], "DUPLICATE_SAMPLE_ID"),
    ]:
        with pytest.raises(ValueError, match=code):
            engine.train_model(samples, config)
    large = _sample(engine, size=256)
    with pytest.raises(ValueError, match="TOTAL_PIXEL_LIMIT"):
        engine.train_model(
            [replace(large, sample_id=str(i)) for i in range(16)], config
        )


def test_cancellation_never_returns_partial_success():
    engine = _engine()
    initial = engine.initial_model()
    checks = 0

    def cancelled():
        nonlocal checks
        checks += 1
        return checks >= 5

    with pytest.raises(ValueError, match="TRAINING_CANCELLED"):
        engine.train_model(
            [_sample(engine)], engine.TrainingConfig(epochs=80), initial, cancelled
        )
    assert initial == engine.initial_model()


def test_budget_exceeded_never_returns_success(monkeypatch):
    engine = _engine()
    tick = 0.0

    def clock():
        nonlocal tick
        tick += 0.02
        return tick

    monkeypatch.setattr(engine, "perf_counter", clock)
    with pytest.raises(ValueError, match="TRAINING_BUDGET_EXCEEDED"):
        engine.train_model(
            [_sample(engine)], engine.TrainingConfig(max_wall_seconds=0.01)
        )


@pytest.mark.parametrize("interrupt", ["budget", "cancel"])
def test_final_loss_boundary_cannot_promote_interrupted_run(monkeypatch, interrupt):
    engine = _engine()
    final_loss_finished = False
    loss_calls = 0
    original_loss = engine._loss

    def measured_loss(*args):
        nonlocal final_loss_finished, loss_calls
        result = original_loss(*args)
        loss_calls += 1
        if loss_calls == 2:
            final_loss_finished = True
        return result

    monkeypatch.setattr(engine, "_loss", measured_loss)
    monkeypatch.setattr(
        engine, "perf_counter", lambda: 1.0 if final_loss_finished else 0.0
    )
    code = "TRAINING_CANCELLED" if interrupt == "cancel" else "TRAINING_BUDGET_EXCEEDED"
    with pytest.raises(ValueError, match=code):
        engine.train_model(
            [_sample(engine)],
            engine.TrainingConfig(epochs=1, max_wall_seconds=0.1),
            should_cancel=(lambda: final_loss_finished)
            if interrupt == "cancel"
            else None,
        )
    assert loss_calls == 2


def test_l2_updates_nonbias_weights_with_actual_gradient():
    engine = _engine()
    image = np.array([[[0, 0, 0], [255, 0, 0]]], dtype=np.uint8)
    sample = engine.PixelSample("one", "train", "c", "g", image, np.array([[0, 1]]))
    model = engine.initial_model()
    weights = np.array([0.2, -0.1, 0.1, 0.1, -0.2, 0.3])
    model["weights"] = weights.tolist()
    features = np.array([[0, 0, 0, 0, 0, 1], [1, 0, 0, 1, 0, 1]])
    residual = 1 / (1 + np.exp(-(features @ weights))) - np.array([0, 1])
    gradient = features.T @ residual / 2
    gradient[:-1] += 0.2 * weights[:-1]
    expected = weights - 0.5 * gradient
    result = engine.train_model(
        [sample], engine.TrainingConfig(epochs=1, l2=0.2), model
    )
    assert result["model"]["weights"] == pytest.approx(expected)


def test_classes_may_be_distributed_across_training_samples():
    engine = _engine()
    sample = _sample(engine)
    background = replace(
        sample, sample_id="background", mask=np.zeros_like(sample.mask)
    )
    foreground = replace(sample, sample_id="foreground", mask=np.ones_like(sample.mask))
    result = engine.train_model(
        [background, foreground], engine.TrainingConfig(epochs=1)
    )
    assert result["training"]["training_pixel_count"] == 512


def test_checkpoint_schema_and_mutated_config_revalidated():
    engine = _engine()
    sample = _sample(engine)
    model = engine.initial_model()
    model["feature_version"] = "unknown"
    with pytest.raises(ValueError, match="MODEL_VERSION"):
        engine.train_model([sample], engine.TrainingConfig(epochs=1), model)
    config = engine.TrainingConfig()
    config.learning_rate = float("nan")
    with pytest.raises(ValidationError):
        engine.train_model([sample], config)
