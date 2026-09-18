"""Static Normality CI wiring contracts, not evidence that GitHub jobs ran.

The locked API/QA lane exercises public-safe contracts. Optional Torch-backed
tensor fixtures must report skips; they cannot turn this lane into a claim of
real model execution, GPU verification, or industrial effectiveness.
"""

from pathlib import Path
import json
import re

import yaml


ROOT = Path(__file__).resolve().parents[1]
PINNED_ACTIONS = {
    "actions/checkout": "3d3c42e5aac5ba805825da76410c181273ba90b1",
    "astral-sh/setup-uv": "bec219d24cd3e171d82865faccec33120bb574f4",
    "actions/setup-node": "820762786026740c76f36085b0efc47a31fe5020",
    "actions/upload-artifact": "043fb46d1a93c77aae656e7c1c64a875d1fc6a0a",
}
PYTHON_CONTRACTS = {
    "tests/test_normality_ttt.py",
    "tests/test_normality_feedback_api.py",
    "tests/test_normality_adaptation_api.py",
    "tests/test_normality_followup.py",
    "tests/test_vision_model_api.py",
    "tests/test_normality_workflow_config.py",
}
NODE_CONTRACTS = {
    "tests/web_normality_model_contracts.test.mjs",
    "tests/web_vision_model_contracts.test.mjs",
    "tests/web_operator_fetch_abort.test.mjs",
}


def _workflow():
    return yaml.safe_load(
        (ROOT / ".github/workflows/quality.yml").read_text(encoding="utf-8")
    )


def _normality_job():
    jobs = _workflow()["jobs"]
    assert "normality-contracts" in jobs, (
        "quality.yml must add the independent normality-contracts job"
    )
    return jobs["normality-contracts"]


def _runs(job):
    return "\n".join(step.get("run", "") for step in job["steps"])


def test_normality_lane_is_independent_windows_linux_python312():
    job = _normality_job()
    assert job["runs-on"] == "${{ matrix.os }}"
    assert job["strategy"]["fail-fast"] is False
    assert set(job["strategy"]["matrix"]["os"]) == {"ubuntu-latest", "windows-latest"}
    assert job["strategy"]["matrix"]["python-version"] == ["3.12"]
    assert "needs" not in job, "Normality checks must not depend on another gate"
    assert "if" not in job, "Normality contracts must run on PRs as well as dispatch"
    assert 1 <= job["timeout-minutes"] <= 30
    assert _workflow()["permissions"] == {"contents": "read"}


def test_normality_lane_reuses_pinned_actions_and_locked_api_qa():
    job = _normality_job()
    action_steps = [step for step in job["steps"] if "uses" in step]
    actions = {}
    for step in action_steps:
        assert re.fullmatch(r"[^@]+@[0-9a-f]{40}", step["uses"])
        action, digest = step["uses"].split("@")
        assert action in PINNED_ACTIONS, "extra integrations require separate review"
        assert digest == PINNED_ACTIONS[action]
        actions[action] = step
    assert {
        "actions/checkout",
        "astral-sh/setup-uv",
        "actions/setup-node",
    } <= actions.keys()
    uv = actions["astral-sh/setup-uv"]["with"]
    assert uv["version"] == "0.11.8"
    assert uv["python-version"] == "${{ matrix.python-version }}"
    assert str(actions["actions/setup-node"]["with"]["node-version"]) == "22"
    commands = " ".join(_runs(job).split())
    assert (
        'uv sync --extra api --extra qa --locked --python "${{ matrix.python-version }}"'
        in commands
    )


def test_normality_python_slice_includes_real_current_filenames_and_skip_evidence():
    job = _normality_job()
    pytest_steps = [
        step
        for step in job["steps"]
        if "uv run --no-sync python -m pytest" in step.get("run", "")
    ]
    assert len(pytest_steps) == 1, "use one auditable scoped Python contract slice"
    command = pytest_steps[0]["run"]
    for path in PYTHON_CONTRACTS:
        assert (ROOT / path).is_file(), f"CI references a missing test: {path}"
        assert path in command
    assert "tests/test_normality_ttt_api.py" not in command
    assert re.search(r"(?:^|\s)-r[a-zA-Z]*[saA][a-zA-Z]*(?:\s|$)", command), (
        "pytest must show skip reasons rather than hiding optional tensor skips"
    )
    assert "--junitxml=" in command
    assert "--ignore" not in command and "--deselect" not in command
    assert not re.search(r"(?:^|\s)-k(?:\s|=)", command)


def test_normality_node_slice_installs_web_lock_and_exercises_api_abort_contracts():
    job = _normality_job()
    node_steps = [step for step in job["steps"] if "node " in step.get("run", "")]
    contract_steps = [step for step in node_steps if "--test" in step["run"]]
    assert len(contract_steps) == 1
    node_step = contract_steps[0]
    assert "node --experimental-strip-types --test" in node_step["run"]
    assert node_step.get("working-directory", ".") in {".", "./"}
    for path in NODE_CONTRACTS:
        assert (ROOT / path).is_file(), f"CI references a missing test: {path}"
        assert path in node_step["run"]
    installs = [
        step for step in job["steps"] if re.search(r"\bnpm ci\b", step.get("run", ""))
    ]
    assert len(installs) == 1
    install = installs[0]
    assert "npm ci --prefix web" in install["run"] or (
        install.get("working-directory") == "web" and install["run"].strip() == "npm ci"
    )
    assert job["steps"].index(install) < job["steps"].index(node_step)
    assert (ROOT / "web/package-lock.json").is_file()


def test_normality_lane_is_contract_only_without_hidden_failures_or_external_model_setup():
    job = _normality_job()
    commands = _runs(job)
    lowered = commands.lower()
    assert "continue-on-error" not in job
    assert all("continue-on-error" not in step for step in job["steps"])
    for bypass in ("|| true", "--exit-zero", "--passWithNoTests", "; exit 0"):
        assert bypass not in commands
    assert "secrets." not in json.dumps(job).lower()
    for external in (
        "pip install",
        "uv pip",
        "uv add",
        "hf download",
        "huggingface-cli download",
        "torch.hub",
        "from_pretrained",
        "load_state_dict_from_url",
        "nvidia-smi",
        "--device cuda",
        "--accelerator gpu",
        "wget ",
        "curl ",
    ):
        assert external not in lowered, (
            f"unexpected external setup in contract lane: {external}"
        )
    assert "find_spec" in commands and "torch" in commands
    assert "EXTERNAL_TENSOR_TESTS_SKIPPED" in commands
    assert "REAL_MODEL_NOT_RUN" in commands
    tensor_tests = (ROOT / "tests/test_normality_ttt.py").read_text(encoding="utf-8")
    assert 'pytest.importorskip("torch")' in tensor_tests


def test_normality_lane_preserves_failure_receipts_without_changing_other_jobs():
    job = _normality_job()
    uploads = [
        step
        for step in job["steps"]
        if step.get("uses", "").startswith("actions/upload-artifact@")
    ]
    assert len(uploads) == 1
    assert uploads[0]["if"] == "always()"
    assert uploads[0]["with"]["path"].startswith("output/")
    assert "normality" in uploads[0]["with"]["path"]
    jobs = _workflow()["jobs"]
    assert {"contracts-and-coverage", "type-debt", "normality-contracts"} <= jobs.keys()
    assert jobs["contracts-and-coverage"]["strategy"]["matrix"]["python-version"] == [
        "3.12",
        "3.13",
    ]
    assert jobs["type-debt"]["if"] == "github.event_name == 'workflow_dispatch'"
