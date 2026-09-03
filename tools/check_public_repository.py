"""Audit a Git snapshot and optional full history before public mirroring."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import subprocess
from pathlib import Path
from typing import Any, Iterable


PROJECT_ROOT = Path(__file__).resolve().parents[1]
MAX_SCANNED_BLOB_BYTES = 16 * 1024 * 1024
PUBLIC_BINARY_REVIEW_PATH = "docs/PUBLIC_BINARY_REVIEW.json"
PUBLIC_MIRROR_MANIFEST_PATH = "PUBLIC_MIRROR_MANIFEST.json"
HISTORY_PATH_UNAVAILABLE = "<git-object-without-tree-path>"
PUBLIC_GENERATED_FILE_SOURCES = {
    ".github/workflows/ci.yml": "tools/templates/public-ci.yml",
    ".github/workflows/pages.yml": "tools/templates/public-pages.yml",
    "README.md": "docs/PUBLIC_REPOSITORY_README.md",
}

FORBIDDEN_TRACKED_PREFIXES = (
    ".venv/",
    ".pytest_cache/",
    ".ruff_cache/",
    ".playwright-cli/",
    "07_results/",
    "10_reports/",
    "deliverables/",
    "desktop/build/",
    "desktop/dist/",
    "evidence/",
    "output/",
    "release/",
    "tmp/",
    "web/node_modules/",
    "web/dist/",
    "web/src-tauri/target/",
    "website/",
)
FORBIDDEN_TRACKED_NAMES = {
    ".env",
    ".env.local",
    ".streamlit/secrets.toml",
}
FORBIDDEN_TRACKED_SUFFIXES = {
    ".db",
    ".log",
    ".mp4",
    ".mov",
    ".pdf",
    ".pptx",
    ".sqlite",
    ".sqlite3",
    ".pem",
    ".key",
    ".p12",
    ".pfx",
    ".wav",
    ".zip",
}

REVIEWED_BINARY_SUFFIXES = {".ico", ".jpeg", ".jpg", ".png", ".webp"}
REVIEWED_BINARY_PREFIXES = (
    "docs/assets/",
    "sample_data/",
    "web/src-tauri/icons/",
)

SECRET_PATTERNS: tuple[tuple[str, re.Pattern[bytes]], ...] = (
    ("github-token", re.compile(rb"\bgh[pousr]_[A-Za-z0-9]{20,}\b")),
    (
        "github-fine-grained-token",
        re.compile(rb"\bgithub_pat_[A-Za-z0-9_]{20,}\b"),
    ),
    ("api-secret", re.compile(rb"\bsk-[A-Za-z0-9_-]{20,}\b")),
    ("huggingface-token", re.compile(rb"\bhf_[A-Za-z0-9]{20,}\b")),
    ("aws-access-key", re.compile(rb"\b(?:AKIA|ASIA)[A-Z0-9]{16}\b")),
    ("slack-token", re.compile(rb"\bxox[baprs]-[A-Za-z0-9-]{10,}\b")),
    (
        "jwt-token",
        re.compile(
            rb"\beyJ[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}\b"
        ),
    ),
    (
        "private-key",
        re.compile(rb"-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----"),
    ),
)
PRIVATE_IDENTITY_PATTERNS: tuple[tuple[str, re.Pattern[bytes]], ...] = (
    (
        "private-email",
        re.compile(rb"(?i)(?<![\\/])\b[A-Z0-9._%+@-]+@[A-Z0-9.-]+\.[A-Z]{2,63}\b"),
    ),
    (
        "private-windows-path",
        re.compile(rb"(?i)\bC:[\\/]Users[\\/][^\\/\s]+(?:[\\/]|\b)"),
    ),
    (
        "private-posix-home",
        re.compile(rb"(?i)(?:^|[\s`'\"(])/(?:home|Users)/[^/\s`'\"<>]+(?:/|$)"),
    ),
    (
        "generic-windows-path",
        re.compile(
            rb"(?i)(?<![A-Za-z0-9+.-])[A-Za-z]:[\\/]+"
            rb"[^\r\n\s`'\"<>|?*]+"
        ),
    ),
    (
        "private-unc-path",
        re.compile(
            rb"(?i)(?<![A-Z0-9._\\-])(?:\\\\){1,2}"
            rb"[A-Z0-9][A-Z0-9._-]{0,252}"
            rb"(?:\\){1,2}[^\\/\s`'\"<>|?*]+"
        ),
    ),
    (
        "private-wsl-path",
        re.compile(
            rb"(?i)(?:^|[\s`'\"(])/(?:mnt/[a-z]|run/desktop/mnt/host/[a-z])(?:/[^\r\n\s`'\"<>]+)+"
        ),
    ),
)
PLACEHOLDER_MARKERS = (
    b"example",
    b"placeholder",
    b"replace_me",
    b"replace-with",
    b"your_api",
    b"not-a-real",
    b"redacted",
    b"authorized-data",
    b"absolute\\path",
    b"absolute/path",
    b"operator-name",
    b"<absolute-path>",
)
GENERIC_PATH_SCANNED_SUFFIXES = {
    ".cff",
    ".cfg",
    ".conf",
    ".csv",
    ".env",
    ".html",
    ".ini",
    ".json",
    ".jsonl",
    ".md",
    ".toml",
    ".txt",
    ".xml",
    ".yaml",
    ".yml",
}
PUBLIC_TEXT_SUFFIXES = GENERIC_PATH_SCANNED_SUFFIXES | {
    "",
    ".bat",
    ".c",
    ".cfg",
    ".cmd",
    ".cpp",
    ".css",
    ".example",
    ".h",
    ".hpp",
    ".js",
    ".lock",
    ".mjs",
    ".ps1",
    ".py",
    ".rs",
    ".sh",
    ".spec",
    ".svg",
    ".toml",
    ".ts",
    ".tsx",
}


class PublicRepositoryValidationError(RuntimeError):
    """Raised when a Git snapshot is not safe to publish."""


def _canonical_json_bytes(value: Any) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")


def _mirror_manifest_violations(
    paths: Iterable[str], *, root: Path | None = None
) -> list[dict[str, str]]:
    project_root = PROJECT_ROOT if root is None else root
    tracked = {path.replace("\\", "/") for path in paths}
    if PUBLIC_MIRROR_MANIFEST_PATH not in tracked:
        return [
            {
                "rule": "public-mirror-manifest-missing",
                "path": PUBLIC_MIRROR_MANIFEST_PATH,
            }
        ]
    manifest_path = project_root / PUBLIC_MIRROR_MANIFEST_PATH
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError):
        return [
            {
                "rule": "public-mirror-manifest-invalid",
                "path": PUBLIC_MIRROR_MANIFEST_PATH,
            }
        ]

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
        return [
            {
                "rule": "public-mirror-manifest-field-drift",
                "path": PUBLIC_MIRROR_MANIFEST_PATH,
            }
        ]

    violations: list[dict[str, str]] = []
    expected_boundary = {
        "schema_version": "visiondata-gate.public-mirror.v2",
        "source_worktree_clean": True,
        "source_history_included": False,
        "private_release_evidence_included": False,
        "customer_data_included": False,
        "personal_data_included": False,
        "tracked_source_only": True,
    }
    if any(manifest.get(key) != value for key, value in expected_boundary.items()):
        violations.append(
            {
                "rule": "public-mirror-boundary-drift",
                "path": PUBLIC_MIRROR_MANIFEST_PATH,
            }
        )
    for field in ("source_commit_oid", "source_tree_oid"):
        value = manifest.get(field)
        if (
            not isinstance(value, str)
            or re.fullmatch(r"[0-9a-f]{40}|[0-9a-f]{64}", value) is None
        ):
            violations.append({"rule": "public-mirror-source-oid-drift", "path": field})

    entries = manifest.get("files")
    if not isinstance(entries, list) or manifest.get("file_count") != len(entries):
        violations.append(
            {
                "rule": "public-mirror-file-count-drift",
                "path": PUBLIC_MIRROR_MANIFEST_PATH,
            }
        )
        return violations

    observed_paths: set[str] = set()
    ordered_paths: list[str] = []
    digest = hashlib.sha256()
    for entry in entries:
        if not isinstance(entry, dict):
            violations.append(
                {
                    "rule": "public-mirror-entry-invalid",
                    "path": PUBLIC_MIRROR_MANIFEST_PATH,
                }
            )
            continue
        relative = entry.get("path")
        expected_entry_fields = {"path", "sha256", "size_bytes"}
        if relative in PUBLIC_GENERATED_FILE_SOURCES:
            expected_entry_fields.add("source")
        if set(entry) != expected_entry_fields or not isinstance(relative, str):
            violations.append(
                {
                    "rule": "public-mirror-entry-field-drift",
                    "path": PUBLIC_MIRROR_MANIFEST_PATH,
                }
            )
            continue
        if relative in observed_paths:
            violations.append(
                {"rule": "public-mirror-path-duplicate", "path": relative}
            )
            continue
        observed_paths.add(relative)
        ordered_paths.append(relative)
        expected_source = PUBLIC_GENERATED_FILE_SOURCES.get(relative)
        if expected_source is not None and entry.get("source") != expected_source:
            rule = {
                "README.md": "public-readme-source-drift",
                ".github/workflows/ci.yml": "public-ci-workflow-source-drift",
                ".github/workflows/pages.yml": "public-pages-workflow-source-drift",
            }[relative]
            violations.append({"rule": rule, "path": relative})
        source = project_root / relative
        if relative not in tracked or not source.is_file():
            violations.append({"rule": "public-mirror-file-missing", "path": relative})
            continue
        data = source.read_bytes()
        if expected_source is not None:
            source_reference = project_root / expected_source
            if not source_reference.is_file() or source_reference.read_bytes() != data:
                violations.append(
                    {"rule": "public-generated-copy-drift", "path": relative}
                )
        observed_sha256 = hashlib.sha256(data).hexdigest()
        if entry.get("size_bytes") != len(data):
            violations.append({"rule": "public-mirror-size-drift", "path": relative})
        if entry.get("sha256") != observed_sha256:
            violations.append({"rule": "public-mirror-sha-drift", "path": relative})
        digest.update(relative.encode("utf-8"))
        digest.update(b"\0")
        digest.update(observed_sha256.encode("ascii"))
        digest.update(b"\0")

    expected_tracked = observed_paths | {PUBLIC_MIRROR_MANIFEST_PATH}
    for relative in sorted(expected_tracked - tracked):
        violations.append({"rule": "public-mirror-file-untracked", "path": relative})
    for relative in sorted(tracked - expected_tracked):
        violations.append({"rule": "public-mirror-unmanifested-file", "path": relative})
    if ordered_paths != sorted(ordered_paths):
        violations.append(
            {
                "rule": "public-mirror-entry-order-drift",
                "path": PUBLIC_MIRROR_MANIFEST_PATH,
            }
        )
    if manifest.get("snapshot_sha256") != digest.hexdigest():
        violations.append(
            {
                "rule": "public-mirror-snapshot-sha-drift",
                "path": PUBLIC_MIRROR_MANIFEST_PATH,
            }
        )
    return violations


def _git(*args: str, text: bool = False) -> str | bytes:
    result = subprocess.run(
        ["git", "--no-replace-objects", *args],
        cwd=PROJECT_ROOT,
        check=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=text,
        encoding="utf-8" if text else None,
    )
    return result.stdout


def _tracked_paths() -> list[str]:
    raw = _git("ls-files", "-z")
    assert isinstance(raw, bytes)
    return sorted(item.decode("utf-8") for item in raw.split(b"\0") if item)


def _contains_forbidden_env_path(parts: list[str]) -> bool:
    last_index = len(parts) - 1
    for index, part in enumerate(parts):
        env_name = part.casefold()
        if env_name == ".env":
            return True
        if env_name.startswith(".env.") and not (
            env_name == ".env.example" and index == last_index
        ):
            return True
    return False


def _path_violations(paths: Iterable[str]) -> list[dict[str, str]]:
    violations: list[dict[str, str]] = []
    for path in paths:
        normalized = path.replace("\\", "/")
        lowered = normalized.casefold()
        forbidden_env = _contains_forbidden_env_path(lowered.split("/"))
        if lowered in FORBIDDEN_TRACKED_NAMES or forbidden_env:
            violations.append({"rule": "forbidden-path", "path": normalized})
        if any(lowered.startswith(prefix) for prefix in FORBIDDEN_TRACKED_PREFIXES):
            violations.append({"rule": "forbidden-prefix", "path": normalized})
        if Path(lowered).suffix in FORBIDDEN_TRACKED_SUFFIXES:
            violations.append({"rule": "forbidden-suffix", "path": normalized})
        suffix = Path(lowered).suffix
        if suffix in REVIEWED_BINARY_SUFFIXES and not any(
            lowered.startswith(prefix) for prefix in REVIEWED_BINARY_PREFIXES
        ):
            violations.append(
                {"rule": "binary-outside-reviewed-prefix", "path": normalized}
            )
    return violations


def _matching_lines(data: bytes, pattern: re.Pattern[bytes]) -> Iterable[bytes]:
    for line in data.splitlines():
        if pattern.search(line):
            yield line


def _is_github_noreply_email(value: bytes) -> bool:
    normalized = value.strip().lower()
    return (
        re.fullmatch(
            rb"[a-z0-9][a-z0-9+._-]*@users\.noreply\.github\.com",
            normalized,
        )
        is not None
    )


def _is_safe_public_email(value: bytes) -> bool:
    normalized = value.strip().lower()
    if normalized.count(b"@") != 1:
        return False
    local_part, domain = normalized.split(b"@", 1)
    if not local_part or not domain:
        return False
    return (
        _is_github_noreply_email(normalized)
        or domain
        in {
            b"example.com",
            b"example.invalid",
        }
        or domain.endswith(b".test")
    )


def _content_violations(
    data: bytes,
    *,
    path: str,
    object_id: str | None = None,
    scan_generic_paths: bool = False,
) -> list[dict[str, str]]:
    violations: list[dict[str, str]] = []
    for rule, pattern in SECRET_PATTERNS:
        for line in _matching_lines(data, pattern):
            unsafe_match_found = any(
                not any(
                    marker in match.group(0).lower() for marker in PLACEHOLDER_MARKERS
                )
                for match in pattern.finditer(line)
            )
            if not unsafe_match_found:
                continue
            entry = {"rule": rule, "path": path}
            if object_id is not None:
                entry["object"] = object_id
            violations.append(entry)
            break
    suffix = Path(path).suffix.casefold()
    for rule, pattern in PRIVATE_IDENTITY_PATTERNS:
        if (
            rule
            in {
                "generic-windows-path",
                "private-unc-path",
                "private-wsl-path",
            }
            and suffix not in GENERIC_PATH_SCANNED_SUFFIXES
            and not scan_generic_paths
        ):
            continue
        for line in _matching_lines(data, pattern):
            matches = list(pattern.finditer(line))
            if rule == "private-email" and not any(
                not _is_safe_public_email(match.group(0)) for match in matches
            ):
                continue
            if rule in {
                "generic-windows-path",
                "private-unc-path",
                "private-wsl-path",
            } and not any(
                not any(
                    marker in match.group(0).lower() for marker in PLACEHOLDER_MARKERS
                )
                for match in matches
            ):
                continue
            entry = {"rule": rule, "path": path}
            if object_id is not None:
                entry["object"] = object_id
            violations.append(entry)
            break
    return violations


def _report_path_and_findings(
    path: str,
    *,
    label: str,
    object_id: str | None = None,
) -> tuple[str, list[dict[str, str]]]:
    normalized = path.replace("\\", "/")
    findings = _content_violations(
        normalized.encode("utf-8"),
        path=label,
        object_id=object_id,
        scan_generic_paths=True,
    )
    return (label if findings else normalized), findings


def _is_redirecting_path(path: Path) -> bool:
    """Treat symlinks, Windows junctions, and unreadable link metadata as unsafe."""

    try:
        if path.is_symlink():
            return True
        is_junction = getattr(path, "is_junction", None)
        return bool(is_junction is not None and is_junction())
    except OSError:
        return True


def _redact_sensitive_violation_paths(
    violations: list[dict[str, str]],
    *,
    label: str,
) -> list[dict[str, str]]:
    sanitized: list[dict[str, str]] = []
    for violation in violations:
        entry = dict(violation)
        path = entry.get("path")
        if isinstance(path, str):
            report_path, findings = _report_path_and_findings(path, label=label)
            if findings:
                entry["path"] = report_path
        sanitized.append(entry)
    return sanitized


def _binary_review_violations(
    paths: Iterable[str], *, root: Path | None = None
) -> list[dict[str, str]]:
    project_root = PROJECT_ROOT if root is None else root
    tracked = {path.replace("\\", "/") for path in paths}
    violations: list[dict[str, str]] = []
    if PUBLIC_BINARY_REVIEW_PATH not in tracked:
        return [
            {
                "rule": "binary-review-manifest-missing",
                "path": PUBLIC_BINARY_REVIEW_PATH,
            }
        ]
    manifest_path = project_root / PUBLIC_BINARY_REVIEW_PATH
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError):
        return [
            {
                "rule": "binary-review-manifest-invalid",
                "path": PUBLIC_BINARY_REVIEW_PATH,
            }
        ]
    if not isinstance(manifest, dict) or set(manifest) != {
        "schema_version",
        "review_basis",
        "reviewed_on",
        "reviewer_identity_included",
        "reviewed_file_count",
        "prohibited_content_checks",
        "files",
        "manifest_sha256",
    }:
        return [
            {"rule": "binary-review-field-drift", "path": PUBLIC_BINARY_REVIEW_PATH}
        ]
    if (
        manifest.get("schema_version") != "visiondata-gate.public-binary-review.v1"
        or manifest.get("review_basis") != "VISUAL_PIXEL_AND_METADATA_INSPECTION"
        or manifest.get("reviewer_identity_included") is not False
    ):
        violations.append(
            {"rule": "binary-review-boundary-drift", "path": PUBLIC_BINARY_REVIEW_PATH}
        )
    stable = dict(manifest)
    expected_manifest_sha256 = stable.pop("manifest_sha256", None)
    observed_manifest_sha256 = hashlib.sha256(_canonical_json_bytes(stable)).hexdigest()
    if expected_manifest_sha256 != observed_manifest_sha256:
        violations.append(
            {"rule": "binary-review-sha-drift", "path": PUBLIC_BINARY_REVIEW_PATH}
        )
    entries = manifest.get("files")
    if not isinstance(entries, list) or manifest.get("reviewed_file_count") != len(
        entries
    ):
        violations.append(
            {"rule": "binary-review-count-drift", "path": PUBLIC_BINARY_REVIEW_PATH}
        )
        return violations
    expected_binary_paths = {
        path
        for path in tracked
        if Path(path).suffix.casefold() in REVIEWED_BINARY_SUFFIXES
    }
    observed_binary_paths: set[str] = set()
    for entry in entries:
        if not isinstance(entry, dict) or set(entry) != {
            "path",
            "sha256",
            "size_bytes",
            "category",
            "review_result",
        }:
            violations.append(
                {"rule": "binary-review-entry-drift", "path": PUBLIC_BINARY_REVIEW_PATH}
            )
            continue
        relative = entry.get("path")
        if not isinstance(relative, str) or relative in observed_binary_paths:
            violations.append(
                {
                    "rule": "binary-review-path-invalid",
                    "path": PUBLIC_BINARY_REVIEW_PATH,
                }
            )
            continue
        observed_binary_paths.add(relative)
        if entry.get("review_result") != "PASS_NO_PRIVATE_CONTENT_OBSERVED":
            violations.append({"rule": "binary-review-not-pass", "path": relative})
        source = project_root / relative
        if relative not in tracked or not source.is_file():
            violations.append({"rule": "binary-review-file-missing", "path": relative})
            continue
        data = source.read_bytes()
        if entry.get("size_bytes") != len(data):
            violations.append({"rule": "binary-review-size-drift", "path": relative})
        if entry.get("sha256") != hashlib.sha256(data).hexdigest():
            violations.append(
                {"rule": "binary-review-file-sha-drift", "path": relative}
            )
    for relative in sorted(expected_binary_paths - observed_binary_paths):
        violations.append({"rule": "binary-missing-semantic-review", "path": relative})
    for relative in sorted(observed_binary_paths - expected_binary_paths):
        violations.append({"rule": "binary-review-untracked-path", "path": relative})
    return violations


def _scan_current(
    paths: list[str], *, root: Path | None = None
) -> tuple[list[dict[str, str]], str]:
    project_root = PROJECT_ROOT if root is None else root
    violations = _path_violations(paths)
    violations.extend(_binary_review_violations(paths, root=project_root))
    digest = hashlib.sha256()
    for relative in paths:
        report_path, path_findings = _report_path_and_findings(
            relative,
            label="tracked-path",
        )
        violations.extend(path_findings)
        path = project_root / relative
        if not path.is_file():
            violations.append({"rule": "tracked-file-missing", "path": report_path})
            continue
        data = path.read_bytes()
        digest.update(relative.encode("utf-8"))
        digest.update(b"\0")
        digest.update(hashlib.sha256(data).digest())
        if len(data) > MAX_SCANNED_BLOB_BYTES:
            violations.append({"rule": "unscanned-oversize-blob", "path": report_path})
            continue
        suffix = path.suffix.casefold()
        if suffix not in REVIEWED_BINARY_SUFFIXES:
            if suffix not in PUBLIC_TEXT_SUFFIXES or b"\0" in data:
                violations.append(
                    {"rule": "unclassified-binary-content", "path": report_path}
                )
                continue
            try:
                data.decode("utf-8")
            except UnicodeDecodeError:
                violations.append({"rule": "non-utf8-public-text", "path": report_path})
                continue
        violations.extend(_content_violations(data, path=report_path))
    return (
        _redact_sensitive_violation_paths(violations, label="tracked-path"),
        digest.hexdigest(),
    )


def _reviewed_binary_records_from_bytes(data: bytes) -> dict[str, str]:
    try:
        manifest = json.loads(data.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError):
        return {}
    if not isinstance(manifest, dict) or set(manifest) != {
        "schema_version",
        "review_basis",
        "reviewed_on",
        "reviewer_identity_included",
        "reviewed_file_count",
        "prohibited_content_checks",
        "files",
        "manifest_sha256",
    }:
        return {}
    if (
        manifest.get("schema_version") != "visiondata-gate.public-binary-review.v1"
        or manifest.get("review_basis") != "VISUAL_PIXEL_AND_METADATA_INSPECTION"
        or manifest.get("reviewer_identity_included") is not False
    ):
        return {}
    stable = dict(manifest)
    expected_manifest_sha256 = stable.pop("manifest_sha256", None)
    if (
        expected_manifest_sha256
        != hashlib.sha256(_canonical_json_bytes(stable)).hexdigest()
    ):
        return {}
    entries = manifest.get("files")
    if not isinstance(entries, list) or manifest.get("reviewed_file_count") != len(
        entries
    ):
        return {}
    records: dict[str, str] = {}
    for entry in entries:
        if not isinstance(entry, dict) or set(entry) != {
            "path",
            "sha256",
            "size_bytes",
            "category",
            "review_result",
        }:
            return {}
        path = entry.get("path")
        sha256 = entry.get("sha256")
        normalized = path.replace("\\", "/") if isinstance(path, str) else None
        if (
            normalized is None
            or normalized in records
            or not isinstance(sha256, str)
            or re.fullmatch(r"[0-9a-f]{64}", sha256) is None
            or not isinstance(entry.get("size_bytes"), int)
            or entry["size_bytes"] < 0
            or not isinstance(entry.get("category"), str)
            or entry.get("review_result") != "PASS_NO_PRIVATE_CONTENT_OBSERVED"
        ):
            return {}
        records[normalized] = sha256
    return records


def _reviewed_binary_records(*, root: Path | None = None) -> dict[str, str]:
    project_root = PROJECT_ROOT if root is None else root
    try:
        data = (project_root / PUBLIC_BINARY_REVIEW_PATH).read_bytes()
    except OSError:
        return {}
    return _reviewed_binary_records_from_bytes(data)


def _reviewed_binary_history_records(
    objects: dict[str, tuple[str, ...]],
    *,
    current_records: dict[str, str] | None = None,
) -> dict[str, frozenset[str]]:
    """Collect every SHA explicitly approved by a valid review manifest revision."""

    approved: dict[str, set[str]] = {}
    seed = _reviewed_binary_records() if current_records is None else current_records
    for path, sha256 in seed.items():
        approved.setdefault(path, set()).add(sha256)

    for object_id, paths in objects.items():
        if PUBLIC_BINARY_REVIEW_PATH not in paths:
            continue
        raw = _git("cat-file", "blob", object_id)
        assert isinstance(raw, bytes)
        for path, sha256 in _reviewed_binary_records_from_bytes(raw).items():
            approved.setdefault(path, set()).add(sha256)

    return {
        path: frozenset(sorted(digests)) for path, digests in sorted(approved.items())
    }


def _history_entry(rule: str, *, path: str, object_id: str) -> dict[str, str]:
    return {"rule": rule, "path": path, "object": object_id}


def _historical_path_policy(
    *,
    path: str,
    object_id: str,
) -> tuple[str, list[dict[str, str]]]:
    normalized = path.replace("\\", "/")
    report_path, content_findings = _report_path_and_findings(
        normalized,
        label="historical-path",
        object_id=object_id,
    )
    structural_findings = [
        {**item, "path": report_path, "object": object_id}
        for item in _path_violations([normalized])
    ]
    return report_path, structural_findings + content_findings


def _historical_path_violations(*, path: str, object_id: str) -> list[dict[str, str]]:
    return _historical_path_policy(path=path, object_id=object_id)[1]


def _historical_blob_violations(
    data: bytes,
    *,
    path: str,
    object_id: str,
    reviewed_binaries: dict[str, str | frozenset[str]],
) -> list[dict[str, str]]:
    normalized = path.replace("\\", "/")
    report_path, violations = _historical_path_policy(
        path=normalized,
        object_id=object_id,
    )
    if len(data) > MAX_SCANNED_BLOB_BYTES:
        violations.append(
            _history_entry(
                "unscanned-oversize-history-blob",
                path=report_path,
                object_id=object_id,
            )
        )
        return violations

    suffix = Path(normalized).suffix.casefold()
    if suffix in REVIEWED_BINARY_SUFFIXES:
        observed_sha256 = hashlib.sha256(data).hexdigest()
        expected_sha256 = reviewed_binaries.get(normalized)
        if expected_sha256 is None:
            violations.append(
                _history_entry(
                    "history-binary-missing-semantic-review",
                    path=report_path,
                    object_id=object_id,
                )
            )
        else:
            approved_sha256 = (
                {expected_sha256}
                if isinstance(expected_sha256, str)
                else expected_sha256
            )
        if expected_sha256 is not None and observed_sha256 not in approved_sha256:
            violations.append(
                _history_entry(
                    "history-binary-sha-drift",
                    path=report_path,
                    object_id=object_id,
                )
            )
    else:
        if suffix not in PUBLIC_TEXT_SUFFIXES or b"\0" in data:
            violations.append(
                _history_entry(
                    "unclassified-history-binary-content",
                    path=report_path,
                    object_id=object_id,
                )
            )
            return violations
        try:
            data.decode("utf-8")
        except UnicodeDecodeError:
            violations.append(
                _history_entry(
                    "non-utf8-history-text",
                    path=report_path,
                    object_id=object_id,
                )
            )
            return violations

    violations.extend(_content_violations(data, path=report_path, object_id=object_id))
    return violations


def _read_cat_file_payload(stream: Any, size: int) -> bytes | None:
    if size > MAX_SCANNED_BLOB_BYTES:
        remaining = size
        while remaining:
            chunk = stream.read(min(remaining, 1024 * 1024))
            if not chunk:
                raise PublicRepositoryValidationError(
                    "git cat-file ended before an oversized object was drained"
                )
            remaining -= len(chunk)
        terminator = stream.read(1)
        if terminator != b"\n":
            raise PublicRepositoryValidationError(
                "git cat-file returned an invalid oversized-object terminator"
            )
        return None
    data = stream.read(size)
    terminator = stream.read(1)
    if len(data) != size or terminator != b"\n":
        raise PublicRepositoryValidationError(
            "git cat-file returned a truncated object without publishing contents"
        )
    return data


def _reachable_object_ids() -> tuple[str, ...]:
    raw = _git(
        "rev-list",
        "--objects",
        "--all",
        "--no-object-names",
        "-z",
    )
    assert isinstance(raw, bytes)
    object_ids: set[str] = set()
    for object_bytes in raw.split(b"\0"):
        if not object_bytes:
            continue
        if re.fullmatch(rb"[0-9a-f]{40,64}", object_bytes) is None:
            raise PublicRepositoryValidationError(
                "Git history contains an invalid reachable object identifier"
            )
        object_ids.add(object_bytes.decode("ascii"))
    return tuple(sorted(object_ids))


def _history_inventory() -> tuple[
    dict[str, tuple[str, ...]],
    list[dict[str, str]],
]:
    raw = _git(
        "log",
        "--all",
        "--root",
        "-m",
        "--raw",
        "-z",
        "--format=",
        "--no-abbrev",
        "--no-renames",
    )
    assert isinstance(raw, bytes)
    objects: dict[str, set[str]] = {}
    detached_path_violations: list[dict[str, str]] = []
    fields = raw.split(b"\0")
    index = 0
    while index < len(fields):
        metadata = fields[index]
        index += 1
        if not metadata:
            continue
        if not metadata.startswith(b":") or index >= len(fields):
            raise PublicRepositoryValidationError(
                "Git history returned an invalid raw diff record"
            )
        path_bytes = fields[index]
        index += 1
        parts = metadata[1:].split()
        if len(parts) != 5:
            raise PublicRepositoryValidationError(
                "Git history returned an unsupported raw diff record"
            )
        old_mode, new_mode, old_object, new_object, _ = parts
        try:
            path = path_bytes.decode("utf-8").replace("\\", "/")
        except UnicodeDecodeError as exc:
            raise PublicRepositoryValidationError(
                "Git history contains a non-UTF-8 object path"
            ) from exc
        for mode, object_bytes in (
            (old_mode, old_object),
            (new_mode, new_object),
        ):
            if set(object_bytes) == {ord("0")}:
                continue
            try:
                object_id = object_bytes.decode("ascii")
            except UnicodeDecodeError as exc:
                raise PublicRepositoryValidationError(
                    "Git history contains a non-ASCII object identifier"
                ) from exc
            if mode == b"160000":
                report_path, path_violations = _historical_path_policy(
                    path=path,
                    object_id=object_id,
                )
                detached_path_violations.extend(path_violations)
                detached_path_violations.append(
                    _history_entry(
                        "unscanned-history-gitlink",
                        path=report_path,
                        object_id=object_id,
                    )
                )
                continue
            objects.setdefault(object_id, set()).add(path)

    for object_id in _reachable_object_ids():
        objects.setdefault(object_id, set())

    for paths in objects.values():
        if not paths:
            paths.add(HISTORY_PATH_UNAVAILABLE)
    return (
        {
            object_id: tuple(sorted(paths))
            for object_id, paths in sorted(objects.items())
        },
        detached_path_violations,
    )


def _history_objects() -> dict[str, tuple[str, ...]]:
    return _history_inventory()[0]


def _scan_history_blobs(
    objects: dict[str, tuple[str, ...]],
    *,
    reviewed_binaries: dict[str, str | frozenset[str]] | None = None,
) -> list[dict[str, str]]:
    violations: list[dict[str, str]] = []
    approved_binaries = (
        _reviewed_binary_history_records(objects)
        if reviewed_binaries is None
        else reviewed_binaries
    )
    process = subprocess.Popen(
        ["git", "--no-replace-objects", "cat-file", "--batch"],
        cwd=PROJECT_ROOT,
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    assert process.stdin is not None and process.stdout is not None
    try:
        for object_id, paths in objects.items():
            process.stdin.write(object_id.encode("ascii") + b"\n")
            process.stdin.flush()
            header = process.stdout.readline().decode("ascii", errors="replace").strip()
            parts = header.split()
            if len(parts) != 3:
                raise PublicRepositoryValidationError(
                    f"unexpected git cat-file header for {object_id}"
                )
            _, kind, raw_size = parts
            size = int(raw_size)
            data = _read_cat_file_payload(process.stdout, size)
            if kind != "blob":
                continue
            if HISTORY_PATH_UNAVAILABLE in paths:
                violations.append(
                    _history_entry(
                        "history-blob-without-tree-path",
                        path=HISTORY_PATH_UNAVAILABLE,
                        object_id=object_id,
                    )
                )
            if data is None:
                for path in paths:
                    report_path, path_violations = _historical_path_policy(
                        path=path,
                        object_id=object_id,
                    )
                    violations.extend(path_violations)
                    violations.append(
                        _history_entry(
                            "unscanned-oversize-history-blob",
                            path=report_path,
                            object_id=object_id,
                        )
                    )
                continue
            for path in paths:
                violations.extend(
                    _historical_blob_violations(
                        data,
                        path=path,
                        object_id=object_id,
                        reviewed_binaries=approved_binaries,
                    )
                )
    finally:
        process.stdin.close()
        process.wait(timeout=30)
    if process.returncode != 0:
        raise PublicRepositoryValidationError(
            "git cat-file failed without publishing local diagnostics"
        )
    return violations


def _identity_metadata_violations(
    value: bytes,
    *,
    role: str,
    object_id: str,
    object_kind: str,
) -> list[dict[str, str]]:
    violations: list[dict[str, str]] = []
    match = re.fullmatch(rb"(.+) <([^<>]+)> [0-9]+ [+-][0-9]{4}", value)
    if match is None:
        return [
            {
                "rule": f"{object_kind}-{role}-identity-invalid",
                "object": object_id,
            }
        ]
    display_name, email = match.groups()
    violations.extend(
        _content_violations(
            display_name,
            path=f"{object_kind}-{role}-display-name",
            object_id=object_id,
            scan_generic_paths=True,
        )
    )
    normalized_email = email.strip().lower()
    violations.extend(
        _content_violations(
            normalized_email,
            path=f"{object_kind}-{role}-email",
            object_id=object_id,
        )
    )
    if not normalized_email:
        violations.append({"rule": f"{role}-email-missing", "object": object_id})
    elif not _is_github_noreply_email(normalized_email):
        violations.append({"rule": f"{role}-email-not-noreply", "object": object_id})
    return violations


def _revision_metadata_violations(
    data: bytes,
    *,
    object_id: str,
    object_kind: str,
) -> list[dict[str, str]]:
    if len(data) > MAX_SCANNED_BLOB_BYTES:
        return [
            {
                "rule": f"unscanned-oversize-{object_kind}-metadata",
                "object": object_id,
            }
        ]
    if b"\0" in data:
        return [
            {
                "rule": f"nul-in-{object_kind}-metadata",
                "object": object_id,
            }
        ]
    try:
        data.decode("utf-8")
    except UnicodeDecodeError:
        return [
            {
                "rule": f"non-utf8-{object_kind}-metadata",
                "object": object_id,
            }
        ]
    header, separator, message = data.partition(b"\n\n")
    if not separator:
        return [{"rule": f"{object_kind}-metadata-invalid", "object": object_id}]

    header_lines = header.splitlines()
    identity_roles = ("author", "committer") if object_kind == "commit" else ("tagger",)
    violations = _content_violations(
        header,
        path=f"{object_kind}-header",
        object_id=object_id,
        scan_generic_paths=True,
    )
    for role in identity_roles:
        prefix = role.encode("ascii") + b" "
        values = [
            line[len(prefix) :] for line in header_lines if line.startswith(prefix)
        ]
        if len(values) != 1:
            violations.append(
                {
                    "rule": f"{object_kind}-{role}-identity-invalid",
                    "object": object_id,
                }
            )
            continue
        violations.extend(
            _identity_metadata_violations(
                values[0],
                role=role,
                object_id=object_id,
                object_kind=object_kind,
            )
        )

    if object_kind == "tag":
        tag_names = [line[4:] for line in header_lines if line.startswith(b"tag ")]
        if len(tag_names) != 1:
            violations.append({"rule": "tag-name-invalid", "object": object_id})
        else:
            violations.extend(
                _content_violations(
                    tag_names[0],
                    path="tag-name",
                    object_id=object_id,
                    scan_generic_paths=True,
                )
            )
    violations.extend(
        _content_violations(
            message,
            path=f"{object_kind}-message",
            object_id=object_id,
            scan_generic_paths=True,
        )
    )
    return violations


def _scan_ref_names() -> list[dict[str, str]]:
    raw = _git(
        "for-each-ref",
        "--include-root-refs",
        "--format=%(refname)%00",
    )
    assert isinstance(raw, bytes)
    violations: list[dict[str, str]] = []
    for record in raw.split(b"\0"):
        ref_name = record.strip(b"\r\n")
        if not ref_name:
            continue
        try:
            ref_name.decode("utf-8")
        except UnicodeDecodeError:
            violations.append({"rule": "non-utf8-git-ref-name", "path": "git-ref-name"})
            continue
        if ref_name.startswith(b"refs/replace/"):
            violations.append(
                {"rule": "git-replace-ref-present", "path": "git-ref-name"}
            )
        violations.extend(_content_violations(ref_name, path="git-ref-name"))
    return violations


def _history_environment_violations() -> list[dict[str, str]]:
    violations: list[dict[str, str]] = []
    shallow = _git("rev-parse", "--is-shallow-repository", text=True)
    assert isinstance(shallow, str)
    if shallow.strip().casefold() != "false":
        violations.append({"rule": "shallow-history-not-complete"})

    graft_location = _git("rev-parse", "--git-path", "info/grafts", text=True)
    assert isinstance(graft_location, str)
    graft_path = Path(graft_location.strip())
    if not graft_path.is_absolute():
        graft_path = PROJECT_ROOT / graft_path
    try:
        graft_present = graft_path.is_file() and graft_path.stat().st_size > 0
    except OSError:
        graft_present = True
    if graft_present:
        violations.append({"rule": "git-grafts-present"})
    return violations


def _ref_snapshot_sha256() -> str:
    raw = _git(
        "for-each-ref",
        "--include-root-refs",
        "--format=%(refname)%00%(objectname)%00%(objecttype)%00",
    )
    assert isinstance(raw, bytes)
    return hashlib.sha256(raw).hexdigest()


def _revision_metadata_objects() -> list[tuple[str, str]]:
    objects: list[tuple[str, str]] = []
    process = subprocess.Popen(
        [
            "git",
            "--no-replace-objects",
            "cat-file",
            "--batch-check=%(objectname) %(objecttype)",
        ],
        cwd=PROJECT_ROOT,
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    assert process.stdin is not None and process.stdout is not None
    try:
        for object_id in _reachable_object_ids():
            process.stdin.write(object_id.encode("ascii") + b"\n")
            process.stdin.flush()
            line = process.stdout.readline().decode("ascii", errors="replace").strip()
            parts = line.split()
            if len(parts) != 2 or parts[0] != object_id:
                raise PublicRepositoryValidationError(
                    f"unexpected git cat-file type header for {object_id}"
                )
            object_kind = parts[1]
            if object_kind in {"commit", "tag"}:
                objects.append((object_id, object_kind))
    finally:
        process.stdin.close()
        process.wait(timeout=30)
    if process.returncode != 0:
        raise PublicRepositoryValidationError(
            "git cat-file type scan failed without publishing local diagnostics"
        )
    return objects


def _scan_commit_identities() -> list[dict[str, str]]:
    violations: list[dict[str, str]] = []
    process = subprocess.Popen(
        ["git", "--no-replace-objects", "cat-file", "--batch"],
        cwd=PROJECT_ROOT,
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    assert process.stdin is not None and process.stdout is not None
    try:
        for object_id, expected_kind in _revision_metadata_objects():
            process.stdin.write(object_id.encode("ascii") + b"\n")
            process.stdin.flush()
            header = process.stdout.readline().decode("ascii", errors="replace").strip()
            parts = header.split()
            if len(parts) != 3:
                raise PublicRepositoryValidationError(
                    f"unexpected git cat-file metadata header for {object_id}"
                )
            _, observed_kind, raw_size = parts
            size = int(raw_size)
            data = _read_cat_file_payload(process.stdout, size)
            if observed_kind != expected_kind:
                raise PublicRepositoryValidationError(
                    f"unexpected Git object kind for {object_id}"
                )
            if data is None:
                violations.append(
                    {
                        "rule": f"unscanned-oversize-{expected_kind}-metadata",
                        "object": object_id,
                    }
                )
                continue
            violations.extend(
                _revision_metadata_violations(
                    data,
                    object_id=object_id,
                    object_kind=expected_kind,
                )
            )
    finally:
        process.stdin.close()
        process.wait(timeout=30)
    if process.returncode != 0:
        raise PublicRepositoryValidationError(
            "git cat-file metadata scan failed without publishing local diagnostics"
        )
    return violations


def validate(*, history: bool) -> dict[str, Any]:
    paths = _tracked_paths()
    current_violations, tree_manifest_sha256 = _scan_current(paths)
    current_violations.extend(_mirror_manifest_violations(paths))
    current_violations = _redact_sensitive_violation_paths(
        current_violations,
        label="tracked-path",
    )
    history_violations: list[dict[str, str]] = []
    history_object_count = 0
    if history:
        history_environment_violations = _history_environment_violations()
        history_violations.extend(history_environment_violations)
        if not history_environment_violations:
            ref_snapshot_before = _ref_snapshot_sha256()
            objects, detached_path_violations = _history_inventory()
            history_object_count = len(objects)
            history_violations.extend(detached_path_violations)
            history_violations.extend(_scan_history_blobs(objects))
            history_violations.extend(_scan_commit_identities())
            history_violations.extend(_scan_ref_names())
            if _ref_snapshot_sha256() != ref_snapshot_before:
                history_violations.append({"rule": "git-ref-snapshot-drift"})
    violations = current_violations + history_violations
    if violations:
        raise PublicRepositoryValidationError(
            json.dumps(
                {
                    "status": "HOLD_PUBLICATION_PRIVACY",
                    "tracked_file_count": len(paths),
                    "history_object_count": history_object_count,
                    "violation_count": len(violations),
                    "violations": violations[:100],
                    "values_disclosed": False,
                },
                ensure_ascii=False,
                indent=2,
            )
        )
    return {
        "status": "PASS_PUBLIC_REPOSITORY_PRIVACY",
        "tracked_file_count": len(paths),
        "history_checked": history,
        "history_object_count": history_object_count,
        "tree_manifest_sha256": tree_manifest_sha256,
        "values_disclosed": False,
    }


def validate_snapshot(root: Path) -> dict[str, Any]:
    candidate = root.expanduser()
    if _is_redirecting_path(candidate):
        raise PublicRepositoryValidationError(
            json.dumps(
                {
                    "status": "HOLD_PUBLICATION_PRIVACY",
                    "reason": "snapshot root is a symbolic link",
                    "path": "snapshot-root",
                    "values_disclosed": False,
                },
                ensure_ascii=False,
                indent=2,
            )
        )
    try:
        resolved = candidate.resolve()
    except (OSError, RuntimeError) as error:
        raise PublicRepositoryValidationError(
            json.dumps(
                {
                    "status": "HOLD_PUBLICATION_PRIVACY",
                    "reason": "snapshot root could not be resolved",
                    "values_disclosed": False,
                },
                ensure_ascii=False,
                indent=2,
            )
        ) from error
    if not resolved.is_dir():
        raise PublicRepositoryValidationError(
            json.dumps(
                {
                    "status": "HOLD_PUBLICATION_PRIVACY",
                    "reason": "snapshot root is missing or is not a directory",
                    "values_disclosed": False,
                },
                ensure_ascii=False,
                indent=2,
            )
        )
    paths: list[str] = []
    pending = [resolved]
    while pending:
        directory = pending.pop()
        try:
            entries = sorted(directory.iterdir(), key=lambda item: item.name)
        except OSError as error:
            raise PublicRepositoryValidationError(
                json.dumps(
                    {
                        "status": "HOLD_PUBLICATION_PRIVACY",
                        "reason": "snapshot could not be enumerated",
                        "values_disclosed": False,
                    },
                    ensure_ascii=False,
                    indent=2,
                )
            ) from error
        child_directories: list[Path] = []
        for path in entries:
            if _is_redirecting_path(path):
                relative = path.relative_to(resolved).as_posix()
                report_path, _ = _report_path_and_findings(
                    relative,
                    label="tracked-path",
                )
                raise PublicRepositoryValidationError(
                    json.dumps(
                        {
                            "status": "HOLD_PUBLICATION_PRIVACY",
                            "reason": "snapshot contains a symbolic link",
                            "path": report_path,
                            "values_disclosed": False,
                        },
                        ensure_ascii=False,
                        indent=2,
                    )
                )
            if path.is_dir():
                child_directories.append(path)
                continue
            if path.is_file():
                paths.append(path.relative_to(resolved).as_posix())
                continue
            relative = path.relative_to(resolved).as_posix()
            report_path, _ = _report_path_and_findings(
                relative,
                label="tracked-path",
            )
            raise PublicRepositoryValidationError(
                json.dumps(
                    {
                        "status": "HOLD_PUBLICATION_PRIVACY",
                        "reason": "snapshot contains an unsupported entry",
                        "path": report_path,
                        "values_disclosed": False,
                    },
                    ensure_ascii=False,
                    indent=2,
                )
            )
        pending.extend(reversed(child_directories))

    current_violations, tree_manifest_sha256 = _scan_current(paths, root=resolved)
    current_violations.extend(_mirror_manifest_violations(paths, root=resolved))
    current_violations = _redact_sensitive_violation_paths(
        current_violations,
        label="tracked-path",
    )
    if current_violations:
        raise PublicRepositoryValidationError(
            json.dumps(
                {
                    "status": "HOLD_PUBLICATION_PRIVACY",
                    "tracked_file_count": len(paths),
                    "history_object_count": 0,
                    "violation_count": len(current_violations),
                    "violations": current_violations[:100],
                    "values_disclosed": False,
                },
                ensure_ascii=False,
                indent=2,
            )
        )
    return {
        "status": "PASS_PUBLIC_REPOSITORY_PRIVACY",
        "tracked_file_count": len(paths),
        "history_checked": False,
        "history_object_count": 0,
        "tree_manifest_sha256": tree_manifest_sha256,
        "values_disclosed": False,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--history", action="store_true")
    parser.add_argument("--snapshot-root", type=Path)
    args = parser.parse_args()
    if args.snapshot_root is not None and args.history:
        parser.error("--history cannot be combined with --snapshot-root")
    try:
        result = (
            validate_snapshot(args.snapshot_root)
            if args.snapshot_root is not None
            else validate(history=args.history)
        )
    except PublicRepositoryValidationError as error:
        print(str(error))
        return 1
    except Exception:
        print(
            json.dumps(
                {
                    "status": "HOLD_PUBLICATION_PRIVACY",
                    "reason": (
                        "public repository privacy check failed without publishing "
                        "local diagnostics"
                    ),
                    "values_disclosed": False,
                },
                ensure_ascii=False,
                indent=2,
            )
        )
        return 1
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
