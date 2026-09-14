"""Freeze bounded RGB/binary-mask datasets without cross-split leakage.

Only explicitly granted roots and manifest paths are read. Original encoded
image/mask bytes are preserved; loaded masks are normalized to uint8 {0, 1}.
Missing source masks remain forbidden unless an explicit, image-SHA-bound
human no-foreground attestation authorizes a separate zero-mask learning copy.
The receipt hashes its JCS body excluding the two derived fields dataset_id
and receipt_sha256. This detects drift, not malicious replacement of an entire
dataset and receipt; callers must retain the returned receipt digest externally.
"""

from __future__ import annotations

import hashlib
from io import BytesIO
import json
import os
from pathlib import Path
import re
import stat
from typing import TYPE_CHECKING, Any

import numpy as np
from PIL import Image, UnidentifiedImageError

from .audit_envelope import canonical_jcs_bytes
from .contracts import BatchManifest

if TYPE_CHECKING:
    from .learning_engine import PixelSample


SCHEMA_VERSION = "visiondata-gate.learning-dataset.v1"
MAX_SAMPLES = 64
MAX_DIMENSION = 256
MAX_TOTAL_PIXELS = 1_000_000
MAX_FILE_BYTES = 4 * 1024 * 1024
MAX_RECEIPT_BYTES = 512 * 1024
SPLITS = ("train", "val", "test")
RECEIPT_KEYS = {
    "schema_version",
    "dataset_id",
    "binding",
    "samples",
    "split_fingerprints",
    "labels_sha256",
    "receipt_sha256",
}
SAMPLE_KEYS = {
    "sample_id",
    "split",
    "category",
    "group_id",
    "image_path",
    "mask_path",
    "image_sha256",
    "mask_sha256",
    "pixel_sha256",
    "mask_pixel_sha256",
    "width",
    "height",
}
NORMAL_MASK_ORIGIN = "EXPLICIT_HUMAN_ZERO_MASK"
NORMAL_SAMPLE_KEYS = {"mask_origin", "normal_attestation_sha256"}


class DatasetError(ValueError):
    """A dataset path, label, integrity, or split contract was not satisfied."""


def _sha(content: bytes) -> str:
    return hashlib.sha256(content).hexdigest()


def _jcs_sha(value: Any) -> str:
    return _sha(canonical_jcs_bytes(value))


def _no_links(path: Path) -> None:
    for component in (path, *path.parents):
        try:
            metadata = component.lstat()
        except FileNotFoundError:
            continue
        if stat.S_ISLNK(metadata.st_mode) or getattr(
            metadata, "st_file_attributes", 0
        ) & getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0x400):
            raise DatasetError("PATH_LINK_OR_REPARSE")


def _root(path: Path) -> Path:
    path = Path(os.path.abspath(path))
    _no_links(path)
    if not path.is_dir():
        raise DatasetError("ROOT_DIRECTORY_REQUIRED")
    return path.resolve(strict=True)


def _relative(value: str) -> str:
    if (
        not isinstance(value, str)
        or not value
        or any(char in value for char in '\\:<>"|?*')
    ):
        raise DatasetError("RELATIVE_PATH")
    parts = value.split("/")
    if any(part in {"", ".", ".."} or part.endswith((".", " ")) for part in parts):
        raise DatasetError("RELATIVE_PATH")
    if any(ord(char) < 32 for char in value):
        raise DatasetError("RELATIVE_PATH")
    return value


def _input_path(root: Path, relative: str) -> Path:
    path = root / _relative(relative)
    _no_links(path)
    try:
        resolved = path.resolve(strict=True)
    except OSError as error:
        raise DatasetError("INPUT_FILE_MISSING") from error
    if not resolved.is_relative_to(root):
        raise DatasetError("PATH_OUTSIDE_ROOT")
    if not resolved.is_file():
        raise DatasetError("INPUT_REGULAR_FILE_REQUIRED")
    return resolved


def _read_file(root: Path, relative: str, *, cap: int = MAX_FILE_BYTES) -> bytes:
    path = _input_path(root, relative)
    before = path.stat()
    if before.st_size > cap:
        raise DatasetError("FILE_BYTE_CAP")
    with path.open("rb") as stream:
        opened = os.fstat(stream.fileno())
        if not stat.S_ISREG(opened.st_mode) or opened.st_ino != before.st_ino:
            raise DatasetError("INPUT_FILE_CHANGED")
        content = stream.read(cap + 1)
        after_opened = os.fstat(stream.fileno())
    _no_links(path)
    after = path.stat()
    if len(content) > cap:
        raise DatasetError("FILE_BYTE_CAP")

    def identity(value):
        return value.st_ino, value.st_size, value.st_mtime_ns

    if identity(before) != identity(after_opened) or identity(before) != identity(
        after
    ):
        raise DatasetError("INPUT_FILE_CHANGED")
    return content


def _private_absolute(value: str) -> bool:
    return value.startswith(("/", "\\")) or re.match(r"^[A-Za-z]:", value) is not None


def _text(value: Any, code: str) -> str:
    if (
        not isinstance(value, str)
        or not value.strip()
        or len(value) > 512
        or any(ord(char) < 32 for char in value)
    ):
        raise DatasetError(code)
    if _private_absolute(value):
        raise DatasetError("METADATA_PRIVATE_PATH")
    return value


def _binding(binding: dict) -> dict:
    if not isinstance(binding, dict):
        raise DatasetError("BINDING_OBJECT_REQUIRED")

    def validate(value):
        if isinstance(value, dict):
            for key, item in value.items():
                if not isinstance(key, str):
                    raise DatasetError("BINDING_KEYS")
                validate(key)
                validate(item)
        elif isinstance(value, list):
            for item in value:
                validate(item)
        elif isinstance(value, str) and _private_absolute(value):
            raise DatasetError("BINDING_PRIVATE_PATH")

    validate(binding)
    encoded = canonical_jcs_bytes(binding)
    if len(encoded) > 16 * 1024:
        raise DatasetError("BINDING_SIZE_CAP")
    return json.loads(encoded)


def _normal_attestations(value: dict | None) -> dict:
    if value is None or value == {}:
        return {}
    if not isinstance(value, dict) or len(value) > MAX_SAMPLES:
        raise DatasetError("NORMAL_ATTESTATION_SCHEMA")
    # Delayed import keeps legacy no-attestation callers' module dependencies
    # unchanged. Revalidate model instances too: model_copy can bypass validation.
    from .learning_contracts import NormalMaskAttestation

    normalized = {}
    for sample_id, attestation in value.items():
        _text(sample_id, "NORMAL_ATTESTATION_SCHEMA")
        if isinstance(attestation, NormalMaskAttestation):
            attestation = attestation.model_dump(mode="json")
        if (
            not isinstance(attestation, dict)
            or attestation.get("operator_attests_no_foreground") is not True
        ):
            raise DatasetError("NORMAL_ATTESTATION_SCHEMA")
        try:
            checked = NormalMaskAttestation.model_validate(attestation).model_dump(
                mode="json"
            )
        except (ValueError, TypeError) as error:
            raise DatasetError("NORMAL_ATTESTATION_SCHEMA") from error
        # Also preserve the receipt's existing no-absolute-private-path boundary.
        normalized[sample_id] = _binding(checked)
    return normalized


def _zero_mask_png(shape: tuple[int, int]) -> bytes:
    stream = BytesIO()
    Image.fromarray(np.zeros(shape, dtype=np.uint8)).save(stream, format="PNG")
    return stream.getvalue()


def _decode(content: bytes, *, mask: bool = False) -> np.ndarray:
    try:
        with Image.open(BytesIO(content)) as image:
            width, height = image.size
            if not (1 <= width <= MAX_DIMENSION and 1 <= height <= MAX_DIMENSION):
                raise DatasetError("IMAGE_DIMENSIONS")
            if getattr(image, "n_frames", 1) != 1:
                raise DatasetError("MULTIFRAME_NOT_SUPPORTED")
            if not mask:
                return np.array(image.convert("RGB"), dtype=np.uint8, copy=True)
            values = np.array(image, copy=True)
    except (
        OSError,
        UnidentifiedImageError,
        Image.DecompressionBombError,
        ValueError,
    ) as error:
        if isinstance(error, DatasetError):
            raise
        raise DatasetError("IMAGE_DECODE") from error
    if values.ndim != 2 or values.dtype.kind not in "biu":
        raise DatasetError("MASK_BINARY_VALUES")
    labels = set(np.unique(values).tolist())
    if not (labels.issubset({0, 1}) or labels.issubset({0, 255})):
        raise DatasetError("MASK_BINARY_VALUES")
    return np.asarray(values > 0, dtype=np.uint8)


def _pixel_sha(array: np.ndarray, *, mask: bool = False) -> str:
    height, width = array.shape[:2]
    domain = (
        b"visiondata-gate.learning-mask.v1\0"
        if mask
        else b"visiondata-gate.learning-rgb.v1\0"
    )
    return _sha(
        domain
        + height.to_bytes(4, "big")
        + width.to_bytes(4, "big")
        + np.ascontiguousarray(array).tobytes()
    )


def _validate_membership(samples: list[dict]) -> None:
    if not 1 <= len(samples) <= MAX_SAMPLES:
        raise DatasetError("SAMPLE_COUNT_CAP")
    for sample in samples:
        for key in ("sample_id", "category", "group_id"):
            _text(sample[key], "SAMPLE_METADATA")
        if not isinstance(sample["split"], str) or sample["split"] not in SPLITS:
            raise DatasetError("SPLITS_REQUIRED")
    ids = [sample["sample_id"] for sample in samples]
    if len(ids) != len(set(ids)):
        raise DatasetError("SAMPLE_IDS")
    if {sample["split"] for sample in samples} != set(SPLITS):
        raise DatasetError("SPLITS_REQUIRED")
    groups = {}
    pixels = {}
    total = 0
    for sample in samples:
        split = sample["split"]
        group = sample["group_id"]
        if group in groups and groups[group] != split:
            raise DatasetError("GROUP_SPLIT_LEAKAGE")
        groups[group] = split
        pixel = sample.get("pixel_sha256")
        if pixel is not None:
            if pixel in pixels and pixels[pixel] != split:
                raise DatasetError("PIXEL_SPLIT_LEAKAGE")
            pixels[pixel] = split
            total += sample["width"] * sample["height"]
    if total > MAX_TOTAL_PIXELS:
        raise DatasetError("TOTAL_PIXEL_CAP")


def _fingerprints(samples: list[dict]) -> dict[str, str]:
    result = {}
    for split in SPLITS:
        members = [
            {
                key: sample[key]
                for key in ("group_id", "category", "pixel_sha256", "mask_pixel_sha256")
            }
            for sample in samples
            if sample["split"] == split
        ]
        members.sort(key=canonical_jcs_bytes)
        result[split] = _jcs_sha(members)
    return result


def _labels_sha(samples: list[dict]) -> str:
    return _jcs_sha(
        [
            {
                key: sample[key]
                for key in ("sample_id", "mask_sha256", "mask_pixel_sha256")
            }
            for sample in samples
        ]
    )


def freeze_dataset(
    source_root: Path,
    manifest: BatchManifest,
    binding: dict,
    groups: dict[str, str],
    destination: Path,
    *,
    normal_attestations: dict | None = None,
) -> dict:
    """Freeze original masks or explicitly attested zero-mask learning copies.

    The caller must verify annotation revision/document SHA and actual emptiness
    against the authoritative snapshot. This layer validates declaration schema,
    membership, current source image SHA, and the derived zero-mask pixels.
    Failed partial copies remain intact; source images and annotations never change.
    """
    root = _root(source_root)
    destination = Path(os.path.abspath(destination))
    _no_links(destination)
    if destination.exists():
        raise DatasetError("DESTINATION_EXISTS")
    _root(destination.parent)
    if not isinstance(manifest, BatchManifest):
        raise DatasetError("BATCH_MANIFEST_REQUIRED")
    if not 1 <= len(manifest.samples) <= MAX_SAMPLES:
        raise DatasetError("SAMPLE_COUNT_CAP")
    ids = [_text(sample.sample_id, "SAMPLE_IDS") for sample in manifest.samples]
    if len(ids) != len(set(ids)):
        raise DatasetError("SAMPLE_IDS")
    if not isinstance(groups, dict) or set(groups) != set(ids):
        raise DatasetError("GROUP_KEYS")
    safe_binding = _binding(binding)
    attestations = _normal_attestations(normal_attestations)
    if set(attestations) - set(ids):
        raise DatasetError("NORMAL_ATTESTATION_UNKNOWN_SAMPLE")
    for sample in manifest.samples:
        if sample.sample_id in attestations and sample.annotation_path is not None:
            raise DatasetError("NORMAL_ATTESTATION_WITH_SOURCE_MASK")
    records = []
    copy_inputs = []
    for index, sample in enumerate(manifest.samples):
        attestation = attestations.get(sample.sample_id)
        if sample.annotation_path is None and attestation is None:
            raise DatasetError("MASK_REQUIRED")
        image_bytes = _read_file(root, sample.relative_path)
        image = _decode(image_bytes)
        derived_mask = None
        if attestation is not None:
            if attestation["expected_asset_sha256"] != _sha(image_bytes):
                raise DatasetError("NORMAL_ATTESTATION_ASSET_SHA256")
            derived_mask = _zero_mask_png(image.shape[:2])
            mask_bytes = derived_mask
        else:
            mask_bytes = _read_file(root, sample.annotation_path)
        mask = _decode(mask_bytes, mask=True)
        if image.shape[:2] != mask.shape:
            raise DatasetError("MASK_DIMENSIONS")
        height, width = image.shape[:2]
        records.append(
            {
                "sample_id": sample.sample_id,
                "split": sample.split,
                "category": _text(sample.category, "SAMPLE_CATEGORY"),
                "group_id": _text(groups[sample.sample_id], "GROUP_ID"),
                "image_path": f"images/{index:04d}.image",
                "mask_path": f"masks/{index:04d}.mask",
                "image_sha256": _sha(image_bytes),
                "mask_sha256": _sha(mask_bytes),
                "pixel_sha256": _pixel_sha(image),
                "mask_pixel_sha256": _pixel_sha(mask, mask=True),
                "width": width,
                "height": height,
            }
        )
        if attestation is not None:
            records[-1].update(
                mask_origin=NORMAL_MASK_ORIGIN,
                normal_attestation_sha256=_jcs_sha(attestation),
            )
        copy_inputs.append((sample.relative_path, sample.annotation_path, derived_mask))
    _validate_membership(records)
    receipt = {
        "schema_version": SCHEMA_VERSION,
        "binding": safe_binding,
        "samples": records,
        "split_fingerprints": _fingerprints(records),
        "labels_sha256": _labels_sha(records),
    }
    if attestations:
        receipt["normal_mask_attestations"] = attestations
    digest = _jcs_sha(receipt)
    receipt.update(dataset_id="dataset_" + digest[:24], receipt_sha256=digest)

    # All semantic validation above precedes the only directory creation.
    # Failure below never recursively removes or overwrites any caller data.
    destination.mkdir(exist_ok=False)
    (destination / "images").mkdir()
    (destination / "masks").mkdir()
    for record, paths in zip(records, copy_inputs):
        for source_path, path_key, hash_key in (
            (paths[0], "image_path", "image_sha256"),
            (paths[1], "mask_path", "mask_sha256"),
        ):
            content = (
                paths[2]
                if path_key == "mask_path" and paths[2] is not None
                else _read_file(root, source_path)
            )
            if _sha(content) != record[hash_key]:
                raise DatasetError("SOURCE_CHANGED_DURING_FREEZE")
            target = destination / record[path_key]
            _no_links(target)
            with target.open("xb") as stream:
                stream.write(content)
    _no_links(destination / "dataset.json")
    with (destination / "dataset.json").open("xb") as stream:
        stream.write(canonical_jcs_bytes(receipt))
    verified, _ = load_dataset(destination)
    return verified


def _exact_files(root: Path, expected: set[str]) -> None:
    actual = set()
    pending = [root]
    while pending:
        parent = pending.pop()
        for path in parent.iterdir():
            _no_links(path)
            if path.is_dir():
                if path.relative_to(root).as_posix() not in {"images", "masks"}:
                    raise DatasetError("FILE_SET")
                pending.append(path)
            elif path.is_file():
                actual.add(path.relative_to(root).as_posix())
            else:
                raise DatasetError("INPUT_REGULAR_FILE_REQUIRED")
    if actual != expected:
        raise DatasetError("FILE_SET")


def load_dataset(dataset_root: Path) -> tuple[dict, list[PixelSample]]:
    """Revalidate receipt, exact files, decoded labels and split isolation."""
    root = _root(dataset_root)
    raw = _read_file(root, "dataset.json", cap=MAX_RECEIPT_BYTES)

    def unique(pairs):
        result = {}
        for key, value in pairs:
            if key in result:
                raise DatasetError("RECEIPT_DUPLICATE_KEYS")
            result[key] = value
        return result

    try:
        receipt = json.loads(raw, object_pairs_hook=unique)
    except (UnicodeError, json.JSONDecodeError) as error:
        raise DatasetError("RECEIPT_JSON") from error
    if (
        not isinstance(receipt, dict)
        or set(receipt)
        not in (RECEIPT_KEYS, RECEIPT_KEYS | {"normal_mask_attestations"})
        or receipt["schema_version"] != SCHEMA_VERSION
    ):
        raise DatasetError("RECEIPT_SCHEMA")
    core = {
        key: value
        for key, value in receipt.items()
        if key not in {"receipt_sha256", "dataset_id"}
    }
    digest = _jcs_sha(core)
    if (
        receipt["receipt_sha256"] != digest
        or receipt["dataset_id"] != "dataset_" + digest[:24]
    ):
        raise DatasetError("RECEIPT_SHA256")
    if raw != canonical_jcs_bytes(receipt):
        raise DatasetError("RECEIPT_NOT_CANONICAL")
    _binding(receipt["binding"])
    attestations = _normal_attestations(receipt.get("normal_mask_attestations"))
    if "normal_mask_attestations" in receipt and (
        not attestations or attestations != receipt["normal_mask_attestations"]
    ):
        raise DatasetError("NORMAL_ATTESTATION_SCHEMA")
    records = receipt["samples"]
    if not isinstance(records, list) or not 1 <= len(records) <= MAX_SAMPLES:
        raise DatasetError("SAMPLE_COUNT_CAP")
    expected = {"dataset.json"}
    normal_members = set()
    for index, record in enumerate(records):
        if not isinstance(record, dict):
            raise DatasetError("SAMPLE_SCHEMA")
        is_normal = record.get("mask_origin") == NORMAL_MASK_ORIGIN
        if set(record) != SAMPLE_KEYS | (NORMAL_SAMPLE_KEYS if is_normal else set()):
            raise DatasetError("SAMPLE_SCHEMA")
        sample_id = _text(record["sample_id"], "SAMPLE_METADATA")
        if is_normal:
            if sample_id not in attestations:
                raise DatasetError("NORMAL_ATTESTATION_MEMBERSHIP")
            attestation = attestations[sample_id]
            if record["normal_attestation_sha256"] != _jcs_sha(attestation):
                raise DatasetError("NORMAL_ATTESTATION_SHA256")
            if attestation["expected_asset_sha256"] != record["image_sha256"]:
                raise DatasetError("NORMAL_ATTESTATION_ASSET_SHA256")
            normal_members.add(sample_id)
        elif sample_id in attestations:
            raise DatasetError("NORMAL_ATTESTATION_MEMBERSHIP")
        for key in ("image_path", "mask_path"):
            _relative(record[key])
        if (
            record["image_path"] != f"images/{index:04d}.image"
            or record["mask_path"] != f"masks/{index:04d}.mask"
        ):
            raise DatasetError("SAMPLE_INDEX_PATH")
        for key in ("image_sha256", "mask_sha256", "pixel_sha256", "mask_pixel_sha256"):
            if (
                not isinstance(record[key], str)
                or re.fullmatch(r"[0-9a-f]{64}", record[key]) is None
            ):
                raise DatasetError("SAMPLE_DIGEST")
        for key in ("width", "height"):
            if type(record[key]) is not int or not 1 <= record[key] <= MAX_DIMENSION:
                raise DatasetError("IMAGE_DIMENSIONS")
        expected.update((record["image_path"], record["mask_path"]))
    if normal_members != set(attestations):
        raise DatasetError("NORMAL_ATTESTATION_MEMBERSHIP")
    _exact_files(root, expected)
    _validate_membership(records)
    decoded = []
    for record in records:
        image_bytes = _read_file(root, record["image_path"])
        mask_bytes = _read_file(root, record["mask_path"])
        if (
            _sha(image_bytes) != record["image_sha256"]
            or _sha(mask_bytes) != record["mask_sha256"]
        ):
            raise DatasetError("FILE_SHA256")
        image, mask = _decode(image_bytes), _decode(mask_bytes, mask=True)
        if record.get("mask_origin") == NORMAL_MASK_ORIGIN:
            if not mask_bytes.startswith(b"\x89PNG\r\n\x1a\n"):
                raise DatasetError("NORMAL_MASK_PNG_REQUIRED")
            if np.any(mask):
                raise DatasetError("NORMAL_MASK_NOT_ZERO")
        if image.shape[:2] != mask.shape or image.shape[:2] != (
            record["height"],
            record["width"],
        ):
            raise DatasetError("MASK_DIMENSIONS")
        if (
            _pixel_sha(image) != record["pixel_sha256"]
            or _pixel_sha(mask, mask=True) != record["mask_pixel_sha256"]
        ):
            raise DatasetError("PIXEL_SHA256")
        decoded.append((record, image, mask))
    if receipt["split_fingerprints"] != _fingerprints(records) or receipt[
        "labels_sha256"
    ] != _labels_sha(records):
        raise DatasetError("SPLIT_OR_LABEL_FINGERPRINT")
    from .learning_engine import PixelSample

    samples = [
        PixelSample(
            sample_id=record["sample_id"],
            split=record["split"],
            category=record["category"],
            group_id=record["group_id"],
            image=image,
            mask=mask,
        )
        for record, image, mask in decoded
    ]
    return receipt, samples
