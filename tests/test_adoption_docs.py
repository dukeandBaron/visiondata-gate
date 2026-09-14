"""Public adoption docs must reference real entry points, not proposed commands."""

from pathlib import Path
import re
import tomllib

import yaml

from tools.export_public_repository import PUBLIC_EXACT_FILES


ROOT = Path(__file__).resolve().parents[1]
NEW_DOCS = (
    "docs/CROSS_PLATFORM_QUICKSTART.md",
    "docs/INTERFACE_SUPPORT.md",
    "docs/RELEASE_PREPARATION.md",
    "docs/EXTERNAL_REVIEW_RESPONSE.md",
    "docs/ENGINEERING_QUALITY_IMPLEMENTATION.md",
    "docs/PUBLIC_API.md",
    "docs/BENCHMARK_REPRODUCIBILITY.md",
    "docs/AUDIT_TRUST_BOUNDARY.md",
)


def test_portable_quickstart_points_to_a_real_launcher():
    quickstart = (ROOT / NEW_DOCS[0]).read_text(encoding="utf-8")
    assert "tools/run_cross_platform_workbench.py --check" in quickstart
    assert (ROOT / "tools/run_cross_platform_workbench.py").is_file()
    for block in re.findall(r"```[^\n]*\n(.*?)```", quickstart, flags=re.S):
        assert "visiondata-gate serve" not in block
        assert "INSECURE_TEST_ACTOR_HEADER_BYPASS" not in block
        assert "uvx visiondata-gate" not in block
    assert "--locked" in quickstart


def test_new_docs_have_resolvable_local_links_and_are_export_allowed():
    for relative in NEW_DOCS:
        path = ROOT / relative
        assert relative in PUBLIC_EXACT_FILES
        content = path.read_text(encoding="utf-8")
        for target in re.findall(r"\]\(([^)]+)\)", content):
            if re.match(r"[a-zA-Z][a-zA-Z0-9+.-]*:", target) or target.startswith("#"):
                continue
            resolved = (path.parent / target.split("#", 1)[0]).resolve()
            assert resolved.is_relative_to(ROOT), relative
            assert resolved.exists(), f"Missing local link in {relative}: {target}"


def test_citation_and_changelog_do_not_invent_a_distribution_release():
    citation = yaml.safe_load((ROOT / "CITATION.cff").read_text(encoding="utf-8"))
    assert citation["cff-version"] == "1.2.0"
    assert citation["type"] == "software"
    assert citation["repository-code"] == (
        "https://github.com/dukeandBaron/visiondata-gate"
    )
    assert citation["authors"] == [{"name": "VisionData Gate contributors"}]
    assert "doi" not in citation
    assert "CITATION.cff" in PUBLIC_EXACT_FILES
    assert "CHANGELOG.md" in PUBLIC_EXACT_FILES
    metadata = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    assert (
        metadata["project"]["scripts"]["visiondata-gate"] == "visiondata_gate.cli:main"
    )
    changelog = (ROOT / "CHANGELOG.md").read_text(encoding="utf-8")
    assert "## [Unreleased]" in changelog
    assert "not a claim of a matching PyPI package version" in changelog
    assert "prerelease" in changelog


def test_canonical_interface_does_not_promise_installer_or_model_authority():
    content = (ROOT / "docs/INTERFACE_SUPPORT.md").read_text(encoding="utf-8")
    assert "primary interactive product" in content
    for boundary in (
        "Legacy/compatibility",
        "Optional desktop wrapper",
        "Public synthetic replay",
    ):
        assert boundary in content
    assert "A Windows smoke pass does not certify them" in content
    assert "older Windows installer does not automatically contain" in content
