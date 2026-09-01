"""Version-pinned, read-only contracts for deterministic industrial Skills.

This module is an in-process extension contract, not a Python security sandbox.
Only reviewed Skill instances are registered explicitly; the registry never imports
an entrypoint string, evaluates an expression, or exposes file paths, raw bytes, or
machine-control handles to a Skill invocation.
"""

from __future__ import annotations

import hashlib
import json
import re
from abc import ABC, abstractmethod
from collections.abc import Iterable, Mapping, Sequence
from enum import Enum
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

_SEMVER_PATTERN = r"^(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)$"
_ID_PATTERN = r"^[a-z0-9][a-z0-9._-]*$"
_MEASUREMENT_PATTERN = r"^[a-z][a-z0-9._-]*$"
_SHA256_PATTERN = r"^[0-9a-f]{64}$"
_JSON_POINTER_PATTERN = r"^/[A-Za-z0-9_.~-]+(?:/[A-Za-z0-9_.~-]+)*$"
_WINDOWS_ABSOLUTE_PATH = re.compile(r"(?:^|\s)[A-Za-z]:[\\/]")


class IndustrialSkillModel(BaseModel):
    """Immutable base model that rejects silent contract drift."""

    model_config = ConfigDict(
        extra="forbid",
        frozen=True,
        str_strip_whitespace=True,
    )


def _safe_text(value: str, *, field_name: str) -> str:
    lowered = value.casefold()
    if _WINDOWS_ABSOLUTE_PATH.search(value) or "\\\\" in value or "file://" in lowered:
        raise ValueError(f"{field_name} must not contain an absolute path")
    return value


class IndustrialSkillDependency(IndustrialSkillModel):
    """One disclosed third-party runtime dependency."""

    package: str = Field(pattern=_ID_PATTERN)
    version_spec: str = Field(min_length=1, max_length=80)
    license_spdx: str = Field(min_length=2, max_length=80)


class FrozenNumericParameter(IndustrialSkillModel):
    """A measurement parameter sealed into the Skill manifest digest."""

    name: str = Field(pattern=_MEASUREMENT_PATTERN)
    value: float = Field(allow_inf_nan=False)
    unit: str = Field(min_length=1, max_length=40)


class IndustrialSkillManifest(IndustrialSkillModel):
    """Reviewed identity and safety boundary for one Skill implementation."""

    schema_version: Literal["visiondata-gate.industrial-skill-manifest.v1"] = (
        "visiondata-gate.industrial-skill-manifest.v1"
    )
    skill_id: str = Field(pattern=_ID_PATTERN)
    skill_version: str = Field(pattern=_SEMVER_PATTERN)
    display_name: str = Field(min_length=1, max_length=120)
    purpose: str = Field(min_length=20, max_length=500)
    algorithm_id: str = Field(pattern=_ID_PATTERN)
    algorithm_version: str = Field(pattern=_SEMVER_PATTERN)
    required_measurements: tuple[str, ...] = Field(min_length=1)
    frozen_parameters: tuple[FrozenNumericParameter, ...] = ()
    third_party_dependencies: tuple[IndustrialSkillDependency, ...] = ()
    license_spdx: str = Field(min_length=2, max_length=80)
    input_model_ref: Literal[
        "visiondata_gate.industrial_skills:IndustrialSkillInvocation"
    ] = "visiondata_gate.industrial_skills:IndustrialSkillInvocation"
    output_model_ref: Literal[
        "visiondata_gate.industrial_skills:IndustrialSkillOutcome"
    ] = "visiondata_gate.industrial_skills:IndustrialSkillOutcome"
    permission_scope: Literal["source.snapshot:read"] = "source.snapshot:read"
    read_only: Literal[True] = True
    raw_bytes_available: Literal[False] = False
    network_access_permitted: Literal[False] = False
    machine_write_permitted: Literal[False] = False
    production_decision_authority: Literal[False] = False
    claim_boundary: str = Field(min_length=40, max_length=800)

    @model_validator(mode="after")
    def unique_manifest_items(self) -> "IndustrialSkillManifest":
        measurements = tuple(self.required_measurements)
        if len(measurements) != len(set(measurements)):
            raise ValueError("required_measurements must be unique")
        if any(not re.fullmatch(_MEASUREMENT_PATTERN, item) for item in measurements):
            raise ValueError("required_measurements contains an invalid name")
        parameter_names = tuple(item.name for item in self.frozen_parameters)
        if len(parameter_names) != len(set(parameter_names)):
            raise ValueError("frozen parameter names must be unique")
        _safe_text(self.purpose, field_name="purpose")
        _safe_text(self.claim_boundary, field_name="claim_boundary")
        return self


class IndustrialSourceSnapshot(IndustrialSkillModel):
    """Path-free identity of the already-authorized source snapshot."""

    source_id: str = Field(pattern=_ID_PATTERN)
    source_kind: Literal[
        "redacted_batch_snapshot",
        "authorized_metadata_snapshot",
    ]
    source_version: str = Field(min_length=1, max_length=120)
    snapshot_sha256: str = Field(pattern=_SHA256_PATTERN)

    @model_validator(mode="after")
    def path_free_version(self) -> "IndustrialSourceSnapshot":
        _safe_text(self.source_version, field_name="source_version")
        return self


class IndustrialEvidenceSpan(IndustrialSkillModel):
    """A versioned, replayable selector into one source snapshot."""

    source_id: str = Field(pattern=_ID_PATTERN)
    source_version: str = Field(min_length=1, max_length=120)
    snapshot_sha256: str = Field(pattern=_SHA256_PATTERN)
    span_kind: Literal["metric", "metadata", "annotation", "pixel_region"]
    selector: str = Field(pattern=_JSON_POINTER_PATTERN, max_length=300)
    sample_id: str | None = Field(default=None, pattern=_ID_PATTERN)

    @model_validator(mode="after")
    def safe_selector(self) -> "IndustrialEvidenceSpan":
        if any(token == ".." for token in self.selector.split("/")):
            raise ValueError("evidence selector traversal is forbidden")
        _safe_text(self.source_version, field_name="source_version")
        return self


class IndustrialMeasurement(IndustrialSkillModel):
    """One deterministic numeric input and its exact evidence selector."""

    name: str = Field(pattern=_MEASUREMENT_PATTERN)
    value: float = Field(allow_inf_nan=False)
    unit: str = Field(min_length=1, max_length=40)
    measurement_version: str = Field(pattern=_SEMVER_PATTERN)
    evidence_span: IndustrialEvidenceSpan


class IndustrialSkillInvocation(IndustrialSkillModel):
    """Path-free invocation supplied to an allowlisted Skill instance."""

    schema_version: Literal["visiondata-gate.industrial-skill-invocation.v1"] = (
        "visiondata-gate.industrial-skill-invocation.v1"
    )
    invocation_id: str = Field(pattern=_ID_PATTERN)
    source: IndustrialSourceSnapshot
    measurements: tuple[IndustrialMeasurement, ...] = Field(min_length=1)

    @model_validator(mode="after")
    def bind_measurements_to_source(self) -> "IndustrialSkillInvocation":
        names = tuple(item.name for item in self.measurements)
        if len(names) != len(set(names)):
            raise ValueError("measurement names must be unique")
        expected = (
            self.source.source_id,
            self.source.source_version,
            self.source.snapshot_sha256,
        )
        for item in self.measurements:
            observed = (
                item.evidence_span.source_id,
                item.evidence_span.source_version,
                item.evidence_span.snapshot_sha256,
            )
            if observed != expected:
                raise ValueError(
                    "measurement evidence is not bound to the source snapshot"
                )
        return self


class NumericAnomalyDecision(IndustrialSkillModel):
    """A deterministic threshold comparison; ``is_anomaly`` is self-checked."""

    observed_value: float = Field(allow_inf_nan=False)
    operator: Literal["gt", "gte", "lt", "lte", "eq", "ne"]
    threshold_value: float = Field(allow_inf_nan=False)
    is_anomaly: bool

    @model_validator(mode="after")
    def verify_decision(self) -> "NumericAnomalyDecision":
        comparisons = {
            "gt": self.observed_value > self.threshold_value,
            "gte": self.observed_value >= self.threshold_value,
            "lt": self.observed_value < self.threshold_value,
            "lte": self.observed_value <= self.threshold_value,
            "eq": self.observed_value == self.threshold_value,
            "ne": self.observed_value != self.threshold_value,
        }
        if comparisons[self.operator] is not self.is_anomaly:
            raise ValueError("is_anomaly disagrees with the declared comparison")
        return self


class IndustrialSkillObservation(IndustrialSkillModel):
    """One versioned observation with no authority to issue a machine command."""

    observation_id: str = Field(pattern=_ID_PATTERN)
    measurement_name: str = Field(pattern=_MEASUREMENT_PATTERN)
    unit: str = Field(min_length=1, max_length=40)
    decision: NumericAnomalyDecision
    severity_if_anomalous: Literal["low", "medium", "high", "critical"]
    reason_code: str = Field(pattern=r"^[A-Z][A-Z0-9_]*$")
    summary: str = Field(min_length=1, max_length=500)
    recommended_action: str = Field(min_length=1, max_length=500)
    algorithm_version: str = Field(pattern=_SEMVER_PATTERN)
    evidence_spans: tuple[IndustrialEvidenceSpan, ...] = Field(min_length=1)
    machine_action_permitted: Literal[False] = False

    @model_validator(mode="after")
    def path_free_text(self) -> "IndustrialSkillObservation":
        _safe_text(self.summary, field_name="summary")
        _safe_text(self.recommended_action, field_name="recommended_action")
        return self


class IndustrialSkillFailure(IndustrialSkillModel):
    """Sanitized fail-closed outcome; never includes the exception message."""

    reason_code: Literal[
        "MISSING_REQUIRED_MEASUREMENT",
        "INVALID_MEASUREMENT_VALUE",
        "SKILL_EXECUTION_FAILED",
        "SKILL_OUTPUT_CONTRACT_VIOLATION",
        "SKILL_MANIFEST_DRIFT",
    ]
    safe_detail: str = Field(min_length=1, max_length=300)

    @model_validator(mode="after")
    def path_free_detail(self) -> "IndustrialSkillFailure":
        _safe_text(self.safe_detail, field_name="safe_detail")
        return self


class IndustrialSkillOutcome(IndustrialSkillModel):
    """Revalidated output returned by a registered Skill."""

    schema_version: Literal["visiondata-gate.industrial-skill-outcome.v1"] = (
        "visiondata-gate.industrial-skill-outcome.v1"
    )
    invocation_id: str = Field(pattern=_ID_PATTERN)
    skill_id: str = Field(pattern=_ID_PATTERN)
    skill_version: str = Field(pattern=_SEMVER_PATTERN)
    algorithm_version: str = Field(pattern=_SEMVER_PATTERN)
    source: IndustrialSourceSnapshot
    status: Literal["OK", "DEFER"]
    observations: tuple[IndustrialSkillObservation, ...] = ()
    failure: IndustrialSkillFailure | None = None
    actual_model_call_count: Literal[0] = 0
    network_call_count: Literal[0] = 0
    machine_write_count: Literal[0] = 0
    production_decision_authority: Literal[False] = False
    claim_boundary: str = Field(min_length=40, max_length=800)

    @model_validator(mode="after")
    def status_semantics(self) -> "IndustrialSkillOutcome":
        if self.status == "OK" and (not self.observations or self.failure is not None):
            raise ValueError("OK requires observations and forbids a failure")
        if self.status == "DEFER" and (self.observations or self.failure is None):
            raise ValueError("DEFER requires one failure and forbids observations")
        observation_ids = tuple(item.observation_id for item in self.observations)
        if len(observation_ids) != len(set(observation_ids)):
            raise ValueError("observation_id values must be unique")
        _safe_text(self.claim_boundary, field_name="claim_boundary")
        return self


class IndustrialSkillReceipt(IndustrialSkillModel):
    """Self-contained, deterministic receipt for one registry invocation."""

    schema_version: Literal["visiondata-gate.industrial-skill-receipt.v1"] = (
        "visiondata-gate.industrial-skill-receipt.v1"
    )
    manifest: IndustrialSkillManifest
    invocation: IndustrialSkillInvocation
    outcome: IndustrialSkillOutcome
    manifest_sha256: str = Field(pattern=_SHA256_PATTERN)
    invocation_sha256: str = Field(pattern=_SHA256_PATTERN)
    outcome_sha256: str = Field(pattern=_SHA256_PATTERN)
    receipt_sha256: str = Field(pattern=_SHA256_PATTERN)


class BaseIndustrialSkill(ABC):
    """Explicitly registered deterministic measurement component.

    Subclasses receive only a typed, path-free snapshot invocation.  This ABC and
    registry enforce the host contract, but cannot sandbox arbitrary Python code.
    Deployments must review trusted in-process implementations or isolate them in a
    separately governed process.
    """

    @property
    @abstractmethod
    def manifest(self) -> IndustrialSkillManifest:
        """Return the immutable, versioned manifest reviewed at registration."""

    @abstractmethod
    def inspect(self, invocation: IndustrialSkillInvocation) -> IndustrialSkillOutcome:
        """Return measurements only; never issue a production or machine command."""


def _json_value(value: object) -> object:
    """Normalize closed Skill models without importing the wider evidence graph."""

    if isinstance(value, BaseModel):
        return _json_value(value.model_dump(mode="json", exclude_none=False))
    if isinstance(value, Enum):
        return value.value
    if value is None or isinstance(value, (str, bool, int, float)):
        return value
    if isinstance(value, Mapping):
        normalized: dict[str, object] = {}
        for key, item in value.items():
            if not isinstance(key, str):
                raise TypeError("canonical Skill receipt keys must be strings")
            normalized[key] = _json_value(item)
        return normalized
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
        return [_json_value(item) for item in value]
    raise TypeError(f"unsupported Skill receipt value: {type(value).__name__}")


def _canonical_json_bytes(value: object) -> bytes:
    text = json.dumps(
        _json_value(value),
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    )
    return (text + "\n").encode("utf-8")


def _model_sha256(model: BaseModel) -> str:
    return hashlib.sha256(_canonical_json_bytes(model)).hexdigest()


def _span_key(span: IndustrialEvidenceSpan) -> bytes:
    return _canonical_json_bytes(span)


def _binding_error(
    manifest: IndustrialSkillManifest,
    invocation: IndustrialSkillInvocation,
    outcome: IndustrialSkillOutcome,
) -> str | None:
    if (
        outcome.skill_id != manifest.skill_id
        or outcome.skill_version != manifest.skill_version
        or outcome.algorithm_version != manifest.algorithm_version
    ):
        return "Skill or algorithm identity does not match the registered manifest."
    if outcome.invocation_id != invocation.invocation_id:
        return "Outcome invocation_id does not match the request."
    if outcome.source != invocation.source:
        return "Outcome source does not match the request source snapshot."
    allowed_spans = {_span_key(item.evidence_span) for item in invocation.measurements}
    for observation in outcome.observations:
        if observation.algorithm_version != manifest.algorithm_version:
            return "Observation algorithm version does not match the manifest."
        if any(
            _span_key(span) not in allowed_spans for span in observation.evidence_spans
        ):
            return "Observation cites evidence that was not present in the invocation."
    return None


def _deferred_outcome(
    manifest: IndustrialSkillManifest,
    invocation: IndustrialSkillInvocation,
    *,
    reason_code: Literal[
        "MISSING_REQUIRED_MEASUREMENT",
        "INVALID_MEASUREMENT_VALUE",
        "SKILL_EXECUTION_FAILED",
        "SKILL_OUTPUT_CONTRACT_VIOLATION",
        "SKILL_MANIFEST_DRIFT",
    ],
    safe_detail: str,
) -> IndustrialSkillOutcome:
    return IndustrialSkillOutcome(
        invocation_id=invocation.invocation_id,
        skill_id=manifest.skill_id,
        skill_version=manifest.skill_version,
        algorithm_version=manifest.algorithm_version,
        source=invocation.source,
        status="DEFER",
        failure=IndustrialSkillFailure(
            reason_code=reason_code,
            safe_detail=safe_detail,
        ),
        claim_boundary=manifest.claim_boundary,
    )


def _seal_receipt(
    manifest: IndustrialSkillManifest,
    invocation: IndustrialSkillInvocation,
    outcome: IndustrialSkillOutcome,
) -> IndustrialSkillReceipt:
    manifest_sha256 = _model_sha256(manifest)
    invocation_sha256 = _model_sha256(invocation)
    outcome_sha256 = _model_sha256(outcome)
    payload = {
        "schema_version": "visiondata-gate.industrial-skill-receipt.v1",
        "manifest": manifest,
        "invocation": invocation,
        "outcome": outcome,
        "manifest_sha256": manifest_sha256,
        "invocation_sha256": invocation_sha256,
        "outcome_sha256": outcome_sha256,
    }
    return IndustrialSkillReceipt(
        **payload,
        receipt_sha256=hashlib.sha256(_canonical_json_bytes(payload)).hexdigest(),
    )


def verify_industrial_skill_receipt(receipt: IndustrialSkillReceipt) -> bool:
    """Recompute hashes and all identity/evidence bindings in one receipt."""

    binding_error = _binding_error(
        receipt.manifest,
        receipt.invocation,
        receipt.outcome,
    )
    payload = receipt.model_dump(mode="python", exclude={"receipt_sha256"})
    return (
        binding_error is None
        and receipt.manifest_sha256 == _model_sha256(receipt.manifest)
        and receipt.invocation_sha256 == _model_sha256(receipt.invocation)
        and receipt.outcome_sha256 == _model_sha256(receipt.outcome)
        and receipt.receipt_sha256
        == hashlib.sha256(_canonical_json_bytes(payload)).hexdigest()
    )


class IndustrialSkillRegistry:
    """Allowlist of explicitly constructed, version-pinned Skill instances."""

    def __init__(self, skills: Iterable[BaseIndustrialSkill] = ()) -> None:
        self._entries: dict[
            tuple[str, str], tuple[BaseIndustrialSkill, IndustrialSkillManifest]
        ] = {}
        for skill in skills:
            self.register(skill)

    def register(self, skill: BaseIndustrialSkill) -> IndustrialSkillManifest:
        """Register one reviewed instance; strings and dynamic imports are rejected."""

        if not isinstance(skill, BaseIndustrialSkill):
            raise TypeError(
                "skill must be an explicitly constructed BaseIndustrialSkill"
            )
        manifest = IndustrialSkillManifest.model_validate(
            skill.manifest.model_dump(mode="python")
        )
        key = (manifest.skill_id, manifest.skill_version)
        if key in self._entries:
            raise ValueError(
                f"Skill {manifest.skill_id}@{manifest.skill_version} is already registered"
            )
        self._entries[key] = (skill, manifest)
        return manifest

    def manifests(self) -> tuple[IndustrialSkillManifest, ...]:
        """Return a stable catalog without exposing mutable registry state."""

        return tuple(
            self._entries[key][1]
            for key in sorted(self._entries, key=lambda item: (item[0], item[1]))
        )

    def invoke(
        self,
        skill_id: str,
        skill_version: str,
        invocation: IndustrialSkillInvocation,
    ) -> IndustrialSkillReceipt:
        """Invoke one exact version and fail closed on drift or malformed output."""

        key = (skill_id, skill_version)
        if key not in self._entries:
            raise KeyError(f"Skill {skill_id}@{skill_version} is not registered")
        skill, registered_manifest = self._entries[key]
        request = IndustrialSkillInvocation.model_validate(
            invocation.model_dump(mode="python")
        )

        try:
            current_manifest = IndustrialSkillManifest.model_validate(
                skill.manifest.model_dump(mode="python")
            )
        except Exception:
            current_manifest = None
        if current_manifest != registered_manifest:
            outcome = _deferred_outcome(
                registered_manifest,
                request,
                reason_code="SKILL_MANIFEST_DRIFT",
                safe_detail="The implementation manifest changed after registration.",
            )
            return _seal_receipt(registered_manifest, request, outcome)

        missing = sorted(
            set(registered_manifest.required_measurements)
            - {item.name for item in request.measurements}
        )
        if missing:
            outcome = _deferred_outcome(
                registered_manifest,
                request,
                reason_code="MISSING_REQUIRED_MEASUREMENT",
                safe_detail="Required measurements are absent: " + ", ".join(missing),
            )
            return _seal_receipt(registered_manifest, request, outcome)

        try:
            raw_outcome = skill.inspect(request)
        except Exception as exc:
            outcome = _deferred_outcome(
                registered_manifest,
                request,
                reason_code="SKILL_EXECUTION_FAILED",
                safe_detail=f"The reviewed Skill raised {type(exc).__name__}; details withheld.",
            )
            return _seal_receipt(registered_manifest, request, outcome)

        try:
            outcome = IndustrialSkillOutcome.model_validate(
                raw_outcome.model_dump(mode="python")
            )
        except Exception:
            outcome = _deferred_outcome(
                registered_manifest,
                request,
                reason_code="SKILL_OUTPUT_CONTRACT_VIOLATION",
                safe_detail="The Skill output did not satisfy the strict output schema.",
            )
            return _seal_receipt(registered_manifest, request, outcome)

        error = _binding_error(registered_manifest, request, outcome)
        if error is not None:
            outcome = _deferred_outcome(
                registered_manifest,
                request,
                reason_code="SKILL_OUTPUT_CONTRACT_VIOLATION",
                safe_detail=error,
            )
        return _seal_receipt(registered_manifest, request, outcome)


class MetadataCountDriftSkill(BaseIndustrialSkill):
    """Deterministically compare an independent tree count with metadata."""

    def __init__(self, *, max_allowed_delta: int = 0) -> None:
        if (
            isinstance(max_allowed_delta, bool)
            or not isinstance(max_allowed_delta, int)
            or max_allowed_delta < 0
        ):
            raise ValueError("max_allowed_delta must be a non-negative integer")
        self._max_allowed_delta = max_allowed_delta
        self._manifest = IndustrialSkillManifest(
            skill_id="visiondata-gate.metadata-count-drift",
            skill_version="1.0.0",
            display_name="Metadata Count Drift",
            purpose=(
                "Compare two independently produced image counts and report an "
                "auditable metadata reconciliation observation."
            ),
            algorithm_id="absolute-count-delta",
            algorithm_version="1.0.0",
            required_measurements=(
                "metadata_image_count",
                "tree_image_count",
            ),
            frozen_parameters=(
                FrozenNumericParameter(
                    name="max_allowed_delta",
                    value=float(max_allowed_delta),
                    unit="images",
                ),
            ),
            license_spdx="Apache-2.0",
            claim_boundary=(
                "This deterministic comparison is a read-only observation. It does "
                "not prove source authorization, dataset completeness, customer "
                "acceptance, or production release eligibility."
            ),
        )

    @property
    def manifest(self) -> IndustrialSkillManifest:
        return self._manifest

    def inspect(self, invocation: IndustrialSkillInvocation) -> IndustrialSkillOutcome:
        measurements = {item.name: item for item in invocation.measurements}
        metadata_count = measurements["metadata_image_count"]
        tree_count = measurements["tree_image_count"]
        values = (metadata_count.value, tree_count.value)
        if any(value < 0 or not value.is_integer() for value in values):
            return _deferred_outcome(
                self.manifest,
                invocation,
                reason_code="INVALID_MEASUREMENT_VALUE",
                safe_detail="Image counts must be non-negative whole numbers.",
            )

        delta = abs(metadata_count.value - tree_count.value)
        is_anomaly = delta > self._max_allowed_delta
        observation = IndustrialSkillObservation(
            observation_id=f"{invocation.invocation_id}.metadata-count-drift",
            measurement_name="metadata_count_absolute_delta",
            unit="images",
            decision=NumericAnomalyDecision(
                observed_value=delta,
                operator="gt",
                threshold_value=float(self._max_allowed_delta),
                is_anomaly=is_anomaly,
            ),
            severity_if_anomalous="high",
            reason_code=("METADATA_COUNT_DRIFT" if is_anomaly else "COUNT_MATCH"),
            summary=(
                f"The independent counts differ by {int(delta)} image(s)."
                if is_anomaly
                else "The independent counts match within the frozen tolerance."
            ),
            recommended_action=(
                "Reconcile the metadata inventory before downstream release review."
                if is_anomaly
                else "Retain the receipt as supporting evidence; no release is granted."
            ),
            algorithm_version=self.manifest.algorithm_version,
            evidence_spans=(
                metadata_count.evidence_span,
                tree_count.evidence_span,
            ),
        )
        return IndustrialSkillOutcome(
            invocation_id=invocation.invocation_id,
            skill_id=self.manifest.skill_id,
            skill_version=self.manifest.skill_version,
            algorithm_version=self.manifest.algorithm_version,
            source=invocation.source,
            status="OK",
            observations=(observation,),
            claim_boundary=self.manifest.claim_boundary,
        )


def build_default_industrial_skill_registry() -> IndustrialSkillRegistry:
    """Return the reviewed built-in registry; no plugin discovery is performed."""

    return IndustrialSkillRegistry((MetadataCountDriftSkill(),))


__all__ = [
    "BaseIndustrialSkill",
    "FrozenNumericParameter",
    "IndustrialEvidenceSpan",
    "IndustrialMeasurement",
    "IndustrialSkillDependency",
    "IndustrialSkillFailure",
    "IndustrialSkillInvocation",
    "IndustrialSkillManifest",
    "IndustrialSkillObservation",
    "IndustrialSkillOutcome",
    "IndustrialSkillReceipt",
    "IndustrialSkillRegistry",
    "IndustrialSourceSnapshot",
    "MetadataCountDriftSkill",
    "NumericAnomalyDecision",
    "build_default_industrial_skill_registry",
    "verify_industrial_skill_receipt",
]
