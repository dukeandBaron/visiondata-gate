from __future__ import annotations

import hashlib

import pytest

from visiondata_gate.demo_fixtures import build_fixture_industrial_incident_request
from visiondata_gate.evidence import canonical_json_bytes
from visiondata_gate.incident_control_plane import (
    IncidentPlanNodeType,
    build_incident_control_plane,
    check_incident_worker_authority,
    verify_incident_control_plane,
    verify_typed_incident_plan_tree,
)
from visiondata_gate.industrial_incident import (
    IndustrialGateContext,
    IndustrialIncidentCase,
    build_industrial_incident_case,
    verify_industrial_incident_case,
)


def _sha256(value: object) -> str:
    return hashlib.sha256(canonical_json_bytes(value)).hexdigest()


def _case():
    context = IndustrialGateContext(
        task_id="task_control_plane_contract",
        gate_final_decision="PASS",
        task_evidence_sha256=_sha256("task-evidence"),
        industrial_delivery_sha256=_sha256("industrial-delivery"),
        source_profile_sha256=_sha256("source-profile"),
        source_authorization_event_sha256=_sha256("source-authorization"),
        source_kind="synthetic_demo",
        source_authorization_status="NOT_APPLICABLE",
        dynamic_response_count=1,
        open_work_order_count=1,
        remediation_plan_ids=["plan_control_plane_001"],
        model_call_count=0,
    )
    return build_industrial_incident_case(
        build_fixture_industrial_incident_request(),
        context,
    )


def test_control_plane_is_deterministic_and_binds_actual_worker_receipts() -> None:
    case = _case()

    first = build_incident_control_plane(case)
    second = build_incident_control_plane(case)

    assert first.bundle_sha256 == second.bundle_sha256
    assert {
        IncidentPlanNodeType.SEQUENCE,
        IncidentPlanNodeType.PARALLEL,
        IncidentPlanNodeType.FALLBACK,
        IncidentPlanNodeType.GUARD,
        IncidentPlanNodeType.INTERRUPT,
        IncidentPlanNodeType.REVALIDATE,
    }.issubset({node.node_type for node in first.plan_tree.nodes})
    worker_nodes = [
        node
        for node in first.plan_tree.nodes
        if node.node_type is IncidentPlanNodeType.WORKER
    ]
    assert [node.source_invocation_id for node in worker_nodes] == [
        receipt.invocation_id for receipt in case.worker_receipts
    ]
    assert first.plan_tree.execution_semantics == "OBSERVED_CASE_PROJECTION_V1"
    verify_incident_control_plane(first, case=case)


def test_typed_plan_tree_tampering_fails_closed() -> None:
    case = _case()
    tree = build_incident_control_plane(case).plan_tree
    tampered = tree.model_copy(update={"selected_path_node_ids": [tree.root_node_id]})

    with pytest.raises(ValueError, match="tree failed SHA-256"):
        verify_typed_incident_plan_tree(tampered, case=case)


def test_delayed_worker_receipt_is_rejected_after_interrupt_epoch() -> None:
    case = _case()
    ledger = build_incident_control_plane(case).authority_ledger
    receipt = case.worker_receipts[0]
    grant = ledger.capability_grants[0]

    accepted = check_incident_worker_authority(
        receipt=receipt,
        grant=grant,
        state=ledger.initial_state,
    )
    delayed = check_incident_worker_authority(
        receipt=receipt,
        grant=grant,
        state=ledger.current_state,
    )

    assert accepted.outcome == "ACCEPTED"
    assert accepted.reason_code == "AUTHORIZED_AT_EPOCH"
    assert delayed.outcome == "REJECTED"
    assert delayed.reason_code == "STALE_AUTHORITY_EPOCH"
    assert (
        ledger.current_state.authority_epoch == ledger.initial_state.authority_epoch + 1
    )
    assert all(not grant.machine_write_permitted for grant in ledger.capability_grants)
    assert all(
        not grant.production_release_permitted for grant in ledger.capability_grants
    )


def test_decision_packet_explains_hold_without_upgrading_claims() -> None:
    case = _case()
    packet = build_incident_control_plane(case).decision_packet
    contrasts = {item.action: item for item in packet.action_contrasts}

    assert packet.current_status == case.status.value
    assert packet.current_recommendation == case.recommendation.value
    assert packet.root_cause_status == "NOT_ESTABLISHED"
    assert packet.production_release_allowed is False
    assert packet.machine_write_permitted is False
    assert contrasts["CURRENT_RECOMMENDATION"].disposition == "SELECTED"
    assert contrasts["PRODUCTION_RELEASE"].disposition == "REJECTED"
    assert contrasts["CLOSE_AS_ROOT_CAUSE_ESTABLISHED"].disposition == "REJECTED"
    assert packet.what_would_change_decision
    assert len(packet.hypothesis_contrasts) >= 6


def test_rehashed_decision_packet_cannot_change_case_evidence_semantics() -> None:
    case = _case()
    bundle = build_incident_control_plane(case)
    packet_payload = bundle.decision_packet.model_dump(
        mode="json",
        exclude={"packet_sha256"},
    )
    assert packet_payload["missing_evidence_refs"]
    packet_payload["missing_evidence_refs"] = []
    tampered_packet = type(bundle.decision_packet)(
        **packet_payload,
        packet_sha256=_sha256(packet_payload),
    )
    bundle_payload = bundle.model_dump(mode="json", exclude={"bundle_sha256"})
    bundle_payload["decision_packet"] = tampered_packet.model_dump(mode="json")
    tampered_bundle = type(bundle)(
        **bundle_payload,
        bundle_sha256=_sha256(bundle_payload),
    )

    with pytest.raises(ValueError, match="changed Case evidence semantics"):
        verify_incident_control_plane(tampered_bundle, case=case)


def test_rehashed_case_cannot_change_worker_trigger_reasons() -> None:
    case = _case()
    worker_role = case.worker_receipts[0].worker_role
    actions = list(case.agent_actions)
    action_index = next(
        index
        for index, action in enumerate(actions)
        if action.dynamic and action.agent_role == worker_role
    )
    actions[action_index] = actions[action_index].model_copy(
        update={"reason_codes": ["FORGED_TRIGGER_REASON"]}
    )
    case_payload = case.model_dump(mode="json", exclude={"case_sha256"})
    case_payload["agent_actions"] = [
        action.model_dump(mode="json") for action in actions
    ]
    tampered_case = IndustrialIncidentCase(
        **case_payload,
        case_sha256=_sha256(case_payload),
    )

    with pytest.raises(ValueError, match="trigger or evidence inputs diverged"):
        verify_industrial_incident_case(tampered_case)
