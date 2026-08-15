from __future__ import annotations

import json

import pytest

from visiondata_gate.architecture_benchmark import run_architecture_benchmark
from visiondata_gate.cli import main


def test_same_protocol_benchmark_reports_quality_stability_latency_and_cost(
    tmp_path,
) -> None:
    run = run_architecture_benchmark(
        tmp_path / "architecture_benchmark.json",
        seeds=[20260809],
        repeats=1,
    )

    report = run.report
    assert report["status"] == "PASS"
    assert report["protocol"]["same_inputs"] is True
    assert report["protocol"]["same_tool_implementations"] is True
    assert report["protocol"]["same_policy_judge"] is True
    assert len(report["records"]) == 12
    summaries = report["summaries"]
    assert set(summaries) == {
        "traditional_pipeline",
        "single_agent",
        "multi_agent",
    }
    for summary in summaries.values():
        assert summary["error_release_rate"] == 0.0
        assert summary["task_success_rate"] == 1.0
        assert summary["perturbation_stability_rate"] == 1.0
        assert summary["latency_ms_p95"] >= 0.0
        assert summary["actual_model_cost_cny"] == 0.0
    assert summaries["traditional_pipeline"]["mean_agent_reviews"] == 0.0
    assert summaries["single_agent"]["mean_agent_reviews"] == 1.0
    assert summaries["multi_agent"]["mean_agent_reviews"] == 6.0
    assert (
        report["multi_agent_vs_traditional"][
            "fixed_sop_multi_agent_necessity_supported"
        ]
        is False
    )
    assert run.report_path.is_file()
    assert len(run.report_sha256) == 64


def test_architecture_benchmark_rejects_invalid_protocol_inputs(tmp_path) -> None:
    with pytest.raises(ValueError, match="seeds"):
        run_architecture_benchmark(tmp_path / "bad.json", seeds=[])
    with pytest.raises(ValueError, match="repeats"):
        run_architecture_benchmark(
            tmp_path / "bad-repeat.json",
            seeds=[1],
            repeats=0,
        )


def test_architecture_benchmark_cli(tmp_path, capsys) -> None:
    output = tmp_path / "benchmark.json"
    assert (
        main(
            [
                "architecture-benchmark",
                "--output",
                str(output),
                "--seeds",
                "20260809",
                "--repeats",
                "1",
            ]
        )
        == 0
    )
    payload = json.loads(capsys.readouterr().out)
    assert payload["status"] == "PASS"
    assert payload["report"] == str(output.resolve())
