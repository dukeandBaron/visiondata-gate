"""Hidden-truth evaluation for VisionData Gate demo runs."""

from __future__ import annotations

from pathlib import Path

from .contracts import (
    CorruptionManifest,
    EvaluationResult,
    Finding,
    GateDecision,
    GateResult,
    Severity,
    TruthIssue,
    WorkOrder,
)


_SEVERITY_ORDER = {
    Severity.CRITICAL: 0,
    Severity.HIGH: 1,
    Severity.MEDIUM: 2,
    Severity.LOW: 3,
}


def _load_truth(truth: CorruptionManifest | Path) -> CorruptionManifest:
    if isinstance(truth, CorruptionManifest):
        return truth
    return CorruptionManifest.model_validate_json(
        Path(truth).read_text(encoding="utf-8")
    )


def _sample_ids_match(left: list[str], right: list[str]) -> bool:
    left_ids = set(left)
    right_ids = set(right)
    if not left_ids or not right_ids:
        return not left_ids and not right_ids
    return bool(left_ids & right_ids)


def _finding_matches(issue: TruthIssue, finding: Finding) -> bool:
    return issue.code.upper() == finding.code.upper() and _sample_ids_match(
        issue.sample_ids, finding.sample_ids
    )


def _candidate_rank(issue: TruthIssue, finding: Finding) -> tuple[int, int, str]:
    truth_ids = set(issue.sample_ids)
    finding_ids = set(finding.sample_ids)
    exact = truth_ids == finding_ids
    overlap = len(truth_ids & finding_ids)
    return (0 if exact else 1, -overlap, finding.finding_id)


def _one_to_one_matches(
    issues: list[TruthIssue], findings: list[Finding]
) -> tuple[set[int], set[int]]:
    candidates: dict[int, list[int]] = {}
    for truth_index, issue in enumerate(issues):
        compatible = [
            finding_index
            for finding_index, finding in enumerate(findings)
            if _finding_matches(issue, finding)
        ]
        candidates[truth_index] = sorted(
            compatible,
            key=lambda index: _candidate_rank(issue, findings[index]),
        )

    finding_to_truth: dict[int, int] = {}

    def assign(truth_index: int, visited_findings: set[int]) -> bool:
        for finding_index in candidates[truth_index]:
            if finding_index in visited_findings:
                continue
            visited_findings.add(finding_index)
            previous_truth = finding_to_truth.get(finding_index)
            if previous_truth is None or assign(previous_truth, visited_findings):
                finding_to_truth[finding_index] = truth_index
                return True
        return False

    truth_order = sorted(
        range(len(issues)),
        key=lambda index: (
            _SEVERITY_ORDER[issues[index].severity],
            issues[index].issue_id,
            index,
        ),
    )
    for truth_index in truth_order:
        assign(truth_index, set())

    return set(finding_to_truth.values()), set(finding_to_truth)


def _work_order_covers(issue: TruthIssue, order: WorkOrder) -> bool:
    reason_codes = {code.upper() for code in order.reason_codes}
    return issue.code.upper() in reason_codes and _sample_ids_match(
        issue.sample_ids, order.sample_ids
    )


def _safe_ratio(numerator: int, denominator: int, *, empty: float) -> float:
    return numerator / denominator if denominator else empty


def evaluate_gate(
    truth: CorruptionManifest | Path,
    gate_result: GateResult,
    post_repair_result: GateResult | None = None,
) -> EvaluationResult:
    """Evaluate detections, release safety, work orders, and repaired PASS.

    Finding-to-truth assignment is one-to-one and maximum-cardinality.  Exact
    sample-ID sets are preferred, followed by larger intersections.  Hidden
    truth is read only here; neither policy nor repair receives it.
    """

    truth_manifest = _load_truth(truth)
    if gate_result.batch_id != truth_manifest.batch_id:
        raise ValueError("gate result batch_id does not match the corruption manifest")
    if (
        post_repair_result is not None
        and post_repair_result.batch_id != truth_manifest.batch_id
    ):
        raise ValueError(
            "post-repair result batch_id does not match the corruption manifest"
        )

    issues = list(truth_manifest.issues)
    findings = list(gate_result.findings)
    matched_truth, matched_findings = _one_to_one_matches(issues, findings)

    true_positives = len(matched_truth)
    false_positives = len(findings) - len(matched_findings)
    false_negatives = len(issues) - len(matched_truth)
    precision = _safe_ratio(
        true_positives,
        true_positives + false_positives,
        empty=1.0 if not issues else 0.0,
    )
    recall = _safe_ratio(true_positives, len(issues), empty=1.0)
    f1 = 2.0 * precision * recall / (precision + recall) if precision + recall else 0.0

    critical_indices = {
        index
        for index, issue in enumerate(issues)
        if issue.severity is Severity.CRITICAL
    }
    missed_critical = len(critical_indices - matched_truth)
    critical_bad_release_rate = 0.0
    if gate_result.decision is GateDecision.PASS and critical_indices:
        critical_bad_release_rate = missed_critical / len(critical_indices)

    false_quarantine_rate = float(
        not issues
        and gate_result.decision in {GateDecision.QUARANTINE, GateDecision.RECAPTURE}
    )

    covered_truth = {
        index
        for index, issue in enumerate(issues)
        if any(_work_order_covers(issue, order) for order in gate_result.work_orders)
    }
    relevant_orders = {
        index
        for index, order in enumerate(gate_result.work_orders)
        if any(_work_order_covers(issue, order) for issue in issues)
    }
    work_order_recall = _safe_ratio(len(covered_truth), len(issues), empty=1.0)
    irrelevant_work_order_rate = _safe_ratio(
        len(gate_result.work_orders) - len(relevant_orders),
        len(gate_result.work_orders),
        empty=0.0,
    )

    post_trace_is_complete = bool(
        post_repair_result and post_repair_result.tool_trace
    ) and all(trace.status == "ok" for trace in post_repair_result.tool_trace)
    post_repair_correct_pass = bool(
        post_repair_result
        and post_repair_result.decision is GateDecision.PASS
        and post_trace_is_complete
        and len(covered_truth) == len(issues)
    )

    notes = [
        "Issue matching is one-to-one by exact code and exact/intersecting sample IDs.",
        "Council agreement is not used as detection evidence.",
        "A post-repair PASS is accepted only after successful tool traces and full work-order coverage.",
    ]
    if false_negatives:
        notes.append(f"{false_negatives} hidden truth issue(s) were not detected.")
    if false_positives:
        notes.append(f"{false_positives} finding(s) did not match hidden truth.")

    return EvaluationResult(
        batch_id=truth_manifest.batch_id,
        truth_issue_count=len(issues),
        predicted_issue_count=len(findings),
        true_positive_count=true_positives,
        false_positive_count=false_positives,
        false_negative_count=false_negatives,
        precision=precision,
        recall=recall,
        f1=f1,
        critical_bad_release_rate=critical_bad_release_rate,
        false_quarantine_rate=false_quarantine_rate,
        work_order_recall=work_order_recall,
        irrelevant_work_order_rate=irrelevant_work_order_rate,
        post_repair_correct_pass=post_repair_correct_pass,
        notes=notes,
    )


__all__ = ["evaluate_gate"]
