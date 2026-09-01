from __future__ import annotations

import hashlib
import json
from pathlib import Path
import zipfile

from PIL import Image
import pytest

from visiondata_gate.cli import main
from visiondata_gate.product_runs import _verify_dynamic_task_event_bindings
from visiondata_gate.runtime_models import RuntimeEvent, RuntimeStage, RuntimeStatus


def _write_metadata(path: Path, *, category: str) -> None:
    headers = ["数据集名称", "样本总数", "good(train)", "good(test)", "NG(test)"]
    values: list[str | int] = [category, 2, 1, 1, 0]

    def cell(column: str, row: int, value: str | int) -> str:
        if isinstance(value, int):
            return f'<c r="{column}{row}"><v>{value}</v></c>'
        return f'<c r="{column}{row}" t="inlineStr"><is><t>{value}</t></is></c>'

    columns = ["A", "B", "C", "D", "E"]
    sheet = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">'
        '<sheetData><row r="1">'
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


def _build_omni_source(root: Path) -> Path:
    release = root / "authorized-omni-source"
    category = "cli-widget"
    images = (
        (
            f"{category}/train/good/train.png",
            Image.new("RGB", (32, 32), (90, 120, 150)),
        ),
        (f"{category}/test/good/good.png", Image.new("RGB", (48, 32), (90, 120, 150))),
        (
            f"{category}/test/scratch/bad.png",
            Image.new("RGB", (32, 32), (90, 120, 150)),
        ),
        (f"{category}/ground_truth/scratch/bad.png", Image.new("L", (32, 32), 0)),
    )
    for relative, image in images:
        destination = release / relative
        destination.parent.mkdir(parents=True, exist_ok=True)
        image.save(destination)
    _write_metadata(release / "official.xlsx", category=category)
    return release


def _source_snapshot(root: Path) -> dict[str, str]:
    return {
        path.relative_to(root).as_posix(): hashlib.sha256(path.read_bytes()).hexdigest()
        for path in sorted(root.rglob("*"))
        if path.is_file()
    }


def _dynamic_task_event_fixture() -> tuple[dict[str, object], RuntimeEvent]:
    result_sha256 = "a" * 64
    input_refs = ["finding:metadata-drift", "trace:5:governance_audit"]
    task = {
        "task_id": "followup.metadata-count-drift",
        "worker_id": "metadata-reconciliation-worker",
        "status": "completed",
        "input_refs": input_refs,
        "result_sha256": result_sha256,
        "tool_trace_ref": "trace:6:metadata_reconciliation",
        "tool_trace_result_sha256": result_sha256,
    }
    event = RuntimeEvent(
        sequence=1,
        phase="verification",
        stage=RuntimeStage.TOOL,
        actor="metadata-reconciliation-worker",
        action="execute_evidence_followup",
        status=RuntimeStatus.SUCCESS,
        summary="Dynamic follow-up completed.",
        task_id="followup.metadata-count-drift",
        tool_name="metadata_reconciliation",
        evidence_refs=[*input_refs, f"result_sha256:{result_sha256}"],
    )
    return task, event


def test_dynamic_plan_task_is_bound_to_its_live_tool_event() -> None:
    task, event = _dynamic_task_event_fixture()

    _verify_dynamic_task_event_bindings([task], [event])


@pytest.mark.parametrize(
    "drift",
    [
        "task_id",
        "worker_id",
        "tool_name",
        "status",
        "input_refs",
        "result_sha256",
    ],
)
def test_dynamic_plan_task_event_binding_fails_closed_on_field_drift(
    drift: str,
) -> None:
    task, event = _dynamic_task_event_fixture()
    if drift == "task_id":
        task["task_id"] = "followup.forged-task"
    elif drift == "worker_id":
        task["worker_id"] = "forged-worker"
    elif drift == "tool_name":
        event = event.model_copy(update={"tool_name": "forged_tool"})
    elif drift == "status":
        event = event.model_copy(update={"status": RuntimeStatus.WARNING})
    elif drift == "input_refs":
        task["input_refs"] = ["finding:forged"]
    else:
        task["result_sha256"] = "b" * 64
        task["tool_trace_result_sha256"] = "b" * 64

    with pytest.raises(ValueError, match="authorized dynamic task"):
        _verify_dynamic_task_event_bindings([task], [event])


def test_product_run_cli_executes_real_product_kernel_without_mutating_source(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    source_root = _build_omni_source(tmp_path / "source-owner")
    product_root = tmp_path / "private-product-state"
    before = _source_snapshot(source_root)

    exit_code = main(
        [
            "product-run",
            "--source-root",
            str(source_root),
            "--source-archive-sha256",
            "7" * 64,
            "--purpose",
            "Local read-only industrial data quality review.",
            "--rights-basis",
            "Operator confirms permission for this bounded local review.",
            "--attest-authorized-use",
            "--product-root",
            str(product_root),
            "--seed",
            "17",
        ]
    )

    captured = capsys.readouterr()
    assert exit_code == 0
    assert captured.err == ""
    payload = json.loads(captured.out)
    assert payload["schema_version"] == "visiondata-gate.product-run-cli.v1"
    assert payload["command_status"] == "COMPLETED_LOCAL_PRODUCT_KERNEL"
    assert payload["task_execution_status"] == "COMPLETED"
    assert payload["kernel_receipt_status"] == ("TASK_BOUND_IN_SHA_VERIFIED_EVIDENCE")
    assert payload["runtime_kind"] == "authorized_local_readonly"
    assert payload["completion_contract"] == ("TYPED_RUNTIME_AND_GATE_RESULTS_VERIFIED")
    assert payload["source_read_mode"] == "READ_ONLY_IN_PLACE"
    assert payload["source_assets_copied_into_product"] is False
    assert payload["network_mode"] == "OFFLINE_NO_EXTERNAL_TRANSPORT"
    assert payload["external_model_call_count"] == 0
    assert payload["production_human_approval_required"] is True
    assert payload["production_approval_status"] == "pending"
    assert payload["production_release_allowed"] is False
    assert "PASS" not in payload["command_status"]
    assert len(payload["kernel_receipt_sha256"]) == 64
    assert len(payload["evidence_sha256"]) == 64
    assert _source_snapshot(source_root) == before
    assert str(source_root) not in captured.out
    assert str(product_root) not in captured.out

    persisted_receipts = list(
        product_root.rglob("evidence/product_kernel_run_receipt.json")
    )
    assert len(persisted_receipts) == 1
    persisted = json.loads(persisted_receipts[0].read_text(encoding="utf-8"))
    assert persisted["receipt_sha256"] == payload["kernel_receipt_sha256"]
    assert persisted["run_id"] == payload["run_id"]


def test_product_run_cli_rejects_invalid_archive_digest_without_creating_state(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    source_root = tmp_path / "source"
    source_root.mkdir()
    product_root = tmp_path / "must-not-exist"

    exit_code = main(
        [
            "product-run",
            "--source-root",
            str(source_root),
            "--source-archive-sha256",
            "not-a-sha",
            "--purpose",
            "Local read-only industrial review.",
            "--rights-basis",
            "Operator confirms permission for this review.",
            "--attest-authorized-use",
            "--product-root",
            str(product_root),
        ]
    )

    captured = capsys.readouterr()
    assert exit_code == 2
    assert captured.out == ""
    error = json.loads(captured.err)
    assert error["command_status"] == "FAILED"
    assert error["error"]["code"] == "INVALID_SOURCE_ARCHIVE_SHA256"
    assert error["production_release_allowed"] is False
    assert str(source_root) not in captured.err
    assert str(product_root) not in captured.err
    assert not product_root.exists()


def test_product_run_cli_rejects_a_product_root_inside_the_source(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    source_root = tmp_path / "source"
    source_root.mkdir()
    product_root = source_root / "product-state"

    exit_code = main(
        [
            "product-run",
            "--source-root",
            str(source_root),
            "--source-archive-sha256",
            "7" * 64,
            "--purpose",
            "Local read-only industrial review.",
            "--rights-basis",
            "Operator confirms permission for this review.",
            "--attest-authorized-use",
            "--product-root",
            str(product_root),
        ]
    )

    captured = capsys.readouterr()
    assert exit_code == 2
    assert captured.out == ""
    error = json.loads(captured.err)
    assert error["error"]["code"] == "PRODUCT_ROOT_OVERLAPS_SOURCE"
    assert error["production_release_allowed"] is False
    assert _source_snapshot(source_root) == {}
    assert not product_root.exists()
