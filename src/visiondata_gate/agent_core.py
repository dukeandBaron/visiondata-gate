"""Production Agent-core contracts shared by adapters and the product service.

This module deliberately contains no fixtures, test doubles, benchmark labels,
or provider-specific transport code.  Data adapters emit live runtime signals;
the product layer persists those signals and seals one execution receipt.
"""

from __future__ import annotations

from collections.abc import Callable, Sequence
import hashlib
import hmac
from typing import Literal

from pydantic import Field, model_validator

from .contracts import GateDecision
from .evidence import canonical_json_bytes
from .product_models import ProductModel
from .runtime_models import RuntimeEvent, RuntimeStage, RuntimeStatus


class AgentRuntimeSignal(ProductModel):
    """One live, source-neutral signal emitted while the Agent core executes."""

    phase: Literal["system", "initial", "verification"]
    stage: RuntimeStage
    actor: str = Field(min_length=1)
    action: str = Field(min_length=1)
    status: RuntimeStatus
    summary: str = Field(min_length=1)
    task_id: str | None = None
    tool_name: str | None = None
    duration_ms: float = Field(default=0.0, ge=0.0)
    evidence_refs: list[str] = Field(default_factory=list)


AgentRuntimeSignalSink = Callable[[AgentRuntimeSignal], None]


_REQUIRED_AGENT_CORE_STAGES = (
    RuntimeStage.INTAKE,
    RuntimeStage.PLANNER,
    RuntimeStage.TOOL,
    RuntimeStage.COUNCIL,
    RuntimeStage.JUDGE,
    RuntimeStage.DELIVERY,
)

_SUCCESS_REQUIRED_AGENT_CORE_STAGES = (
    RuntimeStage.INTAKE,
    RuntimeStage.PLANNER,
    RuntimeStage.JUDGE,
    RuntimeStage.DELIVERY,
)

_TERMINAL_RUNTIME_STATUSES = {
    RuntimeStatus.SUCCESS,
    RuntimeStatus.WARNING,
    RuntimeStatus.ERROR,
    RuntimeStatus.SKIPPED,
}


def _required_stage_first_appearances(
    stages: Sequence[RuntimeStage],
) -> tuple[RuntimeStage, ...]:
    """Return required stages in first-observed order, ignoring optional stages."""

    seen: set[RuntimeStage] = set()
    first_appearances: list[RuntimeStage] = []
    for stage in stages:
        if stage in _REQUIRED_AGENT_CORE_STAGES and stage not in seen:
            seen.add(stage)
            first_appearances.append(stage)
    return tuple(first_appearances)


def _stage_terminal_statuses(
    events: Sequence[RuntimeEvent],
) -> dict[RuntimeStage, RuntimeStatus]:
    """Return the last observed status for every required Agent-core stage."""

    statuses: dict[RuntimeStage, RuntimeStatus] = {}
    for event in events:
        if event.stage in _REQUIRED_AGENT_CORE_STAGES:
            statuses[event.stage] = event.status
    return statuses


def _tool_call_terminal_events(
    events: Sequence[RuntimeEvent],
) -> dict[str, RuntimeEvent]:
    """Return the last signal for every bound Tool invocation."""

    terminal_by_task: dict[str, RuntimeEvent] = {}
    identity_by_task: dict[str, tuple[str, str]] = {}
    for event in events:
        if event.stage is not RuntimeStage.TOOL:
            continue
        if not event.task_id or not event.tool_name:
            raise ValueError(
                "agent-core Tool event requires task_id and tool_name bindings"
            )
        identity = (event.phase, event.tool_name)
        previous_identity = identity_by_task.get(event.task_id)
        if previous_identity is not None and previous_identity != identity:
            raise ValueError(
                "agent-core Tool invocation identity drifted across live events"
            )
        identity_by_task[event.task_id] = identity
        terminal_by_task[event.task_id] = event
    return terminal_by_task


def _validate_tool_causality(events: Sequence[RuntimeEvent]) -> None:
    """Require every Tool signal to belong to an open Planner evidence wave."""

    latest_planner: dict[str, int] = {}
    closed_wave: dict[str, bool] = {}
    for index, event in enumerate(events):
        phase = event.phase
        if event.stage is RuntimeStage.PLANNER:
            latest_planner[phase] = index
            closed_wave[phase] = False
        elif event.stage in {RuntimeStage.COUNCIL, RuntimeStage.JUDGE}:
            if phase in latest_planner:
                closed_wave[phase] = True
        elif event.stage is RuntimeStage.TOOL:
            if phase not in latest_planner:
                raise ValueError(
                    "agent-core Tool invocation has no preceding Planner in its phase"
                )
            if closed_wave.get(phase, False):
                raise ValueError(
                    "agent-core Tool invocation occurred after its evidence wave closed"
                )


def _validate_live_event_contract(
    events: Sequence[RuntimeEvent],
    *,
    final_gate_decision: GateDecision,
    tool_call_count: int,
    dynamic_task_count: int,
) -> None:
    """Fail closed on malformed ordering, unfinished control stages, or false PASS."""

    event_list = list(events)
    if not event_list:
        raise ValueError("agent-core receipt cannot seal an empty event chain")
    expected_sequences = list(range(1, len(event_list) + 1))
    observed_sequences = [event.sequence for event in event_list]
    if observed_sequences != expected_sequences:
        raise ValueError("agent-core event sequences must be contiguous and 1-based")

    observed_required = _required_stage_first_appearances(
        [event.stage for event in event_list]
    )
    if len(observed_required) != len(_REQUIRED_AGENT_CORE_STAGES):
        raise ValueError("agent-core receipt cannot seal an incomplete stage chain")
    if observed_required != _REQUIRED_AGENT_CORE_STAGES:
        raise ValueError("agent-core required-stage first appearances are out of order")

    delivery_started = False
    for event in event_list:
        if event.stage is RuntimeStage.DELIVERY and event.phase != "verification":
            raise ValueError("agent-core Delivery must run in the verification phase")
        if delivery_started and event.stage is not RuntimeStage.DELIVERY:
            raise ValueError(
                "agent-core Delivery is terminal; later non-Delivery work is forbidden"
            )
        if event.stage is RuntimeStage.DELIVERY:
            delivery_started = True

    # Validate the stable identity of a Tool invocation before phase-local
    # causality.  Otherwise a drifted task can be misreported as merely missing
    # a Planner in its newly forged phase.
    terminal_tool_events = _tool_call_terminal_events(event_list)
    _validate_tool_causality(event_list)

    terminal_statuses = _stage_terminal_statuses(event_list)
    unfinished = [
        stage.value
        for stage in _SUCCESS_REQUIRED_AGENT_CORE_STAGES
        if terminal_statuses.get(stage) is not RuntimeStatus.SUCCESS
    ]
    if unfinished:
        raise ValueError(
            "agent-core control stage lacks a successful terminal event: "
            + ", ".join(unfinished)
        )

    nonterminal = [
        stage.value
        for stage in _REQUIRED_AGENT_CORE_STAGES
        if terminal_statuses.get(stage) not in _TERMINAL_RUNTIME_STATUSES
    ]
    if nonterminal:
        raise ValueError(
            "agent-core required stage lacks a terminal event: "
            + ", ".join(nonterminal)
        )

    unfinished_tools = [
        task_id
        for task_id, event in terminal_tool_events.items()
        if event.status not in _TERMINAL_RUNTIME_STATUSES
    ]
    if unfinished_tools:
        raise ValueError(
            "agent-core Tool invocation lacks a terminal event: "
            + ", ".join(sorted(unfinished_tools))
        )
    if len(terminal_tool_events) != tool_call_count:
        raise ValueError("agent-core Tool event count diverged from tool_call_count")
    observed_dynamic_task_count = sum(
        event.phase == "verification" for event in terminal_tool_events.values()
    )
    if observed_dynamic_task_count != dynamic_task_count:
        raise ValueError(
            "agent-core verification Tool count diverged from dynamic_task_count"
        )

    tool_error_count = sum(
        event.stage is RuntimeStage.TOOL and event.status is RuntimeStatus.ERROR
        for event in event_list
    )
    if tool_error_count and final_gate_decision is GateDecision.PASS:
        raise ValueError("agent-core tool failure cannot terminate with Gate PASS")

    if final_gate_decision is GateDecision.PASS:
        unsuccessful_tool_tasks = [
            task_id
            for task_id, event in terminal_tool_events.items()
            if event.status is not RuntimeStatus.SUCCESS
        ]
        if unsuccessful_tool_tasks:
            raise ValueError(
                "agent-core Gate PASS requires successful Tool invocations: "
                + ", ".join(sorted(unsuccessful_tool_tasks))
            )
        unsuccessful = [
            stage.value
            for stage in _REQUIRED_AGENT_CORE_STAGES
            if terminal_statuses.get(stage) is not RuntimeStatus.SUCCESS
        ]
        if unsuccessful:
            raise ValueError(
                "agent-core Gate PASS requires successful terminal stages: "
                + ", ".join(unsuccessful)
            )


class AgentCoreExecutionReceipt(ProductModel):
    """Sealed proof that the production Agent stages ran through live signals."""

    schema_version: Literal["visiondata-gate.agent-core-execution.v2"] = (
        "visiondata-gate.agent-core-execution.v2"
    )
    run_id: str = Field(min_length=1)
    execution_mode: Literal["authorized_local_readonly"] = "authorized_local_readonly"
    source_kind: Literal["local_authorized_directory"] = "local_authorized_directory"
    signal_capture_mode: Literal["LIVE_CORE_SIGNALS"] = "LIVE_CORE_SIGNALS"
    posthoc_event_synthesis: Literal[False] = False
    trace_materialization_mode: Literal["POST_EXECUTION_FROM_LIVE_SIGNALS"] = (
        "POST_EXECUTION_FROM_LIVE_SIGNALS"
    )
    planner_backend: str = Field(min_length=1)
    council_backend: str = Field(min_length=1)
    policy_judge: Literal["frozen_deterministic"] = "frozen_deterministic"
    model_call_count: int = Field(ge=0)
    tool_call_count: int = Field(ge=0)
    dynamic_task_count: int = Field(ge=0)
    final_gate_decision: GateDecision
    runtime_event_count: int = Field(ge=1)
    runtime_event_chain_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    runtime_trace_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    initial_gate_result_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    final_gate_result_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    dynamic_leader_plan_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    stage_sequence: list[RuntimeStage] = Field(min_length=1)
    required_stage_checks: dict[str, bool]
    required_success_checks: dict[str, bool]
    tool_error_event_count: int = Field(ge=0)
    event_sequence_contract: Literal["contiguous_1_based"] = "contiguous_1_based"
    production_decision_authority: Literal["human_only"] = "human_only"
    receipt_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")

    @model_validator(mode="after")
    def validate_live_stage_contract(self) -> AgentCoreExecutionReceipt:
        required = {stage.value for stage in _REQUIRED_AGENT_CORE_STAGES}
        if set(self.required_stage_checks) != required:
            raise ValueError("agent-core receipt has an unexpected required-stage set")
        if not all(self.required_stage_checks.values()):
            raise ValueError("agent-core receipt cannot seal an incomplete stage chain")
        success_required = {
            stage.value for stage in _SUCCESS_REQUIRED_AGENT_CORE_STAGES
        }
        if set(self.required_success_checks) != success_required:
            raise ValueError("agent-core receipt has an unexpected success-stage set")
        if not all(self.required_success_checks.values()):
            raise ValueError(
                "agent-core receipt cannot seal an unsuccessful control chain"
            )
        if (
            self.tool_error_event_count
            and self.final_gate_decision is GateDecision.PASS
        ):
            raise ValueError("agent-core tool failure cannot terminate with Gate PASS")
        observed_required = _required_stage_first_appearances(self.stage_sequence)
        if len(observed_required) != len(_REQUIRED_AGENT_CORE_STAGES):
            raise ValueError("agent-core receipt cannot seal an incomplete stage chain")
        if observed_required != _REQUIRED_AGENT_CORE_STAGES:
            raise ValueError(
                "agent-core required-stage first appearances are out of order"
            )
        if self.runtime_event_count < len(self.stage_sequence):
            raise ValueError(
                "agent-core event count cannot be smaller than stage sequence"
            )
        return self


def _event_chain_sha256(events: Sequence[RuntimeEvent]) -> str:
    return hashlib.sha256(canonical_json_bytes(list(events))).hexdigest()


def build_agent_core_execution_receipt(
    *,
    run_id: str,
    events: Sequence[RuntimeEvent],
    runtime_trace_sha256: str,
    initial_gate_result_sha256: str,
    final_gate_result_sha256: str,
    dynamic_leader_plan_sha256: str,
    planner_backend: str,
    council_backend: str,
    model_call_count: int,
    tool_call_count: int,
    dynamic_task_count: int,
    final_gate_decision: GateDecision,
) -> AgentCoreExecutionReceipt:
    """Build a receipt only when the live production stage chain is complete."""

    event_list = list(events)
    _validate_live_event_contract(
        event_list,
        final_gate_decision=final_gate_decision,
        tool_call_count=tool_call_count,
        dynamic_task_count=dynamic_task_count,
    )
    stage_sequence = list(dict.fromkeys(event.stage for event in event_list))
    terminal_statuses = _stage_terminal_statuses(event_list)
    stable = {
        "schema_version": "visiondata-gate.agent-core-execution.v2",
        "run_id": run_id,
        "execution_mode": "authorized_local_readonly",
        "source_kind": "local_authorized_directory",
        "signal_capture_mode": "LIVE_CORE_SIGNALS",
        "posthoc_event_synthesis": False,
        "trace_materialization_mode": "POST_EXECUTION_FROM_LIVE_SIGNALS",
        "planner_backend": planner_backend,
        "council_backend": council_backend,
        "policy_judge": "frozen_deterministic",
        "model_call_count": model_call_count,
        "tool_call_count": tool_call_count,
        "dynamic_task_count": dynamic_task_count,
        "final_gate_decision": final_gate_decision,
        "runtime_event_count": len(event_list),
        "runtime_event_chain_sha256": _event_chain_sha256(event_list),
        "runtime_trace_sha256": runtime_trace_sha256,
        "initial_gate_result_sha256": initial_gate_result_sha256,
        "final_gate_result_sha256": final_gate_result_sha256,
        "dynamic_leader_plan_sha256": dynamic_leader_plan_sha256,
        "stage_sequence": stage_sequence,
        "required_stage_checks": {
            stage.value: stage in stage_sequence
            for stage in _REQUIRED_AGENT_CORE_STAGES
        },
        "required_success_checks": {
            stage.value: terminal_statuses.get(stage) is RuntimeStatus.SUCCESS
            for stage in _SUCCESS_REQUIRED_AGENT_CORE_STAGES
        },
        "tool_error_event_count": sum(
            event.stage is RuntimeStage.TOOL and event.status is RuntimeStatus.ERROR
            for event in event_list
        ),
        "event_sequence_contract": "contiguous_1_based",
        "production_decision_authority": "human_only",
    }
    return AgentCoreExecutionReceipt(
        **stable,
        receipt_sha256=hashlib.sha256(canonical_json_bytes(stable)).hexdigest(),
    )


def verify_agent_core_execution_receipt(
    receipt: AgentCoreExecutionReceipt,
    *,
    events: Sequence[RuntimeEvent] | None = None,
) -> None:
    """Fail closed if a persisted receipt or its bound live events drifted."""

    stable = receipt.model_dump(mode="json", exclude={"receipt_sha256"})
    expected = hashlib.sha256(canonical_json_bytes(stable)).hexdigest()
    if not hmac.compare_digest(expected, receipt.receipt_sha256):
        raise ValueError("agent-core execution receipt digest mismatch")
    if events is None:
        return

    event_list = list(events)
    _validate_live_event_contract(
        event_list,
        final_gate_decision=receipt.final_gate_decision,
        tool_call_count=receipt.tool_call_count,
        dynamic_task_count=receipt.dynamic_task_count,
    )
    stage_sequence = list(dict.fromkeys(event.stage for event in event_list))
    terminal_statuses = _stage_terminal_statuses(event_list)
    expected_stage_checks = {
        stage.value: stage in stage_sequence for stage in _REQUIRED_AGENT_CORE_STAGES
    }
    expected_success_checks = {
        stage.value: terminal_statuses.get(stage) is RuntimeStatus.SUCCESS
        for stage in _SUCCESS_REQUIRED_AGENT_CORE_STAGES
    }
    expected_tool_error_count = sum(
        event.stage is RuntimeStage.TOOL and event.status is RuntimeStatus.ERROR
        for event in event_list
    )
    if not (
        receipt.runtime_event_count == len(event_list)
        and hmac.compare_digest(
            receipt.runtime_event_chain_sha256,
            _event_chain_sha256(event_list),
        )
        and receipt.stage_sequence == stage_sequence
        and receipt.required_stage_checks == expected_stage_checks
        and receipt.required_success_checks == expected_success_checks
        and receipt.tool_error_event_count == expected_tool_error_count
    ):
        raise ValueError("agent-core live event binding mismatch")


__all__ = [
    "AgentCoreExecutionReceipt",
    "AgentRuntimeSignal",
    "AgentRuntimeSignalSink",
    "build_agent_core_execution_receipt",
    "verify_agent_core_execution_receipt",
]
