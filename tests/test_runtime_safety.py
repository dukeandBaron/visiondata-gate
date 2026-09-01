from __future__ import annotations

import pytest

from visiondata_gate.agents import build_council
from visiondata_gate.contracts import (
    BatchContract,
    BatchManifest,
    GateDecision,
    RuleCheckResult,
    SampleRecord,
    ToolTrace,
)
from visiondata_gate.policy import apply_policy
from visiondata_gate.runtime_models import ScenarioProfile
from visiondata_gate.runtime_safety import (
    RuntimeAction,
    RuntimeActorKind,
    RuntimeInvariantContext,
    RuntimeInvariantStatus,
    SafetyInvariantViolation,
    assert_runtime_invariants,
    build_runtime_invariant_receipt,
    verify_runtime_invariant_receipt,
)


SHA256_ZERO = "0" * 64
SHA256_ONE = "1" * 64


def _manifest() -> BatchManifest:
    return BatchManifest(
        batch_id="batch-runtime-safety",
        seed=7,
        samples=[
            SampleRecord(
                sample_id="sample-1",
                relative_path="images/sample-1.png",
                annotation_path="masks/sample-1.png",
                split="train",
                category="bearing",
                view="front",
                condition="bright",
            )
        ],
    )


def _trace() -> ToolTrace:
    return ToolTrace(
        sequence=1,
        tool="image_quality",
        status="ok",
        input_sha256=SHA256_ZERO,
        result_sha256=SHA256_ONE,
    )


def test_industrial_missing_required_tools_cannot_pass() -> None:
    traces = [_trace()]
    metrics = {"tool_count": 1}
    result = apply_policy(
        _manifest(),
        BatchContract(),
        [],
        traces,
        metrics,
        build_council([], traces, metrics),
        scenario_profile=ScenarioProfile.INDUSTRIAL,
    )

    assert result.decision is GateDecision.DEFER
    checks = {item.check_id: item for item in result.rule_checks}
    assert checks["RC-TOOL-COUNT"].status is RuleCheckResult.FAIL
    assert checks["RC-SCENARIO-TOOLS"].status is RuleCheckResult.FAIL
    assert checks["RC-RUNTIME-INVARIANT-GUARD"].status is RuleCheckResult.FAIL
    assert "RC-TOOL-COUNT" in result.decision_reason
    assert "RC-SCENARIO-TOOLS" in result.decision_reason


def test_generic_legacy_sandbox_pass_contract_is_unchanged() -> None:
    traces = [_trace()]
    result = apply_policy(
        _manifest(),
        BatchContract(),
        [],
        traces,
        {"checked": 1},
        build_council([], traces, {"checked": 1}),
        scenario_profile=ScenarioProfile.GENERIC,
    )

    assert result.decision is GateDecision.PASS
    guard = next(
        item
        for item in result.rule_checks
        if item.check_id == "RC-RUNTIME-INVARIANT-GUARD"
    )
    assert guard.status is RuleCheckResult.PASS


def test_runtime_invariant_receipt_is_deterministic_and_tamper_evident() -> None:
    context = RuntimeInvariantContext(
        action=RuntimeAction.GATE_PASS,
        scenario_profile=ScenarioProfile.INDUSTRIAL,
        input_sha256=SHA256_ZERO,
        failed_required_rule_check_ids=["RC-SCENARIO-TOOLS", "RC-TOOL-COUNT"],
    )

    first = build_runtime_invariant_receipt(context)
    second = build_runtime_invariant_receipt(context)

    assert first == second
    assert first.allowed is False
    assert first.outcomes[0].invariant_id == "INV-1"
    assert first.outcomes[0].status is RuntimeInvariantStatus.FAIL
    verify_runtime_invariant_receipt(first)

    tampered = first.model_copy(update={"allowed": True})
    with pytest.raises(ValueError, match="disposition mismatch"):
        verify_runtime_invariant_receipt(tampered)


def test_capa_child_machine_and_release_invariants_fail_closed() -> None:
    capa = build_runtime_invariant_receipt(
        RuntimeInvariantContext(
            action=RuntimeAction.EXECUTE_CAPA,
            actor_kind=RuntimeActorKind.AGENT,
            input_sha256=SHA256_ZERO,
            named_human_approver="ANONYMOUS",
        )
    )
    child = build_runtime_invariant_receipt(
        RuntimeInvariantContext(
            action=RuntimeAction.EXECUTE_CHILD_RUN,
            input_sha256=SHA256_ZERO,
            parent_source_readonly=False,
        )
    )
    machine = build_runtime_invariant_receipt(
        RuntimeInvariantContext(
            action=RuntimeAction.MACHINE_WRITE,
            input_sha256=SHA256_ZERO,
            machine_write_permitted=True,
        )
    )
    release = build_runtime_invariant_receipt(
        RuntimeInvariantContext(
            action=RuntimeAction.PRODUCTION_RELEASE,
            actor_kind=RuntimeActorKind.AGENT,
            input_sha256=SHA256_ZERO,
            production_release_allowed=True,
            open_responsibilities_count=43,
        )
    )

    assert capa.outcomes[1].status is RuntimeInvariantStatus.FAIL
    assert child.outcomes[2].status is RuntimeInvariantStatus.FAIL
    assert machine.outcomes[3].status is RuntimeInvariantStatus.FAIL
    assert release.outcomes[4].status is RuntimeInvariantStatus.FAIL
    assert release.outcomes[5].status is RuntimeInvariantStatus.FAIL
    with pytest.raises(SafetyInvariantViolation):
        assert_runtime_invariants(release.context)
