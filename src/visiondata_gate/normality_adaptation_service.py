"""Hash-bound, explicit Normality TTT operations and failure audit receipts.

This registry layer never imports torch, modifies a parent pack, trains a
detector, or converts a human guard label into governed label truth.
"""

from __future__ import annotations

import hashlib
import io
import math
from pathlib import Path
import re
import sqlite3
from typing import Literal
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, Field, model_validator

from . import normality_ttt
from .local_model_registry import (
    OPAQUE,
    SHA,
    LocalVisionModelService,
    RunNormalityInference,
    VisionModelError,
    _assert_registry_path,
    _ensure_registry_directory,
    _file,
    _seal,
    _sha,
)
from .task_store import NotFoundError


GUARD_POLICY = {
    "min_true_positive": 1,
    "min_true_negative": 1,
    "max_fp_increase": 0,
    "max_fn_increase": 0,
}


class NormalityTttAsset(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    asset_id: str = Field(pattern=OPAQUE)
    expected_asset_receipt_sha256: str = Field(pattern=SHA)
    expected_image_sha256: str = Field(pattern=SHA)


class NormalityTttGuardAsset(NormalityTttAsset):
    reference_label: Literal["normal", "anomaly"]


class NormalityTttBudget(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, allow_inf_nan=False)
    steps: int = Field(default=3, ge=1, le=8)
    learning_rate: float = Field(default=0.001, ge=1e-5, le=1e-2)
    max_seconds: int = Field(default=60, ge=5, le=120)
    seed: int = Field(default=0, ge=0, le=2**31 - 1)


class RunNormalityTtt(RunNormalityInference):
    expected_ttt_implementation_sha256: str = Field(pattern=SHA)
    adaptation_assets: list[NormalityTttAsset] = Field(
        default_factory=list, max_length=7
    )
    replay_assets: list[NormalityTttAsset] = Field(min_length=1, max_length=8)
    guard_assets: list[NormalityTttGuardAsset] = Field(min_length=2, max_length=16)
    budget: NormalityTttBudget = Field(default_factory=NormalityTttBudget)
    operator_attests_ttt_authorized: Literal[True]
    operator_attests_replay_normal: Literal[True]
    operator_attests_guard_labels_reviewed: Literal[True]

    @model_validator(mode="after")
    def bounded_episode(self):
        if self.budget.max_seconds > self.max_seconds:
            raise ValueError("TTT episode budget exceeds external worker budget")
        if {row.reference_label for row in self.guard_assets} != {"normal", "anomaly"}:
            raise ValueError("TTT guard requires both human-reviewed classes")
        return self


def ttt_implementation_sha256() -> str:
    return hashlib.sha256(Path(normality_ttt.__file__).read_bytes()).hexdigest()


def _number(value, *, minimum=0.0) -> bool:
    return (
        type(value) in {int, float} and math.isfinite(float(value)) and value >= minimum
    )


def _digest(value) -> bool:
    return isinstance(value, str) and re.fullmatch(SHA, value) is not None


def _matrix(value, normal_count, anomaly_count):
    if (
        not isinstance(value, dict)
        or set(value) != {"tp", "tn", "fp", "fn"}
        or any(type(item) is not int or item < 0 for item in value.values())
        or value["tp"] + value["fn"] != anomaly_count
        or value["tn"] + value["fp"] != normal_count
    ):
        raise VisionModelError("TTT_RESULT_CONTRACT_INVALID")


def _validated_report(value, request, groups, implementation_sha):
    """Independently enforce measurement identities, denominators and rollback.

    Guard counts are evaluated against the authorized human label set, not
    against a denominator chosen by the external worker.
    """
    report = value.get("ttt")
    required = {
        "schema_version",
        "strategy",
        "status",
        "rollback_reason",
        "steps_completed",
        "objective_before",
        "objective_after",
        "loss_curve",
        "parameter_sha256_before",
        "parameter_sha256_after",
        "attempted_parameter_sha256",
        "effective_parameter_sha256",
        "backbone_sha256_before",
        "backbone_sha256_after",
        "guard_before",
        "guard_after",
        "effective_guard",
        "reset_after_episode",
        "persistent_learning",
        "parent_pack_unchanged",
        "thresholds_unchanged",
        "budget",
        "input_groups",
        "implementation_sha256",
        "industrial_benefit_validated",
        "guard_policy",
    }
    optional = {
        "loss_weights",
        "mask_fraction",
        "elapsed_seconds",
        "attempt_measurements_available",
    }
    if (
        not isinstance(report, dict)
        or not required <= set(report) <= required | optional
        or report["schema_version"] != "visiondata-gate.normality-ttt.v1"
        or report["strategy"] != "EPISODIC_MASKED_STUDENT"
        or report["status"] not in {"ACCEPTED_EPISODIC", "ROLLED_BACK"}
        or report["implementation_sha256"] != implementation_sha
        or report["input_groups"] != groups
        or report["budget"] != request.budget.model_dump(mode="json")
        or _sha(report["guard_policy"]) != _sha(GUARD_POLICY)
        or any(
            report[key] is not True
            for key in (
                "reset_after_episode",
                "parent_pack_unchanged",
                "thresholds_unchanged",
            )
        )
        or report["persistent_learning"] is not False
        or report["industrial_benefit_validated"] is not False
    ):
        raise VisionModelError("TTT_RESULT_CONTRACT_INVALID")
    for field in (
        "parameter_sha256_before",
        "parameter_sha256_after",
        "attempted_parameter_sha256",
        "effective_parameter_sha256",
        "backbone_sha256_before",
        "backbone_sha256_after",
    ):
        if not _digest(report[field]):
            raise VisionModelError("TTT_RESULT_CONTRACT_INVALID")
    if (
        report["parameter_sha256_after"] != report["attempted_parameter_sha256"]
        or report["backbone_sha256_before"] != report["backbone_sha256_after"]
        or type(report["steps_completed"]) is not int
        or not 0 <= report["steps_completed"] <= request.budget.steps
        or not isinstance(report["loss_curve"], list)
        or len(report["loss_curve"]) != report["steps_completed"]
    ):
        raise VisionModelError("TTT_RESULT_CONTRACT_INVALID")
    for index, row in enumerate(report["loss_curve"], 1):
        if (
            not isinstance(row, dict)
            or set(row)
            != {
                "step",
                "loss",
                "reconstruction_loss",
                "replay_loss",
                "anchor_loss",
                "gradient_norm",
            }
            or type(row["step"]) is not int
            or row["step"] != index
            or any(not _number(row[key]) for key in row if key != "step")
            or row["gradient_norm"] <= 0
            or not math.isclose(
                row["loss"],
                row["reconstruction_loss"]
                + row["replay_loss"]
                + 0.1 * row["anchor_loss"],
                rel_tol=1e-5,
                abs_tol=1e-7,
            )
        ):
            raise VisionModelError("TTT_RESULT_CONTRACT_INVALID")
    objective_before, objective_after = (
        report["objective_before"],
        report["objective_after"],
    )
    if report["steps_completed"] == 0:
        if objective_before is not None or objective_after is not None:
            raise VisionModelError("TTT_RESULT_CONTRACT_INVALID")
    elif (
        not _number(objective_before)
        or not math.isclose(
            objective_before,
            report["loss_curve"][0]["loss"],
            rel_tol=1e-7,
            abs_tol=1e-9,
        )
        or (
            objective_after is not None
            and (
                not _number(objective_after)
                or report["steps_completed"] != request.budget.steps
            )
        )
    ):
        raise VisionModelError("TTT_RESULT_CONTRACT_INVALID")
    normal_count = sum(row.reference_label == "normal" for row in request.guard_assets)
    anomaly_count = len(request.guard_assets) - normal_count
    for field in ("guard_before", "effective_guard"):
        _matrix(report[field], normal_count, anomaly_count)
    if report["guard_after"] is not None:
        _matrix(report["guard_after"], normal_count, anomaly_count)
    if "elapsed_seconds" in report and not _number(report["elapsed_seconds"]):
        raise VisionModelError("TTT_RESULT_CONTRACT_INVALID")
    if "loss_weights" in report and report["loss_weights"] != {
        "masked_reconstruction": 1.0,
        "teacher_replay": 1.0,
        "parameter_anchor": 0.1,
    }:
        raise VisionModelError("TTT_RESULT_CONTRACT_INVALID")
    if "mask_fraction" in report and report["mask_fraction"] != 0.25:
        raise VisionModelError("TTT_RESULT_CONTRACT_INVALID")
    if (
        "attempt_measurements_available" in report
        and report["attempt_measurements_available"] is not True
    ):
        raise VisionModelError("TTT_RESULT_CONTRACT_INVALID")
    if report["status"] == "ACCEPTED_EPISODIC":
        before, after = report["guard_before"], report["guard_after"]
        if (
            after is None
            or report["rollback_reason"] is not None
            or report["steps_completed"] != request.budget.steps
            or report["parameter_sha256_after"] == report["parameter_sha256_before"]
            or report["effective_parameter_sha256"] != report["parameter_sha256_after"]
            or report["effective_guard"] != after
            or min(before["tp"], before["tn"], after["tp"], after["tn"]) < 1
            or after["fp"] > before["fp"]
            or after["fn"] > before["fn"]
            or report.get("elapsed_seconds", 0) > request.budget.max_seconds
            or not _number(objective_before)
            or not _number(objective_after)
            or objective_after >= objective_before
        ):
            raise VisionModelError("TTT_RESULT_CONTRACT_INVALID")
    else:
        allowed_reasons = normality_ttt._ERROR_CODES | {
            "TTT_RUNTIME_ERROR",
            "TTT_INVALID_INPUT",
            "TTT_IMAGE_IO_ERROR",
        }
        if (
            report["rollback_reason"] not in allowed_reasons
            or report["effective_parameter_sha256"] != report["parameter_sha256_before"]
            or report["effective_guard"] != report["guard_before"]
        ):
            raise VisionModelError("TTT_RESULT_CONTRACT_INVALID")
        if report["rollback_reason"] == "TTT_FINAL_OBJECTIVE_NOT_IMPROVED" and (
            not _number(objective_after) or objective_after < objective_before
        ):
            raise VisionModelError("TTT_RESULT_CONTRACT_INVALID")
        if (
            report["rollback_reason"] == "TTT_NONFINITE_FINAL_OBJECTIVE"
            and objective_after is not None
        ):
            raise VisionModelError("TTT_RESULT_CONTRACT_INVALID")
        unqualified = (
            min(report["guard_before"]["tp"], report["guard_before"]["tn"]) < 1
        )
        if (
            report["rollback_reason"] == "TTT_GUARD_BASELINE_UNQUALIFIED"
        ) != unqualified:
            raise VisionModelError("TTT_RESULT_CONTRACT_INVALID")
        if unqualified and (
            report["rollback_reason"] != "TTT_GUARD_BASELINE_UNQUALIFIED"
            or report["steps_completed"] != 0
            or report["guard_after"] is not None
            or report["attempted_parameter_sha256"] != report["parameter_sha256_before"]
        ):
            raise VisionModelError("TTT_RESULT_CONTRACT_INVALID")
    return report


class NormalityAdaptationService(LocalVisionModelService):
    """Explicit local episodes; feedback and detector training stay independent."""

    def ttt_capabilities(self, actor, project):
        self._authorize(actor, project)
        return _seal(
            {
                "schema_version": "visiondata-gate.normality-ttt-capabilities.v1",
                "project_id": project,
                "strategy": "EPISODIC_MASKED_STUDENT",
                "implementation_sha256": ttt_implementation_sha256(),
                "max_steps": 8,
                "max_learning_rate": 0.01,
                "min_learning_rate": 0.00001,
                "max_seconds": 120,
                "max_adaptation_assets": 7,
                "max_replay_assets": 8,
                "max_guard_assets": 16,
                "production_release_allowed": False,
                "machine_write_permitted": False,
                "persistent_learning": False,
                "guard_policy": dict(GUARD_POLICY),
                "industrial_benefit_validated": False,
            }
        )

    def list_failures(self, actor, project):
        return self._list(actor, project, "ttt_failure")

    def _asset_sample(self, conn, project, reference):
        from PIL import Image

        asset, private = self._read(
            conn, project, reference.asset_id, "inference_asset"
        )
        if (
            asset.get("asset_id") != reference.asset_id
            or asset.get("receipt_sha256") != reference.expected_asset_receipt_sha256
            or asset.get("image_sha256") != reference.expected_image_sha256
            or asset.get("status") != "FROZEN_LOCAL_INFERENCE_ASSET"
            or asset.get("production_release_allowed") is not False
            or asset.get("machine_write_permitted") is not False
        ):
            raise VisionModelError("TTT_ASSET_CHANGED")
        expected = (
            self.root
            / "cas"
            / "sha256"
            / asset["image_sha256"][:2]
            / asset["image_sha256"]
        )
        candidate = _assert_registry_path(self.root, Path(private["cas_path"]))
        if candidate != _assert_registry_path(self.root, expected):
            raise VisionModelError("TTT_ASSET_CAS_PATH_MISMATCH")
        verified = _file(candidate, asset["image_sha256"], "TTT_ASSET_CHANGED")
        with verified.open("rb") as stream:
            raw = stream.read(64 * 1024 * 1024 + 1)
        if (
            len(raw) > 64 * 1024 * 1024
            or hashlib.sha256(raw).hexdigest() != asset["image_sha256"]
        ):
            raise VisionModelError("TTT_ASSET_CHANGED")
        try:
            with Image.open(io.BytesIO(raw)) as opened:
                if opened.width * opened.height > 25_000_000:
                    raise VisionModelError("TTT_IMAGE_BUDGET_EXCEEDED")
                rgb = opened.convert("RGB")
                pixel_identity = hashlib.sha256(
                    f"RGB:{rgb.width}:{rgb.height}:".encode("ascii") + rgb.tobytes()
                ).hexdigest()
        except (OSError, ValueError, Image.DecompressionBombError):
            raise VisionModelError("TTT_IMAGE_INVALID") from None
        _assert_registry_path(self.root, candidate)
        return {
            "path": str(verified),
            "sha256": asset["image_sha256"],
            "image_format": asset["format"],
        }, pixel_identity

    def _episode_inputs(self, actor, project, request):
        query = NormalityTttAsset(
            asset_id=request.asset_id,
            expected_asset_receipt_sha256=request.expected_asset_receipt_sha256,
            expected_image_sha256=request.expected_image_sha256,
        )
        groups, seen_ids, seen_pixels = {}, set(), set()
        with self.product.store._connection() as conn:
            self._membership(conn, actor, project)
            for name, references in (
                ("adaptation", [query, *request.adaptation_assets]),
                ("replay", request.replay_assets),
                ("guard", request.guard_assets),
            ):
                rows = []
                for reference in references:
                    if reference.asset_id in seen_ids:
                        raise VisionModelError("TTT_SPLIT_OVERLAP")
                    row, pixel_sha = self._asset_sample(conn, project, reference)
                    if pixel_sha in seen_pixels:
                        raise VisionModelError("TTT_DECODED_PIXEL_OVERLAP")
                    seen_ids.add(reference.asset_id)
                    seen_pixels.add(pixel_sha)
                    if name in {"replay", "guard"}:
                        row.update(
                            reference_source="human",
                            reference_label="normal"
                            if name == "replay"
                            else reference.reference_label,
                        )
                    rows.append(row)
                groups[name] = rows
        identities = normality_ttt.validate_splits(
            groups["adaptation"],
            groups["replay"],
            groups["guard"],
            request.expected_image_sha256,
        )
        return groups, identities

    def _failure(self, actor, project, model, request, operation, implementation, code):
        """Only terminalize this already-authorized episode, even after revocation.

        No new input reads, model loads or authority grants occur here. Record
        and ledger commit together; storage errors remain an explicit HOLD.
        """
        value = self._base(project, "vision_ttt_failure", actor, request)
        value.update(
            failure_id=value["resource_id"],
            model_id=model["model_id"],
            asset_id=request.asset_id,
            model_pack_sha256=model["model_pack_sha256"],
            image_sha256=request.expected_image_sha256,
            authorization_sha256=_sha(request.model_dump(mode="json")),
            ttt_backend_sha256=implementation,
            status="FAILED_CLOSED",
            failure_code=code,
            measurements_available=False,
            retry_policy="NEW_EXPLICIT_AUTHORIZATION_REQUIRED",
        )
        try:
            with self.product.store._connection(immediate=True) as conn:
                result = self._put(conn, value, "ttt_failure")
                conn.execute(
                    "INSERT INTO vision_requests VALUES (?,?,?,?,?,?)",
                    (
                        project,
                        actor,
                        operation,
                        request.request_key,
                        _sha(request.model_dump(mode="json")),
                        result["resource_id"],
                    ),
                )
        except (sqlite3.Error, OSError):
            raise VisionModelError("TTT_TERMINAL_AUDIT_UNAVAILABLE") from None
        self.product.store.get_project(actor, project)
        return result

    def run_ttt(self, actor, project, identifier, request: RunNormalityTtt):
        request = RunNormalityTtt.model_validate(request.model_dump(mode="json"))
        operation = "run_normality_ttt:" + identifier
        with self._operation(actor, project, operation, request) as existing:
            if existing:
                return existing
            implementation = ttt_implementation_sha256()
            if implementation != request.expected_ttt_implementation_sha256:
                raise VisionModelError("TTT_IMPLEMENTATION_CHANGED")
            bound = self._bound_normality_inputs(project, identifier, request)
            samples, identities = self._episode_inputs(actor, project, request)
            model, asset, runtime = (
                bound[key] for key in ("model", "asset", "runtime")
            )
            value = self._base(project, "vision_inference", actor, request)
            output = _ensure_registry_directory(
                self.root, self.root / "inferences" / value["resource_id"]
            )
            # Past this boundary every worker exception gets a durable audit
            # terminal, never an automatic ordinary-inference fallback or retry.
            try:
                result = normality_ttt.run_normality_ttt(
                    executable=bound["runtime_path"],
                    expected_executable_sha256=runtime["executable_sha256"],
                    expected_runtime_sha256=runtime["runtime_sha256"],
                    model_pack=bound["model_cas"]["model_pack"],
                    expected_model_pack_sha256=model["model_pack_sha256"],
                    expected_backbone_weights_sha256=model["backbone_weights_sha256"],
                    expected_source_binding_sha256=model["source_binding_sha256"],
                    expected_source_index_sha256=model["source_index_sha256"],
                    image=bound["image"],
                    image_format=asset["format"],
                    expected_image_sha256=asset["image_sha256"],
                    adaptation_images=samples["adaptation"],
                    replay_images=samples["replay"],
                    guard_images=samples["guard"],
                    budget=request.budget.model_dump(mode="json"),
                    output_root=output,
                    max_seconds=request.max_seconds,
                )
            except Exception as error:
                code = {
                    "NORMALITY_WORKER_TIMEOUT": "TTT_WORKER_TIMEOUT",
                    "NORMALITY_WORKER_FAILED": "TTT_WORKER_FAILED",
                }.get(str(error), "TTT_EXECUTION_FAILED")
                return self._failure(
                    actor, project, model, request, operation, implementation, code
                )
            try:
                # Permission must be checked before any post-worker asset reads.
                self.product.store.get_project(actor, project)
                self._bound_normality_inputs(project, identifier, request)
                _samples_after, identities_after = self._episode_inputs(
                    actor, project, request
                )
                if (
                    identities_after != identities
                    or ttt_implementation_sha256() != implementation
                ):
                    raise VisionModelError("TTT_INPUT_CHANGED")
            except (
                NotFoundError,
                VisionModelError,
                ValueError,
                OSError,
                KeyError,
                TypeError,
            ):
                return self._failure(
                    actor,
                    project,
                    model,
                    request,
                    operation,
                    implementation,
                    "TTT_AUTHORITY_OR_INPUT_CHANGED",
                )
            try:
                expected = {
                    "schema_version": "visiondata-gate.normality-inference-result.v1",
                    "status": "COMPLETED_LOCAL_SANDBOX_INFERENCE",
                    "device": "cpu",
                    "model_pack_schema_version": model["model_pack_schema_version"],
                    **{
                        key: model[key]
                        for key in (
                            "model_pack_sha256",
                            "backbone_weights_sha256",
                            "source_binding_sha256",
                            "source_index_sha256",
                        )
                    },
                    "runtime_sha256": runtime["runtime_sha256"],
                    "image_sha256": asset["image_sha256"],
                    "inference_backend_sha256": bound["inference_backend_sha256"],
                    "ttt_backend_sha256": implementation,
                }
                if not isinstance(result, dict) or any(
                    result.get(key) != item for key, item in expected.items()
                ):
                    raise VisionModelError("TTT_RESULT_CONTRACT_INVALID")
                if (
                    result.get("production_release_allowed") is not False
                    or result.get("machine_write_permitted") is not False
                ):
                    raise VisionModelError("TTT_RESULT_CONTRACT_INVALID")
                for key in (
                    "image_score",
                    "image_threshold",
                    "pixel_threshold",
                    "positive_pixel_fraction",
                ):
                    if not _number(result.get(key)):
                        raise VisionModelError("TTT_RESULT_CONTRACT_INVALID")
                if (
                    type(result.get("predicted_anomaly")) is not bool
                    or result["predicted_anomaly"]
                    != (result["image_score"] >= result["image_threshold"])
                    or result["positive_pixel_fraction"] > 1
                ):
                    raise VisionModelError("TTT_RESULT_CONTRACT_INVALID")
                report = _validated_report(result, request, identities, implementation)
                value.update(
                    inference_id=value["resource_id"],
                    model_id=model["model_id"],
                    asset_id=asset["asset_id"],
                    runtime_id=runtime["runtime_id"],
                    **{
                        key: expected[key]
                        for key in expected
                        if key not in {"schema_version", "status", "device"}
                    },
                    status="COMPLETED_LOCAL_SANDBOX_INFERENCE",
                    device="cpu",
                    **{
                        key: result[key]
                        for key in (
                            "image_score",
                            "image_threshold",
                            "pixel_threshold",
                            "predicted_anomaly",
                            "positive_pixel_fraction",
                            "heatmap",
                        )
                    },
                    heatmap_artifact_id="normality_heatmap_" + uuid4().hex[:24],
                    decision_scope="MODEL_SIGNAL_ONLY_NOT_GATE_OR_PRODUCTION_DECISION",
                    review_required=True,
                    gate_decision="NOT_ISSUED",
                    ttt=report,
                    authorization_sha256=_sha(request.model_dump(mode="json")),
                )
                private = {
                    "output_root": str(output),
                    "heatmap_path": str(output / "artifacts" / "heatmap.png"),
                }
                self._normality_heatmap_bytes(value, private)
            except (VisionModelError, ValueError, TypeError, KeyError, OSError):
                return self._failure(
                    actor,
                    project,
                    model,
                    request,
                    operation,
                    implementation,
                    "TTT_RESULT_CONTRACT_INVALID",
                )
            try:
                with self.product.store._connection(immediate=True) as conn:
                    self._membership(conn, actor, project)
                    current, _ = self._read(conn, project, identifier, "model")
                    if current["receipt_sha256"] != model["receipt_sha256"]:
                        raise VisionModelError("TTT_AUTHORITY_OR_INPUT_CHANGED")
                    saved = self._put(conn, value, "inference", private)
                    self._remember(conn, actor, project, operation, request, saved)
            except (NotFoundError, VisionModelError):
                return self._failure(
                    actor,
                    project,
                    model,
                    request,
                    operation,
                    implementation,
                    "TTT_AUTHORITY_OR_INPUT_CHANGED",
                )
            except (sqlite3.Error, OSError):
                raise VisionModelError("TTT_TERMINAL_AUDIT_UNAVAILABLE") from None
            return saved
