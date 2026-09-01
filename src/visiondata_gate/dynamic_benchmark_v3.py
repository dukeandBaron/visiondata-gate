"""DynamicBench-v3: deterministic dynamic-replanning comparison.

The benchmark compares a frozen rule pipeline with a dynamic replanning policy
under the same synthetic fixture inputs, tool-result mapping, tool budget, and
fail-closed terminal judge.  It exercises the public evidence-belief revision
contracts without changing production Agent behavior to fit the benchmark.

The report is local orchestration evidence only.  It is not industrial model
accuracy, a customer shadow-test result, or evidence of production deployment.
"""

from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass
import hashlib
import hmac
import json
from pathlib import Path
from typing import Any, Literal

import rfc8785

from .evidence_state_contracts import (
    EvidenceBeliefLedgerV2,
    build_case_evidence_belief_ledger_v2,
    verify_evidence_belief_ledger_v2,
)
from .incident_agent_kernel import (
    EvidenceBeliefRevisionReceiptV1,
    build_evidence_belief_revision_receipt_v1,
    verify_evidence_belief_revision_receipt_v1,
)


SCHEMA_VERSION = "visiondata-gate.dynamic-benchmark.v3"
BENCHMARK_ID = "DynamicBench-v3-dynamic-replanning"
STRATEGIES = ("fixed_rule_baseline", "dynamic_replanning_contract")
SCENARIO_CLASSES = (
    "conflicting_evidence",
    "tool_failure",
    "indeterminate",
    "evidence_changed_next_step",
)
FIXED_TOOL_PLAN = (
    "metadata_reconciliation",
    "annotation_integrity",
    "cross_tool_conflict_adjudication",
)
TOOL_BUDGET = 3
FIXTURE_COUNT = 8
FIXED_RECORD_COUNT = FIXTURE_COUNT * len(STRATEGIES)

_FRAME_MAGIC = b"VISIONDATA_GATE_FRAME_V1\x00"
_HASH_DOMAINS = {
    "protocol": "visiondata-gate.dynamicbench-v3.protocol.v1",
    "fixture_manifest": "visiondata-gate.dynamicbench-v3.fixture-manifest.v1",
    "records": "visiondata-gate.dynamicbench-v3.records.v1",
    "metrics": "visiondata-gate.dynamicbench-v3.metrics.v1",
    "comparisons": "visiondata-gate.dynamicbench-v3.comparisons.v1",
    "record": "visiondata-gate.dynamicbench-v3.record.v1",
    "tool_result": "visiondata-gate.dynamicbench-v3.tool-result.v1",
    "evidence_bundle": "visiondata-gate.dynamicbench-v3.evidence-bundle.v1",
    "synthetic_case": "visiondata-gate.dynamicbench-v3.synthetic-case.v1",
    "synthetic_authorization": (
        "visiondata-gate.dynamicbench-v3.synthetic-authorization.v1"
    ),
    "sealed_report": "visiondata-gate.dynamicbench-v3.sealed-report.v1",
}
_CLAIM_BOUNDARY = (
    "DynamicBench-v3 is a local deterministic orchestration benchmark over eight "
    "frozen synthetic fixtures. It does not establish industrial model accuracy, "
    "real-factory applicability, customer acceptance, a production SLO, or a "
    "comparison with unexecuted third-party systems."
)
_VALID_EVIDENCE_STATES = {"CLEAR", "BLOCKING", "CONFLICT", "INDETERMINATE"}


class DynamicBenchmarkV3ValidationError(ValueError):
    """Raised when a v3 protocol or sealed report fails deterministic replay."""


@dataclass(frozen=True)
class _BenchmarkHypothesis:
    hypothesis_id: str
    status: str
    unresolved_evidence_refs: list[str]

    def model_dump(self, *, mode: str) -> dict[str, object]:
        if mode != "json":
            raise ValueError("benchmark hypothesis supports JSON projection only")
        return {
            "hypothesis_id": self.hypothesis_id,
            "status": self.status,
            "unresolved_evidence_refs": self.unresolved_evidence_refs,
        }


def _canonical_jcs_bytes(value: object) -> bytes:
    try:
        return rfc8785.dumps(value)
    except (rfc8785.CanonicalizationError, TypeError, UnicodeError) as error:
        raise DynamicBenchmarkV3ValidationError(
            f"DynamicBench-v3 payload cannot be canonicalized: {error}"
        ) from error


def _frame_bytes(domain: str, payload: object) -> bytes:
    """Frame a JCS payload with explicit domain and length boundaries."""

    if not isinstance(domain, str) or not domain:
        raise DynamicBenchmarkV3ValidationError("hash domain must be non-empty")
    domain_bytes = domain.encode("utf-8")
    payload_bytes = _canonical_jcs_bytes(payload)
    if len(domain_bytes) > (2**32 - 1):
        raise DynamicBenchmarkV3ValidationError("hash domain is too large")
    if len(payload_bytes) > (2**64 - 1):
        raise DynamicBenchmarkV3ValidationError("hash payload is too large")
    return (
        _FRAME_MAGIC
        + len(domain_bytes).to_bytes(4, "big")
        + domain_bytes
        + len(payload_bytes).to_bytes(8, "big")
        + payload_bytes
    )


def _framed_sha256(domain: str, payload: object) -> str:
    return hashlib.sha256(_frame_bytes(domain, payload)).hexdigest()


def _tool_result(
    outcome_code: str,
    *,
    status: Literal["SUCCEEDED", "FAILED"] = "SUCCEEDED",
    evidence_updates: dict[str, str] | None = None,
    fallback_tools: tuple[str, ...] = (),
    next_required_tools: tuple[str, ...] = (),
    replan_reason: str | None = None,
) -> dict[str, Any]:
    updates = dict(sorted((evidence_updates or {}).items()))
    invalid_states = sorted(set(updates.values()) - _VALID_EVIDENCE_STATES)
    if invalid_states:
        raise AssertionError(f"invalid fixture evidence state(s): {invalid_states}")
    if status == "FAILED" and updates:
        raise AssertionError("failed fixture tools cannot publish evidence updates")
    return {
        "status": status,
        "outcome_code": outcome_code,
        "evidence_updates": updates,
        "fallback_tools": list(fallback_tools),
        "next_required_tools": list(next_required_tools),
        "replan_reason": replan_reason,
    }


def _fixture(
    fixture_id: str,
    *,
    scenario_class: str,
    summary: str,
    entry_tool: str,
    special_tool_results: dict[str, dict[str, Any]],
    necessary_tools: tuple[str, ...],
    necessary_evidence_refs: tuple[str, ...],
    expected_terminal_disposition: Literal["RELEASE", "BLOCK", "HOLD"],
    expected_dynamic_path: tuple[str, ...],
    failure_recovery_tool: str | None = None,
    evidence_changed_required_tool: str | None = None,
) -> dict[str, Any]:
    tool_results = {
        tool_id: _tool_result("NO_RELEVANT_CHANGE") for tool_id in FIXED_TOOL_PLAN
    }
    tool_results.update(deepcopy(special_tool_results))
    return {
        "fixture_id": fixture_id,
        "scenario_class": scenario_class,
        "summary": summary,
        "initial_input": {
            "batch_scope": f"synthetic_batch_{fixture_id.lower()}",
            "entry_tool": entry_tool,
            "initial_required_tools": [entry_tool],
        },
        "tool_result_mapping": dict(sorted(tool_results.items())),
        "necessary_tools": list(necessary_tools),
        "necessary_evidence_refs": list(necessary_evidence_refs),
        "expected_terminal_disposition": expected_terminal_disposition,
        "expected_dynamic_path": list(expected_dynamic_path),
        "failure_recovery_tool": failure_recovery_tool,
        "evidence_changed_required_tool": evidence_changed_required_tool,
    }


def build_dynamic_replanning_fixtures() -> list[dict[str, Any]]:
    """Return the frozen 8-fixture manifest, two fixtures per failure class."""

    fixtures = [
        _fixture(
            "C01",
            scenario_class="conflicting_evidence",
            summary="Metadata sources disagree; adjudication resolves the batch clean.",
            entry_tool="metadata_reconciliation",
            special_tool_results={
                "metadata_reconciliation": _tool_result(
                    "METADATA_CONFLICT",
                    evidence_updates={"metadata_alignment": "CONFLICT"},
                    next_required_tools=("cross_tool_conflict_adjudication",),
                    replan_reason="CONFLICTING_EVIDENCE",
                ),
                "cross_tool_conflict_adjudication": _tool_result(
                    "CONFLICT_RESOLVED_CLEAR",
                    evidence_updates={
                        "conflict_adjudication": "CLEAR",
                        "metadata_alignment": "CLEAR",
                    },
                ),
            },
            necessary_tools=(
                "metadata_reconciliation",
                "cross_tool_conflict_adjudication",
            ),
            necessary_evidence_refs=(
                "metadata_alignment",
                "conflict_adjudication",
            ),
            expected_terminal_disposition="RELEASE",
            expected_dynamic_path=(
                "metadata_reconciliation",
                "cross_tool_conflict_adjudication",
            ),
        ),
        _fixture(
            "C02",
            scenario_class="conflicting_evidence",
            summary="Annotation sources disagree; adjudication confirms a blocker.",
            entry_tool="annotation_integrity",
            special_tool_results={
                "annotation_integrity": _tool_result(
                    "ANNOTATION_CONFLICT",
                    evidence_updates={"annotation_geometry": "CONFLICT"},
                    next_required_tools=("cross_tool_conflict_adjudication",),
                    replan_reason="CONFLICTING_EVIDENCE",
                ),
                "cross_tool_conflict_adjudication": _tool_result(
                    "CONFLICT_RESOLVED_BLOCKING",
                    evidence_updates={
                        "annotation_geometry": "BLOCKING",
                        "conflict_adjudication": "CLEAR",
                    },
                ),
            },
            necessary_tools=(
                "annotation_integrity",
                "cross_tool_conflict_adjudication",
            ),
            necessary_evidence_refs=(
                "annotation_geometry",
                "conflict_adjudication",
            ),
            expected_terminal_disposition="BLOCK",
            expected_dynamic_path=(
                "annotation_integrity",
                "cross_tool_conflict_adjudication",
            ),
        ),
        _fixture(
            "F01",
            scenario_class="tool_failure",
            summary="Primary metadata tool fails; deterministic fallback recovers clear evidence.",
            entry_tool="metadata_reconciliation",
            special_tool_results={
                "metadata_reconciliation": _tool_result(
                    "METADATA_TOOL_UNAVAILABLE",
                    status="FAILED",
                    fallback_tools=("metadata_fallback_scan",),
                    replan_reason="TOOL_FAILURE",
                ),
                "metadata_fallback_scan": _tool_result(
                    "FALLBACK_RECOVERED_CLEAR",
                    evidence_updates={"metadata_integrity": "CLEAR"},
                ),
            },
            necessary_tools=("metadata_reconciliation", "metadata_fallback_scan"),
            necessary_evidence_refs=("metadata_integrity",),
            expected_terminal_disposition="RELEASE",
            expected_dynamic_path=(
                "metadata_reconciliation",
                "metadata_fallback_scan",
            ),
            failure_recovery_tool="metadata_fallback_scan",
        ),
        _fixture(
            "F02",
            scenario_class="tool_failure",
            summary="Primary annotation tool fails; fallback recovers a blocking defect.",
            entry_tool="annotation_integrity",
            special_tool_results={
                "annotation_integrity": _tool_result(
                    "ANNOTATION_TOOL_UNAVAILABLE",
                    status="FAILED",
                    fallback_tools=("annotation_fallback_scan",),
                    replan_reason="TOOL_FAILURE",
                ),
                "annotation_fallback_scan": _tool_result(
                    "FALLBACK_RECOVERED_BLOCKING",
                    evidence_updates={"annotation_integrity": "BLOCKING"},
                ),
            },
            necessary_tools=("annotation_integrity", "annotation_fallback_scan"),
            necessary_evidence_refs=("annotation_integrity",),
            expected_terminal_disposition="BLOCK",
            expected_dynamic_path=(
                "annotation_integrity",
                "annotation_fallback_scan",
            ),
            failure_recovery_tool="annotation_fallback_scan",
        ),
        _fixture(
            "I01",
            scenario_class="indeterminate",
            summary="Metadata evidence remains indeterminate and must fail closed.",
            entry_tool="metadata_reconciliation",
            special_tool_results={
                "metadata_reconciliation": _tool_result(
                    "METADATA_INDETERMINATE",
                    evidence_updates={"metadata_integrity": "INDETERMINATE"},
                )
            },
            necessary_tools=("metadata_reconciliation",),
            necessary_evidence_refs=("metadata_integrity",),
            expected_terminal_disposition="HOLD",
            expected_dynamic_path=("metadata_reconciliation",),
        ),
        _fixture(
            "I02",
            scenario_class="indeterminate",
            summary="Annotation evidence remains indeterminate and must fail closed.",
            entry_tool="annotation_integrity",
            special_tool_results={
                "annotation_integrity": _tool_result(
                    "ANNOTATION_INDETERMINATE",
                    evidence_updates={"annotation_integrity": "INDETERMINATE"},
                )
            },
            necessary_tools=("annotation_integrity",),
            necessary_evidence_refs=("annotation_integrity",),
            expected_terminal_disposition="HOLD",
            expected_dynamic_path=("annotation_integrity",),
        ),
        _fixture(
            "N01",
            scenario_class="evidence_changed_next_step",
            summary="Metadata is clear but newly reveals a native-resolution check.",
            entry_tool="metadata_reconciliation",
            special_tool_results={
                "metadata_reconciliation": _tool_result(
                    "NATIVE_RESOLUTION_CHECK_REQUIRED",
                    evidence_updates={"metadata_integrity": "CLEAR"},
                    next_required_tools=("native_resolution_reconciliation",),
                    replan_reason="NEW_EVIDENCE_CHANGED_NEXT_STEP",
                ),
                "native_resolution_reconciliation": _tool_result(
                    "NATIVE_RESOLUTION_CLEAR",
                    evidence_updates={"native_resolution_integrity": "CLEAR"},
                ),
            },
            necessary_tools=(
                "metadata_reconciliation",
                "native_resolution_reconciliation",
            ),
            necessary_evidence_refs=(
                "metadata_integrity",
                "native_resolution_integrity",
            ),
            expected_terminal_disposition="RELEASE",
            expected_dynamic_path=(
                "metadata_reconciliation",
                "native_resolution_reconciliation",
            ),
            evidence_changed_required_tool="native_resolution_reconciliation",
        ),
        _fixture(
            "N02",
            scenario_class="evidence_changed_next_step",
            summary="Annotation is clear but newly reveals a coverage-integrity check.",
            entry_tool="annotation_integrity",
            special_tool_results={
                "annotation_integrity": _tool_result(
                    "COVERAGE_CHECK_REQUIRED",
                    evidence_updates={"annotation_integrity": "CLEAR"},
                    next_required_tools=("coverage_integrity_scan",),
                    replan_reason="NEW_EVIDENCE_CHANGED_NEXT_STEP",
                ),
                "coverage_integrity_scan": _tool_result(
                    "COVERAGE_BLOCKING",
                    evidence_updates={"coverage_integrity": "BLOCKING"},
                ),
            },
            necessary_tools=("annotation_integrity", "coverage_integrity_scan"),
            necessary_evidence_refs=(
                "annotation_integrity",
                "coverage_integrity",
            ),
            expected_terminal_disposition="BLOCK",
            expected_dynamic_path=(
                "annotation_integrity",
                "coverage_integrity_scan",
            ),
            evidence_changed_required_tool="coverage_integrity_scan",
        ),
    ]
    if len(fixtures) != FIXTURE_COUNT:
        raise AssertionError(f"DynamicBench-v3 requires {FIXTURE_COUNT} fixtures")
    scenario_counts = {
        scenario: sum(item["scenario_class"] == scenario for item in fixtures)
        for scenario in SCENARIO_CLASSES
    }
    if scenario_counts != {scenario: 2 for scenario in SCENARIO_CLASSES}:
        raise AssertionError("DynamicBench-v3 requires two fixtures per scenario class")
    return fixtures


def _fixed_protocol() -> dict[str, Any]:
    return {
        "schema_version": "visiondata-gate.dynamic-bench-protocol.v3",
        "benchmark_id": BENCHMARK_ID,
        "strategies": list(STRATEGIES),
        "scenario_classes": list(SCENARIO_CLASSES),
        "fixture_count": FIXTURE_COUNT,
        "scenario_fixture_count": 2,
        "fixed_record_count": FIXED_RECORD_COUNT,
        "tool_budget_per_fixture": TOOL_BUDGET,
        "fixed_rule_plan": list(FIXED_TOOL_PLAN),
        "shared_initial_input": True,
        "shared_tool_result_mapping": True,
        "shared_fail_closed_terminal_judge": True,
        "external_model_calls_allowed": False,
        "terminal_judge": {
            "missing_required_evidence": "HOLD",
            "conflicting_required_evidence": "HOLD",
            "indeterminate_required_evidence": "HOLD",
            "blocking_required_evidence": "BLOCK",
            "otherwise": "RELEASE",
        },
        "hash_profile": {
            "algorithm": "SHA-256",
            "canonicalization": "RFC8785-JCS",
            "framing": (
                "magic || uint32_be(domain_utf8_length) || domain_utf8 || "
                "uint64_be(jcs_payload_length) || jcs_payload"
            ),
            "magic_hex": _FRAME_MAGIC.hex(),
            "domains": deepcopy(_HASH_DOMAINS),
            "security_boundary": (
                "Unkeyed tamper detection only; not a digital signature, trusted "
                "timestamp, identity proof, or authorization grant."
            ),
        },
        "claim_boundary": _CLAIM_BOUNDARY,
    }


def _terminal_disposition(
    evidence_state: dict[str, str], necessary_refs: list[str]
) -> str:
    observed = [evidence_state.get(ref) for ref in necessary_refs]
    if any(item is None for item in observed):
        return "HOLD"
    if any(item in {"CONFLICT", "INDETERMINATE"} for item in observed):
        return "HOLD"
    if any(item == "BLOCKING" for item in observed):
        return "BLOCK"
    if all(item == "CLEAR" for item in observed):
        return "RELEASE"
    raise DynamicBenchmarkV3ValidationError("terminal judge saw an invalid state")


def _build_replan_event(
    *,
    fixture: dict[str, Any],
    after_tool: str,
    next_tool: str,
    result: dict[str, Any],
    evidence_before: dict[str, str],
    evidence_after: dict[str, str],
    sequence: int,
) -> dict[str, Any]:
    case_seed = _framed_sha256(
        _HASH_DOMAINS["synthetic_case"],
        {"fixture_id": fixture["fixture_id"], "sequence": sequence},
    )
    case_id = f"incident_{case_seed[:20]}"
    source_bundle = _framed_sha256(
        _HASH_DOMAINS["evidence_bundle"],
        {
            "fixture_id": fixture["fixture_id"],
            "sequence": sequence,
            "phase": "before_replan",
            "evidence_state": dict(sorted(evidence_before.items())),
        },
    )
    observed_bundle = _framed_sha256(
        _HASH_DOMAINS["evidence_bundle"],
        {
            "fixture_id": fixture["fixture_id"],
            "sequence": sequence,
            "phase": "after_observation",
            "after_tool": after_tool,
            "tool_result": result,
            "evidence_state": dict(sorted(evidence_after.items())),
        },
    )
    unresolved = sorted(
        ref
        for ref in fixture["necessary_evidence_refs"]
        if evidence_after.get(ref) not in {"CLEAR", "BLOCKING"}
    )
    hypothesis = _BenchmarkHypothesis(
        hypothesis_id=f"H-{fixture['fixture_id']}-replan-{sequence}",
        status="UNRESOLVED",
        unresolved_evidence_refs=unresolved,
    )
    authorization_sha = _framed_sha256(
        _HASH_DOMAINS["synthetic_authorization"],
        {"fixture_id": fixture["fixture_id"], "status": "ACTIVE"},
    )
    ledger = build_case_evidence_belief_ledger_v2(
        case_id=case_id,
        evidence_bundle_sha256=source_bundle,
        hypotheses=[hypothesis],
        evidence_edges=[],
        source_authorization_event_sha256=authorization_sha,
        source_authorization_status="ACTIVE",
    )
    verify_evidence_belief_ledger_v2(ledger)
    revision = build_evidence_belief_revision_receipt_v1(
        parent_case_id=case_id,
        parent_case_sha256=_framed_sha256(
            _HASH_DOMAINS["synthetic_case"],
            {"fixture_id": fixture["fixture_id"], "kind": "parent_case"},
        ),
        source_ledger=ledger,
        observed_authorization_event_sha256=authorization_sha,
        observed_authorization_status="ACTIVE",
        observed_evidence_bundle_sha256=observed_bundle,
    )
    verify_evidence_belief_revision_receipt_v1(revision)
    if not revision.fresh_replan_required:
        raise DynamicBenchmarkV3ValidationError(
            "production belief-revision contract did not require a fresh replan"
        )
    return {
        "sequence": sequence,
        "after_tool": after_tool,
        "selected_next_tool": next_tool,
        "trigger_reason": result["replan_reason"],
        "source_ledger": ledger.model_dump(mode="json"),
        "revision_receipt": revision.model_dump(mode="json"),
    }


def _next_dynamic_tools(result: dict[str, Any]) -> list[str]:
    if result["status"] == "FAILED":
        return list(result["fallback_tools"])
    if "INDETERMINATE" in result["evidence_updates"].values():
        return []
    return list(result["next_required_tools"])


def _execute_strategy(
    fixture: dict[str, Any], strategy: str, *, tool_budget: int
) -> dict[str, Any]:
    if strategy not in STRATEGIES:
        raise DynamicBenchmarkV3ValidationError(f"unknown strategy: {strategy}")
    if (
        not isinstance(tool_budget, int)
        or isinstance(tool_budget, bool)
        or tool_budget != TOOL_BUDGET
    ):
        raise DynamicBenchmarkV3ValidationError(
            f"DynamicBench-v3 requires the frozen tool budget {TOOL_BUDGET}"
        )

    result_mapping = fixture["tool_result_mapping"]
    evidence_state: dict[str, str] = {}
    events: list[dict[str, Any]] = []
    replan_events: list[dict[str, Any]] = []
    pending = (
        list(FIXED_TOOL_PLAN)
        if strategy == "fixed_rule_baseline"
        else list(fixture["initial_input"]["initial_required_tools"])
    )
    while pending and len(events) < tool_budget:
        tool_id = pending.pop(0)
        if tool_id not in result_mapping:
            raise DynamicBenchmarkV3ValidationError(
                f"fixture {fixture['fixture_id']} has no result for {tool_id}"
            )
        result = deepcopy(result_mapping[tool_id])
        before = dict(evidence_state)
        if result["status"] == "SUCCEEDED":
            evidence_state.update(result["evidence_updates"])
        after = dict(evidence_state)
        events.append(
            {
                "sequence": len(events) + 1,
                "tool_id": tool_id,
                "is_necessary_tool": tool_id in fixture["necessary_tools"],
                "result": result,
                "tool_result_sha256": _framed_sha256(
                    _HASH_DOMAINS["tool_result"],
                    {
                        "fixture_id": fixture["fixture_id"],
                        "sequence": len(events) + 1,
                        "tool_id": tool_id,
                        "result": result,
                    },
                ),
            }
        )
        if strategy == "fixed_rule_baseline":
            continue
        next_tools = [
            item
            for item in _next_dynamic_tools(result)
            if item not in {event["tool_id"] for event in events}
        ]
        if next_tools:
            if len(next_tools) != 1 or result["replan_reason"] is None:
                raise DynamicBenchmarkV3ValidationError(
                    "dynamic fixture must identify one reasoned next tool"
                )
            next_tool = next_tools[0]
            replan_events.append(
                _build_replan_event(
                    fixture=fixture,
                    after_tool=tool_id,
                    next_tool=next_tool,
                    result=result,
                    evidence_before=before,
                    evidence_after=after,
                    sequence=len(replan_events) + 1,
                )
            )
            pending.extend(next_tools)

    executed_tools = [item["tool_id"] for item in events]
    resolved_refs = sorted(
        ref
        for ref in fixture["necessary_evidence_refs"]
        if evidence_state.get(ref) in {"CLEAR", "BLOCKING"}
    )
    terminal = _terminal_disposition(evidence_state, fixture["necessary_evidence_refs"])
    expected = fixture["expected_terminal_disposition"]
    correct = terminal == expected
    tool_failure_eligible = fixture["scenario_class"] == "tool_failure"
    failure_recovery_tool = fixture["failure_recovery_tool"]
    failure_recovery_success = bool(
        tool_failure_eligible
        and failure_recovery_tool in executed_tools
        and correct
        and len(resolved_refs) == len(fixture["necessary_evidence_refs"])
    )
    replan_eligible = fixture["scenario_class"] in {
        "conflicting_evidence",
        "tool_failure",
        "evidence_changed_next_step",
    }
    evidence_changed_eligible = (
        fixture["scenario_class"] == "evidence_changed_next_step"
    )
    changed_required_tool = fixture["evidence_changed_required_tool"]
    record = {
        "strategy": strategy,
        "fixture_id": fixture["fixture_id"],
        "scenario_class": fixture["scenario_class"],
        "shared_initial_input_sha256": _framed_sha256(
            _HASH_DOMAINS["fixture_manifest"], fixture["initial_input"]
        ),
        "shared_tool_result_mapping_sha256": _framed_sha256(
            _HASH_DOMAINS["fixture_manifest"], result_mapping
        ),
        "tool_budget": tool_budget,
        "executed_tools": executed_tools,
        "tool_events": events,
        "tool_call_count": len(events),
        "tool_budget_violation": len(events) > tool_budget,
        "necessary_tools": fixture["necessary_tools"],
        "necessary_evidence_refs": fixture["necessary_evidence_refs"],
        "resolved_necessary_evidence_refs": resolved_refs,
        "necessary_evidence_covered_count": len(resolved_refs),
        "necessary_evidence_denominator": len(fixture["necessary_evidence_refs"]),
        "unnecessary_tool_call_count": sum(
            tool_id not in fixture["necessary_tools"] for tool_id in executed_tools
        ),
        "tool_failure_recovery_eligible": tool_failure_eligible,
        "tool_failure_recovery_success": failure_recovery_success,
        "replanning_recovery_eligible": replan_eligible,
        "replanning_recovery_success": bool(
            replan_eligible and replan_events and correct
        ),
        "evidence_changed_next_step_eligible": evidence_changed_eligible,
        "evidence_changed_next_step_adapted": bool(
            evidence_changed_eligible
            and changed_required_tool in executed_tools
            and correct
        ),
        "indeterminate_fixture": fixture["scenario_class"] == "indeterminate",
        "indeterminate_correct": bool(
            fixture["scenario_class"] == "indeterminate" and terminal == "HOLD"
        ),
        "replan_events": replan_events,
        "replan_receipt_count": len(replan_events),
        "terminal_disposition": terminal,
        "expected_terminal_disposition": expected,
        "correct_terminal_disposition": correct,
        "unsafe_release": terminal == "RELEASE" and expected != "RELEASE",
        "actual_model_call_count": 0,
        "actual_model_token_count": 0,
        "provider_billed_api_cost_cny": 0.0,
    }
    return {
        **record,
        "record_sha256": _framed_sha256(_HASH_DOMAINS["record"], record),
    }


def _rate(numerator: int, denominator: int) -> float | None:
    return numerator / denominator if denominator else None


def _summarize_strategy(
    strategy: str, records: list[dict[str, Any]], fixtures: list[dict[str, Any]]
) -> dict[str, Any]:
    selected = [item for item in records if item["strategy"] == strategy]
    fixture_count = len(fixtures)
    evidence_denominator = sum(
        len(item["necessary_evidence_refs"]) for item in fixtures
    )
    correct_count = sum(item["correct_terminal_disposition"] for item in selected)
    unsafe_count = sum(item["unsafe_release"] for item in selected)
    evidence_covered = sum(
        item["necessary_evidence_covered_count"] for item in selected
    )
    failure_eligible = sum(item["tool_failure_recovery_eligible"] for item in selected)
    failure_success = sum(item["tool_failure_recovery_success"] for item in selected)
    replan_eligible = sum(item["replanning_recovery_eligible"] for item in selected)
    replan_success = sum(item["replanning_recovery_success"] for item in selected)
    changed_eligible = sum(
        item["evidence_changed_next_step_eligible"] for item in selected
    )
    changed_adapted = sum(
        item["evidence_changed_next_step_adapted"] for item in selected
    )
    indeterminate_count = sum(item["indeterminate_fixture"] for item in selected)
    indeterminate_correct = sum(item["indeterminate_correct"] for item in selected)
    return {
        "strategy": strategy,
        "fixed_fixture_denominator": fixture_count,
        "correct_terminal_disposition_count": correct_count,
        "correct_terminal_disposition_rate": _rate(correct_count, fixture_count),
        "unsafe_release_count": unsafe_count,
        "unsafe_release_rate": _rate(unsafe_count, fixture_count),
        "necessary_evidence_covered_count": evidence_covered,
        "necessary_evidence_fixed_denominator": evidence_denominator,
        "necessary_evidence_coverage_rate": _rate(
            evidence_covered, evidence_denominator
        ),
        "unnecessary_tool_call_count": sum(
            item["unnecessary_tool_call_count"] for item in selected
        ),
        "total_tool_call_count": sum(item["tool_call_count"] for item in selected),
        "tool_budget_violation_count": sum(
            item["tool_budget_violation"] for item in selected
        ),
        "tool_failure_recovery_eligible_count": failure_eligible,
        "tool_failure_recovery_success_count": failure_success,
        "tool_failure_recovery_rate": _rate(failure_success, failure_eligible),
        "replanning_recovery_eligible_count": replan_eligible,
        "replanning_recovery_success_count": replan_success,
        "replanning_recovery_rate": _rate(replan_success, replan_eligible),
        "evidence_changed_next_step_eligible_count": changed_eligible,
        "evidence_changed_next_step_adapted_count": changed_adapted,
        "evidence_changed_next_step_adaptation_rate": _rate(
            changed_adapted, changed_eligible
        ),
        "indeterminate_fixture_count": indeterminate_count,
        "indeterminate_correct_count": indeterminate_correct,
        "indeterminate_correct_rate": _rate(indeterminate_correct, indeterminate_count),
        "replan_receipt_count": sum(item["replan_receipt_count"] for item in selected),
        "actual_model_call_count": sum(
            item["actual_model_call_count"] for item in selected
        ),
        "actual_model_token_count": sum(
            item["actual_model_token_count"] for item in selected
        ),
        "provider_billed_api_cost_cny": sum(
            item["provider_billed_api_cost_cny"] for item in selected
        ),
    }


def _build_metrics(
    records: list[dict[str, Any]], fixtures: list[dict[str, Any]]
) -> dict[str, Any]:
    return {
        strategy: _summarize_strategy(strategy, records, fixtures)
        for strategy in STRATEGIES
    }


def _build_comparisons(metrics: dict[str, Any]) -> dict[str, Any]:
    fixed = metrics["fixed_rule_baseline"]
    dynamic = metrics["dynamic_replanning_contract"]
    return {
        "correct_terminal_gain_count": (
            dynamic["correct_terminal_disposition_count"]
            - fixed["correct_terminal_disposition_count"]
        ),
        "necessary_evidence_coverage_gain_count": (
            dynamic["necessary_evidence_covered_count"]
            - fixed["necessary_evidence_covered_count"]
        ),
        "unnecessary_tool_call_reduction_count": (
            fixed["unnecessary_tool_call_count"]
            - dynamic["unnecessary_tool_call_count"]
        ),
        "tool_failure_recovery_gain_count": (
            dynamic["tool_failure_recovery_success_count"]
            - fixed["tool_failure_recovery_success_count"]
        ),
        "evidence_changed_adaptation_gain_count": (
            dynamic["evidence_changed_next_step_adapted_count"]
            - fixed["evidence_changed_next_step_adapted_count"]
        ),
        "both_strategies_fail_closed_without_unsafe_release": (
            fixed["unsafe_release_count"] == 0 and dynamic["unsafe_release_count"] == 0
        ),
        "dynamic_contract_correct_on_all_frozen_fixtures": (
            dynamic["correct_terminal_disposition_count"] == FIXTURE_COUNT
        ),
        "dynamic_contract_observed_advantage_is_local_fixture_only": True,
    }


def _expected_status(metrics: dict[str, Any], comparisons: dict[str, Any]) -> str:
    fixed = metrics["fixed_rule_baseline"]
    dynamic = metrics["dynamic_replanning_contract"]
    passed = bool(
        comparisons["both_strategies_fail_closed_without_unsafe_release"]
        and comparisons["dynamic_contract_correct_on_all_frozen_fixtures"]
        and dynamic["tool_budget_violation_count"] == 0
        and fixed["tool_budget_violation_count"] == 0
        and dynamic["actual_model_call_count"] == 0
        and fixed["actual_model_call_count"] == 0
    )
    return "PASS" if passed else "FAIL"


def _seal_report(report_without_seal: dict[str, Any]) -> dict[str, Any]:
    return {
        **report_without_seal,
        "sealed_report_sha256": _framed_sha256(
            _HASH_DOMAINS["sealed_report"], report_without_seal
        ),
    }


def build_dynamic_replanning_benchmark_report(
    *, tool_budget: int = TOOL_BUDGET
) -> dict[str, Any]:
    """Execute, seal, and internally validate the frozen v3 comparison."""

    if (
        not isinstance(tool_budget, int)
        or isinstance(tool_budget, bool)
        or tool_budget != TOOL_BUDGET
    ):
        raise DynamicBenchmarkV3ValidationError(
            f"DynamicBench-v3 requires the frozen tool budget {TOOL_BUDGET}"
        )
    protocol = _fixed_protocol()
    fixtures = build_dynamic_replanning_fixtures()
    records = [
        _execute_strategy(fixture, strategy, tool_budget=tool_budget)
        for strategy in STRATEGIES
        for fixture in fixtures
    ]
    metrics = _build_metrics(records, fixtures)
    comparisons = _build_comparisons(metrics)
    report = _seal_report(
        {
            "schema_version": SCHEMA_VERSION,
            "benchmark_id": BENCHMARK_ID,
            "status": _expected_status(metrics, comparisons),
            "verdict": (
                "DYNAMIC_REPLANNING_ADVANTAGE_OBSERVED_IN_FROZEN_LOCAL_FIXTURES"
            ),
            "protocol": protocol,
            "protocol_sha256": _framed_sha256(_HASH_DOMAINS["protocol"], protocol),
            "fixture_manifest": fixtures,
            "fixture_manifest_sha256": _framed_sha256(
                _HASH_DOMAINS["fixture_manifest"], fixtures
            ),
            "records": records,
            "records_sha256": _framed_sha256(_HASH_DOMAINS["records"], records),
            "metrics": metrics,
            "metrics_sha256": _framed_sha256(_HASH_DOMAINS["metrics"], metrics),
            "comparisons": comparisons,
            "comparisons_sha256": _framed_sha256(
                _HASH_DOMAINS["comparisons"], comparisons
            ),
            "actual_model_call_count": 0,
            "actual_model_token_count": 0,
            "provider_billed_api_cost_cny": 0.0,
            "model_execution_status": "NOT_CONNECTED",
            "data_source_status": "FROZEN_SYNTHETIC_FIXTURES",
            "industrial_effectiveness_status": "NOT_EVALUATED",
            "claim_boundary": _CLAIM_BOUNDARY,
        }
    )
    validate_dynamic_replanning_benchmark_report(report)
    return report


def _verify_digest(payload: object, digest: object, domain_key: str) -> None:
    expected = _framed_sha256(_HASH_DOMAINS[domain_key], payload)
    if not isinstance(digest, str) or not hmac.compare_digest(expected, digest):
        raise DynamicBenchmarkV3ValidationError(
            f"DynamicBench-v3 {domain_key} hash mismatch"
        )


def _validate_replan_event(event: dict[str, Any]) -> None:
    try:
        ledger = EvidenceBeliefLedgerV2.model_validate(event["source_ledger"])
        revision = EvidenceBeliefRevisionReceiptV1.model_validate(
            event["revision_receipt"]
        )
        verify_evidence_belief_ledger_v2(ledger)
        verify_evidence_belief_revision_receipt_v1(revision)
    except (KeyError, TypeError, ValueError) as error:
        raise DynamicBenchmarkV3ValidationError(
            "DynamicBench-v3 replan receipt is invalid"
        ) from error
    if (
        revision.source_ledger_sha256 != ledger.ledger_sha256
        or revision.fresh_replan_required is not True
        or revision.disposition != "STALE_REPLAN_REQUIRED"
    ):
        raise DynamicBenchmarkV3ValidationError(
            "DynamicBench-v3 replan receipt does not bind a fresh replan"
        )


def validate_dynamic_replanning_benchmark_report(report: dict[str, Any]) -> None:
    """Recheck all hashes, frozen inputs, records, metrics, and strategy replay."""

    if not isinstance(report, dict):
        raise DynamicBenchmarkV3ValidationError(
            "DynamicBench-v3 report must be an object"
        )
    if report.get("schema_version") != SCHEMA_VERSION:
        raise DynamicBenchmarkV3ValidationError("DynamicBench-v3 schema is invalid")
    if report.get("benchmark_id") != BENCHMARK_ID:
        raise DynamicBenchmarkV3ValidationError(
            "DynamicBench-v3 benchmark identity drifted"
        )
    sealed_payload = {
        key: value for key, value in report.items() if key != "sealed_report_sha256"
    }
    _verify_digest(sealed_payload, report.get("sealed_report_sha256"), "sealed_report")
    for payload_key, digest_key, domain_key in (
        ("protocol", "protocol_sha256", "protocol"),
        ("fixture_manifest", "fixture_manifest_sha256", "fixture_manifest"),
        ("records", "records_sha256", "records"),
        ("metrics", "metrics_sha256", "metrics"),
        ("comparisons", "comparisons_sha256", "comparisons"),
    ):
        _verify_digest(report.get(payload_key), report.get(digest_key), domain_key)

    protocol = report.get("protocol")
    fixtures = report.get("fixture_manifest")
    records = report.get("records")
    metrics = report.get("metrics")
    comparisons = report.get("comparisons")
    if protocol != _fixed_protocol():
        raise DynamicBenchmarkV3ValidationError(
            "DynamicBench-v3 fixed protocol drifted"
        )
    expected_fixtures = build_dynamic_replanning_fixtures()
    if fixtures != expected_fixtures:
        raise DynamicBenchmarkV3ValidationError(
            "DynamicBench-v3 fixture manifest drifted"
        )
    if not isinstance(records, list) or len(records) != FIXED_RECORD_COUNT:
        raise DynamicBenchmarkV3ValidationError(
            "DynamicBench-v3 fixed record denominator mismatch"
        )
    fixture_by_id = {item["fixture_id"]: item for item in expected_fixtures}
    expected_grid = {
        (strategy, fixture_id)
        for strategy in STRATEGIES
        for fixture_id in fixture_by_id
    }
    observed_grid: set[tuple[str, str]] = set()
    for record in records:
        if not isinstance(record, dict):
            raise DynamicBenchmarkV3ValidationError("DynamicBench-v3 record is invalid")
        key = (str(record.get("strategy")), str(record.get("fixture_id")))
        if key in observed_grid or key not in expected_grid:
            raise DynamicBenchmarkV3ValidationError(
                "DynamicBench-v3 record grid has a duplicate or unknown cell"
            )
        observed_grid.add(key)
        record_payload = {
            item_key: item_value
            for item_key, item_value in record.items()
            if item_key != "record_sha256"
        }
        _verify_digest(record_payload, record.get("record_sha256"), "record")
        fixture = fixture_by_id[key[1]]
        _verify_digest(
            fixture["initial_input"],
            record.get("shared_initial_input_sha256"),
            "fixture_manifest",
        )
        _verify_digest(
            fixture["tool_result_mapping"],
            record.get("shared_tool_result_mapping_sha256"),
            "fixture_manifest",
        )
        tool_events = record.get("tool_events")
        if not isinstance(tool_events, list):
            raise DynamicBenchmarkV3ValidationError(
                "DynamicBench-v3 tool event list is invalid"
            )
        for expected_sequence, tool_event in enumerate(tool_events, start=1):
            if not isinstance(tool_event, dict):
                raise DynamicBenchmarkV3ValidationError(
                    "DynamicBench-v3 tool event is invalid"
                )
            _verify_digest(
                {
                    "fixture_id": key[1],
                    "sequence": expected_sequence,
                    "tool_id": tool_event.get("tool_id"),
                    "result": tool_event.get("result"),
                },
                tool_event.get("tool_result_sha256"),
                "tool_result",
            )
        for event in record.get("replan_events", []):
            if not isinstance(event, dict):
                raise DynamicBenchmarkV3ValidationError(
                    "DynamicBench-v3 replan event is invalid"
                )
            _validate_replan_event(event)
        replayed = _execute_strategy(fixture, key[0], tool_budget=TOOL_BUDGET)
        if _canonical_jcs_bytes(record) != _canonical_jcs_bytes(replayed):
            raise DynamicBenchmarkV3ValidationError(
                "DynamicBench-v3 record failed deterministic replay"
            )
    if observed_grid != expected_grid:
        raise DynamicBenchmarkV3ValidationError(
            "DynamicBench-v3 record grid is incomplete"
        )
    expected_metrics = _build_metrics(records, expected_fixtures)
    if metrics != expected_metrics:
        raise DynamicBenchmarkV3ValidationError(
            "DynamicBench-v3 metrics do not match replayed records"
        )
    expected_comparisons = _build_comparisons(expected_metrics)
    if comparisons != expected_comparisons:
        raise DynamicBenchmarkV3ValidationError(
            "DynamicBench-v3 comparisons do not match replayed metrics"
        )
    if report.get("status") != _expected_status(expected_metrics, comparisons):
        raise DynamicBenchmarkV3ValidationError(
            "DynamicBench-v3 status does not match replayed evidence"
        )
    if report.get("verdict") != (
        "DYNAMIC_REPLANNING_ADVANTAGE_OBSERVED_IN_FROZEN_LOCAL_FIXTURES"
    ):
        raise DynamicBenchmarkV3ValidationError(
            "DynamicBench-v3 verdict boundary drifted"
        )
    if not (
        report.get("actual_model_call_count") == 0
        and report.get("actual_model_token_count") == 0
        and report.get("provider_billed_api_cost_cny") == 0.0
        and report.get("model_execution_status") == "NOT_CONNECTED"
        and report.get("data_source_status") == "FROZEN_SYNTHETIC_FIXTURES"
        and report.get("industrial_effectiveness_status") == "NOT_EVALUATED"
        and report.get("claim_boundary") == _CLAIM_BOUNDARY
    ):
        raise DynamicBenchmarkV3ValidationError(
            "DynamicBench-v3 claim or model-execution boundary is inconsistent"
        )


def write_dynamic_replanning_benchmark_report(output_path: str | Path) -> Path:
    """Write one canonical report only after complete deterministic replay."""

    report = build_dynamic_replanning_benchmark_report()
    path = Path(output_path).expanduser().resolve()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(_canonical_jcs_bytes(report) + b"\n")
    return path


def load_dynamic_replanning_benchmark_report(path: str | Path) -> dict[str, Any]:
    """Load and fully replay-validate one stored v3 report."""

    report_path = Path(path).expanduser().resolve(strict=True)
    try:
        report = json.loads(report_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise DynamicBenchmarkV3ValidationError(
            "DynamicBench-v3 report is unreadable"
        ) from error
    if not isinstance(report, dict):
        raise DynamicBenchmarkV3ValidationError(
            "DynamicBench-v3 report must be an object"
        )
    validate_dynamic_replanning_benchmark_report(report)
    return report


__all__ = [
    "DynamicBenchmarkV3ValidationError",
    "build_dynamic_replanning_benchmark_report",
    "build_dynamic_replanning_fixtures",
    "load_dynamic_replanning_benchmark_report",
    "validate_dynamic_replanning_benchmark_report",
    "write_dynamic_replanning_benchmark_report",
]
