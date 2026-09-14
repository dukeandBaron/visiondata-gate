"""Normal-only model experiment planning and claim-boundary tests."""

from __future__ import annotations

import hashlib
import importlib.util
import inspect
from pathlib import Path

import pytest

from visiondata_gate.audit_envelope import canonical_jcs_bytes
from visiondata_gate.model_experiment_agent import (
    assign_model_experiment_roles,
    build_model_experiment_agent_receipt,
    build_visa_yolo26_experiment_plan,
    classify_experiment_outcome,
    validate_development_members,
    validate_experiment_plan,
    validate_model_pack_roundtrip,
    validate_model_worker_feature_contract,
    validate_weight_update_members,
)
from visiondata_gate.runtime_models import RuntimeEvent, RuntimeStage, RuntimeStatus


def _sample(identifier: str, *, split: str, label: str, mask: str | None = None):
    return {
        "source_sample_id": identifier,
        "split": split,
        "product_label": label,
        "mask_sha256": mask,
    }


def test_plan_selects_normal_only_learning_and_rejects_supervised_mask_finetune():
    plan = build_visa_yolo26_experiment_plan(
        source_binding_sha256="a" * 64,
        source_index_sha256="b" * 64,
        seed=20260913,
        max_epochs=12,
        max_wall_seconds=1800,
    )
    validate_experiment_plan(plan)
    assert [item["worker"] for item in plan["selected_workers"]] == [
        "PublicSourceQualificationWorker",
        "SplitIsolationWorker",
        "Yolo26FeatureWorker",
        "NormalityHeadTrainerWorker",
        "TopologyStratifiedEvaluatorWorker",
    ]
    rejected = {item["worker"]: item for item in plan["rejected_workers"]}
    assert rejected["SupervisedMaskFineTuneWorker"]["reason_code"] == (
        "DEVELOPMENT_LABEL_WEIGHT_UPDATE_FORBIDDEN"
    )
    assert rejected["ProductionPromotionWorker"]["reason_code"] == (
        "PUBLIC_PROXY_NOT_FACTORY_VALIDATION"
    )
    assert plan["production_release_allowed"] is False
    assert plan["label_truth_authority"] is False
    assert plan["architecture"] == (
        "YOLO26N_CLASSIFICATION_MULTISCALE_FEATURE_AUTOENCODER"
    )
    assert plan["feature_layers"] == [4, 6, 9]
    assert plan["split_seed"] == 20260913
    assert plan["model_seed"] == 20260913


def test_split_seed_controls_roles_while_model_seed_does_not():
    train_ids = [f"visa_{index:024x}" for index in range(1, 13)]
    arguments = {
        "train_normal_ids": train_ids,
        "development_normal_ids": [f"visa_{index:024x}" for index in range(20, 24)],
        "development_anomaly_ids": [f"visa_{index:024x}" for index in range(30, 34)],
        "train_samples": 6,
        "normal_validation_samples": 3,
    }
    baseline = assign_model_experiment_roles(
        **arguments, split_seed=20260913, model_seed=11
    )
    model_only_change = assign_model_experiment_roles(
        **arguments, split_seed=20260913, model_seed=99
    )
    split_change = assign_model_experiment_roles(
        **arguments, split_seed=20260914, model_seed=11
    )

    assert model_only_change == baseline
    assert split_change != baseline


def test_plan_rejects_a_resealed_non_multiscale_feature_contract():
    plan = build_visa_yolo26_experiment_plan(
        source_binding_sha256="a" * 64,
        source_index_sha256="b" * 64,
        seed=20260913,
        max_epochs=12,
        max_wall_seconds=1800,
    )
    plan["feature_layers"] = [9]
    stable = {key: value for key, value in plan.items() if key != "receipt_sha256"}
    plan["receipt_sha256"] = hashlib.sha256(
        canonical_jcs_bytes(stable)
    ).hexdigest()

    with pytest.raises(ValueError, match="MODEL_EXPERIMENT_FEATURE_LAYERS_INVALID"):
        validate_experiment_plan(plan)


def test_worker_result_must_bind_plan_and_checkpoint_to_the_same_feature_layers():
    plan = build_visa_yolo26_experiment_plan(
        source_binding_sha256="a" * 64,
        source_index_sha256="b" * 64,
        seed=20260913,
        max_epochs=12,
        max_wall_seconds=1800,
    )
    result = {
        "architecture": plan["architecture"],
        "feature_layers": [4, 6, 9],
        "split_seed": plan["split_seed"],
        "model_seed": plan["model_seed"],
        "checkpoint": {"feature_layers": [4, 6, 9]},
    }

    validate_model_worker_feature_contract(result, plan=plan)
    result["checkpoint"]["feature_layers"] = [9]
    with pytest.raises(ValueError, match="MODEL_WORKER_FEATURE_CONTRACT_INVALID"):
        validate_model_worker_feature_contract(result, plan=plan)


def test_worker_result_must_bind_both_seeds_to_the_plan():
    plan = build_visa_yolo26_experiment_plan(
        source_binding_sha256="a" * 64,
        source_index_sha256="b" * 64,
        max_epochs=12,
        max_wall_seconds=1800,
        split_seed=20260913,
        model_seed=11,
    )
    result = {
        "architecture": plan["architecture"],
        "feature_layers": plan["feature_layers"],
        "split_seed": plan["split_seed"],
        "model_seed": 12,
        "checkpoint": {"feature_layers": plan["feature_layers"]},
    }

    with pytest.raises(ValueError, match="MODEL_WORKER_FEATURE_CONTRACT_INVALID"):
        validate_model_worker_feature_contract(result, plan=plan)


class _TensorProbe:
    def __init__(self, *, finite: bool = True) -> None:
        self.finite = finite


def _model_pack() -> dict:
    tensor = _TensorProbe()
    normalizer = {
        "normal_reference_mean": tensor,
        "normal_reference_variance": tensor,
        "reconstruction_mean": tensor,
        "reconstruction_std": tensor,
        "gaussian_mean": tensor,
        "gaussian_std": tensor,
    }
    return {
        "schema_version": "visiondata-gate.yolo26-normality-model-pack.v2",
        "architecture": "YOLO26N_CLASSIFICATION_MULTISCALE_FEATURE_AUTOENCODER",
        "feature_layers": [4, 6, 9],
        "split_seed": 20260913,
        "model_seed": 11,
        "image_size": 256,
        "selected_image_aggregation": "top_1pct",
        "image_threshold": 0.4,
        "pixel_threshold": 0.8,
        "input_normalization": {
            "color_space": "RGB",
            "value_scale": [0.0, 1.0],
            "resize": [256, 256],
            "mean": [0.0, 0.0, 0.0],
            "std": [1.0, 1.0, 1.0],
        },
        "feature_fusion": {
            "strategy": "equal_weight_mean",
            "target_resolution": [64, 64],
            "layer_weights": {"4": 1 / 3, "6": 1 / 3, "9": 1 / 3},
        },
        "backbone": {
            "state_dict": {"stem.weight": tensor},
            "model_yaml": {"nc": 1000, "task": "classify"},
            "weights_sha256": "a" * 64,
            "provenance": {
                "provider": "Ultralytics",
                "architecture": "yolo26n-cls",
                "task": "classify",
                "class_count": 1000,
                "pretraining_dataset": "ImageNet",
                "source_url": (
                    "https://github.com/ultralytics/assets/releases/download/"
                    "v8.4.0/yolo26n-cls.pt"
                ),
            },
            "license": "AGPL-3.0-or-Enterprise",
        },
        "students": {
            str(layer): {"network.weight": tensor} for layer in (4, 6, 9)
        },
        "normalizers": {
            str(layer): dict(normalizer) for layer in (4, 6, 9)
        },
    }


def _model_pack_worker_result(checkpoint_sha256: str) -> dict:
    return {
        "architecture": "YOLO26N_CLASSIFICATION_MULTISCALE_FEATURE_AUTOENCODER",
        "feature_layers": [4, 6, 9],
        "split_seed": 20260913,
        "model_seed": 11,
        "backbone_weights_sha256": "a" * 64,
        "checkpoint": {
            "sha256": checkpoint_sha256,
            "feature_layers": [4, 6, 9],
            "roundtrip_validation": {
                "checkpoint_sha256": checkpoint_sha256,
                "tensor_count": 10,
                "all_tensors_cpu_and_finite": True,
                "backbone_state_dict_reload": "PASS",
                "student_state_dict_reload": {"4": "PASS", "6": "PASS", "9": "PASS"},
            },
        },
    }


def test_model_pack_roundtrip_accepts_complete_finite_cpu_tensor_contract():
    digest = "c" * 64
    validate_model_pack_roundtrip(
        _model_pack(),
        worker_result=_model_pack_worker_result(digest),
        actual_checkpoint_sha256=digest,
        tensor_validator=lambda value: (
            isinstance(value, _TensorProbe) and value.finite
        ),
    )


def test_model_pack_accepts_ultralytics_classifier_default_normalization():
    digest = "c" * 64
    pack = _model_pack()
    pack["input_normalization"]["mean"] = [0.0, 0.0, 0.0]
    pack["input_normalization"]["std"] = [1.0, 1.0, 1.0]

    validate_model_pack_roundtrip(
        pack,
        worker_result=_model_pack_worker_result(digest),
        actual_checkpoint_sha256=digest,
        tensor_validator=lambda value: (
            isinstance(value, _TensorProbe) and value.finite
        ),
    )


def test_model_pack_rejects_torchvision_imagenet_normalization_for_yolo26():
    digest = "c" * 64
    pack = _model_pack()
    pack["input_normalization"]["mean"] = [0.485, 0.456, 0.406]
    pack["input_normalization"]["std"] = [0.229, 0.224, 0.225]

    with pytest.raises(
        ValueError, match="MODEL_PACK_INPUT_NORMALIZATION_INVALID"
    ):
        validate_model_pack_roundtrip(
            pack,
            worker_result=_model_pack_worker_result(digest),
            actual_checkpoint_sha256=digest,
            tensor_validator=lambda value: (
                isinstance(value, _TensorProbe) and value.finite
            ),
        )


def test_model_pack_roundtrip_rejects_nonfinite_layer_tensor():
    digest = "c" * 64
    pack = _model_pack()
    pack["normalizers"]["6"]["gaussian_std"] = _TensorProbe(finite=False)

    with pytest.raises(ValueError, match="MODEL_PACK_TENSOR_INVALID"):
        validate_model_pack_roundtrip(
            pack,
            worker_result=_model_pack_worker_result(digest),
            actual_checkpoint_sha256=digest,
            tensor_validator=lambda value: (
                isinstance(value, _TensorProbe) and value.finite
            ),
        )


def test_model_pack_roundtrip_rejects_worker_result_sha_mismatch():
    with pytest.raises(ValueError, match="MODEL_PACK_SHA_MISMATCH"):
        validate_model_pack_roundtrip(
            _model_pack(),
            worker_result=_model_pack_worker_result("d" * 64),
            actual_checkpoint_sha256="c" * 64,
            tensor_validator=lambda value: (
                isinstance(value, _TensorProbe) and value.finite
            ),
        )


def test_model_pack_roundtrip_rejects_failed_state_dict_reload():
    digest = "c" * 64
    worker_result = _model_pack_worker_result(digest)
    worker_result["checkpoint"]["roundtrip_validation"][
        "backbone_state_dict_reload"
    ] = "FAIL"

    with pytest.raises(ValueError, match="MODEL_PACK_ROUNDTRIP_INVALID"):
        validate_model_pack_roundtrip(
            _model_pack(),
            worker_result=worker_result,
            actual_checkpoint_sha256=digest,
            tensor_validator=lambda value: (
                isinstance(value, _TensorProbe) and value.finite
            ),
        )


def test_model_pack_roundtrip_rejects_backbone_weight_identity_mismatch():
    digest = "c" * 64
    pack = _model_pack()
    pack["backbone"]["weights_sha256"] = "b" * 64

    with pytest.raises(ValueError, match="MODEL_PACK_BACKBONE_INVALID"):
        validate_model_pack_roundtrip(
            pack,
            worker_result=_model_pack_worker_result(digest),
            actual_checkpoint_sha256=digest,
            tensor_validator=lambda value: (
                isinstance(value, _TensorProbe) and value.finite
            ),
        )


def test_model_pack_roundtrip_rejects_model_seed_identity_mismatch():
    digest = "c" * 64
    worker_result = _model_pack_worker_result(digest)
    worker_result["model_seed"] = 12

    with pytest.raises(ValueError, match="MODEL_PACK_SEED_INVALID"):
        validate_model_pack_roundtrip(
            _model_pack(),
            worker_result=worker_result,
            actual_checkpoint_sha256=digest,
            tensor_validator=lambda value: (
                isinstance(value, _TensorProbe) and value.finite
            ),
        )


def test_model_pack_roundtrip_rejects_missing_backbone_architecture_config():
    digest = "c" * 64
    pack = _model_pack()
    del pack["backbone"]["model_yaml"]

    with pytest.raises(ValueError, match="MODEL_PACK_BACKBONE_INVALID"):
        validate_model_pack_roundtrip(
            pack,
            worker_result=_model_pack_worker_result(digest),
            actual_checkpoint_sha256=digest,
            tensor_validator=lambda value: (
                isinstance(value, _TensorProbe) and value.finite
            ),
        )


def test_worker_projects_checkpoint_for_parent_validation_without_package_import():
    runner_path = (
        Path(__file__).resolve().parents[1]
        / "tools"
        / "run_visa_yolo26_normality.py"
    )
    spec = importlib.util.spec_from_file_location("visa_yolo26_runner", runner_path)
    assert spec is not None and spec.loader is not None
    runner = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(runner)
    digest = "c" * 64
    validation_view, tensor_count, all_tensors_valid = (
        runner._build_model_pack_validation_view(
            _model_pack(),
            tensor_validator=lambda value: (
                isinstance(value, _TensorProbe) and value.finite
            ),
        )
    )

    assert tensor_count > 0
    assert all_tensors_valid is True
    assert "visiondata_gate" not in inspect.getsource(runner._worker)
    validate_model_pack_roundtrip(
        validation_view,
        worker_result=_model_pack_worker_result(digest),
        actual_checkpoint_sha256=digest,
        tensor_validator=lambda value: value is True,
    )


def test_weight_updates_are_train_normal_only_and_masks_never_enter_optimizer():
    valid = [
        _sample("visa_" + "1" * 24, split="train", label="normal"),
        _sample("visa_" + "2" * 24, split="train", label="normal"),
    ]
    assert validate_weight_update_members(valid) == [item["source_sample_id"] for item in valid]
    for invalid in (
        [_sample("visa_" + "3" * 24, split="test", label="normal")],
        [_sample("visa_" + "4" * 24, split="train", label="anomaly")],
        [_sample("visa_" + "5" * 24, split="train", label="normal", mask="c" * 64)],
    ):
        with pytest.raises(ValueError, match="WEIGHT_UPDATE_SOURCE_FORBIDDEN"):
            validate_weight_update_members(invalid)


def test_development_members_are_disjoint_and_evaluation_only():
    training_ids = {"visa_" + "1" * 24}
    development = [
        _sample("visa_" + "2" * 24, split="test", label="normal"),
        _sample("visa_" + "3" * 24, split="test", label="anomaly", mask="d" * 64),
    ]
    assert validate_development_members(development, training_ids=training_ids) == [
        item["source_sample_id"] for item in development
    ]
    with pytest.raises(ValueError, match="DEVELOPMENT_SOURCE_FORBIDDEN"):
        validate_development_members(
            [_sample("visa_" + "1" * 24, split="test", label="anomaly", mask="e" * 64)],
            training_ids=training_ids,
        )


def test_optimization_convergence_and_detection_effectiveness_are_separate():
    weak = classify_experiment_outcome(
        train_losses=[1.0, 0.7, 0.4],
        normal_validation_losses=[0.9, 0.6, 0.45],
        image_auroc=0.49,
        pixel_auroc=0.48,
        normal_image_false_positive_rate=0.1,
        image_f1=0.7,
        pixel_f1=0.2,
        single_region_recall=0.8,
        multi_region_recall=0.7,
    )
    assert weak["optimization_status"] == "CONVERGED"
    assert weak["effectiveness_status"] == "NOT_ESTABLISHED"
    strong = classify_experiment_outcome(
        train_losses=[1.0, 0.5, 0.2],
        normal_validation_losses=[0.8, 0.4, 0.2],
        image_auroc=0.81,
        pixel_auroc=0.72,
        normal_image_false_positive_rate=0.1,
        image_f1=0.7,
        pixel_f1=0.2,
        single_region_recall=0.8,
        multi_region_recall=0.7,
    )
    assert strong == {
        "optimization_status": "CONVERGED",
        "effectiveness_status": "OBSERVED_ON_PUBLIC_DEVELOPMENT_PROXY",
        "industrial_acceptance": "HOLD",
        "production_release_allowed": False,
    }

    unsafe_threshold = classify_experiment_outcome(
        train_losses=[1.0, 0.5, 0.2],
        normal_validation_losses=[0.8, 0.4, 0.2],
        image_auroc=0.81,
        pixel_auroc=0.72,
        normal_image_false_positive_rate=1.0,
        image_f1=0.7,
        pixel_f1=0.2,
        single_region_recall=0.8,
        multi_region_recall=0.7,
    )
    assert unsafe_threshold["effectiveness_status"] == "NOT_ESTABLISHED"


def test_model_agent_receipt_uses_live_typed_stages_without_claiming_gate():
    plan = build_visa_yolo26_experiment_plan(
        source_binding_sha256="a" * 64,
        source_index_sha256="b" * 64,
        seed=20260913,
        max_epochs=12,
        max_wall_seconds=1800,
    )
    stages = [
        RuntimeStage.INTAKE,
        RuntimeStage.PLANNER,
        RuntimeStage.TOOL,
        RuntimeStage.COUNCIL,
        RuntimeStage.JUDGE,
        RuntimeStage.DELIVERY,
    ]
    events = [
        RuntimeEvent(
            sequence=index,
            phase="verification" if stage is RuntimeStage.DELIVERY else "initial",
            stage=stage,
            actor="fixture-agent",
            action="fixture-action",
            status=RuntimeStatus.SUCCESS,
            summary="fixture terminal event",
            task_id="fixture-tool" if stage is RuntimeStage.TOOL else None,
            tool_name="fixture-tool" if stage is RuntimeStage.TOOL else None,
        )
        for index, stage in enumerate(stages, start=1)
    ]
    receipt = build_model_experiment_agent_receipt(
        plan=plan,
        events=events,
        execution_result_sha256="c" * 64,
        checkpoint_sha256="d" * 64,
        outcome={
            "optimization_status": "CONVERGED",
            "effectiveness_status": "OBSERVED_ON_PUBLIC_DEVELOPMENT_PROXY",
            "industrial_acceptance": "HOLD",
            "production_release_allowed": False,
        },
    )
    assert receipt["production_gate_receipt"] == "NOT_CLAIMED"
    assert receipt["feature_layers"] == [4, 6, 9]
    assert receipt["final_disposition"] == "HOLD"
    assert receipt["tool_call_count"] == 1
