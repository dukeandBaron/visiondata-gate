from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
import hashlib
from pathlib import Path
import subprocess
import sys
import threading

import pytest
from pydantic import ValidationError

from visiondata_gate.evidence import canonical_json_bytes
from visiondata_gate.product_models import (
    CreateProjectRequest,
    CreateTaskRequest,
    CreateUserRequest,
    CreateWorkspaceRequest,
    TaskExecutionStatus,
)
from visiondata_gate.product_service import ProductService
from visiondata_gate.task_store import ConflictError, NotFoundError
from tests.support.product_run_stub import make_product_lifecycle_stub_runner


def _task(service: ProductService):
    actor = service.create_user(CreateUserRequest(display_name="Recovery operator"))
    workspace = service.create_workspace(
        CreateWorkspaceRequest(name="Recovery fixture", owner_user_id=actor.user_id)
    )
    project = service.create_project(
        actor.user_id,
        CreateProjectRequest(
            workspace_id=workspace.workspace_id, name="Recovery contract"
        ),
    )
    task = service.create_task(
        actor.user_id,
        CreateTaskRequest(
            project_id=project.project_id,
            goal="Verify explicit interrupted-task recovery.",
        ),
        auto_start=False,
    )
    return actor.user_id, task


def test_second_service_cannot_reclaim_an_owned_running_task(tmp_path: Path) -> None:
    entered, release = threading.Event(), threading.Event()
    delegate = make_product_lifecycle_stub_runner()

    def blocking_runner(*args, **kwargs):
        entered.set()
        assert release.wait(15)
        return delegate(*args, **kwargs)

    service = ProductService(tmp_path / "product", runner=blocking_runner)
    actor, task = _task(service)
    pool = ThreadPoolExecutor(max_workers=1)
    future = pool.submit(service.run_task_sync, task.task_id)
    other = None
    try:
        assert entered.wait(10)
        other = ProductService(tmp_path / "product", recover_interrupted=True)
        assert (
            other.get_task(actor, task.task_id).execution_status
            is TaskExecutionStatus.RUNNING
        )
        projection = other.task_execution_recovery(actor, task.task_id)
        assert projection.classification == "OWNED_RUNNING"
        assert projection.can_recover is False
        with pytest.raises(ConflictError, match="execution owner is active"):
            other.recover_task_execution(
                actor, task.task_id, _recovery_request(other, actor, task)
            )
        assert len(other.list_tasks(actor)) == 1
        other.run_task_sync(task.task_id)
        assert (
            other.get_task(actor, task.task_id).execution_status
            is TaskExecutionStatus.RUNNING
        )
    finally:
        release.set()
        future.result(timeout=20)
        pool.shutdown(wait=True)
        service.close(wait=True)
        if other is not None:
            other.close(wait=True)


def _crash_managed_task(tmp_path: Path):
    service = ProductService(tmp_path / "product")
    actor, task = _task(service)
    code = """
import os
from pathlib import Path
import sys
from visiondata_gate.product_service import ProductService
def crash(root, **kwargs):
    root.mkdir(parents=True, exist_ok=True)
    (root / "partial-evidence.bin").write_bytes(b"must-remain-immutable")
    os._exit(23)
service = ProductService(Path(sys.argv[1]), runner=crash)
service.run_task_sync(sys.argv[2])
"""
    completed = subprocess.run(
        [sys.executable, "-c", code, str(service.product_root), task.task_id],
        capture_output=True,
        timeout=30,
        check=False,
    )
    assert completed.returncode == 23, completed.stderr.decode(errors="replace")
    assert (
        service.get_task(actor, task.task_id).execution_status
        is TaskExecutionStatus.RUNNING
    )
    return service, actor, task


@pytest.mark.parametrize("crashed_phase", ["RUNNING", "VERIFYING"])
def test_crash_releases_owner_and_recovery_creates_new_approval_gated_task(
    tmp_path: Path,
    crashed_phase: str,
) -> None:
    from visiondata_gate.execution_recovery import RecoverTaskExecutionRequest

    service, actor, task = _crash_managed_task(tmp_path)
    try:
        if crashed_phase == "VERIFYING":
            service.store.set_verifying_if_running(task.task_id)
        projection = service.task_execution_recovery(actor, task.task_id)
        assert projection.classification == "INTERRUPTED" and projection.can_recover
        assert (
            projection.receipt_sha256
            == hashlib.sha256(
                canonical_json_bytes(
                    projection.model_dump(mode="json", exclude={"receipt_sha256"})
                )
            ).hexdigest()
        )
        artifact = service._task_root(task) / "partial-evidence.bin"
        before = artifact.read_bytes()
        request = RecoverTaskExecutionRequest(
            expected_snapshot_sha256=projection.task_snapshot_sha256,
            reviewer_identity="QA recovery owner",
            note="Retain old artifacts and explicitly restart.",
            operator_attests_recovery=True,
        )
        recovered = service.recover_task_execution(actor, task.task_id, request)
        old = service.get_task(actor, task.task_id)
        replacement = service.get_task(actor, recovered.replacement_task_id)
        assert old.execution_status is TaskExecutionStatus.FAILED
        assert replacement.task_id != old.task_id
        assert replacement.execution_status is TaskExecutionStatus.PLANNED
        assert replacement.plan_approval_required is True
        assert replacement.goal == task.goal
        assert replacement.source_id == task.source_id
        assert replacement.allowed_tools == task.allowed_tools
        assert replacement.seed == task.seed
        assert service.list_interventions(actor, replacement.task_id) == []
        with pytest.raises(ConflictError, match="plan approval"):
            service.run_task_sync(replacement.task_id)
        assert not service._task_root(replacement).exists()
        assert artifact.read_bytes() == before
        assert service.recover_task_execution(actor, task.task_id, request) == recovered
        assert len(service.list_tasks(actor)) == 2
        with service.store._connection() as connection:
            assert (
                connection.execute("SELECT COUNT(*) FROM task_lineage").fetchone()[0]
                == 0
            )
    finally:
        service.close(wait=True)


def _recovery_request(service, actor, task):
    from visiondata_gate.execution_recovery import RecoverTaskExecutionRequest

    projection = service.task_execution_recovery(actor, task.task_id)
    return RecoverTaskExecutionRequest(
        expected_snapshot_sha256=projection.task_snapshot_sha256,
        reviewer_identity="QA recovery owner",
        note="Explicit local recovery.",
        operator_attests_recovery=True,
    )


def test_recovery_rejects_missing_consent_wrong_snapshot_and_cross_workspace(
    tmp_path: Path,
) -> None:
    from visiondata_gate.execution_recovery import RecoverTaskExecutionRequest

    service, actor, task = _crash_managed_task(tmp_path)
    try:
        request = _recovery_request(service, actor, task)
        with pytest.raises(ValidationError):
            RecoverTaskExecutionRequest(
                expected_snapshot_sha256=request.expected_snapshot_sha256,
                reviewer_identity="QA owner",
                note="No affirmative authorization.",
            )
        with pytest.raises(ValidationError):
            service.recover_task_execution(
                actor,
                task.task_id,
                request.model_copy(update={"operator_attests_recovery": False}),
            )
        with pytest.raises(ConflictError, match="task changed"):
            service.recover_task_execution(
                actor,
                task.task_id,
                request.model_copy(update={"expected_snapshot_sha256": "0" * 64}),
            )
        other_actor, _ = _task(service)
        with pytest.raises(NotFoundError):
            service.task_execution_recovery(other_actor, task.task_id)
        with pytest.raises(NotFoundError):
            service.recover_task_execution(other_actor, task.task_id, request)
        assert (
            service.get_task(actor, task.task_id).execution_status
            is TaskExecutionStatus.RUNNING
        )
        assert len(service.list_tasks(actor)) == 1
    finally:
        service.close(wait=True)


def test_legacy_running_without_managed_receipt_is_not_assumed_interrupted(
    tmp_path: Path,
) -> None:
    service = ProductService(tmp_path / "product")
    actor, task = _task(service)
    try:
        assert service.store.claim_task(task.task_id)
        projection = service.task_execution_recovery(actor, task.task_id)
        assert projection.classification == "LEGACY_UNKNOWN"
        assert projection.can_recover is False
        with pytest.raises(ConflictError, match="legacy execution ownership"):
            service.recover_task_execution(
                actor, task.task_id, _recovery_request(service, actor, task)
            )
        assert service.store.recover_interrupted() == 0
        assert (
            service.get_task(actor, task.task_id).execution_status
            is TaskExecutionStatus.RUNNING
        )
    finally:
        service.close(wait=True)


def test_concurrent_recovery_creates_one_replacement_and_retries_return_its_receipt(
    tmp_path: Path,
) -> None:
    service, actor, task = _crash_managed_task(tmp_path)
    other = ProductService(service.product_root)
    request = _recovery_request(service, actor, task)
    barrier = threading.Barrier(2)

    def recover(worker):
        barrier.wait(timeout=5)
        try:
            return worker.recover_task_execution(actor, task.task_id, request)
        except ConflictError:
            return None

    try:
        with ThreadPoolExecutor(max_workers=2) as pool:
            futures = [pool.submit(recover, worker) for worker in (service, other)]
            results = [future.result(timeout=10) for future in futures]
        successful = [result for result in results if result is not None]
        assert successful
        assert len({receipt.replacement_task_id for receipt in successful}) == 1
        assert (
            service.recover_task_execution(actor, task.task_id, request)
            == successful[0]
        )
        assert (
            other.recover_task_execution(actor, task.task_id, request) == successful[0]
        )
        assert len(service.list_tasks(actor)) == 2
        with pytest.raises(ConflictError, match="different recovery"):
            service.recover_task_execution(
                actor,
                task.task_id,
                request.model_copy(
                    update={
                        "note": "An unrelated second request must not create another attempt."
                    }
                ),
            )
    finally:
        service.close(wait=True)
        other.close(wait=True)
