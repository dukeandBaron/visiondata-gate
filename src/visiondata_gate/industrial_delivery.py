"""Industrial delivery receipt derived from one completed evidence-first Gate run."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any, Literal

from pydantic import Field, model_validator

from .contracts import Finding, GateResult, WorkOrder
from .evidence import canonical_json_bytes, sha256_file
from .product_models import (
    DataSourceKind,
    LocalSourceAuthorizationReceipt,
    ProductModel,
    TaskRecord,
)
from .runtime_models import RuntimeTrace


class IndustrialEvidenceSource(ProductModel):
    source_type: Literal[
        "image_batch",
        "mask_annotation",
        "manifest_metadata",
        "tool_measurement",
        "frozen_policy",
        "operator_authorization",
    ]
    evidence_ref: str
    evidence_sha256: str = Field(min_length=64, max_length=64)
    observed_count: int = Field(ge=0)
    status: Literal["used", "operator_attested"]
    role_in_decision: str


class IndustrialInspectionContractBinding(ProductModel):
    """Run-bound proof that tool parameters came from one frozen contract.

    The project contract is intentionally not labelled as a certified AQL
    standard.  It is a strict, project-defined inspection contract whose
    thresholds and tool adapters are captured in the run evidence.
    """

    schema_version: Literal["visiondata-gate.inspection-contract-binding.v1"] = (
        "visiondata-gate.inspection-contract-binding.v1"
    )
    contract_id: str = Field(min_length=1)
    policy_version: str = Field(min_length=1)
    enforced_tools: list[str] = Field(min_length=1)
    tool_parameter_sha256: dict[str, str]
    tool_contract_sha256: dict[str, str]
    input_contract_bound: Literal[True] = True
    same_contract_child_run_required: Literal[True] = True
    aql_interpretation: Literal[
        "PROJECT_DEFINED_QUALITY_CONTRACT_NOT_CERTIFIED_AQL"
    ] = "PROJECT_DEFINED_QUALITY_CONTRACT_NOT_CERTIFIED_AQL"
    binding_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    claim_boundary: str = (
        "This binds the observed run to one project-defined contract and its "
        "tool parameters. It is not a certified AQL plan, customer acceptance "
        "specification, or permission to release production data."
    )


class IndustrialEvidenceFact(ProductModel):
    """One redacted, hash-bound fact contributing to a fusion entry."""

    source_kind: Literal[
        "pixel_measurement",
        "annotation_geometry",
        "partition_fingerprint",
        "manifest_metadata",
        "coverage_measurement",
        "tool_measurement",
    ]
    finding_id: str
    code: str
    tool: str
    sample_ids: list[str]
    evidence_ref: str
    evidence_status: str
    observed: dict[str, Any]
    evidence_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")


class IndustrialEvidenceFusionEntry(ProductModel):
    """Explain how measured facts, policy, and work ownership were joined.

    Entries may be single-measurement plus policy mappings.  The schema never
    upgrades that situation to cross-source corroboration merely to make the
    UI look stronger.
    """

    schema_version: Literal["visiondata-gate.evidence-fusion-entry.v1"] = (
        "visiondata-gate.evidence-fusion-entry.v1"
    )
    entry_id: str = Field(pattern=r"^fusion_[0-9a-f]{20}$")
    primary_finding_id: str
    issue_code: str
    sample_ids: list[str]
    corroborating_finding_ids: list[str]
    source_kinds: list[str] = Field(min_length=2)
    evidence_facts: list[IndustrialEvidenceFact] = Field(min_length=1)
    policy_ref: str
    work_order_ids: list[str]
    assigned_roles: list[str]
    arbitration_basis: list[str] = Field(min_length=1)
    fusion_status: Literal[
        "CROSS_SOURCE_CORROBORATED",
        "SINGLE_MEASUREMENT_WITH_POLICY_MAPPING",
    ]
    root_cause_established: Literal[False] = False
    machine_action_permitted: Literal[False] = False
    entry_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    claim_boundary: str = (
        "This entry explains evidence association and deterministic policy mapping. "
        "It does not establish physical root cause, execute a repair, or authorize "
        "machine or production action."
    )


class IndustrialDynamicExecutionLedger(ProductModel):
    """Budget view over evidence-triggered deterministic follow-up Workers."""

    schema_version: Literal["visiondata-gate.dynamic-execution-ledger.v1"] = (
        "visiondata-gate.dynamic-execution-ledger.v1"
    )
    topology: Literal["EVIDENCE_TRIGGERED_BOUNDED_PARALLEL"] = (
        "EVIDENCE_TRIGGERED_BOUNDED_PARALLEL"
    )
    dispatch_protocol: str
    budget_status: Literal[
        "ENFORCED_WITHIN_LIMIT",
        "ENFORCED_WITH_SKIPS",
        "LEGACY_NOT_RECORDED",
    ]
    budget_limit_units: int | None = Field(default=None, ge=0)
    consumed_units: int | None = Field(default=None, ge=0)
    candidate_count: int | None = Field(default=None, ge=0)
    awarded_count: int | None = Field(default=None, ge=0)
    completed_count: int | None = Field(default=None, ge=0)
    failed_count: int | None = Field(default=None, ge=0)
    budget_exhausted_count: int | None = Field(default=None, ge=0)
    task_ids: list[str]
    dependency_semantics: Literal["EVIDENCE_REFS_NOT_WORKER_CHAIN"] = (
        "EVIDENCE_REFS_NOT_WORKER_CHAIN"
    )
    token_budget_status: Literal["NOT_APPLICABLE_DETERMINISTIC_WORKERS"] = (
        "NOT_APPLICABLE_DETERMINISTIC_WORKERS"
    )
    within_allocated_budget: bool | None
    claim_boundary: str = (
        "Cost units and wall-clock durations describe deterministic follow-up tools. "
        "They are not LLM tokens, factory SLA evidence, or a distributed-runtime claim."
    )


class IndustrialTriageStage(ProductModel):
    tier: Literal["L1", "L2", "L3"]
    name: str
    input_count: int = Field(ge=0)
    selected_count: int = Field(ge=0)
    operation: str
    selection_basis: str
    evidence_refs: list[str] = Field(min_length=1)
    status: Literal["COMPLETED", "COMPLETED_WITH_BUDGET_SKIPS"]

    @model_validator(mode="after")
    def validate_stage_counts(self) -> IndustrialTriageStage:
        if self.selected_count > self.input_count:
            raise ValueError("triage selected_count cannot exceed input_count")
        return self


class IndustrialBatchTriageLedger(ProductModel):
    """Truthful three-stage projection of the currently executed Omni flow."""

    schema_version: Literal["visiondata-gate.batch-triage-ledger.v1"] = (
        "visiondata-gate.batch-triage-ledger.v1"
    )
    stages: list[IndustrialTriageStage] = Field(min_length=3, max_length=3)
    source_assets_copied: bool = False
    full_source_policy_gate_claimed: Literal[False] = False
    throughput_benchmark_claimed: Literal[False] = False
    ledger_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    claim_boundary: str = (
        "L1 is a full-source read-only structure/metadata profile, not a full pixel "
        "Policy Gate. L2 is the frozen stratified Gate denominator. L3 contains only "
        "evidence-triggered follow-ups. No 10,000-image SLA is claimed."
    )


class IndustrialDynamicResponse(ProductModel):
    task_id: str
    trigger: str
    worker_id: str
    status: str
    decision_effect: str
    stop_condition: str
    input_refs: list[str]
    new_evidence_refs: list[str]
    result_sha256: str = Field(min_length=64, max_length=64)
    dispatch_index: int | None = Field(default=None, ge=1)
    dispatch_mode: str = "legacy_not_recorded"
    dispatch_protocol: str = "legacy_not_recorded"
    duration_ms: float | None = Field(default=None, ge=0.0)
    allocated_cost_units: int | None = Field(default=None, ge=0)
    consumed_cost_units: int | None = Field(default=None, ge=0)
    budget_status: Literal[
        "WITHIN_BUDGET",
        "NOT_EXECUTED_BUDGET_EXHAUSTED",
        "LEGACY_NOT_RECORDED",
    ] = "LEGACY_NOT_RECORDED"


class IndustrialEvidenceSpan(ProductModel):
    finding_id: str
    code: str
    tool: str
    sample_ids: list[str]
    summary: str


class IndustrialExecutableWorkOrder(ProductModel):
    work_order_id: str
    action: str
    priority: str
    status: str
    ai_expert_role: str
    required_skill: str
    human_owner_role: str
    prerequisites: list[str]
    acceptance_criteria: list[str]
    human_confirmation_point: str
    machine_action_permitted: Literal[False] = False
    evidence_span: list[IndustrialEvidenceSpan]
    evidence_refs: list[str]
    reason_trace: list[str]
    dynamic_task_refs: list[str]


class IndustrialRiskCluster(ProductModel):
    """Operational view over evidence-linked atomic work orders.

    A cluster reduces operator overload without merging or closing the atomic
    evidence records underneath it.  Counts therefore describe this bounded
    Gate run only; they are not a full-source defect estimate.
    """

    schema_version: Literal["visiondata-gate.industrial-risk-cluster.v1"] = (
        "visiondata-gate.industrial-risk-cluster.v1"
    )
    risk_cluster_id: str = Field(min_length=1)
    title: str = Field(min_length=1)
    objective: str = Field(min_length=1)
    action: str
    priority: str
    reason_codes: list[str] = Field(min_length=1)
    finding_ids: list[str] = Field(min_length=1)
    work_order_ids: list[str] = Field(min_length=1)
    sample_ids: list[str]
    affected_sample_count: int = Field(ge=0)
    sampleless_work_order_count: int = Field(ge=0)
    atomic_work_order_count: int = Field(ge=1)
    human_owner_role: str
    required_skill: str
    dynamic_task_refs: list[str]
    machine_action_permitted: Literal[False] = False
    cluster_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    claim_boundary: str = (
        "This is an operational aggregation of atomic findings and work orders in "
        "one bounded Gate run. It is not a root-cause conclusion, executed repair, "
        "full-source prevalence estimate, or production approval."
    )


class IndustrialRemediationWave(ProductModel):
    """One dependency-ordered wave in a candidate corrective-action plan."""

    wave_id: str = Field(min_length=1)
    sequence: int = Field(ge=1)
    objective: str = Field(min_length=1)
    work_order_ids: list[str]
    owner_roles: list[str]
    prerequisite_wave_ids: list[str]
    acceptance_gate: str = Field(min_length=1)


class IndustrialRemediationPlan(ProductModel):
    """A deterministic option for containment, recovery, and child-run review.

    Effort points are relative ordering aids derived from frozen action and
    priority weights.  They are deliberately not hours, money, or a promise of
    closure.
    """

    schema_version: Literal["visiondata-gate.industrial-remediation-plan.v1"] = (
        "visiondata-gate.industrial-remediation-plan.v1"
    )
    task_id: str
    run_id: str
    plan_id: str
    strategy: Literal[
        "containment_first", "actionable_recovery", "full_evidence_closure"
    ]
    title: str
    objective: str
    selected_work_order_ids: list[str] = Field(min_length=1)
    deferred_work_order_ids: list[str]
    targeted_finding_ids: list[str]
    evidence_coverage_ratio: float = Field(ge=0.0, le=1.0)
    relative_effort_points: int = Field(ge=1)
    waves: list[IndustrialRemediationWave] = Field(min_length=1)
    residual_risk_codes: list[str]
    review_eligibility: Literal[
        "containment_only",
        "partial_recheck_required",
        "full_closure_recheck_required",
    ]
    same_contract_child_run_required: Literal[True] = True
    production_release_allowed: Literal[False] = False
    plan_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    claim_boundary: str = (
        "This is a deterministic remediation option, not an executed repair, cost "
        "estimate, guaranteed finding closure, or production release approval."
    )


class IndustrialDeliveryReceipt(ProductModel):
    schema_version: Literal[
        "visiondata-gate.industrial-delivery.v1",
        "visiondata-gate.industrial-delivery.v2",
        "visiondata-gate.industrial-delivery.v3",
    ] = "visiondata-gate.industrial-delivery.v3"
    task_id: str
    run_id: str
    target_user: str
    industrial_task: str
    final_decision: str
    decision_reason: str
    policy_version: str
    inspection_contract: IndustrialInspectionContractBinding | None = None
    multi_source_fusion: list[IndustrialEvidenceSource] = Field(min_length=6)
    evidence_fusion_matrix: list[IndustrialEvidenceFusionEntry] = Field(
        default_factory=list
    )
    evidence_fusion_matrix_sha256: str | None = Field(
        default=None, pattern=r"^[0-9a-f]{64}$"
    )
    dynamic_responses: list[IndustrialDynamicResponse]
    dynamic_execution_ledger: IndustrialDynamicExecutionLedger | None = None
    batch_triage: IndustrialBatchTriageLedger | None = None
    risk_clusters: list[IndustrialRiskCluster] = Field(default_factory=list)
    executable_work_orders: list[IndustrialExecutableWorkOrder]
    remediation_plans: list[IndustrialRemediationPlan] = Field(default_factory=list)
    autonomy_level: Literal["L2_recommendation_only"] = "L2_recommendation_only"
    allowed_agent_actions: list[str]
    forbidden_agent_actions: list[str]
    production_human_approval_required: Literal[True] = True
    production_approval_status: Literal["pending"] = "pending"
    source_assets_copied_into_product: bool = False
    model_call_count: int = Field(ge=0)
    anomaly_model_backend: Literal["NOT_CONNECTED"] = "NOT_CONNECTED"
    unresolved_boundaries: list[str]
    claim_boundary: str


_ACTION_GUIDANCE = {
    "RECAPTURE": {
        "ai_expert_role": "Acquisition Quality Expert Agent",
        "required_skill": "industrial-image-acquisition-quality",
        "human_owner_role": "industrial_data_owner",
        "prerequisites": [
            "隔离受影响样本并保留原始证据哈希",
            "确认成像设备、光照、曝光和采集工位约束",
        ],
        "acceptance_criteria": [
            "重采样本通过图像质量、覆盖和标注完整性复验",
            "复验结果绑定新输入哈希且不覆盖原始裁决",
        ],
    },
    "RELABEL": {
        "ai_expert_role": "Annotation Integrity Expert Agent",
        "required_skill": "industrial-annotation-integrity",
        "human_owner_role": "annotation_quality_owner",
        "prerequisites": [
            "锁定标注规范版本和受影响样本范围",
            "保留修改前标注及其哈希",
        ],
        "acceptance_criteria": [
            "修改后标注满足尺寸、mask 和类别约束",
            "双人或授权责任人抽检通过后再进入复验",
        ],
    },
    "REMOVE_OR_REPARTITION": {
        "ai_expert_role": "Dataset Leakage Governance Agent",
        "required_skill": "industrial-dataset-split-governance",
        "human_owner_role": "dataset_governance_owner",
        "prerequisites": [
            "确认重复或泄漏证据及关联 split",
            "生成不覆盖原清单的候选重划分方案",
        ],
        "acceptance_criteria": [
            "跨 split 重复与近重复规则复验通过",
            "新 manifest 的哈希、差异和回滚点均可审计",
        ],
    },
    "INVESTIGATE": {
        "ai_expert_role": "Industrial Root-Cause Review Agent",
        "required_skill": "industrial-evidence-conflict-investigation",
        "human_owner_role": "quality_or_safety_owner",
        "prerequisites": [
            "冻结冲突证据、规则版本和工具调用回执",
            "禁止在冲突未消解前自动修复或放行",
        ],
        "acceptance_criteria": [
            "根因、处置选择和反证条件均形成书面记录",
            "授权责任人确认后才能触发后续数据变更",
        ],
    },
}

_ACTION_ORDER = {
    "INVESTIGATE": 0,
    "REMOVE_OR_REPARTITION": 1,
    "RELABEL": 2,
    "RECAPTURE": 3,
}
_ACTION_EFFORT = {
    "INVESTIGATE": 5,
    "REMOVE_OR_REPARTITION": 2,
    "RELABEL": 2,
    "RECAPTURE": 3,
}
_PRIORITY_ORDER = {"critical": 0, "high": 1, "medium": 2, "low": 3}
_PRIORITY_EFFORT = {"critical": 3, "high": 2, "medium": 1, "low": 1}

_RISK_CLUSTER_GUIDANCE = {
    "INVESTIGATE": {
        "risk_cluster_id": "RISK-EVIDENCE-INVESTIGATION",
        "title": "证据冲突与治理调查",
        "objective": "先冻结冲突证据并完成责任人复核，未消解前持续阻断。",
    },
    "REMOVE_OR_REPARTITION": {
        "risk_cluster_id": "RISK-SPLIT-GOVERNANCE",
        "title": "重复泄漏与数据划分治理",
        "objective": "生成可回滚的候选重划分，复验跨集合重复与近重复规则。",
    },
    "RELABEL": {
        "risk_cluster_id": "RISK-ANNOTATION-RECOVERY",
        "title": "标注完整性恢复",
        "objective": "按冻结规范修订候选标注，并由授权责任人抽检后复验。",
    },
    "RECAPTURE": {
        "risk_cluster_id": "RISK-ACQUISITION-RECOVERY",
        "title": "采集质量恢复",
        "objective": "隔离受影响样本，按成像约束形成候选重采批次并复验。",
    },
}


def _load_json(path: Path) -> dict[str, object]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError(f"industrial evidence must be a JSON object: {path.name}")
    return payload


def _fact_source_kind(finding: Finding) -> str:
    tool = finding.tool.casefold()
    code = finding.code.casefold()
    if tool == "image_quality" or any(
        token in code for token in ("sharp", "expos", "luma", "decode")
    ):
        return "pixel_measurement"
    if "annotation" in tool or any(
        token in code for token in ("bbox", "mask", "geometry", "dimension")
    ):
        return "annotation_geometry"
    if "duplicate" in tool or any(
        token in code for token in ("duplicate", "leakage", "split")
    ):
        return "partition_fingerprint"
    if tool == "coverage_matrix" or "coverage" in code:
        return "coverage_measurement"
    if tool == "governance_audit" or any(
        token in code for token in ("metadata", "manifest", "scope")
    ):
        return "manifest_metadata"
    return "tool_measurement"


def _build_inspection_contract_binding(
    gate: GateResult,
) -> IndustrialInspectionContractBinding:
    parameter_hashes = {
        f"{trace.sequence}:{trace.tool}": hashlib.sha256(
            canonical_json_bytes(trace.parameters)
        ).hexdigest()
        for trace in gate.tool_trace
    }
    contract_hashes = {
        f"{trace.sequence}:{trace.tool}": trace.contract_digest
        for trace in gate.tool_trace
        if trace.contract_digest is not None
    }
    stable = {
        "schema_version": "visiondata-gate.inspection-contract-binding.v1",
        "contract_id": gate.contract_id,
        "policy_version": gate.policy_version,
        "enforced_tools": sorted({trace.tool for trace in gate.tool_trace}),
        "tool_parameter_sha256": parameter_hashes,
        "tool_contract_sha256": contract_hashes,
        "input_contract_bound": True,
        "same_contract_child_run_required": True,
        "aql_interpretation": ("PROJECT_DEFINED_QUALITY_CONTRACT_NOT_CERTIFIED_AQL"),
        "claim_boundary": IndustrialInspectionContractBinding.model_fields[
            "claim_boundary"
        ].default,
    }
    return IndustrialInspectionContractBinding(
        **stable,
        binding_sha256=hashlib.sha256(canonical_json_bytes(stable)).hexdigest(),
    )


def _build_evidence_fusion_matrix(
    gate: GateResult,
    work_orders: list[IndustrialExecutableWorkOrder],
) -> tuple[list[IndustrialEvidenceFusionEntry], str]:
    entries: list[IndustrialEvidenceFusionEntry] = []
    for finding in sorted(gate.findings, key=lambda item: item.finding_id):
        primary_samples = set(finding.sample_ids)
        related = [
            candidate
            for candidate in gate.findings
            if candidate.finding_id == finding.finding_id
            or (
                candidate.code == finding.code
                and bool(primary_samples)
                and bool(primary_samples.intersection(candidate.sample_ids))
            )
        ]
        related.sort(key=lambda item: item.finding_id)
        related_ids = {item.finding_id for item in related}
        facts = [
            IndustrialEvidenceFact(
                source_kind=_fact_source_kind(item),
                finding_id=item.finding_id,
                code=item.code,
                tool=item.tool,
                sample_ids=sorted(item.sample_ids),
                evidence_ref=f"finding:{item.finding_id}",
                evidence_status=item.evidence_status.value,
                observed=dict(item.evidence),
                evidence_sha256=hashlib.sha256(
                    canonical_json_bytes(
                        {
                            "finding_id": item.finding_id,
                            "code": item.code,
                            "tool": item.tool,
                            "sample_ids": sorted(item.sample_ids),
                            "evidence_status": item.evidence_status.value,
                            "observed": item.evidence,
                        }
                    )
                ).hexdigest(),
            )
            for item in related
        ]
        matched_orders = [
            order
            for order in work_orders
            if related_ids.intersection(span.finding_id for span in order.evidence_span)
        ]
        arbitration_basis = list(
            dict.fromkeys(
                reason for order in matched_orders for reason in order.reason_trace
            )
        )
        if not arbitration_basis:
            arbitration_basis = [
                f"{finding.tool} measured {finding.code}; frozen policy "
                f"{gate.policy_version} retained the finding without inventing "
                "a root-cause conclusion."
            ]
        measurement_kinds = {fact.source_kind for fact in facts}
        source_kinds = sorted({*measurement_kinds, "frozen_policy"})
        entry_identity = {
            "primary_finding_id": finding.finding_id,
            "corroborating_finding_ids": [item.finding_id for item in related],
            "work_order_ids": sorted(order.work_order_id for order in matched_orders),
            "policy_version": gate.policy_version,
        }
        entry_id = (
            "fusion_"
            + hashlib.sha256(canonical_json_bytes(entry_identity)).hexdigest()[:20]
        )
        stable = {
            "schema_version": "visiondata-gate.evidence-fusion-entry.v1",
            "entry_id": entry_id,
            "primary_finding_id": finding.finding_id,
            "issue_code": finding.code,
            "sample_ids": sorted(finding.sample_ids),
            "corroborating_finding_ids": [
                item.finding_id
                for item in related
                if item.finding_id != finding.finding_id
            ],
            "source_kinds": source_kinds,
            "evidence_facts": facts,
            "policy_ref": f"policy:{gate.policy_version}",
            "work_order_ids": sorted(order.work_order_id for order in matched_orders),
            "assigned_roles": sorted(
                {order.human_owner_role for order in matched_orders}
            ),
            "arbitration_basis": arbitration_basis,
            "fusion_status": (
                "CROSS_SOURCE_CORROBORATED"
                if len(measurement_kinds) > 1
                else "SINGLE_MEASUREMENT_WITH_POLICY_MAPPING"
            ),
            "root_cause_established": False,
            "machine_action_permitted": False,
            "claim_boundary": IndustrialEvidenceFusionEntry.model_fields[
                "claim_boundary"
            ].default,
        }
        entries.append(
            IndustrialEvidenceFusionEntry(
                **stable,
                entry_sha256=hashlib.sha256(canonical_json_bytes(stable)).hexdigest(),
            )
        )
    matrix_sha256 = hashlib.sha256(
        canonical_json_bytes([entry.model_dump(mode="json") for entry in entries])
    ).hexdigest()
    return entries, matrix_sha256


def _optional_int(value: object) -> int | None:
    return value if isinstance(value, int) and not isinstance(value, bool) else None


def _build_dynamic_execution_ledger(
    leader: dict[str, object],
    dynamic_tasks: list[dict[str, object]],
) -> IndustrialDynamicExecutionLedger:
    raw_budget = leader.get("followup_budget")
    budget = raw_budget if isinstance(raw_budget, dict) else None
    if budget is None:
        protocol = next(
            (
                str(item["dispatch_protocol"])
                for item in dynamic_tasks
                if item.get("dispatch_protocol")
            ),
            "legacy_not_recorded",
        )
        limit = None
        consumed = None
        candidate_count = None
        awarded_count = None
        completed_count = None
        failed_count = None
        exhausted = None
        status = "LEGACY_NOT_RECORDED"
    else:
        protocol_value = budget.get("protocol")
        count_keys = (
            "budget_limit_units",
            "consumed_units",
            "candidate_count",
            "awarded_count",
            "completed_count",
            "failed_count",
            "budget_exhausted_count",
        )
        parsed_counts = {key: _optional_int(budget.get(key)) for key in count_keys}
        if (
            not isinstance(protocol_value, str)
            or not protocol_value
            or any(value is None for value in parsed_counts.values())
        ):
            raise ValueError("follow-up budget ledger is incomplete or malformed")
        protocol = protocol_value
        limit = parsed_counts["budget_limit_units"]
        consumed = parsed_counts["consumed_units"]
        candidate_count = parsed_counts["candidate_count"]
        awarded_count = parsed_counts["awarded_count"]
        completed_count = parsed_counts["completed_count"]
        failed_count = parsed_counts["failed_count"]
        exhausted = parsed_counts["budget_exhausted_count"]
        if any(
            value is None
            for value in (
                limit,
                consumed,
                candidate_count,
                awarded_count,
                completed_count,
                failed_count,
                exhausted,
            )
        ):
            raise ValueError("follow-up budget ledger is incomplete or malformed")
        if (
            consumed > limit
            or awarded_count > candidate_count
            or completed_count + failed_count != awarded_count
            or exhausted != candidate_count - awarded_count
            or len(dynamic_tasks) != candidate_count
        ):
            raise ValueError("follow-up budget ledger failed consistency validation")
        status = "ENFORCED_WITH_SKIPS" if exhausted else "ENFORCED_WITHIN_LIMIT"
    return IndustrialDynamicExecutionLedger(
        dispatch_protocol=protocol,
        budget_status=status,
        budget_limit_units=limit,
        consumed_units=consumed,
        candidate_count=candidate_count,
        awarded_count=awarded_count,
        completed_count=completed_count,
        failed_count=failed_count,
        budget_exhausted_count=exhausted,
        task_ids=sorted(str(item["task_id"]) for item in dynamic_tasks),
        within_allocated_budget=(
            consumed <= limit if consumed is not None and limit is not None else None
        ),
    )


def _build_batch_triage_ledger(
    *,
    profile: dict[str, object],
    gate: GateResult,
    dynamic_tasks: list[dict[str, object]],
    dynamic_ledger: IndustrialDynamicExecutionLedger,
) -> IndustrialBatchTriageLedger:
    source_count = int(
        profile.get("source_image_count", gate.metrics.get("source_image_count", 0))
    )
    selected_count = int(
        gate.metrics.get("selected_image_count", gate.metrics.get("sample_count", 0))
    )
    candidate_count = dynamic_ledger.candidate_count
    if candidate_count is None:
        candidate_count = len(dynamic_tasks)
    awarded_count = dynamic_ledger.awarded_count
    if awarded_count is None:
        awarded_count = sum(
            item.get("status") not in {"budget_exhausted", "skipped"}
            for item in dynamic_tasks
        )
    l3_status = (
        "COMPLETED_WITH_BUDGET_SKIPS"
        if dynamic_ledger.budget_status == "ENFORCED_WITH_SKIPS"
        else "COMPLETED"
    )
    stable = {
        "schema_version": "visiondata-gate.batch-triage-ledger.v1",
        "stages": [
            IndustrialTriageStage(
                tier="L1",
                name="全源只读结构与元数据画像",
                input_count=source_count,
                selected_count=source_count,
                operation="READ_ONLY_STRUCTURE_AND_METADATA_PROFILE",
                selection_basis="all discovered source records",
                evidence_refs=["source_profile.json"],
                status="COMPLETED",
            ),
            IndustrialTriageStage(
                tier="L2",
                name="冻结分层抽样 Gate",
                input_count=source_count,
                selected_count=selected_count,
                operation="DETERMINISTIC_STRATIFIED_GATE_SAMPLE",
                selection_basis="fixed per-category train/test bucket contract",
                evidence_refs=["gate_result.json", "source_profile.json"],
                status="COMPLETED",
            ),
            IndustrialTriageStage(
                tier="L3",
                name="证据触发动态补证",
                input_count=candidate_count,
                selected_count=awarded_count,
                operation="BOUNDED_EVIDENCE_TRIGGERED_FOLLOWUP",
                selection_basis=(
                    "risk priority, expected evidence gain, cost units, stable task id"
                ),
                evidence_refs=["dynamic_leader_plan.json"],
                status=l3_status,
            ),
        ],
        "source_assets_copied": bool(
            profile.get("source_assets_copied_into_product", False)
        ),
        "full_source_policy_gate_claimed": False,
        "throughput_benchmark_claimed": False,
        "claim_boundary": IndustrialBatchTriageLedger.model_fields[
            "claim_boundary"
        ].default,
    }
    return IndustrialBatchTriageLedger(
        **stable,
        ledger_sha256=hashlib.sha256(canonical_json_bytes(stable)).hexdigest(),
    )


def _matching_findings(work_order: WorkOrder, findings: list[Finding]) -> list[Finding]:
    source_finding_id = str(
        work_order.replacement_requirements.get("source_finding_id", "")
    )
    if source_finding_id:
        exact = [
            finding for finding in findings if finding.finding_id == source_finding_id
        ]
        if exact:
            return exact

    sample_ids = set(work_order.sample_ids)
    reason_codes = set(work_order.reason_codes)
    reason_matches = [finding for finding in findings if finding.code in reason_codes]
    if reason_matches:
        return sorted(reason_matches, key=lambda finding: finding.finding_id)

    sample_matches = [
        finding
        for finding in findings
        if bool(sample_ids.intersection(finding.sample_ids))
    ]
    return sorted(sample_matches, key=lambda finding: finding.finding_id)


def _work_order_delivery(
    work_order: WorkOrder,
    *,
    findings: list[Finding],
    dynamic_tasks: list[dict[str, object]],
    policy_version: str,
) -> IndustrialExecutableWorkOrder:
    guidance = _ACTION_GUIDANCE[work_order.action]
    matched = _matching_findings(work_order, findings)
    finding_refs = [f"finding:{finding.finding_id}" for finding in matched]
    dynamic_refs = sorted(
        str(item["task_id"])
        for item in dynamic_tasks
        if set(item.get("input_refs", [])).intersection(
            {f"work-order:{work_order.work_order_id}", *finding_refs}
        )
    )
    evidence_span = [
        IndustrialEvidenceSpan(
            finding_id=finding.finding_id,
            code=finding.code,
            tool=finding.tool,
            sample_ids=finding.sample_ids,
            summary=finding.summary,
        )
        for finding in matched
    ]
    reason_trace = [
        (
            f"{finding.code} was measured by {finding.tool}; frozen policy "
            f"{policy_version} mapped it to {work_order.action}."
        )
        for finding in matched
    ]
    if not reason_trace:
        reason_trace = [
            f"Frozen policy {policy_version} emitted {work_order.action} from "
            f"reason codes: {', '.join(work_order.reason_codes)}."
        ]
    return IndustrialExecutableWorkOrder(
        work_order_id=work_order.work_order_id,
        action=work_order.action,
        priority=work_order.priority.value,
        status=work_order.status,
        ai_expert_role=str(guidance["ai_expert_role"]),
        required_skill=str(guidance["required_skill"]),
        human_owner_role=str(guidance["human_owner_role"]),
        prerequisites=list(guidance["prerequisites"]),
        acceptance_criteria=list(guidance["acceptance_criteria"]),
        human_confirmation_point=(
            "The named human owner must approve any source-data change and the final "
            "production release; this Agent only recommends and verifies evidence."
        ),
        evidence_span=evidence_span,
        evidence_refs=[
            f"work-order:{work_order.work_order_id}",
            *finding_refs,
            f"policy:{policy_version}",
        ],
        reason_trace=reason_trace,
        dynamic_task_refs=dynamic_refs,
    )


def _build_risk_clusters(
    work_orders: list[IndustrialExecutableWorkOrder],
) -> list[IndustrialRiskCluster]:
    grouped: dict[str, list[IndustrialExecutableWorkOrder]] = {}
    for work_order in _ordered_work_orders(work_orders):
        grouped.setdefault(work_order.action, []).append(work_order)

    clusters: list[IndustrialRiskCluster] = []
    for action in sorted(grouped, key=lambda value: _ACTION_ORDER[value]):
        orders = grouped[action]
        guidance = _RISK_CLUSTER_GUIDANCE[action]
        stable = {
            "schema_version": "visiondata-gate.industrial-risk-cluster.v1",
            "risk_cluster_id": guidance["risk_cluster_id"],
            "title": guidance["title"],
            "objective": guidance["objective"],
            "action": action,
            "priority": min(
                (item.priority for item in orders),
                key=lambda value: _PRIORITY_ORDER.get(value, 99),
            ),
            "reason_codes": sorted(
                {span.code for item in orders for span in item.evidence_span}
            ),
            "finding_ids": sorted(
                {span.finding_id for item in orders for span in item.evidence_span}
            ),
            "work_order_ids": [item.work_order_id for item in orders],
            "sample_ids": sorted(
                {
                    sample_id
                    for item in orders
                    for span in item.evidence_span
                    for sample_id in span.sample_ids
                }
            ),
            "affected_sample_count": len(
                {
                    sample_id
                    for item in orders
                    for span in item.evidence_span
                    for sample_id in span.sample_ids
                }
            ),
            "sampleless_work_order_count": sum(
                not any(span.sample_ids for span in item.evidence_span)
                for item in orders
            ),
            "atomic_work_order_count": len(orders),
            "human_owner_role": orders[0].human_owner_role,
            "required_skill": orders[0].required_skill,
            "dynamic_task_refs": sorted(
                {ref for item in orders for ref in item.dynamic_task_refs}
            ),
            "machine_action_permitted": False,
            "claim_boundary": IndustrialRiskCluster.model_fields[
                "claim_boundary"
            ].default,
        }
        cluster_sha256 = hashlib.sha256(canonical_json_bytes(stable)).hexdigest()
        clusters.append(IndustrialRiskCluster(**stable, cluster_sha256=cluster_sha256))
    return clusters


def _ordered_work_orders(
    work_orders: list[IndustrialExecutableWorkOrder],
) -> list[IndustrialExecutableWorkOrder]:
    return sorted(
        work_orders,
        key=lambda item: (
            _PRIORITY_ORDER.get(item.priority, 99),
            _ACTION_ORDER.get(item.action, 99),
            item.work_order_id,
        ),
    )


def _remediation_waves(
    selected: list[IndustrialExecutableWorkOrder],
) -> list[IndustrialRemediationWave]:
    waves: list[IndustrialRemediationWave] = []
    prior_wave_id: str | None = None
    for action in sorted(
        {item.action for item in selected}, key=lambda value: _ACTION_ORDER[value]
    ):
        action_orders = [item for item in selected if item.action == action]
        guidance = _ACTION_GUIDANCE[action]
        wave_id = f"wave-{len(waves) + 1:02d}-{action.lower().replace('_', '-')}"
        acceptance = "；".join(str(value) for value in guidance["acceptance_criteria"])
        waves.append(
            IndustrialRemediationWave(
                wave_id=wave_id,
                sequence=len(waves) + 1,
                objective=f"按冻结工单处理 {action} 类问题，并保留变更前后证据。",
                work_order_ids=[item.work_order_id for item in action_orders],
                owner_roles=sorted({item.human_owner_role for item in action_orders}),
                prerequisite_wave_ids=[prior_wave_id] if prior_wave_id else [],
                acceptance_gate=acceptance,
            )
        )
        prior_wave_id = wave_id
    verification_id = f"wave-{len(waves) + 1:02d}-child-run-recheck"
    waves.append(
        IndustrialRemediationWave(
            wave_id=verification_id,
            sequence=len(waves) + 1,
            objective="创建派生数据版本，并使用原合同、原工具白名单和固定种子执行 child Run。",
            work_order_ids=[],
            owner_roles=["quality_or_safety_owner"],
            prerequisite_wave_ids=[prior_wave_id] if prior_wave_id else [],
            acceptance_gate=(
                "child Run 必须独立落盘；未关闭工单、证据冲突或非 PASS 裁决继续失败关闭。"
            ),
        )
    )
    return waves


def _seal_remediation_plan(
    *,
    task_id: str,
    run_id: str,
    strategy: Literal[
        "containment_first", "actionable_recovery", "full_evidence_closure"
    ],
    title: str,
    objective: str,
    selected: list[IndustrialExecutableWorkOrder],
    all_orders: list[IndustrialExecutableWorkOrder],
    review_eligibility: Literal[
        "containment_only",
        "partial_recheck_required",
        "full_closure_recheck_required",
    ],
) -> IndustrialRemediationPlan:
    selected_ids = {item.work_order_id for item in selected}
    deferred = [item for item in all_orders if item.work_order_id not in selected_ids]
    all_finding_ids = {
        span.finding_id for item in all_orders for span in item.evidence_span
    }
    targeted_finding_ids = sorted(
        {span.finding_id for item in selected for span in item.evidence_span}
    )
    coverage = (
        len(targeted_finding_ids) / len(all_finding_ids) if all_finding_ids else 0.0
    )
    effort = sum(
        _ACTION_EFFORT[item.action] + _PRIORITY_EFFORT.get(item.priority, 1)
        for item in selected
    )
    plan_id = {
        "containment_first": "RP-CONTAINMENT-FIRST",
        "actionable_recovery": "RP-ACTIONABLE-RECOVERY",
        "full_evidence_closure": "RP-FULL-EVIDENCE-CLOSURE",
    }[strategy]
    stable = {
        "schema_version": "visiondata-gate.industrial-remediation-plan.v1",
        "task_id": task_id,
        "run_id": run_id,
        "plan_id": plan_id,
        "strategy": strategy,
        "title": title,
        "objective": objective,
        "selected_work_order_ids": [item.work_order_id for item in selected],
        "deferred_work_order_ids": [item.work_order_id for item in deferred],
        "targeted_finding_ids": targeted_finding_ids,
        "evidence_coverage_ratio": round(coverage, 6),
        "relative_effort_points": max(effort, 1),
        "waves": _remediation_waves(selected),
        "residual_risk_codes": sorted(
            {span.code for item in deferred for span in item.evidence_span}
        ),
        "review_eligibility": review_eligibility,
        "same_contract_child_run_required": True,
        "production_release_allowed": False,
        "claim_boundary": IndustrialRemediationPlan.model_fields[
            "claim_boundary"
        ].default,
    }
    plan_sha256 = hashlib.sha256(canonical_json_bytes(stable)).hexdigest()
    return IndustrialRemediationPlan(**stable, plan_sha256=plan_sha256)


def _build_remediation_plans(
    *,
    task_id: str,
    run_id: str,
    work_orders: list[IndustrialExecutableWorkOrder],
) -> list[IndustrialRemediationPlan]:
    ordered = _ordered_work_orders(work_orders)
    if not ordered:
        return []
    critical = [item for item in ordered if item.priority == "critical"]
    representatives: list[IndustrialExecutableWorkOrder] = []
    for action in sorted(
        {item.action for item in ordered}, key=lambda value: _ACTION_ORDER[value]
    ):
        representatives.append(next(item for item in ordered if item.action == action))
    containment_by_id = {
        item.work_order_id: item for item in [*critical, *representatives]
    }
    containment = _ordered_work_orders(list(containment_by_id.values()))
    actionable = [item for item in ordered if item.action != "INVESTIGATE"]
    if not actionable:
        actionable = list(containment)
    return [
        _seal_remediation_plan(
            task_id=task_id,
            run_id=run_id,
            strategy="containment_first",
            title="关键风险优先隔离",
            objective="先处理每类最高优先级问题，快速形成可审计的风险隔离面。",
            selected=containment,
            all_orders=ordered,
            review_eligibility="containment_only",
        ),
        _seal_remediation_plan(
            task_id=task_id,
            run_id=run_id,
            strategy="actionable_recovery",
            title="可执行整改批次",
            objective="批量处理可直接整改的采集、标注和数据划分问题，调查项继续阻断。",
            selected=actionable,
            all_orders=ordered,
            review_eligibility="partial_recheck_required",
        ),
        _seal_remediation_plan(
            task_id=task_id,
            run_id=run_id,
            strategy="full_evidence_closure",
            title="完整证据闭环",
            objective="覆盖全部工单和调查项，完成后仅进入同合同 child Run 复验。",
            selected=ordered,
            all_orders=ordered,
            review_eligibility="full_closure_recheck_required",
        ),
    ]


def _build_synthetic_industrial_delivery_receipt(
    task: TaskRecord, root: Path
) -> IndustrialDeliveryReceipt:
    """Build a synthetic-only delivery receipt without fabricating authorization.

    Synthetic product runs do not have a local-source authorization receipt or the
    Omni dynamic-leader artifacts.  They still need a typed delivery artifact so
    evidence-package integrity and release-readiness checks share one explicit
    contract.  Every source below therefore points only at sealed synthetic run
    evidence, and the authorization-shaped slot states that authorization is not
    applicable instead of claiming an operator attestation.
    """

    gate_path = root / "repaired" / "gate_result.json"
    trace_path = root / "agent_runtime_trace.json"
    summary_path = root / "demo_summary.json"
    scope_path = root / "claim_scope_receipt.json"
    gate = GateResult.model_validate_json(gate_path.read_text(encoding="utf-8"))
    trace = RuntimeTrace.model_validate_json(trace_path.read_text(encoding="utf-8"))
    summary = _load_json(summary_path)

    def observed_count(*keys: str) -> int:
        for key in keys:
            value = gate.metrics.get(key)
            if isinstance(value, int) and not isinstance(value, bool) and value >= 0:
                return value
        return 0

    multi_source_fusion = [
        IndustrialEvidenceSource(
            source_type="image_batch",
            evidence_ref="demo_summary.json",
            evidence_sha256=sha256_file(summary_path),
            observed_count=observed_count(
                "sample_count", "quality_sample_count", "decoded_image_count"
            ),
            status="used",
            role_in_decision=(
                "Describes the generated synthetic batch and its bounded evaluation; "
                "it is not a real-factory source profile."
            ),
        ),
        IndustrialEvidenceSource(
            source_type="mask_annotation",
            evidence_ref="repaired/gate_result.json",
            evidence_sha256=sha256_file(gate_path),
            observed_count=observed_count(
                "annotation_sample_count", "annotation_decoded_mask_count"
            ),
            status="used",
            role_in_decision=(
                "Records annotation measurements from the synthetic verification run."
            ),
        ),
        IndustrialEvidenceSource(
            source_type="manifest_metadata",
            evidence_ref="demo_summary.json",
            evidence_sha256=sha256_file(summary_path),
            observed_count=int(bool(summary)),
            status="used",
            role_in_decision=(
                "Binds the synthetic seed, evaluation and repair summary to delivery."
            ),
        ),
        IndustrialEvidenceSource(
            source_type="tool_measurement",
            evidence_ref="repaired/gate_result.json",
            evidence_sha256=sha256_file(gate_path),
            observed_count=len(gate.tool_trace),
            status="used",
            role_in_decision=(
                "Binds the final synthetic decision to deterministic tool receipts."
            ),
        ),
        IndustrialEvidenceSource(
            source_type="frozen_policy",
            evidence_ref="repaired/gate_result.json",
            evidence_sha256=sha256_file(gate_path),
            observed_count=len(gate.rule_checks),
            status="used",
            role_in_decision=(
                "Maps synthetic measurements to the frozen fail-closed Gate decision."
            ),
        ),
        IndustrialEvidenceSource(
            source_type="operator_authorization",
            evidence_ref="claim_scope_receipt.json",
            evidence_sha256=sha256_file(scope_path),
            observed_count=0,
            status="used",
            role_in_decision=(
                "Authorization is NOT_APPLICABLE for the generated synthetic fixture; "
                "this artifact records that boundary and is not an operator attestation."
            ),
        ),
    ]
    executable_work_orders = [
        _work_order_delivery(
            work_order,
            findings=gate.findings,
            dynamic_tasks=[],
            policy_version=gate.policy_version,
        )
        for work_order in gate.work_orders
    ]
    evidence_fusion_matrix, evidence_fusion_matrix_sha256 = (
        _build_evidence_fusion_matrix(gate, executable_work_orders)
    )
    return IndustrialDeliveryReceipt(
        task_id=task.task_id,
        run_id=gate.run_id,
        target_user="industrial_data_engineer_and_quality_owner",
        industrial_task="synthetic_industrial_vision_dataset_release_gate_demo",
        final_decision=gate.decision.value,
        decision_reason=gate.decision_reason,
        policy_version=gate.policy_version,
        inspection_contract=(
            _build_inspection_contract_binding(gate) if gate.tool_trace else None
        ),
        multi_source_fusion=multi_source_fusion,
        evidence_fusion_matrix=evidence_fusion_matrix,
        evidence_fusion_matrix_sha256=evidence_fusion_matrix_sha256,
        dynamic_responses=[],
        dynamic_execution_ledger=None,
        batch_triage=None,
        risk_clusters=_build_risk_clusters(executable_work_orders),
        executable_work_orders=executable_work_orders,
        remediation_plans=(
            _build_remediation_plans(
                task_id=task.task_id,
                run_id=gate.run_id,
                work_orders=executable_work_orders,
            )
            if executable_work_orders
            else []
        ),
        allowed_agent_actions=[
            "Generate and inspect the repository-owned synthetic fixture.",
            "Measure, compare, and verify the bounded synthetic repair workflow.",
            "Generate traceable receipts for reviewer and regression use.",
        ],
        forbidden_agent_actions=[
            "Represent synthetic evidence as a factory shadow test or customer result.",
            "Approve production release or replace a qualified safety decision maker.",
            "Use this receipt as authorization to read or redistribute external data.",
        ],
        source_assets_copied_into_product=False,
        model_call_count=trace.model_call_count,
        unresolved_boundaries=[
            "This run uses generated synthetic data, not customer or factory data.",
            "No customer-site acceptance or factory deployment has been demonstrated.",
            "Synthetic metrics do not estimate real-factory false-release rates.",
            "No external source authorization was required or granted for this run.",
        ],
        claim_boundary=(
            "This receipt proves a sealed synthetic demonstration and regression "
            "workflow only. It does not prove real-factory effectiveness, authorize "
            "production use, control equipment, or replace the responsible human role."
        ),
    )


def build_industrial_delivery_receipt(
    task: TaskRecord, evidence_dir: str | Path
) -> IndustrialDeliveryReceipt:
    """Build a path-redacted, actionable receipt from already sealed run evidence."""

    root = Path(evidence_dir).resolve(strict=True)
    if task.source_kind is DataSourceKind.SYNTHETIC_DEMO:
        return _build_synthetic_industrial_delivery_receipt(task, root)
    if task.source_kind is not DataSourceKind.LOCAL_AUTHORIZED_DIRECTORY:
        raise ValueError("industrial delivery is unavailable for this source kind")

    gate_path = root / "gate_result.json"
    trace_path = root / "agent_runtime_trace.json"
    source_profile_path = root / "source_profile.json"
    source_receipt_path = root / "local_source_authorization_receipt.json"
    leader_path = root / "dynamic_leader_plan.json"
    gate = GateResult.model_validate_json(gate_path.read_text(encoding="utf-8"))
    trace = RuntimeTrace.model_validate_json(trace_path.read_text(encoding="utf-8"))
    source_receipt = LocalSourceAuthorizationReceipt.model_validate_json(
        source_receipt_path.read_text(encoding="utf-8")
    )
    profile = _load_json(source_profile_path)
    leader = _load_json(leader_path)
    raw_dynamic_tasks = leader.get("dynamic_tasks", [])
    if not isinstance(raw_dynamic_tasks, list) or any(
        not isinstance(item, dict) for item in raw_dynamic_tasks
    ):
        raise ValueError("dynamic_leader_plan.dynamic_tasks must be a list of objects")
    dynamic_tasks: list[dict[str, object]] = raw_dynamic_tasks

    multi_source_fusion = [
        IndustrialEvidenceSource(
            source_type="image_batch",
            evidence_ref="source_profile.json",
            evidence_sha256=sha256_file(source_profile_path),
            observed_count=int(profile.get("source_image_count", 0)),
            status="used",
            role_in_decision="Provides the redacted source population profile.",
        ),
        IndustrialEvidenceSource(
            source_type="mask_annotation",
            evidence_ref="source_profile.json",
            evidence_sha256=sha256_file(source_profile_path),
            observed_count=int(profile.get("source_mask_count", 0)),
            status="used",
            role_in_decision="Defines annotation availability and integrity scope.",
        ),
        IndustrialEvidenceSource(
            source_type="manifest_metadata",
            evidence_ref="dynamic_leader_plan.json",
            evidence_sha256=sha256_file(leader_path),
            observed_count=int(profile.get("metadata_image_count", 0)),
            status="used",
            role_in_decision="Triggers metadata/tree reconciliation when counts drift.",
        ),
        IndustrialEvidenceSource(
            source_type="tool_measurement",
            evidence_ref="gate_result.json",
            evidence_sha256=sha256_file(gate_path),
            observed_count=len(gate.tool_trace),
            status="used",
            role_in_decision="Binds findings to deterministic tool input/output hashes.",
        ),
        IndustrialEvidenceSource(
            source_type="frozen_policy",
            evidence_ref="gate_result.json",
            evidence_sha256=sha256_file(gate_path),
            observed_count=len(gate.rule_checks),
            status="used",
            role_in_decision="Maps evidence to a fail-closed decision and work orders.",
        ),
        IndustrialEvidenceSource(
            source_type="operator_authorization",
            evidence_ref="local_source_authorization_receipt.json",
            evidence_sha256=sha256_file(source_receipt_path),
            observed_count=int(source_receipt.operator_attests_authorized_use),
            status="operator_attested",
            role_in_decision="Records use permission and residency without claiming ownership.",
        ),
    ]
    dynamic_responses: list[IndustrialDynamicResponse] = []
    for item in dynamic_tasks:
        raw_budget = item.get("budget")
        budget = raw_budget if isinstance(raw_budget, dict) else None
        allocated = (
            _optional_int(budget.get("estimated_cost_units")) if budget else None
        )
        consumed = _optional_int(budget.get("consumed_cost_units")) if budget else None
        status = str(item.get("status", "legacy_not_recorded"))
        dynamic_responses.append(
            IndustrialDynamicResponse(
                task_id=str(item["task_id"]),
                trigger=str(item["trigger"]),
                worker_id=str(item["worker_id"]),
                status=status,
                decision_effect=str(item["decision_effect"]),
                stop_condition=str(item.get("stop_condition", "legacy_not_recorded")),
                input_refs=[str(value) for value in item.get("input_refs", [])],
                new_evidence_refs=[
                    str(value) for value in item.get("new_evidence_refs", [])
                ],
                result_sha256=str(item["result_sha256"]),
                dispatch_index=_optional_int(
                    item.get("dispatch_index", item.get("award_rank"))
                ),
                dispatch_mode=str(item.get("dispatch_mode", "legacy_not_recorded")),
                dispatch_protocol=str(
                    item.get("dispatch_protocol", "legacy_not_recorded")
                ),
                duration_ms=(
                    float(item["duration_ms"])
                    if isinstance(item.get("duration_ms"), (int, float))
                    and not isinstance(item.get("duration_ms"), bool)
                    else None
                ),
                allocated_cost_units=allocated,
                consumed_cost_units=consumed,
                budget_status=(
                    "NOT_EXECUTED_BUDGET_EXHAUSTED"
                    if status == "budget_exhausted"
                    else "WITHIN_BUDGET"
                    if budget is not None
                    else "LEGACY_NOT_RECORDED"
                ),
            )
        )
    executable_work_orders = [
        _work_order_delivery(
            work_order,
            findings=gate.findings,
            dynamic_tasks=dynamic_tasks,
            policy_version=gate.policy_version,
        )
        for work_order in gate.work_orders
    ]
    risk_clusters = _build_risk_clusters(executable_work_orders)
    remediation_plans = _build_remediation_plans(
        task_id=task.task_id,
        run_id=gate.run_id,
        work_orders=executable_work_orders,
    )
    inspection_contract = _build_inspection_contract_binding(gate)
    evidence_fusion_matrix, evidence_fusion_matrix_sha256 = (
        _build_evidence_fusion_matrix(gate, executable_work_orders)
    )
    dynamic_execution_ledger = _build_dynamic_execution_ledger(leader, dynamic_tasks)
    batch_triage = _build_batch_triage_ledger(
        profile=profile,
        gate=gate,
        dynamic_tasks=dynamic_tasks,
        dynamic_ledger=dynamic_execution_ledger,
    )
    return IndustrialDeliveryReceipt(
        task_id=task.task_id,
        run_id=gate.run_id,
        target_user="industrial_data_engineer_and_quality_owner",
        industrial_task="industrial_vision_dataset_release_gate",
        final_decision=gate.decision.value,
        decision_reason=gate.decision_reason,
        policy_version=gate.policy_version,
        inspection_contract=inspection_contract,
        multi_source_fusion=multi_source_fusion,
        evidence_fusion_matrix=evidence_fusion_matrix,
        evidence_fusion_matrix_sha256=evidence_fusion_matrix_sha256,
        dynamic_responses=dynamic_responses,
        dynamic_execution_ledger=dynamic_execution_ledger,
        batch_triage=batch_triage,
        risk_clusters=risk_clusters,
        executable_work_orders=executable_work_orders,
        remediation_plans=remediation_plans,
        allowed_agent_actions=[
            "Read the explicitly authorized source in place.",
            "Measure, compare, re-plan bounded evidence tasks, and recommend work orders.",
            "Generate traceable receipts and verify remediation evidence.",
        ],
        forbidden_agent_actions=[
            "Modify source images, masks, labels, manifests, or production systems.",
            "Approve production release or replace a qualified safety decision maker.",
            "Claim data ownership, customer acceptance, or complete dataset certification.",
        ],
        source_assets_copied_into_product=(
            source_receipt.source_assets_copied_into_product
        ),
        model_call_count=trace.model_call_count,
        unresolved_boundaries=[
            "No customer-site acceptance or factory deployment has been demonstrated.",
            "The fixed Gate sample is not a full-source certification.",
            "The anomaly-model backend remains NOT_CONNECTED.",
            "Source rights are operator-attested and are not independently adjudicated.",
        ],
        claim_boundary=(
            "This receipt proves a bounded, read-only industrial data review and an "
            "actionable recommendation chain. It does not authorize production use, "
            "control equipment, certify safety, or replace the responsible human role."
        ),
    )


__all__ = [
    "IndustrialBatchTriageLedger",
    "IndustrialDeliveryReceipt",
    "IndustrialDynamicResponse",
    "IndustrialDynamicExecutionLedger",
    "IndustrialEvidenceFact",
    "IndustrialEvidenceFusionEntry",
    "IndustrialEvidenceSource",
    "IndustrialExecutableWorkOrder",
    "IndustrialInspectionContractBinding",
    "IndustrialRiskCluster",
    "IndustrialRemediationPlan",
    "IndustrialRemediationWave",
    "build_industrial_delivery_receipt",
]
