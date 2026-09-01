"""Fixed-denominator orchestration benchmark for evidence-triggered replanning.

The benchmark compares four execution policies under the same labelled fixture
manifest, rule contract, follow-up budget, deadline, and perturbation set.  It
measures orchestration semantics only: no external model or competitor system is
called, and the synthetic fixtures are not presented as industrial accuracy.
"""

from __future__ import annotations

import hashlib
import json
import math
import statistics
import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from typing import Any, Iterable

from .evidence import canonical_json_bytes, sha256_file, write_canonical_json


TRIGGER_BRANCHES = (
    "metadata_reconciliation",
    "native_resolution_reconciliation",
    "cross_tool_conflict_adjudication",
)

_FROZEN_TRIGGER_RULES = {
    "metadata_reconciliation": "metadata_count_delta != 0",
    "native_resolution_reconciliation": "native_resolution_group_count > 1",
    "cross_tool_conflict_adjudication": "conflicting_action_sample_count > 0",
}

_DYNAMIC_BENCH_CLAIM_BOUNDARY = (
    "DynamicBench-v1 is a deterministic labelled orchestration benchmark. "
    "It measures trigger and scheduling behavior under synthetic evidence "
    "perturbations; it is not industrial model accuracy, customer ROI, a "
    "production SLO, or a numeric comparison against unexecuted competitors."
)

_DYNAMIC_RECORD_KEYS = {
    "actual_model_call_count",
    "actual_model_token_count",
    "architecture",
    "covered_required_branches",
    "dispatch_mode",
    "dispatched_branches",
    "expected_terminal_outcome",
    "expected_trigger_branches",
    "extra_branches",
    "fixture_id",
    "fixture_label",
    "latency_ms",
    "missing_required_branches",
    "output_digests",
    "perturbations",
    "provider_billed_api_cost_cny",
    "redundant_or_duplicate_tool_call_count",
    "rejected_branches",
    "repeat",
    "semantic_sha256",
    "task_success",
    "terminal_outcome",
    "timed_out",
    "timeout_ms",
    "tool_budget",
    "tool_call_count",
}


class DynamicArchitecture(str, Enum):
    TRADITIONAL_PIPELINE = "traditional_pipeline"
    SINGLE_AGENT = "single_agent"
    FIXED_MULTI_AGENT = "fixed_multi_agent"
    DYNAMIC_LEADER = "dynamic_leader"


@dataclass(frozen=True)
class DynamicBenchRun:
    report_path: Path
    report_sha256: str
    report: dict[str, Any]


class DynamicBenchmarkValidationError(ValueError):
    """Raised when a stored DynamicBench report cannot be independently verified."""


def load_dynamic_benchmark_report(path: str | Path) -> dict[str, Any]:
    """Load a report and recheck its hashes, fixed denominators, and record grid."""

    report_path = Path(path).expanduser().resolve(strict=True)
    try:
        report = json.loads(report_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise DynamicBenchmarkValidationError(
            "DynamicBench report is unreadable"
        ) from error
    if not isinstance(report, dict):
        raise DynamicBenchmarkValidationError("DynamicBench report must be an object")
    if report.get("schema_version") != "visiondata-gate.dynamic-benchmark.v1":
        raise DynamicBenchmarkValidationError("DynamicBench schema version is invalid")

    hash_bindings = (
        ("protocol", "protocol_sha256"),
        ("fixture_manifest", "fixture_manifest_sha256"),
        ("records", "records_sha256"),
    )
    for payload_key, digest_key in hash_bindings:
        observed = hashlib.sha256(
            canonical_json_bytes(report.get(payload_key))
        ).hexdigest()
        if observed != report.get(digest_key):
            raise DynamicBenchmarkValidationError(
                f"DynamicBench {payload_key} hash mismatch"
            )

    protocol = report.get("protocol")
    fixtures = report.get("fixture_manifest")
    records = report.get("records")
    summaries = report.get("summaries")
    denominators = report.get("fixed_denominators")
    if not all(
        isinstance(value, expected)
        for value, expected in (
            (protocol, dict),
            (fixtures, list),
            (records, list),
            (summaries, dict),
            (denominators, dict),
        )
    ):
        raise DynamicBenchmarkValidationError(
            "DynamicBench structural sections are invalid"
        )

    architectures = protocol.get("architectures")
    branches = protocol.get("trigger_branches")
    repeats = protocol.get("repeats_for_latency")
    if (
        not isinstance(architectures, list)
        or architectures != [item.value for item in DynamicArchitecture]
        or not isinstance(branches, list)
        or branches != list(TRIGGER_BRANCHES)
        or not isinstance(repeats, int)
        or repeats < 1
        or repeats > 20
    ):
        raise DynamicBenchmarkValidationError("DynamicBench protocol grid is invalid")
    tool_budget = protocol.get("tool_budget_per_fixture")
    timeout_ms = protocol.get("timeout_ms_per_fixture")
    if (
        protocol.get("schema_version") != "visiondata-gate.dynamic-bench-protocol.v1"
        or protocol.get("frozen_rules") != _FROZEN_TRIGGER_RULES
        or protocol.get("shared_input_and_perturbations") is not True
        or protocol.get("external_model_calls_allowed") is not False
        or not isinstance(tool_budget, int)
        or isinstance(tool_budget, bool)
        or tool_budget < 0
        or tool_budget > len(TRIGGER_BRANCHES)
        or not isinstance(timeout_ms, (int, float))
        or isinstance(timeout_ms, bool)
        or not math.isfinite(float(timeout_ms))
        or float(timeout_ms) <= 0.0
    ):
        raise DynamicBenchmarkValidationError(
            "DynamicBench frozen protocol contract is invalid"
        )
    frozen_fixtures = build_dynamic_bench_fixtures()
    if canonical_json_bytes(fixtures) != canonical_json_bytes(frozen_fixtures):
        raise DynamicBenchmarkValidationError(
            "DynamicBench fixture manifest drifted from the frozen labels"
        )
    fixture_ids = [
        item.get("fixture_id") for item in fixtures if isinstance(item, dict)
    ]
    if len(fixture_ids) != len(fixtures) or len(set(fixture_ids)) != len(fixtures):
        raise DynamicBenchmarkValidationError("DynamicBench fixture IDs are invalid")
    positive_count = sum(
        isinstance(item, dict) and item.get("label") == "positive" for item in fixtures
    )
    negative_count = sum(
        isinstance(item, dict) and item.get("label") == "negative" for item in fixtures
    )
    if not (len(fixtures) == 24 and positive_count == 12 and negative_count == 12):
        raise DynamicBenchmarkValidationError(
            "DynamicBench v1 requires exactly 12 positive and 12 negative fixtures"
        )
    expected_denominators = {
        "fixture_count": len(fixtures),
        "positive_fixture_count": positive_count,
        "negative_fixture_count": negative_count,
        "architecture_count": len(architectures),
        "branch_label_count_per_architecture": len(fixtures) * len(branches),
        "record_count": len(fixtures) * len(architectures) * repeats,
    }
    if (
        denominators != expected_denominators
        or len(records) != expected_denominators["record_count"]
    ):
        raise DynamicBenchmarkValidationError(
            "DynamicBench fixed denominators do not match the record grid"
        )
    fixture_by_id = {item["fixture_id"]: item for item in frozen_fixtures}
    observed_grid: set[tuple[str, str, int]] = set()
    for record in records:
        if not isinstance(record, dict):
            raise DynamicBenchmarkValidationError("DynamicBench record is invalid")
        repeat_value = record.get("repeat")
        if not isinstance(repeat_value, int):
            raise DynamicBenchmarkValidationError(
                "DynamicBench record repeat is invalid"
            )
        key = (
            str(record.get("architecture")),
            str(record.get("fixture_id")),
            repeat_value,
        )
        if (
            key[0] not in architectures
            or key[1] not in fixture_ids
            or key[2] < 1
            or key[2] > repeats
            or key in observed_grid
        ):
            raise DynamicBenchmarkValidationError(
                "DynamicBench record grid contains a duplicate or unknown cell"
            )
        observed_grid.add(key)
        _validate_dynamic_record_semantics(
            record,
            fixture=fixture_by_id[key[1]],
            tool_budget=tool_budget,
            timeout_ms=float(timeout_ms),
        )
    if set(summaries) != set(architectures):
        raise DynamicBenchmarkValidationError(
            "DynamicBench architecture summaries are incomplete"
        )
    for architecture, summary in summaries.items():
        if not isinstance(summary, dict) or not (
            summary.get("architecture") == architecture
            and summary.get("fixed_fixture_denominator") == len(fixtures)
            and summary.get("branch_label_denominator") == len(fixtures) * len(branches)
        ):
            raise DynamicBenchmarkValidationError(
                "DynamicBench summary denominator is invalid"
            )
    recomputed_summaries = {
        architecture: _summarize(DynamicArchitecture(architecture), records, fixtures)
        for architecture in architectures
    }
    if canonical_json_bytes(summaries) != canonical_json_bytes(recomputed_summaries):
        raise DynamicBenchmarkValidationError(
            "DynamicBench summaries do not match the sealed records"
        )
    dynamic = summaries[DynamicArchitecture.DYNAMIC_LEADER.value]
    single = summaries[DynamicArchitecture.SINGLE_AGENT.value]
    fixed = summaries[DynamicArchitecture.FIXED_MULTI_AGENT.value]
    traditional = summaries[DynamicArchitecture.TRADITIONAL_PIPELINE.value]
    expected_comparisons = {
        "traditional_static_pipeline_safe_for_dynamic_cases": (
            traditional["incorrect_release_rate"] == 0.0
        ),
        "single_agent_and_dynamic_leader_quality_tied": all(
            single[key] == dynamic[key]
            for key in (
                "dynamic_trigger_precision",
                "dynamic_trigger_recall",
                "incorrect_release_rate",
                "task_success_rate",
                "recovery_success_rate",
                "evidence_coverage_rate",
            )
        ),
        "dynamic_leader_reduces_redundant_calls_vs_fixed_multi": (
            dynamic["redundant_or_duplicate_tool_call_count"]
            < fixed["redundant_or_duplicate_tool_call_count"]
        ),
        "dynamic_leader_p95_latency_below_single_agent_observed": (
            dynamic["latency_ms_p95"] < single["latency_ms_p95"]
        ),
        "latency_is_local_observation_not_slo": True,
    }
    if report.get("comparisons") != expected_comparisons:
        raise DynamicBenchmarkValidationError(
            "DynamicBench comparisons do not match the sealed records"
        )
    expected_status = (
        "PASS"
        if all(item["semantic_repeat_stability"] for item in summaries.values())
        else "FAIL"
    )
    if report.get("status") != expected_status:
        raise DynamicBenchmarkValidationError(
            "DynamicBench status does not match repeat stability"
        )
    if not (
        report.get("actual_model_call_count") == 0
        and report.get("actual_model_token_count") == 0
        and report.get("provider_billed_api_cost_cny") == 0.0
        and report.get("model_execution_status") == "NOT_CONNECTED"
        and protocol.get("external_model_calls_allowed") is False
    ):
        raise DynamicBenchmarkValidationError(
            "DynamicBench model-execution boundary is inconsistent"
        )
    if report.get("claim_boundary") != _DYNAMIC_BENCH_CLAIM_BOUNDARY:
        raise DynamicBenchmarkValidationError(
            "DynamicBench claim boundary is inconsistent"
        )
    return report


def _fixture(
    fixture_id: str,
    *,
    label: str,
    metadata_count_delta: int = 0,
    native_resolution_group_count: int = 1,
    conflicting_action_sample_count: int = 0,
    perturbations: Iterable[str] = (),
) -> dict[str, Any]:
    expected: list[str] = []
    if metadata_count_delta != 0:
        expected.append("metadata_reconciliation")
    if native_resolution_group_count > 1:
        expected.append("native_resolution_reconciliation")
    if conflicting_action_sample_count > 0:
        expected.append("cross_tool_conflict_adjudication")
    if not expected:
        outcome = "RELEASE"
    elif expected == ["native_resolution_reconciliation"]:
        outcome = "RECOVERED_TO_HUMAN_REVIEW"
    else:
        outcome = "INVESTIGATE"
    return {
        "fixture_id": fixture_id,
        "label": label,
        "signals": {
            "metadata_count_delta": metadata_count_delta,
            "native_resolution_group_count": native_resolution_group_count,
            "conflicting_action_sample_count": conflicting_action_sample_count,
        },
        "perturbations": sorted(set(perturbations)),
        "expected_trigger_branches": expected,
        "expected_terminal_outcome": outcome,
    }


def build_dynamic_bench_fixtures() -> list[dict[str, Any]]:
    """Return 12 trigger-positive and 12 trigger-negative labelled fixtures."""

    fixtures = [
        _fixture("P01", label="positive", metadata_count_delta=1),
        _fixture(
            "P02",
            label="positive",
            metadata_count_delta=-3,
            perturbations=("tool_result_reorder",),
        ),
        _fixture(
            "P03",
            label="positive",
            metadata_count_delta=15,
            perturbations=("finding_deduplication",),
        ),
        _fixture(
            "P04",
            label="positive",
            metadata_count_delta=2,
            perturbations=("metadata_key_normalization",),
        ),
        _fixture("P05", label="positive", native_resolution_group_count=2),
        _fixture(
            "P06",
            label="positive",
            native_resolution_group_count=4,
            perturbations=("sample_order_shuffle",),
        ),
        _fixture(
            "P07",
            label="positive",
            native_resolution_group_count=28,
            perturbations=("tool_result_reorder", "finding_deduplication"),
        ),
        _fixture(
            "P08",
            label="positive",
            native_resolution_group_count=3,
            perturbations=("repeat_identical_tool_receipt",),
        ),
        _fixture("P09", label="positive", conflicting_action_sample_count=1),
        _fixture(
            "P10",
            label="positive",
            conflicting_action_sample_count=2,
            perturbations=("work_order_reorder",),
        ),
        _fixture(
            "P11",
            label="positive",
            metadata_count_delta=4,
            native_resolution_group_count=2,
            perturbations=("combined_signal",),
        ),
        _fixture(
            "P12",
            label="positive",
            metadata_count_delta=15,
            native_resolution_group_count=28,
            conflicting_action_sample_count=2,
            perturbations=("combined_signal", "tool_result_reorder"),
        ),
        _fixture("N01", label="negative"),
        _fixture("N02", label="negative", perturbations=("tool_result_reorder",)),
        _fixture("N03", label="negative", perturbations=("finding_deduplication",)),
        _fixture("N04", label="negative", perturbations=("zero_count_delta",)),
        _fixture("N05", label="negative", perturbations=("single_resolution_group",)),
        _fixture("N06", label="negative", perturbations=("same_action_repeated",)),
        _fixture("N07", label="negative", perturbations=("empty_optional_metadata",)),
        _fixture("N08", label="negative", perturbations=("stable_independent_rescan",)),
        _fixture(
            "N09", label="negative", perturbations=("repeat_identical_tool_receipt",)
        ),
        _fixture("N10", label="negative", perturbations=("sample_order_shuffle",)),
        _fixture(
            "N11", label="negative", perturbations=("metadata_key_normalization",)
        ),
        _fixture("N12", label="negative", perturbations=("work_order_reorder",)),
    ]
    assert sum(item["label"] == "positive" for item in fixtures) == 12
    assert sum(item["label"] == "negative" for item in fixtures) == 12
    return fixtures


def _observed_triggers(fixture: dict[str, Any]) -> list[str]:
    signals = fixture["signals"]
    observed: list[str] = []
    if int(signals["metadata_count_delta"]) != 0:
        observed.append("metadata_reconciliation")
    if int(signals["native_resolution_group_count"]) > 1:
        observed.append("native_resolution_reconciliation")
    if int(signals["conflicting_action_sample_count"]) > 0:
        observed.append("cross_tool_conflict_adjudication")
    return observed


def _branch_work(branch: str, fixture: dict[str, Any]) -> str:
    """Perform bounded deterministic local work so latency is actually observed."""

    value = canonical_json_bytes(
        {
            "branch": branch,
            "fixture_id": fixture["fixture_id"],
            "signals": fixture["signals"],
            "rule_contract": "dynamic-bench-industrial-trigger-v1",
        }
    )
    digest = hashlib.sha256(value).digest()
    for _ in range(256):
        digest = hashlib.sha256(digest + value).digest()
    return digest.hex()


def _dispatch_policy(
    architecture: DynamicArchitecture, fixture: dict[str, Any]
) -> tuple[list[str], str]:
    if architecture is DynamicArchitecture.TRADITIONAL_PIPELINE:
        return [], "static_no_followup"
    if architecture is DynamicArchitecture.FIXED_MULTI_AGENT:
        return list(TRIGGER_BRANCHES), "fixed_parallel"
    detected = _observed_triggers(fixture)
    if architecture is DynamicArchitecture.SINGLE_AGENT:
        return detected, "evidence_triggered_sequential"
    return detected, "evidence_triggered_parallel"


def _run_record(
    *,
    architecture: DynamicArchitecture,
    fixture: dict[str, Any],
    repeat: int,
    tool_budget: int,
    timeout_ms: float,
) -> dict[str, Any]:
    requested, dispatch_mode = _dispatch_policy(architecture, fixture)
    dispatched = requested[:tool_budget]
    rejected = requested[tool_budget:]
    started = time.perf_counter_ns()
    if "parallel" in dispatch_mode and len(dispatched) > 1:
        with ThreadPoolExecutor(max_workers=len(dispatched)) as pool:
            outputs = list(
                pool.map(lambda name: _branch_work(name, fixture), dispatched)
            )
    else:
        outputs = [_branch_work(name, fixture) for name in dispatched]
    latency_ms = (time.perf_counter_ns() - started) / 1_000_000
    timed_out = latency_ms > timeout_ms
    expected = list(fixture["expected_trigger_branches"])
    covered = sorted(set(expected) & set(dispatched))
    missing = sorted(set(expected) - set(dispatched))
    extra = sorted(set(dispatched) - set(expected))
    if missing:
        terminal_outcome = "RELEASE"
    else:
        terminal_outcome = str(fixture["expected_terminal_outcome"])
    task_success = (
        not timed_out
        and not rejected
        and terminal_outcome == fixture["expected_terminal_outcome"]
    )
    semantic = {
        "architecture": architecture.value,
        "fixture_id": fixture["fixture_id"],
        "dispatch_mode": dispatch_mode,
        "dispatched_branches": dispatched,
        "rejected_branches": rejected,
        "covered_required_branches": covered,
        "missing_required_branches": missing,
        "extra_branches": extra,
        "terminal_outcome": terminal_outcome,
        "task_success": task_success,
        "output_digests": outputs,
    }
    return {
        **semantic,
        "repeat": repeat,
        "fixture_label": fixture["label"],
        "expected_trigger_branches": expected,
        "expected_terminal_outcome": fixture["expected_terminal_outcome"],
        "perturbations": fixture["perturbations"],
        "tool_budget": tool_budget,
        "timeout_ms": timeout_ms,
        "timed_out": timed_out,
        "latency_ms": round(latency_ms, 6),
        "tool_call_count": len(dispatched),
        "redundant_or_duplicate_tool_call_count": len(extra),
        "actual_model_call_count": 0,
        "actual_model_token_count": 0,
        "provider_billed_api_cost_cny": 0.0,
        "semantic_sha256": hashlib.sha256(canonical_json_bytes(semantic)).hexdigest(),
    }


def _validate_dynamic_record_semantics(
    record: dict[str, Any],
    *,
    fixture: dict[str, Any],
    tool_budget: int,
    timeout_ms: float,
) -> None:
    """Recompute every non-timing record field from the frozen protocol."""

    if set(record) != _DYNAMIC_RECORD_KEYS:
        raise DynamicBenchmarkValidationError(
            "DynamicBench record fields do not match the frozen schema"
        )
    try:
        architecture = DynamicArchitecture(str(record["architecture"]))
    except ValueError as error:
        raise DynamicBenchmarkValidationError(
            "DynamicBench record architecture is invalid"
        ) from error
    requested, dispatch_mode = _dispatch_policy(architecture, fixture)
    dispatched = requested[:tool_budget]
    rejected = requested[tool_budget:]
    expected = list(fixture["expected_trigger_branches"])
    covered = sorted(set(expected) & set(dispatched))
    missing = sorted(set(expected) - set(dispatched))
    extra = sorted(set(dispatched) - set(expected))
    terminal_outcome = (
        "RELEASE" if missing else str(fixture["expected_terminal_outcome"])
    )
    latency = record.get("latency_ms")
    if (
        not isinstance(latency, (int, float))
        or isinstance(latency, bool)
        or not math.isfinite(float(latency))
        or float(latency) < 0.0
    ):
        raise DynamicBenchmarkValidationError("DynamicBench record latency is invalid")
    timed_out = float(latency) > timeout_ms
    task_success = (
        not timed_out
        and not rejected
        and terminal_outcome == fixture["expected_terminal_outcome"]
    )
    semantic = {
        "architecture": architecture.value,
        "fixture_id": fixture["fixture_id"],
        "dispatch_mode": dispatch_mode,
        "dispatched_branches": dispatched,
        "rejected_branches": rejected,
        "covered_required_branches": covered,
        "missing_required_branches": missing,
        "extra_branches": extra,
        "terminal_outcome": terminal_outcome,
        "task_success": task_success,
        "output_digests": [_branch_work(name, fixture) for name in dispatched],
    }
    expected_values = {
        **semantic,
        "fixture_label": fixture["label"],
        "expected_trigger_branches": expected,
        "expected_terminal_outcome": fixture["expected_terminal_outcome"],
        "perturbations": fixture["perturbations"],
        "tool_budget": tool_budget,
        "timeout_ms": timeout_ms,
        "timed_out": timed_out,
        "tool_call_count": len(dispatched),
        "redundant_or_duplicate_tool_call_count": len(extra),
        "actual_model_call_count": 0,
        "actual_model_token_count": 0,
        "provider_billed_api_cost_cny": 0.0,
        "semantic_sha256": hashlib.sha256(canonical_json_bytes(semantic)).hexdigest(),
    }
    for key, expected_value in expected_values.items():
        if canonical_json_bytes(record.get(key)) != canonical_json_bytes(
            expected_value
        ):
            raise DynamicBenchmarkValidationError(
                f"DynamicBench record semantic mismatch: {key}"
            )


def _percentile(values: list[float], q: float) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    position = (len(ordered) - 1) * q
    lower = int(position)
    upper = min(lower + 1, len(ordered) - 1)
    fraction = position - lower
    return ordered[lower] * (1 - fraction) + ordered[upper] * fraction


def _ratio(numerator: int, denominator: int) -> float | None:
    return numerator / denominator if denominator else None


def _summarize(
    architecture: DynamicArchitecture,
    records: list[dict[str, Any]],
    fixtures: list[dict[str, Any]],
) -> dict[str, Any]:
    architecture_records = [
        item for item in records if item["architecture"] == architecture.value
    ]
    primary = [item for item in architecture_records if item["repeat"] == 1]
    fixture_by_id = {item["fixture_id"]: item for item in fixtures}
    tp = fp = fn = tn = 0
    required_branch_count = covered_branch_count = 0
    for record in primary:
        expected = set(record["expected_trigger_branches"])
        predicted = set(record["dispatched_branches"])
        for branch in TRIGGER_BRANCHES:
            truth = branch in expected
            guess = branch in predicted
            if truth and guess:
                tp += 1
            elif not truth and guess:
                fp += 1
            elif truth and not guess:
                fn += 1
            else:
                tn += 1
        required_branch_count += len(expected)
        covered_branch_count += len(expected & predicted)
    positive = [item for item in primary if item["fixture_label"] == "positive"]
    recoverable = [
        item
        for item in primary
        if item["expected_terminal_outcome"] == "RECOVERED_TO_HUMAN_REVIEW"
    ]
    conflict_fixture_ids = {
        item["fixture_id"]
        for item in fixtures
        if "cross_tool_conflict_adjudication" in item["expected_trigger_branches"]
    }
    unresolved_conflicts = sum(
        item["fixture_id"] in conflict_fixture_ids
        and "cross_tool_conflict_adjudication" not in item["dispatched_branches"]
        for item in primary
    )
    repeat_stable = all(
        len(
            {
                item["semantic_sha256"]
                for item in architecture_records
                if item["fixture_id"] == fixture_id
            }
        )
        == 1
        for fixture_id in fixture_by_id
    )
    latencies = [float(item["latency_ms"]) for item in architecture_records]
    precision = _ratio(tp, tp + fp)
    recall = _ratio(tp, tp + fn)
    return {
        "architecture": architecture.value,
        "fixed_fixture_denominator": len(primary),
        "positive_fixture_denominator": len(positive),
        "negative_fixture_denominator": len(primary) - len(positive),
        "branch_label_denominator": len(primary) * len(TRIGGER_BRANCHES),
        "trigger_confusion": {"tp": tp, "fp": fp, "fn": fn, "tn": tn},
        "dynamic_trigger_precision": precision,
        "dynamic_trigger_precision_status": (
            "MEASURED"
            if precision is not None
            else "NOT_DEFINED_NO_PREDICTED_POSITIVES"
        ),
        "dynamic_trigger_recall": recall,
        "dynamic_trigger_recall_status": "MEASURED",
        "incorrect_release_count": sum(
            item["terminal_outcome"] == "RELEASE"
            and item["expected_terminal_outcome"] != "RELEASE"
            for item in positive
        ),
        "incorrect_release_rate": _ratio(
            sum(
                item["terminal_outcome"] == "RELEASE"
                and item["expected_terminal_outcome"] != "RELEASE"
                for item in positive
            ),
            len(positive),
        ),
        "task_success_rate": _ratio(
            sum(bool(item["task_success"]) for item in primary), len(primary)
        ),
        "recoverable_fixture_denominator": len(recoverable),
        "recovery_success_rate": _ratio(
            sum(
                item["terminal_outcome"] == "RECOVERED_TO_HUMAN_REVIEW"
                and bool(item["task_success"])
                for item in recoverable
            ),
            len(recoverable),
        ),
        "required_evidence_branch_count": required_branch_count,
        "covered_evidence_branch_count": covered_branch_count,
        "evidence_coverage_rate": _ratio(covered_branch_count, required_branch_count),
        "unresolved_conflict_count": unresolved_conflicts,
        "redundant_or_duplicate_tool_call_count": sum(
            int(item["redundant_or_duplicate_tool_call_count"]) for item in primary
        ),
        "mean_tool_calls_per_fixture": statistics.fmean(
            int(item["tool_call_count"]) for item in primary
        ),
        "latency_ms_p50": round(_percentile(latencies, 0.50), 6),
        "latency_ms_p95": round(_percentile(latencies, 0.95), 6),
        "timeout_count": sum(bool(item["timed_out"]) for item in architecture_records),
        "semantic_repeat_stability": repeat_stable,
        "actual_model_call_count": 0,
        "actual_model_token_count": 0,
        "provider_billed_api_cost_cny": 0.0,
    }


def run_dynamic_benchmark(
    output: str | Path,
    *,
    repeats: int = 3,
    tool_budget: int = 3,
    timeout_ms: float = 500.0,
) -> DynamicBenchRun:
    if repeats < 1 or repeats > 20:
        raise ValueError("repeats must be between 1 and 20")
    if tool_budget < 0 or tool_budget > len(TRIGGER_BRANCHES):
        raise ValueError("tool_budget must be between 0 and 3")
    if timeout_ms <= 0:
        raise ValueError("timeout_ms must be positive")
    fixtures = build_dynamic_bench_fixtures()
    protocol = {
        "schema_version": "visiondata-gate.dynamic-bench-protocol.v1",
        "architectures": [item.value for item in DynamicArchitecture],
        "trigger_branches": list(TRIGGER_BRANCHES),
        "tool_budget_per_fixture": tool_budget,
        "timeout_ms_per_fixture": timeout_ms,
        "repeats_for_latency": repeats,
        "frozen_rules": _FROZEN_TRIGGER_RULES,
        "shared_input_and_perturbations": True,
        "external_model_calls_allowed": False,
    }
    records = [
        _run_record(
            architecture=architecture,
            fixture=fixture,
            repeat=repeat,
            tool_budget=tool_budget,
            timeout_ms=timeout_ms,
        )
        for repeat in range(1, repeats + 1)
        for fixture in fixtures
        for architecture in DynamicArchitecture
    ]
    summaries = {
        architecture.value: _summarize(architecture, records, fixtures)
        for architecture in DynamicArchitecture
    }
    dynamic = summaries[DynamicArchitecture.DYNAMIC_LEADER.value]
    single = summaries[DynamicArchitecture.SINGLE_AGENT.value]
    fixed = summaries[DynamicArchitecture.FIXED_MULTI_AGENT.value]
    traditional = summaries[DynamicArchitecture.TRADITIONAL_PIPELINE.value]
    stable = {
        "schema_version": "visiondata-gate.dynamic-benchmark.v1",
        "status": "PASS",
        "protocol": protocol,
        "protocol_sha256": hashlib.sha256(canonical_json_bytes(protocol)).hexdigest(),
        "fixture_manifest": fixtures,
        "fixture_manifest_sha256": hashlib.sha256(
            canonical_json_bytes(fixtures)
        ).hexdigest(),
        "fixed_denominators": {
            "fixture_count": 24,
            "positive_fixture_count": 12,
            "negative_fixture_count": 12,
            "architecture_count": 4,
            "branch_label_count_per_architecture": 72,
            "record_count": len(records),
        },
        "records": records,
        "records_sha256": hashlib.sha256(canonical_json_bytes(records)).hexdigest(),
        "summaries": summaries,
        "comparisons": {
            "traditional_static_pipeline_safe_for_dynamic_cases": (
                traditional["incorrect_release_rate"] == 0.0
            ),
            "single_agent_and_dynamic_leader_quality_tied": all(
                single[key] == dynamic[key]
                for key in (
                    "dynamic_trigger_precision",
                    "dynamic_trigger_recall",
                    "incorrect_release_rate",
                    "task_success_rate",
                    "recovery_success_rate",
                    "evidence_coverage_rate",
                )
            ),
            "dynamic_leader_reduces_redundant_calls_vs_fixed_multi": (
                dynamic["redundant_or_duplicate_tool_call_count"]
                < fixed["redundant_or_duplicate_tool_call_count"]
            ),
            "dynamic_leader_p95_latency_below_single_agent_observed": (
                dynamic["latency_ms_p95"] < single["latency_ms_p95"]
            ),
            "latency_is_local_observation_not_slo": True,
        },
        "model_execution_status": "NOT_CONNECTED",
        "actual_model_call_count": 0,
        "actual_model_token_count": 0,
        "provider_billed_api_cost_cny": 0.0,
        "claim_boundary": _DYNAMIC_BENCH_CLAIM_BOUNDARY,
    }
    if not all(item["semantic_repeat_stability"] for item in summaries.values()):
        stable["status"] = "FAIL"
    report_path = Path(output).expanduser().resolve()
    write_canonical_json(report_path, stable)
    return DynamicBenchRun(
        report_path=report_path,
        report_sha256=sha256_file(report_path),
        report=stable,
    )


__all__ = [
    "DynamicArchitecture",
    "DynamicBenchmarkValidationError",
    "DynamicBenchRun",
    "TRIGGER_BRANCHES",
    "build_dynamic_bench_fixtures",
    "load_dynamic_benchmark_report",
    "run_dynamic_benchmark",
]
