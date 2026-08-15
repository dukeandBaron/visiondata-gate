"""Model-provider adapters for evidence-grounded AI council roles."""

from __future__ import annotations

import json
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from typing import Any, Mapping, Sequence

from .agents import build_council
from .contracts import AgentOpinion, CouncilTrace, Finding, GateDecision, ToolTrace
from .runtime_models import KnowledgeHit, ModelBackendKind, RuntimeConfig


@dataclass(frozen=True)
class CouncilBuild:
    council: CouncilTrace
    model_calls: int
    backend_connected: bool
    fallback_used: bool
    warnings: tuple[str, ...] = ()


def _deterministic_build(
    findings: Sequence[Finding],
    traces: Sequence[ToolTrace],
    metrics: Mapping[str, int | float | str],
) -> CouncilBuild:
    return CouncilBuild(
        council=build_council(findings, traces, metrics),
        model_calls=0,
        backend_connected=True,
        fallback_used=False,
    )


def _safe_json_content(content: str) -> dict[str, Any]:
    stripped = content.strip()
    if stripped.startswith("```"):
        lines = stripped.splitlines()
        if lines and lines[0].startswith("```"):
            lines = lines[1:]
        if lines and lines[-1].strip() == "```":
            lines = lines[:-1]
        stripped = "\n".join(lines).strip()
    payload = json.loads(stripped)
    if not isinstance(payload, dict):
        raise ValueError("model response must be one JSON object")
    return payload


def _is_local_endpoint(endpoint: str) -> bool:
    host = (urllib.parse.urlparse(endpoint).hostname or "").lower()
    return host in {"127.0.0.1", "localhost", "::1"}


class OpenAICompatibleCouncil:
    """Call one evidence-bounded model role at a time via Chat Completions."""

    def __init__(
        self,
        config: RuntimeConfig,
        *,
        api_key: str | None = None,
    ) -> None:
        if not config.endpoint:
            raise ValueError("OpenAI-compatible backend requires an endpoint")
        endpoint = config.endpoint.strip()
        parsed = urllib.parse.urlparse(endpoint)
        if parsed.scheme not in {"http", "https"} or not parsed.netloc:
            raise ValueError("model endpoint must be an absolute http(s) URL")
        if not _is_local_endpoint(endpoint) and not config.allow_remote_model:
            raise PermissionError("remote model calls are disabled by runtime policy")
        if not _is_local_endpoint(endpoint) and parsed.scheme != "https":
            raise PermissionError("remote model endpoint must use HTTPS")
        self.endpoint = endpoint
        self.model = config.model
        self.timeout = config.model_timeout_seconds
        self.max_calls = config.max_model_calls
        self.api_key = api_key

    def _call(self, role: AgentOpinion, evidence: dict[str, Any]) -> dict[str, Any]:
        system = (
            "You are one bounded AI reviewer inside an industrial vision data-release gate. "
            "Return JSON only. Cite only supplied evidence_refs. Do not invent measurements, "
            "human approvals, production claims, or hidden chain-of-thought. Your recommendation "
            "is advisory and must be PASS, QUARANTINE, RECAPTURE, or DEFER."
        )
        requested = {
            "claims": ["short evidence-linked claim"],
            "challenge": "one cross-examination question",
            "recommendation": "PASS|QUARANTINE|RECAPTURE|DEFER",
            "confidence_axes": {
                "E": "high|medium|low",
                "T": "high|medium|low",
                "A": "high|medium|low",
                "M": "high|medium|low",
            },
            "limitations": ["explicit limitation"],
        }
        user = {
            "role": {
                "role_id": role.role_id,
                "display_name": role.display_name,
                "focus": role.focus,
            },
            "allowed_evidence_refs": role.evidence_refs,
            "evidence": evidence,
            "output_schema_example": requested,
        }
        body = json.dumps(
            {
                "model": self.model,
                "messages": [
                    {"role": "system", "content": system},
                    {"role": "user", "content": json.dumps(user, ensure_ascii=False)},
                ],
                "temperature": 0.1,
                "max_tokens": 700,
            },
            ensure_ascii=False,
        ).encode("utf-8")
        headers = {"Content-Type": "application/json"}
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"
        request = urllib.request.Request(
            self.endpoint,
            data=body,
            headers=headers,
            method="POST",
        )
        try:
            with urllib.request.urlopen(request, timeout=self.timeout) as response:
                response_payload = json.loads(response.read().decode("utf-8"))
        except (OSError, urllib.error.URLError, json.JSONDecodeError) as error:
            raise RuntimeError(
                f"model request failed: {type(error).__name__}"
            ) from error
        try:
            content = response_payload["choices"][0]["message"]["content"]
        except (KeyError, IndexError, TypeError) as error:
            raise ValueError(
                "model response does not match Chat Completions schema"
            ) from error
        if not isinstance(content, str):
            raise ValueError("model message content must be text")
        return _safe_json_content(content)

    def build(
        self,
        findings: Sequence[Finding],
        traces: Sequence[ToolTrace],
        metrics: Mapping[str, int | float | str],
        knowledge: Sequence[KnowledgeHit],
    ) -> CouncilBuild:
        baseline = build_council(findings, traces, metrics)
        evidence = {
            "findings": [item.model_dump(mode="json") for item in findings],
            "tool_traces": [item.model_dump(mode="json") for item in traces],
            "metrics": dict(metrics),
            "knowledge": [item.model_dump(mode="json") for item in knowledge],
        }
        opinions: list[AgentOpinion] = []
        warnings: list[str] = []
        model_calls = 0
        successful_calls = 0
        for baseline_opinion in baseline.independent_opinions:
            if model_calls >= self.max_calls:
                warnings.append(
                    f"{baseline_opinion.role_id}: model-call budget exhausted; deterministic fallback used"
                )
                opinions.append(baseline_opinion)
                continue
            model_calls += 1
            try:
                payload = self._call(baseline_opinion, evidence)
                claimed_refs = {
                    ref
                    for claim in payload.get("claims", [])
                    for ref in baseline_opinion.evidence_refs
                    if ref in str(claim)
                }
                if (
                    payload.get("claims")
                    and baseline_opinion.evidence_refs
                    and not claimed_refs
                ):
                    raise ValueError(
                        "model claims do not cite an allowed evidence reference"
                    )
                opinion = AgentOpinion(
                    role_id=baseline_opinion.role_id,
                    display_name=baseline_opinion.display_name,
                    focus=baseline_opinion.focus,
                    evidence_refs=baseline_opinion.evidence_refs,
                    claims=payload.get("claims", []),
                    challenge=str(payload.get("challenge", "")),
                    recommendation=GateDecision(
                        str(payload.get("recommendation", "DEFER"))
                    ),
                    confidence_axes=payload.get("confidence_axes", {}),
                    limitations=payload.get("limitations", [])
                    + [
                        "This model opinion is advisory and cannot override measured tool evidence."
                    ],
                    required_additional_evidence=baseline_opinion.required_additional_evidence,
                    counterfactual_guard=baseline_opinion.counterfactual_guard,
                )
            except (ValueError, TypeError, RuntimeError) as error:
                warnings.append(
                    f"{baseline_opinion.role_id}: {type(error).__name__}; deterministic fallback used"
                )
                opinion = baseline_opinion
            else:
                successful_calls += 1
            opinions.append(opinion)

        fallback_used = successful_calls != len(baseline.independent_opinions)
        unresolved = list(baseline.unresolved_objections)
        unresolved.extend(warnings)
        council = CouncilTrace(
            backend=f"openai-compatible:{self.model}",
            shared_model_disclosure=(
                "All named experts are AI roles using the same configured model endpoint. "
                "Their agreement is not independent evidence; failed or invalid model output "
                "falls back to the deterministic evidence reader."
            ),
            independent_opinions=opinions,
            cross_examination=[item.challenge for item in opinions],
            unresolved_objections=unresolved,
        )
        return CouncilBuild(
            council=council,
            model_calls=model_calls,
            backend_connected=successful_calls > 0,
            fallback_used=fallback_used,
            warnings=tuple(warnings),
        )


def build_council_with_backend(
    config: RuntimeConfig,
    findings: Sequence[Finding],
    traces: Sequence[ToolTrace],
    metrics: Mapping[str, int | float | str],
    knowledge: Sequence[KnowledgeHit],
    *,
    api_key: str | None = None,
) -> CouncilBuild:
    if config.backend is ModelBackendKind.DETERMINISTIC:
        return _deterministic_build(findings, traces, metrics)
    try:
        backend = OpenAICompatibleCouncil(config, api_key=api_key)
        return backend.build(findings, traces, metrics, knowledge)
    except (ValueError, PermissionError) as error:
        fallback = _deterministic_build(findings, traces, metrics)
        council = fallback.council.model_copy(
            update={
                "backend": f"deterministic-fallback:{config.model}",
                "shared_model_disclosure": (
                    "The configured model backend was unavailable or blocked by policy. "
                    "All role outputs came from the local deterministic evidence reader; "
                    "role agreement is not independent evidence."
                ),
                "unresolved_objections": fallback.council.unresolved_objections
                + [f"Model backend setup failed: {type(error).__name__}."],
            }
        )
        return CouncilBuild(
            council=council,
            model_calls=0,
            backend_connected=False,
            fallback_used=True,
            warnings=(f"model backend setup failed: {type(error).__name__}",),
        )


__all__ = ["CouncilBuild", "OpenAICompatibleCouncil", "build_council_with_backend"]
