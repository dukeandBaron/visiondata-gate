"""Persisted, scoped compute handoffs. This module never contacts a scheduler.

CANN describes the requested runtime, not a cluster submission API. A future
adapter must preserve the input binding and acquire separate execution authority.
"""

from __future__ import annotations

from datetime import UTC, datetime
import hashlib
import hmac
import json
from typing import TYPE_CHECKING, Any, Literal, Protocol
from uuid import uuid4

from pydantic import Field

from .audit_envelope import canonical_jcs_bytes
from .contracts import GateDecision
from .pipeline import compute_batch_digest
from .product_models import DataSourceKind, ProductModel, TaskExecutionStatus
from .task_store import NotFoundError, ProductStoreError

if TYPE_CHECKING:
    from .product_service import ProductService

SHA = r"^[0-9a-f]{64}$"
REQUIRED_TOOLS = frozenset(
    {
        "image_quality",
        "annotation_integrity",
        "duplicate_leakage",
        "coverage_matrix",
        "governance_audit",
    }
)


class ComputeHandoffError(ProductStoreError):
    code = "compute_handoff_hold"


class ComputeResources(ProductModel):
    runtime_image: str = Field(
        pattern=r"^[A-Za-z0-9][A-Za-z0-9./:_-]{0,220}@sha256:[0-9a-f]{64}$"
    )
    cann_version: str = Field(pattern=r"^[A-Za-z0-9.+_-]{1,40}$")
    npu_count: int = Field(ge=1, le=64, strict=True)
    cpu_cores: int = Field(ge=1, le=256, strict=True)
    memory_gib: int = Field(ge=1, le=4096, strict=True)
    max_wall_seconds: int = Field(ge=60, le=86400, strict=True)


class ComputeHandoffRequest(ProductModel):
    request_key: str = Field(pattern=r"^[A-Za-z0-9_-]{12,100}$")
    expected_preflight_sha256: str = Field(pattern=SHA)
    review_note: str = Field(min_length=8, max_length=2000)
    operator_attests_reviewed: Literal[True]
    workload: Literal["TRAINING", "EVALUATION"]
    resources: ComputeResources


class ComputeSchedulerAdapter(Protocol):
    def capabilities(self) -> dict[str, Any]: ...
    def submit(self, manifest: dict[str, Any]) -> dict[str, Any]: ...
    def poll(self, external_job_id: str) -> dict[str, Any]: ...
    def cancel(self, external_job_id: str) -> dict[str, Any]: ...


class OfflineComputeAdapter:
    def capabilities(self) -> dict[str, Any]:
        return {
            "kind": "OFFLINE_EXPORT",
            "accelerator": "ASCEND_NPU",
            "runtime_family": "CANN",
            "live_submission_available": False,
            "device_validation": "NOT_TESTED",
        }

    def submit(self, manifest: dict[str, Any]) -> dict[str, Any]:
        raise ComputeHandoffError(
            "CONNECTOR_NOT_CONFIGURED: no remote job was submitted"
        )

    def poll(self, external_job_id: str) -> dict[str, Any]:
        raise ComputeHandoffError(
            "CONNECTOR_NOT_CONFIGURED: no remote job status is available"
        )

    def cancel(self, external_job_id: str) -> dict[str, Any]:
        raise ComputeHandoffError(
            "CONNECTOR_NOT_CONFIGURED: no remote job was cancelled"
        )


def _sha(value: Any) -> str:
    return hashlib.sha256(canonical_jcs_bytes(value)).hexdigest()


def _sealed(values: dict[str, Any]) -> dict[str, Any]:
    return {**values, "receipt_sha256": _sha(values)}


def compute_preflight(
    service: ProductService, actor: str, task_id: str
) -> dict[str, Any]:
    task = service.store.get_task(actor, task_id)
    blockers: list[str] = []
    binding = None
    if task.execution_status is not TaskExecutionStatus.COMPLETED:
        blockers.append("TASK_NOT_COMPLETED")
    elif (
        task.source_kind is not DataSourceKind.LOCAL_AUTHORIZED_DIRECTORY
        or not task.source_id
    ):
        blockers.append("REVIEWED_OPERATOR_SNAPSHOT_REQUIRED")
    else:
        try:
            _task, batch_root, manifest, contract, gate = service._annotation_context(
                actor, task_id
            )
            _task, _source_root, snapshot, _profile = (
                service._operator_snapshot_visual_context(actor, task_id)
            )
            source = service.store.get_local_source_authorization(actor, task.source_id)
            if source.status != "active":
                blockers.append("SOURCE_AUTHORIZATION_INACTIVE")
            requirements = getattr(snapshot, "acceptance_requirements", None)
            if (
                snapshot.schema_version
                != "visiondata-gate.operator-project-snapshot.v2"
                or requirements is None
            ):
                blockers.append("EXPLICIT_ANNOTATION_REVIEW_REQUIRED")
            elif source.data_profile.get("acceptance_requirements_sha256") != _sha(
                requirements.model_dump(mode="json")
            ):
                blockers.append("ACCEPTANCE_BINDING_MISMATCH")
            elif getattr(contract, "acceptance_requirements_sha256", None) != _sha(
                requirements.model_dump(mode="json")
            ):
                blockers.append("CONTRACT_ACCEPTANCE_MISMATCH")
            if gate.decision is not GateDecision.PASS:
                blockers.append("GATE_NOT_PASS")
            completed_tools = {
                trace.tool for trace in gate.tool_trace if trace.status == "ok"
            }
            if not REQUIRED_TOOLS.issubset(completed_tools):
                blockers.append("INCOMPLETE_DETERMINISTIC_CHECKS")
            if not hmac.compare_digest(
                compute_batch_digest(batch_root, manifest, contract), gate.input_sha256
            ):
                blockers.append("GATE_INPUT_MISMATCH")
            if not blockers:
                binding = {
                    "task_id": task_id,
                    "workspace_id": task.workspace_id,
                    "project_id": task.project_id,
                    "source_id": task.source_id,
                    "snapshot_id": snapshot.snapshot_id,
                    "snapshot_receipt_sha256": snapshot.receipt_sha256,
                    "acceptance_requirements_sha256": source.data_profile[
                        "acceptance_requirements_sha256"
                    ],
                    "batch_manifest_sha256": snapshot.batch_manifest_sha256,
                    "batch_contract_sha256": snapshot.batch_contract_sha256,
                    "batch_digest_sha256": gate.input_sha256,
                    "gate_result_sha256": _sha(gate.model_dump(mode="json")),
                    "sample_count": len(manifest.samples),
                    "intended_use": contract.intended_use,
                }
        except (OSError, ValueError, RuntimeError):
            blockers.append("FROZEN_EVIDENCE_UNAVAILABLE")
    return _sealed(
        {
            "schema_version": "visiondata-gate.compute-preflight.v1",
            "task_id": task_id,
            "workspace_id": task.workspace_id,
            "project_id": task.project_id,
            "eligibility": "HOLD" if blockers else "READY_FOR_OFFLINE_HANDOFF",
            "blockers": sorted(set(blockers)),
            "binding": binding,
            "adapter": OfflineComputeAdapter().capabilities(),
            "production_release_allowed": False,
        }
    )


def _create_table(connection: Any) -> None:
    connection.execute("""CREATE TABLE IF NOT EXISTS compute_handoffs (
        handoff_id TEXT PRIMARY KEY, task_id TEXT NOT NULL, workspace_id TEXT NOT NULL,
        actor_id TEXT NOT NULL, request_key TEXT NOT NULL, request_sha256 TEXT NOT NULL,
        record_json TEXT NOT NULL, UNIQUE(task_id, actor_id, request_key))""")


def _load_record(row: Any) -> dict[str, Any]:
    try:
        record = json.loads(row["record_json"])
        stable = {
            key: value for key, value in record.items() if key != "receipt_sha256"
        }
        if not hmac.compare_digest(record["receipt_sha256"], _sha(stable)):
            raise ValueError("digest mismatch")
        if (
            record["task_id"] != row["task_id"]
            or record["prepared_by"] != row["actor_id"]
            or record["request"]["request_key"] != row["request_key"]
        ):
            raise ValueError("row mismatch")
        if (
            record["status"] != "PREPARED_NOT_SUBMITTED"
            or record["remote_execution_verified"] is not False
        ):
            raise ValueError("authority mismatch")
        return record
    except (KeyError, TypeError, ValueError) as error:
        raise ComputeHandoffError("HANDOFF_INTEGRITY_HOLD") from error


def prepare_compute_handoff(
    service: ProductService, actor: str, task_id: str, request: ComputeHandoffRequest
) -> dict[str, Any]:
    preflight = compute_preflight(service, actor, task_id)
    if preflight["eligibility"] != "READY_FOR_OFFLINE_HANDOFF":
        raise ComputeHandoffError(
            "COMPUTE_PREFLIGHT_HOLD: " + ",".join(preflight["blockers"])
        )
    if not hmac.compare_digest(
        preflight["receipt_sha256"], request.expected_preflight_sha256
    ):
        raise ComputeHandoffError("STALE_PREFLIGHT: reload the frozen input checks")
    request_json = request.model_dump(mode="json")
    request_sha = _sha(request_json)
    # Source reads may update expiry state and acquire their own write lock.
    # Recheck before entering our transaction, then check the source row inside
    # that transaction without nesting TaskStore connections.
    if compute_preflight(service, actor, task_id) != preflight:
        raise ComputeHandoffError("STALE_PREFLIGHT")
    with service.store._connection(immediate=True) as connection:
        service.store._require_membership(connection, preflight["workspace_id"], actor)
        source_row = connection.execute(
            "SELECT status, authorization_valid_until FROM local_source_authorizations WHERE source_id=? AND workspace_id=?",
            (preflight["binding"]["source_id"], preflight["workspace_id"]),
        ).fetchone()
        if source_row is None or source_row["status"] != "active":
            raise ComputeHandoffError("SOURCE_AUTHORIZATION_INACTIVE")
        valid_until = source_row["authorization_valid_until"]
        if valid_until and datetime.fromisoformat(
            valid_until.replace("Z", "+00:00")
        ) <= datetime.now(UTC):
            raise ComputeHandoffError("SOURCE_AUTHORIZATION_INACTIVE")
        _create_table(connection)
        row = connection.execute(
            "SELECT * FROM compute_handoffs WHERE task_id=? AND actor_id=? AND request_key=?",
            (task_id, actor, request.request_key),
        ).fetchone()
        if row is not None:
            if row["request_sha256"] != request_sha:
                raise ComputeHandoffError("IDEMPOTENCY_CONFLICT")
            return _load_record(row)
        record = _sealed(
            {
                "schema_version": "visiondata-gate.compute-handoff.v1",
                "handoff_id": "compute_" + uuid4().hex[:20],
                "task_id": task_id,
                "workspace_id": preflight["workspace_id"],
                "project_id": preflight["project_id"],
                "prepared_by": actor,
                "prepared_at": datetime.now(UTC).isoformat(timespec="milliseconds"),
                "status": "PREPARED_NOT_SUBMITTED",
                "request": request_json,
                "binding": preflight["binding"],
                "adapter": OfflineComputeAdapter().capabilities(),
                "remote_job_id": None,
                "remote_execution_verified": False,
                "dataset_bytes_exported": False,
                "production_release_allowed": False,
                "machine_write_permitted": False,
                "boundary": "Metadata-only request for a separately authorized scheduler adapter. No CANN/NPU execution, dataset transfer, customer acceptance or production approval.",
            }
        )
        connection.execute(
            "INSERT INTO compute_handoffs VALUES (?,?,?,?,?,?,?)",
            (
                record["handoff_id"],
                task_id,
                record["workspace_id"],
                actor,
                request.request_key,
                request_sha,
                json.dumps(record, ensure_ascii=False),
            ),
        )
    return record


def read_compute_handoffs(
    service: ProductService, actor: str, task_id: str
) -> dict[str, Any]:
    preflight = compute_preflight(service, actor, task_id)
    with service.store._connection() as connection:
        exists = connection.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='compute_handoffs'"
        ).fetchone()
        rows = (
            []
            if exists is None
            else connection.execute(
                "SELECT * FROM compute_handoffs WHERE task_id=? ORDER BY handoff_id",
                (task_id,),
            ).fetchall()
        )
    records = []
    for row in rows:
        record = _load_record(row)
        fresh = (
            preflight["eligibility"] == "READY_FOR_OFFLINE_HANDOFF"
            and record["binding"] == preflight["binding"]
        )
        records.append(
            {"read_status": "VERIFIED" if fresh else "STALE_HOLD", "record": record}
        )
    return _sealed(
        {
            "schema_version": "visiondata-gate.compute-handoff-list.v1",
            "task_id": task_id,
            "workspace_id": preflight["workspace_id"],
            "project_id": preflight["project_id"],
            "items": records,
        }
    )


def export_compute_handoff(
    service: ProductService, actor: str, task_id: str, handoff_id: str
) -> dict[str, Any]:
    for item in read_compute_handoffs(service, actor, task_id)["items"]:
        if item["record"]["handoff_id"] == handoff_id:
            if item["read_status"] != "VERIFIED":
                raise ComputeHandoffError(
                    "STALE_HOLD: source authorization or frozen evidence changed"
                )
            return item["record"]
    raise NotFoundError("compute handoff not found in task")
