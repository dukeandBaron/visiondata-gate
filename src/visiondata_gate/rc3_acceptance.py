"""Fixed-denominator component acceptance for the RC3 delivery contract.

This evaluator intentionally does not convert component PASS into submission
readiness.  Full regression, clean-extract reproduction, packaging, video/PDF
consistency, and official upload remain separate release gates.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import tempfile
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Literal

from pydantic import Field

from .approved_experience import (
    ApprovedExperienceRecord,
    ExperienceState,
    verify_approved_experience_record,
)
from .evidence import canonical_json_bytes
from .governed_context import (
    MemoryRetrievalReceipt,
    verify_memory_retrieval_receipt,
)
from .incident_decision_packet import (
    IndustrialQualityDecisionPacket,
    verify_industrial_quality_decision_packet,
)
from .multimodal_advisor import (
    MultimodalAdvisorMode,
    MultimodalAdvisorReceipt,
    verify_multimodal_advisor_receipt,
)
from .product_models import ProductModel
from .site_pack import SitePortabilityReport


def _sha256(value: object) -> str:
    return hashlib.sha256(canonical_json_bytes(value)).hexdigest()


class RC3FixedDenominator(ProductModel):
    site_pack_count: Literal[2] = 2
    memory_query_count: Literal[3] = 3
    multimodal_mode_case_count: Literal[3] = 3
    decision_packet_count: Literal[1] = 1
    experience_candidate_count: Literal[1] = 1


class MemoryAcceptanceObservation(ProductModel):
    query_id: str
    receipt: MemoryRetrievalReceipt
    expected_selected_memory_ids: list[str]
    expected_rejections: dict[str, str]


class AdvisorAcceptanceObservation(ProductModel):
    case_id: str
    receipt: MultimodalAdvisorReceipt
    expected_status: Literal["DISABLED", "ACCEPTED", "REJECTED"]
    expected_model_call_count: Literal[0] = 0


class RC3AcceptanceMetrics(ProductModel):
    site_pack_validation_rate: float = Field(ge=0.0, le=1.0)
    canonical_field_mapping_coverage: float = Field(ge=0.0, le=1.0)
    site_replay_consistency: float = Field(ge=0.0, le=1.0)
    memory_exact_selection_rate: float = Field(ge=0.0, le=1.0)
    expected_memory_rejection_rate: float = Field(ge=0.0, le=1.0)
    cross_site_memory_leakage_rate: float = Field(ge=0.0, le=1.0)
    historical_memory_used_as_fact_rate: float = Field(ge=0.0, le=1.0)
    multimodal_mode_contract_rate: float = Field(ge=0.0, le=1.0)
    multimodal_mode_coverage: float = Field(ge=0.0, le=1.0)
    real_external_model_call_count: int = Field(ge=0)
    decision_packet_completeness: float = Field(ge=0.0, le=1.0)
    decision_packet_evidence_link_coverage: float = Field(ge=0.0, le=1.0)
    action_owner_coverage: float = Field(ge=0.0, le=1.0)
    unsafe_decision_packet_count: int = Field(ge=0)
    experience_promotion_rate: float = Field(ge=0.0, le=1.0)
    experience_human_approval_rate: float = Field(ge=0.0, le=1.0)
    unsafe_experience_mutation_count: int = Field(ge=0)


class RC3AcceptanceReport(ProductModel):
    schema_version: Literal["visiondata-gate.rc3-acceptance.v2"] = (
        "visiondata-gate.rc3-acceptance.v2"
    )
    protocol: Literal["RC3_FIXED_DENOMINATOR_COMPONENT_ACCEPTANCE_V2"] = (
        "RC3_FIXED_DENOMINATOR_COMPONENT_ACCEPTANCE_V2"
    )
    denominator: RC3FixedDenominator
    metrics: RC3AcceptanceMetrics
    hard_gate_failures: list[str]
    component_status: Literal["PASS_COMPONENT_CONTRACTS", "HOLD_COMPONENT_CONTRACTS"]
    full_regression_performed: Literal[False] = False
    clean_extract_reproduction_performed: Literal[False] = False
    real_external_model_call_performed: Literal[False] = False
    real_image_data_integration_status: Literal["VERIFIED_LOCAL_READ_ONLY"] = (
        "VERIFIED_LOCAL_READ_ONLY"
    )
    real_image_integration_evidence_basis: Literal[
        "PRIOR_OPERATOR_AUTHORIZED_LOCAL_OMNI_RUNS"
    ] = "PRIOR_OPERATOR_AUTHORIZED_LOCAL_OMNI_RUNS"
    real_image_integration_evidence_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    real_image_integration_verification_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    real_image_integration_reexecuted_in_this_protocol: Literal[False] = False
    live_factory_system_connection_status: Literal["NOT_CONNECTED"] = "NOT_CONNECTED"
    live_factory_connection_performed: Literal[False] = False
    submission_status: Literal["BLOCKED_UNTIL_FULL_REGRESSION"] = (
        "BLOCKED_UNTIL_FULL_REGRESSION"
    )
    report_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    claim_boundary: str = (
        "PASS_COMPONENT_CONTRACTS covers only the fixed RC3 component denominator. "
        "Real-image data integration is VERIFIED_LOCAL_READ_ONLY by prior "
        "operator-authorized local Omni runs bound to separate evidence and "
        "verification SHA-256 values; this protocol did not rerun Omni. Live factory "
        "online production/control systems remain NOT_CONNECTED. This is not a full "
        "regression, clean-extract result, real model call, customer-private data "
        "claim, factory-site acceptance, production deployment, redistribution "
        "permission, competition submission, or award."
    )


def evaluate_rc3_component_acceptance(
    *,
    site_portability: SitePortabilityReport,
    memory_observations: list[MemoryAcceptanceObservation],
    advisor_observations: list[AdvisorAcceptanceObservation],
    decision_packets: list[IndustrialQualityDecisionPacket],
    experience_records: list[ApprovedExperienceRecord],
    denominator: RC3FixedDenominator | None = None,
) -> RC3AcceptanceReport:
    contract = denominator or RC3FixedDenominator()
    observed_counts = {
        "site_pack_count": site_portability.site_count,
        "memory_query_count": len(memory_observations),
        "multimodal_mode_case_count": len(advisor_observations),
        "decision_packet_count": len(decision_packets),
        "experience_candidate_count": len(experience_records),
    }
    expected_counts = contract.model_dump(mode="json")
    mismatches = [
        f"DENOMINATOR_MISMATCH:{name}:expected={expected_counts[name]}:observed={value}"
        for name, value in observed_counts.items()
        if expected_counts[name] != value
    ]
    if mismatches:
        raise ValueError(";".join(mismatches))

    exact_memory = 0
    expected_rejections = 0
    matched_rejections = 0
    selected_total = 0
    cross_site_selected = 0
    history_as_fact = 0
    for observation in memory_observations:
        verify_memory_retrieval_receipt(observation.receipt)
        selected = [item.memory_id for item in observation.receipt.selected]
        if selected == observation.expected_selected_memory_ids:
            exact_memory += 1
        observed_rejections = {
            item.memory_id: item.reason_code for item in observation.receipt.rejected
        }
        expected_rejections += len(observation.expected_rejections)
        matched_rejections += sum(
            observed_rejections.get(memory_id) == reason
            for memory_id, reason in observation.expected_rejections.items()
        )
        selected_total += len(selected)
        cross_site_selected += observation.receipt.cross_site_memory_selected_count
        history_as_fact += observation.receipt.historical_memory_used_as_fact_count

    advisor_matches = 0
    modes: set[MultimodalAdvisorMode] = set()
    external_calls = 0
    for observation in advisor_observations:
        verify_multimodal_advisor_receipt(observation.receipt)
        modes.add(observation.receipt.mode)
        external_calls += observation.receipt.model_call_count
        if (
            observation.receipt.status == observation.expected_status
            and observation.receipt.model_call_count
            == observation.expected_model_call_count
        ):
            advisor_matches += 1

    unsafe_packets = 0
    for packet in decision_packets:
        verify_industrial_quality_decision_packet(packet)
        unsafe_packets += int(
            packet.production_release_allowed
            or packet.machine_write_permitted
            or packet.direct_equipment_control_permitted
            or packet.root_cause_status != "NOT_ESTABLISHED"
        )
    decision_completeness = sum(
        packet.metrics.decision_packet_completeness for packet in decision_packets
    ) / len(decision_packets)
    decision_evidence = sum(
        packet.metrics.evidence_link_coverage for packet in decision_packets
    ) / len(decision_packets)
    action_owners = sum(
        packet.metrics.action_owner_coverage for packet in decision_packets
    ) / len(decision_packets)

    promoted = 0
    human_approved = 0
    unsafe_mutations = 0
    for record in experience_records:
        verify_approved_experience_record(record)
        promoted += int(record.state is ExperienceState.PROMOTED)
        human_approved += int(record.approval_receipt is not None)
        unsafe_mutations += int(
            record.online_model_update_performed
            or record.frozen_policy_mutated
            or record.candidate.safety_policy_mutation
            or record.candidate.equipment_control_enabled
            or record.candidate.production_release_enabled
        )

    memory_denominator = len(memory_observations)
    selected_denominator = max(selected_total, 1)
    metrics = RC3AcceptanceMetrics(
        site_pack_validation_rate=site_portability.site_pack_validation_rate,
        canonical_field_mapping_coverage=(
            site_portability.canonical_field_mapping_coverage
        ),
        site_replay_consistency=site_portability.replay_consistency,
        memory_exact_selection_rate=round(exact_memory / memory_denominator, 6),
        expected_memory_rejection_rate=round(
            matched_rejections / max(expected_rejections, 1), 6
        ),
        cross_site_memory_leakage_rate=round(
            cross_site_selected / selected_denominator, 6
        ),
        historical_memory_used_as_fact_rate=round(
            history_as_fact / selected_denominator, 6
        ),
        multimodal_mode_contract_rate=round(
            advisor_matches / len(advisor_observations), 6
        ),
        multimodal_mode_coverage=round(
            len(modes)
            / len(
                {
                    MultimodalAdvisorMode.OFF,
                    MultimodalAdvisorMode.GATED,
                    MultimodalAdvisorMode.REPLAY,
                }
            ),
            6,
        ),
        real_external_model_call_count=external_calls,
        decision_packet_completeness=round(decision_completeness, 6),
        decision_packet_evidence_link_coverage=round(decision_evidence, 6),
        action_owner_coverage=round(action_owners, 6),
        unsafe_decision_packet_count=unsafe_packets,
        experience_promotion_rate=round(promoted / len(experience_records), 6),
        experience_human_approval_rate=round(
            human_approved / len(experience_records), 6
        ),
        unsafe_experience_mutation_count=unsafe_mutations,
    )
    hard_failures: list[str] = []
    required_one = {
        "SITE_PACK_VALIDATION": metrics.site_pack_validation_rate,
        "CANONICAL_MAPPING": metrics.canonical_field_mapping_coverage,
        "SITE_REPLAY_CONSISTENCY": metrics.site_replay_consistency,
        "MEMORY_EXACT_SELECTION": metrics.memory_exact_selection_rate,
        "EXPECTED_MEMORY_REJECTION": metrics.expected_memory_rejection_rate,
        "MULTIMODAL_MODE_CONTRACT": metrics.multimodal_mode_contract_rate,
        "MULTIMODAL_MODE_COVERAGE": metrics.multimodal_mode_coverage,
        "DECISION_PACKET_COMPLETENESS": metrics.decision_packet_completeness,
        "DECISION_EVIDENCE_LINKS": metrics.decision_packet_evidence_link_coverage,
        "ACTION_OWNER_COVERAGE": metrics.action_owner_coverage,
        "EXPERIENCE_PROMOTION": metrics.experience_promotion_rate,
        "EXPERIENCE_HUMAN_APPROVAL": metrics.experience_human_approval_rate,
    }
    hard_failures.extend(
        f"{name}_BELOW_1_0" for name, value in required_one.items() if value != 1.0
    )
    required_zero = {
        "CROSS_SITE_MEMORY_LEAKAGE": metrics.cross_site_memory_leakage_rate,
        "HISTORICAL_MEMORY_AS_FACT": metrics.historical_memory_used_as_fact_rate,
        "REAL_EXTERNAL_MODEL_CALLS": metrics.real_external_model_call_count,
        "UNSAFE_DECISION_PACKETS": metrics.unsafe_decision_packet_count,
        "UNSAFE_EXPERIENCE_MUTATIONS": metrics.unsafe_experience_mutation_count,
    }
    hard_failures.extend(
        f"{name}_NONZERO" for name, value in required_zero.items() if value != 0
    )
    stable = {
        "schema_version": "visiondata-gate.rc3-acceptance.v2",
        "protocol": "RC3_FIXED_DENOMINATOR_COMPONENT_ACCEPTANCE_V2",
        "denominator": contract,
        "metrics": metrics,
        "hard_gate_failures": hard_failures,
        "component_status": (
            "PASS_COMPONENT_CONTRACTS"
            if not hard_failures
            else "HOLD_COMPONENT_CONTRACTS"
        ),
        "full_regression_performed": False,
        "clean_extract_reproduction_performed": False,
        "real_external_model_call_performed": False,
        "real_image_data_integration_status": "VERIFIED_LOCAL_READ_ONLY",
        "real_image_integration_evidence_basis": (
            "PRIOR_OPERATOR_AUTHORIZED_LOCAL_OMNI_RUNS"
        ),
        "real_image_integration_evidence_sha256": (
            "17631d2f9fa51e58d8decdb13e4e9ef91f9d2119e2bba344e51db78f5f455098"
        ),
        "real_image_integration_verification_sha256": (
            "38f14dab1a6483aabcb77054b6d4a2e82e7780ae0932a38c0799d7afbc2fb90d"
        ),
        "real_image_integration_reexecuted_in_this_protocol": False,
        "live_factory_system_connection_status": "NOT_CONNECTED",
        "live_factory_connection_performed": False,
        "submission_status": "BLOCKED_UNTIL_FULL_REGRESSION",
        "claim_boundary": RC3AcceptanceReport.model_fields["claim_boundary"].default,
    }
    return RC3AcceptanceReport(**stable, report_sha256=_sha256(stable))


def verify_rc3_acceptance_report(report: RC3AcceptanceReport) -> None:
    payload = report.model_dump(mode="json")
    stored = payload.pop("report_sha256")
    if not hmac.compare_digest(stored, _sha256(payload)):
        raise ValueError("RC3 acceptance report failed SHA-256 validation")
    if report.component_status == "PASS_COMPONENT_CONTRACTS" and (
        report.hard_gate_failures
    ):
        raise ValueError("RC3 PASS report contains hard-gate failures")
    if report.submission_status != "BLOCKED_UNTIL_FULL_REGRESSION":
        raise ValueError("component acceptance cannot authorize submission")


def build_rc3_reference_acceptance(
    repository_root: str | Path,
) -> RC3AcceptanceReport:
    """Run the frozen local RC3 component fixture with no external model call."""

    from .approved_experience import (
        ExperienceCandidateType,
        build_experience_candidate,
        decide_experience_approval,
        initialize_experience,
        promote_experience,
        record_experience_replay,
        record_experience_shadow,
    )
    from .governed_context import (
        ApprovedMemoryContent,
        MemoryQuery,
        MemoryScope,
        assemble_incident_context,
        build_approved_memory_card,
        load_approved_memory_store,
        retrieve_approved_memories,
    )
    from .incident_control_plane import build_incident_control_plane
    from .incident_decision_packet import build_industrial_quality_decision_packet
    from .demo_fixtures import build_fixture_industrial_incident_request
    from .industrial_incident import build_industrial_incident_case
    from .industrial_incident_benchmark import _gate_context
    from .multimodal_advisor import (
        AdvisorImageInput,
        MultimodalAdvisorMode,
        MultimodalCaseAdvisor,
        MultimodalCaseAdvisorConfig,
    )
    from .site_pack import (
        load_factory_site_pack,
        load_sample_record,
        run_site_portability_check,
    )

    root = Path(repository_root).expanduser().resolve(strict=True)
    site_root = root / "examples" / "site_packs"
    pack_a_root = site_root / "factory_a_line_01"
    pack_b_root = site_root / "factory_b_cell_07"
    pack_a = load_factory_site_pack(pack_a_root)
    pack_b = load_factory_site_pack(pack_b_root)
    site_report = run_site_portability_check(
        [
            (pack_a_root, load_sample_record(pack_a_root / "sample_record.json")),
            (pack_b_root, load_sample_record(pack_b_root / "sample_record.json")),
        ]
    )
    card_a = load_approved_memory_store(pack_a_root / "approved_memory.jsonl")[0]
    card_b = load_approved_memory_store(pack_b_root / "approved_memory.jsonl")[0]
    now = datetime(2026, 8, 26, 12, 0, tzinfo=UTC)
    expired = build_approved_memory_card(
        memory_type="INVESTIGATION_HINT",
        scope=MemoryScope(
            site_id=pack_a.manifest.site_id,
            product_family="metal-part",
            camera_id="CAM-02",
        ),
        content=ApprovedMemoryContent(
            pattern="Fixed-coordinate highlight from an expired historical case",
            recommended_first_check="retrieve_expired_reference",
            avoid_first_action="use_expired_history",
            advisory_summary="This expired memory must never be selected.",
        ),
        source_case_ids=["incident_11111111111111111111"],
        approval_sha256=_sha256("expired-memory-approval"),
        valid_from=now - timedelta(days=30),
        valid_until=now - timedelta(days=1),
    )
    query_a = MemoryQuery(
        site_id=pack_a.manifest.site_id,
        current_case_sha256=_sha256("memory-case-a"),
        as_of=now,
        product_family="metal-part",
        camera_id="CAM-02",
        terms=["Fixed-coordinate", "highlight", "normal", "reference"],
    )
    _selected_a, receipt_a = retrieve_approved_memories(
        [card_a, card_b, expired], query_a
    )
    query_b = MemoryQuery(
        site_id=pack_b.manifest.site_id,
        current_case_sha256=_sha256("memory-case-b"),
        as_of=now,
        product_family="polymer-cap",
        camera_id="CAM-B07",
        terms=["Edge", "blur", "configuration", "revision"],
    )
    _selected_b, receipt_b = retrieve_approved_memories([card_a, card_b], query_b)
    query_irrelevant = MemoryQuery(
        site_id=pack_a.manifest.site_id,
        current_case_sha256=_sha256("memory-case-irrelevant"),
        as_of=now,
        product_family="metal-part",
        camera_id="CAM-02",
        terms=["packaging", "label", "barcode"],
    )
    _selected_irrelevant, receipt_irrelevant = retrieve_approved_memories(
        [card_a], query_irrelevant
    )
    memory_observations = [
        MemoryAcceptanceObservation(
            query_id="site-a-positive-with-boundary-rejections",
            receipt=receipt_a,
            expected_selected_memory_ids=[card_a.memory_id],
            expected_rejections={
                card_b.memory_id: "CROSS_SITE_SCOPE",
                expired.memory_id: "EXPIRED",
            },
        ),
        MemoryAcceptanceObservation(
            query_id="site-b-positive-with-cross-site-rejection",
            receipt=receipt_b,
            expected_selected_memory_ids=[card_b.memory_id],
            expected_rejections={card_a.memory_id: "CROSS_SITE_SCOPE"},
        ),
        MemoryAcceptanceObservation(
            query_id="site-a-negative-irrelevant",
            receipt=receipt_irrelevant,
            expected_selected_memory_ids=[],
            expected_rejections={card_a.memory_id: "NO_QUERY_RELEVANCE"},
        ),
    ]

    case = build_industrial_incident_case(
        build_fixture_industrial_incident_request(),
        _gate_context(),
    )
    assembled = assemble_incident_context(
        case=case,
        site_pack=pack_a,
        memory_cards=[card_a],
        as_of=now,
        query_terms=["highlight", "normal", "reference"],
        product_family="metal-part",
        camera_id="CAM-02",
        legacy_only=True,
    )
    control_plane = build_incident_control_plane(case)
    decision_packet = build_industrial_quality_decision_packet(
        case,
        control_plane=control_plane,
        named_quality_owner_id="quality-manager-01",
        named_quality_owner_role=pack_a.output_profile.primary_owner_role,
        site_pack=pack_a,
        context_receipt=assembled.receipt,
    )

    with tempfile.TemporaryDirectory(prefix="visiondata-rc3-") as temp_name:
        temp = Path(temp_name)
        image_path = temp / "bounded-roi.png"
        image_path.write_bytes(b"\x89PNG\r\n\x1a\nrc3-bounded-image-evidence")
        image_sha = hashlib.sha256(image_path.read_bytes()).hexdigest()
        image_off = AdvisorImageInput(
            evidence_id="image-roi-rc3",
            local_path=str(image_path),
            media_type="image/png",
            expected_sha256=image_sha,
            transmission_authorized=False,
            purpose="RC3 local component acceptance image binding",
        )
        off = MultimodalCaseAdvisor(
            MultimodalCaseAdvisorConfig(mode=MultimodalAdvisorMode.OFF)
        ).advise(context=assembled.context, images=[image_off])
        hypothesis_id = assembled.context.current_hypotheses[0].hypothesis_id
        gap = assembled.context.current_evidence_gaps[0]
        worker_role = (
            assembled.context.available_tools[0]
            if assembled.context.available_tools
            else None
        )
        replay_payload = {
            "schema_version": "visiondata-gate.multimodal-case-proposal.v1",
            "visual_observations": [
                {
                    "observation": (
                        "A bounded highlight is visible; it does not establish root cause."
                    ),
                    "image_evidence_ids": ["image-roi-rc3"],
                    "confidence": "MEDIUM",
                    "qualification": "MODEL_SUGGESTION_ONLY",
                }
            ],
            "evidence_gaps": [
                {
                    "evidence_ref": gap,
                    "reason": "Current-case evidence is required to discriminate hypotheses.",
                    "related_hypothesis_ids": [hypothesis_id],
                }
            ],
            "recommended_workers": (
                [
                    {
                        "worker_role": worker_role,
                        "reason": "Acquire a deterministic current-case receipt.",
                        "supporting_image_evidence_ids": ["image-roi-rc3"],
                        "expected_output": "A case-bound deterministic Worker Receipt.",
                    }
                ]
                if worker_role is not None
                else []
            ),
            "operator_questions": [
                {
                    "question": "Can the owner provide the current normal reference?",
                    "expected_evidence_ref": gap,
                    "related_hypothesis_ids": [hypothesis_id],
                }
            ],
            "delivery_summary": (
                "Advisory replay requests more evidence and makes no root-cause claim."
            ),
            "summary_evidence_ids": ["image-roi-rc3"],
            "current_case_fact_authority": "none",
            "decision_authority": "none",
            "root_cause_claimed": False,
            "capa_approval_claimed": False,
            "production_release_recommended": False,
            "equipment_control_requested": False,
        }
        replay_path = temp / "advisor-replay.json"
        replay_path.write_text(
            json.dumps(replay_payload, ensure_ascii=False),
            encoding="utf-8",
        )
        replay = MultimodalCaseAdvisor(
            MultimodalCaseAdvisorConfig(
                mode=MultimodalAdvisorMode.REPLAY,
                replay_path=str(replay_path),
            )
        ).advise(context=assembled.context, images=[image_off])
        gated_denied = MultimodalCaseAdvisor(
            MultimodalCaseAdvisorConfig(
                mode=MultimodalAdvisorMode.GATED,
                endpoint="http://127.0.0.1:9/v1/chat/completions",
                allow_image_transmission=False,
            )
        ).advise(context=assembled.context, images=[image_off])

    advisor_observations = [
        AdvisorAcceptanceObservation(
            case_id="advisor-off",
            receipt=off.receipt,
            expected_status="DISABLED",
        ),
        AdvisorAcceptanceObservation(
            case_id="advisor-replay",
            receipt=replay.receipt,
            expected_status="ACCEPTED",
        ),
        AdvisorAcceptanceObservation(
            case_id="advisor-gated-denied-before-network",
            receipt=gated_denied.receipt,
            expected_status="REJECTED",
        ),
    ]

    candidate = build_experience_candidate(
        candidate_type=ExperienceCandidateType.INVESTIGATION_HINT,
        source_case_ids=[case.case_id],
        proposal=ApprovedMemoryContent(
            pattern="Fixed-coordinate highlight after a recipe revision",
            recommended_first_check="retrieve_current_normal_reference",
            avoid_first_action="declare_root_cause",
            advisory_summary=(
                "Historical reference only; current evidence keeps precedence."
            ),
        ),
        affected_scope=MemoryScope(
            site_id=pack_a.manifest.site_id,
            product_family="metal-part",
            camera_id="CAM-02",
        ),
        required_replay_suite="industrial-incident-bench-v1",
    )
    experience = initialize_experience(candidate, created_at=now)
    experience = record_experience_replay(
        experience,
        replay_suite_sha256=_sha256("industrial-incident-bench-v1-frozen"),
        case_count=15,
        passed_case_count=15,
        deterministic_replay_rate=1.0,
        unsafe_closure_count=0,
        false_root_cause_count=0,
        premature_production_recovery_count=0,
        cross_site_memory_leakage_count=0,
        historical_memory_used_as_fact_count=0,
        evaluated_at=now + timedelta(minutes=1),
    )
    experience = decide_experience_approval(
        experience,
        approve=True,
        actor_user_id="quality-manager-01",
        actor_role=pack_a.output_profile.primary_owner_role,
        note="Approved for shadow only; no production or equipment authority granted.",
        approval_evidence_sha256=_sha256("rc3-human-approval"),
        decided_at=now + timedelta(minutes=2),
    )
    experience = record_experience_shadow(
        experience,
        observed_case_count=3,
        changed_worker_order_count=1,
        unsafe_closure_count=0,
        cross_site_memory_leakage_count=0,
        historical_memory_used_as_fact_count=0,
        observed_at=now + timedelta(minutes=3),
    )
    experience = promote_experience(
        experience,
        promoted_at=now + timedelta(minutes=4),
        actor="quality-governance-owner",
    )
    return evaluate_rc3_component_acceptance(
        site_portability=site_report,
        memory_observations=memory_observations,
        advisor_observations=advisor_observations,
        decision_packets=[decision_packet],
        experience_records=[experience],
    )


__all__ = [
    "AdvisorAcceptanceObservation",
    "MemoryAcceptanceObservation",
    "RC3AcceptanceMetrics",
    "RC3AcceptanceReport",
    "RC3FixedDenominator",
    "build_rc3_reference_acceptance",
    "evaluate_rc3_component_acceptance",
    "verify_rc3_acceptance_report",
]
