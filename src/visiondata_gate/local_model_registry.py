"""Project-scoped local visual artifacts and explicitly authorized CPU training.

Registration streams bytes only. Model loading is a separate named permission;
Python and Ultralytics stay in the selected external runtime, outside core deps.
"""

from __future__ import annotations

from contextlib import contextmanager
from datetime import UTC, datetime
import hashlib
import hmac
import io
import json
from pathlib import Path, PurePosixPath
import re
import shutil
import stat
import threading
from typing import Literal
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, Field, model_validator

from .audit_envelope import canonical_jcs_bytes
from .execution_recovery import task_execution_lock
from .task_store import NotFoundError, ProductStoreError


SHA = r"^[0-9a-f]{64}$"
OPAQUE = r"^[A-Za-z0-9_-]{1,120}$"


class VisionModelError(ProductStoreError):
    code = "vision_model_hold"


class VisionRequest(BaseModel):
    model_config = ConfigDict(
        extra="forbid", str_strip_whitespace=True, allow_inf_nan=False
    )
    request_key: str = Field(pattern=r"^[A-Za-z0-9_-]{12,100}$")
    reviewer_identity: str = Field(min_length=2, max_length=160)
    note: str = Field(min_length=8, max_length=1000)

    @model_validator(mode="before")
    @classmethod
    def literal_authority(cls, value):
        if isinstance(value, dict):
            for key, grant in value.items():
                if (
                    key.startswith("operator_attests_")
                    or key == "ultralytics_license_acknowledged"
                ) and type(grant) is not bool:
                    raise ValueError("authority grants must be explicit JSON booleans")
        return value


class RegisterVisionModel(VisionRequest):
    display_name: str = Field(min_length=1, max_length=120)
    weights_path: str = Field(min_length=1, max_length=2048)
    expected_weights_sha256: str = Field(pattern=SHA)
    task_type: Literal["detect", "segment"]
    license_id: str = Field(min_length=1, max_length=120)
    source_description: str = Field(min_length=4, max_length=500)
    operator_attests_read_authorized: Literal[True]


class RegisterNormalityModelPack(VisionRequest):
    """Bind one opaque model pack to immutable public-proxy evidence.

    Registration hashes bytes and validates JSON evidence, but the application
    process never deserializes the PyTorch pack.  The separate weights-only load
    grant is intentionally required now so a later sandbox approval cannot
    inherit an ambiguous or unrestricted deserialization authority.
    """

    display_name: str = Field(min_length=1, max_length=120)
    model_pack_path: str = Field(min_length=1, max_length=2048)
    expected_model_pack_sha256: str = Field(pattern=SHA)
    run_directory: str = Field(min_length=1, max_length=2048)
    stability_run_directories: list[str] = Field(min_length=3, max_length=3)
    target_model_seed: Literal[20260913] = 20260913
    stability_summary_path: str = Field(min_length=1, max_length=2048)
    expected_stability_summary_sha256: str = Field(pattern=SHA)
    source_binding_path: str = Field(min_length=1, max_length=2048)
    expected_source_binding_file_sha256: str = Field(pattern=SHA)
    expected_source_binding_sha256: str = Field(pattern=SHA)
    source_index_path: str = Field(min_length=1, max_length=2048)
    expected_source_index_file_sha256: str = Field(pattern=SHA)
    expected_source_index_sha256: str = Field(pattern=SHA)
    backbone_weights_path: str = Field(min_length=1, max_length=2048)
    expected_backbone_weights_sha256: str = Field(pattern=SHA)
    operator_attests_read_authorized: Literal[True]
    operator_attests_weights_only_load_authorized: Literal[True]
    ultralytics_license_acknowledged: Literal[True]

    @model_validator(mode="after")
    def require_three_unique_runs_and_explicit_target(self):
        if len(set(self.stability_run_directories)) != 3:
            raise ValueError("stability run directories must be unique")
        if self.run_directory not in self.stability_run_directories:
            raise ValueError("target run must be one of the three stability runs")
        return self


class RegisterVisionInferenceAsset(VisionRequest):
    display_name: str = Field(min_length=1, max_length=120)
    image_path: str = Field(min_length=1, max_length=2048)
    expected_image_sha256: str = Field(pattern=SHA)
    operator_attests_read_authorized: Literal[True]


class RegisterVisionRuntime(VisionRequest):
    display_name: str = Field(min_length=1, max_length=120)
    executable_path: str = Field(min_length=1, max_length=2048)
    expected_executable_sha256: str = Field(pattern=SHA)
    operator_attests_trusted_runtime: Literal[True]
    operator_attests_execution_authorized: Literal[True]


class ProbeVisionRuntime(VisionRequest):
    expected_runtime_sha256: str = Field(pattern=SHA)
    operator_attests_trusted_runtime: Literal[True]
    operator_attests_execution_authorized: Literal[True]
    import_check: bool = False


class RegisterDetectionDataset(VisionRequest):
    source_root: str = Field(min_length=1, max_length=2048)
    manifest: dict
    expected_manifest_sha256: str = Field(pattern=SHA)
    operator_attests_data_authorized: Literal[True]


class VisionTrainingBudget(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)
    epochs: int = Field(default=1, ge=1, le=5, strict=True)
    imgsz: int = Field(default=64, ge=64, le=320, multiple_of=32, strict=True)
    batch: int = Field(default=2, ge=2, le=8, strict=True)
    seed: int = Field(default=0, ge=0, le=2147483647, strict=True)
    max_seconds: int = Field(default=120, ge=10, le=600, strict=True)
    threads: int = Field(default=2, ge=1, le=4, strict=True)


class RegisterPoolDetectionDataset(VisionRequest):
    pool_id: str = Field(pattern=OPAQUE)
    version_id: str = Field(pattern=OPAQUE)
    expected_pool_receipt_sha256: str = Field(pattern=SHA)
    expected_version_receipt_sha256: str = Field(pattern=SHA)
    class_names: list[str] = Field(min_length=1, max_length=64)
    groups: dict[str, str] = Field(min_length=1, max_length=64)
    normal_sample_ids: list[str] = Field(default_factory=list, max_length=64)
    operator_attests_data_authorized: Literal[True]


class CreateVisionTrainingRun(VisionRequest):
    runtime_id: str = Field(pattern=OPAQUE)
    expected_runtime_sha256: str = Field(pattern=SHA)
    dataset_id: str = Field(pattern=OPAQUE)
    expected_dataset_receipt_sha256: str = Field(pattern=SHA)
    initialization: Literal["ARCHITECTURE_RANDOM", "REGISTERED_WEIGHTS"]
    initial_model_id: str | None = Field(default=None, pattern=OPAQUE)
    expected_weights_sha256: str | None = Field(default=None, pattern=SHA)
    architecture: Literal["yolo26n"] = "yolo26n"
    training: VisionTrainingBudget = Field(default_factory=VisionTrainingBudget)
    operator_attests_training_authorized: Literal[True]
    operator_attests_trusted_runtime: Literal[True]
    operator_attests_trusted_weights: bool = False
    operator_attests_pickle_load_risk: bool = False
    ultralytics_license_acknowledged: Literal[True]
    adaptation: Literal["OFF"] = "OFF"
    responds_to_feedback_ids: list[str] = Field(default_factory=list, max_length=64)
    expected_feedback_receipts: dict[str, str] = Field(
        default_factory=dict, max_length=64
    )

    @model_validator(mode="after")
    def require_loading_authority(self):
        if len(set(self.responds_to_feedback_ids)) != len(
            self.responds_to_feedback_ids
        ) or set(self.responds_to_feedback_ids) != set(self.expected_feedback_receipts):
            raise ValueError(
                "feedback IDs must be unique and exactly match expected receipts"
            )
        if any(
            not key.startswith("vfeedback_") or len(key) != 34
            for key in self.responds_to_feedback_ids
        ):
            raise ValueError("invalid visual feedback identifier")
        if any(
            len(value) != 64 or any(c not in "0123456789abcdef" for c in value)
            for value in self.expected_feedback_receipts.values()
        ):
            raise ValueError("invalid visual feedback digest")
        if self.initialization == "REGISTERED_WEIGHTS":
            if not (
                self.initial_model_id
                and self.expected_weights_sha256
                and self.operator_attests_trusted_weights
                and self.operator_attests_pickle_load_risk
            ):
                raise ValueError(
                    "registered weights require separate named trusted pickle-load authority"
                )
        elif (
            self.initial_model_id is not None
            or self.expected_weights_sha256 is not None
        ):
            raise ValueError("random initialization cannot silently load a checkpoint")
        return self


class VisionRunAction(VisionRequest):
    expected_run_sha256: str = Field(pattern=SHA)
    operator_attests_reviewed: Literal[True]


class SelectVisionModel(VisionRunAction):
    action: Literal["APPROVE_SANDBOX", "REJECT"]
    expected_candidate_weights_sha256: str = Field(pattern=SHA)


class ApproveNormalityModelPack(VisionRequest):
    action: Literal["APPROVE_SANDBOX", "REJECT"]
    expected_model_receipt_sha256: str = Field(pattern=SHA)
    expected_model_pack_sha256: str = Field(pattern=SHA)
    expected_backbone_weights_sha256: str = Field(pattern=SHA)
    expected_source_binding_sha256: str = Field(pattern=SHA)
    expected_source_index_sha256: str = Field(pattern=SHA)
    runtime_id: str = Field(pattern=OPAQUE)
    expected_runtime_sha256: str = Field(pattern=SHA)
    operator_attests_reviewed: Literal[True]
    operator_attests_trusted_runtime: Literal[True]
    operator_attests_execution_authorized: Literal[True]
    operator_attests_trusted_weights: Literal[True]
    operator_attests_weights_only_load_authorized: Literal[True]
    ultralytics_license_acknowledged: Literal[True]


class RunNormalityInference(VisionRequest):
    expected_model_receipt_sha256: str = Field(pattern=SHA)
    expected_model_pack_sha256: str = Field(pattern=SHA)
    expected_backbone_weights_sha256: str = Field(pattern=SHA)
    expected_source_binding_sha256: str = Field(pattern=SHA)
    expected_source_index_sha256: str = Field(pattern=SHA)
    expected_runtime_sha256: str = Field(pattern=SHA)
    asset_id: str = Field(pattern=OPAQUE)
    expected_asset_receipt_sha256: str = Field(pattern=SHA)
    expected_image_sha256: str = Field(pattern=SHA)
    max_seconds: int = Field(default=120, ge=5, le=300, strict=True)
    operator_attests_execution_authorized: Literal[True]
    operator_attests_trusted_runtime: Literal[True]
    operator_attests_trusted_weights: Literal[True]
    operator_attests_weights_only_load_authorized: Literal[True]


class ReviewVisionFeedback(VisionRunAction):
    expected_feedback_sha256: str = Field(pattern=SHA)
    classification: Literal[
        "MODEL_ERROR", "LABEL_REVIEW_REQUIRED", "HARD_SAMPLE", "UNKNOWN"
    ]


class ReviewNormalityInference(VisionRequest):
    expected_inference_sha256: str = Field(pattern=SHA)
    operator_attests_reviewed: Literal[True]
    classification: Literal[
        "MODEL_SIGNAL_CONFIRMED",
        "LIKELY_FALSE_POSITIVE",
        "NEEDS_LABEL_REVIEW",
        "INSUFFICIENT_EVIDENCE",
    ]


def _sha(value) -> str:
    return hashlib.sha256(canonical_jcs_bytes(value)).hexdigest()


def _seal(value: dict) -> dict:
    stable = {key: item for key, item in value.items() if key != "receipt_sha256"}
    return stable | {"receipt_sha256": _sha(stable)}


def _now() -> str:
    return datetime.now(UTC).isoformat()


def _normality_backend_sha256() -> str:
    """Return the exact local inference implementation identity in use now."""

    from . import normality_inference

    return normality_inference._sha(Path(normality_inference.__file__).resolve())


def _dataset_content_identity(dataset: dict) -> str:
    receipt = dataset["dataset_receipt"]
    rows = [
        {key: sample[key] for key in ("pixel_sha256", "label_sha256", "split")}
        for sample in receipt["samples"]
    ]
    return _sha(
        {"class_names": receipt["class_names"], "samples": sorted(rows, key=_sha)}
    )


def _file(path: str | Path, expected: str, error: str) -> Path:
    candidate = Path(path).expanduser()
    if not candidate.is_absolute():
        raise VisionModelError("ABSOLUTE_LOCAL_PATH_REQUIRED")
    for member in (candidate, *candidate.parents):
        try:
            info = member.lstat()
        except OSError:
            raise VisionModelError("LOCAL_FILE_UNAVAILABLE") from None
        if stat.S_ISLNK(info.st_mode) or getattr(info, "st_file_attributes", 0) & 0x400:
            raise VisionModelError("LOCAL_LINK_FORBIDDEN")
    digest = hashlib.sha256()
    try:
        with candidate.open("rb") as stream:
            before = candidate.stat()
            if not stat.S_ISREG(before.st_mode) or before.st_size > 2 * 1024**3:
                raise VisionModelError("FILE_SIZE_OR_TYPE_UNSUPPORTED")
            while chunk := stream.read(1024 * 1024):
                digest.update(chunk)
            after = candidate.stat()
    except OSError:
        raise VisionModelError("LOCAL_FILE_UNAVAILABLE") from None
    if (before.st_size, before.st_mtime_ns, before.st_ino) != (
        after.st_size,
        after.st_mtime_ns,
        after.st_ino,
    ) or not hmac.compare_digest(expected, digest.hexdigest()):
        raise VisionModelError(error)
    return candidate.resolve(strict=True)


def _registry_member_is_link(path: Path) -> bool:
    """Detect symbolic links and Windows junction/reparse points lexically."""

    try:
        info = path.lstat()
    except FileNotFoundError:
        info = None
    except OSError:
        raise VisionModelError("REGISTRY_PATH_UNAVAILABLE") from None
    try:
        junction = path.is_junction()
    except OSError:
        raise VisionModelError("REGISTRY_PATH_UNAVAILABLE") from None
    return bool(
        junction
        or (info is not None and stat.S_ISLNK(info.st_mode))
        or (
            info is not None
            and getattr(info, "st_file_attributes", 0) & 0x400
        )
    )


def _assert_registry_path(registry_root: Path, candidate: Path) -> Path:
    """Fail closed when a registry-owned path can escape through a link."""

    root = Path(registry_root).expanduser().absolute()
    target = Path(candidate).expanduser().absolute()
    try:
        relative = target.relative_to(root)
    except ValueError:
        raise VisionModelError("REGISTRY_PATH_ESCAPE") from None
    members = [root]
    member = root
    for part in relative.parts:
        if part in {"", ".", ".."}:
            raise VisionModelError("REGISTRY_PATH_ESCAPE")
        member /= part
        members.append(member)
    for member in members:
        if _registry_member_is_link(member):
            raise VisionModelError("REGISTRY_PATH_LINK_FORBIDDEN")
    if root.exists():
        try:
            resolved_root = root.resolve(strict=True)
            existing = next(value for value in reversed(members) if value.exists())
            existing.resolve(strict=True).relative_to(resolved_root)
        except (OSError, StopIteration, ValueError):
            raise VisionModelError("REGISTRY_PATH_ESCAPE") from None
    return target


def _ensure_registry_directory(registry_root: Path, directory: Path) -> Path:
    """Create a registry directory with checks on both sides of mkdir."""

    target = _assert_registry_path(registry_root, directory)
    try:
        target.mkdir(parents=True, exist_ok=True)
    except OSError:
        raise VisionModelError("REGISTRY_DIRECTORY_UNAVAILABLE") from None
    target = _assert_registry_path(registry_root, target)
    if not target.is_dir():
        raise VisionModelError("REGISTRY_DIRECTORY_UNAVAILABLE")
    return target


def _rebuild_normality_stability_summary(directories: list[str]) -> dict:
    from .model_stability import build_model_stability_summary

    return build_model_stability_summary(directories)


def _verify_normality_pack_registration_evidence(
    request: RegisterNormalityModelPack,
) -> dict:
    """Verify the opaque pack's detached evidence without deserializing it."""

    from .public_governance_bench import (
        PublicSourceBinding,
        VisaSourceIndex,
        verify_public_source_binding,
        verify_visa_source_index,
    )

    def json_artifact(path: str | Path, expected: str, error: str) -> tuple[Path, dict]:
        verified = _file(path, expected, error)
        if verified.stat().st_size > 64 * 1024 * 1024:
            raise VisionModelError("NORMALITY_EVIDENCE_JSON_TOO_LARGE")
        try:
            raw = verified.read_bytes()
            value = json.loads(raw.decode("utf-8"))
        except (OSError, UnicodeDecodeError, json.JSONDecodeError):
            raise VisionModelError("NORMALITY_EVIDENCE_JSON_INVALID") from None
        if not isinstance(value, dict):
            raise VisionModelError("NORMALITY_EVIDENCE_OBJECT_REQUIRED")
        if not hmac.compare_digest(hashlib.sha256(raw).hexdigest(), expected):
            raise VisionModelError(error)
        return verified, value

    def false(value: dict, field: str, artifact: str) -> None:
        if value.get(field) is not False:
            raise VisionModelError(f"{artifact}_{field}_MUST_REMAIN_FALSE".upper())

    run_root = Path(request.run_directory).expanduser()
    if not run_root.is_absolute():
        raise VisionModelError("ABSOLUTE_LOCAL_PATH_REQUIRED")
    try:
        run_root = run_root.resolve(strict=True)
    except OSError:
        raise VisionModelError("NORMALITY_RUN_DIRECTORY_UNAVAILABLE") from None
    if not run_root.is_dir() or run_root.is_symlink() or run_root.is_junction():
        raise VisionModelError("NORMALITY_RUN_DIRECTORY_INVALID")
    try:
        stability_roots = [
            Path(value).expanduser().resolve(strict=True)
            for value in request.stability_run_directories
        ]
    except OSError:
        raise VisionModelError("NORMALITY_STABILITY_RUN_UNAVAILABLE") from None
    if (
        len(set(stability_roots)) != 3
        or run_root not in stability_roots
        or any(
            not value.is_dir() or value.is_symlink() or value.is_junction()
            for value in stability_roots
        )
    ):
        raise VisionModelError("NORMALITY_STABILITY_RUN_SET_INVALID")

    pack = _file(
        request.model_pack_path,
        request.expected_model_pack_sha256,
        "MODEL_PACK_CHANGED",
    )
    _backbone = _file(
        request.backbone_weights_path,
        request.expected_backbone_weights_sha256,
        "BACKBONE_WEIGHTS_CHANGED",
    )
    _summary_path, summary = json_artifact(
        request.stability_summary_path,
        request.expected_stability_summary_sha256,
        "STABILITY_SUMMARY_CHANGED",
    )
    _binding_path, binding_value = json_artifact(
        request.source_binding_path,
        request.expected_source_binding_file_sha256,
        "SOURCE_BINDING_FILE_CHANGED",
    )
    _index_path, index_value = json_artifact(
        request.source_index_path,
        request.expected_source_index_file_sha256,
        "SOURCE_INDEX_FILE_CHANGED",
    )
    try:
        binding = PublicSourceBinding.model_validate(binding_value)
        index = VisaSourceIndex.model_validate(index_value)
        verify_public_source_binding(binding)
        verify_visa_source_index(index, source_binding=binding)
    except (TypeError, ValueError):
        raise VisionModelError("PUBLIC_SOURCE_EVIDENCE_INVALID") from None
    if (
        not hmac.compare_digest(
            binding.binding_sha256, request.expected_source_binding_sha256
        )
        or not hmac.compare_digest(
            index.index_sha256, request.expected_source_index_sha256
        )
    ):
        raise VisionModelError("PUBLIC_SOURCE_EVIDENCE_CHANGED")

    false(summary, "production_release_allowed", "stability_summary")
    runs = summary.get("runs")
    promotion = summary.get("promotion_gate")
    comparability = summary.get("comparability")
    outcomes = summary.get("outcome_requirements")
    if (
        summary.get("schema_version") != "visiondata-gate.model-stability.v4"
        or summary.get("evaluated_run_count") != 3
        or not isinstance(runs, list)
        or len(runs) != 3
        or not isinstance(promotion, dict)
        or not isinstance(comparability, dict)
        or not isinstance(outcomes, dict)
    ):
        raise VisionModelError("MODEL_STABILITY_CONTRACT_INVALID")
    try:
        rebuilt = _rebuild_normality_stability_summary(
            [str(value) for value in stability_roots]
        )
    except (OSError, TypeError, ValueError):
        raise VisionModelError("MODEL_STABILITY_REBUILD_FAILED") from None
    if rebuilt != summary:
        raise VisionModelError("MODEL_STABILITY_SUMMARY_NOT_REPRODUCIBLE")
    verification = summary.get("verification_implementation")
    evidence_contract = summary.get("evidence_contract")
    required_artifacts = {
        "RUN_RECEIPT.json",
        "agent_runtime_events.json",
        "model_experiment_agent_receipt.json",
        "model_experiment_plan.json",
        "model_result.json",
        "private/worker/best_normality_model_pack.pt",
        "private/worker_result.json",
        "selection_manifest.json",
    }
    if (
        not isinstance(verification, dict)
        or not isinstance(evidence_contract, dict)
        or not isinstance(verification.get("stability_module_sha256"), str)
        or not isinstance(verification.get("outcome_policy_module_sha256"), str)
        or not bool(re.fullmatch(SHA, verification["stability_module_sha256"]))
        or not bool(re.fullmatch(SHA, verification["outcome_policy_module_sha256"]))
        or verification.get("outcome_policy_function")
        != "classify_experiment_outcome"
        or set(evidence_contract.get("required_artifacts", []))
        != required_artifacts
        or evidence_contract.get("model_pack_schema_version")
        != "visiondata-gate.yolo26-normality-model-pack.v2"
        or evidence_contract.get("model_pack_deserialization")
        != "NOT_PERFORMED_NO_TORCH_IMPORT"
        or evidence_contract.get("evaluation_membership_source")
        != "PRIVATE_WORKER_RESULT"
        or evidence_contract.get("outcome_derivation")
        != "RECOMPUTED_WITH_BOUND_CLASSIFY_EXPERIMENT_OUTCOME"
    ):
        raise VisionModelError("MODEL_STABILITY_VERIFIER_IDENTITY_INVALID")
    labels = [item.get("run_label") for item in runs if isinstance(item, dict)]
    if len(labels) != 3 or len(set(labels)) != 3 or any(not label for label in labels):
        raise VisionModelError("MODEL_STABILITY_RUN_SET_INVALID")
    stable = (
        promotion.get("status") == "PUBLIC_PROXY_STABLE"
        and promotion.get("eligible") is True
    )
    held = (
        promotion.get("status") == "MODEL_PROMOTION_HOLD"
        and promotion.get("eligible") is False
    )
    blockers = promotion.get("blockers")
    if (
        not isinstance(blockers, list)
        or not (stable or held)
        or (stable and blockers)
        or (held and not blockers)
    ):
        raise VisionModelError("MODEL_STABILITY_PROMOTION_INVALID")
    if stable and (
        comparability.get("status") != "PASS"
        or any(value is not True for value in outcomes.values())
        or any(
            value is not True
            for value in (promotion.get("criterion_checks") or {}).values()
        )
    ):
        raise VisionModelError("MODEL_STABILITY_FALSE_PASS")

    target = next(
        (
            item
            for item in runs
            if isinstance(item, dict) and item.get("run_label") == run_root.name
        ),
        None,
    )
    artifacts = target.get("artifact_sha256") if isinstance(target, dict) else None
    required = required_artifacts
    if (
        not isinstance(artifacts, dict)
        or set(artifacts) != required
        or any(not isinstance(value, str) for value in artifacts.values())
    ):
        raise VisionModelError("MODEL_STABILITY_TARGET_RUN_UNBOUND")

    _run_receipt_path, run_receipt = json_artifact(
        run_root / "RUN_RECEIPT.json",
        artifacts["RUN_RECEIPT.json"],
        "RUN_RECEIPT_CHANGED",
    )
    referenced = {
        "model_result.json": "model_result_file_sha256",
        "model_experiment_plan.json": "plan_file_sha256",
        "selection_manifest.json": "selection_manifest_sha256",
    }
    loaded: dict[str, dict] = {}
    for name, reference in referenced.items():
        expected = run_receipt.get(reference)
        if expected != artifacts[name]:
            raise VisionModelError("RUN_RECEIPT_ARTIFACT_BINDING_INVALID")
        _path, loaded[name] = json_artifact(
            run_root / name, expected, "RUN_ARTIFACT_CHANGED"
        )
    agent_expected = artifacts["model_experiment_agent_receipt.json"]
    if run_receipt.get("agent_receipt_file_sha256") != agent_expected:
        raise VisionModelError("AGENT_RECEIPT_BINDING_REQUIRED")
    _agent_path, agent = json_artifact(
        run_root / "model_experiment_agent_receipt.json",
        agent_expected,
        "AGENT_RECEIPT_CHANGED",
    )
    plan = loaded["model_experiment_plan.json"]
    result = loaded["model_result.json"]
    selection = loaded["selection_manifest.json"]
    private_result_expected = artifacts["private/worker_result.json"]
    _private_result_path, private_result = json_artifact(
        run_root / "private" / "worker_result.json",
        private_result_expected,
        "PRIVATE_WORKER_RESULT_CHANGED",
    )
    event_expected = artifacts["agent_runtime_events.json"]
    if run_receipt.get("runtime_event_file_sha256") != event_expected:
        raise VisionModelError("RUNTIME_EVENT_FILE_BINDING_INVALID")
    _file(
        run_root / "agent_runtime_events.json",
        event_expected,
        "RUNTIME_EVENT_FILE_CHANGED",
    )
    for artifact_name, artifact in (
        ("RUN_RECEIPT", run_receipt),
        ("MODEL_RESULT", result),
        ("MODEL_PLAN", plan),
        ("AGENT_RECEIPT", agent),
        ("SELECTION_MANIFEST", selection),
        ("PRIVATE_WORKER_RESULT", private_result),
    ):
        false(artifact, "production_release_allowed", artifact_name)
    false(run_receipt, "machine_write_permitted", "run_receipt")
    false(plan, "machine_write_permitted", "model_plan")
    false(agent, "machine_write_permitted", "agent_receipt")
    if plan != _seal(plan) or agent != _seal(agent):
        raise VisionModelError("MODEL_EVIDENCE_RECEIPT_MISMATCH")

    checkpoint = result.get("checkpoint")
    if not isinstance(checkpoint, dict):
        raise VisionModelError("MODEL_PACK_CHECKPOINT_EVIDENCE_REQUIRED")
    relative = checkpoint.get("relative_path")
    if not isinstance(relative, str) or not relative:
        raise VisionModelError("MODEL_PACK_RELATIVE_PATH_REQUIRED")
    expected_pack_location = (run_root / relative).resolve(strict=True)
    try:
        expected_pack_location.relative_to(run_root)
    except ValueError:
        raise VisionModelError("MODEL_PACK_PATH_ESCAPE") from None
    if expected_pack_location != pack:
        raise VisionModelError("MODEL_PACK_PATH_NOT_BOUND_TO_RUN")
    if artifacts["private/worker/best_normality_model_pack.pt"] != (
        request.expected_model_pack_sha256
    ):
        raise VisionModelError("MODEL_STABILITY_PACK_BINDING_INVALID")
    pack_schema = checkpoint.get("schema_version")
    if pack_schema not in {
        "visiondata-gate.yolo26-normality-model-pack.v1",
        "visiondata-gate.yolo26-normality-model-pack.v2",
    }:
        raise VisionModelError("MODEL_PACK_SCHEMA_UNSUPPORTED")
    if pack_schema != "visiondata-gate.yolo26-normality-model-pack.v2":
        raise VisionModelError("MODEL_PACK_V2_REQUIRED")
    roundtrip = checkpoint.get("roundtrip_validation")
    if (
        checkpoint.get("sha256") != request.expected_model_pack_sha256
        or run_receipt.get("checkpoint_sha256")
        != request.expected_model_pack_sha256
        or agent.get("checkpoint_sha256") != request.expected_model_pack_sha256
        or not isinstance(roundtrip, dict)
        or roundtrip.get("checkpoint_sha256") != request.expected_model_pack_sha256
        or roundtrip.get("all_tensors_cpu_and_finite") is not True
        or roundtrip.get("backbone_state_dict_reload") != "PASS"
        or not isinstance(roundtrip.get("student_state_dict_reload"), dict)
        or any(
            value != "PASS"
            for value in roundtrip["student_state_dict_reload"].values()
        )
    ):
        raise VisionModelError("MODEL_PACK_ROUNDTRIP_EVIDENCE_INVALID")
    normalization = (checkpoint.get("validation_view") or {}).get(
        "input_normalization"
    )
    if pack_schema.endswith(".v2") and (
        not isinstance(normalization, dict)
        or normalization.get("mean") != [0.0, 0.0, 0.0]
        or normalization.get("std") != [1.0, 1.0, 1.0]
    ):
        raise VisionModelError("MODEL_PACK_V2_PREPROCESSING_EVIDENCE_INVALID")

    architecture = result.get("architecture")
    layers = result.get("feature_layers")
    split_seed = result.get("split_seed")
    model_seed = result.get("model_seed")
    source_binding_sha256 = request.expected_source_binding_sha256
    source_index_sha256 = request.expected_source_index_sha256
    backbone_sha256 = request.expected_backbone_weights_sha256
    if model_seed != request.target_model_seed:
        raise VisionModelError("PREDECLARED_TARGET_MODEL_SEED_MISMATCH")
    for artifact in (run_receipt, plan):
        if artifact.get("architecture") != architecture:
            raise VisionModelError("MODEL_PACK_RUN_CONTRACT_MISMATCH")
    for artifact in (run_receipt, plan, agent):
        for field, expected in (
            ("feature_layers", layers),
            ("split_seed", split_seed),
            ("model_seed", model_seed),
        ):
            if artifact.get(field) != expected:
                raise VisionModelError("MODEL_PACK_RUN_CONTRACT_MISMATCH")
    if (
        plan.get("source_binding_sha256") != source_binding_sha256
        or agent.get("source_binding_sha256") != source_binding_sha256
        or plan.get("source_index_sha256") != source_index_sha256
        or agent.get("source_index_sha256") != source_index_sha256
        or result.get("backbone_weights_sha256") != backbone_sha256
        or run_receipt.get("backbone_weights_sha256") != backbone_sha256
    ):
        raise VisionModelError("MODEL_PACK_PROVENANCE_MISMATCH")
    agent_evidence = target.get("agent_evidence_sha256")
    if (
        not isinstance(agent_evidence, dict)
        or agent_evidence.get("agent_receipt_self_seal_sha256")
        != agent.get("receipt_sha256")
        or agent_evidence.get("private_execution_result_sha256")
        != private_result_expected
        or agent.get("execution_result_sha256") != private_result_expected
        or agent_evidence.get("runtime_event_chain_sha256")
        != agent.get("runtime_event_chain_sha256")
    ):
        raise VisionModelError("MODEL_STABILITY_AGENT_EVIDENCE_INVALID")

    return {
        "pack_schema_version": pack_schema,
        "architecture": architecture,
        "feature_layers": layers,
        "split_seed": split_seed,
        "model_seed": model_seed,
        "stability_schema_version": summary["schema_version"],
        "verification_implementation": dict(verification),
        "stability_status": promotion["status"],
        "stability_eligible": promotion["eligible"],
        "stability_blockers": list(blockers),
        "source_binding_sha256": source_binding_sha256,
        "source_index_sha256": source_index_sha256,
        "backbone_weights_sha256": backbone_sha256,
        "stability_runs": {
            item["run_label"]: dict(item["artifact_sha256"])
            for item in runs
        },
        "evidence_file_sha256": {
            "model_pack": request.expected_model_pack_sha256,
            "stability_summary": request.expected_stability_summary_sha256,
            "source_binding_file": request.expected_source_binding_file_sha256,
            "source_index_file": request.expected_source_index_file_sha256,
            "backbone_weights": request.expected_backbone_weights_sha256,
            "RUN_RECEIPT.json": artifacts["RUN_RECEIPT.json"],
            "model_result.json": artifacts["model_result.json"],
            "model_experiment_plan.json": artifacts[
                "model_experiment_plan.json"
            ],
            "selection_manifest.json": artifacts["selection_manifest.json"],
            "model_experiment_agent_receipt.json": agent_expected,
            "agent_runtime_events.json": event_expected,
            "private/worker_result.json": private_result_expected,
        },
    }


def _cas_copy(registry_root: Path, source: str | Path, expected: str) -> Path:
    source_path = _file(source, expected, "CAS_SOURCE_CHANGED")
    root = _ensure_registry_directory(
        registry_root, Path(registry_root) / "cas" / "sha256"
    )
    destination_parent = _ensure_registry_directory(
        registry_root, root / expected[:2]
    )
    destination = _assert_registry_path(
        registry_root, destination_parent / expected
    )
    if destination.exists():
        return _file(destination, expected, "CAS_CONTENT_MISMATCH")
    try:
        with source_path.open("rb") as input_stream, destination.open("xb") as output:
            shutil.copyfileobj(input_stream, output, length=1024 * 1024)
        _assert_registry_path(registry_root, destination)
    except FileExistsError:
        return _file(destination, expected, "CAS_CONTENT_MISMATCH")
    except Exception:
        try:
            _assert_registry_path(registry_root, destination)
        except VisionModelError:
            pass
        else:
            destination.unlink(missing_ok=True)
        raise
    if _file(source_path, expected, "CAS_SOURCE_CHANGED") != source_path:
        raise VisionModelError("CAS_SOURCE_CHANGED")
    return _file(destination, expected, "CAS_CONTENT_MISMATCH")


def _store_normality_pack_cas(
    registry_root: Path,
    request: RegisterNormalityModelPack,
    evidence: dict,
) -> dict:
    hashes = evidence["evidence_file_sha256"]
    sources = {
        "stability_summary": request.stability_summary_path,
        "source_binding": request.source_binding_path,
        "source_index": request.source_index_path,
    }
    expected = {
        "stability_summary": hashes["stability_summary"],
        "source_binding": hashes["source_binding_file"],
        "source_index": hashes["source_index_file"],
    }
    roots = {
        Path(value).resolve(strict=True).name: Path(value).resolve(strict=True)
        for value in request.stability_run_directories
    }
    if set(roots) != set(evidence["stability_runs"]):
        raise VisionModelError("MODEL_STABILITY_RUN_DIRECTORY_LABEL_MISMATCH")
    for run_label, artifact_hashes in evidence["stability_runs"].items():
        for relative, digest in artifact_hashes.items():
            pure = PurePosixPath(relative)
            if pure.is_absolute() or any(part in {"", ".", ".."} for part in pure.parts):
                raise VisionModelError("MODEL_STABILITY_ARTIFACT_PATH_INVALID")
            logical = f"runs/{run_label}/{relative}"
            sources[logical] = roots[run_label] / Path(*pure.parts)
            expected[logical] = digest
    target_label = Path(request.run_directory).resolve(strict=True).name
    model_pack_key = (
        f"runs/{target_label}/private/worker/best_normality_model_pack.pt"
    )
    if expected.get(model_pack_key) != request.expected_model_pack_sha256:
        raise VisionModelError("MODEL_PACK_CAS_TARGET_UNBOUND")
    stored = {
        name: str(_cas_copy(registry_root, sources[name], expected[name]))
        for name in sources
    }
    manifest = _seal(
        {
            "schema_version": "visiondata-gate.normality-model-pack-cas.v1",
            "files": expected,
            "target_run_label": target_label,
            "model_pack_key": model_pack_key,
            "model_pack_schema_version": evidence["pack_schema_version"],
            "stability_schema_version": evidence["stability_schema_version"],
            "verification_implementation": evidence["verification_implementation"],
            "stability_runs": evidence["stability_runs"],
            "source_binding_sha256": evidence["source_binding_sha256"],
            "source_index_sha256": evidence["source_index_sha256"],
            "backbone_weights_sha256": evidence["backbone_weights_sha256"],
            "production_release_allowed": False,
        }
    )
    return {"cas_files": stored, "cas_manifest": manifest}


def _verify_normality_pack_cas(
    registry_root: Path,
    model: dict,
    private: dict,
) -> dict[str, Path]:
    from .public_governance_bench import (
        PublicSourceBinding,
        VisaSourceIndex,
        verify_public_source_binding,
        verify_visa_source_index,
    )

    manifest = private.get("cas_manifest")
    files = private.get("cas_files")
    if (
        not isinstance(manifest, dict)
        or manifest != _seal(manifest)
        or not isinstance(files, dict)
        or set(files) != set(manifest.get("files", {}))
        or manifest.get("production_release_allowed") is not False
    ):
        raise VisionModelError("MODEL_PACK_CAS_MANIFEST_INVALID")
    cas_root = (registry_root / "cas" / "sha256").resolve(strict=True)
    verified: dict[str, Path] = {}
    for name, expected in manifest["files"].items():
        path = Path(files[name]).resolve(strict=True)
        try:
            path.relative_to(cas_root)
        except ValueError:
            raise VisionModelError("MODEL_PACK_CAS_PATH_ESCAPE") from None
        if path.name != expected:
            raise VisionModelError("MODEL_PACK_CAS_ADDRESS_MISMATCH")
        verified[name] = _file(path, expected, "MODEL_PACK_CAS_CONTENT_CHANGED")
    if (
        manifest.get("model_pack_schema_version")
        != model.get("model_pack_schema_version")
        or manifest.get("stability_schema_version")
        != model.get("stability_schema_version")
        or manifest.get("verification_implementation")
        != model.get("verification_implementation")
        or manifest.get("stability_runs")
        != model.get("stability_run_artifact_sha256")
        or manifest.get("source_binding_sha256")
        != model.get("source_binding_sha256")
        or manifest.get("source_index_sha256") != model.get("source_index_sha256")
        or manifest.get("backbone_weights_sha256")
        != model.get("backbone_weights_sha256")
        or manifest["files"].get(manifest.get("model_pack_key"))
        != model.get("model_pack_sha256")
    ):
        raise VisionModelError("MODEL_PACK_CAS_IDENTITY_MISMATCH")
    try:
        binding = PublicSourceBinding.model_validate(
            json.loads(verified["source_binding"].read_text(encoding="utf-8"))
        )
        index = VisaSourceIndex.model_validate(
            json.loads(verified["source_index"].read_text(encoding="utf-8"))
        )
        verify_public_source_binding(binding)
        verify_visa_source_index(index, source_binding=binding)
        summary = json.loads(
            verified["stability_summary"].read_text(encoding="utf-8")
        )
        target = manifest.get("target_run_label")
        result_key = f"runs/{target}/model_result.json"
        result = json.loads(verified[result_key].read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError, TypeError, ValueError):
        raise VisionModelError("MODEL_PACK_CAS_EVIDENCE_INVALID") from None
    if (
        binding.binding_sha256 != model.get("source_binding_sha256")
        or index.index_sha256 != model.get("source_index_sha256")
        or summary.get("schema_version") != "visiondata-gate.model-stability.v4"
        or summary.get("verification_implementation")
        != model.get("verification_implementation")
        or summary.get("promotion_gate", {}).get("status")
        != model.get("stability_status")
        or summary.get("promotion_gate", {}).get("eligible")
        is not model.get("stability_eligible")
        or summary.get("production_release_allowed") is not False
        or result.get("checkpoint", {}).get("schema_version")
        != model.get("model_pack_schema_version")
        or result.get("checkpoint", {}).get("sha256")
        != model.get("model_pack_sha256")
        or result.get("production_release_allowed") is not False
    ):
        raise VisionModelError("MODEL_PACK_CAS_EVIDENCE_MISMATCH")
    verified["model_pack"] = verified[manifest["model_pack_key"]]
    return verified


class LocalVisionModelService:
    """Use existing project membership, transactions and explicit per-request work."""

    def __init__(self, product, *, _test_only_allow_unbound_fixtures: bool = False):
        if type(_test_only_allow_unbound_fixtures) is not bool:
            raise TypeError("_test_only_allow_unbound_fixtures must be a boolean")
        self.product = product
        self.root = product.product_root / "vision_models"
        # Test-only seam for lifecycle doubles. API and production call sites always
        # use the fail-closed default and therefore require a governed Data Pool.
        self._test_only_allow_unbound_fixtures = _test_only_allow_unbound_fixtures

    def _authorize(self, actor, project):
        self.product.store.get_project(actor, project)
        if self.root.exists() and (self.root.is_symlink() or self.root.is_junction()):
            raise VisionModelError("REGISTRY_ROOT_LINK_FORBIDDEN")
        self.root.mkdir(exist_ok=True)
        with self.product.store._connection(immediate=True) as conn:
            conn.execute(
                "CREATE TABLE IF NOT EXISTS vision_records (id TEXT PRIMARY KEY, project_id TEXT NOT NULL, kind TEXT NOT NULL, body TEXT NOT NULL, private_body TEXT NOT NULL)"
            )
            conn.execute(
                "CREATE TABLE IF NOT EXISTS vision_requests (project_id TEXT NOT NULL, actor TEXT NOT NULL, operation TEXT NOT NULL, request_key TEXT NOT NULL, request_sha TEXT NOT NULL, result_id TEXT NOT NULL, PRIMARY KEY(project_id, actor, operation, request_key))"
            )
            conn.execute(
                "CREATE TABLE IF NOT EXISTS vision_split_members (project_id TEXT NOT NULL, kind TEXT NOT NULL, value TEXT NOT NULL, split TEXT NOT NULL, PRIMARY KEY(project_id,kind,value))"
            )

    def _membership(self, conn, actor, project):
        row = conn.execute(
            "SELECT workspace_id FROM projects WHERE project_id=?", (project,)
        ).fetchone()
        if row is None:
            raise NotFoundError("visual project unavailable")
        self.product.store._require_membership(conn, row[0], actor)

    def _read(self, conn, project, identifier, kind=None):
        row = conn.execute(
            "SELECT kind,body,private_body FROM vision_records WHERE id=? AND project_id=?",
            (identifier, project),
        ).fetchone()
        if row is None or (kind and row[0] != kind):
            raise NotFoundError("visual resource unavailable")
        value = json.loads(row[1])
        if value != _seal(value):
            raise VisionModelError("REGISTRY_RECEIPT_MISMATCH")
        return value, json.loads(row[2])

    def _put(self, conn, value, kind, private=None, *, replace=False):
        identifier = value["resource_id"]
        sealed = _seal(value)
        if replace:
            conn.execute(
                "UPDATE vision_records SET body=? WHERE id=? AND project_id=?",
                (json.dumps(sealed), identifier, value["project_id"]),
            )
        else:
            conn.execute(
                "INSERT INTO vision_records VALUES (?,?,?,?,?)",
                (
                    identifier,
                    value["project_id"],
                    kind,
                    json.dumps(sealed),
                    json.dumps(private or {}),
                ),
            )
        return sealed

    def _base(self, project, kind, actor, request):
        identifier = kind + "_" + uuid4().hex[:24]
        return {
            "schema_version": f"visiondata-gate.{kind}.v1",
            "resource_id": identifier,
            "project_id": project,
            "created_by": actor,
            "reviewer_identity": request.reviewer_identity,
            "created_at": _now(),
            "production_release_allowed": False,
            "machine_write_permitted": False,
        }

    @contextmanager
    def _operation(self, actor, project, operation, request):
        type(request).model_validate(request.model_dump(mode="json"))
        self._authorize(actor, project)
        with task_execution_lock(
            self.product.product_root,
            f"vision:{project}:{actor}:{operation}:{request.request_key}",
        ) as acquired:
            if not acquired:
                raise VisionModelError("OPERATION_IN_PROGRESS")
            with self.product.store._connection() as conn:
                row = conn.execute(
                    "SELECT request_sha,result_id FROM vision_requests WHERE project_id=? AND actor=? AND operation=? AND request_key=?",
                    (project, actor, operation, request.request_key),
                ).fetchone()
                if row and row[0] != _sha(request.model_dump(mode="json")):
                    raise VisionModelError("IDEMPOTENCY_CONFLICT")
                existing = self._read(conn, project, row[1])[0] if row else None
            try:
                yield existing
            except (OSError, ValueError, TypeError, KeyError):
                raise VisionModelError(
                    "VISION_INPUT_OR_RUNTIME_CONTRACT_INVALID"
                ) from None

    def _remember(self, conn, actor, project, operation, request, result):
        self._membership(conn, actor, project)
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

    def _list(self, actor, project, kind):
        self._authorize(actor, project)
        with self.product.store._connection() as conn:
            ids = conn.execute(
                "SELECT id FROM vision_records WHERE project_id=? AND kind=? ORDER BY id",
                (project, kind),
            ).fetchall()
            items = [self._read(conn, project, row[0], kind)[0] for row in ids]
        return _seal(
            {
                "schema_version": "visiondata-gate.vision-list.v1",
                "project_id": project,
                "items": items,
            }
        )

    def _get(self, actor, project, identifier, kind):
        self._authorize(actor, project)
        with self.product.store._connection() as conn:
            return self._read(conn, project, identifier, kind)[0]

    def list_models(self, actor, project):
        return self._list(actor, project, "model")

    def list_runtimes(self, actor, project):
        return self._list(actor, project, "runtime")

    def list_datasets(self, actor, project):
        return self._list(actor, project, "dataset")

    def list_runs(self, actor, project):
        return self._list(actor, project, "run")

    def list_inference_assets(self, actor, project):
        return self._list(actor, project, "inference_asset")

    def list_inferences(self, actor, project):
        return self._list(actor, project, "inference")

    def get_model(self, actor, project, identifier):
        return self._get(actor, project, identifier, "model")

    def get_run(self, actor, project, identifier):
        return self._get(actor, project, identifier, "run")

    def get_inference_asset(self, actor, project, identifier):
        return self._get(actor, project, identifier, "inference_asset")

    def get_inference(self, actor, project, identifier):
        return self._get(actor, project, identifier, "inference")

    def _normality_inference_record(self, conn, project, identifier):
        try:
            value, private = self._read(conn, project, identifier, "inference")
        except (ValueError, TypeError, AttributeError):
            raise VisionModelError("REGISTRY_RECEIPT_INVALID") from None
        if not isinstance(value, dict) or not isinstance(private, dict):
            raise VisionModelError("REGISTRY_RECEIPT_INVALID")
        if (
            re.fullmatch(r"vision_inference_[0-9a-f]{24}", identifier) is None
            or value.get("schema_version") != "visiondata-gate.vision_inference.v1"
            or value.get("resource_id") != identifier
            or value.get("inference_id") != identifier
            or value.get("project_id") != project
            or value.get("status") != "COMPLETED_LOCAL_SANDBOX_INFERENCE"
            or value.get("production_release_allowed") is not False
            or value.get("machine_write_permitted") is not False
        ):
            raise VisionModelError("NORMALITY_INFERENCE_NOT_REVIEWABLE")
        return value, private

    def _normality_heatmap_bytes(self, inference, private):
        """Read bounded, hash-verified PNG bytes from the exact registry location.

        Never reopen a path in the HTTP response: the digest is over the exact
        bytes returned, not an earlier file check. Private stored paths are also
        untrusted and cannot redirect an inference to another artifact.
        """
        from PIL import Image

        try:
            output = _assert_registry_path(
                self.root, self.root / "inferences" / inference["inference_id"]
            )
            expected = _assert_registry_path(
                self.root, output / "artifacts" / "heatmap.png"
            )
            if (
                _assert_registry_path(self.root, Path(private["output_root"])) != output
                or _assert_registry_path(self.root, Path(private["heatmap_path"]))
                != expected
            ):
                raise VisionModelError("INFERENCE_HEATMAP_PATH_MISMATCH")
            meta = inference["heatmap"]
            digest = meta["sha256"]
            if (
                not isinstance(digest, str)
                or re.fullmatch(SHA, digest) is None
                or meta.get("format") != "png"
                or type(meta.get("bytes")) is not int
                or not 0 < meta["bytes"] <= 16 * 1024 * 1024
            ):
                raise VisionModelError("INFERENCE_HEATMAP_METADATA_INVALID")
            verified = _file(expected, digest, "INFERENCE_HEATMAP_CHANGED")
            with verified.open("rb") as stream:
                raw = stream.read(16 * 1024 * 1024 + 1)
            _assert_registry_path(self.root, expected)
            if (
                len(raw) != meta["bytes"]
                or not hmac.compare_digest(hashlib.sha256(raw).hexdigest(), digest)
                or raw[:16] != b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR"
                or raw[16:24] != b"\x00\x00\x00\x40\x00\x00\x00\x40"
            ):
                raise VisionModelError("INFERENCE_HEATMAP_CHANGED")
            with Image.open(io.BytesIO(raw)) as image:
                if (
                    image.format != "PNG"
                    or image.size != (meta.get("width"), meta.get("height"))
                    or image.size != (64, 64)
                ):
                    raise VisionModelError("INFERENCE_HEATMAP_PNG_INVALID")
                image.verify()
            return raw, digest
        except (OSError, ValueError, TypeError, KeyError, SyntaxError):
            raise VisionModelError("INFERENCE_HEATMAP_UNAVAILABLE") from None

    def get_inference_heatmap(self, actor, project, identifier):
        self._authorize(actor, project)
        with self.product.store._connection() as conn:
            inference, private = self._normality_inference_record(
                conn, project, identifier
            )
        return self._normality_heatmap_bytes(inference, private)

    def list_normality_feedback(self, actor, project, identifier):
        self._authorize(actor, project)
        with self.product.store._connection() as conn:
            self._normality_inference_record(conn, project, identifier)
        result = self._list(actor, project, "normality_feedback")
        return _seal(
            result | {
                "inference_id": identifier,
                "items": [item for item in result["items"]
                          if item["inference_id"] == identifier],
            }
        )

    def review_normality_inference(
        self, actor, project, identifier, request: ReviewNormalityInference
    ):
        request = ReviewNormalityInference.model_validate(request.model_dump(mode="json"))
        operation = "review_normality_inference:" + identifier
        with self._operation(actor, project, operation, request) as existing:
            if existing:
                return existing
            with self.product.store._connection(immediate=True) as conn:
                self._membership(conn, actor, project)
                inference, private = self._normality_inference_record(
                    conn, project, identifier
                )
                if not hmac.compare_digest(
                    inference["receipt_sha256"], request.expected_inference_sha256
                ):
                    raise VisionModelError("STALE_NORMALITY_INFERENCE")
                _raw, heatmap_sha256 = self._normality_heatmap_bytes(inference, private)
                value = self._base(project, "normality_feedback", actor, request)
                value.update(
                    schema_version="visiondata-gate.normality-feedback.v1",
                    feedback_id=value["resource_id"],
                    inference_id=identifier,
                    model_id=inference["model_id"],
                    asset_id=inference["asset_id"],
                    inference_sha256=inference["receipt_sha256"],
                    image_sha256=inference["image_sha256"],
                    model_pack_sha256=inference["model_pack_sha256"],
                    heatmap_sha256=heatmap_sha256,
                    heatmap_artifact_id=inference["heatmap_artifact_id"],
                    classification=request.classification,
                    note=request.note,
                    status="RECORDED_FOR_HUMAN_FOLLOWUP",
                    followup_work_item_type={
                        "MODEL_SIGNAL_CONFIRMED": "MODEL_SIGNAL_REVIEW",
                        "LIKELY_FALSE_POSITIVE": "FALSE_POSITIVE_INVESTIGATION",
                        "NEEDS_LABEL_REVIEW": "LABEL_REVIEW",
                        "INSUFFICIENT_EVIDENCE": "EVIDENCE_COLLECTION",
                    }[request.classification],
                    followup_work_item_created=False,
                    issue_closed=False,
                    label_truth_authority=False,
                    training_ingestion_allowed=False,
                )
                result = self._put(conn, value, "normality_feedback")
                self._remember(conn, actor, project, operation, request, result)
            return result

    def capabilities(self, actor, project):
        models = self.list_models(actor, project)["items"]
        runtimes = self.list_runtimes(actor, project)["items"]
        datasets = self.list_datasets(actor, project)["items"]
        inference_assets = self.list_inference_assets(actor, project)["items"]
        inferences = self.list_inferences(actor, project)["items"]
        ready_runtimes = [
            r
            for r in runtimes
            if r["probe"].get("status") == "ready" and r["probe"].get("runtime_sha256")
        ]
        training_datasets = [
            dataset
            for dataset in datasets
            if dataset.get("provenance") == "GOVERNED_DATA_POOL_V1"
            and dataset.get("training_eligible") is True
            and dataset.get("pool_binding") is not None
        ]
        return _seal(
            {
                "schema_version": "visiondata-gate.vision-capabilities.v1",
                "project_id": project,
                "model_domain": "LOCAL_VISUAL_MODELS",
                "llm_provider_managed": False,
                "supported_registration_tasks": ["detect", "segment", "normality"],
                "executable_training_tasks": ["detect"],
                "executable_inference_tasks": ["normality"],
                "training_device": "CPU_ONLY",
                "normality_runtime": "EXTERNAL_RUNTIME_REQUIRED",
                "initializations": ["ARCHITECTURE_RANDOM", "REGISTERED_WEIGHTS"],
                "ttt_status": "NORMALITY_EPISODIC_AVAILABLE",
                "ttt_scope": "NORMALITY_ONLY_EPISODIC_NO_PERSISTENCE",
                "weight_download_allowed": False,
                "registered_model_count": len(models),
                "registered_runtime_count": len(runtimes),
                "registered_dataset_count": len(datasets),
                "sandbox_approved_normality_model_count": sum(
                    model.get("model_kind") == "YOLO26_NORMALITY_MODEL_PACK"
                    and model.get("status") == "APPROVE_SANDBOX"
                    for model in models
                ),
                "registered_inference_asset_count": len(inference_assets),
                "completed_normality_inference_count": sum(
                    item.get("status") == "COMPLETED_LOCAL_SANDBOX_INFERENCE"
                    for item in inferences
                ),
                "training_ready": bool(ready_runtimes and training_datasets),
                "training_authorization_required": True,
                "license_boundary": "ULTRALYTICS_AGPL_3_0_OR_ENTERPRISE_REVIEW_REQUIRED",
                "production_release_allowed": False,
                "industrial_effectiveness_status": "NOT_EVALUATED",
            }
        )

    def register_model(self, actor, project, request: RegisterVisionModel):
        request = RegisterVisionModel.model_validate(request.model_dump(mode="json"))
        with self._operation(actor, project, "register_model", request) as existing:
            if existing:
                return existing
            path = _file(
                request.weights_path, request.expected_weights_sha256, "WEIGHTS_CHANGED"
            )
            if path.suffix.lower() not in {".pt", ".onnx", ".safetensors"}:
                raise VisionModelError("MODEL_FORMAT_UNSUPPORTED")
            value = self._base(project, "vision_model", actor, request)
            value.update(
                model_id=value["resource_id"],
                display_name=request.display_name,
                task_type=request.task_type,
                weights_sha256=request.expected_weights_sha256,
                file_bytes=path.stat().st_size,
                format=path.suffix.lower()[1:],
                license_id=request.license_id,
                license_status="OPERATOR_DECLARED_NOT_LEGAL_VERIFICATION",
                source_description=request.source_description,
                status="REGISTERED_NOT_LOADED",
                loaded=False,
            )
            with self.product.store._connection(immediate=True) as conn:
                result = self._put(conn, value, "model", {"weights_path": str(path)})
                self._remember(conn, actor, project, "register_model", request, result)
            return result

    def register_inference_asset(
        self, actor, project, request: RegisterVisionInferenceAsset
    ):
        from PIL import Image

        request = RegisterVisionInferenceAsset.model_validate(
            request.model_dump(mode="json")
        )
        with self._operation(
            actor, project, "register_inference_asset", request
        ) as existing:
            if existing:
                return existing
            source = _file(
                request.image_path,
                request.expected_image_sha256,
                "INFERENCE_IMAGE_CHANGED",
            )
            if (
                source.suffix.lower() not in {".png", ".jpg", ".jpeg", ".bmp"}
                or source.stat().st_size > 64 * 1024 * 1024
            ):
                raise VisionModelError("INFERENCE_IMAGE_FORMAT_OR_SIZE_UNSUPPORTED")
            try:
                with Image.open(source) as decoded:
                    width, height = decoded.size
                    decoded.verify()
            except (OSError, ValueError):
                raise VisionModelError("INFERENCE_IMAGE_DECODE_INVALID") from None
            if not 1 <= width <= 8192 or not 1 <= height <= 8192:
                raise VisionModelError("INFERENCE_IMAGE_DIMENSION_UNSUPPORTED")
            cas_path = _cas_copy(
                self.root,
                source,
                request.expected_image_sha256,
            )
            value = self._base(project, "vision_inference_asset", actor, request)
            value.update(
                asset_id=value["resource_id"],
                display_name=request.display_name,
                image_sha256=request.expected_image_sha256,
                image_bytes=source.stat().st_size,
                image_width=width,
                image_height=height,
                format=source.suffix.lower()[1:],
                storage_scope="REGISTRY_OWNED_CONTENT_ADDRESSED",
                status="FROZEN_LOCAL_INFERENCE_ASSET",
            )
            with self.product.store._connection(immediate=True) as conn:
                result = self._put(
                    conn,
                    value,
                    "inference_asset",
                    {"cas_path": str(cas_path)},
                )
                self._remember(
                    conn, actor, project, "register_inference_asset", request, result
                )
            return result

    def register_normality_model_pack(
        self, actor, project, request: RegisterNormalityModelPack
    ):
        request = RegisterNormalityModelPack.model_validate(
            request.model_dump(mode="json")
        )
        with self._operation(
            actor, project, "register_normality_model_pack", request
        ) as existing:
            if existing:
                return existing
            evidence = _verify_normality_pack_registration_evidence(request)
            schema = evidence["pack_schema_version"]
            stable_v2 = (
                schema == "visiondata-gate.yolo26-normality-model-pack.v2"
                and evidence["stability_schema_version"]
                == "visiondata-gate.model-stability.v4"
                and evidence["stability_status"] == "PUBLIC_PROXY_STABLE"
                and evidence["stability_eligible"] is True
            )
            if schema == "visiondata-gate.yolo26-normality-model-pack.v1":
                status = "LEGACY_PREPROCESSING_CONTRACT_HOLD"
            elif stable_v2:
                status = "MODEL_PACK_EVIDENCE_VERIFIED"
            else:
                status = "RESEARCH_ONLY_HOLD"
            cas = _store_normality_pack_cas(self.root, request, evidence)
            value = self._base(project, "vision_model", actor, request)
            value.update(
                model_id=value["resource_id"],
                display_name=request.display_name,
                model_kind="YOLO26_NORMALITY_MODEL_PACK",
                task_type="normality",
                format="pt",
                model_pack_schema_version=schema,
                model_pack_sha256=request.expected_model_pack_sha256,
                weights_sha256=request.expected_model_pack_sha256,
                backbone_weights_sha256=evidence["backbone_weights_sha256"],
                source_binding_sha256=evidence["source_binding_sha256"],
                source_index_sha256=evidence["source_index_sha256"],
                architecture=evidence["architecture"],
                feature_layers=evidence["feature_layers"],
                split_seed=evidence["split_seed"],
                model_seed=evidence["model_seed"],
                stability_schema_version=evidence["stability_schema_version"],
                verification_implementation=evidence["verification_implementation"],
                stability_run_artifact_sha256=evidence["stability_runs"],
                stability_status=evidence["stability_status"],
                stability_eligible=evidence["stability_eligible"],
                stability_blockers=evidence["stability_blockers"],
                evidence_file_sha256=evidence["evidence_file_sha256"],
                license_id="AGPL-3.0_OR_ENTERPRISE_REVIEW_REQUIRED",
                license_status="OPERATOR_ACKNOWLEDGED_NOT_LEGAL_VERIFICATION",
                status=status,
                usage_scope="SANDBOX_CANDIDATE" if stable_v2 else "RESEARCH_ONLY",
                sandbox_eligible=stable_v2,
                sandbox_runtime_id=None,
                sandbox_runtime_sha256=None,
                loaded=False,
                storage_scope="REGISTRY_OWNED_CONTENT_ADDRESSED",
            )
            private = cas
            with self.product.store._connection(immediate=True) as conn:
                result = self._put(conn, value, "model", private)
                self._remember(
                    conn,
                    actor,
                    project,
                    "register_normality_model_pack",
                    request,
                    result,
                )
            return result

    def approve_normality_model_pack(
        self,
        actor,
        project,
        identifier,
        request: ApproveNormalityModelPack,
    ):
        request = ApproveNormalityModelPack.model_validate(
            request.model_dump(mode="json")
        )
        operation = "approve_normality_model_pack:" + identifier
        with self._operation(actor, project, operation, request) as existing:
            if existing:
                return existing
            with self.product.store._connection() as conn:
                model, private = self._read(conn, project, identifier, "model")
                runtime, runtime_private = self._read(
                    conn, project, request.runtime_id, "runtime"
                )
            if (
                request.expected_model_receipt_sha256 != model["receipt_sha256"]
                or model.get("model_kind") != "YOLO26_NORMALITY_MODEL_PACK"
            ):
                raise VisionModelError("STALE_OR_UNSUPPORTED_MODEL_PACK")
            expected_identity = {
                "model_pack_sha256": request.expected_model_pack_sha256,
                "backbone_weights_sha256": request.expected_backbone_weights_sha256,
                "source_binding_sha256": request.expected_source_binding_sha256,
                "source_index_sha256": request.expected_source_index_sha256,
            }
            if any(model.get(key) != value for key, value in expected_identity.items()):
                raise VisionModelError("MODEL_PACK_IDENTITY_CHANGED")
            if request.action == "REJECT":
                with self.product.store._connection(immediate=True) as conn:
                    result = self._put(
                        conn,
                        model
                        | {
                            "status": "REJECT",
                            "sandbox_eligible": False,
                            "usage_scope": "RESEARCH_ONLY",
                            "selected_by": actor,
                            "selection_reviewer": request.reviewer_identity,
                            "selection_note": request.note,
                            "selected_at": _now(),
                        },
                        "model",
                        replace=True,
                    )
                    self._remember(conn, actor, project, operation, request, result)
                return result
            if (
                model.get("model_pack_schema_version")
                != "visiondata-gate.yolo26-normality-model-pack.v2"
                or model.get("stability_schema_version")
                != "visiondata-gate.model-stability.v4"
                or (model.get("status"), model.get("usage_scope")) not in {
                    ("MODEL_PACK_EVIDENCE_VERIFIED", "SANDBOX_CANDIDATE"),
                    ("APPROVE_SANDBOX", "LOCAL_SANDBOX_ONLY"),
                }
                or model.get("sandbox_eligible") is not True
                or model.get("stability_status") != "PUBLIC_PROXY_STABLE"
                or model.get("stability_eligible") is not True
            ):
                raise VisionModelError("MODEL_PACK_NOT_SANDBOX_ELIGIBLE")
            if (
                runtime.get("runtime_sha256") != request.expected_runtime_sha256
                or runtime.get("status") != "PROBED"
                or runtime.get("probe", {}).get("status") != "ready"
                or runtime.get("probe", {}).get("import_status") != "PASSED"
            ):
                raise VisionModelError("RUNTIME_NOT_IMPORT_PROBED")
            runtime_path = _file(
                runtime_private["executable_path"],
                runtime["executable_sha256"],
                "RUNTIME_CHANGED",
            )
            cas_files = _verify_normality_pack_cas(self.root, model, private)
            from .normality_inference import validate_normality_model_pack

            validation_output = _ensure_registry_directory(
                self.root,
                self.root
                / "pack_validations"
                / (identifier + "_" + uuid4().hex),
            )
            validation = validate_normality_model_pack(
                executable=runtime_path,
                expected_executable_sha256=runtime["executable_sha256"],
                expected_runtime_sha256=runtime["runtime_sha256"],
                model_pack=cas_files["model_pack"],
                expected_model_pack_sha256=model["model_pack_sha256"],
                expected_backbone_weights_sha256=model[
                    "backbone_weights_sha256"
                ],
                expected_source_binding_sha256=model["source_binding_sha256"],
                expected_source_index_sha256=model["source_index_sha256"],
                output_root=validation_output,
            )
            _assert_registry_path(self.root, validation_output)
            inference_backend_sha256 = _normality_backend_sha256()
            required_validation = {
                "status": "VALIDATED_FOR_LOCAL_SANDBOX",
                "model_pack_sha256": model["model_pack_sha256"],
                "backbone_weights_sha256": model["backbone_weights_sha256"],
                "source_binding_sha256": model["source_binding_sha256"],
                "source_index_sha256": model["source_index_sha256"],
                "runtime_sha256": runtime["runtime_sha256"],
                "inference_backend_sha256": inference_backend_sha256,
                "model_pack_schema_version": model["model_pack_schema_version"],
                "production_release_allowed": False,
            }
            if any(validation.get(key) != value for key, value in required_validation.items()):
                raise VisionModelError("MODEL_PACK_RUNTIME_VALIDATION_FAILED")
            with self.product.store._connection(immediate=True) as conn:
                self._membership(conn, actor, project)
                current, _ = self._read(conn, project, identifier, "model")
                if current["receipt_sha256"] != model["receipt_sha256"]:
                    raise VisionModelError("MODEL_PACK_CHANGED_DURING_APPROVAL")
                result = self._put(
                    conn,
                    model
                    | {
                        "status": "APPROVE_SANDBOX",
                        "usage_scope": "LOCAL_SANDBOX_ONLY",
                        "sandbox_runtime_id": runtime["runtime_id"],
                        "sandbox_runtime_sha256": runtime["runtime_sha256"],
                        "sandbox_validation": validation,
                        "selected_by": actor,
                        "selection_reviewer": request.reviewer_identity,
                        "selection_note": request.note,
                        "selected_at": _now(),
                        "loaded": False,
                    },
                    "model",
                    replace=True,
                )
                self._remember(conn, actor, project, operation, request, result)
            return result

    def _bound_normality_inputs(self, project, identifier, request):
        """Revalidate exact sandbox, CAS, input and runtime bindings.

        Callers must hold the authorized project-scoped operation context.
        Both ordinary inference and optional Normality TTT use this same gate.
        """
        with self.product.store._connection() as conn:
            model, model_private = self._read(conn, project, identifier, "model")
            asset, asset_private = self._read(
                conn, project, request.asset_id, "inference_asset"
            )
            runtime_id = model.get("sandbox_runtime_id")
            if not isinstance(runtime_id, str):
                raise VisionModelError("MODEL_PACK_NOT_SANDBOX_APPROVED")
            runtime, runtime_private = self._read(
                conn, project, runtime_id, "runtime"
            )
        sandbox_validation = model.get("sandbox_validation")
        inference_backend_sha256 = _normality_backend_sha256()
        if (
            not isinstance(sandbox_validation, dict)
            or sandbox_validation.get("inference_backend_sha256")
            != inference_backend_sha256
        ):
            raise VisionModelError(
                "INFERENCE_BACKEND_CHANGED_SINCE_SANDBOX_APPROVAL"
            )
        identity = {
            "model_pack_sha256": request.expected_model_pack_sha256,
            "backbone_weights_sha256": request.expected_backbone_weights_sha256,
            "source_binding_sha256": request.expected_source_binding_sha256,
            "source_index_sha256": request.expected_source_index_sha256,
            "sandbox_runtime_sha256": request.expected_runtime_sha256,
        }
        if (
            model.get("receipt_sha256")
            != request.expected_model_receipt_sha256
            or any(model.get(key) != value for key, value in identity.items())
            or model.get("status") != "APPROVE_SANDBOX"
            or model.get("usage_scope") != "LOCAL_SANDBOX_ONLY"
            or model.get("model_pack_schema_version")
            != "visiondata-gate.yolo26-normality-model-pack.v2"
            or model.get("stability_schema_version")
            != "visiondata-gate.model-stability.v4"
            or model.get("production_release_allowed") is not False
        ):
            raise VisionModelError("MODEL_PACK_NOT_SANDBOX_APPROVED")
        if (
            asset.get("receipt_sha256")
            != request.expected_asset_receipt_sha256
            or asset.get("image_sha256") != request.expected_image_sha256
            or asset.get("status") != "FROZEN_LOCAL_INFERENCE_ASSET"
            or asset.get("production_release_allowed") is not False
        ):
            raise VisionModelError("INFERENCE_ASSET_CHANGED")
        model_cas = _verify_normality_pack_cas(
            self.root, model, model_private
        )
        image = _file(
            asset_private["cas_path"],
            asset["image_sha256"],
            "INFERENCE_ASSET_CAS_CHANGED",
        )
        cas_root = (self.root / "cas" / "sha256").resolve(strict=True)
        try:
            image.relative_to(cas_root)
        except ValueError:
            raise VisionModelError("INFERENCE_ASSET_CAS_PATH_ESCAPE") from None
        if image.name != asset["image_sha256"]:
            raise VisionModelError("INFERENCE_ASSET_CAS_ADDRESS_MISMATCH")
        if (
            runtime.get("runtime_sha256") != request.expected_runtime_sha256
            or runtime.get("status") != "PROBED"
            or runtime.get("probe", {}).get("status") != "ready"
            or runtime.get("probe", {}).get("import_status") != "PASSED"
        ):
            raise VisionModelError("RUNTIME_NOT_IMPORT_PROBED")
        runtime_path = _file(
            runtime_private["executable_path"],
            runtime["executable_sha256"],
            "RUNTIME_CHANGED",
        )
        return {
            "model": model,
            "asset": asset,
            "runtime": runtime,
            "model_cas": model_cas,
            "image": image,
            "runtime_path": runtime_path,
            "inference_backend_sha256": inference_backend_sha256,
        }

    def run_normality_inference(
        self,
        actor,
        project,
        identifier,
        request: RunNormalityInference,
    ):
        request = RunNormalityInference.model_validate(request.model_dump(mode="json"))
        operation = "run_normality_inference:" + identifier
        with self._operation(actor, project, operation, request) as existing:
            if existing:
                return existing
            bound = self._bound_normality_inputs(project, identifier, request)
            model = bound["model"]
            asset = bound["asset"]
            runtime = bound["runtime"]
            model_cas = bound["model_cas"]
            image = bound["image"]
            runtime_path = bound["runtime_path"]
            inference_backend_sha256 = bound["inference_backend_sha256"]
            value = self._base(project, "vision_inference", actor, request)
            output = _ensure_registry_directory(
                self.root,
                self.root / "inferences" / value["resource_id"],
            )
            from .normality_inference import run_normality_inference

            inference = run_normality_inference(
                executable=runtime_path,
                expected_executable_sha256=runtime["executable_sha256"],
                expected_runtime_sha256=runtime["runtime_sha256"],
                model_pack=model_cas["model_pack"],
                expected_model_pack_sha256=model["model_pack_sha256"],
                expected_backbone_weights_sha256=model[
                    "backbone_weights_sha256"
                ],
                expected_source_binding_sha256=model["source_binding_sha256"],
                expected_source_index_sha256=model["source_index_sha256"],
                image=image,
                image_format=asset["format"],
                expected_image_sha256=asset["image_sha256"],
                output_root=output,
                max_seconds=request.max_seconds,
            )
            _assert_registry_path(self.root, output)
            expected_result = {
                "status": "COMPLETED_LOCAL_SANDBOX_INFERENCE",
                "model_pack_sha256": model["model_pack_sha256"],
                "model_pack_schema_version": model["model_pack_schema_version"],
                "backbone_weights_sha256": model["backbone_weights_sha256"],
                "source_binding_sha256": model["source_binding_sha256"],
                "source_index_sha256": model["source_index_sha256"],
                "runtime_sha256": runtime["runtime_sha256"],
                "inference_backend_sha256": inference_backend_sha256,
                "image_sha256": asset["image_sha256"],
                "machine_write_permitted": False,
                "production_release_allowed": False,
            }
            if any(
                inference.get(key) != expected
                for key, expected in expected_result.items()
            ):
                raise VisionModelError("INFERENCE_RESULT_IDENTITY_MISMATCH")
            heatmap = output / "artifacts" / "heatmap.png"
            heatmap = _assert_registry_path(self.root, heatmap)
            heatmap_meta = inference.get("heatmap")
            if (
                not isinstance(heatmap_meta, dict)
                or not heatmap.is_file()
                or _file(
                    heatmap,
                    heatmap_meta.get("sha256", ""),
                    "INFERENCE_HEATMAP_CHANGED",
                )
                != heatmap.resolve(strict=True)
            ):
                raise VisionModelError("INFERENCE_HEATMAP_INVALID")
            heatmap_artifact_id = "normality_heatmap_" + uuid4().hex[:24]
            value.update(
                inference_id=value["resource_id"],
                model_id=model["model_id"],
                asset_id=asset["asset_id"],
                runtime_id=runtime["runtime_id"],
                model_pack_sha256=model["model_pack_sha256"],
                backbone_weights_sha256=model["backbone_weights_sha256"],
                source_binding_sha256=model["source_binding_sha256"],
                source_index_sha256=model["source_index_sha256"],
                runtime_sha256=runtime["runtime_sha256"],
                inference_backend_sha256=inference_backend_sha256,
                image_sha256=asset["image_sha256"],
                status=inference["status"],
                image_score=inference["image_score"],
                image_threshold=inference["image_threshold"],
                pixel_threshold=inference["pixel_threshold"],
                predicted_anomaly=inference["predicted_anomaly"],
                positive_pixel_fraction=inference["positive_pixel_fraction"],
                heatmap_artifact_id=heatmap_artifact_id,
                heatmap=heatmap_meta,
                device="cpu",
                decision_scope="MODEL_SIGNAL_ONLY_NOT_GATE_OR_PRODUCTION_DECISION",
                review_required=True,
                gate_decision="NOT_ISSUED",
            )
            with self.product.store._connection(immediate=True) as conn:
                result = self._put(
                    conn,
                    value,
                    "inference",
                    {
                        "output_root": str(output),
                        "heatmap_path": str(heatmap.resolve(strict=True)),
                    },
                )
                self._remember(conn, actor, project, operation, request, result)
            return result

    def register_runtime(self, actor, project, request: RegisterVisionRuntime):
        from .learning_yolo_backend import probe_vision_runtime

        with self._operation(actor, project, "register_runtime", request) as existing:
            if existing:
                return existing
            path = _file(
                request.executable_path,
                request.expected_executable_sha256,
                "RUNTIME_CHANGED",
            )
            value = self._base(project, "vision_runtime", actor, request)
            probe = probe_vision_runtime(
                path,
                request.expected_executable_sha256,
                self.root / "probes" / value["resource_id"],
                import_check=False,
            )
            value.update(
                runtime_id=value["resource_id"],
                display_name=request.display_name,
                executable_sha256=request.expected_executable_sha256,
                runtime_sha256=probe.get("runtime_sha256") or _sha(probe),
                probe=probe,
                status=(
                    "METADATA_PROBED_IMPORT_NOT_TESTED"
                    if probe.get("status") == "ready"
                    else "UNAVAILABLE"
                ),
            )
            with self.product.store._connection(immediate=True) as conn:
                result = self._put(
                    conn, value, "runtime", {"executable_path": str(path)}
                )
                self._remember(
                    conn, actor, project, "register_runtime", request, result
                )
            return result

    def probe_runtime(self, actor, project, identifier, request: ProbeVisionRuntime):
        from .learning_yolo_backend import probe_vision_runtime

        with self._operation(
            actor, project, "probe_runtime:" + identifier, request
        ) as existing:
            if existing:
                return existing
            with self.product.store._connection() as conn:
                runtime, private = self._read(conn, project, identifier, "runtime")
            if request.expected_runtime_sha256 != runtime["runtime_sha256"]:
                raise VisionModelError("STALE_RUNTIME")
            probe = probe_vision_runtime(
                Path(private["executable_path"]),
                runtime["executable_sha256"],
                self.root / "probes" / ("probe_" + uuid4().hex),
                import_check=request.import_check,
            )
            if (
                probe.get("runtime_sha256", request.expected_runtime_sha256)
                != request.expected_runtime_sha256
            ):
                raise VisionModelError("RUNTIME_CHANGED")
            with self.product.store._connection(immediate=True) as conn:
                result = self._put(
                    conn,
                    runtime
                    | {
                        "probe": probe,
                        "status": "PROBED"
                        if probe.get("status") == "ready"
                        else "UNAVAILABLE",
                    },
                    "runtime",
                    replace=True,
                )
                self._remember(
                    conn, actor, project, "probe_runtime:" + identifier, request, result
                )
            return result

    def register_dataset(self, actor, project, request: RegisterDetectionDataset):
        from .learning_detection_dataset import freeze_detection_dataset

        with self._operation(actor, project, "register_dataset", request) as existing:
            if existing:
                return existing
            value = self._base(project, "vision_dataset", actor, request)
            output = self.root / "datasets" / value["resource_id"]
            output.parent.mkdir(parents=True, exist_ok=True)
            receipt = freeze_detection_dataset(
                Path(request.source_root),
                request.manifest,
                output,
                request.expected_manifest_sha256,
            )
            value.update(
                dataset_id=value["resource_id"],
                dataset_receipt=receipt,
                dataset_receipt_sha256=receipt["receipt_sha256"],
                provenance="UNBOUND_EXTERNAL_FIXTURE",
                training_eligible=False,
                status="FROZEN_REVIEWED_DETECTION_DATASET",
            )
            return self._publish_dataset(
                actor, project, "register_dataset", request, value, output
            )

    def _publish_dataset(self, actor, project, operation, request, value, output):
        with self.product.store._connection(immediate=True) as conn:
            self._verify_pool_transaction(
                conn, actor, project, {"pool_binding": value.get("pool_binding")}
            )
            for sample in value["dataset_receipt"]["samples"]:
                for kind, key in (
                    ("pixel", sample["pixel_sha256"]),
                    ("group", _sha(sample["group_id"])),
                ):
                    old = conn.execute(
                        "SELECT split FROM vision_split_members WHERE project_id=? AND kind=? AND value=?",
                        (project, kind, key),
                    ).fetchone()
                    if old and old[0] != sample["split"]:
                        raise VisionModelError("PROJECT_HELDOUT_REUSE_FORBIDDEN")
                    conn.execute(
                        "INSERT OR IGNORE INTO vision_split_members VALUES (?,?,?,?)",
                        (project, kind, key, sample["split"]),
                    )
            private = {
                "dataset_root": str(output),
                "pool_binding": value.get("pool_binding"),
            }
            result = self._put(conn, value, "dataset", private)
            self._remember(conn, actor, project, operation, request, result)
        return result

    def register_pool_dataset(
        self, actor, project, request: RegisterPoolDetectionDataset
    ):
        from .learning_detection_dataset import (
            freeze_detection_dataset,
            manifest_sha256,
        )
        from .vision_data_pool_bridge import pool_detection_input, verify_pool_binding

        with self._operation(
            actor, project, "register_pool_dataset", request
        ) as existing:
            if existing:
                return existing
            source_root, manifest, binding = pool_detection_input(
                self.product, actor, project, request
            )
            value = self._base(project, "vision_dataset", actor, request)
            output = self.root / "datasets" / value["resource_id"]
            output.parent.mkdir(parents=True, exist_ok=True)
            receipt = freeze_detection_dataset(
                source_root, manifest, output, manifest_sha256(manifest)
            )
            verify_pool_binding(self.product, actor, project, binding)
            value.update(
                dataset_id=value["resource_id"],
                dataset_receipt=receipt,
                dataset_receipt_sha256=receipt["receipt_sha256"],
                pool_binding=binding,
                provenance="GOVERNED_DATA_POOL_V1",
                training_eligible=True,
                status="FROZEN_REVIEWED_DETECTION_DATASET",
            )
            return self._publish_dataset(
                actor, project, "register_pool_dataset", request, value, output
            )

    def _verify_dataset_source(self, actor, project, private):
        binding = private.get("pool_binding")
        if binding is not None:
            from .vision_data_pool_bridge import verify_pool_binding

            verify_pool_binding(self.product, actor, project, binding)

    def _verify_pool_transaction(self, connection, actor, project, private):
        binding = private.get("pool_binding")
        if binding is not None:
            from .vision_data_pool_bridge import verify_pool_binding_in_connection

            verify_pool_binding_in_connection(connection, actor, project, binding)

    def _require_governed_training_dataset(self, dataset, private):
        governed_dataset = (
            dataset.get("provenance") == "GOVERNED_DATA_POOL_V1"
            and dataset.get("training_eligible") is True
            and private.get("pool_binding") is not None
        )
        if not governed_dataset and not self._test_only_allow_unbound_fixtures:
            raise VisionModelError("GOVERNED_POOL_DATASET_REQUIRED")

    def _feedback_inputs(self, connection, project, request, dataset):
        for identifier in request.responds_to_feedback_ids:
            feedback, _ = self._read(connection, project, identifier, "feedback")
            if (
                feedback["receipt_sha256"]
                != request.expected_feedback_receipts[identifier]
                or feedback["status"] != "TRIAGED_FOR_REVIEW"
                or feedback["classification"] == "UNKNOWN"
            ):
                raise VisionModelError("FEEDBACK_NOT_CURRENT_OR_TRIAGED")
            if feedback["dataset_receipt_sha256"] == dataset["dataset_receipt_sha256"]:
                raise VisionModelError("FEEDBACK_REQUIRES_NEW_DATA_VERSION")
            previous, _ = self._read(
                connection, project, feedback["dataset_id"], "dataset"
            )
            if _dataset_content_identity(previous) == _dataset_content_identity(
                dataset
            ):
                raise VisionModelError("FEEDBACK_REQUIRES_CHANGED_IMAGES_OR_LABELS")
            previous_pool = previous.get("pool_binding")
            if previous_pool is not None:
                new_pool = dataset.get("pool_binding")
                if (
                    new_pool is None
                    or new_pool["version_id"] == previous_pool["version_id"]
                    or new_pool["task_id"] == previous_pool["task_id"]
                ):
                    raise VisionModelError("FEEDBACK_REQUIRES_NEW_POOL_AND_GATE")

    def create_training_run(self, actor, project, request: CreateVisionTrainingRun):
        from .learning_detection_dataset import verify_detection_dataset

        request = CreateVisionTrainingRun.model_validate(
            request.model_dump(mode="json")
        )
        with self._operation(
            actor, project, "create_training_run", request
        ) as existing:
            if existing:
                with self.product.store._connection() as conn:
                    dataset, dataset_private = self._read(
                        conn, project, request.dataset_id, "dataset"
                    )
                self._require_governed_training_dataset(dataset, dataset_private)
                return existing
            with self.product.store._connection() as conn:
                runtime, runtime_private = self._read(
                    conn, project, request.runtime_id, "runtime"
                )
                dataset, dataset_private = self._read(
                    conn, project, request.dataset_id, "dataset"
                )
                model, model_private = (
                    self._read(conn, project, request.initial_model_id, "model")
                    if request.initial_model_id
                    else (None, {})
                )
                self._feedback_inputs(conn, project, request, dataset)
            self._require_governed_training_dataset(dataset, dataset_private)
            if runtime["runtime_sha256"] != request.expected_runtime_sha256:
                raise VisionModelError("STALE_RUNTIME")
            if runtime["probe"].get("status") != "ready":
                raise VisionModelError("RUNTIME_UNAVAILABLE")
            if (
                dataset["dataset_receipt_sha256"]
                != request.expected_dataset_receipt_sha256
            ):
                raise VisionModelError("STALE_DATASET")
            self._verify_dataset_source(actor, project, dataset_private)
            verify_detection_dataset(
                Path(dataset_private["dataset_root"]),
                request.expected_dataset_receipt_sha256,
            )
            _file(
                runtime_private["executable_path"],
                runtime["executable_sha256"],
                "RUNTIME_CHANGED",
            )
            if model is not None:
                if model["task_type"] != "detect" or model["format"] != "pt":
                    raise VisionModelError("YOLO_DETECTION_CHECKPOINT_REQUIRED")
                if model["weights_sha256"] != request.expected_weights_sha256:
                    raise VisionModelError("STALE_WEIGHTS")
                if model["license_id"].upper() in {"UNKNOWN", "UNSPECIFIED", "NONE"}:
                    raise VisionModelError("WEIGHTS_LICENSE_UNRESOLVED")
                _file(
                    model_private["weights_path"],
                    request.expected_weights_sha256,
                    "WEIGHTS_CHANGED",
                )
            value = self._base(project, "vision_run", actor, request)
            value.update(
                run_id=value["resource_id"],
                status="QUEUED",
                runtime_id=request.runtime_id,
                runtime_sha256=request.expected_runtime_sha256,
                dataset_id=request.dataset_id,
                dataset_receipt_sha256=request.expected_dataset_receipt_sha256,
                initial_model_id=request.initial_model_id,
                initialization=request.initialization,
                pretrained_claimed=False,
                architecture="yolo26n",
                device="cpu",
                training=request.training.model_dump(),
                adaptation="OFF",
                ttt_status="DISABLED_NOT_IMPLEMENTED",
                authorization_sha256=_sha(request.model_dump(mode="json")),
                cancel_requested=False,
                candidate_model_id=None,
                selection="PENDING",
                result=None,
                error_code=None,
                responds_to_feedback_ids=list(request.responds_to_feedback_ids),
                feedback_ids=[],
                feedback_status="NOT_EVALUATED",
            )
            private = {
                "runtime": runtime,
                "runtime_private": runtime_private,
                "dataset_private": dataset_private,
                "model_private": model_private,
                "request": request.model_dump(mode="json"),
            }
            with self.product.store._connection(immediate=True) as conn:
                self._verify_pool_transaction(conn, actor, project, dataset_private)
                self._feedback_inputs(conn, project, request, dataset)
                active = conn.execute(
                    "SELECT body FROM vision_records WHERE kind='run' AND project_id=?",
                    (project,),
                ).fetchall()
                if any(
                    json.loads(row[0])["status"] in {"QUEUED", "RUNNING"}
                    for row in active
                ):
                    raise VisionModelError("PROJECT_TRAINING_ALREADY_ACTIVE")
                result = self._put(conn, value, "run", private)
                self._remember(
                    conn, actor, project, "create_training_run", request, result
                )
            threading.Thread(
                target=self._execute_run,
                args=(actor, project, value["run_id"]),
                name="vision-cpu-" + value["run_id"],
                daemon=False,
            ).start()
            return result

    def _cancelled(self, project, identifier):
        with self.product.store._connection() as conn:
            run, _ = self._read(conn, project, identifier, "run")
        return run["cancel_requested"] or run["status"] != "RUNNING"

    def _execute_run(self, actor, project, identifier):
        from .learning_detection_dataset import verify_detection_dataset
        from .learning_yolo_backend import YoloTrainingConfig, run_yolo_training

        with task_execution_lock(
            self.product.product_root, "vision-run:" + identifier
        ) as acquired:
            if not acquired:
                return
            try:
                self._authorize(actor, project)
                with self.product.store._connection(immediate=True) as conn:
                    run, private = self._read(conn, project, identifier, "run")
                    if run["status"] != "QUEUED":
                        return
                    self._membership(conn, actor, project)
                    self._verify_pool_transaction(
                        conn, actor, project, private["dataset_private"]
                    )
                    dataset, _ = self._read(conn, project, run["dataset_id"], "dataset")
                    self._feedback_inputs(
                        conn,
                        project,
                        CreateVisionTrainingRun.model_validate(private["request"]),
                        dataset,
                    )
                    run = self._put(
                        conn,
                        run | {"status": "RUNNING", "started_at": _now()},
                        "run",
                        replace=True,
                    )
                dataset_root = Path(private["dataset_private"]["dataset_root"])
                self._verify_dataset_source(actor, project, private["dataset_private"])
                verify_detection_dataset(dataset_root, run["dataset_receipt_sha256"])
                job_root = self.root / "runs" / identifier
                inputs = job_root / "dataset"
                inputs.parent.mkdir(parents=True, exist_ok=False)
                shutil.copytree(dataset_root, inputs)
                result = run_yolo_training(
                    executable=Path(private["runtime_private"]["executable_path"]),
                    expected_executable_sha256=private["runtime"]["executable_sha256"],
                    expected_runtime_sha256=run["runtime_sha256"],
                    dataset_root=inputs,
                    output_root=job_root / "execution",
                    config=YoloTrainingConfig(**run["training"]),
                    initial_weights=(
                        Path(private["model_private"]["weights_path"])
                        if private["model_private"]
                        else None
                    ),
                    expected_weights_sha256=private["request"][
                        "expected_weights_sha256"
                    ],
                    cancelled=lambda: self._cancelled(project, identifier),
                )
                verify_detection_dataset(dataset_root, run["dataset_receipt_sha256"])
                self.product.store.get_project(actor, project)
                self._verify_dataset_source(actor, project, private["dataset_private"])
                with self.product.store._connection(immediate=True) as conn:
                    current, _ = self._read(conn, project, identifier, "run")
                    self._membership(conn, actor, project)
                    self._verify_pool_transaction(
                        conn, actor, project, private["dataset_private"]
                    )
                    status = {
                        "completed": "SUCCEEDED_CANDIDATE",
                        "cancelled": "CANCELLED",
                        "timed_out": "TIMED_OUT",
                    }.get(result.get("status"), "FAILED")
                    if current["cancel_requested"]:
                        status = "CANCELLED"
                    candidate_id = None
                    feedback_ids = []
                    feedback_status = "NOT_AVAILABLE_LEGACY_RESULT"
                    if status == "SUCCEEDED_CANDIDATE":
                        checkpoint = result["checkpoint"]
                        path = job_root / "execution" / checkpoint["relative_path"]
                        path.resolve().relative_to(job_root.resolve())
                        _file(path, checkpoint["sha256"], "CHECKPOINT_CHANGED")
                        request = CreateVisionTrainingRun.model_validate(
                            private["request"]
                        )
                        candidate = self._base(project, "vision_model", actor, request)
                        candidate_id = candidate["resource_id"]
                        candidate.update(
                            model_id=candidate_id,
                            display_name="YOLO26 candidate",
                            task_type="detect",
                            format="pt",
                            weights_sha256=checkpoint["sha256"],
                            file_bytes=path.stat().st_size,
                            license_id="AGPL-3.0_OR_ENTERPRISE_REVIEW_REQUIRED",
                            license_status="OPERATOR_ACKNOWLEDGED_NOT_LEGAL_VERIFICATION",
                            source_description="Locally generated checkpoint",
                            status="CANDIDATE_REQUIRES_HUMAN_REVIEW",
                            loaded=False,
                            training_run_id=identifier,
                            parent_model_id=run["initial_model_id"],
                            dataset_id=run["dataset_id"],
                        )
                        self._put(conn, candidate, "model", {"weights_path": str(path)})
                        from .vision_feedback import build_vision_feedback

                        dataset, _ = self._read(
                            conn, project, run["dataset_id"], "dataset"
                        )
                        self._feedback_inputs(conn, project, request, dataset)
                        for feedback in build_vision_feedback(
                            project,
                            identifier,
                            run["dataset_id"],
                            dataset["dataset_receipt"],
                            result,
                        ):
                            self._put(conn, feedback, "feedback")
                            feedback_ids.append(feedback["feedback_id"])
                        if result.get("validation_feedback_protocol") is not None:
                            feedback_status = (
                                "VAL_DISAGREEMENTS_REQUIRE_HUMAN_REVIEW"
                                if feedback_ids
                                else "NO_VAL_DISAGREEMENT_AT_FIXED_PROTOCOL"
                            )
                    self._put(
                        conn,
                        current
                        | {
                            "status": status,
                            "result": result,
                            "candidate_model_id": candidate_id,
                            "finished_at": _now(),
                            "feedback_ids": feedback_ids,
                            "feedback_status": feedback_status,
                        },
                        "run",
                        replace=True,
                    )
            except Exception:
                with self.product.store._connection(immediate=True) as conn:
                    run, _ = self._read(conn, project, identifier, "run")
                    self._put(
                        conn,
                        run
                        | {
                            "status": "CANCELLED"
                            if run["cancel_requested"]
                            else "FAILED",
                            "error_code": "TRAINING_EVIDENCE_OR_EXECUTION_FAILED",
                            "finished_at": _now(),
                        },
                        "run",
                        replace=True,
                    )

    def _run_action(self, actor, project, identifier, request, operation):
        with self._operation(
            actor, project, operation + ":" + identifier, request
        ) as existing:
            if existing:
                return existing
            if operation == "selection":
                with self.product.store._connection() as connection:
                    _run, source = self._read(connection, project, identifier, "run")
                self._verify_dataset_source(actor, project, source["dataset_private"])
            with self.product.store._connection(immediate=True) as conn:
                run, private = self._read(conn, project, identifier, "run")
                if request.expected_run_sha256 != run["receipt_sha256"]:
                    raise VisionModelError("STALE_RUN")
                if operation == "cancel":
                    if run["status"] not in {"QUEUED", "RUNNING"}:
                        raise VisionModelError("RUN_ALREADY_TERMINAL")
                    changes = {"cancel_requested": True}
                    if run["status"] == "QUEUED":
                        changes["status"] = "CANCELLED"
                elif operation == "recover":
                    if run["status"] not in {"QUEUED", "RUNNING"}:
                        raise VisionModelError("RUN_NOT_INTERRUPTED")
                    changes = {
                        "status": "INTERRUPTED_HOLD",
                        "cancel_requested": True,
                        "error_code": "NEW_AUTHORIZATION_REQUIRED_NO_AUTO_REPLAY",
                    }
                else:
                    if (
                        run["status"] != "SUCCEEDED_CANDIDATE"
                        or run["selection"] != "PENDING"
                    ):
                        raise VisionModelError("CANDIDATE_NOT_SELECTABLE")
                    self._verify_pool_transaction(
                        conn, actor, project, private["dataset_private"]
                    )
                    model, model_private = self._read(
                        conn, project, run["candidate_model_id"], "model"
                    )
                    if (
                        model["weights_sha256"]
                        != request.expected_candidate_weights_sha256
                    ):
                        raise VisionModelError("STALE_CANDIDATE")
                    _file(
                        model_private["weights_path"],
                        model["weights_sha256"],
                        "CHECKPOINT_CHANGED",
                    )
                    from .learning_detection_dataset import verify_detection_dataset

                    verify_detection_dataset(
                        Path(private["dataset_private"]["dataset_root"]),
                        run["dataset_receipt_sha256"],
                    )
                    changes = {
                        "selection": request.action,
                        "selected_by": actor,
                        "selected_at": _now(),
                        "selection_reviewer": request.reviewer_identity,
                        "selection_note": request.note,
                    }
                    self._put(
                        conn, model | {"status": request.action}, "model", replace=True
                    )
                result = self._put(conn, run | changes, "run", replace=True)
                self._remember(
                    conn, actor, project, operation + ":" + identifier, request, result
                )
            return result

    def cancel_run(self, actor, project, identifier, request: VisionRunAction):
        return self._run_action(actor, project, identifier, request, "cancel")

    def recover_run(self, actor, project, identifier, request: VisionRunAction):
        self._authorize(actor, project)
        with task_execution_lock(
            self.product.product_root, "vision-run:" + identifier
        ) as acquired:
            if not acquired:
                raise VisionModelError("EXECUTION_OWNER_ACTIVE")
            return self._run_action(actor, project, identifier, request, "recover")

    def select_model(self, actor, project, identifier, request: SelectVisionModel):
        return self._run_action(actor, project, identifier, request, "selection")

    def list_feedback(self, actor, project, identifier):
        self.get_run(actor, project, identifier)
        result = self._list(actor, project, "feedback")
        return _seal(
            result
            | {
                "run_id": identifier,
                "items": [
                    item for item in result["items"] if item["run_id"] == identifier
                ],
            }
        )

    def triage_feedback(
        self, actor, project, run_id, feedback_id, request: ReviewVisionFeedback
    ):
        with self._operation(
            actor, project, "triage_feedback:" + feedback_id, request
        ) as existing:
            if existing:
                if existing["run_id"] != run_id:
                    raise NotFoundError("visual feedback unavailable")
                return existing
            with self.product.store._connection(immediate=True) as conn:
                run, _ = self._read(conn, project, run_id, "run")
                feedback, _ = self._read(conn, project, feedback_id, "feedback")
                if feedback["run_id"] != run_id or feedback_id not in run.get(
                    "feedback_ids", []
                ):
                    raise NotFoundError("visual feedback unavailable")
                if (
                    run["receipt_sha256"] != request.expected_run_sha256
                    or feedback["receipt_sha256"] != request.expected_feedback_sha256
                ):
                    raise VisionModelError("STALE_RUN_OR_FEEDBACK")
                if (
                    run["status"] != "SUCCEEDED_CANDIDATE"
                    or feedback["status"] != "PENDING_HUMAN_REVIEW"
                ):
                    raise VisionModelError("FEEDBACK_NOT_REVIEWABLE")
                value = feedback | {
                    "status": "TRIAGED_FOR_REVIEW",
                    "classification": request.classification,
                    "reviewed_by": actor,
                    "reviewer_identity": request.reviewer_identity,
                    "review_note": request.note,
                    "reviewed_at": _now(),
                    "issue_closed": False,
                    "training_ingestion_allowed": False,
                }
                result = self._put(conn, value, "feedback", replace=True)
                self._remember(
                    conn,
                    actor,
                    project,
                    "triage_feedback:" + feedback_id,
                    request,
                    result,
                )
            return result

    def get_operation(self, actor, project, operation, request_key):
        self._authorize(actor, project)
        with self.product.store._connection() as conn:
            row = conn.execute(
                "SELECT result_id FROM vision_requests WHERE project_id=? AND actor=? AND operation=? AND request_key=?",
                (project, actor, operation, request_key),
            ).fetchone()
            if row is None:
                raise NotFoundError("visual operation unavailable")
            resource, _ = self._read(conn, project, row[0])
        return _seal(
            {
                "schema_version": "visiondata-gate.vision-operation.v1",
                "project_id": project,
                "operation": operation,
                "request_key": request_key,
                "resource_id": row[0],
                "resource": resource,
                "auto_replayed": False,
            }
        )
