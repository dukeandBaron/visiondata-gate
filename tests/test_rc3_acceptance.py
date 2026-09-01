from __future__ import annotations

from pathlib import Path

from visiondata_gate.rc3_acceptance import (
    build_rc3_reference_acceptance,
    verify_rc3_acceptance_report,
)


def test_reference_rc3_acceptance_has_fixed_denominators_and_stays_non_submit() -> None:
    root = Path(__file__).parents[1]
    report = build_rc3_reference_acceptance(root)

    verify_rc3_acceptance_report(report)
    assert report.component_status == "PASS_COMPONENT_CONTRACTS"
    assert report.hard_gate_failures == []
    assert report.denominator.model_dump() == {
        "site_pack_count": 2,
        "memory_query_count": 3,
        "multimodal_mode_case_count": 3,
        "decision_packet_count": 1,
        "experience_candidate_count": 1,
    }
    assert report.metrics.cross_site_memory_leakage_rate == 0.0
    assert report.metrics.historical_memory_used_as_fact_rate == 0.0
    assert report.metrics.real_external_model_call_count == 0
    assert report.metrics.unsafe_decision_packet_count == 0
    assert report.metrics.unsafe_experience_mutation_count == 0
    assert report.full_regression_performed is False
    assert report.clean_extract_reproduction_performed is False
    assert report.real_image_data_integration_status == "VERIFIED_LOCAL_READ_ONLY"
    assert (
        report.real_image_integration_evidence_basis
        == "PRIOR_OPERATOR_AUTHORIZED_LOCAL_OMNI_RUNS"
    )
    assert report.real_image_integration_evidence_sha256 == (
        "17631d2f9fa51e58d8decdb13e4e9ef91f9d2119e2bba344e51db78f5f455098"
    )
    assert report.real_image_integration_verification_sha256 == (
        "38f14dab1a6483aabcb77054b6d4a2e82e7780ae0932a38c0799d7afbc2fb90d"
    )
    assert report.real_image_integration_reexecuted_in_this_protocol is False
    assert report.live_factory_system_connection_status == "NOT_CONNECTED"
    assert report.live_factory_connection_performed is False
    assert report.submission_status == "BLOCKED_UNTIL_FULL_REGRESSION"
