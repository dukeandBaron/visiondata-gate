"""Governance-effectiveness contracts for authorized offline shadow evaluation.

This module is deliberately outside the production Agent core.  It consumes a
completed, immutable task and an operator-reviewed label summary after the run;
it never feeds benchmark labels back into planning, tools, or the frozen Judge.
"""

from __future__ import annotations

import hashlib
import hmac
from collections import defaultdict
from collections.abc import Mapping, Sequence
from datetime import datetime
from enum import Enum
from typing import Any, Literal

from pydantic import BaseModel, Field, field_validator, model_validator
import rfc8785

from .evidence import canonical_json_bytes
from .product_models import ProductModel


MetricStatus = Literal["MEASURED", "NOT_MEASURED", "NOT_APPLICABLE"]
GovernanceMetricKey = Literal[
    "false_release_rate",
    "false_block_rate",
    "verified_remediation_pass_rate",
    "unresolved_remediation_rate",
]
ShadowTruthDisposition = Literal["BLOCK", "RELEASE"]
ShadowGateDisposition = Literal["BLOCK", "RELEASE"]
ShadowRemediationOutcome = Literal[
    "NOT_APPLICABLE",
    "UNRESOLVED",
    "VERIFIED_PASS",
    "VERIFIED_FAIL",
]


SHADOW_V2_HASH_ALGORITHM = "sha256"
SHADOW_V2_CANONICALIZATION_PROFILE = "rfc8785-jcs-v1"
SHADOW_V2_FRAMING_PROFILE = "visiondata-gate-shadow-v2-domain-frame-v1"
SHADOW_V2_FRAME_MAGIC = b"visiondata-gate.shadow-v2-hash-frame.v1\x00"
SHADOW_V2_FRAME_MAGIC_UTF8 = "visiondata-gate.shadow-v2-hash-frame.v1\\u0000"
SHADOW_V2_FRAME_CONSTRUCTION = (
    "magic || uint16be(domain_length) || domain || "
    "uint64be(payload_length) || rfc8785_payload"
)


class ShadowV2HashDomain(str, Enum):
    """Closed, non-interchangeable semantic domains for Shadow V2 digests."""

    TRUTH_MANIFEST = "visiondata-gate/shadow-v2/truth-manifest/v2"
    GATE_MANIFEST = "visiondata-gate/shadow-v2/gate-manifest/v2"
    REMEDIATION_MANIFEST = "visiondata-gate/shadow-v2/remediation-manifest/v2"
    EVALUATION_MANIFEST = "visiondata-gate/shadow-v2/evaluation-manifest/v2"
    REQUEST = "visiondata-gate/shadow-v2/request/v2"
    SOURCE_TASK_BINDING = "visiondata-gate/shadow-v2/source-task-binding/v2"
    RECEIPT = "visiondata-gate/shadow-v2/receipt/v2"


def _shadow_v2_json_value(value: Any) -> Any:
    """Convert supported values into the exact RFC 8785 JSON data model."""

    if isinstance(value, BaseModel):
        return _shadow_v2_json_value(value.model_dump(mode="json"))
    if isinstance(value, Enum):
        return _shadow_v2_json_value(value.value)
    if isinstance(value, Mapping):
        normalized: dict[str, Any] = {}
        for key, item in value.items():
            if not isinstance(key, str):
                raise TypeError("RFC 8785 objects require string property names")
            normalized[key] = _shadow_v2_json_value(item)
        return normalized
    if isinstance(value, Sequence) and not isinstance(
        value, (str, bytes, bytearray, memoryview)
    ):
        return [_shadow_v2_json_value(item) for item in value]
    if value is None or isinstance(value, (bool, int, float, str)):
        return value
    raise TypeError(
        f"unsupported RFC 8785 canonical JSON value: {type(value).__name__}"
    )


def _shadow_v2_canonical_jcs_bytes(value: Any) -> bytes:
    """Return strict RFC 8785 JCS bytes without a transport newline."""

    try:
        return rfc8785.dumps(_shadow_v2_json_value(value))
    except (rfc8785.CanonicalizationError, TypeError, UnicodeError) as error:
        raise ValueError(
            f"shadow v2 value cannot be canonicalized with RFC 8785: {error}"
        ) from error


def _shadow_v2_domain_frame(payload: bytes, domain: ShadowV2HashDomain) -> bytes:
    """Build an injective frame over magic, domain and canonical payload bytes."""

    domain_bytes = domain.value.encode("utf-8")
    if len(domain_bytes) > 0xFFFF:
        raise ValueError("shadow v2 hash domain is too long")
    if len(payload) > 0xFFFFFFFFFFFFFFFF:
        raise ValueError("shadow v2 canonical payload is too long")
    return b"".join(
        (
            SHADOW_V2_FRAME_MAGIC,
            len(domain_bytes).to_bytes(2, "big"),
            domain_bytes,
            len(payload).to_bytes(8, "big"),
            payload,
        )
    )


def shadow_v2_domain_separated_sha256(
    value: Any,
    domain: ShadowV2HashDomain,
) -> str:
    """Hash one JCS value in a fixed, length-prefixed Shadow V2 domain frame."""

    payload = _shadow_v2_canonical_jcs_bytes(value)
    frame = _shadow_v2_domain_frame(payload, domain)
    return hashlib.sha256(frame).hexdigest()


def _aware_timestamp(value: str, *, field_name: str) -> datetime:
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as error:
        raise ValueError(f"{field_name} must be ISO-8601") from error
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ValueError(f"{field_name} must include an explicit UTC offset")
    return parsed


class IndustrialShadowBatchIdentity(ProductModel):
    """Pseudonymous factory/batch identity; customer names are not required."""

    dataset_namespace: str = Field(min_length=2, max_length=120)
    site_alias: str = Field(min_length=2, max_length=120)
    line_alias: str = Field(min_length=2, max_length=120)
    station_alias: str = Field(min_length=2, max_length=120)
    camera_alias: str = Field(min_length=2, max_length=120)
    batch_alias: str = Field(min_length=2, max_length=160)
    captured_from: str
    captured_to: str

    @field_validator(
        "dataset_namespace",
        "site_alias",
        "line_alias",
        "station_alias",
        "camera_alias",
        "batch_alias",
    )
    @classmethod
    def reject_path_like_aliases(cls, value: str) -> str:
        if any(character in value for character in ("/", "\\", "\0", "\r", "\n")):
            raise ValueError("shadow identity aliases cannot contain paths or controls")
        return value

    @model_validator(mode="after")
    def validate_capture_window(self) -> IndustrialShadowBatchIdentity:
        start = _aware_timestamp(self.captured_from, field_name="captured_from")
        end = _aware_timestamp(self.captured_to, field_name="captured_to")
        if end < start:
            raise ValueError("captured_to must not precede captured_from")
        return self


class ShadowConfusionCounts(ProductModel):
    """Mutually exclusive labelled units at one explicitly declared grain."""

    unit_of_analysis: str = Field(min_length=2, max_length=120)
    true_block_count: int = Field(ge=0)
    false_release_count: int = Field(ge=0)
    true_release_count: int = Field(ge=0)
    false_block_count: int = Field(ge=0)

    @property
    def labelled_unit_count(self) -> int:
        return (
            self.true_block_count
            + self.false_release_count
            + self.true_release_count
            + self.false_block_count
        )

    @model_validator(mode="after")
    def require_labelled_denominator(self) -> ShadowConfusionCounts:
        if self.labelled_unit_count < 1:
            raise ValueError("shadow evaluation requires at least one labelled unit")
        return self


class ShadowRemediationCounts(ProductModel):
    """Same-contract, independently rechecked remediation outcomes."""

    verified_pass_count: int = Field(default=0, ge=0)
    verified_fail_count: int = Field(default=0, ge=0)
    unresolved_count: int = Field(default=0, ge=0)

    @property
    def verified_count(self) -> int:
        return self.verified_pass_count + self.verified_fail_count

    @property
    def attempted_count(self) -> int:
        return self.verified_count + self.unresolved_count


class CreateIndustrialShadowEvaluationRequest(ProductModel):
    """Operator attestation bound to external truth and Gate-output manifests."""

    identity: IndustrialShadowBatchIdentity
    ground_truth_method: Literal[
        "quality_owner_adjudication",
        "dual_human_adjudication",
        "existing_qms_disposition",
    ]
    truth_manifest_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    gate_output_manifest_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    confusion: ShadowConfusionCounts
    remediation: ShadowRemediationCounts = Field(
        default_factory=ShadowRemediationCounts
    )
    note: str = Field(min_length=8, max_length=2000)
    operator_attests_authorized_historical_use: Literal[True]
    operator_attests_labels_reviewed: Literal[True]
    read_only_shadow: Literal[True] = True
    raw_images_transmitted: Literal[False] = False
    machine_write_permitted: Literal[False] = False


class GovernanceRateMetric(ProductModel):
    key: GovernanceMetricKey
    label: str = Field(min_length=1)
    status: MetricStatus
    numerator: int = Field(ge=0)
    denominator: int = Field(ge=0)
    value: float | None = Field(default=None, ge=0.0, le=1.0)
    unit: Literal["ratio"] = "ratio"
    unit_of_analysis: str = Field(min_length=1)
    target: str = Field(min_length=1)
    definition: str = Field(min_length=1)
    source_ref: str = Field(min_length=1)

    @model_validator(mode="after")
    def validate_ratio_contract(self) -> GovernanceRateMetric:
        if self.denominator == 0:
            if self.numerator != 0 or self.value is not None:
                raise ValueError(
                    "zero-denominator metric cannot carry a measured value"
                )
            if self.status == "MEASURED":
                raise ValueError("zero-denominator metric cannot be MEASURED")
            return self
        if self.numerator > self.denominator:
            raise ValueError("metric numerator cannot exceed denominator")
        expected = self.numerator / self.denominator
        if self.status != "MEASURED" or self.value is None:
            raise ValueError("non-zero denominator requires a measured metric")
        if abs(self.value - expected) > 1e-12:
            raise ValueError("metric value does not match numerator / denominator")
        return self


class ShadowEvaluationUnitV2(ProductModel):
    """One pseudonymous unit with independently bound truth and Gate evidence."""

    unit_id: str = Field(pattern=r"^unit_[0-9a-f]{16,64}$")
    truth_disposition: ShadowTruthDisposition
    gate_disposition: ShadowGateDisposition
    truth_evidence_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    gate_evidence_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    remediation_outcome: ShadowRemediationOutcome = "NOT_APPLICABLE"
    remediation_evidence_sha256: str | None = Field(
        default=None,
        pattern=r"^[0-9a-f]{64}$",
    )

    @model_validator(mode="after")
    def validate_remediation_evidence(self) -> ShadowEvaluationUnitV2:
        if self.remediation_outcome == "NOT_APPLICABLE":
            if self.remediation_evidence_sha256 is not None:
                raise ValueError("NOT_APPLICABLE remediation cannot carry evidence")
        elif self.remediation_evidence_sha256 is None:
            raise ValueError(
                "non-NOT_APPLICABLE remediation requires an evidence digest"
            )
        return self


class CreateShadowEvaluationManifestV2Request(ProductModel):
    """Per-unit shadow labels; aggregate counts are intentionally not accepted."""

    identity: IndustrialShadowBatchIdentity
    unit_of_analysis: str = Field(min_length=2, max_length=120)
    ground_truth_method: Literal[
        "quality_owner_adjudication",
        "dual_human_adjudication",
        "existing_qms_disposition",
    ]
    units: list[ShadowEvaluationUnitV2] = Field(min_length=1, max_length=10_000)
    note: str = Field(min_length=8, max_length=2000)
    operator_attests_authorized_historical_use: Literal[True]
    operator_attests_labels_reviewed: Literal[True]
    read_only_shadow: Literal[True] = True
    raw_images_transmitted: Literal[False] = False
    machine_write_permitted: Literal[False] = False

    @model_validator(mode="after")
    def reject_duplicate_units(self) -> CreateShadowEvaluationManifestV2Request:
        unit_ids = [item.unit_id for item in self.units]
        if len(unit_ids) != len(set(unit_ids)):
            raise ValueError("shadow v2 unit IDs must be unique")
        return self


def _sorted_shadow_v2_units(
    units: Sequence[ShadowEvaluationUnitV2],
) -> list[ShadowEvaluationUnitV2]:
    return sorted(units, key=lambda item: item.unit_id)


def _shadow_v2_manifest_digests(
    *,
    unit_of_analysis: str,
    units: Sequence[ShadowEvaluationUnitV2],
) -> tuple[str, str, str, str]:
    ordered = _sorted_shadow_v2_units(units)
    truth_rows = [
        {
            "unit_id": item.unit_id,
            "truth_disposition": item.truth_disposition,
            "truth_evidence_sha256": item.truth_evidence_sha256,
        }
        for item in ordered
    ]
    gate_rows = [
        {
            "unit_id": item.unit_id,
            "gate_disposition": item.gate_disposition,
            "gate_evidence_sha256": item.gate_evidence_sha256,
        }
        for item in ordered
    ]
    remediation_rows = [
        {
            "unit_id": item.unit_id,
            "remediation_outcome": item.remediation_outcome,
            "remediation_evidence_sha256": item.remediation_evidence_sha256,
        }
        for item in ordered
    ]
    evaluation_rows = [item.model_dump(mode="json") for item in ordered]
    truth_sha256 = shadow_v2_domain_separated_sha256(
        {
            "schema_version": "visiondata-gate.shadow-truth-manifest.v2",
            "unit_of_analysis": unit_of_analysis,
            "units": truth_rows,
        },
        ShadowV2HashDomain.TRUTH_MANIFEST,
    )
    gate_sha256 = shadow_v2_domain_separated_sha256(
        {
            "schema_version": "visiondata-gate.shadow-gate-manifest.v2",
            "unit_of_analysis": unit_of_analysis,
            "units": gate_rows,
        },
        ShadowV2HashDomain.GATE_MANIFEST,
    )
    remediation_sha256 = shadow_v2_domain_separated_sha256(
        {
            "schema_version": "visiondata-gate.shadow-remediation-manifest.v2",
            "unit_of_analysis": unit_of_analysis,
            "units": remediation_rows,
        },
        ShadowV2HashDomain.REMEDIATION_MANIFEST,
    )
    evaluation_sha256 = shadow_v2_domain_separated_sha256(
        {
            "schema_version": "visiondata-gate.shadow-evaluation-manifest.v2",
            "unit_of_analysis": unit_of_analysis,
            "units": evaluation_rows,
        },
        ShadowV2HashDomain.EVALUATION_MANIFEST,
    )
    return (
        evaluation_sha256,
        truth_sha256,
        gate_sha256,
        remediation_sha256,
    )


def _shadow_v2_counts(
    *,
    unit_of_analysis: str,
    units: Sequence[ShadowEvaluationUnitV2],
) -> tuple[ShadowConfusionCounts, ShadowRemediationCounts]:
    true_block_count = 0
    false_release_count = 0
    true_release_count = 0
    false_block_count = 0
    verified_pass_count = 0
    verified_fail_count = 0
    unresolved_count = 0
    for item in units:
        if item.truth_disposition == "BLOCK":
            if item.gate_disposition == "BLOCK":
                true_block_count += 1
            else:
                false_release_count += 1
        elif item.gate_disposition == "RELEASE":
            true_release_count += 1
        else:
            false_block_count += 1

        if item.remediation_outcome == "VERIFIED_PASS":
            verified_pass_count += 1
        elif item.remediation_outcome == "VERIFIED_FAIL":
            verified_fail_count += 1
        elif item.remediation_outcome == "UNRESOLVED":
            unresolved_count += 1

    return (
        ShadowConfusionCounts(
            unit_of_analysis=unit_of_analysis,
            true_block_count=true_block_count,
            false_release_count=false_release_count,
            true_release_count=true_release_count,
            false_block_count=false_block_count,
        ),
        ShadowRemediationCounts(
            verified_pass_count=verified_pass_count,
            verified_fail_count=verified_fail_count,
            unresolved_count=unresolved_count,
        ),
    )


class IndustrialShadowEvaluationReceipt(ProductModel):
    """Immutable, hash-sealed receipt for one authorized historical shadow slice."""

    schema_version: Literal["visiondata-gate.industrial-shadow-evaluation.v1"] = (
        "visiondata-gate.industrial-shadow-evaluation.v1"
    )
    receipt_id: str = Field(pattern=r"^shadow_[0-9a-f]{20}$")
    request_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    workspace_id: str = Field(min_length=1)
    project_id: str = Field(min_length=1)
    task_id: str = Field(min_length=1)
    source_id: str = Field(min_length=1)
    source_authorization_event_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    task_request_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    task_evidence_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    task_final_decision: str = Field(min_length=1)
    identity: IndustrialShadowBatchIdentity
    evidence_scope: Literal["OPERATOR_ATTESTED_AUTHORIZED_HISTORICAL_SHADOW"] = (
        "OPERATOR_ATTESTED_AUTHORIZED_HISTORICAL_SHADOW"
    )
    label_authority: Literal["OPERATOR_REVIEWED_EXTERNAL_MANIFEST"] = (
        "OPERATOR_REVIEWED_EXTERNAL_MANIFEST"
    )
    ground_truth_method: Literal[
        "quality_owner_adjudication",
        "dual_human_adjudication",
        "existing_qms_disposition",
    ]
    truth_manifest_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    gate_output_manifest_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    labelled_unit_count: int = Field(ge=1)
    confusion: ShadowConfusionCounts
    remediation: ShadowRemediationCounts
    false_release_rate: GovernanceRateMetric
    false_block_rate: GovernanceRateMetric
    verified_remediation_pass_rate: GovernanceRateMetric
    unresolved_remediation_rate: GovernanceRateMetric
    measurement_status: Literal["MEASURED", "PARTIAL_MEASUREMENT"]
    note: str = Field(min_length=8, max_length=2000)
    created_by: str = Field(min_length=1)
    created_at: str
    read_only_shadow: Literal[True] = True
    raw_images_transmitted: Literal[False] = False
    machine_write_permitted: Literal[False] = False
    customer_acceptance_claimed: Literal[False] = False
    production_release_allowed: Literal[False] = False
    claim_boundary: str = (
        "This receipt records an operator-attested, read-only historical shadow "
        "evaluation bound to labelled-summary manifests and one immutable local task. "
        "It is not independent customer acceptance, online factory deployment, legal "
        "ownership proof, model certification, or production authorization."
    )
    receipt_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")

    @model_validator(mode="after")
    def validate_metric_bindings(self) -> IndustrialShadowEvaluationReceipt:
        _aware_timestamp(self.created_at, field_name="created_at")
        if self.receipt_id != f"shadow_{self.request_sha256[:20]}":
            raise ValueError("shadow receipt ID does not match request digest")
        if self.labelled_unit_count != self.confusion.labelled_unit_count:
            raise ValueError("shadow labelled-unit count does not reconcile")
        expected_keys = {
            "false_release_rate": self.false_release_rate,
            "false_block_rate": self.false_block_rate,
            "verified_remediation_pass_rate": self.verified_remediation_pass_rate,
            "unresolved_remediation_rate": self.unresolved_remediation_rate,
        }
        if any(metric.key != key for key, metric in expected_keys.items()):
            raise ValueError("shadow metric is bound to the wrong field")
        expected_counts = {
            "false_release_rate": (
                self.confusion.false_release_count,
                self.confusion.true_block_count + self.confusion.false_release_count,
            ),
            "false_block_rate": (
                self.confusion.false_block_count,
                self.confusion.true_release_count + self.confusion.false_block_count,
            ),
            "verified_remediation_pass_rate": (
                self.remediation.verified_pass_count,
                self.remediation.verified_count,
            ),
            "unresolved_remediation_rate": (
                self.remediation.unresolved_count,
                self.remediation.attempted_count,
            ),
        }
        for key, metric in expected_keys.items():
            if (metric.numerator, metric.denominator) != expected_counts[key]:
                raise ValueError(f"shadow {key} counts do not reconcile")
        primary = (
            self.false_release_rate,
            self.false_block_rate,
            self.verified_remediation_pass_rate,
        )
        expected_status = (
            "MEASURED"
            if all(metric.status == "MEASURED" for metric in primary)
            else "PARTIAL_MEASUREMENT"
        )
        if self.measurement_status != expected_status:
            raise ValueError("shadow measurement status does not match metric coverage")
        return self


class ShadowEvaluationManifestV2(ProductModel):
    """Immutable per-unit manifest with server-derived governance metrics."""

    schema_version: Literal["visiondata-gate.shadow-evaluation-manifest.v2"] = (
        "visiondata-gate.shadow-evaluation-manifest.v2"
    )
    hash_algorithm: Literal["sha256"] = SHADOW_V2_HASH_ALGORITHM
    canonicalization_profile: Literal["rfc8785-jcs-v1"] = (
        SHADOW_V2_CANONICALIZATION_PROFILE
    )
    framing_profile: Literal["visiondata-gate-shadow-v2-domain-frame-v1"] = (
        SHADOW_V2_FRAMING_PROFILE
    )
    frame_construction: Literal[
        "magic || uint16be(domain_length) || domain || "
        "uint64be(payload_length) || rfc8785_payload"
    ] = SHADOW_V2_FRAME_CONSTRUCTION
    frame_magic_utf8: Literal["visiondata-gate.shadow-v2-hash-frame.v1\\u0000"] = (
        SHADOW_V2_FRAME_MAGIC_UTF8
    )
    receipt_id: str = Field(pattern=r"^shadowv2_[0-9a-f]{20}$")
    request_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    workspace_id: str = Field(min_length=1)
    project_id: str = Field(min_length=1)
    task_id: str = Field(min_length=1)
    source_id: str = Field(min_length=1)
    source_authorization_event_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    task_request_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    task_evidence_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    task_final_decision: str = Field(min_length=1)
    source_task_binding_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    identity: IndustrialShadowBatchIdentity
    unit_of_analysis: str = Field(min_length=2, max_length=120)
    units: list[ShadowEvaluationUnitV2] = Field(min_length=1, max_length=10_000)
    labelled_unit_count: int = Field(ge=1)
    evaluation_manifest_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    truth_manifest_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    gate_output_manifest_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    remediation_manifest_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    evidence_scope: Literal["PER_UNIT_AUTHORIZED_HISTORICAL_SHADOW"] = (
        "PER_UNIT_AUTHORIZED_HISTORICAL_SHADOW"
    )
    label_authority: Literal["OPERATOR_REVIEWED_PER_UNIT_EXTERNAL_EVIDENCE"] = (
        "OPERATOR_REVIEWED_PER_UNIT_EXTERNAL_EVIDENCE"
    )
    aggregation_authority: Literal[
        "VISIONDATA_GATE_SERVER_DERIVED_FROM_PER_UNIT_RECORDS"
    ] = "VISIONDATA_GATE_SERVER_DERIVED_FROM_PER_UNIT_RECORDS"
    ground_truth_method: Literal[
        "quality_owner_adjudication",
        "dual_human_adjudication",
        "existing_qms_disposition",
    ]
    confusion: ShadowConfusionCounts
    remediation: ShadowRemediationCounts
    false_release_rate: GovernanceRateMetric
    false_block_rate: GovernanceRateMetric
    verified_remediation_pass_rate: GovernanceRateMetric
    unresolved_remediation_rate: GovernanceRateMetric
    measurement_status: Literal["MEASURED", "PARTIAL_MEASUREMENT"]
    server_computed_counts: Literal[True] = True
    client_supplied_aggregate_counts_accepted: Literal[False] = False
    note: str = Field(min_length=8, max_length=2000)
    operator_attests_authorized_historical_use: Literal[True]
    operator_attests_labels_reviewed: Literal[True]
    created_by: str = Field(min_length=1)
    created_at: str
    read_only_shadow: Literal[True] = True
    raw_images_transmitted: Literal[False] = False
    machine_write_permitted: Literal[False] = False
    shadow_labels_enter_agent_core: Literal[False] = False
    customer_acceptance_claimed: Literal[False] = False
    production_release_allowed: Literal[False] = False
    claim_boundary: str = (
        "This receipt derives aggregate counts only from the included pseudonymous "
        "per-unit records and binds them to immutable local task and source digests. "
        "The underlying truth, Gate and remediation evidence remains operator-reviewed "
        "external evidence; this is not independent customer acceptance, online factory "
        "deployment, production authorization, a digital signature, or a trusted "
        "timestamp."
    )
    receipt_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")

    @model_validator(mode="after")
    def validate_server_derived_manifest(self) -> ShadowEvaluationManifestV2:
        _aware_timestamp(self.created_at, field_name="created_at")
        if self.receipt_id != f"shadowv2_{self.request_sha256[:20]}":
            raise ValueError("shadow v2 receipt ID does not match request digest")
        unit_ids = [item.unit_id for item in self.units]
        if unit_ids != sorted(unit_ids):
            raise ValueError("shadow v2 units must use canonical unit-ID order")
        if len(unit_ids) != len(set(unit_ids)):
            raise ValueError("shadow v2 unit IDs must be unique")
        if self.labelled_unit_count != len(self.units):
            raise ValueError("shadow v2 labelled-unit count does not reconcile")

        manifest_digests = _shadow_v2_manifest_digests(
            unit_of_analysis=self.unit_of_analysis,
            units=self.units,
        )
        observed_digests = (
            self.evaluation_manifest_sha256,
            self.truth_manifest_sha256,
            self.gate_output_manifest_sha256,
            self.remediation_manifest_sha256,
        )
        if manifest_digests != observed_digests:
            raise ValueError("shadow v2 derived manifest digest mismatch")

        confusion, remediation = _shadow_v2_counts(
            unit_of_analysis=self.unit_of_analysis,
            units=self.units,
        )
        if self.confusion != confusion:
            raise ValueError("shadow v2 server-derived confusion counts mismatch")
        if self.remediation != remediation:
            raise ValueError("shadow v2 server-derived remediation counts mismatch")

        expected_metrics = {
            "false_release_rate": (
                self.false_release_rate,
                confusion.false_release_count,
                confusion.true_block_count + confusion.false_release_count,
            ),
            "false_block_rate": (
                self.false_block_rate,
                confusion.false_block_count,
                confusion.true_release_count + confusion.false_block_count,
            ),
            "verified_remediation_pass_rate": (
                self.verified_remediation_pass_rate,
                remediation.verified_pass_count,
                remediation.verified_count,
            ),
            "unresolved_remediation_rate": (
                self.unresolved_remediation_rate,
                remediation.unresolved_count,
                remediation.attempted_count,
            ),
        }
        expected_source_ref = shadow_v2_source_ref(
            evaluation_manifest_sha256=self.evaluation_manifest_sha256,
            truth_manifest_sha256=self.truth_manifest_sha256,
            gate_output_manifest_sha256=self.gate_output_manifest_sha256,
            remediation_manifest_sha256=self.remediation_manifest_sha256,
            task_evidence_sha256=self.task_evidence_sha256,
        )
        for key, (metric, numerator, denominator) in expected_metrics.items():
            if metric.key != key:
                raise ValueError("shadow v2 metric is bound to the wrong field")
            if (metric.numerator, metric.denominator) != (numerator, denominator):
                raise ValueError(f"shadow v2 {key} counts do not reconcile")
            if metric.source_ref != expected_source_ref:
                raise ValueError("shadow v2 metric source binding mismatch")

        primary = (
            self.false_release_rate,
            self.false_block_rate,
            self.verified_remediation_pass_rate,
        )
        expected_status = (
            "MEASURED"
            if all(metric.status == "MEASURED" for metric in primary)
            else "PARTIAL_MEASUREMENT"
        )
        if self.measurement_status != expected_status:
            raise ValueError("shadow v2 measurement status mismatch")

        expected_binding = shadow_v2_source_task_binding_sha256(
            workspace_id=self.workspace_id,
            project_id=self.project_id,
            task_id=self.task_id,
            source_id=self.source_id,
            source_authorization_event_sha256=(self.source_authorization_event_sha256),
            task_request_sha256=self.task_request_sha256,
            task_evidence_sha256=self.task_evidence_sha256,
            task_final_decision=self.task_final_decision,
            evaluation_manifest_sha256=self.evaluation_manifest_sha256,
        )
        if not hmac.compare_digest(expected_binding, self.source_task_binding_sha256):
            raise ValueError("shadow v2 source/task binding digest mismatch")

        request = CreateShadowEvaluationManifestV2Request(
            identity=self.identity,
            unit_of_analysis=self.unit_of_analysis,
            ground_truth_method=self.ground_truth_method,
            units=self.units,
            note=self.note,
            operator_attests_authorized_historical_use=(
                self.operator_attests_authorized_historical_use
            ),
            operator_attests_labels_reviewed=(self.operator_attests_labels_reviewed),
            read_only_shadow=self.read_only_shadow,
            raw_images_transmitted=self.raw_images_transmitted,
            machine_write_permitted=self.machine_write_permitted,
        )
        expected_request_sha256 = shadow_evaluation_manifest_v2_request_sha256(
            request,
            workspace_id=self.workspace_id,
            project_id=self.project_id,
            task_id=self.task_id,
            source_id=self.source_id,
            source_authorization_event_sha256=(self.source_authorization_event_sha256),
            task_request_sha256=self.task_request_sha256,
            task_evidence_sha256=self.task_evidence_sha256,
            task_final_decision=self.task_final_decision,
        )
        if not hmac.compare_digest(expected_request_sha256, self.request_sha256):
            raise ValueError("shadow v2 request binding digest mismatch")
        return self


ShadowEvaluationReceipt = IndustrialShadowEvaluationReceipt | ShadowEvaluationManifestV2


class ShadowConfusionMetricGroup(ProductModel):
    """Project aggregate for one compatible confusion-matrix unit."""

    unit_of_analysis: str = Field(min_length=1)
    receipt_count: int = Field(ge=1)
    task_count: int = Field(ge=1)
    labelled_unit_count: int = Field(ge=1)
    false_release_rate: GovernanceRateMetric
    false_block_rate: GovernanceRateMetric
    receipt_ids: list[str] = Field(min_length=1)
    group_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")

    @model_validator(mode="after")
    def validate_group(self) -> ShadowConfusionMetricGroup:
        if len(self.receipt_ids) != self.receipt_count:
            raise ValueError("shadow aggregate receipt count does not reconcile")
        if len(set(self.receipt_ids)) != len(self.receipt_ids):
            raise ValueError("shadow aggregate receipt IDs must be unique")
        if not (
            self.false_release_rate.key == "false_release_rate"
            and self.false_block_rate.key == "false_block_rate"
        ):
            raise ValueError("shadow aggregate metric is bound to the wrong field")
        if any(
            metric.unit_of_analysis != self.unit_of_analysis
            for metric in (self.false_release_rate, self.false_block_rate)
        ):
            raise ValueError("shadow aggregate mixed incompatible analysis units")
        stable = self.model_dump(mode="json", exclude={"group_sha256"})
        observed = hashlib.sha256(canonical_json_bytes(stable)).hexdigest()
        if not hmac.compare_digest(observed, self.group_sha256):
            raise ValueError("shadow aggregate group digest mismatch")
        return self


class ProjectGovernanceEffectivenessSummary(ProductModel):
    """Hash-sealed, unit-safe aggregate over one visible project's receipts."""

    schema_version: Literal["visiondata-gate.project-governance-effectiveness.v1"] = (
        "visiondata-gate.project-governance-effectiveness.v1"
    )
    workspace_id: str = Field(min_length=1)
    project_id: str = Field(min_length=1)
    measurement_status: Literal["NOT_MEASURED", "PARTIAL_MEASUREMENT", "MEASURED"]
    confusion_pooling_status: Literal[
        "NOT_APPLICABLE", "SINGLE_UNIT", "GROUPED_BY_UNIT"
    ]
    receipt_count: int = Field(ge=0)
    task_count: int = Field(ge=0)
    labelled_unit_count: int = Field(ge=0)
    confusion_groups: list[ShadowConfusionMetricGroup]
    verified_remediation_pass_rate: GovernanceRateMetric
    unresolved_remediation_rate: GovernanceRateMetric
    receipt_sha256s: dict[str, str]
    source_manifest_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    raw_images_transmitted: Literal[False] = False
    shadow_labels_enter_agent_core: Literal[False] = False
    production_release_allowed: Literal[False] = False
    claim_boundary: str = (
        "This summary pools only hash-valid operator-attested shadow receipts within "
        "one visible project. Confusion counts are separated by unit_of_analysis; "
        "mixed units are never collapsed into one rate. It is not independent "
        "customer acceptance, production validation, or release authorization."
    )
    summary_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")

    @model_validator(mode="after")
    def validate_summary(self) -> ProjectGovernanceEffectivenessSummary:
        if self.receipt_count != len(self.receipt_sha256s):
            raise ValueError("project shadow receipt count does not reconcile")
        if self.task_count > self.receipt_count:
            raise ValueError("project shadow task count exceeds receipt count")
        if self.labelled_unit_count != sum(
            group.labelled_unit_count for group in self.confusion_groups
        ):
            raise ValueError("project shadow labelled-unit count does not reconcile")
        expected_pooling = (
            "NOT_APPLICABLE"
            if not self.confusion_groups
            else "SINGLE_UNIT"
            if len(self.confusion_groups) == 1
            else "GROUPED_BY_UNIT"
        )
        if self.confusion_pooling_status != expected_pooling:
            raise ValueError("project shadow pooling status does not match unit groups")
        manifest = [
            {"receipt_id": receipt_id, "receipt_sha256": receipt_sha256}
            for receipt_id, receipt_sha256 in sorted(self.receipt_sha256s.items())
        ]
        observed_manifest = hashlib.sha256(canonical_json_bytes(manifest)).hexdigest()
        if not hmac.compare_digest(observed_manifest, self.source_manifest_sha256):
            raise ValueError("project shadow source manifest digest mismatch")
        stable = self.model_dump(mode="json", exclude={"summary_sha256"})
        observed = hashlib.sha256(canonical_json_bytes(stable)).hexdigest()
        if not hmac.compare_digest(observed, self.summary_sha256):
            raise ValueError("project governance summary digest mismatch")
        return self


def _metric(
    *,
    key: GovernanceMetricKey,
    label: str,
    numerator: int,
    denominator: int,
    unit_of_analysis: str,
    target: str,
    definition: str,
    source_ref: str,
    empty_status: Literal["NOT_MEASURED", "NOT_APPLICABLE"],
) -> GovernanceRateMetric:
    return GovernanceRateMetric(
        key=key,
        label=label,
        status="MEASURED" if denominator else empty_status,
        numerator=numerator,
        denominator=denominator,
        value=numerator / denominator if denominator else None,
        unit_of_analysis=unit_of_analysis,
        target=target,
        definition=definition,
        source_ref=source_ref,
    )


def shadow_v2_source_ref(
    *,
    evaluation_manifest_sha256: str,
    truth_manifest_sha256: str,
    gate_output_manifest_sha256: str,
    remediation_manifest_sha256: str,
    task_evidence_sha256: str,
) -> str:
    return (
        f"shadow-v2:{evaluation_manifest_sha256};"
        f"truth:{truth_manifest_sha256};"
        f"gate:{gate_output_manifest_sha256};"
        f"remediation:{remediation_manifest_sha256};"
        f"task-evidence:{task_evidence_sha256}"
    )


def shadow_v2_source_task_binding_sha256(
    *,
    workspace_id: str,
    project_id: str,
    task_id: str,
    source_id: str,
    source_authorization_event_sha256: str,
    task_request_sha256: str,
    task_evidence_sha256: str,
    task_final_decision: str,
    evaluation_manifest_sha256: str,
) -> str:
    return shadow_v2_domain_separated_sha256(
        {
            "schema_version": (
                "visiondata-gate.shadow-evaluation-source-task-binding.v2"
            ),
            "workspace_id": workspace_id,
            "project_id": project_id,
            "task_id": task_id,
            "source_id": source_id,
            "source_authorization_event_sha256": source_authorization_event_sha256,
            "task_request_sha256": task_request_sha256,
            "task_evidence_sha256": task_evidence_sha256,
            "task_final_decision": task_final_decision,
            "evaluation_manifest_sha256": evaluation_manifest_sha256,
        },
        ShadowV2HashDomain.SOURCE_TASK_BINDING,
    )


def shadow_evaluation_manifest_v2_request_sha256(
    request: CreateShadowEvaluationManifestV2Request,
    *,
    workspace_id: str,
    project_id: str,
    task_id: str,
    source_id: str,
    source_authorization_event_sha256: str,
    task_request_sha256: str,
    task_evidence_sha256: str,
    task_final_decision: str,
) -> str:
    """Bind canonical per-unit input to one immutable source/task snapshot."""

    normalized_request = request.model_dump(mode="json")
    normalized_request["units"] = [
        item.model_dump(mode="json") for item in _sorted_shadow_v2_units(request.units)
    ]
    return shadow_v2_domain_separated_sha256(
        {
            "schema_version": "visiondata-gate.shadow-evaluation-request.v2",
            "request": normalized_request,
            "workspace_id": workspace_id,
            "project_id": project_id,
            "task_id": task_id,
            "source_id": source_id,
            "source_authorization_event_sha256": source_authorization_event_sha256,
            "task_request_sha256": task_request_sha256,
            "task_evidence_sha256": task_evidence_sha256,
            "task_final_decision": task_final_decision,
        },
        ShadowV2HashDomain.REQUEST,
    )


def build_shadow_evaluation_manifest_v2(
    *,
    request: CreateShadowEvaluationManifestV2Request,
    workspace_id: str,
    project_id: str,
    task_id: str,
    source_id: str,
    source_authorization_event_sha256: str,
    task_request_sha256: str,
    task_evidence_sha256: str,
    task_final_decision: str,
    created_by: str,
    created_at: str,
) -> ShadowEvaluationManifestV2:
    """Derive all aggregate metrics from canonical per-unit records server-side."""

    request = CreateShadowEvaluationManifestV2Request.model_validate(
        request.model_dump(mode="json")
    )
    ordered_units = _sorted_shadow_v2_units(request.units)
    (
        evaluation_manifest_sha256,
        truth_manifest_sha256,
        gate_output_manifest_sha256,
        remediation_manifest_sha256,
    ) = _shadow_v2_manifest_digests(
        unit_of_analysis=request.unit_of_analysis,
        units=ordered_units,
    )
    confusion, remediation = _shadow_v2_counts(
        unit_of_analysis=request.unit_of_analysis,
        units=ordered_units,
    )
    request_sha256 = shadow_evaluation_manifest_v2_request_sha256(
        request,
        workspace_id=workspace_id,
        project_id=project_id,
        task_id=task_id,
        source_id=source_id,
        source_authorization_event_sha256=source_authorization_event_sha256,
        task_request_sha256=task_request_sha256,
        task_evidence_sha256=task_evidence_sha256,
        task_final_decision=task_final_decision,
    )
    source_task_binding_sha256 = shadow_v2_source_task_binding_sha256(
        workspace_id=workspace_id,
        project_id=project_id,
        task_id=task_id,
        source_id=source_id,
        source_authorization_event_sha256=source_authorization_event_sha256,
        task_request_sha256=task_request_sha256,
        task_evidence_sha256=task_evidence_sha256,
        task_final_decision=task_final_decision,
        evaluation_manifest_sha256=evaluation_manifest_sha256,
    )
    source_ref = shadow_v2_source_ref(
        evaluation_manifest_sha256=evaluation_manifest_sha256,
        truth_manifest_sha256=truth_manifest_sha256,
        gate_output_manifest_sha256=gate_output_manifest_sha256,
        remediation_manifest_sha256=remediation_manifest_sha256,
        task_evidence_sha256=task_evidence_sha256,
    )
    false_release = _metric(
        key="false_release_rate",
        label="误放行率",
        numerator=confusion.false_release_count,
        denominator=confusion.true_block_count + confusion.false_release_count,
        unit_of_analysis=request.unit_of_analysis,
        target="report against a customer-approved threshold",
        definition="false releases / all labelled units that required blocking",
        source_ref=source_ref,
        empty_status="NOT_APPLICABLE",
    )
    false_block = _metric(
        key="false_block_rate",
        label="误拦截率",
        numerator=confusion.false_block_count,
        denominator=confusion.true_release_count + confusion.false_block_count,
        unit_of_analysis=request.unit_of_analysis,
        target="report against a customer-approved threshold",
        definition="false blocks / all labelled units that were releasable",
        source_ref=source_ref,
        empty_status="NOT_APPLICABLE",
    )
    remediation_pass = _metric(
        key="verified_remediation_pass_rate",
        label="整改后验证通过率",
        numerator=remediation.verified_pass_count,
        denominator=remediation.verified_count,
        unit_of_analysis="same-contract remediation recheck",
        target="report against a customer-approved threshold",
        definition="verified passes / all completed same-contract rechecks",
        source_ref=source_ref,
        empty_status="NOT_MEASURED",
    )
    unresolved = _metric(
        key="unresolved_remediation_rate",
        label="整改未决率",
        numerator=remediation.unresolved_count,
        denominator=remediation.attempted_count,
        unit_of_analysis="remediation attempt",
        target="minimize; never remove unresolved attempts from the denominator",
        definition="unresolved attempts / all attempted remediations",
        source_ref=source_ref,
        empty_status="NOT_MEASURED",
    )
    primary = (false_release, false_block, remediation_pass)
    stable = {
        "schema_version": "visiondata-gate.shadow-evaluation-manifest.v2",
        "hash_algorithm": SHADOW_V2_HASH_ALGORITHM,
        "canonicalization_profile": SHADOW_V2_CANONICALIZATION_PROFILE,
        "framing_profile": SHADOW_V2_FRAMING_PROFILE,
        "frame_construction": SHADOW_V2_FRAME_CONSTRUCTION,
        "frame_magic_utf8": SHADOW_V2_FRAME_MAGIC_UTF8,
        "receipt_id": f"shadowv2_{request_sha256[:20]}",
        "request_sha256": request_sha256,
        "workspace_id": workspace_id,
        "project_id": project_id,
        "task_id": task_id,
        "source_id": source_id,
        "source_authorization_event_sha256": source_authorization_event_sha256,
        "task_request_sha256": task_request_sha256,
        "task_evidence_sha256": task_evidence_sha256,
        "task_final_decision": task_final_decision,
        "source_task_binding_sha256": source_task_binding_sha256,
        "identity": request.identity,
        "unit_of_analysis": request.unit_of_analysis,
        "units": ordered_units,
        "labelled_unit_count": len(ordered_units),
        "evaluation_manifest_sha256": evaluation_manifest_sha256,
        "truth_manifest_sha256": truth_manifest_sha256,
        "gate_output_manifest_sha256": gate_output_manifest_sha256,
        "remediation_manifest_sha256": remediation_manifest_sha256,
        "evidence_scope": "PER_UNIT_AUTHORIZED_HISTORICAL_SHADOW",
        "label_authority": "OPERATOR_REVIEWED_PER_UNIT_EXTERNAL_EVIDENCE",
        "aggregation_authority": (
            "VISIONDATA_GATE_SERVER_DERIVED_FROM_PER_UNIT_RECORDS"
        ),
        "ground_truth_method": request.ground_truth_method,
        "confusion": confusion,
        "remediation": remediation,
        "false_release_rate": false_release,
        "false_block_rate": false_block,
        "verified_remediation_pass_rate": remediation_pass,
        "unresolved_remediation_rate": unresolved,
        "measurement_status": (
            "MEASURED"
            if all(metric.status == "MEASURED" for metric in primary)
            else "PARTIAL_MEASUREMENT"
        ),
        "server_computed_counts": True,
        "client_supplied_aggregate_counts_accepted": False,
        "note": request.note,
        "operator_attests_authorized_historical_use": (
            request.operator_attests_authorized_historical_use
        ),
        "operator_attests_labels_reviewed": (request.operator_attests_labels_reviewed),
        "created_by": created_by,
        "created_at": created_at,
        "read_only_shadow": True,
        "raw_images_transmitted": False,
        "machine_write_permitted": False,
        "shadow_labels_enter_agent_core": False,
        "customer_acceptance_claimed": False,
        "production_release_allowed": False,
        "claim_boundary": ShadowEvaluationManifestV2.model_fields[
            "claim_boundary"
        ].default,
    }
    return ShadowEvaluationManifestV2(
        **stable,
        receipt_sha256=shadow_v2_domain_separated_sha256(
            stable,
            ShadowV2HashDomain.RECEIPT,
        ),
    )


def shadow_evaluation_request_sha256(
    request: CreateIndustrialShadowEvaluationRequest,
    *,
    task_id: str,
    task_request_sha256: str,
    task_evidence_sha256: str,
    source_authorization_event_sha256: str,
) -> str:
    """Bind idempotency to both operator input and immutable upstream evidence."""

    return hashlib.sha256(
        canonical_json_bytes(
            {
                "request": request,
                "task_id": task_id,
                "task_request_sha256": task_request_sha256,
                "task_evidence_sha256": task_evidence_sha256,
                "source_authorization_event_sha256": (
                    source_authorization_event_sha256
                ),
            }
        )
    ).hexdigest()


def build_industrial_shadow_evaluation_receipt(
    *,
    request: CreateIndustrialShadowEvaluationRequest,
    workspace_id: str,
    project_id: str,
    task_id: str,
    source_id: str,
    source_authorization_event_sha256: str,
    task_request_sha256: str,
    task_evidence_sha256: str,
    task_final_decision: str,
    created_by: str,
    created_at: str,
) -> IndustrialShadowEvaluationReceipt:
    request_sha256 = shadow_evaluation_request_sha256(
        request,
        task_id=task_id,
        task_request_sha256=task_request_sha256,
        task_evidence_sha256=task_evidence_sha256,
        source_authorization_event_sha256=source_authorization_event_sha256,
    )
    confusion = request.confusion
    remediation = request.remediation
    source_ref = (
        f"truth:{request.truth_manifest_sha256};"
        f"gate:{request.gate_output_manifest_sha256}"
    )
    false_release = _metric(
        key="false_release_rate",
        label="误放行率",
        numerator=confusion.false_release_count,
        denominator=confusion.true_block_count + confusion.false_release_count,
        unit_of_analysis=confusion.unit_of_analysis,
        target="report against a customer-approved threshold",
        definition="false releases / all labelled units that required blocking",
        source_ref=source_ref,
        empty_status="NOT_APPLICABLE",
    )
    false_block = _metric(
        key="false_block_rate",
        label="误拦截率",
        numerator=confusion.false_block_count,
        denominator=confusion.true_release_count + confusion.false_block_count,
        unit_of_analysis=confusion.unit_of_analysis,
        target="report against a customer-approved threshold",
        definition="false blocks / all labelled units that were releasable",
        source_ref=source_ref,
        empty_status="NOT_APPLICABLE",
    )
    remediation_pass = _metric(
        key="verified_remediation_pass_rate",
        label="整改后验证通过率",
        numerator=remediation.verified_pass_count,
        denominator=remediation.verified_count,
        unit_of_analysis="same-contract remediation recheck",
        target="report against a customer-approved threshold",
        definition="verified passes / all completed same-contract rechecks",
        source_ref=source_ref,
        empty_status="NOT_MEASURED",
    )
    unresolved = _metric(
        key="unresolved_remediation_rate",
        label="整改未决率",
        numerator=remediation.unresolved_count,
        denominator=remediation.attempted_count,
        unit_of_analysis="remediation attempt",
        target="minimize; never remove unresolved attempts from the denominator",
        definition="unresolved attempts / all attempted remediations",
        source_ref=source_ref,
        empty_status="NOT_MEASURED",
    )
    primary = (false_release, false_block, remediation_pass)
    stable = {
        "schema_version": "visiondata-gate.industrial-shadow-evaluation.v1",
        "receipt_id": f"shadow_{request_sha256[:20]}",
        "request_sha256": request_sha256,
        "workspace_id": workspace_id,
        "project_id": project_id,
        "task_id": task_id,
        "source_id": source_id,
        "source_authorization_event_sha256": source_authorization_event_sha256,
        "task_request_sha256": task_request_sha256,
        "task_evidence_sha256": task_evidence_sha256,
        "task_final_decision": task_final_decision,
        "identity": request.identity,
        "evidence_scope": "OPERATOR_ATTESTED_AUTHORIZED_HISTORICAL_SHADOW",
        "label_authority": "OPERATOR_REVIEWED_EXTERNAL_MANIFEST",
        "ground_truth_method": request.ground_truth_method,
        "truth_manifest_sha256": request.truth_manifest_sha256,
        "gate_output_manifest_sha256": request.gate_output_manifest_sha256,
        "labelled_unit_count": confusion.labelled_unit_count,
        "confusion": confusion,
        "remediation": remediation,
        "false_release_rate": false_release,
        "false_block_rate": false_block,
        "verified_remediation_pass_rate": remediation_pass,
        "unresolved_remediation_rate": unresolved,
        "measurement_status": (
            "MEASURED"
            if all(metric.status == "MEASURED" for metric in primary)
            else "PARTIAL_MEASUREMENT"
        ),
        "note": request.note,
        "created_by": created_by,
        "created_at": created_at,
        "read_only_shadow": True,
        "raw_images_transmitted": False,
        "machine_write_permitted": False,
        "customer_acceptance_claimed": False,
        "production_release_allowed": False,
        "claim_boundary": IndustrialShadowEvaluationReceipt.model_fields[
            "claim_boundary"
        ].default,
    }
    return IndustrialShadowEvaluationReceipt(
        **stable,
        receipt_sha256=hashlib.sha256(canonical_json_bytes(stable)).hexdigest(),
    )


def build_project_governance_effectiveness_summary(
    *,
    workspace_id: str,
    project_id: str,
    receipts: Sequence[ShadowEvaluationReceipt],
) -> ProjectGovernanceEffectivenessSummary:
    """Pool compatible shadow counts without ever merging different units."""

    receipt_list = sorted(receipts, key=lambda item: (item.receipt_id, item.task_id))
    receipt_ids = [item.receipt_id for item in receipt_list]
    if len(receipt_ids) != len(set(receipt_ids)):
        raise ValueError("project shadow summary received duplicate receipt IDs")
    for receipt in receipt_list:
        if isinstance(receipt, ShadowEvaluationManifestV2):
            verify_shadow_evaluation_manifest_v2(receipt)
        else:
            verify_industrial_shadow_evaluation_receipt(receipt)
        if receipt.workspace_id != workspace_id or receipt.project_id != project_id:
            raise ValueError("project shadow summary received an out-of-scope receipt")

    receipt_sha256s = {item.receipt_id: item.receipt_sha256 for item in receipt_list}
    manifest = [
        {"receipt_id": receipt_id, "receipt_sha256": receipt_sha256}
        for receipt_id, receipt_sha256 in sorted(receipt_sha256s.items())
    ]
    source_manifest_sha256 = hashlib.sha256(canonical_json_bytes(manifest)).hexdigest()
    source_ref = f"shadow-project-manifest:{source_manifest_sha256}"

    by_unit: defaultdict[str, list[ShadowEvaluationReceipt]] = defaultdict(list)
    for receipt in receipt_list:
        by_unit[receipt.confusion.unit_of_analysis].append(receipt)

    groups: list[ShadowConfusionMetricGroup] = []
    for unit_of_analysis in sorted(by_unit):
        unit_receipts = by_unit[unit_of_analysis]
        true_block_count = sum(
            item.confusion.true_block_count for item in unit_receipts
        )
        false_release_count = sum(
            item.confusion.false_release_count for item in unit_receipts
        )
        true_release_count = sum(
            item.confusion.true_release_count for item in unit_receipts
        )
        false_block_count = sum(
            item.confusion.false_block_count for item in unit_receipts
        )
        stable_group = {
            "unit_of_analysis": unit_of_analysis,
            "receipt_count": len(unit_receipts),
            "task_count": len({item.task_id for item in unit_receipts}),
            "labelled_unit_count": sum(
                item.confusion.labelled_unit_count for item in unit_receipts
            ),
            "false_release_rate": _metric(
                key="false_release_rate",
                label="误放行率",
                numerator=false_release_count,
                denominator=true_block_count + false_release_count,
                unit_of_analysis=unit_of_analysis,
                target="report against a customer-approved threshold",
                definition="false releases / all labelled units that required blocking",
                source_ref=source_ref,
                empty_status="NOT_APPLICABLE",
            ),
            "false_block_rate": _metric(
                key="false_block_rate",
                label="误拦截率",
                numerator=false_block_count,
                denominator=true_release_count + false_block_count,
                unit_of_analysis=unit_of_analysis,
                target="report against a customer-approved threshold",
                definition="false blocks / all labelled units that were releasable",
                source_ref=source_ref,
                empty_status="NOT_APPLICABLE",
            ),
            "receipt_ids": sorted(item.receipt_id for item in unit_receipts),
        }
        groups.append(
            ShadowConfusionMetricGroup(
                **stable_group,
                group_sha256=hashlib.sha256(
                    canonical_json_bytes(stable_group)
                ).hexdigest(),
            )
        )

    remediation_pass_count = sum(
        item.remediation.verified_pass_count for item in receipt_list
    )
    remediation_fail_count = sum(
        item.remediation.verified_fail_count for item in receipt_list
    )
    remediation_unresolved_count = sum(
        item.remediation.unresolved_count for item in receipt_list
    )
    remediation_verified_count = remediation_pass_count + remediation_fail_count
    remediation_attempted_count = (
        remediation_verified_count + remediation_unresolved_count
    )
    remediation_pass = _metric(
        key="verified_remediation_pass_rate",
        label="整改后验证通过率",
        numerator=remediation_pass_count,
        denominator=remediation_verified_count,
        unit_of_analysis="same-contract remediation recheck",
        target="report against a customer-approved threshold",
        definition="verified passes / all completed same-contract rechecks",
        source_ref=source_ref,
        empty_status="NOT_MEASURED",
    )
    unresolved = _metric(
        key="unresolved_remediation_rate",
        label="整改未决率",
        numerator=remediation_unresolved_count,
        denominator=remediation_attempted_count,
        unit_of_analysis="remediation attempt",
        target="minimize; never remove unresolved attempts from the denominator",
        definition="unresolved attempts / all attempted remediations",
        source_ref=source_ref,
        empty_status="NOT_MEASURED",
    )
    measured_metrics = [
        metric
        for group in groups
        for metric in (group.false_release_rate, group.false_block_rate)
    ]
    measured_metrics.extend((remediation_pass, unresolved))
    measurement_status: Literal["NOT_MEASURED", "PARTIAL_MEASUREMENT", "MEASURED"]
    if not receipt_list:
        measurement_status = "NOT_MEASURED"
    elif all(metric.status == "MEASURED" for metric in measured_metrics):
        measurement_status = "MEASURED"
    else:
        measurement_status = "PARTIAL_MEASUREMENT"
    stable_summary = {
        "schema_version": "visiondata-gate.project-governance-effectiveness.v1",
        "workspace_id": workspace_id,
        "project_id": project_id,
        "measurement_status": measurement_status,
        "confusion_pooling_status": (
            "NOT_APPLICABLE"
            if not groups
            else "SINGLE_UNIT"
            if len(groups) == 1
            else "GROUPED_BY_UNIT"
        ),
        "receipt_count": len(receipt_list),
        "task_count": len({item.task_id for item in receipt_list}),
        "labelled_unit_count": sum(group.labelled_unit_count for group in groups),
        "confusion_groups": groups,
        "verified_remediation_pass_rate": remediation_pass,
        "unresolved_remediation_rate": unresolved,
        "receipt_sha256s": receipt_sha256s,
        "source_manifest_sha256": source_manifest_sha256,
        "raw_images_transmitted": False,
        "shadow_labels_enter_agent_core": False,
        "production_release_allowed": False,
        "claim_boundary": ProjectGovernanceEffectivenessSummary.model_fields[
            "claim_boundary"
        ].default,
    }
    return ProjectGovernanceEffectivenessSummary(
        **stable_summary,
        summary_sha256=hashlib.sha256(canonical_json_bytes(stable_summary)).hexdigest(),
    )


def verify_industrial_shadow_evaluation_receipt(
    receipt: IndustrialShadowEvaluationReceipt,
) -> None:
    stable = receipt.model_dump(mode="json", exclude={"receipt_sha256"})
    observed = hashlib.sha256(canonical_json_bytes(stable)).hexdigest()
    if not hmac.compare_digest(observed, receipt.receipt_sha256):
        raise ValueError("industrial shadow evaluation receipt digest mismatch")


def verify_shadow_evaluation_manifest_v2(
    manifest: ShadowEvaluationManifestV2,
) -> None:
    """Recompute per-unit semantics and the immutable outer receipt digest."""

    validated = ShadowEvaluationManifestV2.model_validate(
        manifest.model_dump(mode="json")
    )
    stable = validated.model_dump(mode="json", exclude={"receipt_sha256"})
    observed = shadow_v2_domain_separated_sha256(
        stable,
        ShadowV2HashDomain.RECEIPT,
    )
    if not hmac.compare_digest(observed, validated.receipt_sha256):
        raise ValueError("shadow v2 evaluation manifest digest mismatch")


def verify_project_governance_effectiveness_summary(
    summary: ProjectGovernanceEffectivenessSummary,
) -> None:
    """Recheck the top-level summary digest after persistence or transport."""

    stable = summary.model_dump(mode="json", exclude={"summary_sha256"})
    observed = hashlib.sha256(canonical_json_bytes(stable)).hexdigest()
    if not hmac.compare_digest(observed, summary.summary_sha256):
        raise ValueError("project governance summary digest mismatch")


__all__ = [
    "CreateIndustrialShadowEvaluationRequest",
    "CreateShadowEvaluationManifestV2Request",
    "GovernanceRateMetric",
    "IndustrialShadowBatchIdentity",
    "IndustrialShadowEvaluationReceipt",
    "ProjectGovernanceEffectivenessSummary",
    "ShadowConfusionMetricGroup",
    "ShadowConfusionCounts",
    "ShadowEvaluationManifestV2",
    "ShadowEvaluationReceipt",
    "ShadowEvaluationUnitV2",
    "ShadowRemediationCounts",
    "ShadowV2HashDomain",
    "build_industrial_shadow_evaluation_receipt",
    "build_project_governance_effectiveness_summary",
    "build_shadow_evaluation_manifest_v2",
    "shadow_evaluation_manifest_v2_request_sha256",
    "shadow_evaluation_request_sha256",
    "shadow_v2_domain_separated_sha256",
    "shadow_v2_source_ref",
    "shadow_v2_source_task_binding_sha256",
    "verify_industrial_shadow_evaluation_receipt",
    "verify_project_governance_effectiveness_summary",
    "verify_shadow_evaluation_manifest_v2",
]
