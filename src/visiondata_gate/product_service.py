"""Unified product service used by both the Streamlit workspace and REST API."""

from __future__ import annotations

import hashlib
import hmac
import json
import threading
from concurrent.futures import Future, ThreadPoolExecutor
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Callable

from .agent_runtime import AgenticDemoRun, run_agentic_demo
from .evidence import canonical_json_bytes, sha256_file
from .package import audit_submission_zip, build_deterministic_zip
from .product_models import (
    CreateProjectRequest,
    CreateTaskRequest,
    CreateUserRequest,
    CreateWorkspaceRequest,
    DataSourceKind,
    HealthResponse,
    ProjectRecord,
    TaskEventRecord,
    TaskExecutionStatus,
    TaskRecord,
    UserRecord,
    WorkspaceRecord,
)
from .runtime_models import ModelBackendKind, RuntimeConfig
from .task_store import ConflictError, NotFoundError, TaskStore


class ProductServiceError(RuntimeError):
    code = "service_error"


class UnsupportedSourceError(ProductServiceError):
    code = "source_not_connected"


class ArtifactUnavailableError(ProductServiceError):
    code = "artifact_unavailable"


Runner = Callable[..., AgenticDemoRun]

_TASK_EVIDENCE_REQUIRED = (
    "agent_runtime_trace.json",
    "demo_summary.json",
    "proof_index.json",
    "claim_scope_receipt.json",
    "initial/gate_result.json",
    "initial/evidence_matrix.csv",
    "repaired/gate_result.json",
    "repaired/evidence_matrix.csv",
)


def _now() -> str:
    return datetime.now(UTC).isoformat(timespec="milliseconds")


class ProductService:
    """Own task lifecycle, execution, persistence, and artifact boundaries."""

    def __init__(
        self,
        product_root: str | Path,
        *,
        runner: Runner = run_agentic_demo,
        max_workers: int = 1,
        recover_interrupted: bool = False,
    ) -> None:
        self.product_root = Path(product_root).expanduser().resolve()
        self.product_root.mkdir(parents=True, exist_ok=True)
        self.store = TaskStore(self.product_root / "product.sqlite3")
        self.runner = runner
        self._executor = ThreadPoolExecutor(
            max_workers=max_workers,
            thread_name_prefix="visiondata-product",
        )
        self._futures: dict[str, Future[None]] = {}
        self._future_lock = threading.Lock()
        if recover_interrupted:
            self.store.recover_interrupted()

    def close(self, *, wait: bool = False) -> None:
        self._executor.shutdown(wait=wait, cancel_futures=False)

    def health(self) -> HealthResponse:
        return HealthResponse(
            data_sources={
                DataSourceKind.SYNTHETIC_DEMO.value: "connected",
                DataSourceKind.LOCAL_AUTHORIZED_DIRECTORY.value: "not_connected",
                DataSourceKind.EXTERNAL_RESIDENCY_REFERENCE.value: "not_connected",
            }
        )

    def ensure_default_tenant(
        self,
    ) -> tuple[UserRecord, WorkspaceRecord, ProjectRecord]:
        return self.store.ensure_default_tenant()

    def create_user(self, request: CreateUserRequest) -> UserRecord:
        return self.store.create_user(request)

    def list_users(self) -> list[UserRecord]:
        return self.store.list_users()

    def create_workspace(self, request: CreateWorkspaceRequest) -> WorkspaceRecord:
        return self.store.create_workspace(request)

    def list_workspaces(self, actor_user_id: str) -> list[WorkspaceRecord]:
        return self.store.list_workspaces(actor_user_id)

    def create_project(
        self, actor_user_id: str, request: CreateProjectRequest
    ) -> ProjectRecord:
        return self.store.create_project(actor_user_id, request)

    def list_projects(
        self, actor_user_id: str, workspace_id: str
    ) -> list[ProjectRecord]:
        return self.store.list_projects(actor_user_id, workspace_id)

    def get_project(self, actor_user_id: str, project_id: str) -> ProjectRecord:
        return self.store.get_project(actor_user_id, project_id)

    @staticmethod
    def request_sha256(request: CreateTaskRequest, scenario_profile: str) -> str:
        payload = request.model_dump(mode="json")
        payload["scenario_profile"] = scenario_profile
        return hashlib.sha256(canonical_json_bytes(payload)).hexdigest()

    def create_task(
        self,
        actor_user_id: str,
        request: CreateTaskRequest,
        *,
        idempotency_key: str | None = None,
        auto_start: bool = True,
    ) -> TaskRecord:
        if request.source_kind is not DataSourceKind.SYNTHETIC_DEMO:
            raise UnsupportedSourceError(
                "this data source is reserved but is not connected or authorized"
            )
        project = self.store.get_project(actor_user_id, request.project_id)
        if request.source_kind is not project.source_kind:
            raise UnsupportedSourceError(
                "task data source must match the project's frozen data source"
            )
        if project.source_kind is not DataSourceKind.SYNTHETIC_DEMO:
            raise UnsupportedSourceError(
                "the selected project's data source is not connected or authorized"
            )
        scenario = request.scenario_profile or project.scenario_profile
        effective_tools = list(request.allowed_tools)
        if scenario.value != "generic" and "governance_audit" not in effective_tools:
            effective_tools.append("governance_audit")
        effective_request = request.model_copy(
            update={
                "scenario_profile": scenario,
                "source_kind": project.source_kind,
                "allowed_tools": effective_tools,
            }
        )
        normalized_key = None
        if idempotency_key is not None:
            normalized_key = idempotency_key.strip()
            if not normalized_key:
                raise ProductServiceError("idempotency key cannot be blank")
        request_hash = self.request_sha256(effective_request, scenario.value)
        task, created = self.store.create_task(
            actor_user_id,
            effective_request,
            scenario_profile=scenario.value,
            request_sha256=request_hash,
            idempotency_key=normalized_key,
        )
        if auto_start and task.execution_status is TaskExecutionStatus.PLANNED:
            self.start_task(task.task_id)
        return task

    def start_task(self, task_id: str) -> None:
        with self._future_lock:
            existing = self._futures.get(task_id)
            if existing is not None and not existing.done():
                return
            future = self._executor.submit(self._execute_task, task_id)
            self._futures[task_id] = future
        future.add_done_callback(
            lambda completed, run_id=task_id: self._discard_future(run_id, completed)
        )

    def _discard_future(self, task_id: str, expected: Future[None]) -> None:
        with self._future_lock:
            if self._futures.get(task_id) is expected:
                self._futures.pop(task_id, None)

    def run_task_sync(self, task_id: str) -> TaskRecord:
        self._execute_task(task_id)
        return self.store.get_task_unscoped(task_id)

    def _task_root(self, task: TaskRecord) -> Path:
        return (
            self.product_root
            / "runs"
            / task.workspace_id
            / task.project_id
            / task.task_id
            / "attempt-001"
        ).resolve()

    def _relative(self, path: Path) -> str:
        resolved = path.resolve(strict=False)
        try:
            return resolved.relative_to(self.product_root).as_posix()
        except ValueError as exc:
            raise ArtifactUnavailableError(
                "artifact path escaped product root"
            ) from exc

    def _execute_task(self, task_id: str) -> None:
        if not self.store.claim_task(task_id):
            return
        try:
            task = self.store.get_task_unscoped(task_id)
            task_root = self._task_root(task)
            if task_root.exists():
                raise ArtifactUnavailableError(
                    "the immutable task output directory already exists"
                )
            config = RuntimeConfig(
                backend=ModelBackendKind.DETERMINISTIC,
                scenario_profile=task.scenario_profile,
                allowed_tools=task.allowed_tools,
                persist_memory=True,
            )

            def on_event(event: Any) -> None:
                self.store.append_event(task_id, event)
                if str(event.phase) == "verification":
                    self.store.set_verifying_if_running(task_id)

            run = self.runner(
                task_root,
                seed=task.seed,
                goal=task.goal,
                config=config,
                memory_path=task_root / "runtime_memory.json",
                event_sink=on_event,
            )
            self.store.reconcile_events(task_id, list(run.runtime_trace.events))
            evidence_zip = task_root / "VisionDataGate_TaskEvidence.zip"
            build_deterministic_zip(run.evidence_dir, evidence_zip, overwrite=False)
            audit = audit_submission_zip(
                evidence_zip, required_paths=_TASK_EVIDENCE_REQUIRED
            )
            if not audit.ok:
                raise ArtifactUnavailableError(
                    f"task evidence audit failed with {len(audit.issues)} issue(s)"
                )
            final = TaskExecutionStatus.COMPLETED
            current = self.store.get_task_unscoped(task_id).execution_status
            if current is TaskExecutionStatus.RUNNING:
                self.store.set_verifying_if_running(task_id)
            self.store.transition_task(
                task_id,
                final,
                current_phase="completed",
                fields={
                    "initial_decision": run.initial_result.decision.value,
                    "final_decision": run.repaired_result.decision.value,
                    "runtime_status": run.runtime_trace.status.value,
                    "artifact_root_rel": self._relative(task_root),
                    "trace_rel": self._relative(run.runtime_trace_path),
                    "trace_sha256": sha256_file(run.runtime_trace_path),
                    "evidence_zip_rel": self._relative(evidence_zip),
                    "evidence_sha256": sha256_file(evidence_zip),
                    "completed_at": _now(),
                },
            )
        except Exception as exc:
            current = self.store.get_task_unscoped(task_id)
            if current.execution_status in {
                TaskExecutionStatus.RUNNING,
                TaskExecutionStatus.VERIFYING,
            }:
                self.store.transition_task(
                    task_id,
                    TaskExecutionStatus.FAILED,
                    current_phase="failed",
                    fields={
                        "error_code": type(exc).__name__,
                        "error_message": str(exc)[:500],
                        "completed_at": _now(),
                    },
                )

    def get_task(self, actor_user_id: str, task_id: str) -> TaskRecord:
        return self.store.get_task(actor_user_id, task_id)

    def list_tasks(
        self,
        actor_user_id: str,
        *,
        workspace_id: str | None = None,
        project_id: str | None = None,
        limit: int = 100,
    ) -> list[TaskRecord]:
        return self.store.list_tasks(
            actor_user_id,
            workspace_id=workspace_id,
            project_id=project_id,
            limit=limit,
        )

    def list_events(self, actor_user_id: str, task_id: str) -> list[TaskEventRecord]:
        return self.store.list_events(actor_user_id, task_id)

    def _artifact_path(
        self,
        actor_user_id: str,
        task_id: str,
        field: str,
        hash_field: str,
    ) -> Path:
        task = self.store.get_task(actor_user_id, task_id)
        if task.execution_status is not TaskExecutionStatus.COMPLETED:
            raise ArtifactUnavailableError("task artifacts are not ready")
        relative = getattr(task, field)
        if not relative:
            raise ArtifactUnavailableError("task artifact is missing")
        candidate = (self.product_root / relative).resolve(strict=False)
        try:
            candidate.relative_to(self._task_root(task))
        except ValueError as exc:
            raise ArtifactUnavailableError(
                "task artifact escaped immutable task root"
            ) from exc
        if not candidate.is_file():
            raise ArtifactUnavailableError("task artifact is not a regular file")
        expected = getattr(task, hash_field)
        if not expected:
            raise ArtifactUnavailableError("task artifact digest is missing")
        observed = sha256_file(candidate)
        if not hmac.compare_digest(observed, expected):
            raise ArtifactUnavailableError("task artifact integrity check failed")
        return candidate

    def trace_path(self, actor_user_id: str, task_id: str) -> Path:
        return self._artifact_path(actor_user_id, task_id, "trace_rel", "trace_sha256")

    def evidence_path(self, actor_user_id: str, task_id: str) -> Path:
        return self._artifact_path(
            actor_user_id, task_id, "evidence_zip_rel", "evidence_sha256"
        )

    def evidence_member_path(
        self, actor_user_id: str, task_id: str, relative_path: str
    ) -> Path:
        """Resolve one evidence member without accepting a client filesystem path."""

        relative = Path(relative_path)
        if (
            relative.is_absolute()
            or not relative.parts
            or any(part in {"", ".", ".."} for part in relative.parts)
        ):
            raise ArtifactUnavailableError("invalid evidence member")
        evidence_root = self.trace_path(actor_user_id, task_id).parent.resolve(
            strict=True
        )
        candidate = (evidence_root / relative).resolve(strict=False)
        try:
            candidate.relative_to(evidence_root)
        except ValueError as exc:
            raise ArtifactUnavailableError(
                "evidence member escaped task evidence"
            ) from exc
        if not candidate.is_file():
            raise ArtifactUnavailableError("evidence member is missing")
        return candidate

    def read_evidence_zip_json(
        self, actor_user_id: str, task_id: str, relative_path: str
    ) -> dict[str, Any]:
        """Read structured evidence only from the SHA-verified immutable ZIP."""

        import zipfile

        normalized = Path(relative_path).as_posix()
        if (
            normalized.startswith("/")
            or normalized in {"", ".", ".."}
            or ".." in Path(normalized).parts
            or not normalized.casefold().endswith(".json")
        ):
            raise ArtifactUnavailableError("invalid evidence ZIP member")
        archive_path = self.evidence_path(actor_user_id, task_id)
        try:
            with zipfile.ZipFile(archive_path) as archive:
                payload = json.loads(archive.read(normalized).decode("utf-8"))
        except (KeyError, UnicodeDecodeError, zipfile.BadZipFile) as exc:
            raise ArtifactUnavailableError(
                "evidence ZIP member is unavailable"
            ) from exc
        if not isinstance(payload, dict):
            raise ArtifactUnavailableError("evidence JSON must be an object")
        return payload

    def read_evidence_zip_bytes(
        self, actor_user_id: str, task_id: str, relative_path: str
    ) -> bytes:
        """Read one safe member after the evidence ZIP digest is verified."""

        import zipfile

        normalized = Path(relative_path).as_posix()
        if (
            normalized.startswith("/")
            or normalized in {"", ".", ".."}
            or ".." in Path(normalized).parts
        ):
            raise ArtifactUnavailableError("invalid evidence ZIP member")
        archive_path = self.evidence_path(actor_user_id, task_id)
        try:
            with zipfile.ZipFile(archive_path) as archive:
                return archive.read(normalized)
        except (KeyError, zipfile.BadZipFile) as exc:
            raise ArtifactUnavailableError(
                "evidence ZIP member is unavailable"
            ) from exc

    def read_evidence_json(
        self, actor_user_id: str, task_id: str, relative_path: str
    ) -> dict[str, Any]:
        path = self.evidence_member_path(actor_user_id, task_id, relative_path)
        if path.suffix.casefold() != ".json":
            raise ArtifactUnavailableError("requested evidence member is not JSON")
        payload = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(payload, dict):
            raise ArtifactUnavailableError("evidence JSON must be an object")
        return payload

    def read_trace(self, actor_user_id: str, task_id: str) -> dict[str, Any]:
        return json.loads(self.trace_path(actor_user_id, task_id).read_text("utf-8"))


_default_services: dict[Path, ProductService] = {}
_default_lock = threading.Lock()


def get_product_service(
    product_root: str | Path, *, recover_interrupted: bool = False
) -> ProductService:
    """Return a process-local service without mutating another process's runs.

    Startup recovery is deliberately opt-in.  A Streamlit and API process may
    share the same SQLite database during local evaluation, so assuming that a
    RUNNING row is stale merely because this process started would be unsafe.
    """

    root = Path(product_root).expanduser().resolve()
    with _default_lock:
        service = _default_services.get(root)
        if service is None:
            service = ProductService(root, recover_interrupted=recover_interrupted)
            _default_services[root] = service
    return service


__all__ = [
    "ArtifactUnavailableError",
    "ConflictError",
    "NotFoundError",
    "ProductService",
    "ProductServiceError",
    "UnsupportedSourceError",
    "get_product_service",
]
