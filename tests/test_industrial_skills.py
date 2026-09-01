from __future__ import annotations

import pytest
from pydantic import ValidationError

from visiondata_gate.industrial_skills import (
    BaseIndustrialSkill,
    IndustrialEvidenceSpan,
    IndustrialMeasurement,
    IndustrialSkillInvocation,
    IndustrialSkillManifest,
    IndustrialSkillOutcome,
    IndustrialSkillRegistry,
    IndustrialSourceSnapshot,
    MetadataCountDriftSkill,
    build_default_industrial_skill_registry,
    verify_industrial_skill_receipt,
)


SOURCE_SHA256 = "a" * 64


def _invocation(
    *,
    metadata_count: float = 180,
    tree_count: float = 183,
) -> IndustrialSkillInvocation:
    source = IndustrialSourceSnapshot(
        source_id="omni-180-redacted",
        source_kind="authorized_metadata_snapshot",
        source_version="omni-profile-2026.08.28",
        snapshot_sha256=SOURCE_SHA256,
    )

    def measurement(name: str, value: float) -> IndustrialMeasurement:
        return IndustrialMeasurement(
            name=name,
            value=value,
            unit="images",
            measurement_version="1.0.0",
            evidence_span=IndustrialEvidenceSpan(
                source_id=source.source_id,
                source_version=source.source_version,
                snapshot_sha256=source.snapshot_sha256,
                span_kind="metric",
                selector=f"/metrics/{name}",
            ),
        )

    return IndustrialSkillInvocation(
        invocation_id="fixture-count-audit-001",
        source=source,
        measurements=(
            measurement("metadata_image_count", metadata_count),
            measurement("tree_image_count", tree_count),
        ),
    )


def test_default_registry_invokes_real_deterministic_example() -> None:
    registry = build_default_industrial_skill_registry()
    request = _invocation()

    first = registry.invoke(
        "visiondata-gate.metadata-count-drift",
        "1.0.0",
        request,
    )
    second = registry.invoke(
        "visiondata-gate.metadata-count-drift",
        "1.0.0",
        request,
    )

    assert first == second
    assert verify_industrial_skill_receipt(first) is True
    assert first.outcome.status == "OK"
    assert first.outcome.actual_model_call_count == 0
    assert first.outcome.network_call_count == 0
    assert first.outcome.machine_write_count == 0
    assert first.outcome.production_decision_authority is False
    observation = first.outcome.observations[0]
    assert observation.decision.observed_value == 3
    assert observation.decision.threshold_value == 0
    assert observation.decision.is_anomaly is True
    assert observation.reason_code == "METADATA_COUNT_DRIFT"
    assert observation.algorithm_version == "1.0.0"
    assert len(observation.evidence_spans) == 2
    for span in observation.evidence_spans:
        assert span.source_id == request.source.source_id
        assert span.source_version == request.source.source_version
        assert span.snapshot_sha256 == request.source.snapshot_sha256

    tampered = first.model_copy(update={"receipt_sha256": "b" * 64})
    assert verify_industrial_skill_receipt(tampered) is False


def test_equal_counts_are_observed_without_granting_release() -> None:
    registry = IndustrialSkillRegistry((MetadataCountDriftSkill(),))
    receipt = registry.invoke(
        "visiondata-gate.metadata-count-drift",
        "1.0.0",
        _invocation(metadata_count=180, tree_count=180),
    )

    observation = receipt.outcome.observations[0]
    assert receipt.outcome.status == "OK"
    assert observation.decision.is_anomaly is False
    assert observation.reason_code == "COUNT_MATCH"
    assert "no release is granted" in observation.recommended_action.lower()


def test_invocation_rejects_unbound_evidence_and_path_fields() -> None:
    request = _invocation()
    poisoned = request.measurements[0].model_copy(
        update={
            "evidence_span": request.measurements[0].evidence_span.model_copy(
                update={"source_version": "different-version"}
            )
        }
    )
    with pytest.raises(ValidationError, match="not bound to the source snapshot"):
        IndustrialSkillInvocation.model_validate(
            {
                **request.model_dump(mode="python"),
                "measurements": (poisoned, request.measurements[1]),
            }
        )

    with pytest.raises(ValidationError, match="Extra inputs are not permitted"):
        IndustrialSkillInvocation.model_validate(
            {
                **request.model_dump(mode="python"),
                "image_path": "C:\\private\\sample.png",
            }
        )


def test_registry_requires_explicit_instance_and_exact_version() -> None:
    registry = IndustrialSkillRegistry()
    manifest = registry.register(MetadataCountDriftSkill())
    assert registry.manifests() == (manifest,)

    with pytest.raises(ValueError, match="already registered"):
        registry.register(MetadataCountDriftSkill())
    with pytest.raises(TypeError, match="explicitly constructed"):
        registry.register("module:Skill")  # type: ignore[arg-type]
    with pytest.raises(KeyError, match="is not registered"):
        registry.invoke(
            manifest.skill_id,
            "2.0.0",
            _invocation(),
        )


def test_manifest_cannot_request_network_machine_write_or_raw_bytes() -> None:
    valid = MetadataCountDriftSkill().manifest.model_dump(mode="python")
    for field in (
        "network_access_permitted",
        "machine_write_permitted",
        "raw_bytes_available",
        "production_decision_authority",
    ):
        with pytest.raises(ValidationError):
            IndustrialSkillManifest.model_validate({**valid, field: True})


class _UnboundOutputSkill(BaseIndustrialSkill):
    def __init__(self) -> None:
        self._delegate = MetadataCountDriftSkill()

    @property
    def manifest(self) -> IndustrialSkillManifest:
        return self._delegate.manifest

    def inspect(self, invocation: IndustrialSkillInvocation) -> IndustrialSkillOutcome:
        outcome = self._delegate.inspect(invocation)
        forged_source = outcome.source.model_copy(update={"snapshot_sha256": "b" * 64})
        return outcome.model_copy(update={"source": forged_source})


def test_registry_fails_closed_on_unbound_output() -> None:
    registry = IndustrialSkillRegistry((_UnboundOutputSkill(),))
    receipt = registry.invoke(
        "visiondata-gate.metadata-count-drift",
        "1.0.0",
        _invocation(),
    )

    assert receipt.outcome.status == "DEFER"
    assert receipt.outcome.observations == ()
    assert receipt.outcome.failure is not None
    assert receipt.outcome.failure.reason_code == "SKILL_OUTPUT_CONTRACT_VIOLATION"
    assert verify_industrial_skill_receipt(receipt) is True


class _ExplodingSkill(_UnboundOutputSkill):
    def inspect(self, invocation: IndustrialSkillInvocation) -> IndustrialSkillOutcome:
        del invocation
        raise RuntimeError("C:\\private\\operator-token.txt")


def test_registry_sanitizes_plugin_exception_and_defers() -> None:
    registry = IndustrialSkillRegistry((_ExplodingSkill(),))
    receipt = registry.invoke(
        "visiondata-gate.metadata-count-drift",
        "1.0.0",
        _invocation(),
    )

    assert receipt.outcome.status == "DEFER"
    assert receipt.outcome.failure is not None
    assert receipt.outcome.failure.reason_code == "SKILL_EXECUTION_FAILED"
    serialized = receipt.model_dump_json()
    assert "operator-token" not in serialized
    assert "C:\\\\private" not in serialized


def test_missing_required_measurement_defers_before_plugin_call() -> None:
    request = _invocation()
    incomplete = IndustrialSkillInvocation(
        invocation_id=request.invocation_id,
        source=request.source,
        measurements=(request.measurements[0],),
    )
    receipt = build_default_industrial_skill_registry().invoke(
        "visiondata-gate.metadata-count-drift",
        "1.0.0",
        incomplete,
    )

    assert receipt.outcome.status == "DEFER"
    assert receipt.outcome.failure is not None
    assert receipt.outcome.failure.reason_code == "MISSING_REQUIRED_MEASUREMENT"
    assert receipt.outcome.observations == ()
