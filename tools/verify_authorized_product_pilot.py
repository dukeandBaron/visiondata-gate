"""Independently verify a path-redacted authorized product pilot."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import re
import sqlite3
import zipfile

from visiondata_gate.contracts import GateResult
from visiondata_gate.evidence import (
    canonical_json_bytes,
    sha256_file,
    write_canonical_json,
)
from visiondata_gate.industrial_delivery import IndustrialDeliveryReceipt
from visiondata_gate.lineage import task_contract_sha256
from visiondata_gate.product_models import (
    TaskInterventionRecord,
    TaskInterventionAction,
    TaskPlanPreview,
    TaskRecord,
)
from visiondata_gate.runtime_models import RuntimeTrace


def _arguments() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output-root", type=Path, required=True)
    return parser.parse_args()


def _read_product_state(
    database: Path, task_id: str
) -> tuple[TaskRecord, list[TaskInterventionRecord], Path]:
    database_uri = f"file:{database.as_posix()}?mode=ro"
    with sqlite3.connect(database_uri, uri=True) as connection:
        connection.row_factory = sqlite3.Row
        task_row = connection.execute(
            "SELECT * FROM agent_tasks WHERE task_id = ?", (task_id,)
        ).fetchone()
        if task_row is None:
            raise RuntimeError("pilot task is missing from the product registry")
        task_payload = dict(task_row)
        task_payload["allowed_tools"] = json.loads(
            task_payload.pop("allowed_tools_json")
        )
        task_payload["plan_approval_required"] = bool(
            task_payload.get("plan_approval_required", 0)
        )
        task = TaskRecord(**task_payload)

        intervention_rows = connection.execute(
            "SELECT * FROM task_interventions WHERE task_id = ? ORDER BY sequence",
            (task_id,),
        ).fetchall()
        interventions: list[TaskInterventionRecord] = []
        for row in intervention_rows:
            payload = dict(row)
            raw_binding = payload.pop("approval_binding_json", None)
            payload["approval_binding"] = (
                json.loads(raw_binding) if isinstance(raw_binding, str) else None
            )
            interventions.append(TaskInterventionRecord(**payload))

        source_row = connection.execute(
            "SELECT root_path FROM local_source_authorizations WHERE source_id = ?",
            (task.source_id,),
        ).fetchone()
        if source_row is None:
            raise RuntimeError("pilot source binding is missing")
        source_root = Path(str(source_row["root_path"])).resolve(strict=True)
    return task, interventions, source_root


def main() -> int:
    args = _arguments()
    output_root = args.output_root.expanduser().resolve(strict=True)
    receipt_path = output_root / "authorized_product_pilot_receipt.json"
    receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
    task_id = str(receipt["task_id"])
    database_path = output_root / "saas_state" / "product.sqlite3"
    database_sha256 = sha256_file(database_path)
    task, live, source_root = _read_product_state(database_path, task_id)
    if task.evidence_zip_rel is None:
        raise RuntimeError("task evidence path is unavailable")
    evidence_path = (output_root / "saas_state" / task.evidence_zip_rel).resolve(
        strict=True
    )

    checks: list[dict[str, str]] = []

    def verify(check_id: str, condition: bool, detail: str) -> None:
        if not condition:
            raise RuntimeError(f"{check_id}: {detail}")
        checks.append({"check_id": check_id, "status": "PASS", "detail": detail})

    evidence_sha256 = sha256_file(evidence_path)
    verify(
        "evidence-hash-binding",
        evidence_sha256 == task.evidence_sha256 == receipt["evidence_sha256"],
        "SQLite task, pilot receipt, and evidence bytes share one SHA-256.",
    )
    with zipfile.ZipFile(evidence_path) as archive:
        verify("zip-integrity", archive.testzip() is None, "ZIP CRC validation passed.")
        names = sorted(archive.namelist())
        required = {
            "agent_runtime_trace.json",
            "dynamic_leader_plan.json",
            "gate_result.json",
            "industrial_delivery_receipt.json",
            "local_source_authorization_receipt.json",
            "source_profile.json",
            "task_intervention_timeline.json",
            "task_plan_preview.json",
        }
        verify(
            "required-members",
            required.issubset(names),
            "Plan, intervention, runtime, Gate, source, and industrial receipts exist.",
        )
        verify(
            "member-count",
            len(names) == receipt["evidence_member_count"] == 18,
            "Evidence package contains the frozen 18-member contract.",
        )
        payloads = {
            name: archive.read(name)
            for name in names
            if name.endswith((".json", ".csv"))
        }
        plan = TaskPlanPreview.model_validate_json(payloads["task_plan_preview.json"])
        timeline = json.loads(payloads["task_intervention_timeline.json"])
        trace = RuntimeTrace.model_validate_json(payloads["agent_runtime_trace.json"])
        gate = GateResult.model_validate_json(payloads["gate_result.json"])
        leader = json.loads(payloads["dynamic_leader_plan.json"])
        delivery = IndustrialDeliveryReceipt.model_validate_json(
            payloads["industrial_delivery_receipt.json"]
        )
        source_profile = json.loads(payloads["source_profile.json"])

    stable_plan = plan.model_dump(mode="json")
    stable_plan.pop("plan_sha256")
    stable_plan.pop("before_snapshot_sha256")
    recomputed_plan_sha256 = hashlib.sha256(
        canonical_json_bytes(stable_plan)
    ).hexdigest()
    verify(
        "plan-hash",
        recomputed_plan_sha256 == plan.plan_sha256 == receipt["plan_sha256"],
        "Plan SHA-256 recomputes from stable task and permission fields.",
    )
    embedded = timeline.get("interventions", [])
    verify(
        "embedded-plan-approval",
        len(embedded) == 1
        and embedded[0]["action"] == TaskInterventionAction.APPROVE_PLAN.value
        and embedded[0]["before_snapshot_sha256"] == plan.before_snapshot_sha256
        and embedded[0]["plan_sha256"] == plan.plan_sha256,
        "Evidence package freezes the pre-run approval and its before-state snapshot.",
    )
    approval_binding = embedded[0].get("approval_binding") if embedded else None
    binding_payload = dict(approval_binding or {})
    binding_sha256 = str(binding_payload.pop("binding_sha256", ""))
    verify(
        "approval-binding",
        bool(approval_binding)
        and hashlib.sha256(canonical_json_bytes(binding_payload)).hexdigest()
        == binding_sha256
        == receipt["approval_binding_sha256"]
        and approval_binding["request_sha256"] == task.request_sha256
        and approval_binding["before_snapshot_sha256"] == plan.before_snapshot_sha256
        and approval_binding["plan_sha256"] == plan.plan_sha256
        and approval_binding["contract_sha256"] == task_contract_sha256(task)
        and approval_binding["source_profile_status"] == "MATCHED"
        and approval_binding["source_profile_sha256"]
        == source_profile["profile_sha256"],
        "Approval binds the task, plan, snapshot, rule contract, and source profile.",
    )
    verify(
        "live-result-review",
        [item.action for item in live]
        == [
            TaskInterventionAction.APPROVE_PLAN,
            TaskInterventionAction.ACKNOWLEDGE_RESULT,
        ],
        "Live append-only timeline contains pre-run approval and post-run review.",
    )
    verify(
        "runtime-event-chain",
        len(trace.events) == 18 and trace.tool_call_count == len(gate.tool_trace),
        "Runtime contains 18 events and tool count matches final Gate trace.",
    )
    dynamic_tasks = leader.get("dynamic_tasks", [])
    verify(
        "dynamic-branch-count",
        leader.get("replan_count") == 1
        and leader.get("dynamic_task_count") == 3
        and len(dynamic_tasks) == 3,
        "One replan produced exactly three evidence-triggered tasks.",
    )
    traces = {item.sequence: item for item in gate.tool_trace}
    followup_bound = all(
        int(str(item["tool_trace_ref"]).split(":")[1]) in traces
        and traces[int(str(item["tool_trace_ref"]).split(":")[1])].result_sha256
        == item["result_sha256"]
        == item["tool_trace_result_sha256"]
        for item in dynamic_tasks
    )
    verify(
        "dynamic-tooltrace-binding",
        followup_bound,
        "Every dynamic task is bound to a new final ToolTrace result SHA-256.",
    )
    verify(
        "source-profile-boundary",
        source_profile["source_image_count"] == receipt["source_image_count"] == 4464
        and source_profile["source_mask_count"] == receipt["source_mask_count"] == 1439
        and gate.metrics["selected_image_count"]
        == receipt["selected_image_count"]
        == 180,
        "Source profile and fixed Gate denominator remain explicitly separate.",
    )
    verify(
        "gate-counts",
        len(gate.findings) == receipt["finding_count"] == 49
        and len(gate.work_orders) == receipt["work_order_count"] == 49
        and len(gate.tool_trace) == receipt["tool_trace_count"] == 8,
        "Final Gate contains 49 findings, 49 work orders, and 8 ToolTrace records.",
    )
    expected_source_types = {
        "image_batch",
        "mask_annotation",
        "manifest_metadata",
        "tool_measurement",
        "frozen_policy",
        "operator_authorization",
    }
    verify(
        "industrial-multi-source-fusion",
        {item.source_type for item in delivery.multi_source_fusion}
        == expected_source_types,
        "Industrial receipt declares exactly six complementary source types.",
    )
    verify(
        "industrial-work-order-coverage",
        len(delivery.executable_work_orders) == len(gate.work_orders)
        and {item.work_order_id for item in delivery.executable_work_orders}
        == {item.work_order_id for item in gate.work_orders},
        "Every Gate work order has one executable delivery contract.",
    )
    verify(
        "industrial-evidence-trace",
        all(
            item.required_skill
            and item.prerequisites
            and item.acceptance_criteria
            and item.evidence_refs
            and item.reason_trace
            and item.machine_action_permitted is False
            for item in delivery.executable_work_orders
        ),
        "Every delivered work order has Skill, prerequisites, acceptance, and evidence.",
    )
    source_finding_by_order = {
        item.work_order_id: str(
            item.replacement_requirements.get("source_finding_id", "")
        )
        for item in gate.work_orders
    }
    verify(
        "industrial-exact-finding-binding",
        all(
            len(item.evidence_span) == 1
            and item.evidence_span[0].finding_id
            == source_finding_by_order[item.work_order_id]
            for item in delivery.executable_work_orders
        ),
        "Each atomic work order resolves to its exact source finding without sample-overlap contamination.",
    )
    cluster_counts = {
        item.risk_cluster_id: item.atomic_work_order_count
        for item in delivery.risk_clusters
    }
    clusters_sealed = all(
        hashlib.sha256(
            canonical_json_bytes(
                item.model_dump(mode="json", exclude={"cluster_sha256"})
            )
        ).hexdigest()
        == item.cluster_sha256
        and item.machine_action_permitted is False
        for item in delivery.risk_clusters
    )
    cluster_summary = {
        item["risk_cluster_id"]: (
            item["atomic_work_order_count"],
            item["cluster_sha256"],
        )
        for item in receipt["industrial_risk_clusters"]
    }
    verify(
        "industrial-risk-clusters",
        receipt["industrial_risk_cluster_count"] == len(delivery.risk_clusters) == 3
        and cluster_counts
        == {
            "RISK-EVIDENCE-INVESTIGATION": 2,
            "RISK-SPLIT-GOVERNANCE": 7,
            "RISK-ACQUISITION-RECOVERY": 40,
        }
        and sum(cluster_counts.values()) == len(gate.work_orders)
        and clusters_sealed
        and cluster_summary
        == {
            item.risk_cluster_id: (
                item.atomic_work_order_count,
                item.cluster_sha256,
            )
            for item in delivery.risk_clusters
        },
        "Forty-nine atomic records remain intact under three hash-sealed operational risk streams.",
    )
    plans_sealed = all(
        hashlib.sha256(
            canonical_json_bytes(item.model_dump(mode="json", exclude={"plan_sha256"}))
        ).hexdigest()
        == item.plan_sha256
        and item.production_release_allowed is False
        and item.same_contract_child_run_required is True
        and not item.waves[-1].work_order_ids
        and "child Run" in item.waves[-1].objective
        for item in delivery.remediation_plans
    )
    full_plan = next(
        (
            item
            for item in delivery.remediation_plans
            if item.strategy == "full_evidence_closure"
        ),
        None,
    )
    plan_summary = {
        item["plan_id"]: (
            item["selected_work_order_count"],
            item["deferred_work_order_count"],
            item["plan_sha256"],
        )
        for item in receipt["industrial_remediation_plans"]
    }
    verify(
        "industrial-remediation-options",
        receipt["industrial_remediation_plan_count"]
        == len(delivery.remediation_plans)
        == 3
        and {item.plan_id for item in delivery.remediation_plans}
        == {
            "RP-CONTAINMENT-FIRST",
            "RP-ACTIONABLE-RECOVERY",
            "RP-FULL-EVIDENCE-CLOSURE",
        }
        and plans_sealed
        and full_plan is not None
        and full_plan.evidence_coverage_ratio == 1.0
        and not full_plan.deferred_work_order_ids
        and plan_summary
        == {
            item.plan_id: (
                len(item.selected_work_order_ids),
                len(item.deferred_work_order_ids),
                item.plan_sha256,
            )
            for item in delivery.remediation_plans
        },
        "Three sealed options separate containment, actionable recovery, and full evidence closure; none grants release.",
    )
    verify(
        "production-authority-boundary",
        delivery.production_human_approval_required is True
        and delivery.production_approval_status == "pending"
        and delivery.autonomy_level == "L2_recommendation_only",
        "Production authority remains pending with the responsible human role.",
    )
    verify(
        "optional-model-boundary",
        delivery.anomaly_model_backend == "NOT_CONNECTED"
        and delivery.model_call_count == 0,
        "No anomaly model or external LLM call is claimed by this run.",
    )

    serialized = b"\n".join(payloads.values()).decode("utf-8", errors="ignore")
    private_markers = {
        str(source_root),
        str(source_root).replace("\\", "/"),
        source_root.name,
    }
    category_markers = sorted(
        path.name for path in source_root.iterdir() if path.is_dir()
    )
    verify(
        "private-path-redaction",
        not re.search(r"(?i)[a-z]:[\\/]", serialized)
        and all(marker not in serialized for marker in private_markers if marker),
        "Evidence contains no drive-qualified path or authorized source-root marker.",
    )
    verify(
        "category-identifier-redaction",
        all(
            re.search(
                rf"(?<![A-Za-z0-9]){re.escape(marker)}(?![A-Za-z0-9])",
                serialized,
            )
            is None
            for marker in category_markers
        ),
        "Evidence contains no source category directory name.",
    )
    verify(
        "raw-filename-reference-exclusion",
        not re.search(r"(?i)\.(png|jpe?g|bmp)(?:\b|$)", serialized),
        "Evidence contains no raw image filename reference.",
    )
    verify(
        "raw-asset-exclusion",
        all(
            not name.lower().endswith((".png", ".jpg", ".jpeg", ".bmp"))
            for name in names
        )
        and receipt["source_assets_copied_into_product"] is False,
        "Evidence package contains no raw image member.",
    )
    verify(
        "pilot-receipt-boundary",
        receipt["source_path_serialized"] is False
        and receipt["production_approval_status"] == "pending"
        and receipt["anomaly_model_backend"] == "NOT_CONNECTED",
        "Pilot receipt preserves path, production, and model-connection boundaries.",
    )
    verify(
        "product-registry-read-only",
        sha256_file(database_path) == database_sha256,
        "Independent verification opened the product registry read-only.",
    )

    verification = {
        "schema_version": "visiondata-gate.authorized-product-pilot-verification.v2",
        "status": "PASS",
        "task_id": task_id,
        "check_count": len(checks),
        "passed_count": len(checks),
        "evidence_sha256": evidence_sha256,
        "pilot_receipt_sha256": sha256_file(receipt_path),
        "checks": checks,
        "claim_boundary": (
            "Verification covers the local product contract and redaction rules only. "
            "It is not customer acceptance, legal review, full-source certification, "
            "factory deployment, or production authorization."
        ),
    }
    verification_path = output_root / "authorized_product_pilot_verification.json"
    write_canonical_json(verification_path, verification)
    print(
        json.dumps(
            {
                "status": "PASS",
                "check_count": len(checks),
                "evidence_sha256": evidence_sha256,
                "verification_sha256": sha256_file(verification_path),
            },
            ensure_ascii=False,
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
