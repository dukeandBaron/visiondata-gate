from __future__ import annotations

import json
from pathlib import Path

import pytest

import tools.check_bandit_baseline as bandit_baseline


def _finding(
    *,
    path: str = "src\\visiondata_gate\\example.py",
    severity: str = "LOW",
    line_number: int = 7,
) -> dict[str, object]:
    return {
        "code": "6 try:\n7     pass\n",
        "col_offset": 4,
        "end_col_offset": 8,
        "filename": path,
        "issue_confidence": "HIGH",
        "issue_cwe": {"id": 703, "link": "https://cwe.mitre.org/data/definitions/703.html"},
        "issue_severity": severity,
        "issue_text": "Try, Except, Pass detected.",
        "line_number": line_number,
        "line_range": [line_number],
        "more_info": "https://bandit.readthedocs.io/",
        "test_id": "B110",
        "test_name": "try_except_pass",
    }


def _report(*findings: dict[str, object]) -> dict[str, object]:
    return {
        "errors": [],
        "generated_at": "2026-09-14T00:00:00Z",
        "metrics": {"_totals": {"SEVERITY.LOW": len(findings)}},
        "results": list(findings),
    }


def test_baseline_is_cross_platform_and_allows_line_only_drift() -> None:
    baseline = bandit_baseline.build_baseline(
        _report(_finding()),
        bandit_version="1.9.4",
    )
    current = _report(
        _finding(path="src/visiondata_gate/example.py", line_number=99)
    )

    result = bandit_baseline.compare_report_to_baseline(
        current,
        baseline,
        bandit_version="1.9.4",
    )

    assert result["status"] == "PASS_NO_NEW_BANDIT_FINDINGS"
    assert result["baseline_low"] == 1
    assert result["current_low"] == 1
    assert baseline["results"][0]["filename"] == (
        "src/visiondata_gate/example.py"
    )


def test_baseline_rejects_any_new_low_finding() -> None:
    baseline = bandit_baseline.build_baseline(
        _report(_finding()),
        bandit_version="1.9.4",
    )
    current = _report(
        _finding(),
        _finding(path="tools/new_debt.py"),
    )

    with pytest.raises(
        bandit_baseline.BaselineError,
        match="NEW_BANDIT_FINDINGS",
    ):
        bandit_baseline.compare_report_to_baseline(
            current,
            baseline,
            bandit_version="1.9.4",
        )


def test_baseline_rejects_current_or_frozen_medium() -> None:
    medium = _finding(severity="MEDIUM")
    with pytest.raises(bandit_baseline.BaselineError, match="BASELINE_NOT_LOW_ONLY"):
        bandit_baseline.build_baseline(
            _report(medium),
            bandit_version="1.9.4",
        )

    baseline = bandit_baseline.build_baseline(
        _report(_finding()),
        bandit_version="1.9.4",
    )
    with pytest.raises(
        bandit_baseline.BaselineError,
        match="CURRENT_MEDIUM_OR_HIGH_FINDING",
    ):
        bandit_baseline.compare_report_to_baseline(
            _report(medium),
            baseline,
            bandit_version="1.9.4",
        )


def test_baseline_detects_manifest_tampering() -> None:
    baseline = bandit_baseline.build_baseline(
        _report(_finding()),
        bandit_version="1.9.4",
    )
    baseline["results"][0]["issue_text"] = "changed"

    with pytest.raises(bandit_baseline.BaselineError, match="BASELINE_SHA256_MISMATCH"):
        bandit_baseline.compare_report_to_baseline(
            _report(),
            baseline,
            bandit_version="1.9.4",
        )


def test_same_rule_and_count_cannot_hide_replaced_code() -> None:
    baseline = bandit_baseline.build_baseline(
        _report(_finding()), bandit_version="1.9.4"
    )
    changed = _finding()
    changed["code"] = "6 try:\n7     run_new_command()\n"
    with pytest.raises(bandit_baseline.BaselineError, match="NEW_BANDIT_FINDINGS"):
        bandit_baseline.compare_report_to_baseline(
            _report(changed), baseline, bandit_version="1.9.4"
        )


def test_code_fingerprint_ignores_report_line_numbers_only() -> None:
    baseline = bandit_baseline.build_baseline(
        _report(_finding()), bandit_version="1.9.4"
    )
    shifted = _finding(line_number=107)
    shifted["code"] = "106 try:\n107     pass\n"
    result = bandit_baseline.compare_report_to_baseline(
        _report(shifted), baseline, bandit_version="1.9.4"
    )
    assert result["status"] == "PASS_NO_NEW_BANDIT_FINDINGS"


def test_cli_writes_normalized_auditable_baseline(tmp_path: Path) -> None:
    report = tmp_path / "bandit.json"
    baseline = tmp_path / "baseline.json"
    report.write_text(json.dumps(_report(_finding())), encoding="utf-8")

    assert (
        bandit_baseline.main(
            [
                "freeze",
                "--report",
                str(report),
                "--baseline",
                str(baseline),
                "--bandit-version",
                "1.9.4",
            ]
        )
        == 0
    )
    stored = json.loads(baseline.read_text(encoding="utf-8"))
    assert stored["baseline_schema_version"] == (
        "visiondata-gate.bandit-baseline.v1"
    )
    assert stored["bandit_version"] == "1.9.4"
    assert stored["policy"]["new_low_allowed"] is False
    assert len(stored["findings_sha256"]) == 64
