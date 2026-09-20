"""The public entrypoint exposes one executable reuse path and honest adoption state."""

from pathlib import Path

from tools.export_public_repository import PUBLIC_EXACT_FILES


ROOT = Path(__file__).resolve().parents[1]


def test_readme_exposes_five_minute_open_reuse_and_external_adoption_boundary():
    readme = (ROOT / "README.md").read_text(encoding="utf-8")
    public_template = (ROOT / "docs/PUBLIC_REPOSITORY_README.md").read_text(
        encoding="utf-8"
    )
    assert readme == public_template
    for token in (
        "tools/run_open_reuse_smoke.py",
        "Path('output/open-reuse').mkdir(parents=True, exist_ok=True)",
        "--output-root output/open-reuse/run-01",
        "PASS_OPEN_REUSE_SMOKE",
        "docs/ADOPTION_GUIDE.md",
        "docs/OPEN_SOURCE_READINESS.md",
        "docs/THIRD_PARTY_REPRODUCTION.md",
        "THIRD_PARTY_REPRODUCTION_PENDING",
        "维护者 CI",
        "不等于第三方复现",
    ):
        assert token in readme


def test_new_adoption_docs_and_normality_contract_survive_public_export():
    for relative in (
        "docs/ADOPTION_GUIDE.md",
        "docs/OPEN_SOURCE_READINESS.md",
        "docs/THIRD_PARTY_REPRODUCTION.md",
        "docs/NORMALITY_TTT.md",
        "quality/BANDIT_TTT_TOOL_REVIEW.md",
    ):
        assert (ROOT / relative).is_file(), relative
        assert relative in PUBLIC_EXACT_FILES


def test_core_and_benchmark_maps_include_current_ttt_and_followup_assets():
    core = (ROOT / "src/visiondata_gate/README.md").read_text(encoding="utf-8")
    for module in (
        "normality_ttt.py",
        "normality_adaptation_service.py",
        "normality_followup_service.py",
    ):
        assert module in core
    benchmarks = (ROOT / "benchmarks/README.md").read_text(encoding="utf-8")
    assert "NORMALITY_TTT_LOCAL_20260919.json" in benchmarks
    assert "未观察到质量提升" in benchmarks


def test_changelog_records_open_reuse_workflow_without_claiming_external_adoption():
    changelog = (ROOT / "CHANGELOG.md").read_text(encoding="utf-8")
    unreleased = changelog.split("## [Unreleased]", 1)[1].split("## [", 1)[0]
    for token in (
        "open-reuse",
        "ADOPTION_GUIDE",
        "THIRD_PARTY_REPRODUCTION_PENDING",
        "Normality TTT",
    ):
        assert token in unreleased
    assert "independent third-party reproduction completed" not in unreleased.lower()
