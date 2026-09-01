"""Single-entry, evidence-bound outcome projection for a completed CAPA flow.

The envelope does not replace any source artifact. It binds already-verified
Incident, human-decision, CAPA, child-run, and responsibility-queue artifacts
into one deterministic RFC 8785/JCS root for reviewer inspection.

The root is tamper-evident only when retained or published independently. It is
not a digital signature, trusted timestamp, causal proof, or production release.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from enum import Enum
import hashlib
import hmac
import json
from typing import Any, Literal

from pydantic import BaseModel, Field, model_validator

from .audit_envelope import (
    AUDIT_CANONICALIZATION_PROFILE,
    AuditHashDomain,
    AuditSignature,
    GovernedAuditEnvelope,
    canonical_jcs_bytes,
    domain_separated_sha256,
)
from .capa import (
    CapaCaseReport,
    CapaOutcomeAssessment,
    verify_sealed_model,
)
from .contracts import GateResult
from .industrial_incident import (
    IndustrialIncidentCase,
    IndustrialIncidentDecisionReceipt,
    verify_industrial_incident_case,
    verify_industrial_incident_decision_receipt,
)
from .product_models import ProductModel


OUTCOME_PROTOCOL_ID = "visiondata-gate.governed-outcome-envelope.v1"
OUTCOME_FRAMING_PROFILE = "visiondata-gate-outcome-domain-frame-v1"
OUTCOME_FRAME_MAGIC = b"visiondata-gate.outcome-frame.v1\x00"


class OutcomeHashDomain(str, Enum):
    PARENT_GATE = "visiondata-gate/outcome/parent-gate/v1"
    INCIDENT_CASE = "visiondata-gate/outcome/incident-case/v1"
    INCIDENT_AUDIT = "visiondata-gate/outcome/incident-audit/v1"
    HUMAN_DECISION = "visiondata-gate/outcome/human-decision/v1"
    CAPA_SELECTION = "visiondata-gate/outcome/capa-selection/v1"
    CAPA_APPROVAL = "visiondata-gate/outcome/capa-approval/v1"
    DERIVED_VERSION = "visiondata-gate/outcome/derived-version/v1"
    CAPA_EXECUTION = "visiondata-gate/outcome/capa-execution/v1"
    CHILD_GATE = "visiondata-gate/outcome/child-gate/v1"
    FINAL_QUEUE = "visiondata-gate/outcome/final-responsibility-queue/v1"
    RECOVERY = "visiondata-gate/outcome/recovery/v1"
    OUTCOME_ASSESSMENT = "visiondata-gate/outcome/assessment/v1"
    OUTCOME_ROOT = "visiondata-gate/outcome/root/v1"


class OutcomeArtifactType(str, Enum):
    PARENT_GATE_RESULT = "PARENT_GATE_RESULT"
    INCIDENT_CASE = "INCIDENT_CASE"
    INCIDENT_AUDIT_ENVELOPE = "INCIDENT_AUDIT_ENVELOPE"
    HUMAN_INCIDENT_DECISION = "HUMAN_INCIDENT_DECISION"
    CAPA_SELECTION = "CAPA_SELECTION"
    CAPA_APPROVAL = "CAPA_APPROVAL"
    DERIVED_DATA_VERSION = "DERIVED_DATA_VERSION"
    CAPA_EXECUTION = "CAPA_EXECUTION"
    CHILD_GATE_RESULT = "CHILD_GATE_RESULT"
    FINAL_RESPONSIBILITY_QUEUE = "FINAL_RESPONSIBILITY_QUEUE"
    CAPA_RECOVERY = "CAPA_RECOVERY"
    CAPA_OUTCOME_ASSESSMENT = "CAPA_OUTCOME_ASSESSMENT"


class UpstreamIntegrityKind(str, Enum):
    EVIDENCE_ARCHIVE_SHA256 = "EVIDENCE_ARCHIVE_SHA256"
    LEGACY_SELF_SEAL_SHA256 = "LEGACY_SELF_SEAL_SHA256"
    GOVERNED_AUDIT_ROOT = "GOVERNED_AUDIT_ROOT"


_ARTIFACT_DOMAINS = {
    OutcomeArtifactType.PARENT_GATE_RESULT: OutcomeHashDomain.PARENT_GATE,
    OutcomeArtifactType.INCIDENT_CASE: OutcomeHashDomain.INCIDENT_CASE,
    OutcomeArtifactType.INCIDENT_AUDIT_ENVELOPE: OutcomeHashDomain.INCIDENT_AUDIT,
    OutcomeArtifactType.HUMAN_INCIDENT_DECISION: OutcomeHashDomain.HUMAN_DECISION,
    OutcomeArtifactType.CAPA_SELECTION: OutcomeHashDomain.CAPA_SELECTION,
    OutcomeArtifactType.CAPA_APPROVAL: OutcomeHashDomain.CAPA_APPROVAL,
    OutcomeArtifactType.DERIVED_DATA_VERSION: OutcomeHashDomain.DERIVED_VERSION,
    OutcomeArtifactType.CAPA_EXECUTION: OutcomeHashDomain.CAPA_EXECUTION,
    OutcomeArtifactType.CHILD_GATE_RESULT: OutcomeHashDomain.CHILD_GATE,
    OutcomeArtifactType.FINAL_RESPONSIBILITY_QUEUE: OutcomeHashDomain.FINAL_QUEUE,
    OutcomeArtifactType.CAPA_RECOVERY: OutcomeHashDomain.RECOVERY,
    OutcomeArtifactType.CAPA_OUTCOME_ASSESSMENT: (OutcomeHashDomain.OUTCOME_ASSESSMENT),
}
_ARTIFACT_ORDER = tuple(OutcomeArtifactType)


def _json_value(value: Any) -> Any:
    if isinstance(value, BaseModel):
        return _json_value(value.model_dump(mode="json"))
    if isinstance(value, Enum):
        return value.value
    if isinstance(value, Mapping):
        normalized: dict[str, Any] = {}
        for key, item in value.items():
            if not isinstance(key, str):
                raise TypeError("outcome JCS objects require string property names")
            normalized[key] = _json_value(item)
        return normalized
    if isinstance(value, Sequence) and not isinstance(
        value, (str, bytes, bytearray, memoryview)
    ):
        return [_json_value(item) for item in value]
    if value is None or isinstance(value, (bool, int, float, str)):
        return value
    raise TypeError(f"unsupported outcome JSON value: {type(value).__name__}")


def _outcome_frame(value: Any, domain: OutcomeHashDomain) -> bytes:
    payload = canonical_jcs_bytes(_json_value(value))
    domain_bytes = domain.value.encode("utf-8")
    if len(domain_bytes) > 0xFFFF:
        raise ValueError("outcome hash domain is too long")
    return b"".join(
        (
            OUTCOME_FRAME_MAGIC,
            len(domain_bytes).to_bytes(2, "big"),
            domain_bytes,
            len(payload).to_bytes(8, "big"),
            payload,
        )
    )


def outcome_domain_sha256(value: Any, domain: OutcomeHashDomain) -> str:
    return hashlib.sha256(_outcome_frame(value, domain)).hexdigest()


class OutcomeDigestDescriptor(ProductModel):
    algorithm: Literal["sha256"] = "sha256"
    canonicalization_profile: Literal["rfc8785-jcs-v1"] = AUDIT_CANONICALIZATION_PROFILE
    framing_profile: Literal["visiondata-gate-outcome-domain-frame-v1"] = (
        OUTCOME_FRAMING_PROFILE
    )
    frame_magic_utf8: Literal["visiondata-gate.outcome-frame.v1\\u0000"] = (
        "visiondata-gate.outcome-frame.v1\\u0000"
    )
    hash_domain: OutcomeHashDomain
    value: str = Field(pattern=r"^[0-9a-f]{64}$")


def outcome_digest_descriptor(
    value: Any, domain: OutcomeHashDomain
) -> OutcomeDigestDescriptor:
    return OutcomeDigestDescriptor(
        hash_domain=domain,
        value=outcome_domain_sha256(value, domain),
    )


class OutcomeProtocolDescriptor(ProductModel):
    protocol_id: Literal["visiondata-gate.governed-outcome-envelope.v1"] = (
        OUTCOME_PROTOCOL_ID
    )
    digest_algorithm: Literal["sha256"] = "sha256"
    canonicalization_profile: Literal["rfc8785-jcs-v1"] = AUDIT_CANONICALIZATION_PROFILE
    framing_profile: Literal["visiondata-gate-outcome-domain-frame-v1"] = (
        OUTCOME_FRAMING_PROFILE
    )
    frame_construction: Literal[
        "magic || uint16be(domain_length) || domain || "
        "uint64be(payload_length) || rfc8785_payload"
    ] = (
        "magic || uint16be(domain_length) || domain || "
        "uint64be(payload_length) || rfc8785_payload"
    )
    frame_magic_utf8: Literal["visiondata-gate.outcome-frame.v1\\u0000"] = (
        "visiondata-gate.outcome-frame.v1\\u0000"
    )


class GovernedOutcomeIssuer(ProductModel):
    issuer_type: Literal["VISIONDATA_GATE_PRODUCT_SERVICE"] = (
        "VISIONDATA_GATE_PRODUCT_SERVICE"
    )
    actor_id: str = Field(min_length=1, max_length=160)
    workspace_id: str = Field(min_length=1, max_length=160)
    project_id: str = Field(min_length=1, max_length=160)
    identity_assurance: Literal["LOCAL_APPLICATION_RECORD_ONLY"] = (
        "LOCAL_APPLICATION_RECORD_ONLY"
    )


class GovernedOutcomeSubject(ProductModel):
    parent_task_id: str = Field(min_length=1, max_length=160)
    incident_case_id: str = Field(pattern=r"^incident_[0-9a-f]{20}$")
    capa_case_id: str = Field(pattern=r"^capa_[0-9a-f]{20}$")
    child_task_id: str = Field(min_length=1, max_length=160)


class OutcomeArtifactBinding(ProductModel):
    artifact_type: OutcomeArtifactType
    resource_id: str = Field(min_length=1, max_length=200)
    artifact_schema_version: str = Field(min_length=1, max_length=160)
    upstream_integrity_kind: UpstreamIntegrityKind
    upstream_integrity_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    content_digest: OutcomeDigestDescriptor

    @model_validator(mode="after")
    def validate_content_domain(self) -> OutcomeArtifactBinding:
        if self.content_digest.hash_domain is not _ARTIFACT_DOMAINS[self.artifact_type]:
            raise ValueError("outcome artifact uses an invalid hash domain")
        return self


class OutcomeHumanAuthority(ProductModel):
    incident_decision_id: str = Field(pattern=r"^incident_decision_[0-9a-f]{20}$")
    incident_decided_by: str = Field(min_length=1, max_length=160)
    capa_approved_by: str = Field(min_length=1, max_length=160)
    incident_decision_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    capa_approval_binding_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    production_decision_authority: Literal["human_only"] = "human_only"
    external_release_review_still_required: Literal[True] = True


class OutcomeResultBoundary(ProductModel):
    workflow_status: Literal[
        "RECOVERED_TO_HUMAN_REVIEW",
        "STILL_BLOCKED",
        "TRANSFERRED_TO_INVESTIGATION",
    ]
    parent_gate_decision: str = Field(min_length=1, max_length=80)
    child_gate_decision: str = Field(min_length=1, max_length=80)
    child_non_regression_disposition: str = Field(min_length=1, max_length=120)
    release_feasibility_status: str = Field(min_length=1, max_length=160)
    selected_work_order_count: int = Field(ge=1)
    verified_closed_work_order_count: int = Field(ge=0)
    total_responsibility_item_count: int = Field(ge=1)
    open_responsibility_item_count: int = Field(ge=0)
    closed_responsibility_item_count: int = Field(ge=0)
    root_cause_status: Literal["NOT_ESTABLISHED"] = "NOT_ESTABLISHED"
    human_approval_required: Literal[True] = True
    production_release_allowed: Literal[False] = False
    machine_write_permitted: Literal[False] = False
    direct_equipment_control_permitted: Literal[False] = False
    required_human_action: str = Field(min_length=1, max_length=1600)
    claim_boundary: str = (
        "This projection reports a bounded local evidence workflow. Child-run "
        "improvement is not root-cause proof, customer acceptance, safety "
        "certification, or production authorization."
    )


class GovernedOutcomeEnvelope(ProductModel):
    schema_version: Literal["visiondata-gate.governed-outcome-envelope.v1"] = (
        OUTCOME_PROTOCOL_ID
    )
    protocol: OutcomeProtocolDescriptor
    issuer: GovernedOutcomeIssuer
    subject: GovernedOutcomeSubject
    artifacts: list[OutcomeArtifactBinding] = Field(
        min_length=len(_ARTIFACT_ORDER), max_length=len(_ARTIFACT_ORDER)
    )
    human_authority: OutcomeHumanAuthority
    result: OutcomeResultBoundary
    signature: AuditSignature
    claim_boundary: Literal[
        "TAMPER_EVIDENT_LOCAL_OUTCOME_PROJECTION_NOT_SIGNATURE_TRUSTED_TIME_"
        "CAUSAL_PROOF_OR_PRODUCTION_RELEASE"
    ] = (
        "TAMPER_EVIDENT_LOCAL_OUTCOME_PROJECTION_NOT_SIGNATURE_TRUSTED_TIME_"
        "CAUSAL_PROOF_OR_PRODUCTION_RELEASE"
    )
    outcome_root: OutcomeDigestDescriptor

    @model_validator(mode="after")
    def validate_protocol_shape(self) -> GovernedOutcomeEnvelope:
        observed_order = tuple(item.artifact_type for item in self.artifacts)
        if observed_order != _ARTIFACT_ORDER:
            raise ValueError("outcome artifact bindings use an invalid order or set")
        if self.outcome_root.hash_domain is not OutcomeHashDomain.OUTCOME_ROOT:
            raise ValueError("outcome root uses an invalid hash domain")
        if (
            self.result.open_responsibility_item_count
            + self.result.closed_responsibility_item_count
            != self.result.total_responsibility_item_count
        ):
            raise ValueError("outcome responsibility counts do not reconcile")
        if (
            self.result.verified_closed_work_order_count
            > self.result.selected_work_order_count
        ):
            raise ValueError("verified closures exceed selected work orders")
        return self


def _binding(
    artifact_type: OutcomeArtifactType,
    *,
    resource_id: str,
    artifact_schema_version: str,
    upstream_integrity_kind: UpstreamIntegrityKind,
    upstream_integrity_sha256: str,
    content: BaseModel,
) -> OutcomeArtifactBinding:
    return OutcomeArtifactBinding(
        artifact_type=artifact_type,
        resource_id=resource_id,
        artifact_schema_version=artifact_schema_version,
        upstream_integrity_kind=upstream_integrity_kind,
        upstream_integrity_sha256=upstream_integrity_sha256,
        content_digest=outcome_digest_descriptor(
            content, _ARTIFACT_DOMAINS[artifact_type]
        ),
    )


def _verify_incident_audit_root(
    envelope: GovernedAuditEnvelope, case: IndustrialIncidentCase
) -> None:
    payload = envelope.model_dump(mode="json")
    stored_root = payload.pop("audit_root")
    if not isinstance(stored_root, dict):
        raise ValueError("incident audit root is missing")
    # Independently verify the original audit protocol root and subject linkage.
    expected_audit_root = domain_separated_sha256(payload, AuditHashDomain.AUDIT_ROOT)
    if not hmac.compare_digest(expected_audit_root, envelope.audit_root.value):
        raise ValueError("incident audit envelope root failed validation")
    if not (
        envelope.subject.case_id == case.case_id
        and envelope.subject.task_id == case.task_id
        and hmac.compare_digest(envelope.subject.legacy_case_sha256, case.case_sha256)
    ):
        raise ValueError("incident audit envelope lost case linkage")


def build_governed_outcome_envelope(
    *,
    issuer_actor_id: str,
    workspace_id: str,
    project_id: str,
    parent_gate: GateResult,
    parent_evidence_sha256: str,
    incident_case: IndustrialIncidentCase,
    incident_audit_envelope: GovernedAuditEnvelope,
    incident_decision: IndustrialIncidentDecisionReceipt,
    capa_report: CapaCaseReport,
    child_gate: GateResult,
    child_evidence_sha256: str,
    outcome_assessment: CapaOutcomeAssessment,
) -> GovernedOutcomeEnvelope:
    """Build one reviewer entry only after every source binding verifies."""

    verify_industrial_incident_case(incident_case)
    verify_industrial_incident_decision_receipt(incident_decision, case=incident_case)
    _verify_incident_audit_root(incident_audit_envelope, incident_case)

    approval = capa_report.approval
    derived = capa_report.derived_version
    execution = capa_report.execution
    final_queue = capa_report.final_queue
    recovery = capa_report.recovery
    if any(
        item is None for item in (approval, derived, execution, final_queue, recovery)
    ):
        raise ValueError("governed outcome requires a completed CAPA workflow")
    assert approval is not None
    assert derived is not None
    assert execution is not None
    assert final_queue is not None
    assert recovery is not None
    if recovery.child_verification is None:
        raise ValueError("governed outcome requires child non-regression evidence")

    for artifact, seal_field in (
        (capa_report.selection, "selection_sha256"),
        (approval, "binding_sha256"),
        (derived, "receipt_sha256"),
        (execution, "receipt_sha256"),
        (final_queue, "queue_sha256"),
        (recovery, "receipt_sha256"),
        (outcome_assessment, "assessment_sha256"),
    ):
        verify_sealed_model(artifact, seal_field)

    if not (
        incident_case.task_id == capa_report.parent_task_id
        and incident_decision.linked_capa_case_id == capa_report.case_id
        and incident_decision.selected_remediation_plan_id
        == capa_report.selection.plan.plan_id
        and capa_report.selection.parent_task_id == incident_case.task_id
        and capa_report.selection.plan.task_id == incident_case.task_id
    ):
        raise ValueError("governed outcome lost Incident-to-CAPA linkage")
    if not (
        hmac.compare_digest(
            parent_evidence_sha256, capa_report.selection.parent_evidence_sha256
        )
        and hmac.compare_digest(parent_evidence_sha256, approval.parent_evidence_sha256)
        and hmac.compare_digest(
            parent_evidence_sha256, execution.parent_evidence_sha256_before
        )
        and hmac.compare_digest(
            parent_evidence_sha256, execution.parent_evidence_sha256_after
        )
        and hmac.compare_digest(parent_evidence_sha256, recovery.parent_evidence_sha256)
    ):
        raise ValueError("governed outcome lost parent evidence linkage")
    if not (
        execution.parent_immutable
        and execution.child_task_id == recovery.child_task_id
        and hmac.compare_digest(child_evidence_sha256, execution.child_evidence_sha256)
        and hmac.compare_digest(child_evidence_sha256, recovery.child_evidence_sha256)
        and parent_gate.decision.value == recovery.parent_decision
        and child_gate.decision.value == recovery.child_decision
        and hmac.compare_digest(
            final_queue.queue_sha256, recovery.responsibility_queue_sha256
        )
    ):
        raise ValueError("governed outcome lost child-run linkage")
    if not (
        outcome_assessment.case_id == capa_report.case_id
        and outcome_assessment.parent_task_id == incident_case.task_id
        and outcome_assessment.child_task_id == execution.child_task_id
        and hmac.compare_digest(
            outcome_assessment.selection_sha256,
            capa_report.selection.selection_sha256,
        )
        and hmac.compare_digest(
            outcome_assessment.approval_binding_sha256, approval.binding_sha256
        )
        and hmac.compare_digest(
            outcome_assessment.derived_version_receipt_sha256,
            derived.receipt_sha256,
        )
        and hmac.compare_digest(
            outcome_assessment.execution_receipt_sha256, execution.receipt_sha256
        )
        and hmac.compare_digest(
            outcome_assessment.recovery_receipt_sha256, recovery.receipt_sha256
        )
        and hmac.compare_digest(
            outcome_assessment.responsibility_queue_sha256,
            final_queue.queue_sha256,
        )
    ):
        raise ValueError("governed outcome lost assessment linkage")

    artifacts = [
        _binding(
            OutcomeArtifactType.PARENT_GATE_RESULT,
            resource_id=parent_gate.run_id,
            artifact_schema_version=parent_gate.schema_version,
            upstream_integrity_kind=UpstreamIntegrityKind.EVIDENCE_ARCHIVE_SHA256,
            upstream_integrity_sha256=parent_evidence_sha256,
            content=parent_gate,
        ),
        _binding(
            OutcomeArtifactType.INCIDENT_CASE,
            resource_id=incident_case.case_id,
            artifact_schema_version=incident_case.schema_version,
            upstream_integrity_kind=UpstreamIntegrityKind.LEGACY_SELF_SEAL_SHA256,
            upstream_integrity_sha256=incident_case.case_sha256,
            content=incident_case,
        ),
        _binding(
            OutcomeArtifactType.INCIDENT_AUDIT_ENVELOPE,
            resource_id=incident_case.case_id,
            artifact_schema_version=incident_audit_envelope.schema_version,
            upstream_integrity_kind=UpstreamIntegrityKind.GOVERNED_AUDIT_ROOT,
            upstream_integrity_sha256=incident_audit_envelope.audit_root.value,
            content=incident_audit_envelope,
        ),
        _binding(
            OutcomeArtifactType.HUMAN_INCIDENT_DECISION,
            resource_id=incident_decision.decision_id,
            artifact_schema_version=incident_decision.schema_version,
            upstream_integrity_kind=UpstreamIntegrityKind.LEGACY_SELF_SEAL_SHA256,
            upstream_integrity_sha256=incident_decision.decision_sha256,
            content=incident_decision,
        ),
        _binding(
            OutcomeArtifactType.CAPA_SELECTION,
            resource_id=capa_report.case_id,
            artifact_schema_version=capa_report.selection.schema_version,
            upstream_integrity_kind=UpstreamIntegrityKind.LEGACY_SELF_SEAL_SHA256,
            upstream_integrity_sha256=capa_report.selection.selection_sha256,
            content=capa_report.selection,
        ),
        _binding(
            OutcomeArtifactType.CAPA_APPROVAL,
            resource_id=capa_report.case_id,
            artifact_schema_version=approval.schema_version,
            upstream_integrity_kind=UpstreamIntegrityKind.LEGACY_SELF_SEAL_SHA256,
            upstream_integrity_sha256=approval.binding_sha256,
            content=approval,
        ),
        _binding(
            OutcomeArtifactType.DERIVED_DATA_VERSION,
            resource_id=derived.version_id,
            artifact_schema_version=derived.schema_version,
            upstream_integrity_kind=UpstreamIntegrityKind.LEGACY_SELF_SEAL_SHA256,
            upstream_integrity_sha256=derived.receipt_sha256,
            content=derived,
        ),
        _binding(
            OutcomeArtifactType.CAPA_EXECUTION,
            resource_id=execution.child_task_id,
            artifact_schema_version=execution.schema_version,
            upstream_integrity_kind=UpstreamIntegrityKind.LEGACY_SELF_SEAL_SHA256,
            upstream_integrity_sha256=execution.receipt_sha256,
            content=execution,
        ),
        _binding(
            OutcomeArtifactType.CHILD_GATE_RESULT,
            resource_id=child_gate.run_id,
            artifact_schema_version=child_gate.schema_version,
            upstream_integrity_kind=UpstreamIntegrityKind.EVIDENCE_ARCHIVE_SHA256,
            upstream_integrity_sha256=child_evidence_sha256,
            content=child_gate,
        ),
        _binding(
            OutcomeArtifactType.FINAL_RESPONSIBILITY_QUEUE,
            resource_id=capa_report.case_id,
            artifact_schema_version=final_queue.schema_version,
            upstream_integrity_kind=UpstreamIntegrityKind.LEGACY_SELF_SEAL_SHA256,
            upstream_integrity_sha256=final_queue.queue_sha256,
            content=final_queue,
        ),
        _binding(
            OutcomeArtifactType.CAPA_RECOVERY,
            resource_id=capa_report.case_id,
            artifact_schema_version=recovery.schema_version,
            upstream_integrity_kind=UpstreamIntegrityKind.LEGACY_SELF_SEAL_SHA256,
            upstream_integrity_sha256=recovery.receipt_sha256,
            content=recovery,
        ),
        _binding(
            OutcomeArtifactType.CAPA_OUTCOME_ASSESSMENT,
            resource_id=capa_report.case_id,
            artifact_schema_version=outcome_assessment.schema_version,
            upstream_integrity_kind=UpstreamIntegrityKind.LEGACY_SELF_SEAL_SHA256,
            upstream_integrity_sha256=outcome_assessment.assessment_sha256,
            content=outcome_assessment,
        ),
    ]
    stable = {
        "schema_version": OUTCOME_PROTOCOL_ID,
        "protocol": OutcomeProtocolDescriptor(),
        "issuer": GovernedOutcomeIssuer(
            actor_id=issuer_actor_id,
            workspace_id=workspace_id,
            project_id=project_id,
        ),
        "subject": GovernedOutcomeSubject(
            parent_task_id=incident_case.task_id,
            incident_case_id=incident_case.case_id,
            capa_case_id=capa_report.case_id,
            child_task_id=execution.child_task_id,
        ),
        "artifacts": artifacts,
        "human_authority": OutcomeHumanAuthority(
            incident_decision_id=incident_decision.decision_id,
            incident_decided_by=incident_decision.actor_user_id,
            capa_approved_by=approval.approved_by,
            incident_decision_sha256=incident_decision.decision_sha256,
            capa_approval_binding_sha256=approval.binding_sha256,
        ),
        "result": OutcomeResultBoundary(
            workflow_status=recovery.status,
            parent_gate_decision=parent_gate.decision.value,
            child_gate_decision=child_gate.decision.value,
            child_non_regression_disposition=(recovery.child_verification.disposition),
            release_feasibility_status=(outcome_assessment.release_feasibility_status),
            selected_work_order_count=recovery.selected_work_order_count,
            verified_closed_work_order_count=(
                recovery.verified_closed_work_order_count
            ),
            total_responsibility_item_count=len(final_queue.items),
            open_responsibility_item_count=final_queue.open_count,
            closed_responsibility_item_count=final_queue.closed_count,
            root_cause_status=incident_case.root_cause_status,
            required_human_action=recovery.required_human_action,
        ),
        "signature": AuditSignature(),
        "claim_boundary": (
            "TAMPER_EVIDENT_LOCAL_OUTCOME_PROJECTION_NOT_SIGNATURE_TRUSTED_TIME_"
            "CAUSAL_PROOF_OR_PRODUCTION_RELEASE"
        ),
    }
    return GovernedOutcomeEnvelope(
        **stable,
        outcome_root=outcome_digest_descriptor(stable, OutcomeHashDomain.OUTCOME_ROOT),
    )


def _envelope_payload(envelope: GovernedOutcomeEnvelope) -> dict[str, Any]:
    payload = envelope.model_dump(mode="json")
    payload.pop("outcome_root")
    return payload


def verify_governed_outcome_envelope(envelope: GovernedOutcomeEnvelope) -> None:
    observed = outcome_domain_sha256(
        _envelope_payload(envelope), OutcomeHashDomain.OUTCOME_ROOT
    )
    if not hmac.compare_digest(observed, envelope.outcome_root.value):
        raise ValueError("governed outcome envelope root failed validation")


def parse_governed_outcome_envelope_json(
    payload: str | bytes | bytearray,
) -> GovernedOutcomeEnvelope:
    def unique_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
        result: dict[str, Any] = {}
        for key, value in pairs:
            if key in result:
                raise ValueError(f"duplicate JSON member in outcome envelope: {key}")
            result[key] = value
        return result

    def reject_constant(value: str) -> None:
        raise ValueError(f"non-finite JSON number in outcome envelope: {value}")

    text = (
        bytes(payload).decode("utf-8")
        if isinstance(payload, (bytes, bytearray))
        else payload
    )
    parsed = json.loads(
        text,
        object_pairs_hook=unique_object,
        parse_constant=reject_constant,
    )
    envelope = GovernedOutcomeEnvelope.model_validate(parsed)
    verify_governed_outcome_envelope(envelope)
    return envelope


__all__ = [
    "GovernedOutcomeEnvelope",
    "OutcomeArtifactBinding",
    "OutcomeArtifactType",
    "OutcomeDigestDescriptor",
    "OutcomeHashDomain",
    "build_governed_outcome_envelope",
    "outcome_digest_descriptor",
    "outcome_domain_sha256",
    "parse_governed_outcome_envelope_json",
    "verify_governed_outcome_envelope",
]
