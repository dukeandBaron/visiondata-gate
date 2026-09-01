"""Read-only reviewer workbench backed by validated public evidence.

The server deliberately exposes a narrow UI contract.  It does not mount the
product workspace, accept credentials, mutate cases, or infer production state
from a successful HTTP response.  The external-model section reports only
secret-free configuration state; it never returns the API key.
"""

from __future__ import annotations

import hashlib
import json
import os
import urllib.parse
from collections import Counter
from collections.abc import Mapping
from pathlib import Path
from typing import Any

from fastapi import FastAPI, Request
from fastapi.responses import FileResponse, JSONResponse
from starlette.middleware.trustedhost import TrustedHostMiddleware

from .contracts import GateResult
from .release import SubmissionRelease, load_submission_release


PROJECT_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_FRONTEND_ROOT = PROJECT_ROOT / "reviewer_workbench"
DEFAULT_RELEASE_ROOT = PROJECT_ROOT / "evidence" / "submission" / "vdg-20260816-rc1"
DEFAULT_SYNTHETIC_ROOT = PROJECT_ROOT / "07_results" / "frozen_demo_20260809"

REVIEWER_FRONTEND_ROOT_ENV = "VISIONDATA_REVIEWER_FRONTEND_ROOT"
REVIEWER_RELEASE_ROOT_ENV = "VISIONDATA_REVIEWER_RELEASE_ROOT"
REVIEWER_SYNTHETIC_ROOT_ENV = "VISIONDATA_REVIEWER_SYNTHETIC_ROOT"

INCIDENT_MODEL_BASE_URL_ENV = "VISIONDATA_INCIDENT_MODEL_BASE_URL"
INCIDENT_MODEL_ENDPOINT_ENV = "VISIONDATA_INCIDENT_MODEL_ENDPOINT"
INCIDENT_MODEL_API_KEY_ENV = "VISIONDATA_INCIDENT_MODEL_API_KEY"
INCIDENT_MODEL_MODE_ENV = "VISIONDATA_INCIDENT_MODEL_MODE"

_PLACEHOLDER_SECRETS = {"", "YOUR_API_KEY", "REPLACE_ME", "<YOUR_API_KEY>"}
DEFAULT_REVIEWER_GATEWAY_BASE_URL = "https://gw.opentoken.io"


def _sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _sorted_json_bytes(value: object) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=False,
        allow_nan=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")


def _safe_external_model_status(environment: Mapping[str, str]) -> dict[str, Any]:
    """Return a secret-free provider status without making a network call."""

    mode = environment.get(INCIDENT_MODEL_MODE_ENV, "off").strip().casefold()
    raw_endpoint = environment.get(INCIDENT_MODEL_ENDPOINT_ENV, "").strip()
    configured_base_url = environment.get(INCIDENT_MODEL_BASE_URL_ENV, "").strip()
    raw_base_url = configured_base_url or DEFAULT_REVIEWER_GATEWAY_BASE_URL
    candidate = raw_endpoint or raw_base_url
    try:
        parsed = urllib.parse.urlsplit(candidate) if candidate else None
        base_url_parts = urllib.parse.urlsplit(raw_base_url) if raw_base_url else None
        parsed_hostname = parsed.hostname if parsed else None
        base_url_hostname = base_url_parts.hostname if base_url_parts else None
    except ValueError:
        parsed = None
        base_url_parts = None
        parsed_hostname = None
        base_url_hostname = None
    provider_host = ""
    candidate_is_secret_free = bool(
        parsed
        and parsed.scheme in {"http", "https"}
        and parsed_hostname
        and not parsed.username
        and not parsed.password
        and not parsed.query
        and not parsed.fragment
    )
    if candidate_is_secret_free and parsed_hostname:
        provider_host = parsed_hostname.casefold().rstrip(".")
    base_url_is_secret_free = bool(
        base_url_parts
        and base_url_parts.scheme in {"http", "https"}
        and base_url_hostname
        and not base_url_parts.username
        and not base_url_parts.password
        and not base_url_parts.query
        and not base_url_parts.fragment
    )
    raw_key = environment.get(INCIDENT_MODEL_API_KEY_ENV, "").strip()
    key_configured = raw_key not in _PLACEHOLDER_SECRETS
    configured = mode in {"shadow", "gated"} and bool(provider_host) and key_configured
    return {
        "provider_kind": "openai_compatible",
        "base_url": raw_base_url if base_url_is_secret_free else "",
        "base_url_source": "environment" if configured_base_url else "reserved_profile",
        "provider_host": provider_host,
        "mode": mode if mode in {"off", "shadow", "gated", "replay"} else "invalid",
        "key_configured": key_configured,
        "connection_status": (
            "CONFIGURED_NOT_PROBED" if configured else "NOT_CONFIGURED"
        ),
        "decision_authority": "none",
        "raw_key_exposed": False,
        "boundary": (
            "Configuration is not connectivity. REAL_BACKEND_CONNECTED requires a "
            "separate identity and transport receipt; the Frozen Policy Judge and "
            "named human authority are unchanged."
        ),
    }


def _load_synthetic_visual(
    synthetic_root: Path,
) -> tuple[dict[str, Any], Path, Path]:
    initial_result_path = synthetic_root / "evidence" / "initial" / "gate_result.json"
    repaired_result_path = synthetic_root / "evidence" / "repaired" / "gate_result.json"
    before_path = synthetic_root / "dataset" / "batch" / "images" / "q-blur.png"
    after_path = synthetic_root / "repaired_batch" / "images" / "q-blur.png"
    required = (
        initial_result_path,
        repaired_result_path,
        before_path,
        after_path,
    )
    if not all(path.is_file() for path in required):
        raise RuntimeError("Synthetic-v3 reviewer assets are incomplete")

    initial = GateResult.model_validate_json(
        initial_result_path.read_text(encoding="utf-8")
    )
    repaired = GateResult.model_validate_json(
        repaired_result_path.read_text(encoding="utf-8")
    )
    low_sharpness = next(
        finding for finding in initial.findings if finding.code == "LOW_SHARPNESS"
    )
    if any(finding.code == "LOW_SHARPNESS" for finding in repaired.findings):
        raise RuntimeError("Synthetic-v3 repaired result still contains LOW_SHARPNESS")
    evidence = dict(low_sharpness.evidence)
    before_sha256 = _sha256_bytes(before_path.read_bytes())
    after_sha256 = _sha256_bytes(after_path.read_bytes())
    return (
        {
            "evidence_class": "synthetic_injected_truth",
            "sample_id": "q-blur",
            "label": "Synthetic-v3 合成工程夹具",
            "initial_decision": initial.decision,
            "recheck_decision": repaired.decision,
            "truth_issue_count": 12,
            "f1": 1.0,
            "finding_code": low_sharpness.code,
            "measurement": {
                "algorithm": "Laplacian variance",
                "observed": evidence["sharpness"],
                "minimum": evidence["minimum"],
                "mean_luma": evidence["mean_luma"],
                "result": "LOW_SHARPNESS",
            },
            "before": {
                "url": "/api/reviewer/assets/before",
                "sha256": before_sha256,
                "caption": "整改前 · 合成模糊样本",
            },
            "after": {
                "url": "/api/reviewer/assets/after",
                "sha256": after_sha256,
                "caption": "整改副本 · 父来源未覆盖",
            },
            "boundary": (
                "This proves the deterministic repair/recheck path on injected "
                "truth. It is not factory accuracy, customer KPI, or model quality."
            ),
        },
        before_path,
        after_path,
    )


def _public_pilot_snapshot(
    release: SubmissionRelease, release_root: Path
) -> dict[str, Any]:
    omni = release.manifest["evidence_namespaces"]["Omni-180-v1"]
    finding_counts = Counter(
        str(finding.code) for finding in release.omni_gate_result.findings
    )
    tool_trace = [
        {
            "sequence": trace.sequence,
            "tool": str(trace.tool),
            "status": str(trace.status),
            "finding_count": len(trace.finding_ids),
            "input_sha256": trace.input_sha256,
            "result_sha256": trace.result_sha256,
            "contract_version": trace.contract_version,
            "adapter": trace.adapter,
        }
        for trace in release.omni_gate_result.tool_trace
    ]
    work_orders = [
        {
            "work_order_id": order.work_order_id,
            "action": str(order.action),
            "priority": str(order.priority),
            "reason_codes": [str(code) for code in order.reason_codes],
            "status": str(order.status),
        }
        for order in release.omni_gate_result.work_orders[:6]
    ]
    dynamic_tasks = [
        {
            "task_id": task["task_id"],
            "worker_id": task["worker_id"],
            "trigger": task["trigger"],
            "decision_effect": task["decision_effect"],
            "status": task["status"],
            "result_sha256": task["result_sha256"],
            "planned_before_initial_evidence": task["planned_before_initial_evidence"],
        }
        for task in release.dynamic_leader_plan["dynamic_tasks"]
    ]
    gate_path = release_root / "omni_gate_result.json"
    return {
        "release_id": release.manifest["release_id"],
        "evidence_namespace": "Omni-180-v1",
        "evidence_class": omni["evidence_class"],
        "decision": omni["decision"],
        "fixed_image_denominator": omni["selected_image_count"],
        "source_tree_image_count": omni["source_tree_image_count"],
        "source_tree_mask_count": omni["source_tree_mask_count"],
        "finding_count": omni["finding_count"],
        "work_order_count": omni["work_order_count"],
        "rule_check_count": omni["rule_check_count"],
        "replan_count": omni["replan_count"],
        "dynamic_worker_count": omni["worker_count"],
        "finding_counts": dict(sorted(finding_counts.items())),
        "tool_trace": tool_trace,
        "dynamic_tasks": dynamic_tasks,
        "work_order_preview": work_orders,
        "gate_result_sha256": _sha256_bytes(gate_path.read_bytes()),
        "actual_model_call_count": 0,
        "claim_boundary": omni["claim_boundary"],
    }


def build_reviewer_snapshot(
    *,
    release_root: Path = DEFAULT_RELEASE_ROOT,
    synthetic_root: Path = DEFAULT_SYNTHETIC_ROOT,
    environment: Mapping[str, str] | None = None,
) -> tuple[dict[str, Any], Path, Path]:
    """Build the browser contract from validated, redacted evidence."""

    release = load_submission_release(release_root)
    synthetic, before_path, after_path = _load_synthetic_visual(synthetic_root)
    snapshot: dict[str, Any] = {
        "schema_version": "visiondata-gate.reviewer-workbench.v1",
        "mode": "READ_ONLY_REVIEWER",
        "product": {
            "name": "VisionData Gate",
            "title": "换型后视觉异常处置与独立复验工作台",
            "deployment": "LOCAL_OR_ON_PREM",
            "device_control": False,
            "production_decision_authority": "HUMAN_ONLY",
        },
        "case": {
            "case_id": "rc3-05-redacted-summary",
            "display_name": "换型异常 · Parent / Child 复验",
            "evidence_class": "LOCAL_AUTHORIZED_REDACTED_SUMMARY",
            "status": "HOLD",
            "root_cause_status": "NOT_ESTABLISHED",
            "owner": "具名质量负责人（公开视图脱敏）",
            "production_release_allowed": False,
            "parent": {"version": "v1", "decision": "RECAPTURE", "findings": 49},
            "capa": {
                "selected_work_orders": 49,
                "approval_authority": "NAMED_HUMAN_ONLY",
                "parent_mutated": False,
            },
            "derived": {"images": 180, "masks": 60, "private": True},
            "child": {
                "version": "v2",
                "findings": 33,
                "verified_closed": 6,
                "open_responsibilities": 43,
                "status": "TRANSFERRED_TO_INVESTIGATION",
            },
            "boundary": (
                "Finding reduction is not root-cause proof or production recovery. "
                "The redacted summary contains no original images, class names, "
                "filenames, or private paths."
            ),
        },
        "public_pilot": _public_pilot_snapshot(release, release_root),
        "synthetic_visual": synthetic,
        "architecture_control": {
            "record_count": 288,
            "fixed_sop_multi_agent_necessity_supported": False,
            "actual_model_call_count": 0,
        },
        "phases": [
            {"id": "evidence", "label": "证据资格化", "status": "COMPLETED"},
            {"id": "replan", "label": "动态补证", "status": "COMPLETED"},
            {"id": "decision", "label": "人工决定", "status": "HOLD"},
            {
                "id": "recheck",
                "label": "Child Run 复验",
                "status": "COMPLETED_WITH_OPEN_RESPONSIBILITIES",
            },
        ],
        "runtime": {
            "planner_mode": "GATED",
            "tool_access": "READ_ONLY",
            "model_call_count_in_frozen_pilot": 0,
            "chain_of_thought_exposed": False,
            "reason_trace_available": True,
            "signature": "NOT_CONFIGURED",
            "trusted_timestamp": "NOT_CONFIGURED",
            "external_anchor": "NOT_CONFIGURED",
        },
        "external_model": _safe_external_model_status(
            os.environ if environment is None else environment
        ),
        "boundary": (
            "Reviewer Workbench is a read-only projection of validated public "
            "evidence plus a redacted local case summary. It is not an official "
            "submission receipt, customer acceptance, factory deployment, or "
            "production authorization."
        ),
    }
    snapshot_sha256 = _sha256_bytes(_sorted_json_bytes(snapshot))
    snapshot["snapshot_integrity"] = {
        "algorithm": "sha256",
        "serialization": "sorted-json-v1",
        "sha256": snapshot_sha256,
        "signature": "NOT_CONFIGURED",
    }
    return snapshot, before_path, after_path


def _configured_path(environment: Mapping[str, str], name: str, default: Path) -> Path:
    configured = environment.get(name, "").strip()
    return Path(configured).resolve() if configured else default.resolve()


def create_reviewer_app() -> FastAPI:
    environment = os.environ
    frontend_root = _configured_path(
        environment, REVIEWER_FRONTEND_ROOT_ENV, DEFAULT_FRONTEND_ROOT
    )
    release_root = _configured_path(
        environment, REVIEWER_RELEASE_ROOT_ENV, DEFAULT_RELEASE_ROOT
    )
    synthetic_root = _configured_path(
        environment, REVIEWER_SYNTHETIC_ROOT_ENV, DEFAULT_SYNTHETIC_ROOT
    )
    required_frontend = tuple(
        frontend_root / name for name in ("index.html", "styles.css", "app.js")
    )
    if not all(path.is_file() for path in required_frontend):
        raise RuntimeError("Reviewer Workbench frontend is incomplete")
    snapshot, before_path, after_path = build_reviewer_snapshot(
        release_root=release_root,
        synthetic_root=synthetic_root,
        environment=environment,
    )
    snapshot_sha256 = snapshot["snapshot_integrity"]["sha256"]

    app = FastAPI(
        title="VisionData Gate Reviewer Workbench",
        docs_url=None,
        redoc_url=None,
        openapi_url=None,
    )
    app.add_middleware(
        TrustedHostMiddleware,
        allowed_hosts=["127.0.0.1", "localhost", "testserver"],
    )

    @app.middleware("http")
    async def reviewer_security_headers(request: Request, call_next: Any):
        response = await call_next(request)
        response.headers["Cache-Control"] = "no-store"
        response.headers["Content-Security-Policy"] = (
            "default-src 'self'; img-src 'self' data:; style-src 'self'; "
            "script-src 'self'; connect-src 'self'; frame-ancestors 'none'; "
            "base-uri 'none'; form-action 'none'"
        )
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["X-Frame-Options"] = "DENY"
        response.headers["Referrer-Policy"] = "no-referrer"
        response.headers["Permissions-Policy"] = (
            "camera=(), microphone=(), geolocation=(), payment=()"
        )
        return response

    @app.get("/", include_in_schema=False)
    def reviewer_index() -> FileResponse:
        return FileResponse(frontend_root / "index.html", media_type="text/html")

    @app.get("/styles.css", include_in_schema=False)
    def reviewer_styles() -> FileResponse:
        return FileResponse(frontend_root / "styles.css", media_type="text/css")

    @app.get("/app.js", include_in_schema=False)
    def reviewer_script() -> FileResponse:
        return FileResponse(
            frontend_root / "app.js", media_type="application/javascript"
        )

    @app.get("/api/reviewer/snapshot", include_in_schema=False)
    def reviewer_snapshot() -> JSONResponse:
        return JSONResponse(
            snapshot,
            headers={
                "ETag": f'"{snapshot_sha256}"',
                "X-Evidence-SHA256": snapshot_sha256,
            },
        )

    def evidence_image(path: Path, sha256: str) -> FileResponse:
        return FileResponse(
            path,
            media_type="image/png",
            headers={"ETag": f'"{sha256}"', "X-Evidence-SHA256": sha256},
        )

    @app.get("/api/reviewer/assets/before", include_in_schema=False)
    def reviewer_before() -> FileResponse:
        return evidence_image(
            before_path, snapshot["synthetic_visual"]["before"]["sha256"]
        )

    @app.get("/api/reviewer/assets/after", include_in_schema=False)
    def reviewer_after() -> FileResponse:
        return evidence_image(
            after_path, snapshot["synthetic_visual"]["after"]["sha256"]
        )

    @app.get("/health", include_in_schema=False)
    def reviewer_health() -> dict[str, Any]:
        return {
            "ok": True,
            "mode": "READ_ONLY_REVIEWER",
            "release_id": snapshot["public_pilot"]["release_id"],
            "snapshot_sha256": snapshot_sha256,
            "submission_eligible": False,
        }

    return app


__all__ = ["build_reviewer_snapshot", "create_reviewer_app"]
