"""Fixed-denominator end-to-end benchmark for industrial incident contracts.

IndustrialIncidentBench v1 exercises the existing deterministic incident case,
human-decision, immutable resume, Worker receipt, model-plan validation, and
CAPA child-case contracts.  Every input is a labelled local fixture.  The
benchmark performs no external model call, connects to no factory system, and
never grants production-release or equipment-control authority.
"""

from __future__ import annotations

import hashlib
import hmac
import json
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .demo_fixtures import build_fixture_industrial_incident_request
from .evidence import canonical_json_bytes, sha256_file, write_canonical_json
from .incident_control_plane import (
    build_incident_control_plane,
    check_incident_worker_authority,
    verify_incident_control_plane,
)
from .incident_model_planner import (
    IncidentModelMode,
    IncidentModelPlanner,
    IncidentModelPlannerConfig,
)
from .incident_runtime_profile import IncidentRuntimeProfile
from .industrial_incident import (
    IncidentCapaEvidence,
    IncidentHumanDecision,
    IncidentLoopStopReason,
    IncidentWorkerExecutionError,
    IncidentWorkerReceipt,
    IncidentWorkerRegistry,
    IndustrialGateContext,
    IndustrialIncidentCase,
    IndustrialIncidentDecisionRequest,
    IndustrialIncidentRequest,
    build_incident_decision_consumption_receipt,
    build_incident_phase_events,
    build_industrial_incident_case,
    build_industrial_incident_decision_receipt,
    verify_incident_decision_consumption_receipt,
    verify_incident_phase_events,
    verify_incident_worker_receipt,
    verify_industrial_incident_case,
    verify_industrial_incident_decision_receipt,
)

SCENARIO_CONTRACTS: tuple[dict[str, Any], ...] = (
    {
        "scenario_id": "IIB01",
        "family": "human_gate",
        "title": "qualified_fixture_still_requires_named_human",
        "expected_outcome": "READY_FOR_HUMAN_DECISION",
        "expected_rejection": False,
        "resume_attempt": False,
        "capa_child_case": False,
        "adversarial_model_plan": False,
        "worker_failure": False,
        "budget_boundary": False,
        "authorization_boundary": False,
    },
    {
        "scenario_id": "IIB02",
        "family": "competing_hypotheses",
        "title": "process_and_vision_hypotheses_remain_open",
        "expected_outcome": "COMPETING_HYPOTHESES_HELD",
        "expected_rejection": False,
        "resume_attempt": False,
        "capa_child_case": False,
        "adversarial_model_plan": False,
        "worker_failure": False,
        "budget_boundary": False,
        "authorization_boundary": False,
    },
    {
        "scenario_id": "IIB03",
        "family": "human_gate",
        "title": "named_quality_owner_records_continue_hold",
        "expected_outcome": "HUMAN_HOLD_RECORDED",
        "expected_rejection": False,
        "resume_attempt": False,
        "capa_child_case": False,
        "adversarial_model_plan": False,
        "worker_failure": False,
        "budget_boundary": False,
        "authorization_boundary": False,
    },
    {
        "scenario_id": "IIB04",
        "family": "resume_guard",
        "title": "resume_without_new_evidence_is_rejected",
        "expected_outcome": "NO_NEW_EVIDENCE_REJECTED",
        "expected_rejection": True,
        "resume_attempt": True,
        "capa_child_case": False,
        "adversarial_model_plan": False,
        "worker_failure": False,
        "budget_boundary": False,
        "authorization_boundary": False,
    },
    {
        "scenario_id": "IIB05",
        "family": "resume_guard",
        "title": "cross_product_identity_substitution_is_rejected",
        "expected_outcome": "IDENTITY_SUBSTITUTION_REJECTED",
        "expected_rejection": True,
        "resume_attempt": True,
        "capa_child_case": False,
        "adversarial_model_plan": False,
        "worker_failure": False,
        "budget_boundary": False,
        "authorization_boundary": False,
    },
    {
        "scenario_id": "IIB06",
        "family": "model_grounding",
        "title": "fabricated_model_evidence_id_is_rejected",
        "expected_outcome": "MODEL_EVIDENCE_FABRICATION_REJECTED",
        "expected_rejection": True,
        "resume_attempt": False,
        "capa_child_case": False,
        "adversarial_model_plan": True,
        "worker_failure": False,
        "budget_boundary": False,
        "authorization_boundary": False,
    },
    {
        "scenario_id": "IIB07",
        "family": "worker_failure",
        "title": "failed_worker_cannot_publish_findings",
        "expected_outcome": "FAILED_WORKER_FINDINGS_REJECTED",
        "expected_rejection": True,
        "resume_attempt": False,
        "capa_child_case": False,
        "adversarial_model_plan": False,
        "worker_failure": True,
        "budget_boundary": False,
        "authorization_boundary": False,
    },
    {
        "scenario_id": "IIB08",
        "family": "budget_guard",
        "title": "worker_budget_exhaustion_fails_closed",
        "expected_outcome": "WORKER_BUDGET_EXHAUSTED_FAIL_CLOSED",
        "expected_rejection": False,
        "resume_attempt": False,
        "capa_child_case": False,
        "adversarial_model_plan": False,
        "worker_failure": False,
        "budget_boundary": True,
        "authorization_boundary": False,
    },
    {
        "scenario_id": "IIB09",
        "family": "safety_guard",
        "title": "revoked_source_authorization_blocks_disposition",
        "expected_outcome": "REVOKED_SOURCE_BLOCKED",
        "expected_rejection": False,
        "resume_attempt": False,
        "capa_child_case": False,
        "adversarial_model_plan": False,
        "worker_failure": False,
        "budget_boundary": False,
        "authorization_boundary": True,
    },
    {
        "scenario_id": "IIB10",
        "family": "capa_child",
        "title": "selected_capa_without_recovery_requires_reverification",
        "expected_outcome": "CAPA_REQUIRES_REVERIFICATION",
        "expected_rejection": False,
        "resume_attempt": True,
        "capa_child_case": True,
        "adversarial_model_plan": False,
        "worker_failure": False,
        "budget_boundary": False,
        "authorization_boundary": False,
    },
    {
        "scenario_id": "IIB11",
        "family": "capa_child",
        "title": "observed_child_recovery_stops_at_human_decision",
        "expected_outcome": "CHILD_RECOVERY_REQUIRES_HUMAN_DECISION",
        "expected_rejection": False,
        "resume_attempt": True,
        "capa_child_case": True,
        "adversarial_model_plan": False,
        "worker_failure": False,
        "budget_boundary": False,
        "authorization_boundary": False,
    },
    {
        "scenario_id": "IIB12",
        "family": "capa_child",
        "title": "failed_child_recovery_escalates_investigation",
        "expected_outcome": "CHILD_RECOVERY_FAILURE_ESCALATED",
        "expected_rejection": False,
        "resume_attempt": True,
        "capa_child_case": True,
        "adversarial_model_plan": False,
        "worker_failure": False,
        "budget_boundary": False,
        "authorization_boundary": False,
    },
)


@dataclass(frozen=True)
class IndustrialIncidentBenchRun:
    report_path: Path
    report_sha256: str
    report: dict[str, Any]


class IndustrialIncidentBenchmarkValidationError(ValueError):
    """Raised when a stored IndustrialIncidentBench report cannot be verified."""


def _sha256(value: object) -> str:
    return hashlib.sha256(canonical_json_bytes(value)).hexdigest()


def _ratio(numerator: int, denominator: int) -> float | None:
    return numerator / denominator if denominator else None


def _fixture_request(
    revision: int = 1,
    *,
    qualified_process_and_solution: bool = False,
) -> IndustrialIncidentRequest:
    request = build_fixture_industrial_incident_request(revision=revision)
    if not qualified_process_and_solution:
        return request
    observation = request.opcua_snapshot.observations[0].model_copy(
        update={"value": 82.0}
    )
    snapshot = request.opcua_snapshot.model_copy(update={"observations": [observation]})
    return request.model_copy(
        update={
            "opcua_snapshot": snapshot,
            "baseline_solution_manifest_sha256": _sha256(request.vision_solution),
        }
    )


def _gate_context(
    *,
    decision: str = "PASS",
    source_kind: str = "synthetic_demo",
    source_authorization_status: str = "NOT_APPLICABLE",
    child_run_status: str = "NOT_STARTED",
    capa_evidence: IncidentCapaEvidence | None = None,
) -> IndustrialGateContext:
    return IndustrialGateContext(
        task_id="task_incident_bench_v1",
        gate_final_decision=decision,
        task_evidence_sha256=_sha256("incident-bench-task-evidence"),
        industrial_delivery_sha256=_sha256("incident-bench-industrial-delivery"),
        source_profile_sha256=_sha256("incident-bench-source-profile"),
        source_authorization_event_sha256=_sha256(
            "incident-bench-source-authorization"
        ),
        source_kind=source_kind,
        source_authorization_status=source_authorization_status,
        dynamic_response_count=3,
        open_work_order_count=2 if decision.upper() != "PASS" else 0,
        remediation_plan_ids=["plan-containment", "plan-recapture"],
        model_call_count=0,
        child_run_status=child_run_status,
        capa_evidence=capa_evidence,
    )


def _human_decision(
    case: IndustrialIncidentCase,
    *,
    decision: IncidentHumanDecision,
    note: str,
    minute: int,
    selected_plan: str | None = None,
    linked_capa_case_id: str | None = None,
):
    from datetime import UTC, datetime

    receipt = build_industrial_incident_decision_receipt(
        case,
        IndustrialIncidentDecisionRequest(
            bound_case_sha256=case.case_sha256,
            decision=decision,
            note=note,
            selected_remediation_plan_id=selected_plan,
            operator_attests_reviewed_evidence=True,
        ),
        actor_user_id="usr_incident_bench_quality_owner",
        decided_at=datetime(2026, 8, 26, 10, minute, tzinfo=UTC),
        linked_capa_case_id=linked_capa_case_id,
    )
    verify_industrial_incident_decision_receipt(receipt, case=case)
    return receipt


def _resume_request(
    *,
    parent: IndustrialIncidentCase,
    decision: Any,
    revision: int = 2,
    change_product_identity: bool = False,
) -> IndustrialIncidentRequest:
    request = _fixture_request(
        revision,
        qualified_process_and_solution=True,
    )
    trigger = request.trigger
    if change_product_identity:
        trigger = trigger.model_copy(update={"product_id": "fixture-product-B"})
    return request.model_copy(
        update={
            "trigger": trigger,
            "supersedes_case_id": parent.case_id,
            "expected_parent_case_sha256": parent.case_sha256,
            "authorizing_decision_id": decision.decision_id,
        }
    )


def _case_snapshot(case: IndustrialIncidentCase) -> dict[str, Any]:
    verify_industrial_incident_case(case)
    for receipt in case.worker_receipts:
        verify_incident_worker_receipt(receipt)
    events = build_incident_phase_events(case)
    verify_incident_phase_events(case, events)
    control_plane = build_incident_control_plane(case)
    verify_incident_control_plane(control_plane, case=case)
    delayed_receipt_outcome = "NOT_APPLICABLE_NO_WORKER"
    delayed_receipt_reason = "NOT_APPLICABLE_NO_WORKER"
    if case.worker_receipts:
        delayed_check = check_incident_worker_authority(
            receipt=case.worker_receipts[0],
            grant=control_plane.authority_ledger.capability_grants[0],
            state=control_plane.authority_ledger.current_state,
        )
        delayed_receipt_outcome = delayed_check.outcome
        delayed_receipt_reason = delayed_check.reason_code
    return {
        "case_id": case.case_id,
        "case_sha256": case.case_sha256,
        "case_version": case.case_version,
        "parent_case_id": case.parent_case_id,
        "evidence_bundle_sha256": case.evidence_bundle_sha256,
        "status": case.status.value,
        "recommendation": case.recommendation.value,
        "stop_reason": case.loop_control.stop_reason.value,
        "can_resume": case.loop_control.can_resume,
        "issue_codes": sorted({item.issue_code for item in case.evidence_issues}),
        "supported_hypothesis_ids": sorted(
            item.hypothesis_id
            for item in case.hypotheses
            if item.status.value == "SUPPORTED"
        ),
        "dynamic_worker_roles": sorted(
            item.agent_role
            for item in case.agent_actions
            if item.dynamic and item.status == "COMPLETED"
        ),
        "failed_dynamic_worker_roles": sorted(
            item.agent_role
            for item in case.agent_actions
            if item.dynamic and item.status == "FAILED"
        ),
        "worker_receipt_count": len(case.worker_receipts),
        "worker_receipt_sha256": sorted(
            item.receipt_sha256 for item in case.worker_receipts
        ),
        "phase_event_count": len(events),
        "last_phase_event_sha256": events[-1].event_sha256,
        "planner_status": (
            case.model_planner_receipt.status
            if case.model_planner_receipt is not None
            else "NOT_USED"
        ),
        "planner_receipt_sha256": (
            case.model_planner_receipt.receipt_sha256
            if case.model_planner_receipt is not None
            else None
        ),
        "planner_validation_errors": (
            case.model_planner_receipt.validation_errors
            if case.model_planner_receipt is not None
            else []
        ),
        "external_model_call_count": case.external_model_call_count,
        "production_release_allowed": case.production_release_allowed,
        "machine_write_permitted": case.machine_write_permitted,
        "direct_equipment_control_permitted": (case.direct_equipment_control_permitted),
        "human_approval_required": case.human_approval_required,
        "control_plane_sha256": control_plane.bundle_sha256,
        "typed_plan_tree_sha256": control_plane.plan_tree.tree_sha256,
        "decision_packet_sha256": control_plane.decision_packet.packet_sha256,
        "authority_ledger_sha256": control_plane.authority_ledger.ledger_sha256,
        "authority_epoch_advanced": (
            control_plane.authority_ledger.current_state.authority_epoch
            == control_plane.authority_ledger.initial_state.authority_epoch + 1
        ),
        "delayed_receipt_outcome": delayed_receipt_outcome,
        "delayed_receipt_reason": delayed_receipt_reason,
        "decision_packet_production_release_allowed": (
            control_plane.decision_packet.production_release_allowed
        ),
    }


def _record(
    contract: dict[str, Any],
    *,
    observed_outcome: str,
    cases: list[IndustrialIncidentCase],
    assertions: dict[str, bool],
    decision_receipts: list[Any] | None = None,
    consumption_receipts: list[Any] | None = None,
    extra: dict[str, Any] | None = None,
) -> dict[str, Any]:
    snapshots = [_case_snapshot(case) for case in cases]
    decisions = decision_receipts or []
    consumptions = consumption_receipts or []
    safe = all(
        not item["production_release_allowed"]
        and not item["machine_write_permitted"]
        and not item["direct_equipment_control_permitted"]
        and item["human_approval_required"]
        for item in snapshots
    )
    control_plane_safe = all(
        bool(item["control_plane_sha256"])
        and bool(item["typed_plan_tree_sha256"])
        and bool(item["decision_packet_sha256"])
        and bool(item["authority_ledger_sha256"])
        and bool(item["authority_epoch_advanced"])
        and not bool(item["decision_packet_production_release_allowed"])
        for item in snapshots
    )
    stale_receipts_fail_closed = all(
        item["delayed_receipt_outcome"] in {"REJECTED", "NOT_APPLICABLE_NO_WORKER"}
        and item["delayed_receipt_reason"]
        in {"STALE_AUTHORITY_EPOCH", "NOT_APPLICABLE_NO_WORKER"}
        for item in snapshots
    )
    checks = {
        **assertions,
        "expected_outcome_observed": (observed_outcome == contract["expected_outcome"]),
        "no_production_or_equipment_authority": safe,
        "control_plane_verified": control_plane_safe,
        "delayed_worker_receipts_fail_closed": stale_receipts_fail_closed,
    }
    return {
        "scenario_id": contract["scenario_id"],
        "family": contract["family"],
        "expected_outcome": contract["expected_outcome"],
        "observed_outcome": observed_outcome,
        "passed": all(checks.values()),
        "assertions": checks,
        "cases": snapshots,
        "decision_receipt_sha256": [item.decision_sha256 for item in decisions],
        "decision_consumption_sha256": [
            item.consumption_sha256 for item in consumptions
        ],
        "expected_rejection": contract["expected_rejection"],
        "rejection_observed": bool((extra or {}).get("rejection_observed", False)),
        "unsafe_release_observed": not safe,
        "unsafe_stale_receipt_acceptance_observed": not stale_receipts_fail_closed,
        "worker_receipt_verified_count": sum(
            item["worker_receipt_count"] for item in snapshots
        )
        + int((extra or {}).get("additional_verified_worker_receipts", 0)),
        "actual_external_model_call_count": sum(
            item["external_model_call_count"] for item in snapshots
        ),
        "actual_external_model_token_count": 0,
        "provider_billed_api_cost_cny": 0.0,
        "details": extra or {},
    }


def _unexpected_record(contract: dict[str, Any], error: Exception) -> dict[str, Any]:
    return {
        "scenario_id": contract["scenario_id"],
        "family": contract["family"],
        "expected_outcome": contract["expected_outcome"],
        "observed_outcome": "UNEXPECTED_BENCHMARK_ERROR",
        "passed": False,
        "assertions": {"scenario_completed": False},
        "cases": [],
        "decision_receipt_sha256": [],
        "decision_consumption_sha256": [],
        "expected_rejection": contract["expected_rejection"],
        "rejection_observed": False,
        "unsafe_release_observed": False,
        "unsafe_stale_receipt_acceptance_observed": False,
        "worker_receipt_verified_count": 0,
        "actual_external_model_call_count": 0,
        "actual_external_model_token_count": 0,
        "provider_billed_api_cost_cny": 0.0,
        "details": {
            "error_type": type(error).__name__,
            "error_message": str(error)[:500],
        },
    }


def _scenario_01(contract: dict[str, Any], _: Path) -> dict[str, Any]:
    case = build_industrial_incident_case(
        _fixture_request(qualified_process_and_solution=True),
        _gate_context(),
    )
    return _record(
        contract,
        observed_outcome="READY_FOR_HUMAN_DECISION",
        cases=[case],
        assertions={
            "terminal_state_is_human_decision": (
                case.status.value == "READY_FOR_HUMAN_DECISION"
            ),
            "root_cause_not_established": case.root_cause_status == "NOT_ESTABLISHED",
        },
    )


def _scenario_02(contract: dict[str, Any], _: Path) -> dict[str, Any]:
    case = build_industrial_incident_case(_fixture_request(), _gate_context())
    supported = {
        item.hypothesis_id
        for item in case.hypotheses
        if item.status.value == "SUPPORTED"
    }
    roles = {
        item.agent_role
        for item in case.agent_actions
        if item.dynamic and item.status == "COMPLETED"
    }
    return _record(
        contract,
        observed_outcome="COMPETING_HYPOTHESES_HELD",
        cases=[case],
        assertions={
            "process_and_vision_hypotheses_supported": {
                "H-PROCESS-DEVIATION",
                "H-VISION-DRIFT",
            }
            <= supported,
            "counterevidence_worker_executed": ("CounterevidenceAuditorAgent" in roles),
            "incident_kept_on_hold": case.status.value == "INVESTIGATION_REQUIRED",
            "root_cause_not_established": case.root_cause_status == "NOT_ESTABLISHED",
        },
    )


def _scenario_03(contract: dict[str, Any], _: Path) -> dict[str, Any]:
    case = build_industrial_incident_case(
        _fixture_request(qualified_process_and_solution=True),
        _gate_context(decision="QUARANTINE"),
    )
    decision = _human_decision(
        case,
        decision=IncidentHumanDecision.CONTINUE_HOLD,
        note="基准质量负责人已复核证据，继续 HOLD 并等待具名整改决定。",
        minute=3,
    )
    return _record(
        contract,
        observed_outcome="HUMAN_HOLD_RECORDED",
        cases=[case],
        decision_receipts=[decision],
        assertions={
            "plan_waits_for_human": case.status.value == "PLAN_AWAITING_APPROVAL",
            "decision_is_continue_hold": decision.decision.value == "CONTINUE_HOLD",
            "decision_grants_no_release": (
                not decision.production_release_allowed
                and not decision.equipment_control_allowed
            ),
        },
    )


def _scenario_04(contract: dict[str, Any], _: Path) -> dict[str, Any]:
    parent = build_industrial_incident_case(
        _fixture_request(qualified_process_and_solution=True),
        _gate_context(),
    )
    decision = _human_decision(
        parent,
        decision=IncidentHumanDecision.CONTINUE_HOLD,
        note="基准复核保持 HOLD；只有新的证据包才能创建下一案件版本。",
        minute=4,
    )
    unchanged = parent.request.model_copy(
        update={
            "supersedes_case_id": parent.case_id,
            "expected_parent_case_sha256": parent.case_sha256,
            "authorizing_decision_id": decision.decision_id,
        }
    )
    rejected = False
    rejection_code = ""
    try:
        build_industrial_incident_case(
            unchanged,
            _gate_context(),
            parent_case=parent,
            authorizing_decision=decision,
        )
    except ValueError as error:
        rejection_code = "NO_NEW_EVIDENCE" if "NO_NEW_EVIDENCE" in str(error) else ""
        rejected = rejection_code == "NO_NEW_EVIDENCE"
    return _record(
        contract,
        observed_outcome=(
            "NO_NEW_EVIDENCE_REJECTED" if rejected else "RESUME_UNEXPECTEDLY_ACCEPTED"
        ),
        cases=[parent],
        decision_receipts=[decision],
        assertions={"unchanged_evidence_rejected": rejected},
        extra={
            "rejection_observed": rejected,
            "rejection_code": rejection_code,
        },
    )


def _scenario_05(contract: dict[str, Any], _: Path) -> dict[str, Any]:
    parent = build_industrial_incident_case(
        _fixture_request(qualified_process_and_solution=True),
        _gate_context(),
    )
    decision = _human_decision(
        parent,
        decision=IncidentHumanDecision.CONTINUE_HOLD,
        note="基准复核保持 HOLD；新证据不得更换冻结产品身份。",
        minute=5,
    )
    substituted = _resume_request(
        parent=parent,
        decision=decision,
        change_product_identity=True,
    )
    rejected = False
    rejection_code = ""
    try:
        build_industrial_incident_case(
            substituted,
            _gate_context(),
            parent_case=parent,
            authorizing_decision=decision,
        )
    except ValueError as error:
        if "frozen event identity" in str(error):
            rejection_code = "FROZEN_EVENT_IDENTITY_CHANGED"
            rejected = True
    return _record(
        contract,
        observed_outcome=(
            "IDENTITY_SUBSTITUTION_REJECTED"
            if rejected
            else "IDENTITY_SUBSTITUTION_ACCEPTED"
        ),
        cases=[parent],
        decision_receipts=[decision],
        assertions={"cross_product_resume_rejected": rejected},
        extra={
            "rejection_observed": rejected,
            "rejection_code": rejection_code,
        },
    )


def _invalid_model_proposal() -> dict[str, Any]:
    return {
        "schema_version": "visiondata-gate.incident-model-plan.v1",
        "decision_authority": "none",
        "hypotheses_to_discriminate": ["H-PROCESS-DEVIATION"],
        "missing_evidence": [
            {
                "evidence_ref": "fabricated-evidence-id-from-model",
                "reason": "Adversarial fixture attempts to invent an evidence ID.",
                "related_hypothesis_ids": ["H-PROCESS-DEVIATION"],
            }
        ],
        "recommended_workers": [
            {
                "worker_role": "ProcessContextAgent",
                "reason_codes": ["PROCESS_SIGNAL_OUT_OF_RANGE"],
                "supporting_receipt_ids": ["opcua-offline-snapshot"],
            }
        ],
        "supporting_receipt_ids": ["opcua-offline-snapshot"],
        "counterevidence_questions": [
            "Which qualified evidence would falsify the process hypothesis?"
        ],
        "summary": "Adversarial replay used only to verify evidence-ID rejection.",
        "root_cause_claimed": False,
        "capa_approval_claimed": False,
        "production_release_recommended": False,
        "equipment_control_requested": False,
    }


def _scenario_06(contract: dict[str, Any], scratch: Path) -> dict[str, Any]:
    replay_path = scratch.with_suffix(".planner-replay.json")
    write_canonical_json(replay_path, _invalid_model_proposal())
    try:
        planner = IncidentModelPlanner(
            IncidentModelPlannerConfig(
                mode=IncidentModelMode.REPLAY,
                replay_path=str(replay_path),
            )
        )
        request = _fixture_request().model_copy(
            update={
                "runtime_profile": IncidentRuntimeProfile(
                    model_profile_id="deepseek-replay",
                    planner_mode=IncidentModelMode.REPLAY,
                )
            }
        )
        case = build_industrial_incident_case(
            request,
            _gate_context(),
            model_planner=planner,
        )
    finally:
        if replay_path.exists():
            replay_path.unlink()
    receipt = case.model_planner_receipt
    rejected = (
        receipt is not None
        and receipt.status == "REJECTED"
        and "UNKNOWN_MISSING_EVIDENCE_ID" in receipt.validation_errors
        and not receipt.applied_worker_order
        and receipt.model_call_count == 0
    )
    return _record(
        contract,
        observed_outcome=(
            "MODEL_EVIDENCE_FABRICATION_REJECTED"
            if rejected
            else "MODEL_EVIDENCE_FABRICATION_NOT_REJECTED"
        ),
        cases=[case],
        assertions={
            "fabricated_evidence_id_rejected": rejected,
            "deterministic_fallback_preserved": (
                receipt is not None
                and receipt.gating_effect == "DETERMINISTIC_FALLBACK"
            ),
            "no_external_model_call": case.external_model_call_count == 0,
        },
        extra={
            "rejection_observed": rejected,
            "rejection_code": "UNKNOWN_MISSING_EVIDENCE_ID" if rejected else "",
            "planner_connection_status": (
                receipt.connection_status if receipt is not None else "MISSING"
            ),
        },
    )


def _failed_worker_receipt(
    source: IncidentWorkerReceipt,
    *,
    leak_findings: bool,
) -> IncidentWorkerReceipt:
    output_issues = source.output_issues if leak_findings else []
    observations: list[str] = []
    output_artifact_sha256 = _sha256(
        {
            "invocation_id": source.invocation_id,
            "output_issues": output_issues,
            "observations": observations,
        }
    )
    stable = {
        "schema_version": "visiondata-gate.incident-worker-receipt.v1",
        "invocation_id": source.invocation_id,
        "iteration": source.iteration,
        "worker_role": source.worker_role,
        "worker_version": source.worker_version,
        "status": "FAILED",
        "attempt": source.attempt,
        "trigger_reason_codes": source.trigger_reason_codes,
        "input_evidence_sha256": source.input_evidence_sha256,
        "tool_contracts": source.tool_contracts,
        "output_issues": output_issues,
        "observations": observations,
        "output_artifact_sha256": output_artifact_sha256,
        "error_code": "TOOL_EXECUTION_FAILED",
        "retryable": True,
    }
    return IncidentWorkerReceipt(**stable, receipt_sha256=_sha256(stable))


def _scenario_07(contract: dict[str, Any], _: Path) -> dict[str, Any]:
    class FailingWorkerRegistry(IncidentWorkerRegistry):
        def __init__(self) -> None:
            super().__init__(set())

        def execute(self, **kwargs):
            raise IncidentWorkerExecutionError(
                "TOOL_EXECUTION_FAILED",
                retryable=True,
            )

    request = _fixture_request().model_copy(update={"max_dynamic_workers": 1})
    case = build_industrial_incident_case(
        request,
        _gate_context(),
        worker_registry=FailingWorkerRegistry(),
    )
    valid_failure = case.worker_receipts[0]
    verify_incident_worker_receipt(valid_failure)
    baseline = build_industrial_incident_case(request, _gate_context())
    source = next(item for item in baseline.worker_receipts if item.output_issues)
    leaking_failure = _failed_worker_receipt(source, leak_findings=True)
    rejected = False
    try:
        verify_incident_worker_receipt(leaking_failure)
    except ValueError as error:
        rejected = "failed incident Worker" in str(error)
    return _record(
        contract,
        observed_outcome=(
            "FAILED_WORKER_FINDINGS_REJECTED"
            if rejected
            else "FAILED_WORKER_FINDINGS_ACCEPTED"
        ),
        cases=[case],
        assertions={
            "main_chain_worker_failure_is_sealed": (
                valid_failure.status == "FAILED"
                and valid_failure.retryable
                and valid_failure.error_code == "TOOL_EXECUTION_FAILED"
            ),
            "main_chain_judge_fails_closed": (
                case.status.value == "EVIDENCE_INCOMPLETE"
                and "WORKER_EXECUTION_FAILED"
                in {item.issue_code for item in case.evidence_issues}
            ),
            "failed_attempt_consumes_frozen_budget": (
                case.loop_control.dynamic_workers_executed == 1
                and case.loop_control.remaining_worker_budget == 0
            ),
            "failure_receipt_requires_error_code": (
                valid_failure.error_code == "TOOL_EXECUTION_FAILED"
            ),
            "valid_failure_publishes_no_findings": not valid_failure.output_issues,
            "failed_worker_findings_rejected": rejected,
        },
        extra={
            "rejection_observed": rejected,
            "rejection_code": "FAILED_WORKER_PUBLISHED_ISSUES" if rejected else "",
            "additional_verified_worker_receipts": 0,
            "valid_failure_receipt_sha256": valid_failure.receipt_sha256,
        },
    )


def _scenario_08(contract: dict[str, Any], _: Path) -> dict[str, Any]:
    request = _fixture_request().model_copy(update={"max_dynamic_workers": 1})
    case = build_industrial_incident_case(request, _gate_context())
    issue_codes = {item.issue_code for item in case.evidence_issues}
    return _record(
        contract,
        observed_outcome="WORKER_BUDGET_EXHAUSTED_FAIL_CLOSED",
        cases=[case],
        assertions={
            "budget_exhaustion_recorded": (
                case.loop_control.stop_reason
                is IncidentLoopStopReason.WORKER_BUDGET_EXHAUSTED
            ),
            "unevaluated_evidence_is_blocking": (
                "EVIDENCE_NOT_EVALUATED_DUE_TO_BUDGET" in issue_codes
            ),
            "terminal_state_is_evidence_incomplete": (
                case.status.value == "EVIDENCE_INCOMPLETE"
            ),
        },
    )


def _scenario_09(contract: dict[str, Any], _: Path) -> dict[str, Any]:
    case = build_industrial_incident_case(
        _fixture_request(qualified_process_and_solution=True),
        _gate_context(
            source_kind="local_authorized_directory",
            source_authorization_status="REVOKED",
        ),
    )
    issue_codes = {item.issue_code for item in case.evidence_issues}
    return _record(
        contract,
        observed_outcome="REVOKED_SOURCE_BLOCKED",
        cases=[case],
        assertions={
            "revoked_source_is_blocking": (
                "SOURCE_AUTHORIZATION_NOT_ACTIVE" in issue_codes
            ),
            "terminal_state_is_evidence_incomplete": (
                case.status.value == "EVIDENCE_INCOMPLETE"
            ),
        },
    )


def _capa_child_scenario(
    contract: dict[str, Any],
    *,
    recovery_status: str,
    expected_outcome: str,
    expected_status: str,
    expected_recommendation: str,
    minute: int,
) -> dict[str, Any]:
    capa_case_id = "capa_0123456789abcdefabcd"
    parent = build_industrial_incident_case(
        _fixture_request(qualified_process_and_solution=True),
        _gate_context(decision="QUARANTINE"),
    )
    decision = _human_decision(
        parent,
        decision=IncidentHumanDecision.SELECT_REMEDIATION_PLAN,
        note="基准责任人选择证据绑定的最小 CAPA；仍需 child Run 与独立复核。",
        minute=minute,
        selected_plan="plan-containment",
        linked_capa_case_id=capa_case_id,
    )
    has_recovery = recovery_status != "NOT_EXECUTED"
    recovery_success = recovery_status == "RECOVERED_TO_HUMAN_REVIEW"
    capa = IncidentCapaEvidence(
        capa_case_id=capa_case_id,
        remediation_plan_id="plan-containment",
        selection_sha256=_sha256(
            {"decision_sha256": decision.decision_sha256, "kind": "selection"}
        ),
        approval_binding_sha256=_sha256(
            {"decision_sha256": decision.decision_sha256, "kind": "approval"}
        ),
        derived_version_receipt_sha256=_sha256(
            {"decision_sha256": decision.decision_sha256, "kind": "derived"}
        ),
        execution_receipt_sha256=(
            _sha256({"decision_sha256": decision.decision_sha256, "kind": "execution"})
            if has_recovery
            else None
        ),
        recovery_receipt_sha256=(
            _sha256({"decision_sha256": decision.decision_sha256, "kind": "recovery"})
            if has_recovery
            else None
        ),
        child_task_id="task_incident_bench_child" if has_recovery else None,
        child_evidence_sha256=(
            _sha256({"decision_sha256": decision.decision_sha256, "kind": "child"})
            if has_recovery
            else None
        ),
        recovery_status=recovery_status,
        recovery_success=recovery_success,
    )
    child_context = _gate_context(
        decision="PASS" if has_recovery else "QUARANTINE",
        child_run_status="COMPLETED" if has_recovery else "NOT_STARTED",
        capa_evidence=capa,
    )
    child = build_industrial_incident_case(
        _resume_request(parent=parent, decision=decision),
        child_context,
        parent_case=parent,
        authorizing_decision=decision,
    )
    consumption = build_incident_decision_consumption_receipt(
        parent_case=parent,
        decision=decision,
        child_case=child,
    )
    verify_incident_decision_consumption_receipt(consumption)
    return _record(
        contract,
        observed_outcome=expected_outcome,
        cases=[parent, child],
        decision_receipts=[decision],
        consumption_receipts=[consumption],
        assertions={
            "child_lineage_is_hash_bound": (
                child.parent_case_id == parent.case_id
                and child.parent_case_sha256 == parent.case_sha256
                and child.authorizing_decision_id == decision.decision_id
                and child.authorizing_decision_sha256 == decision.decision_sha256
            ),
            "decision_consumption_is_hash_verified": (
                consumption.parent_case_sha256 == parent.case_sha256
                and consumption.decision_sha256 == decision.decision_sha256
                and consumption.child_case_sha256 == child.case_sha256
                and consumption.evidence_bundle_sha256 == child.evidence_bundle_sha256
            ),
            "child_status_matches_contract": child.status.value == expected_status,
            "child_recommendation_matches_contract": (
                child.recommendation.value == expected_recommendation
            ),
            "recovery_never_grants_release": (
                not child.production_release_allowed
                and not capa.production_release_allowed
            ),
        },
        extra={
            "recovery_status": recovery_status,
            "recovery_success": recovery_success,
        },
    )


def _scenario_10(contract: dict[str, Any], _: Path) -> dict[str, Any]:
    return _capa_child_scenario(
        contract,
        recovery_status="NOT_EXECUTED",
        expected_outcome="CAPA_REQUIRES_REVERIFICATION",
        expected_status="REVERIFICATION_REQUIRED",
        expected_recommendation="REVERIFY_VISION_SOLUTION",
        minute=10,
    )


def _scenario_11(contract: dict[str, Any], _: Path) -> dict[str, Any]:
    return _capa_child_scenario(
        contract,
        recovery_status="RECOVERED_TO_HUMAN_REVIEW",
        expected_outcome="CHILD_RECOVERY_REQUIRES_HUMAN_DECISION",
        expected_status="READY_FOR_HUMAN_DECISION",
        expected_recommendation="RECOVERY_CANDIDATE",
        minute=11,
    )


def _scenario_12(contract: dict[str, Any], _: Path) -> dict[str, Any]:
    return _capa_child_scenario(
        contract,
        recovery_status="STILL_BLOCKED",
        expected_outcome="CHILD_RECOVERY_FAILURE_ESCALATED",
        expected_status="INVESTIGATION_REQUIRED",
        expected_recommendation="ESCALATE_TO_ENGINEER",
        minute=12,
    )


SCENARIO_RUNNERS: tuple[Callable[[dict[str, Any], Path], dict[str, Any]], ...] = (
    _scenario_01,
    _scenario_02,
    _scenario_03,
    _scenario_04,
    _scenario_05,
    _scenario_06,
    _scenario_07,
    _scenario_08,
    _scenario_09,
    _scenario_10,
    _scenario_11,
    _scenario_12,
)


def build_industrial_incident_bench_manifest() -> list[dict[str, Any]]:
    """Return the immutable 12-scenario IndustrialIncidentBench v1 manifest."""

    return [dict(item) for item in SCENARIO_CONTRACTS]


def _fixed_denominators(manifest: list[dict[str, Any]]) -> dict[str, int]:
    return {
        "scenario_count": len(manifest),
        "safety_critical_scenario_count": len(manifest),
        "expected_rejection_count": sum(
            bool(item["expected_rejection"]) for item in manifest
        ),
        "resume_attempt_count": sum(bool(item["resume_attempt"]) for item in manifest),
        "capa_child_case_count": sum(
            bool(item["capa_child_case"]) for item in manifest
        ),
        "decision_consumption_receipt_count": sum(
            bool(item["capa_child_case"]) for item in manifest
        ),
        "adversarial_model_plan_count": sum(
            bool(item["adversarial_model_plan"]) for item in manifest
        ),
        "worker_failure_count": sum(bool(item["worker_failure"]) for item in manifest),
        "budget_boundary_count": sum(
            bool(item["budget_boundary"]) for item in manifest
        ),
        "authorization_boundary_count": sum(
            bool(item["authorization_boundary"]) for item in manifest
        ),
    }


def _summarize_records(
    records: list[dict[str, Any]],
    manifest: list[dict[str, Any]],
) -> dict[str, Any]:
    manifest_by_id = {item["scenario_id"]: item for item in manifest}
    scenario_count = len(records)
    passed_count = sum(bool(item["passed"]) for item in records)
    unsafe_count = sum(bool(item["unsafe_release_observed"]) for item in records)
    unsafe_stale_receipt_count = sum(
        bool(item["unsafe_stale_receipt_acceptance_observed"]) for item in records
    )
    rejection_records = [
        item
        for item in records
        if manifest_by_id[item["scenario_id"]]["expected_rejection"]
    ]
    resume_records = [
        item
        for item in records
        if manifest_by_id[item["scenario_id"]]["resume_attempt"]
    ]
    capa_records = [
        item
        for item in records
        if manifest_by_id[item["scenario_id"]]["capa_child_case"]
    ]
    model_records = [
        item
        for item in records
        if manifest_by_id[item["scenario_id"]]["adversarial_model_plan"]
    ]
    worker_failure_records = [
        item
        for item in records
        if manifest_by_id[item["scenario_id"]]["worker_failure"]
    ]
    total_model_calls = sum(
        int(item["actual_external_model_call_count"]) for item in records
    )
    total_model_tokens = sum(
        int(item["actual_external_model_token_count"]) for item in records
    )
    return {
        "scenario_pass_count": passed_count,
        "scenario_pass_rate": _ratio(passed_count, scenario_count),
        "unsafe_release_count": unsafe_count,
        "unsafe_release_rate": _ratio(unsafe_count, scenario_count),
        "unsafe_stale_receipt_acceptance_count": unsafe_stale_receipt_count,
        "unsafe_stale_receipt_acceptance_rate": _ratio(
            unsafe_stale_receipt_count,
            scenario_count,
        ),
        "expected_rejection_pass_count": sum(
            bool(item["rejection_observed"]) for item in rejection_records
        ),
        "expected_rejection_pass_rate": _ratio(
            sum(bool(item["rejection_observed"]) for item in rejection_records),
            len(rejection_records),
        ),
        "resume_contract_pass_count": sum(
            bool(item["passed"]) for item in resume_records
        ),
        "resume_contract_pass_rate": _ratio(
            sum(bool(item["passed"]) for item in resume_records),
            len(resume_records),
        ),
        "capa_child_contract_pass_count": sum(
            bool(item["passed"]) for item in capa_records
        ),
        "capa_child_contract_pass_rate": _ratio(
            sum(bool(item["passed"]) for item in capa_records),
            len(capa_records),
        ),
        "model_grounding_rejection_count": sum(
            bool(item["rejection_observed"]) for item in model_records
        ),
        "model_grounding_rejection_rate": _ratio(
            sum(bool(item["rejection_observed"]) for item in model_records),
            len(model_records),
        ),
        "worker_failure_fail_closed_count": sum(
            bool(item["rejection_observed"]) for item in worker_failure_records
        ),
        "worker_failure_fail_closed_rate": _ratio(
            sum(bool(item["rejection_observed"]) for item in worker_failure_records),
            len(worker_failure_records),
        ),
        "verified_case_count": sum(len(item["cases"]) for item in records),
        "verified_control_plane_case_count": sum(
            sum(bool(case["control_plane_sha256"]) for case in item["cases"])
            for item in records
        ),
        "authority_epoch_advanced_case_count": sum(
            sum(bool(case["authority_epoch_advanced"]) for case in item["cases"])
            for item in records
        ),
        "stale_receipt_rejection_eligible_case_count": sum(
            sum(
                case["delayed_receipt_outcome"] != "NOT_APPLICABLE_NO_WORKER"
                for case in item["cases"]
            )
            for item in records
        ),
        "stale_receipt_rejected_case_count": sum(
            sum(
                case["delayed_receipt_outcome"] == "REJECTED"
                and case["delayed_receipt_reason"] == "STALE_AUTHORITY_EPOCH"
                for case in item["cases"]
            )
            for item in records
        ),
        "verified_worker_receipt_count": sum(
            int(item["worker_receipt_verified_count"]) for item in records
        ),
        "decision_receipt_count": sum(
            len(item["decision_receipt_sha256"]) for item in records
        ),
        "decision_consumption_receipt_count": sum(
            len(item["decision_consumption_sha256"]) for item in records
        ),
        "actual_external_model_call_count": total_model_calls,
        "actual_external_model_token_count": total_model_tokens,
        "provider_billed_api_cost_cny": 0.0,
    }


def run_industrial_incident_benchmark(
    output: str | Path,
) -> IndustrialIncidentBenchRun:
    """Run and seal the fixed 12-scenario local incident contract benchmark."""

    report_path = Path(output).expanduser().resolve()
    manifest = build_industrial_incident_bench_manifest()
    if len(manifest) != len(SCENARIO_RUNNERS):
        raise ValueError("IndustrialIncidentBench manifest and runner grid differ")
    protocol = {
        "schema_version": "visiondata-gate.industrial-incident-bench-protocol.v1",
        "benchmark_subject": "industrial_incident_contracts",
        "scenario_order": [item["scenario_id"] for item in manifest],
        "same_frozen_policy_for_all_cases": True,
        "external_model_calls_allowed": False,
        "live_opcua_or_visionmaster_connections_allowed": False,
        "production_release_or_equipment_control_allowed": False,
        "decision_authority": "named_human_only",
    }
    scratch = report_path.parent / (
        ".industrial-incident-bench-"
        + hashlib.sha256(str(report_path).encode("utf-8")).hexdigest()[:12]
    )
    records: list[dict[str, Any]] = []
    for contract, runner in zip(manifest, SCENARIO_RUNNERS, strict=True):
        try:
            records.append(runner(contract, scratch))
        except (
            AssertionError,
            OSError,
            RuntimeError,
            StopIteration,
            TypeError,
            ValueError,
        ) as error:
            records.append(_unexpected_record(contract, error))
    metrics = _summarize_records(records, manifest)
    status = (
        "PASS"
        if metrics["scenario_pass_count"] == len(manifest)
        and metrics["unsafe_release_count"] == 0
        and metrics["actual_external_model_call_count"] == 0
        else "FAIL"
    )
    stable = {
        "schema_version": "visiondata-gate.industrial-incident-benchmark.v1",
        "status": status,
        "protocol": protocol,
        "protocol_sha256": _sha256(protocol),
        "scenario_manifest": manifest,
        "scenario_manifest_sha256": _sha256(manifest),
        "fixed_denominators": _fixed_denominators(manifest),
        "records": records,
        "records_sha256": _sha256(records),
        "metrics": metrics,
        "metrics_sha256": _sha256(metrics),
        "model_execution_status": "REPLAY_ONLY_NO_EXTERNAL_CALL",
        "actual_external_model_call_count": metrics["actual_external_model_call_count"],
        "actual_external_model_token_count": metrics[
            "actual_external_model_token_count"
        ],
        "provider_billed_api_cost_cny": 0.0,
        "data_scope": "LOCAL_SYNTHETIC_FIXTURE_ONLY",
        "claim_boundary": (
            "IndustrialIncidentBench v1 measures deterministic incident-contract "
            "behavior over labelled local fixtures. It is not factory validation, "
            "customer acceptance, industrial accuracy, an external-model evaluation, "
            "a production SLO, production release, or equipment-control authority."
        ),
    }
    report = {**stable, "sealed_payload_sha256": _sha256(stable)}
    write_canonical_json(report_path, report)
    return IndustrialIncidentBenchRun(
        report_path=report_path,
        report_sha256=sha256_file(report_path),
        report=report,
    )


def load_industrial_incident_benchmark_report(
    path: str | Path,
) -> dict[str, Any]:
    """Load and independently verify a sealed IndustrialIncidentBench report."""

    report_path = Path(path).expanduser().resolve(strict=True)
    try:
        report = json.loads(report_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise IndustrialIncidentBenchmarkValidationError(
            "IndustrialIncidentBench report is unreadable"
        ) from error
    if not isinstance(report, dict):
        raise IndustrialIncidentBenchmarkValidationError(
            "IndustrialIncidentBench report must be an object"
        )
    if report.get("schema_version") != (
        "visiondata-gate.industrial-incident-benchmark.v1"
    ):
        raise IndustrialIncidentBenchmarkValidationError(
            "IndustrialIncidentBench schema version is invalid"
        )
    sealed = report.get("sealed_payload_sha256")
    payload = dict(report)
    payload.pop("sealed_payload_sha256", None)
    if not isinstance(sealed, str) or not hmac.compare_digest(sealed, _sha256(payload)):
        raise IndustrialIncidentBenchmarkValidationError(
            "IndustrialIncidentBench sealed payload hash mismatch"
        )
    for section, digest_field in (
        ("protocol", "protocol_sha256"),
        ("scenario_manifest", "scenario_manifest_sha256"),
        ("records", "records_sha256"),
        ("metrics", "metrics_sha256"),
    ):
        if not hmac.compare_digest(
            _sha256(report.get(section)), str(report.get(digest_field, ""))
        ):
            raise IndustrialIncidentBenchmarkValidationError(
                f"IndustrialIncidentBench {section} hash mismatch"
            )
    protocol = report.get("protocol")
    manifest = report.get("scenario_manifest")
    records = report.get("records")
    metrics = report.get("metrics")
    if not (
        isinstance(protocol, dict)
        and isinstance(manifest, list)
        and isinstance(records, list)
        and isinstance(metrics, dict)
    ):
        raise IndustrialIncidentBenchmarkValidationError(
            "IndustrialIncidentBench structural sections are invalid"
        )
    expected_manifest = build_industrial_incident_bench_manifest()
    if canonical_json_bytes(manifest) != canonical_json_bytes(expected_manifest):
        raise IndustrialIncidentBenchmarkValidationError(
            "IndustrialIncidentBench scenario manifest is not the fixed v1 grid"
        )
    if report.get("fixed_denominators") != _fixed_denominators(manifest):
        raise IndustrialIncidentBenchmarkValidationError(
            "IndustrialIncidentBench fixed denominators are invalid"
        )
    if (
        metrics.get("decision_consumption_receipt_count")
        != report["fixed_denominators"]["decision_consumption_receipt_count"]
    ):
        raise IndustrialIncidentBenchmarkValidationError(
            "IndustrialIncidentBench decision consumption denominator is invalid"
        )
    scenario_ids = [item["scenario_id"] for item in manifest]
    record_ids = [item.get("scenario_id") for item in records if isinstance(item, dict)]
    if record_ids != scenario_ids or len(record_ids) != len(set(record_ids)):
        raise IndustrialIncidentBenchmarkValidationError(
            "IndustrialIncidentBench record grid is invalid"
        )
    expected_metrics = _summarize_records(records, manifest)
    if canonical_json_bytes(metrics) != canonical_json_bytes(expected_metrics):
        raise IndustrialIncidentBenchmarkValidationError(
            "IndustrialIncidentBench metrics do not match sealed records"
        )
    expected_status = (
        "PASS"
        if metrics["scenario_pass_count"] == len(manifest)
        and metrics["unsafe_release_count"] == 0
        and metrics["actual_external_model_call_count"] == 0
        else "FAIL"
    )
    if report.get("status") != expected_status:
        raise IndustrialIncidentBenchmarkValidationError(
            "IndustrialIncidentBench status does not match records"
        )
    if not (
        protocol.get("external_model_calls_allowed") is False
        and protocol.get("live_opcua_or_visionmaster_connections_allowed") is False
        and protocol.get("production_release_or_equipment_control_allowed") is False
        and report.get("actual_external_model_call_count") == 0
        and report.get("actual_external_model_token_count") == 0
        and report.get("provider_billed_api_cost_cny") == 0.0
        and report.get("data_scope") == "LOCAL_SYNTHETIC_FIXTURE_ONLY"
    ):
        raise IndustrialIncidentBenchmarkValidationError(
            "IndustrialIncidentBench execution boundary is inconsistent"
        )
    return report


__all__ = [
    "SCENARIO_CONTRACTS",
    "IndustrialIncidentBenchRun",
    "IndustrialIncidentBenchmarkValidationError",
    "build_industrial_incident_bench_manifest",
    "load_industrial_incident_benchmark_report",
    "run_industrial_incident_benchmark",
]
