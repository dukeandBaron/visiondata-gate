from __future__ import annotations

import json

from visiondata_gate.agent_runtime import run_agentic_demo
from visiondata_gate.cli import main
from visiondata_gate.contracts import BatchContract, BatchManifest, GateDecision
from visiondata_gate.evidence import canonical_json_bytes
from visiondata_gate.generator import generate_demo_dataset
from visiondata_gate.pipeline import run_gate
from visiondata_gate.runtime_models import RuntimeConfig
from visiondata_gate.tool_fault_evaluation import (
    build_tool_fault_evaluation_receipt,
)
from visiondata_gate.tools import run_tool


def _fixture(tmp_path):
    paths = generate_demo_dataset(tmp_path / "dataset", seed=20260824)
    manifest = BatchManifest.model_validate_json(paths["batch_manifest"].read_bytes())
    contract = BatchContract()
    baseline = run_gate(paths["batch_root"], manifest, contract)
    return paths, manifest, contract, baseline


def test_five_runtime_tool_faults_are_typed_and_fail_closed(tmp_path) -> None:
    paths, manifest, contract, baseline = _fixture(tmp_path)
    before = canonical_json_bytes(
        {"manifest": manifest, "contract": contract, "baseline": baseline}
    )

    first = build_tool_fault_evaluation_receipt(
        paths["batch_root"],
        manifest,
        contract,
        baseline_gate_result=baseline,
    )
    second = build_tool_fault_evaluation_receipt(
        paths["batch_root"],
        manifest,
        contract,
        baseline_gate_result=baseline,
    )

    assert first["status"] == "PASS_LOCAL"
    assert first["summary"] == {
        "intervention_count": 5,
        "detected_count": 5,
        "missed_count": 0,
        "detection_rate": 1.0,
        "typed_error_trace_count": 5,
        "policy_defer_count": 5,
        "source_evidence_unchanged": True,
    }
    assert {item["fault_family"] for item in first["interventions"]} == {
        "timeout",
        "stale_response",
        "malformed_payload",
        "permission_denied",
        "poisoned_tool_contract",
    }
    assert all(item["policy_decision"] == "DEFER" for item in first["interventions"])
    assert all(item["typed_error_trace"] for item in first["interventions"])
    assert canonical_json_bytes(first) == canonical_json_bytes(second)
    assert before == canonical_json_bytes(
        {"manifest": manifest, "contract": contract, "baseline": baseline}
    )


def test_tool_fault_eval_cli_writes_canonical_receipt(tmp_path, capsys) -> None:
    paths, _manifest, _contract, _baseline = _fixture(tmp_path)
    output = tmp_path / "tool-fault-receipt.json"

    exit_code = main(
        [
            "tool-fault-eval",
            "--batch-root",
            str(paths["batch_root"]),
            "--manifest",
            str(paths["batch_manifest"]),
            "--output",
            str(output),
        ]
    )
    payload = json.loads(capsys.readouterr().out)
    receipt = json.loads(output.read_text(encoding="utf-8"))

    assert exit_code == 0
    assert payload["status"] == "PASS_LOCAL"
    assert payload["detected_count"] == payload["intervention_count"] == 5
    assert payload["typed_error_trace_count"] == payload["policy_defer_count"] == 5
    assert len(payload["output_sha256"]) == 64
    assert receipt["status"] == "PASS_LOCAL"


def test_agent_runtime_uses_injected_gateway_and_policy_defer(tmp_path) -> None:
    def timeout_image_quality(*args, **kwargs):
        if args[0] == "image_quality":
            raise TimeoutError("test timeout")
        return run_tool(*args, **kwargs)

    run = run_agentic_demo(
        tmp_path / "runtime-fault",
        seed=20260825,
        config=RuntimeConfig(persist_memory=False),
        tool_runner=timeout_image_quality,
    )

    assert run.initial_result.decision is GateDecision.DEFER
    assert run.repaired_result.decision is GateDecision.DEFER
    for result in (run.initial_result, run.repaired_result):
        trace = next(item for item in result.tool_trace if item.tool == "image_quality")
        assert trace.status == "error"
        assert trace.error == "TimeoutError: tool execution failed"
        assert trace.finding_ids == []
        assert any("TOOL_ERROR" in item.reason_codes for item in result.work_orders)
    assert not (run.evidence_dir / "tool_fault_intervention_receipt.json").exists()
