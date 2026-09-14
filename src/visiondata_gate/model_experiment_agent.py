"""Governed planning for public-proxy visual model experiments.

This module is intentionally model-runtime agnostic.  It freezes the policy
that may be a local PyTorch worker can update weights from, records which
candidate workers were rejected, and keeps optimization convergence separate
from public-development effectiveness and industrial acceptance.
"""

from __future__ import annotations

import hashlib
import hmac
import math
import re
from typing import Any, Callable, Iterable, Sequence

from .audit_envelope import canonical_jcs_bytes
from .runtime_models import RuntimeEvent, RuntimeStage, RuntimeStatus


_SHA = re.compile(r"^[0-9a-f]{64}$")
_VISA_ID = re.compile(r"^visa_[0-9a-f]{24}$")
_MULTISCALE_ARCHITECTURE = "YOLO26N_CLASSIFICATION_MULTISCALE_FEATURE_AUTOENCODER"
_MULTISCALE_FEATURE_LAYERS = (4, 6, 9)
_MODEL_PACK_SCHEMA_VERSION = "visiondata-gate.yolo26-normality-model-pack.v2"
_IMAGE_AGGREGATIONS = {
    "max",
    "mean",
    "top_0_1pct",
    "top_0_5pct",
    "top_1pct",
    "top_2pct",
    "top_5pct",
    "top_10pct",
}


def _sha(value: object) -> str:
    return hashlib.sha256(canonical_jcs_bytes(value)).hexdigest()


def _require(condition: bool, code: str) -> None:
    if not condition:
        raise ValueError(code)


def _sealed(value: dict[str, Any]) -> dict[str, Any]:
    stable = {key: item for key, item in value.items() if key != "receipt_sha256"}
    return {**stable, "receipt_sha256": _sha(stable)}


def _validate_seed(value: int, code: str) -> None:
    _require(type(value) is int and 0 <= value <= 2**31 - 1, code)


def assign_model_experiment_roles(
    *,
    train_normal_ids: Sequence[str],
    development_normal_ids: Sequence[str],
    development_anomaly_ids: Sequence[str],
    train_samples: int,
    normal_validation_samples: int,
    split_seed: int,
    model_seed: int,
) -> dict[str, str]:
    """Assign immutable data roles using only ``split_seed`` for ranking."""

    _validate_seed(split_seed, "SPLIT_SEED_INVALID")
    _validate_seed(model_seed, "MODEL_SEED_INVALID")
    _require(type(train_samples) is int and train_samples > 0, "TRAIN_COUNT_INVALID")
    _require(
        type(normal_validation_samples) is int and normal_validation_samples > 0,
        "NORMAL_VALIDATION_COUNT_INVALID",
    )
    groups = (
        list(train_normal_ids),
        list(development_normal_ids),
        list(development_anomaly_ids),
    )
    identifiers = [identifier for group in groups for identifier in group]
    _require(
        bool(identifiers)
        and all(isinstance(value, str) and _VISA_ID.fullmatch(value) for value in identifiers)
        and len(identifiers) == len(set(identifiers)),
        "MODEL_EXPERIMENT_MEMBER_ID_INVALID",
    )
    required_train = train_samples + normal_validation_samples
    _require(len(groups[0]) >= required_train, "INSUFFICIENT_TRAIN_NORMAL_MEMBERS")
    _require(bool(groups[1]) and bool(groups[2]), "DEVELOPMENT_MEMBERS_REQUIRED")
    ranked_train = sorted(
        groups[0],
        key=lambda identifier: hashlib.sha256(
            f"{split_seed}\0{identifier}".encode("utf-8")
        ).hexdigest(),
    )
    selected_train = ranked_train[:train_samples]
    selected_validation = ranked_train[train_samples:required_train]
    return {
        **{identifier: "weight_update_train_normal" for identifier in selected_train},
        **{
            identifier: "checkpoint_validation_normal"
            for identifier in selected_validation
        },
        **{identifier: "development_normal" for identifier in groups[1]},
        **{identifier: "development_anomaly" for identifier in groups[2]},
    }


def build_visa_yolo26_experiment_plan(
    *,
    source_binding_sha256: str,
    source_index_sha256: str,
    max_epochs: int,
    max_wall_seconds: int,
    split_seed: int = 20260913,
    model_seed: int | None = None,
    seed: int | None = None,
) -> dict[str, Any]:
    """Freeze a normal-only YOLO26-feature experiment plan.

    VisA anomaly masks may be used only after checkpoint selection for
    development evaluation.  They are never optimizer inputs or label truth for
    VisionData Gate's own production decisions.
    """

    _require(bool(_SHA.fullmatch(source_binding_sha256)), "SOURCE_BINDING_SHA_INVALID")
    _require(bool(_SHA.fullmatch(source_index_sha256)), "SOURCE_INDEX_SHA_INVALID")
    if model_seed is None:
        model_seed = seed if seed is not None else 20260913
    elif seed is not None:
        _require(seed == model_seed, "MODEL_SEED_ALIAS_CONFLICT")
    _validate_seed(split_seed, "SPLIT_SEED_INVALID")
    _validate_seed(model_seed, "MODEL_SEED_INVALID")
    _require(type(max_epochs) is int and 1 <= max_epochs <= 100, "EPOCH_BUDGET_INVALID")
    _require(
        type(max_wall_seconds) is int and 60 <= max_wall_seconds <= 14_400,
        "WALL_BUDGET_INVALID",
    )
    plan = {
        "schema_version": "visiondata-gate.model-experiment-plan.v1",
        "dataset_id": "VisA",
        "source_binding_sha256": source_binding_sha256,
        "source_index_sha256": source_index_sha256,
        "split_seed": split_seed,
        "model_seed": model_seed,
        "architecture": _MULTISCALE_ARCHITECTURE,
        "feature_layers": list(_MULTISCALE_FEATURE_LAYERS),
        "learning_paradigm": "NORMAL_ONLY_FEATURE_RECONSTRUCTION",
        "selected_workers": [
            {
                "worker": "PublicSourceQualificationWorker",
                "reason_code": "CC_BY_SOURCE_AND_INDEX_BINDING_REQUIRED",
            },
            {
                "worker": "SplitIsolationWorker",
                "reason_code": "WEIGHT_UPDATES_REQUIRE_TRAIN_NORMAL_ONLY",
            },
            {
                "worker": "Yolo26FeatureWorker",
                "reason_code": "LIGHTWEIGHT_PUBLIC_PRETRAINED_VISUAL_BACKBONE",
            },
            {
                "worker": "NormalityHeadTrainerWorker",
                "reason_code": "LEARN_NORMAL_FEATURE_MANIFOLD_WITHOUT_ANOMALY_LABELS",
            },
            {
                "worker": "TopologyStratifiedEvaluatorWorker",
                "reason_code": "REPORT_SINGLE_AND_MULTI_REGION_DEVELOPMENT_STRATA",
            },
        ],
        "rejected_workers": [
            {
                "worker": "SupervisedMaskFineTuneWorker",
                "reason_code": "DEVELOPMENT_LABEL_WEIGHT_UPDATE_FORBIDDEN",
            },
            {
                "worker": "ProductionPromotionWorker",
                "reason_code": "PUBLIC_PROXY_NOT_FACTORY_VALIDATION",
            },
            {
                "worker": "MachineWriteWorker",
                "reason_code": "DIRECT_EQUIPMENT_CONTROL_FORBIDDEN",
            },
        ],
        "budget": {
            "max_epochs": max_epochs,
            "max_wall_seconds": max_wall_seconds,
            "max_gpu_count": 1,
            "external_llm_call_budget": 0,
        },
        "weight_update_policy": {
            "allowed_split": "train",
            "allowed_product_label": "normal",
            "mask_bytes_allowed": False,
        },
        "development_policy": {
            "allowed_split": "test",
            "roles": ["THRESHOLD_CALIBRATION", "HELDOUT_DEVELOPMENT_EVALUATION"],
            "weight_update_allowed": False,
            "mask_role": "PUBLIC_REFERENCE_EVALUATION_ONLY",
        },
        "label_truth_authority": False,
        "machine_write_permitted": False,
        "production_release_allowed": False,
    }
    result = _sealed(plan)
    validate_experiment_plan(result)
    return result


def validate_experiment_plan(plan: dict[str, Any]) -> None:
    _require(isinstance(plan, dict), "MODEL_EXPERIMENT_PLAN_INVALID")
    digest = plan.get("receipt_sha256")
    _require(
        isinstance(digest, str)
        and bool(_SHA.fullmatch(digest))
        and hmac.compare_digest(digest, _sealed(plan)["receipt_sha256"]),
        "MODEL_EXPERIMENT_PLAN_SHA_MISMATCH",
    )
    _require(
        plan.get("schema_version") == "visiondata-gate.model-experiment-plan.v1"
        and plan.get("dataset_id") == "VisA"
        and plan.get("learning_paradigm") == "NORMAL_ONLY_FEATURE_RECONSTRUCTION",
        "MODEL_EXPERIMENT_PLAN_SCOPE_INVALID",
    )
    _require(
        plan.get("architecture") == _MULTISCALE_ARCHITECTURE
        and plan.get("feature_layers") == list(_MULTISCALE_FEATURE_LAYERS),
        "MODEL_EXPERIMENT_FEATURE_LAYERS_INVALID",
    )
    _require(
        type(plan.get("split_seed")) is int
        and 0 <= plan["split_seed"] <= 2**31 - 1
        and type(plan.get("model_seed")) is int
        and 0 <= plan["model_seed"] <= 2**31 - 1,
        "MODEL_EXPERIMENT_SEED_INVALID",
    )
    _require(
        plan.get("production_release_allowed") is False
        and plan.get("machine_write_permitted") is False
        and plan.get("label_truth_authority") is False,
        "MODEL_EXPERIMENT_PLAN_SAFETY_INVALID",
    )
    selected = plan.get("selected_workers")
    rejected = plan.get("rejected_workers")
    _require(
        isinstance(selected, list)
        and isinstance(rejected, list)
        and len({item.get("worker") for item in selected}) == len(selected)
        and len({item.get("worker") for item in rejected}) == len(rejected),
        "MODEL_EXPERIMENT_WORKER_LEDGER_INVALID",
    )
    _require(
        {item.get("worker") for item in selected}.isdisjoint(
            {item.get("worker") for item in rejected}
        ),
        "MODEL_EXPERIMENT_WORKER_CONFLICT",
    )


def validate_model_worker_feature_contract(
    result: dict[str, Any], *, plan: dict[str, Any]
) -> None:
    """Require the worker and checkpoint metadata to match the frozen plan."""

    validate_experiment_plan(plan)
    checkpoint = result.get("checkpoint")
    _require(
        isinstance(result, dict)
        and result.get("architecture") == plan["architecture"]
        and result.get("feature_layers") == plan["feature_layers"]
        and result.get("split_seed") == plan["split_seed"]
        and result.get("model_seed") == plan["model_seed"]
        and isinstance(checkpoint, dict)
        and checkpoint.get("feature_layers") == plan["feature_layers"],
        "MODEL_WORKER_FEATURE_CONTRACT_INVALID",
    )


def validate_model_pack_roundtrip(
    pack: dict[str, Any],
    *,
    worker_result: dict[str, Any],
    actual_checkpoint_sha256: str,
    tensor_validator: Callable[[Any], bool],
) -> None:
    """Validate a locally reloaded, self-contained inference checkpoint."""

    expected_layers = list(_MULTISCALE_FEATURE_LAYERS)
    expected_keys = {str(layer) for layer in expected_layers}
    checkpoint = worker_result.get("checkpoint")
    _require(
        bool(_SHA.fullmatch(actual_checkpoint_sha256))
        and isinstance(checkpoint, dict)
        and isinstance(checkpoint.get("sha256"), str)
        and hmac.compare_digest(
            actual_checkpoint_sha256, checkpoint["sha256"]
        ),
        "MODEL_PACK_SHA_MISMATCH",
    )
    roundtrip = checkpoint.get("roundtrip_validation")
    _require(
        isinstance(roundtrip, dict)
        and roundtrip.get("checkpoint_sha256") == actual_checkpoint_sha256
        and type(roundtrip.get("tensor_count")) is int
        and roundtrip["tensor_count"] > 0
        and roundtrip.get("all_tensors_cpu_and_finite") is True
        and roundtrip.get("backbone_state_dict_reload") == "PASS"
        and isinstance(roundtrip.get("student_state_dict_reload"), dict),
        "MODEL_PACK_ROUNDTRIP_INVALID",
    )
    _require(
        set(roundtrip["student_state_dict_reload"]) == expected_keys
        and all(
            value == "PASS"
            for value in roundtrip["student_state_dict_reload"].values()
        ),
        "MODEL_PACK_ROUNDTRIP_INVALID",
    )
    _require(
        isinstance(pack, dict)
        and pack.get("schema_version")
        == _MODEL_PACK_SCHEMA_VERSION
        and pack.get("architecture") == _MULTISCALE_ARCHITECTURE
        and pack.get("feature_layers") == expected_layers
        and worker_result.get("architecture") == _MULTISCALE_ARCHITECTURE
        and worker_result.get("feature_layers") == expected_layers
        and checkpoint.get("feature_layers") == expected_layers,
        "MODEL_PACK_SCOPE_INVALID",
    )
    _require(
        type(pack.get("split_seed")) is int
        and 0 <= pack["split_seed"] <= 2**31 - 1
        and type(pack.get("model_seed")) is int
        and 0 <= pack["model_seed"] <= 2**31 - 1
        and worker_result.get("split_seed") == pack["split_seed"]
        and worker_result.get("model_seed") == pack["model_seed"],
        "MODEL_PACK_SEED_INVALID",
    )
    image_size = pack.get("image_size")
    image_threshold = pack.get("image_threshold")
    pixel_threshold = pack.get("pixel_threshold")
    _require(
        type(image_size) is int
        and image_size > 0
        and pack.get("selected_image_aggregation") in _IMAGE_AGGREGATIONS
        and type(image_threshold) in {int, float}
        and math.isfinite(float(image_threshold))
        and float(image_threshold) >= 0.0
        and type(pixel_threshold) in {int, float}
        and math.isfinite(float(pixel_threshold))
        and float(pixel_threshold) >= 0.0,
        "MODEL_PACK_THRESHOLD_INVALID",
    )
    normalization = pack.get("input_normalization")
    _require(
        isinstance(normalization, dict)
        and normalization.get("color_space") == "RGB"
        and normalization.get("value_scale") == [0.0, 1.0]
        and normalization.get("resize") == [image_size, image_size]
        and normalization.get("mean") == [0.0, 0.0, 0.0]
        and normalization.get("std") == [1.0, 1.0, 1.0],
        "MODEL_PACK_INPUT_NORMALIZATION_INVALID",
    )
    fusion = pack.get("feature_fusion")
    weights = fusion.get("layer_weights") if isinstance(fusion, dict) else None
    _require(
        isinstance(fusion, dict)
        and fusion.get("strategy") == "equal_weight_mean"
        and fusion.get("target_resolution") == [64, 64]
        and isinstance(weights, dict)
        and set(weights) == expected_keys
        and all(
            type(value) in {int, float}
            and math.isfinite(float(value))
            and math.isclose(
                float(value), 1.0 / len(expected_layers), rel_tol=0.0, abs_tol=1e-12
            )
            for value in weights.values()
        ),
        "MODEL_PACK_FUSION_INVALID",
    )
    backbone = pack.get("backbone")
    provenance = backbone.get("provenance") if isinstance(backbone, dict) else None
    backbone_state = backbone.get("state_dict") if isinstance(backbone, dict) else None
    model_yaml = backbone.get("model_yaml") if isinstance(backbone, dict) else None
    _require(
        isinstance(backbone, dict)
        and isinstance(backbone_state, dict)
        and bool(backbone_state)
        and isinstance(model_yaml, dict)
        and bool(model_yaml)
        and bool(_SHA.fullmatch(str(backbone.get("weights_sha256", ""))))
        and backbone.get("weights_sha256")
        == worker_result.get("backbone_weights_sha256")
        and isinstance(backbone.get("license"), str)
        and bool(backbone["license"].strip())
        and isinstance(provenance, dict)
        and provenance.get("provider") == "Ultralytics"
        and provenance.get("architecture") == "yolo26n-cls"
        and provenance.get("task") == "classify"
        and provenance.get("class_count") == 1000
        and provenance.get("pretraining_dataset") == "ImageNet"
        and provenance.get("source_url")
        == "https://github.com/ultralytics/assets/releases/download/"
        "v8.4.0/yolo26n-cls.pt",
        "MODEL_PACK_BACKBONE_INVALID",
    )
    students = pack.get("students")
    normalizers = pack.get("normalizers")
    _require(
        isinstance(students, dict)
        and set(students) == expected_keys
        and isinstance(normalizers, dict)
        and set(normalizers) == expected_keys,
        "MODEL_PACK_LAYER_SET_INVALID",
    )
    normalizer_fields = {
        "normal_reference_mean",
        "normal_reference_variance",
        "reconstruction_mean",
        "reconstruction_std",
        "gaussian_mean",
        "gaussian_std",
    }
    tensor_values: list[Any] = list(backbone_state.values())
    for layer_key in expected_keys:
        student_state = students[layer_key]
        layer_normalizers = normalizers[layer_key]
        _require(
            isinstance(student_state, dict)
            and bool(student_state)
            and isinstance(layer_normalizers, dict)
            and set(layer_normalizers) == normalizer_fields,
            "MODEL_PACK_LAYER_STATE_INVALID",
        )
        tensor_values.extend(student_state.values())
        tensor_values.extend(layer_normalizers.values())
    _require(
        bool(tensor_values) and all(tensor_validator(value) for value in tensor_values),
        "MODEL_PACK_TENSOR_INVALID",
    )


def validate_weight_update_members(samples: Iterable[dict[str, Any]]) -> list[str]:
    """Return bound IDs only when every optimizer input is train/normal/no-mask."""

    identifiers: list[str] = []
    for sample in samples:
        identifier = sample.get("source_sample_id")
        if (
            not isinstance(identifier, str)
            or not _VISA_ID.fullmatch(identifier)
            or sample.get("split") != "train"
            or sample.get("product_label") != "normal"
            or sample.get("mask_sha256") is not None
        ):
            raise ValueError("WEIGHT_UPDATE_SOURCE_FORBIDDEN")
        identifiers.append(identifier)
    _require(bool(identifiers), "WEIGHT_UPDATE_SOURCE_REQUIRED")
    _require(len(identifiers) == len(set(identifiers)), "WEIGHT_UPDATE_SOURCE_DUPLICATE")
    return identifiers


def validate_development_members(
    samples: Iterable[dict[str, Any]], *, training_ids: set[str]
) -> list[str]:
    """Validate evaluation-only development members and split isolation."""

    identifiers: list[str] = []
    for sample in samples:
        identifier = sample.get("source_sample_id")
        label = sample.get("product_label")
        has_mask = sample.get("mask_sha256") is not None
        if (
            not isinstance(identifier, str)
            or not _VISA_ID.fullmatch(identifier)
            or identifier in training_ids
            or sample.get("split") != "test"
            or label not in {"normal", "anomaly"}
            or (label == "anomaly") != has_mask
        ):
            raise ValueError("DEVELOPMENT_SOURCE_FORBIDDEN")
        identifiers.append(identifier)
    _require(bool(identifiers), "DEVELOPMENT_SOURCE_REQUIRED")
    _require(len(identifiers) == len(set(identifiers)), "DEVELOPMENT_SOURCE_DUPLICATE")
    return identifiers


def _finite_series(values: Sequence[float], code: str) -> list[float]:
    checked = [float(value) for value in values]
    _require(len(checked) >= 2 and all(math.isfinite(value) for value in checked), code)
    return checked


def classify_experiment_outcome(
    *,
    train_losses: Sequence[float],
    normal_validation_losses: Sequence[float],
    image_auroc: float,
    pixel_auroc: float,
    normal_image_false_positive_rate: float,
    image_f1: float,
    pixel_f1: float,
    single_region_recall: float,
    multi_region_recall: float,
) -> dict[str, Any]:
    """Separate optimizer convergence from public-proxy task effectiveness."""

    training = _finite_series(train_losses, "TRAIN_LOSS_INVALID")
    validation = _finite_series(
        normal_validation_losses, "NORMAL_VALIDATION_LOSS_INVALID"
    )
    image_metric, pixel_metric = float(image_auroc), float(pixel_auroc)
    false_positive_rate, image_f1_value, pixel_f1_value = (
        float(normal_image_false_positive_rate),
        float(image_f1),
        float(pixel_f1),
    )
    single_recall, multi_recall = (
        float(single_region_recall),
        float(multi_region_recall),
    )
    _require(
        all(
            math.isfinite(value) and 0.0 <= value <= 1.0
            for value in (
                image_metric,
                pixel_metric,
                false_positive_rate,
                image_f1_value,
                pixel_f1_value,
                single_recall,
                multi_recall,
            )
        ),
        "DEVELOPMENT_METRIC_INVALID",
    )
    converged = (
        training[-1] <= training[0] * 0.75
        and validation[-1] <= validation[0] * 0.75
    )
    effective = (
        converged
        and image_metric >= 0.55
        and pixel_metric >= 0.65
        and false_positive_rate <= 0.30
        and image_f1_value >= 0.50
        and pixel_f1_value >= 0.05
        and single_recall >= 0.30
        and multi_recall >= 0.30
    )
    return {
        "optimization_status": "CONVERGED" if converged else "NOT_ESTABLISHED",
        "effectiveness_status": (
            "OBSERVED_ON_PUBLIC_DEVELOPMENT_PROXY"
            if effective
            else "NOT_ESTABLISHED"
        ),
        "industrial_acceptance": "HOLD",
        "production_release_allowed": False,
    }


def build_model_experiment_agent_receipt(
    *,
    plan: dict[str, Any],
    events: Sequence[RuntimeEvent],
    execution_result_sha256: str,
    checkpoint_sha256: str,
    outcome: dict[str, Any],
) -> dict[str, Any]:
    """Seal live model-worker events without impersonating a production Gate."""

    validate_experiment_plan(plan)
    _require(bool(_SHA.fullmatch(execution_result_sha256)), "EXECUTION_RESULT_SHA_INVALID")
    _require(bool(_SHA.fullmatch(checkpoint_sha256)), "CHECKPOINT_SHA_INVALID")
    event_list = list(events)
    _require(bool(event_list), "MODEL_AGENT_EVENT_CHAIN_EMPTY")
    _require(
        [event.sequence for event in event_list]
        == list(range(1, len(event_list) + 1)),
        "MODEL_AGENT_EVENT_SEQUENCE_INVALID",
    )
    required = (
        RuntimeStage.INTAKE,
        RuntimeStage.PLANNER,
        RuntimeStage.TOOL,
        RuntimeStage.COUNCIL,
        RuntimeStage.JUDGE,
        RuntimeStage.DELIVERY,
    )
    stage_sequence = tuple(dict.fromkeys(event.stage for event in event_list))
    _require(stage_sequence == required, "MODEL_AGENT_STAGE_SEQUENCE_INVALID")
    terminal = {
        RuntimeStatus.SUCCESS,
        RuntimeStatus.WARNING,
        RuntimeStatus.ERROR,
        RuntimeStatus.SKIPPED,
    }
    _require(
        all(event.status in terminal for event in event_list),
        "MODEL_AGENT_EVENT_NONTERMINAL",
    )
    _require(
        event_list[-1].stage is RuntimeStage.DELIVERY
        and event_list[-1].status is RuntimeStatus.SUCCESS,
        "MODEL_AGENT_DELIVERY_INCOMPLETE",
    )
    tool_events = [event for event in event_list if event.stage is RuntimeStage.TOOL]
    _require(
        all(event.task_id and event.tool_name for event in tool_events),
        "MODEL_AGENT_TOOL_BINDING_INVALID",
    )
    _require(
        outcome.get("industrial_acceptance") == "HOLD"
        and outcome.get("production_release_allowed") is False,
        "MODEL_AGENT_OUTCOME_SAFETY_INVALID",
    )
    stable = {
        "schema_version": "visiondata-gate.model-experiment-agent-receipt.v1",
        "behavior_scope": "MODEL_EXPERIMENT_WORKER_DECISION_AND_EXECUTION",
        "production_gate_receipt": "NOT_CLAIMED",
        "agent_control_pattern": "INTAKE_PLANNER_TOOL_COUNCIL_JUDGE_DELIVERY",
        "source_binding_sha256": plan["source_binding_sha256"],
        "source_index_sha256": plan["source_index_sha256"],
        "plan_receipt_sha256": plan["receipt_sha256"],
        "feature_layers": list(plan["feature_layers"]),
        "split_seed": plan["split_seed"],
        "model_seed": plan["model_seed"],
        "runtime_event_count": len(event_list),
        "runtime_event_chain_sha256": _sha(
            [event.model_dump(mode="json") for event in event_list]
        ),
        "stage_sequence": [stage.value for stage in stage_sequence],
        "tool_call_count": len(tool_events),
        "model_call_count": 0,
        "execution_result_sha256": execution_result_sha256,
        "checkpoint_sha256": checkpoint_sha256,
        "optimization_status": outcome["optimization_status"],
        "effectiveness_status": outcome["effectiveness_status"],
        "final_disposition": "HOLD",
        "label_truth_authority": False,
        "machine_write_permitted": False,
        "production_release_allowed": False,
    }
    return _sealed(stable)


__all__ = [
    "build_model_experiment_agent_receipt",
    "build_visa_yolo26_experiment_plan",
    "assign_model_experiment_roles",
    "classify_experiment_outcome",
    "validate_development_members",
    "validate_experiment_plan",
    "validate_model_pack_roundtrip",
    "validate_model_worker_feature_contract",
    "validate_weight_update_members",
]
