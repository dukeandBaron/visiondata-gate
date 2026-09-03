"""Export a privacy-bounded, history-free public repository snapshot.

The exporter copies only Git-tracked files selected by an explicit allowlist.
It never copies the source .git directory, ignored files, release evidence,
binary presentation material, local receipts, databases, logs, or build output.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Iterable


PROJECT_ROOT = Path(__file__).resolve().parents[1]
PUBLIC_PAGES_TEMPLATE = "tools/templates/public-pages.yml"
PUBLIC_PAGES_WORKFLOW = ".github/workflows/pages.yml"
PUBLIC_CI_TEMPLATE = "tools/templates/public-ci.yml"
PUBLIC_CI_WORKFLOW = ".github/workflows/ci.yml"

PUBLIC_EXACT_FILES = {
    ".env.example",
    ".gitattributes",
    ".gitignore",
    ".streamlit/config.toml",
    ".github/ISSUE_TEMPLATE/bug_report.yml",
    ".github/ISSUE_TEMPLATE/config.yml",
    ".github/ISSUE_TEMPLATE/feature_request.yml",
    ".github/pull_request_template.md",
    "CHANGELOG.md",
    "CITATION.cff",
    "CODE_OF_CONDUCT.md",
    "CONTRIBUTING.md",
    "LICENSE",
    "NOTICE",
    "README.md",
    "SECURITY.md",
    "SUPPORT.md",
    "app.py",
    "build_windows_installer.ps1",
    "environment.core.yml",
    "pyproject.toml",
    "run_api.ps1",
    "run_app.ps1",
    "run_demo.ps1",
    "run_semifinal_demo.ps1",
    "run_tests.ps1",
    "run_web.ps1",
    "run_workbench.ps1",
    "setup_env.ps1",
    "uv.lock",
    "docs/CARGO_LICENSES.locked.json",
    "docs/SBOM.cdx.json",
    "docs/THIRD_PARTY_LICENSE_INVENTORY.generated.md",
    "docs/THIRD_PARTY_NOTICES.md",
    "docs/PUBLIC_BINARY_REVIEW.json",
    "docs/api_reference.md",
    "docs/architecture.md",
    "docs/audit_envelope.md",
    "docs/assets/web-command-center.png",
    "docs/compliance.md",
    "docs/quickstart.md",
    "benchmarks/README.md",
    "benchmarks/dynamicbench-v3-report.json",
    "benchmarks/visa-public-proxy-summary.json",
}

PUBLIC_PREFIXES = (
    "adapters/",
    "agentteams/",
    "desktop/",
    "examples/",
    "rulepacks/",
    "sample_data/",
    "schemas/",
    "skills/",
    "src/",
    "tests/",
    "tools/",
    "web/",
)

PUBLIC_EXCLUDED_FILES = {
    "tests/test_build_semifinal_defense_kit.py",
    "tools/build_semifinal_defense_kit.py",
    "tools/build_semifinal_governance_evidence.py",
}

FORBIDDEN_PREFIXES = (
    ".git/",
    ".playwright-cli/",
    ".pytest_cache/",
    "07_results/",
    "10_reports/",
    "deliverables/",
    "desktop/build/",
    "desktop/dist/",
    "evidence/",
    "output/",
    "release/",
    "tmp/",
    "web/dist/",
    "web/node_modules/",
    "web/src-tauri/target/",
    "website/",
)

FORBIDDEN_NAMES = {
    ".env",
    ".env.local",
    ".streamlit/secrets.toml",
}

FORBIDDEN_SUFFIXES = {
    ".db",
    ".key",
    ".log",
    ".mp4",
    ".pdf",
    ".pptx",
    ".p12",
    ".pem",
    ".pfx",
    ".sqlite",
    ".sqlite3",
    ".zip",
}


class PublicExportError(RuntimeError):
    """Raised when a public snapshot cannot be exported safely."""


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


def _git_text(*args: str) -> str:
    return subprocess.check_output(
        ["git", *args],
        cwd=PROJECT_ROOT,
        text=True,
        encoding="utf-8",
        stderr=subprocess.PIPE,
    ).strip()


def _source_identity() -> dict[str, object]:
    status = _git_text("status", "--porcelain=v1", "--untracked-files=all")
    if status:
        raise PublicExportError(
            "source worktree must be clean before a public snapshot is exported"
        )
    commit_oid = _git_text("rev-parse", "HEAD")
    tree_oid = _git_text("rev-parse", "HEAD^{tree}")
    if not commit_oid or not tree_oid:
        raise PublicExportError("source Git identity is unavailable")
    return {
        "source_commit_oid": commit_oid,
        "source_tree_oid": tree_oid,
        "source_worktree_clean": True,
    }


def _tracked_paths() -> list[str]:
    raw = subprocess.check_output(
        ["git", "ls-files", "-z"],
        cwd=PROJECT_ROOT,
        stderr=subprocess.PIPE,
    )
    return sorted(item.decode("utf-8") for item in raw.split(b"\0") if item)


def _selected(path: str) -> bool:
    normalized = path.replace("\\", "/")
    parts = normalized.split("/")
    if (
        not normalized
        or normalized.startswith("/")
        or any(part in {"", ".", ".."} for part in parts)
        or any(
            ":" in part or any(ord(character) < 32 for character in part)
            for part in parts
        )
    ):
        return False
    lowered = normalized.casefold()
    if _contains_forbidden_env_path(parts):
        return False
    if lowered in FORBIDDEN_NAMES:
        return False
    if any(lowered.startswith(prefix) for prefix in FORBIDDEN_PREFIXES):
        return False
    if Path(lowered).suffix in FORBIDDEN_SUFFIXES:
        return False
    if normalized in PUBLIC_EXCLUDED_FILES:
        return False
    return normalized in PUBLIC_EXACT_FILES or normalized.startswith(PUBLIC_PREFIXES)


def _validate_destination(destination: Path) -> Path:
    candidate = destination.expanduser()
    try:
        is_junction = getattr(candidate, "is_junction", None)
        redirecting = candidate.is_symlink() or bool(
            is_junction is not None and is_junction()
        )
    except OSError:
        redirecting = True
    if redirecting:
        raise PublicExportError("destination must not be a symbolic link")
    try:
        resolved = candidate.resolve()
    except (OSError, RuntimeError) as error:
        raise PublicExportError("destination cannot be resolved") from error
    source = PROJECT_ROOT.resolve()
    if resolved == source or source in resolved.parents:
        raise PublicExportError("destination must be outside the private source tree")
    if resolved.exists():
        raise PublicExportError("destination must not already exist")
    resolved.parent.mkdir(parents=True, exist_ok=True)
    return resolved


def _copy_files(destination: Path, paths: Iterable[str]) -> list[dict[str, object]]:
    manifest: list[dict[str, object]] = []
    for relative in paths:
        if not _selected(relative):
            raise PublicExportError("unsafe or non-public tracked path")
        source = PROJECT_ROOT / relative
        if source.is_symlink():
            raise PublicExportError("public source must not be a symlink")
        try:
            resolved_source = source.resolve(strict=True)
        except OSError as error:
            raise PublicExportError(
                "tracked public source cannot be resolved"
            ) from error
        if PROJECT_ROOT.resolve() not in resolved_source.parents:
            raise PublicExportError("public source escapes repository")
        if not resolved_source.is_file():
            raise PublicExportError("tracked public source is missing")
        target = destination / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(resolved_source, target)
        data = target.read_bytes()
        manifest.append(
            {
                "path": relative,
                "sha256": hashlib.sha256(data).hexdigest(),
                "size_bytes": len(data),
            }
        )
    return manifest


def _validate_export_snapshot(destination: Path) -> None:
    validators = (
        (
            PROJECT_ROOT / "tools" / "check_public_repository.py",
            ("--snapshot-root", str(destination)),
        ),
        (
            PROJECT_ROOT / "tools" / "check_markdown_links.py",
            ("--root", str(destination)),
        ),
    )
    for checker, arguments in validators:
        result = subprocess.run(
            [sys.executable, str(checker), *arguments],
            cwd=PROJECT_ROOT,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            check=False,
        )
        if result.returncode != 0:
            raise PublicExportError(
                "pre-publish public snapshot validation rejected the export"
            )


def _assemble_snapshot(
    resolved: Path,
    *,
    source_identity: dict[str, object],
) -> dict[str, object]:
    selected = [path for path in _tracked_paths() if _selected(path)]
    if not selected:
        raise PublicExportError("public allowlist selected no tracked files")
    required = {
        PUBLIC_CI_TEMPLATE,
        PUBLIC_PAGES_TEMPLATE,
        "CODE_OF_CONDUCT.md",
        "CONTRIBUTING.md",
        "LICENSE",
        "README.md",
        "SECURITY.md",
        "docs/CARGO_LICENSES.locked.json",
        "docs/PUBLIC_BINARY_REVIEW.json",
        "docs/api_reference.md",
        "docs/architecture.md",
        "docs/audit_envelope.md",
        "docs/compliance.md",
        "docs/quickstart.md",
        "benchmarks/README.md",
        "benchmarks/dynamicbench-v3-report.json",
        "benchmarks/visa-public-proxy-summary.json",
        "tools/check_public_pages.py",
        "tools/check_public_repository.py",
        "tools/run_public_test_suite.py",
        "web/package-lock.json",
        "web/public/public-replay.v1.json",
    }
    missing = sorted(required.difference(selected))
    if missing:
        raise PublicExportError(
            "required public files are not tracked: " + ", ".join(missing)
        )

    manifest = _copy_files(resolved, selected)
    generated_workflows = {
        PUBLIC_CI_WORKFLOW: PUBLIC_CI_TEMPLATE,
        PUBLIC_PAGES_WORKFLOW: PUBLIC_PAGES_TEMPLATE,
    }
    for workflow_path, template_path in generated_workflows.items():
        template = resolved / template_path
        workflow = resolved / workflow_path
        workflow.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(template, workflow)
        workflow_data = workflow.read_bytes()
        manifest.append(
            {
                "path": workflow_path,
                "sha256": hashlib.sha256(workflow_data).hexdigest(),
                "size_bytes": len(workflow_data),
                "source": template_path,
            }
        )
    manifest.sort(key=lambda item: str(item["path"]))

    tree_digest = hashlib.sha256()
    for item in manifest:
        tree_digest.update(str(item["path"]).encode("utf-8"))
        tree_digest.update(b"\0")
        tree_digest.update(str(item["sha256"]).encode("ascii"))
        tree_digest.update(b"\0")
    export_manifest = {
        "schema_version": "visiondata-gate.public-mirror.v2",
        **source_identity,
        "source_history_included": False,
        "private_release_evidence_included": False,
        "customer_data_included": False,
        "personal_data_included": False,
        "tracked_source_only": True,
        "file_count": len(manifest),
        "snapshot_sha256": tree_digest.hexdigest(),
        "files": manifest,
    }
    (resolved / "PUBLIC_MIRROR_MANIFEST.json").write_text(
        json.dumps(export_manifest, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
        newline="\n",
    )
    _validate_export_snapshot(resolved)
    if _source_identity() != source_identity:
        raise PublicExportError("source Git identity changed during public export")
    return export_manifest


def export(destination: Path) -> dict[str, object]:
    source_identity = _source_identity()
    resolved_destination = _validate_destination(destination)
    with tempfile.TemporaryDirectory(
        prefix=".visiondata-gate-public-",
        dir=resolved_destination.parent,
    ) as staging_name:
        staging = Path(staging_name)
        export_manifest = _assemble_snapshot(
            staging,
            source_identity=source_identity,
        )
        staging.replace(resolved_destination)
    return export_manifest


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--destination", type=Path, required=True)
    args = parser.parse_args()
    try:
        result = export(args.destination)
    except PublicExportError as error:
        reason = str(error)
        print(
            json.dumps(
                {"status": "HOLD_PUBLIC_EXPORT", "reason": reason},
                ensure_ascii=False,
                indent=2,
            )
        )
        return 1
    except Exception:
        print(
            json.dumps(
                {
                    "status": "HOLD_PUBLIC_EXPORT",
                    "reason": "public export failed without publishing local diagnostics",
                },
                ensure_ascii=False,
                indent=2,
            )
        )
        return 1
    print(
        json.dumps(
            {
                "status": "PASS_PUBLIC_EXPORT",
                "destination": "public-export-destination",
                "file_count": result["file_count"],
                "snapshot_sha256": result["snapshot_sha256"],
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
