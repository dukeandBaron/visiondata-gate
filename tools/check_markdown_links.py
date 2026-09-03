"""Fail closed when a public snapshot contains broken local Markdown links."""

from __future__ import annotations

import argparse
import json
import re
from pathlib import Path
from urllib.parse import unquote


MARKDOWN_LINK = re.compile(r"!?\[[^\]\n]*\]\(([^)\n]+)\)")
HTML_LINK = re.compile(r"(?:href|src)=[\"']([^\"']+)[\"']", re.IGNORECASE)
EXTERNAL_PREFIXES = ("http://", "https://", "mailto:", "data:", "tel:")
ROOT_RELATIVE_TEMPLATES = {"docs/PUBLIC_REPOSITORY_README.md"}
PUBLIC_MANIFEST = "PUBLIC_MIRROR_MANIFEST.json"
IGNORED_DIRECTORY_NAMES = {
    ".git",
    ".mypy_cache",
    ".pytest_cache",
    ".ruff_cache",
    ".venv",
    "build",
    "dist",
    "node_modules",
    "target",
    "tmp",
}


def _target(raw: str) -> str:
    value = raw.strip()
    if value.startswith("<") and ">" in value:
        return value[1 : value.index(">")]
    return value.split(maxsplit=1)[0]


def _documents(root: Path) -> list[Path]:
    manifest_path = root / PUBLIC_MANIFEST
    if manifest_path.is_file():
        payload = json.loads(manifest_path.read_text(encoding="utf-8"))
        files = payload.get("files") if isinstance(payload, dict) else None
        if not isinstance(files, list):
            raise ValueError("public mirror manifest has no file list")
        documents: list[Path] = []
        for item in files:
            relative = item.get("path") if isinstance(item, dict) else None
            if isinstance(relative, str) and relative.casefold().endswith(".md"):
                documents.append(root / relative)
        return sorted(documents)
    return sorted(
        path
        for path in root.rglob("*.md")
        if path.is_file()
        and not any(
            part.casefold() in IGNORED_DIRECTORY_NAMES
            for part in path.relative_to(root).parts
        )
    )


def find_broken_links(root: Path) -> list[dict[str, str]]:
    resolved_root = root.resolve(strict=True)
    failures: list[dict[str, str]] = []
    for document in _documents(resolved_root):
        if not document.is_file():
            failures.append(
                {
                    "document": document.relative_to(resolved_root).as_posix(),
                    "target": "self",
                    "reason": "missing",
                }
            )
            continue
        relative_document = document.relative_to(resolved_root).as_posix()
        text = document.read_text(encoding="utf-8")
        raw_targets = [*MARKDOWN_LINK.findall(text), *HTML_LINK.findall(text)]
        for raw in raw_targets:
            target = unquote(_target(raw)).replace("\\", "/")
            lowered = target.casefold()
            if (
                not target
                or target.startswith("#")
                or target.startswith("//")
                or lowered.startswith(EXTERNAL_PREFIXES)
            ):
                continue
            path_part = target.split("#", 1)[0].split("?", 1)[0]
            if not path_part:
                continue
            base = (
                resolved_root
                if relative_document in ROOT_RELATIVE_TEMPLATES
                else document.parent
            )
            candidate = (
                resolved_root / path_part.lstrip("/")
                if path_part.startswith("/")
                else base / path_part
            ).resolve()
            if candidate != resolved_root and resolved_root not in candidate.parents:
                failures.append(
                    {
                        "document": relative_document,
                        "target": target,
                        "reason": "escape",
                    }
                )
            elif not candidate.exists():
                failures.append(
                    {
                        "document": relative_document,
                        "target": target,
                        "reason": "missing",
                    }
                )
    return failures


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, default=Path.cwd())
    args = parser.parse_args()
    try:
        failures = find_broken_links(args.root)
    except (OSError, UnicodeDecodeError, ValueError):
        print(
            json.dumps(
                {"status": "HOLD_PUBLIC_DOCS", "reason": "documentation scan failed"},
                ensure_ascii=False,
            )
        )
        return 1
    if failures:
        print(
            json.dumps(
                {
                    "status": "HOLD_PUBLIC_DOCS",
                    "broken_link_count": len(failures),
                    "failures": failures,
                },
                ensure_ascii=False,
                indent=2,
            )
        )
        return 1
    print(json.dumps({"status": "PASS_PUBLIC_DOCS", "broken_link_count": 0}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
