import pytest

from tests import test_learning_lifecycle as helper
from visiondata_gate.learning_contracts import CreateLearningCycle, RunLearningRound
from visiondata_gate.learning_service import LearningService, LearningError


def test_normal_mask_requires_current_snapshot_human_authority(tmp_path):
    product = helper.ProductService(tmp_path / "product", recover_interrupted=False)
    try:
        with helper.TestClient(helper.create_app(product)) as client:
            task, preflight, groups = helper.make_task(
                client, product, include_normal=True
            )
            snapshot = product._operator_snapshot_visual_context(helper.ACTOR, task)[2]
            normal = next(
                asset for asset in snapshot.assets if asset.annotation_count == 0
            )
            assert normal.mask_relative_path is None
            declaration = {
                "reviewer_name": "Synthetic normal reviewer",
                "review_note": "Explicitly inspected generated normal image and found no target foreground",
                "expected_asset_sha256": normal.source_sha256,
                "expected_annotation_revision": normal.annotation_revision,
                "expected_annotation_sha256": normal.annotation_document_sha256,
                "operator_attests_no_foreground": True,
            }
            payload = {
                "request_key": "normal-cycle-create-001",
                "expected_preflight_sha256": preflight["receipt_sha256"],
                "groups": groups,
                "review_note": "Authorize local supervised reference data with explicit normal declaration",
                "operator_attests_training_authorized": True,
                "normal_mask_attestations": {normal.asset_id: declaration},
            }
            service = LearningService(product)
            for key, value in (
                ("expected_annotation_revision", normal.annotation_revision + 1),
                ("expected_annotation_sha256", "f" * 64),
            ):
                bad = CreateLearningCycle.model_validate(
                    payload
                    | {
                        "normal_mask_attestations": {
                            normal.asset_id: declaration | {key: value}
                        }
                    }
                )
                with pytest.raises(
                    LearningError, match="NORMAL_MASK_ATTESTATION_STALE"
                ):
                    service.create_cycle(helper.ACTOR, task, bad)
            cycle = service.create_cycle(
                helper.ACTOR, task, CreateLearningCycle.model_validate(payload)
            )
            member = next(
                sample
                for sample in cycle["dataset"]["samples"]
                if sample["sample_id"] == normal.asset_id
            )
            assert member["mask_origin"] == "EXPLICIT_HUMAN_ZERO_MASK"
            assert member["normal_attestation_sha256"]
            original = product._operator_snapshot_visual_context(helper.ACTOR, task)[2]
            assert (
                next(
                    asset
                    for asset in original.assets
                    if asset.asset_id == normal.asset_id
                ).mask_relative_path
                is None
            )
            run = service.run_round(
                helper.ACTOR,
                cycle["cycle_id"],
                RunLearningRound(
                    request_key="normal-training-run-001",
                    expected_cycle_sha256=cycle["receipt_sha256"],
                    task_id=task,
                    expected_preflight_sha256=preflight["receipt_sha256"],
                    groups=groups,
                    normal_mask_attestations={normal.asset_id: declaration},
                    review_note="Run bounded training with explicitly declared negative sample",
                    operator_attests_training_authorized=True,
                ),
            )
            assert run["status"] == "COMPLETED", run
            assert normal.asset_id in run["training"]["training_sample_ids"]
    finally:
        product.close(wait=True)
