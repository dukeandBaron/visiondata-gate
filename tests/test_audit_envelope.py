from __future__ import annotations

import hashlib

import pytest

from visiondata_gate.audit_envelope import (
    AuditArtifactStatus,
    AuditHashDomain,
    GovernedAuditEnvelope,
    build_governed_audit_envelope,
    canonical_jcs_bytes,
    domain_separated_sha256,
    parse_governed_audit_envelope_json,
    verify_governed_audit_envelope,
)
from visiondata_gate.demo_fixtures import build_fixture_industrial_incident_request
from visiondata_gate.incident_control_plane import build_incident_control_plane
from visiondata_gate.incident_runtime_profile import build_runtime_profile_binding
from visiondata_gate.industrial_incident import (
    IndustrialGateContext,
    build_incident_phase_events,
    build_industrial_incident_case,
    incident_runtime_profile,
)


def _digest(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _audit_inputs():
    request = build_fixture_industrial_incident_request()
    context = IndustrialGateContext(
        task_id="task_0123456789abcdef",
        gate_final_decision="PASS",
        task_evidence_sha256=_digest("task-evidence"),
        industrial_delivery_sha256=_digest("industrial-delivery"),
        source_profile_sha256=_digest("source-profile"),
        source_authorization_event_sha256=_digest("source-authorization"),
        dynamic_response_count=3,
        open_work_order_count=0,
        remediation_plan_ids=[],
        model_call_count=0,
    )
    case = build_industrial_incident_case(request, context)
    events = build_incident_phase_events(case)
    control_plane = build_incident_control_plane(case)
    profile = incident_runtime_profile(case.request)
    assert profile is not None
    binding = build_runtime_profile_binding(
        case_id=case.case_id,
        case_sha256=case.case_sha256,
        profile=profile,
        planner_config_sha256=None,
        planner_connection_status="OFF",
        governed_context_receipt_sha256=None,
        selected_memory_count=0,
        rejected_memory_count=0,
    )
    return case, events, control_plane, binding


def test_rfc8785_jcs_and_domain_digest_have_frozen_golden() -> None:
    payload = {"b": 1, "a": "中", "n": 0.0}

    assert canonical_jcs_bytes(payload) == b'{"a":"\xe4\xb8\xad","b":1,"n":0}'
    assert domain_separated_sha256(payload, AuditHashDomain.CASE) == (
        "cf69092957d5e0268e62c659a2372ce8f7ae26df7cfe809b3c1d3597066630a5"
    )
    assert canonical_jcs_bytes({"n": 0.0, "a": "中", "b": 1}) == (
        canonical_jcs_bytes(payload)
    )


@pytest.mark.parametrize("invalid", [float("nan"), float("inf"), 2**60])
def test_rfc8785_rejects_values_outside_ijson_number_domain(invalid: object) -> None:
    with pytest.raises(ValueError, match="RFC 8785"):
        canonical_jcs_bytes({"value": invalid})


def test_hash_domains_are_fixed_and_isolated() -> None:
    payload = {"same": "payload"}

    assert domain_separated_sha256(payload, AuditHashDomain.CASE) != (
        domain_separated_sha256(payload, AuditHashDomain.PHASE_EVENT)
    )
    with pytest.raises(ValueError):
        AuditHashDomain("client-selected/custom-domain")


def test_audit_envelope_parser_rejects_duplicate_json_members() -> None:
    duplicate = (
        '{"schema_version":"visiondata-gate.governed-audit-envelope.v1",'
        '"schema_version":"visiondata-gate.governed-audit-envelope.v1"}'
    )

    with pytest.raises(ValueError, match="duplicate JSON member"):
        parse_governed_audit_envelope_json(duplicate)


def test_governed_audit_envelope_rebuilds_and_verifies_independently() -> None:
    case, events, control_plane, binding = _audit_inputs()
    envelope = build_governed_audit_envelope(
        case,
        phase_events=events,
        issuer_actor_id="user_local_operator",
        workspace_id="workspace_evaluation",
        project_id="project_image_gate",
        control_plane=control_plane,
        runtime_profile_binding=binding,
    )

    assert envelope.subject.legacy_case_sha256 == case.case_sha256
    assert envelope.subject.audit_digest.hash_domain is AuditHashDomain.CASE
    assert envelope.audit_root.hash_domain is AuditHashDomain.AUDIT_ROOT
    assert envelope.signature.status == "NOT_CONFIGURED"
    assert [item.status for item in envelope.governance] == [
        AuditArtifactStatus.BOUND,
        AuditArtifactStatus.NOT_APPLICABLE,
        AuditArtifactStatus.NOT_APPLICABLE,
        AuditArtifactStatus.BOUND,
    ]
    verify_governed_audit_envelope(
        envelope,
        case=case,
        phase_events=events,
        control_plane=control_plane,
        runtime_profile_binding=binding,
        expected_workspace_id="workspace_evaluation",
        expected_project_id="project_image_gate",
    )


def test_envelope_tampering_and_event_reordering_fail_closed() -> None:
    case, events, control_plane, binding = _audit_inputs()
    envelope = build_governed_audit_envelope(
        case,
        phase_events=events,
        issuer_actor_id="user_local_operator",
        workspace_id="workspace_evaluation",
        project_id="project_image_gate",
        control_plane=control_plane,
        runtime_profile_binding=binding,
    )
    tampered = envelope.model_dump(mode="json")
    tampered["issuer"]["actor_id"] = "forged_operator"
    parsed_tampered = GovernedAuditEnvelope.model_validate(tampered)

    with pytest.raises(ValueError, match="audit-root"):
        verify_governed_audit_envelope(
            parsed_tampered,
            case=case,
            phase_events=events,
            control_plane=control_plane,
            runtime_profile_binding=binding,
        )
    with pytest.raises(ValueError, match="phase event"):
        verify_governed_audit_envelope(
            envelope,
            case=case,
            phase_events=list(reversed(events)),
            control_plane=control_plane,
            runtime_profile_binding=binding,
        )
