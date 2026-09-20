"""CPU-only episodic student adaptation in an explicitly approved external runtime.

Importing this module does not import torch. No fitted state is written back to a
pack. Human guard labels are used only for the post-update acceptance gate.
"""

from __future__ import annotations

import copy
import hashlib
import math
from pathlib import Path
import shutil
import sys
import time


_ERROR_CODES = frozenset(
    {
        "TTT_TIME_BUDGET_EXCEEDED",
        "TTT_SAMPLE_BUDGET_INVALID",
        "TTT_FEATURE_CONTRACT_INVALID",
        "TTT_NONFINITE_INPUT",
        "TTT_FEATURE_BUDGET_EXCEEDED",
        "TTT_NONFINITE_LOSS",
        "TTT_NONFINITE_GRADIENT",
        "TTT_NO_VALID_GRADIENT",
        "TTT_NONFINITE_PARAMETER",
        "TTT_GUARD_METRICS_INVALID",
        "TTT_GUARD_DENOMINATOR_CHANGED",
        "TTT_GUARD_REGRESSION",
        "TTT_GUARD_BASELINE_UNQUALIFIED",
        "TTT_NO_PARAMETER_UPDATE",
        "TTT_LOSS_NOT_IMPROVED",
        "TTT_FINAL_OBJECTIVE_NOT_IMPROVED",
        "TTT_NONFINITE_FINAL_OBJECTIVE",
        "TTT_IMAGE_INVALID",
        "TTT_IMAGE_SHA_MISMATCH",
        "TTT_IMAGE_BUDGET_EXCEEDED",
        "NORMALITY_NONFINITE_SCORE_MAP",
        "NORMALITY_INPUT_IMAGE_SHA_MISMATCH",
    }
)

GUARD_POLICY = {
    "min_true_positive": 1,
    "min_true_negative": 1,
    "max_fp_increase": 0,
    "max_fn_increase": 0,
}


def _error_code(error: Exception) -> str:
    if isinstance(error, ValueError) and str(error) in _ERROR_CODES:
        return str(error)
    if isinstance(error, OSError):
        return "TTT_IMAGE_IO_ERROR"
    return (
        "TTT_RUNTIME_ERROR" if isinstance(error, RuntimeError) else "TTT_INVALID_INPUT"
    )


def _inference_module():
    if __package__:
        from . import normality_inference

        return normality_inference
    # Script worker loads this exact sibling without application dependencies.
    return sys.modules["__main__"]


def validate_budget(budget: dict) -> dict:
    if (
        not isinstance(budget, dict)
        or set(budget) != {"steps", "learning_rate", "max_seconds", "seed"}
        or type(budget["steps"]) is not int
        or not 1 <= budget["steps"] <= 8
        or type(budget["learning_rate"]) not in {int, float}
        or not math.isfinite(float(budget["learning_rate"]))
        or not 1e-5 <= float(budget["learning_rate"]) <= 1e-2
        or type(budget["max_seconds"]) is not int
        or not 5 <= budget["max_seconds"] <= 120
        or type(budget["seed"]) is not int
        or not 0 <= budget["seed"] < 2**31
    ):
        raise ValueError("TTT_BUDGET_INVALID")
    return dict(budget)


def validate_splits(
    adaptation: list, replay: list, guard: list, query_sha: str
) -> dict:
    """Require query participation and disjoint normal replay / human guard sets."""
    _valid_sha = _inference_module()._valid_sha

    identities = {}
    seen = set()
    base_keys = {"path", "sha256", "image_format"}
    for name, records, low, high in (
        ("adaptation", adaptation, 1, 8),
        ("replay", replay, 1, 8),
        ("guard", guard, 2, 16),
    ):
        if not isinstance(records, list) or not low <= len(records) <= high:
            raise ValueError("TTT_SAMPLE_BUDGET_INVALID")
        hashes = []
        for record in records:
            expected = (
                base_keys
                if name == "adaptation"
                else base_keys | {"reference_label", "reference_source"}
            )
            if (
                not isinstance(record, dict)
                or set(record) != expected
                or not isinstance(record["path"], str)
                or not record["path"]
                or not _valid_sha(record["sha256"])
                or record["image_format"] not in {"png", "jpg", "jpeg", "bmp"}
            ):
                raise ValueError("TTT_SAMPLE_CONTRACT_INVALID")
            if name != "adaptation" and record["reference_source"] != "human":
                raise ValueError("TTT_HUMAN_GUARD_REQUIRED")
            if name == "replay" and record["reference_label"] != "normal":
                raise ValueError("TTT_NORMAL_REPLAY_REQUIRED")
            if name == "guard" and record["reference_label"] not in {
                "normal",
                "anomaly",
            }:
                raise ValueError("TTT_HUMAN_GUARD_REQUIRED")
            if record["sha256"] in seen:
                raise ValueError("TTT_SPLIT_OVERLAP")
            hashes.append(record["sha256"])
            seen.add(record["sha256"])
        identities[name] = {"count": len(records), "sha256": hashes}
    if query_sha not in identities["adaptation"]["sha256"]:
        raise ValueError("TTT_QUERY_MUST_PARTICIPATE")
    if {row["reference_label"] for row in guard} != {"normal", "anomaly"}:
        raise ValueError("TTT_BOTH_GUARD_CLASSES_REQUIRED")
    return identities


def parameter_digest(module) -> str:
    """Hash actual tensor bytes, names, shapes and dtypes, not client assertions."""
    digest = hashlib.sha256()
    for name, value in sorted(module.state_dict().items()):
        tensor = value.detach().cpu().contiguous()
        digest.update(name.encode("utf-8"))
        digest.update(str(tensor.dtype).encode("ascii"))
        digest.update(str(tuple(tensor.shape)).encode("ascii"))
        digest.update(tensor.numpy().tobytes())
    return digest.hexdigest()


def validate_pixel_isolation(adaptation: list, replay: list, guard: list) -> None:
    """Reject byte-distinct encodings of identical decoded RGB images and size."""
    from PIL import Image

    backend = _inference_module()
    seen = set()
    for row in adaptation + replay + guard:
        path = backend._checked_file(
            Path(row["path"]), row["sha256"], "TTT_IMAGE_SHA_MISMATCH"
        )
        if path.stat().st_size > 64 * 1024 * 1024:
            raise ValueError("TTT_IMAGE_BUDGET_EXCEEDED")
        try:
            with Image.open(path) as opened:
                if opened.width * opened.height > 25_000_000:
                    raise ValueError("TTT_IMAGE_BUDGET_EXCEEDED")
                opened.verify()
            with Image.open(path) as opened:
                rgb = opened.convert("RGB")
                digest = hashlib.sha256(
                    f"RGB:{rgb.width}:{rgb.height}:".encode("ascii") + rgb.tobytes()
                ).hexdigest()
        except (OSError, SyntaxError) as error:
            raise ValueError("TTT_IMAGE_INVALID") from error
        if backend._sha(path) != row["sha256"]:
            raise ValueError("TTT_IMAGE_SHA_MISMATCH")
        if digest in seen:
            raise ValueError("TTT_DECODED_PIXEL_OVERLAP")
        seen.add(digest)


def _matrix(value: dict) -> dict:
    if (
        not isinstance(value, dict)
        or set(value) != {"tp", "tn", "fp", "fn"}
        or any(type(v) is not int or v < 0 for v in value.values())
        or value["tp"] + value["fn"] < 1
        or value["tn"] + value["fp"] < 1
    ):
        raise ValueError("TTT_GUARD_METRICS_INVALID")
    return dict(value)


def run_tensor_episode(
    loaded: dict,
    adaptation: list,
    replay: list,
    guard_evaluator,
    budget: dict,
    *,
    clock=time.monotonic,
):
    """Real SGD on cloned students; the callback evaluates independent guard data.

    This internal worker-only entry point accepts frozen features, not labels.
    Masked reconstruction + frozen-teacher replay + parameter anchoring are
    optimized. The parent student and backbone tensor bytes are never mutated.
    """
    budget = validate_budget(budget)
    torch = loaded["_torch"]
    baseline = loaded["_students"]
    backbone = loaded["_backbone"]
    backbone.eval().requires_grad_(False)
    candidate = copy.deepcopy(baseline).eval().requires_grad_(True)
    teacher = copy.deepcopy(baseline).eval().requires_grad_(False)
    before = parameter_digest(baseline)
    backbone_before = parameter_digest(backbone)
    report = {
        "schema_version": "visiondata-gate.normality-ttt.v1",
        "strategy": "EPISODIC_MASKED_STUDENT",
        "status": "ROLLED_BACK",
        "rollback_reason": None,
        "steps_completed": 0,
        "loss_curve": [],
        "objective_before": None,
        "objective_after": None,
        "parameter_sha256_before": before,
        "parameter_sha256_after": before,
        "attempted_parameter_sha256": before,
        "effective_parameter_sha256": before,
        "backbone_sha256_before": backbone_before,
        "backbone_sha256_after": backbone_before,
        "guard_before": None,
        "guard_after": None,
        "effective_guard": None,
        "reset_after_episode": True,
        "persistent_learning": False,
        "parent_pack_unchanged": True,
        "thresholds_unchanged": True,
        "budget": budget,
        "loss_weights": {
            "masked_reconstruction": 1.0,
            "teacher_replay": 1.0,
            "parameter_anchor": 0.1,
        },
        "mask_fraction": 0.25,
        "industrial_benefit_validated": False,
        "guard_policy": dict(GUARD_POLICY),
    }
    started = clock()

    def check_time():
        if clock() - started >= budget["max_seconds"]:
            raise ValueError("TTT_TIME_BUDGET_EXCEEDED")

    try:
        report["guard_before"] = _matrix(guard_evaluator(baseline))
        report["effective_guard"] = report["guard_before"]
        check_time()
        if report["guard_before"]["tp"] < 1 or report["guard_before"]["tn"] < 1:
            raise ValueError("TTT_GUARD_BASELINE_UNQUALIFIED")
        if not 1 <= len(adaptation) <= 8 or not 1 <= len(replay) <= 8:
            raise ValueError("TTT_SAMPLE_BUDGET_INVALID")
        total_elements = 0
        for features in adaptation + replay:
            if not isinstance(features, dict) or set(features) != set(candidate):
                raise ValueError("TTT_FEATURE_CONTRACT_INVALID")
            for feature in features.values():
                if (
                    not isinstance(feature, torch.Tensor)
                    or feature.device.type != "cpu"
                    or feature.ndim != 4
                    or feature.shape[0] != 1
                    or not feature.is_floating_point()
                ):
                    raise ValueError("TTT_FEATURE_CONTRACT_INVALID")
                if not bool(torch.isfinite(feature).all()):
                    raise ValueError("TTT_NONFINITE_INPUT")
                total_elements += feature.numel()
        if total_elements > 16_000_000:
            raise ValueError("TTT_FEATURE_BUDGET_EXCEEDED")
        anchors = [parameter.detach().clone() for parameter in candidate.parameters()]
        generator = torch.Generator(device="cpu").manual_seed(budget["seed"])
        # A fixed corruption makes first/last reconstruction loss comparable.
        masks = [
            {
                key: (torch.rand(value.shape, generator=generator) < 0.25)
                for key, value in row.items()
            }
            for row in adaptation
        ]
        for row in masks:
            for mask in row.values():
                mask.reshape(-1)[0] = True
        with torch.no_grad():
            replay_targets = [
                {
                    key: teacher[key](value.detach()).detach()
                    for key, value in row.items()
                }
                for row in replay
            ]

        def objective_terms():
            # Training and final no-grad measurement use exactly the same masks,
            # frozen replay targets, parameter anchors and denominators.
            reconstruction = torch.zeros(())
            distillation = torch.zeros(())
            for row, row_masks in zip(adaptation, masks):
                for key, feature in row.items():
                    feature = feature.detach()
                    mask = row_masks[key]
                    prediction = candidate[key](feature.masked_fill(mask, 0.0))
                    reconstruction = (
                        reconstruction + (prediction - feature).square()[mask].mean()
                    )
            reconstruction = reconstruction / (len(adaptation) * len(candidate))
            for row, targets in zip(replay, replay_targets):
                for key, feature in row.items():
                    distillation = (
                        distillation
                        + (candidate[key](feature.detach()) - targets[key])
                        .square()
                        .mean()
                    )
            distillation = distillation / (len(replay) * len(candidate))
            anchor = sum(
                (parameter - initial).square().mean()
                for parameter, initial in zip(candidate.parameters(), anchors)
            )
            loss = reconstruction + distillation + 0.1 * anchor
            return loss, reconstruction, distillation, anchor

        optimizer = torch.optim.SGD(candidate.parameters(), lr=budget["learning_rate"])
        for step in range(budget["steps"]):
            check_time()
            optimizer.zero_grad(set_to_none=True)
            loss, reconstruction, distillation, anchor = objective_terms()
            if not bool(torch.isfinite(loss)):
                raise ValueError("TTT_NONFINITE_LOSS")
            loss.backward()
            gradients = [p.grad for p in candidate.parameters() if p.grad is not None]
            if not gradients or any(
                not bool(torch.isfinite(g).all()) for g in gradients
            ):
                raise ValueError("TTT_NONFINITE_GRADIENT")
            gradient_norm = float(
                torch.nn.utils.clip_grad_norm_(candidate.parameters(), 1.0)
            )
            if not math.isfinite(gradient_norm) or gradient_norm <= 0:
                raise ValueError("TTT_NO_VALID_GRADIENT")
            optimizer.step()
            report["steps_completed"] += 1
            if report["steps_completed"] == 1:
                report["objective_before"] = float(loss.detach())
            report["loss_curve"].append(
                {
                    "step": step + 1,
                    "loss": float(loss.detach()),
                    "reconstruction_loss": float(reconstruction.detach()),
                    "replay_loss": float(distillation.detach()),
                    "anchor_loss": float(anchor.detach()),
                    "gradient_norm": gradient_norm,
                }
            )
            if any(not bool(torch.isfinite(p).all()) for p in candidate.parameters()):
                raise ValueError("TTT_NONFINITE_PARAMETER")
        check_time()
        with torch.no_grad():
            final_objective = objective_terms()[0]
        if not bool(torch.isfinite(final_objective)):
            raise ValueError("TTT_NONFINITE_FINAL_OBJECTIVE")
        report["objective_after"] = float(final_objective)
        check_time()
        if report["objective_after"] >= report["objective_before"]:
            raise ValueError("TTT_FINAL_OBJECTIVE_NOT_IMPROVED")
        report["guard_after"] = _matrix(guard_evaluator(candidate))
        check_time()
        previous, current = report["guard_before"], report["guard_after"]
        if (
            current["tp"] + current["fn"] != previous["tp"] + previous["fn"]
            or current["tn"] + current["fp"] != previous["tn"] + previous["fp"]
        ):
            raise ValueError("TTT_GUARD_DENOMINATOR_CHANGED")
        if (
            current["fp"] > previous["fp"]
            or current["fn"] > previous["fn"]
            or current["tp"] < 1
            or current["tn"] < 1
        ):
            raise ValueError("TTT_GUARD_REGRESSION")
        if parameter_digest(candidate) == before:
            raise ValueError("TTT_NO_PARAMETER_UPDATE")
        report["status"] = "ACCEPTED_EPISODIC"
        report["effective_guard"] = current
    except (ValueError, RuntimeError) as error:
        report["rollback_reason"] = _error_code(error)
    report["parameter_sha256_after"] = parameter_digest(candidate)
    report["attempted_parameter_sha256"] = report["parameter_sha256_after"]
    report["backbone_sha256_after"] = parameter_digest(backbone)
    if (
        parameter_digest(baseline) != before
        or report["backbone_sha256_after"] != backbone_before
    ):
        raise ValueError("TTT_FROZEN_PARENT_MUTATED")
    accepted = report["status"] == "ACCEPTED_EPISODIC"
    selected = candidate if accepted else baseline
    report["effective_parameter_sha256"] = parameter_digest(selected)
    report["elapsed_seconds"] = max(0.0, clock() - started)
    return report, selected


def extract_features(loaded: dict, sample: dict) -> dict:
    """Apply the pack's native RGB transform and detach frozen backbone features."""
    backend = _inference_module()
    path = backend._checked_file(
        Path(sample["path"]), sample["sha256"], "TTT_IMAGE_SHA_MISMATCH"
    )
    if path.stat().st_size > 64 * 1024 * 1024:
        raise ValueError("TTT_IMAGE_BUDGET_EXCEEDED")
    from PIL import Image
    import numpy as np

    try:
        with Image.open(path) as opened:
            if opened.width * opened.height > 25_000_000:
                raise ValueError("TTT_IMAGE_BUDGET_EXCEEDED")
            opened.verify()
        with Image.open(path) as opened:
            size = loaded["image_size"]
            if not 1 <= size <= 512:
                raise ValueError("TTT_IMAGE_BUDGET_EXCEEDED")
            rgb = opened.convert("RGB").resize((size, size), Image.Resampling.BILINEAR)
            array = np.asarray(rgb, dtype=np.float32) / 255.0
    except (OSError, SyntaxError) as error:
        raise ValueError("TTT_IMAGE_INVALID") from error
    torch = loaded["_torch"]
    tensor = torch.from_numpy(array.copy()).permute(2, 0, 1).unsqueeze(0)
    backbone = loaded["_backbone"].eval().requires_grad_(False)
    captured = {}

    def capture(layer):
        def hook(_module, _args, value):
            if isinstance(value, (list, tuple)):
                value = value[0]
            if not isinstance(value, torch.Tensor) or value.ndim != 4:
                raise ValueError("TTT_FEATURE_CONTRACT_INVALID")
            captured[str(layer)] = torch.nn.functional.normalize(
                value.float(), dim=1
            ).detach()

        return hook

    handles = [
        backbone.model[layer].register_forward_hook(capture(layer))
        for layer in loaded["feature_layers"]
    ]
    try:
        # no_grad produces ordinary detached tensors usable in later autograd.
        with torch.no_grad():
            backbone(tensor)
    finally:
        for handle in handles:
            handle.remove()
    if set(captured) != {str(layer) for layer in loaded["feature_layers"]}:
        raise ValueError("TTT_FEATURE_CONTRACT_INVALID")
    if any(not bool(torch.isfinite(value).all()) for value in captured.values()):
        raise ValueError("TTT_NONFINITE_INPUT")
    if backend._sha(path) != sample["sha256"]:
        raise ValueError("TTT_IMAGE_SHA_MISMATCH")
    return captured


def _failure_report(reason: str, budget: dict) -> dict:
    return {
        "schema_version": "visiondata-gate.normality-ttt.v1",
        "strategy": "EPISODIC_MASKED_STUDENT",
        "status": "ROLLED_BACK",
        "rollback_reason": reason,
        "steps_completed": 0,
        "loss_curve": [],
        "objective_before": None,
        "objective_after": None,
        "parameter_sha256_before": None,
        "parameter_sha256_after": None,
        "attempted_parameter_sha256": None,
        "effective_parameter_sha256": None,
        "guard_before": None,
        "guard_after": None,
        "effective_guard": None,
        "reset_after_episode": True,
        "persistent_learning": False,
        "parent_pack_unchanged": True,
        "thresholds_unchanged": True,
        "budget": budget,
        "industrial_benefit_validated": False,
        "attempt_measurements_available": False,
        "guard_policy": dict(GUARD_POLICY),
    }


def child_ttt(request: dict) -> dict:
    """Worker entry: validate exact identities, actually adapt, then gate output."""
    backend = _inference_module()
    extras = {
        "adaptation_images",
        "replay_images",
        "guard_images",
        "budget",
        "ttt_backend_sha256",
    }
    if not isinstance(request, dict) or not extras.issubset(request):
        raise ValueError("TTT_REQUEST_INVALID")
    if request["ttt_backend_sha256"] != backend._sha(Path(__file__).resolve()):
        raise ValueError("TTT_IMPLEMENTATION_SHA_MISMATCH")
    budget = validate_budget(request["budget"])
    identities = validate_splits(
        request["adaptation_images"],
        request["replay_images"],
        request["guard_images"],
        request["image_sha256"],
    )
    validate_pixel_isolation(
        request["adaptation_images"], request["replay_images"], request["guard_images"]
    )
    base_request = {key: value for key, value in request.items() if key not in extras}
    final_heatmap = Path(base_request["heatmap_path"])
    work = final_heatmap.parent.parent / "ttt_artifacts"
    baseline_heatmap = work / "baseline" / "heatmap.png"
    base_request["heatmap_path"] = str(baseline_heatmap)
    # Existing path validates runtime, pack, native transform, and query identity.
    baseline = backend._child_infer(base_request)
    report = _failure_report("TTT_NOT_STARTED", budget)
    selected_result, selected_heatmap = baseline, baseline_heatmap
    loaded = None
    try:
        loaded = backend._load_normality_pack(
            Path(request["model_pack_path"]),
            request["model_pack_sha256"],
            request["backbone_weights_sha256"],
        )
        if loaded["image_size"] > 512:
            raise ValueError("TTT_IMAGE_BUDGET_EXCEEDED")
        loaded["_backbone"].eval().requires_grad_(False)
        guard_calls = 0

        def evaluate(students):
            nonlocal guard_calls
            guard_calls += 1
            state = dict(loaded, _students=students)
            matrix = {"tp": 0, "tn": 0, "fp": 0, "fn": 0}
            for index, row in enumerate(request["guard_images"]):
                # Image decode/finite scores are enforced by native inference.
                result = backend._score_normality_image(
                    state,
                    Path(row["path"]),
                    row["sha256"],
                    work / f"guard_{guard_calls}_{index}" / "heatmap.png",
                )
                predicted = result["predicted_anomaly"]
                if row["reference_label"] == "anomaly":
                    matrix["tp" if predicted else "fn"] += 1
                else:
                    matrix["fp" if predicted else "tn"] += 1
            return matrix

        baseline_matrix = evaluate(loaded["_students"])
        parent_digest = parameter_digest(loaded["_students"])
        backbone_digest = parameter_digest(loaded["_backbone"])
        report.update(
            guard_before=baseline_matrix,
            effective_guard=baseline_matrix,
            parameter_sha256_before=parent_digest,
            parameter_sha256_after=parent_digest,
            attempted_parameter_sha256=parent_digest,
            effective_parameter_sha256=parent_digest,
            backbone_sha256_before=backbone_digest,
            backbone_sha256_after=backbone_digest,
            attempt_measurements_available=True,
        )
        adaptation = [
            extract_features(loaded, row) for row in request["adaptation_images"]
        ]
        replay = [extract_features(loaded, row) for row in request["replay_images"]]

        def evaluate_once(students):
            return (
                baseline_matrix
                if students is loaded["_students"]
                else evaluate(students)
            )

        report, selected = run_tensor_episode(
            loaded, adaptation, replay, evaluate_once, budget
        )
        if report["status"] == "ACCEPTED_EPISODIC":
            candidate_heatmap = work / "candidate" / "heatmap.png"
            candidate = backend._score_normality_image(
                dict(loaded, _students=selected),
                Path(request["image_path"]),
                request["image_sha256"],
                candidate_heatmap,
            )
            selected_result = dict(baseline, **candidate)
            selected_heatmap = candidate_heatmap
    except (ValueError, RuntimeError, OSError) as error:
        reason = _error_code(error)
        report["status"], report["rollback_reason"] = "ROLLED_BACK", reason
        report["effective_guard"] = report["guard_before"]
        if loaded is not None:
            digest = parameter_digest(loaded["_students"])
            report["parameter_sha256_before"] = digest
            report["effective_parameter_sha256"] = digest
        selected_result, selected_heatmap = baseline, baseline_heatmap
    if backend._sha(Path(request["model_pack_path"])) != request["model_pack_sha256"]:
        raise ValueError("TTT_PARENT_PACK_CHANGED")
    report.update(
        input_groups=identities, implementation_sha256=request["ttt_backend_sha256"]
    )
    final_heatmap.parent.mkdir(parents=True, exist_ok=False)
    shutil.copyfile(selected_heatmap, final_heatmap)
    return dict(
        selected_result, ttt=report, ttt_backend_sha256=request["ttt_backend_sha256"]
    )


def run_normality_ttt(
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
    adaptation_images: list,
    replay_images: list,
    guard_images: list,
    budget: dict,
    output_root: Path,
    max_seconds: int = 180,
) -> dict:
    """Public stdlib-only boundary. Every invocation starts from the parent pack."""
    backend = _inference_module()
    budget = validate_budget(budget)
    identities = validate_splits(
        adaptation_images, replay_images, guard_images, expected_image_sha256
    )
    validate_pixel_isolation(adaptation_images, replay_images, guard_images)
    if type(max_seconds) is not int or not 5 <= max_seconds <= 300:
        raise ValueError("NORMALITY_WORKER_BUDGET_INVALID")
    common = dict(
        executable=executable,
        expected_executable_sha256=expected_executable_sha256,
        expected_runtime_sha256=expected_runtime_sha256,
        model_pack=model_pack,
        expected_model_pack_sha256=expected_model_pack_sha256,
        expected_backbone_weights_sha256=expected_backbone_weights_sha256,
        expected_source_binding_sha256=expected_source_binding_sha256,
        expected_source_index_sha256=expected_source_index_sha256,
    )
    runtime, original_pack, request = backend._worker_request(
        **common, output_root=output_root
    )
    output = Path(output_root).expanduser().resolve()
    inputs = output / "inputs"
    originals = []
    for name, records in (
        ("adaptation_images", adaptation_images),
        ("replay_images", replay_images),
        ("guard_images", guard_images),
    ):
        frozen = []
        for index, row in enumerate(records):
            source = backend._checked_file(
                Path(row["path"]), row["sha256"], "TTT_IMAGE_SHA_MISMATCH"
            )
            if source.stat().st_size > 64 * 1024 * 1024:
                raise ValueError("TTT_IMAGE_BUDGET_EXCEEDED")
            destination = inputs / f"{name}_{index}.{row['image_format']}"
            shutil.copyfile(source, destination)
            backend._checked_file(destination, row["sha256"], "TTT_IMAGE_SHA_MISMATCH")
            originals.append((source, row["sha256"]))
            frozen.append(dict(row, path=str(destination)))
        request[name] = frozen
    source_image = backend._checked_file(
        image, expected_image_sha256, "NORMALITY_INPUT_IMAGE_SHA_MISMATCH"
    )
    if image_format not in {"png", "jpg", "jpeg", "bmp"}:
        raise ValueError("NORMALITY_INPUT_IMAGE_FORMAT_OR_SIZE_UNSUPPORTED")
    frozen_image = inputs / ("image." + image_format)
    shutil.copyfile(source_image, frozen_image)
    heatmap = output / "artifacts" / "heatmap.png"
    implementation_sha = backend._sha(Path(__file__).resolve())
    request.update(
        image_path=str(frozen_image),
        image_sha256=expected_image_sha256,
        heatmap_path=str(heatmap),
        budget=budget,
        ttt_backend_sha256=implementation_sha,
    )
    child = backend._run_worker_process(
        mode="ttt",
        executable=runtime,
        request=request,
        output_root=output / "worker",
        max_seconds=max_seconds,
    )
    expected = {
        "status": "completed",
        "model_pack_sha256": expected_model_pack_sha256,
        "runtime_sha256": expected_runtime_sha256,
        "model_pack_schema_version": "visiondata-gate.yolo26-normality-model-pack.v2",
        "backbone_weights_sha256": expected_backbone_weights_sha256,
        "source_binding_sha256": expected_source_binding_sha256,
        "source_index_sha256": expected_source_index_sha256,
        "image_sha256": expected_image_sha256,
        "inference_backend_sha256": request["inference_backend_sha256"],
        "ttt_backend_sha256": implementation_sha,
        "device": "cpu",
        "machine_write_permitted": False,
        "production_release_allowed": False,
    }
    if any(child.get(key) != value for key, value in expected.items()):
        raise ValueError("TTT_WORKER_IDENTITY_MISMATCH")
    for key in (
        "image_score",
        "image_threshold",
        "pixel_threshold",
        "positive_pixel_fraction",
    ):
        if (
            type(child.get(key)) not in {int, float}
            or not math.isfinite(float(child[key]))
            or float(child[key]) < 0
        ):
            raise ValueError("NORMALITY_INFERENCE_RESULT_INVALID")
    if (
        type(child.get("predicted_anomaly")) is not bool
        or child["predicted_anomaly"]
        != (child["image_score"] >= child["image_threshold"])
        or not 0 <= child["positive_pixel_fraction"] <= 1
    ):
        raise ValueError("NORMALITY_INFERENCE_RESULT_INVALID")
    if (
        not heatmap.is_file()
        or backend._sha(heatmap) != child.get("heatmap_sha256")
        or heatmap.stat().st_size != child.get("heatmap_bytes")
        or child.get("heatmap_width") != 64
        or child.get("heatmap_height") != 64
    ):
        raise ValueError("NORMALITY_HEATMAP_CONTRACT_INVALID")
    ttt = child.get("ttt")
    if (
        not isinstance(ttt, dict)
        or ttt.get("schema_version") != "visiondata-gate.normality-ttt.v1"
        or ttt.get("implementation_sha256") != implementation_sha
        or ttt.get("input_groups") != identities
        or ttt.get("status") not in {"ACCEPTED_EPISODIC", "ROLLED_BACK"}
        or ttt.get("parent_pack_unchanged") is not True
        or ttt.get("thresholds_unchanged") is not True
        or ttt.get("persistent_learning") is not False
        or ttt.get("reset_after_episode") is not True
    ):
        raise ValueError("TTT_RESULT_INVALID")
    for source, digest in originals + [
        (source_image, expected_image_sha256),
        (original_pack, expected_model_pack_sha256),
        (runtime, expected_executable_sha256),
    ]:
        if backend._sha(source) != digest:
            raise ValueError("TTT_INPUT_CHANGED_DURING_EPISODE")
    return {
        **child,
        "schema_version": "visiondata-gate.normality-inference-result.v1",
        "status": "COMPLETED_LOCAL_SANDBOX_INFERENCE",
        "heatmap": {
            "sha256": child["heatmap_sha256"],
            "bytes": child["heatmap_bytes"],
            "width": 64,
            "height": 64,
            "format": "png",
        },
        "decision_scope": "MODEL_SIGNAL_ONLY_NOT_GATE_OR_PRODUCTION_DECISION",
    }
