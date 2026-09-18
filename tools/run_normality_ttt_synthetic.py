"""Reproduce CPU tensor-only TTT evidence; never claims factory effectiveness.

Run with an explicitly selected existing torch interpreter, e.g.:
  python tools/run_normality_ttt_synthetic.py
No weights, data, network, CUDA, package installation or persistent update.
"""

from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import sys
import subprocess
import tempfile


def _require(condition: bool, error_code: str) -> None:
    """Never remove evidence checks when Python optimization is enabled."""
    if not condition:
        raise RuntimeError(error_code)


def _validate_episodes(
    *,
    accepted,
    repeated,
    rejected,
    selected_digest,
    parent_before,
    parent_after,
    unqualified,
) -> None:
    _require(
        accepted["status"] == "ACCEPTED_EPISODIC", "TTT_SYNTHETIC_EXPECTED_ACCEPTED"
    )
    _require(
        accepted["objective_after"] < accepted["objective_before"],
        "TTT_SYNTHETIC_OBJECTIVE_NOT_IMPROVED",
    )
    _require(
        repeated["attempted_parameter_sha256"]
        == accepted["attempted_parameter_sha256"],
        "TTT_SYNTHETIC_REPEAT_MISMATCH",
    )
    _require(
        rejected["rollback_reason"] == "TTT_GUARD_REGRESSION",
        "TTT_SYNTHETIC_EXPECTED_GUARD_ROLLBACK",
    )
    _require(
        selected_digest == parent_before == parent_after, "TTT_SYNTHETIC_PARENT_CHANGED"
    )
    _require(
        accepted["backbone_sha256_before"] == accepted["backbone_sha256_after"],
        "TTT_SYNTHETIC_BACKBONE_CHANGED",
    )
    for episode in unqualified:
        _require(
            episode["rollback_reason"] == "TTT_GUARD_BASELINE_UNQUALIFIED",
            "TTT_SYNTHETIC_EXPECTED_UNQUALIFIED_GUARD",
        )
        _require(episode["steps_completed"] == 0, "TTT_SYNTHETIC_UNQUALIFIED_UPDATED")
        _require(
            episode["objective_before"] is None,
            "TTT_SYNTHETIC_UNMEASURED_OBJECTIVE_PRESENT",
        )
        _require(
            episode["objective_after"] is None,
            "TTT_SYNTHETIC_UNMEASURED_OBJECTIVE_PRESENT",
        )


def _validate_bootstrap(returncode: int, receipt: dict) -> None:
    _require(
        returncode == 1 and receipt.get("error_code") == "TTT_REQUEST_INVALID",
        "TTT_SYNTHETIC_BOOTSTRAP_MISMATCH",
    )


def main() -> int:
    os.environ["CUDA_VISIBLE_DEVICES"] = ""
    sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
    import torch
    from visiondata_gate.normality_ttt import parameter_digest, run_tensor_episode
    from visiondata_gate import normality_inference

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
    budget = {"steps": 3, "learning_rate": 0.01, "max_seconds": 30, "seed": 7}

    def guard_evaluator(anomaly_value, threshold):
        def evaluate(candidate):
            matrix = {"tp": 0, "tn": 0, "fp": 0, "fn": 0}
            with torch.no_grad():
                for value, truth in ((0.1, False), (anomaly_value, True)):
                    features = torch.full((1, 2, 4, 4), value)
                    score = float((candidate["4"](features) - features).square().mean())
                    predicted = score >= threshold
                    if truth:
                        matrix["tp" if predicted else "fn"] += 1
                    else:
                        matrix["fp" if predicted else "tn"] += 1
            return matrix

        return evaluate

    parent_before = parameter_digest(students)
    accepted, _ = run_tensor_episode(
        loaded, adaptation, replay, guard_evaluator(4.0, 1.0), budget
    )
    repeated, _ = run_tensor_episode(
        loaded, adaptation, replay, guard_evaluator(4.0, 1.0), budget
    )
    rejected, selected = run_tensor_episode(
        loaded, adaptation, replay, guard_evaluator(0.8, 0.63), budget
    )
    missed_guard, _ = run_tensor_episode(
        loaded, adaptation, replay, guard_evaluator(0.2, 1.0), budget
    )
    false_positive_guard, _ = run_tensor_episode(
        loaded, adaptation, replay, guard_evaluator(4.0, 0.005), budget
    )
    _validate_episodes(
        accepted=accepted,
        repeated=repeated,
        rejected=rejected,
        selected_digest=parameter_digest(selected),
        parent_before=parent_before,
        parent_after=parameter_digest(students),
        unqualified=(missed_guard, false_positive_guard),
    )
    with tempfile.TemporaryDirectory(prefix="visiondata-ttt-bootstrap-") as temporary:
        work = Path(temporary)
        request_path, result_path = work / "request.json", work / "result.json"
        request_path.write_text("{}", encoding="utf-8")
        completed = subprocess.run(
            normality_inference._worker_command(
                Path(sys.executable), "ttt", request_path, result_path
            ),
            cwd=work,
            env=normality_inference._child_environment(work / "environment"),
            capture_output=True,
            timeout=30,
        )
        bootstrap = json.loads(result_path.read_text(encoding="utf-8"))
        _validate_bootstrap(completed.returncode, bootstrap)
    result = {
        "schema_version": "visiondata-gate.ttt-synthetic-experiment.v1",
        "evidence_scope": "CPU_SYNTHETIC_TENSOR_ALGORITHM_EXECUTION_ONLY",
        "factory_validated": False,
        "official_platform_validated": False,
        "runtime": {
            "python": sys.version.split()[0],
            "torch": torch.__version__,
            "device": "cpu",
            "threads": torch.get_num_threads(),
        },
        "implementation_sha256": hashlib.sha256(
            (
                Path(__file__).resolve().parents[1]
                / "src"
                / "visiondata_gate"
                / "normality_ttt.py"
            ).read_bytes()
        ).hexdigest(),
        "tensor_shapes": {"adaptation": [1, 2, 4, 4], "replay": [1, 2, 4, 4]},
        "accepted_episode": accepted,
        "guard_regression_episode": rejected,
        "all_anomalies_missed_baseline": missed_guard,
        "all_normals_false_positive_baseline": false_positive_guard,
        "repeat_same_seed_identical_parameters": True,
        "repeated_episode_parameter_sha256": repeated["attempted_parameter_sha256"],
        "external_worker_bootstrap": {
            "status": "EXPECTED_INVALID_REQUEST_REJECTION",
            "error_code": bootstrap["error_code"],
            "isolated_no_application_import": True,
            "full_yolo26_pack_execution": False,
        },
        "parent_parameters_unchanged": True,
    }
    print(json.dumps(result, indent=2, sort_keys=True, allow_nan=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
