"""Three-seed model-stability evidence contract tests."""

from __future__ import annotations

import copy
import hashlib
import json
from pathlib import Path
import subprocess
import sys

import pytest

from visiondata_gate import model_experiment_agent as model_experiment_agent_module
from visiondata_gate import model_stability as model_stability_module
from visiondata_gate.audit_envelope import canonical_jcs_bytes
from visiondata_gate.evidence import canonical_json_bytes, sha256_file
from visiondata_gate.model_stability import (
    ModelStabilityContractError,
    build_model_stability_summary,
    write_model_stability_artifacts,
)


def _write_json(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(canonical_json_bytes(value))


def _sealed_plan(**body: object) -> dict[str, object]:
    receipt_sha256 = hashlib.sha256(
        canonical_json_bytes(body, trailing_newline=False)
    ).hexdigest()
    return {**body, "receipt_sha256": receipt_sha256}


def _jcs_digest(value: object) -> str:
    return hashlib.sha256(canonical_jcs_bytes(value)).hexdigest()


def _sealed_agent_receipt(**body: object) -> dict[str, object]:
    return {**body, "receipt_sha256": _jcs_digest(body)}


def _make_run(
    root: Path,
    *,
    name: str,
    seed: int,
    image_auroc: float,
    pixel_auroc: float,
    image_f1: float,
    pixel_f1: float,
    architecture: str = "YOLO26N_CLASSIFICATION_MULTISCALE_FEATURE_AUTOENCODER",
    backbone_sha256: str = "b" * 64,
    identity_marker: str = "c",
    policy_sha256: str | None = None,
    source_binding_sha256: str = "f" * 64,
    source_index_sha256: str = "1" * 64,
    max_epochs: int = 12,
    samples_per_role: int = 4,
    multi_region_component_count: int = 2,
    optimization_status: str = "CONVERGED",
    effectiveness_status: str = "OBSERVED_ON_PUBLIC_DEVELOPMENT_PROXY",
    learning_paradigm: str = "NORMAL_ONLY_FEATURE_RECONSTRUCTION",
    split_seed: int | None = 900,
    sample_identity_marker: str = "7",
    sample_id_prefix: str = "sample",
    sample_sha_identity_marker: str | None = None,
    mask_identity_marker: str = "8",
    swap_sample_roles: bool = False,
    swap_evaluation_membership: bool = False,
    input_normalization_mean: list[float] | None = None,
    train_losses: list[float] | None = None,
    normal_validation_losses: list[float] | None = None,
) -> Path:
    run_dir = root / name
    identity = {
        "experiment_tool_sha256": identity_marker * 64,
        "policy_module_sha256": policy_sha256
        or sha256_file(Path(model_experiment_agent_module.__file__).resolve()),
        "runtime_executable_sha256": "e" * 64,
    }
    budget = {
        "external_llm_call_budget": 0,
        "max_epochs": max_epochs,
        "max_gpu_count": 1,
        "max_wall_seconds": 1800,
    }
    roles = {
        "checkpoint_validation_normal": samples_per_role,
        "development_anomaly": samples_per_role,
        "development_normal": samples_per_role,
        "weight_update_train_normal": samples_per_role,
    }
    plan_body: dict[str, object] = {
        "schema_version": "visiondata-gate.model-experiment-plan.v1",
        "architecture": architecture,
        "budget": budget,
        "dataset_id": "VisA",
        "feature_layers": [4, 6, 9],
        "label_truth_authority": False,
        "learning_paradigm": learning_paradigm,
        "machine_write_permitted": False,
        "production_release_allowed": False,
        "source_binding_sha256": source_binding_sha256,
        "source_index_sha256": source_index_sha256,
    }
    if split_seed is None:
        plan_body["seed"] = seed
    else:
        plan_body["split_seed"] = split_seed
        plan_body["model_seed"] = seed
    plan = _sealed_plan(**plan_body)
    samples: list[dict[str, object]] = []
    for role, count in roles.items():
        for index in range(count):
            marker = sample_sha_identity_marker or f"{index + 2:x}"
            samples.append(
                {
                    "source_sample_id": f"{sample_id_prefix}-{role}-{index}",
                    "role": role,
                    "sample_sha256": marker * 64,
                    "image_sha256": sample_identity_marker * 64,
                    "mask_sha256": (
                        None if "normal" in role else mask_identity_marker * 64
                    ),
                }
            )
    if swap_sample_roles:
        first_other_role = samples_per_role
        samples[0]["role"], samples[first_other_role]["role"] = (
            samples[first_other_role]["role"],
            samples[0]["role"],
        )
    manifest = {
        "schema_version": "visiondata-gate.visa-model-selection.v1",
        "dataset_id": "VisA",
        "dataset_version": "VisA_20220922",
        "license_id": "CC-BY-4.0",
        "object_class": "capsules",
        "production_release_allowed": False,
        "roles": roles,
        "samples": samples,
    }
    if split_seed is None:
        manifest["seed"] = seed
    else:
        manifest["split_seed"] = split_seed
        manifest["model_seed"] = seed

    effective_split_seed = seed if split_seed is None else split_seed
    development_samples = [
        sample
        for sample in samples
        if sample["role"] in {"development_normal", "development_anomaly"}
    ]
    per_sample_predictions: list[dict[str, object]] = []
    for sample in development_samples:
        source_sample_id = str(sample["source_sample_id"])
        index = int(source_sample_id.rsplit("-", maxsplit=1)[-1])
        product_label = (
            "anomaly" if sample["role"] == "development_anomaly" else "normal"
        )
        component_count = (
            0
            if product_label == "normal"
            else (1 if index < 2 else multi_region_component_count)
        )
        per_sample_predictions.append(
            {
                "source_sample_id": source_sample_id,
                "split_role": "calibration" if index % 2 == 0 else "heldout_development",
                "product_label": product_label,
                "component_count_proxy": component_count,
                "image_score": 0.8 if product_label == "anomaly" else 0.2,
                "predicted_anomaly": product_label == "anomaly",
            }
        )
    if swap_evaluation_membership:
        calibration_normal = next(
            item
            for item in per_sample_predictions
            if item["split_role"] == "calibration"
            and item["product_label"] == "normal"
        )
        heldout_normal = next(
            item
            for item in per_sample_predictions
            if item["split_role"] == "heldout_development"
            and item["product_label"] == "normal"
        )
        calibration_normal["split_role"], heldout_normal["split_role"] = (
            heldout_normal["split_role"],
            calibration_normal["split_role"],
        )
    calibration_rows = [
        item
        for item in per_sample_predictions
        if item["split_role"] == "calibration"
    ]
    heldout_rows = [
        item
        for item in per_sample_predictions
        if item["split_role"] == "heldout_development"
    ]
    heldout_single = [
        item
        for item in heldout_rows
        if item["product_label"] == "anomaly"
        and item["component_count_proxy"] == 1
    ]
    heldout_multi = [
        item
        for item in heldout_rows
        if item["product_label"] == "anomaly"
        and int(item["component_count_proxy"]) > 1
    ]
    normalization = {
        "color_space": "RGB",
        "value_scale": [0.0, 1.0],
        "resize": [256, 256],
        "mean": input_normalization_mean or [0.0, 0.0, 0.0],
        "std": [1.0, 1.0, 1.0],
    }
    feature_fusion = {
        "strategy": "equal_weight_mean",
        "target_resolution": [64, 64],
        "layer_weights": {
            "4": 1.0 / 3.0,
            "6": 1.0 / 3.0,
            "9": 1.0 / 3.0,
        },
    }
    validation_view = {
        "schema_version": "visiondata-gate.yolo26-normality-model-pack.v2",
        "architecture": architecture,
        "feature_layers": [4, 6, 9],
        "split_seed": effective_split_seed,
        "model_seed": seed,
        "image_size": 256,
        "selected_image_aggregation": "top_0_5pct",
        "image_threshold": 0.5,
        "pixel_threshold": 0.5,
        "input_normalization": normalization,
        "feature_fusion": feature_fusion,
        "backbone": {
            "state_dict": {"model.0.weight": True},
            "model_yaml": {"present": True},
            "weights_sha256": backbone_sha256,
            "provenance": {"architecture": "yolo26n-cls"},
            "license": "AGPL-3.0-or-Enterprise",
        },
        "students": {
            layer: {"encoder.weight": True} for layer in ("4", "6", "9")
        },
        "normalizers": {
            layer: {
                "normal_reference_mean": True,
                "normal_reference_variance": True,
                "reconstruction_mean": True,
                "reconstruction_std": True,
                "gaussian_mean": True,
                "gaussian_std": True,
            }
            for layer in ("4", "6", "9")
        },
    }
    checkpoint_path = run_dir / "private" / "worker" / "best_normality_model_pack.pt"
    checkpoint_path.parent.mkdir(parents=True, exist_ok=True)
    checkpoint_path.write_bytes(f"model-pack-v2:{seed}".encode("ascii"))
    checkpoint_sha256 = sha256_file(checkpoint_path)
    checkpoint = {
        "relative_path": "best_normality_model_pack.pt",
        "sha256": checkpoint_sha256,
        "bytes": checkpoint_path.stat().st_size,
        "selection": "minimum_normal_validation_reconstruction_loss",
        "feature_layers": [4, 6, 9],
        "format": "PYTORCH_SELF_CONTAINED_INFERENCE_PACK",
        "schema_version": "visiondata-gate.yolo26-normality-model-pack.v2",
        "contains_backbone": True,
        "selected_image_aggregation": "top_0_5pct",
        "image_threshold": 0.5,
        "pixel_threshold": 0.5,
        "validation_view": validation_view,
        "roundtrip_validation": {
            "checkpoint_sha256": checkpoint_sha256,
            "tensor_count": 22,
            "all_tensors_cpu_and_finite": True,
            "backbone_state_dict_reload": "PASS",
            "student_state_dict_reload": {"4": "PASS", "6": "PASS", "9": "PASS"},
        },
    }
    private_result = {
        "schema_version": "visiondata-gate.yolo26-normality-worker-result.v1",
        "status": "COMPLETED",
        "architecture": architecture,
        "feature_layers": [4, 6, 9],
        "split_seed": effective_split_seed,
        "model_seed": seed,
        "feature_fusion": feature_fusion,
        "backbone_weights_sha256": backbone_sha256,
        "implementation_identity": identity,
        "checkpoint": checkpoint,
        "best_normal_validation_loss": 0.1,
        "train_losses": train_losses or [0.4, 0.2],
        "normal_validation_losses": normal_validation_losses or [0.3, 0.1],
        "calibration": {
            "sample_count": len(calibration_rows),
            "selected_image_aggregation": "top_0_5pct",
            "image_threshold": 0.5,
            "pixel_threshold": 0.5,
        },
        "heldout_development": {
            "evaluation_sample_count": len(heldout_rows),
            "image_auroc": image_auroc,
            "image_average_precision": 0.8,
            "image_f1": image_f1,
            "normal_image_false_positive_rate": 0.1,
            "pixel_auroc": pixel_auroc,
            "pixel_average_precision": 0.2,
            "pixel_f1": pixel_f1,
            "single_region_proxy": {
                "sample_count": len(heldout_single),
                "component_count_proxy": sum(
                    int(item["component_count_proxy"]) for item in heldout_single
                ),
                "image_detection_recall": 0.8,
                "component_detected_fraction_at_10pct_overlap": 0.7,
            },
            "multi_region_proxy": {
                "sample_count": len(heldout_multi),
                "component_count_proxy": sum(
                    int(item["component_count_proxy"]) for item in heldout_multi
                ),
                "image_detection_recall": 0.7,
                "component_detected_fraction_at_10pct_overlap": 0.6,
            },
        },
        "runtime": {
            "elapsed_seconds": 10.0,
            "latency_ms_p50": 20.0,
            "latency_ms_p95": 25.0,
            "latency_ms_max": 30.0,
            "peak_allocated_bytes": 100,
        },
        "industrial_acceptance": "HOLD",
        "production_release_allowed": False,
        "per_sample_predictions": per_sample_predictions,
    }
    _write_json(run_dir / "private" / "worker_result.json", private_result)
    model_result = copy.deepcopy(private_result)
    model_result.pop("per_sample_predictions")
    model_result["checkpoint"]["relative_path"] = (
        "private/worker/" + model_result["checkpoint"]["relative_path"]
    )
    _write_json(run_dir / "model_experiment_plan.json", plan)
    _write_json(run_dir / "selection_manifest.json", manifest)
    _write_json(run_dir / "model_result.json", model_result)
    events = [
        {"sequence": 1, "stage": "intake", "status": "success"},
        {"sequence": 2, "stage": "planner", "status": "success"},
        {
            "sequence": 3,
            "stage": "tool",
            "status": "success",
            "task_id": "model-worker",
            "tool_name": "normality-model",
        },
        {"sequence": 4, "stage": "council", "status": "success"},
        {"sequence": 5, "stage": "judge", "status": "success"},
        {"sequence": 6, "stage": "delivery", "status": "success"},
    ]
    _write_json(run_dir / "agent_runtime_events.json", events)
    agent_receipt = _sealed_agent_receipt(
        schema_version="visiondata-gate.model-experiment-agent-receipt.v1",
        behavior_scope="MODEL_EXPERIMENT_WORKER_DECISION_AND_EXECUTION",
        production_gate_receipt="NOT_CLAIMED",
        agent_control_pattern="INTAKE_PLANNER_TOOL_COUNCIL_JUDGE_DELIVERY",
        source_binding_sha256=source_binding_sha256,
        source_index_sha256=source_index_sha256,
        plan_receipt_sha256=plan["receipt_sha256"],
        feature_layers=[4, 6, 9],
        split_seed=effective_split_seed,
        model_seed=seed,
        runtime_event_count=len(events),
        runtime_event_chain_sha256=_jcs_digest(events),
        stage_sequence=["intake", "planner", "tool", "council", "judge", "delivery"],
        tool_call_count=1,
        model_call_count=0,
        execution_result_sha256=sha256_file(
            run_dir / "private" / "worker_result.json"
        ),
        checkpoint_sha256=checkpoint_sha256,
        optimization_status=optimization_status,
        effectiveness_status=effectiveness_status,
        final_disposition="HOLD",
        label_truth_authority=False,
        machine_write_permitted=False,
        production_release_allowed=False,
    )
    _write_json(run_dir / "model_experiment_agent_receipt.json", agent_receipt)
    receipt = {
        "schema_version": "visiondata-gate.visa-yolo26-normality-experiment.v1",
        "status": "LOCAL_PUBLIC_PROXY_EXPERIMENT_COMPLETED",
        "dataset_id": "VisA",
        "dataset_version": "VisA_20220922",
        "license_id": "CC-BY-4.0",
        "object_class": "capsules",
        "architecture": architecture,
        "feature_layers": [4, 6, 9],
        "split_seed": effective_split_seed,
        "model_seed": seed,
        "feature_fusion": feature_fusion,
        "backbone_weights_sha256": backbone_sha256,
        "implementation_identity": identity,
        "optimization_status": optimization_status,
        "effectiveness_status": effectiveness_status,
        "industrial_acceptance": "HOLD",
        "production_release_allowed": False,
        "machine_write_permitted": False,
        "plan_file_sha256": sha256_file(run_dir / "model_experiment_plan.json"),
        "selection_manifest_sha256": sha256_file(
            run_dir / "selection_manifest.json"
        ),
        "model_result_file_sha256": sha256_file(run_dir / "model_result.json"),
        "runtime_event_file_sha256": sha256_file(
            run_dir / "agent_runtime_events.json"
        ),
        "agent_receipt_file_sha256": sha256_file(
            run_dir / "model_experiment_agent_receipt.json"
        ),
        "checkpoint_sha256": checkpoint_sha256,
    }
    _write_json(run_dir / "RUN_RECEIPT.json", receipt)
    return run_dir


def test_stable_three_seed_summary_promotes_only_the_public_proxy(tmp_path: Path):
    run_dirs = [
        _make_run(
            tmp_path,
            name=f"run{index}",
            seed=100 + index,
            image_auroc=value,
            pixel_auroc=0.80 + index * 0.01,
            image_f1=0.70 + index * 0.02,
            pixel_f1=0.20 + index * 0.01,
        )
        for index, value in enumerate((0.80, 0.82, 0.84))
    ]

    summary = build_model_stability_summary(run_dirs)

    assert summary["promotion_gate"]["status"] == "PUBLIC_PROXY_STABLE"
    assert summary["promotion_gate"]["eligible"] is True
    assert summary["production_release_allowed"] is False


    image_auroc_summary = summary["metrics"]["image_auroc"]
    assert image_auroc_summary == {
        "values_by_seed": {"100": 0.8, "101": 0.82, "102": 0.84},
        "mean": 0.82,
        "std": image_auroc_summary["std"],
        "min": 0.8,
        "max": 0.84,
        "range": 0.039999999999999925,
        "max_allowed_range": 0.05,
        "range_within_limit": True,
    }
    assert image_auroc_summary["std"] == pytest.approx(0.01632993161855449)
    assert summary["statistics_definition"] == "population_standard_deviation"


def test_claimed_effectiveness_is_rejected_when_recomputed_metrics_fail(
    tmp_path: Path,
):
    run_dirs = [
        _make_run(
            tmp_path,
            name=f"false-effectiveness-run-{index}",
            seed=701 + index,
            split_seed=700,
            image_auroc=0.0,
            pixel_auroc=0.0,
            image_f1=0.0,
            pixel_f1=0.0,
            effectiveness_status="OBSERVED_ON_PUBLIC_DEVELOPMENT_PROXY",
        )
        for index in range(3)
    ]

    with pytest.raises(
        ModelStabilityContractError,
        match="MODEL_OUTCOME_DERIVATION_MISMATCH: effectiveness_status",
    ):
        build_model_stability_summary(run_dirs)


def test_claimed_convergence_is_rejected_when_recomputed_losses_fail(
    tmp_path: Path,
):
    run_dirs = [
        _make_run(
            tmp_path,
            name=f"false-convergence-run-{index}",
            seed=711 + index,
            split_seed=710,
            image_auroc=0.8,
            pixel_auroc=0.8,
            image_f1=0.7,
            pixel_f1=0.2,
            train_losses=[0.4, 0.39],
            normal_validation_losses=[0.3, 0.29],
            optimization_status="CONVERGED",
            effectiveness_status="OBSERVED_ON_PUBLIC_DEVELOPMENT_PROXY",
        )
        for index in range(3)
    ]

    with pytest.raises(
        ModelStabilityContractError,
        match="MODEL_OUTCOME_DERIVATION_MISMATCH: optimization_status",
    ):
        build_model_stability_summary(run_dirs)


def test_v4_summary_exposes_the_full_evidence_contract(tmp_path: Path):
    run_dirs = [
        _make_run(
            tmp_path,
            name=f"evidence-contract-run-{index}",
            seed=150 + index,
            image_auroc=0.8,
            pixel_auroc=0.8,
            image_f1=0.7,
            pixel_f1=0.2,
        )
        for index in range(3)
    ]

    summary = build_model_stability_summary(run_dirs)

    assert summary["evidence_contract"] == {
        "required_artifacts": [
            "RUN_RECEIPT.json",
            "model_result.json",
            "model_experiment_plan.json",
            "selection_manifest.json",
            "model_experiment_agent_receipt.json",
            "agent_runtime_events.json",
            "private/worker_result.json",
            "private/worker/best_normality_model_pack.pt",
        ],
        "model_pack_schema_version": (
            "visiondata-gate.yolo26-normality-model-pack.v2"
        ),
        "model_pack_deserialization": "NOT_PERFORMED_NO_TORCH_IMPORT",
        "evaluation_membership_source": "PRIVATE_WORKER_RESULT",
        "outcome_derivation": (
            "RECOMPUTED_WITH_BOUND_CLASSIFY_EXPERIMENT_OUTCOME"
        ),
    }
    for run in summary["runs"]:
        assert {
            "model_experiment_agent_receipt.json",
            "agent_runtime_events.json",
            "private/worker_result.json",
            "private/worker/best_normality_model_pack.pt",
        }.issubset(run["artifact_sha256"])
        assert set(run["agent_evidence_sha256"]) == {
            "agent_receipt_self_seal_sha256",
            "runtime_event_chain_sha256",
            "private_execution_result_sha256",
        }


def test_stability_artifacts_are_deterministic_hashed_and_path_redacted(
    tmp_path: Path,
):
    run_dirs = [
        _make_run(
            tmp_path,
            name=f"source-run-{index}",
            seed=200 + index,
            image_auroc=0.80 + index * 0.01,
            pixel_auroc=0.70 + index * 0.01,
            image_f1=0.60 + index * 0.01,
            pixel_f1=0.20 + index * 0.01,
        )
        for index in range(3)
    ]
    summary = build_model_stability_summary(run_dirs)
    output = tmp_path / "published-stability"

    artifacts = write_model_stability_artifacts(summary, output)

    json_path = output / "MODEL_STABILITY_SUMMARY.json"
    markdown_path = output / "MODEL_STABILITY_SUMMARY.md"
    sums_path = output / "SHA256SUMS.txt"
    assert json.loads(json_path.read_text(encoding="utf-8")) == summary
    assert artifacts == {
        "MODEL_STABILITY_SUMMARY.json": sha256_file(json_path),
        "MODEL_STABILITY_SUMMARY.md": sha256_file(markdown_path),
        "SHA256SUMS.txt": sha256_file(sums_path),
    }
    sums = sums_path.read_text(encoding="utf-8")
    assert sums == (
        f"{artifacts['MODEL_STABILITY_SUMMARY.json']}  MODEL_STABILITY_SUMMARY.json\n"
        f"{artifacts['MODEL_STABILITY_SUMMARY.md']}  MODEL_STABILITY_SUMMARY.md\n"
    )
    published = json_path.read_text(encoding="utf-8") + markdown_path.read_text(
        encoding="utf-8"
    )
    assert str(tmp_path) not in published
    assert "- Stability schema: `visiondata-gate.model-stability.v4`" in published
    assert (
        summary["verification_implementation"]["stability_module_sha256"]
        in published
    )
    assert (
        summary["verification_implementation"]["outcome_policy_module_sha256"]
        in published
    )
    assert (
        "- Outcome derivation: "
        "`RECOMPUTED_WITH_BOUND_CLASSIFY_EXPERIMENT_OUTCOME`"
        in published
    )
    assert "- Split seed: `900`" in published
    assert "- Model seeds: `200, 201, 202`" in published
    assert (
        "- Model Pack deserialization: `NOT_PERFORMED_NO_TORCH_IMPORT`"
        in published
    )
    assert "production_release_allowed: false" in published


def test_stability_cli_writes_summary_without_turning_hold_into_failure(
    tmp_path: Path,
):
    run_dirs = [
        _make_run(
            tmp_path,
            name=f"hold-run-{index}",
            seed=300 + index,
            image_auroc=value,
            pixel_auroc=0.70,
            image_f1=0.60,
            pixel_f1=0.20,
        )
        for index, value in enumerate((0.60, 0.70, 0.80))
    ]
    output = tmp_path / "cli-output"
    project_root = Path(__file__).resolve().parents[1]

    completed = subprocess.run(
        [
            sys.executable,
            str(project_root / "tools" / "summarize_visa_yolo26_stability.py"),
            "--output",
            str(output),
            *(str(path) for path in run_dirs),
        ],
        cwd=project_root,
        check=False,
        capture_output=True,
        text=True,
        encoding="utf-8",
    )

    assert completed.returncode == 0, completed.stderr
    command_receipt = json.loads(completed.stdout)
    assert command_receipt["status"] == "MODEL_PROMOTION_HOLD"
    assert command_receipt["split_seed"] == 900
    assert command_receipt["model_seeds"] == [300, 301, 302]
    assert command_receipt["production_release_allowed"] is False
    assert (output / "MODEL_STABILITY_SUMMARY.json").is_file()


@pytest.mark.parametrize(
    ("third_run_overrides", "failed_check"),
    [
        ({"identity_marker": "9"}, "implementation_identity_match"),
        ({"source_binding_sha256": "8" * 64}, "source_binding_sha256_match"),
        ({"source_index_sha256": "7" * 64}, "source_index_sha256_match"),
        ({"split_seed": 901}, "split_seed_match"),
        ({"backbone_sha256": "6" * 64}, "backbone_weights_sha256_match"),
        ({"architecture": "DIFFERENT_ARCHITECTURE"}, "architecture_match"),
        ({"max_epochs": 13}, "budget_match"),
        ({"samples_per_role": 3}, "role_denominators_match"),
        ({"multi_region_component_count": 3}, "heldout_denominators_match"),
    ],
)
def test_cross_run_contract_drift_is_named_and_blocks_promotion(
    tmp_path: Path,
    third_run_overrides: dict[str, object],
    failed_check: str,
):
    common = {
        "image_auroc": 0.8,
        "pixel_auroc": 0.8,
        "image_f1": 0.7,
        "pixel_f1": 0.2,
    }
    run_dirs = [
        _make_run(tmp_path, name="run-a", seed=401, **common),
        _make_run(tmp_path, name="run-b", seed=402, **common),
        _make_run(
            tmp_path,
            name="run-c",
            seed=403,
            **common,
            **third_run_overrides,
        ),
    ]

    summary = build_model_stability_summary(run_dirs)

    assert summary["comparability"]["status"] == "COMPARABILITY_HOLD"
    assert failed_check in summary["comparability"]["failed_check_ids"]
    assert summary["promotion_gate"]["status"] == "MODEL_PROMOTION_HOLD"
    assert "CROSS_SEED_COMPARABILITY_MISMATCH" in summary["promotion_gate"][
        "blockers"
    ]
    assert summary["production_release_allowed"] is False


def test_v4_summary_binds_the_verifier_and_outcome_policy_sources(tmp_path: Path):
    run_dirs = [
        _make_run(
            tmp_path,
            name=f"implementation-binding-run-{index}",
            seed=160 + index,
            image_auroc=0.8,
            pixel_auroc=0.8,
            image_f1=0.7,
            pixel_f1=0.2,
        )
        for index in range(3)
    ]

    summary = build_model_stability_summary(run_dirs)

    assert summary["verification_implementation"] == {
        "stability_module_sha256": sha256_file(
            Path(model_stability_module.__file__).resolve()
        ),
        "outcome_policy_module_sha256": sha256_file(
            Path(model_experiment_agent_module.__file__).resolve()
        ),
        "outcome_policy_function": "classify_experiment_outcome",
    }


def test_stability_rejects_outcome_policy_source_drift(tmp_path: Path):
    run_dirs = [
        _make_run(
            tmp_path,
            name=f"policy-drift-run-{index}",
            seed=170 + index,
            image_auroc=0.8,
            pixel_auroc=0.8,
            image_f1=0.7,
            pixel_f1=0.2,
            policy_sha256="d" * 64 if index == 2 else None,
        )
        for index in range(3)
    ]

    with pytest.raises(
        ModelStabilityContractError,
        match="OUTCOME_POLICY_SOURCE_DRIFT: model_experiment_agent.py",
    ):
        build_model_stability_summary(run_dirs)


HISTORICAL_POLICY_SHA = "c2d9b28ed86724d1fdee8e47629fa5282c06e29528e0ec5d1f5796401b9bb30c"
DOCUMENTED_POLICY_SHA = "ff1f2385b1e070a352f9242dd821adf36858d505d6b91e3e1d01229123db3fd6"


def _historical_policy_runs(tmp_path, *, last_policy=None):
    return [
        _make_run(tmp_path, name=f"historical-run-{index}", seed=800 + index,
                  image_auroc=0.8, pixel_auroc=0.8, image_f1=0.7, pixel_f1=0.2,
                  policy_sha256=last_policy if index == 2 and last_policy else HISTORICAL_POLICY_SHA)
        for index in range(3)
    ]


def test_reviewed_docstring_migration_has_sealed_receipts_and_preserves_training_identity(tmp_path):
    runs = _historical_policy_runs(tmp_path)
    before = {str(path): sha256_file(path) for root in runs for path in root.rglob("*") if path.is_file()}
    summary = build_model_stability_summary(runs)
    assert summary["promotion_gate"]["status"] == "PUBLIC_PROXY_STABLE"
    assert summary["verification_implementation"]["outcome_policy_module_sha256"] == DOCUMENTED_POLICY_SHA
    receipts = summary["outcome_policy_compatibility_receipts"]
    assert len(receipts) == 3
    for receipt in receipts:
        assert receipt["schema_version"] == "visiondata-gate.outcome-policy-source-compatibility.v1"
        assert receipt["historical_policy_module_sha256"] == HISTORICAL_POLICY_SHA
        assert receipt["current_policy_module_sha256"] == DOCUMENTED_POLICY_SHA
        assert receipt["reconstructed_historical_source_sha256"] == HISTORICAL_POLICY_SHA
        assert receipt["verification_implementation"] == summary["verification_implementation"]
        assert receipt["training_identity_rewritten"] is False
        assert receipt["production_release_allowed"] is False
        assert receipt["receipt_sha256"] == _jcs_digest({key: value for key, value in receipt.items() if key != "receipt_sha256"})
    assert {str(path): sha256_file(path) for root in runs for path in root.rglob("*") if path.is_file()} == before
    for root in runs:
        original = json.loads((root / "RUN_RECEIPT.json").read_text("utf-8"))
        assert original["implementation_identity"]["policy_module_sha256"] == HISTORICAL_POLICY_SHA
    rendered = model_stability_module.render_model_stability_markdown(summary)
    assert HISTORICAL_POLICY_SHA in rendered and DOCUMENTED_POLICY_SHA in rendered
    assert "training_identity_rewritten: false" in rendered


def test_exact_current_policy_does_not_add_migration_fields(tmp_path):
    runs = [_make_run(tmp_path, name=f"same-source-{index}", seed=810 + index,
                      image_auroc=0.8, pixel_auroc=0.8, image_f1=0.7, pixel_f1=0.2)
            for index in range(3)]
    assert "outcome_policy_compatibility_receipts" not in build_model_stability_summary(runs)


def test_mixed_historical_and_current_training_identity_stays_incomparable(tmp_path):
    summary = build_model_stability_summary(_historical_policy_runs(tmp_path, last_policy=DOCUMENTED_POLICY_SHA))
    assert summary["promotion_gate"]["eligible"] is False
    assert "implementation_identity_match" in summary["comparability"]["failed_check_ids"]


@pytest.mark.parametrize("change", ["code", "docstring", "duplicate_patch"])
def test_unknown_current_source_cannot_use_docstring_compatibility(tmp_path, monkeypatch, change):
    runs = _historical_policy_runs(tmp_path / "runs")
    source = Path(model_experiment_agent_module.__file__).read_bytes()
    if change == "code":
        changed = source + b"\nunknown_runtime_constant = 1\n"
    elif change == "docstring":
        changed = source.replace(b"adjudicated masks", b"arbitrary masks")
    else:
        changed = source.replace(b"The resulting experiment", b"The resulting experiment\nThe resulting experiment")
    fixture = tmp_path / "changed_policy.py"
    fixture.write_bytes(changed)
    monkeypatch.setattr(model_experiment_agent_module, "__file__", str(fixture))
    with pytest.raises(ModelStabilityContractError, match="OUTCOME_POLICY_SOURCE_DRIFT"):
        build_model_stability_summary(runs)


def test_current_hash_claim_cannot_bypass_actual_reverse_patch(tmp_path, monkeypatch):
    runs = _historical_policy_runs(tmp_path / "runs")
    fixture = tmp_path / "not-the-reviewed-source.py"
    fixture.write_bytes(b"def classify_experiment_outcome(): return {}\n")
    monkeypatch.setattr(model_experiment_agent_module, "__file__", str(fixture))
    verifier = model_stability_module._verification_implementation()
    verifier["outcome_policy_module_sha256"] = DOCUMENTED_POLICY_SHA
    monkeypatch.setattr(model_stability_module, "_verification_implementation", lambda: verifier)
    with pytest.raises(ModelStabilityContractError, match="OUTCOME_POLICY_SOURCE_DRIFT"):
        build_model_stability_summary(runs)


def test_non_seed_plan_drift_is_not_averaged_as_a_stability_result(tmp_path: Path):
    common = {
        "image_auroc": 0.8,
        "pixel_auroc": 0.8,
        "image_f1": 0.7,
        "pixel_f1": 0.2,
    }
    run_dirs = [
        _make_run(tmp_path, name="plan-run-0", seed=400, **common),
        _make_run(tmp_path, name="plan-run-1", seed=401, **common),
        _make_run(
            tmp_path,
            name="plan-run-2",
            seed=402,
            learning_paradigm="DIFFERENT_LEARNING_PARADIGM",
            **common,
        ),
    ]

    summary = build_model_stability_summary(run_dirs)

    assert "plan_contract_match" in summary["comparability"]["failed_check_ids"]
    assert summary["promotion_gate"]["status"] == "MODEL_PROMOTION_HOLD"


def test_promotion_gate_exposes_every_failed_status_and_range_criterion(
    tmp_path: Path,
):
    run_dirs = [
        _make_run(
            tmp_path,
            name="criterion-run-0",
            seed=500,
            image_auroc=0.50,
            pixel_auroc=0.50,
            image_f1=0.40,
            pixel_f1=0.10,
            effectiveness_status="NOT_ESTABLISHED",
        ),
        _make_run(
            tmp_path,
            name="criterion-run-1",
            seed=501,
            image_auroc=0.56,
            pixel_auroc=0.56,
            image_f1=0.51,
            pixel_f1=0.16,
            effectiveness_status="NOT_ESTABLISHED",
        ),
        _make_run(
            tmp_path,
            name="criterion-run-2",
            seed=502,
            image_auroc=0.52,
            pixel_auroc=0.52,
            image_f1=0.45,
            pixel_f1=0.12,
            train_losses=[0.4, 0.39],
            normal_validation_losses=[0.3, 0.29],
            optimization_status="NOT_ESTABLISHED",
            effectiveness_status="NOT_ESTABLISHED",
        ),
    ]

    summary = build_model_stability_summary(run_dirs)

    assert summary["promotion_gate"]["criterion_checks"] == {
        "comparability_contract": True,
        "all_runs_completed": True,
        "all_optimization_converged": False,
        "all_effectiveness_observed": False,
        "image_auroc_range_within_limit": False,
        "pixel_auroc_range_within_limit": False,
        "image_f1_range_within_limit": False,
        "pixel_f1_range_within_limit": False,
    }
    assert set(summary["promotion_gate"]["blockers"]) == {
        "OPTIMIZATION_NOT_CONVERGED_ALL_SEEDS",
        "EFFECTIVENESS_NOT_OBSERVED_ALL_SEEDS",
        "IMAGE_AUROC_RANGE_EXCEEDS_LIMIT",
        "PIXEL_AUROC_RANGE_EXCEEDS_LIMIT",
        "IMAGE_F1_RANGE_EXCEEDS_LIMIT",
        "PIXEL_F1_RANGE_EXCEEDS_LIMIT",
    }
    assert summary["promotion_gate"]["status"] == "MODEL_PROMOTION_HOLD"
    assert summary["production_release_allowed"] is False


def test_tampered_model_result_is_rejected_before_aggregation(tmp_path: Path):
    run_dirs = [
        _make_run(
            tmp_path,
            name=f"tamper-run-{index}",
            seed=600 + index,
            image_auroc=0.8,
            pixel_auroc=0.8,
            image_f1=0.7,
            pixel_f1=0.2,
        )
        for index in range(3)
    ]
    target = run_dirs[1] / "model_result.json"
    target.write_bytes(target.read_bytes() + b" ")

    with pytest.raises(
        ModelStabilityContractError,
        match="STABILITY_ARTIFACT_SHA256_MISMATCH: model_result.json",
    ):
        build_model_stability_summary(run_dirs)


def test_tampered_agent_receipt_is_rejected_before_aggregation(tmp_path: Path):
    run_dirs = [
        _make_run(
            tmp_path,
            name=f"agent-tamper-run-{index}",
            seed=610 + index,
            image_auroc=0.8,
            pixel_auroc=0.8,
            image_f1=0.7,
            pixel_f1=0.2,
        )
        for index in range(3)
    ]
    target = run_dirs[1] / "model_experiment_agent_receipt.json"
    receipt = json.loads(target.read_text(encoding="utf-8"))
    receipt["final_disposition"] = "PASS"
    _write_json(target, receipt)

    with pytest.raises(
        ModelStabilityContractError,
        match=(
            "STABILITY_ARTIFACT_SHA256_MISMATCH: "
            "model_experiment_agent_receipt.json"
        ),
    ):
        build_model_stability_summary(run_dirs)


def test_tampered_checkpoint_bytes_are_rejected_before_aggregation(
    tmp_path: Path,
):
    run_dirs = [
        _make_run(
            tmp_path,
            name=f"checkpoint-tamper-run-{index}",
            seed=620 + index,
            image_auroc=0.8,
            pixel_auroc=0.8,
            image_f1=0.7,
            pixel_f1=0.2,
        )
        for index in range(3)
    ]
    target = (
        run_dirs[1]
        / "private"
        / "worker"
        / "best_normality_model_pack.pt"
    )
    target.write_bytes(target.read_bytes() + b"tampered")

    with pytest.raises(
        ModelStabilityContractError,
        match=(
            "STABILITY_CHECKPOINT_SHA256_MISMATCH: "
            "best_normality_model_pack.pt"
        ),
    ):
        build_model_stability_summary(run_dirs)


def test_evaluation_membership_drift_is_named_and_blocks_promotion(
    tmp_path: Path,
):
    common = {
        "split_seed": 915,
        "image_auroc": 0.8,
        "pixel_auroc": 0.8,
        "image_f1": 0.7,
        "pixel_f1": 0.2,
    }
    run_dirs = [
        _make_run(tmp_path, name="evaluation-run-0", seed=916, **common),
        _make_run(tmp_path, name="evaluation-run-1", seed=917, **common),
        _make_run(
            tmp_path,
            name="evaluation-run-2",
            seed=918,
            swap_evaluation_membership=True,
            **common,
        ),
    ]

    summary = build_model_stability_summary(run_dirs)

    assert summary["comparability"]["status"] == "COMPARABILITY_HOLD"
    assert "evaluation_membership_match" in summary["comparability"][
        "failed_check_ids"
    ]
    assert "EVALUATION_MEMBERSHIP_MISMATCH" in summary["promotion_gate"][
        "blockers"
    ]
    assert summary["promotion_gate"]["status"] == "MODEL_PROMOTION_HOLD"
    assert summary["production_release_allowed"] is False


def test_non_native_model_pack_normalization_is_rejected(tmp_path: Path):
    run_dirs = [
        _make_run(
            tmp_path,
            name=f"normalization-run-{index}",
            seed=630 + index,
            image_auroc=0.8,
            pixel_auroc=0.8,
            image_f1=0.7,
            pixel_f1=0.2,
            input_normalization_mean=(
                [0.485, 0.456, 0.406] if index == 1 else None
            ),
        )
        for index in range(3)
    ]

    with pytest.raises(
        ModelStabilityContractError,
        match="MODEL_PACK_INPUT_NORMALIZATION_INVALID: model_result.json",
    ):
        build_model_stability_summary(run_dirs)


def test_public_model_result_must_equal_the_private_projection(tmp_path: Path):
    run_dirs = [
        _make_run(
            tmp_path,
            name=f"projection-run-{index}",
            seed=640 + index,
            image_auroc=0.8,
            pixel_auroc=0.8,
            image_f1=0.7,
            pixel_f1=0.2,
        )
        for index in range(3)
    ]
    target = run_dirs[1] / "model_result.json"
    public_result = json.loads(target.read_text(encoding="utf-8"))
    public_result["checkpoint"]["image_threshold"] = 0.9
    _write_json(target, public_result)
    receipt_path = run_dirs[1] / "RUN_RECEIPT.json"
    receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
    receipt["model_result_file_sha256"] = sha256_file(target)
    _write_json(receipt_path, receipt)

    with pytest.raises(
        ModelStabilityContractError,
        match="PUBLIC_MODEL_RESULT_PROJECTION_MISMATCH: model_result.json",
    ):
        build_model_stability_summary(run_dirs)


def test_three_distinct_seed_receipts_are_required(tmp_path: Path):
    run_dirs = [
        _make_run(
            tmp_path,
            name=f"duplicate-seed-run-{index}",
            seed=700 if index < 2 else 701,
            image_auroc=0.8,
            pixel_auroc=0.8,
            image_f1=0.7,
            pixel_f1=0.2,
        )
        for index in range(3)
    ]

    with pytest.raises(
        ModelStabilityContractError, match="THREE_UNIQUE_SEEDS_REQUIRED"
    ):
        build_model_stability_summary(run_dirs)


def test_explicit_split_seed_and_unique_model_seeds_define_comparability(
    tmp_path: Path,
):
    run_dirs = [
        _make_run(
            tmp_path,
            name=f"explicit-seed-run-{index}",
            split_seed=900,
            seed=901 + index,
            image_auroc=0.80 + index * 0.01,
            pixel_auroc=0.80 + index * 0.01,
            image_f1=0.70 + index * 0.01,
            pixel_f1=0.20 + index * 0.01,
        )
        for index in range(3)
    ]

    summary = build_model_stability_summary(run_dirs)

    assert summary["schema_version"] == "visiondata-gate.model-stability.v4"
    assert summary["split_seed"] == 900
    assert summary["model_seeds"] == [901, 902, 903]
    assert summary["seeds"] == [901, 902, 903]
    assert summary["comparability"]["status"] == "PASS"
    assert summary["comparability"]["failed_check_ids"] == []
    assert summary["promotion_gate"]["status"] == "PUBLIC_PROXY_STABLE"
    assert summary["production_release_allowed"] is False


def test_legacy_single_seed_runs_remain_a_comparability_hold(tmp_path: Path):
    run_dirs = [
        _make_run(
            tmp_path,
            name=f"legacy-seed-run-{index}",
            split_seed=None,
            seed=920 + index,
            image_auroc=0.80 + index * 0.01,
            pixel_auroc=0.80 + index * 0.01,
            image_f1=0.70 + index * 0.01,
            pixel_f1=0.20 + index * 0.01,
        )
        for index in range(3)
    ]

    summary = build_model_stability_summary(run_dirs)

    assert summary["split_seed"] is None
    assert summary["model_seeds"] == [920, 921, 922]
    assert summary["comparability"]["status"] == "COMPARABILITY_HOLD"
    assert {
        "explicit_split_model_seed_contract",
        "split_seed_match",
    }.issubset(summary["comparability"]["failed_check_ids"])
    assert "EXPLICIT_SPLIT_MODEL_SEED_CONTRACT_REQUIRED" in summary[
        "promotion_gate"
    ]["blockers"]
    assert summary["promotion_gate"]["status"] == "MODEL_PROMOTION_HOLD"
    assert summary["production_release_allowed"] is False


@pytest.mark.parametrize(
    "member_drift",
    [
        {"sample_id_prefix": "changed-sample"},
        {"swap_sample_roles": True},
        {"sample_sha_identity_marker": "9"},
        {"sample_identity_marker": "a"},
        {"mask_identity_marker": "b"},
    ],
)
def test_every_frozen_member_field_must_match_across_model_seeds(
    tmp_path: Path, member_drift: dict[str, object]
):
    common = {
        "split_seed": 910,
        "image_auroc": 0.8,
        "pixel_auroc": 0.8,
        "image_f1": 0.7,
        "pixel_f1": 0.2,
    }
    run_dirs = [
        _make_run(tmp_path, name="member-run-0", seed=911, **common),
        _make_run(tmp_path, name="member-run-1", seed=912, **common),
        _make_run(
            tmp_path,
            name="member-run-2",
            seed=913,
            **common,
            **member_drift,
        ),
    ]

    summary = build_model_stability_summary(run_dirs)

    assert summary["comparability"]["status"] == "COMPARABILITY_HOLD"
    assert "selection_membership_match" in summary["comparability"][
        "failed_check_ids"
    ]
    assert "SELECTION_MEMBERSHIP_MISMATCH" in summary["promotion_gate"][
        "blockers"
    ]
    assert summary["promotion_gate"]["status"] == "MODEL_PROMOTION_HOLD"
    assert summary["production_release_allowed"] is False
