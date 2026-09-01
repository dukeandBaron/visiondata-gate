from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

from visiondata_gate.adapter_sdk import verify_adapter_conformance
from visiondata_gate.cli import main
from visiondata_gate.evidence import canonical_json_bytes
from visiondata_gate.rulepack import (
    build_rule_pack_runtime_binding,
    load_rule_pack,
    verify_rule_pack,
)
from tools.audit_worktree_namespaces import _audit_current_claims


ROOT = Path(__file__).resolve().parents[1]
RULEPACK = ROOT / "rulepacks" / "industrial-v1.json"
MANIFEST = ROOT / "adapters" / "examples" / "omni-readonly-manifest.json"
OBSERVATION = ROOT / "adapters" / "examples" / "omni-readonly-observation.json"


def test_industrial_rulepack_is_strict_hashable_and_fail_closed(
    tmp_path: Path,
) -> None:
    pack = load_rule_pack(RULEPACK)
    assert pack.pack_id == "visiondata-gate.industrial-v1"
    assert pack.decision_precedence == [
        "INVESTIGATE",
        "RECAPTURE",
        "DEFER",
        "RELEASE",
    ]
    assert pack.production_release_allowed_by_default is False
    assert pack.raw_redistribution_allowed is False
    output = tmp_path / "rulepack-receipt.json"
    receipt = verify_rule_pack(RULEPACK, output=output)
    assert receipt.status == "PASS"
    assert receipt.rule_count == 5
    assert receipt.dynamic_trigger_count == 3
    assert len(receipt.source_file_sha256) == 64
    assert output.exists()


def test_industrial_rulepack_compiles_only_supported_runtime_surfaces() -> None:
    pack = load_rule_pack(RULEPACK)
    binding = build_rule_pack_runtime_binding(pack)

    assert binding.action_by_finding_code["COVERAGE_GAP"] == "RECAPTURE"
    assert binding.rule_id_by_finding_code["METADATA_COUNT_DRIFT"] == (
        "GV.EVIDENCE_CONFLICT"
    )
    assert binding.dynamic_trigger_capabilities == {
        "cross-tool-action-conflict": ("industrial-remediation-conflict-adjudication"),
        "metadata-count-drift": "industrial-metadata-reconciliation",
        "native-resolution-groups": ("native-resolution-quality-reconciliation"),
    }
    assert len(binding.binding_sha256) == 64

    unsafe_rule = pack.rules[0].model_copy(update={"action": "QUARANTINE"})
    unsafe_pack = pack.model_copy(update={"rules": [unsafe_rule, *pack.rules[1:]]})
    with pytest.raises(ValueError, match="non-executable action"):
        build_rule_pack_runtime_binding(unsafe_pack)

    unknown_trigger = pack.dynamic_trigger_rules[0].model_copy(
        update={"worker_capability": "unregistered-machine-writer"}
    )
    unsafe_trigger_pack = pack.model_copy(
        update={
            "dynamic_trigger_rules": [
                unknown_trigger,
                *pack.dynamic_trigger_rules[1:],
            ]
        }
    )
    with pytest.raises(ValueError, match="predicate/capability contract"):
        build_rule_pack_runtime_binding(unsafe_trigger_pack)


def test_rulepack_model_rejects_noncanonical_finding_code() -> None:
    pack = load_rule_pack(RULEPACK)
    payload = pack.model_dump(mode="json")
    payload["rules"][0]["finding_codes"][0] = "low_sharpness"

    with pytest.raises(ValueError, match="canonical upper snake case"):
        type(pack).model_validate(payload)


def test_rulepack_model_rejects_duplicate_finding_code_within_rule() -> None:
    pack = load_rule_pack(RULEPACK)
    payload = pack.model_dump(mode="json")
    finding_codes = payload["rules"][0]["finding_codes"]
    finding_codes.append(finding_codes[0])

    with pytest.raises(ValueError, match="within one rule must be unique"):
        type(pack).model_validate(payload)


def test_rulepack_model_rejects_finding_code_shared_across_rules() -> None:
    pack = load_rule_pack(RULEPACK)
    payload = pack.model_dump(mode="json")
    payload["rules"][1]["finding_codes"].append(payload["rules"][0]["finding_codes"][0])

    with pytest.raises(ValueError, match="map to exactly one policy rule"):
        type(pack).model_validate(payload)


def test_rulepack_schema_publishes_canonical_unique_finding_codes() -> None:
    schema = json.loads(
        (ROOT / "schemas" / "rulepack.schema.json").read_text(encoding="utf-8")
    )
    finding_codes = schema["$defs"]["rule"]["properties"]["finding_codes"]

    assert finding_codes["uniqueItems"] is True
    assert finding_codes["items"]["pattern"] == r"^[A-Z][A-Z0-9_]*$"


def test_adapter_examples_pass_offline_conformance(tmp_path: Path) -> None:
    output = tmp_path / "adapter-conformance.json"
    receipt = verify_adapter_conformance(MANIFEST, OBSERVATION, output=output)
    assert receipt["status"] == "PASS"
    assert all(item["status"] == "PASS" for item in receipt["checks"])
    assert receipt["actual_model_call_count"] == 0
    assert receipt["network_probe_performed"] is False
    observed = receipt.pop("receipt_sha256")
    assert observed == hashlib.sha256(canonical_json_bytes(receipt)).hexdigest()
    assert output.exists()


def test_adapter_conformance_fails_closed_on_path_or_sensitive_key(
    tmp_path: Path,
) -> None:
    payload = json.loads(OBSERVATION.read_text(encoding="utf-8"))
    payload["metrics"]["root_path"] = "C:\\private\\omni"
    poisoned = tmp_path / "poisoned-observation.json"
    poisoned.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    receipt = verify_adapter_conformance(MANIFEST, poisoned)
    assert receipt["status"] == "FAIL"
    redaction = next(
        item
        for item in receipt["checks"]
        if item["check_id"] == "path_and_secret_redaction"
    )
    assert redaction["status"] == "FAIL"
    assert "C:\\private" not in json.dumps(receipt, ensure_ascii=False)


def test_reuse_contract_cli_commands(tmp_path: Path) -> None:
    adapter_output = tmp_path / "adapter.json"
    assert (
        main(
            [
                "adapter-conformance",
                "--manifest",
                str(MANIFEST),
                "--observation",
                str(OBSERVATION),
                "--output",
                str(adapter_output),
            ]
        )
        == 0
    )
    rulepack_output = tmp_path / "rulepack.json"
    assert (
        main(
            [
                "rulepack-verify",
                "--rulepack",
                str(RULEPACK),
                "--output",
                str(rulepack_output),
            ]
        )
        == 0
    )
    assert adapter_output.exists()
    assert rulepack_output.exists()


def test_published_json_schemas_are_well_formed() -> None:
    schemas = sorted((ROOT / "schemas").glob("*.schema.json"))
    assert {item.name for item in schemas} == {
        "adapter-manifest.schema.json",
        "adapter-observation.schema.json",
        "evidence-finding.schema.json",
        "rulepack.schema.json",
    }
    for schema in schemas:
        payload = json.loads(schema.read_text(encoding="utf-8"))
        assert payload["$schema"].endswith("2020-12/schema")
        assert payload["type"] == "object"


def test_current_rc3_claims_preserve_failure_and_model_boundaries() -> None:
    report = _audit_current_claims(ROOT, require_local_evidence=False)
    assert report["status"] == "PASS"
    assert report["missing_requirements"] == []
    assert report["stale_claim_hits"] == []
