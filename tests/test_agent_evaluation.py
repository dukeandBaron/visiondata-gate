from __future__ import annotations

import json

import pytest

from visiondata_gate.agent_evaluation import build_agent_evaluation_receipt
from visiondata_gate.agent_runtime import run_agentic_demo
from visiondata_gate.cli import main
from visiondata_gate.evidence import canonical_json_bytes
from visiondata_gate.runtime_models import RuntimeConfig


@pytest.fixture(scope="module")
def evaluated_run(tmp_path_factory):
    root = tmp_path_factory.mktemp("agent-evaluation")
    return run_agentic_demo(
        root / "run",
        seed=20260823,
        config=RuntimeConfig(persist_memory=False),
        memory_path=root / "memory.json",
    )


def test_fault_interventions_are_detected_without_mutating_source(
    evaluated_run,
) -> None:
    source_bundle = {
        "trace": evaluated_run.runtime_trace,
        "initial": evaluated_run.initial_result,
        "repaired": evaluated_run.repaired_result,
    }
    before = canonical_json_bytes(source_bundle)

    first = build_agent_evaluation_receipt(
        evaluated_run.runtime_trace,
        evaluated_run.initial_result,
        evaluated_run.repaired_result,
    )
    second = build_agent_evaluation_receipt(
        evaluated_run.runtime_trace,
        evaluated_run.initial_result,
        evaluated_run.repaired_result,
    )

    assert canonical_json_bytes(source_bundle) == before
    assert canonical_json_bytes(first) == canonical_json_bytes(second)
    assert first["status"] == "PASS_LOCAL"
    assert first["baseline"]["audit_status"] == "PASS"
    assert first["baseline"]["false_positive"] is False
    assert first["summary"] == {
        "intervention_count": 11,
        "detected_count": 11,
        "missed_count": 0,
        "detection_rate": 1.0,
        "baseline_false_positive_count": 0,
        "valid_variant_control_count": 1,
        "valid_variant_false_positive_count": 0,
    }
    assert all(case["status"] == "DETECTED" for case in first["interventions"])
    assert all(
        case["expected_failed_check"] in case["newly_failed_checks"]
        for case in first["interventions"]
    )
    assert all(
        case["clean_input_sha256"] != case["mutated_input_sha256"]
        for case in first["interventions"]
    )
    assert first["valid_trajectory_controls"][0]["status"] == "PASS"
    assert first["valid_trajectory_controls"][0]["newly_failed_checks"] == []
    assert first["method"]["reference_trajectory_required"] is False
    assert first["method"]["llm_judge_used"] is False
    assert first["claims"]["agent_capability_measured"] is False


def test_agent_demo_keeps_intervention_evaluation_out_of_runtime(evaluated_run) -> None:
    receipt_path = evaluated_run.evidence_dir / "agent_eval_intervention_receipt.json"
    summary = json.loads(evaluated_run.summary_path.read_text(encoding="utf-8"))
    proof = json.loads(
        evaluated_run.evidence_dir.joinpath("proof_index.json").read_text(
            encoding="utf-8"
        )
    )

    assert not receipt_path.exists()
    assert not evaluated_run.evidence_dir.joinpath(
        "tool_fault_intervention_receipt.json"
    ).exists()
    assert "agent_eval_intervention_receipt" not in summary["runtime"]
    assert "tool_fault_intervention_receipt" not in summary["runtime"]
    assert (
        "agent_eval_intervention_receipt.json"
        not in summary["runtime"]["proof_artifact_hashes"]
    )
    assert not any(
        item["role"]
        in {
            "agent_eval_intervention_receipt",
            "tool_fault_intervention_receipt",
        }
        for item in proof["artifact_index"]
    )
    assert not any(
        item["claim_id"]
        in {
            "agent_evaluator_sensitivity",
            "runtime_tool_fault_fail_closed",
        }
        for item in proof["claims"]
    )
    delivery = next(
        task
        for task in evaluated_run.runtime_trace.tasks
        if task.task_id == "system.delivery"
    )
    assert "evidence/agent_eval_intervention_receipt.json" not in delivery.output_refs
    assert "evidence/tool_fault_intervention_receipt.json" not in delivery.output_refs


def test_agent_eval_cli_rescores_saved_artifacts(
    evaluated_run, tmp_path, capsys
) -> None:
    output = tmp_path / "agent-eval.json"
    exit_code = main(
        [
            "agent-eval",
            "--runtime-trace",
            str(evaluated_run.runtime_trace_path),
            "--initial-result",
            str(evaluated_run.evidence_dir / "initial" / "gate_result.json"),
            "--repaired-result",
            str(evaluated_run.evidence_dir / "repaired" / "gate_result.json"),
            "--output",
            str(output),
        ]
    )
    payload = json.loads(capsys.readouterr().out)
    receipt = json.loads(output.read_text(encoding="utf-8"))

    assert exit_code == 0
    assert payload["status"] == "PASS_LOCAL"
    assert payload["detected_count"] == payload["intervention_count"] == 11
    assert payload["valid_variant_false_positive_count"] == 0
    assert len(payload["output_sha256"]) == 64
    assert receipt["status"] == "PASS_LOCAL"
