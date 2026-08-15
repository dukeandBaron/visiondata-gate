"""Strict, portable contracts shared by every VisionData Gate component."""

from __future__ import annotations

from enum import Enum
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator


class StrictModel(BaseModel):
    """Base model that rejects silent schema drift."""

    model_config = ConfigDict(extra="forbid")


class GateDecision(str, Enum):
    PASS = "PASS"
    QUARANTINE = "QUARANTINE"
    RECAPTURE = "RECAPTURE"
    DEFER = "DEFER"


class Severity(str, Enum):
    CRITICAL = "critical"
    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"


class EvidenceStatus(str, Enum):
    VERIFIED = "verified"
    SOURCE_BACKED = "source-backed"
    INFERRED = "inferred"
    UNSUPPORTED = "unsupported"


class RuleCheckResult(str, Enum):
    PASS = "PASS"
    FAIL = "FAIL"


class SampleRecord(StrictModel):
    sample_id: str = Field(min_length=1)
    relative_path: str = Field(min_length=1)
    split: Literal["train", "val", "test"]
    category: str = Field(min_length=1)
    view: str = Field(min_length=1)
    condition: str = Field(min_length=1)
    annotation_path: str | None = None
    source_sample_id: str | None = None

    @field_validator("relative_path", "annotation_path")
    @classmethod
    def portable_relative_path(cls, value: str | None) -> str | None:
        if value is None:
            return value
        normalized = value.replace("\\", "/")
        if normalized.startswith("/") or ":" in normalized.split("/")[0]:
            raise ValueError("paths in manifests must be relative")
        if ".." in normalized.split("/"):
            raise ValueError("path traversal is forbidden")
        return normalized


class BatchManifest(StrictModel):
    schema_version: Literal["1.0"] = "1.0"
    batch_id: str = Field(min_length=1)
    seed: int = Field(ge=0)
    samples: list[SampleRecord] = Field(min_length=1)

    @field_validator("samples")
    @classmethod
    def unique_sample_ids(cls, samples: list[SampleRecord]) -> list[SampleRecord]:
        ids = [sample.sample_id for sample in samples]
        if len(ids) != len(set(ids)):
            raise ValueError("sample_id values must be unique")
        return samples


class QualityThresholds(StrictModel):
    expected_width: int = Field(default=128, ge=16)
    expected_height: int = Field(default=128, ge=16)
    min_mean_luma: float = Field(default=35.0, ge=0, le=255)
    max_mean_luma: float = Field(default=225.0, ge=0, le=255)
    min_sharpness: float = Field(default=18.0, ge=0)
    max_mask_fraction: float = Field(default=0.65, gt=0, le=1)
    min_mask_fraction: float = Field(default=0.002, ge=0, lt=1)
    near_duplicate_hamming: int = Field(default=4, ge=0, le=64)


class CoverageContract(StrictModel):
    categories: list[str] = Field(min_length=1)
    views: list[str] = Field(min_length=1)
    conditions: list[str] = Field(min_length=1)
    min_per_cell: int = Field(default=1, ge=1)
    splits: list[Literal["train", "val", "test"]] = Field(
        default_factory=lambda: ["train"]
    )


class BatchContract(StrictModel):
    schema_version: Literal["1.0"] = "1.0"
    contract_id: str = "visiondata-image-demo-v1"
    intended_use: Literal["sandbox_experiment_training_pool"] = (
        "sandbox_experiment_training_pool"
    )
    required_splits: list[Literal["train", "val", "test"]] = Field(
        default_factory=lambda: ["train", "val", "test"]
    )
    annotations_required: bool = True
    thresholds: QualityThresholds = Field(default_factory=QualityThresholds)
    coverage: CoverageContract = Field(
        default_factory=lambda: CoverageContract(
            categories=["bearing", "gear"],
            views=["front", "side"],
            conditions=["bright", "dim"],
        )
    )
    policy_version: str = "gate-policy-1.0"


class Finding(StrictModel):
    finding_id: str = Field(min_length=1)
    code: str = Field(min_length=1)
    severity: Severity
    tool: str = Field(min_length=1)
    sample_ids: list[str] = Field(default_factory=list)
    summary: str = Field(min_length=1)
    evidence: dict[str, Any] = Field(default_factory=dict)
    evidence_status: EvidenceStatus = EvidenceStatus.VERIFIED
    recommended_action: str = Field(min_length=1)


class ToolTrace(StrictModel):
    sequence: int = Field(ge=1)
    tool: str = Field(min_length=1)
    status: Literal["ok", "error", "skipped"]
    input_sha256: str = Field(min_length=64, max_length=64)
    parameters: dict[str, Any] = Field(default_factory=dict)
    result_sha256: str = Field(min_length=64, max_length=64)
    finding_ids: list[str] = Field(default_factory=list)
    error: str | None = None
    contract_version: str = "1.0.0"
    contract_digest: str | None = Field(default=None, min_length=64, max_length=64)
    adapter: str = "local-deterministic"


class ToolContract(StrictModel):
    """Stable adapter contract for one allowlisted measurement tool.

    The contract is intentionally separate from implementation metadata.  A
    remote/MCP adapter may replace the implementation only after preserving
    these fields and replaying the same fixture.
    """

    name: str = Field(min_length=1)
    version: str = Field(min_length=1)
    input_schema: str = Field(min_length=1)
    output_schema: str = Field(min_length=1)
    permission_scope: str = Field(min_length=1)
    read_only: bool = True
    side_effect_level: Literal["L0_none", "L1_reserve", "L2_external", "L3_production"]
    idempotency: str = Field(min_length=1)
    max_retries: int = Field(default=0, ge=0, le=3)
    failure_policy: Literal["fail_closed", "defer", "quarantine"] = "fail_closed"
    audit_fields: list[str] = Field(min_length=1)
    mcp_migration_target: str = Field(min_length=1)
    migration_cost: Literal["low", "medium", "high"]


class RuleCheck(StrictModel):
    check_id: str = Field(min_length=1)
    status: RuleCheckResult
    detail: str = Field(min_length=1)
    related_refs: list[str] = Field(default_factory=list)


class AgentOpinion(StrictModel):
    role_id: str
    display_name: str
    focus: str
    evidence_refs: list[str] = Field(default_factory=list)
    claims: list[str] = Field(default_factory=list)
    challenge: str
    recommendation: GateDecision
    confidence_axes: dict[Literal["E", "T", "A", "M"], Literal["high", "medium", "low"]]
    limitations: list[str] = Field(default_factory=list)
    required_additional_evidence: list[str] = Field(default_factory=list)
    counterfactual_guard: str = "No counterfactual guard configured."


class CouncilTrace(StrictModel):
    backend: str
    shared_model_disclosure: str
    independent_opinions: list[AgentOpinion]
    cross_examination: list[str]
    unresolved_objections: list[str]


class WorkOrder(StrictModel):
    work_order_id: str
    action: Literal["RECAPTURE", "RELABEL", "REMOVE_OR_REPARTITION", "INVESTIGATE"]
    priority: Severity
    reason_codes: list[str]
    sample_ids: list[str] = Field(default_factory=list)
    replacement_requirements: dict[str, Any] = Field(default_factory=dict)
    status: Literal["open", "simulated_complete"] = "open"


class GateResult(StrictModel):
    schema_version: Literal["1.0"] = "1.0"
    run_id: str
    batch_id: str
    contract_id: str
    input_sha256: str = Field(min_length=64, max_length=64)
    policy_version: str
    decision: GateDecision
    decision_reason: str
    release_scope: Literal["sandbox_experiment_training_pool"] = (
        "sandbox_experiment_training_pool"
    )
    human_authority_required_before_production: Literal[True] = True
    metrics: dict[str, int | float | str]
    findings: list[Finding]
    tool_trace: list[ToolTrace]
    council_trace: CouncilTrace
    rule_checks: list[RuleCheck] = Field(default_factory=list)
    work_orders: list[WorkOrder]
    boundary_notice: str = (
        "PASS only means this batch satisfies the frozen demo data contract for a sandbox "
        "experiment pool; it is not product acceptance, model validation, data authorization, "
        "or a legal/safety certification."
    )


class TruthIssue(StrictModel):
    issue_id: str
    code: str
    severity: Severity
    sample_ids: list[str] = Field(default_factory=list)
    detectable_by: list[str] = Field(default_factory=list)


class CorruptionManifest(StrictModel):
    schema_version: Literal["1.0"] = "1.0"
    seed: int
    batch_id: str
    issues: list[TruthIssue]
    reserve_manifest: str


class EvaluationResult(StrictModel):
    schema_version: Literal["1.0"] = "1.0"
    batch_id: str
    truth_issue_count: int = Field(ge=0)
    predicted_issue_count: int = Field(ge=0)
    true_positive_count: int = Field(ge=0)
    false_positive_count: int = Field(ge=0)
    false_negative_count: int = Field(ge=0)
    precision: float = Field(ge=0, le=1)
    recall: float = Field(ge=0, le=1)
    f1: float = Field(ge=0, le=1)
    critical_bad_release_rate: float = Field(ge=0, le=1)
    false_quarantine_rate: float = Field(ge=0, le=1)
    work_order_recall: float = Field(ge=0, le=1)
    irrelevant_work_order_rate: float = Field(ge=0, le=1)
    post_repair_correct_pass: bool
    notes: list[str] = Field(default_factory=list)
