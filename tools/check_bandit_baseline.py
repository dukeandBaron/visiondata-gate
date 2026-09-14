#!/usr/bin/env python3
"""Freeze and enforce a cross-platform, low-severity-only Bandit baseline."""

from __future__ import annotations

import argparse
from collections import Counter
import hashlib
import json
from pathlib import Path
import re
from typing import Any


BASELINE_SCHEMA_VERSION = "visiondata-gate.bandit-baseline.v1"
MAX_REPORT_BYTES = 64 * 1024 * 1024
STABLE_IDENTITY_FIELDS = (
    "filename",
    "issue_confidence",
    "issue_cwe",
    "issue_severity",
    "issue_text",
    "test_id",
    "test_name",
)


class BaselineError(RuntimeError):
    """The scanner report or frozen baseline violates the security policy."""


def _canonical_json(value: object) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")


def _normalize_finding(value: object) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise BaselineError("BANDIT_FINDING_INVALID")
    finding = dict(value)
    filename = finding.get("filename")
    if not isinstance(filename, str) or not filename.strip():
        raise BaselineError("BANDIT_FINDING_PATH_INVALID")
    finding["filename"] = filename.replace("\\", "/")
    for field in (
        "issue_confidence",
        "issue_severity",
        "issue_text",
        "test_id",
        "test_name",
    ):
        if not isinstance(finding.get(field), str):
            raise BaselineError("BANDIT_FINDING_FIELD_INVALID")
    cwe = finding.get("issue_cwe")
    if not isinstance(cwe, dict) or not isinstance(cwe.get("id"), int):
        raise BaselineError("BANDIT_FINDING_CWE_INVALID")
    return finding


def _normalized_results(report: dict[str, Any]) -> list[dict[str, Any]]:
    errors = report.get("errors")
    if not isinstance(errors, list) or errors:
        raise BaselineError("BANDIT_SCAN_ERRORS_PRESENT")
    raw_results = report.get("results")
    if not isinstance(raw_results, list):
        raise BaselineError("BANDIT_RESULTS_INVALID")
    return [_normalize_finding(item) for item in raw_results]


def _stable_fingerprint(finding: dict[str, Any]) -> str:
    identity = {field: finding[field] for field in STABLE_IDENTITY_FIELDS}
    code = finding.get("code")
    if not isinstance(code, str) or not code.strip():
        raise BaselineError("BANDIT_CODE_EVIDENCE_MISSING")
    # Remove only Bandit's numeric line prefixes; preserve actual source bytes.
    identity["code"] = "\n".join(
        re.sub(r"^\d+[ \t]", "", line) for line in code.splitlines()
    )
    return hashlib.sha256(_canonical_json(identity)).hexdigest()


def _results_sha256(results: list[dict[str, Any]]) -> str:
    return hashlib.sha256(_canonical_json(results)).hexdigest()


def build_baseline(
    report: dict[str, Any],
    *,
    bandit_version: str,
) -> dict[str, Any]:
    results = _normalized_results(report)
    if any(item["issue_severity"] != "LOW" for item in results):
        raise BaselineError("BASELINE_NOT_LOW_ONLY")
    results.sort(
        key=lambda item: (
            _stable_fingerprint(item),
            int(item.get("line_number", 0)),
        )
    )
    return {
        "baseline_schema_version": BASELINE_SCHEMA_VERSION,
        "bandit_version": bandit_version,
        "errors": [],
        "findings_sha256": _results_sha256(results),
        "generated_at": report.get("generated_at"),
        "metrics": report.get("metrics", {}),
        "policy": {
            "allowed_existing_severity": "LOW",
            "current_medium_or_high_allowed": False,
            "new_low_allowed": False,
            "resolved_findings_may_be_removed": True,
            "stable_identity_fields": list(STABLE_IDENTITY_FIELDS),
            "code_fingerprint": "SOURCE_SNIPPET_EXCLUDING_REPORT_LINE_NUMBERS",
        },
        "results": results,
        "scan_roots": ["src", "desktop", "tools"],
    }


def _validate_baseline(
    baseline: dict[str, Any],
    *,
    bandit_version: str,
) -> list[dict[str, Any]]:
    if baseline.get("baseline_schema_version") != BASELINE_SCHEMA_VERSION:
        raise BaselineError("BASELINE_SCHEMA_INVALID")
    if baseline.get("bandit_version") != bandit_version:
        raise BaselineError("BASELINE_BANDIT_VERSION_MISMATCH")
    policy = baseline.get("policy")
    if not (
        isinstance(policy, dict)
        and policy.get("allowed_existing_severity") == "LOW"
        and policy.get("current_medium_or_high_allowed") is False
        and policy.get("new_low_allowed") is False
        and policy.get("stable_identity_fields")
        == list(STABLE_IDENTITY_FIELDS)
        and policy.get("code_fingerprint")
        == "SOURCE_SNIPPET_EXCLUDING_REPORT_LINE_NUMBERS"
    ):
        raise BaselineError("BASELINE_POLICY_INVALID")
    results = _normalized_results(baseline)
    if any(item["issue_severity"] != "LOW" for item in results):
        raise BaselineError("BASELINE_NOT_LOW_ONLY")
    if not isinstance(baseline.get("findings_sha256"), str) or (
        baseline["findings_sha256"] != _results_sha256(results)
    ):
        raise BaselineError("BASELINE_SHA256_MISMATCH")
    return results


def compare_report_to_baseline(
    report: dict[str, Any],
    baseline: dict[str, Any],
    *,
    bandit_version: str,
) -> dict[str, Any]:
    baseline_results = _validate_baseline(
        baseline,
        bandit_version=bandit_version,
    )
    current_results = _normalized_results(report)
    if any(item["issue_severity"] in {"MEDIUM", "HIGH"} for item in current_results):
        raise BaselineError("CURRENT_MEDIUM_OR_HIGH_FINDING")
    if any(item["issue_severity"] != "LOW" for item in current_results):
        raise BaselineError("CURRENT_SEVERITY_INVALID")

    baseline_counts = Counter(_stable_fingerprint(item) for item in baseline_results)
    current_counts = Counter(_stable_fingerprint(item) for item in current_results)
    new_counts = current_counts - baseline_counts
    if new_counts:
        raise BaselineError(
            f"NEW_BANDIT_FINDINGS:{sum(new_counts.values())}"
        )
    matched = sum((current_counts & baseline_counts).values())
    return {
        "status": "PASS_NO_NEW_BANDIT_FINDINGS",
        "bandit_version": bandit_version,
        "baseline_low": len(baseline_results),
        "current_low": len(current_results),
        "resolved_low": len(baseline_results) - matched,
        "new_low": 0,
        "current_medium": 0,
        "current_high": 0,
        "baseline_findings_sha256": baseline["findings_sha256"],
    }


def _read_json(path: Path) -> dict[str, Any]:
    if not path.is_file() or path.stat().st_size > MAX_REPORT_BYTES:
        raise BaselineError("BANDIT_REPORT_FILE_INVALID")
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise BaselineError("BANDIT_REPORT_ROOT_INVALID")
    return value


def _write_json(path: Path, value: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    rendered = json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    path.write_text(rendered, encoding="utf-8", newline="\n")


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)
    for command in ("freeze", "check"):
        subparser = subparsers.add_parser(command)
        subparser.add_argument("--report", type=Path, required=True)
        subparser.add_argument("--baseline", type=Path, required=True)
        subparser.add_argument("--bandit-version", required=True)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        report = _read_json(args.report)
        if args.command == "freeze":
            baseline = build_baseline(report, bandit_version=args.bandit_version)
            _write_json(args.baseline, baseline)
            result = {
                "status": "PASS_LOW_BASELINE_FROZEN",
                "bandit_version": args.bandit_version,
                "baseline_low": len(baseline["results"]),
                "baseline_findings_sha256": baseline["findings_sha256"],
            }
        else:
            baseline = _read_json(args.baseline)
            result = compare_report_to_baseline(
                report,
                baseline,
                bandit_version=args.bandit_version,
            )
    except (BaselineError, json.JSONDecodeError, OSError) as exc:
        print(json.dumps({"status": "HOLD", "reason": str(exc)}, sort_keys=True))
        return 2
    print(json.dumps(result, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
