"""Optional, bounded CPU YOLO detection in an explicitly selected interpreter.

No torch/Ultralytics import occurs in the application process. The caller must
authorize execution of the named runtime and, when supplied, trust and authorize
deserialization of the exact checkpoint SHA. A SHA proves identity, not safety.
Registration alone must never call training. Ultralytics licensing remains
AGPL-3.0/Enterprise; process separation is not a licensing exemption.

The child disables Python sockets, subprocesses and integrations. This is a
defence against accidental network use, not an OS sandbox for malicious native
code or pickle. Only trusted runtimes/checkpoints belong in this backend.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import asdict, dataclass
import hashlib
import importlib.metadata
import json
import math
import os
from pathlib import Path
import shutil
import subprocess
import sys
import sysconfig
import tempfile
import time


_PACKAGES = ("torch", "torchvision", "ultralytics", "numpy", "Pillow", "PyYAML")
_IMAGE_SUFFIXES = {".png", ".jpg", ".jpeg", ".bmp"}
_BOUNDARIES = {
    "device": "cpu",
    "gpu_status": "GPU_NOT_RUN",
    "industrial_status": "industrial_NOT_EVALUATED",
    "production_approved": False,
    "model_selection": "HUMAN_REVIEW_REQUIRED",
    "test_evaluation": "NOT_RUN",
    "adaptation": "DISABLED_NOT_TTT",
    "license": "Ultralytics AGPL-3.0 or Enterprise; review required",
}


def _sha(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _digest(value: object) -> str:
    return hashlib.sha256(
        json.dumps(value, sort_keys=True, separators=(",", ":"),
                   ensure_ascii=True, allow_nan=False).encode("utf-8")
    ).hexdigest()


def _valid_sha(value: str) -> bool:
    return (isinstance(value, str) and len(value) == 64
            and all(c in "0123456789abcdef" for c in value))


def _checked_executable(executable: Path, expected: str) -> Path:
    path = Path(executable).resolve(strict=True)
    if not path.is_file() or not _valid_sha(expected) or _sha(path) != expected:
        raise ValueError("RUNTIME_EXECUTABLE_SHA_MISMATCH")
    return path


@dataclass(frozen=True)
class YoloTrainingConfig:
    """Small supervised bounding-box detection budget; not segmentation or VLM."""

    epochs: int = 1
    imgsz: int = 64
    batch: int = 2
    seed: int = 0
    max_seconds: int = 120
    threads: int = 2

    def __post_init__(self) -> None:
        limits = {"epochs": (1, 5), "imgsz": (64, 320), "batch": (2, 8),
                  "seed": (0, 2**31 - 1), "max_seconds": (10, 600),
                  "threads": (1, 4)}
        for name, (low, high) in limits.items():
            value = getattr(self, name)
            if type(value) is not int or not low <= value <= high:
                raise ValueError("YOLO_CONFIG_INVALID_" + name.upper())
        if self.imgsz % 32:
            raise ValueError("YOLO_CONFIG_IMAGE_SIZE_MULTIPLE_32")


def _child_environment(work_root: Path, threads: int = 2) -> dict[str, str]:
    """Allowlist only OS boot variables; never forward application credentials."""
    isolated = work_root.resolve()
    isolated.mkdir(parents=True, exist_ok=True)
    env = {key: os.environ[key] for key in ("SYSTEMROOT", "WINDIR")
           if key in os.environ}
    env.update({
        "HOME": str(isolated), "USERPROFILE": str(isolated),
        "APPDATA": str(isolated), "LOCALAPPDATA": str(isolated),
        "TEMP": str(isolated), "TMP": str(isolated),
        "YOLO_CONFIG_DIR": str(isolated / "yolo"),
        "MPLCONFIGDIR": str(isolated / "matplotlib"),
        "TORCH_HOME": str(isolated / "torch"),
        "XDG_CACHE_HOME": str(isolated / "cache"),
        "CUDA_VISIBLE_DEVICES": "", "WANDB_MODE": "disabled",
        "WANDB_DISABLED": "true", "COMET_MODE": "DISABLED",
        "HF_HUB_OFFLINE": "1", "TRANSFORMERS_OFFLINE": "1",
        "YOLO_OFFLINE": "true", "YOLO_AUTOINSTALL": "false",
        "YOLO_VERBOSE": "false", "MPLBACKEND": "Agg",
        "PYTHONDONTWRITEBYTECODE": "1",
        "OMP_NUM_THREADS": str(threads), "MKL_NUM_THREADS": str(threads),
        "OPENBLAS_NUM_THREADS": str(threads), "NUMEXPR_NUM_THREADS": str(threads),
    })
    return env


def _command(executable: Path, mode: str, request: Path, result: Path) -> list[str]:
    # -S avoids execution of arbitrary site .pth files; add package paths in child.
    # -B keeps reviewed source directories immutable across install/uninstall.
    return [str(executable), "-B", "-I", "-S", str(Path(__file__).resolve()),
            mode, str(request), str(result)]


def _json_write(path: Path, value: object) -> None:
    path.write_text(json.dumps(value, sort_keys=True, indent=2,
                               allow_nan=False), encoding="utf-8")


def probe_vision_runtime(
    executable: Path, expected_executable_sha256: str, work_root: Path,
    *, import_check: bool = False,
) -> dict:
    """Hash and probe an explicitly authorized runtime, without loading weights.

    Metadata-only by default. The stable fingerprint hashes installed package
    metadata/RECORD files and actual Ultralytics Python/YAML source bytes. It is
    not a full hash of every native dependency or a security attestation.
    """
    return _probe_runtime(executable, expected_executable_sha256, work_root,
                          import_check=import_check, timeout=90 if import_check else 20)


def _probe_runtime(
    executable: Path, expected_executable_sha256: str, work_root: Path,
    *, import_check: bool, timeout: float,
    cancelled: Callable[[], bool] | None = None,
) -> dict:
    if type(import_check) is not bool:
        raise ValueError("RUNTIME_IMPORT_CHECK_BOOLEAN_REQUIRED")
    executable = _checked_executable(executable, expected_executable_sha256)
    root = Path(work_root).resolve()
    root.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="vision-probe-", dir=root) as temp:
        folder = Path(temp)
        request, result = folder / "request.json", folder / "result.json"
        _json_write(request, {"executable_sha256": expected_executable_sha256,
                              "import_check": import_check})
        started = time.monotonic()
        finished = subprocess.Popen(
            _command(executable, "probe", request, result),
            env=_child_environment(folder / "environment"), cwd=folder,
            stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
        try:
            while finished.poll() is None:
                if cancelled is not None and cancelled():
                    return {"status": "unavailable", "error_code": "RUNTIME_PROBE_CANCELLED"}
                if time.monotonic() - started >= timeout:
                    return {"status": "unavailable", "error_code": "RUNTIME_PROBE_TIMEOUT"}
                time.sleep(0.1)
        finally:
            if finished.poll() is None:
                finished.kill()
                finished.wait(timeout=5)
        if finished.returncode != 0 or not result.is_file():
            return {"status": "unavailable", "error_code": "RUNTIME_PROBE_FAILED"}
        return json.loads(result.read_text(encoding="utf-8"))


def _inside(root: Path, path: Path) -> Path:
    resolved = path.resolve(strict=True)
    if not resolved.is_relative_to(root) or path.is_symlink():
        raise ValueError("YOLO_DATASET_PATH_ESCAPE")
    return resolved


def _dataset_receipt(dataset_root: Path) -> dict:
    import yaml
    from PIL import Image

    root = dataset_root.resolve(strict=True)
    data_file = _inside(root, root / "data.yaml")
    if data_file.stat().st_size > 64_000:
        raise ValueError("YOLO_DATASET_CONFIG_LIMIT")
    data = yaml.safe_load(data_file.read_text(encoding="utf-8"))
    if not isinstance(data, dict) or set(data) - {"path", "train", "val", "test", "names", "nc"}:
        raise ValueError("YOLO_DATASET_CONFIG_UNSUPPORTED")
    if data.get("path") not in (None, ".", str(root), root.as_posix()):
        raise ValueError("YOLO_DATASET_ROOT_MISMATCH")
    names = data.get("names")
    if isinstance(names, dict) and all(type(k) is int for k in names):
        if set(names) != set(range(len(names))):
            raise ValueError("YOLO_CLASS_MAPPING_INVALID")
        names = [names[i] for i in range(len(names))]
    if (not isinstance(names, list) or not 1 <= len(names) <= 64
            or any(not isinstance(n, str) or not n.strip() or len(n) > 96 for n in names)
            or len(set(names)) != len(names)):
        raise ValueError("YOLO_CLASS_MAPPING_INVALID")
    if "nc" in data and (type(data["nc"]) is not int or data["nc"] != len(names)):
        raise ValueError("YOLO_CLASS_MAPPING_INVALID")
    files, seen, counts = [], {}, {}
    seen_pixels: dict[str, str] = {}
    total_bytes = 0
    for split in ("train", "val", "test"):
        if split == "test" and split not in data:
            continue
        if data.get(split) != "images/" + split:
            raise ValueError("YOLO_STANDARD_SPLIT_LAYOUT_REQUIRED")
        directory = _inside(root, root / "images" / split)
        samples = sorted(directory.iterdir())
        if not 1 <= len(samples) <= 64:
            raise ValueError("YOLO_SPLIT_SAMPLE_LIMIT")
        counts[split] = len(samples)
        stems: set[str] = set()
        for image in samples:
            if not image.is_file() or image.suffix.lower() not in _IMAGE_SUFFIXES:
                raise ValueError("YOLO_IMAGE_FORMAT_UNSUPPORTED")
            image = _inside(root, image)
            if image.stem.casefold() in stems:
                raise ValueError("YOLO_AMBIGUOUS_LABEL")
            stems.add(image.stem.casefold())
            label = _inside(root, root / "labels" / split / (image.stem + ".txt"))
            if image.stat().st_size > 16_000_000 or label.stat().st_size > 64_000:
                raise ValueError("YOLO_SAMPLE_BYTE_LIMIT")
            total_bytes += image.stat().st_size + label.stat().st_size
            if total_bytes > 128_000_000:
                raise ValueError("YOLO_DATASET_BYTE_LIMIT")
            image_sha = _sha(image)
            if image_sha in seen:
                raise ValueError(
                    "YOLO_IMAGE_WITHIN_SPLIT_DUPLICATE"
                    if seen[image_sha] == split
                    else "YOLO_DUPLICATE_IMAGE_OR_SPLIT_LEAKAGE"
                )
            seen[image_sha] = split
            # Test bytes are hashed for split isolation; never supplied to the model.
            with Image.open(image) as decoded:
                if not 1 <= decoded.width <= 2048 or not 1 <= decoded.height <= 2048:
                    raise ValueError("YOLO_IMAGE_DIMENSION_LIMIT")
                decoded.verify()
            with Image.open(image) as decoded:
                rgb = decoded.convert("RGB")
                pixel_sha = hashlib.sha256(
                    rgb.width.to_bytes(4, "big")
                    + rgb.height.to_bytes(4, "big")
                    + rgb.tobytes()
                ).hexdigest()
            if pixel_sha in seen_pixels:
                raise ValueError(
                    "YOLO_PIXEL_WITHIN_SPLIT_DUPLICATE"
                    if seen_pixels[pixel_sha] == split
                    else "YOLO_DUPLICATE_PIXELS_OR_SPLIT_LEAKAGE"
                )
            seen_pixels[pixel_sha] = split
            label_text = label.read_text(encoding="utf-8")
            for line in label_text.splitlines():
                tokens = line.split()
                if len(tokens) != 5:
                    raise ValueError("YOLO_DETECTION_BOX_REQUIRED")
                try:
                    cls = int(tokens[0])
                    x, y, width, height = map(float, tokens[1:])
                except ValueError as error:
                    raise ValueError("YOLO_DETECTION_BOX_INVALID") from error
                if (str(cls) != tokens[0] or not 0 <= cls < len(names)
                        or not all(math.isfinite(v) for v in (x, y, width, height))
                        or not 0 < width <= 1 or not 0 < height <= 1
                        or x - width / 2 < -1e-6 or x + width / 2 > 1 + 1e-6
                        or y - height / 2 < -1e-6 or y + height / 2 > 1 + 1e-6):
                    raise ValueError("YOLO_DETECTION_BOX_INVALID")
            files.extend([
                {"path": image.relative_to(root).as_posix(), "sha256": image_sha,
                 "split": split},
                {"path": label.relative_to(root).as_posix(), "sha256": _sha(label),
                 "split": split},
            ])
    body = {"names": names, "counts": counts, "files": files,
            "config_sha256": _sha(data_file)}
    return {**body, "sha256": _digest(body)}


def run_yolo_training(
    *, executable: Path, expected_executable_sha256: str,
    expected_runtime_sha256: str, dataset_root: Path, output_root: Path,
    config: YoloTrainingConfig, initial_weights: Path | None = None,
    expected_weights_sha256: str | None = None,
    cancelled: Callable[[], bool] | None = None,
) -> dict:
    """Run supervised detection with an authorized runtime/checkpoint.

    Caller must bind authorization to runtime SHA, dataset version, exact weights
    SHA and license acceptance before calling. This low-level function does not
    create that authorization. Output must be a fresh per-job directory. Caller
    owns idempotency and durable job lookup. Input/contract errors raise safe
    ValueError codes; executed jobs return completed/failed/cancelled/timed_out.
    """
    if not isinstance(config, YoloTrainingConfig):
        raise ValueError("YOLO_CONFIG_REQUIRED")
    config = YoloTrainingConfig(**asdict(config))
    if cancelled is not None and not callable(cancelled):
        raise ValueError("YOLO_CANCEL_CALLBACK_INVALID")
    started = time.monotonic()
    executable = _checked_executable(executable, expected_executable_sha256)
    if not _valid_sha(expected_runtime_sha256):
        raise ValueError("RUNTIME_FINGERPRINT_REQUIRED")
    if (initial_weights is None) != (expected_weights_sha256 is None):
        raise ValueError("YOLO_WEIGHTS_SHA_REQUIRED")
    if initial_weights is not None:
        initial_weights = Path(initial_weights).resolve(strict=True)
        if (initial_weights.suffix.lower() != ".pt"
                or not _valid_sha(expected_weights_sha256)
                or initial_weights.stat().st_size > 512_000_000
                or _sha(initial_weights) != expected_weights_sha256):
            raise ValueError("YOLO_WEIGHTS_SHA_MISMATCH")
    source = Path(dataset_root).resolve(strict=True)
    output = Path(output_root).resolve()
    if output == source or output.is_relative_to(source) or source.is_relative_to(output):
        raise ValueError("YOLO_OUTPUT_OVERLAPS_DATASET")
    output.mkdir(parents=True, exist_ok=True)
    if any(output.iterdir()):
        raise ValueError("YOLO_FRESH_OUTPUT_REQUIRED")
    _json_write(output / "started.json", {"config": asdict(config), **_BOUNDARIES})

    def interrupted() -> str | None:
        if cancelled is not None and cancelled():
            return "cancelled"
        return "timed_out" if time.monotonic() - started >= config.max_seconds else None

    def finish(status: str, **details: object) -> dict:
        result = {"status": status, **_BOUNDARIES, "config": asdict(config),
                  "runtime_sha256": expected_runtime_sha256,
                  "elapsed_seconds": round(time.monotonic() - started, 4), **details}
        _json_write(output / "result.json", result)
        _json_write(
            output / "retention.json",
            {
                "schema_version": "visiondata-gate.yolo-job-retention.v1",
                "status": status,
                "automatic_deletion_permitted": False,
                "cleanup_requires_reference_review": True,
                "preserve": [
                    "started.json",
                    "result.json",
                    "dataset_receipt.json",
                    "request.json",
                    "child_result.json",
                    "worker.log",
                ],
                "reviewable_working_copies": [
                    "dataset",
                    "initial.pt",
                    "environment",
                    "probe",
                ],
                "checkpoints": (
                    "PRESERVE_UNTIL_MODEL_AND_FEEDBACK_REFERENCES_REVIEWED"
                ),
                "scope": "THIS_JOB_ONLY_NOT_SOURCE_DATA_OR_REGISTRY",
            },
        )
        return result

    if status := interrupted():
        return finish(status)
    receipt = _dataset_receipt(source)
    # This preflight is not a quota: another process can consume disk later.
    # Evidence is retained and failed jobs are never deleted automatically.
    copy_bytes = sum(
        (source / item["path"]).stat().st_size
        for item in receipt["files"]
        if item["split"] != "test"
    )
    weights_bytes = initial_weights.stat().st_size if initial_weights else 0
    required_free = copy_bytes + weights_bytes + 576 * 1024 * 1024
    if shutil.disk_usage(output).free < required_free:
        return finish("failed", error_code="YOLO_OUTPUT_SPACE_INSUFFICIENT")
    runtime = _probe_runtime(executable, expected_executable_sha256,
                             output / "probe", import_check=False,
                             timeout=max(0.1, config.max_seconds - (time.monotonic() - started)),
                             cancelled=cancelled)
    if status := interrupted():
        return finish(status)
    if runtime.get("status") != "ready" or runtime.get("runtime_sha256") != expected_runtime_sha256:
        raise ValueError("RUNTIME_FINGERPRINT_MISMATCH")
    frozen = output / "dataset"
    frozen.mkdir()
    for item in receipt["files"]:
        if status := interrupted():
            return finish(status)
        if item["split"] == "test":
            continue
        original = _inside(source, source / item["path"])
        destination = frozen / item["path"]
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(original, destination)
        if _sha(destination) != item["sha256"] or _sha(original) != item["sha256"]:
            raise ValueError("YOLO_DATASET_CHANGED")
    # JSON is a YAML subset. Never forward user-controlled YAML directives.
    _json_write(frozen / "data.yaml", {"path": str(frozen), "train": "images/train",
                                      "val": "images/val", "names": receipt["names"]})
    if _dataset_receipt(source) != receipt:
        raise ValueError("YOLO_DATASET_CHANGED")
    if initial_weights is not None:
        copied = output / "initial.pt"
        shutil.copyfile(initial_weights, copied)
        if _sha(copied) != expected_weights_sha256:
            raise ValueError("YOLO_WEIGHTS_SHA_MISMATCH")
        initial_weights = copied
    _json_write(output / "dataset_receipt.json", receipt)
    request, child_result = output / "request.json", output / "child_result.json"
    payload = {"executable_sha256": expected_executable_sha256,
               "runtime_sha256": expected_runtime_sha256,
               "source_dataset_sha256": receipt["sha256"],
               "config": asdict(config), "dataset": str(frozen), "output": str(output),
               "initial_weights": str(initial_weights) if initial_weights else None,
               "weights_sha256": expected_weights_sha256,
               "dataset_receipt": _dataset_receipt(frozen)}
    _json_write(request, payload)
    if status := interrupted():
        return finish(status)
    # Recheck bytes immediately before process creation and again inside child.
    _checked_executable(executable, expected_executable_sha256)
    with (output / "worker.log").open("wb") as log:
        process = subprocess.Popen(
            _command(executable, "train", request, child_result),
            env=_child_environment(output / "environment", config.threads), cwd=output,
            stdin=subprocess.DEVNULL, stdout=log, stderr=log,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
        try:
            while process.poll() is None:
                if status := interrupted():
                    process.terminate()
                    try:
                        process.wait(timeout=5)
                    except subprocess.TimeoutExpired:
                        process.kill()
                        process.wait(timeout=5)
                    return finish(status)
                time.sleep(0.1)
        finally:
            if process.poll() is None:
                process.kill()
                process.wait(timeout=5)
    if status := interrupted():
        return finish(status)
    if process.returncode or not child_result.is_file():
        return finish("failed", error_code="YOLO_CHILD_FAILED")
    child = json.loads(child_result.read_text(encoding="utf-8"))
    if child.get("status") != "completed":
        return finish("failed", error_code=child.get("error_code", "YOLO_CHILD_FAILED"))
    checkpoint = _inside(output, output / child["checkpoint"]["relative_path"])
    if _sha(checkpoint) != child["checkpoint"]["sha256"]:
        return finish("failed", error_code="YOLO_CHECKPOINT_CHANGED")
    if _dataset_receipt(source) != receipt:
        return finish("failed", error_code="YOLO_DATASET_CHANGED")
    return finish("completed", **{k: v for k, v in child.items() if k != "status"},
                  dataset_sha256=receipt["sha256"],
                  validation_samples=receipt["counts"]["val"],
                  training_samples=receipt["counts"]["train"])


def _deny_network_and_children() -> None:
    import socket

    def denied(*_args: object, **_kwargs: object) -> None:
        raise OSError("VISION_NETWORK_DISABLED")

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
                     "subprocess.Popen", "os.system", "os.exec", "os.posix_spawn"}:
            raise OSError("VISION_NETWORK_OR_CHILD_PROCESS_DISABLED")

    sys.addaudithook(audit)


def _package_paths() -> None:
    for key in ("purelib", "platlib"):
        location = sysconfig.get_path(key)
        if location not in sys.path:
            sys.path.append(location)


def _runtime_metadata(expected_sha: str) -> dict:
    _checked_executable(Path(sys.executable), expected_sha)
    versions, records = {}, {}
    for name in _PACKAGES:
        try:
            distribution = importlib.metadata.distribution(name)
            versions[name] = distribution.version
            records[name] = _digest({
                "metadata": distribution.read_text("METADATA"),
                "record": distribution.read_text("RECORD"),
            })
        except importlib.metadata.PackageNotFoundError:
            versions[name] = None
            records[name] = None
    sources = {}
    if versions["ultralytics"]:
        dist = importlib.metadata.distribution("ultralytics")
        package = Path(dist.locate_file("ultralytics")).resolve()
        for entry in sorted(package.rglob("*")):
            if entry.is_file() and entry.suffix in {".py", ".yaml"}:
                sources[entry.relative_to(package).as_posix()] = _sha(entry)
    receipt = {"schema": "vision-runtime.v1", "executable_sha256": expected_sha,
               "python_version": list(sys.version_info[:3]), "packages": versions,
               "package_metadata_sha256": records,
               "ultralytics_source_sha256": _digest(sources),
               "yolo26_config_sha256": sources.get("cfg/models/26/yolo26.yaml"),
               "backend_source_sha256": _sha(Path(__file__))}
    ready = all(versions.values()) and receipt["yolo26_config_sha256"] is not None
    return {**receipt, "runtime_sha256": _digest(receipt),
            "status": "ready" if ready else "unavailable", "import_status": "NOT_RUN",
            "fingerprint_scope": "executable, metadata/RECORD, actual Ultralytics Python/YAML and backend source; not every native dependency"}


def _import_backend() -> tuple:
    import torch
    import torchvision
    import ultralytics
    from ultralytics.utils import SETTINGS, callbacks
    from ultralytics.utils import checks

    SETTINGS.update({key: False for key, value in SETTINGS.items()
                     if isinstance(value, bool)})
    callbacks.add_integration_callbacks = lambda _instance: None
    checks.check_pip_update_available = lambda: None
    checks.check_font = lambda *_args, **_kwargs: None
    # data.utils binds check_font by name; suppress that alias too.
    import ultralytics.data.utils
    ultralytics.data.utils.check_font = checks.check_font
    torch.set_num_threads(int(os.environ["OMP_NUM_THREADS"]))
    return torch, torchvision, ultralytics


def _metrics(result: object) -> dict:
    metrics = {}
    for key, value in result.results_dict.items():
        numeric = float(value)
        if not math.isfinite(numeric):
            raise ValueError("YOLO_NONFINITE_METRICS")
        metrics[str(key)] = numeric
    return metrics


def _parameter_sha(model: object) -> str:
    digest = hashlib.sha256()
    for name, value in sorted(model.named_parameters()):
        tensor = value.detach().cpu().float().contiguous()
        digest.update(name.encode("utf-8"))
        digest.update(str(tuple(tensor.shape)).encode("ascii"))
        digest.update(tensor.numpy().tobytes())
    return digest.hexdigest()


def _validate_initial_definition(actual: dict, expected: dict) -> None:
    keys = ("backbone", "head", "scales", "scale", "end2end", "reg_max")
    if any(key not in actual or actual[key] != expected[key] for key in keys):
        raise ValueError("YOLO_INITIAL_ARCHITECTURE_MISMATCH")


def _feedback_box(value: dict, *, prediction: bool) -> dict:
    if not isinstance(value, dict) or type(value.get("class_id")) is not int:
        raise ValueError("YOLO_FEEDBACK_BOX_INVALID")
    coordinates = value.get("xyxy")
    if (value["class_id"] < 0 or not isinstance(coordinates, (list, tuple))
            or len(coordinates) != 4
            or any(type(v) not in (float, int) or not math.isfinite(v)
                   or not 0 <= v <= 1 for v in coordinates)
            or coordinates[0] >= coordinates[2] or coordinates[1] >= coordinates[3]):
        raise ValueError("YOLO_FEEDBACK_BOX_INVALID")
    result = {"class_id": value["class_id"], "xyxy": [float(v) for v in coordinates]}
    if prediction:
        confidence = value.get("confidence")
        if (type(confidence) not in (float, int) or not math.isfinite(confidence)
                or not 0 <= confidence <= 1):
            raise ValueError("YOLO_FEEDBACK_CONFIDENCE_INVALID")
        result["confidence"] = float(confidence)
    return result


def _box_iou(first: list[float], second: list[float]) -> float:
    width = max(0.0, min(first[2], second[2]) - max(first[0], second[0]))
    height = max(0.0, min(first[3], second[3]) - max(first[1], second[1]))
    intersection = width * height
    first_area = (first[2] - first[0]) * (first[3] - first[1])
    second_area = (second[2] - second[0]) * (second[3] - second[1])
    return intersection / (first_area + second_area - intersection)


def _match_validation_boxes(predictions: list[dict], ground_truth: list[dict]) -> dict:
    """Fixed operating point, deterministic class-aware global greedy IoU.

    Predictions are sorted by confidence descending, class and coordinates
    ascending. Candidate pairs are sorted by IoU descending, then prediction and
    reference index ascending. Each prediction/reference can match at most once.
    Counts describe disagreement with reference labels, not label correctness.
    """
    if not isinstance(predictions, list) or not isinstance(ground_truth, list):
        raise ValueError("YOLO_FEEDBACK_BOX_LIST_REQUIRED")
    if len(predictions) > 300 or len(ground_truth) > 256:
        raise ValueError("YOLO_FEEDBACK_BOX_LIMIT")
    checked_predictions = [_feedback_box(value, prediction=True) for value in predictions]
    predicted = sorted(
        (value for value in checked_predictions if value["confidence"] >= 0.25),
        key=lambda value: (-value["confidence"], value["class_id"], *value["xyxy"]),
    )
    expected = [_feedback_box(value, prediction=False) for value in ground_truth]
    pairs = []
    for prediction_index, prediction in enumerate(predicted):
        for reference_index, reference in enumerate(expected):
            if prediction["class_id"] != reference["class_id"]:
                continue
            iou = _box_iou(prediction["xyxy"], reference["xyxy"])
            if iou >= 0.5:
                pairs.append((-iou, prediction_index, reference_index))
    matched_predictions, matched_references, matches = set(), set(), []
    for negative_iou, prediction_index, reference_index in sorted(pairs):
        if prediction_index in matched_predictions or reference_index in matched_references:
            continue
        matched_predictions.add(prediction_index)
        matched_references.add(reference_index)
        matches.append({"prediction_index": prediction_index,
                        "ground_truth_index": reference_index, "iou": -negative_iou})
    true_positive = len(matches)
    false_positive, false_negative = len(predicted) - true_positive, len(expected) - true_positive
    reasons = []
    if false_positive:
        reasons.append("FALSE_POSITIVE_CANDIDATE")
    if false_negative:
        reasons.append("FALSE_NEGATIVE_CANDIDATE")
    return {"prediction_boxes": predicted, "ground_truth_boxes": expected,
            "tp": true_positive, "fp": false_positive, "fn": false_negative,
            "matched_ious": [match["iou"] for match in matches], "matches": matches,
            "reason_codes": reasons, "review_required": True}


def _validation_feedback(model: object, request: dict, config: YoloTrainingConfig,
                         checkpoint_sha256: str) -> dict:
    """Actually predict every val member; parent owns the same wall/cancel budget."""
    dataset = Path(request["dataset"])
    receipt = request["dataset_receipt"]
    files = {item["path"]: item for item in receipt["files"]}
    val_images = sorted((item for item in receipt["files"]
                         if item["split"] == "val" and item["path"].startswith("images/val/")),
                        key=lambda item: Path(item["path"]).stem)
    if len(val_images) != receipt["counts"]["val"]:
        raise ValueError("YOLO_FEEDBACK_SAMPLE_COUNT_MISMATCH")
    details = []
    for entry in val_images:
        image = _inside(dataset, dataset / entry["path"])
        label_entry = files["labels/val/" + image.stem + ".txt"]
        label = _inside(dataset, dataset / label_entry["path"])
        if _sha(image) != entry["sha256"] or _sha(label) != label_entry["sha256"]:
            raise ValueError("YOLO_DATASET_CHANGED")
        ground_truth = []
        for line in label.read_text(encoding="utf-8").splitlines():
            values = line.split()
            class_id = int(values[0])
            x, y, width, height = map(float, values[1:])
            ground_truth.append({"class_id": class_id,
                                 "xyxy": [max(0.0, x - width / 2), max(0.0, y - height / 2),
                                          min(1.0, x + width / 2), min(1.0, y + height / 2)]})
        predictions = model.predict(
            source=str(image), device="cpu", imgsz=config.imgsz, batch=1,
            conf=0.25, iou=0.5, max_det=300, agnostic_nms=False,
            augment=False, half=False, stream=False, verbose=False,
            save=False, save_txt=False, save_conf=False, save_crop=False,
        )
        if len(predictions) != 1 or predictions[0].boxes is None:
            raise ValueError("YOLO_FEEDBACK_PREDICTION_MISSING")
        boxes = predictions[0].boxes
        coordinates = boxes.xyxyn.cpu().tolist()
        confidences = boxes.conf.cpu().tolist()
        classes = boxes.cls.cpu().tolist()
        if len(coordinates) != len(confidences) or len(classes) != len(coordinates):
            raise ValueError("YOLO_FEEDBACK_PREDICTION_SHAPE")
        parsed = []
        for xyxy, confidence, class_id in zip(coordinates, confidences, classes, strict=True):
            if (not math.isfinite(class_id) or class_id != int(class_id)
                    or not 0 <= int(class_id) < len(receipt["names"])):
                raise ValueError("YOLO_FEEDBACK_PREDICTION_CLASS")
            parsed.append({"class_id": int(class_id), "xyxy": xyxy, "confidence": confidence})
        details.append({"sample_id": image.stem, "image_sha256": entry["sha256"],
                        "label_sha256": label_entry["sha256"],
                        **_match_validation_boxes(parsed, ground_truth)})
        if _sha(image) != entry["sha256"] or _sha(label) != label_entry["sha256"]:
            raise ValueError("YOLO_DATASET_CHANGED")
    protocol = {
        "schema_version": "visiondata-gate.validation-feedback.v1", "split": "val",
        "confidence_threshold": 0.25, "iou_threshold": 0.5, "max_detections": 300,
        "matching": "class_aware_greedy_iou_descending",
        "prediction_order": "confidence_descending_then_class_and_coordinates",
        "tie_break": "prediction_index_then_ground_truth_index",
        "dataset_sha256": request["source_dataset_sha256"],
        "checkpoint_sha256": checkpoint_sha256, "runtime_sha256": request["runtime_sha256"],
        "sample_count": len(details), "review_required": True,
        "label_truth_status": "REFERENCE_LABELS_NOT_ADJUDICATED",
        "interpretation": "Fixed operating-point disagreements, not aggregate mAP or adjudicated label errors",
    }
    keys = ("sample_id", "image_sha256", "label_sha256", "tp", "fp", "fn",
            "reason_codes", "review_required")
    return {"validation_feedback_protocol": protocol,
            "validation_samples_detail": details,
            "validation_feedback_candidates": [
                {key: row[key] for key in keys} for row in details if row["fp"] or row["fn"]
            ]}


def _training_options(
    config: YoloTrainingConfig,
    *,
    dataset: Path,
    output: Path,
    device: str = "cpu",
) -> dict:
    """Resolve the complete small-budget trainer contract.

    Ultralytics otherwise applies at least 100 warmup iterations whenever
    ``warmup_epochs`` is positive.  That can consume every batch in the bounded
    1--5 epoch smoke and leave a final accumulated gradient unapplied.  A zero
    warmup plus ``nbs == batch`` makes every observed batch an optimizer step.
    """

    if device != "cpu":
        raise ValueError("YOLO_CONFIG_DEVICE_NOT_AUTHORIZED")
    return {
        "data": str(dataset / "data.yaml"),
        "device": device,
        "epochs": config.epochs,
        "imgsz": config.imgsz,
        "batch": config.batch,
        "workers": 0,
        "amp": False,
        "seed": config.seed,
        "deterministic": True,
        "pretrained": False,
        "plots": False,
        "save": True,
        "val": True,
        "cache": False,
        "project": str(output),
        "name": "training",
        "exist_ok": False,
        "optimizer": "SGD",
        "lr0": 0.001,
        "momentum": 0.9,
        "warmup_epochs": 0.0,
        "nbs": config.batch,
        "mosaic": 0.0,
        "mixup": 0.0,
        "copy_paste": 0.0,
        "auto_augment": None,
        "close_mosaic": 0,
        "patience": 0,
        "resume": False,
        "verbose": False,
    }


def _child_train(request: dict) -> dict:
    import csv
    import copy

    runtime = _runtime_metadata(request["executable_sha256"])
    if runtime["runtime_sha256"] != request["runtime_sha256"]:
        raise ValueError("RUNTIME_FINGERPRINT_MISMATCH")
    config = YoloTrainingConfig(**request["config"])
    dataset, output = Path(request["dataset"]), Path(request["output"])
    if _dataset_receipt(dataset) != request["dataset_receipt"]:
        raise ValueError("YOLO_DATASET_CHANGED")
    torch, _torchvision, ultralytics = _import_backend()
    from ultralytics import YOLO
    from ultralytics.utils import YAML

    torch.manual_seed(config.seed)
    model_config = Path(ultralytics.__file__).parent / "cfg/models/26/yolo26.yaml"
    model_definition = YAML.load(model_config)
    model_definition["scale"] = "n"
    model_definition["nc"] = len(request["dataset_receipt"]["names"])
    local_config = output / "yolo26n.yaml"
    YAML.save(local_config, model_definition)
    initial = request["initial_weights"]
    if initial:
        weights = Path(initial)
        if _sha(weights) != request["weights_sha256"]:
            raise ValueError("YOLO_WEIGHTS_SHA_MISMATCH")
        model = YOLO(str(weights), task="detect")
        if (model.task != "detect"
                or list(model.names.values()) != request["dataset_receipt"]["names"]):
            raise ValueError("YOLO_INITIAL_MODEL_TASK_OR_CLASSES_MISMATCH")
        _validate_initial_definition(model.model.yaml, model_definition)
    else:
        model = YOLO(str(local_config), task="detect")
        model.model.names = dict(enumerate(request["dataset_receipt"]["names"]))
        # Ultralytics otherwise reconstructs a different random model in train().
        # Pin a locally generated checkpoint so baseline and training start from
        # the same actual parameters, including the serialization conversion.
        pinned_initial = output / "random_initial.pt"
        model.save(str(pinned_initial))
        model = YOLO(str(pinned_initial), task="detect")
    # Validation may fuse/cast a model. Use a deep copy so the baseline cannot
    # alter the actual training initialization.
    baseline_model = copy.deepcopy(model)
    validation = {"data": str(dataset / "data.yaml"), "split": "val",
                  "device": "cpu", "imgsz": config.imgsz, "batch": config.batch,
                  "workers": 0, "half": False, "plots": False, "verbose": False,
                  "save_json": False, "project": str(output), "exist_ok": False}
    baseline = _metrics(baseline_model.val(name="baseline", **validation))
    del baseline_model
    initial_parameter_sha = _parameter_sha(model.model)
    initialization_verified = []

    def verify_training_initialization(trainer: object) -> None:
        if _parameter_sha(trainer.model) != initial_parameter_sha:
            raise ValueError("YOLO_BASELINE_INITIALIZATION_MISMATCH")
        initialization_verified.append(True)

    model.add_callback("on_train_start", verify_training_initialization)
    train_options = _training_options(
        config, dataset=dataset, output=output, device="cpu"
    )
    model.train(**train_options)
    checkpoint = output / "training/weights/last.pt"
    if not checkpoint.is_file() or not checkpoint.stat().st_size:
        raise ValueError("YOLO_CHECKPOINT_MISSING")
    # Verify an actual serialization round-trip and evaluate that exact last.pt,
    # not the library's automatically selected best.pt.
    reloaded = YOLO(str(checkpoint), task="detect")
    # Capture checkpoint parameters before val() can fuse convolutions in-place.
    candidate_parameter_sha = _parameter_sha(reloaded.model)
    candidate = _metrics(reloaded.val(name="candidate", **validation))
    checkpoint_sha = _sha(checkpoint)
    feedback = _validation_feedback(reloaded, request, config, checkpoint_sha)
    with (output / "training/results.csv").open(encoding="utf-8", newline="") as stream:
        rows = list(csv.DictReader(stream))
    if len(rows) != config.epochs:
        raise ValueError("YOLO_EPOCH_COUNT_MISMATCH")
    losses = [{key.strip(): float(value) for key, value in row.items()
               if key.strip().startswith("train/")} for row in rows]
    if (not initialization_verified or not losses or not all(losses)
            or any(not math.isfinite(value) for row in losses for value in row.values())):
        raise ValueError("YOLO_TRAINING_VERIFICATION_FAILED")
    if _dataset_receipt(dataset) != request["dataset_receipt"]:
        raise ValueError("YOLO_DATASET_CHANGED")
    return {"status": "completed", "baseline": baseline, "candidate": candidate,
            **feedback,
            "actual_epochs": len(rows), "initialization": "trusted_local_weights" if initial else "random",
            "baseline_initialization_match": "VERIFIED",
            "initial_parameter_sha256": initial_parameter_sha,
            "candidate_parameter_sha256": candidate_parameter_sha,
            "training_losses": losses,
            "checkpoint": {"relative_path": checkpoint.relative_to(output).as_posix(),
                           "sha256": checkpoint_sha, "bytes": checkpoint.stat().st_size,
                           "round_trip": "VERIFIED", "selection": "last_epoch"},
            "network_policy": "python_socket_deny_and_integrations_disabled",
            "training_parameters": {k: v for k, v in train_options.items()
                                    if k not in {"data", "project"}}}


def _child_main() -> int:
    mode, request_file, result_file = sys.argv[1:]
    result_path = Path(result_file)
    _deny_network_and_children()
    _package_paths()
    request = json.loads(Path(request_file).read_text(encoding="utf-8"))
    try:
        if mode == "probe":
            result = _runtime_metadata(request["executable_sha256"])
            if request["import_check"] and result["status"] == "ready":
                torch, torchvision, ultralytics = _import_backend()
                value = torch.ones(1, device="cpu") + 1
                result["import_status"] = "PASSED" if value.item() == 2 else "FAILED"
                result["imported_versions"] = {"torch": torch.__version__,
                                               "torchvision": torchvision.__version__,
                                               "ultralytics": ultralytics.__version__}
                result["device"] = "cpu"
        elif mode == "train":
            result = _child_train(request)
        else:
            raise ValueError("YOLO_CHILD_MODE_INVALID")
        _json_write(result_path, result)
        return 0
    except Exception as error:
        # Do not expose paths or third-party exception messages in API DTOs.
        known = str(error)
        safe = known if known.startswith(("YOLO_", "RUNTIME_")) and known.replace("_", "").isalnum() else "YOLO_CHILD_EXECUTION_FAILED"
        _json_write(result_path, {"status": "failed", "error_code": safe,
                                  "error_type": type(error).__name__})
        import traceback
        traceback.print_exc()  # local job log only; caller must not expose it via API
        return 0


if __name__ == "__main__":
    raise SystemExit(_child_main())


__all__ = ["YoloTrainingConfig", "probe_vision_runtime", "run_yolo_training"]
