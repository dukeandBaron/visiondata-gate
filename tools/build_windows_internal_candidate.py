"""Build one parameterized, create-only Windows internal candidate ZIP.

The archive is deliberately an internal review artifact.  It binds one exact
installer to its build manifest and two caller-selected validation documents;
it never installs, publishes, moves, replaces, or deletes an existing artifact.
"""

from __future__ import annotations

import argparse
import hashlib
import hmac
import json
from pathlib import Path, PurePosixPath
import re
import stat
import sys
from typing import Any
import zipfile


FIXED_ZIP_TIME = (1980, 1, 1, 0, 0, 0)
INSTALLER_MEMBER = "installer/VisionData Gate_0.1.0_x64-setup.exe"
README_MEMBER = "README_INTERNAL_CANDIDATE.md"
CHECKSUM_MEMBER = "SHA256SUMS.txt"
BUILD_MANIFEST_MEMBER = "evidence/BUILD_MANIFEST.json"
IDENTITY_MEMBER = "evidence/BUILD_SOURCE_IDENTITY.json"
VALIDATION_SUMMARY_MEMBER = "evidence/VALIDATION_SUMMARY.json"
VALIDATION_RECEIPT_MEMBER = "evidence/VALIDATION_RECEIPT.json"
MEMBER_ORDER = (
    INSTALLER_MEMBER,
    README_MEMBER,
    BUILD_MANIFEST_MEMBER,
    IDENTITY_MEMBER,
    VALIDATION_SUMMARY_MEMBER,
    VALIDATION_RECEIPT_MEMBER,
    CHECKSUM_MEMBER,
)
SHA256_PATTERN = re.compile(r"^[0-9a-f]{64}$")
BUILD_ID_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{5,119}$")
VERSION_PATTERN = re.compile(r"^[0-9]+\.[0-9]+\.[0-9]+(?:[-+][A-Za-z0-9.-]+)?$")
WINDOWS_ABSOLUTE = re.compile(r"(?i)^(?:[a-z]:[\\/]|\\\\)")
# These values are denylist prefixes, never temporary write destinations.
PRIVATE_POSIX_PREFIXES = ("/home/", "/root/", "/Users/", "/mnt/", "/tmp/")  # nosec B108
FORBIDDEN_ARCHIVE_SUFFIXES = (
    ".pt",
    ".pth",
    ".ckpt",
    ".db",
    ".sqlite",
    ".sqlite3",
    ".log",
    ".env",
)
SENSITIVE_KEYS = {
    "access_token",
    "api_key",
    "apikey",
    "authorization",
    "client_secret",
    "cookie",
    "password",
    "private_key",
    "refresh_token",
    "set_cookie",
}


class CandidateError(ValueError):
    """Stable fail-closed error code without a private filesystem path."""


def _require(condition: bool, code: str) -> None:
    if not condition:
        raise CandidateError(code)


def _valid_sha256(value: str) -> bool:
    return isinstance(value, str) and SHA256_PATTERN.fullmatch(value) is not None


def _is_link_or_reparse(path: Path) -> bool:
    try:
        metadata = path.lstat()
    except OSError:
        raise CandidateError("LOCAL_ARTIFACT_UNAVAILABLE") from None
    junction = getattr(path, "is_junction", None)
    try:
        is_junction = bool(junction()) if callable(junction) else False
    except OSError:
        raise CandidateError("LOCAL_ARTIFACT_UNAVAILABLE") from None
    return bool(
        stat.S_ISLNK(metadata.st_mode)
        or getattr(metadata, "st_file_attributes", 0) & 0x400
        or is_junction
    )


def _regular_file(path: Path, unavailable_code: str) -> Path:
    candidate = Path(path).expanduser()
    _require(candidate.is_absolute(), "ABSOLUTE_INPUT_PATH_REQUIRED")
    for member in (candidate, *candidate.parents):
        if not member.exists():
            raise CandidateError(unavailable_code)
        if _is_link_or_reparse(member):
            raise CandidateError("LOCAL_ARTIFACT_LINK_FORBIDDEN")
    try:
        metadata = candidate.stat()
    except OSError:
        raise CandidateError(unavailable_code) from None
    _require(stat.S_ISREG(metadata.st_mode), unavailable_code)
    _require(metadata.st_size <= 2 * 1024**3, "LOCAL_ARTIFACT_TOO_LARGE")
    return candidate.resolve(strict=True)


def _hash_file(path: Path) -> tuple[str, int]:
    digest = hashlib.sha256()
    try:
        before = path.stat()
        with path.open("rb") as stream:
            for chunk in iter(lambda: stream.read(1024 * 1024), b""):
                digest.update(chunk)
        after = path.stat()
    except OSError:
        raise CandidateError("LOCAL_ARTIFACT_UNAVAILABLE") from None
    _require(
        (before.st_size, before.st_mtime_ns, before.st_ino)
        == (after.st_size, after.st_mtime_ns, after.st_ino),
        "LOCAL_ARTIFACT_CHANGED_DURING_READ",
    )
    return digest.hexdigest(), after.st_size


def _read_bound_bytes(
    path: Path,
    expected_sha256: str,
    mismatch_code: str,
    *,
    max_bytes: int,
) -> tuple[Path, bytes]:
    _require(_valid_sha256(expected_sha256), "EXPECTED_SHA256_INVALID")
    verified = _regular_file(path, "LOCAL_ARTIFACT_UNAVAILABLE")
    _require(verified.stat().st_size <= max_bytes, "JSON_ARTIFACT_TOO_LARGE")
    try:
        before = verified.stat()
        raw = verified.read_bytes()
        after = verified.stat()
    except OSError:
        raise CandidateError("LOCAL_ARTIFACT_UNAVAILABLE") from None
    _require(
        (before.st_size, before.st_mtime_ns, before.st_ino)
        == (after.st_size, after.st_mtime_ns, after.st_ino),
        "LOCAL_ARTIFACT_CHANGED_DURING_READ",
    )
    actual = hashlib.sha256(raw).hexdigest()
    _require(hmac.compare_digest(actual, expected_sha256), mismatch_code)
    return verified, raw


def _walk_strings(value: Any):
    if isinstance(value, str):
        yield value
    elif isinstance(value, dict):
        for key, item in value.items():
            yield from _walk_strings(key)
            yield from _walk_strings(item)
    elif isinstance(value, (list, tuple)):
        for item in value:
            yield from _walk_strings(item)


def _reject_private_or_absolute_values(value: dict) -> None:
    for item in _walk_strings(value):
        normalized = item.strip()
        lowered = normalized.lower()
        if (
            WINDOWS_ABSOLUTE.match(normalized)
            or lowered.startswith("file://")
            or any(normalized.startswith(prefix) for prefix in PRIVATE_POSIX_PREFIXES)
            or "\\appdata\\" in lowered
            or "product.sqlite3" in lowered
        ):
            raise CandidateError("PRIVATE_OR_ABSOLUTE_PATH_FORBIDDEN")


def _reject_credentials(value: Any) -> None:
    if isinstance(value, dict):
        for key, item in value.items():
            normalized_key = str(key).strip().lower().replace("-", "_")
            if normalized_key in SENSITIVE_KEYS:
                raise CandidateError("PRIVATE_OR_CREDENTIAL_DATA_FORBIDDEN")
            _reject_credentials(item)
    elif isinstance(value, (list, tuple)):
        for item in value:
            _reject_credentials(item)
    elif isinstance(value, str):
        lowered = value.strip().lower()
        if (
            lowered.startswith(("bearer ", "sk-"))
            or "api_key=" in lowered
            or "access_token=" in lowered
            or "x-amz-signature=" in lowered
        ):
            raise CandidateError("PRIVATE_OR_CREDENTIAL_DATA_FORBIDDEN")


def _parse_safe_json(raw: bytes) -> dict:
    try:
        value = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError):
        raise CandidateError("VALIDATION_JSON_INVALID") from None
    _require(isinstance(value, dict), "VALIDATION_JSON_OBJECT_REQUIRED")
    _reject_private_or_absolute_values(value)
    _reject_credentials(value)
    return value


def _canonical_json(value: dict) -> bytes:
    try:
        text = json.dumps(
            value,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        )
    except (TypeError, ValueError):
        raise CandidateError("CANDIDATE_METADATA_INVALID") from None
    return (text + "\n").encode("utf-8")


def _prepare_output(output_zip: Path) -> Path:
    output = Path(output_zip).expanduser()
    _require(output.is_absolute(), "ABSOLUTE_OUTPUT_PATH_REQUIRED")
    _require(output.suffix.lower() == ".zip", "OUTPUT_ZIP_SUFFIX_REQUIRED")
    _require(not output.exists(), "OUTPUT_ALREADY_EXISTS")
    parent = output.parent
    _require(parent.is_dir(), "OUTPUT_PARENT_DIRECTORY_REQUIRED")
    for member in (parent, *parent.parents):
        if _is_link_or_reparse(member):
            raise CandidateError("OUTPUT_PARENT_LINK_FORBIDDEN")
    return output.absolute()


def _validate_boundaries(
    *,
    installer_sha256: str,
    installer_bytes: int,
    build_manifest_sha256: str,
    build_manifest: dict,
    validation_summary: dict,
    validation_receipt: dict,
) -> None:
    installer = build_manifest.get("artifacts", {}).get("installer", {})
    _require(
        isinstance(installer, dict)
        and installer.get("sha256") == installer_sha256
        and installer.get("size") == installer_bytes,
        "BUILD_MANIFEST_INSTALLER_MISMATCH",
    )
    source_sha256 = build_manifest.get("source_content_sha256")
    _require(_valid_sha256(source_sha256), "BUILD_SOURCE_IDENTITY_INVALID")
    _require(
        build_manifest.get("production_release_allowed") is False
        and validation_summary.get("production_release_allowed") is False
        and validation_receipt.get("production_release_allowed") is False,
        "PRODUCTION_AUTHORITY_WIDENED",
    )
    _require(
        validation_summary.get("machine_write_permitted") is False
        and validation_receipt.get("machine_write_permitted") is False,
        "MACHINE_AUTHORITY_WIDENED",
    )
    _require(
        build_manifest.get("code_signed") is False,
        "SIGNED_BUILD_NOT_SUPPORTED_BY_NOT_SIGNED_CANDIDATE",
    )
    _require(
        build_manifest.get("clean_machine_validation") == "NOT_RUN"
        and validation_summary.get("clean_machine_validation") == "NOT_RUN"
        and validation_receipt.get("clean_machine_validation") == "NOT_RUN",
        "CLEAN_MACHINE_BOUNDARY_MISMATCH",
    )
    _require(
        validation_summary.get("industrial_performance_verified") is False
        and validation_receipt.get("industrial_performance_verified") is False,
        "INDUSTRIAL_VALIDATION_MUST_REMAIN_HOLD",
    )
    capability = build_manifest.get("external_runtime_model_capability")
    _require(
        isinstance(capability, dict)
        and capability.get("capability") == "EXTERNAL_RUNTIME_REQUIRED"
        and capability.get("model_pack_bundled") is False
        and capability.get("production_release_allowed") is False,
        "EXTERNAL_RUNTIME_BOUNDARY_MISMATCH",
    )
    _require(
        validation_summary.get("bound_build_manifest_sha256")
        == build_manifest_sha256,
        "VALIDATION_SUMMARY_BUILD_BINDING_MISMATCH",
    )
    receipt_installer_sha = validation_receipt.get(
        "installer_sha256",
        validation_receipt.get("bound_installer_sha256"),
    )
    _require(
        receipt_installer_sha == installer_sha256,
        "VALIDATION_RECEIPT_INSTALLER_BINDING_MISMATCH",
    )


def _release_boundaries() -> dict:
    return {
        "candidate_scope": "INTERNAL_ONLY",
        "clean_machine_validation": "NOT_RUN",
        "external_runtime_required": True,
        "industrial_validation": "HOLD",
        "license_review_required": True,
        "model_pack_bundled": False,
        "production_release_allowed": False,
        "signature_status": "NOT_SIGNED",
    }


def _readme(
    *,
    build_id: str,
    package_version: str,
    installer_sha256: str,
    source_content_sha256: str,
) -> bytes:
    return f"""# VisionData Gate Windows Internal Candidate

Build: `{build_id}`  
Package version: `{package_version}`

This ZIP is an internal review candidate only. It is not a public release,
factory acceptance record, or production authorization.

- Signature: **NotSigned**
- Model execution: **External Runtime Required**
- Payload: **No Model Pack Bundled**
- Authority: `production_release_allowed=false`
- Portability: `clean-machine validation=NOT_RUN`
- Effectiveness: `industrial validation=HOLD`
- Distribution: **license review required** before any external delivery

The optional vision path requires a separately authorized Python/Torch/
TorchVision/Ultralytics runtime and separately supplied model pack. SHA-256
proves artifact identity only; it is not a safety certificate or license grant.

Installer SHA-256: `{installer_sha256}`  
Frozen source content SHA-256: `{source_content_sha256}`

`SHA256SUMS.txt` covers every archive member except itself to avoid recursive
self-reference. Validate the archive and every checksum before review.
""".encode("utf-8")


def _zip_info(name: str) -> zipfile.ZipInfo:
    pure = PurePosixPath(name)
    _require(
        not pure.is_absolute()
        and pure.parts
        and all(part not in {"", ".", ".."} for part in pure.parts),
        "ARCHIVE_MEMBER_PATH_INVALID",
    )
    info = zipfile.ZipInfo(name, date_time=FIXED_ZIP_TIME)
    info.compress_type = zipfile.ZIP_STORED
    info.create_system = 3
    info.external_attr = 0o100644 << 16
    return info


def _write_bytes_member(
    archive: zipfile.ZipFile,
    name: str,
    payload: bytes,
) -> None:
    archive.writestr(_zip_info(name), payload)


def _write_installer_member(
    archive: zipfile.ZipFile,
    installer: Path,
    expected_sha256: str,
    expected_bytes: int,
) -> None:
    digest = hashlib.sha256()
    try:
        before = installer.stat()
        with installer.open("rb") as source, archive.open(
            _zip_info(INSTALLER_MEMBER), "w", force_zip64=True
        ) as destination:
            for chunk in iter(lambda: source.read(1024 * 1024), b""):
                digest.update(chunk)
                destination.write(chunk)
        after = installer.stat()
    except OSError:
        raise CandidateError("INSTALLER_UNAVAILABLE_DURING_BUILD") from None
    _require(
        (before.st_size, before.st_mtime_ns, before.st_ino)
        == (after.st_size, after.st_mtime_ns, after.st_ino)
        and after.st_size == expected_bytes
        and hmac.compare_digest(digest.hexdigest(), expected_sha256),
        "INSTALLER_CHANGED_DURING_BUILD",
    )


def _parse_checksums(raw: bytes) -> dict[str, str]:
    try:
        rows = raw.decode("utf-8").splitlines()
        values = {}
        for row in rows:
            digest, name = row.split("  ", 1)
            if name in values:
                raise ValueError("duplicate checksum member")
            values[name] = digest
    except (UnicodeDecodeError, ValueError):
        raise CandidateError("ARCHIVE_CHECKSUMS_INVALID") from None
    _require(
        all(_valid_sha256(digest) for digest in values.values()),
        "ARCHIVE_CHECKSUMS_INVALID",
    )
    return values


def _verify_archive(output: Path, expected_members: set[str]) -> None:
    try:
        with zipfile.ZipFile(output) as archive:
            _require(archive.testzip() is None, "ARCHIVE_CRC_INVALID")
            _require(
                set(archive.namelist()) == expected_members,
                "ARCHIVE_MEMBER_SET_MISMATCH",
            )
            for info in archive.infolist():
                pure = PurePosixPath(info.filename)
                mode = info.external_attr >> 16
                _require(
                    not pure.is_absolute()
                    and ".." not in pure.parts
                    and not stat.S_ISLNK(mode)
                    and not info.is_dir(),
                    "ARCHIVE_MEMBER_PATH_INVALID",
                )
                _require(
                    not info.filename.lower().endswith(FORBIDDEN_ARCHIVE_SUFFIXES),
                    "PRIVATE_OR_MODEL_ARTIFACT_IN_ARCHIVE",
                )
            checksums = _parse_checksums(archive.read(CHECKSUM_MEMBER))
            _require(
                set(checksums) == expected_members - {CHECKSUM_MEMBER},
                "ARCHIVE_CHECKSUM_SCOPE_MISMATCH",
            )
            for name, expected in checksums.items():
                digest = hashlib.sha256()
                with archive.open(name) as stream:
                    for chunk in iter(lambda: stream.read(1024 * 1024), b""):
                        digest.update(chunk)
                _require(
                    hmac.compare_digest(digest.hexdigest(), expected),
                    "ARCHIVE_MEMBER_SHA256_MISMATCH",
                )
    except (OSError, zipfile.BadZipFile):
        raise CandidateError("ARCHIVE_VALIDATION_FAILED") from None


def build_internal_candidate(
    *,
    installer: Path,
    expected_installer_sha256: str,
    build_manifest: Path,
    expected_build_manifest_sha256: str,
    validation_summary: Path,
    expected_validation_summary_sha256: str,
    validation_receipt: Path,
    expected_validation_receipt_sha256: str,
    output_zip: Path,
    build_id: str,
    package_version: str,
) -> dict:
    """Create one immutable internal ZIP from explicit, SHA-bound inputs."""

    output = _prepare_output(output_zip)
    _require(BUILD_ID_PATTERN.fullmatch(build_id) is not None, "BUILD_ID_INVALID")
    _require(
        VERSION_PATTERN.fullmatch(package_version) is not None,
        "PACKAGE_VERSION_INVALID",
    )
    _require(_valid_sha256(expected_installer_sha256), "EXPECTED_SHA256_INVALID")
    installer_path = _regular_file(installer, "INSTALLER_UNAVAILABLE")
    installer_actual_sha256, installer_bytes = _hash_file(installer_path)
    _require(
        hmac.compare_digest(installer_actual_sha256, expected_installer_sha256),
        "INSTALLER_SHA256_MISMATCH",
    )
    _manifest_path, manifest_raw = _read_bound_bytes(
        build_manifest,
        expected_build_manifest_sha256,
        "BUILD_MANIFEST_SHA256_MISMATCH",
        max_bytes=64 * 1024 * 1024,
    )
    _summary_path, summary_raw = _read_bound_bytes(
        validation_summary,
        expected_validation_summary_sha256,
        "VALIDATION_SUMMARY_SHA256_MISMATCH",
        max_bytes=64 * 1024 * 1024,
    )
    _receipt_path, receipt_raw = _read_bound_bytes(
        validation_receipt,
        expected_validation_receipt_sha256,
        "VALIDATION_RECEIPT_SHA256_MISMATCH",
        max_bytes=64 * 1024 * 1024,
    )
    manifest_value = _parse_safe_json(manifest_raw)
    summary_value = _parse_safe_json(summary_raw)
    receipt_value = _parse_safe_json(receipt_raw)
    _validate_boundaries(
        installer_sha256=expected_installer_sha256,
        installer_bytes=installer_bytes,
        build_manifest_sha256=expected_build_manifest_sha256,
        build_manifest=manifest_value,
        validation_summary=summary_value,
        validation_receipt=receipt_value,
    )
    boundaries = _release_boundaries()
    identity = {
        "schema_version": "visiondata-gate.windows-internal-candidate-identity.v1",
        "status": "INTERNAL_CANDIDATE_RELEASE_HOLD",
        "build_id": build_id,
        "package_version": package_version,
        "source_content_sha256": manifest_value["source_content_sha256"],
        "installer": {
            "member_path": INSTALLER_MEMBER,
            "sha256": expected_installer_sha256,
            "bytes": installer_bytes,
        },
        "evidence": {
            BUILD_MANIFEST_MEMBER: {
                "sha256": expected_build_manifest_sha256,
                "bytes": len(manifest_raw),
                "schema_version": manifest_value.get("schema_version"),
                "status": manifest_value.get("status"),
            },
            VALIDATION_SUMMARY_MEMBER: {
                "sha256": expected_validation_summary_sha256,
                "bytes": len(summary_raw),
                "schema_version": summary_value.get("schema_version"),
                "status": summary_value.get("status"),
            },
            VALIDATION_RECEIPT_MEMBER: {
                "sha256": expected_validation_receipt_sha256,
                "bytes": len(receipt_raw),
                "schema_version": receipt_value.get("schema_version"),
                "status": receipt_value.get("status"),
            },
        },
        "checksum_scope": "ALL_MEMBERS_EXCEPT_SHA256SUMS_TO_AVOID_SELF_REFERENCE",
        "release_boundaries": boundaries,
        "machine_write_permitted": False,
        "production_release_allowed": False,
    }
    payloads = {
        README_MEMBER: _readme(
            build_id=build_id,
            package_version=package_version,
            installer_sha256=expected_installer_sha256,
            source_content_sha256=manifest_value["source_content_sha256"],
        ),
        BUILD_MANIFEST_MEMBER: manifest_raw,
        IDENTITY_MEMBER: _canonical_json(identity),
        VALIDATION_SUMMARY_MEMBER: summary_raw,
        VALIDATION_RECEIPT_MEMBER: receipt_raw,
    }
    member_sha256 = {
        INSTALLER_MEMBER: expected_installer_sha256,
        **{
            name: hashlib.sha256(payload).hexdigest()
            for name, payload in payloads.items()
        },
    }
    payloads[CHECKSUM_MEMBER] = "".join(
        f"{member_sha256[name]}  {name}\n"
        for name in MEMBER_ORDER
        if name != CHECKSUM_MEMBER
    ).encode("utf-8")
    try:
        with zipfile.ZipFile(
            output,
            mode="x",
            compression=zipfile.ZIP_STORED,
            strict_timestamps=True,
        ) as archive:
            for name in MEMBER_ORDER:
                if name == INSTALLER_MEMBER:
                    _write_installer_member(
                        archive,
                        installer_path,
                        expected_installer_sha256,
                        installer_bytes,
                    )
                else:
                    _write_bytes_member(archive, name, payloads[name])
    except FileExistsError:
        raise CandidateError("OUTPUT_ALREADY_EXISTS") from None
    _verify_archive(output, set(MEMBER_ORDER))
    archive_sha256, archive_bytes = _hash_file(output)
    return {
        "schema_version": "visiondata-gate.windows-internal-candidate-build.v1",
        "status": "CREATED_INTERNAL_CANDIDATE_RELEASE_HOLD",
        "archive_name": output.name,
        "sha256": archive_sha256,
        "bytes": archive_bytes,
        "member_count": len(MEMBER_ORDER),
        "installer_sha256": expected_installer_sha256,
        "source_content_sha256": manifest_value["source_content_sha256"],
        "release_boundaries": boundaries,
        "machine_write_permitted": False,
        "production_release_allowed": False,
    }


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Create a SHA-bound Windows internal candidate ZIP without "
            "installing, publishing, moving, or replacing artifacts."
        )
    )
    parser.add_argument("--installer", required=True, type=Path)
    parser.add_argument("--installer-sha256", required=True)
    parser.add_argument("--build-manifest", required=True, type=Path)
    parser.add_argument("--build-manifest-sha256", required=True)
    parser.add_argument("--validation-summary", required=True, type=Path)
    parser.add_argument("--validation-summary-sha256", required=True)
    parser.add_argument("--validation-receipt", required=True, type=Path)
    parser.add_argument("--validation-receipt-sha256", required=True)
    parser.add_argument("--build-id", required=True)
    parser.add_argument("--package-version", required=True)
    parser.add_argument("--output-zip", required=True, type=Path)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        result = build_internal_candidate(
            installer=args.installer,
            expected_installer_sha256=args.installer_sha256,
            build_manifest=args.build_manifest,
            expected_build_manifest_sha256=args.build_manifest_sha256,
            validation_summary=args.validation_summary,
            expected_validation_summary_sha256=args.validation_summary_sha256,
            validation_receipt=args.validation_receipt,
            expected_validation_receipt_sha256=args.validation_receipt_sha256,
            output_zip=args.output_zip,
            build_id=args.build_id,
            package_version=args.package_version,
        )
    except CandidateError as error:
        print(
            json.dumps(
                {
                    "status": "HOLD",
                    "error_code": str(error),
                    "production_release_allowed": False,
                },
                sort_keys=True,
            ),
            file=sys.stderr,
        )
        return 2
    print(json.dumps(result, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
