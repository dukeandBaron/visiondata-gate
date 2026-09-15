"""Explicit detection labels, source integrity, and held-out split isolation."""

from __future__ import annotations

import hashlib
import importlib
import json
import os
from pathlib import Path
import subprocess

from PIL import Image, PngImagePlugin
import pytest

from visiondata_gate.audit_envelope import canonical_jcs_bytes


def test_detection_dataset_module_exists():
    assert (
        Path(__file__).resolve().parents[1]
        / "src/visiondata_gate/learning_detection_dataset.py"
    ).is_file(), "explicit detection dataset implementation is missing"


@pytest.fixture
def module():
    return importlib.import_module("visiondata_gate.learning_detection_dataset")


@pytest.fixture
def source(tmp_path):
    root = tmp_path / "source"
    root.mkdir()
    samples = []
    for i, split in enumerate(("train", "val", "test")):
        path = root / f"{split}.png"
        Image.new("RGB", (12, 10), (i * 60, 120, 50)).save(path)
        samples.append(
            {
                "sample_id": f"sample-{split}",
                "image_path": path.name,
                "image_sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
                "split": split,
                "group_id": f"part-{split}",
                "annotation_revision": 1,
                "boxes": [
                    {
                        "class_id": 0,
                        "x_center": 0.5,
                        "y_center": 0.5,
                        "width": 0.5,
                        "height": 0.4,
                    }
                ],
                "reviewer_name": "fixture reviewer",
                "reviewed": True,
                "normal_attested": False,
            }
        )
    return (
        root,
        {
            "schema_version": "visiondata-gate.detection-dataset.v1",
            "class_names": ["scratch", "dent"],
            "source_version": "authorized-synthetic-v1",
            "samples": samples,
        },
        tmp_path / "frozen",
    )


def freeze(module, source):
    root, manifest, target = source
    return module.freeze_detection_dataset(
        root, manifest, target, module.manifest_sha256(manifest)
    )


def test_freeze_preserves_real_images_and_explicit_labels(module, source):
    root, manifest, target = source
    before = {p.name: p.read_bytes() for p in root.iterdir()}
    receipt = freeze(module, source)
    assert module.verify_detection_dataset(target, receipt["receipt_sha256"]) == receipt
    assert receipt["split_counts"] == {"train": 1, "val": 1, "test": 1}
    assert receipt["class_names"] == ["scratch", "dent"]
    assert (
        receipt["manifest_sha256"]
        == hashlib.sha256(canonical_jcs_bytes(manifest)).hexdigest()
    )
    assert str(root) not in json.dumps(receipt)
    assert (target / "data.yaml").read_text("utf-8") == (
        "train: images/train\nval: images/val\ntest: images/test\n"
        'names: ["scratch", "dent"]\n'
    )
    for sample in receipt["samples"]:
        assert (target / sample["image_path"]).read_bytes() == before[
            f"{sample['split']}.png"
        ]
        assert (target / sample["label_path"]).read_text("utf-8") == (
            "0 0.5 0.5 0.5 0.4\n"
        )
    assert before == {p.name: p.read_bytes() for p in root.iterdir()}


@pytest.mark.parametrize(
    "field,value",
    [
        ("reviewed", False),
        ("reviewed", 1),
        ("reviewer_name", " "),
        ("annotation_revision", True),
        ("annotation_revision", -1),
        ("sample_id", "../bad"),
        ("image_path", "../train.png"),
        ("image_path", "C:/train.png"),
        ("image_path", "dir\\train.png"),
        ("image_path", "NUL.png"),
        ("split", "validation"),
        ("group_id", ""),
        ("normal_attested", "true"),
    ],
)
def test_rejects_invalid_sample_contract(module, source, field, value):
    source[1]["samples"][0][field] = value
    with pytest.raises(ValueError):
        freeze(module, source)
    assert not source[2].exists()


@pytest.mark.parametrize(
    "field,value",
    [
        ("class_id", True),
        ("class_id", 2),
        ("class_id", -1),
        ("class_id", "0"),
        ("width", 0.0),
        ("width", 1.1),
        ("height", -0.1),
        ("x_center", 0.0),
        ("y_center", 1.0),
        ("width", float("nan")),
        ("height", float("inf")),
    ],
)
def test_rejects_invalid_explicit_box(module, source, field, value):
    source[1]["samples"][0]["boxes"][0][field] = value
    with pytest.raises(ValueError):
        freeze(module, source)
    assert not source[2].exists()


def test_no_box_requires_explicit_normal_attestation(module, source):
    source[1]["samples"][0]["boxes"] = []
    with pytest.raises(ValueError, match="NORMAL_ATTESTATION"):
        freeze(module, source)
    source[1]["samples"][0]["normal_attested"] = True
    receipt = freeze(module, source)
    assert (source[2] / receipt["samples"][0]["label_path"]).read_bytes() == b""


def test_rejects_contradictory_normal_attestation(module, source):
    source[1]["samples"][0]["normal_attested"] = True
    with pytest.raises(ValueError, match="NORMAL_ATTESTATION"):
        freeze(module, source)




@pytest.mark.parametrize("kind", ["group", "image", "pixels", "sample_id"])
def test_rejects_split_leakage(module, source, kind):
    root, manifest, _ = source
    first, second = manifest["samples"][:2]
    if kind == "group":
        second["group_id"] = first["group_id"]
    elif kind == "sample_id":
        second["sample_id"] = first["sample_id"]
    else:
        original = root / first["image_path"]
        copied = root / second["image_path"]
        if kind == "image":
            copied.write_bytes(original.read_bytes())
        else:
            info = PngImagePlugin.PngInfo()
            info.add_text("encoding_note", "different bytes, same pixels")
            with Image.open(original) as image:
                image.save(copied, pnginfo=info)
        second["image_sha256"] = hashlib.sha256(copied.read_bytes()).hexdigest()
    with pytest.raises(ValueError):
        freeze(module, source)
    assert not source[2].exists()


@pytest.mark.parametrize("split", ["train", "val", "test"])
@pytest.mark.parametrize("encoding", ["same_bytes", "same_pixels"])
def test_rejects_within_split_duplicates_before_freezing(
    module, source, split, encoding
):
    root, manifest, target = source
    sample = next(item for item in manifest["samples"] if item["split"] == split)
    original, copied = root / sample["image_path"], root / "copy.png"
    if encoding == "same_bytes":
        copied.write_bytes(original.read_bytes())
    else:
        info = PngImagePlugin.PngInfo()
        info.add_text("note", "different bytes, identical pixels")
        with Image.open(original) as image:
            image.save(copied, pnginfo=info)
    manifest["samples"].append(
        {
            **sample,
            "sample_id": "copy",
            "image_path": "copy.png",
            "image_sha256": hashlib.sha256(copied.read_bytes()).hexdigest(),
        }
    )
    with pytest.raises(ValueError, match="(?:IMAGE|PIXEL)_WITHIN_SPLIT_DUPLICATE"):
        freeze(module, source)
    assert not target.exists()


@pytest.mark.parametrize("mutation", ["extra", "classes", "missing_split"])
def test_rejects_incomplete_or_open_manifest(module, source, mutation):
    manifest = source[1]
    if mutation == "extra":
        manifest["download"] = "untrusted script"
    elif mutation == "classes":
        manifest["class_names"] = ["scratch", "scratch"]
    else:
        manifest["samples"].pop()
    with pytest.raises(ValueError):
        freeze(module, source)


def test_manifest_hash_binds_raw_request_before_defaults(module, source):
    manifest = source[1]
    del manifest["samples"][0]["normal_attested"]
    digest = hashlib.sha256(canonical_jcs_bytes(manifest)).hexdigest()
    assert module.manifest_sha256(manifest) == digest
    receipt = module.freeze_detection_dataset(source[0], manifest, source[2], digest)
    assert receipt["manifest_sha256"] == digest
    assert (
        module.verify_detection_dataset(source[2], receipt["receipt_sha256"]) == receipt
    )


def test_hash_drift_rejected_before_output(module, source):
    digest = module.manifest_sha256(source[1])
    source[1]["source_version"] = "changed"
    with pytest.raises(ValueError, match="MANIFEST_SHA"):
        module.freeze_detection_dataset(source[0], source[1], source[2], digest)
    assert not source[2].exists()


def test_source_byte_drift_rejected_before_output(module, source):
    (source[0] / "train.png").write_bytes(b"changed")
    with pytest.raises(ValueError, match="IMAGE_SHA"):
        freeze(module, source)
    assert not source[2].exists()


def test_no_overwrite_or_source_nested_output(module, source):
    source[2].mkdir()
    sentinel = source[2] / "keep.txt"
    sentinel.write_text("owned by someone else", "utf-8")
    with pytest.raises(ValueError, match="OUTPUT_EXISTS"):
        freeze(module, source)
    assert sentinel.read_text("utf-8") == "owned by someone else"
    with pytest.raises(ValueError, match="OUTPUT_INSIDE_SOURCE"):
        module.freeze_detection_dataset(
            source[0], source[1], source[0] / "new", module.manifest_sha256(source[1])
        )


@pytest.mark.parametrize(
    "target", ["image", "label", "manifest", "yaml", "receipt", "extra"]
)
def test_verify_detects_changed_members(module, source, target):
    receipt = freeze(module, source)
    paths = {
        "image": receipt["samples"][0]["image_path"],
        "label": receipt["samples"][0]["label_path"],
        "manifest": "manifest.json",
        "yaml": "data.yaml",
        "receipt": "dataset.json",
        "extra": "unexpected.py",
    }
    (source[2] / paths[target]).write_bytes(b"tampered")
    with pytest.raises(ValueError):
        module.verify_detection_dataset(source[2], receipt["receipt_sha256"])


def test_verify_cannot_trust_rehashed_receipt_metadata(module, source):
    receipt = freeze(module, source)
    receipt["samples"][0]["boxes"][0]["width"] = 0.2
    core = {
        k: v for k, v in receipt.items() if k not in {"receipt_sha256", "dataset_id"}
    }
    receipt["receipt_sha256"] = hashlib.sha256(canonical_jcs_bytes(core)).hexdigest()
    receipt["dataset_id"] = "detds_" + receipt["receipt_sha256"][:24]
    (source[2] / "dataset.json").write_bytes(canonical_jcs_bytes(receipt))
    with pytest.raises(ValueError, match="RECEIPT_METADATA"):
        module.verify_detection_dataset(source[2], receipt["receipt_sha256"])


def test_revalidates_mutated_model_instance(module, source):
    manifest = module.DetectionDatasetManifest.model_validate(source[1])
    manifest.samples[0].boxes[0].width = -0.5
    with pytest.raises(ValueError):
        module.freeze_detection_dataset(
            source[0], manifest, source[2], module.manifest_sha256(manifest)
        )


def test_rejects_oversized_images(module, source):
    path = source[0] / "train.png"
    Image.new("RGB", (2049, 2)).save(path)
    source[1]["samples"][0]["image_sha256"] = hashlib.sha256(
        path.read_bytes()
    ).hexdigest()
    with pytest.raises(ValueError, match="IMAGE_DIMENSIONS"):
        freeze(module, source)


def test_source_link_is_rejected(module, source, tmp_path):
    original = source[0] / "train.png"
    link = source[0] / "link.png"
    try:
        link.symlink_to(original)
    except OSError:
        pytest.skip("host does not permit symlink creation")
    source[1]["samples"][0]["image_path"] = link.name
    with pytest.raises(ValueError, match="PATH_LINK_OR_REPARSE"):
        freeze(module, source)


def test_hash_pinned_verifier_rejects_untrusted_whole_receipt(module, source):
    freeze(module, source)
    with pytest.raises(ValueError, match="RECEIPT_SHA"):
        module.verify_detection_dataset(source[2], "0" * 64)


def test_verifier_rejects_extra_empty_directory(module, source):
    receipt = freeze(module, source)
    (source[2] / "untracked").mkdir()
    with pytest.raises(ValueError, match="UNEXPECTED_DATASET_MEMBERS"):
        module.verify_detection_dataset(source[2], receipt["receipt_sha256"])


@pytest.mark.skipif(os.name != "nt", reason="Windows junction contract")
def test_source_junction_is_rejected(module, source, tmp_path):
    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / "train.png").write_bytes((source[0] / "train.png").read_bytes())
    junction = source[0] / "junction"
    subprocess.run(
        ["cmd", "/c", "mklink", "/J", str(junction), str(outside)],
        check=True,
        capture_output=True,
    )
    source[1]["samples"][0]["image_path"] = "junction/train.png"
    with pytest.raises(ValueError, match="PATH_LINK_OR_REPARSE"):
        freeze(module, source)


def test_total_pixels_cap_is_enforced_before_output(module, source, monkeypatch):
    monkeypatch.setattr(module, "MAX_TOTAL_PIXELS", 359)
    with pytest.raises(ValueError, match="TOTAL_PIXEL_CAP"):
        freeze(module, source)
    assert not source[2].exists()


def test_class_names_cannot_inject_yaml(module, source):
    source[1]["class_names"] = ["scratch: [x]", 'a"; download: do_bad_things']
    receipt = freeze(module, source)
    import yaml

    document = yaml.safe_load((source[2] / "data.yaml").read_text("utf-8"))
    assert set(document) == {"train", "val", "test", "names"}
    assert document["names"] == receipt["class_names"]


def test_case_aliases_are_rejected_before_output(module, source):
    source[1]["samples"][1]["sample_id"] = "SAMPLE-TRAIN"
    with pytest.raises(ValueError, match="SAMPLE_ID_DUPLICATE"):
        freeze(module, source)
