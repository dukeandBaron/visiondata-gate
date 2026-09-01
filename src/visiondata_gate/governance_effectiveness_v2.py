"""Per-unit governance metrics and paired orchestration evidence for GOAI review.

The v1 shadow contract accepts an operator-reviewed confusion summary.  This
module adds the stricter evidence plane needed for semifinal review:

* every false-release / false-block observation is derived from a pseudonymous
  governance unit and an external adjudication binding;
* remediation outcomes remain separate from disposition confusion counts;
* Dynamic-vs-Fixed claims are computed only from paired episodes that share one
  input contract, input manifest, and truth label;
* authorized private shadow evidence and frozen synthetic orchestration fixtures
  are never pooled into one metric.

Nothing in this module feeds labels back into the Agent core or authorizes a
production release.
"""

from __future__ import annotations

from datetime import datetime
import hashlib
import hmac
import json
from math import sqrt
from pathlib import Path
import re
from typing import Any, Literal

from pydantic import Field, field_validator, model_validator

from .audit_envelope import canonical_jcs_bytes
from .dynamic_benchmark import (
    DynamicArchitecture,
    load_dynamic_benchmark_report,
)
from .evidence import sha256_file
from .product_models import ProductModel


SHA256_PATTERN = r"^[0-9a-f]{64}$"
SAFE_IDENTIFIER_PATTERN = r"^[A-Za-z0-9][A-Za-z0-9_.:-]{1,159}$"
GOVERNANCE_FRAME_MAGIC = b"visiondata-gate.governance-effectiveness.v2\x00"
WILSON_Z_95 = 1.959963984540054

EvaluationScope = Literal[
    "PRIVATE_AUTHORIZED_SHADOW",
    "SYNTHETIC_FIXED_FIXTURE",
    "PUBLIC_INDUSTRIAL_PROXY_WITH_PROGRAMMATIC_GOVERNANCE_TRUTH",
]
TruthDisposition = Literal["BLOCK_REQUIRED", "RELEASE_ALLOWED"]
SystemDisposition = Literal["RELEASED", "BLOCKED", "HUMAN_REVIEW"]
StrategyId = Literal[
    "FIXED_RULE_PIPELINE",
    "FIXED_EXHAUSTIVE_PIPELINE",
    "DYNAMIC_EVIDENCE_AGENT",
]
BaselineStrategyId = Literal[
    "FIXED_RULE_PIPELINE",
    "FIXED_EXHAUSTIVE_PIPELINE",
]
MetricStatusV2 = Literal[
    "MEASURED",
    "NOT_MEASURED",
    "NOT_MEASURED_PENDING_ADJUDICATION",
    "NOT_APPLICABLE",
]


def _aware_timestamp(value: str, *, field_name: str) -> datetime:
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as error:
        raise ValueError(f"{field_name} must be ISO-8601") from error
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ValueError(f"{field_name} must include an explicit UTC offset")
    return parsed


def _reject_path_or_control(value: str, *, field_name: str) -> str:
    if any(character in value for character in ("/", "\\", "\0", "\r", "\n")):
        raise ValueError(f"{field_name} cannot contain paths or controls")
    return value


def _reject_sensitive_path_text(value: str, *, field_name: str) -> str:
    if re.search(r"(?i)(?:[a-z]:[\\/]|\\\\[^\\]+\\)", value):
        raise ValueError(f"{field_name} cannot contain a host path")
    if "\0" in value:
        raise ValueError(f"{field_name} cannot contain controls")
    return value


def _domain_sha256(domain: str, value: Any) -> str:
    domain_bytes = domain.encode("utf-8")
    payload = canonical_jcs_bytes(value)
    frame = b"".join(
        (
            GOVERNANCE_FRAME_MAGIC,
            len(domain_bytes).to_bytes(2, "big"),
            domain_bytes,
            len(payload).to_bytes(8, "big"),
            payload,
        )
    )
    return hashlib.sha256(frame).hexdigest()


def _wilson_interval(numerator: int, denominator: int) -> tuple[float, float]:
    if denominator <= 0:
        raise ValueError("Wilson interval requires a positive denominator")
    p = numerator / denominator
    z2 = WILSON_Z_95**2
    scale = 1 + z2 / denominator
    center = (p + z2 / (2 * denominator)) / scale
    margin = (
        WILSON_Z_95
        * sqrt(p * (1 - p) / denominator + z2 / (4 * denominator**2))
        / scale
    )
    lower = max(0.0, center - margin)
    upper = min(1.0, center + margin)
    if abs(lower) < 1e-15:
        lower = 0.0
    if abs(1.0 - upper) < 1e-15:
        upper = 1.0
    return lower, upper


class GovernanceRateEstimateV2(ProductModel):
    """One fixed-definition rate with its finite-denominator uncertainty."""

    key: str = Field(min_length=1, max_length=120)
    status: MetricStatusV2
    numerator: int = Field(ge=0)
    denominator: int = Field(ge=0)
    value: float | None = Field(default=None, ge=0.0, le=1.0)
    wilson_95_lower: float | None = Field(default=None, ge=0.0, le=1.0)
    wilson_95_upper: float | None = Field(default=None, ge=0.0, le=1.0)
    unit_of_analysis: str = Field(min_length=1, max_length=120)
    definition: str = Field(min_length=1, max_length=500)

    @model_validator(mode="after")
    def validate_rate(self) -> GovernanceRateEstimateV2:
        if self.denominator == 0:
            if self.numerator != 0 or any(
                item is not None
                for item in (self.value, self.wilson_95_lower, self.wilson_95_upper)
            ):
                raise ValueError("zero-denominator rate cannot carry a value")
            if self.status == "MEASURED":
                raise ValueError("zero-denominator rate cannot be MEASURED")
            return self
        if self.status != "MEASURED":
            raise ValueError("positive-denominator rate must be MEASURED")
        if self.numerator > self.denominator:
            raise ValueError("rate numerator cannot exceed denominator")
        if any(
            item is None
            for item in (self.value, self.wilson_95_lower, self.wilson_95_upper)
        ):
            raise ValueError("measured rate requires value and Wilson interval")
        expected_value = self.numerator / self.denominator
        expected_lower, expected_upper = _wilson_interval(
            self.numerator, self.denominator
        )
        if abs(float(self.value) - expected_value) > 1e-12:
            raise ValueError("rate value does not match numerator / denominator")
        if abs(float(self.wilson_95_lower) - expected_lower) > 1e-12:
            raise ValueError("rate lower interval does not reconcile")
        if abs(float(self.wilson_95_upper) - expected_upper) > 1e-12:
            raise ValueError("rate upper interval does not reconcile")
        return self


def _rate(
    *,
    key: str,
    numerator: int,
    denominator: int,
    unit_of_analysis: str,
    definition: str,
    empty_status: Literal[
        "NOT_MEASURED",
        "NOT_MEASURED_PENDING_ADJUDICATION",
        "NOT_APPLICABLE",
    ],
) -> GovernanceRateEstimateV2:
    lower: float | None = None
    upper: float | None = None
    if denominator:
        lower, upper = _wilson_interval(numerator, denominator)
    return GovernanceRateEstimateV2(
        key=key,
        status="MEASURED" if denominator else empty_status,
        numerator=numerator,
        denominator=denominator,
        value=numerator / denominator if denominator else None,
        wilson_95_lower=lower,
        wilson_95_upper=upper,
        unit_of_analysis=unit_of_analysis,
        definition=definition,
    )


class GovernanceTruthBindingV2(ProductModel):
    """External truth binding; pending labels are explicit rather than inferred."""

    status: Literal["ADJUDICATED", "PENDING_ADJUDICATION"]
    disposition: TruthDisposition | None = None
    method: (
        Literal[
            "QUALITY_OWNER_ADJUDICATION",
            "DUAL_HUMAN_ADJUDICATION",
            "EXISTING_QMS_DISPOSITION",
            "FROZEN_SYNTHETIC_FIXTURE",
            "FROZEN_PROGRAMMATIC_GOVERNANCE_INJECTION",
        ]
        | None
    ) = None
    adjudication_receipt_sha256: str | None = Field(
        default=None, pattern=SHA256_PATTERN
    )
    pending_reason: str | None = Field(default=None, min_length=8, max_length=500)

    @field_validator("pending_reason")
    @classmethod
    def reject_path_in_pending_reason(cls, value: str | None) -> str | None:
        if value is None:
            return None
        return _reject_sensitive_path_text(value, field_name="pending_reason")

    @model_validator(mode="after")
    def validate_truth_binding(self) -> GovernanceTruthBindingV2:
        adjudicated_fields = (
            self.disposition,
            self.method,
            self.adjudication_receipt_sha256,
        )
        if self.status == "ADJUDICATED":
            if any(item is None for item in adjudicated_fields):
                raise ValueError(
                    "adjudicated truth requires disposition, method, and receipt"
                )
            if self.pending_reason is not None:
                raise ValueError("adjudicated truth cannot carry a pending reason")
        else:
            if any(item is not None for item in adjudicated_fields):
                raise ValueError("pending truth cannot carry adjudicated values")
            if self.pending_reason is None:
                raise ValueError("pending truth requires an explicit reason")
        return self


class GovernanceStrategyObservationV2(ProductModel):
    """Pseudonymous decision and bounded orchestration trace for one strategy."""

    strategy: StrategyId
    system_disposition: SystemDisposition
    decision_receipt_sha256: str = Field(pattern=SHA256_PATTERN)
    trace_receipt_sha256: str = Field(pattern=SHA256_PATTERN)
    replan_triggered: bool
    replan_count: int = Field(ge=0)
    selected_worker_count: int = Field(ge=0)
    selected_worker_ids: list[str] = Field(default_factory=list)
    worker_selection_evidence_status: Literal[
        "PROVIDED",
        "SUMMARY_ONLY_NO_WORKER_IDS",
        "LEGACY_BENCHMARK_NO_SELECTION_RECEIPT",
        "NOT_APPLICABLE",
    ]
    worker_selection_receipt_sha256: str | None = Field(
        default=None, pattern=SHA256_PATTERN
    )
    detected_evidence_gap_ids: list[str] = Field(default_factory=list)
    covered_required_gap_ids: list[str] = Field(default_factory=list)
    unresolved_required_gap_ids: list[str] = Field(default_factory=list)
    tool_call_count: int = Field(ge=0)
    redundant_tool_call_count: int | None = Field(default=None, ge=0)
    latency_ms: float | None = Field(default=None, ge=0.0)
    actual_model_call_count: int = Field(default=0, ge=0)
    actual_model_token_count: int = Field(default=0, ge=0)
    provider_billed_api_cost_cny: float = Field(default=0.0, ge=0.0)

    @field_validator(
        "selected_worker_ids",
        "detected_evidence_gap_ids",
        "covered_required_gap_ids",
        "unresolved_required_gap_ids",
    )
    @classmethod
    def validate_unique_safe_identifiers(cls, values: list[str]) -> list[str]:
        if len(values) != len(set(values)):
            raise ValueError("strategy trace identifiers must be unique")
        for value in values:
            _reject_path_or_control(value, field_name="strategy trace identifier")
        return values

    @model_validator(mode="after")
    def validate_observation(self) -> GovernanceStrategyObservationV2:
        if self.replan_triggered != (self.replan_count > 0):
            raise ValueError("replan flag and count do not reconcile")
        if (
            self.strategy
            in {
                "FIXED_RULE_PIPELINE",
                "FIXED_EXHAUSTIVE_PIPELINE",
            }
            and self.replan_count != 0
        ):
            raise ValueError("fixed pipeline cannot claim dynamic replanning")
        if len(self.selected_worker_ids) > self.selected_worker_count:
            raise ValueError("selected Worker IDs exceed the declared count")
        if self.worker_selection_evidence_status == "PROVIDED":
            if self.worker_selection_receipt_sha256 is None:
                raise ValueError(
                    "provided Worker selection evidence requires a receipt"
                )
            if len(self.selected_worker_ids) != self.selected_worker_count:
                raise ValueError("provided Worker selection evidence requires all IDs")
        elif self.worker_selection_receipt_sha256 is not None:
            raise ValueError(
                "unavailable Worker selection evidence cannot carry a receipt"
            )
        if self.worker_selection_evidence_status == "NOT_APPLICABLE" and (
            self.selected_worker_count or self.selected_worker_ids
        ):
            raise ValueError("not-applicable Worker selection cannot carry Workers")
        if not set(self.covered_required_gap_ids).issubset(
            self.detected_evidence_gap_ids
        ):
            raise ValueError("covered gaps must be detected gaps")
        return self


def _complex_conflict_expected(
    conflict_tags: list[str], required_gap_ids: list[str]
) -> bool:
    return len(required_gap_ids) >= 2 or "cross_tool_action_conflict" in conflict_tags


class GovernanceDecisionUnitV2(ProductModel):
    """One batch/case-level release decision at a fixed analysis grain."""

    unit_id: str = Field(pattern=SAFE_IDENTIFIER_PATTERN)
    unit_of_analysis: Literal["governance_case"] = "governance_case"
    source_scope: EvaluationScope
    input_contract_sha256: str = Field(pattern=SHA256_PATTERN)
    input_manifest_sha256: str = Field(pattern=SHA256_PATTERN)
    truth: GovernanceTruthBindingV2
    required_evidence_gap_ids: list[str] = Field(default_factory=list)
    conflict_tags: list[str] = Field(default_factory=list)
    complex_conflict: bool
    observation: GovernanceStrategyObservationV2

    @field_validator("required_evidence_gap_ids", "conflict_tags")
    @classmethod
    def validate_unique_tags(cls, values: list[str]) -> list[str]:
        if len(values) != len(set(values)):
            raise ValueError("decision-unit tags must be unique")
        for value in values:
            _reject_path_or_control(value, field_name="decision-unit tag")
        return values

    @model_validator(mode="after")
    def validate_unit(self) -> GovernanceDecisionUnitV2:
        if self.complex_conflict != _complex_conflict_expected(
            self.conflict_tags, self.required_evidence_gap_ids
        ):
            raise ValueError("complex-conflict classification does not match protocol")
        required = set(self.required_evidence_gap_ids)
        if not set(self.observation.covered_required_gap_ids).issubset(required):
            raise ValueError("covered gaps are outside the frozen required set")
        if set(self.observation.unresolved_required_gap_ids) != (
            required - set(self.observation.covered_required_gap_ids)
        ):
            raise ValueError("unresolved gaps do not reconcile with required coverage")
        return self


class GovernanceRemediationUnitV2(ProductModel):
    """One remediation attempt with an independent same-contract recheck."""

    remediation_id: str = Field(pattern=SAFE_IDENTIFIER_PATTERN)
    source_scope: EvaluationScope
    parent_unit_id: str = Field(pattern=SAFE_IDENTIFIER_PATTERN)
    verification_contract_sha256: str = Field(pattern=SHA256_PATTERN)
    parent_decision_receipt_sha256: str = Field(pattern=SHA256_PATTERN)
    child_decision_receipt_sha256: str | None = Field(
        default=None, pattern=SHA256_PATTERN
    )
    lineage_receipt_sha256: str | None = Field(default=None, pattern=SHA256_PATTERN)
    named_approval_binding_sha256: str | None = Field(
        default=None, pattern=SHA256_PATTERN
    )
    outcome: Literal["VERIFIED_PASS", "VERIFIED_FAIL", "PENDING_RECHECK"]
    independent_recheck_performed: bool
    production_release_allowed: Literal[False] = False

    @model_validator(mode="after")
    def validate_remediation(self) -> GovernanceRemediationUnitV2:
        if self.outcome == "PENDING_RECHECK":
            if self.independent_recheck_performed:
                raise ValueError("pending remediation cannot claim a completed recheck")
            if self.child_decision_receipt_sha256 is not None:
                raise ValueError("pending remediation cannot carry a child decision")
        else:
            if not self.independent_recheck_performed:
                raise ValueError("verified remediation requires an independent recheck")
            if self.child_decision_receipt_sha256 is None:
                raise ValueError(
                    "verified remediation requires a child decision receipt"
                )
            if self.lineage_receipt_sha256 is None:
                raise ValueError("verified remediation requires a lineage receipt")
            if self.named_approval_binding_sha256 is None:
                raise ValueError("verified remediation requires named approval binding")
        return self


class CreateGovernanceEffectivenessV2Request(ProductModel):
    evaluation_id: str = Field(pattern=SAFE_IDENTIFIER_PATTERN)
    source_scope: EvaluationScope
    evaluated_strategy: StrategyId
    dataset_identity_sha256: str = Field(pattern=SHA256_PATTERN)
    source_authorization_binding_sha256: str | None = Field(
        default=None, pattern=SHA256_PATTERN
    )
    decision_units: list[GovernanceDecisionUnitV2] = Field(default_factory=list)
    remediation_units: list[GovernanceRemediationUnitV2] = Field(default_factory=list)
    evaluated_at: str
    note: str = Field(min_length=8, max_length=1000)
    operator_attests_authorized_use: bool
    raw_images_transmitted: Literal[False] = False
    shadow_labels_enter_agent_core: Literal[False] = False
    machine_write_permitted: Literal[False] = False

    @field_validator("note")
    @classmethod
    def reject_path_in_note(cls, value: str) -> str:
        return _reject_sensitive_path_text(value, field_name="note")

    @model_validator(mode="after")
    def validate_request(self) -> CreateGovernanceEffectivenessV2Request:
        _aware_timestamp(self.evaluated_at, field_name="evaluated_at")
        if not self.decision_units and not self.remediation_units:
            raise ValueError("governance evaluation requires at least one unit")
        if (
            self.source_scope == "PRIVATE_AUTHORIZED_SHADOW"
            and self.source_authorization_binding_sha256 is None
        ):
            raise ValueError("private shadow evaluation requires authorization binding")
        if self.source_scope == "PRIVATE_AUTHORIZED_SHADOW" and not (
            self.operator_attests_authorized_use
        ):
            raise ValueError(
                "private shadow evaluation requires operator authorization"
            )
        if (
            self.source_scope
            == "PUBLIC_INDUSTRIAL_PROXY_WITH_PROGRAMMATIC_GOVERNANCE_TRUTH"
            and self.source_authorization_binding_sha256 is None
        ):
            raise ValueError(
                "public industrial proxy evaluation requires a license and "
                "attribution binding"
            )
        if (
            self.source_scope
            == "PUBLIC_INDUSTRIAL_PROXY_WITH_PROGRAMMATIC_GOVERNANCE_TRUTH"
            and not self.operator_attests_authorized_use
        ):
            raise ValueError(
                "public industrial proxy evaluation requires authorized-use attestation"
            )
        if self.source_scope == (
            "PUBLIC_INDUSTRIAL_PROXY_WITH_PROGRAMMATIC_GOVERNANCE_TRUTH"
        ) and any(
            item.truth.status == "ADJUDICATED"
            and item.truth.method != "FROZEN_PROGRAMMATIC_GOVERNANCE_INJECTION"
            for item in self.decision_units
        ):
            raise ValueError(
                "public industrial proxy truth must bind a frozen programmatic "
                "governance injection"
            )
        if any(item.source_scope != self.source_scope for item in self.decision_units):
            raise ValueError("decision units cannot mix evidence scopes")
        if any(
            item.source_scope != self.source_scope for item in self.remediation_units
        ):
            raise ValueError("remediation units cannot mix evidence scopes")
        if any(
            item.observation.strategy != self.evaluated_strategy
            for item in self.decision_units
        ):
            raise ValueError("decision units cannot mix evaluated strategies")
        decision_ids = [item.unit_id for item in self.decision_units]
        remediation_ids = [item.remediation_id for item in self.remediation_units]
        if len(decision_ids) != len(set(decision_ids)):
            raise ValueError("governance decision unit IDs must be unique")
        if len(remediation_ids) != len(set(remediation_ids)):
            raise ValueError("governance remediation IDs must be unique")
        return self


def _governance_protocol() -> dict[str, Any]:
    return {
        "protocol_id": "visiondata-gate.governance-effectiveness.v2",
        "decision_unit_of_analysis": "governance_case",
        "false_release_rate": (
            "released adjudicated BLOCK_REQUIRED cases / all adjudicated "
            "BLOCK_REQUIRED cases"
        ),
        "false_block_rate": (
            "blocked or human-review adjudicated RELEASE_ALLOWED cases / all "
            "adjudicated RELEASE_ALLOWED cases"
        ),
        "verified_remediation_pass_rate": (
            "VERIFIED_PASS attempts / all completed independent same-contract rechecks"
        ),
        "pending_remediation_rule": (
            "PENDING_RECHECK is reported separately and never silently removed"
        ),
        "uncertainty": "two-sided Wilson score interval, 95 percent",
        "complex_conflict_predicate": (
            "two or more required evidence gaps OR cross_tool_action_conflict"
        ),
        "label_isolation": "shadow labels never enter Agent planning or Judge input",
    }


class GovernanceEffectivenessV2Report(ProductModel):
    schema_version: Literal["visiondata-gate.governance-effectiveness-report.v2"] = (
        "visiondata-gate.governance-effectiveness-report.v2"
    )
    request: CreateGovernanceEffectivenessV2Request
    request_sha256: str = Field(pattern=SHA256_PATTERN)
    protocol: dict[str, Any]
    protocol_sha256: str = Field(pattern=SHA256_PATTERN)
    decision_units_sha256: str = Field(pattern=SHA256_PATTERN)
    remediation_units_sha256: str = Field(pattern=SHA256_PATTERN)
    measurement_status: Literal["MEASURED", "PARTIAL_MEASUREMENT", "NOT_MEASURED"]
    decision_unit_count: int = Field(ge=0)
    adjudicated_decision_unit_count: int = Field(ge=0)
    pending_adjudication_count: int = Field(ge=0)
    confusion: dict[str, int]
    false_release_rate: GovernanceRateEstimateV2
    false_block_rate: GovernanceRateEstimateV2
    verified_remediation_pass_rate: GovernanceRateEstimateV2
    pending_remediation_rate: GovernanceRateEstimateV2
    adjudication_coverage_rate: GovernanceRateEstimateV2
    complex_conflict_coverage_rate: GovernanceRateEstimateV2
    production_release_allowed: Literal[False] = False
    claim_boundary: str
    report_sha256: str = Field(pattern=SHA256_PATTERN)

    @model_validator(mode="after")
    def validate_report_bindings(self) -> GovernanceEffectivenessV2Report:
        if self.decision_unit_count != len(self.request.decision_units):
            raise ValueError("decision-unit count does not reconcile")
        if self.pending_adjudication_count != (
            self.decision_unit_count - self.adjudicated_decision_unit_count
        ):
            raise ValueError("pending-adjudication count does not reconcile")
        if sum(self.confusion.values()) != self.adjudicated_decision_unit_count:
            raise ValueError("confusion matrix does not reconcile")
        return self


def _measurement_status(
    metrics: list[GovernanceRateEstimateV2],
) -> Literal["MEASURED", "PARTIAL_MEASUREMENT", "NOT_MEASURED"]:
    measured = sum(metric.status == "MEASURED" for metric in metrics)
    if measured == 0:
        return "NOT_MEASURED"
    if measured == len(metrics):
        return "MEASURED"
    return "PARTIAL_MEASUREMENT"


def build_governance_effectiveness_v2_report(
    request: CreateGovernanceEffectivenessV2Request,
) -> GovernanceEffectivenessV2Report:
    adjudicated = [
        item for item in request.decision_units if item.truth.status == "ADJUDICATED"
    ]
    true_block = false_release = true_release = false_block = 0
    for item in adjudicated:
        truth = item.truth.disposition
        observed = item.observation.system_disposition
        if truth == "BLOCK_REQUIRED":
            if observed == "RELEASED":
                false_release += 1
            else:
                true_block += 1
        elif observed == "RELEASED":
            true_release += 1
        else:
            false_block += 1

    completed_remediations = [
        item for item in request.remediation_units if item.outcome != "PENDING_RECHECK"
    ]
    remediation_passes = sum(
        item.outcome == "VERIFIED_PASS" for item in completed_remediations
    )
    pending_remediations = sum(
        item.outcome == "PENDING_RECHECK" for item in request.remediation_units
    )
    complex_units = [item for item in request.decision_units if item.complex_conflict]
    adjudicated_complex = sum(
        item.truth.status == "ADJUDICATED" for item in complex_units
    )

    false_release_rate = _rate(
        key="false_release_rate",
        numerator=false_release,
        denominator=true_block + false_release,
        unit_of_analysis="governance_case",
        definition=_governance_protocol()["false_release_rate"],
        empty_status=(
            "NOT_APPLICABLE"
            if adjudicated
            else "NOT_MEASURED_PENDING_ADJUDICATION"
            if request.decision_units
            else "NOT_MEASURED"
        ),
    )
    false_block_rate = _rate(
        key="false_block_rate",
        numerator=false_block,
        denominator=true_release + false_block,
        unit_of_analysis="governance_case",
        definition=_governance_protocol()["false_block_rate"],
        empty_status=(
            "NOT_APPLICABLE"
            if adjudicated
            else "NOT_MEASURED_PENDING_ADJUDICATION"
            if request.decision_units
            else "NOT_MEASURED"
        ),
    )
    remediation_pass_rate = _rate(
        key="verified_remediation_pass_rate",
        numerator=remediation_passes,
        denominator=len(completed_remediations),
        unit_of_analysis="same_contract_remediation_recheck",
        definition=_governance_protocol()["verified_remediation_pass_rate"],
        empty_status="NOT_MEASURED",
    )
    pending_remediation_rate = _rate(
        key="pending_remediation_rate",
        numerator=pending_remediations,
        denominator=len(request.remediation_units),
        unit_of_analysis="remediation_attempt",
        definition="pending rechecks / all registered remediation attempts",
        empty_status="NOT_MEASURED",
    )
    adjudication_coverage = _rate(
        key="adjudication_coverage_rate",
        numerator=len(adjudicated),
        denominator=len(request.decision_units),
        unit_of_analysis="governance_case",
        definition="externally adjudicated cases / all shadow decision cases",
        empty_status="NOT_MEASURED",
    )
    complex_coverage = _rate(
        key="complex_conflict_coverage_rate",
        numerator=adjudicated_complex,
        denominator=len(complex_units),
        unit_of_analysis="complex_conflict_governance_case",
        definition="adjudicated complex-conflict cases / all complex-conflict cases",
        empty_status="NOT_APPLICABLE",
    )
    protocol = _governance_protocol()
    stable = {
        "schema_version": "visiondata-gate.governance-effectiveness-report.v2",
        "request": request,
        "request_sha256": _domain_sha256("request", request),
        "protocol": protocol,
        "protocol_sha256": _domain_sha256("protocol", protocol),
        "decision_units_sha256": _domain_sha256(
            "decision-units", request.decision_units
        ),
        "remediation_units_sha256": _domain_sha256(
            "remediation-units", request.remediation_units
        ),
        "measurement_status": _measurement_status(
            [false_release_rate, false_block_rate, remediation_pass_rate]
        ),
        "decision_unit_count": len(request.decision_units),
        "adjudicated_decision_unit_count": len(adjudicated),
        "pending_adjudication_count": len(request.decision_units) - len(adjudicated),
        "confusion": {
            "true_block_count": true_block,
            "false_release_count": false_release,
            "true_release_count": true_release,
            "false_block_count": false_block,
        },
        "false_release_rate": false_release_rate,
        "false_block_rate": false_block_rate,
        "verified_remediation_pass_rate": remediation_pass_rate,
        "pending_remediation_rate": pending_remediation_rate,
        "adjudication_coverage_rate": adjudication_coverage,
        "complex_conflict_coverage_rate": complex_coverage,
        "production_release_allowed": False,
        "claim_boundary": (
            "This report derives governance rates only from pseudonymous per-case "
            "records and external adjudication bindings. Pending truth stays NOT_MEASURED. "
            "It is not customer acceptance, factory deployment, model certification, "
            "legal ownership proof, or production authorization."
        ),
    }
    return GovernanceEffectivenessV2Report(
        **stable,
        report_sha256=_domain_sha256("governance-report", stable),
    )


def verify_governance_effectiveness_v2_report(
    report: GovernanceEffectivenessV2Report,
) -> None:
    stable = report.model_dump(mode="json", exclude={"report_sha256"})
    observed = _domain_sha256("governance-report", stable)
    if not hmac.compare_digest(observed, report.report_sha256):
        raise ValueError("governance-effectiveness v2 report digest mismatch")
    rebuilt = build_governance_effectiveness_v2_report(report.request)
    if canonical_jcs_bytes(rebuilt) != canonical_jcs_bytes(report):
        raise ValueError(
            "governance-effectiveness v2 report failed deterministic replay"
        )


class PairedGovernanceEpisodeV2(ProductModel):
    """Same-input, same-truth episode comparing Fixed and Dynamic policies."""

    episode_id: str = Field(pattern=SAFE_IDENTIFIER_PATTERN)
    source_scope: EvaluationScope
    input_contract_sha256: str = Field(pattern=SHA256_PATTERN)
    input_manifest_sha256: str = Field(pattern=SHA256_PATTERN)
    truth: GovernanceTruthBindingV2
    required_evidence_gap_ids: list[str] = Field(default_factory=list)
    conflict_tags: list[str] = Field(default_factory=list)
    complex_conflict: bool
    fixed_observation: GovernanceStrategyObservationV2
    dynamic_observation: GovernanceStrategyObservationV2

    @field_validator("required_evidence_gap_ids", "conflict_tags")
    @classmethod
    def validate_episode_tags(cls, values: list[str]) -> list[str]:
        if len(values) != len(set(values)):
            raise ValueError("paired episode tags must be unique")
        for value in values:
            _reject_path_or_control(value, field_name="paired episode tag")
        return values

    @model_validator(mode="after")
    def validate_episode(self) -> PairedGovernanceEpisodeV2:
        if self.fixed_observation.strategy not in {
            "FIXED_RULE_PIPELINE",
            "FIXED_EXHAUSTIVE_PIPELINE",
        }:
            raise ValueError("paired fixed observation has the wrong strategy")
        if self.dynamic_observation.strategy != "DYNAMIC_EVIDENCE_AGENT":
            raise ValueError("paired Dynamic observation has the wrong strategy")
        if self.complex_conflict != _complex_conflict_expected(
            self.conflict_tags, self.required_evidence_gap_ids
        ):
            raise ValueError("paired complex-conflict classification drifted")
        required = set(self.required_evidence_gap_ids)
        for observation in (self.fixed_observation, self.dynamic_observation):
            covered = set(observation.covered_required_gap_ids)
            if not covered.issubset(required):
                raise ValueError("paired coverage is outside the required gap set")
            if set(observation.unresolved_required_gap_ids) != required - covered:
                raise ValueError("paired unresolved gaps do not reconcile")
        return self


class CreatePairedStrategyComparisonV2Request(ProductModel):
    comparison_id: str = Field(pattern=SAFE_IDENTIFIER_PATTERN)
    source_scope: EvaluationScope
    baseline_strategy: BaselineStrategyId
    dataset_identity_sha256: str = Field(pattern=SHA256_PATTERN)
    source_benchmark_sha256: str = Field(pattern=SHA256_PATTERN)
    episodes: list[PairedGovernanceEpisodeV2] = Field(min_length=1)
    evaluated_at: str
    note: str = Field(min_length=8, max_length=1000)
    raw_images_transmitted: Literal[False] = False
    production_release_allowed: Literal[False] = False

    @field_validator("note")
    @classmethod
    def reject_path_in_note(cls, value: str) -> str:
        return _reject_sensitive_path_text(value, field_name="note")

    @model_validator(mode="after")
    def validate_comparison_request(self) -> CreatePairedStrategyComparisonV2Request:
        _aware_timestamp(self.evaluated_at, field_name="evaluated_at")
        ids = [item.episode_id for item in self.episodes]
        if len(ids) != len(set(ids)):
            raise ValueError("paired episode IDs must be unique")
        if any(item.source_scope != self.source_scope for item in self.episodes):
            raise ValueError("paired comparison cannot mix evidence scopes")
        if any(
            item.fixed_observation.strategy != self.baseline_strategy
            for item in self.episodes
        ):
            raise ValueError("paired comparison baseline strategy does not reconcile")
        return self


class PairedStrategySummaryV2(ProductModel):
    strategy: StrategyId
    episode_count: int = Field(ge=0)
    adjudicated_episode_count: int = Field(ge=0)
    confusion: dict[str, int]
    false_release_rate: GovernanceRateEstimateV2
    false_block_rate: GovernanceRateEstimateV2
    evidence_gap_coverage_rate: GovernanceRateEstimateV2
    tool_call_count: int = Field(ge=0)
    redundant_tool_call_count: int | None = Field(default=None, ge=0)
    latency_ms_p95: float | None = Field(default=None, ge=0.0)
    actual_model_call_count: int = Field(ge=0)
    actual_model_token_count: int = Field(ge=0)
    provider_billed_api_cost_cny: float = Field(ge=0.0)


class PairedStrategyComparisonV2Report(ProductModel):
    schema_version: Literal["visiondata-gate.paired-strategy-comparison.v2"] = (
        "visiondata-gate.paired-strategy-comparison.v2"
    )
    request: CreatePairedStrategyComparisonV2Request
    request_sha256: str = Field(pattern=SHA256_PATTERN)
    pairing_protocol: dict[str, Any]
    pairing_protocol_sha256: str = Field(pattern=SHA256_PATTERN)
    episodes_sha256: str = Field(pattern=SHA256_PATTERN)
    adjudication_coverage_rate: GovernanceRateEstimateV2
    complex_conflict_episode_count: int = Field(ge=0)
    overall_fixed: PairedStrategySummaryV2
    overall_dynamic: PairedStrategySummaryV2
    complex_fixed: PairedStrategySummaryV2
    complex_dynamic: PairedStrategySummaryV2
    comparison_deltas: dict[str, int | float | None]
    complex_conflict_verdict: Literal[
        "DYNAMIC_SAFETY_ADVANTAGE",
        "DYNAMIC_FALSE_BLOCK_REDUCTION",
        "DYNAMIC_EFFICIENCY_ADVANTAGE",
        "NO_MEASURED_ADVANTAGE",
        "MEASURED_TRADEOFF",
        "NOT_MEASURED_PENDING_ADJUDICATION",
    ]
    external_competitor_system_executed: Literal[False] = False
    production_release_allowed: Literal[False] = False
    claim_boundary: str
    report_sha256: str = Field(pattern=SHA256_PATTERN)


def _p95(values: list[float]) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    position = (len(ordered) - 1) * 0.95
    lower = int(position)
    upper = min(lower + 1, len(ordered) - 1)
    fraction = position - lower
    return ordered[lower] * (1 - fraction) + ordered[upper] * fraction


def _strategy_summary(
    episodes: list[PairedGovernanceEpisodeV2],
    *,
    attribute: Literal["fixed_observation", "dynamic_observation"],
    fallback_strategy: StrategyId,
) -> PairedStrategySummaryV2:
    observations = [getattr(item, attribute) for item in episodes]
    adjudicated = [item for item in episodes if item.truth.status == "ADJUDICATED"]
    true_block = false_release = true_release = false_block = 0
    for item in adjudicated:
        observation = getattr(item, attribute)
        if item.truth.disposition == "BLOCK_REQUIRED":
            if observation.system_disposition == "RELEASED":
                false_release += 1
            else:
                true_block += 1
        elif observation.system_disposition == "RELEASED":
            true_release += 1
        else:
            false_block += 1
    required_gap_count = sum(len(item.required_evidence_gap_ids) for item in episodes)
    covered_gap_count = sum(
        len(getattr(item, attribute).covered_required_gap_ids) for item in episodes
    )
    redundant_values = [item.redundant_tool_call_count for item in observations]
    latencies = [
        float(item.latency_ms) for item in observations if item.latency_ms is not None
    ]
    return PairedStrategySummaryV2(
        strategy=observations[0].strategy if observations else fallback_strategy,
        episode_count=len(episodes),
        adjudicated_episode_count=len(adjudicated),
        confusion={
            "true_block_count": true_block,
            "false_release_count": false_release,
            "true_release_count": true_release,
            "false_block_count": false_block,
        },
        false_release_rate=_rate(
            key="false_release_rate",
            numerator=false_release,
            denominator=true_block + false_release,
            unit_of_analysis="paired_governance_episode",
            definition="false releases / paired truth cases requiring block",
            empty_status="NOT_APPLICABLE" if adjudicated else "NOT_MEASURED",
        ),
        false_block_rate=_rate(
            key="false_block_rate",
            numerator=false_block,
            denominator=true_release + false_block,
            unit_of_analysis="paired_governance_episode",
            definition="false blocks / paired truth cases allowing release",
            empty_status="NOT_APPLICABLE" if adjudicated else "NOT_MEASURED",
        ),
        evidence_gap_coverage_rate=_rate(
            key="evidence_gap_coverage_rate",
            numerator=covered_gap_count,
            denominator=required_gap_count,
            unit_of_analysis="required_evidence_gap",
            definition="covered required evidence gaps / all required evidence gaps",
            empty_status="NOT_APPLICABLE",
        ),
        tool_call_count=sum(item.tool_call_count for item in observations),
        redundant_tool_call_count=(
            sum(int(item) for item in redundant_values if item is not None)
            if all(item is not None for item in redundant_values)
            else None
        ),
        latency_ms_p95=_p95(latencies),
        actual_model_call_count=sum(
            item.actual_model_call_count for item in observations
        ),
        actual_model_token_count=sum(
            item.actual_model_token_count for item in observations
        ),
        provider_billed_api_cost_cny=sum(
            item.provider_billed_api_cost_cny for item in observations
        ),
    )


def _pairing_protocol(baseline_strategy: BaselineStrategyId) -> dict[str, Any]:
    return {
        "protocol_id": "visiondata-gate.paired-strategy-comparison.v2",
        "pairing_keys": [
            "episode_id",
            "input_contract_sha256",
            "input_manifest_sha256",
            "adjudication_receipt_sha256",
        ],
        "fixed_strategy": baseline_strategy,
        "dynamic_strategy": "DYNAMIC_EVIDENCE_AGENT",
        "complex_conflict_predicate": (
            "two or more required evidence gaps OR cross_tool_action_conflict"
        ),
        "advantage_rule": (
            "claim safety advantage only when complex-subset false releases decrease "
            "without increasing false blocks"
        ),
        "scope_isolation": "private and synthetic evidence are never pooled",
    }


def _complex_verdict(
    fixed: PairedStrategySummaryV2,
    dynamic: PairedStrategySummaryV2,
) -> Literal[
    "DYNAMIC_SAFETY_ADVANTAGE",
    "DYNAMIC_FALSE_BLOCK_REDUCTION",
    "DYNAMIC_EFFICIENCY_ADVANTAGE",
    "NO_MEASURED_ADVANTAGE",
    "MEASURED_TRADEOFF",
    "NOT_MEASURED_PENDING_ADJUDICATION",
]:
    if fixed.adjudicated_episode_count == 0:
        return "NOT_MEASURED_PENDING_ADJUDICATION"
    fixed_false_release = fixed.confusion["false_release_count"]
    dynamic_false_release = dynamic.confusion["false_release_count"]
    fixed_false_block = fixed.confusion["false_block_count"]
    dynamic_false_block = dynamic.confusion["false_block_count"]
    safety_better = dynamic_false_release < fixed_false_release
    no_new_block_harm = dynamic_false_block <= fixed_false_block
    if safety_better and no_new_block_harm:
        return "DYNAMIC_SAFETY_ADVANTAGE"
    if (
        dynamic_false_release == fixed_false_release
        and dynamic_false_block < fixed_false_block
    ):
        return "DYNAMIC_FALSE_BLOCK_REDUCTION"
    efficiency_known = (
        fixed.redundant_tool_call_count is not None
        and dynamic.redundant_tool_call_count is not None
    )
    efficiency_better = efficiency_known and (
        int(dynamic.redundant_tool_call_count) < int(fixed.redundant_tool_call_count)
    )
    same_decision_error = (
        dynamic_false_release == fixed_false_release
        and dynamic_false_block == fixed_false_block
    )
    if same_decision_error and efficiency_better:
        return "DYNAMIC_EFFICIENCY_ADVANTAGE"
    if (safety_better and not no_new_block_harm) or (
        dynamic_false_release > fixed_false_release
        and dynamic_false_block < fixed_false_block
    ):
        return "MEASURED_TRADEOFF"
    return "NO_MEASURED_ADVANTAGE"


def build_paired_strategy_comparison_v2_report(
    request: CreatePairedStrategyComparisonV2Request,
) -> PairedStrategyComparisonV2Report:
    overall_fixed = _strategy_summary(
        request.episodes,
        attribute="fixed_observation",
        fallback_strategy=request.baseline_strategy,
    )
    overall_dynamic = _strategy_summary(
        request.episodes,
        attribute="dynamic_observation",
        fallback_strategy="DYNAMIC_EVIDENCE_AGENT",
    )
    complex_episodes = [item for item in request.episodes if item.complex_conflict]
    complex_fixed = _strategy_summary(
        complex_episodes,
        attribute="fixed_observation",
        fallback_strategy=request.baseline_strategy,
    )
    complex_dynamic = _strategy_summary(
        complex_episodes,
        attribute="dynamic_observation",
        fallback_strategy="DYNAMIC_EVIDENCE_AGENT",
    )
    adjudicated_count = sum(
        item.truth.status == "ADJUDICATED" for item in request.episodes
    )
    protocol = _pairing_protocol(request.baseline_strategy)
    fixed_gap = complex_fixed.evidence_gap_coverage_rate.value
    dynamic_gap = complex_dynamic.evidence_gap_coverage_rate.value
    fixed_redundant = complex_fixed.redundant_tool_call_count
    dynamic_redundant = complex_dynamic.redundant_tool_call_count
    stable = {
        "schema_version": "visiondata-gate.paired-strategy-comparison.v2",
        "request": request,
        "request_sha256": _domain_sha256("paired-request", request),
        "pairing_protocol": protocol,
        "pairing_protocol_sha256": _domain_sha256("pairing-protocol", protocol),
        "episodes_sha256": _domain_sha256("paired-episodes", request.episodes),
        "adjudication_coverage_rate": _rate(
            key="adjudication_coverage_rate",
            numerator=adjudicated_count,
            denominator=len(request.episodes),
            unit_of_analysis="paired_governance_episode",
            definition="adjudicated paired episodes / all paired episodes",
            empty_status="NOT_MEASURED",
        ),
        "complex_conflict_episode_count": len(complex_episodes),
        "overall_fixed": overall_fixed,
        "overall_dynamic": overall_dynamic,
        "complex_fixed": complex_fixed,
        "complex_dynamic": complex_dynamic,
        "comparison_deltas": {
            "complex_false_release_count_fixed_minus_dynamic": (
                complex_fixed.confusion["false_release_count"]
                - complex_dynamic.confusion["false_release_count"]
            ),
            "complex_false_block_count_fixed_minus_dynamic": (
                complex_fixed.confusion["false_block_count"]
                - complex_dynamic.confusion["false_block_count"]
            ),
            "complex_evidence_gap_coverage_dynamic_minus_fixed": (
                float(dynamic_gap) - float(fixed_gap)
                if dynamic_gap is not None and fixed_gap is not None
                else None
            ),
            "complex_redundant_calls_fixed_minus_dynamic": (
                int(fixed_redundant) - int(dynamic_redundant)
                if fixed_redundant is not None and dynamic_redundant is not None
                else None
            ),
            "overall_tool_calls_fixed_minus_dynamic": (
                overall_fixed.tool_call_count - overall_dynamic.tool_call_count
            ),
        },
        "complex_conflict_verdict": _complex_verdict(complex_fixed, complex_dynamic),
        "external_competitor_system_executed": False,
        "production_release_allowed": False,
        "claim_boundary": (
            "This report compares two policies implemented inside VisionData Gate under "
            "paired inputs and truth labels. It does not represent an executed external "
            "competitor, industrial model accuracy, customer ROI, or production SLO. "
            "Synthetic results cannot be pooled with private industrial shadow metrics."
        ),
    }
    return PairedStrategyComparisonV2Report(
        **stable,
        report_sha256=_domain_sha256("paired-report", stable),
    )


def verify_paired_strategy_comparison_v2_report(
    report: PairedStrategyComparisonV2Report,
    *,
    allow_legacy_false_block_verdict: bool = False,
) -> None:
    stable = report.model_dump(mode="json", exclude={"report_sha256"})
    observed = _domain_sha256("paired-report", stable)
    if not hmac.compare_digest(observed, report.report_sha256):
        raise ValueError("paired strategy comparison report digest mismatch")
    rebuilt = build_paired_strategy_comparison_v2_report(report.request)
    if canonical_jcs_bytes(rebuilt) != canonical_jcs_bytes(report):
        if (
            allow_legacy_false_block_verdict
            and report.complex_conflict_verdict == "NO_MEASURED_ADVANTAGE"
            and rebuilt.complex_conflict_verdict == "DYNAMIC_FALSE_BLOCK_REDUCTION"
        ):
            legacy_stable = report.model_dump(
                mode="json",
                exclude={"report_sha256", "complex_conflict_verdict"},
            )
            rebuilt_stable = rebuilt.model_dump(
                mode="json",
                exclude={"report_sha256", "complex_conflict_verdict"},
            )
            if canonical_jcs_bytes(legacy_stable) == canonical_jcs_bytes(
                rebuilt_stable
            ):
                return
        raise ValueError("paired strategy comparison failed deterministic replay")


def _system_disposition(terminal_outcome: str) -> SystemDisposition:
    if terminal_outcome == "RELEASE":
        return "RELEASED"
    if terminal_outcome == "RECOVERED_TO_HUMAN_REVIEW":
        return "HUMAN_REVIEW"
    return "BLOCKED"


def _dynamic_bench_observation(
    record: dict[str, Any],
    *,
    strategy: StrategyId,
    required_gap_ids: list[str],
) -> GovernanceStrategyObservationV2:
    dispatched = [str(item) for item in record["dispatched_branches"]]
    covered = sorted(set(dispatched) & set(required_gap_ids))
    unresolved = sorted(set(required_gap_ids) - set(covered))
    dynamic = strategy == "DYNAMIC_EVIDENCE_AGENT"
    replan_count = 1 if dynamic and dispatched else 0
    return GovernanceStrategyObservationV2(
        strategy=strategy,
        system_disposition=_system_disposition(str(record["terminal_outcome"])),
        decision_receipt_sha256=str(record["semantic_sha256"]),
        trace_receipt_sha256=_domain_sha256("dynamic-bench-record", record),
        replan_triggered=replan_count > 0,
        replan_count=replan_count,
        selected_worker_count=len(dispatched),
        selected_worker_ids=dispatched,
        worker_selection_evidence_status=(
            "LEGACY_BENCHMARK_NO_SELECTION_RECEIPT" if dispatched else "NOT_APPLICABLE"
        ),
        detected_evidence_gap_ids=dispatched,
        covered_required_gap_ids=covered,
        unresolved_required_gap_ids=unresolved,
        tool_call_count=int(record["tool_call_count"]),
        redundant_tool_call_count=int(record["redundant_or_duplicate_tool_call_count"]),
        latency_ms=float(record["latency_ms"]),
        actual_model_call_count=int(record["actual_model_call_count"]),
        actual_model_token_count=int(record["actual_model_token_count"]),
        provider_billed_api_cost_cny=float(record["provider_billed_api_cost_cny"]),
    )


def build_paired_comparison_from_dynamic_benchmark(
    benchmark_path: str | Path,
    *,
    evaluated_at: str,
    baseline_architecture: Literal[
        "traditional_pipeline", "fixed_multi_agent"
    ] = "traditional_pipeline",
) -> PairedStrategyComparisonV2Report:
    """Translate a fully replay-validated DynamicBench-v1 report into pairs."""

    path = Path(benchmark_path).expanduser().resolve(strict=True)
    benchmark = load_dynamic_benchmark_report(path)
    fixtures = {item["fixture_id"]: item for item in benchmark["fixture_manifest"]}
    primary = {
        (item["architecture"], item["fixture_id"]): item
        for item in benchmark["records"]
        if item["repeat"] == 1
    }
    episodes: list[PairedGovernanceEpisodeV2] = []
    for fixture_id in sorted(fixtures):
        fixture = fixtures[fixture_id]
        required = [str(item) for item in fixture["expected_trigger_branches"]]
        conflict_tags: list[str] = []
        if "cross_tool_conflict_adjudication" in required:
            conflict_tags.append("cross_tool_action_conflict")
        if len(required) >= 2:
            conflict_tags.append("multi_signal_conflict")
        fixed_record = primary[(baseline_architecture, fixture_id)]
        dynamic_record = primary[(DynamicArchitecture.DYNAMIC_LEADER.value, fixture_id)]
        truth: TruthDisposition = (
            "RELEASE_ALLOWED"
            if fixture["expected_terminal_outcome"] == "RELEASE"
            else "BLOCK_REQUIRED"
        )
        episodes.append(
            PairedGovernanceEpisodeV2(
                episode_id=f"dynamic-bench-v1-{fixture_id}",
                source_scope="SYNTHETIC_FIXED_FIXTURE",
                input_contract_sha256=benchmark["protocol_sha256"],
                input_manifest_sha256=_domain_sha256(
                    "dynamic-bench-fixture-input",
                    {
                        "signals": fixture["signals"],
                        "perturbations": fixture["perturbations"],
                    },
                ),
                truth=GovernanceTruthBindingV2(
                    status="ADJUDICATED",
                    disposition=truth,
                    method="FROZEN_SYNTHETIC_FIXTURE",
                    adjudication_receipt_sha256=_domain_sha256(
                        "dynamic-bench-fixture-truth", fixture
                    ),
                ),
                required_evidence_gap_ids=required,
                conflict_tags=conflict_tags,
                complex_conflict=_complex_conflict_expected(conflict_tags, required),
                fixed_observation=_dynamic_bench_observation(
                    fixed_record,
                    strategy=(
                        "FIXED_RULE_PIPELINE"
                        if baseline_architecture == "traditional_pipeline"
                        else "FIXED_EXHAUSTIVE_PIPELINE"
                    ),
                    required_gap_ids=required,
                ),
                dynamic_observation=_dynamic_bench_observation(
                    dynamic_record,
                    strategy="DYNAMIC_EVIDENCE_AGENT",
                    required_gap_ids=required,
                ),
            )
        )
    request = CreatePairedStrategyComparisonV2Request(
        comparison_id=(
            "dynamic-bench-v1-fixed-rule-vs-dynamic"
            if baseline_architecture == "traditional_pipeline"
            else "dynamic-bench-v1-fixed-exhaustive-vs-dynamic"
        ),
        source_scope="SYNTHETIC_FIXED_FIXTURE",
        baseline_strategy=(
            "FIXED_RULE_PIPELINE"
            if baseline_architecture == "traditional_pipeline"
            else "FIXED_EXHAUSTIVE_PIPELINE"
        ),
        dataset_identity_sha256=benchmark["fixture_manifest_sha256"],
        source_benchmark_sha256=sha256_file(path),
        episodes=episodes,
        evaluated_at=evaluated_at,
        note=(
            "Frozen deterministic orchestration fixtures; not industrial accuracy "
            "and not an external competitor execution."
        ),
    )
    return build_paired_strategy_comparison_v2_report(request)


def _load_json_object(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise ValueError(f"evidence receipt is unreadable: {path.name}") from error
    if not isinstance(value, dict):
        raise ValueError(f"evidence receipt must be an object: {path.name}")
    return value


def build_omni_rc3_governance_effectiveness_report(
    *,
    product_pilot_receipt_path: str | Path,
    capa_pilot_receipt_path: str | Path,
    expected_product_receipt_sha256: str,
    expected_capa_receipt_sha256: str,
    evaluated_at: str,
) -> GovernanceEffectivenessV2Report:
    """Build the current private Omni receipt without inventing missing truth.

    The parent Gate decision has no batch/case adjudication manifest in the RC3
    evidence set, so false-release and false-block rates remain NOT_MEASURED.
    The completed child Run is a real independent remediation recheck and is
    therefore counted as VERIFIED_PASS or VERIFIED_FAIL.
    """

    product_path = Path(product_pilot_receipt_path).expanduser().resolve(strict=True)
    capa_path = Path(capa_pilot_receipt_path).expanduser().resolve(strict=True)
    product_sha = sha256_file(product_path)
    capa_sha = sha256_file(capa_path)
    if not hmac.compare_digest(product_sha, expected_product_receipt_sha256):
        raise ValueError("authorized product pilot receipt SHA-256 mismatch")
    if not hmac.compare_digest(capa_sha, expected_capa_receipt_sha256):
        raise ValueError("authorized CAPA pilot receipt SHA-256 mismatch")
    product = _load_json_object(product_path)
    capa = _load_json_object(capa_path)
    if not (
        product.get("schema_version") == "visiondata-gate.authorized-product-pilot.v2"
        and product.get("source_path_serialized") is False
        and product.get("source_assets_copied_into_product") is False
        and product.get("task_id") == capa.get("parent_task_id")
        and product.get("evidence_sha256") == capa.get("parent_evidence_sha256")
        and capa.get("schema_version") == "visiondata-gate.authorized-capa-pilot.v1"
        and capa.get("parent_immutable") is True
        and capa.get("parent_source_mutated") is False
        and capa.get("production_release_allowed") is False
        and capa.get("actual_model_call_count") == 0
    ):
        raise ValueError("Omni RC3 evidence receipts failed semantic binding checks")

    final_decision = str(product.get("final_decision"))
    decision_disposition: SystemDisposition = (
        "RELEASED" if final_decision == "PASS" else "BLOCKED"
    )
    decision_unit = GovernanceDecisionUnitV2(
        unit_id="omni-rc3-parent-gate",
        source_scope="PRIVATE_AUTHORIZED_SHADOW",
        input_contract_sha256=str(product["plan_sha256"]),
        input_manifest_sha256=str(product["source_profile_sha256"]),
        truth=GovernanceTruthBindingV2(
            status="PENDING_ADJUDICATION",
            pending_reason=(
                "RC3 has no independent batch-level QMS or dual-human disposition "
                "manifest bound to this Gate decision."
            ),
        ),
        required_evidence_gap_ids=[],
        conflict_tags=[],
        complex_conflict=False,
        observation=GovernanceStrategyObservationV2(
            strategy="DYNAMIC_EVIDENCE_AGENT",
            system_disposition=decision_disposition,
            decision_receipt_sha256=product_sha,
            trace_receipt_sha256=str(product["evidence_sha256"]),
            replan_triggered=int(product.get("replan_count", 0)) > 0,
            replan_count=int(product.get("replan_count", 0)),
            selected_worker_count=int(product.get("dynamic_task_count", 0)),
            selected_worker_ids=[],
            worker_selection_evidence_status="SUMMARY_ONLY_NO_WORKER_IDS",
            detected_evidence_gap_ids=[],
            covered_required_gap_ids=[],
            unresolved_required_gap_ids=[],
            tool_call_count=int(product.get("tool_trace_count", 0)),
            redundant_tool_call_count=None,
            latency_ms=None,
            actual_model_call_count=int(capa["actual_model_call_count"]),
            actual_model_token_count=0,
            provider_billed_api_cost_cny=0.0,
        ),
    )
    child_complete = capa.get("completion_state") == "CAPA_CHILD_RUN_COMPLETED"
    recovery_success = capa.get("recovery_success") is True
    if child_complete:
        remediation_outcome: Literal[
            "VERIFIED_PASS", "VERIFIED_FAIL", "PENDING_RECHECK"
        ] = "VERIFIED_PASS" if recovery_success else "VERIFIED_FAIL"
    else:
        remediation_outcome = "PENDING_RECHECK"
    remediation = GovernanceRemediationUnitV2(
        remediation_id="omni-rc3-capa-child-run",
        source_scope="PRIVATE_AUTHORIZED_SHADOW",
        parent_unit_id=decision_unit.unit_id,
        verification_contract_sha256=str(capa["capa_approval_binding_sha256"]),
        parent_decision_receipt_sha256=product_sha,
        child_decision_receipt_sha256=(
            str(capa["child_evidence_sha256"]) if child_complete else None
        ),
        lineage_receipt_sha256=(
            str(capa["lineage_report_sha256"]) if child_complete else None
        ),
        named_approval_binding_sha256=(
            str(capa["capa_approval_binding_sha256"]) if child_complete else None
        ),
        outcome=remediation_outcome,
        independent_recheck_performed=child_complete,
    )
    request = CreateGovernanceEffectivenessV2Request(
        evaluation_id="omni-rc3-authorized-shadow",
        source_scope="PRIVATE_AUTHORIZED_SHADOW",
        evaluated_strategy="DYNAMIC_EVIDENCE_AGENT",
        dataset_identity_sha256=str(product["source_profile_sha256"]),
        source_authorization_binding_sha256=str(product["source_registry_sha256"]),
        decision_units=[decision_unit],
        remediation_units=[remediation],
        evaluated_at=evaluated_at,
        note=(
            "Authorized private Omni shadow evidence. Parent disposition truth remains "
            "pending; the completed child Run is counted as one remediation recheck."
        ),
        operator_attests_authorized_use=True,
    )
    return build_governance_effectiveness_v2_report(request)


def write_governance_v2_report(
    path: str | Path,
    report: GovernanceEffectivenessV2Report | PairedStrategyComparisonV2Report,
) -> Path:
    output = Path(path).expanduser().resolve()
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_bytes(canonical_jcs_bytes(report) + b"\n")
    return output


__all__ = [
    "CreateGovernanceEffectivenessV2Request",
    "CreatePairedStrategyComparisonV2Request",
    "GovernanceDecisionUnitV2",
    "GovernanceEffectivenessV2Report",
    "GovernanceRateEstimateV2",
    "GovernanceRemediationUnitV2",
    "GovernanceStrategyObservationV2",
    "GovernanceTruthBindingV2",
    "PairedGovernanceEpisodeV2",
    "PairedStrategyComparisonV2Report",
    "PairedStrategySummaryV2",
    "build_governance_effectiveness_v2_report",
    "build_omni_rc3_governance_effectiveness_report",
    "build_paired_comparison_from_dynamic_benchmark",
    "build_paired_strategy_comparison_v2_report",
    "verify_governance_effectiveness_v2_report",
    "verify_paired_strategy_comparison_v2_report",
    "write_governance_v2_report",
]
