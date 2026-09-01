"""Run a new path-redacted product pilot from an existing local authorization.

The script reuses only an operator-attested authorization stored in a previous
local product state. It never copies source assets and never serializes the
server-local source path into the new evidence package or pilot receipt.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sqlite3
import zipfile

from visiondata_gate.evidence import sha256_file, write_canonical_json
from visiondata_gate.product_models import (
    AuthorizeLocalSourceRequest,
    CreateProjectRequest,
    CreateTaskRequest,
    CreateUserRequest,
    CreateWorkspaceRequest,
    DataSourceKind,
    LocalSourceAuthorizationReceipt,
    TaskExecutionStatus,
    TaskInterventionAction,
    TaskInterventionRequest,
)
from visiondata_gate.product_service import ProductService
from visiondata_gate.task_store import LocalSourceBinding


def _arguments() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--source-product-root",
        type=Path,
        required=True,
        help="Existing local product root containing product.sqlite3.",
    )
    parser.add_argument(
        "--source-id",
        help="Existing active source ID. Omit only when exactly one is active.",
    )
    parser.add_argument("--output-root", type=Path, required=True)
    parser.add_argument("--seed", type=int, default=20_260_825)
    parser.add_argument(
        "--goal",
        default=(
            "审核授权工业视觉数据，依据中间证据动态补证，生成可执行工单与工业交付回执。"
        ),
    )
    return parser.parse_args()


def _select_source(connection: sqlite3.Connection, requested: str | None) -> str:
    rows = connection.execute(
        """
        SELECT source_id FROM local_source_authorizations
        WHERE status = 'active' ORDER BY created_at DESC, source_id DESC
        """
    ).fetchall()
    source_ids = [str(row[0]) for row in rows]
    if requested is not None:
        if requested not in source_ids:
            raise RuntimeError("requested active source authorization was not found")
        return requested
    if len(source_ids) != 1:
        raise RuntimeError(
            "--source-id is required unless exactly one source is active"
        )
    return source_ids[0]


def _load_source_binding_readonly(
    database: Path, requested: str | None
) -> LocalSourceBinding:
    database_uri = f"file:{database.as_posix()}?mode=ro"
    with sqlite3.connect(database_uri, uri=True) as connection:
        connection.row_factory = sqlite3.Row
        source_id = _select_source(connection, requested)
        row = connection.execute(
            "SELECT * FROM local_source_authorizations WHERE source_id = ?",
            (source_id,),
        ).fetchone()
    if row is None:
        raise RuntimeError("active source authorization disappeared during read")
    receipt = LocalSourceAuthorizationReceipt(
        source_id=str(row["source_id"]),
        workspace_id=str(row["workspace_id"]),
        adapter_kind=str(row["adapter_kind"]),
        display_name=str(row["display_name"]),
        root_path_sha256=str(row["root_path_sha256"]),
        source_archive_sha256=str(row["source_archive_sha256"]),
        purpose=str(row["purpose"]),
        rights_basis=str(row["rights_basis"]),
        residency=str(row["residency"]),
        operator_attests_authorized_use=bool(row["operator_attests_authorized_use"]),
        read_only=bool(row["read_only"]),
        raw_redistribution_allowed=bool(row["raw_redistribution_allowed"]),
        data_profile=json.loads(str(row["data_profile_json"])),
        status=str(row["status"]),
        created_at=str(row["created_at"]),
    )
    return LocalSourceBinding(
        receipt=receipt,
        root_path=Path(str(row["root_path"])).resolve(strict=False),
    )


def main() -> int:
    args = _arguments()
    source_product_root = args.source_product_root.expanduser().resolve(strict=True)
    source_database = source_product_root / "product.sqlite3"
    if not source_database.is_file():
        raise RuntimeError("source product database was not found")
    output_root = args.output_root.expanduser().resolve(strict=False)
    if output_root.exists():
        raise RuntimeError(
            "output root already exists; immutable pilot will not overwrite it"
        )

    source_database_sha256 = sha256_file(source_database)
    binding = _load_source_binding_readonly(source_database, args.source_id)
    source_root = binding.root_path.resolve(strict=True)
    try:
        output_root.relative_to(source_root)
    except ValueError:
        pass
    else:
        raise RuntimeError("output root must not be inside the authorized source")

    product_root = output_root / "saas_state"
    service = ProductService(
        product_root,
        recover_interrupted=False,
        local_source_allow_roots=[source_root],
    )
    try:
        user = service.create_user(CreateUserRequest(display_name="RC3 Pilot Operator"))
        workspace = service.create_workspace(
            CreateWorkspaceRequest(
                name="RC3 Industrial Evidence",
                owner_user_id=user.user_id,
            )
        )
        authorization = service.authorize_local_source(
            user.user_id,
            AuthorizeLocalSourceRequest(
                workspace_id=workspace.workspace_id,
                display_name=binding.receipt.display_name,
                root_path=str(source_root),
                source_archive_sha256=binding.receipt.source_archive_sha256,
                adapter_kind=binding.receipt.adapter_kind,
                purpose=binding.receipt.purpose,
                rights_basis=binding.receipt.rights_basis,
                residency=binding.receipt.residency,
                operator_attests_authorized_use=True,
            ),
        )
        project = service.create_project(
            user.user_id,
            CreateProjectRequest(
                workspace_id=workspace.workspace_id,
                name="Industrial Vision Release Gate",
                description="Read-only, evidence-first product pilot.",
                source_kind=DataSourceKind.LOCAL_AUTHORIZED_DIRECTORY,
            ),
        )
        task = service.create_task(
            user.user_id,
            CreateTaskRequest(
                project_id=project.project_id,
                goal=args.goal,
                seed=args.seed,
                source_kind=DataSourceKind.LOCAL_AUTHORIZED_DIRECTORY,
                source_id=authorization.source_id,
                plan_approval_required=True,
            ),
            auto_start=True,
        )
        preview = service.task_plan_preview(user.user_id, task.task_id)
        approval = service.intervene_task(
            user.user_id,
            task.task_id,
            TaskInterventionRequest(
                action=TaskInterventionAction.APPROVE_PLAN,
                note="已核对只读范围、工具权限、补证预算与生产人工审批边界。",
            ),
        )
        service.close(wait=True)
        completed = service.get_task(user.user_id, task.task_id)
        if completed.execution_status is not TaskExecutionStatus.COMPLETED:
            raise RuntimeError(
                f"product pilot did not complete: {completed.execution_status.value}"
            )
        review = service.intervene_task(
            user.user_id,
            task.task_id,
            TaskInterventionRequest(
                action=TaskInterventionAction.ACKNOWLEDGE_RESULT,
                note="已审阅最终裁决、证据引用、工单和安全边界。",
            ),
        )
        delivery = service.industrial_delivery_receipt(user.user_id, task.task_id)
        evidence_path = service.evidence_path(user.user_id, task.task_id)
        with zipfile.ZipFile(evidence_path) as archive:
            bad_member = archive.testzip()
            if bad_member is not None:
                raise RuntimeError("evidence ZIP integrity check failed")
            evidence_members = sorted(archive.namelist())
            source_profile = json.loads(archive.read("source_profile.json"))
            gate_result = json.loads(archive.read("gate_result.json"))
            dynamic_plan = json.loads(archive.read("dynamic_leader_plan.json"))
            embedded_timeline = json.loads(
                archive.read("task_intervention_timeline.json")
            )

        pilot_receipt = {
            "schema_version": "visiondata-gate.authorized-product-pilot.v2",
            "task_id": task.task_id,
            "execution_status": completed.execution_status.value,
            "initial_decision": completed.initial_decision,
            "final_decision": completed.final_decision,
            "plan_sha256": preview.plan_sha256,
            "approval_intervention_id": approval.intervention_id,
            "approval_before_snapshot_sha256": approval.before_snapshot_sha256,
            "approval_binding_sha256": (
                approval.approval_binding.binding_sha256
                if approval.approval_binding is not None
                else None
            ),
            "result_review_intervention_id": review.intervention_id,
            "result_review_before_snapshot_sha256": review.before_snapshot_sha256,
            "embedded_intervention_count": len(embedded_timeline["interventions"]),
            "live_intervention_count": len(
                service.list_interventions(user.user_id, task.task_id)
            ),
            "source_profile_sha256": source_profile["profile_sha256"],
            "source_image_count": source_profile["source_image_count"],
            "source_mask_count": source_profile["source_mask_count"],
            "selected_image_count": gate_result["metrics"]["selected_image_count"],
            "finding_count": len(gate_result["findings"]),
            "work_order_count": len(gate_result["work_orders"]),
            "tool_trace_count": len(gate_result["tool_trace"]),
            "replan_count": dynamic_plan["replan_count"],
            "dynamic_task_count": dynamic_plan["dynamic_task_count"],
            "industrial_source_count": len(delivery.multi_source_fusion),
            "industrial_delivery_work_order_count": len(
                delivery.executable_work_orders
            ),
            "industrial_risk_cluster_count": len(delivery.risk_clusters),
            "industrial_remediation_plan_count": len(delivery.remediation_plans),
            "industrial_risk_clusters": [
                {
                    "risk_cluster_id": item.risk_cluster_id,
                    "atomic_work_order_count": item.atomic_work_order_count,
                    "affected_sample_count": item.affected_sample_count,
                    "cluster_sha256": item.cluster_sha256,
                }
                for item in delivery.risk_clusters
            ],
            "industrial_remediation_plans": [
                {
                    "plan_id": item.plan_id,
                    "selected_work_order_count": len(item.selected_work_order_ids),
                    "deferred_work_order_count": len(item.deferred_work_order_ids),
                    "evidence_coverage_ratio": item.evidence_coverage_ratio,
                    "relative_effort_points": item.relative_effort_points,
                    "plan_sha256": item.plan_sha256,
                }
                for item in delivery.remediation_plans
            ],
            "source_registry_sha256": source_database_sha256,
            "production_approval_status": delivery.production_approval_status,
            "anomaly_model_backend": delivery.anomaly_model_backend,
            "evidence_sha256": sha256_file(evidence_path),
            "evidence_member_count": len(evidence_members),
            "evidence_members": evidence_members,
            "source_assets_copied_into_product": False,
            "source_path_serialized": False,
            "claim_boundary": (
                "Local operator-attested, read-only industrial data pilot. It is not "
                "customer acceptance, factory deployment, full-source certification, "
                "legal ownership adjudication, or production authorization."
            ),
        }
        receipt_path = output_root / "authorized_product_pilot_receipt.json"
        write_canonical_json(receipt_path, pilot_receipt)
        if sha256_file(source_database) != source_database_sha256:
            raise RuntimeError("source product registry changed during read-only reuse")
        print(
            json.dumps(
                {
                    "status": completed.execution_status.value,
                    "task_id": task.task_id,
                    "final_decision": completed.final_decision,
                    "evidence_sha256": pilot_receipt["evidence_sha256"],
                    "evidence_member_count": len(evidence_members),
                    "pilot_receipt_sha256": sha256_file(receipt_path),
                },
                ensure_ascii=False,
                sort_keys=True,
            )
        )
        return 0
    finally:
        service.close(wait=True)


if __name__ == "__main__":
    raise SystemExit(main())
