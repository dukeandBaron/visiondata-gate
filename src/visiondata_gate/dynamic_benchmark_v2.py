"""DynamicBench-v2 for deterministic Worker selection semantics.

The v2 benchmark is additive and does not modify DynamicBench-v1.  It contains
24 precedence fixtures, four candidate-order variants, and three exact repeats
for a fixed denominator of 288 records.  It measures selection correctness,
input-order invariance, and receipt stability only; it is not an industrial
accuracy test or calibration evidence for probabilistic active sensing.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

import rfc8785

from .worker_selection import (
    BlockingSeverity,
    MeasuredCostBucket,
    WorkerCandidate,
    build_worker_selection_receipt,
    verify_worker_selection_receipt,
)


SCHEMA_VERSION = "visiondata-gate.dynamic-benchmark.v2"
BENCHMARK_ID = "DynamicBench-v2-worker-selection"
INPUT_VARIANTS = ("identity", "reverse", "rotate_left", "rotate_right")
REPEATS = 3
FIXTURE_COUNT = 24
FIXED_RECORD_COUNT = FIXTURE_COUNT * len(INPUT_VARIANTS) * REPEATS


class DynamicBenchmarkV2ValidationError(ValueError):
    """Raised when a stored v2 report fails deterministic replay."""


def _canonical_jcs_bytes(value: object) -> bytes:
    try:
        return rfc8785.dumps(value)
    except (rfc8785.CanonicalizationError, TypeError, UnicodeError) as error:
        raise DynamicBenchmarkV2ValidationError(
            f"DynamicBench-v2 payload cannot be canonicalized: {error}"
        ) from error


def _sha256(value: object) -> str:
    return hashlib.sha256(_canonical_jcs_bytes(value)).hexdigest()


def _fixed_protocol() -> dict[str, Any]:
    """Return the immutable protocol whose identity defines DynamicBench-v2."""

    return {
        "benchmark_id": BENCHMARK_ID,
        "scope": "deterministic Worker selection semantics only",
        "fixture_count": FIXTURE_COUNT,
        "input_variants": list(INPUT_VARIANTS),
        "repeat_count": REPEATS,
        "fixed_record_count": FIXED_RECORD_COUNT,
        "worker_budget": 1,
        "external_model_calls_allowed": False,
        "claim_boundary": (
            "Not industrial accuracy, model quality, latency, probabilistic active-sensing "
            "calibration, or competitor evidence."
        ),
    }


def _candidate(
    worker_id: str,
    *,
    eligible: bool = True,
    severity: BlockingSeverity = BlockingSeverity.WARNING,
    hypothesis_count: int = 1,
    unresolved_count: int = 1,
    cost: MeasuredCostBucket = MeasuredCostBucket.MEDIUM,
) -> WorkerCandidate:
    return WorkerCandidate(
        worker_id=worker_id,
        eligible=eligible,
        ineligibility_reasons=[] if eligible else ["MISSING_REQUIRED_TOOL_CONTRACT"],
        blocking_severity=severity,
        discriminated_hypothesis_ids=[
            f"H-{worker_id}-{index}" for index in range(hypothesis_count)
        ],
        unresolved_evidence_refs=[
            f"evidence:{worker_id}:{index}" for index in range(unresolved_count)
        ],
        measured_cost_bucket=cost,
    )


def _fixture(
    fixture_id: str,
    rule_under_test: str,
    candidates: list[WorkerCandidate],
    expected_worker_id: str,
) -> dict[str, Any]:
    return {
        "fixture_id": fixture_id,
        "rule_under_test": rule_under_test,
        "worker_budget": 1,
        "candidates": [item.model_dump(mode="json") for item in candidates],
        "expected_selected_worker_ids": [expected_worker_id],
    }


def build_worker_selection_bench_fixtures() -> list[dict[str, Any]]:
    """Return 24 fixtures covering each lexicographic precedence rule."""

    fixtures: list[dict[str, Any]] = []
    for index in range(1, 5):
        prefix = f"S{index:02d}"
        winner = f"{prefix}-blocking"
        fixtures.append(
            _fixture(
                prefix,
                "blocking_severity",
                [
                    _candidate(winner, severity=BlockingSeverity.BLOCKING),
                    _candidate(f"{prefix}-warning", severity=BlockingSeverity.WARNING),
                    _candidate(f"{prefix}-none", severity=BlockingSeverity.NONE),
                ],
                winner,
            )
        )
    for index in range(1, 5):
        prefix = f"D{index:02d}"
        winner = f"{prefix}-three"
        fixtures.append(
            _fixture(
                prefix,
                "hypothesis_discrimination_count",
                [
                    _candidate(winner, hypothesis_count=3),
                    _candidate(f"{prefix}-two", hypothesis_count=2),
                    _candidate(f"{prefix}-one", hypothesis_count=1),
                ],
                winner,
            )
        )
    for index in range(1, 5):
        prefix = f"U{index:02d}"
        winner = f"{prefix}-three"
        fixtures.append(
            _fixture(
                prefix,
                "unresolved_evidence_count",
                [
                    _candidate(winner, unresolved_count=3),
                    _candidate(f"{prefix}-two", unresolved_count=2),
                    _candidate(f"{prefix}-one", unresolved_count=1),
                ],
                winner,
            )
        )
    for index in range(1, 5):
        prefix = f"C{index:02d}"
        winner = f"{prefix}-low"
        fixtures.append(
            _fixture(
                prefix,
                "measured_cost_bucket",
                [
                    _candidate(winner, cost=MeasuredCostBucket.LOW),
                    _candidate(f"{prefix}-medium", cost=MeasuredCostBucket.MEDIUM),
                    _candidate(f"{prefix}-high", cost=MeasuredCostBucket.HIGH),
                ],
                winner,
            )
        )
    for index in range(1, 5):
        prefix = f"I{index:02d}"
        winner = f"{prefix}-a"
        fixtures.append(
            _fixture(
                prefix,
                "stable_worker_id",
                [
                    _candidate(f"{prefix}-c"),
                    _candidate(f"{prefix}-b"),
                    _candidate(winner),
                ],
                winner,
            )
        )
    for index in range(1, 5):
        prefix = f"E{index:02d}"
        winner = f"{prefix}-eligible"
        fixtures.append(
            _fixture(
                prefix,
                "eligibility_guard",
                [
                    _candidate(
                        f"{prefix}-ineligible",
                        eligible=False,
                        severity=BlockingSeverity.BLOCKING,
                        hypothesis_count=4,
                        unresolved_count=4,
                        cost=MeasuredCostBucket.LOW,
                    ),
                    _candidate(winner),
                    _candidate(f"{prefix}-eligible-z"),
                ],
                winner,
            )
        )
    if len(fixtures) != FIXTURE_COUNT:
        raise AssertionError(
            f"DynamicBench-v2 requires exactly {FIXTURE_COUNT} fixtures"
        )
    return fixtures


def _apply_variant(
    candidates: list[WorkerCandidate], variant: str
) -> list[WorkerCandidate]:
    if variant == "identity":
        return list(candidates)
    if variant == "reverse":
        return list(reversed(candidates))
    if variant == "rotate_left":
        return candidates[1:] + candidates[:1]
    if variant == "rotate_right":
        return candidates[-1:] + candidates[:-1]
    raise DynamicBenchmarkV2ValidationError(f"unknown input variant: {variant}")


def _summary(
    records: list[dict[str, Any]], fixtures: list[dict[str, Any]]
) -> dict[str, Any]:
    correct_count = sum(item["selection_correct"] for item in records)
    stable_fixture_count = 0
    order_invariant_fixture_count = 0
    for fixture in fixtures:
        fixture_records = [
            item for item in records if item["fixture_id"] == fixture["fixture_id"]
        ]
        selected_outputs = {
            tuple(item["selected_worker_ids"]) for item in fixture_records
        }
        receipt_digests = {item["selection_receipt_sha256"] for item in fixture_records}
        order_invariant_fixture_count += len(selected_outputs) == 1
        stable_fixture_count += len(receipt_digests) == 1
    return {
        "record_count": len(records),
        "correct_selection_count": correct_count,
        "selection_accuracy": correct_count / len(records) if records else None,
        "fixture_count": len(fixtures),
        "input_order_invariant_fixture_count": order_invariant_fixture_count,
        "repeat_stable_fixture_count": stable_fixture_count,
        "all_records_correct": correct_count == len(records),
        "all_fixtures_input_order_invariant": (
            order_invariant_fixture_count == len(fixtures)
        ),
        "all_fixtures_repeat_stable": stable_fixture_count == len(fixtures),
    }


def build_worker_selection_benchmark_report() -> dict[str, Any]:
    """Execute and seal the fixed 288-record selection benchmark."""

    fixtures = build_worker_selection_bench_fixtures()
    protocol = _fixed_protocol()
    records: list[dict[str, Any]] = []
    for fixture in fixtures:
        candidates = [
            WorkerCandidate.model_validate(item) for item in fixture["candidates"]
        ]
        for variant in INPUT_VARIANTS:
            ordered = _apply_variant(candidates, variant)
            for repeat in range(1, REPEATS + 1):
                receipt = build_worker_selection_receipt(
                    ordered, worker_budget=int(fixture["worker_budget"])
                )
                verify_worker_selection_receipt(receipt)
                selected = receipt.selected_worker_ids
                semantic = {
                    "fixture_id": fixture["fixture_id"],
                    "rule_under_test": fixture["rule_under_test"],
                    "input_variant": variant,
                    "repeat": repeat,
                    "selected_worker_ids": selected,
                    "expected_selected_worker_ids": fixture[
                        "expected_selected_worker_ids"
                    ],
                    "selection_receipt_sha256": receipt.receipt_sha256,
                    "actual_model_call_count": 0,
                }
                records.append(
                    {
                        **semantic,
                        "selection_correct": (
                            selected == fixture["expected_selected_worker_ids"]
                        ),
                        "semantic_sha256": _sha256(semantic),
                    }
                )
    summary = _summary(records, fixtures)
    status = (
        "PASS"
        if summary["all_records_correct"]
        and summary["all_fixtures_input_order_invariant"]
        and summary["all_fixtures_repeat_stable"]
        else "FAIL"
    )
    return {
        "schema_version": SCHEMA_VERSION,
        "benchmark_id": BENCHMARK_ID,
        "status": status,
        "protocol": protocol,
        "protocol_sha256": _sha256(protocol),
        "fixture_manifest": fixtures,
        "fixture_manifest_sha256": _sha256(fixtures),
        "records": records,
        "records_sha256": _sha256(records),
        "summary": summary,
        "actual_model_call_count": 0,
        "actual_model_token_count": 0,
        "provider_billed_api_cost_cny": 0.0,
        "model_execution_status": "NOT_CONNECTED",
    }


def validate_worker_selection_benchmark_report(report: dict[str, Any]) -> None:
    """Validate hashes, grid, summaries, and every selection by replay."""

    if report.get("schema_version") != SCHEMA_VERSION:
        raise DynamicBenchmarkV2ValidationError("DynamicBench-v2 schema is invalid")
    if report.get("benchmark_id") != BENCHMARK_ID:
        raise DynamicBenchmarkV2ValidationError(
            "DynamicBench-v2 benchmark identity drifted"
        )
    for payload_key, digest_key in (
        ("protocol", "protocol_sha256"),
        ("fixture_manifest", "fixture_manifest_sha256"),
        ("records", "records_sha256"),
    ):
        if _sha256(report.get(payload_key)) != report.get(digest_key):
            raise DynamicBenchmarkV2ValidationError(
                f"DynamicBench-v2 {payload_key} hash mismatch"
            )
    fixtures = report.get("fixture_manifest")
    records = report.get("records")
    if not isinstance(fixtures, list) or not isinstance(records, list):
        raise DynamicBenchmarkV2ValidationError("DynamicBench-v2 grid is invalid")
    expected_protocol = _fixed_protocol()
    if report.get("protocol") != expected_protocol:
        raise DynamicBenchmarkV2ValidationError(
            "DynamicBench-v2 fixed protocol drifted"
        )
    expected_fixtures = build_worker_selection_bench_fixtures()
    if fixtures != expected_fixtures:
        raise DynamicBenchmarkV2ValidationError(
            "DynamicBench-v2 fixture manifest drifted"
        )
    if len(fixtures) != FIXTURE_COUNT or len(records) != FIXED_RECORD_COUNT:
        raise DynamicBenchmarkV2ValidationError(
            "DynamicBench-v2 fixed denominator mismatch"
        )
    fixture_by_id = {item["fixture_id"]: item for item in fixtures}
    observed_grid: set[tuple[str, str, int]] = set()
    for record in records:
        key = (
            str(record.get("fixture_id")),
            str(record.get("input_variant")),
            int(record.get("repeat", 0)),
        )
        if (
            key in observed_grid
            or key[0] not in fixture_by_id
            or key[1] not in INPUT_VARIANTS
            or key[2] < 1
            or key[2] > REPEATS
        ):
            raise DynamicBenchmarkV2ValidationError(
                "DynamicBench-v2 contains a duplicate or unknown grid cell"
            )
        observed_grid.add(key)
        fixture = fixture_by_id[key[0]]
        base = [WorkerCandidate.model_validate(item) for item in fixture["candidates"]]
        receipt = build_worker_selection_receipt(
            _apply_variant(base, key[1]), worker_budget=int(fixture["worker_budget"])
        )
        semantic = {
            "fixture_id": key[0],
            "rule_under_test": fixture["rule_under_test"],
            "input_variant": key[1],
            "repeat": key[2],
            "selected_worker_ids": receipt.selected_worker_ids,
            "expected_selected_worker_ids": fixture["expected_selected_worker_ids"],
            "selection_receipt_sha256": receipt.receipt_sha256,
            "actual_model_call_count": 0,
        }
        if (
            record.get("rule_under_test") != fixture["rule_under_test"]
            or record.get("selected_worker_ids") != receipt.selected_worker_ids
            or record.get("selection_receipt_sha256") != receipt.receipt_sha256
            or record.get("actual_model_call_count") != 0
            or record.get("selection_correct")
            is not (
                receipt.selected_worker_ids == fixture["expected_selected_worker_ids"]
            )
            or record.get("semantic_sha256") != _sha256(semantic)
        ):
            raise DynamicBenchmarkV2ValidationError(
                "DynamicBench-v2 record failed deterministic replay"
            )
    expected_summary = _summary(records, fixtures)
    if report.get("summary") != expected_summary:
        raise DynamicBenchmarkV2ValidationError("DynamicBench-v2 summary mismatch")
    expected_status = (
        "PASS"
        if expected_summary["all_records_correct"]
        and expected_summary["all_fixtures_input_order_invariant"]
        and expected_summary["all_fixtures_repeat_stable"]
        else "FAIL"
    )
    if report.get("status") != expected_status:
        raise DynamicBenchmarkV2ValidationError("DynamicBench-v2 status mismatch")
    if not (
        report.get("actual_model_call_count") == 0
        and report.get("actual_model_token_count") == 0
        and report.get("provider_billed_api_cost_cny") == 0.0
        and report.get("model_execution_status") == "NOT_CONNECTED"
    ):
        raise DynamicBenchmarkV2ValidationError(
            "DynamicBench-v2 model-execution boundary is inconsistent"
        )


def write_worker_selection_benchmark_report(output_path: str | Path) -> Path:
    """Build, validate, and write one canonical UTF-8 report."""

    report = build_worker_selection_benchmark_report()
    validate_worker_selection_benchmark_report(report)
    path = Path(output_path).expanduser().resolve()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(_canonical_jcs_bytes(report) + b"\n")
    return path


def load_worker_selection_benchmark_report(path: str | Path) -> dict[str, Any]:
    """Load one report and perform full replay validation."""

    report_path = Path(path).expanduser().resolve(strict=True)
    try:
        report = json.loads(report_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise DynamicBenchmarkV2ValidationError(
            "DynamicBench-v2 report is unreadable"
        ) from error
    if not isinstance(report, dict):
        raise DynamicBenchmarkV2ValidationError(
            "DynamicBench-v2 report must be an object"
        )
    validate_worker_selection_benchmark_report(report)
    return report


__all__ = [
    "DynamicBenchmarkV2ValidationError",
    "build_worker_selection_bench_fixtures",
    "build_worker_selection_benchmark_report",
    "load_worker_selection_benchmark_report",
    "validate_worker_selection_benchmark_report",
    "write_worker_selection_benchmark_report",
]
