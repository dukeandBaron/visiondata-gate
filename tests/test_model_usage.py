"""Read-only accounting over saved receipts; no real provider request is made."""

from __future__ import annotations

import hashlib
from types import SimpleNamespace

import pytest

from visiondata_gate.agent_core import build_agent_core_execution_receipt
from visiondata_gate.contracts import GateDecision
from visiondata_gate.demo_fixtures import build_fixture_industrial_incident_request
from visiondata_gate.evidence import canonical_json_bytes
from visiondata_gate.incident_model_planner import (
    IncidentModelMode,
    IncidentModelPlan,
    IncidentModelPlannerReceipt,
    IncidentModelUsage,
)
from visiondata_gate.incident_runtime_profile import IncidentRuntimeProfile
from visiondata_gate.industrial_incident import (
    IndustrialGateContext,
    build_industrial_incident_case,
)
from visiondata_gate.model_usage import build_task_model_usage, verify_task_model_usage
from visiondata_gate.network_resilience import HTTPAttemptReceipt, HTTPExchangeReceipt
from visiondata_gate.product_models import DataSourceKind, TaskExecutionStatus
from visiondata_gate.runtime_models import RuntimeEvent, RuntimeStage, RuntimeStatus


def _sha(value):
    return hashlib.sha256(canonical_json_bytes(value)).hexdigest()


def _planner(*, usage=None, mode="shadow", attempts=1, failed=False, local=False):
    offline = mode in {"off", "replay"}
    transport = (
        None
        if offline
        else HTTPExchangeReceipt(
            request_id="fixture-request-0123456789",
            endpoint_id="https://fixture.invalid/v1/chat/completions",
            endpoint_scope="local" if local else "remote",
            method="POST",
            status="HTTP_ERROR"
            if failed
            else "RECOVERED"
            if attempts > 1
            else "SUCCESS",
            request_sha256="a" * 64,
            response_sha256=None if failed else "b" * 64,
            attempts=[
                HTTPAttemptReceipt(
                    attempt=i + 1,
                    status="http_error" if failed or i < attempts - 1 else "success",
                    duration_ms=1,
                    retryable=failed or i < attempts - 1,
                    http_status=503 if failed or i < attempts - 1 else 200,
                )
                for i in range(attempts)
            ],
            attempt_count=attempts,
            retry_count=max(0, attempts - 1),
            circuit_before="closed",
            circuit_after="closed",
        )
    )
    receipt = IncidentModelPlannerReceipt(
        mode=mode,
        status="TRANSPORT_FAILED" if failed else "REJECTED",
        connection_status="REPLAY_ONLY"
        if mode == "replay"
        else "REAL_BACKEND_NOT_CONNECTED"
        if offline or failed
        else "CONTRACT_CONNECTED_LOCAL_TEST"
        if local
        else "REAL_BACKEND_CONNECTED",
        gating_effect="DETERMINISTIC_FALLBACK",
        configured_model="fixture-model",
        config_sha256="c" * 64,
        planner_input_sha256="d" * 64,
        validation_checks={},
        validation_errors=[],
        recommended_worker_order=[],
        applied_worker_order=[],
        model_call_count=0 if offline else 1,
        estimated_input_tokens=999,
        context_budget_tokens=8192,
        transport_receipt=transport,
        usage=IncidentModelUsage(
            **(usage or {}),
            cost_status="NOT_APPLICABLE_REPLAY"
            if mode == "replay"
            else "TOKENS_REPORTED_COST_NOT_COMPUTED"
            if usage
            else "NOT_REPORTED_BY_PROVIDER",
        ),
        receipt_sha256="0" * 64,
    )
    return receipt.model_copy(
        update={
            "receipt_sha256": _sha(
                receipt.model_dump(mode="json", exclude={"receipt_sha256"})
            )
        }
    )


def _case(receipt, *, task_id="task-fixture", revision=1):
    request = build_fixture_industrial_incident_request(revision=revision)
    if receipt is not None:
        request = request.model_copy(
            update={
                "runtime_profile": IncidentRuntimeProfile(
                    planner_mode=receipt.mode,
                    model_profile_id="deepseek-replay"
                    if receipt.mode is IncidentModelMode.REPLAY
                    else "deepseek-chat",
                )
            }
        )
    gate = IndustrialGateContext(
        task_id=task_id,
        gate_final_decision="QUARANTINE",
        task_evidence_sha256="e" * 64,
        industrial_delivery_sha256="f" * 64,
        source_profile_sha256="a" * 64,
        source_authorization_event_sha256="b" * 64,
        source_kind="local_authorized_directory",
        source_authorization_status="ACTIVE",
        dynamic_response_count=0,
        open_work_order_count=1,
        remediation_plan_ids=[],
        model_call_count=0,
    )
    planner = (
        None
        if receipt is None
        else SimpleNamespace(
            plan=lambda **kwargs: IncidentModelPlan(
                receipt=receipt, applied_worker_order=()
            )
        )
    )
    return build_industrial_incident_case(request, gate, model_planner=planner)


class _Service:
    def __init__(self, cases=(), *, core_calls=0, completed=True):
        self.cases = list(cases)
        events = [
            RuntimeEvent(
                sequence=i + 1,
                phase="verification" if stage is RuntimeStage.DELIVERY else "initial",
                stage=stage,
                actor="fixture",
                action="execute",
                status=RuntimeStatus.SUCCESS,
                summary="fixture",
                task_id="tool-1" if stage is RuntimeStage.TOOL else None,
                tool_name="image_quality" if stage is RuntimeStage.TOOL else None,
            )
            for i, stage in enumerate(
                (
                    RuntimeStage.INTAKE,
                    RuntimeStage.PLANNER,
                    RuntimeStage.TOOL,
                    RuntimeStage.COUNCIL,
                    RuntimeStage.JUDGE,
                    RuntimeStage.DELIVERY,
                )
            )
        ]
        self.trace = {
            "run_id": "run-fixture",
            "model_call_count": core_calls,
            "events": [x.model_dump(mode="json") for x in events],
        }
        self.core = build_agent_core_execution_receipt(
            run_id="run-fixture",
            events=events,
            runtime_trace_sha256=_sha(self.trace),
            initial_gate_result_sha256="a" * 64,
            final_gate_result_sha256="b" * 64,
            dynamic_leader_plan_sha256="c" * 64,
            planner_backend="deterministic",
            council_backend="deterministic",
            model_call_count=core_calls,
            tool_call_count=1,
            dynamic_task_count=0,
            final_gate_decision=GateDecision.QUARANTINE,
        )
        self.task = SimpleNamespace(
            task_id="task-fixture",
            workspace_id="workspace-fixture",
            project_id="project-fixture",
            request_sha256="d" * 64,
            trace_sha256=_sha(self.trace),
            evidence_sha256="e" * 64,
            source_kind=DataSourceKind.LOCAL_AUTHORIZED_DIRECTORY,
            execution_status=TaskExecutionStatus.COMPLETED
            if completed
            else TaskExecutionStatus.CREATED,
        )

    def get_task(self, actor_id, task_id):
        if actor_id != "owner" or task_id != self.task.task_id:
            raise PermissionError("no access")
        return self.task

    def list_industrial_incident_cases(self, actor_id, task_id):
        self.get_task(actor_id, task_id)
        return self.cases

    def read_optional_evidence_zip_json(self, actor_id, task_id, member):
        self.get_task(actor_id, task_id)
        assert member == "agent_core_execution_receipt.json"
        return self.core.model_dump(mode="json") if self.core else None

    def read_trace(self, actor_id, task_id):
        self.get_task(actor_id, task_id)
        return self.trace


def _report(service):
    return build_task_model_usage(service, "owner", "task-fixture")


def test_reported_usage_is_read_from_receipt_and_estimate_is_not_spend():
    service = _Service(
        [
            _case(
                _planner(
                    usage={
                        "input_tokens": 120,
                        "output_tokens": 80,
                        "total_tokens": 200,
                    }
                )
            )
        ]
    )
    before = [case.model_dump_json() for case in service.cases]
    report = _report(service)
    verify_task_model_usage(report)
    assert report.summary.logical_model_calls == 1
    assert report.summary.transport_attempts == 1
    assert report.summary.total_tokens == 200
    assert report.summary.usage_completeness == "COMPLETE"
    assert report.summary.cost is None
    assert report.summary.pricing_status == "NOT_CONFIGURED"
    assert before == [case.model_dump_json() for case in service.cases]
    assert "fixture.invalid" not in report.model_dump_json()


@pytest.mark.parametrize(
    "usage, completeness", [(None, "NOT_REPORTED"), ({"input_tokens": 120}, "PARTIAL")]
)
def test_missing_provider_tokens_are_never_filled_with_estimates(usage, completeness):
    report = _report(_Service([_case(_planner(usage=usage))]))
    assert report.summary.usage_completeness == completeness
    assert report.summary.total_tokens is None
    assert report.summary.output_tokens is None
    assert report.summary.unreported_receipt_count == 1


def test_replay_and_local_contract_do_not_count_as_remote_usage():
    cases = [
        _case(_planner(mode="replay")),
        _case(_planner(local=True, usage={"total_tokens": 100}), revision=2),
    ]
    report = _report(_Service(cases))
    assert report.summary.logical_model_calls == 0
    assert report.summary.total_tokens == 0
    assert report.summary.local_model_calls == 1
    assert report.summary.replay_receipt_count == 1
    assert report.summary.usage_completeness == "NOT_APPLICABLE"


def test_failed_three_attempt_exchange_is_one_logical_call_without_known_tokens():
    report = _report(_Service([_case(_planner(attempts=3, failed=True))]))
    assert report.summary.logical_model_calls == 1
    assert report.summary.transport_attempts == 3
    assert report.summary.successful_responses == 0
    assert report.summary.total_tokens is None


def test_recovered_exchange_reports_final_response_but_not_total_retry_spend():
    report = _report(
        _Service(
            [
                _case(
                    _planner(
                        attempts=2,
                        usage={
                            "input_tokens": 120,
                            "output_tokens": 80,
                            "total_tokens": 200,
                        },
                    )
                )
            ]
        )
    )
    assert report.summary.logical_model_calls == 1
    assert report.summary.transport_attempts == 2
    assert report.summary.usage_completeness == "PARTIAL"
    assert report.summary.total_tokens is None
    assert report.records[-1].total_tokens == 200


def test_verified_core_zero_differs_from_unrun_or_missing_evidence():
    report = _report(_Service())
    assert report.summary.call_status == "ZERO_CALLS"
    assert report.summary.logical_model_calls == 0
    missing = _Service()
    missing.core = None
    assert _report(missing).summary.call_status == "UNKNOWN"
    assert _report(_Service(completed=False)).summary.logical_model_calls is None


def test_scope_denial_propagates_before_loading_any_usage():
    with pytest.raises(PermissionError):
        build_task_model_usage(_Service(), "other-actor", "task-fixture")
    report = _report(_Service([_case(_planner(), task_id="other-task")]))
    assert report.summary.call_status == "UNKNOWN"
    assert report.summary.usage_completeness == "UNAVAILABLE"


def test_tampered_case_never_counts_as_successful_usage():
    case = _case(_planner(usage={"total_tokens": 200}))
    case.model_planner_receipt.usage.total_tokens = 1
    report = _report(_Service([case]))
    assert report.summary.logical_model_calls is None
    assert report.summary.successful_responses is None
    assert report.summary.usage_completeness == "UNAVAILABLE"


def test_invalid_transport_count_and_inconsistent_usage_are_unavailable():
    receipt = _planner(
        usage={"input_tokens": 120, "output_tokens": 80, "total_tokens": 1}
    )
    report = _report(_Service([_case(receipt)]))
    assert report.summary.usage_completeness == "UNAVAILABLE"


def test_signed_but_inconsistent_transport_metadata_is_not_accepted():
    receipt = _planner(
        usage={"input_tokens": 10, "output_tokens": 2, "total_tokens": 12}
    )
    receipt.transport_receipt.attempt_count = 9
    receipt = receipt.model_copy(
        update={
            "receipt_sha256": _sha(
                receipt.model_dump(mode="json", exclude={"receipt_sha256"})
            )
        }
    )
    assert (
        _report(_Service([_case(receipt)])).summary.usage_completeness == "UNAVAILABLE"
    )


def test_nonzero_core_without_per_request_usage_remains_unknown():
    report = _report(_Service(core_calls=2))
    assert report.summary.logical_model_calls is None
    assert report.summary.total_tokens is None
    assert report.summary.call_status == "UNKNOWN"


def test_changed_usage_report_fails_its_own_digest():
    report = _report(_Service())
    report.summary.total_tokens = 55
    with pytest.raises(ValueError, match="digest"):
        verify_task_model_usage(report)


def test_copied_remote_receipt_is_ambiguous_not_two_verified_calls():
    receipt = _planner(
        usage={"input_tokens": 10, "output_tokens": 2, "total_tokens": 12}
    )
    report = _report(_Service([_case(receipt, revision=1), _case(receipt, revision=2)]))
    assert report.summary.usage_completeness == "UNAVAILABLE"
    assert report.summary.logical_model_calls is None
