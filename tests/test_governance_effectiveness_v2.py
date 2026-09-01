from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

import visiondata_gate.governance_effectiveness_v2 as governance_module
from visiondata_gate.dynamic_benchmark import run_dynamic_benchmark
from visiondata_gate.governance_effectiveness_v2 import (
    CreateGovernanceEffectivenessV2Request,
    CreatePairedStrategyComparisonV2Request,
    GovernanceDecisionUnitV2,
    GovernanceRemediationUnitV2,
    GovernanceStrategyObservationV2,
    GovernanceTruthBindingV2,
    PairedGovernanceEpisodeV2,
    PairedStrategyComparisonV2Report,
    build_governance_effectiveness_v2_report,
    build_omni_rc3_governance_effectiveness_report,
    build_paired_comparison_from_dynamic_benchmark,
    build_paired_strategy_comparison_v2_report,
    verify_governance_effectiveness_v2_report,
    verify_paired_strategy_comparison_v2_report,
)


def _sha(character: str) -> str:
    return character * 64


def _observation(
    disposition: str,
    *,
    strategy: str = "DYNAMIC_EVIDENCE_AGENT",
) -> GovernanceStrategyObservationV2:
    return GovernanceStrategyObservationV2(
        strategy=strategy,
        system_disposition=disposition,
        decision_receipt_sha256=_sha("a"),
        trace_receipt_sha256=_sha("b"),
        replan_triggered=False,
        replan_count=0,
        selected_worker_count=0,
        selected_worker_ids=[],
        worker_selection_evidence_status="NOT_APPLICABLE",
        detected_evidence_gap_ids=[],
        covered_required_gap_ids=[],
        unresolved_required_gap_ids=[],
        tool_call_count=2,
        redundant_tool_call_count=0,
        latency_ms=1.5,
        actual_model_call_count=0,
        actual_model_token_count=0,
        provider_billed_api_cost_cny=0.0,
    )


def _decision_unit(
    unit_id: str,
    *,
    truth: str | None,
    observed: str,
) -> GovernanceDecisionUnitV2:
    truth_binding = (
        GovernanceTruthBindingV2(
            status="PENDING_ADJUDICATION",
            pending_reason="Independent quality-owner disposition is not yet available.",
        )
        if truth is None
        else GovernanceTruthBindingV2(
            status="ADJUDICATED",
            disposition=truth,
            method="DUAL_HUMAN_ADJUDICATION",
            adjudication_receipt_sha256=_sha("c"),
        )
    )
    return GovernanceDecisionUnitV2(
        unit_id=unit_id,
        source_scope="PRIVATE_AUTHORIZED_SHADOW",
        input_contract_sha256=_sha("d"),
        input_manifest_sha256=_sha("e"),
        truth=truth_binding,
        required_evidence_gap_ids=[],
        conflict_tags=[],
        complex_conflict=False,
        observation=_observation(observed),
    )


def _remediation(
    remediation_id: str,
    outcome: str,
) -> GovernanceRemediationUnitV2:
    completed = outcome != "PENDING_RECHECK"
    return GovernanceRemediationUnitV2(
        remediation_id=remediation_id,
        source_scope="PRIVATE_AUTHORIZED_SHADOW",
        parent_unit_id="case-parent",
        verification_contract_sha256=_sha("1"),
        parent_decision_receipt_sha256=_sha("2"),
        child_decision_receipt_sha256=_sha("3") if completed else None,
        lineage_receipt_sha256=_sha("4") if completed else None,
        named_approval_binding_sha256=_sha("5") if completed else None,
        outcome=outcome,
        independent_recheck_performed=completed,
    )


def _private_request(
    *,
    decision_units: list[GovernanceDecisionUnitV2],
    remediation_units: list[GovernanceRemediationUnitV2],
    note: str = "Authorized per-case shadow evaluation with external labels.",
) -> CreateGovernanceEffectivenessV2Request:
    return CreateGovernanceEffectivenessV2Request(
        evaluation_id="private-shadow-v2",
        source_scope="PRIVATE_AUTHORIZED_SHADOW",
        evaluated_strategy="DYNAMIC_EVIDENCE_AGENT",
        dataset_identity_sha256=_sha("6"),
        source_authorization_binding_sha256=_sha("7"),
        decision_units=decision_units,
        remediation_units=remediation_units,
        evaluated_at="2026-08-29T03:00:00+08:00",
        note=note,
        operator_attests_authorized_use=True,
    )


def _public_proxy_unit(*, truth_method: str) -> GovernanceDecisionUnitV2:
    observation = _observation("BLOCKED")
    observation = GovernanceStrategyObservationV2(
        **(
            observation.model_dump()
            | {
                "detected_evidence_gap_ids": ["mask-image-pairing"],
                "covered_required_gap_ids": ["mask-image-pairing"],
            }
        )
    )
    return GovernanceDecisionUnitV2(
        unit_id="visa-pcb-injection-001",
        source_scope=("PUBLIC_INDUSTRIAL_PROXY_WITH_PROGRAMMATIC_GOVERNANCE_TRUTH"),
        input_contract_sha256=_sha("8"),
        input_manifest_sha256=_sha("9"),
        truth=GovernanceTruthBindingV2(
            status="ADJUDICATED",
            disposition="BLOCK_REQUIRED",
            method=truth_method,
            adjudication_receipt_sha256=_sha("c"),
        ),
        required_evidence_gap_ids=["mask-image-pairing"],
        conflict_tags=[],
        complex_conflict=False,
        observation=observation,
    )


@pytest.mark.tier_core
def test_public_industrial_proxy_requires_license_binding_and_injection_truth() -> None:
    common = {
        "evaluation_id": "public-governancebench-v1",
        "source_scope": ("PUBLIC_INDUSTRIAL_PROXY_WITH_PROGRAMMATIC_GOVERNANCE_TRUTH"),
        "evaluated_strategy": "DYNAMIC_EVIDENCE_AGENT",
        "dataset_identity_sha256": _sha("6"),
        "source_authorization_binding_sha256": _sha("7"),
        "decision_units": [
            _public_proxy_unit(truth_method="FROZEN_PROGRAMMATIC_GOVERNANCE_INJECTION")
        ],
        "remediation_units": [],
        "evaluated_at": "2026-08-29T03:00:00+08:00",
        "note": (
            "VisA product labels remain source annotations; the frozen injection "
            "manifest supplies only batch-governance proxy truth."
        ),
        "operator_attests_authorized_use": True,
    }

    request = CreateGovernanceEffectivenessV2Request(**common)
    report = build_governance_effectiveness_v2_report(request)
    verify_governance_effectiveness_v2_report(report)
    assert request.source_scope == (
        "PUBLIC_INDUSTRIAL_PROXY_WITH_PROGRAMMATIC_GOVERNANCE_TRUTH"
    )
    assert report.false_release_rate.value == 0.0

    with pytest.raises(ValueError, match="license and attribution binding"):
        CreateGovernanceEffectivenessV2Request(
            **(common | {"source_authorization_binding_sha256": None})
        )

    with pytest.raises(ValueError, match="frozen programmatic governance injection"):
        CreateGovernanceEffectivenessV2Request(
            **(
                common
                | {
                    "decision_units": [
                        _public_proxy_unit(truth_method="DUAL_HUMAN_ADJUDICATION")
                    ]
                }
            )
        )


@pytest.mark.tier_core
def test_v2_derives_confusion_and_remediation_metrics_from_units() -> None:
    request = _private_request(
        decision_units=[
            _decision_unit(
                "case-block-false-release",
                truth="BLOCK_REQUIRED",
                observed="RELEASED",
            ),
            _decision_unit(
                "case-block-true-block",
                truth="BLOCK_REQUIRED",
                observed="BLOCKED",
            ),
            _decision_unit(
                "case-release-true-release",
                truth="RELEASE_ALLOWED",
                observed="RELEASED",
            ),
            _decision_unit(
                "case-release-false-block",
                truth="RELEASE_ALLOWED",
                observed="HUMAN_REVIEW",
            ),
        ],
        remediation_units=[
            _remediation("remediation-pass", "VERIFIED_PASS"),
            _remediation("remediation-fail", "VERIFIED_FAIL"),
            _remediation("remediation-pending", "PENDING_RECHECK"),
        ],
    )

    report = build_governance_effectiveness_v2_report(request)

    assert report.measurement_status == "MEASURED"
    assert report.confusion == {
        "true_block_count": 1,
        "false_release_count": 1,
        "true_release_count": 1,
        "false_block_count": 1,
    }
    assert report.false_release_rate.value == 0.5
    assert report.false_block_rate.value == 0.5
    assert report.verified_remediation_pass_rate.value == 0.5
    assert report.pending_remediation_rate.value == pytest.approx(1 / 3)
    assert report.adjudication_coverage_rate.value == 1.0
    assert report.false_release_rate.wilson_95_lower is not None
    assert report.false_release_rate.wilson_95_upper is not None
    verify_governance_effectiveness_v2_report(report)

    tampered = report.model_copy(
        update={"confusion": {**report.confusion, "false_release_count": 0}}
    )
    with pytest.raises(ValueError, match="digest mismatch"):
        verify_governance_effectiveness_v2_report(tampered)


@pytest.mark.tier_core
def test_v2_keeps_missing_truth_not_measured() -> None:
    report = build_governance_effectiveness_v2_report(
        _private_request(
            decision_units=[
                _decision_unit(
                    "case-pending-truth",
                    truth=None,
                    observed="BLOCKED",
                )
            ],
            remediation_units=[],
        )
    )

    assert report.measurement_status == "NOT_MEASURED"
    assert report.adjudicated_decision_unit_count == 0
    assert report.pending_adjudication_count == 1
    assert report.false_release_rate.status == "NOT_MEASURED_PENDING_ADJUDICATION"
    assert report.false_block_rate.status == "NOT_MEASURED_PENDING_ADJUDICATION"
    assert report.verified_remediation_pass_rate.status == "NOT_MEASURED"
    assert report.adjudication_coverage_rate.value == 0.0


@pytest.mark.tier_core
def test_v2_rejects_duplicate_units_and_host_paths() -> None:
    duplicated = _decision_unit(
        "case-duplicate",
        truth="BLOCK_REQUIRED",
        observed="BLOCKED",
    )
    with pytest.raises(ValueError, match="unit IDs must be unique"):
        _private_request(
            decision_units=[duplicated, duplicated],
            remediation_units=[],
        )

    with pytest.raises(ValueError, match="host path"):
        _private_request(
            decision_units=[duplicated],
            remediation_units=[],
            note="Evidence was loaded from E:\\private\\factory and reviewed.",
        )


@pytest.mark.tier_core
def test_dynamic_bench_translates_to_same_input_complex_conflict_pairs(
    tmp_path: Path,
) -> None:
    run = run_dynamic_benchmark(tmp_path / "dynamic.json", repeats=1)

    report = build_paired_comparison_from_dynamic_benchmark(
        run.report_path,
        evaluated_at="2026-08-29T03:00:00+08:00",
        baseline_architecture="traditional_pipeline",
    )

    assert report.request.source_scope == "SYNTHETIC_FIXED_FIXTURE"
    assert len(report.request.episodes) == 24
    assert report.complex_conflict_episode_count == 4
    assert report.complex_fixed.confusion["false_release_count"] == 4
    assert report.complex_dynamic.confusion["false_release_count"] == 0
    assert report.complex_fixed.evidence_gap_coverage_rate.value == 0.0
    assert report.complex_dynamic.evidence_gap_coverage_rate.value == 1.0
    assert report.complex_conflict_verdict == "DYNAMIC_SAFETY_ADVANTAGE"
    assert report.external_competitor_system_executed is False
    assert all(
        item.fixed_observation.decision_receipt_sha256
        != item.dynamic_observation.decision_receipt_sha256
        or item.fixed_observation.system_disposition
        == item.dynamic_observation.system_disposition
        for item in report.request.episodes
    )
    verify_paired_strategy_comparison_v2_report(report)

    tampered = report.model_copy(
        update={"complex_conflict_verdict": "NO_MEASURED_ADVANTAGE"}
    )
    with pytest.raises(ValueError, match="digest mismatch"):
        verify_paired_strategy_comparison_v2_report(tampered)

    exhaustive = build_paired_comparison_from_dynamic_benchmark(
        run.report_path,
        evaluated_at="2026-08-29T03:00:00+08:00",
        baseline_architecture="fixed_multi_agent",
    )
    assert exhaustive.request.baseline_strategy == "FIXED_EXHAUSTIVE_PIPELINE"
    assert exhaustive.complex_fixed.confusion["false_release_count"] == 0
    assert exhaustive.complex_dynamic.confusion["false_release_count"] == 0
    assert exhaustive.complex_fixed.redundant_tool_call_count == 5
    assert exhaustive.complex_dynamic.redundant_tool_call_count == 0
    assert exhaustive.complex_conflict_verdict == "DYNAMIC_EFFICIENCY_ADVANTAGE"
    verify_paired_strategy_comparison_v2_report(exhaustive)


@pytest.mark.tier_core
def test_paired_verdict_distinguishes_false_block_reduction_from_safety() -> None:
    required = ["complete_required_tool_set", "transient_tool_recovery"]

    def paired_observation(strategy: str, disposition: str):  # type: ignore[no-untyped-def]
        return GovernanceStrategyObservationV2(
            **(
                _observation(disposition, strategy=strategy).model_dump()
                | {
                    "detected_evidence_gap_ids": required,
                    "covered_required_gap_ids": required,
                    "unresolved_required_gap_ids": [],
                }
            )
        )

    episode = PairedGovernanceEpisodeV2(
        episode_id="paired-false-block-reduction",
        source_scope="SYNTHETIC_FIXED_FIXTURE",
        input_contract_sha256=_sha("1"),
        input_manifest_sha256=_sha("2"),
        truth=GovernanceTruthBindingV2(
            status="ADJUDICATED",
            disposition="RELEASE_ALLOWED",
            method="FROZEN_SYNTHETIC_FIXTURE",
            adjudication_receipt_sha256=_sha("3"),
        ),
        required_evidence_gap_ids=required,
        conflict_tags=["runtime_tool_fault"],
        complex_conflict=True,
        fixed_observation=paired_observation("FIXED_RULE_PIPELINE", "HUMAN_REVIEW"),
        dynamic_observation=paired_observation("DYNAMIC_EVIDENCE_AGENT", "RELEASED"),
    )
    request = CreatePairedStrategyComparisonV2Request(
        comparison_id="paired-false-block-reduction",
        source_scope="SYNTHETIC_FIXED_FIXTURE",
        baseline_strategy="FIXED_RULE_PIPELINE",
        dataset_identity_sha256=_sha("4"),
        source_benchmark_sha256=_sha("5"),
        episodes=[episode],
        evaluated_at="2026-08-29T03:00:00+08:00",
        note="Frozen pair isolates equal false release and lower false block.",
    )
    report = build_paired_strategy_comparison_v2_report(request)

    assert report.complex_fixed.confusion["false_release_count"] == 0
    assert report.complex_dynamic.confusion["false_release_count"] == 0
    assert report.complex_fixed.confusion["false_block_count"] == 1
    assert report.complex_dynamic.confusion["false_block_count"] == 0
    assert report.complex_conflict_verdict == "DYNAMIC_FALSE_BLOCK_REDUCTION"
    verify_paired_strategy_comparison_v2_report(report)

    legacy_stable = report.model_dump(mode="json", exclude={"report_sha256"})
    legacy_stable["complex_conflict_verdict"] = "NO_MEASURED_ADVANTAGE"
    legacy = PairedStrategyComparisonV2Report(
        **legacy_stable,
        report_sha256=governance_module._domain_sha256("paired-report", legacy_stable),
    )
    with pytest.raises(ValueError, match="deterministic replay"):
        verify_paired_strategy_comparison_v2_report(legacy)
    verify_paired_strategy_comparison_v2_report(
        legacy, allow_legacy_false_block_verdict=True
    )


@pytest.mark.tier_core
def test_paired_report_model_rejects_invalid_digest_shape() -> None:
    with pytest.raises(ValueError):
        PairedStrategyComparisonV2Report.model_validate(
            {
                "schema_version": "visiondata-gate.paired-strategy-comparison.v2",
                "report_sha256": "not-a-digest",
            }
        )


@pytest.mark.tier_core
def test_omni_rc3_counts_child_recheck_but_not_missing_disposition_truth(
    tmp_path: Path,
) -> None:
    product = {
        "schema_version": "visiondata-gate.authorized-product-pilot.v2",
        "task_id": "tsk_private",
        "evidence_sha256": _sha("a"),
        "plan_sha256": _sha("b"),
        "source_profile_sha256": _sha("c"),
        "source_registry_sha256": _sha("d"),
        "final_decision": "RECAPTURE",
        "replan_count": 1,
        "dynamic_task_count": 3,
        "tool_trace_count": 8,
        "source_path_serialized": False,
        "source_assets_copied_into_product": False,
    }
    capa = {
        "schema_version": "visiondata-gate.authorized-capa-pilot.v1",
        "parent_task_id": "tsk_private",
        "parent_evidence_sha256": _sha("a"),
        "completion_state": "CAPA_CHILD_RUN_COMPLETED",
        "child_evidence_sha256": _sha("e"),
        "lineage_report_sha256": _sha("f"),
        "capa_approval_binding_sha256": _sha("1"),
        "parent_immutable": True,
        "parent_source_mutated": False,
        "production_release_allowed": False,
        "actual_model_call_count": 0,
        "recovery_success": False,
    }
    product_path = tmp_path / "authorized_product_pilot_receipt.json"
    capa_path = tmp_path / "authorized_capa_pilot_receipt.json"
    product_path.write_text(json.dumps(product), encoding="utf-8")
    capa_path.write_text(json.dumps(capa), encoding="utf-8")
    product_sha = hashlib.sha256(product_path.read_bytes()).hexdigest()
    capa_sha = hashlib.sha256(capa_path.read_bytes()).hexdigest()

    report = build_omni_rc3_governance_effectiveness_report(
        product_pilot_receipt_path=product_path,
        capa_pilot_receipt_path=capa_path,
        expected_product_receipt_sha256=product_sha,
        expected_capa_receipt_sha256=capa_sha,
        evaluated_at="2026-08-29T03:00:00+08:00",
    )

    assert report.measurement_status == "PARTIAL_MEASUREMENT"
    assert report.false_release_rate.status == "NOT_MEASURED_PENDING_ADJUDICATION"
    assert report.false_block_rate.status == "NOT_MEASURED_PENDING_ADJUDICATION"
    assert report.verified_remediation_pass_rate.status == "MEASURED"
    assert report.verified_remediation_pass_rate.numerator == 0
    assert report.verified_remediation_pass_rate.denominator == 1
    assert report.verified_remediation_pass_rate.value == 0.0
    assert report.pending_adjudication_count == 1
    assert report.request.decision_units[0].observation.selected_worker_count == 3
    verify_governance_effectiveness_v2_report(report)

    with pytest.raises(ValueError, match="product pilot receipt SHA-256 mismatch"):
        build_omni_rc3_governance_effectiveness_report(
            product_pilot_receipt_path=product_path,
            capa_pilot_receipt_path=capa_path,
            expected_product_receipt_sha256=_sha("9"),
            expected_capa_receipt_sha256=capa_sha,
            evaluated_at="2026-08-29T03:00:00+08:00",
        )
