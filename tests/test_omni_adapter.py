from __future__ import annotations

import json
from pathlib import Path
import zipfile

from PIL import Image
import pytest

import visiondata_gate.omni_adapter as omni_adapter
from visiondata_gate.cli import main
from visiondata_gate.industrial_skills import (
    IndustrialSkillFailure,
    IndustrialSkillInvocation,
    IndustrialSkillOutcome,
    IndustrialSkillReceipt,
    MetadataCountDriftSkill,
    verify_industrial_skill_receipt,
)
from visiondata_gate.omni_adapter import (
    run_omni_readonly_gate,
    run_omni_readonly_smoke,
)
from visiondata_gate.tools import validate_tool_contract_trace


RULEPACK = Path(__file__).resolve().parents[1] / "rulepacks" / "industrial-v1.json"


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


@pytest.mark.parametrize("blocked_name", ["official.xlsx", "test", "ground_truth"])
def test_source_reparse_points_fail_closed_before_evidence_is_written(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    blocked_name: str,
) -> None:
    release, _ = _build_fixture(tmp_path / "input")
    real_check = omni_adapter._is_reparse_path

    def simulated_reparse(path: Path) -> bool:
        return path.name == blocked_name or real_check(path)

    monkeypatch.setattr(omni_adapter, "_is_reparse_path", simulated_reparse)
    output = tmp_path / "evidence" / "blocked.json"

    with pytest.raises(
        omni_adapter.OmniSourceBoundaryError,
        match="links or reparse points",
    ):
        run_omni_readonly_smoke(
            release,
            output,
            source_archive_sha256="9" * 64,
            per_bucket=1,
        )

    assert not output.exists()


def test_xlsx_member_budget_rejects_archive_fanout(tmp_path: Path) -> None:
    metadata = tmp_path / "official.xlsx"
    _write_minimal_metadata(metadata, category="widget", total=3)
    with zipfile.ZipFile(metadata, "a") as bundle:
        for index in range(omni_adapter._XLSX_MAX_ZIP_MEMBERS):
            bundle.writestr(f"padding/{index:04d}.txt", b"")

    with pytest.raises(ValueError, match="member budget exceeded"):
        omni_adapter._load_official_counts(metadata)


def test_xlsx_column_reference_budget_rejects_sparse_allocation_attack(
    tmp_path: Path,
) -> None:
    metadata = tmp_path / "official.xlsx"
    sheet = (
        '<?xml version="1.0" encoding="UTF-8"?>'
        '<worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">'
        '<sheetData><row r="1"><c r="ZZZ1" t="inlineStr"><is><t>'
        "数据集名称</t></is></c></row></sheetData></worksheet>"
    )
    with zipfile.ZipFile(metadata, "w") as bundle:
        bundle.writestr("xl/worksheets/sheet1.xml", sheet)

    with pytest.raises(ValueError, match="column budget exceeded"):
        omni_adapter._load_official_counts(metadata)


def test_xlsx_utf16_doctype_is_rejected_before_xml_parse(tmp_path: Path) -> None:
    metadata = tmp_path / "official.xlsx"
    headers = ["&dataset_header;", "样本总数", "good(train)", "good(test)", "NG(test)"]
    header_cells = "".join(
        f'<c r="{column}1" t="inlineStr"><is><t>{value}</t></is></c>'
        for column, value in zip(["A", "B", "C", "D", "E"], headers, strict=True)
    )
    sheet = (
        '<?xml version="1.0" encoding="UTF-16"?>'
        '<!DOCTYPE worksheet [<!ENTITY dataset_header "数据集名称">]>'
        '<worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">'
        f'<sheetData><row r="1">{header_cells}</row>'
        '<row r="2"><c r="A2" t="inlineStr"><is><t>widget</t></is></c>'
        '<c r="B2"><v>3</v></c><c r="C2"><v>1</v></c>'
        '<c r="D2"><v>1</v></c><c r="E2"><v>1</v></c>'
        "</row></sheetData></worksheet>"
    ).encode("utf-16")
    with zipfile.ZipFile(metadata, "w", compression=zipfile.ZIP_DEFLATED) as bundle:
        bundle.writestr("xl/worksheets/sheet1.xml", sheet)

    with pytest.raises(
        ValueError,
        match="XML (?:must use UTF-8|declarations are not allowed)",
    ):
        omni_adapter._load_official_counts(metadata)


def test_xlsx_shared_string_rich_text_remains_supported(tmp_path: Path) -> None:
    metadata = tmp_path / "official.xlsx"
    strings = [
        "数据集名称",
        "样本总数",
        "good(train)",
        "good(test)",
        "NG(test)",
        "widget",
    ]
    shared = (
        '<?xml version="1.0" encoding="UTF-8"?>'
        '<sst xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">'
        + "".join(
            f"<si><r><t>{value[:1]}</t></r><r><t>{value[1:]}</t></r></si>"
            for value in strings
        )
        + "</sst>"
    )
    header = "".join(
        f'<c r="{column}1" t="s"><v>{index}</v></c>'
        for index, column in enumerate(["A", "B", "C", "D", "E"])
    )
    values = (
        '<c r="A2" t="s"><v>5</v></c>'
        '<c r="B2"><v>3</v></c><c r="C2"><v>1</v></c>'
        '<c r="D2"><v>1</v></c><c r="E2"><v>1</v></c>'
    )
    sheet = (
        '<?xml version="1.0" encoding="UTF-8"?>'
        '<worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">'
        f'<sheetData><row r="1">{header}</row><row r="2">{values}</row></sheetData>'
        "</worksheet>"
    )
    with zipfile.ZipFile(metadata, "w", compression=zipfile.ZIP_DEFLATED) as bundle:
        bundle.writestr("xl/sharedStrings.xml", shared)
        bundle.writestr("xl/worksheets/sheet1.xml", sheet)

    assert omni_adapter._load_official_counts(metadata) == {
        "widget": {
            "total": 3,
            "train_good": 1,
            "test_good": 1,
            "test_anomaly": 1,
        }
    }


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
        rulepack_path=RULEPACK,
    )

    result = run.gate_result
    assert result.run_id.startswith("omni-gate-")
    plan = json.loads(run.leader_plan_path.read_text(encoding="utf-8"))
    assert len(result.tool_trace) == 5 + plan["dynamic_task_count"]
    assert {trace.tool for trace in result.tool_trace[:5]} == {
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
    assert [trace.sequence for trace in result.tool_trace] == list(
        range(1, len(result.tool_trace) + 1)
    )
    assert all(len(trace.input_sha256) == 64 for trace in result.tool_trace[5:])
    assert all(len(trace.result_sha256) == 64 for trace in result.tool_trace[5:])
    assert len(result.council_trace.independent_opinions) > 1
    assert any(finding.code == "METADATA_COUNT_DRIFT" for finding in result.findings)
    assert any(
        "METADATA_COUNT_DRIFT" in order.reason_codes for order in result.work_orders
    )
    assert run.leader_plan_path.is_file()
    assert plan["replan_count"] == 1
    assert "metadata-reconciliation" in plan["branch_types"]
    assert plan["rule_pack_runtime_status"] == "ACTIVATED"
    assert plan["rule_pack_binding"]["pack_id"] == ("visiondata-gate.industrial-v1")
    assert all(
        task["trigger_rule_id"]
        in {
            "metadata-count-drift",
            "native-resolution-groups",
            "cross-tool-action-conflict",
        }
        for task in plan["dynamic_tasks"]
    )
    assert all(
        order.replacement_requirements.get("rule_pack_binding_sha256")
        == plan["rule_pack_binding"]["binding_sha256"]
        for order in result.work_orders
        if "METADATA_COUNT_DRIFT" in order.reason_codes
    )
    assert result.decision.value != "PASS"
    serialized = run.gate_result_path.read_text(encoding="utf-8")
    assert str(release) not in serialized
    assert category not in serialized
    assert ".png" not in serialized


def test_rulepack_activation_rejects_stale_copied_binding_before_dataset_scan(
    tmp_path: Path, monkeypatch
) -> None:
    valid = omni_adapter.build_rule_pack_runtime_binding(RULEPACK)
    stale = valid.model_copy(
        update={
            "action_by_finding_code": {
                **valid.action_by_finding_code,
                "LOW_SHARPNESS": "INVESTIGATE",
            }
        }
    )
    monkeypatch.setattr(
        omni_adapter,
        "build_rule_pack_runtime_binding",
        lambda _path: stale,
    )

    def fail_if_dataset_scan_starts(_root: str | Path) -> Path:
        pytest.fail("dataset scan started before Rule Pack integrity validation")

    monkeypatch.setattr(
        omni_adapter,
        "_discover_dataset_root",
        fail_if_dataset_scan_starts,
    )

    with pytest.raises(ValueError, match="integrity validation"):
        run_omni_readonly_gate(
            tmp_path / "dataset-must-not-be-read",
            tmp_path / "output-must-not-exist",
            source_archive_sha256="e" * 64,
            per_bucket=1,
            rulepack_path=RULEPACK,
        )

    assert not (tmp_path / "output-must-not-exist").exists()


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
    metadata_task = next(
        task
        for task in plan["dynamic_tasks"]
        if task["task_id"] == "followup.metadata-reconciliation"
    )
    resolution_task = next(
        task
        for task in plan["dynamic_tasks"]
        if task["task_id"] == "followup.native-resolution-reconciliation"
    )
    assert metadata_task["outputs"]["independent_rescan_matches_initial"] is True
    assert metadata_task["outputs"]["tree_image_count"] == 3
    assert metadata_task["outputs"]["metadata_image_count"] == 2
    assert metadata_task["outputs"]["observed_delta_images"] == 1
    assert metadata_task["outputs"]["skill_id"] == (
        "visiondata-gate.metadata-count-drift"
    )
    assert metadata_task["outputs"]["skill_version"] == "1.0.0"
    assert metadata_task["outputs"]["skill_reported_delta_images"] == 1
    assert metadata_task["outputs"]["skill_receipt_verified"] is True
    assert metadata_task["outputs"]["skill_receipt_verification_status"] == ("VERIFIED")
    assert metadata_task["outputs"]["skill_observation_verified"] is True
    assert metadata_task["outputs"]["skill_integration_status"] == "ACCEPTED"
    skill_receipt = IndustrialSkillReceipt.model_validate(
        metadata_task["outputs"]["skill_receipt"]
    )
    assert verify_industrial_skill_receipt(skill_receipt) is True
    assert (
        skill_receipt.receipt_sha256 == metadata_task["outputs"]["skill_receipt_sha256"]
    )
    assert (
        f"industrial-skill-receipt:{skill_receipt.receipt_sha256}"
        in metadata_task["new_evidence_refs"]
    )
    assert resolution_task["outputs"]["rechecked_image_count"] == 3
    assert resolution_task["outputs"]["group_policy"] == (
        "measure_per_native_size_then_reconcile"
    )
    followup_traces = run.gate_result.tool_trace[5:]
    assert len(followup_traces) == plan["dynamic_task_count"]
    assert {
        (trace.sequence, trace.tool, trace.input_sha256, trace.result_sha256)
        for trace in followup_traces
    } == {
        (
            binding["sequence"],
            binding["tool"],
            binding["input_sha256"],
            binding["result_sha256"],
        )
        for binding in plan["followup_trace_bindings"]
    }
    assert any(
        order.action == "INVESTIGATE" and "METADATA_COUNT_DRIFT" in order.reason_codes
        for order in run.gate_result.work_orders
    )
    serialized = run.leader_plan_path.read_text(encoding="utf-8")
    assert str(release) not in serialized
    assert category not in serialized
    assert ".png" not in serialized


def test_semantic_dispatch_hash_is_stable_across_operational_timing(
    tmp_path: Path,
) -> None:
    release, _ = _build_fixture(
        tmp_path / "input", metadata_total=2, mixed_resolution=True
    )
    first = run_omni_readonly_gate(
        release,
        tmp_path / "evidence" / "first",
        source_archive_sha256="8" * 64,
        per_bucket=1,
        seed=23,
    )
    second = run_omni_readonly_gate(
        release,
        tmp_path / "evidence" / "second",
        source_archive_sha256="8" * 64,
        per_bucket=1,
        seed=23,
    )

    first_plan = json.loads(first.leader_plan_path.read_text(encoding="utf-8"))
    second_plan = json.loads(second.leader_plan_path.read_text(encoding="utf-8"))
    assert (
        first_plan["dispatch_plan_sha256"]
        == first_plan["semantic_dispatch_plan_sha256"]
    )
    assert (
        first_plan["semantic_dispatch_plan_sha256"]
        == second_plan["semantic_dispatch_plan_sha256"]
    )
    assert first.gate_result.input_sha256 == second.gate_result.input_sha256
    assert first_plan["hash_contract"]["semantic_hash_excludes"] == ["duration_ms"]
    assert len(first_plan["operational_dispatch_plan_sha256"]) == 64


def test_followup_budget_exhaustion_emits_skipped_trace_and_forces_defer(
    tmp_path: Path,
) -> None:
    release, _ = _build_fixture(
        tmp_path / "input", metadata_total=2, mixed_resolution=True
    )
    run = run_omni_readonly_gate(
        release,
        tmp_path / "evidence" / "gate",
        source_archive_sha256="9" * 64,
        per_bucket=1,
        seed=29,
        followup_tool_budget=0,
    )

    plan = json.loads(run.leader_plan_path.read_text(encoding="utf-8"))
    assert plan["followup_budget"]["awarded_count"] == 0
    assert plan["followup_budget"]["budget_exhausted_count"] >= 2
    assert all(task["status"] == "budget_exhausted" for task in plan["dynamic_tasks"])
    assert all(trace.status == "skipped" for trace in run.gate_result.tool_trace[5:])
    assert any(
        finding.code == "FOLLOWUP_BUDGET_EXHAUSTED"
        for finding in run.gate_result.findings
    )
    assert run.gate_result.decision.value == "DEFER"


def test_followup_worker_failure_emits_error_trace_and_forces_defer(
    tmp_path: Path, monkeypatch
) -> None:
    release, _ = _build_fixture(tmp_path / "input", metadata_total=2)
    real_load = omni_adapter._load_official_counts
    call_count = 0

    def fail_metadata_followup(path: Path) -> dict[str, dict[str, int]]:
        nonlocal call_count
        call_count += 1
        if call_count == 2:
            raise RuntimeError("injected follow-up failure")
        return real_load(path)

    monkeypatch.setattr(omni_adapter, "_load_official_counts", fail_metadata_followup)
    run = run_omni_readonly_gate(
        release,
        tmp_path / "evidence" / "gate",
        source_archive_sha256="a" * 64,
        per_bucket=1,
        seed=31,
    )

    plan = json.loads(run.leader_plan_path.read_text(encoding="utf-8"))
    metadata_task = next(
        task
        for task in plan["dynamic_tasks"]
        if task["task_id"] == "followup.metadata-reconciliation"
    )
    assert metadata_task["status"] == "failed"
    assert any(trace.status == "error" for trace in run.gate_result.tool_trace[5:])
    assert any(
        finding.code == "FOLLOWUP_TOOL_ERROR" for finding in run.gate_result.findings
    )
    assert run.gate_result.decision.value == "DEFER"


def test_metadata_skill_receipt_verification_failure_fails_worker_closed(
    tmp_path: Path, monkeypatch
) -> None:
    release, _ = _build_fixture(tmp_path / "input", metadata_total=2)
    monkeypatch.setattr(
        omni_adapter,
        "verify_industrial_skill_receipt",
        lambda _receipt: False,
    )

    run = run_omni_readonly_gate(
        release,
        tmp_path / "evidence" / "gate",
        source_archive_sha256="b" * 64,
        per_bucket=1,
        seed=37,
    )

    plan = json.loads(run.leader_plan_path.read_text(encoding="utf-8"))
    task = next(
        item
        for item in plan["dynamic_tasks"]
        if item["task_id"] == "followup.metadata-reconciliation"
    )
    assert task["status"] == "failed"
    assert task["outputs"]["skill_receipt_verified"] is False
    assert task["outputs"]["skill_receipt_verification_status"] == "FAILED"
    assert task["outputs"]["skill_integration_status"] == "FAIL_CLOSED"
    assert task["outputs"]["skill_failure_reason"] == (
        "SKILL_RECEIPT_VERIFICATION_FAILED"
    )
    assert len(task["outputs"]["skill_receipt_sha256"]) == 64
    trace = next(
        item
        for item in run.gate_result.tool_trace
        if item.parameters.get("followup_task_id") == "followup.metadata-reconciliation"
    )
    assert trace.status == "error"
    assert trace.error == "SKILL_RECEIPT_VERIFICATION_FAILED"
    assert any(
        finding.code == "FOLLOWUP_TOOL_ERROR" for finding in run.gate_result.findings
    )
    assert run.gate_result.decision.value == "DEFER"


def test_metadata_skill_defer_outcome_fails_worker_closed(
    tmp_path: Path, monkeypatch
) -> None:
    release, _ = _build_fixture(tmp_path / "input", metadata_total=2)

    def defer_skill(
        skill: MetadataCountDriftSkill,
        invocation: IndustrialSkillInvocation,
    ) -> IndustrialSkillOutcome:
        return IndustrialSkillOutcome(
            invocation_id=invocation.invocation_id,
            skill_id=skill.manifest.skill_id,
            skill_version=skill.manifest.skill_version,
            algorithm_version=skill.manifest.algorithm_version,
            source=invocation.source,
            status="DEFER",
            failure=IndustrialSkillFailure(
                reason_code="SKILL_EXECUTION_FAILED",
                safe_detail="Injected deterministic test defer.",
            ),
            claim_boundary=skill.manifest.claim_boundary,
        )

    monkeypatch.setattr(MetadataCountDriftSkill, "inspect", defer_skill)
    run = run_omni_readonly_gate(
        release,
        tmp_path / "evidence" / "gate",
        source_archive_sha256="c" * 64,
        per_bucket=1,
        seed=41,
    )

    plan = json.loads(run.leader_plan_path.read_text(encoding="utf-8"))
    task = next(
        item
        for item in plan["dynamic_tasks"]
        if item["task_id"] == "followup.metadata-reconciliation"
    )
    assert task["status"] == "failed"
    assert task["outputs"]["skill_outcome_status"] == "DEFER"
    assert task["outputs"]["skill_receipt_verified"] is True
    assert task["outputs"]["skill_receipt_verification_status"] == "VERIFIED"
    assert task["outputs"]["skill_integration_status"] == "FAIL_CLOSED"
    assert task["outputs"]["skill_failure_reason"] == "SKILL_OUTCOME_DEFER"
    receipt = IndustrialSkillReceipt.model_validate(task["outputs"]["skill_receipt"])
    assert verify_industrial_skill_receipt(receipt) is True
    trace = next(
        item
        for item in run.gate_result.tool_trace
        if item.parameters.get("followup_task_id") == "followup.metadata-reconciliation"
    )
    assert trace.status == "error"
    assert trace.error == "SKILL_OUTCOME_DEFER"
    assert run.gate_result.decision.value == "DEFER"


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
                "--followup-tool-budget",
                "0",
            ]
        )
        == 0
    )
    printed = json.loads(capsys.readouterr().out)
    assert printed["completion_state"] == "REAL_DATA_GATE_COMPLETED"
    assert printed["decision"] != "PASS"
    assert Path(printed["gate_result"]).is_file()
    assert Path(printed["receipt"]).is_file()
    receipt = json.loads(Path(printed["receipt"]).read_text(encoding="utf-8"))
    assert receipt["leader_followup_budget"]["budget_limit_units"] == 0
