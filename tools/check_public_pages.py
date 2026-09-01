"""Fail-closed checks for the privacy-safe GitHub Pages projection."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
from pathlib import Path
from typing import Any


PROJECT_ROOT = Path(__file__).resolve().parents[1]
PUBLIC_MANIFEST = PROJECT_ROOT / "web" / "public" / "public-replay.v1.json"

PROHIBITED_TEXT_PATTERNS: tuple[tuple[str, re.Pattern[str]], ...] = (
    ("windows-user-path", re.compile(r"(?i)\bC:[\\/]Users[\\/][^\\/\s]+")),
    (
        "private-drive-path",
        re.compile(r"(?i)(?<![A-Za-z0-9+.-])[A-Za-z]:[\\/]+[^\r\n`'\"<>|?*]+"),
    ),
    ("github-token", re.compile(r"\bgh[pousr]_[A-Za-z0-9]{20,}\b")),
    (
        "github-fine-grained-token",
        re.compile(r"\bgithub_pat_[A-Za-z0-9_]{20,}\b"),
    ),
    ("generic-api-secret", re.compile(r"\bsk-[A-Za-z0-9_-]{20,}\b")),
    ("huggingface-token", re.compile(r"\bhf_[A-Za-z0-9]{20,}\b")),
    ("aws-access-key", re.compile(r"\b(?:AKIA|ASIA)[A-Z0-9]{16}\b")),
    ("slack-token", re.compile(r"\bxox[baprs]-[A-Za-z0-9-]{10,}\b")),
    (
        "jwt-token",
        re.compile(
            r"\beyJ[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}\b"
        ),
    ),
    ("private-key", re.compile(r"-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----")),
    (
        "private-email",
        re.compile(r"(?i)\b[A-Z0-9._%+@-]+@[A-Z0-9.-]+\.[A-Z]{2,63}\b"),
    ),
)

GITHUB_NOREPLY_EMAIL = re.compile(
    r"(?i)[A-Z0-9][A-Z0-9+._-]*@users\.noreply\.github\.com"
)

PROHIBITED_DIST_SUFFIXES = {
    ".map",
    ".env",
    ".db",
    ".sqlite",
    ".sqlite3",
    ".log",
    ".pem",
    ".key",
    ".p12",
    ".pfx",
}
PROHIBITED_DIST_RUNTIME_PATTERNS: tuple[tuple[str, re.Pattern[str]], ...] = (
    ("local-api-route", re.compile(r"/v1/")),
    ("reviewer-api-route", re.compile(r"/api/reviewer")),
    (
        "write-request-method",
        re.compile(r"\bmethod\s*:\s*[\"'](?:POST|PUT|PATCH|DELETE)[\"']"),
    ),
)


class PublicPagesValidationError(RuntimeError):
    """Raised when the public projection violates its frozen contract."""


def _canonical_jcs_subset(value: Any) -> bytes:
    """Encode this manifest's JSON domain using the RFC 8785-compatible subset."""

    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise PublicPagesValidationError(message)


def _is_redirecting_path(path: Path) -> bool:
    """Reject link-like entries without disclosing their resolved targets."""

    try:
        if path.is_symlink():
            return True
        is_junction = getattr(path, "is_junction", None)
        return bool(is_junction is not None and is_junction())
    except OSError:
        return True


def _require_exact_keys(value: Any, expected: set[str], label: str) -> None:
    _require(isinstance(value, dict), f"{label} must be an object")
    _require(set(value) == expected, f"{label} field set drift")


def _scan_text(label: str, text: str) -> list[str]:
    violations: list[str] = []
    for rule, pattern in PROHIBITED_TEXT_PATTERNS:
        matches = list(pattern.finditer(text))
        if rule == "private-email":
            matches = [
                match
                for match in matches
                if GITHUB_NOREPLY_EMAIL.fullmatch(match.group(0)) is None
            ]
        if matches:
            violations.append(f"{label}:{rule}")
    return violations


def _scan_runtime_surfaces(label: str, text: str) -> list[str]:
    return [
        f"{label}:{rule}"
        for rule, pattern in PROHIBITED_DIST_RUNTIME_PATTERNS
        if pattern.search(text)
    ]


def validate_manifest() -> dict[str, Any]:
    manifest = json.loads(PUBLIC_MANIFEST.read_text(encoding="utf-8"))
    _require_exact_keys(
        manifest,
        {
            "schema_version",
            "source_mode",
            "release_status",
            "evidence_boundary",
            "case",
            "triggering_evidence",
            "worker_selection",
            "competing_hypotheses",
            "missing_evidence",
            "phases",
            "lineage",
            "demo_controls",
            "manifest_sha256",
        },
        "public replay manifest",
    )
    _require(
        manifest.get("schema_version") == "visiondata-gate.public-replay.v1",
        "public replay schema drift",
    )
    _require(
        manifest.get("source_mode") == "PUBLIC_SYNTHETIC_REPLAY",
        "public replay source mode drift",
    )
    release = manifest.get("release_status", {})
    _require_exact_keys(
        release,
        {
            "local_candidate",
            "official_submission",
            "official_evaluation",
            "production_release_allowed",
        },
        "release_status",
    )
    _require(
        release.get("official_submission") == "PENDING", "official submission drift"
    )
    _require(
        release.get("official_evaluation") == "NOT_EVALUATED",
        "official evaluation drift",
    )
    _require(
        release.get("production_release_allowed") is False,
        "public replay must never allow production release",
    )
    evidence_boundary = manifest.get("evidence_boundary", {})
    _require_exact_keys(
        evidence_boundary,
        {
            "baseline_tag",
            "baseline_claim",
            "release_artifacts_included",
            "public_snapshot_attestation",
        },
        "evidence_boundary",
    )
    _require(
        evidence_boundary
        == {
            "baseline_tag": "v0.1.0-goai-rc3-r3",
            "baseline_claim": "PASS_LOCAL_RC3_RELEASE_CANDIDATE",
            "release_artifacts_included": False,
            "public_snapshot_attestation": "NOT_ISSUED",
        },
        "public replay evidence boundary drift",
    )
    controls = manifest.get("demo_controls", {})
    expected_controls = {
        "read_only": True,
        "backend_connected": False,
        "api_key_input_enabled": False,
        "customer_data_included": False,
        "personal_data_included": False,
        "raw_industrial_images_included": False,
    }
    _require(controls == expected_controls, "public replay control set drift")
    _require_exact_keys(
        manifest.get("case", {}),
        {
            "case_id",
            "title",
            "dataset",
            "input_scope",
            "initial_disposition",
            "child_disposition",
            "human_authority_required",
        },
        "case",
    )
    worker_selection = manifest.get("worker_selection", {})
    _require_exact_keys(
        worker_selection,
        {"budget", "selected", "rejected"},
        "worker_selection",
    )
    _require_exact_keys(
        worker_selection.get("budget", {}),
        {"selected", "maximum", "model_call_count"},
        "worker_selection.budget",
    )
    for index, item in enumerate(manifest.get("triggering_evidence", [])):
        _require_exact_keys(
            item,
            {"id", "signal", "measurement", "threshold", "effect"},
            f"triggering_evidence[{index}]",
        )
    for index, item in enumerate(worker_selection.get("selected", [])):
        _require_exact_keys(
            item,
            {"worker", "reason", "triggering_evidence_id"},
            f"worker_selection.selected[{index}]",
        )
    for index, item in enumerate(worker_selection.get("rejected", [])):
        _require_exact_keys(
            item,
            {"worker", "reason"},
            f"worker_selection.rejected[{index}]",
        )
    for index, item in enumerate(manifest.get("competing_hypotheses", [])):
        _require_exact_keys(
            item,
            {"id", "statement", "state"},
            f"competing_hypotheses[{index}]",
        )
    for collection in ("phases", "lineage"):
        for index, item in enumerate(manifest.get(collection, [])):
            _require_exact_keys(
                item,
                {"id", "label", "state"},
                f"{collection}[{index}]",
            )
    _require(
        manifest.get("worker_selection", {}).get("budget", {}).get("model_call_count")
        == 0,
        "public replay must not claim or perform model calls",
    )
    _require(
        manifest.get("missing_evidence"),
        "public replay must preserve explicit missing evidence",
    )

    expected_digest = manifest.get("manifest_sha256")
    _require(
        isinstance(expected_digest, str)
        and re.fullmatch(r"[0-9a-f]{64}", expected_digest) is not None,
        "invalid manifest_sha256",
    )
    stable = dict(manifest)
    stable.pop("manifest_sha256", None)
    observed_digest = hashlib.sha256(_canonical_jcs_subset(stable)).hexdigest()
    _require(observed_digest == expected_digest, "public replay JCS SHA-256 drift")

    violations = _scan_text(
        PUBLIC_MANIFEST.relative_to(PROJECT_ROOT).as_posix(),
        PUBLIC_MANIFEST.read_text(encoding="utf-8"),
    )
    _require(not violations, f"private material in public manifest: {violations}")
    return {
        "schema_version": manifest["schema_version"],
        "source_mode": manifest["source_mode"],
        "manifest_sha256": expected_digest,
        "production_release_allowed": False,
    }


def validate_dist(dist: Path) -> dict[str, Any]:
    candidate = dist.expanduser()
    _require(
        not _is_redirecting_path(candidate),
        "public Pages dist must not be a symbolic link",
    )
    try:
        resolved = candidate.resolve()
    except (OSError, RuntimeError) as error:
        raise PublicPagesValidationError(
            "public Pages dist could not be resolved"
        ) from error
    _require(resolved.is_dir(), "public Pages dist not found")
    index = resolved / "index.html"
    copied_manifest = resolved / PUBLIC_MANIFEST.name
    _require(
        not _is_redirecting_path(index),
        "dist/index.html must not be a symbolic link",
    )
    _require(
        not _is_redirecting_path(copied_manifest),
        "dist public replay manifest must not be a symbolic link",
    )
    _require(index.is_file(), "dist/index.html missing")
    _require(copied_manifest.is_file(), "dist public replay manifest missing")
    _require(
        copied_manifest.read_bytes() == PUBLIC_MANIFEST.read_bytes(),
        "dist public replay manifest differs from source",
    )

    text_parts: list[str] = []
    violations: list[str] = []
    runtime_violations: list[str] = []
    file_count = 0
    pending = [resolved]
    while pending:
        directory = pending.pop()
        try:
            entries = sorted(directory.iterdir(), key=lambda item: item.name)
        except OSError as error:
            raise PublicPagesValidationError(
                "public Pages dist could not be enumerated"
            ) from error
        child_directories: list[Path] = []
        for path in entries:
            relative = path.relative_to(resolved).as_posix()
            path_violations = _scan_text("dist-path", relative)
            report_label = "dist-path" if path_violations else relative
            _require(
                not _is_redirecting_path(path),
                f"public Pages dist contains a symbolic link: {report_label}",
            )
            if path.is_dir():
                violations.extend(path_violations)
                child_directories.append(path)
                continue
            _require(
                path.is_file(),
                f"unsupported public Pages dist entry: {report_label}",
            )
            file_count += 1
            violations.extend(path_violations)
            _require(
                path.suffix.lower() not in PROHIBITED_DIST_SUFFIXES,
                f"prohibited public artifact: {report_label}",
            )
            if path.suffix.lower() not in {
                ".html",
                ".js",
                ".css",
                ".json",
                ".svg",
                ".txt",
            }:
                continue
            text = path.read_text(encoding="utf-8")
            text_parts.append(text)
            violations.extend(_scan_text(report_label, text))
            runtime_violations.extend(_scan_runtime_surfaces(report_label, text))
        pending.extend(reversed(child_directories))

    _require(not violations, f"private material in Pages dist: {violations[:20]}")
    _require(
        not runtime_violations,
        f"backend authority present in Pages dist: {runtime_violations[:20]}",
    )
    joined = "\n".join(text_parts)
    for required in (
        "PUBLIC SYNTHETIC REPLAY",
        "public-replay.v1.json",
        "production_release_allowed",
    ):
        _require(
            required in joined,
            f"required public boundary missing from dist: {required}",
        )
    _require(
        "sourceMappingURL=" not in joined, "public build must not publish source maps"
    )
    return {
        "dist": "public-pages-dist",
        "file_count": file_count,
        "source_maps": 0,
        "privacy_violations": 0,
        "backend_authority_surfaces": 0,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--dist", type=Path)
    args = parser.parse_args()
    try:
        result: dict[str, Any] = {
            "status": "PASS_PUBLIC_PAGES_PRIVACY",
            "manifest": validate_manifest(),
        }
        if args.dist is not None:
            result["dist"] = validate_dist(args.dist)
    except PublicPagesValidationError as error:
        print(
            json.dumps(
                {
                    "status": "HOLD_PUBLIC_PAGES_PRIVACY",
                    "reason": str(error),
                    "values_disclosed": False,
                },
                ensure_ascii=False,
                indent=2,
            )
        )
        return 1
    except Exception:
        print(
            json.dumps(
                {
                    "status": "HOLD_PUBLIC_PAGES_PRIVACY",
                    "reason": (
                        "public Pages privacy check failed without publishing "
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
