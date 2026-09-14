"""Real tiny-image tests for immutable, split-safe local learning datasets."""

from __future__ import annotations

import hashlib
import importlib
import json
import os
from pathlib import Path
import subprocess

import numpy as np
from PIL import Image, PngImagePlugin
import pytest

from visiondata_gate.audit_envelope import canonical_jcs_bytes
from visiondata_gate.contracts import BatchManifest, SampleRecord


def test_learning_dataset_module_exists():
    path = (
        Path(__file__).resolve().parents[1] / "src/visiondata_gate/learning_dataset.py"
    )
    assert path.is_file(), "the independent dataset freezing module is missing"


@pytest.fixture
def dataset():
    return importlib.import_module("visiondata_gate.learning_dataset")


def _png(path, values, **kwargs):
    path.parent.mkdir(parents=True, exist_ok=True)
    Image.fromarray(values).save(path, format="PNG", **kwargs)


@pytest.fixture
def source(tmp_path):
    root = tmp_path / "source"
    samples = []
    for index, split in enumerate(("train", "val", "test")):
        image = np.zeros((8, 9, 3), dtype=np.uint8)
        image[..., 0] = 10 + index * 50
        image[1:4, 2:5, 1] = 200
        mask = np.zeros((8, 9), dtype=np.uint8)
        if split != "test":
            mask[1:4, 2:5] = 255
        _png(root / f"images/{split}.png", image)
        _png(root / f"masks/{split}.png", mask)
        samples.append(
            SampleRecord(
                sample_id=f"sample-{split}",
                relative_path=f"images/{split}.png",
                annotation_path=f"masks/{split}.png",
                split=split,
                category="normal" if split == "test" else "defect",
                view="top",
                condition="fixture",
            )
        )
    manifest = BatchManifest(batch_id="synthetic", seed=1, samples=samples)
    groups = {sample.sample_id: "group-" + sample.split for sample in samples}
    return root, manifest, groups, tmp_path / "dataset"


def freeze(dataset, source, binding=None):
    root, manifest, groups, destination = source
    return dataset.freeze_dataset(
        root,
        manifest,
        binding or {"task_id": "task-1", "round": 1},
        groups,
        destination,
    )


def _rehash_receipt(path, mutate):
    receipt = json.loads(path.read_text(encoding="utf-8"))
    mutate(receipt)
    core = {
        key: value
        for key, value in receipt.items()
        if key not in {"receipt_sha256", "dataset_id"}
    }
    digest = hashlib.sha256(canonical_jcs_bytes(core)).hexdigest()
    receipt["receipt_sha256"] = digest
    receipt["dataset_id"] = "dataset_" + digest[:24]
    path.write_bytes(canonical_jcs_bytes(receipt))


def test_freeze_and_load_real_rgb_and_binary_masks(dataset, source):
    receipt = freeze(dataset, source)
    loaded, samples = dataset.load_dataset(source[3])
    assert loaded == receipt
    assert len(samples) == 3
    assert {sample.split for sample in samples} == {"train", "val", "test"}
    for sample in samples:
        assert sample.image.dtype == np.uint8
        assert sample.image.shape == (8, 9, 3)
        assert sample.mask.dtype == np.uint8
        assert set(np.unique(sample.mask)).issubset({0, 1})
    assert not next(
        sample for sample in samples if sample.category == "normal"
    ).mask.any()
    core = {
        key: value
        for key, value in receipt.items()
        if key not in {"receipt_sha256", "dataset_id"}
    }
    assert (
        receipt["receipt_sha256"]
        == hashlib.sha256(canonical_jcs_bytes(core)).hexdigest()
    )
    assert receipt["dataset_id"] == "dataset_" + receipt["receipt_sha256"][:24]
    assert (source[3] / "dataset.json").read_bytes() == canonical_jcs_bytes(receipt)
    assert str(source[0]) not in json.dumps(receipt)


def test_original_file_bytes_are_copied_and_fingerprinted(dataset, source):
    receipt = freeze(dataset, source)
    for original, frozen in zip(source[1].samples, receipt["samples"]):
        for path_key, hash_key, original_path in (
            ("image_path", "image_sha256", original.relative_path),
            ("mask_path", "mask_sha256", original.annotation_path),
        ):
            copied = (source[3] / frozen[path_key]).read_bytes()
            assert copied == (source[0] / original_path).read_bytes()
            assert hashlib.sha256(copied).hexdigest() == frozen[hash_key]
        assert len(frozen["pixel_sha256"]) == 64
        assert len(frozen["mask_pixel_sha256"]) == 64


def test_missing_mask_never_synthesized(dataset, source):
    source[1].samples[0].annotation_path = None
    with pytest.raises(ValueError, match="MASK_REQUIRED"):
        freeze(dataset, source)
    assert not source[3].exists()


@pytest.mark.parametrize(
    "values",
    [np.array([[0, 2]], dtype=np.uint8), np.array([[0, 1, 255]], dtype=np.uint8)],
)
def test_nonbinary_or_mixed_mask_values_rejected(dataset, source, values):
    _png(source[0] / "masks/train.png", np.resize(values, (8, 9)))
    with pytest.raises(ValueError, match="MASK_BINARY_VALUES"):
        freeze(dataset, source)


def test_mask_shape_must_match_image(dataset, source):
    _png(source[0] / "masks/train.png", np.zeros((7, 9), dtype=np.uint8))
    with pytest.raises(ValueError, match="MASK_DIMENSIONS"):
        freeze(dataset, source)


def test_group_cannot_cross_splits(dataset, source):
    source[2]["sample-val"] = source[2]["sample-train"]
    with pytest.raises(ValueError, match="GROUP_SPLIT_LEAKAGE"):
        freeze(dataset, source)


@pytest.mark.parametrize("change", ["missing", "extra"])
def test_group_keys_must_exactly_cover_sample_ids(dataset, source, change):
    if change == "missing":
        source[2].pop("sample-train")
    else:
        source[2]["unknown"] = "extra-group"
    with pytest.raises(ValueError, match="GROUP_KEYS"):
        freeze(dataset, source)


def test_same_decoded_image_reencoded_cannot_cross_split(dataset, source):
    image = np.asarray(Image.open(source[0] / "images/train.png").convert("RGB"))
    metadata = PngImagePlugin.PngInfo()
    metadata.add_text("different_encoding", "same actual pixels")
    _png(source[0] / "images/val.png", image, pnginfo=metadata, compress_level=0)
    assert (source[0] / "images/train.png").read_bytes() != (
        source[0] / "images/val.png"
    ).read_bytes()
    with pytest.raises(ValueError, match="PIXEL_SPLIT_LEAKAGE"):
        freeze(dataset, source)


def test_all_three_splits_required(dataset, source):
    source[1].samples[2].split = "val"
    with pytest.raises(ValueError, match="SPLITS_REQUIRED"):
        freeze(dataset, source)


def test_mutated_manifest_duplicate_ids_rejected(dataset, source):
    source[1].samples[1].sample_id = source[1].samples[0].sample_id
    with pytest.raises(ValueError, match="SAMPLE_IDS"):
        freeze(dataset, source)


@pytest.mark.parametrize(
    "value",
    [
        "../escape.png",
        "images/../images/train.png",
        "C:/private.png",
        "/absolute.png",
        "images/train.png:stream",
        "images\\train.png",
    ],
)
def test_mutated_manifest_unsafe_paths_rejected(dataset, source, value):
    source[1].samples[0].relative_path = value
    with pytest.raises(ValueError, match="RELATIVE_PATH"):
        freeze(dataset, source)
    assert not source[3].exists()


def test_existing_destination_never_overwritten(dataset, source):
    source[3].mkdir()
    marker = source[3] / "user.txt"
    marker.write_text("keep", encoding="utf-8")
    with pytest.raises(ValueError, match="DESTINATION_EXISTS"):
        freeze(dataset, source)
    assert marker.read_text(encoding="utf-8") == "keep"


def test_sample_id_not_used_as_path(dataset, source):
    source[1].samples[0].sample_id = "../../opaque-id"
    source[2]["../../opaque-id"] = source[2].pop("sample-train")
    receipt = freeze(dataset, source)
    assert all("opaque" not in row["image_path"] for row in receipt["samples"])


def test_frozen_image_tamper_rejected(dataset, source):
    receipt = freeze(dataset, source)
    (source[3] / receipt["samples"][0]["image_path"]).write_bytes(b"tampered")
    with pytest.raises(ValueError, match="FILE_SHA256"):
        dataset.load_dataset(source[3])


def test_receipt_tamper_rejected(dataset, source):
    freeze(dataset, source)
    path = source[3] / "dataset.json"
    receipt = json.loads(path.read_text(encoding="utf-8"))
    receipt["binding"]["round"] = 999
    path.write_bytes(canonical_jcs_bytes(receipt))
    with pytest.raises(ValueError, match="RECEIPT_SHA256"):
        dataset.load_dataset(source[3])


def test_rehashed_receipt_cannot_forge_decoded_pixels(dataset, source):
    freeze(dataset, source)
    _rehash_receipt(
        source[3] / "dataset.json",
        lambda receipt: receipt["samples"][0].update(pixel_sha256="0" * 64),
    )
    with pytest.raises(ValueError, match="PIXEL_SHA256"):
        dataset.load_dataset(source[3])


def test_rehashed_receipt_cannot_escape_root(dataset, source):
    freeze(dataset, source)
    _rehash_receipt(
        source[3] / "dataset.json",
        lambda receipt: receipt["samples"][0].update(image_path="../outside.png"),
    )
    with pytest.raises(ValueError, match="RELATIVE_PATH"):
        dataset.load_dataset(source[3])


def test_unexpected_frozen_data_rejected(dataset, source):
    freeze(dataset, source)
    (source[3] / "unexpected.sqlite").write_bytes(b"not scanned business data")
    with pytest.raises(ValueError, match="FILE_SET"):
        dataset.load_dataset(source[3])


def test_split_fingerprints_ignore_binding_and_reuploaded_sample_ids(
    dataset, source, tmp_path
):
    first = freeze(dataset, source)
    renamed = source[1].model_copy(deep=True)
    renamed_groups = {}
    for sample in renamed.samples:
        group = source[2][sample.sample_id]
        sample.sample_id = "new-" + sample.sample_id
        renamed_groups[sample.sample_id] = group
    second = dataset.freeze_dataset(
        source[0],
        renamed,
        {"task_id": "task-2", "round": 2},
        renamed_groups,
        tmp_path / "next-dataset",
    )
    assert first["dataset_id"] != second["dataset_id"]
    assert first["split_fingerprints"] == second["split_fingerprints"]


def test_binding_rejects_private_absolute_paths(dataset, source):
    with pytest.raises(ValueError, match="BINDING_PRIVATE_PATH"):
        freeze(
            dataset,
            source,
            binding={"source_path": "D:/authorized-data/private"},
        )


def test_image_dimension_cap_before_freeze(dataset, source):
    _png(source[0] / "images/train.png", np.zeros((257, 1, 3), dtype=np.uint8))
    with pytest.raises(ValueError, match="IMAGE_DIMENSIONS"):
        freeze(dataset, source)


def test_file_byte_cap_rejected_before_decode(dataset, source):
    (source[0] / "images/train.png").write_bytes(b"X" * (4 * 1024 * 1024 + 1))
    with pytest.raises(ValueError, match="FILE_BYTE_CAP"):
        freeze(dataset, source)


def test_sample_count_cap_rejected_before_any_copy(dataset, source):
    source[1].samples = [source[1].samples[0].model_copy(deep=True) for _ in range(65)]
    with pytest.raises(ValueError, match="SAMPLE_COUNT_CAP"):
        freeze(dataset, source)
    assert not source[3].exists()


def test_total_pixel_cap_rejected(dataset, source):
    samples = []
    groups = {}
    for index in range(16):
        split = ("train", "val", "test")[index % 3]
        _png(
            source[0] / f"large/{index}.png",
            np.full((256, 256, 3), index, dtype=np.uint8),
        )
        _png(
            source[0] / f"large/{index}.mask.png", np.zeros((256, 256), dtype=np.uint8)
        )
        sample = (
            source[1]
            .samples[0]
            .model_copy(
                update={
                    "sample_id": f"large-{index}",
                    "split": split,
                    "relative_path": f"large/{index}.png",
                    "annotation_path": f"large/{index}.mask.png",
                }
            )
        )
        samples.append(sample)
        groups[sample.sample_id] = f"group-{index}"
    source[1].samples = samples
    with pytest.raises(ValueError, match="TOTAL_PIXEL_CAP"):
        dataset.freeze_dataset(source[0], source[1], {}, groups, source[3])
    assert not source[3].exists()


def test_rgb_mask_is_not_silently_grayscaled(dataset, source):
    _png(source[0] / "masks/train.png", np.zeros((8, 9, 3), dtype=np.uint8))
    with pytest.raises(ValueError, match="MASK_BINARY_VALUES"):
        freeze(dataset, source)


def test_reencoding_same_pixels_preserves_split_fingerprints(dataset, source, tmp_path):
    first = freeze(dataset, source)
    for sample in source[1].samples:
        image = np.array(Image.open(source[0] / sample.relative_path).convert("RGB"))
        _png(source[0] / sample.relative_path, image, compress_level=0)
        mask = np.array(Image.open(source[0] / sample.annotation_path))
        _png(source[0] / sample.annotation_path, (mask > 0).astype(np.uint8))
    second = dataset.freeze_dataset(
        source[0], source[1], {"round": 2}, source[2], tmp_path / "reencoded"
    )
    assert first["samples"][0]["image_sha256"] != second["samples"][0]["image_sha256"]
    assert first["samples"][0]["mask_sha256"] != second["samples"][0]["mask_sha256"]
    assert first["split_fingerprints"] == second["split_fingerprints"]


def test_source_changes_mid_freeze_leaves_partial_directory_intact(
    dataset, source, monkeypatch
):
    original = dataset._read_file
    reads = {}

    def changed(root, path, **kwargs):
        content = original(root, path, **kwargs)
        reads[path] = reads.get(path, 0) + 1
        return (
            content + b"changed"
            if path == "images/train.png" and reads[path] == 2
            else content
        )

    monkeypatch.setattr(dataset, "_read_file", changed)
    with pytest.raises(ValueError, match="SOURCE_CHANGED_DURING_FREEZE"):
        freeze(dataset, source)
    assert source[3].is_dir()
    assert (source[3] / "images").is_dir()
    assert not (source[3] / "dataset.json").exists()


def test_source_junction_is_rejected(dataset, source):
    if os.name != "nt":
        pytest.skip("Windows junction test")
    junction = source[0] / "linked_images"
    result = subprocess.run(
        ["cmd", "/c", "mklink", "/J", str(junction), str(source[0] / "images")],
        capture_output=True,
        check=False,
    )
    if result.returncode != 0:
        pytest.skip("Windows junction creation unavailable")
    try:
        source[1].samples[0].relative_path = "linked_images/train.png"
        with pytest.raises(ValueError, match="PATH_LINK_OR_REPARSE"):
            freeze(dataset, source)
    finally:
        os.rmdir(junction)


@pytest.mark.parametrize("field", ["sample_id", "split", "group_id"])
def test_rehashed_invalid_metadata_is_rejected_as_value_error(dataset, source, field):
    freeze(dataset, source)
    _rehash_receipt(
        source[3] / "dataset.json",
        lambda receipt: receipt["samples"][0].update({field: ["invalid"]}),
    )
    with pytest.raises(ValueError, match="SAMPLE_METADATA|SPLITS_REQUIRED"):
        dataset.load_dataset(source[3])


def _normal_attestation(source, sample_id="sample-test"):
    sample = next(item for item in source[1].samples if item.sample_id == sample_id)
    return {
        "reviewer_name": "Synthetic normal reviewer",
        "review_note": "SYNTHETIC_TEST_ACTOR explicitly reviewed no foreground in this image",
        "expected_asset_sha256": hashlib.sha256(
            (source[0] / sample.relative_path).read_bytes()
        ).hexdigest(),
        "expected_annotation_revision": 0,
        "expected_annotation_sha256": hashlib.sha256(b'{"annotations":[]}').hexdigest(),
        "operator_attests_no_foreground": True,
    }


def _freeze_normal(dataset, source, attestations):
    return dataset.freeze_dataset(
        source[0],
        source[1],
        {"task_id": "synthetic-normal-task"},
        source[2],
        source[3],
        normal_attestations=attestations,
    )


def test_explicit_normal_attestation_derives_zero_mask_without_changing_source(
    dataset, source
):
    sample = source[1].samples[2]
    sample.annotation_path = None
    before = {
        path.relative_to(source[0]).as_posix(): path.read_bytes()
        for path in source[0].rglob("*")
        if path.is_file()
    }
    attestation = _normal_attestation(source)
    receipt = _freeze_normal(dataset, source, {sample.sample_id: attestation})
    record = next(
        row for row in receipt["samples"] if row["sample_id"] == sample.sample_id
    )
    assert record["mask_origin"] == "EXPLICIT_HUMAN_ZERO_MASK"
    assert (
        record["normal_attestation_sha256"]
        == hashlib.sha256(canonical_jcs_bytes(attestation)).hexdigest()
    )
    assert receipt["normal_mask_attestations"] == {sample.sample_id: attestation}
    mask_bytes = (source[3] / record["mask_path"]).read_bytes()
    assert mask_bytes.startswith(b"\x89PNG\r\n\x1a\n")
    assert record["mask_sha256"] == hashlib.sha256(mask_bytes).hexdigest()
    loaded, pixels = dataset.load_dataset(source[3])
    assert loaded == receipt
    assert not next(
        row for row in pixels if row.sample_id == sample.sample_id
    ).mask.any()
    after = {
        path.relative_to(source[0]).as_posix(): path.read_bytes()
        for path in source[0].rglob("*")
        if path.is_file()
    }
    assert after == before
    assert sample.annotation_path is None


def test_empty_normal_attestations_keep_legacy_receipt_bytes(dataset, source, tmp_path):
    old = freeze(dataset, source)
    new_root = tmp_path / "empty-normal-option"
    current = dataset.freeze_dataset(
        source[0],
        source[1],
        {"task_id": "task-1", "round": 1},
        source[2],
        new_root,
        normal_attestations={},
    )
    assert current == old
    assert (new_root / "dataset.json").read_bytes() == (
        source[3] / "dataset.json"
    ).read_bytes()
    assert "normal_mask_attestations" not in old
    assert all(
        "mask_origin" not in row and "normal_attestation_sha256" not in row
        for row in old["samples"]
    )


def test_normal_attestation_conflicts_with_existing_source_mask(dataset, source):
    with pytest.raises(ValueError, match="NORMAL_ATTESTATION_WITH_SOURCE_MASK"):
        _freeze_normal(dataset, source, {"sample-test": _normal_attestation(source)})
    assert not source[3].exists()


def test_unknown_normal_attestation_sample_rejected(dataset, source):
    with pytest.raises(ValueError, match="NORMAL_ATTESTATION_UNKNOWN_SAMPLE"):
        _freeze_normal(dataset, source, {"unknown-sample": _normal_attestation(source)})
    assert not source[3].exists()


def test_normal_attestation_stale_image_sha_rejected(dataset, source):
    source[1].samples[2].annotation_path = None
    attestation = _normal_attestation(source) | {"expected_asset_sha256": "0" * 64}
    with pytest.raises(ValueError, match="NORMAL_ATTESTATION_ASSET_SHA256"):
        _freeze_normal(dataset, source, {"sample-test": attestation})
    assert not source[3].exists()


@pytest.mark.parametrize(
    "mutation",
    [
        {"operator_attests_no_foreground": False},
        {"expected_annotation_revision": -1},
        {"expected_annotation_sha256": "invalid"},
        {"reviewer_name": ""},
        {"unknown_permission": True},
    ],
)
def test_normal_attestation_schema_is_validated(dataset, source, mutation):
    source[1].samples[2].annotation_path = None
    with pytest.raises(ValueError, match="NORMAL_ATTESTATION_SCHEMA"):
        _freeze_normal(
            dataset, source, {"sample-test": _normal_attestation(source) | mutation}
        )


def test_self_rehashed_nonzero_normal_mask_is_rejected(dataset, source):
    source[1].samples[2].annotation_path = None
    receipt = _freeze_normal(
        dataset, source, {"sample-test": _normal_attestation(source)}
    )
    record = receipt["samples"][2]
    tampered = np.zeros((8, 9), dtype=np.uint8)
    tampered[0, 0] = 1
    _png(source[3] / record["mask_path"], tampered)

    def alter(value):
        row = value["samples"][2]
        row["mask_sha256"] = hashlib.sha256(
            (source[3] / row["mask_path"]).read_bytes()
        ).hexdigest()
        row["mask_pixel_sha256"] = dataset._pixel_sha(tampered, mask=True)
        value["split_fingerprints"] = dataset._fingerprints(value["samples"])
        value["labels_sha256"] = dataset._labels_sha(value["samples"])

    _rehash_receipt(source[3] / "dataset.json", alter)
    with pytest.raises(ValueError, match="NORMAL_MASK_NOT_ZERO"):
        dataset.load_dataset(source[3])


def test_normal_attestation_digest_tamper_rejected(dataset, source):
    source[1].samples[2].annotation_path = None
    _freeze_normal(dataset, source, {"sample-test": _normal_attestation(source)})
    _rehash_receipt(
        source[3] / "dataset.json",
        lambda value: value["samples"][2].update(normal_attestation_sha256="0" * 64),
    )
    with pytest.raises(ValueError, match="NORMAL_ATTESTATION_SHA256"):
        dataset.load_dataset(source[3])


def test_loader_rejects_unreferenced_normal_attestation(dataset, source):
    source[1].samples[2].annotation_path = None
    _freeze_normal(dataset, source, {"sample-test": _normal_attestation(source)})
    _rehash_receipt(
        source[3] / "dataset.json",
        lambda value: value["normal_mask_attestations"].update(
            unknown=value["normal_mask_attestations"]["sample-test"]
        ),
    )
    with pytest.raises(ValueError, match="NORMAL_ATTESTATION_MEMBERSHIP"):
        dataset.load_dataset(source[3])


def test_all_normal_train_can_freeze_but_engine_rejects_missing_positive_class(
    dataset, source
):
    from visiondata_gate.learning_engine import TrainingConfig, train_model

    attestations = {}
    for sample in source[1].samples:
        sample.annotation_path = None
        attestations[sample.sample_id] = _normal_attestation(source, sample.sample_id)
    _freeze_normal(dataset, source, attestations)
    _, samples = dataset.load_dataset(source[3])
    with pytest.raises(ValueError, match="CLASS|POSITIVE"):
        train_model(
            [row for row in samples if row.split == "train"], TrainingConfig(epochs=1)
        )
