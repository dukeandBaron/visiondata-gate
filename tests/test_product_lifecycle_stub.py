"""Hard boundaries for the lifecycle stub; these are not Agent E2E tests."""

from __future__ import annotations

from dataclasses import replace
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from tests.support.product_run_stub import make_product_lifecycle_stub_runner
from visiondata_gate.contracts import GateDecision, GateResult
from visiondata_gate.evidence import write_canonical_json
from visiondata_gate.product_models import (
    CreateProjectRequest,
    CreateTaskRequest,
    CreateUserRequest,
    CreateWorkspaceRequest,
    TaskExecutionStatus,
)
from visiondata_gate.product_runs import ProductTaskRun, verify_product_task_run
from visiondata_gate.product_service import ProductService
from visiondata_gate.runtime_models import RuntimeConfig, RuntimeStatus, RuntimeTrace


def test_legacy_untyped_lifecycle_runner_fails_task_and_never_completes(
    tmp_path: Path,
) -> None:
    """A legacy shape cannot masquerade as a completed Agent run."""

    def legacy_runner(output_dir: str | Path, **_kwargs: object) -> SimpleNamespace:
        evidence_dir = Path(output_dir) / "evidence"
        evidence_dir.mkdir(parents=True)
        trace_path = evidence_dir / "agent_runtime_trace.json"
        write_canonical_json(
            trace_path,
            {"schema_version": "test", "status": "success"},
        )
        return SimpleNamespace(
            evidence_dir=evidence_dir,
            runtime_trace_path=trace_path,
            initial_result=SimpleNamespace(decision=GateDecision.RECAPTURE),
            repaired_result=SimpleNamespace(decision=GateDecision.PASS),
            runtime_trace=SimpleNamespace(status=RuntimeStatus.SUCCESS, events=[]),
        )

    service = ProductService(
        tmp_path / "product",
        runner=legacy_runner,  # type: ignore[arg-type]
        recover_interrupted=False,
    )
    try:
        user = service.create_user(CreateUserRequest(display_name="Lifecycle Owner"))
        workspace = service.create_workspace(
            CreateWorkspaceRequest(
                name="Lifecycle Contract",
                owner_user_id=user.user_id,
            )
        )
        project = service.create_project(
            user.user_id,
            CreateProjectRequest(
                workspace_id=workspace.workspace_id,
                name="Reject legacy runner shape",
            ),
        )
        task = service.create_task(
            user.user_id,
            CreateTaskRequest(
                project_id=project.project_id,
                goal="验证旧测试替身绝不能冒充 Agent 完成态。",
            ),
            auto_start=False,
        )

        failed = service.run_task_sync(task.task_id)

        assert failed.execution_status is TaskExecutionStatus.FAILED
        assert failed.execution_status is not TaskExecutionStatus.COMPLETED
        assert failed.final_decision is None
        assert failed.error_code == "TypeError"
        assert failed.error_message == (
            "synthetic product runner must return AgenticDemoRun"
        )
    finally:
        service.close(wait=True)


def test_synthetic_task_rejects_authorized_runtime_kind_masquerade(
    tmp_path: Path,
) -> None:
    """The task source contract, not a runner label, selects the runtime kind."""

    sealed_runner = make_product_lifecycle_stub_runner()

    def wrong_kind_runner(output_dir: str | Path, **kwargs: object) -> ProductTaskRun:
        run = sealed_runner(output_dir, **kwargs)
        wrong_receipt = run.kernel_receipt.model_copy(
            update={"runtime_kind": "authorized_local_readonly"}
        )
        return replace(run, kernel_receipt=wrong_receipt)

    service = ProductService(
        tmp_path / "product",
        runner=wrong_kind_runner,
        recover_interrupted=False,
    )
    try:
        user = service.create_user(CreateUserRequest(display_name="Runtime Owner"))
        workspace = service.create_workspace(
            CreateWorkspaceRequest(
                name="Runtime Kind Contract",
                owner_user_id=user.user_id,
            )
        )
        project = service.create_project(
            user.user_id,
            CreateProjectRequest(
                workspace_id=workspace.workspace_id,
                name="Reject runtime-kind masquerade",
            ),
        )
        task = service.create_task(
            user.user_id,
            CreateTaskRequest(
                project_id=project.project_id,
                goal="验证 synthetic task 不能冒充 authorized runtime。",
            ),
            auto_start=False,
        )

        failed = service.run_task_sync(task.task_id)

        assert failed.execution_status is TaskExecutionStatus.FAILED
        assert failed.error_code == "ArtifactUnavailableError"
        assert failed.error_message == (
            "Agent kernel runtime kind does not match the task source contract"
        )
    finally:
        service.close(wait=True)


@pytest.mark.parametrize(
    "relative_path",
    ["agent_runtime_trace.json", "repaired/gate_result.json"],
)
def test_sealed_lifecycle_stub_tampering_fails_product_run_verification(
    tmp_path: Path,
    relative_path: str,
) -> None:
    """A sealed lifecycle artifact remains subject to the production verifier."""

    runner = make_product_lifecycle_stub_runner()
    run = runner(
        tmp_path / relative_path.replace("/", "-"),
        seed=20260828,
        goal="Verify sealed lifecycle artifact integrity; not Agent E2E.",
        config=RuntimeConfig(),
    )
    assert isinstance(run, ProductTaskRun)
    verify_product_task_run(run)

    target = run.evidence_dir / relative_path
    if relative_path == "agent_runtime_trace.json":
        trace = RuntimeTrace.model_validate_json(target.read_bytes())
        write_canonical_json(
            target,
            trace.model_copy(update={"goal": "tampered lifecycle goal"}),
        )
    else:
        gate_result = GateResult.model_validate_json(target.read_bytes())
        write_canonical_json(
            target,
            gate_result.model_copy(update={"decision": GateDecision.QUARANTINE}),
        )

    with pytest.raises(ValueError, match="kernel artifact integrity failed"):
        verify_product_task_run(run)

    # Keep an explicit machine-readable assertion that this was a local tamper test,
    # not a generated Agent result or benchmark score.
    assert (
        json.loads(
            (run.evidence_dir / "acceptance_scorecard.json").read_text(encoding="utf-8")
        )["overall_status"]
        == "NOT_EVALUATED_LIFECYCLE_STUB"
    )
