"""Synthetic unit evidence for validation disagreements, never label truth."""

from __future__ import annotations

import copy
import re
from types import SimpleNamespace

import pytest

from visiondata_gate.local_model_registry import (
    LocalVisionModelService,
    VisionModelError,
)
from visiondata_gate.vision_feedback import build_vision_feedback


def feedback_result(receipt, *, clear=False, base=None):
    """Known one-box fixture; counts are specified, not computed by the matcher."""
    result = (
        copy.deepcopy(base)
        if base
        else {
            "dataset_sha256": "d" * 64,
            "runtime_sha256": "a" * 64,
            "checkpoint": {"sha256": "c" * 64},
            "evidence_origin": "TEST_DOUBLE_NO_TRAINING_EXECUTION",
        }
    )
    details = []
    for sample in receipt["samples"]:
        if sample["split"] != "val":
            continue
        box = sample["boxes"][0]
        truth = {
            "class_id": box["class_id"],
            "xyxy": [
                box["x_center"] - box["width"] / 2,
                box["y_center"] - box["height"] / 2,
                box["x_center"] + box["width"] / 2,
                box["y_center"] + box["height"] / 2,
            ],
        }
        details.append(
            {
                "sample_id": sample["sample_id"],
                "image_sha256": sample["image_sha256"],
                "label_sha256": sample["label_sha256"],
                "ground_truth_boxes": [truth],
                "prediction_boxes": [{**truth, "confidence": 0.8}] if clear else [],
                "tp": 1 if clear else 0,
                "fp": 0,
                "fn": 0 if clear else 1,
                "matched_ious": [1.0] if clear else [],
                "matches": [
                    {"prediction_index": 0, "ground_truth_index": 0, "iou": 1.0}
                ]
                if clear
                else [],
                "reason_codes": [] if clear else ["FALSE_NEGATIVE_CANDIDATE"],
                "review_required": True,
            }
        )
    result["validation_samples_detail"] = details
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
    result["validation_feedback_candidates"] = [
        {key: copy.deepcopy(row[key]) for key in compact_keys}
        for row in details
        if row["fp"] or row["fn"]
    ]
    result["validation_feedback_protocol"] = {
        "schema_version": "visiondata-gate.validation-feedback.v1",
        "split": "val",
        "confidence_threshold": 0.25,
        "iou_threshold": 0.5,
        "max_detections": 300,
        "matching": "class_aware_greedy_iou_descending",
        "prediction_order": "confidence_descending_then_class_and_coordinates",
        "tie_break": "prediction_index_then_ground_truth_index",
        "dataset_sha256": result["dataset_sha256"],
        "checkpoint_sha256": result["checkpoint"]["sha256"],
        "runtime_sha256": result["runtime_sha256"],
        "sample_count": len(details),
        "review_required": True,
        "label_truth_status": "REFERENCE_LABELS_NOT_ADJUDICATED",
        "interpretation": "Fixed operating-point disagreements, not aggregate mAP or adjudicated label errors",
    }
    return result


@pytest.fixture
def receipt():
    return {
        "receipt_sha256": "f" * 64,
        "source_version": "TEST_DOUBLE_v1",
        "class_names": ["scratch"],
        "samples": [
            {
                "sample_id": "val-1",
                "split": "val",
                "image_sha256": "1" * 64,
                "label_sha256": "2" * 64,
                "pixel_sha256": "4" * 64,
                "group_id": "part-val",
                "annotation_revision": 1,
                "boxes": [
                    {
                        "class_id": 0,
                        "x_center": 0.5,
                        "y_center": 0.5,
                        "width": 0.5,
                        "height": 0.5,
                    }
                ],
            }
        ],
    }


def test_false_negative_is_deterministic_pending_human_review(receipt):
    result = feedback_result(receipt)
    first = build_vision_feedback("project", "run", "dataset", receipt, result)
    assert build_vision_feedback("project", "run", "dataset", receipt, result) == first
    assert len(first) == 1
    item = first[0]
    assert re.fullmatch(r"vfeedback_[0-9a-f]{24}", item["feedback_id"])
    assert item["detail"]["fn"] == 1
    assert item["status"] == "PENDING_HUMAN_REVIEW"
    assert item["classification"] is None
    assert item["dataset_receipt_sha256"] == receipt["receipt_sha256"]
    for key in (
        "issue_closed",
        "label_truth_authority",
        "training_ingestion_allowed",
        "production_release_allowed",
    ):
        assert item[key] is False


def test_clear_validation_emits_no_candidate(receipt):
    assert (
        build_vision_feedback(
            "project", "run", "dataset", receipt, feedback_result(receipt, clear=True)
        )
        == []
    )


def test_missing_protocol_is_legacy_absence_not_zero_error_evidence(receipt):
    assert build_vision_feedback("project", "run", "dataset", receipt, {}) == []


def test_full_val_population_cannot_be_replaced_with_a_subset(receipt):
    result = feedback_result(receipt)
    result["validation_samples_detail"] = []
    result["validation_feedback_protocol"]["sample_count"] = 0
    with pytest.raises(ValueError, match="PROTOCOL_BINDING_INVALID"):
        build_vision_feedback("project", "run", "dataset", receipt, result)


def test_pool_response_policy_requires_new_version_and_gate_without_claiming_gate_pass(
    receipt, monkeypatch
):
    # Policy-only TEST_DOUBLE: no public PASS receipt or live pool is forged.
    service = object.__new__(LocalVisionModelService)
    identifier = "vfeedback_" + "1" * 24
    previous = {
        "dataset_receipt_sha256": "f" * 64,
        "dataset_receipt": receipt,
        "pool_binding": {
            "pool_id": "TEST_DOUBLE_pool",
            "version_id": "TEST_DOUBLE_v1",
            "task_id": "TEST_DOUBLE_gate1",
        },
    }
    feedback = {
        "receipt_sha256": "b" * 64,
        "status": "TRIAGED_FOR_REVIEW",
        "classification": "MODEL_ERROR",
        "dataset_receipt_sha256": "f" * 64,
        "dataset_id": "old",
    }
    current_receipt = copy.deepcopy(receipt)
    current_receipt["source_version"] = "TEST_DOUBLE_v2"
    current_receipt["receipt_sha256"] = "e" * 64
    current_receipt["samples"][0]["annotation_revision"] = 2
    current_receipt["samples"][0]["boxes"][0]["width"] = 0.4
    current_receipt["samples"][0]["label_sha256"] = "3" * 64
    current = {
        "dataset_receipt_sha256": "e" * 64,
        "dataset_receipt": current_receipt,
        "pool_binding": {
            "pool_id": "TEST_DOUBLE_pool",
            "version_id": "TEST_DOUBLE_v2",
            "task_id": "TEST_DOUBLE_gate2",
        },
    }
    request = SimpleNamespace(
        responds_to_feedback_ids=[identifier],
        expected_feedback_receipts={identifier: "b" * 64},
    )
    monkeypatch.setattr(
        service,
        "_read",
        lambda conn, project, key, kind: (
            feedback if kind == "feedback" else previous,
            {},
        ),
    )
    for bad in (
        None,
        {**current["pool_binding"], "version_id": "TEST_DOUBLE_v1"},
        {**current["pool_binding"], "task_id": "TEST_DOUBLE_gate1"},
    ):
        with pytest.raises(
            VisionModelError, match="FEEDBACK_REQUIRES_NEW_POOL_AND_GATE"
        ):
            service._feedback_inputs(
                None, "TEST_DOUBLE_project", request, {**current, "pool_binding": bad}
            )
    service._feedback_inputs(None, "TEST_DOUBLE_project", request, current)
