"""Deterministic continual-learning retention contracts and promotion gate.

This module evaluates already-produced multi-object metrics. It does not train a
model, infer missing measurements, or grant production authority.
"""

from __future__ import annotations

import hashlib
import re
from typing import Literal

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    StrictInt,
    field_validator,
    model_validator,
)

from .audit_envelope import canonical_jcs_bytes


SHA = r"^[0-9a-f]{64}$"
IDENTIFIER = r"^[A-Za-z0-9_.-]{1,120}$"


class RetentionMetricPolicy(BaseModel):
    model_config = ConfigDict(
        extra="forbid", str_strip_whitespace=True, allow_inf_nan=False
    )

    metric_id: str = Field(pattern=IDENTIFIER)
    direction: Literal["HIGHER_IS_BETTER", "LOWER_IS_BETTER"]
    max_average_forgetting: float = Field(ge=0)
    max_worst_object_forgetting: float = Field(ge=0)
    minimum_final_score: float | None = None
    maximum_final_score: float | None = None

    @model_validator(mode="after")
    def direction_has_one_absolute_gate(self):
        if self.direction == "HIGHER_IS_BETTER":
            if self.minimum_final_score is None or self.maximum_final_score is not None:
                raise ValueError(
                    "higher-is-better metrics require only minimum_final_score"
                )
        elif self.maximum_final_score is None or self.minimum_final_score is not None:
            raise ValueError(
                "lower-is-better metrics require only maximum_final_score"
            )
        return self


class ContinualRetentionPolicy(BaseModel):
    model_config = ConfigDict(
        extra="forbid", str_strip_whitespace=True, allow_inf_nan=False
    )

    strategy: Literal[
        "EPISODIC_TTT",
        "OBJECT_SCOPED_ADAPTER",
        "REPLAY_DISTILLATION",
    ]
    minimum_replay_samples_per_prior_object: int = Field(default=0, ge=0)
    require_frozen_backbone: bool = True
    require_teacher_distillation: bool = False
    metrics: list[RetentionMetricPolicy] = Field(min_length=1, max_length=32)

    @field_validator("metrics")
    @classmethod
    def unique_metric_ids(cls, values):
        identifiers = [item.metric_id for item in values]
        if len(identifiers) != len(set(identifiers)):
            raise ValueError("retention metric ids must be unique")
        return values

    @model_validator(mode="after")
    def persistent_update_requires_replay(self):
        if self.strategy == "REPLAY_DISTILLATION":
            if self.minimum_replay_samples_per_prior_object < 1:
                raise ValueError("persistent continual learning requires replay")
            if not self.require_teacher_distillation:
                raise ValueError("persistent continual learning requires a teacher")
        return self


class RetentionStageObservation(BaseModel):
    model_config = ConfigDict(
        extra="forbid", str_strip_whitespace=True, allow_inf_nan=False
    )

    stage_index: int = Field(ge=0, strict=True)
    trained_object_id: str = Field(pattern=IDENTIFIER)
    stage_model_sha256: str = Field(pattern=SHA)
    backbone_sha256: str = Field(pattern=SHA)
    object_metrics: dict[str, dict[str, float]] = Field(min_length=1, max_length=64)
    replay_sample_counts: dict[str, StrictInt] = Field(
        default_factory=dict, max_length=64
    )
    replay_manifest_sha256: str | None = Field(default=None, pattern=SHA)
    teacher_model_sha256: str | None = Field(default=None, pattern=SHA)

    @field_validator("object_metrics")
    @classmethod
    def valid_object_metrics(cls, value):
        if any(re.fullmatch(IDENTIFIER, identifier) is None for identifier in value):
            raise ValueError("object metric keys must be bounded identifiers")
        if any(not metrics for metrics in value.values()):
            raise ValueError("every object requires at least one metric")
        return value

    @field_validator("replay_sample_counts")
    @classmethod
    def valid_replay_counts(cls, value):
        if any(
            re.fullmatch(IDENTIFIER, identifier) is None
            or isinstance(count, bool)
            or count < 0
            for identifier, count in value.items()
        ):
            raise ValueError("replay counts must be non-negative bounded integers")
        return value


class ContinualRetentionEvaluationRequest(BaseModel):
    model_config = ConfigDict(
        extra="forbid", str_strip_whitespace=True, allow_inf_nan=False
    )

    request_key: str = Field(pattern=r"^[A-Za-z0-9_-]{12,100}$")
    review_note: str = Field(min_length=8, max_length=2000)
    parent_model_id: str = Field(pattern=IDENTIFIER)
    parent_model_sha256: str = Field(pattern=SHA)
    candidate_model_id: str = Field(pattern=IDENTIFIER)
    candidate_model_sha256: str = Field(pattern=SHA)
    evidence_scope: Literal[
        "SYNTHETIC_CONTRACT_FIXTURE",
        "PUBLIC_PROXY",
        "FACTORY_SHADOW",
    ]
    retention_dataset_sha256: str = Field(pattern=SHA)
    retention_membership_sha256: str = Field(pattern=SHA)
    evaluator_sha256: str = Field(pattern=SHA)
    base_backbone_sha256: str = Field(pattern=SHA)
    object_sequence: list[str] = Field(min_length=2, max_length=64)
    policy: ContinualRetentionPolicy
    stages: list[RetentionStageObservation] = Field(min_length=2, max_length=64)
    operator_attests_independent_evaluation: Literal[True]
    operator_attests_replay_buffer_authorized: Literal[True]

    @field_validator("object_sequence")
    @classmethod
    def valid_object_sequence(cls, values):
        if len(values) != len(set(values)) or any(
            re.fullmatch(IDENTIFIER, value) is None for value in values
        ):
            raise ValueError("object sequence must contain unique bounded identifiers")
        return values

    @model_validator(mode="after")
    def fixed_denominator_and_replay_contract(self):
        if self.parent_model_id == self.candidate_model_id:
            raise ValueError("candidate model must differ from parent model")
        if self.parent_model_sha256 == self.candidate_model_sha256:
            raise ValueError("candidate weights must differ from parent weights")
        if len(self.stages) != len(self.object_sequence):
            raise ValueError("one retention stage is required per object")

        metric_ids = {item.metric_id for item in self.policy.metrics}
        for index, stage in enumerate(self.stages):
            if stage.stage_index != index:
                raise ValueError("retention stage indices must be contiguous")
            if stage.trained_object_id != self.object_sequence[index]:
                raise ValueError("retention stages must follow object sequence")
            if index == 0 and stage.stage_model_sha256 != self.parent_model_sha256:
                raise ValueError("first retention stage must bind the parent model")
            if (
                index == len(self.stages) - 1
                and stage.stage_model_sha256 != self.candidate_model_sha256
            ):
                raise ValueError("final retention stage must bind the candidate model")
            if (
                self.policy.require_frozen_backbone
                and stage.backbone_sha256 != self.base_backbone_sha256
            ):
                raise ValueError("backbone must remain frozen across retention stages")
            expected_objects = set(self.object_sequence[: index + 1])
            if set(stage.object_metrics) != expected_objects:
                raise ValueError(
                    "every stage must measure the exact seen object prefix"
                )
            for metrics in stage.object_metrics.values():
                if set(metrics) != metric_ids:
                    raise ValueError("every object must report the fixed metric set")

            prior_objects = set(self.object_sequence[:index])
            if self.policy.strategy == "REPLAY_DISTILLATION":
                if set(stage.replay_sample_counts) != prior_objects:
                    raise ValueError("replay must cover the exact prior object set")
                if any(
                    count
                    < self.policy.minimum_replay_samples_per_prior_object
                    for count in stage.replay_sample_counts.values()
                ):
                    raise ValueError("replay sample minimum is not satisfied")
                if index == 0 and stage.replay_manifest_sha256 is not None:
                    raise ValueError("first stage cannot claim a replay manifest")
                if index > 0 and stage.replay_manifest_sha256 is None:
                    raise ValueError("replay manifest is required after the first stage")
            elif set(stage.replay_sample_counts) - prior_objects:
                raise ValueError("replay cannot reference unseen objects")

            if index == 0 and stage.teacher_model_sha256 is not None:
                raise ValueError("the first stage cannot claim a prior teacher")
            if (
                index > 0
                and self.policy.require_teacher_distillation
                and stage.teacher_model_sha256 is None
            ):
                raise ValueError("teacher evidence is required after the first stage")
            if (
                index > 0
                and stage.teacher_model_sha256 is not None
                and stage.teacher_model_sha256
                != self.stages[index - 1].stage_model_sha256
            ):
                raise ValueError("teacher model lineage must bind the prior stage")
        return self


def _sha(value: object) -> str:
    return hashlib.sha256(canonical_jcs_bytes(value)).hexdigest()


def _rounded(value: float) -> float:
    return round(float(value), 12)


def _forgetting(direction: str, history: list[float]) -> tuple[float, float, float]:
    final = history[-1]
    if direction == "HIGHER_IS_BETTER":
        best = max(history)
        forgetting = max(0.0, best - final)
        backward_transfer = final - history[0]
    else:
        best = min(history)
        forgetting = max(0.0, final - best)
        backward_transfer = history[0] - final
    return _rounded(best), _rounded(forgetting), _rounded(backward_transfer)


def evaluate_continual_retention(
    *,
    project_id: str,
    evaluated_by: str,
    request: ContinualRetentionEvaluationRequest,
) -> dict:
    """Evaluate a fixed multi-object matrix and produce a sealed gate receipt."""

    if re.fullmatch(IDENTIFIER, project_id) is None:
        raise ValueError("project_id must be a bounded identifier")
    if not evaluated_by or len(evaluated_by) > 120:
        raise ValueError("evaluated_by must be a bounded principal")

    metric_results: dict[str, dict] = {}
    blockers: list[dict] = []
    final_stage = request.stages[-1]
    prior_objects = request.object_sequence[:-1]

    for policy in request.policy.metrics:
        object_results: dict[str, dict] = {}
        prior_forgetting: list[float] = []
        prior_backward_transfer: list[float] = []
        for object_index, object_id in enumerate(request.object_sequence):
            history = [
                stage.object_metrics[object_id][policy.metric_id]
                for stage in request.stages[object_index:]
            ]
            best, forgetting, backward_transfer = _forgetting(
                policy.direction, history
            )
            final = _rounded(history[-1])
            object_results[object_id] = {
                "learned_stage_score": _rounded(history[0]),
                "best_observed_score": best,
                "final_score": final,
                "forgetting": forgetting,
                "backward_transfer": backward_transfer,
                "observation_count": len(history),
            }
            if object_id in prior_objects:
                prior_forgetting.append(forgetting)
                prior_backward_transfer.append(backward_transfer)

            if (
                policy.minimum_final_score is not None
                and final < policy.minimum_final_score
            ):
                blockers.append(
                    {
                        "code": "FINAL_SCORE_BELOW_MINIMUM",
                        "metric_id": policy.metric_id,
                        "object_id": object_id,
                        "observed": final,
                        "limit": policy.minimum_final_score,
                    }
                )
            if (
                policy.maximum_final_score is not None
                and final > policy.maximum_final_score
            ):
                blockers.append(
                    {
                        "code": "FINAL_SCORE_ABOVE_MAXIMUM",
                        "metric_id": policy.metric_id,
                        "object_id": object_id,
                        "observed": final,
                        "limit": policy.maximum_final_score,
                    }
                )

        average_forgetting = _rounded(
            sum(prior_forgetting) / len(prior_forgetting)
        )
        worst_forgetting = _rounded(max(prior_forgetting))
        worst_index = prior_forgetting.index(worst_forgetting)
        worst_object = prior_objects[worst_index]
        average_backward_transfer = _rounded(
            sum(prior_backward_transfer) / len(prior_backward_transfer)
        )
        if average_forgetting > policy.max_average_forgetting:
            blockers.append(
                {
                    "code": "AVERAGE_FORGETTING_EXCEEDED",
                    "metric_id": policy.metric_id,
                    "object_id": None,
                    "observed": average_forgetting,
                    "limit": policy.max_average_forgetting,
                }
            )
        if worst_forgetting > policy.max_worst_object_forgetting:
            blockers.append(
                {
                    "code": "WORST_OBJECT_FORGETTING_EXCEEDED",
                    "metric_id": policy.metric_id,
                    "object_id": worst_object,
                    "observed": worst_forgetting,
                    "limit": policy.max_worst_object_forgetting,
                }
            )
        metric_results[policy.metric_id] = {
            "direction": policy.direction,
            "prior_object_denominator": len(prior_objects),
            "average_forgetting": average_forgetting,
            "worst_forgetting": worst_forgetting,
            "worst_object_id": worst_object,
            "average_backward_transfer": average_backward_transfer,
            "objects": object_results,
        }

    eligible = not blockers
    request_json = request.model_dump(mode="json")
    stable = {
        "schema_version": "visiondata-gate.continual-retention-receipt.v1",
        "project_id": project_id,
        "evaluated_by": evaluated_by,
        "request_key": request.request_key,
        "review_note": request.review_note,
        "parent_model_id": request.parent_model_id,
        "parent_model_sha256": request.parent_model_sha256,
        "candidate_model_id": request.candidate_model_id,
        "candidate_model_sha256": request.candidate_model_sha256,
        "evidence_scope": request.evidence_scope,
        "retention_dataset_sha256": request.retention_dataset_sha256,
        "retention_membership_sha256": request.retention_membership_sha256,
        "evaluator_sha256": request.evaluator_sha256,
        "base_backbone_sha256": request.base_backbone_sha256,
        "object_sequence": request.object_sequence,
        "evaluated_object_count": len(request.object_sequence),
        "prior_object_denominator": len(prior_objects),
        "policy": request.policy.model_dump(mode="json"),
        "policy_sha256": _sha(request.policy.model_dump(mode="json")),
        "retention_matrix_sha256": _sha(
            [stage.model_dump(mode="json") for stage in request.stages]
        ),
        "stage_model_sha256s": [
            stage.stage_model_sha256 for stage in request.stages
        ],
        "replay_manifest_sha256s": [
            stage.replay_manifest_sha256 for stage in request.stages
        ],
        "request_sha256": _sha(request_json),
        "metrics": metric_results,
        "blockers": blockers,
        "decision": (
            "ELIGIBLE_FOR_SANDBOX_REVIEW"
            if eligible
            else "HOLD_CATASTROPHIC_FORGETTING"
        ),
        "sandbox_promotion_eligible": eligible,
        "industrial_acceptance": "HOLD",
        "production_release_allowed": False,
        "machine_write_permitted": False,
        "claim_boundary": (
            "The receipt evaluates the supplied fixed retention matrix. It does "
            "not prove that training occurred, validate factory performance, or "
            "grant production-release authority."
        ),
        "final_stage_trained_object_id": final_stage.trained_object_id,
    }
    return stable | {"receipt_sha256": _sha(stable)}


__all__ = [
    "ContinualRetentionEvaluationRequest",
    "ContinualRetentionPolicy",
    "RetentionMetricPolicy",
    "RetentionStageObservation",
    "evaluate_continual_retention",
]
