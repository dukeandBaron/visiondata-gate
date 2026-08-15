"""Mask presence and structural consistency checks."""

from __future__ import annotations

from pathlib import Path

import numpy as np
from PIL import Image, UnidentifiedImageError

from .contracts import BatchContract, BatchManifest, Finding, Severity
from .quality import _new_finding, _resolve_sample_path, _validated_root


TOOL_NAME = "annotation_integrity"


def _expected_decode_error(exc: Exception) -> bool:
    return isinstance(exc, (UnidentifiedImageError, SyntaxError)) or (
        isinstance(exc, OSError)
        and not isinstance(exc, (PermissionError, FileNotFoundError, IsADirectoryError))
    )


def inspect_annotations(
    batch_root: str | Path,
    manifest: BatchManifest,
    contract: BatchContract | None = None,
) -> tuple[list[Finding], dict[str, int | float | str]]:
    root = _validated_root(batch_root)
    validated_manifest = BatchManifest.model_validate(manifest.model_dump(mode="json"))
    active_contract = BatchContract.model_validate(
        (contract or BatchContract()).model_dump(mode="json")
    )
    expected_size = (
        active_contract.thresholds.expected_width,
        active_contract.thresholds.expected_height,
    )

    findings: list[Finding] = []
    checked_count = 0
    missing_count = 0
    mismatch_count = 0
    decoded_mask_count = 0
    mask_fractions: list[float] = []

    for sample in validated_manifest.samples:
        if sample.annotation_path is None:
            if not active_contract.annotations_required:
                continue
            evidence = {"reason": "manifest_path_missing"}
            findings.append(
                _new_finding(
                    tool=TOOL_NAME,
                    code="MISSING_ANNOTATION",
                    severity=Severity.HIGH,
                    sample_ids=[sample.sample_id],
                    summary=f"Required annotation path is absent for {sample.sample_id}.",
                    evidence=evidence,
                    recommended_action="relabel",
                )
            )
            missing_count += 1
            continue

        checked_count += 1
        mask_path = _resolve_sample_path(root, sample.annotation_path)
        if not mask_path.exists():
            evidence = {
                "annotation_path": sample.annotation_path,
                "reason": "missing_file",
            }
            findings.append(
                _new_finding(
                    tool=TOOL_NAME,
                    code="MISSING_ANNOTATION",
                    severity=Severity.HIGH,
                    sample_ids=[sample.sample_id],
                    summary=f"Required annotation payload is missing for {sample.sample_id}.",
                    evidence=evidence,
                    recommended_action="relabel",
                )
            )
            missing_count += 1
            continue
        if not mask_path.is_file():
            raise IsADirectoryError(mask_path)

        try:
            with Image.open(mask_path) as image:
                image.load()
                size = image.size
                mask = np.asarray(image.convert("L"), dtype=np.uint8)
        except (UnidentifiedImageError, SyntaxError, OSError) as exc:
            if not _expected_decode_error(exc):
                raise
            evidence = {
                "annotation_path": sample.annotation_path,
                "reason": "decode_error",
                "error_type": type(exc).__name__,
            }
            findings.append(
                _new_finding(
                    tool=TOOL_NAME,
                    code="MISSING_ANNOTATION",
                    severity=Severity.HIGH,
                    sample_ids=[sample.sample_id],
                    summary=f"Required annotation payload cannot be decoded for {sample.sample_id}.",
                    evidence=evidence,
                    recommended_action="relabel",
                )
            )
            missing_count += 1
            continue

        decoded_mask_count += 1
        if size != expected_size:
            evidence = {
                "annotation_path": sample.annotation_path,
                "observed_width": size[0],
                "observed_height": size[1],
                "expected_width": expected_size[0],
                "expected_height": expected_size[1],
            }
            findings.append(
                _new_finding(
                    tool=TOOL_NAME,
                    code="ANNOTATION_DIMENSION_MISMATCH",
                    severity=Severity.HIGH,
                    sample_ids=[sample.sample_id],
                    summary=f"Annotation dimensions violate the contract for {sample.sample_id}.",
                    evidence=evidence,
                    recommended_action="relabel",
                )
            )
            mismatch_count += 1
            continue

        foreground_fraction = float(np.count_nonzero(mask) / mask.size)
        mask_fractions.append(foreground_fraction)

    findings.sort(key=lambda item: (item.code, tuple(item.sample_ids), item.finding_id))
    out_of_range_count = sum(
        fraction < active_contract.thresholds.min_mask_fraction
        or fraction > active_contract.thresholds.max_mask_fraction
        for fraction in mask_fractions
    )
    metrics: dict[str, int | float | str] = {
        "sample_count": len(validated_manifest.samples),
        "annotation_path_count": checked_count,
        "decoded_mask_count": decoded_mask_count,
        "missing_annotation_count": missing_count,
        "annotation_dimension_mismatch_count": mismatch_count,
        "mask_fraction_out_of_range_count": out_of_range_count,
        "mask_fraction_min": round(min(mask_fractions), 6) if mask_fractions else 0.0,
        "mask_fraction_max": round(max(mask_fractions), 6) if mask_fractions else 0.0,
    }
    return findings, metrics


def run_annotation_tool(
    batch_root: str | Path,
    manifest: BatchManifest,
    contract: BatchContract | None = None,
) -> tuple[list[Finding], dict[str, int | float | str]]:
    return inspect_annotations(batch_root, manifest, contract)
