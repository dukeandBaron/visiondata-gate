"""Bounded external-runtime validation and inference for normality model packs.

The application process never imports torch or deserializes a pack.  A named
external Python runtime performs those operations in a fresh local process with
network and child-process creation disabled.  This is process isolation against
accidental integration calls, not an OS security sandbox for hostile pickle or
native code; callers must separately authorize both the exact runtime and pack.
"""

from __future__ import annotations

import hashlib
import importlib.util
import json
import math
from collections.abc import Callable
import os
from pathlib import Path
import shutil
import subprocess
import sys
import sysconfig
import time


def _sha(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _valid_sha(value: str) -> bool:
    return (
        isinstance(value, str)
        and len(value) == 64
        and all(character in "0123456789abcdef" for character in value)
    )


def _checked_file(path: Path, expected: str, error: str) -> Path:
    candidate = Path(path).expanduser().resolve(strict=True)
    if (
        not candidate.is_file()
        or candidate.is_symlink()
        or not _valid_sha(expected)
        or _sha(candidate) != expected
    ):
        raise ValueError(error)
    return candidate


def _validate_pack_contract(
    pack: dict,
    *,
    expected_backbone_weights_sha256: str,
    tensor_validator: Callable[[object], bool],
) -> dict:
    """Validate the v2 pack structure without depending on a concrete tensor type."""

    if not isinstance(pack, dict) or pack.get("schema_version") != (
        "visiondata-gate.yolo26-normality-model-pack.v2"
    ):
        raise ValueError("NORMALITY_MODEL_PACK_V2_REQUIRED")
    layers = pack.get("feature_layers")
    if (
        pack.get("architecture")
        != "YOLO26N_CLASSIFICATION_MULTISCALE_FEATURE_AUTOENCODER"
        or layers != [4, 6, 9]
    ):
        raise ValueError("NORMALITY_MODEL_PACK_ARCHITECTURE_INVALID")
    if any(type(pack.get(name)) is not int for name in ("split_seed", "model_seed")):
        raise ValueError("NORMALITY_MODEL_PACK_SEED_INVALID")
    image_size = pack.get("image_size")
    image_threshold = pack.get("image_threshold")
    pixel_threshold = pack.get("pixel_threshold")
    if (
        type(image_size) is not int
        or image_size <= 0
        or type(image_threshold) not in {int, float}
        or not math.isfinite(float(image_threshold))
        or float(image_threshold) < 0.0
        or type(pixel_threshold) not in {int, float}
        or not math.isfinite(float(pixel_threshold))
        or float(pixel_threshold) < 0.0
        or pack.get("selected_image_aggregation")
        not in {
            "max",
            "mean",
            "top_0_1pct",
            "top_0_5pct",
            "top_1pct",
            "top_2pct",
            "top_5pct",
            "top_10pct",
        }
    ):
        raise ValueError("NORMALITY_MODEL_PACK_THRESHOLD_INVALID")
    normalization = pack.get("input_normalization")
    if (
        not isinstance(normalization, dict)
        or normalization.get("color_space") != "RGB"
        or normalization.get("value_scale") != [0.0, 1.0]
        or normalization.get("resize") != [image_size, image_size]
        or normalization.get("mean") != [0.0, 0.0, 0.0]
        or normalization.get("std") != [1.0, 1.0, 1.0]
    ):
        raise ValueError("NORMALITY_NATIVE_PREPROCESSING_REQUIRED")
    fusion = pack.get("feature_fusion")
    weights = fusion.get("layer_weights") if isinstance(fusion, dict) else None
    expected_layer_keys = {"4", "6", "9"}
    if (
        not isinstance(fusion, dict)
        or fusion.get("strategy") != "equal_weight_mean"
        or fusion.get("target_resolution") != [64, 64]
        or not isinstance(weights, dict)
        or set(weights) != expected_layer_keys
        or any(
            type(weight) not in {int, float}
            or not math.isfinite(float(weight))
            or not math.isclose(float(weight), 1.0 / 3.0, abs_tol=1e-12)
            for weight in weights.values()
        )
    ):
        raise ValueError("NORMALITY_MODEL_PACK_FUSION_INVALID")
    blend = pack.get("anomaly_map_blend")
    if blend != {
        "normal_feature_diagonal_gaussian": 0.5,
        "feature_reconstruction_error": 0.5,
    }:
        raise ValueError("NORMALITY_MODEL_PACK_BLEND_INVALID")
    backbone = pack.get("backbone")
    provenance = backbone.get("provenance") if isinstance(backbone, dict) else None
    state = backbone.get("state_dict") if isinstance(backbone, dict) else None
    if (
        not isinstance(backbone, dict)
        or not isinstance(state, dict)
        or not state
        or not isinstance(backbone.get("model_yaml"), dict)
        or not backbone["model_yaml"]
        or backbone.get("weights_sha256") != expected_backbone_weights_sha256
        or not isinstance(backbone.get("license"), str)
        or not backbone["license"].strip()
        or not isinstance(provenance, dict)
        or provenance.get("provider") != "Ultralytics"
        or provenance.get("architecture") != "yolo26n-cls"
        or provenance.get("task") != "classify"
        or provenance.get("class_count") != 1000
        or provenance.get("pretraining_dataset") != "ImageNet"
        or provenance.get("source_url")
        != "https://github.com/ultralytics/assets/releases/download/"
        "v8.4.0/yolo26n-cls.pt"
    ):
        raise ValueError("NORMALITY_MODEL_PACK_BACKBONE_INVALID")
    students = pack.get("students")
    normalizers = pack.get("normalizers")
    channels = pack.get("channels")
    bottlenecks = pack.get("bottlenecks")
    if (
        not isinstance(students, dict)
        or set(students) != expected_layer_keys
        or not isinstance(normalizers, dict)
        or set(normalizers) != expected_layer_keys
        or not isinstance(channels, dict)
        or set(channels) != {4, 6, 9}
        or not isinstance(bottlenecks, dict)
        or set(bottlenecks) != {4, 6, 9}
        or any(type(value) is not int or value <= 0 for value in channels.values())
        or any(
            type(value) is not int or value <= 0 for value in bottlenecks.values()
        )
    ):
        raise ValueError("NORMALITY_MODEL_PACK_LAYER_CONTRACT_INVALID")
    normalizer_names = {
        "normal_reference_mean",
        "normal_reference_variance",
        "reconstruction_mean",
        "reconstruction_std",
        "gaussian_mean",
        "gaussian_std",
    }
    tensors = list(state.values())
    for key in expected_layer_keys:
        if (
            not isinstance(students[key], dict)
            or not students[key]
            or not isinstance(normalizers[key], dict)
            or set(normalizers[key]) != normalizer_names
        ):
            raise ValueError("NORMALITY_MODEL_PACK_LAYER_STATE_INVALID")
        tensors.extend(students[key].values())
        tensors.extend(normalizers[key].values())
    if not tensors or any(not tensor_validator(value) for value in tensors):
        raise ValueError("NORMALITY_MODEL_PACK_TENSOR_INVALID")
    return {
        "model_pack_schema_version": pack["schema_version"],
        "architecture": pack["architecture"],
        "feature_layers": list(layers),
        "split_seed": pack["split_seed"],
        "model_seed": pack["model_seed"],
        "image_size": image_size,
        "selected_image_aggregation": pack["selected_image_aggregation"],
        "image_threshold": float(image_threshold),
        "pixel_threshold": float(pixel_threshold),
        "input_normalization": dict(normalization),
        "backbone_weights_sha256": backbone["weights_sha256"],
    }


def _write_json(path: Path, value: object) -> None:
    path.write_text(
        json.dumps(value, sort_keys=True, indent=2, allow_nan=False),
        encoding="utf-8",
    )


def _child_environment(work_root: Path) -> dict[str, str]:
    root = work_root.resolve()
    root.mkdir(parents=True, exist_ok=True)
    environment = {
        key: os.environ[key] for key in ("SYSTEMROOT", "WINDIR") if key in os.environ
    }
    environment.update(
        {
            "HOME": str(root),
            "USERPROFILE": str(root),
            # Windows getpass otherwise imports the unavailable Unix pwd module
            # during Torch optimizer/Dynamo cache initialization. Never inherit
            # the caller's identifying USER/LOGNAME/USERNAME values.
            "USERNAME": "visiondata-worker",
            "APPDATA": str(root),
            "LOCALAPPDATA": str(root),
            "TEMP": str(root),
            "TMP": str(root),
            "YOLO_CONFIG_DIR": str(root / "yolo"),
            "MPLCONFIGDIR": str(root / "matplotlib"),
            "TORCH_HOME": str(root / "torch"),
            "XDG_CACHE_HOME": str(root / "cache"),
            "CUDA_VISIBLE_DEVICES": "",
            "WANDB_MODE": "disabled",
            "WANDB_DISABLED": "true",
            "COMET_MODE": "DISABLED",
            "HF_HUB_OFFLINE": "1",
            "TRANSFORMERS_OFFLINE": "1",
            "YOLO_OFFLINE": "true",
            "YOLO_AUTOINSTALL": "false",
            "YOLO_VERBOSE": "false",
            "MPLBACKEND": "Agg",
            "PYTHONDONTWRITEBYTECODE": "1",
            "OMP_NUM_THREADS": "2",
            "MKL_NUM_THREADS": "2",
            "OPENBLAS_NUM_THREADS": "2",
            "NUMEXPR_NUM_THREADS": "2",
        }
    )
    return environment


def _worker_command(
    executable: Path,
    mode: str,
    request_path: Path,
    result_path: Path,
) -> list[str]:
    return [
        str(executable),
        "-B",
        "-I",
        "-S",
        str(Path(__file__).resolve()),
        "worker",
        mode,
        str(request_path),
        str(result_path),
    ]


def _run_worker_process(
    *,
    mode: str,
    executable: Path,
    request: dict,
    output_root: Path,
    max_seconds: int,
) -> dict:
    if mode not in {"validate", "infer", "ttt"}:
        raise ValueError("NORMALITY_WORKER_MODE_INVALID")
    if type(max_seconds) is not int or not 5 <= max_seconds <= 300:
        raise ValueError("NORMALITY_WORKER_BUDGET_INVALID")
    output = Path(output_root).expanduser().resolve()
    output.mkdir(parents=True, exist_ok=False)
    request_path = output / "request.json"
    result_path = output / "result.json"
    _write_json(request_path, request)
    command = _worker_command(executable, mode, request_path, result_path)
    started = time.monotonic()
    with (output / "worker.log").open("wb") as log:
        process = subprocess.Popen(
            command,
            env=_child_environment(output / "environment"),
            cwd=output,
            stdin=subprocess.DEVNULL,
            stdout=log,
            stderr=log,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
        try:
            while process.poll() is None:
                if time.monotonic() - started >= max_seconds:
                    process.terminate()
                    try:
                        process.wait(timeout=5)
                    except subprocess.TimeoutExpired:
                        process.kill()
                        process.wait(timeout=5)
                    raise ValueError("NORMALITY_WORKER_TIMEOUT")
                time.sleep(0.05)
        finally:
            if process.poll() is None:
                process.kill()
                process.wait(timeout=5)
    if process.returncode != 0 or not result_path.is_file():
        raise ValueError("NORMALITY_WORKER_FAILED")
    try:
        value = json.loads(result_path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError):
        raise ValueError("NORMALITY_WORKER_RESULT_INVALID") from None
    if not isinstance(value, dict):
        raise ValueError("NORMALITY_WORKER_RESULT_INVALID")
    return value


def _package_paths() -> None:
    for key in ("purelib", "platlib"):
        location = sysconfig.get_path(key)
        if location and location not in sys.path:
            sys.path.append(location)


def _deny_network_and_children() -> None:
    import socket

    def denied(*_args: object, **_kwargs: object) -> None:
        raise OSError("NORMALITY_NETWORK_OR_CHILD_PROCESS_DISABLED")

    socket.create_connection = denied
    socket.getaddrinfo = denied
    socket.gethostbyname = denied
    socket.gethostbyname_ex = denied
    socket.gethostbyaddr = denied
    socket.getnameinfo = denied
    socket.socket.connect = denied
    socket.socket.connect_ex = denied
    socket.socket.sendto = denied
    if hasattr(socket.socket, "sendmsg"):
        socket.socket.sendmsg = denied

    def audit(event: str, _args: tuple) -> None:
        if (event.startswith("socket.") and event != "socket.__new__") or event in {
            "subprocess.Popen",
            "os.system",
            "os.exec",
            "os.posix_spawn",
        }:
            raise OSError("NORMALITY_NETWORK_OR_CHILD_PROCESS_DISABLED")

    sys.addaudithook(audit)


def _runtime_metadata(expected_executable_sha256: str) -> dict:
    """Reuse the registered runtime fingerprint algorithm by exact source file."""

    backend_path = Path(__file__).with_name("learning_yolo_backend.py").resolve()
    spec = importlib.util.spec_from_file_location(
        "_visiondata_gate_normality_runtime_metadata", backend_path
    )
    if spec is None or spec.loader is None:
        raise ValueError("NORMALITY_RUNTIME_METADATA_UNAVAILABLE")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    try:
        spec.loader.exec_module(module)
        return module._runtime_metadata(expected_executable_sha256)
    finally:
        if sys.modules.get(spec.name) is module:
            del sys.modules[spec.name]


def _torch_load_model_pack(torch_module, pack_path: Path) -> dict:
    """Use PyTorch's restricted weights-only loader on CPU, without fallback."""

    return torch_module.load(pack_path, map_location="cpu", weights_only=True)


def _load_normality_pack(
    pack_path: Path,
    expected_model_pack_sha256: str,
    expected_backbone_weights_sha256: str,
) -> dict:
    """Deserialize and rebuild a trusted pack only inside the external child."""

    pack_path = _checked_file(
        pack_path,
        expected_model_pack_sha256,
        "NORMALITY_MODEL_PACK_SHA_MISMATCH",
    )
    import torch
    from torch import nn
    from ultralytics.nn.tasks import ClassificationModel

    torch.set_num_threads(int(os.environ.get("OMP_NUM_THREADS", "2")))
    pack = _torch_load_model_pack(torch, pack_path)
    metadata = _validate_pack_contract(
        pack,
        expected_backbone_weights_sha256=expected_backbone_weights_sha256,
        tensor_validator=lambda value: (
            isinstance(value, torch.Tensor)
            and value.device.type == "cpu"
            and bool(torch.isfinite(value).all().item())
        ),
    )
    backbone = ClassificationModel(
        cfg=pack["backbone"]["model_yaml"],
        ch=3,
        nc=1000,
        verbose=False,
    )
    backbone.load_state_dict(pack["backbone"]["state_dict"], strict=True)
    backbone.eval()

    class FeatureDenoisingAutoencoder(nn.Module):
        def __init__(self, layer: int) -> None:
            super().__init__()
            channels = pack["channels"][layer]
            bottleneck = pack["bottlenecks"][layer]
            hidden = max(bottleneck * 2, min(256, channels // 2))
            self.network = nn.Sequential(
                nn.Conv2d(channels, hidden, 1),
                nn.GELU(),
                nn.Conv2d(hidden, hidden, 3, padding=1, groups=hidden),
                nn.GELU(),
                nn.Conv2d(hidden, bottleneck, 1),
                nn.GELU(),
                nn.Conv2d(bottleneck, hidden, 1),
                nn.GELU(),
                nn.Conv2d(hidden, channels, 1),
            )

        def forward(self, value):
            return self.network(value)

    students = nn.ModuleDict(
        {
            str(layer): FeatureDenoisingAutoencoder(layer)
            for layer in pack["feature_layers"]
        }
    )
    for layer in pack["feature_layers"]:
        students[str(layer)].load_state_dict(pack["students"][str(layer)], strict=True)
    students.eval()
    return metadata | {
        "_torch": torch,
        "_pack": pack,
        "_backbone": backbone,
        "_students": students,
    }


def _child_validate(request: dict) -> dict:
    required = {
        "schema_version",
        "runtime_executable_sha256",
        "runtime_sha256",
        "model_pack_path",
        "model_pack_sha256",
        "backbone_weights_sha256",
        "source_binding_sha256",
        "source_index_sha256",
        "inference_backend_sha256",
        "device",
        "production_release_allowed",
        "machine_write_permitted",
    }
    if not isinstance(request, dict) or set(request) != required:
        raise ValueError("NORMALITY_WORKER_REQUEST_INVALID")
    if (
        request["schema_version"] != "visiondata-gate.normality-worker-request.v1"
        or request["device"] != "cpu"
        or request["production_release_allowed"] is not False
        or request["machine_write_permitted"] is not False
        or request["inference_backend_sha256"] != _sha(Path(__file__).resolve())
    ):
        raise ValueError("NORMALITY_WORKER_BOUNDARY_INVALID")
    _checked_file(
        Path(sys.executable),
        request["runtime_executable_sha256"],
        "NORMALITY_RUNTIME_EXECUTABLE_SHA_MISMATCH",
    )
    runtime = _runtime_metadata(request["runtime_executable_sha256"])
    if (
        runtime.get("status") != "ready"
        or runtime.get("runtime_sha256") != request["runtime_sha256"]
    ):
        raise ValueError("NORMALITY_RUNTIME_FINGERPRINT_MISMATCH")
    loaded = _load_normality_pack(
        Path(request["model_pack_path"]),
        request["model_pack_sha256"],
        request["backbone_weights_sha256"],
    )
    if loaded.get("model_pack_schema_version") != (
        "visiondata-gate.yolo26-normality-model-pack.v2"
    ) or loaded.get("backbone_weights_sha256") != request[
        "backbone_weights_sha256"
    ]:
        raise ValueError("NORMALITY_MODEL_PACK_IDENTITY_MISMATCH")
    return {
        "status": "validated",
        "runtime_sha256": request["runtime_sha256"],
        "model_pack_sha256": request["model_pack_sha256"],
        "model_pack_schema_version": loaded["model_pack_schema_version"],
        "backbone_weights_sha256": request["backbone_weights_sha256"],
        "source_binding_sha256": request["source_binding_sha256"],
        "source_index_sha256": request["source_index_sha256"],
        "inference_backend_sha256": request["inference_backend_sha256"],
        "device": "cpu",
        "machine_write_permitted": False,
        "production_release_allowed": False,
    }


def _score_normality_image(
    loaded: dict,
    image_path: Path,
    expected_image_sha256: str,
    heatmap_path: Path,
) -> dict:
    """Score one image and write a bounded 64x64 grayscale evidence map."""

    torch = loaded["_torch"]
    pack = loaded["_pack"]
    backbone = loaded["_backbone"]
    students = loaded["_students"]
    import numpy as np
    from PIL import Image
    from torch.nn import functional

    image_path = _checked_file(
        image_path,
        expected_image_sha256,
        "NORMALITY_INPUT_IMAGE_SHA_MISMATCH",
    )
    if (
        image_path.suffix.lower() not in {".png", ".jpg", ".jpeg", ".bmp"}
        or image_path.stat().st_size > 64 * 1024 * 1024
    ):
        raise ValueError("NORMALITY_INPUT_IMAGE_FORMAT_OR_SIZE_UNSUPPORTED")
    image_size = loaded["image_size"]
    with Image.open(image_path) as opened:
        opened.verify()
    with Image.open(image_path) as opened:
        original_width, original_height = opened.size
        rgb = opened.convert("RGB").resize(
            (image_size, image_size), Image.Resampling.BILINEAR
        )
        array = np.asarray(rgb, dtype=np.float32) / 255.0
    normalization = loaded["input_normalization"]
    mean = torch.tensor(normalization["mean"], dtype=torch.float32)[:, None, None]
    std = torch.tensor(normalization["std"], dtype=torch.float32)[:, None, None]
    tensor = torch.from_numpy(array).permute(2, 0, 1)
    tensor = ((tensor - mean) / std).unsqueeze(0)
    layers = loaded["feature_layers"]
    captured: dict[int, object] = {}

    def capture(layer: int):
        def callback(_module, _inputs, output):
            value = output[0] if isinstance(output, (tuple, list)) else output
            if not isinstance(value, torch.Tensor) or value.ndim != 4:
                raise ValueError("NORMALITY_FEATURE_TENSOR_INVALID")
            captured[layer] = value

        return callback

    handles = [
        backbone.model[layer].register_forward_hook(capture(layer)) for layer in layers
    ]
    started = time.perf_counter()
    try:
        with torch.inference_mode():
            backbone(tensor)
            if set(captured) != set(layers):
                raise ValueError("NORMALITY_FEATURE_CAPTURE_INVALID")
            layer_maps = []
            for layer in layers:
                feature = functional.normalize(captured[layer].float(), dim=1)
                normalizers = pack["normalizers"][str(layer)]
                reconstruction = (
                    students[str(layer)](feature) - feature
                ).square().mean(dim=1, keepdim=True)
                gaussian = (
                    (feature - normalizers["normal_reference_mean"].float()).square()
                    / normalizers["normal_reference_variance"].float()
                ).mean(dim=1, keepdim=True)
                reconstruction_score = functional.relu(
                    (reconstruction - normalizers["reconstruction_mean"].float())
                    / normalizers["reconstruction_std"].float()
                )
                gaussian_score = functional.relu(
                    (gaussian - normalizers["gaussian_mean"].float())
                    / normalizers["gaussian_std"].float()
                )
                layer_maps.append(
                    functional.interpolate(
                        0.5 * reconstruction_score + 0.5 * gaussian_score,
                        size=(64, 64),
                        mode="bilinear",
                        align_corners=False,
                    )
                )
            score_map = torch.stack(layer_maps).mean(dim=0)[0, 0]
    finally:
        for handle in handles:
            handle.remove()
    latency_ms = (time.perf_counter() - started) * 1000.0
    if not bool(torch.isfinite(score_map).all().item()):
        raise ValueError("NORMALITY_NONFINITE_SCORE_MAP")
    values = score_map.detach().cpu().numpy().astype(np.float32)
    flat = np.sort(values.reshape(-1))
    aggregation = loaded["selected_image_aggregation"]
    if aggregation == "max":
        image_score = float(flat[-1])
    elif aggregation == "mean":
        image_score = float(flat.mean())
    else:
        fraction = {
            "top_0_1pct": 0.001,
            "top_0_5pct": 0.005,
            "top_1pct": 0.01,
            "top_2pct": 0.02,
            "top_5pct": 0.05,
            "top_10pct": 0.10,
        }[aggregation]
        count = max(1, int(len(flat) * fraction))
        image_score = float(flat[-count:].mean())
    image_threshold = float(loaded["image_threshold"])
    pixel_threshold = float(loaded["pixel_threshold"])
    positive_pixel_fraction = float((values >= pixel_threshold).mean())
    scale = pixel_threshold * 2.0
    if scale <= 0.0:
        scale = float(values.max()) if float(values.max()) > 0.0 else 1.0
    rendered = np.clip(values / scale, 0.0, 1.0)
    rendered = np.rint(rendered * 255.0).astype(np.uint8)
    heatmap_path = Path(heatmap_path).resolve()
    heatmap_path.parent.mkdir(parents=True, exist_ok=False)
    Image.fromarray(rendered).save(heatmap_path, format="PNG")
    if _sha(image_path) != expected_image_sha256:
        raise ValueError("NORMALITY_INPUT_IMAGE_SHA_MISMATCH")
    return {
        "image_score": image_score,
        "image_threshold": image_threshold,
        "pixel_threshold": pixel_threshold,
        "predicted_anomaly": image_score >= image_threshold,
        "positive_pixel_fraction": positive_pixel_fraction,
        "heatmap_sha256": _sha(heatmap_path),
        "heatmap_bytes": heatmap_path.stat().st_size,
        "heatmap_width": 64,
        "heatmap_height": 64,
        "input_width": original_width,
        "input_height": original_height,
        "latency_ms": latency_ms,
    }


def _child_infer(request: dict) -> dict:
    base_fields = {
        "schema_version",
        "runtime_executable_sha256",
        "runtime_sha256",
        "model_pack_path",
        "model_pack_sha256",
        "backbone_weights_sha256",
        "source_binding_sha256",
        "source_index_sha256",
        "inference_backend_sha256",
        "device",
        "production_release_allowed",
        "machine_write_permitted",
    }
    if not isinstance(request, dict) or set(request) != base_fields | {
        "image_path",
        "image_sha256",
        "heatmap_path",
    }:
        raise ValueError("NORMALITY_INFERENCE_REQUEST_INVALID")
    if (
        request["schema_version"] != "visiondata-gate.normality-worker-request.v1"
        or request["device"] != "cpu"
        or request["production_release_allowed"] is not False
        or request["machine_write_permitted"] is not False
        or request["inference_backend_sha256"] != _sha(Path(__file__).resolve())
    ):
        raise ValueError("NORMALITY_WORKER_BOUNDARY_INVALID")
    _checked_file(
        Path(sys.executable),
        request["runtime_executable_sha256"],
        "NORMALITY_RUNTIME_EXECUTABLE_SHA_MISMATCH",
    )
    runtime = _runtime_metadata(request["runtime_executable_sha256"])
    if (
        runtime.get("status") != "ready"
        or runtime.get("runtime_sha256") != request["runtime_sha256"]
    ):
        raise ValueError("NORMALITY_RUNTIME_FINGERPRINT_MISMATCH")
    loaded = _load_normality_pack(
        Path(request["model_pack_path"]),
        request["model_pack_sha256"],
        request["backbone_weights_sha256"],
    )
    if loaded.get("model_pack_schema_version") != (
        "visiondata-gate.yolo26-normality-model-pack.v2"
    ) or loaded.get("backbone_weights_sha256") != request[
        "backbone_weights_sha256"
    ]:
        raise ValueError("NORMALITY_MODEL_PACK_IDENTITY_MISMATCH")
    scored = _score_normality_image(
        loaded,
        Path(request["image_path"]),
        request["image_sha256"],
        Path(request["heatmap_path"]),
    )
    return {
        "status": "completed",
        "runtime_sha256": request["runtime_sha256"],
        "model_pack_sha256": request["model_pack_sha256"],
        "model_pack_schema_version": loaded["model_pack_schema_version"],
        "backbone_weights_sha256": request["backbone_weights_sha256"],
        "source_binding_sha256": request["source_binding_sha256"],
        "source_index_sha256": request["source_index_sha256"],
        "image_sha256": request["image_sha256"],
        "inference_backend_sha256": request["inference_backend_sha256"],
        **scored,
        "device": "cpu",
        "machine_write_permitted": False,
        "production_release_allowed": False,
    }


def _worker_main(argv: list[str]) -> int:
    if len(argv) != 4 or argv[0] != "worker" or argv[1] not in {"validate", "infer", "ttt"}:
        return 2
    _package_paths()
    _deny_network_and_children()
    request_path = Path(argv[2]).resolve(strict=True)
    result_path = Path(argv[3]).resolve()
    try:
        request = json.loads(request_path.read_text(encoding="utf-8"))
        if argv[1] == "ttt":
            if __package__:
                from . import normality_ttt
            else:
                spec = importlib.util.spec_from_file_location(
                    "_normality_ttt_worker", Path(__file__).with_name("normality_ttt.py")
                )
                normality_ttt = importlib.util.module_from_spec(spec)
                spec.loader.exec_module(normality_ttt)
            result = normality_ttt.child_ttt(request)
        else:
            result = _child_validate(request) if argv[1] == "validate" else _child_infer(request)
        _write_json(result_path, result)
        return 0
    except Exception as error:
        _write_json(
            result_path,
            {
                "status": "failed",
                "error_code": str(error).split(":", 1)[0][:120],
                "production_release_allowed": False,
                "machine_write_permitted": False,
            },
        )
        return 1


def _worker_request(
    *,
    executable: Path,
    expected_executable_sha256: str,
    expected_runtime_sha256: str,
    model_pack: Path,
    expected_model_pack_sha256: str,
    expected_backbone_weights_sha256: str,
    expected_source_binding_sha256: str,
    expected_source_index_sha256: str,
    output_root: Path,
) -> tuple[Path, Path, dict]:
    runtime = _checked_file(
        executable,
        expected_executable_sha256,
        "NORMALITY_RUNTIME_EXECUTABLE_SHA_MISMATCH",
    )
    pack = _checked_file(
        model_pack,
        expected_model_pack_sha256,
        "NORMALITY_MODEL_PACK_SHA_MISMATCH",
    )
    for value, error in (
        (expected_runtime_sha256, "NORMALITY_RUNTIME_SHA_INVALID"),
        (expected_backbone_weights_sha256, "NORMALITY_BACKBONE_SHA_INVALID"),
        (expected_source_binding_sha256, "NORMALITY_SOURCE_BINDING_SHA_INVALID"),
        (expected_source_index_sha256, "NORMALITY_SOURCE_INDEX_SHA_INVALID"),
    ):
        if not _valid_sha(value):
            raise ValueError(error)
    output = Path(output_root).expanduser().resolve()
    if output == pack or pack.is_relative_to(output):
        raise ValueError("NORMALITY_OUTPUT_OVERLAPS_MODEL_PACK")
    inputs = output / "inputs"
    inputs.mkdir(parents=True, exist_ok=False)
    frozen_pack = inputs / "model_pack.pt"
    shutil.copyfile(pack, frozen_pack)
    if _sha(frozen_pack) != expected_model_pack_sha256:
        raise ValueError("NORMALITY_MODEL_PACK_SHA_MISMATCH")
    request = {
        "schema_version": "visiondata-gate.normality-worker-request.v1",
        "runtime_executable_sha256": expected_executable_sha256,
        "runtime_sha256": expected_runtime_sha256,
        "model_pack_path": str(frozen_pack),
        "model_pack_sha256": expected_model_pack_sha256,
        "backbone_weights_sha256": expected_backbone_weights_sha256,
        "source_binding_sha256": expected_source_binding_sha256,
        "source_index_sha256": expected_source_index_sha256,
        "inference_backend_sha256": _sha(Path(__file__).resolve()),
        "device": "cpu",
        "production_release_allowed": False,
        "machine_write_permitted": False,
    }
    return runtime, pack, request


def validate_normality_model_pack(
    *,
    executable: Path,
    expected_executable_sha256: str,
    expected_runtime_sha256: str,
    model_pack: Path,
    expected_model_pack_sha256: str,
    expected_backbone_weights_sha256: str,
    expected_source_binding_sha256: str,
    expected_source_index_sha256: str,
    output_root: Path,
    max_seconds: int = 120,
) -> dict:
    """Validate one exact v2 pack in the selected external runtime."""

    runtime, original_pack, request = _worker_request(
        executable=executable,
        expected_executable_sha256=expected_executable_sha256,
        expected_runtime_sha256=expected_runtime_sha256,
        model_pack=model_pack,
        expected_model_pack_sha256=expected_model_pack_sha256,
        expected_backbone_weights_sha256=expected_backbone_weights_sha256,
        expected_source_binding_sha256=expected_source_binding_sha256,
        expected_source_index_sha256=expected_source_index_sha256,
        output_root=output_root,
    )
    child = _run_worker_process(
        mode="validate",
        executable=runtime,
        request=request,
        output_root=Path(output_root) / "worker",
        max_seconds=max_seconds,
    )
    expected = {
        "status": "validated",
        "runtime_sha256": expected_runtime_sha256,
        "model_pack_sha256": expected_model_pack_sha256,
        "model_pack_schema_version": (
            "visiondata-gate.yolo26-normality-model-pack.v2"
        ),
        "backbone_weights_sha256": expected_backbone_weights_sha256,
        "source_binding_sha256": expected_source_binding_sha256,
        "source_index_sha256": expected_source_index_sha256,
        "production_release_allowed": False,
    }
    if any(child.get(key) != value for key, value in expected.items()):
        raise ValueError("NORMALITY_WORKER_IDENTITY_MISMATCH")
    if (
        child.get("machine_write_permitted") is not False
        or child.get("device") != "cpu"
        or child.get("inference_backend_sha256")
        != request["inference_backend_sha256"]
    ):
        raise ValueError("NORMALITY_WORKER_BOUNDARY_MISMATCH")
    if (
        _sha(runtime) != expected_executable_sha256
        or _sha(original_pack) != expected_model_pack_sha256
    ):
        raise ValueError("NORMALITY_INPUT_CHANGED_DURING_VALIDATION")
    return {
        "schema_version": "visiondata-gate.normality-pack-validation.v1",
        "status": "VALIDATED_FOR_LOCAL_SANDBOX",
        "model_pack_sha256": expected_model_pack_sha256,
        "model_pack_schema_version": expected["model_pack_schema_version"],
        "backbone_weights_sha256": expected_backbone_weights_sha256,
        "source_binding_sha256": expected_source_binding_sha256,
        "source_index_sha256": expected_source_index_sha256,
        "runtime_sha256": expected_runtime_sha256,
        "inference_backend_sha256": request["inference_backend_sha256"],
        "device": "cpu",
        "isolation_scope": (
            "FRESH_EXTERNAL_PROCESS_NETWORK_AND_CHILD_PROCESS_DISABLED_"
            "NOT_OS_SANDBOX"
        ),
        "machine_write_permitted": False,
        "production_release_allowed": False,
    }


def run_normality_inference(
    *,
    executable: Path,
    expected_executable_sha256: str,
    expected_runtime_sha256: str,
    model_pack: Path,
    expected_model_pack_sha256: str,
    expected_backbone_weights_sha256: str,
    expected_source_binding_sha256: str,
    expected_source_index_sha256: str,
    image: Path,
    image_format: str,
    expected_image_sha256: str,
    output_root: Path,
    max_seconds: int = 120,
) -> dict:
    """Infer one frozen local image with one exact, already-approved v2 pack."""

    runtime, original_pack, request = _worker_request(
        executable=executable,
        expected_executable_sha256=expected_executable_sha256,
        expected_runtime_sha256=expected_runtime_sha256,
        model_pack=model_pack,
        expected_model_pack_sha256=expected_model_pack_sha256,
        expected_backbone_weights_sha256=expected_backbone_weights_sha256,
        expected_source_binding_sha256=expected_source_binding_sha256,
        expected_source_index_sha256=expected_source_index_sha256,
        output_root=output_root,
    )
    source_image = _checked_file(
        image, expected_image_sha256, "NORMALITY_INPUT_IMAGE_SHA_MISMATCH"
    )
    normalized_format = image_format.lower() if isinstance(image_format, str) else ""
    if (
        normalized_format not in {"png", "jpg", "jpeg", "bmp"}
        or source_image.stat().st_size > 64 * 1024 * 1024
    ):
        raise ValueError("NORMALITY_INPUT_IMAGE_FORMAT_OR_SIZE_UNSUPPORTED")
    output = Path(output_root).expanduser().resolve()
    frozen_image = output / "inputs" / ("image." + normalized_format)
    shutil.copyfile(source_image, frozen_image)
    if _sha(frozen_image) != expected_image_sha256:
        raise ValueError("NORMALITY_INPUT_IMAGE_SHA_MISMATCH")
    heatmap = output / "artifacts" / "heatmap.png"
    request.update(
        image_path=str(frozen_image),
        image_sha256=expected_image_sha256,
        heatmap_path=str(heatmap),
    )
    child = _run_worker_process(
        mode="infer",
        executable=runtime,
        request=request,
        output_root=output / "worker",
        max_seconds=max_seconds,
    )
    if (
        child.get("inference_backend_sha256")
        != request["inference_backend_sha256"]
    ):
        raise ValueError("NORMALITY_WORKER_BOUNDARY_MISMATCH")
    expected = {
        "status": "completed",
        "runtime_sha256": expected_runtime_sha256,
        "model_pack_sha256": expected_model_pack_sha256,
        "model_pack_schema_version": (
            "visiondata-gate.yolo26-normality-model-pack.v2"
        ),
        "backbone_weights_sha256": expected_backbone_weights_sha256,
        "source_binding_sha256": expected_source_binding_sha256,
        "source_index_sha256": expected_source_index_sha256,
        "image_sha256": expected_image_sha256,
        "device": "cpu",
        "machine_write_permitted": False,
        "production_release_allowed": False,
    }
    if any(child.get(key) != value for key, value in expected.items()):
        raise ValueError("NORMALITY_INFERENCE_IDENTITY_MISMATCH")
    numeric = (
        "image_score",
        "image_threshold",
        "pixel_threshold",
        "positive_pixel_fraction",
    )
    if any(
        type(child.get(key)) not in {int, float}
        or not math.isfinite(float(child[key]))
        for key in numeric
    ) or type(child.get("predicted_anomaly")) is not bool:
        raise ValueError("NORMALITY_INFERENCE_RESULT_INVALID")
    if (
        float(child["image_score"]) < 0.0
        or float(child["image_threshold"]) < 0.0
        or float(child["pixel_threshold"]) < 0.0
        or not 0.0 <= float(child["positive_pixel_fraction"]) <= 1.0
    ):
        raise ValueError("NORMALITY_INFERENCE_RESULT_INVALID")
    if child["predicted_anomaly"] is not (
        float(child["image_score"]) >= float(child["image_threshold"])
    ):
        raise ValueError("NORMALITY_INFERENCE_PREDICTION_MISMATCH")
    if not heatmap.is_file() or _sha(heatmap) != child.get("heatmap_sha256"):
        raise ValueError("NORMALITY_HEATMAP_SHA_MISMATCH")
    if (
        child.get("heatmap_bytes") != heatmap.stat().st_size
        or child.get("heatmap_width") != 64
        or child.get("heatmap_height") != 64
        or not 0.0 <= float(child["positive_pixel_fraction"]) <= 1.0
    ):
        raise ValueError("NORMALITY_HEATMAP_CONTRACT_INVALID")
    if (
        _sha(runtime) != expected_executable_sha256
        or _sha(original_pack) != expected_model_pack_sha256
        or _sha(source_image) != expected_image_sha256
    ):
        raise ValueError("NORMALITY_INPUT_CHANGED_DURING_INFERENCE")
    return {
        "schema_version": "visiondata-gate.normality-inference-result.v1",
        "status": "COMPLETED_LOCAL_SANDBOX_INFERENCE",
        "model_pack_sha256": expected_model_pack_sha256,
        "model_pack_schema_version": expected["model_pack_schema_version"],
        "backbone_weights_sha256": expected_backbone_weights_sha256,
        "source_binding_sha256": expected_source_binding_sha256,
        "source_index_sha256": expected_source_index_sha256,
        "runtime_sha256": expected_runtime_sha256,
        "inference_backend_sha256": request["inference_backend_sha256"],
        "image_sha256": expected_image_sha256,
        "image_score": float(child["image_score"]),
        "image_threshold": float(child["image_threshold"]),
        "pixel_threshold": float(child["pixel_threshold"]),
        "predicted_anomaly": child["predicted_anomaly"],
        "positive_pixel_fraction": float(child["positive_pixel_fraction"]),
        "heatmap": {
            "sha256": child["heatmap_sha256"],
            "bytes": child["heatmap_bytes"],
            "width": 64,
            "height": 64,
            "format": "png",
        },
        "device": "cpu",
        "decision_scope": "MODEL_SIGNAL_ONLY_NOT_GATE_OR_PRODUCTION_DECISION",
        "machine_write_permitted": False,
        "production_release_allowed": False,
    }


if __name__ == "__main__":
    raise SystemExit(_worker_main(sys.argv[1:]))
