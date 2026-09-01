"""Build a redacted, deterministic public Goal 3 evidence bundle.

The source receipts live below the ignored local ``output`` namespace and contain
machine-local paths, browser process details, and diagnostic stderr.  This module
verifies those source receipts, projects only bounded synthetic facts, copies the
receipt-bound screenshots without metadata, and emits exact RFC 8785 JCS JSON.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import shutil
import struct
import tempfile
import zlib
from collections import Counter
from pathlib import Path, PurePosixPath
from typing import Any

from .audit_envelope import canonical_jcs_bytes
from .evidence import canonical_json_bytes, sha256_file
from .incident_interaction import IncidentInteractionReceipt
from .industrial_incident import parse_industrial_incident_case
from .package import scan_bytes_for_credentials, scan_bytes_for_private_paths
from .worker_selection import (
    WorkerSelectionReceipt,
    build_agent_behavior_receipt,
    verify_agent_behavior_receipt,
    verify_worker_selection_receipt,
)


GOAL3_PUBLIC_ROOT = PurePosixPath("evidence/submission/vdg-20260831-rc3/goal3")
GOAL3_PUBLIC_JSON_NAMES = (
    "goal3_acceptance_summary.json",
    "worker_selection_receipt.json",
    "incident_interaction_receipt.json",
    "semifinal_demo_manifest.json",
    "review_projection_negative_ui_summary.json",
)
GOAL3_PUBLIC_SCREENSHOT_NAMES = (
    "screenshots/01-review-main.png",
    "screenshots/02-authority-case.png",
    "screenshots/03-missing-reason-codes.png",
    "screenshots/04-bad-agent-behavior-sha.png",
    "screenshots/05-bad-strong-etag.png",
    "screenshots/06-network-interruption.png",
    "screenshots/07-stale-retention.png",
)
GOAL3_PUBLIC_REQUIRED_PATHS = tuple(
    str(GOAL3_PUBLIC_ROOT / name)
    for name in (*GOAL3_PUBLIC_JSON_NAMES, *GOAL3_PUBLIC_SCREENSHOT_NAMES)
)

DYNAMICBENCH_REPORT_PATHS = (
    "10_reports/DYNAMICBENCH_V2_WORKER_SELECTION_20260828.json",
    "10_reports/DYNAMICBENCH_V3_REPLANNING_20260829.json",
    "10_reports/DYNAMICBENCH_V4_PRODUCT_RUNTIME_20260829.json",
)

_NEGATIVE_SCENARIOS = (
    (
        "MISSING_REASON_CODES",
        "DELETE_SELECTED_WORKER_REASON_CODES",
        "CONTRACT_HOLD",
        "INVALID_INCIDENT_REVIEW_PROJECTION",
        "screenshots/03-missing-reason-codes.png",
        "01-missing-reason-codes.png",
    ),
    (
        "BAD_AGENT_BEHAVIOR_SHA",
        "REPLACE_AGENT_BEHAVIOR_SHA_WITH_INVALID_VALUE",
        "CONTRACT_HOLD",
        "INVALID_INCIDENT_REVIEW_PROJECTION",
        "screenshots/04-bad-agent-behavior-sha.png",
        "02-bad-agent-behavior-sha.png",
    ),
    (
        "BAD_STRONG_ETAG",
        "REPLACE_STRONG_ETAG_WITH_DIFFERENT_VALID_DIGEST",
        "STALE_HOLD",
        "RESPONSE_ETAG_BINDING_DRIFT",
        "screenshots/05-bad-strong-etag.png",
        "03-bad-strong-etag.png",
    ),
    (
        "NETWORK_INTERRUPTION",
        "FAIL_EXACT_REVIEW_PROJECTION_GET_AS_INTERNET_DISCONNECTED",
        "RETRYABLE_UNAVAILABLE",
        "NETWORK_UNAVAILABLE",
        "screenshots/06-network-interruption.png",
        "04-network-interruption.png",
    ),
    (
        "STALE_RETENTION",
        "REPLACE_EMBEDDED_PROJECTION_SHA_WITH_DIFFERENT_VALID_DIGEST",
        "STALE_HOLD",
        "INCIDENT_REVIEW_PROJECTION_SHA_DRIFT",
        "screenshots/07-stale-retention.png",
        "05-stale-retention.png",
    ),
)

_PNG_SIGNATURE = b"\x89PNG\r\n\x1a\n"
_FORBIDDEN_PNG_METADATA_CHUNKS = frozenset({b"eXIf", b"iTXt", b"tEXt", b"zTXt"})
_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
_COMMIT_RE = re.compile(r"^[0-9a-f]{40}$")
_EXTRA_PRIVATE_PATTERNS = (
    ("absolute_windows_path", re.compile(rb"(?i)(?<![a-z0-9])[a-z]:[\\/]")),
    (
        "local_browser_detail",
        re.compile(
            rb"(?i)(?:appdata|program files|devtools|stderr|wrong_secret|"
            rb"ws://|127\.0\.0\.1|localhost)"
        ),
    ),
)
_INTERACTION_HASH_DOMAIN = b"visiondata-gate/incident-interaction-receipt/v1"

_SEMIFINAL_SOURCE_MANIFEST_FIELDS = frozenset(
    {
        "schema_version",
        "status",
        "source_scope",
        "product_root",
        "actor_user_id",
        "workspace_id",
        "project_id",
        "project_source_kind",
        "task_id",
        "review_start_path",
        "task_request_sha256",
        "task_evidence_sha256",
        "task_execution_status",
        "task_final_decision",
        "task_release_readiness_status",
        "task_release_readiness_sha256",
        "event_count",
        "parent_case_id",
        "parent_case_sha256",
        "decision_id",
        "decision_sha256",
        "decision_kind",
        "child_case_id",
        "child_case_sha256",
        "child_incident_status",
        "child_incident_recommendation",
        "interaction_id",
        "interaction_receipt_sha256",
        "interaction_status",
        "remaining_open_question_count",
        "visual_assets",
        "production_release_allowed",
        "machine_write_permitted",
        "customer_validation",
        "factory_shadow_metrics",
        "claim_boundary",
        "manifest_sha256",
    }
)
_SEMIFINAL_PUBLIC_SOURCE_FIELDS = tuple(
    sorted(
        _SEMIFINAL_SOURCE_MANIFEST_FIELDS
        - {"actor_user_id", "manifest_sha256", "product_root", "review_start_path"}
    )
)


class Goal3PublicEvidenceError(ValueError):
    """Raised when source evidence cannot be projected safely and exactly."""


def _fail(message: str) -> None:
    raise Goal3PublicEvidenceError(message)


def _strict_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            _fail(f"duplicate JSON member: {key}")
        result[key] = value
    return result


def _read_json_object(path: Path) -> tuple[dict[str, Any], bytes]:
    try:
        raw = path.read_bytes()
    except OSError as exc:
        raise Goal3PublicEvidenceError(
            f"cannot read required JSON: {path.name}"
        ) from exc
    try:
        value = json.loads(
            raw.decode("utf-8"),
            object_pairs_hook=_strict_object,
            parse_constant=lambda value: _fail(f"non-finite JSON number: {value}"),
        )
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise Goal3PublicEvidenceError(f"invalid UTF-8 JSON: {path.name}") from exc
    if not isinstance(value, dict):
        _fail(f"required JSON is not an object: {path.name}")
    return value, raw


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _expect(condition: bool, message: str) -> None:
    if not condition:
        _fail(message)


def _resolve_inside(root: Path, value: Path, *, label: str) -> Path:
    candidate = value if value.is_absolute() else root / value
    try:
        resolved = candidate.resolve(strict=True)
        resolved.relative_to(root)
    except (OSError, ValueError) as exc:
        raise Goal3PublicEvidenceError(
            f"{label} must resolve inside the project root"
        ) from exc
    if resolved.is_symlink():
        _fail(f"{label} cannot be a symlink")
    return resolved


def _verify_canonical_receipt_sha(payload: dict[str, Any], *, label: str) -> str:
    stored = payload.get("receipt_sha256")
    if not isinstance(stored, str) or not _SHA256_RE.fullmatch(stored):
        _fail(f"{label} has no valid receipt_sha256")
    stable = dict(payload)
    stable.pop("receipt_sha256", None)
    observed = _sha256(canonical_json_bytes(stable))
    _expect(observed == stored, f"{label} receipt_sha256 drifted")
    return stored


def _verify_manifest_sha(payload: dict[str, Any]) -> str:
    stored = payload.get("manifest_sha256")
    if not isinstance(stored, str) or not _SHA256_RE.fullmatch(stored):
        _fail("semifinal manifest has no valid manifest_sha256")
    stable = dict(payload)
    stable.pop("manifest_sha256", None)
    _expect(
        _sha256(canonical_json_bytes(stable)) == stored,
        "semifinal manifest SHA-256 drifted",
    )
    return stored


def _verify_interaction_sha(receipt: IncidentInteractionReceipt) -> None:
    stable = receipt.model_dump(mode="json", exclude={"receipt_sha256"})
    payload = canonical_json_bytes(stable)
    framed = (
        b"VDG-INTERACTION-V1\x00"
        + len(_INTERACTION_HASH_DOMAIN).to_bytes(2, "big")
        + _INTERACTION_HASH_DOMAIN
        + len(payload).to_bytes(8, "big")
        + payload
    )
    _expect(
        _sha256(framed) == receipt.receipt_sha256,
        "interaction receipt SHA-256 drifted",
    )


def inspect_public_png(path: Path) -> dict[str, Any]:
    """Validate a PNG and return bounded metadata without decoding its pixels."""

    raw = path.read_bytes()
    _expect(raw.startswith(_PNG_SIGNATURE), f"invalid PNG signature: {path.name}")
    offset = len(_PNG_SIGNATURE)
    width: int | None = None
    height: int | None = None
    seen_iend = False
    chunk_types: list[str] = []
    while offset < len(raw):
        _expect(offset + 12 <= len(raw), f"truncated PNG chunk: {path.name}")
        length = struct.unpack(">I", raw[offset : offset + 4])[0]
        chunk_type = raw[offset + 4 : offset + 8]
        end = offset + 12 + length
        _expect(end <= len(raw), f"truncated PNG data: {path.name}")
        chunk_data = raw[offset + 8 : offset + 8 + length]
        stored_crc = struct.unpack(">I", raw[offset + 8 + length : end])[0]
        observed_crc = zlib.crc32(chunk_type)
        observed_crc = zlib.crc32(chunk_data, observed_crc) & 0xFFFFFFFF
        _expect(stored_crc == observed_crc, f"PNG CRC drifted: {path.name}")
        _expect(
            chunk_type not in _FORBIDDEN_PNG_METADATA_CHUNKS,
            f"PNG contains forbidden metadata: {path.name}",
        )
        chunk_types.append(chunk_type.decode("ascii", errors="replace"))
        if chunk_type == b"IHDR":
            _expect(length == 13 and width is None, f"invalid PNG IHDR: {path.name}")
            width, height = struct.unpack(">II", chunk_data[:8])
        if chunk_type == b"IEND":
            _expect(length == 0, f"invalid PNG IEND: {path.name}")
            seen_iend = True
            offset = end
            break
        offset = end
    _expect(seen_iend and offset == len(raw), f"invalid PNG termination: {path.name}")
    _expect(width is not None and height is not None, f"PNG has no IHDR: {path.name}")
    return {
        "bytes": len(raw),
        "height": height,
        "metadata_chunks_included": False,
        "sha256": _sha256(raw),
        "width": width,
        "chunk_types": chunk_types,
    }


def _assert_public_json(path: str, data: bytes) -> None:
    issues = [
        *scan_bytes_for_credentials(path, data),
        *scan_bytes_for_private_paths(path, data),
    ]
    if issues:
        _fail(f"public JSON failed package privacy scan: {path}")
    for label, pattern in _EXTRA_PRIVATE_PATTERNS:
        if pattern.search(data):
            _fail(f"public JSON contains {label}: {path}")


def _write_jcs(
    path: Path, payload: dict[str, Any], *, public_path: str
) -> dict[str, Any]:
    data = canonical_jcs_bytes(payload)
    _assert_public_json(public_path, data)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data)
    return {"bytes": len(data), "path": public_path, "sha256": _sha256(data)}


def _copy_public_png(
    source: Path,
    destination: Path,
    *,
    public_path: str,
    expected_sha256: str | None = None,
    expected_bytes: int | None = None,
) -> dict[str, Any]:
    source_info = inspect_public_png(source)
    if expected_sha256 is not None:
        _expect(source_info["sha256"] == expected_sha256, "screenshot SHA-256 drifted")
    if expected_bytes is not None:
        _expect(source_info["bytes"] == expected_bytes, "screenshot byte count drifted")
    destination.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(source, destination)
    copied_info = inspect_public_png(destination)
    _expect(
        source_info == copied_info, "copied screenshot changed bytes or PNG structure"
    )
    return {
        "bytes": copied_info["bytes"],
        "height": copied_info["height"],
        "metadata_chunks_included": False,
        "path": public_path,
        "sha256": copied_info["sha256"],
        "width": copied_info["width"],
    }


def _safe_public_manifest(
    manifest: dict[str, Any], *, source_file_sha256: str
) -> dict[str, Any]:
    observed_fields = frozenset(manifest)
    _expect(
        observed_fields == _SEMIFINAL_SOURCE_MANIFEST_FIELDS,
        "semifinal manifest field set drifted; public projection requires explicit review",
    )
    public = {key: manifest[key] for key in _SEMIFINAL_PUBLIC_SOURCE_FIELDS}
    public["schema_version"] = "visiondata-gate.semifinal-demo-public-manifest.v1"
    public["source_manifest_schema_version"] = manifest["schema_version"]
    public["source_manifest_sha256"] = manifest["manifest_sha256"]
    public["source_manifest_file_sha256"] = source_file_sha256
    public["public_export"] = {
        "absolute_paths_included": False,
        "private_pilot_evidence_included": False,
        "raw_product_root_included": False,
        "source_assets_included": False,
    }
    return public


def _dynamicbench_summary(
    project_root: Path,
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    reports: list[tuple[dict[str, Any], bytes]] = []
    bindings: list[dict[str, Any]] = []
    for relative in DYNAMICBENCH_REPORT_PATHS:
        payload, raw = _read_json_object(project_root / PurePosixPath(relative))
        _assert_public_json(relative, raw)
        reports.append((payload, raw))
        bindings.append(
            {
                "bytes": len(raw),
                "kind": "DYNAMICBENCH",
                "path": relative,
                "sha256": _sha256(raw),
            }
        )

    v2, _ = reports[0]
    v2_summary = v2.get("summary")
    _expect(
        v2.get("status") == "PASS" and isinstance(v2_summary, dict),
        "DynamicBench v2 did not PASS",
    )
    _expect(
        v2_summary.get("record_count") == 288, "DynamicBench v2 denominator drifted"
    )
    _expect(
        v2_summary.get("correct_selection_count") == 288,
        "DynamicBench v2 accuracy drifted",
    )
    records = v2.get("records")
    _expect(
        isinstance(records, list) and len(records) == 288,
        "DynamicBench v2 records drifted",
    )
    _expect(
        all(
            item.get("actual_model_call_count") == 0
            for item in records
            if isinstance(item, dict)
        ),
        "DynamicBench v2 unexpectedly called a model",
    )

    v3, _ = reports[1]
    v3_metrics = v3.get("metrics")
    _expect(
        v3.get("status") == "PASS" and isinstance(v3_metrics, dict),
        "DynamicBench v3 did not PASS",
    )
    dynamic = v3_metrics.get("dynamic_replanning_contract")
    fixed = v3_metrics.get("fixed_rule_baseline")
    _expect(
        isinstance(dynamic, dict) and isinstance(fixed, dict),
        "DynamicBench v3 metrics are incomplete",
    )
    _expect(
        v3.get("data_source_status") == "FROZEN_SYNTHETIC_FIXTURES",
        "DynamicBench v3 source scope drifted",
    )
    _expect(
        v3.get("industrial_effectiveness_status") == "NOT_EVALUATED",
        "DynamicBench v3 industrial boundary drifted",
    )
    _expect(
        v3.get("actual_model_call_count") == 0,
        "DynamicBench v3 unexpectedly called a model",
    )

    v4, _ = reports[2]
    v4_metrics = v4.get("metrics")
    _expect(
        v4.get("status") == "PASS" and isinstance(v4_metrics, dict),
        "DynamicBench v4 did not PASS",
    )
    _expect(
        v4.get("data_source_status") == "FROZEN_SYNTHETIC_FIXTURES",
        "DynamicBench v4 source scope drifted",
    )
    _expect(
        v4.get("industrial_effectiveness_status") == "NOT_EVALUATED",
        "DynamicBench v4 industrial boundary drifted",
    )
    _expect(
        v4.get("production_deployment_status") == "NOT_CONNECTED",
        "DynamicBench v4 production boundary drifted",
    )

    summary = {
        "v2_worker_selection": {
            "actual_model_call_count": 0,
            "claim_boundary": (
                "Deterministic Worker-selection correctness, input-order invariance, and repeat stability "
                "over frozen synthetic fixtures only; industrial effectiveness is not evaluated."
            ),
            "correct_selection_count": v2_summary["correct_selection_count"],
            "input_order_invariant_fixture_count": v2_summary[
                "input_order_invariant_fixture_count"
            ],
            "record_count": v2_summary["record_count"],
            "repeat_stable_fixture_count": v2_summary["repeat_stable_fixture_count"],
            "status": v2["status"],
        },
        "v3_dynamic_replanning": {
            "claim_boundary": v3["claim_boundary"],
            "dynamic_correct_terminal_count": dynamic[
                "correct_terminal_disposition_count"
            ],
            "dynamic_tool_call_count": dynamic["total_tool_call_count"],
            "dynamic_tool_failure_recovery_count": dynamic[
                "tool_failure_recovery_success_count"
            ],
            "dynamic_unsafe_release_count": dynamic["unsafe_release_count"],
            "fixed_correct_terminal_count": fixed["correct_terminal_disposition_count"],
            "fixed_tool_call_count": fixed["total_tool_call_count"],
            "fixed_tool_failure_recovery_count": fixed[
                "tool_failure_recovery_success_count"
            ],
            "fixed_unsafe_release_count": fixed["unsafe_release_count"],
            "industrial_effectiveness_status": v3["industrial_effectiveness_status"],
            "status": v3["status"],
        },
        "v4_product_runtime": {
            "claim_boundary": v4["claim_boundary"],
            "incident_v6_count": v4_metrics["incident_v6_count"],
            "industrial_effectiveness_status": v4["industrial_effectiveness_status"],
            "passed_count": v4_metrics["passed_count"],
            "product_service_execution_count": v4_metrics[
                "product_service_execution_count"
            ],
            "production_deployment_status": v4["production_deployment_status"],
            "status": v4["status"],
            "tool_failure_recovered_fail_closed_count": v4_metrics[
                "tool_failure_recovered_fail_closed_count"
            ],
            "unsafe_production_release_count": v4_metrics[
                "unsafe_production_release_count"
            ],
        },
    }
    return summary, bindings


def _build_negative_summary(
    receipt: dict[str, Any],
    *,
    source_file_sha256: str,
    screenshot_bindings: dict[str, dict[str, Any]],
) -> dict[str, Any]:
    _expect(
        receipt.get("schema_version")
        == "visiondata-gate.review-projection-negative-ui-receipt.v1",
        "negative UI receipt schema drifted",
    )
    _expect(
        receipt.get("status") == "PASS_LOCAL_REVIEW_PROJECTION_NEGATIVE_UI",
        "negative UI receipt did not PASS",
    )
    summary = receipt.get("summary")
    boundaries = receipt.get("boundaries")
    runs = receipt.get("scenario_runs")
    _expect(
        isinstance(summary, dict) and isinstance(boundaries, dict),
        "negative UI receipt is incomplete",
    )
    _expect(
        isinstance(runs, list) and len(runs) == len(_NEGATIVE_SCENARIOS),
        "negative UI scenario count drifted",
    )
    by_name = {item.get("scenario"): item for item in runs if isinstance(item, dict)}
    public_runs: list[dict[str, Any]] = []
    projection_shas: set[str] = set()
    behavior_shas: set[str] = set()
    for (
        scenario,
        injection,
        expected_status,
        expected_error,
        public_screenshot,
        _,
    ) in _NEGATIVE_SCENARIOS:
        run = by_name.get(scenario)
        _expect(isinstance(run, dict), f"missing negative UI scenario: {scenario}")
        observed = run.get("observed")
        snapshot = observed.get("snapshot") if isinstance(observed, dict) else None
        assertions = run.get("assertions")
        page_network = run.get("page_network")
        console = run.get("console")
        _expect(isinstance(snapshot, dict), f"missing observed snapshot: {scenario}")
        _expect(
            isinstance(assertions, dict) and assertions,
            f"missing assertions: {scenario}",
        )
        _expect(
            all(value is True for value in assertions.values()),
            f"negative UI assertion failed: {scenario}",
        )
        _expect(
            run.get("status") == "PASS_EXPECTED_FAIL_CLOSED",
            f"negative UI scenario failed: {scenario}",
        )
        _expect(
            run.get("expected_status") == expected_status,
            f"expected status drifted: {scenario}",
        )
        _expect(
            run.get("expected_error_code") == expected_error,
            f"expected error drifted: {scenario}",
        )
        _expect(
            snapshot.get("data_read_status") == expected_status,
            f"observed status drifted: {scenario}",
        )
        error_text = snapshot.get("error_text")
        _expect(
            isinstance(error_text, str)
            and error_text.split(" · ", 1)[0] == expected_error,
            f"observed error drifted: {scenario}",
        )
        _expect(
            snapshot.get("current_projection_visible") is False,
            f"failed UI retained CURRENT projection: {scenario}",
        )
        _expect(
            snapshot.get("stale_projection_visible") is True,
            f"failed UI lost stale projection: {scenario}",
        )
        _expect(
            isinstance(page_network, dict), f"missing page network audit: {scenario}"
        )
        _expect(
            page_network.get("forbidden_write_method_count") == 0,
            f"page write observed: {scenario}",
        )
        _expect(isinstance(console, dict), f"missing console audit: {scenario}")
        _expect(
            console.get("unexpected_count") == 0,
            f"unexpected browser error: {scenario}",
        )
        _expect(
            console.get("runtime_exception_count") == 0,
            f"runtime exception observed: {scenario}",
        )
        projection_sha = snapshot.get("projection_sha256")
        baseline = run.get("baseline")
        behavior_sha = (
            baseline.get("agent_behavior_receipt_sha256")
            if isinstance(baseline, dict)
            else None
        )
        _expect(
            isinstance(projection_sha, str)
            and _SHA256_RE.fullmatch(projection_sha) is not None,
            f"projection SHA missing: {scenario}",
        )
        _expect(
            isinstance(behavior_sha, str)
            and _SHA256_RE.fullmatch(behavior_sha) is not None,
            f"behavior SHA missing: {scenario}",
        )
        projection_shas.add(projection_sha)
        behavior_shas.add(behavior_sha)
        public_runs.append(
            {
                "assertions": assertions,
                "injection": injection,
                "observed_error_code": expected_error,
                "observed_status": snapshot["data_read_status"],
                "scenario": scenario,
                "screenshot": screenshot_bindings[public_screenshot],
                "status": run["status"],
            }
        )
    _expect(
        len(projection_shas) == 1 and len(behavior_shas) == 1,
        "negative UI source bindings drifted across scenarios",
    )
    _expect(summary.get("passed_scenario_count") == 5, "negative UI PASS count drifted")
    _expect(
        summary.get("failed_scenario_count") == 0, "negative UI failure count drifted"
    )
    _expect(
        summary.get("no_page_http_write_methods") is True,
        "negative UI write boundary drifted",
    )
    _expect(
        summary.get("console_unexpected_count") == 0,
        "negative UI console boundary drifted",
    )
    _expect(
        summary.get("runtime_exception_count") == 0,
        "negative UI runtime boundary drifted",
    )
    return {
        "bound_evidence": {
            "agent_behavior_receipt_sha256": next(iter(behavior_shas)),
            "projection_sha256": next(iter(projection_shas)),
        },
        "boundaries": {
            "customer_validation": boundaries["customer_validation"],
            "factory_shadow_metrics": boundaries["factory_shadow_metrics"],
            "machine_write_permitted": False,
            "page_http_mutation_permitted": False,
            "production_release_allowed": False,
            "submission_eligible": False,
        },
        "claim_boundary": receipt["claim_boundary"],
        "isolated_source": {
            "cross_source_product_root_identity_claimed": False,
            "interaction_receipt_sha256": receipt["manifest"][
                "interaction_receipt_sha256"
            ],
            "kind": "SEPARATE_ISOLATED_GOAL1_PRODUCT_ROOT",
            "manifest_file_sha256": receipt["manifest"]["file_sha256"],
            "manifest_sha256": receipt["manifest"]["declared_manifest_sha256"],
            "raw_manifest_packaged": False,
        },
        "raw_receipt_packaged": False,
        "scenarios": public_runs,
        "schema_version": "visiondata-gate.goal3-public-negative-ui-summary.v1",
        "source_generated_at_utc": receipt["generated_at_utc"],
        "source_receipt_file_sha256": source_file_sha256,
        "source_receipt_sha256": receipt["receipt_sha256"],
        "source_scope": "SYNTHETIC_FIXTURE_REPLAY_ONLY",
        "status": receipt["status"],
        "summary": summary,
    }


def _verify_ui_manifest_summary(
    receipt: dict[str, Any], *, label: str
) -> dict[str, Any]:
    """Verify the receipt-bound manifest summary without claiming raw-manifest custody."""

    manifest = receipt.get("manifest")
    _expect(isinstance(manifest, dict), f"{label} manifest summary is missing")
    for key in (
        "file_sha256",
        "declared_manifest_sha256",
        "calculated_manifest_sha256",
        "interaction_receipt_sha256",
    ):
        value = manifest.get(key)
        _expect(
            isinstance(value, str) and _SHA256_RE.fullmatch(value) is not None,
            f"{label} manifest {key} is invalid",
        )
    _expect(
        manifest["declared_manifest_sha256"] == manifest["calculated_manifest_sha256"],
        f"{label} manifest digest summary drifted",
    )
    _expect(
        manifest.get("contract_status") == "VERIFIED",
        f"{label} manifest contract was not verified",
    )
    boundaries = manifest.get("boundaries")
    _expect(isinstance(boundaries, dict), f"{label} manifest boundaries are missing")
    _expect(
        boundaries.get("source_scope") == "SYNTHETIC_FIXTURE_REPLAY_ONLY",
        f"{label} manifest source scope drifted",
    )
    for key in ("machine_write_permitted", "production_release_allowed"):
        _expect(boundaries.get(key) is False, f"{label} manifest enabled {key}")
    _expect(
        boundaries.get("customer_validation") == "NOT_CLAIMED",
        f"{label} manifest customer boundary drifted",
    )
    _expect(
        boundaries.get("factory_shadow_metrics") == "NOT_MEASURED_PENDING_ADJUDICATION",
        f"{label} manifest factory boundary drifted",
    )
    return manifest


def build_goal3_public_evidence(
    *,
    project_root: Path,
    product_root: Path,
    negative_receipt_path: Path,
    positive_receipt_path: Path,
    positive_authority_screenshot: Path,
    output_root: Path,
    source_runtime_commit: str,
) -> dict[str, Any]:
    """Build the public bundle after validating all source receipts fail-closed."""

    project = project_root.resolve(strict=True)
    _expect(project.is_dir(), "project root is not a directory")
    _expect(
        _COMMIT_RE.fullmatch(source_runtime_commit) is not None,
        "invalid runtime commit",
    )
    product = _resolve_inside(project, product_root, label="product root")
    negative_path = _resolve_inside(
        project, negative_receipt_path, label="negative receipt"
    )
    positive_path = _resolve_inside(
        project, positive_receipt_path, label="positive receipt"
    )
    positive_authority = _resolve_inside(
        project, positive_authority_screenshot, label="positive authority screenshot"
    )

    output = output_root if output_root.is_absolute() else project / output_root
    output = output.resolve(strict=False)
    _expect(
        output == project / GOAL3_PUBLIC_ROOT,
        "output root must be the fixed public Goal 3 directory",
    )
    _expect(not output.exists(), "public Goal 3 output already exists")

    manifest_path = product / "semifinal_demo_manifest.json"
    manifest, manifest_raw = _read_json_object(manifest_path)
    manifest_sha = _verify_manifest_sha(manifest)
    _expect(
        manifest.get("source_scope") == "SYNTHETIC_FIXTURE_REPLAY_ONLY",
        "manifest source scope drifted",
    )
    _expect(
        manifest.get("project_source_kind") == "synthetic_demo",
        "manifest source kind drifted",
    )
    _expect(
        manifest.get("production_release_allowed") is False,
        "manifest enabled production release",
    )
    _expect(
        manifest.get("machine_write_permitted") is False,
        "manifest enabled machine write",
    )
    _expect(
        manifest.get("customer_validation") == "NOT_CLAIMED",
        "manifest customer boundary drifted",
    )
    _expect(
        manifest.get("factory_shadow_metrics") == "NOT_MEASURED_PENDING_ADJUDICATION",
        "manifest factory boundary drifted",
    )
    declared_product_root = Path(str(manifest.get("product_root"))).resolve(
        strict=False
    )
    _expect(
        declared_product_root == product,
        "manifest product root does not match the selected source",
    )

    child_case_path = (
        product
        / "industrial_incidents"
        / str(manifest["workspace_id"])
        / str(manifest["project_id"])
        / str(manifest["task_id"])
        / str(manifest["child_case_id"])
        / "case.json"
    )
    child_payload, child_raw = _read_json_object(child_case_path)
    child_case = parse_industrial_incident_case(child_payload)
    _expect(
        child_case.case_sha256 == manifest["child_case_sha256"],
        "child Case binding drifted",
    )
    _expect(child_case.status == "INVESTIGATION_REQUIRED", "child Case status drifted")
    _expect(
        child_case.recommendation == "CONTINUE_HOLD",
        "child Case recommendation drifted",
    )
    _expect(
        child_case.root_cause_status == "NOT_ESTABLISHED", "root cause boundary drifted"
    )
    _expect(
        child_case.production_release_allowed is False,
        "child Case enabled production release",
    )
    _expect(
        child_case.machine_write_permitted is False, "child Case enabled machine write"
    )

    selection = WorkerSelectionReceipt.model_validate(
        child_payload["worker_selection_receipt"]
    )
    verify_worker_selection_receipt(selection)
    behavior = build_agent_behavior_receipt(selection)
    verify_agent_behavior_receipt(behavior, selection=selection)

    interaction_path = child_case_path.parent / "interaction" / "receipt.json"
    interaction_payload, interaction_raw = _read_json_object(interaction_path)
    interaction = IncidentInteractionReceipt.model_validate(interaction_payload)
    _verify_interaction_sha(interaction)
    _expect(
        interaction.receipt_sha256 == manifest["interaction_receipt_sha256"],
        "interaction binding drifted",
    )
    _expect(
        interaction.child_case_sha256 == child_case.case_sha256,
        "interaction child binding drifted",
    )
    _expect(
        interaction.remaining_open_question_count == 1,
        "interaction open-question count drifted",
    )
    _expect(
        interaction.production_release_allowed is False,
        "interaction enabled production release",
    )
    _expect(
        interaction.machine_write_permitted is False,
        "interaction enabled machine write",
    )

    negative, negative_raw = _read_json_object(negative_path)
    negative_receipt_sha = _verify_canonical_receipt_sha(negative, label="negative UI")
    negative_manifest = _verify_ui_manifest_summary(negative, label="negative UI")

    positive, positive_raw = _read_json_object(positive_path)
    positive_receipt_sha = _verify_canonical_receipt_sha(positive, label="positive UI")
    _expect(
        positive.get("status") == "PASS_LOCAL_REVIEW_UI_VERIFIED",
        "positive UI receipt did not PASS",
    )
    positive_boundaries = positive.get("boundaries")
    _expect(isinstance(positive_boundaries, dict), "positive UI boundaries are missing")
    _expect(
        positive_boundaries.get("source_scope") == "SYNTHETIC_FIXTURE_REPLAY_ONLY",
        "positive UI source scope drifted",
    )
    _expect(
        positive_boundaries.get("production_release_allowed") is False,
        "positive UI enabled production release",
    )
    _expect(
        positive_boundaries.get("machine_write_permitted") is False,
        "positive UI enabled machine write",
    )
    positive_manifest = _verify_ui_manifest_summary(positive, label="positive UI")
    for key in (
        "file_sha256",
        "declared_manifest_sha256",
        "interaction_receipt_sha256",
    ):
        _expect(
            positive_manifest[key] == negative_manifest[key],
            f"positive and negative UI isolated sources disagree on {key}",
        )
    _expect(
        negative_manifest["file_sha256"] != _sha256(manifest_raw),
        "separate isolated UI source falsely matches the persistent ProductRoot",
    )
    browser_runs = positive.get("browser_runs")
    _expect(
        isinstance(browser_runs, list) and len(browser_runs) == 1,
        "positive UI run count drifted",
    )
    positive_artifact_root = (
        positive_path.parent / f"{positive_path.stem}_artifacts" / "run-01"
    ).resolve(strict=True)
    viewports = browser_runs[0].get("viewports")
    _expect(isinstance(viewports, list), "positive UI viewport list is missing")
    review_viewports = [
        item
        for item in viewports
        if isinstance(item, dict)
        and item.get("status") == "PASS_LOCAL_VIEWPORT"
        and item.get("viewport") == {"width": 1440, "height": 900, "label": "1440x900"}
    ]
    _expect(
        len(review_viewports) == 1,
        "positive UI receipt must contain exactly one verified 1440x900 viewport",
    )
    review_source = review_viewports[0].get("screenshot")
    _expect(
        isinstance(review_source, dict),
        "positive UI 1440x900 screenshot binding is missing",
    )
    positive_review = Path(str(review_source.get("path"))).resolve(strict=True)
    _expect(
        positive_review.parent == positive_artifact_root
        and positive_review.name == "05-1440x900.png",
        "positive review screenshot escaped its receipt artifact set",
    )
    _expect(
        review_source.get("sha256") == sha256_file(positive_review)
        and review_source.get("bytes") == positive_review.stat().st_size,
        "positive review screenshot binding drifted",
    )
    authority_source = (
        browser_runs[0].get("authority_case", {}).get("authority_screenshot", {})
    )
    declared_authority = Path(str(authority_source.get("path"))).resolve(strict=True)
    _expect(
        declared_authority == positive_authority
        and positive_authority.parent == positive_artifact_root
        and positive_authority.name == "authority-case.png",
        "positive authority screenshot escaped its receipt artifact set",
    )
    _expect(
        authority_source.get("sha256") == sha256_file(positive_authority),
        "positive authority screenshot binding drifted",
    )
    _expect(
        authority_source.get("bytes") == positive_authority.stat().st_size,
        "positive authority screenshot size drifted",
    )

    negative_artifact_root = (
        negative_path.parent / f"{negative_path.stem}_artifacts" / "negative" / "run-01"
    )
    negative_artifact_root = negative_artifact_root.resolve(strict=True)
    screenshot_sources: dict[str, tuple[Path, str | None, int | None]] = {
        "screenshots/01-review-main.png": (
            positive_review,
            str(review_source["sha256"]),
            int(review_source["bytes"]),
        ),
        "screenshots/02-authority-case.png": (
            positive_authority,
            authority_source["sha256"],
            authority_source["bytes"],
        ),
    }
    by_scenario = {
        item.get("scenario"): item
        for item in negative.get("scenario_runs", [])
        if isinstance(item, dict)
    }
    for scenario, _, _, _, public_name, source_name in _NEGATIVE_SCENARIOS:
        run = by_scenario.get(scenario)
        _expect(
            isinstance(run, dict), f"missing negative screenshot source: {scenario}"
        )
        screenshot = run.get("screenshot")
        _expect(
            isinstance(screenshot, dict),
            f"missing negative screenshot receipt: {scenario}",
        )
        source = Path(str(screenshot.get("path"))).resolve(strict=True)
        _expect(
            source.parent == negative_artifact_root,
            f"negative screenshot escaped its receipt set: {scenario}",
        )
        _expect(
            source.name == source_name, f"negative screenshot name drifted: {scenario}"
        )
        screenshot_sources[public_name] = (
            source,
            str(screenshot.get("sha256")),
            int(screenshot.get("bytes")),
        )

    dynamicbench, report_bindings = _dynamicbench_summary(project)
    hypothesis_counts = Counter(item.status for item in child_case.hypotheses)
    _expect(
        hypothesis_counts == Counter({"SUPPORTED": 3, "REJECTED": 2, "UNRESOLVED": 1}),
        "competing-hypothesis outcome drifted",
    )

    output.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(
        prefix=".goal3-public-", dir=output.parent
    ) as temporary:
        staging = Path(temporary) / "goal3"
        staging.mkdir()
        artifact_bindings: list[dict[str, Any]] = [*report_bindings]

        selection_public = str(GOAL3_PUBLIC_ROOT / "worker_selection_receipt.json")
        artifact_bindings.append(
            {
                "kind": "WORKER_SELECTION_RECEIPT",
                **_write_jcs(
                    staging / "worker_selection_receipt.json",
                    selection.model_dump(mode="json"),
                    public_path=selection_public,
                ),
            }
        )
        interaction_public = str(
            GOAL3_PUBLIC_ROOT / "incident_interaction_receipt.json"
        )
        artifact_bindings.append(
            {
                "kind": "INCIDENT_INTERACTION_RECEIPT",
                **_write_jcs(
                    staging / "incident_interaction_receipt.json",
                    interaction.model_dump(mode="json"),
                    public_path=interaction_public,
                ),
            }
        )
        manifest_public = str(GOAL3_PUBLIC_ROOT / "semifinal_demo_manifest.json")
        artifact_bindings.append(
            {
                "kind": "SEMIFINAL_DEMO_PUBLIC_MANIFEST",
                **_write_jcs(
                    staging / "semifinal_demo_manifest.json",
                    _safe_public_manifest(
                        manifest, source_file_sha256=_sha256(manifest_raw)
                    ),
                    public_path=manifest_public,
                ),
            }
        )

        screenshot_bindings: dict[str, dict[str, Any]] = {}
        for public_name, (
            source,
            expected_sha,
            expected_size,
        ) in screenshot_sources.items():
            public_path = str(GOAL3_PUBLIC_ROOT / public_name)
            binding = _copy_public_png(
                source,
                staging / PurePosixPath(public_name),
                public_path=public_path,
                expected_sha256=expected_sha,
                expected_bytes=expected_size,
            )
            screenshot_bindings[public_name] = binding
            artifact_bindings.append({"kind": "SYNTHETIC_UI_SCREENSHOT", **binding})

        negative_summary = _build_negative_summary(
            negative,
            source_file_sha256=_sha256(negative_raw),
            screenshot_bindings=screenshot_bindings,
        )
        negative_public = str(
            GOAL3_PUBLIC_ROOT / "review_projection_negative_ui_summary.json"
        )
        artifact_bindings.append(
            {
                "kind": "REVIEW_PROJECTION_NEGATIVE_UI_SUMMARY",
                **_write_jcs(
                    staging / "review_projection_negative_ui_summary.json",
                    negative_summary,
                    public_path=negative_public,
                ),
            }
        )

        acceptance = {
            "artifact_bindings": sorted(
                artifact_bindings, key=lambda item: str(item["path"])
            ),
            "boundaries": {
                "customer_validation": "NOT_CLAIMED",
                "factory_shadow_metrics": "NOT_MEASURED_PENDING_ADJUDICATION",
                "industrial_effectiveness_status": "NOT_EVALUATED",
                "machine_write_permitted": False,
                "official_status": "NOT_EVALUATED",
                "private_omni_data_included": False,
                "production_release_allowed": False,
                "submission_eligible": False,
            },
            "claim_boundary": (
                "This public bundle proves deterministic local Agent behavior, synthetic ProductRoot interaction, "
                "frozen DynamicBench results, and expected fail-closed browser behavior only. It does not prove "
                "factory effectiveness, customer acceptance, production deployment, official submission, or "
                "production release. This subsystem summary is not a standalone release decision; repository-level "
                "release status must be established by the detached Release Attestation. The Goal 1 review UI "
                "receipts come from a separate isolated synthetic ProductRoot and are not claimed to share identity "
                "with the persistent ProductRoot interaction evidence."
            ),
            "dynamicbench": dynamicbench,
            "interaction": {
                "interaction_status": interaction.interaction_status,
                "machine_write_permitted": False,
                "production_release_allowed": False,
                "receipt_sha256": interaction.receipt_sha256,
                "remaining_open_question_count": interaction.remaining_open_question_count,
                "turn_actions": [item.action for item in interaction.turns],
            },
            "kernel_contract": {
                "stage_sequence": [
                    "INTAKE",
                    "PLANNER",
                    "TOOL",
                    "COUNCIL",
                    "JUDGE",
                    "DELIVERY",
                ],
                "status": "PASS_LOCAL_CAPABILITY",
            },
            "raw_sources": {
                "child_case_file_sha256": _sha256(child_raw),
                "interaction_receipt_file_sha256": _sha256(interaction_raw),
                "manifest_file_sha256": _sha256(manifest_raw),
                "negative_ui_receipt_file_sha256": _sha256(negative_raw),
                "negative_ui_receipt_sha256": negative_receipt_sha,
                "positive_ui_receipt_file_sha256": _sha256(positive_raw),
                "positive_ui_receipt_sha256": positive_receipt_sha,
                "raw_receipts_packaged": False,
                "source_runtime_commit": source_runtime_commit,
            },
            "schema_version": "visiondata-gate.goal3-public-acceptance-summary.v1",
            "source_scope": "SYNTHETIC_FIXTURE_REPLAY_ONLY",
            "source_sets": {
                "cross_source_product_root_identity_claimed": False,
                "isolated_goal1_review_ui": {
                    "interaction_receipt_sha256": negative_manifest[
                        "interaction_receipt_sha256"
                    ],
                    "kind": "SEPARATE_ISOLATED_GOAL1_PRODUCT_ROOT",
                    "manifest_file_sha256": negative_manifest["file_sha256"],
                    "manifest_sha256": negative_manifest["declared_manifest_sha256"],
                    "positive_and_negative_receipts_same_source": True,
                    "raw_manifest_packaged": False,
                },
                "persistent_product_interaction": {
                    "interaction_receipt_sha256": interaction.receipt_sha256,
                    "kind": "PERSISTENT_SEMIFINAL_PRODUCT_ROOT",
                    "manifest_file_sha256": _sha256(manifest_raw),
                    "manifest_sha256": manifest_sha,
                    "raw_manifest_packaged": False,
                },
            },
            "status": {
                "capability": "PASS_LOCAL_CAPABILITY",
                "final_delivery": "NOT_A_RELEASE_DECISION",
                "public_evidence_integrity": "PASS_LOCAL_PUBLIC_EVIDENCE",
            },
            "worker_selection": {
                "agent_behavior_receipt_sha256": behavior.receipt_sha256,
                "competing_hypothesis_count": len(child_case.hypotheses),
                "hypothesis_status_counts": dict(sorted(hypothesis_counts.items())),
                "recommendation": child_case.recommendation,
                "rejected_worker_count": len(behavior.rejected),
                "root_cause_status": child_case.root_cause_status,
                "selected_worker_count": len(behavior.selected),
                "selection_receipt_sha256": selection.receipt_sha256,
                "status": child_case.status,
                "worker_budget": selection.worker_budget,
            },
        }
        acceptance_public = str(GOAL3_PUBLIC_ROOT / "goal3_acceptance_summary.json")
        _write_jcs(
            staging / "goal3_acceptance_summary.json",
            acceptance,
            public_path=acceptance_public,
        )
        os.replace(staging, output)

    return verify_goal3_public_evidence(project)


def verify_goal3_public_evidence(project_root: Path) -> dict[str, Any]:
    """Verify public JCS files, artifact bindings, screenshots, and boundaries."""

    project = project_root.resolve(strict=True)
    public_root = project / GOAL3_PUBLIC_ROOT
    _expect(public_root.is_dir(), "public Goal 3 evidence directory is missing")
    observed_files = {
        path.relative_to(project).as_posix()
        for path in public_root.rglob("*")
        if path.is_file()
    }
    _expect(
        observed_files == set(GOAL3_PUBLIC_REQUIRED_PATHS),
        "public Goal 3 evidence file set drifted",
    )

    parsed: dict[str, dict[str, Any]] = {}
    for name in GOAL3_PUBLIC_JSON_NAMES:
        relative = str(GOAL3_PUBLIC_ROOT / name)
        path = project / PurePosixPath(relative)
        payload, raw = _read_json_object(path)
        _expect(
            raw == canonical_jcs_bytes(payload),
            f"public JSON is not exact RFC 8785 JCS: {relative}",
        )
        _assert_public_json(relative, raw)
        parsed[name] = payload

    acceptance = parsed["goal3_acceptance_summary.json"]
    _expect(
        acceptance.get("source_scope") == "SYNTHETIC_FIXTURE_REPLAY_ONLY",
        "public source scope drifted",
    )
    boundaries = acceptance.get("boundaries")
    _expect(isinstance(boundaries, dict), "public acceptance boundaries are missing")
    for key in (
        "machine_write_permitted",
        "private_omni_data_included",
        "production_release_allowed",
        "submission_eligible",
    ):
        _expect(boundaries.get(key) is False, f"unsafe public boundary: {key}")
    _expect(
        boundaries.get("factory_shadow_metrics") == "NOT_MEASURED_PENDING_ADJUDICATION",
        "factory metric boundary drifted",
    )
    _expect(
        boundaries.get("industrial_effectiveness_status") == "NOT_EVALUATED",
        "industrial effectiveness boundary drifted",
    )
    status = acceptance.get("status")
    _expect(isinstance(status, dict), "public acceptance status is missing")
    _expect(
        status.get("final_delivery") == "NOT_A_RELEASE_DECISION",
        "Goal 3 subsystem summary attempted a release decision",
    )
    claim_boundary = acceptance.get("claim_boundary")
    _expect(
        isinstance(claim_boundary, str)
        and "not a standalone release decision" in claim_boundary,
        "Goal 3 release-decision boundary is missing",
    )
    source_sets = acceptance.get("source_sets")
    _expect(isinstance(source_sets, dict), "Goal 3 source-set boundary is missing")
    _expect(
        source_sets.get("cross_source_product_root_identity_claimed") is False,
        "Goal 3 falsely claimed cross-source ProductRoot identity",
    )
    persistent_source = source_sets.get("persistent_product_interaction")
    isolated_source = source_sets.get("isolated_goal1_review_ui")
    _expect(
        isinstance(persistent_source, dict) and isinstance(isolated_source, dict),
        "Goal 3 source-set summaries are incomplete",
    )
    public_manifest = parsed["semifinal_demo_manifest.json"]
    _expect(
        persistent_source.get("kind") == "PERSISTENT_SEMIFINAL_PRODUCT_ROOT"
        and persistent_source.get("manifest_file_sha256")
        == public_manifest.get("source_manifest_file_sha256")
        and persistent_source.get("manifest_sha256")
        == public_manifest.get("source_manifest_sha256"),
        "persistent ProductRoot source binding drifted",
    )
    _expect(
        isolated_source.get("kind") == "SEPARATE_ISOLATED_GOAL1_PRODUCT_ROOT"
        and isolated_source.get("positive_and_negative_receipts_same_source") is True
        and isolated_source.get("raw_manifest_packaged") is False,
        "isolated review UI source boundary drifted",
    )
    _expect(
        isolated_source.get("manifest_file_sha256")
        != persistent_source.get("manifest_file_sha256"),
        "isolated review UI source falsely matches the persistent ProductRoot",
    )

    bindings = acceptance.get("artifact_bindings")
    _expect(
        isinstance(bindings, list) and bindings, "public artifact bindings are missing"
    )
    bound_paths: set[str] = set()
    for binding in bindings:
        _expect(isinstance(binding, dict), "invalid public artifact binding")
        relative = str(binding.get("path"))
        _expect(
            relative not in bound_paths,
            f"duplicate public artifact binding: {relative}",
        )
        bound_paths.add(relative)
        path = project / PurePosixPath(relative)
        _expect(path.is_file(), f"bound public artifact is missing: {relative}")
        _expect(
            path.stat().st_size == binding.get("bytes"),
            f"bound artifact byte count drifted: {relative}",
        )
        _expect(
            sha256_file(path) == binding.get("sha256"),
            f"bound artifact SHA-256 drifted: {relative}",
        )

    expected_bound = {
        *DYNAMICBENCH_REPORT_PATHS,
        *(
            path
            for path in GOAL3_PUBLIC_REQUIRED_PATHS
            if not path.endswith("goal3_acceptance_summary.json")
        ),
    }
    _expect(bound_paths == expected_bound, "public artifact binding set drifted")

    negative = parsed["review_projection_negative_ui_summary.json"]
    _expect(
        negative.get("raw_receipt_packaged") is False,
        "raw negative receipt was marked packageable",
    )
    negative_source = negative.get("isolated_source")
    _expect(
        isinstance(negative_source, dict)
        and negative_source.get("cross_source_product_root_identity_claimed") is False
        and negative_source.get("kind") == "SEPARATE_ISOLATED_GOAL1_PRODUCT_ROOT"
        and negative_source.get("manifest_file_sha256")
        == isolated_source.get("manifest_file_sha256")
        and negative_source.get("manifest_sha256")
        == isolated_source.get("manifest_sha256")
        and negative_source.get("interaction_receipt_sha256")
        == isolated_source.get("interaction_receipt_sha256")
        and negative_source.get("raw_manifest_packaged") is False,
        "negative UI isolated-source binding drifted",
    )
    scenarios = negative.get("scenarios")
    _expect(
        isinstance(scenarios, list) and len(scenarios) == 5,
        "public negative scenario count drifted",
    )
    for scenario in scenarios:
        screenshot = scenario.get("screenshot")
        _expect(
            isinstance(screenshot, dict),
            "public negative screenshot binding is missing",
        )
        path = project / PurePosixPath(str(screenshot["path"]))
        info = inspect_public_png(path)
        for key in ("bytes", "height", "sha256", "width"):
            _expect(
                info[key] == screenshot.get(key), f"public screenshot {key} drifted"
            )

    return {
        "artifact_count": len(bindings) + 1,
        "goal3_acceptance_summary_sha256": sha256_file(
            public_root / "goal3_acceptance_summary.json"
        ),
        "json_count": len(GOAL3_PUBLIC_JSON_NAMES),
        "screenshot_count": len(GOAL3_PUBLIC_SCREENSHOT_NAMES),
        "status": "PASS_LOCAL_GOAL3_PUBLIC_EVIDENCE",
        "submission_eligible": False,
    }


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Build redacted RFC 8785 JCS Goal 3 evidence from local synthetic receipts."
    )
    parser.add_argument("--project-root", type=Path, default=Path.cwd())
    parser.add_argument("--product-root", type=Path, required=True)
    parser.add_argument("--negative-receipt", type=Path, required=True)
    parser.add_argument("--positive-receipt", type=Path, required=True)
    parser.add_argument("--positive-authority-screenshot", type=Path, required=True)
    parser.add_argument("--output-root", type=Path, required=True)
    parser.add_argument("--source-runtime-commit", required=True)
    parser.add_argument("--verify-only", action="store_true")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        if args.verify_only:
            result = verify_goal3_public_evidence(args.project_root)
        else:
            result = build_goal3_public_evidence(
                project_root=args.project_root,
                product_root=args.product_root,
                negative_receipt_path=args.negative_receipt,
                positive_receipt_path=args.positive_receipt,
                positive_authority_screenshot=args.positive_authority_screenshot,
                output_root=args.output_root,
                source_runtime_commit=args.source_runtime_commit,
            )
    except (Goal3PublicEvidenceError, OSError, ValueError) as exc:
        print(
            json.dumps(
                {
                    "error": str(exc),
                    "error_type": type(exc).__name__,
                    "status": "FAIL_CLOSED",
                    "submission_eligible": False,
                },
                ensure_ascii=False,
                sort_keys=True,
            )
        )
        return 2
    print(json.dumps(result, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())


__all__ = [
    "DYNAMICBENCH_REPORT_PATHS",
    "GOAL3_PUBLIC_JSON_NAMES",
    "GOAL3_PUBLIC_REQUIRED_PATHS",
    "GOAL3_PUBLIC_ROOT",
    "GOAL3_PUBLIC_SCREENSHOT_NAMES",
    "Goal3PublicEvidenceError",
    "build_goal3_public_evidence",
    "inspect_public_png",
    "verify_goal3_public_evidence",
]
