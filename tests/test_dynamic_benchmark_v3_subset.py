from __future__ import annotations

import hashlib
import json
from pathlib import Path
import subprocess
import sys


REPO_ROOT = Path(__file__).resolve().parents[1]
SCRIPT = REPO_ROOT / "tools" / "run_dynamic_benchmark_v3_subset.py"
def test_subset_cli_writes_deterministic_source_bound_raw_records(
    tmp_path: Path,
) -> None:
    first = tmp_path / "subset-first.json"
    second = tmp_path / "subset-second.json"

    for output in (first, second):
        completed = subprocess.run(
            [
                sys.executable,
                str(SCRIPT),
                str(output),
            ],
            cwd=REPO_ROOT,
            capture_output=True,
            text=True,
            check=False,
        )
        assert completed.returncode == 0, completed.stderr

    assert first.read_bytes() == second.read_bytes()
    payload = json.loads(first.read_text(encoding="utf-8"))
    assert payload["schema_version"] == (
        "visiondata-gate.dynamic-benchmark-v3-repro-subset.v1"
    )
    assert payload["status"] == "PASS_LOCAL_REPRODUCIBILITY_SUBSET"
    assert payload["selection"]["profile_id"] == "balanced-smoke-a-v1"
    assert payload["selection"]["fixture_ids"] == ["C01", "F02", "I01", "N02"]
    assert payload["selection"]["scenario_count"] == 4
    assert payload["selection"]["entry_tool_counts"] == {
        "annotation_integrity": 2,
        "metadata_reconciliation": 2,
    }
    assert payload["selection"]["expected_terminal_disposition_counts"] == {
        "BLOCK": 2,
        "HOLD": 1,
        "RELEASE": 1,
    }
    assert len(payload["fixture_manifest"]) == 4
    assert len(payload["raw_records"]) == 8
    assert payload["source_full_report"]["origin"] == "BUILT_FROM_CURRENT_SOURCE"
    assert payload["source_full_report"]["stored_report_match"] == "NOT_REQUESTED"
    assert payload["source_full_report"]["fixture_count"] == 8
    assert payload["source_full_report"]["record_count"] == 16
    assert payload["protocol_parameters"]["fixed_rule_plan"] == [
        "metadata_reconciliation",
        "annotation_integrity",
        "cross_tool_conflict_adjudication",
    ]
    assert payload["protocol_parameters"]["planner_kind"] == (
        "deterministic_evidence_state_router"
    )
    assert payload["protocol_parameters"]["randomness_used"] is False
    assert payload["protocol_parameters"]["external_model_calls_allowed"] is False
    assert payload["source_code"]["supported_python"] == ">=3.12,<3.14"
    assert payload["source_code"]["uv_lock_sha256"] == hashlib.sha256(
        (REPO_ROOT / "uv.lock").read_bytes()
    ).hexdigest()
    assert payload["external_baselines"] == {
        "langgraph": "NOT_RUN",
        "react": "NOT_RUN",
    }
    assert payload["metrics"]["fixed_rule_baseline"] == {
        "correct_terminal_disposition_count": 2,
        "fixed_fixture_denominator": 4,
        "tool_failure_recovery_eligible_count": 1,
        "tool_failure_recovery_success_count": 0,
        "total_tool_call_count": 12,
        "unnecessary_tool_call_count": 7,
        "unsafe_release_count": 0,
    }
    assert payload["metrics"]["dynamic_replanning_contract"] == {
        "correct_terminal_disposition_count": 4,
        "fixed_fixture_denominator": 4,
        "tool_failure_recovery_eligible_count": 1,
        "tool_failure_recovery_success_count": 1,
        "total_tool_call_count": 7,
        "unnecessary_tool_call_count": 0,
        "unsafe_release_count": 0,
    }
    assert payload["actual_model_call_count"] == 0
    assert payload["model_temperature"] == "NOT_APPLICABLE"
    assert payload["random_seed"] == "NOT_APPLICABLE"
    assert payload["external_agent_baseline_status"] == "NOT_RUN"
    assert payload["industrial_effectiveness_status"] == "NOT_EVALUATED"
    assert payload["production_release_allowed"] is False
    assert "generated_at" not in payload
    fixtures = {item["fixture_id"]: item for item in payload["fixture_manifest"]}
    for record in payload["raw_records"]:
        if record["strategy"] == "dynamic_replanning_contract":
            assert record["executed_tools"] == fixtures[record["fixture_id"]][
                "expected_dynamic_path"
            ]
        else:
            assert record["executed_tools"] == payload["protocol_parameters"][
                "fixed_rule_plan"
            ]

    verified = subprocess.run(
        [sys.executable, str(SCRIPT), str(first), "--verify-only"],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    assert verified.returncode == 0, verified.stderr

    first.write_text("{}\n", encoding="utf-8")
    rejected = subprocess.run(
        [sys.executable, str(SCRIPT), str(first), "--verify-only"],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    assert rejected.returncode != 0


def test_custom_subset_is_explicitly_non_comparable(tmp_path: Path) -> None:
    output = tmp_path / "custom.json"
    completed = subprocess.run(
        [
            sys.executable,
            str(SCRIPT),
            str(output),
            "--fixture-id",
            "C02",
            "--fixture-id",
            "F01",
            "--fixture-id",
            "I02",
            "--fixture-id",
            "N01",
        ],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    assert completed.returncode == 0, completed.stderr
    payload = json.loads(output.read_text(encoding="utf-8"))
    assert payload["status"] == "CUSTOM_SELECTION_NOT_COMPARABLE"
    assert payload["selection"]["profile_id"] == "custom"
    assert payload["production_release_allowed"] is False


def test_frozen_profiles_are_disjoint_and_cover_the_full_fixture_set(
    tmp_path: Path,
) -> None:
    fixture_sets: list[set[str]] = []
    for profile in ("balanced-smoke-a-v1", "balanced-smoke-b-v1"):
        output = tmp_path / f"{profile}.json"
        completed = subprocess.run(
            [sys.executable, str(SCRIPT), str(output), "--profile", profile],
            cwd=REPO_ROOT,
            capture_output=True,
            text=True,
            check=False,
        )
        assert completed.returncode == 0, completed.stderr
        payload = json.loads(output.read_text(encoding="utf-8"))
        assert payload["status"] == "PASS_LOCAL_REPRODUCIBILITY_SUBSET"
        fixture_sets.append(set(payload["selection"]["fixture_ids"]))
    assert fixture_sets[0].isdisjoint(fixture_sets[1])
    assert fixture_sets[0] | fixture_sets[1] == {
        "C01",
        "C02",
        "F01",
        "F02",
        "I01",
        "I02",
        "N01",
        "N02",
    }
