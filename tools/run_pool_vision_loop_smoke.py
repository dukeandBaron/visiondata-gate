"""Two bounded synthetic rounds through real workbook/Gate/pool/YOLO services."""

from __future__ import annotations

import argparse
from io import BytesIO
import json
from pathlib import Path
import time
import hashlib

import numpy as np
from PIL import Image

from visiondata_gate.data_pool import (
    CreateDataPoolRequest,
    CreateDataPoolVersionRequest,
    DataPoolService,
)
from visiondata_gate.learning_projection import learning_readiness
from visiondata_gate.local_model_registry import (
    CreateVisionTrainingRun,
    LocalVisionModelService,
    ProbeVisionRuntime,
    RegisterPoolDetectionDataset,
    RegisterVisionRuntime,
    ReviewVisionFeedback,
    SelectVisionModel,
)
from visiondata_gate.operator_workspace import (
    OperatorImageStore,
    SaveAnnotationsRequest,
)
from visiondata_gate.product_models import (
    AuthorizeOperatorProjectSnapshotRequest,
    CreateProjectRequest,
    CreateTaskRequest,
    CreateUserRequest,
    CreateWorkspaceRequest,
    TaskInterventionRequest,
)
from visiondata_gate.product_service import ProductService


COMMON = {
    "reviewer_identity": "Synthetic protocol operator",
    "note": "Explicit synthetic workflow verification; no private data or industrial accuracy claim",
}


def _add_samples(operator, actor, workspace, project, specs, reviews, groups):
    for seed, split in specs:
        rng = np.random.default_rng(seed)
        pixels = np.zeros((64, 64, 3), dtype=np.int16) + (70, 120, 150)
        pixels[16:32, 16:32] = (190, 80, 70)
        pixels += rng.integers(-45, 46, size=pixels.shape)
        buffer = BytesIO()
        Image.fromarray(np.clip(pixels, 0, 255).astype(np.uint8)).save(
            buffer, format="PNG"
        )
        asset = operator.add_image(
            actor,
            workspace,
            project_id=project,
            filename=f"synthetic-{seed}.png",
            data=buffer.getvalue(),
        )
        state = operator.save_annotations(
            actor,
            workspace,
            asset.asset_id,
            SaveAnnotationsRequest(
                expected_revision=0,
                annotations=[
                    {
                        "annotation_id": "synthetic-defect",
                        "label": "defect",
                        "x": 0.25,
                        "y": 0.25,
                        "width": 0.25,
                        "height": 0.25,
                    }
                ],
            ),
        )
        reviews.append(
            {
                "asset_id": asset.asset_id,
                "split": split,
                "category": "defect",
                "annotation_requirement": "REQUIRED",
                "human_review": {
                    "reviewer_name": "Synthetic protocol operator",
                    "note": "Reviewed explicitly generated square annotation",
                    "expected_asset_sha256": asset.source_sha256,
                    "expected_annotation_revision": state.revision,
                    "expected_annotation_sha256": state.document_sha256,
                    "operator_attests_reviewed": True,
                },
            }
        )
        groups[asset.asset_id] = f"synthetic-acquisition-{seed}"


def _pool_dataset(
    product,
    service,
    operator,
    actor,
    workspace,
    project,
    reviews,
    groups,
    number,
    previous,
):
    grant = product.authorize_operator_project_snapshot(
        actor,
        AuthorizeOperatorProjectSnapshotRequest(
            workspace_id=workspace,
            project_id=project,
            operator_attests_authorized_use=True,
            acceptance_requirements={
                "schema_version": "visiondata-gate.operator-acceptance-requirements.v1",
                "purpose_description": "Synthetic detector feedback workflow validation",
                "category_vocabulary": ["defect"],
                "samples": reviews,
            },
        ),
        operator,
    )
    task = product.create_task(
        actor,
        CreateTaskRequest(
            project_id=project,
            goal="Verify synthetic detection source before pool entry",
            source_kind="local_authorized_directory",
            source_id=grant.source_id,
            plan_approval_required=True,
        ),
        auto_start=False,
    )
    product.intervene_task(
        actor,
        task.task_id,
        TaskInterventionRequest(
            action="approve_plan",
            note="Explicit synthetic operator approval for this frozen Gate",
        ),
        start_approved_task=False,
    )
    product.run_task_sync(task.task_id)
    gate = product._annotation_context(actor, task.task_id)[4]
    if gate.decision.value != "PASS" or gate.findings:
        raise ValueError("ACTUAL_SYNTHETIC_GATE_NOT_PASS")
    readiness = learning_readiness(product, actor, task.task_id)
    snap = product._operator_snapshot_visual_context(actor, task.task_id)[2]
    members = [
        {
            "sample_id": a.asset_id,
            "expected_asset_sha256": a.source_sha256,
            "expected_annotation_revision": a.annotation_revision,
            "expected_annotation_sha256": a.annotation_document_sha256,
            "disposition": "QUALIFIED_CANDIDATE",
            "repair_action": "NONE",
            "repair_result": "NOT_APPLICABLE",
            "decision_note": "Reviewed actual Gate evidence and generated labels",
        }
        for a in snap.assets
    ]
    request = {
        "request_key": f"reviewed-pool-{number:04d}",
        "expected_readiness_sha256": readiness["receipt_sha256"],
        "reviewer_name": "Synthetic protocol operator",
        "review_note": "Reviewed all frozen synthetic samples and real Gate outcome",
        "operator_attests_reviewed": True,
        "members": members,
    }
    pool_service = DataPoolService(product)
    if previous is None:
        projection = pool_service.create_pool(
            actor, task.task_id, CreateDataPoolRequest(**request)
        )
    else:
        pool_service.create_version(
            actor,
            previous["pool"]["pool_id"],
            CreateDataPoolVersionRequest(
                **request,
                expected_pool_sha256=previous["pool"]["receipt_sha256"],
                expected_parent_version_sha256=previous["current_version"][
                    "receipt_sha256"
                ],
                source_task_id=task.task_id,
            ),
        )
        projection = pool_service.get_pool(actor, previous["pool"]["pool_id"])
    dataset = service.register_pool_dataset(
        actor,
        project,
        RegisterPoolDetectionDataset(
            **COMMON,
            request_key=f"pool-detection-{number:04d}",
            pool_id=projection["pool"]["pool_id"],
            version_id=projection["current_version"]["version_id"],
            expected_pool_receipt_sha256=projection["pool"]["receipt_sha256"],
            expected_version_receipt_sha256=projection["current_version"][
                "receipt_sha256"
            ],
            class_names=["defect"],
            groups=groups,
            operator_attests_data_authorized=True,
        ),
    )
    return dataset, projection


def run(root: Path, executable: Path) -> dict:
    root = root.resolve()
    root.mkdir(parents=True, exist_ok=False)
    product = ProductService(root / "product", recover_interrupted=False)
    try:
        actor = product.create_user(
            CreateUserRequest(display_name="Synthetic operator")
        ).user_id
        workspace = product.create_workspace(
            CreateWorkspaceRequest(name="Pool vision loop", owner_user_id=actor)
        ).workspace_id
        project = product.create_project(
            actor,
            CreateProjectRequest(
                workspace_id=workspace,
                name="Synthetic detector loop",
                scenario_profile="industrial",
                source_kind="local_authorized_directory",
            ),
        ).project_id
        operator = OperatorImageStore(product.product_root / "operator_workspace")
        service = LocalVisionModelService(product)
        runtime = service.register_runtime(
            actor,
            project,
            RegisterVisionRuntime(
                **COMMON,
                request_key="pool-runtime-0001",
                display_name="Explicit CPU YOLO runtime",
                executable_path=str(executable.resolve()),
                expected_executable_sha256=hashlib.sha256(
                    executable.read_bytes()
                ).hexdigest(),
                operator_attests_trusted_runtime=True,
                operator_attests_execution_authorized=True,
            ),
        )
        runtime = service.probe_runtime(
            actor,
            project,
            runtime["runtime_id"],
            ProbeVisionRuntime(
                **COMMON,
                request_key="pool-runtime-import-0001",
                expected_runtime_sha256=runtime["runtime_sha256"],
                operator_attests_trusted_runtime=True,
                operator_attests_execution_authorized=True,
                import_check=True,
            ),
        )
        reviews, groups, rounds = [], {}, []
        projection = previous_model = None
        feedback = []
        for number in (1, 2):
            specs = (
                [
                    (1700 + i, s)
                    for i, s in enumerate(
                        (
                            "train",
                            "train",
                            "train",
                            "train",
                            "val",
                            "val",
                            "test",
                            "test",
                        )
                    )
                ]
                if number == 1
                else [(1800, "train"), (1801, "train")]
            )
            _add_samples(operator, actor, workspace, project, specs, reviews, groups)
            dataset, projection = _pool_dataset(
                product,
                service,
                operator,
                actor,
                workspace,
                project,
                reviews,
                groups,
                number,
                projection,
            )
            request = CreateVisionTrainingRun(
                **COMMON,
                request_key=f"pool-training-{number:04d}",
                runtime_id=runtime["runtime_id"],
                expected_runtime_sha256=runtime["runtime_sha256"],
                dataset_id=dataset["dataset_id"],
                expected_dataset_receipt_sha256=dataset["dataset_receipt_sha256"],
                initialization="REGISTERED_WEIGHTS"
                if previous_model
                else "ARCHITECTURE_RANDOM",
                initial_model_id=previous_model["model_id"] if previous_model else None,
                expected_weights_sha256=previous_model["weights_sha256"]
                if previous_model
                else None,
                operator_attests_training_authorized=True,
                operator_attests_trusted_runtime=True,
                operator_attests_trusted_weights=bool(previous_model),
                operator_attests_pickle_load_risk=bool(previous_model),
                ultralytics_license_acknowledged=True,
                responds_to_feedback_ids=[f["feedback_id"] for f in feedback],
                expected_feedback_receipts={
                    f["feedback_id"]: f["receipt_sha256"] for f in feedback
                },
            )
            queued = service.create_training_run(actor, project, request)
            duplicate = service.create_training_run(actor, project, request)
            assert queued["run_id"] == duplicate["run_id"]
            deadline = time.monotonic() + 180
            while True:
                current = service.get_run(actor, project, queued["run_id"])
                if current["status"] not in {"QUEUED", "RUNNING"}:
                    break
                if time.monotonic() > deadline:
                    raise TimeoutError("BOUNDED_SERVICE_WAIT_EXCEEDED")
                time.sleep(0.25)
            if current["status"] != "SUCCEEDED_CANDIDATE":
                raise RuntimeError(
                    "POOL_TRAINING_FAILED:" + str(current.get("error_code"))
                )
            candidates = service.list_feedback(actor, project, current["run_id"])[
                "items"
            ]
            feedback = [
                service.triage_feedback(
                    actor,
                    project,
                    current["run_id"],
                    item["feedback_id"],
                    ReviewVisionFeedback(
                        **COMMON,
                        request_key=f"triage-{item['feedback_id']}",
                        expected_run_sha256=current["receipt_sha256"],
                        expected_feedback_sha256=item["receipt_sha256"],
                        operator_attests_reviewed=True,
                        classification="HARD_SAMPLE",
                    ),
                )
                for item in candidates
            ]
            previous_model = service.get_model(
                actor, project, current["candidate_model_id"]
            )
            current = service.select_model(
                actor,
                project,
                current["run_id"],
                SelectVisionModel(
                    request_key=f"pool-selection-{number:04d}",
                    reviewer_identity=COMMON["reviewer_identity"],
                    note="Synthetic sandbox experiment only; zero mAP is not production qualification",
                    expected_run_sha256=current["receipt_sha256"],
                    operator_attests_reviewed=True,
                    action="APPROVE_SANDBOX" if number == 1 else "REJECT",
                    expected_candidate_weights_sha256=previous_model["weights_sha256"],
                ),
            )
            rounds.append(
                {
                    "dataset": dataset,
                    "pool": projection,
                    "run": current,
                    "feedback": feedback,
                }
            )
            (root / f"round-{number}.json").write_text(
                json.dumps(rounds[-1], ensure_ascii=False, indent=2), encoding="utf-8"
            )
            print(
                json.dumps(
                    {
                        "round": number,
                        "status": current["status"],
                        "feedback_count": len(feedback),
                        "selection": current["selection"],
                    }
                ),
                flush=True,
            )
        receipt = {
            "schema_version": "visiondata-gate.pool-vision-loop-smoke.v1",
            "scope": "ISOLATED_SYNTHETIC_ACTUAL_GATE_POOL_YOLO_SERVICE",
            "runtime": runtime,
            "rounds": rounds,
            "weight_downloaded": False,
            "private_data_used": False,
            "ttt_implemented": False,
            "test_prediction_feedback": False,
            "production_release_allowed": False,
            "industrial_effectiveness_status": "NOT_EVALUATED",
        }
        (root / "POOL_VISION_LOOP_SMOKE.json").write_text(
            json.dumps(receipt, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        return receipt
    finally:
        product.close(wait=True)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-root", type=Path, required=True)
    parser.add_argument("--python-executable", type=Path, required=True)
    args = parser.parse_args()
    result = run(args.output_root, args.python_executable)
    print(
        json.dumps(
            {
                "completed_rounds": len(result["rounds"]),
                "result": str(args.output_root / "POOL_VISION_LOOP_SMOKE.json"),
            }
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
