"""Fail-closed three-seed stability evidence for governed model experiments.

The module consumes sealed public-proxy experiment artifacts.  It never runs a
model, updates weights, or grants production authority.  Cross-run drift is
reported as a promotion blocker instead of being averaged away.
"""

from __future__ import annotations

import copy
import hashlib
import hmac
import json
import math
import statistics
from collections import Counter
from collections.abc import Mapping, Sequence
from pathlib import Path, PurePosixPath
from typing import Any

from . import model_experiment_agent as _outcome_policy
from .audit_envelope import canonical_jcs_bytes
from .evidence import canonical_json_bytes, sha256_file


STABILITY_SCHEMA_VERSION = "visiondata-gate.model-stability.v4"
EXPECTED_EFFECTIVENESS_STATUS = "OBSERVED_ON_PUBLIC_DEVELOPMENT_PROXY"
EXPECTED_OPTIMIZATION_STATUS = "CONVERGED"
EXPECTED_RUN_STATUS = "LOCAL_PUBLIC_PROXY_EXPERIMENT_COMPLETED"
EXPECTED_MODEL_PACK_SCHEMA_VERSION = (
    "visiondata-gate.yolo26-normality-model-pack.v2"
)
EXPECTED_FEATURE_LAYERS = (4, 6, 9)
# One reviewed, directed compatibility edge only. This is not a general
# comment/docstring normalization rule and must not be extended implicitly.
_HISTORICAL_POLICY_SHA256 = "c2d9b28ed86724d1fdee8e47629fa5282c06e29528e0ec5d1f5796401b9bb30c"
_DOCUMENTED_POLICY_SHA256 = "ff1f2385b1e070a352f9242dd821adf36858d505d6b91e3e1d01229123db3fd6"
_REVIEWED_POLICY_DOCSTRING_ADDITION = (
    b"\nThe resulting experiment is a normality proxy over multiscale classification\n"
    b"features.  It is not the supervised bounding-box detector implemented by the\n"
    b"separate YOLO training backend, and it does not generate adjudicated masks.\n"
)
EXPECTED_AGENT_STAGES = (
    "intake",
    "planner",
    "tool",
    "council",
    "judge",
    "delivery",
)

PROMOTION_RANGE_LIMITS: dict[str, float] = {
    "image_auroc": 0.05,
    "pixel_auroc": 0.05,
    "image_f1": 0.10,
    "pixel_f1": 0.05,
}

_REQUIRED_FILES = {
    "run_receipt": "RUN_RECEIPT.json",
    "model_result": "model_result.json",
    "plan": "model_experiment_plan.json",
    "selection_manifest": "selection_manifest.json",
    "agent_receipt": "model_experiment_agent_receipt.json",
    "runtime_events": "agent_runtime_events.json",
    "private_result": "private/worker_result.json",
}

_METRIC_PATHS: dict[str, tuple[str, ...]] = {
    "best_normal_validation_loss": ("best_normal_validation_loss",),
    "image_auroc": ("heldout_development", "image_auroc"),
    "image_average_precision": (
        "heldout_development",
        "image_average_precision",
    ),
    "image_f1": ("heldout_development", "image_f1"),
    "normal_image_false_positive_rate": (
        "heldout_development",
        "normal_image_false_positive_rate",
    ),
    "pixel_auroc": ("heldout_development", "pixel_auroc"),
    "pixel_average_precision": (
        "heldout_development",
        "pixel_average_precision",
    ),
    "pixel_f1": ("heldout_development", "pixel_f1"),
    "single_region_image_detection_recall": (
        "heldout_development",
        "single_region_proxy",
        "image_detection_recall",
    ),
    "single_region_component_detected_fraction_at_10pct_overlap": (
        "heldout_development",
        "single_region_proxy",
        "component_detected_fraction_at_10pct_overlap",
    ),
    "multi_region_image_detection_recall": (
        "heldout_development",
        "multi_region_proxy",
        "image_detection_recall",
    ),
    "multi_region_component_detected_fraction_at_10pct_overlap": (
        "heldout_development",
        "multi_region_proxy",
        "component_detected_fraction_at_10pct_overlap",
    ),
    "runtime_elapsed_seconds": ("runtime", "elapsed_seconds"),
    "runtime_latency_ms_p50": ("runtime", "latency_ms_p50"),
    "runtime_latency_ms_p95": ("runtime", "latency_ms_p95"),
    "runtime_latency_ms_max": ("runtime", "latency_ms_max"),
    "runtime_peak_allocated_bytes": ("runtime", "peak_allocated_bytes"),
}


class ModelStabilityContractError(ValueError):
    """Raised when one input run cannot be trusted as sealed evidence."""


def _contract_error(code: str, detail: str) -> ModelStabilityContractError:
    return ModelStabilityContractError(f"{code}: {detail}")


def _load_json_object(path: Path) -> dict[str, Any]:
    try:
        raw = path.read_text(encoding="utf-8")
    except FileNotFoundError as exc:
        raise _contract_error("STABILITY_ARTIFACT_MISSING", path.name) from exc
    try:
        value = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise _contract_error("STABILITY_ARTIFACT_INVALID_JSON", path.name) from exc
    if not isinstance(value, dict):
        raise _contract_error("STABILITY_JSON_OBJECT_REQUIRED", path.name)
    return value


def _load_json_array(path: Path) -> list[Any]:
    try:
        raw = path.read_text(encoding="utf-8")
    except FileNotFoundError as exc:
        raise _contract_error("STABILITY_ARTIFACT_MISSING", path.name) from exc
    try:
        value = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise _contract_error("STABILITY_ARTIFACT_INVALID_JSON", path.name) from exc
    if not isinstance(value, list):
        raise _contract_error("STABILITY_JSON_ARRAY_REQUIRED", path.name)
    return value


def _required(value: Mapping[str, Any], path: Sequence[str], *, artifact: str) -> Any:
    current: Any = value
    for key in path:
        if not isinstance(current, Mapping) or key not in current:
            joined = ".".join(path)
            raise _contract_error(
                "STABILITY_FIELD_REQUIRED", f"{artifact}:{joined}"
            )
        current = current[key]
    return current


def _finite_number(value: Any, *, field: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise _contract_error("STABILITY_FINITE_NUMBER_REQUIRED", field)
    result = float(value)
    if not math.isfinite(result):
        raise _contract_error("STABILITY_FINITE_NUMBER_REQUIRED", field)
    return result


def _canonical_digest(value: Any) -> str:
    return hashlib.sha256(
        canonical_json_bytes(value, trailing_newline=False)
    ).hexdigest()


def _canonical_jcs_digest(value: Any) -> str:
    return hashlib.sha256(canonical_jcs_bytes(value)).hexdigest()


def _verification_implementation() -> dict[str, str]:
    verifier_path = Path(__file__).resolve(strict=True)
    outcome_policy_path = Path(_outcome_policy.__file__).resolve(strict=True)
    return {
        "stability_module_sha256": sha256_file(verifier_path),
        "outcome_policy_module_sha256": sha256_file(outcome_policy_path),
        "outcome_policy_function": "classify_experiment_outcome",
    }


def _outcome_policy_source_compatibility(
    historical_sha: Any,
    verification: Mapping[str, str],
    *,
    run_label: str,
    model_seed: int,
) -> dict[str, Any] | None:
    """Admit only the reviewed byte-for-byte docstring migration, with a receipt.

    The historical policy remains the training identity. The current source is
    used only for verification and outcome re-derivation; no old artifact is
    rewritten and no new training execution is implied.
    """
    current_sha = verification["outcome_policy_module_sha256"]
    if historical_sha == current_sha:
        return None
    valid_pair = (
        historical_sha == _HISTORICAL_POLICY_SHA256
        and current_sha == _DOCUMENTED_POLICY_SHA256
    )
    if not valid_pair:
        raise _contract_error("OUTCOME_POLICY_SOURCE_DRIFT", "model_experiment_agent.py")
    try:
        current_bytes = Path(_outcome_policy.__file__).read_bytes()
    except OSError:
        raise _contract_error("OUTCOME_POLICY_SOURCE_DRIFT", "model_experiment_agent.py") from None
    reconstructed = current_bytes.replace(_REVIEWED_POLICY_DOCSTRING_ADDITION, b"", 1)
    reconstructed_sha = hashlib.sha256(reconstructed).hexdigest()
    if (
        hashlib.sha256(current_bytes).hexdigest() != _DOCUMENTED_POLICY_SHA256
        or current_bytes.count(_REVIEWED_POLICY_DOCSTRING_ADDITION) != 1
        or reconstructed_sha != _HISTORICAL_POLICY_SHA256
    ):
        raise _contract_error("OUTCOME_POLICY_SOURCE_DRIFT", "model_experiment_agent.py")
    receipt = {
        "schema_version": "visiondata-gate.outcome-policy-source-compatibility.v1",
        "migration_id": "normality-scope-module-docstring-20260918",
        "status": "EXACT_REVIEWED_DOCSTRING_MIGRATION",
        "historical_policy_module_sha256": historical_sha,
        "current_policy_module_sha256": current_sha,
        "reconstructed_historical_source_sha256": reconstructed_sha,
        "verification_method": "EXACT_REVERSE_PATCH_AND_FULL_BYTE_SHA256",
        "verification_implementation": dict(verification),
        "run_label": run_label,
        "model_seed": model_seed,
        "training_identity_rewritten": False,
        "production_release_allowed": False,
        "claim_boundary": (
            "Compatibility applies only to this exact reviewed policy-module "
            "docstring change. Training used the historical implementation identity; "
            "current source only re-verifies the preserved evidence."
        ),
    }
    return receipt | {"receipt_sha256": _canonical_jcs_digest(receipt)}


def _safe_run_member(root: Path, relative: Any, *, artifact: str) -> Path:
    if not isinstance(relative, str) or not relative or "\\" in relative:
        raise _contract_error("STABILITY_RELATIVE_PATH_INVALID", artifact)
    pure = PurePosixPath(relative)
    if pure.is_absolute() or any(part in {"", ".", ".."} for part in pure.parts):
        raise _contract_error("STABILITY_RELATIVE_PATH_INVALID", artifact)
    try:
        candidate = (root / Path(*pure.parts)).resolve(strict=True)
        candidate.relative_to(root)
    except (FileNotFoundError, ValueError) as exc:
        raise _contract_error("STABILITY_ARTIFACT_MISSING", pure.name) from exc
    if not candidate.is_file():
        raise _contract_error("STABILITY_ARTIFACT_MISSING", pure.name)
    return candidate


def _assert_false(value: Mapping[str, Any], *, artifact: str, field: str) -> None:
    if _required(value, (field,), artifact=artifact) is not False:
        raise _contract_error(
            "PRODUCTION_AUTHORITY_MUST_REMAIN_FALSE", f"{artifact}:{field}"
        )


def _assert_equal_within_run(
    *, field: str, artifact_values: Mapping[str, Any]
) -> None:
    values = list(artifact_values.values())
    if not values or any(value != values[0] for value in values[1:]):
        raise _contract_error(
            "INTRA_RUN_CONTRACT_MISMATCH",
            f"{field}:{','.join(sorted(artifact_values))}",
        )


def _validate_referenced_hash(
    receipt: Mapping[str, Any],
    *,
    field: str,
    artifact_path: Path,
) -> str:
    expected = _required(receipt, (field,), artifact="RUN_RECEIPT.json")
    observed = sha256_file(artifact_path)
    if not isinstance(expected, str) or expected != observed:
        raise _contract_error(
            "STABILITY_ARTIFACT_SHA256_MISMATCH", artifact_path.name
        )
    return observed


def _validate_manifest_roles(manifest: Mapping[str, Any]) -> dict[str, int]:
    roles = _required(manifest, ("roles",), artifact="selection_manifest.json")
    samples = _required(manifest, ("samples",), artifact="selection_manifest.json")
    if not isinstance(roles, Mapping) or not isinstance(samples, list):
        raise _contract_error(
            "SELECTION_ROLE_CONTRACT_INVALID", "roles or samples type"
        )
    normalized: dict[str, int] = {}
    for role, count in roles.items():
        if not isinstance(role, str) or isinstance(count, bool) or not isinstance(count, int):
            raise _contract_error(
                "SELECTION_ROLE_CONTRACT_INVALID", "role count must be integer"
            )
        if count < 0:
            raise _contract_error(
                "SELECTION_ROLE_CONTRACT_INVALID", "role count must be non-negative"
            )
        normalized[role] = count
    observed = Counter(
        sample.get("role")
        for sample in samples
        if isinstance(sample, Mapping) and isinstance(sample.get("role"), str)
    )
    if len(observed) != len(normalized) or dict(observed) != normalized:
        raise _contract_error(
            "SELECTION_ROLE_DENOMINATOR_MISMATCH", "declared roles differ from samples"
        )
    return dict(sorted(normalized.items()))


def _is_sha256(value: Any) -> bool:
    return (
        isinstance(value, str)
        and len(value) == 64
        and all(character in "0123456789abcdef" for character in value)
    )


def _selection_membership(manifest: Mapping[str, Any]) -> list[dict[str, Any]]:
    samples = _required(manifest, ("samples",), artifact="selection_manifest.json")
    if not isinstance(samples, list):
        raise _contract_error(
            "SELECTION_MEMBERSHIP_INVALID", "samples must be a list"
        )
    normalized: list[dict[str, Any]] = []
    seen: set[str] = set()
    for index, sample in enumerate(samples):
        if not isinstance(sample, Mapping):
            raise _contract_error(
                "SELECTION_MEMBERSHIP_INVALID", f"sample[{index}] must be an object"
            )
        sample_id = sample.get("sample_id", sample.get("source_sample_id"))
        role = sample.get("role")
        sample_sha256 = sample.get("sample_sha256")
        image_sha256 = sample.get("image_sha256")
        mask_sha256 = sample.get("mask_sha256")
        if not isinstance(sample_id, str) or not sample_id:
            raise _contract_error(
                "SELECTION_MEMBERSHIP_INVALID", f"sample[{index}].sample_id"
            )
        if sample_id in seen:
            raise _contract_error(
                "SELECTION_MEMBER_ID_DUPLICATE", sample_id
            )
        seen.add(sample_id)
        if not isinstance(role, str) or not role:
            raise _contract_error(
                "SELECTION_MEMBERSHIP_INVALID", f"sample[{index}].role"
            )
        for field, digest in (
            ("sample_sha256", sample_sha256),
            ("image_sha256", image_sha256),
        ):
            if not _is_sha256(digest):
                raise _contract_error(
                    "SELECTION_MEMBER_SHA256_INVALID", f"sample[{index}].{field}"
                )
        if mask_sha256 is not None and not _is_sha256(mask_sha256):
            raise _contract_error(
                "SELECTION_MEMBER_SHA256_INVALID",
                f"sample[{index}].mask_sha256",
            )
        normalized.append(
            {
                "sample_id": sample_id,
                "role": role,
                "sample_sha256": sample_sha256,
                "image_sha256": image_sha256,
                "mask_sha256": mask_sha256,
            }
        )
    normalized.sort(key=lambda sample: str(sample["sample_id"]))
    return normalized


def _seed_value(
    value: Mapping[str, Any], key: str, *, artifact: str
) -> int | None:
    observed = value.get(key)
    if observed is None:
        return None
    if isinstance(observed, bool) or not isinstance(observed, int):
        raise _contract_error(
            "STABILITY_INTEGER_SEED_REQUIRED", f"{artifact}:{key}"
        )
    return observed


def _read_seed_contract(
    plan: Mapping[str, Any], manifest: Mapping[str, Any]
) -> dict[str, Any]:
    plan_split = _seed_value(
        plan, "split_seed", artifact="model_experiment_plan.json"
    )
    plan_model = _seed_value(
        plan, "model_seed", artifact="model_experiment_plan.json"
    )
    manifest_split = _seed_value(
        manifest, "split_seed", artifact="selection_manifest.json"
    )
    manifest_model = _seed_value(
        manifest, "model_seed", artifact="selection_manifest.json"
    )
    plan_legacy = _seed_value(plan, "seed", artifact="model_experiment_plan.json")
    manifest_legacy = _seed_value(
        manifest, "seed", artifact="selection_manifest.json"
    )
    issues: list[str] = []

    if plan_split is not None and plan_model is not None:
        if manifest_split is None:
            issues.append("SELECTION_MANIFEST_SPLIT_SEED_MISSING")
        elif manifest_split != plan_split:
            issues.append("INTRA_RUN_SPLIT_SEED_MISMATCH")
        if manifest_model is not None and manifest_model != plan_model:
            issues.append("INTRA_RUN_MODEL_SEED_MISMATCH")
        if plan_legacy is not None and plan_legacy != plan_model:
            issues.append("LEGACY_PLAN_SEED_ALIAS_MISMATCH")
        if manifest_legacy is not None and manifest_legacy != plan_model:
            issues.append("LEGACY_MANIFEST_SEED_ALIAS_MISMATCH")
        return {
            "status": "EXPLICIT" if not issues else "INVALID",
            "split_seed": plan_split,
            "model_seed": plan_model,
            "issues": issues,
        }

    if plan_legacy is not None and manifest_legacy is not None:
        if plan_legacy != manifest_legacy:
            issues.append("INTRA_RUN_LEGACY_SEED_MISMATCH")
        issues.append("LEGACY_AMBIGUOUS_SEED_CONTRACT")
        return {
            "status": "LEGACY_AMBIGUOUS" if len(issues) == 1 else "INVALID",
            "split_seed": None,
            "model_seed": plan_legacy,
            "issues": issues,
        }

    fallback_model = plan_model if plan_model is not None else plan_legacy
    if fallback_model is None:
        raise _contract_error("MODEL_SEED_REQUIRED", "model_experiment_plan.json")
    issues.append("INCOMPLETE_SPLIT_MODEL_SEED_CONTRACT")
    return {
        "status": "INVALID",
        "split_seed": plan_split,
        "model_seed": fallback_model,
        "issues": issues,
    }


def _validate_agent_evidence(
    *,
    receipt: Mapping[str, Any],
    agent_receipt: Mapping[str, Any],
    events: Sequence[Any],
    plan: Mapping[str, Any],
    private_result_path: Path,
) -> dict[str, str]:
    unsigned_agent = dict(agent_receipt)
    stored_agent_seal = unsigned_agent.pop("receipt_sha256", None)
    observed_agent_seal = _canonical_jcs_digest(unsigned_agent)
    if not isinstance(stored_agent_seal, str) or not hmac.compare_digest(
        stored_agent_seal, observed_agent_seal
    ):
        raise _contract_error(
            "MODEL_AGENT_RECEIPT_SELF_SEAL_MISMATCH",
            "model_experiment_agent_receipt.json",
        )
    if agent_receipt.get("schema_version") != (
        "visiondata-gate.model-experiment-agent-receipt.v1"
    ):
        raise _contract_error(
            "MODEL_AGENT_RECEIPT_SCHEMA_INVALID",
            "model_experiment_agent_receipt.json",
        )
    if agent_receipt.get("plan_receipt_sha256") != plan.get("receipt_sha256"):
        raise _contract_error(
            "MODEL_AGENT_PLAN_RECEIPT_MISMATCH",
            "model_experiment_agent_receipt.json",
        )
    for field in ("source_binding_sha256", "source_index_sha256"):
        if agent_receipt.get(field) != plan.get(field):
            raise _contract_error(
                "MODEL_AGENT_SOURCE_BINDING_MISMATCH",
                field,
            )
    if (
        agent_receipt.get("final_disposition") != "HOLD"
        or agent_receipt.get("production_gate_receipt") != "NOT_CLAIMED"
        or agent_receipt.get("label_truth_authority") is not False
        or agent_receipt.get("machine_write_permitted") is not False
        or agent_receipt.get("production_release_allowed") is not False
    ):
        raise _contract_error(
            "MODEL_AGENT_SAFETY_BOUNDARY_INVALID",
            "model_experiment_agent_receipt.json",
        )
    if (
        agent_receipt.get("optimization_status")
        != receipt.get("optimization_status")
        or agent_receipt.get("effectiveness_status")
        != receipt.get("effectiveness_status")
    ):
        raise _contract_error(
            "MODEL_AGENT_OUTCOME_MISMATCH",
            "model_experiment_agent_receipt.json",
        )
    if not events or any(not isinstance(event, Mapping) for event in events):
        raise _contract_error(
            "MODEL_AGENT_EVENT_CHAIN_INVALID", "agent_runtime_events.json"
        )
    sequences = [event.get("sequence") for event in events]
    if sequences != list(range(1, len(events) + 1)):
        raise _contract_error(
            "MODEL_AGENT_EVENT_SEQUENCE_INVALID", "agent_runtime_events.json"
        )
    stages = tuple(
        dict.fromkeys(str(event.get("stage")) for event in events)
    )
    if (
        stages != EXPECTED_AGENT_STAGES
        or agent_receipt.get("stage_sequence") != list(stages)
        or agent_receipt.get("runtime_event_count") != len(events)
    ):
        raise _contract_error(
            "MODEL_AGENT_EVENT_STAGE_INVALID", "agent_runtime_events.json"
        )
    if (
        events[-1].get("stage") != "delivery"
        or events[-1].get("status") != "success"
    ):
        raise _contract_error(
            "MODEL_AGENT_DELIVERY_INCOMPLETE", "agent_runtime_events.json"
        )
    observed_event_chain = _canonical_jcs_digest(list(events))
    if not hmac.compare_digest(
        str(agent_receipt.get("runtime_event_chain_sha256", "")),
        observed_event_chain,
    ):
        raise _contract_error(
            "MODEL_AGENT_EVENT_CHAIN_SHA256_MISMATCH",
            "agent_runtime_events.json",
        )
    tool_count = sum(event.get("stage") == "tool" for event in events)
    if (
        agent_receipt.get("tool_call_count") != tool_count
        or agent_receipt.get("model_call_count") != 0
    ):
        raise _contract_error(
            "MODEL_AGENT_CALL_COUNT_MISMATCH",
            "model_experiment_agent_receipt.json",
        )
    private_result_sha256 = sha256_file(private_result_path)
    if not hmac.compare_digest(
        str(agent_receipt.get("execution_result_sha256", "")),
        private_result_sha256,
    ):
        raise _contract_error(
            "MODEL_AGENT_EXECUTION_RESULT_SHA256_MISMATCH",
            "worker_result.json",
        )
    return {
        "agent_receipt_self_seal_sha256": observed_agent_seal,
        "runtime_event_chain_sha256": observed_event_chain,
        "private_execution_result_sha256": private_result_sha256,
    }


def _expected_public_projection(
    private_result: Mapping[str, Any],
) -> dict[str, Any]:
    projection = copy.deepcopy(dict(private_result))
    if "per_sample_predictions" not in projection:
        raise _contract_error(
            "PRIVATE_EVALUATION_MEMBERSHIP_REQUIRED", "worker_result.json"
        )
    projection.pop("per_sample_predictions")
    checkpoint = projection.get("checkpoint")
    if not isinstance(checkpoint, dict):
        raise _contract_error(
            "MODEL_PACK_METADATA_REQUIRED", "worker_result.json"
        )
    private_relative = checkpoint.get("relative_path")
    if (
        not isinstance(private_relative, str)
        or not private_relative
        or "\\" in private_relative
    ):
        raise _contract_error(
            "STABILITY_RELATIVE_PATH_INVALID", "worker_result.json"
        )
    private_path = PurePosixPath(private_relative)
    if private_path.is_absolute() or any(
        part in {"", ".", ".."} for part in private_path.parts
    ):
        raise _contract_error(
            "STABILITY_RELATIVE_PATH_INVALID", "worker_result.json"
        )
    checkpoint["relative_path"] = (
        PurePosixPath("private", "worker", *private_path.parts).as_posix()
    )
    return projection


def _validate_public_projection(
    *, public_result: Mapping[str, Any], private_result: Mapping[str, Any]
) -> None:
    if dict(public_result) != _expected_public_projection(private_result):
        raise _contract_error(
            "PUBLIC_MODEL_RESULT_PROJECTION_MISMATCH", "model_result.json"
        )


def _all_true_tensor_map(value: Any) -> bool:
    return (
        isinstance(value, Mapping)
        and bool(value)
        and all(item is True for item in value.values())
    )


def _validate_model_pack_metadata(
    *,
    result: Mapping[str, Any],
    plan: Mapping[str, Any],
    receipt: Mapping[str, Any],
    agent_receipt: Mapping[str, Any],
) -> Mapping[str, Any]:
    checkpoint = result.get("checkpoint")
    if not isinstance(checkpoint, Mapping):
        raise _contract_error("MODEL_PACK_METADATA_REQUIRED", "model_result.json")
    validation = checkpoint.get("validation_view")
    roundtrip = checkpoint.get("roundtrip_validation")
    if not isinstance(validation, Mapping) or not isinstance(roundtrip, Mapping):
        raise _contract_error(
            "MODEL_PACK_VALIDATION_EVIDENCE_REQUIRED", "model_result.json"
        )
    if (
        checkpoint.get("schema_version") != EXPECTED_MODEL_PACK_SCHEMA_VERSION
        or validation.get("schema_version") != EXPECTED_MODEL_PACK_SCHEMA_VERSION
    ):
        raise _contract_error(
            "MODEL_PACK_SCHEMA_INVALID", "model_result.json"
        )
    feature_layers = list(EXPECTED_FEATURE_LAYERS)
    if not all(
        value == feature_layers
        for value in (
            result.get("feature_layers"),
            plan.get("feature_layers"),
            receipt.get("feature_layers"),
            agent_receipt.get("feature_layers"),
            checkpoint.get("feature_layers"),
            validation.get("feature_layers"),
        )
    ):
        raise _contract_error(
            "MODEL_PACK_FEATURE_LAYERS_INVALID", "model_result.json"
        )
    architecture = result.get("architecture")
    if not isinstance(architecture, str) or not architecture or not all(
        value == architecture
        for value in (
            plan.get("architecture"),
            receipt.get("architecture"),
            validation.get("architecture"),
        )
    ):
        raise _contract_error("MODEL_PACK_SCOPE_INVALID", "model_result.json")
    image_size = validation.get("image_size")
    normalization = validation.get("input_normalization")
    if not (
        type(image_size) is int
        and image_size > 0
        and isinstance(normalization, Mapping)
        and normalization.get("color_space") == "RGB"
        and normalization.get("value_scale") == [0.0, 1.0]
        and normalization.get("resize") == [image_size, image_size]
        and normalization.get("mean") == [0.0, 0.0, 0.0]
        and normalization.get("std") == [1.0, 1.0, 1.0]
    ):
        raise _contract_error(
            "MODEL_PACK_INPUT_NORMALIZATION_INVALID", "model_result.json"
        )
    for field in (
        "selected_image_aggregation",
        "image_threshold",
        "pixel_threshold",
    ):
        if checkpoint.get(field) != validation.get(field):
            raise _contract_error(
                "MODEL_PACK_THRESHOLD_CONTRACT_MISMATCH", field
            )
    if validation.get("feature_fusion") != result.get("feature_fusion"):
        raise _contract_error(
            "MODEL_PACK_FUSION_CONTRACT_MISMATCH", "model_result.json"
        )
    backbone = validation.get("backbone")
    students = validation.get("students")
    normalizers = validation.get("normalizers")
    expected_layer_keys = {str(layer) for layer in EXPECTED_FEATURE_LAYERS}
    if not (
        isinstance(backbone, Mapping)
        and _all_true_tensor_map(backbone.get("state_dict"))
        and isinstance(backbone.get("model_yaml"), Mapping)
        and backbone["model_yaml"].get("present") is True
        and backbone.get("weights_sha256")
        == result.get("backbone_weights_sha256")
        and isinstance(students, Mapping)
        and set(students) == expected_layer_keys
        and all(_all_true_tensor_map(value) for value in students.values())
        and isinstance(normalizers, Mapping)
        and set(normalizers) == expected_layer_keys
        and all(_all_true_tensor_map(value) for value in normalizers.values())
    ):
        raise _contract_error(
            "MODEL_PACK_VALIDATION_VIEW_INVALID", "model_result.json"
        )
    tensor_count = sum(
        len(value)
        for value in (
            [backbone["state_dict"]]
            + list(students.values())
            + list(normalizers.values())
        )
    )
    reloads = roundtrip.get("student_state_dict_reload")
    if not (
        type(roundtrip.get("tensor_count")) is int
        and roundtrip.get("tensor_count") == tensor_count
        and roundtrip.get("all_tensors_cpu_and_finite") is True
        and roundtrip.get("backbone_state_dict_reload") == "PASS"
        and isinstance(reloads, Mapping)
        and set(reloads) == expected_layer_keys
        and all(value == "PASS" for value in reloads.values())
    ):
        raise _contract_error(
            "MODEL_PACK_ROUNDTRIP_EVIDENCE_INVALID", "model_result.json"
        )
    return checkpoint


def _validate_checkpoint_artifact(
    *,
    root: Path,
    checkpoint: Mapping[str, Any],
    receipt: Mapping[str, Any],
    agent_receipt: Mapping[str, Any],
) -> tuple[Path, str]:
    checkpoint_path = _safe_run_member(
        root,
        checkpoint.get("relative_path"),
        artifact="model checkpoint",
    )
    actual_sha256 = sha256_file(checkpoint_path)
    roundtrip = checkpoint.get("roundtrip_validation")
    expected_hashes = (
        checkpoint.get("sha256"),
        receipt.get("checkpoint_sha256"),
        agent_receipt.get("checkpoint_sha256"),
        roundtrip.get("checkpoint_sha256")
        if isinstance(roundtrip, Mapping)
        else None,
    )
    if any(
        not isinstance(value, str)
        or not hmac.compare_digest(value, actual_sha256)
        for value in expected_hashes
    ):
        raise _contract_error(
            "STABILITY_CHECKPOINT_SHA256_MISMATCH", checkpoint_path.name
        )
    size = checkpoint.get("bytes")
    if type(size) is not int or size <= 0 or size != checkpoint_path.stat().st_size:
        raise _contract_error(
            "STABILITY_CHECKPOINT_SIZE_MISMATCH", checkpoint_path.name
        )
    return checkpoint_path, actual_sha256


def _evaluation_membership(
    *, private_result: Mapping[str, Any], manifest: Mapping[str, Any]
) -> list[dict[str, Any]]:
    samples = manifest.get("samples")
    predictions = private_result.get("per_sample_predictions")
    if not isinstance(samples, list) or not isinstance(predictions, list):
        raise _contract_error(
            "PRIVATE_EVALUATION_MEMBERSHIP_REQUIRED", "worker_result.json"
        )
    expected: dict[str, str] = {}
    for sample in samples:
        if not isinstance(sample, Mapping):
            continue
        role = sample.get("role")
        if role not in {"development_normal", "development_anomaly"}:
            continue
        source_sample_id = sample.get("source_sample_id")
        if not isinstance(source_sample_id, str) or source_sample_id in expected:
            raise _contract_error(
                "EVALUATION_SOURCE_MEMBER_INVALID", "selection_manifest.json"
            )
        expected[source_sample_id] = (
            "normal" if role == "development_normal" else "anomaly"
        )
    observed: list[dict[str, Any]] = []
    seen: set[str] = set()
    for index, prediction in enumerate(predictions):
        if not isinstance(prediction, Mapping):
            raise _contract_error(
                "EVALUATION_MEMBERSHIP_INVALID", f"prediction[{index}]"
            )
        source_sample_id = prediction.get("source_sample_id")
        split_role = prediction.get("split_role")
        product_label = prediction.get("product_label")
        component_count = prediction.get("component_count_proxy")
        if (
            not isinstance(source_sample_id, str)
            or source_sample_id in seen
            or split_role not in {"calibration", "heldout_development"}
            or expected.get(source_sample_id) != product_label
            or isinstance(component_count, bool)
            or not isinstance(component_count, int)
            or component_count < 0
            or (product_label == "normal" and component_count != 0)
            or (product_label == "anomaly" and component_count == 0)
        ):
            raise _contract_error(
                "EVALUATION_MEMBERSHIP_INVALID", f"prediction[{index}]"
            )
        seen.add(source_sample_id)
        observed.append(
            {
                "source_sample_id": source_sample_id,
                "split_role": split_role,
                "product_label": product_label,
                "component_count_proxy": component_count,
            }
        )
    if seen != set(expected):
        raise _contract_error(
            "EVALUATION_MEMBERSHIP_INCOMPLETE", "worker_result.json"
        )
    calibration_members = [
        item for item in observed if item["split_role"] == "calibration"
    ]
    heldout_members = [
        item for item in observed if item["split_role"] == "heldout_development"
    ]
    calibration = private_result.get("calibration")
    heldout = private_result.get("heldout_development")
    if not isinstance(calibration, Mapping) or not isinstance(heldout, Mapping):
        raise _contract_error(
            "EVALUATION_DENOMINATOR_INVALID", "worker_result.json"
        )
    if calibration.get("sample_count") != len(calibration_members):
        raise _contract_error(
            "CALIBRATION_DENOMINATOR_MISMATCH", "worker_result.json"
        )
    if heldout.get("evaluation_sample_count") != len(heldout_members):
        raise _contract_error(
            "EVALUATION_DENOMINATOR_MISMATCH", "worker_result.json"
        )
    single_members = [
        item
        for item in heldout_members
        if item["product_label"] == "anomaly"
        and item["component_count_proxy"] == 1
    ]
    multi_members = [
        item
        for item in heldout_members
        if item["product_label"] == "anomaly"
        and item["component_count_proxy"] > 1
    ]
    for field, members in (
        ("single_region_proxy", single_members),
        ("multi_region_proxy", multi_members),
    ):
        topology = heldout.get(field)
        if (
            not isinstance(topology, Mapping)
            or topology.get("sample_count") != len(members)
            or isinstance(topology.get("component_count_proxy"), bool)
            or not isinstance(topology.get("component_count_proxy"), int)
            or topology["component_count_proxy"] < 0
        ):
            raise _contract_error(
                "TOPOLOGY_DENOMINATOR_MISMATCH", f"worker_result.json:{field}"
            )
    return sorted(observed, key=lambda item: item["source_sample_id"])


def _load_run(
    run_dir: str | Path, *, verification_implementation: Mapping[str, str]
) -> dict[str, Any]:
    root = Path(run_dir).expanduser().resolve(strict=True)
    if not root.is_dir():
        raise _contract_error("STABILITY_RUN_DIRECTORY_REQUIRED", root.name)
    paths = {key: root / name for key, name in _REQUIRED_FILES.items()}
    artifacts = {
        key: _load_json_object(path)
        for key, path in paths.items()
        if key != "runtime_events"
    }
    events = _load_json_array(paths["runtime_events"])
    receipt = artifacts["run_receipt"]
    result = artifacts["model_result"]
    plan = artifacts["plan"]
    manifest = artifacts["selection_manifest"]
    agent_receipt = artifacts["agent_receipt"]
    private_result = artifacts["private_result"]

    artifact_hashes = {
        "RUN_RECEIPT.json": sha256_file(paths["run_receipt"]),
        "model_result.json": _validate_referenced_hash(
            receipt,
            field="model_result_file_sha256",
            artifact_path=paths["model_result"],
        ),
        "model_experiment_plan.json": _validate_referenced_hash(
            receipt,
            field="plan_file_sha256",
            artifact_path=paths["plan"],
        ),
        "selection_manifest.json": _validate_referenced_hash(
            receipt,
            field="selection_manifest_sha256",
            artifact_path=paths["selection_manifest"],
        ),
        "model_experiment_agent_receipt.json": _validate_referenced_hash(
            receipt,
            field="agent_receipt_file_sha256",
            artifact_path=paths["agent_receipt"],
        ),
        "agent_runtime_events.json": _validate_referenced_hash(
            receipt,
            field="runtime_event_file_sha256",
            artifact_path=paths["runtime_events"],
        ),
    }

    plan_receipt_sha256 = _required(
        plan, ("receipt_sha256",), artifact="model_experiment_plan.json"
    )
    unsigned_plan = dict(plan)
    unsigned_plan.pop("receipt_sha256", None)
    if plan_receipt_sha256 != _canonical_digest(unsigned_plan):
        raise _contract_error(
            "MODEL_EXPERIMENT_PLAN_RECEIPT_MISMATCH", root.name
        )

    for artifact_name, artifact in (
        ("RUN_RECEIPT.json", receipt),
        ("model_result.json", result),
        ("model_experiment_plan.json", plan),
        ("selection_manifest.json", manifest),
        ("model_experiment_agent_receipt.json", agent_receipt),
        ("private/worker_result.json", private_result),
    ):
        _assert_false(
            artifact,
            artifact=artifact_name,
            field="production_release_allowed",
        )
    _assert_false(
        receipt,
        artifact="RUN_RECEIPT.json",
        field="machine_write_permitted",
    )

    agent_evidence_sha256 = _validate_agent_evidence(
        receipt=receipt,
        agent_receipt=agent_receipt,
        events=events,
        plan=plan,
        private_result_path=paths["private_result"],
    )
    artifact_hashes["private/worker_result.json"] = sha256_file(
        paths["private_result"]
    )
    _validate_public_projection(
        public_result=result,
        private_result=private_result,
    )
    checkpoint = _validate_model_pack_metadata(
        result=result,
        plan=plan,
        receipt=receipt,
        agent_receipt=agent_receipt,
    )
    checkpoint_path, checkpoint_sha256 = _validate_checkpoint_artifact(
        root=root,
        checkpoint=checkpoint,
        receipt=receipt,
        agent_receipt=agent_receipt,
    )
    artifact_hashes[checkpoint_path.relative_to(root).as_posix()] = (
        checkpoint_sha256
    )

    seed_contract = _read_seed_contract(plan, manifest)

    architecture_values = {
        "run_receipt": _required(
            receipt, ("architecture",), artifact="RUN_RECEIPT.json"
        ),
        "model_result": _required(
            result, ("architecture",), artifact="model_result.json"
        ),
        "plan": _required(plan, ("architecture",), artifact="model_experiment_plan.json"),
    }
    _assert_equal_within_run(field="architecture", artifact_values=architecture_values)
    identity_values = {
        "run_receipt": _required(
            receipt, ("implementation_identity",), artifact="RUN_RECEIPT.json"
        ),
        "model_result": _required(
            result, ("implementation_identity",), artifact="model_result.json"
        ),
    }
    _assert_equal_within_run(
        field="implementation_identity", artifact_values=identity_values
    )
    run_identity = identity_values["run_receipt"]
    if not isinstance(run_identity, Mapping):
        raise _contract_error(
            "OUTCOME_POLICY_SOURCE_DRIFT", "model_experiment_agent.py"
        )
    policy_compatibility = _outcome_policy_source_compatibility(
        run_identity.get("policy_module_sha256"),
        verification_implementation,
        run_label=root.name,
        model_seed=seed_contract["model_seed"],
    )
    backbone_values = {
        "run_receipt": _required(
            receipt, ("backbone_weights_sha256",), artifact="RUN_RECEIPT.json"
        ),
        "model_result": _required(
            result, ("backbone_weights_sha256",), artifact="model_result.json"
        ),
    }
    _assert_equal_within_run(
        field="backbone_weights_sha256", artifact_values=backbone_values
    )
    dataset_values = {
        "run_receipt": (
            _required(receipt, ("dataset_id",), artifact="RUN_RECEIPT.json"),
            _required(receipt, ("dataset_version",), artifact="RUN_RECEIPT.json"),
            _required(receipt, ("license_id",), artifact="RUN_RECEIPT.json"),
            _required(receipt, ("object_class",), artifact="RUN_RECEIPT.json"),
        ),
        "selection_manifest": (
            _required(manifest, ("dataset_id",), artifact="selection_manifest.json"),
            _required(
                manifest, ("dataset_version",), artifact="selection_manifest.json"
            ),
            _required(manifest, ("license_id",), artifact="selection_manifest.json"),
            _required(manifest, ("object_class",), artifact="selection_manifest.json"),
        ),
    }
    _assert_equal_within_run(field="dataset_identity", artifact_values=dataset_values)
    if _required(plan, ("dataset_id",), artifact="model_experiment_plan.json") != (
        dataset_values["run_receipt"][0]
    ):
        raise _contract_error("INTRA_RUN_CONTRACT_MISMATCH", "dataset_id:plan")

    roles = _validate_manifest_roles(manifest)
    selection_membership = _selection_membership(manifest)
    evaluation_membership = _evaluation_membership(
        private_result=private_result,
        manifest=manifest,
    )
    heldout = _required(result, ("heldout_development",), artifact="model_result.json")
    if not isinstance(heldout, Mapping):
        raise _contract_error(
            "STABILITY_MAPPING_REQUIRED", "model_result:heldout_development"
        )
    denominator_paths = {
        "evaluation_sample_count": ("evaluation_sample_count",),
        "single_region_sample_count": ("single_region_proxy", "sample_count"),
        "single_region_component_count_proxy": (
            "single_region_proxy",
            "component_count_proxy",
        ),
        "multi_region_sample_count": ("multi_region_proxy", "sample_count"),
        "multi_region_component_count_proxy": (
            "multi_region_proxy",
            "component_count_proxy",
        ),
    }
    heldout_denominators: dict[str, int] = {}
    for name, path in denominator_paths.items():
        value = _required(heldout, path, artifact="model_result.json")
        if isinstance(value, bool) or not isinstance(value, int) or value < 0:
            raise _contract_error("STABILITY_DENOMINATOR_INVALID", name)
        heldout_denominators[name] = value
    calibration_count = _required(
        result,
        ("calibration", "sample_count"),
        artifact="model_result.json",
    )
    if (
        isinstance(calibration_count, bool)
        or not isinstance(calibration_count, int)
        or calibration_count < 0
    ):
        raise _contract_error(
            "STABILITY_DENOMINATOR_INVALID", "calibration_sample_count"
        )
    heldout_denominators["calibration_sample_count"] = calibration_count

    metrics = {
        name: _finite_number(
            _required(result, path, artifact="model_result.json"), field=name
        )
        for name, path in _METRIC_PATHS.items()
    }
    train_losses = _required(result, ("train_losses",), artifact="model_result.json")
    validation_losses = _required(
        result, ("normal_validation_losses",), artifact="model_result.json"
    )
    if not isinstance(train_losses, list) or not train_losses:
        raise _contract_error("STABILITY_LOSS_SERIES_REQUIRED", "train_losses")
    if not isinstance(validation_losses, list) or not validation_losses:
        raise _contract_error(
            "STABILITY_LOSS_SERIES_REQUIRED", "normal_validation_losses"
        )
    try:
        derived_outcome = _outcome_policy.classify_experiment_outcome(
            train_losses=train_losses,
            normal_validation_losses=validation_losses,
            image_auroc=metrics["image_auroc"],
            pixel_auroc=metrics["pixel_auroc"],
            normal_image_false_positive_rate=metrics[
                "normal_image_false_positive_rate"
            ],
            image_f1=metrics["image_f1"],
            pixel_f1=metrics["pixel_f1"],
            single_region_recall=metrics[
                "single_region_image_detection_recall"
            ],
            multi_region_recall=metrics[
                "multi_region_image_detection_recall"
            ],
        )
    except (TypeError, ValueError) as exc:
        raise _contract_error(
            "MODEL_OUTCOME_DERIVATION_INVALID", type(exc).__name__
        ) from exc
    for field in ("optimization_status", "effectiveness_status"):
        if receipt.get(field) != derived_outcome[field]:
            raise _contract_error("MODEL_OUTCOME_DERIVATION_MISMATCH", field)
    metrics.update(
        {
            "train_loss_first_epoch": _finite_number(
                train_losses[0], field="train_loss_first_epoch"
            ),
            "train_loss_last_epoch": _finite_number(
                train_losses[-1], field="train_loss_last_epoch"
            ),
            "normal_validation_loss_first_epoch": _finite_number(
                validation_losses[0], field="normal_validation_loss_first_epoch"
            ),
            "normal_validation_loss_last_epoch": _finite_number(
                validation_losses[-1], field="normal_validation_loss_last_epoch"
            ),
        }
    )
    plan_contract = dict(plan)
    plan_contract.pop("seed", None)
    plan_contract.pop("model_seed", None)
    plan_contract.pop("receipt_sha256", None)

    return {
        "run_label": root.name,
        "seed": seed_contract["model_seed"],
        "model_seed": seed_contract["model_seed"],
        "split_seed": seed_contract["split_seed"],
        "seed_contract_status": seed_contract["status"],
        "seed_contract_issues": seed_contract["issues"],
        "run_status": _required(receipt, ("status",), artifact="RUN_RECEIPT.json"),
        "optimization_status": derived_outcome["optimization_status"],
        "effectiveness_status": derived_outcome["effectiveness_status"],
        "implementation_identity": identity_values["run_receipt"],
        "outcome_policy_compatibility": policy_compatibility,
        "source_binding_sha256": _required(
            plan, ("source_binding_sha256",), artifact="model_experiment_plan.json"
        ),
        "source_index_sha256": _required(
            plan, ("source_index_sha256",), artifact="model_experiment_plan.json"
        ),
        "backbone_weights_sha256": backbone_values["run_receipt"],
        "architecture": architecture_values["run_receipt"],
        "budget": _required(plan, ("budget",), artifact="model_experiment_plan.json"),
        "plan_contract": plan_contract,
        "dataset_identity": {
            "dataset_id": dataset_values["run_receipt"][0],
            "dataset_version": dataset_values["run_receipt"][1],
            "license_id": dataset_values["run_receipt"][2],
            "object_class": dataset_values["run_receipt"][3],
        },
        "role_denominators": roles,
        "selection_membership": selection_membership,
        "evaluation_membership": evaluation_membership,
        "heldout_denominators": heldout_denominators,
        "metrics": metrics,
        "artifact_sha256": artifact_hashes,
        "agent_evidence_sha256": agent_evidence_sha256,
    }


def _same_value_check(check_id: str, runs: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    values = [run[check_id] for run in runs]
    matches = all(value == values[0] for value in values[1:])
    return {
        "check_id": f"{check_id}_match",
        "status": "PASS" if matches else "FAIL",
        "value_sha256_by_seed": {
            str(run["seed"]): _canonical_digest(run[check_id]) for run in runs
        },
    }


def _metric_summary(
    runs: Sequence[Mapping[str, Any]], metric: str
) -> dict[str, Any]:
    values_by_seed = {
        str(run["seed"]): float(run["metrics"][metric]) for run in runs
    }
    values = list(values_by_seed.values())
    result: dict[str, Any] = {
        "values_by_seed": values_by_seed,
        "mean": statistics.fmean(values),
        "std": statistics.pstdev(values),
        "min": min(values),
        "max": max(values),
        "range": max(values) - min(values),
    }
    limit = PROMOTION_RANGE_LIMITS.get(metric)
    if limit is not None:
        result["max_allowed_range"] = limit
        result["range_within_limit"] = result["range"] <= limit
    return result


def build_model_stability_summary(
    run_directories: Sequence[str | Path],
) -> dict[str, Any]:
    """Load exactly three sealed runs and build a fail-closed stability summary."""

    if len(run_directories) != 3:
        raise _contract_error(
            "THREE_RUNS_REQUIRED", f"observed={len(run_directories)}"
        )
    verification_implementation = _verification_implementation()
    runs = [
        _load_run(
            run_dir,
            verification_implementation=verification_implementation,
        )
        for run_dir in run_directories
    ]
    runs.sort(key=lambda run: int(run["model_seed"]))
    model_seeds = [int(run["model_seed"]) for run in runs]
    if len(set(model_seeds)) != 3:
        raise _contract_error("THREE_UNIQUE_SEEDS_REQUIRED", repr(model_seeds))
    explicit_seed_contract = all(
        run["seed_contract_status"] == "EXPLICIT" for run in runs
    )
    split_seeds = [run["split_seed"] for run in runs]
    split_seed_match = explicit_seed_contract and len(set(split_seeds)) == 1
    seed_checks = [
        {
            "check_id": "explicit_split_model_seed_contract",
            "status": "PASS" if explicit_seed_contract else "FAIL",
            "observed_by_model_seed": {
                str(run["model_seed"]): {
                    "status": run["seed_contract_status"],
                    "issues": run["seed_contract_issues"],
                }
                for run in runs
            },
        },
        {
            "check_id": "split_seed_match",
            "status": "PASS" if split_seed_match else "FAIL",
            "observed_by_model_seed": {
                str(run["model_seed"]): run["split_seed"] for run in runs
            },
        },
        {
            "check_id": "model_seed_unique",
            "status": "PASS",
            "observed": model_seeds,
        },
    ]

    comparison_fields = (
        "implementation_identity",
        "source_binding_sha256",
        "source_index_sha256",
        "backbone_weights_sha256",
        "architecture",
        "budget",
        "plan_contract",
        "dataset_identity",
        "role_denominators",
        "selection_membership",
        "evaluation_membership",
        "heldout_denominators",
    )
    comparison_checks = seed_checks + [
        _same_value_check(field, runs) for field in comparison_fields
    ]
    failed_check_ids = [
        str(check["check_id"])
        for check in comparison_checks
        if check["status"] == "FAIL"
    ]
    comparability_pass = all(check["status"] == "PASS" for check in comparison_checks)

    metric_names = tuple(runs[0]["metrics"])
    if any(tuple(run["metrics"]) != metric_names for run in runs[1:]):
        raise _contract_error("STABILITY_METRIC_SCHEMA_MISMATCH", "metric names")
    metrics = {name: _metric_summary(runs, name) for name in metric_names}

    all_completed = all(run["run_status"] == EXPECTED_RUN_STATUS for run in runs)
    all_converged = all(
        run["optimization_status"] == EXPECTED_OPTIMIZATION_STATUS for run in runs
    )
    all_observed = all(
        run["effectiveness_status"] == EXPECTED_EFFECTIVENESS_STATUS for run in runs
    )
    criterion_checks = {
        "comparability_contract": comparability_pass,
        "all_runs_completed": all_completed,
        "all_optimization_converged": all_converged,
        "all_effectiveness_observed": all_observed,
        **{
            f"{metric}_range_within_limit": bool(
                metrics[metric]["range_within_limit"]
            )
            for metric in PROMOTION_RANGE_LIMITS
        },
    }
    blockers: list[str] = []
    if not comparability_pass:
        blockers.append("CROSS_SEED_COMPARABILITY_MISMATCH")
    if "explicit_split_model_seed_contract" in failed_check_ids:
        blockers.append("EXPLICIT_SPLIT_MODEL_SEED_CONTRACT_REQUIRED")
    if "split_seed_match" in failed_check_ids:
        blockers.append("SPLIT_SEED_MISMATCH")
    if "selection_membership_match" in failed_check_ids:
        blockers.append("SELECTION_MEMBERSHIP_MISMATCH")
    if "evaluation_membership_match" in failed_check_ids:
        blockers.append("EVALUATION_MEMBERSHIP_MISMATCH")
    if "role_denominators_match" in failed_check_ids:
        blockers.append("ROLE_DENOMINATOR_MISMATCH")
    if "heldout_denominators_match" in failed_check_ids:
        blockers.append("EVALUATION_DENOMINATOR_MISMATCH")
    if not all_completed:
        blockers.append("RUN_NOT_COMPLETED_ALL_SEEDS")
    if not all_converged:
        blockers.append("OPTIMIZATION_NOT_CONVERGED_ALL_SEEDS")
    if not all_observed:
        blockers.append("EFFECTIVENESS_NOT_OBSERVED_ALL_SEEDS")
    for metric, limit in PROMOTION_RANGE_LIMITS.items():
        if metrics[metric]["range"] > limit:
            blockers.append(f"{metric.upper()}_RANGE_EXCEEDS_LIMIT")

    eligible = not blockers
    public_runs = [
        {
            "run_label": run["run_label"],
            "seed": run["seed"],
            "split_seed": run["split_seed"],
            "model_seed": run["model_seed"],
            "seed_contract_status": run["seed_contract_status"],
            "seed_contract_issues": run["seed_contract_issues"],
            "run_status": run["run_status"],
            "optimization_status": run["optimization_status"],
            "effectiveness_status": run["effectiveness_status"],
            "artifact_sha256": run["artifact_sha256"],
            "agent_evidence_sha256": run["agent_evidence_sha256"],
        }
        for run in runs
    ]
    summary = {
        "schema_version": STABILITY_SCHEMA_VERSION,
        "verification_implementation": verification_implementation,
        "evidence_contract": {
            "required_artifacts": [
                "RUN_RECEIPT.json",
                "model_result.json",
                "model_experiment_plan.json",
                "selection_manifest.json",
                "model_experiment_agent_receipt.json",
                "agent_runtime_events.json",
                "private/worker_result.json",
                "private/worker/best_normality_model_pack.pt",
            ],
            "model_pack_schema_version": EXPECTED_MODEL_PACK_SCHEMA_VERSION,
            "model_pack_deserialization": "NOT_PERFORMED_NO_TORCH_IMPORT",
            "evaluation_membership_source": "PRIVATE_WORKER_RESULT",
            "outcome_derivation": (
                "RECOMPUTED_WITH_BOUND_CLASSIFY_EXPERIMENT_OUTCOME"
            ),
        },
        "evaluated_run_count": 3,
        "split_seed": split_seeds[0] if split_seed_match else None,
        "model_seeds": model_seeds,
        "seeds": model_seeds,
        "statistics_definition": "population_standard_deviation",
        "comparability": {
            "status": "PASS" if comparability_pass else "COMPARABILITY_HOLD",
            "failed_check_ids": failed_check_ids,
            "checks": comparison_checks,
        },
        "outcome_requirements": {
            "all_runs_completed": all_completed,
            "all_optimization_converged": all_converged,
            "all_effectiveness_observed": all_observed,
        },
        "promotion_thresholds": {
            "required_run_count": 3,
            "required_run_status": EXPECTED_RUN_STATUS,
            "required_optimization_status": EXPECTED_OPTIMIZATION_STATUS,
            "required_effectiveness_status": EXPECTED_EFFECTIVENESS_STATUS,
            "max_metric_ranges": PROMOTION_RANGE_LIMITS,
        },
        "metrics": metrics,
        "runs": public_runs,
        "promotion_gate": {
            "status": "PUBLIC_PROXY_STABLE" if eligible else "MODEL_PROMOTION_HOLD",
            "eligible": eligible,
            "criterion_checks": criterion_checks,
            "blockers": blockers,
        },
        "claim_boundary": (
            "A PUBLIC_PROXY_STABLE result is a bounded three-seed public-development "
            "proxy statement only. It is not factory validation, customer acceptance, "
            "model-registry promotion, installer readiness, or production release."
        ),
        "production_release_allowed": False,
    }
    compatibility_receipts = [
        run["outcome_policy_compatibility"]
        for run in runs if run["outcome_policy_compatibility"] is not None
    ]
    if compatibility_receipts:
        summary["outcome_policy_compatibility_receipts"] = compatibility_receipts
    return summary


def _format_metric(value: Any) -> str:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise _contract_error("STABILITY_FINITE_NUMBER_REQUIRED", "markdown metric")
    number = float(value)
    if not math.isfinite(number):
        raise _contract_error("STABILITY_FINITE_NUMBER_REQUIRED", "markdown metric")
    return f"{number:.9g}"


def render_model_stability_markdown(summary: Mapping[str, Any]) -> str:
    """Render a deterministic, reviewer-readable stability result."""

    if summary.get("production_release_allowed") is not False:
        raise _contract_error(
            "PRODUCTION_AUTHORITY_MUST_REMAIN_FALSE", "stability summary"
        )
    promotion = _required(summary, ("promotion_gate",), artifact="stability summary")
    metrics = _required(summary, ("metrics",), artifact="stability summary")
    runs = _required(summary, ("runs",), artifact="stability summary")
    comparison = _required(summary, ("comparability",), artifact="stability summary")
    verification = _required(
        summary, ("verification_implementation",), artifact="stability summary"
    )
    evidence_contract = _required(
        summary, ("evidence_contract",), artifact="stability summary"
    )
    if not isinstance(promotion, Mapping) or not isinstance(metrics, Mapping):
        raise _contract_error("STABILITY_MAPPING_REQUIRED", "markdown summary")
    if not isinstance(runs, list) or not isinstance(comparison, Mapping):
        raise _contract_error("STABILITY_MAPPING_REQUIRED", "markdown summary")
    if not isinstance(verification, Mapping) or not isinstance(
        evidence_contract, Mapping
    ):
        raise _contract_error("STABILITY_MAPPING_REQUIRED", "markdown summary")

    blockers = promotion.get("blockers", [])
    if not isinstance(blockers, list):
        raise _contract_error("STABILITY_LIST_REQUIRED", "promotion blockers")
    lines: list[str] = [
        "# VisionData Gate Three-Seed Model Stability",
        "",
        f"- Stability schema: `{summary.get('schema_version')}`",
        f"- Promotion gate: `{promotion.get('status')}`",
        f"- Comparable runs: `{comparison.get('status')}`",
        f"- Split seed: `{summary.get('split_seed')}`",
        f"- Model seeds: `{', '.join(str(seed) for seed in summary.get('model_seeds', []))}`",
        "- Stability verifier SHA-256: "
        f"`{verification.get('stability_module_sha256')}`",
        "- Outcome policy SHA-256: "
        f"`{verification.get('outcome_policy_module_sha256')}`",
        f"- Outcome derivation: `{evidence_contract.get('outcome_derivation')}`",
        "- Model Pack deserialization: "
        f"`{summary.get('evidence_contract', {}).get('model_pack_deserialization')}`",
        "- production_release_allowed: false",
        "",
        "This artifact measures a public development proxy only. It is not factory ",
        "validation, customer acceptance, installer readiness, or production release.",
        "",
        "## Run outcomes",
        "",
        "| Seed | Run | Optimization | Effectiveness |",
        "|---:|---|---|---|",
    ]
    compatibility = summary.get("outcome_policy_compatibility_receipts", [])
    if compatibility:
        section = [
            "## Exact reviewed source compatibility", "",
            "Training used the preserved historical policy, not the current verifier source.",
            "Only the reviewed module-docstring reverse patch was admitted.",
            "- training_identity_rewritten: false", "",
        ]
        for receipt in compatibility:
            unsigned = {key: value for key, value in receipt.items() if key != "receipt_sha256"}
            if (
                receipt.get("receipt_sha256") != _canonical_jcs_digest(unsigned)
                or receipt.get("verification_implementation") != verification
                or receipt.get("historical_policy_module_sha256") != _HISTORICAL_POLICY_SHA256
                or receipt.get("current_policy_module_sha256") != _DOCUMENTED_POLICY_SHA256
                or receipt.get("training_identity_rewritten") is not False
            ):
                raise _contract_error("OUTCOME_POLICY_COMPATIBILITY_RECEIPT_INVALID", "stability summary")
            section.extend([
                f"- Run `{receipt['run_label']}`, model seed `{receipt['model_seed']}`:",
                f"  - Historical training policy: `{receipt['historical_policy_module_sha256']}`",
                f"  - Current verification policy: `{receipt['current_policy_module_sha256']}`",
                f"  - Exact compatibility receipt: `{receipt['receipt_sha256']}`", "",
            ])
        insertion = lines.index("## Run outcomes")
        lines[insertion:insertion] = section
    for run in runs:
        if not isinstance(run, Mapping):
            raise _contract_error("STABILITY_MAPPING_REQUIRED", "run summary")
        lines.append(
            "| {seed} | `{run}` | `{optimization}` | `{effectiveness}` |".format(
                seed=run.get("seed"),
                run=run.get("run_label"),
                optimization=run.get("optimization_status"),
                effectiveness=run.get("effectiveness_status"),
            )
        )

    lines.extend(
        [
            "",
            "## Aggregated metrics",
            "",
            "Population standard deviation is reported for the complete three-run set.",
            "",
            "| Metric | Mean | Std | Min | Max | Range | Allowed range | Within limit |",
            "|---|---:|---:|---:|---:|---:|---:|---|",
        ]
    )
    for name, metric in metrics.items():
        if not isinstance(metric, Mapping):
            raise _contract_error("STABILITY_MAPPING_REQUIRED", f"metric:{name}")
        allowed = metric.get("max_allowed_range")
        within = metric.get("range_within_limit")
        lines.append(
            "| `{name}` | {mean} | {std} | {minimum} | {maximum} | {span} | "
            "{allowed} | {within} |".format(
                name=name,
                mean=_format_metric(metric.get("mean")),
                std=_format_metric(metric.get("std")),
                minimum=_format_metric(metric.get("min")),
                maximum=_format_metric(metric.get("max")),
                span=_format_metric(metric.get("range")),
                allowed="-" if allowed is None else _format_metric(allowed),
                within="-" if within is None else str(bool(within)).lower(),
            )
        )

    lines.extend(["", "## Promotion blockers", ""])
    if blockers:
        lines.extend(f"- `{blocker}`" for blocker in blockers)
    else:
        lines.append("- None for the bounded public-proxy stability gate.")
    lines.extend(
        [
            "",
            "## Claim boundary",
            "",
            str(summary.get("claim_boundary", "")),
            "",
        ]
    )
    return "\n".join(lines)


def _write_immutable(path: Path, data: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        with path.open("xb") as handle:
            handle.write(data)
    except FileExistsError as exc:
        if not path.is_file() or path.read_bytes() != data:
            raise _contract_error(
                "STABILITY_OUTPUT_ALREADY_DIFFERS", path.name
            ) from exc


def write_model_stability_artifacts(
    summary: Mapping[str, Any], output_directory: str | Path
) -> dict[str, str]:
    """Write immutable JSON, Markdown, and a two-artifact SHA-256 manifest."""

    if summary.get("production_release_allowed") is not False:
        raise _contract_error(
            "PRODUCTION_AUTHORITY_MUST_REMAIN_FALSE", "stability summary"
        )
    output = Path(output_directory).expanduser().resolve(strict=False)
    json_name = "MODEL_STABILITY_SUMMARY.json"
    markdown_name = "MODEL_STABILITY_SUMMARY.md"
    sums_name = "SHA256SUMS.txt"
    json_bytes = canonical_json_bytes(summary)
    markdown_bytes = render_model_stability_markdown(summary).encode("utf-8")
    json_sha256 = hashlib.sha256(json_bytes).hexdigest()
    markdown_sha256 = hashlib.sha256(markdown_bytes).hexdigest()
    sums_bytes = (
        f"{json_sha256}  {json_name}\n"
        f"{markdown_sha256}  {markdown_name}\n"
    ).encode("utf-8")
    _write_immutable(output / json_name, json_bytes)
    _write_immutable(output / markdown_name, markdown_bytes)
    _write_immutable(output / sums_name, sums_bytes)
    return {
        json_name: json_sha256,
        markdown_name: markdown_sha256,
        sums_name: hashlib.sha256(sums_bytes).hexdigest(),
    }
