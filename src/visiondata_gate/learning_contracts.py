"""Explicit local learning authority, independent from offline CANN handoffs."""

from typing import Literal
import re

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from .learning_engine import TrainingConfig
from .learning_evaluation import EvaluationPolicy

SHA = r"^[0-9a-f]{64}$"


class LearningRequest(BaseModel):
    model_config = ConfigDict(
        extra="forbid", str_strip_whitespace=True, allow_inf_nan=False
    )
    request_key: str = Field(pattern=r"^[A-Za-z0-9_-]{12,100}$")
    review_note: str = Field(min_length=8, max_length=2000)


class NormalMaskAttestation(BaseModel):
    model_config = ConfigDict(
        extra="forbid", str_strip_whitespace=True, allow_inf_nan=False
    )
    reviewer_name: str = Field(min_length=2, max_length=120)
    review_note: str = Field(min_length=8, max_length=2000)
    expected_asset_sha256: str = Field(pattern=SHA)
    expected_annotation_revision: int = Field(ge=0, strict=True)
    expected_annotation_sha256: str = Field(pattern=SHA)
    operator_attests_no_foreground: Literal[True]


class DatasetAuthorization(LearningRequest):
    expected_preflight_sha256: str = Field(pattern=SHA)
    groups: dict[str, str] = Field(min_length=1, max_length=64)
    operator_attests_training_authorized: Literal[True]
    normal_mask_attestations: dict[str, NormalMaskAttestation] = Field(
        default_factory=dict, max_length=64
    )

    @field_validator("groups")
    @classmethod
    def valid_groups(cls, value: dict[str, str]) -> dict[str, str]:
        if any(
            not key.strip() or not group.strip() or len(group) > 120
            for key, group in value.items()
        ):
            raise ValueError("Every sample needs a nonempty bounded collection group")
        return value


class CreateLearningCycle(DatasetAuthorization):
    training: TrainingConfig = Field(default_factory=TrainingConfig)
    evaluation: EvaluationPolicy = Field(default_factory=EvaluationPolicy)
    max_rounds: int = Field(default=3, ge=1, le=10, strict=True)
    max_total_epochs: int = Field(default=500, ge=1, le=2000, strict=True)
    max_total_wall_seconds: float = Field(default=120, gt=0, le=600)

    @model_validator(mode="after")
    def first_round_fits_budget(self):
        if (
            self.training.epochs > self.max_total_epochs
            or self.training.max_wall_seconds > self.max_total_wall_seconds
        ):
            raise ValueError("The cycle budget must admit at least the first round")
        return self


class RunLearningRound(DatasetAuthorization):
    task_id: str = Field(pattern=r"^[A-Za-z0-9_-]{1,120}$")
    expected_cycle_sha256: str = Field(pattern=SHA)
    responds_to_feedback_ids: list[str] = Field(default_factory=list, max_length=64)

    @field_validator("responds_to_feedback_ids")
    @classmethod
    def unique_feedback(cls, values):
        if len(set(values)) != len(values) or any(
            not re.fullmatch(r"feedback_[0-9a-f]{24}", value) for value in values
        ):
            raise ValueError("Feedback references must be explicit, unique owned IDs")
        return values


class CycleAction(LearningRequest):
    expected_cycle_sha256: str = Field(pattern=SHA)
    operator_attests_reviewed: Literal[True]


class ModelSelection(CycleAction):
    expected_run_sha256: str = Field(pattern=SHA)
    expected_continual_retention_receipt_sha256: str | None = Field(
        default=None, pattern=SHA
    )
    action: Literal[
        "APPROVE_SANDBOX",
        "APPROVE_SANDBOX_CONTINUAL",
        "REJECT",
    ]

    @model_validator(mode="after")
    def continual_approval_requires_one_retention_receipt(self):
        continual = self.action == "APPROVE_SANDBOX_CONTINUAL"
        supplied = self.expected_continual_retention_receipt_sha256 is not None
        if continual != supplied:
            raise ValueError(
                "continual sandbox approval requires exactly one retention receipt"
            )
        return self


class FeedbackReview(CycleAction):
    classification: Literal[
        "LABEL_ERROR", "HARD_SAMPLE", "DISTRIBUTION_SHIFT", "INSUFFICIENT_EVIDENCE"
    ]
    followup_task_id: str | None = Field(
        default=None, pattern=r"^[A-Za-z0-9_-]{1,120}$"
    )


class FeedbackFollowup(CycleAction):
    expected_run_sha256: str = Field(pattern=SHA)
    task_id: str = Field(pattern=r"^[A-Za-z0-9_-]{1,120}$")
    expected_preflight_sha256: str = Field(pattern=SHA)
    sample_ids: list[str] = Field(min_length=1, max_length=64)

    @field_validator("sample_ids")
    @classmethod
    def unique_members(cls, values):
        if len(set(values)) != len(values) or any(
            not value.strip() for value in values
        ):
            raise ValueError("Followup members must be nonempty and unique")
        return values


class RollbackModel(CycleAction):
    model_id: str = Field(pattern=r"^[A-Za-z0-9_-]{1,120}$")
