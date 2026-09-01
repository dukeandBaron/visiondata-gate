"""Contract-valid ProductService lifecycle stub; not an Agent E2E runner.

The stub deliberately exercises only ProductService state transitions, artifact
binding, and event reconciliation.  It emits no model or tool evidence and must
never be counted as an Agent runtime, benchmark, or release-readiness result.
"""

from __future__ import annotations

from collections.abc import Callable
import hashlib
from pathlib import Path
from typing import TypeAlias

from visiondata_gate.contracts import CouncilTrace, GateDecision, GateResult
from visiondata_gate.evidence import canonical_json_bytes, write_canonical_json
from visiondata_gate.product_runs import (
    SYNTHETIC_REQUIRED_EVIDENCE,
    ProductTaskRun,
    seal_product_task_run,
)
from visiondata_gate.runtime_models import (
    MemorySnapshot,
    RuntimeConfig,
    RuntimeEvent,
    RuntimeStage,
    RuntimeStatus,
    RuntimeTrace,
    ScenarioProfile,
)

LifecycleEventTransform: TypeAlias = Callable[
    [tuple[RuntimeEvent, ...]], tuple[RuntimeEvent, ...]
]
LifecycleProductRunner: TypeAlias = Callable[..., ProductTaskRun]

_KERNEL_RECEIPT_PATH = "product_kernel_run_receipt.json"
_TRACE_PATH = "agent_runtime_trace.json"
_INITIAL_GATE_PATH = "initial/gate_result.json"
_FINAL_GATE_PATH = "repaired/gate_result.json"


def _sha256(value: object) -> str:
    return hashlib.sha256(canonical_json_bytes(value)).hexdigest()


def _gate_result(
    *,
    run_id: str,
    contract_id: str,
    input_sha256: str,
    decision: GateDecision,
    phase: str,
) -> GateResult:
    return GateResult(
        run_id=run_id,
        batch_id="product-lifecycle-stub-batch",
        contract_id=contract_id,
        input_sha256=input_sha256,
        policy_version="product-lifecycle-stub.v1",
        decision=decision,
        decision_reason=(
            f"Lifecycle stub {phase} decision for ProductService state testing only."
        ),
        metrics={
            "test_scope": "product_lifecycle_only",
            "agent_e2e_evaluated": "false",
            "model_call_count": 0,
            "tool_call_count": 0,
        },
        findings=[],
        tool_trace=[],
        council_trace=CouncilTrace(
            backend="tests.product-lifecycle-stub",
            shared_model_disclosure=(
                "No model or expert council ran; this is not Agent E2E evidence."
            ),
            independent_opinions=[],
            cross_examination=[],
            unresolved_objections=[],
        ),
        rule_checks=[],
        work_orders=[],
        boundary_notice=(
            "TEST ONLY: contract-valid ProductService lifecycle stub. "
            "Agent behavior, tool execution, model grounding, and release readiness "
            "are NOT_EVALUATED."
        ),
    )


def _write_non_kernel_artifacts(
    evidence_dir: Path,
    *,
    final_decision: GateDecision,
) -> None:
    payloads: dict[str, object] = {
        "demo_summary.json": {
            "schema_version": "visiondata-gate.test-lifecycle-summary.v1",
            "status": "NOT_EVALUATED_LIFECYCLE_STUB",
            "final_decision": final_decision.value,
            "agent_e2e": False,
        },
        "proof_index.json": {
            "status": "NOT_EVALUATED_LIFECYCLE_STUB",
            "proof_scope": "product_lifecycle_only",
        },
        "claim_scope_receipt.json": {
            "status": "NOT_EVALUATED_LIFECYCLE_STUB",
            "production": "NOT_AVAILABLE",
            "agent_e2e": "NOT_EVALUATED",
        },
        "llm_grounding_receipt.json": {
            "status": "NOT_EVALUATED_LIFECYCLE_STUB",
            "connected": False,
            "actual_model_call_count": 0,
        },
        "model_transport_receipt.json": {"status": "NOT_ATTEMPTED_LIFECYCLE_STUB"},
        "prompt_injection_runtime_receipt.json": {
            "status": "NOT_EVALUATED_LIFECYCLE_STUB"
        },
        "backend_identity_runtime_receipt.json": {
            "status": "NOT_EVALUATED_LIFECYCLE_STUB"
        },
        "acceptance_scorecard.json": {
            "overall_status": "NOT_EVALUATED_LIFECYCLE_STUB",
            "agent_e2e": False,
        },
    }
    protected = {
        _KERNEL_RECEIPT_PATH,
        _TRACE_PATH,
        _INITIAL_GATE_PATH,
        _FINAL_GATE_PATH,
    }
    for relative in SYNTHETIC_REQUIRED_EVIDENCE:
        if relative in protected:
            continue
        path = evidence_dir / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        if path.suffix == ".csv":
            path.write_text(
                "finding_id,work_order_ids\n",
                encoding="utf-8",
                newline="\n",
            )
            continue
        write_canonical_json(
            path,
            payloads.get(
                relative,
                {
                    "status": "NOT_EVALUATED_LIFECYCLE_STUB",
                    "artifact": relative,
                },
            ),
        )


def make_product_lifecycle_stub_runner(
    final_decision: GateDecision = GateDecision.PASS,
    *,
    trace_event_transform: LifecycleEventTransform | None = None,
) -> LifecycleProductRunner:
    """Return a sealed lifecycle runner; this does not simulate Agent behavior."""

    def run(output_dir: str | Path, **kwargs: object) -> ProductTaskRun:
        root = Path(output_dir)
        evidence_dir = root / "evidence"
        evidence_dir.mkdir(parents=True, exist_ok=False)

        goal = str(kwargs.get("goal") or "Exercise ProductService lifecycle only.")
        seed = kwargs.get("seed", 0)
        config = kwargs.get("config")
        if isinstance(config, RuntimeConfig):
            config_payload: object = config.model_dump(mode="json")
            scenario_profile = config.scenario_profile
        else:
            config_payload = {"status": "CONFIG_NOT_SUPPLIED_TO_LIFECYCLE_STUB"}
            scenario_profile = ScenarioProfile.GENERIC
        execution_config_sha256 = _sha256(config_payload)
        run_id = f"lifecycle-{_sha256([goal, seed, final_decision.value])[:20]}"
        input_sha256 = _sha256([run_id, "product-lifecycle-stub-input"])
        contract_id = "visiondata-gate.product-lifecycle-stub.v1"

        emitted_events = (
            RuntimeEvent(
                sequence=1,
                phase="initial",
                stage=RuntimeStage.INTAKE,
                actor="Product Lifecycle Stub",
                action="accept_lifecycle_fixture",
                status=RuntimeStatus.SUCCESS,
                summary="任务已接收。",
                task_id="lifecycle.intake",
            ),
            RuntimeEvent(
                sequence=2,
                phase="verification",
                stage=RuntimeStage.VERIFY,
                actor="Product Lifecycle Stub",
                action="verify_lifecycle_fixture",
                status=RuntimeStatus.SUCCESS,
                summary="进入复验。",
                task_id="lifecycle.verify",
            ),
        )
        event_sink = kwargs.get("event_sink")
        if callable(event_sink):
            for event in emitted_events:
                event_sink(event)
        trace_events = (
            trace_event_transform(emitted_events)
            if trace_event_transform is not None
            else emitted_events
        )

        trace = RuntimeTrace(
            run_id=run_id,
            execution_config_sha256=execution_config_sha256,
            goal=goal,
            intent="Verify ProductService lifecycle transitions and artifact binding.",
            backend="tests.product-lifecycle-stub",
            backend_connected=False,
            fallback_used=False,
            status=RuntimeStatus.SUCCESS,
            tasks=[],
            events=list(trace_events),
            memory=MemorySnapshot(
                working={"scope": "product_lifecycle_only"},
                session=["Agent E2E is not evaluated by this lifecycle stub."],
            ),
            model_call_count=0,
            tool_call_count=0,
            judge_decisions=[GateDecision.RECAPTURE.value, final_decision.value],
            unresolved=["AGENT_E2E_NOT_EVALUATED"],
            boundary_notice=(
                "TEST ONLY lifecycle stub. No Agent planning, tool execution, model "
                "call, or production decision occurred."
            ),
            scenario_profile=scenario_profile,
        )
        initial = _gate_result(
            run_id=run_id,
            contract_id=contract_id,
            input_sha256=input_sha256,
            decision=GateDecision.RECAPTURE,
            phase="initial",
        )
        final = _gate_result(
            run_id=run_id,
            contract_id=contract_id,
            input_sha256=input_sha256,
            decision=final_decision,
            phase="final",
        )
        trace_path = evidence_dir / _TRACE_PATH
        initial_path = evidence_dir / _INITIAL_GATE_PATH
        final_path = evidence_dir / _FINAL_GATE_PATH
        write_canonical_json(trace_path, trace)
        write_canonical_json(initial_path, initial)
        write_canonical_json(final_path, final)
        _write_non_kernel_artifacts(
            evidence_dir,
            final_decision=final_decision,
        )
        return seal_product_task_run(
            runtime_kind="synthetic_demo",
            evidence_dir=evidence_dir,
            runtime_trace_path=trace_path,
            initial_gate_result_path=initial_path,
            final_gate_result_path=final_path,
        )

    return run


__all__ = [
    "LifecycleEventTransform",
    "LifecycleProductRunner",
    "make_product_lifecycle_stub_runner",
]
