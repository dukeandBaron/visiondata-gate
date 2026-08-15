"""Exact and cross-split perceptual duplicate checks."""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from pathlib import Path

import numpy as np
from PIL import Image, UnidentifiedImageError

from .contracts import BatchContract, BatchManifest, Finding, Severity
from .quality import _new_finding, _resolve_sample_path, _validated_root


TOOL_NAME = "duplicate_leakage"
_MAX_NEAR_DUPLICATE_MAE = 1.0


@dataclass(frozen=True)
class _Fingerprint:
    sample_id: str
    relative_path: str
    split: str
    file_sha256: str
    difference_hash: int
    thumbnail: np.ndarray


def _file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _perceptual_fingerprint(path: Path) -> tuple[int, np.ndarray, tuple[int, int]]:
    with Image.open(path) as image:
        image.load()
        size = image.size
        gray = image.convert("L")
        dhash_pixels = np.asarray(
            gray.resize((9, 8), resample=Image.Resampling.BILINEAR), dtype=np.uint8
        )
        thumbnail = np.asarray(
            gray.resize((16, 16), resample=Image.Resampling.BILINEAR), dtype=np.float32
        )
    bits = (dhash_pixels[:, 1:] > dhash_pixels[:, :-1]).reshape(-1)
    value = 0
    for bit in bits:
        value = (value << 1) | int(bit)
    return value, thumbnail, size


def _is_expected_decode_error(exc: Exception) -> bool:
    return isinstance(exc, (UnidentifiedImageError, SyntaxError)) or (
        isinstance(exc, OSError)
        and not isinstance(exc, (PermissionError, FileNotFoundError, IsADirectoryError))
    )


def inspect_duplicates(
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

    digest_groups: dict[str, list[tuple[str, str, str]]] = {}
    fingerprints: list[_Fingerprint] = []
    decode_skipped_count = 0

    for sample in validated_manifest.samples:
        path = _resolve_sample_path(root, sample.relative_path)
        if not path.exists():
            decode_skipped_count += 1
            continue
        if not path.is_file():
            raise IsADirectoryError(path)
        digest = _file_sha256(path)
        digest_groups.setdefault(digest, []).append(
            (sample.sample_id, sample.relative_path, sample.split)
        )
        try:
            difference_hash, thumbnail, size = _perceptual_fingerprint(path)
        except (UnidentifiedImageError, SyntaxError, OSError) as exc:
            if _is_expected_decode_error(exc):
                decode_skipped_count += 1
                continue
            raise
        if size != expected_size:
            decode_skipped_count += 1
            continue
        fingerprints.append(
            _Fingerprint(
                sample_id=sample.sample_id,
                relative_path=sample.relative_path,
                split=sample.split,
                file_sha256=digest,
                difference_hash=difference_hash,
                thumbnail=thumbnail,
            )
        )

    findings: list[Finding] = []
    exact_group_count = 0
    exact_pair_count = 0
    cross_split_exact_pair_count = 0
    for digest, raw_members in sorted(digest_groups.items()):
        if len(raw_members) < 2:
            continue
        members = sorted(raw_members, key=lambda item: item[0])
        sample_ids = [item[0] for item in members]
        splits = [item[2] for item in members]
        exact_group_count += 1
        exact_pair_count += len(members) * (len(members) - 1) // 2
        exact_evidence = {
            "sha256": digest,
            "relative_paths": [item[1] for item in members],
            "splits": splits,
        }
        findings.append(
            _new_finding(
                tool=TOOL_NAME,
                code="EXACT_DUPLICATE",
                severity=Severity.MEDIUM,
                sample_ids=sample_ids,
                summary="Multiple manifest samples have byte-identical image payloads.",
                evidence=exact_evidence,
                recommended_action="remove or repartition",
            )
        )

        cross_pairs = sum(
            1
            for left_index, left in enumerate(members)
            for right in members[left_index + 1 :]
            if left[2] != right[2]
        )
        if cross_pairs:
            cross_split_exact_pair_count += cross_pairs
            findings.append(
                _new_finding(
                    tool=TOOL_NAME,
                    code="CROSS_SPLIT_EXACT_DUPLICATE",
                    severity=Severity.CRITICAL,
                    sample_ids=sample_ids,
                    summary="Byte-identical images cross dataset split boundaries.",
                    evidence={**exact_evidence, "cross_split_pair_count": cross_pairs},
                    recommended_action="remove or repartition",
                )
            )

    compared_pair_count = 0
    cross_split_near_pair_count = 0
    ordered_fingerprints = sorted(fingerprints, key=lambda item: item.sample_id)
    for left_index, left in enumerate(ordered_fingerprints):
        for right in ordered_fingerprints[left_index + 1 :]:
            if left.split == right.split or left.file_sha256 == right.file_sha256:
                continue
            compared_pair_count += 1
            hamming = (left.difference_hash ^ right.difference_hash).bit_count()
            if hamming > active_contract.thresholds.near_duplicate_hamming:
                continue
            mean_abs_difference = float(
                np.mean(np.abs(left.thumbnail - right.thumbnail), dtype=np.float64)
            )
            if mean_abs_difference > _MAX_NEAR_DUPLICATE_MAE:
                continue
            sample_ids = sorted([left.sample_id, right.sample_id])
            member_by_id = {left.sample_id: left, right.sample_id: right}
            evidence = {
                "hamming_distance": hamming,
                "maximum_hamming": active_contract.thresholds.near_duplicate_hamming,
                "thumbnail_mean_abs_difference": round(mean_abs_difference, 6),
                "maximum_thumbnail_mean_abs_difference": _MAX_NEAR_DUPLICATE_MAE,
                "relative_paths": [
                    member_by_id[item].relative_path for item in sample_ids
                ],
                "splits": [member_by_id[item].split for item in sample_ids],
            }
            findings.append(
                _new_finding(
                    tool=TOOL_NAME,
                    code="CROSS_SPLIT_NEAR_DUPLICATE",
                    severity=Severity.HIGH,
                    sample_ids=sample_ids,
                    summary="Perceptually near-identical images cross dataset split boundaries.",
                    evidence=evidence,
                    recommended_action="remove or repartition",
                )
            )
            cross_split_near_pair_count += 1

    findings.sort(key=lambda item: (item.code, tuple(item.sample_ids), item.finding_id))
    metrics: dict[str, int | float | str] = {
        "sample_count": len(validated_manifest.samples),
        "hashed_file_count": sum(len(items) for items in digest_groups.values()),
        "perceptual_eligible_count": len(fingerprints),
        "decode_skipped_count": decode_skipped_count,
        "exact_duplicate_group_count": exact_group_count,
        "exact_duplicate_pair_count": exact_pair_count,
        "cross_split_exact_pair_count": cross_split_exact_pair_count,
        "cross_split_compared_pair_count": compared_pair_count,
        "cross_split_near_pair_count": cross_split_near_pair_count,
    }
    return findings, metrics


def run_duplicate_tool(
    batch_root: str | Path,
    manifest: BatchManifest,
    contract: BatchContract | None = None,
) -> tuple[list[Finding], dict[str, int | float | str]]:
    return inspect_duplicates(batch_root, manifest, contract)
