"""Read-only model accounting from verified saved task and planner evidence.

Provider token reports are distinct from estimates and billing. A successful
retry reports the final response only; missing earlier-attempt usage is unknown.
This module never calls a provider and never changes historical receipts.
"""

from __future__ import annotations

import hashlib
import hmac
from typing import TYPE_CHECKING, Literal

from pydantic import Field

from .agent_core import AgentCoreExecutionReceipt, verify_agent_core_execution_receipt
from .evidence import canonical_json_bytes
from .incident_model_planner import (
    IncidentModelMode,
    verify_incident_model_planner_receipt,
)
from .industrial_incident import IndustrialIncidentCase, verify_industrial_incident_case
from .product_models import DataSourceKind, ProductModel, TaskExecutionStatus
from .runtime_models import RuntimeEvent
from .task_store import ProductStoreError

if TYPE_CHECKING:
    from .product_service import ProductService

UsageCompleteness = Literal[
    "COMPLETE", "PARTIAL", "NOT_REPORTED", "NOT_APPLICABLE", "UNAVAILABLE"
]


class ModelUsageRecord(ProductModel):
    source_kind: Literal["TASK_CORE", "INCIDENT_CASE", "INCIDENT_PLANNER"]
    case_id: str | None = None
    case_sha256: str | None = Field(default=None, pattern=r"^[0-9a-f]{64}$")
    source_receipt_sha256: str | None = Field(default=None, pattern=r"^[0-9a-f]{64}$")
    transport_receipt_sha256: str | None = Field(
        default=None, pattern=r"^[0-9a-f]{64}$"
    )
    origin: Literal["REMOTE", "LOCAL", "REPLAY", "ZERO_CALLS", "UNKNOWN"]
    planner_mode: str | None = None
    outcome: Literal[
        "NO_CALL", "RESPONSE_RECORDED", "TRANSPORT_FAILED", "CIRCUIT_BLOCKED", "UNKNOWN"
    ]
    logical_model_calls: int | None = Field(default=None, ge=0)
    transport_attempts: int | None = Field(default=None, ge=0)
    successful_responses: int | None = Field(default=None, ge=0)
    input_tokens: int | None = Field(default=None, ge=0)
    output_tokens: int | None = Field(default=None, ge=0)
    total_tokens: int | None = Field(default=None, ge=0)
    estimated_input_tokens: int | None = Field(default=None, ge=0)
    unreported_attempt_count: int = Field(default=0, ge=0)
    usage_completeness: UsageCompleteness
    token_scope: Literal[
        "PROVIDER_FINAL_RESPONSE", "PROVEN_NO_REMOTE_CALL", "UNAVAILABLE"
    ]


class ModelUsageSummary(ProductModel):
    accounting_scope: Literal["TASK_CORE_AND_SAVED_INCIDENT_PLANNERS_REMOTE_ONLY"] = (
        "TASK_CORE_AND_SAVED_INCIDENT_PLANNERS_REMOTE_ONLY"
    )
    call_status: Literal["ZERO_CALLS", "CALLS_RECORDED", "UNKNOWN"]
    logical_model_calls: int | None = Field(default=None, ge=0)
    transport_attempts: int | None = Field(default=None, ge=0)
    successful_responses: int | None = Field(default=None, ge=0)
    local_model_calls: int | None = Field(default=None, ge=0)
    replay_receipt_count: int = Field(default=0, ge=0)
    input_tokens: int | None = Field(default=None, ge=0)
    output_tokens: int | None = Field(default=None, ge=0)
    total_tokens: int | None = Field(default=None, ge=0)
    usage_completeness: UsageCompleteness
    unreported_receipt_count: int = Field(default=0, ge=0)
    unreported_attempt_count: int = Field(default=0, ge=0)
    pricing_status: Literal["NOT_CONFIGURED"] = "NOT_CONFIGURED"
    cost: None = None
    currency: None = None


class TaskModelUsageReport(ProductModel):
    schema_version: Literal["visiondata-gate.task-model-usage.v1"] = (
        "visiondata-gate.task-model-usage.v1"
    )
    task_id: str
    workspace_id: str
    project_id: str
    task_request_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    task_evidence_sha256: str | None = Field(default=None, pattern=r"^[0-9a-f]{64}$")
    task_trace_sha256: str | None = Field(default=None, pattern=r"^[0-9a-f]{64}$")
    records: list[ModelUsageRecord]
    summary: ModelUsageSummary
    unavailable_reasons: list[str] = Field(default_factory=list)
    includes_secrets_or_prompts: Literal[False] = False
    estimates_counted_as_usage: Literal[False] = False
    boundary_notice: str = (
        "Saved task-core and incident-planner evidence only; not an account-wide "
        "provider invoice. Local contracts and replay are excluded from remote "
        "totals. Tokens are provider-reported, never estimated; retries may leave "
        "unreported usage. Unknown usage and all costs remain null."
    )
    receipt_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")


def _sha(value: object) -> str:
    return hashlib.sha256(canonical_json_bytes(value)).hexdigest()


def _zero_record(
    *, kind: str, digest: str, case=None, replay=False
) -> ModelUsageRecord:
    return ModelUsageRecord(
        source_kind=kind,
        source_receipt_sha256=digest,
        case_id=case.case_id if case else None,
        case_sha256=case.case_sha256 if case else None,
        origin="REPLAY" if replay else "ZERO_CALLS",
        outcome="NO_CALL",
        logical_model_calls=0,
        transport_attempts=0,
        successful_responses=0,
        input_tokens=0,
        output_tokens=0,
        total_tokens=0,
        usage_completeness="NOT_APPLICABLE",
        token_scope="PROVEN_NO_REMOTE_CALL",
    )


def _planner_record(case: IndustrialIncidentCase) -> ModelUsageRecord:
    receipt = case.model_planner_receipt
    if receipt is None:
        if case.external_model_call_count:
            raise ValueError("missing planner receipt")
        return _zero_record(kind="INCIDENT_CASE", digest=case.case_sha256, case=case)
    verify_incident_model_planner_receipt(receipt)
    if (
        receipt.mode in {IncidentModelMode.OFF, IncidentModelMode.REPLAY}
        or receipt.model_call_count == 0
    ):
        if receipt.model_call_count or receipt.transport_receipt is not None:
            raise ValueError("offline receipt contains a transport invocation")
        record = _zero_record(
            kind="INCIDENT_PLANNER",
            digest=receipt.receipt_sha256,
            case=case,
            replay=receipt.mode is IncidentModelMode.REPLAY,
        )
        return record.model_copy(
            update={
                "planner_mode": receipt.mode.value,
                "estimated_input_tokens": receipt.estimated_input_tokens,
            }
        )
    exchange = receipt.transport_receipt
    if exchange is None:
        return ModelUsageRecord(
            source_kind="INCIDENT_PLANNER",
            case_id=case.case_id,
            case_sha256=case.case_sha256,
            source_receipt_sha256=receipt.receipt_sha256,
            origin="UNKNOWN",
            outcome="UNKNOWN",
            usage_completeness="UNAVAILABLE",
            token_scope="UNAVAILABLE",
        )
    attempts = exchange.attempts
    if (
        exchange.attempt_count != len(attempts)
        or exchange.retry_count != max(0, len(attempts) - 1)
        or [item.attempt for item in attempts] != list(range(1, len(attempts) + 1))
    ):
        raise ValueError("transport attempt counts are inconsistent")
    success = exchange.status in {"SUCCESS", "RECOVERED"}
    if receipt.usage.cost_status == "NOT_APPLICABLE_REPLAY":
        raise ValueError("live exchange carries replay-only usage")
    expected_connection = (
        "CONTRACT_CONNECTED_LOCAL_TEST"
        if exchange.endpoint_scope == "local"
        else "REAL_BACKEND_CONNECTED"
    )
    if success and receipt.connection_status != expected_connection:
        raise ValueError("transport scope contradicts planner connection identity")
    if success and (
        not attempts
        or attempts[-1].status != "success"
        or exchange.response_sha256 is None
    ):
        raise ValueError("transport success lacks a final response")
    if not success and any(item.status == "success" for item in attempts):
        raise ValueError("transport terminal status contradicts its attempts")
    if not attempts and exchange.status != "CIRCUIT_OPEN":
        raise ValueError("empty transport has no circuit-open proof")
    if len([item for item in attempts if item.status == "success"]) > 1:
        raise ValueError("one logical exchange has multiple terminal successes")
    if (receipt.status == "TRANSPORT_FAILED") == success:
        raise ValueError("planner and transport outcomes disagree")
    tokens = {
        name: getattr(receipt.usage, name)
        for name in ("input_tokens", "output_tokens", "total_tokens")
    }
    if not success and any(value is not None for value in tokens.values()):
        raise ValueError("failed transport cannot authenticate provider usage")
    if (
        all(value is not None for value in tokens.values())
        and tokens["input_tokens"] + tokens["output_tokens"] != tokens["total_tokens"]
    ):
        raise ValueError("provider token counts are inconsistent")
    if tokens["total_tokens"] is not None and any(
        value is not None and value > tokens["total_tokens"]
        for name, value in tokens.items()
        if name != "total_tokens"
    ):
        raise ValueError("provider component exceeds reported total")
    if not attempts:
        record = _zero_record(
            kind="INCIDENT_PLANNER", digest=receipt.receipt_sha256, case=case
        )
        return record.model_copy(
            update={
                "outcome": "CIRCUIT_BLOCKED",
                "transport_receipt_sha256": _sha(exchange.model_dump(mode="json")),
            }
        )
    known = sum(value is not None for value in tokens.values())
    completeness = (
        "COMPLETE"
        if known == 3 and len(attempts) == 1
        else "PARTIAL"
        if known
        else "NOT_REPORTED"
    )
    return ModelUsageRecord(
        source_kind="INCIDENT_PLANNER",
        case_id=case.case_id,
        case_sha256=case.case_sha256,
        source_receipt_sha256=receipt.receipt_sha256,
        transport_receipt_sha256=_sha(exchange.model_dump(mode="json")),
        origin="LOCAL" if exchange.endpoint_scope == "local" else "REMOTE",
        planner_mode=receipt.mode.value,
        outcome="RESPONSE_RECORDED" if success else "TRANSPORT_FAILED",
        logical_model_calls=1,
        transport_attempts=len(attempts),
        successful_responses=int(success),
        **tokens,
        estimated_input_tokens=receipt.estimated_input_tokens,
        unreported_attempt_count=len(attempts) - int(success),
        usage_completeness=completeness,
        token_scope="PROVIDER_FINAL_RESPONSE",
    )


def _core_record(service, actor_id: str, task) -> ModelUsageRecord:
    payload = service.read_optional_evidence_zip_json(
        actor_id, task.task_id, "agent_core_execution_receipt.json"
    )
    if payload is None:
        raise ValueError("core receipt missing")
    receipt = AgentCoreExecutionReceipt.model_validate(payload)
    trace = service.read_trace(actor_id, task.task_id)
    verify_agent_core_execution_receipt(
        receipt,
        events=[RuntimeEvent.model_validate(event) for event in trace["events"]],
    )
    if (
        task.source_kind is not DataSourceKind.LOCAL_AUTHORIZED_DIRECTORY
        or receipt.run_id != trace["run_id"]
        or receipt.runtime_trace_sha256 != task.trace_sha256
        or receipt.model_call_count != trace["model_call_count"]
    ):
        raise ValueError("core receipt lost its task/trace binding")
    if receipt.model_call_count == 0:
        return _zero_record(kind="TASK_CORE", digest=receipt.receipt_sha256)
    # Core receipts carry a total counter, not per-request usage or origin.
    # It cannot be added to incident tokens or represented as verified zero.
    return ModelUsageRecord(
        source_kind="TASK_CORE",
        source_receipt_sha256=receipt.receipt_sha256,
        origin="UNKNOWN",
        outcome="UNKNOWN",
        usage_completeness="UNAVAILABLE",
        token_scope="UNAVAILABLE",
    )


def _summary(records: list[ModelUsageRecord], reasons: list[str]) -> ModelUsageSummary:
    remote = [record for record in records if record.origin == "REMOTE"]
    unknown = (
        bool(reasons)
        or any(record.origin == "UNKNOWN" for record in records)
        or not records
    )
    counts = {
        name: None if unknown else sum(getattr(record, name) or 0 for record in remote)
        for name in (
            "logical_model_calls",
            "transport_attempts",
            "successful_responses",
        )
    }
    tokens: dict[str, int | None] = {}
    for name in ("input_tokens", "output_tokens", "total_tokens"):
        tokens[name] = (
            None
            if unknown
            or any(
                getattr(record, name) is None or record.unreported_attempt_count
                for record in remote
            )
            else sum(getattr(record, name) for record in remote)
        )
    if unknown:
        completeness = "UNAVAILABLE"
    elif not remote:
        completeness = "NOT_APPLICABLE"
    elif all(record.usage_completeness == "COMPLETE" for record in remote):
        completeness = "COMPLETE"
    elif any(
        any(getattr(record, name) is not None for name in tokens) for record in remote
    ):
        completeness = "PARTIAL"
    else:
        completeness = "NOT_REPORTED"
    return ModelUsageSummary(
        call_status="UNKNOWN"
        if unknown
        else "CALLS_RECORDED"
        if counts["logical_model_calls"]
        else "ZERO_CALLS",
        **counts,
        **tokens,
        usage_completeness=completeness,
        local_model_calls=None
        if unknown
        else sum(
            record.logical_model_calls or 0
            for record in records
            if record.origin == "LOCAL"
        ),
        replay_receipt_count=sum(record.origin == "REPLAY" for record in records),
        unreported_receipt_count=sum(
            record.usage_completeness != "COMPLETE" for record in remote
        ),
        unreported_attempt_count=sum(
            record.unreported_attempt_count for record in remote
        ),
    )


def build_task_model_usage(
    service: ProductService, actor_id: str, task_id: str
) -> TaskModelUsageReport:
    """Authorize first, then project only verified saved evidence; never execute."""
    # Runtime import avoids a cycle when ProductService exposes this projection.
    from .product_service import ProductServiceError

    task = service.get_task(actor_id, task_id)
    records: list[ModelUsageRecord] = []
    reasons: list[str] = []
    if task.execution_status is not TaskExecutionStatus.COMPLETED:
        reasons.append("TASK_NOT_COMPLETED")
    else:
        try:
            records.append(_core_record(service, actor_id, task))
        except (
            ProductServiceError,
            ProductStoreError,
            OSError,
            ValueError,
            KeyError,
            TypeError,
        ):
            reasons.append("TASK_CORE_EVIDENCE_UNAVAILABLE")
        try:
            cases = service.list_industrial_incident_cases(actor_id, task_id)
            seen: dict[str, str] = {}
            seen_invocations: set[str] = set()
            for case in sorted(
                cases, key=lambda item: (item.case_version, item.case_id)
            ):
                verify_industrial_incident_case(case)
                if (
                    case.task_id != task_id
                    or case.gate_context.task_id != task_id
                    or case.gate_context.task_evidence_sha256 != task.evidence_sha256
                    or case.gate_context.source_kind != task.source_kind.value
                ):
                    raise ValueError("incident lost task scope binding")
                if case.case_id in seen:
                    if seen[case.case_id] != case.case_sha256:
                        raise ValueError("case identity collision")
                    continue
                seen[case.case_id] = case.case_sha256
                record = _planner_record(case)
                if record.origin in {"REMOTE", "LOCAL"}:
                    if record.source_receipt_sha256 in seen_invocations:
                        raise ValueError(
                            "one saved invocation was copied between cases"
                        )
                    seen_invocations.add(record.source_receipt_sha256)
                records.append(record)
        except (
            ProductServiceError,
            ProductStoreError,
            OSError,
            ValueError,
            KeyError,
            TypeError,
        ):
            reasons.append("INCIDENT_EVIDENCE_UNAVAILABLE")
    report = TaskModelUsageReport(
        task_id=task.task_id,
        workspace_id=task.workspace_id,
        project_id=task.project_id,
        task_request_sha256=task.request_sha256,
        task_evidence_sha256=task.evidence_sha256,
        task_trace_sha256=task.trace_sha256,
        records=records,
        summary=_summary(records, reasons),
        unavailable_reasons=reasons,
        receipt_sha256="0" * 64,
    )
    return report.model_copy(
        update={
            "receipt_sha256": _sha(
                report.model_dump(mode="json", exclude={"receipt_sha256"})
            )
        }
    )


def verify_task_model_usage(report: TaskModelUsageReport) -> None:
    expected = _sha(report.model_dump(mode="json", exclude={"receipt_sha256"}))
    if not hmac.compare_digest(expected, report.receipt_sha256):
        raise ValueError("model usage projection digest mismatch")
    if report.summary != _summary(report.records, report.unavailable_reasons):
        raise ValueError("model usage summary does not match its evidence records")
