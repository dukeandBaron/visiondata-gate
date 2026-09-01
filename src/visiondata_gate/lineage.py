"""Immutable parent-child lineage for remediation and re-verification runs."""

from __future__ import annotations

import hashlib
import hmac
from typing import Literal

from pydantic import Field

from .evidence import canonical_json_bytes
from .product_models import (
    DataSourceKind,
    ProductModel,
    TaskExecutionStatus,
    TaskRecord,
)


class CreateReverificationRequest(ProductModel):
    """Request a new run without mutating or replacing the parent decision."""

    note: str = Field(min_length=4, max_length=1000)
    source_id: str | None = Field(default=None, min_length=1)


class TaskLineageEdge(ProductModel):
    """Append-only binding between one completed run and its re-verification."""

    schema_version: Literal["visiondata-gate.task-lineage-edge.v1"] = (
        "visiondata-gate.task-lineage-edge.v1"
    )
    child_task_id: str
    parent_task_id: str
    root_task_id: str
    relation: Literal["reverification"] = "reverification"
    depth: int = Field(ge=1)
    parent_request_sha256: str = Field(min_length=64, max_length=64)
    parent_evidence_sha256: str = Field(min_length=64, max_length=64)
    contract_sha256: str = Field(min_length=64, max_length=64)
    created_by: str
    note: str = Field(min_length=4, max_length=1000)
    created_at: str
    edge_sha256: str = Field(min_length=64, max_length=64)


class TaskLineageNode(ProductModel):
    task_id: str
    parent_task_id: str | None = None
    depth: int = Field(ge=0)
    relation: Literal["initial", "reverification"]
    execution_status: TaskExecutionStatus
    final_decision: str | None = None
    request_sha256: str = Field(min_length=64, max_length=64)
    evidence_sha256: str | None = None
    source_kind: DataSourceKind
    source_id: str | None = None
    source_binding_sha256: str | None = Field(default=None, pattern=r"^[0-9a-f]{64}$")
    created_at: str
    completed_at: str | None = None
    is_focus: bool


class TaskLineageReport(ProductModel):
    """Hash-sealed projection of a run family; it does not mutate frozen evidence."""

    schema_version: Literal["visiondata-gate.task-lineage.v1"] = (
        "visiondata-gate.task-lineage.v1"
    )
    root_task_id: str
    focus_task_id: str
    latest_task_id: str
    contract_sha256: str = Field(min_length=64, max_length=64)
    node_count: int = Field(ge=1)
    edge_count: int = Field(ge=0)
    nodes: list[TaskLineageNode] = Field(min_length=1)
    edges: list[TaskLineageEdge]
    report_sha256: str = Field(min_length=64, max_length=64)
    claim_boundary: str = (
        "Lineage proves local parent/child request and evidence-hash bindings. It does "
        "not prove that remediation was correct, that a customer accepted the result, "
        "or that production release was authorized."
    )


def task_contract_sha256_from_values(
    *,
    project_id: str,
    scenario_profile: str,
    source_kind: str,
    allowed_tools: list[str],
    seed: int,
) -> str:
    """Hash the policy-bearing fields that a re-verification must inherit."""

    payload = {
        "schema_version": "visiondata-gate.reverification-contract.v1",
        "project_id": project_id,
        "scenario_profile": scenario_profile,
        "source_kind": source_kind,
        "allowed_tools": allowed_tools,
        "seed": seed,
        "runtime_backend": "deterministic",
        "policy_authority": "frozen_policy_judge",
        "production_authority": "human_only",
    }
    return hashlib.sha256(canonical_json_bytes(payload)).hexdigest()


def task_contract_sha256(task: TaskRecord) -> str:
    return task_contract_sha256_from_values(
        project_id=task.project_id,
        scenario_profile=task.scenario_profile.value,
        source_kind=task.source_kind.value,
        allowed_tools=task.allowed_tools,
        seed=task.seed,
    )


def seal_task_lineage_edge(**values: object) -> TaskLineageEdge:
    stable = {
        **values,
        "schema_version": "visiondata-gate.task-lineage-edge.v1",
        "relation": "reverification",
    }
    stable.pop("edge_sha256", None)
    digest = hashlib.sha256(canonical_json_bytes(stable)).hexdigest()
    return TaskLineageEdge(**stable, edge_sha256=digest)


def verify_task_lineage_edge(edge: TaskLineageEdge) -> bool:
    payload = edge.model_dump(mode="json", exclude={"edge_sha256"})
    observed = hashlib.sha256(canonical_json_bytes(payload)).hexdigest()
    return hmac.compare_digest(observed, edge.edge_sha256)


def build_task_lineage_report(
    *,
    focus_task_id: str,
    tasks: list[TaskRecord],
    edges: list[TaskLineageEdge],
    source_binding_sha256_by_id: dict[str, str] | None = None,
) -> TaskLineageReport:
    if not tasks:
        raise ValueError("task lineage cannot be empty")
    by_id = {task.task_id: task for task in tasks}
    source_bindings = source_binding_sha256_by_id or {}
    edge_by_child = {edge.child_task_id: edge for edge in edges}
    root_candidates = [task for task in tasks if task.task_id not in edge_by_child]
    if len(root_candidates) != 1:
        raise ValueError("task lineage must contain exactly one root")
    root = root_candidates[0]
    contract_sha256 = task_contract_sha256(root)
    nodes: list[TaskLineageNode] = []
    for task in tasks:
        if not hmac.compare_digest(task_contract_sha256(task), contract_sha256):
            raise ValueError("task lineage contract drift detected")
        edge = edge_by_child.get(task.task_id)
        if edge is not None:
            if edge.parent_task_id not in by_id or edge.root_task_id != root.task_id:
                raise ValueError("task lineage edge references an unknown task")
            parent = by_id[edge.parent_task_id]
            if edge.parent_request_sha256 != parent.request_sha256:
                raise ValueError("task lineage parent request binding failed")
            if edge.parent_evidence_sha256 != parent.evidence_sha256:
                raise ValueError("task lineage parent evidence binding failed")
            if not hmac.compare_digest(edge.contract_sha256, contract_sha256):
                raise ValueError("task lineage edge contract binding failed")
            if not verify_task_lineage_edge(edge):
                raise ValueError("task lineage edge digest failed")
            parent_depth = edge_by_child.get(parent.task_id)
            expected_depth = 1 if parent_depth is None else parent_depth.depth + 1
            if edge.depth != expected_depth:
                raise ValueError("task lineage depth is inconsistent")
        nodes.append(
            TaskLineageNode(
                task_id=task.task_id,
                parent_task_id=edge.parent_task_id if edge else None,
                depth=edge.depth if edge else 0,
                relation="reverification" if edge else "initial",
                execution_status=task.execution_status,
                final_decision=task.final_decision,
                request_sha256=task.request_sha256,
                evidence_sha256=task.evidence_sha256,
                source_kind=task.source_kind,
                source_id=task.source_id,
                source_binding_sha256=(
                    source_bindings.get(task.source_id) if task.source_id else None
                ),
                created_at=task.created_at,
                completed_at=task.completed_at,
                is_focus=task.task_id == focus_task_id,
            )
        )
    nodes.sort(key=lambda item: (item.depth, item.created_at, item.task_id))
    ordered_edges = sorted(edges, key=lambda item: (item.depth, item.created_at))
    latest = max(nodes, key=lambda item: (item.created_at, item.task_id))
    stable = {
        "schema_version": "visiondata-gate.task-lineage.v1",
        "root_task_id": root.task_id,
        "focus_task_id": focus_task_id,
        "latest_task_id": latest.task_id,
        "contract_sha256": contract_sha256,
        "node_count": len(nodes),
        "edge_count": len(ordered_edges),
        "nodes": nodes,
        "edges": ordered_edges,
        "claim_boundary": TaskLineageReport.model_fields["claim_boundary"].default,
    }
    digest = hashlib.sha256(canonical_json_bytes(stable)).hexdigest()
    return TaskLineageReport(**stable, report_sha256=digest)


__all__ = [
    "CreateReverificationRequest",
    "TaskLineageEdge",
    "TaskLineageNode",
    "TaskLineageReport",
    "build_task_lineage_report",
    "seal_task_lineage_edge",
    "task_contract_sha256",
    "task_contract_sha256_from_values",
    "verify_task_lineage_edge",
]
