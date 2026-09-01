"""Evidence-sidecar contracts for one industrial vision quality incident.

The sidecar deliberately does not implement MES, SCADA, PLC, or camera control.
It consumes a redacted OPC UA Machine Vision shaped snapshot, a vendor-neutral
vision-solution manifest, a quality-result receipt, a batch trace record,
production change records, and an already-completed VisionData Gate task.  The
result is a deterministic, human-gated incident decision package that can point
into the existing CAPA and child-run workflow.

OPC UA inputs in this module are offline exports or fixtures only.  Raw endpoint
addresses, credentials, certificate material, and writable NodeIds are outside
the evidence contract.
"""

from __future__ import annotations

import hashlib
import hmac
import json
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from contextvars import ContextVar
from copy import deepcopy
from datetime import datetime, timedelta
from enum import Enum
from functools import wraps
from typing import TYPE_CHECKING, Annotated, Literal, ParamSpec, TypeVar

from pydantic import (
    Field,
    PrivateAttr,
    TypeAdapter,
    field_validator,
    model_serializer,
    model_validator,
)

from .evidence import canonical_json_bytes
from .evidence_state_contracts import (
    EvidenceBeliefLedgerV2,
    build_case_evidence_belief_ledger_v2,
    verify_evidence_belief_ledger_v2,
)
from .incident_agent_kernel import (
    AutonomyGuardReceiptV1,
    CouncilArbitrationReceiptV1,
    EvidenceBeliefRevisionReceiptV1,
    WorkerExecutionPlanReceiptV1,
    build_autonomy_guard_receipt_v1,
    build_council_arbitration_receipt_v1,
    build_evidence_belief_revision_receipt_v1,
    build_worker_execution_plan_receipt_v1,
    verify_autonomy_guard_receipt_v1,
    verify_council_arbitration_receipt_v1,
    verify_evidence_belief_revision_receipt_v1,
    verify_worker_execution_plan_receipt_v1,
)
from .incident_model_planner import (
    IncidentModelMode,
    IncidentModelPlanner,
    IncidentModelPlannerReceipt,
    verify_incident_model_planner_receipt,
)
from .incident_runtime_profile import IncidentRuntimeProfile
from .product_models import ProductModel
from .worker_selection import (
    BlockingSeverity,
    MeasuredCostBucket,
    WorkerCandidate,
    WorkerSelectionReceipt,
    build_worker_selection_receipt,
    verify_worker_selection_receipt,
)

if TYPE_CHECKING:
    from .governed_context import GovernedMemoryPlanningInput

ScalarValue = bool | int | float | str | None

LEGACY_INCIDENT_CASE_SCHEMA_VERSIONS = frozenset(
    {
        "visiondata-gate.industrial-incident-case.v1",
        "visiondata-gate.industrial-incident-case.v2",
        "visiondata-gate.industrial-incident-case.v3",
    }
)
GOVERNED_INCIDENT_CASE_SCHEMA_VERSIONS = frozenset(
    {
        "visiondata-gate.industrial-incident-case.v4",
        "visiondata-gate.industrial-incident-case.v5",
        "visiondata-gate.industrial-incident-case.v6",
    }
)
PLANNING_ARTIFACT_INCIDENT_CASE_SCHEMA_VERSIONS = frozenset(
    {
        "visiondata-gate.industrial-incident-case.v5",
        "visiondata-gate.industrial-incident-case.v6",
    }
)
AGENT_KERNEL_INCIDENT_CASE_SCHEMA_VERSION = (
    "visiondata-gate.industrial-incident-case.v6"
)
PHASE_EVENT_INCIDENT_CASE_SCHEMA_VERSIONS = frozenset(
    {
        "visiondata-gate.industrial-incident-case.v3",
        *GOVERNED_INCIDENT_CASE_SCHEMA_VERSIONS,
    }
)
GOVERNED_INCIDENT_CASE_SCHEMA_VERSION = AGENT_KERNEL_INCIDENT_CASE_SCHEMA_VERSION
GOVERNED_AUDIT_ENVELOPE_REQUIREMENT = "REQUIRED"


def _require_aware(value: datetime) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("timestamp must include an explicit UTC offset")
    return value


def _sha256(value: object) -> str:
    return hashlib.sha256(canonical_json_bytes(value)).hexdigest()


def industrial_incident_planning_subject_sha256(
    request: IndustrialIncidentRequest,
    gate_context: IndustrialGateContext,
    *,
    authorizing_decision: IndustrialIncidentDecisionReceipt | None = None,
) -> str:
    """Seal all immutable inputs available before Workers or a model Planner run."""

    return _sha256(
        {
            "request": _sha256(request),
            "context": _sha256(gate_context),
            "authorizing_decision": (
                authorizing_decision.decision_sha256
                if authorizing_decision is not None
                else None
            ),
        }
    )


class OPCUASnapshotMode(str, Enum):
    OFFLINE_EXPORT = "OFFLINE_EXPORT"
    FIXTURE_REPLAY = "FIXTURE_REPLAY"


class OPCUAValueSeverity(str, Enum):
    GOOD = "Good"
    UNCERTAIN = "Uncertain"
    BAD = "Bad"


class ManufacturingRecordAuthorityStatus(str, Enum):
    VERIFIED = "VERIFIED"
    NOT_VERIFIED = "NOT_VERIFIED"
    REVOKED = "REVOKED"
    EXPIRED = "EXPIRED"


class ProductionChangeKind(str, Enum):
    PRODUCT_CHANGEOVER = "PRODUCT_CHANGEOVER"
    RECIPE_CHANGE = "RECIPE_CHANGE"
    VISION_SOLUTION_UPGRADE = "VISION_SOLUTION_UPGRADE"
    PROCESS_SETPOINT_CHANGE = "PROCESS_SETPOINT_CHANGE"


class IncidentTriggerKind(str, Enum):
    NG_RATE_DRIFT = "NG_RATE_DRIFT"
    NEW_DEFECT_CLUSTER = "NEW_DEFECT_CLUSTER"
    SOLUTION_CHANGE_REVIEW = "SOLUTION_CHANGE_REVIEW"
    TRACEABILITY_ALERT = "TRACEABILITY_ALERT"
    EVIDENCE_INTEGRITY_ALERT = "EVIDENCE_INTEGRITY_ALERT"


class IncidentStatus(str, Enum):
    EVIDENCE_INCOMPLETE = "EVIDENCE_INCOMPLETE"
    INVESTIGATION_REQUIRED = "INVESTIGATION_REQUIRED"
    PLAN_AWAITING_APPROVAL = "PLAN_AWAITING_APPROVAL"
    REVERIFICATION_REQUIRED = "REVERIFICATION_REQUIRED"
    READY_FOR_HUMAN_DECISION = "READY_FOR_HUMAN_DECISION"
    CLOSED = "CLOSED"

    # Backward-compatible names for the unintegrated v1 draft.  The serialized
    # state values above are the only values exposed by the v2 product contract.
    SOLUTION_REVERIFICATION_REQUIRED = "REVERIFICATION_REQUIRED"  # noqa: PIE796
    CAPA_READY = "PLAN_AWAITING_APPROVAL"  # noqa: PIE796
    READY_FOR_HUMAN_REVIEW = "READY_FOR_HUMAN_DECISION"  # noqa: PIE796


class IncidentRecommendation(str, Enum):
    COLLECT_MORE_EVIDENCE = "COLLECT_MORE_EVIDENCE"
    CONTINUE_HOLD = "CONTINUE_HOLD"
    REVERIFY_VISION_SOLUTION = "REVERIFY_VISION_SOLUTION"
    SELECT_REMEDIATION_PLAN = "SELECT_REMEDIATION_PLAN"
    RECOVERY_CANDIDATE = "RECOVERY_CANDIDATE"
    RECAPTURE_REQUIRED = "RECAPTURE_REQUIRED"
    ESCALATE_TO_ENGINEER = "ESCALATE_TO_ENGINEER"

    HOLD_FOR_HUMAN_REVIEW = "CONTINUE_HOLD"  # noqa: PIE796
    EXECUTE_APPROVED_CAPA = "SELECT_REMEDIATION_PLAN"  # noqa: PIE796
    CONTINUE_OBSERVATION = "RECOVERY_CANDIDATE"  # noqa: PIE796


class IncidentLoopStopReason(str, Enum):
    WAITING_FOR_EVIDENCE = "WAITING_FOR_EVIDENCE"
    WAITING_FOR_HUMAN_APPROVAL = "WAITING_FOR_HUMAN_APPROVAL"
    READY_FOR_HUMAN_DECISION = "READY_FOR_HUMAN_DECISION"
    MAX_ITERATIONS_REACHED = "MAX_ITERATIONS_REACHED"
    WORKER_BUDGET_EXHAUSTED = "WORKER_BUDGET_EXHAUSTED"
    NO_DISCRIMINATING_ACTION = "NO_DISCRIMINATING_ACTION"
    SAFETY_GATE_BLOCKED = "SAFETY_GATE_BLOCKED"


class IncidentHumanDecision(str, Enum):
    CONTINUE_HOLD = "CONTINUE_HOLD"
    ESCALATE_INVESTIGATION = "ESCALATE_INVESTIGATION"
    SELECT_REMEDIATION_PLAN = "SELECT_REMEDIATION_PLAN"
    REQUEST_REVERIFICATION = "REQUEST_REVERIFICATION"
    REJECT_RECOMMENDATION = "REJECT_RECOMMENDATION"


class EvidenceQualification(str, Enum):
    QUALIFIED = "QUALIFIED"
    QUALIFIED_WITH_WARNING = "QUALIFIED_WITH_WARNING"
    NOT_QUALIFIED = "NOT_QUALIFIED"


class HypothesisStatus(str, Enum):
    SUPPORTED = "SUPPORTED"
    PLAUSIBLE = "PLAUSIBLE"
    UNRESOLVED = "UNRESOLVED"
    REJECTED = "REJECTED"


class IncidentKnowledgeReference(ProductModel):
    """Hash-only knowledge context that may influence a case decision.

    Raw SOP text and proprietary rule content stay outside the case package.  A
    reference is qualified only when its version and digest are explicit.
    """

    reference_id: str = Field(pattern=r"^[a-zA-Z0-9_.:-]{3,160}$")
    kind: Literal[
        "enterprise_sop",
        "frozen_rulepack",
        "inspection_standard",
        "approved_baseline",
    ]
    title: str = Field(min_length=1, max_length=240)
    version: str = Field(min_length=1, max_length=120)
    content_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    qualification: EvidenceQualification = EvidenceQualification.QUALIFIED
    scope_note: str = Field(min_length=1, max_length=500)


class IncidentOperatorQuestion(ProductModel):
    """One structured interruption instead of an unbounded chat prompt."""

    question_id: str = Field(pattern=r"^question_[0-9a-f]{12}$")
    prompt: str = Field(min_length=1, max_length=800)
    reason_codes: list[str] = Field(min_length=1)
    expected_evidence_type: Literal[
        "opcua_snapshot",
        "traceability_receipt",
        "batch_trace_record",
        "production_change_record",
        "vision_solution_manifest",
        "offline_vision_run",
        "process_owner_attestation",
        "quality_owner_decision",
    ]
    required: bool = True
    status: Literal["OPEN", "ANSWERED", "SUPERSEDED"] = "OPEN"


class IncidentLoopStep(ProductModel):
    """Observable loop event; it never stores hidden chain-of-thought."""

    sequence: int = Field(ge=1)
    iteration: int = Field(ge=1)
    phase: Literal["PLAN", "ACT", "OBSERVE", "EVALUATE", "INTERRUPT"]
    actor: str = Field(min_length=1, max_length=120)
    summary: str = Field(min_length=1, max_length=800)
    input_refs: list[str]
    output_refs: list[str]
    status: Literal["COMPLETED", "PAUSED", "STOPPED"]


class IncidentLoopControl(ProductModel):
    current_iteration: int = Field(ge=1)
    max_iterations: int = Field(ge=1, le=12)
    dynamic_worker_budget: int = Field(ge=1, le=12)
    dynamic_workers_executed: int = Field(ge=0)
    remaining_worker_budget: int = Field(ge=0)
    stop_reason: IncidentLoopStopReason
    can_resume: bool
    resume_requires: list[str]


class IncidentDecisionSummary(ProductModel):
    """Reviewer-facing rationale made only from observable case evidence."""

    observed_facts: list[str] = Field(min_length=1, max_length=12)
    unresolved_reason_codes: list[str]
    alternatives_kept_open: list[str]
    prohibited_conclusions: list[str] = Field(min_length=1)
    next_safe_action: str = Field(min_length=1, max_length=800)


class OPCUAMachineVisionContext(ProductModel):
    """Semantic correlation keys shaped after the OPC UA Machine Vision model.

    ``lot_reference`` is explicitly a local MES/barcode/operator extension.  It
    is not presented as a standard OPC UA Machine Vision ``BatchId``.
    """

    product_id: str = Field(min_length=1, max_length=160)
    part_id: str | None = Field(default=None, max_length=160)
    recipe_id: str = Field(min_length=1, max_length=160)
    configuration_id: str = Field(min_length=1, max_length=160)
    job_id: str = Field(min_length=1, max_length=160)
    result_id: str = Field(min_length=1, max_length=160)
    creation_time: datetime
    result_state: Literal["Completed", "Processing", "Aborted", "Failed"]
    is_partial: bool = False
    is_simulated: bool = False
    lot_reference: str | None = Field(default=None, max_length=160)
    lot_reference_authority: (
        Literal[
            "MES_EXPORT", "BARCODE_SCAN", "WORK_ORDER_EXPORT", "OPERATOR_ATTESTATION"
        ]
        | None
    ) = None

    @field_validator("creation_time")
    @classmethod
    def validate_creation_time(cls, value: datetime) -> datetime:
        return _require_aware(value)

    @model_validator(mode="after")
    def validate_lot_authority(self) -> OPCUAMachineVisionContext:
        if (self.lot_reference is None) != (self.lot_reference_authority is None):
            raise ValueError(
                "lot_reference and lot_reference_authority travel together"
            )
        return self


class OPCUANodeObservation(ProductModel):
    """One redacted DataValue observation from an allowlisted semantic alias."""

    semantic_alias: str = Field(pattern=r"^[a-z][a-z0-9_.-]{1,79}$")
    namespace_uri: str = Field(min_length=3, max_length=500)
    browse_path: str = Field(min_length=1, max_length=500)
    node_id_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    data_type: str = Field(min_length=1, max_length=80)
    engineering_unit: str | None = Field(default=None, max_length=40)
    value: ScalarValue
    status_code: str = Field(min_length=1, max_length=120)
    severity: OPCUAValueSeverity
    source_timestamp: datetime | None = None
    server_timestamp: datetime
    semantics_changed: bool = False

    @field_validator("source_timestamp", "server_timestamp")
    @classmethod
    def validate_timestamp(cls, value: datetime | None) -> datetime | None:
        if value is None:
            return None
        return _require_aware(value)


class OPCUAOfflineSnapshot(ProductModel):
    schema_version: Literal["visiondata-gate.opcua-offline-snapshot.v1"] = (
        "visiondata-gate.opcua-offline-snapshot.v1"
    )
    source_mode: OPCUASnapshotMode
    captured_at: datetime
    server_application_uri_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    node_whitelist_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    allowlisted_aliases: list[str] = Field(min_length=1, max_length=64)
    machine_vision_context: OPCUAMachineVisionContext
    observations: list[OPCUANodeObservation] = Field(min_length=1, max_length=256)
    operator_attests_authorized_export: Literal[True]
    read_only: Literal[True] = True
    machine_write_permitted: Literal[False] = False
    method_call_permitted: Literal[False] = False
    credentials_embedded: Literal[False] = False
    certificate_private_key_embedded: Literal[False] = False
    real_endpoint_connected: Literal[False] = False

    @field_validator("captured_at")
    @classmethod
    def validate_captured_at(cls, value: datetime) -> datetime:
        return _require_aware(value)

    @field_validator("allowlisted_aliases")
    @classmethod
    def validate_unique_allowlist(cls, values: list[str]) -> list[str]:
        if len(values) != len(set(values)):
            raise ValueError("allowlisted_aliases must be unique")
        return values

    @model_validator(mode="after")
    def validate_observation_allowlist(self) -> OPCUAOfflineSnapshot:
        aliases = [item.semantic_alias for item in self.observations]
        if len(aliases) != len(set(aliases)):
            raise ValueError(
                "OPC UA observations must have unique semantic_alias values"
            )
        unknown = sorted(set(aliases) - set(self.allowlisted_aliases))
        if unknown:
            raise ValueError(
                "OPC UA observations escaped the semantic allowlist: "
                + ", ".join(unknown)
            )
        return self


class VisionSolutionManifest(ProductModel):
    """Vendor-neutral export contract for a versioned visual inspection solution."""

    schema_version: Literal["visiondata-gate.vision-solution-manifest.v1"] = (
        "visiondata-gate.vision-solution-manifest.v1"
    )
    source_profile: Literal[
        "VENDOR_NEUTRAL_EXPORT", "VISIONMASTER_COMPATIBLE_OFFLINE_EXPORT"
    ]
    solution_id: str = Field(min_length=1, max_length=160)
    solution_version: str = Field(min_length=1, max_length=120)
    product_id: str = Field(min_length=1, max_length=160)
    recipe_id: str = Field(min_length=1, max_length=160)
    configuration_id: str = Field(min_length=1, max_length=160)
    exported_at: datetime
    algorithm_graph_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    model_artifact_sha256: str | None = Field(default=None, pattern=r"^[0-9a-f]{64}$")
    camera_config_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    lighting_config_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    calibration_receipt_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    rulepack_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    dataset_version_id: str = Field(min_length=1, max_length=160)
    visionmaster_sdk_connected: Literal[False] = False
    external_platform_write_permitted: Literal[False] = False

    @field_validator("exported_at")
    @classmethod
    def validate_exported_at(cls, value: datetime) -> datetime:
        return _require_aware(value)


class OfflineVisionRunReceipt(ProductModel):
    """Offline result receipt; it never claims a live VisionMaster SDK connection."""

    schema_version: Literal["visiondata-gate.offline-vision-run.v1"] = (
        "visiondata-gate.offline-vision-run.v1"
    )
    source_profile: Literal[
        "VENDOR_NEUTRAL_EXPORT", "VISIONMASTER_COMPATIBLE_OFFLINE_EXPORT"
    ]
    evidence_domain: Literal["QUALITY_INSPECTION_RESULT"] = "QUALITY_INSPECTION_RESULT"
    run_id: str = Field(min_length=1, max_length=160)
    solution_manifest_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    product_id: str = Field(min_length=1, max_length=160)
    part_id: str | None = Field(default=None, max_length=160)
    recipe_id: str = Field(min_length=1, max_length=160)
    configuration_id: str = Field(min_length=1, max_length=160)
    job_id: str = Field(min_length=1, max_length=160)
    result_id: str = Field(min_length=1, max_length=160)
    batch_id: str | None = Field(default=None, max_length=160)
    lot_reference: str | None = Field(default=None, max_length=160)
    work_order_id: str | None = Field(default=None, max_length=160)
    line_id: str | None = Field(default=None, max_length=160)
    started_at: datetime
    completed_at: datetime
    execution_state: Literal["Completed", "Aborted", "Failed"]
    input_count: int = Field(ge=1)
    ok_count: int = Field(ge=0)
    ng_count: int = Field(ge=0)
    unknown_count: int = Field(default=0, ge=0)
    is_partial: bool = False
    is_simulated: bool = False
    sample_index_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    result_summary_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    visionmaster_sdk_connected: Literal[False] = False

    @field_validator("started_at", "completed_at")
    @classmethod
    def validate_run_time(cls, value: datetime) -> datetime:
        return _require_aware(value)

    @model_validator(mode="after")
    def validate_counts_and_time(self) -> OfflineVisionRunReceipt:
        if self.completed_at < self.started_at:
            raise ValueError("completed_at must not precede started_at")
        if self.ok_count + self.ng_count + self.unknown_count != self.input_count:
            raise ValueError("run result counts must sum to input_count")
        return self


class ProcessSignalExpectation(ProductModel):
    semantic_alias: str = Field(pattern=r"^[a-z][a-z0-9_.-]{1,79}$")
    required: bool = True
    engineering_unit: str = Field(min_length=1, max_length=40)
    minimum: float | None = None
    maximum: float | None = None

    @model_validator(mode="after")
    def validate_bounds(self) -> ProcessSignalExpectation:
        if self.minimum is None and self.maximum is None:
            raise ValueError("at least one process-signal bound is required")
        if (
            self.minimum is not None
            and self.maximum is not None
            and self.minimum > self.maximum
        ):
            raise ValueError("minimum must not exceed maximum")
        return self


class BatchTraceRecord(ProductModel):
    """Read-only authority and identity binding for one production batch.

    ``source_record_sha256`` identifies the original MES/barcode/work-order
    export without embedding that raw record in the case.  The separate
    ``record_binding_sha256`` makes this normalized contract locally
    tamper-evident.
    """

    schema_version: Literal["visiondata-gate.batch-trace-record.v1"] = (
        "visiondata-gate.batch-trace-record.v1"
    )
    record_id: str = Field(pattern=r"^[a-zA-Z0-9_.:-]{3,160}$")
    source_kind: Literal["MES_EXPORT", "BARCODE_SCAN", "WORK_ORDER_EXPORT"]
    source_system_id_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    source_record_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    source_authorization_sha256: str | None = Field(
        default=None, pattern=r"^[0-9a-f]{64}$"
    )
    authority_status: ManufacturingRecordAuthorityStatus
    batch_id: str = Field(min_length=1, max_length=160)
    lot_reference: str = Field(min_length=1, max_length=160)
    work_order_id: str = Field(min_length=1, max_length=160)
    line_id: str = Field(min_length=1, max_length=160)
    product_id: str = Field(min_length=1, max_length=160)
    part_id: str | None = Field(default=None, max_length=160)
    recipe_id: str = Field(min_length=1, max_length=160)
    configuration_id: str = Field(min_length=1, max_length=160)
    production_window_start: datetime
    production_window_end: datetime
    exported_at: datetime
    operator_attests_authorized_export: Literal[True]
    is_simulated: bool = False
    read_only: Literal[True] = True
    external_write_permitted: Literal[False] = False
    raw_personal_data_embedded: Literal[False] = False
    record_binding_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")

    @field_validator("production_window_start", "production_window_end", "exported_at")
    @classmethod
    def validate_timestamps(cls, value: datetime) -> datetime:
        return _require_aware(value)

    @model_validator(mode="after")
    def validate_authority_and_binding(self) -> BatchTraceRecord:
        if self.production_window_end < self.production_window_start:
            raise ValueError("production window end must not precede start")
        if self.exported_at < self.production_window_end:
            raise ValueError("batch export must not precede production window end")
        if (
            self.authority_status is ManufacturingRecordAuthorityStatus.VERIFIED
            and self.source_authorization_sha256 is None
        ):
            raise ValueError("verified batch record requires source authorization")
        payload = self.model_dump(mode="json", exclude={"record_binding_sha256"})
        if not hmac.compare_digest(self.record_binding_sha256, _sha256(payload)):
            raise ValueError("batch trace record failed binding integrity validation")
        return self


class ProductionChangeRecord(ProductModel):
    """Read-only, authority-scoped production or solution change record."""

    schema_version: Literal["visiondata-gate.production-change-record.v1"] = (
        "visiondata-gate.production-change-record.v1"
    )
    record_id: str = Field(pattern=r"^[a-zA-Z0-9_.:-]{3,160}$")
    change_order_id: str = Field(min_length=1, max_length=160)
    change_kind: ProductionChangeKind
    change_status: Literal["APPROVED_EFFECTIVE", "DRAFT", "CANCELLED"]
    source_kind: Literal[
        "MES_CHANGELOG_EXPORT",
        "WORK_ORDER_CHANGELOG",
        "APPROVED_OFFLINE_EXPORT",
    ]
    source_system_id_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    source_record_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    source_authorization_sha256: str | None = Field(
        default=None, pattern=r"^[0-9a-f]{64}$"
    )
    authority_status: ManufacturingRecordAuthorityStatus
    line_id: str = Field(min_length=1, max_length=160)
    work_order_id: str = Field(min_length=1, max_length=160)
    batch_id: str = Field(min_length=1, max_length=160)
    lot_reference: str = Field(min_length=1, max_length=160)
    effective_at: datetime
    recorded_at: datetime
    exported_at: datetime
    previous_product_id: str | None = Field(default=None, max_length=160)
    new_product_id: str | None = Field(default=None, max_length=160)
    previous_recipe_id: str | None = Field(default=None, max_length=160)
    new_recipe_id: str | None = Field(default=None, max_length=160)
    previous_configuration_id: str | None = Field(default=None, max_length=160)
    new_configuration_id: str | None = Field(default=None, max_length=160)
    previous_solution_manifest_sha256: str | None = Field(
        default=None, pattern=r"^[0-9a-f]{64}$"
    )
    new_solution_manifest_sha256: str | None = Field(
        default=None, pattern=r"^[0-9a-f]{64}$"
    )
    previous_process_contract_sha256: str | None = Field(
        default=None, pattern=r"^[0-9a-f]{64}$"
    )
    new_process_contract_sha256: str | None = Field(
        default=None, pattern=r"^[0-9a-f]{64}$"
    )
    operator_attests_authorized_export: Literal[True]
    is_simulated: bool = False
    read_only: Literal[True] = True
    equipment_control_permitted: Literal[False] = False
    record_binding_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")

    @field_validator("effective_at", "recorded_at", "exported_at")
    @classmethod
    def validate_timestamps(cls, value: datetime) -> datetime:
        return _require_aware(value)

    @model_validator(mode="after")
    def validate_change_and_binding(self) -> ProductionChangeRecord:
        if self.recorded_at < self.effective_at:
            raise ValueError("change record time must not precede effective time")
        if self.exported_at < self.recorded_at:
            raise ValueError("change export must not precede record time")
        pairs = {
            "product": (self.previous_product_id, self.new_product_id),
            "recipe": (self.previous_recipe_id, self.new_recipe_id),
            "configuration": (
                self.previous_configuration_id,
                self.new_configuration_id,
            ),
            "solution": (
                self.previous_solution_manifest_sha256,
                self.new_solution_manifest_sha256,
            ),
            "process": (
                self.previous_process_contract_sha256,
                self.new_process_contract_sha256,
            ),
        }
        for label, pair in pairs.items():
            if (pair[0] is None) != (pair[1] is None):
                raise ValueError(f"previous/new {label} values travel together")
        changed = {label for label, pair in pairs.items() if pair[0] != pair[1]}
        required_domain = {
            ProductionChangeKind.PRODUCT_CHANGEOVER: "product",
            ProductionChangeKind.RECIPE_CHANGE: "recipe",
            ProductionChangeKind.VISION_SOLUTION_UPGRADE: "solution",
            ProductionChangeKind.PROCESS_SETPOINT_CHANGE: "process",
        }[self.change_kind]
        if required_domain not in changed:
            raise ValueError(
                f"{self.change_kind.value} requires a changed {required_domain} pair"
            )
        if (
            self.authority_status is ManufacturingRecordAuthorityStatus.VERIFIED
            and self.source_authorization_sha256 is None
        ):
            raise ValueError("verified production change requires source authorization")
        payload = self.model_dump(mode="json", exclude={"record_binding_sha256"})
        if not hmac.compare_digest(self.record_binding_sha256, _sha256(payload)):
            raise ValueError(
                "production change record failed binding integrity validation"
            )
        return self


def build_batch_trace_record(**values: object) -> BatchTraceRecord:
    """Seal a normalized batch record after Pydantic applies all defaults."""

    draft = BatchTraceRecord.model_construct(**values, record_binding_sha256="0" * 64)
    payload = draft.model_dump(mode="json", exclude={"record_binding_sha256"})
    return BatchTraceRecord(**payload, record_binding_sha256=_sha256(payload))


def build_production_change_record(**values: object) -> ProductionChangeRecord:
    """Seal a normalized production change record after applying defaults."""

    draft = ProductionChangeRecord.model_construct(
        **values, record_binding_sha256="0" * 64
    )
    payload = draft.model_dump(mode="json", exclude={"record_binding_sha256"})
    return ProductionChangeRecord(**payload, record_binding_sha256=_sha256(payload))


def verify_batch_trace_record(record: BatchTraceRecord) -> None:
    payload = record.model_dump(mode="json", exclude={"record_binding_sha256"})
    if not hmac.compare_digest(record.record_binding_sha256, _sha256(payload)):
        raise ValueError("batch trace record failed binding integrity validation")


def verify_production_change_record(record: ProductionChangeRecord) -> None:
    payload = record.model_dump(mode="json", exclude={"record_binding_sha256"})
    if not hmac.compare_digest(record.record_binding_sha256, _sha256(payload)):
        raise ValueError("production change record failed binding integrity validation")


class IndustrialIncidentTrigger(ProductModel):
    trigger_kind: IncidentTriggerKind
    triggered_at: datetime
    operator_message: str = Field(min_length=8, max_length=1200)
    product_id: str = Field(min_length=1, max_length=160)
    part_id: str | None = Field(default=None, max_length=160)
    recipe_id: str = Field(min_length=1, max_length=160)
    configuration_id: str = Field(min_length=1, max_length=160)
    batch_id: str | None = Field(default=None, max_length=160)
    lot_reference: str | None = Field(default=None, max_length=160)
    work_order_id: str | None = Field(default=None, max_length=160)
    line_id: str | None = Field(default=None, max_length=160)
    baseline_ng_rate: float | None = Field(default=None, ge=0.0, le=1.0)
    observed_ng_rate: float | None = Field(default=None, ge=0.0, le=1.0)
    sample_count: int = Field(ge=1)

    @field_validator("triggered_at")
    @classmethod
    def validate_triggered_at(cls, value: datetime) -> datetime:
        return _require_aware(value)

    @model_validator(mode="after")
    def validate_rate_trigger(self) -> IndustrialIncidentTrigger:
        if self.trigger_kind is IncidentTriggerKind.NG_RATE_DRIFT and (
            self.baseline_ng_rate is None or self.observed_ng_rate is None
        ):
            raise ValueError("NG_RATE_DRIFT requires baseline and observed NG rates")
        return self


class _IndustrialIncidentRequestBase(ProductModel):
    _legacy_canonical_payload: dict[str, object] | None = PrivateAttr(default=None)
    _legacy_normalized_sha256: str | None = PrivateAttr(default=None)

    trigger: IndustrialIncidentTrigger
    opcua_snapshot: OPCUAOfflineSnapshot
    vision_solution: VisionSolutionManifest
    offline_run: OfflineVisionRunReceipt
    process_signal_expectations: list[ProcessSignalExpectation] = Field(
        default_factory=list, max_length=64
    )
    knowledge_references: list[IncidentKnowledgeReference] = Field(
        default_factory=list, max_length=24
    )
    baseline_solution_manifest_sha256: str | None = Field(
        default=None, pattern=r"^[0-9a-f]{64}$"
    )
    max_signal_age_seconds: int = Field(default=120, ge=1, le=86_400)
    max_clock_skew_seconds: int = Field(default=5, ge=0, le=300)
    max_cross_source_skew_seconds: int = Field(default=30, ge=0, le=3_600)
    max_agent_iterations: int = Field(default=4, ge=1, le=12)
    max_dynamic_workers: int = Field(default=10, ge=1, le=12)
    supersedes_case_id: str | None = Field(
        default=None, pattern=r"^incident_[0-9a-f]{20}$"
    )
    # A short-lived pre-v3 build persisted these two lineage keys under the v1
    # schema.  They remain readable, but are serialized only when they existed
    # in the original payload.  New v1/v2 requests never gain v3 fields.
    expected_parent_case_sha256: str | None = Field(
        default=None, pattern=r"^[0-9a-f]{64}$"
    )
    authorizing_decision_id: str | None = Field(
        default=None, pattern=r"^incident_decision_[0-9a-f]{20}$"
    )
    operator_attests_inputs_authorized: Literal[True]
    raw_industrial_data_redistribution_allowed: Literal[False] = False

    @model_validator(mode="after")
    def validate_signal_contract(self) -> _IndustrialIncidentRequestBase:
        aliases = [item.semantic_alias for item in self.process_signal_expectations]
        if len(aliases) != len(set(aliases)):
            raise ValueError("process signal expectations must have unique aliases")
        outside = sorted(set(aliases) - set(self.opcua_snapshot.allowlisted_aliases))
        if outside:
            raise ValueError(
                "process signal expectations escaped the OPC UA allowlist: "
                + ", ".join(outside)
            )
        return self

    @model_serializer(mode="wrap")
    def serialize_versioned_request(self, handler):
        payload = handler(self)
        if (
            self._legacy_canonical_payload is not None
            and self._legacy_normalized_sha256 is not None
            and hmac.compare_digest(_sha256(payload), self._legacy_normalized_sha256)
        ):
            return deepcopy(self._legacy_canonical_payload)
        if self.schema_version in {
            "visiondata-gate.industrial-incident-request.v1",
            "visiondata-gate.industrial-incident-request.v2",
        }:
            for field_name in (
                "expected_parent_case_sha256",
                "authorizing_decision_id",
            ):
                if field_name not in self.model_fields_set:
                    payload.pop(field_name, None)
        return payload

    def model_copy(self, *, update=None, deep: bool = False):
        copied = super().model_copy(update=update, deep=deep)
        if update:
            copied._legacy_canonical_payload = None
            copied._legacy_normalized_sha256 = None
        return copied


class IndustrialIncidentRequestV1(_IndustrialIncidentRequestBase):
    """Original evidence request; retained as an immutable read contract."""

    schema_version: Literal["visiondata-gate.industrial-incident-request.v1"] = (
        "visiondata-gate.industrial-incident-request.v1"
    )

    @property
    def batch_trace_record(self) -> None:
        return None

    @property
    def production_change_records(self) -> list[ProductionChangeRecord]:
        return []

    @property
    def max_production_record_skew_seconds(self) -> int:
        return 300

    @property
    def max_change_lookback_seconds(self) -> int:
        return 86_400


class IndustrialIncidentRequestV2(_IndustrialIncidentRequestBase):
    """Manufacturing-context request without Runtime Profile settings."""

    schema_version: Literal["visiondata-gate.industrial-incident-request.v2"] = (
        "visiondata-gate.industrial-incident-request.v2"
    )
    batch_trace_record: BatchTraceRecord
    production_change_records: list[ProductionChangeRecord] = Field(
        min_length=1, max_length=16
    )
    max_production_record_skew_seconds: int = Field(default=300, ge=0, le=86_400)
    max_change_lookback_seconds: int = Field(default=86_400, ge=1, le=2_592_000)

    @model_validator(mode="after")
    def validate_manufacturing_contract(self) -> IndustrialIncidentRequestV2:
        change_ids = [item.record_id for item in self.production_change_records]
        if len(change_ids) != len(set(change_ids)):
            raise ValueError("production change record IDs must be unique")
        return self


class IndustrialIncidentRequestV3(IndustrialIncidentRequestV2):
    """Current immutable request with an explicit, secret-free Runtime Profile."""

    schema_version: Literal["visiondata-gate.industrial-incident-request.v3"] = (
        "visiondata-gate.industrial-incident-request.v3"
    )
    runtime_profile: IncidentRuntimeProfile

    @model_validator(mode="after")
    def validate_v3_lineage(self) -> IndustrialIncidentRequestV3:
        resume_fields = (
            self.supersedes_case_id,
            self.expected_parent_case_sha256,
            self.authorizing_decision_id,
        )
        if any(value is not None for value in resume_fields) and not all(
            value is not None for value in resume_fields
        ):
            raise ValueError(
                "supersedes_case_id, expected_parent_case_sha256, and "
                "authorizing_decision_id travel together"
            )
        return self


IndustrialIncidentRequest = Annotated[
    IndustrialIncidentRequestV1
    | IndustrialIncidentRequestV2
    | IndustrialIncidentRequestV3,
    Field(discriminator="schema_version"),
]

_INDUSTRIAL_INCIDENT_REQUEST_ADAPTER = TypeAdapter(IndustrialIncidentRequest)


def parse_industrial_incident_request(payload: object) -> IndustrialIncidentRequest:
    """Parse exactly one request schema without upgrading its serialized shape."""

    if isinstance(
        payload,
        (
            IndustrialIncidentRequestV1,
            IndustrialIncidentRequestV2,
            IndustrialIncidentRequestV3,
        ),
    ):
        return payload
    request = _INDUSTRIAL_INCIDENT_REQUEST_ADAPTER.validate_python(payload)
    if isinstance(request, (IndustrialIncidentRequestV1, IndustrialIncidentRequestV2)):
        if not isinstance(payload, dict):
            raise ValueError("legacy incident request payload must be a JSON object")
        normalized = request.model_dump(mode="json")
        request._legacy_canonical_payload = deepcopy(payload)
        request._legacy_normalized_sha256 = _sha256(normalized)
    return request


def parse_industrial_incident_request_json(
    payload: str | bytes | bytearray,
) -> IndustrialIncidentRequest:
    """JSON counterpart of :func:`parse_industrial_incident_request`."""

    return parse_industrial_incident_request(json.loads(payload))


def incident_runtime_profile(
    request: IndustrialIncidentRequest,
) -> IncidentRuntimeProfile | None:
    """Return v3 settings without injecting a nullable field into legacy schemas."""

    if isinstance(request, IndustrialIncidentRequestV3):
        return request.runtime_profile
    return None


class IncidentCapaEvidence(ProductModel):
    """Exact, verified CAPA chain selected by the authorizing incident decision."""

    capa_case_id: str = Field(pattern=r"^capa_[0-9a-f]{20}$")
    remediation_plan_id: str = Field(min_length=1, max_length=160)
    selection_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    approval_binding_sha256: str | None = Field(default=None, pattern=r"^[0-9a-f]{64}$")
    derived_version_receipt_sha256: str | None = Field(
        default=None, pattern=r"^[0-9a-f]{64}$"
    )
    execution_receipt_sha256: str | None = Field(
        default=None, pattern=r"^[0-9a-f]{64}$"
    )
    recovery_receipt_sha256: str | None = Field(default=None, pattern=r"^[0-9a-f]{64}$")
    child_task_id: str | None = None
    child_evidence_sha256: str | None = Field(default=None, pattern=r"^[0-9a-f]{64}$")
    recovery_status: Literal[
        "NOT_EXECUTED",
        "RECOVERED_TO_HUMAN_REVIEW",
        "STILL_BLOCKED",
        "TRANSFERRED_TO_INVESTIGATION",
    ] = "NOT_EXECUTED"
    recovery_success: bool = False
    production_release_allowed: Literal[False] = False

    @model_validator(mode="after")
    def validate_recovery_chain(self) -> IncidentCapaEvidence:
        recovery_fields = (
            self.recovery_receipt_sha256,
            self.child_task_id,
            self.child_evidence_sha256,
        )
        has_recovery = self.recovery_status != "NOT_EXECUTED"
        if has_recovery != all(value is not None for value in recovery_fields):
            raise ValueError(
                "recovery status requires receipt, child task, and child evidence"
            )
        if self.recovery_success != (
            self.recovery_status == "RECOVERED_TO_HUMAN_REVIEW"
        ):
            raise ValueError("recovery_success must match recovery_status")
        return self


class IndustrialGateContext(ProductModel):
    """Frozen facts imported from an already-completed Gate task."""

    task_id: str
    gate_final_decision: str
    task_evidence_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    industrial_delivery_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    source_profile_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    source_authorization_event_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    source_kind: Literal[
        "synthetic_demo",
        "local_authorized_directory",
        "external_residency_reference",
    ] = "synthetic_demo"
    source_authorization_status: Literal[
        "ACTIVE", "REVOKED", "EXPIRED", "UNAVAILABLE", "NOT_APPLICABLE"
    ] = "NOT_APPLICABLE"
    dynamic_response_count: int = Field(ge=0)
    open_work_order_count: int = Field(ge=0)
    remediation_plan_ids: list[str]
    model_call_count: int = Field(ge=0)
    risk_cluster_count: int = Field(default=0, ge=0)
    child_run_status: Literal[
        "NOT_STARTED", "RUNNING", "COMPLETED", "TRANSFERRED_TO_INVESTIGATION"
    ] = "NOT_STARTED"
    capa_evidence: IncidentCapaEvidence | None = None


class IncidentEvidenceRef(ProductModel):
    evidence_type: Literal[
        "opcua_snapshot",
        "vision_solution_manifest",
        "offline_vision_run",
        "quality_inspection_result",
        "batch_trace_record",
        "production_change_record",
        "gate_evidence_package",
        "industrial_delivery",
        "source_authorization",
        "knowledge_reference",
        "capa_selection",
        "capa_approval",
        "capa_derived_version",
        "capa_execution",
        "capa_recovery",
    ]
    evidence_ref: str
    evidence_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    qualification: EvidenceQualification
    role_in_decision: str


class IncidentEvidenceIssue(ProductModel):
    issue_code: str = Field(pattern=r"^[A-Z0-9_]{3,80}$")
    severity: Literal["BLOCKING", "WARNING"]
    evidence_source: str
    summary: str
    required_evidence_or_action: str
    worker_role: str
    blocks_disposition: bool
    producer_type: Literal["WORKER_RECEIPT", "DETERMINISTIC_PREFLIGHT"] = (
        "WORKER_RECEIPT"
    )
    producer_invocation_id: str | None = None
    producer_receipt_sha256: str | None = Field(default=None, pattern=r"^[0-9a-f]{64}$")
    input_evidence_refs: list[str] = Field(default_factory=list)


class IncidentHypothesis(ProductModel):
    hypothesis_id: str
    category: Literal[
        "evidence_failure",
        "traceability_mismatch",
        "process_deviation",
        "vision_configuration_drift",
        "visual_data_quality",
        "true_product_defect",
    ]
    statement: str
    status: HypothesisStatus
    supporting_issue_codes: list[str]
    contradicting_issue_codes: list[str] = Field(default_factory=list)
    unresolved_evidence_refs: list[str] = Field(default_factory=list)
    next_discriminating_test: str


class IncidentAgentAction(ProductModel):
    sequence: int = Field(ge=1)
    iteration: int = Field(default=1, ge=1)
    agent_role: str
    action: str
    status: Literal["COMPLETED", "DISPATCHED", "PENDING_HUMAN", "STOPPED", "FAILED"]
    dynamic: bool
    reason_codes: list[str]
    input_refs: list[str]
    expected_output: str
    tool_contracts: list[str]
    output_receipt_sha256: str | None = Field(default=None, pattern=r"^[0-9a-f]{64}$")
    machine_action_permitted: Literal[False] = False


class IncidentWorkerReceipt(ProductModel):
    """Tamper-evident output from one actually invoked deterministic Worker."""

    schema_version: Literal["visiondata-gate.incident-worker-receipt.v1"] = (
        "visiondata-gate.incident-worker-receipt.v1"
    )
    invocation_id: str = Field(pattern=r"^worker_invocation_[0-9a-f]{20}$")
    iteration: int = Field(ge=1)
    worker_role: str = Field(min_length=1, max_length=120)
    worker_version: str = Field(min_length=1, max_length=80)
    status: Literal["SUCCEEDED", "FAILED"]
    attempt: int = Field(default=1, ge=1, le=3)
    trigger_reason_codes: list[str] = Field(min_length=1)
    input_evidence_sha256: list[str] = Field(min_length=1)
    tool_contracts: list[str] = Field(min_length=1)
    output_issues: list[IncidentEvidenceIssue]
    observations: list[str]
    output_artifact_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    error_code: str | None = None
    retryable: bool = False
    receipt_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")


class IncidentEvidenceEdge(ProductModel):
    edge_id: str = Field(pattern=r"^edge_[0-9a-f]{16}$")
    hypothesis_id: str
    relation: Literal["SUPPORTS", "CONTRADICTS", "UNRESOLVED"]
    issue_code: str | None = None
    evidence_ref: str
    qualification: EvidenceQualification
    producer_receipt_sha256: str | None = Field(default=None, pattern=r"^[0-9a-f]{64}$")


class IncidentProgressLedger(ProductModel):
    evidence_bundle_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    previous_evidence_bundle_sha256: str | None = Field(
        default=None, pattern=r"^[0-9a-f]{64}$"
    )
    evaluated_issue_codes: list[str]
    newly_observed_issue_codes: list[str]
    resolved_issue_codes: list[str]
    hypothesis_state_changes: list[str]
    completed_worker_invocations: list[str]
    repeated_invocation_signatures: list[str]
    progress_made: bool
    stall_count: int = Field(ge=0)
    replan_reason: str


class IncidentPhaseEvent(ProductModel):
    """One tamper-evident event in the case-local Agent execution chain."""

    schema_version: Literal["visiondata-gate.incident-phase-event.v1"] = (
        "visiondata-gate.incident-phase-event.v1"
    )
    event_id: str = Field(pattern=r"^incident_event_[0-9a-f]{20}$")
    case_id: str = Field(pattern=r"^incident_[0-9a-f]{20}$")
    case_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    sequence: int = Field(ge=1)
    iteration: int = Field(ge=1)
    phase: Literal["PLAN", "ACT", "OBSERVE", "EVALUATE", "INTERRUPT"]
    invocation_id: str = Field(pattern=r"^(?:worker|phase)_invocation_[0-9a-f]{20}$")
    actor: str = Field(min_length=1, max_length=120)
    input_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    output_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    status: Literal["SUCCEEDED", "FAILED", "STOPPED", "PAUSED"]
    error_code: str | None = Field(default=None, pattern=r"^[A-Z0-9_]{3,100}$")
    retryable: bool = False
    prev_event_sha256: str | None = Field(default=None, pattern=r"^[0-9a-f]{64}$")
    event_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")


class IndustrialIncidentCase(ProductModel):
    _canonical_payload_override: dict[str, object] | None = PrivateAttr(default=None)
    _normalized_payload_sha256: str | None = PrivateAttr(default=None)

    schema_version: Literal[
        "visiondata-gate.industrial-incident-case.v1",
        "visiondata-gate.industrial-incident-case.v2",
        "visiondata-gate.industrial-incident-case.v3",
        "visiondata-gate.industrial-incident-case.v4",
        "visiondata-gate.industrial-incident-case.v5",
        "visiondata-gate.industrial-incident-case.v6",
    ] = GOVERNED_INCIDENT_CASE_SCHEMA_VERSION
    audit_envelope_requirement: Literal["REQUIRED"] | None = None
    case_id: str = Field(pattern=r"^incident_[0-9a-f]{20}$")
    incident_root_id: str | None = Field(
        default=None, pattern=r"^incident_[0-9a-f]{20}$"
    )
    case_version: int = Field(default=1, ge=1)
    parent_case_id: str | None = Field(default=None, pattern=r"^incident_[0-9a-f]{20}$")
    parent_case_sha256: str | None = Field(default=None, pattern=r"^[0-9a-f]{64}$")
    authorizing_decision_id: str | None = Field(
        default=None, pattern=r"^incident_decision_[0-9a-f]{20}$"
    )
    authorizing_decision_sha256: str | None = Field(
        default=None, pattern=r"^[0-9a-f]{64}$"
    )
    task_id: str
    target_user: Literal["中小制造企业质量负责人"] = "中小制造企业质量负责人"
    task_boundary: Literal["换型后视觉质量异常处置与方案复验"] = (
        "换型后视觉质量异常处置与方案复验"
    )
    request: IndustrialIncidentRequest
    gate_context: IndustrialGateContext
    context_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    evidence_bundle_sha256: str | None = Field(default=None, pattern=r"^[0-9a-f]{64}$")
    evidence_refs: list[IncidentEvidenceRef] = Field(min_length=6)
    evidence_issues: list[IncidentEvidenceIssue]
    hypotheses: list[IncidentHypothesis] = Field(min_length=6)
    evidence_edges: list[IncidentEvidenceEdge] = Field(default_factory=list)
    planning_belief_ledger: EvidenceBeliefLedgerV2 | None = None
    worker_selection_receipt: WorkerSelectionReceipt | None = None
    parent_belief_revision_receipt: EvidenceBeliefRevisionReceiptV1 | None = None
    worker_execution_plan_receipt: WorkerExecutionPlanReceiptV1 | None = None
    council_arbitration_receipt: CouncilArbitrationReceiptV1 | None = None
    autonomy_guard_receipt: AutonomyGuardReceiptV1 | None = None
    agent_actions: list[IncidentAgentAction] = Field(min_length=3)
    worker_receipts: list[IncidentWorkerReceipt] = Field(default_factory=list)
    model_planner_receipt: IncidentModelPlannerReceipt | None = None
    governed_memory_planning_input_sha256: str | None = Field(
        default=None,
        pattern=r"^[0-9a-f]{64}$",
    )
    governed_memory_retrieval_receipt_sha256: str | None = Field(
        default=None,
        pattern=r"^[0-9a-f]{64}$",
    )
    loop_steps: list[IncidentLoopStep] = Field(min_length=5)
    loop_control: IncidentLoopControl
    progress_ledger: IncidentProgressLedger | None = None
    knowledge_references: list[IncidentKnowledgeReference] = Field(min_length=1)
    decision_summary: IncidentDecisionSummary
    dynamic_branch_count: int = Field(ge=0)
    status: IncidentStatus
    recommendation: IncidentRecommendation
    recommendation_reason: str
    operator_questions: list[IncidentOperatorQuestion]
    linked_remediation_plan_ids: list[str]
    root_cause_status: Literal["NOT_ESTABLISHED"] = "NOT_ESTABLISHED"
    planning_mode: Literal[
        "deterministic_evidence_policy_v1",
        "bounded_evidence_agent_loop_v2",
        "bounded_model_planner_loop_v3",
    ] = "bounded_evidence_agent_loop_v2"
    external_model_call_count: int = Field(ge=0)
    opcua_connection_status: Literal[
        "OPC_UA_REAL_ENDPOINT_NOT_CONNECTED",
        "OPC_UA_FIXTURE_REPLAY_ONLY",
    ]
    visionmaster_connection_status: Literal["VISIONMASTER_SDK_NOT_CONNECTED"] = (
        "VISIONMASTER_SDK_NOT_CONNECTED"
    )
    human_approval_required: Literal[True] = True
    production_release_allowed: Literal[False] = False
    machine_write_permitted: Literal[False] = False
    direct_equipment_control_permitted: Literal[False] = False
    case_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    claim_boundary: str = (
        "This sidecar case is a deterministic decision-support artifact over an "
        "authorized Gate task plus offline industrial evidence. It is not a live OPC "
        "UA or VisionMaster connection, root-cause proof, factory deployment, customer "
        "acceptance, production release, or authority to control equipment."
    )

    @model_serializer(mode="wrap")
    def serialize_preserving_loaded_canonical_payload(self, handler):
        payload = handler(self)
        if (
            self._canonical_payload_override is not None
            and self._normalized_payload_sha256 is not None
            and hmac.compare_digest(_sha256(payload), self._normalized_payload_sha256)
        ):
            return deepcopy(self._canonical_payload_override)
        return payload

    def model_copy(self, *, update=None, deep: bool = False):
        copied = super().model_copy(update=update, deep=deep)
        if update:
            copied._canonical_payload_override = None
            copied._normalized_payload_sha256 = None
        return copied

    @model_validator(mode="after")
    def validate_versioned_governance_and_lineage(self) -> IndustrialIncidentCase:
        if self.schema_version in GOVERNED_INCIDENT_CASE_SCHEMA_VERSIONS:
            if self.audit_envelope_requirement != GOVERNED_AUDIT_ENVELOPE_REQUIREMENT:
                raise ValueError(
                    "governed incident case requires a governed audit envelope"
                )
        elif self.audit_envelope_requirement is not None:
            raise ValueError(
                "legacy incident case cannot carry a governed audit requirement"
            )
        has_planning_artifacts = (
            self.planning_belief_ledger is not None
            or self.worker_selection_receipt is not None
        )
        if self.schema_version in PLANNING_ARTIFACT_INCIDENT_CASE_SCHEMA_VERSIONS:
            if (
                self.planning_belief_ledger is None
                or self.worker_selection_receipt is None
            ):
                raise ValueError(
                    "v5+ incident case requires belief and Worker-selection artifacts"
                )
        elif has_planning_artifacts:
            raise ValueError("pre-v5 incident case cannot carry v5 planning artifacts")
        agent_kernel_receipts = (
            self.parent_belief_revision_receipt,
            self.worker_execution_plan_receipt,
            self.council_arbitration_receipt,
            self.autonomy_guard_receipt,
        )
        if self.schema_version == AGENT_KERNEL_INCIDENT_CASE_SCHEMA_VERSION:
            if any(
                item is None
                for item in (
                    self.worker_execution_plan_receipt,
                    self.council_arbitration_receipt,
                    self.autonomy_guard_receipt,
                )
            ):
                raise ValueError("v6 incident case requires Agent-kernel receipts")
            if (
                self.case_version == 1
                and self.parent_belief_revision_receipt is not None
            ):
                raise ValueError("root v6 incident case cannot revise a parent belief")
            if self.case_version > 1 and self.parent_belief_revision_receipt is None:
                raise ValueError(
                    "resumed v6 incident case requires parent belief revision"
                )
        elif any(item is not None for item in agent_kernel_receipts):
            raise ValueError("pre-v6 incident case cannot carry Agent-kernel receipts")
        if self.schema_version not in PHASE_EVENT_INCIDENT_CASE_SCHEMA_VERSIONS:
            return self
        if self.incident_root_id is None or self.evidence_bundle_sha256 is None:
            raise ValueError(
                "v3 incident case requires root and evidence bundle bindings"
            )
        lineage = (
            self.parent_case_id,
            self.parent_case_sha256,
            self.authorizing_decision_id,
            self.authorizing_decision_sha256,
        )
        if self.case_version == 1 and any(value is not None for value in lineage):
            raise ValueError("root incident case must not contain resume lineage")
        if self.case_version > 1 and not all(value is not None for value in lineage):
            raise ValueError(
                "resumed incident case requires complete parent and decision lineage"
            )
        return self


_P = ParamSpec("_P")
_R = TypeVar("_R")
_IncidentCaseVerificationCache = dict[int, tuple[IndustrialIncidentCase, str]]
_INCIDENT_CASE_VERIFICATION_CACHE: ContextVar[_IncidentCaseVerificationCache | None] = (
    ContextVar("incident_case_verification_cache", default=None)
)


@contextmanager
def incident_case_verification_scope() -> Iterator[None]:
    """Bound successful Case verification reuse to one trusted call graph.

    Nested scopes share the outer cache. The outermost exit always discards it,
    so another service request must read and verify its artifacts again. Cache
    entries retain the exact object and sealed digest to prevent object-id reuse
    or a different Case object from inheriting a prior verification.

    A scoped call graph must not expose a mutable Case object to untrusted code.
    ProductService uses this only around synchronous, internal Incident methods.
    """

    if _INCIDENT_CASE_VERIFICATION_CACHE.get() is not None:
        yield
        return
    token = _INCIDENT_CASE_VERIFICATION_CACHE.set({})
    try:
        yield
    finally:
        _INCIDENT_CASE_VERIFICATION_CACHE.reset(token)


def reuse_incident_case_verification(
    function: Callable[_P, _R],
) -> Callable[_P, _R]:
    """Run one synchronous entry point in a bounded verification scope."""

    @wraps(function)
    def wrapped(*args: _P.args, **kwargs: _P.kwargs) -> _R:
        with incident_case_verification_scope():
            return function(*args, **kwargs)

    return wrapped


def incident_case_requires_governed_audit_envelope(
    case: IndustrialIncidentCase,
) -> bool:
    """Classify governance from the immutable case protocol, never file absence."""

    if case.schema_version in GOVERNED_INCIDENT_CASE_SCHEMA_VERSIONS:
        if case.audit_envelope_requirement != GOVERNED_AUDIT_ENVELOPE_REQUIREMENT:
            raise ValueError(
                "governed incident case lost its governed audit requirement"
            )
        return True
    if case.schema_version in LEGACY_INCIDENT_CASE_SCHEMA_VERSIONS:
        if case.audit_envelope_requirement is not None:
            raise ValueError("legacy incident case has an invalid audit requirement")
        return False
    raise ValueError("industrial incident case uses an unsupported schema version")


def parse_industrial_incident_case(payload: object) -> IndustrialIncidentCase:
    """Validate a stored case without rewriting its historical canonical shape."""

    if isinstance(payload, IndustrialIncidentCase):
        verify_industrial_incident_case(payload)
        return payload
    if not isinstance(payload, dict):
        raise ValueError("industrial incident case payload must be a JSON object")
    raw_payload = deepcopy(payload)
    stored_sha256 = raw_payload.get("case_sha256")
    if not isinstance(stored_sha256, str):
        raise ValueError("industrial incident case is missing case_sha256")
    stable = dict(raw_payload)
    stable.pop("case_sha256", None)
    if not hmac.compare_digest(stored_sha256, _sha256(stable)):
        raise ValueError("industrial incident case failed raw SHA-256 validation")
    case = IndustrialIncidentCase.model_validate(raw_payload)
    request_payload = raw_payload.get("request")
    if isinstance(
        case.request, (IndustrialIncidentRequestV1, IndustrialIncidentRequestV2)
    ) and isinstance(request_payload, dict):
        normalized_request = case.request.model_dump(mode="json")
        case.request._legacy_canonical_payload = deepcopy(request_payload)
        case.request._legacy_normalized_sha256 = _sha256(normalized_request)
    normalized_case = case.model_dump(mode="json")
    case._canonical_payload_override = raw_payload
    case._normalized_payload_sha256 = _sha256(normalized_case)
    verify_industrial_incident_case(case)
    return case


def parse_industrial_incident_case_json(
    payload: str | bytes | bytearray,
) -> IndustrialIncidentCase:
    """JSON counterpart of :func:`parse_industrial_incident_case`."""

    return parse_industrial_incident_case(json.loads(payload))


class IndustrialIncidentDecisionRequest(ProductModel):
    bound_case_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    decision: IncidentHumanDecision
    note: str = Field(min_length=8, max_length=1200)
    selected_remediation_plan_id: str | None = Field(default=None, max_length=160)
    operator_attests_reviewed_evidence: Literal[True]
    production_release_requested: Literal[False] = False
    equipment_control_requested: Literal[False] = False

    @model_validator(mode="after")
    def validate_plan_selection(self) -> IndustrialIncidentDecisionRequest:
        if (self.decision is IncidentHumanDecision.SELECT_REMEDIATION_PLAN) != (
            self.selected_remediation_plan_id is not None
        ):
            raise ValueError(
                "SELECT_REMEDIATION_PLAN and selected_remediation_plan_id travel together"
            )
        return self


class IndustrialIncidentDecisionReceipt(ProductModel):
    schema_version: Literal["visiondata-gate.industrial-incident-decision.v1"] = (
        "visiondata-gate.industrial-incident-decision.v1"
    )
    decision_id: str = Field(pattern=r"^incident_decision_[0-9a-f]{20}$")
    case_id: str = Field(pattern=r"^incident_[0-9a-f]{20}$")
    case_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    task_id: str
    actor_user_id: str
    decision: IncidentHumanDecision
    note: str
    selected_remediation_plan_id: str | None = None
    linked_capa_case_id: str | None = Field(
        default=None, pattern=r"^capa_[0-9a-f]{20}$"
    )
    decided_at: datetime
    production_release_allowed: Literal[False] = False
    equipment_control_allowed: Literal[False] = False
    decision_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    claim_boundary: str = (
        "This receipt records a named human workflow decision bound to one incident "
        "case. It is not a production release, equipment-control authorization, or "
        "proof that a selected CAPA has executed."
    )

    @field_validator("decided_at")
    @classmethod
    def validate_decided_at(cls, value: datetime) -> datetime:
        return _require_aware(value)


class IndustrialIncidentDecisionConsumptionReceipt(ProductModel):
    """Append-only proof that one decision authorized exactly one child case."""

    schema_version: Literal[
        "visiondata-gate.industrial-incident-decision-consumption.v1"
    ] = "visiondata-gate.industrial-incident-decision-consumption.v1"
    parent_case_id: str = Field(pattern=r"^incident_[0-9a-f]{20}$")
    parent_case_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    decision_id: str = Field(pattern=r"^incident_decision_[0-9a-f]{20}$")
    decision_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    child_case_id: str = Field(pattern=r"^incident_[0-9a-f]{20}$")
    child_case_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    evidence_bundle_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    consumed_at: datetime
    consumption_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")

    @field_validator("consumed_at")
    @classmethod
    def validate_consumed_at(cls, value: datetime) -> datetime:
        return _require_aware(value)


def build_industrial_incident_decision_receipt(
    case: IndustrialIncidentCase,
    request: IndustrialIncidentDecisionRequest,
    *,
    actor_user_id: str,
    decided_at: datetime,
    linked_capa_case_id: str | None = None,
) -> IndustrialIncidentDecisionReceipt:
    """Seal one named human workflow decision against an immutable case.

    Selecting a remediation plan may link an already-created CAPA case, but the
    receipt never approves or executes that CAPA and never grants production or
    equipment-control authority.
    """

    verify_industrial_incident_case(case)
    decided_at = _require_aware(decided_at)
    if not hmac.compare_digest(request.bound_case_sha256, case.case_sha256):
        raise ValueError("incident decision is not bound to the supplied case")
    if request.selected_remediation_plan_id is not None and (
        request.selected_remediation_plan_id not in case.linked_remediation_plan_ids
    ):
        raise ValueError("selected remediation plan is not in the bound case")
    if linked_capa_case_id is not None and (
        request.decision is not IncidentHumanDecision.SELECT_REMEDIATION_PLAN
    ):
        raise ValueError("a CAPA case may only be linked to a plan-selection decision")
    if request.decision is IncidentHumanDecision.SELECT_REMEDIATION_PLAN and (
        linked_capa_case_id is None
    ):
        raise ValueError("plan-selection decision requires a created CAPA case")

    stable = {
        "schema_version": "visiondata-gate.industrial-incident-decision.v1",
        "decision_id": "incident_decision_"
        + _sha256(
            {
                "case_sha256": case.case_sha256,
                "actor_user_id": actor_user_id,
                "decision": request.decision,
                "note": request.note,
                "selected_remediation_plan_id": (request.selected_remediation_plan_id),
                "linked_capa_case_id": linked_capa_case_id,
                "decided_at": decided_at,
            }
        )[:20],
        "case_id": case.case_id,
        "case_sha256": case.case_sha256,
        "task_id": case.task_id,
        "actor_user_id": actor_user_id,
        "decision": request.decision,
        "note": request.note,
        "selected_remediation_plan_id": request.selected_remediation_plan_id,
        "linked_capa_case_id": linked_capa_case_id,
        "decided_at": decided_at,
        "production_release_allowed": False,
        "equipment_control_allowed": False,
        "claim_boundary": IndustrialIncidentDecisionReceipt.model_fields[
            "claim_boundary"
        ].default,
    }
    draft = IndustrialIncidentDecisionReceipt(**stable, decision_sha256="0" * 64)
    serialized = draft.model_dump(mode="json")
    serialized.pop("decision_sha256")
    return draft.model_copy(update={"decision_sha256": _sha256(serialized)})


def verify_industrial_incident_decision_receipt(
    receipt: IndustrialIncidentDecisionReceipt,
    *,
    case: IndustrialIncidentCase | None = None,
) -> None:
    payload = receipt.model_dump(mode="json")
    stored = payload.pop("decision_sha256")
    expected = _sha256(payload)
    if not hmac.compare_digest(stored, expected):
        raise ValueError(
            "industrial incident decision failed SHA-256 integrity validation"
        )
    if case is not None:
        verify_industrial_incident_case(case)
        if not (
            receipt.case_id == case.case_id
            and receipt.task_id == case.task_id
            and hmac.compare_digest(receipt.case_sha256, case.case_sha256)
        ):
            raise ValueError("industrial incident decision failed case binding")


def industrial_incident_evidence_bundle_sha256(
    request: IndustrialIncidentRequest,
) -> str:
    """Hash only evidence and frozen evaluation inputs, excluding resume controls."""

    payload = request.model_dump(mode="json")
    payload.pop("supersedes_case_id", None)
    payload.pop("expected_parent_case_sha256", None)
    payload.pop("authorizing_decision_id", None)
    return _sha256(payload)


def _industrial_incident_observed_evidence_sha256(
    request: IndustrialIncidentRequest,
) -> str:
    """Hash source observations only for the resume new-evidence guard.

    Runtime profiles, loop budgets, validation tolerances, and other execution
    controls may change how a new immutable Case is evaluated, but they are not
    new industrial evidence.  This fingerprint is intentionally separate from
    the versioned ``evidence_bundle_sha256`` so historical Case receipts retain
    their original canonical identity.
    """

    return _sha256(
        {
            "trigger": request.trigger,
            "opcua_snapshot": request.opcua_snapshot,
            "vision_solution": request.vision_solution,
            "offline_run": request.offline_run,
            "batch_trace_record": request.batch_trace_record,
            "production_change_records": request.production_change_records,
            "knowledge_references": request.knowledge_references,
            "baseline_solution_manifest_sha256": (
                request.baseline_solution_manifest_sha256
            ),
        }
    )


class IncidentWorkerExecutionError(RuntimeError):
    """Typed boundary error raised when a selected Worker cannot produce evidence."""

    def __init__(self, error_code: str, *, retryable: bool = False) -> None:
        super().__init__(error_code)
        self.error_code = error_code
        self.retryable = retryable


def _incident_worker_invocation_id(
    *,
    worker_role: str,
    worker_version: str,
    iteration: int,
    trigger_reason_codes: list[str],
    input_evidence_sha256: list[str],
    tool_contracts: list[str],
) -> str:
    invocation_stable = {
        "worker_role": worker_role,
        "worker_version": worker_version,
        "iteration": iteration,
        "trigger_reason_codes": sorted(set(trigger_reason_codes)),
        "input_evidence_sha256": input_evidence_sha256,
        "tool_contracts": tool_contracts,
    }
    return "worker_invocation_" + _sha256(invocation_stable)[:20]


class IncidentWorkerRegistry:
    """Bounded registry for independently invoked deterministic evidence Workers."""

    worker_version = "deterministic-evidence-worker-v1"

    def __init__(self, roles: set[str]) -> None:
        self._roles = frozenset(roles)

    def execute(
        self,
        *,
        worker_role: str,
        iteration: int,
        trigger_reason_codes: list[str],
        input_evidence_sha256: list[str],
        tool_contracts: list[str],
        candidate_issues: list[IncidentEvidenceIssue],
        observations: list[str] | None = None,
    ) -> IncidentWorkerReceipt:
        if worker_role not in self._roles:
            raise ValueError(f"unregistered incident worker: {worker_role}")
        invocation_id = _incident_worker_invocation_id(
            worker_role=worker_role,
            worker_version=self.worker_version,
            iteration=iteration,
            trigger_reason_codes=trigger_reason_codes,
            input_evidence_sha256=input_evidence_sha256,
            tool_contracts=tool_contracts,
        )
        output_issues = [
            item.model_copy(
                update={
                    "producer_type": "WORKER_RECEIPT",
                    "producer_invocation_id": invocation_id,
                    "producer_receipt_sha256": None,
                    "input_evidence_refs": list(input_evidence_sha256),
                }
            )
            for item in candidate_issues
            if item.worker_role == worker_role
        ]
        output_artifact_sha256 = _sha256(
            {
                "invocation_id": invocation_id,
                "output_issues": output_issues,
                "observations": observations or [],
            }
        )
        stable = {
            "schema_version": "visiondata-gate.incident-worker-receipt.v1",
            "invocation_id": invocation_id,
            "iteration": iteration,
            "worker_role": worker_role,
            "worker_version": self.worker_version,
            "status": "SUCCEEDED",
            "attempt": 1,
            "trigger_reason_codes": sorted(set(trigger_reason_codes)),
            "input_evidence_sha256": input_evidence_sha256,
            "tool_contracts": tool_contracts,
            "output_issues": output_issues,
            "observations": observations or [],
            "output_artifact_sha256": output_artifact_sha256,
            "error_code": None,
            "retryable": False,
        }
        return IncidentWorkerReceipt(**stable, receipt_sha256=_sha256(stable))


def _build_failed_incident_worker_receipt(
    *,
    worker_registry: IncidentWorkerRegistry,
    worker_role: str,
    iteration: int,
    trigger_reason_codes: list[str],
    input_evidence_sha256: list[str],
    tool_contracts: list[str],
    failure: IncidentWorkerExecutionError,
) -> IncidentWorkerReceipt:
    """Seal a path-free failure without admitting any Worker output as evidence."""

    invocation_id = _incident_worker_invocation_id(
        worker_role=worker_role,
        worker_version=worker_registry.worker_version,
        iteration=iteration,
        trigger_reason_codes=trigger_reason_codes,
        input_evidence_sha256=input_evidence_sha256,
        tool_contracts=tool_contracts,
    )
    observations = ["Worker 未产生可采信证据；冻结策略必须失败关闭并请求人工补证。"]
    output_artifact_sha256 = _sha256(
        {
            "invocation_id": invocation_id,
            "output_issues": [],
            "observations": observations,
        }
    )
    stable = {
        "schema_version": "visiondata-gate.incident-worker-receipt.v1",
        "invocation_id": invocation_id,
        "iteration": iteration,
        "worker_role": worker_role,
        "worker_version": worker_registry.worker_version,
        "status": "FAILED",
        "attempt": 1,
        "trigger_reason_codes": sorted(set(trigger_reason_codes)),
        "input_evidence_sha256": input_evidence_sha256,
        "tool_contracts": tool_contracts,
        "output_issues": [],
        "observations": observations,
        "output_artifact_sha256": output_artifact_sha256,
        "error_code": failure.error_code,
        "retryable": failure.retryable,
    }
    return IncidentWorkerReceipt(**stable, receipt_sha256=_sha256(stable))


DEFAULT_INCIDENT_WORKER_REGISTRY = IncidentWorkerRegistry(
    {
        "EvidenceQualificationAgent",
        "SignalIntegrityAgent",
        "TraceabilityAgent",
        "ManufacturingContextAgent",
        "ProcessContextAgent",
        "VisionRecipeAgent",
        "VisualDataQualityAgent",
        "CounterevidenceAuditorAgent",
    }
)


def verify_incident_worker_receipt(receipt: IncidentWorkerReceipt) -> None:
    payload = receipt.model_dump(mode="json")
    stored = payload.pop("receipt_sha256")
    if not hmac.compare_digest(stored, _sha256(payload)):
        raise ValueError("incident Worker receipt failed SHA-256 integrity validation")
    expected_output = _sha256(
        {
            "invocation_id": receipt.invocation_id,
            "output_issues": receipt.output_issues,
            "observations": receipt.observations,
        }
    )
    if not hmac.compare_digest(expected_output, receipt.output_artifact_sha256):
        raise ValueError("incident Worker output artifact failed integrity validation")
    if receipt.status != "SUCCEEDED" and receipt.output_issues:
        raise ValueError("failed incident Worker must not publish decision issues")
    if receipt.status == "FAILED" and receipt.error_code is None:
        raise ValueError("failed incident Worker requires an explicit error code")


def build_incident_decision_consumption_receipt(
    *,
    parent_case: IndustrialIncidentCase,
    decision: IndustrialIncidentDecisionReceipt,
    child_case: IndustrialIncidentCase,
) -> IndustrialIncidentDecisionConsumptionReceipt:
    verify_industrial_incident_case(parent_case)
    verify_industrial_incident_decision_receipt(decision, case=parent_case)
    verify_industrial_incident_case(child_case)
    if not (
        child_case.parent_case_id == parent_case.case_id
        and child_case.parent_case_sha256 == parent_case.case_sha256
        and child_case.authorizing_decision_id == decision.decision_id
        and child_case.authorizing_decision_sha256 == decision.decision_sha256
        and child_case.evidence_bundle_sha256 is not None
    ):
        raise ValueError("incident decision consumption failed child lineage binding")
    stable = {
        "schema_version": (
            "visiondata-gate.industrial-incident-decision-consumption.v1"
        ),
        "parent_case_id": parent_case.case_id,
        "parent_case_sha256": parent_case.case_sha256,
        "decision_id": decision.decision_id,
        "decision_sha256": decision.decision_sha256,
        "child_case_id": child_case.case_id,
        "child_case_sha256": child_case.case_sha256,
        "evidence_bundle_sha256": child_case.evidence_bundle_sha256,
        "consumed_at": decision.decided_at,
    }
    # Hash the validated JSON representation so construction and verification
    # use the same canonical UTC rendering (Pydantic normalizes ``+00:00`` to
    # ``Z`` in JSON mode).
    draft = IndustrialIncidentDecisionConsumptionReceipt(
        **stable, consumption_sha256="0" * 64
    )
    payload = draft.model_dump(mode="json", exclude={"consumption_sha256"})
    return draft.model_copy(update={"consumption_sha256": _sha256(payload)})


def verify_incident_decision_consumption_receipt(
    receipt: IndustrialIncidentDecisionConsumptionReceipt,
) -> None:
    payload = receipt.model_dump(mode="json")
    stored = payload.pop("consumption_sha256")
    if not hmac.compare_digest(stored, _sha256(payload)):
        raise ValueError("incident decision consumption failed integrity validation")


def _build_incident_hypotheses(
    issues: list[IncidentEvidenceIssue],
) -> list[IncidentHypothesis]:
    issue_codes = [item.issue_code for item in issues]
    blocking_codes = [item.issue_code for item in issues if item.blocks_disposition]
    qualification_codes = [
        code
        for code in issue_codes
        if code
        in {
            "SOURCE_AUTHORIZATION_NOT_ACTIVE",
            "EXTERNAL_SOURCE_AUTHORIZATION_UNVERIFIED",
            "KNOWLEDGE_REFERENCE_NOT_QUALIFIED",
            "SYNTHETIC_SOURCE_SCOPE",
            "SIMULATED_EVIDENCE_SCOPE",
            "BATCH_RECORD_NOT_AUTHORITY_BOUND",
            "CHANGEOVER_RECORD_NOT_AUTHORITY_BOUND",
            "BATCH_TRACE_RECORD_MISSING",
            "PRODUCTION_CHANGE_RECORD_MISSING",
            "EVIDENCE_NOT_EVALUATED_DUE_TO_BUDGET",
            "WORKER_EXECUTION_FAILED",
        }
    ]
    signal_codes = [
        code
        for code in issue_codes
        if code.startswith(("OPC_", "VISION_RESULT_"))
        or code in {"SNAPSHOT_TIME_WINDOW_MISMATCH", "SOURCE_PROFILE_MISMATCH"}
    ]
    trace_codes = [
        code
        for code in issue_codes
        if code.startswith("CORRELATION_")
        or code
        in {
            "LOT_REFERENCE_NOT_AUTHORITY_BOUND",
            "VISION_RESULT_TIME_WINDOW_MISMATCH",
            "INCIDENT_SAMPLE_COUNT_MISMATCH",
            "INCIDENT_NG_RATE_MISMATCH",
            "BATCH_IDENTITY_CONFLICT",
            "WORK_ORDER_CORRELATION_MISSING",
            "PRODUCTION_RECORD_TIME_WINDOW_MISMATCH",
            "QUALITY_RESULT_BATCH_MISMATCH",
        }
    ]
    process_codes = [
        code
        for code in issue_codes
        if code
        in {
            "PROCESS_SIGNAL_OUT_OF_RANGE",
            "PRODUCTION_CHANGE_SUPPORTS_PROCESS_HYPOTHESIS",
        }
    ]
    process_contradiction_codes = [
        code
        for code in issue_codes
        if code == "PRODUCTION_CHANGE_CONTRADICTS_PROCESS_HYPOTHESIS"
    ]
    vision_codes = [
        code
        for code in issue_codes
        if code
        in {
            "OFFLINE_RUN_MANIFEST_HASH_MISMATCH",
            "VISION_SOLUTION_MANIFEST_DRIFT",
            "VISION_RESULT_NOT_COMPLETED",
            "VISION_RESULT_PARTIAL",
            "SOURCE_PROFILE_MISMATCH",
            "PRODUCTION_CHANGE_SUPPORTS_VISION_HYPOTHESIS",
        }
    ]
    data_codes = [code for code in issue_codes if code == "GATE_DECISION_NOT_PASS"]
    recovery_codes = [
        code for code in issue_codes if code == "CHILD_RUN_RECOVERY_NOT_OBSERVED"
    ]
    return [
        IncidentHypothesis(
            hypothesis_id="H-EVIDENCE-FAILURE",
            category="evidence_failure",
            statement="异常可能来自不可用、过期或语义漂移的设备证据。",
            status=(
                HypothesisStatus.SUPPORTED
                if signal_codes or qualification_codes
                else HypothesisStatus.REJECTED
            ),
            supporting_issue_codes=qualification_codes + signal_codes,
            unresolved_evidence_refs=["opcua-offline-snapshot"],
            next_discriminating_test="获取同一白名单的新 DataValue 快照并复核质量码与双时间戳。",
        ),
        IncidentHypothesis(
            hypothesis_id="H-TRACEABILITY",
            category="traceability_mismatch",
            statement="OPC结果、视觉运行和现场批次可能未指向同一工件或任务。",
            status=(
                HypothesisStatus.SUPPORTED if trace_codes else HypothesisStatus.REJECTED
            ),
            supporting_issue_codes=trace_codes,
            unresolved_evidence_refs=["offline-vision-run-receipt"],
            next_discriminating_test="用 ResultId、JobId、PartId 及权威批次来源重新关联。",
        ),
        IncidentHypothesis(
            hypothesis_id="H-PROCESS-DEVIATION",
            category="process_deviation",
            statement="异常可能与冻结工艺窗口外的设备或过程信号有关。",
            status=(
                HypothesisStatus.SUPPORTED
                if process_codes
                else HypothesisStatus.UNRESOLVED
            ),
            supporting_issue_codes=process_codes,
            contradicting_issue_codes=process_contradiction_codes,
            unresolved_evidence_refs=["process-owner-attestation"],
            next_discriminating_test="由工艺责任人复核异常时间窗内的信号趋势和变更记录。",
        ),
        IncidentHypothesis(
            hypothesis_id="H-VISION-DRIFT",
            category="vision_configuration_drift",
            statement="异常可能由视觉配方、算法图、相机、光源或标定版本漂移引起。",
            status=(
                HypothesisStatus.SUPPORTED
                if vision_codes
                else HypothesisStatus.UNRESOLVED
            ),
            supporting_issue_codes=vision_codes,
            unresolved_evidence_refs=["vision-solution-manifest"],
            next_discriminating_test="对比批准基线并在不改源数据的派生版本上执行同合同复验。",
        ),
        IncidentHypothesis(
            hypothesis_id="H-VISUAL-DATA-QUALITY",
            category="visual_data_quality",
            statement="异常可能来自图像、标注、覆盖或metadata证据问题。",
            status=(
                HypothesisStatus.SUPPORTED
                if data_codes or recovery_codes
                else HypothesisStatus.REJECTED
            ),
            supporting_issue_codes=data_codes + recovery_codes,
            unresolved_evidence_refs=["gate-evidence-package"],
            next_discriminating_test="执行已批准 CAPA 并比较父/子 Run 的原子 finding。",
        ),
        IncidentHypothesis(
            hypothesis_id="H-TRUE-PRODUCT-DEFECT",
            category="true_product_defect",
            statement="排除证据、关联、工艺和视觉方案问题后，才可继续评估真实产品缺陷。",
            status=(
                HypothesisStatus.PLAUSIBLE
                if not blocking_codes and not process_codes and not vision_codes
                else HypothesisStatus.UNRESOLVED
            ),
            supporting_issue_codes=[],
            unresolved_evidence_refs=["physical-sample-review"],
            next_discriminating_test="由具名质量责任人按企业抽检规范复核实物与独立样本。",
        ),
    ]


def _build_incident_evidence_edges(
    hypotheses: list[IncidentHypothesis],
    issues: list[IncidentEvidenceIssue],
) -> list[IncidentEvidenceEdge]:
    issue_by_code = {item.issue_code: item for item in issues}
    edges: list[IncidentEvidenceEdge] = []
    for hypothesis in hypotheses:
        for code in hypothesis.supporting_issue_codes:
            issue = issue_by_code.get(code)
            if issue is None:
                continue
            stable = {
                "hypothesis": hypothesis.hypothesis_id,
                "relation": "SUPPORTS",
                "issue": code,
                "source": issue.evidence_source,
            }
            edges.append(
                IncidentEvidenceEdge(
                    edge_id="edge_" + _sha256(stable)[:16],
                    hypothesis_id=hypothesis.hypothesis_id,
                    relation="SUPPORTS",
                    issue_code=code,
                    evidence_ref=issue.evidence_source,
                    qualification=(
                        EvidenceQualification.NOT_QUALIFIED
                        if issue.blocks_disposition
                        else EvidenceQualification.QUALIFIED_WITH_WARNING
                    ),
                    producer_receipt_sha256=issue.producer_receipt_sha256,
                )
            )
        for code in hypothesis.contradicting_issue_codes:
            issue = issue_by_code.get(code)
            if issue is None:
                continue
            stable = {
                "hypothesis": hypothesis.hypothesis_id,
                "relation": "CONTRADICTS",
                "issue": code,
                "source": issue.evidence_source,
            }
            edges.append(
                IncidentEvidenceEdge(
                    edge_id="edge_" + _sha256(stable)[:16],
                    hypothesis_id=hypothesis.hypothesis_id,
                    relation="CONTRADICTS",
                    issue_code=code,
                    evidence_ref=issue.evidence_source,
                    qualification=EvidenceQualification.QUALIFIED_WITH_WARNING,
                    producer_receipt_sha256=issue.producer_receipt_sha256,
                )
            )
        if not hypothesis.supporting_issue_codes and hypothesis.status in {
            HypothesisStatus.UNRESOLVED,
            HypothesisStatus.PLAUSIBLE,
        }:
            evidence_ref = hypothesis.unresolved_evidence_refs[0]
            stable = {
                "hypothesis": hypothesis.hypothesis_id,
                "relation": "UNRESOLVED",
                "source": evidence_ref,
            }
            edges.append(
                IncidentEvidenceEdge(
                    edge_id="edge_" + _sha256(stable)[:16],
                    hypothesis_id=hypothesis.hypothesis_id,
                    relation="UNRESOLVED",
                    evidence_ref=evidence_ref,
                    qualification=EvidenceQualification.QUALIFIED_WITH_WARNING,
                )
            )
    return edges


def _build_worker_candidate(
    *,
    worker_role: str,
    reason_codes: list[str],
    candidate_issues: list[IncidentEvidenceIssue],
    candidate_hypotheses: list[IncidentHypothesis],
) -> WorkerCandidate:
    """Project measured planning facts into the frozen Worker selector contract."""

    normalized_codes = sorted(set(reason_codes))
    reason_code_set = set(normalized_codes)
    relevant_issues = [
        item for item in candidate_issues if item.issue_code in reason_code_set
    ]
    relevant_hypotheses = [
        item
        for item in candidate_hypotheses
        if reason_code_set
        & set(item.supporting_issue_codes + item.contradicting_issue_codes)
    ]
    if any(item.blocks_disposition for item in relevant_issues):
        severity = BlockingSeverity.BLOCKING
    elif normalized_codes:
        severity = BlockingSeverity.WARNING
    else:
        severity = BlockingSeverity.NONE
    return WorkerCandidate(
        worker_id=worker_role,
        eligible=bool(normalized_codes),
        ineligibility_reasons=([] if normalized_codes else ["NO_TRIGGER_EVIDENCE"]),
        blocking_severity=severity,
        discriminated_hypothesis_ids=[
            item.hypothesis_id for item in relevant_hypotheses
        ],
        unresolved_evidence_refs=sorted(
            {
                evidence_ref
                for item in relevant_hypotheses
                for evidence_ref in item.unresolved_evidence_refs
            }
        ),
        # No production cost telemetry is bound to this Case yet.  UNKNOWN is
        # deliberate; claiming LOW/MEDIUM/HIGH without a receipt would invent data.
        measured_cost_bucket=MeasuredCostBucket.UNKNOWN,
    )


def _issue(
    code: str,
    *,
    severity: Literal["BLOCKING", "WARNING"],
    source: str,
    summary: str,
    action: str,
    worker: str,
) -> IncidentEvidenceIssue:
    return IncidentEvidenceIssue(
        issue_code=code,
        severity=severity,
        evidence_source=source,
        summary=summary,
        required_evidence_or_action=action,
        worker_role=worker,
        blocks_disposition=severity == "BLOCKING",
    )


def _add_correlation_issue(
    issues: list[IncidentEvidenceIssue],
    field_name: str,
    values: dict[str, str | None],
) -> None:
    present = {key: value for key, value in values.items() if value is not None}
    if len(set(present.values())) <= 1:
        return
    issues.append(
        _issue(
            f"CORRELATION_{field_name.upper()}_MISMATCH",
            severity="BLOCKING",
            source="cross-source-correlation",
            summary=f"{field_name} 在触发、OPC、方案或离线运行回执之间不一致。",
            action="由权威条码、工单或结果标识重新绑定同一工件与视觉运行。",
            worker="TraceabilityAgent",
        )
    )


def build_industrial_incident_case(
    request: IndustrialIncidentRequest,
    gate_context: IndustrialGateContext,
    *,
    parent_case: IndustrialIncidentCase | None = None,
    authorizing_decision: IndustrialIncidentDecisionReceipt | None = None,
    model_planner: IncidentModelPlanner | None = None,
    governed_memory: GovernedMemoryPlanningInput | None = None,
    worker_registry: IncidentWorkerRegistry | None = None,
) -> IndustrialIncidentCase:
    """Run one bounded, fail-closed evidence Agent iteration.

    A resume never mutates history.  It supplies refreshed evidence in a new
    request whose ``supersedes_case_id`` must bind the prior immutable case.
    """

    if parent_case is None and (
        request.supersedes_case_id is not None or authorizing_decision is not None
    ):
        raise ValueError("resume controls require the bound parent case")
    resolved_worker_registry = worker_registry or DEFAULT_INCIDENT_WORKER_REGISTRY
    if request.batch_trace_record is not None:
        verify_batch_trace_record(request.batch_trace_record)
    for production_change in request.production_change_records:
        verify_production_change_record(production_change)
    evidence_bundle_sha256 = industrial_incident_evidence_bundle_sha256(request)
    if parent_case is not None:
        verify_industrial_incident_case(parent_case)
        if request.supersedes_case_id != parent_case.case_id:
            raise ValueError("incident resume does not bind the supplied parent case")
        if not hmac.compare_digest(
            request.expected_parent_case_sha256 or "", parent_case.case_sha256
        ):
            raise ValueError("incident resume failed parent case SHA-256 binding")
        if authorizing_decision is None:
            raise ValueError("incident resume requires an authorizing human decision")
        verify_industrial_incident_decision_receipt(
            authorizing_decision, case=parent_case
        )
        if request.authorizing_decision_id != authorizing_decision.decision_id:
            raise ValueError("incident resume failed authorizing decision binding")
        allowed_resume_decisions = {
            IncidentHumanDecision.CONTINUE_HOLD,
            IncidentHumanDecision.ESCALATE_INVESTIGATION,
            IncidentHumanDecision.SELECT_REMEDIATION_PLAN,
            IncidentHumanDecision.REQUEST_REVERIFICATION,
        }
        if authorizing_decision.decision not in allowed_resume_decisions:
            raise ValueError("human decision does not authorize an incident resume")
        if parent_case.task_id != gate_context.task_id:
            raise ValueError("incident parent and gate context task do not match")
        if not parent_case.loop_control.can_resume:
            raise ValueError("incident parent reached a non-resumable stop condition")
        if (
            request.max_agent_iterations != parent_case.request.max_agent_iterations
            or request.max_dynamic_workers != parent_case.request.max_dynamic_workers
        ):
            raise ValueError(
                "incident resume cannot expand or replace frozen loop budgets"
            )
        observed_evidence_sha256 = _industrial_incident_observed_evidence_sha256(
            request
        )
        previous_observed_evidence_sha256 = (
            _industrial_incident_observed_evidence_sha256(parent_case.request)
        )
        if hmac.compare_digest(
            observed_evidence_sha256,
            previous_observed_evidence_sha256,
        ):
            raise ValueError("NO_NEW_EVIDENCE: incident resume evidence is unchanged")
        identity_fields = (
            "trigger_kind",
            "product_id",
            "part_id",
            "batch_id",
            "lot_reference",
            "work_order_id",
            "line_id",
        )
        parent_identity = tuple(
            getattr(parent_case.request.trigger, field) for field in identity_fields
        )
        child_identity = tuple(
            getattr(request.trigger, field) for field in identity_fields
        )
        if child_identity != parent_identity:
            raise ValueError(
                "incident resume changed the frozen event identity; create a new root case"
            )
        if (
            authorizing_decision.decision
            is IncidentHumanDecision.SELECT_REMEDIATION_PLAN
        ):
            capa = gate_context.capa_evidence
            if (
                capa is None
                or capa.capa_case_id != authorizing_decision.linked_capa_case_id
            ):
                raise ValueError("incident resume failed exact CAPA decision binding")
            if (
                capa.remediation_plan_id
                != authorizing_decision.selected_remediation_plan_id
            ):
                raise ValueError(
                    "incident resume CAPA plan differs from the human decision"
                )
        elif gate_context.capa_evidence is not None:
            raise ValueError("CAPA evidence requires a plan-selection decision")

    snapshot_sha256 = _sha256(request.opcua_snapshot)
    solution_sha256 = _sha256(request.vision_solution)
    offline_run_sha256 = _sha256(request.offline_run)
    batch_trace_sha256 = (
        _sha256(request.batch_trace_record)
        if request.batch_trace_record is not None
        else None
    )
    production_change_sha256s = [
        _sha256(item) for item in request.production_change_records
    ]
    context_sha256 = _sha256(gate_context)
    planning_subject_sha256 = industrial_incident_planning_subject_sha256(
        request,
        gate_context,
        authorizing_decision=authorizing_decision,
    )
    case_id = f"incident_{planning_subject_sha256[:20]}"
    case_version = 1 if parent_case is None else parent_case.case_version + 1
    parent_belief_revision_receipt: EvidenceBeliefRevisionReceiptV1 | None = None
    if parent_case is not None:
        parent_ledger = parent_case.planning_belief_ledger
        if parent_ledger is None:
            raise ValueError(
                "incident resume requires a v5+ parent belief ledger; "
                "historical pre-v5 Cases remain readable but cannot enter the v6 loop"
            )
        parent_belief_revision_receipt = build_evidence_belief_revision_receipt_v1(
            parent_case_id=parent_case.case_id,
            parent_case_sha256=parent_case.case_sha256,
            source_ledger=parent_ledger,
            observed_authorization_event_sha256=(
                gate_context.source_authorization_event_sha256
            ),
            observed_authorization_status=(gate_context.source_authorization_status),
            observed_evidence_bundle_sha256=evidence_bundle_sha256,
        )
        verify_evidence_belief_revision_receipt_v1(parent_belief_revision_receipt)

    if governed_memory is not None:
        from .governed_context import verify_governed_memory_planning_input

        verify_governed_memory_planning_input(governed_memory)
        if not hmac.compare_digest(
            governed_memory.planning_subject_sha256,
            planning_subject_sha256,
        ):
            raise ValueError("governed memory does not bind this planning subject")
        if governed_memory.query_scope.line_id != request.trigger.line_id:
            raise ValueError("governed memory query does not bind this incident line")

    trigger = request.trigger
    snapshot = request.opcua_snapshot
    opc_context = snapshot.machine_vision_context
    solution = request.vision_solution
    run = request.offline_run
    batch_trace = request.batch_trace_record
    production_changes = request.production_change_records
    issues: list[IncidentEvidenceIssue] = []

    if solution.source_profile != run.source_profile:
        issues.append(
            _issue(
                "SOURCE_PROFILE_MISMATCH",
                severity="BLOCKING",
                source="vision-solution-and-offline-run",
                summary="视觉方案与离线运行回执声明的导出来源档案不一致。",
                action="使用同一导出合同重新生成方案 Manifest 与运行回执。",
                worker="VisionRecipeAgent",
            )
        )
    if trigger.sample_count != run.input_count:
        issues.append(
            _issue(
                "INCIDENT_SAMPLE_COUNT_MISMATCH",
                severity="BLOCKING",
                source="incident-trigger-and-offline-run",
                summary="异常触发样本数与离线运行输入数不一致。",
                action="核对同一 ResultId/JobId 的统计口径并重建触发回执。",
                worker="TraceabilityAgent",
            )
        )
    observed_run_ng_rate = run.ng_count / run.input_count
    if trigger.observed_ng_rate is not None and abs(
        trigger.observed_ng_rate - observed_run_ng_rate
    ) > max(1.0 / run.input_count, 1e-9):
        issues.append(
            _issue(
                "INCIDENT_NG_RATE_MISMATCH",
                severity="BLOCKING",
                source="incident-trigger-and-offline-run",
                summary="异常触发 NG 率与离线运行计数无法相互复算。",
                action="按同一输入数和 NG 计数重新计算并绑定统计回执。",
                worker="TraceabilityAgent",
            )
        )
    snapshot_age = (trigger.triggered_at - snapshot.captured_at).total_seconds()
    if snapshot_age > request.max_signal_age_seconds or snapshot_age < (
        -request.max_clock_skew_seconds
    ):
        issues.append(
            _issue(
                "SNAPSHOT_TIME_WINDOW_MISMATCH",
                severity="BLOCKING",
                source="opcua-snapshot",
                summary="OPC UA 快照采集时间不在冻结异常窗口内。",
                action="在同一异常窗口重新导出只读快照并核验时钟同步。",
                worker="SignalIntegrityAgent",
            )
        )

    if not hmac.compare_digest(run.solution_manifest_sha256, solution_sha256):
        issues.append(
            _issue(
                "OFFLINE_RUN_MANIFEST_HASH_MISMATCH",
                severity="BLOCKING",
                source="offline-vision-run",
                summary="离线运行回执未绑定当前视觉方案 Manifest。",
                action="重新导出同一方案版本的 Manifest 与运行回执并核对 SHA-256。",
                worker="VisionRecipeAgent",
            )
        )

    correlations: dict[str, dict[str, str | None]] = {
        "product_id": {
            "trigger": trigger.product_id,
            "opc": opc_context.product_id,
            "solution": solution.product_id,
            "run": run.product_id,
        },
        "part_id": {
            "trigger": trigger.part_id,
            "opc": opc_context.part_id,
            "run": run.part_id,
        },
        "recipe_id": {
            "trigger": trigger.recipe_id,
            "opc": opc_context.recipe_id,
            "solution": solution.recipe_id,
            "run": run.recipe_id,
        },
        "configuration_id": {
            "trigger": trigger.configuration_id,
            "opc": opc_context.configuration_id,
            "solution": solution.configuration_id,
            "run": run.configuration_id,
        },
        "job_id": {"opc": opc_context.job_id, "run": run.job_id},
        "result_id": {"opc": opc_context.result_id, "run": run.result_id},
        "batch_id": {
            "trigger": trigger.batch_id,
            "run": run.batch_id,
        },
        "lot_reference": {
            "trigger": trigger.lot_reference,
            "opc_extension": opc_context.lot_reference,
            "run": run.lot_reference,
        },
        "work_order_id": {
            "trigger": trigger.work_order_id,
            "run": run.work_order_id,
        },
        "line_id": {"trigger": trigger.line_id, "run": run.line_id},
    }
    for field_name, values in correlations.items():
        _add_correlation_issue(issues, field_name, values)

    qualified_process_change_ids: list[str] = []
    qualified_vision_change_ids: list[str] = []
    manufacturing_time_mismatches: list[str] = []
    batch_identity_conflicts: set[str] = set()
    unbound_change_records: list[str] = []

    if batch_trace is None:
        issues.append(
            _issue(
                "BATCH_TRACE_RECORD_MISSING",
                severity="BLOCKING",
                source="manufacturing-context",
                summary="缺少独立 MES、条码或工单批次追溯记录。",
                action="补充带来源授权、生产时间窗和记录摘要的批次追溯回执。",
                worker="ManufacturingContextAgent",
            )
        )
    else:
        if (
            batch_trace.authority_status
            is not ManufacturingRecordAuthorityStatus.VERIFIED
            or batch_trace.source_authorization_sha256 is None
        ):
            issues.append(
                _issue(
                    "BATCH_RECORD_NOT_AUTHORITY_BOUND",
                    severity="BLOCKING",
                    source=f"batch-trace:{batch_trace.record_id}",
                    summary="批次记录未绑定当前有效的 MES、条码或工单来源授权。",
                    action="取得权威系统导出和授权摘要后重新生成批次追溯记录。",
                    worker="ManufacturingContextAgent",
                )
            )

        current_identity = {
            "product_id": trigger.product_id,
            "part_id": trigger.part_id,
            "recipe_id": trigger.recipe_id,
            "configuration_id": trigger.configuration_id,
            "batch_id": trigger.batch_id,
            "lot_reference": trigger.lot_reference,
            "line_id": trigger.line_id,
        }
        batch_identity = {
            "product_id": batch_trace.product_id,
            "part_id": batch_trace.part_id,
            "recipe_id": batch_trace.recipe_id,
            "configuration_id": batch_trace.configuration_id,
            "batch_id": batch_trace.batch_id,
            "lot_reference": batch_trace.lot_reference,
            "line_id": batch_trace.line_id,
        }
        for field_name, batch_value in batch_identity.items():
            current_value = current_identity[field_name]
            if current_value is None or current_value != batch_value:
                batch_identity_conflicts.add(field_name)

        if (
            run.batch_id is None
            or run.lot_reference is None
            or run.batch_id != batch_trace.batch_id
            or run.lot_reference != batch_trace.lot_reference
        ):
            issues.append(
                _issue(
                    "QUALITY_RESULT_BATCH_MISMATCH",
                    severity="BLOCKING",
                    source="quality-result-and-batch-trace",
                    summary="质检运行回执缺少批次绑定，或与权威批次/批号不一致。",
                    action="按同一 ResultId、批次和工单重新导出质检结果回执。",
                    worker="ManufacturingContextAgent",
                )
            )

        window_skew = timedelta(seconds=request.max_production_record_skew_seconds)
        if (
            run.started_at < batch_trace.production_window_start - window_skew
            or run.completed_at > batch_trace.production_window_end + window_skew
            or trigger.triggered_at < batch_trace.production_window_start - window_skew
            or trigger.triggered_at > batch_trace.production_window_end + window_skew
        ):
            manufacturing_time_mismatches.append(batch_trace.record_id)

    if not production_changes:
        issues.append(
            _issue(
                "PRODUCTION_CHANGE_RECORD_MISSING",
                severity="BLOCKING",
                source="manufacturing-context",
                summary="缺少换型、配方、视觉方案或工艺设定的生产变更记录。",
                action="从 MES、工单变更日志或批准的离线导出补充变更回执。",
                worker="ManufacturingContextAgent",
            )
        )

    for change in production_changes:
        authority_bound = (
            change.authority_status is ManufacturingRecordAuthorityStatus.VERIFIED
            and change.source_authorization_sha256 is not None
            and change.change_status == "APPROVED_EFFECTIVE"
        )
        if not authority_bound:
            unbound_change_records.append(change.record_id)

        change_time_qualified = True
        if batch_trace is not None:
            earliest_effective = batch_trace.production_window_start - timedelta(
                seconds=request.max_change_lookback_seconds
            )
            latest_effective = trigger.triggered_at + timedelta(
                seconds=request.max_production_record_skew_seconds
            )
            if not earliest_effective <= change.effective_at <= latest_effective:
                manufacturing_time_mismatches.append(change.record_id)
                change_time_qualified = False
            if change.batch_id != batch_trace.batch_id:
                batch_identity_conflicts.add("change.batch_id")
            if change.lot_reference != batch_trace.lot_reference:
                batch_identity_conflicts.add("change.lot_reference")
            if change.line_id != batch_trace.line_id:
                batch_identity_conflicts.add("change.line_id")

        expected_new_values = {
            "new_product_id": trigger.product_id,
            "new_recipe_id": trigger.recipe_id,
            "new_configuration_id": trigger.configuration_id,
        }
        for field_name, expected in expected_new_values.items():
            actual = getattr(change, field_name)
            if actual is not None and actual != expected:
                batch_identity_conflicts.add(f"change.{field_name}")

        if authority_bound and change_time_qualified:
            if change.change_kind in {
                ProductionChangeKind.PRODUCT_CHANGEOVER,
                ProductionChangeKind.RECIPE_CHANGE,
                ProductionChangeKind.PROCESS_SETPOINT_CHANGE,
            }:
                qualified_process_change_ids.append(change.record_id)
            elif (
                change.change_kind is ProductionChangeKind.VISION_SOLUTION_UPGRADE
                and change.new_solution_manifest_sha256 == solution_sha256
            ):
                qualified_vision_change_ids.append(change.record_id)

    work_order_values = [trigger.work_order_id, run.work_order_id]
    if batch_trace is not None:
        work_order_values.append(batch_trace.work_order_id)
    work_order_values.extend(item.work_order_id for item in production_changes)
    if (
        batch_trace is None
        or not production_changes
        or any(value is None for value in work_order_values)
        or len({value for value in work_order_values if value is not None}) != 1
    ):
        issues.append(
            _issue(
                "WORK_ORDER_CORRELATION_MISSING",
                severity="BLOCKING",
                source="manufacturing-context",
                summary="质检结果、批次记录和生产变更记录未形成唯一工单关联。",
                action="补充并统一 WorkOrderId；不得仅凭时间接近推定同一生产任务。",
                worker="ManufacturingContextAgent",
            )
        )

    if batch_identity_conflicts:
        issues.append(
            _issue(
                "BATCH_IDENTITY_CONFLICT",
                severity="BLOCKING",
                source="manufacturing-context",
                summary=(
                    "权威批次记录与当前异常证据身份冲突："
                    + "、".join(sorted(batch_identity_conflicts))
                    + "。"
                ),
                action="按权威批次、工单和 ResultId 重新绑定四类证据。",
                worker="ManufacturingContextAgent",
            )
        )

    if manufacturing_time_mismatches:
        issues.append(
            _issue(
                "PRODUCTION_RECORD_TIME_WINDOW_MISMATCH",
                severity="BLOCKING",
                source="manufacturing-context",
                summary=(
                    "生产记录不在冻结异常/生产时间窗："
                    + "、".join(sorted(set(manufacturing_time_mismatches)))
                    + "。"
                ),
                action="核验产线时钟、生产窗口和变更生效时间后重新导出。",
                worker="ManufacturingContextAgent",
            )
        )

    if unbound_change_records:
        issues.append(
            _issue(
                "CHANGEOVER_RECORD_NOT_AUTHORITY_BOUND",
                severity="BLOCKING",
                source="manufacturing-context",
                summary=(
                    "生产变更记录未批准生效或未绑定有效来源授权："
                    + "、".join(sorted(unbound_change_records))
                    + "。"
                ),
                action="由具名生产责任人确认变更单，并绑定权威系统授权摘要。",
                worker="ManufacturingContextAgent",
            )
        )

    if opc_context.lot_reference is None:
        issues.append(
            _issue(
                "LOT_REFERENCE_NOT_AUTHORITY_BOUND",
                severity="WARNING",
                source="opcua-snapshot",
                summary="当前证据没有 MES、条码、工单或操作员权威批次绑定。",
                action="补充权威批次来源；ProductId 不得替代 BatchId。",
                worker="TraceabilityAgent",
            )
        )

    if gate_context.source_kind == "local_authorized_directory" and (
        gate_context.source_authorization_status != "ACTIVE"
    ):
        issues.append(
            _issue(
                "SOURCE_AUTHORIZATION_NOT_ACTIVE",
                severity="BLOCKING",
                source="visiondata-gate",
                summary="父任务的本地来源授权当前不是 ACTIVE，旧证据不能继续驱动处置。",
                action="由授权责任人恢复有效授权并生成新的授权事件回执。",
                worker="EvidenceQualificationAgent",
            )
        )
    elif gate_context.source_kind == "synthetic_demo":
        issues.append(
            _issue(
                "SYNTHETIC_SOURCE_SCOPE",
                severity="WARNING",
                source="visiondata-gate",
                summary="父任务使用合成演示来源，只能验证 Agent 产品闭环。",
                action="不得将此案件写成工厂现场验证或客户验收。",
                worker="EvidenceQualificationAgent",
            )
        )
    elif gate_context.source_kind == "external_residency_reference":
        issues.append(
            _issue(
                "EXTERNAL_SOURCE_AUTHORIZATION_UNVERIFIED",
                severity="BLOCKING",
                source="visiondata-gate",
                summary="外部驻留来源没有可由当前服务验签的授权与新鲜度回执。",
                action="取得可验证的授权事件、来源画像和当前有效性回执后重建案件。",
                worker="EvidenceQualificationAgent",
            )
        )

    for reference in request.knowledge_references:
        if reference.qualification is EvidenceQualification.NOT_QUALIFIED:
            issues.append(
                _issue(
                    "KNOWLEDGE_REFERENCE_NOT_QUALIFIED",
                    severity="BLOCKING",
                    source=f"knowledge:{reference.reference_id}",
                    summary="知识或规则引用未通过版本与摘要资格校验。",
                    action="绑定经授权的知识版本、内容 SHA-256 与适用范围后重试。",
                    worker="EvidenceQualificationAgent",
                )
            )

    if opc_context.result_state != "Completed" or run.execution_state != "Completed":
        issues.append(
            _issue(
                "VISION_RESULT_NOT_COMPLETED",
                severity="BLOCKING",
                source="opcua-and-offline-run",
                summary="视觉结果尚未完成、已中止或失败，不能作为最终复验证据。",
                action="取得 Completed 结果回执或转视觉运行失败调查。",
                worker="VisionRecipeAgent",
            )
        )
    if opc_context.is_partial or run.is_partial:
        issues.append(
            _issue(
                "VISION_RESULT_PARTIAL",
                severity="BLOCKING",
                source="opcua-and-offline-run",
                summary="视觉结果标记为部分结果，不能支持解除 HOLD。",
                action="等待完整结果并生成新的证据快照。",
                worker="SignalIntegrityAgent",
            )
        )
    if opc_context.is_simulated or run.is_simulated:
        issues.append(
            _issue(
                "SIMULATED_EVIDENCE_SCOPE",
                severity="WARNING",
                source="opcua-and-offline-run",
                summary="当前快照或视觉结果为仿真证据，只能验证产品闭环。",
                action="在授权现场另行获取真实只读证据后再作业务判断。",
                worker="EvidenceQualificationAgent",
            )
        )

    run_context_skew = abs(
        (run.completed_at - opc_context.creation_time).total_seconds()
    )
    if run_context_skew > request.max_cross_source_skew_seconds:
        issues.append(
            _issue(
                "VISION_RESULT_TIME_WINDOW_MISMATCH",
                severity="BLOCKING",
                source="cross-source-correlation",
                summary="OPC Result CreationTime 与离线运行完成时间超出冻结时间窗。",
                action="用 ResultId/JobId 精确重绑；只有时间近似不能解除 HOLD。",
                worker="TraceabilityAgent",
            )
        )

    observations = {item.semantic_alias: item for item in snapshot.observations}
    for expectation in request.process_signal_expectations:
        observation = observations.get(expectation.semantic_alias)
        if observation is None:
            if expectation.required:
                issues.append(
                    _issue(
                        "OPC_REQUIRED_SIGNAL_MISSING",
                        severity="BLOCKING",
                        source=f"opcua:{expectation.semantic_alias}",
                        summary=f"缺少必需过程信号 {expectation.semantic_alias}。",
                        action="从只读白名单重新导出该信号及质量码和双时间戳。",
                        worker="SignalIntegrityAgent",
                    )
                )
            continue
        if observation.severity is not OPCUAValueSeverity.GOOD:
            issues.append(
                _issue(
                    f"OPC_VALUE_{observation.severity.value.upper()}",
                    severity="BLOCKING",
                    source=f"opcua:{expectation.semantic_alias}",
                    summary=(
                        f"{expectation.semantic_alias} 的 StatusCode 严重度为 "
                        f"{observation.severity.value}，值不具备裁决资格。"
                    ),
                    action="修复信号质量后获取新快照；Bad/Uncertain 不得被当作可靠值。",
                    worker="SignalIntegrityAgent",
                )
            )
        if observation.source_timestamp is None:
            issues.append(
                _issue(
                    "OPC_SOURCE_TIMESTAMP_MISSING",
                    severity="BLOCKING",
                    source=f"opcua:{expectation.semantic_alias}",
                    summary="缺少 sourceTimestamp，无法证明信号属于本次异常时间窗。",
                    action="重新导出带 sourceTimestamp 的 DataValue。",
                    worker="SignalIntegrityAgent",
                )
            )
        else:
            signal_age = (
                trigger.triggered_at - observation.source_timestamp
            ).total_seconds()
            if signal_age > request.max_signal_age_seconds:
                issues.append(
                    _issue(
                        "OPC_SIGNAL_STALE",
                        severity="BLOCKING",
                        source=f"opcua:{expectation.semantic_alias}",
                        summary=f"{expectation.semantic_alias} 超出允许的新鲜度窗口。",
                        action="在异常窗口内重新取得只读快照。",
                        worker="SignalIntegrityAgent",
                    )
                )
            elif signal_age < -request.max_clock_skew_seconds:
                issues.append(
                    _issue(
                        "OPC_SIGNAL_FROM_FUTURE",
                        severity="BLOCKING",
                        source=f"opcua:{expectation.semantic_alias}",
                        summary=f"{expectation.semantic_alias} 的 sourceTimestamp 晚于异常触发窗口。",
                        action="核验采集时钟与事件时间后重新取得只读快照。",
                        worker="SignalIntegrityAgent",
                    )
                )
            clock_skew = abs(
                (
                    observation.server_timestamp - observation.source_timestamp
                ).total_seconds()
            )
            if clock_skew > request.max_clock_skew_seconds:
                issues.append(
                    _issue(
                        "OPC_CLOCK_SKEW",
                        severity="BLOCKING",
                        source=f"opcua:{expectation.semantic_alias}",
                        summary=f"{expectation.semantic_alias} 的 source/server 时间差超限。",
                        action="核验时钟同步和采集链路后生成新快照。",
                        worker="SignalIntegrityAgent",
                    )
                )
        if observation.semantics_changed:
            issues.append(
                _issue(
                    "OPC_SEMANTICS_CHANGED",
                    severity="BLOCKING",
                    source=f"opcua:{expectation.semantic_alias}",
                    summary=f"{expectation.semantic_alias} 的工程语义或属性已变化。",
                    action="重读工程单位、范围与属性后更新白名单合同。",
                    worker="SignalIntegrityAgent",
                )
            )
        if observation.engineering_unit != expectation.engineering_unit:
            issues.append(
                _issue(
                    "OPC_ENGINEERING_UNIT_MISMATCH",
                    severity="BLOCKING",
                    source=f"opcua:{expectation.semantic_alias}",
                    summary=(
                        f"{expectation.semantic_alias} 的工程单位与冻结规则不一致。"
                    ),
                    action="核对单位换算或重读节点工程单位，禁止静默换算。",
                    worker="SignalIntegrityAgent",
                )
            )
        numeric_value = observation.value
        if isinstance(numeric_value, bool) or not isinstance(
            numeric_value, (int, float)
        ):
            issues.append(
                _issue(
                    "OPC_NUMERIC_SIGNAL_TYPE_MISMATCH",
                    severity="BLOCKING",
                    source=f"opcua:{expectation.semantic_alias}",
                    summary=f"{expectation.semantic_alias} 不是可比较的数值。",
                    action="重新读取与规则声明的数据类型一致的值。",
                    worker="SignalIntegrityAgent",
                )
            )
        elif (
            expectation.minimum is not None and numeric_value < expectation.minimum
        ) or (expectation.maximum is not None and numeric_value > expectation.maximum):
            issues.append(
                _issue(
                    "PROCESS_SIGNAL_OUT_OF_RANGE",
                    severity="WARNING",
                    source=f"opcua:{expectation.semantic_alias}",
                    summary=f"{expectation.semantic_alias} 超出冻结工艺窗口。",
                    action="由设备/工艺责任人核验变化原因，Agent 不自动调整设备。",
                    worker="ProcessContextAgent",
                )
            )

    if (
        request.baseline_solution_manifest_sha256 is not None
        and not hmac.compare_digest(
            request.baseline_solution_manifest_sha256, solution_sha256
        )
    ):
        issues.append(
            _issue(
                "VISION_SOLUTION_MANIFEST_DRIFT",
                severity="WARNING",
                source="vision-solution-manifest",
                summary="当前视觉方案 Manifest 与批准基线不同。",
                action="核对算法图、模型、相机、光源、标定和规则差异并重新复验。",
                worker="VisionRecipeAgent",
            )
        )

    process_signal_out_of_range = any(
        item.issue_code == "PROCESS_SIGNAL_OUT_OF_RANGE" for item in issues
    )
    process_signal_unqualified = any(
        item.blocks_disposition
        and (
            item.issue_code.startswith("OPC_")
            or item.issue_code == "SNAPSHOT_TIME_WINDOW_MISMATCH"
        )
        for item in issues
    )
    if qualified_process_change_ids and process_signal_out_of_range:
        issues.append(
            _issue(
                "PRODUCTION_CHANGE_SUPPORTS_PROCESS_HYPOTHESIS",
                severity="WARNING",
                source="production-change-records",
                summary=(
                    "已批准生产变更与越界过程信号处于同一冻结窗口，"
                    "仅支持继续检验工艺解释，不能据此认定根因。"
                ),
                action="由工艺责任人复核变更差异、趋势和独立样本，保留竞争性解释。",
                worker="ManufacturingContextAgent",
            )
        )
    elif (
        qualified_process_change_ids
        and request.process_signal_expectations
        and not process_signal_unqualified
    ):
        issues.append(
            _issue(
                "PRODUCTION_CHANGE_CONTRADICTS_PROCESS_HYPOTHESIS",
                severity="WARNING",
                source="production-change-records",
                summary=(
                    "已批准生产变更存在，但本次冻结过程信号仍在规则窗口内；"
                    "该证据反驳而非排除工艺解释。"
                ),
                action="继续保留视觉方案、数据质量和真实缺陷假设，并由责任人复核。",
                worker="ManufacturingContextAgent",
            )
        )

    if qualified_vision_change_ids and any(
        item.issue_code == "VISION_SOLUTION_MANIFEST_DRIFT" for item in issues
    ):
        issues.append(
            _issue(
                "PRODUCTION_CHANGE_SUPPORTS_VISION_HYPOTHESIS",
                severity="WARNING",
                source="production-change-records",
                summary=(
                    "批准的视觉方案升级记录与当前 Manifest 一致；"
                    "仅支持执行同合同复验，不能直接认定视觉方案为根因。"
                ),
                action="对升级前后方案执行同数据、同规则的独立 child Run。",
                worker="ManufacturingContextAgent",
            )
        )

    if gate_context.gate_final_decision.upper() != "PASS":
        issues.append(
            _issue(
                "GATE_DECISION_NOT_PASS",
                severity="WARNING",
                source="visiondata-gate",
                summary=(
                    "现有视觉数据证据门禁为 "
                    f"{gate_context.gate_final_decision}，仍需整改或调查。"
                ),
                action="选择最小整改方案，经人工批准后创建派生版本并执行 child Run。",
                worker="VisualDataQualityAgent",
            )
        )

    if gate_context.capa_evidence is not None and (
        gate_context.capa_evidence.recovery_status
        in {"STILL_BLOCKED", "TRANSFERRED_TO_INVESTIGATION"}
    ):
        issues.append(
            _issue(
                "CHILD_RUN_RECOVERY_NOT_OBSERVED",
                severity="WARNING",
                source="visiondata-gate-capa",
                summary="既有 child Run 未观察到可恢复候选，案件仍处于调查状态。",
                action="保留 HOLD；扩大授权候选池、物理重采或完成人工根因调查。",
                worker="VisualDataQualityAgent",
            )
        )

    candidate_issues = issues
    candidate_hypotheses = _build_incident_hypotheses(candidate_issues)
    candidate_evidence_edges = _build_incident_evidence_edges(
        candidate_hypotheses,
        candidate_issues,
    )
    planning_belief_ledger = build_case_evidence_belief_ledger_v2(
        case_id=case_id,
        evidence_bundle_sha256=evidence_bundle_sha256,
        hypotheses=candidate_hypotheses,
        evidence_edges=candidate_evidence_edges,
        source_authorization_event_sha256=(
            gate_context.source_authorization_event_sha256
        ),
        source_authorization_status=gate_context.source_authorization_status,
    )
    verify_evidence_belief_ledger_v2(planning_belief_ledger)
    candidate_codes_by_role: dict[str, list[str]] = {}
    for item in candidate_issues:
        candidate_codes_by_role.setdefault(item.worker_role, []).append(item.issue_code)

    actions = [
        IncidentAgentAction(
            sequence=1,
            iteration=case_version,
            agent_role="IncidentCoordinatorAgent",
            action="冻结异常目标、身份关联和安全边界",
            status="COMPLETED",
            dynamic=False,
            reason_codes=[request.trigger.trigger_kind.value],
            input_refs=["incident-request", "gate-context"],
            expected_output="证据资格与动态补证计划",
            tool_contracts=["incident-contract-validator"],
        )
    ]
    dynamic_specs = [
        (
            candidate_codes_by_role.get("EvidenceQualificationAgent", []),
            "EvidenceQualificationAgent",
            "复核来源授权、证据资格与可声明边界",
            "来源资格与声明边界回执",
            ["source-authorization-validator"],
        ),
        (
            candidate_codes_by_role.get("ManufacturingContextAgent", [])
            or ["MULTISOURCE_MANUFACTURING_CONTEXT_REVIEW"],
            "ManufacturingContextAgent",
            "关联质检、批次、工单、生产变更与冻结时间窗",
            "四源身份、授权、时间窗与假设证据回执",
            ["manufacturing-context-correlation-check"],
        ),
        (
            candidate_codes_by_role.get("SignalIntegrityAgent", []),
            "SignalIntegrityAgent",
            "补验 OPC 质量码、语义、单位和时间戳",
            "新的只读 OPC UA 离线快照",
            ["opcua-offline-snapshot-validator"],
        ),
        (
            candidate_codes_by_role.get("TraceabilityAgent", []),
            "TraceabilityAgent",
            "重新关联产品、工件、任务、结果和权威批次",
            "具备唯一关联键的追溯回执",
            ["machine-vision-correlation-check"],
        ),
        (
            candidate_codes_by_role.get("ProcessContextAgent", []),
            "ProcessContextAgent",
            "核验冻结工艺窗口外的过程信号",
            "设备/工艺责任人调查请求",
            ["process-window-check"],
        ),
        (
            candidate_codes_by_role.get("VisionRecipeAgent", []),
            "VisionRecipeAgent",
            "核对视觉配方、配置与离线运行沿袭",
            "方案差异和复验要求",
            ["vision-solution-lineage-check"],
        ),
        (
            candidate_codes_by_role.get("VisualDataQualityAgent", []),
            "VisualDataQualityAgent",
            "复用 Gate finding 与整改方案形成最小 CAPA 入口",
            "人工可选的证据绑定整改方案",
            ["industrial-delivery", "capa-plan-selector"],
        ),
    ]
    prior_dynamic_workers_executed = (
        0 if parent_case is None else parent_case.loop_control.dynamic_workers_executed
    )
    dynamic_worker_budget = max(
        request.max_dynamic_workers - prior_dynamic_workers_executed, 0
    )
    active_categories = sum(bool(codes) for codes, *_ in dynamic_specs)
    counterevidence_reason_codes = (
        sorted({item.issue_code for item in candidate_issues})
        if active_categories >= 2
        else []
    )
    worker_candidates = [
        _build_worker_candidate(
            worker_role=role,
            reason_codes=list(codes),
            candidate_issues=candidate_issues,
            candidate_hypotheses=candidate_hypotheses,
        )
        for codes, role, *_ in dynamic_specs
    ]
    worker_candidates.append(
        WorkerCandidate(
            worker_id="CounterevidenceAuditorAgent",
            eligible=bool(counterevidence_reason_codes),
            ineligibility_reasons=(
                []
                if counterevidence_reason_codes
                else ["MULTI_HYPOTHESIS_CONFLICT_NOT_OBSERVED"]
            ),
            # This Worker audits competing explanations but does not acquire a
            # new discriminating measurement.  It therefore cannot outrank a
            # blocking evidence-acquisition Worker by invented information gain.
            blocking_severity=(
                BlockingSeverity.WARNING
                if counterevidence_reason_codes
                else BlockingSeverity.NONE
            ),
            discriminated_hypothesis_ids=[],
            unresolved_evidence_refs=[],
            measured_cost_bucket=MeasuredCostBucket.UNKNOWN,
        )
    )
    worker_selection_receipt = build_worker_selection_receipt(
        worker_candidates,
        worker_budget=dynamic_worker_budget,
    )
    verify_worker_selection_receipt(worker_selection_receipt)
    selected_worker_ids = set(worker_selection_receipt.selected_worker_ids)
    dynamic_workers_executed = 0
    worker_receipts: list[IncidentWorkerReceipt] = []
    failed_worker_receipts: list[IncidentWorkerReceipt] = []
    evaluated_issues: list[IncidentEvidenceIssue] = []
    stopped_roles: list[str] = []
    model_planner_receipt: IncidentModelPlannerReceipt | None = None
    worker_input_hashes = [
        snapshot_sha256,
        solution_sha256,
        offline_run_sha256,
        context_sha256,
        evidence_bundle_sha256,
    ]
    if batch_trace_sha256 is not None:
        worker_input_hashes.append(batch_trace_sha256)
    worker_input_hashes.extend(production_change_sha256s)

    active_worker_reason_codes = {
        role: list(codes)
        for codes, role, *_ in dynamic_specs
        if codes and role in selected_worker_ids
    }
    planner_governed_memory: dict[str, object] | None = None
    if governed_memory is not None:
        from .governed_context import governed_memory_planner_payload

        planner_governed_memory = governed_memory_planner_payload(governed_memory)
    if (
        model_planner is not None
        and dynamic_worker_budget > 0
        and active_worker_reason_codes
    ):
        available_receipt_ids = [
            "opcua-offline-snapshot",
            "vision-solution-manifest",
            "offline-vision-run-receipt",
            f"task:{gate_context.task_id}:evidence",
            f"task:{gate_context.task_id}:industrial-delivery",
            f"task:{gate_context.task_id}:source-authorization",
        ]
        if batch_trace is not None:
            available_receipt_ids.append(f"batch-trace:{batch_trace.record_id}")
        available_receipt_ids.extend(
            f"production-change:{item.record_id}" for item in production_changes
        )
        if governed_memory is not None:
            available_receipt_ids.append(
                "governed-memory-retrieval:"
                + governed_memory.retrieval_receipt.receipt_sha256
            )
        allowed_missing_evidence_ids = sorted(
            {
                evidence_ref
                for hypothesis in candidate_hypotheses
                for evidence_ref in hypothesis.unresolved_evidence_refs
            }
        )
        model_plan = model_planner.plan(
            case_id=case_id,
            evidence_bundle_sha256=evidence_bundle_sha256,
            trigger_kind=request.trigger.trigger_kind.value,
            candidate_issues=[
                {
                    "issue_code": item.issue_code,
                    "severity": item.severity,
                    "evidence_source": item.evidence_source,
                    "summary": item.summary,
                    "worker_role": item.worker_role,
                }
                for item in candidate_issues
            ],
            candidate_hypotheses=[
                {
                    "hypothesis_id": item.hypothesis_id,
                    "status": item.status.value,
                    "statement": item.statement,
                    "unresolved_evidence_refs": item.unresolved_evidence_refs,
                    "next_discriminating_test": item.next_discriminating_test,
                }
                for item in candidate_hypotheses
            ],
            available_receipt_ids=available_receipt_ids,
            allowed_missing_evidence_ids=allowed_missing_evidence_ids,
            worker_reason_codes=active_worker_reason_codes,
            remaining_worker_budget=dynamic_worker_budget,
            governed_memory=planner_governed_memory,
        )
        model_planner_receipt = model_plan.receipt
        verify_incident_model_planner_receipt(model_planner_receipt)
        if model_plan.applied_worker_order:
            spec_by_role = {item[1]: item for item in dynamic_specs}
            prioritized = [
                spec_by_role[role] for role in model_plan.applied_worker_order
            ]
            prioritized_roles = set(model_plan.applied_worker_order)
            dynamic_specs = prioritized + [
                item for item in dynamic_specs if item[1] not in prioritized_roles
            ]
        actions.append(
            IncidentAgentAction(
                sequence=len(actions) + 1,
                iteration=case_version,
                agent_role="EvidenceGapCounterevidencePlannerAgent",
                action=(
                    "在影子模式生成证据缺口与反证建议，不改变调度"
                    if model_planner_receipt.mode is IncidentModelMode.SHADOW
                    else "验证模型建议后，仅调整白名单 Worker 的有界优先级"
                ),
                status=(
                    "COMPLETED"
                    if model_planner_receipt.status == "ACCEPTED"
                    else "STOPPED"
                ),
                dynamic=False,
                reason_codes=sorted(
                    {
                        code
                        for codes in active_worker_reason_codes.values()
                        for code in codes
                    }
                ),
                input_refs=[
                    "incident-evidence-gap-contract",
                    "worker-allowlist",
                    "worker-budget",
                ]
                + (
                    [
                        "governed-memory-retrieval:"
                        + governed_memory.retrieval_receipt.receipt_sha256
                    ]
                    if governed_memory is not None
                    else []
                ),
                expected_output=(
                    "经 Schema、证据 ID、Worker、预算与权限验证的咨询性计划"
                ),
                tool_contracts=[
                    "openai-compatible-chat-completions",
                    "incident-model-plan-validator-v1",
                ],
                output_receipt_sha256=model_planner_receipt.receipt_sha256,
            )
        )

    applied_worker_priority = (
        model_planner_receipt.applied_worker_order
        if model_planner_receipt is not None
        else []
    )
    counterevidence_dependencies = sorted(
        selected_worker_ids - {"CounterevidenceAuditorAgent"}
    )
    worker_execution_plan_receipt = build_worker_execution_plan_receipt_v1(
        worker_selection_receipt,
        dependency_map=(
            {"CounterevidenceAuditorAgent": counterevidence_dependencies}
            if "CounterevidenceAuditorAgent" in selected_worker_ids
            else None
        ),
        priority_order=applied_worker_priority,
    )
    verify_worker_execution_plan_receipt_v1(
        worker_execution_plan_receipt,
        selection=worker_selection_receipt,
    )
    autonomy_guard_receipt = build_autonomy_guard_receipt_v1(
        case_id=case_id,
        runtime_profile=incident_runtime_profile(request),
        selection=worker_selection_receipt,
        planner_receipt=model_planner_receipt,
    )
    verify_autonomy_guard_receipt_v1(
        autonomy_guard_receipt,
        selection=worker_selection_receipt,
        planner_receipt=model_planner_receipt,
    )

    dynamic_spec_by_role = {item[1]: item for item in dynamic_specs}
    ordinary_execution_order = [
        worker_id
        for worker_id in worker_execution_plan_receipt.execution_order
        if worker_id != "CounterevidenceAuditorAgent"
    ]
    ordered_dynamic_specs = [
        dynamic_spec_by_role[worker_id]
        for worker_id in ordinary_execution_order
        if worker_id in dynamic_spec_by_role
    ]
    ordered_dynamic_specs.extend(
        item for item in dynamic_specs if item[1] not in set(ordinary_execution_order)
    )

    for codes, role, action, expected, tools in ordered_dynamic_specs:
        if not codes:
            continue
        selected_for_execution = role in selected_worker_ids
        receipt: IncidentWorkerReceipt | None = None
        if selected_for_execution:
            try:
                receipt = resolved_worker_registry.execute(
                    worker_role=role,
                    iteration=case_version,
                    trigger_reason_codes=codes,
                    input_evidence_sha256=worker_input_hashes,
                    tool_contracts=tools,
                    candidate_issues=candidate_issues,
                )
            except IncidentWorkerExecutionError as error:
                receipt = _build_failed_incident_worker_receipt(
                    worker_registry=resolved_worker_registry,
                    worker_role=role,
                    iteration=case_version,
                    trigger_reason_codes=codes,
                    input_evidence_sha256=worker_input_hashes,
                    tool_contracts=tools,
                    failure=error,
                )
            verify_incident_worker_receipt(receipt)
            worker_receipts.append(receipt)
            if receipt.status == "SUCCEEDED":
                evaluated_issues.extend(
                    item.model_copy(
                        update={"producer_receipt_sha256": receipt.receipt_sha256}
                    )
                    for item in receipt.output_issues
                )
            else:
                failed_worker_receipts.append(receipt)
        else:
            stopped_roles.append(role)
        actions.append(
            IncidentAgentAction(
                sequence=len(actions) + 1,
                iteration=case_version,
                agent_role=role,
                action=action,
                status=(
                    "COMPLETED"
                    if receipt is not None and receipt.status == "SUCCEEDED"
                    else "FAILED"
                    if receipt is not None
                    else "STOPPED"
                ),
                dynamic=True,
                reason_codes=codes,
                input_refs=["incident-evidence"],
                expected_output=(
                    expected
                    if selected_for_execution
                    else "确定性 Worker 选择器未在本轮预算内选中；等待新案件版本继续"
                ),
                tool_contracts=tools,
                output_receipt_sha256=(
                    receipt.receipt_sha256 if receipt is not None else None
                ),
            )
        )
        if selected_for_execution:
            dynamic_workers_executed += 1
    if active_categories >= 2:
        selected_for_execution = "CounterevidenceAuditorAgent" in selected_worker_ids
        counter_receipt: IncidentWorkerReceipt | None = None
        candidate_issue_codes = counterevidence_reason_codes
        if selected_for_execution:
            counter_plan_node = next(
                item
                for item in worker_execution_plan_receipt.nodes
                if item.worker_id == "CounterevidenceAuditorAgent"
            )
            receipts_by_role = {item.worker_role: item for item in worker_receipts}
            missing_dependency_roles = [
                worker_id
                for worker_id in counter_plan_node.dependency_worker_ids
                if worker_id not in receipts_by_role
            ]
            if missing_dependency_roles:
                raise ValueError(
                    "Counterevidence dependency receipt is missing: "
                    + ", ".join(missing_dependency_roles)
                )
            dependency_receipts = [
                receipts_by_role[worker_id]
                for worker_id in counter_plan_node.dependency_worker_ids
            ]
            counter_input_hashes = worker_input_hashes + [
                item.receipt_sha256 for item in dependency_receipts
            ]
            failed_dependency_roles = [
                item.worker_role
                for item in dependency_receipts
                if item.status != "SUCCEEDED"
            ]
            if failed_dependency_roles:
                counter_receipt = _build_failed_incident_worker_receipt(
                    worker_registry=resolved_worker_registry,
                    worker_role="CounterevidenceAuditorAgent",
                    iteration=case_version,
                    trigger_reason_codes=candidate_issue_codes,
                    input_evidence_sha256=counter_input_hashes,
                    tool_contracts=["counterevidence-consistency-check"],
                    failure=IncidentWorkerExecutionError(
                        "DEPENDENCY_BARRIER_FAILED",
                        retryable=any(item.retryable for item in dependency_receipts),
                    ),
                )
            else:
                try:
                    counter_receipt = resolved_worker_registry.execute(
                        worker_role="CounterevidenceAuditorAgent",
                        iteration=case_version,
                        trigger_reason_codes=candidate_issue_codes,
                        input_evidence_sha256=counter_input_hashes,
                        tool_contracts=["counterevidence-consistency-check"],
                        candidate_issues=candidate_issues,
                        observations=[
                            "保留相互竞争的解释；相关性不得提升为已证实根因。"
                        ],
                    )
                except IncidentWorkerExecutionError as error:
                    counter_receipt = _build_failed_incident_worker_receipt(
                        worker_registry=resolved_worker_registry,
                        worker_role="CounterevidenceAuditorAgent",
                        iteration=case_version,
                        trigger_reason_codes=candidate_issue_codes,
                        input_evidence_sha256=counter_input_hashes,
                        tool_contracts=["counterevidence-consistency-check"],
                        failure=error,
                    )
            verify_incident_worker_receipt(counter_receipt)
            worker_receipts.append(counter_receipt)
            if counter_receipt.status == "FAILED":
                failed_worker_receipts.append(counter_receipt)
        else:
            stopped_roles.append("CounterevidenceAuditorAgent")
        actions.append(
            IncidentAgentAction(
                sequence=len(actions) + 1,
                iteration=case_version,
                agent_role="CounterevidenceAuditorAgent",
                action="检查多条解释之间的冲突，禁止把相关性写成根因",
                status=(
                    "COMPLETED"
                    if counter_receipt is not None
                    and counter_receipt.status == "SUCCEEDED"
                    else "FAILED"
                    if counter_receipt is not None
                    else "STOPPED"
                ),
                dynamic=True,
                reason_codes=candidate_issue_codes,
                input_refs=["hypothesis-ledger", "incident-evidence"],
                expected_output=(
                    "保留反证条件的调查结论"
                    if selected_for_execution
                    else "确定性 Worker 选择器未在本轮预算内选中；不得形成根因结论"
                ),
                tool_contracts=["counterevidence-consistency-check"],
                output_receipt_sha256=(
                    counter_receipt.receipt_sha256
                    if counter_receipt is not None
                    else None
                ),
            )
        )
        if selected_for_execution:
            dynamic_workers_executed += 1

    issues = evaluated_issues
    if failed_worker_receipts:
        failed_roles = sorted(item.worker_role for item in failed_worker_receipts)
        issues.append(
            IncidentEvidenceIssue(
                issue_code="WORKER_EXECUTION_FAILED",
                severity="BLOCKING",
                evidence_source="incident-worker-runtime",
                summary=(
                    "选中的专业 Worker 未产生可采信输出："
                    + "、".join(failed_roles)
                    + "。"
                ),
                required_evidence_or_action=(
                    "保持 HOLD；检查工具可用性后由具名责任人补证或创建新的受控案件迭代。"
                ),
                worker_role="IncidentCoordinatorAgent",
                blocks_disposition=True,
                producer_type="DETERMINISTIC_PREFLIGHT",
                input_evidence_refs=[
                    item.receipt_sha256 for item in failed_worker_receipts
                ],
            )
        )
    if stopped_roles:
        issues.append(
            IncidentEvidenceIssue(
                issue_code="EVIDENCE_NOT_EVALUATED_DUE_TO_BUDGET",
                severity="BLOCKING",
                evidence_source="incident-worker-budget",
                summary=(
                    "动态 Worker 预算不足，仍有专业证据分支未执行："
                    + "、".join(stopped_roles)
                    + "。"
                ),
                required_evidence_or_action=(
                    "由质量负责人补充针对性证据或创建新的受控案件迭代；"
                    "未执行 Worker 的候选问题不得进入裁决。"
                ),
                worker_role="IncidentCoordinatorAgent",
                blocks_disposition=True,
                producer_type="DETERMINISTIC_PREFLIGHT",
                input_evidence_refs=worker_input_hashes,
            )
        )

    issue_codes = [item.issue_code for item in issues]
    blocking_codes = [item.issue_code for item in issues if item.blocks_disposition]
    process_codes = [
        item.issue_code
        for item in issues
        if item.issue_code
        in {
            "PROCESS_SIGNAL_OUT_OF_RANGE",
            "PRODUCTION_CHANGE_SUPPORTS_PROCESS_HYPOTHESIS",
        }
    ]
    vision_codes = [
        item.issue_code
        for item in issues
        if item.worker_role == "VisionRecipeAgent"
        or item.issue_code == "PRODUCTION_CHANGE_SUPPORTS_VISION_HYPOTHESIS"
    ]
    data_codes = [code for code in issue_codes if code == "GATE_DECISION_NOT_PASS"]
    recovery_codes = [
        code for code in issue_codes if code == "CHILD_RUN_RECOVERY_NOT_OBSERVED"
    ]
    hypotheses = _build_incident_hypotheses(issues)
    evidence_edges = _build_incident_evidence_edges(hypotheses, issues)
    council_arbitration_receipt = build_council_arbitration_receipt_v1(
        case_id=case_id,
        belief_ledger=planning_belief_ledger,
        worker_execution_plan=worker_execution_plan_receipt,
        worker_receipts=worker_receipts,
        hypotheses=hypotheses,
    )
    verify_council_arbitration_receipt_v1(council_arbitration_receipt)

    evidence_blocking = bool(blocking_codes)
    if evidence_blocking:
        status = IncidentStatus.EVIDENCE_INCOMPLETE
        recommendation = IncidentRecommendation.COLLECT_MORE_EVIDENCE
        recommendation_reason = (
            "关键证据未完成、不可用、过期或无法唯一关联，系统失败关闭。"
        )
    elif recovery_codes:
        status = IncidentStatus.INVESTIGATION_REQUIRED
        recommendation = IncidentRecommendation.ESCALATE_TO_ENGINEER
        recommendation_reason = (
            "既有 child Run 未观察到恢复，禁止重复自动整改并转人工调查。"
        )
    elif (
        gate_context.capa_evidence is not None
        and gate_context.capa_evidence.recovery_status == "NOT_EXECUTED"
    ):
        status = IncidentStatus.REVERIFICATION_REQUIRED
        recommendation = IncidentRecommendation.REVERIFY_VISION_SOLUTION
        recommendation_reason = (
            "已选择的 CAPA 尚未形成可验签 recovery 回执，继续保持 HOLD。"
        )
    elif process_codes and vision_codes:
        status = IncidentStatus.INVESTIGATION_REQUIRED
        recommendation = IncidentRecommendation.CONTINUE_HOLD
        recommendation_reason = "工艺与视觉解释仍有冲突，需要具名责任人调查。"
    elif vision_codes:
        status = IncidentStatus.REVERIFICATION_REQUIRED
        recommendation = IncidentRecommendation.REVERIFY_VISION_SOLUTION
        recommendation_reason = "视觉方案沿袭或版本发生变化，需要同合同独立复验。"
    elif process_codes:
        status = IncidentStatus.INVESTIGATION_REQUIRED
        recommendation = IncidentRecommendation.CONTINUE_HOLD
        recommendation_reason = "过程信号超出冻结窗口，必须由设备或工艺责任人复核。"
    elif (
        gate_context.capa_evidence is not None
        and gate_context.capa_evidence.recovery_success
    ):
        status = IncidentStatus.READY_FOR_HUMAN_DECISION
        recommendation = IncidentRecommendation.RECOVERY_CANDIDATE
        recommendation_reason = (
            "绑定 CAPA 的 child Run 已观察到恢复候选，且当前工艺与视觉冲突已关闭；"
            "仍需具名质量负责人独立复核。"
        )
    elif data_codes and gate_context.remediation_plan_ids:
        status = IncidentStatus.PLAN_AWAITING_APPROVAL
        recommendation = IncidentRecommendation.SELECT_REMEDIATION_PLAN
        recommendation_reason = (
            "现有 Gate 已形成可选整改方案，等待质量负责人选择与批准。"
        )
    else:
        status = IncidentStatus.READY_FOR_HUMAN_DECISION
        recommendation = IncidentRecommendation.RECOVERY_CANDIDATE
        recommendation_reason = "当前证据可进入独立人工复核，但系统不作生产放行。"

    actions.extend(
        [
            IncidentAgentAction(
                sequence=len(actions) + 1,
                iteration=case_version,
                agent_role="EvidenceCouncil",
                action="交叉核对支持、反驳与未决证据，不建立物理根因",
                status="COMPLETED",
                dynamic=False,
                reason_codes=(
                    [council_arbitration_receipt.disposition]
                    + council_arbitration_receipt.failed_worker_ids
                ),
                input_refs=[
                    "evidence-belief-ledger",
                    "worker-execution-plan",
                    "worker-receipts",
                ],
                expected_output=(
                    "证据冲突与未决项的确定性仲裁回执；冻结 Judge 仍保有裁决权"
                ),
                tool_contracts=["council-arbitration-receipt-v1"],
                output_receipt_sha256=council_arbitration_receipt.receipt_sha256,
            ),
            IncidentAgentAction(
                sequence=len(actions) + 2,
                iteration=case_version,
                agent_role="FrozenPolicyJudge",
                action="按冻结证据资格规则形成处置建议",
                status="COMPLETED",
                dynamic=False,
                reason_codes=sorted(set(issue_codes)) or ["NO_BLOCKING_ISSUE"],
                input_refs=["evidence-ledger", "hypothesis-ledger"],
                expected_output=f"{status.value}:{recommendation.value}",
                tool_contracts=["industrial-incident-policy-v1"],
            ),
            IncidentAgentAction(
                sequence=len(actions) + 3,
                iteration=case_version,
                agent_role="NamedQualityOwner",
                action="独立复核并决定是否批准调查、CAPA或后续生产流程",
                status="PENDING_HUMAN",
                dynamic=False,
                reason_codes=["HUMAN_AUTHORITY_REQUIRED"],
                input_refs=["incident-case", "enterprise-safety-procedure"],
                expected_output="具名、可审计的人工决定",
                tool_contracts=[],
            ),
        ]
    )

    sealed_actions: list[IncidentAgentAction] = []
    for item in actions:
        if item.status != "COMPLETED" or item.output_receipt_sha256 is not None:
            sealed_actions.append(item)
            continue
        receipt_payload = item.model_dump(
            mode="json", exclude={"output_receipt_sha256"}
        )
        sealed_actions.append(
            item.model_copy(update={"output_receipt_sha256": _sha256(receipt_payload)})
        )
    actions = sealed_actions

    expected_evidence_by_worker = {
        "SignalIntegrityAgent": "opcua_snapshot",
        "EvidenceQualificationAgent": "quality_owner_decision",
        "TraceabilityAgent": "traceability_receipt",
        "ManufacturingContextAgent": "production_change_record",
        "ProcessContextAgent": "process_owner_attestation",
        "VisionRecipeAgent": "vision_solution_manifest",
        "VisualDataQualityAgent": "quality_owner_decision",
        "CounterevidenceAuditorAgent": "quality_owner_decision",
    }
    questions: list[IncidentOperatorQuestion] = []
    seen_prompts: set[str] = set()
    for item in issues:
        prompt = item.required_evidence_or_action
        if prompt in seen_prompts:
            continue
        seen_prompts.add(prompt)
        questions.append(
            IncidentOperatorQuestion(
                question_id=f"question_{_sha256({'code': item.issue_code, 'prompt': prompt})[:12]}",
                prompt=prompt,
                reason_codes=[item.issue_code],
                expected_evidence_type=expected_evidence_by_worker.get(
                    item.worker_role, "quality_owner_decision"
                ),
                required=item.blocks_disposition,
            )
        )
    if not questions:
        prompt = "请质量负责人确认企业抽检规范、现场风险与后续责任人。"
        questions = [
            IncidentOperatorQuestion(
                question_id=f"question_{_sha256(prompt)[:12]}",
                prompt=prompt,
                reason_codes=["HUMAN_AUTHORITY_REQUIRED"],
                expected_evidence_type="quality_owner_decision",
            )
        ]

    knowledge_references = list(request.knowledge_references)
    if not knowledge_references:
        knowledge_references = [
            IncidentKnowledgeReference(
                reference_id="rulepack:incident-default",
                kind="frozen_rulepack",
                title="当前任务冻结规则包",
                version="bound-by-vision-manifest",
                content_sha256=solution.rulepack_sha256,
                qualification=EvidenceQualification.QUALIFIED,
                scope_note="仅用于证据资格、处置边界和复验合同，不替代企业 SOP。",
            )
        ]

    simulated = (
        snapshot.source_mode is OPCUASnapshotMode.FIXTURE_REPLAY
        or opc_context.is_simulated
        or run.is_simulated
        or (batch_trace is not None and batch_trace.is_simulated)
        or any(item.is_simulated for item in production_changes)
    )
    evidence_refs = [
        IncidentEvidenceRef(
            evidence_type="opcua_snapshot",
            evidence_ref="opcua-offline-snapshot",
            evidence_sha256=snapshot_sha256,
            qualification=(
                EvidenceQualification.QUALIFIED_WITH_WARNING
                if simulated
                else EvidenceQualification.QUALIFIED
            ),
            role_in_decision="设备与机器视觉结果的只读语义、质量码和时间证据",
        ),
        IncidentEvidenceRef(
            evidence_type="vision_solution_manifest",
            evidence_ref="vision-solution-manifest",
            evidence_sha256=solution_sha256,
            qualification=EvidenceQualification.QUALIFIED,
            role_in_decision="视觉方案、模型、相机、光源、标定和规则版本沿袭",
        ),
        IncidentEvidenceRef(
            evidence_type="quality_inspection_result",
            evidence_ref="offline-vision-run-receipt",
            evidence_sha256=offline_run_sha256,
            qualification=(
                EvidenceQualification.NOT_QUALIFIED
                if run.execution_state != "Completed" or run.is_partial
                else EvidenceQualification.QUALIFIED_WITH_WARNING
                if run.is_simulated
                else EvidenceQualification.QUALIFIED
            ),
            role_in_decision="质检结果、OK/NG统计、批次/工单绑定和样本索引回执",
        ),
        IncidentEvidenceRef(
            evidence_type="gate_evidence_package",
            evidence_ref=f"task:{gate_context.task_id}:evidence",
            evidence_sha256=gate_context.task_evidence_sha256,
            qualification=EvidenceQualification.QUALIFIED,
            role_in_decision="图像、标注、metadata和动态补证的不可变证据包",
        ),
        IncidentEvidenceRef(
            evidence_type="industrial_delivery",
            evidence_ref=f"task:{gate_context.task_id}:industrial-delivery",
            evidence_sha256=gate_context.industrial_delivery_sha256,
            qualification=EvidenceQualification.QUALIFIED,
            role_in_decision="风险簇、责任动作和候选整改方案",
        ),
        IncidentEvidenceRef(
            evidence_type="source_authorization",
            evidence_ref=f"task:{gate_context.task_id}:source-authorization",
            evidence_sha256=gate_context.source_authorization_event_sha256,
            qualification=(
                EvidenceQualification.QUALIFIED
                if gate_context.source_kind == "local_authorized_directory"
                and gate_context.source_authorization_status == "ACTIVE"
                else EvidenceQualification.QUALIFIED_WITH_WARNING
                if gate_context.source_kind == "synthetic_demo"
                else EvidenceQualification.NOT_QUALIFIED
            ),
            role_in_decision="输入来源类型、授权状态与当前画像一致性",
        ),
    ]
    if batch_trace is not None and batch_trace_sha256 is not None:
        evidence_refs.append(
            IncidentEvidenceRef(
                evidence_type="batch_trace_record",
                evidence_ref=f"batch-trace:{batch_trace.record_id}",
                evidence_sha256=batch_trace_sha256,
                qualification=(
                    EvidenceQualification.NOT_QUALIFIED
                    if batch_trace.authority_status
                    is not ManufacturingRecordAuthorityStatus.VERIFIED
                    else EvidenceQualification.QUALIFIED_WITH_WARNING
                    if batch_trace.is_simulated
                    else EvidenceQualification.QUALIFIED
                ),
                role_in_decision=(
                    "MES/条码/工单权威批次、产品、配方、产线与生产时间窗绑定"
                ),
            )
        )
    evidence_refs.extend(
        IncidentEvidenceRef(
            evidence_type="production_change_record",
            evidence_ref=f"production-change:{item.record_id}",
            evidence_sha256=digest,
            qualification=(
                EvidenceQualification.NOT_QUALIFIED
                if item.authority_status
                is not ManufacturingRecordAuthorityStatus.VERIFIED
                or item.change_status != "APPROVED_EFFECTIVE"
                else EvidenceQualification.QUALIFIED_WITH_WARNING
                if item.is_simulated
                else EvidenceQualification.QUALIFIED
            ),
            role_in_decision=("换型、配方、视觉方案或工艺设定变更的批准状态与生效时间"),
        )
        for item, digest in zip(
            production_changes, production_change_sha256s, strict=True
        )
    )
    evidence_refs.extend(
        IncidentEvidenceRef(
            evidence_type="knowledge_reference",
            evidence_ref=f"knowledge:{item.reference_id}:{item.version}",
            evidence_sha256=item.content_sha256,
            qualification=item.qualification,
            role_in_decision=item.scope_note,
        )
        for item in knowledge_references
    )
    if gate_context.capa_evidence is not None:
        capa = gate_context.capa_evidence
        evidence_refs.append(
            IncidentEvidenceRef(
                evidence_type="capa_selection",
                evidence_ref=f"capa:{capa.capa_case_id}:selection",
                evidence_sha256=capa.selection_sha256,
                qualification=EvidenceQualification.QUALIFIED,
                role_in_decision="具名人工决定所选择的精确 CAPA 案件与方案",
            )
        )
        optional_capa_refs = [
            (
                "capa_approval",
                "approval",
                capa.approval_binding_sha256,
                "CAPA 审批与来源、规则、责任队列绑定",
            ),
            (
                "capa_derived_version",
                "derived-version",
                capa.derived_version_receipt_sha256,
                "不修改父数据的派生版本回执",
            ),
            (
                "capa_execution",
                "execution",
                capa.execution_receipt_sha256,
                "派生版本 child Run 执行与父子证据沿袭",
            ),
            (
                "capa_recovery",
                "recovery",
                capa.recovery_receipt_sha256,
                "child Run 恢复结果与责任队列复核",
            ),
        ]
        for evidence_type, suffix, digest, role in optional_capa_refs:
            if digest is None:
                continue
            evidence_refs.append(
                IncidentEvidenceRef(
                    evidence_type=evidence_type,
                    evidence_ref=f"capa:{capa.capa_case_id}:{suffix}",
                    evidence_sha256=digest,
                    qualification=EvidenceQualification.QUALIFIED,
                    role_in_decision=role,
                )
            )

    stopped_dynamic = any(item.dynamic and item.status == "STOPPED" for item in actions)
    failed_dynamic = any(item.dynamic and item.status == "FAILED" for item in actions)
    required_prompts = [item.prompt for item in questions if item.required]
    if stopped_dynamic:
        stop_reason = IncidentLoopStopReason.WORKER_BUDGET_EXHAUSTED
    elif case_version >= request.max_agent_iterations and status not in {
        IncidentStatus.READY_FOR_HUMAN_DECISION,
        IncidentStatus.PLAN_AWAITING_APPROVAL,
    }:
        stop_reason = IncidentLoopStopReason.MAX_ITERATIONS_REACHED
    elif status is IncidentStatus.EVIDENCE_INCOMPLETE:
        stop_reason = IncidentLoopStopReason.WAITING_FOR_EVIDENCE
    elif status in {
        IncidentStatus.PLAN_AWAITING_APPROVAL,
        IncidentStatus.INVESTIGATION_REQUIRED,
        IncidentStatus.REVERIFICATION_REQUIRED,
    }:
        stop_reason = IncidentLoopStopReason.WAITING_FOR_HUMAN_APPROVAL
    else:
        stop_reason = IncidentLoopStopReason.READY_FOR_HUMAN_DECISION

    can_resume = case_version < request.max_agent_iterations and stop_reason not in {
        IncidentLoopStopReason.MAX_ITERATIONS_REACHED,
        IncidentLoopStopReason.SAFETY_GATE_BLOCKED,
    }
    current_executed_dynamic_count = sum(
        item.dynamic and item.status in {"COMPLETED", "FAILED"} for item in actions
    )
    completed_dynamic_count = (
        prior_dynamic_workers_executed + current_executed_dynamic_count
    )
    loop_control = IncidentLoopControl(
        current_iteration=case_version,
        max_iterations=request.max_agent_iterations,
        dynamic_worker_budget=request.max_dynamic_workers,
        dynamic_workers_executed=completed_dynamic_count,
        remaining_worker_budget=max(
            request.max_dynamic_workers - completed_dynamic_count, 0
        ),
        stop_reason=stop_reason,
        can_resume=can_resume,
        resume_requires=required_prompts or ["具名质量负责人决定"],
    )

    dynamic_roles = [
        item.agent_role
        for item in actions
        if item.dynamic and item.status == "COMPLETED"
    ]
    failed_dynamic_roles = [
        item.agent_role for item in actions if item.dynamic and item.status == "FAILED"
    ]
    loop_steps = [
        IncidentLoopStep(
            sequence=1,
            iteration=case_version,
            phase="PLAN",
            actor="IncidentCoordinatorAgent",
            summary=(
                "冻结触发事件、证据边界、工具预算与人工权限；"
                f"模型规划模式为 {model_planner_receipt.mode.value}，"
                "仅允许经验证的 Worker 优先级生效。"
                if model_planner_receipt is not None
                else "冻结触发事件、证据边界、工具预算与人工权限。"
            ),
            input_refs=["incident-request", "gate-context"],
            output_refs=["evidence-plan", "worker-budget"]
            + (
                ["incident-model-planner-receipt"]
                if model_planner_receipt is not None
                else []
            ),
            status="COMPLETED",
        ),
        IncidentLoopStep(
            sequence=2,
            iteration=case_version,
            phase="ACT",
            actor="DynamicWorkerPool",
            summary=(
                "按证据缺口完成 " + "、".join(dynamic_roles)
                if dynamic_roles
                else "专业 Worker 未产生已完成输出。"
                if failed_dynamic_roles
                else "当前证据未触发额外专业 Worker。"
            ),
            input_refs=["evidence-plan"],
            output_refs=["evidence-issue-ledger", "worker-receipts"],
            status=("STOPPED" if stopped_dynamic or failed_dynamic else "COMPLETED"),
        ),
        IncidentLoopStep(
            sequence=3,
            iteration=case_version,
            phase="OBSERVE",
            actor="EvidenceLedger",
            summary=(
                f"形成 {len(issues)} 条证据问题和 {len(hypotheses)} 条竞争性假设；"
                "未把相关性写成根因。"
            ),
            input_refs=["worker-receipts"],
            output_refs=["evidence-issue-ledger", "hypothesis-ledger"],
            status="COMPLETED",
        ),
        IncidentLoopStep(
            sequence=4,
            iteration=case_version,
            phase="EVALUATE",
            actor="FrozenPolicyJudge",
            summary=f"冻结规则给出 {status.value} / {recommendation.value}。",
            input_refs=["evidence-issue-ledger", "hypothesis-ledger"],
            output_refs=["decision-summary"],
            status="COMPLETED",
        ),
        IncidentLoopStep(
            sequence=5,
            iteration=case_version,
            phase="INTERRUPT",
            actor="NamedQualityOwner",
            summary="在继续补证、选择整改方案或复验前暂停，等待具名人工决定。",
            input_refs=["decision-summary", "operator-questions"],
            output_refs=["human-decision-receipt"],
            status="PAUSED",
        ),
    ]

    previous_issue_codes = (
        set()
        if parent_case is None
        else {item.issue_code for item in parent_case.evidence_issues}
    )
    current_issue_codes = {item.issue_code for item in issues}
    newly_observed_issue_codes = sorted(current_issue_codes - previous_issue_codes)
    resolved_issue_codes = sorted(previous_issue_codes - current_issue_codes)
    previous_hypothesis_states = (
        {}
        if parent_case is None
        else {item.hypothesis_id: item.status.value for item in parent_case.hypotheses}
    )
    hypothesis_state_changes = sorted(
        f"{item.hypothesis_id}:{previous_hypothesis_states.get(item.hypothesis_id, 'NEW')}->{item.status.value}"
        for item in hypotheses
        if previous_hypothesis_states.get(item.hypothesis_id) != item.status.value
    )
    previous_worker_signatures = (
        set()
        if parent_case is None
        else {
            f"{item.worker_role}:{item.output_artifact_sha256}"
            for item in parent_case.worker_receipts
        }
    )
    current_worker_signatures = {
        f"{item.worker_role}:{item.output_artifact_sha256}" for item in worker_receipts
    }
    repeated_invocation_signatures = sorted(
        previous_worker_signatures & current_worker_signatures
    )
    progress_made = parent_case is None or bool(
        newly_observed_issue_codes
        or resolved_issue_codes
        or hypothesis_state_changes
        or (
            gate_context.capa_evidence is not None
            and gate_context.capa_evidence.recovery_status != "NOT_EXECUTED"
        )
    )
    previous_stall_count = (
        0
        if parent_case is None or parent_case.progress_ledger is None
        else parent_case.progress_ledger.stall_count
    )
    progress_ledger = IncidentProgressLedger(
        evidence_bundle_sha256=evidence_bundle_sha256,
        previous_evidence_bundle_sha256=(
            None
            if parent_case is None
            else parent_case.evidence_bundle_sha256
            or industrial_incident_evidence_bundle_sha256(parent_case.request)
        ),
        evaluated_issue_codes=sorted(current_issue_codes),
        newly_observed_issue_codes=newly_observed_issue_codes,
        resolved_issue_codes=resolved_issue_codes,
        hypothesis_state_changes=hypothesis_state_changes,
        completed_worker_invocations=[item.invocation_id for item in worker_receipts],
        repeated_invocation_signatures=repeated_invocation_signatures,
        progress_made=progress_made,
        stall_count=0 if progress_made else previous_stall_count + 1,
        replan_reason=(
            "首次案件已建立证据基线。"
            if parent_case is None
            else "新证据改变了问题或假设状态，继续按冻结策略评估。"
            if progress_made
            else "证据包发生变化但问题与假设未移动；禁止重复同一路径并转人工重规划。"
        ),
    )

    unresolved_codes = sorted(
        item.issue_code
        for item in issues
        if item.blocks_disposition or item.severity == "WARNING"
    )
    observed_facts = [
        f"{len(evidence_refs)} 份证据引用已绑定 SHA-256。",
        (
            f"本轮 {current_executed_dynamic_count} 个、累计 {completed_dynamic_count} 个"
            "动态专业 Worker 执行有界调用（失败调用同样占用冻结预算）。"
        ),
        f"当前父 Gate 结论为 {gate_context.gate_final_decision}。",
        (
            "本案件使用 fixture/仿真证据，只验证产品闭环。"
            if simulated
            else "本案件使用离线只读导出，未连接真实 OPC UA 端点。"
        ),
    ]
    if model_planner_receipt is not None:
        observed_facts.append(
            "可选模型 Planner 仅产生咨询性计划回执；最终状态仍由冻结规则计算。"
        )
    decision_summary = IncidentDecisionSummary(
        observed_facts=observed_facts,
        unresolved_reason_codes=unresolved_codes,
        alternatives_kept_open=[
            item.statement
            for item in hypotheses
            if item.status is not HypothesisStatus.REJECTED
        ][:6],
        prohibited_conclusions=[
            "不得把当前证据相关性写成已证实根因。",
            "不得把 child Run 或 Gate 结果写成生产放行。",
            "不得据此直接控制设备、相机、光源、IO 或配方。",
        ],
        next_safe_action=recommendation_reason,
    )

    incident_root_id = (
        case_id
        if parent_case is None
        else parent_case.incident_root_id or parent_case.case_id
    )
    stable = {
        "schema_version": GOVERNED_INCIDENT_CASE_SCHEMA_VERSION,
        "audit_envelope_requirement": GOVERNED_AUDIT_ENVELOPE_REQUIREMENT,
        "case_id": case_id,
        "incident_root_id": incident_root_id,
        "case_version": case_version,
        "parent_case_id": parent_case.case_id if parent_case is not None else None,
        "parent_case_sha256": (
            parent_case.case_sha256 if parent_case is not None else None
        ),
        "authorizing_decision_id": (
            authorizing_decision.decision_id
            if authorizing_decision is not None
            else None
        ),
        "authorizing_decision_sha256": (
            authorizing_decision.decision_sha256
            if authorizing_decision is not None
            else None
        ),
        "task_id": gate_context.task_id,
        "target_user": "中小制造企业质量负责人",
        "task_boundary": "换型后视觉质量异常处置与方案复验",
        "request": request,
        "gate_context": gate_context,
        "context_sha256": context_sha256,
        "evidence_bundle_sha256": evidence_bundle_sha256,
        "evidence_refs": evidence_refs,
        "evidence_issues": issues,
        "hypotheses": hypotheses,
        "evidence_edges": evidence_edges,
        "planning_belief_ledger": planning_belief_ledger,
        "worker_selection_receipt": worker_selection_receipt,
        "parent_belief_revision_receipt": parent_belief_revision_receipt,
        "worker_execution_plan_receipt": worker_execution_plan_receipt,
        "council_arbitration_receipt": council_arbitration_receipt,
        "autonomy_guard_receipt": autonomy_guard_receipt,
        "agent_actions": actions,
        "worker_receipts": worker_receipts,
        "model_planner_receipt": model_planner_receipt,
        "governed_memory_planning_input_sha256": (
            governed_memory.input_sha256 if governed_memory is not None else None
        ),
        "governed_memory_retrieval_receipt_sha256": (
            governed_memory.retrieval_receipt.receipt_sha256
            if governed_memory is not None
            else None
        ),
        "loop_steps": loop_steps,
        "loop_control": loop_control,
        "progress_ledger": progress_ledger,
        "knowledge_references": knowledge_references,
        "decision_summary": decision_summary,
        "dynamic_branch_count": current_executed_dynamic_count,
        "status": status,
        "recommendation": recommendation,
        "recommendation_reason": recommendation_reason,
        "operator_questions": questions,
        "linked_remediation_plan_ids": gate_context.remediation_plan_ids,
        "root_cause_status": "NOT_ESTABLISHED",
        "planning_mode": (
            "bounded_model_planner_loop_v3"
            if model_planner_receipt is not None
            else "bounded_evidence_agent_loop_v2"
        ),
        "external_model_call_count": (
            model_planner_receipt.model_call_count
            if model_planner_receipt is not None
            else 0
        ),
        "opcua_connection_status": (
            "OPC_UA_FIXTURE_REPLAY_ONLY"
            if simulated
            else "OPC_UA_REAL_ENDPOINT_NOT_CONNECTED"
        ),
        "visionmaster_connection_status": "VISIONMASTER_SDK_NOT_CONNECTED",
        "human_approval_required": True,
        "production_release_allowed": False,
        "machine_write_permitted": False,
        "direct_equipment_control_permitted": False,
        "claim_boundary": IndustrialIncidentCase.model_fields["claim_boundary"].default,
    }
    return IndustrialIncidentCase(**stable, case_sha256=_sha256(stable))


def build_incident_phase_events(
    case: IndustrialIncidentCase,
) -> list[IncidentPhaseEvent]:
    """Build a deterministic append-only phase and invocation event chain."""

    verify_industrial_incident_case(case)
    events: list[IncidentPhaseEvent] = []

    def append_event(
        *,
        phase: Literal["PLAN", "ACT", "OBSERVE", "EVALUATE", "INTERRUPT"],
        actor: str,
        input_sha256: str,
        output_sha256: str,
        status: Literal["SUCCEEDED", "FAILED", "STOPPED", "PAUSED"],
        invocation_id: str | None = None,
        error_code: str | None = None,
        retryable: bool = False,
    ) -> None:
        sequence = len(events) + 1
        resolved_invocation_id = invocation_id or (
            "phase_invocation_"
            + _sha256(
                {
                    "case_id": case.case_id,
                    "sequence": sequence,
                    "phase": phase,
                    "actor": actor,
                }
            )[:20]
        )
        stable = {
            "schema_version": "visiondata-gate.incident-phase-event.v1",
            "event_id": "incident_event_"
            + _sha256(
                {
                    "case_id": case.case_id,
                    "sequence": sequence,
                    "invocation_id": resolved_invocation_id,
                }
            )[:20],
            "case_id": case.case_id,
            "case_sha256": case.case_sha256,
            "sequence": sequence,
            "iteration": case.case_version,
            "phase": phase,
            "invocation_id": resolved_invocation_id,
            "actor": actor,
            "input_sha256": input_sha256,
            "output_sha256": output_sha256,
            "status": status,
            "error_code": error_code,
            "retryable": retryable,
            "prev_event_sha256": (events[-1].event_sha256 if events else None),
        }
        events.append(IncidentPhaseEvent(**stable, event_sha256=_sha256(stable)))

    dynamic_actions = [item for item in case.agent_actions if item.dynamic]
    append_event(
        phase="PLAN",
        actor="IncidentCoordinatorAgent",
        input_sha256=_sha256(
            {
                "request": case.request,
                "gate_context": case.gate_context,
                "parent_case_sha256": case.parent_case_sha256,
                "authorizing_decision_sha256": case.authorizing_decision_sha256,
                "governed_memory_planning_input_sha256": (
                    case.governed_memory_planning_input_sha256
                ),
                "governed_memory_retrieval_receipt_sha256": (
                    case.governed_memory_retrieval_receipt_sha256
                ),
            }
        ),
        output_sha256=_sha256(
            {
                "dynamic_actions": dynamic_actions,
                "loop_control": case.loop_control,
                "model_planner_receipt": case.model_planner_receipt,
            }
        ),
        status="SUCCEEDED",
    )

    receipts_by_sha = {item.receipt_sha256: item for item in case.worker_receipts}
    if not dynamic_actions:
        append_event(
            phase="ACT",
            actor="DynamicWorkerPool",
            input_sha256=events[-1].output_sha256,
            output_sha256=_sha256(
                {
                    "result": "NO_DYNAMIC_WORKER_REQUIRED",
                    "case_id": case.case_id,
                }
            ),
            status="SUCCEEDED",
        )
    for action in dynamic_actions:
        receipt = receipts_by_sha.get(action.output_receipt_sha256 or "")
        if receipt is not None:
            status: Literal["SUCCEEDED", "FAILED", "STOPPED", "PAUSED"] = (
                "SUCCEEDED" if receipt.status == "SUCCEEDED" else "FAILED"
            )
            invocation_id = receipt.invocation_id
            output_sha256 = receipt.output_artifact_sha256
            error_code = receipt.error_code
            retryable = receipt.retryable
        else:
            status = "PAUSED" if action.status == "PENDING_HUMAN" else "STOPPED"
            invocation_id = None
            output_sha256 = _sha256(action)
            error_code = (
                action.reason_codes[0] if action.reason_codes else "WORKER_NOT_EXECUTED"
            )
            retryable = False
        append_event(
            phase="ACT",
            actor=action.agent_role,
            input_sha256=_sha256(
                {
                    "evidence_bundle_sha256": case.evidence_bundle_sha256,
                    "input_refs": action.input_refs,
                    "reason_codes": action.reason_codes,
                    "tool_contracts": action.tool_contracts,
                }
            ),
            output_sha256=output_sha256,
            status=status,
            invocation_id=invocation_id,
            error_code=error_code,
            retryable=retryable,
        )

    observation_output_sha256 = _sha256(
        {
            "evidence_issues": case.evidence_issues,
            "hypotheses": case.hypotheses,
            "evidence_edges": case.evidence_edges,
            "progress_ledger": case.progress_ledger,
        }
    )
    append_event(
        phase="OBSERVE",
        actor="EvidenceLedger",
        input_sha256=_sha256(
            {
                "worker_receipt_sha256": [
                    item.receipt_sha256 for item in case.worker_receipts
                ],
                "last_act_event_sha256": events[-1].event_sha256,
            }
        ),
        output_sha256=observation_output_sha256,
        status="SUCCEEDED",
    )
    evaluation_output_sha256 = _sha256(
        {
            "status": case.status,
            "recommendation": case.recommendation,
            "recommendation_reason": case.recommendation_reason,
            "decision_summary": case.decision_summary,
        }
    )
    append_event(
        phase="EVALUATE",
        actor="FrozenPolicyJudge",
        input_sha256=observation_output_sha256,
        output_sha256=evaluation_output_sha256,
        status="SUCCEEDED",
    )
    append_event(
        phase="INTERRUPT",
        actor="NamedQualityOwner",
        input_sha256=evaluation_output_sha256,
        output_sha256=_sha256(
            {
                "state": "AWAITING_NAMED_HUMAN_DECISION",
                "operator_questions": case.operator_questions,
                "production_release_allowed": case.production_release_allowed,
            }
        ),
        status="PAUSED",
        error_code="HUMAN_DECISION_REQUIRED",
        retryable=False,
    )
    verify_incident_phase_events(case, events)
    return events


def verify_incident_phase_events(
    case: IndustrialIncidentCase, events: list[IncidentPhaseEvent]
) -> None:
    """Verify case binding, ordering, hashes, and invoked Worker coverage."""

    verify_industrial_incident_case(case)
    if not events:
        raise ValueError("industrial incident phase event chain is empty")
    expected_phases = (
        ["PLAN"] + ["ACT"] * (len(events) - 4) + ["OBSERVE", "EVALUATE", "INTERRUPT"]
    )
    if [item.phase for item in events] != expected_phases:
        raise ValueError("industrial incident phase event ordering is invalid")

    previous_sha256: str | None = None
    for sequence, event in enumerate(events, start=1):
        payload = event.model_dump(mode="json")
        stored = payload.pop("event_sha256")
        if not hmac.compare_digest(stored, _sha256(payload)):
            raise ValueError(
                "industrial incident phase event failed SHA-256 validation"
            )
        if (
            event.sequence != sequence
            or event.case_id != case.case_id
            or event.case_sha256 != case.case_sha256
            or event.iteration != case.case_version
        ):
            raise ValueError("industrial incident phase event failed case binding")
        if event.prev_event_sha256 != previous_sha256:
            raise ValueError("industrial incident phase event chain is broken")
        previous_sha256 = event.event_sha256

    receipt_by_invocation = {item.invocation_id: item for item in case.worker_receipts}
    worker_events = {
        item.invocation_id: item
        for item in events
        if item.phase == "ACT" and item.invocation_id.startswith("worker_invocation_")
    }
    if set(worker_events) != set(receipt_by_invocation):
        raise ValueError(
            "industrial incident phase events do not cover Worker receipts"
        )
    for invocation_id, receipt in receipt_by_invocation.items():
        event = worker_events[invocation_id]
        expected_status = "SUCCEEDED" if receipt.status == "SUCCEEDED" else "FAILED"
        if (
            event.actor != receipt.worker_role
            or event.output_sha256 != receipt.output_artifact_sha256
            or event.status != expected_status
            or event.error_code != receipt.error_code
            or event.retryable != receipt.retryable
        ):
            raise ValueError("industrial incident Worker event failed receipt binding")


def verify_industrial_incident_case(case: IndustrialIncidentCase) -> None:
    cache = _INCIDENT_CASE_VERIFICATION_CACHE.get()
    if cache is not None:
        cached = cache.get(id(case))
        if (
            cached is not None
            and cached[0] is case
            and hmac.compare_digest(cached[1], case.case_sha256)
        ):
            return

    payload = case.model_dump(mode="json")
    stored = payload.pop("case_sha256")
    expected = _sha256(payload)
    if not hmac.compare_digest(stored, expected):
        compatibility_payloads: list[dict[str, object]] = []
        if case.schema_version != AGENT_KERNEL_INCIDENT_CASE_SCHEMA_VERSION:
            pre_v6_payload = dict(payload)
            for field_name in (
                "parent_belief_revision_receipt",
                "worker_execution_plan_receipt",
                "council_arbitration_receipt",
                "autonomy_guard_receipt",
            ):
                pre_v6_payload.pop(field_name, None)
            compatibility_payloads.append(pre_v6_payload)
            if case.model_planner_receipt is None:
                without_optional_planner = dict(pre_v6_payload)
                without_optional_planner.pop("model_planner_receipt", None)
                compatibility_payloads.append(without_optional_planner)
            if (
                case.schema_version
                not in PLANNING_ARTIFACT_INCIDENT_CASE_SCHEMA_VERSIONS
            ):
                pre_v5_payload = dict(pre_v6_payload)
                pre_v5_payload.pop("planning_belief_ledger", None)
                pre_v5_payload.pop("worker_selection_receipt", None)
                compatibility_payloads.append(pre_v5_payload)
                if case.model_planner_receipt is None:
                    pre_v5_without_planner = dict(pre_v5_payload)
                    pre_v5_without_planner.pop("model_planner_receipt", None)
                    compatibility_payloads.append(pre_v5_without_planner)
        if not any(
            hmac.compare_digest(stored, _sha256(candidate))
            for candidate in compatibility_payloads
        ):
            raise ValueError(
                "industrial incident case failed SHA-256 integrity validation"
            )
    if case.schema_version not in PHASE_EVENT_INCIDENT_CASE_SCHEMA_VERSIONS:
        if cache is not None:
            cache[id(case)] = (case, case.case_sha256)
        return
    if case.schema_version in PLANNING_ARTIFACT_INCIDENT_CASE_SCHEMA_VERSIONS:
        planning_belief_ledger = case.planning_belief_ledger
        worker_selection_receipt = case.worker_selection_receipt
        if planning_belief_ledger is None or worker_selection_receipt is None:
            raise ValueError("v5+ incident case lost its planning artifacts")
        verify_evidence_belief_ledger_v2(planning_belief_ledger)
        verify_worker_selection_receipt(worker_selection_receipt)
        if planning_belief_ledger.case_id != case.case_id or not hmac.compare_digest(
            planning_belief_ledger.evidence_bundle_sha256,
            case.evidence_bundle_sha256 or "",
        ):
            raise ValueError("incident belief ledger lost its Case binding")
        freshness = planning_belief_ledger.source_authorization_freshness
        if (
            freshness.source_authorization_event_sha256
            != case.gate_context.source_authorization_event_sha256
            or freshness.source_authorization_status
            != case.gate_context.source_authorization_status
        ):
            raise ValueError("incident belief ledger lost source authorization binding")
        known_hypothesis_ids = {
            item.hypothesis_id for item in planning_belief_ledger.snapshots
        }
        if any(
            not set(candidate.discriminated_hypothesis_ids) <= known_hypothesis_ids
            for candidate in worker_selection_receipt.candidates
        ):
            raise ValueError("Worker selection references an unknown belief hypothesis")
    if (case.governed_memory_planning_input_sha256 is None) != (
        case.governed_memory_retrieval_receipt_sha256 is None
    ):
        raise ValueError("incident governed memory binding is incomplete")
    if case.model_planner_receipt is not None:
        verify_incident_model_planner_receipt(case.model_planner_receipt)
        if case.planning_mode != "bounded_model_planner_loop_v3":
            raise ValueError("incident model receipt lacks model planning mode")
        if (
            case.external_model_call_count
            != case.model_planner_receipt.model_call_count
        ):
            raise ValueError("incident model call count failed receipt binding")
        if (
            case.model_planner_receipt.governed_memory_input_sha256
            != case.governed_memory_planning_input_sha256
            or case.model_planner_receipt.governed_memory_retrieval_receipt_sha256
            != case.governed_memory_retrieval_receipt_sha256
        ):
            raise ValueError("incident model Planner lost governed memory binding")
    elif case.external_model_call_count != 0:
        raise ValueError("incident model calls require a planner receipt")
    for receipt in case.worker_receipts:
        verify_incident_worker_receipt(receipt)
    if case.schema_version == AGENT_KERNEL_INCIDENT_CASE_SCHEMA_VERSION:
        planning_belief_ledger = case.planning_belief_ledger
        worker_selection_receipt = case.worker_selection_receipt
        worker_execution_plan_receipt = case.worker_execution_plan_receipt
        council_arbitration_receipt = case.council_arbitration_receipt
        autonomy_guard_receipt = case.autonomy_guard_receipt
        assert planning_belief_ledger is not None
        assert worker_selection_receipt is not None
        assert worker_execution_plan_receipt is not None
        assert council_arbitration_receipt is not None
        assert autonomy_guard_receipt is not None
        verify_worker_execution_plan_receipt_v1(
            worker_execution_plan_receipt,
            selection=worker_selection_receipt,
        )
        if case.case_version == 1:
            if case.parent_belief_revision_receipt is not None:
                raise ValueError("root v6 Case unexpectedly revises a parent belief")
        else:
            revision = case.parent_belief_revision_receipt
            if revision is None:
                raise ValueError("resumed v6 Case lost parent belief revision")
            verify_evidence_belief_revision_receipt_v1(revision)
            if (
                revision.parent_case_id != case.parent_case_id
                or revision.parent_case_sha256 != case.parent_case_sha256
                or revision.observed_authorization_event_sha256
                != case.gate_context.source_authorization_event_sha256
                or revision.observed_authorization_status
                != case.gate_context.source_authorization_status
                or revision.observed_evidence_bundle_sha256
                != case.evidence_bundle_sha256
            ):
                raise ValueError("parent belief revision lost Case lineage binding")
        expected_council = build_council_arbitration_receipt_v1(
            case_id=case.case_id,
            belief_ledger=planning_belief_ledger,
            worker_execution_plan=worker_execution_plan_receipt,
            worker_receipts=case.worker_receipts,
            hypotheses=case.hypotheses,
        )
        if expected_council != council_arbitration_receipt:
            raise ValueError("Council arbitration diverged from Case evidence")
        verify_council_arbitration_receipt_v1(council_arbitration_receipt)
        expected_autonomy_guard = build_autonomy_guard_receipt_v1(
            case_id=case.case_id,
            runtime_profile=incident_runtime_profile(case.request),
            selection=worker_selection_receipt,
            planner_receipt=case.model_planner_receipt,
        )
        if expected_autonomy_guard != autonomy_guard_receipt:
            raise ValueError("autonomy guard diverged from the bounded runtime")
        if (
            worker_execution_plan_receipt.requested_priority_order
            != autonomy_guard_receipt.applied_worker_priority_ids
        ):
            raise ValueError("Worker execution plan lost planner-priority binding")
        verify_autonomy_guard_receipt_v1(
            autonomy_guard_receipt,
            selection=worker_selection_receipt,
            planner_receipt=case.model_planner_receipt,
            require_planner_binding=True,
        )
        receipts_by_role = {item.worker_role: item for item in case.worker_receipts}
        if case.evidence_bundle_sha256 is None:
            raise ValueError("v6 incident Case lost its evidence bundle SHA")
        expected_worker_inputs = [
            _sha256(case.request.opcua_snapshot),
            _sha256(case.request.vision_solution),
            _sha256(case.request.offline_run),
            _sha256(case.gate_context),
            case.evidence_bundle_sha256,
        ]
        if case.request.batch_trace_record is not None:
            expected_worker_inputs.append(_sha256(case.request.batch_trace_record))
        expected_worker_inputs.extend(
            _sha256(item) for item in case.request.production_change_records
        )
        executed_worker_order = [
            item.agent_role
            for item in case.agent_actions
            if item.dynamic and item.status in {"COMPLETED", "FAILED"}
        ]
        executed_actions_by_role = {
            item.agent_role: item
            for item in case.agent_actions
            if item.dynamic and item.status in {"COMPLETED", "FAILED"}
        }
        if executed_worker_order != worker_execution_plan_receipt.execution_order:
            raise ValueError("Worker runtime order diverged from its execution plan")
        for node in worker_execution_plan_receipt.nodes:
            receipt = receipts_by_role.get(node.worker_id)
            action = executed_actions_by_role.get(node.worker_id)
            if receipt is None or action is None:
                raise ValueError("Worker execution plan lacks an execution receipt")
            dependency_receipts = [
                receipts_by_role.get(worker_id)
                for worker_id in node.dependency_worker_ids
            ]
            if any(item is None for item in dependency_receipts):
                raise ValueError("Worker dependency barrier lost a receipt")
            dependency_sha256s = {
                item.receipt_sha256 for item in dependency_receipts if item is not None
            }
            if not dependency_sha256s <= set(receipt.input_evidence_sha256):
                raise ValueError("Worker receipt lost dependency SHA binding")
            expected_input_sha256 = [
                *expected_worker_inputs,
                *[
                    item.receipt_sha256
                    for item in dependency_receipts
                    if item is not None
                ],
            ]
            if (
                receipt.iteration != action.iteration
                or receipt.trigger_reason_codes != sorted(set(action.reason_codes))
                or receipt.tool_contracts != action.tool_contracts
                or receipt.input_evidence_sha256 != expected_input_sha256
            ):
                raise ValueError(
                    "Worker receipt trigger or evidence inputs diverged from execution"
                )
            dependency_failed = any(
                item is not None and item.status != "SUCCEEDED"
                for item in dependency_receipts
            )
            if dependency_failed and not (
                receipt.status == "FAILED"
                and receipt.error_code == "DEPENDENCY_BARRIER_FAILED"
            ):
                raise ValueError("failed Worker dependency did not stop execution")
    receipt_by_sha = {item.receipt_sha256: item for item in case.worker_receipts}
    for action in case.agent_actions:
        if action.dynamic and action.status in {"COMPLETED", "FAILED"}:
            receipt = receipt_by_sha.get(action.output_receipt_sha256 or "")
            if receipt is None or receipt.worker_role != action.agent_role:
                raise ValueError("executed dynamic action lacks a bound Worker receipt")
            expected_receipt_status = (
                "SUCCEEDED" if action.status == "COMPLETED" else "FAILED"
            )
            if receipt.status != expected_receipt_status:
                raise ValueError(
                    "dynamic action status diverged from its Worker receipt"
                )
    if case.schema_version in PLANNING_ARTIFACT_INCIDENT_CASE_SCHEMA_VERSIONS:
        worker_selection_receipt = case.worker_selection_receipt
        assert worker_selection_receipt is not None
        selected_roles = set(worker_selection_receipt.selected_worker_ids)
        executed_dynamic_roles = {
            item.agent_role
            for item in case.agent_actions
            if item.dynamic and item.status in {"COMPLETED", "FAILED"}
        }
        receipt_roles = {item.worker_role for item in case.worker_receipts}
        if len(receipt_roles) != len(case.worker_receipts):
            raise ValueError("incident case contains duplicate Worker role receipts")
        if selected_roles != executed_dynamic_roles or selected_roles != receipt_roles:
            raise ValueError(
                "incident Worker execution diverged from its selection receipt"
            )
    for issue in case.evidence_issues:
        if issue.producer_type == "WORKER_RECEIPT":
            receipt = receipt_by_sha.get(issue.producer_receipt_sha256 or "")
            if receipt is None:
                raise ValueError("incident issue lacks a verified producer receipt")
            if receipt.status != "SUCCEEDED":
                raise ValueError("incident Judge consumed a failed Worker receipt")
    if cache is not None:
        cache[id(case)] = (case, case.case_sha256)


__all__ = [
    "AGENT_KERNEL_INCIDENT_CASE_SCHEMA_VERSION",
    "GOVERNED_AUDIT_ENVELOPE_REQUIREMENT",
    "GOVERNED_INCIDENT_CASE_SCHEMA_VERSION",
    "GOVERNED_INCIDENT_CASE_SCHEMA_VERSIONS",
    "LEGACY_INCIDENT_CASE_SCHEMA_VERSIONS",
    "PHASE_EVENT_INCIDENT_CASE_SCHEMA_VERSIONS",
    "PLANNING_ARTIFACT_INCIDENT_CASE_SCHEMA_VERSIONS",
    "BatchTraceRecord",
    "EvidenceQualification",
    "HypothesisStatus",
    "IncidentAgentAction",
    "IncidentCapaEvidence",
    "IncidentDecisionSummary",
    "IncidentEvidenceEdge",
    "IncidentEvidenceIssue",
    "IncidentEvidenceRef",
    "IncidentHumanDecision",
    "IncidentHypothesis",
    "IncidentKnowledgeReference",
    "IncidentLoopControl",
    "IncidentLoopStep",
    "IncidentLoopStopReason",
    "IncidentOperatorQuestion",
    "IncidentPhaseEvent",
    "IncidentProgressLedger",
    "IncidentRecommendation",
    "IncidentStatus",
    "IncidentTriggerKind",
    "IncidentWorkerReceipt",
    "IncidentWorkerExecutionError",
    "IncidentWorkerRegistry",
    "IndustrialGateContext",
    "IndustrialIncidentCase",
    "IndustrialIncidentDecisionConsumptionReceipt",
    "IndustrialIncidentDecisionReceipt",
    "IndustrialIncidentDecisionRequest",
    "IndustrialIncidentRequest",
    "IndustrialIncidentRequestV1",
    "IndustrialIncidentRequestV2",
    "IndustrialIncidentRequestV3",
    "IndustrialIncidentTrigger",
    "ManufacturingRecordAuthorityStatus",
    "OPCUAMachineVisionContext",
    "OPCUANodeObservation",
    "OPCUAOfflineSnapshot",
    "OPCUASnapshotMode",
    "OPCUAValueSeverity",
    "OfflineVisionRunReceipt",
    "ProcessSignalExpectation",
    "ProductionChangeKind",
    "ProductionChangeRecord",
    "VisionSolutionManifest",
    "build_batch_trace_record",
    "build_incident_decision_consumption_receipt",
    "build_incident_phase_events",
    "build_industrial_incident_case",
    "build_industrial_incident_decision_receipt",
    "build_production_change_record",
    "industrial_incident_evidence_bundle_sha256",
    "industrial_incident_planning_subject_sha256",
    "incident_case_requires_governed_audit_envelope",
    "incident_case_verification_scope",
    "incident_runtime_profile",
    "parse_industrial_incident_case",
    "parse_industrial_incident_case_json",
    "parse_industrial_incident_request",
    "parse_industrial_incident_request_json",
    "reuse_incident_case_verification",
    "verify_batch_trace_record",
    "verify_incident_decision_consumption_receipt",
    "verify_incident_phase_events",
    "verify_incident_worker_receipt",
    "verify_industrial_incident_case",
    "verify_industrial_incident_decision_receipt",
    "verify_production_change_record",
]
