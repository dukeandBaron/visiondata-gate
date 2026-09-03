#!/usr/bin/env python3
"""Build a deterministic, privacy-bounded GOAI semifinal Defense Kit.

This package binds presentation materials and a public source snapshot to the
current clean Git commit.  It is an attachment-integrity receipt, not a release
attestation or proof of official submission.
"""

from __future__ import annotations

import argparse
import hashlib
import io
import json
import os
import re
import stat
import subprocess
import sys
import tempfile
import zipfile
from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from urllib.parse import urlsplit
from xml.etree import ElementTree

SCHEMA = "visiondata-gate.goai-semifinal-defense-kit.v1"
RECEIPT_SCHEMA = "visiondata-gate.goai-semifinal-defense-kit-receipt.v1"
FIXED_ZIP_TIME = (2026, 9, 2, 0, 0, 0)
MAX_FILE_BYTES = 128 * 1024 * 1024
MAX_TOTAL_BYTES = 768 * 1024 * 1024
MAX_PUBLIC_SOURCE_ENTRIES = 20_000
MAX_PUBLIC_SOURCE_BYTES = 256 * 1024 * 1024
MAX_CONTAINER_ENTRIES = 8_192
MAX_CONTAINER_ENTRY_BYTES = 96 * 1024 * 1024
MAX_CONTAINER_TOTAL_BYTES = 512 * 1024 * 1024
MAX_CONTAINER_COMPRESSION_RATIO = 250
PUBLIC_MANIFEST_NAME = "PUBLIC_MIRROR_MANIFEST.json"
PUBLIC_MANIFEST_SCHEMA = "visiondata-gate.public-mirror.v2"
PUBLIC_MANIFEST_FIELDS = {
    "schema_version",
    "source_commit_oid",
    "source_tree_oid",
    "source_worktree_clean",
    "source_history_included",
    "private_release_evidence_included",
    "customer_data_included",
    "personal_data_included",
    "tracked_source_only",
    "file_count",
    "snapshot_sha256",
    "files",
}
PPTX_REQUIRED_MEMBERS = {
    "[content_types].xml",
    "_rels/.rels",
    "ppt/presentation.xml",
}
PPTX_FORBIDDEN_PREFIXES = (
    "_xmlsignatures/",
    "customui/",
    "customxml/",
    "ppt/activex/",
    "ppt/embeddings/",
    "ppt/externallinks/",
)
PPTX_FORBIDDEN_MEMBERS = {
    "ppt/vbaproject.bin",
    "vbaproject.bin",
}
RELATIONSHIP_TAG = (
    "{http://schemas.openxmlformats.org/package/2006/relationships}Relationship"
)

FIXED_MATERIALS = {
    "presentation/GOAI_VisionDataGate_Semifinal_Defense_RC4_20260902.pptx": (
        "presentation_pptx",
        "deliverables/GOAI_VisionDataGate_Semifinal_Defense_RC4_20260902.pptx",
    ),
    "presentation/GOAI_VisionDataGate_Semifinal_Defense_RC4_20260902.pdf": (
        "presentation_pdf",
        "deliverables/GOAI_VisionDataGate_Semifinal_Defense_RC4_20260902.pdf",
    ),
    "demo/VisionDataGate_GOAI_Semifinal_60s_RC4_20260902.mp4": (
        "demo_video",
        "deliverables/VisionDataGate_GOAI_Semifinal_60s_RC4_20260902.mp4",
    ),
    "demo/VisionDataGate_GOAI_Semifinal_60s_RC4_20260902.receipt.json": (
        "demo_video_receipt",
        "deliverables/VisionDataGate_GOAI_Semifinal_60s_RC4_20260902.receipt.json",
    ),
    "demo/frames/01-public-home.png": (
        "demo_fallback_frame",
        "deliverables/semifinal_rc4_frames/01-public-home.png",
    ),
    "demo/frames/02-command-center.png": (
        "demo_fallback_frame",
        "deliverables/semifinal_rc4_frames/02-command-center.png",
    ),
    "demo/frames/03-case-workbench.png": (
        "demo_fallback_frame",
        "deliverables/semifinal_rc4_frames/03-case-workbench.png",
    ),
    "demo/frames/04-capa-lineage.png": (
        "demo_fallback_frame",
        "deliverables/semifinal_rc4_frames/04-capa-lineage.png",
    ),
    "demo/frames/05-runs-recheck.png": (
        "demo_fallback_frame",
        "deliverables/semifinal_rc4_frames/05-runs-recheck.png",
    ),
    "demo/frames/06-governance-boundary.png": (
        "demo_fallback_frame",
        "deliverables/semifinal_rc4_frames/06-governance-boundary.png",
    ),
    "defense/GOAI_SEMIFINAL_GUIDE_20260902.md": (
        "official_guide_summary",
        "docs/GOAI_SEMIFINAL_GUIDE_20260902.md",
    ),
    "defense/DEMO_60S_SCRIPT_SEMIFINAL.md": (
        "demo_script",
        "docs/DEMO_60S_SCRIPT_SEMIFINAL.md",
    ),
    "defense/DEFENSE_3MIN_SCRIPT_SEMIFINAL.md": (
        "defense_script",
        "docs/DEFENSE_3MIN_SCRIPT_SEMIFINAL.md",
    ),
    "defense/DEFENSE_QA_SEMIFINAL.md": (
        "defense_qa",
        "docs/DEFENSE_QA_SEMIFINAL.md",
    ),
    "defense/SEMIFINAL_DEFENSE_RUNBOOK_20260902.md": (
        "defense_runbook",
        "docs/SEMIFINAL_DEFENSE_RUNBOOK_20260902.md",
    ),
    "defense/DATA_SOURCE_AND_COMPLIANCE_SEMIFINAL_RC3.md": (
        "data_compliance",
        "docs/DATA_SOURCE_AND_COMPLIANCE_SEMIFINAL_RC3.md",
    ),
    "defense/SEMIFINAL_ATTACHMENT_MANIFEST.md": (
        "attachment_boundary",
        "docs/SEMIFINAL_ATTACHMENT_MANIFEST.md",
    ),
}

TEXT_SUFFIXES = {
    ".css",
    ".csv",
    ".html",
    ".ini",
    ".js",
    ".json",
    ".jsonl",
    ".lock",
    ".md",
    ".mjs",
    ".ps1",
    ".py",
    ".rst",
    ".toml",
    ".ts",
    ".tsx",
    ".txt",
    ".yaml",
    ".yml",
}

SECRET_PATTERNS = (
    re.compile(rb"(?i)\bsk-[a-z0-9_-]{16,}\b"),
    re.compile(
        rb"(?i)\b(?:api[_-]?key|access[_-]?token|secret)\s*[:=]\s*['\"]?[a-z0-9_./+-]{20,}"
    ),
)
PRIVATE_PATH_PATTERNS = (
    re.compile(rb"(?i)[a-z]:[\\/]+users[\\/]+[^\\/\s]+"),
    re.compile(
        rb"(?i)[a-z]:[\\/]+(?:goal|blender_render|codex_competitions)(?:[\\/]|\b)"
    ),
    re.compile(rb"(?i)/(?:home|users)/[^/\s]+/"),
)


class DefenseKitError(RuntimeError):
    """Fail-closed error that exposes only a stable, non-sensitive code."""

    def __init__(self, code: str):
        if re.fullmatch(r"[a-z0-9_]{3,96}", code) is None:
            raise ValueError("defense kit error code must be a stable identifier")
        self.code = code
        super().__init__(code)


@dataclass(frozen=True)
class Material:
    archive_path: str
    role: str
    data: bytes

    @property
    def sha256(self) -> str:
        return hashlib.sha256(self.data).hexdigest()

    def record(self) -> dict[str, str | int]:
        return {
            "path": self.archive_path,
            "role": self.role,
            "size_bytes": len(self.data),
            "sha256": self.sha256,
        }


def _canonical_json(value: object) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")


def _safe_archive_path(value: str) -> str:
    if (
        not value
        or "\\" in value
        or value.startswith("/")
        or value.endswith("/")
        or any(ord(character) < 32 for character in value)
    ):
        raise DefenseKitError("archive_path_rejected")
    raw_parts = value.split("/")
    if any(part in {"", ".", ".."} for part in raw_parts):
        raise DefenseKitError("archive_path_rejected")
    path = PurePosixPath(value)
    if (
        path.is_absolute()
        or any(":" in part for part in path.parts)
        or path.as_posix() != value
    ):
        raise DefenseKitError("archive_path_rejected")
    return path.as_posix()


def _reject_sensitive_path(value: str, *, allow_env_example: bool = False) -> None:
    normalized = _safe_archive_path(value)
    parts = PurePosixPath(normalized).parts
    last_index = len(parts) - 1
    for index, part in enumerate(parts):
        folded = part.casefold()
        if (folded == ".env" or folded.startswith(".env.")) and not (
            allow_env_example and folded == ".env.example" and index == last_index
        ):
            raise DefenseKitError("environment_path_rejected")
    if any(part.casefold() in {".git", "id_rsa", "id_ed25519"} for part in parts):
        raise DefenseKitError("sensitive_path_rejected")


def _privacy_scan(data: bytes, *, label: str) -> None:
    del label
    for pattern in (*SECRET_PATTERNS, *PRIVATE_PATH_PATTERNS):
        if pattern.search(data):
            raise DefenseKitError("privacy_scan_failed")


def _validate_external_relationships(data: bytes) -> None:
    try:
        root = ElementTree.fromstring(data)
    except ElementTree.ParseError as exc:
        raise DefenseKitError("pptx_relationships_invalid") from exc
    for relationship in root.iter(RELATIONSHIP_TAG):
        if relationship.get("TargetMode", "").casefold() != "external":
            continue
        target = relationship.get("Target", "").strip()
        parsed = urlsplit(target)
        if parsed.scheme.casefold() not in {"http", "https"} or not parsed.netloc:
            raise DefenseKitError("pptx_external_relationship_rejected")


def _container_member_name(info: zipfile.ZipInfo) -> str:
    raw = info.filename
    if info.is_dir():
        if not raw.endswith("/"):
            raise DefenseKitError("container_member_path_rejected")
        raw = raw[:-1]
    try:
        return _safe_archive_path(raw)
    except DefenseKitError as exc:
        raise DefenseKitError("container_member_path_rejected") from exc


def _scan_container(path: Path, data: bytes) -> None:
    suffix = path.suffix.casefold()
    if suffix not in {".pptx", ".zip"}:
        return
    try:
        with zipfile.ZipFile(io.BytesIO(data), mode="r") as archive:
            infos = archive.infolist()
            if not infos or len(infos) > MAX_CONTAINER_ENTRIES:
                raise DefenseKitError("container_entry_count_rejected")
            seen: set[str] = set()
            observed_members: set[str] = set()
            total_uncompressed = 0
            for info in infos:
                normalized = _container_member_name(info)
                folded = normalized.casefold()
                if folded in seen:
                    raise DefenseKitError("container_member_collision")
                seen.add(folded)
                observed_members.add(folded)
                _reject_sensitive_path(normalized)
                mode = (info.external_attr >> 16) & 0xFFFF
                file_type = stat.S_IFMT(mode)
                if info.flag_bits & 0x1:
                    raise DefenseKitError("container_encrypted_member_rejected")
                if info.is_dir():
                    if file_type and not stat.S_ISDIR(mode):
                        raise DefenseKitError("container_member_type_rejected")
                    continue
                if file_type and not stat.S_ISREG(mode):
                    raise DefenseKitError("container_member_type_rejected")
                if info.compress_type not in {zipfile.ZIP_STORED, zipfile.ZIP_DEFLATED}:
                    raise DefenseKitError("container_compression_rejected")
                if info.file_size <= 0 or info.file_size > MAX_CONTAINER_ENTRY_BYTES:
                    raise DefenseKitError("container_member_size_rejected")
                total_uncompressed += info.file_size
                if total_uncompressed > MAX_CONTAINER_TOTAL_BYTES:
                    raise DefenseKitError("container_total_size_rejected")
                if (
                    info.file_size >= 4 * 1024 * 1024
                    and info.compress_size > 0
                    and info.file_size // info.compress_size
                    > MAX_CONTAINER_COMPRESSION_RATIO
                ):
                    raise DefenseKitError("container_compression_ratio_rejected")
                if suffix == ".pptx" and (
                    folded in PPTX_FORBIDDEN_MEMBERS
                    or any(
                        folded.startswith(prefix) for prefix in PPTX_FORBIDDEN_PREFIXES
                    )
                ):
                    raise DefenseKitError("pptx_active_content_rejected")
                member_data = archive.read(info)
                if len(member_data) != info.file_size:
                    raise DefenseKitError("container_member_size_drift")
                _privacy_scan(member_data, label=normalized)
                if suffix == ".pptx" and folded == "[content_types].xml":
                    lowered_content_types = member_data.lower()
                    if any(
                        marker in lowered_content_types
                        for marker in (
                            b"activex",
                            b"macroenabled",
                            b"oleobject",
                            b"vbaproject",
                        )
                    ):
                        raise DefenseKitError("pptx_active_content_rejected")
                if suffix == ".pptx" and folded.endswith(".rels"):
                    _validate_external_relationships(member_data)
            if suffix == ".pptx" and not PPTX_REQUIRED_MEMBERS.issubset(
                observed_members
            ):
                raise DefenseKitError("pptx_required_members_missing")
    except DefenseKitError:
        raise
    except (OSError, RuntimeError, NotImplementedError, zipfile.BadZipFile) as exc:
        raise DefenseKitError("container_invalid") from exc


def _run_git(root: Path, *args: str) -> str:
    try:
        result = subprocess.run(
            ["git", "--no-replace-objects", *args],
            cwd=root,
            check=False,
            capture_output=True,
            timeout=30,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise DefenseKitError("git_validation_failed") from exc
    if result.returncode != 0:
        raise DefenseKitError("git_validation_failed")
    try:
        return result.stdout.decode("utf-8").strip()
    except UnicodeDecodeError as exc:
        raise DefenseKitError("git_output_invalid") from exc


def _git_identity(root: Path) -> tuple[str, str]:
    if _run_git(root, "status", "--porcelain", "--untracked-files=all"):
        raise DefenseKitError("source_worktree_not_clean")
    return _run_git(root, "rev-parse", "HEAD"), _run_git(
        root, "rev-parse", "HEAD^{tree}"
    )


def _is_redirecting(path: Path) -> bool:
    try:
        if path.is_symlink():
            return True
        junction = getattr(path, "is_junction", None)
        return bool(junction is not None and junction())
    except OSError:
        return True


def _absolute_without_resolving(path: Path) -> Path:
    return Path(os.path.abspath(os.fspath(path.expanduser())))


def _reject_redirecting_components(path: Path) -> None:
    absolute = _absolute_without_resolving(path)
    parts = absolute.parts
    if not parts:
        raise DefenseKitError("filesystem_path_rejected")
    current = Path(parts[0])
    if current.exists() and _is_redirecting(current):
        raise DefenseKitError("filesystem_redirect_rejected")
    for part in parts[1:]:
        current /= part
        if not current.exists():
            break
        if _is_redirecting(current):
            raise DefenseKitError("filesystem_redirect_rejected")


def _regular_file_under(root: Path, candidate: Path) -> Path:
    _reject_redirecting_components(candidate)
    try:
        resolved = candidate.resolve(strict=True)
        resolved.relative_to(root)
    except (OSError, RuntimeError, ValueError) as exc:
        raise DefenseKitError("material_path_rejected") from exc
    if not resolved.is_file():
        raise DefenseKitError("material_not_regular_file")
    return resolved


def _require_tracked(root: Path, relative: str) -> Path:
    stage = _run_git(root, "ls-files", "--stage", "--error-unmatch", "--", relative)
    mode = stage.split(maxsplit=1)[0] if stage else ""
    if mode not in {"100644", "100755"}:
        raise DefenseKitError("tracked_material_mode_rejected")
    candidate = root.joinpath(*PurePosixPath(relative).parts)
    return _regular_file_under(root, candidate)


def _read_bounded_file(path: Path, *, maximum: int, allow_empty: bool = False) -> bytes:
    try:
        with path.open("rb") as handle:
            data = handle.read(maximum + 1)
    except OSError as exc:
        raise DefenseKitError("file_read_failed") from exc
    if len(data) > maximum or (not data and not allow_empty):
        raise DefenseKitError("file_size_rejected")
    return data


def _read_material(root: Path, archive_path: str, role: str, relative: str) -> Material:
    _reject_sensitive_path(archive_path)
    path = _require_tracked(root, relative)
    data = _read_bounded_file(path, maximum=MAX_FILE_BYTES)
    _privacy_scan(data, label=relative)
    _scan_container(path, data)
    return Material(archive_path=archive_path, role=role, data=data)


def _resolve_snapshot_root(public_snapshot: Path) -> Path:
    _reject_redirecting_components(public_snapshot)
    try:
        snapshot = public_snapshot.expanduser().resolve(strict=True)
    except (OSError, RuntimeError) as exc:
        raise DefenseKitError("public_snapshot_path_rejected") from exc
    if not snapshot.is_dir():
        raise DefenseKitError("public_snapshot_path_rejected")
    return snapshot


def _snapshot_files(snapshot: Path) -> list[Path]:
    pending = [snapshot]
    files: list[Path] = []
    while pending:
        directory = pending.pop()
        try:
            entries = sorted(directory.iterdir(), key=lambda item: item.name.casefold())
        except OSError as exc:
            raise DefenseKitError("public_snapshot_enumeration_failed") from exc
        child_directories: list[Path] = []
        for path in entries:
            if _is_redirecting(path):
                raise DefenseKitError("public_snapshot_redirect_rejected")
            try:
                resolved = path.resolve(strict=True)
                resolved.relative_to(snapshot)
            except (OSError, RuntimeError, ValueError) as exc:
                raise DefenseKitError("public_snapshot_path_rejected") from exc
            if path.is_dir():
                child_directories.append(path)
            elif path.is_file():
                files.append(path)
            else:
                raise DefenseKitError("public_snapshot_entry_type_rejected")
        pending.extend(reversed(child_directories))
    if not files or len(files) > MAX_PUBLIC_SOURCE_ENTRIES + 1:
        raise DefenseKitError("public_snapshot_entry_count_rejected")
    return sorted(files, key=lambda item: item.relative_to(snapshot).as_posix())


def _unique_json(data: bytes) -> object:
    def reject_duplicates(pairs: list[tuple[str, object]]) -> dict[str, object]:
        value: dict[str, object] = {}
        for key, item in pairs:
            if key in value:
                raise DefenseKitError("public_snapshot_manifest_duplicate_key")
            value[key] = item
        return value

    try:
        return json.loads(data.decode("utf-8"), object_pairs_hook=reject_duplicates)
    except DefenseKitError:
        raise
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise DefenseKitError("public_snapshot_manifest_invalid") from exc


def _validate_public_snapshot_with_checker(root: Path, snapshot: Path) -> None:
    checker = root / "tools" / "check_public_repository.py"
    if not checker.is_file():
        raise DefenseKitError("public_snapshot_checker_missing")
    environment = os.environ.copy()
    environment["PYTHONDONTWRITEBYTECODE"] = "1"
    try:
        result = subprocess.run(
            [sys.executable, str(checker), "--snapshot-root", str(snapshot)],
            cwd=root,
            capture_output=True,
            env=environment,
            check=False,
            timeout=180,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise DefenseKitError("public_snapshot_validation_failed") from exc
    if result.returncode != 0:
        raise DefenseKitError("public_snapshot_validation_failed")


def _read_snapshot_bytes(snapshot: Path) -> dict[str, bytes]:
    values: dict[str, bytes] = {}
    total = 0
    for path in _snapshot_files(snapshot):
        relative = path.relative_to(snapshot).as_posix()
        _reject_sensitive_path(
            f"source/{relative}",
            allow_env_example=True,
        )
        data = _read_bounded_file(path, maximum=MAX_FILE_BYTES)
        total += len(data)
        if total > MAX_PUBLIC_SOURCE_BYTES:
            raise DefenseKitError("public_snapshot_total_size_rejected")
        # Public source content is governed by the repository checker invoked in
        # _public_snapshot_materials.  Reapplying the generic attachment regexes
        # here would reject reviewed detector fixtures and placeholder topology
        # examples that the context-aware checker intentionally classifies.
        values[relative] = data
    return values


def _validate_public_manifest(
    manifest_data: bytes,
    files: dict[str, bytes],
    *,
    commit: str,
    tree: str,
) -> tuple[dict[str, object], str]:
    parsed = _unique_json(manifest_data)
    if not isinstance(parsed, dict) or set(parsed) != PUBLIC_MANIFEST_FIELDS:
        raise DefenseKitError("public_snapshot_manifest_field_drift")
    manifest = parsed
    if (
        manifest.get("schema_version") != PUBLIC_MANIFEST_SCHEMA
        or manifest.get("source_commit_oid") != commit
        or manifest.get("source_tree_oid") != tree
        or manifest.get("source_worktree_clean") is not True
        or manifest.get("source_history_included") is not False
        or manifest.get("private_release_evidence_included") is not False
        or manifest.get("customer_data_included") is not False
        or manifest.get("personal_data_included") is not False
        or manifest.get("tracked_source_only") is not True
    ):
        raise DefenseKitError("public_snapshot_manifest_boundary_drift")
    entries = manifest.get("files")
    file_count = manifest.get("file_count")
    if (
        not isinstance(entries, list)
        or not isinstance(file_count, int)
        or isinstance(file_count, bool)
        or file_count != len(entries)
    ):
        raise DefenseKitError("public_snapshot_manifest_count_drift")

    observed_paths: list[str] = []
    seen: set[str] = set()
    digest = hashlib.sha256()
    for entry in entries:
        if (
            not isinstance(entry, dict)
            or not {"path", "sha256", "size_bytes"}.issubset(entry)
            or set(entry).difference({"path", "sha256", "size_bytes", "source"})
        ):
            raise DefenseKitError("public_snapshot_manifest_entry_invalid")
        relative = entry.get("path")
        sha256 = entry.get("sha256")
        size = entry.get("size_bytes")
        if not isinstance(relative, str):
            raise DefenseKitError("public_snapshot_manifest_entry_invalid")
        _reject_sensitive_path(f"source/{relative}", allow_env_example=True)
        folded = relative.casefold()
        if folded in seen or relative == PUBLIC_MANIFEST_NAME:
            raise DefenseKitError("public_snapshot_manifest_path_collision")
        seen.add(folded)
        if (
            not isinstance(sha256, str)
            or re.fullmatch(r"[0-9a-f]{64}", sha256) is None
            or not isinstance(size, int)
            or isinstance(size, bool)
            or size <= 0
        ):
            raise DefenseKitError("public_snapshot_manifest_entry_invalid")
        data = files.get(relative)
        if data is None:
            raise DefenseKitError("public_snapshot_file_set_drift")
        observed_sha = hashlib.sha256(data).hexdigest()
        if len(data) != size:
            raise DefenseKitError("public_snapshot_file_size_mismatch")
        if observed_sha != sha256:
            raise DefenseKitError("public_snapshot_file_hash_mismatch")
        observed_paths.append(relative)
        digest.update(relative.encode("utf-8"))
        digest.update(b"\0")
        digest.update(observed_sha.encode("ascii"))
        digest.update(b"\0")
    if observed_paths != sorted(observed_paths):
        raise DefenseKitError("public_snapshot_manifest_order_drift")
    expected_files = set(observed_paths) | {PUBLIC_MANIFEST_NAME}
    if set(files) != expected_files:
        raise DefenseKitError("public_snapshot_file_set_drift")
    snapshot_sha256 = manifest.get("snapshot_sha256")
    if (
        not isinstance(snapshot_sha256, str)
        or re.fullmatch(r"[0-9a-f]{64}", snapshot_sha256) is None
        or snapshot_sha256 != digest.hexdigest()
    ):
        raise DefenseKitError("public_snapshot_digest_mismatch")
    return manifest, snapshot_sha256


def _public_snapshot_materials(
    root: Path,
    public_snapshot: Path,
    *,
    commit: str,
    tree: str,
) -> tuple[list[Material], str]:
    snapshot = _resolve_snapshot_root(public_snapshot)
    first_read = _read_snapshot_bytes(snapshot)
    manifest_data = first_read.get(PUBLIC_MANIFEST_NAME)
    if manifest_data is None:
        raise DefenseKitError("public_snapshot_manifest_missing")
    _, snapshot_sha256 = _validate_public_manifest(
        manifest_data,
        first_read,
        commit=commit,
        tree=tree,
    )
    _validate_public_snapshot_with_checker(root, snapshot)
    if _read_snapshot_bytes(snapshot) != first_read:
        raise DefenseKitError("public_snapshot_drift_during_validation")
    materials = [
        Material(f"source/{relative}", "public_source", data)
        for relative, data in sorted(first_read.items())
    ]
    return materials, snapshot_sha256


def _zip_info(name: str) -> zipfile.ZipInfo:
    info = zipfile.ZipInfo(_safe_archive_path(name), date_time=FIXED_ZIP_TIME)
    info.compress_type = zipfile.ZIP_DEFLATED
    info.external_attr = (stat.S_IFREG | 0o644) << 16
    info.create_system = 3
    return info


def _checksum_bytes(materials: Iterable[Material]) -> bytes:
    lines = [f"{item.sha256}  {item.archive_path}\n" for item in materials]
    return "".join(sorted(lines)).encode("utf-8")


def _resolve_new_output(root: Path, value: Path, *, suffix: str) -> Path:
    candidate = _absolute_without_resolving(value)
    _reject_redirecting_components(candidate.parent)
    try:
        resolved = candidate.resolve(strict=False)
        resolved.relative_to(root)
    except (OSError, RuntimeError, ValueError) as exc:
        raise DefenseKitError("output_path_rejected") from exc
    if resolved.suffix.casefold() != suffix or resolved.exists():
        raise DefenseKitError("output_path_rejected")
    return resolved


def _is_git_ignored(root: Path, path: Path) -> bool:
    relative = path.relative_to(root).as_posix()
    try:
        result = subprocess.run(
            [
                "git",
                "--no-replace-objects",
                "check-ignore",
                "--no-index",
                "-q",
                "--",
                relative,
            ],
            cwd=root,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            check=False,
            timeout=30,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise DefenseKitError("git_ignore_validation_failed") from exc
    if result.returncode not in {0, 1}:
        raise DefenseKitError("git_ignore_validation_failed")
    return result.returncode == 0


def _temporary_file(parent: Path, *, prefix: str) -> Path:
    path: Path | None = None
    descriptor: int | None = None
    try:
        descriptor, name = tempfile.mkstemp(
            prefix=prefix,
            suffix=".tmp",
            dir=parent,
        )
        path = Path(name)
        os.close(descriptor)
        descriptor = None
        path.chmod(0o644)
        return path
    except OSError as exc:
        if descriptor is not None:
            try:
                os.close(descriptor)
            except OSError:
                pass
        if path is not None:
            try:
                path.unlink(missing_ok=True)
            except OSError:
                pass
        raise DefenseKitError("temporary_output_failed") from exc


def _publish_no_replace(staging: Path, destination: Path) -> None:
    try:
        os.link(staging, destination)
    except FileExistsError as exc:
        raise DefenseKitError("output_already_exists") from exc
    except OSError as exc:
        raise DefenseKitError("output_publish_failed") from exc
    try:
        staging.unlink()
    except OSError as exc:
        try:
            destination.unlink(missing_ok=True)
        except OSError:
            pass
        raise DefenseKitError("output_publish_failed") from exc


def _verify_archive(path: Path, materials: list[Material]) -> bytes:
    expected = {item.archive_path: item.sha256 for item in materials}
    expected_casefold = {name.casefold() for name in expected}
    if len(expected_casefold) != len(expected):
        raise DefenseKitError("archive_expected_path_collision")
    try:
        with zipfile.ZipFile(path, mode="r") as archive:
            infos = archive.infolist()
            if len(infos) != len(expected):
                raise DefenseKitError("archive_entry_set_drift")
            observed: dict[str, str] = {}
            seen: set[str] = set()
            for info in infos:
                if info.is_dir():
                    raise DefenseKitError("archive_entry_set_drift")
                normalized = _container_member_name(info)
                folded = normalized.casefold()
                if folded in seen:
                    raise DefenseKitError("archive_path_collision")
                seen.add(folded)
                mode = (info.external_attr >> 16) & 0xFFFF
                if (
                    info.date_time != FIXED_ZIP_TIME
                    or info.compress_type != zipfile.ZIP_DEFLATED
                    or info.flag_bits & 0x1
                    or (mode and not stat.S_ISREG(mode))
                ):
                    raise DefenseKitError("archive_metadata_drift")
                observed[normalized] = hashlib.sha256(archive.read(info)).hexdigest()
    except DefenseKitError:
        raise
    except (OSError, RuntimeError, NotImplementedError, zipfile.BadZipFile) as exc:
        raise DefenseKitError("archive_verification_failed") from exc
    if observed != expected:
        raise DefenseKitError("archive_content_drift")
    return _read_bounded_file(path, maximum=MAX_TOTAL_BYTES + 32 * 1024 * 1024)


def build(
    *,
    root: Path,
    public_snapshot: Path,
    output_zip: Path,
    receipt_path: Path,
) -> dict[str, object]:
    try:
        root = root.resolve(strict=True)
    except (OSError, RuntimeError) as exc:
        raise DefenseKitError("project_root_rejected") from exc
    if not root.is_dir():
        raise DefenseKitError("project_root_rejected")
    raw_output_zip = _absolute_without_resolving(output_zip)
    raw_receipt_path = _absolute_without_resolving(receipt_path)
    if os.path.normcase(os.fspath(raw_output_zip)) == os.path.normcase(
        os.fspath(raw_receipt_path)
    ):
        raise DefenseKitError("output_paths_conflict")
    output_zip = _resolve_new_output(root, raw_output_zip, suffix=".zip")
    receipt_path = _resolve_new_output(root, raw_receipt_path, suffix=".json")
    snapshot = _resolve_snapshot_root(public_snapshot)
    if snapshot in output_zip.parents or snapshot in receipt_path.parents:
        raise DefenseKitError("output_snapshot_overlap")

    commit, tree = _git_identity(root)
    if not _is_git_ignored(root, output_zip) or not _is_git_ignored(root, receipt_path):
        raise DefenseKitError("output_not_git_ignored")
    materials = [
        _read_material(root, archive_path, role, relative)
        for archive_path, (role, relative) in FIXED_MATERIALS.items()
    ]
    source_materials, snapshot_sha256 = _public_snapshot_materials(
        root,
        snapshot,
        commit=commit,
        tree=tree,
    )
    materials.extend(source_materials)

    readme = (
        "VisionData Gate - GOAI 2026 Semifinal RC4 Defense Kit\n"
        "This package is a privacy-bounded defense attachment, not proof of "
        "official submission or production release.\n"
        f"source_commit={commit}\nsource_tree={tree}\n"
        "official_submission=PENDING\nofficial_evaluation=NOT_EVALUATED\n"
        "production_release_allowed=false\nmachine_write_permitted=false\n"
        "authority=human_only\n"
    ).encode()
    materials.append(Material("README.txt", "package_readme", readme))
    materials.sort(key=lambda item: item.archive_path)

    if len({item.archive_path.casefold() for item in materials}) != len(materials):
        raise DefenseKitError("archive_path_collision")
    total_bytes = sum(len(item.data) for item in materials)
    if total_bytes > MAX_TOTAL_BYTES:
        raise DefenseKitError("package_size_rejected")

    manifest = {
        "schema_version": SCHEMA,
        "kind": "RC4_DEFENSE_KIT_ATTACHMENT_INTEGRITY",
        "source": {"commit": commit, "tree": tree, "worktree_clean": True},
        "public_snapshot": {
            "snapshot_sha256": snapshot_sha256,
            "attestation": "NOT_ISSUED",
        },
        "frozen_rc3_baseline": {
            "decision": "PASS_LOCAL_RC3_RELEASE_CANDIDATE",
            "commit": "c5fd68fc38025ffab4345cd739e611c96b13c530",
            "tree": "5501787b6ed452759af16e60dca76ce0c2ec54bf",
        },
        "official_submission": "PENDING",
        "official_evaluation": "NOT_EVALUATED",
        "production_release_allowed": False,
        "machine_write_permitted": False,
        "authority": "human_only",
        "factory_shadow_metrics": "NOT_MEASURED_PENDING_ADJUDICATION",
        "materials": [item.record() for item in materials],
    }
    manifest_material = Material(
        "DEFENSE_KIT_MANIFEST.json",
        "defense_kit_manifest",
        _canonical_json(manifest),
    )
    checksummed = [*materials, manifest_material]
    checksum_material = Material(
        "SHA256SUMS.txt",
        "checksums",
        _checksum_bytes(checksummed),
    )
    archive_materials = sorted(
        [*checksummed, checksum_material], key=lambda item: item.archive_path
    )

    try:
        output_zip.parent.mkdir(parents=True, exist_ok=True)
        receipt_path.parent.mkdir(parents=True, exist_ok=True)
    except OSError as exc:
        raise DefenseKitError("output_directory_failed") from exc

    temporary_zip: Path | None = None
    temporary_receipt: Path | None = None
    published_zip = False
    published_receipt = False
    try:
        temporary_zip = _temporary_file(
            output_zip.parent,
            prefix=f".{output_zip.name}.",
        )
        temporary_receipt = _temporary_file(
            receipt_path.parent,
            prefix=f".{receipt_path.name}.",
        )
        try:
            with zipfile.ZipFile(
                temporary_zip,
                "w",
                compression=zipfile.ZIP_DEFLATED,
                compresslevel=9,
            ) as archive:
                for item in archive_materials:
                    archive.writestr(_zip_info(item.archive_path), item.data)
        except (OSError, RuntimeError, NotImplementedError, zipfile.BadZipFile) as exc:
            raise DefenseKitError("archive_write_failed") from exc

        zip_bytes = _verify_archive(temporary_zip, archive_materials)
        if _git_identity(root) != (commit, tree):
            raise DefenseKitError("source_drift_during_assembly")
        receipt = {
            "schema_version": RECEIPT_SCHEMA,
            "status": "PASS_LOCAL_RC4_DEFENSE_KIT_INTEGRITY",
            "source_commit": commit,
            "source_tree": tree,
            "zip_filename": output_zip.name,
            "zip_size_bytes": len(zip_bytes),
            "zip_sha256": hashlib.sha256(zip_bytes).hexdigest(),
            "entry_count": len(archive_materials),
            "public_snapshot_sha256": snapshot_sha256,
            "official_submission": "PENDING",
            "official_evaluation": "NOT_EVALUATED",
            "production_release_allowed": False,
            "machine_write_permitted": False,
            "authority": "human_only",
        }
        receipt_bytes = _canonical_json(receipt) + b"\n"
        try:
            temporary_receipt.write_bytes(receipt_bytes)
            observed_receipt_bytes = temporary_receipt.read_bytes()
        except OSError as exc:
            raise DefenseKitError("receipt_write_failed") from exc
        if observed_receipt_bytes != receipt_bytes:
            raise DefenseKitError("receipt_write_verification_failed")
        if output_zip.exists() or receipt_path.exists():
            raise DefenseKitError("output_already_exists")
        _publish_no_replace(temporary_zip, output_zip)
        published_zip = True
        _publish_no_replace(temporary_receipt, receipt_path)
        published_receipt = True
        final_zip_bytes = _verify_archive(output_zip, archive_materials)
        try:
            final_receipt_bytes = receipt_path.read_bytes()
        except OSError as exc:
            raise DefenseKitError("published_output_verification_failed") from exc
        if (
            hashlib.sha256(final_zip_bytes).hexdigest() != receipt["zip_sha256"]
            or final_receipt_bytes != receipt_bytes
        ):
            raise DefenseKitError("published_output_verification_failed")
        return receipt
    finally:
        for temporary in (temporary_zip, temporary_receipt):
            if temporary is None:
                continue
            try:
                temporary.unlink(missing_ok=True)
            except OSError:
                pass
        if sys.exc_info()[0] is not None:
            if published_receipt:
                try:
                    receipt_path.unlink(missing_ok=True)
                except OSError:
                    pass
            if published_zip:
                try:
                    output_zip.unlink(missing_ok=True)
                except OSError:
                    pass


class _RedactingArgumentParser(argparse.ArgumentParser):
    def error(self, message: str) -> None:
        del message
        raise DefenseKitError("cli_arguments_invalid")


def main(argv: list[str] | None = None) -> int:
    try:
        parser = _RedactingArgumentParser(description=__doc__)
        parser.add_argument(
            "--project-root",
            type=Path,
            default=Path(__file__).parents[1],
        )
        parser.add_argument("--public-snapshot", type=Path, required=True)
        parser.add_argument("--output-zip", type=Path, required=True)
        parser.add_argument("--receipt", type=Path, required=True)
        args = parser.parse_args(argv)
        result = build(
            root=args.project_root,
            public_snapshot=args.public_snapshot,
            output_zip=args.output_zip,
            receipt_path=args.receipt,
        )
    except DefenseKitError as exc:
        print(
            json.dumps(
                {
                    "status": "HOLD_RC4_DEFENSE_KIT",
                    "reason_code": exc.code,
                    "official_submission": "PENDING",
                },
                ensure_ascii=False,
            )
        )
        return 2
    except Exception:  # noqa: BLE001 - CLI must redact unexpected local diagnostics.
        print(
            json.dumps(
                {
                    "status": "HOLD_RC4_DEFENSE_KIT",
                    "reason_code": "defense_kit_build_failed",
                    "official_submission": "PENDING",
                },
                ensure_ascii=False,
            )
        )
        return 2
    print(json.dumps(result, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
