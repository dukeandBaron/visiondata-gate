"""Bind a current, entirely qualified data pool to explicit detection labels.

The producer is queried on every use. This module accepts no filesystem paths,
does not derive subsets, and never turns binary masks into detector labels.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import sqlite3
from datetime import UTC, datetime
from pathlib import Path

from PIL import Image

from .audit_envelope import canonical_jcs_bytes
from .compute_handoff import REQUIRED_TOOLS
from .learning_detection_dataset import DetectionDatasetManifest, manifest_sha256
from .local_model_registry import VisionModelError
from .operator_workspace import OperatorImageStore
from .task_store import NotFoundError

_BINDING_SCHEMA = "visiondata-gate.pool-detection-binding.v1"
_FRAME = {
    "schema_version": "visiondata-gate.operator-detection-frame.v1",
    "input_coordinates": "normalized_xywh",
    "input_origin": "top_left",
    "output_coordinates": "normalized_center_xywh",
    "image_frame": "frozen_original_width_height",
    "mask_conversion": False,
}


def _sha(value: object) -> str:
    return hashlib.sha256(canonical_jcs_bytes(value)).hexdigest()


def _need(condition: bool, code: str) -> None:
    if not condition:
        raise VisionModelError(code)


def _sealed(value: dict) -> dict:
    stable = {key: item for key, item in value.items() if key != "receipt_sha256"}
    return stable | {"receipt_sha256": _sha(stable)}


def _verify_seal(value: dict) -> None:
    _need(isinstance(value, dict), "POOL_RESPONSE_INVALID")
    digest = value.get("receipt_sha256")
    _need(
        isinstance(digest, str)
        and hmac.compare_digest(digest, _sealed(value)["receipt_sha256"]),
        "POOL_RECEIPT_MISMATCH",
    )


def _fresh_context(product, actor: str, project: str, request: dict):
    from .data_pool import load_fresh_data_pool_context

    context = load_fresh_data_pool_context(
        product,
        actor,
        request["pool_id"],
        version_id=request["version_id"],
        require_current=True,
        require_all_qualified=True,
        require_gate_pass=True,
    )
    pool, version = context.pool, context.version
    _verify_seal(pool)
    _verify_seal(version)
    _need(
        pool["project_id"] == project
        and pool["pool_id"] == request["pool_id"]
        and pool["receipt_sha256"] == request["expected_pool_receipt_sha256"]
        and pool["current_version_id"] == request["version_id"]
        and version["version_id"] == request["version_id"]
        and version["pool_id"] == pool["pool_id"]
        and version["receipt_sha256"] == request["expected_version_receipt_sha256"],
        "POOL_VERSION_BINDING_MISMATCH",
    )
    return context


def _build_input(product, actor: str, project: str, request: dict):
    product.store.get_project(actor, project)
    _need(
        request.get("operator_attests_data_authorized") is True,
        "POOL_DATA_AUTHORIZATION_REQUIRED",
    )
    context = _fresh_context(product, actor, project, request)
    pool, version = context.pool, context.version
    task_id = pool["current_task_id"]
    task, source_root, snapshot, profile_sha = (
        product._operator_snapshot_visual_context(actor, task_id)
    )
    context_task, source_manifest, gate = context.task, context.manifest, context.gate
    _need(
        task.task_id == context_task.task_id == version["source_task_id"]
        and task.project_id == context_task.project_id == snapshot.project_id == project
        and version["project_id"] == project
        and task.workspace_id == snapshot.workspace_id == pool["workspace_id"]
        and version["workspace_id"] == task.workspace_id
        and task.source_id == pool["current_source_id"] == version["source_id"]
        and snapshot.snapshot_id
        == pool["current_snapshot_id"]
        == version["snapshot_id"]
        and snapshot.receipt_sha256 == version["snapshot_receipt_sha256"]
        and snapshot.batch_manifest_sha256 == version["batch_manifest_sha256"]
        and snapshot.batch_contract_sha256 == version["batch_contract_sha256"]
        and context.source_root == source_root
        and context.snapshot == snapshot,
        "POOL_SOURCE_BINDING_MISMATCH",
    )
    _need(
        getattr(gate.decision, "value", gate.decision) == "PASS"
        and gate.findings == []
        and all(
            trace.status == "ok" and trace.error is None for trace in gate.tool_trace
        )
        and REQUIRED_TOOLS.issubset({trace.tool for trace in gate.tool_trace})
        and gate.input_sha256 == snapshot.batch_digest_sha256
        and _sha(gate.model_dump(mode="json")) == version["gate_result_sha256"],
        "POOL_FULL_GATE_PASS_REQUIRED",
    )
    readiness = context.readiness
    _verify_seal(readiness)
    _need(
        readiness.get("projection_status") == "VERIFIED"
        and readiness.get("task_id") == task_id
        and readiness.get("project_id") == project
        and readiness.get("workspace_id") == task.workspace_id
        and readiness.get("preflight_eligibility") == "READY_FOR_OFFLINE_HANDOFF"
        and readiness.get("blockers") == []
        and readiness.get("global_findings") == []
        and readiness.get("unmapped_finding_refs") == []
        and readiness["receipt_sha256"] == version["readiness_receipt_sha256"],
        "POOL_READINESS_HOLD",
    )
    assets = {asset.asset_id: asset for asset in snapshot.assets}
    samples = {sample.sample_id: sample for sample in source_manifest.samples}
    members = {member["sample_id"]: member for member in version["members"]}
    prepared = {member["sample_id"]: member for member in readiness["members"]}
    _need(
        len(members) == len(version["members"]) == version["qualified_count"]
        and len(samples) == len(source_manifest.samples)
        and set(assets) == set(samples) == set(members) == set(prepared)
        and set(request["groups"]) == set(samples),
        "POOL_EXACT_MEMBERSHIP_REQUIRED",
    )
    normal_ids = request.get("normal_sample_ids", [])
    _need(
        isinstance(normal_ids, list)
        and len(normal_ids) == len(set(normal_ids))
        and set(normal_ids).issubset(samples),
        "POOL_NORMAL_ATTESTATION_INVALID",
    )
    class_names = request["class_names"]
    _need(
        isinstance(class_names, list)
        and class_names
        and all(isinstance(name, str) for name in class_names)
        and len(set(class_names)) == len(class_names),
        "POOL_CLASS_MAPPING_INVALID",
    )
    review = version["human_review"]
    _need(review.get("operator_attests_reviewed") is True, "POOL_REVIEW_REQUIRED")
    requirements = snapshot.acceptance_requirements
    _need(requirements is not None, "POOL_EXPLICIT_SNAPSHOT_REVIEW_REQUIRED")
    _need(
        set(class_names) == set(requirements.category_vocabulary),
        "POOL_FROZEN_CLASS_VOCABULARY_MISMATCH",
    )
    policies = {entry.asset_id: entry for entry in requirements.samples}
    _need(set(policies) == set(samples), "POOL_EXACT_REVIEW_REQUIRED")
    operator_root = product.product_root / "operator_workspace"
    _need(operator_root.is_dir(), "POOL_LIVE_STORE_UNAVAILABLE")
    operator = OperatorImageStore(operator_root)
    detection_samples, annotation_bindings = [], []
    observed_normals = set()
    for sample_id in sorted(samples):
        asset, sample = assets[sample_id], samples[sample_id]
        member, ready = members[sample_id], prepared[sample_id]
        _need(
            member.get("disposition") == "QUALIFIED_CANDIDATE"
            and member.get("repair_action") == "NONE"
            and member.get("repair_result") == "NOT_APPLICABLE"
            and member.get("finding_refs") == []
            and member.get("repair_cause_codes") == []
            and ready.get("finding_refs") == []
            and member.get("readiness_state") == ready.get("readiness_state")
            and ready.get("readiness_state")
            in {
                "GATE_ELIGIBLE_NOT_TRAINING_APPROVED",
                "MASK_REQUIRED_FOR_REFERENCE_TRAINER",
            },
            "POOL_MEMBER_NOT_QUALIFIED",
        )
        _need(
            member["split"] == ready["split"] == sample.split
            and member["category"] == ready["category"] == sample.category
            and member["source_task_id"] == task_id
            and member["asset_sha256"] == asset.source_sha256
            and member["annotation_revision"] == asset.annotation_revision
            and member["annotation_sha256"] == asset.annotation_document_sha256
            and member["annotation_requirement"]
            == policies[sample_id].annotation_requirement
            and asset.source_relative_path == "batch/" + sample.relative_path,
            "POOL_MEMBER_FRAME_MISMATCH",
        )
        with Image.open(source_root / asset.source_relative_path) as image:
            _need(
                image.size == (asset.width, asset.height)
                and image.getexif().get(274, 1) == 1
                and getattr(image, "n_frames", 1) == 1,
                "POOL_IMAGE_FRAME_UNSUPPORTED",
            )
        live = operator.get_annotations(
            snapshot.actor_id, snapshot.workspace_id, sample_id
        )
        frozen_review = policies[sample_id].human_review
        _need(
            live.asset_id == sample_id
            and live.asset_sha256 == asset.source_sha256
            and live.revision == asset.annotation_revision
            and live.document_sha256 == asset.annotation_document_sha256
            and len(live.annotations) == asset.annotation_count
            and frozen_review is not None
            and frozen_review.operator_attests_reviewed is True
            and frozen_review.expected_asset_sha256 == asset.source_sha256
            and frozen_review.expected_annotation_revision == live.revision
            and frozen_review.expected_annotation_sha256 == live.document_sha256,
            "POOL_LIVE_ANNOTATION_DRIFT",
        )
        boxes = []
        for box in live.annotations:
            _need(box.label in class_names, "POOL_CLASS_MAPPING_INCOMPLETE")
            boxes.append(
                {
                    "class_id": class_names.index(box.label),
                    "x_center": box.x + box.width / 2,
                    "y_center": box.y + box.height / 2,
                    "width": box.width,
                    "height": box.height,
                }
            )
        if not boxes:
            observed_normals.add(sample_id)
            _need(
                policies[sample_id].annotation_requirement
                in {"OPTIONAL", "NOT_APPLICABLE"},
                "POOL_NORMAL_REVIEW_REQUIRED",
            )
        detection_samples.append(
            {
                "sample_id": sample_id,
                "image_path": asset.source_relative_path,
                "image_sha256": asset.source_sha256,
                "split": sample.split,
                "group_id": request["groups"][sample_id],
                "annotation_revision": live.revision,
                "boxes": boxes,
                "reviewer_name": review["reviewer_name"],
                "reviewed": True,
                "normal_attested": sample_id in normal_ids,
            }
        )
        annotation_bindings.append(
            {
                "sample_id": sample_id,
                "source_sha256": asset.source_sha256,
                "annotation_revision": live.revision,
                "annotation_document_sha256": live.document_sha256,
                "width": asset.width,
                "height": asset.height,
            }
        )
    _need(observed_normals == set(normal_ids), "POOL_NORMAL_ATTESTATION_REQUIRED")
    manifest = DetectionDatasetManifest.model_validate(
        {
            "schema_version": "visiondata-gate.detection-dataset.v1",
            "class_names": class_names,
            "source_version": version["version_id"],
            "samples": detection_samples,
        }
    ).model_dump(mode="json")
    product.store.get_project(actor, project)
    current = _fresh_context(product, actor, project, request)
    _need(
        current.pool == pool
        and current.version == version
        and current.readiness == readiness
        and current.snapshot == snapshot
        and current.gate == gate,
        "POOL_CHANGED_DURING_EXPORT",
    )
    binding = _sealed(
        {
            "schema_version": _BINDING_SCHEMA,
            "project_id": project,
            "workspace_id": task.workspace_id,
            "task_id": task_id,
            "task_evidence_sha256": task.evidence_sha256,
            "source_id": task.source_id,
            "pool_id": pool["pool_id"],
            "version_id": version["version_id"],
            "pool_receipt_sha256": pool["receipt_sha256"],
            "version_receipt_sha256": version["receipt_sha256"],
            "snapshot_id": snapshot.snapshot_id,
            "snapshot_receipt_sha256": snapshot.receipt_sha256,
            "source_profile_sha256": profile_sha,
            "batch_manifest_sha256": snapshot.batch_manifest_sha256,
            "batch_contract_sha256": snapshot.batch_contract_sha256,
            "gate_result_sha256": version["gate_result_sha256"],
            "readiness_receipt_sha256": readiness["receipt_sha256"],
            "class_names": class_names,
            "class_mapping_sha256": _sha(class_names),
            "groups": dict(sorted(request["groups"].items())),
            "normal_sample_ids": sorted(normal_ids),
            "coordinate_frame": dict(_FRAME),
            "coordinate_frame_sha256": _sha(_FRAME),
            "annotation_bindings_sha256": _sha(annotation_bindings),
            "detection_manifest_sha256": manifest_sha256(manifest),
            "sample_count": len(detection_samples),
            "production_release_allowed": False,
            "label_truth_authority": False,
        }
    )
    return source_root, manifest, binding


def pool_detection_input(
    product, actor: str, project: str, request
) -> tuple[Path, dict, dict]:
    """Read one current full PASS pool into explicit, reviewed detector input."""
    product.store.get_project(actor, project)
    try:
        values = (
            request.model_dump(mode="json")
            if hasattr(request, "model_dump")
            else request
        )
        return _build_input(product, actor, project, values)
    except (NotFoundError, VisionModelError):
        raise
    except (
        OSError,
        RuntimeError,
        ValueError,
        KeyError,
        TypeError,
        AttributeError,
        ImportError,
    ):
        raise VisionModelError("POOL_BRIDGE_EVIDENCE_UNAVAILABLE") from None


def verify_pool_binding(product, actor: str, project: str, binding: dict) -> None:
    """Recheck membership, current producer and frozen/live labels before use."""
    product.store.get_project(actor, project)
    try:
        _verify_seal(binding)
        _need(
            binding["schema_version"] == _BINDING_SCHEMA
            and binding["project_id"] == project,
            "POOL_BINDING_INVALID",
        )
        request = {
            "pool_id": binding["pool_id"],
            "version_id": binding["version_id"],
            "expected_pool_receipt_sha256": binding["pool_receipt_sha256"],
            "expected_version_receipt_sha256": binding["version_receipt_sha256"],
            "class_names": binding["class_names"],
            "groups": binding["groups"],
            "normal_sample_ids": binding["normal_sample_ids"],
            "operator_attests_data_authorized": True,
        }
        _source, _manifest, current = pool_detection_input(
            product, actor, project, request
        )
        _need(current == binding, "POOL_BINDING_DRIFT")
    except (NotFoundError, VisionModelError):
        raise
    except (
        OSError,
        RuntimeError,
        ValueError,
        KeyError,
        TypeError,
        AttributeError,
        ImportError,
    ):
        raise VisionModelError("POOL_BINDING_UNAVAILABLE") from None


def verify_pool_binding_in_connection(
    connection: sqlite3.Connection, actor: str, project: str, binding: dict
) -> None:
    """Recheck authority and pool HEAD inside the caller's write transaction.

    Call after ``verify_pool_binding`` and before publishing the result. This
    performs SELECTs only: no connection, transaction, DDL, commit, or file reads.
    Frozen/live file verification remains the preceding full verifier's job.
    """
    from .identity_service import assert_active_in_connection

    _need(connection.in_transaction, "POOL_TRANSACTION_REQUIRED")
    assert_active_in_connection(connection, actor)
    try:
        _verify_seal(binding)
        _need(
            binding["schema_version"] == _BINDING_SCHEMA
            and binding["project_id"] == project,
            "POOL_BINDING_INVALID",
        )
        membership = connection.execute(
            "SELECT p.workspace_id FROM projects p "
            "JOIN workspace_members m ON p.workspace_id=m.workspace_id "
            "WHERE p.project_id=? AND m.user_id=?",
            (project, actor),
        ).fetchone()
        if membership is None:
            raise NotFoundError("visual pool unavailable")
        workspace = membership["workspace_id"]
        _need(binding["workspace_id"] == workspace, "POOL_PROJECT_BINDING_MISMATCH")
        pool_row = connection.execute(
            "SELECT current_task_id,workspace_id,project_id,record_json "
            "FROM governed_data_pools_v1 WHERE pool_id=?",
            (binding["pool_id"],),
        ).fetchone()
        version_row = connection.execute(
            "SELECT pool_id,source_task_id,record_json "
            "FROM governed_data_pool_versions_v1 WHERE version_id=?",
            (binding["version_id"],),
        ).fetchone()
        _need(
            pool_row is not None and version_row is not None, "POOL_RECORD_UNAVAILABLE"
        )
        pool, version = (
            json.loads(pool_row["record_json"]),
            json.loads(version_row["record_json"]),
        )
        _verify_seal(pool)
        _verify_seal(version)
        _need(
            pool_row["project_id"] == pool["project_id"] == project
            and pool_row["workspace_id"] == pool["workspace_id"] == workspace
            and pool_row["current_task_id"]
            == pool["current_task_id"]
            == binding["task_id"]
            and pool["pool_id"]
            == version_row["pool_id"]
            == version["pool_id"]
            == binding["pool_id"]
            and pool["current_version_id"]
            == version["version_id"]
            == binding["version_id"]
            and pool["current_source_id"]
            == version["source_id"]
            == binding["source_id"]
            and pool["current_snapshot_id"]
            == version["snapshot_id"]
            == binding["snapshot_id"]
            and version_row["source_task_id"]
            == version["source_task_id"]
            == binding["task_id"]
            and version["workspace_id"] == workspace
            and version["project_id"] == project
            and pool["receipt_sha256"] == binding["pool_receipt_sha256"]
            and version["receipt_sha256"] == binding["version_receipt_sha256"],
            "POOL_HEAD_CHANGED",
        )
        task = connection.execute(
            "SELECT workspace_id,project_id,source_id,source_kind,execution_status,"
            "initial_decision,evidence_sha256,error_code FROM agent_tasks WHERE task_id=?",
            (binding["task_id"],),
        ).fetchone()
        _need(
            task is not None
            and task["workspace_id"] == workspace
            and task["project_id"] == project
            and task["source_id"] == binding["source_id"]
            and task["source_kind"] == "local_authorized_directory"
            and task["execution_status"] == "COMPLETED"
            and task["initial_decision"] == "PASS"
            and task["error_code"] is None
            and isinstance(binding["task_evidence_sha256"], str)
            and task["evidence_sha256"] == binding["task_evidence_sha256"],
            "POOL_TASK_AUTHORITY_CHANGED",
        )
        source = connection.execute(
            "SELECT workspace_id,adapter_kind,source_archive_sha256,data_profile_json,"
            "status,authorization_valid_until,operator_attests_authorized_use,read_only "
            "FROM local_source_authorizations WHERE source_id=?",
            (binding["source_id"],),
        ).fetchone()
        _need(
            source is not None
            and source["workspace_id"] == workspace
            and source["adapter_kind"] == "operator_project_snapshot"
            and source["status"] == "active"
            and source["operator_attests_authorized_use"] == 1
            and source["read_only"] == 1
            and source["source_archive_sha256"] == binding["snapshot_receipt_sha256"],
            "POOL_SOURCE_AUTHORIZATION_INACTIVE",
        )
        if source["authorization_valid_until"]:
            valid_until = datetime.fromisoformat(
                source["authorization_valid_until"].replace("Z", "+00:00")
            )
            _need(
                valid_until.tzinfo is not None and valid_until > datetime.now(UTC),
                "POOL_SOURCE_AUTHORIZATION_EXPIRED",
            )
        profile = json.loads(source["data_profile_json"])
        _need(
            profile["profile_sha256"] == binding["source_profile_sha256"]
            and profile["operator_snapshot_receipt_sha256"]
            == binding["snapshot_receipt_sha256"]
            and profile["snapshot_id"] == binding["snapshot_id"]
            and profile["batch_manifest_sha256"] == binding["batch_manifest_sha256"]
            and profile["batch_contract_sha256"] == binding["batch_contract_sha256"],
            "POOL_SOURCE_PROFILE_CHANGED",
        )
    except (NotFoundError, VisionModelError):
        raise
    except (ValueError, TypeError, KeyError, sqlite3.DatabaseError):
        raise VisionModelError("POOL_TRANSACTION_BINDING_UNAVAILABLE") from None


__all__ = [
    "pool_detection_input",
    "verify_pool_binding",
    "verify_pool_binding_in_connection",
]
