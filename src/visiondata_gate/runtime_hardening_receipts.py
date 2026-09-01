"""Aggregate per-Council safety receipts into run-level evidence artifacts."""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any

from .model_backends import CouncilBuild


PhaseBuild = tuple[str, CouncilBuild]


def build_model_transport_runtime_receipt(
    phases: Sequence[PhaseBuild],
) -> dict[str, Any]:
    records: list[dict[str, Any]] = []
    for phase, build in phases:
        records.extend(
            {"phase": phase, **item.model_dump(mode="json")}
            for item in build.transport_receipts
        )
    failure_statuses = {
        "TIMEOUT",
        "HTTP_ERROR",
        "TRANSPORT_ERROR",
        "REDIRECT_BLOCKED",
        "INVALID_RESPONSE",
        "CIRCUIT_OPEN",
    }
    failed = sum(item["status"] in failure_statuses for item in records)
    recovered = sum(item["status"] == "RECOVERED" for item in records)
    status = (
        "NOT_ATTEMPTED" if not records else "DEGRADED" if failed else "PASS_RUNTIME"
    )
    return {
        "schema_version": "visiondata-gate.model-transport-runtime.v1",
        "status": status,
        "request_count": len(records),
        "failed_request_count": failed,
        "recovered_request_count": recovered,
        "timeout_count": sum(item["status"] == "TIMEOUT" for item in records),
        "circuit_open_count": sum(item["status"] == "CIRCUIT_OPEN" for item in records),
        "redirect_block_count": sum(
            item["status"] == "REDIRECT_BLOCKED" for item in records
        ),
        "requests": records,
        "secrets_retained": False,
        "boundary_notice": (
            "This receipt describes only transport calls made by this run. The separate "
            "network-resilience evaluation exercises forced timeout and automatic recovery."
        ),
    }


def build_prompt_guard_runtime_receipt(phases: Sequence[PhaseBuild]) -> dict[str, Any]:
    records = [
        {
            "phase": phase,
            **build.prompt_injection_receipt.model_dump(mode="json"),
        }
        for phase, build in phases
        if build.prompt_injection_receipt is not None
    ]
    statuses = {item["status"] for item in records}
    status = (
        "BLOCKED_LOCAL_RULESET"
        if "BLOCKED_LOCAL_RULESET" in statuses
        else "CLEAR_LOCAL_RULESET"
        if "CLEAR_LOCAL_RULESET" in statuses
        else "NOT_APPLICABLE_NO_MODEL_CALL"
    )
    return {
        "schema_version": "visiondata-gate.prompt-injection-runtime.v1",
        "status": status,
        "phase_count": len(records),
        "scanned_item_count": sum(item["scanned_item_count"] for item in records),
        "blocked_item_count": sum(item["blocked_item_count"] for item in records),
        "remote_model_call_blocked": status == "BLOCKED_LOCAL_RULESET",
        "decision_authority": "frozen_policy_judge_unchanged",
        "phases": records,
        "boundary_notice": (
            "This runtime receipt is not the fixed attack-set evaluation and does not "
            "establish universal prompt-injection protection."
        ),
    }


def build_backend_identity_runtime_receipt(
    phases: Sequence[PhaseBuild],
) -> dict[str, Any]:
    records = [
        {
            "phase": phase,
            **build.backend_identity_receipt.model_dump(mode="json"),
        }
        for phase, build in phases
        if build.backend_identity_receipt is not None
    ]
    statuses = {item["status"] for item in records}
    if statuses and statuses <= {"NOT_APPLICABLE"}:
        status = "NOT_APPLICABLE_DETERMINISTIC"
    elif "REAL_BACKEND_CONNECTED" in statuses:
        status = "REAL_BACKEND_CONNECTED"
    elif "CONTRACT_CONNECTED_LOCAL_TEST" in statuses:
        status = "CONTRACT_CONNECTED_LOCAL_TEST"
    elif "BACKEND_RESPONDED_IDENTITY_UNVERIFIED" in statuses:
        status = "BACKEND_RESPONDED_IDENTITY_UNVERIFIED"
    else:
        status = "REAL_BACKEND_NOT_CONNECTED"
    return {
        "schema_version": "visiondata-gate.backend-identity-runtime.v1",
        "status": status,
        "phase_count": len(records),
        "real_backend_connected": status == "REAL_BACKEND_CONNECTED",
        "contract_test_connected": status == "CONTRACT_CONNECTED_LOCAL_TEST",
        "phases": records,
        "boundary_notice": (
            "Code availability, a configured token, or a contract fixture is not a real "
            "backend connection. Endpoint-reported identity is not a checkpoint hash."
        ),
    }


__all__ = [
    "build_backend_identity_runtime_receipt",
    "build_model_transport_runtime_receipt",
    "build_prompt_guard_runtime_receipt",
]
