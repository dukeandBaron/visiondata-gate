"""Explicit Image/Batch/Case/Episode denominator contracts.

The contract prevents sample counts, Gate runs, adjudicated governance cases,
and paired comparison episodes from being silently pooled.  It binds what is
measured, preserves pending denominators as zero-valued NOT_MEASURED states,
and never grants production authority.
"""

from __future__ import annotations

import hashlib
import hmac
import json
from pathlib import Path
from typing import Any, Literal

import rfc8785
from pydantic import ConfigDict, Field, model_validator

from .product_models import ProductModel


SHA256_PATTERN = r"^[0-9a-f]{64}$"
CONTRACT_FRAME_MAGIC = b"visiondata-gate.evaluation-unit-contract.v1\x00"

EvaluationUnitKind = Literal["IMAGE", "BATCH", "CASE", "EPISODE"]
EvaluationDenominatorStatus = Literal[
    "MEASURED",
    "NOT_MEASURED_PENDING_ADJUDICATION",
    "NOT_APPLICABLE",
]


def _canonical_bytes(value: Any) -> bytes:
    try:
        return rfc8785.dumps(value)
    except (rfc8785.CanonicalizationError, TypeError, UnicodeError) as error:
        raise ValueError(
            f"evaluation unit contract cannot be canonicalized: {error}"
        ) from error


def _domain_sha256(domain: str, value: Any) -> str:
    domain_bytes = domain.encode("utf-8")
    payload = _canonical_bytes(value)
    frame = b"".join(
        (
            CONTRACT_FRAME_MAGIC,
            len(domain_bytes).to_bytes(2, "big"),
            domain_bytes,
            len(payload).to_bytes(8, "big"),
            payload,
        )
    )
    return hashlib.sha256(frame).hexdigest()


class EvaluationDenominatorV1(ProductModel):
    """One denominator with an explicit evidence and measurement state."""

    model_config = ConfigDict(frozen=True)

    unit_kind: EvaluationUnitKind
    status: EvaluationDenominatorStatus
    count: int = Field(ge=0, strict=True)
    evidence_binding_sha256: str | None = Field(default=None, pattern=SHA256_PATTERN)
    definition: str = Field(min_length=8, max_length=600)
    pending_reason: str | None = Field(default=None, min_length=8, max_length=600)

    @model_validator(mode="after")
    def validate_denominator(self) -> EvaluationDenominatorV1:
        if self.status == "MEASURED":
            if self.count <= 0 or self.evidence_binding_sha256 is None:
                raise ValueError(
                    "measured denominator requires a positive count and evidence binding"
                )
            if self.pending_reason is not None:
                raise ValueError("measured denominator cannot carry a pending reason")
            return self
        if self.count != 0 or self.evidence_binding_sha256 is not None:
            raise ValueError(
                "unmeasured denominator must remain zero and cannot carry evidence"
            )
        if (
            self.status == "NOT_MEASURED_PENDING_ADJUDICATION"
            and self.pending_reason is not None
        ):
            return self
        if self.status == "NOT_MEASURED_PENDING_ADJUDICATION":
            raise ValueError("pending denominator requires an explicit reason")
        if self.pending_reason is not None:
            raise ValueError("not-applicable denominator cannot carry a pending reason")
        return self


class ImageBatchCaseEpisodeContractV1(ProductModel):
    """Frozen four-grain evaluation contract for one evidence scope."""

    model_config = ConfigDict(frozen=True)

    schema_version: Literal["visiondata-gate.image-batch-case-episode-contract.v1"] = (
        "visiondata-gate.image-batch-case-episode-contract.v1"
    )
    digest_contract: Literal["RFC8785_JCS_SHA256_LENGTH_PREFIX_DOMAIN_V1"] = (
        "RFC8785_JCS_SHA256_LENGTH_PREFIX_DOMAIN_V1"
    )
    evaluation_id: str = Field(pattern=r"^[A-Za-z0-9][A-Za-z0-9_.:-]{1,159}$")
    source_scope: Literal[
        "PRIVATE_AUTHORIZED_SHADOW",
        "SYNTHETIC_FIXED_FIXTURE",
        "PUBLIC_INDUSTRIAL_PROXY_WITH_PROGRAMMATIC_GOVERNANCE_TRUTH",
    ]
    dataset_identity_sha256: str = Field(pattern=SHA256_PATTERN)
    source_profile_image_count: int = Field(ge=0, strict=True)
    image: EvaluationDenominatorV1
    batch: EvaluationDenominatorV1
    case: EvaluationDenominatorV1
    episode: EvaluationDenominatorV1
    false_release_rate_denominator: EvaluationDenominatorV1
    false_block_rate_denominator: EvaluationDenominatorV1
    kpi_denominator_units: dict[str, EvaluationUnitKind] = Field(
        default_factory=lambda: {
            "image_quality_observation": "IMAGE",
            "gate_batch_disposition": "BATCH",
            "false_release_rate": "CASE",
            "false_block_rate": "CASE",
            "dynamic_vs_fixed_comparison": "EPISODE",
        }
    )
    image_count_may_be_used_as_case_count: Literal[False] = False
    batch_count_may_be_used_as_case_count: Literal[False] = False
    pending_truth_counts_as_measured: Literal[False] = False
    production_release_allowed: Literal[False] = False
    contract_sha256: str = Field(pattern=SHA256_PATTERN)

    @model_validator(mode="after")
    def validate_contract(self) -> ImageBatchCaseEpisodeContractV1:
        expected_units = {
            "image": "IMAGE",
            "batch": "BATCH",
            "case": "CASE",
            "episode": "EPISODE",
        }
        for field_name, expected_unit in expected_units.items():
            denominator = getattr(self, field_name)
            if denominator.unit_kind != expected_unit:
                raise ValueError(
                    f"{field_name} denominator must use the {expected_unit} unit"
                )
        if (
            self.image.status == "MEASURED"
            and self.image.count > self.source_profile_image_count
        ):
            raise ValueError(
                "measured Image denominator cannot exceed the source-profile image count"
            )
        expected_kpi_units = {
            "image_quality_observation": "IMAGE",
            "gate_batch_disposition": "BATCH",
            "false_release_rate": "CASE",
            "false_block_rate": "CASE",
            "dynamic_vs_fixed_comparison": "EPISODE",
        }
        if self.kpi_denominator_units != expected_kpi_units:
            raise ValueError("evaluation KPI denominator mapping drifted")
        for field_name in (
            "false_release_rate_denominator",
            "false_block_rate_denominator",
        ):
            rate_denominator = getattr(self, field_name)
            if rate_denominator.unit_kind != "CASE":
                raise ValueError(f"{field_name} must use the CASE unit")
            if rate_denominator.status == "MEASURED":
                if self.case.status != "MEASURED":
                    raise ValueError(
                        f"{field_name} cannot be measured while the Case denominator "
                        "is unmeasured"
                    )
                if rate_denominator.count > self.case.count:
                    raise ValueError(
                        f"{field_name} cannot exceed the measured Case denominator"
                    )
        return self


def build_image_batch_case_episode_contract(
    *,
    evaluation_id: str,
    source_scope: Literal[
        "PRIVATE_AUTHORIZED_SHADOW",
        "SYNTHETIC_FIXED_FIXTURE",
        "PUBLIC_INDUSTRIAL_PROXY_WITH_PROGRAMMATIC_GOVERNANCE_TRUTH",
    ],
    dataset_identity_sha256: str,
    source_profile_image_count: int,
    image: EvaluationDenominatorV1,
    batch: EvaluationDenominatorV1,
    case: EvaluationDenominatorV1,
    episode: EvaluationDenominatorV1,
    false_release_rate_denominator: EvaluationDenominatorV1,
    false_block_rate_denominator: EvaluationDenominatorV1,
) -> ImageBatchCaseEpisodeContractV1:
    stable = {
        "schema_version": "visiondata-gate.image-batch-case-episode-contract.v1",
        "digest_contract": "RFC8785_JCS_SHA256_LENGTH_PREFIX_DOMAIN_V1",
        "evaluation_id": evaluation_id,
        "source_scope": source_scope,
        "dataset_identity_sha256": dataset_identity_sha256,
        "source_profile_image_count": source_profile_image_count,
        "image": image.model_dump(mode="json"),
        "batch": batch.model_dump(mode="json"),
        "case": case.model_dump(mode="json"),
        "episode": episode.model_dump(mode="json"),
        "false_release_rate_denominator": (
            false_release_rate_denominator.model_dump(mode="json")
        ),
        "false_block_rate_denominator": (
            false_block_rate_denominator.model_dump(mode="json")
        ),
        "kpi_denominator_units": {
            "image_quality_observation": "IMAGE",
            "gate_batch_disposition": "BATCH",
            "false_release_rate": "CASE",
            "false_block_rate": "CASE",
            "dynamic_vs_fixed_comparison": "EPISODE",
        },
        "image_count_may_be_used_as_case_count": False,
        "batch_count_may_be_used_as_case_count": False,
        "pending_truth_counts_as_measured": False,
        "production_release_allowed": False,
    }
    contract = ImageBatchCaseEpisodeContractV1(
        **stable,
        contract_sha256=_domain_sha256("evaluation-unit-contract", stable),
    )
    verify_image_batch_case_episode_contract(contract)
    return contract


def verify_image_batch_case_episode_contract(
    contract: ImageBatchCaseEpisodeContractV1,
) -> None:
    validated = ImageBatchCaseEpisodeContractV1.model_validate(
        contract.model_dump(mode="json")
    )
    stable = validated.model_dump(mode="json", exclude={"contract_sha256"})
    observed = _domain_sha256("evaluation-unit-contract", stable)
    if not hmac.compare_digest(observed, validated.contract_sha256):
        raise ValueError("evaluation unit contract digest mismatch")


def build_omni_product_pilot_evaluation_contract(
    product_pilot_receipt_path: str | Path,
    *,
    expected_receipt_sha256: str,
) -> ImageBatchCaseEpisodeContractV1:
    """Project the current private Pilot without inventing Case/Episode truth."""

    path = Path(product_pilot_receipt_path).expanduser().resolve(strict=True)
    payload_bytes = path.read_bytes()
    observed_sha256 = hashlib.sha256(payload_bytes).hexdigest()
    if not hmac.compare_digest(observed_sha256, expected_receipt_sha256):
        raise ValueError("authorized product pilot receipt SHA-256 mismatch")

    def reject_duplicate_keys(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
        value: dict[str, Any] = {}
        for key, item in pairs:
            if key in value:
                raise ValueError(f"duplicate JSON key: {key}")
            value[key] = item
        return value

    try:
        payload = json.loads(
            payload_bytes.decode("utf-8"),
            object_pairs_hook=reject_duplicate_keys,
        )
    except (json.JSONDecodeError, UnicodeDecodeError, ValueError) as error:
        raise ValueError("authorized product pilot receipt is invalid JSON") from error
    if not isinstance(payload, dict):
        raise ValueError("authorized product pilot receipt must be an object")
    if not (
        payload.get("schema_version") == "visiondata-gate.authorized-product-pilot.v2"
        and payload.get("execution_status") == "COMPLETED"
        and payload.get("final_decision")
        in {"PASS", "QUARANTINE", "RECAPTURE", "DEFER"}
        and payload.get("source_path_serialized") is False
        and payload.get("source_assets_copied_into_product") is False
    ):
        raise ValueError("authorized product pilot receipt failed boundary checks")
    selected_image_count = payload.get("selected_image_count")
    source_image_count = payload.get("source_image_count")
    dataset_identity = payload.get("source_profile_sha256")
    if (
        not isinstance(selected_image_count, int)
        or isinstance(selected_image_count, bool)
        or selected_image_count <= 0
        or not isinstance(source_image_count, int)
        or isinstance(source_image_count, bool)
        or source_image_count < selected_image_count
        or not isinstance(dataset_identity, str)
    ):
        raise ValueError("authorized product pilot denominator fields are invalid")
    return build_image_batch_case_episode_contract(
        evaluation_id="omni-rc3-authorized-product-pilot",
        source_scope="PRIVATE_AUTHORIZED_SHADOW",
        dataset_identity_sha256=dataset_identity,
        source_profile_image_count=source_image_count,
        image=EvaluationDenominatorV1(
            unit_kind="IMAGE",
            status="MEASURED",
            count=selected_image_count,
            evidence_binding_sha256=observed_sha256,
            definition=(
                "selected images reported by one hash-bound authorized ProductService "
                "Pilot receipt; this is not a Case denominator"
            ),
        ),
        batch=EvaluationDenominatorV1(
            unit_kind="BATCH",
            status="MEASURED",
            count=1,
            evidence_binding_sha256=observed_sha256,
            definition=(
                "one ProductService Gate batch/run represented by the authorized Pilot "
                "receipt; this is not factory prevalence"
            ),
        ),
        case=EvaluationDenominatorV1(
            unit_kind="CASE",
            status="NOT_MEASURED_PENDING_ADJUDICATION",
            count=0,
            definition=(
                "independently adjudicated governance cases eligible for false-release "
                "and false-block metrics"
            ),
            pending_reason=(
                "no independent Case-level QMS or dual-human adjudication manifest is "
                "bound to the current Pilot receipt"
            ),
        ),
        episode=EvaluationDenominatorV1(
            unit_kind="EPISODE",
            status="NOT_MEASURED_PENDING_ADJUDICATION",
            count=0,
            definition=(
                "same-input same-truth paired Fixed-versus-Dynamic execution episodes"
            ),
            pending_reason=(
                "the private Pilot receipt does not contain a paired strategy episode "
                "manifest"
            ),
        ),
        false_release_rate_denominator=EvaluationDenominatorV1(
            unit_kind="CASE",
            status="NOT_MEASURED_PENDING_ADJUDICATION",
            count=0,
            definition=(
                "independently adjudicated cases whose truth requires blocking; the "
                "denominator for false-release rate"
            ),
            pending_reason=(
                "the current Pilot receipt does not bind independently adjudicated "
                "BLOCK_REQUIRED truth cases"
            ),
        ),
        false_block_rate_denominator=EvaluationDenominatorV1(
            unit_kind="CASE",
            status="NOT_MEASURED_PENDING_ADJUDICATION",
            count=0,
            definition=(
                "independently adjudicated cases whose truth allows release; the "
                "denominator for false-block rate"
            ),
            pending_reason=(
                "the current Pilot receipt does not bind independently adjudicated "
                "RELEASE_ALLOWED truth cases"
            ),
        ),
    )


__all__ = [
    "EvaluationDenominatorV1",
    "ImageBatchCaseEpisodeContractV1",
    "build_image_batch_case_episode_contract",
    "build_omni_product_pilot_evaluation_contract",
    "verify_image_batch_case_episode_contract",
]
