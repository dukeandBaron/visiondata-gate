"""Versioned, domain-separated audit envelopes for industrial incident cases.

The historical v1/v2/v3 case and phase-event SHA-256 contracts remain untouched.
This module adds a new content-level audit protocol alongside those contracts:

* RFC 8785 JSON Canonicalization Scheme (JCS);
* a fixed, length-prefixed hash-domain frame;
* explicit legacy-digest, lineage, governance, and safety-boundary bindings;
* one deterministic case audit root; and
* an honest ``NOT_CONFIGURED`` signature boundary.

The envelope is tamper-evident when its audit root is retained or published by a
trusted party.  A bare digest is not an identity signature, trusted timestamp, or
proof that the recorded business assertion was true when first produced.
"""

from __future__ import annotations

import hashlib
import hmac
import json
from collections.abc import Mapping, Sequence
from enum import Enum
from pathlib import Path
from typing import Any, Literal

import rfc8785
from pydantic import BaseModel, Field, model_validator

from .evidence import canonical_json_bytes
from .governed_context import (
    AssembledIncidentContext,
    verify_assembled_incident_context,
)
from .incident_control_plane import (
    IncidentControlPlaneBundle,
    verify_incident_control_plane,
)
from .incident_runtime_profile import (
    IncidentRuntimeProfileBinding,
)
from .industrial_incident import (
    IncidentPhaseEvent,
    IndustrialIncidentCase,
    IndustrialIncidentDecisionReceipt,
    incident_case_requires_governed_audit_envelope,
    incident_runtime_profile,
    parse_industrial_incident_case_json,
    verify_incident_phase_events,
    verify_industrial_incident_case,
    verify_industrial_incident_decision_receipt,
)
from .product_models import ProductModel
from .site_pack import FactorySitePack, verify_factory_site_pack


AUDIT_PROTOCOL_ID = "visiondata-gate.governed-audit-envelope.v1"
AUDIT_CANONICALIZATION_PROFILE = "rfc8785-jcs-v1"
AUDIT_FRAMING_PROFILE = "visiondata-gate-domain-frame-v1"
AUDIT_FRAME_MAGIC = b"visiondata-gate.audit-frame.v1\x00"


class AuditHashDomain(str, Enum):
    """Closed set of domains accepted by the v1 audit protocol."""

    CASE = "visiondata-gate/industrial-incident-case/audit/v1"
    PARENT_CASE = "visiondata-gate/industrial-incident-parent/audit/v1"
    HUMAN_DECISION = "visiondata-gate/industrial-incident-decision/audit/v1"
    PHASE_EVENT = "visiondata-gate/industrial-incident-phase-event/audit/v1"
    WORKER_RECEIPT = "visiondata-gate/industrial-worker-receipt/audit/v1"
    RUNTIME_PROFILE_BINDING = (
        "visiondata-gate/industrial-runtime-profile-binding/audit/v1"
    )
    SITE_PACK = "visiondata-gate/industrial-site-pack/audit/v1"
    GOVERNED_CONTEXT = "visiondata-gate/industrial-governed-context/audit/v1"
    CONTROL_PLANE = "visiondata-gate/industrial-control-plane/audit/v1"
    POLICY_CONTRACT = "visiondata-gate/industrial-policy-contract/audit/v1"
    AUDIT_ROOT = "visiondata-gate/industrial-case-audit-root/v1"
    AUDIT_ANCHOR = "visiondata-gate/industrial-case-audit-anchor/v1"


class AuditArtifactType(str, Enum):
    RUNTIME_PROFILE_BINDING = "RUNTIME_PROFILE_BINDING"
    SITE_PACK = "SITE_PACK"
    GOVERNED_CONTEXT = "GOVERNED_CONTEXT"
    CONTROL_PLANE = "CONTROL_PLANE"


class AuditArtifactStatus(str, Enum):
    BOUND = "BOUND"
    NOT_APPLICABLE = "NOT_APPLICABLE"


def _json_value(value: Any) -> Any:
    """Convert supported Python/Pydantic values into the RFC 8785 data model."""

    if isinstance(value, BaseModel):
        return _json_value(value.model_dump(mode="json"))
    if isinstance(value, Enum):
        return _json_value(value.value)
    if isinstance(value, Mapping):
        normalized: dict[str, Any] = {}
        for key, item in value.items():
            if not isinstance(key, str):
                raise TypeError("RFC 8785 objects require string property names")
            normalized[key] = _json_value(item)
        return normalized
    if isinstance(value, Sequence) and not isinstance(
        value, (str, bytes, bytearray, memoryview)
    ):
        return [_json_value(item) for item in value]
    if value is None or isinstance(value, (bool, int, float, str)):
        return value
    raise TypeError(
        f"unsupported RFC 8785 canonical JSON value: {type(value).__name__}"
    )


def canonical_jcs_bytes(value: Any) -> bytes:
    """Return RFC 8785 JCS bytes, rejecting values outside the JCS domain."""

    try:
        return rfc8785.dumps(_json_value(value))
    except (rfc8785.CanonicalizationError, TypeError, UnicodeError) as error:
        raise ValueError(
            f"value cannot be canonicalized with RFC 8785: {error}"
        ) from error


def _domain_frame(payload: bytes, domain: AuditHashDomain) -> bytes:
    domain_bytes = domain.value.encode("utf-8")
    if len(domain_bytes) > 0xFFFF:
        raise ValueError("audit hash domain is too long")
    return b"".join(
        (
            AUDIT_FRAME_MAGIC,
            len(domain_bytes).to_bytes(2, "big"),
            domain_bytes,
            len(payload).to_bytes(8, "big"),
            payload,
        )
    )


def domain_separated_sha256(value: Any, domain: AuditHashDomain) -> str:
    """Hash one JCS value inside the protocol's fixed, injective domain frame."""

    canonical = canonical_jcs_bytes(value)
    return hashlib.sha256(_domain_frame(canonical, domain)).hexdigest()


class DigestDescriptor(ProductModel):
    algorithm: Literal["sha256"] = "sha256"
    canonicalization_profile: Literal["rfc8785-jcs-v1"] = AUDIT_CANONICALIZATION_PROFILE
    framing_profile: Literal["visiondata-gate-domain-frame-v1"] = AUDIT_FRAMING_PROFILE
    hash_domain: AuditHashDomain
    value: str = Field(pattern=r"^[0-9a-f]{64}$")


def digest_descriptor(value: Any, domain: AuditHashDomain) -> DigestDescriptor:
    """Build a self-describing domain-separated digest."""

    return DigestDescriptor(
        hash_domain=domain,
        value=domain_separated_sha256(value, domain),
    )


class AuditProtocolDescriptor(ProductModel):
    protocol_id: Literal["visiondata-gate.governed-audit-envelope.v1"] = (
        AUDIT_PROTOCOL_ID
    )
    digest_algorithm: Literal["sha256"] = "sha256"
    canonicalization_profile: Literal["rfc8785-jcs-v1"] = AUDIT_CANONICALIZATION_PROFILE
    framing_profile: Literal["visiondata-gate-domain-frame-v1"] = AUDIT_FRAMING_PROFILE
    frame_construction: Literal[
        "magic || uint16be(domain_length) || domain || "
        "uint64be(payload_length) || rfc8785_payload"
    ] = (
        "magic || uint16be(domain_length) || domain || "
        "uint64be(payload_length) || rfc8785_payload"
    )
    frame_magic_utf8: Literal["visiondata-gate.audit-frame.v1\\u0000"] = (
        "visiondata-gate.audit-frame.v1\\u0000"
    )
    legacy_digest_contract: Literal["PRESERVED_AS_RECORDED"] = "PRESERVED_AS_RECORDED"


class AuditIssuer(ProductModel):
    issuer_type: Literal["VISIONDATA_GATE_PRODUCT_SERVICE"] = (
        "VISIONDATA_GATE_PRODUCT_SERVICE"
    )
    actor_id: str = Field(min_length=1, max_length=160)
    workspace_id: str = Field(min_length=1, max_length=160)
    project_id: str = Field(min_length=1, max_length=160)
    identity_assurance: Literal["LOCAL_APPLICATION_RECORD_ONLY"] = (
        "LOCAL_APPLICATION_RECORD_ONLY"
    )


class AuditSubject(ProductModel):
    subject_type: Literal["IndustrialIncidentCase"] = "IndustrialIncidentCase"
    case_id: str = Field(pattern=r"^incident_[0-9a-f]{20}$")
    task_id: str = Field(min_length=1, max_length=160)
    case_schema_version: str = Field(min_length=1, max_length=120)
    legacy_case_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    audit_digest: DigestDescriptor

    @model_validator(mode="after")
    def validate_case_domain(self) -> AuditSubject:
        if self.audit_digest.hash_domain is not AuditHashDomain.CASE:
            raise ValueError("case audit digest uses an invalid hash domain")
        return self


class AuditLineage(ProductModel):
    transition_type: Literal["ROOT_CASE_CREATED", "CHILD_CASE_CREATED"]
    parent_case_id: str | None = Field(default=None, pattern=r"^incident_[0-9a-f]{20}$")
    parent_legacy_case_sha256: str | None = Field(
        default=None, pattern=r"^[0-9a-f]{64}$"
    )
    parent_audit_digest: DigestDescriptor | None = None
    authorizing_decision_id: str | None = Field(
        default=None, pattern=r"^incident_decision_[0-9a-f]{20}$"
    )
    authorizing_decision_legacy_sha256: str | None = Field(
        default=None, pattern=r"^[0-9a-f]{64}$"
    )
    authorizing_decision_audit_digest: DigestDescriptor | None = None

    @model_validator(mode="after")
    def validate_lineage_shape(self) -> AuditLineage:
        values = (
            self.parent_case_id,
            self.parent_legacy_case_sha256,
            self.parent_audit_digest,
            self.authorizing_decision_id,
            self.authorizing_decision_legacy_sha256,
            self.authorizing_decision_audit_digest,
        )
        if self.transition_type == "ROOT_CASE_CREATED":
            if any(value is not None for value in values):
                raise ValueError("root audit lineage must not bind a parent")
            return self
        if not all(value is not None for value in values):
            raise ValueError(
                "child audit lineage requires parent and decision bindings"
            )
        assert self.parent_audit_digest is not None
        assert self.authorizing_decision_audit_digest is not None
        if self.parent_audit_digest.hash_domain is not AuditHashDomain.PARENT_CASE:
            raise ValueError("parent audit digest uses an invalid hash domain")
        if (
            self.authorizing_decision_audit_digest.hash_domain
            is not AuditHashDomain.HUMAN_DECISION
        ):
            raise ValueError("human decision digest uses an invalid hash domain")
        return self


class PhaseEventAuditBinding(ProductModel):
    sequence: int = Field(ge=1)
    event_id: str = Field(pattern=r"^incident_event_[0-9a-f]{20}$")
    legacy_event_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    audit_digest: DigestDescriptor

    @model_validator(mode="after")
    def validate_event_domain(self) -> PhaseEventAuditBinding:
        if self.audit_digest.hash_domain is not AuditHashDomain.PHASE_EVENT:
            raise ValueError("phase-event audit digest uses an invalid hash domain")
        return self


class WorkerReceiptAuditBinding(ProductModel):
    invocation_id: str = Field(pattern=r"^worker_invocation_[0-9a-f]{20}$")
    worker_role: str = Field(min_length=1, max_length=120)
    legacy_receipt_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    audit_digest: DigestDescriptor

    @model_validator(mode="after")
    def validate_worker_domain(self) -> WorkerReceiptAuditBinding:
        if self.audit_digest.hash_domain is not AuditHashDomain.WORKER_RECEIPT:
            raise ValueError("Worker receipt audit digest uses an invalid hash domain")
        return self


class GovernanceArtifactBinding(ProductModel):
    artifact_type: AuditArtifactType
    status: AuditArtifactStatus
    legacy_sha256: str | None = Field(default=None, pattern=r"^[0-9a-f]{64}$")
    audit_digest: DigestDescriptor | None = None

    @model_validator(mode="after")
    def validate_presence(self) -> GovernanceArtifactBinding:
        if self.status is AuditArtifactStatus.BOUND:
            if self.legacy_sha256 is None or self.audit_digest is None:
                raise ValueError("bound governance artifact requires both digests")
        elif self.legacy_sha256 is not None or self.audit_digest is not None:
            raise ValueError("not-applicable artifact must not contain a digest")
        return self


class CaseResultBoundary(ProductModel):
    schema_version: Literal["visiondata-gate.incident-policy-contract.v1"] = (
        "visiondata-gate.incident-policy-contract.v1"
    )
    case_status: str = Field(min_length=1, max_length=80)
    recommendation: str = Field(min_length=1, max_length=120)
    root_cause_status: Literal["NOT_ESTABLISHED"] = "NOT_ESTABLISHED"
    human_approval_required: Literal[True] = True
    production_release_allowed: Literal[False] = False
    machine_write_permitted: Literal[False] = False
    direct_equipment_control_permitted: Literal[False] = False
    policy_contract_fingerprint: DigestDescriptor
    claim_boundary: str = Field(min_length=1, max_length=1600)

    @model_validator(mode="after")
    def validate_policy_domain(self) -> CaseResultBoundary:
        if (
            self.policy_contract_fingerprint.hash_domain
            is not AuditHashDomain.POLICY_CONTRACT
        ):
            raise ValueError("policy fingerprint uses an invalid hash domain")
        return self


class AuditSignature(ProductModel):
    status: Literal["NOT_CONFIGURED"] = "NOT_CONFIGURED"
    signature_algorithm: None = None
    key_id: None = None
    signature_value: None = None
    trusted_timestamp: None = None
    assurance_boundary: Literal[
        "DIGEST_INTEGRITY_ONLY_NO_SIGNER_IDENTITY_OR_TRUSTED_TIME"
    ] = "DIGEST_INTEGRITY_ONLY_NO_SIGNER_IDENTITY_OR_TRUSTED_TIME"


_ARTIFACT_DOMAINS = {
    AuditArtifactType.RUNTIME_PROFILE_BINDING: AuditHashDomain.RUNTIME_PROFILE_BINDING,
    AuditArtifactType.SITE_PACK: AuditHashDomain.SITE_PACK,
    AuditArtifactType.GOVERNED_CONTEXT: AuditHashDomain.GOVERNED_CONTEXT,
    AuditArtifactType.CONTROL_PLANE: AuditHashDomain.CONTROL_PLANE,
}
_ARTIFACT_ORDER = tuple(AuditArtifactType)


class GovernedAuditEnvelope(ProductModel):
    schema_version: Literal["visiondata-gate.governed-audit-envelope.v1"] = (
        AUDIT_PROTOCOL_ID
    )
    protocol: AuditProtocolDescriptor
    issuer: AuditIssuer
    subject: AuditSubject
    lineage: AuditLineage
    phase_events: list[PhaseEventAuditBinding] = Field(min_length=1)
    worker_receipts: list[WorkerReceiptAuditBinding]
    governance: list[GovernanceArtifactBinding]
    result: CaseResultBoundary
    signature: AuditSignature
    claim_boundary: Literal[
        "TAMPER_EVIDENT_DETERMINISTIC_LINEAGE_NOT_CAUSAL_PROOF_OR_CERTIFICATION"
    ] = "TAMPER_EVIDENT_DETERMINISTIC_LINEAGE_NOT_CAUSAL_PROOF_OR_CERTIFICATION"
    audit_root: DigestDescriptor

    @model_validator(mode="after")
    def validate_protocol_shape(self) -> GovernedAuditEnvelope:
        if self.audit_root.hash_domain is not AuditHashDomain.AUDIT_ROOT:
            raise ValueError("audit root uses an invalid hash domain")
        sequences = [event.sequence for event in self.phase_events]
        if sequences != list(range(1, len(sequences) + 1)):
            raise ValueError(
                "phase-event audit bindings must be contiguous and ordered"
            )
        if len({event.event_id for event in self.phase_events}) != len(
            self.phase_events
        ):
            raise ValueError("phase-event audit bindings contain duplicate IDs")
        artifact_types = tuple(item.artifact_type for item in self.governance)
        if artifact_types != _ARTIFACT_ORDER:
            raise ValueError("governance artifact bindings use an invalid order or set")
        for item in self.governance:
            if item.audit_digest is not None and (
                item.audit_digest.hash_domain
                is not _ARTIFACT_DOMAINS[item.artifact_type]
            ):
                raise ValueError("governance artifact uses an invalid hash domain")
        bound = {item.artifact_type: item.status for item in self.governance}
        if bound[AuditArtifactType.CONTROL_PLANE] is not AuditArtifactStatus.BOUND:
            raise ValueError("control plane must be bound into the audit root")
        if (
            bound[AuditArtifactType.SITE_PACK]
            is not bound[AuditArtifactType.GOVERNED_CONTEXT]
        ):
            raise ValueError("site pack and governed context must travel together")
        return self


class GovernedAuditAnchor(ProductModel):
    """Task-level write-once binding that prevents Sidecar-only replacement."""

    schema_version: Literal["visiondata-gate.governed-audit-anchor.v1"] = (
        "visiondata-gate.governed-audit-anchor.v1"
    )
    case_id: str = Field(pattern=r"^incident_[0-9a-f]{20}$")
    task_id: str = Field(min_length=1, max_length=160)
    legacy_case_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    envelope_protocol_id: Literal["visiondata-gate.governed-audit-envelope.v1"] = (
        AUDIT_PROTOCOL_ID
    )
    audit_root: DigestDescriptor
    anchor_digest: DigestDescriptor

    @model_validator(mode="after")
    def validate_digest_domains(self) -> GovernedAuditAnchor:
        if self.audit_root.hash_domain is not AuditHashDomain.AUDIT_ROOT:
            raise ValueError("audit anchor contains an invalid audit-root domain")
        if self.anchor_digest.hash_domain is not AuditHashDomain.AUDIT_ANCHOR:
            raise ValueError("audit anchor contains an invalid anchor domain")
        return self


def _parse_unique_json(
    payload: str | bytes | bytearray,
    *,
    artifact_name: str,
) -> Any:
    def unique_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
        result: dict[str, Any] = {}
        for key, value in pairs:
            if key in result:
                raise ValueError(f"duplicate JSON member in {artifact_name}: {key}")
            result[key] = value
        return result

    def reject_constant(value: str) -> None:
        raise ValueError(f"non-finite JSON number in {artifact_name}: {value}")

    if isinstance(payload, (bytes, bytearray)):
        text = bytes(payload).decode("utf-8")
    else:
        text = payload
    return json.loads(
        text,
        object_pairs_hook=unique_object,
        parse_constant=reject_constant,
    )


def parse_governed_audit_envelope_json(
    payload: str | bytes | bytearray,
) -> GovernedAuditEnvelope:
    """Parse one envelope as I-JSON and reject duplicate member names."""

    parsed = _parse_unique_json(
        payload,
        artifact_name="audit envelope",
    )
    return GovernedAuditEnvelope.model_validate(parsed)


def parse_governed_audit_anchor_json(
    payload: str | bytes | bytearray,
) -> GovernedAuditAnchor:
    """Parse one task-level anchor without accepting ambiguous JSON members."""

    parsed = _parse_unique_json(
        payload,
        artifact_name="audit anchor",
    )
    return GovernedAuditAnchor.model_validate(parsed)


def _legacy_sha256(
    value: BaseModel,
    field_name: str,
    *,
    legacy_optional_fields: tuple[str, ...] = (),
) -> str:
    payload = value.model_dump(mode="json")
    stored = payload.pop(field_name)
    if not isinstance(stored, str):
        raise ValueError(f"{field_name} is missing")
    observed = hashlib.sha256(canonical_json_bytes(payload)).hexdigest()
    if not hmac.compare_digest(stored, observed):
        legacy_payload = dict(payload)
        if all(legacy_payload.get(name) is None for name in legacy_optional_fields):
            for name in legacy_optional_fields:
                legacy_payload.pop(name, None)
        legacy_observed = hashlib.sha256(
            canonical_json_bytes(legacy_payload)
        ).hexdigest()
        if not hmac.compare_digest(stored, legacy_observed):
            raise ValueError(f"{field_name} failed legacy SHA-256 validation")
    return stored


def _verify_runtime_binding(
    case: IndustrialIncidentCase,
    binding: IncidentRuntimeProfileBinding | None,
    governed_context: AssembledIncidentContext | None,
) -> None:
    profile = incident_runtime_profile(case.request)
    if profile is None:
        if binding is not None:
            raise ValueError("legacy case unexpectedly has a runtime profile binding")
        return
    if binding is None:
        raise ValueError("runtime profile binding is required for this case")
    _legacy_sha256(
        binding,
        "binding_sha256",
        legacy_optional_fields=(
            "governed_memory_planning_input_sha256",
            "governed_memory_retrieval_receipt_sha256",
        ),
    )
    if (
        binding.case_id != case.case_id
        or not hmac.compare_digest(binding.case_sha256, case.case_sha256)
        or binding.profile != profile
        or not hmac.compare_digest(binding.profile_sha256, profile.profile_sha256())
    ):
        raise ValueError("runtime profile binding lost immutable case linkage")
    planner_receipt = case.model_planner_receipt
    expected_planner_config_sha256 = (
        planner_receipt.config_sha256 if planner_receipt is not None else None
    )
    expected_planner_connection_status = (
        planner_receipt.connection_status if planner_receipt is not None else "OFF"
    )
    if (
        binding.planner_config_sha256 != expected_planner_config_sha256
        or binding.planner_connection_status != expected_planner_connection_status
    ):
        raise ValueError("runtime profile binding lost planner linkage")
    if governed_context is None:
        if (
            binding.governed_context_receipt_sha256 is not None
            or binding.governed_memory_planning_input_sha256 is not None
            or binding.governed_memory_retrieval_receipt_sha256 is not None
            or binding.selected_memory_count != 0
            or binding.rejected_memory_count != 0
        ):
            raise ValueError(
                "runtime profile binding references absent governed context"
            )
    elif (
        binding.governed_context_receipt_sha256
        != governed_context.receipt.receipt_sha256
        or binding.governed_memory_planning_input_sha256
        != (
            governed_context.planning_input.input_sha256
            if governed_context.planning_input is not None
            else None
        )
        or binding.governed_memory_retrieval_receipt_sha256
        != governed_context.retrieval_receipt.receipt_sha256
        or binding.selected_memory_count
        != len(governed_context.retrieval_receipt.selected)
        or binding.rejected_memory_count
        != len(governed_context.retrieval_receipt.rejected)
    ):
        raise ValueError("runtime profile binding lost governed-context linkage")


def _policy_payload(case: IndustrialIncidentCase) -> dict[str, Any]:
    return {
        "schema_version": "visiondata-gate.incident-policy-contract.v1",
        "case_status": case.status,
        "recommendation": case.recommendation,
        "root_cause_status": case.root_cause_status,
        "human_approval_required": case.human_approval_required,
        "production_release_allowed": case.production_release_allowed,
        "machine_write_permitted": case.machine_write_permitted,
        "direct_equipment_control_permitted": (case.direct_equipment_control_permitted),
        "claim_boundary": case.claim_boundary,
    }


def _artifact_binding(
    artifact_type: AuditArtifactType,
    artifact: BaseModel | None,
    *,
    legacy_sha256: str | None,
) -> GovernanceArtifactBinding:
    if artifact is None:
        if legacy_sha256 is not None:
            raise ValueError("absent governance artifact cannot have a legacy digest")
        return GovernanceArtifactBinding(
            artifact_type=artifact_type,
            status=AuditArtifactStatus.NOT_APPLICABLE,
        )
    if legacy_sha256 is None:
        raise ValueError("bound governance artifact requires a legacy digest")
    return GovernanceArtifactBinding(
        artifact_type=artifact_type,
        status=AuditArtifactStatus.BOUND,
        legacy_sha256=legacy_sha256,
        audit_digest=digest_descriptor(artifact, _ARTIFACT_DOMAINS[artifact_type]),
    )


def _envelope_payload(envelope: GovernedAuditEnvelope) -> dict[str, Any]:
    payload = envelope.model_dump(mode="json")
    payload.pop("audit_root")
    return payload


def _anchor_payload(anchor: GovernedAuditAnchor) -> dict[str, Any]:
    payload = anchor.model_dump(mode="json")
    payload.pop("anchor_digest")
    return payload


def _verify_envelope_audit_root(envelope: GovernedAuditEnvelope) -> None:
    observed_root = digest_descriptor(
        _envelope_payload(envelope),
        AuditHashDomain.AUDIT_ROOT,
    )
    if not hmac.compare_digest(
        canonical_jcs_bytes(observed_root),
        canonical_jcs_bytes(envelope.audit_root),
    ):
        raise ValueError("governed audit envelope failed audit-root validation")


def build_governed_audit_envelope(
    case: IndustrialIncidentCase,
    *,
    phase_events: Sequence[IncidentPhaseEvent],
    issuer_actor_id: str,
    workspace_id: str,
    project_id: str,
    control_plane: IncidentControlPlaneBundle,
    parent_case: IndustrialIncidentCase | None = None,
    authorizing_decision: IndustrialIncidentDecisionReceipt | None = None,
    runtime_profile_binding: IncidentRuntimeProfileBinding | None = None,
    site_pack: FactorySitePack | None = None,
    governed_context: AssembledIncidentContext | None = None,
) -> GovernedAuditEnvelope:
    """Build one deterministic v1 envelope without changing legacy SHA contracts."""

    verify_industrial_incident_case(case)
    events = list(phase_events)
    verify_incident_phase_events(case, events)
    verify_incident_control_plane(control_plane, case=case)
    _verify_runtime_binding(case, runtime_profile_binding, governed_context)

    if (site_pack is None) != (governed_context is None):
        raise ValueError("site pack and governed context must travel together")
    if site_pack is not None and governed_context is not None:
        verify_factory_site_pack(site_pack)
        verify_assembled_incident_context(
            governed_context,
            case=case,
            site_pack=site_pack,
        )

    has_lineage = case.parent_case_id is not None
    if has_lineage != (parent_case is not None and authorizing_decision is not None):
        raise ValueError("audit inputs do not match the case lineage shape")
    if parent_case is None:
        lineage = AuditLineage(transition_type="ROOT_CASE_CREATED")
    else:
        assert authorizing_decision is not None
        verify_industrial_incident_case(parent_case)
        verify_industrial_incident_decision_receipt(
            authorizing_decision,
            case=parent_case,
        )
        if (
            case.parent_case_id != parent_case.case_id
            or case.parent_case_sha256 != parent_case.case_sha256
            or case.authorizing_decision_id != authorizing_decision.decision_id
            or case.authorizing_decision_sha256 != authorizing_decision.decision_sha256
        ):
            raise ValueError("audit parent or decision does not match case lineage")
        lineage = AuditLineage(
            transition_type="CHILD_CASE_CREATED",
            parent_case_id=parent_case.case_id,
            parent_legacy_case_sha256=parent_case.case_sha256,
            parent_audit_digest=digest_descriptor(
                parent_case,
                AuditHashDomain.PARENT_CASE,
            ),
            authorizing_decision_id=authorizing_decision.decision_id,
            authorizing_decision_legacy_sha256=(authorizing_decision.decision_sha256),
            authorizing_decision_audit_digest=digest_descriptor(
                authorizing_decision,
                AuditHashDomain.HUMAN_DECISION,
            ),
        )

    policy_payload = _policy_payload(case)
    result = CaseResultBoundary(
        **policy_payload,
        policy_contract_fingerprint=digest_descriptor(
            policy_payload,
            AuditHashDomain.POLICY_CONTRACT,
        ),
    )
    runtime_legacy = (
        runtime_profile_binding.binding_sha256
        if runtime_profile_binding is not None
        else None
    )
    site_legacy = site_pack.pack_sha256 if site_pack is not None else None
    context_legacy = (
        governed_context.receipt.receipt_sha256
        if governed_context is not None
        else None
    )
    stable: dict[str, Any] = {
        "schema_version": AUDIT_PROTOCOL_ID,
        "protocol": AuditProtocolDescriptor(),
        "issuer": AuditIssuer(
            actor_id=issuer_actor_id,
            workspace_id=workspace_id,
            project_id=project_id,
        ),
        "subject": AuditSubject(
            case_id=case.case_id,
            task_id=case.task_id,
            case_schema_version=case.schema_version,
            legacy_case_sha256=case.case_sha256,
            audit_digest=digest_descriptor(case, AuditHashDomain.CASE),
        ),
        "lineage": lineage,
        "phase_events": [
            PhaseEventAuditBinding(
                sequence=event.sequence,
                event_id=event.event_id,
                legacy_event_sha256=event.event_sha256,
                audit_digest=digest_descriptor(event, AuditHashDomain.PHASE_EVENT),
            )
            for event in events
        ],
        "worker_receipts": [
            WorkerReceiptAuditBinding(
                invocation_id=receipt.invocation_id,
                worker_role=receipt.worker_role,
                legacy_receipt_sha256=receipt.receipt_sha256,
                audit_digest=digest_descriptor(
                    receipt,
                    AuditHashDomain.WORKER_RECEIPT,
                ),
            )
            for receipt in case.worker_receipts
        ],
        "governance": [
            _artifact_binding(
                AuditArtifactType.RUNTIME_PROFILE_BINDING,
                runtime_profile_binding,
                legacy_sha256=runtime_legacy,
            ),
            _artifact_binding(
                AuditArtifactType.SITE_PACK,
                site_pack,
                legacy_sha256=site_legacy,
            ),
            _artifact_binding(
                AuditArtifactType.GOVERNED_CONTEXT,
                governed_context,
                legacy_sha256=context_legacy,
            ),
            _artifact_binding(
                AuditArtifactType.CONTROL_PLANE,
                control_plane,
                legacy_sha256=control_plane.bundle_sha256,
            ),
        ],
        "result": result,
        "signature": AuditSignature(),
        "claim_boundary": (
            "TAMPER_EVIDENT_DETERMINISTIC_LINEAGE_NOT_CAUSAL_PROOF_OR_CERTIFICATION"
        ),
    }
    root = digest_descriptor(stable, AuditHashDomain.AUDIT_ROOT)
    return GovernedAuditEnvelope(**stable, audit_root=root)


def build_governed_audit_anchor(
    case: IndustrialIncidentCase,
    envelope: GovernedAuditEnvelope,
) -> GovernedAuditAnchor:
    """Bind one envelope root outside the replaceable case Sidecar directory."""

    verify_industrial_incident_case(case)
    _verify_envelope_audit_root(envelope)
    if (
        envelope.subject.case_id != case.case_id
        or envelope.subject.task_id != case.task_id
        or not hmac.compare_digest(
            envelope.subject.legacy_case_sha256,
            case.case_sha256,
        )
    ):
        raise ValueError("governed audit anchor lost immutable case linkage")
    stable: dict[str, Any] = {
        "schema_version": "visiondata-gate.governed-audit-anchor.v1",
        "case_id": case.case_id,
        "task_id": case.task_id,
        "legacy_case_sha256": case.case_sha256,
        "envelope_protocol_id": envelope.schema_version,
        "audit_root": envelope.audit_root,
    }
    anchor_digest = digest_descriptor(stable, AuditHashDomain.AUDIT_ANCHOR)
    return GovernedAuditAnchor(**stable, anchor_digest=anchor_digest)


def verify_governed_audit_anchor(
    anchor: GovernedAuditAnchor,
    *,
    case: IndustrialIncidentCase,
    envelope: GovernedAuditEnvelope | None = None,
) -> None:
    """Fail closed unless the task-level anchor matches its case and envelope."""

    verify_industrial_incident_case(case)
    observed_digest = digest_descriptor(
        _anchor_payload(anchor),
        AuditHashDomain.AUDIT_ANCHOR,
    )
    if not hmac.compare_digest(
        canonical_jcs_bytes(observed_digest),
        canonical_jcs_bytes(anchor.anchor_digest),
    ):
        raise ValueError("governed audit anchor failed digest validation")
    if (
        anchor.case_id != case.case_id
        or anchor.task_id != case.task_id
        or not hmac.compare_digest(
            anchor.legacy_case_sha256,
            case.case_sha256,
        )
    ):
        raise ValueError("governed audit anchor failed case binding")
    if envelope is not None:
        expected = build_governed_audit_anchor(case, envelope)
        if not hmac.compare_digest(
            canonical_jcs_bytes(expected),
            canonical_jcs_bytes(anchor),
        ):
            raise ValueError("governed audit envelope failed task-level anchor binding")


def verify_governed_audit_envelope(
    envelope: GovernedAuditEnvelope,
    *,
    case: IndustrialIncidentCase,
    phase_events: Sequence[IncidentPhaseEvent],
    control_plane: IncidentControlPlaneBundle,
    parent_case: IndustrialIncidentCase | None = None,
    authorizing_decision: IndustrialIncidentDecisionReceipt | None = None,
    runtime_profile_binding: IncidentRuntimeProfileBinding | None = None,
    site_pack: FactorySitePack | None = None,
    governed_context: AssembledIncidentContext | None = None,
    expected_workspace_id: str | None = None,
    expected_project_id: str | None = None,
) -> None:
    """Fail closed unless the envelope exactly matches all supplied artifacts."""

    _verify_envelope_audit_root(envelope)
    if (
        expected_workspace_id is not None
        and envelope.issuer.workspace_id != expected_workspace_id
    ):
        raise ValueError("governed audit envelope failed workspace binding")
    if (
        expected_project_id is not None
        and envelope.issuer.project_id != expected_project_id
    ):
        raise ValueError("governed audit envelope failed project binding")

    expected = build_governed_audit_envelope(
        case,
        phase_events=phase_events,
        issuer_actor_id=envelope.issuer.actor_id,
        workspace_id=envelope.issuer.workspace_id,
        project_id=envelope.issuer.project_id,
        control_plane=control_plane,
        parent_case=parent_case,
        authorizing_decision=authorizing_decision,
        runtime_profile_binding=runtime_profile_binding,
        site_pack=site_pack,
        governed_context=governed_context,
    )
    if not hmac.compare_digest(
        canonical_jcs_bytes(expected),
        canonical_jcs_bytes(envelope),
    ):
        raise ValueError("governed audit envelope does not match source artifacts")


def verify_governed_audit_case_directory(
    case_directory: str | Path,
) -> GovernedAuditEnvelope:
    """Independently verify one persisted case directory without product state."""

    root = Path(case_directory).expanduser().resolve(strict=True)
    if not root.is_dir():
        raise ValueError("industrial incident case path is not a directory")
    case = parse_industrial_incident_case_json((root / "case.json").read_bytes())
    if root.name != case.case_id:
        raise ValueError("industrial incident directory name does not match case_id")
    events = [
        IncidentPhaseEvent.model_validate_json(path.read_bytes())
        for path in sorted((root / "phase_events").glob("*.json"))
        if path.is_file()
    ]
    control_plane = IncidentControlPlaneBundle.model_validate_json(
        (root / "control_plane.json").read_bytes()
    )
    envelope = parse_governed_audit_envelope_json(
        (root / "audit" / "governed_audit_envelope.json").read_bytes()
    )
    anchor_path = root.parent / "governed_audit_anchors" / f"{case.case_id}.json"
    anchor: GovernedAuditAnchor | None = None
    anchor_required = incident_case_requires_governed_audit_envelope(case)
    if anchor_required and not anchor_path.is_file():
        raise ValueError("governed industrial incident audit anchor is missing")
    if anchor_required or anchor_path.is_file():
        anchor = parse_governed_audit_anchor_json(anchor_path.read_bytes())
        verify_governed_audit_anchor(anchor, case=case)

    runtime_root = root / "runtime"
    binding_path = runtime_root / "profile_binding.json"
    site_path = runtime_root / "site_pack.json"
    governed_path = runtime_root / "governed_context.json"
    binding = (
        IncidentRuntimeProfileBinding.model_validate_json(binding_path.read_bytes())
        if binding_path.is_file()
        else None
    )
    site_pack = (
        FactorySitePack.model_validate_json(site_path.read_bytes())
        if site_path.is_file()
        else None
    )
    governed_context = (
        AssembledIncidentContext.model_validate_json(governed_path.read_bytes())
        if governed_path.is_file()
        else None
    )

    parent: IndustrialIncidentCase | None = None
    decision: IndustrialIncidentDecisionReceipt | None = None
    if case.parent_case_id is not None:
        if case.authorizing_decision_id is None:
            raise ValueError("child case is missing its authorizing decision ID")
        parent_root = (root.parent / case.parent_case_id).resolve(strict=True)
        if parent_root.parent != root.parent or not parent_root.is_dir():
            raise ValueError("parent case path escaped the incident case collection")
        parent = parse_industrial_incident_case_json(
            (parent_root / "case.json").read_bytes()
        )
        decision = IndustrialIncidentDecisionReceipt.model_validate_json(
            (
                parent_root / "decisions" / f"{case.authorizing_decision_id}.json"
            ).read_bytes()
        )

    verify_governed_audit_envelope(
        envelope,
        case=case,
        phase_events=events,
        control_plane=control_plane,
        parent_case=parent,
        authorizing_decision=decision,
        runtime_profile_binding=binding,
        site_pack=site_pack,
        governed_context=governed_context,
    )
    if anchor is not None:
        verify_governed_audit_anchor(
            anchor,
            case=case,
            envelope=envelope,
        )
    return envelope


__all__ = [
    "AUDIT_CANONICALIZATION_PROFILE",
    "AUDIT_FRAMING_PROFILE",
    "AUDIT_PROTOCOL_ID",
    "AuditArtifactStatus",
    "AuditArtifactType",
    "AuditHashDomain",
    "DigestDescriptor",
    "GovernedAuditAnchor",
    "GovernedAuditEnvelope",
    "build_governed_audit_anchor",
    "build_governed_audit_envelope",
    "canonical_jcs_bytes",
    "digest_descriptor",
    "domain_separated_sha256",
    "parse_governed_audit_anchor_json",
    "parse_governed_audit_envelope_json",
    "verify_governed_audit_anchor",
    "verify_governed_audit_envelope",
    "verify_governed_audit_case_directory",
]
