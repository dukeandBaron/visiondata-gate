"""The repository homepage exposes real evidence and reusable entry points."""

from __future__ import annotations

import json
import re
from pathlib import Path
import tomllib


ROOT = Path(__file__).resolve().parents[1]


def test_readme_maps_all_finals_dimensions_to_evidence() -> None:
    text = (ROOT / "README.md").read_text(encoding="utf-8")
    for dimension, score in (
        ("问题价值与实际影响", "20"),
        ("创新性", "25"),
        ("技术／研究深度", "25"),
        ("完成度与可验证性", "15"),
        ("开源价值与复用", "15"),
    ):
        assert dimension in text
        assert score in text
    assert "docs/FINALS_EVIDENCE_MAP.md" in text
    assert "Public 主仓" in text.replace("**", "")
    score_table = text.split("## 决赛评分证据索引", 1)[1].split("## 当前声明边界", 1)[0]
    scores = [int(row.split("|")[3].strip()) for row in score_table.splitlines()
              if re.match(r"^\|.*\|\s*\d+\s*\|", row)]
    assert scores == [8, 7, 5, 10, 10, 5, 10, 8, 7, 8, 7, 7, 8]
    assert sum(scores) == 100


def test_readme_exposes_benchmark_denominators_and_boundaries() -> None:
    text = (ROOT / "README.md").read_text(encoding="utf-8")
    for token in (
        "288 条",
        "24 / 24",
        "8 / 8",
        "4 / 8",
        "14",
        "24",
        "12 / 12",
        "6 / 6",
        "2094 collected",
        "2070 passed",
        "24 skipped",
        "不证明工业模型达标",
    ):
        # Product copy may use compact ratios; spacing is not a factual contract.
        assert re.sub(r"\s+", "", token) in re.sub(r"\s+", "", text)
    assert "2066 passed / 27 skipped" not in text


def test_reuse_catalogues_cover_actual_assets_and_license() -> None:
    for relative in (
        "src/visiondata_gate/README.md",
        "skills/README.md",
        "schemas/README.md",
        "examples/reuse/README.md",
        "docs/VERSIONING.md",
        "docs/LICENSING.md",
        "docs/FINALS_EVIDENCE_MAP.md",
    ):
        assert (ROOT / relative).is_file(), relative

    skill_manifest = json.loads(
        (ROOT / "skills/manifest.json").read_text(encoding="utf-8")
    )
    skill_catalogue = (ROOT / "skills/README.md").read_text(encoding="utf-8")
    assert len(skill_manifest["skills"]) == 5
    for item in skill_manifest["skills"]:
        assert (ROOT / item["path"]).is_file()
        assert item["name"] in skill_catalogue
        assert item["version"] in skill_catalogue

    schema_catalogue = (ROOT / "schemas/README.md").read_text(encoding="utf-8")
    for schema in (ROOT / "schemas").glob("*.json"):
        assert schema.name in schema_catalogue

    project = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))[
        "project"
    ]
    assert project["license"] == "Apache-2.0"
    licensing = (ROOT / "docs/LICENSING.md").read_text(encoding="utf-8")
    for boundary in ("Apache", "NOTICE", "Private", "AGPL", "第三方"):
        assert boundary in licensing


def test_readme_links_code_skill_schema_version_and_license_guides() -> None:
    text = (ROOT / "README.md").read_text(encoding="utf-8")
    for target in (
        "src/visiondata_gate/README.md",
        "skills/README.md",
        "schemas/README.md",
        "docs/VERSIONING.md",
        "docs/VERSION_EVOLUTION.md",
        "docs/LICENSING.md",
    ):
        assert target in text
