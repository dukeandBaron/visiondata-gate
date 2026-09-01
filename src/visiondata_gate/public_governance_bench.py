"""Frozen contracts for public industrial proxy governance evaluation.

Public anomaly labels describe product condition; they are never treated as
dataset-release governance truth.  This module indexes a locally authorized
VisA checkout, binds license/header/source digests, and derives detached truth
only from a frozen programmatic governance protocol.

The module does not download data, mutate the source dataset, call a model, or
authorize production release.
"""

from __future__ import annotations

import csv
from datetime import datetime
import hashlib
import hmac
import io
from pathlib import Path, PurePosixPath
import re
from typing import Literal, Sequence

from pydantic import Field, field_validator, model_validator

from .audit_envelope import canonical_jcs_bytes
from .evidence import sha256_file
from .governance_effectiveness_v2 import GovernanceTruthBindingV2
from .product_models import ProductModel


SHA256_PATTERN = r"^[0-9a-f]{64}$"
SAFE_ID_PATTERN = r"^[A-Za-z0-9][A-Za-z0-9_.:-]{1,159}$"
PUBLIC_BENCH_FRAME_MAGIC = b"visiondata-gate.public-governance-bench.v1\x00"
OFFICIAL_VISA_1CLS_HEADER = ("object", "split", "label", "image", "mask")

ProgrammaticCaseType = Literal[
    "CLEAN_CONTROL",
    "EXACT_CROSS_SPLIT_DUPLICATE",
    "IMAGE_DECODE_CORRUPTED",
    "ANOMALY_MASK_MISSING",
    "IMAGE_MASK_PAIR_SWAPPED",
    "MASK_DIMENSION_MISMATCH",
    "LABEL_MASK_CONTRADICTION",
    "MANIFEST_DUPLICATE_SAMPLE_ID",
    "PATH_TRAVERSAL_REFERENCE",
    "BLUR_THRESHOLD",
    "EXPOSURE_THRESHOLD",
    "NEAR_DUPLICATE",
    "MULTIVIEW_SIMILARITY",
    "CLASS_BALANCE_DRIFT",
    "LOGICAL_ANOMALY_STAGE_SUITABILITY",
]

AUTO_BLOCK_TYPES = frozenset(
    {
        "EXACT_CROSS_SPLIT_DUPLICATE",
        "IMAGE_DECODE_CORRUPTED",
        "ANOMALY_MASK_MISSING",
        "IMAGE_MASK_PAIR_SWAPPED",
        "MASK_DIMENSION_MISMATCH",
        "LABEL_MASK_CONTRADICTION",
        "MANIFEST_DUPLICATE_SAMPLE_ID",
        "PATH_TRAVERSAL_REFERENCE",
    }
)
PENDING_ADJUDICATION_TYPES = frozenset(
    {
        "BLUR_THRESHOLD",
        "EXPOSURE_THRESHOLD",
        "NEAR_DUPLICATE",
        "MULTIVIEW_SIMILARITY",
        "CLASS_BALANCE_DRIFT",
        "LOGICAL_ANOMALY_STAGE_SUITABILITY",
    }
)

_PROGRAMMATIC_PROTOCOL = {
    "protocol_id": "PUBLIC_GOVERNANCE_BENCH_V1",
    "clean_control_disposition": "RELEASE_ALLOWED",
    "auto_block_types": sorted(AUTO_BLOCK_TYPES),
    "pending_adjudication_types": sorted(PENDING_ADJUDICATION_TYPES),
    "dataset_product_label_governance_authority": "none",
    "source_dataset_mutated": False,
    "production_release_allowed": False,
}


class SourceSchemaDeferredError(ValueError):
    """The source schema was not explicitly mapped and must not be guessed."""


def _aware(value: datetime) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("timestamp must include an explicit UTC offset")
    return value


def _domain_sha256(domain: str, value: object) -> str:
    domain_bytes = domain.encode("utf-8")
    payload = canonical_jcs_bytes(value)
    frame = b"".join(
        (
            PUBLIC_BENCH_FRAME_MAGIC,
            len(domain_bytes).to_bytes(2, "big"),
            domain_bytes,
            len(payload).to_bytes(8, "big"),
            payload,
        )
    )
    return hashlib.sha256(frame).hexdigest()


def _seal(model: ProductModel, field: str, *, domain: str) -> str:
    return _domain_sha256(
        domain,
        model.model_dump(mode="json", exclude={field}),
    )


def _sealed_model(
    model_type: type[ProductModel],
    field: str,
    stable: dict[str, object],
    *,
    domain: str,
) -> ProductModel:
    draft = model_type(**stable, **{field: "0" * 64})
    return draft.model_copy(update={field: _seal(draft, field, domain=domain)})


def _verify_seal(
    model: ProductModel,
    field: str,
    *,
    domain: str,
    message: str,
) -> None:
    if not hmac.compare_digest(
        getattr(model, field),
        _seal(model, field, domain=domain),
    ):
        raise ValueError(message)


def _safe_relative_path(value: str, *, field_name: str) -> str:
    if not value or "\\" in value or "\0" in value or "\r" in value or "\n" in value:
        raise ValueError(f"{field_name} must be a non-empty POSIX relative path")
    if re.match(r"^[A-Za-z]:", value):
        raise ValueError(f"{field_name} cannot contain a drive path")
    relative = PurePosixPath(value)
    if relative.is_absolute() or any(
        part in {"", ".", ".."} for part in relative.parts
    ):
        raise ValueError(f"{field_name} escaped the dataset root")
    return relative.as_posix()


def _resolve_source_member(root: Path, relative: str) -> Path:
    safe = _safe_relative_path(relative, field_name="source asset path")
    candidate = (root / Path(*PurePosixPath(safe).parts)).resolve(strict=True)
    try:
        candidate.relative_to(root)
    except ValueError as error:
        raise ValueError("source asset path escaped the dataset root") from error
    if not candidate.is_file():
        raise ValueError("source asset path must resolve to a file")
    return candidate


def visa_csv_header_sha256(fieldnames: Sequence[str]) -> str:
    if not fieldnames or any(not item for item in fieldnames):
        raise ValueError("VisA CSV header cannot be empty")
    if len(fieldnames) != len(set(fieldnames)):
        raise ValueError("VisA CSV header contains duplicate columns")
    return _domain_sha256("visa-csv-header", list(fieldnames))


class PublicSourceBinding(ProductModel):
    schema_version: Literal["visiondata-gate.public-source-binding.v1"] = (
        "visiondata-gate.public-source-binding.v1"
    )
    dataset_id: Literal["VisA"] = "VisA"
    dataset_version: str = Field(min_length=1, max_length=80)
    source_homepage_url: str = Field(min_length=12, max_length=500)
    source_archive_sha256: str = Field(pattern=SHA256_PATTERN)
    license_id: Literal["CC-BY-4.0"] = "CC-BY-4.0"
    license_text_sha256: str = Field(pattern=SHA256_PATTERN)
    attribution_text_sha256: str = Field(pattern=SHA256_PATTERN)
    rights_review_status: Literal["OPERATOR_ATTESTED_NOT_LEGAL_OPINION"] = (
        "OPERATOR_ATTESTED_NOT_LEGAL_OPINION"
    )
    local_authorized_read_only: Literal[True] = True
    raw_redistribution_performed: Literal[False] = False
    product_label_role: Literal["PRODUCT_CONDITION_ONLY_NOT_GOVERNANCE_TRUTH"] = (
        "PRODUCT_CONDITION_ONLY_NOT_GOVERNANCE_TRUTH"
    )
    bound_at: datetime
    binding_sha256: str = Field(pattern=SHA256_PATTERN)

    @field_validator("source_homepage_url")
    @classmethod
    def require_https_homepage(cls, value: str) -> str:
        if not value.startswith("https://") or "\0" in value:
            raise ValueError("public source homepage must use HTTPS")
        return value

    @field_validator("bound_at")
    @classmethod
    def validate_bound_at(cls, value: datetime) -> datetime:
        return _aware(value)


class VisaColumnMapping(ProductModel):
    object_column: str = Field(min_length=1, max_length=160)
    split_column: str = Field(min_length=1, max_length=160)
    product_label_column: str = Field(min_length=1, max_length=160)
    image_path_column: str = Field(min_length=1, max_length=160)
    mask_path_column: str = Field(min_length=1, max_length=160)

    @model_validator(mode="after")
    def require_distinct_columns(self) -> VisaColumnMapping:
        values = list(self.model_dump().values())
        if len(values) != len(set(values)):
            raise ValueError("VisA semantic columns must map to distinct CSV columns")
        return self


def official_visa_1cls_column_mapping() -> VisaColumnMapping:
    """Return the explicit semantic mapping for the official 1cls.csv header."""

    return VisaColumnMapping(
        object_column="object",
        split_column="split",
        product_label_column="label",
        image_path_column="image",
        mask_path_column="mask",
    )


class VisaSourceSample(ProductModel):
    source_sample_id: str = Field(pattern=r"^visa_[0-9a-f]{24}$")
    row_number: int = Field(ge=2)
    object_class: str = Field(min_length=1, max_length=160)
    split: str = Field(min_length=1, max_length=80)
    product_label: str = Field(min_length=1, max_length=160)
    image_relative_path: str = Field(min_length=1, max_length=500)
    image_sha256: str = Field(pattern=SHA256_PATTERN)
    image_size_bytes: int = Field(gt=0)
    mask_relative_path: str | None = Field(default=None, max_length=500)
    mask_sha256: str | None = Field(default=None, pattern=SHA256_PATTERN)
    mask_size_bytes: int | None = Field(default=None, gt=0)
    product_label_governance_authority: Literal["none"] = "none"
    sample_sha256: str = Field(pattern=SHA256_PATTERN)

    @model_validator(mode="after")
    def validate_mask_binding(self) -> VisaSourceSample:
        mask_values = (
            self.mask_relative_path,
            self.mask_sha256,
            self.mask_size_bytes,
        )
        if any(value is None for value in mask_values) and not all(
            value is None for value in mask_values
        ):
            raise ValueError(
                "VisA mask path, digest, and size must be all present or absent"
            )
        return self


class VisaSourceIndex(ProductModel):
    schema_version: Literal["visiondata-gate.visa-source-index.v1"] = (
        "visiondata-gate.visa-source-index.v1"
    )
    source_binding_sha256: str = Field(pattern=SHA256_PATTERN)
    split_csv_relative_path: str = Field(min_length=1, max_length=500)
    split_csv_sha256: str = Field(pattern=SHA256_PATTERN)
    csv_header: list[str] = Field(min_length=1)
    csv_header_sha256: str = Field(pattern=SHA256_PATTERN)
    column_mapping: VisaColumnMapping
    sample_count: int = Field(ge=1)
    samples: list[VisaSourceSample] = Field(min_length=1)
    source_assets_copied: Literal[False] = False
    product_labels_used_as_governance_truth: Literal[False] = False
    index_sha256: str = Field(pattern=SHA256_PATTERN)

    @model_validator(mode="after")
    def validate_index_counts(self) -> VisaSourceIndex:
        if self.sample_count != len(self.samples):
            raise ValueError("VisA source index sample count does not reconcile")
        sample_ids = [item.source_sample_id for item in self.samples]
        if len(sample_ids) != len(set(sample_ids)):
            raise ValueError("VisA source index contains duplicate sample IDs")
        if not hmac.compare_digest(
            self.csv_header_sha256,
            visa_csv_header_sha256(self.csv_header),
        ):
            raise ValueError("VisA CSV header digest does not reconcile")
        return self


class CreateProgrammaticGovernanceCase(ProductModel):
    unit_id: str = Field(pattern=SAFE_ID_PATTERN)
    source_sample_id: str = Field(pattern=r"^visa_[0-9a-f]{24}$")
    case_type: ProgrammaticCaseType
    parameters_sha256: str = Field(pattern=SHA256_PATTERN)
    derived_artifact_relative_paths: list[str] = Field(default_factory=list)

    @field_validator("derived_artifact_relative_paths")
    @classmethod
    def validate_derived_paths(cls, values: list[str]) -> list[str]:
        normalized = [
            _safe_relative_path(value, field_name="derived artifact path")
            for value in values
        ]
        if len(normalized) != len(set(normalized)):
            raise ValueError("derived artifact paths must be unique")
        return normalized


class ProgrammaticGovernanceCase(ProductModel):
    unit_id: str = Field(pattern=SAFE_ID_PATTERN)
    source_sample_id: str = Field(pattern=r"^visa_[0-9a-f]{24}$")
    source_sample_sha256: str = Field(pattern=SHA256_PATTERN)
    source_product_label: str = Field(min_length=1, max_length=160)
    case_type: ProgrammaticCaseType
    parameters_sha256: str = Field(pattern=SHA256_PATTERN)
    derived_artifact_relative_paths: list[str]
    truth_status: Literal["ADJUDICATED", "PENDING_ADJUDICATION"]
    truth_disposition: Literal["BLOCK_REQUIRED", "RELEASE_ALLOWED"] | None = None
    truth_method: Literal["FROZEN_PROGRAMMATIC_GOVERNANCE_INJECTION"] | None = None
    pending_reason: str | None = Field(default=None, min_length=8, max_length=500)
    product_label_used_as_governance_truth: Literal[False] = False
    source_dataset_mutated: Literal[False] = False
    production_release_allowed: Literal[False] = False
    case_sha256: str = Field(pattern=SHA256_PATTERN)

    @model_validator(mode="after")
    def validate_truth_boundary(self) -> ProgrammaticGovernanceCase:
        if self.case_type == "CLEAN_CONTROL":
            expected = ("ADJUDICATED", "RELEASE_ALLOWED")
        elif self.case_type in AUTO_BLOCK_TYPES:
            expected = ("ADJUDICATED", "BLOCK_REQUIRED")
        elif self.case_type in PENDING_ADJUDICATION_TYPES:
            expected = ("PENDING_ADJUDICATION", None)
        else:  # pragma: no cover - Literal and frozen sets make this defensive.
            raise ValueError("unsupported programmatic governance case type")
        if (self.truth_status, self.truth_disposition) != expected:
            raise ValueError(
                "programmatic governance truth escaped the frozen protocol"
            )
        if self.truth_status == "ADJUDICATED":
            if self.truth_method is None or self.pending_reason is not None:
                raise ValueError("adjudicated programmatic truth is incomplete")
        elif self.truth_method is not None or self.pending_reason is None:
            raise ValueError(
                "pending programmatic truth requires only a pending reason"
            )
        return self


class ProgrammaticGovernanceInjectionManifest(ProductModel):
    schema_version: Literal[
        "visiondata-gate.programmatic-governance-injection-manifest.v1"
    ] = "visiondata-gate.programmatic-governance-injection-manifest.v1"
    evaluation_scope: Literal[
        "PUBLIC_INDUSTRIAL_PROXY_WITH_PROGRAMMATIC_GOVERNANCE_TRUTH"
    ] = "PUBLIC_INDUSTRIAL_PROXY_WITH_PROGRAMMATIC_GOVERNANCE_TRUTH"
    source_binding_sha256: str = Field(pattern=SHA256_PATTERN)
    source_index_sha256: str = Field(pattern=SHA256_PATTERN)
    protocol_id: Literal["PUBLIC_GOVERNANCE_BENCH_V1"] = "PUBLIC_GOVERNANCE_BENCH_V1"
    protocol_sha256: str = Field(pattern=SHA256_PATTERN)
    deterministic_seed: int = Field(ge=0)
    created_at: datetime
    case_count: int = Field(ge=1)
    cases: list[ProgrammaticGovernanceCase] = Field(min_length=1)
    source_dataset_mutated: Literal[False] = False
    raw_images_transmitted: Literal[False] = False
    product_labels_used_as_governance_truth: Literal[False] = False
    manifest_sha256: str = Field(pattern=SHA256_PATTERN)

    @field_validator("created_at")
    @classmethod
    def validate_created_at(cls, value: datetime) -> datetime:
        return _aware(value)

    @model_validator(mode="after")
    def validate_manifest_counts(self) -> ProgrammaticGovernanceInjectionManifest:
        if self.case_count != len(self.cases):
            raise ValueError("programmatic manifest case count does not reconcile")
        unit_ids = [item.unit_id for item in self.cases]
        if len(unit_ids) != len(set(unit_ids)):
            raise ValueError("programmatic manifest contains duplicate unit IDs")
        if not hmac.compare_digest(
            self.protocol_sha256,
            _domain_sha256("programmatic-protocol", _PROGRAMMATIC_PROTOCOL),
        ):
            raise ValueError("programmatic manifest protocol digest is not trusted")
        return self


class ProgrammaticGovernanceTruthUnit(ProductModel):
    unit_id: str = Field(pattern=SAFE_ID_PATTERN)
    source_sample_id: str = Field(pattern=r"^visa_[0-9a-f]{24}$")
    programmatic_case_sha256: str = Field(pattern=SHA256_PATTERN)
    status: Literal["ADJUDICATED", "PENDING_ADJUDICATION"]
    disposition: Literal["BLOCK_REQUIRED", "RELEASE_ALLOWED"] | None = None
    method: Literal["FROZEN_PROGRAMMATIC_GOVERNANCE_INJECTION"] | None = None
    pending_reason: str | None = Field(default=None, min_length=8, max_length=500)
    source_product_label: str = Field(min_length=1, max_length=160)
    source_product_label_governance_authority: Literal["none"] = "none"


class ProgrammaticGovernanceTruthReceipt(ProductModel):
    schema_version: Literal[
        "visiondata-gate.programmatic-governance-truth-receipt.v1"
    ] = "visiondata-gate.programmatic-governance-truth-receipt.v1"
    manifest_sha256: str = Field(pattern=SHA256_PATTERN)
    protocol_sha256: str = Field(pattern=SHA256_PATTERN)
    unit_count: int = Field(ge=1)
    release_allowed_count: int = Field(ge=0)
    block_required_count: int = Field(ge=0)
    pending_adjudication_count: int = Field(ge=0)
    units: list[ProgrammaticGovernanceTruthUnit] = Field(min_length=1)
    actual_factory_truth: Literal[False] = False
    public_proxy_only: Literal[True] = True
    production_release_allowed: Literal[False] = False
    receipt_sha256: str = Field(pattern=SHA256_PATTERN)

    @model_validator(mode="after")
    def validate_truth_counts(self) -> ProgrammaticGovernanceTruthReceipt:
        if self.unit_count != len(self.units):
            raise ValueError("detached truth receipt unit count does not reconcile")
        unit_ids = [item.unit_id for item in self.units]
        if len(unit_ids) != len(set(unit_ids)):
            raise ValueError("detached truth receipt contains duplicate unit IDs")
        counts = {
            "release": sum(
                item.disposition == "RELEASE_ALLOWED" for item in self.units
            ),
            "block": sum(item.disposition == "BLOCK_REQUIRED" for item in self.units),
            "pending": sum(
                item.status == "PENDING_ADJUDICATION" for item in self.units
            ),
        }
        if (
            self.release_allowed_count != counts["release"]
            or self.block_required_count != counts["block"]
            or self.pending_adjudication_count != counts["pending"]
            or sum(counts.values()) != self.unit_count
        ):
            raise ValueError("detached truth receipt counts are inconsistent")
        return self


def build_public_source_binding(
    *,
    dataset_version: str,
    source_homepage_url: str,
    source_archive_sha256: str,
    license_text_sha256: str,
    attribution_text_sha256: str,
    bound_at: datetime,
) -> PublicSourceBinding:
    stable = {
        "schema_version": "visiondata-gate.public-source-binding.v1",
        "dataset_id": "VisA",
        "dataset_version": dataset_version,
        "source_homepage_url": source_homepage_url,
        "source_archive_sha256": source_archive_sha256,
        "license_id": "CC-BY-4.0",
        "license_text_sha256": license_text_sha256,
        "attribution_text_sha256": attribution_text_sha256,
        "rights_review_status": "OPERATOR_ATTESTED_NOT_LEGAL_OPINION",
        "local_authorized_read_only": True,
        "raw_redistribution_performed": False,
        "product_label_role": "PRODUCT_CONDITION_ONLY_NOT_GOVERNANCE_TRUTH",
        "bound_at": _aware(bound_at),
    }
    binding = _sealed_model(
        PublicSourceBinding,
        "binding_sha256",
        stable,
        domain="public-source-binding",
    )
    verify_public_source_binding(binding)  # type: ignore[arg-type]
    return binding  # type: ignore[return-value]


def verify_public_source_binding(binding: PublicSourceBinding) -> None:
    _verify_seal(
        binding,
        "binding_sha256",
        domain="public-source-binding",
        message="public source binding failed SHA-256 validation",
    )


def build_visa_source_index(
    dataset_root: str | Path,
    *,
    source_binding: PublicSourceBinding,
    split_csv_relative_path: str,
    expected_csv_header_sha256: str,
    column_mapping: VisaColumnMapping,
) -> VisaSourceIndex:
    verify_public_source_binding(source_binding)
    root = Path(dataset_root).expanduser().resolve(strict=True)
    if not root.is_dir():
        raise ValueError("VisA dataset root must be a directory")
    csv_relative = _safe_relative_path(
        split_csv_relative_path,
        field_name="VisA split CSV path",
    )
    csv_path = _resolve_source_member(root, csv_relative)
    raw = csv_path.read_bytes()
    try:
        text = raw.decode("utf-8-sig")
    except UnicodeDecodeError as error:
        raise SourceSchemaDeferredError("VisA split CSV is not UTF-8") from error
    reader = csv.DictReader(io.StringIO(text, newline=""))
    header = list(reader.fieldnames or [])
    header_sha256 = visa_csv_header_sha256(header)
    if not hmac.compare_digest(header_sha256, expected_csv_header_sha256):
        raise SourceSchemaDeferredError(
            "VisA CSV header differs from the explicitly approved header digest"
        )
    mapped_columns = set(column_mapping.model_dump().values())
    if not mapped_columns.issubset(set(header)):
        raise SourceSchemaDeferredError(
            "VisA CSV semantic mapping refers to absent columns; positional guessing is forbidden"
        )
    samples: list[VisaSourceSample] = []
    for row_number, row in enumerate(reader, start=2):
        object_class = (row.get(column_mapping.object_column) or "").strip()
        split = (row.get(column_mapping.split_column) or "").strip()
        product_label = (row.get(column_mapping.product_label_column) or "").strip()
        image_relative = _safe_relative_path(
            (row.get(column_mapping.image_path_column) or "").strip(),
            field_name=f"VisA image path at row {row_number}",
        )
        raw_mask = (row.get(column_mapping.mask_path_column) or "").strip()
        mask_relative = (
            _safe_relative_path(
                raw_mask,
                field_name=f"VisA mask path at row {row_number}",
            )
            if raw_mask
            else None
        )
        if not object_class or not split or not product_label:
            raise SourceSchemaDeferredError(
                f"VisA required semantic value is blank at row {row_number}"
            )
        image_path = _resolve_source_member(root, image_relative)
        mask_path = (
            _resolve_source_member(root, mask_relative)
            if mask_relative is not None
            else None
        )
        sample_identity = _domain_sha256(
            "visa-source-sample-id",
            {
                "row_number": row_number,
                "object_class": object_class,
                "split": split,
                "product_label": product_label,
                "image_relative_path": image_relative,
                "mask_relative_path": mask_relative,
            },
        )
        stable = {
            "source_sample_id": f"visa_{sample_identity[:24]}",
            "row_number": row_number,
            "object_class": object_class,
            "split": split,
            "product_label": product_label,
            "image_relative_path": image_relative,
            "image_sha256": sha256_file(image_path),
            "image_size_bytes": image_path.stat().st_size,
            "mask_relative_path": mask_relative,
            "mask_sha256": sha256_file(mask_path) if mask_path is not None else None,
            "mask_size_bytes": mask_path.stat().st_size
            if mask_path is not None
            else None,
            "product_label_governance_authority": "none",
        }
        sample = _sealed_model(
            VisaSourceSample,
            "sample_sha256",
            stable,
            domain="visa-source-sample",
        )
        samples.append(sample)  # type: ignore[arg-type]
    if not samples:
        raise SourceSchemaDeferredError("VisA split CSV contains no source samples")
    stable_index = {
        "schema_version": "visiondata-gate.visa-source-index.v1",
        "source_binding_sha256": source_binding.binding_sha256,
        "split_csv_relative_path": csv_relative,
        "split_csv_sha256": hashlib.sha256(raw).hexdigest(),
        "csv_header": header,
        "csv_header_sha256": header_sha256,
        "column_mapping": column_mapping,
        "sample_count": len(samples),
        "samples": samples,
        "source_assets_copied": False,
        "product_labels_used_as_governance_truth": False,
    }
    index = _sealed_model(
        VisaSourceIndex,
        "index_sha256",
        stable_index,
        domain="visa-source-index",
    )
    verify_visa_source_index(index, source_binding=source_binding)  # type: ignore[arg-type]
    return index  # type: ignore[return-value]


def verify_visa_source_index(
    index: VisaSourceIndex,
    *,
    source_binding: PublicSourceBinding,
) -> None:
    verify_public_source_binding(source_binding)
    if not hmac.compare_digest(
        index.source_binding_sha256,
        source_binding.binding_sha256,
    ):
        raise ValueError("VisA source index differs from its source binding")
    for sample in index.samples:
        _verify_seal(
            sample,
            "sample_sha256",
            domain="visa-source-sample",
            message="VisA source sample failed SHA-256 validation",
        )
    _verify_seal(
        index,
        "index_sha256",
        domain="visa-source-index",
        message="VisA source index failed SHA-256 validation",
    )


def verify_visa_source_assets(
    index: VisaSourceIndex,
    *,
    dataset_root: str | Path,
) -> None:
    """Fail closed if any indexed CSV, image, mask, size, or digest drifted."""

    root = Path(dataset_root).expanduser().resolve(strict=True)
    if not root.is_dir():
        raise ValueError("VisA dataset root must be a directory")
    csv_path = _resolve_source_member(root, index.split_csv_relative_path)
    if not hmac.compare_digest(sha256_file(csv_path), index.split_csv_sha256):
        raise ValueError("VisA split CSV drifted after source indexing")
    for sample in index.samples:
        image_path = _resolve_source_member(root, sample.image_relative_path)
        if (
            image_path.stat().st_size != sample.image_size_bytes
            or not hmac.compare_digest(sha256_file(image_path), sample.image_sha256)
        ):
            raise ValueError("VisA image asset drifted after source indexing")
        if sample.mask_relative_path is None:
            continue
        mask_path = _resolve_source_member(root, sample.mask_relative_path)
        if (
            mask_path.stat().st_size != sample.mask_size_bytes
            or sample.mask_sha256 is None
            or not hmac.compare_digest(sha256_file(mask_path), sample.mask_sha256)
        ):
            raise ValueError("VisA mask asset drifted after source indexing")


def build_programmatic_governance_manifest(
    source_index: VisaSourceIndex,
    *,
    source_binding: PublicSourceBinding,
    dataset_root: str | Path,
    deterministic_seed: int,
    created_at: datetime,
    cases: Sequence[CreateProgrammaticGovernanceCase],
) -> ProgrammaticGovernanceInjectionManifest:
    verify_visa_source_index(source_index, source_binding=source_binding)
    verify_visa_source_assets(source_index, dataset_root=dataset_root)
    sample_by_id = {item.source_sample_id: item for item in source_index.samples}
    built_cases: list[ProgrammaticGovernanceCase] = []
    for request in cases:
        sample = sample_by_id.get(request.source_sample_id)
        if sample is None:
            raise ValueError("programmatic case refers to an unknown VisA sample")
        if request.case_type == "CLEAN_CONTROL":
            status = "ADJUDICATED"
            disposition = "RELEASE_ALLOWED"
            method = "FROZEN_PROGRAMMATIC_GOVERNANCE_INJECTION"
            pending_reason = None
        elif request.case_type in AUTO_BLOCK_TYPES:
            status = "ADJUDICATED"
            disposition = "BLOCK_REQUIRED"
            method = "FROZEN_PROGRAMMATIC_GOVERNANCE_INJECTION"
            pending_reason = None
        elif request.case_type in PENDING_ADJUDICATION_TYPES:
            status = "PENDING_ADJUDICATION"
            disposition = None
            method = None
            pending_reason = (
                "This boundary condition requires protocol-specific human adjudication."
            )
        else:  # pragma: no cover
            raise ValueError("unsupported programmatic governance case type")
        stable_case = {
            "unit_id": request.unit_id,
            "source_sample_id": sample.source_sample_id,
            "source_sample_sha256": sample.sample_sha256,
            "source_product_label": sample.product_label,
            "case_type": request.case_type,
            "parameters_sha256": request.parameters_sha256,
            "derived_artifact_relative_paths": (
                request.derived_artifact_relative_paths
            ),
            "truth_status": status,
            "truth_disposition": disposition,
            "truth_method": method,
            "pending_reason": pending_reason,
            "product_label_used_as_governance_truth": False,
            "source_dataset_mutated": False,
            "production_release_allowed": False,
        }
        built = _sealed_model(
            ProgrammaticGovernanceCase,
            "case_sha256",
            stable_case,
            domain="programmatic-governance-case",
        )
        built_cases.append(built)  # type: ignore[arg-type]
    if not built_cases:
        raise ValueError("programmatic governance manifest requires at least one case")
    stable_manifest = {
        "schema_version": (
            "visiondata-gate.programmatic-governance-injection-manifest.v1"
        ),
        "evaluation_scope": (
            "PUBLIC_INDUSTRIAL_PROXY_WITH_PROGRAMMATIC_GOVERNANCE_TRUTH"
        ),
        "source_binding_sha256": source_binding.binding_sha256,
        "source_index_sha256": source_index.index_sha256,
        "protocol_id": "PUBLIC_GOVERNANCE_BENCH_V1",
        "protocol_sha256": _domain_sha256(
            "programmatic-protocol", _PROGRAMMATIC_PROTOCOL
        ),
        "deterministic_seed": deterministic_seed,
        "created_at": _aware(created_at),
        "case_count": len(built_cases),
        "cases": built_cases,
        "source_dataset_mutated": False,
        "raw_images_transmitted": False,
        "product_labels_used_as_governance_truth": False,
    }
    manifest = _sealed_model(
        ProgrammaticGovernanceInjectionManifest,
        "manifest_sha256",
        stable_manifest,
        domain="programmatic-governance-manifest",
    )
    verify_programmatic_governance_manifest(
        manifest,  # type: ignore[arg-type]
        source_index=source_index,
        source_binding=source_binding,
    )
    return manifest  # type: ignore[return-value]


def verify_programmatic_governance_manifest(
    manifest: ProgrammaticGovernanceInjectionManifest,
    *,
    source_index: VisaSourceIndex,
    source_binding: PublicSourceBinding,
) -> None:
    verify_visa_source_index(source_index, source_binding=source_binding)
    if manifest.source_binding_sha256 != source_binding.binding_sha256:
        raise ValueError("programmatic manifest differs from its source binding")
    if manifest.source_index_sha256 != source_index.index_sha256:
        raise ValueError("programmatic manifest differs from its source index")
    samples = {item.source_sample_id: item for item in source_index.samples}
    for case in manifest.cases:
        sample = samples.get(case.source_sample_id)
        if sample is None or sample.sample_sha256 != case.source_sample_sha256:
            raise ValueError("programmatic case lost its source sample binding")
        _verify_seal(
            case,
            "case_sha256",
            domain="programmatic-governance-case",
            message="programmatic governance case failed SHA-256 validation",
        )
    _verify_seal(
        manifest,
        "manifest_sha256",
        domain="programmatic-governance-manifest",
        message="programmatic governance manifest failed SHA-256 validation",
    )


def build_programmatic_truth_receipt(
    manifest: ProgrammaticGovernanceInjectionManifest,
) -> ProgrammaticGovernanceTruthReceipt:
    units = [
        ProgrammaticGovernanceTruthUnit(
            unit_id=case.unit_id,
            source_sample_id=case.source_sample_id,
            programmatic_case_sha256=case.case_sha256,
            status=case.truth_status,
            disposition=case.truth_disposition,
            method=case.truth_method,
            pending_reason=case.pending_reason,
            source_product_label=case.source_product_label,
            source_product_label_governance_authority="none",
        )
        for case in manifest.cases
    ]
    stable = {
        "schema_version": ("visiondata-gate.programmatic-governance-truth-receipt.v1"),
        "manifest_sha256": manifest.manifest_sha256,
        "protocol_sha256": manifest.protocol_sha256,
        "unit_count": len(units),
        "release_allowed_count": sum(
            item.disposition == "RELEASE_ALLOWED" for item in units
        ),
        "block_required_count": sum(
            item.disposition == "BLOCK_REQUIRED" for item in units
        ),
        "pending_adjudication_count": sum(
            item.status == "PENDING_ADJUDICATION" for item in units
        ),
        "units": units,
        "actual_factory_truth": False,
        "public_proxy_only": True,
        "production_release_allowed": False,
    }
    receipt = _sealed_model(
        ProgrammaticGovernanceTruthReceipt,
        "receipt_sha256",
        stable,
        domain="programmatic-governance-truth-receipt",
    )
    verify_programmatic_truth_receipt(receipt, manifest=manifest)  # type: ignore[arg-type]
    return receipt  # type: ignore[return-value]


def verify_programmatic_truth_receipt(
    receipt: ProgrammaticGovernanceTruthReceipt,
    *,
    manifest: ProgrammaticGovernanceInjectionManifest,
) -> None:
    if receipt.manifest_sha256 != manifest.manifest_sha256:
        raise ValueError("detached truth receipt differs from its manifest")
    if receipt.protocol_sha256 != manifest.protocol_sha256:
        raise ValueError("detached truth receipt differs from its protocol")
    cases = {item.unit_id: item for item in manifest.cases}
    if {item.unit_id for item in receipt.units} != set(cases):
        raise ValueError("detached truth receipt does not cover the full manifest")
    for unit in receipt.units:
        case = cases.get(unit.unit_id)
        if case is None or unit.programmatic_case_sha256 != case.case_sha256:
            raise ValueError("detached truth unit lost its programmatic case binding")
        if (
            unit.status != case.truth_status
            or unit.disposition != case.truth_disposition
            or unit.method != case.truth_method
            or unit.pending_reason != case.pending_reason
        ):
            raise ValueError("detached truth unit differs from the frozen case truth")
    _verify_seal(
        receipt,
        "receipt_sha256",
        domain="programmatic-governance-truth-receipt",
        message="programmatic governance truth receipt failed SHA-256 validation",
    )


def governance_truth_binding_from_public_receipt(
    receipt: ProgrammaticGovernanceTruthReceipt,
    *,
    unit_id: str,
) -> GovernanceTruthBindingV2:
    by_id = {item.unit_id: item for item in receipt.units}
    unit = by_id.get(unit_id)
    if unit is None:
        raise ValueError("public truth receipt does not contain the requested unit")
    if unit.status == "PENDING_ADJUDICATION":
        return GovernanceTruthBindingV2(
            status="PENDING_ADJUDICATION",
            pending_reason=unit.pending_reason,
        )
    return GovernanceTruthBindingV2(
        status="ADJUDICATED",
        disposition=unit.disposition,
        method="FROZEN_PROGRAMMATIC_GOVERNANCE_INJECTION",
        adjudication_receipt_sha256=receipt.receipt_sha256,
    )


def canonical_public_bench_json_bytes(value: ProductModel) -> bytes:
    return canonical_jcs_bytes(value.model_dump(mode="json"))


__all__ = [
    "AUTO_BLOCK_TYPES",
    "OFFICIAL_VISA_1CLS_HEADER",
    "PENDING_ADJUDICATION_TYPES",
    "CreateProgrammaticGovernanceCase",
    "ProgrammaticGovernanceInjectionManifest",
    "ProgrammaticGovernanceTruthReceipt",
    "PublicSourceBinding",
    "SourceSchemaDeferredError",
    "VisaColumnMapping",
    "VisaSourceIndex",
    "build_programmatic_governance_manifest",
    "build_programmatic_truth_receipt",
    "build_public_source_binding",
    "build_visa_source_index",
    "canonical_public_bench_json_bytes",
    "governance_truth_binding_from_public_receipt",
    "official_visa_1cls_column_mapping",
    "verify_programmatic_governance_manifest",
    "verify_programmatic_truth_receipt",
    "verify_public_source_binding",
    "verify_visa_source_assets",
    "verify_visa_source_index",
    "visa_csv_header_sha256",
]
