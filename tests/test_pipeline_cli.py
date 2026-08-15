from __future__ import annotations

import json
from pathlib import Path

from visiondata_gate.cli import main
from visiondata_gate.contracts import GateDecision
from visiondata_gate.pipeline import run_full_demo


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
