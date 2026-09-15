import pytest
from examples.reuse.metadata_skill import run_example


@pytest.mark.parametrize("first,second,delta", [(12, 14, 2), (12, 12, 0), (20, 12, 8)])
def test_example_executes_real_sdk_with_changed_input(first, second, delta):
    receipt = run_example(first, second)
    assert receipt.outcome.status == "OK"
    decision = receipt.outcome.observations[0].decision
    assert decision.observed_value == delta
    assert decision.is_anomaly is (delta > 0)
    assert receipt.outcome.actual_model_call_count == 0
    assert receipt.outcome.network_call_count == 0


@pytest.mark.parametrize("value", [-1, True, 1.2, 1_000_001])
def test_example_rejects_invalid_count(value):
    with pytest.raises(ValueError):
        run_example(value, 12)
