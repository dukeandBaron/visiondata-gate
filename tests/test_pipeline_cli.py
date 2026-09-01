from __future__ import annotations

import json
from pathlib import Path

import pytest

import visiondata_gate.cli as cli_module
from visiondata_gate.cli import main
from visiondata_gate.contracts import GateDecision
from visiondata_gate.demo_fixtures import build_fixture_industrial_incident_request
from visiondata_gate.evidence import write_canonical_json
from visiondata_gate.geometry_consistency import GeometryThresholds
from visiondata_gate.industrial_incident import (
    IndustrialGateContext,
    parse_industrial_incident_case_json,
)
from visiondata_gate.pipeline import run_full_demo
from visiondata_gate.runtime_models import ModelBackendKind, ScenarioProfile


def test_lazy_cli_parser_constants_match_typed_runtime_contracts() -> None:
    assert cli_module._MODEL_BACKEND_CHOICES == tuple(
        item.value for item in ModelBackendKind
    )
    assert cli_module._SCENARIO_CHOICES == tuple(item.value for item in ScenarioProfile)
    assert cli_module._DEFAULT_MODEL_BACKEND == ModelBackendKind.DETERMINISTIC.value
    assert cli_module._DEFAULT_SCENARIO == ScenarioProfile.GENERIC.value
    assert (
        cli_module._DEFAULT_MAX_REPROJECTION_ERROR_PX
        == GeometryThresholds().max_reprojection_error_px
    )


def test_full_demo_blocks_dirty_batch_and_passes_repaired_batch(tmp_path: Path) -> None:
    run = run_full_demo(tmp_path / "demo", seed=20260809)

    assert run.initial_result.decision is not GateDecision.PASS
    assert run.repaired_result.decision is GateDecision.PASS
    assert run.evaluation.precision == 1.0
    assert run.evaluation.recall == 1.0
    assert run.evaluation.f1 == 1.0
    assert run.evaluation.critical_bad_release_rate == 0.0
    assert run.evaluation.post_repair_correct_pass is True
    assert run.summary_path.is_file()


def test_cli_demo_writes_machine_readable_summary(tmp_path: Path, capsys) -> None:
    output = tmp_path / "cli-demo"
    assert main(["demo", "--output", str(output), "--seed", "77"]) == 0

    printed = json.loads(capsys.readouterr().out)
    assert printed["repaired_decision"] == "PASS"
    assert printed["post_repair_correct_pass"] is True
    assert Path(printed["summary"]).is_file()


@pytest.mark.parametrize(
    ("command", "expected_status"),
    [
        ("network-resilience-eval", "PASS_LOCAL"),
        ("prompt-injection-eval", "PASS_LOCAL_FIXED_ATTACK_SET"),
        ("backend-contract-eval", "PASS_LOCAL_CONTRACTS_ONLY"),
    ],
)
def test_cli_runtime_hardening_evaluations_write_receipts(
    tmp_path: Path, capsys, command: str, expected_status: str
) -> None:
    output = tmp_path / f"{command}.json"
    assert main([command, "--output", str(output)]) == 0
    printed = json.loads(capsys.readouterr().out)
    assert printed["status"] == expected_status
    assert output.is_file()
    assert len(printed["output_sha256"]) == 64


def test_cli_incident_evaluate_runs_local_read_only_four_source_contract(
    tmp_path: Path, capsys
) -> None:
    request_path = tmp_path / "incident-request.json"
    context_path = tmp_path / "gate-context.json"
    output_path = tmp_path / "incident-case.json"
    request = build_fixture_industrial_incident_request()
    context = IndustrialGateContext(
        task_id="task_cli_incident_fixture",
        gate_final_decision="PASS",
        task_evidence_sha256="1" * 64,
        industrial_delivery_sha256="2" * 64,
        source_profile_sha256="3" * 64,
        source_authorization_event_sha256="4" * 64,
        source_kind="synthetic_demo",
        source_authorization_status="NOT_APPLICABLE",
        dynamic_response_count=0,
        open_work_order_count=0,
        remediation_plan_ids=[],
        model_call_count=0,
    )
    write_canonical_json(request_path, request)
    write_canonical_json(context_path, context)

    assert (
        main(
            [
                "incident-evaluate",
                "--request",
                str(request_path),
                "--gate-context",
                str(context_path),
                "--output",
                str(output_path),
            ]
        )
        == 0
    )

    printed = json.loads(capsys.readouterr().out)
    case = parse_industrial_incident_case_json(output_path.read_bytes())
    assert printed["execution_status"] == "COMPLETED_LOCAL_READ_ONLY_EVALUATION"
    assert printed["case_id"] == case.case_id
    assert printed["root_cause_status"] == "NOT_ESTABLISHED"
    assert printed["production_release_allowed"] is False
    assert case.request.schema_version.endswith(".v3")
    assert case.request.runtime_profile.model_profile_id == "deterministic-off"
