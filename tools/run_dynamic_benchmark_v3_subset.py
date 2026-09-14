from __future__ import annotations

import argparse
import hashlib
from pathlib import Path
import tomllib
from typing import Any, Sequence

import rfc8785

from visiondata_gate.dynamic_benchmark_v3 import (
    build_dynamic_replanning_benchmark_report,
    load_dynamic_replanning_benchmark_report,
)


SCHEMA_VERSION = "visiondata-gate.dynamic-benchmark-v3-repro-subset.v1"
FROZEN_PROFILES = {
    "balanced-smoke-a-v1": ("C01", "F02", "I01", "N02"),
    "balanced-smoke-b-v1": ("C02", "F01", "I02", "N01"),
}
DEFAULT_PROFILE = "balanced-smoke-a-v1"
COMPLEMENTARY_PROFILE = {
    "balanced-smoke-a-v1": "balanced-smoke-b-v1",
    "balanced-smoke-b-v1": "balanced-smoke-a-v1",
}
EXPECTED_SCENARIOS = {
    "conflicting_evidence",
    "tool_failure",
    "indeterminate",
    "evidence_changed_next_step",
}
CLAIM_BOUNDARY = (
    "This deterministic four-fixture projection is a reproducibility aid for the "
    "author-defined DynamicBench-v3 protocol. It is not a new benchmark result, "
    "an external ReAct or LangGraph comparison, industrial effectiveness evidence, "
    "customer validation, or production-release authority."
)


def _sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _strategy_metrics(records: list[dict[str, Any]]) -> dict[str, int]:
    return {
        "correct_terminal_disposition_count": sum(
            bool(item["correct_terminal_disposition"]) for item in records
        ),
        "fixed_fixture_denominator": len(records),
        "tool_failure_recovery_eligible_count": sum(
            bool(item["tool_failure_recovery_eligible"]) for item in records
        ),
        "tool_failure_recovery_success_count": sum(
            bool(item["tool_failure_recovery_success"]) for item in records
        ),
        "total_tool_call_count": sum(int(item["tool_call_count"]) for item in records),
        "unnecessary_tool_call_count": sum(
            int(item["unnecessary_tool_call_count"]) for item in records
        ),
        "unsafe_release_count": sum(bool(item["unsafe_release"]) for item in records),
    }


def build_subset_report(
    full_report_path: str | Path | None = None,
    *,
    fixture_ids: Sequence[str] = FROZEN_PROFILES[DEFAULT_PROFILE],
    profile_id: str = DEFAULT_PROFILE,
) -> dict[str, Any]:
    rebuilt = build_dynamic_replanning_benchmark_report()
    stored_report: dict[str, Any] | None = None
    report_path: Path | None = None
    if full_report_path is not None:
        report_path = Path(full_report_path).expanduser().resolve(strict=True)
        stored_report = load_dynamic_replanning_benchmark_report(report_path)
        if rfc8785.dumps(stored_report) != rfc8785.dumps(rebuilt):
            raise ValueError(
                "the stored full report is valid but current source does not reproduce it"
            )
    source_report = rebuilt

    selected_ids = list(dict.fromkeys(fixture_ids))
    if len(selected_ids) != len(fixture_ids) or len(selected_ids) != 4:
        raise ValueError("the reproducibility subset requires four unique fixture IDs")
    fixtures_by_id = {
        str(item["fixture_id"]): item for item in source_report["fixture_manifest"]
    }
    unknown = sorted(set(selected_ids) - set(fixtures_by_id))
    if unknown:
        raise ValueError("unknown DynamicBench-v3 fixture IDs: " + ", ".join(unknown))
    selected_fixtures = [fixtures_by_id[fixture_id] for fixture_id in selected_ids]
    scenarios = {str(item["scenario_class"]) for item in selected_fixtures}
    if scenarios != EXPECTED_SCENARIOS:
        raise ValueError(
            "the reproducibility subset requires one fixture from every scenario class"
        )

    selected_set = set(selected_ids)
    records = [
        item
        for item in source_report["records"]
        if str(item["fixture_id"]) in selected_set
    ]
    strategies = [str(item) for item in source_report["protocol"]["strategies"]]
    expected_grid = {
        (strategy, fixture_id)
        for strategy in strategies
        for fixture_id in selected_ids
    }
    observed_grid = {
        (str(item["strategy"]), str(item["fixture_id"])) for item in records
    }
    if observed_grid != expected_grid or len(records) != len(expected_grid):
        raise ValueError("the reproducibility subset record grid is incomplete")

    metrics = {
        strategy: _strategy_metrics(
            [item for item in records if item["strategy"] == strategy]
        )
        for strategy in strategies
    }
    repo_root = Path(__file__).resolve().parents[1]
    source_module = repo_root / "src" / "visiondata_gate" / "dynamic_benchmark_v3.py"
    pyproject_path = repo_root / "pyproject.toml"
    uv_lock_path = repo_root / "uv.lock"
    with pyproject_path.open("rb") as stream:
        supported_python = str(tomllib.load(stream)["project"]["requires-python"])
    is_frozen_profile = (
        profile_id in FROZEN_PROFILES
        and tuple(selected_ids) == FROZEN_PROFILES[profile_id]
    )
    entry_tool_counts: dict[str, int] = {}
    expected_terminal_counts: dict[str, int] = {}
    for fixture in selected_fixtures:
        entry_tool = str(fixture["initial_input"]["entry_tool"])
        entry_tool_counts[entry_tool] = entry_tool_counts.get(entry_tool, 0) + 1
        terminal = str(fixture["expected_terminal_disposition"])
        expected_terminal_counts[terminal] = expected_terminal_counts.get(terminal, 0) + 1
    source_full_report: dict[str, Any] = {
        "origin": "BUILT_FROM_CURRENT_SOURCE",
        "stored_report_match": "NOT_REQUESTED",
        "sealed_report_sha256": source_report["sealed_report_sha256"],
        "protocol_sha256": source_report["protocol_sha256"],
        "fixture_manifest_sha256": source_report["fixture_manifest_sha256"],
        "records_sha256": source_report["records_sha256"],
        "fixture_count": len(source_report["fixture_manifest"]),
        "record_count": len(source_report["records"]),
        "self_validation_passed": True,
    }
    if stored_report is not None and report_path is not None:
        source_full_report.update(
            {
                "origin": "BUILT_AND_MATCHED_STORED_REPORT",
                "stored_report_match": True,
                "stored_report_file_sha256": _sha256_bytes(report_path.read_bytes()),
            }
        )
    stable: dict[str, Any] = {
        "schema_version": SCHEMA_VERSION,
        "status": (
            "PASS_LOCAL_REPRODUCIBILITY_SUBSET"
            if is_frozen_profile
            else "CUSTOM_SELECTION_NOT_COMPARABLE"
        ),
        "source_full_report": source_full_report,
        "source_code": {
            "repository_relative_path": (
                "src/visiondata_gate/dynamic_benchmark_v3.py"
            ),
            "file_sha256": _sha256_bytes(source_module.read_bytes()),
            "pyproject_file_sha256": _sha256_bytes(pyproject_path.read_bytes()),
            "uv_lock_sha256": _sha256_bytes(uv_lock_path.read_bytes()),
            "supported_python": supported_python,
        },
        "selection": {
            "profile_id": profile_id if is_frozen_profile else "custom",
            "complementary_profile_id": (
                COMPLEMENTARY_PROFILE[profile_id]
                if is_frozen_profile
                else "NOT_APPLICABLE"
            ),
            "method": (
                "frozen_balanced_entry_and_terminal_profile"
                if is_frozen_profile
                else "custom_one_fixture_per_scenario_not_comparable"
            ),
            "fixture_ids": selected_ids,
            "scenario_count": len(scenarios),
            "strategy_count": len(strategies),
            "record_count": len(records),
            "entry_tool_counts": dict(sorted(entry_tool_counts.items())),
            "expected_terminal_disposition_counts": dict(
                sorted(expected_terminal_counts.items())
            ),
        },
        "protocol_parameters": {
            "schema_version": source_report["protocol"]["schema_version"],
            "benchmark_id": source_report["protocol"]["benchmark_id"],
            "strategies": strategies,
            "tool_budget_per_fixture": source_report["protocol"][
                "tool_budget_per_fixture"
            ],
            "fixed_rule_plan": source_report["protocol"]["fixed_rule_plan"],
            "terminal_judge": source_report["protocol"]["terminal_judge"],
            "planner_kind": "deterministic_evidence_state_router",
            "planner_entrypoint": (
                "visiondata_gate.dynamic_benchmark_v3._execute_strategy"
            ),
            "randomness_used": False,
            "random_seed": "NOT_APPLICABLE",
            "model_id": "NOT_CONNECTED",
            "model_temperature": "NOT_APPLICABLE",
            "external_model_calls_allowed": source_report["protocol"][
                "external_model_calls_allowed"
            ],
            "shared_initial_input": source_report["protocol"]["shared_initial_input"],
            "shared_tool_result_mapping": source_report["protocol"][
                "shared_tool_result_mapping"
            ],
            "shared_fail_closed_terminal_judge": source_report["protocol"][
                "shared_fail_closed_terminal_judge"
            ],
        },
        "fixture_manifest": selected_fixtures,
        "raw_records": records,
        "metrics": metrics,
        "actual_model_call_count": 0,
        "model_temperature": "NOT_APPLICABLE",
        "random_seed": "NOT_APPLICABLE",
        "external_agent_baseline_status": "NOT_RUN",
        "external_baselines": {
            "langgraph": "NOT_RUN",
            "react": "NOT_RUN",
        },
        "industrial_effectiveness_status": "NOT_EVALUATED",
        "production_release_allowed": False,
        "self_evaluation_bias": [
            "fixtures, expected outcomes, and both compared strategies are author-defined",
            "the fixed baseline is not a ReAct, LangGraph, or third-party Agent baseline",
            "the subset has four synthetic fixtures and cannot replace the full eight-fixture report",
            "zero model calls means this evaluates deterministic orchestration, not LLM planning quality",
        ],
        "claim_boundary": CLAIM_BOUNDARY,
        "digest_profile": "RFC8785_JCS_THEN_UNKEYED_SHA256",
    }
    return {
        **stable,
        "subset_payload_sha256": _sha256_bytes(rfc8785.dumps(stable)),
    }


def main() -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Rebuild DynamicBench-v3, verify the frozen full report, and emit a "
            "small source-bound raw-record subset."
        )
    )
    parser.add_argument("output", type=Path, help="Canonical subset JSON path")
    parser.add_argument(
        "--full-report",
        type=Path,
        default=None,
        help="Optional stored full report to replay-match in addition to source rebuild",
    )
    selection = parser.add_mutually_exclusive_group()
    selection.add_argument(
        "--profile",
        choices=sorted(FROZEN_PROFILES),
        default=None,
        help=f"Frozen subset profile; defaults to {DEFAULT_PROFILE}",
    )
    selection.add_argument(
        "--fixture-id",
        action="append",
        dest="fixture_ids",
        help=(
            "Select exactly four unique fixtures, one per scenario class. "
            "Custom selections are emitted as CUSTOM_SELECTION_NOT_COMPARABLE."
        ),
    )
    parser.add_argument(
        "--verify-only",
        action="store_true",
        help="Compare an existing output with a fresh deterministic rebuild",
    )
    args = parser.parse_args()

    profile_id = args.profile or DEFAULT_PROFILE
    fixture_ids = args.fixture_ids or FROZEN_PROFILES[profile_id]
    if args.fixture_ids:
        profile_id = "custom"
    payload = build_subset_report(
        args.full_report,
        fixture_ids=fixture_ids,
        profile_id=profile_id,
    )
    output = args.output.expanduser().resolve()
    expected_bytes = rfc8785.dumps(payload) + b"\n"
    if args.verify_only:
        if not output.is_file() or output.read_bytes() != expected_bytes:
            raise ValueError("stored subset does not match the deterministic rebuild")
    else:
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_bytes(expected_bytes)
    fixed = payload["metrics"]["fixed_rule_baseline"]
    dynamic = payload["metrics"]["dynamic_replanning_contract"]
    print(
        f"status={payload['status']} fixtures={len(payload['fixture_manifest'])} "
        f"records={len(payload['raw_records'])} "
        f"fixed_correct={fixed['correct_terminal_disposition_count']}/"
        f"{fixed['fixed_fixture_denominator']} "
        f"dynamic_correct={dynamic['correct_terminal_disposition_count']}/"
        f"{dynamic['fixed_fixture_denominator']} "
        f"sha256={payload['subset_payload_sha256']} output={output}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
