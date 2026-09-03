#!/usr/bin/env python3
"""Assemble a privacy-bounded, source-bound GOAI upload bundle.

The bundle is deliberately assembled from an explicit role allowlist.  It is
not a general-purpose directory copier: every input must stay inside the clean
project worktree, use the expected suffix, and be a regular non-link file.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import shutil
import stat
import subprocess
import sys
import tempfile
import zipfile
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Any, Iterable


PROJECT_ROOT = Path(__file__).resolve().parents[1]
SRC_ROOT = PROJECT_ROOT / "src"
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))

from pydantic import ValidationError  # noqa: E402

from visiondata_gate.audit_envelope import canonical_jcs_bytes  # noqa: E402
from visiondata_gate.package import validate_archive_path  # noqa: E402
from visiondata_gate.release_attestation import (  # noqa: E402
    FullTestReceipt,
    GitSourceState,
    ReleaseAttestationError,
    get_clean_git_source_state,
    load_release_attestation,
    verify_release_attestation,
)
from tools.export_public_repository import (  # noqa: E402
    PUBLIC_PAGES_TEMPLATE,
    PUBLIC_PAGES_WORKFLOW,
    _selected as public_export_selected,
)


MANIFEST_NAME = "UPLOAD_MANIFEST.json"
CHECKSUMS_NAME = "SHA256SUMS.txt"
MANIFEST_SCHEMA = "visiondata-gate.submission-upload-bundle.v1"
PUBLIC_MIRROR_SCHEMA = "visiondata-gate.public-mirror.v2"
MAX_ATTACHMENT_BYTES = 512 * 1024 * 1024
MAX_BUNDLE_BYTES = 1024 * 1024 * 1024
MAX_PUBLIC_SOURCE_FILE_BYTES = 32 * 1024 * 1024
MAX_PUBLIC_SOURCE_TOTAL_BYTES = 128 * 1024 * 1024
MAX_PUBLIC_SOURCE_ENTRIES = 20_000
PUBLIC_GENERATED_FILE_SOURCES = {
    PUBLIC_PAGES_WORKFLOW: PUBLIC_PAGES_TEMPLATE,
}

ROLE_SUFFIXES = {
    "candidate_zip": ".zip",
    "public_source_zip": ".zip",
    "roadshow_pptx": ".pptx",
    "roadshow_pdf": ".pdf",
    "demo_video": ".mp4",
    "release_attestation": ".json",
    "full_test_receipt": ".json",
    "clean_extract_receipt": ".json",
    "build_one_receipt": ".json",
    "build_two_receipt": ".json",
    "full_test_junit": ".xml",
}
TRACKED_MEDIA_ROLES = frozenset({"roadshow_pptx", "roadshow_pdf", "demo_video"})
ATTESTED_RECEIPT_ROLES = {
    "full_test_receipt": "full_test_receipt",
    "clean_extract_receipt": "clean_extract_receipt",
    "build_one_receipt": "build_one_receipt",
    "build_two_receipt": "build_two_receipt",
}
SHA256_RE = re.compile(r"[0-9a-f]{64}")


class UploadBundleError(RuntimeError):
    """Fail-closed upload bundle validation error with a non-sensitive code."""

    def __init__(self, code: str):
        if re.fullmatch(r"[a-z0-9_]{3,80}", code) is None:
            raise ValueError("upload bundle error codes must be stable identifiers")
        self.code = code
        super().__init__(code)


@dataclass(frozen=True)
class BoundFile:
    role: str
    absolute_path: Path
    relative_path: str
    filename: str
    size_bytes: int
    sha256: str

    def manifest_record(self) -> dict[str, str | int]:
        return {
            "filename": self.filename,
            "role": self.role,
            "sha256": self.sha256,
            "size_bytes": self.size_bytes,
        }


@dataclass(frozen=True)
class UploadBundleResult:
    source_commit: str
    source_tree: str
    release_id: str
    attachment_count: int
    checksums_entry_count: int
    manifest_sha256: str
    checksums_sha256: str

    def to_dict(self) -> dict[str, str | int | bool]:
        return {
            "status": "PASS_LOCAL_UPLOAD_BUNDLE",
            "source_commit": self.source_commit,
            "source_tree": self.source_tree,
            "release_id": self.release_id,
            "attachment_count": self.attachment_count,
            "checksums_entry_count": self.checksums_entry_count,
            "manifest_sha256": self.manifest_sha256,
            "checksums_sha256": self.checksums_sha256,
            "submission_eligible": False,
            "official_status": "NOT_EVALUATED",
        }


def _sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _is_redirecting_path(path: Path) -> bool:
    """Treat symlinks, Windows junctions, and unreadable metadata as unsafe."""

    try:
        if path.is_symlink():
            return True
        is_junction = getattr(path, "is_junction", None)
        if is_junction is not None and is_junction():
            return True
        os_is_junction = getattr(os.path, "isjunction", None)
        return bool(os_is_junction is not None and os_is_junction(path))
    except OSError:
        return True


def _reject_link_components(root: Path, relative: str, *, code: str) -> None:
    current = root
    for part in PurePosixPath(relative).parts:
        current = current / part
        if os.path.lexists(current) and _is_redirecting_path(current):
            raise UploadBundleError(code)


def _portable_relative(root: Path, value: Path, *, code: str) -> str:
    candidate = value if value.is_absolute() else root / value
    candidate = candidate.absolute()
    try:
        relative = candidate.relative_to(root).as_posix()
    except ValueError as exc:
        raise UploadBundleError(code) from exc
    try:
        return validate_archive_path(relative)
    except ValueError as exc:
        raise UploadBundleError(code) from exc


def _resolve_input(root: Path, role: str, value: Path) -> BoundFile:
    if role not in ROLE_SUFFIXES:
        raise UploadBundleError("unknown_input_role")
    relative = _portable_relative(root, value, code="input_outside_project")
    _reject_link_components(root, relative, code="input_link_rejected")
    candidate = root.joinpath(*PurePosixPath(relative).parts)
    try:
        resolved = candidate.resolve(strict=True)
    except (OSError, RuntimeError) as exc:
        raise UploadBundleError("input_missing_or_unreadable") from exc
    try:
        resolved.relative_to(root)
    except ValueError as exc:
        raise UploadBundleError("input_outside_project") from exc
    if not resolved.is_file() or _is_redirecting_path(candidate):
        raise UploadBundleError("input_not_regular_file")
    if candidate.suffix.casefold() != ROLE_SUFFIXES[role]:
        raise UploadBundleError("input_suffix_rejected")
    if candidate.name.casefold() in {
        MANIFEST_NAME.casefold(),
        CHECKSUMS_NAME.casefold(),
    }:
        raise UploadBundleError("reserved_output_name")
    size = candidate.stat().st_size
    if size <= 0 or size > MAX_ATTACHMENT_BYTES:
        raise UploadBundleError("input_size_rejected")
    return BoundFile(
        role=role,
        absolute_path=candidate,
        relative_path=relative,
        filename=candidate.name,
        size_bytes=size,
        sha256=_sha256_file(candidate),
    )


def _subprocess_environment() -> dict[str, str]:
    return {
        name: value
        for name, value in os.environ.items()
        if not name.upper().startswith("GIT_")
    }


def _run_git(root: Path, arguments: list[str]) -> subprocess.CompletedProcess[bytes]:
    try:
        return subprocess.run(
            ["git", "--no-replace-objects", *arguments],
            cwd=root,
            check=False,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            env=_subprocess_environment(),
            timeout=30,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise UploadBundleError("git_validation_failed") from exc


def _require_tracked_media(root: Path, item: BoundFile) -> None:
    result = _run_git(
        root,
        ["ls-files", "--error-unmatch", "--", item.relative_path],
    )
    if result.returncode != 0:
        raise UploadBundleError("media_must_be_tracked")


def _resolve_output(root: Path, value: Path) -> tuple[Path, str]:
    relative = _portable_relative(root, value, code="output_outside_project")
    if len(PurePosixPath(relative).parts) < 2:
        raise UploadBundleError("output_scope_rejected")
    _reject_link_components(root, relative, code="output_link_rejected")
    destination = root.joinpath(*PurePosixPath(relative).parts)
    if destination.exists():
        raise UploadBundleError("output_must_not_exist")
    ignored = _run_git(root, ["check-ignore", "--no-index", "-q", "--", relative])
    if ignored.returncode != 0:
        raise UploadBundleError("output_namespace_not_ignored")
    parent_relative = PurePosixPath(relative).parent.as_posix()
    ignored_parent = _run_git(
        root,
        ["check-ignore", "--no-index", "-q", "--", f"{parent_relative}/"],
    )
    if ignored_parent.returncode != 0:
        raise UploadBundleError("output_namespace_not_ignored")
    return destination, relative


def _unique_json_bytes(data: bytes, *, code: str) -> Any:
    def unique_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
        result: dict[str, Any] = {}
        for key, value in pairs:
            if key in result:
                raise UploadBundleError(code)
            result[key] = value
        return result

    try:
        text = data.decode("utf-8")
        return json.loads(text, object_pairs_hook=unique_object)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise UploadBundleError(code) from exc


def _load_full_test_receipt(item: BoundFile) -> FullTestReceipt:
    data = item.absolute_path.read_bytes()
    payload = _unique_json_bytes(data, code="full_test_receipt_invalid")
    try:
        receipt = FullTestReceipt.model_validate(payload)
    except ValidationError as exc:
        raise UploadBundleError("full_test_receipt_invalid") from exc
    canonical = canonical_jcs_bytes(
        receipt.model_dump(mode="json", by_alias=True, exclude_none=False)
    )
    if canonical != data:
        raise UploadBundleError("full_test_receipt_noncanonical")
    return receipt


def _require_binding(item: BoundFile, binding: Any, *, code: str) -> None:
    try:
        matches = (
            item.relative_path == binding.path
            and item.size_bytes == binding.size_bytes
            and item.sha256 == binding.digest.sha256
        )
    except AttributeError as exc:
        raise UploadBundleError(code) from exc
    if not matches:
        raise UploadBundleError(code)


def _validate_attested_inputs(
    *,
    root: Path,
    source: GitSourceState,
    inputs: dict[str, BoundFile],
) -> tuple[str, str, FullTestReceipt]:
    attestation_item = inputs["release_attestation"]
    try:
        verification = verify_release_attestation(
            project_root=root,
            attestation_path=attestation_item.absolute_path,
        )
        attestation = load_release_attestation(attestation_item.absolute_path)
    except (OSError, ValueError, ReleaseAttestationError) as exc:
        raise UploadBundleError("attestation_verification_failed") from exc

    predicate = attestation.statement.predicate
    if predicate.source != source:
        raise UploadBundleError("attestation_source_mismatch")
    candidate = inputs["candidate_zip"]
    subject = attestation.statement.subject[0]
    build_one = predicate.reproducibility.build_one.artifact
    if (
        subject.name != candidate.relative_path
        or subject.digest.sha256 != candidate.sha256
    ):
        raise UploadBundleError("candidate_subject_mismatch")
    _require_binding(candidate, build_one, code="candidate_binding_mismatch")
    if (
        verification.status != "PASS_LOCAL_INTEGRITY"
        or verification.subject.name != subject.name
        or verification.subject.digest.sha256 != subject.digest.sha256
        or verification.statement_digest.value != attestation.statement_digest.value
    ):
        raise UploadBundleError("attestation_verification_mismatch")

    materials = {material.kind: material for material in predicate.materials}
    if len(materials) != len(predicate.materials):
        raise UploadBundleError("attestation_material_duplicate")
    for role, kind in ATTESTED_RECEIPT_ROLES.items():
        material = materials.get(kind)
        if material is None:
            raise UploadBundleError("attestation_receipt_missing")
        _require_binding(inputs[role], material, code="attested_receipt_mismatch")

    full_receipt = _load_full_test_receipt(inputs["full_test_receipt"])
    if full_receipt.source != source:
        raise UploadBundleError("full_test_source_mismatch")
    _require_binding(
        inputs["full_test_junit"],
        full_receipt.junit,
        code="full_test_junit_mismatch",
    )
    return predicate.release_id, attestation.statement_digest.value, full_receipt


def _expected_public_source_files(root: Path) -> dict[str, tuple[int, str]]:
    result = _run_git(root, ["ls-files", "-z"])
    if result.returncode != 0:
        raise UploadBundleError("public_source_binding_failed")
    expected: dict[str, tuple[int, str]] = {}
    try:
        tracked = sorted(
            item.decode("utf-8") for item in result.stdout.split(b"\0") if item
        )
    except UnicodeDecodeError as exc:
        raise UploadBundleError("public_source_binding_failed") from exc
    for relative in tracked:
        if not public_export_selected(relative):
            continue
        try:
            normalized = validate_archive_path(relative)
        except ValueError as exc:
            raise UploadBundleError("public_source_binding_failed") from exc
        _reject_link_components(root, normalized, code="public_source_binding_failed")
        path = root.joinpath(*PurePosixPath(normalized).parts)
        try:
            resolved = path.resolve(strict=True)
            resolved.relative_to(root)
        except (OSError, RuntimeError, ValueError) as exc:
            raise UploadBundleError("public_source_binding_failed") from exc
        if not resolved.is_file() or _is_redirecting_path(path):
            raise UploadBundleError("public_source_binding_failed")
        size = path.stat().st_size
        if size <= 0 or size > MAX_PUBLIC_SOURCE_FILE_BYTES:
            raise UploadBundleError("public_source_binding_failed")
        expected[normalized] = (size, _sha256_file(path))

    for generated, source_path in PUBLIC_GENERATED_FILE_SOURCES.items():
        binding = expected.get(source_path)
        if binding is None:
            raise UploadBundleError("public_source_binding_failed")
        expected[generated] = binding
    if not expected or len(expected) > MAX_PUBLIC_SOURCE_ENTRIES:
        raise UploadBundleError("public_source_binding_failed")
    return expected


def _validate_public_source_zip(
    item: BoundFile,
    source: GitSourceState,
    *,
    expected_files: dict[str, tuple[int, str]],
) -> None:
    try:
        archive = zipfile.ZipFile(item.absolute_path, mode="r")
    except (OSError, zipfile.BadZipFile) as exc:
        raise UploadBundleError("public_source_zip_invalid") from exc

    with archive:
        manifest_data: bytes | None = None
        observed: dict[str, tuple[int, str]] = {}
        seen_casefold: set[str] = set()
        total_size = 0
        infos = archive.infolist()
        if len(infos) > MAX_PUBLIC_SOURCE_ENTRIES + 1:
            raise UploadBundleError("public_source_entry_count_rejected")
        for info in infos:
            name = info.filename.rstrip("/")
            if not name:
                continue
            try:
                normalized = validate_archive_path(name)
            except ValueError as exc:
                raise UploadBundleError("public_source_path_rejected") from exc
            folded = normalized.casefold()
            if folded in seen_casefold:
                raise UploadBundleError("public_source_path_collision")
            seen_casefold.add(folded)
            if any(
                part.casefold() == ".git" for part in PurePosixPath(normalized).parts
            ):
                raise UploadBundleError("public_source_git_history_rejected")
            mode = (info.external_attr >> 16) & 0xFFFF
            if info.flag_bits & 0x1:
                raise UploadBundleError("public_source_entry_rejected")
            if info.is_dir():
                if mode and not stat.S_ISDIR(mode):
                    raise UploadBundleError("public_source_entry_rejected")
                continue
            if mode and not stat.S_ISREG(mode):
                raise UploadBundleError("public_source_entry_rejected")
            if info.file_size <= 0 or info.file_size > MAX_PUBLIC_SOURCE_FILE_BYTES:
                raise UploadBundleError("public_source_size_rejected")
            total_size += info.file_size
            if total_size > MAX_PUBLIC_SOURCE_TOTAL_BYTES:
                raise UploadBundleError("public_source_size_rejected")
            try:
                data = archive.read(info)
            except (RuntimeError, zipfile.BadZipFile, NotImplementedError) as exc:
                raise UploadBundleError("public_source_zip_invalid") from exc
            if normalized == "PUBLIC_MIRROR_MANIFEST.json":
                manifest_data = data
            else:
                observed[normalized] = (len(data), _sha256_bytes(data))

    if manifest_data is None:
        raise UploadBundleError("public_source_manifest_missing")
    manifest = _unique_json_bytes(
        manifest_data,
        code="public_source_manifest_invalid",
    )
    expected_fields = {
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
    if not isinstance(manifest, dict) or set(manifest) != expected_fields:
        raise UploadBundleError("public_source_manifest_invalid")
    if (
        manifest.get("schema_version") != PUBLIC_MIRROR_SCHEMA
        or manifest.get("source_commit_oid") != source.commit
        or manifest.get("source_tree_oid") != source.tree
        or manifest.get("source_worktree_clean") is not True
        or manifest.get("source_history_included") is not False
        or manifest.get("private_release_evidence_included") is not False
        or manifest.get("customer_data_included") is not False
        or manifest.get("personal_data_included") is not False
        or manifest.get("tracked_source_only") is not True
    ):
        raise UploadBundleError("public_source_boundary_mismatch")
    entries = manifest.get("files")
    file_count = manifest.get("file_count")
    if (
        not isinstance(entries, list)
        or not isinstance(file_count, int)
        or isinstance(file_count, bool)
        or file_count != len(entries)
    ):
        raise UploadBundleError("public_source_manifest_invalid")

    declared: dict[str, tuple[int, str]] = {}
    ordered_paths: list[str] = []
    snapshot_digest = hashlib.sha256()
    for entry in entries:
        if not isinstance(entry, dict):
            raise UploadBundleError("public_source_manifest_invalid")
        relative = entry.get("path")
        expected_keys = {"path", "sha256", "size_bytes"}
        if relative in PUBLIC_GENERATED_FILE_SOURCES:
            expected_keys.add("source")
        if set(entry) != expected_keys or not isinstance(relative, str):
            raise UploadBundleError("public_source_manifest_invalid")
        try:
            validate_archive_path(relative)
        except ValueError as exc:
            raise UploadBundleError("public_source_manifest_invalid") from exc
        size = entry.get("size_bytes")
        digest = entry.get("sha256")
        if (
            relative in declared
            or not isinstance(size, int)
            or isinstance(size, bool)
            or size <= 0
            or not isinstance(digest, str)
            or SHA256_RE.fullmatch(digest) is None
        ):
            raise UploadBundleError("public_source_manifest_invalid")
        expected_generated_source = PUBLIC_GENERATED_FILE_SOURCES.get(relative)
        if (
            expected_generated_source is not None
            and entry.get("source") != expected_generated_source
        ):
            raise UploadBundleError("public_source_manifest_invalid")
        declared[relative] = (size, digest)
        ordered_paths.append(relative)
        snapshot_digest.update(relative.encode("utf-8"))
        snapshot_digest.update(b"\0")
        snapshot_digest.update(digest.encode("ascii"))
        snapshot_digest.update(b"\0")

    if (
        ordered_paths != sorted(ordered_paths)
        or declared != observed
        or declared != expected_files
        or manifest.get("snapshot_sha256") != snapshot_digest.hexdigest()
    ):
        raise UploadBundleError("public_source_manifest_mismatch")


def _checksums_bytes(items: Iterable[tuple[str, str]]) -> bytes:
    ordered = sorted(items, key=lambda item: item[0])
    return "".join(f"{digest}  {filename}\n" for filename, digest in ordered).encode(
        "utf-8"
    )


def _copy_and_verify(item: BoundFile, destination: Path) -> None:
    shutil.copyfile(item.absolute_path, destination)
    if (
        destination.stat().st_size != item.size_bytes
        or _sha256_file(destination) != item.sha256
        or item.absolute_path.stat().st_size != item.size_bytes
        or _sha256_file(item.absolute_path) != item.sha256
    ):
        raise UploadBundleError("input_drift_during_copy")


def assemble_upload_bundle(
    *,
    project_root: str | Path,
    output: str | Path,
    candidate_zip: str | Path,
    public_source_zip: str | Path,
    roadshow_pptx: str | Path,
    roadshow_pdf: str | Path,
    demo_video: str | Path,
    release_attestation: str | Path,
    full_test_receipt: str | Path,
    clean_extract_receipt: str | Path,
    build_one_receipt: str | Path,
    build_two_receipt: str | Path,
    full_test_junit: str | Path,
) -> UploadBundleResult:
    """Validate, copy, hash, and atomically publish one local upload bundle."""

    root = Path(project_root).resolve(strict=True)
    if not root.is_dir():
        raise UploadBundleError("project_root_invalid")
    try:
        source = get_clean_git_source_state(root)
    except (OSError, ValueError, ReleaseAttestationError) as exc:
        raise UploadBundleError("source_not_clean_or_committed") from exc
    destination, _ = _resolve_output(root, Path(output))

    raw_inputs = {
        "candidate_zip": Path(candidate_zip),
        "public_source_zip": Path(public_source_zip),
        "roadshow_pptx": Path(roadshow_pptx),
        "roadshow_pdf": Path(roadshow_pdf),
        "demo_video": Path(demo_video),
        "release_attestation": Path(release_attestation),
        "full_test_receipt": Path(full_test_receipt),
        "clean_extract_receipt": Path(clean_extract_receipt),
        "build_one_receipt": Path(build_one_receipt),
        "build_two_receipt": Path(build_two_receipt),
        "full_test_junit": Path(full_test_junit),
    }
    inputs = {
        role: _resolve_input(root, role, value) for role, value in raw_inputs.items()
    }
    filenames = [item.filename.casefold() for item in inputs.values()]
    if len(set(filenames)) != len(filenames):
        raise UploadBundleError("duplicate_attachment_basename")
    if sum(item.size_bytes for item in inputs.values()) > MAX_BUNDLE_BYTES:
        raise UploadBundleError("bundle_size_rejected")
    for role in TRACKED_MEDIA_ROLES:
        _require_tracked_media(root, inputs[role])

    release_id, statement_digest, _ = _validate_attested_inputs(
        root=root,
        source=source,
        inputs=inputs,
    )
    expected_public_files = _expected_public_source_files(root)
    _validate_public_source_zip(
        inputs["public_source_zip"],
        source,
        expected_files=expected_public_files,
    )
    try:
        if get_clean_git_source_state(root) != source:
            raise UploadBundleError("source_drift_during_validation")
    except ReleaseAttestationError as exc:
        raise UploadBundleError("source_drift_during_validation") from exc

    destination.parent.mkdir(parents=True, exist_ok=True)
    staging = Path(
        tempfile.mkdtemp(
            prefix=".visiondata-gate-upload-",
            dir=destination.parent,
        )
    )
    promoted = False
    try:
        for item in sorted(inputs.values(), key=lambda value: value.filename):
            _copy_and_verify(item, staging / item.filename)

        manifest = {
            "schema_version": MANIFEST_SCHEMA,
            "source": {
                "commit": source.commit,
                "tree": source.tree,
                "dirty": False,
            },
            "release": {
                "release_id": release_id,
                "attestation_statement_digest": statement_digest,
                "attestation_verification": "PASS_LOCAL_INTEGRITY",
                "signature": "NOT_CONFIGURED",
                "trusted_timestamp": "NOT_CONFIGURED",
                "external_anchor": "NOT_CONFIGURED",
                "submission_eligible": False,
                "official_status": "NOT_EVALUATED",
            },
            "attachment_count": len(inputs),
            "attachments": [
                item.manifest_record()
                for item in sorted(inputs.values(), key=lambda value: value.role)
            ],
            "checksums": {
                "algorithm": "SHA-256",
                "filename": CHECKSUMS_NAME,
                "entry_count": len(inputs) + 1,
                "scope": "ALL_ATTACHMENTS_AND_MANIFEST_EXCLUDING_CHECKSUM_FILE",
            },
            "privacy_boundary": {
                "bundle_metadata_absolute_paths_included": False,
                "attachment_privacy_evaluation": "NOT_EVALUATED_BY_THIS_TOOL",
                "personal_identity_status": "NOT_EVALUATED",
                "credential_status": "NOT_EVALUATED",
            },
        }
        manifest_bytes = canonical_jcs_bytes(manifest)
        manifest_path = staging / MANIFEST_NAME
        manifest_path.write_bytes(manifest_bytes)
        checksum_records = [
            (item.filename, item.sha256) for item in inputs.values()
        ] + [(MANIFEST_NAME, _sha256_bytes(manifest_bytes))]
        checksums_bytes = _checksums_bytes(checksum_records)
        (staging / CHECKSUMS_NAME).write_bytes(checksums_bytes)

        expected_names = {item.filename for item in inputs.values()} | {
            MANIFEST_NAME,
            CHECKSUMS_NAME,
        }
        if {path.name for path in staging.iterdir()} != expected_names:
            raise UploadBundleError("bundle_output_set_drift")
        for filename, digest in checksum_records:
            if _sha256_file(staging / filename) != digest:
                raise UploadBundleError("bundle_output_hash_drift")
        try:
            if get_clean_git_source_state(root) != source:
                raise UploadBundleError("source_drift_during_assembly")
        except ReleaseAttestationError as exc:
            raise UploadBundleError("source_drift_during_assembly") from exc
        if destination.exists():
            raise UploadBundleError("output_must_not_exist")
        staging.replace(destination)
        promoted = True
        return UploadBundleResult(
            source_commit=source.commit,
            source_tree=source.tree,
            release_id=release_id,
            attachment_count=len(inputs),
            checksums_entry_count=len(checksum_records),
            manifest_sha256=_sha256_bytes(manifest_bytes),
            checksums_sha256=_sha256_bytes(checksums_bytes),
        )
    finally:
        if not promoted and staging.exists():
            shutil.rmtree(staging)


class _RedactingArgumentParser(argparse.ArgumentParser):
    def error(self, message: str) -> None:
        del message
        raise UploadBundleError("cli_arguments_invalid")


def build_parser() -> argparse.ArgumentParser:
    parser = _RedactingArgumentParser(description=__doc__)
    parser.add_argument("--project-root", type=Path, default=PROJECT_ROOT)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--candidate-zip", type=Path, required=True)
    parser.add_argument("--public-source-zip", type=Path, required=True)
    parser.add_argument("--pptx", type=Path, required=True)
    parser.add_argument("--pdf", type=Path, required=True)
    parser.add_argument("--video", type=Path, required=True)
    parser.add_argument("--attestation", type=Path, required=True)
    parser.add_argument("--full-test-receipt", type=Path, required=True)
    parser.add_argument("--clean-extract-receipt", type=Path, required=True)
    parser.add_argument("--build-one-receipt", type=Path, required=True)
    parser.add_argument("--build-two-receipt", type=Path, required=True)
    parser.add_argument("--full-test-junit", type=Path, required=True)
    return parser


def main(argv: list[str] | None = None) -> int:
    try:
        args = build_parser().parse_args(argv)
        result = assemble_upload_bundle(
            project_root=args.project_root,
            output=args.output,
            candidate_zip=args.candidate_zip,
            public_source_zip=args.public_source_zip,
            roadshow_pptx=args.pptx,
            roadshow_pdf=args.pdf,
            demo_video=args.video,
            release_attestation=args.attestation,
            full_test_receipt=args.full_test_receipt,
            clean_extract_receipt=args.clean_extract_receipt,
            build_one_receipt=args.build_one_receipt,
            build_two_receipt=args.build_two_receipt,
            full_test_junit=args.full_test_junit,
        )
    except UploadBundleError as exc:
        payload = {
            "ok": False,
            "status": "HOLD_UPLOAD_BUNDLE",
            "reason_code": exc.code,
            "values_disclosed": False,
            "submission_eligible": False,
            "official_status": "NOT_EVALUATED",
        }
        sys.stdout.buffer.write(canonical_jcs_bytes(payload))
        return 2
    except Exception:
        payload = {
            "ok": False,
            "status": "HOLD_UPLOAD_BUNDLE",
            "reason_code": "unexpected_failure_without_local_diagnostics",
            "values_disclosed": False,
            "submission_eligible": False,
            "official_status": "NOT_EVALUATED",
        }
        sys.stdout.buffer.write(canonical_jcs_bytes(payload))
        return 2

    payload = {
        "ok": True,
        **result.to_dict(),
        "destination": "project-local-ignored-upload-bundle",
    }
    sys.stdout.buffer.write(canonical_jcs_bytes(payload))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
