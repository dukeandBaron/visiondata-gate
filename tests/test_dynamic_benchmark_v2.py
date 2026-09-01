from __future__ import annotations

from copy import deepcopy
import hashlib

import pytest
import rfc8785

from visiondata_gate.dynamic_benchmark_v2 import (
    DynamicBenchmarkV2ValidationError,
    build_worker_selection_benchmark_report,
    validate_worker_selection_benchmark_report,
)


def _rehash(value: object) -> str:
    return hashlib.sha256(rfc8785.dumps(value)).hexdigest()


def test_dynamic_benchmark_v2_has_fixed_288_record_denominator() -> None:
    report = build_worker_selection_benchmark_report()

    assert report["status"] == "PASS"
    assert len(report["fixture_manifest"]) == 24
    assert len(report["records"]) == 288
    assert report["summary"] == {
        "record_count": 288,
        "correct_selection_count": 288,
        "selection_accuracy": 1.0,
        "fixture_count": 24,
        "input_order_invariant_fixture_count": 24,
        "repeat_stable_fixture_count": 24,
        "all_records_correct": True,
        "all_fixtures_input_order_invariant": True,
        "all_fixtures_repeat_stable": True,
    }
    assert report["actual_model_call_count"] == 0
    validate_worker_selection_benchmark_report(report)


def test_dynamic_benchmark_v2_replay_rejects_tampered_record() -> None:
    report = build_worker_selection_benchmark_report()
    tampered = deepcopy(report)
    tampered["records"][0]["selected_worker_ids"] = ["forged-worker"]

    with pytest.raises(
        DynamicBenchmarkV2ValidationError, match="records hash mismatch"
    ):
        validate_worker_selection_benchmark_report(tampered)


def test_dynamic_benchmark_v2_rejects_rehashed_protocol_drift() -> None:
    report = build_worker_selection_benchmark_report()
    tampered = deepcopy(report)
    tampered["protocol"]["fixed_record_count"] = 144
    tampered["protocol_sha256"] = _rehash(tampered["protocol"])

    with pytest.raises(
        DynamicBenchmarkV2ValidationError, match="fixed protocol drifted"
    ):
        validate_worker_selection_benchmark_report(tampered)


def test_dynamic_benchmark_v2_rejects_rehashed_fixture_drift() -> None:
    report = build_worker_selection_benchmark_report()
    tampered = deepcopy(report)
    tampered["fixture_manifest"][0]["rule_under_test"] = "renamed_rule"
    tampered["fixture_manifest_sha256"] = _rehash(tampered["fixture_manifest"])

    with pytest.raises(DynamicBenchmarkV2ValidationError, match="manifest drifted"):
        validate_worker_selection_benchmark_report(tampered)


def test_dynamic_benchmark_v2_rejects_rehashed_record_semantic_drift() -> None:
    report = build_worker_selection_benchmark_report()
    tampered = deepcopy(report)
    record = tampered["records"][0]
    record["rule_under_test"] = "renamed_rule"
    semantic = {
        key: record[key]
        for key in (
            "fixture_id",
            "rule_under_test",
            "input_variant",
            "repeat",
            "selected_worker_ids",
            "expected_selected_worker_ids",
            "selection_receipt_sha256",
            "actual_model_call_count",
        )
    }
    record["semantic_sha256"] = _rehash(semantic)
    tampered["records_sha256"] = _rehash(tampered["records"])

    with pytest.raises(DynamicBenchmarkV2ValidationError, match="deterministic replay"):
        validate_worker_selection_benchmark_report(tampered)


def test_dynamic_benchmark_v2_rejects_benchmark_identity_drift() -> None:
    report = build_worker_selection_benchmark_report()
    report["benchmark_id"] = "DynamicBench-v2-renamed"

    with pytest.raises(DynamicBenchmarkV2ValidationError, match="identity drifted"):
        validate_worker_selection_benchmark_report(report)
