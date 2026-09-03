"""Bounded reviewer projection for industrial-validation evidence.

The project currently has three materially different evidence tracks:

* a current-environment RC5 VisA public-industrial proxy recomputation with
  programmatic governance truth;
* a historical Omni private *offline dataset* Gate/CAPA/child-run receipt;
* factory shadow metrics, which remain unmeasured without an independent QMS
  or dual-human adjudication manifest.

This module keeps those tracks separate and exposes a small, hash-sealed
projection.  It never reads private source images, never turns historical
receipts into a current re-run, and never grants production authority.
"""

from __future__ import annotations

import hashlib
import hmac
import json
from math import sqrt
from pathlib import Path, PurePosixPath
from typing import Any, Literal

from pydantic import Field, field_validator, model_validator

from .audit_envelope import canonical_jcs_bytes
from .product_models import ProductModel


SHA256_PATTERN = r"^[0-9a-f]{64}$"
PROJECTION_SCHEMA_VERSION = "visiondata-gate.private-industrial-validation-summary.v1"
PROJECTION_HASH_PROFILE = (
    "visiondata-gate.private-industrial-validation-projection-jcs-sha256.v1"
)
PROJECTION_FRAME_MAGIC = b"visiondata-gate.private-industrial-validation.v1\x00"
DYNAMIC_CAPABILITY_CLAIM = "CONTRACT_AWARE_BOUNDED_RECOVERY_NOT_WORKER_REPLANNING"
_SOURCE_PROJECT_ROOT = Path(__file__).resolve().parents[2]
VISA_COMPACT_RECEIPT_NAME = "visa_public_proxy_summary.v1.json"
DEFAULT_VISA_COMPACT_RECEIPT_PATH = (
    _SOURCE_PROJECT_ROOT / "benchmarks" / "visa-public-proxy-summary.json"
)
FROZEN_VISA_COMPACT_RECEIPT_CONTENT_SHA256 = (
    "9031fa5389da78c4ddf3148177eface4ef072b75984052426312c7601d3f260e"
)

EvidenceTrack = Literal[
    "PUBLIC_INDUSTRIAL_PROXY_WITH_PROGRAMMATIC_GOVERNANCE_TRUTH",
    "DATASET_OFFLINE_VALIDATION",
    "FACTORY_SHADOW_METRICS",
]
MetricStatus = Literal[
    "MEASURED",
    "NOT_MEASURED_PENDING_ADJUDICATION",
    "NOT_APPLICABLE",
]
ScenarioGroup = Literal[
    "NORMAL_NO_FAULT",
    "TRANSIENT_RECOVERABLE_FAULT",
    "PERSISTENT_FAULT_SAFETY_COST",
]
ExecutionStrategy = Literal[
    "FIXED_SINGLE_ATTEMPT",
    "FIXED_UNIFORM_BOUNDED_RETRY",
    "DYNAMIC_CONTRACT_AWARE_RETRY",
]


_OMNI_SOURCE_REPORT_FILE_SHA256 = (
    "c74975c2e0c98f55393721647d830cd43a10d69a928ab84f8b07be6a23275b95"
)
_OMNI_CAPA_RECEIPT_SHA256 = (
    "eaf897f91bb092c4dcb7a22a3ffb0dec0982217d4c084d01855ca8eac27b52b1"
)


def _domain_sha256(domain: str, value: Any) -> str:
    domain_bytes = domain.encode("utf-8")
    payload = canonical_jcs_bytes(value)
    framed = b"".join(
        (
            PROJECTION_FRAME_MAGIC,
            len(domain_bytes).to_bytes(2, "big"),
            domain_bytes,
            len(payload).to_bytes(8, "big"),
            payload,
        )
    )
    return hashlib.sha256(framed).hexdigest()


def _wilson_95(numerator: int, denominator: int) -> tuple[float, float]:
    if denominator <= 0:
        raise ValueError("Wilson interval requires a positive denominator")
    z = 1.959963984540054
    p = numerator / denominator
    z2 = z * z
    scale = 1 + z2 / denominator
    center = (p + z2 / (2 * denominator)) / scale
    margin = z * sqrt(p * (1 - p) / denominator + z2 / (4 * denominator**2)) / scale
    lower = max(0.0, center - margin)
    upper = min(1.0, center + margin)
    if abs(lower) < 1e-15:
        lower = 0.0
    if abs(1.0 - upper) < 1e-15:
        upper = 1.0
    return lower, upper


class PrivateIndustrialRateMetric(ProductModel):
    status: MetricStatus
    numerator: int | None = Field(default=None, ge=0)
    denominator: int | None = Field(default=None, ge=1)
    value: float | None = Field(default=None, ge=0.0, le=1.0)
    wilson_95_lower: float | None = Field(default=None, ge=0.0, le=1.0)
    wilson_95_upper: float | None = Field(default=None, ge=0.0, le=1.0)
    unit_of_analysis: str = Field(min_length=1, max_length=120)
    definition: str = Field(min_length=8, max_length=500)
    not_measured_reason_code: str | None = Field(default=None, min_length=4)

    @model_validator(mode="after")
    def validate_metric(self) -> PrivateIndustrialRateMetric:
        numeric = (
            self.numerator,
            self.denominator,
            self.value,
            self.wilson_95_lower,
            self.wilson_95_upper,
        )
        if self.status == "MEASURED":
            if any(item is None for item in numeric):
                raise ValueError("measured metric requires counts, value, and interval")
            assert self.numerator is not None
            assert self.denominator is not None
            assert self.value is not None
            assert self.wilson_95_lower is not None
            assert self.wilson_95_upper is not None
            if self.numerator > self.denominator:
                raise ValueError("metric numerator cannot exceed denominator")
            lower, upper = _wilson_95(self.numerator, self.denominator)
            if abs(self.value - self.numerator / self.denominator) > 1e-12:
                raise ValueError("metric value does not reconcile")
            if abs(self.wilson_95_lower - lower) > 1e-12:
                raise ValueError("metric lower interval does not reconcile")
            if abs(self.wilson_95_upper - upper) > 1e-12:
                raise ValueError("metric upper interval does not reconcile")
            if self.not_measured_reason_code is not None:
                raise ValueError("measured metric cannot carry a missing-data reason")
            return self
        if any(item is not None for item in numeric):
            raise ValueError("unmeasured metric numeric fields must remain null")
        if self.not_measured_reason_code is None:
            raise ValueError("unmeasured metric requires an explicit reason code")
        return self


def _measured_rate(
    numerator: int,
    denominator: int,
    *,
    unit: str,
    definition: str,
) -> PrivateIndustrialRateMetric:
    lower, upper = _wilson_95(numerator, denominator)
    return PrivateIndustrialRateMetric(
        status="MEASURED",
        numerator=numerator,
        denominator=denominator,
        value=numerator / denominator,
        wilson_95_lower=lower,
        wilson_95_upper=upper,
        unit_of_analysis=unit,
        definition=definition,
    )


def _unmeasured_rate(
    *,
    status: Literal[
        "NOT_MEASURED_PENDING_ADJUDICATION",
        "NOT_APPLICABLE",
    ],
    unit: str,
    definition: str,
    reason_code: str,
) -> PrivateIndustrialRateMetric:
    return PrivateIndustrialRateMetric(
        status=status,
        unit_of_analysis=unit,
        definition=definition,
        not_measured_reason_code=reason_code,
    )


class ArtifactIdentityBinding(ProductModel):
    status: Literal["MATCHED", "DRIFTED", "DRIFTED_2_OF_2", "UNAVAILABLE"]
    matched_count: int = Field(ge=0)
    total_count: int = Field(ge=1)
    drifted_count: int = Field(ge=0)
    missing_count: int = Field(ge=0)
    mismatched_artifacts: list[str] = Field(default_factory=list)
    missing_artifacts: list[str] = Field(default_factory=list)

    @field_validator("mismatched_artifacts", "missing_artifacts")
    @classmethod
    def validate_relative_names(cls, values: list[str]) -> list[str]:
        if values != sorted(set(values)):
            raise ValueError("identity artifact names must be sorted and unique")
        for value in values:
            path = PurePosixPath(value)
            if (
                not value
                or "\\" in value
                or path.is_absolute()
                or ".." in path.parts
                or ":" in value
            ):
                raise ValueError(
                    "identity artifact name must remain repository-relative"
                )
        return values

    @model_validator(mode="after")
    def validate_counts(self) -> ArtifactIdentityBinding:
        if self.matched_count + self.drifted_count + self.missing_count != (
            self.total_count
        ):
            raise ValueError("identity comparison counts do not reconcile")
        if self.drifted_count != len(self.mismatched_artifacts):
            raise ValueError("identity drift count does not reconcile")
        if self.missing_count != len(self.missing_artifacts):
            raise ValueError("identity missing count does not reconcile")
        if self.status == "MATCHED" and self.matched_count != self.total_count:
            raise ValueError("MATCHED identity must match every artifact")
        if self.status == "DRIFTED_2_OF_2" and not (
            self.total_count == 2
            and self.drifted_count == 2
            and self.missing_count == 0
        ):
            raise ValueError("DRIFTED_2_OF_2 identity has inconsistent counts")
        if self.status == "UNAVAILABLE" and self.missing_count == 0:
            raise ValueError("UNAVAILABLE identity requires missing artifacts")
        if self.status == "DRIFTED" and self.drifted_count == 0:
            raise ValueError("DRIFTED identity requires mismatched artifacts")
        return self


class VisaScenarioStrategyMetrics(ProductModel):
    execution_strategy: ExecutionStrategy
    correct_decision_rate: PrivateIndustrialRateMetric
    false_release_rate: PrivateIndustrialRateMetric
    false_block_rate: PrivateIndustrialRateMetric
    transient_recovery_rate: PrivateIndustrialRateMetric
    non_retryable_retry_rate: PrivateIndustrialRateMetric
    physical_tool_call_count: int = Field(ge=0)
    retry_count: int = Field(ge=0)


class VisaScenarioMetrics(ProductModel):
    scenario_group: ScenarioGroup
    fault_modes: list[
        Literal[
            "NONE",
            "TRANSIENT_TIMEOUT_ONCE",
            "PERMISSION_DENIED_PERSISTENT",
            "TOOL_RESPONSE_INTEGRITY_PERSISTENT",
        ]
    ]
    episode_denominator: int = Field(ge=1)
    release_allowed_denominator: int = Field(ge=1)
    block_required_denominator: int = Field(ge=1)
    strategies: list[VisaScenarioStrategyMetrics] = Field(min_length=3, max_length=3)

    @model_validator(mode="after")
    def validate_scenario(self) -> VisaScenarioMetrics:
        if self.episode_denominator != (
            self.release_allowed_denominator + self.block_required_denominator
        ):
            raise ValueError("scenario denominators do not reconcile")
        strategies = [item.execution_strategy for item in self.strategies]
        if strategies != [
            "FIXED_SINGLE_ATTEMPT",
            "FIXED_UNIFORM_BOUNDED_RETRY",
            "DYNAMIC_CONTRACT_AWARE_RETRY",
        ]:
            raise ValueError("scenario strategy order or set drifted")
        for item in self.strategies:
            expected = {
                "correct_decision_rate": self.episode_denominator,
                "false_release_rate": self.block_required_denominator,
                "false_block_rate": self.release_allowed_denominator,
            }
            for field_name, denominator in expected.items():
                metric = getattr(item, field_name)
                if metric.status != "MEASURED" or metric.denominator != denominator:
                    raise ValueError("scenario metric denominator drifted")
            if self.scenario_group == "TRANSIENT_RECOVERABLE_FAULT":
                if (
                    item.transient_recovery_rate.status != "MEASURED"
                    or item.transient_recovery_rate.denominator
                    != self.episode_denominator
                ):
                    raise ValueError("transient recovery denominator drifted")
            elif item.transient_recovery_rate.status != "NOT_APPLICABLE":
                raise ValueError("transient recovery leaked into another scenario")
            if self.scenario_group == "PERSISTENT_FAULT_SAFETY_COST":
                if (
                    item.non_retryable_retry_rate.status != "MEASURED"
                    or item.non_retryable_retry_rate.denominator
                    != self.episode_denominator
                ):
                    raise ValueError("persistent retry denominator drifted")
            elif item.non_retryable_retry_rate.status != "NOT_APPLICABLE":
                raise ValueError("persistent retry leaked into another scenario")
        return self


class CompactArtifactIdentity(ProductModel):
    artifact: str = Field(min_length=1, max_length=240)
    sha256: str = Field(pattern=SHA256_PATTERN)

    @field_validator("artifact")
    @classmethod
    def validate_artifact(cls, value: str) -> str:
        path = PurePosixPath(value)
        if "\\" in value or path.is_absolute() or ".." in path.parts or ":" in value:
            raise ValueError("compact receipt artifact must be repository-relative")
        return value


class CompactVisaStrategyCounts(ProductModel):
    execution_strategy: ExecutionStrategy
    correct_decision_count: int = Field(ge=0)
    false_release_count: int = Field(ge=0)
    false_block_count: int = Field(ge=0)
    transient_recovery_count: int | None = Field(default=None, ge=0)
    non_retryable_retry_count: int | None = Field(default=None, ge=0)
    physical_tool_call_count: int = Field(ge=0)
    retry_count: int = Field(ge=0)


class CompactVisaScenarioCounts(ProductModel):
    scenario_group: ScenarioGroup
    fault_modes: list[
        Literal[
            "NONE",
            "TRANSIENT_TIMEOUT_ONCE",
            "PERMISSION_DENIED_PERSISTENT",
            "TOOL_RESPONSE_INTEGRITY_PERSISTENT",
        ]
    ]
    episode_denominator: int = Field(ge=1)
    release_allowed_denominator: int = Field(ge=1)
    block_required_denominator: int = Field(ge=1)
    strategies: list[CompactVisaStrategyCounts] = Field(min_length=3, max_length=3)

    @model_validator(mode="after")
    def validate_counts(self) -> CompactVisaScenarioCounts:
        if self.episode_denominator != (
            self.release_allowed_denominator + self.block_required_denominator
        ):
            raise ValueError("compact scenario denominators do not reconcile")
        expected_strategies = [
            "FIXED_SINGLE_ATTEMPT",
            "FIXED_UNIFORM_BOUNDED_RETRY",
            "DYNAMIC_CONTRACT_AWARE_RETRY",
        ]
        if [item.execution_strategy for item in self.strategies] != expected_strategies:
            raise ValueError("compact scenario strategy order drifted")
        for item in self.strategies:
            if item.correct_decision_count > self.episode_denominator:
                raise ValueError("compact correct-decision count exceeds denominator")
            if item.false_release_count > self.block_required_denominator:
                raise ValueError("compact false-release count exceeds denominator")
            if item.false_block_count > self.release_allowed_denominator:
                raise ValueError("compact false-block count exceeds denominator")
            if self.scenario_group == "TRANSIENT_RECOVERABLE_FAULT":
                if item.transient_recovery_count is None:
                    raise ValueError("compact transient slice lacks recovery count")
                if item.transient_recovery_count > self.episode_denominator:
                    raise ValueError("compact transient recovery exceeds denominator")
            elif item.transient_recovery_count is not None:
                raise ValueError("compact transient count leaked into another slice")
            if self.scenario_group == "PERSISTENT_FAULT_SAFETY_COST":
                if item.non_retryable_retry_count is None:
                    raise ValueError("compact persistent slice lacks retry count")
                if item.non_retryable_retry_count > self.episode_denominator:
                    raise ValueError("compact persistent retry exceeds denominator")
            elif item.non_retryable_retry_count is not None:
                raise ValueError("compact persistent count leaked into another slice")
        return self


class VisaPublicProxyCompactReceipt(ProductModel):
    schema_version: Literal["visiondata-gate.visa-public-proxy-compact-evidence.v1"] = (
        "visiondata-gate.visa-public-proxy-compact-evidence.v1"
    )
    source_run_label: Literal["formal_300x300_rc5_20260903"] = (
        "formal_300x300_rc5_20260903"
    )
    evidence_track: Literal[
        "PUBLIC_INDUSTRIAL_PROXY_WITH_PROGRAMMATIC_GOVERNANCE_TRUTH"
    ] = "PUBLIC_INDUSTRIAL_PROXY_WITH_PROGRAMMATIC_GOVERNANCE_TRUTH"
    evidence_origin: Literal["CURRENT_ENVIRONMENT_RECOMPUTED_RECEIPT"] = (
        "CURRENT_ENVIRONMENT_RECOMPUTED_RECEIPT"
    )
    recomputable_now: Literal[True] = True
    dataset_id: Literal["VisA"] = "VisA"
    benchmark_id: Literal["Public-GovernanceBench-v1-runtime-recovery-v2"] = (
        "Public-GovernanceBench-v1-runtime-recovery-v2"
    )
    benchmark_file_sha256: str = Field(pattern=SHA256_PATTERN)
    benchmark_report_sha256: str = Field(pattern=SHA256_PATTERN)
    implementation_receipt_file_sha256: str = Field(pattern=SHA256_PATTERN)
    implementation_receipt_sha256: str = Field(pattern=SHA256_PATTERN)
    dataset_identity_sha256: str = Field(pattern=SHA256_PATTERN)
    source_binding_sha256: str = Field(pattern=SHA256_PATTERN)
    programmatic_manifest_sha256: str = Field(pattern=SHA256_PATTERN)
    truth_receipt_sha256: str = Field(pattern=SHA256_PATTERN)
    core_components: list[CompactArtifactIdentity] = Field(min_length=17, max_length=17)
    project_environment: list[CompactArtifactIdentity] = Field(
        min_length=2, max_length=2
    )
    dynamic_capability_claim: Literal[
        "CONTRACT_AWARE_BOUNDED_RECOVERY_NOT_WORKER_REPLANNING"
    ] = DYNAMIC_CAPABILITY_CLAIM
    scenario_groups: list[CompactVisaScenarioCounts] = Field(min_length=3, max_length=3)
    configured_intervention_distribution_is_production_prevalence: Literal[False] = (
        False
    )
    actual_factory_truth: Literal[False] = False
    production_release_allowed: Literal[False] = False
    claim_boundary: str = Field(min_length=8, max_length=1000)
    receipt_sha256: str = Field(pattern=SHA256_PATTERN)

    @model_validator(mode="after")
    def validate_receipt(self) -> VisaPublicProxyCompactReceipt:
        core_names = [item.artifact for item in self.core_components]
        environment_names = [item.artifact for item in self.project_environment]
        if len(core_names) != len(set(core_names)):
            raise ValueError("compact receipt core artifacts must be unique")
        if environment_names != ["pyproject.toml", "uv.lock"]:
            raise ValueError("compact receipt environment artifact set drifted")
        expected_groups = [
            "NORMAL_NO_FAULT",
            "TRANSIENT_RECOVERABLE_FAULT",
            "PERSISTENT_FAULT_SAFETY_COST",
        ]
        if [item.scenario_group for item in self.scenario_groups] != expected_groups:
            raise ValueError("compact receipt scenario groups drifted")
        stable = self.model_dump(mode="json", exclude={"receipt_sha256"})
        if not hmac.compare_digest(
            self.receipt_sha256,
            _domain_sha256("visa-compact-receipt", stable),
        ):
            raise ValueError("compact VisA receipt digest mismatch")
        return self


class VisaPublicProxyProjection(ProductModel):
    evidence_track: Literal[
        "PUBLIC_INDUSTRIAL_PROXY_WITH_PROGRAMMATIC_GOVERNANCE_TRUTH"
    ] = "PUBLIC_INDUSTRIAL_PROXY_WITH_PROGRAMMATIC_GOVERNANCE_TRUTH"
    evidence_origin: Literal["CURRENT_ENVIRONMENT_RECOMPUTED_RECEIPT"] = (
        "CURRENT_ENVIRONMENT_RECOMPUTED_RECEIPT"
    )
    recomputable_now: Literal[True] = True
    status: Literal["VERIFIED_CURRENT_ENVIRONMENT_RECOMPUTED"] = (
        "VERIFIED_CURRENT_ENVIRONMENT_RECOMPUTED"
    )
    dataset_id: Literal["VisA"] = "VisA"
    benchmark_id: Literal["Public-GovernanceBench-v1-runtime-recovery-v2"] = (
        "Public-GovernanceBench-v1-runtime-recovery-v2"
    )
    compact_receipt_artifact_name: Literal["visa_public_proxy_summary.v1.json"] = (
        "visa_public_proxy_summary.v1.json"
    )
    compact_receipt_file_sha256: str = Field(pattern=SHA256_PATTERN)
    compact_receipt_sha256: str = Field(pattern=SHA256_PATTERN)
    benchmark_file_sha256: str = Field(pattern=SHA256_PATTERN)
    benchmark_report_sha256: str = Field(pattern=SHA256_PATTERN)
    implementation_receipt_file_sha256: str = Field(pattern=SHA256_PATTERN)
    implementation_receipt_sha256: str = Field(pattern=SHA256_PATTERN)
    dataset_identity_sha256: str = Field(pattern=SHA256_PATTERN)
    source_binding_sha256: str = Field(pattern=SHA256_PATTERN)
    programmatic_manifest_sha256: str = Field(pattern=SHA256_PATTERN)
    truth_receipt_sha256: str = Field(pattern=SHA256_PATTERN)
    core_component_binding: ArtifactIdentityBinding
    project_environment_binding: ArtifactIdentityBinding
    dynamic_capability_claim: Literal[
        "CONTRACT_AWARE_BOUNDED_RECOVERY_NOT_WORKER_REPLANNING"
    ] = DYNAMIC_CAPABILITY_CLAIM
    scenario_groups: list[VisaScenarioMetrics] = Field(min_length=3, max_length=3)
    scenario_groups_sha256: str = Field(pattern=SHA256_PATTERN)
    configured_intervention_distribution_is_production_prevalence: Literal[False] = (
        False
    )
    actual_factory_truth: Literal[False] = False
    production_release_allowed: Literal[False] = False
    claim_boundary: str = Field(min_length=8, max_length=1000)

    @model_validator(mode="after")
    def validate_groups(self) -> VisaPublicProxyProjection:
        observed = [item.scenario_group for item in self.scenario_groups]
        expected = [
            "NORMAL_NO_FAULT",
            "TRANSIENT_RECOVERABLE_FAULT",
            "PERSISTENT_FAULT_SAFETY_COST",
        ]
        if observed != expected:
            raise ValueError("VisA scenario groups must remain separate and ordered")
        digest = _domain_sha256("visa-scenario-groups", self.scenario_groups)
        if not hmac.compare_digest(digest, self.scenario_groups_sha256):
            raise ValueError("VisA scenario-group digest mismatch")
        return self


class OmniOfflineValidationProjection(ProductModel):
    evidence_track: Literal["DATASET_OFFLINE_VALIDATION"] = "DATASET_OFFLINE_VALIDATION"
    evidence_origin: Literal["HISTORICAL_FROZEN_RECEIPT"] = "HISTORICAL_FROZEN_RECEIPT"
    recomputable_now: Literal[False] = False
    status: Literal["VERIFIED_HISTORICAL_ONLY"] = "VERIFIED_HISTORICAL_ONLY"
    source_artifact_name: Literal["OMNI_CAPA_RC3_RESULT.md"] = "OMNI_CAPA_RC3_RESULT.md"
    source_report_file_sha256: str = Field(pattern=SHA256_PATTERN)
    capa_receipt_sha256: str = Field(pattern=SHA256_PATTERN)
    original_receipts_available_now: Literal[False] = False
    source_profile_image_count: int = Field(ge=0)
    source_profile_mask_count: int = Field(ge=0)
    fixed_gate_sample_count: int = Field(ge=0)
    parent_finding_count: int = Field(ge=0)
    child_finding_count: int = Field(ge=0)
    finding_count_delta: int
    verified_closed_responsibility_count: int = Field(ge=0)
    open_responsibility_count: int = Field(ge=0)
    verified_remediation_pass_rate: PrivateIndustrialRateMetric
    factory_shadow_equivalent: Literal[False] = False
    production_release_allowed: Literal[False] = False
    not_recomputable_reason_code: Literal[
        "ORIGINAL_SOURCE_BYTES_AND_RECEIPTS_NOT_PRESENT_IN_CURRENT_AUTHORITY_TREE"
    ] = "ORIGINAL_SOURCE_BYTES_AND_RECEIPTS_NOT_PRESENT_IN_CURRENT_AUTHORITY_TREE"
    claim_boundary: str = Field(min_length=8, max_length=1000)

    @model_validator(mode="after")
    def validate_historical_counts(self) -> OmniOfflineValidationProjection:
        if self.finding_count_delta != (
            self.child_finding_count - self.parent_finding_count
        ):
            raise ValueError("Omni finding delta does not reconcile")
        if (
            self.verified_remediation_pass_rate.status != "MEASURED"
            or self.verified_remediation_pass_rate.numerator != 0
            or self.verified_remediation_pass_rate.denominator != 1
        ):
            raise ValueError("Omni remediation rate must remain the frozen 0/1")
        return self


class FactoryShadowMetricsProjection(ProductModel):
    evidence_track: Literal["FACTORY_SHADOW_METRICS"] = "FACTORY_SHADOW_METRICS"
    evidence_origin: Literal["NO_INDEPENDENT_ADJUDICATION_RECEIPT"] = (
        "NO_INDEPENDENT_ADJUDICATION_RECEIPT"
    )
    recomputable_now: Literal[False] = False
    status: Literal["NOT_MEASURED_PENDING_ADJUDICATION"] = (
        "NOT_MEASURED_PENDING_ADJUDICATION"
    )
    independent_adjudication_manifest_sha256: None = None
    customer_shadow_execution_receipt_sha256: None = None
    false_release_rate: PrivateIndustrialRateMetric
    false_block_rate: PrivateIndustrialRateMetric
    remediation_pass_rate: PrivateIndustrialRateMetric
    production_release_allowed: Literal[False] = False
    claim_boundary: str = Field(min_length=8, max_length=1000)

    @model_validator(mode="after")
    def validate_unmeasured_metrics(self) -> FactoryShadowMetricsProjection:
        for metric in (
            self.false_release_rate,
            self.false_block_rate,
            self.remediation_pass_rate,
        ):
            if metric.status != "NOT_MEASURED_PENDING_ADJUDICATION":
                raise ValueError(
                    "factory shadow metric cannot be measured without truth"
                )
            if metric.not_measured_reason_code != (
                "INDEPENDENT_ADJUDICATION_MANIFEST_MISSING"
            ):
                raise ValueError("factory shadow missing-data reason drifted")
        return self


class IndustrialValidationScope(ProductModel):
    scope_kind: Literal["GLOBAL_REVIEW", "WORKSPACE_REFERENCE", "PROJECT_REFERENCE"]
    workspace_id: str | None = None
    project_id: str | None = None
    association_status: Literal[
        "GLOBAL_FROZEN_REFERENCE",
        "REFERENCE_ONLY_NOT_WORKSPACE_DERIVED",
        "REFERENCE_ONLY_NOT_PROJECT_DERIVED",
    ]
    read_only: Literal[True] = True

    @model_validator(mode="after")
    def validate_scope(self) -> IndustrialValidationScope:
        if self.scope_kind == "GLOBAL_REVIEW":
            if self.workspace_id is not None or self.project_id is not None:
                raise ValueError("global review scope cannot carry tenant identifiers")
            if self.association_status != "GLOBAL_FROZEN_REFERENCE":
                raise ValueError("global review association drifted")
        elif self.scope_kind == "WORKSPACE_REFERENCE":
            if self.workspace_id is None or self.project_id is not None:
                raise ValueError("workspace scope binding is incomplete")
            if self.association_status != "REFERENCE_ONLY_NOT_WORKSPACE_DERIVED":
                raise ValueError("workspace association drifted")
        else:
            if self.workspace_id is None or self.project_id is None:
                raise ValueError("project scope binding is incomplete")
            if self.association_status != "REFERENCE_ONLY_NOT_PROJECT_DERIVED":
                raise ValueError("project association drifted")
        return self


class PrivateIndustrialValidationSummary(ProductModel):
    schema_version: Literal[
        "visiondata-gate.private-industrial-validation-summary.v1"
    ] = PROJECTION_SCHEMA_VERSION
    status: Literal["HOLD"] = "HOLD"
    availability: Literal[
        "CURRENT_PUBLIC_PROXY_WITH_HISTORICAL_OFFLINE_EVIDENCE",
        "PUBLIC_PROXY_UNAVAILABLE_WITH_HISTORICAL_OFFLINE_EVIDENCE",
    ]
    verification_status: Literal[
        "VERIFIED_BOUNDED_PROJECTION",
        "FAILED_CLOSED",
    ]
    failure_codes: list[str]
    scope: IndustrialValidationScope
    visa_public_proxy: VisaPublicProxyProjection | None
    omni_offline_validation: OmniOfflineValidationProjection
    factory_shadow_metrics: FactoryShadowMetricsProjection
    production_release_allowed: Literal[False] = False
    machine_write_permitted: Literal[False] = False
    read_only: Literal[True] = True
    claim_boundary: str = Field(min_length=8, max_length=1600)
    projection_hash_profile: Literal[
        "visiondata-gate.private-industrial-validation-projection-jcs-sha256.v1"
    ] = PROJECTION_HASH_PROFILE
    projection_sha256: str = Field(pattern=SHA256_PATTERN)

    @field_validator("failure_codes")
    @classmethod
    def validate_failure_codes(cls, values: list[str]) -> list[str]:
        if values != sorted(set(values)):
            raise ValueError("industrial validation failure codes must be sorted")
        return values


def global_industrial_validation_scope() -> IndustrialValidationScope:
    return IndustrialValidationScope(
        scope_kind="GLOBAL_REVIEW",
        association_status="GLOBAL_FROZEN_REFERENCE",
    )


def scoped_industrial_validation_scope(
    *, workspace_id: str, project_id: str | None = None
) -> IndustrialValidationScope:
    if project_id is None:
        return IndustrialValidationScope(
            scope_kind="WORKSPACE_REFERENCE",
            workspace_id=workspace_id,
            association_status="REFERENCE_ONLY_NOT_WORKSPACE_DERIVED",
        )
    return IndustrialValidationScope(
        scope_kind="PROJECT_REFERENCE",
        workspace_id=workspace_id,
        project_id=project_id,
        association_status="REFERENCE_ONLY_NOT_PROJECT_DERIVED",
    )


def _identity_binding(
    project_root: Path,
    expected: dict[str, str],
) -> ArtifactIdentityBinding:
    mismatched: list[str] = []
    missing: list[str] = []
    matched = 0
    root = project_root.expanduser().resolve()
    for relative_name, expected_sha256 in expected.items():
        candidate = (root / Path(*PurePosixPath(relative_name).parts)).resolve()
        try:
            candidate.relative_to(root)
        except ValueError as error:  # pragma: no cover - constants are frozen.
            raise ValueError("identity artifact escaped the project root") from error
        if not candidate.is_file():
            missing.append(relative_name)
            continue
        current_sha256 = hashlib.sha256(candidate.read_bytes()).hexdigest()
        if hmac.compare_digest(current_sha256, expected_sha256):
            matched += 1
        else:
            mismatched.append(relative_name)
    total = len(expected)
    if missing:
        status: Literal["MATCHED", "DRIFTED", "DRIFTED_2_OF_2", "UNAVAILABLE"] = (
            "UNAVAILABLE"
        )
    elif matched == total:
        status = "MATCHED"
    elif total == 2 and len(mismatched) == 2:
        status = "DRIFTED_2_OF_2"
    else:
        status = "DRIFTED"
    return ArtifactIdentityBinding(
        status=status,
        matched_count=matched,
        total_count=total,
        drifted_count=len(mismatched),
        missing_count=len(missing),
        mismatched_artifacts=sorted(mismatched),
        missing_artifacts=sorted(missing),
    )


def _scenario_strategy(
    *,
    execution_strategy: ExecutionStrategy,
    episode_count: int,
    release_count: int,
    block_count: int,
    correct_count: int,
    false_release_count: int,
    false_block_count: int,
    tool_calls: int,
    retry_count: int,
    transient_recovery_count: int | None,
    non_retryable_retry_count: int | None,
) -> VisaScenarioStrategyMetrics:
    transient = (
        _measured_rate(
            transient_recovery_count,
            episode_count,
            unit="transient_fault_episode",
            definition="recovered transient-fault episodes / transient episodes",
        )
        if transient_recovery_count is not None
        else _unmeasured_rate(
            status="NOT_APPLICABLE",
            unit="transient_fault_episode",
            definition="transient recovery applies only to the transient fault slice",
            reason_code="SCENARIO_GROUP_NOT_TRANSIENT",
        )
    )
    persistent = (
        _measured_rate(
            non_retryable_retry_count,
            episode_count,
            unit="persistent_fault_episode",
            definition="unproductive retries / persistent non-retryable fault episodes",
        )
        if non_retryable_retry_count is not None
        else _unmeasured_rate(
            status="NOT_APPLICABLE",
            unit="persistent_fault_episode",
            definition="non-retryable retry cost applies only to persistent faults",
            reason_code="SCENARIO_GROUP_NOT_PERSISTENT",
        )
    )
    return VisaScenarioStrategyMetrics(
        execution_strategy=execution_strategy,
        correct_decision_rate=_measured_rate(
            correct_count,
            episode_count,
            unit="programmatic_governance_episode",
            definition="correct dispositions / episodes in this configured slice",
        ),
        false_release_rate=_measured_rate(
            false_release_count,
            block_count,
            unit="programmatic_block_required_episode",
            definition="released BLOCK_REQUIRED proxy episodes / BLOCK_REQUIRED proxy episodes",
        ),
        false_block_rate=_measured_rate(
            false_block_count,
            release_count,
            unit="programmatic_release_allowed_episode",
            definition="non-released RELEASE_ALLOWED proxy episodes / RELEASE_ALLOWED proxy episodes",
        ),
        transient_recovery_rate=transient,
        non_retryable_retry_rate=persistent,
        physical_tool_call_count=tool_calls,
        retry_count=retry_count,
    )


def _visa_scenario_groups(
    rows: list[CompactVisaScenarioCounts],
) -> list[VisaScenarioMetrics]:
    groups: list[VisaScenarioMetrics] = []
    for row in rows:
        strategies = [
            _scenario_strategy(
                execution_strategy=strategy.execution_strategy,
                episode_count=row.episode_denominator,
                release_count=row.release_allowed_denominator,
                block_count=row.block_required_denominator,
                correct_count=strategy.correct_decision_count,
                false_release_count=strategy.false_release_count,
                false_block_count=strategy.false_block_count,
                tool_calls=strategy.physical_tool_call_count,
                retry_count=strategy.retry_count,
                transient_recovery_count=strategy.transient_recovery_count,
                non_retryable_retry_count=strategy.non_retryable_retry_count,
            )
            for strategy in row.strategies
        ]
        groups.append(
            VisaScenarioMetrics(
                scenario_group=row.scenario_group,
                fault_modes=row.fault_modes,
                episode_denominator=row.episode_denominator,
                release_allowed_denominator=row.release_allowed_denominator,
                block_required_denominator=row.block_required_denominator,
                strategies=strategies,
            )
        )
    return groups


def load_visa_public_proxy_compact_receipt(
    path: str | Path,
    *,
    expected_content_sha256: str,
) -> tuple[VisaPublicProxyCompactReceipt, str]:
    source = Path(path).expanduser().resolve(strict=True)
    if not source.is_file():
        raise ValueError("compact VisA receipt is not a regular file")
    raw = source.read_bytes()
    content_sha256 = hashlib.sha256(raw).hexdigest()
    if not hmac.compare_digest(content_sha256, expected_content_sha256):
        raise ValueError("compact VisA receipt content SHA-256 mismatch")
    try:
        decoded = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise ValueError("compact VisA receipt is not valid UTF-8 JSON") from error
    receipt = VisaPublicProxyCompactReceipt.model_validate(decoded)
    return receipt, content_sha256


def build_private_industrial_validation_summary(
    *,
    project_root: str | Path,
    scope: IndustrialValidationScope,
    visa_receipt: VisaPublicProxyCompactReceipt | None,
    visa_receipt_file_sha256: str | None = None,
    visa_failure_code: str | None = None,
) -> PrivateIndustrialValidationSummary:
    """Build a host-path-free projection from sealed facts and current repo bytes."""

    root = Path(project_root).expanduser().resolve()
    current_binding_verified = False
    if visa_receipt is None:
        if visa_failure_code is None:
            raise ValueError("missing VisA receipt requires a failure code")
        visa = None
        core_binding = None
        environment_binding = None
    else:
        if visa_failure_code is not None or visa_receipt_file_sha256 is None:
            raise ValueError("verified VisA receipt has inconsistent load state")
        core_expected = {
            item.artifact: item.sha256 for item in visa_receipt.core_components
        }
        environment_expected = {
            item.artifact: item.sha256 for item in visa_receipt.project_environment
        }
        core_binding = _identity_binding(root, core_expected)
        environment_binding = _identity_binding(root, environment_expected)
        current_binding_verified = (
            core_binding.status == "MATCHED" and environment_binding.status == "MATCHED"
        )
        scenario_groups = _visa_scenario_groups(visa_receipt.scenario_groups)
        visa = VisaPublicProxyProjection(
            compact_receipt_file_sha256=visa_receipt_file_sha256,
            compact_receipt_sha256=visa_receipt.receipt_sha256,
            benchmark_file_sha256=visa_receipt.benchmark_file_sha256,
            benchmark_report_sha256=visa_receipt.benchmark_report_sha256,
            implementation_receipt_file_sha256=(
                visa_receipt.implementation_receipt_file_sha256
            ),
            implementation_receipt_sha256=(visa_receipt.implementation_receipt_sha256),
            dataset_identity_sha256=visa_receipt.dataset_identity_sha256,
            source_binding_sha256=visa_receipt.source_binding_sha256,
            programmatic_manifest_sha256=(visa_receipt.programmatic_manifest_sha256),
            truth_receipt_sha256=visa_receipt.truth_receipt_sha256,
            core_component_binding=core_binding,
            project_environment_binding=environment_binding,
            scenario_groups=scenario_groups,
            scenario_groups_sha256=_domain_sha256(
                "visa-scenario-groups", scenario_groups
            ),
            claim_boundary=visa_receipt.claim_boundary,
        )
    omni = OmniOfflineValidationProjection(
        source_report_file_sha256=_OMNI_SOURCE_REPORT_FILE_SHA256,
        capa_receipt_sha256=_OMNI_CAPA_RECEIPT_SHA256,
        source_profile_image_count=4464,
        source_profile_mask_count=1439,
        fixed_gate_sample_count=180,
        parent_finding_count=49,
        child_finding_count=33,
        finding_count_delta=-16,
        verified_closed_responsibility_count=6,
        open_responsibility_count=43,
        verified_remediation_pass_rate=_measured_rate(
            0,
            1,
            unit="same_contract_remediation_recheck",
            definition="verified PASS child rechecks / completed child rechecks",
        ),
        claim_boundary=(
            "Historical Omni evidence is a private offline dataset Gate/CAPA/child "
            "workflow projection. Finding delta and responsibility closure use "
            "different grains. Original source bytes and receipts are absent from "
            "the current authority tree, so this is not a current recomputation, "
            "factory shadow test, recovery success, or production release."
        ),
    )
    missing_reason = "INDEPENDENT_ADJUDICATION_MANIFEST_MISSING"
    factory = FactoryShadowMetricsProjection(
        false_release_rate=_unmeasured_rate(
            status="NOT_MEASURED_PENDING_ADJUDICATION",
            unit="factory_governance_case",
            definition="released adjudicated BLOCK_REQUIRED factory cases / all such cases",
            reason_code=missing_reason,
        ),
        false_block_rate=_unmeasured_rate(
            status="NOT_MEASURED_PENDING_ADJUDICATION",
            unit="factory_governance_case",
            definition="blocked adjudicated RELEASE_ALLOWED factory cases / all such cases",
            reason_code=missing_reason,
        ),
        remediation_pass_rate=_unmeasured_rate(
            status="NOT_MEASURED_PENDING_ADJUDICATION",
            unit="factory_same_contract_recheck",
            definition="factory remediation rechecks passing independent adjudication / all completed rechecks",
            reason_code=missing_reason,
        ),
        claim_boundary=(
            "Factory false-release, false-block, and remediation-pass rates remain "
            "unmeasured until independently adjudicated per-case truth and an "
            "authorized customer shadow execution receipt are SHA-bound."
        ),
    )
    failure_codes = [
        "FACTORY_SHADOW_ADJUDICATION_MANIFEST_MISSING",
        "OMNI_HISTORICAL_SOURCE_NOT_RECOMPUTABLE",
    ]
    if visa_receipt is None:
        assert visa_failure_code is not None
        failure_codes.append(visa_failure_code)
    else:
        assert core_binding is not None
        assert environment_binding is not None
        if core_binding.status != "MATCHED":
            failure_codes.append("VISA_CURRENT_CORE_COMPONENT_BINDING_NOT_MATCHED")
        if environment_binding.status == "DRIFTED_2_OF_2":
            failure_codes.append("VISA_PROJECT_ENVIRONMENT_DRIFTED_2_OF_2")
        elif environment_binding.status != "MATCHED":
            failure_codes.append("VISA_PROJECT_ENVIRONMENT_BINDING_NOT_MATCHED")
        if not current_binding_verified:
            visa = None
    availability = (
        "CURRENT_PUBLIC_PROXY_WITH_HISTORICAL_OFFLINE_EVIDENCE"
        if visa is not None
        else "PUBLIC_PROXY_UNAVAILABLE_WITH_HISTORICAL_OFFLINE_EVIDENCE"
    )
    stable: dict[str, Any] = {
        "schema_version": PROJECTION_SCHEMA_VERSION,
        "status": "HOLD",
        "availability": availability,
        "verification_status": (
            "VERIFIED_BOUNDED_PROJECTION" if visa is not None else "FAILED_CLOSED"
        ),
        "failure_codes": sorted(failure_codes),
        "scope": scope,
        "visa_public_proxy": visa,
        "omni_offline_validation": omni,
        "factory_shadow_metrics": factory,
        "production_release_allowed": False,
        "machine_write_permitted": False,
        "read_only": True,
        "claim_boundary": (
            "This read-only projection separates the current-environment RC5 public "
            "proxy recomputation, historical private offline dataset evidence, and "
            "unmeasured factory shadow metrics. It does not authorize production "
            "release, replace a quality owner, or prove customer acceptance."
        ),
        "projection_hash_profile": PROJECTION_HASH_PROFILE,
    }
    return PrivateIndustrialValidationSummary(
        **stable,
        projection_sha256=_domain_sha256("industrial-validation-projection", stable),
    )


def verify_private_industrial_validation_summary(
    summary: PrivateIndustrialValidationSummary,
) -> None:
    stable = summary.model_dump(mode="json", exclude={"projection_sha256"})
    expected = _domain_sha256("industrial-validation-projection", stable)
    if not hmac.compare_digest(expected, summary.projection_sha256):
        raise ValueError("private industrial validation projection digest mismatch")
    if summary.verification_status == "VERIFIED_BOUNDED_PROJECTION":
        if summary.visa_public_proxy is None:
            raise ValueError("verified projection requires a compact VisA receipt")
        if summary.availability != (
            "CURRENT_PUBLIC_PROXY_WITH_HISTORICAL_OFFLINE_EVIDENCE"
        ):
            raise ValueError("verified projection availability drifted")
        if (
            summary.visa_public_proxy.core_component_binding.status != "MATCHED"
            or summary.visa_public_proxy.project_environment_binding.status != "MATCHED"
        ):
            raise ValueError("verified projection requires current source identity")
    elif summary.visa_public_proxy is not None:
        raise ValueError("failed-closed projection cannot expose VisA metrics")
    elif summary.availability != (
        "PUBLIC_PROXY_UNAVAILABLE_WITH_HISTORICAL_OFFLINE_EVIDENCE"
    ):
        raise ValueError("failed-closed projection availability drifted")
    omni = summary.omni_offline_validation
    if (
        omni.source_report_file_sha256 != _OMNI_SOURCE_REPORT_FILE_SHA256
        or omni.capa_receipt_sha256 != _OMNI_CAPA_RECEIPT_SHA256
        or (
            omni.source_profile_image_count,
            omni.source_profile_mask_count,
            omni.fixed_gate_sample_count,
            omni.parent_finding_count,
            omni.child_finding_count,
            omni.verified_closed_responsibility_count,
            omni.open_responsibility_count,
        )
        != (4464, 1439, 180, 49, 33, 6, 43)
    ):
        raise ValueError("Omni historical projection facts drifted")


class PrivateIndustrialValidationSource:
    """Construct the projection from a sealed compact receipt plus current repo bytes."""

    def __init__(
        self,
        project_root: str | Path | None = None,
        *,
        visa_compact_receipt_path: str | Path | None = None,
        expected_visa_compact_receipt_content_sha256: str = (
            FROZEN_VISA_COMPACT_RECEIPT_CONTENT_SHA256
        ),
    ) -> None:
        self.project_root = (
            Path(project_root).expanduser().resolve()
            if project_root is not None
            else _SOURCE_PROJECT_ROOT
        )
        self.visa_compact_receipt_path = (
            Path(visa_compact_receipt_path).expanduser().resolve()
            if visa_compact_receipt_path is not None
            else DEFAULT_VISA_COMPACT_RECEIPT_PATH
        )
        self.expected_visa_compact_receipt_content_sha256 = (
            expected_visa_compact_receipt_content_sha256
        )

    def project(
        self, *, scope: IndustrialValidationScope
    ) -> PrivateIndustrialValidationSummary:
        receipt: VisaPublicProxyCompactReceipt | None = None
        receipt_file_sha256: str | None = None
        failure_code: str | None = None
        try:
            receipt, receipt_file_sha256 = load_visa_public_proxy_compact_receipt(
                self.visa_compact_receipt_path,
                expected_content_sha256=(
                    self.expected_visa_compact_receipt_content_sha256
                ),
            )
        except FileNotFoundError:
            failure_code = "VISA_COMPACT_RECEIPT_MISSING"
        except OSError:
            failure_code = "VISA_COMPACT_RECEIPT_UNREADABLE"
        except ValueError as error:
            failure_code = (
                "VISA_COMPACT_RECEIPT_CONTENT_SHA256_MISMATCH"
                if "content SHA-256 mismatch" in str(error)
                else "VISA_COMPACT_RECEIPT_CONTRACT_INVALID"
            )
        projection = build_private_industrial_validation_summary(
            project_root=self.project_root,
            scope=scope,
            visa_receipt=receipt,
            visa_receipt_file_sha256=receipt_file_sha256,
            visa_failure_code=failure_code,
        )
        verify_private_industrial_validation_summary(projection)
        return projection


__all__ = [
    "DYNAMIC_CAPABILITY_CLAIM",
    "DEFAULT_VISA_COMPACT_RECEIPT_PATH",
    "FROZEN_VISA_COMPACT_RECEIPT_CONTENT_SHA256",
    "ArtifactIdentityBinding",
    "CompactArtifactIdentity",
    "CompactVisaScenarioCounts",
    "CompactVisaStrategyCounts",
    "FactoryShadowMetricsProjection",
    "IndustrialValidationScope",
    "OmniOfflineValidationProjection",
    "PrivateIndustrialRateMetric",
    "PrivateIndustrialValidationSource",
    "PrivateIndustrialValidationSummary",
    "VisaPublicProxyProjection",
    "VisaPublicProxyCompactReceipt",
    "VisaScenarioMetrics",
    "VisaScenarioStrategyMetrics",
    "build_private_industrial_validation_summary",
    "global_industrial_validation_scope",
    "load_visa_public_proxy_compact_receipt",
    "scoped_industrial_validation_scope",
    "verify_private_industrial_validation_summary",
]
