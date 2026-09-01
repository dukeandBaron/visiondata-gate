from __future__ import annotations

import json
import re
import shutil
from pathlib import Path

import pytest

from visiondata_gate.release import (
    ARCHITECTURE_FILENAME,
    DEFAULT_RELEASE_ID,
    DYNAMIC_PLAN_FILENAME,
    OMNI_GATE_FILENAME,
    OMNI_RECEIPT_FILENAME,
    REDACTION_RECEIPT_FILENAME,
    RELEASE_MANIFEST_FILENAME,
    SCENARIO_DELIVERY_FILENAME,
    SYNTHETIC_SUMMARY_FILENAME,
    ReleaseValidationError,
    build_submission_release,
    load_submission_release,
)
from visiondata_gate.evidence import canonical_json_bytes, sha256_bytes


PROJECT_ROOT = Path(__file__).resolve().parents[1]
PUBLIC_RELEASE = PROJECT_ROOT / "evidence" / "submission" / DEFAULT_RELEASE_ID


def test_public_release_is_cross_hashed_and_application_first() -> None:
    release = load_submission_release(PUBLIC_RELEASE)
    manifest = release.manifest
    assert manifest["track"] == {
        "event": "GOAI 世界人工智能开源大赛",
        "industry_direction": "AI+工业制造",
        "official_url": "https://www.goaihz.com/tracks?track=apps",
        "track_name_en": "Boundless Agents",
        "track_name_zh": "无界应用",
        "track_number": 2,
    }
    assert manifest["project"]["positioning"] == "工业视觉数据治理与发布 Agent"
    assert manifest["infra_support"]["role"] == "可信后台，不是参赛主叙事"
    assert manifest["agentteams"]["connection_status"] == "mapped_not_connected"
    assert manifest["runtime_disclosure"]["actual_model_call_count"] == 0
    receipt = release.scenario_delivery_receipt
    assert receipt["status"] == "LOCAL_SCENARIO_PILOT_VERIFIED"
    assert receipt["scenario"]["name"] == "训练前工业视觉数据批次审核与发布门禁"
    assert receipt["proof_ladder"]["implemented"]["status"] == "PASS"
    assert receipt["proof_ladder"]["public_pilot"]["status"] == "PASS"
    assert receipt["proof_ladder"]["external_validation"]["status"] == "OPEN"


def test_public_release_preserves_fixed_denominators_and_negative_result() -> None:
    release = load_submission_release(PUBLIC_RELEASE)
    namespaces = release.manifest["evidence_namespaces"]
    assert set(namespaces) == {"Synthetic-v3", "ArchBench-v2", "Omni-180-v1"}
    assert namespaces["ArchBench-v2"]["record_count"] == 288
    assert (
        namespaces["ArchBench-v2"]["fixed_sop_multi_agent_necessity_supported"] is False
    )
    assert namespaces["Omni-180-v1"]["selected_image_count"] == 180
    assert namespaces["Omni-180-v1"]["source_tree_image_count"] == 4464
    assert namespaces["Omni-180-v1"]["dynamic_task_count"] == 3
    assert namespaces["Omni-180-v1"]["finding_count"] == 45
    assert namespaces["Omni-180-v1"]["work_order_count"] == 45
    assert namespaces["Omni-180-v1"]["rule_check_count"] == 8
    pilot = release.scenario_delivery_receipt["observed_pilot"]
    assert pilot["fixed_image_denominator"] == 180
    assert pilot["replan_count"] == 1
    assert pilot["dynamic_worker_count"] == 3
    assert pilot["finding_count"] == pilot["work_order_count"] == 45
    assert pilot["decision"] == "RECAPTURE"
    assert [item["observed_value"] for item in pilot["dynamic_triggers"]] == [
        2,
        15,
        28,
    ]


def test_public_release_contains_no_local_absolute_or_private_paths() -> None:
    windows_absolute = re.compile(rb"(?i)(?<![A-Za-z0-9])[A-Z]:[\\/]")
    forbidden = (b"file://", b"/users/", b"\\users\\", b"appdata/local/temp")
    for path in PUBLIC_RELEASE.iterdir():
        if not path.is_file():
            continue
        data = path.read_bytes()
        lowered = data.lower()
        assert windows_absolute.search(data) is None, path.name
        assert not any(marker in lowered for marker in forbidden), path.name


def test_public_release_rejects_cross_hash_tamper(tmp_path: Path) -> None:
    target = tmp_path / DEFAULT_RELEASE_ID
    shutil.copytree(PUBLIC_RELEASE, target)
    gate_path = target / OMNI_GATE_FILENAME
    payload = json.loads(gate_path.read_text(encoding="utf-8"))
    payload["decision_reason"] = "tampered"
    gate_path.write_text(json.dumps(payload), encoding="utf-8")
    with pytest.raises(ReleaseValidationError, match="hash|receipt|artifact"):
        load_submission_release(target)


def test_public_release_rejects_semantic_scenario_receipt_tamper(
    tmp_path: Path,
) -> None:
    target = tmp_path / DEFAULT_RELEASE_ID
    shutil.copytree(PUBLIC_RELEASE, target)
    scenario_path = target / SCENARIO_DELIVERY_FILENAME
    scenario = json.loads(scenario_path.read_text(encoding="utf-8"))
    scenario["observed_pilot"]["dynamic_worker_count"] = 4
    scenario_data = canonical_json_bytes(scenario)
    scenario_path.write_bytes(scenario_data)

    digest = sha256_bytes(scenario_data)
    redaction_path = target / REDACTION_RECEIPT_FILENAME
    redaction = json.loads(redaction_path.read_text(encoding="utf-8"))
    record = next(
        item
        for item in redaction["files"]
        if item["public_path"] == SCENARIO_DELIVERY_FILENAME
    )
    record["source_sha256"] = digest
    record["public_sha256"] = digest
    redaction_path.write_bytes(canonical_json_bytes(redaction))

    manifest_path = target / RELEASE_MANIFEST_FILENAME
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    artifact = manifest["artifacts"]["scenario_delivery_receipt"]
    artifact["sha256"] = digest
    artifact["size"] = len(scenario_data)
    redaction_data = redaction_path.read_bytes()
    redaction_artifact = manifest["artifacts"]["redaction_receipt"]
    redaction_artifact["sha256"] = sha256_bytes(redaction_data)
    redaction_artifact["size"] = len(redaction_data)
    manifest_path.write_bytes(canonical_json_bytes(manifest))

    with pytest.raises(ReleaseValidationError, match="scenario delivery receipt"):
        load_submission_release(target)


def test_release_builder_reproduces_valid_public_bundle(tmp_path: Path) -> None:
    project = tmp_path / "project"
    project.mkdir()
    output = project / "evidence" / "submission" / DEFAULT_RELEASE_ID
    release = build_submission_release(
        project_root=project,
        output_dir=output,
        architecture_benchmark_path=PUBLIC_RELEASE / ARCHITECTURE_FILENAME,
        dynamic_plan_path=PUBLIC_RELEASE / DYNAMIC_PLAN_FILENAME,
        omni_gate_path=PUBLIC_RELEASE / OMNI_GATE_FILENAME,
        omni_receipt_path=PUBLIC_RELEASE / OMNI_RECEIPT_FILENAME,
        synthetic_summary_path=PUBLIC_RELEASE / SYNTHETIC_SUMMARY_FILENAME,
        qa_passed=160,
        qa_skipped=1,
        qa_warnings=1,
        ruff_status="PASS",
        format_status="PASS",
        compileall_status="PASS",
    )
    assert release.manifest["quality_gates"]["pytest"] == {
        "failed": 0,
        "passed": 160,
        "skipped": 1,
        "warnings": 1,
    }
    assert (output / RELEASE_MANIFEST_FILENAME).is_file()
    assert (output / SCENARIO_DELIVERY_FILENAME).is_file()
    assert load_submission_release(output).manifest == release.manifest
