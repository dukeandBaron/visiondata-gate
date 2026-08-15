"""Deterministic release policy for the sandbox experiment training pool."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any, Literal

from .agents import build_council
from .contracts import (
    BatchContract,
    BatchManifest,
    CouncilTrace,
    EvidenceStatus,
    Finding,
    GateDecision,
    GateResult,
    Severity,
    RuleCheck,
    RuleCheckResult,
    ToolTrace,
    WorkOrder,
)
from .runtime_models import ScenarioProfile


WorkOrderAction = Literal[
    "RECAPTURE", "RELABEL", "REMOVE_OR_REPARTITION", "INVESTIGATE"
]


_RECAPTURE_KEYWORDS = (
    "COVERAGE",
    "MISSING_CELL",
    "UNDERREPRESENT",
    "DECODE",
    "DIMENSION",
    "RESOLUTION",
    "LUMA",
    "SHARP",
    "BLUR",
    "QUALITY",
)
_RELABEL_KEYWORDS = ("ANNOTATION", "MASK", "LABEL", "BBOX", "POLYGON")
_REPARTITION_KEYWORDS = ("DUPLICATE", "LEAK", "SPLIT")

_FROZEN_CODE_ACTIONS: dict[str, WorkOrderAction] = {
    "DECODE_FAILURE": "RECAPTURE",
    "INVALID_DIMENSIONS": "RECAPTURE",
    "LOW_SHARPNESS": "RECAPTURE",
    "OVEREXPOSED": "RECAPTURE",
    "UNDEREXPOSED": "RECAPTURE",
    "COVERAGE_GAP": "RECAPTURE",
    "EXACT_DUPLICATE": "REMOVE_OR_REPARTITION",
    "CROSS_SPLIT_EXACT_DUPLICATE": "REMOVE_OR_REPARTITION",
    "CROSS_SPLIT_NEAR_DUPLICATE": "REMOVE_OR_REPARTITION",
    "MISSING_ANNOTATION": "RELABEL",
    "ANNOTATION_DIMENSION_MISMATCH": "RELABEL",
}


@dataclass(frozen=True)
class _ScenarioRuleProfile:
    """Scenario-specific governance policy with bounded perturbation controls."""

    label: str
    require_governance_metrics: bool
    min_tool_count: int
    required_tool_names: tuple[str, ...]
    max_governance_missing_cells: int
    max_governance_unknown_cells: int
    counterfactual_probe_budget: int
    counterfactual_flip_tolerance: int
    counterfactual_tool_probe_budget: int
    counterfactual_tool_flip_tolerance: int
    rule_packages: tuple[str, ...]


_SCENARIO_RULEBOOK: dict[ScenarioProfile, _ScenarioRuleProfile] = {
    ScenarioProfile.GENERIC: _ScenarioRuleProfile(
        label="Generic",
        require_governance_metrics=False,
        min_tool_count=4,
        required_tool_names=(
            "image_quality",
            "duplicate_leakage",
            "annotation_integrity",
            "coverage_matrix",
        ),
        max_governance_missing_cells=0,
        max_governance_unknown_cells=0,
        counterfactual_probe_budget=0,
        counterfactual_flip_tolerance=99,
        counterfactual_tool_probe_budget=0,
        counterfactual_tool_flip_tolerance=99,
        rule_packages=("CORE",),
    ),
    ScenarioProfile.INDUSTRIAL: _ScenarioRuleProfile(
        label="Industrial",
        require_governance_metrics=True,
        min_tool_count=5,
        required_tool_names=(
            "image_quality",
            "duplicate_leakage",
            "annotation_integrity",
            "coverage_matrix",
            "governance_audit",
        ),
        max_governance_missing_cells=1,
        max_governance_unknown_cells=1,
        counterfactual_probe_budget=3,
        counterfactual_flip_tolerance=1,
        counterfactual_tool_probe_budget=3,
        counterfactual_tool_flip_tolerance=1,
        rule_packages=(
            "CORE",
            "COUNTERFACTUAL-FINDING",
            "COUNTERFACTUAL-TOOL",
            "RULE-STABILITY",
        ),
    ),
    ScenarioProfile.AUTOMOTIVE: _ScenarioRuleProfile(
        label="Automotive",
        require_governance_metrics=True,
        min_tool_count=5,
        required_tool_names=(
            "image_quality",
            "duplicate_leakage",
            "annotation_integrity",
            "coverage_matrix",
            "governance_audit",
        ),
        max_governance_missing_cells=0,
        max_governance_unknown_cells=0,
        counterfactual_probe_budget=2,
        counterfactual_flip_tolerance=0,
        counterfactual_tool_probe_budget=2,
        counterfactual_tool_flip_tolerance=0,
        rule_packages=(
            "CORE",
            "COUNTERFACTUAL-FINDING",
            "COUNTERFACTUAL-TOOL",
            "RULE-STABILITY",
        ),
    ),
    ScenarioProfile.FINANCE: _ScenarioRuleProfile(
        label="Finance",
        require_governance_metrics=True,
        min_tool_count=5,
        required_tool_names=(
            "image_quality",
            "duplicate_leakage",
            "annotation_integrity",
            "coverage_matrix",
            "governance_audit",
        ),
        max_governance_missing_cells=0,
        max_governance_unknown_cells=0,
        counterfactual_probe_budget=1,
        counterfactual_flip_tolerance=0,
        counterfactual_tool_probe_budget=1,
        counterfactual_tool_flip_tolerance=0,
        rule_packages=(
            "CORE",
            "COUNTERFACTUAL-FINDING",
            "COUNTERFACTUAL-TOOL",
            "RULE-STABILITY",
        ),
    ),
    ScenarioProfile.EDUCATION: _ScenarioRuleProfile(
        label="Education",
        require_governance_metrics=True,
        min_tool_count=5,
        required_tool_names=(
            "image_quality",
            "duplicate_leakage",
            "annotation_integrity",
            "coverage_matrix",
            "governance_audit",
        ),
        max_governance_missing_cells=2,
        max_governance_unknown_cells=1,
        counterfactual_probe_budget=3,
        counterfactual_flip_tolerance=1,
        counterfactual_tool_probe_budget=3,
        counterfactual_tool_flip_tolerance=1,
        rule_packages=(
            "CORE",
            "COUNTERFACTUAL-FINDING",
            "COUNTERFACTUAL-TOOL",
            "RULE-STABILITY",
        ),
    ),
    ScenarioProfile.WEARABLE: _ScenarioRuleProfile(
        label="Wearable",
        require_governance_metrics=True,
        min_tool_count=5,
        required_tool_names=(
            "image_quality",
            "duplicate_leakage",
            "annotation_integrity",
            "coverage_matrix",
            "governance_audit",
        ),
        max_governance_missing_cells=1,
        max_governance_unknown_cells=1,
        counterfactual_probe_budget=2,
        counterfactual_flip_tolerance=1,
        counterfactual_tool_probe_budget=2,
        counterfactual_tool_flip_tolerance=1,
        rule_packages=(
            "CORE",
            "COUNTERFACTUAL-FINDING",
            "COUNTERFACTUAL-TOOL",
            "RULE-STABILITY",
        ),
    ),
}


def _canonical_sha256(manifest: BatchManifest, contract: BatchContract) -> str:
    payload = {
        "contract": contract.model_dump(mode="json"),
        "manifest": manifest.model_dump(mode="json"),
    }
    encoded = json.dumps(
        payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _stable_work_order_id(payload: Mapping[str, Any]) -> str:
    encoded = json.dumps(
        payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    ).encode("utf-8")
    return f"wo-{hashlib.sha256(encoded).hexdigest()[:16]}"


def _finding_action(finding: Finding) -> WorkOrderAction:
    code = finding.code.upper()
    # A governance coverage gap is actionable when the tool supplies the
    # missing cells: the reserve-backed repair operator can add a compatible
    # sample without touching the original batch.  Unknown scope remains an
    # investigation and therefore keeps the fail-closed boundary.
    if (
        code == "GOVERNANCE_SCOPE_GAP"
        and isinstance(finding.evidence.get("missing_cells"), list)
        and finding.evidence.get("missing_cells")
    ):
        return "RECAPTURE"
    recommendation = finding.recommended_action.lower()
    if code in _FROZEN_CODE_ACTIONS:
        return _FROZEN_CODE_ACTIONS[code]
    if (
        any(keyword in code for keyword in _RECAPTURE_KEYWORDS)
        or "recapture" in recommendation
    ):
        return "RECAPTURE"
    if (
        any(keyword in code for keyword in _RELABEL_KEYWORDS)
        or "relabel" in recommendation
    ):
        return "RELABEL"
    if (
        any(keyword in code for keyword in _REPARTITION_KEYWORDS)
        or "repartition" in recommendation
        or "remove" in recommendation
    ):
        return "REMOVE_OR_REPARTITION"
    return "INVESTIGATE"


def _finding_work_order(
    finding: Finding, *, force_investigate: bool = False
) -> WorkOrder:
    action: WorkOrderAction = (
        "INVESTIGATE" if force_investigate else _finding_action(finding)
    )
    payload = {
        "action": action,
        "finding_id": finding.finding_id,
        "reason_codes": [finding.code],
        "sample_ids": sorted(finding.sample_ids),
    }
    replacement_requirements = dict(finding.evidence)
    replacement_requirements["source_finding_id"] = finding.finding_id
    return WorkOrder(
        work_order_id=_stable_work_order_id(payload),
        action=action,
        priority=finding.severity,
        reason_codes=[finding.code],
        sample_ids=sorted(finding.sample_ids),
        replacement_requirements=replacement_requirements,
    )


def _trace_work_order(trace: ToolTrace) -> WorkOrder:
    reason_code = "TOOL_ERROR" if trace.status == "error" else "TOOL_SKIPPED"
    payload = {
        "action": "INVESTIGATE",
        "reason_codes": [reason_code, trace.tool],
        "sequence": trace.sequence,
    }
    return WorkOrder(
        work_order_id=_stable_work_order_id(payload),
        action="INVESTIGATE",
        priority=Severity.CRITICAL,
        reason_codes=[reason_code, trace.tool],
        replacement_requirements={
            "tool": trace.tool,
            "trace_sequence": trace.sequence,
            "error": trace.error or trace.status,
        },
    )


def _missing_trace_work_order() -> WorkOrder:
    payload = {"action": "INVESTIGATE", "reason_codes": ["NO_TOOL_TRACE"]}
    return WorkOrder(
        work_order_id=_stable_work_order_id(payload),
        action="INVESTIGATE",
        priority=Severity.CRITICAL,
        reason_codes=["NO_TOOL_TRACE"],
        replacement_requirements={"required": "at least one completed tool trace"},
    )


def _normalized_metrics(
    metrics: Mapping[str, int | float | str | object],
) -> dict[str, int | float | str]:
    normalized: dict[str, int | float | str] = {}
    for key in sorted(metrics):
        value = metrics[key]
        if isinstance(value, bool):
            normalized[str(key)] = str(value).lower()
        elif isinstance(value, (int, float, str)):
            normalized[str(key)] = value
        else:
            normalized[str(key)] = json.dumps(
                value, ensure_ascii=False, sort_keys=True, default=str
            )
    return normalized


def _scenario_profile(profile: ScenarioProfile) -> _ScenarioRuleProfile:
    return _SCENARIO_RULEBOOK[profile]


def _decision_order(decision: GateDecision) -> int:
    return {
        GateDecision.DEFER: 0,
        GateDecision.QUARANTINE: 1,
        GateDecision.RECAPTURE: 2,
        GateDecision.PASS: 3,
    }[decision]


def _governance_metric(
    metrics: Mapping[str, int | float | str | object], key: str
) -> tuple[bool, int]:
    canonical_key = f"governance_{key}"
    raw_key = (
        canonical_key if canonical_key in metrics else key.removeprefix("governance_")
    )
    if raw_key not in metrics:
        return False, 0
    raw = metrics[raw_key]
    if isinstance(raw, bool):
        return True, int(raw)
    if isinstance(raw, int):
        if raw < 0:
            raise ValueError(f"governance metric {raw_key} must be non-negative")
        return True, raw
    if isinstance(raw, float):
        if not raw.is_integer():
            raise TypeError(f"governance metric {raw_key} must be an integer")
        if raw < 0:
            raise ValueError(f"governance metric {raw_key} must be non-negative")
        return True, int(raw)
    if isinstance(raw, str):
        stripped = raw.strip()
        if not stripped or not stripped.lstrip("-").isdigit():
            raise TypeError(f"governance metric {raw_key} must be an integer")
        value = int(stripped)
        if value < 0:
            raise ValueError(f"governance metric {raw_key} must be non-negative")
        return True, value
    raise TypeError(
        f"governance metric {raw_key} has unsupported type: {type(raw).__name__}"
    )


def _build_core_work_orders(
    finding_list: Sequence[Finding],
    trace_list: Sequence[ToolTrace],
) -> tuple[list[WorkOrder], list[ToolTrace], bool]:
    incomplete_traces = [trace for trace in trace_list if trace.status != "ok"]
    unsupported = [
        finding
        for finding in finding_list
        if finding.evidence_status is EvidenceStatus.UNSUPPORTED
        or (
            finding.evidence_status is EvidenceStatus.INFERRED
            and finding.severity in {Severity.CRITICAL, Severity.HIGH}
        )
    ]

    work_orders: list[WorkOrder] = []
    work_orders.extend(_trace_work_order(trace) for trace in incomplete_traces)
    if not trace_list:
        work_orders.append(_missing_trace_work_order())

    unsupported_ids = {finding.finding_id for finding in unsupported}
    work_orders.extend(
        _finding_work_order(
            finding, force_investigate=finding.finding_id in unsupported_ids
        )
        for finding in finding_list
    )

    block_release = bool(incomplete_traces or not trace_list or unsupported)
    return work_orders, incomplete_traces, block_release


def _derive_gate_decision(
    work_orders: Sequence[WorkOrder], block_release: bool
) -> tuple[GateDecision, str]:
    if block_release:
        decision = GateDecision.DEFER
        decision_reason = (
            "DEFER: required tool evidence is missing, failed, skipped, or unsupported; "
            "the batch is not released."
        )
    elif any(order.action == "RECAPTURE" for order in work_orders):
        decision = GateDecision.RECAPTURE
        decision_reason = (
            "RECAPTURE: verified capture-quality or coverage findings require reserve "
            "replacement before the batch can be reconsidered."
        )
    elif work_orders:
        decision = GateDecision.QUARANTINE
        decision_reason = (
            "QUARANTINE: verified findings require relabeling, removal, repartition, "
            "or investigation before release."
        )
    else:
        decision = GateDecision.PASS
        decision_reason = (
            "PASS only for the frozen sandbox experiment training pool contract; "
            "production release still requires human authority."
        )
    return decision, decision_reason


def _build_counterfactual_rule_checks(
    base_decision: GateDecision,
    finding_list: Sequence[Finding],
    trace_list: Sequence[ToolTrace],
    scenario_profile: ScenarioProfile,
) -> RuleCheck:
    profile = _scenario_profile(scenario_profile)
    if profile.counterfactual_probe_budget <= 0:
        return RuleCheck(
            check_id="RC-COUNTERFACTUAL-REMOVE-1",
            status=RuleCheckResult.PASS,
            detail="Counterfactual perturbation checks are not enabled for this package.",
            related_refs=["counterfactual:disabled"],
        )

    max_probes = min(len(finding_list), profile.counterfactual_probe_budget)
    if max_probes == 0:
        return RuleCheck(
            check_id="RC-COUNTERFACTUAL-REMOVE-1",
            status=RuleCheckResult.PASS,
            detail="Not enough findings to perform counterfactual perturbation checks.",
            related_refs=["counterfactual:no-findings"],
        )

    # Keep perturbation scope deterministic and bounded.
    ordered = sorted(finding_list, key=lambda item: (item.code, item.finding_id))
    candidates = ordered[:max_probes]
    flipped_ids: list[str] = []
    for finding in candidates:
        perturbed = [item for item in ordered if item.finding_id != finding.finding_id]
        candidate_work_orders, candidate_incomplete_traces, block_release = (
            _build_core_work_orders(perturbed, trace_list)
        )
        candidate_decision, _ = _derive_gate_decision(
            candidate_work_orders, block_release
        )
        if _decision_order(candidate_decision) > _decision_order(base_decision):
            flipped_ids.append(finding.finding_id)

    failed = len(flipped_ids) > profile.counterfactual_flip_tolerance
    return RuleCheck(
        check_id="RC-COUNTERFACTUAL-REMOVE-1",
        status=RuleCheckResult.FAIL if failed else RuleCheckResult.PASS,
        detail=(
            "Counterfactual single-finding deletions changed decision in a stricter-to-looser direction "
            f"for {len(flipped_ids)}/{len(candidates)} probes."
            if failed
            else (
                "Decision remained non-more-permissive under single-finding deletions."
                if flipped_ids
                else "Decision was robust for all sampled single-finding deletions."
            )
        ),
        related_refs=(
            [f"finding:{finding_id}" for finding_id in flipped_ids]
            if flipped_ids
            else ["findings:stable"]
        ),
    )


def _tool_trace_signature(trace: ToolTrace) -> str:
    payload = trace.model_dump(mode="json", exclude_none=False)
    return canonical_text(payload)


def _trace_sequence_signature(trace_list: Sequence[ToolTrace]) -> tuple[str, ...]:
    return tuple(_tool_trace_signature(trace) for trace in trace_list)


def canonical_text(value: object) -> str:
    return json.dumps(
        value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=str
    )


def _tool_perturbations_for_target(
    finding_id: str,
    tool_name: str,
    trace_list: Sequence[ToolTrace],
) -> list[tuple[str, list[ToolTrace]]]:
    removed = [
        trace
        for trace in trace_list
        if not (trace.tool == tool_name and finding_id in trace.finding_ids)
    ]
    candidates: list[tuple[str, list[ToolTrace]]] = []
    if removed != list(trace_list):
        candidates.append((f"remove:{finding_id}:{tool_name}", list(removed)))

    deduped: list[ToolTrace] = []
    seen_signatures: set[str] = set()
    for trace in trace_list:
        if trace.tool == tool_name and finding_id in trace.finding_ids:
            signature = _tool_trace_signature(trace)
            if signature in seen_signatures:
                continue
            seen_signatures.add(signature)
        deduped.append(trace)
    if deduped != list(trace_list):
        candidates.append((f"dedupe:{finding_id}:{tool_name}", deduped))

    reordered = [trace for trace in trace_list if trace.tool == tool_name]
    reordered.extend(trace for trace in trace_list if trace.tool != tool_name)
    if reordered != list(trace_list):
        candidates.append((f"reorder:{finding_id}:{tool_name}", reordered))
    return candidates


def _build_tool_perturbation_candidates(
    finding_list: Sequence[Finding],
    trace_list: Sequence[ToolTrace],
    budget: int,
) -> list[tuple[str, list[ToolTrace]]]:
    if budget <= 0 or not finding_list:
        return []

    ordered_findings = sorted(
        finding_list, key=lambda item: (item.code, item.finding_id)
    )
    variants: list[tuple[str, list[ToolTrace]]] = []
    seen_signatures: set[tuple[str, ...]] = set()
    base_signature = _trace_sequence_signature(trace_list)

    for finding in ordered_findings:
        if len(variants) >= budget:
            break
        touched_tools = sorted(
            {
                trace.tool
                for trace in trace_list
                if finding.finding_id in trace.finding_ids
            }
        )
        for tool_name in touched_tools:
            for label, candidate in _tool_perturbations_for_target(
                finding.finding_id, tool_name, trace_list
            ):
                if len(variants) >= budget:
                    break
                signature = _trace_sequence_signature(candidate)
                if signature in seen_signatures or signature == base_signature:
                    continue
                seen_signatures.add(signature)
                variants.append((label, candidate))
    return variants


def _build_counterfactual_tool_checks(
    base_decision: GateDecision,
    finding_list: Sequence[Finding],
    trace_list: Sequence[ToolTrace],
    scenario_profile: ScenarioProfile,
) -> RuleCheck:
    profile = _scenario_profile(scenario_profile)
    if profile.counterfactual_tool_probe_budget <= 0:
        return RuleCheck(
            check_id="RC-COUNTERFACTUAL-TOOL-REMOVE-1",
            status=RuleCheckResult.PASS,
            detail=(
                "Tool-level counterfactual checks are disabled for this scenario profile."
            ),
            related_refs=["counterfactual:tool-disabled"],
        )

    candidates = _build_tool_perturbation_candidates(
        finding_list, trace_list, profile.counterfactual_tool_probe_budget
    )
    if not candidates:
        return RuleCheck(
            check_id="RC-COUNTERFACTUAL-TOOL-REMOVE-1",
            status=RuleCheckResult.PASS,
            detail="No tool-level counterfactual perturbations were applicable.",
            related_refs=["counterfactual:tool-no-variants"],
        )

    flipped_spans: list[str] = []
    probes_executed = 0
    for probe_id, candidate_trace in candidates:
        candidate_work_orders, _, block_release = _build_core_work_orders(
            finding_list, candidate_trace
        )
        candidate_decision, _ = _derive_gate_decision(
            candidate_work_orders, block_release
        )
        probes_executed += 1
        if _decision_order(candidate_decision) > _decision_order(base_decision):
            flipped_spans.append(probe_id)

        if len(flipped_spans) > profile.counterfactual_tool_flip_tolerance:
            break

    failed = len(flipped_spans) > profile.counterfactual_tool_flip_tolerance
    return RuleCheck(
        check_id="RC-COUNTERFACTUAL-TOOL-REMOVE-1",
        status=RuleCheckResult.FAIL if failed else RuleCheckResult.PASS,
        detail=(
            "Counterfactual tool perturbations changed decision in a stricter-to-looser "
            f"direction for {len(flipped_spans)}/{max(1, probes_executed)} perturbations."
            if failed
            else (
                "Decision remained non-more-permissive under deterministic tool perturbations."
                if flipped_spans
                else "Decision was robust for sampled tool perturbations."
            )
        ),
        related_refs=(
            [f"tool:{span}" for span in flipped_spans]
            if flipped_spans
            else ["counterfactual-tool-stable"]
        ),
    )


def _build_counterfactual_rule_stability_check(
    base_core_checks: Sequence[RuleCheck],
    finding_list: Sequence[Finding],
    trace_list: Sequence[ToolTrace],
    metrics: Mapping[str, int | float | str | object],
    scenario_profile: ScenarioProfile,
) -> RuleCheck:
    profile = _scenario_profile(scenario_profile)
    if (
        profile.counterfactual_probe_budget <= 0
        and profile.counterfactual_tool_probe_budget <= 0
    ):
        return RuleCheck(
            check_id="RC-COUNTERFACTUAL-RULE-STABILITY-1",
            status=RuleCheckResult.PASS,
            detail="Rule-stability counterfactual checks are disabled for this package.",
            related_refs=["counterfactual-stability:disabled"],
        )

    base_map = {check.check_id: check.status for check in base_core_checks}
    stability_violations: list[str] = []
    finding_flips: list[str] = []
    tool_flips: list[str] = []

    ordered_findings = sorted(
        finding_list, key=lambda item: (item.code, item.finding_id)
    )
    finding_budget = min(
        len(ordered_findings), max(0, profile.counterfactual_probe_budget)
    )
    for finding in ordered_findings[:finding_budget]:
        candidate_findings = [
            item for item in finding_list if item.finding_id != finding.finding_id
        ]
        candidate_checks = _build_core_rule_checks(
            candidate_findings,
            trace_list,
            metrics,
            scenario_profile,
        )
        candidate_map = {check.check_id: check.status for check in candidate_checks}
        for check_id in sorted(base_map):
            base_status = base_map[check_id]
            candidate_status = candidate_map.get(check_id)
            # Removing a required finding/tool may make a rule stricter
            # (PASS -> FAIL).  That is fail-closed behaviour, not instability.
            # Only a more-permissive transition (FAIL -> PASS) is a safety
            # violation worth flagging in the stability package.
            more_permissive = (
                base_status is RuleCheckResult.FAIL
                and candidate_status in {RuleCheckResult.PASS, None}
            )
            if more_permissive:
                finding_flips.append(
                    f"finding:{finding.finding_id}|{check_id}|{base_status.value}->"
                    f"{candidate_status.value if candidate_status else 'none'}"
                )
                stability_violations.append(f"finding:{finding.finding_id}|{check_id}")

    if profile.counterfactual_tool_probe_budget > 0:
        tool_budget = min(
            len(ordered_findings),
            max(0, profile.counterfactual_tool_probe_budget),
        )
        tool_candidates = _build_tool_perturbation_candidates(
            ordered_findings[:tool_budget], trace_list, tool_budget
        )
        for probe_id, candidate_trace in tool_candidates:
            candidate_checks = _build_core_rule_checks(
                finding_list, candidate_trace, metrics, scenario_profile
            )
            candidate_map = {check.check_id: check.status for check in candidate_checks}
            for check_id in sorted(base_map):
                base_status = base_map[check_id]
                candidate_status = candidate_map.get(check_id)
                more_permissive = (
                    base_status is RuleCheckResult.FAIL
                    and candidate_status in {RuleCheckResult.PASS, None}
                )
                if more_permissive:
                    tool_flips.append(
                        f"{probe_id}:{check_id}|{base_status.value}->"
                        f"{candidate_status.value if candidate_status else 'none'}"
                    )
                    stability_violations.append(f"{probe_id}:{check_id}")

    finding_instability = len(finding_flips) > profile.counterfactual_flip_tolerance
    tool_instability = len(tool_flips) > profile.counterfactual_tool_flip_tolerance
    failed = finding_instability or tool_instability

    return RuleCheck(
        check_id="RC-COUNTERFACTUAL-RULE-STABILITY-1",
        status=RuleCheckResult.FAIL if failed else RuleCheckResult.PASS,
        detail=(
            "Rule decision stability checks failed: "
            f"{len(stability_violations)} unstable rule outputs under counterfactual perturbation."
            if failed
            else (
                "Rule stability checks passed under sampled counterfactual perturbations."
                if not stability_violations
                else "Rule outputs were stable within configured tolerances."
            )
        ),
        related_refs=(
            stability_violations[:24]
            if stability_violations
            else ["counterfactual-rule-stable"]
        ),
    )


def _build_rule_checks(
    findings: Sequence[Finding],
    traces: Sequence[ToolTrace],
    metrics: Mapping[str, int | float | str | object],
    base_decision: GateDecision,
    scenario_profile: ScenarioProfile,
) -> list[RuleCheck]:
    core_checks: list[RuleCheck] = _build_core_rule_checks(
        findings, traces, metrics, scenario_profile
    )
    profile = _scenario_profile(scenario_profile)
    enabled_packages = set(profile.rule_packages)
    checks: list[RuleCheck] = list(core_checks)
    if "COUNTERFACTUAL-FINDING" in enabled_packages:
        checks.append(
            _build_counterfactual_rule_checks(
                base_decision, findings, traces, scenario_profile
            )
        )
    if "COUNTERFACTUAL-TOOL" in enabled_packages:
        checks.append(
            _build_counterfactual_tool_checks(
                base_decision, findings, traces, scenario_profile
            )
        )
    if "RULE-STABILITY" in enabled_packages:
        checks.append(
            _build_counterfactual_rule_stability_check(
                core_checks,
                findings,
                traces,
                metrics,
                scenario_profile,
            )
        )
    return checks


def _build_core_rule_checks(
    findings: Sequence[Finding],
    traces: Sequence[ToolTrace],
    metrics: Mapping[str, int | float | str | object],
    scenario_profile: ScenarioProfile,
) -> list[RuleCheck]:
    failed_findings = {
        finding.finding_id
        for finding in findings
        if finding.evidence_status is not EvidenceStatus.VERIFIED
    }
    bad_trace_tools = {
        trace.tool
        for trace in traces
        if trace.status != "ok" or trace.error is not None
    }
    profile = _scenario_profile(scenario_profile)
    governance_scope_gap_missing = None
    governance_scope_gap_unknown = None
    governance_missing_cell_count_present = False
    governance_unknown_cell_count_present = False
    governance_scope_gap_missing_value = None
    governance_scope_gap_unknown_value = None
    metric_missing = False
    governance_metric_issues: list[str] = []
    if "governance_missing_cell_count" in metrics or "missing_cell_count" in metrics:
        try:
            (
                governance_missing_cell_count_present,
                governance_scope_gap_missing_value,
            ) = _governance_metric(metrics, "missing_cell_count")
        except (TypeError, ValueError) as error:
            metric_missing = True
            governance_metric_issues.append(
                f"governance_missing_cell_count parse failure: {error}"
            )
    if "governance_unknown_cell_count" in metrics or "unknown_cell_count" in metrics:
        try:
            (
                governance_unknown_cell_count_present,
                governance_scope_gap_unknown_value,
            ) = _governance_metric(metrics, "unknown_cell_count")
        except (TypeError, ValueError) as error:
            metric_missing = True
            governance_metric_issues.append(
                f"governance_unknown_cell_count parse failure: {error}"
            )
    governance_metric_present = (
        governance_missing_cell_count_present or governance_unknown_cell_count_present
    )
    if profile.require_governance_metrics and (
        not governance_missing_cell_count_present
        or not governance_unknown_cell_count_present
    ):
        # defensive branch; keep explicit for static linters
        metric_missing = True
        if not governance_missing_cell_count_present:
            governance_metric_issues.append("governance_missing_cell_count missing")
        if not governance_unknown_cell_count_present:
            governance_metric_issues.append("governance_unknown_cell_count missing")

    checks: list[RuleCheck] = []
    checks.append(
        RuleCheck(
            check_id="RC-TOOL-COUNT",
            status=RuleCheckResult.PASS
            if int(metrics.get("tool_count", 0)) >= profile.min_tool_count
            else RuleCheckResult.FAIL,
            detail=(
                "Core tool suite was fully invoked."
                if int(metrics.get("tool_count", 0)) >= profile.min_tool_count
                else (
                    f"Core tool suite invocation count is {int(metrics.get('tool_count', 0))}, "
                    f"require >= {profile.min_tool_count} for scenario {profile.label}."
                )
            ),
            related_refs=["tool_count", "tool_error_count"],
        )
    )
    required_tools = set(profile.required_tool_names)
    observed_tools = {trace.tool for trace in traces}
    checks.append(
        RuleCheck(
            check_id="RC-SCENARIO-TOOLS",
            status=RuleCheckResult.PASS
            if required_tools.issubset(observed_tools)
            else RuleCheckResult.FAIL,
            detail=(
                f"All required tools executed for scenario {profile.label}."
                if required_tools.issubset(observed_tools)
                else (
                    "Missing scenario-required tool trace(s): "
                    + ", ".join(sorted(required_tools - observed_tools))
                )
            ),
            related_refs=[
                f"tool:{tool_name}" for tool_name in sorted(profile.required_tool_names)
            ],
        )
    )
    checks.append(
        RuleCheck(
            check_id="RC-TRACE-OK",
            status=RuleCheckResult.PASS
            if not bad_trace_tools
            else RuleCheckResult.FAIL,
            detail=(
                "All tool traces are successful."
                if not bad_trace_tools
                else f"Non-OK traces: {', '.join(sorted(bad_trace_tools))}"
            ),
            related_refs=[f"trace:{tool}" for tool in sorted(bad_trace_tools)]
            if bad_trace_tools
            else ["trace:all-ok"],
        )
    )
    checks.append(
        RuleCheck(
            check_id="RC-EVIDENCE-QUALITY",
            status=RuleCheckResult.PASS
            if not failed_findings
            else RuleCheckResult.FAIL,
            detail=(
                "All findings are verified or source-backed."
                if not failed_findings
                else "Some findings require stronger evidence."
            ),
            related_refs=sorted(failed_findings)
            if failed_findings
            else ["findings:verified"],
        )
    )
    if governance_metric_present or profile.require_governance_metrics:
        governance_scope_gap_missing = governance_scope_gap_missing_value
        governance_scope_gap_unknown = governance_scope_gap_unknown_value
        governance_missing_limit = profile.max_governance_missing_cells
        governance_unknown_limit = profile.max_governance_unknown_cells
        governance_check_detail = ""
        if metric_missing:
            governance_check_detail = "governance metrics parsing/availability issue"
        elif governance_scope_gap_missing is None:
            governance_check_detail = "missing governance_missing_cell_count metric"
        elif governance_scope_gap_unknown is None:
            governance_check_detail = "missing governance_unknown_cell_count metric"
        elif (
            governance_scope_gap_missing <= governance_missing_limit
            and governance_scope_gap_unknown <= governance_unknown_limit
        ):
            governance_check_detail = "Governance scope aligns with contract."
        else:
            governance_check_detail = (
                f"Governance scope exceeds scenario limits: "
                f"missing={governance_scope_gap_missing}, unknown={governance_scope_gap_unknown}, "
                f"limits missing<={governance_missing_limit}, unknown<={governance_unknown_limit}"
            )
        checks.append(
            RuleCheck(
                check_id="RC-GOVERNANCE-SCOPE",
                status=RuleCheckResult.FAIL
                if (
                    metric_missing
                    or (
                        profile.require_governance_metrics
                        and not governance_metric_present
                    )
                    or (
                        governance_scope_gap_missing is not None
                        and governance_scope_gap_unknown is not None
                        and (
                            governance_scope_gap_missing > governance_missing_limit
                            or governance_scope_gap_unknown > governance_unknown_limit
                        )
                    )
                )
                else RuleCheckResult.PASS,
                detail=(
                    f"Scenario rulebook({profile.label}) requires governance metrics, but "
                    "governance tool output is missing."
                    if profile.require_governance_metrics
                    and not governance_metric_present
                    else f"Scenario rulebook({profile.label}) governance scope check: {governance_check_detail}"
                ),
                related_refs=(
                    (
                        ["governance:missing-metrics"]
                        if profile.require_governance_metrics
                        and not governance_metric_present
                        else [
                            "governance_missing_cell_count",
                            "governance_unknown_cell_count",
                        ]
                    )
                    if not metric_missing
                    else governance_metric_issues
                ),
            )
        )
    return checks


def build_scenario_rule_profile_snapshot(profile: ScenarioProfile) -> dict[str, Any]:
    """Return a stable snapshot of scenario-specific governance configuration.

    The payload is deterministic and meant for evidence traceability and UI display.
    """

    scenario = _scenario_profile(profile)
    enabled_checks: list[str] = [
        "RC-TOOL-COUNT",
        "RC-SCENARIO-TOOLS",
        "RC-TRACE-OK",
        "RC-EVIDENCE-QUALITY",
    ]
    if scenario.require_governance_metrics:
        enabled_checks.append("RC-GOVERNANCE-SCOPE")
    if "COUNTERFACTUAL-FINDING" in scenario.rule_packages:
        enabled_checks.append("RC-COUNTERFACTUAL-REMOVE-1")
    if "COUNTERFACTUAL-TOOL" in scenario.rule_packages:
        enabled_checks.append("RC-COUNTERFACTUAL-TOOL-REMOVE-1")
    if "RULE-STABILITY" in scenario.rule_packages:
        enabled_checks.append("RC-COUNTERFACTUAL-RULE-STABILITY-1")

    return {
        "scenario_profile": profile.value,
        "label": scenario.label,
        "require_governance_metrics": scenario.require_governance_metrics,
        "min_tool_count": scenario.min_tool_count,
        "required_tool_names": list(scenario.required_tool_names),
        "counters": {
            "max_governance_missing_cells": scenario.max_governance_missing_cells,
            "max_governance_unknown_cells": scenario.max_governance_unknown_cells,
            "counterfactual_probe_budget": scenario.counterfactual_probe_budget,
            "counterfactual_flip_tolerance": scenario.counterfactual_flip_tolerance,
            "counterfactual_tool_probe_budget": scenario.counterfactual_tool_probe_budget,
            "counterfactual_tool_flip_tolerance": scenario.counterfactual_tool_flip_tolerance,
        },
        "rule_packages": list(scenario.rule_packages),
        "enabled_checks": enabled_checks,
    }


def apply_policy(
    manifest: BatchManifest,
    contract: BatchContract,
    findings: Sequence[Finding],
    tool_trace: Sequence[ToolTrace],
    metrics: Mapping[str, int | float | str | object],
    council_trace: CouncilTrace | None = None,
    *,
    scenario_profile: ScenarioProfile = ScenarioProfile.GENERIC,
    input_sha256: str | None = None,
    run_id: str | None = None,
) -> GateResult:
    """Apply fail-closed policy and return a fully typed gate result."""

    finding_list = list(findings)
    trace_list = list(tool_trace)
    digest = input_sha256 or _canonical_sha256(manifest, contract)
    council = council_trace or build_council(finding_list, trace_list, metrics)

    work_orders, _, block_release = _build_core_work_orders(finding_list, trace_list)
    decision, decision_reason = _derive_gate_decision(work_orders, block_release)

    rule_checks = _build_rule_checks(
        finding_list, trace_list, metrics, decision, scenario_profile
    )
    failed_scenario_checks = [
        check
        for check in rule_checks
        if check.status is RuleCheckResult.FAIL
        and check.check_id
        in {
            "RC-GOVERNANCE-SCOPE",
            "RC-COUNTERFACTUAL-REMOVE-1",
            "RC-COUNTERFACTUAL-TOOL-REMOVE-1",
            "RC-COUNTERFACTUAL-RULE-STABILITY-1",
        }
    ]
    if decision is GateDecision.PASS and failed_scenario_checks:
        decision = GateDecision.DEFER
        decision_reason = (
            f"DEFER: scenario profile {scenario_profile.value} requires stricter "
            "guardrails than PASS-level release."
        )

    return GateResult(
        run_id=run_id or f"gate-{digest[:16]}",
        batch_id=manifest.batch_id,
        contract_id=contract.contract_id,
        input_sha256=digest,
        policy_version=contract.policy_version,
        decision=decision,
        decision_reason=decision_reason,
        metrics=_normalized_metrics(metrics),
        findings=finding_list,
        tool_trace=trace_list,
        council_trace=council,
        rule_checks=rule_checks,
        work_orders=work_orders,
    )


run_policy = apply_policy

__all__ = [
    "apply_policy",
    "build_scenario_rule_profile_snapshot",
    "run_policy",
]
