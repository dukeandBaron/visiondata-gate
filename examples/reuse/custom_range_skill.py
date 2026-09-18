# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 VisionData Gate contributors
"""Define and explicitly register a trusted custom range-checking Skill.

All inputs are synthetic scalar measurements built in memory. No image is opened,
no plugin is discovered, and no network, model or machine-control API is called.
The bounds are illustrative, not factory calibration or a defect-truth rule.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math

from visiondata_gate.industrial_skills import (
    BaseIndustrialSkill,
    FrozenNumericParameter,
    IndustrialEvidenceSpan,
    IndustrialMeasurement,
    IndustrialSkillDependency,
    IndustrialSkillFailure,
    IndustrialSkillInvocation,
    IndustrialSkillManifest,
    IndustrialSkillObservation,
    IndustrialSkillOutcome,
    IndustrialSkillReceipt,
    IndustrialSkillRegistry,
    IndustrialSourceSnapshot,
    NumericAnomalyDecision,
    verify_industrial_skill_receipt,
)


MEASUREMENT_NAME = "exposure_mean"
MEASUREMENT_VERSION = "1.0.0"
MEASUREMENT_UNIT = "gray_level_0_255"
SCOPE = "SYNTHETIC_CUSTOM_SKILL_EXAMPLE"


def _level(value: float, name: str) -> float:
    if (
        type(value) not in (int, float)
        or not 0 <= value <= 255
        or not math.isfinite(value)
    ):
        raise ValueError(f"{name} must be a finite numeric value between 0 and 255")
    # A canonical float keeps integer and float spellings of the same value equal.
    return float(value)


class ExposureMeanRangeSkill(BaseIndustrialSkill):
    """Compare one supplied mean with inclusive, manifest-frozen bounds.

    Only the host can supply measurements. This class does not compute an image
    mean, validate a camera, discover plugins or authorize production decisions.
    """

    def __init__(self, *, lower: float = 64, upper: float = 192) -> None:
        lower = _level(lower, "lower")
        upper = _level(upper, "upper")
        if lower >= upper:
            raise ValueError("lower must be strictly less than upper")
        self._manifest = IndustrialSkillManifest(
            skill_id="example.exposure-mean-range",
            skill_version="1.0.0",
            display_name="Synthetic Exposure Mean Range",
            purpose=(
                "Compare a host-supplied synthetic exposure mean against frozen "
                "illustrative bounds and return evidence-bound observations."
            ),
            algorithm_id="inclusive-exposure-mean-range",
            algorithm_version="1.0.0",
            required_measurements=(MEASUREMENT_NAME,),
            frozen_parameters=(
                FrozenNumericParameter(
                    name="lower_mean", value=lower, unit=MEASUREMENT_UNIT
                ),
                FrozenNumericParameter(
                    name="upper_mean", value=upper, unit=MEASUREMENT_UNIT
                ),
            ),
            third_party_dependencies=(
                IndustrialSkillDependency(
                    package="visiondata-gate",
                    version_spec="==0.1.0",
                    license_spdx="Apache-2.0",
                ),
            ),
            license_spdx="Apache-2.0",
            claim_boundary=(
                "This trusted in-process example checks a synthetic mean against "
                "illustrative bounds. It is not an OS sandbox, image decoding, "
                "factory calibration, defect truth, model inference, source "
                "authorization, or production release."
            ),
        )

    @property
    def manifest(self) -> IndustrialSkillManifest:
        return self._manifest

    def inspect(self, invocation: IndustrialSkillInvocation) -> IndustrialSkillOutcome:
        mean = next(
            (item for item in invocation.measurements if item.name == MEASUREMENT_NAME),
            None,
        )
        identity = {
            "invocation_id": invocation.invocation_id,
            "skill_id": self.manifest.skill_id,
            "skill_version": self.manifest.skill_version,
            "algorithm_version": self.manifest.algorithm_version,
            "source": invocation.source,
            "claim_boundary": self.manifest.claim_boundary,
        }
        # The Registry checks this before inspect; retain fail-closed direct use too.
        if mean is None:
            return IndustrialSkillOutcome(
                **identity,
                status="DEFER",
                failure=IndustrialSkillFailure(
                    reason_code="MISSING_REQUIRED_MEASUREMENT",
                    safe_detail="The exposure mean measurement is absent.",
                ),
            )
        if (
            not math.isfinite(mean.value)
            or not 0 <= mean.value <= 255
            or mean.unit != MEASUREMENT_UNIT
            or mean.measurement_version != MEASUREMENT_VERSION
        ):
            return IndustrialSkillOutcome(
                **identity,
                status="DEFER",
                failure=IndustrialSkillFailure(
                    reason_code="INVALID_MEASUREMENT_VALUE",
                    safe_detail="Exposure mean requires finite 0-255 levels and the exact unit/version.",
                ),
            )
        # Consume the frozen manifest values, not a second mutable configuration.
        bounds = {item.name: item.value for item in self.manifest.frozen_parameters}
        observations = []
        for name, operator, anomalous, reason in (
            (
                "lower_mean",
                "lt",
                mean.value < bounds["lower_mean"],
                "EXPOSURE_MEAN_BELOW_RANGE",
            ),
            (
                "upper_mean",
                "gt",
                mean.value > bounds["upper_mean"],
                "EXPOSURE_MEAN_ABOVE_RANGE",
            ),
        ):
            observations.append(
                IndustrialSkillObservation(
                    observation_id=f"{invocation.invocation_id}.{name}",
                    measurement_name=MEASUREMENT_NAME,
                    unit=MEASUREMENT_UNIT,
                    decision=NumericAnomalyDecision(
                        observed_value=mean.value,
                        operator=operator,
                        threshold_value=bounds[name],
                        is_anomaly=anomalous,
                    ),
                    severity_if_anomalous="medium",
                    reason_code=reason
                    if anomalous
                    else "EXPOSURE_MEAN_BOUND_SATISFIED",
                    summary=f"Synthetic exposure mean {mean.value:g}; frozen {name} is {bounds[name]:g}.",
                    recommended_action=(
                        "A human should check the supplied measurement and applicable calibration; no release is granted."
                        if anomalous
                        else "Retain this read-only observation; no release is granted."
                    ),
                    algorithm_version=self.manifest.algorithm_version,
                    evidence_spans=(mean.evidence_span,),
                )
            )
        return IndustrialSkillOutcome(
            **identity, status="OK", observations=tuple(observations)
        )


def build_synthetic_invocation(
    mean: float = 128, *, include_measurement: bool = True
) -> IndustrialSkillInvocation:
    """Build a path-free synthetic source and its explicit evidence selectors."""
    mean = _level(mean, "mean")
    if type(include_measurement) is not bool:
        raise ValueError("include_measurement must be a boolean")
    metrics = {"synthetic_sample_count": 1.0}
    if include_measurement:
        metrics[MEASUREMENT_NAME] = mean
    fixture_bytes = json.dumps(
        {"scope": SCOPE, "metrics": metrics},
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")
    source = IndustrialSourceSnapshot(
        source_id="synthetic-exposure-metrics",
        source_kind="redacted_batch_snapshot",
        source_version="example-1.0.0",
        snapshot_sha256=hashlib.sha256(fixture_bytes).hexdigest(),
    )
    measurements = tuple(
        IndustrialMeasurement(
            name=name,
            value=value,
            unit=MEASUREMENT_UNIT if name == MEASUREMENT_NAME else "samples",
            measurement_version=MEASUREMENT_VERSION,
            evidence_span=IndustrialEvidenceSpan(
                source_id=source.source_id,
                source_version=source.source_version,
                snapshot_sha256=source.snapshot_sha256,
                span_kind="metric",
                selector=f"/metrics/{name}",
            ),
        )
        for name, value in metrics.items()
    )
    return IndustrialSkillInvocation(
        invocation_id="synthetic-exposure-range-1",
        source=source,
        measurements=measurements,
    )


def run_example(
    mean: float = 128,
    *,
    lower: float = 64,
    upper: float = 192,
    include_measurement: bool = True,
) -> IndustrialSkillReceipt:
    """Register this exact custom instance and return its independently checked seal."""
    skill = ExposureMeanRangeSkill(lower=lower, upper=upper)
    registry = IndustrialSkillRegistry()
    manifest = registry.register(skill)
    invocation = build_synthetic_invocation(
        mean, include_measurement=include_measurement
    )
    receipt = registry.invoke(manifest.skill_id, manifest.skill_version, invocation)
    if not verify_industrial_skill_receipt(receipt):
        raise RuntimeError("Custom Skill receipt verification failed")
    return receipt


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--mean", type=float, default=128)
    parser.add_argument("--lower", type=float, default=64)
    parser.add_argument("--upper", type=float, default=192)
    parser.add_argument("--omit-measurement", action="store_true")
    args = parser.parse_args(argv)
    try:
        receipt = run_example(
            args.mean,
            lower=args.lower,
            upper=args.upper,
            include_measurement=not args.omit_measurement,
        )
    except ValueError as error:
        parser.error(str(error))
    print(
        json.dumps(
            {
                "scope": SCOPE,
                "status": receipt.outcome.status,
                "skill_id": receipt.manifest.skill_id,
                "skill_version": receipt.manifest.skill_version,
                "mean": args.mean,
                "lower": args.lower,
                "upper": args.upper,
                "is_anomaly": (
                    any(
                        item.decision.is_anomaly
                        for item in receipt.outcome.observations
                    )
                    if receipt.outcome.status == "OK"
                    else None
                ),
                "failure_reason": receipt.outcome.failure.reason_code
                if receipt.outcome.failure
                else None,
                "receipt_verified": True,
                "receipt_sha256": receipt.receipt_sha256,
                "manifest_sha256": receipt.manifest_sha256,
                "actual_model_call_count": receipt.outcome.actual_model_call_count,
                "network_call_count": receipt.outcome.network_call_count,
                "machine_write_count": receipt.outcome.machine_write_count,
                "production_release_allowed": False,
            },
            indent=2,
            allow_nan=False,
        )
    )
    return 0 if receipt.outcome.status == "OK" else 1


if __name__ == "__main__":
    raise SystemExit(main())
