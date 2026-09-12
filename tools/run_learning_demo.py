"""Run a synthetic, authenticated loopback HTTP reference-learning workflow.

No test modules, TestClient, direct service mutations, external model calls,
browser, installer, or industrial data are used. The subprocess owns all state
inside one newly created output root. Human declarations are synthetic actors.
"""

from __future__ import annotations

import argparse
import hashlib
from io import BytesIO
import json
import os
from pathlib import Path
import re
import secrets
import socket
import stat
import subprocess
import sys
import threading
import time

import httpx
import numpy as np
from PIL import Image


WORKSPACE = "wsp_local_demo"
ACTOR = "usr_local_demo"
TEST_ACTOR = "SYNTHETIC_TEST_ACTOR"
TOOLS = [
    "image_quality",
    "duplicate_leakage",
    "annotation_integrity",
    "coverage_matrix",
    "governance_audit",
]
TRAINING = {"epochs": 250, "learning_rate": 1.5, "max_wall_seconds": 20.0}
SCOPE = "SYNTHETIC_LOCAL_HTTP_REFERENCE_LEARNING"
ENV_ALLOWLIST = (
    "SystemRoot",
    "SYSTEMROOT",
    "WINDIR",
    "windir",
    "COMSPEC",
    "ComSpec",
    "SYSTEMDRIVE",
    "SystemDrive",
    "PATHEXT",
    "NUMBER_OF_PROCESSORS",
)


class DemoError(RuntimeError):
    """A safe, bounded code; no response body, token, or local path is included."""


def no_links(path: Path) -> None:
    for component in (path, *path.parents):
        try:
            metadata = component.lstat()
        except FileNotFoundError:
            continue
        if stat.S_ISLNK(metadata.st_mode) or getattr(
            metadata, "st_file_attributes", 0
        ) & getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0x400):
            raise DemoError("OUTPUT_LINK_OR_REPARSE")


def new_output_root(value: Path) -> Path:
    root = Path(os.path.abspath(value))
    no_links(root)
    if root.exists():
        raise DemoError("OUTPUT_ROOT_EXISTS")
    if not root.parent.is_dir():
        raise DemoError("OUTPUT_PARENT_MUST_EXIST")
    root.mkdir(exist_ok=False)
    for name in ("product", "temp", "resources", "appdata", "localappdata"):
        (root / name).mkdir()
    return root.resolve(strict=True)


def child_environment(root: Path, token: str, source=None) -> dict[str, str]:
    source = os.environ if source is None else source
    environment = {key: source[key] for key in ENV_ALLOWLIST if key in source}
    system_root = environment.get("SystemRoot", environment.get("SYSTEMROOT", ""))
    paths = [str(Path(sys.executable).parent)]
    if system_root:
        paths.extend((str(Path(system_root) / "System32"), system_root))
    environment.update(
        {
            "PATH": os.pathsep.join(paths),
            "TEMP": str(root / "temp"),
            "TMP": str(root / "temp"),
            "APPDATA": str(root / "appdata"),
            "LOCALAPPDATA": str(root / "localappdata"),
            "PYTHONUTF8": "1",
            "PYTHONIOENCODING": "utf-8",
            "PYTHONNOUSERSITE": "1",
            "PYTHONDONTWRITEBYTECODE": "1",
            "OMP_NUM_THREADS": "1",
            "OPENBLAS_NUM_THREADS": "1",
            "MKL_NUM_THREADS": "1",
            "VISIONDATA_PRODUCT_ROOT": str(root / "product"),
            "VISIONDATA_RESOURCE_ROOT": str(root / "resources"),
            "VISIONDATA_SESSION_TOKEN": token,
            "VISIONDATA_SESSION_ACTOR_USER_ID": ACTOR,
            "VISIONDATA_INSECURE_TEST_ACTOR_HEADER_BYPASS": "false",
            "VISIONDATA_AGENTTEAMS_MODE": "off",
            "VISIONDATA_INCIDENT_MODEL_MODE": "off",
            "VISIONDATA_MEMORY_ADMISSION_MODE": "strict_envelope_v1",
            "VISIONDATA_WEB_ORIGINS": "",
        }
    )
    return environment


def free_loopback_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as listener:
        listener.bind(("127.0.0.1", 0))
        return int(listener.getsockname()[1])


def serve_child(port: int) -> int:
    """Private subprocess mode; closing its parent-owned stdin requests shutdown."""
    import uvicorn

    sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
    # api.py exposes one initialized app. Using its factory would create a second
    # ProductService in addition to that module-level app, so use the actual app.
    config = uvicorn.Config(
        "visiondata_gate.api:app",
        host="127.0.0.1",
        port=port,
        log_level="critical",
        access_log=False,
        timeout_graceful_shutdown=30,
    )
    server = uvicorn.Server(config)

    def request_shutdown():
        sys.stdin.buffer.read(1)
        server.should_exit = True

    threading.Thread(target=request_shutdown, daemon=True).start()
    server.run()
    return 0


def stop_owned_child(child: subprocess.Popen) -> dict:
    forced = False
    if child.poll() is None:
        try:
            child.stdin.write(b"q")
            child.stdin.flush()
            child.stdin.close()
        except (BrokenPipeError, OSError, ValueError):
            pass
        try:
            child.wait(timeout=40)
        except subprocess.TimeoutExpired:
            forced = True
            child.terminate()
            try:
                child.wait(timeout=10)
            except subprocess.TimeoutExpired:
                child.kill()
                child.wait(timeout=10)
    return {
        "child_exit_code": child.returncode,
        "graceful_shutdown": not forced and child.returncode == 0,
        "forced_own_child_termination": forced,
    }


def generated_image(index: int, variant: int, split: str) -> bytes:
    rng = np.random.default_rng(
        300 + index + (variant * 100 if split == "train" else 0)
    )
    pixels = np.empty((64, 64, 3), dtype=np.int16)
    pixels[:] = (70, 120, 150)
    pixels[16:32, 16:32] = (190, 80, 70)
    pixels += rng.integers(-45, 46, size=pixels.shape)
    output = BytesIO()
    Image.fromarray(np.clip(pixels, 0, 255).astype(np.uint8)).save(output, format="PNG")
    return output.getvalue()


def require(condition, code: str):
    if not condition:
        raise DemoError(code)


class HttpWorkflow:
    def __init__(self, client: httpx.Client, deadline: float):
        self.client = client
        self.deadline = deadline
        self.current_stage = "STARTING"
        self.http_request_count = 0

    def request(self, method, path, *, expected=200, receipt=False, **kwargs):
        require(
            path.startswith("/v1/") and not path.startswith("//"),
            "LOOPBACK_API_PATH_REQUIRED",
        )
        remaining = self.deadline - time.monotonic()
        require(remaining > 0, "DEMO_TIME_BUDGET_EXHAUSTED")
        response = self.client.request(
            method, path, timeout=min(180.0, remaining), **kwargs
        )
        self.http_request_count += 1
        if response.status_code != expected:
            code = "UNEXPECTED_STATUS"
            try:
                candidate = response.json().get("error", {}).get("code", "")
                if isinstance(candidate, str) and re.fullmatch(
                    r"[a-zA-Z0-9_]{1,80}", candidate
                ):
                    code = candidate.upper()
            except (ValueError, AttributeError):
                pass
            raise DemoError(f"HTTP_{response.status_code}_{code}")
        value = response.json()
        if receipt:
            digest = value.get("receipt_sha256")
            require(
                isinstance(digest, str) and re.fullmatch(r"[0-9a-f]{64}", digest),
                "RECEIPT_SHA256_REQUIRED",
            )
            require(
                response.headers.get("etag") == f'"{digest}"', "ETAG_RECEIPT_MISMATCH"
            )
        return value

    def cycle(self, cycle_id):
        return self.request("GET", f"/v1/learning-cycles/{cycle_id}", receipt=True)

    def run(self, run_id):
        return self.request("GET", f"/v1/learning-runs/{run_id}", receipt=True)

    def wait_task(self, task_id, expected):
        while time.monotonic() < self.deadline:
            task = self.request("GET", f"/v1/tasks/{task_id}")
            if task["execution_status"] == expected:
                return task
            require(
                task["execution_status"]
                not in {"FAILED", "CANCELLED", "ARCHIVED", "COMPLETED"},
                "GATE_TASK_UNEXPECTED_TERMINAL_STATE",
            )
            time.sleep(0.15)
        raise DemoError("GATE_TASK_TIMEOUT")


def make_gate_task(flow, *, project_id, samples, groups, variant, nonce):
    flow.current_stage = f"ROUND_{variant + 1}_UPLOAD_AND_ANNOTATE"
    for index, split in enumerate(
        ("train", "train", "val", "test") if variant == 0 else ("train", "train")
    ):
        content = generated_image(index, variant, split)
        uploaded = flow.request(
            "POST",
            f"/v1/operator-workspaces/{WORKSPACE}/assets",
            expected=201,
            params={"project_id": project_id},
            files=[
                ("files", (f"synthetic-{variant}-{index}.png", content, "image/png"))
            ],
        )
        asset = uploaded["assets"][0]
        require(
            asset["source_sha256"] == hashlib.sha256(content).hexdigest(),
            "UPLOADED_IMAGE_SHA_MISMATCH",
        )
        annotated = flow.request(
            "PUT",
            f"/v1/operator-workspaces/{WORKSPACE}/assets/{asset['asset_id']}/annotations",
            json={
                "expected_revision": 0,
                "annotations": [
                    {
                        "annotation_id": "target",
                        "label": "defect",
                        "x": 0.25,
                        "y": 0.25,
                        "width": 0.25,
                        "height": 0.25,
                    }
                ],
            },
        )
        groups[asset["asset_id"]] = f"independent-{split}-{variant}-{index}"
        samples.append(
            {
                "asset_id": asset["asset_id"],
                "split": split,
                "category": "defect",
                "annotation_requirement": "REQUIRED",
                "human_review": {
                    "reviewer_name": TEST_ACTOR,
                    "note": "SYNTHETIC_TEST_ACTOR: known generated square labels; not real human acceptance",
                    "expected_asset_sha256": asset["source_sha256"],
                    "expected_annotation_revision": annotated["revision"],
                    "expected_annotation_sha256": annotated["document_sha256"],
                    "operator_attests_reviewed": True,
                },
            }
        )
    flow.current_stage = f"ROUND_{variant + 1}_FREEZE_AND_APPROVE_GATE_TASK"
    snapshot = flow.request(
        "POST",
        "/v1/data-sources/operator-project-snapshots",
        expected=201,
        json={
            "workspace_id": WORKSPACE,
            "project_id": project_id,
            "operator_attests_authorized_use": True,
            "acceptance_requirements": {
                "schema_version": "visiondata-gate.operator-acceptance-requirements.v1",
                "purpose_description": "Synthetic reference learning only; simulated human declarations and no industrial claims",
                "category_vocabulary": ["defect"],
                "samples": samples,
            },
        },
    )
    task = flow.request(
        "POST",
        "/v1/tasks",
        expected=202,
        headers={"Idempotency-Key": f"{nonce}-gate-{variant}"},
        json={
            "project_id": project_id,
            "goal": "Verify synthetic supervised training data and its true binary labels",
            "source_kind": "local_authorized_directory",
            "source_id": snapshot["source_id"],
            "allowed_tools": TOOLS,
            "plan_approval_required": True,
        },
    )
    task_id = task["task_id"]
    flow.wait_task(task_id, "PLANNED")
    plan = flow.request("GET", f"/v1/tasks/{task_id}/plan")
    require(
        plan["approval_required"] is True and set(plan["allowed_tools"]) == set(TOOLS),
        "PLAN_AUTHORITY_MISMATCH",
    )
    approval = flow.request(
        "POST",
        f"/v1/tasks/{task_id}/interventions",
        expected=201,
        json={
            "action": "approve_plan",
            "note": "SYNTHETIC_TEST_ACTOR approves exactly the five-tool local fixture plan; not production approval",
        },
    )
    completed = flow.wait_task(task_id, "COMPLETED")
    flow.current_stage = f"ROUND_{variant + 1}_COMPUTE_PREFLIGHT"
    preflight = flow.request(
        "GET", f"/v1/tasks/{task_id}/compute-preflight", receipt=True
    )
    require(
        preflight["eligibility"] == "READY_FOR_OFFLINE_HANDOFF",
        "COMPUTE_PREFLIGHT_HOLD",
    )
    return (
        task_id,
        preflight,
        {
            "task_id": task_id,
            "source_id": snapshot["source_id"],
            "status": completed["execution_status"],
            "plan_approval_required": True,
            "approval_binding_sha256": (approval.get("approval_binding") or {}).get(
                "binding_sha256"
            ),
            "preflight_eligibility": preflight["eligibility"],
            "preflight_sha256": preflight["receipt_sha256"],
            "sample_count": len(samples),
            "split_counts": {
                split: sum(item["split"] == split for item in samples)
                for split in ("train", "val", "test")
            },
        },
    )


def safe_evaluation(value):
    return {
        key: value[key]
        for key in (
            "schema_version",
            "split",
            "policy",
            "aggregate",
            "categories",
            "latency",
            "decision",
            "blockers",
        )
    }


def review_and_select(flow, cycle_id, run, nonce):
    flow.current_stage = f"ROUND_{run['round_number']}_SYNTHETIC_FEEDBACK_REVIEW"
    feedback_ids = [item["feedback_id"] for item in run["feedback"]]
    for feedback_id in feedback_ids:
        cycle = flow.cycle(cycle_id)
        run = flow.request(
            "POST",
            f"/v1/learning-cycles/{cycle_id}/runs/{run['run_id']}/feedback/{feedback_id}",
            receipt=True,
            json={
                "request_key": f"{nonce}-{feedback_id}",
                "expected_cycle_sha256": cycle["receipt_sha256"],
                "operator_attests_reviewed": True,
                "classification": "HARD_SAMPLE",
                "review_note": "SYNTHETIC_TEST_ACTOR checked known generated labels; collect new train examples, never ingest held-out data",
            },
        )
    cycle = flow.cycle(cycle_id)
    run = flow.run(run["run_id"])
    action = (
        "APPROVE_SANDBOX" if run["evaluation"]["decision"] == "ELIGIBLE" else "REJECT"
    )
    flow.current_stage = f"ROUND_{run['round_number']}_MEASURED_MODEL_SELECTION"
    cycle = flow.request(
        "POST",
        f"/v1/learning-cycles/{cycle_id}/runs/{run['run_id']}/selection",
        receipt=True,
        json={
            "request_key": f"{nonce}-select-{run['round_number']}",
            "expected_cycle_sha256": cycle["receipt_sha256"],
            "expected_run_sha256": run["receipt_sha256"],
            "action": action,
            "operator_attests_reviewed": True,
            "review_note": "SYNTHETIC_TEST_ACTOR: approve sandbox only when measured default policy is eligible; otherwise retain champion",
        },
    )
    run = flow.run(run["run_id"])
    require(run["selection"]["action"] == action, "SELECTION_RECEIPT_MISMATCH")
    return cycle, run, action


def check_learning_readiness(flow, task_id, preflight, expected_sample_ids):
    flow.current_stage = "READ_LEARNING_READINESS_BEFORE_AUTHORIZATION"
    readiness = flow.request(
        "GET", f"/v1/tasks/{task_id}/learning-readiness", receipt=True
    )
    require(
        readiness["task_id"] == task_id
        and readiness["projection_status"] == "VERIFIED",
        "READINESS_NOT_VERIFIED",
    )
    members = readiness["members"]
    require(
        len(members) == len(expected_sample_ids)
        and {item["sample_id"] for item in members} == set(expected_sample_ids),
        "READINESS_MEMBER_MISMATCH",
    )
    require(
        readiness["preflight_receipt_sha256"] == preflight["receipt_sha256"],
        "READINESS_PREFLIGHT_SHA_MISMATCH",
    )
    require(
        readiness["training_authorized"] is False
        and readiness["production_release_allowed"] is False,
        "READINESS_NOT_TRAINING_AUTHORITY",
    )
    return {
        "task_id": task_id,
        "projection_status": readiness["projection_status"],
        "member_count": len(members),
        "preflight_receipt_sha256": readiness["preflight_receipt_sha256"],
        "preflight_eligibility": readiness["preflight_eligibility"],
        "training_authorized": readiness["training_authorized"],
        "member_readiness_states": sorted(
            {item["readiness_state"] for item in members}
        ),
        "receipt_sha256": readiness["receipt_sha256"],
    }


def link_feedback_followups(
    flow,
    project_id,
    cycle_id,
    run_id,
    feedback_ids,
    task_id,
    preflight,
    new_train_ids,
    nonce,
):
    flow.current_stage = "LINK_NEW_GATE_EVIDENCE_TO_TRIAGED_FEEDBACK"
    links = []
    for feedback_id in feedback_ids:
        cycle = flow.cycle(cycle_id)
        current_run = flow.run(run_id)
        request_key = f"{nonce}-followup-{feedback_id}"
        linked_run = flow.request(
            "POST",
            f"/v1/learning-cycles/{cycle_id}/runs/{run_id}/feedback/{feedback_id}/followup",
            receipt=True,
            json={
                "request_key": request_key,
                "expected_cycle_sha256": cycle["receipt_sha256"],
                "expected_run_sha256": current_run["receipt_sha256"],
                "task_id": task_id,
                "expected_preflight_sha256": preflight["receipt_sha256"],
                "sample_ids": new_train_ids,
                "operator_attests_reviewed": True,
                "review_note": "SYNTHETIC_TEST_ACTOR links new Gate evidence only; this association does not prove any issue was fixed or closed",
            },
        )
        item = next(
            (
                item
                for item in linked_run["feedback"]
                if item["feedback_id"] == feedback_id
            ),
            None,
        )
        require(item is not None, "FOLLOWUP_FEEDBACK_MEMBER_MISSING")
        followup = item["followup"]
        require(
            item["followup_status"] == "NEW_GATE_EVIDENCE_LINKED_NOT_ISSUE_CLOSED"
            and item["followup_task_id"] == task_id,
            "FOLLOWUP_LINK_STATUS_MISMATCH",
        )
        require(
            followup["issue_closed"] is False
            and followup["training_ingestion_allowed"] is False,
            "FOLLOWUP_MUST_NOT_CLOSE_ISSUE_OR_AUTO_INGEST",
        )
        require(
            followup["sample_ids"] == new_train_ids
            and followup["preflight_receipt_sha256"] == preflight["receipt_sha256"],
            "FOLLOWUP_NEW_INPUT_BINDING_MISMATCH",
        )
        operation = flow.request(
            "GET",
            f"/v1/projects/{project_id}/learning-operations/followup/{request_key}",
            receipt=True,
            params={"target_id": feedback_id},
        )
        require(
            operation["lookup_status"] == "FOUND"
            and operation["result_semantics"] == "CURRENT_RESULT"
            and operation["automatic_retry_allowed"] is False,
            "FOLLOWUP_OPERATION_RECONCILIATION_MISMATCH",
        )
        require(
            operation["result_id"] == run_id
            and operation["result_receipt_sha256"] == linked_run["receipt_sha256"]
            and operation["current_result"]["receipt_sha256"]
            == linked_run["receipt_sha256"],
            "FOLLOWUP_OPERATION_CURRENT_RESULT_MISMATCH",
        )
        links.append(
            {
                "feedback_id": feedback_id,
                "run_id": run_id,
                "task_id": task_id,
                "sample_ids": new_train_ids,
                "followup_status": item["followup_status"],
                "issue_closed": followup["issue_closed"],
                "training_ingestion_allowed": followup["training_ingestion_allowed"],
                "followup_receipt_sha256": followup["receipt_sha256"],
                "preflight_receipt_sha256": followup["preflight_receipt_sha256"],
                "review_actor_kind": TEST_ACTOR,
                "operation": {
                    key: operation[key]
                    for key in (
                        "lookup_status",
                        "result_semantics",
                        "automatic_retry_allowed",
                        "result_id",
                        "result_receipt_sha256",
                        "request_sha256",
                        "receipt_sha256",
                    )
                },
            }
        )
    return links


def safe_final_cycle(final):
    return {
        "status": final["status"],
        "champion_model_id": final["champion_model_id"],
        "receipt_sha256": final["receipt_sha256"],
        "round_count": len(final["round_ids"]),
        "epochs_reserved": final["epochs_reserved"],
        "wall_seconds_reserved": final["wall_seconds_reserved"],
        "final_evaluation": safe_evaluation(final["final_evaluation"]),
        "test_feedback_count": len(final["final_evaluation"]["sample_results"]),
        "final_evaluation_sha256": final["final_evaluation_sha256"],
        **{
            key: final[key]
            for key in (
                "final_candidate_model_id",
                "final_candidate_model_sha256",
                "final_baseline_model_id",
                "final_baseline_model_sha256",
                "final_candidate_accepted",
            )
        },
    }


def execute_workflow(flow: HttpWorkflow, result: dict, nonce: str):
    flow.current_stage = "CREATE_SYNTHETIC_PROJECT"
    project = flow.request(
        "POST",
        "/v1/projects",
        expected=201,
        json={
            "workspace_id": WORKSPACE,
            "name": "Synthetic local reference learning",
            "source_kind": "local_authorized_directory",
            "scenario_profile": "industrial",
        },
    )
    project_id = project["project_id"]
    result["project_id"] = project_id
    samples, groups = [], {}
    task_id, preflight, gate = make_gate_task(
        flow,
        project_id=project_id,
        samples=samples,
        groups=groups,
        variant=0,
        nonce=nonce,
    )
    result["gate_tasks"].append(gate)
    result["initial_learning_readiness"] = check_learning_readiness(
        flow, task_id, preflight, set(groups)
    )
    original_holdouts = json.loads(
        json.dumps([item for item in samples if item["split"] in {"val", "test"}])
    )
    flow.current_stage = "CREATE_LEARNING_CYCLE"
    cycle = flow.request(
        "POST",
        f"/v1/tasks/{task_id}/learning-cycles",
        expected=201,
        receipt=True,
        json={
            "request_key": nonce + "-create-cycle",
            "expected_preflight_sha256": preflight["receipt_sha256"],
            "groups": groups,
            "review_note": "SYNTHETIC_TEST_ACTOR explicitly authorizes bounded CPU reference learning on generated labels",
            "operator_attests_training_authorized": True,
            "training": TRAINING,
            "max_rounds": 2,
            "max_total_epochs": 1000,
            "max_total_wall_seconds": 120.0,
        },
    )
    cycle_id = cycle["cycle_id"]
    result["cycle_id"] = cycle_id
    result["initial_holdout_fingerprints"] = cycle["evaluation_fingerprints"]
    for round_number in (1, 2):
        responds_to_feedback_ids = []
        if round_number == 2:
            previous_sample_ids = set(groups)
            task_id, preflight, gate = make_gate_task(
                flow,
                project_id=project_id,
                samples=samples,
                groups=groups,
                variant=1,
                nonce=nonce,
            )
            result["gate_tasks"].append(gate)
            current_holdouts = [
                item for item in samples if item["split"] in {"val", "test"}
            ]
            require(
                current_holdouts == original_holdouts, "ORIGINAL_HOLDOUT_H2_CHANGED"
            )
            new_train_ids = sorted(set(groups) - previous_sample_ids)
            require(
                len(new_train_ids) == 2
                and all(
                    item["split"] == "train"
                    for item in samples
                    if item["asset_id"] in new_train_ids
                ),
                "FOLLOWUP_REQUIRES_EXACT_NEW_TRAIN_MEMBERS",
            )
            first_round = result["rounds"][0]
            require(
                all(
                    item["status"] != "PENDING_HUMAN_REVIEW"
                    for item in first_round["feedback"]
                ),
                "FOLLOWUP_REQUIRES_TRIAGED_FEEDBACK",
            )
            links = link_feedback_followups(
                flow,
                project_id,
                cycle_id,
                first_round["run_id"],
                [item["feedback_id"] for item in first_round["feedback"]],
                task_id,
                preflight,
                new_train_ids,
                nonce,
            )
            result["feedback_followups"] = links
            responds_to_feedback_ids = [item["feedback_id"] for item in links]
            if links:
                first_round["post_followup_run_receipt_sha256"] = links[-1][
                    "operation"
                ]["result_receipt_sha256"]
        cycle = flow.cycle(cycle_id)
        baseline = flow.request(
            "GET", f"/v1/learning-models/{cycle['champion_model_id']}", receipt=True
        )
        flow.current_stage = f"ROUND_{round_number}_REAL_CPU_TRAINING"
        run = flow.request(
            "POST",
            f"/v1/learning-cycles/{cycle_id}/rounds",
            receipt=True,
            json={
                "request_key": f"{nonce}-round-{round_number}",
                "task_id": task_id,
                "groups": groups,
                "expected_preflight_sha256": preflight["receipt_sha256"],
                "expected_cycle_sha256": cycle["receipt_sha256"],
                "responds_to_feedback_ids": responds_to_feedback_ids,
                "operator_attests_training_authorized": True,
                "review_note": "SYNTHETIC_TEST_ACTOR authorizes one bounded actual CPU training round; held-out labels remain excluded",
            },
        )
        require(run["status"] == "COMPLETED", "LEARNING_ROUND_NOT_COMPLETED")
        require(
            run["responds_to_feedback_ids"] == responds_to_feedback_ids,
            "ROUND_FEEDBACK_RESPONSE_IDS_MISMATCH",
        )
        require(
            run["initial_model_sha256"] == baseline["model_sha256"],
            "APPROVED_BASELINE_SHA_MISMATCH",
        )
        cycle, run, action = review_and_select(flow, cycle_id, run, nonce)
        training = run["training"]
        result["rounds"].append(
            {
                "round_number": run["round_number"],
                "run_id": run["run_id"],
                "status": run["status"],
                "dataset_id": run["dataset_id"],
                "dataset_receipt_sha256": run["dataset_receipt_sha256"],
                "initial_model_id": run["initial_model_id"],
                "initial_model_sha256": run["initial_model_sha256"],
                "model_id": run["model_id"],
                "model_sha256": run["model_sha256"],
                "weights_changed": run["model_sha256"] != run["initial_model_sha256"],
                "continued_from_current_approved_model": True,
                "training": {
                    key: training[key]
                    for key in (
                        "loss_before",
                        "loss_after",
                        "epochs_completed",
                        "training_pixel_count",
                        "elapsed_seconds",
                        "optimizer",
                        "device",
                    )
                },
                "training_sample_count": len(training["training_sample_ids"]),
                "evaluation": safe_evaluation(run["evaluation"]),
                "feedback": [
                    {
                        "feedback_id": item["feedback_id"],
                        "status": item["status"],
                        "classification": item["classification"],
                        "training_ingestion_allowed": item[
                            "training_ingestion_allowed"
                        ],
                    }
                    for item in run["feedback"]
                ],
                "selection_action": action,
                "champion_model_id": cycle["champion_model_id"],
                "run_receipt_sha256": run["receipt_sha256"],
                "responds_to_feedback_ids": run["responds_to_feedback_ids"],
            }
        )
        require(
            cycle["evaluation_fingerprints"] == result["initial_holdout_fingerprints"],
            "FROZEN_HOLDOUT_FINGERPRINT_CHANGED",
        )
    require(
        result["rounds"][0]["dataset_id"] != result["rounds"][1]["dataset_id"],
        "SECOND_ROUND_DATASET_NOT_NEW",
    )
    result["original_holdout_h2_preserved"] = True
    result["holdout_fingerprints_preserved"] = True
    result["round_two_continued_first_candidate"] = (
        result["rounds"][1]["initial_model_sha256"]
        == result["rounds"][0]["model_sha256"]
    )
    cycle = flow.cycle(cycle_id)
    flow.current_stage = "FINALIZE_ONCE_WITH_HELD_OUT_TEST_NO_FEEDBACK"
    final = flow.request(
        "POST",
        f"/v1/learning-cycles/{cycle_id}/finalize",
        receipt=True,
        json={
            "request_key": nonce + "-finalize",
            "expected_cycle_sha256": cycle["receipt_sha256"],
            "operator_attests_reviewed": True,
            "review_note": "SYNTHETIC_TEST_ACTOR consumes the held-out final test once and closes further training; no production authority",
        },
    )
    require(final["status"] == "FINALIZED", "FINALIZATION_NOT_COMPLETED")
    require(
        final["final_evaluation"]["split"] == "test"
        and final["final_evaluation"]["sample_results"] == [],
        "FINAL_TEST_FEEDBACK_MUST_BE_EMPTY",
    )
    require(
        final["production_release_allowed"] is False
        and final["remote_execution_verified"] is False,
        "SCOPE_BOUNDARY_VIOLATION",
    )
    result["final_cycle"] = safe_final_cycle(final)
    result["status"] = "COMPLETED_REFERENCE_WORKFLOW"


def run_demo(root: Path, timeout_seconds: int) -> tuple[int, dict]:
    token = secrets.token_hex(32)
    nonce = "demo-" + secrets.token_hex(12)
    port = free_loopback_port()
    base = f"http://127.0.0.1:{port}"
    result = {
        "schema_version": "visiondata-gate.synthetic-learning-demo.v1",
        "scope": SCOPE,
        "status": "STARTING",
        "human_review_actor_kind": TEST_ACTOR,
        "real_human_acceptance": False,
        "raw_images_transmitted": False,
        "raw_image_boundary": "Six generated PNGs uploaded only to the owned loopback HTTP service; no external model or remote upload",
        "remote_execution_verified": False,
        "remote_job_submitted": False,
        "production_release_allowed": False,
        "industrial_performance_verified": False,
        "reinforcement_learning": False,
        "native_gui_validation": "NOT_RUN",
        "installer_validation": "NOT_RUN",
        "machine_write_permitted": False,
        "training_configuration": TRAINING,
        "evaluation_policy": "UNCHANGED_DEFAULT",
        "limits": {
            "max_rounds": 2,
            "max_total_epochs": 1000,
            "max_total_wall_seconds": 120,
            "demo_timeout_seconds": timeout_seconds,
        },
        "gate_tasks": [],
        "rounds": [],
    }
    child = None
    flow = None
    started = time.monotonic()
    try:
        flags = subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0
        child = subprocess.Popen(
            [
                sys.executable,
                str(Path(__file__).resolve()),
                "--serve-child",
                "--port",
                str(port),
            ],
            cwd=root,
            env=child_environment(root, token),
            stdin=subprocess.PIPE,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            creationflags=flags,
        )
        deadline = started + timeout_seconds
        headers = {"X-VisionData-Session-Token": token, "X-Actor-User-Id": ACTOR}
        with httpx.Client(
            base_url=base, headers=headers, trust_env=False, follow_redirects=False
        ) as client:
            flow = HttpWorkflow(client, deadline)
            ready_deadline = min(deadline, started + 45)
            while time.monotonic() < ready_deadline:
                require(child.poll() is None, "OWNED_SERVER_EXITED_BEFORE_READY")
                try:
                    health = client.get("/v1/health", timeout=1.0)
                    if health.status_code == 200:
                        require(
                            health.json().get("authentication")
                            == "session_token_bound_principal",
                            "SESSION_AUTHENTICATION_NOT_BOUND",
                        )
                        break
                except (httpx.ConnectError, httpx.TimeoutException):
                    pass
                time.sleep(0.15)
            else:
                raise DemoError("OWNED_SERVER_READINESS_TIMEOUT")
            unauthorized = client.get(
                "/v1/projects",
                headers={"X-VisionData-Session-Token": "incorrect-demo-token"},
                timeout=3.0,
            )
            require(unauthorized.status_code == 401, "INVALID_SESSION_NOT_REJECTED")
            flow.request("GET", "/v1/projects", params={"workspace_id": WORKSPACE})
            result["session_authentication"] = (
                "VERIFIED_VALID_TOKEN_ACCEPTED_INVALID_TOKEN_REJECTED"
            )
            execute_workflow(flow, result, nonce)
    except (DemoError, httpx.HTTPError, ValueError, KeyError, OSError) as error:
        result["status"] = "FAILED"
        result["failure_stage"] = flow.current_stage if flow else "STARTING"
        result["failure_code"] = (
            str(error) if isinstance(error, DemoError) else type(error).__name__
        )
    finally:
        if child is not None:
            result["process_cleanup"] = stop_owned_child(child)
        result["elapsed_seconds"] = time.monotonic() - started
        result["http_request_count"] = flow.http_request_count if flow else 0
    if result.get("process_cleanup", {}).get("graceful_shutdown") is not True:
        result["status"] = "FAILED"
        result.setdefault("failure_code", "OWNED_SERVER_NOT_GRACEFULLY_STOPPED")
    encoded = (
        json.dumps(
            result, ensure_ascii=False, sort_keys=True, indent=2, allow_nan=False
        ).encode("utf-8")
        + b"\n"
    )
    require(token.encode() not in encoded, "SESSION_TOKEN_IN_RECEIPT")
    no_links(root / "LEARNING_DEMO_RECEIPT.json")
    with (root / "LEARNING_DEMO_RECEIPT.json").open("xb") as stream:
        stream.write(encoded)
    print(
        json.dumps(
            {
                "status": result["status"],
                "scope": SCOPE,
                "receipt_sha256": hashlib.sha256(encoded).hexdigest(),
                "round_count": len(result["rounds"]),
                "final_cycle_status": result.get("final_cycle", {}).get("status"),
                "failure_stage": result.get("failure_stage"),
                "failure_code": result.get("failure_code"),
            },
            sort_keys=True,
        )
    )
    return (0 if result["status"] == "COMPLETED_REFERENCE_WORKFLOW" else 2), result


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--output-root",
        type=Path,
        help="A new directory below an existing parent; never overwritten",
    )
    parser.add_argument(
        "--timeout-seconds",
        type=int,
        default=240,
        help="Whole demonstration budget: 30..600 seconds (default: 240)",
    )
    parser.add_argument("--serve-child", action="store_true", help=argparse.SUPPRESS)
    parser.add_argument("--port", type=int, help=argparse.SUPPRESS)
    args = parser.parse_args(argv)
    if args.serve_child:
        require(
            args.port is not None and 1 <= args.port <= 65535, "CHILD_PORT_REQUIRED"
        )
        require(
            bool(os.environ.get("VISIONDATA_SESSION_TOKEN")), "CHILD_SESSION_REQUIRED"
        )
        return serve_child(args.port)
    if args.output_root is None:
        parser.error("--output-root is required")
    if not 30 <= args.timeout_seconds <= 600:
        parser.error("--timeout-seconds must be between 30 and 600")
    try:
        root = new_output_root(args.output_root)
        code, _ = run_demo(root, args.timeout_seconds)
        return code
    except DemoError as error:
        print(
            json.dumps({"status": "REFUSED", "failure_code": str(error)}),
            file=sys.stderr,
        )
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
