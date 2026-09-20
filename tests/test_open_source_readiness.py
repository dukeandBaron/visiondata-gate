"""Evidence-first open-source guidance; static checks are not external adoption."""

from pathlib import Path
import re

import pytest
import yaml


ROOT = Path(__file__).resolve().parents[1]
READINESS = ROOT / "docs/OPEN_SOURCE_READINESS.md"


def readiness():
    assert READINESS.is_file(), "the 7+8 open-source evidence map must exist"
    return READINESS.read_text(encoding="utf-8")


def test_readiness_maps_official_seven_plus_eight_without_awarding_a_score():
    text = readiness()
    assert re.search(r"核心组件.*7\s*分", text)
    assert re.search(r"文档.*8\s*分", text)
    for item in (
        "FINALS_EVIDENCE_MAP.md",
        "NOT_A_GUARANTEED_SCORE",
        "不设 Star / Fork 单项分",
    ):
        assert item in text
    assert "独立第三方记录不是另加的参赛准入条件" in text


def test_readiness_separates_current_publication_states_and_third_party_evidence():
    text = readiness()
    for status in (
        "PUBLIC_SOURCE_AVAILABLE",
        "MAIN_BEHIND_REVIEWED_PR",
        "PR_37_DRAFT_NOT_MERGED",
        "PAGES_SERVING_PREVIOUS_DEPLOYMENT",
        "NO_STABLE_RELEASE",
        "EXTERNAL_CLEAN_CLONE_PENDING",
        "HISTORY_PRIVACY_HOLD",
    ):
        assert status in text
    assert re.search(r"快照.*20\d{2}-\d{2}-\d{2}", text)
    assert "重新查询" in text
    assert not re.search(r"\b\d+\s+(?:stars?|forks?)\b", text, flags=re.I)
    assert "模板不是已完成的第三方复现记录" in text


def test_readiness_links_actual_reusable_assets_and_license_boundaries():
    text = readiness()
    for target in (
        "../src/visiondata_gate/README.md",
        "../skills/README.md",
        "../schemas/README.md",
        "../examples/reuse/README.md",
        "PUBLIC_API.md",
        "VERSIONING.md",
        "../LICENSE",
        "../NOTICE",
        "LICENSING.md",
        "../CHANGELOG.md",
        "../CITATION.cff",
        "API_QUICKSTART.md",
    ):
        assert f"]({target})" in text
        assert (READINESS.parent / target).is_file()
    for boundary in (
        "私域数据与未授权权重不开放不是缺陷",
        "AGPL",
        "Enterprise",
        "EXTERNAL_CLEAN_CLONE_PENDING",
        "REAL_MODEL_NOT_RUN",
    ):
        assert boundary in text


def test_readiness_provides_real_local_verification_and_read_only_github_commands():
    text = readiness()
    for command in (
        "uv run --no-sync python examples/reuse/metadata_skill.py --metadata-count 12 --observed-count 14",
        "uv run --no-sync python examples/reuse/metadata_skill.py --metadata-count 12 --observed-count 12",
        "gh repo view dukeandBaron/visiondata-gate --json visibility,defaultBranchRef,licenseInfo",
        "gh pr view 37 --repo dukeandBaron/visiondata-gate",
        "gh pr checks 37 --repo dukeandBaron/visiondata-gate",
        "gh run list --repo dukeandBaron/visiondata-gate --workflow pages.yml",
    ):
        assert command in text
    for name in (
        "test_open_source_readiness.py",
        "test_adoption_docs.py",
        "test_public_api_surface.py",
        "test_reuse_metadata_example.py",
        "test_industrial_skills.py",
        "test_reuse_contracts.py",
    ):
        assert f"tests/{name}" in text
        assert (ROOT / "tests" / name).is_file()
    for unsupported in (
        "gh pr merge",
        "gh repo edit",
        "--method PATCH",
        "--method POST",
    ):
        assert unsupported not in text
    assert "不能关闭或放宽历史隐私门禁" in text


@pytest.mark.parametrize(
    "relative",
    [
        "docs/OPEN_SOURCE_READINESS.md",
        "CONTRIBUTING.md",
        ".github/ISSUE_TEMPLATE/reproduction.md",
        ".github/pull_request_template.md",
    ],
)
def test_readiness_and_templates_have_resolvable_local_links(relative):
    path = ROOT / relative
    assert path.is_file(), relative
    text = path.read_text(encoding="utf-8")
    for target in re.findall(r"\]\(([^)]+)\)", text):
        if re.match(r"[A-Za-z][A-Za-z0-9+.-]*:", target) or target.startswith("#"):
            continue
        resolved = (path.parent / target.split("#", 1)[0]).resolve()
        assert resolved.is_relative_to(ROOT), relative
        assert resolved.exists(), f"broken local link in {relative}: {target}"


def test_reproduction_issue_requires_version_identity_results_and_independence():
    text = (ROOT / ".github/ISSUE_TEMPLATE/reproduction.md").read_text(encoding="utf-8")
    frontmatter = yaml.safe_load(text.split("---", 2)[1])
    assert frontmatter["name"] == "Reproduction / 部署与复现反馈"
    assert frontmatter["title"] == "[Reproduction] "
    for item in (
        "commit SHA",
        "tree SHA",
        "操作系统",
        "Python",
        "Node",
        "完整命令",
        "退出码",
        "输出 SHA-256",
        "SUCCESS / PARTIAL / FAIL",
        "独立性",
        "未运行",
        "维护者",
        "同团队",
        "独立第三方",
        "隐私",
        "客户原图",
        "令牌",
        "绝对路径",
        "原始私有回执",
    ):
        assert item in text
    assert "仅填写自己实际执行的步骤" in text


def test_pull_request_template_requests_reusable_example_compatibility_and_evidence():
    text = (ROOT / ".github/pull_request_template.md").read_text(encoding="utf-8")
    for item in (
        "复用接口",
        "最小示例",
        "输入",
        "输出",
        "兼容",
        "迁移",
        "第三方依赖",
        "许可证",
        "实际验证",
        "未运行",
        "独立第三方",
        "历史隐私门禁",
        "生产权限",
    ):
        assert item in text


def test_contributing_explains_how_to_submit_honest_reproduction_evidence():
    text = (ROOT / "CONTRIBUTING.md").read_text(encoding="utf-8")
    assert "](docs/OPEN_SOURCE_READINESS.md)" in text
    assert "](.github/ISSUE_TEMPLATE/reproduction.md)" in text
    assert "tests/test_open_source_readiness.py" in text
    assert "independent third-party" in text
    assert "Do not create" in text and "adoption" in text
