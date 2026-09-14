"""Readiness is an evidence projection, never data-goodness or training authority."""

from __future__ import annotations

import hashlib
import importlib
import importlib.util
import json
from types import SimpleNamespace

import pytest

from tests.test_learning_lifecycle import ACTOR, learning_input as learning_input
from visiondata_gate.audit_envelope import canonical_jcs_bytes
from visiondata_gate.compute_handoff import REQUIRED_TOOLS
from visiondata_gate.contracts import Finding, GateDecision
from visiondata_gate.product_models import TaskExecutionStatus
from visiondata_gate.task_store import NotFoundError


def _module():
    name = "visiondata_gate.learning_projection"
    assert importlib.util.find_spec(name) is not None, (
        "Learning readiness projection missing"
    )
    return importlib.import_module(name)


def _inputs():
    samples = [
        SimpleNamespace(
            sample_id="img_one",
            split="train",
            category="defect",
            annotation_path="masks/one.png",
        ),
        SimpleNamespace(
            sample_id="img_two", split="val", category="good", annotation_path=None
        ),
    ]
    manifest = SimpleNamespace(samples=samples)
    contract = SimpleNamespace(
        sample_annotation_requirements={
            "img_one": "REQUIRED",
            "img_two": "NOT_APPLICABLE",
        }
    )
    gate = SimpleNamespace(
        decision=GateDecision.PASS,
        findings=[],
        tool_trace=[
            SimpleNamespace(tool=name, status="ok", error=None)
            for name in sorted(REQUIRED_TOOLS)
        ],
    )
    snapshot = SimpleNamespace(
        assets=[
            SimpleNamespace(
                asset_id="img_one",
                mask_relative_path="batch/masks/one.png",
                mask_sha256="a" * 64,
            ),
            SimpleNamespace(
                asset_id="img_two", mask_relative_path=None, mask_sha256=None
            ),
        ]
    )
    preflight = {"eligibility": "READY_FOR_OFFLINE_HANDOFF", "blockers": []}
    return manifest, contract, gate, snapshot, preflight


def _finding(sample_ids):
    return Finding(
        finding_id="finding_1",
        code="LOW_SHARPNESS",
        severity="high",
        tool="image_quality",
        sample_ids=sample_ids,
        summary="PRIVATE_SOURCE_PATH_MUST_NOT_LEAK",
        evidence={"path": "C:/private/image.png"},
        recommended_action="recapture",
    )


def test_mask_missing_is_trainer_requirement_not_bad_data():
    module = _module()
    result = module._project_members(*_inputs())
    assert (
        result["members"][0]["readiness_state"] == "GATE_ELIGIBLE_NOT_TRAINING_APPROVED"
    )
    assert (
        result["members"][1]["readiness_state"] == "MASK_REQUIRED_FOR_REFERENCE_TRAINER"
    )
    assert result["members"][1]["annotation_requirement"] == "NOT_APPLICABLE"
    assert result["members"][1]["mask_available"] is False


def test_member_findings_use_exact_identity_and_hash_only():
    module = _module()
    values = _inputs()
    values[2].findings = [_finding(["img_one"])]
    result = module._project_members(*values)
    assert result["members"][0]["readiness_state"] == "NEEDS_ATTENTION"
    assert result["members"][1]["finding_refs"] == []
    reference = result["members"][0]["finding_refs"][0]
    assert set(reference) == {"finding_id", "code", "severity", "finding_sha256"}
    assert (
        reference["finding_sha256"]
        == hashlib.sha256(canonical_jcs_bytes(values[2].findings[0])).hexdigest()
    )
    assert "PRIVATE_SOURCE" not in json.dumps(result)
    assert "C:/private" not in json.dumps(result)


def test_global_finding_does_not_falsely_identify_every_member():
    module = _module()
    values = _inputs()
    values[2].findings = [_finding([])]
    values[2].decision = GateDecision.QUARANTINE
    values[4].update(eligibility="HOLD", blockers=["GATE_NOT_PASS"])
    result = module._project_members(*values)
    assert len(result["global_findings"]) == 1
    assert result["members"][0]["readiness_state"] == "BLOCKED_BY_BATCH"
    assert all(item["finding_refs"] == [] for item in result["members"])


def test_unmapped_finding_identity_holds_all_members_without_guessing():
    module = _module()
    values = _inputs()
    values[2].findings = [_finding(["unknown-asset"])]
    result = module._project_members(*values)
    assert all(
        item["readiness_state"] == "UNVERIFIED_FINDING_IDENTITY"
        for item in result["members"]
    )
    assert result["unmapped_finding_refs"]
    assert "FINDING_IDENTITY_UNMAPPED" in result["blockers"]


def test_tool_failure_cannot_be_projected_as_eligible():
    module = _module()
    values = _inputs()
    values[2].tool_trace[0].status = "error"
    values[2].tool_trace[0].error = "SECRET_PATH"
    result = module._project_members(*values)
    assert all(
        item["readiness_state"] == "UNVERIFIED_TOOL_FAILURE"
        for item in result["members"]
    )
    assert "SECRET_PATH" not in json.dumps(result)


def test_missing_tool_evidence_is_unknown_not_a_pass():
    module = _module()
    values = _inputs()
    values[2].tool_trace.pop()
    result = module._project_members(*values)
    assert all(item["readiness_state"] == "UNVERIFIED" for item in result["members"])
    assert "REQUIRED_TOOL_EVIDENCE_INCOMPLETE" in result["blockers"]


def test_mask_binding_mismatch_is_unknown_not_present():
    module = _module()
    values = _inputs()
    values[3].assets[0].mask_relative_path = "batch/masks/other.png"
    result = module._project_members(*values)
    assert result["members"][0]["readiness_state"] == "UNVERIFIED"
    assert result["members"][0]["mask_available"] is None


def test_real_gate_projection_is_sealed_and_never_grants_training(learning_input):
    module = _module()
    _client, product, (task_id, preflight, _groups) = learning_input
    result = module.learning_readiness(product, ACTOR, task_id)
    assert result["task_id"] == task_id
    assert result["preflight_receipt_sha256"] == preflight["receipt_sha256"]
    assert result["preflight_eligibility"] == "READY_FOR_OFFLINE_HANDOFF"
    assert len(result["members"]) == 4
    assert all(
        item["readiness_state"] == "GATE_ELIGIBLE_NOT_TRAINING_APPROVED"
        for item in result["members"]
    )
    assert result["training_authorized"] is False
    assert result["production_release_allowed"] is False
    assert (
        result["annotation_review_basis"]
        == "OPERATOR_ATTESTATION_NOT_INDEPENDENT_TRUTH"
    )
    assert "BINARY_MASK_VALUES" in result["required_dataset_validation"]
    stable = {key: value for key, value in result.items() if key != "receipt_sha256"}
    assert (
        result["receipt_sha256"]
        == hashlib.sha256(canonical_jcs_bytes(stable)).hexdigest()
    )
    assert module.learning_readiness(product, ACTOR, task_id) == result
    with pytest.raises(NotFoundError):
        module.learning_readiness(product, "usr_foreign", task_id)


def test_unavailable_context_is_safe_unverified_but_permissions_propagate(monkeypatch):
    module = _module()
    task = SimpleNamespace(
        task_id="task_one",
        project_id="project_one",
        workspace_id="workspace_one",
        execution_status=TaskExecutionStatus.COMPLETED,
    )
    product = SimpleNamespace(store=SimpleNamespace(get_task=lambda *_args: task))

    def unavailable(*_args):
        raise ValueError("C:/private/SECRET")

    monkeypatch.setattr(module, "compute_preflight", unavailable)
    result = module.learning_readiness(product, "actor", "task_one")
    assert result["projection_status"] == "UNVERIFIED"
    assert result["members"] == []
    assert "PREFLIGHT_UNAVAILABLE" in result["blockers"]
    assert "SECRET" not in json.dumps(result)

    def forbidden(*_args):
        raise NotFoundError("not visible")

    product.store.get_task = forbidden
    with pytest.raises(NotFoundError):
        module.learning_readiness(product, "foreign", "task_one")


def _fake_product_and_preflight(module, state=TaskExecutionStatus.COMPLETED):
    task = SimpleNamespace(
        task_id="task_one",
        project_id="project_one",
        workspace_id="workspace_one",
        execution_status=state,
    )
    product = SimpleNamespace(store=SimpleNamespace(get_task=lambda *_args: task))
    preflight = module._seal(
        {
            "schema_version": "visiondata-gate.compute-preflight.v1",
            "task_id": task.task_id,
            "project_id": task.project_id,
            "workspace_id": task.workspace_id,
            "eligibility": "HOLD",
            "blockers": ["GATE_NOT_PASS"],
            "binding": None,
        }
    )
    return product, preflight


def test_incomplete_task_is_unverified_without_reading_private_context(monkeypatch):
    module = _module()
    product, preflight = _fake_product_and_preflight(
        module, TaskExecutionStatus.RUNNING
    )
    monkeypatch.setattr(module, "compute_preflight", lambda *_args: preflight)
    result = module.learning_readiness(product, "actor", "task_one")
    assert result["projection_status"] == "UNVERIFIED"
    assert result["members"] == []
    assert "TASK_NOT_COMPLETED" in result["blockers"]
    assert result["training_authorized"] is False


def test_preflight_digest_or_unknown_eligibility_cannot_claim_readiness(monkeypatch):
    module = _module()
    product, original = _fake_product_and_preflight(module)
    for changed in (
        dict(original, receipt_sha256="0" * 64),
        module._seal(dict(original, eligibility="UNKNOWN")),
    ):
        monkeypatch.setattr(
            module, "compute_preflight", lambda *_args, value=changed: value
        )
        result = module.learning_readiness(product, "actor", "task_one")
        assert result["projection_status"] == "UNVERIFIED"
        assert result["preflight_eligibility"] == "UNVERIFIED"
        assert result["preflight_receipt_sha256"] is None


def test_context_error_never_exposes_path_and_late_permission_failure_propagates(
    monkeypatch,
):
    module = _module()
    product, preflight = _fake_product_and_preflight(module)
    monkeypatch.setattr(module, "compute_preflight", lambda *_args: preflight)

    def missing_context(*_args):
        raise ValueError("C:/PRIVATE_SOURCE/SECRET")

    product._annotation_context = missing_context
    result = module.learning_readiness(product, "actor", "task_one")
    assert "FROZEN_CONTEXT_UNAVAILABLE" in result["blockers"]
    assert "PRIVATE_SOURCE" not in json.dumps(result)

    def lost_permission(*_args):
        raise NotFoundError("no longer visible")

    product._annotation_context = lost_permission
    with pytest.raises(NotFoundError):
        module.learning_readiness(product, "actor", "task_one")
