"""Runtime tool-fault interventions for the fail-closed gateway and Judge.

The evaluator exercises the same ``execute_tool_gateway`` path used by the
agent runtime.  Each frozen fault is injected independently, converted into a
typed error trace, and passed to the deterministic Policy Judge.  It does not
call an LLM, modify source evidence, or grant release authority.
"""

from __future__ import annotations

from collections.abc import Callable
from functools import partial
from pathlib import Path
from typing import Any

from .contracts import (
    BatchContract,
    BatchManifest,
    Finding,
    GateDecision,
    GateResult,
    ToolTrace,
)
from .evidence import canonical_json_bytes, sha256_bytes
from .policy import apply_policy
from .runtime_models import ScenarioProfile
from .tools import (
    MetricValue,
    ToolResult,
    build_batch_fingerprint,
    build_tool_request_sha256,
    execute_tool_gateway,
    tool_catalog,
    validate_tool_contract_trace,
)


FaultRunner = Callable[..., object]


def _alternate_digest(value: str | None) -> str:
    replacement = "0" * 64
    return "f" * 64 if value == replacement else replacement


def _timeout_runner(*_args: Any, **_kwargs: Any) -> object:
    raise TimeoutError("simulated adapter deadline exceeded")


def _copy_tool_result(result: ToolResult) -> ToolResult:
    return (
        [item.model_copy(deep=True) for item in result[0]],
        result[1].model_copy(deep=True),
        dict(result[2]),
    )


def _static_response_runner(result: ToolResult, *_args: Any, **_kwargs: Any) -> object:
    return _copy_tool_result(result)


def _stale_response_runner(result: ToolResult, *_args: Any, **_kwargs: Any) -> object:
    findings, trace, metrics = _copy_tool_result(result)
    return (
        findings,
        trace.model_copy(
            update={"input_sha256": _alternate_digest(trace.input_sha256)}
        ),
        metrics,
    )


def _malformed_payload_runner(*_args: Any, **_kwargs: Any) -> object:
    return {"status": "ok", "findings": [], "metrics": {}}


def _permission_denied_runner(*_args: Any, **_kwargs: Any) -> object:
    raise PermissionError("simulated adapter permission denial")


def _poisoned_contract_runner(
    result: ToolResult, *_args: Any, **_kwargs: Any
) -> object:
    findings, trace, metrics = _copy_tool_result(result)
    return (
        findings,
        trace.model_copy(
            update={"contract_digest": _alternate_digest(trace.contract_digest)}
        ),
        metrics,
    )


_FAULTS: tuple[tuple[str, str, str, FaultRunner | None], ...] = (
    (
        "TFR-001",
        "timeout",
        "adapter raises TimeoutError before returning a response",
        _timeout_runner,
    ),
    (
        "TFR-002",
        "stale_response",
        "response carries a digest from a different request",
        None,
    ),
    (
        "TFR-003",
        "malformed_payload",
        "adapter returns an untyped mapping instead of the response tuple",
        _malformed_payload_runner,
    ),
    (
        "TFR-004",
        "permission_denied",
        "adapter raises PermissionError for the allowlisted call",
        _permission_denied_runner,
    ),
    (
        "TFR-005",
        "poisoned_tool_contract",
        "response contract digest no longer matches the registered description",
        None,
    ),
)


def _aggregate_tool_results(
    results: list[ToolResult], manifest: BatchManifest
) -> tuple[list[Finding], list[ToolTrace], dict[str, MetricValue]]:
    findings: list[Finding] = []
    traces: list[ToolTrace] = []
    metrics: dict[str, MetricValue] = {
        "sample_count": len(manifest.samples),
        "tool_count": len(results),
        "tool_error_count": sum(result[1].status != "ok" for result in results),
    }
    for tool_findings, trace, tool_metrics in results:
        findings.extend(item.model_copy(deep=True) for item in tool_findings)
        traces.append(trace.model_copy(deep=True))
        metrics.update(tool_metrics)
    findings.sort(key=lambda item: (item.tool, item.finding_id))
    traces.sort(key=lambda item: item.sequence)
    metrics["finding_count"] = len(findings)
    return findings, traces, metrics


def _source_sha256(
    manifest: BatchManifest,
    contract: BatchContract,
    baseline_results: list[ToolResult],
) -> str:
    return sha256_bytes(
        canonical_json_bytes(
            {
                "manifest": manifest,
                "contract": contract,
                "baseline_results": [
                    {
                        "findings": result[0],
                        "trace": result[1],
                        "metrics": result[2],
                    }
                    for result in baseline_results
                ],
            }
        )
    )


def _results_from_gate_result(
    gate_result: GateResult,
    *,
    include_optional: bool,
) -> list[ToolResult]:
    catalog = tool_catalog(include_optional=include_optional)
    finding_by_id = {item.finding_id: item for item in gate_result.findings}
    trace_by_tool = {item.tool: item for item in gate_result.tool_trace}
    results: list[ToolResult] = []
    for item in catalog:
        tool_name = str(item["name"])
        trace = trace_by_tool.get(tool_name)
        if trace is None or trace.status != "ok":
            raise ValueError(f"baseline GateResult has no clean trace for {tool_name}")
        findings = [
            finding_by_id[finding_id].model_copy(deep=True)
            for finding_id in trace.finding_ids
        ]
        metric_prefix = f"{item['metric_prefix']}_"
        metrics = {
            key: value
            for key, value in gate_result.metrics.items()
            if key.startswith(metric_prefix)
        }
        results.append((findings, trace.model_copy(deep=True), metrics))
    return results


def build_tool_fault_evaluation_receipt(
    batch_root: str | Path,
    manifest: BatchManifest,
    contract: BatchContract,
    *,
    scenario_profile: ScenarioProfile = ScenarioProfile.GENERIC,
    include_optional: bool = False,
    target_tool: str = "image_quality",
    baseline_gate_result: GateResult | None = None,
) -> dict[str, Any]:
    """Evaluate five runtime response faults under one fixed local protocol."""

    catalog = tool_catalog(include_optional=include_optional)
    tool_names = [str(item["name"]) for item in catalog]
    if target_tool not in tool_names:
        raise ValueError(f"target tool is not active: {target_tool}")

    batch_fingerprint_before = build_batch_fingerprint(batch_root, manifest)

    if baseline_gate_result is None:
        baseline_results = [
            execute_tool_gateway(
                tool_name,
                batch_root,
                manifest,
                contract,
                include_optional=include_optional,
                batch_fingerprint=batch_fingerprint_before,
            )
            for tool_name in tool_names
        ]
    else:
        saved_results = _results_from_gate_result(
            baseline_gate_result, include_optional=include_optional
        )
        baseline_results = [
            execute_tool_gateway(
                result[1].tool,
                batch_root,
                manifest,
                contract,
                include_optional=include_optional,
                runner=partial(_static_response_runner, result),
                batch_fingerprint=batch_fingerprint_before,
            )
            for result in saved_results
        ]
    source_before_sha256 = _source_sha256(manifest, contract, baseline_results)
    baseline_findings, baseline_traces, baseline_metrics = _aggregate_tool_results(
        baseline_results, manifest
    )
    baseline_policy_result = apply_policy(
        manifest,
        contract,
        baseline_findings,
        baseline_traces,
        baseline_metrics,
        scenario_profile=scenario_profile,
        run_id="tool-fault-baseline",
    )
    baseline_gateway_ok = all(trace.status == "ok" for trace in baseline_traces)
    expected_request_sha256 = build_tool_request_sha256(
        target_tool,
        batch_root,
        manifest,
        contract,
        include_optional=include_optional,
        batch_fingerprint=batch_fingerprint_before,
    )
    clean_target_result = next(
        result for result in baseline_results if result[1].tool == target_tool
    )

    cases: list[dict[str, Any]] = []
    for case_id, fault_family, injection, runner in _FAULTS:
        active_runner = runner
        if fault_family == "stale_response":
            active_runner = partial(_stale_response_runner, clean_target_result)
        elif fault_family == "poisoned_tool_contract":
            active_runner = partial(_poisoned_contract_runner, clean_target_result)
        if active_runner is None:
            raise RuntimeError(f"fault runner is not configured: {fault_family}")
        fault_result = execute_tool_gateway(
            target_tool,
            batch_root,
            manifest,
            contract,
            include_optional=include_optional,
            runner=active_runner,
            batch_fingerprint=batch_fingerprint_before,
        )
        case_results = [
            fault_result
            if result[1].tool == target_tool
            else (
                [item.model_copy(deep=True) for item in result[0]],
                result[1].model_copy(deep=True),
                dict(result[2]),
            )
            for result in baseline_results
        ]
        findings, traces, metrics = _aggregate_tool_results(case_results, manifest)
        gate_result = apply_policy(
            manifest,
            contract,
            findings,
            traces,
            metrics,
            scenario_profile=scenario_profile,
            run_id=f"tool-fault-{case_id.lower()}",
        )
        error_trace = fault_result[1]
        typed_error_trace = (
            isinstance(error_trace, ToolTrace)
            and error_trace.status == "error"
            and bool(error_trace.error)
            and not error_trace.finding_ids
            and error_trace.input_sha256 == expected_request_sha256
            and validate_tool_contract_trace(
                error_trace, include_optional=include_optional
            )
            is None
        )
        investigation_work_order = any(
            order.action == "INVESTIGATE"
            and "TOOL_ERROR" in order.reason_codes
            and target_tool in order.reason_codes
            for order in gate_result.work_orders
        )
        detected = (
            typed_error_trace
            and gate_result.decision is GateDecision.DEFER
            and investigation_work_order
            and not fault_result[0]
            and not fault_result[2]
        )
        cases.append(
            {
                "case_id": case_id,
                "fault_family": fault_family,
                "injection": injection,
                "target_tool": target_tool,
                "gateway_trace_status": error_trace.status,
                "gateway_error": error_trace.error,
                "typed_error_trace": typed_error_trace,
                "request_digest_matches_current_input": (
                    error_trace.input_sha256 == expected_request_sha256
                ),
                "findings_forwarded": len(fault_result[0]),
                "metrics_forwarded": len(fault_result[2]),
                "policy_decision": gate_result.decision.value,
                "policy_deferred": gate_result.decision is GateDecision.DEFER,
                "investigation_work_order_present": investigation_work_order,
                "detected": detected,
                "status": "DETECTED" if detected else "MISSED",
            }
        )

    source_after_sha256 = _source_sha256(manifest, contract, baseline_results)
    batch_fingerprint_after = build_batch_fingerprint(batch_root, manifest)
    source_evidence_unchanged = (
        source_after_sha256 == source_before_sha256
        and batch_fingerprint_after == batch_fingerprint_before
    )
    detected_count = sum(bool(case["detected"]) for case in cases)
    intervention_count = len(cases)
    missed_count = intervention_count - detected_count
    status = (
        "PASS_LOCAL"
        if baseline_gateway_ok and source_evidence_unchanged and missed_count == 0
        else "FAIL"
    )
    return {
        "schema_version": "visiondata-gate.tool-fault-intervention.v1",
        "evaluation_type": "runtime_tool_gateway_fail_closed",
        "status": status,
        "target_tool": target_tool,
        "scenario_profile": scenario_profile.value,
        "baseline": {
            "gateway_ok": baseline_gateway_ok,
            "policy_decision": baseline_policy_result.decision.value,
            "tool_count": len(baseline_traces),
            "source_input_sha256": source_before_sha256,
            "batch_fingerprint_sha256": batch_fingerprint_before,
        },
        "method": {
            "strategy": "execute_inject_gateway_validate_policy",
            "fixed_denominator": intervention_count,
            "tool_gateway_path_shared_with_runtime": True,
            "policy_judge_used": True,
            "llm_judge_used": False,
            "model_call_count": 0,
            "source_evidence_mutated": not source_evidence_unchanged,
            "batch_bytes_rehashed_before_and_after": True,
            "shared_gateway_request_fingerprint": True,
        },
        "summary": {
            "intervention_count": intervention_count,
            "detected_count": detected_count,
            "missed_count": missed_count,
            "detection_rate": round(detected_count / intervention_count, 6),
            "typed_error_trace_count": sum(
                bool(case["typed_error_trace"]) for case in cases
            ),
            "policy_defer_count": sum(bool(case["policy_deferred"]) for case in cases),
            "source_evidence_unchanged": source_evidence_unchanged,
        },
        "interventions": cases,
        "claims": {
            "runtime_gateway_fault_handling_measured": True,
            "frozen_fault_catalog_complete": True,
            "automatic_recovery_measured": False,
            "production_resilience_measured": False,
            "hosted_agent_platform_tested": False,
        },
        "boundary": (
            "PASS_LOCAL means the local runtime Tool Gateway converted all five frozen "
            "adapter/response faults into typed error traces and the deterministic Policy "
            "Judge returned DEFER for this fixture. It does not prove automatic recovery, "
            "real network timeout enforcement, production resilience, hosted-platform "
            "behavior, or official competition acceptance."
        ),
    }


__all__ = ["build_tool_fault_evaluation_receipt"]
