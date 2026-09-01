from __future__ import annotations

import copy
import hashlib

import pytest

from visiondata_gate.evidence import canonical_json_bytes
from visiondata_gate.memory_governance_benchmark import (
    run_memory_governance_benchmark,
    verify_memory_governance_benchmark,
)


MATRIX_DOMAIN = "visiondata-gate/governance-boundary-contract-matrix/v2"
RECEIPT_V3_DOMAIN = "visiondata-gate/industrial-memory-retrieval/audit/v3"


def _domain_sha256(domain: str, payload: object) -> str:
    return hashlib.sha256(
        domain.encode("utf-8")
        + b"\x00"
        + canonical_json_bytes(payload, trailing_newline=False)
    ).hexdigest()


def _reseal_matrix(payload: dict[str, object]) -> None:
    stable = dict(payload)
    stable.pop("matrix_sha256", None)
    payload["matrix_sha256"] = _domain_sha256(MATRIX_DOMAIN, stable)


def test_governance_boundary_matrix_is_complete_replayable_and_deterministic() -> None:
    first = run_memory_governance_benchmark()
    second = run_memory_governance_benchmark()

    assert first["artifact_name"] == "Governance Boundary Contract Matrix"
    assert first["denominator"] == 40
    assert first["clean_episode_count"] == 20
    assert first["boundary_conflict_episode_count"] == 20
    assert first["baseline"] == {
        "name": "UNGOVERNED_LEXICAL_TOP1_PROXY",
        "correct_top1_count": 20,
        "correct_top1_rate": 0.5,
        "unsafe_selection_count": 20,
        "unsafe_selection_rate": 0.5,
    }
    assert first["governed"] == {
        "name": "GOVERNED_HYBRID_SPARSE_RRF_V3_RECEIPT",
        "correct_top1_count": 40,
        "correct_top1_rate": 1.0,
        "unsafe_selection_count": 0,
        "unsafe_selection_rate": 0.0,
        "boundary_rejection_denominator": 20,
        "correct_boundary_rejection_count": 20,
    }
    assert first["verifier_replays_baseline"] is True
    assert first["verifier_replays_governed"] is True
    assert first["composition_boundary"] == (
        "RETRIEVAL_CONTRACT_ONLY_NOT_PRODUCT_ADMISSION_CHAIN"
    )
    assert first["card_integrity_and_governance_gates_evaluated"] is True
    assert first["strict_memory_admission_chain_evaluated"] is False
    assert first["command_admission_clock_binding_evaluated"] is False
    assert first["semantic_model_evaluated"] is False
    assert first["vector_database_evaluated"] is False
    assert first["real_factory_effectiveness_evaluated"] is False
    assert first["matrix_sha256"] == second["matrix_sha256"]

    episode = first["episodes"][20]
    assert episode["query"]["processing_time_source"]["source_kind"] == (
        "EXPLICIT_CALLER_BINDING"
    )
    assert len(episode["ordered_candidate_cards"]) == 2
    assert episode["truth"]["provenance"] == (
        "AUTHOR_CONSTRUCTED_DETERMINISTIC_PROTOCOL_V2"
    )
    assert episode["baseline_evidence"]["ranked"]
    assert episode["governed_receipt"]["schema_version"] == (
        "visiondata-gate.memory-retrieval-receipt.v3"
    )
    assert episode["governed_receipt"]["memory_admission_status"] == (
        "DIRECT_CALL_NOT_ADMISSION_VERIFIED"
    )
    assert episode["governed_receipt"]["semantic_status"] == "NOT_CONFIGURED"
    verify_memory_governance_benchmark(first)


def test_matrix_rejects_resealed_summary_tampering_after_two_path_replay() -> None:
    tampered = copy.deepcopy(run_memory_governance_benchmark())
    tampered["governed"]["unsafe_selection_count"] = 1
    _reseal_matrix(tampered)

    with pytest.raises(
        ValueError,
        match="absent from executed channels|deterministic two-path replay",
    ):
        verify_memory_governance_benchmark(tampered)


def test_matrix_rejects_fabricated_id_after_receipt_and_matrix_resealing() -> None:
    tampered = copy.deepcopy(run_memory_governance_benchmark())
    row = tampered["episodes"][0]
    fabricated = "memory_ffffffffffffffffffff"

    row["truth"]["expected_memory_id"] = fabricated
    row["baseline_evidence"]["selected_memory_id"] = fabricated
    row["baseline_evidence"]["ranked"][0]["memory_id"] = fabricated
    row["outcome"]["baseline_selected_memory_id"] = fabricated
    row["outcome"]["governed_selected_memory_id"] = fabricated

    receipt = row["governed_receipt"]
    receipt["selected"][0]["memory_id"] = fabricated
    receipt_stable = dict(receipt)
    receipt_stable.pop("receipt_sha256")
    receipt["receipt_sha256"] = _domain_sha256(RECEIPT_V3_DOMAIN, receipt_stable)
    _reseal_matrix(tampered)

    with pytest.raises(
        ValueError,
        match="absent from executed channels|deterministic two-path replay",
    ):
        verify_memory_governance_benchmark(tampered)
