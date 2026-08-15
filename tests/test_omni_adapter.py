from __future__ import annotations

import json
from pathlib import Path
import zipfile

from PIL import Image

from visiondata_gate.cli import main
from visiondata_gate.omni_adapter import (
    run_omni_readonly_gate,
    run_omni_readonly_smoke,
)
from visiondata_gate.tools import validate_tool_contract_trace


def _write_minimal_metadata(path: Path, *, category: str, total: int) -> None:
    headers = ["数据集名称", "样本总数", "good(train)", "good(test)", "NG(test)"]
    values = [category, total, 1, 1, max(total - 2, 0)]

    def cell(column: str, row: int, value: str | int) -> str:
        if isinstance(value, int):
            return f'<c r="{column}{row}"><v>{value}</v></c>'
        return f'<c r="{column}{row}" t="inlineStr"><is><t>{value}</t></is></c>'

    columns = ["A", "B", "C", "D", "E"]
    sheet = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">'
        "<sheetData>"
        '<row r="1">'
        + "".join(
            cell(column, 1, value)
            for column, value in zip(columns, headers, strict=True)
        )
        + '</row><row r="2">'
        + "".join(
            cell(column, 2, value)
            for column, value in zip(columns, values, strict=True)
        )
        + "</row></sheetData></worksheet>"
    )
    path.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(path, "w") as bundle:
        bundle.writestr("xl/worksheets/sheet1.xml", sheet)


def _build_fixture(
    root: Path,
    *,
    metadata_total: int = 3,
    mixed_resolution: bool = False,
) -> tuple[Path, str]:
    release = root / "private-release"
    category = "secret-widget"
    image = Image.new("RGB", (32, 32), color=(90, 120, 150))
    mask = Image.new("L", (32, 32), color=0)
    test_good = (
        Image.new("RGB", (48, 32), color=(90, 120, 150)) if mixed_resolution else image
    )
    for relative, payload in (
        (f"{category}/train/good/train.png", image),
        (f"{category}/test/good/test-good.png", test_good),
        (f"{category}/test/scratch/test-bad.png", image),
        (f"{category}/ground_truth/scratch/test-bad.png", mask),
    ):
        destination = release / relative
        destination.parent.mkdir(parents=True, exist_ok=True)
        payload.save(destination)
    _write_minimal_metadata(
        release / "official.xlsx",
        category=category,
        total=metadata_total,
    )
    return release, category


def test_readonly_smoke_is_redacted_and_repeatable(tmp_path: Path) -> None:
    release, category = _build_fixture(tmp_path / "input")
    source_snapshot = sorted(
        (path.relative_to(release).as_posix(), path.stat().st_size)
        for path in release.rglob("*")
        if path.is_file()
    )
    first = run_omni_readonly_smoke(
        release,
        tmp_path / "evidence" / "first.json",
        source_archive_sha256="a" * 64,
        per_bucket=1,
        seed=7,
        full_decode=True,
    )
    second = run_omni_readonly_smoke(
        release,
        tmp_path / "evidence" / "second.json",
        source_archive_sha256="a" * 64,
        per_bucket=1,
        seed=7,
        full_decode=True,
    )

    assert first.summary_sha256 == second.summary_sha256
    assert first.summary["scope"]["selected_image_count"] == 3
    assert first.summary["dataset_structure"]["training_normal_only"] is True
    assert first.summary["dataset_structure"]["missing_mask_count"] == 0
    assert first.summary["release_decision"] == "DEFER"
    serialized = first.summary_path.read_text(encoding="utf-8")
    assert str(release) not in serialized
    assert category not in serialized
    assert ".png" not in serialized
    assert (
        sorted(
            (path.relative_to(release).as_posix(), path.stat().st_size)
            for path in release.rglob("*")
            if path.is_file()
        )
        == source_snapshot
    )


def test_metadata_drift_is_explicit_and_fail_closed(tmp_path: Path) -> None:
    release, _ = _build_fixture(tmp_path / "input", metadata_total=2)
    run = run_omni_readonly_smoke(
        release,
        tmp_path / "evidence" / "drift.json",
        source_archive_sha256="b" * 64,
        per_bucket=1,
    )

    assert run.summary["dataset_structure"]["metadata_count_deltas"]["total"] == 1
    assert "METADATA_COUNT_DRIFT" in run.summary["blockers"]
    assert (
        run.summary["tool_execution"]["finding_code_counts"]["METADATA_COUNT_DRIFT"]
        == 1
    )
    assert run.summary["release_decision"] == "DEFER"


def test_cli_writes_compact_real_data_receipt(tmp_path: Path, capsys) -> None:
    release, _ = _build_fixture(tmp_path / "input")
    output = tmp_path / "evidence" / "cli.json"
    assert (
        main(
            [
                "omni-smoke",
                "--root",
                str(release),
                "--source-archive-sha256",
                "c" * 64,
                "--output",
                str(output),
                "--per-bucket",
                "1",
            ]
        )
        == 0
    )
    printed = json.loads(capsys.readouterr().out)
    assert printed["completion_state"] == "REAL_DATA_SMOKE_COMPLETED"
    assert printed["release_decision"] == "DEFER"
    assert printed["selected_image_count"] == 3
    assert output.is_file()


def test_real_data_enters_council_policy_and_work_order_chain(tmp_path: Path) -> None:
    release, category = _build_fixture(tmp_path / "input", metadata_total=2)
    run = run_omni_readonly_gate(
        release,
        tmp_path / "evidence" / "gate",
        source_archive_sha256="d" * 64,
        per_bucket=1,
        seed=11,
    )

    result = run.gate_result
    assert result.run_id.startswith("omni-gate-")
    assert len(result.tool_trace) == 5
    assert {trace.tool for trace in result.tool_trace} == {
        "image_quality",
        "duplicate_leakage",
        "annotation_integrity",
        "coverage_matrix",
        "governance_audit",
    }
    assert all(
        trace.adapter == "external-readonly-omni-v1" for trace in result.tool_trace
    )
    assert all(
        validate_tool_contract_trace(trace, include_optional=True) is None
        for trace in result.tool_trace
    )
    assert len(result.council_trace.independent_opinions) > 1
    assert any(finding.code == "METADATA_COUNT_DRIFT" for finding in result.findings)
    assert any(
        "METADATA_COUNT_DRIFT" in order.reason_codes for order in result.work_orders
    )
    assert run.leader_plan_path.is_file()
    plan = json.loads(run.leader_plan_path.read_text(encoding="utf-8"))
    assert plan["replan_count"] == 1
    assert "metadata-reconciliation" in plan["branch_types"]
    assert result.decision.value != "PASS"
    serialized = run.gate_result_path.read_text(encoding="utf-8")
    assert str(release) not in serialized
    assert category not in serialized
    assert ".png" not in serialized


def test_leader_dynamically_adds_resolution_and_conflict_workers(
    tmp_path: Path,
) -> None:
    release, category = _build_fixture(
        tmp_path / "input",
        metadata_total=2,
        mixed_resolution=True,
    )
    run = run_omni_readonly_gate(
        release,
        tmp_path / "evidence" / "gate",
        source_archive_sha256="f" * 64,
        per_bucket=1,
        seed=17,
    )

    plan = json.loads(run.leader_plan_path.read_text(encoding="utf-8"))
    assert plan["mode"] == "evidence_triggered_replan"
    assert plan["dynamic_task_count"] >= 2
    assert {
        "metadata-reconciliation",
        "native-resolution-reconciliation",
    } <= set(plan["branch_types"])
    assert all(
        task["dispatch_basis"] == "intermediate_evidence"
        and task["status"] == "completed"
        and len(task["result_sha256"]) == 64
        for task in plan["dynamic_tasks"]
    )
    assert any(
        order.action == "INVESTIGATE" and "METADATA_COUNT_DRIFT" in order.reason_codes
        for order in run.gate_result.work_orders
    )
    serialized = run.leader_plan_path.read_text(encoding="utf-8")
    assert str(release) not in serialized
    assert category not in serialized
    assert ".png" not in serialized


def test_cli_omni_gate_reports_real_gate_result(tmp_path: Path, capsys) -> None:
    release, _ = _build_fixture(tmp_path / "input", metadata_total=2)
    output = tmp_path / "evidence" / "gate"
    assert (
        main(
            [
                "omni-gate",
                "--root",
                str(release),
                "--source-archive-sha256",
                "e" * 64,
                "--output",
                str(output),
                "--per-bucket",
                "1",
            ]
        )
        == 0
    )
    printed = json.loads(capsys.readouterr().out)
    assert printed["completion_state"] == "REAL_DATA_GATE_COMPLETED"
    assert printed["decision"] != "PASS"
    assert Path(printed["gate_result"]).is_file()
    assert Path(printed["receipt"]).is_file()
