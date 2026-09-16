import os
from pathlib import Path

from tools.export_public_repository import _selected


ROOT = Path(__file__).resolve().parents[1]


def _public_markdown() -> dict[str, str]:
    result = {}
    skipped = {
        ".git",
        ".pytest_cache",
        ".venv",
        "__pycache__",
        "dist",
        "node_modules",
        "output",
        "target",
    }
    for directory, names, files in os.walk(ROOT):
        names[:] = [name for name in names if name not in skipped]
        base = Path(directory)
        for name in files:
            if not name.endswith(".md"):
                continue
            path = base / name
            relative = path.relative_to(ROOT).as_posix()
            if relative == "README.md" or _selected(relative):
                result[relative] = path.read_text("utf-8")
    return result


def test_public_docs_use_only_the_canonical_github_repository_and_pages_path():
    documents = _public_markdown()
    stale_link_paths = sorted(
        path for path, text in documents.items() if "visiondata-gate-public" in text
    )
    stale_dual_repo_paths = sorted(
        path
        for path, text in documents.items()
        if "私有权威仓 + 隐私安全公共镜像" in text
    )

    assert stale_link_paths == []
    assert stale_dual_repo_paths == []
    assert "dukeandBaron/visiondata-gate" in documents["README.md"]
    assert "dukeandbaron.github.io/visiondata-gate/" in documents["README.md"]
