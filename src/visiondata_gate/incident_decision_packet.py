"""Actionable, evidence-linked delivery packet for an industrial incident.

The control-plane packet remains the low-level audit record.  This module
projects it into a named-owner operational contract and deterministic exports
without changing the underlying incident disposition or causal claim level.
"""

from __future__ import annotations

import csv
import hashlib
import hmac
import io
import zipfile
from collections import defaultdict
from dataclasses import dataclass
from html import escape
from pathlib import Path
from typing import Annotated, Literal

from pydantic import Field, field_validator

from .evidence import canonical_json_bytes
from .evidence_state_contracts import (
    EvidenceBeliefLedgerV2,
    verify_evidence_belief_ledger_v2,
)
from .governed_context import ContextReceipt
from .incident_agent_kernel import (
    AutonomyGuardReceiptV1,
    CouncilArbitrationReceiptV1,
    EvidenceBeliefRevisionReceiptV1,
    WorkerExecutionPlanReceiptV1,
    verify_autonomy_guard_receipt_v1,
    verify_council_arbitration_receipt_v1,
    verify_evidence_belief_revision_receipt_v1,
    verify_worker_execution_plan_receipt_v1,
)
from .incident_control_plane import (
    IncidentControlPlaneBundle,
    verify_incident_control_plane,
)
from .industrial_incident import (
    AGENT_KERNEL_INCIDENT_CASE_SCHEMA_VERSION,
    PLANNING_ARTIFACT_INCIDENT_CASE_SCHEMA_VERSIONS,
    IndustrialIncidentCase,
    verify_industrial_incident_case,
)
from .multimodal_advisor import (
    MultimodalAdvisorReceipt,
    verify_multimodal_advisor_receipt,
)
from .product_models import ProductModel
from .site_pack import FactorySitePack, verify_factory_site_pack
from .worker_selection import (
    AgentBehaviorReceiptV1,
    WorkerSelectionReceipt,
    build_agent_behavior_receipt,
    verify_agent_behavior_receipt,
    verify_worker_selection_receipt,
)

ZIP_EPOCH = (1980, 1, 1, 0, 0, 0)


def _sha256(value: object) -> str:
    return hashlib.sha256(canonical_json_bytes(value)).hexdigest()


def _sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


class DecisionEvidenceLink(ProductModel):
    evidence_ref: str
    evidence_type: str
    evidence_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    qualification: str
    role_in_decision: str
    current_case_eligible: bool


class DecisionVerifiedFact(ProductModel):
    fact_id: str = Field(pattern=r"^fact_[0-9a-f]{16}$")
    statement: str = Field(min_length=3, max_length=1200)
    supporting_evidence_refs: list[str] = Field(min_length=1)
    verification_scope: Literal["CURRENT_CASE_EVIDENCE_ONLY"] = (
        "CURRENT_CASE_EVIDENCE_ONLY"
    )
    root_cause_claim: Literal[False] = False


class DecisionHypothesis(ProductModel):
    hypothesis_id: str
    category: str
    status: str
    supporting_issue_codes: list[str]
    contradicting_issue_codes: list[str]
    unresolved_evidence_refs: list[str]
    next_discriminating_test: str


class ActionContract(ProductModel):
    schema_version: Literal["visiondata-gate.action-contract.v1"] = (
        "visiondata-gate.action-contract.v1"
    )
    action_id: str = Field(pattern=r"^action_[0-9a-f]{20}$")
    action_type: Literal[
        "REQUEST_EVIDENCE",
        "ESCALATE_INVESTIGATION",
        "SELECT_CAPA",
        "START_CHILD_RUN_REVERIFICATION",
    ]
    accountable_owner_id: str = Field(min_length=1, max_length=160)
    accountable_owner_role: str = Field(min_length=1, max_length=160)
    requested_contributor_role: str = Field(min_length=1, max_length=160)
    required_input: str = Field(min_length=3, max_length=1600)
    reason: str = Field(min_length=3, max_length=1600)
    acceptance_criteria: list[str] = Field(min_length=2, max_length=12)
    blocking: bool
    source_evidence_refs: list[str] = Field(min_length=1, max_length=24)
    source_issue_codes: list[str] = Field(default_factory=list, max_length=24)
    related_hypothesis_ids: list[str] = Field(default_factory=list, max_length=8)
    status: Literal["PROPOSED_REQUIRES_HUMAN"] = "PROPOSED_REQUIRES_HUMAN"
    machine_action_permitted: Literal[False] = False
    production_release_permitted: Literal[False] = False
    action_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")

    @field_validator(
        "acceptance_criteria",
        "source_evidence_refs",
        "source_issue_codes",
        "related_hypothesis_ids",
    )
    @classmethod
    def unique_lists(cls, values: list[str]) -> list[str]:
        if len(values) != len(set(values)):
            raise ValueError("Action Contract list values must be unique")
        return values


class HumanDecisionOption(ProductModel):
    decision: Literal[
        "CONTINUE_HOLD",
        "SUPPLY_EVIDENCE",
        "ESCALATE_INVESTIGATION",
        "SELECT_CAPA",
        "REQUEST_CHILD_RUN_REVERIFICATION",
    ]
    enabled: bool
    reason: str
    requires_bound_decision_receipt: Literal[True] = True


class DecisionPacketMetrics(ProductModel):
    evidence_link_coverage: float = Field(ge=0.0, le=1.0)
    action_owner_coverage: float = Field(ge=0.0, le=1.0)
    unresolved_risk_visibility: float = Field(ge=0.0, le=1.0)
    decision_packet_completeness: float = Field(ge=0.0, le=1.0)
    important_conclusion_count: int = Field(ge=1)
    evidence_linked_conclusion_count: int = Field(ge=0)
    action_count: int = Field(ge=1)
    named_owner_action_count: int = Field(ge=0)


class _IndustrialQualityDecisionPacketBase(ProductModel):
    case_id: str = Field(pattern=r"^incident_[0-9a-f]{20}$")
    case_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    case_version: int = Field(ge=1)
    control_plane_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    site_id: str | None = None
    site_pack_sha256: str | None = Field(default=None, pattern=r"^[0-9a-f]{64}$")
    context_receipt_sha256: str | None = Field(default=None, pattern=r"^[0-9a-f]{64}$")
    multimodal_advisor_receipt_sha256: str | None = Field(
        default=None, pattern=r"^[0-9a-f]{64}$"
    )
    disposition: str
    recommendation: str
    recommendation_reason: str
    root_cause_status: Literal["NOT_ESTABLISHED"] = "NOT_ESTABLISHED"
    named_quality_owner_id: str = Field(min_length=1, max_length=160)
    named_quality_owner_role: str = Field(min_length=1, max_length=160)
    evidence_index: list[DecisionEvidenceLink] = Field(min_length=6)
    verified_facts: list[DecisionVerifiedFact] = Field(min_length=1)
    competing_hypotheses: list[DecisionHypothesis] = Field(min_length=6)
    current_evidence_gaps: list[str]
    unresolved_risk_codes: list[str]
    action_contracts: list[ActionContract] = Field(min_length=1, max_length=10)
    human_decision_options: list[HumanDecisionOption] = Field(min_length=5)
    linked_remediation_plan_ids: list[str]
    child_run_status: str
    external_model_call_count: int = Field(ge=0)
    opcua_connection_status: str
    visionmaster_connection_status: str
    metrics: DecisionPacketMetrics
    human_approval_required: Literal[True] = True
    production_release_allowed: Literal[False] = False
    machine_write_permitted: Literal[False] = False
    direct_equipment_control_permitted: Literal[False] = False
    packet_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    claim_boundary: str = (
        "This packet delivers evidence-linked decision support and proposed actions to "
        "a named quality owner. It is not root-cause proof, an executed CAPA, customer "
        "acceptance, production release, or equipment-control authority."
    )


class IndustrialQualityDecisionPacketV1(_IndustrialQualityDecisionPacketBase):
    """Historical projection for pre-v5 Incident Cases."""

    schema_version: Literal["visiondata-gate.industrial-quality-decision-packet.v1"] = (
        "visiondata-gate.industrial-quality-decision-packet.v1"
    )


class IndustrialQualityDecisionPacketV2(_IndustrialQualityDecisionPacketBase):
    """Decision delivery that carries the replayable v5 planning artifacts."""

    schema_version: Literal["visiondata-gate.industrial-quality-decision-packet.v2"] = (
        "visiondata-gate.industrial-quality-decision-packet.v2"
    )
    planning_belief_ledger: EvidenceBeliefLedgerV2
    worker_selection_receipt: WorkerSelectionReceipt


class IndustrialQualityDecisionPacketV3(_IndustrialQualityDecisionPacketBase):
    """Decision delivery carrying the complete v6 Agent-kernel envelope."""

    schema_version: Literal["visiondata-gate.industrial-quality-decision-packet.v3"] = (
        "visiondata-gate.industrial-quality-decision-packet.v3"
    )
    planning_belief_ledger: EvidenceBeliefLedgerV2
    worker_selection_receipt: WorkerSelectionReceipt
    parent_belief_revision_receipt: EvidenceBeliefRevisionReceiptV1 | None = None
    worker_execution_plan_receipt: WorkerExecutionPlanReceiptV1
    council_arbitration_receipt: CouncilArbitrationReceiptV1
    autonomy_guard_receipt: AutonomyGuardReceiptV1


IndustrialQualityDecisionPacket = Annotated[
    IndustrialQualityDecisionPacketV1
    | IndustrialQualityDecisionPacketV2
    | IndustrialQualityDecisionPacketV3,
    Field(discriminator="schema_version"),
]


class DecisionPacketExportArtifact(ProductModel):
    path: str
    media_type: str
    byte_count: int = Field(ge=1)
    sha256: str = Field(pattern=r"^[0-9a-f]{64}$")


class DecisionPacketExportReceipt(ProductModel):
    schema_version: Literal["visiondata-gate.decision-packet-export.v1"] = (
        "visiondata-gate.decision-packet-export.v1"
    )
    case_id: str
    case_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    packet_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    artifacts: list[DecisionPacketExportArtifact] = Field(min_length=5)
    audit_bundle_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    deterministic_archive: Literal[True] = True
    raw_source_assets_included: Literal[False] = False
    receipt_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")


@dataclass(frozen=True)
class DecisionPacketExports:
    decision_packet_json: bytes
    decision_packet_html: bytes
    evidence_request_csv: bytes
    capa_action_list_json: bytes
    agent_behavior_receipt_json: bytes | None
    audit_bundle_zip: bytes
    receipt: DecisionPacketExportReceipt


_CONTRIBUTOR_BY_WORKER = {
    "SignalIntegrityAgent": "ProcessEngineer",
    "TraceabilityAgent": "QualityEngineer",
    "VisionConfigurationAgent": "VisionEngineer",
    "VisualEvidenceAgent": "VisionEngineer",
    "CounterEvidenceAgent": "QualityEngineer",
}


def _action_contract(
    *,
    action_type: Literal[
        "REQUEST_EVIDENCE",
        "ESCALATE_INVESTIGATION",
        "SELECT_CAPA",
        "START_CHILD_RUN_REVERIFICATION",
    ],
    accountable_owner_id: str,
    accountable_owner_role: str,
    requested_contributor_role: str,
    required_input: str,
    reason: str,
    acceptance_criteria: list[str],
    blocking: bool,
    source_evidence_refs: list[str],
    source_issue_codes: list[str],
    related_hypothesis_ids: list[str],
) -> ActionContract:
    identity = _sha256(
        {
            "action_type": action_type,
            "accountable_owner_id": accountable_owner_id,
            "requested_contributor_role": requested_contributor_role,
            "required_input": required_input,
            "source_evidence_refs": source_evidence_refs,
            "source_issue_codes": source_issue_codes,
            "related_hypothesis_ids": related_hypothesis_ids,
        }
    )
    stable = {
        "schema_version": "visiondata-gate.action-contract.v1",
        "action_id": f"action_{identity[:20]}",
        "action_type": action_type,
        "accountable_owner_id": accountable_owner_id,
        "accountable_owner_role": accountable_owner_role,
        "requested_contributor_role": requested_contributor_role,
        "required_input": required_input,
        "reason": reason,
        "acceptance_criteria": acceptance_criteria,
        "blocking": blocking,
        "source_evidence_refs": source_evidence_refs,
        "source_issue_codes": source_issue_codes,
        "related_hypothesis_ids": related_hypothesis_ids,
        "status": "PROPOSED_REQUIRES_HUMAN",
        "machine_action_permitted": False,
        "production_release_permitted": False,
    }
    return ActionContract(**stable, action_sha256=_sha256(stable))


def _build_action_contracts(
    case: IndustrialIncidentCase,
    *,
    owner_id: str,
    owner_role: str,
) -> list[ActionContract]:
    evidence_refs = {item.evidence_ref for item in case.evidence_refs}
    fallback_ref = case.evidence_bundle_sha256 or case.case_sha256
    grouped: dict[str, list[object]] = defaultdict(list)
    for issue in case.evidence_issues:
        if issue.blocks_disposition:
            grouped[issue.worker_role].append(issue)
    actions: list[ActionContract] = []
    for worker_role, raw_issues in sorted(grouped.items()):
        issues = list(raw_issues)
        issue_codes = sorted({item.issue_code for item in issues})
        source_refs = sorted(
            {
                ref
                for item in issues
                for ref in [item.evidence_source, *item.input_evidence_refs]
                if ref in evidence_refs
            }
        ) or [fallback_ref]
        hypothesis_ids = sorted(
            {
                hypothesis.hypothesis_id
                for hypothesis in case.hypotheses
                if set(hypothesis.supporting_issue_codes) & set(issue_codes)
                or set(hypothesis.unresolved_evidence_refs) & set(source_refs)
            }
        )
        required = "；".join(
            dict.fromkeys(item.required_evidence_or_action for item in issues)
        )
        reason = "；".join(dict.fromkeys(item.summary for item in issues))
        actions.append(
            _action_contract(
                action_type="REQUEST_EVIDENCE",
                accountable_owner_id=owner_id,
                accountable_owner_role=owner_role,
                requested_contributor_role=_CONTRIBUTOR_BY_WORKER.get(
                    worker_role, worker_role
                ),
                required_input=required,
                reason=reason,
                acceptance_criteria=[
                    f"新证据必须绑定当前 case SHA {case.case_sha256}",
                    "证据必须通过来源、时间窗、字段和 SHA-256 完整性校验",
                    "补证只生成新 Receipt，不覆盖原始案件与失败证据",
                ],
                blocking=True,
                source_evidence_refs=source_refs,
                source_issue_codes=issue_codes,
                related_hypothesis_ids=hypothesis_ids,
            )
        )
    if case.linked_remediation_plan_ids:
        actions.append(
            _action_contract(
                action_type="SELECT_CAPA",
                accountable_owner_id=owner_id,
                accountable_owner_role=owner_role,
                requested_contributor_role="QualityManager",
                required_input=(
                    "由具名质量负责人从候选方案中选择："
                    + ", ".join(case.linked_remediation_plan_ids)
                ),
                reason="整改方案尚未获得与当前案件 SHA 绑定的人工决定。",
                acceptance_criteria=[
                    "选择结果生成不可变 Incident Decision Receipt",
                    "审批绑定包含 case SHA、plan ID、actor 和时间戳",
                    "选择方案不等同于执行完成或生产放行",
                ],
                blocking=True,
                source_evidence_refs=[case.case_sha256],
                source_issue_codes=[],
                related_hypothesis_ids=[
                    item.hypothesis_id
                    for item in case.hypotheses
                    if item.status.value != "REJECTED"
                ],
            )
        )
    capa = case.gate_context.capa_evidence
    if capa is not None and capa.recovery_status == "NOT_EXECUTED":
        actions.append(
            _action_contract(
                action_type="START_CHILD_RUN_REVERIFICATION",
                accountable_owner_id=owner_id,
                accountable_owner_role=owner_role,
                requested_contributor_role="VisionEngineer",
                required_input=(
                    "基于批准的派生版本启动同规则、独立 child Run 局部复验"
                ),
                reason="CAPA 已有绑定证据，但尚无独立 child Run 恢复结果。",
                acceptance_criteria=[
                    "child Run 绑定父案件、批准 SHA、派生版本 SHA 和同一规则版本",
                    "复验失败或证据冲突时维持 HOLD 并转调查",
                    "系统不得把 child Run 成功写成生产自动放行",
                ],
                blocking=True,
                source_evidence_refs=[capa.selection_sha256],
                source_issue_codes=[],
                related_hypothesis_ids=[
                    item.hypothesis_id
                    for item in case.hypotheses
                    if item.status.value != "REJECTED"
                ],
            )
        )
    if not actions:
        actions.append(
            _action_contract(
                action_type="ESCALATE_INVESTIGATION",
                accountable_owner_id=owner_id,
                accountable_owner_role=owner_role,
                requested_contributor_role="QualityEngineer",
                required_input="由具名责任人复核完整证据包与竞争假设。",
                reason="当前没有可自动闭合的安全动作，必须保留人工责任边界。",
                acceptance_criteria=[
                    "复核记录绑定当前 case SHA",
                    "根因、CAPA 和生产决定分别记录，不得合并推断",
                ],
                blocking=True,
                source_evidence_refs=[fallback_ref],
                source_issue_codes=[],
                related_hypothesis_ids=[item.hypothesis_id for item in case.hypotheses],
            )
        )
    return actions[:10]


def build_industrial_quality_decision_packet(
    case: IndustrialIncidentCase,
    *,
    control_plane: IncidentControlPlaneBundle,
    named_quality_owner_id: str,
    named_quality_owner_role: str = "QualityManager",
    site_pack: FactorySitePack | None = None,
    context_receipt: ContextReceipt | None = None,
    multimodal_advisor_receipt: MultimodalAdvisorReceipt | None = None,
) -> IndustrialQualityDecisionPacket:
    verify_industrial_incident_case(case)
    verify_incident_control_plane(control_plane, case=case)
    if site_pack is not None:
        verify_factory_site_pack(site_pack)
    if context_receipt is not None:
        if context_receipt.case_id != case.case_id or (
            context_receipt.case_sha256 != case.case_sha256
        ):
            raise ValueError("Decision Packet context receipt lost case binding")
        if site_pack is None or (
            context_receipt.site_pack_sha256 != site_pack.pack_sha256
        ):
            raise ValueError("Decision Packet context requires its bound Site Pack")
    if multimodal_advisor_receipt is not None:
        verify_multimodal_advisor_receipt(multimodal_advisor_receipt)
        if context_receipt is None or (
            multimodal_advisor_receipt.context_sha256 != context_receipt.context_sha256
        ):
            raise ValueError("Decision Packet advisor lost context binding")

    evidence_index = [
        DecisionEvidenceLink(
            evidence_ref=item.evidence_ref,
            evidence_type=item.evidence_type,
            evidence_sha256=item.evidence_sha256,
            qualification=item.qualification.value,
            role_in_decision=item.role_in_decision,
            current_case_eligible=item.qualification.value != "NOT_QUALIFIED",
        )
        for item in case.evidence_refs
    ]
    qualified_refs = [
        item.evidence_ref for item in evidence_index if item.current_case_eligible
    ] or [case.evidence_bundle_sha256 or case.case_sha256]
    facts = [
        DecisionVerifiedFact(
            fact_id=f"fact_{_sha256([case.case_sha256, statement])[:16]}",
            statement=statement,
            supporting_evidence_refs=qualified_refs,
        )
        for statement in case.decision_summary.observed_facts
    ]
    hypotheses = [
        DecisionHypothesis(
            hypothesis_id=item.hypothesis_id,
            category=item.category,
            status=item.status.value,
            supporting_issue_codes=item.supporting_issue_codes,
            contradicting_issue_codes=item.contradicting_issue_codes,
            unresolved_evidence_refs=item.unresolved_evidence_refs,
            next_discriminating_test=item.next_discriminating_test,
        )
        for item in case.hypotheses
    ]
    gaps = sorted(
        {ref for item in hypotheses for ref in item.unresolved_evidence_refs}
        | {
            f"{item.expected_evidence_type}:{item.question_id}"
            for item in case.operator_questions
            if item.status == "OPEN"
        }
    )
    unresolved_risks = sorted(
        item.issue_code for item in case.evidence_issues if item.blocks_disposition
    )
    actions = _build_action_contracts(
        case,
        owner_id=named_quality_owner_id,
        owner_role=named_quality_owner_role,
    )
    important_count = len(facts) + len(hypotheses) + len(actions)
    evidence_linked = sum(bool(item.supporting_evidence_refs) for item in facts)
    evidence_linked += sum(
        bool(item.supporting_issue_codes or item.unresolved_evidence_refs)
        for item in hypotheses
    )
    evidence_linked += sum(bool(item.source_evidence_refs) for item in actions)
    evidence_coverage = evidence_linked / important_count
    owner_coverage = sum(
        bool(item.accountable_owner_id and item.accountable_owner_role)
        for item in actions
    ) / len(actions)
    risk_visibility = 1.0
    completeness = (evidence_coverage + owner_coverage + risk_visibility) / 3
    metrics = DecisionPacketMetrics(
        evidence_link_coverage=round(evidence_coverage, 6),
        action_owner_coverage=round(owner_coverage, 6),
        unresolved_risk_visibility=risk_visibility,
        decision_packet_completeness=round(completeness, 6),
        important_conclusion_count=important_count,
        evidence_linked_conclusion_count=evidence_linked,
        action_count=len(actions),
        named_owner_action_count=sum(
            bool(item.accountable_owner_id and item.accountable_owner_role)
            for item in actions
        ),
    )
    capa = case.gate_context.capa_evidence
    options = [
        HumanDecisionOption(
            decision="CONTINUE_HOLD",
            enabled=True,
            reason="保留当前证据和安全边界，不提前闭合案件。",
        ),
        HumanDecisionOption(
            decision="SUPPLY_EVIDENCE",
            enabled=bool(gaps or unresolved_risks),
            reason="按 Action Contract 补充当前案件可验证证据。",
        ),
        HumanDecisionOption(
            decision="ESCALATE_INVESTIGATION",
            enabled=True,
            reason="竞争假设未消解时转具名专业人员调查。",
        ),
        HumanDecisionOption(
            decision="SELECT_CAPA",
            enabled=bool(case.linked_remediation_plan_ids),
            reason="只能选择已有候选方案，且选择不等同于执行或放行。",
        ),
        HumanDecisionOption(
            decision="REQUEST_CHILD_RUN_REVERIFICATION",
            enabled=capa is not None,
            reason="整改证据完整后才能请求同合同 child Run 独立复验。",
        ),
    ]
    common = {
        "case_id": case.case_id,
        "case_sha256": case.case_sha256,
        "case_version": case.case_version,
        "control_plane_sha256": control_plane.bundle_sha256,
        "site_id": site_pack.manifest.site_id if site_pack else None,
        "site_pack_sha256": site_pack.pack_sha256 if site_pack else None,
        "context_receipt_sha256": (
            context_receipt.receipt_sha256 if context_receipt else None
        ),
        "multimodal_advisor_receipt_sha256": (
            multimodal_advisor_receipt.receipt_sha256
            if multimodal_advisor_receipt
            else None
        ),
        "disposition": case.status.value,
        "recommendation": case.recommendation.value,
        "recommendation_reason": case.recommendation_reason,
        "root_cause_status": "NOT_ESTABLISHED",
        "named_quality_owner_id": named_quality_owner_id,
        "named_quality_owner_role": named_quality_owner_role,
        "evidence_index": evidence_index,
        "verified_facts": facts,
        "competing_hypotheses": hypotheses,
        "current_evidence_gaps": gaps,
        "unresolved_risk_codes": unresolved_risks,
        "action_contracts": actions,
        "human_decision_options": options,
        "linked_remediation_plan_ids": case.linked_remediation_plan_ids,
        "child_run_status": case.gate_context.child_run_status,
        "external_model_call_count": (
            case.external_model_call_count
            + (
                multimodal_advisor_receipt.model_call_count
                if multimodal_advisor_receipt
                else 0
            )
        ),
        "opcua_connection_status": case.opcua_connection_status,
        "visionmaster_connection_status": case.visionmaster_connection_status,
        "metrics": metrics,
        "human_approval_required": True,
        "production_release_allowed": False,
        "machine_write_permitted": False,
        "direct_equipment_control_permitted": False,
        "claim_boundary": _IndustrialQualityDecisionPacketBase.model_fields[
            "claim_boundary"
        ].default,
    }
    if case.schema_version == AGENT_KERNEL_INCIDENT_CASE_SCHEMA_VERSION:
        if (
            case.planning_belief_ledger is None
            or case.worker_selection_receipt is None
            or case.worker_execution_plan_receipt is None
            or case.council_arbitration_receipt is None
            or case.autonomy_guard_receipt is None
        ):
            raise ValueError("v6 Decision Packet requires Agent-kernel artifacts")
        stable = {
            "schema_version": ("visiondata-gate.industrial-quality-decision-packet.v3"),
            **common,
            "planning_belief_ledger": case.planning_belief_ledger,
            "worker_selection_receipt": case.worker_selection_receipt,
            "parent_belief_revision_receipt": (case.parent_belief_revision_receipt),
            "worker_execution_plan_receipt": case.worker_execution_plan_receipt,
            "council_arbitration_receipt": case.council_arbitration_receipt,
            "autonomy_guard_receipt": case.autonomy_guard_receipt,
        }
        packet: IndustrialQualityDecisionPacket = IndustrialQualityDecisionPacketV3(
            **stable,
            packet_sha256=_sha256(stable),
        )
    elif case.schema_version in PLANNING_ARTIFACT_INCIDENT_CASE_SCHEMA_VERSIONS:
        if case.planning_belief_ledger is None or case.worker_selection_receipt is None:
            raise ValueError("v5 Decision Packet requires the Case planning artifacts")
        stable = {
            "schema_version": ("visiondata-gate.industrial-quality-decision-packet.v2"),
            **common,
            "planning_belief_ledger": case.planning_belief_ledger,
            "worker_selection_receipt": case.worker_selection_receipt,
        }
        packet = IndustrialQualityDecisionPacketV2(
            **stable,
            packet_sha256=_sha256(stable),
        )
    else:
        stable = {
            "schema_version": ("visiondata-gate.industrial-quality-decision-packet.v1"),
            **common,
        }
        packet = IndustrialQualityDecisionPacketV1(
            **stable,
            packet_sha256=_sha256(stable),
        )
    verify_industrial_quality_decision_packet(
        packet,
        case=case,
        control_plane=control_plane,
    )
    return packet


def verify_industrial_quality_decision_packet(
    packet: IndustrialQualityDecisionPacket,
    *,
    case: IndustrialIncidentCase | None = None,
    control_plane: IncidentControlPlaneBundle | None = None,
) -> None:
    payload = packet.model_dump(mode="json")
    stored = payload.pop("packet_sha256")
    if not hmac.compare_digest(stored, _sha256(payload)):
        raise ValueError("industrial quality Decision Packet failed SHA-256 validation")
    if isinstance(packet, IndustrialQualityDecisionPacketV2):
        verify_evidence_belief_ledger_v2(packet.planning_belief_ledger)
        verify_worker_selection_receipt(packet.worker_selection_receipt)
    if isinstance(packet, IndustrialQualityDecisionPacketV3):
        verify_evidence_belief_ledger_v2(packet.planning_belief_ledger)
        verify_worker_selection_receipt(packet.worker_selection_receipt)
        if packet.parent_belief_revision_receipt is not None:
            verify_evidence_belief_revision_receipt_v1(
                packet.parent_belief_revision_receipt
            )
        verify_worker_execution_plan_receipt_v1(
            packet.worker_execution_plan_receipt,
            selection=packet.worker_selection_receipt,
        )
        verify_council_arbitration_receipt_v1(packet.council_arbitration_receipt)
        verify_autonomy_guard_receipt_v1(
            packet.autonomy_guard_receipt,
            selection=packet.worker_selection_receipt,
        )
    for action in packet.action_contracts:
        action_payload = action.model_dump(mode="json")
        action_sha = action_payload.pop("action_sha256")
        if not hmac.compare_digest(action_sha, _sha256(action_payload)):
            raise ValueError("Action Contract failed SHA-256 validation")
        if action.machine_action_permitted or action.production_release_permitted:
            raise ValueError("Action Contract escaped the industrial safety boundary")
    if packet.production_release_allowed or packet.machine_write_permitted:
        raise ValueError("Decision Packet escaped the industrial safety boundary")
    if case is not None:
        verify_industrial_incident_case(case)
        if packet.case_id != case.case_id or packet.case_sha256 != case.case_sha256:
            raise ValueError("Decision Packet failed immutable case binding")
        if packet.disposition != case.status.value or (
            packet.recommendation != case.recommendation.value
        ):
            raise ValueError("Decision Packet changed the incident disposition")
        if case.schema_version == AGENT_KERNEL_INCIDENT_CASE_SCHEMA_VERSION:
            expected_packet_type = IndustrialQualityDecisionPacketV3
        elif case.schema_version in PLANNING_ARTIFACT_INCIDENT_CASE_SCHEMA_VERSIONS:
            expected_packet_type = IndustrialQualityDecisionPacketV2
        else:
            expected_packet_type = IndustrialQualityDecisionPacketV1
        if not isinstance(packet, expected_packet_type):
            raise ValueError("Decision Packet schema does not match the Incident Case")
        if isinstance(packet, IndustrialQualityDecisionPacketV2) and (
            packet.planning_belief_ledger != case.planning_belief_ledger
            or packet.worker_selection_receipt != case.worker_selection_receipt
        ):
            raise ValueError("Decision Packet lost its planning-artifact binding")
        if isinstance(packet, IndustrialQualityDecisionPacketV3) and (
            packet.planning_belief_ledger != case.planning_belief_ledger
            or packet.worker_selection_receipt != case.worker_selection_receipt
            or packet.parent_belief_revision_receipt
            != case.parent_belief_revision_receipt
            or packet.worker_execution_plan_receipt
            != case.worker_execution_plan_receipt
            or packet.council_arbitration_receipt != case.council_arbitration_receipt
            or packet.autonomy_guard_receipt != case.autonomy_guard_receipt
        ):
            raise ValueError("Decision Packet lost its Agent-kernel binding")
    if control_plane is not None:
        if case is None:
            raise ValueError("control-plane verification requires the bound case")
        verify_incident_control_plane(control_plane, case=case)
        if packet.control_plane_sha256 != control_plane.bundle_sha256:
            raise ValueError("Decision Packet failed control-plane binding")


def decision_packet_json_bytes(packet: IndustrialQualityDecisionPacket) -> bytes:
    verify_industrial_quality_decision_packet(packet)
    return canonical_json_bytes(packet)


def evidence_request_csv_bytes(packet: IndustrialQualityDecisionPacket) -> bytes:
    verify_industrial_quality_decision_packet(packet)
    stream = io.StringIO(newline="")
    fields = [
        "action_id",
        "action_type",
        "accountable_owner_id",
        "accountable_owner_role",
        "requested_contributor_role",
        "required_input",
        "reason",
        "acceptance_criteria",
        "blocking",
        "source_evidence_refs",
        "source_issue_codes",
        "related_hypothesis_ids",
    ]
    writer = csv.DictWriter(stream, fieldnames=fields, lineterminator="\n")
    writer.writeheader()
    for action in packet.action_contracts:
        if action.action_type != "REQUEST_EVIDENCE":
            continue
        writer.writerow(
            {
                "action_id": action.action_id,
                "action_type": action.action_type,
                "accountable_owner_id": action.accountable_owner_id,
                "accountable_owner_role": action.accountable_owner_role,
                "requested_contributor_role": action.requested_contributor_role,
                "required_input": action.required_input,
                "reason": action.reason,
                "acceptance_criteria": " | ".join(action.acceptance_criteria),
                "blocking": str(action.blocking).lower(),
                "source_evidence_refs": " | ".join(action.source_evidence_refs),
                "source_issue_codes": " | ".join(action.source_issue_codes),
                "related_hypothesis_ids": " | ".join(action.related_hypothesis_ids),
            }
        )
    return stream.getvalue().encode("utf-8-sig")


def capa_action_list_json_bytes(packet: IndustrialQualityDecisionPacket) -> bytes:
    verify_industrial_quality_decision_packet(packet)
    payload = {
        "schema_version": "visiondata-gate.capa-action-list.v1",
        "case_id": packet.case_id,
        "case_sha256": packet.case_sha256,
        "packet_sha256": packet.packet_sha256,
        "actions": [item.model_dump(mode="json") for item in packet.action_contracts],
        "production_release_allowed": False,
        "machine_action_permitted": False,
    }
    return canonical_json_bytes(payload)


def decision_packet_html_bytes(packet: IndustrialQualityDecisionPacket) -> bytes:
    verify_industrial_quality_decision_packet(packet)

    def li(values: list[str]) -> str:
        return "".join(f"<li>{escape(value)}</li>" for value in values) or (
            "<li class=muted>当前无记录</li>"
        )

    hypotheses = "".join(
        "<tr>"
        f"<td><code>{escape(item.hypothesis_id)}</code></td>"
        f"<td>{escape(item.category)}</td>"
        f"<td><span class='state'>{escape(item.status)}</span></td>"
        f"<td>{escape(', '.join(item.supporting_issue_codes) or '—')}</td>"
        f"<td>{escape(', '.join(item.unresolved_evidence_refs) or '—')}</td>"
        "</tr>"
        for item in packet.competing_hypotheses
    )
    actions = "".join(
        "<article class=action>"
        f"<div class=action-title><span>{escape(item.action_type)}</span>"
        f"<code>{escape(item.action_id)}</code></div>"
        f"<p><b>责任人</b> {escape(item.accountable_owner_id)} · "
        f"{escape(item.accountable_owner_role)}</p>"
        f"<p><b>协作角色</b> {escape(item.requested_contributor_role)}</p>"
        f"<p><b>需要</b> {escape(item.required_input)}</p>"
        f"<p><b>原因</b> {escape(item.reason)}</p>"
        f"<ul>{li(item.acceptance_criteria)}</ul>"
        f"<p class=refs>证据：{escape(', '.join(item.source_evidence_refs))}</p>"
        "</article>"
        for item in packet.action_contracts
    )
    evidence = "".join(
        f"<tr id='{escape(item.evidence_ref)}'><td><code>{escape(item.evidence_ref)}</code>"
        f"</td><td>{escape(item.evidence_type)}</td><td>{escape(item.qualification)}</td>"
        f"<td><code>{escape(item.evidence_sha256[:16])}…</code></td></tr>"
        for item in packet.evidence_index
    )
    html = f"""<!doctype html>
<html lang="zh-CN"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>VisionData Gate Decision Packet</title><style>
:root{{--ink:#17201d;--muted:#66716d;--line:#dce4e0;--paper:#f6f8f7;--card:#fff;--green:#175f4c;--amber:#9a5a08}}
*{{box-sizing:border-box}}body{{margin:0;background:var(--paper);color:var(--ink);font:15px/1.55 Inter,-apple-system,BlinkMacSystemFont,"Segoe UI","PingFang SC","Microsoft YaHei",sans-serif}}
main{{max-width:1180px;margin:0 auto;padding:36px 24px 72px}}header{{display:flex;justify-content:space-between;gap:24px;align-items:flex-start;margin-bottom:22px}}h1{{font-size:30px;line-height:1.1;margin:5px 0 8px}}h2{{font-size:18px;margin:0 0 14px}}p{{margin:7px 0}}.eyebrow{{color:var(--green);font-size:12px;font-weight:800;letter-spacing:.12em;text-transform:uppercase}}.badges{{display:flex;gap:8px;flex-wrap:wrap;justify-content:flex-end}}.badge,.state{{display:inline-block;border:1px solid var(--line);background:#fff;border-radius:999px;padding:5px 10px;font-size:12px;font-weight:700}}.badge.hold{{background:#fff4df;border-color:#f0d49e;color:var(--amber)}}.grid{{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:16px}}section{{background:var(--card);border:1px solid var(--line);border-radius:18px;padding:20px;box-shadow:0 8px 28px rgba(23,32,29,.04)}}section.wide{{grid-column:1/-1}}ul{{margin:0;padding-left:20px}}table{{width:100%;border-collapse:collapse;font-size:13px}}th,td{{text-align:left;vertical-align:top;padding:10px;border-bottom:1px solid var(--line)}}th{{color:var(--muted);font-weight:700}}code{{font:12px/1.4 ui-monospace,SFMono-Regular,Consolas,monospace;word-break:break-all}}.actions{{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:12px}}.action{{border:1px solid var(--line);border-radius:14px;padding:15px;background:#fcfdfc}}.action-title{{display:flex;justify-content:space-between;gap:10px;font-weight:800;color:var(--green)}}.refs,.muted{{color:var(--muted);font-size:12px}}footer{{margin-top:18px;padding:16px;border-left:4px solid var(--amber);background:#fff9ef;color:#6b4a1b}}@media(max-width:760px){{.grid,.actions{{grid-template-columns:1fr}}header{{display:block}}.badges{{justify-content:flex-start;margin-top:12px}}}}
</style></head><body><main>
<header><div><div class=eyebrow>Industrial Quality Decision Packet</div><h1>换型后视觉质量异常处置</h1><p>案件 <code>{escape(packet.case_id)}</code> · 不可变版本 {packet.case_version}</p></div><div class=badges><span class="badge hold">{escape(packet.disposition)}</span><span class=badge>Root cause: NOT_ESTABLISHED</span><span class=badge>Human approval required</span></div></header>
<div class=grid>
<section><h2>① 当前状态</h2><p><b>建议：</b>{escape(packet.recommendation)}</p><p>{escape(packet.recommendation_reason)}</p><p><b>具名责任人：</b>{escape(packet.named_quality_owner_id)} · {escape(packet.named_quality_owner_role)}</p><p class=refs>Case SHA <code>{escape(packet.case_sha256)}</code></p></section>
<section><h2>② 已验证事实</h2><ul>{li([item.statement for item in packet.verified_facts])}</ul><p class=refs>范围：当前案件证据；不构成根因认定。</p></section>
<section class=wide><h2>③ 竞争假设</h2><div style="overflow:auto"><table><thead><tr><th>假设</th><th>类别</th><th>状态</th><th>支持代码</th><th>未决证据</th></tr></thead><tbody>{hypotheses}</tbody></table></div></section>
<section><h2>④ 当前缺口</h2><ul>{li(packet.current_evidence_gaps)}</ul><p class=refs>未关闭风险：{escape(", ".join(packet.unresolved_risk_codes) or "无")}</p></section>
<section><h2>⑥ 下一步人工决定</h2><ul>{li([f"{item.decision}: {'可选' if item.enabled else '条件未满足'} — {item.reason}" for item in packet.human_decision_options])}</ul></section>
<section class=wide><h2>⑤ 建议动作</h2><div class=actions>{actions}</div></section>
<section class=wide><h2>证据索引</h2><div style="overflow:auto"><table><thead><tr><th>Evidence Ref</th><th>类型</th><th>资格</th><th>SHA-256</th></tr></thead><tbody>{evidence}</tbody></table></div></section>
</div><footer>{escape(packet.claim_boundary)}</footer>
</main></body></html>
"""
    return html.encode("utf-8")


def _zip_info(name: str) -> zipfile.ZipInfo:
    info = zipfile.ZipInfo(name, ZIP_EPOCH)
    info.compress_type = zipfile.ZIP_STORED
    info.external_attr = 0o100644 << 16
    info.create_system = 3
    return info


def build_decision_packet_exports(
    packet: IndustrialQualityDecisionPacket,
) -> DecisionPacketExports:
    verify_industrial_quality_decision_packet(packet)
    artifacts = {
        "capa_action_list.json": capa_action_list_json_bytes(packet),
        "decision_packet.html": decision_packet_html_bytes(packet),
        "decision_packet.json": decision_packet_json_bytes(packet),
        "evidence_request_list.csv": evidence_request_csv_bytes(packet),
    }
    behavior_receipt: AgentBehaviorReceiptV1 | None = None
    if isinstance(
        packet, (IndustrialQualityDecisionPacketV2, IndustrialQualityDecisionPacketV3)
    ):
        behavior_receipt = build_agent_behavior_receipt(packet.worker_selection_receipt)
        verify_agent_behavior_receipt(
            behavior_receipt,
            selection=packet.worker_selection_receipt,
        )
        artifacts["agent_behavior_receipt.json"] = canonical_json_bytes(
            behavior_receipt
        )
    manifest = {
        "schema_version": "visiondata-gate.decision-packet-manifest.v1",
        "case_id": packet.case_id,
        "case_sha256": packet.case_sha256,
        "packet_sha256": packet.packet_sha256,
        "artifacts": {
            name: {"sha256": _sha256_bytes(data), "byte_count": len(data)}
            for name, data in sorted(artifacts.items())
        },
        "raw_source_assets_included": False,
    }
    artifacts["manifest.json"] = canonical_json_bytes(manifest)
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", compression=zipfile.ZIP_STORED) as archive:
        for name, data in sorted(artifacts.items()):
            archive.writestr(_zip_info(name), data)
    bundle = buffer.getvalue()
    media_types = {
        "agent_behavior_receipt.json": "application/json",
        "capa_action_list.json": "application/json",
        "decision_packet.html": "text/html; charset=utf-8",
        "decision_packet.json": "application/json",
        "evidence_request_list.csv": "text/csv; charset=utf-8",
        "manifest.json": "application/json",
    }
    export_artifacts = [
        DecisionPacketExportArtifact(
            path=name,
            media_type=media_types[name],
            byte_count=len(data),
            sha256=_sha256_bytes(data),
        )
        for name, data in sorted(artifacts.items())
    ]
    bundle_sha = _sha256_bytes(bundle)
    stable = {
        "schema_version": "visiondata-gate.decision-packet-export.v1",
        "case_id": packet.case_id,
        "case_sha256": packet.case_sha256,
        "packet_sha256": packet.packet_sha256,
        "artifacts": export_artifacts,
        "audit_bundle_sha256": bundle_sha,
        "deterministic_archive": True,
        "raw_source_assets_included": False,
    }
    receipt = DecisionPacketExportReceipt(
        **stable,
        receipt_sha256=_sha256(stable),
    )
    return DecisionPacketExports(
        decision_packet_json=artifacts["decision_packet.json"],
        decision_packet_html=artifacts["decision_packet.html"],
        evidence_request_csv=artifacts["evidence_request_list.csv"],
        capa_action_list_json=artifacts["capa_action_list.json"],
        agent_behavior_receipt_json=(
            artifacts.get("agent_behavior_receipt.json")
            if behavior_receipt is not None
            else None
        ),
        audit_bundle_zip=bundle,
        receipt=receipt,
    )


def write_decision_packet_exports(
    root: str | Path,
    exports: DecisionPacketExports,
) -> None:
    destination = Path(root).expanduser().resolve()
    destination.mkdir(parents=True, exist_ok=True)
    files = {
        "decision_packet.json": exports.decision_packet_json,
        "decision_packet.html": exports.decision_packet_html,
        "evidence_request_list.csv": exports.evidence_request_csv,
        "capa_action_list.json": exports.capa_action_list_json,
        "audit_bundle.zip": exports.audit_bundle_zip,
        "export_receipt.json": canonical_json_bytes(exports.receipt),
    }
    if exports.agent_behavior_receipt_json is not None:
        files["agent_behavior_receipt.json"] = exports.agent_behavior_receipt_json
    for name, data in files.items():
        path = destination / name
        if path.exists() and path.read_bytes() != data:
            raise FileExistsError(f"refusing to overwrite a different export: {name}")
        if not path.exists():
            path.write_bytes(data)


__all__ = [
    "ActionContract",
    "DecisionPacketExportReceipt",
    "DecisionPacketExports",
    "IndustrialQualityDecisionPacket",
    "IndustrialQualityDecisionPacketV1",
    "IndustrialQualityDecisionPacketV2",
    "IndustrialQualityDecisionPacketV3",
    "build_decision_packet_exports",
    "build_industrial_quality_decision_packet",
    "capa_action_list_json_bytes",
    "decision_packet_html_bytes",
    "decision_packet_json_bytes",
    "evidence_request_csv_bytes",
    "verify_industrial_quality_decision_packet",
    "write_decision_packet_exports",
]
