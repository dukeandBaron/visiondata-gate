from __future__ import annotations

from visiondata_gate.acceptance import _dynamic_metric


def test_dynamic_metric_does_not_infer_an_absent_denominator() -> None:
    metric = _dynamic_metric("dynamic_trigger_precision", "precision", None)

    assert metric.status == "NOT_MEASURED"
    assert metric.value is None


def test_dynamic_metric_accepts_a_bounded_numeric_ratio() -> None:
    metric = _dynamic_metric(
        "dynamic_trigger_precision",
        "precision",
        {"dynamic_trigger_precision": 0.95},
    )

    assert metric.status == "PASS"
    assert metric.value == 0.95


def test_dynamic_metric_rejects_out_of_range_or_string_values() -> None:
    out_of_range = _dynamic_metric(
        "dynamic_trigger_precision",
        "precision",
        {"dynamic_trigger_precision": 1.2},
    )
    numeric_string = _dynamic_metric(
        "dynamic_trigger_precision",
        "precision",
        {"dynamic_trigger_precision": "0.95"},
    )

    assert out_of_range.status == "FAIL"
    assert out_of_range.value is None
    assert numeric_string.status == "FAIL"
    assert numeric_string.value is None
