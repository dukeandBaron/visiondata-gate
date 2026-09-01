"""Enterprise-facing acceptance scorecard built only from persisted evidence."""

from __future__ import annotations

import math
from collections.abc import Mapping
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from .annotation_roundtrip import AnnotationProvider, AnnotationRoundtripReceipt
from .contracts import EvaluationResult
from .grounding import LLMGroundingReceipt
from .runtime_models import RuntimeTrace


class AcceptanceModel(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


class AcceptanceMetric(AcceptanceModel):
    key: str = Field(min_length=1)
    label: str = Field(min_length=1)
    value: bool | int | float | str | None = None
    unit: str | None = None
    target: str = Field(min_length=1)
    status: Literal["PASS", "FAIL", "OBSERVED", "NOT_MEASURED"]
    source_ref: str = Field(min_length=1)
    note: str = Field(min_length=1)


class AcceptanceScorecard(AcceptanceModel):
    schema_version: Literal["visiondata-gate.acceptance-scorecard.v1"] = (
        "visiondata-gate.acceptance-scorecard.v1"
    )
    task_id: str = Field(min_length=1)
    scope: Literal["local_sandbox_evaluation"] = "local_sandbox_evaluation"
    overall_status: Literal["PASS_LOCAL", "PARTIAL_LOCAL", "FAIL_LOCAL"]
    final_gate_decision: str = Field(min_length=1)
    metrics: list[AcceptanceMetric] = Field(min_length=1)
    external_connections: dict[str, str]
    decision_authority: Literal["frozen_policy_judge"] = "frozen_policy_judge"
    production_acceptance: Literal["not_claimed"] = "not_claimed"
    boundary_notice: str = (
        "This scorecard reports local evidence and explicitly marks unavailable metrics. "
        "It is not a customer acceptance certificate, factory deployment receipt, or "
        "production authorization."
    )


def _dynamic_metric(
    key: str,
    label: str,
    evaluation: Mapping[str, Any] | None,
) -> AcceptanceMetric:
    if evaluation is None or key not in evaluation:
        return AcceptanceMetric(
            key=key,
            label=label,
            value=None,
            target="report on labelled trigger fixtures",
            status="NOT_MEASURED",
            source_ref="dynamic_trigger_evaluation:not_available",
            note=(
                "The local product task does not contain labelled dynamic-trigger ground "
                "truth; no precision/recall value is inferred from a replan count."
            ),
        )
    raw_value = evaluation[key]
    if (
        isinstance(raw_value, bool)
        or not isinstance(raw_value, (int, float))
        or not math.isfinite(float(raw_value))
        or not 0.0 <= float(raw_value) <= 1.0
    ):
        return AcceptanceMetric(
            key=key,
            label=label,
            value=None,
            unit="ratio",
            target=">= 0.90",
            status="FAIL",
            source_ref="dynamic_trigger_evaluation.json",
            note="The supplied trigger metric is not a finite numeric ratio in [0, 1].",
        )
    value = float(raw_value)
    return AcceptanceMetric(
        key=key,
        label=label,
        value=value,
        unit="ratio",
        target=">= 0.90",
        status="PASS" if value >= 0.9 else "FAIL",
        source_ref="dynamic_trigger_evaluation.json",
        note="Measured against labelled trigger and non-trigger fixtures.",
    )


def build_acceptance_scorecard(
    *,
    task_id: str,
    runtime_trace: RuntimeTrace,
    evaluation: EvaluationResult | None,
    grounding_receipt: LLMGroundingReceipt | None,
    roundtrip_receipt: AnnotationRoundtripReceipt | None = None,
    dynamic_trigger_evaluation: Mapping[str, Any] | None = None,
    data_source: str = "synthetic_demo",
) -> AcceptanceScorecard:
    """Build a scorecard without promoting absent measurements into zeroes."""

    metrics: list[AcceptanceMetric] = []
    if grounding_receipt is None:
        metrics.extend(
            [
                AcceptanceMetric(
                    key="unsupported_claim_rate",
                    label="无证据主张率",
                    value=None,
                    unit="ratio",
                    target="= 0 when model output exists",
                    status="NOT_MEASURED",
                    source_ref="llm_grounding_receipt:not_available",
                    note=(
                        "This task evidence does not contain a model grounding receipt; "
                        "no unsupported-claim denominator is inferred from deterministic "
                        "tool output."
                    ),
                ),
                AcceptanceMetric(
                    key="citation_validity",
                    label="引用有效率",
                    value=None,
                    unit="ratio",
                    target="= 1 when model output exists",
                    status="NOT_MEASURED",
                    source_ref="llm_grounding_receipt:not_available",
                    note=(
                        "This task evidence does not contain model citations, so citation "
                        "validity has no measured denominator."
                    ),
                ),
            ]
        )
    elif grounding_receipt.claim_count:
        unsupported_rate = grounding_receipt.unsupported_claim_rate
        citation_validity = grounding_receipt.citation_validity
        metrics.extend(
            [
                AcceptanceMetric(
                    key="unsupported_claim_rate",
                    label="无证据主张率",
                    value=unsupported_rate,
                    unit="ratio",
                    target="= 0",
                    status="PASS" if unsupported_rate == 0 else "FAIL",
                    source_ref="llm_grounding_receipt.json",
                    note="Rejected claims remain visible in the grounding receipt.",
                ),
                AcceptanceMetric(
                    key="citation_validity",
                    label="引用有效率",
                    value=citation_validity,
                    unit="ratio",
                    target="= 1",
                    status="PASS" if citation_validity == 1 else "FAIL",
                    source_ref="llm_grounding_receipt.json",
                    note="A valid citation requires an allowed ref and an exact source span.",
                ),
            ]
        )
    else:
        metrics.extend(
            [
                AcceptanceMetric(
                    key="unsupported_claim_rate",
                    label="无证据主张率",
                    value=None,
                    unit="ratio",
                    target="= 0 when model output exists",
                    status="NOT_MEASURED",
                    source_ref="llm_grounding_receipt.json",
                    note="No model claims were emitted; the deterministic council was used.",
                ),
                AcceptanceMetric(
                    key="citation_validity",
                    label="引用有效率",
                    value=None,
                    unit="ratio",
                    target="= 1 when model output exists",
                    status="NOT_MEASURED",
                    source_ref="llm_grounding_receipt.json",
                    note="No model citations were emitted, so a denominator is unavailable.",
                ),
            ]
        )

    metrics.extend(
        [
            _dynamic_metric(
                "dynamic_trigger_precision",
                "动态触发精确率",
                dynamic_trigger_evaluation,
            ),
            _dynamic_metric(
                "dynamic_trigger_recall",
                "动态触发召回率",
                dynamic_trigger_evaluation,
            ),
        ]
    )

    if roundtrip_receipt is None:
        metrics.extend(
            [
                AcceptanceMetric(
                    key="work_order_roundtrip_fidelity",
                    label="工单往返保真度",
                    value=None,
                    unit="ratio",
                    target="= 1",
                    status="NOT_MEASURED",
                    source_ref="annotation_roundtrip_receipt:not_available",
                    note="No annotation return package has been imported for this task.",
                ),
                AcceptanceMetric(
                    key="remediation_closure_rate",
                    label="整改闭环率",
                    value=None,
                    unit="ratio",
                    target=">= 0.90",
                    status="NOT_MEASURED",
                    source_ref="annotation_roundtrip_receipt:not_available",
                    note="Closure requires accepted returned bytes and a same-contract recheck.",
                ),
            ]
        )
    else:
        closure = roundtrip_receipt.remediation_closure_rate
        metrics.extend(
            [
                AcceptanceMetric(
                    key="work_order_roundtrip_fidelity",
                    label="工单往返保真度",
                    value=roundtrip_receipt.roundtrip_fidelity,
                    unit="ratio",
                    target="= 1",
                    status=(
                        "PASS"
                        if roundtrip_receipt.roundtrip_fidelity == 1.0
                        else "FAIL"
                    ),
                    source_ref=f"{roundtrip_receipt.receipt_id}.receipt.json",
                    note="Accepted revisions passed sample, work-order, version, hash, and mask checks.",
                ),
                AcceptanceMetric(
                    key="remediation_closure_rate",
                    label="整改闭环率",
                    value=closure,
                    unit="ratio",
                    target=">= 0.90",
                    status=(
                        "NOT_MEASURED"
                        if closure is None
                        else "PASS"
                        if closure >= 0.9
                        else "FAIL"
                    ),
                    source_ref=f"{roundtrip_receipt.receipt_id}.receipt.json",
                    note=(
                        "A work order closes only when every mapped sample is accepted and "
                        "its original reason code is absent from the same-contract recheck."
                    ),
                ),
                AcceptanceMetric(
                    key="annotation_recheck_gate_outcome",
                    label="整改回传复验结论",
                    value=roundtrip_receipt.recheck_decision,
                    target="PASS under the frozen contract",
                    status=(
                        "NOT_MEASURED"
                        if not roundtrip_receipt.same_contract_recheck_performed
                        else "PASS"
                        if roundtrip_receipt.recheck_decision == "PASS"
                        else "FAIL"
                    ),
                    source_ref=f"{roundtrip_receipt.receipt_id}.receipt.json",
                    note=(
                        "This metric evaluates the imported annotation recheck; it is "
                        "separate from the built-in synthetic repair benchmark."
                    ),
                ),
            ]
        )

    elapsed_ms = runtime_trace.memory.working.get("elapsed_ms")
    metrics.append(
        AcceptanceMetric(
            key="batch_latency_ms",
            label="批次端到端时延",
            value=float(elapsed_ms) if isinstance(elapsed_ms, (int, float)) else None,
            unit="ms",
            target="report-only until an enterprise SLO is frozen",
            status=(
                "OBSERVED" if isinstance(elapsed_ms, (int, float)) else "NOT_MEASURED"
            ),
            source_ref="agent_runtime_trace.json#/memory/working/elapsed_ms",
            note="Observed local wall-clock latency; hardware-normalized SLO is not claimed.",
        )
    )
    if runtime_trace.model_call_count == 0:
        metrics.append(
            AcceptanceMetric(
                key="provider_billed_model_cost",
                label="外部模型计费成本",
                value=0.0,
                unit="CNY",
                target="report-only",
                status="OBSERVED",
                source_ref="agent_runtime_trace.json#/model_call_count",
                note="No external model call occurred; local CPU/GPU infrastructure cost is not priced.",
            )
        )
    else:
        metrics.append(
            AcceptanceMetric(
                key="provider_billed_model_cost",
                label="外部模型计费成本",
                value=None,
                unit="CNY",
                target="capture provider usage receipt",
                status="NOT_MEASURED",
                source_ref="provider_usage_receipt:not_available",
                note="Model calls occurred but token usage and provider billing were not supplied.",
            )
        )

    if evaluation is None:
        metrics.extend(
            [
                AcceptanceMetric(
                    key="critical_bad_release_rate",
                    label="合成基准关键错误放行率",
                    value=None,
                    unit="ratio",
                    target="= 0 on labelled synthetic truth",
                    status="NOT_MEASURED",
                    source_ref="initial/evaluation.json:not_available",
                    note=(
                        "This authorized-source task has no synthetic truth manifest; a "
                        "critical bad-release rate is not inferred from its Gate decision."
                    ),
                ),
                AcceptanceMetric(
                    key="task_success",
                    label="合成基准自动修复闭环",
                    value=None,
                    target="true on the frozen synthetic repair fixture",
                    status="NOT_MEASURED",
                    source_ref="initial/evaluation.json:not_available",
                    note=(
                        "The real-source task does not run the built-in synthetic repair "
                        "benchmark; remediation remains represented by work orders and an "
                        "optional same-contract roundtrip."
                    ),
                ),
            ]
        )
    else:
        metrics.extend(
            [
                AcceptanceMetric(
                    key="critical_bad_release_rate",
                    label="合成基准关键错误放行率",
                    value=evaluation.critical_bad_release_rate,
                    unit="ratio",
                    target="= 0",
                    status=(
                        "PASS" if evaluation.critical_bad_release_rate == 0 else "FAIL"
                    ),
                    source_ref="initial/evaluation.json",
                    note="Measured against the frozen synthetic truth manifest.",
                ),
                AcceptanceMetric(
                    key="task_success",
                    label="合成基准自动修复闭环",
                    value=evaluation.post_repair_correct_pass,
                    target="true",
                    status="PASS" if evaluation.post_repair_correct_pass else "FAIL",
                    source_ref="initial/evaluation.json",
                    note=(
                        "This is the frozen synthetic benchmark's built-in repair result; it "
                        "does not substitute for an imported annotation recheck."
                    ),
                ),
            ]
        )

    data_source_state = {
        "synthetic_demo": "connected",
        "local_authorized_directory": "connected_readonly_operator_attested",
        "external_residency_reference": "not_connected",
    }.get(data_source, "unknown_not_connected")
    if grounding_receipt is None:
        llm_state = (
            "not_connected_runtime_model_calls_0"
            if runtime_trace.model_call_count == 0
            else "grounding_receipt_not_available"
        )
    else:
        llm_state = (
            f"{grounding_receipt.endpoint_scope}_connected"
            if grounding_receipt.connected
            else "not_connected"
        )
    connections = {
        "data_source": f"{data_source}:{data_source_state}",
        "llm": llm_state,
        "cvat": "not_connected",
        "fiftyone": "not_connected",
        "agentteams": (
            runtime_trace.agentteams.connection_status
            if runtime_trace.agentteams is not None
            else "not_configured"
        ),
    }
    if roundtrip_receipt is not None:
        key = (
            "cvat"
            if roundtrip_receipt.provider is AnnotationProvider.CVAT
            else "fiftyone"
        )
        connections[key] = (
            "connected"
            if roundtrip_receipt.external_connected
            else "local_contract_verified_not_connected"
        )

    if any(item.status == "FAIL" for item in metrics):
        overall = "FAIL_LOCAL"
    elif any(item.status == "NOT_MEASURED" for item in metrics):
        overall = "PARTIAL_LOCAL"
    else:
        overall = "PASS_LOCAL"
    if not runtime_trace.judge_decisions:
        raise ValueError("acceptance scorecard requires a frozen judge decision")
    return AcceptanceScorecard(
        task_id=task_id,
        overall_status=overall,
        final_gate_decision=runtime_trace.judge_decisions[-1],
        metrics=metrics,
        external_connections=connections,
    )


__all__ = [
    "AcceptanceMetric",
    "AcceptanceScorecard",
    "build_acceptance_scorecard",
]
