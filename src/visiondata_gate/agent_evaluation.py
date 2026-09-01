"""Deterministic sensitivity evaluation for the local agent-runtime auditor.

The runtime contract audit can report whether one trace is internally coherent.
This module tests the evaluator itself: it copies a clean trace, applies one
known fault at a time, and verifies that the intended audit check changes from
passing to failing.  The original evidence objects are never mutated.

This is deliberately not an Agent capability benchmark.  It uses no LLM judge,
does not require one reference trajectory, and grants no release authority.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from .contracts import GateResult
from .evidence import canonical_json_bytes, sha256_bytes
from .reviewer_audit import build_runtime_contract_audit
from .runtime_models import RuntimeStage, RuntimeStatus, RuntimeTrace


@dataclass(frozen=True)
class _Fixture:
    trace: RuntimeTrace
    initial: GateResult
    repaired: GateResult


@dataclass(frozen=True)
class _Intervention:
    case_id: str
    fault_family: str
    mutation: str
    expected_failed_check: str
    apply: Callable[[_Fixture], dict[str, Any]]


def _copy_fixture(
    trace: RuntimeTrace,
    initial: GateResult,
    repaired: GateResult,
) -> _Fixture:
    return _Fixture(
        trace=trace.model_copy(deep=True),
        initial=initial.model_copy(deep=True),
        repaired=repaired.model_copy(deep=True),
    )


def _fixture_sha256(fixture: _Fixture) -> str:
    return sha256_bytes(
        canonical_json_bytes(
            {
                "trace": fixture.trace,
                "initial": fixture.initial,
                "repaired": fixture.repaired,
            }
        )
    )


def _audit_sha256(audit: dict[str, Any]) -> str:
    return sha256_bytes(canonical_json_bytes(audit))


def _failed_checks(audit: dict[str, Any]) -> list[str]:
    return sorted(key for key, passed in audit["checks"].items() if not passed)


def _alternate_digest(value: str | None) -> str:
    replacement = "0" * 64
    return "f" * 64 if value == replacement else replacement


def _duplicate_policy_judge(fixture: _Fixture) -> dict[str, Any]:
    source = next(
        (
            event
            for event in fixture.trace.events
            if event.actor == "Policy Judge"
            and event.action == "apply_fail_closed_policy"
        ),
        None,
    )
    if source is None:
        raise ValueError("intervention requires one Policy Judge event")
    injected_sequence = max(event.sequence for event in fixture.trace.events) + 1
    fixture.trace.events.append(
        source.model_copy(update={"sequence": injected_sequence}, deep=True)
    )
    return {
        "source_event_sequence": source.sequence,
        "injected_event_sequence": injected_sequence,
    }


def _append_undeclared_task_event(fixture: _Fixture) -> dict[str, Any]:
    source = next(
        (
            event
            for event in fixture.trace.events
            if event.actor != "Policy Judge"
            and bool(event.collaboration.get("team_id"))
        ),
        None,
    )
    if source is None:
        raise ValueError(
            "intervention requires one collaboration-bound non-Judge event"
        )
    injected_sequence = max(event.sequence for event in fixture.trace.events) + 1
    fixture.trace.events.append(
        source.model_copy(
            update={
                "sequence": injected_sequence,
                "task_id": "evaluation.undeclared-task",
                "summary": "Evaluator sensitivity probe with an undeclared task binding.",
            },
            deep=True,
        )
    )
    return {
        "source_event_sequence": source.sequence,
        "injected_event_sequence": injected_sequence,
        "injected_task_id": "evaluation.undeclared-task",
    }


def _tamper_context_transfer_hash(fixture: _Fixture) -> dict[str, Any]:
    if not fixture.trace.context_transfers:
        raise ValueError("intervention requires at least one context transfer")
    target = fixture.trace.context_transfers[0]
    original = target.payload_sha256
    target.payload_sha256 = _alternate_digest(original)
    return {
        "transfer_sequence": target.sequence,
        "original_payload_sha256": original,
        "mutated_payload_sha256": target.payload_sha256,
    }


def _delete_context_transfer_edge(fixture: _Fixture) -> dict[str, Any]:
    if not fixture.trace.context_transfers:
        raise ValueError("intervention requires at least one context transfer")
    removed = fixture.trace.context_transfers.pop(0)
    return {
        "removed_edge": [removed.source_task_id, removed.task_id],
        "removed_transfer_sequence": removed.sequence,
    }


def _tamper_tool_contract_digest(fixture: _Fixture) -> dict[str, Any]:
    candidates = fixture.initial.tool_trace + fixture.repaired.tool_trace
    if not candidates:
        raise ValueError("intervention requires at least one tool trace")
    target = candidates[0]
    original = target.contract_digest
    target.contract_digest = _alternate_digest(original)
    return {
        "tool": target.tool,
        "tool_trace_sequence": target.sequence,
        "original_contract_digest": original,
        "mutated_contract_digest": target.contract_digest,
    }


def _unlink_finding_from_tool_trace(fixture: _Fixture) -> dict[str, Any]:
    selected_phase: str | None = None
    selected_finding_id: str | None = None
    for phase, result in (
        ("initial", fixture.initial),
        ("verification", fixture.repaired),
    ):
        traced_ids = {
            finding_id for item in result.tool_trace for finding_id in item.finding_ids
        }
        selected_finding_id = next(
            (
                finding.finding_id
                for finding in result.findings
                if finding.finding_id in traced_ids
            ),
            None,
        )
        if selected_finding_id is not None:
            selected_phase = phase
            for item in result.tool_trace:
                item.finding_ids = [
                    finding_id
                    for finding_id in item.finding_ids
                    if finding_id != selected_finding_id
                ]
            break
    if selected_phase is None or selected_finding_id is None:
        raise ValueError("intervention requires one finding bound to a tool trace")
    return {
        "phase": selected_phase,
        "unlinked_finding_id": selected_finding_id,
    }


def _clear_work_order_reason_codes(fixture: _Fixture) -> dict[str, Any]:
    candidates = fixture.initial.work_orders + fixture.repaired.work_orders
    if not candidates:
        raise ValueError("intervention requires at least one work order")
    target = candidates[0]
    original = list(target.reason_codes)
    target.reason_codes = []
    return {
        "work_order_id": target.work_order_id,
        "removed_reason_codes": original,
    }


def _unbind_run_id_from_execution_config(fixture: _Fixture) -> dict[str, Any]:
    original = fixture.trace.run_id
    candidate = "evaluation-unbound-run-id"
    if fixture.trace.execution_config_sha256[:10] in candidate:
        candidate = "evaluation-unbound-alternate"
    fixture.trace.run_id = candidate
    return {
        "original_run_id": original,
        "mutated_run_id": fixture.trace.run_id,
        "required_config_prefix": fixture.trace.execution_config_sha256[:10],
    }


def _delete_skill_execution(fixture: _Fixture) -> dict[str, Any]:
    if not fixture.trace.skill_executions:
        raise ValueError("intervention requires at least one Skill execution")
    removed = fixture.trace.skill_executions.pop(0)
    return {
        "removed_task_id": removed.task_id,
        "removed_skill_id": removed.skill_id,
        "removed_execution_sequence": removed.sequence,
    }


def _break_same_contract_recheck(fixture: _Fixture) -> dict[str, Any]:
    original = fixture.repaired.contract_id
    fixture.repaired.contract_id = f"{original}-evaluation-mismatch"
    return {
        "original_contract_id": original,
        "mutated_repaired_contract_id": fixture.repaired.contract_id,
    }


def _delete_decision_chain_entry(fixture: _Fixture) -> dict[str, Any]:
    if not fixture.trace.judge_decisions:
        raise ValueError("intervention requires at least one Judge decision")
    removed = fixture.trace.judge_decisions.pop()
    return {
        "removed_decision": removed,
        "remaining_decision_count": len(fixture.trace.judge_decisions),
    }


_INTERVENTIONS = (
    _Intervention(
        case_id="AEI-001",
        fault_family="authority_duplication",
        mutation="duplicate one Policy Judge authority event",
        expected_failed_check="one_policy_authority_per_pass",
        apply=_duplicate_policy_judge,
    ),
    _Intervention(
        case_id="AEI-002",
        fault_family="task_binding",
        mutation="append an event bound to an undeclared task",
        expected_failed_check="event_tasks_declared",
        apply=_append_undeclared_task_event,
    ),
    _Intervention(
        case_id="AEI-003",
        fault_family="context_integrity",
        mutation="tamper one context-transfer payload digest",
        expected_failed_check="context_transfer_hashes_valid",
        apply=_tamper_context_transfer_hash,
    ),
    _Intervention(
        case_id="AEI-004",
        fault_family="context_coverage",
        mutation="delete one declared context-transfer edge receipt",
        expected_failed_check="context_transfer_edges_complete",
        apply=_delete_context_transfer_edge,
    ),
    _Intervention(
        case_id="AEI-005",
        fault_family="tool_contract",
        mutation="tamper one observed tool-contract digest",
        expected_failed_check="typed_tool_contracts_bound",
        apply=_tamper_tool_contract_digest,
    ),
    _Intervention(
        case_id="AEI-006",
        fault_family="evidence_linkage",
        mutation="unlink one finding from every tool trace",
        expected_failed_check="finding_tool_refs_closed",
        apply=_unlink_finding_from_tool_trace,
    ),
    _Intervention(
        case_id="AEI-007",
        fault_family="work_order_grounding",
        mutation="clear one work order's reason-code references",
        expected_failed_check="work_order_reason_refs_present",
        apply=_clear_work_order_reason_codes,
    ),
    _Intervention(
        case_id="AEI-008",
        fault_family="run_configuration_binding",
        mutation="replace the run ID without its execution-config digest prefix",
        expected_failed_check="execution_config_bound_to_run_id",
        apply=_unbind_run_id_from_execution_config,
    ),
    _Intervention(
        case_id="AEI-009",
        fault_family="skill_execution_coverage",
        mutation="delete one run-bound Skill execution receipt",
        expected_failed_check="skill_execution_coverage_complete",
        apply=_delete_skill_execution,
    ),
    _Intervention(
        case_id="AEI-010",
        fault_family="recheck_contract",
        mutation="change the repaired pass to a different contract ID",
        expected_failed_check="same_contract_recheck",
        apply=_break_same_contract_recheck,
    ),
    _Intervention(
        case_id="AEI-011",
        fault_family="decision_chain",
        mutation="delete one recorded Judge decision",
        expected_failed_check="decision_chain_present",
        apply=_delete_decision_chain_entry,
    ),
)


def _reschedule_independent_worker_events(fixture: _Fixture) -> dict[str, Any]:
    """Swap two independent terminal Worker events and keep references coherent."""

    tasks = {task.task_id: task for task in fixture.trace.tasks}
    candidates = [
        event
        for event in fixture.trace.events
        if event.task_id in tasks
        and event.stage is RuntimeStage.TOOL
        and event.status not in {RuntimeStatus.QUEUED, RuntimeStatus.RUNNING}
        and event.status is tasks[event.task_id].status
    ]
    selected: tuple[Any, Any] | None = None
    for index, left in enumerate(candidates):
        left_task = tasks[left.task_id]
        for right in candidates[index + 1 :]:
            right_task = tasks[right.task_id]
            if (
                left.phase == right.phase
                and left_task.dependencies == right_task.dependencies
                and left.task_id != right.task_id
            ):
                selected = (left, right)
                break
        if selected is not None:
            break
    if selected is None:
        raise ValueError(
            "valid-path control requires two independent terminal Worker events"
        )

    left, right = selected
    left_original = left.sequence
    right_original = right.sequence
    left.sequence, right.sequence = right_original, left_original
    fixture.trace.events.sort(key=lambda event: event.sequence)
    terminal_sequence = {left.task_id: left.sequence, right.task_id: right.sequence}
    for transfer in fixture.trace.context_transfers:
        if transfer.task_id in terminal_sequence:
            transfer.recorded_event_sequence = terminal_sequence[transfer.task_id]
    for execution in fixture.trace.skill_executions:
        if execution.task_id in terminal_sequence:
            execution.recorded_event_sequence = terminal_sequence[execution.task_id]

    return {
        "control_id": "AEC-001",
        "variant": "independent_worker_completion_order",
        "swapped_tasks": [left.task_id, right.task_id],
        "original_event_sequences": [left_original, right_original],
        "variant_event_sequences": [left.sequence, right.sequence],
        "preserved_invariants": [
            "task_dependencies",
            "tool_outputs",
            "gate_decisions",
            "context_transfer_payloads",
            "skill_contracts",
        ],
    }


def build_agent_evaluation_receipt(
    trace: RuntimeTrace,
    initial: GateResult,
    repaired: GateResult,
) -> dict[str, Any]:
    """Measure whether known trace faults are detected without mutating inputs.

    The denominator is the frozen intervention catalog above.  A case is
    detected only when its named check is newly failing relative to the clean
    baseline; failure of an unrelated check does not earn credit.
    """

    clean = _Fixture(trace=trace, initial=initial, repaired=repaired)
    clean_input_sha256 = _fixture_sha256(clean)
    baseline_audit = build_runtime_contract_audit(trace, initial, repaired)
    baseline_failed = _failed_checks(baseline_audit)

    cases: list[dict[str, Any]] = []
    for spec in _INTERVENTIONS:
        mutated = _copy_fixture(trace, initial, repaired)
        mutation_details = spec.apply(mutated)
        mutated_audit = build_runtime_contract_audit(
            mutated.trace,
            mutated.initial,
            mutated.repaired,
        )
        observed_failed = _failed_checks(mutated_audit)
        newly_failed = sorted(set(observed_failed) - set(baseline_failed))
        detected = spec.expected_failed_check in newly_failed
        cases.append(
            {
                "case_id": spec.case_id,
                "fault_family": spec.fault_family,
                "mutation": spec.mutation,
                "mutation_details": mutation_details,
                "expected_failed_check": spec.expected_failed_check,
                "observed_failed_checks": observed_failed,
                "newly_failed_checks": newly_failed,
                "unexpected_newly_failed_checks": sorted(
                    set(newly_failed) - {spec.expected_failed_check}
                ),
                "detected": detected,
                "status": "DETECTED" if detected else "MISSED",
                "clean_input_sha256": clean_input_sha256,
                "mutated_input_sha256": _fixture_sha256(mutated),
                "audit_output_sha256": _audit_sha256(mutated_audit),
            }
        )

    variant = _copy_fixture(trace, initial, repaired)
    variant_details = _reschedule_independent_worker_events(variant)
    variant_audit = build_runtime_contract_audit(
        variant.trace,
        variant.initial,
        variant.repaired,
    )
    variant_failed = _failed_checks(variant_audit)
    variant_new_failed = sorted(set(variant_failed) - set(baseline_failed))
    variant_false_positive = bool(variant_new_failed)

    detected_count = sum(case["detected"] for case in cases)
    intervention_count = len(cases)
    missed_count = intervention_count - detected_count
    baseline_false_positive = bool(baseline_failed)
    status = (
        "PASS_LOCAL"
        if not baseline_false_positive
        and missed_count == 0
        and not variant_false_positive
        else "FAIL"
    )

    return {
        "schema_version": "visiondata-gate.agent-evaluator-sensitivity.v1",
        "evaluation_type": "local_evaluator_sensitivity",
        "run_id": trace.run_id,
        "status": status,
        "baseline": {
            "input_sha256": clean_input_sha256,
            "audit_output_sha256": _audit_sha256(baseline_audit),
            "audit_status": baseline_audit["status"],
            "failed_checks": baseline_failed,
            "false_positive": baseline_false_positive,
        },
        "method": {
            "strategy": "reproduce_intervene_rescore",
            "fixed_denominator": intervention_count,
            "scoring": "unweighted_exact_expected_check_detection",
            "reference_trajectory_required": False,
            "llm_judge_used": False,
            "source_evidence_mutated": False,
        },
        "summary": {
            "intervention_count": intervention_count,
            "detected_count": detected_count,
            "missed_count": missed_count,
            "detection_rate": round(detected_count / intervention_count, 6),
            "baseline_false_positive_count": int(baseline_false_positive),
            "valid_variant_control_count": 1,
            "valid_variant_false_positive_count": int(variant_false_positive),
        },
        "interventions": cases,
        "valid_trajectory_controls": [
            {
                **variant_details,
                "status": "PASS" if not variant_false_positive else "FALSE_POSITIVE",
                "observed_failed_checks": variant_failed,
                "newly_failed_checks": variant_new_failed,
                "clean_input_sha256": clean_input_sha256,
                "variant_input_sha256": _fixture_sha256(variant),
                "audit_output_sha256": _audit_sha256(variant_audit),
            }
        ],
        "claims": {
            "evaluator_sensitivity_measured": True,
            "agent_capability_measured": False,
            "production_quality_measured": False,
            "hosted_agent_platform_tested": False,
        },
        "boundary": (
            "PASS_LOCAL means this local rule-based auditor detected every frozen fault "
            "intervention and accepted the coherent alternate schedule for this fixture. "
            "It is not an Agent capability score, an LLM-judge result, a production-quality "
            "claim, hosted-platform validation, or official competition evidence."
        ),
    }


__all__ = ["build_agent_evaluation_receipt"]
