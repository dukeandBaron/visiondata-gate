from __future__ import annotations

import json

from visiondata_gate.agent_runtime import run_agentic_demo
from visiondata_gate.proof import build_observability_summary, build_reviewer_readiness
from visiondata_gate.runtime_models import RuntimeConfig


def test_proof_index_and_observability_are_trace_bound(tmp_path) -> None:
    run = run_agentic_demo(
        tmp_path / "run",
        seed=20260812,
        config=RuntimeConfig(),
        memory_path=tmp_path / "memory.json",
    )
    evidence = run.evidence_dir
    proof_path = evidence / "proof_index.json"
    observability_path = evidence / "observability_summary.json"
    readiness_path = evidence / "reviewer_readiness.json"
    claim_scope_path = evidence / "claim_scope_receipt.json"
    assert proof_path.is_file()
    assert observability_path.is_file()
    assert readiness_path.is_file()
    assert claim_scope_path.is_file()

    proof = json.loads(proof_path.read_text(encoding="utf-8"))
    observability = json.loads(observability_path.read_text(encoding="utf-8"))
    readiness = json.loads(readiness_path.read_text(encoding="utf-8"))
    claim_scope = json.loads(claim_scope_path.read_text(encoding="utf-8"))
    assert proof["schema_version"] == "visiondata-gate.proof-index.v1"
    assert proof["decision_chain"] == ["RECAPTURE", "PASS"]
    assert proof["integrity"]["all_declared_artifacts_present"] is True
    assert {claim["support_level"] for claim in proof["claims"]} >= {
        "verified_local",
        "explicit_limitation",
    }
    assert observability["health_checks"]["event_sequence_contiguous"] is True
    assert observability["health_checks"]["all_events_have_agentteams_binding"] is True
    assert observability["channels"]["otel_collector"] == "not_connected"
    assert build_observability_summary(run.runtime_trace) == observability
    assert readiness["schema_version"] == "visiondata-gate.reviewer-readiness.v1"
    assert len(readiness["dimensions"]) == 5
    assert readiness["status_counts"]["PARTIAL"] >= 1
    assert readiness["status_counts"]["OPEN"] >= 1
    assert (
        build_reviewer_readiness(
            run.runtime_trace,
            run.initial_result,
            run.repaired_result,
            run.evaluation,
        )
        == readiness
    )
    readiness_claim = next(
        claim
        for claim in proof["claims"]
        if claim["claim_id"] == "reviewer_readiness_matrix"
    )
    assert readiness_claim["support_level"] == "reviewer_navigation"
    assert any(
        item["path"].endswith("evidence/reviewer_readiness.json")
        for item in proof["artifact_index"]
    )
    assert any(
        item["path"].endswith("evidence/tool_ablation_receipt.json")
        for item in proof["artifact_index"]
    )
    assert any(
        item["path"].endswith("evidence/skill_qualification_receipt.json")
        for item in proof["artifact_index"]
    )
    claim_ids = {claim["claim_id"] for claim in proof["claims"]}
    assert "tool_ablation_necessity" in claim_ids
    assert "runtime_skill_qualification" in claim_ids
    assert claim_scope["schema_version"] == "visiondata-gate.claim-scope-receipt.v1"
    prohibited = {item["claim_id"]: item for item in claim_scope["prohibited_claims"]}
    assert prohibited["hosted_agentteams_connected"]["observed"] is False
    assert prohibited["real_customer_validation"]["observed"] is False
    assert prohibited["real_industrial_data"]["observed"] is False
    assert prohibited["production_deployment"]["observed"] is False
    assert prohibited["official_submission_receipt"]["observed"] is False
    assert prohibited["visual_replay_reviewed"]["status"] == "NOT_APPLICABLE_NO_VIDEO"
