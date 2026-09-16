"""Calibration-only operating-point selection; never authorizes production use."""

from __future__ import annotations

from dataclasses import dataclass, asdict
import hashlib
import math
from typing import Any

import numpy as np

from .audit_envelope import canonical_jcs_bytes


@dataclass(frozen=True)
class OperatingPolicy:
    min_recall: float
    max_false_positive_rate: float

    def __post_init__(self):
        for value in (self.min_recall, self.max_false_positive_rate):
            if (
                isinstance(value, bool)
                or not math.isfinite(value)
                or not 0 <= value <= 1
            ):
                raise ValueError("INVALID_OPERATING_POLICY")


def _validate_rows(rows: list[dict], *, role: str) -> list[dict]:
    if not rows or len(rows) > 100_000:
        raise ValueError("INVALID_SAMPLE_COUNT")
    identifiers = set()
    channels = None
    labels = set()
    for row in rows:
        identifier = row.get("source_sample_id")
        if (
            not isinstance(identifier, str)
            or not identifier
            or identifier in identifiers
        ):
            raise ValueError("INVALID_OR_DUPLICATE_SAMPLE_ID")
        identifiers.add(identifier)
        if row.get("split_role") != role:
            raise ValueError("SPLIT_ROLE_MISMATCH")
        label = row.get("product_label")
        if label not in {"normal", "anomaly"}:
            raise ValueError("UNKNOWN_REFERENCE_LABEL")
        labels.add(label)
        scores = row.get("image_scores")
        if not isinstance(scores, dict) or not scores or len(scores) > 32:
            raise ValueError("MISSING_SCORE_CHANNELS")
        if channels is None:
            channels = set(scores)
        if set(scores) != channels:
            raise ValueError("SCORE_CHANNEL_SET_CHANGED")
        for key, value in scores.items():
            if (
                not isinstance(key, str)
                or not key
                or type(value) not in {int, float}
                or not math.isfinite(value)
            ):
                raise ValueError("NONFINITE_OR_INVALID_SCORE")
    if labels != {"normal", "anomaly"}:
        raise ValueError("BOTH_REFERENCE_CLASSES_REQUIRED")
    return rows


def _wilson(successes: int, count: int) -> list[float]:
    p, z = successes / count, 1.959963984540054
    divisor = 1 + z * z / count
    center = (p + z * z / (2 * count)) / divisor
    half = z * math.sqrt(p * (1 - p) / count + z * z / (4 * count * count)) / divisor
    return [max(0.0, center - half), min(1.0, center + half)]


def confusion_metrics(rows: list[dict], channel: str, threshold: float) -> dict:
    if not math.isfinite(threshold):
        raise ValueError("NONFINITE_THRESHOLD")
    tp = fp = tn = fn = 0
    for row in rows:
        predicted = row["image_scores"][channel] >= threshold
        actual = row["product_label"] == "anomaly"
        tp += int(predicted and actual)
        fp += int(predicted and not actual)
        tn += int(not predicted and not actual)
        fn += int(not predicted and actual)
    return _count_metrics(tp, fp, tn, fn)


def _count_metrics(tp: int, fp: int, tn: int, fn: int) -> dict:
    if not (tp + fn and tn + fp):
        raise ValueError("BOTH_REFERENCE_CLASSES_REQUIRED")
    return {
        "tp": tp,
        "fp": fp,
        "tn": tn,
        "fn": fn,
        "sample_count": tp + fp + tn + fn,
        "positive_count": tp + fn,
        "negative_count": tn + fp,
        "accuracy": (tp + tn) / (tp + fp + tn + fn),
        "recall": tp / (tp + fn),
        "false_negative_rate": fn / (tp + fn),
        "false_positive_rate": fp / (fp + tn),
        "precision": tp / (tp + fp) if tp + fp else None,
        "f1": 2 * tp / (2 * tp + fp + fn),
        "recall_wilson_95": _wilson(tp, tp + fn),
        "fpr_wilson_95": _wilson(fp, fp + tn),
    }


def select_operating_point(calibration: list[dict], policy: OperatingPolicy) -> dict:
    """Choose score channel and threshold jointly, without evaluation inputs."""
    rows = _validate_rows(calibration, role="calibration")
    best = None
    best_rank = None
    for channel in sorted(rows[0]["image_scores"]):
        ordered = sorted(rows, key=lambda row: row["image_scores"][channel])
        scores = np.asarray(
            [row["image_scores"][channel] for row in ordered], dtype=float
        )
        positive_prefix = np.concatenate(
            ([0], np.cumsum([row["product_label"] == "anomaly" for row in ordered]))
        )
        positives = int(positive_prefix[-1])
        negatives = len(rows) - positives
        thresholds, indices = np.unique(scores, return_index=True)
        points = list(zip(thresholds.tolist(), indices.tolist(), strict=True))
        points.append((math.nextafter(float(scores[-1]), math.inf), len(rows)))
        for threshold, index in points:
            if not math.isfinite(threshold):
                continue
            fn = int(positive_prefix[index])
            tn = index - fn
            tp, fp = positives - fn, negatives - tn
            if fp / negatives > policy.max_false_positive_rate:
                continue
            rank = (
                tp / positives,
                -fp / negatives,
                2 * tp / (2 * tp + fp + fn),
                threshold,
                channel,
            )
            if best_rank is None or rank > best_rank:
                best_rank = rank
                best = {
                    "channel": channel,
                    "threshold": threshold,
                    "metrics": _count_metrics(tp, fp, tn, fn),
                }
    if best is None:
        raise ValueError("NO_FINITE_OPERATING_POINT")
    eligible = best["metrics"]["recall"] >= policy.min_recall
    payload = {
        "schema_version": "visiondata-gate.anomaly-operating-point.v1",
        "status": "CALIBRATION_TARGET_MET"
        if eligible
        else "HOLD_NO_FEASIBLE_OPERATING_POINT",
        "policy": asdict(policy),
        "selection_objective": "MAX_RECALL_UNDER_FPR_CAP",
        "calibration_sha256": hashlib.sha256(
            canonical_jcs_bytes(sorted(rows, key=lambda x: x["source_sample_id"]))
        ).hexdigest(),
        "calibration_ids": sorted(row["source_sample_id"] for row in rows),
        "diagnostic_candidate": best,
        "deployable_threshold": None,
        "independent_evaluation_required": True,
        "production_release_allowed": False,
        "machine_write_permitted": False,
        "confidence_boundary": "EMPIRICAL_TARGET_NOT_A_POPULATION_GUARANTEE",
    }
    payload["receipt_sha256"] = hashlib.sha256(canonical_jcs_bytes(payload)).hexdigest()
    return payload


def evaluate_operating_point(selection: dict, evaluation: list[dict]) -> dict:
    bound = {k: v for k, v in selection.items() if k != "receipt_sha256"}
    if hashlib.sha256(canonical_jcs_bytes(bound)).hexdigest() != selection.get(
        "receipt_sha256"
    ):
        raise ValueError("SELECTION_RECEIPT_DRIFT")
    rows = _validate_rows(evaluation, role="heldout_development")
    if set(selection["calibration_ids"]) & {row["source_sample_id"] for row in rows}:
        raise ValueError("CALIBRATION_EVALUATION_OVERLAP")
    candidate = selection["diagnostic_candidate"]
    if candidate["channel"] not in rows[0]["image_scores"]:
        raise ValueError("EVALUATION_SCORE_CHANNEL_MISSING")
    metrics = confusion_metrics(rows, candidate["channel"], candidate["threshold"])
    policy = OperatingPolicy(**selection["policy"])
    met = (
        metrics["recall"] >= policy.min_recall
        and metrics["false_positive_rate"] <= policy.max_false_positive_rate
    )
    return {
        "status": "TARGET_MET_PENDING_INDEPENDENT_REVIEW"
        if met and selection["status"] == "CALIBRATION_TARGET_MET"
        else "HOLD_OPERATING_TARGET_NOT_MET",
        "metrics": metrics,
        "selection_receipt_sha256": selection["receipt_sha256"],
        "evaluation_sha256": hashlib.sha256(
            canonical_jcs_bytes(sorted(rows, key=lambda x: x["source_sample_id"]))
        ).hexdigest(),
        "evaluation_used_for_selection": False,
        "production_release_allowed": False,
    }


def summarize_anomaly_map(values: Any) -> dict[str, float]:
    """Offer bounded local-score channels without accepting any reference Mask."""
    array = np.asarray(values, dtype=np.float64)
    if (
        array.ndim != 2
        or not array.size
        or array.size > 16_777_216
        or not np.isfinite(array).all()
    ):
        raise ValueError("INVALID_ANOMALY_MAP")
    flat = np.sort(array.ravel())
    return {
        "mean": float(flat.mean()),
        "max": float(flat[-1]),
        **{
            "top_" + str(fraction).replace(".", "_") + "pct": float(
                flat[-max(1, int(flat.size * fraction / 100)) :].mean()
            )
            for fraction in (0.1, 0.5, 1, 2, 5, 10)
        },
    }


