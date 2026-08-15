"""Deterministic evidence serialization for VisionData Gate.

The functions in this module deliberately avoid timestamps, host names, and
other ambient state.  Equal logical inputs therefore produce equal bytes.
"""

from __future__ import annotations

import csv
import hashlib
import io
import json
import math
from collections.abc import Iterable, Mapping, Sequence
from datetime import date, datetime, timezone
from decimal import Decimal
from enum import Enum
from pathlib import Path, PurePath
from typing import Any

from pydantic import BaseModel

from .contracts import EvaluationResult, Finding, GateResult
from .policy import build_scenario_rule_profile_snapshot
from .runtime_models import ScenarioProfile


FINDINGS_CSV_FIELDS = (
    "finding_id",
    "code",
    "severity",
    "tool",
    "sample_ids",
    "summary",
    "evidence_status",
    "recommended_action",
    "evidence_json",
)

EVIDENCE_MATRIX_FIELDS = (
    "tool",
    "finding_id",
    "finding_code",
    "sample_ids",
    "work_order_ids",
    "failed_rule_checks",
    "evidence_span",
    "reason_trace",
)


def sha256_bytes(data: bytes) -> str:
    """Return a lowercase SHA-256 digest for *data*."""

    return hashlib.sha256(data).hexdigest()


def sha256_file(path: str | Path, *, chunk_size: int = 1024 * 1024) -> str:
    """Hash a file without loading it all into memory."""

    digest = hashlib.sha256()
    with Path(path).open("rb") as handle:
        for chunk in iter(lambda: handle.read(chunk_size), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _normalize_json(value: Any) -> Any:
    """Convert supported values to a deterministic JSON-compatible tree.

    Sets and arbitrary objects are intentionally rejected: silently choosing
    an order for an unordered input would make the evidence contract unclear.
    """

    if isinstance(value, BaseModel):
        return _normalize_json(value.model_dump(mode="json", exclude_none=False))
    if isinstance(value, Enum):
        return _normalize_json(value.value)
    if value is None or isinstance(value, (str, bool, int)):
        return value
    if isinstance(value, float):
        if not math.isfinite(value):
            raise ValueError("canonical JSON forbids NaN and infinity")
        return value
    if isinstance(value, Decimal):
        if not value.is_finite():
            raise ValueError("canonical JSON forbids non-finite Decimal values")
        return str(value)
    if isinstance(value, datetime):
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("canonical JSON requires timezone-aware datetimes")
        utc_value = value.astimezone(timezone.utc)
        return utc_value.isoformat(timespec="microseconds").replace("+00:00", "Z")
    if isinstance(value, date):
        return value.isoformat()
    if isinstance(value, PurePath):
        return value.as_posix()
    if isinstance(value, Mapping):
        normalized: dict[str, Any] = {}
        for key, item in value.items():
            if not isinstance(key, str):
                raise TypeError("canonical JSON object keys must be strings")
            normalized[key] = _normalize_json(item)
        return normalized
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
        return [_normalize_json(item) for item in value]
    if isinstance(value, (set, frozenset)):
        raise TypeError("canonical JSON does not accept unordered sets")

    # NumPy scalar support without making NumPy a hard import in this module.
    if type(value).__module__.startswith("numpy") and hasattr(value, "item"):
        return _normalize_json(value.item())
    raise TypeError(f"unsupported canonical JSON value: {type(value).__name__}")


def canonical_json_text(value: Any, *, trailing_newline: bool = True) -> str:
    """Serialize *value* with stable key order, UTF-8 text, and no NaN."""

    text = json.dumps(
        _normalize_json(value),
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    )
    return text + ("\n" if trailing_newline else "")


def canonical_json_bytes(value: Any, *, trailing_newline: bool = True) -> bytes:
    """Return canonical JSON encoded as UTF-8 bytes."""

    return canonical_json_text(value, trailing_newline=trailing_newline).encode("utf-8")


def write_canonical_json(path: str | Path, value: Any) -> str:
    """Write canonical JSON and return its SHA-256 digest."""

    destination = Path(path)
    destination.parent.mkdir(parents=True, exist_ok=True)
    data = canonical_json_bytes(value)
    destination.write_bytes(data)
    return sha256_bytes(data)


def _coerce_finding(value: Finding | Mapping[str, Any]) -> Finding:
    if isinstance(value, Finding):
        return value
    return Finding.model_validate(value)


def findings_csv_bytes(findings: Iterable[Finding | Mapping[str, Any]]) -> bytes:
    """Return a stable, spreadsheet-friendly findings CSV.

    Findings and sample IDs are sorted because their order has no semantic
    meaning in the frozen contract. Evidence dictionaries are stored as
    canonical inline JSON rather than Python repr strings.
    """

    normalized = [_coerce_finding(finding) for finding in findings]
    normalized.sort(key=lambda finding: (finding.finding_id, finding.code))

    buffer = io.StringIO(newline="")
    writer = csv.DictWriter(
        buffer,
        fieldnames=list(FINDINGS_CSV_FIELDS),
        extrasaction="raise",
        lineterminator="\n",
    )
    writer.writeheader()
    for finding in normalized:
        writer.writerow(
            {
                "finding_id": finding.finding_id,
                "code": finding.code,
                "severity": finding.severity.value,
                "tool": finding.tool,
                "sample_ids": "|".join(sorted(finding.sample_ids)),
                "summary": finding.summary,
                "evidence_status": finding.evidence_status.value,
                "recommended_action": finding.recommended_action,
                "evidence_json": canonical_json_text(
                    finding.evidence, trailing_newline=False
                ),
            }
        )
    return buffer.getvalue().encode("utf-8")


def write_findings_csv(
    path: str | Path, findings: Iterable[Finding | Mapping[str, Any]]
) -> str:
    """Write deterministic findings CSV and return its SHA-256 digest."""

    destination = Path(path)
    destination.parent.mkdir(parents=True, exist_ok=True)
    data = findings_csv_bytes(findings)
    destination.write_bytes(data)
    return sha256_bytes(data)


def _build_tool_to_finding_links(
    result: GateResult,
) -> dict[str, dict[str, list[str]]]:
    links: dict[str, dict[str, list[str]]] = {}
    failed_checks = [
        check for check in result.rule_checks if check.status.value == "FAIL"
    ]
    for finding in result.findings:
        keys = {
            finding.finding_id,
            finding.code,
            f"finding:{finding.finding_id}",
            f"code:{finding.code}",
        }
        for check in failed_checks:
            matched = sorted(
                ref
                for ref in check.related_refs
                if ref in keys
                or ref == check.check_id
                or ref == f"finding:{finding.finding_id}"
            )
            if not matched:
                continue
            links.setdefault(finding.finding_id, {}).setdefault(
                check.check_id, []
            ).extend(matched)
        if finding.code == "GOVERNANCE_SCOPE_GAP":
            # Governance tools commonly emit scope checks even without explicit refs.
            for check in failed_checks:
                if check.check_id == "RC-GOVERNANCE-SCOPE":
                    links.setdefault(finding.finding_id, {})[check.check_id] = [
                        "governance_scope_gap"
                    ]
                    break
    return {
        key: {check_id: sorted(set(refs)) for check_id, refs in value.items()}
        for key, value in links.items()
    }


def _compose_evidence_span(
    *, finding_id: str, tool: str, work_order_id: str = ""
) -> str:
    if work_order_id:
        return f"finding={finding_id}|tool={tool}|work_order={work_order_id}"
    return f"finding={finding_id}|tool={tool}"


def _compose_reason_trace(
    *, check_id: str, refs: Sequence[str], work_order_id: str = ""
) -> str:
    work_order_part = work_order_id or "none"
    return canonical_json_text(
        {
            "check_id": check_id,
            "refs": sorted(set(refs)),
            "work_order": work_order_part,
        },
        trailing_newline=False,
    )


def build_evidence_matrix_records(result: GateResult) -> list[dict[str, str]]:
    """Build deterministic one-to-one mapping rows for tool/finding/work order / rule check."""

    failed_checks_by_finding = _build_tool_to_finding_links(result)
    rows: list[dict[str, str]] = []
    represented_checks: set[str] = set()

    ordered_findings = sorted(
        result.findings, key=lambda finding: (finding.tool, finding.finding_id)
    )
    for finding in ordered_findings:
        work_orders = [
            order.work_order_id
            for order in result.work_orders
            if finding.code in order.reason_codes
            or finding.finding_id in order.reason_codes
        ]
        failed_map = failed_checks_by_finding.get(finding.finding_id, {})
        failed_checks = sorted(failed_map)
        if work_orders and failed_checks:
            for work_order_id in sorted(set(work_orders)):
                for check_id in failed_checks:
                    refs = sorted(failed_map[check_id])
                    rows.append(
                        {
                            "tool": finding.tool,
                            "finding_id": finding.finding_id,
                            "finding_code": finding.code,
                            "sample_ids": "|".join(sorted(finding.sample_ids)),
                            "work_order_ids": work_order_id,
                            "failed_rule_checks": check_id,
                            "evidence_span": _compose_evidence_span(
                                finding_id=finding.finding_id,
                                tool=finding.tool,
                                work_order_id=work_order_id,
                            ),
                            "reason_trace": _compose_reason_trace(
                                check_id=check_id,
                                refs=refs,
                                work_order_id=work_order_id,
                            ),
                        }
                    )
                    represented_checks.add(check_id)
        elif work_orders:
            for work_order_id in sorted(set(work_orders)):
                rows.append(
                    {
                        "tool": finding.tool,
                        "finding_id": finding.finding_id,
                        "finding_code": finding.code,
                        "sample_ids": "|".join(sorted(finding.sample_ids)),
                        "work_order_ids": work_order_id,
                        "failed_rule_checks": "",
                        "evidence_span": _compose_evidence_span(
                            finding_id=finding.finding_id,
                            tool=finding.tool,
                            work_order_id=work_order_id,
                        ),
                        "reason_trace": _compose_reason_trace(
                            check_id="finding-work-order-map",
                            refs=["finding:" + finding.finding_id],
                            work_order_id=work_order_id,
                        ),
                    }
                )
        elif failed_checks:
            for check_id in failed_checks:
                refs = sorted(failed_map[check_id])
                rows.append(
                    {
                        "tool": finding.tool,
                        "finding_id": finding.finding_id,
                        "finding_code": finding.code,
                        "sample_ids": "|".join(sorted(finding.sample_ids)),
                        "work_order_ids": "",
                        "failed_rule_checks": check_id,
                        "evidence_span": _compose_evidence_span(
                            finding_id=finding.finding_id,
                            tool=finding.tool,
                        ),
                        "reason_trace": _compose_reason_trace(
                            check_id=check_id,
                            refs=refs,
                        ),
                    }
                )
                represented_checks.add(check_id)

    failed_checks = [
        check for check in result.rule_checks if check.status.value == "FAIL"
    ]
    for check in failed_checks:
        if check.check_id in represented_checks:
            continue
        work_order_ids = [
            order.work_order_id
            for order in result.work_orders
            if check.check_id in order.reason_codes
        ]
        rows.append(
            {
                "tool": "policy",
                "finding_id": "",
                "finding_code": "",
                "sample_ids": "",
                "work_order_ids": "|".join(work_order_ids),
                "failed_rule_checks": check.check_id,
                "evidence_span": "policy-only|check-unbound-work-orders",
                "reason_trace": _compose_reason_trace(
                    check_id=check.check_id,
                    refs=check.related_refs,
                    work_order_id="|".join(work_order_ids),
                ),
            }
        )

    # Keep deterministic output order for downstream audit artifacts.
    rows.sort(
        key=lambda item: (
            item["tool"],
            item["finding_id"],
            item["finding_code"],
            item["failed_rule_checks"],
            item["work_order_ids"],
        )
    )
    return rows


def evidence_matrix_csv_bytes(rows: Iterable[dict[str, str]]) -> bytes:
    rows_sorted = list(rows)
    buffer = io.StringIO(newline="")
    writer = csv.DictWriter(
        buffer,
        fieldnames=list(EVIDENCE_MATRIX_FIELDS),
        extrasaction="raise",
        lineterminator="\n",
    )
    writer.writeheader()
    for row in rows_sorted:
        writer.writerow({key: row.get(key, "") for key in EVIDENCE_MATRIX_FIELDS})
    return buffer.getvalue().encode("utf-8")


def write_evidence_matrix_csv(path: str | Path, rows: Iterable[dict[str, str]]) -> str:
    destination = Path(path)
    destination.parent.mkdir(parents=True, exist_ok=True)
    data = evidence_matrix_csv_bytes(rows)
    destination.write_bytes(data)
    return sha256_bytes(data)


def write_evidence_artifacts(
    output_dir: str | Path,
    result: GateResult,
    evaluation: EvaluationResult | None = None,
    *,
    scenario_profile: ScenarioProfile | None = None,
) -> dict[str, str]:
    """Write the canonical JSON/CSV evidence core.

    The returned mapping contains relative POSIX paths and file hashes, ready
    to be incorporated into a higher-level artifact manifest.
    """

    root = Path(output_dir)
    root.mkdir(parents=True, exist_ok=True)
    artifacts: dict[str, str] = {}

    artifacts["gate_result.json"] = write_canonical_json(
        root / "gate_result.json", result
    )
    artifacts["findings.csv"] = write_findings_csv(
        root / "findings.csv", result.findings
    )
    if scenario_profile is not None:
        artifacts["rule_package_snapshot.json"] = write_canonical_json(
            root / "rule_package_snapshot.json",
            build_scenario_rule_profile_snapshot(scenario_profile),
        )
    artifacts["evidence_matrix.csv"] = write_evidence_matrix_csv(
        root / "evidence_matrix.csv",
        build_evidence_matrix_records(result),
    )
    if evaluation is not None:
        artifacts["evaluation.json"] = write_canonical_json(
            root / "evaluation.json", evaluation
        )
    return dict(sorted(artifacts.items()))


__all__ = [
    "FINDINGS_CSV_FIELDS",
    "canonical_json_bytes",
    "canonical_json_text",
    "findings_csv_bytes",
    "sha256_bytes",
    "sha256_file",
    "write_canonical_json",
    "write_evidence_matrix_csv",
    "build_evidence_matrix_records",
    "evidence_matrix_csv_bytes",
    "write_evidence_artifacts",
    "write_findings_csv",
]
