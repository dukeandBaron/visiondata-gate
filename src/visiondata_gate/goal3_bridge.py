"""Hash-bound handoff from a Goal task into the Goal3 incident kernel.

The handoff is a read-only projection.  It does not manufacture industrial
evidence and it never creates an Incident implicitly.  Its only job is to make
the product transition explicit: a completed, SHA-verified Gate task may accept
an operator-authorized IndustrialIncidentRequest, while every other state fails
closed with a concrete next action.
"""

from __future__ import annotations

import hashlib
import hmac
from typing import Literal

from pydantic import Field, model_validator

from .audit_envelope import canonical_jcs_bytes
from .industrial_incident import IndustrialIncidentCase
from .product_models import (
    DataSourceKind,
    ProductModel,
    TaskExecutionStatus,
    TaskRecord,
)


Goal3HandoffStatus = Literal[
    "WAITING_FOR_TASK_COMPLETION",
    "BLOCKED_TASK_TERMINAL",
    "BLOCKED_EVIDENCE_INTEGRITY",
    "READY_FOR_INCIDENT_INTAKE",
    "INCIDENT_CHAIN_ACTIVE",
]


class Goal3HandoffReceipt(ProductModel):
    """Current, verifiable product state at the Goal -> Goal3 boundary."""

    schema_version: Literal["visiondata-gate.goal3-handoff.v1"] = (
        "visiondata-gate.goal3-handoff.v1"
    )
    task_id: str = Field(min_length=1)
    workspace_id: str = Field(min_length=1)
    project_id: str = Field(min_length=1)
    task_request_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    task_execution_status: TaskExecutionStatus
    task_final_decision: str | None
    task_evidence_sha256: str | None = Field(default=None, pattern=r"^[0-9a-f]{64}$")
    task_evidence_integrity: Literal["VERIFIED", "UNAVAILABLE", "FAILED"]
    source_kind: DataSourceKind
    handoff_status: Goal3HandoffStatus
    incident_intake_permitted: bool
    incident_count: int = Field(ge=0)
    latest_case_id: str | None = Field(default=None, pattern=r"^incident_[0-9a-f]{20}$")
    latest_case_sha256: str | None = Field(default=None, pattern=r"^[0-9a-f]{64}$")
    latest_case_version: int | None = Field(default=None, ge=1)
    latest_case_status: str | None = None
    latest_case_recommendation: str | None = None
    required_input_schema: Literal["visiondata-gate.industrial-incident-request.v3"] = (
        "visiondata-gate.industrial-incident-request.v3"
    )
    accepted_replay_schemas: list[
        Literal[
            "visiondata-gate.industrial-incident-request.v1",
            "visiondata-gate.industrial-incident-request.v2",
        ]
    ] = Field(
        default_factory=lambda: [
            "visiondata-gate.industrial-incident-request.v1",
            "visiondata-gate.industrial-incident-request.v2",
        ]
    )
    next_action: str = Field(min_length=1, max_length=800)
    human_authority_required: Literal[True] = True
    production_release_allowed: Literal[False] = False
    machine_write_permitted: Literal[False] = False
    receipt_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    claim_boundary: str = (
        "This receipt proves only the local, read-only handoff state between one "
        "Goal task and the Goal3 incident intake. It does not supply missing "
        "industrial evidence, create an Incident, establish root cause, authorize "
        "production release, control equipment, or prove factory deployment."
    )

    @model_validator(mode="after")
    def validate_state_contract(self) -> Goal3HandoffReceipt:
        has_latest = self.latest_case_id is not None
        latest_values = (
            self.latest_case_sha256,
            self.latest_case_version,
            self.latest_case_status,
            self.latest_case_recommendation,
        )
        if has_latest != all(value is not None for value in latest_values):
            raise ValueError("latest Incident fields must travel together")
        if has_latest != (self.incident_count > 0):
            raise ValueError("latest Incident fields must match incident_count")
        if self.incident_intake_permitted != (
            self.task_execution_status is TaskExecutionStatus.COMPLETED
            and self.task_evidence_integrity == "VERIFIED"
        ):
            raise ValueError("Incident intake permission diverged from task evidence")
        if self.handoff_status == "INCIDENT_CHAIN_ACTIVE" and not has_latest:
            raise ValueError("active Incident chain requires a latest case")
        return self


def _receipt_sha256(payload: object) -> str:
    return hashlib.sha256(canonical_jcs_bytes(payload)).hexdigest()


def build_goal3_handoff_receipt(
    *,
    task: TaskRecord,
    task_evidence_integrity: Literal["VERIFIED", "UNAVAILABLE", "FAILED"],
    incidents: list[IndustrialIncidentCase],
) -> Goal3HandoffReceipt:
    latest = incidents[-1] if incidents else None
    if task.execution_status in {
        TaskExecutionStatus.CREATED,
        TaskExecutionStatus.PLANNED,
        TaskExecutionStatus.RUNNING,
        TaskExecutionStatus.VERIFYING,
    }:
        handoff_status = "WAITING_FOR_TASK_COMPLETION"
        next_action = (
            "Complete the Goal task and verify its immutable evidence package before "
            "opening Goal3 incident intake."
        )
    elif task.execution_status is not TaskExecutionStatus.COMPLETED:
        handoff_status = "BLOCKED_TASK_TERMINAL"
        next_action = (
            "Create a new controlled Goal task; failed, cancelled, or archived tasks "
            "cannot enter Goal3 incident intake."
        )
    elif task_evidence_integrity != "VERIFIED":
        handoff_status = "BLOCKED_EVIDENCE_INTEGRITY"
        next_action = (
            "Restore and verify the task evidence package. Do not import an Incident "
            "against missing or mismatched evidence."
        )
    elif latest is not None:
        handoff_status = "INCIDENT_CHAIN_ACTIVE"
        next_action = (
            "Open the latest Goal3 Incident, review its observable evidence and "
            "record any high-risk decision through the named human gate."
        )
    else:
        handoff_status = "READY_FOR_INCIDENT_INTAKE"
        next_action = (
            "Import an operator-authorized IndustrialIncidentRequest v3. The request "
            "must carry offline industrial evidence and explicit safety attestations."
        )

    stable = {
        "schema_version": "visiondata-gate.goal3-handoff.v1",
        "task_id": task.task_id,
        "workspace_id": task.workspace_id,
        "project_id": task.project_id,
        "task_request_sha256": task.request_sha256,
        "task_execution_status": task.execution_status,
        "task_final_decision": task.final_decision,
        "task_evidence_sha256": task.evidence_sha256,
        "task_evidence_integrity": task_evidence_integrity,
        "source_kind": task.source_kind,
        "handoff_status": handoff_status,
        "incident_intake_permitted": (
            task.execution_status is TaskExecutionStatus.COMPLETED
            and task_evidence_integrity == "VERIFIED"
        ),
        "incident_count": len(incidents),
        "latest_case_id": latest.case_id if latest is not None else None,
        "latest_case_sha256": latest.case_sha256 if latest is not None else None,
        "latest_case_version": latest.case_version if latest is not None else None,
        "latest_case_status": latest.status.value if latest is not None else None,
        "latest_case_recommendation": (
            latest.recommendation.value if latest is not None else None
        ),
        "required_input_schema": "visiondata-gate.industrial-incident-request.v3",
        "accepted_replay_schemas": [
            "visiondata-gate.industrial-incident-request.v1",
            "visiondata-gate.industrial-incident-request.v2",
        ],
        "next_action": next_action,
        "human_authority_required": True,
        "production_release_allowed": False,
        "machine_write_permitted": False,
        "claim_boundary": Goal3HandoffReceipt.model_fields["claim_boundary"].default,
    }
    return Goal3HandoffReceipt(
        **stable,
        receipt_sha256=_receipt_sha256(stable),
    )


def verify_goal3_handoff_receipt(receipt: Goal3HandoffReceipt) -> None:
    stable = receipt.model_dump(mode="json", exclude={"receipt_sha256"})
    observed = _receipt_sha256(stable)
    if not hmac.compare_digest(observed, receipt.receipt_sha256):
        raise ValueError("Goal3 handoff receipt failed SHA-256 verification")


__all__ = [
    "Goal3HandoffReceipt",
    "Goal3HandoffStatus",
    "build_goal3_handoff_receipt",
    "verify_goal3_handoff_receipt",
]
