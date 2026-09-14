"""External normality inference boundary tests."""

from __future__ import annotations

import hashlib
import subprocess
import sys

import pytest

from visiondata_gate import normality_inference


def _sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def test_external_worker_command_disables_bytecode_residue(tmp_path):
    command = normality_inference._worker_command(
        tmp_path / "python.exe",
        "validate",
        tmp_path / "request.json",
        tmp_path / "result.json",
    )

    assert command[1:4] == ["-B", "-I", "-S"]
    assert normality_inference._child_environment(tmp_path)[
        "PYTHONDONTWRITEBYTECODE"
    ] == "1"


def test_pack_validation_rejects_changed_bytes_before_starting_a_child(
    tmp_path, monkeypatch
):
    executable = tmp_path / "python.exe"
    executable.write_bytes(b"synthetic runtime")
    pack = tmp_path / "model-pack.pt"
    pack.write_bytes(b"changed pack")

    def forbidden(*_args, **_kwargs):
        pytest.fail("invalid pack bytes reached child-process creation")

    monkeypatch.setattr(subprocess, "Popen", forbidden)
    with pytest.raises(ValueError, match="NORMALITY_MODEL_PACK_SHA_MISMATCH"):
        normality_inference.validate_normality_model_pack(
            executable=executable,
            expected_executable_sha256=_sha(executable),
            expected_runtime_sha256="1" * 64,
            model_pack=pack,
            expected_model_pack_sha256="2" * 64,
            expected_backbone_weights_sha256="3" * 64,
            expected_source_binding_sha256="4" * 64,
            expected_source_index_sha256="5" * 64,
            output_root=tmp_path / "validation",
        )


def _synthetic_pack(schema: str) -> dict:
    return {
        "schema_version": schema,
        "architecture": "YOLO26N_CLASSIFICATION_MULTISCALE_FEATURE_AUTOENCODER",
        "feature_layers": [4, 6, 9],
        "split_seed": 20260913,
        "model_seed": 20260913,
        "image_size": 256,
        "selected_image_aggregation": "mean",
        "image_threshold": 0.5,
        "pixel_threshold": 1.5,
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
        "anomaly_map_blend": {
            "normal_feature_diagonal_gaussian": 0.5,
            "feature_reconstruction_error": 0.5,
        },
        "channels": {4: 16, 6: 24, 9: 32},
        "bottlenecks": {4: 16, 6: 16, 9: 16},
        "backbone": {
            "state_dict": {"weight": "tensor"},
            "model_yaml": {"task": "classify"},
            "weights_sha256": "3" * 64,
            "provenance": {
                "provider": "Ultralytics",
                "architecture": "yolo26n-cls",
                "task": "classify",
                "class_count": 1000,
                "pretraining_dataset": "ImageNet",
                "source_url": "https://github.com/ultralytics/assets/releases/download/v8.4.0/yolo26n-cls.pt",
            },
            "license": "AGPL-3.0",
        },
        "students": {str(layer): {"weight": "tensor"} for layer in (4, 6, 9)},
        "normalizers": {
            str(layer): {
                "normal_reference_mean": "tensor",
                "normal_reference_variance": "tensor",
                "reconstruction_mean": "tensor",
                "reconstruction_std": "tensor",
                "gaussian_mean": "tensor",
                "gaussian_std": "tensor",
            }
            for layer in (4, 6, 9)
        },
    }


def test_pack_contract_accepts_only_v2_native_yolo_preprocessing():
    validated = normality_inference._validate_pack_contract(
        _synthetic_pack("visiondata-gate.yolo26-normality-model-pack.v2"),
        expected_backbone_weights_sha256="3" * 64,
        tensor_validator=lambda value: value == "tensor",
    )
    assert validated["model_pack_schema_version"].endswith(".v2")
    assert validated["input_normalization"]["mean"] == [0.0, 0.0, 0.0]
    with pytest.raises(ValueError, match="NORMALITY_MODEL_PACK_V2_REQUIRED"):
        normality_inference._validate_pack_contract(
            _synthetic_pack("visiondata-gate.yolo26-normality-model-pack.v1"),
            expected_backbone_weights_sha256="3" * 64,
            tensor_validator=lambda value: value == "tensor",
        )


def test_validation_returns_only_bound_identity_from_external_worker(
    tmp_path, monkeypatch
):
    executable = tmp_path / "python.exe"
    executable.write_bytes(b"synthetic runtime")
    pack = tmp_path / "model-pack.pt"
    pack.write_bytes(b"synthetic v2 pack")
    runtime_sha = "1" * 64
    pack_sha = _sha(pack)
    backbone_sha = "3" * 64
    binding_sha = "4" * 64
    index_sha = "5" * 64
    backend_sha = _sha(normality_inference.Path(normality_inference.__file__))
    calls = []

    def worker(**kwargs):
        calls.append(kwargs)
        return {
            "status": "validated",
            "runtime_sha256": runtime_sha,
            "model_pack_sha256": pack_sha,
            "model_pack_schema_version": "visiondata-gate.yolo26-normality-model-pack.v2",
            "backbone_weights_sha256": backbone_sha,
            "source_binding_sha256": binding_sha,
            "source_index_sha256": index_sha,
            "inference_backend_sha256": backend_sha,
            "device": "cpu",
            "machine_write_permitted": False,
            "production_release_allowed": False,
        }

    monkeypatch.setattr(normality_inference, "_run_worker_process", worker)
    result = normality_inference.validate_normality_model_pack(
        executable=executable,
        expected_executable_sha256=_sha(executable),
        expected_runtime_sha256=runtime_sha,
        model_pack=pack,
        expected_model_pack_sha256=pack_sha,
        expected_backbone_weights_sha256=backbone_sha,
        expected_source_binding_sha256=binding_sha,
        expected_source_index_sha256=index_sha,
        output_root=tmp_path / "validation",
    )

    assert result["status"] == "VALIDATED_FOR_LOCAL_SANDBOX"
    assert result["production_release_allowed"] is False
    assert result["machine_write_permitted"] is False
    assert len(calls) == 1
    assert calls[0]["mode"] == "validate"


def test_validation_requires_exact_child_backend_identity(tmp_path, monkeypatch):
    executable = tmp_path / "python.exe"
    executable.write_bytes(b"synthetic runtime")
    pack = tmp_path / "model-pack.pt"
    pack.write_bytes(b"synthetic v2 pack")
    runtime_sha = "1" * 64
    pack_sha = _sha(pack)
    monkeypatch.setattr(
        normality_inference,
        "_run_worker_process",
        lambda **_kwargs: {
            "status": "validated",
            "runtime_sha256": runtime_sha,
            "model_pack_sha256": pack_sha,
            "model_pack_schema_version": "visiondata-gate.yolo26-normality-model-pack.v2",
            "backbone_weights_sha256": "3" * 64,
            "source_binding_sha256": "4" * 64,
            "source_index_sha256": "5" * 64,
            "device": "cpu",
            "machine_write_permitted": False,
            "production_release_allowed": False,
        },
    )

    with pytest.raises(ValueError, match="NORMALITY_WORKER_BOUNDARY_MISMATCH"):
        normality_inference.validate_normality_model_pack(
            executable=executable,
            expected_executable_sha256=_sha(executable),
            expected_runtime_sha256=runtime_sha,
            model_pack=pack,
            expected_model_pack_sha256=pack_sha,
            expected_backbone_weights_sha256="3" * 64,
            expected_source_binding_sha256="4" * 64,
            expected_source_index_sha256="5" * 64,
            output_root=tmp_path / "validation",
        )


def test_child_validation_rechecks_runtime_and_v2_pack_identity(tmp_path, monkeypatch):
    pack = tmp_path / "model_pack.pt"
    pack.write_bytes(b"synthetic child fixture")
    request = {
        "schema_version": "visiondata-gate.normality-worker-request.v1",
        "runtime_executable_sha256": _sha(normality_inference.Path(sys.executable)),
        "runtime_sha256": "1" * 64,
        "model_pack_path": str(pack),
        "model_pack_sha256": _sha(pack),
        "backbone_weights_sha256": "3" * 64,
        "source_binding_sha256": "4" * 64,
        "source_index_sha256": "5" * 64,
        "inference_backend_sha256": _sha(
            normality_inference.Path(normality_inference.__file__)
        ),
        "device": "cpu",
        "production_release_allowed": False,
        "machine_write_permitted": False,
    }
    monkeypatch.setattr(
        normality_inference,
        "_runtime_metadata",
        lambda _expected: {"runtime_sha256": "1" * 64, "status": "ready"},
    )
    monkeypatch.setattr(
        normality_inference,
        "_load_normality_pack",
        lambda *_args, **_kwargs: {
            "model_pack_schema_version": "visiondata-gate.yolo26-normality-model-pack.v2",
            "backbone_weights_sha256": "3" * 64,
        },
    )

    result = normality_inference._child_validate(request)

    assert result["status"] == "validated"
    assert result["runtime_sha256"] == "1" * 64
    assert result["model_pack_sha256"] == _sha(pack)
    assert result["source_binding_sha256"] == "4" * 64
    assert result["source_index_sha256"] == "5" * 64
    assert result["production_release_allowed"] is False


def test_model_pack_deserialization_is_weights_only_on_cpu(tmp_path):
    pack = tmp_path / "model_pack.pt"
    pack.write_bytes(b"synthetic")
    calls = []

    class TorchProbe:
        @staticmethod
        def load(path, **kwargs):
            calls.append((path, kwargs))
            return {"loaded": True}

    value = normality_inference._torch_load_model_pack(TorchProbe, pack)

    assert value == {"loaded": True}
    assert calls == [(pack, {"map_location": "cpu", "weights_only": True})]


def test_runtime_metadata_loader_executes_backend_with_dataclass_module_registered():
    executable = normality_inference.Path(sys.executable).resolve()
    receipt = normality_inference._runtime_metadata(_sha(executable))

    assert receipt["executable_sha256"] == _sha(executable)
    assert receipt["schema"] == "vision-runtime.v1"
    assert isinstance(receipt["runtime_sha256"], str)


def test_inference_binds_registered_input_and_heatmap_artifact(tmp_path, monkeypatch):
    executable = tmp_path / "python.exe"
    executable.write_bytes(b"synthetic runtime")
    pack = tmp_path / "model-pack.pt"
    pack.write_bytes(b"synthetic v2 pack")
    image = tmp_path / ("a" * 64)
    image.write_bytes(b"synthetic image bytes")
    runtime_sha = "1" * 64
    pack_sha = _sha(pack)
    backend_sha = _sha(normality_inference.Path(normality_inference.__file__))

    def worker(**kwargs):
        request = kwargs["request"]
        heatmap = normality_inference.Path(request["heatmap_path"])
        heatmap.parent.mkdir(parents=True, exist_ok=True)
        heatmap.write_bytes(b"synthetic heatmap")
        return {
            "status": "completed",
            "runtime_sha256": runtime_sha,
            "model_pack_sha256": pack_sha,
            "model_pack_schema_version": "visiondata-gate.yolo26-normality-model-pack.v2",
            "backbone_weights_sha256": "3" * 64,
            "source_binding_sha256": "4" * 64,
            "source_index_sha256": "5" * 64,
            "inference_backend_sha256": backend_sha,
            "image_sha256": _sha(image),
            "image_score": 0.75,
            "image_threshold": 0.5,
            "pixel_threshold": 1.5,
            "predicted_anomaly": True,
            "positive_pixel_fraction": 0.125,
            "heatmap_sha256": _sha(heatmap),
            "heatmap_bytes": heatmap.stat().st_size,
            "heatmap_width": 64,
            "heatmap_height": 64,
            "device": "cpu",
            "machine_write_permitted": False,
            "production_release_allowed": False,
        }

    monkeypatch.setattr(normality_inference, "_run_worker_process", worker)
    result = normality_inference.run_normality_inference(
        executable=executable,
        expected_executable_sha256=_sha(executable),
        expected_runtime_sha256=runtime_sha,
        model_pack=pack,
        expected_model_pack_sha256=pack_sha,
        expected_backbone_weights_sha256="3" * 64,
        expected_source_binding_sha256="4" * 64,
        expected_source_index_sha256="5" * 64,
        image=image,
        image_format="png",
        expected_image_sha256=_sha(image),
        output_root=tmp_path / "inference",
    )

    assert result["status"] == "COMPLETED_LOCAL_SANDBOX_INFERENCE"
    assert result["predicted_anomaly"] is True
    assert result["heatmap"]["sha256"] == hashlib.sha256(
        b"synthetic heatmap"
    ).hexdigest()
    assert "path" not in result["heatmap"]
    assert result["production_release_allowed"] is False


def _run_parent_inference_with_worker_result(
    tmp_path,
    monkeypatch,
    *,
    include_backend_identity: bool,
    predicted_anomaly: bool,
):
    executable = tmp_path / "python.exe"
    executable.write_bytes(b"synthetic runtime")
    pack = tmp_path / "model-pack.pt"
    pack.write_bytes(b"synthetic v2 pack")
    image = tmp_path / "image.png"
    image.write_bytes(b"synthetic image bytes")
    runtime_sha = "1" * 64
    pack_sha = _sha(pack)
    backend_sha = _sha(normality_inference.Path(normality_inference.__file__))

    def worker(**kwargs):
        request = kwargs["request"]
        heatmap = normality_inference.Path(request["heatmap_path"])
        heatmap.parent.mkdir(parents=True, exist_ok=True)
        heatmap.write_bytes(b"synthetic heatmap")
        result = {
            "status": "completed",
            "runtime_sha256": runtime_sha,
            "model_pack_sha256": pack_sha,
            "model_pack_schema_version": "visiondata-gate.yolo26-normality-model-pack.v2",
            "backbone_weights_sha256": "3" * 64,
            "source_binding_sha256": "4" * 64,
            "source_index_sha256": "5" * 64,
            "image_sha256": _sha(image),
            "image_score": 0.75,
            "image_threshold": 0.5,
            "pixel_threshold": 1.5,
            "predicted_anomaly": predicted_anomaly,
            "positive_pixel_fraction": 0.125,
            "heatmap_sha256": _sha(heatmap),
            "heatmap_bytes": heatmap.stat().st_size,
            "heatmap_width": 64,
            "heatmap_height": 64,
            "device": "cpu",
            "machine_write_permitted": False,
            "production_release_allowed": False,
        }
        if include_backend_identity:
            result["inference_backend_sha256"] = backend_sha
        return result

    monkeypatch.setattr(normality_inference, "_run_worker_process", worker)
    return normality_inference.run_normality_inference(
        executable=executable,
        expected_executable_sha256=_sha(executable),
        expected_runtime_sha256=runtime_sha,
        model_pack=pack,
        expected_model_pack_sha256=pack_sha,
        expected_backbone_weights_sha256="3" * 64,
        expected_source_binding_sha256="4" * 64,
        expected_source_index_sha256="5" * 64,
        image=image,
        image_format="png",
        expected_image_sha256=_sha(image),
        output_root=tmp_path / "inference",
    )


def test_inference_requires_exact_child_backend_identity(tmp_path, monkeypatch):
    with pytest.raises(ValueError, match="NORMALITY_WORKER_BOUNDARY_MISMATCH"):
        _run_parent_inference_with_worker_result(
            tmp_path,
            monkeypatch,
            include_backend_identity=False,
            predicted_anomaly=True,
        )


def test_inference_rejects_prediction_threshold_contradiction(tmp_path, monkeypatch):
    with pytest.raises(ValueError, match="NORMALITY_INFERENCE_PREDICTION_MISMATCH"):
        _run_parent_inference_with_worker_result(
            tmp_path,
            monkeypatch,
            include_backend_identity=True,
            predicted_anomaly=False,
        )


def test_child_inference_preserves_bound_model_source_and_image_identity(
    tmp_path, monkeypatch
):
    pack = tmp_path / "model_pack.pt"
    pack.write_bytes(b"synthetic child pack")
    image = tmp_path / "image.png"
    image.write_bytes(b"synthetic child image")
    heatmap = tmp_path / "heatmap.png"
    executable_sha = _sha(normality_inference.Path(sys.executable))
    backend_sha = _sha(normality_inference.Path(normality_inference.__file__))
    request = {
        "schema_version": "visiondata-gate.normality-worker-request.v1",
        "runtime_executable_sha256": executable_sha,
        "runtime_sha256": "1" * 64,
        "model_pack_path": str(pack),
        "model_pack_sha256": _sha(pack),
        "backbone_weights_sha256": "3" * 64,
        "source_binding_sha256": "4" * 64,
        "source_index_sha256": "5" * 64,
        "inference_backend_sha256": backend_sha,
        "device": "cpu",
        "production_release_allowed": False,
        "machine_write_permitted": False,
        "image_path": str(image),
        "image_sha256": _sha(image),
        "heatmap_path": str(heatmap),
    }
    monkeypatch.setattr(
        normality_inference,
        "_runtime_metadata",
        lambda _expected: {"runtime_sha256": "1" * 64, "status": "ready"},
    )
    monkeypatch.setattr(
        normality_inference,
        "_load_normality_pack",
        lambda *_args, **_kwargs: {
            "model_pack_schema_version": "visiondata-gate.yolo26-normality-model-pack.v2",
            "backbone_weights_sha256": "3" * 64,
        },
    )

    def score(_loaded, _image, _expected_image_sha, _heatmap):
        assert _image == image
        assert _expected_image_sha == _sha(image)
        assert _heatmap == heatmap
        return {
            "image_score": 0.75,
            "image_threshold": 0.5,
            "pixel_threshold": 1.5,
            "predicted_anomaly": True,
            "positive_pixel_fraction": 0.125,
            "heatmap_sha256": "6" * 64,
            "heatmap_bytes": 16,
            "heatmap_width": 64,
            "heatmap_height": 64,
        }

    monkeypatch.setattr(normality_inference, "_score_normality_image", score)
    result = normality_inference._child_infer(request)

    assert result["status"] == "completed"
    assert result["model_pack_sha256"] == _sha(pack)
    assert result["image_sha256"] == _sha(image)
    assert result["source_binding_sha256"] == "4" * 64
    assert result["production_release_allowed"] is False
    changed = _synthetic_pack("visiondata-gate.yolo26-normality-model-pack.v2")
    changed["input_normalization"]["mean"] = [0.485, 0.456, 0.406]
    with pytest.raises(ValueError, match="NORMALITY_NATIVE_PREPROCESSING_REQUIRED"):
        normality_inference._validate_pack_contract(
            changed,
            expected_backbone_weights_sha256="3" * 64,
            tensor_validator=lambda value: value == "tensor",
        )
