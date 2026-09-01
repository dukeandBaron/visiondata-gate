"""Local-only image workspace used by the operator Web UI.

The store keeps original bytes, deterministic image metadata, previews, and
append-only annotation revisions under the product root.  It never calls an
external model or copies data outside the configured local workspace.
"""

from __future__ import annotations

import hashlib
import hmac
import math
import os
import re
import time
import uuid
import warnings
from datetime import UTC, datetime
from io import BytesIO
from pathlib import Path
from typing import Literal

import numpy as np
from PIL import Image, ImageOps, UnidentifiedImageError
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from .audit_envelope import canonical_jcs_bytes


MAX_UPLOAD_BYTES = 32 * 1024 * 1024
MAX_UPLOAD_FILES = 64
MAX_UPLOAD_BATCH_BYTES = 128 * 1024 * 1024
MAX_IMAGE_PIXELS = 50_000_000

_SAFE_SEGMENT = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,95}\Z")
_SUPPORTED_FORMATS: dict[str, tuple[str, str]] = {
    "BMP": ("image/bmp", ".bmp"),
    "JPEG": ("image/jpeg", ".jpg"),
    "PNG": ("image/png", ".png"),
    "TIFF": ("image/tiff", ".tif"),
    "WEBP": ("image/webp", ".webp"),
}


def _now() -> str:
    return datetime.now(UTC).isoformat(timespec="milliseconds")


class OperatorWorkspaceError(RuntimeError):
    """Typed, user-safe error raised by the local operator workspace."""

    def __init__(self, code: str, message: str, *, status_code: int = 400) -> None:
        self.code = code
        self.status_code = status_code
        super().__init__(message)


class ImageInspectionMetrics(BaseModel):
    model_config = ConfigDict(frozen=True)

    mean_luma: float
    contrast_std: float
    edge_energy: float
    black_clip_ratio: float
    white_clip_ratio: float
    sample_width: int
    sample_height: int


class OperatorImageAsset(BaseModel):
    model_config = ConfigDict(frozen=True)

    asset_id: str
    workspace_id: str
    project_id: str | None = None
    original_name: str
    format: str
    content_type: str
    byte_size: int
    width: int
    height: int
    mode: str
    source_sha256: str
    preview_sha256: str
    source_url: str
    preview_url: str
    duplicate_of_asset_id: str | None = None
    annotation_count: int = 0
    annotation_revision: int = 0
    inspection: ImageInspectionMetrics
    created_at: str
    local_only: Literal[True] = True
    external_transmission: Literal[False] = False


class OperatorImageUploadBatch(BaseModel):
    model_config = ConfigDict(frozen=True)

    workspace_id: str
    project_id: str | None = None
    uploaded_count: int
    assets: list[OperatorImageAsset]
    raw_images_transmitted: Literal[False] = False


class BoundingBoxAnnotation(BaseModel):
    model_config = ConfigDict(frozen=True)

    annotation_id: str = Field(min_length=1, max_length=96)
    label: str = Field(min_length=1, max_length=120)
    x: float = Field(ge=0.0, le=1.0)
    y: float = Field(ge=0.0, le=1.0)
    width: float = Field(gt=0.0, le=1.0)
    height: float = Field(gt=0.0, le=1.0)
    source: Literal["MANUAL", "IMPORTED"] = "MANUAL"

    @field_validator("label")
    @classmethod
    def normalize_label(cls, value: str) -> str:
        normalized = value.strip()
        if not normalized:
            raise ValueError("annotation label cannot be blank")
        return normalized

    @model_validator(mode="after")
    def remain_inside_image(self) -> BoundingBoxAnnotation:
        tolerance = 1e-9
        if self.x + self.width > 1.0 + tolerance:
            raise ValueError("annotation exceeds the image width")
        if self.y + self.height > 1.0 + tolerance:
            raise ValueError("annotation exceeds the image height")
        return self


class SaveAnnotationsRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    expected_revision: int = Field(ge=0)
    annotations: list[BoundingBoxAnnotation] = Field(max_length=500)

    @field_validator("annotations")
    @classmethod
    def annotation_ids_are_unique(
        cls, values: list[BoundingBoxAnnotation]
    ) -> list[BoundingBoxAnnotation]:
        identifiers = [item.annotation_id for item in values]
        if len(identifiers) != len(set(identifiers)):
            raise ValueError("annotation IDs must be unique")
        return values


class StoredAnnotationRevision(BaseModel):
    model_config = ConfigDict(frozen=True)

    schema_version: Literal[
        "visiondata-gate.operator-annotation-revision.v1",
        "visiondata-gate.operator-annotation-revision.v2",
    ] = "visiondata-gate.operator-annotation-revision.v1"
    asset_id: str
    asset_sha256: str
    revision: int = Field(ge=1)
    updated_at: str
    annotations: list[BoundingBoxAnnotation]
    previous_revision_sha256: str | None = Field(
        default=None, pattern=r"^[0-9a-f]{64}$"
    )
    revision_payload_sha256: str | None = Field(default=None, pattern=r"^[0-9a-f]{64}$")

    @model_validator(mode="after")
    def require_v2_chain_fields(self) -> StoredAnnotationRevision:
        if self.schema_version.endswith(".v2") and (
            self.previous_revision_sha256 is None
            or self.revision_payload_sha256 is None
        ):
            raise ValueError("v2 annotation revision requires chain and payload seals")
        return self


class OperatorAnnotationState(BaseModel):
    model_config = ConfigDict(frozen=True)

    asset_id: str
    asset_sha256: str
    revision: int = Field(ge=0)
    updated_at: str | None = None
    annotations: list[BoundingBoxAnnotation]
    document_sha256: str
    previous_revision_sha256: str | None = None
    revision_payload_sha256: str | None = None


class PixelBoundingBox(BaseModel):
    model_config = ConfigDict(frozen=True)

    x: int = Field(ge=0)
    y: int = Field(ge=0)
    width: int = Field(ge=1)
    height: int = Field(ge=1)


class CreateOperatorWorkOrderRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    annotation_id: str = Field(min_length=1, max_length=96)
    expected_annotation_revision: int = Field(ge=1)
    assignee: str = Field(default="Annotation Lead", min_length=1, max_length=120)
    note: str = Field(default="", max_length=1000)
    operator_attests_reviewed_evidence: Literal[True]

    @field_validator("assignee")
    @classmethod
    def normalize_work_order_assignee(cls, value: str) -> str:
        normalized = value.strip()
        if not normalized:
            raise ValueError("assignee cannot be blank")
        return normalized

    @field_validator("note")
    @classmethod
    def normalize_work_order_note(cls, value: str) -> str:
        return value.strip()


class UpdateOperatorWorkOrderRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    expected_revision: int = Field(ge=1)
    status: Literal["OPEN", "ACKNOWLEDGED", "IN_CAPA", "REJECTED", "CLOSED"]
    assignee: str = Field(min_length=1, max_length=120)
    note: str = Field(min_length=1, max_length=1000)
    operator_attests_reviewed_evidence: Literal[True]
    verification_annotation_revision: int | None = Field(default=None, ge=1)
    verification_annotation_sha256: str | None = Field(
        default=None, pattern=r"^[0-9a-f]{64}$"
    )

    @field_validator("assignee")
    @classmethod
    def normalize_work_order_update_assignee(cls, value: str) -> str:
        normalized = value.strip()
        if not normalized:
            raise ValueError("assignee cannot be blank")
        return normalized

    @field_validator("note")
    @classmethod
    def normalize_work_order_update_note(cls, value: str) -> str:
        normalized = value.strip()
        if not normalized:
            raise ValueError("note cannot be blank")
        return normalized

    @model_validator(mode="after")
    def validate_closure_evidence(self) -> UpdateOperatorWorkOrderRequest:
        evidence = (
            self.verification_annotation_revision,
            self.verification_annotation_sha256,
        )
        if self.status == "CLOSED" and any(value is None for value in evidence):
            raise ValueError(
                "CLOSED work orders require a bound verification annotation revision"
            )
        if self.status != "CLOSED" and any(value is not None for value in evidence):
            raise ValueError(
                "verification annotation evidence is only valid for CLOSED work orders"
            )
        return self


class StoredOperatorWorkOrderRevision(BaseModel):
    model_config = ConfigDict(frozen=True)

    work_order_id: str
    workspace_id: str
    project_id: str | None = None
    asset_id: str
    asset_sha256: str
    image_name: str
    annotation_revision: int = Field(ge=1)
    annotation: BoundingBoxAnnotation
    pixel_bbox: PixelBoundingBox
    crop_sha256: str
    revision: int = Field(ge=1)
    status: Literal["OPEN", "ACKNOWLEDGED", "IN_CAPA", "REJECTED", "CLOSED"]
    assignee: str
    note: str
    operator_attests_reviewed_evidence: bool = False
    verification_annotation_revision: int | None = Field(default=None, ge=1)
    verification_annotation_sha256: str | None = Field(
        default=None, pattern=r"^[0-9a-f]{64}$"
    )
    production_authority: Literal["human_only"] = "human_only"
    created_by: str
    created_at: str
    updated_by: str
    updated_at: str


class OperatorWorkOrderState(StoredOperatorWorkOrderRevision):
    model_config = ConfigDict(frozen=True)

    crop_url: str
    document_sha256: str


class OperatorAgentEvent(BaseModel):
    model_config = ConfigDict(frozen=True)

    sequence: int = Field(ge=1)
    stage: Literal["INTAKE", "TOOL", "KNOWLEDGE", "DELIVERY", "HUMAN_GATE"]
    actor: Literal["operator-agent", "deterministic-tool", "governance"]
    action: str = Field(min_length=1, max_length=120)
    status: Literal["COMPLETED", "WARNING", "WAITING"]
    summary: str = Field(min_length=1, max_length=1200)
    tool_name: str | None = Field(default=None, max_length=120)
    duration_ms: float = Field(default=0.0, ge=0.0)
    evidence_refs: list[str] = Field(default_factory=list)
    receipt_sha256: str = Field(min_length=64, max_length=64)


class OperatorKnowledgeHit(BaseModel):
    model_config = ConfigDict(frozen=True)

    card_id: str = Field(min_length=1, max_length=120)
    title: str = Field(min_length=1, max_length=200)
    excerpt: str = Field(min_length=1, max_length=800)
    source: str = Field(min_length=1, max_length=200)
    permission_scope: Literal["local-read-only"] = "local-read-only"
    evidence_ref: str = Field(min_length=1, max_length=300)


class OperatorAgentRecommendation(BaseModel):
    model_config = ConfigDict(frozen=True)

    code: str = Field(min_length=1, max_length=120)
    severity: Literal["LOW", "MEDIUM", "HIGH"]
    title: str = Field(min_length=1, max_length=200)
    summary: str = Field(min_length=1, max_length=1200)
    next_action: str = Field(min_length=1, max_length=600)
    evidence_refs: list[str] = Field(default_factory=list)
    decision_authority: Literal["none"] = "none"


class OperatorHumanGate(BaseModel):
    model_config = ConfigDict(frozen=True)

    required: Literal[True] = True
    status: Literal["AWAITING_HUMAN_REVIEW"] = "AWAITING_HUMAN_REVIEW"
    required_action: str = Field(min_length=1, max_length=600)
    production_authority: Literal["human_only"] = "human_only"


class StoredOperatorAnalysisRun(BaseModel):
    model_config = ConfigDict(frozen=True)

    schema_version: Literal["visiondata-gate.operator-analysis-run.v1"] = (
        "visiondata-gate.operator-analysis-run.v1"
    )
    analysis_run_id: str
    workspace_id: str
    project_id: str | None = None
    asset_id: str
    asset_sha256: str = Field(min_length=64, max_length=64)
    annotation_revision: int = Field(ge=0)
    annotation_document_sha256: str = Field(min_length=64, max_length=64)
    started_at: str
    completed_at: str
    goal: str
    intent: str
    backend: Literal["local-deterministic"] = "local-deterministic"
    backend_connected: Literal[True] = True
    fallback_used: Literal[False] = False
    execution_status: Literal["COMPLETED"] = "COMPLETED"
    workflow_status: Literal["AWAITING_HUMAN_REVIEW"] = "AWAITING_HUMAN_REVIEW"
    model_call_count: Literal[0] = 0
    tool_call_count: int = Field(ge=1)
    raw_images_transmitted: Literal[False] = False
    events: list[OperatorAgentEvent]
    knowledge_hits: list[OperatorKnowledgeHit]
    recommendation: OperatorAgentRecommendation
    human_gate: OperatorHumanGate
    boundary_notice: str


class OperatorAnalysisRunState(StoredOperatorAnalysisRun):
    model_config = ConfigDict(frozen=True)

    document_sha256: str = Field(min_length=64, max_length=64)


class CreateOperatorCopilotTurnRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    question: str = Field(min_length=1, max_length=600)

    @field_validator("question")
    @classmethod
    def normalize_question(cls, value: str) -> str:
        normalized = value.strip()
        if not normalized:
            raise ValueError("copilot question cannot be blank")
        return normalized


class StoredOperatorCopilotTurn(BaseModel):
    model_config = ConfigDict(frozen=True)

    schema_version: Literal["visiondata-gate.operator-copilot-turn.v1"] = (
        "visiondata-gate.operator-copilot-turn.v1"
    )
    turn_id: str
    analysis_run_id: str
    workspace_id: str
    project_id: str | None = None
    asset_id: str
    asset_sha256: str = Field(min_length=64, max_length=64)
    question: str
    answer: str
    evidence_refs: list[str]
    answer_mode: Literal["LOCAL_EVIDENCE_GROUNDED"] = "LOCAL_EVIDENCE_GROUNDED"
    model_call_count: Literal[0] = 0
    raw_images_transmitted: Literal[False] = False
    created_by: str
    created_at: str
    boundary_notice: str


class OperatorCopilotTurnState(StoredOperatorCopilotTurn):
    model_config = ConfigDict(frozen=True)

    document_sha256: str = Field(min_length=64, max_length=64)


def _safe_segment(value: str, label: str) -> str:
    if not _SAFE_SEGMENT.fullmatch(value):
        raise OperatorWorkspaceError(
            "invalid_workspace_identifier",
            f"{label} contains unsupported characters",
            status_code=422,
        )
    return value


def _clean_filename(value: str | None) -> str:
    raw = (value or "uploaded-image").replace("\\", "/")
    name = raw.rsplit("/", 1)[-1].strip().strip(".")
    if not name:
        return "uploaded-image"
    return name[:180]


def _sealed_agent_event(
    *,
    sequence: int,
    stage: Literal["INTAKE", "TOOL", "KNOWLEDGE", "DELIVERY", "HUMAN_GATE"],
    actor: Literal["operator-agent", "deterministic-tool", "governance"],
    action: str,
    status: Literal["COMPLETED", "WARNING", "WAITING"],
    summary: str,
    tool_name: str | None = None,
    duration_ms: float = 0.0,
    evidence_refs: tuple[str, ...] = (),
) -> OperatorAgentEvent:
    payload = {
        "sequence": sequence,
        "stage": stage,
        "actor": actor,
        "action": action,
        "status": status,
        "summary": summary,
        "tool_name": tool_name,
        "duration_ms": round(duration_ms, 3),
        "evidence_refs": list(evidence_refs),
    }
    receipt_sha256 = hashlib.sha256(canonical_jcs_bytes(payload)).hexdigest()
    return OperatorAgentEvent(**payload, receipt_sha256=receipt_sha256)


def _atomic_write(path: Path, data: bytes, *, replace: bool) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.parent / f".{path.name}.{uuid.uuid4().hex}.tmp"
    try:
        with temporary.open("xb") as handle:
            handle.write(data)
            handle.flush()
            os.fsync(handle.fileno())
        if replace:
            os.replace(temporary, path)
        else:
            try:
                with path.open("xb") as target:
                    target.write(data)
                    target.flush()
                    os.fsync(target.fileno())
            except FileExistsError as exc:
                raise OperatorWorkspaceError(
                    "immutable_revision_conflict",
                    "the annotation revision already exists",
                    status_code=409,
                ) from exc
    finally:
        try:
            temporary.unlink()
        except FileNotFoundError:
            pass


def _image_metrics(image: Image.Image) -> ImageInspectionMetrics:
    grayscale = image.convert("L")
    grayscale.thumbnail((512, 512), Image.Resampling.BILINEAR)
    values = np.asarray(grayscale, dtype=np.float32)
    horizontal = (
        float(np.abs(np.diff(values, axis=1)).mean()) if values.shape[1] > 1 else 0.0
    )
    vertical = (
        float(np.abs(np.diff(values, axis=0)).mean()) if values.shape[0] > 1 else 0.0
    )
    return ImageInspectionMetrics(
        mean_luma=round(float(values.mean()), 4),
        contrast_std=round(float(values.std()), 4),
        edge_energy=round((horizontal + vertical) / 2.0, 4),
        black_clip_ratio=round(float((values <= 5.0).mean()), 6),
        white_clip_ratio=round(float((values >= 250.0).mean()), 6),
        sample_width=int(values.shape[1]),
        sample_height=int(values.shape[0]),
    )


def _decode_upload(
    data: bytes,
) -> tuple[str, str, str, int, int, str, bytes, ImageInspectionMetrics]:
    if not data:
        raise OperatorWorkspaceError("empty_upload", "the uploaded file is empty")
    if len(data) > MAX_UPLOAD_BYTES:
        raise OperatorWorkspaceError(
            "upload_too_large",
            f"each image must be no larger than {MAX_UPLOAD_BYTES // (1024 * 1024)} MiB",
            status_code=413,
        )

    try:
        with warnings.catch_warnings():
            warnings.simplefilter("error", Image.DecompressionBombWarning)
            with Image.open(BytesIO(data)) as verification_image:
                verification_image.verify()
            with Image.open(BytesIO(data)) as source_image:
                image_format = (source_image.format or "").upper()
                if image_format not in _SUPPORTED_FORMATS:
                    raise OperatorWorkspaceError(
                        "unsupported_image_format",
                        "supported formats are JPEG, PNG, BMP, TIFF, and WebP",
                        status_code=415,
                    )
                oriented = ImageOps.exif_transpose(source_image)
                width, height = oriented.size
                if width <= 0 or height <= 0 or width * height > MAX_IMAGE_PIXELS:
                    raise OperatorWorkspaceError(
                        "image_dimensions_out_of_bounds",
                        "the decoded image dimensions exceed the local safety limit",
                        status_code=413,
                    )
                original_mode = source_image.mode
                rgba = oriented.convert("RGBA")
                background = Image.new("RGBA", rgba.size, (8, 18, 27, 255))
                background.alpha_composite(rgba)
                display_image = background.convert("RGB")
                metrics = _image_metrics(display_image)
                display_image.thumbnail((2048, 2048), Image.Resampling.LANCZOS)
                preview_buffer = BytesIO()
                display_image.save(
                    preview_buffer,
                    format="JPEG",
                    quality=90,
                    optimize=True,
                    progressive=False,
                )
    except OperatorWorkspaceError:
        raise
    except (Image.DecompressionBombError, Image.DecompressionBombWarning) as exc:
        raise OperatorWorkspaceError(
            "image_dimensions_out_of_bounds",
            "the decoded image dimensions exceed the local safety limit",
            status_code=413,
        ) from exc
    except (UnidentifiedImageError, OSError, ValueError) as exc:
        raise OperatorWorkspaceError(
            "invalid_image",
            "the uploaded bytes are not a valid supported image",
            status_code=415,
        ) from exc

    content_type, extension = _SUPPORTED_FORMATS[image_format]
    return (
        image_format,
        content_type,
        extension,
        width,
        height,
        original_mode,
        preview_buffer.getvalue(),
        metrics,
    )


class OperatorImageStore:
    """Filesystem-backed, actor-scoped local image and annotation store."""

    def __init__(self, root: str | Path) -> None:
        self.root = Path(root).expanduser().resolve()
        self.root.mkdir(parents=True, exist_ok=True)

    def _workspace_root(
        self, actor_user_id: str, workspace_id: str, *, create: bool
    ) -> Path:
        actor = _safe_segment(actor_user_id, "actor user ID")
        workspace = _safe_segment(workspace_id, "workspace ID")
        candidate = (self.root / actor / workspace).resolve()
        try:
            candidate.relative_to(self.root)
        except ValueError as exc:
            raise OperatorWorkspaceError(
                "workspace_path_escape",
                "the operator workspace escaped its configured root",
                status_code=422,
            ) from exc
        if create:
            candidate.mkdir(parents=True, exist_ok=True)
        return candidate

    def _asset(
        self, actor_user_id: str, workspace_id: str, asset_id: str
    ) -> tuple[OperatorImageAsset, Path]:
        safe_asset_id = _safe_segment(asset_id, "asset ID")
        workspace_root = self._workspace_root(actor_user_id, workspace_id, create=False)
        asset_root = (workspace_root / safe_asset_id).resolve()
        try:
            asset_root.relative_to(workspace_root)
        except ValueError as exc:
            raise OperatorWorkspaceError(
                "asset_path_escape", "the image asset path is invalid", status_code=422
            ) from exc
        metadata_path = asset_root / "asset.json"
        if not metadata_path.is_file():
            raise OperatorWorkspaceError(
                "operator_asset_not_found",
                "the image asset was not found in this workspace",
                status_code=404,
            )
        try:
            record = OperatorImageAsset.model_validate_json(
                metadata_path.read_text(encoding="utf-8")
            )
        except (OSError, ValueError) as exc:
            raise OperatorWorkspaceError(
                "operator_asset_integrity_failed",
                "the image asset metadata failed validation",
                status_code=409,
            ) from exc
        if record.workspace_id != workspace_id or record.asset_id != asset_id:
            raise OperatorWorkspaceError(
                "operator_asset_binding_failed",
                "the image asset metadata does not match its workspace path",
                status_code=409,
            )
        return record, asset_root

    def add_image(
        self,
        actor_user_id: str,
        workspace_id: str,
        *,
        project_id: str | None = None,
        filename: str | None,
        data: bytes,
    ) -> OperatorImageAsset:
        (
            image_format,
            content_type,
            extension,
            width,
            height,
            original_mode,
            preview_bytes,
            metrics,
        ) = _decode_upload(data)
        workspace_root = self._workspace_root(actor_user_id, workspace_id, create=True)
        source_sha256 = hashlib.sha256(data).hexdigest()
        duplicate = next(
            (
                item.asset_id
                for item in self.list_assets(
                    actor_user_id,
                    workspace_id,
                    project_id=project_id,
                    unassigned_only=project_id is None,
                )
                if item.source_sha256 == source_sha256
            ),
            None,
        )
        asset_id = f"img_{uuid.uuid4().hex[:20]}"
        asset_root = workspace_root / asset_id
        asset_root.mkdir(parents=False, exist_ok=False)
        source_path = asset_root / f"source{extension}"
        preview_path = asset_root / "preview.jpg"
        _atomic_write(source_path, data, replace=False)
        _atomic_write(preview_path, preview_bytes, replace=False)

        base_url = f"/v1/operator-workspaces/{workspace_id}/assets/{asset_id}"
        record = OperatorImageAsset(
            asset_id=asset_id,
            workspace_id=workspace_id,
            project_id=project_id,
            original_name=_clean_filename(filename),
            format=image_format,
            content_type=content_type,
            byte_size=len(data),
            width=width,
            height=height,
            mode=original_mode,
            source_sha256=source_sha256,
            preview_sha256=hashlib.sha256(preview_bytes).hexdigest(),
            source_url=f"{base_url}/content",
            preview_url=f"{base_url}/preview",
            duplicate_of_asset_id=duplicate,
            inspection=metrics,
            created_at=_now(),
        )
        _atomic_write(
            asset_root / "asset.json",
            canonical_jcs_bytes(record.model_dump(mode="json")),
            replace=False,
        )
        return record

    def validate_image_upload(self, data: bytes) -> None:
        """Validate and decode one upload without creating filesystem state."""

        _decode_upload(data)

    def list_assets(
        self,
        actor_user_id: str,
        workspace_id: str,
        *,
        project_id: str | None = None,
        include_unassigned: bool = False,
        unassigned_only: bool = False,
    ) -> list[OperatorImageAsset]:
        workspace_root = self._workspace_root(actor_user_id, workspace_id, create=False)
        if not workspace_root.is_dir():
            return []
        assets: list[OperatorImageAsset] = []
        for metadata_path in workspace_root.glob("img_*/asset.json"):
            try:
                record = OperatorImageAsset.model_validate_json(
                    metadata_path.read_text(encoding="utf-8")
                )
                if unassigned_only and record.project_id is not None:
                    continue
                if (
                    not unassigned_only
                    and project_id is not None
                    and record.project_id != project_id
                    and not (include_unassigned and record.project_id is None)
                ):
                    continue
                annotation_state = self.get_annotations(
                    actor_user_id, workspace_id, record.asset_id
                )
            except (OSError, ValueError, OperatorWorkspaceError) as exc:
                raise OperatorWorkspaceError(
                    "operator_workspace_integrity_failed",
                    "one or more local image records failed validation",
                    status_code=409,
                ) from exc
            assets.append(
                record.model_copy(
                    update={
                        "annotation_count": len(annotation_state.annotations),
                        "annotation_revision": annotation_state.revision,
                    }
                )
            )
        return sorted(
            assets, key=lambda item: (item.created_at, item.asset_id), reverse=True
        )

    def file_variant(
        self,
        actor_user_id: str,
        workspace_id: str,
        asset_id: str,
        variant: Literal["source", "preview"],
    ) -> tuple[Path, str, str]:
        record, asset_root = self._asset(actor_user_id, workspace_id, asset_id)
        if variant == "preview":
            path = asset_root / "preview.jpg"
            content_type = "image/jpeg"
            digest = record.preview_sha256
        else:
            candidates = list(asset_root.glob("source.*"))
            if len(candidates) != 1:
                raise OperatorWorkspaceError(
                    "operator_asset_integrity_failed",
                    "the exact source image could not be resolved",
                    status_code=409,
                )
            path = candidates[0]
            content_type = record.content_type
            digest = record.source_sha256
        if (
            not path.is_file()
            or hashlib.sha256(path.read_bytes()).hexdigest() != digest
        ):
            raise OperatorWorkspaceError(
                "operator_asset_integrity_failed",
                "the image asset bytes failed their SHA-256 binding",
                status_code=409,
            )
        return path, content_type, digest

    def get_annotations(
        self, actor_user_id: str, workspace_id: str, asset_id: str
    ) -> OperatorAnnotationState:
        record, asset_root = self._asset(actor_user_id, workspace_id, asset_id)
        revisions = sorted((asset_root / "annotations").glob("rev_*.json"))
        if not revisions:
            empty_digest = hashlib.sha256(canonical_jcs_bytes([])).hexdigest()
            return OperatorAnnotationState(
                asset_id=asset_id,
                asset_sha256=record.source_sha256,
                revision=0,
                annotations=[],
                document_sha256=empty_digest,
            )
        previous_document_sha256 = hashlib.sha256(canonical_jcs_bytes([])).hexdigest()
        revision: StoredAnnotationRevision | None = None
        data = b""
        for expected_revision, path in enumerate(revisions, start=1):
            try:
                data = path.read_bytes()
                revision = StoredAnnotationRevision.model_validate_json(data)
            except (OSError, ValueError) as exc:
                raise OperatorWorkspaceError(
                    "annotation_integrity_failed",
                    "an annotation revision failed validation",
                    status_code=409,
                ) from exc
            if (
                revision.asset_id != record.asset_id
                or revision.asset_sha256 != record.source_sha256
                or revision.revision != expected_revision
                or path.name != f"rev_{revision.revision:06d}.json"
            ):
                raise OperatorWorkspaceError(
                    "annotation_binding_failed",
                    "the annotation revision chain is not bound to the current image",
                    status_code=409,
                )
            if revision.schema_version.endswith(".v2"):
                payload = revision.model_dump(
                    mode="json", exclude={"revision_payload_sha256"}
                )
                expected_payload_sha256 = hashlib.sha256(
                    canonical_jcs_bytes(payload)
                ).hexdigest()
                canonical_document = canonical_jcs_bytes(
                    revision.model_dump(mode="json")
                )
                if (
                    not hmac.compare_digest(
                        revision.previous_revision_sha256 or "",
                        previous_document_sha256,
                    )
                    or not hmac.compare_digest(
                        revision.revision_payload_sha256 or "",
                        expected_payload_sha256,
                    )
                    or data != canonical_document
                ):
                    raise OperatorWorkspaceError(
                        "annotation_chain_integrity_failed",
                        "the append-only annotation revision chain failed validation",
                        status_code=409,
                    )
            previous_document_sha256 = hashlib.sha256(data).hexdigest()
        assert revision is not None
        return OperatorAnnotationState(
            **revision.model_dump(mode="json"),
            document_sha256=previous_document_sha256,
        )

    def save_annotations(
        self,
        actor_user_id: str,
        workspace_id: str,
        asset_id: str,
        request: SaveAnnotationsRequest,
    ) -> OperatorAnnotationState:
        record, asset_root = self._asset(actor_user_id, workspace_id, asset_id)
        current = self.get_annotations(actor_user_id, workspace_id, asset_id)
        if request.expected_revision != current.revision:
            raise OperatorWorkspaceError(
                "annotation_revision_conflict",
                "annotations changed after this editor loaded; refresh before saving",
                status_code=409,
            )
        stable = {
            "schema_version": "visiondata-gate.operator-annotation-revision.v2",
            "asset_id": record.asset_id,
            "asset_sha256": record.source_sha256,
            "revision": current.revision + 1,
            "updated_at": _now(),
            "annotations": request.annotations,
            "previous_revision_sha256": current.document_sha256,
        }
        next_revision = StoredAnnotationRevision(
            **stable,
            revision_payload_sha256=hashlib.sha256(
                canonical_jcs_bytes(stable)
            ).hexdigest(),
        )
        data = canonical_jcs_bytes(next_revision.model_dump(mode="json"))
        path = asset_root / "annotations" / f"rev_{next_revision.revision:06d}.json"
        _atomic_write(path, data, replace=False)
        return OperatorAnnotationState(
            **next_revision.model_dump(mode="json"),
            document_sha256=hashlib.sha256(data).hexdigest(),
        )

    def _work_order_root(
        self,
        actor_user_id: str,
        workspace_id: str,
        work_order_id: str,
    ) -> Path:
        safe_work_order_id = _safe_segment(work_order_id, "work order ID")
        workspace_root = self._workspace_root(actor_user_id, workspace_id, create=False)
        candidate = (workspace_root / "work_orders" / safe_work_order_id).resolve()
        try:
            candidate.relative_to(workspace_root)
        except ValueError as exc:
            raise OperatorWorkspaceError(
                "work_order_path_escape",
                "the work order path is invalid",
                status_code=422,
            ) from exc
        return candidate

    @staticmethod
    def _work_order_response(
        revision: StoredOperatorWorkOrderRevision,
        data: bytes,
    ) -> OperatorWorkOrderState:
        return OperatorWorkOrderState(
            **revision.model_dump(mode="json"),
            crop_url=(
                f"/v1/operator-workspaces/{revision.workspace_id}/work-orders/"
                f"{revision.work_order_id}/crop"
            ),
            document_sha256=hashlib.sha256(data).hexdigest(),
        )

    def get_work_order(
        self,
        actor_user_id: str,
        workspace_id: str,
        work_order_id: str,
    ) -> OperatorWorkOrderState:
        work_order_root = self._work_order_root(
            actor_user_id, workspace_id, work_order_id
        )
        revisions = sorted((work_order_root / "revisions").glob("rev_*.json"))
        if not revisions:
            raise OperatorWorkspaceError(
                "operator_work_order_not_found",
                "the operator work order was not found",
                status_code=404,
            )
        latest = revisions[-1]
        try:
            data = latest.read_bytes()
            revision = StoredOperatorWorkOrderRevision.model_validate_json(data)
        except (OSError, ValueError) as exc:
            raise OperatorWorkspaceError(
                "work_order_integrity_failed",
                "the latest work order revision failed validation",
                status_code=409,
            ) from exc
        if (
            revision.work_order_id != work_order_id
            or revision.workspace_id != workspace_id
            or latest.name != f"rev_{revision.revision:06d}.json"
        ):
            raise OperatorWorkspaceError(
                "work_order_binding_failed",
                "the work order revision does not match its workspace path",
                status_code=409,
            )
        return self._work_order_response(revision, data)

    def list_work_orders(
        self,
        actor_user_id: str,
        workspace_id: str,
        *,
        project_id: str | None = None,
        include_unassigned: bool = False,
        unassigned_only: bool = False,
    ) -> list[OperatorWorkOrderState]:
        workspace_root = self._workspace_root(actor_user_id, workspace_id, create=False)
        work_orders_root = workspace_root / "work_orders"
        if not work_orders_root.is_dir():
            return []
        records = [
            self.get_work_order(actor_user_id, workspace_id, path.name)
            for path in work_orders_root.glob("wo_*")
            if path.is_dir()
        ]
        if unassigned_only:
            records = [item for item in records if item.project_id is None]
        elif project_id is not None:
            records = [
                item
                for item in records
                if item.project_id == project_id
                or (include_unassigned and item.project_id is None)
            ]
        return sorted(
            records,
            key=lambda item: (item.updated_at, item.work_order_id),
            reverse=True,
        )

    def create_work_order(
        self,
        actor_user_id: str,
        workspace_id: str,
        asset_id: str,
        request: CreateOperatorWorkOrderRequest,
    ) -> OperatorWorkOrderState:
        asset, _asset_root = self._asset(actor_user_id, workspace_id, asset_id)
        annotation_state = self.get_annotations(actor_user_id, workspace_id, asset_id)
        if request.expected_annotation_revision != annotation_state.revision:
            raise OperatorWorkspaceError(
                "work_order_annotation_revision_conflict",
                "annotations changed before the work order was issued; refresh and retry",
                status_code=409,
            )
        annotation = next(
            (
                item
                for item in annotation_state.annotations
                if item.annotation_id == request.annotation_id
            ),
            None,
        )
        if annotation is None:
            raise OperatorWorkspaceError(
                "work_order_annotation_not_found",
                "the selected annotation is not present in the saved revision",
                status_code=409,
            )

        left = max(0, min(asset.width - 1, math.floor(annotation.x * asset.width)))
        top = max(0, min(asset.height - 1, math.floor(annotation.y * asset.height)))
        right = max(
            left + 1,
            min(
                asset.width, math.ceil((annotation.x + annotation.width) * asset.width)
            ),
        )
        bottom = max(
            top + 1,
            min(
                asset.height,
                math.ceil((annotation.y + annotation.height) * asset.height),
            ),
        )
        pixel_bbox = PixelBoundingBox(
            x=left,
            y=top,
            width=right - left,
            height=bottom - top,
        )

        source_path, _content_type, _digest = self.file_variant(
            actor_user_id, workspace_id, asset_id, "source"
        )
        try:
            with Image.open(source_path) as source_image:
                oriented = ImageOps.exif_transpose(source_image).convert("RGB")
                crop = oriented.crop((left, top, right, bottom))
                crop.thumbnail((512, 512), Image.Resampling.LANCZOS)
                crop_buffer = BytesIO()
                crop.save(crop_buffer, format="JPEG", quality=92, optimize=True)
                crop_bytes = crop_buffer.getvalue()
        except (OSError, ValueError) as exc:
            raise OperatorWorkspaceError(
                "work_order_crop_failed",
                "the annotation crop could not be generated from the bound source image",
                status_code=409,
            ) from exc

        work_order_id = f"wo_{uuid.uuid4().hex[:20]}"
        work_order_root = self._work_order_root(
            actor_user_id, workspace_id, work_order_id
        )
        work_order_root.mkdir(parents=True, exist_ok=False)
        _atomic_write(work_order_root / "crop.jpg", crop_bytes, replace=False)
        timestamp = _now()
        revision = StoredOperatorWorkOrderRevision(
            work_order_id=work_order_id,
            workspace_id=workspace_id,
            project_id=asset.project_id,
            asset_id=asset.asset_id,
            asset_sha256=asset.source_sha256,
            image_name=asset.original_name,
            annotation_revision=annotation_state.revision,
            annotation=annotation,
            pixel_bbox=pixel_bbox,
            crop_sha256=hashlib.sha256(crop_bytes).hexdigest(),
            revision=1,
            status="OPEN",
            assignee=request.assignee,
            note=request.note,
            operator_attests_reviewed_evidence=(
                request.operator_attests_reviewed_evidence
            ),
            created_by=actor_user_id,
            created_at=timestamp,
            updated_by=actor_user_id,
            updated_at=timestamp,
        )
        data = canonical_jcs_bytes(revision.model_dump(mode="json"))
        _atomic_write(
            work_order_root / "revisions" / "rev_000001.json",
            data,
            replace=False,
        )
        return self._work_order_response(revision, data)

    def update_work_order(
        self,
        actor_user_id: str,
        workspace_id: str,
        work_order_id: str,
        request: UpdateOperatorWorkOrderRequest,
    ) -> OperatorWorkOrderState:
        current = self.get_work_order(actor_user_id, workspace_id, work_order_id)
        if request.expected_revision != current.revision:
            raise OperatorWorkspaceError(
                "work_order_revision_conflict",
                "the work order changed after this view loaded; refresh before updating",
                status_code=409,
            )
        if (
            not current.operator_attests_reviewed_evidence
            and request.status != "REJECTED"
        ):
            raise OperatorWorkspaceError(
                "work_order_human_review_required",
                "legacy work orders without a human-review attestation may only be rejected",
                status_code=409,
            )
        allowed_transitions = {
            "OPEN": {"ACKNOWLEDGED", "IN_CAPA", "REJECTED"},
            "ACKNOWLEDGED": {"ACKNOWLEDGED", "IN_CAPA", "REJECTED"},
            "IN_CAPA": {"IN_CAPA", "CLOSED", "REJECTED"},
            "REJECTED": set(),
            "CLOSED": set(),
        }
        if request.status not in allowed_transitions[current.status]:
            raise OperatorWorkspaceError(
                "work_order_transition_forbidden",
                f"work order status cannot transition from {current.status} to {request.status}",
                status_code=409,
            )
        if request.status == "CLOSED":
            verification = self.get_annotations(
                actor_user_id, workspace_id, current.asset_id
            )
            if not (
                request.verification_annotation_revision == verification.revision
                and request.verification_annotation_sha256
                == verification.document_sha256
            ):
                raise OperatorWorkspaceError(
                    "work_order_verification_binding_conflict",
                    "the supplied closure evidence is not the current annotation revision",
                    status_code=409,
                )
            if verification.revision <= current.annotation_revision:
                raise OperatorWorkspaceError(
                    "work_order_reverification_required",
                    "close requires a newer annotation revision than the issued work order",
                    status_code=409,
                )
            current_target = next(
                (
                    item
                    for item in verification.annotations
                    if item.annotation_id == current.annotation.annotation_id
                ),
                None,
            )
            if current_target == current.annotation:
                raise OperatorWorkspaceError(
                    "work_order_target_not_remediated",
                    "the bound annotation has not changed in the verification revision",
                    status_code=409,
                )
        revision = StoredOperatorWorkOrderRevision(
            **{
                **current.model_dump(
                    mode="json", exclude={"crop_url", "document_sha256"}
                ),
                "revision": current.revision + 1,
                "status": request.status,
                "assignee": request.assignee,
                "note": request.note,
                "operator_attests_reviewed_evidence": (
                    request.operator_attests_reviewed_evidence
                ),
                "verification_annotation_revision": (
                    request.verification_annotation_revision
                ),
                "verification_annotation_sha256": (
                    request.verification_annotation_sha256
                ),
                "updated_by": actor_user_id,
                "updated_at": _now(),
            }
        )
        data = canonical_jcs_bytes(revision.model_dump(mode="json"))
        work_order_root = self._work_order_root(
            actor_user_id, workspace_id, work_order_id
        )
        _atomic_write(
            work_order_root / "revisions" / f"rev_{revision.revision:06d}.json",
            data,
            replace=False,
        )
        return self._work_order_response(revision, data)

    def work_order_crop(
        self,
        actor_user_id: str,
        workspace_id: str,
        work_order_id: str,
    ) -> tuple[Path, str]:
        current = self.get_work_order(actor_user_id, workspace_id, work_order_id)
        path = (
            self._work_order_root(actor_user_id, workspace_id, work_order_id)
            / "crop.jpg"
        )
        if (
            not path.is_file()
            or hashlib.sha256(path.read_bytes()).hexdigest() != current.crop_sha256
        ):
            raise OperatorWorkspaceError(
                "work_order_crop_integrity_failed",
                "the work order crop failed its SHA-256 binding",
                status_code=409,
            )
        return path, current.crop_sha256

    @staticmethod
    def _analysis_response(
        run: StoredOperatorAnalysisRun,
        data: bytes,
    ) -> OperatorAnalysisRunState:
        return OperatorAnalysisRunState(
            **run.model_dump(mode="json"),
            document_sha256=hashlib.sha256(data).hexdigest(),
        )

    def list_analysis_runs(
        self,
        actor_user_id: str,
        workspace_id: str,
        asset_id: str,
    ) -> list[OperatorAnalysisRunState]:
        asset, asset_root = self._asset(actor_user_id, workspace_id, asset_id)
        runs: list[OperatorAnalysisRunState] = []
        for path in (asset_root / "analysis_runs").glob("arun_*.json"):
            try:
                data = path.read_bytes()
                run = StoredOperatorAnalysisRun.model_validate_json(data)
            except (OSError, ValueError) as exc:
                raise OperatorWorkspaceError(
                    "operator_analysis_integrity_failed",
                    "one or more operator analysis traces failed validation",
                    status_code=409,
                ) from exc
            if (
                run.workspace_id != workspace_id
                or run.asset_id != asset.asset_id
                or run.asset_sha256 != asset.source_sha256
                or path.name != f"{run.analysis_run_id}.json"
            ):
                raise OperatorWorkspaceError(
                    "operator_analysis_binding_failed",
                    "the operator analysis trace is not bound to this image",
                    status_code=409,
                )
            runs.append(self._analysis_response(run, data))
        return sorted(
            runs,
            key=lambda item: (item.completed_at, item.analysis_run_id),
            reverse=True,
        )

    def create_analysis_run(
        self,
        actor_user_id: str,
        workspace_id: str,
        asset_id: str,
    ) -> OperatorAnalysisRunState:
        started_at = _now()
        asset, asset_root = self._asset(actor_user_id, workspace_id, asset_id)

        tool_started = time.perf_counter()
        source_path, _content_type, source_digest = self.file_variant(
            actor_user_id, workspace_id, asset_id, "source"
        )
        sha_duration = (time.perf_counter() - tool_started) * 1000.0
        asset_ref = f"asset:{asset.asset_id}:sha256:{source_digest}"

        tool_started = time.perf_counter()
        try:
            with Image.open(source_path) as source_image:
                inspected_image = ImageOps.exif_transpose(source_image).convert("RGB")
                inspection = _image_metrics(inspected_image)
        except (OSError, ValueError) as exc:
            raise OperatorWorkspaceError(
                "operator_analysis_image_failed",
                "the bound source image could not be inspected",
                status_code=409,
            ) from exc
        inspection_duration = (time.perf_counter() - tool_started) * 1000.0
        inspection_digest = hashlib.sha256(
            canonical_jcs_bytes(inspection.model_dump(mode="json"))
        ).hexdigest()
        inspection_ref = f"inspection:{asset.asset_id}:sha256:{inspection_digest}"

        tool_started = time.perf_counter()
        duplicates = sorted(
            item.asset_id
            for item in self.list_assets(
                actor_user_id,
                workspace_id,
                project_id=asset.project_id,
                unassigned_only=asset.project_id is None,
            )
            if item.asset_id != asset.asset_id
            and item.source_sha256 == asset.source_sha256
        )
        duplicate_duration = (time.perf_counter() - tool_started) * 1000.0
        duplicate_digest = hashlib.sha256(
            canonical_jcs_bytes(
                {
                    "asset_sha256": asset.source_sha256,
                    "duplicate_asset_ids": duplicates,
                }
            )
        ).hexdigest()
        duplicate_ref = f"duplicate-ledger:sha256:{duplicate_digest}"

        tool_started = time.perf_counter()
        annotation_state = self.get_annotations(actor_user_id, workspace_id, asset_id)
        annotation_duration = (time.perf_counter() - tool_started) * 1000.0
        annotation_ref = (
            f"annotation:{asset.asset_id}:revision:{annotation_state.revision}:"
            f"sha256:{annotation_state.document_sha256}"
        )

        tool_started = time.perf_counter()
        work_orders = [
            item
            for item in self.list_work_orders(
                actor_user_id,
                workspace_id,
                project_id=asset.project_id,
                unassigned_only=asset.project_id is None,
            )
            if item.asset_id == asset.asset_id
        ]
        work_order_duration = (time.perf_counter() - tool_started) * 1000.0
        work_order_digest = hashlib.sha256(
            canonical_jcs_bytes(
                [
                    {
                        "work_order_id": item.work_order_id,
                        "revision": item.revision,
                        "status": item.status,
                        "document_sha256": item.document_sha256,
                    }
                    for item in work_orders
                ]
            )
        ).hexdigest()
        work_order_ref = f"work-order-ledger:sha256:{work_order_digest}"

        screening_flags: list[str] = []
        if inspection.black_clip_ratio >= 0.05:
            screening_flags.append("black clipping >= 5%")
        if inspection.white_clip_ratio >= 0.05:
            screening_flags.append("white clipping >= 5%")
        if inspection.contrast_std < 12.0:
            screening_flags.append("contrast sigma < 12")
        if inspection.edge_energy < 3.0:
            screening_flags.append("edge energy < 3")

        policy_ref = "policy:operator-workspace:human-only-production-authority"
        knowledge_hits = [
            OperatorKnowledgeHit(
                card_id="operator-human-authority-v1",
                title="工业放行权限边界",
                excerpt=(
                    "Agent 只提供证据编排与辅助建议；工单签发需要具名人员复核，"
                    "生产放行权始终属于授权人工。"
                ),
                source="operator-workspace-policy.v1",
                evidence_ref=policy_ref,
            )
        ]

        if duplicates:
            recommendation = OperatorAgentRecommendation(
                code="DUPLICATE_REVIEW",
                severity="HIGH",
                title="复核重复样本与跨划分泄漏",
                summary=(
                    f"本地 SHA-256 账本找到 {len(duplicates)} 个同字节资产；"
                    "当前运行只证明字节相同，尚未证明 Train/Val 泄漏。"
                ),
                next_action="由数据负责人核对划分归属；确认前不要据此放行数据集。",
                evidence_refs=[asset_ref, duplicate_ref],
            )
        elif work_orders:
            recommendation = OperatorAgentRecommendation(
                code="FOLLOW_EXISTING_WORK_ORDER",
                severity="MEDIUM",
                title="继续处理已绑定工单",
                summary=(
                    f"该图片已有 {len(work_orders)} 张本地工单；Agent 未创建重复工单。"
                ),
                next_action="打开 CAPA 队列，由具名负责人复核现有工单状态。",
                evidence_refs=[annotation_ref, work_order_ref],
            )
        elif screening_flags:
            recommendation = OperatorAgentRecommendation(
                code="CAPTURE_QUALITY_REVIEW",
                severity="MEDIUM",
                title="复核采集质量信号",
                summary=(
                    "本地工作区筛查阈值触发："
                    + "；".join(screening_flags)
                    + "。这些阈值是操作台预筛，不是质量判定标准。"
                ),
                next_action="结合光学剖面与现场 SOP，由人工判断是否重采或继续标注。",
                evidence_refs=[inspection_ref, policy_ref],
            )
        elif annotation_state.annotations:
            labels = sorted({item.label for item in annotation_state.annotations})
            recommendation = OperatorAgentRecommendation(
                code="ANNOTATION_REVIEW",
                severity="LOW",
                title="复核人工标注并决定是否签发工单",
                summary=(
                    f"当前保存版本含 {len(annotation_state.annotations)} 个人工标注："
                    f"{', '.join(labels)}。Agent 不把人工标签冒充模型识别结果。"
                ),
                next_action="核对标注几何与类别后，可在 BBox 上右键创建 CAPA 草稿。",
                evidence_refs=[annotation_ref, policy_ref],
            )
        else:
            recommendation = OperatorAgentRecommendation(
                code="MANUAL_TRIAGE_REQUIRED",
                severity="LOW",
                title="等待人工取证",
                summary="完整性与基础像素统计已完成，当前没有保存的缺陷标注或工单。",
                next_action="使用框选或光学剖面探针完成取证，再由人工决定是否生成工单。",
                evidence_refs=[asset_ref, inspection_ref, annotation_ref],
            )

        quality_summary = (
            "像素统计已复算："
            f"Mean luma {inspection.mean_luma:.2f}，"
            f"Contrast sigma {inspection.contrast_std:.2f}，"
            f"Edge energy {inspection.edge_energy:.2f}。"
        )
        if screening_flags:
            quality_summary += " 工作区预筛信号：" + "；".join(screening_flags) + "。"
        else:
            quality_summary += " 未触发当前工作区预筛阈值；这不等于质量 PASS。"

        events = [
            _sealed_agent_event(
                sequence=1,
                stage="INTAKE",
                actor="operator-agent",
                action="understand_operator_task",
                status="COMPLETED",
                summary=(
                    f"收到本地图片 {asset.original_name}；任务是核对完整性、像素质量、"
                    "重复关系、标注与工单账本。"
                ),
                evidence_refs=(asset_ref,),
            ),
            _sealed_agent_event(
                sequence=2,
                stage="TOOL",
                actor="deterministic-tool",
                action="verify_asset_integrity",
                status="COMPLETED",
                summary="源文件字节与资产 SHA-256 绑定一致。",
                tool_name="sha256_integrity_probe",
                duration_ms=sha_duration,
                evidence_refs=(asset_ref,),
            ),
            _sealed_agent_event(
                sequence=3,
                stage="TOOL",
                actor="deterministic-tool",
                action="inspect_image_quality",
                status="WARNING" if screening_flags else "COMPLETED",
                summary=quality_summary,
                tool_name="image_quality_probe",
                duration_ms=inspection_duration,
                evidence_refs=(inspection_ref,),
            ),
            _sealed_agent_event(
                sequence=4,
                stage="TOOL",
                actor="deterministic-tool",
                action="lookup_duplicate_ledger",
                status="WARNING" if duplicates else "COMPLETED",
                summary=(
                    f"找到 {len(duplicates)} 个同 SHA-256 资产：{', '.join(duplicates)}。"
                    if duplicates
                    else "本地账本未找到其他同 SHA-256 资产。"
                ),
                tool_name="duplicate_ledger_lookup",
                duration_ms=duplicate_duration,
                evidence_refs=(duplicate_ref,),
            ),
            _sealed_agent_event(
                sequence=5,
                stage="TOOL",
                actor="deterministic-tool",
                action="lookup_annotation_ledger",
                status="COMPLETED" if annotation_state.annotations else "WARNING",
                summary=(
                    f"读取 annotation revision {annotation_state.revision}，"
                    f"包含 {len(annotation_state.annotations)} 个保存标注。"
                ),
                tool_name="annotation_ledger_lookup",
                duration_ms=annotation_duration,
                evidence_refs=(annotation_ref,),
            ),
            _sealed_agent_event(
                sequence=6,
                stage="TOOL",
                actor="deterministic-tool",
                action="lookup_work_order_ledger",
                status="COMPLETED",
                summary=f"读取到 {len(work_orders)} 张与当前图片绑定的本地工单。",
                tool_name="work_order_ledger_lookup",
                duration_ms=work_order_duration,
                evidence_refs=(work_order_ref,),
            ),
            _sealed_agent_event(
                sequence=7,
                stage="KNOWLEDGE",
                actor="operator-agent",
                action="retrieve_governance_policy",
                status="COMPLETED",
                summary="检索到本地治理卡：AI 只有建议权，生产决策权属于授权人工。",
                evidence_refs=(policy_ref,),
            ),
            _sealed_agent_event(
                sequence=8,
                stage="DELIVERY",
                actor="operator-agent",
                action="deliver_grounded_recommendation",
                status="WARNING" if recommendation.severity != "LOW" else "COMPLETED",
                summary=f"{recommendation.title}：{recommendation.next_action}",
                evidence_refs=tuple(recommendation.evidence_refs),
            ),
            _sealed_agent_event(
                sequence=9,
                stage="HUMAN_GATE",
                actor="governance",
                action="await_named_human_review",
                status="WAITING",
                summary="等待具名人员复核；未授予生产放行或设备写入权限。",
                evidence_refs=(policy_ref, annotation_ref),
            ),
        ]

        run = StoredOperatorAnalysisRun(
            analysis_run_id=f"arun_{uuid.uuid4().hex[:20]}",
            workspace_id=workspace_id,
            project_id=asset.project_id,
            asset_id=asset.asset_id,
            asset_sha256=asset.source_sha256,
            annotation_revision=annotation_state.revision,
            annotation_document_sha256=annotation_state.document_sha256,
            started_at=started_at,
            completed_at=_now(),
            goal="为当前工业图片生成可审计的本地取证摘要与人工处置建议。",
            intent=(
                "只读编排 SHA-256、像素质量、重复、标注和工单账本；不执行生产写入。"
            ),
            tool_call_count=5,
            events=events,
            knowledge_hits=knowledge_hits,
            recommendation=recommendation,
            human_gate=OperatorHumanGate(
                required_action=(
                    "复核图片、指标、标注与建议；若创建工单，必须勾选 AI 辅助边界确认。"
                )
            ),
            boundary_notice=(
                "本运行是本地确定性证据编排，model_call_count=0。"
                "未向 OpenToken 或其他外部模型发送原图，不构成缺陷识别置信度、"
                "质量 PASS 或生产授权。"
            ),
        )
        data = canonical_jcs_bytes(run.model_dump(mode="json"))
        _atomic_write(
            asset_root / "analysis_runs" / f"{run.analysis_run_id}.json",
            data,
            replace=False,
        )
        return self._analysis_response(run, data)

    def _analysis_run(
        self,
        actor_user_id: str,
        workspace_id: str,
        asset_id: str,
        analysis_run_id: str,
    ) -> OperatorAnalysisRunState:
        safe_run_id = _safe_segment(analysis_run_id, "analysis run ID")
        run = next(
            (
                item
                for item in self.list_analysis_runs(
                    actor_user_id, workspace_id, asset_id
                )
                if item.analysis_run_id == safe_run_id
            ),
            None,
        )
        if run is None:
            raise OperatorWorkspaceError(
                "operator_analysis_not_found",
                "the operator analysis run was not found for this image",
                status_code=404,
            )
        return run

    @staticmethod
    def _copilot_response(
        turn: StoredOperatorCopilotTurn,
        data: bytes,
    ) -> OperatorCopilotTurnState:
        return OperatorCopilotTurnState(
            **turn.model_dump(mode="json"),
            document_sha256=hashlib.sha256(data).hexdigest(),
        )

    def list_copilot_turns(
        self,
        actor_user_id: str,
        workspace_id: str,
        asset_id: str,
        analysis_run_id: str,
    ) -> list[OperatorCopilotTurnState]:
        run = self._analysis_run(actor_user_id, workspace_id, asset_id, analysis_run_id)
        _asset, asset_root = self._asset(actor_user_id, workspace_id, asset_id)
        turns: list[OperatorCopilotTurnState] = []
        turns_root = asset_root / "copilot_turns" / run.analysis_run_id
        for path in turns_root.glob("turn_*.json"):
            try:
                data = path.read_bytes()
                turn = StoredOperatorCopilotTurn.model_validate_json(data)
            except (OSError, ValueError) as exc:
                raise OperatorWorkspaceError(
                    "operator_copilot_integrity_failed",
                    "one or more Copilot turns failed validation",
                    status_code=409,
                ) from exc
            if (
                turn.analysis_run_id != run.analysis_run_id
                or turn.workspace_id != workspace_id
                or turn.asset_id != asset_id
                or turn.asset_sha256 != run.asset_sha256
                or path.name != f"{turn.turn_id}.json"
            ):
                raise OperatorWorkspaceError(
                    "operator_copilot_binding_failed",
                    "the Copilot turn is not bound to this analysis run",
                    status_code=409,
                )
            turns.append(self._copilot_response(turn, data))
        return sorted(turns, key=lambda item: (item.created_at, item.turn_id))

    def create_copilot_turn(
        self,
        actor_user_id: str,
        workspace_id: str,
        asset_id: str,
        analysis_run_id: str,
        request: CreateOperatorCopilotTurnRequest,
    ) -> OperatorCopilotTurnState:
        run = self._analysis_run(actor_user_id, workspace_id, asset_id, analysis_run_id)
        _asset, asset_root = self._asset(actor_user_id, workspace_id, asset_id)
        normalized = request.question.casefold()
        run_ref = f"analysis-run:{run.analysis_run_id}:sha256:{run.document_sha256}"
        event_by_action = {event.action: event for event in run.events}
        duplicate_event = event_by_action["lookup_duplicate_ledger"]
        work_order_event = event_by_action["lookup_work_order_ledger"]
        annotation_event = event_by_action["lookup_annotation_ledger"]
        quality_event = event_by_action["inspect_image_quality"]

        if any(keyword in normalized for keyword in ("供应商", "supplier", "维修记录")):
            answer = (
                "当前图片工作区没有已授权的供应商或设备维修数据库证据，"
                "因此我不能回答供应商归属或历史维修次数。若后续接入受控数据源，"
                "需要生成新的 Tool Receipt 后才能引用。"
            )
            evidence_refs = [run_ref]
        elif any(keyword in normalized for keyword in ("重复", "泄漏", "duplicate")):
            answer = (
                f"重复账本结果：{duplicate_event.summary} "
                "字节重复不自动等同于 Train/Val 泄漏，仍需人工核对划分归属。"
            )
            evidence_refs = [*duplicate_event.evidence_refs, run_ref]
        elif any(keyword in normalized for keyword in ("工单", "capa", "派发")):
            answer = (
                f"工单账本结果：{work_order_event.summary} "
                "创建新工单前必须复核已保存标注并完成 AI 辅助边界确认；"
                "生产放行权不会随工单创建而解锁。"
            )
            evidence_refs = [
                *work_order_event.evidence_refs,
                *annotation_event.evidence_refs,
                run.knowledge_hits[0].evidence_ref,
                run_ref,
            ]
        elif any(keyword in normalized for keyword in ("模型", "置信度", "llm")):
            answer = (
                "本次运行的 model_call_count=0，backend=local-deterministic。"
                "没有视觉模型置信度，也没有向外部模型发送原图；界面展示的是"
                "已落盘的工具事件和证据回执。"
            )
            evidence_refs = [run_ref]
        elif any(keyword in normalized for keyword in ("质量", "曝光", "清晰", "像素")):
            answer = (
                f"像素质量探针结果：{quality_event.summary} "
                "这些指标只用于本地预筛，不能单独构成质量 PASS。"
            )
            evidence_refs = [*quality_event.evidence_refs, run_ref]
        elif any(keyword in normalized for keyword in ("建议", "下一步", "怎么处理")):
            answer = (
                f"当前建议是“{run.recommendation.title}”。"
                f"下一步：{run.recommendation.next_action} "
                "该建议 decision_authority=none，需由具名人员决定。"
            )
            evidence_refs = [*run.recommendation.evidence_refs, run_ref]
        elif any(keyword in normalized for keyword in ("证据", "sha", "依据", "回执")):
            answer = (
                f"本次分析绑定图片 SHA-256 {run.asset_sha256}、"
                f"annotation revision {run.annotation_revision}，"
                f"Trace 回执 {run.document_sha256}。可展开每个活动事件查看独立回执。"
            )
            evidence_refs = [run_ref, *annotation_event.evidence_refs]
        else:
            answer = (
                "我只能基于当前本地 Trace 回答：图片完整性、像素质量、重复账本、"
                "标注 revision、工单状态、建议与安全边界。当前问题没有可引用的"
                "受控证据，因此不作推断。"
            )
            evidence_refs = [run_ref]

        turn = StoredOperatorCopilotTurn(
            turn_id=f"turn_{uuid.uuid4().hex[:20]}",
            analysis_run_id=run.analysis_run_id,
            workspace_id=workspace_id,
            project_id=run.project_id,
            asset_id=asset_id,
            asset_sha256=run.asset_sha256,
            question=request.question,
            answer=answer,
            evidence_refs=list(dict.fromkeys(evidence_refs)),
            created_by=actor_user_id,
            created_at=_now(),
            boundary_notice=(
                "This turn is deterministic local evidence retrieval, not an LLM response. "
                "No raw image or question was transmitted externally."
            ),
        )
        data = canonical_jcs_bytes(turn.model_dump(mode="json"))
        _atomic_write(
            asset_root / "copilot_turns" / run.analysis_run_id / f"{turn.turn_id}.json",
            data,
            replace=False,
        )
        return self._copilot_response(turn, data)


__all__ = [
    "BoundingBoxAnnotation",
    "CreateOperatorCopilotTurnRequest",
    "CreateOperatorWorkOrderRequest",
    "MAX_UPLOAD_BYTES",
    "MAX_UPLOAD_FILES",
    "OperatorAnnotationState",
    "OperatorAnalysisRunState",
    "OperatorCopilotTurnState",
    "OperatorImageAsset",
    "OperatorImageStore",
    "OperatorImageUploadBatch",
    "OperatorWorkOrderState",
    "OperatorWorkspaceError",
    "PixelBoundingBox",
    "SaveAnnotationsRequest",
    "UpdateOperatorWorkOrderRequest",
]
