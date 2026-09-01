from visiondata_gate.backend_contract_evaluation import (
    build_backend_contract_evaluation_receipt,
)
from visiondata_gate.network_resilience_evaluation import (
    build_network_resilience_evaluation_receipt,
)
from visiondata_gate.prompt_injection_evaluation import (
    build_prompt_injection_evaluation_receipt,
)


def test_network_resilience_fixed_denominator_passes() -> None:
    receipt = build_network_resilience_evaluation_receipt()
    assert receipt["status"] == "PASS_LOCAL"
    assert receipt["fixed_denominator"] == 4
    assert receipt["passed_count"] == 4
    assert receipt["real_socket_timeout_verified"] is True
    assert receipt["circuit_auto_recovery_verified"] is True


def test_prompt_injection_reports_attack_and_utility_separately() -> None:
    receipt = build_prompt_injection_evaluation_receipt()
    assert receipt["status"] == "PASS_LOCAL_FIXED_ATTACK_SET"
    assert receipt["attack"]["fixed_denominator"] == 12
    assert receipt["attack"]["blocked_count"] == 12
    assert receipt["benign_utility"]["fixed_denominator"] == 6
    assert receipt["benign_utility"]["allowed_count"] == 6
    assert receipt["remote_model_calls_on_blocked_attacks"] == 0


def test_external_backend_contracts_pass_but_real_backends_remain_unconnected() -> None:
    receipt = build_backend_contract_evaluation_receipt()
    assert receipt["status"] == "PASS_LOCAL_CONTRACTS_ONLY"
    assert receipt["fixed_denominator"] == 3
    assert receipt["contract_connected_count"] == 3
    assert receipt["real_backend_connected_count"] == 0
    assert receipt["real_backend_status"] == "REAL_BACKEND_NOT_CONNECTED"
