"""Executable runtime invariant checks for governed state transitions.

This module is deliberately narrower than formal model checking.  It evaluates
six frozen, testable invariants at a proposed transition and emits a
deterministic receipt.  Callers remain responsible for selecting the correct
transition boundary and for persisting the receipt with the surrounding case.
"""

from __future__ import annotations

import hashlib
import hmac
from enum import Enum
from typing import Literal

import rfc8785
from pydantic import Field, field_validator

from .product_models import ProductModel
from .runtime_models import ScenarioProfile


RUNTIME_INVARIANT_SCHEMA_VERSION = "visiondata-gate.runtime-invariant-receipt.v1"


def _canonical_jcs_bytes(value: object) -> bytes:
    """Canonicalize an already JSON-compatible payload without policy imports."""

    try:
        return rfc8785.dumps(value)
    except (rfc8785.CanonicalizationError, TypeError, UnicodeError) as error:
        raise ValueError(
            f"runtime invariant payload cannot be canonicalized: {error}"
        ) from error


# These checks already governed PASS before the invariant receipt existed.
SCENARIO_PASS_GUARD_CHECK_IDS = frozenset(
    {
        "RC-GOVERNANCE-SCOPE",
        "RC-COUNTERFACTUAL-REMOVE-1",
        "RC-COUNTERFACTUAL-TOOL-REMOVE-1",
        "RC-COUNTERFACTUAL-RULE-STABILITY-1",
    }
)

# Industrial PASS additionally requires the complete deterministic measurement
# contract.  Generic sandbox behaviour is intentionally left backward
# compatible until its legacy one-tool PASS fixture is migrated explicitly.
INDUSTRIAL_PASS_MANDATORY_CHECK_IDS = frozenset(
    {
        "RC-TOOL-COUNT",
        "RC-SCENARIO-TOOLS",
        "RC-TRACE-OK",
        "RC-EVIDENCE-QUALITY",
    }
)


class RuntimeAction(str, Enum):
    GATE_PASS = "GATE_PASS"
    EXECUTE_CAPA = "EXECUTE_CAPA"
    EXECUTE_CHILD_RUN = "EXECUTE_CHILD_RUN"
    MACHINE_WRITE = "MACHINE_WRITE"
    PRODUCTION_RELEASE = "PRODUCTION_RELEASE"
    OTHER = "OTHER"


class RuntimeActorKind(str, Enum):
    AGENT = "AGENT"
    HUMAN = "HUMAN"
    SYSTEM = "SYSTEM"


class RuntimeInvariantStatus(str, Enum):
    PASS = "PASS"
    FAIL = "FAIL"
    NOT_APPLICABLE = "NOT_APPLICABLE"


class RuntimeInvariantContext(ProductModel):
    """Facts available immediately before one governed transition."""

    schema_version: Literal["visiondata-gate.runtime-invariant-context.v1"] = (
        "visiondata-gate.runtime-invariant-context.v1"
    )
    action: RuntimeAction
    actor_kind: RuntimeActorKind = RuntimeActorKind.SYSTEM
    scenario_profile: ScenarioProfile = ScenarioProfile.GENERIC
    input_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    failed_required_rule_check_ids: list[str] = Field(default_factory=list)
    named_human_approver: str | None = None
    parent_case_sha256: str | None = Field(default=None, pattern=r"^[0-9a-f]{64}$")
    parent_source_readonly: bool | None = None
    machine_write_permitted: bool = False
    production_release_allowed: bool = False
    open_responsibilities_count: int = Field(default=0, ge=0)

    @field_validator("failed_required_rule_check_ids")
    @classmethod
    def normalize_failed_check_ids(cls, value: list[str]) -> list[str]:
        normalized = sorted({item.strip() for item in value if item.strip()})
        return normalized

    @field_validator("named_human_approver")
    @classmethod
    def reject_blank_approver(cls, value: str | None) -> str | None:
        if value is None:
            return None
        normalized = value.strip()
        return normalized or None


class RuntimeInvariantOutcome(ProductModel):
    invariant_id: Literal["INV-1", "INV-2", "INV-3", "INV-4", "INV-5", "INV-6"]
    status: RuntimeInvariantStatus
    detail: str = Field(min_length=1)
    related_refs: list[str] = Field(default_factory=list)


class RuntimeInvariantReceipt(ProductModel):
    """Self-contained, deterministic receipt for one invariant evaluation."""

    schema_version: Literal["visiondata-gate.runtime-invariant-receipt.v1"] = (
        RUNTIME_INVARIANT_SCHEMA_VERSION
    )
    checker_version: Literal["runtime-invariant-checker.v1"] = (
        "runtime-invariant-checker.v1"
    )
    context: RuntimeInvariantContext
    context_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    outcomes: list[RuntimeInvariantOutcome] = Field(min_length=6, max_length=6)
    allowed: bool
    receipt_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")


class SafetyInvariantViolation(RuntimeError):
    """Raised when a caller explicitly requests fail-fast transition checking."""

    def __init__(self, receipt: RuntimeInvariantReceipt) -> None:
        failed = [
            item.invariant_id
            for item in receipt.outcomes
            if item.status is RuntimeInvariantStatus.FAIL
        ]
        super().__init__("runtime invariant violation: " + ", ".join(failed))
        self.receipt = receipt


def required_gate_check_ids(profile: ScenarioProfile) -> frozenset[str]:
    """Return the frozen PASS-level rule-check contract for one scenario."""

    required = set(SCENARIO_PASS_GUARD_CHECK_IDS)
    if profile is ScenarioProfile.INDUSTRIAL:
        required.update(INDUSTRIAL_PASS_MANDATORY_CHECK_IDS)
    return frozenset(required)


def _outcome(
    invariant_id: Literal["INV-1", "INV-2", "INV-3", "INV-4", "INV-5", "INV-6"],
    status: RuntimeInvariantStatus,
    detail: str,
    *related_refs: str,
) -> RuntimeInvariantOutcome:
    return RuntimeInvariantOutcome(
        invariant_id=invariant_id,
        status=status,
        detail=detail,
        related_refs=sorted({item for item in related_refs if item}),
    )


def _evaluate_outcomes(
    context: RuntimeInvariantContext,
) -> list[RuntimeInvariantOutcome]:
    if context.action is RuntimeAction.GATE_PASS:
        inv1 = _outcome(
            "INV-1",
            (
                RuntimeInvariantStatus.FAIL
                if context.failed_required_rule_check_ids
                else RuntimeInvariantStatus.PASS
            ),
            (
                "Required PASS-level tool or evidence checks failed."
                if context.failed_required_rule_check_ids
                else "All required PASS-level tool and evidence checks passed."
            ),
            *(
                f"rule-check:{check_id}"
                for check_id in context.failed_required_rule_check_ids
            ),
        )
    else:
        inv1 = _outcome(
            "INV-1",
            RuntimeInvariantStatus.NOT_APPLICABLE,
            "The proposed action is not a Gate PASS transition.",
        )

    if context.action is RuntimeAction.EXECUTE_CAPA:
        approver = (context.named_human_approver or "").strip()
        valid_approver = bool(approver) and approver.upper() != "ANONYMOUS"
        inv2 = _outcome(
            "INV-2",
            RuntimeInvariantStatus.PASS
            if valid_approver
            else RuntimeInvariantStatus.FAIL,
            (
                "CAPA execution is bound to a named human approver."
                if valid_approver
                else "CAPA execution requires a named, non-anonymous human approver."
            ),
            f"approver:{approver}" if valid_approver else "approver:missing",
        )
    else:
        inv2 = _outcome(
            "INV-2",
            RuntimeInvariantStatus.NOT_APPLICABLE,
            "The proposed action does not execute CAPA.",
        )

    if context.action is RuntimeAction.EXECUTE_CHILD_RUN:
        lineage_bound = bool(context.parent_case_sha256) and (
            context.parent_source_readonly is True
        )
        inv3 = _outcome(
            "INV-3",
            RuntimeInvariantStatus.PASS
            if lineage_bound
            else RuntimeInvariantStatus.FAIL,
            (
                "Child Run is bound to an immutable parent digest and read-only source."
                if lineage_bound
                else "Child Run requires a parent digest and an explicitly read-only parent source."
            ),
            (
                f"parent-sha256:{context.parent_case_sha256}"
                if context.parent_case_sha256
                else "parent-sha256:missing"
            ),
            f"parent-readonly:{str(context.parent_source_readonly).lower()}",
        )
    else:
        inv3 = _outcome(
            "INV-3",
            RuntimeInvariantStatus.NOT_APPLICABLE,
            "The proposed action does not execute a Child Run.",
        )

    machine_write_violation = (
        context.machine_write_permitted or context.action is RuntimeAction.MACHINE_WRITE
    )
    inv4 = _outcome(
        "INV-4",
        RuntimeInvariantStatus.FAIL
        if machine_write_violation
        else RuntimeInvariantStatus.PASS,
        (
            "Direct machine or PLC write is forbidden."
            if machine_write_violation
            else "Direct machine and PLC write remains disabled."
        ),
        f"machine-write-permitted:{str(context.machine_write_permitted).lower()}",
    )

    unauthorized_release = context.production_release_allowed or (
        context.action is RuntimeAction.PRODUCTION_RELEASE
        and context.actor_kind is not RuntimeActorKind.HUMAN
    )
    inv5 = _outcome(
        "INV-5",
        RuntimeInvariantStatus.FAIL
        if unauthorized_release
        else RuntimeInvariantStatus.PASS,
        (
            "Production release authority is restricted to a human decision."
            if unauthorized_release
            else "Agent and system production-release authority remains disabled."
        ),
        f"actor:{context.actor_kind.value}",
        f"production-release-allowed:{str(context.production_release_allowed).lower()}",
    )

    if context.action is RuntimeAction.PRODUCTION_RELEASE:
        inv6 = _outcome(
            "INV-6",
            (
                RuntimeInvariantStatus.FAIL
                if context.open_responsibilities_count > 0
                else RuntimeInvariantStatus.PASS
            ),
            (
                "Open responsibilities require fail-closed transfer to investigation."
                if context.open_responsibilities_count > 0
                else "No open responsibility blocks the proposed human release transition."
            ),
            f"open-responsibilities:{context.open_responsibilities_count}",
        )
    else:
        inv6 = _outcome(
            "INV-6",
            RuntimeInvariantStatus.NOT_APPLICABLE,
            "The proposed action is not a production-release transition.",
        )

    return [inv1, inv2, inv3, inv4, inv5, inv6]


def build_runtime_invariant_receipt(
    context: RuntimeInvariantContext,
) -> RuntimeInvariantReceipt:
    """Evaluate the six invariants and seal a deterministic receipt."""

    outcomes = _evaluate_outcomes(context)
    allowed = not any(item.status is RuntimeInvariantStatus.FAIL for item in outcomes)
    context_payload = context.model_dump(mode="json")
    context_sha256 = hashlib.sha256(_canonical_jcs_bytes(context_payload)).hexdigest()
    draft = RuntimeInvariantReceipt(
        context=context,
        context_sha256=context_sha256,
        outcomes=outcomes,
        allowed=allowed,
        receipt_sha256="0" * 64,
    )
    payload = draft.model_dump(mode="json", exclude={"receipt_sha256"})
    return draft.model_copy(
        update={
            "receipt_sha256": hashlib.sha256(_canonical_jcs_bytes(payload)).hexdigest()
        }
    )


def verify_runtime_invariant_receipt(receipt: RuntimeInvariantReceipt) -> None:
    """Re-evaluate and compare every sealed receipt field."""

    expected = build_runtime_invariant_receipt(receipt.context)
    if not hmac.compare_digest(receipt.context_sha256, expected.context_sha256):
        raise ValueError("runtime invariant context digest mismatch")
    if receipt.outcomes != expected.outcomes:
        raise ValueError("runtime invariant outcomes mismatch")
    if receipt.allowed is not expected.allowed:
        raise ValueError("runtime invariant disposition mismatch")
    if not hmac.compare_digest(receipt.receipt_sha256, expected.receipt_sha256):
        raise ValueError("runtime invariant receipt digest mismatch")


def assert_runtime_invariants(
    context: RuntimeInvariantContext,
) -> RuntimeInvariantReceipt:
    """Return an allowed receipt or raise with the complete failed receipt."""

    receipt = build_runtime_invariant_receipt(context)
    if not receipt.allowed:
        raise SafetyInvariantViolation(receipt)
    return receipt


__all__ = [
    "INDUSTRIAL_PASS_MANDATORY_CHECK_IDS",
    "RUNTIME_INVARIANT_SCHEMA_VERSION",
    "SCENARIO_PASS_GUARD_CHECK_IDS",
    "RuntimeAction",
    "RuntimeActorKind",
    "RuntimeInvariantContext",
    "RuntimeInvariantOutcome",
    "RuntimeInvariantReceipt",
    "RuntimeInvariantStatus",
    "SafetyInvariantViolation",
    "assert_runtime_invariants",
    "build_runtime_invariant_receipt",
    "required_gate_check_ids",
    "verify_runtime_invariant_receipt",
]
