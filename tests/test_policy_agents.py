from __future__ import annotations

from pathlib import Path

import pytest

from visiondata_gate.agents import build_council
from visiondata_gate.contracts import (
    BatchContract,
    BatchManifest,
    EvidenceStatus,
    Finding,
    GateDecision,
    RuleCheckResult,
    SampleRecord,
    Severity,
    ToolTrace,
)
from visiondata_gate.policy import apply_policy, build_scenario_rule_profile_snapshot
from visiondata_gate.runtime_models import ScenarioProfile
from visiondata_gate.rulepack import (
    build_rule_pack_runtime_binding,
    load_rule_pack,
)


SHA256_ZERO = "0" * 64
SHA256_ONE = "1" * 64
RULEPACK = Path(__file__).resolve().parents[1] / "rulepacks" / "industrial-v1.json"


def _manifest() -> BatchManifest:
    return BatchManifest(
        batch_id="batch-dirty",
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


def _trace(*, status: str = "ok", error: str | None = None) -> ToolTrace:
    return ToolTrace(
        sequence=1,
        tool="image_quality",
        status=status,
        input_sha256=SHA256_ZERO,
        result_sha256=SHA256_ONE,
        error=error,
    )


def _finding(code: str, action: str = "recapture") -> Finding:
    return Finding(
        finding_id=f"finding-{code}",
        code=code,
        severity=Severity.HIGH,
        tool="image_quality",
        sample_ids=["sample-1"],
        summary=f"Detected {code}",
        evidence={"category": "bearing", "view": "front"},
        evidence_status=EvidenceStatus.VERIFIED,
        recommended_action=action,
    )


def test_council_discloses_shared_ai_backend_and_cross_examines() -> None:
    council = build_council([_finding("LOW_SHARPNESS")], [_trace()], {"n": 1})

    assert len(council.independent_opinions) == 6
    assert all(
        opinion.display_name.startswith("AI ")
        for opinion in council.independent_opinions
    )
    assert all(
        opinion.required_additional_evidence for opinion in council.independent_opinions
    )
    disclosure = council.shared_model_disclosure.lower()
    assert "shared backend" in disclosure
    assert "not independent evidence" in disclosure
    assert "vote" in disclosure
    assert len(council.cross_examination) >= 5
    assert all(opinion.challenge for opinion in council.independent_opinions)


def test_tool_error_forces_defer_and_investigation_work_order() -> None:
    traces = [_trace(status="error", error="decoder unavailable")]
    council = build_council([], traces, {})

    result = apply_policy(_manifest(), BatchContract(), [], traces, {}, council)

    assert result.decision is GateDecision.DEFER
    assert result.work_orders
    assert result.work_orders[0].action == "INVESTIGATE"
    assert result.human_authority_required_before_production is True
    assert result.rule_checks
    assert any(check.check_id == "RC-TRACE-OK" for check in result.rule_checks)


def test_clean_evidence_passes_only_for_sandbox_scope() -> None:
    traces = [_trace()]
    council = build_council([], traces, {"checked": 1})

    result = apply_policy(
        _manifest(), BatchContract(), [], traces, {"checked": 1}, council
    )

    assert result.decision is GateDecision.PASS
    assert result.release_scope == "sandbox_experiment_training_pool"
    assert "sandbox" in result.decision_reason.lower()
    assert not result.work_orders
    assert any(check.status.value == "PASS" for check in result.rule_checks)


def test_generic_profile_keeps_core_checks_only() -> None:
    traces = [
        _tool_trace("image_quality"),
        _tool_trace("duplicate_leakage"),
        _tool_trace("annotation_integrity"),
        _tool_trace("coverage_matrix"),
    ]
    council = build_council([], traces, {"tool_count": 4})

    result = apply_policy(
        _manifest(),
        BatchContract(),
        [],
        traces,
        {"tool_count": 4},
        council,
        scenario_profile=ScenarioProfile.GENERIC,
    )

    check_ids = {check.check_id for check in result.rule_checks}
    assert result.decision is GateDecision.PASS
    assert all("COUNTERFACTUAL" not in check_id for check_id in check_ids)


def test_scenario_rule_profile_snapshot_is_stable_and_complete() -> None:
    snapshot = build_scenario_rule_profile_snapshot(ScenarioProfile.INDUSTRIAL)

    assert snapshot["scenario_profile"] == "industrial"
    assert snapshot["require_governance_metrics"] is True
    assert snapshot["min_tool_count"] == 5
    assert snapshot["counters"]["counterfactual_tool_probe_budget"] == 3
    assert "COUNTERFACTUAL-FINDING" in snapshot["rule_packages"]
    assert "RC-COUNTERFACTUAL-TOOL-REMOVE-1" in snapshot["enabled_checks"]


def test_quality_finding_requires_recapture() -> None:
    finding = _finding("LOW_SHARPNESS")
    traces = [_trace()]
    council = build_council([finding], traces, {})

    result = apply_policy(_manifest(), BatchContract(), [finding], traces, {}, council)

    assert result.decision is GateDecision.RECAPTURE
    assert [order.action for order in result.work_orders] == ["RECAPTURE"]
    assert result.work_orders[0].sample_ids == ["sample-1"]


def test_activated_rulepack_controls_actions_and_unknown_codes_fail_closed() -> None:
    pack = load_rule_pack(RULEPACK)
    investigate_capture = pack.rules[0].model_copy(update={"action": "INVESTIGATE"})
    runtime_binding = build_rule_pack_runtime_binding(
        pack.model_copy(update={"rules": [investigate_capture, *pack.rules[1:]]})
    )
    finding = _finding("LOW_SHARPNESS")

    result = apply_policy(
        _manifest(),
        BatchContract(),
        [finding],
        [_trace()],
        {},
        runtime_rulepack=runtime_binding,
    )

    assert result.decision is GateDecision.QUARANTINE
    assert result.work_orders[0].action == "INVESTIGATE"
    assert result.work_orders[0].replacement_requirements["rule_id"] == (
        "IQ.CAPTURE_QUALITY"
    )
    assert result.policy_version.endswith("visiondata-gate.industrial-v1@1.0.0")
    assert any(
        check.check_id == "RC-RULEPACK-RUNTIME-BINDING" for check in result.rule_checks
    )

    unknown = _finding("NEW_UNREGISTERED_DEFECT", "recapture")
    unknown_result = apply_policy(
        _manifest(),
        BatchContract(),
        [unknown],
        [_trace()],
        {},
        runtime_rulepack=runtime_binding,
    )
    assert unknown_result.work_orders[0].action == "INVESTIGATE"
    assert unknown_result.work_orders[0].replacement_requirements["rule_id"] == (
        "UNMATCHED_FAIL_CLOSED"
    )


def test_policy_rejects_model_copy_drift_in_rulepack_binding() -> None:
    binding = build_rule_pack_runtime_binding(RULEPACK)
    mutated_actions = dict(binding.action_by_finding_code)
    mutated_actions["LOW_SHARPNESS"] = "INVESTIGATE"
    stale_binding = binding.model_copy(
        update={"action_by_finding_code": mutated_actions}
    )

    with pytest.raises(ValueError, match="failed integrity validation"):
        apply_policy(
            _manifest(),
            BatchContract(),
            [_finding("LOW_SHARPNESS")],
            [_trace()],
            {},
            runtime_rulepack=stale_binding,
        )


@pytest.mark.parametrize(
    ("status", "error"),
    [
        ("error", "decoder unavailable"),
        ("skipped", None),
    ],
)
def test_incomplete_trace_work_order_binds_rulepack_and_id(
    status: str,
    error: str | None,
) -> None:
    pack = load_rule_pack(RULEPACK)
    binding = build_rule_pack_runtime_binding(pack)
    changed_binding = build_rule_pack_runtime_binding(
        pack.model_copy(update={"version": "1.0.1"})
    )
    traces = [_trace(status=status, error=error)]

    unbound = apply_policy(_manifest(), BatchContract(), [], traces, {})
    bound = apply_policy(
        _manifest(),
        BatchContract(),
        [],
        traces,
        {},
        runtime_rulepack=binding,
    )
    changed = apply_policy(
        _manifest(),
        BatchContract(),
        [],
        traces,
        {},
        runtime_rulepack=changed_binding,
    )

    order = bound.work_orders[0]
    requirements = order.replacement_requirements
    assert requirements["rule_pack_source_sha256"] == binding.source_sha256
    assert requirements["rule_pack_semantic_sha256"] == binding.semantic_sha256
    assert requirements["rule_pack_binding_sha256"] == binding.binding_sha256
    assert requirements["rule_id"] == "GV.EVIDENCE_CONFLICT"
    assert order.work_order_id != unbound.work_orders[0].work_order_id
    assert order.work_order_id != changed.work_orders[0].work_order_id


def test_missing_trace_work_order_binds_rulepack_and_id() -> None:
    pack = load_rule_pack(RULEPACK)
    binding = build_rule_pack_runtime_binding(pack)
    changed_binding = build_rule_pack_runtime_binding(
        pack.model_copy(update={"version": "1.0.1"})
    )

    unbound = apply_policy(_manifest(), BatchContract(), [], [], {})
    bound = apply_policy(
        _manifest(),
        BatchContract(),
        [],
        [],
        {},
        runtime_rulepack=binding,
    )
    changed = apply_policy(
        _manifest(),
        BatchContract(),
        [],
        [],
        {},
        runtime_rulepack=changed_binding,
    )

    order = bound.work_orders[0]
    requirements = order.replacement_requirements
    assert requirements["rule_pack_source_sha256"] == binding.source_sha256
    assert requirements["rule_pack_semantic_sha256"] == binding.semantic_sha256
    assert requirements["rule_pack_binding_sha256"] == binding.binding_sha256
    assert requirements["rule_id"] == "UNMATCHED_FAIL_CLOSED"
    assert order.work_order_id != unbound.work_orders[0].work_order_id
    assert order.work_order_id != changed.work_orders[0].work_order_id


def test_duplicate_finding_quarantines_and_requests_repartition() -> None:
    finding = _finding("CROSS_SPLIT_NEAR_DUPLICATE", "remove or repartition")
    traces = [_trace()]
    council = build_council([finding], traces, {})

    result = apply_policy(_manifest(), BatchContract(), [finding], traces, {}, council)

    assert result.decision is GateDecision.QUARANTINE
    assert [order.action for order in result.work_orders] == ["REMOVE_OR_REPARTITION"]


def test_scenario_profile_finance_requires_governance_metrics_for_pass() -> None:
    traces = [_trace()]
    council = build_council([], traces, {})

    result = apply_policy(
        _manifest(),
        BatchContract(),
        [],
        traces,
        {"tool_count": 5},
        council,
        scenario_profile=ScenarioProfile.FINANCE,
    )

    assert result.decision is GateDecision.DEFER
    checks = {check.check_id: check for check in result.rule_checks}
    assert checks["RC-GOVERNANCE-SCOPE"].status is RuleCheckResult.FAIL


def test_scenario_profile_finance_counterfactual_is_strict() -> None:
    finding = _finding("LOW_SHARPNESS")
    traces = [_trace()]
    council = build_council([finding], traces, {})

    result = apply_policy(
        _manifest(),
        BatchContract(),
        [finding],
        traces,
        {"tool_count": 5},
        council,
        scenario_profile=ScenarioProfile.FINANCE,
    )
    check = next(
        check
        for check in result.rule_checks
        if check.check_id == "RC-COUNTERFACTUAL-REMOVE-1"
    )
    assert check.status is RuleCheckResult.FAIL


def test_scenario_profile_industrial_counterfactual_tolerance() -> None:
    finding = _finding("LOW_SHARPNESS")
    traces = [_trace()]
    council = build_council([finding], traces, {})

    result = apply_policy(
        _manifest(),
        BatchContract(),
        [finding],
        traces,
        {"tool_count": 5},
        council,
        scenario_profile=ScenarioProfile.INDUSTRIAL,
    )
    check = next(
        check
        for check in result.rule_checks
        if check.check_id == "RC-COUNTERFACTUAL-REMOVE-1"
    )
    assert check.status is RuleCheckResult.PASS


def test_governance_scope_gap_with_missing_cells_is_reserve_actionable() -> None:
    finding = Finding(
        finding_id="gov-gap",
        code="GOVERNANCE_SCOPE_GAP",
        severity=Severity.HIGH,
        tool="governance_audit",
        summary="one required cell is missing",
        evidence={
            "missing_cells": [
                {
                    "split": "train",
                    "category": "gear",
                    "view": "side",
                    "condition": "dim",
                    "observed_count": 0,
                    "required_count": 1,
                }
            ]
        },
        recommended_action="investigate",
    )
    result = apply_policy(
        _manifest(),
        BatchContract(),
        [finding],
        [_tool_trace("governance_audit")],
        {
            "tool_count": 5,
            "governance_missing_cell_count": 1,
            "governance_unknown_cell_count": 0,
        },
        scenario_profile=ScenarioProfile.INDUSTRIAL,
    )
    assert result.work_orders[0].action == "RECAPTURE"
    assert result.work_orders[0].replacement_requirements["missing_cells"]


def test_scenario_profile_tool_counterfactual_is_stable_for_same_finding_traces() -> (
    None
):
    finding = _finding("LOW_SHARPNESS")
    traces = [
        _trace(),
        ToolTrace(
            sequence=2,
            tool="annotation_integrity",
            status="ok",
            input_sha256=SHA256_ZERO,
            result_sha256=SHA256_ONE,
            finding_ids=[finding.finding_id],
            parameters={"validator": "annotation"},
        ),
    ]
    council = build_council([finding], traces, {})

    result = apply_policy(
        _manifest(),
        BatchContract(),
        [finding],
        traces,
        {"tool_count": 5},
        council,
        scenario_profile=ScenarioProfile.INDUSTRIAL,
    )
    check = next(
        check
        for check in result.rule_checks
        if check.check_id == "RC-COUNTERFACTUAL-TOOL-REMOVE-1"
    )
    assert check.status is RuleCheckResult.PASS


def _tool_trace(tool: str) -> ToolTrace:
    return ToolTrace(
        sequence=1,
        tool=tool,
        status="ok",
        input_sha256=SHA256_ZERO,
        result_sha256=SHA256_ONE,
        finding_ids=[],
    )


def test_counterfactual_rule_stability_flagged_on_rule_flip_for_finance_profile() -> (
    None
):
    stable_finding = _finding("CROSS_SPLIT_NEAR_DUPLICATE")
    unsupported_finding = _finding("A_UNSUPPORTED").model_copy(
        update={
            "finding_id": "finding-U",
            "evidence_status": EvidenceStatus.UNSUPPORTED,
        }
    )
    tracing = [
        _tool_trace("image_quality"),
        _tool_trace("duplicate_leakage"),
        _tool_trace("annotation_integrity"),
        _tool_trace("coverage_matrix"),
        _tool_trace("governance_audit"),
    ]
    traces = [
        trace.model_copy(update={"sequence": i + 1}) for i, trace in enumerate(tracing)
    ]
    council = build_council([stable_finding, unsupported_finding], traces, {})

    result = apply_policy(
        _manifest(),
        BatchContract(),
        [stable_finding, unsupported_finding],
        traces,
        {
            "tool_count": 5,
            "governance_missing_cell_count": 0,
            "governance_unknown_cell_count": 0,
        },
        council,
        scenario_profile=ScenarioProfile.FINANCE,
    )
    check = next(
        check
        for check in result.rule_checks
        if check.check_id == "RC-COUNTERFACTUAL-RULE-STABILITY-1"
    )
    assert check.status is RuleCheckResult.FAIL


def test_counterfactual_tool_check_handles_dedupe_and_reorder_variants() -> None:
    finding = _finding("LOW_SHARPNESS")
    duplicate_trace = ToolTrace(
        sequence=2,
        tool="annotation_integrity",
        status="ok",
        input_sha256=SHA256_ZERO,
        result_sha256=SHA256_ONE,
        finding_ids=[finding.finding_id],
        parameters={"validator": "annotation"},
    )
    traces = [
        _tool_trace("image_quality"),
        ToolTrace(
            sequence=1,
            tool="annotation_integrity",
            status="ok",
            input_sha256=SHA256_ZERO,
            result_sha256=SHA256_ONE,
            finding_ids=[finding.finding_id],
            parameters={"validator": "annotation"},
        ),
        duplicate_trace,
        _tool_trace("duplicate_leakage"),
        _tool_trace("coverage_matrix"),
        _tool_trace("governance_audit"),
    ]
    council = build_council([finding], traces, {})

    result = apply_policy(
        _manifest(),
        BatchContract(),
        [finding],
        traces,
        {
            "tool_count": 6,
            "governance_missing_cell_count": 0,
            "governance_unknown_cell_count": 0,
        },
        council,
        scenario_profile=ScenarioProfile.INDUSTRIAL,
    )
    check = next(
        check
        for check in result.rule_checks
        if check.check_id == "RC-COUNTERFACTUAL-TOOL-REMOVE-1"
    )
    assert check.status is RuleCheckResult.PASS


def test_counterfactual_rule_stability_ignores_more_strict_fail_closed_flip() -> None:
    # Removing a tool can only make the scenario-tool rule stricter (PASS ->
    # FAIL).  That is a safe fail-closed transition and must not be reported as
    # instability.
    finding = _finding("LOW_SHARPNESS")
    traces = [_tool_trace("image_quality"), _tool_trace("annotation_integrity")]
    result = apply_policy(
        _manifest(),
        BatchContract(),
        [finding],
        traces,
        {"tool_count": 2},
        scenario_profile=ScenarioProfile.INDUSTRIAL,
    )
    check = next(
        check
        for check in result.rule_checks
        if check.check_id == "RC-COUNTERFACTUAL-RULE-STABILITY-1"
    )
    assert check.status is RuleCheckResult.PASS


def test_unsupported_high_severity_evidence_defers() -> None:
    finding = _finding("UNKNOWN_STRUCTURE")
    finding = finding.model_copy(update={"evidence_status": EvidenceStatus.UNSUPPORTED})
    traces = [_trace()]
    council = build_council([finding], traces, {})

    result = apply_policy(_manifest(), BatchContract(), [finding], traces, {}, council)

    assert result.decision is GateDecision.DEFER
    assert result.work_orders[0].action == "INVESTIGATE"


@pytest.mark.parametrize(
    ("code", "expected_action", "expected_decision"),
    [
        ("DECODE_FAILURE", "RECAPTURE", GateDecision.RECAPTURE),
        ("INVALID_DIMENSIONS", "RECAPTURE", GateDecision.RECAPTURE),
        ("LOW_SHARPNESS", "RECAPTURE", GateDecision.RECAPTURE),
        ("OVEREXPOSED", "RECAPTURE", GateDecision.RECAPTURE),
        ("UNDEREXPOSED", "RECAPTURE", GateDecision.RECAPTURE),
        ("COVERAGE_GAP", "RECAPTURE", GateDecision.RECAPTURE),
        ("EXACT_DUPLICATE", "REMOVE_OR_REPARTITION", GateDecision.QUARANTINE),
        (
            "CROSS_SPLIT_EXACT_DUPLICATE",
            "REMOVE_OR_REPARTITION",
            GateDecision.QUARANTINE,
        ),
        (
            "CROSS_SPLIT_NEAR_DUPLICATE",
            "REMOVE_OR_REPARTITION",
            GateDecision.QUARANTINE,
        ),
        ("MISSING_ANNOTATION", "RELABEL", GateDecision.QUARANTINE),
        (
            "ANNOTATION_DIMENSION_MISMATCH",
            "RELABEL",
            GateDecision.QUARANTINE,
        ),
    ],
)
def test_frozen_finding_codes_have_fixed_work_order_mapping(
    code: str, expected_action: str, expected_decision: GateDecision
) -> None:
    finding = _finding(code, "investigate")
    traces = [_trace()]

    result = apply_policy(
        _manifest(),
        BatchContract(),
        [finding],
        traces,
        {},
        build_council([finding], traces, {}),
    )

    assert result.work_orders[0].action == expected_action
    assert result.decision is expected_decision
