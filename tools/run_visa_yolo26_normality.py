"""Run a bounded, Agent-governed YOLO26n normal-only VisA experiment.

Only ``train/normal`` samples may update the feature-reconstruction head.
Development images and masks are used after checkpoint selection.  The result
is a public-proxy experiment and never grants production release.
"""

from __future__ import annotations

import argparse
from datetime import UTC, datetime
import hashlib
import hmac
import json
import math
import os
from pathlib import Path
import statistics
import subprocess
import sys
import time
from typing import Any, Callable


_MULTISCALE_ARCHITECTURE = "YOLO26N_CLASSIFICATION_MULTISCALE_FEATURE_AUTOENCODER"
_MULTISCALE_FEATURE_LAYERS = [4, 6, 9]
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


def _sha_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _load_json(path: Path) -> dict:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError("JSON_OBJECT_REQUIRED")
    return value


def _write_json(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")),
        encoding="utf-8",
    )


def _rank(split_seed: int, identifier: str) -> str:
    return hashlib.sha256(
        f"{split_seed}\0{identifier}".encode("utf-8")
    ).hexdigest()


def _safe_member(root: Path, relative: str) -> Path:
    normalized = relative.replace("\\", "/")
    if not normalized or normalized.startswith("/") or ".." in normalized.split("/"):
        raise ValueError("SOURCE_RELATIVE_PATH_INVALID")
    candidate = (root / Path(*normalized.split("/"))).resolve(strict=True)
    candidate.relative_to(root)
    if not candidate.is_file():
        raise ValueError("SOURCE_MEMBER_NOT_FILE")
    return candidate


def _percentile(values: list[float], quantile: float) -> float:
    ordered = sorted(values)
    if not ordered:
        return 0.0
    position = (len(ordered) - 1) * quantile
    low = math.floor(position)
    high = math.ceil(position)
    if low == high:
        return ordered[low]
    return ordered[low] * (high - position) + ordered[high] * (position - low)


def _is_sha256(value: object) -> bool:
    return (
        isinstance(value, str)
        and len(value) == 64
        and all(character in "0123456789abcdef" for character in value)
    )


def _validate_local_model_pack_roundtrip(
    pack: dict[str, Any],
    *,
    worker_result: dict[str, Any],
    actual_checkpoint_sha256: str,
    tensor_validator: Callable[[Any], bool],
) -> None:
    """Validate the reloaded model pack without project-package imports."""

    checkpoint = worker_result.get("checkpoint")
    if not (
        _is_sha256(actual_checkpoint_sha256)
        and isinstance(checkpoint, dict)
        and _is_sha256(checkpoint.get("sha256"))
        and hmac.compare_digest(
            actual_checkpoint_sha256, checkpoint["sha256"]
        )
    ):
        raise ValueError("MODEL_PACK_SHA_MISMATCH")
    if not (
        isinstance(pack, dict)
        and pack.get("schema_version")
        == _MODEL_PACK_SCHEMA_VERSION
        and pack.get("architecture") == _MULTISCALE_ARCHITECTURE
        and pack.get("feature_layers") == _MULTISCALE_FEATURE_LAYERS
        and worker_result.get("architecture") == _MULTISCALE_ARCHITECTURE
        and worker_result.get("feature_layers") == _MULTISCALE_FEATURE_LAYERS
        and checkpoint.get("feature_layers") == _MULTISCALE_FEATURE_LAYERS
    ):
        raise ValueError("MODEL_PACK_SCOPE_INVALID")
    split_seed = pack.get("split_seed")
    model_seed = pack.get("model_seed")
    if not (
        type(split_seed) is int
        and 0 <= split_seed <= 2**31 - 1
        and type(model_seed) is int
        and 0 <= model_seed <= 2**31 - 1
        and worker_result.get("split_seed") == split_seed
        and worker_result.get("model_seed") == model_seed
    ):
        raise ValueError("MODEL_PACK_SEED_INVALID")
    image_size = pack.get("image_size")
    image_threshold = pack.get("image_threshold")
    pixel_threshold = pack.get("pixel_threshold")
    if not (
        type(image_size) is int
        and image_size > 0
        and pack.get("selected_image_aggregation") in _IMAGE_AGGREGATIONS
        and type(image_threshold) in {int, float}
        and math.isfinite(float(image_threshold))
        and float(image_threshold) >= 0.0
        and type(pixel_threshold) in {int, float}
        and math.isfinite(float(pixel_threshold))
        and float(pixel_threshold) >= 0.0
    ):
        raise ValueError("MODEL_PACK_THRESHOLD_INVALID")
    normalization = pack.get("input_normalization")
    if not (
        isinstance(normalization, dict)
        and normalization.get("color_space") == "RGB"
        and normalization.get("value_scale") == [0.0, 1.0]
        and normalization.get("resize") == [image_size, image_size]
        and normalization.get("mean") == [0.0, 0.0, 0.0]
        and normalization.get("std") == [1.0, 1.0, 1.0]
    ):
        raise ValueError("MODEL_PACK_INPUT_NORMALIZATION_INVALID")
    expected_keys = {str(layer) for layer in _MULTISCALE_FEATURE_LAYERS}
    fusion = pack.get("feature_fusion")
    weights = fusion.get("layer_weights") if isinstance(fusion, dict) else None
    if not (
        isinstance(fusion, dict)
        and fusion.get("strategy") == "equal_weight_mean"
        and fusion.get("target_resolution") == [64, 64]
        and isinstance(weights, dict)
        and set(weights) == expected_keys
        and all(
            type(value) in {int, float}
            and math.isfinite(float(value))
            and math.isclose(float(value), 1.0 / 3.0, rel_tol=0.0, abs_tol=1e-12)
            for value in weights.values()
        )
    ):
        raise ValueError("MODEL_PACK_FUSION_INVALID")
    backbone = pack.get("backbone")
    provenance = backbone.get("provenance") if isinstance(backbone, dict) else None
    backbone_state = backbone.get("state_dict") if isinstance(backbone, dict) else None
    model_yaml = backbone.get("model_yaml") if isinstance(backbone, dict) else None
    if not (
        isinstance(backbone, dict)
        and isinstance(backbone_state, dict)
        and bool(backbone_state)
        and isinstance(model_yaml, dict)
        and bool(model_yaml)
        and _is_sha256(backbone.get("weights_sha256"))
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
        "v8.4.0/yolo26n-cls.pt"
    ):
        raise ValueError("MODEL_PACK_BACKBONE_INVALID")
    students = pack.get("students")
    normalizers = pack.get("normalizers")
    if not (
        isinstance(students, dict)
        and set(students) == expected_keys
        and isinstance(normalizers, dict)
        and set(normalizers) == expected_keys
    ):
        raise ValueError("MODEL_PACK_LAYER_SET_INVALID")
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
        if not (
            isinstance(student_state, dict)
            and bool(student_state)
            and isinstance(layer_normalizers, dict)
            and set(layer_normalizers) == normalizer_fields
        ):
            raise ValueError("MODEL_PACK_LAYER_STATE_INVALID")
        tensor_values.extend(student_state.values())
        tensor_values.extend(layer_normalizers.values())
    if not tensor_values or not all(
        tensor_validator(value) for value in tensor_values
    ):
        raise ValueError("MODEL_PACK_TENSOR_INVALID")


def _build_model_pack_validation_view(
    pack: dict[str, Any], *, tensor_validator: Callable[[Any], bool]
) -> tuple[dict[str, Any], int, bool]:
    """Project a torch checkpoint into JSON-safe evidence for the parent."""

    tensor_results: list[bool] = []

    def tensor_status(value: Any) -> bool:
        result = bool(tensor_validator(value))
        tensor_results.append(result)
        return result

    backbone = pack.get("backbone") if isinstance(pack, dict) else None
    backbone = backbone if isinstance(backbone, dict) else {}
    backbone_state = backbone.get("state_dict")
    backbone_state = backbone_state if isinstance(backbone_state, dict) else {}
    students = pack.get("students") if isinstance(pack, dict) else None
    students = students if isinstance(students, dict) else {}
    normalizers = pack.get("normalizers") if isinstance(pack, dict) else None
    normalizers = normalizers if isinstance(normalizers, dict) else {}
    validation_view = {
        key: pack.get(key)
        for key in (
            "schema_version",
            "architecture",
            "feature_layers",
            "split_seed",
            "model_seed",
            "image_size",
            "selected_image_aggregation",
            "image_threshold",
            "pixel_threshold",
            "input_normalization",
            "feature_fusion",
        )
    }
    validation_view["backbone"] = {
        "state_dict": {
            key: tensor_status(value) for key, value in backbone_state.items()
        },
        "model_yaml": {"present": bool(backbone.get("model_yaml"))},
        "weights_sha256": backbone.get("weights_sha256"),
        "provenance": backbone.get("provenance"),
        "license": backbone.get("license"),
    }
    validation_view["students"] = {
        layer: {key: tensor_status(value) for key, value in state.items()}
        for layer, state in students.items()
        if isinstance(state, dict)
    }
    validation_view["normalizers"] = {
        layer: {key: tensor_status(value) for key, value in values.items()}
        for layer, values in normalizers.items()
        if isinstance(values, dict)
    }
    return validation_view, len(tensor_results), bool(tensor_results) and all(
        tensor_results
    )


def _worker(request_path: Path, result_path: Path) -> int:
    import cv2
    import numpy as np
    from PIL import Image
    from sklearn.metrics import average_precision_score, roc_auc_score
    import torch
    from torch import nn
    import torch.nn.functional as functional
    from ultralytics import YOLO
    import ultralytics

    request = _load_json(request_path)
    root = Path(request["dataset_root"]).resolve(strict=True)
    weights = Path(request["weights_path"]).resolve(strict=True)
    output = Path(request["worker_output"]).resolve()
    output.mkdir(parents=True, exist_ok=False)
    if _sha_file(Path(__file__).resolve()) != request["experiment_tool_sha256"]:
        raise ValueError("EXPERIMENT_TOOL_SHA_MISMATCH")
    if _sha_file(Path(sys.executable).resolve()) != request["runtime_executable_sha256"]:
        raise ValueError("RUNTIME_EXECUTABLE_SHA_MISMATCH")
    policy_module = Path(request["policy_module_path"]).resolve(strict=True)
    if _sha_file(policy_module) != request["policy_module_sha256"]:
        raise ValueError("MODEL_POLICY_MODULE_SHA_MISMATCH")
    if _sha_file(weights) != request["weights_sha256"]:
        raise ValueError("BACKBONE_WEIGHTS_SHA_MISMATCH")

    split_seed = int(request["split_seed"])
    model_seed = int(request["model_seed"])
    torch.manual_seed(model_seed)
    np.random.seed(model_seed)
    if not torch.cuda.is_available():
        raise ValueError("CUDA_REQUIRED_FOR_BOUNDED_EXPERIMENT")
    device = torch.device("cuda:0")
    torch.cuda.set_device(device)
    torch.backends.cudnn.benchmark = False
    torch.backends.cudnn.deterministic = True
    torch.cuda.reset_peak_memory_stats(device)

    samples = request["samples"]
    by_role: dict[str, list[dict]] = {}
    for sample in samples:
        by_role.setdefault(sample["role"], []).append(sample)
        image_path = _safe_member(root, sample["image_relative_path"])
        if _sha_file(image_path) != sample["image_sha256"]:
            raise ValueError("SOURCE_IMAGE_SHA_MISMATCH")
        mask_relative = sample.get("mask_relative_path")
        if mask_relative:
            mask_path = _safe_member(root, mask_relative)
            if _sha_file(mask_path) != sample["mask_sha256"]:
                raise ValueError("SOURCE_MASK_SHA_MISMATCH")

    backbone_artifact = YOLO(str(weights), task="classify")
    checkpoint_metadata = backbone_artifact.ckpt or {}
    checkpoint_train_args = checkpoint_metadata.get("train_args") or {}
    pretraining_data = Path(str(checkpoint_train_args.get("data", ""))).name.lower()
    if (
        backbone_artifact.task != "classify"
        or len(backbone_artifact.names) != 1000
        or pretraining_data != "imagenet"
        or request["weights_source_url"]
        != "https://github.com/ultralytics/assets/releases/download/v8.4.0/yolo26n-cls.pt"
    ):
        raise ValueError("YOLO26_PUBLIC_PRETRAINING_PROVENANCE_INVALID")
    backbone_provenance = {
        "provider": "Ultralytics",
        "architecture": "yolo26n-cls",
        "task": backbone_artifact.task,
        "class_count": len(backbone_artifact.names),
        "pretraining_dataset": "ImageNet",
        "checkpoint_ultralytics_version": checkpoint_metadata.get("version"),
        "checkpoint_date": checkpoint_metadata.get("date"),
        "source_url": request["weights_source_url"],
        "runtime_license_review_required": True,
    }
    backbone_license = (
        checkpoint_metadata.get("license") or "AGPL-3.0-or-Enterprise"
    )
    backbone = backbone_artifact.model.to(device).eval()
    backbone_model_yaml = getattr(backbone, "yaml", None)
    if not isinstance(backbone_model_yaml, dict) or not backbone_model_yaml:
        raise ValueError("YOLO26_BACKBONE_ARCHITECTURE_CONFIG_INVALID")
    feature_layer_indices = list(request["feature_layers"])
    if (
        not hasattr(backbone, "model")
        or feature_layer_indices != [4, 6, 9]
        or max(feature_layer_indices) >= len(backbone.model)
    ):
        raise ValueError("YOLO26_FEATURE_LAYER_UNAVAILABLE")
    feature_fusion = {
        "strategy": "equal_weight_mean",
        "target_resolution": [64, 64],
        "layer_weights": {
            str(layer_index): 1.0 / len(feature_layer_indices)
            for layer_index in feature_layer_indices
        },
    }
    captured: dict[int, torch.Tensor] = {}

    def capture(layer_index: int):
        def callback(_module, _inputs, output_value):
            value = (
                output_value[0]
                if isinstance(output_value, (tuple, list))
                else output_value
            )
            if not isinstance(value, torch.Tensor) or value.ndim != 4:
                raise ValueError("YOLO26_FEATURE_TENSOR_INVALID")
            captured[layer_index] = value

        return callback

    handles = [
        backbone.model[layer_index].register_forward_hook(capture(layer_index))
        for layer_index in feature_layer_indices
    ]
    image_size = int(request["image_size"])
    input_normalization = {
        "color_space": "RGB",
        "value_scale": [0.0, 1.0],
        "resize": [image_size, image_size],
        # Ultralytics classification checkpoints are trained with the package's
        # DEFAULT_MEAN=(0, 0, 0) and DEFAULT_STD=(1, 1, 1).  Applying torchvision's
        # ImageNet normalization here changes the checkpoint's input contract.
        "mean": [0.0, 0.0, 0.0],
        "std": [1.0, 1.0, 1.0],
    }
    mean = torch.tensor(input_normalization["mean"])[:, None, None]
    std = torch.tensor(input_normalization["std"])[:, None, None]

    def image_tensor(sample: dict) -> torch.Tensor:
        path = _safe_member(root, sample["image_relative_path"])
        with Image.open(path) as image:
            rgb = image.convert("RGB").resize(
                (image_size, image_size), Image.Resampling.BILINEAR
            )
            array = np.asarray(rgb, dtype=np.float32) / 255.0
        tensor = torch.from_numpy(array).permute(2, 0, 1)
        return (tensor - mean) / std

    def features(members: list[dict], batch_size: int) -> dict[int, torch.Tensor]:
        values: dict[int, list[torch.Tensor]] = {
            layer_index: [] for layer_index in feature_layer_indices
        }
        with torch.inference_mode():
            for offset in range(0, len(members), batch_size):
                batch = torch.stack(
                    [image_tensor(item) for item in members[offset : offset + batch_size]]
                ).to(device)
                captured.clear()
                backbone(batch)
                if set(captured) != set(feature_layer_indices):
                    raise ValueError("YOLO26_FEATURE_CAPTURE_COUNT_INVALID")
                for layer_index in feature_layer_indices:
                    value = functional.normalize(
                        captured[layer_index].float(), dim=1
                    )
                    values[layer_index].append(value.cpu().half())
        return {
            layer_index: torch.cat(layer_values)
            for layer_index, layer_values in values.items()
        }

    training = by_role["weight_update_train_normal"]
    normal_validation = by_role["checkpoint_validation_normal"]
    train_features = features(training, int(request["feature_batch_size"]))
    validation_features = features(
        normal_validation, int(request["feature_batch_size"])
    )
    channels = {
        layer_index: int(train_features[layer_index].shape[1])
        for layer_index in feature_layer_indices
    }
    bottlenecks = {
        layer_index: max(16, min(96, channels[layer_index] // 8))
        for layer_index in feature_layer_indices
    }

    class FeatureDenoisingAutoencoder(nn.Module):
        def __init__(self, layer_index: int) -> None:
            super().__init__()
            channel_count = channels[layer_index]
            bottleneck = bottlenecks[layer_index]
            hidden = max(bottleneck * 2, min(256, channel_count // 2))
            self.network = nn.Sequential(
                nn.Conv2d(channel_count, hidden, 1),
                nn.GELU(),
                nn.Conv2d(hidden, hidden, 3, padding=1, groups=hidden),
                nn.GELU(),
                nn.Conv2d(hidden, bottleneck, 1),
                nn.GELU(),
                nn.Conv2d(bottleneck, hidden, 1),
                nn.GELU(),
                nn.Conv2d(hidden, channel_count, 1),
            )

        def forward(self, value: torch.Tensor) -> torch.Tensor:
            return self.network(value)

    students = nn.ModuleDict(
        {
            str(layer_index): FeatureDenoisingAutoencoder(layer_index)
            for layer_index in feature_layer_indices
        }
    ).to(device)
    optimizer = torch.optim.AdamW(
        students.parameters(), lr=float(request["learning_rate"]), weight_decay=1e-4
    )
    epochs = int(request["epochs"])
    feature_batch = int(request["student_batch_size"])
    train_losses: list[float] = []
    validation_losses: list[float] = []
    best_loss = math.inf
    best_state = None
    generator = torch.Generator().manual_seed(model_seed)
    started = time.perf_counter()
    for _epoch in range(epochs):
        students.train()
        sample_count = len(train_features[feature_layer_indices[0]])
        permutation = torch.randperm(sample_count, generator=generator)
        epoch_losses: list[float] = []
        for offset in range(0, len(permutation), feature_batch):
            indexes = permutation[offset : offset + feature_batch]
            optimizer.zero_grad(set_to_none=True)
            layer_losses = []
            for layer_index in feature_layer_indices:
                batch = train_features[layer_index][indexes].float().to(device)
                noisy = functional.dropout(batch, p=0.10, training=True)
                noisy = noisy + 0.02 * torch.randn_like(noisy)
                prediction = students[str(layer_index)](noisy)
                layer_losses.append(functional.mse_loss(prediction, batch))
            loss = torch.stack(layer_losses).mean()
            if not torch.isfinite(loss):
                raise ValueError("NONFINITE_TRAINING_LOSS")
            loss.backward()
            optimizer.step()
            epoch_losses.append(float(loss.detach().cpu()))
        train_losses.append(statistics.fmean(epoch_losses))
        students.eval()
        held_losses: list[float] = []
        with torch.inference_mode():
            validation_count = len(validation_features[feature_layer_indices[0]])
            for offset in range(0, validation_count, feature_batch):
                layer_losses = []
                for layer_index in feature_layer_indices:
                    batch = validation_features[layer_index][
                        offset : offset + feature_batch
                    ].float().to(device)
                    layer_losses.append(
                        functional.mse_loss(students[str(layer_index)](batch), batch)
                    )
                held_losses.append(float(torch.stack(layer_losses).mean().cpu()))
        validation_loss = statistics.fmean(held_losses)
        validation_losses.append(validation_loss)
        if validation_loss < best_loss:
            best_loss = validation_loss
            best_state = {
                key: value.detach().cpu().clone()
                for key, value in students.state_dict().items()
            }
    if best_state is None:
        raise ValueError("CHECKPOINT_SELECTION_FAILED")
    students.load_state_dict(best_state)
    students.eval()

    reference_means: dict[int, torch.Tensor] = {}
    reference_variances: dict[int, torch.Tensor] = {}
    reconstruction_means: dict[int, torch.Tensor] = {}
    reconstruction_stds: dict[int, torch.Tensor] = {}
    gaussian_means: dict[int, torch.Tensor] = {}
    gaussian_stds: dict[int, torch.Tensor] = {}
    with torch.inference_mode():
        for layer_index in feature_layer_indices:
            train_reference = train_features[layer_index].float()
            reference_mean = train_reference.mean(dim=0, keepdim=True).to(device)
            reference_variance = (
                train_reference.var(dim=0, unbiased=False, keepdim=True)
                .clamp_min(1e-6)
                .to(device)
            )
            validation = validation_features[layer_index].float().to(device)
            reconstruction = (
                students[str(layer_index)](validation) - validation
            ).square().mean(dim=1, keepdim=True)
            gaussian = (
                (validation - reference_mean).square() / reference_variance
            ).mean(dim=1, keepdim=True)
            reference_means[layer_index] = reference_mean
            reference_variances[layer_index] = reference_variance
            reconstruction_means[layer_index] = reconstruction.mean(
                dim=0, keepdim=True
            )
            reconstruction_stds[layer_index] = reconstruction.std(
                dim=0, unbiased=False, keepdim=True
            ).clamp_min(1e-6)
            gaussian_means[layer_index] = gaussian.mean(dim=0, keepdim=True)
            gaussian_stds[layer_index] = gaussian.std(
                dim=0, unbiased=False, keepdim=True
            ).clamp_min(1e-6)

    def component_count(mask_array: np.ndarray) -> tuple[int, np.ndarray]:
        binary = (mask_array > 0).astype(np.uint8)
        _count, labels, component_stats, _centroids = cv2.connectedComponentsWithStats(
            binary, 8
        )
        keep = component_stats[1:, cv2.CC_STAT_AREA] >= 4
        kept_labels = np.flatnonzero(keep) + 1
        filtered = np.isin(labels, kept_labels).astype(np.uint8)
        return int(keep.sum()), filtered

    def fused_anomaly_map(
        feature_maps: dict[int, torch.Tensor],
    ) -> torch.Tensor:
        layer_maps: list[torch.Tensor] = []
        for layer_index in feature_layer_indices:
            feature = feature_maps[layer_index].float().to(device)
            reconstruction = (
                students[str(layer_index)](feature) - feature
            ).square().mean(dim=1, keepdim=True)
            gaussian = (
                (feature - reference_means[layer_index]).square()
                / reference_variances[layer_index]
            ).mean(dim=1, keepdim=True)
            reconstruction_score = functional.relu(
                (reconstruction - reconstruction_means[layer_index])
                / reconstruction_stds[layer_index]
            )
            gaussian_score = functional.relu(
                (gaussian - gaussian_means[layer_index])
                / gaussian_stds[layer_index]
            )
            layer_maps.append(
                functional.interpolate(
                    0.5 * reconstruction_score + 0.5 * gaussian_score,
                    size=(64, 64),
                    mode="bilinear",
                    align_corners=False,
                )
            )
        return torch.stack(layer_maps, dim=0).mean(dim=0)

    def score_sample(sample: dict) -> dict:
        feature_maps = features([sample], 1)
        with torch.inference_mode():
            combined = fused_anomaly_map(feature_maps)[0, 0]
        score_map = combined.detach().cpu().numpy().astype(np.float32)
        flat = np.sort(score_map.reshape(-1))
        image_scores = {"max": float(flat[-1]), "mean": float(flat.mean())}
        for name, fraction in (
            ("top_0_1pct", 0.001),
            ("top_0_5pct", 0.005),
            ("top_1pct", 0.01),
            ("top_2pct", 0.02),
            ("top_5pct", 0.05),
            ("top_10pct", 0.10),
        ):
            top_count = max(1, int(len(flat) * fraction))
            image_scores[name] = float(flat[-top_count:].mean())
        if sample["product_label"] == "anomaly":
            mask_path = _safe_member(root, sample["mask_relative_path"])
            with Image.open(mask_path) as mask_image:
                original_mask = np.asarray(mask_image.convert("L"))
                resized = mask_image.convert("L").resize(
                    (64, 64), Image.Resampling.NEAREST
                )
                mask = np.asarray(resized)
            topology, _original_binary = component_count(original_mask)
            _resized_topology, binary = component_count(mask)
        else:
            topology, binary = 0, np.zeros((64, 64), dtype=np.uint8)
        return {
            "source_sample_id": sample["source_sample_id"],
            "product_label": sample["product_label"],
            "rank": _rank(split_seed, sample["source_sample_id"]),
            "image_scores": image_scores,
            "score_map": score_map,
            "mask": binary,
            "component_count_proxy": topology,
        }

    development = [
        *by_role["development_normal"],
        *by_role["development_anomaly"],
    ]
    development_by_id = {
        item["source_sample_id"]: item for item in development
    }
    scored = [score_sample(item) for item in development]
    normals = sorted(
        [item for item in scored if item["product_label"] == "normal"],
        key=lambda item: item["rank"],
    )
    anomalies_by_topology = {
        "single": sorted(
            [item for item in scored if item["component_count_proxy"] == 1],
            key=lambda item: item["rank"],
        ),
        "multi": sorted(
            [item for item in scored if item["component_count_proxy"] > 1],
            key=lambda item: item["rank"],
        ),
    }
    calibration = normals[::2]
    evaluation = normals[1::2]
    for members in anomalies_by_topology.values():
        calibration.extend(members[::2])
        evaluation.extend(members[1::2])

    calibration_image_truth = np.asarray(
        [item["product_label"] == "anomaly" for item in calibration],
        dtype=np.uint8,
    )
    aggregation_metrics = {}
    for name in sorted(scored[0]["image_scores"]):
        values = np.asarray([item["image_scores"][name] for item in calibration])
        aggregation_metrics[name] = {
            "image_auroc": float(roc_auc_score(calibration_image_truth, values)),
            "image_average_precision": float(
                average_precision_score(calibration_image_truth, values)
            ),
        }
    selected_aggregation = max(
        aggregation_metrics,
        key=lambda name: (
            aggregation_metrics[name]["image_auroc"],
            aggregation_metrics[name]["image_average_precision"],
            name,
        ),
    )
    for item in scored:
        item["image_score"] = item["image_scores"][selected_aggregation]

    def best_threshold(
        scores: np.ndarray,
        truth: np.ndarray,
        *,
        negative_reference: np.ndarray,
        maximum_false_positive_rate: float,
    ) -> tuple[float, float]:
        candidates = np.unique(np.quantile(scores, np.linspace(0.0, 1.0, 257)))
        best_f1 = -1.0
        best_value = float(candidates[0])
        for threshold in candidates:
            observed_false_positive_rate = float(
                (negative_reference >= threshold).mean()
            )
            if observed_false_positive_rate > maximum_false_positive_rate:
                continue
            prediction = scores >= threshold
            true_positive = int(np.logical_and(prediction, truth == 1).sum())
            false_positive = int(np.logical_and(prediction, truth == 0).sum())
            false_negative = int(np.logical_and(~prediction, truth == 1).sum())
            f1 = 2 * true_positive / max(
                2 * true_positive + false_positive + false_negative, 1
            )
            if f1 > best_f1 or (f1 == best_f1 and threshold > best_value):
                best_f1, best_value = f1, float(threshold)
        if best_f1 < 0:
            raise ValueError("CALIBRATION_FALSE_POSITIVE_CONSTRAINT_UNSATISFIED")
        return best_value, best_f1

    calibration_image_scores = np.asarray(
        [item["image_score"] for item in calibration]
    )
    normal_calibration_image_scores = calibration_image_scores[
        calibration_image_truth == 0
    ]
    image_threshold, calibration_image_f1 = best_threshold(
        calibration_image_scores,
        calibration_image_truth,
        negative_reference=normal_calibration_image_scores,
        maximum_false_positive_rate=0.20,
    )
    calibration_pixel_scores = np.concatenate(
        [item["score_map"].reshape(-1) for item in calibration]
    )
    calibration_pixel_truth = np.concatenate(
        [item["mask"].reshape(-1) for item in calibration]
    )
    normal_calibration_pixel_scores = np.concatenate(
        [
            item["score_map"].reshape(-1)
            for item in calibration
            if item["product_label"] == "normal"
        ]
    )
    pixel_threshold, calibration_pixel_f1 = best_threshold(
        calibration_pixel_scores,
        calibration_pixel_truth,
        negative_reference=normal_calibration_pixel_scores,
        maximum_false_positive_rate=0.01,
    )

    evaluation_image_scores = np.asarray(
        [item["image_score"] for item in evaluation]
    )
    evaluation_image_truth = np.asarray(
        [item["product_label"] == "anomaly" for item in evaluation],
        dtype=np.uint8,
    )
    evaluation_pixel_scores = np.concatenate(
        [item["score_map"].reshape(-1) for item in evaluation]
    )
    evaluation_pixel_truth = np.concatenate(
        [item["mask"].reshape(-1) for item in evaluation]
    )

    def f1_at(scores: np.ndarray, truth: np.ndarray, threshold: float) -> float:
        prediction = scores >= threshold
        true_positive = int(np.logical_and(prediction, truth == 1).sum())
        false_positive = int(np.logical_and(prediction, truth == 0).sum())
        false_negative = int(np.logical_and(~prediction, truth == 1).sum())
        return 2 * true_positive / max(
            2 * true_positive + false_positive + false_negative, 1
        )

    calibration_image_f1 = f1_at(
        calibration_image_scores, calibration_image_truth, image_threshold
    )
    calibration_pixel_f1 = f1_at(
        calibration_pixel_scores, calibration_pixel_truth, pixel_threshold
    )

    def safe_metric(function, truth: np.ndarray, scores: np.ndarray) -> float:
        return float(function(truth, scores)) if len(np.unique(truth)) == 2 else 0.0

    image_predictions = evaluation_image_scores >= image_threshold
    normal_mask = evaluation_image_truth == 0
    heldout = {
        "image_auroc": safe_metric(
            roc_auc_score, evaluation_image_truth, evaluation_image_scores
        ),
        "image_average_precision": safe_metric(
            average_precision_score, evaluation_image_truth, evaluation_image_scores
        ),
        "image_f1": f1_at(
            evaluation_image_scores, evaluation_image_truth, image_threshold
        ),
        "normal_image_false_positive_rate": float(
            image_predictions[normal_mask].mean()
        ),
        "pixel_auroc": safe_metric(
            roc_auc_score, evaluation_pixel_truth, evaluation_pixel_scores
        ),
        "pixel_average_precision": safe_metric(
            average_precision_score, evaluation_pixel_truth, evaluation_pixel_scores
        ),
        "pixel_f1": f1_at(
            evaluation_pixel_scores, evaluation_pixel_truth, pixel_threshold
        ),
        "evaluation_sample_count": len(evaluation),
        "evaluation_resolution": [64, 64],
    }

    def topology_metrics(kind: str) -> dict:
        members = [
            item
            for item in evaluation
            if item["product_label"] == "anomaly"
            and (
                item["component_count_proxy"] == 1
                if kind == "single"
                else item["component_count_proxy"] > 1
            )
        ]
        detected = [item["image_score"] >= image_threshold for item in members]
        component_hits = 0
        component_total = 0
        for item in members:
            prediction = item["score_map"] >= pixel_threshold
            count, labels, stats, _centroids = cv2.connectedComponentsWithStats(
                item["mask"].astype(np.uint8), 8
            )
            for label in range(1, count):
                if stats[label, cv2.CC_STAT_AREA] < 4:
                    continue
                component_total += 1
                region = labels == label
                component_hits += int(float(prediction[region].mean()) >= 0.10)
        return {
            "sample_count": len(members),
            "image_detection_recall": float(np.mean(detected)) if detected else 0.0,
            "component_count_proxy": component_total,
            "component_detected_fraction_at_10pct_overlap": (
                component_hits / component_total if component_total else 0.0
            ),
        }

    heldout["single_region_proxy"] = topology_metrics("single")
    heldout["multi_region_proxy"] = topology_metrics("multi")

    latency_members = evaluation[: min(20, len(evaluation))]
    latency_ms: list[float] = []
    for sample in latency_members:
        torch.cuda.synchronize(device)
        tick = time.perf_counter()
        feature_maps = features(
            [development_by_id[sample["source_sample_id"]]], 1
        )
        with torch.inference_mode():
            fused_anomaly_map(feature_maps)
        torch.cuda.synchronize(device)
        latency_ms.append((time.perf_counter() - tick) * 1000.0)

    for handle in handles:
        handle.remove()
    elapsed = time.perf_counter() - started
    calibration_ids = {item["source_sample_id"] for item in calibration}
    per_sample = [
        {
            "source_sample_id": item["source_sample_id"],
            "split_role": (
                "calibration"
                if item["source_sample_id"] in calibration_ids
                else "heldout_development"
            ),
            "product_label": item["product_label"],
            "component_count_proxy": item["component_count_proxy"],
            "image_score": item["image_score"],
            "predicted_anomaly": bool(item["image_score"] >= image_threshold),
        }
        for item in scored
    ]
    model_pack = {
        "schema_version": _MODEL_PACK_SCHEMA_VERSION,
        "architecture": "YOLO26N_CLASSIFICATION_MULTISCALE_FEATURE_AUTOENCODER",
        "feature_layers": feature_layer_indices,
        "split_seed": split_seed,
        "model_seed": model_seed,
        "image_size": image_size,
        "selected_image_aggregation": selected_aggregation,
        "image_threshold": image_threshold,
        "pixel_threshold": pixel_threshold,
        "input_normalization": input_normalization,
        "feature_fusion": feature_fusion,
        "anomaly_map_blend": {
            "normal_feature_diagonal_gaussian": 0.5,
            "feature_reconstruction_error": 0.5,
        },
        "checkpoint_selection": "minimum_normal_validation_reconstruction_loss",
        "channels": channels,
        "bottlenecks": bottlenecks,
        "backbone": {
            "state_dict": {
                key: value.detach().cpu().clone()
                for key, value in backbone.state_dict().items()
            },
            "model_yaml": dict(backbone_model_yaml),
            "weights_sha256": request["weights_sha256"],
            "provenance": backbone_provenance,
            "license": backbone_license,
        },
        "students": {
            str(layer_index): {
                key: value.detach().cpu().clone()
                for key, value in students[str(layer_index)].state_dict().items()
            }
            for layer_index in feature_layer_indices
        },
        "normalizers": {
            str(layer_index): {
                "normal_reference_mean": reference_means[layer_index].cpu(),
                "normal_reference_variance": reference_variances[layer_index].cpu(),
                "reconstruction_mean": reconstruction_means[layer_index].cpu(),
                "reconstruction_std": reconstruction_stds[layer_index].cpu(),
                "gaussian_mean": gaussian_means[layer_index].cpu(),
                "gaussian_std": gaussian_stds[layer_index].cpu(),
            }
            for layer_index in feature_layer_indices
        },
    }
    checkpoint = output / "best_normality_model_pack.pt"
    torch.save(model_pack, checkpoint)
    checkpoint_sha = _sha_file(checkpoint)
    result = {
        "schema_version": "visiondata-gate.yolo26-normality-worker-result.v1",
        "status": "COMPLETED",
        "implementation_identity": {
            "experiment_tool_sha256": request["experiment_tool_sha256"],
            "policy_module_sha256": request["policy_module_sha256"],
            "runtime_executable_sha256": request["runtime_executable_sha256"],
        },
        "architecture": "YOLO26N_CLASSIFICATION_MULTISCALE_FEATURE_AUTOENCODER",
        "feature_layers": feature_layer_indices,
        "split_seed": split_seed,
        "model_seed": model_seed,
        "feature_fusion": feature_fusion,
        "training_input_policy": "TRAIN_NORMAL_ONLY",
        "development_weight_update_allowed": False,
        "backbone_frozen": True,
        "backbone_weights_sha256": request["weights_sha256"],
        "backbone_provenance": {
            **backbone_provenance,
            "checkpoint_license": backbone_license,
        },
        "checkpoint": {
            "relative_path": checkpoint.relative_to(output).as_posix(),
            "sha256": checkpoint_sha,
            "bytes": checkpoint.stat().st_size,
            "selection": "minimum_normal_validation_reconstruction_loss",
            "feature_layers": feature_layer_indices,
            "format": "PYTORCH_SELF_CONTAINED_INFERENCE_PACK",
            "schema_version": model_pack["schema_version"],
            "contains_backbone": True,
            "selected_image_aggregation": selected_aggregation,
            "image_threshold": image_threshold,
            "pixel_threshold": pixel_threshold,
        },
        "train_losses": train_losses,
        "normal_validation_losses": validation_losses,
        "best_normal_validation_loss": best_loss,
        "calibration": {
            "sample_count": len(calibration),
            "selected_image_aggregation": selected_aggregation,
            "image_aggregation_metrics": aggregation_metrics,
            "image_threshold": image_threshold,
            "pixel_threshold": pixel_threshold,
            "threshold_policy": (
                "best_calibration_f1_subject_to_image_fpr_0.20_and_pixel_fpr_0.01"
            ),
            "image_f1_at_selected_threshold": calibration_image_f1,
            "pixel_f1_at_selected_threshold": calibration_pixel_f1,
        },
        "heldout_development": heldout,
        "per_sample_predictions": per_sample,
        "runtime": {
            "python": sys.version.split()[0],
            "torch": torch.__version__,
            "ultralytics": ultralytics.__version__,
            "device": "cuda:0",
            "gpu_name": torch.cuda.get_device_name(device),
            "peak_allocated_bytes": int(torch.cuda.max_memory_allocated(device)),
            "elapsed_seconds": elapsed,
            "latency_scope": (
                "decode_resize_backbone_multiscale_students_normalizers_"
                "equal_weight_map_no_json_single_image"
            ),
            "latency_sample_count": len(latency_ms),
            "latency_ms_p50": _percentile(latency_ms, 0.50),
            "latency_ms_p95": _percentile(latency_ms, 0.95),
            "latency_ms_max": max(latency_ms) if latency_ms else 0.0,
        },
        "topology_boundary": (
            "8-connected mask regions with minimum area 4 are a topology proxy, "
            "not human instance ground truth"
        ),
        "label_truth_authority": False,
        "industrial_acceptance": "HOLD",
        "production_release_allowed": False,
    }
    checkpoint_roundtrip = torch.load(checkpoint, weights_only=False)
    validation_view, tensor_count, all_tensors_valid = (
        _build_model_pack_validation_view(
            checkpoint_roundtrip,
            tensor_validator=lambda value: (
                isinstance(value, torch.Tensor)
                and value.device.type == "cpu"
                and bool(torch.isfinite(value).all().item())
            ),
        )
    )
    if not all_tensors_valid:
        raise ValueError("MODEL_PACK_TENSOR_INVALID")
    backbone.load_state_dict(checkpoint_roundtrip["backbone"]["state_dict"])
    for layer_index in feature_layer_indices:
        students[str(layer_index)].load_state_dict(
            checkpoint_roundtrip["students"][str(layer_index)]
        )
    result["checkpoint"]["validation_view"] = validation_view
    result["checkpoint"]["roundtrip_validation"] = {
        "checkpoint_sha256": checkpoint_sha,
        "tensor_count": tensor_count,
        "all_tensors_cpu_and_finite": True,
        "backbone_state_dict_reload": "PASS",
        "student_state_dict_reload": {
            str(layer_index): "PASS" for layer_index in feature_layer_indices
        },
    }
    _write_json(result_path, result)
    return 0


def _orchestrate(args: argparse.Namespace) -> int:
    from visiondata_gate.evidence import write_canonical_json
    from visiondata_gate.model_experiment_agent import (
        assign_model_experiment_roles,
        build_model_experiment_agent_receipt,
        build_visa_yolo26_experiment_plan,
        classify_experiment_outcome,
        validate_development_members,
        validate_model_pack_roundtrip,
        validate_model_worker_feature_contract,
        validate_weight_update_members,
    )
    from visiondata_gate.public_governance_bench import (
        PublicSourceBinding,
        VisaSourceIndex,
        verify_public_source_binding,
        verify_visa_source_index,
    )
    from visiondata_gate.runtime_models import (
        RuntimeEvent,
        RuntimeStage,
        RuntimeStatus,
    )

    output = args.output.resolve()
    output.mkdir(parents=True, exist_ok=False)
    private = output / "private"
    private.mkdir()
    root = args.dataset_root.resolve(strict=True)
    runtime = args.runtime_python.resolve(strict=True)
    weights = args.weights.resolve(strict=True)
    binding = PublicSourceBinding.model_validate(_load_json(args.source_binding))
    index = VisaSourceIndex.model_validate(_load_json(args.source_index))
    verify_public_source_binding(binding)
    verify_visa_source_index(index, source_binding=binding)
    if _sha_file(weights) != args.expected_weights_sha256:
        raise ValueError("BACKBONE_WEIGHTS_SHA_MISMATCH")

    category = args.object_class
    category_samples = [
        item for item in index.samples if item.object_class == category
    ]
    train_normal = [
        item
        for item in category_samples
        if item.split == "train" and item.product_label == "normal"
    ]
    development_normal = [
        item
        for item in category_samples
        if item.split == "test" and item.product_label == "normal"
    ]
    development_anomaly = [
        item
        for item in category_samples
        if item.split == "test" and item.product_label == "anomaly"
    ]
    required_train = args.train_samples + args.normal_validation_samples
    if (
        len(train_normal) < required_train
        or len(development_normal) < 4
        or len(development_anomaly) < 4
    ):
        raise ValueError("INSUFFICIENT_CATEGORY_SAMPLES")
    roles = assign_model_experiment_roles(
        train_normal_ids=[item.source_sample_id for item in train_normal],
        development_normal_ids=[
            item.source_sample_id for item in development_normal
        ],
        development_anomaly_ids=[
            item.source_sample_id for item in development_anomaly
        ],
        train_samples=args.train_samples,
        normal_validation_samples=args.normal_validation_samples,
        split_seed=args.split_seed,
        model_seed=args.model_seed,
    )
    selected_train = [
        item
        for item in train_normal
        if roles.get(item.source_sample_id) == "weight_update_train_normal"
    ]
    selected_development = [*development_normal, *development_anomaly]
    validate_weight_update_members(
        [item.model_dump(mode="json") for item in selected_train]
    )
    validate_development_members(
        [item.model_dump(mode="json") for item in selected_development],
        training_ids={item.source_sample_id for item in selected_train},
    )

    selected = [
        item for item in category_samples if item.source_sample_id in roles
    ]
    for sample in selected:
        image = _safe_member(root, sample.image_relative_path)
        if _sha_file(image) != sample.image_sha256:
            raise ValueError("SOURCE_IMAGE_SHA_MISMATCH")
        if sample.mask_relative_path:
            mask = _safe_member(root, sample.mask_relative_path)
            if _sha_file(mask) != sample.mask_sha256:
                raise ValueError("SOURCE_MASK_SHA_MISMATCH")

    plan = build_visa_yolo26_experiment_plan(
        source_binding_sha256=binding.binding_sha256,
        source_index_sha256=index.index_sha256,
        max_epochs=args.epochs,
        max_wall_seconds=args.max_wall_seconds,
        split_seed=args.split_seed,
        model_seed=args.model_seed,
    )
    plan_path = output / "model_experiment_plan.json"
    plan_file_sha = write_canonical_json(plan_path, plan)
    selection = {
        "schema_version": "visiondata-gate.visa-model-selection.v1",
        "dataset_id": "VisA",
        "dataset_version": binding.dataset_version,
        "license_id": binding.license_id,
        "object_class": category,
        "selection_rule": (
            "frozen_user_requested_capsules_single_multi_topology_demo"
        ),
        "split_seed": args.split_seed,
        "model_seed": args.model_seed,
        "roles": {
            role: sum(value == role for value in roles.values())
            for role in sorted(set(roles.values()))
        },
        "samples": [
            {
                "source_sample_id": item.source_sample_id,
                "sample_sha256": item.sample_sha256,
                "image_sha256": item.image_sha256,
                "mask_sha256": item.mask_sha256,
                "role": roles[item.source_sample_id],
            }
            for item in sorted(selected, key=lambda value: value.source_sample_id)
        ],
        "weight_update_uses_development": False,
        "raw_images_transmitted": False,
        "source_assets_copied": False,
        "production_release_allowed": False,
    }
    selection_path = output / "selection_manifest.json"
    selection_sha = write_canonical_json(selection_path, selection)

    worker_output = private / "worker"
    experiment_tool = Path(__file__).resolve()
    policy_module = (
        experiment_tool.parents[1]
        / "src"
        / "visiondata_gate"
        / "model_experiment_agent.py"
    ).resolve(strict=True)
    request = {
        "dataset_root": str(root),
        "weights_path": str(weights),
        "weights_sha256": args.expected_weights_sha256,
        "weights_source_url": (
            "https://github.com/ultralytics/assets/releases/download/"
            "v8.4.0/yolo26n-cls.pt"
        ),
        "worker_output": str(worker_output),
        "experiment_tool_sha256": _sha_file(experiment_tool),
        "policy_module_path": str(policy_module),
        "policy_module_sha256": _sha_file(policy_module),
        "runtime_executable_sha256": _sha_file(runtime),
        "split_seed": plan["split_seed"],
        "model_seed": plan["model_seed"],
        "epochs": args.epochs,
        "image_size": args.image_size,
        "feature_batch_size": args.feature_batch_size,
        "student_batch_size": args.student_batch_size,
        "learning_rate": args.learning_rate,
        "feature_layers": plan["feature_layers"],
        "samples": [
            {
                **item.model_dump(mode="json"),
                "role": roles[item.source_sample_id],
            }
            for item in selected
        ],
    }
    request_path = private / "worker_request.json"
    result_path = private / "worker_result.json"
    _write_json(request_path, request)
    runtime_config = private / "runtime_config"
    (runtime_config / "yolo").mkdir(parents=True)
    (runtime_config / "matplotlib").mkdir()
    environment = {
        key: os.environ[key]
        for key in ("SYSTEMROOT", "WINDIR", "PATH")
        if key in os.environ
    }
    environment.update(
        {
            "CUDA_VISIBLE_DEVICES": "0",
            "YOLO_CONFIG_DIR": str(runtime_config / "yolo"),
            "MPLCONFIGDIR": str(runtime_config / "matplotlib"),
            "YOLO_OFFLINE": "true",
            "YOLO_AUTOINSTALL": "false",
            "WANDB_MODE": "disabled",
            "WANDB_DISABLED": "true",
            "COMET_MODE": "DISABLED",
            "HF_HUB_OFFLINE": "1",
            "TRANSFORMERS_OFFLINE": "1",
            "PYTHONHASHSEED": str(args.model_seed),
            "MPLBACKEND": "Agg",
        }
    )
    log_path = private / "worker.log"
    command = [
        str(runtime),
        str(Path(__file__).resolve()),
        "--worker",
        str(request_path),
        str(result_path),
    ]
    started = time.perf_counter()
    with log_path.open("wb") as log:
        completed = subprocess.run(
            command,
            cwd=output,
            env=environment,
            stdin=subprocess.DEVNULL,
            stdout=log,
            stderr=log,
            timeout=args.max_wall_seconds,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
            check=False,
        )
    if completed.returncode != 0 or not result_path.is_file():
        raise RuntimeError(
            f"MODEL_WORKER_FAILED exit={completed.returncode}; inspect {log_path}"
        )
    worker_result = _load_json(result_path)
    if worker_result.get("status") != "COMPLETED":
        raise RuntimeError("MODEL_WORKER_RESULT_NOT_COMPLETED")
    validate_model_worker_feature_contract(worker_result, plan=plan)
    execution_result_sha = _sha_file(result_path)
    checkpoint = worker_output / worker_result["checkpoint"]["relative_path"]
    checkpoint_sha = _sha_file(checkpoint)
    if checkpoint_sha != worker_result["checkpoint"]["sha256"]:
        raise ValueError("CHECKPOINT_SHA_MISMATCH")
    validate_model_pack_roundtrip(
        worker_result["checkpoint"]["validation_view"],
        worker_result=worker_result,
        actual_checkpoint_sha256=checkpoint_sha,
        tensor_validator=lambda value: value is True,
    )
    for sample in selected:
        image = _safe_member(root, sample.image_relative_path)
        if _sha_file(image) != sample.image_sha256:
            raise ValueError("SOURCE_CHANGED_AFTER_TRAINING")
        if sample.mask_relative_path:
            mask = _safe_member(root, sample.mask_relative_path)
            if _sha_file(mask) != sample.mask_sha256:
                raise ValueError("SOURCE_CHANGED_AFTER_TRAINING")

    metrics = worker_result["heldout_development"]
    outcome = classify_experiment_outcome(
        train_losses=worker_result["train_losses"],
        normal_validation_losses=worker_result["normal_validation_losses"],
        image_auroc=metrics["image_auroc"],
        pixel_auroc=metrics["pixel_auroc"],
        normal_image_false_positive_rate=metrics[
            "normal_image_false_positive_rate"
        ],
        image_f1=metrics["image_f1"],
        pixel_f1=metrics["pixel_f1"],
        single_region_recall=metrics["single_region_proxy"][
            "image_detection_recall"
        ],
        multi_region_recall=metrics["multi_region_proxy"][
            "image_detection_recall"
        ],
    )
    runtime_events: list[RuntimeEvent] = []

    def event(
        stage,
        actor,
        action,
        status,
        summary,
        task_id=None,
        tool_name=None,
        refs=None,
    ) -> None:
        runtime_events.append(
            RuntimeEvent(
                sequence=len(runtime_events) + 1,
                phase=(
                    "verification"
                    if stage is RuntimeStage.DELIVERY
                    else "initial"
                ),
                stage=stage,
                actor=actor,
                action=action,
                status=status,
                summary=summary,
                task_id=task_id,
                tool_name=tool_name,
                evidence_refs=refs or [],
            )
        )

    event(
        RuntimeStage.INTAKE,
        "ModelExperimentManager",
        "freeze_public_source_scope",
        RuntimeStatus.SUCCESS,
        "Bound CC-BY-4.0 source, index and local-only execution scope.",
    )
    event(
        RuntimeStage.PLANNER,
        "EvidenceGapModelPlanner",
        "select_normal_only_route",
        RuntimeStatus.SUCCESS,
        (
            "Selected frozen YOLO26 features plus a normal-only reconstruction "
            "head; rejected anomaly-mask fine-tuning."
        ),
    )
    event(
        RuntimeStage.TOOL,
        "PublicSourceQualificationWorker",
        "verify_selected_source_assets",
        RuntimeStatus.SUCCESS,
        "Verified selected image and mask digests before and after execution.",
        "model.source.verify",
        "public_source_integrity",
        [binding.binding_sha256, index.index_sha256, selection_sha],
    )
    event(
        RuntimeStage.TOOL,
        "SplitIsolationWorker",
        "verify_optimizer_input_boundary",
        RuntimeStatus.SUCCESS,
        (
            "Optimizer membership contains train/normal images only; "
            "development masks are evaluation-only."
        ),
        "model.split.verify",
        "split_isolation",
        [selection_sha],
    )
    event(
        RuntimeStage.TOOL,
        "NormalityHeadTrainerWorker",
        "train_feature_reconstruction_head",
        (
            RuntimeStatus.SUCCESS
            if outcome["optimization_status"] == "CONVERGED"
            else RuntimeStatus.WARNING
        ),
        f"Optimization status: {outcome['optimization_status']}.",
        "model.train",
        "yolo26_feature_autoencoder",
        [execution_result_sha, worker_result["checkpoint"]["sha256"]],
    )
    event(
        RuntimeStage.TOOL,
        "TopologyStratifiedEvaluatorWorker",
        "evaluate_public_development_proxy",
        (
            RuntimeStatus.SUCCESS
            if outcome["effectiveness_status"] != "NOT_ESTABLISHED"
            else RuntimeStatus.WARNING
        ),
        f"Effectiveness status: {outcome['effectiveness_status']}.",
        "model.evaluate",
        "single_multi_topology_evaluation",
        [execution_result_sha],
    )
    event(
        RuntimeStage.COUNCIL,
        "ModelEvidenceCouncil",
        "separate_optimization_effectiveness_and_industrial_claims",
        RuntimeStatus.SUCCESS,
        (
            "Separated loss convergence, public proxy metrics and industrial "
            "acceptance."
        ),
    )
    event(
        RuntimeStage.JUDGE,
        "FrozenModelPolicyJudge",
        "issue_hold_disposition",
        RuntimeStatus.SUCCESS,
        "Public proxy evidence cannot grant factory or production release.",
    )
    event(
        RuntimeStage.DELIVERY,
        "EvidenceDelivery",
        "seal_model_experiment_receipts",
        RuntimeStatus.SUCCESS,
        (
            "Sealed plan, selection, runtime, checkpoint and metric evidence "
            "with production release false."
        ),
    )
    event_path = output / "agent_runtime_events.json"
    event_sha = write_canonical_json(
        event_path, [item.model_dump(mode="json") for item in runtime_events]
    )
    agent_receipt = build_model_experiment_agent_receipt(
        plan=plan,
        events=runtime_events,
        execution_result_sha256=execution_result_sha,
        checkpoint_sha256=worker_result["checkpoint"]["sha256"],
        outcome=outcome,
    )
    agent_receipt_path = output / "model_experiment_agent_receipt.json"
    agent_receipt_file_sha = write_canonical_json(
        agent_receipt_path, agent_receipt
    )
    public_result = {
        key: value
        for key, value in worker_result.items()
        if key != "per_sample_predictions"
    }
    public_result["checkpoint"] = {
        **public_result["checkpoint"],
        "relative_path": (
            "private/worker/" + public_result["checkpoint"]["relative_path"]
        ),
    }
    public_result_path = output / "model_result.json"
    public_result_sha = write_canonical_json(public_result_path, public_result)
    receipt = {
        "schema_version": "visiondata-gate.visa-yolo26-normality-experiment.v1",
        "completed_at": datetime.now(UTC).isoformat(),
        "status": "LOCAL_PUBLIC_PROXY_EXPERIMENT_COMPLETED",
        "dataset_id": "VisA",
        "dataset_version": binding.dataset_version,
        "license_id": binding.license_id,
        "object_class": category,
        "architecture": worker_result["architecture"],
        "feature_layers": worker_result["feature_layers"],
        "split_seed": worker_result["split_seed"],
        "model_seed": worker_result["model_seed"],
        "feature_fusion": worker_result["feature_fusion"],
        "plan_file_sha256": plan_file_sha,
        "selection_manifest_sha256": selection_sha,
        "runtime_event_file_sha256": event_sha,
        "agent_receipt_file_sha256": agent_receipt_file_sha,
        "model_result_file_sha256": public_result_sha,
        "checkpoint_sha256": worker_result["checkpoint"]["sha256"],
        "backbone_weights_sha256": args.expected_weights_sha256,
        "implementation_identity": worker_result["implementation_identity"],
        "optimization_status": outcome["optimization_status"],
        "effectiveness_status": outcome["effectiveness_status"],
        "industrial_acceptance": "HOLD",
        "official_platform_result": "NOT_APPLICABLE_GOAI_PUBLIC_PROXY",
        "factory_shadow_test": "NOT_RUN",
        "label_truth_authority": False,
        "raw_images_transmitted": False,
        "source_assets_copied": False,
        "machine_write_permitted": False,
        "production_release_allowed": False,
        "elapsed_seconds_orchestrator": time.perf_counter() - started,
        "claim_boundary": (
            "This is a local model experiment on the public CC-BY-4.0 VisA "
            "proxy. It is not Omni-AD competition training, factory validation, "
            "customer acceptance, production release, or proof of human "
            "instance labels."
        ),
    }
    receipt_path = output / "RUN_RECEIPT.json"
    receipt_sha = write_canonical_json(receipt_path, receipt)
    report = f"""# VisA YOLO26n 正常性模型实验

- 状态：`{receipt['status']}`
- Agent 收口：`{agent_receipt['final_disposition']}`
- 数据切分 Seed：`{receipt['split_seed']}`
- 模型训练 Seed：`{receipt['model_seed']}`
- 优化收敛：`{outcome['optimization_status']}`
- 公共开发集效果：`{outcome['effectiveness_status']}`
- 图像 AUROC：`{metrics['image_auroc']:.6f}`
- 像素 AUROC：`{metrics['pixel_auroc']:.6f}`
- 图像 F1：`{metrics['image_f1']:.6f}`
- 像素 F1：`{metrics['pixel_f1']:.6f}`
- 单区域代理召回：`{metrics['single_region_proxy']['image_detection_recall']:.6f}`
- 多区域代理召回：`{metrics['multi_region_proxy']['image_detection_recall']:.6f}`
- 本机 P50/P95/Max：`{worker_result['runtime']['latency_ms_p50']:.3f}` / `{worker_result['runtime']['latency_ms_p95']:.3f}` / `{worker_result['runtime']['latency_ms_max']:.3f}` ms
- Peak allocated VRAM：`{worker_result['runtime']['peak_allocated_bytes']}` bytes
- Run receipt SHA-256：`{receipt_sha}`

> 边界：仅为公开 VisA 代理实验。`production_release_allowed=false`，工厂 shadow test 未运行；单/多区域为 mask 8 连通域代理，不是人工实例真值。
"""
    (output / "RUN_SUMMARY.md").write_text(report, encoding="utf-8")
    serialized = "\n".join(
        path.read_text(encoding="utf-8", errors="ignore")
        for path in output.iterdir()
        if path.is_file()
    )
    for forbidden in (str(root), str(weights), str(runtime)):
        if forbidden in serialized:
            raise RuntimeError("PUBLIC_RECEIPT_PATH_REDACTION_FAILED")
    print(
        json.dumps(
            {
                "status": receipt["status"],
                "optimization_status": outcome["optimization_status"],
                "effectiveness_status": outcome["effectiveness_status"],
                "run_receipt_sha256": receipt_sha,
                "output": str(output),
            },
            ensure_ascii=False,
        )
    )
    return 0


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--worker", nargs=2, metavar=("REQUEST", "RESULT"))
    parser.add_argument("--dataset-root", type=Path)
    parser.add_argument("--source-binding", type=Path)
    parser.add_argument("--source-index", type=Path)
    parser.add_argument("--runtime-python", type=Path)
    parser.add_argument("--weights", type=Path)
    parser.add_argument("--expected-weights-sha256")
    parser.add_argument("--output", type=Path)
    parser.add_argument("--object-class", default="capsules")
    parser.add_argument("--split-seed", type=int, default=20260913)
    parser.add_argument(
        "--model-seed", "--seed", dest="model_seed", type=int, default=20260913
    )
    parser.add_argument("--epochs", type=int, default=12)
    parser.add_argument("--max-wall-seconds", type=int, default=1800)
    parser.add_argument("--train-samples", type=int, default=192)
    parser.add_argument("--normal-validation-samples", type=int, default=48)
    parser.add_argument("--image-size", type=int, default=256)
    parser.add_argument("--feature-batch-size", type=int, default=16)
    parser.add_argument("--student-batch-size", type=int, default=16)
    parser.add_argument("--learning-rate", type=float, default=0.001)
    return parser


def main() -> int:
    args = _parser().parse_args()
    if args.worker:
        return _worker(Path(args.worker[0]), Path(args.worker[1]))
    required = (
        "dataset_root",
        "source_binding",
        "source_index",
        "runtime_python",
        "weights",
        "expected_weights_sha256",
        "output",
    )
    missing = [name for name in required if getattr(args, name) is None]
    if missing:
        raise ValueError("MISSING_ARGUMENTS:" + ",".join(missing))
    if not (1 <= args.epochs <= 100 and 60 <= args.max_wall_seconds <= 14_400):
        raise ValueError("EXPERIMENT_BUDGET_INVALID")
    if not (
        0 <= args.split_seed <= 2**31 - 1
        and 0 <= args.model_seed <= 2**31 - 1
    ):
        raise ValueError("EXPERIMENT_SEED_INVALID")
    if not (64 <= args.image_size <= 640 and args.image_size % 32 == 0):
        raise ValueError("IMAGE_SIZE_INVALID")
    return _orchestrate(args)


if __name__ == "__main__":
    raise SystemExit(main())
