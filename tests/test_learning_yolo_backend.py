"""Bounded subprocess contracts plus an explicitly enabled real CPU smoke."""

from dataclasses import FrozenInstanceError
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
from types import SimpleNamespace

from PIL import Image, ImageDraw
import pytest

from visiondata_gate import learning_yolo_backend as backend


def _dataset(root: Path) -> Path:
    root.mkdir()
    for split, count in (("train", 4), ("val", 2), ("test", 2)):
        (root / "images" / split).mkdir(parents=True)
        (root / "labels" / split).mkdir(parents=True)
        for index in range(count):
            image = Image.new("RGB", (64, 64), (index * 20, len(split) * 15, 30))
            ImageDraw.Draw(image).rectangle(
                (16, 16, 47, 47), fill=(200, 100, index * 10)
            )
            image.save(root / "images" / split / f"{index}.png")
            (root / "labels" / split / f"{index}.txt").write_text(
                "0 0.5 0.5 0.5 0.5\n", encoding="utf-8"
            )
    (root / "data.yaml").write_text(
        json.dumps(
            {
                "path": ".",
                "train": "images/train",
                "val": "images/val",
                "test": "images/test",
                "names": ["synthetic_rectangle"],
            }
        ),
        encoding="utf-8",
    )
    return root


@pytest.mark.parametrize(
    "values",
    [
        {"epochs": 0},
        {"epochs": 6},
        {"epochs": True},
        {"imgsz": 65},
        {"imgsz": 640},
        {"batch": 1},
        {"threads": 5},
        {"max_seconds": 601},
        {"seed": -1},
        {"batch": 2.0},
        {"max_seconds": float("nan")},
    ],
)
def test_strict_config(values):
    with pytest.raises(ValueError, match="YOLO_CONFIG_"):
        backend.YoloTrainingConfig(**values)


def test_frozen_config_and_unknown_fields():
    config = backend.YoloTrainingConfig()
    with pytest.raises(FrozenInstanceError):
        config.epochs = 3
    with pytest.raises(TypeError):
        backend.YoloTrainingConfig(device="cuda")


@pytest.mark.parametrize(
    "key", ["backbone", "head", "scales", "scale", "end2end", "reg_max"]
)
def test_initial_weights_architecture_cannot_rely_on_claimed_model_name(key):
    expected = {
        "backbone": [[-1, 1, "Conv", [64, 3, 2]]],
        "head": ["Detect"],
        "scales": {"n": [0.5, 0.25, 1024]},
        "scale": "n",
        "end2end": True,
        "reg_max": 1,
    }
    backend._validate_initial_definition(expected, expected)
    wrong = {**expected, key: "different"}
    with pytest.raises(ValueError, match="YOLO_INITIAL_ARCHITECTURE_MISMATCH"):
        backend._validate_initial_definition(wrong, expected)


def _box(class_id=0, xyxy=None, confidence=None):
    value = {
        "class_id": class_id,
        "xyxy": [0.25, 0.25, 0.75, 0.75] if xyxy is None else xyxy,
    }
    if confidence is not None:
        value["confidence"] = confidence
    return value


def test_validation_matching_class_aware_one_to_one_and_confidence_boundary():
    expected = [_box(0), _box(1)]
    predictions = [
        _box(0, confidence=0.25),
        _box(0, confidence=0.24),
        _box(0, confidence=0.8),
        _box(2, confidence=0.9),
    ]
    result = backend._match_validation_boxes(predictions, expected)
    assert (result["tp"], result["fp"], result["fn"]) == (1, 2, 1)
    assert len(result["prediction_boxes"]) == 3
    assert result["matches"] == [
        {"prediction_index": 1, "ground_truth_index": 0, "iou": 1.0}
    ]
    assert result["matched_ious"] == [1.0]
    assert result["reason_codes"] == [
        "FALSE_POSITIVE_CANDIDATE",
        "FALSE_NEGATIVE_CANDIDATE",
    ]
    assert result["review_required"] is True
    # Input boxes are not reordered or annotated in-place.
    assert predictions[0]["confidence"] == 0.25
    assert expected == [_box(0), _box(1)]


def test_validation_matching_includes_exact_iou_boundary_and_excludes_below():
    truth = [_box(xyxy=[0, 0, 1, 1])]
    exact = backend._match_validation_boxes(
        [_box(xyxy=[0, 0, 1, 0.5], confidence=0.8)], truth
    )
    assert (exact["tp"], exact["fp"], exact["fn"]) == (1, 0, 0)
    assert exact["matched_ious"] == [0.5]
    below = backend._match_validation_boxes(
        [_box(xyxy=[0, 0, 1, 0.499], confidence=0.8)], truth
    )
    assert (below["tp"], below["fp"], below["fn"]) == (0, 1, 1)


def test_validation_matching_global_greedy_iou_not_confidence_order():
    truth = [_box(xyxy=[0, 0, 1, 1])]
    predictions = [
        _box(xyxy=[0, 0, 1, 0.6], confidence=0.9),
        _box(xyxy=[0, 0, 1, 1], confidence=0.3),
    ]
    result = backend._match_validation_boxes(predictions, truth)
    assert result["matches"] == [
        {"prediction_index": 1, "ground_truth_index": 0, "iou": 1.0}
    ]
    assert backend._match_validation_boxes(list(reversed(predictions)), truth) == result


def test_validation_matching_ties_and_empty_normal_images():
    tied = backend._match_validation_boxes(
        [_box(confidence=0.8), _box(confidence=0.8)], [_box(), _box()]
    )
    assert tied["matches"] == [
        {"prediction_index": 0, "ground_truth_index": 0, "iou": 1.0},
        {"prediction_index": 1, "ground_truth_index": 1, "iou": 1.0},
    ]
    empty = backend._match_validation_boxes([], [])
    assert (empty["tp"], empty["fp"], empty["fn"]) == (0, 0, 0)
    assert empty["reason_codes"] == []
    missed = backend._match_validation_boxes([], [_box()])
    assert missed["reason_codes"] == ["FALSE_NEGATIVE_CANDIDATE"]


@pytest.mark.parametrize(
    "invalid",
    [
        _box(xyxy=[0, 0, 0, 1], confidence=0.8),
        _box(xyxy=[0, 0, float("nan"), 1], confidence=0.8),
        _box(xyxy=[0, 0, 2, 1], confidence=0.8),
        _box(class_id=True, confidence=0.8),
        _box(confidence=float("inf")),
    ],
)
def test_validation_matching_rejects_invalid_predictions(invalid):
    with pytest.raises(ValueError, match="YOLO_FEEDBACK_"):
        backend._match_validation_boxes([invalid], [])


class _CpuList:
    def __init__(self, values):
        self.values = values

    def cpu(self):
        return self

    def tolist(self):
        return self.values


class _FeedbackModel:
    def __init__(self, after_predict=None):
        self.calls = []
        self.after_predict = after_predict

    def predict(self, **kwargs):
        self.calls.append(kwargs)
        if self.after_predict:
            self.after_predict()
        return [
            SimpleNamespace(
                boxes=SimpleNamespace(
                    xyxyn=_CpuList([[0.25, 0.25, 0.75, 0.75]]),
                    conf=_CpuList([0.8]),
                    cls=_CpuList([0.0]),
                )
            )
        ]


def _feedback_request(dataset):
    return {
        "dataset": str(dataset),
        "dataset_receipt": backend._dataset_receipt(dataset),
        "source_dataset_sha256": "a" * 64,
        "runtime_sha256": "b" * 64,
    }


def test_validation_feedback_predicts_every_val_member_only_and_filters_candidates(
    tmp_path,
):
    dataset = _dataset(tmp_path / "dataset")
    (dataset / "labels/val/1.txt").write_text("", encoding="utf-8")
    request = _feedback_request(dataset)
    model = _FeedbackModel()
    result = backend._validation_feedback(
        model, request, backend.YoloTrainingConfig(), "c" * 64
    )
    details = result["validation_samples_detail"]
    assert [row["sample_id"] for row in details] == ["0", "1"]
    assert [(row["tp"], row["fp"], row["fn"]) for row in details] == [
        (1, 0, 0),
        (0, 1, 0),
    ]
    assert [row["sample_id"] for row in result["validation_feedback_candidates"]] == [
        "1"
    ]
    assert len(model.calls) == 2
    for call in model.calls:
        assert Path(call["source"]).parent == dataset / "images/val"
        assert call["conf"] == 0.25 and call["iou"] == 0.5
        assert call["save"] is False and call["device"] == "cpu"
    for row in details:
        assert row["image_sha256"] == backend._sha(
            dataset / f"images/val/{row['sample_id']}.png"
        )
        assert row["label_sha256"] == backend._sha(
            dataset / f"labels/val/{row['sample_id']}.txt"
        )
    protocol = result["validation_feedback_protocol"]
    assert protocol["dataset_sha256"] == "a" * 64
    assert protocol["runtime_sha256"] == "b" * 64
    assert protocol["checkpoint_sha256"] == "c" * 64
    assert protocol["sample_count"] == 2 and protocol["split"] == "val"
    assert protocol["label_truth_status"] == "REFERENCE_LABELS_NOT_ADJUDICATED"
    assert str(tmp_path) not in json.dumps(result)


def test_validation_feedback_rejects_bytes_changed_during_prediction(tmp_path):
    dataset = _dataset(tmp_path / "dataset")
    request = _feedback_request(dataset)
    model = _FeedbackModel(
        after_predict=lambda: (dataset / "labels/val/0.txt").write_text(
            "", encoding="utf-8"
        )
    )
    with pytest.raises(ValueError, match="YOLO_DATASET_CHANGED"):
        backend._validation_feedback(
            model, request, backend.YoloTrainingConfig(), "c" * 64
        )


def test_environment_never_inherits_provider_tokens_or_proxy(tmp_path, monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "private")
    monkeypatch.setenv("HTTPS_PROXY", "private-proxy")
    monkeypatch.setenv("PYTHONPATH", "untrusted-code")
    monkeypatch.setenv("PATH", "untrusted-tools")
    environment = backend._child_environment(tmp_path)
    for key in ("OPENAI_API_KEY", "HTTPS_PROXY", "PYTHONPATH", "PATH"):
        assert key not in environment
    assert environment["CUDA_VISIBLE_DEVICES"] == ""
    assert environment["YOLO_AUTOINSTALL"] == "false"
    assert str(tmp_path) in environment["YOLO_CONFIG_DIR"]
    assert environment["WANDB_MODE"] == "disabled"


def test_package_import_does_not_load_torch_or_ultralytics():
    source = str(Path(backend.__file__))
    code = (
        f"import sys, runpy; runpy.run_path({source!r}); "
        "assert 'torch' not in sys.modules; assert 'ultralytics' not in sys.modules"
    )
    assert (
        subprocess.run(
            [sys.executable, "-I", "-S", "-c", code], capture_output=True, check=False
        ).returncode
        == 0
    )


def test_socket_and_subprocess_blocker_in_disposable_child():
    source = str(Path(backend.__file__))
    code = f"""
import sys, runpy
_deny_network_and_children = runpy.run_path({source!r})['_deny_network_and_children']
import socket, subprocess
_deny_network_and_children()
for action in (lambda: socket.create_connection(('127.0.0.1', 80)),
               lambda: socket.getaddrinfo('example.com', 443),
               lambda: socket.gethostbyname('example.com'),
               lambda: socket.socket().connect(('127.0.0.1', 80)),
               lambda: subprocess.run([sys.executable, '-c', 'pass'])):
    try:
        action()
    except OSError:
        pass
    else:
        raise AssertionError('denial missing')
"""
    assert (
        subprocess.run(
            [sys.executable, "-I", "-S", "-c", code], capture_output=True, check=False
        ).returncode
        == 0
    )


def test_probe_checks_executable_before_spawning(tmp_path, monkeypatch):
    monkeypatch.setattr(subprocess, "Popen", lambda *_a, **_k: pytest.fail("spawned"))
    with pytest.raises(ValueError, match="RUNTIME_EXECUTABLE_SHA_MISMATCH"):
        backend.probe_vision_runtime(Path(sys.executable), "0" * 64, tmp_path)


def test_metadata_probe_is_stable_and_has_no_private_paths(tmp_path):
    executable = Path(sys.executable)
    expected = backend._sha(executable)
    first = backend.probe_vision_runtime(executable, expected, tmp_path)
    second = backend.probe_vision_runtime(executable, expected, tmp_path)
    assert first == second
    assert first["executable_sha256"] == expected
    assert first["import_status"] == "NOT_RUN"
    assert len(first["runtime_sha256"]) == 64
    assert str(tmp_path) not in json.dumps(first)
    assert str(executable) not in json.dumps(first)


def test_dataset_denominators_and_hash_changes(tmp_path):
    dataset = _dataset(tmp_path / "dataset")
    first = backend._dataset_receipt(dataset)
    assert first["counts"] == {"train": 4, "val": 2, "test": 2}
    label = dataset / "labels/train/0.txt"
    label.write_text("0 0.5 0.5 0.25 0.25\n", encoding="utf-8")
    assert backend._dataset_receipt(dataset)["sha256"] != first["sha256"]


@pytest.mark.parametrize(
    "label",
    [
        "0 0.5 0.5 0.2 0.2 0.3 0.3",
        "1 0.5 0.5 0.2 0.2",
        "0 nan 0.5 0.2 0.2",
        "0 0.5 0.5 -0.2 0.2",
        "0 0 0 0.5 0.5",
    ],
)
def test_segmentation_and_invalid_detection_labels_rejected(tmp_path, label):
    dataset = _dataset(tmp_path / "dataset")
    (dataset / "labels/train/0.txt").write_text(label, encoding="utf-8")
    with pytest.raises(ValueError, match="YOLO_DETECTION_BOX_"):
        backend._dataset_receipt(dataset)


@pytest.mark.parametrize(
    "update",
    [
        {"download": "arbitrary code"},
        {"train": "../private"},
        {"names": {1: "missing-zero"}},
        {"nc": 2},
        {"path": "https://example.com"},
    ],
)
def test_dataset_config_rejects_code_paths_and_class_drift(tmp_path, update):
    dataset = _dataset(tmp_path / "dataset")
    path = dataset / "data.yaml"
    value = json.loads(path.read_text())
    value.update(update)
    path.write_text(json.dumps(value), encoding="utf-8")
    with pytest.raises(ValueError, match="YOLO_"):
        backend._dataset_receipt(dataset)


def test_train_val_content_leakage_rejected(tmp_path):
    dataset = _dataset(tmp_path / "dataset")
    (dataset / "images/val/0.png").write_bytes(
        (dataset / "images/train/0.png").read_bytes()
    )
    with pytest.raises(ValueError, match="SPLIT_LEAKAGE"):
        backend._dataset_receipt(dataset)


def test_cancel_does_not_launch_and_persists_nonapproval(tmp_path, monkeypatch):
    dataset = _dataset(tmp_path / "dataset")
    monkeypatch.setattr(subprocess, "Popen", lambda *_a, **_k: pytest.fail("spawned"))
    result = backend.run_yolo_training(
        executable=Path(sys.executable),
        expected_executable_sha256=backend._sha(Path(sys.executable)),
        expected_runtime_sha256="a" * 64,
        dataset_root=dataset,
        output_root=tmp_path / "job",
        config=backend.YoloTrainingConfig(),
        cancelled=lambda: True,
    )
    assert result["status"] == "cancelled"
    assert not result["production_approved"]
    assert "checkpoint" not in result
    assert (
        json.loads((tmp_path / "job/result.json").read_text())["status"] == "cancelled"
    )


def test_runtime_drift_prevents_training(tmp_path, monkeypatch):
    dataset = _dataset(tmp_path / "dataset")
    monkeypatch.setattr(
        backend,
        "_probe_runtime",
        lambda *_a, **_k: {
            "status": "ready",
            "runtime_sha256": "b" * 64,
        },
    )
    monkeypatch.setattr(subprocess, "Popen", lambda *_a, **_k: pytest.fail("spawned"))
    with pytest.raises(ValueError, match="RUNTIME_FINGERPRINT_MISMATCH"):
        backend.run_yolo_training(
            executable=Path(sys.executable),
            expected_executable_sha256=backend._sha(Path(sys.executable)),
            expected_runtime_sha256="a" * 64,
            dataset_root=dataset,
            output_root=tmp_path / "job",
            config=backend.YoloTrainingConfig(),
        )


@pytest.mark.parametrize("interrupt", ["cancelled", "timed_out"])
def test_runtime_probe_interrupt_kills_only_its_owned_child(
    tmp_path, monkeypatch, interrupt
):
    processes = []
    original = subprocess.Popen

    def start(*args, **kwargs):
        process = original(*args, **kwargs)
        processes.append(process)
        return process

    monkeypatch.setattr(subprocess, "Popen", start)
    monkeypatch.setattr(
        backend,
        "_command",
        lambda executable, *_args: [
            str(executable),
            "-I",
            "-S",
            "-c",
            "import time; time.sleep(30)",
        ],
    )
    result = backend._probe_runtime(
        Path(sys.executable),
        backend._sha(Path(sys.executable)),
        tmp_path,
        import_check=False,
        timeout=0.2,
        cancelled=(lambda: True) if interrupt == "cancelled" else None,
    )
    assert result["status"] == "unavailable"
    assert result["error_code"] == (
        "RUNTIME_PROBE_CANCELLED"
        if interrupt == "cancelled"
        else "RUNTIME_PROBE_TIMEOUT"
    )
    assert len(processes) == 1 and processes[0].poll() is not None


@pytest.mark.parametrize("interrupt", ["cancelled", "timed_out"])
def test_training_interrupt_is_durable_and_stops_worker(
    tmp_path, monkeypatch, interrupt
):
    dataset = _dataset(tmp_path / "dataset")
    monkeypatch.setattr(
        backend,
        "_probe_runtime",
        lambda *_a, **_k: {
            "status": "ready",
            "runtime_sha256": "a" * 64,
        },
    )
    processes = []
    original = subprocess.Popen

    def start(*args, **kwargs):
        process = original(*args, **kwargs)
        processes.append(process)
        return process

    monkeypatch.setattr(subprocess, "Popen", start)
    monkeypatch.setattr(
        backend,
        "_command",
        lambda executable, *_args: [
            str(executable),
            "-I",
            "-S",
            "-c",
            "import time; time.sleep(30)",
        ],
    )
    result = backend.run_yolo_training(
        executable=Path(sys.executable),
        expected_executable_sha256=backend._sha(Path(sys.executable)),
        expected_runtime_sha256="a" * 64,
        dataset_root=dataset,
        output_root=tmp_path / "job",
        config=backend.YoloTrainingConfig(max_seconds=5),
        cancelled=(lambda: bool(processes)) if interrupt == "cancelled" else None,
    )
    assert result["status"] == interrupt
    assert result["elapsed_seconds"] < 8
    assert len(processes) == 1 and processes[0].poll() is not None
    assert "checkpoint" not in result
    assert json.loads((tmp_path / "job/result.json").read_text())["status"] == interrupt


@pytest.mark.slow
def test_explicit_actual_cpu_train_val_checkpoint(tmp_path):
    """Opt in with a named trusted interpreter; no weights/data downloads."""
    selected = os.environ.get("VDG_TEST_YOLO_EXECUTABLE")
    if not selected:
        pytest.skip("Explicit external runtime authorization required")
    executable = Path(selected)
    expected = os.environ["VDG_TEST_YOLO_EXECUTABLE_SHA256"]
    # Optional durable root is strictly new; no existing artifacts are replaced.
    evidence_root = os.environ.get("VDG_TEST_YOLO_EVIDENCE_ROOT")
    root = Path(evidence_root) if evidence_root else tmp_path
    if evidence_root:
        root.mkdir(parents=True, exist_ok=False)
    dataset = _dataset(root / "synthetic_dataset")
    receipt = backend.probe_vision_runtime(
        executable, expected, root / "probe", import_check=True
    )
    assert receipt["status"] == "ready", receipt
    assert receipt["import_status"] == "PASSED", receipt
    original_test = backend._sha(dataset / "images/test/0.png")
    trusted_initial = os.environ.get("VDG_TEST_YOLO_INITIAL_WEIGHTS")
    trusted_sha = os.environ.get("VDG_TEST_YOLO_INITIAL_WEIGHTS_SHA256")
    result = backend.run_yolo_training(
        executable=executable,
        expected_executable_sha256=expected,
        expected_runtime_sha256=receipt["runtime_sha256"],
        dataset_root=dataset,
        output_root=root / "job",
        config=backend.YoloTrainingConfig(max_seconds=120),
        initial_weights=Path(trusted_initial) if trusted_initial else None,
        expected_weights_sha256=trusted_sha,
    )
    assert result["status"] == "completed", result
    assert result["actual_epochs"] == 1
    assert result["validation_samples"] == 2
    assert result["training_samples"] == 4
    assert result["checkpoint"]["round_trip"] == "VERIFIED"
    assert result["baseline_initialization_match"] == "VERIFIED"
    assert result["candidate_parameter_sha256"] != result["initial_parameter_sha256"]
    assert result["training_losses"] and all(result["training_losses"])
    checkpoint = root / "job" / result["checkpoint"]["relative_path"]
    assert (
        hashlib.sha256(checkpoint.read_bytes()).hexdigest()
        == result["checkpoint"]["sha256"]
    )
    assert not (root / "job/dataset/images/test").exists()
    assert backend._sha(dataset / "images/test/0.png") == original_test
    assert not result["production_approved"]
    assert result["gpu_status"] == "GPU_NOT_RUN"
    assert result["initialization"] == (
        "trusted_local_weights" if trusted_initial else "random"
    )
    assert "baseline" in result and "candidate" in result
    protocol = result["validation_feedback_protocol"]
    assert protocol["dataset_sha256"] == result["dataset_sha256"]
    assert protocol["runtime_sha256"] == result["runtime_sha256"]
    assert protocol["checkpoint_sha256"] == result["checkpoint"]["sha256"]
    assert protocol["sample_count"] == result["validation_samples"]
    details = result["validation_samples_detail"]
    assert {row["sample_id"] for row in details} == {"0", "1"}
    assert len(details) == result["validation_samples"]
    for row in details:
        assert row["image_sha256"] == backend._sha(
            dataset / f"images/val/{row['sample_id']}.png"
        )
        assert row["label_sha256"] == backend._sha(
            dataset / f"labels/val/{row['sample_id']}.txt"
        )
        assert row["tp"] + row["fp"] == len(row["prediction_boxes"])
        assert row["tp"] + row["fn"] == len(row["ground_truth_boxes"])
        assert row["review_required"] is True
    assert {row["sample_id"] for row in result["validation_feedback_candidates"]} == {
        row["sample_id"] for row in details if row["fp"] or row["fn"]
    }
