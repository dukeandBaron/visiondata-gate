#!/usr/bin/env python3
"""Exercise the public API through a real HTTP process and verify artifacts."""

from __future__ import annotations

import argparse
import hashlib
import json
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any


TERMINAL = {"COMPLETED", "FAILED", "ARCHIVED"}


def _request(
    base_url: str,
    path: str,
    *,
    actor: str | None = None,
    payload: dict[str, Any] | None = None,
    idempotency_key: str | None = None,
) -> tuple[int, dict[str, str], bytes]:
    headers = {"Accept": "application/json"}
    if actor:
        headers["X-Actor-User-Id"] = actor
    if idempotency_key:
        headers["Idempotency-Key"] = idempotency_key
    data = None
    if payload is not None:
        headers["Content-Type"] = "application/json"
        data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    request = urllib.request.Request(
        f"{base_url.rstrip('/')}{path}", headers=headers, data=data
    )
    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            return response.status, dict(response.headers.items()), response.read()
    except urllib.error.HTTPError as error:
        return error.code, dict(error.headers.items()), error.read()


def _json(raw: bytes) -> Any:
    return json.loads(raw.decode("utf-8"))


def _header(headers: dict[str, str], name: str) -> str:
    folded = {key.casefold(): value for key, value in headers.items()}
    return folded[name.casefold()]


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--base-url", default="http://127.0.0.1:8787")
    parser.add_argument("--output", type=Path)
    parser.add_argument("--timeout-seconds", type=float, default=90.0)
    parser.add_argument("--idempotency-key", default="submission-api-smoke-20260813-v2")
    args = parser.parse_args()

    actor = "usr_local_demo"
    health_status, _, health_raw = _request(args.base_url, "/v1/health")
    health = _json(health_raw)
    assert health_status == 200
    assert health["production_ready"] is False
    assert health["agentteams_connection"] == "mapped_not_connected"

    openapi_status, _, openapi_raw = _request(args.base_url, "/openapi.json")
    paths = _json(openapi_raw)["paths"]
    assert openapi_status == 200
    assert "/v1/users" not in paths
    assert "post" not in paths["/v1/workspaces"]

    workspaces_status, _, workspaces_raw = _request(
        args.base_url, "/v1/workspaces", actor=actor
    )
    assert workspaces_status == 200
    workspace = _json(workspaces_raw)[0]
    projects_status, _, projects_raw = _request(
        args.base_url,
        f"/v1/projects?workspace_id={workspace['workspace_id']}",
        actor=actor,
    )
    assert projects_status == 200
    project = _json(projects_raw)[0]

    idempotency_key = args.idempotency_key
    task_payload = {
        "project_id": project["project_id"],
        "goal": "通过真实 HTTP API 运行审核闭环并校验证据摘要。",
        "seed": 20260813,
    }
    first_status, first_headers, first_raw = _request(
        args.base_url,
        "/v1/tasks",
        actor=actor,
        payload=task_payload,
        idempotency_key=idempotency_key,
    )
    first = _json(first_raw)
    assert first_status == 202
    task_id = first["task_id"]
    assert _header(first_headers, "Location") == f"/v1/tasks/{task_id}"
    second_status, _, second_raw = _request(
        args.base_url,
        "/v1/tasks",
        actor=actor,
        payload=task_payload,
        idempotency_key=idempotency_key,
    )
    assert second_status == 202
    assert _json(second_raw)["task_id"] == task_id

    deadline = time.monotonic() + args.timeout_seconds
    task = first
    while task["execution_status"] not in TERMINAL:
        if time.monotonic() >= deadline:
            raise TimeoutError(f"task {task_id} did not complete")
        time.sleep(0.25)
        task_status, _, task_raw = _request(
            args.base_url, f"/v1/tasks/{task_id}", actor=actor
        )
        assert task_status == 200
        task = _json(task_raw)
    assert task["execution_status"] == "COMPLETED", task

    events_status, _, events_raw = _request(
        args.base_url, f"/v1/tasks/{task_id}/events", actor=actor
    )
    events = _json(events_raw)
    assert events_status == 200
    assert events
    assert [item["sequence"] for item in events] == list(range(1, len(events) + 1))

    trace_status, trace_headers, trace = _request(
        args.base_url, f"/v1/tasks/{task_id}/trace", actor=actor
    )
    evidence_status, evidence_headers, evidence = _request(
        args.base_url, f"/v1/tasks/{task_id}/evidence", actor=actor
    )
    trace_sha256 = hashlib.sha256(trace).hexdigest()
    evidence_sha256 = hashlib.sha256(evidence).hexdigest()
    assert trace_status == 200
    assert evidence_status == 200
    assert trace_sha256 == task["trace_sha256"]
    assert evidence_sha256 == task["evidence_sha256"]
    assert _header(trace_headers, "ETag") == f'"{trace_sha256}"'
    assert _header(evidence_headers, "ETag") == f'"{evidence_sha256}"'
    assert _header(evidence_headers, "X-Evidence-SHA256") == evidence_sha256

    receipt = {
        "schema_version": "visiondata-gate.api-smoke.v1",
        "status": "PASS",
        "base_url": args.base_url,
        "task_id": task_id,
        "idempotency_verified": True,
        "event_count": len(events),
        "event_sequence_contiguous": True,
        "execution_status": task["execution_status"],
        "initial_decision": task["initial_decision"],
        "final_decision": task["final_decision"],
        "trace_sha256": trace_sha256,
        "evidence_sha256": evidence_sha256,
        "artifact_response_hashes_verified": True,
        "public_account_bootstrap_routes_absent": True,
        "production_ready": health["production_ready"],
        "agentteams_connection": health["agentteams_connection"],
        "boundary": "Local synthetic HTTP integration smoke; not customer or production deployment evidence.",
    }
    rendered = json.dumps(receipt, ensure_ascii=False, sort_keys=True, indent=2) + "\n"
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(rendered, encoding="utf-8", newline="\n")
    print(rendered, end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
