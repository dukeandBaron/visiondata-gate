from __future__ import annotations

import json
import re
from pathlib import Path

import pytest
from pydantic import ValidationError

from visiondata_gate.contracts import (
    BatchContract,
    BatchManifest,
    CorruptionManifest,
    Finding,
    ToolTrace,
)
from visiondata_gate.generator import generate_demo_dataset
from visiondata_gate.tools import (
    run_all_tools,
    run_tool,
    tool_catalog,
    tool_contract_catalog,
    validate_tool_contract_trace,
)


def _read(path: Path, model_type):
    return model_type.model_validate(json.loads(path.read_text(encoding="utf-8")))


def _issue_keys(items) -> set[tuple[str, tuple[str, ...]]]:
    return {(item.code, tuple(sorted(item.sample_ids))) for item in items}


def test_all_tools_exactly_recover_the_hidden_programmatic_truth(
    tmp_path: Path,
) -> None:
    paths = generate_demo_dataset(tmp_path / "dataset", seed=2026)
    truth = _read(paths["corruption_manifest"], CorruptionManifest)
    contract = BatchContract()

    findings, traces, metrics = run_all_tools(
        paths["batch_root"], paths["batch_manifest"], contract
    )

    assert all(isinstance(item, Finding) for item in findings)
    assert all(isinstance(item, ToolTrace) for item in traces)
    assert _issue_keys(findings) == _issue_keys(truth.issues)
    assert [trace.sequence for trace in traces] == [1, 2, 3, 4]
    assert [trace.tool for trace in traces] == [
        "image_quality",
        "duplicate_leakage",
        "annotation_integrity",
        "coverage_matrix",
    ]
    assert all(trace.status == "ok" and trace.error is None for trace in traces)
    assert all(re.fullmatch(r"[0-9a-f]{64}", trace.input_sha256) for trace in traces)
    assert all(re.fullmatch(r"[0-9a-f]{64}", trace.result_sha256) for trace in traces)
    assert all(
        trace.contract_digest and trace.adapter == "local-deterministic"
        for trace in traces
    )
    assert metrics["finding_count"] == len(truth.issues)
    assert metrics["tool_count"] == 4
    assert metrics["coverage_missing_cell_count"] == 1


def test_catalog_includes_optional_gov_when_enabled() -> None:
    core = {item["name"] for item in tool_catalog()}
    optional = {item["name"] for item in tool_catalog(include_optional=True)}
    assert "governance_audit" not in core
    assert "governance_audit" in optional


def test_typed_tool_contracts_bind_and_detect_drift(tmp_path: Path) -> None:
    paths = generate_demo_dataset(tmp_path / "dataset", seed=2026)
    _, traces, _ = run_all_tools(
        paths["batch_root"],
        paths["batch_manifest"],
        BatchContract(),
        include_optional_tools=True,
    )
    contracts = tool_contract_catalog(include_optional=True)
    assert len(contracts) == 5
    assert all(
        validate_tool_contract_trace(trace, include_optional=True) is None
        for trace in traces
    )
    drifted = traces[0].model_copy(update={"contract_version": "9.9.9"})
    assert "version drift" in (validate_tool_contract_trace(drifted) or "")


def test_run_all_tools_with_optional_governance_can_be_extended(
    tmp_path: Path,
) -> None:
    paths = generate_demo_dataset(tmp_path / "dataset", seed=2026)
    contract = BatchContract()
    findings, traces, metrics = run_all_tools(
        paths["batch_root"],
        paths["batch_manifest"],
        contract,
        include_optional_tools=True,
    )

    assert [trace.sequence for trace in traces] == [1, 2, 3, 4, 5]
    assert [trace.tool for trace in traces] == [
        "image_quality",
        "duplicate_leakage",
        "annotation_integrity",
        "coverage_matrix",
        "governance_audit",
    ]
    assert metrics["tool_count"] == 5
    assert "governance_missing_cell_count" in metrics
    assert "governance_governance_missing_cell_count" not in metrics
    assert metrics["governance_missing_cell_count"] >= 0
    assert any(trace.tool == "governance_audit" for trace in traces)


def test_run_single_tool_rejects_governance_when_not_enabled() -> None:
    with pytest.raises(ValueError):
        run_tool("governance_audit", "nowhere", {}, {})


def test_tool_results_and_traces_are_reproducible(tmp_path: Path) -> None:
    paths = generate_demo_dataset(tmp_path / "dataset", seed=31)
    first = run_all_tools(paths["batch_root"], paths["batch_manifest"], BatchContract())
    second = run_all_tools(
        paths["batch_root"], paths["batch_manifest"], BatchContract()
    )

    first_payload = (
        [item.model_dump(mode="json") for item in first[0]],
        [item.model_dump(mode="json") for item in first[1]],
        first[2],
    )
    second_payload = (
        [item.model_dump(mode="json") for item in second[0]],
        [item.model_dump(mode="json") for item in second[1]],
        second[2],
    )
    assert first_payload == second_payload


def test_run_all_tools_revalidates_model_instances_and_rejects_traversal(
    tmp_path: Path,
) -> None:
    paths = generate_demo_dataset(tmp_path / "dataset", seed=12)
    manifest = _read(paths["batch_manifest"], BatchManifest)
    unsafe_sample = manifest.samples[0].model_copy(
        update={"relative_path": "../outside.png"}
    )
    unsafe_manifest = manifest.model_copy(
        update={"samples": [unsafe_sample, *manifest.samples[1:]]}
    )

    with pytest.raises(ValidationError):
        run_all_tools(paths["batch_root"], unsafe_manifest, BatchContract())


def test_run_all_tools_does_not_swallow_missing_batch_root(tmp_path: Path) -> None:
    paths = generate_demo_dataset(tmp_path / "dataset", seed=3)

    with pytest.raises(FileNotFoundError):
        run_all_tools(tmp_path / "missing", paths["batch_manifest"], BatchContract())
