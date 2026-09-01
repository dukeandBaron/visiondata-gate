from __future__ import annotations

import hashlib
import json
from pathlib import Path
import zipfile

import numpy as np
from PIL import Image
from fastapi.testclient import TestClient
import pytest

import visiondata_gate.capa as capa_module
from visiondata_gate.capa import (
    ApproveRemediationPlanRequest,
    CapaStatus,
    ExecuteRemediationPlanRequest,
    SelectRemediationPlanRequest,
    build_capa_outcome_assessment,
    verify_child_run_closure,
)
from visiondata_gate.contracts import EvidenceStatus, Finding, Severity
from visiondata_gate.demo_fixtures import build_fixture_industrial_incident_request
from visiondata_gate.evidence import canonical_json_bytes
from visiondata_gate.governed_outcome import (
    OutcomeArtifactType,
    OutcomeHashDomain,
    outcome_digest_descriptor,
    verify_governed_outcome_envelope,
)
from visiondata_gate.industrial_incident import (
    IncidentHumanDecision,
    IncidentStatus,
    IndustrialIncidentDecisionRequest,
)
from visiondata_gate.incident_review_projection import (
    build_incident_review_projection,
)
from visiondata_gate.api import create_app
from visiondata_gate.product_models import (
    AuthorizeLocalSourceRequest,
    CreateProjectRequest,
    CreateTaskRequest,
    CreateUserRequest,
    CreateWorkspaceRequest,
    DataSourceKind,
    LocalSourceAuthorizationReceipt,
    RevokeLocalSourceAuthorizationRequest,
    TaskRecord,
    TaskExecutionStatus,
)
from visiondata_gate.product_service import ArtifactUnavailableError, ProductService
from visiondata_gate.task_store import ConflictError
from visiondata_gate.worker_selection import build_agent_behavior_receipt


SEED = 20_260_825


def _closure_finding(
    *,
    finding_id: str,
    code: str,
    sample_ids: list[str],
) -> Finding:
    return Finding(
        finding_id=finding_id,
        code=code,
        severity=Severity.HIGH,
        tool="deterministic-test-tool",
        sample_ids=sample_ids,
        summary="冻结合同下的原子 finding。",
        evidence={"measurement": "bounded-fixture"},
        evidence_status=EvidenceStatus.VERIFIED,
        recommended_action="RECAPTURE",
    )


def test_child_run_closure_verifies_zero_regression_and_stable_seal() -> None:
    parent_findings = [
        _closure_finding(
            finding_id="parent-blur",
            code="IMAGE_BLUR",
            sample_ids=["sample-redacted-07", "sample-redacted-11"],
        ),
        _closure_finding(
            finding_id="parent-policy",
            code="METADATA_MISMATCH",
            sample_ids=[],
        ),
    ]

    verification = verify_child_run_closure(
        parent_findings=parent_findings,
        child_findings=[],
        parent_contract_id="frozen-contract-v7",
        child_contract_id="frozen-contract-v7",
        child_decision="PASS",
        parent_evidence_sha256="a" * 64,
        child_evidence_sha256="b" * 64,
    )

    assert verification.is_zero_regression is True
    assert verification.disposition == "ZERO_REGRESSION_VERIFIED"
    assert verification.persistent_count == 0
    assert verification.regressed_count == 0
    assert verification.strictly_closed_count == 3
    assert verification.strictly_closed_keys == [
        "IMAGE_BLUR::sample::sample-redacted-07",
        "IMAGE_BLUR::sample::sample-redacted-11",
        "METADATA_MISMATCH::aggregate",
    ]
    assert (
        verification.verification_sha256
        == hashlib.sha256(
            canonical_json_bytes(
                verification.model_dump(mode="json", exclude={"verification_sha256"})
            )
        ).hexdigest()
    )


def test_child_run_closure_detects_same_code_on_new_redacted_sample() -> None:
    parent = _closure_finding(
        finding_id="parent-offset",
        code="ANNOTATION_OFFSET",
        sample_ids=["sample-redacted-old"],
    )
    child = _closure_finding(
        finding_id="child-offset-new-measurement",
        code="ANNOTATION_OFFSET",
        sample_ids=["sample-redacted-new"],
    )

    verification = verify_child_run_closure(
        parent_findings=[parent],
        child_findings=[child],
        parent_contract_id="frozen-contract-v9",
        child_contract_id="frozen-contract-v9",
        child_decision="QUARANTINE",
        parent_evidence_sha256="c" * 64,
        child_evidence_sha256="d" * 64,
    )

    assert verification.is_zero_regression is False
    assert verification.disposition == "REGRESSION_DETECTED"
    assert verification.strictly_closed_keys == [
        "ANNOTATION_OFFSET::sample::sample-redacted-old"
    ]
    assert verification.persistent_keys == []
    assert verification.regressed_keys == [
        "ANNOTATION_OFFSET::sample::sample-redacted-new"
    ]
    assert verification.regressed_count == 1


def _write_metadata(path: Path, category: str, count: int) -> None:
    headers = ["数据集名称", "样本总数", "good(train)", "good(test)", "NG(test)"]
    values: list[str | int] = [category, count * 3, count, count, count]

    def cell(column: str, row: int, value: str | int) -> str:
        if isinstance(value, int):
            return f'<c r="{column}{row}"><v>{value}</v></c>'
        return f'<c r="{column}{row}" t="inlineStr"><is><t>{value}</t></is></c>'

    columns = ["A", "B", "C", "D", "E"]
    sheet = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">'
        '<sheetData><row r="1">'
        + "".join(
            cell(column, 1, value)
            for column, value in zip(columns, headers, strict=True)
        )
        + '</row><row r="2">'
        + "".join(
            cell(column, 2, value)
            for column, value in zip(columns, values, strict=True)
        )
        + "</row></sheetData></worksheet>"
    )
    path.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(path, "w") as bundle:
        bundle.writestr("xl/worksheets/sheet1.xml", sheet)


def _selected_names(prefix: str, bucket: str, count: int = 4) -> set[str]:
    paths = [f"private-widget/{prefix}/{bucket}-{index}.png" for index in range(count)]
    ordered = sorted(
        paths,
        key=lambda value: hashlib.sha256(f"{SEED}\0{value}".encode()).hexdigest(),
    )
    return {Path(value).name for value in ordered[:2]}


def _build_recoverable_source(root: Path) -> Path:
    release = root / "omni-private-release"
    category = "private-widget"
    buckets = (
        ("train/good", "train"),
        ("test/good", "test-good"),
        ("test/scratch", "test-bad"),
    )
    for bucket_index, (relative_root, name_prefix) in enumerate(buckets):
        selected = _selected_names(relative_root, name_prefix)
        for index in range(4):
            name = f"{name_prefix}-{index}.png"
            destination = release / category / relative_root / name
            destination.parent.mkdir(parents=True, exist_ok=True)
            if name in selected:
                image = Image.new("RGB", (32, 32), color=(90, 90, 90))
            else:
                rng = np.random.default_rng(10_000 + bucket_index * 100 + index)
                payload = rng.integers(45, 210, size=(32, 32, 3), dtype=np.uint8)
                image = Image.fromarray(payload, mode="RGB")
            image.save(destination)
            if relative_root == "test/scratch":
                mask = np.zeros((32, 32), dtype=np.uint8)
                mask[8:24, 8:24] = 255
                mask_path = release / category / "ground_truth/scratch" / name
                mask_path.parent.mkdir(parents=True, exist_ok=True)
                Image.fromarray(mask, mode="L").save(mask_path)
    _write_metadata(release / "official.xlsx", category, 4)
    return release


def _provision_parent(
    tmp_path: Path,
) -> tuple[ProductService, str, TaskRecord, LocalSourceAuthorizationReceipt, Path]:
    allowed = tmp_path / "allowed"
    allowed.mkdir()
    release = _build_recoverable_source(allowed)
    service = ProductService(
        tmp_path / "product",
        local_source_allow_roots=[allowed],
        recover_interrupted=False,
    )
    user = service.create_user(CreateUserRequest(display_name="CAPA Owner"))
    workspace = service.create_workspace(
        CreateWorkspaceRequest(name="CAPA Workspace", owner_user_id=user.user_id)
    )
    project = service.create_project(
        user.user_id,
        CreateProjectRequest(
            workspace_id=workspace.workspace_id,
            name="Derived recovery",
            description="Bounded Omni CAPA child-run test.",
            source_kind=DataSourceKind.LOCAL_AUTHORIZED_DIRECTORY,
        ),
    )
    source = service.authorize_local_source(
        user.user_id,
        AuthorizeLocalSourceRequest(
            workspace_id=workspace.workspace_id,
            display_name="Authorized private Omni fixture",
            root_path=str(release),
            source_archive_sha256="a" * 64,
            purpose="用于本地私有派生版本和同合同复验测试。",
            rights_basis="操作者授权本地只读检查与私有派生处理，禁止原始数据再分发。",
            operator_attests_authorized_use=True,
        ),
    )
    parent = service.create_task(
        user.user_id,
        CreateTaskRequest(
            project_id=project.project_id,
            goal="审核该授权工业视觉批次并形成可执行整改闭环。",
            seed=SEED,
            source_kind=DataSourceKind.LOCAL_AUTHORIZED_DIRECTORY,
            source_id=source.source_id,
            allowed_tools=[
                "image_quality",
                "duplicate_leakage",
                "annotation_integrity",
                "coverage_matrix",
            ],
        ),
        auto_start=False,
    )
    parent = service.run_task_sync(parent.task_id)
    assert parent.execution_status is TaskExecutionStatus.COMPLETED
    assert parent.final_decision != "PASS"
    return service, user.user_id, parent, source, release


def test_capa_executes_only_on_derived_version_and_creates_child_run(
    tmp_path: Path,
) -> None:
    service, actor, parent, source, release = _provision_parent(tmp_path)
    parent_evidence_before = parent.evidence_sha256
    source_files_before = sorted(
        (path.relative_to(release).as_posix(), path.read_bytes())
        for path in release.rglob("*")
        if path.is_file()
    )

    delivery = service.industrial_delivery_receipt(actor, parent.task_id)
    full_plan = next(
        plan
        for plan in delivery.remediation_plans
        if plan.strategy == "full_evidence_closure"
    )
    selected = service.select_remediation_plan(
        actor,
        parent.task_id,
        SelectRemediationPlanRequest(
            plan_id=full_plan.plan_id,
            plan_sha256=full_plan.plan_sha256,
            note="选择完整闭环方案，保留失败结果并创建独立 child Run。",
        ),
    )
    assert selected.status is CapaStatus.SELECTED
    approved = service.approve_remediation_plan(
        actor,
        parent.task_id,
        selected.case_id,
        ApproveRemediationPlanRequest(
            note="批准只在私有派生版本执行隔离、回填和 metadata 对账。",
            approved_work_order_ids=full_plan.selected_work_order_ids,
            operator_attests_derived_processing=True,
            source_mutation_permitted=False,
            raw_redistribution_allowed=False,
            max_copied_images=240,
        ),
    )
    assert approved.status is CapaStatus.APPROVED
    assert approved.approval is not None
    assert approved.approval.remediation_plan_sha256 == full_plan.plan_sha256
    assert approved.approval.planned_copy_count == 6
    assert approved.approval.source_authorization_event_sha256 == (
        source.latest_authorization_event_sha256
    )

    completed = service.execute_remediation_plan(
        actor,
        parent.task_id,
        selected.case_id,
        ExecuteRemediationPlanRequest(
            reviewer_identity="QA-017 李工",
            note="已复核批准绑定、来源一致性与派生副本执行边界。",
            expected_approval_binding_sha256=approved.approval.binding_sha256,
            operator_attests_derived_processing=True,
            source_mutation_permitted=False,
            raw_redistribution_allowed=False,
        ),
    )
    assert completed.recovery is not None
    assert completed.execution is not None
    assert completed.execution_authorization is not None
    assert completed.derived_version is not None
    assert completed.final_queue is not None
    assert completed.execution.parent_immutable is True
    assert completed.execution.schema_version == "visiondata-gate.capa-execution.v2"
    assert completed.execution_authorization.reviewer_identity == "QA-017 李工"
    assert completed.execution.execution_authorization_sha256 == (
        completed.execution_authorization.authorization_sha256
    )
    assert completed.execution.parent_evidence_sha256_before == parent_evidence_before
    assert completed.execution.parent_evidence_sha256_after == parent_evidence_before
    assert completed.derived_version.parent_source_mutated is False
    assert completed.derived_version.source_assets_copied_into_product is True
    assert completed.derived_version.raw_redistribution_allowed is False
    assert completed.recovery.production_release_allowed is False
    assert completed.recovery.recovery_success is True
    assert completed.recovery.child_verification is not None
    assert completed.recovery.child_verification.is_zero_regression is True
    assert completed.recovery.child_verification.regressed_count == 0
    assert completed.recovery.child_verification.verification_sha256 == (
        hashlib.sha256(
            canonical_json_bytes(
                completed.recovery.child_verification.model_dump(
                    mode="json", exclude={"verification_sha256"}
                )
            )
        ).hexdigest()
    )
    assert completed.status is CapaStatus.RECOVERED_TO_HUMAN_REVIEW
    assert completed.recovery.child_finding_count < (
        completed.recovery.parent_finding_count
    )
    assert completed.recovery.remaining_work_order_count == 0
    recovery_payload = completed.recovery.model_dump(
        mode="json",
        exclude={"receipt_sha256"},
    )
    recovery_payload["recovery_success"] = False
    with pytest.raises(ValueError, match="status and success flag diverged"):
        capa_module.CapaRecoveryReceipt(
            **recovery_payload,
            receipt_sha256=hashlib.sha256(
                canonical_json_bytes(recovery_payload)
            ).hexdigest(),
        )
    final_queue_payload = completed.final_queue.model_dump(
        mode="json",
        exclude={"queue_sha256"},
    )
    final_queue_payload["open_count"] = 1
    final_queue_payload["closed_count"] -= 1
    with pytest.raises(ValueError, match="counts do not match item states"):
        capa_module.CapaResponsibilityQueue(
            **final_queue_payload,
            queue_sha256=hashlib.sha256(
                canonical_json_bytes(final_queue_payload)
            ).hexdigest(),
        )
    assert completed.execution.child_task_id != parent.task_id
    assert (
        service.task_lineage(actor, completed.execution.child_task_id).edge_count == 1
    )
    assert service.get_task(actor, parent.task_id).evidence_sha256 == (
        parent_evidence_before
    )
    assessment = service.capa_outcome_assessment(
        actor, parent.task_id, selected.case_id
    )
    assert assessment.release_feasibility_status == (
        "OBSERVED_RECOVERY_TO_HUMAN_REVIEW"
    )
    assert assessment.minimum_observed_relative_effort_points == (
        full_plan.relative_effort_points
    )
    assert assessment.observed_release_candidate_found is True
    assert (
        sum(
            item.execution_status == "EXECUTED" for item in assessment.plan_observations
        )
        == 1
    )
    failed_recovery = completed.recovery.model_copy(
        update={
            "status": "STILL_BLOCKED",
            "recovery_success": False,
            "remaining_work_order_count": 1,
        }
    )
    failed_report = completed.model_copy(update={"recovery": failed_recovery})
    failed_assessment = build_capa_outcome_assessment(
        failed_report, delivery.remediation_plans
    )
    assert failed_assessment.release_feasibility_status == (
        "NO_FEASIBLE_RELEASE_OBSERVED_IN_CURRENT_AUTHORIZED_POOL"
    )
    assert failed_assessment.minimum_observed_relative_effort_points is None
    client = TestClient(
        create_app(service, ensure_demo_tenant=False, enable_account_bootstrap=False)
    )
    headers = {"X-Actor-User-Id": actor}
    fetched = client.get(
        f"/v1/tasks/{parent.task_id}/capa-cases/{selected.case_id}",
        headers=headers,
    )
    assert fetched.status_code == 200
    assert fetched.json()["status"] == "RECOVERED_TO_HUMAN_REVIEW"
    fetched_sha256 = hashlib.sha256(canonical_json_bytes(fetched.json())).hexdigest()
    assert fetched.headers["x-content-sha256"] == fetched_sha256
    assert fetched.headers["etag"] == f'"{fetched_sha256}"'
    outcome_response = client.get(
        f"/v1/tasks/{parent.task_id}/capa-cases/{selected.case_id}/outcome-assessment",
        headers=headers,
    )
    assert outcome_response.status_code == 200
    assert outcome_response.json()["observed_release_candidate_found"] is True
    assert (
        outcome_response.headers["x-content-sha256"]
        == (outcome_response.json()["assessment_sha256"])
    )
    assert outcome_response.headers["etag"] == (
        f'"{outcome_response.json()["assessment_sha256"]}"'
    )
    assert outcome_response.headers["cache-control"] == "private, no-store"
    replay_response = client.get(
        f"/v1/tasks/{parent.task_id}/capa-cases/{selected.case_id}/causal-replay",
        headers=headers,
    )
    assert replay_response.status_code == 200
    replay = replay_response.json()
    assert [step["step_id"] for step in replay["steps"]] == [
        "T0",
        "T1",
        "T2",
        "T3",
        "T4",
    ]
    assert replay["current_step_id"] == "T4"
    assert replay["read_only"] is True
    assert replay["production_release_allowed"] is False
    child_gate = service.read_evidence_zip_json(
        actor,
        completed.execution.child_task_id,
        "final/gate_result.json",
    )
    assert replay["steps"][4]["evidence_digests"]["child_gate_sha256"] == (
        hashlib.sha256(canonical_json_bytes(child_gate)).hexdigest()
    )
    assert replay_response.headers["x-content-sha256"] == replay["report_sha256"]
    assert replay_response.headers["cache-control"] == "private, no-store"
    listed = client.get(f"/v1/tasks/{parent.task_id}/capa-cases", headers=headers)
    assert listed.status_code == 200
    assert [item["case_id"] for item in listed.json()] == [selected.case_id]
    listed_sha256 = hashlib.sha256(canonical_json_bytes(listed.json())).hexdigest()
    assert listed.headers["x-content-sha256"] == listed_sha256
    assert listed.headers["etag"] == f'"{listed_sha256}"'
    source_files_after = sorted(
        (path.relative_to(release).as_posix(), path.read_bytes())
        for path in release.rglob("*")
        if path.is_file()
    )
    assert source_files_after == source_files_before
    parent_archive = service.evidence_path(actor, parent.task_id)
    with parent_archive.open("ab") as stream:
        stream.write(b"tampered-after-successful-replay")
    with pytest.raises(ArtifactUnavailableError, match="integrity check failed"):
        service.capa_causal_replay(actor, parent.task_id, selected.case_id)
    service.close(wait=True)


def test_incident_decision_executes_exact_capa_and_resumes_with_child_evidence(
    tmp_path: Path,
) -> None:
    service, actor, parent, _, _ = _provision_parent(tmp_path)
    request = build_fixture_industrial_incident_request().model_copy(
        update={"max_dynamic_workers": 12}
    )
    incident = service.create_industrial_incident_case(actor, parent.task_id, request)
    delivery = service.industrial_delivery_receipt(actor, parent.task_id)
    full_plan = next(
        plan
        for plan in delivery.remediation_plans
        if plan.strategy == "full_evidence_closure"
    )
    assert full_plan.plan_id in incident.linked_remediation_plan_ids

    decision = service.record_industrial_incident_decision(
        actor,
        parent.task_id,
        incident.case_id,
        IndustrialIncidentDecisionRequest(
            bound_case_sha256=incident.case_sha256,
            decision=IncidentHumanDecision.SELECT_REMEDIATION_PLAN,
            note="具名质量负责人选择完整证据闭环方案，仅授权私有派生处理与独立复验。",
            selected_remediation_plan_id=full_plan.plan_id,
            operator_attests_reviewed_evidence=True,
        ),
    )
    assert decision.linked_capa_case_id is not None

    approved = service.approve_remediation_plan(
        actor,
        parent.task_id,
        decision.linked_capa_case_id,
        ApproveRemediationPlanRequest(
            note="批准在私有派生版本执行冻结方案，不修改父版本、不允许原始数据再分发。",
            approved_work_order_ids=full_plan.selected_work_order_ids,
            operator_attests_derived_processing=True,
            source_mutation_permitted=False,
            raw_redistribution_allowed=False,
            max_copied_images=240,
        ),
    )
    completed = service.execute_remediation_plan(
        actor, parent.task_id, decision.linked_capa_case_id
    )
    assert approved.approval is not None
    assert completed.derived_version is not None
    assert completed.execution is not None
    assert completed.recovery is not None

    outcome = service.get_governed_outcome_envelope(
        actor, parent.task_id, decision.linked_capa_case_id
    )
    verify_governed_outcome_envelope(outcome)
    assert outcome.subject.incident_case_id == incident.case_id
    assert outcome.subject.capa_case_id == decision.linked_capa_case_id
    assert outcome.subject.child_task_id == completed.execution.child_task_id
    assert [item.artifact_type for item in outcome.artifacts] == list(
        OutcomeArtifactType
    )
    assert outcome.result.workflow_status == "RECOVERED_TO_HUMAN_REVIEW"
    assert outcome.result.production_release_allowed is False
    assert outcome.result.root_cause_status == "NOT_ESTABLISHED"
    assert outcome.signature.status == "NOT_CONFIGURED"

    client = TestClient(
        create_app(service, ensure_demo_tenant=False, enable_account_bootstrap=False)
    )
    outcome_response = client.get(
        f"/v1/tasks/{parent.task_id}/capa-cases/"
        f"{decision.linked_capa_case_id}/governed-outcome-envelope",
        headers={"X-Actor-User-Id": actor},
    )
    assert outcome_response.status_code == 200
    assert outcome_response.headers["x-content-sha256"] == outcome.outcome_root.value
    assert outcome_response.headers["cache-control"] == "private, no-store"

    resumed_request = build_fixture_industrial_incident_request(revision=2).model_copy(
        update={
            "max_dynamic_workers": 12,
            "supersedes_case_id": incident.case_id,
            "expected_parent_case_sha256": incident.case_sha256,
            "authorizing_decision_id": decision.decision_id,
        }
    )
    child = service.resume_industrial_incident_case(
        actor, parent.task_id, incident.case_id, resumed_request
    )
    capa_evidence = child.gate_context.capa_evidence
    assert child.parent_case_id == incident.case_id
    assert child.authorizing_decision_id == decision.decision_id
    assert capa_evidence is not None
    assert capa_evidence.capa_case_id == decision.linked_capa_case_id
    assert capa_evidence.selection_sha256 == completed.selection.selection_sha256
    assert capa_evidence.approval_binding_sha256 == approved.approval.binding_sha256
    assert (
        capa_evidence.derived_version_receipt_sha256
        == completed.derived_version.receipt_sha256
    )
    assert capa_evidence.execution_receipt_sha256 == completed.execution.receipt_sha256
    assert capa_evidence.recovery_receipt_sha256 == completed.recovery.receipt_sha256
    assert capa_evidence.child_task_id == completed.recovery.child_task_id
    assert (
        capa_evidence.child_evidence_sha256 == completed.recovery.child_evidence_sha256
    )
    assert capa_evidence.recovery_success is True
    assert child.status is IncidentStatus.INVESTIGATION_REQUIRED
    assert "工艺与视觉解释仍有冲突" in child.recommendation_reason
    assert child.production_release_allowed is False
    phase_events = service.list_industrial_incident_phase_events(
        actor, parent.task_id, child.case_id
    )
    assert phase_events[0].phase == "PLAN"
    assert phase_events[-1].phase == "INTERRUPT"
    assert phase_events[-1].status == "PAUSED"
    assert phase_events[-1].error_code == "HUMAN_DECISION_REQUIRED"
    assert sum(item.phase == "ACT" for item in phase_events) >= 1
    assert {
        item.invocation_id
        for item in phase_events
        if item.invocation_id.startswith("worker_invocation_")
    } == {item.invocation_id for item in child.worker_receipts}
    assert all(
        current.prev_event_sha256 == previous.event_sha256
        for previous, current in zip(phase_events, phase_events[1:], strict=False)
    )

    review_projection = service.get_industrial_incident_review_projection(
        actor,
        parent.task_id,
        incident.case_id,
    )
    assert review_projection.transport_source_mode == "LIVE"
    assert review_projection.evidence_source_mode == "REPLAY"
    behavior = build_agent_behavior_receipt(incident.worker_selection_receipt)
    assert review_projection.agent_behavior_receipt_sha256 == behavior.receipt_sha256
    selected_reasons = {
        item.worker_id: item.reason_codes for item in review_projection.selected_workers
    }
    assert selected_reasons == {
        item.worker_id: item.reason_codes for item in behavior.selected
    }
    assert all(
        "SELECTED_WITHIN_WORKER_BUDGET" in reason_codes
        for reason_codes in selected_reasons.values()
    )
    assert review_projection.human_decisions[0].decision_id == decision.decision_id
    assert review_projection.human_decisions[0].linked_capa_case_id == (
        decision.linked_capa_case_id
    )
    assert review_projection.capa_cases[0].case_id == decision.linked_capa_case_id
    assert review_projection.capa_cases[0].child_task_id == (
        completed.execution.child_task_id
    )
    assert review_projection.capa_cases[0].child_evidence_sha256 == (
        completed.execution.child_evidence_sha256
    )
    assert review_projection.capa_cases[0].child_lineage_report_sha256 == (
        completed.execution.child_lineage_report_sha256
    )
    assert review_projection.capa_cases[0].recovery_receipt_sha256 == (
        completed.recovery.receipt_sha256
    )
    assert review_projection.child_cases[0].case_id == child.case_id
    assert review_projection.missing_linked_capa_case_ids == []
    assert review_projection.production_release_allowed is False

    child_projection = service.get_industrial_incident_review_projection(
        actor,
        parent.task_id,
        child.case_id,
    )
    assert child_projection.parent_case is not None
    assert child_projection.parent_case.case_id == incident.case_id
    assert child_projection.current_case.authorizing_decision_id == decision.decision_id
    assert (
        child_projection.current_case.authorizing_decision_sha256
        == decision.decision_sha256
    )

    missing_capa_projection = build_incident_review_projection(
        case=incident,
        related_cases=service.list_industrial_incident_cases(actor, parent.task_id),
        decisions=service.list_industrial_incident_decisions(
            actor,
            parent.task_id,
            incident.case_id,
        ),
        control_plane=service.get_industrial_incident_control_plane(
            actor,
            parent.task_id,
            incident.case_id,
        ),
        capa_cases=[],
        task_lineage=service.task_lineage(actor, parent.task_id),
    )
    assert missing_capa_projection.capa_cases == []
    assert missing_capa_projection.missing_linked_capa_case_ids == [
        decision.linked_capa_case_id
    ]

    outcome_path = (
        service._capa_case_root(parent, decision.linked_capa_case_id)
        / "governed_outcome_envelope.json"
    )
    tampered = json.loads(outcome_path.read_text(encoding="utf-8"))
    tampered["result"]["required_human_action"] = (
        "tampered but locally re-hashed outcome claim"
    )
    stable = dict(tampered)
    stable.pop("outcome_root")
    tampered["outcome_root"] = outcome_digest_descriptor(
        stable, OutcomeHashDomain.OUTCOME_ROOT
    ).model_dump(mode="json")
    outcome_path.write_text(
        json.dumps(tampered, ensure_ascii=False, sort_keys=True), encoding="utf-8"
    )
    with pytest.raises(ArtifactUnavailableError, match="differs from bound evidence"):
        service.get_governed_outcome_envelope(
            actor, parent.task_id, decision.linked_capa_case_id
        )
    execution_path = (
        service._capa_case_root(parent, decision.linked_capa_case_id) / "execution.json"
    )
    execution_payload = json.loads(execution_path.read_text(encoding="utf-8"))
    execution_payload["child_lineage_report_sha256"] = "f" * 64
    execution_stable = dict(execution_payload)
    execution_stable.pop("receipt_sha256")
    execution_payload["receipt_sha256"] = hashlib.sha256(
        canonical_json_bytes(execution_stable)
    ).hexdigest()
    execution_path.write_text(
        json.dumps(execution_payload, ensure_ascii=False, sort_keys=True),
        encoding="utf-8",
    )
    with pytest.raises(
        ArtifactUnavailableError,
        match="child evidence or lineage binding failed",
    ):
        service.get_capa_case(actor, parent.task_id, decision.linked_capa_case_id)
    service.close(wait=True)


def test_capa_artifact_tampering_fails_closed(tmp_path: Path) -> None:
    service, actor, parent, _, _ = _provision_parent(tmp_path)
    delivery = service.industrial_delivery_receipt(actor, parent.task_id)
    plan = delivery.remediation_plans[0]
    selected = service.select_remediation_plan(
        actor,
        parent.task_id,
        SelectRemediationPlanRequest(
            plan_id=plan.plan_id,
            plan_sha256=plan.plan_sha256,
            note="创建后验证回执篡改必须失败关闭。",
        ),
    )
    selection_path = (
        service._capa_case_root(parent, selected.case_id) / "selection.json"
    )
    payload = json.loads(selection_path.read_text(encoding="utf-8"))
    payload["selection_note"] = "tampered without recomputing the seal"
    selection_path.write_text(
        json.dumps(payload, ensure_ascii=False, sort_keys=True), encoding="utf-8"
    )

    with pytest.raises(ArtifactUnavailableError, match="integrity validation"):
        service.get_capa_case(actor, parent.task_id, selected.case_id)
    service.close(wait=True)


def test_capa_approval_binds_actual_image_copy_budget(tmp_path: Path) -> None:
    service, actor, parent, _, _ = _provision_parent(tmp_path)
    delivery = service.industrial_delivery_receipt(actor, parent.task_id)
    plan = next(
        item
        for item in delivery.remediation_plans
        if item.strategy == "containment_first"
    )
    selected = service.select_remediation_plan(
        actor,
        parent.task_id,
        SelectRemediationPlanRequest(
            plan_id=plan.plan_id,
            plan_sha256=plan.plan_sha256,
            note="用冻结 Gate 图像分母约束复制预算。",
        ),
    )
    client = TestClient(
        create_app(service, ensure_demo_tenant=False, enable_account_bootstrap=False)
    )
    incomplete = client.get(
        f"/v1/tasks/{parent.task_id}/capa-cases/{selected.case_id}/outcome-assessment",
        headers={"X-Actor-User-Id": actor},
    )
    assert incomplete.status_code == 409
    assert incomplete.json()["error"]["code"] == "artifact_unavailable"
    with pytest.raises(ConflictError, match="image copy budget"):
        service.approve_remediation_plan(
            actor,
            parent.task_id,
            selected.case_id,
            ApproveRemediationPlanRequest(
                note="故意设置低于冻结 6 图像分母的预算。",
                approved_work_order_ids=plan.selected_work_order_ids,
                operator_attests_derived_processing=True,
                max_copied_images=5,
            ),
        )
    assert (
        service.get_capa_case(actor, parent.task_id, selected.case_id).status
        is CapaStatus.SELECTED
    )
    service.close(wait=True)


def test_capa_approval_is_invalid_after_source_revocation(tmp_path: Path) -> None:
    service, actor, parent, source, _ = _provision_parent(tmp_path)
    delivery = service.industrial_delivery_receipt(actor, parent.task_id)
    plan = next(
        item
        for item in delivery.remediation_plans
        if item.strategy == "containment_first"
    )
    selected = service.select_remediation_plan(
        actor,
        parent.task_id,
        SelectRemediationPlanRequest(
            plan_id=plan.plan_id,
            plan_sha256=plan.plan_sha256,
            note="先批准，再验证授权撤销会使批准失效。",
        ),
    )
    approved = service.approve_remediation_plan(
        actor,
        parent.task_id,
        selected.case_id,
        ApproveRemediationPlanRequest(
            note="只批准私有派生版本处理。",
            approved_work_order_ids=plan.selected_work_order_ids,
            operator_attests_derived_processing=True,
            max_copied_images=6,
        ),
    )
    assert approved.status is CapaStatus.APPROVED
    service.revoke_local_source_authorization(
        actor,
        source.source_id,
        RevokeLocalSourceAuthorizationRequest(
            reason="撤回后续派生处理授权，旧 CAPA 批准必须失败关闭。",
            expected_latest_event_sha256=source.latest_authorization_event_sha256,
        ),
    )
    with pytest.raises(ConflictError, match="source authorization invalidated"):
        service.execute_remediation_plan(actor, parent.task_id, selected.case_id)
    assert not (service.product_root / "derived_versions").exists()
    service.close(wait=True)


def test_capa_derived_publication_is_atomic_and_retryable(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    service, actor, parent, _, _ = _provision_parent(tmp_path)
    delivery = service.industrial_delivery_receipt(actor, parent.task_id)
    plan = next(
        item
        for item in delivery.remediation_plans
        if item.strategy == "containment_first"
    )
    selected = service.select_remediation_plan(
        actor,
        parent.task_id,
        SelectRemediationPlanRequest(
            plan_id=plan.plan_id,
            plan_sha256=plan.plan_sha256,
            note="验证复制工具失败时不发布半成品派生版本。",
        ),
    )
    approved = service.approve_remediation_plan(
        actor,
        parent.task_id,
        selected.case_id,
        ApproveRemediationPlanRequest(
            note="只批准同盘 staging 后的私有派生版本。",
            approved_work_order_ids=plan.selected_work_order_ids,
            operator_attests_derived_processing=True,
            max_copied_images=6,
        ),
    )
    assert approved.status is CapaStatus.APPROVED

    original_copy = capa_module._copy_record
    copy_count = 0

    def fail_during_second_copy(*args: object, **kwargs: object) -> tuple[int, int]:
        nonlocal copy_count
        result = original_copy(*args, **kwargs)
        copy_count += 1
        if copy_count == 2:
            raise RuntimeError("injected copy tool failure")
        return result

    monkeypatch.setattr(capa_module, "_copy_record", fail_during_second_copy)
    with pytest.raises(RuntimeError, match="injected copy tool failure"):
        service.execute_remediation_plan(actor, parent.task_id, selected.case_id)

    publish_root = (
        service.product_root
        / "derived_versions"
        / parent.workspace_id
        / parent.project_id
        / selected.case_id
    )
    assert not publish_root.exists() or list(publish_root.iterdir()) == []
    assert (
        service.get_capa_case(actor, parent.task_id, selected.case_id).derived_version
        is None
    )

    monkeypatch.setattr(capa_module, "_copy_record", original_copy)
    completed = service.execute_remediation_plan(
        actor, parent.task_id, selected.case_id
    )
    assert completed.derived_version is not None
    assert (
        completed.derived_version.schema_version
        == "visiondata-gate.derived-data-version.v2"
    )
    assert (
        completed.derived_version.publication_mode == "SAME_FILESYSTEM_STAGING_RENAME"
    )
    assert completed.derived_version.staging_verified_before_publish is True
    assert not any(".staging-" in path.name for path in publish_root.iterdir())
    service.close(wait=True)


def test_capa_resumes_after_derived_version_was_published(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    service, actor, parent, _, _ = _provision_parent(tmp_path)
    delivery = service.industrial_delivery_receipt(actor, parent.task_id)
    plan = next(
        item
        for item in delivery.remediation_plans
        if item.strategy == "containment_first"
    )
    selected = service.select_remediation_plan(
        actor,
        parent.task_id,
        SelectRemediationPlanRequest(
            plan_id=plan.plan_id,
            plan_sha256=plan.plan_sha256,
            note="验证派生版本发布后中断能够从内嵌回执继续。",
        ),
    )
    approved = service.approve_remediation_plan(
        actor,
        parent.task_id,
        selected.case_id,
        ApproveRemediationPlanRequest(
            note="批准私有派生处理与显式恢复后的同合同 Child Run。",
            approved_work_order_ids=plan.selected_work_order_ids,
            operator_attests_derived_processing=True,
            max_copied_images=6,
        ),
    )
    assert approved.approval is not None
    execution_request = ExecuteRemediationPlanRequest(
        reviewer_identity="QA-021 周工",
        note="派生发布后仅按同一不可变授权继续 Child Run。",
        expected_approval_binding_sha256=approved.approval.binding_sha256,
        operator_attests_derived_processing=True,
    )

    original_create_child = service.create_reverification_task

    def fail_after_published_derived_version(*args: object, **kwargs: object) -> None:
        raise RuntimeError("injected interruption after derived publication")

    monkeypatch.setattr(
        service,
        "create_reverification_task",
        fail_after_published_derived_version,
    )
    with pytest.raises(
        RuntimeError, match="injected interruption after derived publication"
    ):
        service.execute_remediation_plan(
            actor, parent.task_id, selected.case_id, execution_request
        )

    interrupted = service.get_capa_case(actor, parent.task_id, selected.case_id)
    assert interrupted.status is CapaStatus.DERIVED_VERSION_READY
    assert interrupted.derived_version is not None
    assert interrupted.execution is None
    published_receipt = (
        service.product_root
        / "derived_versions"
        / parent.workspace_id
        / parent.project_id
        / selected.case_id
        / interrupted.derived_version.version_id
        / "derived_version_receipt.json"
    )
    assert published_receipt.is_file()

    monkeypatch.setattr(
        service,
        "create_reverification_task",
        original_create_child,
    )
    completed = service.execute_remediation_plan(
        actor, parent.task_id, selected.case_id, execution_request
    )
    assert completed.execution is not None
    assert completed.recovery is not None
    assert completed.derived_version == interrupted.derived_version
    assert completed.execution.derived_version_id == (
        interrupted.derived_version.version_id
    )
    assert completed.execution_authorization is not None
    assert completed.execution.schema_version == "visiondata-gate.capa-execution.v2"
    assert completed.recovery.production_release_allowed is False
    service.close(wait=True)
