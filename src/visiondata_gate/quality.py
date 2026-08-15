"""Deterministic image decode, dimension, exposure, and sharpness checks."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path, PurePosixPath
from typing import Any

import numpy as np
from PIL import Image, UnidentifiedImageError

from .contracts import (
    BatchContract,
    BatchManifest,
    EvidenceStatus,
    Finding,
    Severity,
)


TOOL_NAME = "image_quality"


def _validated_root(batch_root: str | Path) -> Path:
    root = Path(batch_root).expanduser().resolve()
    if not root.exists():
        raise FileNotFoundError(root)
    if not root.is_dir():
        raise NotADirectoryError(root)
    return root


def _resolve_sample_path(root: Path, relative_path: str) -> Path:
    normalized = relative_path.replace("\\", "/")
    portable = PurePosixPath(normalized)
    if (
        not normalized
        or portable.is_absolute()
        or ".." in portable.parts
        or (portable.parts and ":" in portable.parts[0])
    ):
        raise ValueError(f"unsafe relative path: {relative_path!r}")
    candidate = root.joinpath(*portable.parts).resolve()
    try:
        candidate.relative_to(root)
    except ValueError as exc:
        raise ValueError(f"path escapes batch root: {relative_path!r}") from exc
    return candidate


def _canonical_sha256(payload: Any) -> str:
    encoded = json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _stable_finding_id(
    tool: str,
    code: str,
    sample_ids: list[str],
    evidence: dict[str, Any],
) -> str:
    digest = _canonical_sha256(
        {
            "tool": tool,
            "code": code,
            "sample_ids": sorted(sample_ids),
            "evidence": evidence,
        }
    )
    return f"{tool}-{code.lower().replace('_', '-')}-{digest[:12]}"


def _new_finding(
    *,
    code: str,
    severity: Severity,
    sample_ids: list[str],
    summary: str,
    evidence: dict[str, Any],
    recommended_action: str,
    tool: str = TOOL_NAME,
) -> Finding:
    ordered_ids = sorted(sample_ids)
    return Finding(
        finding_id=_stable_finding_id(tool, code, ordered_ids, evidence),
        code=code,
        severity=severity,
        tool=tool,
        sample_ids=ordered_ids,
        summary=summary,
        evidence=evidence,
        evidence_status=EvidenceStatus.VERIFIED,
        recommended_action=recommended_action,
    )


def _sharpness_score(gray: np.ndarray) -> float:
    values = gray.astype(np.float32, copy=False)
    if values.shape[0] < 3 or values.shape[1] < 3:
        return 0.0
    center = values[1:-1, 1:-1]
    laplacian = (
        -4.0 * center
        + values[:-2, 1:-1]
        + values[2:, 1:-1]
        + values[1:-1, :-2]
        + values[1:-1, 2:]
    )
    return float(np.var(laplacian, dtype=np.float64))


def _decode_rgb(path: Path) -> tuple[np.ndarray, tuple[int, int]]:
    with Image.open(path) as image:
        image.load()
        size = image.size
        rgb = np.asarray(image.convert("RGB"), dtype=np.uint8)
    return rgb, size


def inspect_image_quality(
    batch_root: str | Path,
    manifest: BatchManifest,
    contract: BatchContract | None = None,
) -> tuple[list[Finding], dict[str, int | float | str]]:
    """Inspect every manifest image with contract-controlled thresholds.

    Missing or malformed image payloads are expected data findings.  Unsafe
    paths, inaccessible roots, and programming/runtime errors are raised.
    """

    root = _validated_root(batch_root)
    validated_manifest = BatchManifest.model_validate(manifest.model_dump(mode="json"))
    active_contract = BatchContract.model_validate(
        (contract or BatchContract()).model_dump(mode="json")
    )
    thresholds = active_contract.thresholds
    expected_size = (thresholds.expected_width, thresholds.expected_height)

    findings: list[Finding] = []
    decoded_count = 0
    dimension_count = 0
    decode_failure_count = 0
    underexposed_count = 0
    overexposed_count = 0
    low_sharpness_count = 0
    luma_values: list[float] = []
    sharpness_values: list[float] = []

    for sample in validated_manifest.samples:
        image_path = _resolve_sample_path(root, sample.relative_path)
        if not image_path.exists():
            evidence = {"relative_path": sample.relative_path, "reason": "missing_file"}
            findings.append(
                _new_finding(
                    code="DECODE_FAILURE",
                    severity=Severity.CRITICAL,
                    sample_ids=[sample.sample_id],
                    summary=f"Image payload is missing for {sample.sample_id}.",
                    evidence=evidence,
                    recommended_action="recapture",
                )
            )
            decode_failure_count += 1
            continue
        if not image_path.is_file():
            raise IsADirectoryError(image_path)

        try:
            rgb, size = _decode_rgb(image_path)
        except (UnidentifiedImageError, SyntaxError) as exc:
            evidence = {
                "relative_path": sample.relative_path,
                "reason": "decode_error",
                "error_type": type(exc).__name__,
            }
            findings.append(
                _new_finding(
                    code="DECODE_FAILURE",
                    severity=Severity.CRITICAL,
                    sample_ids=[sample.sample_id],
                    summary=f"Image payload cannot be decoded for {sample.sample_id}.",
                    evidence=evidence,
                    recommended_action="recapture",
                )
            )
            decode_failure_count += 1
            continue
        except OSError as exc:
            if isinstance(exc, (PermissionError, FileNotFoundError, IsADirectoryError)):
                raise
            evidence = {
                "relative_path": sample.relative_path,
                "reason": "decode_error",
                "error_type": type(exc).__name__,
            }
            findings.append(
                _new_finding(
                    code="DECODE_FAILURE",
                    severity=Severity.CRITICAL,
                    sample_ids=[sample.sample_id],
                    summary=f"Image payload cannot be decoded for {sample.sample_id}.",
                    evidence=evidence,
                    recommended_action="recapture",
                )
            )
            decode_failure_count += 1
            continue

        decoded_count += 1
        if size != expected_size:
            evidence = {
                "relative_path": sample.relative_path,
                "observed_width": size[0],
                "observed_height": size[1],
                "expected_width": expected_size[0],
                "expected_height": expected_size[1],
            }
            findings.append(
                _new_finding(
                    code="INVALID_DIMENSIONS",
                    severity=Severity.HIGH,
                    sample_ids=[sample.sample_id],
                    summary=f"Image dimensions violate the contract for {sample.sample_id}.",
                    evidence=evidence,
                    recommended_action="recapture",
                )
            )
            dimension_count += 1
            # Other pixel metrics are not comparable at a non-contract size.
            continue

        luma = np.asarray(
            Image.fromarray(rgb, mode="RGB").convert("L"), dtype=np.float32
        )
        mean_luma = float(np.mean(luma, dtype=np.float64))
        sharpness = _sharpness_score(luma)
        luma_values.append(mean_luma)
        sharpness_values.append(sharpness)
        common_evidence = {
            "relative_path": sample.relative_path,
            "mean_luma": round(mean_luma, 6),
            "sharpness": round(sharpness, 6),
        }

        if mean_luma < thresholds.min_mean_luma:
            evidence = {**common_evidence, "minimum": thresholds.min_mean_luma}
            findings.append(
                _new_finding(
                    code="UNDEREXPOSED",
                    severity=Severity.HIGH,
                    sample_ids=[sample.sample_id],
                    summary=f"Mean luminance is below the contract for {sample.sample_id}.",
                    evidence=evidence,
                    recommended_action="recapture",
                )
            )
            underexposed_count += 1
        elif mean_luma > thresholds.max_mean_luma:
            evidence = {**common_evidence, "maximum": thresholds.max_mean_luma}
            findings.append(
                _new_finding(
                    code="OVEREXPOSED",
                    severity=Severity.HIGH,
                    sample_ids=[sample.sample_id],
                    summary=f"Mean luminance is above the contract for {sample.sample_id}.",
                    evidence=evidence,
                    recommended_action="recapture",
                )
            )
            overexposed_count += 1
        elif sharpness < thresholds.min_sharpness:
            evidence = {**common_evidence, "minimum": thresholds.min_sharpness}
            findings.append(
                _new_finding(
                    code="LOW_SHARPNESS",
                    severity=Severity.HIGH,
                    sample_ids=[sample.sample_id],
                    summary=f"Sharpness is below the contract for {sample.sample_id}.",
                    evidence=evidence,
                    recommended_action="recapture",
                )
            )
            low_sharpness_count += 1

    findings.sort(key=lambda item: (item.code, tuple(item.sample_ids), item.finding_id))
    metrics: dict[str, int | float | str] = {
        "sample_count": len(validated_manifest.samples),
        "decoded_image_count": decoded_count,
        "decode_failure_count": decode_failure_count,
        "invalid_dimension_count": dimension_count,
        "underexposed_count": underexposed_count,
        "overexposed_count": overexposed_count,
        "low_sharpness_count": low_sharpness_count,
        "mean_luma_min": round(min(luma_values), 6) if luma_values else 0.0,
        "mean_luma_max": round(max(luma_values), 6) if luma_values else 0.0,
        "sharpness_min": round(min(sharpness_values), 6) if sharpness_values else 0.0,
        "sharpness_max": round(max(sharpness_values), 6) if sharpness_values else 0.0,
    }
    return findings, metrics


def run_quality_tool(
    batch_root: str | Path,
    manifest: BatchManifest,
    contract: BatchContract | None = None,
) -> tuple[list[Finding], dict[str, int | float | str]]:
    """Stable public alias used by the whitelist orchestrator."""

    return inspect_image_quality(batch_root, manifest, contract)
