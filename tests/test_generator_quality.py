from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest
from PIL import Image

from visiondata_gate.contracts import BatchManifest, CorruptionManifest
from visiondata_gate.generator import generate_demo_dataset
from visiondata_gate.quality import inspect_image_quality


QUALITY_TRUTH = {
    ("DECODE_FAILURE", ("q-bad-file",)),
    ("INVALID_DIMENSIONS", ("q-wrong-size",)),
    ("LOW_SHARPNESS", ("q-blur",)),
    ("OVEREXPOSED", ("q-overexposed",)),
    ("UNDEREXPOSED", ("q-underexposed",)),
}


def _sha256_tree(root: Path) -> dict[str, str]:
    return {
        path.relative_to(root).as_posix(): hashlib.sha256(path.read_bytes()).hexdigest()
        for path in sorted(item for item in root.rglob("*") if item.is_file())
    }


def _load_manifest(
    path: Path, model_type: type[BatchManifest] | type[CorruptionManifest]
):
    return model_type.model_validate(json.loads(path.read_text(encoding="utf-8")))


def test_generator_is_byte_deterministic_for_a_fixed_seed(tmp_path: Path) -> None:
    first = generate_demo_dataset(tmp_path / "first", seed=20260809)
    second = generate_demo_dataset(tmp_path / "second", seed=20260809)

    assert set(first) == {
        "output_root",
        "batch_root",
        "batch_manifest",
        "corruption_manifest",
        "reserve_root",
        "reserve_manifest",
    }
    assert all(path.is_absolute() for path in first.values())
    assert _sha256_tree(first["output_root"]) == _sha256_tree(second["output_root"])


def test_generator_emits_valid_manifests_and_clean_reserve(tmp_path: Path) -> None:
    paths = generate_demo_dataset(tmp_path / "dataset", seed=17)
    batch = _load_manifest(paths["batch_manifest"], BatchManifest)
    truth = _load_manifest(paths["corruption_manifest"], CorruptionManifest)
    reserve = _load_manifest(paths["reserve_manifest"], BatchManifest)

    assert batch.batch_id == truth.batch_id
    assert batch.seed == truth.seed == reserve.seed == 17
    assert truth.reserve_manifest == "reserve/reserve_manifest.json"
    assert len(batch.samples) >= 20
    assert reserve.samples

    for sample in reserve.samples:
        image_path = paths["reserve_root"] / sample.relative_path
        mask_path = paths["reserve_root"] / str(sample.annotation_path)
        with Image.open(image_path) as image:
            image.load()
            assert image.size == (128, 128)
        with Image.open(mask_path) as mask:
            mask.load()
            assert mask.size == (128, 128)


def test_quality_corruptions_are_detected_without_extra_quality_findings(
    tmp_path: Path,
) -> None:
    paths = generate_demo_dataset(tmp_path / "dataset", seed=41)
    manifest = _load_manifest(paths["batch_manifest"], BatchManifest)

    findings, metrics = inspect_image_quality(paths["batch_root"], manifest)
    observed = {
        (finding.code, tuple(sorted(finding.sample_ids))) for finding in findings
    }

    assert observed == QUALITY_TRUTH
    assert metrics["sample_count"] == len(manifest.samples)
    assert metrics["decode_failure_count"] == 1
    assert metrics["invalid_dimension_count"] == 1
    assert metrics["low_sharpness_count"] == 1
    assert metrics["overexposed_count"] == 1
    assert metrics["underexposed_count"] == 1


def test_quality_tool_does_not_swallow_missing_root(tmp_path: Path) -> None:
    paths = generate_demo_dataset(tmp_path / "dataset", seed=5)
    manifest = _load_manifest(paths["batch_manifest"], BatchManifest)

    with pytest.raises(FileNotFoundError):
        inspect_image_quality(tmp_path / "does-not-exist", manifest)
