"""Auditable control-plane sidecars for one industrial incident case.

The existing ``IndustrialIncidentCase`` remains the immutable business record.
This module adds three independently sealed views without changing the case-v3
hash contract:

* a typed execution tree projected from actions that actually ran;
* an authority-epoch ledger that makes delayed Worker receipts rejectable;
* a contrastive decision packet for the named quality owner.

These objects do not grant production-release or equipment-control authority.
"""

from __future__ import annotations

import hashlib
import hmac
from enum import Enum
from typing import Literal

from pydantic import Field, model_validator

from .evidence import canonical_json_bytes
from .industrial_incident import (
    IncidentWorkerReceipt,
    IndustrialIncidentCase,
    verify_incident_worker_receipt,
    verify_industrial_incident_case,
)
from .product_models import ProductModel


def _sha256(value: object) -> str:
    return hashlib.sha256(canonical_json_bytes(value)).hexdigest()


def _identifier(prefix: str, *parts: object) -> str:
    digest = _sha256([prefix, *parts])[:20]
    return f"{prefix}_{digest}"


def _verify_seal(value: ProductModel, field: str, message: str) -> None:
    payload = value.model_dump(mode="json")
    stored = payload.pop(field)
    if not hmac.compare_digest(stored, _sha256(payload)):
        raise ValueError(message)


class IncidentPlanNodeType(str, Enum):
    SEQUENCE = "SEQUENCE"
    PARALLEL = "PARALLEL"
    FALLBACK = "FALLBACK"
    GUARD = "GUARD"
    INTERRUPT = "INTERRUPT"
    REVALIDATE = "REVALIDATE"
    WORKER = "WORKER"


class IncidentPlanNodeStatus(str, Enum):
    COMPLETED = "COMPLETED"
    PAUSED = "PAUSED"
    SKIPPED = "SKIPPED"
    FAILED = "FAILED"
    BLOCKED = "BLOCKED"


class IncidentPlanNode(ProductModel):
    schema_version: Literal["visiondata-gate.incident-plan-node.v1"] = (
        "visiondata-gate.incident-plan-node.v1"
    )
    node_id: str = Field(pattern=r"^plan_node_[0-9a-f]{20}$")
    node_type: IncidentPlanNodeType
    parent_node_id: str | None = Field(
        default=None, pattern=r"^plan_node_[0-9a-f]{20}$"
    )
    sequence: int = Field(ge=1)
    goal: str = Field(min_length=1, max_length=360)
    preconditions: list[str]
    triggering_evidence_refs: list[str]
    reason_codes: list[str]
    allowed_workers: list[str]
    worker_role: str | None = Field(default=None, max_length=120)
    source_invocation_id: str | None = Field(
        default=None, pattern=r"^worker_invocation_[0-9a-f]{20}$"
    )
    budget_cost: int = Field(ge=0, le=12)
    selected: bool
    status: IncidentPlanNodeStatus
    output_refs: list[str]
    node_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")

    @model_validator(mode="after")
    def validate_worker_leaf(self) -> IncidentPlanNode:
        worker_fields = (self.worker_role, self.source_invocation_id)
        if self.node_type is IncidentPlanNodeType.WORKER and not all(worker_fields):
            raise ValueError("Worker plan node requires role and invocation binding")
        if self.node_type is not IncidentPlanNodeType.WORKER and any(worker_fields):
            raise ValueError("only Worker plan nodes may bind a Worker invocation")
        if (
            self.worker_role is not None
            and self.worker_role not in self.allowed_workers
        ):
            raise ValueError("selected Worker must be present in the node allowlist")
        return self


class TypedIncidentPlanTree(ProductModel):
    schema_version: Literal["visiondata-gate.typed-incident-plan-tree.v1"] = (
        "visiondata-gate.typed-incident-plan-tree.v1"
    )
    case_id: str = Field(pattern=r"^incident_[0-9a-f]{20}$")
    case_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    root_node_id: str = Field(pattern=r"^plan_node_[0-9a-f]{20}$")
    nodes: list[IncidentPlanNode] = Field(min_length=7)
    selected_path_node_ids: list[str] = Field(min_length=1)
    dynamic_worker_budget: int = Field(ge=1, le=12)
    dynamic_workers_executed: int = Field(ge=0, le=12)
    remaining_worker_budget: int = Field(ge=0, le=12)
    execution_semantics: Literal["OBSERVED_CASE_PROJECTION_V1"] = (
        "OBSERVED_CASE_PROJECTION_V1"
    )
    tree_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")

    @model_validator(mode="after")
    def validate_tree_shape(self) -> TypedIncidentPlanTree:
        node_ids = [node.node_id for node in self.nodes]
        if len(node_ids) != len(set(node_ids)):
            raise ValueError("typed incident plan node IDs must be unique")
        if self.root_node_id not in node_ids:
            raise ValueError("typed incident plan root is missing")
        nodes_by_id = {node.node_id: node for node in self.nodes}
        root = nodes_by_id[self.root_node_id]
        if root.parent_node_id is not None:
            raise ValueError("typed incident plan root must not have a parent")
        for node in self.nodes:
            if node.node_id == self.root_node_id:
                continue
            if node.parent_node_id not in nodes_by_id:
                raise ValueError("typed incident plan contains an orphan node")
            visited = {node.node_id}
            parent_id = node.parent_node_id
            while parent_id is not None:
                if parent_id in visited:
                    raise ValueError("typed incident plan contains a cycle")
                visited.add(parent_id)
                parent_id = nodes_by_id[parent_id].parent_node_id
        if not set(self.selected_path_node_ids).issubset(node_ids):
            raise ValueError("typed incident selected path references an unknown node")
        required_types = {
            IncidentPlanNodeType.SEQUENCE,
            IncidentPlanNodeType.PARALLEL,
            IncidentPlanNodeType.FALLBACK,
            IncidentPlanNodeType.GUARD,
            IncidentPlanNodeType.INTERRUPT,
            IncidentPlanNodeType.REVALIDATE,
        }
        if not required_types.issubset({node.node_type for node in self.nodes}):
            raise ValueError("typed incident plan is missing a required control node")
        if self.dynamic_workers_executed + self.remaining_worker_budget != (
            self.dynamic_worker_budget
        ):
            raise ValueError("typed incident plan Worker budget does not reconcile")
        return self


def _plan_node(**payload: object) -> IncidentPlanNode:
    stable = {
        "schema_version": "visiondata-gate.incident-plan-node.v1",
        **payload,
    }
    return IncidentPlanNode(**stable, node_sha256=_sha256(stable))


def build_typed_incident_plan_tree(
    case: IndustrialIncidentCase,
) -> TypedIncidentPlanTree:
    """Project the actual case actions into a typed, independently sealed tree."""

    verify_industrial_incident_case(case)
    node_sequence = 0
    nodes: list[IncidentPlanNode] = []

    def add(key: str, **payload: object) -> IncidentPlanNode:
        nonlocal node_sequence
        node_sequence += 1
        node = _plan_node(
            node_id=_identifier("plan_node", case.case_id, key),
            sequence=node_sequence,
            **payload,
        )
        nodes.append(node)
        return node

    qualified_refs = sorted(
        evidence.evidence_ref
        for evidence in case.evidence_refs
        if evidence.qualification.value != "NOT_QUALIFIED"
    )
    all_reason_codes = sorted({issue.issue_code for issue in case.evidence_issues})
    worker_roles = sorted({receipt.worker_role for receipt in case.worker_receipts})
    root = add(
        "root",
        node_type=IncidentPlanNodeType.SEQUENCE,
        parent_node_id=None,
        goal="完成证据资格、竞争假设调查、确定性裁决、人工中断与复验交接",
        preconditions=["CASE_IDENTITY_BOUND", "CASE_SHA256_VERIFIED"],
        triggering_evidence_refs=qualified_refs,
        reason_codes=all_reason_codes,
        allowed_workers=worker_roles,
        worker_role=None,
        source_invocation_id=None,
        budget_cost=0,
        selected=True,
        status=(
            IncidentPlanNodeStatus.COMPLETED
            if case.status.value == "CLOSED"
            else IncidentPlanNodeStatus.PAUSED
        ),
        output_refs=[case.case_sha256],
    )
    qualification = add(
        "evidence-qualification-guard",
        node_type=IncidentPlanNodeType.GUARD,
        parent_node_id=root.node_id,
        goal="只允许已授权、身份一致且可验签的证据参与案件判断",
        preconditions=["READ_ONLY_EVIDENCE"],
        triggering_evidence_refs=qualified_refs,
        reason_codes=sorted(
            {
                issue.issue_code
                for issue in case.evidence_issues
                if "EVIDENCE" in issue.issue_code or "AUTHORIZATION" in issue.issue_code
            }
        ),
        allowed_workers=["EvidenceQualificationAgent"],
        worker_role=None,
        source_invocation_id=None,
        budget_cost=0,
        selected=True,
        status=IncidentPlanNodeStatus.COMPLETED,
        output_refs=[case.evidence_bundle_sha256 or case.context_sha256],
    )
    investigation = add(
        "parallel-investigation",
        node_type=IncidentPlanNodeType.PARALLEL,
        parent_node_id=root.node_id,
        goal="并行保留竞争解释并执行有证据触发的最小 Worker 集",
        preconditions=[qualification.node_id],
        triggering_evidence_refs=qualified_refs,
        reason_codes=all_reason_codes,
        allowed_workers=worker_roles,
        worker_role=None,
        source_invocation_id=None,
        budget_cost=0,
        selected=bool(case.worker_receipts),
        status=(
            IncidentPlanNodeStatus.COMPLETED
            if case.worker_receipts
            else IncidentPlanNodeStatus.SKIPPED
        ),
        output_refs=[receipt.receipt_sha256 for receipt in case.worker_receipts],
    )
    worker_nodes: list[IncidentPlanNode] = []
    for receipt in case.worker_receipts:
        worker_nodes.append(
            add(
                f"worker:{receipt.invocation_id}",
                node_type=IncidentPlanNodeType.WORKER,
                parent_node_id=investigation.node_id,
                goal=f"执行 {receipt.worker_role} 的只读证据任务",
                preconditions=[qualification.node_id],
                triggering_evidence_refs=receipt.input_evidence_sha256,
                reason_codes=receipt.trigger_reason_codes,
                allowed_workers=[receipt.worker_role],
                worker_role=receipt.worker_role,
                source_invocation_id=receipt.invocation_id,
                budget_cost=1,
                selected=True,
                status=(
                    IncidentPlanNodeStatus.COMPLETED
                    if receipt.status == "SUCCEEDED"
                    else IncidentPlanNodeStatus.FAILED
                ),
                output_refs=[receipt.receipt_sha256],
            )
        )
    fallback_selected = any(
        receipt.status == "FAILED" for receipt in case.worker_receipts
    ) or case.loop_control.stop_reason.value in {
        "WORKER_BUDGET_EXHAUSTED",
        "NO_DISCRIMINATING_ACTION",
        "SAFETY_GATE_BLOCKED",
    }
    fallback = add(
        "safe-fallback",
        node_type=IncidentPlanNodeType.FALLBACK,
        parent_node_id=root.node_id,
        goal="Worker 失败、预算耗尽或安全门禁阻断时保持 HOLD 并转补证",
        preconditions=[investigation.node_id],
        triggering_evidence_refs=[
            receipt.receipt_sha256
            for receipt in case.worker_receipts
            if receipt.status == "FAILED"
        ],
        reason_codes=[case.loop_control.stop_reason.value],
        allowed_workers=[],
        worker_role=None,
        source_invocation_id=None,
        budget_cost=0,
        selected=fallback_selected,
        status=(
            IncidentPlanNodeStatus.COMPLETED
            if fallback_selected
            else IncidentPlanNodeStatus.SKIPPED
        ),
        output_refs=[case.recommendation.value],
    )
    judge = add(
        "frozen-policy-judge",
        node_type=IncidentPlanNodeType.GUARD,
        parent_node_id=root.node_id,
        goal="由冻结规则裁决业务状态，禁止模型直接确立根因或恢复生产",
        preconditions=[qualification.node_id, investigation.node_id],
        triggering_evidence_refs=[edge.evidence_ref for edge in case.evidence_edges],
        reason_codes=all_reason_codes,
        allowed_workers=[],
        worker_role=None,
        source_invocation_id=None,
        budget_cost=0,
        selected=True,
        status=IncidentPlanNodeStatus.COMPLETED,
        output_refs=[case.status.value, case.recommendation.value],
    )
    interrupt = add(
        "named-human-interrupt",
        node_type=IncidentPlanNodeType.INTERRUPT,
        parent_node_id=root.node_id,
        goal="撤销自动执行权限并等待具名质量负责人决定",
        preconditions=[judge.node_id],
        triggering_evidence_refs=[case.case_sha256],
        reason_codes=[case.loop_control.stop_reason.value],
        allowed_workers=[],
        worker_role=None,
        source_invocation_id=None,
        budget_cost=0,
        selected=True,
        status=IncidentPlanNodeStatus.PAUSED,
        output_refs=[question.question_id for question in case.operator_questions],
    )
    child_completed = case.gate_context.child_run_status == "COMPLETED"
    revalidate = add(
        "immutable-child-revalidation",
        node_type=IncidentPlanNodeType.REVALIDATE,
        parent_node_id=root.node_id,
        goal="仅在人工授权后创建派生版本和独立 child Run，并保持生产放行关闭",
        preconditions=[interrupt.node_id, "VALID_DECISION_SHA256"],
        triggering_evidence_refs=(
            [case.gate_context.capa_evidence.child_evidence_sha256]
            if case.gate_context.capa_evidence is not None
            and case.gate_context.capa_evidence.child_evidence_sha256 is not None
            else []
        ),
        reason_codes=[case.gate_context.child_run_status],
        allowed_workers=[],
        worker_role=None,
        source_invocation_id=None,
        budget_cost=0,
        selected=child_completed,
        status=(
            IncidentPlanNodeStatus.COMPLETED
            if child_completed
            else IncidentPlanNodeStatus.BLOCKED
        ),
        output_refs=(
            [case.gate_context.capa_evidence.recovery_receipt_sha256]
            if case.gate_context.capa_evidence is not None
            and case.gate_context.capa_evidence.recovery_receipt_sha256 is not None
            else []
        ),
    )
    selected_path = [
        root.node_id,
        qualification.node_id,
        *(
            [investigation.node_id, *[node.node_id for node in worker_nodes]]
            if case.worker_receipts
            else []
        ),
        *([fallback.node_id] if fallback_selected else []),
        judge.node_id,
        interrupt.node_id,
        *([revalidate.node_id] if child_completed else []),
    ]
    stable = {
        "schema_version": "visiondata-gate.typed-incident-plan-tree.v1",
        "case_id": case.case_id,
        "case_sha256": case.case_sha256,
        "root_node_id": root.node_id,
        "nodes": nodes,
        "selected_path_node_ids": selected_path,
        "dynamic_worker_budget": case.loop_control.dynamic_worker_budget,
        "dynamic_workers_executed": case.loop_control.dynamic_workers_executed,
        "remaining_worker_budget": case.loop_control.remaining_worker_budget,
        "execution_semantics": "OBSERVED_CASE_PROJECTION_V1",
    }
    tree = TypedIncidentPlanTree(**stable, tree_sha256=_sha256(stable))
    verify_typed_incident_plan_tree(tree, case=case)
    return tree


def verify_typed_incident_plan_tree(
    tree: TypedIncidentPlanTree,
    *,
    case: IndustrialIncidentCase | None = None,
) -> None:
    for node in tree.nodes:
        _verify_seal(
            node,
            "node_sha256",
            "typed incident plan node failed SHA-256 validation",
        )
    _verify_seal(
        tree,
        "tree_sha256",
        "typed incident plan tree failed SHA-256 validation",
    )
    if case is None:
        return
    verify_industrial_incident_case(case)
    if tree.case_id != case.case_id or not hmac.compare_digest(
        tree.case_sha256, case.case_sha256
    ):
        raise ValueError("typed incident plan tree failed case binding")
    if (
        tree.dynamic_worker_budget != case.loop_control.dynamic_worker_budget
        or tree.dynamic_workers_executed != case.loop_control.dynamic_workers_executed
        or tree.remaining_worker_budget != case.loop_control.remaining_worker_budget
    ):
        raise ValueError("typed incident plan tree failed Worker budget binding")
    actual = {
        (receipt.invocation_id, receipt.worker_role, receipt.receipt_sha256)
        for receipt in case.worker_receipts
    }
    projected = {
        (node.source_invocation_id, node.worker_role, node.output_refs[0])
        for node in tree.nodes
        if node.node_type is IncidentPlanNodeType.WORKER
    }
    if actual != projected:
        raise ValueError("typed incident plan tree failed Worker receipt binding")


class IncidentAuthorityStatus(str, Enum):
    ACTIVE = "ACTIVE"
    INTERRUPTED = "INTERRUPTED"


class IncidentAuthorityState(ProductModel):
    schema_version: Literal["visiondata-gate.incident-authority-state.v1"] = (
        "visiondata-gate.incident-authority-state.v1"
    )
    case_id: str = Field(pattern=r"^incident_[0-9a-f]{20}$")
    case_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    authority_epoch: int = Field(ge=1)
    status: IncidentAuthorityStatus
    allowed_effects: list[Literal["READ_CASE_EVIDENCE", "RETURN_WORKER_RECEIPT"]]
    forbidden_effects: list[
        Literal["WRITE_EQUIPMENT", "RELEASE_PRODUCTION", "APPROVE_CAPA"]
    ]
    predecessor_state_sha256: str | None = Field(
        default=None, pattern=r"^[0-9a-f]{64}$"
    )
    state_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")


class IncidentWorkerCapabilityGrant(ProductModel):
    schema_version: Literal["visiondata-gate.incident-worker-capability.v1"] = (
        "visiondata-gate.incident-worker-capability.v1"
    )
    grant_id: str = Field(pattern=r"^capability_[0-9a-f]{20}$")
    case_id: str = Field(pattern=r"^incident_[0-9a-f]{20}$")
    case_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    authority_epoch: int = Field(ge=1)
    issuing_state_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    invocation_id: str = Field(pattern=r"^worker_invocation_[0-9a-f]{20}$")
    worker_role: str = Field(min_length=1, max_length=120)
    permitted_effects: list[Literal["READ_CASE_EVIDENCE", "RETURN_WORKER_RECEIPT"]]
    machine_write_permitted: Literal[False] = False
    production_release_permitted: Literal[False] = False
    grant_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")


class IncidentWorkerAuthorityCheck(ProductModel):
    schema_version: Literal["visiondata-gate.incident-worker-authority-check.v1"] = (
        "visiondata-gate.incident-worker-authority-check.v1"
    )
    check_id: str = Field(pattern=r"^authority_check_[0-9a-f]{20}$")
    case_id: str = Field(pattern=r"^incident_[0-9a-f]{20}$")
    grant_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    worker_receipt_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    grant_epoch: int = Field(ge=1)
    observed_authority_epoch: int = Field(ge=1)
    observed_authority_status: IncidentAuthorityStatus
    outcome: Literal["ACCEPTED", "REJECTED"]
    reason_code: Literal[
        "AUTHORIZED_AT_EPOCH",
        "STALE_AUTHORITY_EPOCH",
        "AUTHORITY_NOT_ACTIVE",
        "AUTHORITY_STATE_MISMATCH",
        "WORKER_RECEIPT_BINDING_MISMATCH",
    ]
    check_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")


class IncidentAuthorityLedger(ProductModel):
    schema_version: Literal["visiondata-gate.incident-authority-ledger.v1"] = (
        "visiondata-gate.incident-authority-ledger.v1"
    )
    case_id: str = Field(pattern=r"^incident_[0-9a-f]{20}$")
    case_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    initial_state: IncidentAuthorityState
    capability_grants: list[IncidentWorkerCapabilityGrant]
    accepted_receipts: list[IncidentWorkerAuthorityCheck]
    current_state: IncidentAuthorityState
    interrupt_reason: str = Field(min_length=1, max_length=160)
    stale_receipt_policy: Literal["REJECT_IF_GRANT_EPOCH_IS_NOT_CURRENT"] = (
        "REJECT_IF_GRANT_EPOCH_IS_NOT_CURRENT"
    )
    ledger_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")

    @model_validator(mode="after")
    def validate_counts_and_epochs(self) -> IncidentAuthorityLedger:
        if len(self.capability_grants) != len(self.accepted_receipts):
            raise ValueError("authority ledger grant and receipt counts must match")
        if self.initial_state.status is not IncidentAuthorityStatus.ACTIVE:
            raise ValueError("authority ledger initial state must be ACTIVE")
        if self.current_state.status is not IncidentAuthorityStatus.INTERRUPTED:
            raise ValueError("authority ledger current state must be INTERRUPTED")
        if self.current_state.authority_epoch != self.initial_state.authority_epoch + 1:
            raise ValueError("authority interrupt must advance the global epoch once")
        if self.current_state.predecessor_state_sha256 != (
            self.initial_state.state_sha256
        ):
            raise ValueError("authority interrupt failed predecessor binding")
        return self


def _authority_state(**payload: object) -> IncidentAuthorityState:
    stable = {
        "schema_version": "visiondata-gate.incident-authority-state.v1",
        **payload,
    }
    return IncidentAuthorityState(**stable, state_sha256=_sha256(stable))


def _capability_grant(
    case: IndustrialIncidentCase,
    state: IncidentAuthorityState,
    receipt: IncidentWorkerReceipt,
) -> IncidentWorkerCapabilityGrant:
    stable = {
        "schema_version": "visiondata-gate.incident-worker-capability.v1",
        "grant_id": _identifier(
            "capability", case.case_id, state.authority_epoch, receipt.invocation_id
        ),
        "case_id": case.case_id,
        "case_sha256": case.case_sha256,
        "authority_epoch": state.authority_epoch,
        "issuing_state_sha256": state.state_sha256,
        "invocation_id": receipt.invocation_id,
        "worker_role": receipt.worker_role,
        "permitted_effects": ["READ_CASE_EVIDENCE", "RETURN_WORKER_RECEIPT"],
        "machine_write_permitted": False,
        "production_release_permitted": False,
    }
    return IncidentWorkerCapabilityGrant(**stable, grant_sha256=_sha256(stable))


def check_incident_worker_authority(
    *,
    receipt: IncidentWorkerReceipt,
    grant: IncidentWorkerCapabilityGrant,
    state: IncidentAuthorityState,
) -> IncidentWorkerAuthorityCheck:
    """Evaluate a Worker receipt against the authority state at publication time."""

    verify_incident_worker_receipt(receipt)
    _verify_seal(
        grant,
        "grant_sha256",
        "incident Worker capability failed SHA-256 validation",
    )
    _verify_seal(
        state,
        "state_sha256",
        "incident authority state failed SHA-256 validation",
    )
    if grant.authority_epoch != state.authority_epoch:
        outcome = "REJECTED"
        reason = "STALE_AUTHORITY_EPOCH"
    elif state.status is not IncidentAuthorityStatus.ACTIVE:
        outcome = "REJECTED"
        reason = "AUTHORITY_NOT_ACTIVE"
    elif not hmac.compare_digest(grant.issuing_state_sha256, state.state_sha256):
        outcome = "REJECTED"
        reason = "AUTHORITY_STATE_MISMATCH"
    elif (
        grant.case_id != state.case_id
        or not hmac.compare_digest(grant.case_sha256, state.case_sha256)
        or grant.invocation_id != receipt.invocation_id
        or grant.worker_role != receipt.worker_role
    ):
        outcome = "REJECTED"
        reason = "WORKER_RECEIPT_BINDING_MISMATCH"
    else:
        outcome = "ACCEPTED"
        reason = "AUTHORIZED_AT_EPOCH"
    stable = {
        "schema_version": "visiondata-gate.incident-worker-authority-check.v1",
        "check_id": _identifier(
            "authority_check",
            grant.grant_sha256,
            receipt.receipt_sha256,
            state.state_sha256,
        ),
        "case_id": state.case_id,
        "grant_sha256": grant.grant_sha256,
        "worker_receipt_sha256": receipt.receipt_sha256,
        "grant_epoch": grant.authority_epoch,
        "observed_authority_epoch": state.authority_epoch,
        "observed_authority_status": state.status,
        "outcome": outcome,
        "reason_code": reason,
    }
    return IncidentWorkerAuthorityCheck(**stable, check_sha256=_sha256(stable))


def build_incident_authority_ledger(
    case: IndustrialIncidentCase,
) -> IncidentAuthorityLedger:
    verify_industrial_incident_case(case)
    initial_epoch = case.case_version * 2 - 1
    initial = _authority_state(
        case_id=case.case_id,
        case_sha256=case.case_sha256,
        authority_epoch=initial_epoch,
        status=IncidentAuthorityStatus.ACTIVE,
        allowed_effects=["READ_CASE_EVIDENCE", "RETURN_WORKER_RECEIPT"],
        forbidden_effects=[
            "WRITE_EQUIPMENT",
            "RELEASE_PRODUCTION",
            "APPROVE_CAPA",
        ],
        predecessor_state_sha256=None,
    )
    grants = [
        _capability_grant(case, initial, receipt) for receipt in case.worker_receipts
    ]
    accepted = [
        check_incident_worker_authority(
            receipt=receipt,
            grant=grant,
            state=initial,
        )
        for receipt, grant in zip(case.worker_receipts, grants, strict=True)
    ]
    current = _authority_state(
        case_id=case.case_id,
        case_sha256=case.case_sha256,
        authority_epoch=initial_epoch + 1,
        status=IncidentAuthorityStatus.INTERRUPTED,
        allowed_effects=[],
        forbidden_effects=[
            "WRITE_EQUIPMENT",
            "RELEASE_PRODUCTION",
            "APPROVE_CAPA",
        ],
        predecessor_state_sha256=initial.state_sha256,
    )
    stable = {
        "schema_version": "visiondata-gate.incident-authority-ledger.v1",
        "case_id": case.case_id,
        "case_sha256": case.case_sha256,
        "initial_state": initial,
        "capability_grants": grants,
        "accepted_receipts": accepted,
        "current_state": current,
        "interrupt_reason": case.loop_control.stop_reason.value,
        "stale_receipt_policy": "REJECT_IF_GRANT_EPOCH_IS_NOT_CURRENT",
    }
    ledger = IncidentAuthorityLedger(**stable, ledger_sha256=_sha256(stable))
    verify_incident_authority_ledger(ledger, case=case)
    return ledger


def verify_incident_authority_ledger(
    ledger: IncidentAuthorityLedger,
    *,
    case: IndustrialIncidentCase | None = None,
) -> None:
    _verify_seal(
        ledger.initial_state,
        "state_sha256",
        "incident authority initial state failed SHA-256 validation",
    )
    _verify_seal(
        ledger.current_state,
        "state_sha256",
        "incident authority current state failed SHA-256 validation",
    )
    for grant in ledger.capability_grants:
        _verify_seal(
            grant,
            "grant_sha256",
            "incident Worker capability failed SHA-256 validation",
        )
    for check in ledger.accepted_receipts:
        _verify_seal(
            check,
            "check_sha256",
            "incident Worker authority check failed SHA-256 validation",
        )
        if check.outcome != "ACCEPTED":
            raise ValueError(
                "authority ledger may contain only accepted pre-interrupt receipts"
            )
        if check.observed_authority_epoch != ledger.initial_state.authority_epoch:
            raise ValueError("accepted Worker receipt is outside the active epoch")
    _verify_seal(
        ledger,
        "ledger_sha256",
        "incident authority ledger failed SHA-256 validation",
    )
    if case is None:
        return
    verify_industrial_incident_case(case)
    if ledger.case_id != case.case_id or not hmac.compare_digest(
        ledger.case_sha256, case.case_sha256
    ):
        raise ValueError("incident authority ledger failed case binding")
    if [item.worker_receipt_sha256 for item in ledger.accepted_receipts] != [
        item.receipt_sha256 for item in case.worker_receipts
    ]:
        raise ValueError("incident authority ledger failed Worker receipt binding")


class IncidentWorkerChoice(ProductModel):
    worker_role: str
    invocation_id: str = Field(pattern=r"^worker_invocation_[0-9a-f]{20}$")
    trigger_reason_codes: list[str] = Field(min_length=1)
    receipt_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    result: Literal["SUCCEEDED", "FAILED"]


class IncidentHypothesisContrast(ProductModel):
    hypothesis_id: str
    category: str
    status: str
    supporting_issue_codes: list[str]
    contradicting_issue_codes: list[str]
    unresolved_evidence_refs: list[str]
    next_discriminating_test: str


class IncidentActionContrast(ProductModel):
    action: Literal[
        "CURRENT_RECOMMENDATION",
        "PRODUCTION_RELEASE",
        "CLOSE_AS_ROOT_CAUSE_ESTABLISHED",
        "EXECUTE_CAPA_WITHOUT_OWNER",
    ]
    disposition: Literal["SELECTED", "REJECTED", "DEFERRED"]
    rationale: str = Field(min_length=1, max_length=800)
    evidence_refs: list[str]
    change_conditions: list[str]


class ContrastiveIncidentDecisionPacket(ProductModel):
    schema_version: Literal["visiondata-gate.contrastive-decision-packet.v1"] = (
        "visiondata-gate.contrastive-decision-packet.v1"
    )
    case_id: str = Field(pattern=r"^incident_[0-9a-f]{20}$")
    case_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    current_status: str
    current_recommendation: str
    recommendation_reason: str
    observed_facts: list[str] = Field(min_length=1)
    qualified_evidence_refs: list[str] = Field(min_length=1)
    blocking_issue_codes: list[str]
    hypothesis_contrasts: list[IncidentHypothesisContrast] = Field(min_length=6)
    selected_workers: list[IncidentWorkerChoice]
    action_contrasts: list[IncidentActionContrast] = Field(min_length=4)
    missing_evidence_refs: list[str]
    what_would_change_decision: list[str] = Field(min_length=1)
    maximum_causal_claim_level: Literal[
        "L1_ASSOCIATED",
        "L4_INTERVENTION_SUPPORTED",
    ]
    root_cause_status: Literal["NOT_ESTABLISHED"] = "NOT_ESTABLISHED"
    production_release_allowed: Literal[False] = False
    machine_write_permitted: Literal[False] = False
    plan_tree_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    authority_ledger_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    packet_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")


def _build_action_contrasts(
    case: IndustrialIncidentCase,
    *,
    qualified_refs: list[str],
    change_conditions: list[str],
) -> list[IncidentActionContrast]:
    return [
        IncidentActionContrast(
            action="CURRENT_RECOMMENDATION",
            disposition="SELECTED",
            rationale=case.recommendation_reason,
            evidence_refs=qualified_refs,
            change_conditions=change_conditions,
        ),
        IncidentActionContrast(
            action="PRODUCTION_RELEASE",
            disposition="REJECTED",
            rationale=("系统没有生产放行权限；当前案件结论仅供具名质量负责人复核。"),
            evidence_refs=[case.case_sha256],
            change_conditions=[
                "具名责任人批准",
                "独立 child Run 完成",
                "冻结规则确认阻断项关闭",
            ],
        ),
        IncidentActionContrast(
            action="CLOSE_AS_ROOT_CAUSE_ESTABLISHED",
            disposition="REJECTED",
            rationale="竞争解释仍被保留，root_cause_status 明确为 NOT_ESTABLISHED。",
            evidence_refs=[case.case_sha256],
            change_conditions=[
                "满足企业根因认定 SOP",
                "反证审计完成",
                "具名责任人确认",
            ],
        ),
        IncidentActionContrast(
            action="EXECUTE_CAPA_WITHOUT_OWNER",
            disposition="REJECTED",
            rationale="整改方案只能由系统提出，不能绕过具名责任人审批。",
            evidence_refs=[case.case_sha256],
            change_conditions=[
                "有效 decision SHA",
                "选定 remediation plan",
                "审批绑定未失效",
            ],
        ),
    ]


def build_contrastive_decision_packet(
    case: IndustrialIncidentCase,
    *,
    plan_tree: TypedIncidentPlanTree,
    authority_ledger: IncidentAuthorityLedger,
) -> ContrastiveIncidentDecisionPacket:
    verify_industrial_incident_case(case)
    verify_typed_incident_plan_tree(plan_tree, case=case)
    verify_incident_authority_ledger(authority_ledger, case=case)
    qualified_refs = sorted(
        evidence.evidence_ref
        for evidence in case.evidence_refs
        if evidence.qualification.value != "NOT_QUALIFIED"
    )
    missing = sorted(
        {
            reference
            for hypothesis in case.hypotheses
            for reference in hypothesis.unresolved_evidence_refs
        }
        | {
            f"{question.expected_evidence_type}:{question.question_id}"
            for question in case.operator_questions
            if question.status == "OPEN"
        }
    )
    change_conditions = list(dict.fromkeys(case.loop_control.resume_requires))
    if not change_conditions:
        change_conditions = ["具名质量负责人提交与当前 case SHA 绑定的决定"]
    capa = case.gate_context.capa_evidence
    causal_level = (
        "L4_INTERVENTION_SUPPORTED"
        if capa is not None and capa.recovery_success
        else "L1_ASSOCIATED"
    )
    stable = {
        "schema_version": "visiondata-gate.contrastive-decision-packet.v1",
        "case_id": case.case_id,
        "case_sha256": case.case_sha256,
        "current_status": case.status.value,
        "current_recommendation": case.recommendation.value,
        "recommendation_reason": case.recommendation_reason,
        "observed_facts": case.decision_summary.observed_facts,
        "qualified_evidence_refs": qualified_refs,
        "blocking_issue_codes": sorted(
            issue.issue_code
            for issue in case.evidence_issues
            if issue.blocks_disposition
        ),
        "hypothesis_contrasts": [
            IncidentHypothesisContrast(
                hypothesis_id=hypothesis.hypothesis_id,
                category=hypothesis.category,
                status=hypothesis.status.value,
                supporting_issue_codes=hypothesis.supporting_issue_codes,
                contradicting_issue_codes=hypothesis.contradicting_issue_codes,
                unresolved_evidence_refs=hypothesis.unresolved_evidence_refs,
                next_discriminating_test=hypothesis.next_discriminating_test,
            )
            for hypothesis in case.hypotheses
        ],
        "selected_workers": [
            IncidentWorkerChoice(
                worker_role=receipt.worker_role,
                invocation_id=receipt.invocation_id,
                trigger_reason_codes=receipt.trigger_reason_codes,
                receipt_sha256=receipt.receipt_sha256,
                result=receipt.status,
            )
            for receipt in case.worker_receipts
        ],
        "action_contrasts": _build_action_contrasts(
            case,
            qualified_refs=qualified_refs,
            change_conditions=change_conditions,
        ),
        "missing_evidence_refs": missing,
        "what_would_change_decision": change_conditions,
        "maximum_causal_claim_level": causal_level,
        "root_cause_status": "NOT_ESTABLISHED",
        "production_release_allowed": False,
        "machine_write_permitted": False,
        "plan_tree_sha256": plan_tree.tree_sha256,
        "authority_ledger_sha256": authority_ledger.ledger_sha256,
    }
    packet = ContrastiveIncidentDecisionPacket(
        **stable,
        packet_sha256=_sha256(stable),
    )
    verify_contrastive_decision_packet(
        packet,
        case=case,
        plan_tree=plan_tree,
        authority_ledger=authority_ledger,
    )
    return packet


def verify_contrastive_decision_packet(
    packet: ContrastiveIncidentDecisionPacket,
    *,
    case: IndustrialIncidentCase,
    plan_tree: TypedIncidentPlanTree,
    authority_ledger: IncidentAuthorityLedger,
) -> None:
    _verify_seal(
        packet,
        "packet_sha256",
        "contrastive incident decision packet failed SHA-256 validation",
    )
    if packet.case_id != case.case_id or not hmac.compare_digest(
        packet.case_sha256, case.case_sha256
    ):
        raise ValueError("contrastive incident decision packet failed case binding")
    if packet.current_status != case.status.value or (
        packet.current_recommendation != case.recommendation.value
    ):
        raise ValueError("contrastive incident decision packet changed the disposition")
    if not hmac.compare_digest(packet.plan_tree_sha256, plan_tree.tree_sha256):
        raise ValueError("contrastive incident decision packet failed plan binding")
    if not hmac.compare_digest(
        packet.authority_ledger_sha256,
        authority_ledger.ledger_sha256,
    ):
        raise ValueError(
            "contrastive incident decision packet failed authority binding"
        )
    expected_workers = [
        IncidentWorkerChoice(
            worker_role=receipt.worker_role,
            invocation_id=receipt.invocation_id,
            trigger_reason_codes=receipt.trigger_reason_codes,
            receipt_sha256=receipt.receipt_sha256,
            result=receipt.status,
        )
        for receipt in case.worker_receipts
    ]
    if packet.selected_workers != expected_workers:
        raise ValueError("contrastive incident decision packet changed Worker history")
    expected_hypotheses = [
        IncidentHypothesisContrast(
            hypothesis_id=hypothesis.hypothesis_id,
            category=hypothesis.category,
            status=hypothesis.status.value,
            supporting_issue_codes=hypothesis.supporting_issue_codes,
            contradicting_issue_codes=hypothesis.contradicting_issue_codes,
            unresolved_evidence_refs=hypothesis.unresolved_evidence_refs,
            next_discriminating_test=hypothesis.next_discriminating_test,
        )
        for hypothesis in case.hypotheses
    ]
    expected_missing = sorted(
        {
            reference
            for hypothesis in case.hypotheses
            for reference in hypothesis.unresolved_evidence_refs
        }
        | {
            f"{question.expected_evidence_type}:{question.question_id}"
            for question in case.operator_questions
            if question.status == "OPEN"
        }
    )
    expected_change_conditions = list(dict.fromkeys(case.loop_control.resume_requires))
    if not expected_change_conditions:
        expected_change_conditions = ["具名质量负责人提交与当前 case SHA 绑定的决定"]
    expected_qualified_refs = sorted(
        evidence.evidence_ref
        for evidence in case.evidence_refs
        if evidence.qualification.value != "NOT_QUALIFIED"
    )
    expected_blocking_codes = sorted(
        issue.issue_code for issue in case.evidence_issues if issue.blocks_disposition
    )
    capa = case.gate_context.capa_evidence
    expected_causal_level = (
        "L4_INTERVENTION_SUPPORTED"
        if capa is not None and capa.recovery_success
        else "L1_ASSOCIATED"
    )
    if (
        packet.recommendation_reason != case.recommendation_reason
        or packet.observed_facts != case.decision_summary.observed_facts
        or packet.qualified_evidence_refs != expected_qualified_refs
        or packet.blocking_issue_codes != expected_blocking_codes
        or packet.hypothesis_contrasts != expected_hypotheses
        or packet.missing_evidence_refs != expected_missing
        or packet.what_would_change_decision != expected_change_conditions
        or packet.maximum_causal_claim_level != expected_causal_level
        or packet.action_contrasts
        != _build_action_contrasts(
            case,
            qualified_refs=expected_qualified_refs,
            change_conditions=expected_change_conditions,
        )
    ):
        raise ValueError(
            "contrastive incident decision packet changed Case evidence semantics"
        )


class IncidentControlPlaneBundle(ProductModel):
    schema_version: Literal["visiondata-gate.incident-control-plane.v1"] = (
        "visiondata-gate.incident-control-plane.v1"
    )
    case_id: str = Field(pattern=r"^incident_[0-9a-f]{20}$")
    case_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    plan_tree: TypedIncidentPlanTree
    authority_ledger: IncidentAuthorityLedger
    decision_packet: ContrastiveIncidentDecisionPacket
    bundle_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    claim_boundary: str = (
        "This sealed sidecar exposes executed planning, receipt authority, and "
        "decision contrasts. It is not hidden reasoning, a live factory connection, "
        "root-cause proof, production release, or equipment-control authority."
    )


def build_incident_control_plane(
    case: IndustrialIncidentCase,
) -> IncidentControlPlaneBundle:
    tree = build_typed_incident_plan_tree(case)
    authority = build_incident_authority_ledger(case)
    packet = build_contrastive_decision_packet(
        case,
        plan_tree=tree,
        authority_ledger=authority,
    )
    stable = {
        "schema_version": "visiondata-gate.incident-control-plane.v1",
        "case_id": case.case_id,
        "case_sha256": case.case_sha256,
        "plan_tree": tree,
        "authority_ledger": authority,
        "decision_packet": packet,
        "claim_boundary": (
            "This sealed sidecar exposes executed planning, receipt authority, and "
            "decision contrasts. It is not hidden reasoning, a live factory "
            "connection, root-cause proof, production release, or equipment-control "
            "authority."
        ),
    }
    bundle = IncidentControlPlaneBundle(
        **stable,
        bundle_sha256=_sha256(stable),
    )
    verify_incident_control_plane(bundle, case=case)
    return bundle


def verify_incident_control_plane(
    bundle: IncidentControlPlaneBundle,
    *,
    case: IndustrialIncidentCase,
) -> None:
    verify_typed_incident_plan_tree(bundle.plan_tree, case=case)
    verify_incident_authority_ledger(bundle.authority_ledger, case=case)
    verify_contrastive_decision_packet(
        bundle.decision_packet,
        case=case,
        plan_tree=bundle.plan_tree,
        authority_ledger=bundle.authority_ledger,
    )
    _verify_seal(
        bundle,
        "bundle_sha256",
        "incident control-plane bundle failed SHA-256 validation",
    )
    if bundle.case_id != case.case_id or not hmac.compare_digest(
        bundle.case_sha256, case.case_sha256
    ):
        raise ValueError("incident control-plane bundle failed case binding")


__all__ = [
    "ContrastiveIncidentDecisionPacket",
    "IncidentAuthorityLedger",
    "IncidentAuthorityState",
    "IncidentControlPlaneBundle",
    "IncidentPlanNode",
    "IncidentPlanNodeStatus",
    "IncidentPlanNodeType",
    "IncidentWorkerAuthorityCheck",
    "IncidentWorkerCapabilityGrant",
    "TypedIncidentPlanTree",
    "build_contrastive_decision_packet",
    "build_incident_authority_ledger",
    "build_incident_control_plane",
    "build_typed_incident_plan_tree",
    "check_incident_worker_authority",
    "verify_contrastive_decision_packet",
    "verify_incident_authority_ledger",
    "verify_incident_control_plane",
    "verify_typed_incident_plan_tree",
]
