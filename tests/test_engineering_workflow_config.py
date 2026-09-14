"""Static QA wiring contracts; these do not claim GitHub jobs executed."""

from pathlib import Path
import re
import tomllib

import yaml

from tools.export_public_repository import PUBLIC_EXACT_FILES, _selected


ROOT = Path(__file__).resolve().parents[1]


def workflow(name):
    return yaml.safe_load(
        (ROOT / ".github/workflows" / name).read_text(encoding="utf-8")
    )


def runs(job):
    return "\n".join(step.get("run", "") for step in job.get("steps", []))


def test_quality_matrix_selects_real_python_versions_and_no_hidden_failures():
    document = workflow("quality.yml")
    job = document["jobs"]["contracts-and-coverage"]
    assert set(job["strategy"]["matrix"]["os"]) == {"ubuntu-latest", "windows-latest"}
    assert set(job["strategy"]["matrix"]["python-version"]) == {"3.12", "3.13"}
    commands = runs(job)
    assert '--python "${{ matrix.python-version }}"' in commands
    assert '--pythonversion "${{ matrix.python-version }}"' in commands
    assert "--with-requirements quality/requirements.txt" in commands
    assert "check_engineering_quality.py coverage" in commands
    assert "test_submission_release.py" not in commands
    assert "--cov-branch" in commands
    assert "--junitxml=" in commands
    for item in document["jobs"].values():
        assert "continue-on-error" not in item
        assert all("continue-on-error" not in step for step in item.get("steps", []))
        assert "|| true" not in runs(item)


def test_security_jobs_fail_independently_and_pin_real_action_commits():
    document = workflow("security.yml")
    assert document["permissions"] == {"contents": "read"}
    triggers = document.get("on", document.get(True))
    assert "pull_request_target" not in triggers
    jobs = document["jobs"]
    assert set(jobs) == {"dependency-audit", "bandit", "codeql"}
    assert "--no-deps --disable-pip" in runs(jobs["dependency-audit"])
    assert "${{ github.workspace }}/output/security/" in runs(jobs["dependency-audit"])
    assert "-m bandit -r src desktop tools" in runs(jobs["bandit"])
    assert "--exit-zero" not in runs(jobs["bandit"])
    assert "check_bandit_baseline.py check" in runs(jobs["bandit"])
    assert "quality/bandit-baseline.json" in runs(jobs["bandit"])
    assert jobs["codeql"]["permissions"]["security-events"] == "write"
    assert jobs["codeql"]["permissions"]["actions"] == "read"
    analysis = next(s for s in jobs["codeql"]["steps"] if 'codeql-action/analyze@' in s.get('uses', ''))
    assert analysis['with']['output'] == 'output/codeql'
    assert analysis['with']['upload'] is False
    assert any('upload-artifact@' in s.get('uses', '') and s.get('with', {}).get('path') == 'output/codeql/' for s in jobs['codeql']['steps'])
    for job in jobs.values():
        assert all("continue-on-error" not in step for step in job["steps"])
        for step in job["steps"]:
            if "uses" in step:
                assert re.fullmatch(r"[^@]+@[0-9a-f]{40}", step["uses"])
        uploads = [
            step for step in job["steps"] if "upload-artifact@" in step.get("uses", "")
        ]
        assert all(step.get("if") == "always()" for step in uploads)


def test_quality_toolchain_and_hooks_are_locked_separately():
    config = tomllib.loads(
        (ROOT / "quality/pyproject.toml").read_text(encoding="utf-8")
    )
    dependencies = config["project"]["dependencies"]
    assert all(re.fullmatch(r"[a-z0-9-]+==[0-9.]+", item) for item in dependencies)
    assert "pyright==1.1.414" in dependencies
    assert "coverage==7.16.0" in dependencies
    assert "pip-audit==2.10.1" in dependencies
    assert config["tool"]["uv"]["package"] is False
    assert (ROOT / "quality/uv.lock").is_file()
    exported = (ROOT / "quality/requirements.txt").read_text(encoding="utf-8")
    assert "--hash=sha256:" in exported
    assert "--index-url" not in exported
    hook = yaml.safe_load(
        (ROOT / ".pre-commit-config.yaml").read_text(encoding="utf-8")
    )
    assert all("--fix" not in item["entry"] for item in hook["repos"][0]["hooks"])


def test_public_export_includes_only_reviewed_quality_files_not_qa_environment():
    required = {
        ".github/workflows/quality.yml",
        ".github/workflows/security.yml",
        ".github/dependabot.yml",
        ".pre-commit-config.yaml",
        "quality/pyproject.toml",
        "quality/uv.lock",
        "quality/requirements.txt",
        "quality/pyright-gate.json",
        "quality/pyright-debt.json",
        "quality/coverage-profile.json",
        "quality/bandit-baseline.json",
        "quality/README.md",
    }
    assert required <= PUBLIC_EXACT_FILES
    assert all(_selected(path) for path in required)
    assert not _selected("quality/.venv/pyvenv.cfg")
    assert not _selected("output/review-quality-prep/typed-coverage/coverage.json")


def test_dependency_updates_require_pull_requests_not_automatic_merges():
    data = yaml.safe_load((ROOT / ".github/dependabot.yml").read_text(encoding="utf-8"))
    assert data["version"] == 2
    ecosystems = {
        (item["package-ecosystem"], item["directory"]) for item in data["updates"]
    }
    assert {
        ("uv", "/"),
        ("uv", "/quality"),
        ("npm", "/web"),
        ("cargo", "/web/src-tauri"),
        ("github-actions", "/"),
    } <= ecosystems
    assert all(item["open-pull-requests-limit"] <= 3 for item in data["updates"])
