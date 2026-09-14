from __future__ import annotations

from copy import deepcopy

import pytest
from pydantic import ValidationError

from visiondata_gate.continual_learning import (
    ContinualRetentionEvaluationRequest,
    evaluate_continual_retention,
)


SHA_A = "a" * 64
SHA_B = "b" * 64
SHA_C = "c" * 64
SHA_D = "d" * 64
SHA_E = "e" * 64
SHA_F = "f" * 64


def retention_payload() -> dict:
    return {
        "request_key": "continual-retention-0001",
        "review_note": "Independently evaluate synthetic multi-object retention",
        "parent_model_id": "model_parent",
        "parent_model_sha256": SHA_A,
        "candidate_model_id": "model_candidate",
        "candidate_model_sha256": SHA_B,
        "evidence_scope": "SYNTHETIC_CONTRACT_FIXTURE",
        "retention_dataset_sha256": SHA_C,
        "retention_membership_sha256": SHA_D,
        "evaluator_sha256": SHA_E,
        "base_backbone_sha256": "9" * 64,
        "object_sequence": ["capsules", "pcb", "candle"],
        "policy": {
            "strategy": "REPLAY_DISTILLATION",
            "minimum_replay_samples_per_prior_object": 4,
            "require_frozen_backbone": True,
            "require_teacher_distillation": True,
            "metrics": [
                {
                    "metric_id": "image_auroc",
                    "direction": "HIGHER_IS_BETTER",
                    "max_average_forgetting": 0.03,
                    "max_worst_object_forgetting": 0.05,
                    "minimum_final_score": 0.80,
                },
                {
                    "metric_id": "normal_false_positive_rate",
                    "direction": "LOWER_IS_BETTER",
                    "max_average_forgetting": 0.02,
                    "max_worst_object_forgetting": 0.03,
                    "maximum_final_score": 0.15,
                },
            ],
        },
        "stages": [
            {
                "stage_index": 0,
                "trained_object_id": "capsules",
                "stage_model_sha256": SHA_A,
                "backbone_sha256": "9" * 64,
                "object_metrics": {
                    "capsules": {
                        "image_auroc": 0.90,
                        "normal_false_positive_rate": 0.08,
                    }
                },
                "replay_sample_counts": {},
                "replay_manifest_sha256": None,
                "teacher_model_sha256": None,
            },
            {
                "stage_index": 1,
                "trained_object_id": "pcb",
                "stage_model_sha256": SHA_F,
                "backbone_sha256": "9" * 64,
                "object_metrics": {
                    "capsules": {
                        "image_auroc": 0.89,
                        "normal_false_positive_rate": 0.09,
                    },
                    "pcb": {
                        "image_auroc": 0.86,
                        "normal_false_positive_rate": 0.10,
                    },
                },
                "replay_sample_counts": {"capsules": 4},
                "replay_manifest_sha256": "1" * 64,
                "teacher_model_sha256": SHA_A,
            },
            {
                "stage_index": 2,
                "trained_object_id": "candle",
                "stage_model_sha256": SHA_B,
                "backbone_sha256": "9" * 64,
                "object_metrics": {
                    "capsules": {
                        "image_auroc": 0.88,
                        "normal_false_positive_rate": 0.10,
                    },
                    "pcb": {
                        "image_auroc": 0.85,
                        "normal_false_positive_rate": 0.11,
                    },
                    "candle": {
                        "image_auroc": 0.87,
                        "normal_false_positive_rate": 0.09,
                    },
                },
                "replay_sample_counts": {"capsules": 4, "pcb": 4},
                "replay_manifest_sha256": "2" * 64,
                "teacher_model_sha256": SHA_F,
            },
        ],
        "operator_attests_independent_evaluation": True,
        "operator_attests_replay_buffer_authorized": True,
    }


def test_retention_gate_accepts_bounded_multi_object_forgetting() -> None:
    request = ContinualRetentionEvaluationRequest.model_validate(retention_payload())
    receipt = evaluate_continual_retention(
        project_id="project_alpha",
        evaluated_by="quality_engineer",
        request=request,
    )

    assert receipt["decision"] == "ELIGIBLE_FOR_SANDBOX_REVIEW"
    assert receipt["sandbox_promotion_eligible"] is True
    assert receipt["production_release_allowed"] is False
    assert receipt["industrial_acceptance"] == "HOLD"
    assert receipt["evaluated_object_count"] == 3
    assert receipt["prior_object_denominator"] == 2
    assert receipt["metrics"]["image_auroc"]["average_forgetting"] == pytest.approx(
        0.015
    )
    assert receipt["metrics"]["image_auroc"]["worst_forgetting"] == pytest.approx(
        0.02
    )
    assert receipt["metrics"]["normal_false_positive_rate"][
        "average_forgetting"
    ] == pytest.approx(0.015)
    assert len(receipt["policy_sha256"]) == 64
    assert len(receipt["retention_matrix_sha256"]) == 64
    assert len(receipt["receipt_sha256"]) == 64


def test_retention_gate_holds_when_one_old_object_is_forgotten() -> None:
    payload = retention_payload()
    payload["stages"][-1]["object_metrics"]["capsules"]["image_auroc"] = 0.70
    request = ContinualRetentionEvaluationRequest.model_validate(payload)

    receipt = evaluate_continual_retention(
        project_id="project_alpha",
        evaluated_by="quality_engineer",
        request=request,
    )

    assert receipt["decision"] == "HOLD_CATASTROPHIC_FORGETTING"
    assert receipt["sandbox_promotion_eligible"] is False
    assert receipt["production_release_allowed"] is False
    assert any(
        blocker["code"] == "WORST_OBJECT_FORGETTING_EXCEEDED"
        and blocker["object_id"] == "capsules"
        for blocker in receipt["blockers"]
    )


def test_retention_contract_rejects_missing_prior_object_measurement() -> None:
    payload = retention_payload()
    del payload["stages"][-1]["object_metrics"]["pcb"]

    with pytest.raises(ValidationError, match="seen object prefix"):
        ContinualRetentionEvaluationRequest.model_validate(payload)


def test_retention_contract_rejects_underfilled_replay_buffer() -> None:
    payload = deepcopy(retention_payload())
    payload["stages"][-1]["replay_sample_counts"]["pcb"] = 3

    with pytest.raises(ValidationError, match="replay sample minimum"):
        ContinualRetentionEvaluationRequest.model_validate(payload)


def test_retention_contract_rejects_broken_teacher_model_lineage() -> None:
    payload = retention_payload()
    payload["stages"][-1]["teacher_model_sha256"] = SHA_A

    with pytest.raises(ValidationError, match="teacher model lineage"):
        ContinualRetentionEvaluationRequest.model_validate(payload)


def test_retention_contract_rejects_non_integer_replay_count() -> None:
    payload = retention_payload()
    payload["stages"][-1]["replay_sample_counts"]["pcb"] = 4.0

    with pytest.raises(ValidationError):
        ContinualRetentionEvaluationRequest.model_validate(payload)


def test_retention_contract_rejects_backbone_drift() -> None:
    payload = retention_payload()
    payload["stages"][-1]["backbone_sha256"] = "8" * 64

    with pytest.raises(ValidationError, match="backbone must remain frozen"):
        ContinualRetentionEvaluationRequest.model_validate(payload)


def test_retention_contract_requires_replay_manifest_after_first_stage() -> None:
    payload = retention_payload()
    payload["stages"][-1]["replay_manifest_sha256"] = None

    with pytest.raises(ValidationError, match="replay manifest"):
        ContinualRetentionEvaluationRequest.model_validate(payload)
