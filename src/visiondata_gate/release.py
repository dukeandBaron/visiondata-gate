"""Validated public-release bundle for the GOAI submission candidate.

The release bundle deliberately separates three evidence namespaces:

* ``Synthetic-v3`` proves the repair/recheck mechanics on injected truth.
* ``ArchBench-v2`` compares orchestration choices under one frozen protocol.
* ``Omni-180-v1`` is a fixed-denominator public-image pilot that exercises
  evidence-triggered replanning without copying source assets into the project.

This module never infers customer, factory, production, or hosted AgentTeams
status from those artifacts.  It also refuses public JSON containing local
absolute paths or private-evidence markers.
"""

from __future__ import annotations

import json
import os
import re
import subprocess
from collections import Counter
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Any, Mapping

from .contracts import GateResult
from .evidence import (
    canonical_json_bytes,
    sha256_bytes,
    sha256_file,
    write_canonical_json,
)


RELEASE_SCHEMA = "visiondata-gate.submission-release.v1"
REDACTION_SCHEMA = "visiondata-gate.redaction-receipt.v1"
SCENARIO_DELIVERY_SCHEMA = "visiondata-gate.scenario-delivery-receipt.v1"
DEFAULT_RELEASE_ID = "vdg-20260816-rc1"
DEFAULT_RELEASE_RELATIVE_DIR = PurePosixPath(
    "evidence/submission", DEFAULT_RELEASE_ID
).as_posix()

ARCHITECTURE_FILENAME = "architecture_benchmark.json"
DYNAMIC_PLAN_FILENAME = "dynamic_leader_plan.json"
OMNI_GATE_FILENAME = "omni_gate_result.json"
OMNI_RECEIPT_FILENAME = "omni_gate_receipt.json"
SYNTHETIC_SUMMARY_FILENAME = "synthetic_demo_summary.json"
SCENARIO_DELIVERY_FILENAME = "scenario_delivery_receipt.json"
REDACTION_RECEIPT_FILENAME = "redaction_receipt.json"
RELEASE_MANIFEST_FILENAME = "release_manifest.json"

EXPECTED_ARTIFACTS = {
    "architecture_benchmark": ARCHITECTURE_FILENAME,
    "dynamic_leader_plan": DYNAMIC_PLAN_FILENAME,
    "omni_gate_result": OMNI_GATE_FILENAME,
    "omni_gate_receipt": OMNI_RECEIPT_FILENAME,
    "scenario_delivery_receipt": SCENARIO_DELIVERY_FILENAME,
    "synthetic_demo_summary": SYNTHETIC_SUMMARY_FILENAME,
    "redaction_receipt": REDACTION_RECEIPT_FILENAME,
}

_SCENARIO_EVIDENCE_FILENAMES = (
    ARCHITECTURE_FILENAME,
    DYNAMIC_PLAN_FILENAME,
    OMNI_GATE_FILENAME,
    OMNI_RECEIPT_FILENAME,
    SYNTHETIC_SUMMARY_FILENAME,
)
_SUPPORTED_SCENARIO_CLAIMS = (
    "已完成训练前工业视觉数据批次审核应用的本地可运行闭环。",
    "已实现工作台、在线评委 Demo、REST API、五类工具、证据触发 Dynamic Leader、Frozen Policy Judge、整改工单、同合同复验与证据包。",
    "已在固定 180 张公开图像上完成 Policy Gate 实跑：1 次重规划、3 个动态 Worker、45 条 findings、45 张整改工单、8 项规则检查，结论 RECAPTURE。",
    "已完成 288 条传统流水线、单 Agent、多 Agent 同协议对照；固定 SOP 下多 Agent 必要性未被支持。",
)

_EXPECTED_ARCHITECTURES = {
    "traditional_pipeline",
    "single_agent",
    "multi_agent",
}
_EXPECTED_BRANCH_TYPES = {
    "cross-tool-conflict-adjudication",
    "metadata-reconciliation",
    "native-resolution-reconciliation",
}
_RELEASE_ID_PATTERN = re.compile(r"vdg-[0-9]{8}-rc[1-9][0-9]*")
_WINDOWS_ABSOLUTE_PATTERN = re.compile(rb"(?i)(?<![A-Za-z0-9])[A-Z]:[\\/]")
_FORBIDDEN_PUBLIC_MARKERS = (
    b"_private_evidence",
    b"file://",
    b"/users/",
    b"\\users\\",
    b"appdata/local/temp",
)


class ReleaseValidationError(ValueError):
    """Raised when a public submission release is missing or inconsistent."""


@dataclass(frozen=True)
class SubmissionRelease:
    """Parsed and cross-validated public release artifacts."""

    manifest: dict[str, Any]
    redaction_receipt: dict[str, Any]
    architecture_benchmark: dict[str, Any]
    dynamic_leader_plan: dict[str, Any]
    omni_gate_result: GateResult
    omni_gate_receipt: dict[str, Any]
    scenario_delivery_receipt: dict[str, Any]
    synthetic_demo_summary: dict[str, Any]


def _json_object(data: bytes, *, label: str) -> dict[str, Any]:
    try:
        value = json.loads(data.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ReleaseValidationError(f"{label} is not valid UTF-8 JSON") from exc
    if not isinstance(value, dict):
        raise ReleaseValidationError(f"{label} must contain one JSON object")
    return value


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise ReleaseValidationError(message)


def _scan_public_bytes(name: str, data: bytes) -> None:
    lowered = data.lower()
    if _WINDOWS_ABSOLUTE_PATTERN.search(data):
        raise ReleaseValidationError(f"{name} contains a Windows absolute path")
    for marker in _FORBIDDEN_PUBLIC_MARKERS:
        if marker in lowered:
            raise ReleaseValidationError(f"{name} contains a private-path marker")


def _validate_architecture_benchmark(value: dict[str, Any]) -> dict[str, Any]:
    _require(
        value.get("schema_version") == "visiondata-gate.architecture-benchmark.v1",
        "architecture benchmark schema is unexpected",
    )
    _require(value.get("status") == "PASS", "architecture benchmark did not pass")
    protocol = value.get("protocol")
    records = value.get("records")
    summaries = value.get("summaries")
    comparison = value.get("multi_agent_vs_traditional")
    _require(isinstance(protocol, dict), "architecture protocol is missing")
    _require(isinstance(records, list), "architecture records are missing")
    _require(isinstance(summaries, dict), "architecture summaries are missing")
    _require(isinstance(comparison, dict), "architecture comparison is missing")
    _require(len(records) == 288, "ArchBench-v2 must contain exactly 288 records")
    _require(
        set(protocol.get("architectures", [])) == _EXPECTED_ARCHITECTURES,
        "ArchBench-v2 architecture set changed",
    )
    _require(len(protocol.get("seeds", [])) == 8, "ArchBench-v2 seed count changed")
    _require(protocol.get("repeats") == 3, "ArchBench-v2 repeat count changed")
    _require(
        len(protocol.get("perturbations", [])) == 4,
        "ArchBench-v2 perturbation count changed",
    )
    counts = Counter(
        record.get("architecture") for record in records if isinstance(record, dict)
    )
    _require(
        counts == Counter({name: 96 for name in _EXPECTED_ARCHITECTURES}),
        "ArchBench-v2 must contain 96 records per architecture",
    )
    for index, record in enumerate(records):
        _require(isinstance(record, dict), f"architecture record {index} is invalid")
        _require(record.get("task_success") is True, f"record {index} failed its task")
        _require(
            record.get("unsafe_release") is False, f"record {index} released unsafely"
        )
        _require(
            record.get("actual_model_call_count") == 0,
            f"record {index} model-call disclosure changed",
        )
        _require(
            float(record.get("actual_model_cost_cny", -1)) == 0.0,
            f"record {index} model-cost disclosure changed",
        )
    _require(
        comparison.get("fixed_sop_multi_agent_necessity_supported") is False,
        "fixed-SOP negative conclusion must be preserved",
    )
    for name in sorted(_EXPECTED_ARCHITECTURES):
        summary = summaries.get(name)
        _require(isinstance(summary, dict), f"summary missing for {name}")
        _require(summary.get("record_count") == 96, f"record count changed for {name}")
        _require(
            summary.get("error_release_rate") == 0.0, f"unsafe rate changed for {name}"
        )
        _require(
            summary.get("task_success_rate") == 1.0, f"success rate changed for {name}"
        )
        _require(
            summary.get("perturbation_stability_rate") == 1.0,
            f"stability rate changed for {name}",
        )
    return {
        "record_count": len(records),
        "architecture_record_counts": dict(sorted(counts.items())),
        "actual_model_call_count": 0,
        "fixed_sop_multi_agent_necessity_supported": False,
    }


def _validate_dynamic_plan(value: dict[str, Any]) -> dict[str, Any]:
    _require(
        value.get("schema_version") == "visiondata-gate.dynamic-leader-plan.v1",
        "dynamic Leader plan schema is unexpected",
    )
    _require(
        value.get("mode") == "evidence_triggered_replan",
        "dynamic Leader mode must be evidence-triggered",
    )
    tasks = value.get("dynamic_tasks")
    _require(isinstance(tasks, list), "dynamic tasks are missing")
    _require(value.get("static_task_count") == 5, "static tool-task count changed")
    _require(value.get("replan_count") == 1, "Omni pilot must record one replan")
    _require(
        value.get("dynamic_task_count") == 3,
        "Omni pilot must record three dynamic tasks",
    )
    _require(len(tasks) == 3, "dynamic task list must contain three tasks")
    _require(
        set(value.get("branch_types", [])) == _EXPECTED_BRANCH_TYPES,
        "dynamic branch set changed",
    )
    workers: list[str] = []
    tasks_by_id: dict[str, dict[str, Any]] = {}
    for index, task in enumerate(tasks):
        _require(isinstance(task, dict), f"dynamic task {index} is invalid")
        _require(
            task.get("status") == "completed", f"dynamic task {index} is incomplete"
        )
        _require(
            task.get("dispatch_basis") == "intermediate_evidence",
            f"dynamic task {index} was not evidence-triggered",
        )
        _require(
            task.get("planned_before_initial_evidence") is False,
            f"dynamic task {index} was preplanned",
        )
        worker = task.get("worker_id")
        _require(
            isinstance(worker, str) and worker, f"dynamic task {index} has no worker"
        )
        workers.append(worker)
        task_id = task.get("task_id")
        _require(
            isinstance(task_id, str) and task_id,
            f"dynamic task {index} has no task ID",
        )
        _require(task_id not in tasks_by_id, f"duplicate dynamic task ID: {task_id}")
        tasks_by_id[task_id] = task
    _require(len(set(workers)) == 3, "dynamic tasks must use three distinct Workers")

    expected_task_ids = {
        "followup.cross-tool-conflict-adjudication",
        "followup.metadata-reconciliation",
        "followup.native-resolution-reconciliation",
    }
    _require(
        set(tasks_by_id) == expected_task_ids,
        "dynamic task identities changed",
    )
    conflict_outputs = tasks_by_id["followup.cross-tool-conflict-adjudication"].get(
        "outputs"
    )
    metadata_outputs = tasks_by_id["followup.metadata-reconciliation"].get("outputs")
    resolution_outputs = tasks_by_id["followup.native-resolution-reconciliation"].get(
        "outputs"
    )
    _require(isinstance(conflict_outputs, dict), "conflict Worker outputs are missing")
    _require(isinstance(metadata_outputs, dict), "metadata Worker outputs are missing")
    _require(
        isinstance(resolution_outputs, dict),
        "native-resolution Worker outputs are missing",
    )
    _require(
        conflict_outputs.get("conflict_sample_count") == 2,
        "cross-tool conflict sample count changed",
    )
    _require(
        conflict_outputs.get("resolution") == "investigation_required",
        "cross-tool conflict resolution changed",
    )
    count_deltas = metadata_outputs.get("aggregate_count_deltas")
    _require(isinstance(count_deltas, dict), "metadata count deltas are missing")
    _require(count_deltas.get("total") == 15, "metadata count drift changed")
    _require(
        metadata_outputs.get("metadata_mismatch_category_count") == 3,
        "metadata mismatch category count changed",
    )
    _require(
        metadata_outputs.get("tree_image_count") == 4464,
        "metadata reconciliation tree count changed",
    )
    _require(
        resolution_outputs.get("native_resolution_group_count") == 28,
        "native-resolution group count changed",
    )
    _require(
        resolution_outputs.get("quality_trace_complete") is True,
        "native-resolution quality trace is incomplete",
    )

    trigger_facts = [
        {
            "task_id": "followup.cross-tool-conflict-adjudication",
            "signal": "CROSS_TOOL_ACTION_CONFLICT",
            "observed_value": 2,
            "unit": "samples",
            "trigger_statement": "2 个样本出现跨工具处置冲突",
            "dynamic_action": "增派冲突复核 Worker，并转为 INVESTIGATE",
        },
        {
            "task_id": "followup.metadata-reconciliation",
            "signal": "METADATA_COUNT_DRIFT",
            "observed_value": 15,
            "unit": "images",
            "trigger_statement": "metadata 与文件树数量漂移 15（涉及 3 类）",
            "dynamic_action": "增派元数据对账 Worker，保留调查工单并禁止自动修补",
        },
        {
            "task_id": "followup.native-resolution-reconciliation",
            "signal": "NATIVE_RESOLUTION_GROUPS",
            "observed_value": 28,
            "unit": "groups",
            "trigger_statement": "发现 28 个原生分辨率组",
            "dynamic_action": "增派分辨率补证 Worker，按原生尺寸分组测量后复判",
        },
    ]
    return {
        "replan_count": 1,
        "dynamic_task_count": 3,
        "worker_count": 3,
        "branch_types": sorted(_EXPECTED_BRANCH_TYPES),
        "trigger_facts": trigger_facts,
    }


def _validate_gate_result(data: bytes) -> GateResult:
    try:
        result = GateResult.model_validate_json(data)
    except Exception as exc:  # Pydantic exposes several validation exception types.
        raise ReleaseValidationError(
            "Omni GateResult failed contract validation"
        ) from exc
    _require(
        result.decision.value == "RECAPTURE", "Omni decision must remain RECAPTURE"
    )
    _require(
        result.metrics.get("sample_count") == 180,
        "Omni fixed denominator must remain 180",
    )
    _require(
        len(result.tool_trace) == 5, "Omni initial tool trace must contain five tools"
    )
    _require(len(result.findings) == 45, "Omni finding count must remain 45")
    _require(len(result.work_orders) == 45, "Omni work-order count must remain 45")
    _require(len(result.rule_checks) == 8, "Omni rule-check count must remain 8")
    _require(
        all(check.status.value == "PASS" for check in result.rule_checks),
        "Omni GateResult contains a failed release-integrity rule check",
    )
    return result


def _validate_synthetic_summary(value: dict[str, Any]) -> dict[str, Any]:
    _require(
        value.get("schema_version") == "visiondata-gate.demo-summary.v1",
        "Synthetic-v3 summary schema is unexpected",
    )
    evaluation = value.get("evaluation")
    initial = value.get("initial")
    repaired = value.get("repaired")
    _require(isinstance(evaluation, dict), "Synthetic-v3 evaluation is missing")
    _require(isinstance(initial, dict), "Synthetic-v3 initial result is missing")
    _require(isinstance(repaired, dict), "Synthetic-v3 repaired result is missing")
    _require(
        evaluation.get("truth_issue_count") == 12,
        "Synthetic-v3 truth denominator changed",
    )
    _require(evaluation.get("f1") == 1.0, "Synthetic-v3 F1 changed")
    _require(
        initial.get("decision") == "RECAPTURE", "Synthetic-v3 initial decision changed"
    )
    _require(
        repaired.get("decision") == "PASS", "Synthetic-v3 recheck decision changed"
    )
    return {
        "truth_issue_count": 12,
        "f1": 1.0,
        "initial_decision": "RECAPTURE",
        "recheck_decision": "PASS",
    }


def _validate_omni_receipt(
    value: dict[str, Any],
    *,
    gate_data: bytes,
    plan_data: bytes,
    gate_result: GateResult,
) -> dict[str, Any]:
    _require(
        value.get("schema_version") == "visiondata-gate.omni-gate-receipt.v1",
        "Omni receipt schema is unexpected",
    )
    _require(value.get("redacted") is True, "Omni receipt is not marked redacted")
    _require(
        value.get("source_assets_copied_into_project") is False,
        "Omni source assets must not be copied into the public project",
    )
    _require(
        value.get("selected_image_count") == 180, "Omni receipt denominator changed"
    )
    _require(
        value.get("source_image_count") == 4464, "Omni source-tree image count changed"
    )
    _require(
        value.get("source_mask_count") == 1439, "Omni source-tree mask count changed"
    )
    _require(
        value.get("metadata_count_delta_total") == 15, "Omni metadata drift changed"
    )
    _require(value.get("leader_replan_count") == 1, "Omni replan receipt changed")
    _require(
        value.get("leader_dynamic_task_count") == 3, "Omni dynamic-task receipt changed"
    )
    _require(
        value.get("finding_count") == len(gate_result.findings),
        "Omni finding receipt mismatch",
    )
    _require(
        value.get("work_order_count") == len(gate_result.work_orders),
        "Omni work-order receipt mismatch",
    )
    _require(
        value.get("failed_rule_check_count") == 0, "Omni receipt reports failed checks"
    )
    _require(
        value.get("decision") == gate_result.decision.value,
        "Omni decision receipt mismatch",
    )
    _require(
        value.get("gate_result_sha256") == sha256_bytes(gate_data),
        "Omni GateResult hash does not match its receipt",
    )
    _require(
        value.get("dynamic_leader_plan_sha256") == sha256_bytes(plan_data),
        "dynamic Leader plan hash does not match its receipt",
    )
    return {
        "selected_image_count": 180,
        "source_tree_image_count": 4464,
        "source_tree_mask_count": 1439,
        "metadata_count_delta_total": 15,
        "finding_count": len(gate_result.findings),
        "work_order_count": len(gate_result.work_orders),
        "rule_check_count": len(gate_result.rule_checks),
        "decision": gate_result.decision.value,
    }


def _scenario_delivery_payload(
    *,
    release_id: str,
    source_tree_sha256: str,
    artifact_bytes: Mapping[str, bytes],
    architecture_summary: Mapping[str, Any],
    dynamic_plan_summary: Mapping[str, Any],
    omni_metrics: Mapping[str, Any],
) -> dict[str, Any]:
    """Build the exact, path-free proof ladder used by UI and reviewers."""

    external_items = [
        "客户或企业 shadow test 与验收回执",
        "工厂现场只读接入与现场 KPI",
        "生产部署、生产 IAM 与授权写回",
        "外部 LLM 运行回执",
        "Omni 全量 Policy Gate",
        "hosted AgentTeams/Matrix transport 回执",
    ]
    observed_pilot = {
        "evidence_namespace": "Omni-180-v1",
        "evidence_class": "fixed_public_image_pilot",
        "fixed_image_denominator": omni_metrics["selected_image_count"],
        "source_tree_image_count_structure_decode_only": omni_metrics[
            "source_tree_image_count"
        ],
        "source_tree_mask_count_structure_decode_only": omni_metrics[
            "source_tree_mask_count"
        ],
        "replan_count": dynamic_plan_summary["replan_count"],
        "dynamic_worker_count": dynamic_plan_summary["worker_count"],
        "finding_count": omni_metrics["finding_count"],
        "work_order_count": omni_metrics["work_order_count"],
        "rule_check_count": omni_metrics["rule_check_count"],
        "failed_rule_check_count": 0,
        "decision": omni_metrics["decision"],
        "dynamic_triggers": dynamic_plan_summary["trigger_facts"],
    }
    return {
        "schema_version": SCENARIO_DELIVERY_SCHEMA,
        "release_id": release_id,
        "status": "LOCAL_SCENARIO_PILOT_VERIFIED",
        "scenario": {
            "name": "训练前工业视觉数据批次审核与发布门禁",
            "target_users": [
                "工业视觉算法工程师",
                "数据工程师",
                "数据治理负责人",
            ],
            "operational_trigger": "图像、标注与元数据批次准备进入沙箱实验训练池",
            "input_contract": "批次数据、元数据、冻结审核阈值与发布范围",
            "closed_loop": [
                "提交批次与审核目标",
                "校验合同、场景与权限",
                "并行调用五类只读工具",
                "依据中间证据动态补证、对账或转调查",
                "Frozen Policy Judge 形成结论与整改工单",
                "在保留副本上整改并按同一合同复验",
                "交付 GateResult、证据矩阵、reason trace 与 SHA-256 凭证",
            ],
            "delivery_surfaces": [
                "GitHub Pages 在线评委 Demo（固定公开运行）",
                "Streamlit 团队工作台与 Reviewer Mode",
                "REST API：POST /v1/tasks",
                "REST API：GET /v1/tasks/{task_id}/trace",
                "REST API：GET /v1/tasks/{task_id}/evidence",
                "可下载 canonical JSON 与 evidence ZIP",
            ],
        },
        "proof_ladder": {
            "implemented": {
                "label": "已工程实现",
                "status": "PASS",
                "scope": "本地可运行应用闭环",
                "facts": [
                    "在线评委 Demo、工作台、Reviewer Mode、REST API 与本地任务存储",
                    "五类只读工具、证据触发 Dynamic Leader 与 Frozen Policy Judge",
                    "finding → work order → rule check → 同合同复验 → 证据交付",
                ],
            },
            "public_pilot": {
                "label": "已公开数据实跑",
                "status": "PASS",
                "scope": "Omni-180-v1 固定分母 Policy Gate",
                "facts": [
                    "180 张固定公开图像完成 Gate",
                    "1 次重规划并动态增派 3 个 Worker",
                    "45 条 findings 映射为 45 张整改工单",
                    "8 项发布完整性规则检查通过，结论 RECAPTURE",
                ],
            },
            "external_validation": {
                "label": "下一阶段外部验收",
                "status": "OPEN",
                "scope": "需要外部主体、授权环境或平台回执",
                "items": external_items,
            },
        },
        "observed_pilot": observed_pilot,
        "architecture_control": {
            "record_count": architecture_summary["record_count"],
            "architectures": sorted(_EXPECTED_ARCHITECTURES),
            "fixed_sop_multi_agent_necessity_supported": architecture_summary[
                "fixed_sop_multi_agent_necessity_supported"
            ],
            "conclusion": "固定 SOP 下三种架构质量相同；动态 Agent 只用于中间证据改变后续任务的场景。",
        },
        "implementation_evidence": {
            "source_tree_sha256": source_tree_sha256,
            "public_interfaces": [
                "GitHub Pages static reviewer demo",
                "Streamlit",
                "FastAPI REST API",
                "CLI",
                "canonical evidence package",
            ],
            "delivery_artifacts": [
                "GateResult",
                "findings",
                "work orders",
                "rule checks",
                "evidence matrix",
                "reason trace",
                "SHA-256 receipts",
            ],
        },
        "evidence_sha256": {
            filename: sha256_bytes(artifact_bytes[filename])
            for filename in _SCENARIO_EVIDENCE_FILENAMES
        },
        "supported_claim_language": list(_SUPPORTED_SCENARIO_CLAIMS),
        "external_validation_required_for": external_items,
        "interpretation": (
            "前两层是本 release 已完成并可复验的工程事实；第三层用于扩大到客户、工厂和生产环境，"
            "不反向否定已完成的本地闭环与固定公开数据实跑。"
        ),
    }


def _validate_scenario_delivery_receipt(
    value: dict[str, Any],
    *,
    release_id: str,
    source_tree_sha256: str,
    artifact_bytes: Mapping[str, bytes],
    architecture_summary: Mapping[str, Any],
    dynamic_plan_summary: Mapping[str, Any],
    omni_metrics: Mapping[str, Any],
) -> None:
    expected = _scenario_delivery_payload(
        release_id=release_id,
        source_tree_sha256=source_tree_sha256,
        artifact_bytes=artifact_bytes,
        architecture_summary=architecture_summary,
        dynamic_plan_summary=dynamic_plan_summary,
        omni_metrics=omni_metrics,
    )
    _require(
        value == expected,
        "scenario delivery receipt does not match the validated implementation and pilot evidence",
    )


def _validate_redaction_receipt(
    value: dict[str, Any], artifact_bytes: Mapping[str, bytes]
) -> None:
    _require(
        value.get("schema_version") == REDACTION_SCHEMA,
        "redaction receipt schema is unexpected",
    )
    _require(value.get("status") == "PASS", "redaction receipt did not pass")
    _require(
        value.get("source_assets_included") is False,
        "redaction receipt includes source assets",
    )
    records = value.get("files")
    _require(isinstance(records, list), "redaction receipt file list is missing")
    declared: dict[str, dict[str, Any]] = {}
    for index, record in enumerate(records):
        _require(isinstance(record, dict), f"redaction record {index} is invalid")
        path = record.get("public_path")
        _require(
            isinstance(path, str) and path, f"redaction record {index} has no path"
        )
        _require(path not in declared, f"duplicate redaction record for {path}")
        declared[path] = record
    expected = {
        ARCHITECTURE_FILENAME,
        DYNAMIC_PLAN_FILENAME,
        OMNI_GATE_FILENAME,
        OMNI_RECEIPT_FILENAME,
        SCENARIO_DELIVERY_FILENAME,
        SYNTHETIC_SUMMARY_FILENAME,
    }
    _require(set(declared) == expected, "redaction receipt file set changed")
    for path in sorted(expected):
        record = declared[path]
        data = artifact_bytes.get(path)
        _require(data is not None, f"redaction receipt target is missing: {path}")
        digest = sha256_bytes(data)
        _require(
            record.get("public_sha256") == digest, f"public hash mismatch for {path}"
        )
        _require(
            record.get("source_sha256") == digest, f"source hash mismatch for {path}"
        )
        _require(
            record.get("redaction_action") == "none_required_already_redacted",
            f"redaction action changed for {path}",
        )
        _require(
            record.get("privacy_scan") == "PASS", f"privacy scan failed for {path}"
        )


def _validate_manifest(
    value: dict[str, Any],
    *,
    release_id: str,
    artifact_bytes: Mapping[str, bytes],
) -> None:
    _require(
        value.get("schema_version") == RELEASE_SCHEMA,
        "release manifest schema is unexpected",
    )
    _require(
        value.get("release_id") == release_id, "release ID does not match its directory"
    )
    track = value.get("track")
    _require(isinstance(track, dict), "release track declaration is missing")
    _require(track.get("track_number") == 2, "primary track must be track 2")
    _require(
        track.get("track_name_en") == "Boundless Agents",
        "primary track must be Boundless Agents",
    )
    _require(
        track.get("industry_direction") == "AI+工业制造", "industry direction changed"
    )
    runtime = value.get("runtime_disclosure")
    _require(isinstance(runtime, dict), "runtime disclosure is missing")
    _require(
        runtime.get("mode") == "local-deterministic", "runtime mode disclosure changed"
    )
    _require(
        runtime.get("actual_model_call_count") == 0, "model-call disclosure changed"
    )
    agentteams = value.get("agentteams")
    _require(isinstance(agentteams, dict), "AgentTeams disclosure is missing")
    _require(
        agentteams.get("connection_status") == "mapped_not_connected",
        "AgentTeams connection status must remain mapped_not_connected",
    )
    artifacts = value.get("artifacts")
    _require(isinstance(artifacts, dict), "release artifact index is missing")
    _require(
        set(artifacts) == set(EXPECTED_ARTIFACTS), "release artifact index changed"
    )
    for key, expected_path in sorted(EXPECTED_ARTIFACTS.items()):
        record = artifacts.get(key)
        _require(isinstance(record, dict), f"artifact record is invalid: {key}")
        _require(record.get("path") == expected_path, f"artifact path changed: {key}")
        data = artifact_bytes.get(expected_path)
        _require(data is not None, f"release artifact is missing: {expected_path}")
        _require(
            record.get("sha256") == sha256_bytes(data),
            f"release artifact hash mismatch: {key}",
        )
        _require(
            record.get("size") == len(data), f"release artifact size mismatch: {key}"
        )


def validate_submission_release_members(
    members: Mapping[str, bytes],
    *,
    release_root: str = DEFAULT_RELEASE_RELATIVE_DIR,
) -> SubmissionRelease:
    """Validate a release represented by package-relative member bytes."""

    root = release_root.rstrip("/")
    manifest_name = f"{root}/{RELEASE_MANIFEST_FILENAME}"
    manifest_data = members.get(manifest_name)
    _require(manifest_data is not None, "public release manifest is missing")
    manifest = _json_object(manifest_data, label=manifest_name)
    release_id = manifest.get("release_id")
    _require(
        isinstance(release_id, str)
        and _RELEASE_ID_PATTERN.fullmatch(release_id) is not None,
        "release ID is invalid",
    )
    _require(
        PurePosixPath(root).name == release_id,
        "release directory and release ID differ",
    )

    artifact_bytes: dict[str, bytes] = {}
    for filename in EXPECTED_ARTIFACTS.values():
        member_name = f"{root}/{filename}"
        data = members.get(member_name)
        _require(data is not None, f"public release artifact is missing: {filename}")
        _scan_public_bytes(filename, data)
        artifact_bytes[filename] = data
    _scan_public_bytes(RELEASE_MANIFEST_FILENAME, manifest_data)

    benchmark = _json_object(
        artifact_bytes[ARCHITECTURE_FILENAME], label=ARCHITECTURE_FILENAME
    )
    plan = _json_object(
        artifact_bytes[DYNAMIC_PLAN_FILENAME], label=DYNAMIC_PLAN_FILENAME
    )
    omni_receipt = _json_object(
        artifact_bytes[OMNI_RECEIPT_FILENAME], label=OMNI_RECEIPT_FILENAME
    )
    scenario_delivery = _json_object(
        artifact_bytes[SCENARIO_DELIVERY_FILENAME],
        label=SCENARIO_DELIVERY_FILENAME,
    )
    synthetic = _json_object(
        artifact_bytes[SYNTHETIC_SUMMARY_FILENAME], label=SYNTHETIC_SUMMARY_FILENAME
    )
    redaction = _json_object(
        artifact_bytes[REDACTION_RECEIPT_FILENAME], label=REDACTION_RECEIPT_FILENAME
    )
    gate_result = _validate_gate_result(artifact_bytes[OMNI_GATE_FILENAME])

    architecture_summary = _validate_architecture_benchmark(benchmark)
    dynamic_plan_summary = _validate_dynamic_plan(plan)
    _validate_synthetic_summary(synthetic)
    omni_metrics = _validate_omni_receipt(
        omni_receipt,
        gate_data=artifact_bytes[OMNI_GATE_FILENAME],
        plan_data=artifact_bytes[DYNAMIC_PLAN_FILENAME],
        gate_result=gate_result,
    )
    _validate_redaction_receipt(redaction, artifact_bytes)
    _validate_manifest(
        manifest,
        release_id=release_id,
        artifact_bytes=artifact_bytes,
    )
    source_state = manifest.get("source_state")
    _require(isinstance(source_state, dict), "release source state is missing")
    source_tree_sha256 = source_state.get("source_tree_sha256")
    _require(
        isinstance(source_tree_sha256, str)
        and re.fullmatch(r"[0-9a-f]{64}", source_tree_sha256) is not None,
        "release source-tree digest is invalid",
    )
    _validate_scenario_delivery_receipt(
        scenario_delivery,
        release_id=release_id,
        source_tree_sha256=source_tree_sha256,
        artifact_bytes=artifact_bytes,
        architecture_summary=architecture_summary,
        dynamic_plan_summary=dynamic_plan_summary,
        omni_metrics=omni_metrics,
    )
    _require(
        canonical_json_bytes(manifest) == manifest_data,
        "release manifest is not canonical JSON",
    )
    _require(
        canonical_json_bytes(redaction) == artifact_bytes[REDACTION_RECEIPT_FILENAME],
        "redaction receipt is not canonical JSON",
    )
    _require(
        canonical_json_bytes(scenario_delivery)
        == artifact_bytes[SCENARIO_DELIVERY_FILENAME],
        "scenario delivery receipt is not canonical JSON",
    )
    return SubmissionRelease(
        manifest=manifest,
        redaction_receipt=redaction,
        architecture_benchmark=benchmark,
        dynamic_leader_plan=plan,
        omni_gate_result=gate_result,
        omni_gate_receipt=omni_receipt,
        scenario_delivery_receipt=scenario_delivery,
        synthetic_demo_summary=synthetic,
    )


def load_submission_release(release_dir: str | Path) -> SubmissionRelease:
    """Load and validate one public release directory without exposing its path."""

    root = Path(release_dir)
    if not root.is_dir():
        raise ReleaseValidationError("public release directory is missing")
    release_root = PurePosixPath("evidence/submission", root.name).as_posix()
    members: dict[str, bytes] = {}
    for filename in {RELEASE_MANIFEST_FILENAME, *EXPECTED_ARTIFACTS.values()}:
        path = root / filename
        if not path.is_file():
            raise ReleaseValidationError(
                f"public release artifact is missing: {filename}"
            )
        members[f"{release_root}/{filename}"] = path.read_bytes()
    return validate_submission_release_members(members, release_root=release_root)


def _source_tree_sha256(project_root: Path) -> str:
    include_roots = (
        project_root / "src",
        project_root / "tools",
        project_root / "tests",
        project_root / "docs",
        project_root / "agentteams",
        project_root / "skills",
    )
    paths = [
        path
        for name in ("README.md", "app.py", "pyproject.toml")
        if (path := project_root / name).is_file()
    ]
    for root in include_roots:
        if root.is_dir():
            paths.extend(path for path in root.rglob("*") if path.is_file())
    records: list[dict[str, str]] = []
    for path in sorted(
        set(paths), key=lambda item: item.relative_to(project_root).as_posix()
    ):
        relative = path.relative_to(project_root).as_posix()
        if any(
            part in {"__pycache__", ".pytest_cache", ".ruff_cache"}
            for part in path.parts
        ):
            continue
        if path.suffix.lower() not in {".json", ".md", ".py", ".toml", ".yaml", ".yml"}:
            continue
        records.append({"path": relative, "sha256": sha256_file(path)})
    return sha256_bytes(canonical_json_bytes(records))


def _git_identity(project_root: Path) -> tuple[str | None, str]:
    try:
        process = subprocess.run(
            ["git", "-C", os.fspath(project_root), "rev-parse", "--verify", "HEAD"],
            check=False,
            capture_output=True,
            text=True,
            encoding="utf-8",
            timeout=5,
        )
    except (OSError, subprocess.SubprocessError):
        return None, "git_unavailable"
    if process.returncode != 0:
        return None, "parent_repository_has_no_commits"
    commit = process.stdout.strip()
    if re.fullmatch(r"[0-9a-f]{40}", commit):
        return commit, "commit_resolved"
    return None, "git_head_unresolved"


def _artifact_record(path: str, data: bytes) -> dict[str, Any]:
    return {"path": path, "sha256": sha256_bytes(data), "size": len(data)}


def _deliverable_records(
    project_root: Path, paths: Mapping[str, Path] | None
) -> dict[str, Any]:
    records: dict[str, Any] = {}
    for label, path in sorted((paths or {}).items()):
        resolved = path.resolve(strict=True)
        try:
            relative = resolved.relative_to(project_root.resolve()).as_posix()
        except ValueError as exc:
            raise ReleaseValidationError(
                f"deliverable is outside the project: {label}"
            ) from exc
        records[label] = {
            "path": relative,
            "sha256": sha256_file(resolved),
            "size": resolved.stat().st_size,
        }
    return records


def build_submission_release(
    *,
    project_root: str | Path,
    output_dir: str | Path,
    architecture_benchmark_path: str | Path,
    dynamic_plan_path: str | Path,
    omni_gate_path: str | Path,
    omni_receipt_path: str | Path,
    synthetic_summary_path: str | Path,
    release_id: str = DEFAULT_RELEASE_ID,
    qa_passed: int | None = None,
    qa_skipped: int | None = None,
    qa_warnings: int | None = None,
    ruff_status: str = "PENDING",
    format_status: str = "PENDING",
    compileall_status: str = "PENDING",
    deliverables: Mapping[str, Path] | None = None,
    overwrite: bool = False,
) -> SubmissionRelease:
    """Build a deterministic, redacted public release from validated artifacts."""

    _require(
        _RELEASE_ID_PATTERN.fullmatch(release_id) is not None, "release ID is invalid"
    )
    root = Path(project_root).resolve(strict=True)
    destination = Path(output_dir).resolve(strict=False)
    expected_destination = (root / "evidence" / "submission" / release_id).resolve(
        strict=False
    )
    _require(
        destination == expected_destination,
        "release output must use evidence/submission/<release_id>",
    )

    source_paths = {
        ARCHITECTURE_FILENAME: Path(architecture_benchmark_path),
        DYNAMIC_PLAN_FILENAME: Path(dynamic_plan_path),
        OMNI_GATE_FILENAME: Path(omni_gate_path),
        OMNI_RECEIPT_FILENAME: Path(omni_receipt_path),
        SYNTHETIC_SUMMARY_FILENAME: Path(synthetic_summary_path),
    }
    source_bytes: dict[str, bytes] = {}
    for filename, path in source_paths.items():
        try:
            data = path.read_bytes()
        except OSError as exc:
            raise ReleaseValidationError(
                f"source artifact is unavailable: {filename}"
            ) from exc
        _scan_public_bytes(filename, data)
        source_bytes[filename] = data

    benchmark = _json_object(
        source_bytes[ARCHITECTURE_FILENAME], label=ARCHITECTURE_FILENAME
    )
    plan = _json_object(
        source_bytes[DYNAMIC_PLAN_FILENAME], label=DYNAMIC_PLAN_FILENAME
    )
    receipt = _json_object(
        source_bytes[OMNI_RECEIPT_FILENAME], label=OMNI_RECEIPT_FILENAME
    )
    synthetic = _json_object(
        source_bytes[SYNTHETIC_SUMMARY_FILENAME], label=SYNTHETIC_SUMMARY_FILENAME
    )
    gate_result = _validate_gate_result(source_bytes[OMNI_GATE_FILENAME])
    arch_summary = _validate_architecture_benchmark(benchmark)
    plan_summary = _validate_dynamic_plan(plan)
    synthetic_metrics = _validate_synthetic_summary(synthetic)
    omni_metrics = _validate_omni_receipt(
        receipt,
        gate_data=source_bytes[OMNI_GATE_FILENAME],
        plan_data=source_bytes[DYNAMIC_PLAN_FILENAME],
        gate_result=gate_result,
    )
    source_tree_digest = _source_tree_sha256(root)
    scenario_delivery = _scenario_delivery_payload(
        release_id=release_id,
        source_tree_sha256=source_tree_digest,
        artifact_bytes=source_bytes,
        architecture_summary=arch_summary,
        dynamic_plan_summary=plan_summary,
        omni_metrics=omni_metrics,
    )
    scenario_delivery_data = canonical_json_bytes(scenario_delivery)
    _scan_public_bytes(SCENARIO_DELIVERY_FILENAME, scenario_delivery_data)
    source_bytes[SCENARIO_DELIVERY_FILENAME] = scenario_delivery_data

    existing = []
    if destination.exists():
        _require(destination.is_dir(), "release output exists and is not a directory")
        existing = [path.name for path in destination.iterdir()]
        unexpected = sorted(
            set(existing) - {RELEASE_MANIFEST_FILENAME, *EXPECTED_ARTIFACTS.values()}
        )
        _require(not unexpected, "release output contains unexpected files")
        _require(
            overwrite or not existing,
            "release output already exists; pass overwrite=True",
        )
    destination.mkdir(parents=True, exist_ok=True)
    for filename, data in source_bytes.items():
        (destination / filename).write_bytes(data)

    redaction = {
        "schema_version": REDACTION_SCHEMA,
        "release_id": release_id,
        "status": "PASS",
        "source_assets_included": False,
        "forbidden_path_scan": "PASS",
        "files": [
            {
                "source_label": {
                    ARCHITECTURE_FILENAME: "ArchBench-v2 frozen output",
                    DYNAMIC_PLAN_FILENAME: "Omni-180-v1 dynamic plan",
                    OMNI_GATE_FILENAME: "Omni-180-v1 redacted GateResult",
                    OMNI_RECEIPT_FILENAME: "Omni-180-v1 cross-hash receipt",
                    SCENARIO_DELIVERY_FILENAME: "Industrial scenario delivery proof ladder",
                    SYNTHETIC_SUMMARY_FILENAME: "Synthetic-v3 frozen demo summary",
                }[filename],
                "public_path": filename,
                "source_sha256": sha256_bytes(data),
                "public_sha256": sha256_bytes(data),
                "redaction_action": "none_required_already_redacted",
                "privacy_scan": "PASS",
            }
            for filename, data in sorted(source_bytes.items())
        ],
        "boundary": (
            "Only redacted JSON evidence is published. No source image, mask, category name, "
            "original filename, customer record, or private absolute path is included."
        ),
    }
    redaction_path = destination / REDACTION_RECEIPT_FILENAME
    write_canonical_json(redaction_path, redaction)
    redaction_data = redaction_path.read_bytes()

    quality_values = (qa_passed, qa_skipped, qa_warnings)
    _require(
        all(value is None for value in quality_values)
        or all(isinstance(value, int) and value >= 0 for value in quality_values),
        "QA counts must be all omitted or all non-negative integers",
    )
    qa_status = "PASS" if qa_passed is not None else "PENDING_FINAL_VERIFICATION"
    git_commit, git_state = _git_identity(root)
    public_bytes = {**source_bytes, REDACTION_RECEIPT_FILENAME: redaction_data}
    manifest = {
        "schema_version": RELEASE_SCHEMA,
        "release_id": release_id,
        "project": {
            "name": "VisionData Gate",
            "positioning": "工业视觉数据治理与发布 Agent",
            "primary_user": "工业视觉算法工程师与工业数据治理团队",
        },
        "track": {
            "event": "GOAI 世界人工智能开源大赛",
            "track_number": 2,
            "track_name_zh": "无界应用",
            "track_name_en": "Boundless Agents",
            "industry_direction": "AI+工业制造",
            "official_url": "https://www.goaihz.com/tracks?track=apps",
        },
        "application_story": {
            "pain": "数据批次进入实验训练池前，质量、重复、标注、覆盖与治理证据分散，整改和复验难以闭环。",
            "input": "工业视觉图像批次、标注、元数据与冻结审核合同",
            "closed_loop": [
                "理解审核目标与权限边界",
                "并行调用五类只读检查工具",
                "依据中间证据动态补证和增派 Worker",
                "冻结 Policy Judge 形成门禁结论与整改工单",
                "在保留副本上整改并按同一合同复验",
                "交付 GateResult、证据矩阵、reason trace 与 SHA-256 凭证",
            ],
            "output": "可执行整改工单、同规则复验结果与可校验审核凭证",
        },
        "infra_support": {
            "role": "可信后台，不是参赛主叙事",
            "capabilities": [
                "typed task 与上下文引用",
                "工具白名单和失败关闭",
                "证据触发的动态编排",
                "finding 到工单、规则检查和复验的统一追踪",
                "可替换 AgentTeams adapter 与可复用 Skills",
            ],
        },
        "runtime_disclosure": {
            "mode": "local-deterministic",
            "actual_model_call_count": 0,
            "actual_model_cost_cny": 0.0,
            "worker_kind": "deterministic_local_ai_roles",
            "authority": "advisory_workers_plus_frozen_policy_judge",
        },
        "agentteams": {
            "static_contract_status": "PASS",
            "runtime_transport_status": "OPEN",
            "connection_status": "mapped_not_connected",
            "claim": "v1.2.2 contract mapping exists; hosted Team/Matrix runtime is not claimed",
        },
        "evidence_namespaces": {
            "Synthetic-v3": {
                **synthetic_metrics,
                "artifact": SYNTHETIC_SUMMARY_FILENAME,
                "evidence_class": "synthetic_injected_truth",
                "claim_boundary": "engineering closed-loop evidence only",
            },
            "ArchBench-v2": {
                **arch_summary,
                "artifact": ARCHITECTURE_FILENAME,
                "protocol": "8 seeds x 3 repeats x 4 perturbations x 3 architectures",
                "claim_boundary": "no customer ROI, production SLO, or general multi-Agent superiority claim",
            },
            "Omni-180-v1": {
                **omni_metrics,
                **plan_summary,
                "artifacts": [
                    DYNAMIC_PLAN_FILENAME,
                    OMNI_GATE_FILENAME,
                    OMNI_RECEIPT_FILENAME,
                ],
                "evidence_class": "fixed_public_image_pilot",
                "claim_boundary": (
                    "Policy Gate applies to the fixed 180-image denominator only; the 4,464-image tree "
                    "received structure/decode audit, not full Gate certification"
                ),
            },
        },
        "quality_gates": {
            "status": qa_status,
            "pytest": {
                "passed": qa_passed,
                "skipped": qa_skipped,
                "warnings": qa_warnings,
                "failed": 0 if qa_passed is not None else None,
            },
            "ruff_rules": ruff_status,
            "ruff_format": format_status,
            "compileall": compileall_status,
        },
        "claim_scope": {
            "proof_ladder": {
                "implemented": "PASS",
                "public_pilot": "PASS",
                "external_validation": "OPEN",
            },
            "verified": [
                *_SUPPORTED_SCENARIO_CLAIMS,
                "公开 release 已完成脱敏、交叉哈希与结构一致性校验。",
            ],
            "external_pending": scenario_delivery["external_validation_required_for"],
            "not_claimed": [
                "customer acceptance",
                "factory-site validation",
                "production deployment or IAM",
                "full Omni dataset Gate certification",
                "external LLM execution",
                "hosted AgentTeams/Matrix connection",
                "official website submission receipt",
            ],
        },
        "source_state": {
            "git_commit": git_commit,
            "git_state": git_state,
            "source_tree_sha256": source_tree_digest,
        },
        "deliverables": _deliverable_records(root, deliverables),
        "external_owner_actions": [
            "confirm the top-level open-source license and NOTICE",
            "upload through the account holder and retain the official submission receipt",
        ],
        "artifacts": {
            key: _artifact_record(filename, public_bytes[filename])
            for key, filename in sorted(EXPECTED_ARTIFACTS.items())
        },
    }
    manifest_path = destination / RELEASE_MANIFEST_FILENAME
    write_canonical_json(manifest_path, manifest)
    _scan_public_bytes(RELEASE_MANIFEST_FILENAME, manifest_path.read_bytes())
    return load_submission_release(destination)


__all__ = [
    "ARCHITECTURE_FILENAME",
    "DEFAULT_RELEASE_ID",
    "DEFAULT_RELEASE_RELATIVE_DIR",
    "DYNAMIC_PLAN_FILENAME",
    "EXPECTED_ARTIFACTS",
    "OMNI_GATE_FILENAME",
    "OMNI_RECEIPT_FILENAME",
    "REDACTION_RECEIPT_FILENAME",
    "RELEASE_MANIFEST_FILENAME",
    "SCENARIO_DELIVERY_FILENAME",
    "SCENARIO_DELIVERY_SCHEMA",
    "ReleaseValidationError",
    "SubmissionRelease",
    "SYNTHETIC_SUMMARY_FILENAME",
    "build_submission_release",
    "load_submission_release",
    "validate_submission_release_members",
]
