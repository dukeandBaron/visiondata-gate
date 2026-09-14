"""Driver-only regressions; these mocks never claim a real training workflow."""

from __future__ import annotations

import importlib.util
from io import BytesIO
import json
from pathlib import Path
import time

import httpx
import pytest


def _driver():
    path = Path(__file__).resolve().parents[1] / "tools/run_learning_demo.py"
    spec = importlib.util.spec_from_file_location("learning_demo_driver", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_authenticated_startup_project_list_supplies_required_workspace(
    tmp_path, monkeypatch
):
    driver = _driver()
    calls = []

    class OwnedChild:
        def __init__(self, *args, **kwargs):
            self.stdin = BytesIO()
            self.returncode = None

        def poll(self):
            return self.returncode

        def wait(self, timeout):
            self.returncode = 0
            return 0

    class Client:
        def __init__(self, *args, **kwargs):
            assert kwargs["trust_env"] is False
            assert kwargs["follow_redirects"] is False

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

        def get(self, path, **kwargs):
            if path == "/v1/health":
                return httpx.Response(
                    200, json={"authentication": "session_token_bound_principal"}
                )
            assert path == "/v1/projects"
            assert (
                kwargs["headers"]["X-VisionData-Session-Token"]
                == "incorrect-demo-token"
            )
            return httpx.Response(
                401, json={"error": {"code": "local_session_required"}}
            )

        def request(self, method, path, **kwargs):
            calls.append((method, path, kwargs))
            if kwargs.get("params") != {"workspace_id": driver.WORKSPACE}:
                return httpx.Response(422, json={"error": {"code": "invalid_request"}})
            return httpx.Response(200, json=[])

    monkeypatch.setattr(driver.subprocess, "Popen", OwnedChild)
    monkeypatch.setattr(driver, "free_loopback_port", lambda: 23456)
    monkeypatch.setattr(driver.httpx, "Client", Client)
    monkeypatch.setattr(
        driver,
        "execute_workflow",
        lambda flow, result, nonce: result.update(
            status="COMPLETED_REFERENCE_WORKFLOW"
        ),
    )
    code, result = driver.run_demo(tmp_path, 30)
    assert code == 0, result.get("failure_code")
    assert calls[0][0:2] == ("GET", "/v1/projects")
    assert calls[0][2]["params"] == {"workspace_id": driver.WORKSPACE}
    receipt = json.loads(
        (tmp_path / "LEARNING_DEMO_RECEIPT.json").read_text(encoding="utf-8")
    )
    assert receipt["process_cleanup"]["graceful_shutdown"] is True
    assert receipt["real_human_acceptance"] is False


def test_child_environment_excludes_parent_model_and_private_configuration(tmp_path):
    driver = _driver()
    environment = driver.child_environment(
        tmp_path,
        "in-memory-test-token",
        {
            "SystemRoot": "C:/Windows",
            "OPENAI_API_KEY": "not-for-child",
            "HTTP_PROXY": "https://outside.invalid",
            "PYTHONPATH": "other-source",
            "VISIONDATA_PRODUCT_ROOT": "private-state",
            "VISIONDATA_INCIDENT_MODEL_MODE": "live",
        },
    )
    assert not {"OPENAI_API_KEY", "HTTP_PROXY", "PYTHONPATH"} & environment.keys()
    assert environment["VISIONDATA_INCIDENT_MODEL_MODE"] == "off"
    assert environment["VISIONDATA_PRODUCT_ROOT"] == str(tmp_path / "product")


@pytest.mark.parametrize("execution_status", ["PLANNED", "COMPLETED"])
def test_task_poll_uses_task_record_execution_status(monkeypatch, execution_status):
    driver = _driver()
    flow = driver.HttpWorkflow(None, time.monotonic() + 5)
    task = {"task_id": "synthetic-task", "execution_status": execution_status}
    monkeypatch.setattr(flow, "request", lambda *args, **kwargs: task)
    assert flow.wait_task("synthetic-task", execution_status) == task


def test_task_poll_rejects_failed_execution_status(monkeypatch):
    driver = _driver()
    flow = driver.HttpWorkflow(None, time.monotonic() + 5)
    monkeypatch.setattr(
        flow, "request", lambda *args, **kwargs: {"execution_status": "FAILED"}
    )
    with pytest.raises(driver.DemoError, match="GATE_TASK_UNEXPECTED_TERMINAL_STATE"):
        flow.wait_task("synthetic-task", "COMPLETED")


def test_learning_readiness_checks_exact_members_preflight_and_no_authority():
    driver = _driver()
    assert callable(getattr(driver, "check_learning_readiness", None)), (
        "readiness seam is missing"
    )
    readiness = {
        "projection_status": "VERIFIED",
        "task_id": "task-one",
        "preflight_receipt_sha256": "a" * 64,
        "preflight_eligibility": "READY_FOR_OFFLINE_HANDOFF",
        "training_authorized": False,
        "production_release_allowed": False,
        "receipt_sha256": "b" * 64,
        "members": [
            {
                "sample_id": name,
                "split": "train",
                "readiness_state": "GATE_ELIGIBLE_NOT_TRAINING_APPROVED",
            }
            for name in ("sample-a", "sample-b")
        ],
    }

    class Flow:
        def request(self, method, path, **kwargs):
            assert (method, path) == ("GET", "/v1/tasks/task-one/learning-readiness")
            assert kwargs["receipt"] is True
            return readiness

    summary = driver.check_learning_readiness(
        Flow(), "task-one", {"receipt_sha256": "a" * 64}, {"sample-a", "sample-b"}
    )
    assert summary["member_count"] == 2
    assert summary["training_authorized"] is False
    readiness["training_authorized"] = True
    with pytest.raises(driver.DemoError, match="READINESS_NOT_TRAINING_AUTHORITY"):
        driver.check_learning_readiness(
            Flow(), "task-one", {"receipt_sha256": "a" * 64}, {"sample-a", "sample-b"}
        )


def test_followup_links_refresh_authority_and_lookup_current_result():
    driver = _driver()
    assert callable(getattr(driver, "link_feedback_followups", None)), (
        "followup seam is missing"
    )
    feedback_ids = ["feedback_" + f"{number:024x}" for number in (1, 2)]
    calls = []

    class Flow:
        count = 0

        def cycle(self, cycle_id):
            return {"receipt_sha256": f"cycle-sha-{self.count}"}

        def run(self, run_id):
            return {"run_id": run_id, "receipt_sha256": f"run-sha-{self.count}"}

        def request(self, method, path, **kwargs):
            calls.append((method, path, kwargs))
            if method == "POST":
                body = kwargs["json"]
                assert body["expected_cycle_sha256"] == f"cycle-sha-{self.count}"
                assert body["expected_run_sha256"] == f"run-sha-{self.count}"
                assert body["sample_ids"] == ["new-train-a", "new-train-b"]
                feedback_id = path.split("/")[-2]
                self.count += 1
                self.latest = {
                    "run_id": "run-first",
                    "receipt_sha256": f"run-sha-{self.count}",
                    "feedback": [
                        {
                            "feedback_id": feedback_id,
                            "followup_status": "NEW_GATE_EVIDENCE_LINKED_NOT_ISSUE_CLOSED",
                            "followup_task_id": "task-new",
                            "followup": {
                                "issue_closed": False,
                                "training_ingestion_allowed": False,
                                "sample_ids": body["sample_ids"],
                                "receipt_sha256": "c" * 64,
                                "preflight_receipt_sha256": "d" * 64,
                            },
                        }
                    ],
                }
                return self.latest
            assert path.startswith(
                "/v1/projects/project-one/learning-operations/followup/"
            )
            assert kwargs["params"]["target_id"] in feedback_ids
            return {
                "lookup_status": "FOUND",
                "result_semantics": "CURRENT_RESULT",
                "automatic_retry_allowed": False,
                "result_id": "run-first",
                "result_receipt_sha256": self.latest["receipt_sha256"],
                "current_result": self.latest,
                "request_sha256": "e" * 64,
                "receipt_sha256": "f" * 64,
            }

    links = driver.link_feedback_followups(
        Flow(),
        "project-one",
        "cycle-one",
        "run-first",
        feedback_ids,
        "task-new",
        {"receipt_sha256": "d" * 64},
        ["new-train-a", "new-train-b"],
        "demo-test-request-0001",
    )
    assert [item["feedback_id"] for item in links] == feedback_ids
    assert all(item["issue_closed"] is False for item in links)
    assert all(item["operation"]["automatic_retry_allowed"] is False for item in links)
    assert [method for method, _, _ in calls] == ["POST", "GET", "POST", "GET"]


def test_final_summary_distinguishes_finalized_from_candidate_acceptance():
    driver = _driver()
    assert callable(getattr(driver, "safe_final_cycle", None)), (
        "final candidate binding summary is missing"
    )
    evaluation = {key: {} for key in ("policy", "aggregate", "categories", "latency")}
    evaluation.update(
        schema_version="test-evaluation",
        split="test",
        decision="HOLD",
        blockers=["INSUFFICIENT_DICE_GAIN"],
        sample_results=[],
    )
    final = {
        "status": "FINALIZED",
        "champion_model_id": "baseline",
        "receipt_sha256": "a" * 64,
        "round_ids": ["round-1", "round-2"],
        "epochs_reserved": 500,
        "wall_seconds_reserved": 40,
        "final_evaluation": evaluation,
        "final_evaluation_sha256": "b" * 64,
        "final_candidate_model_id": "candidate",
        "final_candidate_model_sha256": "c" * 64,
        "final_baseline_model_id": "baseline",
        "final_baseline_model_sha256": "d" * 64,
        "final_candidate_accepted": False,
    }
    summary = driver.safe_final_cycle(final)
    assert summary["status"] == "FINALIZED"
    assert summary["final_candidate_accepted"] is False
    assert summary["final_candidate_model_id"] == "candidate"
    assert summary["final_baseline_model_sha256"] == "d" * 64
