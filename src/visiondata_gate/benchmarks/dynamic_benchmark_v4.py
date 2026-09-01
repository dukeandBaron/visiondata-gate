"""DynamicBench-v4 production-runtime bridge.

Unlike DynamicBench-v3, this benchmark does not implement its own Planner,
Tool loop, Council, or Judge.  Every observed case is created through
``ProductService.create_industrial_incident_case`` and then read back through
the public integrity-verifying product API.

The input data remains frozen synthetic fixture data.  The report proves the
production runtime bridge and fail-closed contracts; it does not prove factory
accuracy or turn the v3 fixed-vs-dynamic comparison into a production trial.
"""

from __future__ import annotations

from copy import deepcopy
import hashlib
import hmac
import json
from pathlib import Path
import re
from typing import Any

import rfc8785

from visiondata_gate.agent_runtime import run_agentic_demo
from visiondata_gate.demo_fixtures import build_fixture_industrial_incident_request
from visiondata_gate.dynamic_benchmark_v3 import (
    load_dynamic_replanning_benchmark_report,
)
from visiondata_gate.evidence import canonical_json_bytes
from visiondata_gate.industrial_incident import (
    AGENT_KERNEL_INCIDENT_CASE_SCHEMA_VERSION,
    IncidentWorkerExecutionError,
    IncidentWorkerRegistry,
)
from visiondata_gate.product_models import (
    CreateProjectRequest,
    CreateTaskRequest,
    CreateUserRequest,
    CreateWorkspaceRequest,
    TaskExecutionStatus,
)
from visiondata_gate.product_service import ProductService


SCHEMA_VERSION = "visiondata-gate.dynamic-benchmark.v4"
BENCHMARK_ID = "DynamicBench-v4-production-runtime-bridge"
DECISION_PACKET_V3 = "visiondata-gate.industrial-quality-decision-packet.v3"
PRODUCTION_ROUTE = (
    "ProductService.run_task_sync->"
    "ProductService.create_industrial_incident_case->IncidentKernelV6"
)
CLAIM_BOUNDARY = (
    "DynamicBench-v4 proves that frozen synthetic incident requests traverse the "
    "real ProductService and Incident v6 runtime, persistence, audit envelope, "
    "control plane, and DecisionPacket v3 verification paths. It does not establish "
    "industrial model accuracy, factory applicability, customer acceptance, a "
    "production SLO, or a production fixed-vs-dynamic advantage."
)

_FRAME_MAGIC = b"VISIONDATA_GATE_DYNAMICBENCH_V4\x00"
_HASH_DOMAINS = {
    "fixture_manifest": "visiondata-gate.dynamicbench-v4.fixture-manifest.v1",
    "record": "visiondata-gate.dynamicbench-v4.record.v1",
    "records": "visiondata-gate.dynamicbench-v4.records.v1",
    "metrics": "visiondata-gate.dynamicbench-v4.metrics.v1",
    "comparison": "visiondata-gate.dynamicbench-v4.comparison-binding.v1",
    "report": "visiondata-gate.dynamicbench-v4.report.v1",
}
_SHA256 = re.compile(r"^[0-9a-f]{64}$")

_WORKER_ROLES = {
    "EvidenceQualificationAgent",
    "SignalIntegrityAgent",
    "TraceabilityAgent",
    "ManufacturingContextAgent",
    "ProcessContextAgent",
    "VisionRecipeAgent",
    "VisualDataQualityAgent",
    "CounterevidenceAuditorAgent",
}

_FIXTURE_MANIFEST: tuple[dict[str, Any], ...] = (
    {
        "fixture_id": "P01",
        "scenario_class": "conflicting_evidence",
        "request_variant": "default_conflicting_fixture",
        "revision": 1,
        "worker_registry": "production_default",
        "expected": {
            "case_status": "INVESTIGATION_REQUIRED",
            "minimum_dynamic_branch_count": 1,
            "minimum_failed_worker_count": 0,
            "required_issue_codes": [],
            "required_dynamic_roles": ["CounterevidenceAuditorAgent"],
        },
    },
    {
        "fixture_id": "P02",
        "scenario_class": "qualified_evidence",
        "request_variant": "qualified_process_and_solution",
        "revision": 2,
        "worker_registry": "production_default",
        "expected": {
            "case_status": "READY_FOR_HUMAN_DECISION",
            "minimum_dynamic_branch_count": 0,
            "minimum_failed_worker_count": 0,
            "required_issue_codes": [],
            "required_dynamic_roles": [],
        },
    },
    {
        "fixture_id": "P03",
        "scenario_class": "tool_failure",
        "request_variant": "single_worker_failure",
        "revision": 3,
        "worker_registry": "injected_failure_registry",
        "expected": {
            "case_status": "EVIDENCE_INCOMPLETE",
            "minimum_dynamic_branch_count": 1,
            "minimum_failed_worker_count": 1,
            "required_issue_codes": ["WORKER_EXECUTION_FAILED"],
            "required_dynamic_roles": [],
        },
    },
    {
        "fixture_id": "P04",
        "scenario_class": "worker_budget_boundary",
        "request_variant": "single_worker_budget",
        "revision": 4,
        "worker_registry": "production_default",
        "expected": {
            "case_status": "EVIDENCE_INCOMPLETE",
            "minimum_dynamic_branch_count": 1,
            "minimum_failed_worker_count": 0,
            "required_issue_codes": ["EVIDENCE_NOT_EVALUATED_DUE_TO_BUDGET"],
            "required_dynamic_roles": [],
        },
    },
)


class DynamicBenchmarkV4ValidationError(ValueError):
    """Raised when a v4 execution report violates its frozen contract."""


def _canonical_jcs_bytes(value: object) -> bytes:
    try:
        return rfc8785.dumps(value)
    except (rfc8785.CanonicalizationError, TypeError, UnicodeError) as error:
        raise DynamicBenchmarkV4ValidationError(
            f"v4 payload cannot be canonicalized: {error}"
        ) from error


class _FailingWorkerRegistry(IncidentWorkerRegistry):
    """Production registry boundary that deterministically reports tool failure."""

    worker_version = "dynamicbench-v4-failing-worker-v1"

    def __init__(self) -> None:
        super().__init__(set(_WORKER_ROLES))

    def execute(self, **_: Any):  # type: ignore[no-untyped-def]
        raise IncidentWorkerExecutionError(
            "DYNAMICBENCH_INJECTED_TOOL_FAILURE",
            retryable=True,
        )


def _framed_sha256(domain: str, payload: object) -> str:
    domain_bytes = domain.encode("utf-8")
    payload_bytes = _canonical_jcs_bytes(payload)
    framed = (
        _FRAME_MAGIC
        + len(domain_bytes).to_bytes(4, "big")
        + domain_bytes
        + len(payload_bytes).to_bytes(8, "big")
        + payload_bytes
    )
    return hashlib.sha256(framed).hexdigest()


def build_dynamic_benchmark_v4_fixtures() -> list[dict[str, Any]]:
    """Return the frozen public fixture/expectation manifest."""

    return deepcopy(list(_FIXTURE_MANIFEST))


def _request_for_fixture(fixture: dict[str, Any]):  # type: ignore[no-untyped-def]
    variant = fixture["request_variant"]
    request = build_fixture_industrial_incident_request(
        revision=int(fixture["revision"])
    )
    if variant == "qualified_process_and_solution":
        observation = request.opcua_snapshot.observations[0].model_copy(
            update={"value": 82.0}
        )
        snapshot = request.opcua_snapshot.model_copy(
            update={"observations": [observation]}
        )
        request = request.model_copy(
            update={
                "opcua_snapshot": snapshot,
                "baseline_solution_manifest_sha256": hashlib.sha256(
                    canonical_json_bytes(request.vision_solution)
                ).hexdigest(),
            }
        )
    if variant in {"single_worker_failure", "single_worker_budget"}:
        request = request.model_copy(update={"max_dynamic_workers": 1})
    return request


def _registry_for_fixture(fixture: dict[str, Any]) -> IncidentWorkerRegistry | None:
    mode = fixture["worker_registry"]
    if mode == "production_default":
        return None
    if mode == "injected_failure_registry":
        return _FailingWorkerRegistry()
    raise DynamicBenchmarkV4ValidationError(f"unknown Worker registry mode: {mode}")


def _setup_completed_gate_task(
    root: Path,
    *,
    worker_registry: IncidentWorkerRegistry | None,
) -> tuple[ProductService, str, str]:
    service = ProductService(
        root,
        recover_interrupted=False,
        incident_worker_registry=worker_registry,
    )
    user = service.create_user(
        CreateUserRequest(display_name="DynamicBench-v4 local evaluator")
    )
    workspace = service.create_workspace(
        CreateWorkspaceRequest(
            name="DynamicBench-v4 production bridge",
            owner_user_id=user.user_id,
        )
    )
    project = service.create_project(
        user.user_id,
        CreateProjectRequest(
            workspace_id=workspace.workspace_id,
            name="DynamicBench-v4 frozen synthetic runtime",
        ),
    )
    task = service.create_task(
        user.user_id,
        CreateTaskRequest(
            project_id=project.project_id,
            goal=(
                "Execute the frozen local Gate task before an Incident v6 "
                "production-runtime integration check."
            ),
            seed=17,
        ),
        auto_start=False,
    )
    completed = service.run_task_sync(task.task_id)
    if completed.execution_status is not TaskExecutionStatus.COMPLETED:
        service.close(wait=True)
        raise DynamicBenchmarkV4ValidationError(
            "ProductService prerequisite Gate task did not complete"
        )
    return service, user.user_id, completed.task_id


def _assertions_for_record(
    *,
    fixture: dict[str, Any],
    case: Any,
    persisted: Any,
    packet: Any,
    control_plane: Any,
) -> dict[str, bool]:
    expected = fixture["expected"]
    issue_codes = {item.issue_code for item in case.evidence_issues}
    completed_roles = {
        item.agent_role
        for item in case.agent_actions
        if item.dynamic and item.status == "COMPLETED"
    }
    failed_receipts = [item for item in case.worker_receipts if item.status == "FAILED"]
    return {
        "product_service_persisted_roundtrip_verified": (
            persisted.case_id == case.case_id
            and hmac.compare_digest(persisted.case_sha256, case.case_sha256)
        ),
        "incident_v6_observed": (
            case.schema_version == AGENT_KERNEL_INCIDENT_CASE_SCHEMA_VERSION
        ),
        "worker_execution_plan_receipt_observed": (
            case.worker_execution_plan_receipt is not None
        ),
        "council_arbitration_receipt_observed": (
            case.council_arbitration_receipt is not None
        ),
        "autonomy_guard_receipt_observed": case.autonomy_guard_receipt is not None,
        "decision_packet_v3_observed": packet.schema_version == DECISION_PACKET_V3,
        "control_plane_case_binding_verified": (
            control_plane.case_id == case.case_id
            and hmac.compare_digest(control_plane.case_sha256, case.case_sha256)
            and hmac.compare_digest(
                packet.control_plane_sha256,
                control_plane.bundle_sha256,
            )
        ),
        "expected_case_status_observed": case.status.value == expected["case_status"],
        "dynamic_branch_floor_observed": (
            case.dynamic_branch_count >= expected["minimum_dynamic_branch_count"]
        ),
        "failed_worker_floor_observed": (
            len(failed_receipts) >= expected["minimum_failed_worker_count"]
        ),
        "required_issue_codes_observed": (
            set(expected["required_issue_codes"]) <= issue_codes
        ),
        "required_dynamic_roles_observed": (
            set(expected["required_dynamic_roles"]) <= completed_roles
        ),
        "truth_not_present_in_runtime_request": (
            "expected" not in case.request.model_dump(mode="json")
        ),
        "human_only_fail_closed_boundary": (
            case.human_approval_required
            and not case.production_release_allowed
            and not case.machine_write_permitted
            and not case.direct_equipment_control_permitted
            and not packet.production_release_allowed
            and not packet.machine_write_permitted
        ),
    }


def _execute_fixture(root: Path, fixture: dict[str, Any]) -> dict[str, Any]:
    service, actor, task_id = _setup_completed_gate_task(
        root,
        worker_registry=_registry_for_fixture(fixture),
    )
    try:
        request = _request_for_fixture(fixture)
        case = service.create_industrial_incident_case(
            actor,
            task_id,
            request,
            idempotency_key=f"dynamicbench-v4-{fixture['fixture_id'].lower()}",
        )
        persisted = service.get_industrial_incident_case(actor, task_id, case.case_id)
        envelope = service.get_industrial_incident_audit_envelope(
            actor, task_id, case.case_id
        )
        control_plane = service.get_industrial_incident_control_plane(
            actor, task_id, case.case_id
        )
        packet = service.get_industrial_incident_decision_packet(
            actor, task_id, case.case_id
        )
        assertions = _assertions_for_record(
            fixture=fixture,
            case=case,
            persisted=persisted,
            packet=packet,
            control_plane=control_plane,
        )
        completed_roles = sorted(
            item.agent_role
            for item in case.agent_actions
            if item.dynamic and item.status == "COMPLETED"
        )
        failed_roles = sorted(
            item.worker_role for item in case.worker_receipts if item.status == "FAILED"
        )
        issue_codes = sorted({item.issue_code for item in case.evidence_issues})
        stable = {
            "fixture_id": fixture["fixture_id"],
            "scenario_class": fixture["scenario_class"],
            "production_route": PRODUCTION_ROUTE,
            "runner_identity": (
                f"{run_agentic_demo.__module__}.{run_agentic_demo.__name__}"
            ),
            "truth_delivery_to_runtime": False,
            "task_execution_status": "COMPLETED",
            "case_schema_version": case.schema_version,
            "case_status": case.status.value,
            "case_recommendation": case.recommendation.value,
            "case_sha256": case.case_sha256,
            "dynamic_branch_count": case.dynamic_branch_count,
            "completed_dynamic_roles": completed_roles,
            "failed_worker_roles": failed_roles,
            "worker_receipt_count": len(case.worker_receipts),
            "issue_codes": issue_codes,
            "decision_packet_schema_version": packet.schema_version,
            "decision_packet_sha256": packet.packet_sha256,
            "control_plane_sha256": control_plane.bundle_sha256,
            "governed_audit_envelope_sha256": envelope.audit_root.value,
            "actual_external_model_call_count": case.external_model_call_count,
            "production_release_allowed": case.production_release_allowed,
            "assertions": assertions,
            "passed": all(assertions.values()),
        }
        return {
            **stable,
            "record_sha256": _framed_sha256(_HASH_DOMAINS["record"], stable),
        }
    finally:
        service.close(wait=True)


def _metrics(records: list[dict[str, Any]]) -> dict[str, Any]:
    return {
        "fixed_fixture_denominator": len(_FIXTURE_MANIFEST),
        "product_service_execution_count": len(records),
        "passed_count": sum(bool(item["passed"]) for item in records),
        "incident_v6_count": sum(
            item["case_schema_version"] == AGENT_KERNEL_INCIDENT_CASE_SCHEMA_VERSION
            for item in records
        ),
        "decision_packet_v3_count": sum(
            item["decision_packet_schema_version"] == DECISION_PACKET_V3
            for item in records
        ),
        "tool_failure_fixture_count": sum(
            item["scenario_class"] == "tool_failure" for item in records
        ),
        "tool_failure_recovered_fail_closed_count": sum(
            item["scenario_class"] == "tool_failure"
            and item["passed"]
            and not item["production_release_allowed"]
            for item in records
        ),
        "unsafe_production_release_count": sum(
            bool(item["production_release_allowed"]) for item in records
        ),
        "actual_external_model_call_count": sum(
            int(item["actual_external_model_call_count"]) for item in records
        ),
    }


def _comparison_binding(path: Path) -> dict[str, Any]:
    report = load_dynamic_replanning_benchmark_report(path)
    return {
        "benchmark_id": report["benchmark_id"],
        "schema_version": report["schema_version"],
        "status": report["status"],
        "verdict": report["verdict"],
        "sealed_report_sha256": report["sealed_report_sha256"],
        "file_sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
        "relationship": (
            "V3_PROVES_DETERMINISTIC_PAIRED_ORCHESTRATION;"
            "V4_PROVES_PRODUCTION_RUNTIME_BRIDGE;CLAIMS_MUST_NOT_BE_POOLED"
        ),
    }


def build_dynamic_benchmark_v4_report(
    *,
    scratch_root: str | Path,
    v3_report_path: str | Path,
) -> dict[str, Any]:
    """Execute and seal the v4 ProductService/Incident-v6 integration grid."""

    scratch = Path(scratch_root).expanduser().resolve()
    scratch.mkdir(parents=True, exist_ok=True)
    if any(scratch.iterdir()):
        raise DynamicBenchmarkV4ValidationError("v4 scratch root must be empty")
    fixtures = build_dynamic_benchmark_v4_fixtures()
    records = [
        _execute_fixture(scratch / fixture["fixture_id"], fixture)
        for fixture in fixtures
    ]
    metrics = _metrics(records)
    comparison = _comparison_binding(Path(v3_report_path).expanduser().resolve())
    report_without_seal = {
        "schema_version": SCHEMA_VERSION,
        "benchmark_id": BENCHMARK_ID,
        "status": "PASS" if metrics["passed_count"] == len(fixtures) else "FAIL",
        "verdict": "PRODUCTION_RUNTIME_BRIDGE_VERIFIED_ON_FROZEN_LOCAL_FIXTURES",
        "production_route": PRODUCTION_ROUTE,
        "fixture_manifest": fixtures,
        "fixture_manifest_sha256": _framed_sha256(
            _HASH_DOMAINS["fixture_manifest"], fixtures
        ),
        "records": records,
        "records_sha256": _framed_sha256(_HASH_DOMAINS["records"], records),
        "metrics": metrics,
        "metrics_sha256": _framed_sha256(_HASH_DOMAINS["metrics"], metrics),
        "dynamicbench_v3_comparison_binding": comparison,
        "dynamicbench_v3_comparison_binding_sha256": _framed_sha256(
            _HASH_DOMAINS["comparison"], comparison
        ),
        "data_source_status": "FROZEN_SYNTHETIC_FIXTURES",
        "industrial_effectiveness_status": "NOT_EVALUATED",
        "production_deployment_status": "NOT_CONNECTED",
        "claim_boundary": CLAIM_BOUNDARY,
    }
    report = {
        **report_without_seal,
        "sealed_report_sha256": _framed_sha256(
            _HASH_DOMAINS["report"], report_without_seal
        ),
    }
    validate_dynamic_benchmark_v4_report(report)
    return report


def _verify_hash(payload: object, digest: object, domain: str) -> None:
    expected = _framed_sha256(domain, payload)
    if not isinstance(digest, str) or not hmac.compare_digest(expected, digest):
        raise DynamicBenchmarkV4ValidationError("v4 digest mismatch")


def validate_dynamic_benchmark_v4_report(report: dict[str, Any]) -> None:
    """Validate all v4 hashes and the frozen production-runtime contract."""

    if report.get("schema_version") != SCHEMA_VERSION:
        raise DynamicBenchmarkV4ValidationError("v4 schema mismatch")
    if report.get("benchmark_id") != BENCHMARK_ID:
        raise DynamicBenchmarkV4ValidationError("v4 benchmark identity mismatch")
    payload = {
        key: value for key, value in report.items() if key != "sealed_report_sha256"
    }
    _verify_hash(payload, report.get("sealed_report_sha256"), _HASH_DOMAINS["report"])
    fixtures = report.get("fixture_manifest")
    records = report.get("records")
    metrics = report.get("metrics")
    comparison = report.get("dynamicbench_v3_comparison_binding")
    if fixtures != build_dynamic_benchmark_v4_fixtures():
        raise DynamicBenchmarkV4ValidationError("v4 fixture manifest drifted")
    if not isinstance(records, list) or len(records) != len(fixtures):
        raise DynamicBenchmarkV4ValidationError("v4 record denominator mismatch")
    _verify_hash(
        fixtures,
        report.get("fixture_manifest_sha256"),
        _HASH_DOMAINS["fixture_manifest"],
    )
    _verify_hash(records, report.get("records_sha256"), _HASH_DOMAINS["records"])
    _verify_hash(metrics, report.get("metrics_sha256"), _HASH_DOMAINS["metrics"])
    _verify_hash(
        comparison,
        report.get("dynamicbench_v3_comparison_binding_sha256"),
        _HASH_DOMAINS["comparison"],
    )
    expected_ids = [item["fixture_id"] for item in fixtures]
    if [item.get("fixture_id") for item in records] != expected_ids:
        raise DynamicBenchmarkV4ValidationError("v4 record grid drifted")
    for record in records:
        record_payload = {
            key: value for key, value in record.items() if key != "record_sha256"
        }
        _verify_hash(
            record_payload,
            record.get("record_sha256"),
            _HASH_DOMAINS["record"],
        )
        if not record.get("passed") or not all(record.get("assertions", {}).values()):
            raise DynamicBenchmarkV4ValidationError(
                f"v4 production fixture failed: {record.get('fixture_id')}"
            )
        for key in (
            "case_sha256",
            "decision_packet_sha256",
            "control_plane_sha256",
            "governed_audit_envelope_sha256",
        ):
            if not isinstance(record.get(key), str) or not _SHA256.fullmatch(
                record[key]
            ):
                raise DynamicBenchmarkV4ValidationError(f"v4 record has invalid {key}")
    expected_metrics = _metrics(records)
    if metrics != expected_metrics:
        raise DynamicBenchmarkV4ValidationError("v4 metrics drifted")
    if report.get("status") != "PASS" or metrics["passed_count"] != len(fixtures):
        raise DynamicBenchmarkV4ValidationError("v4 status is not PASS")
    if metrics["unsafe_production_release_count"] != 0:
        raise DynamicBenchmarkV4ValidationError("v4 observed an unsafe release")
    if not isinstance(comparison, dict) or comparison.get("status") != "PASS":
        raise DynamicBenchmarkV4ValidationError("v4 lacks a valid v3 binding")
    if report.get("claim_boundary") != CLAIM_BOUNDARY:
        raise DynamicBenchmarkV4ValidationError("v4 claim boundary drifted")


def write_dynamic_benchmark_v4_report(
    output_path: str | Path,
    *,
    scratch_root: str | Path,
    v3_report_path: str | Path,
    overwrite: bool = False,
) -> Path:
    """Execute v4 and write one canonical, self-verifying report."""

    output = Path(output_path).expanduser().resolve()
    if output.exists() and not overwrite:
        raise FileExistsError(f"refusing to overwrite v4 report: {output}")
    report = build_dynamic_benchmark_v4_report(
        scratch_root=scratch_root,
        v3_report_path=v3_report_path,
    )
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_bytes(_canonical_jcs_bytes(report) + b"\n")
    return output


def load_dynamic_benchmark_v4_report(path: str | Path) -> dict[str, Any]:
    report_path = Path(path).expanduser().resolve(strict=True)
    try:
        report = json.loads(report_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise DynamicBenchmarkV4ValidationError("v4 report is unreadable") from error
    if not isinstance(report, dict):
        raise DynamicBenchmarkV4ValidationError("v4 report must be an object")
    validate_dynamic_benchmark_v4_report(report)
    return report


__all__ = [
    "BENCHMARK_ID",
    "CLAIM_BOUNDARY",
    "DynamicBenchmarkV4ValidationError",
    "SCHEMA_VERSION",
    "build_dynamic_benchmark_v4_fixtures",
    "build_dynamic_benchmark_v4_report",
    "load_dynamic_benchmark_v4_report",
    "validate_dynamic_benchmark_v4_report",
    "write_dynamic_benchmark_v4_report",
]
