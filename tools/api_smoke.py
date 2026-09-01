#!/usr/bin/env python3
"""Exercise the public API through a real HTTP process and verify artifacts."""

from __future__ import annotations

import argparse
import base64
import hashlib
import io
import json
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any

from PIL import Image

from visiondata_gate.contracts import BatchContract


TERMINAL = {"COMPLETED", "FAILED", "ARCHIVED"}


def _request(
    base_url: str,
    path: str,
    *,
    actor: str | None = None,
    payload: dict[str, Any] | None = None,
    idempotency_key: str | None = None,
    method: str | None = None,
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
        f"{base_url.rstrip('/')}{path}",
        headers=headers,
        data=data,
        method=method,
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

    export_status, _, export_raw = _request(
        args.base_url,
        f"/v1/tasks/{task_id}/annotation-exports/cvat",
        actor=actor,
        method="POST",
    )
    assert export_status == 201, (export_status, export_raw[:500])
    export = _json(export_raw)
    bundle = export["bundle"]
    assert bundle["connector_state"] == "contract_ready_not_connected"
    assert bundle["external_connected"] is False
    annotation_task = next(
        item
        for item in bundle["tasks"]
        if item["eligible_for_annotation_return"] and item["sample_ids"]
    )
    sample = next(
        item
        for item in bundle["samples"]
        if item["internal_sample_id"] in annotation_task["sample_ids"]
    )
    contract = BatchContract()
    mask = io.BytesIO()
    Image.new(
        "L",
        (contract.thresholds.expected_width, contract.thresholds.expected_height),
        color=255,
    ).save(mask, format="PNG")
    import_payload = {
        "schema_version": "visiondata-gate.annotation-import.v1",
        "export_id": bundle["export_id"],
        "provider": "cvat",
        "revisions": [
            {
                "work_order_id": annotation_task["work_order_id"],
                "internal_sample_id": sample["internal_sample_id"],
                "external_sample_key": sample["external_sample_key"],
                "external_task_id": None,
                "source_image_sha256": sample["image_sha256"],
                "prior_annotation_sha256": sample["prior_annotation_sha256"],
                "annotation_version": f"api-smoke-v2-{task_id}",
                "annotation_content_base64": base64.b64encode(mask.getvalue()).decode(
                    "ascii"
                ),
            }
        ],
    }
    import_status, _, import_raw = _request(
        args.base_url,
        f"/v1/tasks/{task_id}/annotation-imports",
        actor=actor,
        payload=import_payload,
    )
    assert import_status == 200
    roundtrip = _json(import_raw)
    assert roundtrip["external_connected"] is False
    assert roundtrip["connector_state"] == "local_contract_verified"
    assert roundtrip["same_contract_recheck_performed"] is True
    assert roundtrip["original_input_unchanged"] is True

    roundtrips_status, _, roundtrips_raw = _request(
        args.base_url,
        f"/v1/tasks/{task_id}/annotation-roundtrips",
        actor=actor,
    )
    assert roundtrips_status == 200
    roundtrips = _json(roundtrips_raw)
    assert any(item["receipt_id"] == roundtrip["receipt_id"] for item in roundtrips)
    scorecard_status, _, scorecard_raw = _request(
        args.base_url,
        f"/v1/tasks/{task_id}/acceptance-scorecard",
        actor=actor,
        payload=None,
    )
    assert scorecard_status == 200
    scorecard = _json(scorecard_raw)
    assert scorecard["production_acceptance"] == "not_claimed"
    assert scorecard["external_connections"]["cvat"] == (
        "local_contract_verified_not_connected"
    )

    reverification_status, reverification_headers, reverification_raw = _request(
        args.base_url,
        f"/v1/tasks/{task_id}/reverifications",
        actor=actor,
        payload={
            "note": (
                "HTTP smoke 创建独立同合同复验 Run；不覆盖父裁决，等待人工计划批准。"
            )
        },
        idempotency_key=f"{idempotency_key}-reverification-v1",
        method="POST",
    )
    assert reverification_status == 202
    reverification = _json(reverification_raw)
    child_task_id = reverification["task_id"]
    assert reverification["execution_status"] == "PLANNED"
    assert reverification["plan_approval_required"] is True
    assert _header(reverification_headers, "Location") == (f"/v1/tasks/{child_task_id}")
    lineage_status, _, lineage_raw = _request(
        args.base_url,
        f"/v1/tasks/{child_task_id}/lineage",
        actor=actor,
    )
    assert lineage_status == 200
    lineage = _json(lineage_raw)
    assert lineage["root_task_id"] == task_id
    assert lineage["focus_task_id"] == child_task_id
    assert lineage["node_count"] == 2
    assert lineage["edge_count"] == 1
    assert lineage["edges"][0]["parent_evidence_sha256"] == evidence_sha256

    receipt = {
        "schema_version": "visiondata-gate.api-smoke.v2",
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
        "annotation_export_status": export_status,
        "annotation_connector_state": bundle["connector_state"],
        "annotation_import_status": import_status,
        "roundtrip_receipt_id": roundtrip["receipt_id"],
        "roundtrip_same_contract_recheck": roundtrip["same_contract_recheck_performed"],
        "scorecard_status": scorecard_status,
        "scorecard_production_acceptance": scorecard["production_acceptance"],
        "reverification_status": reverification_status,
        "reverification_child_task_id": child_task_id,
        "reverification_human_approval_required": True,
        "lineage_status": lineage_status,
        "lineage_node_count": lineage["node_count"],
        "lineage_edge_count": lineage["edge_count"],
        "lineage_contract_sha256": lineage["contract_sha256"],
        "lineage_report_sha256": lineage["report_sha256"],
        "lineage_parent_evidence_bound": True,
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
