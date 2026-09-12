"""Local process ownership and explicit task recovery contracts.

An OS lock lives only for the executing process. SQLite records separately prove
that a RUNNING task was claimed by this protocol; an absent lock alone never
proves that a legacy runtime stopped. No timer, heartbeat or queue is involved.
"""

from __future__ import annotations

from contextlib import contextmanager
from datetime import UTC, datetime
import errno
import hashlib
import hmac
import os
from pathlib import Path
from typing import Iterator, Literal, TypeVar
import uuid

from pydantic import Field

from .evidence import canonical_json_bytes
from .product_models import ProductModel, TaskExecutionStatus, TaskRecord


_SHA256 = r"^[0-9a-f]{64}$"
_Sealed = TypeVar("_Sealed", bound=ProductModel)


class TaskExecutionRecoveryProjection(ProductModel):
    schema_version: Literal["visiondata-gate.task-execution-recovery.v1"] = (
        "visiondata-gate.task-execution-recovery.v1"
    )
    task_id: str
    workspace_id: str
    project_id: str
    execution_status: TaskExecutionStatus
    classification: Literal[
        "OWNED_RUNNING", "INTERRUPTED", "LEGACY_UNKNOWN", "NOT_APPLICABLE"
    ]
    can_recover: bool
    reason_codes: list[str]
    task_snapshot_sha256: str = Field(pattern=_SHA256)
    receipt_sha256: str = Field(pattern=_SHA256)


class RecoverTaskExecutionRequest(ProductModel):
    expected_snapshot_sha256: str = Field(pattern=_SHA256)
    reviewer_identity: str = Field(min_length=2, max_length=160)
    note: str = Field(min_length=2, max_length=1000)
    operator_attests_recovery: Literal[True]


class TaskExecutionRecoveryReceipt(ProductModel):
    schema_version: Literal["visiondata-gate.task-execution-recovery-receipt.v1"] = (
        "visiondata-gate.task-execution-recovery-receipt.v1"
    )
    task_id: str
    workspace_id: str
    project_id: str
    replacement_task_id: str
    original_snapshot_sha256: str = Field(pattern=_SHA256)
    failed_task_snapshot_sha256: str = Field(pattern=_SHA256)
    replacement_task_snapshot_sha256: str = Field(pattern=_SHA256)
    reviewer_identity: str
    note: str
    recovered_by: str
    recovered_at: str
    requires_new_plan_approval: Literal[True] = True
    auto_started: Literal[False] = False
    receipt_sha256: str = Field(pattern=_SHA256)


class ManagedExecutionOwner(ProductModel):
    schema_version: Literal["visiondata-gate.execution-owner.v1"] = (
        "visiondata-gate.execution-owner.v1"
    )
    task_id: str
    workspace_id: str
    project_id: str
    request_sha256: str = Field(pattern=_SHA256)
    execution_id: str
    process_id: int = Field(ge=1)
    started_at: str
    receipt_sha256: str = Field(pattern=_SHA256)


def seal_execution_model(model_type: type[_Sealed], **values: object) -> _Sealed:
    provisional = model_type(**values, receipt_sha256="0" * 64)
    stable = provisional.model_dump(mode="json", exclude={"receipt_sha256"})
    return model_type(
        **stable,
        receipt_sha256=hashlib.sha256(canonical_json_bytes(stable)).hexdigest(),
    )


def verify_execution_model(model: ProductModel) -> None:
    stable = model.model_dump(mode="json", exclude={"receipt_sha256"})
    observed = hashlib.sha256(canonical_json_bytes(stable)).hexdigest()
    if not hmac.compare_digest(observed, str(getattr(model, "receipt_sha256", ""))):
        raise ValueError("task execution receipt digest mismatch")


def new_execution_owner(task: TaskRecord) -> ManagedExecutionOwner:
    return seal_execution_model(
        ManagedExecutionOwner,
        task_id=task.task_id,
        workspace_id=task.workspace_id,
        project_id=task.project_id,
        request_sha256=task.request_sha256,
        execution_id="exec_" + uuid.uuid4().hex,
        process_id=os.getpid(),
        started_at=datetime.now(UTC).isoformat(),
    )


@contextmanager
def task_execution_lock(product_root: Path, task_id: str) -> Iterator[bool]:
    """Acquire one nonblocking cross-process lock until this context exits.

    Locks use OS file handles and are released after process death. Lockfiles are
    retained so another process never races an unlink with a new lock inode.
    """

    lock_root = product_root / "private" / "execution_locks"
    lock_root.mkdir(parents=True, exist_ok=True)
    lock_path = lock_root / (
        hashlib.sha256(task_id.encode("utf-8")).hexdigest() + ".lock"
    )
    descriptor = os.open(lock_path, os.O_CREAT | os.O_RDWR, 0o600)
    acquired = False
    try:
        if os.fstat(descriptor).st_size == 0:
            os.write(descriptor, b"0")
            os.fsync(descriptor)
        os.lseek(descriptor, 0, os.SEEK_SET)
        try:
            if os.name == "nt":
                import msvcrt

                msvcrt.locking(descriptor, msvcrt.LK_NBLCK, 1)
            else:
                import fcntl

                fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
            acquired = True
        except OSError as error:
            if error.errno not in {errno.EACCES, errno.EAGAIN, errno.EDEADLK}:
                raise
        yield acquired
    finally:
        if acquired:
            if os.name == "nt":
                import msvcrt

                os.lseek(descriptor, 0, os.SEEK_SET)
                msvcrt.locking(descriptor, msvcrt.LK_UNLCK, 1)
            else:
                import fcntl

                fcntl.flock(descriptor, fcntl.LOCK_UN)
        os.close(descriptor)
