"""Strict grounding contracts for optional model-assisted council opinions.

The language model is never a measurement source or a release authority.  This
module turns the evidence already produced by deterministic tools into a small
fact index, validates model citations against exact source spans, and emits a
machine-readable receipt for accepted and rejected claims.
"""

from __future__ import annotations

import re
from collections.abc import Mapping, Sequence
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator

from .contracts import Finding, GateDecision, ToolTrace
from .evidence import canonical_json_text, sha256_bytes
from .runtime_models import KnowledgeHit


class GroundingModel(BaseModel):
    """Reject silent schema changes at the model trust boundary."""

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


class EvidenceFact(GroundingModel):
    ref: str = Field(min_length=1)
    aliases: list[str] = Field(default_factory=list)
    kind: Literal["finding", "tool_trace", "metric", "knowledge"]
    source_path: str = Field(min_length=1)
    text: str = Field(min_length=1)
    sha256: str = Field(min_length=64, max_length=64)


class ModelCitation(GroundingModel):
    evidence_ref: str = Field(min_length=1, max_length=240)
    evidence_span: str = Field(min_length=1, max_length=2_000)


class ModelClaim(GroundingModel):
    kind: Literal["observation", "risk", "recommendation"]
    statement: str = Field(min_length=1, max_length=1_200)
    citations: list[ModelCitation] = Field(min_length=1, max_length=8)

    @field_validator("citations")
    @classmethod
    def unique_citations(cls, values: list[ModelCitation]) -> list[ModelCitation]:
        keys = [(item.evidence_ref, item.evidence_span) for item in values]
        if len(keys) != len(set(keys)):
            raise ValueError("citations must be unique")
        return values


class ModelAdvisoryResponse(GroundingModel):
    schema_version: Literal["visiondata-gate.model-advisory.v1"] = (
        "visiondata-gate.model-advisory.v1"
    )
    decision_authority: Literal["none"] = "none"
    claims: list[ModelClaim] = Field(min_length=1, max_length=12)
    challenge: str = Field(min_length=1, max_length=1_200)
    advisory_recommendation: GateDecision
    confidence_axes: dict[Literal["E", "T", "A", "M"], Literal["high", "medium", "low"]]
    limitations: list[str] = Field(default_factory=list, max_length=8)

    @field_validator("confidence_axes")
    @classmethod
    def all_confidence_axes_are_required(
        cls,
        value: dict[Literal["E", "T", "A", "M"], Literal["high", "medium", "low"]],
    ) -> dict[Literal["E", "T", "A", "M"], Literal["high", "medium", "low"]]:
        if set(value) != {"E", "T", "A", "M"}:
            raise ValueError("confidence_axes must contain exactly E, T, A, and M")
        return value

    @field_validator("challenge")
    @classmethod
    def challenge_cannot_assert_external_authority(cls, value: str) -> str:
        if _unsupported_authority(value):
            raise ValueError("challenge contains unsupported external authority")
        return value

    @field_validator("limitations")
    @classmethod
    def limitations_cannot_assert_external_authority(
        cls, values: list[str]
    ) -> list[str]:
        if len(values) != len(set(values)):
            raise ValueError("limitations must be unique")
        if any(_unsupported_authority(value) for value in values):
            raise ValueError("limitations contain unsupported external authority")
        return values


class ClaimGroundingCheck(GroundingModel):
    claim_index: int = Field(ge=0)
    accepted: bool
    evidence_refs: list[str] = Field(default_factory=list)
    invalid_refs: list[str] = Field(default_factory=list)
    invalid_spans: list[str] = Field(default_factory=list)
    unsupported_numeric_literals: list[str] = Field(default_factory=list)
    issues: list[str] = Field(default_factory=list)


class RoleGroundingReceipt(GroundingModel):
    role_id: str = Field(min_length=1)
    phase: Literal["initial", "verification", "unspecified"] = "unspecified"
    status: Literal[
        "not_attempted",
        "accepted",
        "grounding_rejected",
        "schema_rejected",
        "transport_error",
    ]
    attempted: bool
    connected: bool
    schema_valid: bool
    output_accepted: bool
    claim_count: int = Field(ge=0)
    accepted_claim_count: int = Field(ge=0)
    citation_count: int = Field(ge=0)
    valid_citation_count: int = Field(ge=0)
    unsupported_claim_count: int = Field(ge=0)
    checks: list[ClaimGroundingCheck] = Field(default_factory=list)
    issues: list[str] = Field(default_factory=list)
    response_sha256: str | None = Field(default=None, min_length=64, max_length=64)


class LLMGroundingReceipt(GroundingModel):
    schema_version: Literal["visiondata-gate.llm-grounding-receipt.v1"] = (
        "visiondata-gate.llm-grounding-receipt.v1"
    )
    backend: str = Field(min_length=1)
    model: str = Field(min_length=1)
    endpoint_scope: Literal["none", "local", "remote"]
    connected: bool
    actual_model_call_count: int = Field(ge=0)
    transport_success_count: int = Field(ge=0)
    accepted_output_count: int = Field(ge=0)
    claim_count: int = Field(ge=0)
    unsupported_claim_count: int = Field(ge=0)
    citation_count: int = Field(ge=0)
    valid_citation_count: int = Field(ge=0)
    unsupported_claim_rate: float | None = Field(default=None, ge=0.0, le=1.0)
    citation_validity: float | None = Field(default=None, ge=0.0, le=1.0)
    decision_authority: Literal["none"] = "none"
    final_decision_authority: Literal["frozen_policy_judge"] = "frozen_policy_judge"
    role_receipts: list[RoleGroundingReceipt] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    boundary_notice: str = (
        "Model output is advisory only. Missing, malformed, ungrounded, or "
        "authority-seeking output is rejected and cannot relax the frozen gate."
    )


_NUMBER_RE = re.compile(r"(?<![\w])[-+]?(?:\d+(?:\.\d+)?|\.\d+)%?")
_WORD_RE = re.compile(r"[A-Za-z][A-Za-z0-9_-]{3,}|[\u4e00-\u9fff]{2,}")
_AUTHORITY_PATTERNS = (
    re.compile(r"\bproduction[- ]ready\b", re.IGNORECASE),
    re.compile(r"\bcustomer[- ]accepted\b", re.IGNORECASE),
    re.compile(r"\bcertified\b", re.IGNORECASE),
    re.compile(r"\bapproved for production\b", re.IGNORECASE),
    re.compile(r"生产(?:已经|已)?(?:验证|验收|批准|放行)"),
    re.compile(r"客户(?:已经|已)?验收"),
    re.compile(r"可直接放行"),
    re.compile(r"获得认证"),
)
_STOPWORDS = {
    "this",
    "that",
    "with",
    "from",
    "into",
    "reports",
    "shows",
    "evidence",
    "finding",
    "当前",
    "证据",
    "显示",
    "说明",
    "存在",
    "需要",
    "建议",
}


def _fact(
    *,
    ref: str,
    aliases: Sequence[str],
    kind: Literal["finding", "tool_trace", "metric", "knowledge"],
    source_path: str,
    payload: Any,
) -> EvidenceFact:
    text = canonical_json_text(payload, trailing_newline=False)
    return EvidenceFact(
        ref=ref,
        aliases=sorted(set(str(item) for item in aliases if item and item != ref)),
        kind=kind,
        source_path=source_path,
        text=text,
        sha256=sha256_bytes(text.encode("utf-8")),
    )


def build_evidence_fact_index(
    findings: Sequence[Finding],
    traces: Sequence[ToolTrace],
    metrics: Mapping[str, int | float | str],
    knowledge: Sequence[KnowledgeHit],
) -> tuple[list[EvidenceFact], dict[str, EvidenceFact]]:
    """Create a canonical evidence index and explicit alias lookup."""

    facts: list[EvidenceFact] = []
    for finding in sorted(findings, key=lambda item: item.finding_id):
        facts.append(
            _fact(
                ref=f"finding:{finding.finding_id}",
                aliases=[finding.finding_id],
                kind="finding",
                source_path=f"findings/{finding.finding_id}",
                payload=finding.model_dump(mode="json"),
            )
        )
    for trace in sorted(traces, key=lambda item: (item.sequence, item.tool)):
        ref = f"trace:{trace.sequence}:{trace.tool}"
        facts.append(
            _fact(
                ref=ref,
                aliases=[],
                kind="tool_trace",
                source_path=f"tool_trace/{trace.sequence}/{trace.tool}",
                payload=trace.model_dump(mode="json"),
            )
        )
    for key, value in sorted(metrics.items()):
        facts.append(
            _fact(
                ref=f"metric:{key}",
                aliases=[],
                kind="metric",
                source_path=f"metrics/{key}",
                payload={"name": key, "value": value},
            )
        )
    for hit in sorted(knowledge, key=lambda item: item.card_id):
        facts.append(
            _fact(
                ref=f"knowledge:{hit.card_id}",
                aliases=[hit.source],
                kind="knowledge",
                source_path=f"knowledge/{hit.card_id}",
                payload=hit.model_dump(mode="json"),
            )
        )

    lookup: dict[str, EvidenceFact] = {}
    for item in facts:
        for key in [item.ref, *item.aliases]:
            if key in lookup and lookup[key].sha256 != item.sha256:
                raise ValueError(f"ambiguous evidence alias: {key}")
            lookup[key] = item
    return facts, lookup


def _content_tokens(text: str) -> set[str]:
    return {
        token.casefold()
        for token in _WORD_RE.findall(text)
        if token.casefold() not in _STOPWORDS
    }


def _unsupported_authority(statement: str) -> bool:
    return any(pattern.search(statement) for pattern in _AUTHORITY_PATTERNS)


def validate_model_advisory(
    payload: Mapping[str, Any],
    *,
    role_id: str,
    allowed_refs: Sequence[str],
    fact_lookup: Mapping[str, EvidenceFact],
) -> tuple[ModelAdvisoryResponse | None, RoleGroundingReceipt]:
    """Validate schema, citations, exact spans, numeric facts, and authority."""

    response_digest = sha256_bytes(
        canonical_json_text(dict(payload), trailing_newline=False).encode("utf-8")
    )
    try:
        response = ModelAdvisoryResponse.model_validate(payload)
    except ValidationError as error:
        return None, RoleGroundingReceipt(
            role_id=role_id,
            status="schema_rejected",
            attempted=True,
            connected=True,
            schema_valid=False,
            output_accepted=False,
            claim_count=1,
            accepted_claim_count=0,
            citation_count=0,
            valid_citation_count=0,
            unsupported_claim_count=1,
            issues=[
                f"schema_validation_failed:{item['type']}" for item in error.errors()
            ],
            response_sha256=response_digest,
        )

    allowed = set(allowed_refs)
    checks: list[ClaimGroundingCheck] = []
    total_citations = 0
    valid_citations = 0
    accepted_claims = 0
    for index, claim in enumerate(response.claims):
        invalid_refs: list[str] = []
        invalid_spans: list[str] = []
        cited_spans: list[str] = []
        normalized_refs: list[str] = []
        for citation in claim.citations:
            total_citations += 1
            fact = fact_lookup.get(citation.evidence_ref)
            if citation.evidence_ref not in allowed or fact is None:
                invalid_refs.append(citation.evidence_ref)
                continue
            if citation.evidence_span not in fact.text:
                invalid_spans.append(citation.evidence_ref)
                continue
            valid_citations += 1
            cited_spans.append(citation.evidence_span)
            normalized_refs.append(fact.ref)

        cited_text = " ".join(cited_spans)
        unsupported_numbers = sorted(
            literal
            for literal in set(_NUMBER_RE.findall(claim.statement))
            if literal not in cited_text
        )
        issues: list[str] = []
        if invalid_refs:
            issues.append("unknown_or_disallowed_reference")
        if invalid_spans:
            issues.append("span_not_found_in_cited_fact")
        if unsupported_numbers:
            issues.append("numeric_literal_not_in_cited_span")
        if _unsupported_authority(claim.statement):
            issues.append("unsupported_production_or_acceptance_authority")
        if cited_spans and not (
            _content_tokens(claim.statement) & _content_tokens(cited_text)
        ):
            issues.append("claim_has_no_lexical_support_in_cited_span")
        accepted = not issues
        if accepted:
            accepted_claims += 1
        checks.append(
            ClaimGroundingCheck(
                claim_index=index,
                accepted=accepted,
                evidence_refs=sorted(set(normalized_refs)),
                invalid_refs=sorted(set(invalid_refs)),
                invalid_spans=sorted(set(invalid_spans)),
                unsupported_numeric_literals=unsupported_numbers,
                issues=issues,
            )
        )

    unsupported_claims = len(response.claims) - accepted_claims
    accepted = unsupported_claims == 0
    receipt = RoleGroundingReceipt(
        role_id=role_id,
        status="accepted" if accepted else "grounding_rejected",
        attempted=True,
        connected=True,
        schema_valid=True,
        output_accepted=accepted,
        claim_count=len(response.claims),
        accepted_claim_count=accepted_claims,
        citation_count=total_citations,
        valid_citation_count=valid_citations,
        unsupported_claim_count=unsupported_claims,
        checks=checks,
        issues=([] if accepted else ["one_or_more_claims_failed_grounding"]),
        response_sha256=response_digest,
    )
    return (response if accepted else None), receipt


def build_llm_grounding_receipt(
    *,
    backend: str,
    model: str,
    endpoint_scope: Literal["none", "local", "remote"],
    role_receipts: Sequence[RoleGroundingReceipt],
    warnings: Sequence[str] = (),
) -> LLMGroundingReceipt:
    roles = list(role_receipts)
    claim_count = sum(item.claim_count for item in roles)
    unsupported = sum(item.unsupported_claim_count for item in roles)
    citation_count = sum(item.citation_count for item in roles)
    valid_citations = sum(item.valid_citation_count for item in roles)
    return LLMGroundingReceipt(
        backend=backend,
        model=model,
        endpoint_scope=endpoint_scope,
        connected=any(item.connected for item in roles),
        actual_model_call_count=sum(item.attempted for item in roles),
        transport_success_count=sum(item.connected for item in roles),
        accepted_output_count=sum(item.output_accepted for item in roles),
        claim_count=claim_count,
        unsupported_claim_count=unsupported,
        citation_count=citation_count,
        valid_citation_count=valid_citations,
        unsupported_claim_rate=(unsupported / claim_count if claim_count else None),
        citation_validity=(
            valid_citations / citation_count if citation_count else None
        ),
        role_receipts=roles,
        warnings=list(warnings),
    )


def not_attempted_role_receipt(role_id: str) -> RoleGroundingReceipt:
    return RoleGroundingReceipt(
        role_id=role_id,
        status="not_attempted",
        attempted=False,
        connected=False,
        schema_valid=False,
        output_accepted=False,
        claim_count=0,
        accepted_claim_count=0,
        citation_count=0,
        valid_citation_count=0,
        unsupported_claim_count=0,
    )


def transport_error_role_receipt(role_id: str, error_type: str) -> RoleGroundingReceipt:
    return RoleGroundingReceipt(
        role_id=role_id,
        status="transport_error",
        attempted=True,
        connected=False,
        schema_valid=False,
        output_accepted=False,
        claim_count=0,
        accepted_claim_count=0,
        citation_count=0,
        valid_citation_count=0,
        unsupported_claim_count=0,
        issues=[f"transport_error:{error_type}"],
    )


__all__ = [
    "EvidenceFact",
    "LLMGroundingReceipt",
    "ModelAdvisoryResponse",
    "ModelCitation",
    "ModelClaim",
    "RoleGroundingReceipt",
    "build_evidence_fact_index",
    "build_llm_grounding_receipt",
    "not_attempted_role_receipt",
    "transport_error_role_receipt",
    "validate_model_advisory",
]
