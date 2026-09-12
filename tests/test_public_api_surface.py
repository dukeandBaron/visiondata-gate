from __future__ import annotations

import visiondata_gate
from visiondata_gate import audit_envelope, contracts, evidence, evidence_state
from visiondata_gate import evidence_state_contracts
from visiondata_gate.benchmarks import dynamic_benchmark_v4


def test_cross_module_contract_names_are_explicit_exports() -> None:
    assert "SourceAuthorizationStatusV2" in evidence_state_contracts.__all__
    assert "PRODUCTION_ROUTE" in dynamic_benchmark_v4.__all__
    assert dynamic_benchmark_v4.PRODUCTION_ROUTE == (
        "ProductService.run_task_sync->"
        "ProductService.create_industrial_incident_case->"
        "IncidentKernelV6"
    )


def test_documented_package_and_json_boundaries_remain_exact() -> None:
    assert visiondata_gate.__all__ == ["GateDecision"]
    assert visiondata_gate.GateDecision is contracts.GateDecision
    assert evidence_state.EvidenceBeliefLedgerV2 is (
        evidence_state_contracts.EvidenceBeliefLedgerV2
    )
    assert evidence.canonical_json_bytes({"a": 1}) == b'{"a":1}\n'
    assert audit_envelope.canonical_jcs_bytes({"a": 1}) == b'{"a":1}'
