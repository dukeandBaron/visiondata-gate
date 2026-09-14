"""Recompute bounded validation disagreements against frozen detector labels."""

from __future__ import annotations

import hashlib

from .audit_envelope import canonical_jcs_bytes
from .learning_yolo_backend import _match_validation_boxes


def _sha(value: object) -> str:
    return hashlib.sha256(canonical_jcs_bytes(value)).hexdigest()


def build_vision_feedback(
    project_id: str, run_id: str, dataset_id: str, dataset_receipt: dict, result: dict
) -> list[dict]:
    """Require every val member, recheck labels/matching, emit human-only tasks."""
    protocol = result.get("validation_feedback_protocol")
    if protocol is None:
        # Explicit compatibility for old persisted results; absence is not zero errors.
        return []
    expected = {
        s["sample_id"]: s for s in dataset_receipt["samples"] if s["split"] == "val"
    }
    details = result["validation_samples_detail"]
    if (
        protocol["schema_version"] != "visiondata-gate.validation-feedback.v1"
        or protocol["split"] != "val"
        or protocol["confidence_threshold"] != 0.25
        or protocol["iou_threshold"] != 0.5
        or protocol["max_detections"] != 300
        or protocol["matching"] != "class_aware_greedy_iou_descending"
        or protocol["tie_break"] != "prediction_index_then_ground_truth_index"
        or protocol["prediction_order"]
        != "confidence_descending_then_class_and_coordinates"
        or protocol["review_required"] is not True
        or protocol["label_truth_status"] != "REFERENCE_LABELS_NOT_ADJUDICATED"
        or protocol["dataset_sha256"] != result["dataset_sha256"]
        or protocol["checkpoint_sha256"] != result["checkpoint"]["sha256"]
        or protocol["runtime_sha256"] != result["runtime_sha256"]
        or protocol["sample_count"] != len(expected)
        or len(details) != len(expected)
        or {d["sample_id"] for d in details} != set(expected)
    ):
        raise ValueError("VISION_FEEDBACK_PROTOCOL_BINDING_INVALID")
    compact_keys = (
        "sample_id",
        "image_sha256",
        "label_sha256",
        "tp",
        "fp",
        "fn",
        "reason_codes",
        "review_required",
    )
    compact = [
        {key: row[key] for key in compact_keys}
        for row in details
        if row["fp"] or row["fn"]
    ]
    if result.get("validation_feedback_candidates") != compact:
        raise ValueError("VISION_FEEDBACK_CANDIDATE_PROJECTION_CHANGED")
    candidates = []
    for row in details:
        sample = expected[row["sample_id"]]
        if (
            row["image_sha256"] != sample["image_sha256"]
            or row["label_sha256"] != sample["label_sha256"]
        ):
            raise ValueError("VISION_FEEDBACK_MEMBER_CHANGED")
        truth = row["ground_truth_boxes"]
        if len(truth) != len(sample["boxes"]):
            raise ValueError("VISION_FEEDBACK_LABEL_CHANGED")
        for observed, box in zip(truth, sample["boxes"], strict=True):
            target = [
                box["x_center"] - box["width"] / 2,
                box["y_center"] - box["height"] / 2,
                box["x_center"] + box["width"] / 2,
                box["y_center"] + box["height"] / 2,
            ]
            if observed["class_id"] != box["class_id"] or any(
                abs(a - b) > 1e-5 for a, b in zip(observed["xyxy"], target, strict=True)
            ):
                raise ValueError("VISION_FEEDBACK_LABEL_CHANGED")
        if any(
            p["class_id"] >= len(dataset_receipt["class_names"])
            for p in row["prediction_boxes"]
        ):
            raise ValueError("VISION_FEEDBACK_CLASS_UNKNOWN")
        matched = _match_validation_boxes(row["prediction_boxes"], truth)
        if any(row[key] != matched[key] for key in matched):
            raise ValueError("VISION_FEEDBACK_MATCHING_CHANGED")
        if not row["fp"] and not row["fn"]:
            continue
        identifier = (
            "vfeedback_"
            + _sha({"run_id": run_id, "sample": row, "protocol": protocol})[:24]
        )
        candidates.append(
            {
                "schema_version": "visiondata-gate.vision-feedback.v1",
                "resource_id": identifier,
                "feedback_id": identifier,
                "project_id": project_id,
                "run_id": run_id,
                "dataset_id": dataset_id,
                "dataset_receipt_sha256": dataset_receipt["receipt_sha256"],
                "sample_id": row["sample_id"],
                "split": "val",
                "image_sha256": row["image_sha256"],
                "label_sha256": row["label_sha256"],
                "checkpoint_sha256": result["checkpoint"]["sha256"],
                "protocol_sha256": _sha(protocol),
                "detail": row,
                "status": "PENDING_HUMAN_REVIEW",
                "classification": None,
                "issue_closed": False,
                "label_truth_authority": False,
                "training_ingestion_allowed": False,
                "production_release_allowed": False,
            }
        )
    return candidates
