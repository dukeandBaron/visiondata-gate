"""The shared example instructions must work without a source checkout."""

from pathlib import Path


def test_sample_instructions_separate_installed_and_source_workflows():
    text = (Path(__file__).resolve().parents[1] / "sample_data/README.md").read_text("utf-8")
    assert "## 安装版" in text
    installed, source = text.split("## 安装版", 1)[1].split("## 源码版", 1)
    assert "开始菜单" in installed
    assert "run_workbench.ps1" not in installed
    assert "127.0.0.1:4173" not in installed
    assert "合成" in installed and "人工" in installed
    assert "run_workbench.ps1" in source


