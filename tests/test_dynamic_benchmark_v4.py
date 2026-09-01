from __future__ import annotations

from copy import deepcopy
import json
from pathlib import Path

import pytest

from visiondata_gate.benchmarks.dynamic_benchmark_v4 import (
    BENCHMARK_ID,
    DynamicBenchmarkV4ValidationError,
    build_dynamic_benchmark_v4_fixtures,
    build_dynamic_benchmark_v4_report,
    load_dynamic_benchmark_v4_report,
    validate_dynamic_benchmark_v4_report,
)
from visiondata_gate.evidence import canonical_json_bytes


PROJECT_ROOT = Path(__file__).resolve().parents[1]
V3_REPORT = PROJECT_ROOT / "10_reports" / "DYNAMICBENCH_V3_REPLANNING_20260829.json"


@pytest.fixture(scope="module")
def v4_report(tmp_path_factory: pytest.TempPathFactory) -> dict[str, object]:
    return build_dynamic_benchmark_v4_report(
        scratch_root=tmp_path_factory.mktemp("dynamicbench-v4-product-state"),
        v3_report_path=V3_REPORT,
    )


def test_v4_executes_real_product_service_incident_v6_grid(
    v4_report: dict[str, object],
) -> None:
    report = v4_report
    records = report["records"]
    metrics = report["metrics"]

    assert report["benchmark_id"] == BENCHMARK_ID
    assert report["status"] == "PASS"
    assert metrics == {
        "fixed_fixture_denominator": 4,
        "product_service_execution_count": 4,
        "passed_count": 4,
        "incident_v6_count": 4,
        "decision_packet_v3_count": 4,
        "tool_failure_fixture_count": 1,
        "tool_failure_recovered_fail_closed_count": 1,
        "unsafe_production_release_count": 0,
        "actual_external_model_call_count": 0,
    }
    assert [item["fixture_id"] for item in records] == ["P01", "P02", "P03", "P04"]
    assert all(item["passed"] for item in records)
    assert all(item["truth_delivery_to_runtime"] is False for item in records)
    assert all(
        item["production_route"].startswith("ProductService.run_task_sync")
        for item in records
    )
    assert records[2]["failed_worker_roles"] == ["EvidenceQualificationAgent"]
    assert records[2]["case_status"] == "EVIDENCE_INCOMPLETE"
    assert "WORKER_EXECUTION_FAILED" in records[2]["issue_codes"]
    assert "EVIDENCE_NOT_EVALUATED_DUE_TO_BUDGET" in records[3]["issue_codes"]


def test_v4_manifest_keeps_truth_outside_runtime_request() -> None:
    fixtures = build_dynamic_benchmark_v4_fixtures()

    assert len(fixtures) == 4
    assert len({item["fixture_id"] for item in fixtures}) == 4
    assert all("expected" in item for item in fixtures)
    assert all("runtime_request" not in item for item in fixtures)


def test_v4_loader_and_hash_validation_are_fail_closed(
    tmp_path: Path,
    v4_report: dict[str, object],
) -> None:
    output = tmp_path / "dynamicbench-v4.json"
    output.write_bytes(canonical_json_bytes(v4_report) + b"\n")

    loaded = load_dynamic_benchmark_v4_report(output)
    assert loaded["sealed_report_sha256"] == v4_report["sealed_report_sha256"]

    tampered = deepcopy(v4_report)
    tampered["records"][0]["case_status"] = "READY_FOR_HUMAN_DECISION"
    with pytest.raises(DynamicBenchmarkV4ValidationError, match="digest mismatch"):
        validate_dynamic_benchmark_v4_report(tampered)

    payload = json.loads(output.read_text(encoding="utf-8"))
    payload["unexpected"] = True
    output.write_text(json.dumps(payload), encoding="utf-8")
    with pytest.raises(DynamicBenchmarkV4ValidationError, match="digest mismatch"):
        load_dynamic_benchmark_v4_report(output)
