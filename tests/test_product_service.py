from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from visiondata_gate.contracts import GateDecision
from visiondata_gate.evidence import write_canonical_json
from visiondata_gate.product_models import (
    CreateProjectRequest,
    CreateTaskRequest,
    CreateUserRequest,
    CreateWorkspaceRequest,
    DataSourceKind,
    TaskExecutionStatus,
)
from visiondata_gate.product_service import (
    ArtifactUnavailableError,
    ProductService,
    UnsupportedSourceError,
)
from visiondata_gate.runtime_models import RuntimeEvent, RuntimeStage, RuntimeStatus


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


def _fake_runner(final_decision: GateDecision = GateDecision.PASS):
    def run(output_dir: str | Path, **kwargs: object) -> SimpleNamespace:
        root = Path(output_dir)
        evidence = root / "evidence"
        (evidence / "initial").mkdir(parents=True)
        (evidence / "repaired").mkdir(parents=True)
        event_sink = kwargs.get("event_sink")
        emitted_events: list[RuntimeEvent] = []
        if callable(event_sink):
            emitted_events.extend(
                [
                    RuntimeEvent(
                        sequence=1,
                        phase="initial",
                        stage=RuntimeStage.INTAKE,
                        actor="Task Trigger",
                        action="accept",
                        status=RuntimeStatus.SUCCESS,
                        summary="任务已接收。",
                    ),
                    RuntimeEvent(
                        sequence=2,
                        phase="verification",
                        stage=RuntimeStage.VERIFY,
                        actor="Verification",
                        action="verify",
                        status=RuntimeStatus.SUCCESS,
                        summary="进入复验。",
                    ),
                ]
            )
            for event in emitted_events:
                event_sink(event)
        artifacts = {
            "agent_runtime_trace.json": {"schema_version": "test", "status": "success"},
            "demo_summary.json": {"final": final_decision.value},
            "proof_index.json": {"status": "PASS"},
            "claim_scope_receipt.json": {"production": "NOT_AVAILABLE"},
            "initial/gate_result.json": {"decision": "RECAPTURE"},
            "initial/evidence_matrix.csv": "finding_id,work_order_ids\nf1,w1\n",
            "repaired/gate_result.json": {"decision": final_decision.value},
            "repaired/evidence_matrix.csv": "finding_id,work_order_ids\n",
        }
        for relative, payload in artifacts.items():
            path = evidence / relative
            path.parent.mkdir(parents=True, exist_ok=True)
            if isinstance(payload, str):
                path.write_text(payload, encoding="utf-8", newline="\n")
            else:
                write_canonical_json(path, payload)
        trace_path = evidence / "agent_runtime_trace.json"
        return SimpleNamespace(
            evidence_dir=evidence,
            runtime_trace_path=trace_path,
            initial_result=SimpleNamespace(decision=GateDecision.RECAPTURE),
            repaired_result=SimpleNamespace(decision=final_decision),
            runtime_trace=SimpleNamespace(
                status=RuntimeStatus.SUCCESS, events=emitted_events
            ),
        )

    return run


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
    base_runner = _fake_runner()

    def tampering_runner(output_dir: str | Path, **kwargs: object) -> SimpleNamespace:
        run = base_runner(output_dir, **kwargs)
        original_events = list(run.runtime_trace.events)
        run.runtime_trace.events = [
            original_events[0].model_copy(update={"summary": "伪造的回放事件"}),
            original_events[1],
        ]
        return run

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
