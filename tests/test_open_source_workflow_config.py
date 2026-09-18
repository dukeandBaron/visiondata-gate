"""Clean-checkout reuse CI is maintainer evidence, not third-party adoption."""

from pathlib import Path
import json
import re

import yaml


ROOT = Path(__file__).resolve().parents[1]
PINNED_ACTIONS = {
    "actions/checkout": "3d3c42e5aac5ba805825da76410c181273ba90b1",
    "astral-sh/setup-uv": "bec219d24cd3e171d82865faccec33120bb574f4",
    "actions/upload-artifact": "043fb46d1a93c77aae656e7c1c64a875d1fc6a0a",
}
FOCUSED_TESTS = {
    "tests/test_open_reuse_smoke.py",
    "tests/test_open_source_readiness.py",
    "tests/test_adoption_docs.py",
    "tests/test_reuse_contracts.py",
    "tests/test_reuse_metadata_example.py",
    "tests/test_custom_skill_example.py",
    "tests/test_open_source_workflow_config.py",
}


def _workflow():
    return yaml.safe_load(
        (ROOT / ".github/workflows/quality.yml").read_text(encoding="utf-8")
    )


def _job():
    jobs = _workflow()["jobs"]
    assert "open-reuse" in jobs, "quality.yml needs an independent open-reuse job"
    return jobs["open-reuse"]


def _runs(job):
    return "\n".join(step.get("run", "") for step in job["steps"])


def test_open_reuse_job_is_clean_checkout_windows_linux_python312():
    job = _job()
    assert job["runs-on"] == "${{ matrix.os }}"
    assert job["strategy"]["fail-fast"] is False
    assert set(job["strategy"]["matrix"]["os"]) == {
        "ubuntu-latest",
        "windows-latest",
    }
    assert job["strategy"]["matrix"]["python-version"] == ["3.12"]
    assert "needs" not in job and "if" not in job
    assert "third-party" in job["name"].lower()
    assert 1 <= job["timeout-minutes"] <= 15


def test_open_reuse_job_uses_only_pinned_reviewed_actions_and_locked_dependencies():
    job = _job()
    found = {}
    for step in job["steps"]:
        if "uses" not in step:
            continue
        assert re.fullmatch(r"[^@]+@[0-9a-f]{40}", step["uses"])
        action, digest = step["uses"].split("@")
        assert action in PINNED_ACTIONS
        assert digest == PINNED_ACTIONS[action]
        found[action] = step
    assert set(PINNED_ACTIONS) <= set(found)
    assert found["astral-sh/setup-uv"]["with"]["version"] == "0.11.8"
    commands = " ".join(_runs(job).split())
    assert (
        'uv sync --extra qa --locked --python "${{ matrix.python-version }}"'
        in commands
    )
    assert "pip install" not in commands.lower()


def test_open_reuse_job_executes_actual_smoke_and_fixed_focused_tests():
    job = _job()
    commands = _runs(job)
    assert (
        "tools/run_open_reuse_smoke.py --output-root output/open-reuse/run"
        in commands
    )
    assert "PASS_OPEN_REUSE_SMOKE" in commands
    for path in FOCUSED_TESTS:
        assert (ROOT / path).is_file(), f"workflow references missing test {path}"
        assert path in commands
    assert "--junitxml=output/open-reuse/pytest.xml" in commands
    assert "--ignore" not in commands and "--deselect" not in commands
    assert not re.search(r"(?:^|\s)-k(?:\s|=)", commands)


def test_open_reuse_job_cannot_claim_external_adoption_or_hide_failure():
    job = _job()
    encoded = json.dumps(job).lower()
    commands = _runs(job)
    assert "maintainer_ci_clean_checkout_not_third_party_adoption" in commands.lower()
    assert "third_party_reproduction_pending" in commands.lower()
    assert "production_release_allowed" in commands
    assert "continue-on-error" not in encoded
    assert "secrets." not in encoded
    for bypass in ("|| true", "--exit-zero", "; exit 0"):
        assert bypass not in commands
    for external in (
        "curl ",
        "wget ",
        "hf download",
        "huggingface-cli",
        "nvidia-smi",
        "torch.hub",
        "from_pretrained",
    ):
        assert external not in commands.lower()


def test_open_reuse_receipts_are_always_preserved_without_changing_other_jobs():
    job = _job()
    uploads = [
        step
        for step in job["steps"]
        if step.get("uses", "").startswith("actions/upload-artifact@")
    ]
    assert len(uploads) == 1
    assert uploads[0]["if"] == "always()"
    assert uploads[0]["with"]["path"] == "output/open-reuse/"
    jobs = _workflow()["jobs"]
    assert {
        "contracts-and-coverage",
        "normality-contracts",
        "open-reuse",
        "type-debt",
    } <= set(jobs)
    assert jobs["contracts-and-coverage"]["strategy"]["matrix"][
        "python-version"
    ] == ["3.12", "3.13"]
    assert jobs["normality-contracts"]["strategy"]["matrix"]["python-version"] == [
        "3.12"
    ]
    assert jobs["type-debt"]["if"] == "github.event_name == 'workflow_dispatch'"
