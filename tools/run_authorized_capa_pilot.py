"""Run one private Omni CAPA case from an existing completed parent task.

The script discovers the already-authorized source path only from the local
SQLite binding.  It never prints or serializes that path.  All writes stay in
the explicitly supplied product root and the caller-supplied receipt path.
"""

from __future__ import annotations

import argparse
from pathlib import Path

from visiondata_gate.capa import (
    ApproveRemediationPlanRequest,
    SelectRemediationPlanRequest,
)
from visiondata_gate.evidence import write_canonical_json
from visiondata_gate.product_service import ProductService
from visiondata_gate.task_store import TaskStore


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--product-root", type=Path, required=True)
    parser.add_argument("--parent-task-id", required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()

    product_root = args.product_root.expanduser().resolve(strict=True)
    store = TaskStore(product_root / "product.sqlite3")
    parent = store.get_task_unscoped(args.parent_task_id)
    if parent.source_id is None:
        raise RuntimeError("parent task has no authorized local source")
    binding = store.get_local_source_binding_unscoped(parent.source_id)
    source_root = binding.root_path.resolve(strict=True)
    service = ProductService(
        product_root,
        local_source_allow_roots=[source_root],
        recover_interrupted=False,
    )
    try:
        delivery = service.industrial_delivery_receipt(
            parent.created_by, parent.task_id
        )
        plan = next(
            item
            for item in delivery.remediation_plans
            if item.strategy == "full_evidence_closure"
        )
        selected = service.select_remediation_plan(
            parent.created_by,
            parent.task_id,
            SelectRemediationPlanRequest(
                plan_id=plan.plan_id,
                plan_sha256=plan.plan_sha256,
                note=(
                    "RC3 private Omni CAPA pilot: select the full evidence-closure "
                    "option without modifying the parent source or parent evidence."
                ),
            ),
        )
        service.approve_remediation_plan(
            parent.created_by,
            parent.task_id,
            selected.case_id,
            ApproveRemediationPlanRequest(
                note=(
                    "Operator approves bounded private derived processing, deterministic "
                    "quarantine/backfill, metadata reconciliation, and a same-contract "
                    "child Run. Raw redistribution and parent-source mutation remain forbidden."
                ),
                approved_work_order_ids=plan.selected_work_order_ids,
                operator_attests_derived_processing=True,
                source_mutation_permitted=False,
                raw_redistribution_allowed=False,
                max_copied_images=240,
            ),
        )
        completed = service.execute_remediation_plan(
            parent.created_by, parent.task_id, selected.case_id
        )
        if (
            completed.approval is None
            or completed.derived_version is None
            or completed.execution is None
            or completed.final_queue is None
            or completed.recovery is None
        ):
            raise RuntimeError("CAPA pilot did not produce the complete receipt chain")
        child_delivery = service.industrial_delivery_receipt(
            parent.created_by, completed.execution.child_task_id
        )
        receipt = {
            "schema_version": "visiondata-gate.authorized-capa-pilot.v1",
            "completion_state": "CAPA_CHILD_RUN_COMPLETED",
            "parent_task_id": parent.task_id,
            "case_id": completed.case_id,
            "child_task_id": completed.execution.child_task_id,
            "plan_id": completed.selection.plan.plan_id,
            "plan_sha256": completed.selection.plan.plan_sha256,
            "capa_approval_binding_sha256": completed.approval.binding_sha256,
            "derived_version_id": completed.derived_version.version_id,
            "derived_version_receipt_sha256": (
                completed.derived_version.receipt_sha256
            ),
            "derived_image_count": completed.derived_version.derived_image_count,
            "derived_mask_count": completed.derived_version.derived_mask_count,
            "derived_operation_count": completed.derived_version.operation_count,
            "unresolved_derived_work_order_count": len(
                completed.derived_version.unresolved_work_order_ids
            ),
            "parent_decision": completed.recovery.parent_decision,
            "child_decision": completed.recovery.child_decision,
            "parent_finding_count": completed.recovery.parent_finding_count,
            "child_finding_count": completed.recovery.child_finding_count,
            "verified_closed_work_order_count": (
                completed.recovery.verified_closed_work_order_count
            ),
            "remaining_work_order_count": (
                completed.recovery.remaining_work_order_count
            ),
            "recovery_status": completed.recovery.status,
            "recovery_success": completed.recovery.recovery_success,
            "parent_immutable": completed.execution.parent_immutable,
            "parent_evidence_sha256": completed.execution.parent_evidence_sha256_after,
            "child_evidence_sha256": completed.execution.child_evidence_sha256,
            "lineage_report_sha256": completed.execution.child_lineage_report_sha256,
            "responsibility_queue_sha256": completed.final_queue.queue_sha256,
            "actual_model_call_count": child_delivery.model_call_count,
            "model_execution_status": (
                "NOT_CONNECTED" if child_delivery.model_call_count == 0 else "MEASURED"
            ),
            "source_assets_copied_into_private_derived_version": True,
            "parent_source_mutated": False,
            "raw_redistribution_allowed": False,
            "public_export_allowed": False,
            "production_release_allowed": False,
            "required_human_action": completed.recovery.required_human_action,
            "claim_boundary": (
                "This is a bounded local CAPA pilot on operator-authorized Omni bytes. "
                "Backfill uses alternate authorized samples and is not physical recapture. "
                "It is not a full-source correction, customer acceptance, factory deployment, "
                "production authorization, model-accuracy result, or organizer endorsement."
            ),
        }
        digest = write_canonical_json(args.output.expanduser().resolve(), receipt)
        print(f"CAPA_STATUS={completed.recovery.status}")
        print(f"PARENT_TASK={parent.task_id}")
        print(f"CASE_ID={completed.case_id}")
        print(f"CHILD_TASK={completed.execution.child_task_id}")
        print(f"RECEIPT_SHA256={digest}")
        print(f"PARENT_IMMUTABLE={str(completed.execution.parent_immutable).lower()}")
        print(f"MODEL_CALLS={child_delivery.model_call_count}")
    finally:
        service.close(wait=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
