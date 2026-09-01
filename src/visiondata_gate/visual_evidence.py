"""Read-only visual evidence projected from one immutable Product Task.

The projection deliberately joins only already-sealed artifacts:

* the task-bound Operator Project Snapshot receipt;
* the SHA-verified task Evidence ZIP; and
* the typed Industrial Delivery receipt.

It never accepts a browser filesystem path and never reads the mutable Operator
annotation ledger.  Preview and mask URLs therefore refer to the frozen snapshot
that the Agent actually inspected, not to a later workbook revision.
"""

from __future__ import annotations

import hashlib
from collections import defaultdict
from typing import Any, Literal
from urllib.parse import quote

from pydantic import Field, model_validator

from .audit_envelope import canonical_jcs_bytes
from .industrial_delivery import IndustrialDeliveryReceipt
from .operator_snapshot import OperatorProjectSnapshotReceipt
from .product_models import ProductModel, TaskRecord


_SHA256_PATTERN = r"^[0-9a-f]{64}$"


def _sha256_payload(value: object) -> str:
    return hashlib.sha256(canonical_jcs_bytes(value)).hexdigest()


class TaskVisualEvidenceMeasurement(ProductModel):
    """One redacted deterministic fact tied to a frozen sample."""

    source_kind: str = Field(min_length=1)
    finding_id: str = Field(min_length=1)
    code: str = Field(min_length=1)
    tool: str = Field(min_length=1)
    evidence_ref: str = Field(min_length=1)
    evidence_sha256: str = Field(pattern=_SHA256_PATTERN)
    observed: dict[str, Any]


class TaskVisualEvidenceItem(ProductModel):
    """Browser-safe identity for one frozen sample and its evidence facts."""

    sample_id: str = Field(min_length=1)
    original_name: str = Field(min_length=1)
    width: int = Field(ge=1)
    height: int = Field(ge=1)
    source_sha256: str = Field(pattern=_SHA256_PATTERN)
    preview_sha256: str = Field(pattern=_SHA256_PATTERN)
    annotation_revision: int = Field(ge=0)
    annotation_document_sha256: str = Field(pattern=_SHA256_PATTERN)
    annotation_count: int = Field(ge=0)
    mask_sha256: str | None = Field(default=None, pattern=_SHA256_PATTERN)
    preview_url: str = Field(pattern=r"^/v1/tasks/")
    mask_url: str | None = Field(default=None, pattern=r"^/v1/tasks/")
    affected: bool
    finding_ids: list[str]
    issue_codes: list[str]
    tools: list[str]
    work_order_ids: list[str]
    measurements: list[TaskVisualEvidenceMeasurement]
    item_sha256: str = Field(pattern=_SHA256_PATTERN)

    @model_validator(mode="after")
    def validate_item(self) -> "TaskVisualEvidenceItem":
        for values in (
            self.finding_ids,
            self.issue_codes,
            self.tools,
            self.work_order_ids,
        ):
            if values != sorted(set(values)):
                raise ValueError(
                    "visual evidence identity lists must be sorted and unique"
                )
        if self.affected != bool(self.finding_ids or self.issue_codes):
            raise ValueError("visual evidence affected flag does not match findings")
        if (self.mask_sha256 is None) != (self.mask_url is None):
            raise ValueError("visual evidence mask digest and URL must be paired")
        stable = self.model_dump(mode="json", exclude={"item_sha256"})
        if _sha256_payload(stable) != self.item_sha256:
            raise ValueError("visual evidence item digest mismatch")
        return self


class TaskVisualEvidenceManifest(ProductModel):
    """SHA-sealed, browser-safe projection of frozen task imagery."""

    schema_version: Literal["visiondata-gate.task-visual-evidence.v1"] = (
        "visiondata-gate.task-visual-evidence.v1"
    )
    task_id: str = Field(pattern=r"^tsk_[0-9a-f]{20}$")
    workspace_id: str = Field(min_length=1)
    project_id: str = Field(min_length=1)
    source_id: str = Field(min_length=1)
    task_request_sha256: str = Field(pattern=_SHA256_PATTERN)
    task_evidence_sha256: str = Field(pattern=_SHA256_PATTERN)
    source_profile_sha256: str = Field(pattern=_SHA256_PATTERN)
    operator_snapshot_receipt_sha256: str = Field(pattern=_SHA256_PATTERN)
    visual_count: int = Field(ge=1)
    affected_count: int = Field(ge=0)
    items: list[TaskVisualEvidenceItem] = Field(min_length=1)
    read_only: Literal[True] = True
    raw_images_transmitted: Literal[False] = False
    production_release_allowed: Literal[False] = False
    manifest_sha256: str = Field(pattern=_SHA256_PATTERN)
    claim_boundary: str = (
        "This manifest exposes only previews and redacted measurements from the "
        "immutable Operator Project Snapshot inspected by the named task. It is not "
        "the mutable workbook, physical root-cause proof, customer acceptance, or "
        "production release authorization."
    )

    @model_validator(mode="after")
    def validate_manifest(self) -> "TaskVisualEvidenceManifest":
        if self.visual_count != len(self.items):
            raise ValueError("visual evidence count mismatch")
        if self.affected_count != sum(item.affected for item in self.items):
            raise ValueError("visual evidence affected count mismatch")
        sample_ids = [item.sample_id for item in self.items]
        if sample_ids != sorted(set(sample_ids)):
            raise ValueError("visual evidence samples must be sorted and unique")
        stable = self.model_dump(mode="json", exclude={"manifest_sha256"})
        if _sha256_payload(stable) != self.manifest_sha256:
            raise ValueError("visual evidence manifest digest mismatch")
        return self


def build_task_visual_evidence_manifest(
    *,
    task: TaskRecord,
    snapshot: OperatorProjectSnapshotReceipt,
    delivery: IndustrialDeliveryReceipt,
    source_profile_sha256: str,
) -> TaskVisualEvidenceManifest:
    """Build a deterministic visual projection from verified typed receipts."""

    if not task.evidence_sha256 or not task.source_id:
        raise ValueError(
            "task visual evidence requires sealed task evidence and source"
        )
    if len(source_profile_sha256) != 64:
        raise ValueError("task visual evidence requires a source profile SHA-256")
    if delivery.task_id != task.task_id:
        raise ValueError("industrial delivery is not bound to the visual task")
    if (
        snapshot.workspace_id != task.workspace_id
        or snapshot.project_id != task.project_id
    ):
        raise ValueError("operator snapshot escaped the task workspace or project")

    finding_ids: dict[str, set[str]] = defaultdict(set)
    issue_codes: dict[str, set[str]] = defaultdict(set)
    tools: dict[str, set[str]] = defaultdict(set)
    work_order_ids: dict[str, set[str]] = defaultdict(set)
    measurements: dict[str, dict[str, TaskVisualEvidenceMeasurement]] = defaultdict(
        dict
    )

    for entry in delivery.evidence_fusion_matrix:
        for sample_id in entry.sample_ids:
            finding_ids[sample_id].add(entry.primary_finding_id)
            finding_ids[sample_id].update(entry.corroborating_finding_ids)
            issue_codes[sample_id].add(entry.issue_code)
            work_order_ids[sample_id].update(entry.work_order_ids)
        for fact in entry.evidence_facts:
            measurement = TaskVisualEvidenceMeasurement(
                source_kind=fact.source_kind,
                finding_id=fact.finding_id,
                code=fact.code,
                tool=fact.tool,
                evidence_ref=fact.evidence_ref,
                evidence_sha256=fact.evidence_sha256,
                observed=fact.observed,
            )
            for sample_id in fact.sample_ids:
                finding_ids[sample_id].add(fact.finding_id)
                issue_codes[sample_id].add(fact.code)
                tools[sample_id].add(fact.tool)
                measurements[sample_id][fact.evidence_sha256] = measurement

    items: list[TaskVisualEvidenceItem] = []
    for asset in sorted(snapshot.assets, key=lambda item: item.asset_id):
        encoded_task = quote(task.task_id, safe="")
        encoded_sample = quote(asset.asset_id, safe="")
        preview_url = (
            f"/v1/tasks/{encoded_task}/visual-evidence/{encoded_sample}/preview"
        )
        mask_url = (
            f"/v1/tasks/{encoded_task}/visual-evidence/{encoded_sample}/mask"
            if asset.mask_sha256 is not None
            else None
        )
        stable: dict[str, Any] = {
            "sample_id": asset.asset_id,
            "original_name": asset.original_name,
            "width": asset.width,
            "height": asset.height,
            "source_sha256": asset.source_sha256,
            "preview_sha256": asset.preview_sha256,
            "annotation_revision": asset.annotation_revision,
            "annotation_document_sha256": asset.annotation_document_sha256,
            "annotation_count": asset.annotation_count,
            "mask_sha256": asset.mask_sha256,
            "preview_url": preview_url,
            "mask_url": mask_url,
            "affected": bool(
                finding_ids[asset.asset_id] or issue_codes[asset.asset_id]
            ),
            "finding_ids": sorted(finding_ids[asset.asset_id]),
            "issue_codes": sorted(issue_codes[asset.asset_id]),
            "tools": sorted(tools[asset.asset_id]),
            "work_order_ids": sorted(work_order_ids[asset.asset_id]),
            "measurements": [
                item.model_dump(mode="json")
                for item in sorted(
                    measurements[asset.asset_id].values(),
                    key=lambda value: (
                        value.code,
                        value.finding_id,
                        value.evidence_sha256,
                    ),
                )
            ],
        }
        items.append(
            TaskVisualEvidenceItem.model_validate(
                {**stable, "item_sha256": _sha256_payload(stable)}
            )
        )

    stable_manifest: dict[str, Any] = {
        "schema_version": "visiondata-gate.task-visual-evidence.v1",
        "task_id": task.task_id,
        "workspace_id": task.workspace_id,
        "project_id": task.project_id,
        "source_id": task.source_id,
        "task_request_sha256": task.request_sha256,
        "task_evidence_sha256": task.evidence_sha256,
        "source_profile_sha256": source_profile_sha256,
        "operator_snapshot_receipt_sha256": snapshot.receipt_sha256,
        "visual_count": len(items),
        "affected_count": sum(item.affected for item in items),
        "items": [item.model_dump(mode="json") for item in items],
        "read_only": True,
        "raw_images_transmitted": False,
        "production_release_allowed": False,
        "claim_boundary": TaskVisualEvidenceManifest.model_fields[
            "claim_boundary"
        ].default,
    }
    return TaskVisualEvidenceManifest.model_validate(
        {
            **stable_manifest,
            "manifest_sha256": _sha256_payload(stable_manifest),
        }
    )
