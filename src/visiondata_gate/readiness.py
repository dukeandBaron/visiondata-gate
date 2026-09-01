"""Live control-gate reports for task execution and production handoff.

These reports are deliberately separate from the immutable run evidence ZIP.  A
run proves what was observed at execution time; readiness re-checks the current
product state before a human starts or relies on that run.
"""

from __future__ import annotations

import hashlib
from typing import Literal

from pydantic import Field

from .evidence import canonical_json_bytes
from .product_models import ProductModel, TaskExecutionStatus


class ReadinessCheck(ProductModel):
    """One independently inspectable prerequisite in a live control gate."""

    key: str = Field(min_length=1)
    label: str = Field(min_length=1)
    status: Literal["PASS", "PENDING", "BLOCKED", "NOT_APPLICABLE"]
    summary: str = Field(min_length=1)
    evidence_ref: str = Field(min_length=1)
    evidence_sha256: str | None = Field(default=None, pattern=r"^[0-9a-f]{64}$")


class TaskPreflightReport(ProductModel):
    """Run-before-readiness report that never exposes a server-local path."""

    schema_version: Literal[
        "visiondata-gate.task-preflight.v1",
        "visiondata-gate.task-preflight.v2",
        "visiondata-gate.task-preflight.v3",
    ] = "visiondata-gate.task-preflight.v3"
    task_id: str = Field(min_length=1)
    source_id: str | None = Field(default=None, min_length=1)
    source_binding_sha256: str | None = Field(default=None, pattern=r"^[0-9a-f]{64}$")
    lifecycle_status: TaskExecutionStatus
    overall_status: Literal[
        "READY_TO_RUN",
        "AWAITING_HUMAN_APPROVAL",
        "BLOCKED",
        "NOT_RUNNABLE",
    ]
    prerequisite_ready: bool
    execution_ready: bool
    source_profile_status: Literal[
        "MATCHED", "CHANGED", "UNAVAILABLE", "NOT_APPLICABLE"
    ]
    frozen_source_profile_sha256: str | None = Field(
        default=None, pattern=r"^[0-9a-f]{64}$"
    )
    current_source_profile_sha256: str | None = Field(
        default=None, pattern=r"^[0-9a-f]{64}$"
    )
    source_authorization_status: Literal[
        "ACTIVE", "REVOKED", "EXPIRED", "UNAVAILABLE", "NOT_APPLICABLE"
    ] = "NOT_APPLICABLE"
    source_authorization_event_sha256: str | None = Field(
        default=None, pattern=r"^[0-9a-f]{64}$"
    )
    plan_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    checks: list[ReadinessCheck] = Field(min_length=1)
    production_authority: Literal["human_only"] = "human_only"
    report_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    claim_boundary: str = (
        "This live report verifies prerequisites for the current task state. It is "
        "not evidence that execution completed or that production release was approved."
    )


class TaskReleaseReadinessReport(ProductModel):
    """Post-run fail-closed status bound to immutable evidence and live source state."""

    schema_version: Literal["visiondata-gate.release-readiness.v1"] = (
        "visiondata-gate.release-readiness.v1"
    )
    task_id: str = Field(min_length=1)
    overall_status: Literal[
        "READY_FOR_HUMAN_REVIEW",
        "BLOCKED_GATE_DECISION",
        "BLOCKED_SOURCE_STALE",
        "BLOCKED_EVIDENCE_INTEGRITY",
        "DEMO_ONLY",
    ]
    final_gate_decision: str = Field(min_length=1)
    evidence_sha256: str | None = Field(default=None, pattern=r"^[0-9a-f]{64}$")
    evidence_integrity: Literal["VERIFIED", "FAILED"]
    source_freshness: Literal["CURRENT", "STALE", "UNAVAILABLE", "NOT_APPLICABLE"]
    frozen_source_profile_sha256: str | None = Field(
        default=None, pattern=r"^[0-9a-f]{64}$"
    )
    current_source_profile_sha256: str | None = Field(
        default=None, pattern=r"^[0-9a-f]{64}$"
    )
    open_work_order_count: int | None = Field(default=None, ge=0)
    checks: list[ReadinessCheck] = Field(min_length=1)
    production_release_allowed: Literal[False] = False
    required_human_action: str = Field(min_length=1)
    report_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    claim_boundary: str = (
        "This live report can block reuse of stale or non-passing evidence. It never "
        "grants production authority; the responsible human and enterprise process "
        "remain the final decision makers."
    )


def build_task_preflight_report(**values: object) -> TaskPreflightReport:
    """Seal a preflight payload without making wall-clock time part of the result."""

    stable = {
        "schema_version": "visiondata-gate.task-preflight.v3",
        **values,
        "claim_boundary": TaskPreflightReport.model_fields["claim_boundary"].default,
    }
    digest = hashlib.sha256(canonical_json_bytes(stable)).hexdigest()
    return TaskPreflightReport(**stable, report_sha256=digest)


def build_task_release_readiness_report(
    **values: object,
) -> TaskReleaseReadinessReport:
    """Seal a post-run readiness payload against its current observable state."""

    stable = {
        "schema_version": "visiondata-gate.release-readiness.v1",
        **values,
        "production_release_allowed": False,
        "claim_boundary": TaskReleaseReadinessReport.model_fields[
            "claim_boundary"
        ].default,
    }
    digest = hashlib.sha256(canonical_json_bytes(stable)).hexdigest()
    return TaskReleaseReadinessReport(**stable, report_sha256=digest)


__all__ = [
    "ReadinessCheck",
    "TaskPreflightReport",
    "TaskReleaseReadinessReport",
    "build_task_preflight_report",
    "build_task_release_readiness_report",
]
