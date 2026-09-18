"""Explicit human-only Normality followup with recoverable cross-store writes.

The SQL intent is committed before filesystem work. IDs are server-derived from
the actor/project/operation/key. GET reconciliation only observes complete
filesystem objects and seals their binding; it never creates an asset or order.
"""

from __future__ import annotations

import hashlib
import json
import warnings
from contextvars import ContextVar
from functools import wraps
from io import BytesIO
from pathlib import Path
from typing import Literal

from PIL import Image
from pydantic import Field

from .local_model_registry import (
    OPAQUE,
    SHA,
    LocalVisionModelService,
    VisionModelError,
    VisionRequest,
    _assert_registry_path,
    _now,
    _seal,
    _sha,
)
from .operator_workspace import CreateOperatorWorkOrderRequest, OperatorImageStore
from .task_store import NotFoundError


IMPORT_OPERATION = "import_normality_followup:"
ORDER_OPERATION = "create_normality_followup_work_order:"
GATES = {
    "issue_closed": False,
    "label_truth_authority": False,
    "training_ingestion_allowed": False,
    "production_release_allowed": False,
    "machine_write_permitted": False,
    "annotation_created": False,
}

_intent_started = ContextVar("normality_followup_intent_started", default=False)


class FollowupWriteOutcomeUnknown(RuntimeError):
    """A durable intent exists: failure cannot establish absence of side effects."""


def _write_boundary(function):
    @wraps(function)
    def wrapped(*args, **kwargs):
        token = _intent_started.set(False)
        try:
            return function(*args, **kwargs)
        except Exception:
            if _intent_started.get() and not kwargs.get("_recover_only", False):
                raise FollowupWriteOutcomeUnknown(
                    "reconcile the original key"
                ) from None
            raise
        finally:
            _intent_started.reset(token)

    return wrapped


class FollowupEvidence(VisionRequest):
    expected_feedback_sha256: str = Field(pattern=SHA)
    expected_inference_sha256: str = Field(pattern=SHA)
    expected_asset_sha256: str = Field(pattern=SHA)
    expected_image_sha256: str = Field(pattern=SHA)
    operator_attests_no_label_or_training_authority: Literal[True]


class ImportNormalityFollowup(FollowupEvidence):
    operator_attests_import_authorized: Literal[True]


class CreateNormalityFollowupWorkOrder(FollowupEvidence):
    import_id: str = Field(pattern=OPAQUE)
    expected_import_sha256: str = Field(pattern=SHA)
    annotation_id: str = Field(min_length=1, max_length=96)
    expected_annotation_revision: int = Field(strict=True, ge=1)
    expected_annotation_document_sha256: str = Field(pattern=SHA)
    assignee: str = Field(min_length=1, max_length=120)
    operator_attests_create_work_order: Literal[True]
    operator_attests_reviewed_evidence: Literal[True]


class NormalityFollowupService(LocalVisionModelService):
    def __init__(self, product, operator_store: OperatorImageStore):
        super().__init__(product)
        self.operator_store = operator_store

    def _authorize(self, actor, project):
        super()._authorize(actor, project)
        with self.product.store._connection(immediate=True) as conn:
            conn.execute(
                "CREATE TABLE IF NOT EXISTS normality_followup_intents ("
                "project_id TEXT NOT NULL, actor TEXT NOT NULL, operation TEXT NOT NULL, "
                "request_key TEXT NOT NULL, request_sha TEXT NOT NULL, body TEXT NOT NULL, "
                "PRIMARY KEY(project_id,actor,operation,request_key))"
            )

    def _chain(self, actor, project, feedback_id, request=None):
        self._authorize(actor, project)
        workspace = self.product.store.get_project(actor, project).workspace_id
        with self.product.store._connection() as conn:
            feedback, _ = self._read(conn, project, feedback_id, "normality_feedback")
            inference, _ = self._normality_inference_record(
                conn, project, feedback["inference_id"]
            )
            asset, private = self._read(
                conn, project, inference["asset_id"], "inference_asset"
            )
        if (
            feedback.get("classification")
            not in {"NEEDS_LABEL_REVIEW", "LIKELY_FALSE_POSITIVE"}
            or feedback.get("status") != "RECORDED_FOR_HUMAN_FOLLOWUP"
            or feedback.get("inference_sha256") != inference["receipt_sha256"]
            or feedback.get("asset_id") != asset["asset_id"]
            or feedback.get("image_sha256") != asset["image_sha256"]
            or inference.get("image_sha256") != asset["image_sha256"]
            or asset.get("storage_scope") != "REGISTRY_OWNED_CONTENT_ADDRESSED"
            or asset.get("status") != "FROZEN_LOCAL_INFERENCE_ASSET"
            or any(
                value.get("project_id") != project
                for value in (feedback, inference, asset)
            )
        ):
            raise VisionModelError("FOLLOWUP_EVIDENCE_CHAIN_HOLD")
        if request is not None and (
            request.expected_feedback_sha256 != feedback["receipt_sha256"]
            or request.expected_inference_sha256 != inference["receipt_sha256"]
            or request.expected_asset_sha256 != asset["receipt_sha256"]
            or request.expected_image_sha256 != asset["image_sha256"]
        ):
            raise VisionModelError("FOLLOWUP_EVIDENCE_CHANGED")
        digest = asset["image_sha256"]
        expected = self.root / "cas" / "sha256" / digest[:2] / digest
        candidate = Path(private["cas_path"])
        if candidate.absolute() != expected.absolute():
            raise VisionModelError("FOLLOWUP_CAS_PATH_HOLD")
        source = _assert_registry_path(self.root, candidate)
        if (
            source.stat().st_size != asset["image_bytes"]
            or source.stat().st_size > 32 * 1024 * 1024
        ):
            raise VisionModelError("FOLLOWUP_SOURCE_SIZE_HOLD")
        raw = source.read_bytes()
        if hashlib.sha256(raw).hexdigest() != digest:
            raise VisionModelError("FOLLOWUP_SOURCE_CHANGED")
        with warnings.catch_warnings():
            warnings.simplefilter("error", Image.DecompressionBombWarning)
            with Image.open(BytesIO(raw)) as verification:
                verification.verify()
            with Image.open(BytesIO(raw)) as decoded:
                if decoded.getexif().get(274, 1) != 1:
                    raise VisionModelError(
                        "FOLLOWUP_EXIF_HOLD_NORMALIZE_NEW_VERSION_AND_RERUN"
                    )
                if decoded.size != (asset["image_width"], asset["image_height"]):
                    raise VisionModelError("FOLLOWUP_COORDINATE_FRAME_HOLD")
                if (
                    decoded.width * decoded.height > 50_000_000
                    or getattr(decoded, "n_frames", 1) != 1
                ):
                    raise VisionModelError("FOLLOWUP_IMAGE_FRAME_HOLD")
        lineage = {
            "project_id": project,
            "workspace_id": workspace,
            "feedback_id": feedback_id,
            "feedback_sha256": feedback["receipt_sha256"],
            "inference_id": inference["inference_id"],
            "inference_sha256": inference["receipt_sha256"],
            "vision_asset_id": asset["asset_id"],
            "vision_asset_sha256": asset["receipt_sha256"],
            "image_sha256": digest,
            "image_width": asset["image_width"],
            "image_height": asset["image_height"],
            "coordinate_frame": "DECODED_PIXELS_EXIF_IDENTITY",
        }
        return lineage, raw

    def _intent(self, actor, project, operation, request, lineage, *, recover_only):
        request_body = request.model_dump(mode="json")
        request_sha = _sha(request_body)
        with self.product.store._connection(immediate=True) as conn:
            self._membership(conn, actor, project)
            row = conn.execute(
                "SELECT request_sha,body FROM normality_followup_intents WHERE project_id=? AND actor=? AND operation=? AND request_key=?",
                (project, actor, operation, request.request_key),
            ).fetchone()
            if row:
                if row[0] != request_sha:
                    raise VisionModelError("FOLLOWUP_IDEMPOTENCY_CONFLICT")
                intent = json.loads(row[1])
                if (
                    intent != _seal(intent)
                    or intent["request"] != request_body
                    or intent["lineage"] != lineage
                ):
                    raise VisionModelError("FOLLOWUP_INTENT_CHANGED")
                _intent_started.set(True)
                return intent
            if recover_only:
                raise NotFoundError("followup operation unavailable")
            token = _sha([project, actor, operation, request.request_key])
            intent = _seal(
                {
                    "request": request_body,
                    "lineage": lineage,
                    "token": token,
                    "created_at": _now(),
                    "created_by": actor,
                }
            )
            conn.execute(
                "INSERT INTO normality_followup_intents VALUES (?,?,?,?,?,?)",
                (
                    project,
                    actor,
                    operation,
                    request.request_key,
                    request_sha,
                    json.dumps(intent),
                ),
            )
        _intent_started.set(True)
        return intent

    def _observe_prior_intent(self, actor, project, operation, request):
        """Prior filesystem success stays UNKNOWN even if later input checks fail."""
        with self.product.store._connection() as conn:
            row = conn.execute(
                "SELECT request_sha FROM normality_followup_intents WHERE project_id=? AND actor=? AND operation=? AND request_key=?",
                (project, actor, operation, request.request_key),
            ).fetchone()
        if row is not None:
            if row[0] != _sha(request.model_dump(mode="json")):
                raise VisionModelError("FOLLOWUP_IDEMPOTENCY_CONFLICT")
            _intent_started.set(True)

    def _base_receipt(self, intent, kind, request):
        identifier = f"normality_followup_{kind}_{intent['token'][:32]}"
        return (
            intent["lineage"]
            | GATES
            | {
                "schema_version": f"visiondata-gate.normality-followup-{kind.replace('_', '-')}.v1",
                "resource_id": identifier,
                "created_at": intent["created_at"],
                "created_by": intent["created_by"],
                "reviewer_identity": request.reviewer_identity,
                "note": request.note,
            }
        )

    def _finish(self, actor, project, operation, request, value, kind):
        with self.product.store._connection(immediate=True) as conn:
            self._membership(conn, actor, project)
            result = self._put(conn, value, kind)
            self._remember(conn, actor, project, operation, request, result)
        return result

    def _safe_asset(self, actor, workspace, asset_id):
        root = self.operator_store.root
        lexical = root / actor / workspace / asset_id
        _assert_registry_path(root, lexical)
        if lexical.exists():
            for path in lexical.rglob("*"):
                _assert_registry_path(root, path)
        return lexical

    def _verify_import_live(self, actor, project, imported, lineage):
        if (
            imported.get("created_by") != actor
            or imported.get("project_id") != project
            or any(imported.get(key) != value for key, value in lineage.items())
        ):
            raise NotFoundError("followup import unavailable")
        asset_id, workspace = imported["operator_asset_id"], imported["workspace_id"]
        self._safe_asset(actor, workspace, asset_id)
        asset, _ = self.operator_store._asset(actor, workspace, asset_id)
        self.operator_store.file_variant(actor, workspace, asset_id, "source")
        self.operator_store.file_variant(actor, workspace, asset_id, "preview")
        if (
            asset.project_id != project
            or asset.source_sha256 != imported["image_sha256"]
            or imported["operator_source_sha256"] != asset.source_sha256
            or (asset.width, asset.height)
            != (imported["image_width"], imported["image_height"])
        ):
            raise VisionModelError("FOLLOWUP_OPERATOR_ASSET_CHANGED")
        return asset

    @_write_boundary
    def import_feedback(
        self, actor, project, feedback_id, request, *, _recover_only=False
    ):
        request = ImportNormalityFollowup.model_validate(
            request.model_dump(mode="json")
        )
        operation = IMPORT_OPERATION + feedback_id
        with self._operation(actor, project, operation, request) as existing:
            self._observe_prior_intent(actor, project, operation, request)
            lineage, raw = self._chain(actor, project, feedback_id, request)
            if existing:
                self._verify_import_live(actor, project, existing, lineage)
                return existing
            intent = self._intent(
                actor, project, operation, request, lineage, recover_only=_recover_only
            )
            token, workspace = intent["token"], lineage["workspace_id"]
            asset_id = self.operator_store._followup_id("img", token)
            root = self._safe_asset(actor, workspace, asset_id)
            if _recover_only:
                if not (root / "asset.json").is_file():
                    raise NotFoundError("followup import not yet completed")
                asset, _ = self.operator_store._asset(actor, workspace, asset_id)
            else:
                with Image.open(BytesIO(raw)) as decoded:
                    extension = {"PNG": ".png", "JPEG": ".jpg", "BMP": ".bmp"}.get(
                        decoded.format
                    )
                if extension is None:
                    raise VisionModelError("FOLLOWUP_IMAGE_FORMAT_HOLD")
                asset = self.operator_store.add_image(
                    actor,
                    workspace,
                    project_id=project,
                    filename=f"normality-{lineage['image_sha256'][:16]}{extension}",
                    data=raw,
                    _idempotency_token=token,
                    _created_at=intent["created_at"],
                )
            value = self._base_receipt(intent, "import", request)
            value.update(
                import_id=value["resource_id"],
                operator_asset_id=asset.asset_id,
                operator_source_sha256=asset.source_sha256,
                status="ASSET_IMPORTED_AWAITING_HUMAN_ANNOTATION",
                work_order_created=False,
            )
            self._verify_import_live(actor, project, value, lineage)
            return self._finish(
                actor, project, operation, request, value, "normality_followup_import"
            )

    def _read_import(self, actor, project, feedback_id, import_id, lineage):
        with self.product.store._connection() as conn:
            imported, _ = self._read(
                conn, project, import_id, "normality_followup_import"
            )
        if imported["feedback_id"] != feedback_id:
            raise NotFoundError("followup import unavailable")
        self._verify_import_live(actor, project, imported, lineage)
        return imported

    def _annotations(self, actor, imported):
        return self.operator_store.get_annotations(
            actor, imported["workspace_id"], imported["operator_asset_id"]
        )

    def annotations(self, actor, project, feedback_id, import_id):
        lineage, _ = self._chain(actor, project, feedback_id)
        imported = self._read_import(actor, project, feedback_id, import_id, lineage)
        state = self._annotations(actor, imported)
        return _seal(
            GATES
            | state.model_dump(mode="json")
            | {
                "schema_version": "visiondata-gate.normality-followup-annotations.v1",
                "project_id": project,
                "feedback_id": feedback_id,
                "import_id": import_id,
                "workspace_id": imported["workspace_id"],
                "operator_asset_id": imported["operator_asset_id"],
            }
        )

    def _verify_order_live(self, actor, record):
        workspace, order_id = record["workspace_id"], record["work_order_id"]
        root = self.operator_store.root / actor / workspace / "work_orders" / order_id
        _assert_registry_path(self.operator_store.root, root)
        if root.exists():
            for path in root.rglob("*"):
                _assert_registry_path(self.operator_store.root, path)
        order = self.operator_store.get_work_order(actor, workspace, order_id)
        crop = root / "crop.jpg"
        if (
            order.status != "OPEN"
            or order.revision != 1
            or order.document_sha256 != record["work_order_document_sha256"]
            or order.crop_sha256 != record["crop_sha256"]
            or hashlib.sha256(crop.read_bytes()).hexdigest() != record["crop_sha256"]
            or order.asset_id != record["operator_asset_id"]
            or order.asset_sha256 != record["image_sha256"]
            or order.project_id != record["project_id"]
            or order.created_by != actor
            or order.annotation.source != "MANUAL"
            or order.annotation.annotation_id != record["annotation_id"]
            or order.annotation_revision != record["annotation_revision"]
        ):
            raise VisionModelError("FOLLOWUP_WORK_ORDER_READBACK_HOLD")
        return order

    @_write_boundary
    def create_work_order(
        self, actor, project, feedback_id, request, *, _recover_only=False
    ):
        request = CreateNormalityFollowupWorkOrder.model_validate(
            request.model_dump(mode="json")
        )
        operation = ORDER_OPERATION + feedback_id
        with self._operation(actor, project, operation, request) as existing:
            self._observe_prior_intent(actor, project, operation, request)
            lineage, _ = self._chain(actor, project, feedback_id, request)
            imported = self._read_import(
                actor, project, feedback_id, request.import_id, lineage
            )
            if imported["receipt_sha256"] != request.expected_import_sha256:
                raise VisionModelError("FOLLOWUP_IMPORT_CHANGED")
            if existing:
                self._verify_order_live(actor, existing)
                return existing
            annotation = self._annotations(actor, imported)
            selected = next(
                (
                    item
                    for item in annotation.annotations
                    if item.annotation_id == request.annotation_id
                ),
                None,
            )
            if (
                annotation.revision != request.expected_annotation_revision
                or annotation.document_sha256
                != request.expected_annotation_document_sha256
                or annotation.asset_sha256 != lineage["image_sha256"]
                or selected is None
                or selected.source != "MANUAL"
            ):
                raise VisionModelError("FOLLOWUP_CURRENT_MANUAL_ANNOTATION_REQUIRED")
            intent = self._intent(
                actor, project, operation, request, lineage, recover_only=_recover_only
            )
            token, workspace = intent["token"], lineage["workspace_id"]
            order_id = self.operator_store._followup_id("wo", token)
            order_root = (
                self.operator_store.root / actor / workspace / "work_orders" / order_id
            )
            _assert_registry_path(self.operator_store.root, order_root)
            if _recover_only:
                first = order_root / "revisions" / "rev_000001.json"
                _assert_registry_path(self.operator_store.root, first)
                if not first.is_file():
                    raise NotFoundError("followup work order not yet completed")
                order = self.operator_store.get_work_order(actor, workspace, order_id)
            else:
                order = self.operator_store.create_work_order(
                    actor,
                    workspace,
                    imported["operator_asset_id"],
                    CreateOperatorWorkOrderRequest(
                        annotation_id=request.annotation_id,
                        expected_annotation_revision=request.expected_annotation_revision,
                        assignee=request.assignee,
                        note=request.note,
                        operator_attests_reviewed_evidence=True,
                    ),
                    _idempotency_token=token,
                    _created_at=intent["created_at"],
                    _expected_annotation_sha256=request.expected_annotation_document_sha256,
                )
            if (
                order.annotation != selected
                or order.assignee != request.assignee
                or order.note != request.note
                or order.created_at != intent["created_at"]
                or order.operator_attests_reviewed_evidence is not True
            ):
                raise VisionModelError("FOLLOWUP_RECOVERED_ORDER_CHANGED")
            value = self._base_receipt(intent, "work_order", request)
            value.update(
                binding_id=value["resource_id"],
                import_id=imported["import_id"],
                import_sha256=imported["receipt_sha256"],
                operator_asset_id=imported["operator_asset_id"],
                operator_source_sha256=imported["operator_source_sha256"],
                annotation_id=request.annotation_id,
                annotation_revision=annotation.revision,
                annotation_document_sha256=annotation.document_sha256,
                work_order_id=order.work_order_id,
                work_order_document_sha256=order.document_sha256,
                crop_sha256=order.crop_sha256,
                assignee=order.assignee,
                status="OPEN",
                work_order_created=True,
            )
            self._verify_order_live(actor, value)
            return self._finish(
                actor,
                project,
                operation,
                request,
                value,
                "normality_followup_work_order",
            )

    def list_followup(self, actor, project, feedback_id):
        lineage, _ = self._chain(actor, project, feedback_id)
        imports, orders = [], []
        with self.product.store._connection() as conn:
            rows = conn.execute(
                "SELECT id FROM vision_records WHERE project_id=? AND kind IN (?,?) ORDER BY id",
                (project, "normality_followup_import", "normality_followup_work_order"),
            ).fetchall()
            values = [self._read(conn, project, row[0])[0] for row in rows]
        for value in values:
            if (
                value.get("created_by") != actor
                or value.get("feedback_id") != feedback_id
            ):
                continue
            if value["schema_version"].endswith("followup-import.v1"):
                self._verify_import_live(actor, project, value, lineage)
                imports.append(value)
            else:
                imported = self._read_import(
                    actor, project, feedback_id, value["import_id"], lineage
                )
                if imported["receipt_sha256"] != value["import_sha256"]:
                    raise VisionModelError("FOLLOWUP_IMPORT_BINDING_CHANGED")
                self._verify_order_live(actor, value)
                orders.append(value)
        return _seal(
            GATES
            | {
                "schema_version": "visiondata-gate.normality-followup-list.v1",
                "project_id": project,
                "feedback_id": feedback_id,
                "imports": imports,
                "work_orders": orders,
            }
        )

    def get_followup_operation(self, actor, project, operation, request_key):
        self._authorize(actor, project)
        if operation.startswith(IMPORT_OPERATION):
            request_type, execute, prefix = (
                ImportNormalityFollowup,
                self.import_feedback,
                IMPORT_OPERATION,
            )
        elif operation.startswith(ORDER_OPERATION):
            request_type, execute, prefix = (
                CreateNormalityFollowupWorkOrder,
                self.create_work_order,
                ORDER_OPERATION,
            )
        else:
            raise NotFoundError("followup operation unavailable")
        with self.product.store._connection() as conn:
            row = conn.execute(
                "SELECT body FROM normality_followup_intents WHERE project_id=? AND actor=? AND operation=? AND request_key=?",
                (project, actor, operation, request_key),
            ).fetchone()
        if row is None:
            raise NotFoundError("followup operation unavailable")
        intent = json.loads(row[0])
        if intent != _seal(intent):
            raise VisionModelError("FOLLOWUP_INTENT_CHANGED")
        request = request_type.model_validate(intent["request"])
        if request.request_key != request_key:
            raise VisionModelError("FOLLOWUP_INTENT_KEY_CHANGED")
        resource = execute(
            actor, project, operation[len(prefix) :], request, _recover_only=True
        )
        return _seal(
            {
                "schema_version": "visiondata-gate.vision-operation.v1",
                "project_id": project,
                "operation": operation,
                "request_key": request_key,
                "resource_id": resource["resource_id"],
                "resource": resource,
                "auto_replayed": False,
            }
        )
