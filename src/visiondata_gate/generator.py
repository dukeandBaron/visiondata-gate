"""Deterministic synthetic data for the auditable image-gate demo.

The generator deliberately keeps the hidden truth outside ``batch_root``.  The
tools therefore see only the public batch manifest and data files, while the
evaluator can load the sibling corruption manifest afterwards.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

import numpy as np
from PIL import Image, ImageFilter

from .contracts import (
    BatchManifest,
    CorruptionManifest,
    SampleRecord,
    Severity,
    TruthIssue,
)


_WIDTH = 128
_HEIGHT = 128


@dataclass(frozen=True)
class _SampleSpec:
    sample_id: str
    split: Literal["train", "val", "test"]
    category: str
    view: str
    condition: str
    corruption: str = "clean"
    copy_from: str | None = None


def _sample_seed(seed: int, sample_id: str) -> int:
    digest = hashlib.sha256(f"{seed}:{sample_id}".encode("utf-8")).digest()
    return int.from_bytes(digest[:8], byteorder="big", signed=False)


def _industrial_scene(seed: int, spec: _SampleSpec) -> tuple[np.ndarray, np.ndarray]:
    """Render one RGB industrial-style scene and its binary object mask."""

    rng = np.random.default_rng(_sample_seed(seed, spec.sample_id))
    yy, xx = np.mgrid[0:_HEIGHT, 0:_WIDTH]
    center_x = 64 + int(rng.integers(-8, 9))
    center_y = 64 + int(rng.integers(-7, 8))
    x_scale = 1.0 if spec.view == "front" else 0.76
    dx = (xx - center_x) / x_scale
    dy = yy - center_y
    radius = np.sqrt(dx * dx + dy * dy)
    angle = np.arctan2(dy, dx)

    if spec.category == "bearing":
        outer = radius <= 35
        inner = radius < 16
        object_mask = outer & ~inner
        metallic = 144 + 25 * np.cos(angle * 6) + 18 * np.cos(radius * 0.75)
    else:
        tooth_boundary = 30 + 5 * (np.cos(angle * 12) > 0.25)
        outer = radius <= tooth_boundary
        inner = radius < 10
        object_mask = outer & ~inner
        metallic = 132 + 31 * np.cos(angle * 12) + 15 * np.sin(radius * 0.82)

    background_level = 116 if spec.condition == "bright" else 68
    background = (
        background_level
        + 0.10 * (xx - 64)
        + 7 * np.sin((xx + yy) / 17.0)
        + rng.normal(0.0, 5.0, size=(_HEIGHT, _WIDTH))
    )
    gray = np.where(object_mask, metallic, background)
    gray = np.where(inner, background_level * 0.48, gray)

    rgb = np.stack((gray * 0.92, gray, gray * 1.06), axis=-1)
    if spec.category == "gear":
        rgb[..., 0] += object_mask * 8
        rgb[..., 2] -= object_mask * 5

    # Seeded fiducials and surface marks make unrelated scenes perceptually
    # distinguishable while retaining an unmistakably industrial appearance.
    for _ in range(7):
        x0 = int(rng.integers(5, 116))
        y0 = int(rng.integers(5, 116))
        width = int(rng.integers(3, 11))
        height = int(rng.integers(2, 7))
        delta = int(rng.choice(np.array([-48, -31, 34, 52])))
        rgb[y0 : y0 + height, x0 : x0 + width, :] += delta

    image = np.clip(np.rint(rgb), 0, 255).astype(np.uint8)
    mask = (object_mask.astype(np.uint8) * 255).astype(np.uint8)
    return image, mask


def _apply_corruption(
    image: np.ndarray,
    mask: np.ndarray,
    corruption: str,
) -> tuple[np.ndarray, np.ndarray]:
    if corruption == "clean":
        return image, mask
    if corruption == "blur":
        blurred = Image.fromarray(image, mode="RGB").filter(
            ImageFilter.GaussianBlur(radius=4.5)
        )
        return np.asarray(blurred, dtype=np.uint8), mask
    if corruption == "overexposed":
        changed = np.clip(image.astype(np.float32) * 0.35 + 205.0, 0, 255).astype(
            np.uint8
        )
        return changed, mask
    if corruption == "underexposed":
        changed = np.clip(image.astype(np.float32) * 0.24, 0, 255).astype(np.uint8)
        return changed, mask
    if corruption == "wrong_size":
        return image[:, :96, :], mask
    if corruption == "near_copy":
        changed = image.copy()
        old_value = int(changed[5, 5, 0])
        changed[5, 5, 0] = old_value - 1 if old_value == 255 else old_value + 1
        return changed, mask
    if corruption in {"bad_file", "missing_annotation", "wrong_annotation_size"}:
        return image, mask
    raise ValueError(f"unknown corruption mode: {corruption}")


def _save_png(path: Path, array: np.ndarray, mode: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    Image.fromarray(array, mode=mode).save(path, format="PNG", compress_level=9)


def _write_json(path: Path, model: BatchManifest | CorruptionManifest) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = json.dumps(
        model.model_dump(mode="json"),
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    )
    path.write_text(payload + "\n", encoding="utf-8", newline="\n")


def _batch_specs() -> list[_SampleSpec]:
    specs: list[_SampleSpec] = []
    for category in ("bearing", "gear"):
        for view in ("front", "side"):
            for condition in ("bright", "dim"):
                if (category, view, condition) == ("gear", "side", "dim"):
                    continue
                specs.append(
                    _SampleSpec(
                        sample_id=f"base-{category}-{view}-{condition}",
                        split="train",
                        category=category,
                        view=view,
                        condition=condition,
                    )
                )

    specs.extend(
        [
            _SampleSpec("clean-val-bearing", "val", "bearing", "front", "bright"),
            _SampleSpec("clean-val-gear", "val", "gear", "side", "dim"),
            _SampleSpec("clean-test-bearing", "test", "bearing", "side", "bright"),
            _SampleSpec("clean-test-gear", "test", "gear", "front", "dim"),
            _SampleSpec("q-blur", "train", "bearing", "front", "bright", "blur"),
            _SampleSpec(
                "q-overexposed", "train", "gear", "front", "bright", "overexposed"
            ),
            _SampleSpec(
                "q-underexposed", "train", "bearing", "side", "dim", "underexposed"
            ),
            _SampleSpec("q-bad-file", "train", "gear", "side", "bright", "bad_file"),
            _SampleSpec("q-wrong-size", "train", "gear", "front", "dim", "wrong_size"),
            _SampleSpec("dup-same-source", "train", "bearing", "side", "bright"),
            _SampleSpec(
                "dup-same-copy",
                "train",
                "bearing",
                "side",
                "bright",
                copy_from="dup-same-source",
            ),
            _SampleSpec("leak-exact-source", "train", "gear", "front", "bright"),
            _SampleSpec(
                "leak-exact-copy",
                "val",
                "gear",
                "front",
                "bright",
                copy_from="leak-exact-source",
            ),
            _SampleSpec("leak-near-source", "train", "bearing", "front", "dim"),
            _SampleSpec(
                "leak-near-copy",
                "test",
                "bearing",
                "front",
                "dim",
                corruption="near_copy",
                copy_from="leak-near-source",
            ),
            _SampleSpec(
                "ann-missing",
                "train",
                "bearing",
                "side",
                "bright",
                "missing_annotation",
            ),
            _SampleSpec(
                "ann-wrong-size",
                "train",
                "gear",
                "side",
                "bright",
                "wrong_annotation_size",
            ),
        ]
    )
    return specs


def _render_batch(
    batch_root: Path, specs: list[_SampleSpec], seed: int
) -> list[SampleRecord]:
    rendered: dict[str, tuple[np.ndarray, np.ndarray]] = {}
    records: list[SampleRecord] = []

    for spec in specs:
        if spec.copy_from is None:
            base_image, base_mask = _industrial_scene(seed, spec)
        else:
            try:
                source_image, source_mask = rendered[spec.copy_from]
            except KeyError as exc:
                raise ValueError(
                    f"copy source {spec.copy_from!r} must precede {spec.sample_id!r}"
                ) from exc
            base_image, base_mask = source_image.copy(), source_mask.copy()

        image, mask = _apply_corruption(base_image, base_mask, spec.corruption)
        rendered[spec.sample_id] = (image.copy(), mask.copy())
        image_relative = f"images/{spec.sample_id}.png"
        mask_relative = f"masks/{spec.sample_id}.png"
        image_path = batch_root / image_relative
        mask_path = batch_root / mask_relative

        if spec.corruption == "bad_file":
            image_path.parent.mkdir(parents=True, exist_ok=True)
            image_path.write_bytes(b"VISIONDATA_GATE_INTENTIONAL_BAD_IMAGE\n")
        else:
            _save_png(image_path, image, "RGB")

        if spec.corruption != "missing_annotation":
            mask_to_write = (
                mask[:, :64] if spec.corruption == "wrong_annotation_size" else mask
            )
            _save_png(mask_path, mask_to_write, "L")

        records.append(
            SampleRecord(
                sample_id=spec.sample_id,
                relative_path=image_relative,
                annotation_path=mask_relative,
                split=spec.split,
                category=spec.category,
                view=spec.view,
                condition=spec.condition,
            )
        )
    return records


def _reserve_specs(batch_specs: list[_SampleSpec]) -> list[_SampleSpec]:
    replace_ids = {
        "q-blur",
        "q-overexposed",
        "q-underexposed",
        "q-bad-file",
        "q-wrong-size",
        "dup-same-copy",
        "leak-exact-copy",
        "leak-near-copy",
        "ann-missing",
        "ann-wrong-size",
    }
    reserves = [
        _SampleSpec(
            sample_id=f"reserve-{spec.sample_id}",
            split=spec.split,
            category=spec.category,
            view=spec.view,
            condition=spec.condition,
        )
        for spec in batch_specs
        if spec.sample_id in replace_ids
    ]
    reserves.append(
        _SampleSpec(
            "reserve-coverage-gear-side-dim",
            "train",
            "gear",
            "side",
            "dim",
        )
    )
    return reserves


def _render_reserve(
    reserve_root: Path,
    specs: list[_SampleSpec],
    seed: int,
) -> list[SampleRecord]:
    records: list[SampleRecord] = []
    for spec in specs:
        image, mask = _industrial_scene(seed, spec)
        image_relative = f"images/{spec.sample_id}.png"
        mask_relative = f"masks/{spec.sample_id}.png"
        _save_png(reserve_root / image_relative, image, "RGB")
        _save_png(reserve_root / mask_relative, mask, "L")
        source_sample_id = spec.sample_id.removeprefix("reserve-")
        if source_sample_id == "coverage-gear-side-dim":
            source_sample_id = None
        records.append(
            SampleRecord(
                sample_id=spec.sample_id,
                relative_path=image_relative,
                annotation_path=mask_relative,
                split=spec.split,
                category=spec.category,
                view=spec.view,
                condition=spec.condition,
                source_sample_id=source_sample_id,
            )
        )
    return records


def _truth_manifest(seed: int, batch_id: str) -> CorruptionManifest:
    issue_specs = [
        ("LOW_SHARPNESS", Severity.HIGH, ["q-blur"], ["image_quality"]),
        ("OVEREXPOSED", Severity.HIGH, ["q-overexposed"], ["image_quality"]),
        ("UNDEREXPOSED", Severity.HIGH, ["q-underexposed"], ["image_quality"]),
        ("DECODE_FAILURE", Severity.CRITICAL, ["q-bad-file"], ["image_quality"]),
        ("INVALID_DIMENSIONS", Severity.HIGH, ["q-wrong-size"], ["image_quality"]),
        (
            "EXACT_DUPLICATE",
            Severity.MEDIUM,
            ["dup-same-copy", "dup-same-source"],
            ["duplicate_leakage"],
        ),
        (
            "EXACT_DUPLICATE",
            Severity.MEDIUM,
            ["leak-exact-copy", "leak-exact-source"],
            ["duplicate_leakage"],
        ),
        (
            "CROSS_SPLIT_EXACT_DUPLICATE",
            Severity.CRITICAL,
            ["leak-exact-copy", "leak-exact-source"],
            ["duplicate_leakage"],
        ),
        (
            "CROSS_SPLIT_NEAR_DUPLICATE",
            Severity.HIGH,
            ["leak-near-copy", "leak-near-source"],
            ["duplicate_leakage"],
        ),
        (
            "MISSING_ANNOTATION",
            Severity.HIGH,
            ["ann-missing"],
            ["annotation_integrity"],
        ),
        (
            "ANNOTATION_DIMENSION_MISMATCH",
            Severity.HIGH,
            ["ann-wrong-size"],
            ["annotation_integrity"],
        ),
        ("COVERAGE_GAP", Severity.HIGH, [], ["coverage_matrix"]),
    ]
    issues = [
        TruthIssue(
            issue_id=f"truth-{index:03d}",
            code=code,
            severity=severity,
            sample_ids=sorted(sample_ids),
            detectable_by=detectable_by,
        )
        for index, (code, severity, sample_ids, detectable_by) in enumerate(
            issue_specs, start=1
        )
    ]
    return CorruptionManifest(
        seed=seed,
        batch_id=batch_id,
        issues=issues,
        reserve_manifest="reserve/reserve_manifest.json",
    )


def generate_demo_dataset(output_dir: str | Path, seed: int) -> dict[str, Path]:
    """Generate a deterministic dirty batch, hidden truth, and clean reserve.

    The function only creates or replaces its named demo artifacts under the
    explicitly supplied directory.  It never deletes unrelated files.
    """

    if isinstance(seed, bool) or not isinstance(seed, int):
        raise TypeError("seed must be an integer")
    if seed < 0:
        raise ValueError("seed must be non-negative")

    root = Path(output_dir).expanduser().resolve()
    if root.exists() and not root.is_dir():
        raise NotADirectoryError(root)
    batch_root = root / "batch"
    reserve_root = root / "reserve"
    hidden_root = root / "hidden"
    for directory in (batch_root, reserve_root, hidden_root):
        directory.mkdir(parents=True, exist_ok=True)

    specs = _batch_specs()
    batch_id = f"visiondata-demo-seed-{seed}-dirty"
    batch_manifest = BatchManifest(
        batch_id=batch_id,
        seed=seed,
        samples=_render_batch(batch_root, specs, seed),
    )
    reserve_manifest = BatchManifest(
        batch_id=f"visiondata-demo-seed-{seed}-reserve",
        seed=seed,
        samples=_render_reserve(reserve_root, _reserve_specs(specs), seed),
    )
    corruption_manifest = _truth_manifest(seed, batch_id)

    batch_manifest_path = batch_root / "batch_manifest.json"
    reserve_manifest_path = reserve_root / "reserve_manifest.json"
    corruption_manifest_path = hidden_root / "corruption_manifest.json"
    _write_json(batch_manifest_path, batch_manifest)
    _write_json(reserve_manifest_path, reserve_manifest)
    _write_json(corruption_manifest_path, corruption_manifest)

    return {
        "output_root": root,
        "batch_root": batch_root,
        "batch_manifest": batch_manifest_path,
        "corruption_manifest": corruption_manifest_path,
        "reserve_root": reserve_root,
        "reserve_manifest": reserve_manifest_path,
    }
