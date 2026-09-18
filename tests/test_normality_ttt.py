"""Real CPU-gradient tests plus dependency-free TTT boundary contracts."""

from __future__ import annotations

import importlib
import importlib.util
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys

import pytest


def _engine():
    assert importlib.util.find_spec("visiondata_gate.normality_ttt") is not None, (
        "bounded real-gradient TTT engine is missing"
    )
    return importlib.import_module("visiondata_gate.normality_ttt")


@pytest.fixture
def tensor_case():
    torch = pytest.importorskip("torch")
    torch.set_num_threads(1)
    torch.manual_seed(17)
    students = torch.nn.ModuleDict({"4": torch.nn.Conv2d(2, 2, 1)})
    with torch.no_grad():
        students["4"].weight.zero_()
        students["4"].bias.zero_()
    loaded = {
        "_torch": torch,
        "_students": students,
        "_backbone": torch.nn.Conv2d(2, 2, 1),
    }
    adaptation = [{"4": torch.ones(1, 2, 4, 4)}]
    replay = [{"4": torch.full((1, 2, 4, 4), 0.25)}]
    normal = {"4": torch.full((1, 2, 4, 4), 0.1)}
    anomaly = {"4": torch.full((1, 2, 4, 4), 4.0)}

    def evaluate(candidate):
        matrix = {"tp": 0, "tn": 0, "fp": 0, "fn": 0}
        with torch.no_grad():
            for features, truth in ((normal, False), (anomaly, True)):
                score = (candidate["4"](features["4"]) - features["4"]).square().mean()
                predicted = float(score) >= 1.0
                key = (
                    ("tp" if predicted else "fn")
                    if truth
                    else ("fp" if predicted else "tn")
                )
                matrix[key] += 1
        return matrix

    return loaded, adaptation, replay, evaluate


def test_real_gradient_update_and_frozen_parent(tensor_case):
    engine = _engine()
    loaded, adaptation, replay, evaluate = tensor_case
    before = engine.parameter_digest(loaded["_students"])
    report, selected = engine.run_tensor_episode(
        loaded,
        adaptation,
        replay,
        evaluate,
        {"steps": 3, "learning_rate": 0.01, "max_seconds": 30, "seed": 7},
    )
    assert report["status"] == "ACCEPTED_EPISODIC"
    assert report["steps_completed"] == 3
    assert report["parameter_sha256_before"] != report["parameter_sha256_after"]
    assert report["parameter_sha256_before"] == before
    assert engine.parameter_digest(loaded["_students"]) == before
    assert engine.parameter_digest(selected) == report["parameter_sha256_after"]
    assert report["backbone_sha256_before"] == report["backbone_sha256_after"]
    assert all(parameter.grad is None for parameter in loaded["_backbone"].parameters())
    assert all(row["gradient_norm"] > 0 for row in report["loss_curve"])
    assert (
        report["loss_curve"][-1]["reconstruction_loss"]
        < (report["loss_curve"][0]["reconstruction_loss"])
    )
    assert report["guard_before"] == report["guard_after"]
    assert report["reset_after_episode"] and not report["persistent_learning"]


def test_episodes_restart_identically(tensor_case):
    loaded, adaptation, replay, evaluate = tensor_case
    engine = _engine()
    args = (
        loaded,
        adaptation,
        replay,
        evaluate,
        {"steps": 2, "learning_rate": 0.01, "max_seconds": 30, "seed": 7},
    )
    first, _ = engine.run_tensor_episode(*args)
    second, _ = engine.run_tensor_episode(*args)
    assert first["parameter_sha256_after"] == second["parameter_sha256_after"]
    assert first["loss_curve"] == second["loss_curve"]


def test_guard_regression_rolls_back_real_candidate(tensor_case):
    loaded, adaptation, replay, _ = tensor_case
    engine = _engine()
    before = engine.parameter_digest(loaded["_students"])

    def evaluate(candidate):
        return {
            "tp": 1,
            "fn": 0,
            "tn": int(engine.parameter_digest(candidate) == before),
            "fp": int(engine.parameter_digest(candidate) != before),
        }

    report, selected = engine.run_tensor_episode(
        loaded,
        adaptation,
        replay,
        evaluate,
        {"steps": 1, "learning_rate": 0.01, "max_seconds": 30, "seed": 7},
    )
    assert report["status"] == "ROLLED_BACK"
    assert report["rollback_reason"] == "TTT_GUARD_REGRESSION"
    assert report["parameter_sha256_after"] != before
    assert engine.parameter_digest(selected) == before


@pytest.mark.parametrize(
    "key,value",
    [
        ("steps", 0),
        ("steps", 9),
        ("learning_rate", float("nan")),
        ("max_seconds", 121),
        ("seed", True),
    ],
)
def test_invalid_budget_rejected(key, value):
    budget = {"steps": 2, "learning_rate": 0.001, "max_seconds": 30, "seed": 7}
    budget[key] = value
    with pytest.raises(ValueError, match="TTT_BUDGET_INVALID"):
        _engine().validate_budget(budget)


def test_nonfinite_input_rolls_back(tensor_case):
    loaded, adaptation, replay, evaluate = tensor_case
    adaptation[0]["4"][0, 0, 0, 0] = float("nan")
    report, selected = _engine().run_tensor_episode(
        loaded,
        adaptation,
        replay,
        evaluate,
        {"steps": 2, "learning_rate": 0.01, "max_seconds": 30, "seed": 7},
    )
    assert report["rollback_reason"] == "TTT_NONFINITE_INPUT"
    assert report["steps_completed"] == 0
    assert selected is loaded["_students"]


def _samples():
    def item(key, **extra):
        return {
            "path": key + ".png",
            "sha256": key * 64,
            "image_format": "png",
            **extra,
        }

    return (
        [item("a")],
        [item("b", reference_label="normal", reference_source="human")],
        [
            item("c", reference_label="normal", reference_source="human"),
            item("d", reference_label="anomaly", reference_source="human"),
        ],
    )


def test_split_contamination_and_nonhuman_guard_rejected():
    engine = _engine()
    adaptation, replay, guard = _samples()
    engine.validate_splits(adaptation, replay, guard, "a" * 64)
    guard[0]["sha256"] = adaptation[0]["sha256"]
    with pytest.raises(ValueError, match="TTT_SPLIT_OVERLAP"):
        engine.validate_splits(adaptation, replay, guard, "a" * 64)
    adaptation, replay, guard = _samples()
    guard[0]["reference_source"] = "pseudo"
    with pytest.raises(ValueError, match="TTT_HUMAN_GUARD_REQUIRED"):
        engine.validate_splits(adaptation, replay, guard, "a" * 64)


def test_guard_must_have_both_classes():
    adaptation, replay, guard = _samples()
    guard[1]["reference_label"] = "normal"
    with pytest.raises(ValueError, match="TTT_BOTH_GUARD_CLASSES_REQUIRED"):
        _engine().validate_splits(adaptation, replay, guard, "a" * 64)


def test_guard_labels_are_not_allowed_in_adaptation():
    adaptation, replay, guard = _samples()
    adaptation[0]["reference_label"] = "normal"
    with pytest.raises(ValueError, match="TTT_SAMPLE_CONTRACT_INVALID"):
        _engine().validate_splits(adaptation, replay, guard, "a" * 64)


def test_time_budget_rolls_back_without_updates(tensor_case):
    loaded, adaptation, replay, evaluate = tensor_case
    ticks = iter([0.0, 6.0, 7.0])
    report, selected = _engine().run_tensor_episode(
        loaded,
        adaptation,
        replay,
        evaluate,
        {"steps": 1, "learning_rate": 0.01, "max_seconds": 5, "seed": 7},
        clock=lambda: next(ticks),
    )
    assert report["rollback_reason"] == "TTT_TIME_BUDGET_EXCEEDED"
    assert report["steps_completed"] == 0
    assert selected is loaded["_students"]


def test_import_does_not_import_torch():
    root = Path(__file__).resolve().parents[1]
    result = subprocess.run(
        [
            sys.executable,
            "-c",
            "import sys; sys.path.insert(0, 'src'); "
            "from visiondata_gate import normality_ttt; "
            "assert 'torch' not in sys.modules",
        ],
        cwd=root,
        capture_output=True,
    )
    assert result.returncode == 0, result.stderr


def test_worker_mode_supports_ttt(tmp_path, monkeypatch):
    from visiondata_gate import normality_inference

    monkeypatch.setattr(normality_inference, "_package_paths", lambda: None)
    monkeypatch.setattr(normality_inference, "_deny_network_and_children", lambda: None)
    monkeypatch.setattr(
        _engine(), "child_ttt", lambda request: {"status": "completed"}, raising=False
    )
    request = tmp_path / "request.json"
    request.write_text("{}", encoding="utf-8")
    result = tmp_path / "result.json"
    assert (
        normality_inference._worker_main(["worker", "ttt", str(request), str(result)])
        == 0
    )
    assert result.is_file()


def test_wrapper_rejects_split_pollution_before_launch(tmp_path):
    adaptation, replay, guard = _samples()
    guard[0]["sha256"] = adaptation[0]["sha256"]
    assert hasattr(_engine(), "run_normality_ttt"), "external TTT wrapper is missing"
    with pytest.raises(ValueError, match="TTT_SPLIT_OVERLAP"):
        _engine().run_normality_ttt(
            executable=tmp_path / "python",
            expected_executable_sha256="f" * 64,
            expected_runtime_sha256="f" * 64,
            model_pack=tmp_path / "pack.pt",
            expected_model_pack_sha256="f" * 64,
            expected_backbone_weights_sha256="f" * 64,
            expected_source_binding_sha256="f" * 64,
            expected_source_index_sha256="f" * 64,
            image=tmp_path / "a.png",
            image_format="png",
            expected_image_sha256="a" * 64,
            adaptation_images=adaptation,
            replay_images=replay,
            guard_images=guard,
            budget={"steps": 1, "learning_rate": 0.001, "max_seconds": 10, "seed": 7},
            output_root=tmp_path / "out",
        )


def test_extract_features_is_frozen_and_rejects_bad_image(tmp_path, tensor_case):
    engine = _engine()
    assert hasattr(engine, "extract_features"), (
        "image-to-frozen-features adapter missing"
    )
    loaded, *_ = tensor_case
    bad = tmp_path / "bad.png"
    bad.write_bytes(b"not an image")
    sample = {
        "path": str(bad),
        "image_format": "png",
        "sha256": hashlib.sha256(bad.read_bytes()).hexdigest(),
    }
    with pytest.raises(ValueError, match="TTT_IMAGE_INVALID"):
        engine.extract_features(loaded, sample)


def test_query_must_train_and_replay_must_be_normal():
    engine = _engine()
    adaptation, replay, guard = _samples()
    with pytest.raises(ValueError, match="TTT_QUERY_MUST_PARTICIPATE"):
        engine.validate_splits(adaptation, replay, guard, "e" * 64)
    replay[0]["reference_label"] = "anomaly"
    with pytest.raises(ValueError, match="TTT_NORMAL_REPLAY_REQUIRED"):
        engine.validate_splits(adaptation, replay, guard, "a" * 64)


def test_nonfinite_gradient_rolls_back(tensor_case):
    loaded, adaptation, replay, evaluate = tensor_case

    torch = loaded["_torch"]

    # A finite forward with a deliberately nonfinite parameter gradient.
    class BadGradient(torch.autograd.Function):
        @staticmethod
        def forward(ctx, value):
            return value.clone()

        @staticmethod
        def backward(ctx, gradient):
            return gradient * float("nan")

    class BadStudent(torch.nn.Conv2d):
        def forward(self, value):
            return BadGradient.apply(super().forward(value))

    loaded["_students"] = torch.nn.ModuleDict({"4": BadStudent(2, 2, 1)})
    report, selected = _engine().run_tensor_episode(
        loaded,
        adaptation,
        replay,
        evaluate,
        {"steps": 2, "learning_rate": 0.001, "max_seconds": 30, "seed": 7},
    )
    assert report["rollback_reason"] == "TTT_NONFINITE_GRADIENT"
    assert report["steps_completed"] == 0
    assert selected is loaded["_students"]


def test_oversized_features_rejected(tensor_case):
    loaded, _, replay, evaluate = tensor_case
    torch = loaded["_torch"]
    oversized = [{"4": torch.ones(1).expand(1, 2, 4096, 2048)}]
    report, _ = _engine().run_tensor_episode(
        loaded,
        oversized,
        replay,
        evaluate,
        {"steps": 2, "learning_rate": 0.001, "max_seconds": 30, "seed": 7},
    )
    assert report["rollback_reason"] == "TTT_FEATURE_BUDGET_EXCEEDED"


def test_unknown_runtime_error_does_not_leak_local_path(tensor_case):
    loaded, adaptation, replay, _ = tensor_case

    def broken_guard(_students):
        raise RuntimeError("C:/private/customer/secret.png cannot load")

    report, _ = _engine().run_tensor_episode(
        loaded,
        adaptation,
        replay,
        broken_guard,
        {"steps": 2, "learning_rate": 0.001, "max_seconds": 30, "seed": 7},
    )
    assert report["rollback_reason"] == "TTT_RUNTIME_ERROR"


def test_extracts_real_features_with_no_backbone_gradient(tmp_path, tensor_case):
    from PIL import Image

    loaded, *_ = tensor_case
    torch = loaded["_torch"]

    class Backbone(torch.nn.Module):
        def __init__(self):
            super().__init__()
            self.model = torch.nn.Sequential(torch.nn.Conv2d(3, 2, 1))

        def forward(self, value):
            return self.model(value)

    loaded.update(_backbone=Backbone(), feature_layers=[0], image_size=8)
    path = tmp_path / "valid.png"
    Image.new("RGB", (8, 8), (90, 30, 20)).save(path)
    features = _engine().extract_features(
        loaded,
        {
            "path": str(path),
            "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
            "image_format": "png",
        },
    )
    assert features["0"].shape == (1, 2, 8, 8)
    assert not features["0"].requires_grad
    assert not features["0"].is_inference()
    assert all(
        not parameter.requires_grad for parameter in loaded["_backbone"].parameters()
    )


@pytest.mark.parametrize(
    "threshold,status", [(0.22, "ACCEPTED_EPISODIC"), (0.275, "ROLLED_BACK")]
)
def test_child_uses_real_images_guards_and_selected_heatmap(
    tmp_path, monkeypatch, tensor_case, threshold, status
):
    from PIL import Image
    from visiondata_gate import normality_inference as backend

    torch = tensor_case[0]["_torch"]

    class Backbone(torch.nn.Module):
        def __init__(self):
            super().__init__()
            self.model = torch.nn.Sequential(torch.nn.Conv2d(3, 3, 1, bias=False))
            with torch.no_grad():
                self.model[0].weight.copy_(torch.eye(3).reshape(3, 3, 1, 1))

        def forward(self, value):
            return self.model(value)

    students = torch.nn.ModuleDict({"0": torch.nn.Conv2d(3, 3, 1)})
    with torch.no_grad():
        students["0"].weight.zero_()
        students["0"].bias.zero_()
    loaded = {
        "_torch": torch,
        "_students": students,
        "_backbone": Backbone(),
        "image_size": 8,
        "feature_layers": [0],
        "selected_image_aggregation": "mean",
        "image_threshold": threshold,
        "pixel_threshold": threshold,
        "input_normalization": {"mean": [0, 0, 0], "std": [1, 1, 1]},
        "_pack": {
            "normalizers": {
                "0": {
                    "normal_reference_mean": torch.full((1, 3, 1, 1), 3**-0.5),
                    "normal_reference_variance": torch.ones(1),
                    "reconstruction_mean": torch.zeros(1),
                    "reconstruction_std": torch.ones(1),
                    "gaussian_mean": torch.zeros(1),
                    "gaussian_std": torch.ones(1),
                }
            }
        },
    }

    def sample(name, color, label=None):
        path = tmp_path / (name + ".png")
        Image.new("RGB", (8, 8), color).save(path)
        value = {"path": str(path), "sha256": backend._sha(path), "image_format": "png"}
        if label is not None:
            value.update(reference_label=label, reference_source="human")
        return value

    query = sample("query", (100, 40, 30))
    replay = sample("replay", (30, 30, 30), "normal")
    guard = [
        sample("normal", (10, 10, 10), "normal"),
        sample("anomaly", (240, 20, 20), "anomaly"),
    ]
    pack = tmp_path / "parent.pt"
    pack.write_bytes(b"synthetic pack identity; real tensor loader supplied by fixture")
    baseline_scores = []

    def baseline_infer(request):
        scored = backend._score_normality_image(
            loaded,
            Path(request["image_path"]),
            request["image_sha256"],
            Path(request["heatmap_path"]),
        )
        baseline_scores.append(scored)
        return dict(scored, status="completed")

    monkeypatch.setattr(backend, "_child_infer", baseline_infer)
    monkeypatch.setattr(backend, "_load_normality_pack", lambda *args: loaded)
    result = _engine().child_ttt(
        {
            "image_path": query["path"],
            "image_sha256": query["sha256"],
            "heatmap_path": str(tmp_path / "out" / "artifacts" / "heatmap.png"),
            "model_pack_path": str(pack),
            "model_pack_sha256": backend._sha(pack),
            "backbone_weights_sha256": "f" * 64,
            "ttt_backend_sha256": backend._sha(Path(_engine().__file__)),
            "adaptation_images": [query],
            "replay_images": [replay],
            "guard_images": guard,
            "budget": {"steps": 3, "learning_rate": 0.01, "max_seconds": 30, "seed": 7},
        }
    )
    report = result["ttt"]
    assert report["status"] == status
    assert report["steps_completed"] == 3
    assert report["guard_before"] == {"tp": 1, "tn": 1, "fp": 0, "fn": 0}
    assert report["attempted_parameter_sha256"] != report["parameter_sha256_before"]
    assert (
        backend._sha(tmp_path / "out" / "artifacts" / "heatmap.png")
        == result["heatmap_sha256"]
    )
    if status == "ROLLED_BACK":
        assert result["image_score"] == baseline_scores[0]["image_score"]
        assert result["heatmap_sha256"] == baseline_scores[0]["heatmap_sha256"]
        assert report["rollback_reason"] == "TTT_GUARD_REGRESSION"
        assert report["guard_after"]["fn"] == 1


def test_reencoded_duplicate_pixels_cannot_cross_roles(tmp_path):
    from PIL import Image

    engine = _engine()
    assert hasattr(engine, "validate_pixel_isolation"), "decoded RGB isolation missing"
    left, right = tmp_path / "left.png", tmp_path / "right.png"
    pixels = Image.new("RGB", (8, 8), (123, 45, 67))
    pixels.save(left, compress_level=0)
    pixels.save(right, compress_level=9)
    records = [
        {
            "path": str(path),
            "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
            "image_format": "png",
        }
        for path in (left, right)
    ]
    assert records[0]["sha256"] != records[1]["sha256"]
    with pytest.raises(ValueError, match="TTT_DECODED_PIXEL_OVERLAP"):
        engine.validate_pixel_isolation([records[0]], [records[1]], [])


def test_isolated_external_worker_loads_exact_sibling_without_application(tmp_path):
    from visiondata_gate import normality_inference as backend

    request = tmp_path / "request.json"
    result = tmp_path / "result.json"
    request.write_text("{}", encoding="utf-8")
    command = backend._worker_command(Path(sys.executable), "ttt", request, result)
    completed = subprocess.run(
        command,
        cwd=tmp_path,
        env=backend._child_environment(tmp_path / "environment"),
        capture_output=True,
    )
    assert completed.returncode == 1, completed.stderr
    receipt = json.loads(result.read_text(encoding="utf-8"))
    assert receipt["error_code"] == "TTT_REQUEST_INVALID"


@pytest.mark.parametrize("normal_value,anomaly_value", [(0.1, 0.2), (4.0, 5.0)])
def test_unqualified_baseline_guard_prevents_update(
    tensor_case, normal_value, anomaly_value
):
    loaded, adaptation, replay, _ = tensor_case
    torch = loaded["_torch"]

    def actual_guard(candidate):
        matrix = {"tp": 0, "tn": 0, "fp": 0, "fn": 0}
        with torch.no_grad():
            for value, truth in ((normal_value, False), (anomaly_value, True)):
                feature = torch.full((1, 2, 4, 4), value)
                predicted = (
                    float((candidate["4"](feature) - feature).square().mean()) >= 1
                )
                matrix[
                    ("tp" if predicted else "fn")
                    if truth
                    else ("fp" if predicted else "tn")
                ] += 1
        return matrix

    report, selected = _engine().run_tensor_episode(
        loaded,
        adaptation,
        replay,
        actual_guard,
        {"steps": 3, "learning_rate": 0.01, "max_seconds": 30, "seed": 7},
    )
    assert report["status"] == "ROLLED_BACK"
    assert report["rollback_reason"] == "TTT_GUARD_BASELINE_UNQUALIFIED"
    assert report["steps_completed"] == 0
    assert report["guard_after"] is None
    assert selected is loaded["_students"]
    assert report["guard_policy"] == {
        "min_true_positive": 1,
        "min_true_negative": 1,
        "max_fp_increase": 0,
        "max_fn_increase": 0,
    }


def test_worker_username_is_synthetic_without_inheriting_personal_environment(
    tmp_path, monkeypatch
):
    from visiondata_gate import normality_inference as backend

    for key in ("LOGNAME", "USER", "LNAME", "USERNAME"):
        monkeypatch.setenv(key, "private-test-user-never-forward")
    snapshot = dict(os.environ)
    environment = backend._child_environment(tmp_path / "isolated")
    assert environment.get("USERNAME") == "visiondata-worker"
    assert not {"LOGNAME", "USER", "LNAME"} & environment.keys()
    assert "private-test-user-never-forward" not in environment.values()
    assert dict(os.environ) == snapshot
    assert environment["CUDA_VISIBLE_DEVICES"] == ""


def test_real_sgd_under_actual_isolated_worker_environment(tmp_path):
    from visiondata_gate import normality_inference as backend

    external = os.environ.get("VISIONDATA_TEST_TORCH_PYTHON", sys.executable)
    if external == sys.executable and importlib.util.find_spec("torch") is None:
        pytest.skip("explicit external Torch runtime required for gradient smoke")
    script = """
import getpass, importlib.util, json, socket, subprocess, sys
spec = importlib.util.spec_from_file_location('worker_backend', sys.argv[1])
backend = importlib.util.module_from_spec(spec)
spec.loader.exec_module(backend)
backend._package_paths()
backend._deny_network_and_children()
import torch
torch.set_num_threads(1)
parameter = torch.nn.Parameter(torch.tensor([1.0], device='cpu'))
optimizer = torch.optim.SGD([parameter], lr=0.1)
optimizer.zero_grad()
loss = (parameter - 3.0).square().sum()
loss.backward()
optimizer.step()
assert parameter.item() > 1.0
assert getpass.getuser() == 'visiondata-worker'
for action in (
    lambda: socket.getaddrinfo('localhost', 80),
    lambda: subprocess.run([sys.executable, '-c', 'pass']),
):
    try:
        action()
    except OSError as error:
        assert str(error) == 'NORMALITY_NETWORK_OR_CHILD_PROCESS_DISABLED'
    else:
        raise AssertionError('isolation unexpectedly weakened')
print(json.dumps({'parameter_after': parameter.item(), 'torch': torch.__version__,
                  'username': getpass.getuser(), 'device': parameter.device.type}))
"""
    completed = subprocess.run(
        [
            external,
            "-B",
            "-I",
            "-S",
            "-c",
            script,
            str(Path(backend.__file__).resolve()),
        ],
        env=backend._child_environment(tmp_path / "isolated"),
        cwd=tmp_path,
        capture_output=True,
        text=True,
        timeout=90,
    )
    assert completed.returncode == 0, completed.stderr
    receipt = json.loads(completed.stdout)
    assert receipt["device"] == "cpu"
    assert receipt["parameter_after"] > 1.0


@pytest.mark.parametrize("steps", [1, 3])
def test_last_optimizer_step_worsening_rolls_back_on_final_objective(
    tensor_case, monkeypatch, steps
):
    loaded, adaptation, replay, evaluate = tensor_case
    torch = loaded["_torch"]
    original_step = torch.optim.SGD.step
    calls = 0

    def faulty_final_step(optimizer, *args, **kwargs):
        nonlocal calls
        result = original_step(optimizer, *args, **kwargs)
        calls += 1
        if calls == steps:
            with torch.no_grad():
                for group in optimizer.param_groups:
                    for parameter in group["params"]:
                        if parameter.ndim == 1:
                            parameter.fill_(-0.2)
        return result

    monkeypatch.setattr(torch.optim.SGD, "step", faulty_final_step)
    report, selected = _engine().run_tensor_episode(
        loaded,
        adaptation,
        replay,
        evaluate,
        {"steps": steps, "learning_rate": 0.01, "max_seconds": 30, "seed": 7},
    )
    assert report["status"] == "ROLLED_BACK"
    assert report["rollback_reason"] == "TTT_FINAL_OBJECTIVE_NOT_IMPROVED"
    assert report["steps_completed"] == steps
    assert report["objective_after"] >= report["objective_before"]
    assert selected is loaded["_students"]
    if steps > 1:
        assert report["loss_curve"][-1]["loss"] < report["loss_curve"][0]["loss"]


def test_single_step_measures_post_update_objective(tensor_case):
    loaded, adaptation, replay, evaluate = tensor_case
    report, _ = _engine().run_tensor_episode(
        loaded,
        adaptation,
        replay,
        evaluate,
        {"steps": 1, "learning_rate": 0.01, "max_seconds": 30, "seed": 7},
    )
    assert report["status"] == "ACCEPTED_EPISODIC"
    assert report.get("objective_after") is not None, (
        "post-update objective is unmeasured"
    )
    assert report["objective_after"] < report["objective_before"]
    assert report["objective_before"] == report["loss_curve"][0]["loss"]


def test_zero_step_has_no_invented_final_objective(tensor_case):
    loaded, adaptation, replay, _ = tensor_case
    report, _ = _engine().run_tensor_episode(
        loaded,
        adaptation,
        replay,
        lambda _: {"tp": 0, "tn": 1, "fp": 0, "fn": 1},
        {"steps": 1, "learning_rate": 0.01, "max_seconds": 30, "seed": 7},
    )
    assert "objective_before" in report and "objective_after" in report
    assert report["objective_before"] is None and report["objective_after"] is None


def test_partial_update_failure_preserves_only_measured_initial_objective(
    tensor_case, monkeypatch
):
    loaded, adaptation, replay, evaluate = tensor_case
    torch = loaded["_torch"]
    original_step = torch.optim.SGD.step
    calls = 0

    def fail_second_step(optimizer, *args, **kwargs):
        nonlocal calls
        calls += 1
        if calls == 2:
            raise RuntimeError("synthetic optimizer boundary failure")
        return original_step(optimizer, *args, **kwargs)

    monkeypatch.setattr(torch.optim.SGD, "step", fail_second_step)
    report, selected = _engine().run_tensor_episode(
        loaded,
        adaptation,
        replay,
        evaluate,
        {"steps": 3, "learning_rate": 0.01, "max_seconds": 30, "seed": 7},
    )
    assert report["status"] == "ROLLED_BACK"
    assert report["steps_completed"] == 1
    assert report["objective_before"] == 1.0
    assert report["objective_after"] is None
    assert selected is loaded["_students"]


def test_nonfinite_final_objective_is_not_serialized_as_a_number(
    tensor_case, monkeypatch
):
    loaded, adaptation, replay, evaluate = tensor_case
    torch = loaded["_torch"]
    original_step = torch.optim.SGD.step

    def overflow_objective(optimizer, *args, **kwargs):
        result = original_step(optimizer, *args, **kwargs)
        with torch.no_grad():
            for group in optimizer.param_groups:
                for parameter in group["params"]:
                    if parameter.ndim == 1:
                        parameter.fill_(
                            1e20
                        )  # finite parameter, overflowing squared loss
        return result

    monkeypatch.setattr(torch.optim.SGD, "step", overflow_objective)
    report, _ = _engine().run_tensor_episode(
        loaded,
        adaptation,
        replay,
        evaluate,
        {"steps": 1, "learning_rate": 0.01, "max_seconds": 30, "seed": 7},
    )
    assert report["rollback_reason"] == "TTT_NONFINITE_FINAL_OBJECTIVE"
    assert report["steps_completed"] == 1
    assert report["objective_before"] == 1.0
    assert report["objective_after"] is None
    json.dumps(report, allow_nan=False)
