"""Freeze reviewed detection boxes into bounded, split-isolated YOLO datasets.

This module never infers boxes from masks or downloads data. The caller grants
the source root and retains the manifest/receipt digest outside the dataset.
Hashes establish content identity; reviewer assertions are not authentication.
Training must use a working copy because the frozen tree admits no extra files.
"""

from __future__ import annotations

import hashlib
from io import BytesIO
import json
import os
from pathlib import Path
import re
import stat
import struct
from typing import Annotated, Any, Literal

from PIL import Image, UnidentifiedImageError
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator
import rfc8785


SCHEMA_VERSION = "visiondata-gate.detection-dataset.v1"
RECEIPT_SCHEMA_VERSION = "visiondata-gate.detection-dataset-receipt.v1"
MAX_SAMPLES = 64
MAX_DIMENSION = 2048
MAX_TOTAL_PIXELS = 16_000_000
MAX_FILE_BYTES = 16 * 1024 * 1024
MAX_TOTAL_FILE_BYTES = 128 * 1024 * 1024
MAX_MANIFEST_BYTES = 2 * 1024 * 1024
SPLITS = ("train", "val", "test")
_HASH = re.compile(r"^[a-f0-9]{64}$")
_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_-]{0,95}$")
_RESERVED = re.compile(r"^(CON|PRN|AUX|NUL|COM[0-9]|LPT[0-9])$", re.I)
_FORMATS = {".png": "PNG", ".jpg": "JPEG", ".jpeg": "JPEG", ".bmp": "BMP"}


class DetectionDatasetError(ValueError):
    """An explicit detection dataset contract or retained digest was violated."""


def _text(value: str) -> str:
    if (
        not value.strip()
        or value != value.strip()
        or any(ord(c) < 32 or ord(c) == 127 for c in value)
        or value.startswith(("/", "\\"))
        or re.match(r"^[A-Za-z]:", value)
    ):
        raise DetectionDatasetError("METADATA_TEXT")
    return value


def _portable(value: str) -> str:
    if not value or any(c in value for c in '\\:<>"|?*'):
        raise DetectionDatasetError("RELATIVE_PATH")
    for part in value.split("/"):
        if (
            part in {"", ".", ".."}
            or part.endswith((".", " "))
            or _RESERVED.fullmatch(part.split(".")[0])
            or any(ord(c) < 32 or ord(c) == 127 for c in part)
        ):
            raise DetectionDatasetError("RELATIVE_PATH")
    return value


class _StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)


class DetectionBox(_StrictModel):
    """Explicit normalized center-width-height box; no mask conversion."""

    class_id: Annotated[int, Field(ge=0, le=63)]
    x_center: Annotated[float, Field(ge=0, le=1, allow_inf_nan=False)]
    y_center: Annotated[float, Field(ge=0, le=1, allow_inf_nan=False)]
    width: Annotated[float, Field(gt=0, le=1, allow_inf_nan=False)]
    height: Annotated[float, Field(gt=0, le=1, allow_inf_nan=False)]

    @model_validator(mode="after")
    def within_image(self) -> DetectionBox:
        if not (
            0 <= self.x_center - self.width / 2
            and self.x_center + self.width / 2 <= 1
            and 0 <= self.y_center - self.height / 2
            and self.y_center + self.height / 2 <= 1
        ):
            raise DetectionDatasetError("BOX_OUTSIDE_IMAGE")
        return self


class DetectionSample(_StrictModel):
    sample_id: Annotated[str, Field(min_length=1, max_length=96)]
    image_path: Annotated[str, Field(min_length=1, max_length=512)]
    image_sha256: Annotated[str, Field(pattern=r"^[a-f0-9]{64}$")]
    split: Literal["train", "val", "test"]
    group_id: Annotated[str, Field(min_length=1, max_length=160)]
    annotation_revision: Annotated[int, Field(ge=0, le=2**31 - 1)]
    boxes: Annotated[list[DetectionBox], Field(max_length=256)]
    reviewer_name: Annotated[str, Field(min_length=1, max_length=160)]
    reviewed: bool
    normal_attested: bool = False

    @field_validator("sample_id")
    @classmethod
    def safe_id(cls, value: str) -> str:
        if not _ID.fullmatch(value) or _RESERVED.fullmatch(value):
            raise DetectionDatasetError("SAMPLE_ID")
        return value

    @field_validator("image_path")
    @classmethod
    def portable_image(cls, value: str) -> str:
        _portable(value)
        if Path(value).suffix.lower() not in _FORMATS:
            raise DetectionDatasetError("IMAGE_EXTENSION")
        return value

    @field_validator("group_id", "reviewer_name")
    @classmethod
    def valid_text(cls, value: str) -> str:
        return _text(value)

    @model_validator(mode="after")
    def explicit_review(self) -> DetectionSample:
        if self.reviewed is not True:
            raise DetectionDatasetError("REVIEW_REQUIRED")
        if self.normal_attested != (not self.boxes):
            raise DetectionDatasetError("NORMAL_ATTESTATION")
        return self


class DetectionDatasetManifest(_StrictModel):
    schema_version: Literal["visiondata-gate.detection-dataset.v1"]
    class_names: Annotated[list[str], Field(min_length=1, max_length=64)]
    source_version: Annotated[str, Field(min_length=1, max_length=160)]
    samples: Annotated[list[DetectionSample], Field(min_length=3, max_length=64)]

    @field_validator("source_version")
    @classmethod
    def valid_version(cls, value: str) -> str:
        return _text(value)

    @field_validator("class_names")
    @classmethod
    def valid_classes(cls, value: list[str]) -> list[str]:
        for name in value:
            _text(name)
            if len(name) > 96:
                raise DetectionDatasetError("CLASS_NAME_LENGTH")
        if len(set(value)) != len(value):
            raise DetectionDatasetError("CLASS_NAMES_DUPLICATE")
        return value

    @model_validator(mode="after")
    def complete_splits(self) -> DetectionDatasetManifest:
        if {s.split for s in self.samples} != set(SPLITS):
            raise DetectionDatasetError("TRAIN_VAL_TEST_REQUIRED")
        ids: set[str] = set()
        paths: set[str] = set()
        groups: dict[str, str] = {}
        for sample in self.samples:
            # A Windows-created dataset must remain portable to case-insensitive
            # filesystems; distinct case spellings must not alias output members.
            if sample.sample_id.casefold() in ids:
                raise DetectionDatasetError("SAMPLE_ID_DUPLICATE")
            ids.add(sample.sample_id.casefold())
            if sample.image_path.casefold() in paths:
                raise DetectionDatasetError("IMAGE_PATH_DUPLICATE")
            paths.add(sample.image_path.casefold())
            if groups.setdefault(sample.group_id, sample.split) != sample.split:
                raise DetectionDatasetError("GROUP_SPLIT_LEAKAGE")
            if any(box.class_id >= len(self.class_names) for box in sample.boxes):
                raise DetectionDatasetError("UNKNOWN_CLASS_ID")
        return self


def _sha(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _jcs(value: Any) -> bytes:
    try:
        return rfc8785.dumps(value)
    except (rfc8785.CanonicalizationError, TypeError, UnicodeError) as error:
        raise DetectionDatasetError("INVALID_CANONICAL_JSON") from error


def _raw(manifest: DetectionDatasetManifest | dict) -> dict:
    if isinstance(manifest, DetectionDatasetManifest):
        return manifest.model_dump(mode="json")
    if not isinstance(manifest, dict):
        raise DetectionDatasetError("MANIFEST_OBJECT")
    return manifest


def manifest_sha256(manifest: DetectionDatasetManifest | dict) -> str:
    """Hash the complete supplied JSON object before defaults are inserted."""
    payload = _jcs(_raw(manifest))
    if len(payload) > MAX_MANIFEST_BYTES:
        raise DetectionDatasetError("MANIFEST_BYTE_CAP")
    return _sha(payload)


def _no_links(path: Path) -> None:
    for part in (path, *path.parents):
        try:
            metadata = part.lstat()
        except FileNotFoundError:
            continue
        if stat.S_ISLNK(metadata.st_mode) or getattr(
            metadata, "st_file_attributes", 0
        ) & getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0x400):
            raise DetectionDatasetError("PATH_LINK_OR_REPARSE")


def _directory(path: Path) -> Path:
    absolute = Path(os.path.abspath(path))
    _no_links(absolute)
    if not absolute.is_dir():
        raise DetectionDatasetError("ROOT_DIRECTORY_REQUIRED")
    return absolute.resolve(strict=True)


def _read(root: Path, relative: str, cap: int = MAX_FILE_BYTES) -> bytes:
    path = root / _portable(relative)
    _no_links(path)
    try:
        resolved = path.resolve(strict=True)
        if not resolved.is_relative_to(root):
            raise DetectionDatasetError("PATH_OUTSIDE_ROOT")
        before = path.stat()
        if not stat.S_ISREG(before.st_mode):
            raise DetectionDatasetError("REGULAR_FILE_REQUIRED")
        if before.st_size > cap:
            raise DetectionDatasetError("FILE_BYTE_CAP")
        with path.open("rb") as stream:
            opened = os.fstat(stream.fileno())
            content = stream.read(cap + 1)
            finished = os.fstat(stream.fileno())
        _no_links(path)
        after = path.stat()
    except OSError as error:
        raise DetectionDatasetError("DATASET_FILE_UNAVAILABLE") from error

    def identity(item):
        return item.st_dev, item.st_ino, item.st_size, item.st_mtime_ns

    if any(identity(value) != identity(before) for value in (opened, finished, after)):
        raise DetectionDatasetError("FILE_CHANGED_DURING_READ")
    if len(content) > cap:
        raise DetectionDatasetError("FILE_BYTE_CAP")
    return content


def _decode(content: bytes, extension: str) -> tuple[int, int, str]:
    try:
        with Image.open(BytesIO(content)) as image:
            width, height = image.size
            if not (1 <= width <= MAX_DIMENSION and 1 <= height <= MAX_DIMENSION):
                raise DetectionDatasetError("IMAGE_DIMENSIONS")
            if image.format != _FORMATS[extension]:
                raise DetectionDatasetError("IMAGE_FORMAT_EXTENSION_MISMATCH")
            if getattr(image, "n_frames", 1) != 1:
                raise DetectionDatasetError("MULTIFRAME_NOT_SUPPORTED")
            if image.getexif().get(274, 1) != 1:
                raise DetectionDatasetError("ORIENTED_IMAGE_REQUIRES_EXPLICIT_REVIEW")
            if image.mode not in {"L", "RGB"}:
                raise DetectionDatasetError("IMAGE_MODE_REQUIRES_RGB_OR_L")
            pixels = image.convert("RGB").tobytes()
    except (
        UnidentifiedImageError,
        OSError,
        SyntaxError,
        Image.DecompressionBombError,
    ) as error:
        raise DetectionDatasetError("IMAGE_DECODE") from error
    return (
        width,
        height,
        _sha(
            b"visiondata-gate.detection-pixels.v1\x00"
            + struct.pack(">II", width, height)
            + pixels
        ),
    )


def _labels(sample: DetectionSample) -> bytes:
    return "".join(
        f"{box.class_id} "
        + " ".join(
            _jcs(value).decode("ascii")
            for value in (box.x_center, box.y_center, box.width, box.height)
        )
        + "\n"
        for box in sample.boxes
    ).encode("ascii")


def _yaml(class_names: list[str]) -> bytes:
    # JSON strings/lists form a YAML-compatible subset. Fixed keys prevent
    # executable download hooks, absolute roots, or untrusted YAML tags.
    return (
        "train: images/train\nval: images/val\ntest: images/test\nnames: "
        + json.dumps(class_names, ensure_ascii=True)
        + "\n"
    ).encode("ascii")


def _collect(
    root: Path, manifest: DetectionDatasetManifest, *, frozen: bool
) -> tuple[list[dict], dict[str, bytes]]:
    rows = []
    members: dict[str, bytes] = {}
    seen_images: dict[str, str] = {}
    seen_pixels: dict[str, str] = {}
    total_pixels = 0
    total_bytes = 0
    for sample in manifest.samples:
        extension = Path(sample.image_path).suffix.lower()
        image_path = f"images/{sample.split}/{sample.sample_id}{extension}"
        label_path = f"labels/{sample.split}/{sample.sample_id}.txt"
        content = _read(root, image_path if frozen else sample.image_path)
        if _sha(content) != sample.image_sha256:
            raise DetectionDatasetError("IMAGE_SHA_MISMATCH")
        width, height, pixel_sha = _decode(content, extension)
        total_pixels += width * height
        total_bytes += len(content)
        if total_pixels > MAX_TOTAL_PIXELS:
            raise DetectionDatasetError("TOTAL_PIXEL_CAP")
        if total_bytes > MAX_TOTAL_FILE_BYTES:
            raise DetectionDatasetError("TOTAL_FILE_BYTE_CAP")
        if seen_images.setdefault(sample.image_sha256, sample.split) != sample.split:
            raise DetectionDatasetError("IMAGE_SPLIT_LEAKAGE")
        if seen_pixels.setdefault(pixel_sha, sample.split) != sample.split:
            raise DetectionDatasetError("PIXEL_SPLIT_LEAKAGE")
        labels = _labels(sample)
        if frozen and _read(root, label_path, MAX_MANIFEST_BYTES) != labels:
            raise DetectionDatasetError("LABEL_CONTENT_MISMATCH")
        members[image_path] = content
        members[label_path] = labels
        rows.append(
            {
                **sample.model_dump(mode="json"),
                "image_path": image_path,
                "label_path": label_path,
                "pixel_sha256": pixel_sha,
                "label_sha256": _sha(labels),
                "width": width,
                "height": height,
            }
        )
    return rows, members


def _receipt(manifest: DetectionDatasetManifest, digest: str, rows: list[dict]) -> dict:
    body = {
        "schema_version": RECEIPT_SCHEMA_VERSION,
        "source_version": manifest.source_version,
        "class_names": manifest.class_names,
        "manifest_sha256": digest,
        "samples": rows,
        "split_counts": {
            split: sum(row["split"] == split for row in rows) for split in SPLITS
        },
        "data_yaml_sha256": _sha(_yaml(manifest.class_names)),
    }
    receipt_sha = _sha(_jcs(body))
    return {
        **body,
        "dataset_id": "detds_" + receipt_sha[:24],
        "receipt_sha256": receipt_sha,
    }


def _inventory(root: Path) -> set[str]:
    files: set[str] = set()
    for directory, directories, filenames in os.walk(root, followlinks=False):
        for name in directories + filenames:
            path = Path(directory) / name
            _no_links(path)
            relative = path.relative_to(root).as_posix()
            _portable(relative)
            if name in filenames:
                if not path.is_file():
                    raise DetectionDatasetError("REGULAR_FILE_REQUIRED")
                files.add(relative)
            else:
                files.add(relative + "/")
    return files


def freeze_detection_dataset(
    source_root: Path,
    manifest: DetectionDatasetManifest | dict,
    output_root: Path,
    expected_manifest_sha256: str,
) -> dict:
    """Create a new frozen tree after complete validation, without source writes.

    The source-root grant and the named reviewer are supplied by the caller's
    authorization layer. Invalid inputs create no output. An interrupted write
    may leave a partial new tree; it never validates and must not be reused.
    """
    raw_bytes = _jcs(_raw(manifest))
    digest = manifest_sha256(manifest)
    if (
        not isinstance(expected_manifest_sha256, str)
        or digest != expected_manifest_sha256
    ):
        raise DetectionDatasetError("MANIFEST_SHA_MISMATCH")
    checked = DetectionDatasetManifest.model_validate(json.loads(raw_bytes))
    root = _directory(source_root)
    output = Path(os.path.abspath(output_root))
    _no_links(output)
    if output.exists():
        raise DetectionDatasetError("OUTPUT_EXISTS")
    if output.is_relative_to(root):
        raise DetectionDatasetError("OUTPUT_INSIDE_SOURCE")
    _directory(output.parent)
    rows, members = _collect(root, checked, frozen=False)
    receipt = _receipt(checked, digest, rows)
    members.update(
        {
            "manifest.json": raw_bytes,
            "data.yaml": _yaml(checked.class_names),
            "dataset.json": _jcs(receipt),
        }
    )
    try:
        output.mkdir(exist_ok=False)
        for relative, content in members.items():
            path = output / relative
            _no_links(path)
            path.parent.mkdir(parents=True, exist_ok=True)
            _no_links(path)
            with path.open("xb") as stream:
                stream.write(content)
    except OSError as error:
        raise DetectionDatasetError("OUTPUT_WRITE_FAILED") from error
    return verify_detection_dataset(output, receipt["receipt_sha256"])


def _json(content: bytes) -> dict:
    try:
        parsed = json.loads(content)
        if not isinstance(parsed, dict) or _jcs(parsed) != content:
            raise DetectionDatasetError("NONCANONICAL_DATASET_JSON")
        return parsed
    except (ValueError, UnicodeError) as error:
        raise DetectionDatasetError("DATASET_JSON_INVALID") from error


def verify_detection_dataset(dataset_root: Path, expected_receipt_sha256: str) -> dict:
    """Re-read exactly the frozen members and reconstruct the bound receipt.

    Always pass an independently retained digest. Recomputing it from a local
    replacement receipt would not protect against replacement of the whole tree.
    """
    if not isinstance(expected_receipt_sha256, str) or not _HASH.fullmatch(
        expected_receipt_sha256
    ):
        raise DetectionDatasetError("RECEIPT_SHA_REQUIRED")
    root = _directory(dataset_root)
    receipt = _json(_read(root, "dataset.json", MAX_MANIFEST_BYTES))
    body = {
        k: v for k, v in receipt.items() if k not in {"dataset_id", "receipt_sha256"}
    }
    if (
        receipt.get("receipt_sha256") != expected_receipt_sha256
        or _sha(_jcs(body)) != expected_receipt_sha256
        or receipt.get("dataset_id") != "detds_" + expected_receipt_sha256[:24]
    ):
        raise DetectionDatasetError("RECEIPT_SHA_MISMATCH")
    raw = _json(_read(root, "manifest.json", MAX_MANIFEST_BYTES))
    digest = manifest_sha256(raw)
    if digest != receipt.get("manifest_sha256"):
        raise DetectionDatasetError("MANIFEST_SHA_MISMATCH")
    checked = DetectionDatasetManifest.model_validate(raw)
    rows, members = _collect(root, checked, frozen=True)
    if _read(root, "data.yaml", MAX_MANIFEST_BYTES) != _yaml(checked.class_names):
        raise DetectionDatasetError("YAML_CONTENT_MISMATCH")
    expected_directories = {
        "images/",
        "labels/",
        *(f"{kind}/{split}/" for kind in ("images", "labels") for split in SPLITS),
    }
    if _inventory(root) != set(members) | expected_directories | {
        "manifest.json",
        "dataset.json",
        "data.yaml",
    }:
        raise DetectionDatasetError("UNEXPECTED_DATASET_MEMBERS")
    if receipt != _receipt(checked, digest, rows):
        raise DetectionDatasetError("RECEIPT_METADATA_MISMATCH")
    return receipt
