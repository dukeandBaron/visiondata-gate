"""Pixel-level candidate evaluation with explicit missing evidence and CPU limits.

This module neither trains models nor changes annotations. Validation feedback is
only a candidate for human review; test evaluation emits no per-sample feedback.
Latency is a single local CPU observation per prediction, not a device benchmark.
"""

from __future__ import annotations

import hashlib
import struct
import time

import numpy as np
from pydantic import BaseModel, ConfigDict, Field

from .audit_envelope import canonical_jcs_bytes
from .learning_engine import PixelSample, predict


class EvaluationPolicy(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)

    threshold: float = Field(default=0.5, gt=0, lt=1, strict=True)
    max_false_negative_rate: float = Field(default=0.2, ge=0, le=1, strict=True)
    max_false_positive_rate: float = Field(default=0.2, ge=0, le=1, strict=True)
    min_dice: float = Field(default=0.7, ge=0, le=1, strict=True)
    min_dice_gain: float = Field(default=0.001, ge=0, le=1, strict=True)
    max_category_dice_regression: float = Field(default=0.0, ge=0, le=1, strict=True)
    max_p95_latency_ms: float = Field(default=1000.0, gt=0, le=60000, strict=True)


_COUNT_KEYS = ("tp", "fp", "tn", "fn")
_MEASURED_KEYS = ("dice", "false_negative_rate", "false_positive_rate")
_MODEL_NAMES = ("candidate", "baseline")


def _validate_samples(samples: list[PixelSample], split: str) -> list[np.ndarray]:
    if split not in {"val", "test"}:
        raise ValueError("EVALUATION_SPLIT_INVALID")
    if not isinstance(samples, list) or not samples:
        raise ValueError("EVALUATION_SAMPLES_EMPTY")
    seen: set[str] = set()
    masks: list[np.ndarray] = []
    for sample in samples:
        if not isinstance(sample, PixelSample):
            raise ValueError("PIXEL_SAMPLE_REQUIRED")
        if sample.split != split:
            raise ValueError("SAMPLE_SPLIT_MISMATCH")
        if not isinstance(sample.sample_id, str) or not sample.sample_id.strip():
            raise ValueError("SAMPLE_ID_INVALID")
        if sample.sample_id in seen:
            raise ValueError("SAMPLE_ID_DUPLICATE")
        seen.add(sample.sample_id)
        if not isinstance(sample.category, str) or not sample.category.strip():
            raise ValueError("SAMPLE_CATEGORY_INVALID")
        if not isinstance(sample.group_id, str) or not sample.group_id.strip():
            raise ValueError("SAMPLE_GROUP_ID_INVALID")
        image, mask = sample.image, sample.mask
        if (not isinstance(image, np.ndarray) or image.dtype != np.uint8
                or image.ndim != 3 or image.shape[2] != 3
                or not all(1 <= size <= 256 for size in image.shape[:2])):
            raise ValueError("SAMPLE_IMAGE_INVALID")
        if (not isinstance(mask, np.ndarray) or mask.ndim != 2
                or mask.shape != image.shape[:2] or mask.dtype.kind not in "buif"
                or not np.isfinite(mask).all()):
            raise ValueError("SAMPLE_MASK_INVALID")
        if not (np.isin(mask, [0, 1]).all() or np.isin(mask, [0, 255]).all()):
            raise ValueError("SAMPLE_MASK_INVALID")
        masks.append(mask != 0)
    return masks


def _predict_checked(model: dict, image: np.ndarray) -> tuple[np.ndarray, float]:
    started = time.perf_counter()
    probabilities = predict(model, image)
    elapsed_ms = (time.perf_counter() - started) * 1000.0
    if (not isinstance(probabilities, np.ndarray)
            or probabilities.shape != image.shape[:2]
            or probabilities.dtype.kind not in "buif"
            or not np.isfinite(probabilities).all()
            or np.any(probabilities < 0) or np.any(probabilities > 1)):
        raise ValueError("PREDICTION_INVALID")
    if not np.isfinite(elapsed_ms) or elapsed_ms < 0:
        raise ValueError("LATENCY_OBSERVATION_INVALID")
    return probabilities, elapsed_ms


def _pixel_counts(truth: np.ndarray, prediction: np.ndarray) -> dict[str, int]:
    return {
        "tp": int(np.count_nonzero(truth & prediction)),
        "fp": int(np.count_nonzero(~truth & prediction)),
        "tn": int(np.count_nonzero(~truth & ~prediction)),
        "fn": int(np.count_nonzero(truth & ~prediction)),
    }


def _metrics(counts: dict[str, int]) -> dict:
    tp, fp, tn, fn = (counts[key] for key in _COUNT_KEYS)
    dice_denominator = 2 * tp + fp + fn
    positive_count, negative_count = tp + fn, fp + tn
    pixel_count = positive_count + negative_count
    return {
        **counts,
        "dice": 2 * tp / dice_denominator if dice_denominator else None,
        "false_negative_rate": fn / positive_count if positive_count else None,
        "false_positive_rate": fp / negative_count if negative_count else None,
        "error_rate": (fp + fn) / pixel_count if pixel_count else None,
    }


def _array_digest(array: np.ndarray, *, probabilities: bool = False) -> str:
    domain = b"visiondata-gate.probability-map.v1\0" if probabilities else b"visiondata-gate.binary-mask.v1\0"
    canonical = np.ascontiguousarray(array, dtype="<f8" if probabilities else np.uint8)
    framed = domain + struct.pack(">II", *canonical.shape) + canonical.tobytes(order="C")
    return hashlib.sha256(framed).hexdigest()


def _new_counts() -> dict[str, dict[str, int]]:
    return {name: {key: 0 for key in _COUNT_KEYS} for name in _MODEL_NAMES}


def _unmeasured_blockers(metrics: dict, prefix: str) -> list[str]:
    return [
        f"{prefix}:{name}:{key}"
        for name in _MODEL_NAMES
        for key in _MEASURED_KEYS
        if metrics[name][key] is None
    ]


def evaluate_models(
    candidate: dict,
    baseline: dict,
    samples: list[PixelSample],
    policy: EvaluationPolicy,
    split: str = "val",
) -> dict:
    """Evaluate one frozen split using the same inclusive threshold for both models.

    Invalid inputs fail before prediction. Eligibility requires measured positive
    and negative populations overall and in every category, candidate absolute
    limits, strictly positive minimum Dice gain, no excessive category regression,
    and candidate p95 latency within budget. Baseline latency is descriptive only.
    """
    if not isinstance(policy, EvaluationPolicy):
        raise ValueError("EVALUATION_POLICY_REQUIRED")
    policy = EvaluationPolicy.model_validate(policy.model_dump(mode="python"))
    started = time.perf_counter()
    masks = _validate_samples(samples, split)
    total_counts = _new_counts()
    category_counts: dict[str, dict[str, dict[str, int]]] = {}
    elapsed_ms: dict[str, list[float]] = {name: [] for name in _MODEL_NAMES}
    sample_results: list[dict] = []
    for sample, truth in zip(samples, masks, strict=True):
        bucket = category_counts.setdefault(sample.category, _new_counts())
        sample_metrics: dict[str, dict] = {}
        for name, current_model in (("candidate", candidate), ("baseline", baseline)):
            probabilities, duration = _predict_checked(current_model, sample.image)
            elapsed_ms[name].append(duration)
            prediction = probabilities >= policy.threshold
            counts = _pixel_counts(truth, prediction)
            for key in _COUNT_KEYS:
                total_counts[name][key] += counts[key]
                bucket[name][key] += counts[key]
            if split == "val":
                sample_metrics[name] = {
                    **_metrics(counts),
                    "prediction_sha256": _array_digest(probabilities, probabilities=True),
                    "prediction_mask_sha256": _array_digest(prediction),
                }
        if split == "val":
            sample_results.append({
                "sample_id": sample.sample_id,
                "category": sample.category,
                "group_id": sample.group_id,
                "truth_mask_sha256": _array_digest(truth),
                **sample_metrics,
                "error_candidate": bool(sample_metrics["candidate"]["fp"] + sample_metrics["candidate"]["fn"]),
                "review_status": "PENDING_HUMAN_REVIEW",
                "annotation_error_confirmed": False,
            })

    aggregate = {name: _metrics(total_counts[name]) for name in _MODEL_NAMES}
    categories = {
        category: {name: _metrics(category_counts[category][name]) for name in _MODEL_NAMES}
        for category in sorted(category_counts)
    }
    latency = {
        "scope": "LOCAL_CPU_OBSERVATION_ONLY",
        "timer": "time.perf_counter",
        "measurement": "predict_call_only",
        "model_order": ["candidate", "baseline"],
        "observations_per_sample": 1,
        "warmup_runs": 0,
        "quantile_method": "linear",
        "benchmark_claim": False,
        **{
            name: {
                "sample_count": len(elapsed_ms[name]),
                "p95_ms": float(np.percentile(elapsed_ms[name], 95, method="linear")),
            }
            for name in _MODEL_NAMES
        },
    }
    blockers = _unmeasured_blockers(aggregate, "AGGREGATE_METRIC_NOT_MEASURED")
    candidate_metrics, baseline_metrics = aggregate["candidate"], aggregate["baseline"]
    for key, limit, code in (
        ("false_negative_rate", policy.max_false_negative_rate, "FALSE_NEGATIVE_RATE_EXCEEDED"),
        ("false_positive_rate", policy.max_false_positive_rate, "FALSE_POSITIVE_RATE_EXCEEDED"),
    ):
        if candidate_metrics[key] is not None and candidate_metrics[key] > limit:
            blockers.append(code)
    candidate_dice, baseline_dice = candidate_metrics["dice"], baseline_metrics["dice"]
    if candidate_dice is not None and candidate_dice < policy.min_dice:
        blockers.append("MIN_DICE_NOT_MET")
    if candidate_dice is not None and baseline_dice is not None:
        gain = candidate_dice - baseline_dice
        if gain <= 0 or gain < policy.min_dice_gain:
            blockers.append("INSUFFICIENT_DICE_GAIN")
    for category, metrics in categories.items():
        blockers.extend(_unmeasured_blockers(metrics, f"CATEGORY_METRIC_NOT_MEASURED:{category}"))
        candidate_dice = metrics["candidate"]["dice"]
        baseline_dice = metrics["baseline"]["dice"]
        if (candidate_dice is not None and baseline_dice is not None
                and baseline_dice - candidate_dice > policy.max_category_dice_regression):
            blockers.append(f"CATEGORY_DICE_REGRESSION:{category}")
    if latency["candidate"]["p95_ms"] > policy.max_p95_latency_ms:
        blockers.append("CANDIDATE_LATENCY_BUDGET_EXCEEDED")
    observed_elapsed = time.perf_counter() - started
    if not np.isfinite(observed_elapsed) or observed_elapsed < 0:
        raise ValueError("ELAPSED_OBSERVATION_INVALID")
    result = {
        "schema_version": "visiondata-gate.learning-evaluation.v1",
        "split": split,
        "policy": policy.model_dump(mode="json"),
        "aggregate": aggregate,
        "categories": categories,
        "sample_results": sample_results,
        "latency": latency,
        "decision": "HOLD" if blockers else "ELIGIBLE",
        "blockers": blockers,
        "observed_elapsed_seconds": observed_elapsed,
    }
    canonical_jcs_bytes(result)
    return result
