"""A real custom Skill subclass, using only synthetic in-memory measurements."""

from copy import deepcopy
import importlib
import importlib.util
import json

import pytest

from visiondata_gate.industrial_skills import (
    BaseIndustrialSkill,
    IndustrialSkillInvocation,
    IndustrialSkillRegistry,
    verify_industrial_skill_receipt,
)


def example():
    assert importlib.util.find_spec("examples.reuse.custom_range_skill") is not None, (
        "the custom deterministic range Skill example must exist"
    )
    return importlib.import_module("examples.reuse.custom_range_skill")


@pytest.mark.parametrize(
    "mean,expected",
    [
        (0, (True, False)),
        (64, (False, False)),
        (128, (False, False)),
        (192, (False, False)),
        (255, (False, True)),
    ],
)
def test_custom_subclass_checks_both_bounds_without_granting_authority(mean, expected):
    module = example()
    skill = module.ExposureMeanRangeSkill()
    assert isinstance(skill, BaseIndustrialSkill)
    manifest = skill.manifest
    assert manifest.skill_id == "example.exposure-mean-range"
    assert manifest.skill_version == "1.0.0"
    assert manifest.required_measurements == ("exposure_mean",)
    assert {item.name: item.value for item in manifest.frozen_parameters} == {
        "lower_mean": 64.0,
        "upper_mean": 192.0,
    }
    assert manifest.license_spdx == "Apache-2.0"
    for marker in ("synthetic", "not an OS sandbox", "production release"):
        assert marker in manifest.claim_boundary
    request = module.build_synthetic_invocation(mean)
    registry = IndustrialSkillRegistry()
    assert registry.register(skill) == manifest
    receipt = registry.invoke(manifest.skill_id, "1.0.0", request)
    assert verify_industrial_skill_receipt(receipt)
    assert receipt.outcome.status == "OK"
    assert (
        tuple(item.decision.is_anomaly for item in receipt.outcome.observations)
        == expected
    )
    assert tuple(item.decision.operator for item in receipt.outcome.observations) == (
        "lt",
        "gt",
    )
    assert all(
        item.decision.observed_value == mean for item in receipt.outcome.observations
    )
    assert receipt.outcome.actual_model_call_count == 0
    assert receipt.outcome.network_call_count == 0
    assert receipt.outcome.machine_write_count == 0
    assert receipt.outcome.production_decision_authority is False
    assert manifest.network_access_permitted is False
    assert manifest.machine_write_permitted is False
    assert manifest.raw_bytes_available is False
    for observation in receipt.outcome.observations:
        assert observation.machine_action_permitted is False
        assert (
            observation.evidence_spans[0].snapshot_sha256
            == request.source.snapshot_sha256
        )
        assert observation.evidence_spans[0].selector == "/metrics/exposure_mean"
    with pytest.raises(KeyError):
        registry.invoke(manifest.skill_id, "latest", request)


def test_missing_required_measurement_defers_with_verified_failure_receipt():
    receipt = example().run_example(include_measurement=False)
    assert receipt.outcome.status == "DEFER"
    assert receipt.outcome.failure.reason_code == "MISSING_REQUIRED_MEASUREMENT"
    assert receipt.outcome.observations == ()
    assert verify_industrial_skill_receipt(receipt)


@pytest.mark.parametrize(
    "mean", [True, -1, 256, float("nan"), float("inf"), -float("inf"), "128", None]
)
def test_synthetic_input_rejects_invalid_or_nonfinite_mean(mean):
    with pytest.raises(ValueError):
        example().run_example(mean)


@pytest.mark.parametrize(
    "lower,upper",
    [
        (100, 100),
        (192, 64),
        (-1, 200),
        (64, 256),
        (True, 192),
        (64, float("inf")),
        ("64", 192),
    ],
)
def test_custom_parameters_must_be_a_finite_ordered_pixel_range(lower, upper):
    with pytest.raises(ValueError):
        example().ExposureMeanRangeSkill(lower=lower, upper=upper)


def test_snapshot_parameters_and_receipts_are_deterministic_and_input_sensitive():
    module = example()
    first = module.run_example(128)
    assert module.run_example(128.0) == first
    changed_input = module.run_example(129)
    assert (
        changed_input.invocation.source.snapshot_sha256
        != first.invocation.source.snapshot_sha256
    )
    assert changed_input.invocation_sha256 != first.invocation_sha256
    assert changed_input.receipt_sha256 != first.receipt_sha256
    changed_parameters = module.run_example(128, lower=60)
    assert changed_parameters.manifest_sha256 != first.manifest_sha256
    assert changed_parameters.receipt_sha256 != first.receipt_sha256


def test_registered_manifest_drift_fails_closed_before_inspection():
    module = example()
    skill = module.ExposureMeanRangeSkill()
    registry = IndustrialSkillRegistry((skill,))
    original = skill.manifest
    skill._manifest = original.model_copy(update={"algorithm_version": "1.0.1"})
    receipt = registry.invoke(
        original.skill_id, original.skill_version, module.build_synthetic_invocation()
    )
    assert receipt.outcome.status == "DEFER"
    assert receipt.outcome.failure.reason_code == "SKILL_MANIFEST_DRIFT"
    assert receipt.manifest == original
    assert verify_industrial_skill_receipt(receipt)


@pytest.mark.parametrize("part", ["manifest", "invocation", "outcome", "receipt"])
def test_tampered_custom_receipt_is_rejected(part):
    receipt = deepcopy(example().run_example())
    if part == "manifest":
        receipt = receipt.model_copy(
            update={
                "manifest": receipt.manifest.model_copy(
                    update={"algorithm_version": "1.0.1"}
                )
            }
        )
    elif part == "invocation":
        receipt = receipt.model_copy(
            update={
                "invocation": receipt.invocation.model_copy(
                    update={"invocation_id": "other-invocation"}
                )
            }
        )
    elif part == "outcome":
        receipt = receipt.model_copy(
            update={
                "outcome": receipt.outcome.model_copy(
                    update={
                        "claim_boundary": "Tampered claim boundary must not verify as the original evidence receipt."
                    }
                )
            }
        )
    else:
        receipt = receipt.model_copy(update={"receipt_sha256": "0" * 64})
    assert verify_industrial_skill_receipt(receipt) is False


@pytest.mark.parametrize(
    "change",
    [
        {"value": -1.0},
        {"value": 256.0},
        {"unit": "seconds"},
        {"measurement_version": "2.0.0"},
    ],
)
def test_direct_sdk_invocation_rejects_out_of_range_or_wrong_unit_measurement(change):
    module = example()
    request = module.build_synthetic_invocation()
    measurements = tuple(
        item.model_copy(update=change) if item.name == "exposure_mean" else item
        for item in request.measurements
    )
    request = IndustrialSkillInvocation.model_validate(
        request.model_dump(mode="python") | {"measurements": measurements}
    )
    skill = module.ExposureMeanRangeSkill()
    receipt = IndustrialSkillRegistry((skill,)).invoke(
        skill.manifest.skill_id, skill.manifest.skill_version, request
    )
    assert receipt.outcome.status == "DEFER"
    assert receipt.outcome.failure.reason_code == "INVALID_MEASUREMENT_VALUE"
    assert verify_industrial_skill_receipt(receipt)


@pytest.mark.parametrize(
    "args,status,anomaly,exit_code",
    [
        (["--mean", "128"], "OK", False, 0),
        (["--mean", "230"], "OK", True, 0),
        (["--omit-measurement"], "DEFER", None, 1),
    ],
)
def test_cli_reports_scope_and_verified_result_without_writing_files(
    capsys, args, status, anomaly, exit_code
):
    assert example().main(args) == exit_code
    output = json.loads(capsys.readouterr().out)
    assert output["scope"] == "SYNTHETIC_CUSTOM_SKILL_EXAMPLE"
    assert output["status"] == status
    assert output["is_anomaly"] is anomaly
    assert output["receipt_verified"] is True
    assert output["production_release_allowed"] is False
    assert output["actual_model_call_count"] == 0
    assert output["network_call_count"] == 0


def test_cli_rejects_invalid_input_without_a_success_receipt(capsys):
    with pytest.raises(SystemExit) as error:
        example().main(["--mean", "nan"])
    assert error.value.code == 2
    assert capsys.readouterr().out == ""


def test_receipt_verification_failure_is_not_silently_reported_as_success(monkeypatch):
    module = example()
    monkeypatch.setattr(
        module, "verify_industrial_skill_receipt", lambda receipt: False
    )
    with pytest.raises(RuntimeError, match="verification"):
        module.run_example()


def test_huge_integer_is_a_normal_input_validation_error():
    with pytest.raises(ValueError):
        example().run_example(10**1000)


def test_example_runs_without_file_network_or_process_operations(monkeypatch):
    import builtins
    import io
    import socket
    import subprocess

    module = example()

    def forbidden(*args, **kwargs):
        pytest.fail("the in-memory custom Skill attempted external I/O")

    with monkeypatch.context() as guard:
        guard.setattr(builtins, "open", forbidden)
        guard.setattr(io, "open", forbidden)
        guard.setattr(socket, "socket", forbidden)
        guard.setattr(socket, "create_connection", forbidden)
        guard.setattr(subprocess, "Popen", forbidden)
        receipt = module.run_example()
    assert verify_industrial_skill_receipt(receipt)


def test_direct_inspection_of_missing_measurement_defers():
    module = example()
    outcome = module.ExposureMeanRangeSkill().inspect(
        module.build_synthetic_invocation(include_measurement=False)
    )
    assert outcome.status == "DEFER"
    assert outcome.failure.reason_code == "MISSING_REQUIRED_MEASUREMENT"


def test_measurement_inclusion_flag_requires_a_real_boolean():
    with pytest.raises(ValueError):
        example().build_synthetic_invocation(include_measurement=1)
