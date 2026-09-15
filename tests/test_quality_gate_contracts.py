from pathlib import Path
import tomllib

import yaml


ROOT = Path(__file__).resolve().parents[1]


def test_public_job_is_explicitly_scoped_not_a_full_freeze_regression() -> None:
    workflow = yaml.safe_load(
        (ROOT / ".github/workflows/quality.yml").read_text("utf-8")
    )
    job = workflow["jobs"]["contracts-and-coverage"]
    assert job["timeout-minutes"] == 15
    assert "Scoped" in job["name"]
    assert any(
        "check_engineering_quality.py coverage" in s.get("run", "")
        for s in job["steps"]
    )


def test_python_ci_pins_both_supported_versions_on_both_platforms() -> None:
    workflow = yaml.safe_load(
        (ROOT / ".github/workflows/quality.yml").read_text("utf-8")
    )
    job = workflow["jobs"]["contracts-and-coverage"]
    matrix = job["strategy"]["matrix"]
    assert set(matrix["os"]) == {"ubuntu-latest", "windows-latest"}
    assert set(matrix["python-version"]) == {"3.12", "3.13"}
    assert job["strategy"]["fail-fast"] is False
    version = "${{ matrix.python-version }}"
    assert version in job["name"]
    setup = next(step for step in job["steps"] if step.get("name") == "Install uv")
    assert setup["with"]["python-version"] == version
    sync = next(
        step
        for step in job["steps"]
        if step.get("name") == "Install locked application test dependencies"
    )["run"]
    assert "--locked" in sync
    assert f'--python "{version}"' in sync
    verify = next(
        step for step in job["steps"] if step.get("name") == "Verify selected Python"
    )["run"]
    assert "sys.version_info" in verify
    assert version in verify


def test_explicit_ruff_rules_preserve_the_existing_default_gate() -> None:
    project = tomllib.loads((ROOT / "pyproject.toml").read_text("utf-8"))
    ruff = project["tool"]["ruff"]
    assert ruff["line-length"] == 88
    assert ruff["target-version"] == "py312"
    assert ruff["lint"]["select"] == ["E4", "E7", "E9", "F"]
    assert not ruff["lint"].get("ignore")


def test_native_lint_and_format_failures_cannot_mask_each_other() -> None:
    # Formatting remains an explicit contributor gate while whole-tree format
    # debt is documented; do not invent a full-format hosted CI PASS.
    config = yaml.safe_load((ROOT / ".pre-commit-config.yaml").read_text("utf-8"))
    steps = config["repos"][0]["hooks"]
    lint = [step for step in steps if "ruff check" in step["entry"]]
    formatting = [step for step in steps if "ruff format --check" in step["entry"]]
    assert len(lint) == len(formatting) == 1
    assert lint[0] is not formatting[0]


def test_quality_document_keeps_unmeasured_gates_explicit() -> None:
    document = (ROOT / "docs/QUALITY_GATES.md").read_text("utf-8")
    assert "NOT_MEASURED" in document
    assert "HOLD_UNMEASURED_GATES" in document
    assert "不是覆盖率" in document
    assert "--cov-branch" in document
    assert "public CI" in document
