"""Durable command receipts for mutating industrial-incident operations.

The command journal deliberately separates admission from a terminal result.
If a process stops after admission but before a terminal receipt is persisted,
the command is reported as ``UNCERTAIN`` and is never replayed automatically.
"""

from __future__ import annotations

import hashlib
import hmac
from datetime import UTC, datetime
from enum import Enum
from typing import Literal

from pydantic import Field

from .evidence import canonical_json_bytes
from .product_models import ProductModel


class IncidentCommandKind(str, Enum):
    CREATE_CASE = "CREATE_CASE"
    RECORD_DECISION = "RECORD_DECISION"
    RESUME_CASE = "RESUME_CASE"


class IncidentCommandStatus(str, Enum):
    COMPLETED = "COMPLETED"
    REJECTED = "REJECTED"
    UNCERTAIN = "UNCERTAIN"


class IncidentCommandAdmission(ProductModel):
    schema_version: Literal["visiondata-gate.incident-command-admission.v1"] = (
        "visiondata-gate.incident-command-admission.v1"
    )
    command_id: str = Field(pattern=r"^incident_command_[0-9a-f]{24}$")
    operation: IncidentCommandKind
    task_id: str = Field(min_length=1, max_length=160)
    target_case_id: str | None = Field(default=None, pattern=r"^incident_[0-9a-f]{20}$")
    actor_user_id: str = Field(min_length=1, max_length=160)
    idempotency_key_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    request_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    expected_case_sha256: str | None = Field(default=None, pattern=r"^[0-9a-f]{64}$")
    admitted_at: datetime
    admission_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")


class IncidentCommandTerminal(ProductModel):
    schema_version: Literal["visiondata-gate.incident-command-terminal.v1"] = (
        "visiondata-gate.incident-command-terminal.v1"
    )
    command_id: str = Field(pattern=r"^incident_command_[0-9a-f]{24}$")
    admission_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    status: Literal["COMPLETED", "REJECTED"]
    resource_kind: Literal["incident_case", "incident_decision"] | None = None
    resource_id: str | None = Field(default=None, min_length=1, max_length=160)
    resource_sha256: str | None = Field(default=None, pattern=r"^[0-9a-f]{64}$")
    error_code: str | None = Field(default=None, min_length=1, max_length=120)
    error_message: str | None = Field(default=None, min_length=1, max_length=500)
    terminal_at: datetime
    terminal_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")


class IncidentCommandReceipt(ProductModel):
    schema_version: Literal["visiondata-gate.incident-command-receipt.v1"] = (
        "visiondata-gate.incident-command-receipt.v1"
    )
    command_id: str = Field(pattern=r"^incident_command_[0-9a-f]{24}$")
    operation: IncidentCommandKind
    task_id: str
    target_case_id: str | None
    actor_user_id: str
    idempotency_key_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    request_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    expected_case_sha256: str | None = Field(default=None, pattern=r"^[0-9a-f]{64}$")
    status: IncidentCommandStatus
    admission_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    terminal_sha256: str | None = Field(default=None, pattern=r"^[0-9a-f]{64}$")
    resource_kind: Literal["incident_case", "incident_decision"] | None = None
    resource_id: str | None = None
    resource_sha256: str | None = Field(default=None, pattern=r"^[0-9a-f]{64}$")
    error_code: str | None = None
    error_message: str | None = None
    admitted_at: datetime
    terminal_at: datetime | None = None
    boundary_notice: str = (
        "COMPLETED proves that a local immutable result receipt was persisted. "
        "UNCERTAIN means admission exists without a terminal receipt; the command "
        "must not be replayed automatically and does not imply that no side effect "
        "occurred. This is not a production release or equipment-control receipt."
    )


def _sha256(value: object) -> str:
    return hashlib.sha256(canonical_json_bytes(value)).hexdigest()


def normalize_incident_idempotency_key(value: str) -> str:
    normalized = value.strip()
    if not normalized:
        raise ValueError("incident idempotency key cannot be blank")
    if len(normalized) > 120:
        raise ValueError("incident idempotency key exceeds 120 characters")
    return normalized


def resolve_incident_idempotency_key(value: str | None, request: object) -> str:
    """Return an explicit key or a deterministic request-bound fallback.

    The fallback keeps direct Python callers and older API clients idempotent
    without adding transport metadata to ``IndustrialIncidentRequest`` (which
    would incorrectly change the industrial evidence-bundle identity).
    """

    if value is not None:
        return normalize_incident_idempotency_key(value)
    return f"auto:{_sha256(request)}"


def incident_command_id(
    *,
    task_id: str,
    operation: IncidentCommandKind,
    target_case_id: str | None,
    idempotency_key: str,
) -> str:
    normalized = normalize_incident_idempotency_key(idempotency_key)
    digest = _sha256(
        {
            "task_id": task_id,
            "operation": operation.value,
            "target_case_id": target_case_id,
            "idempotency_key": normalized,
        }
    )
    return f"incident_command_{digest[:24]}"


def build_incident_command_admission(
    *,
    command_id: str,
    operation: IncidentCommandKind,
    task_id: str,
    target_case_id: str | None,
    actor_user_id: str,
    idempotency_key: str,
    request: object,
    expected_case_sha256: str | None,
) -> IncidentCommandAdmission:
    normalized = normalize_incident_idempotency_key(idempotency_key)
    stable = {
        "schema_version": "visiondata-gate.incident-command-admission.v1",
        "command_id": command_id,
        "operation": operation.value,
        "task_id": task_id,
        "target_case_id": target_case_id,
        "actor_user_id": actor_user_id,
        "idempotency_key_sha256": _sha256(normalized),
        "request_sha256": _sha256(request),
        "expected_case_sha256": expected_case_sha256,
        "admitted_at": datetime.now(UTC),
    }
    return IncidentCommandAdmission(
        **stable,
        admission_sha256=_sha256(stable),
    )


def verify_incident_command_admission(
    admission: IncidentCommandAdmission,
) -> None:
    stable = admission.model_dump(mode="json", exclude={"admission_sha256"})
    if not hmac.compare_digest(_sha256(stable), admission.admission_sha256):
        raise ValueError("incident command admission failed SHA-256 validation")


def build_incident_command_terminal(
    admission: IncidentCommandAdmission,
    *,
    status: Literal["COMPLETED", "REJECTED"],
    resource_kind: Literal["incident_case", "incident_decision"] | None = None,
    resource_id: str | None = None,
    resource_sha256: str | None = None,
    error_code: str | None = None,
    error_message: str | None = None,
) -> IncidentCommandTerminal:
    if status == "COMPLETED":
        if not resource_kind or not resource_id or not resource_sha256:
            raise ValueError("completed incident command requires a bound resource")
        if error_code is not None or error_message is not None:
            raise ValueError("completed incident command cannot contain an error")
    elif resource_kind is not None or resource_id is not None or resource_sha256:
        raise ValueError("rejected incident command cannot bind a resource")
    if status == "REJECTED" and (not error_code or not error_message):
        raise ValueError("rejected incident command requires a bounded error")

    stable = {
        "schema_version": "visiondata-gate.incident-command-terminal.v1",
        "command_id": admission.command_id,
        "admission_sha256": admission.admission_sha256,
        "status": status,
        "resource_kind": resource_kind,
        "resource_id": resource_id,
        "resource_sha256": resource_sha256,
        "error_code": error_code,
        "error_message": error_message,
        "terminal_at": datetime.now(UTC),
    }
    return IncidentCommandTerminal(**stable, terminal_sha256=_sha256(stable))


def verify_incident_command_terminal(
    terminal: IncidentCommandTerminal,
    *,
    admission: IncidentCommandAdmission,
) -> None:
    verify_incident_command_admission(admission)
    stable = terminal.model_dump(mode="json", exclude={"terminal_sha256"})
    if not hmac.compare_digest(_sha256(stable), terminal.terminal_sha256):
        raise ValueError("incident command terminal failed SHA-256 validation")
    if (
        terminal.command_id != admission.command_id
        or terminal.admission_sha256 != admission.admission_sha256
    ):
        raise ValueError("incident command terminal failed admission binding")


def build_incident_command_receipt(
    admission: IncidentCommandAdmission,
    terminal: IncidentCommandTerminal | None,
) -> IncidentCommandReceipt:
    verify_incident_command_admission(admission)
    if terminal is None:
        return IncidentCommandReceipt(
            command_id=admission.command_id,
            operation=admission.operation,
            task_id=admission.task_id,
            target_case_id=admission.target_case_id,
            actor_user_id=admission.actor_user_id,
            idempotency_key_sha256=admission.idempotency_key_sha256,
            request_sha256=admission.request_sha256,
            expected_case_sha256=admission.expected_case_sha256,
            status=IncidentCommandStatus.UNCERTAIN,
            admission_sha256=admission.admission_sha256,
            error_code="TERMINAL_RECEIPT_MISSING",
            error_message=(
                "admission exists without a terminal receipt; automatic replay "
                "is prohibited"
            ),
            admitted_at=admission.admitted_at,
        )

    verify_incident_command_terminal(terminal, admission=admission)
    return IncidentCommandReceipt(
        command_id=admission.command_id,
        operation=admission.operation,
        task_id=admission.task_id,
        target_case_id=admission.target_case_id,
        actor_user_id=admission.actor_user_id,
        idempotency_key_sha256=admission.idempotency_key_sha256,
        request_sha256=admission.request_sha256,
        expected_case_sha256=admission.expected_case_sha256,
        status=IncidentCommandStatus(terminal.status),
        admission_sha256=admission.admission_sha256,
        terminal_sha256=terminal.terminal_sha256,
        resource_kind=terminal.resource_kind,
        resource_id=terminal.resource_id,
        resource_sha256=terminal.resource_sha256,
        error_code=terminal.error_code,
        error_message=terminal.error_message,
        admitted_at=admission.admitted_at,
        terminal_at=terminal.terminal_at,
    )


__all__ = [
    "IncidentCommandAdmission",
    "IncidentCommandKind",
    "IncidentCommandReceipt",
    "IncidentCommandStatus",
    "IncidentCommandTerminal",
    "build_incident_command_admission",
    "build_incident_command_receipt",
    "build_incident_command_terminal",
    "incident_command_id",
    "normalize_incident_idempotency_key",
    "resolve_incident_idempotency_key",
    "verify_incident_command_admission",
    "verify_incident_command_terminal",
]
