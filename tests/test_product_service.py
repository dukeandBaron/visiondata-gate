from __future__ import annotations

import hashlib
import json
import sqlite3
import zipfile
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from visiondata_gate.api import create_app
from visiondata_gate.approved_experience import (
    ExperienceCandidateType,
    build_experience_candidate,
    build_memory_admission_envelope,
    build_source_case_evidence_binding,
    decide_experience_approval,
    initialize_experience,
    memory_admission_envelope_jsonl,
    promote_experience,
    record_experience_replay,
    record_experience_shadow,
)
from visiondata_gate.audit_envelope import (
    AuditHashDomain,
    canonical_jcs_bytes,
    domain_separated_sha256,
    parse_governed_audit_envelope_json,
    verify_governed_audit_case_directory,
)
from visiondata_gate.cli import main as cli_main
from visiondata_gate.contracts import GateDecision
from visiondata_gate.demo_fixtures import build_fixture_industrial_incident_request
from visiondata_gate.evidence import canonical_json_bytes, write_canonical_json
from visiondata_gate.incident_model_planner import IncidentModelMode
from visiondata_gate.lineage import CreateReverificationRequest
from visiondata_gate.industrial_incident import (
    IncidentHumanDecision,
    IndustrialIncidentDecisionRequest,
)
from visiondata_gate.incident_runtime_profile import (
    IncidentMemoryMode,
    IncidentRuntimeProfile,
)
from visiondata_gate.governed_context import ApprovedMemoryContent, MemoryScope
from visiondata_gate.product_models import (
    CreateProjectRequest,
    CreateTaskRequest,
    CreateUserRequest,
    CreateWorkspaceRequest,
    DataSourceKind,
    TaskExecutionStatus,
    TaskInterventionAction,
    TaskInterventionRequest,
)
from visiondata_gate.product_service import (
    ArtifactUnavailableError,
    IncidentIdempotencyConflictError,
    ProductService,
    UnsupportedSourceError,
)
from visiondata_gate.task_store import ConflictError
from tests.support.product_run_stub import (
    LifecycleProductRunner,
    make_product_lifecycle_stub_runner,
)


def _setup(service: ProductService) -> tuple[str, str]:
    user = service.create_user(CreateUserRequest(display_name="Local Operator"))
    workspace = service.create_workspace(
        CreateWorkspaceRequest(name="Evaluation", owner_user_id=user.user_id)
    )
    project = service.create_project(
        user.user_id,
        CreateProjectRequest(workspace_id=workspace.workspace_id, name="Image Gate"),
    )
    return user.user_id, project.project_id


def _fake_runner(
    final_decision: GateDecision = GateDecision.PASS,
) -> LifecycleProductRunner:
    """Return a contract-valid lifecycle stub, never Agent E2E evidence."""

    return make_product_lifecycle_stub_runner(final_decision)


def _strict_memory_admission_fixture(
    path: Path,
    *,
    workspace_id: str,
    project_id: str,
):
    """Build one fully promoted historical-memory envelope for service tests."""

    def digest(label: str) -> str:
        return hashlib.sha256(label.encode("utf-8")).hexdigest()

    now = datetime(2026, 8, 26, 0, 0, tzinfo=UTC)
    source_case_id = "incident_0123456789abcdefabcd"
    scope = MemoryScope(
        site_id="factory-a-line-01",
        line_id="fixture-line-A",
    )
    candidate = build_experience_candidate(
        candidate_type=ExperienceCandidateType.WORKER_PRIORITY_HINT,
        source_case_ids=[source_case_id],
        proposal=ApprovedMemoryContent(
            pattern=("fixture-recipe-A-17 NG_RATE_DRIFT recurred after recipe change"),
            recommended_first_check="retrieve_current_normal_reference",
            avoid_first_action=(
                "Do not infer a process root cause before current-case verification"
            ),
            advisory_summary=(
                "Historical reference only; the current incident must obtain "
                "independent evidence."
            ),
        ),
        affected_scope=scope,
        required_replay_suite="industrial-incident-bench-v1",
    )
    record = initialize_experience(candidate, created_at=now)
    record = record_experience_replay(
        record,
        replay_suite_sha256=digest("strict-memory-frozen-replay-suite"),
        case_count=15,
        passed_case_count=15,
        deterministic_replay_rate=1.0,
        unsafe_closure_count=0,
        false_root_cause_count=0,
        premature_production_recovery_count=0,
        cross_site_memory_leakage_count=0,
        historical_memory_used_as_fact_count=0,
        evaluated_at=now + timedelta(minutes=1),
    )
    record = decide_experience_approval(
        record,
        approve=True,
        actor_user_id="quality-manager-01",
        actor_role="QualityManager",
        note="Approved for shadow observation only.",
        approval_evidence_sha256=digest("strict-memory-human-approval"),
        decided_at=now + timedelta(minutes=2),
    )
    record = record_experience_shadow(
        record,
        observed_case_count=6,
        changed_worker_order_count=2,
        unsafe_closure_count=0,
        cross_site_memory_leakage_count=0,
        historical_memory_used_as_fact_count=0,
        observed_at=now + timedelta(minutes=3),
    )
    record = promote_experience(
        record,
        promoted_at=now + timedelta(minutes=4),
        actor="quality-governance-owner",
    )
    binding = build_source_case_evidence_binding(
        workspace_id=workspace_id,
        project_id=project_id,
        task_id="archived-source-task-01",
        case_id=source_case_id,
        case_sha256=digest("strict-memory-source-case"),
        case_audit_root_sha256=digest("strict-memory-source-case-audit-root"),
        scope=scope,
        verification_status="VERIFIED_ARCHIVED_CASE_RECEIPT",
        verified_at=now + timedelta(minutes=4),
    )
    envelope = build_memory_admission_envelope(
        record,
        workspace_id=workspace_id,
        project_id=project_id,
        source_case_bindings=[binding],
        admitted_at=now + timedelta(minutes=5),
        admitted_by_actor_user_id="quality-governance-owner",
        admitted_by_actor_role="QualityGovernanceOwner",
    )
    path.write_text(memory_admission_envelope_jsonl(envelope), encoding="utf-8")
    return binding, envelope


def test_service_runs_closed_loop_and_binds_artifacts(tmp_path: Path) -> None:
    service = ProductService(
        tmp_path / "product",
        runner=_fake_runner(),
        recover_interrupted=False,
    )
    actor, project_id = _setup(service)
    task = service.create_task(
        actor,
        CreateTaskRequest(
            project_id=project_id, goal="运行审核并交付绑定当前任务的证据。"
        ),
        auto_start=False,
    )
    completed = service.run_task_sync(task.task_id)

    assert completed.execution_status is TaskExecutionStatus.COMPLETED
    assert completed.initial_decision == "RECAPTURE"
    assert completed.final_decision == "PASS"
    assert completed.evidence_sha256
    assert service.trace_path(actor, task.task_id).is_file()
    assert service.evidence_path(actor, task.task_id).is_file()
    assert [event.phase for event in service.list_events(actor, task.task_id)] == [
        "initial",
        "verification",
    ]
    evidence_path = service.evidence_path(actor, task.task_id)
    assert (
        completed.evidence_sha256
        == hashlib.sha256(evidence_path.read_bytes()).hexdigest()
    )
    with zipfile.ZipFile(evidence_path) as archive:
        assert "industrial_delivery_receipt.json" in archive.namelist()
        delivery = json.loads(archive.read("industrial_delivery_receipt.json"))
    assert delivery["task_id"] == task.task_id
    assert delivery["industrial_task"] == (
        "synthetic_industrial_vision_dataset_release_gate_demo"
    )
    assert delivery["production_approval_status"] == "pending"
    assert delivery["source_assets_copied_into_product"] is False
    assert any(
        "NOT_APPLICABLE" in source["role_in_decision"]
        for source in delivery["multi_source_fusion"]
        if source["source_type"] == "operator_authorization"
    )

    readiness = service.task_release_readiness(actor, task.task_id)
    assert readiness.overall_status == "DEMO_ONLY"
    assert readiness.evidence_integrity == "VERIFIED"
    assert readiness.source_freshness == "NOT_APPLICABLE"
    assert readiness.production_release_allowed is False


def test_reverification_creates_hash_bound_append_only_child_run(
    tmp_path: Path,
) -> None:
    service = ProductService(
        tmp_path / "product",
        runner=_fake_runner(GateDecision.RECAPTURE),
        recover_interrupted=False,
    )
    actor, project_id = _setup(service)
    parent = service.create_task(
        actor,
        CreateTaskRequest(
            project_id=project_id,
            goal="完成首轮门禁后保留原裁决，并创建独立整改复验运行。",
            seed=20260825,
            allowed_tools=["image_quality", "duplicate_leakage"],
        ),
        auto_start=False,
    )
    parent = service.run_task_sync(parent.task_id)
    request = CreateReverificationRequest(
        note="整改已在保留副本完成，申请使用原规则与原固定种子复验。"
    )
    child = service.create_reverification_task(
        actor,
        parent.task_id,
        request,
        idempotency_key="reverify-001",
    )
    repeated = service.create_reverification_task(
        actor,
        parent.task_id,
        request,
        idempotency_key="reverify-001",
    )

    assert repeated.task_id == child.task_id
    assert child.execution_status is TaskExecutionStatus.PLANNED
    assert child.plan_approval_required is True
    assert child.project_id == parent.project_id
    assert child.scenario_profile is parent.scenario_profile
    assert child.source_kind is parent.source_kind
    assert child.allowed_tools == parent.allowed_tools
    assert child.seed == parent.seed
    assert child.request_sha256 != parent.request_sha256
    assert service.get_task(actor, parent.task_id).evidence_sha256 == (
        parent.evidence_sha256
    )

    report = service.task_lineage(actor, child.task_id)
    assert report.root_task_id == parent.task_id
    assert report.focus_task_id == child.task_id
    assert report.latest_task_id == child.task_id
    assert report.node_count == 2
    assert report.edge_count == 1
    assert [node.depth for node in report.nodes] == [0, 1]
    edge = report.edges[0]
    assert edge.parent_task_id == parent.task_id
    assert edge.child_task_id == child.task_id
    assert edge.parent_request_sha256 == parent.request_sha256
    assert edge.parent_evidence_sha256 == parent.evidence_sha256
    assert edge.contract_sha256 == report.contract_sha256
    assert (
        report.report_sha256
        == hashlib.sha256(
            canonical_json_bytes(report.model_dump(exclude={"report_sha256"}))
        ).hexdigest()
    )

    with service.store._connection(immediate=True) as connection:
        with pytest.raises(sqlite3.IntegrityError, match="append-only"):
            connection.execute(
                "UPDATE task_lineage SET note = ? WHERE child_task_id = ?",
                ("rewrite", child.task_id),
            )
    with service.store._connection(immediate=True) as connection:
        with pytest.raises(sqlite3.IntegrityError, match="append-only"):
            connection.execute(
                "DELETE FROM task_lineage WHERE child_task_id = ?",
                (child.task_id,),
            )


def test_reverification_rejects_unfinished_parent(tmp_path: Path) -> None:
    service = ProductService(
        tmp_path / "product", runner=_fake_runner(), recover_interrupted=False
    )
    actor, project_id = _setup(service)
    parent = service.create_task(
        actor,
        CreateTaskRequest(
            project_id=project_id,
            goal="未完成的父任务不能被包装成已经具备证据的复验起点。",
        ),
        auto_start=False,
    )
    with pytest.raises(ConflictError, match="completed parent"):
        service.create_reverification_task(
            actor,
            parent.task_id,
            CreateReverificationRequest(note="尚未形成可绑定的父证据，禁止复验。"),
        )


def test_reverification_api_returns_child_and_hash_sealed_lineage(
    tmp_path: Path,
) -> None:
    service = ProductService(
        tmp_path / "product", runner=_fake_runner(), recover_interrupted=False
    )
    actor, project_id = _setup(service)
    parent = service.create_task(
        actor,
        CreateTaskRequest(
            project_id=project_id,
            goal="通过 REST API 创建独立复验 Run 并读取完整父子证据链。",
        ),
        auto_start=False,
    )
    parent = service.run_task_sync(parent.task_id)
    client = TestClient(create_app(service, ensure_demo_tenant=False))
    headers = {
        "X-Actor-User-Id": actor,
        "Idempotency-Key": "api-reverification-001",
    }
    created = client.post(
        f"/v1/tasks/{parent.task_id}/reverifications",
        headers=headers,
        json={"note": "整改完成后经 API 发起同合同复验，等待人工计划批准。"},
    )
    assert created.status_code == 202
    child_id = created.json()["task_id"]
    assert created.headers["location"] == f"/v1/tasks/{child_id}"
    assert created.json()["plan_approval_required"] is True

    lineage = client.get(
        f"/v1/tasks/{child_id}/lineage",
        headers={"X-Actor-User-Id": actor},
    )
    assert lineage.status_code == 200
    assert lineage.json()["root_task_id"] == parent.task_id
    assert lineage.json()["focus_task_id"] == child_id
    assert lineage.json()["node_count"] == 2
    assert lineage.json()["edges"][0]["parent_evidence_sha256"] == (
        parent.evidence_sha256
    )
    assert lineage.headers["x-content-sha256"] == lineage.json()["report_sha256"]
    assert lineage.headers["etag"] == f'"{lineage.json()["report_sha256"]}"'


def test_defer_is_a_completed_fail_closed_decision_not_system_failure(
    tmp_path: Path,
) -> None:
    service = ProductService(
        tmp_path / "product",
        runner=_fake_runner(GateDecision.DEFER),
        recover_interrupted=False,
    )
    actor, project_id = _setup(service)
    task = service.create_task(
        actor,
        CreateTaskRequest(
            project_id=project_id,
            goal="缺少必需证据时完成运行并返回暂缓决定。",
            allowed_tools=["image_quality"],
        ),
        auto_start=False,
    )
    result = service.run_task_sync(task.task_id)
    assert result.execution_status is TaskExecutionStatus.COMPLETED
    assert result.final_decision == "DEFER"
    assert result.error_code is None


def test_runner_exception_is_failed_without_historic_result_reuse(
    tmp_path: Path,
) -> None:
    def broken_runner(*_args: object, **_kwargs: object) -> object:
        raise RuntimeError("synthetic runner failure")

    service = ProductService(
        tmp_path / "product", runner=broken_runner, recover_interrupted=False
    )
    actor, project_id = _setup(service)
    task = service.create_task(
        actor,
        CreateTaskRequest(project_id=project_id, goal="验证异常时不会冒充完成任务。"),
        auto_start=False,
    )
    failed = service.run_task_sync(task.task_id)
    assert failed.execution_status is TaskExecutionStatus.FAILED
    assert failed.final_decision is None
    assert failed.error_code == "RuntimeError"
    with pytest.raises(ArtifactUnavailableError):
        service.evidence_path(actor, task.task_id)


def test_runner_cannot_rewrite_an_event_already_persisted_by_the_sink(
    tmp_path: Path,
) -> None:
    def rewrite_returned_trace(events):
        return (
            events[0].model_copy(update={"summary": "伪造的回放事件"}),
            events[1],
        )

    # The returned trace remains production-contract-valid, while the event sink
    # keeps the original events. This tests lifecycle reconciliation, not Agent E2E.
    tampering_runner = make_product_lifecycle_stub_runner(
        trace_event_transform=rewrite_returned_trace
    )

    service = ProductService(
        tmp_path / "product",
        runner=tampering_runner,
        recover_interrupted=False,
    )
    actor, project_id = _setup(service)
    task = service.create_task(
        actor,
        CreateTaskRequest(
            project_id=project_id,
            goal="验证 runner 返回值不能改写 event sink 已落库的审计事件。",
        ),
        auto_start=False,
    )

    failed = service.run_task_sync(task.task_id)

    assert failed.execution_status is TaskExecutionStatus.FAILED
    assert failed.error_code == "ConflictError"
    assert failed.final_decision is None
    events = service.list_events(actor, task.task_id)
    assert [event.summary for event in events] == ["任务已接收。", "进入复验。"]
    with pytest.raises(ArtifactUnavailableError):
        service.evidence_path(actor, task.task_id)


def test_unconnected_source_is_rejected_before_task_creation(tmp_path: Path) -> None:
    service = ProductService(tmp_path / "product", recover_interrupted=False)
    actor, project_id = _setup(service)
    with pytest.raises(UnsupportedSourceError):
        service.create_task(
            actor,
            CreateTaskRequest(
                project_id=project_id,
                goal="不得在授权边界未知时读取外部数据目录。",
                source_kind=DataSourceKind.LOCAL_AUTHORIZED_DIRECTORY,
            ),
            auto_start=False,
        )
    assert service.list_tasks(actor) == []


def test_tampered_artifact_path_is_fail_closed(tmp_path: Path) -> None:
    service = ProductService(
        tmp_path / "product",
        runner=_fake_runner(),
        recover_interrupted=False,
    )
    actor, project_id = _setup(service)
    task = service.create_task(
        actor,
        CreateTaskRequest(
            project_id=project_id, goal="生成用于路径隔离检查的审核任务。"
        ),
        auto_start=False,
    )
    service.run_task_sync(task.task_id)
    with service.store._connection(immediate=True) as connection:
        connection.execute(
            "UPDATE agent_tasks SET trace_rel = ? WHERE task_id = ?",
            ("../../outside.json", task.task_id),
        )
    outside = tmp_path / "outside.json"
    outside.write_text(json.dumps({"secret": True}), encoding="utf-8")
    with pytest.raises(ArtifactUnavailableError):
        service.trace_path(actor, task.task_id)


def test_tampered_artifact_bytes_are_rejected(tmp_path: Path) -> None:
    service = ProductService(
        tmp_path / "product", runner=_fake_runner(), recover_interrupted=False
    )
    actor, project_id = _setup(service)
    task = service.create_task(
        actor,
        CreateTaskRequest(
            project_id=project_id, goal="生成并校验不可静默修改的证据包。"
        ),
        auto_start=False,
    )
    completed = service.run_task_sync(task.task_id)
    evidence = service.evidence_path(actor, task.task_id)
    evidence.write_bytes(evidence.read_bytes() + b"tampered")
    with pytest.raises(ArtifactUnavailableError):
        service.evidence_path(actor, completed.task_id)


def test_project_and_task_source_must_match(tmp_path: Path) -> None:
    service = ProductService(tmp_path / "product", recover_interrupted=False)
    user = service.create_user(CreateUserRequest(display_name="Source Owner"))
    workspace = service.create_workspace(
        CreateWorkspaceRequest(name="Source Workspace", owner_user_id=user.user_id)
    )
    project = service.create_project(
        user.user_id,
        CreateProjectRequest(
            workspace_id=workspace.workspace_id,
            name="External Project",
            source_kind=DataSourceKind.EXTERNAL_RESIDENCY_REFERENCE,
        ),
    )
    with pytest.raises(UnsupportedSourceError):
        service.create_task(
            user.user_id,
            CreateTaskRequest(
                project_id=project.project_id,
                goal="不能用默认合成来源绕过项目的未连接外部来源。",
            ),
            auto_start=False,
        )


def test_blank_idempotency_key_is_domain_error(tmp_path: Path) -> None:
    from visiondata_gate.product_service import ProductServiceError

    service = ProductService(tmp_path / "product", recover_interrupted=False)
    actor, project_id = _setup(service)
    with pytest.raises(ProductServiceError):
        service.create_task(
            actor,
            CreateTaskRequest(
                project_id=project_id, goal="拒绝空白幂等键而不是触发数据库异常。"
            ),
            idempotency_key="   ",
            auto_start=False,
        )


def test_plan_approval_blocks_bypass_and_seals_intervention_timeline(
    tmp_path: Path,
) -> None:
    service = ProductService(
        tmp_path / "product", runner=_fake_runner(), recover_interrupted=False
    )
    actor, project_id = _setup(service)
    task = service.create_task(
        actor,
        CreateTaskRequest(
            project_id=project_id,
            goal="先审阅确定性计划，再运行并交付不可变干预记录。",
            plan_approval_required=True,
        ),
        auto_start=False,
    )
    preview = service.task_plan_preview(actor, task.task_id)
    assert preview.approval_required is True
    assert preview.production_authority == "human_only"
    assert preview.before_snapshot_sha256 == service.store.task_snapshot_sha256(task)

    with pytest.raises(ConflictError, match="approval is required"):
        service.run_task_sync(task.task_id)
    assert service.get_task(actor, task.task_id).execution_status is (
        TaskExecutionStatus.PLANNED
    )

    approval = service.intervene_task(
        actor,
        task.task_id,
        TaskInterventionRequest(
            action=TaskInterventionAction.APPROVE_PLAN,
            note="已核对只读范围、补证预算和人工最终审批边界。",
        ),
    )
    service.close(wait=True)
    completed = service.get_task(actor, task.task_id)
    assert completed.execution_status is TaskExecutionStatus.COMPLETED
    assert approval.before_snapshot_sha256 == preview.before_snapshot_sha256
    assert approval.plan_sha256 == preview.plan_sha256
    assert approval.approval_binding is not None
    assert approval.approval_binding.request_sha256 == task.request_sha256
    assert approval.approval_binding.plan_sha256 == preview.plan_sha256
    assert approval.approval_binding.source_profile_status == "NOT_APPLICABLE"
    assert approval.approval_binding.source_profile_sha256 is None
    assert (
        approval.approval_binding.binding_sha256
        == hashlib.sha256(
            canonical_json_bytes(
                approval.approval_binding.model_dump(
                    mode="json", exclude={"binding_sha256"}
                )
            )
        ).hexdigest()
    )
    assert [
        item.action for item in service.list_interventions(actor, task.task_id)
    ] == [TaskInterventionAction.APPROVE_PLAN]

    with zipfile.ZipFile(service.evidence_path(actor, task.task_id)) as archive:
        plan = json.loads(archive.read("task_plan_preview.json"))
        timeline = json.loads(archive.read("task_intervention_timeline.json"))
    assert plan["plan_sha256"] == preview.plan_sha256
    assert timeline["append_only"] is True
    assert timeline["interventions"][0]["action"] == "approve_plan"
    assert (
        timeline["interventions"][0]["approval_binding"]["binding_sha256"]
        == approval.approval_binding.binding_sha256
    )

    review = service.intervene_task(
        actor,
        task.task_id,
        TaskInterventionRequest(
            action=TaskInterventionAction.ACKNOWLEDGE_RESULT,
            note="已审阅裁决、证据引用和工单边界。",
        ),
    )
    assert review.before_status is TaskExecutionStatus.COMPLETED
    assert len(service.list_interventions(actor, task.task_id)) == 2

    with pytest.raises(sqlite3.IntegrityError, match="append-only"):
        with service.store._connection(immediate=True) as connection:
            connection.execute(
                "UPDATE task_interventions SET note = ? WHERE intervention_id = ?",
                ("tampered", approval.intervention_id),
            )


def test_legacy_plan_approval_without_binding_cannot_claim_task(
    tmp_path: Path,
) -> None:
    service = ProductService(
        tmp_path / "product", runner=_fake_runner(), recover_interrupted=False
    )
    actor, project_id = _setup(service)
    task = service.create_task(
        actor,
        CreateTaskRequest(
            project_id=project_id,
            goal="旧批准没有任务、计划、规则和来源绑定时必须失败关闭。",
            plan_approval_required=True,
        ),
        auto_start=False,
    )
    preview = service.task_plan_preview(actor, task.task_id)
    with service.store._connection(immediate=True) as connection:
        connection.execute(
            """
            INSERT INTO task_interventions (
                intervention_id, task_id, sequence, actor_user_id, action,
                note, before_status, before_phase, before_snapshot_sha256,
                plan_sha256, approval_binding_json, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, NULL, ?)
            """,
            (
                "int_legacy_without_binding",
                task.task_id,
                1,
                actor,
                TaskInterventionAction.APPROVE_PLAN.value,
                "历史批准记录，仅用于迁移失败关闭测试。",
                TaskExecutionStatus.PLANNED.value,
                "planned",
                preview.before_snapshot_sha256,
                preview.plan_sha256,
                "2026-08-25T00:00:00+00:00",
            ),
        )

    approval = service.list_interventions(actor, task.task_id)[0]
    assert approval.approval_binding is None
    preflight = service.task_preflight(actor, task.task_id)
    approval_check = next(
        item for item in preflight.checks if item.key == "human_plan_approval"
    )
    assert approval_check.status == "BLOCKED"
    assert "缺少" in approval_check.summary
    assert service.store.claim_task(task.task_id) is False
    with pytest.raises(
        ConflictError,
        match="approval is required and must be current before execution",
    ):
        service.run_task_sync(task.task_id)
    assert service.get_task(actor, task.task_id).execution_status is (
        TaskExecutionStatus.PLANNED
    )


def test_operator_can_cancel_only_a_not_yet_executed_plan(tmp_path: Path) -> None:
    service = ProductService(
        tmp_path / "product", runner=_fake_runner(), recover_interrupted=False
    )
    actor, project_id = _setup(service)
    task = service.create_task(
        actor,
        CreateTaskRequest(
            project_id=project_id,
            goal="在任何工具调用前取消尚未批准的审核计划。",
            plan_approval_required=True,
        ),
        auto_start=False,
    )
    cancellation = service.intervene_task(
        actor,
        task.task_id,
        TaskInterventionRequest(
            action=TaskInterventionAction.CANCEL_PLAN,
            note="来源范围仍需确认，本次不执行。",
        ),
    )
    cancelled = service.get_task(actor, task.task_id)
    assert cancellation.before_status is TaskExecutionStatus.PLANNED
    assert cancelled.execution_status is TaskExecutionStatus.CANCELLED
    assert service.list_events(actor, task.task_id) == []
    assert service.run_task_sync(task.task_id).execution_status is (
        TaskExecutionStatus.CANCELLED
    )


def test_incident_service_persists_pause_decide_and_immutable_resume(
    tmp_path: Path,
) -> None:
    service = ProductService(
        tmp_path / "product", runner=_fake_runner(), recover_interrupted=False
    )
    actor, project_id = _setup(service)
    task = service.create_task(
        actor,
        CreateTaskRequest(
            project_id=project_id,
            goal="用显式 fixture 验证换型后异常案件的暂停、人工决定与不可变续跑。",
        ),
        auto_start=False,
    )
    task = service.run_task_sync(task.task_id)

    first_request = build_fixture_industrial_incident_request()
    first = service.create_industrial_incident_case(actor, task.task_id, first_request)
    assert first.case_version == 1
    assert first.loop_steps[-1].status == "PAUSED"
    assert (
        service.get_industrial_incident_case(
            actor, task.task_id, first.case_id
        ).case_sha256
        == first.case_sha256
    )

    resumed_request = first_request.model_copy(
        update={"supersedes_case_id": first.case_id}
    )
    with pytest.raises(ConflictError, match="named human decision"):
        service.resume_industrial_incident_case(
            actor, task.task_id, first.case_id, resumed_request
        )

    decision = service.record_industrial_incident_decision(
        actor,
        task.task_id,
        first.case_id,
        IndustrialIncidentDecisionRequest(
            bound_case_sha256=first.case_sha256,
            decision=IncidentHumanDecision.CONTINUE_HOLD,
            note="已核对 fixture 证据边界，继续 HOLD 并用新案件版本演练补证。",
            operator_attests_reviewed_evidence=True,
        ),
    )
    assert decision.case_sha256 == first.case_sha256
    assert decision.production_release_allowed is False

    resumed_request = build_fixture_industrial_incident_request(revision=2).model_copy(
        update={
            "supersedes_case_id": first.case_id,
            "expected_parent_case_sha256": first.case_sha256,
            "authorizing_decision_id": decision.decision_id,
        }
    )
    resumed = service.resume_industrial_incident_case(
        actor, task.task_id, first.case_id, resumed_request
    )
    assert resumed.case_version == 2
    assert resumed.parent_case_id == first.case_id
    assert resumed.case_id != first.case_id
    resumed_envelope = service.get_industrial_incident_audit_envelope(
        actor,
        task.task_id,
        resumed.case_id,
    )
    assert resumed_envelope.lineage.parent_legacy_case_sha256 == first.case_sha256
    assert (
        resumed_envelope.lineage.authorizing_decision_legacy_sha256
        == decision.decision_sha256
    )
    assert [
        item.case_id
        for item in service.list_industrial_incident_cases(actor, task.task_id)
    ] == [first.case_id, resumed.case_id]
    assert (
        len(
            service.list_industrial_incident_decisions(
                actor, task.task_id, first.case_id
            )
        )
        == 1
    )
    interaction = service.get_industrial_incident_interaction_receipt(
        actor,
        task.task_id,
        resumed.case_id,
    )
    assert interaction.parent_case_id == first.case_id
    assert interaction.decision_id == decision.decision_id
    assert interaction.child_case_id == resumed.case_id
    assert interaction.multi_turn_state_transition_verified is True
    assert interaction.hidden_chain_of_thought_retained is False
    assert interaction.production_release_allowed is False

    replayed = service.resume_industrial_incident_case(
        actor, task.task_id, first.case_id, resumed_request
    )
    assert replayed.case_id == resumed.case_id
    assert replayed.case_sha256 == resumed.case_sha256

    competing_request = build_fixture_industrial_incident_request(
        revision=3
    ).model_copy(
        update={
            "supersedes_case_id": first.case_id,
            "expected_parent_case_sha256": first.case_sha256,
            "authorizing_decision_id": decision.decision_id,
        }
    )
    with pytest.raises(ConflictError, match="already advanced"):
        service.resume_industrial_incident_case(
            actor, task.task_id, first.case_id, competing_request
        )

    with pytest.raises(ConflictError, match="different active human decision"):
        service.record_industrial_incident_decision(
            actor,
            task.task_id,
            first.case_id,
            IndustrialIncidentDecisionRequest(
                bound_case_sha256=first.case_sha256,
                decision=IncidentHumanDecision.ESCALATE_INVESTIGATION,
                note="提交另一条冲突决定应被拒绝，避免同一案件出现双重 head。",
                operator_attests_reviewed_evidence=True,
            ),
        )

    interaction_path = (
        service._incident_case_root(task, resumed.case_id)
        / "interaction"
        / "receipt.json"
    )
    interaction_payload = json.loads(interaction_path.read_text(encoding="utf-8"))
    interaction_payload["remaining_open_question_count"] += 1
    write_canonical_json(interaction_path, interaction_payload)
    with pytest.raises(ArtifactUnavailableError, match="semantic verification"):
        service.get_industrial_incident_interaction_receipt(
            actor,
            task.task_id,
            resumed.case_id,
        )


def test_incident_phase_event_tampering_fails_closed(tmp_path: Path) -> None:
    service = ProductService(
        tmp_path / "product", runner=_fake_runner(), recover_interrupted=False
    )
    actor, project_id = _setup(service)
    task = service.create_task(
        actor,
        CreateTaskRequest(
            project_id=project_id,
            goal="验证案件阶段事件链被修改后必须失败关闭。",
        ),
        auto_start=False,
    )
    task = service.run_task_sync(task.task_id)
    case = service.create_industrial_incident_case(
        actor, task.task_id, build_fixture_industrial_incident_request()
    )
    phase_root = service._incident_case_root(task, case.case_id) / "phase_events"
    event_path = sorted(phase_root.glob("*.json"))[1]
    payload = json.loads(event_path.read_text(encoding="utf-8"))
    payload["status"] = "FAILED"
    event_path.write_text(
        json.dumps(payload, ensure_ascii=False, sort_keys=True), encoding="utf-8"
    )

    with pytest.raises(ArtifactUnavailableError, match="phase events"):
        service.get_industrial_incident_case(actor, task.task_id, case.case_id)


def test_incident_api_exposes_case_pause_decision_and_resume(tmp_path: Path) -> None:
    service = ProductService(
        tmp_path / "product", runner=_fake_runner(), recover_interrupted=False
    )
    actor, project_id = _setup(service)
    task = service.create_task(
        actor,
        CreateTaskRequest(
            project_id=project_id,
            goal="通过任务级 API 演练仿真异常案件，不声明现场连接。",
        ),
        auto_start=False,
    )
    task = service.run_task_sync(task.task_id)
    headers = {"X-Actor-User-Id": actor}
    fixture = build_fixture_industrial_incident_request()

    with TestClient(create_app(service, ensure_demo_tenant=False)) as client:
        created = client.post(
            f"/v1/tasks/{task.task_id}/industrial-incidents",
            headers=headers,
            json=fixture.model_dump(mode="json"),
        )
        assert created.status_code == 201
        case = created.json()
        case_id = case["case_id"]
        assert case["opcua_connection_status"] == "OPC_UA_FIXTURE_REPLAY_ONLY"

        listed = client.get(
            f"/v1/tasks/{task.task_id}/industrial-incidents",
            headers=headers,
        )
        assert listed.status_code == 200
        assert [item["case_id"] for item in listed.json()] == [case_id]
        listed_sha256 = hashlib.sha256(canonical_json_bytes(listed.json())).hexdigest()
        assert listed.headers["x-content-sha256"] == listed_sha256
        assert listed.headers["etag"] == f'"{listed_sha256}"'

        phase_events = client.get(
            f"/v1/tasks/{task.task_id}/industrial-incidents/{case_id}/phase-events",
            headers=headers,
        )
        assert phase_events.status_code == 200
        assert phase_events.json()[0]["phase"] == "PLAN"
        assert phase_events.json()[-1]["phase"] == "INTERRUPT"
        assert phase_events.json()[-1]["status"] == "PAUSED"
        phase_sha256 = hashlib.sha256(
            canonical_json_bytes(phase_events.json())
        ).hexdigest()
        assert phase_events.headers["x-content-sha256"] == phase_sha256
        assert phase_events.headers["etag"] == f'"{phase_sha256}"'

        control_plane = client.get(
            f"/v1/tasks/{task.task_id}/industrial-incidents/{case_id}/control-plane",
            headers=headers,
        )
        assert control_plane.status_code == 200
        assert (
            control_plane.headers["x-content-sha256"]
            == (control_plane.json()["bundle_sha256"])
        )
        assert control_plane.headers["etag"] == (
            f'"{control_plane.json()["bundle_sha256"]}"'
        )

        decision_packet = client.get(
            f"/v1/tasks/{task.task_id}/industrial-incidents/{case_id}/decision-packet",
            headers=headers,
        )
        assert decision_packet.status_code == 200
        assert (
            decision_packet.headers["x-decision-packet-sha256"]
            == (decision_packet.json()["packet_sha256"])
        )
        assert decision_packet.headers["etag"] == (
            f'"{decision_packet.json()["packet_sha256"]}"'
        )

        runtime_binding = client.get(
            f"/v1/tasks/{task.task_id}/industrial-incidents/"
            f"{case_id}/runtime-profile-binding",
            headers=headers,
        )
        assert runtime_binding.status_code == 200
        assert (
            runtime_binding.headers["x-content-sha256"]
            == (runtime_binding.json()["binding_sha256"])
        )

        decision = client.post(
            f"/v1/tasks/{task.task_id}/industrial-incidents/{case_id}/decisions",
            headers=headers,
            json={
                "bound_case_sha256": case["case_sha256"],
                "decision": "CONTINUE_HOLD",
                "note": "已核对 fixture 边界，继续 HOLD 后再生成不可变补证版本。",
                "operator_attests_reviewed_evidence": True,
            },
        )
        assert decision.status_code == 201
        assert decision.json()["production_release_allowed"] is False
        decision_ledger = client.get(
            f"/v1/tasks/{task.task_id}/industrial-incidents/{case_id}/decisions",
            headers=headers,
        )
        decision_ledger_sha256 = hashlib.sha256(
            canonical_json_bytes(decision_ledger.json())
        ).hexdigest()
        assert decision_ledger.headers["x-content-sha256"] == decision_ledger_sha256
        assert decision_ledger.headers["etag"] == f'"{decision_ledger_sha256}"'

        resumed_payload = build_fixture_industrial_incident_request(
            revision=2
        ).model_dump(mode="json")
        resumed_payload.update(
            {
                "supersedes_case_id": case_id,
                "expected_parent_case_sha256": case["case_sha256"],
                "authorizing_decision_id": decision.json()["decision_id"],
            }
        )
        resumed = client.post(
            f"/v1/tasks/{task.task_id}/industrial-incidents/{case_id}/resume",
            headers=headers,
            json=resumed_payload,
        )
        assert resumed.status_code == 201
        assert resumed.json()["case_version"] == 2
        assert resumed.json()["parent_case_id"] == case_id

        review_projection = client.get(
            f"/v1/tasks/{task.task_id}/industrial-incidents/"
            f"{case_id}/review-projection",
            headers=headers,
        )
        assert review_projection.status_code == 200
        projection = review_projection.json()
        assert projection["transport_source_mode"] == "LIVE"
        assert projection["evidence_source_mode"] == "REPLAY"
        assert projection["factory_live_connection_claimed"] is False
        assert (
            projection["worker_budget"]
            == case["worker_selection_receipt"]["worker_budget"]
        )
        assert {item["worker_id"] for item in projection["selected_workers"]} == set(
            case["worker_selection_receipt"]["selected_worker_ids"]
        )
        assert projection["rejected_workers"]
        assert projection["triggering_evidence"]
        assert len(projection["competing_hypotheses"]) >= 6
        assert projection["what_would_change_decision"]
        assert (
            projection["control_plane_bundle_sha256"]
            == control_plane.json()["bundle_sha256"]
        )
        assert (
            projection["contrastive_decision_packet_sha256"]
            == (control_plane.json()["decision_packet"]["packet_sha256"])
        )
        assert (
            decision_packet.json()["control_plane_sha256"]
            == projection["control_plane_bundle_sha256"]
        )
        assert (
            projection["human_decisions"][0]["decision_id"]
            == (decision.json()["decision_id"])
        )
        assert projection["human_decisions"][0]["case_sha256"] == case["case_sha256"]
        assert projection["child_cases"][0]["case_id"] == (resumed.json()["case_id"])
        assert projection["child_cases"][0]["parent_case_sha256"] == case["case_sha256"]
        assert projection["missing_linked_capa_case_ids"] == []
        assert projection["production_release_allowed"] is False
        assert projection["machine_write_permitted"] is False
        projection_stable = dict(projection)
        projection_sha256 = projection_stable.pop("projection_sha256")
        assert (
            projection_sha256
            == hashlib.sha256(canonical_json_bytes(projection_stable)).hexdigest()
        )
        assert review_projection.headers["x-content-sha256"] == projection_sha256
        assert review_projection.headers["etag"] == f'"{projection_sha256}"'


def test_v3_deterministic_off_profile_ignores_legacy_service_planner(
    tmp_path: Path,
) -> None:
    class ForbiddenLegacyPlanner:
        def plan(self, **_values: object) -> object:
            raise AssertionError(
                "legacy service planner must not run for a v3 off profile"
            )

        def health_label(self) -> str:
            return "forbidden-test-planner"

    service = ProductService(
        tmp_path / "product",
        runner=_fake_runner(),
        recover_interrupted=False,
        incident_model_planner=ForbiddenLegacyPlanner(),  # type: ignore[arg-type]
    )
    actor, project_id = _setup(service)
    task = service.create_task(
        actor,
        CreateTaskRequest(
            project_id=project_id,
            goal="验证 v3 请求绑定的确定性运行档案不会继承服务级旧 Planner。",
        ),
        auto_start=False,
    )
    task = service.run_task_sync(task.task_id)

    case = service.create_industrial_incident_case(
        actor,
        task.task_id,
        build_fixture_industrial_incident_request(),
    )

    assert case.model_planner_receipt is None


def test_v3_create_persists_runtime_profile_binding(tmp_path: Path) -> None:
    service = ProductService(
        tmp_path / "product", runner=_fake_runner(), recover_interrupted=False
    )
    actor, project_id = _setup(service)
    task = service.create_task(
        actor,
        CreateTaskRequest(
            project_id=project_id,
            goal="验证案件运行档案与不可变 Case 双向绑定。",
        ),
        auto_start=False,
    )
    task = service.run_task_sync(task.task_id)
    request = build_fixture_industrial_incident_request()

    case = service.create_industrial_incident_case(actor, task.task_id, request)
    binding_path = (
        service._incident_case_root(task, case.case_id)
        / "runtime"
        / "profile_binding.json"
    )

    assert binding_path.is_file()
    binding = json.loads(binding_path.read_text(encoding="utf-8"))
    assert binding["case_id"] == case.case_id
    assert binding["case_sha256"] == case.case_sha256
    assert binding["profile_sha256"] == request.runtime_profile.profile_sha256()
    assert (
        service.get_industrial_incident_case(
            actor, task.task_id, case.case_id
        ).case_sha256
        == case.case_sha256
    )


def test_same_idempotency_key_cannot_change_runtime_profile(tmp_path: Path) -> None:
    service = ProductService(
        tmp_path / "product", runner=_fake_runner(), recover_interrupted=False
    )
    actor, project_id = _setup(service)
    task = service.create_task(
        actor,
        CreateTaskRequest(
            project_id=project_id,
            goal="验证运行档案属于幂等命令合同。",
        ),
        auto_start=False,
    )
    task = service.run_task_sync(task.task_id)
    request = build_fixture_industrial_incident_request()
    service.create_industrial_incident_case(
        actor,
        task.task_id,
        request,
        idempotency_key="profile-bound-create",
    )
    changed = request.model_copy(
        update={
            "runtime_profile": IncidentRuntimeProfile(
                max_output_tokens=600,
                context_budget_tokens=4_096,
            )
        }
    )

    with pytest.raises(
        IncidentIdempotencyConflictError,
        match="already bound to another command",
    ):
        service.create_industrial_incident_case(
            actor,
            task.task_id,
            changed,
            idempotency_key="profile-bound-create",
        )


def test_profile_only_change_cannot_reuse_decision_as_new_evidence(
    tmp_path: Path,
) -> None:
    service = ProductService(
        tmp_path / "product", runner=_fake_runner(), recover_interrupted=False
    )
    actor, project_id = _setup(service)
    task = service.create_task(
        actor,
        CreateTaskRequest(
            project_id=project_id,
            goal="验证运行参数变化不能冒充新的工业证据。",
        ),
        auto_start=False,
    )
    task = service.run_task_sync(task.task_id)
    parent_request = build_fixture_industrial_incident_request()
    parent = service.create_industrial_incident_case(
        actor, task.task_id, parent_request
    )
    decision = service.record_industrial_incident_decision(
        actor,
        task.task_id,
        parent.case_id,
        IndustrialIncidentDecisionRequest(
            bound_case_sha256=parent.case_sha256,
            decision=IncidentHumanDecision.CONTINUE_HOLD,
            note="继续 HOLD，等待新的现场或离线证据。",
            operator_attests_reviewed_evidence=True,
        ),
    )
    profile_only_request = parent_request.model_copy(
        update={
            "runtime_profile": IncidentRuntimeProfile(
                max_output_tokens=600,
                context_budget_tokens=4_096,
            ),
            "supersedes_case_id": parent.case_id,
            "expected_parent_case_sha256": parent.case_sha256,
            "authorizing_decision_id": decision.decision_id,
        }
    )

    with pytest.raises(ConflictError, match="NO_NEW_EVIDENCE"):
        service.resume_industrial_incident_case(
            actor,
            task.task_id,
            parent.case_id,
            profile_only_request,
        )


def test_child_with_new_evidence_can_adopt_new_profile_without_mutating_parent(
    tmp_path: Path,
) -> None:
    service = ProductService(
        tmp_path / "product", runner=_fake_runner(), recover_interrupted=False
    )
    actor, project_id = _setup(service)
    task = service.create_task(
        actor,
        CreateTaskRequest(
            project_id=project_id,
            goal="验证新证据 child Case 可显式采用新运行档案。",
        ),
        auto_start=False,
    )
    task = service.run_task_sync(task.task_id)
    parent_request = build_fixture_industrial_incident_request()
    parent = service.create_industrial_incident_case(
        actor, task.task_id, parent_request
    )
    decision = service.record_industrial_incident_decision(
        actor,
        task.task_id,
        parent.case_id,
        IndustrialIncidentDecisionRequest(
            bound_case_sha256=parent.case_sha256,
            decision=IncidentHumanDecision.CONTINUE_HOLD,
            note="批准基于新证据创建不可变 child Case。",
            operator_attests_reviewed_evidence=True,
        ),
    )
    child_profile = IncidentRuntimeProfile(
        max_output_tokens=600,
        context_budget_tokens=4_096,
    )
    child_request = build_fixture_industrial_incident_request(revision=2).model_copy(
        update={
            "runtime_profile": child_profile,
            "supersedes_case_id": parent.case_id,
            "expected_parent_case_sha256": parent.case_sha256,
            "authorizing_decision_id": decision.decision_id,
        }
    )

    child = service.resume_industrial_incident_case(
        actor,
        task.task_id,
        parent.case_id,
        child_request,
    )
    reloaded_parent = service.get_industrial_incident_case(
        actor, task.task_id, parent.case_id
    )
    reloaded_child = service.get_industrial_incident_case(
        actor, task.task_id, child.case_id
    )

    assert reloaded_parent.request.runtime_profile == parent_request.runtime_profile
    assert reloaded_child.request.runtime_profile == child_profile
    assert (
        reloaded_parent.request.runtime_profile.profile_sha256()
        != reloaded_child.request.runtime_profile.profile_sha256()
    )
    assert reloaded_child.parent_case_sha256 == reloaded_parent.case_sha256


def test_runtime_binding_cannot_claim_a_planner_absent_from_the_case(
    tmp_path: Path,
) -> None:
    service = ProductService(
        tmp_path / "product", runner=_fake_runner(), recover_interrupted=False
    )
    actor, project_id = _setup(service)
    task = service.create_task(
        actor,
        CreateTaskRequest(
            project_id=project_id,
            goal="验证运行档案不能伪称 Case 未记录的模型连接。",
        ),
        auto_start=False,
    )
    task = service.run_task_sync(task.task_id)
    case = service.create_industrial_incident_case(
        actor,
        task.task_id,
        build_fixture_industrial_incident_request(),
    )
    binding_path = (
        service._incident_case_root(task, case.case_id)
        / "runtime"
        / "profile_binding.json"
    )
    binding = json.loads(binding_path.read_text(encoding="utf-8"))
    binding["planner_config_sha256"] = "f" * 64
    binding["planner_connection_status"] = "REAL_BACKEND_CONNECTED"
    stable = dict(binding)
    stable.pop("binding_sha256")
    binding["binding_sha256"] = hashlib.sha256(canonical_json_bytes(stable)).hexdigest()
    write_canonical_json(binding_path, binding)

    with pytest.raises(ArtifactUnavailableError, match="planner linkage"):
        service.get_industrial_incident_case(actor, task.task_id, case.case_id)


def test_approved_site_context_is_persisted_and_bound_to_the_case(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    site_root = (
        Path(__file__).parents[1] / "examples" / "site_packs" / "factory_a_line_01"
    )
    service = ProductService(
        tmp_path / "product",
        runner=_fake_runner(),
        recover_interrupted=False,
        incident_site_profiles={"factory-a-line-01": site_root},
        approved_memory_store_path=site_root / "approved_memory.jsonl",
        memory_admission_mode="legacy_card_v1",
    )
    actor, project_id = _setup(service)
    task = service.create_task(
        actor,
        CreateTaskRequest(
            project_id=project_id,
            goal="验证经批准的厂站经验只作为可追溯历史参考。",
        ),
        auto_start=False,
    )
    task = service.run_task_sync(task.task_id)
    replay_path = (
        Path(__file__).parents[1] / "examples" / "incident_model_replay.fixture.json"
    )
    monkeypatch.setenv("VISIONDATA_INCIDENT_MODEL_REPLAY_PATH", str(replay_path))
    request = build_fixture_industrial_incident_request().model_copy(
        update={
            "runtime_profile": IncidentRuntimeProfile(
                model_profile_id="deepseek-replay",
                planner_mode=IncidentModelMode.REPLAY,
                memory_mode=IncidentMemoryMode.APPROVED_SITE,
                memory_top_k=4,
                site_profile_id="factory-a-line-01",
            )
        }
    )

    case = service.create_industrial_incident_case(actor, task.task_id, request)
    runtime_root = service._incident_case_root(task, case.case_id) / "runtime"
    binding = json.loads(
        (runtime_root / "profile_binding.json").read_text(encoding="utf-8")
    )
    governed = json.loads(
        (runtime_root / "governed_context.json").read_text(encoding="utf-8")
    )
    admission_paths = list(
        (service._incident_task_root(task) / "commands").glob("*/admission.json")
    )
    assert len(admission_paths) == 1
    admission = json.loads(admission_paths[0].read_text(encoding="utf-8"))
    retrieval = governed["retrieval_receipt"]
    parse_timestamp = lambda value: datetime.fromisoformat(  # noqa: E731
        value.replace("Z", "+00:00")
    )

    assert retrieval["authorization_clock"] == "PROCESSING_TIME"
    assert parse_timestamp(retrieval["event_time"]) == request.trigger.triggered_at
    assert parse_timestamp(retrieval["processing_time"]) == parse_timestamp(
        admission["admitted_at"]
    )
    assert parse_timestamp(retrieval["processing_time"]) >= parse_timestamp(
        retrieval["event_time"]
    )

    assert (
        binding["governed_context_receipt_sha256"]
        == governed["receipt"]["receipt_sha256"]
    )
    assert (
        binding["governed_memory_planning_input_sha256"]
        == governed["planning_input"]["input_sha256"]
        == case.governed_memory_planning_input_sha256
    )
    assert (
        binding["governed_memory_retrieval_receipt_sha256"]
        == governed["retrieval_receipt"]["receipt_sha256"]
        == case.governed_memory_retrieval_receipt_sha256
    )
    assert case.model_planner_receipt is not None
    assert (
        case.model_planner_receipt.governed_memory_retrieval_receipt_sha256
        == binding["governed_memory_retrieval_receipt_sha256"]
    )
    assert (
        case.model_planner_receipt.governed_memory_input_sha256
        == binding["governed_memory_planning_input_sha256"]
    )
    assert (
        governed["planning_input"]["retrieval_receipt"] == governed["retrieval_receipt"]
    )
    assert (
        binding["selected_memory_count"] + binding["rejected_memory_count"]
        == governed["retrieval_receipt"]["candidate_count"]
    )
    assert governed["context"]["case_id"] == case.case_id
    assert governed["context"]["case_sha256"] == case.case_sha256
    assert governed["context"]["historical_memory_used_as_current_fact"] is False
    assert (
        service.get_industrial_incident_case(
            actor, task.task_id, case.case_id
        ).case_sha256
        == case.case_sha256
    )

    packet = service.get_industrial_incident_decision_packet(
        actor,
        task.task_id,
        case.case_id,
    )
    assert packet.site_id == governed["context"]["site_id"]
    assert packet.site_pack_sha256 == governed["receipt"]["site_pack_sha256"]
    assert packet.context_receipt_sha256 == governed["receipt"]["receipt_sha256"]

    binding["governed_memory_retrieval_receipt_sha256"] = "f" * 64
    stable_binding = dict(binding)
    stable_binding.pop("binding_sha256")
    binding["binding_sha256"] = hashlib.sha256(
        canonical_json_bytes(stable_binding)
    ).hexdigest()
    write_canonical_json(runtime_root / "profile_binding.json", binding)
    with pytest.raises(ArtifactUnavailableError, match="governed context"):
        service.get_industrial_incident_case(actor, task.task_id, case.case_id)


def test_strict_memory_admission_is_verified_before_runtime_retrieval(
    tmp_path: Path,
) -> None:
    site_root = (
        Path(__file__).parents[1] / "examples" / "site_packs" / "factory_a_line_01"
    )
    product_root = tmp_path / "product"
    bootstrap = ProductService(
        product_root,
        runner=_fake_runner(),
        recover_interrupted=False,
    )
    actor, project_id = _setup(bootstrap)
    project = bootstrap.store.get_project(actor, project_id)
    admission_store = tmp_path / "strict-memory-admission.jsonl"
    source_binding, envelope = _strict_memory_admission_fixture(
        admission_store,
        workspace_id=project.workspace_id,
        project_id=project.project_id,
    )
    bootstrap.close()

    unready = ProductService(
        product_root,
        runner=_fake_runner(),
        recover_interrupted=False,
        incident_site_profiles={"factory-a-line-01": site_root},
        governed_memory_admission_store_path=admission_store,
    )
    assert (
        unready.health().data_sources["governed_site_memory"]
        == "contract_ready_not_connected"
    )
    assert unready.incident_runtime_capabilities().memory_profiles == []
    unready.close()

    service = ProductService(
        product_root,
        runner=_fake_runner(),
        recover_interrupted=False,
        incident_site_profiles={"factory-a-line-01": site_root},
        governed_memory_admission_store_path=admission_store,
        memory_source_case_registry={source_binding.case_id: source_binding},
    )
    assert (
        service.health().data_sources["governed_site_memory"]
        == "strict_admission_chain_available"
    )
    assert [
        item.profile_id
        for item in service.incident_runtime_capabilities().memory_profiles
    ] == ["factory-a-line-01"]
    task = service.create_task(
        actor,
        CreateTaskRequest(
            project_id=project_id,
            goal="验证完整审批链记忆只能作为当前案件的历史补证建议。",
        ),
        auto_start=False,
    )
    task = service.run_task_sync(task.task_id)
    request = build_fixture_industrial_incident_request().model_copy(
        update={
            "runtime_profile": IncidentRuntimeProfile(
                memory_mode=IncidentMemoryMode.APPROVED_SITE,
                memory_top_k=4,
                site_profile_id="factory-a-line-01",
            )
        }
    )

    case = service.create_industrial_incident_case(actor, task.task_id, request)
    runtime_root = service._incident_case_root(task, case.case_id) / "runtime"
    governed = json.loads(
        (runtime_root / "governed_context.json").read_text(encoding="utf-8")
    )
    retrieval = governed["retrieval_receipt"]
    clock_source = retrieval["processing_time_source"]
    admission = json.loads(
        (
            service._incident_command_root(task, clock_source["source_id"])
            / "admission.json"
        ).read_text(encoding="utf-8")
    )

    assert retrieval["schema_version"] == "visiondata-gate.memory-retrieval-receipt.v3"
    assert clock_source["source_kind"] == "INCIDENT_COMMAND_ADMISSION"
    assert clock_source["source_sha256"] == admission["admission_sha256"]
    assert retrieval["processing_time"] == admission["admitted_at"]
    assert retrieval["memory_admission_status"] == ("STRICT_PROMOTION_CHAIN_VERIFIED")
    assert (
        retrieval["memory_admission_store_sha256"]
        == hashlib.sha256(admission_store.read_bytes()).hexdigest()
    )
    assert retrieval["selection_algorithm"] == "HYBRID_SPARSE_RRF_V2"
    assert retrieval["candidate_count"] == 1
    assert retrieval["selected_count"] == 1
    assert retrieval["selected"][0]["memory_sha256"] == envelope.card.memory_sha256
    assert governed["context"]["historical_memory_used_as_current_fact"] is False
    assert case.production_release_allowed is False


def test_bare_memory_store_requires_explicit_legacy_mode(tmp_path: Path) -> None:
    site_root = (
        Path(__file__).parents[1] / "examples" / "site_packs" / "factory_a_line_01"
    )

    with pytest.raises(ValueError, match="requires explicit legacy_card_v1"):
        ProductService(
            tmp_path / "product",
            runner=_fake_runner(),
            recover_interrupted=False,
            approved_memory_store_path=site_root / "approved_memory.jsonl",
        )


def test_resumed_case_reuses_one_preplanning_retrieval_for_its_runtime_binding(
    tmp_path: Path,
) -> None:
    site_root = (
        Path(__file__).parents[1] / "examples" / "site_packs" / "factory_a_line_01"
    )
    service = ProductService(
        tmp_path / "product",
        runner=_fake_runner(),
        recover_interrupted=False,
        incident_site_profiles={"factory-a-line-01": site_root},
        approved_memory_store_path=site_root / "approved_memory.jsonl",
        memory_admission_mode="legacy_card_v1",
    )
    actor, project_id = _setup(service)
    task = service.create_task(
        actor,
        CreateTaskRequest(
            project_id=project_id,
            goal="验证恢复案件在计划前只检索一次治理记忆。",
        ),
        auto_start=False,
    )
    task = service.run_task_sync(task.task_id)
    profile = IncidentRuntimeProfile(
        memory_mode=IncidentMemoryMode.APPROVED_SITE,
        memory_top_k=4,
        site_profile_id="factory-a-line-01",
    )
    parent_request = build_fixture_industrial_incident_request().model_copy(
        update={"runtime_profile": profile}
    )
    parent = service.create_industrial_incident_case(
        actor,
        task.task_id,
        parent_request,
    )
    decision = service.record_industrial_incident_decision(
        actor,
        task.task_id,
        parent.case_id,
        IndustrialIncidentDecisionRequest(
            bound_case_sha256=parent.case_sha256,
            decision=IncidentHumanDecision.CONTINUE_HOLD,
            note="批准使用新证据恢复调查，但历史经验不得成为当前事实。",
            operator_attests_reviewed_evidence=True,
        ),
    )
    child_request = build_fixture_industrial_incident_request(revision=2).model_copy(
        update={
            "runtime_profile": profile,
            "supersedes_case_id": parent.case_id,
            "expected_parent_case_sha256": parent.case_sha256,
            "authorizing_decision_id": decision.decision_id,
        }
    )
    child = service.resume_industrial_incident_case(
        actor,
        task.task_id,
        parent.case_id,
        child_request,
    )
    child_runtime = service._incident_case_root(task, child.case_id) / "runtime"
    binding = json.loads(
        (child_runtime / "profile_binding.json").read_text(encoding="utf-8")
    )
    governed = json.loads(
        (child_runtime / "governed_context.json").read_text(encoding="utf-8")
    )

    retrieval_sha256 = governed["retrieval_receipt"]["receipt_sha256"]
    clock_source = governed["retrieval_receipt"]["processing_time_source"]
    admission = json.loads(
        (
            service._incident_command_root(task, clock_source["source_id"])
            / "admission.json"
        ).read_text(encoding="utf-8")
    )
    assert (
        governed["retrieval_receipt"]["schema_version"]
        == "visiondata-gate.memory-retrieval-receipt.v3"
    )
    assert clock_source["source_kind"] == "INCIDENT_COMMAND_ADMISSION"
    assert clock_source["source_sha256"] == admission["admission_sha256"]
    assert governed["retrieval_receipt"]["processing_time"] == admission["admitted_at"]
    assert (
        governed["retrieval_receipt"]["selection_algorithm"] == "HYBRID_SPARSE_RRF_V2"
    )
    assert governed["retrieval_receipt"]["semantic_status"] == "NOT_CONFIGURED"
    assert governed["retrieval_receipt"]["fallback"] == "DETERMINISTIC_LEXICAL"
    assert governed["retrieval_receipt"]["raw_query_retained"] is False
    assert child.governed_memory_retrieval_receipt_sha256 == retrieval_sha256
    assert (
        governed["planning_input"]["retrieval_receipt"]["receipt_sha256"]
        == retrieval_sha256
    )
    assert binding["governed_memory_retrieval_receipt_sha256"] == retrieval_sha256
    assert governed["context"]["historical_memory_used_as_current_fact"] is False
    assert child.root_cause_status == "NOT_ESTABLISHED"
    assert child.production_release_allowed is False


def test_runtime_capabilities_api_is_secret_free(tmp_path: Path) -> None:
    service = ProductService(
        tmp_path / "product", runner=_fake_runner(), recover_interrupted=False
    )

    with TestClient(create_app(service, ensure_demo_tenant=False)) as client:
        response = client.get("/v1/industrial-incidents/runtime-capabilities")

    assert response.status_code == 200
    payload = response.json()
    assert payload["secrets_exposed"] is False
    assert payload["production_decision_authority"] == "human_only"

    def nested_keys(value: object) -> set[str]:
        if isinstance(value, dict):
            return {str(key).casefold() for key in value} | {
                nested for item in value.values() for nested in nested_keys(item)
            }
        if isinstance(value, list):
            return {nested for item in value for nested in nested_keys(item)}
        return set()

    assert {
        "api_key",
        "endpoint",
        "provider_endpoint",
        "remote_endpoint_hosts",
        "replay_path",
    }.isdisjoint(nested_keys(payload))
    serialized = json.dumps(payload, ensure_ascii=False).casefold()
    assert "https://api.deepseek.com" not in serialized


def test_case_runtime_profile_binding_is_available_through_api(
    tmp_path: Path,
) -> None:
    service = ProductService(
        tmp_path / "product", runner=_fake_runner(), recover_interrupted=False
    )
    actor, project_id = _setup(service)
    task = service.create_task(
        actor,
        CreateTaskRequest(
            project_id=project_id,
            goal="验证评委可通过 API 读取 Case 绑定的运行档案收据。",
        ),
        auto_start=False,
    )
    task = service.run_task_sync(task.task_id)
    case = service.create_industrial_incident_case(
        actor,
        task.task_id,
        build_fixture_industrial_incident_request(),
    )

    with TestClient(create_app(service, ensure_demo_tenant=False)) as client:
        response = client.get(
            f"/v1/tasks/{task.task_id}/industrial-incidents/"
            f"{case.case_id}/runtime-profile-binding",
            headers={"X-Actor-User-Id": actor},
        )

    assert response.status_code == 200
    payload = response.json()
    assert payload["case_id"] == case.case_id
    assert payload["case_sha256"] == case.case_sha256
    assert payload["profile"]["model_profile_id"] == "deterministic-off"
    assert payload["production_decision_authority"] == "human_only"
    assert response.headers["x-content-sha256"] == payload["binding_sha256"]
    assert response.headers["etag"] == f'"{payload["binding_sha256"]}"'


def test_governed_context_is_available_through_case_api(tmp_path: Path) -> None:
    site_root = (
        Path(__file__).parents[1] / "examples" / "site_packs" / "factory_a_line_01"
    )
    service = ProductService(
        tmp_path / "product",
        runner=_fake_runner(),
        recover_interrupted=False,
        incident_site_profiles={"factory-a-line-01": site_root},
        approved_memory_store_path=site_root / "approved_memory.jsonl",
        memory_admission_mode="legacy_card_v1",
    )
    actor, project_id = _setup(service)
    task = service.create_task(
        actor,
        CreateTaskRequest(
            project_id=project_id,
            goal="验证前端只能读取与当前 Case 验签一致的治理上下文。",
        ),
        auto_start=False,
    )
    task = service.run_task_sync(task.task_id)
    request = build_fixture_industrial_incident_request().model_copy(
        update={
            "runtime_profile": IncidentRuntimeProfile(
                memory_mode=IncidentMemoryMode.APPROVED_SITE,
                memory_top_k=4,
                site_profile_id="factory-a-line-01",
            )
        }
    )
    case = service.create_industrial_incident_case(actor, task.task_id, request)

    with TestClient(create_app(service, ensure_demo_tenant=False)) as client:
        response = client.get(
            f"/v1/tasks/{task.task_id}/industrial-incidents/"
            f"{case.case_id}/governed-context",
            headers={"X-Actor-User-Id": actor},
        )

    assert response.status_code == 200
    payload = response.json()
    assert payload["context"]["case_id"] == case.case_id
    assert payload["context"]["case_sha256"] == case.case_sha256
    assert payload["context"]["historical_memory_used_as_current_fact"] is False
    assert payload["receipt"]["raw_prompt_retained"] is False
    assert payload["receipt"]["raw_image_retained"] is False
    content_sha256 = hashlib.sha256(canonical_json_bytes(payload)).hexdigest()
    assert response.headers["x-content-sha256"] == content_sha256
    assert response.headers["etag"] == f'"{content_sha256}"'


def test_incident_audit_envelope_is_jcs_persisted_and_exposed_by_api(
    tmp_path: Path,
    capsys,
) -> None:
    service = ProductService(
        tmp_path / "product", runner=_fake_runner(), recover_interrupted=False
    )
    actor, project_id = _setup(service)
    task = service.create_task(
        actor,
        CreateTaskRequest(
            project_id=project_id,
            goal="验证案件审计根以 RFC 8785 Sidecar 独立持久化并通过 API 读取。",
        ),
        auto_start=False,
    )
    task = service.run_task_sync(task.task_id)
    case = service.create_industrial_incident_case(
        actor,
        task.task_id,
        build_fixture_industrial_incident_request(),
    )
    envelope = service.get_industrial_incident_audit_envelope(
        actor,
        task.task_id,
        case.case_id,
    )
    envelope_path = (
        service._incident_case_root(task, case.case_id)
        / "audit"
        / "governed_audit_envelope.json"
    )

    assert envelope_path.read_bytes() == canonical_jcs_bytes(envelope)
    assert envelope.subject.legacy_case_sha256 == case.case_sha256
    assert envelope.signature.status == "NOT_CONFIGURED"
    assert envelope.claim_boundary.startswith("TAMPER_EVIDENT_")

    with TestClient(create_app(service, ensure_demo_tenant=False)) as client:
        response = client.get(
            f"/v1/tasks/{task.task_id}/industrial-incidents/"
            f"{case.case_id}/audit-envelope",
            headers={"X-Actor-User-Id": actor},
        )
    assert response.status_code == 200
    assert response.json()["audit_root"]["value"] == envelope.audit_root.value
    assert response.headers["x-audit-root-sha256"] == envelope.audit_root.value
    assert response.headers["x-signature-status"] == "NOT_CONFIGURED"

    assert (
        cli_main(
            [
                "incident-audit-verify",
                "--case-dir",
                str(envelope_path.parent.parent),
            ]
        )
        == 0
    )
    verification = json.loads(capsys.readouterr().out)
    assert verification["verification_status"] == "PASS"
    assert verification["audit_root_sha256"] == envelope.audit_root.value
    assert verification["signature"] == "NOT_CONFIGURED"


def test_incident_audit_envelope_tampering_fails_closed(tmp_path: Path) -> None:
    service = ProductService(
        tmp_path / "product", runner=_fake_runner(), recover_interrupted=False
    )
    actor, project_id = _setup(service)
    task = service.create_task(
        actor,
        CreateTaskRequest(
            project_id=project_id,
            goal="验证案件 Audit Root 被修改后读取必须失败关闭。",
        ),
        auto_start=False,
    )
    task = service.run_task_sync(task.task_id)
    case = service.create_industrial_incident_case(
        actor,
        task.task_id,
        build_fixture_industrial_incident_request(),
    )
    envelope_path = (
        service._incident_case_root(task, case.case_id)
        / "audit"
        / "governed_audit_envelope.json"
    )
    payload = json.loads(envelope_path.read_text(encoding="utf-8"))
    payload["issuer"]["actor_id"] = "forged_local_operator"
    stable = dict(payload)
    stable.pop("audit_root")
    payload["audit_root"]["value"] = domain_separated_sha256(
        stable,
        AuditHashDomain.AUDIT_ROOT,
    )
    envelope_path.write_text(
        json.dumps(payload, ensure_ascii=False, sort_keys=True),
        encoding="utf-8",
    )

    with pytest.raises(ArtifactUnavailableError, match="audit anchor binding"):
        service.get_industrial_incident_case(actor, task.task_id, case.case_id)
    with pytest.raises(ValueError, match="anchor binding"):
        verify_governed_audit_case_directory(
            service._incident_case_root(task, case.case_id)
        )


def test_governed_incident_case_missing_audit_sidecar_fails_closed(
    tmp_path: Path,
) -> None:
    service = ProductService(
        tmp_path / "product", runner=_fake_runner(), recover_interrupted=False
    )
    actor, project_id = _setup(service)
    task = service.create_task(
        actor,
        CreateTaskRequest(
            project_id=project_id,
            goal="验证受治理案件缺少 Sidecar 时必须失败关闭。",
        ),
        auto_start=False,
    )
    task = service.run_task_sync(task.task_id)
    case = service.create_industrial_incident_case(
        actor,
        task.task_id,
        build_fixture_industrial_incident_request(),
    )
    envelope_path = (
        service._incident_case_root(task, case.case_id)
        / "audit"
        / "governed_audit_envelope.json"
    )
    envelope_path.unlink()

    with pytest.raises(ArtifactUnavailableError, match="required but missing"):
        service.get_industrial_incident_case(actor, task.task_id, case.case_id)


def test_governed_incident_case_missing_task_anchor_fails_closed(
    tmp_path: Path,
) -> None:
    service = ProductService(
        tmp_path / "product", runner=_fake_runner(), recover_interrupted=False
    )
    actor, project_id = _setup(service)
    task = service.create_task(
        actor,
        CreateTaskRequest(
            project_id=project_id,
            goal="验证受治理案件缺少独立 Anchor 时必须失败关闭。",
        ),
        auto_start=False,
    )
    task = service.run_task_sync(task.task_id)
    case = service.create_industrial_incident_case(
        actor,
        task.task_id,
        build_fixture_industrial_incident_request(),
    )
    service._incident_audit_anchor_path(task, case.case_id).unlink()

    with pytest.raises(
        ArtifactUnavailableError, match="anchor is required but missing"
    ):
        service.get_industrial_incident_case(actor, task.task_id, case.case_id)


def test_governed_audit_anchor_is_write_once_and_exact_replay_safe(
    tmp_path: Path,
) -> None:
    service = ProductService(
        tmp_path / "product", runner=_fake_runner(), recover_interrupted=False
    )
    actor, project_id = _setup(service)
    task = service.create_task(
        actor,
        CreateTaskRequest(
            project_id=project_id,
            goal="验证独立 Anchor 允许精确重放但拒绝不同 Audit Root。",
        ),
        auto_start=False,
    )
    task = service.run_task_sync(task.task_id)
    case = service.create_industrial_incident_case(
        actor,
        task.task_id,
        build_fixture_industrial_incident_request(),
    )
    envelope = service.get_industrial_incident_audit_envelope(
        actor,
        task.task_id,
        case.case_id,
    )
    anchor_path = service._incident_audit_anchor_path(task, case.case_id)
    original = anchor_path.read_bytes()

    service._persist_governed_audit_anchor(task, case, envelope)
    assert anchor_path.read_bytes() == original

    forged_payload = envelope.model_dump(mode="json")
    forged_payload["issuer"]["actor_id"] = "forged_local_operator"
    stable = dict(forged_payload)
    stable.pop("audit_root")
    forged_payload["audit_root"]["value"] = domain_separated_sha256(
        stable,
        AuditHashDomain.AUDIT_ROOT,
    )
    forged = parse_governed_audit_envelope_json(
        json.dumps(forged_payload, ensure_ascii=False)
    )

    with pytest.raises(ConflictError, match="immutable artifact already differs"):
        service._persist_governed_audit_anchor(task, case, forged)
    assert anchor_path.read_bytes() == original


def test_incident_audit_envelope_replacement_fails_closed(tmp_path: Path) -> None:
    service = ProductService(
        tmp_path / "product", runner=_fake_runner(), recover_interrupted=False
    )
    actor, project_id = _setup(service)
    task = service.create_task(
        actor,
        CreateTaskRequest(project_id=project_id, goal="验证案件封套不可跨案件替换。"),
        auto_start=False,
    )
    task = service.run_task_sync(task.task_id)
    first = service.create_industrial_incident_case(
        actor, task.task_id, build_fixture_industrial_incident_request(revision=1)
    )
    second = service.create_industrial_incident_case(
        actor, task.task_id, build_fixture_industrial_incident_request(revision=2)
    )
    first_path = (
        service._incident_case_root(task, first.case_id)
        / "audit"
        / "governed_audit_envelope.json"
    )
    second_path = (
        service._incident_case_root(task, second.case_id)
        / "audit"
        / "governed_audit_envelope.json"
    )
    first_path.write_bytes(second_path.read_bytes())

    with pytest.raises(ArtifactUnavailableError, match="audit envelope"):
        service.get_industrial_incident_case(actor, task.task_id, first.case_id)


def test_incident_audit_envelope_corruption_fails_closed(tmp_path: Path) -> None:
    service = ProductService(
        tmp_path / "product", runner=_fake_runner(), recover_interrupted=False
    )
    actor, project_id = _setup(service)
    task = service.create_task(
        actor,
        CreateTaskRequest(project_id=project_id, goal="验证损坏封套不会静默降级。"),
        auto_start=False,
    )
    task = service.run_task_sync(task.task_id)
    case = service.create_industrial_incident_case(
        actor, task.task_id, build_fixture_industrial_incident_request()
    )
    envelope_path = (
        service._incident_case_root(task, case.case_id)
        / "audit"
        / "governed_audit_envelope.json"
    )
    envelope_path.write_bytes(b'{"schema_version":')

    with pytest.raises(ArtifactUnavailableError, match="audit envelope"):
        service.get_industrial_incident_case(actor, task.task_id, case.case_id)


def test_governed_case_schema_rollback_fails_command_binding(tmp_path: Path) -> None:
    service = ProductService(
        tmp_path / "product", runner=_fake_runner(), recover_interrupted=False
    )
    actor, project_id = _setup(service)
    task = service.create_task(
        actor,
        CreateTaskRequest(
            project_id=project_id, goal="验证 v5 不能回滚伪装成 legacy。"
        ),
        auto_start=False,
    )
    task = service.run_task_sync(task.task_id)
    case = service.create_industrial_incident_case(
        actor, task.task_id, build_fixture_industrial_incident_request()
    )
    case_path = service._incident_case_root(task, case.case_id) / "case.json"
    payload = json.loads(case_path.read_text(encoding="utf-8"))
    payload["schema_version"] = "visiondata-gate.industrial-incident-case.v3"
    payload.pop("audit_envelope_requirement")
    payload.pop("planning_belief_ledger")
    payload.pop("worker_selection_receipt")
    payload.pop("parent_belief_revision_receipt")
    payload.pop("worker_execution_plan_receipt")
    payload.pop("council_arbitration_receipt")
    payload.pop("autonomy_guard_receipt")
    stable = dict(payload)
    stable.pop("case_sha256")
    payload["case_sha256"] = hashlib.sha256(canonical_json_bytes(stable)).hexdigest()
    write_canonical_json(case_path, payload)
    (
        service._incident_case_root(task, case.case_id)
        / "audit"
        / "governed_audit_envelope.json"
    ).unlink()

    with pytest.raises(ArtifactUnavailableError, match="immutable command binding"):
        service.get_industrial_incident_case(actor, task.task_id, case.case_id)
