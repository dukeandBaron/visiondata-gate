from pathlib import Path

from tools.check_markdown_links import find_broken_links


def test_public_docs_checker_accepts_files_and_external_links(tmp_path: Path) -> None:
    (tmp_path / "docs").mkdir()
    (tmp_path / "docs" / "guide.md").write_text("# Guide\n", encoding="utf-8")
    (tmp_path / "README.md").write_text(
        "[Guide](docs/guide.md) [Web](https://example.com)\n",
        encoding="utf-8",
    )
    assert find_broken_links(tmp_path) == []


def test_public_docs_checker_reports_missing_and_escape_without_absolute_paths(
    tmp_path: Path,
) -> None:
    root = tmp_path / "public"
    root.mkdir()
    (root / "README.md").write_text(
        "[Missing](docs/missing.md) [Escape](../private.md)\n",
        encoding="utf-8",
    )
    assert find_broken_links(root) == [
        {"document": "README.md", "target": "docs/missing.md", "reason": "missing"},
        {"document": "README.md", "target": "../private.md", "reason": "escape"},
    ]


def test_root_readme_resolves_links_from_repository_root(tmp_path: Path) -> None:
    (tmp_path / "docs").mkdir()
    (tmp_path / "docs" / "guide.md").write_text("# Guide\n", encoding="utf-8")
    (tmp_path / "README.md").write_text("[Guide](docs/guide.md)\n", encoding="utf-8")
    assert find_broken_links(tmp_path) == []


def test_public_docs_checker_ignores_dependency_directories(tmp_path: Path) -> None:
    dependency = tmp_path / ".venv" / "dependency"
    dependency.mkdir(parents=True)
    (dependency / "README.md").write_text("[Missing](private.md)\n", encoding="utf-8")
    (tmp_path / "README.md").write_text("# Public project\n", encoding="utf-8")
    assert find_broken_links(tmp_path) == []
