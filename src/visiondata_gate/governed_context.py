"""Governed, site-scoped historical memory and incident context assembly."""

from __future__ import annotations

import hashlib
import hmac
import json
import math
import re
import unicodedata
from collections import Counter
from decimal import Decimal, ROUND_HALF_EVEN, localcontext
from datetime import datetime
from fractions import Fraction
from pathlib import Path
from typing import Annotated, Literal, Mapping, Protocol, Sequence

from pydantic import ConfigDict, Field, TypeAdapter, field_validator, model_validator

from .evidence import canonical_json_bytes
from .industrial_incident import IndustrialIncidentCase, verify_industrial_incident_case
from .product_models import ProductModel
from .site_pack import FactorySitePack, verify_factory_site_pack


def _sha256(value: object) -> str:
    return hashlib.sha256(canonical_json_bytes(value)).hexdigest()


def _aware(value: datetime) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("memory timestamps require an explicit UTC offset")
    return value


def _tokens(value: str) -> set[str]:
    lowered = value.casefold()
    tokens = set(re.findall(r"[a-z0-9_.-]+", lowered))
    for chunk in re.findall(r"[\u4e00-\u9fff]+", lowered):
        if len(chunk) == 1:
            tokens.add(chunk)
        else:
            tokens.update(chunk[index : index + 2] for index in range(len(chunk) - 1))
    return tokens


class MemoryScope(ProductModel):
    site_id: str = Field(pattern=r"^[a-z0-9][a-z0-9._-]{2,119}$")
    product_family: str | None = Field(default=None, max_length=120)
    line_id: str | None = Field(default=None, max_length=120)
    station_id: str | None = Field(default=None, max_length=120)
    camera_id: str | None = Field(default=None, max_length=120)


def _memory_scope_hash_payload(
    scope: MemoryScope | dict[str, object],
) -> dict[str, object]:
    """Keep pre-station v1 cards verifiable while sealing station-aware cards."""

    payload = (
        scope.model_dump(mode="json", exclude_none=False)
        if isinstance(scope, MemoryScope)
        else dict(scope)
    )
    if payload.get("station_id") is None:
        payload.pop("station_id", None)
    return payload


class ApprovedMemoryContent(ProductModel):
    pattern: str = Field(min_length=3, max_length=500)
    recommended_first_check: str = Field(min_length=3, max_length=240)
    avoid_first_action: str | None = Field(default=None, max_length=240)
    advisory_summary: str = Field(min_length=3, max_length=800)


class ApprovedMemoryCard(ProductModel):
    schema_version: Literal["visiondata-gate.approved-memory-card.v1"] = (
        "visiondata-gate.approved-memory-card.v1"
    )
    memory_id: str = Field(pattern=r"^memory_[0-9a-f]{20}$")
    memory_type: Literal[
        "INVESTIGATION_HINT",
        "QUESTION_TEMPLATE",
        "OUTPUT_TEMPLATE",
        "FIELD_ALIAS",
        "WORKER_PRIORITY_HINT",
    ]
    memory_version: int = Field(ge=1)
    scope: MemoryScope
    content: ApprovedMemoryContent
    source_case_ids: list[str] = Field(min_length=1, max_length=32)
    approval_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    valid_from: datetime
    valid_until: datetime | None = None
    status: Literal["APPROVED", "REVOKED"] = "APPROVED"
    historical_reference_only: Literal[True] = True
    may_set_current_case_fact: Literal[False] = False
    policy_judge_input: Literal[False] = False
    machine_action_permitted: Literal[False] = False
    memory_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")

    @field_validator("valid_from", "valid_until")
    @classmethod
    def validate_timestamps(cls, value: datetime | None) -> datetime | None:
        return _aware(value) if value is not None else None

    @model_validator(mode="after")
    def validate_validity_window(self) -> ApprovedMemoryCard:
        if self.valid_until is not None and self.valid_until <= self.valid_from:
            raise ValueError("memory valid_until must follow valid_from")
        if len(self.source_case_ids) != len(set(self.source_case_ids)):
            raise ValueError("memory source_case_ids must be unique")
        return self


class LegacyMemoryQueryV1(ProductModel):
    """Exact pre-clock query used only to verify/replay historical v1 receipts."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    site_id: str
    current_case_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    as_of: datetime
    product_family: str | None = None
    line_id: str | None = None
    camera_id: str | None = None
    terms: list[str] = Field(default_factory=list, max_length=32)
    limit: int = Field(default=4, ge=1, le=12)

    @field_validator("as_of")
    @classmethod
    def validate_as_of(cls, value: datetime) -> datetime:
        return _aware(value)


class LegacyHybridMemoryQueryV2(ProductModel):
    """Original single-clock hybrid query; dual-clock authority is unknowable."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    site_id: str = Field(pattern=r"^[a-z0-9][a-z0-9._-]{2,119}$")
    current_case_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    as_of: datetime
    product_family: str | None = Field(default=None, max_length=120)
    line_id: str | None = Field(default=None, max_length=120)
    station_id: str | None = Field(default=None, max_length=120)
    camera_id: str | None = Field(default=None, max_length=120)
    terms: list[str] = Field(default_factory=list, max_length=32)
    limit: int = Field(default=4, ge=1, le=12)

    @field_validator("as_of")
    @classmethod
    def validate_as_of(cls, value: datetime) -> datetime:
        return _aware(value)


class MemoryProcessingTimeSource(ProductModel):
    source_kind: Literal["INCIDENT_COMMAND_ADMISSION", "EXPLICIT_CALLER_BINDING"]
    source_id: str = Field(min_length=1, max_length=200)
    source_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")

    @model_validator(mode="after")
    def validate_source_identity(self) -> MemoryProcessingTimeSource:
        if self.source_kind == "INCIDENT_COMMAND_ADMISSION" and not re.fullmatch(
            r"incident_command_[0-9a-f]{24}", self.source_id
        ):
            raise ValueError("incident admission clock source requires a command ID")
        return self


class ClockedMemoryQueryV3(ProductModel):
    site_id: str = Field(pattern=r"^[a-z0-9][a-z0-9._-]{2,119}$")
    current_case_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    event_time: datetime
    processing_time: datetime
    processing_time_source: MemoryProcessingTimeSource
    product_family: str | None = Field(default=None, max_length=120)
    line_id: str | None = Field(default=None, max_length=120)
    station_id: str | None = Field(default=None, max_length=120)
    camera_id: str | None = Field(default=None, max_length=120)
    terms: list[str] = Field(default_factory=list, max_length=32)
    limit: int = Field(default=4, ge=1, le=12)

    @field_validator("event_time", "processing_time")
    @classmethod
    def validate_query_clock(cls, value: datetime) -> datetime:
        return _aware(value)

    @model_validator(mode="after")
    def validate_clock_order(self) -> ClockedMemoryQueryV3:
        if self.processing_time < self.event_time:
            raise ValueError("memory processing_time must not precede event_time")
        return self


# Compatibility name for the exact historical v1 API. New code must select a
# versioned query explicitly and must not infer processing time for this type.
MemoryQuery = LegacyMemoryQueryV1


class LegacyMemorySelectionV1(ProductModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    rank: int = Field(ge=1)
    memory_id: str
    memory_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    score: int = Field(ge=1)
    selection_reasons: list[str] = Field(min_length=1)
    source_case_ids: list[str]
    historical_reference_only: Literal[True] = True


class LegacyMemoryRejectionV1(ProductModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    memory_id: str
    memory_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    reason_code: Literal[
        "CROSS_SITE_SCOPE",
        "PRODUCT_SCOPE_MISMATCH",
        "LINE_SCOPE_MISMATCH",
        "CAMERA_SCOPE_MISMATCH",
        "NOT_YET_VALID",
        "EXPIRED",
        "REVOKED",
        "NO_QUERY_RELEVANCE",
    ]


class LegacyMemoryRetrievalReceiptV1(ProductModel):
    """Byte-compatible historical schema recovered from the read-only backup."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_version: Literal["visiondata-gate.memory-retrieval-receipt.v1"] = (
        "visiondata-gate.memory-retrieval-receipt.v1"
    )
    query_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    current_case_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    memory_store_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    candidate_count: int = Field(ge=0)
    selected: list[LegacyMemorySelectionV1]
    rejected: list[LegacyMemoryRejectionV1]
    cross_site_memory_selected_count: Literal[0] = 0
    stale_memory_selected_count: Literal[0] = 0
    historical_memory_used_as_fact_count: Literal[0] = 0
    selection_algorithm: Literal["SCOPE_THEN_RELEVANCE_V1"] = "SCOPE_THEN_RELEVANCE_V1"
    receipt_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")


MemoryRetrievalReceipt = LegacyMemoryRetrievalReceiptV1


class MemorySelection(ProductModel):
    rank: int = Field(ge=1)
    memory_id: str
    memory_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    score: int = Field(ge=1)
    selection_reasons: list[str] = Field(min_length=1)
    source_case_ids: list[str]
    accepted: Literal["historical_reference_only"] = "historical_reference_only"
    historical_reference_only: Literal[True] = True
    may_set_current_case_fact: Literal[False] = False


class MemoryRejection(ProductModel):
    memory_id: str
    memory_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    reason_code: Literal[
        "CROSS_SITE_SCOPE",
        "PRODUCT_SCOPE_MISMATCH",
        "LINE_SCOPE_MISMATCH",
        "STATION_SCOPE_MISMATCH",
        "CAMERA_SCOPE_MISMATCH",
        "NOT_YET_VALID",
        "EXPIRED",
        "REVOKED",
        "NO_QUERY_RELEVANCE",
        "RANK_LIMIT_EXCEEDED",
    ]


class HybridRetrievalProfileV2(ProductModel):
    """Frozen, dependency-free retrieval policy for new incident runs.

    The default profile deliberately keeps embedding disabled.  A local adapter
    may be supplied explicitly, but remote retrieval is outside this contract.
    """

    schema_version: Literal["visiondata-gate.hybrid-retrieval-profile.v2"] = (
        "visiondata-gate.hybrid-retrieval-profile.v2"
    )
    algorithm: Literal["HYBRID_SPARSE_RRF_V2"] = "HYBRID_SPARSE_RRF_V2"
    tokenizer_profile: Literal["unicode_nfkc_casefold_cjk23_latin12_v1"] = (
        "unicode_nfkc_casefold_cjk23_latin12_v1"
    )
    enabled_channels: list[Literal["keyword", "bm25", "ngram", "embedding"]]
    rrf_k: int = Field(default=60, ge=1, le=1_000)
    channel_weights: dict[str, int]
    bm25_k1_milli: int = Field(default=1_200, ge=1, le=10_000)
    bm25_b_milli: int = Field(default=750, ge=0, le=1_000)
    score_scale: int = Field(default=1_000_000, ge=1_000, le=1_000_000_000)
    embedding_policy: Literal["disabled", "optional", "required"] = "disabled"
    profile_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")

    @model_validator(mode="after")
    def validate_profile_contract(self) -> HybridRetrievalProfileV2:
        if len(self.enabled_channels) != len(set(self.enabled_channels)):
            raise ValueError("hybrid retrieval channels must be unique")
        if not {"keyword", "bm25", "ngram"}.issubset(self.enabled_channels):
            raise ValueError("hybrid retrieval requires all frozen sparse channels")
        if self.embedding_policy == "disabled" and "embedding" in self.enabled_channels:
            raise ValueError("disabled embedding cannot be an enabled channel")
        if (
            self.embedding_policy != "disabled"
            and "embedding" not in self.enabled_channels
        ):
            raise ValueError("enabled embedding policy requires the embedding channel")
        if set(self.channel_weights) != set(self.enabled_channels):
            raise ValueError("hybrid retrieval weights must match enabled channels")
        if any(weight < 1 for weight in self.channel_weights.values()):
            raise ValueError("hybrid retrieval weights must be positive")
        return self


class EmbeddingIdentity(ProductModel):
    provider: Literal["local"] = "local"
    model_id: str = Field(min_length=1, max_length=240)
    model_files_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    tokenizer_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    dimension: int = Field(ge=1, le=65_536)
    normalization: Literal["l2"] = "l2"
    deterministic: Literal[True] = True


class LocalEmbeddingAdapter(Protocol):
    """Explicit local-only adapter; implementations must not perform network I/O."""

    @property
    def identity(self) -> EmbeddingIdentity: ...

    def embed(self, texts: Sequence[str]) -> Sequence[Sequence[float]]: ...


class RetrievalChannelMatchV2(ProductModel):
    rank: int = Field(ge=1)
    memory_id: str
    memory_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    score_micro: int = Field(ge=1)
    match_basis_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")


class RetrievalChannelReceiptV2(ProductModel):
    channel: Literal["keyword", "bm25", "ngram", "embedding"]
    status: Literal["EXECUTED", "DISABLED", "UNAVAILABLE_FALLBACK"]
    config_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    query_representation_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    eligible_corpus_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    ranked: list[RetrievalChannelMatchV2]
    warning_code: str | None = Field(default=None, max_length=160)


class HybridMemorySelectionV2(ProductModel):
    rank: int = Field(ge=1)
    fusion_rank: int = Field(ge=1)
    memory_id: str
    memory_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    lexical_score: int = Field(ge=0)
    semantic_score: int | None = Field(default=None, ge=0)
    channel_ranks: dict[str, int | None]
    rrf_numerator: int = Field(ge=1)
    rrf_denominator: int = Field(ge=1)
    scope_specificity: int = Field(ge=0, le=5)
    memory_version: int = Field(ge=1)
    selection_reasons: list[str] = Field(min_length=1)
    source_case_ids: list[str]
    accepted: Literal["historical_reference_only"] = "historical_reference_only"
    historical_reference_only: Literal[True] = True
    may_set_current_case_fact: Literal[False] = False


class LegacyHybridMemoryRetrievalReceiptV2(ProductModel):
    """Frozen single-clock hybrid receipt produced before dual-clock governance.

    ``as_of`` was hashed through ``query_sha256`` in this version, but the
    receipt did not preserve an independently attributable processing clock.
    It therefore remains verifiable for integrity while its authorization time
    is explicitly not provable.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_version: Literal["visiondata-gate.memory-retrieval-receipt.v2"] = (
        "visiondata-gate.memory-retrieval-receipt.v2"
    )
    query_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    query_scope: MemoryScope
    current_case_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    memory_store_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    scope_filter_digest: str = Field(pattern=r"^[0-9a-f]{64}$")
    eligible_corpus_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    retrieval_profile_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    memory_admission_store_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    memory_admission_status: Literal[
        "STRICT_PROMOTION_CHAIN_VERIFIED",
        "LEGACY_CARD_EXPLICITLY_ALLOWED",
        "DIRECT_CALL_NOT_ADMISSION_VERIFIED",
    ]
    retrieval_backend_identity: Literal[
        "visiondata-gate.governed-hybrid-sparse-rrf.v2"
    ] = "visiondata-gate.governed-hybrid-sparse-rrf.v2"
    embedding_model_identity: str = Field(min_length=1, max_length=240)
    semantic_status: Literal["NOT_CONFIGURED", "USED", "FAILED_FALLBACK"] = (
        "NOT_CONFIGURED"
    )
    fallback: Literal["NONE", "DETERMINISTIC_LEXICAL"] = "DETERMINISTIC_LEXICAL"
    candidate_count: int = Field(ge=0)
    eligible_count: int = Field(ge=0)
    selected_count: int = Field(ge=0)
    rejected_count: int = Field(ge=0)
    channel_receipts: list[RetrievalChannelReceiptV2]
    selected: list[HybridMemorySelectionV2]
    rejected: list[MemoryRejection]
    accepted_usage: Literal["historical_reference_only"] = "historical_reference_only"
    may_set_current_case_fact: Literal[False] = False
    policy_judge_input: Literal[False] = False
    raw_query_retained: Literal[False] = False
    cross_site_memory_selected_count: Literal[0] = 0
    stale_memory_selected_count: Literal[0] = 0
    historical_memory_used_as_fact_count: Literal[0] = 0
    selection_algorithm: Literal["HYBRID_SPARSE_RRF_V2"] = "HYBRID_SPARSE_RRF_V2"
    canonicalization_profile: Literal["visiondata-gate-canonical-json-v1"] = (
        "visiondata-gate-canonical-json-v1"
    )
    hash_domain: Literal["visiondata-gate/industrial-memory-retrieval/audit/v2"] = (
        "visiondata-gate/industrial-memory-retrieval/audit/v2"
    )
    receipt_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")


HybridMemoryRetrievalReceiptV2 = LegacyHybridMemoryRetrievalReceiptV2


class HybridMemoryRetrievalReceiptV3(ProductModel):
    """Dual-clock hybrid receipt bound to an attributable processing event."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_version: Literal["visiondata-gate.memory-retrieval-receipt.v3"] = (
        "visiondata-gate.memory-retrieval-receipt.v3"
    )
    query_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    query_scope: MemoryScope
    current_case_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    event_time: datetime
    processing_time: datetime
    processing_time_source: MemoryProcessingTimeSource
    authorization_clock: Literal["PROCESSING_TIME"] = "PROCESSING_TIME"
    memory_store_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    scope_filter_digest: str = Field(pattern=r"^[0-9a-f]{64}$")
    eligible_corpus_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    retrieval_profile_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    memory_admission_store_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    memory_admission_status: Literal[
        "STRICT_PROMOTION_CHAIN_VERIFIED",
        "LEGACY_CARD_EXPLICITLY_ALLOWED",
        "DIRECT_CALL_NOT_ADMISSION_VERIFIED",
    ]
    retrieval_backend_identity: Literal[
        "visiondata-gate.governed-hybrid-sparse-rrf.v2"
    ] = "visiondata-gate.governed-hybrid-sparse-rrf.v2"
    embedding_model_identity: str = Field(min_length=1, max_length=240)
    semantic_status: Literal["NOT_CONFIGURED", "USED", "FAILED_FALLBACK"] = (
        "NOT_CONFIGURED"
    )
    fallback: Literal["NONE", "DETERMINISTIC_LEXICAL"] = "DETERMINISTIC_LEXICAL"
    candidate_count: int = Field(ge=0)
    eligible_count: int = Field(ge=0)
    selected_count: int = Field(ge=0)
    rejected_count: int = Field(ge=0)
    channel_receipts: list[RetrievalChannelReceiptV2]
    selected: list[HybridMemorySelectionV2]
    rejected: list[MemoryRejection]
    accepted_usage: Literal["historical_reference_only"] = "historical_reference_only"
    may_set_current_case_fact: Literal[False] = False
    policy_judge_input: Literal[False] = False
    raw_query_retained: Literal[False] = False
    cross_site_memory_selected_count: Literal[0] = 0
    stale_memory_selected_count: Literal[0] = 0
    historical_memory_used_as_fact_count: Literal[0] = 0
    selection_algorithm: Literal["HYBRID_SPARSE_RRF_V2"] = "HYBRID_SPARSE_RRF_V2"
    canonicalization_profile: Literal["visiondata-gate-canonical-json-v1"] = (
        "visiondata-gate-canonical-json-v1"
    )
    hash_domain: Literal["visiondata-gate/industrial-memory-retrieval/audit/v3"] = (
        "visiondata-gate/industrial-memory-retrieval/audit/v3"
    )
    receipt_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")

    @field_validator("event_time", "processing_time")
    @classmethod
    def validate_receipt_clock(cls, value: datetime) -> datetime:
        return _aware(value)

    @model_validator(mode="after")
    def validate_receipt_clock_order(self) -> HybridMemoryRetrievalReceiptV3:
        if self.processing_time < self.event_time:
            raise ValueError("memory processing_time must not precede event_time")
        return self


MemoryRetrievalReceiptAny = Annotated[
    LegacyMemoryRetrievalReceiptV1
    | LegacyHybridMemoryRetrievalReceiptV2
    | HybridMemoryRetrievalReceiptV3,
    Field(discriminator="schema_version"),
]
_MEMORY_RETRIEVAL_RECEIPT_ADAPTER = TypeAdapter(MemoryRetrievalReceiptAny)


class MemoryRetrievalVerificationResult(ProductModel):
    schema_version: Literal["visiondata-gate.memory-retrieval-verification.v1"] = (
        "visiondata-gate.memory-retrieval-verification.v1"
    )
    receipt_schema_version: Literal[
        "visiondata-gate.memory-retrieval-receipt.v1",
        "visiondata-gate.memory-retrieval-receipt.v2",
        "visiondata-gate.memory-retrieval-receipt.v3",
    ]
    integrity: Literal["VERIFIED"] = "VERIFIED"
    dual_clock_authorization: Literal["NOT_PROVABLE", "PROVABLE"]
    source_structure_verified: bool
    processing_time_source_verified: bool
    source_binding_evidence: Literal[
        "NOT_AVAILABLE",
        "RECEIPT_STRUCTURE_ONLY",
        "COMMAND_ADMISSION_VERIFIED",
    ]


class ContextHypothesis(ProductModel):
    hypothesis_id: str
    category: str
    status: str
    unresolved_evidence_refs: list[str]


class HistoricalMemoryReference(ProductModel):
    memory_id: str
    memory_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    memory_type: str
    pattern: str
    recommended_first_check: str
    avoid_first_action: str | None = None
    source_case_ids: list[str]
    historical_reference_only: Literal[True] = True
    may_set_current_case_fact: Literal[False] = False
    current_case_fact_eligible: Literal[False] = False


class GovernedMemoryPlanningInput(ProductModel):
    """Pre-planning view of approved history with no decision authority.

    The full retrieval receipt remains attached for audit, while only accepted
    historical references are exposed to the optional model Planner.  This
    object is built before an immutable Case exists, so ``planning_subject_sha256``
    binds the request, Gate context, and resume lineage instead of claiming to
    be the final Case digest.
    """

    schema_version: Literal["visiondata-gate.governed-memory-planning-input.v1"] = (
        "visiondata-gate.governed-memory-planning-input.v1"
    )
    planning_subject_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    query_scope: MemoryScope
    accepted_historical_references: list[HistoricalMemoryReference]
    retrieval_receipt: MemoryRetrievalReceiptAny
    allowed_effects: list[
        Literal[
            "MISSING_EVIDENCE_PRIORITIZATION",
            "COUNTEREVIDENCE_QUESTION",
            "ALLOWLISTED_WORKER_PRIORITY",
        ]
    ] = Field(min_length=3, max_length=3)
    current_case_fact_authority: Literal["none"] = "none"
    root_cause_authority: Literal["none"] = "none"
    decision_authority: Literal["none"] = "none"
    policy_judge_input: Literal[False] = False
    machine_action_permitted: Literal[False] = False
    input_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")

    @model_validator(mode="after")
    def validate_fixed_effect_boundary(self) -> GovernedMemoryPlanningInput:
        expected = [
            "MISSING_EVIDENCE_PRIORITIZATION",
            "COUNTEREVIDENCE_QUESTION",
            "ALLOWLISTED_WORKER_PRIORITY",
        ]
        if self.allowed_effects != expected:
            raise ValueError("governed memory planning effects must remain frozen")
        return self


class IncidentAdvisorContext(ProductModel):
    schema_version: Literal["visiondata-gate.incident-advisor-context.v1"] = (
        "visiondata-gate.incident-advisor-context.v1"
    )
    case_id: str = Field(pattern=r"^incident_[0-9a-f]{20}$")
    case_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    site_id: str
    site_pack_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    current_case_facts: list[str] = Field(min_length=1)
    current_hypotheses: list[ContextHypothesis] = Field(min_length=6)
    current_evidence_gaps: list[str]
    site_profile: dict[str, str | list[str]]
    relevant_approved_memories: list[HistoricalMemoryReference]
    available_tools: list[str]
    remaining_worker_budget: int = Field(ge=0, le=12)
    frozen_prohibitions: list[str] = Field(min_length=5)
    precedence: list[
        Literal[
            "FROZEN_POLICY",
            "CURRENT_VERIFIED_EVIDENCE",
            "CURRENT_SITE_PROFILE",
            "APPROVED_HISTORICAL_EXPERIENCE",
            "MODEL_SUGGESTION",
        ]
    ] = Field(min_length=5, max_length=5)
    historical_memory_used_as_current_fact: Literal[False] = False
    context_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")


class ContextReceipt(ProductModel):
    schema_version: Literal["visiondata-gate.context-receipt.v1"] = (
        "visiondata-gate.context-receipt.v1"
    )
    case_id: str
    case_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    site_id: str
    site_pack_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    context_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    memory_retrieval_receipt_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    governed_memory_planning_input_sha256: str | None = Field(
        default=None,
        pattern=r"^[0-9a-f]{64}$",
    )
    selected_memory_ids: list[str]
    cross_site_memory_leakage_count: Literal[0] = 0
    stale_memory_acceptance_count: Literal[0] = 0
    historical_memory_used_as_fact_count: Literal[0] = 0
    may_set_current_case_fact: Literal[False] = False
    raw_prompt_retained: Literal[False] = False
    raw_image_retained: Literal[False] = False
    receipt_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")


class AssembledIncidentContext(ProductModel):
    context: IncidentAdvisorContext
    receipt: ContextReceipt
    retrieval_receipt: MemoryRetrievalReceiptAny
    planning_input: GovernedMemoryPlanningInput | None = None


def build_approved_memory_card(
    *,
    memory_type: Literal[
        "INVESTIGATION_HINT",
        "QUESTION_TEMPLATE",
        "OUTPUT_TEMPLATE",
        "FIELD_ALIAS",
        "WORKER_PRIORITY_HINT",
    ],
    scope: MemoryScope,
    content: ApprovedMemoryContent,
    source_case_ids: list[str],
    approval_sha256: str,
    valid_from: datetime,
    valid_until: datetime | None = None,
    status: Literal["APPROVED", "REVOKED"] = "APPROVED",
    memory_version: int = 1,
) -> ApprovedMemoryCard:
    identity = _sha256(
        {
            "memory_type": memory_type,
            "scope": _memory_scope_hash_payload(scope),
            "content": content,
            "source_case_ids": source_case_ids,
            "approval_sha256": approval_sha256,
            "memory_version": memory_version,
        }
    )
    stable = {
        "schema_version": "visiondata-gate.approved-memory-card.v1",
        "memory_id": f"memory_{identity[:20]}",
        "memory_type": memory_type,
        "memory_version": memory_version,
        "scope": scope,
        "content": content,
        "source_case_ids": source_case_ids,
        "approval_sha256": approval_sha256,
        "valid_from": _aware(valid_from),
        "valid_until": _aware(valid_until) if valid_until is not None else None,
        "status": status,
        "historical_reference_only": True,
        "may_set_current_case_fact": False,
        "policy_judge_input": False,
        "machine_action_permitted": False,
    }
    draft = ApprovedMemoryCard(**stable, memory_sha256="0" * 64)
    normalized = draft.model_dump(mode="json")
    normalized.pop("memory_sha256")
    normalized["scope"] = _memory_scope_hash_payload(normalized["scope"])
    return draft.model_copy(update={"memory_sha256": _sha256(normalized)})


def verify_approved_memory_card(card: ApprovedMemoryCard) -> None:
    payload = card.model_dump(mode="json")
    stored = payload.pop("memory_sha256")
    payload["scope"] = _memory_scope_hash_payload(payload["scope"])
    if not hmac.compare_digest(stored, _sha256(payload)):
        raise ValueError("approved memory card failed SHA-256 validation")


def load_approved_memory_store(path: str | Path) -> list[ApprovedMemoryCard]:
    source = Path(path).expanduser().resolve(strict=True)
    cards: list[ApprovedMemoryCard] = []
    for line_number, raw_line in enumerate(
        source.read_text(encoding="utf-8").splitlines(),
        start=1,
    ):
        if not raw_line.strip():
            continue
        try:
            payload = json.loads(raw_line)
            card = ApprovedMemoryCard.model_validate(payload)
            verify_approved_memory_card(card)
        except (json.JSONDecodeError, ValueError) as error:
            raise ValueError(
                f"approved memory store failed at line {line_number}"
            ) from error
        cards.append(card)
    ids = [card.memory_id for card in cards]
    if len(ids) != len(set(ids)):
        raise ValueError("approved memory store contains duplicate memory IDs")
    return cards


MemoryQueryAny = LegacyMemoryQueryV1 | LegacyHybridMemoryQueryV2 | ClockedMemoryQueryV3


def _query_event_time(query: MemoryQueryAny) -> datetime:
    return query.event_time if isinstance(query, ClockedMemoryQueryV3) else query.as_of


def _query_authorization_time(query: MemoryQueryAny) -> datetime:
    # Historical v1/v2 schemas retained only one clock.  Replaying them uses
    # that clock for the original selection semantics, but verification reports
    # the dual-clock authorization claim as NOT_PROVABLE.
    return (
        query.processing_time
        if isinstance(query, ClockedMemoryQueryV3)
        else query.as_of
    )


def _scope_rejection(card: ApprovedMemoryCard, query: MemoryQueryAny) -> str | None:
    if card.scope.site_id != query.site_id:
        return "CROSS_SITE_SCOPE"
    scoped_fields = [
        ("product_family", "PRODUCT_SCOPE_MISMATCH"),
        ("line_id", "LINE_SCOPE_MISMATCH"),
        ("camera_id", "CAMERA_SCOPE_MISMATCH"),
    ]
    if not isinstance(query, LegacyMemoryQueryV1):
        scoped_fields.insert(2, ("station_id", "STATION_SCOPE_MISMATCH"))
    for field, reason in scoped_fields:
        required = getattr(card.scope, field)
        observed = getattr(query, field, None)
        if required is not None and required != observed:
            return reason
    if card.status == "REVOKED":
        return "REVOKED"
    authorization_time = _query_authorization_time(query)
    if authorization_time < card.valid_from:
        return "NOT_YET_VALID"
    if card.valid_until is not None and authorization_time >= card.valid_until:
        return "EXPIRED"
    return None


_MEMORY_V2_HASH_DOMAIN = "visiondata-gate/industrial-memory-retrieval/audit/v2"
_MEMORY_V3_HASH_DOMAIN = "visiondata-gate/industrial-memory-retrieval/audit/v3"
_HARD_REJECTION_CODES = {
    "CROSS_SITE_SCOPE",
    "PRODUCT_SCOPE_MISMATCH",
    "LINE_SCOPE_MISMATCH",
    "STATION_SCOPE_MISMATCH",
    "CAMERA_SCOPE_MISMATCH",
    "NOT_YET_VALID",
    "EXPIRED",
    "REVOKED",
}


def _memory_v2_sha256(value: object) -> str:
    material = (
        _MEMORY_V2_HASH_DOMAIN.encode("utf-8")
        + b"\x00"
        + canonical_json_bytes(
            value,
            trailing_newline=False,
        )
    )
    return hashlib.sha256(material).hexdigest()


def _memory_v3_sha256(value: object) -> str:
    material = (
        _MEMORY_V3_HASH_DOMAIN.encode("utf-8")
        + b"\x00"
        + canonical_json_bytes(
            value,
            trailing_newline=False,
        )
    )
    return hashlib.sha256(material).hexdigest()


def build_hybrid_retrieval_profile_v2(
    *,
    embedding_policy: Literal["disabled", "optional", "required"] = "disabled",
) -> HybridRetrievalProfileV2:
    enabled_channels: list[str] = ["keyword", "bm25", "ngram"]
    weights = {"keyword": 2, "bm25": 4, "ngram": 3}
    if embedding_policy != "disabled":
        enabled_channels.append("embedding")
        weights["embedding"] = 4
    stable = {
        "schema_version": "visiondata-gate.hybrid-retrieval-profile.v2",
        "algorithm": "HYBRID_SPARSE_RRF_V2",
        "tokenizer_profile": "unicode_nfkc_casefold_cjk23_latin12_v1",
        "enabled_channels": enabled_channels,
        "rrf_k": 60,
        "channel_weights": weights,
        "bm25_k1_milli": 1_200,
        "bm25_b_milli": 750,
        "score_scale": 1_000_000,
        "embedding_policy": embedding_policy,
    }
    return HybridRetrievalProfileV2(
        **stable,
        profile_sha256=_memory_v2_sha256(stable),
    )


DEFAULT_HYBRID_RETRIEVAL_PROFILE_V2 = build_hybrid_retrieval_profile_v2()


def verify_hybrid_retrieval_profile_v2(profile: HybridRetrievalProfileV2) -> None:
    payload = profile.model_dump(mode="json")
    stored = payload.pop("profile_sha256")
    if not hmac.compare_digest(stored, _memory_v2_sha256(payload)):
        raise ValueError("hybrid retrieval profile failed SHA-256 validation")


def _normalized_retrieval_text(value: str) -> str:
    return unicodedata.normalize("NFKC", value).casefold()


def _v2_word_tokens(value: str) -> list[str]:
    normalized = _normalized_retrieval_text(value)
    tokens = re.findall(r"[a-z0-9_.-]+", normalized)
    for chunk in re.findall(r"[\u4e00-\u9fff]+", normalized):
        if len(chunk) == 1:
            tokens.append(chunk)
        else:
            tokens.extend(chunk[index : index + 2] for index in range(len(chunk) - 1))
    return tokens


def _v2_ngram_tokens(value: str) -> set[str]:
    normalized = _normalized_retrieval_text(value)
    latin = re.findall(r"[a-z0-9_.-]+", normalized)
    tokens = {f"latin1:{token}" for token in latin}
    tokens.update(
        f"latin2:{latin[index]}::{latin[index + 1]}" for index in range(len(latin) - 1)
    )
    for chunk in re.findall(r"[\u4e00-\u9fff]+", normalized):
        for width in (2, 3):
            tokens.update(
                f"cjk{width}:{chunk[index : index + width]}"
                for index in range(max(0, len(chunk) - width + 1))
            )
        if len(chunk) == 1:
            tokens.add(f"cjk1:{chunk}")
    return tokens


def _card_retrieval_text(card: ApprovedMemoryCard) -> str:
    return " ".join(
        [
            card.memory_type,
            card.content.pattern,
            card.content.pattern,
            card.content.recommended_first_check,
            card.content.recommended_first_check,
            card.content.avoid_first_action or "",
            card.content.advisory_summary,
        ]
    )


def _scope_specificity(card: ApprovedMemoryCard) -> int:
    return sum(
        value is not None
        for value in (
            card.scope.product_family,
            card.scope.line_id,
            card.scope.station_id,
            card.scope.camera_id,
        )
    )


def _rank_positive_scores(
    cards: Sequence[ApprovedMemoryCard],
    scores: dict[str, int],
) -> list[tuple[int, ApprovedMemoryCard]]:
    ranked = [
        (scores.get(card.memory_id, 0), card)
        for card in cards
        if scores.get(card.memory_id, 0) > 0
    ]
    ranked.sort(
        key=lambda item: (
            -item[0],
            -item[1].memory_version,
            item[1].memory_sha256,
        )
    )
    return ranked


def _bm25_scores_micro(
    cards: Sequence[ApprovedMemoryCard],
    *,
    query_text: str,
    profile: HybridRetrievalProfileV2,
) -> tuple[dict[str, int], dict[str, list[str]]]:
    documents = {
        card.memory_id: _v2_word_tokens(_card_retrieval_text(card)) for card in cards
    }
    query_terms = set(_v2_word_tokens(query_text))
    if not cards or not query_terms:
        return {card.memory_id: 0 for card in cards}, documents
    document_frequency = {
        term: sum(term in set(tokens) for tokens in documents.values())
        for term in query_terms
    }
    with localcontext() as context:
        context.prec = 50
        count = Decimal(len(cards))
        average_length = (
            sum(Decimal(len(tokens)) for tokens in documents.values()) / count
        )
        k1 = Decimal(profile.bm25_k1_milli) / Decimal(1_000)
        b = Decimal(profile.bm25_b_milli) / Decimal(1_000)
        scale = Decimal(profile.score_scale)
        scores: dict[str, int] = {}
        for card in cards:
            tokens = documents[card.memory_id]
            frequencies = Counter(tokens)
            length = Decimal(len(tokens))
            score = Decimal(0)
            for term in query_terms:
                frequency = frequencies.get(term, 0)
                if frequency == 0:
                    continue
                df = Decimal(document_frequency[term])
                idf = (
                    Decimal(1) + (count - df + Decimal("0.5")) / (df + Decimal("0.5"))
                ).ln()
                tf = Decimal(frequency)
                denominator = tf + k1 * (Decimal(1) - b + b * length / average_length)
                score += idf * (tf * (k1 + Decimal(1))) / denominator
            scores[card.memory_id] = int(
                (score * scale).to_integral_value(rounding=ROUND_HALF_EVEN)
            )
    return scores, documents


def _cosine_score_micro(
    left: Sequence[float],
    right: Sequence[float],
    *,
    scale: int,
) -> int:
    if len(left) != len(right) or not left:
        raise ValueError("embedding vectors have an invalid dimension")
    if any(not math.isfinite(value) for value in (*left, *right)):
        raise ValueError("embedding vectors contain non-finite values")
    left_norm = math.sqrt(sum(value * value for value in left))
    right_norm = math.sqrt(sum(value * value for value in right))
    if left_norm == 0 or right_norm == 0:
        return 0
    cosine = sum(a * b for a, b in zip(left, right, strict=True)) / (
        left_norm * right_norm
    )
    return max(0, int(round(cosine * scale)))


def _channel_receipt(
    *,
    channel: Literal["keyword", "bm25", "ngram", "embedding"],
    status: Literal["EXECUTED", "DISABLED", "UNAVAILABLE_FALLBACK"],
    profile: HybridRetrievalProfileV2,
    query_representation: object,
    eligible_corpus_sha256: str,
    ranked: Sequence[tuple[int, ApprovedMemoryCard]],
    representations: dict[str, object],
    warning_code: str | None = None,
) -> RetrievalChannelReceiptV2:
    return RetrievalChannelReceiptV2(
        channel=channel,
        status=status,
        config_sha256=_memory_v2_sha256(
            {
                "profile_sha256": profile.profile_sha256,
                "channel": channel,
                "weight": profile.channel_weights.get(channel),
            }
        ),
        query_representation_sha256=_memory_v2_sha256(query_representation),
        eligible_corpus_sha256=eligible_corpus_sha256,
        ranked=[
            RetrievalChannelMatchV2(
                rank=rank,
                memory_id=card.memory_id,
                memory_sha256=card.memory_sha256,
                score_micro=score,
                match_basis_sha256=_memory_v2_sha256(
                    representations.get(card.memory_id, card.memory_sha256)
                ),
            )
            for rank, (score, card) in enumerate(ranked, start=1)
        ],
        warning_code=warning_code,
    )


def _retrieve_approved_memories_hybrid(
    cards: Sequence[ApprovedMemoryCard],
    query: LegacyHybridMemoryQueryV2 | ClockedMemoryQueryV3,
    *,
    receipt_version: Literal[2, 3],
    profile: HybridRetrievalProfileV2 = DEFAULT_HYBRID_RETRIEVAL_PROFILE_V2,
    embedding_adapter: LocalEmbeddingAdapter | None = None,
    memory_admission_status: Literal[
        "STRICT_PROMOTION_CHAIN_VERIFIED",
        "LEGACY_CARD_EXPLICITLY_ALLOWED",
        "DIRECT_CALL_NOT_ADMISSION_VERIFIED",
    ] = "DIRECT_CALL_NOT_ADMISSION_VERIFIED",
    memory_admission_store_sha256: str | None = None,
) -> tuple[
    list[ApprovedMemoryCard],
    LegacyHybridMemoryRetrievalReceiptV2 | HybridMemoryRetrievalReceiptV3,
]:
    """Retrieve approved memory through hard gates and auditable hybrid ranking."""

    if receipt_version == 2 and not isinstance(query, LegacyHybridMemoryQueryV2):
        raise TypeError("hybrid v2 retrieval requires LegacyHybridMemoryQueryV2")
    if receipt_version == 3 and not isinstance(query, ClockedMemoryQueryV3):
        raise TypeError("hybrid v3 retrieval requires ClockedMemoryQueryV3")
    receipt_hasher = _memory_v2_sha256 if receipt_version == 2 else _memory_v3_sha256
    verify_hybrid_retrieval_profile_v2(profile)
    for card in cards:
        verify_approved_memory_card(card)
    rejected: list[MemoryRejection] = []
    eligible: list[ApprovedMemoryCard] = []
    scope_decisions: list[dict[str, str]] = []
    for card in cards:
        reason = _scope_rejection(card, query)
        scope_decisions.append(
            {
                "memory_id": card.memory_id,
                "memory_sha256": card.memory_sha256,
                "decision": reason or "ELIGIBLE",
            }
        )
        if reason is None:
            eligible.append(card)
        else:
            rejected.append(
                MemoryRejection(
                    memory_id=card.memory_id,
                    memory_sha256=card.memory_sha256,
                    reason_code=reason,
                )
            )

    query_text = " ".join(query.terms)
    card_text = {card.memory_id: _card_retrieval_text(card) for card in eligible}
    eligible_corpus_sha256 = receipt_hasher(
        [
            {
                "memory_id": card.memory_id,
                "memory_sha256": card.memory_sha256,
                "text_sha256": receipt_hasher(card_text[card.memory_id]),
            }
            for card in eligible
        ]
    )

    query_keywords = sorted(set(_v2_word_tokens(query_text)))
    keyword_representations = {
        card.memory_id: sorted(set(_v2_word_tokens(card_text[card.memory_id])))
        for card in eligible
    }
    keyword_scores = {
        card.memory_id: len(
            set(query_keywords) & set(keyword_representations[card.memory_id])
        )
        * profile.score_scale
        for card in eligible
    }
    keyword_ranked = _rank_positive_scores(eligible, keyword_scores)

    bm25_scores, bm25_representations = _bm25_scores_micro(
        eligible,
        query_text=query_text,
        profile=profile,
    )
    bm25_ranked = _rank_positive_scores(eligible, bm25_scores)

    query_ngrams = sorted(_v2_ngram_tokens(query_text))
    ngram_representations = {
        card.memory_id: sorted(_v2_ngram_tokens(card_text[card.memory_id]))
        for card in eligible
    }
    ngram_scores: dict[str, int] = {}
    query_ngram_set = set(query_ngrams)
    for card in eligible:
        observed = set(ngram_representations[card.memory_id])
        union = query_ngram_set | observed
        overlap = query_ngram_set & observed
        ngram_scores[card.memory_id] = (
            len(overlap) * profile.score_scale // len(union) if union else 0
        )
    ngram_ranked = _rank_positive_scores(eligible, ngram_scores)

    semantic_status: Literal["NOT_CONFIGURED", "USED", "FAILED_FALLBACK"] = (
        "NOT_CONFIGURED"
    )
    fallback: Literal["NONE", "DETERMINISTIC_LEXICAL"] = "DETERMINISTIC_LEXICAL"
    embedding_model_identity = "none"
    embedding_scores = {card.memory_id: 0 for card in eligible}
    embedding_representations: dict[str, object] = {
        card.memory_id: card.memory_sha256 for card in eligible
    }
    embedding_ranked: list[tuple[int, ApprovedMemoryCard]] = []
    embedding_status: Literal["EXECUTED", "DISABLED", "UNAVAILABLE_FALLBACK"] = (
        "DISABLED"
    )
    embedding_warning: str | None = None
    if profile.embedding_policy != "disabled":
        if embedding_adapter is None:
            if profile.embedding_policy == "required":
                raise ValueError("required local embedding adapter is not configured")
            embedding_status = "UNAVAILABLE_FALLBACK"
            embedding_warning = "EMBEDDING_NOT_CONFIGURED"
        else:
            try:
                identity = embedding_adapter.identity
                if identity.provider != "local" or not identity.deterministic:
                    raise ValueError(
                        "embedding adapter must be local and deterministic"
                    )
                vectors = list(
                    embedding_adapter.embed(
                        [query_text, *(card_text[card.memory_id] for card in eligible)]
                    )
                )
                if len(vectors) != len(eligible) + 1:
                    raise ValueError("embedding adapter returned an invalid batch size")
                if any(len(vector) != identity.dimension for vector in vectors):
                    raise ValueError("embedding adapter returned an invalid dimension")
                query_vector = vectors[0]
                embedding_representations = {
                    card.memory_id: [round(value, 12) for value in vector]
                    for card, vector in zip(eligible, vectors[1:], strict=True)
                }
                embedding_scores = {
                    card.memory_id: _cosine_score_micro(
                        query_vector,
                        vector,
                        scale=profile.score_scale,
                    )
                    for card, vector in zip(eligible, vectors[1:], strict=True)
                }
                embedding_ranked = _rank_positive_scores(eligible, embedding_scores)
                embedding_status = "EXECUTED"
                semantic_status = "USED"
                fallback = "NONE"
                embedding_model_identity = (
                    f"{identity.model_id}@{identity.model_files_sha256[:12]}"
                    f"/{identity.tokenizer_sha256[:12]}"
                )
            except Exception as error:
                if profile.embedding_policy == "required":
                    raise ValueError(
                        "required local embedding retrieval failed"
                    ) from error
                embedding_status = "UNAVAILABLE_FALLBACK"
                embedding_warning = f"EMBEDDING_FAILED:{type(error).__name__}"
                semantic_status = "FAILED_FALLBACK"

    channels = [
        _channel_receipt(
            channel="keyword",
            status="EXECUTED",
            profile=profile,
            query_representation=query_keywords,
            eligible_corpus_sha256=eligible_corpus_sha256,
            ranked=keyword_ranked,
            representations=keyword_representations,
        ),
        _channel_receipt(
            channel="bm25",
            status="EXECUTED",
            profile=profile,
            query_representation=_v2_word_tokens(query_text),
            eligible_corpus_sha256=eligible_corpus_sha256,
            ranked=bm25_ranked,
            representations=bm25_representations,
        ),
        _channel_receipt(
            channel="ngram",
            status="EXECUTED",
            profile=profile,
            query_representation=query_ngrams,
            eligible_corpus_sha256=eligible_corpus_sha256,
            ranked=ngram_ranked,
            representations=ngram_representations,
        ),
        _channel_receipt(
            channel="embedding",
            status=embedding_status,
            profile=profile,
            query_representation=(
                {"query_sha256": _memory_v2_sha256(query_text)}
                if embedding_status == "EXECUTED"
                else {"status": embedding_status}
            ),
            eligible_corpus_sha256=eligible_corpus_sha256,
            ranked=embedding_ranked,
            representations=embedding_representations,
            warning_code=embedding_warning,
        ),
    ]

    rank_maps = {
        receipt.channel: {item.memory_id: item.rank for item in receipt.ranked}
        for receipt in channels
        if receipt.status == "EXECUTED"
    }
    fusion: list[tuple[Fraction, ApprovedMemoryCard, dict[str, int | None]]] = []
    for card in eligible:
        ranks = {
            channel: rank_maps.get(channel, {}).get(card.memory_id)
            for channel in ("keyword", "bm25", "ngram", "embedding")
        }
        score = sum(
            (
                Fraction(profile.channel_weights[channel], profile.rrf_k + rank)
                for channel, rank in ranks.items()
                if rank is not None and channel in profile.channel_weights
            ),
            Fraction(0, 1),
        )
        if score == 0:
            rejected.append(
                MemoryRejection(
                    memory_id=card.memory_id,
                    memory_sha256=card.memory_sha256,
                    reason_code="NO_QUERY_RELEVANCE",
                )
            )
            continue
        fusion.append((score, card, ranks))
    fusion.sort(
        key=lambda item: (
            -item[0],
            -_scope_specificity(item[1]),
            -item[1].memory_version,
            item[1].memory_sha256,
        )
    )
    chosen = fusion[: query.limit]
    for _score, card, _ranks in fusion[query.limit :]:
        rejected.append(
            MemoryRejection(
                memory_id=card.memory_id,
                memory_sha256=card.memory_sha256,
                reason_code="RANK_LIMIT_EXCEEDED",
            )
        )
    selected_cards = [item[1] for item in chosen]
    selections = [
        HybridMemorySelectionV2(
            rank=rank,
            fusion_rank=rank,
            memory_id=card.memory_id,
            memory_sha256=card.memory_sha256,
            lexical_score=(
                keyword_scores.get(card.memory_id, 0)
                + bm25_scores.get(card.memory_id, 0)
                + ngram_scores.get(card.memory_id, 0)
            ),
            semantic_score=(
                embedding_scores.get(card.memory_id, 0)
                if semantic_status == "USED"
                else None
            ),
            channel_ranks=ranks,
            rrf_numerator=score.numerator,
            rrf_denominator=score.denominator,
            scope_specificity=_scope_specificity(card),
            memory_version=card.memory_version,
            selection_reasons=[
                (
                    "SCOPE_PROCESSING_TIME_AUTHORIZATION_FRESHNESS_PASSED"
                    if receipt_version == 3
                    else "SCOPE_SINGLE_CLOCK_AUTHORIZATION_FRESHNESS_PASSED"
                ),
                *[
                    f"{channel.upper()}_RANK:{channel_rank}"
                    for channel, channel_rank in ranks.items()
                    if channel_rank is not None
                ],
            ],
            source_case_ids=card.source_case_ids,
        )
        for rank, (score, card, ranks) in enumerate(chosen, start=1)
    ]

    stable: dict[str, object] = {
        "schema_version": (
            "visiondata-gate.memory-retrieval-receipt.v2"
            if receipt_version == 2
            else "visiondata-gate.memory-retrieval-receipt.v3"
        ),
        "query_sha256": receipt_hasher(query),
        "query_scope": MemoryScope(
            site_id=query.site_id,
            product_family=query.product_family,
            line_id=query.line_id,
            station_id=query.station_id,
            camera_id=query.camera_id,
        ),
        "current_case_sha256": query.current_case_sha256,
        "memory_store_sha256": receipt_hasher([card.memory_sha256 for card in cards]),
        "scope_filter_digest": receipt_hasher(scope_decisions),
        "eligible_corpus_sha256": eligible_corpus_sha256,
        "retrieval_profile_sha256": profile.profile_sha256,
        "memory_admission_store_sha256": (
            memory_admission_store_sha256
            or receipt_hasher([card.memory_sha256 for card in cards])
        ),
        "memory_admission_status": memory_admission_status,
        "retrieval_backend_identity": ("visiondata-gate.governed-hybrid-sparse-rrf.v2"),
        "embedding_model_identity": embedding_model_identity,
        "semantic_status": semantic_status,
        "fallback": fallback,
        "candidate_count": len(cards),
        "eligible_count": len(eligible),
        "selected_count": len(selections),
        "rejected_count": len(rejected),
        "channel_receipts": channels,
        "selected": selections,
        "rejected": rejected,
        "accepted_usage": "historical_reference_only",
        "may_set_current_case_fact": False,
        "policy_judge_input": False,
        "raw_query_retained": False,
        "cross_site_memory_selected_count": 0,
        "stale_memory_selected_count": 0,
        "historical_memory_used_as_fact_count": 0,
        "selection_algorithm": "HYBRID_SPARSE_RRF_V2",
        "canonicalization_profile": "visiondata-gate-canonical-json-v1",
        "hash_domain": (
            _MEMORY_V2_HASH_DOMAIN if receipt_version == 2 else _MEMORY_V3_HASH_DOMAIN
        ),
    }
    if isinstance(query, ClockedMemoryQueryV3):
        query_payload = query.model_dump(mode="json")
        stable.update(
            {
                "event_time": query_payload["event_time"],
                "processing_time": query_payload["processing_time"],
                "processing_time_source": query.processing_time_source,
                "authorization_clock": "PROCESSING_TIME",
            }
        )
        receipt: LegacyHybridMemoryRetrievalReceiptV2 | HybridMemoryRetrievalReceiptV3
        receipt = HybridMemoryRetrievalReceiptV3(
            **stable,
            receipt_sha256=_memory_v3_sha256(stable),
        )
    else:
        receipt = LegacyHybridMemoryRetrievalReceiptV2(
            **stable,
            receipt_sha256=_memory_v2_sha256(stable),
        )
    verify_memory_retrieval_receipt(receipt)
    return selected_cards, receipt


def retrieve_approved_memories_v2(
    cards: Sequence[ApprovedMemoryCard],
    query: LegacyHybridMemoryQueryV2,
    *,
    profile: HybridRetrievalProfileV2 = DEFAULT_HYBRID_RETRIEVAL_PROFILE_V2,
    embedding_adapter: LocalEmbeddingAdapter | None = None,
    memory_admission_status: Literal[
        "STRICT_PROMOTION_CHAIN_VERIFIED",
        "LEGACY_CARD_EXPLICITLY_ALLOWED",
        "DIRECT_CALL_NOT_ADMISSION_VERIFIED",
    ] = "DIRECT_CALL_NOT_ADMISSION_VERIFIED",
    memory_admission_store_sha256: str | None = None,
) -> tuple[list[ApprovedMemoryCard], LegacyHybridMemoryRetrievalReceiptV2]:
    selected, receipt = _retrieve_approved_memories_hybrid(
        cards,
        query,
        receipt_version=2,
        profile=profile,
        embedding_adapter=embedding_adapter,
        memory_admission_status=memory_admission_status,
        memory_admission_store_sha256=memory_admission_store_sha256,
    )
    if not isinstance(receipt, LegacyHybridMemoryRetrievalReceiptV2):
        raise AssertionError("hybrid v2 retrieval returned the wrong receipt schema")
    return selected, receipt


def retrieve_approved_memories_v3(
    cards: Sequence[ApprovedMemoryCard],
    query: ClockedMemoryQueryV3,
    *,
    profile: HybridRetrievalProfileV2 = DEFAULT_HYBRID_RETRIEVAL_PROFILE_V2,
    embedding_adapter: LocalEmbeddingAdapter | None = None,
    memory_admission_status: Literal[
        "STRICT_PROMOTION_CHAIN_VERIFIED",
        "LEGACY_CARD_EXPLICITLY_ALLOWED",
        "DIRECT_CALL_NOT_ADMISSION_VERIFIED",
    ] = "DIRECT_CALL_NOT_ADMISSION_VERIFIED",
    memory_admission_store_sha256: str | None = None,
) -> tuple[list[ApprovedMemoryCard], HybridMemoryRetrievalReceiptV3]:
    selected, receipt = _retrieve_approved_memories_hybrid(
        cards,
        query,
        receipt_version=3,
        profile=profile,
        embedding_adapter=embedding_adapter,
        memory_admission_status=memory_admission_status,
        memory_admission_store_sha256=memory_admission_store_sha256,
    )
    if not isinstance(receipt, HybridMemoryRetrievalReceiptV3):
        raise AssertionError("hybrid v3 retrieval returned the wrong receipt schema")
    return selected, receipt


def retrieve_approved_memories(
    cards: list[ApprovedMemoryCard],
    query: LegacyMemoryQueryV1,
) -> tuple[list[ApprovedMemoryCard], MemoryRetrievalReceipt]:
    for card in cards:
        verify_approved_memory_card(card)
    query_tokens = _tokens(" ".join(query.terms))
    selected_candidates: list[tuple[int, ApprovedMemoryCard, list[str]]] = []
    rejected: list[LegacyMemoryRejectionV1] = []
    for card in cards:
        scope_reason = _scope_rejection(card, query)
        if scope_reason is not None:
            rejected.append(
                LegacyMemoryRejectionV1(
                    memory_id=card.memory_id,
                    memory_sha256=card.memory_sha256,
                    reason_code=scope_reason,
                )
            )
            continue
        card_text = " ".join(
            [
                card.memory_type,
                card.content.pattern,
                card.content.recommended_first_check,
                card.content.avoid_first_action or "",
                card.content.advisory_summary,
            ]
        )
        overlap = len(query_tokens & _tokens(card_text)) if query_tokens else 1
        if overlap == 0:
            rejected.append(
                LegacyMemoryRejectionV1(
                    memory_id=card.memory_id,
                    memory_sha256=card.memory_sha256,
                    reason_code="NO_QUERY_RELEVANCE",
                )
            )
            continue
        scope_specificity = sum(
            value is not None
            for value in (
                card.scope.product_family,
                card.scope.line_id,
                card.scope.camera_id,
            )
        )
        score = overlap * 10 + scope_specificity
        reasons = ["SITE_SCOPE_MATCH", "APPROVED_AND_FRESH"]
        if overlap:
            reasons.append(f"QUERY_TOKEN_OVERLAP:{overlap}")
        selected_candidates.append((score, card, reasons))
    selected_candidates.sort(
        key=lambda item: (-item[0], -item[1].memory_version, item[1].memory_sha256)
    )
    chosen = selected_candidates[: query.limit]
    selected_cards = [item[1] for item in chosen]
    selections = [
        LegacyMemorySelectionV1(
            rank=rank,
            memory_id=card.memory_id,
            memory_sha256=card.memory_sha256,
            score=score,
            selection_reasons=reasons,
            source_case_ids=card.source_case_ids,
        )
        for rank, (score, card, reasons) in enumerate(chosen, start=1)
    ]
    store_sha = _sha256([card.memory_sha256 for card in cards])
    stable = {
        "schema_version": "visiondata-gate.memory-retrieval-receipt.v1",
        "query_sha256": _sha256(query),
        "current_case_sha256": query.current_case_sha256,
        "memory_store_sha256": store_sha,
        "candidate_count": len(cards),
        "selected": selections,
        "rejected": rejected,
        "cross_site_memory_selected_count": 0,
        "stale_memory_selected_count": 0,
        "historical_memory_used_as_fact_count": 0,
        "selection_algorithm": "SCOPE_THEN_RELEVANCE_V1",
    }
    receipt = LegacyMemoryRetrievalReceiptV1(
        **stable,
        receipt_sha256=_sha256(stable),
    )
    return selected_cards, receipt


def parse_memory_retrieval_receipt(
    value: MemoryRetrievalReceiptAny | Mapping[str, object] | str | bytes,
) -> MemoryRetrievalReceiptAny:
    if isinstance(
        value,
        (
            LegacyMemoryRetrievalReceiptV1,
            LegacyHybridMemoryRetrievalReceiptV2,
            HybridMemoryRetrievalReceiptV3,
        ),
    ):
        return value
    if isinstance(value, (str, bytes)):
        return _MEMORY_RETRIEVAL_RECEIPT_ADAPTER.validate_json(value)
    return _MEMORY_RETRIEVAL_RECEIPT_ADAPTER.validate_python(value)


def verify_memory_retrieval_receipt(
    receipt: MemoryRetrievalReceiptAny,
) -> MemoryRetrievalVerificationResult:
    payload = receipt.model_dump(mode="json")
    stored = payload.pop("receipt_sha256")
    if isinstance(receipt, LegacyMemoryRetrievalReceiptV1):
        expected = _sha256(payload)
    elif isinstance(receipt, LegacyHybridMemoryRetrievalReceiptV2):
        expected = _memory_v2_sha256(payload)
    else:
        expected = _memory_v3_sha256(payload)
    if not hmac.compare_digest(stored, expected):
        raise ValueError("memory retrieval receipt failed SHA-256 validation")
    if len(receipt.selected) != len({item.memory_id for item in receipt.selected}):
        raise ValueError("memory retrieval selected duplicate memory IDs")

    if isinstance(receipt, LegacyMemoryRetrievalReceiptV1):
        return MemoryRetrievalVerificationResult(
            receipt_schema_version=receipt.schema_version,
            dual_clock_authorization="NOT_PROVABLE",
            source_structure_verified=False,
            processing_time_source_verified=False,
            source_binding_evidence="NOT_AVAILABLE",
        )

    if receipt.selected_count != len(receipt.selected):
        raise ValueError("memory retrieval selected count does not match entries")
    if receipt.rejected_count != len(receipt.rejected):
        raise ValueError("memory retrieval rejected count does not match entries")
    if receipt.candidate_count != receipt.selected_count + receipt.rejected_count:
        raise ValueError("memory retrieval receipt did not account for every candidate")
    accepted_ids = {item.memory_id for item in receipt.selected}
    rejected_ids = {item.memory_id for item in receipt.rejected}
    if len(rejected_ids) != len(receipt.rejected):
        raise ValueError("memory retrieval rejected duplicate memory IDs")
    if accepted_ids & rejected_ids:
        raise ValueError("memory retrieval candidate was both accepted and rejected")
    if [item.rank for item in receipt.selected] != list(
        range(1, receipt.selected_count + 1)
    ):
        raise ValueError("memory retrieval selected ranks are not contiguous")
    if receipt.eligible_count > receipt.candidate_count:
        raise ValueError("hybrid retrieval eligible count exceeds candidates")
    hard_rejections = [
        item for item in receipt.rejected if item.reason_code in _HARD_REJECTION_CODES
    ]
    if receipt.eligible_count != receipt.candidate_count - len(hard_rejections):
        raise ValueError("hybrid retrieval eligible count lost filter accounting")
    if [item.fusion_rank for item in receipt.selected] != list(
        range(1, receipt.selected_count + 1)
    ):
        raise ValueError("hybrid retrieval fusion ranks are not contiguous")
    hard_rejected_ids = {item.memory_id for item in hard_rejections}
    executed_channel_members: dict[str, set[str]] = {}
    for channel in receipt.channel_receipts:
        ranks = [item.rank for item in channel.ranked]
        if ranks != list(range(1, len(ranks) + 1)):
            raise ValueError("hybrid retrieval channel ranks are not contiguous")
        channel_ids = [item.memory_id for item in channel.ranked]
        if len(channel_ids) != len(set(channel_ids)):
            raise ValueError("hybrid retrieval channel selected duplicate memory IDs")
        if hard_rejected_ids & set(channel_ids):
            raise ValueError("hard-rejected memory reached a retrieval channel")
        if channel.status != "EXECUTED" and channel.ranked:
            raise ValueError("inactive retrieval channel returned ranked memories")
        if channel.status == "EXECUTED":
            for item in channel.ranked:
                executed_channel_members.setdefault(item.memory_id, set()).add(
                    item.memory_sha256
                )
    for item in receipt.selected:
        channel_digests = executed_channel_members.get(item.memory_id, set())
        if item.memory_sha256 not in channel_digests:
            raise ValueError(
                "hybrid retrieval selected memory is absent from executed channels"
            )
    if receipt.semantic_status == "USED":
        if receipt.fallback != "NONE" or receipt.embedding_model_identity == "none":
            raise ValueError("semantic retrieval identity or fallback is inconsistent")
    elif receipt.fallback != "DETERMINISTIC_LEXICAL":
        raise ValueError("semantic fallback status is inconsistent")

    if isinstance(receipt, HybridMemoryRetrievalReceiptV3):
        _aware(receipt.event_time)
        _aware(receipt.processing_time)
        if receipt.processing_time < receipt.event_time:
            raise ValueError("memory processing_time must not precede event_time")
        MemoryProcessingTimeSource.model_validate(
            receipt.processing_time_source.model_dump(mode="json")
        )
        return MemoryRetrievalVerificationResult(
            receipt_schema_version=receipt.schema_version,
            dual_clock_authorization="PROVABLE",
            source_structure_verified=True,
            processing_time_source_verified=False,
            source_binding_evidence="RECEIPT_STRUCTURE_ONLY",
        )

    return MemoryRetrievalVerificationResult(
        receipt_schema_version=receipt.schema_version,
        dual_clock_authorization="NOT_PROVABLE",
        source_structure_verified=False,
        processing_time_source_verified=False,
        source_binding_evidence="NOT_AVAILABLE",
    )


def verify_memory_retrieval_command_admission_binding(
    receipt: MemoryRetrievalReceiptAny,
    *,
    command_id: str,
    admission_sha256: str,
    admitted_at: datetime,
) -> MemoryRetrievalVerificationResult:
    """Verify the v3 clock source against an external admission receipt."""

    verification = verify_memory_retrieval_receipt(receipt)
    if not isinstance(receipt, HybridMemoryRetrievalReceiptV3):
        raise ValueError("command admission binding requires a v3 memory receipt")
    admitted_at = _aware(admitted_at)
    source = receipt.processing_time_source
    if source.source_kind != "INCIDENT_COMMAND_ADMISSION":
        raise ValueError("memory processing clock is not command-admission sourced")
    if not hmac.compare_digest(source.source_id, command_id):
        raise ValueError("memory processing clock lost command ID binding")
    if not hmac.compare_digest(source.source_sha256, admission_sha256):
        raise ValueError("memory processing clock lost admission SHA binding")
    if receipt.processing_time != admitted_at:
        raise ValueError("memory processing clock differs from admission time")
    return verification.model_copy(
        update={
            "processing_time_source_verified": True,
            "source_binding_evidence": "COMMAND_ADMISSION_VERIFIED",
        }
    )


def build_governed_memory_planning_input(
    *,
    planning_subject_sha256: str,
    site_pack: FactorySitePack,
    memory_cards: list[ApprovedMemoryCard],
    line_id: str | None,
    as_of: datetime,
    processing_time: datetime,
    processing_time_source: MemoryProcessingTimeSource,
    query_terms: list[str],
    product_family: str | None = None,
    station_id: str | None = None,
    camera_id: str | None = None,
    memory_limit: int = 4,
    retrieval_profile: HybridRetrievalProfileV2 | None = None,
    embedding_adapter: LocalEmbeddingAdapter | None = None,
    memory_admission_status: Literal[
        "STRICT_PROMOTION_CHAIN_VERIFIED",
        "LEGACY_CARD_EXPLICITLY_ALLOWED",
        "DIRECT_CALL_NOT_ADMISSION_VERIFIED",
    ] = "DIRECT_CALL_NOT_ADMISSION_VERIFIED",
    memory_admission_store_sha256: str | None = None,
) -> GovernedMemoryPlanningInput:
    """Retrieve approved history once, before Case planning begins."""

    verify_factory_site_pack(site_pack)
    query = ClockedMemoryQueryV3(
        site_id=site_pack.manifest.site_id,
        current_case_sha256=planning_subject_sha256,
        event_time=_aware(as_of),
        processing_time=_aware(processing_time),
        processing_time_source=processing_time_source,
        product_family=product_family,
        line_id=line_id,
        station_id=station_id,
        camera_id=camera_id,
        terms=query_terms,
        limit=memory_limit,
    )
    selected, retrieval = retrieve_approved_memories_v3(
        memory_cards,
        query,
        profile=retrieval_profile or DEFAULT_HYBRID_RETRIEVAL_PROFILE_V2,
        embedding_adapter=embedding_adapter,
        memory_admission_status=memory_admission_status,
        memory_admission_store_sha256=memory_admission_store_sha256,
    )
    verify_memory_retrieval_receipt(retrieval)
    stable = {
        "schema_version": "visiondata-gate.governed-memory-planning-input.v1",
        "planning_subject_sha256": planning_subject_sha256,
        "query_scope": retrieval.query_scope,
        "accepted_historical_references": [
            HistoricalMemoryReference(
                memory_id=card.memory_id,
                memory_sha256=card.memory_sha256,
                memory_type=card.memory_type,
                pattern=card.content.pattern,
                recommended_first_check=card.content.recommended_first_check,
                avoid_first_action=card.content.avoid_first_action,
                source_case_ids=card.source_case_ids,
            )
            for card in selected
        ],
        "retrieval_receipt": retrieval,
        "allowed_effects": [
            "MISSING_EVIDENCE_PRIORITIZATION",
            "COUNTEREVIDENCE_QUESTION",
            "ALLOWLISTED_WORKER_PRIORITY",
        ],
        "current_case_fact_authority": "none",
        "root_cause_authority": "none",
        "decision_authority": "none",
        "policy_judge_input": False,
        "machine_action_permitted": False,
    }
    planning_input = GovernedMemoryPlanningInput(
        **stable,
        input_sha256=_sha256(stable),
    )
    verify_governed_memory_planning_input(planning_input)
    return planning_input


def verify_governed_memory_planning_input(
    planning_input: GovernedMemoryPlanningInput,
) -> None:
    verify_memory_retrieval_receipt(planning_input.retrieval_receipt)
    if isinstance(planning_input.retrieval_receipt, LegacyMemoryRetrievalReceiptV1):
        raise ValueError("governed planning input requires a scoped hybrid receipt")
    payload = planning_input.model_dump(mode="json")
    stored = payload.pop("input_sha256")
    if not hmac.compare_digest(stored, _sha256(payload)):
        raise ValueError("governed memory planning input failed SHA-256 validation")
    if not hmac.compare_digest(
        planning_input.planning_subject_sha256,
        planning_input.retrieval_receipt.current_case_sha256,
    ):
        raise ValueError("governed memory planning input lost subject binding")
    if planning_input.query_scope != planning_input.retrieval_receipt.query_scope:
        raise ValueError("governed memory planning input lost query-scope binding")
    selected = planning_input.retrieval_receipt.selected
    accepted = planning_input.accepted_historical_references
    if [item.memory_id for item in accepted] != [item.memory_id for item in selected]:
        raise ValueError("governed memory planning input lost selected-memory order")
    if [item.memory_sha256 for item in accepted] != [
        item.memory_sha256 for item in selected
    ]:
        raise ValueError("governed memory planning input lost selected-memory digest")
    if any(
        reference.current_case_fact_eligible or reference.may_set_current_case_fact
        for reference in accepted
    ):
        raise ValueError("governed historical memory gained current-case authority")


def governed_memory_planner_payload(
    planning_input: GovernedMemoryPlanningInput,
) -> dict[str, object]:
    """Return the narrow Planner-visible view; rejected card content stays hidden."""

    verify_governed_memory_planning_input(planning_input)
    return {
        "schema_version": planning_input.schema_version,
        "input_sha256": planning_input.input_sha256,
        "retrieval_receipt_sha256": (planning_input.retrieval_receipt.receipt_sha256),
        "query_scope": planning_input.query_scope.model_dump(mode="json"),
        "accepted_historical_references": [
            item.model_dump(mode="json")
            for item in planning_input.accepted_historical_references
        ],
        "selected_memory_count": planning_input.retrieval_receipt.selected_count,
        "rejected_memory_count": planning_input.retrieval_receipt.rejected_count,
        "allowed_effects": planning_input.allowed_effects,
        "current_case_fact_authority": planning_input.current_case_fact_authority,
        "root_cause_authority": planning_input.root_cause_authority,
        "decision_authority": planning_input.decision_authority,
        "policy_judge_input": planning_input.policy_judge_input,
        "machine_action_permitted": planning_input.machine_action_permitted,
    }


def assemble_incident_context(
    *,
    case: IndustrialIncidentCase,
    site_pack: FactorySitePack,
    memory_cards: list[ApprovedMemoryCard],
    as_of: datetime | None = None,
    query_terms: list[str] | None = None,
    product_family: str | None = None,
    station_id: str | None = None,
    camera_id: str | None = None,
    memory_limit: int = 4,
    planning_input: GovernedMemoryPlanningInput | None = None,
    legacy_only: bool = False,
) -> AssembledIncidentContext:
    verify_industrial_incident_case(case)
    verify_factory_site_pack(site_pack)
    if planning_input is None:
        if not legacy_only:
            raise ValueError(
                "direct context assembly requires governed planning input or "
                "legacy_only=True"
            )
        if as_of is None:
            raise ValueError("legacy-only context assembly requires explicit as_of")
        if station_id is not None:
            raise ValueError(
                "legacy-only memory query cannot claim station-scope authorization"
            )
        query = LegacyMemoryQueryV1(
            site_id=site_pack.manifest.site_id,
            current_case_sha256=case.case_sha256,
            as_of=_aware(as_of),
            product_family=product_family,
            line_id=case.request.trigger.line_id,
            camera_id=camera_id,
            terms=query_terms or case.decision_summary.unresolved_reason_codes,
            limit=memory_limit,
        )
        selected, retrieval = retrieve_approved_memories(memory_cards, query)
        verification = verify_memory_retrieval_receipt(retrieval)
        if verification.dual_clock_authorization != "NOT_PROVABLE":
            raise ValueError("legacy-only retrieval made a dual-clock authority claim")
        accepted_references = [
            HistoricalMemoryReference(
                memory_id=card.memory_id,
                memory_sha256=card.memory_sha256,
                memory_type=card.memory_type,
                pattern=card.content.pattern,
                recommended_first_check=card.content.recommended_first_check,
                avoid_first_action=card.content.avoid_first_action,
                source_case_ids=card.source_case_ids,
            )
            for card in selected
        ]
    else:
        if legacy_only:
            raise ValueError("governed planning input cannot be marked legacy-only")
        verify_governed_memory_planning_input(planning_input)
        if planning_input.query_scope.site_id != site_pack.manifest.site_id:
            raise ValueError("governed memory planning input escaped the Site Pack")
        if planning_input.query_scope.line_id != case.request.trigger.line_id:
            raise ValueError("governed memory planning input escaped the incident line")
        if case.governed_memory_planning_input_sha256 != planning_input.input_sha256:
            raise ValueError(
                "incident case lost governed memory planning input binding"
            )
        if (
            case.governed_memory_retrieval_receipt_sha256
            != planning_input.retrieval_receipt.receipt_sha256
        ):
            raise ValueError("incident case lost memory retrieval receipt binding")
        retrieval = planning_input.retrieval_receipt
        accepted_references = planning_input.accepted_historical_references
    gaps = sorted(
        {
            reference
            for hypothesis in case.hypotheses
            for reference in hypothesis.unresolved_evidence_refs
        }
        | {
            f"{question.expected_evidence_type}:{question.question_id}"
            for question in case.operator_questions
            if question.status == "OPEN"
        }
    )
    available_tools = sorted(
        {
            action.agent_role
            for action in case.agent_actions
            if action.dynamic and action.agent_role.endswith("Agent")
        }
    )
    context_stable = {
        "schema_version": "visiondata-gate.incident-advisor-context.v1",
        "case_id": case.case_id,
        "case_sha256": case.case_sha256,
        "site_id": site_pack.manifest.site_id,
        "site_pack_sha256": site_pack.pack_sha256,
        "current_case_facts": case.decision_summary.observed_facts,
        "current_hypotheses": [
            ContextHypothesis(
                hypothesis_id=item.hypothesis_id,
                category=item.category,
                status=item.status.value,
                unresolved_evidence_refs=item.unresolved_evidence_refs,
            )
            for item in case.hypotheses
        ],
        "current_evidence_gaps": gaps,
        "site_profile": {
            "site_name": site_pack.manifest.site_name,
            "timezone": site_pack.manifest.timezone,
            "quality_owner_roles": site_pack.manifest.quality_owner_roles,
            "supported_case_types": site_pack.manifest.supported_case_types,
        },
        "relevant_approved_memories": accepted_references,
        "available_tools": available_tools,
        "remaining_worker_budget": case.loop_control.remaining_worker_budget,
        "frozen_prohibitions": [
            "DO_NOT_ESTABLISH_ROOT_CAUSE",
            "DO_NOT_APPROVE_CAPA",
            "DO_NOT_RELEASE_PRODUCTION",
            "DO_NOT_WRITE_EQUIPMENT",
            "DO_NOT_TREAT_HISTORY_AS_CURRENT_FACT",
        ],
        "precedence": [
            "FROZEN_POLICY",
            "CURRENT_VERIFIED_EVIDENCE",
            "CURRENT_SITE_PROFILE",
            "APPROVED_HISTORICAL_EXPERIENCE",
            "MODEL_SUGGESTION",
        ],
        "historical_memory_used_as_current_fact": False,
    }
    context = IncidentAdvisorContext(
        **context_stable,
        context_sha256=_sha256(context_stable),
    )
    receipt_stable = {
        "schema_version": "visiondata-gate.context-receipt.v1",
        "case_id": case.case_id,
        "case_sha256": case.case_sha256,
        "site_id": site_pack.manifest.site_id,
        "site_pack_sha256": site_pack.pack_sha256,
        "context_sha256": context.context_sha256,
        "memory_retrieval_receipt_sha256": retrieval.receipt_sha256,
        "governed_memory_planning_input_sha256": (
            planning_input.input_sha256 if planning_input is not None else None
        ),
        "selected_memory_ids": [item.memory_id for item in accepted_references],
        "cross_site_memory_leakage_count": 0,
        "stale_memory_acceptance_count": 0,
        "historical_memory_used_as_fact_count": 0,
        "may_set_current_case_fact": False,
        "raw_prompt_retained": False,
        "raw_image_retained": False,
    }
    receipt = ContextReceipt(
        **receipt_stable,
        receipt_sha256=_sha256(receipt_stable),
    )
    assembled = AssembledIncidentContext(
        context=context,
        receipt=receipt,
        retrieval_receipt=retrieval,
        planning_input=planning_input,
    )
    verify_assembled_incident_context(
        assembled,
        case=case,
        site_pack=site_pack,
    )
    return assembled


def verify_assembled_incident_context(
    assembled: AssembledIncidentContext,
    *,
    case: IndustrialIncidentCase,
    site_pack: FactorySitePack,
) -> None:
    verify_memory_retrieval_receipt(assembled.retrieval_receipt)
    if assembled.planning_input is None:
        if assembled.receipt.governed_memory_planning_input_sha256 is not None:
            raise ValueError("context receipt references absent planning input")
    else:
        verify_governed_memory_planning_input(assembled.planning_input)
        if assembled.planning_input.retrieval_receipt != assembled.retrieval_receipt:
            raise ValueError(
                "assembled context replaced the planning retrieval receipt"
            )
        if (
            assembled.receipt.governed_memory_planning_input_sha256
            != assembled.planning_input.input_sha256
        ):
            raise ValueError("context receipt lost planning-input binding")
        if (
            case.governed_memory_planning_input_sha256
            != assembled.planning_input.input_sha256
            or case.governed_memory_retrieval_receipt_sha256
            != assembled.retrieval_receipt.receipt_sha256
        ):
            raise ValueError("assembled context lost pre-planning Case binding")
    context_payload = assembled.context.model_dump(mode="json")
    context_sha = context_payload.pop("context_sha256")
    if not hmac.compare_digest(context_sha, _sha256(context_payload)):
        raise ValueError("incident advisor context failed SHA-256 validation")
    receipt_payload = assembled.receipt.model_dump(mode="json")
    receipt_sha = receipt_payload.pop("receipt_sha256")
    if not hmac.compare_digest(receipt_sha, _sha256(receipt_payload)):
        legacy_receipt_payload = dict(receipt_payload)
        if assembled.receipt.governed_memory_planning_input_sha256 is None:
            legacy_receipt_payload.pop(
                "governed_memory_planning_input_sha256",
                None,
            )
        if not hmac.compare_digest(receipt_sha, _sha256(legacy_receipt_payload)):
            raise ValueError("context receipt failed SHA-256 validation")
    if assembled.context.case_id != case.case_id or not hmac.compare_digest(
        assembled.context.case_sha256,
        case.case_sha256,
    ):
        raise ValueError("assembled context failed case binding")
    if (
        assembled.context.site_id != site_pack.manifest.site_id
        or not hmac.compare_digest(
            assembled.context.site_pack_sha256,
            site_pack.pack_sha256,
        )
    ):
        raise ValueError("assembled context failed Site Pack binding")
    if any(
        reference.current_case_fact_eligible or reference.may_set_current_case_fact
        for reference in assembled.context.relevant_approved_memories
    ):
        raise ValueError("historical memory escaped into current case facts")
    selected_ids = [item.memory_id for item in assembled.retrieval_receipt.selected]
    if assembled.receipt.selected_memory_ids != selected_ids:
        raise ValueError("context receipt failed selected-memory binding")


__all__ = [
    "ApprovedMemoryCard",
    "ApprovedMemoryContent",
    "AssembledIncidentContext",
    "ClockedMemoryQueryV3",
    "ContextReceipt",
    "DEFAULT_HYBRID_RETRIEVAL_PROFILE_V2",
    "EmbeddingIdentity",
    "GovernedMemoryPlanningInput",
    "HybridMemoryRetrievalReceiptV2",
    "HybridMemoryRetrievalReceiptV3",
    "HybridRetrievalProfileV2",
    "IncidentAdvisorContext",
    "LocalEmbeddingAdapter",
    "LegacyHybridMemoryQueryV2",
    "LegacyHybridMemoryRetrievalReceiptV2",
    "LegacyMemoryQueryV1",
    "LegacyMemoryRetrievalReceiptV1",
    "MemoryQuery",
    "MemoryProcessingTimeSource",
    "MemoryRetrievalReceipt",
    "MemoryRetrievalReceiptAny",
    "MemoryRetrievalVerificationResult",
    "MemoryScope",
    "assemble_incident_context",
    "build_approved_memory_card",
    "build_governed_memory_planning_input",
    "build_hybrid_retrieval_profile_v2",
    "governed_memory_planner_payload",
    "load_approved_memory_store",
    "parse_memory_retrieval_receipt",
    "retrieve_approved_memories",
    "retrieve_approved_memories_v2",
    "retrieve_approved_memories_v3",
    "verify_approved_memory_card",
    "verify_assembled_incident_context",
    "verify_governed_memory_planning_input",
    "verify_hybrid_retrieval_profile_v2",
    "verify_memory_retrieval_command_admission_binding",
    "verify_memory_retrieval_receipt",
]
