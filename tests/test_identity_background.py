"""Account authority at execution/publication, separate from session lifetime.

Only the kernel runner is replaced by the existing sealed lifecycle fixture;
SQLite, approval, execution ownership, packaging, and publication are real.
These checks are not Agent E2E or production IAM validation.
"""

from __future__ import annotations

from pathlib import Path
from threading import Event

import pytest

import visiondata_gate.product_service as product_service_module
from tests.support.product_run_stub import make_product_lifecycle_stub_runner
from visiondata_gate.identity_service import IdentityError, IdentityService
from visiondata_gate.product_models import (
    CreateTaskRequest,
    TaskExecutionStatus,
    TaskInterventionAction,
    TaskInterventionRequest,
)
from visiondata_gate.product_service import ProductService

pytestmark = pytest.mark.tier_integration
PASSWORD = "synthetic background password 48"


def prepare_approved_task(service: ProductService):
    service.ensure_default_tenant()
    identity = IdentityService(service)
    admin = identity.setup(
        "usr_local_demo",
        login_name="administrator",
        display_name="Administrator",
        password=PASSWORD,
    )
    creator = identity.register(
        login_name="task-creator",
        display_name="Task creator",
        password=PASSWORD,
    )
    aid, uid = admin["user"]["user_id"], creator["user_id"]
    identity.approve(aid, uid)
    identity.add_member(aid, "wsp_local_demo", uid)
    session = identity.login(login_name="task-creator", password=PASSWORD)
    task = service.create_task(
        uid,
        CreateTaskRequest(
            project_id="prj_industrial_vision",
            goal="Verify approved identity lifecycle authority using synthetic data.",
            plan_approval_required=True,
        ),
        auto_start=False,
    )
    service.intervene_task(
        aid,
        task.task_id,
        TaskInterventionRequest(
            action=TaskInterventionAction.APPROVE_PLAN,
            note="Approve isolated synthetic lifecycle fixture.",
        ),
        start_approved_task=False,
    )
    return identity, aid, uid, session, task


def test_disabled_creator_before_execution_reaches_failed_without_running(
    tmp_path: Path,
) -> None:
    called = Event()
    stub = make_product_lifecycle_stub_runner()

    def observed_runner(*args, **kwargs):
        called.set()
        return stub(*args, **kwargs)

    service = ProductService(
        tmp_path / "product",
        runner=observed_runner,
        recover_interrupted=False,
    )
    try:
        identity, aid, uid, _, task = prepare_approved_task(service)
        identity.set_status(aid, uid, "DISABLED")
        raised = None
        try:
            service.run_task_sync(task.task_id)
        except Exception as exc:
            raised = exc
        current = service.store.get_task_unscoped(task.task_id)
        assert current.execution_status is TaskExecutionStatus.FAILED, (
            current.execution_status,
            type(raised).__name__ if raised else None,
        )
        assert not called.is_set()
        assert current.evidence_zip_rel is None
        assert raised is None, (
            "The managed task must record failure, not lose it in a worker."
        )
    finally:
        service.close(wait=True)


def test_disabled_creator_during_blocked_runner_cannot_publish(tmp_path: Path) -> None:
    entered, release = Event(), Event()
    stub = make_product_lifecycle_stub_runner()

    def blocked_runner(*args, **kwargs):
        entered.set()
        assert release.wait(timeout=10), "Test did not release its synthetic runner."
        return stub(*args, **kwargs)

    service = ProductService(
        tmp_path / "product",
        runner=blocked_runner,
        recover_interrupted=False,
    )
    try:
        identity, aid, uid, _, task = prepare_approved_task(service)
        service.start_task(task.task_id)
        assert entered.wait(timeout=10), "Approved task did not enter the runner."
        identity.set_status(aid, uid, "DISABLED")
        release.set()
        service.close(wait=True)
        current = service.store.get_task_unscoped(task.task_id)
        assert current.execution_status is TaskExecutionStatus.FAILED
        assert current.evidence_zip_rel is None
        assert current.completed_at is not None
    finally:
        release.set()
        service.close(wait=True)


def test_disabled_creator_at_final_publication_cannot_commit_completed(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    audited, release = Event(), Event()
    real_audit = product_service_module.audit_submission_zip

    def block_after_real_audit(*args, **kwargs):
        report = real_audit(*args, **kwargs)
        assert report.ok
        audited.set()
        assert release.wait(timeout=10), "Test did not release publication barrier."
        return report

    monkeypatch.setattr(
        product_service_module, "audit_submission_zip", block_after_real_audit
    )
    service = ProductService(
        tmp_path / "product",
        runner=make_product_lifecycle_stub_runner(),
        recover_interrupted=False,
    )
    try:
        identity, aid, uid, _, task = prepare_approved_task(service)
        service.start_task(task.task_id)
        assert audited.wait(timeout=10), "Task did not reach final publication barrier."
        identity.set_status(aid, uid, "DISABLED")
        release.set()
        service.close(wait=True)
        current = service.store.get_task_unscoped(task.task_id)
        assert current.execution_status is TaskExecutionStatus.FAILED
        assert current.evidence_zip_rel is None
        assert current.evidence_sha256 is None
        assert current.completed_at is not None
    finally:
        release.set()
        service.close(wait=True)


@pytest.mark.parametrize("rotation", ["logout", "password"])
def test_session_rotation_does_not_cancel_already_approved_background_task(
    tmp_path: Path,
    rotation: str,
) -> None:
    entered, release = Event(), Event()
    stub = make_product_lifecycle_stub_runner()

    def blocked_runner(*args, **kwargs):
        entered.set()
        assert release.wait(timeout=10), "Test did not release its synthetic runner."
        return stub(*args, **kwargs)

    service = ProductService(
        tmp_path / "product",
        runner=blocked_runner,
        recover_interrupted=False,
    )
    try:
        identity, aid, uid, session, task = prepare_approved_task(service)
        service.start_task(task.task_id)
        assert entered.wait(timeout=10), "Approved task did not enter the runner."
        if rotation == "logout":
            current_session = identity.authenticate(session["access_token"])
            identity.revoke_session(uid, current_session["session_id"])
        else:
            identity.change_password(
                uid, PASSWORD, "new synthetic background password 61"
            )
        with pytest.raises(IdentityError, match="identity_authentication_failed"):
            identity.authenticate(session["access_token"])
        release.set()
        service.close(wait=True)
        current = service.get_task(aid, task.task_id)
        assert current.execution_status is TaskExecutionStatus.COMPLETED
        assert current.evidence_zip_rel is not None
        assert service.evidence_path(aid, task.task_id).is_file()
    finally:
        release.set()
        service.close(wait=True)
