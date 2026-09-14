"""Explicit synthetic service smoke; no private inputs or downloaded weights."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import time

from PIL import Image, ImageDraw

from visiondata_gate.learning_detection_dataset import manifest_sha256
from visiondata_gate.local_model_registry import (
    CreateVisionTrainingRun,
    LocalVisionModelService,
    ProbeVisionRuntime,
    RegisterDetectionDataset,
    RegisterVisionRuntime,
    SelectVisionModel,
)
from visiondata_gate.product_models import (
    CreateProjectRequest,
    CreateUserRequest,
    CreateWorkspaceRequest,
)
from visiondata_gate.product_service import ProductService


def run(root: Path, executable: Path) -> dict:
    root = root.resolve()
    root.mkdir(parents=True, exist_ok=False)
    data = root / "synthetic_source"
    data.mkdir()
    samples = []
    for index, split in enumerate(
        ("train", "train", "train", "train", "val", "val", "test", "test")
    ):
        image = Image.new("RGB", (64, 64), (15 + index * 3, 20, 28))
        x, y, size = 12 + index % 3, 14 + index % 4, 22
        ImageDraw.Draw(image).rectangle(
            (x, y, x + size, y + size), fill=(210, 130 + index * 3, 70)
        )
        path = data / f"sample_{index}.png"
        image.save(path)
        samples.append(
            {
                "sample_id": f"sample_{index}",
                "image_path": path.name,
                "image_sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
                "split": split,
                "group_id": f"synthetic_group_{index}",
                "annotation_revision": 1,
                "boxes": [
                    {
                        "class_id": 0,
                        "x_center": (x + size / 2) / 64,
                        "y_center": (y + size / 2) / 64,
                        "width": size / 64,
                        "height": size / 64,
                    }
                ],
                "reviewer_name": "Synthetic protocol operator",
                "reviewed": True,
            }
        )
    manifest = {
        "schema_version": "visiondata-gate.detection-dataset.v1",
        "source_version": "synthetic-service-smoke-v1",
        "class_names": ["synthetic_square"],
        "samples": samples,
    }
    common = {
        "reviewer_identity": "Synthetic protocol operator",
        "note": "Authorized synthetic CPU service verification; no industrial effect claim",
    }
    product = ProductService(root / "product", recover_interrupted=False)
    try:
        actor = product.create_user(
            CreateUserRequest(display_name="Synthetic operator")
        ).user_id
        workspace = product.create_workspace(
            CreateWorkspaceRequest(name="Vision smoke", owner_user_id=actor)
        )
        project = product.create_project(
            actor,
            CreateProjectRequest(
                workspace_id=workspace.workspace_id, name="Synthetic CPU detection"
            ),
        ).project_id
        service = LocalVisionModelService(product)
        runtime = service.register_runtime(
            actor,
            project,
            RegisterVisionRuntime(
                **common,
                request_key="runtime-register-0001",
                display_name="Explicit external Python",
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
                **common,
                request_key="runtime-import-0001",
                expected_runtime_sha256=runtime["runtime_sha256"],
                operator_attests_trusted_runtime=True,
                operator_attests_execution_authorized=True,
                import_check=True,
            ),
        )
        dataset = service.register_dataset(
            actor,
            project,
            RegisterDetectionDataset(
                **common,
                request_key="dataset-register-0001",
                source_root=str(data),
                manifest=manifest,
                expected_manifest_sha256=manifest_sha256(manifest),
                operator_attests_data_authorized=True,
            ),
        )
        request = CreateVisionTrainingRun(
            **common,
            request_key="cpu-training-0001",
            runtime_id=runtime["runtime_id"],
            expected_runtime_sha256=runtime["runtime_sha256"],
            dataset_id=dataset["dataset_id"],
            expected_dataset_receipt_sha256=dataset["dataset_receipt_sha256"],
            initialization="ARCHITECTURE_RANDOM",
            operator_attests_training_authorized=True,
            operator_attests_trusted_runtime=True,
            ultralytics_license_acknowledged=True,
        )
        queued = service.create_training_run(actor, project, request)
        replay = service.create_training_run(actor, project, request)
        if replay["run_id"] != queued["run_id"]:
            raise AssertionError("idempotent launch changed run identity")
        deadline = time.monotonic() + 180
        while True:
            current = service.get_run(actor, project, queued["run_id"])
            if current["status"] not in {"QUEUED", "RUNNING"}:
                break
            if time.monotonic() > deadline:
                raise TimeoutError("service smoke exceeded bounded wait")
            time.sleep(0.25)
        if current["status"] == "SUCCEEDED_CANDIDATE":
            model = service.get_model(actor, project, current["candidate_model_id"])
            # Engineering success is not a model-accuracy acceptance claim.
            current = service.select_model(
                actor,
                project,
                current["run_id"],
                SelectVisionModel(
                    **common,
                    request_key="reject-smoke-0001",
                    expected_run_sha256=current["receipt_sha256"],
                    operator_attests_reviewed=True,
                    action="REJECT",
                    expected_candidate_weights_sha256=model["weights_sha256"],
                ),
            )
        receipt = {
            "schema_version": "visiondata-gate.local-vision-service-smoke.v1",
            "scope": "ISOLATED_SYNTHETIC_DIRECT_SERVICE",
            "runtime": runtime,
            "dataset": dataset,
            "run": current,
            "idempotent_run_identity": replay["run_id"] == queued["run_id"],
            "weight_downloaded": False,
            "private_data_used": False,
            "production_release_allowed": False,
            "industrial_effectiveness_status": "NOT_EVALUATED",
        }
        (root / "VISION_SERVICE_SMOKE.json").write_text(
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
    receipt = run(args.output_root, args.python_executable)
    print(
        json.dumps(
            {
                "status": receipt["run"]["status"],
                "selection": receipt["run"]["selection"],
                "result": str(args.output_root / "VISION_SERVICE_SMOKE.json"),
            },
            ensure_ascii=False,
        )
    )
    return 0 if receipt["run"]["status"] == "SUCCEEDED_CANDIDATE" else 2


if __name__ == "__main__":
    raise SystemExit(main())
