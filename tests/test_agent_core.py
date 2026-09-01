"""Production Agent-core receipt tests; no demo fixture or evaluation harness."""

from __future__ import annotations

import hashlib

import pytest

from visiondata_gate.contracts import GateDecision
from visiondata_gate.agent_core import (
    AgentCoreExecutionReceipt,
    build_agent_core_execution_receipt,
    verify_agent_core_execution_receipt,
)
from visiondata_gate.evidence import canonical_json_bytes
from visiondata_gate.runtime_models import RuntimeEvent, RuntimeStage, RuntimeStatus


def _events_for_stages(stages: tuple[RuntimeStage, ...]) -> list[RuntimeEvent]:
    return [
        RuntimeEvent(
            sequence=index,
            phase="verification" if stage is RuntimeStage.DELIVERY else "initial",
            stage=stage,
            actor=f"actor-{stage.value}",
            action=f"execute-{stage.value}",
            status=RuntimeStatus.SUCCESS,
            summary=f"live {stage.value} signal",
            task_id=f"tool-{index}" if stage is RuntimeStage.TOOL else None,
            tool_name=f"tool-{index}" if stage is RuntimeStage.TOOL else None,
        )
        for index, stage in enumerate(stages, start=1)
    ]


def _live_events() -> list[RuntimeEvent]:
    events = _events_for_stages(
        (
            RuntimeStage.INTAKE,
            RuntimeStage.PLANNER,
            RuntimeStage.TOOL,
            RuntimeStage.TOOL,
            RuntimeStage.COUNCIL,
            RuntimeStage.JUDGE,
            RuntimeStage.PLANNER,
            RuntimeStage.TOOL,
            RuntimeStage.COUNCIL,
            RuntimeStage.JUDGE,
            RuntimeStage.DELIVERY,
        )
    )
    for index in range(6, len(events)):
        events[index] = events[index].model_copy(update={"phase": "verification"})
    return events


def _build_receipt(events: list[RuntimeEvent]):
    tool_events = [event for event in events if event.stage is RuntimeStage.TOOL]
    return build_agent_core_execution_receipt(
        run_id="authorized-run-001",
        events=events,
        runtime_trace_sha256="a" * 64,
        initial_gate_result_sha256="b" * 64,
        final_gate_result_sha256="c" * 64,
        dynamic_leader_plan_sha256="d" * 64,
        planner_backend="deterministic-leader-v1",
        council_backend="deterministic-evidence-council-v1",
        model_call_count=0,
        tool_call_count=len(tool_events),
        dynamic_task_count=sum(event.phase == "verification" for event in tool_events),
        final_gate_decision=GateDecision.PASS,
    )


def test_agent_core_receipt_binds_live_stage_chain() -> None:
    events = _live_events()
    receipt = _build_receipt(events)

    verify_agent_core_execution_receipt(receipt, events=events)

    assert receipt.signal_capture_mode == "LIVE_CORE_SIGNALS"
    assert receipt.posthoc_event_synthesis is False
    assert receipt.trace_materialization_mode == ("POST_EXECUTION_FROM_LIVE_SIGNALS")
    assert receipt.runtime_event_count == len(events)
    assert all(receipt.required_stage_checks.values())


def test_agent_core_receipt_rejects_post_capture_event_rewrite() -> None:
    events = _live_events()
    receipt = _build_receipt(events)
    events[2] = events[2].model_copy(update={"summary": "rewritten after capture"})

    with pytest.raises(ValueError, match="live event binding mismatch"):
        verify_agent_core_execution_receipt(receipt, events=events)


def test_agent_core_receipt_cannot_seal_incomplete_stage_chain() -> None:
    events = [
        event for event in _live_events() if event.stage is not RuntimeStage.DELIVERY
    ]

    with pytest.raises(ValueError, match="incomplete stage chain"):
        _build_receipt(events)


def test_agent_core_receipt_cannot_seal_out_of_order_required_stages() -> None:
    events = _events_for_stages(
        (
            RuntimeStage.INTAKE,
            RuntimeStage.TOOL,
            RuntimeStage.PLANNER,
            RuntimeStage.COUNCIL,
            RuntimeStage.JUDGE,
            RuntimeStage.DELIVERY,
        )
    )

    with pytest.raises(ValueError, match="first appearances are out of order"):
        _build_receipt(events)


def test_agent_core_receipt_rejects_work_after_delivery_started() -> None:
    events = _live_events()
    events.append(
        RuntimeEvent(
            sequence=len(events) + 1,
            phase="verification",
            stage=RuntimeStage.TOOL,
            actor="late-worker",
            action="execute-after-delivery",
            status=RuntimeStatus.SUCCESS,
            summary="This work must not be accepted after evidence delivery.",
            task_id="tool.after-delivery",
            tool_name="governance_audit",
        )
    )

    with pytest.raises(ValueError, match="Delivery is terminal"):
        _build_receipt(events)


def test_agent_core_receipt_rejects_verification_tool_before_planner() -> None:
    events = _live_events()
    planner = events[6]
    tool = events[7]
    events[6] = tool.model_copy(update={"sequence": 7})
    events[7] = planner.model_copy(update={"sequence": 8})

    with pytest.raises(ValueError, match="no preceding Planner"):
        _build_receipt(events)


def test_agent_core_receipt_rejects_initial_tool_after_judge() -> None:
    events = _live_events()
    events.insert(
        6,
        RuntimeEvent(
            sequence=7,
            phase="initial",
            stage=RuntimeStage.TOOL,
            actor="late-initial-worker",
            action="execute-after-initial-judge",
            status=RuntimeStatus.SUCCESS,
            summary="The initial evidence wave is already closed.",
            task_id="tool.late-initial",
            tool_name="governance_audit",
        ),
    )
    events = [
        event.model_copy(update={"sequence": index})
        for index, event in enumerate(events, 1)
    ]

    with pytest.raises(ValueError, match="evidence wave closed"):
        _build_receipt(events)


def test_agent_core_receipt_rejects_delivery_outside_verification_phase() -> None:
    events = _live_events()
    events[-1] = events[-1].model_copy(update={"phase": "initial"})

    with pytest.raises(ValueError, match="Delivery must run in the verification phase"):
        _build_receipt(events)


def test_agent_core_receipt_allows_optional_stages_between_required_stages() -> None:
    events = _events_for_stages(
        (
            RuntimeStage.INTAKE,
            RuntimeStage.ROUTER,
            RuntimeStage.MEMORY,
            RuntimeStage.PLANNER,
            RuntimeStage.TOOL,
            RuntimeStage.COUNCIL,
            RuntimeStage.JUDGE,
            RuntimeStage.REPAIR,
            RuntimeStage.VERIFY,
            RuntimeStage.DELIVERY,
        )
    )

    receipt = _build_receipt(events)

    verify_agent_core_execution_receipt(receipt, events=events)


def test_agent_core_receipt_rejects_non_contiguous_event_sequences() -> None:
    events = _live_events()
    events[2] = events[2].model_copy(update={"sequence": 99})

    with pytest.raises(ValueError, match="contiguous and 1-based"):
        _build_receipt(events)


def test_agent_core_receipt_rejects_unsuccessful_control_chain() -> None:
    events = _live_events()
    events[-2] = events[-2].model_copy(update={"status": RuntimeStatus.ERROR})

    with pytest.raises(ValueError, match="successful terminal event: judge"):
        _build_receipt(events)


def test_agent_core_receipt_allows_tool_failure_only_with_fail_closed_decision() -> (
    None
):
    events = _live_events()
    events[2] = events[2].model_copy(update={"status": RuntimeStatus.ERROR})

    with pytest.raises(
        ValueError, match="tool failure cannot terminate with Gate PASS"
    ):
        _build_receipt(events)

    receipt = build_agent_core_execution_receipt(
        run_id="authorized-run-001",
        events=events,
        runtime_trace_sha256="a" * 64,
        initial_gate_result_sha256="b" * 64,
        final_gate_result_sha256="c" * 64,
        dynamic_leader_plan_sha256="d" * 64,
        planner_backend="deterministic-leader-v1",
        council_backend="deterministic-evidence-council-v1",
        model_call_count=0,
        tool_call_count=3,
        dynamic_task_count=1,
        final_gate_decision=GateDecision.DEFER,
    )

    verify_agent_core_execution_receipt(receipt, events=events)
    assert receipt.tool_error_event_count == 1
    assert receipt.final_gate_decision is GateDecision.DEFER

    tampered = receipt.model_dump(mode="json")
    tampered["final_gate_decision"] = "PASS"
    stable = dict(tampered)
    stable.pop("receipt_sha256")
    tampered["receipt_sha256"] = hashlib.sha256(
        canonical_json_bytes(stable)
    ).hexdigest()
    with pytest.raises(
        ValueError, match="tool failure cannot terminate with Gate PASS"
    ):
        AgentCoreExecutionReceipt.model_validate(tampered)


@pytest.mark.parametrize("stage", [RuntimeStage.TOOL, RuntimeStage.COUNCIL])
@pytest.mark.parametrize("status", [RuntimeStatus.QUEUED, RuntimeStatus.RUNNING])
def test_agent_core_receipt_cannot_seal_unfinished_required_stage(
    stage: RuntimeStage,
    status: RuntimeStatus,
) -> None:
    events = _live_events()
    index = max(index for index, event in enumerate(events) if event.stage is stage)
    events[index] = events[index].model_copy(update={"status": status})

    with pytest.raises(
        ValueError,
        match=f"required stage lacks a terminal event: {stage.value}",
    ):
        build_agent_core_execution_receipt(
            run_id="authorized-run-001",
            events=events,
            runtime_trace_sha256="a" * 64,
            initial_gate_result_sha256="b" * 64,
            final_gate_result_sha256="c" * 64,
            dynamic_leader_plan_sha256="d" * 64,
            planner_backend="deterministic-leader-v1",
            council_backend="deterministic-evidence-council-v1",
            model_call_count=0,
            tool_call_count=3,
            dynamic_task_count=1,
            final_gate_decision=GateDecision.DEFER,
        )


@pytest.mark.parametrize("stage", [RuntimeStage.TOOL, RuntimeStage.COUNCIL])
@pytest.mark.parametrize(
    "status",
    [RuntimeStatus.WARNING, RuntimeStatus.SKIPPED],
)
def test_agent_core_gate_pass_requires_successful_tool_and_council_terminal(
    stage: RuntimeStage,
    status: RuntimeStatus,
) -> None:
    events = _live_events()
    index = max(index for index, event in enumerate(events) if event.stage is stage)
    events[index] = events[index].model_copy(update={"status": status})

    with pytest.raises(
        ValueError,
        match=(
            "Gate PASS requires successful Tool invocations"
            if stage is RuntimeStage.TOOL
            else f"Gate PASS requires successful terminal stages: {stage.value}"
        ),
    ):
        _build_receipt(events)

    receipt = build_agent_core_execution_receipt(
        run_id="authorized-run-001",
        events=events,
        runtime_trace_sha256="a" * 64,
        initial_gate_result_sha256="b" * 64,
        final_gate_result_sha256="c" * 64,
        dynamic_leader_plan_sha256="d" * 64,
        planner_backend="deterministic-leader-v1",
        council_backend="deterministic-evidence-council-v1",
        model_call_count=0,
        tool_call_count=3,
        dynamic_task_count=1,
        final_gate_decision=GateDecision.DEFER,
    )
    verify_agent_core_execution_receipt(receipt, events=events)


def test_agent_core_receipt_binds_tool_and_dynamic_call_counts() -> None:
    events = _live_events()

    with pytest.raises(ValueError, match="diverged from tool_call_count"):
        build_agent_core_execution_receipt(
            run_id="authorized-run-001",
            events=events,
            runtime_trace_sha256="a" * 64,
            initial_gate_result_sha256="b" * 64,
            final_gate_result_sha256="c" * 64,
            dynamic_leader_plan_sha256="d" * 64,
            planner_backend="deterministic-leader-v1",
            council_backend="deterministic-evidence-council-v1",
            model_call_count=0,
            tool_call_count=4,
            dynamic_task_count=1,
            final_gate_decision=GateDecision.DEFER,
        )

    with pytest.raises(ValueError, match="diverged from dynamic_task_count"):
        build_agent_core_execution_receipt(
            run_id="authorized-run-001",
            events=events,
            runtime_trace_sha256="a" * 64,
            initial_gate_result_sha256="b" * 64,
            final_gate_result_sha256="c" * 64,
            dynamic_leader_plan_sha256="d" * 64,
            planner_backend="deterministic-leader-v1",
            council_backend="deterministic-evidence-council-v1",
            model_call_count=0,
            tool_call_count=3,
            dynamic_task_count=2,
            final_gate_decision=GateDecision.DEFER,
        )


def test_agent_core_tool_event_requires_traceable_invocation_identity() -> None:
    events = _live_events()
    events[2] = events[2].model_copy(update={"task_id": None})

    with pytest.raises(ValueError, match="requires task_id and tool_name bindings"):
        _build_receipt(events)


@pytest.mark.parametrize(
    "identity_update",
    [
        {"tool_name": "drifted-tool"},
        {"phase": "verification"},
    ],
)
def test_agent_core_rejects_reused_tool_task_identity_drift(
    identity_update: dict[str, str],
) -> None:
    events = _live_events()
    first_tool = events[2]
    events[3] = events[3].model_copy(
        update={
            "task_id": first_tool.task_id,
            "tool_name": first_tool.tool_name,
            **identity_update,
        }
    )

    with pytest.raises(ValueError, match="Tool invocation identity drifted"):
        _build_receipt(events)
