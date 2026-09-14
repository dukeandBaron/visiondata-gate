"""Immutable Operator Project snapshots for Product Agent execution.

The server reads the actor-scoped ``OperatorImageStore``, verifies source/preview
bytes and the append-only annotation chain, then materializes one private,
immutable dataset snapshot. Explicit requirements may assert reviewed digests;
these are compared with server-verified identities, never trusted as their source.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
import hashlib
import hmac
import os
from pathlib import Path
import shutil
import tempfile
from typing import Literal

from PIL import Image, ImageDraw
from pydantic import BaseModel, ConfigDict, Field, model_validator

from .audit_envelope import canonical_jcs_bytes
from .contracts import (
    BatchContract,
    BatchManifest,
    CoverageContract,
    OperatorAcceptanceRequirements,
    OperatorSampleAcceptanceRequirement,
    QualityThresholds,
    SampleRecord,
)
from .operator_workspace import OperatorImageStore
from .pipeline import compute_batch_digest


_SHA256_PATTERN = r"^[0-9a-f]{64}$"
_ADAPTER_KIND = "operator_project_snapshot"
_RECEIPT_NAME = "operator_project_snapshot_receipt.json"
_HASH_CHUNK_BYTES = 64 * 1024


def _now() -> str:
    return datetime.now(UTC).isoformat(timespec="milliseconds")


def _sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(_HASH_CHUNK_BYTES), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _safe_member(root: Path, relative: str) -> Path:
    normalized = relative.replace("\\", "/")
    if normalized.startswith("/") or ".." in normalized.split("/"):
        raise ValueError("operator snapshot member path is unsafe")
    candidate = root.joinpath(*normalized.split("/")).resolve(strict=False)
    try:
        candidate.relative_to(root)
    except ValueError as exc:
        raise ValueError("operator snapshot member escaped its root") from exc
    return candidate


class OperatorSnapshotAssetBinding(BaseModel):
    """One immutable source/preview/annotation identity inside a snapshot."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    asset_id: str = Field(min_length=1)
    original_name: str = Field(min_length=1)
    width: int = Field(ge=1)
    height: int = Field(ge=1)
    source_relative_path: str = Field(min_length=1)
    source_sha256: str = Field(pattern=_SHA256_PATTERN)
    preview_relative_path: str = Field(min_length=1)
    preview_sha256: str = Field(pattern=_SHA256_PATTERN)
    annotation_revision: int = Field(ge=0)
    annotation_document_sha256: str = Field(pattern=_SHA256_PATTERN)
    annotation_count: int = Field(ge=0)
    mask_relative_path: str | None = None
    mask_sha256: str | None = Field(default=None, pattern=_SHA256_PATTERN)

    @model_validator(mode="after")
    def require_mask_pair(self) -> "OperatorSnapshotAssetBinding":
        if (self.mask_relative_path is None) != (self.mask_sha256 is None):
            raise ValueError("operator snapshot mask path and digest must be paired")
        if self.annotation_count > 0 and self.mask_relative_path is None:
            raise ValueError("annotated operator assets require a frozen mask")
        if self.annotation_count == 0 and self.mask_relative_path is not None:
            raise ValueError("unannotated operator assets cannot claim a mask")
        return self


class OperatorProjectSnapshotReceipt(BaseModel):
    """JCS/SHA-sealed identity for one server-materialized project snapshot."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_version: Literal[
        "visiondata-gate.operator-project-snapshot.v1",
        "visiondata-gate.operator-project-snapshot.v2",
    ] = "visiondata-gate.operator-project-snapshot.v1"
    adapter_kind: Literal["operator_project_snapshot"] = _ADAPTER_KIND
    snapshot_id: str = Field(pattern=r"^opsnap_[0-9a-f]{20}$")
    workspace_id: str = Field(min_length=1)
    project_id: str = Field(min_length=1)
    actor_id: str = Field(min_length=1)
    created_at: str = Field(min_length=1)
    asset_count: int = Field(ge=1)
    assets: list[OperatorSnapshotAssetBinding] = Field(min_length=1)
    snapshot_binding_sha256: str = Field(pattern=_SHA256_PATTERN)
    batch_manifest_relative_path: Literal["batch_manifest.json"] = "batch_manifest.json"
    batch_manifest_sha256: str = Field(pattern=_SHA256_PATTERN)
    batch_contract_relative_path: Literal["batch_contract.json"] = "batch_contract.json"
    batch_contract_sha256: str = Field(pattern=_SHA256_PATTERN)
    batch_digest_sha256: str = Field(pattern=_SHA256_PATTERN)
    source_assets_copied_into_product: Literal[True] = True
    raw_images_transmitted: Literal[False] = False
    machine_write_permitted: Literal[False] = False
    production_release_allowed: Literal[False] = False
    receipt_sha256: str = Field(pattern=_SHA256_PATTERN)
    acceptance_requirements: OperatorAcceptanceRequirements | None = Field(
        default=None, exclude_if=lambda value: value is None
    )
    claim_boundary: str = (
        "This receipt proves a private local snapshot of the named operator project "
        "at the recorded asset and annotation revisions. It is not factory shadow "
        "validation, customer acceptance, or production authorization."
    )

    @model_validator(mode="after")
    def validate_asset_count(self) -> "OperatorProjectSnapshotReceipt":
        if self.asset_count != len(self.assets):
            raise ValueError("operator snapshot asset count mismatch")
        asset_ids = [item.asset_id for item in self.assets]
        if len(asset_ids) != len(set(asset_ids)):
            raise ValueError("operator snapshot asset IDs must be unique")
        if self.schema_version.endswith(".v2") != (
            self.acceptance_requirements is not None
        ):
            raise ValueError("v2 snapshot requires explicit acceptance requirements")
        return self


@dataclass(frozen=True)
class MaterializedOperatorProjectSnapshot:
    root: Path
    receipt: OperatorProjectSnapshotReceipt
    source_profile: dict[str, object]


def _snapshot_binding_payload(
    *,
    workspace_id: str,
    project_id: str,
    actor_id: str,
    assets: list[OperatorSnapshotAssetBinding],
    acceptance_requirements: OperatorAcceptanceRequirements | None = None,
) -> dict[str, object]:
    payload: dict[str, object] = {
        "schema_version": "visiondata-gate.operator-project-snapshot-binding.v1",
        "adapter_kind": _ADAPTER_KIND,
        "workspace_id": workspace_id,
        "project_id": project_id,
        "actor_id": actor_id,
        "assets": [item.model_dump(mode="json") for item in assets],
    }
    if acceptance_requirements is not None:
        payload["schema_version"] = (
            "visiondata-gate.operator-project-snapshot-binding.v2"
        )
        payload["acceptance_requirements"] = acceptance_requirements.model_dump(
            mode="json"
        )
    return payload


def _profile_from_receipt(receipt: OperatorProjectSnapshotReceipt) -> dict[str, object]:
    stable: dict[str, object] = {
        "schema_version": "visiondata-gate.operator-project-snapshot-profile.v1",
        "adapter_kind": _ADAPTER_KIND,
        "snapshot_id": receipt.snapshot_id,
        "workspace_id": receipt.workspace_id,
        "project_id": receipt.project_id,
        "actor_id": receipt.actor_id,
        "asset_count": receipt.asset_count,
        "source_image_count": receipt.asset_count,
        "source_mask_count": sum(
            item.mask_relative_path is not None for item in receipt.assets
        ),
        "metadata_image_count": receipt.asset_count,
        "snapshot_binding_sha256": receipt.snapshot_binding_sha256,
        "operator_snapshot_receipt_sha256": receipt.receipt_sha256,
        "batch_manifest_sha256": receipt.batch_manifest_sha256,
        "batch_contract_sha256": receipt.batch_contract_sha256,
        "batch_digest_sha256": receipt.batch_digest_sha256,
        "source_assets_copied_into_product": True,
        "raw_images_transmitted": False,
        "production_release_allowed": False,
    }
    if receipt.acceptance_requirements is not None:
        stable["schema_version"] = (
            "visiondata-gate.operator-project-snapshot-profile.v2"
        )
        stable["acceptance_requirements_sha256"] = _sha256_bytes(
            canonical_jcs_bytes(receipt.acceptance_requirements.model_dump(mode="json"))
        )
    return {
        **stable,
        "profile_sha256": _sha256_bytes(canonical_jcs_bytes(stable)),
    }


def _write_jcs(path: Path, value: object) -> str:
    data = canonical_jcs_bytes(value)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("xb") as handle:
        handle.write(data)
        handle.flush()
        os.fsync(handle.fileno())
    return _sha256_bytes(data)


def _mask_for_annotations(
    path: Path,
    *,
    width: int,
    height: int,
    annotations: list[object],
) -> str:
    mask = Image.new("L", (width, height), color=0)
    draw = ImageDraw.Draw(mask)
    for annotation in annotations:
        x = float(getattr(annotation, "x"))
        y = float(getattr(annotation, "y"))
        box_width = float(getattr(annotation, "width"))
        box_height = float(getattr(annotation, "height"))
        left = max(0, min(width - 1, int(x * width)))
        top = max(0, min(height - 1, int(y * height)))
        right = max(left, min(width - 1, int((x + box_width) * width - 1e-9)))
        bottom = max(top, min(height - 1, int((y + box_height) * height - 1e-9)))
        draw.rectangle((left, top, right, bottom), fill=255)
    path.parent.mkdir(parents=True, exist_ok=True)
    mask.save(path, format="PNG", optimize=False, compress_level=9)
    return _sha256_file(path)


def _verify_receipt_digest(receipt: OperatorProjectSnapshotReceipt) -> None:
    stable = receipt.model_dump(mode="json", exclude={"receipt_sha256"})
    observed = _sha256_bytes(canonical_jcs_bytes(stable))
    if not hmac.compare_digest(observed, receipt.receipt_sha256):
        raise ValueError("operator project snapshot receipt digest mismatch")


def _validate_acceptance_asset(
    requirement: OperatorSampleAcceptanceRequirement,
    asset: OperatorSnapshotAssetBinding,
) -> None:
    review = requirement.human_review
    if not (
        hmac.compare_digest(review.expected_asset_sha256, asset.source_sha256)
        and review.expected_annotation_revision == asset.annotation_revision
        and hmac.compare_digest(
            review.expected_annotation_sha256, asset.annotation_document_sha256
        )
    ):
        raise ValueError(
            "human annotation review does not match the current asset revision"
        )
    policy = requirement.annotation_requirement
    if policy == "UNKNOWN":
        raise ValueError(
            "unknown annotation requirements must be resolved before snapshotting"
        )
    if policy == "REQUIRED" and asset.annotation_count == 0:
        raise ValueError("a required annotation is missing")
    if policy == "NOT_APPLICABLE" and asset.annotation_count != 0:
        raise ValueError("a not-applicable sample cannot contain annotations")


def profile_operator_project_snapshot(
    root: str | Path,
    *,
    expected_receipt_sha256: str | None = None,
) -> dict[str, object]:
    """Recompute every persisted binding before a Product Agent may read it."""

    snapshot_root = Path(root).expanduser().resolve(strict=True)
    if not snapshot_root.is_dir() or snapshot_root.is_symlink():
        raise ValueError("operator project snapshot root is not a regular directory")
    receipt_path = snapshot_root / _RECEIPT_NAME
    if not receipt_path.is_file() or receipt_path.is_symlink():
        raise ValueError("operator project snapshot receipt is unavailable")
    receipt_bytes = receipt_path.read_bytes()
    receipt = OperatorProjectSnapshotReceipt.model_validate_json(receipt_bytes)
    if receipt_bytes != canonical_jcs_bytes(receipt.model_dump(mode="json")):
        raise ValueError("operator project snapshot receipt is not canonical JCS")
    _verify_receipt_digest(receipt)
    if receipt.snapshot_id != snapshot_root.name:
        raise ValueError("operator project snapshot path identity mismatch")
    if expected_receipt_sha256 is not None and not hmac.compare_digest(
        expected_receipt_sha256, receipt.receipt_sha256
    ):
        raise ValueError("operator project snapshot authorization binding mismatch")

    for asset in receipt.assets:
        members = [
            (asset.source_relative_path, asset.source_sha256),
            (asset.preview_relative_path, asset.preview_sha256),
        ]
        if asset.mask_relative_path is not None and asset.mask_sha256 is not None:
            members.append((asset.mask_relative_path, asset.mask_sha256))
        for relative, expected in members:
            candidate = _safe_member(snapshot_root, relative).resolve(strict=True)
            if not candidate.is_file() or candidate.is_symlink():
                raise ValueError("operator project snapshot member is unavailable")
            if not hmac.compare_digest(_sha256_file(candidate), expected):
                raise ValueError("operator project snapshot member digest mismatch")

    manifest_path = _safe_member(snapshot_root, receipt.batch_manifest_relative_path)
    contract_path = _safe_member(snapshot_root, receipt.batch_contract_relative_path)
    if not (
        manifest_path.is_file()
        and contract_path.is_file()
        and hmac.compare_digest(
            _sha256_file(manifest_path), receipt.batch_manifest_sha256
        )
        and hmac.compare_digest(
            _sha256_file(contract_path), receipt.batch_contract_sha256
        )
    ):
        raise ValueError("operator project snapshot manifest or contract drifted")
    manifest = BatchManifest.model_validate_json(manifest_path.read_bytes())
    contract = BatchContract.model_validate_json(contract_path.read_bytes())
    requirements = receipt.acceptance_requirements
    if requirements is not None:
        requirements_sha256 = _sha256_bytes(
            canonical_jcs_bytes(requirements.model_dump(mode="json"))
        )
        expected_policies = {
            item.asset_id: item.annotation_requirement for item in requirements.samples
        }
        if not (
            contract.schema_version == "2.0"
            and contract.acceptance_requirements_sha256 == requirements_sha256
            and contract.sample_annotation_requirements == expected_policies
        ):
            raise ValueError(
                "snapshot acceptance requirements do not match the frozen contract"
            )
        declared = {item.asset_id: item for item in requirements.samples}
        manifested = {item.sample_id: item for item in manifest.samples}
        if set(manifested) != {item.asset_id for item in receipt.assets}:
            raise ValueError("explicit snapshot manifest asset coverage mismatch")
        for asset in receipt.assets:
            if asset.asset_id not in declared:
                raise ValueError(
                    "snapshot asset has no explicit acceptance requirement"
                )
            requirement = declared[asset.asset_id]
            _validate_acceptance_asset(requirement, asset)
            sample = manifested[asset.asset_id]
            if (
                sample.split != requirement.split
                or sample.category != requirement.category
            ):
                raise ValueError(
                    "snapshot sample split or category violates explicit requirements"
                )
    observed_batch_digest = compute_batch_digest(
        snapshot_root / "batch", manifest, contract
    )
    if not hmac.compare_digest(observed_batch_digest, receipt.batch_digest_sha256):
        raise ValueError("operator project snapshot batch digest mismatch")

    binding_payload = _snapshot_binding_payload(
        workspace_id=receipt.workspace_id,
        project_id=receipt.project_id,
        actor_id=receipt.actor_id,
        assets=receipt.assets,
        acceptance_requirements=receipt.acceptance_requirements,
    )
    observed_binding = _sha256_bytes(canonical_jcs_bytes(binding_payload))
    if not hmac.compare_digest(observed_binding, receipt.snapshot_binding_sha256):
        raise ValueError("operator project snapshot identity binding mismatch")
    return _profile_from_receipt(receipt)


def materialize_operator_project_snapshot(
    store: OperatorImageStore,
    *,
    actor_user_id: str,
    workspace_id: str,
    project_id: str,
    snapshots_root: str | Path,
    seed: int = 20_260_829,
    acceptance_requirements: OperatorAcceptanceRequirements | None = None,
) -> MaterializedOperatorProjectSnapshot:
    """Create or reuse one content-addressed, actor/project-bound snapshot."""

    assets = store.list_assets(
        actor_user_id,
        workspace_id,
        project_id=project_id,
        include_unassigned=False,
    )
    if not assets:
        raise ValueError(
            "operator project snapshot requires at least one project asset"
        )

    requirements = (
        OperatorAcceptanceRequirements.model_validate(
            acceptance_requirements.model_dump(mode="json")
        )
        if acceptance_requirements is not None
        else None
    )
    declared = (
        {item.asset_id: item for item in requirements.samples} if requirements else {}
    )
    if requirements is not None and set(declared) != {
        asset.asset_id for asset in assets
    }:
        raise ValueError(
            "acceptance requirements must cover exactly all current project assets"
        )

    source_records: list[tuple[object, Path, Path, object]] = []
    identity_assets: list[OperatorSnapshotAssetBinding] = []
    for asset in sorted(assets, key=lambda item: item.asset_id):
        if asset.project_id != project_id:
            raise ValueError("operator asset escaped the requested project scope")
        source_path, _content_type, source_sha = store.file_variant(
            actor_user_id, workspace_id, asset.asset_id, "source"
        )
        preview_path, _preview_type, preview_sha = store.file_variant(
            actor_user_id, workspace_id, asset.asset_id, "preview"
        )
        annotations = store.get_annotations(actor_user_id, workspace_id, asset.asset_id)
        if not (
            hmac.compare_digest(source_sha, asset.source_sha256)
            and hmac.compare_digest(preview_sha, asset.preview_sha256)
            and hmac.compare_digest(annotations.asset_sha256, asset.source_sha256)
        ):
            raise ValueError("operator asset identity changed while snapshotting")
        source_relative = f"batch/images/{asset.asset_id}{source_path.suffix.lower()}"
        preview_relative = f"previews/{asset.asset_id}.jpg"
        mask_relative = (
            f"batch/masks/{asset.asset_id}.png" if annotations.annotations else None
        )
        identity_assets.append(
            OperatorSnapshotAssetBinding(
                asset_id=asset.asset_id,
                original_name=asset.original_name,
                width=asset.width,
                height=asset.height,
                source_relative_path=source_relative,
                source_sha256=asset.source_sha256,
                preview_relative_path=preview_relative,
                preview_sha256=asset.preview_sha256,
                annotation_revision=annotations.revision,
                annotation_document_sha256=annotations.document_sha256,
                annotation_count=len(annotations.annotations),
                mask_relative_path=mask_relative,
                mask_sha256="0" * 64 if mask_relative is not None else None,
            )
        )
        if requirements is not None:
            _validate_acceptance_asset(declared[asset.asset_id], identity_assets[-1])
            if any(
                item.label not in requirements.category_vocabulary
                for item in annotations.annotations
            ):
                raise ValueError(
                    "annotation label is outside the declared category vocabulary"
                )
        source_records.append((asset, source_path, preview_path, annotations))

    provisional_payload = _snapshot_binding_payload(
        workspace_id=workspace_id,
        project_id=project_id,
        actor_id=actor_user_id,
        assets=identity_assets,
        acceptance_requirements=requirements,
    )
    provisional_digest = _sha256_bytes(canonical_jcs_bytes(provisional_payload))
    snapshot_id = f"opsnap_{provisional_digest[:20]}"
    root = Path(snapshots_root).expanduser().resolve()
    root.mkdir(parents=True, exist_ok=True)
    destination = (root / snapshot_id).resolve()
    destination.relative_to(root)
    if destination.exists():
        profile = profile_operator_project_snapshot(destination)
        receipt = OperatorProjectSnapshotReceipt.model_validate_json(
            (destination / _RECEIPT_NAME).read_bytes()
        )
        return MaterializedOperatorProjectSnapshot(destination, receipt, profile)

    temp_root = Path(tempfile.mkdtemp(prefix=f".{snapshot_id}-", dir=root)).resolve()
    try:
        frozen_assets: list[OperatorSnapshotAssetBinding] = []
        sample_records: list[SampleRecord] = []
        categories: set[str] = set()
        for identity, source_record in zip(
            identity_assets, source_records, strict=True
        ):
            asset, source_path, preview_path, annotations = source_record
            frozen_source = _safe_member(temp_root, identity.source_relative_path)
            frozen_preview = _safe_member(temp_root, identity.preview_relative_path)
            frozen_source.parent.mkdir(parents=True, exist_ok=True)
            frozen_preview.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(source_path, frozen_source)
            shutil.copyfile(preview_path, frozen_preview)
            if not (
                hmac.compare_digest(_sha256_file(frozen_source), identity.source_sha256)
                and hmac.compare_digest(
                    _sha256_file(frozen_preview), identity.preview_sha256
                )
            ):
                raise ValueError("operator asset copy failed digest verification")
            mask_sha256 = None
            if identity.mask_relative_path is not None:
                mask_path = _safe_member(temp_root, identity.mask_relative_path)
                mask_sha256 = _mask_for_annotations(
                    mask_path,
                    width=int(getattr(asset, "width")),
                    height=int(getattr(asset, "height")),
                    annotations=list(getattr(annotations, "annotations")),
                )
            frozen = identity.model_copy(update={"mask_sha256": mask_sha256})
            frozen_assets.append(frozen)
            annotation_labels = {
                str(getattr(item, "label"))
                for item in getattr(annotations, "annotations")
            }
            categories.update(annotation_labels or {"unlabeled"})
            sample_records.append(
                SampleRecord(
                    sample_id=identity.asset_id,
                    relative_path=identity.source_relative_path.removeprefix("batch/"),
                    split="train",
                    category=sorted(annotation_labels)[0]
                    if annotation_labels
                    else "unlabeled",
                    view="operator",
                    condition="observed",
                    annotation_path=(
                        identity.mask_relative_path.removeprefix("batch/")
                        if identity.mask_relative_path is not None
                        else None
                    ),
                )
            )
            if requirements is not None:
                requirement = declared[identity.asset_id]
                sample_records[-1] = sample_records[-1].model_copy(
                    update={
                        "split": requirement.split,
                        "category": requirement.category,
                    }
                )

        first_asset = assets[0]
        manifest = BatchManifest(
            batch_id=snapshot_id,
            seed=seed,
            samples=sample_records,
        )
        contract = BatchContract(
            contract_id="visiondata-operator-project-snapshot-v1",
            required_splits=["train"],
            annotations_required=all(
                item.annotation_count > 0 for item in frozen_assets
            ),
            thresholds=QualityThresholds(
                expected_width=max(16, first_asset.width),
                expected_height=max(16, first_asset.height),
            ),
            coverage=CoverageContract(
                categories=sorted(categories),
                views=["operator"],
                conditions=["observed"],
                splits=["train"],
                min_per_cell=1,
            ),
            policy_version="operator-project-snapshot-policy-1.0",
        )
        if requirements is not None:
            declared_splits = sorted({item.split for item in requirements.samples})
            contract = BatchContract(
                schema_version="2.0",
                contract_id="visiondata-operator-project-snapshot-v2",
                required_splits=declared_splits,
                annotations_required=any(
                    item.annotation_requirement == "REQUIRED"
                    for item in requirements.samples
                ),
                thresholds=contract.thresholds,
                coverage=CoverageContract(
                    categories=sorted({item.category for item in requirements.samples}),
                    views=["operator"],
                    conditions=["observed"],
                    splits=declared_splits,
                    min_per_cell=1,
                ),
                policy_version="operator-project-snapshot-policy-2.0",
                acceptance_requirements_sha256=_sha256_bytes(
                    canonical_jcs_bytes(requirements.model_dump(mode="json"))
                ),
                sample_annotation_requirements={
                    item.asset_id: item.annotation_requirement
                    for item in requirements.samples
                },
            )
        manifest_sha256 = _write_jcs(
            temp_root / "batch_manifest.json", manifest.model_dump(mode="json")
        )
        contract_sha256 = _write_jcs(
            temp_root / "batch_contract.json", contract.model_dump(mode="json")
        )
        batch_digest = compute_batch_digest(temp_root / "batch", manifest, contract)
        binding_payload = _snapshot_binding_payload(
            workspace_id=workspace_id,
            project_id=project_id,
            actor_id=actor_user_id,
            assets=frozen_assets,
            acceptance_requirements=requirements,
        )
        snapshot_binding_sha256 = _sha256_bytes(canonical_jcs_bytes(binding_payload))
        stable_receipt = {
            "schema_version": "visiondata-gate.operator-project-snapshot.v1",
            "adapter_kind": _ADAPTER_KIND,
            "snapshot_id": snapshot_id,
            "workspace_id": workspace_id,
            "project_id": project_id,
            "actor_id": actor_user_id,
            "created_at": _now(),
            "asset_count": len(frozen_assets),
            "assets": [item.model_dump(mode="json") for item in frozen_assets],
            "snapshot_binding_sha256": snapshot_binding_sha256,
            "batch_manifest_relative_path": "batch_manifest.json",
            "batch_manifest_sha256": manifest_sha256,
            "batch_contract_relative_path": "batch_contract.json",
            "batch_contract_sha256": contract_sha256,
            "batch_digest_sha256": batch_digest,
            "source_assets_copied_into_product": True,
            "raw_images_transmitted": False,
            "machine_write_permitted": False,
            "production_release_allowed": False,
            "claim_boundary": OperatorProjectSnapshotReceipt.model_fields[
                "claim_boundary"
            ].default,
        }
        if requirements is not None:
            stable_receipt["schema_version"] = (
                "visiondata-gate.operator-project-snapshot.v2"
            )
            stable_receipt["acceptance_requirements"] = requirements.model_dump(
                mode="json"
            )
        receipt = OperatorProjectSnapshotReceipt(
            **stable_receipt,
            receipt_sha256=_sha256_bytes(canonical_jcs_bytes(stable_receipt)),
        )
        _write_jcs(temp_root / _RECEIPT_NAME, receipt.model_dump(mode="json"))
        temp_root.replace(destination)
    except Exception:
        if temp_root.exists():
            shutil.rmtree(temp_root)
        raise

    profile = profile_operator_project_snapshot(
        destination, expected_receipt_sha256=receipt.receipt_sha256
    )
    return MaterializedOperatorProjectSnapshot(destination, receipt, profile)


def materialize_operator_snapshot_subset(
    source_root: str | Path,
    *,
    snapshots_root: str | Path,
    retained_asset_ids: set[str],
    expected_receipt_sha256: str,
    created_at: str,
) -> MaterializedOperatorProjectSnapshot:
    """Seal a private subset; authorization and removal policy belong to CAPA.

    The original contract and every retained asset binding remain byte-identical.
    The manifest, batch digest and snapshot receipt receive new identities.
    """

    parent_root = Path(source_root).expanduser().resolve(strict=True)
    profile_operator_project_snapshot(
        parent_root, expected_receipt_sha256=expected_receipt_sha256
    )
    parent = OperatorProjectSnapshotReceipt.model_validate_json(
        (parent_root / _RECEIPT_NAME).read_bytes()
    )
    all_ids = {asset.asset_id for asset in parent.assets}
    if not retained_asset_ids or not retained_asset_ids < all_ids:
        raise ValueError("derived snapshot requires a nonempty proper asset subset")
    retained = [
        asset for asset in parent.assets if asset.asset_id in retained_asset_ids
    ]
    subset_identity = {
        "schema_version": "visiondata-gate.operator-snapshot-subset.v1",
        "parent_receipt_sha256": expected_receipt_sha256,
        "retained_asset_ids": sorted(retained_asset_ids),
    }
    snapshot_id = "opsnap_" + _sha256_bytes(canonical_jcs_bytes(subset_identity))[:20]
    output_root = Path(snapshots_root).expanduser().resolve(strict=True)
    destination = output_root / snapshot_id
    destination.mkdir(exist_ok=False)
    members = {parent.batch_contract_relative_path: parent.batch_contract_sha256}
    for asset in retained:
        members[asset.source_relative_path] = asset.source_sha256
        members[asset.preview_relative_path] = asset.preview_sha256
        if asset.mask_relative_path is not None and asset.mask_sha256 is not None:
            members[asset.mask_relative_path] = asset.mask_sha256
    for relative, expected in sorted(members.items()):
        source = _safe_member(parent_root, relative)
        target = _safe_member(destination, relative)
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(source, target)
        if not hmac.compare_digest(_sha256_file(target), expected):
            raise ValueError("derived snapshot retained member digest mismatch")
    manifest = BatchManifest.model_validate_json(
        (parent_root / parent.batch_manifest_relative_path).read_bytes()
    )
    if {sample.sample_id for sample in manifest.samples} != all_ids:
        raise ValueError("snapshot manifest samples do not match asset bindings")
    derived_manifest = manifest.model_copy(
        update={
            "batch_id": snapshot_id,
            "samples": [
                sample
                for sample in manifest.samples
                if sample.sample_id in retained_asset_ids
            ],
        }
    )
    manifest_sha = _write_jcs(
        destination / parent.batch_manifest_relative_path,
        derived_manifest.model_dump(mode="json"),
    )
    contract = BatchContract.model_validate_json(
        (destination / parent.batch_contract_relative_path).read_bytes()
    )
    binding = _snapshot_binding_payload(
        workspace_id=parent.workspace_id,
        project_id=parent.project_id,
        actor_id=parent.actor_id,
        assets=retained,
        acceptance_requirements=parent.acceptance_requirements,
    )
    stable = parent.model_dump(mode="json", exclude={"receipt_sha256"})
    stable.update(
        {
            "snapshot_id": snapshot_id,
            "created_at": created_at,
            "asset_count": len(retained),
            "assets": [asset.model_dump(mode="json") for asset in retained],
            "snapshot_binding_sha256": _sha256_bytes(canonical_jcs_bytes(binding)),
            "batch_manifest_sha256": manifest_sha,
            "batch_digest_sha256": compute_batch_digest(
                destination / "batch", derived_manifest, contract
            ),
        }
    )
    receipt = OperatorProjectSnapshotReceipt(
        **stable, receipt_sha256=_sha256_bytes(canonical_jcs_bytes(stable))
    )
    _write_jcs(destination / _RECEIPT_NAME, receipt.model_dump(mode="json"))
    profile_operator_project_snapshot(
        parent_root, expected_receipt_sha256=expected_receipt_sha256
    )
    profile = profile_operator_project_snapshot(
        destination, expected_receipt_sha256=receipt.receipt_sha256
    )
    return MaterializedOperatorProjectSnapshot(destination, receipt, profile)


__all__ = [
    "MaterializedOperatorProjectSnapshot",
    "OperatorProjectSnapshotReceipt",
    "OperatorSnapshotAssetBinding",
    "materialize_operator_project_snapshot",
    "materialize_operator_snapshot_subset",
    "profile_operator_project_snapshot",
]
