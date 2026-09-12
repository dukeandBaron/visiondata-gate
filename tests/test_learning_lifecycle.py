"""Real local Gate inputs; all images and labels are synthetic and test-owned."""

from io import BytesIO

import numpy as np
import pytest
from fastapi.testclient import TestClient
from PIL import Image

from visiondata_gate.api import create_app
from visiondata_gate.product_models import CreateTaskRequest
from visiondata_gate.product_service import ProductService

ACTOR = "usr_local_demo"
WORKSPACE = "wsp_local_demo"
HEADERS = {"X-Actor-User-Id": ACTOR}


def make_task(
    client,
    service,
    *,
    project_id=None,
    variant=0,
    previous_task_id=None,
    previous_groups=None,
    include_normal=False,
):
    if project_id is None:
        response = client.post(
            "/v1/projects",
            headers=HEADERS,
            json={
                "workspace_id": WORKSPACE,
                "name": "Synthetic learning protocol",
                "source_kind": "local_authorized_directory",
                "scenario_profile": "industrial",
            },
        )
        assert response.status_code == 201, response.text
        project_id = response.json()["project_id"]
    samples = []
    groups = dict(previous_groups or {})
    if previous_task_id:
        prior = service._operator_snapshot_visual_context(ACTOR, previous_task_id)[2]
        samples = [
            sample.model_dump(mode="json")
            for sample in prior.acceptance_requirements.samples
        ]
    splits = (
        ("train", "train") if previous_task_id else ("train", "train", "val", "test")
    )
    if include_normal:
        splits = (*splits, "train")
    for index, split in enumerate(splits):
        is_normal = include_normal and index == len(splits) - 1
        rng = np.random.default_rng(
            300 + index + (variant * 100 if split == "train" else 0)
        )
        pixels = np.empty((64, 64, 3), dtype=np.int16)
        pixels[:] = (70, 120, 150)
        if not is_normal:
            pixels[16:32, 16:32] = (190, 80, 70)
        pixels += rng.integers(-45, 46, size=pixels.shape)
        buffer = BytesIO()
        Image.fromarray(np.clip(pixels, 0, 255).astype(np.uint8)).save(
            buffer, format="PNG"
        )
        response = client.post(
            f"/v1/operator-workspaces/{WORKSPACE}/assets",
            headers=HEADERS,
            params={"project_id": project_id},
            files=[
                (
                    "files",
                    (
                        f"synthetic-{variant}-{index}.png",
                        buffer.getvalue(),
                        "image/png",
                    ),
                )
            ],
        )
        assert response.status_code == 201, response.text
        asset = response.json()["assets"][0]
        groups[asset["asset_id"]] = f"independent-{split}-{variant}-{index}"
        annotated = client.put(
            f"/v1/operator-workspaces/{WORKSPACE}/assets/{asset['asset_id']}/annotations",
            headers=HEADERS,
            json={
                "expected_revision": 0,
                "annotations": []
                if is_normal
                else [
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
        assert annotated.status_code == 200, annotated.text
        state = annotated.json()
        samples.append(
            {
                "asset_id": asset["asset_id"],
                "split": split,
                "category": "defect",
                "annotation_requirement": "NOT_APPLICABLE" if is_normal else "REQUIRED",
                "human_review": {
                    "reviewer_name": "Synthetic label reviewer",
                    "note": "Generated known square mask for local reference test",
                    "expected_asset_sha256": asset["source_sha256"],
                    "expected_annotation_revision": state["revision"],
                    "expected_annotation_sha256": state["document_sha256"],
                    "operator_attests_reviewed": True,
                },
            }
        )
    snapshot = client.post(
        "/v1/data-sources/operator-project-snapshots",
        headers=HEADERS,
        json={
            "workspace_id": WORKSPACE,
            "project_id": project_id,
            "operator_attests_authorized_use": True,
            "acceptance_requirements": {
                "schema_version": "visiondata-gate.operator-acceptance-requirements.v1",
                "purpose_description": "Synthetic supervised learning protocol; no industrial quality claim",
                "category_vocabulary": ["defect"],
                "samples": samples,
            },
        },
    )
    assert snapshot.status_code == 201, snapshot.text
    task = service.create_task(
        ACTOR,
        CreateTaskRequest(
            project_id=project_id,
            goal="Verify synthetic training data",
            source_kind="local_authorized_directory",
            source_id=snapshot.json()["source_id"],
            plan_approval_required=False,
        ),
        auto_start=False,
    )
    service.run_task_sync(task.task_id)
    preflight = client.get(
        f"/v1/tasks/{task.task_id}/compute-preflight", headers=HEADERS
    ).json()
    assert preflight["eligibility"] == "READY_FOR_OFFLINE_HANDOFF", preflight
    manifest = service._annotation_context(ACTOR, task.task_id)[2]
    assert set(groups) == {sample.sample_id for sample in manifest.samples}
    return task.task_id, preflight, groups


@pytest.fixture
def learning_input(tmp_path):
    service = ProductService(tmp_path / "product", recover_interrupted=False)
    try:
        with TestClient(create_app(service)) as client:
            yield client, service, make_task(client, service)
    finally:
        service.close(wait=True)


def test_learning_service_exists_before_any_execution():
    from visiondata_gate.learning_service import LearningService

    assert callable(LearningService)


def test_real_dataset_train_evaluate_select_finalize(learning_input):
    from visiondata_gate.learning_contracts import (
        CreateLearningCycle,
        RunLearningRound,
        ModelSelection,
        CycleAction,
        FeedbackReview,
    )
    from visiondata_gate.learning_service import LearningService

    client, product, (task_id, preflight, groups) = learning_input
    service = LearningService(product)
    create = CreateLearningCycle(
        request_key="cycle-create-0001",
        expected_preflight_sha256=preflight["receipt_sha256"],
        groups=groups,
        review_note="Authorize the local CPU reference workflow",
        operator_attests_training_authorized=True,
        training={"epochs": 250, "learning_rate": 1.5},
        max_total_epochs=800,
    )
    cycle = service.create_cycle(ACTOR, task_id, create)
    assert service.create_cycle(ACTOR, task_id, create) == cycle
    execute = RunLearningRound(
        request_key="round-execute-001",
        task_id=task_id,
        groups=groups,
        expected_preflight_sha256=preflight["receipt_sha256"],
        expected_cycle_sha256=cycle["receipt_sha256"],
        review_note="Execute one bounded local training round",
        operator_attests_training_authorized=True,
    )
    run = service.run_round(ACTOR, cycle["cycle_id"], execute)
    assert run["status"] == "COMPLETED", run
    assert run["training"]["loss_after"] < run["training"]["loss_before"]
    assert run["model_sha256"] != run["initial_model_sha256"]
    assert run["evaluation"]["decision"] == "ELIGIBLE", run["evaluation"]
    assert service.run_round(ACTOR, cycle["cycle_id"], execute) == run
    # Actual model errors must produce real feedback, not be hidden to force a
    # clean demo. Synthetic masks are independently known in this fixture.
    for item in list(run["feedback"]):
        cycle = service.get_cycle(ACTOR, cycle["cycle_id"])
        run = service.review_feedback(
            ACTOR,
            cycle["cycle_id"],
            run["run_id"],
            item["feedback_id"],
            FeedbackReview(
                request_key="review-" + item["feedback_id"],
                expected_cycle_sha256=cycle["receipt_sha256"],
                review_note="Known generated labels checked; collect similar training examples",
                operator_attests_reviewed=True,
                classification="HARD_SAMPLE",
            ),
        )
    cycle = service.get_cycle(ACTOR, cycle["cycle_id"])
    action = ModelSelection(
        request_key="select-model-0001",
        expected_cycle_sha256=cycle["receipt_sha256"],
        expected_run_sha256=run["receipt_sha256"],
        action="APPROVE_SANDBOX",
        review_note="Reviewed independent validation and sandbox scope",
        operator_attests_reviewed=True,
    )
    cycle = service.select_model(ACTOR, cycle["cycle_id"], run["run_id"], action)
    assert cycle["champion_model_id"] == run["model_id"]
    result = service.finalize(
        ACTOR,
        cycle["cycle_id"],
        CycleAction(
            request_key="finalize-cycle-001",
            expected_cycle_sha256=cycle["receipt_sha256"],
            review_note="Seal held-out test and stop further rounds",
            operator_attests_reviewed=True,
        ),
    )
    assert result["status"] == "FINALIZED"
    assert result["final_evaluation"]["split"] == "test"
    assert result["final_evaluation"]["sample_results"] == []
    assert result["production_release_allowed"] is False


def create_and_run(service, task_id, preflight, groups, *, epochs=250, max_rounds=3):
    from visiondata_gate.learning_contracts import CreateLearningCycle, RunLearningRound

    cycle = service.create_cycle(
        ACTOR,
        task_id,
        CreateLearningCycle(
            request_key="create-learning-001",
            expected_preflight_sha256=preflight["receipt_sha256"],
            groups=groups,
            review_note="Approve synthetic local supervised training",
            operator_attests_training_authorized=True,
            training={"epochs": epochs, "learning_rate": 1.5},
            max_rounds=max_rounds,
            max_total_epochs=1000,
        ),
    )
    run = service.run_round(
        ACTOR,
        cycle["cycle_id"],
        RunLearningRound(
            request_key="run-learning-0001",
            task_id=task_id,
            groups=groups,
            expected_cycle_sha256=cycle["receipt_sha256"],
            expected_preflight_sha256=preflight["receipt_sha256"],
            review_note="Execute first bounded local CPU round",
            operator_attests_training_authorized=True,
        ),
    )
    return cycle, run


def review_and_select(service, cycle_id, run):
    from visiondata_gate.learning_contracts import FeedbackReview, ModelSelection

    assert run["status"] == "COMPLETED", run
    for item in list(run["feedback"]):
        cycle = service.get_cycle(ACTOR, cycle_id)
        run = service.review_feedback(
            ACTOR,
            cycle_id,
            run["run_id"],
            item["feedback_id"],
            FeedbackReview(
                request_key="triage-" + item["feedback_id"],
                expected_cycle_sha256=cycle["receipt_sha256"],
                review_note="Verified generated labels; preserve held-out examples and collect similar new data",
                operator_attests_reviewed=True,
                classification="HARD_SAMPLE",
            ),
        )
    cycle = service.get_cycle(ACTOR, cycle_id)
    action = (
        "APPROVE_SANDBOX" if run["evaluation"]["decision"] == "ELIGIBLE" else "REJECT"
    )
    cycle = service.select_model(
        ACTOR,
        cycle_id,
        run["run_id"],
        ModelSelection(
            request_key="selection-" + run["run_id"],
            expected_cycle_sha256=cycle["receipt_sha256"],
            expected_run_sha256=run["receipt_sha256"],
            action=action,
            review_note="Accept only measured improvement; otherwise retain previous model",
            operator_attests_reviewed=True,
        ),
    )
    return cycle


def test_second_round_continues_selected_weights_and_preserves_holdout(learning_input):
    from visiondata_gate.learning_contracts import RunLearningRound, CycleAction
    from visiondata_gate.learning_service import LearningService, LearningError

    client, product, (task_id, preflight, groups) = learning_input
    service = LearningService(product)
    cycle, first = create_and_run(service, task_id, preflight, groups, max_rounds=2)
    assert first["evaluation"]["decision"] == "ELIGIBLE"
    cycle = review_and_select(service, cycle["cycle_id"], first)
    task2, preflight2, groups2 = make_task(
        client,
        product,
        project_id=cycle["project_id"],
        variant=1,
        previous_task_id=task_id,
        previous_groups=groups,
    )
    request = RunLearningRound(
        request_key="run-learning-0002",
        task_id=task2,
        groups=groups2,
        expected_preflight_sha256=preflight2["receipt_sha256"],
        expected_cycle_sha256=cycle["receipt_sha256"],
        review_note="Train cumulative revised data without changing held-out protocol",
        operator_attests_training_authorized=True,
    )
    second = service.run_round(ACTOR, cycle["cycle_id"], request)
    assert second["status"] == "COMPLETED", second
    assert second["initial_model_sha256"] == first["model_sha256"]
    assert second["dataset_id"] != first["dataset_id"]
    assert second["training"]["training_sample_ids"]
    cycle = review_and_select(service, cycle["cycle_id"], second)
    reloaded = LearningService(product).get_cycle(ACTOR, cycle["cycle_id"])
    assert reloaded == cycle
    with pytest.raises(LearningError, match="CYCLE_BUDGET_EXHAUSTED"):
        service.run_round(
            ACTOR,
            cycle["cycle_id"],
            request.model_copy(
                update={
                    "request_key": "run-over-budget-003",
                    "expected_cycle_sha256": cycle["receipt_sha256"],
                }
            ),
        )
    selected_model = service.get_model(ACTOR, cycle["champion_model_id"])
    expected_test_baseline = (
        selected_model["parent_model_id"] or cycle["initial_model_id"]
    )
    final = service.finalize(
        ACTOR,
        cycle["cycle_id"],
        CycleAction(
            request_key="close-final-test-001",
            expected_cycle_sha256=cycle["receipt_sha256"],
            review_note="Consume final holdout once and close the cycle",
            operator_attests_reviewed=True,
        ),
    )
    assert final["status"] == "FINALIZED"
    assert final["final_candidate_model_id"] == selected_model["model_id"]
    assert final["final_baseline_model_id"] == expected_test_baseline
    assert final["final_candidate_model_sha256"] == selected_model["model_sha256"]
    if final["final_evaluation"]["decision"] == "HOLD":
        assert final["champion_model_id"] == expected_test_baseline
    with pytest.raises(LearningError, match="CYCLE_CLOSED"):
        service.run_round(
            ACTOR,
            cycle["cycle_id"],
            request.model_copy(
                update={
                    "request_key": "run-after-final-004",
                    "expected_cycle_sha256": final["receipt_sha256"],
                }
            ),
        )
