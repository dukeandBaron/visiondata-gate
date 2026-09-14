"""Read-only, SHA-sealed sample readiness; never a data-goodness classifier.

Existing ProductService contexts verify frozen evidence and original members.
This projection does not approve training, infer independent annotation truth,
or replace learning_dataset.freeze_dataset's group/mask/split validation.
"""

from __future__ import annotations

import hashlib
import hmac
import re

from .audit_envelope import canonical_jcs_bytes
from .compute_handoff import REQUIRED_TOOLS, compute_preflight
from .product_models import TaskExecutionStatus
from .task_store import NotFoundError


def _sha(value) -> str:
    return hashlib.sha256(canonical_jcs_bytes(value)).hexdigest()


def _seal(value: dict) -> dict:
    stable = {key: item for key, item in value.items() if key != "receipt_sha256"}
    return {**stable, "receipt_sha256": _sha(stable)}


def _value(value):
    return getattr(value, "value", value)


def _finding_ref(finding) -> dict:
    return {
        "finding_id": finding.finding_id,
        "code": finding.code,
        "severity": _value(finding.severity),
        "finding_sha256": _sha(finding.model_dump(mode="json")),
    }


def _safe_blockers(values) -> list[str]:
    if not isinstance(values, list) or any(
        not isinstance(value, str) or not re.fullmatch(r"[A-Z][A-Z0-9_]{0,100}", value)
        for value in values
    ):
        raise ValueError("unsafe blocker metadata")
    return sorted(set(values))


def _project_members(manifest, contract, gate, snapshot, preflight) -> dict:
    """Deterministic projection over already verified contexts; no file reads."""
    blockers = set(_safe_blockers(preflight["blockers"]))
    sample_ids = [sample.sample_id for sample in manifest.samples]
    known_ids = set(sample_ids)
    asset_ids = [asset.asset_id for asset in snapshot.assets]
    assets = {asset.asset_id: asset for asset in snapshot.assets}
    member_identity_valid = (
        len(sample_ids) == len(known_ids)
        and len(asset_ids) == len(assets)
        and known_ids == set(assets)
    )
    if not member_identity_valid:
        blockers.add("SNAPSHOT_MEMBER_IDENTITY_UNVERIFIED")
    references = {sample_id: [] for sample_id in known_ids}
    global_findings, unmapped = [], []
    for finding in gate.findings:
        reference = _finding_ref(finding)
        if not finding.sample_ids:
            global_findings.append(reference)
        elif not set(finding.sample_ids).issubset(known_ids):
            unmapped.append(reference)
        else:
            for sample_id in set(finding.sample_ids):
                references[sample_id].append(reference)
    if unmapped:
        blockers.add("FINDING_IDENTITY_UNMAPPED")
    failed_tool = any(
        trace.status == "error" or trace.error is not None for trace in gate.tool_trace
    )
    complete_tools = REQUIRED_TOOLS.issubset(
        {
            trace.tool
            for trace in gate.tool_trace
            if trace.status == "ok" and trace.error is None
        }
    )
    if failed_tool:
        blockers.add("DETERMINISTIC_TOOL_FAILURE")
    elif not complete_tools:
        blockers.add("REQUIRED_TOOL_EVIDENCE_INCOMPLETE")
    decision = _value(gate.decision)
    decision_valid = decision in {"PASS", "QUARANTINE", "RECAPTURE", "DEFER"}
    if not decision_valid:
        blockers.add("GATE_DECISION_UNVERIFIED")
    uncertain_input = bool(
        blockers
        & {
            "FROZEN_EVIDENCE_UNAVAILABLE",
            "GATE_INPUT_MISMATCH",
            "ACCEPTANCE_BINDING_MISMATCH",
            "CONTRACT_ACCEPTANCE_MISMATCH",
            "SOURCE_AUTHORIZATION_INACTIVE",
            "EXPLICIT_ANNOTATION_REVIEW_REQUIRED",
            "REVIEWED_OPERATOR_SNAPSHOT_REQUIRED",
        }
    )
    policies = getattr(contract, "sample_annotation_requirements", None) or {}
    members = []
    for sample in manifest.samples:
        asset = assets.get(sample.sample_id)
        requirement = policies.get(sample.sample_id, "UNKNOWN")
        requirement_known = requirement in {"REQUIRED", "OPTIONAL", "NOT_APPLICABLE"}
        if not requirement_known:
            requirement = "UNKNOWN"
            blockers.add("SAMPLE_ANNOTATION_REQUIREMENT_UNKNOWN")
        mask_available = None
        mask_verified = False
        if asset is not None:
            if sample.annotation_path is None:
                mask_verified = (
                    asset.mask_relative_path is None and asset.mask_sha256 is None
                )
                mask_available = False if mask_verified else None
            else:
                mask_verified = (
                    asset.mask_relative_path == f"batch/{sample.annotation_path}"
                    and isinstance(asset.mask_sha256, str)
                    and re.fullmatch(r"[0-9a-f]{64}", asset.mask_sha256) is not None
                )
                mask_available = True if mask_verified else None
        if not mask_verified:
            blockers.add("MASK_BINDING_UNVERIFIED")
        matched = sorted(
            references.get(sample.sample_id, []),
            key=lambda item: (item["finding_id"], item["finding_sha256"]),
        )
        if unmapped:
            state = "UNVERIFIED_FINDING_IDENTITY"
        elif failed_tool:
            state = "UNVERIFIED_TOOL_FAILURE"
        elif (
            not member_identity_valid
            or not complete_tools
            or not decision_valid
            or uncertain_input
            or not requirement_known
            or not mask_verified
        ):
            state = "UNVERIFIED"
        elif matched:
            state = "NEEDS_ATTENTION"
        elif not mask_available:
            state = "MASK_REQUIRED_FOR_REFERENCE_TRAINER"
        elif decision != "PASS":
            state = "BLOCKED_BY_BATCH"
        elif preflight["eligibility"] == "READY_FOR_OFFLINE_HANDOFF":
            state = "GATE_ELIGIBLE_NOT_TRAINING_APPROVED"
        else:
            state = "UNVERIFIED"
            blockers.add("PREFLIGHT_NOT_ELIGIBLE")
        members.append(
            {
                "sample_id": sample.sample_id,
                "split": sample.split,
                "category": sample.category,
                "annotation_requirement": requirement,
                "mask_available": mask_available,
                "readiness_state": state,
                "finding_refs": matched,
            }
        )
    return {
        "members": members,
        "global_findings": sorted(
            global_findings,
            key=lambda item: (item["finding_id"], item["finding_sha256"]),
        ),
        "unmapped_finding_refs": sorted(
            unmapped, key=lambda item: (item["finding_id"], item["finding_sha256"])
        ),
        "blockers": sorted(blockers),
    }


def _same_task(task, candidate) -> bool:
    return all(
        getattr(task, key) == getattr(candidate, key)
        for key in ("task_id", "project_id", "workspace_id")
    )


def learning_readiness(product, actor: str, task_id: str) -> dict:
    """Project accessible frozen Gate evidence without granting training rights.

    NotFoundError propagates for authorization failures, including a membership
    change during reads. Other evidence failures become sealed UNVERIFIED states
    with controlled reason codes, never filesystem paths or exception text.
    """
    task = product.store.get_task(actor, task_id)
    result = {
        "schema_version": "visiondata-gate.learning-readiness.v1",
        "task_id": task.task_id,
        "project_id": task.project_id,
        "workspace_id": task.workspace_id,
        "projection_status": "UNVERIFIED",
        "preflight_receipt_sha256": None,
        "preflight_eligibility": "UNVERIFIED",
        "blockers": [],
        "members": [],
        "global_findings": [],
        "unmapped_finding_refs": [],
        "training_authorized": False,
        "production_release_allowed": False,
        "annotation_review_basis": "OPERATOR_ATTESTATION_NOT_INDEPENDENT_TRUTH",
        "required_dataset_validation": [
            "GROUP_DECLARATIONS",
            "BINARY_MASK_VALUES",
            "TRAIN_VAL_TEST_COVERAGE",
            "GROUP_AND_PIXEL_SPLIT_ISOLATION",
            "IMAGE_MASK_SHAPES_AND_RESOURCE_LIMITS",
        ],
        "claim_boundary": (
            "This projects frozen Gate evidence, not good/bad data, independent label truth, "
            "model accuracy or training approval. A missing mask is a reference-trainer "
            "requirement, not a defect finding. Group declarations, binary masks and full "
            "train/val/test membership still require freeze_dataset validation."
        ),
    }
    try:
        preflight = compute_preflight(product, actor, task_id)
        if not (
            isinstance(preflight, dict)
            and isinstance(preflight.get("receipt_sha256"), str)
            and hmac.compare_digest(
                preflight["receipt_sha256"], _seal(preflight)["receipt_sha256"]
            )
            and all(
                preflight.get(key) == getattr(task, key)
                for key in ("task_id", "project_id", "workspace_id")
            )
            and preflight.get("eligibility") in {"HOLD", "READY_FOR_OFFLINE_HANDOFF"}
        ):
            raise ValueError("unverified preflight binding")
        result.update(
            preflight_receipt_sha256=preflight["receipt_sha256"],
            preflight_eligibility=preflight["eligibility"],
            blockers=_safe_blockers(preflight["blockers"]),
        )
    except NotFoundError:
        raise
    except (OSError, RuntimeError, ValueError, KeyError, TypeError):
        product.store.get_task(actor, task_id)
        result["blockers"] = ["PREFLIGHT_UNAVAILABLE"]
        return _seal(result)
    if task.execution_status is not TaskExecutionStatus.COMPLETED:
        result["blockers"] = sorted(set(result["blockers"]) | {"TASK_NOT_COMPLETED"})
        return _seal(result)
    try:
        context_task, _batch_root, manifest, contract, gate = (
            product._annotation_context(actor, task_id)
        )
        visual_task, _source_root, snapshot, _profile = (
            product._operator_snapshot_visual_context(actor, task_id)
        )
        if not (
            _same_task(task, context_task)
            and _same_task(task, visual_task)
            and snapshot.project_id == task.project_id
            and snapshot.workspace_id == task.workspace_id
        ):
            raise ValueError("context identity mismatch")
        if preflight["eligibility"] == "READY_FOR_OFFLINE_HANDOFF":
            binding = preflight["binding"]
            if binding["snapshot_receipt_sha256"] != snapshot.receipt_sha256 or binding[
                "gate_result_sha256"
            ] != _sha(gate.model_dump(mode="json")):
                raise ValueError("preflight evidence changed")
        projected = _project_members(manifest, contract, gate, snapshot, preflight)
        product.store.get_task(actor, task_id)
        result.update(projected)
        result["projection_status"] = (
            "UNVERIFIED"
            if not result["members"]
            or any(
                item["readiness_state"].startswith("UNVERIFIED")
                for item in result["members"]
            )
            else "VERIFIED"
        )
        return _seal(result)
    except NotFoundError:
        raise
    except (OSError, RuntimeError, ValueError, KeyError, TypeError, AttributeError):
        product.store.get_task(actor, task_id)
        result["blockers"] = sorted(
            set(result["blockers"]) | {"FROZEN_CONTEXT_UNAVAILABLE"}
        )
        return _seal(result)


__all__ = ["learning_readiness"]
