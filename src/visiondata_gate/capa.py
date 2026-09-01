"""Evidence-bound corrective action and child-run recovery contracts.

CAPA artifacts are deliberately separate from the immutable parent task ZIP.
The parent source is read-only.  Approved actions are materialized only in a
private derived version, which can then be evaluated by a normal child task.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
import hashlib
import hmac
import os
from pathlib import Path
import shutil
import tempfile
import time
from typing import Any, Literal
import zipfile

import numpy as np
from pydantic import Field, model_validator

from .contracts import BatchManifest, Finding
from .duplicates import _file_sha256, _perceptual_fingerprint
from .evidence import canonical_json_bytes, sha256_file, write_canonical_json
from .industrial_delivery import (
    IndustrialExecutableWorkOrder,
    IndustrialRemediationPlan,
)
from .omni_adapter import (
    _bucket,
    _discover_dataset_root,
    _gate_measurement_contract,
    _image_size,
    _load_official_counts,
    _metadata_workbook,
    _sample_record,
    _scan_dataset,
    _select_records,
    _validate_source_path,
    profile_omni_source,
)
from .operator_snapshot import (
    OperatorProjectSnapshotReceipt,
    profile_operator_project_snapshot,
)
from .product_models import ProductModel
from .quality import inspect_image_quality


class CapaStatus(str, Enum):
    SELECTED = "SELECTED"
    APPROVED = "APPROVED"
    DERIVED_VERSION_READY = "DERIVED_VERSION_READY"
    CHILD_RUN_COMPLETED = "CHILD_RUN_COMPLETED"
    RECOVERED_TO_HUMAN_REVIEW = "RECOVERED_TO_HUMAN_REVIEW"
    STILL_BLOCKED = "STILL_BLOCKED"
    TRANSFERRED_TO_INVESTIGATION = "TRANSFERRED_TO_INVESTIGATION"


class ResponsibilityStatus(str, Enum):
    OPEN = "OPEN"
    APPROVED_FOR_DERIVED_VERSION = "APPROVED_FOR_DERIVED_VERSION"
    EXECUTED_ON_DERIVED_VERSION = "EXECUTED_ON_DERIVED_VERSION"
    DEFERRED_NOT_SELECTED = "DEFERRED_NOT_SELECTED"
    BLOCKED_NO_REPLACEMENT = "BLOCKED_NO_REPLACEMENT"
    AWAITING_HUMAN_INVESTIGATION = "AWAITING_HUMAN_INVESTIGATION"
    VERIFIED_CLOSED = "VERIFIED_CLOSED"
    RECHECK_FAILED = "RECHECK_FAILED"


class SelectRemediationPlanRequest(ProductModel):
    plan_id: str
    plan_sha256: str
    note: str
    idempotency_key: str | None = Field(
        default=None, pattern=r"^[a-zA-Z0-9_.:-]{8,240}$"
    )


class ApproveRemediationPlanRequest(ProductModel):
    note: str
    approved_work_order_ids: list[str]
    operator_attests_derived_processing: Literal[True]
    source_mutation_permitted: Literal[False] = False
    raw_redistribution_allowed: Literal[False] = False
    max_copied_images: int = Field(default=240, ge=1, le=10_000)


class ExecuteRemediationPlanRequest(ProductModel):
    """Explicit, hash-bound human confirmation for one CAPA execution."""

    reviewer_identity: str = Field(min_length=2, max_length=160)
    note: str = Field(min_length=2, max_length=1000)
    expected_approval_binding_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    operator_attests_derived_processing: Literal[True]
    source_mutation_permitted: Literal[False] = False
    raw_redistribution_allowed: Literal[False] = False


class CapaCaseSelection(ProductModel):
    schema_version: Literal["visiondata-gate.capa-selection.v1"] = (
        "visiondata-gate.capa-selection.v1"
    )
    case_id: str
    parent_task_id: str
    parent_request_sha256: str
    parent_evidence_sha256: str
    industrial_delivery_sha256: str
    plan: IndustrialRemediationPlan
    selected_by: str
    selection_note: str
    created_at: str
    selection_sha256: str


class CapaResponsibilityItem(ProductModel):
    queue_item_id: str
    work_order_id: str
    action: str
    priority: str
    owner_role: str
    required_skill: str
    status: ResponsibilityStatus
    selected: bool
    affected_sample_ids: list[str]
    finding_ids: list[str]
    acceptance_criteria: list[str]
    evidence_refs: list[str]
    result_refs: list[str] = Field(default_factory=list)
    status_reason: str


class CapaResponsibilityQueue(ProductModel):
    schema_version: Literal["visiondata-gate.capa-responsibility-queue.v1"] = (
        "visiondata-gate.capa-responsibility-queue.v1"
    )
    case_id: str
    parent_task_id: str
    phase: Literal["initial", "final"]
    items: list[CapaResponsibilityItem]
    open_count: int
    closed_count: int
    queue_sha256: str
    claim_boundary: str = (
        "Queue states describe this bounded local CAPA case. They are not customer "
        "acceptance, production authorization, or proof of physical recapture."
    )

    @model_validator(mode="after")
    def validate_queue_counts(self) -> CapaResponsibilityQueue:
        open_statuses = {
            ResponsibilityStatus.OPEN,
            ResponsibilityStatus.APPROVED_FOR_DERIVED_VERSION,
            ResponsibilityStatus.DEFERRED_NOT_SELECTED,
            ResponsibilityStatus.BLOCKED_NO_REPLACEMENT,
            ResponsibilityStatus.AWAITING_HUMAN_INVESTIGATION,
            ResponsibilityStatus.RECHECK_FAILED,
        }
        expected_open = sum(item.status in open_statuses for item in self.items)
        expected_closed = len(self.items) - expected_open
        if self.open_count != expected_open or self.closed_count != expected_closed:
            raise ValueError(
                "CAPA responsibility queue counts do not match item states"
            )
        queue_item_ids = [item.queue_item_id for item in self.items]
        work_order_ids = [item.work_order_id for item in self.items]
        if len(queue_item_ids) != len(set(queue_item_ids)):
            raise ValueError("CAPA responsibility queue contains duplicate item IDs")
        if len(work_order_ids) != len(set(work_order_ids)):
            raise ValueError("CAPA responsibility queue contains duplicate work orders")
        return self


class CapaApprovalBinding(ProductModel):
    schema_version: Literal[
        "visiondata-gate.capa-approval-binding.v1",
        "visiondata-gate.capa-approval-binding.v2",
        "visiondata-gate.capa-approval-binding.v3",
    ] = "visiondata-gate.capa-approval-binding.v3"
    case_id: str
    parent_task_id: str
    parent_request_sha256: str
    parent_evidence_sha256: str
    industrial_delivery_sha256: str
    selection_sha256: str
    remediation_plan_id: str
    remediation_plan_sha256: str
    rule_contract_sha256: str
    source_id: str
    source_profile_sha256: str
    source_authorization_event_sha256: str | None = None
    responsibility_queue_sha256: str
    approved_work_order_ids: list[str]
    approved_by: str
    approval_note: str
    operator_attests_derived_processing: Literal[True]
    source_mutation_permitted: Literal[False]
    raw_redistribution_allowed: Literal[False]
    planned_copy_count: int | None = Field(default=None, ge=1)
    max_copied_images: int = Field(ge=1, le=10_000)
    approved_at: str
    binding_sha256: str


class DerivedOperation(ProductModel):
    operation_id: str
    work_order_ids: list[str]
    action: Literal[
        "QUARANTINE_AND_BACKFILL",
        "REPARTITION_BY_BACKFILL",
        "RECONCILE_DERIVED_METADATA",
        "INVESTIGATION_HOLD",
    ]
    status: Literal["EXECUTED", "BLOCKED", "NOT_REQUIRED"]
    before_sample_ids: list[str]
    after_sample_ids: list[str]
    finding_codes: list[str]
    reason: str


class DerivedDataVersionReceipt(ProductModel):
    schema_version: Literal[
        "visiondata-gate.derived-data-version.v1",
        "visiondata-gate.derived-data-version.v2",
    ] = "visiondata-gate.derived-data-version.v2"
    case_id: str
    version_id: str
    parent_task_id: str
    parent_source_id: str
    remediation_plan_id: str
    remediation_plan_sha256: str
    approval_binding_sha256: str
    original_selection_count: int
    derived_image_count: int
    derived_mask_count: int
    operation_count: int
    operations: list[DerivedOperation]
    unresolved_work_order_ids: list[str]
    private_manifest_sha256: str
    derived_content_sha256: str
    derived_source_profile_sha256: str
    root_path_sha256: str
    parent_source_mutated: Literal[False] = False
    source_assets_copied_into_product: Literal[True] = True
    raw_redistribution_allowed: Literal[False] = False
    public_export_allowed: Literal[False] = False
    rollback_strategy: Literal["discard_derived_version"] = "discard_derived_version"
    rollback_point_sha256: str
    publication_mode: Literal["SAME_FILESYSTEM_STAGING_RENAME"] | None = None
    staging_verified_before_publish: Literal[True] | None = None
    publication_atomicity_scope: str | None = None
    created_at: str
    receipt_sha256: str
    claim_boundary: str = (
        "This receipt proves a private bounded derived copy and deterministic data "
        "selection actions. Backfill is not physical recapture, and the version is "
        "not a complete correction of the organizer source or a production release. "
        "Atomic publication covers only the derived-version directory namespace; "
        "source authorization, child execution, and later CAPA receipts are separate "
        "write-once workflow stages."
    )


class CapaExecutionAuthorization(ProductModel):
    schema_version: Literal["visiondata-gate.capa-execution-authorization.v1"] = (
        "visiondata-gate.capa-execution-authorization.v1"
    )
    case_id: str
    parent_task_id: str
    approval_binding_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    actor_user_id: str
    reviewer_identity: str
    execution_note: str
    operator_attests_derived_processing: Literal[True]
    source_mutation_permitted: Literal[False]
    raw_redistribution_allowed: Literal[False]
    authorized_at: str
    authorization_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")


class CapaExecutionReceipt(ProductModel):
    schema_version: Literal[
        "visiondata-gate.capa-execution.v1",
        "visiondata-gate.capa-execution.v2",
    ] = "visiondata-gate.capa-execution.v1"
    case_id: str
    parent_task_id: str
    child_task_id: str
    derived_version_id: str
    derived_source_id: str
    remediation_plan_sha256: str
    capa_approval_binding_sha256: str
    child_plan_approval_binding_sha256: str
    parent_evidence_sha256_before: str
    parent_evidence_sha256_after: str
    parent_source_profile_sha256_before: str
    parent_source_profile_sha256_after: str
    parent_immutable: bool
    child_evidence_sha256: str
    child_lineage_report_sha256: str
    execution_authorization_sha256: str | None = Field(
        default=None, pattern=r"^[0-9a-f]{64}$"
    )
    executed_at: str
    receipt_sha256: str

    @model_validator(mode="after")
    def require_v2_execution_authorization(self) -> "CapaExecutionReceipt":
        if (
            self.schema_version == "visiondata-gate.capa-execution.v2"
            and self.execution_authorization_sha256 is None
        ):
            raise ValueError("CAPA execution v2 requires an authorization digest")
        if (
            self.schema_version == "visiondata-gate.capa-execution.v1"
            and self.execution_authorization_sha256 is not None
        ):
            raise ValueError("CAPA execution v1 cannot carry v2 authorization fields")
        return self


class ChildRunClosureVerification(ProductModel):
    """Atomic code+sample comparison for one same-contract child run.

    Finding IDs include measured values and can legitimately change after a
    recheck.  The comparison therefore expands every finding into stable
    ``code + redacted sample_id`` keys; sampleless governance findings use a
    code-level aggregate key.  This is stronger than comparing code sets while
    remaining honest about the available identity resolution.
    """

    schema_version: Literal["visiondata-gate.child-run-closure-verification.v1"] = (
        "visiondata-gate.child-run-closure-verification.v1"
    )
    identity_scope: Literal["CODE_AND_REDACTED_SAMPLE_ID"] = (
        "CODE_AND_REDACTED_SAMPLE_ID"
    )
    parent_contract_id: str
    child_contract_id: str
    same_contract_verified: Literal[True] = True
    parent_atomic_keys: list[str]
    child_atomic_keys: list[str]
    strictly_closed_keys: list[str]
    persistent_keys: list[str]
    regressed_keys: list[str]
    strictly_closed_count: int = Field(ge=0)
    persistent_count: int = Field(ge=0)
    regressed_count: int = Field(ge=0)
    is_zero_regression: bool
    disposition: Literal[
        "ZERO_REGRESSION_VERIFIED",
        "PERSISTENT_FINDINGS_REMAIN",
        "REGRESSION_DETECTED",
        "GATE_NOT_PASS_WITHOUT_ATOMIC_FINDINGS",
    ]
    parent_evidence_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    child_evidence_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    verification_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    claim_boundary: str = (
        "Zero regression means that this child run introduced no new finding key at "
        "the available code plus redacted-sample identity resolution. It is not a "
        "root-cause proof, full-source certification, or production approval."
    )


def _atomic_finding_keys(findings: list[Finding]) -> set[str]:
    keys: set[str] = set()
    for finding in findings:
        if finding.sample_ids:
            keys.update(
                f"{finding.code}::sample::{sample_id}"
                for sample_id in finding.sample_ids
            )
        else:
            keys.add(f"{finding.code}::aggregate")
    return keys


def verify_child_run_closure(
    *,
    parent_findings: list[Finding],
    child_findings: list[Finding],
    parent_contract_id: str,
    child_contract_id: str,
    child_decision: str,
    parent_evidence_sha256: str,
    child_evidence_sha256: str,
) -> ChildRunClosureVerification:
    """Return a sealed non-regression result; never discard negative evidence."""

    if parent_contract_id != child_contract_id:
        raise ValueError("child-run closure requires the same frozen contract")
    parent_keys = _atomic_finding_keys(parent_findings)
    child_keys = _atomic_finding_keys(child_findings)
    closed = parent_keys - child_keys
    persistent = parent_keys & child_keys
    regressed = child_keys - parent_keys
    zero_regression = not regressed
    if regressed:
        disposition = "REGRESSION_DETECTED"
    elif persistent:
        disposition = "PERSISTENT_FINDINGS_REMAIN"
    elif child_decision == "PASS":
        disposition = "ZERO_REGRESSION_VERIFIED"
    else:
        disposition = "GATE_NOT_PASS_WITHOUT_ATOMIC_FINDINGS"
    stable = {
        "schema_version": "visiondata-gate.child-run-closure-verification.v1",
        "identity_scope": "CODE_AND_REDACTED_SAMPLE_ID",
        "parent_contract_id": parent_contract_id,
        "child_contract_id": child_contract_id,
        "same_contract_verified": True,
        "parent_atomic_keys": sorted(parent_keys),
        "child_atomic_keys": sorted(child_keys),
        "strictly_closed_keys": sorted(closed),
        "persistent_keys": sorted(persistent),
        "regressed_keys": sorted(regressed),
        "strictly_closed_count": len(closed),
        "persistent_count": len(persistent),
        "regressed_count": len(regressed),
        "is_zero_regression": zero_regression,
        "disposition": disposition,
        "parent_evidence_sha256": parent_evidence_sha256,
        "child_evidence_sha256": child_evidence_sha256,
        "claim_boundary": ChildRunClosureVerification.model_fields[
            "claim_boundary"
        ].default,
    }
    return ChildRunClosureVerification(
        **stable,
        verification_sha256=hashlib.sha256(canonical_json_bytes(stable)).hexdigest(),
    )


class CapaRecoveryReceipt(ProductModel):
    schema_version: Literal[
        "visiondata-gate.capa-recovery.v1",
        "visiondata-gate.capa-recovery.v2",
    ] = "visiondata-gate.capa-recovery.v2"
    case_id: str
    parent_task_id: str
    child_task_id: str
    status: Literal[
        "RECOVERED_TO_HUMAN_REVIEW",
        "STILL_BLOCKED",
        "TRANSFERRED_TO_INVESTIGATION",
    ]
    parent_decision: str
    child_decision: str
    parent_finding_count: int = Field(ge=0)
    child_finding_count: int = Field(ge=0)
    parent_finding_codes: list[str]
    child_finding_codes: list[str]
    resolved_finding_codes: list[str]
    new_finding_codes: list[str]
    child_verification: ChildRunClosureVerification | None = None
    selected_work_order_count: int = Field(ge=0)
    verified_closed_work_order_count: int = Field(ge=0)
    remaining_work_order_count: int = Field(ge=0)
    recovery_success: bool
    production_release_allowed: Literal[False] = False
    required_human_action: str
    parent_evidence_sha256: str
    child_evidence_sha256: str
    derived_version_receipt_sha256: str
    responsibility_queue_sha256: str
    recovered_at: str
    receipt_sha256: str
    claim_boundary: str = (
        "A recovered status permits only independent human review. It is not "
        "production approval, customer acceptance, or safety certification."
    )

    @model_validator(mode="after")
    def validate_child_verification(self) -> CapaRecoveryReceipt:
        expected_success_status = self.status == "RECOVERED_TO_HUMAN_REVIEW"
        if self.recovery_success != expected_success_status:
            raise ValueError("CAPA recovery status and success flag diverged")
        if self.verified_closed_work_order_count > self.selected_work_order_count:
            raise ValueError("CAPA recovery closed count exceeds selected work orders")
        parent_codes = set(self.parent_finding_codes)
        child_codes = set(self.child_finding_codes)
        if (
            len(parent_codes) != len(self.parent_finding_codes)
            or len(child_codes) != len(self.child_finding_codes)
            or self.resolved_finding_codes != sorted(parent_codes - child_codes)
            or self.new_finding_codes != sorted(child_codes - parent_codes)
        ):
            raise ValueError("CAPA recovery finding-code deltas do not reconcile")
        verification = self.child_verification
        if verification is None:
            if (
                self.schema_version == "visiondata-gate.capa-recovery.v2"
                or self.recovery_success
            ):
                raise ValueError(
                    "CAPA recovery requires child-run closure verification"
                )
            return self
        payload = verification.model_dump(mode="json", exclude={"verification_sha256"})
        observed = hashlib.sha256(canonical_json_bytes(payload)).hexdigest()
        if not hmac.compare_digest(observed, verification.verification_sha256):
            raise ValueError("child-run closure verification seal mismatch")
        regressed_codes = sorted(
            {key.split("::", 1)[0] for key in verification.regressed_keys}
        )
        if not set(self.new_finding_codes).issubset(regressed_codes):
            raise ValueError("new finding codes are not represented by regression keys")
        if (
            verification.parent_evidence_sha256 != self.parent_evidence_sha256
            or verification.child_evidence_sha256 != self.child_evidence_sha256
        ):
            raise ValueError("CAPA recovery lost child-verification evidence binding")
        expected_success = (
            self.child_decision == "PASS"
            and self.remaining_work_order_count == 0
            and self.verified_closed_work_order_count == self.selected_work_order_count
            and verification.is_zero_regression
        )
        if self.recovery_success != expected_success:
            raise ValueError("CAPA recovery success does not match closure evidence")
        return self


class CapaPlanObservation(ProductModel):
    plan_id: str
    plan_sha256: str
    strategy: Literal[
        "containment_first", "actionable_recovery", "full_evidence_closure"
    ]
    selected: bool
    execution_status: Literal["EXECUTED", "NOT_EXECUTED"]
    selected_work_order_count: int = Field(ge=1)
    deferred_work_order_count: int = Field(ge=0)
    evidence_coverage_ratio: float = Field(ge=0.0, le=1.0)
    relative_effort_points: int = Field(ge=1)
    observed_child_decision: str | None = None
    observed_verified_closed_work_order_count: int | None = Field(default=None, ge=0)
    observed_remaining_work_order_count: int | None = Field(default=None, ge=0)
    production_release_allowed: Literal[False] = False


class CapaOutcomeAssessment(ProductModel):
    """Deterministic feasibility view over candidate plans and one observed run."""

    schema_version: Literal["visiondata-gate.capa-outcome-assessment.v1"] = (
        "visiondata-gate.capa-outcome-assessment.v1"
    )
    case_id: str
    parent_task_id: str
    child_task_id: str
    selected_plan_id: str
    selected_plan_sha256: str
    selected_plan_is_highest_coverage: bool
    plan_observations: list[CapaPlanObservation] = Field(min_length=1)
    release_feasibility_status: Literal[
        "OBSERVED_RECOVERY_TO_HUMAN_REVIEW",
        "NOT_ESTIMABLE_HIGHER_COVERAGE_PLAN_UNEXECUTED",
        "NO_FEASIBLE_RELEASE_OBSERVED_IN_CURRENT_AUTHORIZED_POOL",
    ]
    minimum_observed_relative_effort_points: int | None = Field(default=None, ge=1)
    observed_release_candidate_found: bool
    required_next_action: str
    selection_sha256: str
    approval_binding_sha256: str
    derived_version_receipt_sha256: str
    execution_receipt_sha256: str
    recovery_receipt_sha256: str
    responsibility_queue_sha256: str
    assessment_sha256: str
    claim_boundary: str = (
        "Relative effort points order deterministic candidate plans only; they are "
        "not hours, money, ROI, or a guaranteed minimum cost. Unexecuted plans have "
        "no observed outcome. A child PASS would still require independent human "
        "review and would not itself authorize production release."
    )


class CapaCaseReport(ProductModel):
    schema_version: Literal["visiondata-gate.capa-case.v1"] = (
        "visiondata-gate.capa-case.v1"
    )
    case_id: str
    parent_task_id: str
    status: CapaStatus
    selection: CapaCaseSelection
    approval: CapaApprovalBinding | None = None
    initial_queue: CapaResponsibilityQueue
    execution_authorization: CapaExecutionAuthorization | None = None
    derived_version: DerivedDataVersionReceipt | None = None
    execution: CapaExecutionReceipt | None = None
    final_queue: CapaResponsibilityQueue | None = None
    recovery: CapaRecoveryReceipt | None = None


@dataclass(frozen=True)
class DerivedVersionBuild:
    receipt: DerivedDataVersionReceipt
    derived_root: Path
    source_profile: dict[str, Any]


def seal_model(model_type: type[ProductModel], stable: dict[str, Any], field: str):
    """Instantiate a model whose final field hashes every preceding field."""

    digest = hashlib.sha256(canonical_json_bytes(stable)).hexdigest()
    return model_type(**stable, **{field: digest})


def verify_sealed_model(model: ProductModel, field: str) -> None:
    """Fail closed when a stored CAPA artifact no longer matches its own seal."""

    if field not in type(model).model_fields:
        raise ValueError(f"unknown seal field: {field}")
    expected = getattr(model, field, None)
    if not isinstance(expected, str):
        raise ValueError(f"CAPA seal is missing: {field}")
    payload = model.model_dump(mode="json", exclude={field}, exclude_unset=True)
    observed = hashlib.sha256(canonical_json_bytes(payload)).hexdigest()
    if not hmac.compare_digest(observed, expected):
        raise ValueError(f"CAPA seal mismatch: {field}")


def build_responsibility_queue(
    *,
    case_id: str,
    parent_task_id: str,
    work_orders: list[IndustrialExecutableWorkOrder],
    selected_work_order_ids: list[str],
    phase: Literal["initial", "final"] = "initial",
    status_by_work_order: dict[str, tuple[ResponsibilityStatus, str, list[str]]]
    | None = None,
) -> CapaResponsibilityQueue:
    selected = set(selected_work_order_ids)
    overrides = status_by_work_order or {}
    items: list[CapaResponsibilityItem] = []
    for work_order in sorted(work_orders, key=lambda item: item.work_order_id):
        is_selected = work_order.work_order_id in selected
        if work_order.work_order_id in overrides:
            status, reason, result_refs = overrides[work_order.work_order_id]
        elif is_selected:
            status = ResponsibilityStatus.OPEN
            reason = "等待具名责任人批准后仅在派生版本执行。"
            result_refs = []
        else:
            status = ResponsibilityStatus.DEFERRED_NOT_SELECTED
            reason = "当前方案未选择该原子工单，风险继续保留。"
            result_refs = []
        items.append(
            CapaResponsibilityItem(
                queue_item_id=f"queue-{work_order.work_order_id}",
                work_order_id=work_order.work_order_id,
                action=work_order.action,
                priority=work_order.priority,
                owner_role=work_order.human_owner_role,
                required_skill=work_order.required_skill,
                status=status,
                selected=is_selected,
                affected_sample_ids=sorted(
                    {
                        sample_id
                        for span in work_order.evidence_span
                        for sample_id in span.sample_ids
                    }
                ),
                finding_ids=sorted(
                    {span.finding_id for span in work_order.evidence_span}
                ),
                acceptance_criteria=work_order.acceptance_criteria,
                evidence_refs=work_order.evidence_refs,
                result_refs=result_refs,
                status_reason=reason,
            )
        )
    open_statuses = {
        ResponsibilityStatus.OPEN,
        ResponsibilityStatus.APPROVED_FOR_DERIVED_VERSION,
        ResponsibilityStatus.DEFERRED_NOT_SELECTED,
        ResponsibilityStatus.BLOCKED_NO_REPLACEMENT,
        ResponsibilityStatus.AWAITING_HUMAN_INVESTIGATION,
        ResponsibilityStatus.RECHECK_FAILED,
    }
    stable = {
        "schema_version": "visiondata-gate.capa-responsibility-queue.v1",
        "case_id": case_id,
        "parent_task_id": parent_task_id,
        "phase": phase,
        "items": items,
        "open_count": sum(item.status in open_statuses for item in items),
        "closed_count": sum(item.status not in open_statuses for item in items),
        "claim_boundary": CapaResponsibilityQueue.model_fields[
            "claim_boundary"
        ].default,
    }
    return seal_model(CapaResponsibilityQueue, stable, "queue_sha256")


def build_capa_outcome_assessment(
    report: CapaCaseReport,
    plans: list[IndustrialRemediationPlan],
) -> CapaOutcomeAssessment:
    """Describe what was actually executed and whether a release path was observed."""

    if not (
        report.approval is not None
        and report.derived_version is not None
        and report.execution is not None
        and report.final_queue is not None
        and report.recovery is not None
    ):
        raise ValueError("CAPA outcome assessment requires a completed child Run")
    selected = report.selection.plan
    matching = [item for item in plans if item.plan_sha256 == selected.plan_sha256]
    if len(matching) != 1:
        raise ValueError("selected CAPA plan is not unique in parent evidence")
    if len({item.plan_sha256 for item in plans}) != len(plans):
        raise ValueError("CAPA candidate plans contain duplicate hashes")
    highest_coverage = max(item.evidence_coverage_ratio for item in plans)
    selected_is_highest = selected.evidence_coverage_ratio == highest_coverage

    observations = [
        CapaPlanObservation(
            plan_id=plan.plan_id,
            plan_sha256=plan.plan_sha256,
            strategy=plan.strategy,
            selected=plan.plan_sha256 == selected.plan_sha256,
            execution_status=(
                "EXECUTED"
                if plan.plan_sha256 == selected.plan_sha256
                else "NOT_EXECUTED"
            ),
            selected_work_order_count=len(plan.selected_work_order_ids),
            deferred_work_order_count=len(plan.deferred_work_order_ids),
            evidence_coverage_ratio=plan.evidence_coverage_ratio,
            relative_effort_points=plan.relative_effort_points,
            observed_child_decision=(
                report.recovery.child_decision
                if plan.plan_sha256 == selected.plan_sha256
                else None
            ),
            observed_verified_closed_work_order_count=(
                report.recovery.verified_closed_work_order_count
                if plan.plan_sha256 == selected.plan_sha256
                else None
            ),
            observed_remaining_work_order_count=(
                report.recovery.remaining_work_order_count
                if plan.plan_sha256 == selected.plan_sha256
                else None
            ),
            production_release_allowed=False,
        )
        for plan in plans
    ]
    if report.recovery.recovery_success:
        feasibility = "OBSERVED_RECOVERY_TO_HUMAN_REVIEW"
        minimum_effort = selected.relative_effort_points
        next_action = (
            "由具名质量责任人独立核验 child Evidence 后，再决定是否进入企业放行流程。"
        )
    elif selected_is_highest:
        feasibility = "NO_FEASIBLE_RELEASE_OBSERVED_IN_CURRENT_AUTHORIZED_POOL"
        minimum_effort = None
        next_action = (
            "扩大授权候选池、执行物理重采或完成人工根因调查；不得把相对 effort "
            "换算为虚构工时、金额或自动继续放行。"
        )
    else:
        feasibility = "NOT_ESTIMABLE_HIGHER_COVERAGE_PLAN_UNEXECUTED"
        minimum_effort = None
        next_action = (
            "由具名责任人决定是否批准更高覆盖方案；未执行方案不得填入成功率或成本。"
        )
    stable = {
        "schema_version": "visiondata-gate.capa-outcome-assessment.v1",
        "case_id": report.case_id,
        "parent_task_id": report.parent_task_id,
        "child_task_id": report.execution.child_task_id,
        "selected_plan_id": selected.plan_id,
        "selected_plan_sha256": selected.plan_sha256,
        "selected_plan_is_highest_coverage": selected_is_highest,
        "plan_observations": observations,
        "release_feasibility_status": feasibility,
        "minimum_observed_relative_effort_points": minimum_effort,
        "observed_release_candidate_found": report.recovery.recovery_success,
        "required_next_action": next_action,
        "selection_sha256": report.selection.selection_sha256,
        "approval_binding_sha256": report.approval.binding_sha256,
        "derived_version_receipt_sha256": report.derived_version.receipt_sha256,
        "execution_receipt_sha256": report.execution.receipt_sha256,
        "recovery_receipt_sha256": report.recovery.receipt_sha256,
        "responsibility_queue_sha256": report.final_queue.queue_sha256,
        "claim_boundary": CapaOutcomeAssessment.model_fields["claim_boundary"].default,
    }
    return seal_model(CapaOutcomeAssessment, stable, "assessment_sha256")


def _quality_passes(dataset_root: Path, record: Any, *, seed: int) -> bool:
    size = _image_size(record.path, source_root=dataset_root)
    if size is None:
        return False
    sample = _sample_record(record, seed=seed)
    manifest = BatchManifest(
        batch_id=f"capa-candidate-{sample.sample_id}", seed=seed, samples=[sample]
    )
    findings, _ = inspect_image_quality(
        dataset_root,
        manifest,
        _gate_measurement_contract(width=size[0], height=size[1]),
    )
    return not findings


def _cached_fingerprint(
    record: Any,
    cache: dict[str, tuple[str, int, np.ndarray]],
) -> tuple[str, int, np.ndarray]:
    key = record.relative_path
    cached = cache.get(key)
    if cached is not None:
        return cached
    source = _validate_source_path(
        record.path,
        source_root=record.source_root,
        expected="file",
    )
    file_sha256 = _file_sha256(source)
    difference_hash, thumbnail, _ = _perceptual_fingerprint(source)
    cached = (file_sha256, difference_hash, thumbnail)
    cache[key] = cached
    return cached


def _duplicate_safe(
    candidate: Any,
    others: list[Any],
    *,
    fingerprint_cache: dict[str, tuple[str, int, np.ndarray]],
) -> bool:
    candidate_sha, candidate_hash, candidate_thumb = _cached_fingerprint(
        candidate, fingerprint_cache
    )
    for other in others:
        other_sha, other_hash, other_thumb = _cached_fingerprint(
            other, fingerprint_cache
        )
        if candidate_sha == other_sha:
            return False
        if candidate.split == other.split:
            continue
        if (candidate_hash ^ other_hash).bit_count() > 4:
            continue
        mean_abs_difference = float(
            np.mean(np.abs(candidate_thumb - other_thumb), dtype=np.float64)
        )
        if mean_abs_difference <= 1.0:
            return False
    return True


def _write_metadata(path: Path, records: list[Any]) -> None:
    headers = ["数据集名称", "样本总数", "good(train)", "good(test)", "NG(test)"]
    by_category: dict[str, dict[str, int]] = {}
    for record in records:
        counts = by_category.setdefault(
            record.category,
            {"total": 0, "train_good": 0, "test_good": 0, "test_anomaly": 0},
        )
        counts["total"] += 1
        counts[_bucket(record)] += 1

    def cell(column: str, row: int, value: str | int) -> str:
        if isinstance(value, int):
            return f'<c r="{column}{row}"><v>{value}</v></c>'
        escaped = value.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
        return f'<c r="{column}{row}" t="inlineStr"><is><t>{escaped}</t></is></c>'

    columns = ["A", "B", "C", "D", "E"]
    rows = [
        '<row r="1">'
        + "".join(
            cell(column, 1, value)
            for column, value in zip(columns, headers, strict=True)
        )
        + "</row>"
    ]
    for row_index, category in enumerate(sorted(by_category), start=2):
        counts = by_category[category]
        values: list[str | int] = [
            category,
            counts["total"],
            counts["train_good"],
            counts["test_good"],
            counts["test_anomaly"],
        ]
        rows.append(
            f'<row r="{row_index}">'
            + "".join(
                cell(column, row_index, value)
                for column, value in zip(columns, values, strict=True)
            )
            + "</row>"
        )
    sheet = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">'
        "<sheetData>" + "".join(rows) + "</sheetData></worksheet>"
    )
    path.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(path, "x") as bundle:
        bundle.writestr("xl/worksheets/sheet1.xml", sheet)


def _copy_record(
    dataset_root: Path, derived_root: Path, record: Any
) -> tuple[int, int]:
    source = _validate_source_path(
        record.path,
        source_root=dataset_root,
        expected="file",
    )
    destination = (derived_root / record.relative_path).resolve(strict=False)
    destination.relative_to(derived_root)
    destination.parent.mkdir(parents=True, exist_ok=True)
    if destination.exists():
        raise FileExistsError(destination)
    shutil.copy2(source, destination)
    masks = 0
    if record.annotation_path is not None:
        mask_source = _validate_source_path(
            dataset_root / record.annotation_path,
            source_root=dataset_root,
            expected="file",
        )
        mask_destination = (derived_root / record.annotation_path).resolve(strict=False)
        mask_destination.relative_to(derived_root)
        mask_destination.parent.mkdir(parents=True, exist_ok=True)
        if mask_destination.exists():
            raise FileExistsError(mask_destination)
        shutil.copy2(mask_source, mask_destination)
        masks = 1
    return 1, masks


def _publish_staged_version(staging: Path, destination: Path) -> None:
    """Publish one complete same-filesystem version tree in one rename.

    The bounded retry covers the transient Windows ``ERROR_ACCESS_DENIED`` case
    caused by antivirus/indexers. It never overwrites an existing destination.
    """

    attempts = 5 if os.name == "nt" else 1
    for attempt in range(attempts):
        if destination.exists() or destination.is_symlink():
            raise FileExistsError("derived version root already exists")
        try:
            os.rename(staging, destination)
            return
        except PermissionError as error:
            if os.name != "nt" or getattr(error, "winerror", None) != 5:
                raise
            if attempt == attempts - 1:
                raise RuntimeError(
                    "atomic derived-version publication remained unavailable after "
                    "bounded Windows retries"
                ) from error
            time.sleep(0.05 * (attempt + 1))


def build_operator_snapshot_derived_version(
    *,
    source_root: str | Path,
    output_version_root: str | Path,
    parent_source_id: str,
    parent_source_archive_sha256: str,
    parent_task_id: str,
    case_id: str,
    version_id: str,
    plan: IndustrialRemediationPlan,
    approval: CapaApprovalBinding,
    work_orders: list[IndustrialExecutableWorkOrder],
    created_at: str,
) -> DerivedVersionBuild:
    """Clone one immutable Operator snapshot without inventing repair evidence.

    A workbook snapshot contains only assets explicitly frozen by the operator.  It
    has no larger authorized candidate pool from which a blurred or mislabeled sample
    can be silently replaced.  The derived copy can still enter a same-contract Child
    Run, while every selected corrective action remains open until independently
    authorized replacement evidence exists.
    """

    frozen_root = Path(source_root).expanduser().resolve(strict=True)
    frozen_profile = profile_operator_project_snapshot(
        frozen_root,
        expected_receipt_sha256=parent_source_archive_sha256,
    )
    snapshot_receipt_path = frozen_root / "operator_project_snapshot_receipt.json"
    snapshot_receipt = OperatorProjectSnapshotReceipt.model_validate_json(
        snapshot_receipt_path.read_bytes()
    )
    if snapshot_receipt.asset_count > approval.max_copied_images:
        raise ValueError(
            "derived image copy budget is smaller than the frozen Gate selection"
        )
    if (
        approval.planned_copy_count is not None
        and snapshot_receipt.asset_count != approval.planned_copy_count
    ):
        raise ValueError("frozen Gate selection count changed after CAPA approval")
    if approval.approved_work_order_ids != plan.selected_work_order_ids:
        raise ValueError("approval does not cover the exact selected work-order set")

    order_by_id = {item.work_order_id: item for item in work_orders}
    try:
        selected_orders = [order_by_id[item] for item in plan.selected_work_order_ids]
    except KeyError as error:
        raise ValueError("selected CAPA work order is unavailable") from error
    operations: list[DerivedOperation] = []
    unresolved_ids: list[str] = []
    for order in selected_orders:
        sample_ids = sorted(
            {sample_id for span in order.evidence_span for sample_id in span.sample_ids}
        )
        codes = sorted({span.code for span in order.evidence_span})
        unresolved_ids.append(order.work_order_id)
        operations.append(
            DerivedOperation(
                operation_id=f"op-evidence-hold-{order.work_order_id}",
                work_order_ids=[order.work_order_id],
                action="INVESTIGATION_HOLD",
                status="BLOCKED",
                before_sample_ids=sample_ids,
                after_sample_ids=[],
                finding_codes=codes,
                reason=(
                    "当前冻结工作簿没有独立授权的替换图像或标注修订；系统只创建"
                    "派生副本并保留责任项，不合成物理重采结果，也不覆盖 Parent。"
                ),
            )
        )

    final_version_root = Path(output_version_root).expanduser().resolve(strict=False)
    final_source_root = final_version_root / snapshot_receipt.snapshot_id
    publish_parent = final_version_root.parent
    if final_version_root.exists() or final_version_root.is_symlink():
        raise FileExistsError("derived version root already exists")
    publish_parent.mkdir(parents=True, exist_ok=True)
    publish_parent = publish_parent.resolve(strict=True)
    final_version_root.relative_to(publish_parent)
    staging_version_root = Path(
        tempfile.mkdtemp(prefix=f".{version_id}.staging-", dir=publish_parent)
    ).resolve(strict=True)
    staging_source_root = staging_version_root / snapshot_receipt.snapshot_id
    staging_source_root.mkdir(parents=False, exist_ok=False)

    try:
        members = {
            "operator_project_snapshot_receipt.json",
            snapshot_receipt.batch_manifest_relative_path,
            snapshot_receipt.batch_contract_relative_path,
        }
        for asset in snapshot_receipt.assets:
            members.add(asset.source_relative_path)
            members.add(asset.preview_relative_path)
            if asset.mask_relative_path is not None:
                members.add(asset.mask_relative_path)
        for relative in sorted(members):
            normalized = relative.replace("\\", "/")
            if normalized.startswith("/") or ".." in normalized.split("/"):
                raise ValueError("operator snapshot member path is unsafe")
            source_member = frozen_root.joinpath(*normalized.split("/")).resolve(
                strict=True
            )
            source_member.relative_to(frozen_root)
            if not source_member.is_file() or source_member.is_symlink():
                raise ValueError("operator snapshot member is unavailable")
            target_member = staging_source_root.joinpath(*normalized.split("/"))
            target_member.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(source_member, target_member)
            if not hmac.compare_digest(
                sha256_file(source_member), sha256_file(target_member)
            ):
                raise ValueError("operator snapshot copy failed digest verification")

        observed_profile = profile_operator_project_snapshot(
            staging_source_root,
            expected_receipt_sha256=parent_source_archive_sha256,
        )
        if not hmac.compare_digest(
            str(observed_profile["profile_sha256"]),
            str(frozen_profile["profile_sha256"]),
        ):
            raise ValueError("operator snapshot profile changed during derived copy")

        private_manifest = {
            "schema_version": "visiondata-gate.private-operator-derived-manifest.v1",
            "case_id": case_id,
            "version_id": version_id,
            "parent_task_id": parent_task_id,
            "parent_source_id": parent_source_id,
            "operator_snapshot_receipt_sha256": snapshot_receipt.receipt_sha256,
            "copy_mode": "frozen_snapshot_clone_no_automatic_remediation",
            "asset_bindings": [
                {
                    "asset_id": asset.asset_id,
                    "source_sha256": asset.source_sha256,
                    "annotation_document_sha256": (asset.annotation_document_sha256),
                    "mask_sha256": asset.mask_sha256,
                }
                for asset in snapshot_receipt.assets
            ],
            "operations": [item.model_dump(mode="json") for item in operations],
            "unresolved_work_order_ids": sorted(unresolved_ids),
            "raw_redistribution_allowed": False,
            "production_release_allowed": False,
        }
        manifest_path = staging_version_root / "private_manifest.json"
        private_manifest_sha256 = write_canonical_json(manifest_path, private_manifest)
        derived_content_sha256 = hashlib.sha256(
            canonical_json_bytes(
                {
                    "private_manifest_sha256": private_manifest_sha256,
                    "parent_source_archive_sha256": parent_source_archive_sha256,
                    "plan_sha256": plan.plan_sha256,
                    "operator_snapshot_receipt_sha256": (
                        snapshot_receipt.receipt_sha256
                    ),
                }
            )
        ).hexdigest()
        source_profile = dict(observed_profile)
        source_profile.pop("profile_sha256", None)
        source_profile.update(
            {
                "source_assets_copied_into_product": True,
                "derived_version_id": version_id,
                "derived_from_source_id": parent_source_id,
                "derived_manifest_sha256": private_manifest_sha256,
            }
        )
        source_profile["profile_sha256"] = hashlib.sha256(
            canonical_json_bytes(source_profile)
        ).hexdigest()
        normalized_path = str(final_source_root).casefold().replace("\\", "/")
        root_path_sha256 = hashlib.sha256(normalized_path.encode("utf-8")).hexdigest()
        rollback_point_sha256 = hashlib.sha256(
            canonical_json_bytes(
                {
                    "parent_source_id": parent_source_id,
                    "parent_source_archive_sha256": parent_source_archive_sha256,
                    "parent_task_id": parent_task_id,
                    "parent_evidence_sha256": approval.parent_evidence_sha256,
                    "strategy": "discard_derived_version",
                }
            )
        ).hexdigest()
        stable = {
            "schema_version": "visiondata-gate.derived-data-version.v2",
            "case_id": case_id,
            "version_id": version_id,
            "parent_task_id": parent_task_id,
            "parent_source_id": parent_source_id,
            "remediation_plan_id": plan.plan_id,
            "remediation_plan_sha256": plan.plan_sha256,
            "approval_binding_sha256": approval.binding_sha256,
            "original_selection_count": snapshot_receipt.asset_count,
            "derived_image_count": snapshot_receipt.asset_count,
            "derived_mask_count": sum(
                asset.mask_relative_path is not None
                for asset in snapshot_receipt.assets
            ),
            "operation_count": len(operations),
            "operations": operations,
            "unresolved_work_order_ids": sorted(unresolved_ids),
            "private_manifest_sha256": private_manifest_sha256,
            "derived_content_sha256": derived_content_sha256,
            "derived_source_profile_sha256": source_profile["profile_sha256"],
            "root_path_sha256": root_path_sha256,
            "parent_source_mutated": False,
            "source_assets_copied_into_product": True,
            "raw_redistribution_allowed": False,
            "public_export_allowed": False,
            "rollback_strategy": "discard_derived_version",
            "rollback_point_sha256": rollback_point_sha256,
            "publication_mode": "SAME_FILESYSTEM_STAGING_RENAME",
            "staging_verified_before_publish": True,
            "publication_atomicity_scope": ("DERIVED_VERSION_DIRECTORY_NAMESPACE_ONLY"),
            "created_at": created_at,
            "claim_boundary": DerivedDataVersionReceipt.model_fields[
                "claim_boundary"
            ].default,
        }
        receipt = seal_model(DerivedDataVersionReceipt, stable, "receipt_sha256")
        receipt_path = staging_version_root / "derived_version_receipt.json"
        write_canonical_json(receipt_path, receipt)
        if not hmac.compare_digest(sha256_file(manifest_path), private_manifest_sha256):
            raise ValueError("staged private manifest failed integrity validation")
        staged_receipt = DerivedDataVersionReceipt.model_validate_json(
            receipt_path.read_text(encoding="utf-8")
        )
        verify_sealed_model(staged_receipt, "receipt_sha256")
        if canonical_json_bytes(staged_receipt) != canonical_json_bytes(receipt):
            raise ValueError("staged derived-version receipt changed before publish")

        _publish_staged_version(staging_version_root, final_version_root)
        return DerivedVersionBuild(
            receipt=receipt,
            derived_root=final_source_root,
            source_profile=source_profile,
        )
    finally:
        if staging_version_root.exists():
            staging_version_root.relative_to(publish_parent)
            if staging_version_root.name.startswith(f".{version_id}.staging-"):
                shutil.rmtree(staging_version_root)


def build_omni_derived_version(
    *,
    source_root: str | Path,
    output_root: str | Path,
    parent_source_id: str,
    parent_source_archive_sha256: str,
    parent_task_id: str,
    case_id: str,
    version_id: str,
    plan: IndustrialRemediationPlan,
    approval: CapaApprovalBinding,
    work_orders: list[IndustrialExecutableWorkOrder],
    seed: int,
    created_at: str,
) -> DerivedVersionBuild:
    """Create one bounded private copy; never mutate the authorized source tree."""

    dataset_root = _discover_dataset_root(source_root)
    metadata_path = _metadata_workbook(dataset_root)
    official_counts = _load_official_counts(metadata_path)
    records, _ = _scan_dataset(dataset_root, official_counts)
    original_selected, _ = _select_records(records, per_bucket=2, seed=seed)
    if len(original_selected) > approval.max_copied_images:
        raise ValueError(
            "derived image copy budget is smaller than the frozen Gate selection"
        )
    if (
        approval.planned_copy_count is not None
        and len(original_selected) != approval.planned_copy_count
    ):
        raise ValueError("frozen Gate selection count changed after CAPA approval")
    original_samples = [
        _sample_record(record, seed=seed) for record in original_selected
    ]
    record_by_sample_id = {
        sample.sample_id: record
        for sample, record in zip(original_samples, original_selected, strict=True)
    }
    order_by_id = {item.work_order_id: item for item in work_orders}
    selected_orders = [order_by_id[item] for item in plan.selected_work_order_ids]
    if approval.approved_work_order_ids != plan.selected_work_order_ids:
        raise ValueError("approval does not cover the exact selected work-order set")

    work_orders_by_sample: dict[str, list[IndustrialExecutableWorkOrder]] = {}
    metadata_orders: list[IndustrialExecutableWorkOrder] = []
    unresolved_ids: set[str] = set()
    operations: list[DerivedOperation] = []
    for order in selected_orders:
        sample_ids = sorted(
            {sample_id for span in order.evidence_span for sample_id in span.sample_ids}
        )
        codes = sorted({span.code for span in order.evidence_span})
        if sample_ids:
            for sample_id in sample_ids:
                work_orders_by_sample.setdefault(sample_id, []).append(order)
        elif "METADATA_COUNT_DRIFT" in codes:
            metadata_orders.append(order)
        else:
            unresolved_ids.add(order.work_order_id)
            operations.append(
                DerivedOperation(
                    operation_id=f"op-hold-{order.work_order_id}",
                    work_order_ids=[order.work_order_id],
                    action="INVESTIGATION_HOLD",
                    status="BLOCKED",
                    before_sample_ids=[],
                    after_sample_ids=[],
                    finding_codes=codes,
                    reason="该调查项没有可执行样本范围，必须由责任人补充证据。",
                )
            )

    final_records = list(original_selected)
    used_paths = {record.relative_path for record in final_records}
    quality_cache: dict[str, bool] = {}
    fingerprint_cache: dict[str, tuple[str, int, np.ndarray]] = {}
    candidate_groups: dict[tuple[str, str], list[Any]] = {}
    for record in records:
        candidate_groups.setdefault((record.category, _bucket(record)), []).append(
            record
        )
    for candidates in candidate_groups.values():
        candidates.sort(
            key=lambda item: hashlib.sha256(
                f"{seed}\0{item.relative_path}".encode("utf-8")
            ).hexdigest()
        )

    for sample_id in sorted(work_orders_by_sample):
        orders = work_orders_by_sample[sample_id]
        current = record_by_sample_id.get(sample_id)
        order_ids = sorted({order.work_order_id for order in orders})
        codes = sorted({span.code for order in orders for span in order.evidence_span})
        if current is None:
            unresolved_ids.update(order_ids)
            operations.append(
                DerivedOperation(
                    operation_id=f"op-missing-{sample_id}",
                    work_order_ids=order_ids,
                    action="INVESTIGATION_HOLD",
                    status="BLOCKED",
                    before_sample_ids=[sample_id],
                    after_sample_ids=[],
                    finding_codes=codes,
                    reason="父 Run 的脱敏 sample ID 无法映射到当前冻结选择，失败关闭。",
                )
            )
            continue
        index = final_records.index(current)
        other_records = [
            item for offset, item in enumerate(final_records) if offset != index
        ]
        replacement = None
        for candidate in candidate_groups[(current.category, _bucket(current))]:
            if candidate.relative_path in used_paths:
                continue
            if (
                candidate.annotation_path is not None
                and not (dataset_root / candidate.annotation_path).is_file()
            ):
                continue
            quality_ok = quality_cache.get(candidate.relative_path)
            if quality_ok is None:
                quality_ok = _quality_passes(dataset_root, candidate, seed=seed)
                quality_cache[candidate.relative_path] = quality_ok
            if not quality_ok:
                continue
            if not _duplicate_safe(
                candidate,
                other_records,
                fingerprint_cache=fingerprint_cache,
            ):
                continue
            replacement = candidate
            break
        action = (
            "REPARTITION_BY_BACKFILL"
            if any(order.action == "REMOVE_OR_REPARTITION" for order in orders)
            else "QUARANTINE_AND_BACKFILL"
        )
        if replacement is None:
            unresolved_ids.update(order_ids)
            operations.append(
                DerivedOperation(
                    operation_id=f"op-blocked-{sample_id}",
                    work_order_ids=order_ids,
                    action=action,
                    status="BLOCKED",
                    before_sample_ids=[sample_id],
                    after_sample_ids=[],
                    finding_codes=codes,
                    reason="同类别、同桶内没有满足冻结质量与去重约束的候选替换。",
                )
            )
            continue
        final_records[index] = replacement
        used_paths.remove(current.relative_path)
        used_paths.add(replacement.relative_path)
        replacement_sample = _sample_record(replacement, seed=seed)
        operations.append(
            DerivedOperation(
                operation_id=f"op-backfill-{sample_id}",
                work_order_ids=order_ids,
                action=action,
                status="EXECUTED",
                before_sample_ids=[sample_id],
                after_sample_ids=[replacement_sample.sample_id],
                finding_codes=codes,
                reason=(
                    "原样本仅在派生版本隔离，并以同类别、同桶、通过冻结质量和去重规则的"
                    "现有授权候选回填；这不是物理重采。"
                ),
            )
        )

    if metadata_orders:
        operations.append(
            DerivedOperation(
                operation_id="op-derived-metadata-reconcile",
                work_order_ids=sorted(order.work_order_id for order in metadata_orders),
                action="RECONCILE_DERIVED_METADATA",
                status="EXECUTED",
                before_sample_ids=[],
                after_sample_ids=[],
                finding_codes=["METADATA_COUNT_DRIFT"],
                reason="派生版本 metadata 按实际派生资产重新计数，不修改父来源工作簿。",
            )
        )

    final_source_root = Path(output_root).expanduser().resolve(strict=False)
    final_version_root = final_source_root.parent
    publish_parent = final_version_root.parent
    if final_version_root.exists() or final_version_root.is_symlink():
        raise FileExistsError("derived version root already exists")
    publish_parent.mkdir(parents=True, exist_ok=True)
    publish_parent = publish_parent.resolve(strict=True)
    final_version_root.relative_to(publish_parent)
    staging_version_root = Path(
        tempfile.mkdtemp(prefix=f".{version_id}.staging-", dir=publish_parent)
    ).resolve(strict=True)
    staging_source_root = staging_version_root / final_source_root.name
    staging_source_root.mkdir(parents=False, exist_ok=False)

    try:
        image_count = 0
        mask_count = 0
        private_assets: list[dict[str, Any]] = []
        for record in sorted(final_records, key=lambda item: item.relative_path):
            copied_images, copied_masks = _copy_record(
                dataset_root, staging_source_root, record
            )
            image_count += copied_images
            mask_count += copied_masks
            sample = _sample_record(record, seed=seed)
            private_assets.append(
                {
                    "sample_id": sample.sample_id,
                    "relative_path": record.relative_path,
                    "image_sha256": sha256_file(
                        staging_source_root / record.relative_path
                    ),
                    "annotation_relative_path": record.annotation_path,
                    "annotation_sha256": (
                        sha256_file(staging_source_root / record.annotation_path)
                        if record.annotation_path is not None
                        else None
                    ),
                }
            )
        _write_metadata(staging_source_root / "derived_official.xlsx", final_records)
        private_manifest = {
            "schema_version": "visiondata-gate.private-derived-manifest.v1",
            "case_id": case_id,
            "version_id": version_id,
            "parent_task_id": parent_task_id,
            "parent_source_id": parent_source_id,
            "seed": seed,
            "assets": private_assets,
            "metadata_sha256": sha256_file(
                staging_source_root / "derived_official.xlsx"
            ),
            "raw_redistribution_allowed": False,
        }
        manifest_path = staging_version_root / "private_manifest.json"
        private_manifest_sha256 = write_canonical_json(manifest_path, private_manifest)
        derived_content_sha256 = hashlib.sha256(
            canonical_json_bytes(
                {
                    "private_manifest_sha256": private_manifest_sha256,
                    "parent_source_archive_sha256": parent_source_archive_sha256,
                    "plan_sha256": plan.plan_sha256,
                }
            )
        ).hexdigest()
        profile = profile_omni_source(
            staging_source_root, source_archive_sha256=derived_content_sha256
        )
        profile.pop("profile_sha256", None)
        profile.update(
            {
                "source_assets_copied_into_product": True,
                "derived_version_id": version_id,
                "derived_from_source_id": parent_source_id,
                "derived_manifest_sha256": private_manifest_sha256,
            }
        )
        profile["profile_sha256"] = hashlib.sha256(
            canonical_json_bytes(profile)
        ).hexdigest()
        normalized_path = str(final_source_root).casefold().replace("\\", "/")
        root_path_sha256 = hashlib.sha256(normalized_path.encode("utf-8")).hexdigest()
        rollback_point_sha256 = hashlib.sha256(
            canonical_json_bytes(
                {
                    "parent_source_id": parent_source_id,
                    "parent_source_archive_sha256": parent_source_archive_sha256,
                    "parent_task_id": parent_task_id,
                    "parent_evidence_sha256": approval.parent_evidence_sha256,
                    "strategy": "discard_derived_version",
                }
            )
        ).hexdigest()
        stable = {
            "schema_version": "visiondata-gate.derived-data-version.v2",
            "case_id": case_id,
            "version_id": version_id,
            "parent_task_id": parent_task_id,
            "parent_source_id": parent_source_id,
            "remediation_plan_id": plan.plan_id,
            "remediation_plan_sha256": plan.plan_sha256,
            "approval_binding_sha256": approval.binding_sha256,
            "original_selection_count": len(original_selected),
            "derived_image_count": image_count,
            "derived_mask_count": mask_count,
            "operation_count": len(operations),
            "operations": operations,
            "unresolved_work_order_ids": sorted(unresolved_ids),
            "private_manifest_sha256": private_manifest_sha256,
            "derived_content_sha256": derived_content_sha256,
            "derived_source_profile_sha256": profile["profile_sha256"],
            "root_path_sha256": root_path_sha256,
            "parent_source_mutated": False,
            "source_assets_copied_into_product": True,
            "raw_redistribution_allowed": False,
            "public_export_allowed": False,
            "rollback_strategy": "discard_derived_version",
            "rollback_point_sha256": rollback_point_sha256,
            "publication_mode": "SAME_FILESYSTEM_STAGING_RENAME",
            "staging_verified_before_publish": True,
            "publication_atomicity_scope": ("DERIVED_VERSION_DIRECTORY_NAMESPACE_ONLY"),
            "created_at": created_at,
            "claim_boundary": DerivedDataVersionReceipt.model_fields[
                "claim_boundary"
            ].default,
        }
        receipt = seal_model(DerivedDataVersionReceipt, stable, "receipt_sha256")
        receipt_path = staging_version_root / "derived_version_receipt.json"
        write_canonical_json(receipt_path, receipt)

        # Re-read the completed staging artifacts before exposing their path.
        if not hmac.compare_digest(sha256_file(manifest_path), private_manifest_sha256):
            raise ValueError("staged private manifest failed integrity validation")
        staged_receipt = DerivedDataVersionReceipt.model_validate_json(
            receipt_path.read_text(encoding="utf-8")
        )
        verify_sealed_model(staged_receipt, "receipt_sha256")
        if canonical_json_bytes(staged_receipt) != canonical_json_bytes(receipt):
            raise ValueError("staged derived-version receipt changed before publish")

        _publish_staged_version(staging_version_root, final_version_root)
        return DerivedVersionBuild(
            receipt=receipt,
            derived_root=final_source_root,
            source_profile=profile,
        )
    finally:
        if staging_version_root.exists():
            # This exact path was created by mkdtemp inside the resolved publish
            # parent; never broaden cleanup beyond that generated staging tree.
            staging_version_root.relative_to(publish_parent)
            if staging_version_root.name.startswith(f".{version_id}.staging-"):
                shutil.rmtree(staging_version_root)


__all__ = [
    "ApproveRemediationPlanRequest",
    "CapaApprovalBinding",
    "CapaCaseReport",
    "CapaCaseSelection",
    "CapaExecutionAuthorization",
    "CapaExecutionReceipt",
    "CapaOutcomeAssessment",
    "CapaPlanObservation",
    "CapaRecoveryReceipt",
    "CapaResponsibilityQueue",
    "CapaStatus",
    "ChildRunClosureVerification",
    "DerivedDataVersionReceipt",
    "DerivedOperation",
    "DerivedVersionBuild",
    "ExecuteRemediationPlanRequest",
    "ResponsibilityStatus",
    "SelectRemediationPlanRequest",
    "build_operator_snapshot_derived_version",
    "build_omni_derived_version",
    "build_capa_outcome_assessment",
    "build_responsibility_queue",
    "seal_model",
    "verify_child_run_closure",
    "verify_sealed_model",
]
