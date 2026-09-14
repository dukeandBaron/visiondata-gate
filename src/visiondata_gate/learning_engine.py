"""Bounded NumPy CPU pixel logistic regression, not reinforcement learning.

Feature order is R/255, G/255, B/255, x, y, bias. Coordinates span [0, 1]
(a singleton dimension uses 0). Checkpoints contain JSON weights only. Training
uses deterministic full-batch gradient descent from a zero/default or supplied
checkpoint; seed is recorded in the config but no random sampling is performed.
Loss is mean binary cross-entropy plus l2/2 times the squared non-bias weights.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
import hashlib
import math
from time import perf_counter

import numpy as np
from pydantic import BaseModel, ConfigDict, Field

from .audit_envelope import canonical_jcs_bytes


@dataclass(frozen=True)
class PixelSample:
    sample_id: str
    split: str
    category: str
    group_id: str
    image: np.ndarray
    mask: np.ndarray


class TrainingConfig(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)

    epochs: int = Field(default=80, ge=1, le=500, strict=True)
    learning_rate: float = Field(default=0.5, ge=0.0001, le=2, strict=True)
    l2: float = Field(default=0.0, ge=0, le=1, strict=True)
    max_wall_seconds: float = Field(default=20.0, ge=0.01, le=120, strict=True)
    seed: int = Field(default=0, ge=0, strict=True)


def initial_model() -> dict:
    return {
        "schema_version": "visiondata-gate.pixel-logistic.v1",
        "feature_version": "rgb_xy_v1",
        "weights": [0.0] * 6,
    }


def _validated_model(model: dict) -> dict:
    if not isinstance(model, dict) or set(model) != {
        "schema_version",
        "feature_version",
        "weights",
    }:
        raise ValueError("MODEL_SCHEMA")
    if (
        model["schema_version"] != "visiondata-gate.pixel-logistic.v1"
        or model["feature_version"] != "rgb_xy_v1"
    ):
        raise ValueError("MODEL_VERSION")
    values = model["weights"]
    if (
        not isinstance(values, list)
        or len(values) != 6
        or any(type(value) not in {int, float} for value in values)
    ):
        raise ValueError("MODEL_WEIGHTS")
    try:
        weights = [float(value) for value in values]
    except (OverflowError, ValueError) as error:
        raise ValueError("MODEL_WEIGHTS_NONFINITE") from error
    if not all(math.isfinite(value) for value in weights):
        raise ValueError("MODEL_WEIGHTS_NONFINITE")
    return {**initial_model(), "weights": weights}


def _image_shape(image: np.ndarray) -> tuple[int, int]:
    if not isinstance(image, np.ndarray) or image.dtype != np.uint8:
        raise ValueError("IMAGE_RGB_UINT8_REQUIRED")
    if image.ndim != 3 or image.shape[2] != 3:
        raise ValueError("IMAGE_RGB_SHAPE")
    height, width = image.shape[:2]
    if not (1 <= height <= 256 and 1 <= width <= 256):
        raise ValueError("IMAGE_SIZE_LIMIT")
    return height, width


def _features(image: np.ndarray) -> np.ndarray:
    height, width = _image_shape(image)
    features = np.empty((height * width, 6), dtype=np.float64)
    features[:, :3] = image.reshape(-1, 3).astype(np.float64) / 255.0
    features[:, 3] = np.tile(np.linspace(0.0, 1.0, width), height)
    features[:, 4] = np.repeat(np.linspace(0.0, 1.0, height), width)
    features[:, 5] = 1.0
    return features


def _labels(mask: np.ndarray, shape: tuple[int, int]) -> np.ndarray:
    if not isinstance(mask, np.ndarray) or mask.shape != shape or mask.ndim != 2:
        raise ValueError("MASK_SHAPE")
    if mask.dtype.kind not in "buif" or not np.isfinite(mask).all():
        raise ValueError("MASK_NONFINITE_OR_NONNUMERIC")
    values = np.unique(mask)
    encoded_01 = np.isin(values, [0, 1]).all()
    encoded_0255 = np.isin(values, [0, 255]).all()
    if not (encoded_01 or encoded_0255):
        raise ValueError("MASK_BINARY_ENCODING_REQUIRED")
    return (mask.reshape(-1) != 0).astype(np.float64)


def _sigmoid(logits: np.ndarray) -> np.ndarray:
    if not np.isfinite(logits).all():
        raise ValueError("MODEL_NUMERIC_OVERFLOW")
    result = np.empty_like(logits, dtype=np.float64)
    positive = logits >= 0
    result[positive] = 1.0 / (1.0 + np.exp(-logits[positive]))
    exp_negative = np.exp(logits[~positive])
    result[~positive] = exp_negative / (1.0 + exp_negative)
    return result


def predict(model: dict, image: np.ndarray) -> np.ndarray:
    validated = _validated_model(model)
    features = _features(image)
    try:
        with np.errstate(over="raise", invalid="raise"):
            logits = features @ np.asarray(validated["weights"], dtype=np.float64)
            return _sigmoid(logits).reshape(image.shape[:2])
    except FloatingPointError as error:
        raise ValueError("MODEL_NUMERIC_OVERFLOW") from error


def _loss(
    features: np.ndarray, labels: np.ndarray, weights: np.ndarray, l2: float
) -> float:
    logits = features @ weights
    loss = float(np.mean(np.logaddexp(0.0, logits) - labels * logits))
    if l2:
        loss += 0.5 * l2 * float(weights[:-1] @ weights[:-1])
    if not math.isfinite(loss):
        raise ValueError("TRAINING_NUMERIC_OVERFLOW")
    return loss


def train_model(
    samples: list[PixelSample],
    config: TrainingConfig,
    initial: dict | None = None,
    should_cancel: Callable[[], bool] | None = None,
) -> dict:
    """Update six weights using train-only pixels; interruptions never succeed.

    The supplied arrays and checkpoint are never modified. Validation and feature
    preparation count toward wall time. Bounds are checked before and after each
    epoch, including the final loss calculation; no partial checkpoint is returned.
    """
    if not isinstance(config, TrainingConfig):
        raise ValueError("TRAINING_CONFIG_REQUIRED")
    # Revalidate mutable or model_construct-created config instances at the boundary.
    config = TrainingConfig.model_validate(config.model_dump(mode="python"))
    if should_cancel is not None and not callable(should_cancel):
        raise ValueError("CANCEL_CALLBACK_INVALID")
    started = perf_counter()

    def check_budget() -> float:
        if should_cancel is not None and should_cancel():
            raise ValueError("TRAINING_CANCELLED")
        elapsed = perf_counter() - started
        if elapsed >= config.max_wall_seconds:
            raise ValueError("TRAINING_BUDGET_EXCEEDED")
        return elapsed

    check_budget()
    if not isinstance(samples, list) or not 1 <= len(samples) <= 64:
        raise ValueError("SAMPLE_COUNT")
    if any(not isinstance(sample, PixelSample) for sample in samples):
        raise ValueError("PIXEL_SAMPLE_REQUIRED")
    if any(sample.split != "train" for sample in samples):
        raise ValueError("TRAIN_SPLIT_REQUIRED")
    if any(
        not isinstance(value, str) or not value.strip()
        for sample in samples
        for value in (sample.sample_id, sample.category, sample.group_id)
    ):
        raise ValueError("SAMPLE_METADATA")
    sample_ids = [sample.sample_id for sample in samples]
    if len(set(sample_ids)) != len(sample_ids):
        raise ValueError("DUPLICATE_SAMPLE_ID")
    checkpoint = _validated_model(initial_model() if initial is None else initial)
    weights = np.asarray(checkpoint["weights"], dtype=np.float64).copy()
    initial_sha = hashlib.sha256(canonical_jcs_bytes(checkpoint)).hexdigest()
    pixel_count = 0
    labels_by_sample: list[np.ndarray] = []
    for sample in samples:
        shape = _image_shape(sample.image)
        pixel_count += shape[0] * shape[1]
        if pixel_count > 1_000_000:
            raise ValueError("TOTAL_PIXEL_LIMIT")
        labels_by_sample.append(_labels(sample.mask, shape))
        check_budget()
    labels = np.concatenate(labels_by_sample)
    if not ((labels == 0).any() and (labels == 1).any()):
        raise ValueError("BOTH_PIXEL_CLASSES_REQUIRED")
    features = np.concatenate([_features(sample.image) for sample in samples], axis=0)
    check_budget()
    try:
        with np.errstate(over="raise", invalid="raise", divide="raise"):
            loss_before = _loss(features, labels, weights, config.l2)
            for _epoch in range(config.epochs):
                check_budget()
                residual = _sigmoid(features @ weights) - labels
                gradient = (features.T @ residual) / pixel_count
                gradient[:-1] += config.l2 * weights[:-1]
                weights = weights - config.learning_rate * gradient
                if not np.isfinite(weights).all():
                    raise ValueError("TRAINING_NUMERIC_OVERFLOW")
                check_budget()
            loss_after = _loss(features, labels, weights, config.l2)
    except FloatingPointError as error:
        raise ValueError("TRAINING_NUMERIC_OVERFLOW") from error
    elapsed = check_budget()
    model = _validated_model({**checkpoint, "weights": weights.tolist()})
    return {
        "model": model,
        "training": {
            "loss_before": loss_before,
            "loss_after": loss_after,
            "epochs_completed": config.epochs,
            "training_sample_ids": sample_ids,
            "training_pixel_count": pixel_count,
            "elapsed_seconds": elapsed,
            "initial_model_sha256": initial_sha,
            "optimizer": "full_batch_gradient_descent",
            "device": "CPU",
        },
    }


__all__ = ["PixelSample", "TrainingConfig", "initial_model", "predict", "train_model"]
