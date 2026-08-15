"""Auditable, role-separated AI council traces."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass

from .contracts import (
    AgentOpinion,
    CouncilTrace,
    EvidenceStatus,
    Finding,
    GateDecision,
    Severity,
    ToolTrace,
)


@dataclass(frozen=True)
class _RoleSpec:
    role_id: str
    display_name: str
    focus: str
    keywords: tuple[str, ...]
    challenge: str
    counterfactual_guard: str


_ROLE_SPECS = (
    _RoleSpec(
        role_id="ai_data_contract",
        display_name="AI Data Contract Expert",
        focus="Frozen contract scope, evidence status, and release boundary",
        keywords=("CONTRACT", "SCHEMA", "SPLIT", "COVERAGE"),
        challenge=(
            "AI Acquisition Quality Expert: are every threshold and claimed "
            "measurement tied to an executed tool trace?"
        ),
        counterfactual_guard=(
            "If one split is removed and the rest remain unchanged, recommendation "
            "should only tighten, never expand."
        ),
    ),
    _RoleSpec(
        role_id="ai_acquisition_quality",
        display_name="AI Acquisition Quality Expert",
        focus="Decodeability, dimensions, illumination, and sharpness",
        keywords=(
            "DECODE",
            "DIMENSION",
            "LUMA",
            "SHARP",
            "BLUR",
            "QUALITY",
        ),
        challenge=(
            "AI Annotation and Coverage Expert: could mask structure or missing "
            "coverage invalidate the apparent image-quality conclusion?"
        ),
        counterfactual_guard=(
            "If one high-quality sample is replaced by the same corruption level, "
            "recommendation should remain consistent after recompute."
        ),
    ),
    _RoleSpec(
        role_id="ai_duplicate_leakage",
        display_name="AI Duplicate and Leakage Expert",
        focus="Exact duplicates, near duplicates, and cross-split leakage",
        keywords=("DUPLICATE", "LEAK", "SPLIT"),
        challenge=(
            "AI Annotation and Coverage Expert: after removal or repartition, "
            "does every required coverage cell remain populated?"
        ),
        counterfactual_guard=(
            "If one suspected duplicate source is excluded, core leakage conclusions "
            "should not become more permissive."
        ),
    ),
    _RoleSpec(
        role_id="ai_annotation_coverage",
        display_name="AI Annotation and Coverage Expert",
        focus="Annotation structure and contract coverage cells",
        keywords=(
            "ANNOTATION",
            "MASK",
            "LABEL",
            "BBOX",
            "COVERAGE",
            "MISSING_CELL",
        ),
        challenge=(
            "AI Duplicate and Leakage Expert: would a proposed relabel preserve "
            "a duplicate or cross-split leak?"
        ),
        counterfactual_guard=(
            "If one annotation path is perturbed within bounded edits, "
            "coverage and relabel risk profile should be revalidated."
        ),
    ),
    _RoleSpec(
        role_id="ai_repair_safety",
        display_name="AI Repair Safety Expert",
        focus="Work-order remediation side-effects and residual risk",
        keywords=("RECAPTURE", "REMOVE_OR_REPARTITION", "RELABEL", "REPAIR"),
        challenge=(
            "All AI council roles: can every remediation order be executed without "
            "introducing higher-priority unresolved findings?"
        ),
        counterfactual_guard=(
            "After applying a hypothetical repair order, recommendation should be "
            "retested by a full deterministic second pass."
        ),
    ),
    _RoleSpec(
        role_id="ai_red_team_auditor",
        display_name="AI Red-Team Audit Expert",
        focus="Missing evidence, tool failures, and unsafe release claims",
        keywords=(),
        challenge=(
            "All AI council roles: identify one conclusion that would change if "
            "a tool failed or its evidence were unsupported."
        ),
        counterfactual_guard=(
            "Any transition from ok to error on a critical tool must force DEFER; "
            "failure-free relaxation is invalid."
        ),
    ),
)


def _is_relevant(role: _RoleSpec, finding: Finding) -> bool:
    if role.role_id == "ai_red_team_auditor":
        return True
    code = finding.code.upper()
    return any(keyword in code for keyword in role.keywords)


def _role_findings(role: _RoleSpec, findings: Sequence[Finding]) -> list[Finding]:
    return [finding for finding in findings if _is_relevant(role, finding)]


def _recommendation(
    findings: Sequence[Finding], traces: Sequence[ToolTrace]
) -> GateDecision:
    if any(trace.status != "ok" for trace in traces):
        return GateDecision.DEFER
    if any(
        finding.evidence_status is EvidenceStatus.UNSUPPORTED
        or (
            finding.evidence_status is EvidenceStatus.INFERRED
            and finding.severity in {Severity.CRITICAL, Severity.HIGH}
        )
        for finding in findings
    ):
        return GateDecision.DEFER

    codes = " ".join(finding.code.upper() for finding in findings)
    if any(
        keyword in codes
        for keyword in (
            "COVERAGE",
            "MISSING_CELL",
            "SHARP",
            "BLUR",
            "LUMA",
            "DIMENSION",
            "QUALITY",
        )
    ):
        return GateDecision.RECAPTURE
    if findings:
        return GateDecision.QUARANTINE
    return GateDecision.PASS


def _confidence_axes(
    findings: Sequence[Finding], traces: Sequence[ToolTrace]
) -> dict[str, str]:
    tool_status = (
        "high" if traces and all(trace.status == "ok" for trace in traces) else "low"
    )
    evidence_status = (
        "high"
        if findings
        and all(
            finding.evidence_status is EvidenceStatus.VERIFIED for finding in findings
        )
        else "medium"
    )
    return {
        "E": evidence_status,
        "T": tool_status,
        "A": "high" if findings else "medium",
        "M": "low",
    }


def _claims(findings: Sequence[Finding], traces: Sequence[ToolTrace]) -> list[str]:
    claims = [
        (
            f"Tool finding {finding.finding_id} reports code {finding.code} "
            f"with evidence status {finding.evidence_status.value}."
        )
        for finding in findings
    ]
    claims.extend(
        f"Tool trace {trace.sequence}:{trace.tool} ended with status {trace.status}."
        for trace in traces
        if trace.status != "ok"
    )
    if not claims:
        claims.append(
            "No role-specific finding was emitted by the executed tool traces; "
            "this is not proof that untested issues are absent."
        )
    return claims


def _required_additional_evidence(
    role: _RoleSpec,
    relevant_findings: Sequence[Finding],
    traces: Sequence[ToolTrace],
) -> list[str]:
    if not traces:
        return ["No deterministic evidence traces were available; rerun all tools."]

    if role.role_id == "ai_red_team_auditor":
        missing = [
            f"Tool {trace.tool} returned non-OK status {trace.status}."
            for trace in traces
            if trace.status != "ok"
        ]
        if missing:
            return missing + [
                "Request complete trace payloads for each failed/unknown tool."
            ]

    if not relevant_findings:
        return [
            f"Collect a focused control probe for one sample in role keywords {', '.join(role.keywords[:2])} "
            "before changing final posture."
        ]

    evidence: list[str] = []
    unsupported = [
        finding
        for finding in relevant_findings
        if finding.evidence_status is not EvidenceStatus.VERIFIED
    ]
    if unsupported:
        evidence.append(
            "Re-collect unsupported or inferred findings from raw tool outputs."
        )
    for finding in relevant_findings:
        evidence.append(
            f"{finding.code} at sample set {', '.join(sorted(finding.sample_ids))}"
        )
    return evidence[:4]


def build_council(
    findings: Sequence[Finding],
    traces: Sequence[ToolTrace],
    metrics: Mapping[str, int | float | str],
) -> CouncilTrace:
    """Build a deterministic AI council trace from tool-produced evidence."""

    finding_list = list(findings)
    trace_list = list(traces)
    metric_refs = [f"metric:{key}" for key in sorted(metrics)]
    opinions: list[AgentOpinion] = []

    for role in _ROLE_SPECS:
        relevant = _role_findings(role, finding_list)
        evidence_refs = [finding.finding_id for finding in relevant]
        evidence_refs.extend(
            f"trace:{trace.sequence}:{trace.tool}"
            for trace in trace_list
            if trace.status != "ok" or role.role_id == "ai_red_team_auditor"
        )
        evidence_refs.extend(metric_refs)

        opinions.append(
            AgentOpinion(
                role_id=role.role_id,
                display_name=role.display_name,
                focus=role.focus,
                evidence_refs=evidence_refs,
                claims=_claims(relevant, trace_list),
                challenge=role.challenge,
                recommendation=_recommendation(relevant, trace_list),
                confidence_axes=_confidence_axes(relevant, trace_list),
                limitations=[
                    "This is an AI role, not a human domain expert.",
                    "The role shares one backend with all other council roles.",
                    "Its recommendation is advisory and cannot override tool evidence.",
                ],
                required_additional_evidence=_required_additional_evidence(
                    role, relevant, trace_list
                ),
                counterfactual_guard=role.counterfactual_guard,
            )
        )

    unresolved = [
        f"Tool {trace.tool} did not complete successfully: {trace.error or trace.status}."
        for trace in trace_list
        if trace.status != "ok"
    ]
    unresolved.extend(
        f"Finding {finding.finding_id} has unsupported evidence."
        for finding in finding_list
        if finding.evidence_status is EvidenceStatus.UNSUPPORTED
    )
    if not finding_list:
        unresolved.append(
            "Absence of findings is conditional on the tools that actually ran."
        )
    unresolved.append(
        "No AI council opinion establishes production readiness; production authority "
        "remains human."
    )

    return CouncilTrace(
        backend="shared-deterministic-ai-council-simulator-v1",
        shared_model_disclosure=(
            "All named experts are explicitly simulated AI roles using one shared "
            "backend. Their agreement is not independent evidence, and a vote is "
            "never used to justify a gate decision."
        ),
        independent_opinions=opinions,
        cross_examination=[role.challenge for role in _ROLE_SPECS],
        unresolved_objections=unresolved,
    )


def build_single_agent_review(
    findings: Sequence[Finding],
    traces: Sequence[ToolTrace],
    metrics: Mapping[str, int | float | str],
) -> CouncilTrace:
    """Build the one-reviewer baseline used by the architecture benchmark.

    The reviewer sees exactly the same typed evidence as the multi-role council.
    It has no tool or release authority, and the deterministic Policy Judge
    remains unchanged.  Keeping this baseline explicit prevents a six-role
    prompt from being relabelled as a single Agent during evaluation.
    """

    finding_list = list(findings)
    trace_list = list(traces)
    evidence_refs = [item.finding_id for item in finding_list]
    evidence_refs.extend(f"trace:{trace.sequence}:{trace.tool}" for trace in trace_list)
    evidence_refs.extend(f"metric:{key}" for key in sorted(metrics))
    opinion = AgentOpinion(
        role_id="ai_generalist_reviewer",
        display_name="AI Generalist Evidence Reviewer",
        focus="All frozen contract, measurement, remediation, and release evidence",
        evidence_refs=evidence_refs,
        claims=_claims(finding_list, trace_list),
        challenge=(
            "Policy Judge: reject any recommendation that is not supported by "
            "a completed ToolTrace and the frozen contract."
        ),
        recommendation=_recommendation(finding_list, trace_list),
        confidence_axes=_confidence_axes(finding_list, trace_list),
        limitations=[
            "This is one AI reviewer, not a panel or a human expert.",
            "It cannot call tools, change the contract, or write the release decision.",
            "Its recommendation is advisory and is not detection evidence.",
        ],
        required_additional_evidence=[
            f"Resolve non-OK trace {trace.tool}:{trace.status}."
            for trace in trace_list
            if trace.status != "ok"
        ],
        counterfactual_guard=(
            "Reordering equivalent findings or traces must not make the release "
            "decision more permissive."
        ),
    )
    unresolved = [
        f"Tool {trace.tool} did not complete successfully: {trace.error or trace.status}."
        for trace in trace_list
        if trace.status != "ok"
    ]
    unresolved.append(
        "A single reviewer is not independent corroboration and has no production authority."
    )
    return CouncilTrace(
        backend="single-deterministic-ai-reviewer-v1",
        shared_model_disclosure=(
            "Exactly one deterministic AI reviewer interprets the shared typed evidence; "
            "the Policy Judge remains the only release authority."
        ),
        independent_opinions=[opinion],
        cross_examination=[],
        unresolved_objections=unresolved,
    )


def build_traditional_pipeline_receipt() -> CouncilTrace:
    """Return the no-Agent review receipt for the traditional baseline."""

    return CouncilTrace(
        backend="traditional-deterministic-pipeline-v1",
        shared_model_disclosure=(
            "No AI reviewer is used. Deterministic tool outputs flow directly into "
            "the same frozen Policy Judge used by the Agent baselines."
        ),
        independent_opinions=[],
        cross_examination=[],
        unresolved_objections=[
            "This baseline has no Agent interpretation or cross-role challenge."
        ],
    )


__all__ = [
    "build_council",
    "build_single_agent_review",
    "build_traditional_pipeline_receipt",
]
