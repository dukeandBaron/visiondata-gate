from __future__ import annotations

import hashlib

import pytest

from visiondata_gate.evidence import canonical_json_bytes
from visiondata_gate.incident_commands import (
    IncidentCommandAdmission,
    IncidentCommandKind,
    IncidentCommandStatus,
    IncidentCommandTerminal,
    build_incident_command_admission,
    build_incident_command_receipt,
    build_incident_command_terminal,
    incident_command_id,
    resolve_incident_idempotency_key,
    verify_incident_command_admission,
    verify_incident_command_terminal,
)

TASK_ID = "task_incident_contract"
CASE_ID = "incident_0123456789abcdefabcd"
ACTOR_ID = "usr_quality_owner"
RESOURCE_SHA256 = hashlib.sha256(b"incident-resource").hexdigest()


def _request(*, revision: int = 1) -> dict[str, object]:
    return {
        "schema_version": "test.incident-command-request.v1",
        "revision": revision,
        "operator_attests_inputs_authorized": True,
    }


def _admission(
    *,
    operation: IncidentCommandKind = IncidentCommandKind.RESUME_CASE,
    request: object | None = None,
    actor_user_id: str = ACTOR_ID,
) -> IncidentCommandAdmission:
    payload = _request() if request is None else request
    idempotency_key = resolve_incident_idempotency_key(None, payload)
    target_case_id = None if operation is IncidentCommandKind.CREATE_CASE else CASE_ID
    command_id = incident_command_id(
        task_id=TASK_ID,
        operation=operation,
        target_case_id=target_case_id,
        idempotency_key=idempotency_key,
    )
    return build_incident_command_admission(
        command_id=command_id,
        operation=operation,
        task_id=TASK_ID,
        target_case_id=target_case_id,
        actor_user_id=actor_user_id,
        idempotency_key=idempotency_key,
        request=payload,
        expected_case_sha256=(
            None if operation is IncidentCommandKind.CREATE_CASE else RESOURCE_SHA256
        ),
    )


def _reseal_terminal(
    terminal: IncidentCommandTerminal,
    **updates: object,
) -> IncidentCommandTerminal:
    payload = terminal.model_dump(mode="json", exclude={"terminal_sha256"})
    payload.update(updates)
    terminal_sha256 = hashlib.sha256(canonical_json_bytes(payload)).hexdigest()
    return terminal.model_copy(update={**updates, "terminal_sha256": terminal_sha256})


def test_admission_and_terminal_sha256_detect_tampering() -> None:
    admission = _admission()
    verify_incident_command_admission(admission)

    terminal = build_incident_command_terminal(
        admission,
        status="COMPLETED",
        resource_kind="incident_case",
        resource_id="incident_fedcba9876543210fedc",
        resource_sha256=RESOURCE_SHA256,
    )
    verify_incident_command_terminal(terminal, admission=admission)

    tampered_admission = admission.model_copy(update={"request_sha256": "f" * 64})
    with pytest.raises(ValueError, match="admission failed SHA-256"):
        verify_incident_command_admission(tampered_admission)

    tampered_terminal = terminal.model_copy(
        update={"resource_id": "incident_aaaaaaaaaaaaaaaaaaaa"}
    )
    with pytest.raises(ValueError, match="terminal failed SHA-256"):
        verify_incident_command_terminal(
            tampered_terminal,
            admission=admission,
        )


def test_default_idempotency_key_is_stable_for_the_same_request() -> None:
    first_request = _request()
    equivalent_request = {
        "operator_attests_inputs_authorized": True,
        "revision": 1,
        "schema_version": "test.incident-command-request.v1",
    }

    first_key = resolve_incident_idempotency_key(None, first_request)
    second_key = resolve_incident_idempotency_key(None, equivalent_request)
    changed_key = resolve_incident_idempotency_key(None, _request(revision=2))

    assert first_key == second_key
    assert first_key.startswith("auto:")
    assert changed_key != first_key
    assert incident_command_id(
        task_id=TASK_ID,
        operation=IncidentCommandKind.CREATE_CASE,
        target_case_id=None,
        idempotency_key=first_key,
    ) == incident_command_id(
        task_id=TASK_ID,
        operation=IncidentCommandKind.CREATE_CASE,
        target_case_id=None,
        idempotency_key=second_key,
    )


def test_admission_without_terminal_is_explicitly_uncertain() -> None:
    admission = _admission()

    receipt = build_incident_command_receipt(admission, None)

    assert receipt.status is IncidentCommandStatus.UNCERTAIN
    assert receipt.admission_sha256 == admission.admission_sha256
    assert receipt.terminal_sha256 is None
    assert receipt.resource_kind is None
    assert receipt.resource_id is None
    assert receipt.resource_sha256 is None
    assert receipt.error_code == "TERMINAL_RECEIPT_MISSING"
    assert "automatic replay is prohibited" in (receipt.error_message or "")


def test_terminal_rejects_a_resealed_admission_binding_tamper() -> None:
    admission = _admission()
    terminal = build_incident_command_terminal(
        admission,
        status="COMPLETED",
        resource_kind="incident_case",
        resource_id="incident_fedcba9876543210fedc",
        resource_sha256=RESOURCE_SHA256,
    )
    rebound = _reseal_terminal(terminal, admission_sha256="a" * 64)

    with pytest.raises(ValueError, match="admission binding"):
        verify_incident_command_terminal(rebound, admission=admission)


def test_completed_and_rejected_terminals_project_disjoint_fields() -> None:
    admission = _admission()
    completed = build_incident_command_terminal(
        admission,
        status="COMPLETED",
        resource_kind="incident_case",
        resource_id="incident_fedcba9876543210fedc",
        resource_sha256=RESOURCE_SHA256,
    )
    completed_receipt = build_incident_command_receipt(admission, completed)

    assert completed_receipt.status is IncidentCommandStatus.COMPLETED
    assert completed_receipt.resource_kind == "incident_case"
    assert completed_receipt.resource_id == "incident_fedcba9876543210fedc"
    assert completed_receipt.resource_sha256 == RESOURCE_SHA256
    assert completed_receipt.error_code is None
    assert completed_receipt.error_message is None

    rejected = build_incident_command_terminal(
        admission,
        status="REJECTED",
        error_code="STALE_EXPECTED_CASE",
        error_message="expected case SHA-256 no longer matches the active case",
    )
    rejected_receipt = build_incident_command_receipt(admission, rejected)

    assert rejected_receipt.status is IncidentCommandStatus.REJECTED
    assert rejected_receipt.resource_kind is None
    assert rejected_receipt.resource_id is None
    assert rejected_receipt.resource_sha256 is None
    assert rejected_receipt.error_code == "STALE_EXPECTED_CASE"
    assert rejected_receipt.error_message is not None


@pytest.mark.parametrize(
    "terminal_kwargs, expected_message",
    [
        (
            {"status": "COMPLETED"},
            "completed incident command requires a bound resource",
        ),
        (
            {
                "status": "COMPLETED",
                "resource_kind": "incident_case",
                "resource_id": "incident_fedcba9876543210fedc",
                "resource_sha256": RESOURCE_SHA256,
                "error_code": "IMPOSSIBLE_ERROR",
            },
            "completed incident command cannot contain an error",
        ),
        (
            {
                "status": "REJECTED",
                "resource_kind": "incident_case",
                "resource_id": "incident_fedcba9876543210fedc",
                "resource_sha256": RESOURCE_SHA256,
                "error_code": "REJECTED",
                "error_message": "rejected command",
            },
            "rejected incident command cannot bind a resource",
        ),
        (
            {"status": "REJECTED"},
            "rejected incident command requires a bounded error",
        ),
    ],
)
def test_terminal_field_constraints_fail_closed(
    terminal_kwargs: dict[str, object],
    expected_message: str,
) -> None:
    admission = _admission()

    with pytest.raises(ValueError, match=expected_message):
        build_incident_command_terminal(admission, **terminal_kwargs)
