#!/usr/bin/env python3
"""Prepare an isolated, idempotent reviewer project for the real Web workbench.

This is product/demo preparation code, not a test runner.  It exercises the
normal ProductService, deterministic Agent runtime, Incident command ledger,
named-human gate, immutable resume path, and interaction receipt.  All seeded
industrial inputs are explicitly marked as synthetic fixture replay.
"""

from __future__ import annotations

import argparse
import hashlib
import io
import json
from pathlib import Path

from PIL import Image, ImageDraw, ImageFilter

from visiondata_gate.demo_fixtures import build_fixture_industrial_incident_request
from visiondata_gate.evidence import canonical_json_bytes, write_canonical_json
from visiondata_gate.industrial_incident import (
    IncidentHumanDecision,
    IndustrialIncidentDecisionRequest,
)
from visiondata_gate.operator_workspace import OperatorImageStore
from visiondata_gate.product_models import (
    CreateTaskRequest,
    DataSourceKind,
    TaskExecutionStatus,
)
from visiondata_gate.product_service import ProductService
from visiondata_gate.semifinal_manifest import SEMIFINAL_MANIFEST_CLAIM_BOUNDARY


ACTOR_ID = "usr_local_demo"
TASK_KEY = "semifinal-review-task-v1"
PARENT_CASE_KEY = "semifinal-review-incident-parent-v1"
DECISION_KEY = "semifinal-review-human-decision-v1"
RESUME_KEY = "semifinal-review-incident-resume-v1"


def _fixture_image_bytes(*, repaired: bool) -> bytes:
    canvas = Image.new("RGB", (720, 440), (12, 17, 24))
    draw = ImageDraw.Draw(canvas)
    draw.rounded_rectangle(
        (105, 72, 615, 368),
        radius=34,
        fill=(78, 88, 99),
        outline=(178, 191, 204),
        width=4,
    )
    draw.ellipse(
        (256, 120, 464, 328), fill=(31, 37, 45), outline=(218, 226, 234), width=5
    )
    draw.ellipse(
        (314, 178, 406, 270), fill=(118, 128, 136), outline=(231, 237, 242), width=4
    )
    defect_box = (387, 126, 502, 222)
    draw.rectangle(
        defect_box, outline=(72, 220, 157) if repaired else (255, 102, 102), width=6
    )
    draw.line((408, 157, 477, 194), fill=(230, 117, 83), width=7)
    draw.line((412, 195, 471, 151), fill=(230, 117, 83), width=5)
    if not repaired:
        canvas = canvas.filter(ImageFilter.GaussianBlur(radius=5.0))
        overlay = ImageDraw.Draw(canvas)
        overlay.rectangle(defect_box, outline=(255, 102, 102), width=6)
    buffer = io.BytesIO()
    canvas.save(buffer, format="PNG", optimize=False)
    return buffer.getvalue()


def _ensure_visual_assets(
    store: OperatorImageStore,
    *,
    workspace_id: str,
    project_id: str,
) -> list[dict[str, object]]:
    expected = [
        ("synthetic-fixture-before.png", _fixture_image_bytes(repaired=False)),
        ("synthetic-fixture-recheck.png", _fixture_image_bytes(repaired=True)),
    ]
    existing = store.list_assets(ACTOR_ID, workspace_id, project_id=project_id)
    by_sha: dict[str, list[object]] = {}
    for asset in existing:
        by_sha.setdefault(asset.source_sha256, []).append(asset)

    for filename, data in expected:
        digest = hashlib.sha256(data).hexdigest()
        matches = by_sha.get(digest, [])
        if len(matches) > 1:
            raise RuntimeError(
                f"isolated demo contains duplicate seeded asset digest: {digest}"
            )
        if not matches:
            asset = store.add_image(
                ACTOR_ID,
                workspace_id,
                project_id=project_id,
                filename=filename,
                data=data,
            )
            by_sha[digest] = [asset]

    resolved = store.list_assets(ACTOR_ID, workspace_id, project_id=project_id)
    expected_shas = {
        hashlib.sha256(data).hexdigest(): filename for filename, data in expected
    }
    selected = [item for item in resolved if item.source_sha256 in expected_shas]
    if len(selected) != len(expected):
        raise RuntimeError("isolated demo visual assets are incomplete")
    return [
        {
            "asset_id": item.asset_id,
            "filename": expected_shas[item.source_sha256],
            "source_sha256": item.source_sha256,
            "preview_sha256": item.preview_sha256,
            "width": item.width,
            "height": item.height,
        }
        for item in sorted(selected, key=lambda value: value.source_sha256)
    ]


def prepare_demo(product_root: Path) -> dict[str, object]:
    product_root = product_root.expanduser().resolve()
    service = ProductService(product_root, recover_interrupted=False)
    try:
        user, workspace, project = service.ensure_default_tenant()
        if user.user_id != ACTOR_ID:
            raise RuntimeError("default demo actor identity drifted")
        if project.source_kind is not DataSourceKind.SYNTHETIC_DEMO:
            raise RuntimeError(
                "isolated semifinal demo must remain a synthetic_demo project"
            )

        visual_assets = _ensure_visual_assets(
            OperatorImageStore(product_root / "operator_workspace"),
            workspace_id=workspace.workspace_id,
            project_id=project.project_id,
        )
        task = service.create_task(
            ACTOR_ID,
            CreateTaskRequest(
                project_id=project.project_id,
                goal=(
                    "在冻结合成数据上执行确定性视觉治理，并演示 Agent 暂停、"
                    "具名人工决定与不可变 Child Case 续跑。"
                ),
                seed=20_260_809,
                plan_approval_required=False,
                allowed_tools=[
                    "image_quality",
                    "duplicate_leakage",
                    "annotation_integrity",
                    "coverage_matrix",
                    "governance_audit",
                ],
            ),
            idempotency_key=TASK_KEY,
            auto_start=False,
        )
        if task.execution_status not in {
            TaskExecutionStatus.COMPLETED,
            TaskExecutionStatus.ARCHIVED,
        }:
            task = service.run_task_sync(task.task_id)
        if task.execution_status is not TaskExecutionStatus.COMPLETED:
            raise RuntimeError(
                f"semifinal demo task did not complete: {task.execution_status.value}"
            )

        parent_request = build_fixture_industrial_incident_request(revision=1)
        parent = service.create_industrial_incident_case(
            ACTOR_ID,
            task.task_id,
            parent_request,
            idempotency_key=PARENT_CASE_KEY,
        )
        decision = service.record_industrial_incident_decision(
            ACTOR_ID,
            task.task_id,
            parent.case_id,
            IndustrialIncidentDecisionRequest(
                bound_case_sha256=parent.case_sha256,
                decision=IncidentHumanDecision.CONTINUE_HOLD,
                note=(
                    "已复核冻结 fixture 的证据边界；继续 HOLD，并仅用新的"
                    "已授权离线证据创建 Child Case。"
                ),
                operator_attests_reviewed_evidence=True,
            ),
            idempotency_key=DECISION_KEY,
        )
        child_request = build_fixture_industrial_incident_request(
            revision=2
        ).model_copy(
            update={
                "supersedes_case_id": parent.case_id,
                "expected_parent_case_sha256": parent.case_sha256,
                "authorizing_decision_id": decision.decision_id,
            }
        )
        child = service.resume_industrial_incident_case(
            ACTOR_ID,
            task.task_id,
            parent.case_id,
            child_request,
            idempotency_key=RESUME_KEY,
        )
        interaction = service.get_industrial_incident_interaction_receipt(
            ACTOR_ID,
            task.task_id,
            child.case_id,
        )
        readiness = service.task_release_readiness(ACTOR_ID, task.task_id)
        events = service.list_events(ACTOR_ID, task.task_id)

        if task.final_decision != "PASS":
            raise RuntimeError(
                "semifinal demo task must retain the frozen PASS decision"
            )
        if readiness.overall_status != "DEMO_ONLY":
            raise RuntimeError(
                "semifinal demo release readiness must remain explicitly DEMO_ONLY"
            )
        if child.recommendation.value != "CONTINUE_HOLD":
            raise RuntimeError("semifinal demo child incident must continue HOLD")

        stable: dict[str, object] = {
            "schema_version": "visiondata-gate.semifinal-demo-manifest.v1",
            "status": "PASS_LOCAL_DEMO_PREPARED",
            "source_scope": "SYNTHETIC_FIXTURE_REPLAY_ONLY",
            "product_root": product_root.as_posix(),
            "actor_user_id": ACTOR_ID,
            "workspace_id": workspace.workspace_id,
            "project_id": project.project_id,
            "project_source_kind": project.source_kind.value,
            "task_id": task.task_id,
            "review_start_path": f"/review?task={task.task_id}",
            "task_request_sha256": task.request_sha256,
            "task_evidence_sha256": task.evidence_sha256,
            "task_execution_status": task.execution_status.value,
            "task_final_decision": task.final_decision,
            "task_release_readiness_status": readiness.overall_status,
            "task_release_readiness_sha256": readiness.report_sha256,
            "event_count": len(events),
            "parent_case_id": parent.case_id,
            "parent_case_sha256": parent.case_sha256,
            "decision_id": decision.decision_id,
            "decision_sha256": decision.decision_sha256,
            "decision_kind": decision.decision.value,
            "child_case_id": child.case_id,
            "child_case_sha256": child.case_sha256,
            "child_incident_status": child.status.value,
            "child_incident_recommendation": child.recommendation.value,
            "interaction_id": interaction.interaction_id,
            "interaction_receipt_sha256": interaction.receipt_sha256,
            "interaction_status": interaction.interaction_status,
            "remaining_open_question_count": (
                interaction.remaining_open_question_count
            ),
            "visual_assets": visual_assets,
            "production_release_allowed": False,
            "machine_write_permitted": False,
            "customer_validation": "NOT_CLAIMED",
            "factory_shadow_metrics": "NOT_MEASURED_PENDING_ADJUDICATION",
            "claim_boundary": SEMIFINAL_MANIFEST_CLAIM_BOUNDARY,
        }
        manifest_sha256 = hashlib.sha256(canonical_json_bytes(stable)).hexdigest()
        manifest = {**stable, "manifest_sha256": manifest_sha256}
        write_canonical_json(product_root / "semifinal_demo_manifest.json", manifest)
        return manifest
    finally:
        service.close(wait=True)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--product-root",
        type=Path,
        default=Path("output") / "semifinal_demo" / "product",
    )
    args = parser.parse_args()
    manifest = prepare_demo(args.product_root)
    print(json.dumps(manifest, ensure_ascii=False, sort_keys=True, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
