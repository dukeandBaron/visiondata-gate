"""Read-only reconciliation of learning POST identities to current sealed records.

The request ledger stores the JCS digest of the validated request including
defaults, not a digest of the raw HTTP body. Its result pointer resolves to the
current record, which may have changed since the original response. Missing
ledger rows never prove that no write occurred, including an in-progress create.
"""

from __future__ import annotations

import hashlib
import hmac
import re

from .audit_envelope import canonical_jcs_bytes
from .learning_contracts import CreateLearningCycle, RunLearningRound
from .learning_service import LearningError, LearningService
from .task_store import NotFoundError


_RESULT_KINDS = {
    "create": "cycle",
    "train": "run",
    "feedback": "run",
    "followup": "run",
    "select": "cycle",
    "rollback": "cycle",
    "cancel": "cycle",
    "recover": "cycle",
    "finalize": "cycle",
}
_IDENTIFIER = re.compile(r"[A-Za-z0-9_-]{1,120}")
_REQUEST_KEY = re.compile(r"[A-Za-z0-9_-]{12,100}")
_DIGEST = re.compile(r"[0-9a-f]{64}")


def _sha(value: dict) -> str:
    return hashlib.sha256(canonical_jcs_bytes(value)).hexdigest()


def _seal(value: dict) -> dict:
    return value | {"receipt_sha256": _sha(value)}


def _validate_result_scope(connection, operation, target_id, result, project_id):
    if result["project_id"] != project_id:
        raise LearningError("LEARNING_OPERATION_RESULT_INTEGRITY_HOLD")
    if operation in {"rollback", "cancel", "recover", "finalize"}:
        if result["cycle_id"] != target_id:
            raise LearningError("LEARNING_OPERATION_RESULT_INTEGRITY_HOLD")
    elif operation == "train":
        if result["cycle_id"] != target_id:
            raise LearningError("LEARNING_OPERATION_RESULT_INTEGRITY_HOLD")
    elif operation in {"feedback", "followup"}:
        if not any(item.get("feedback_id") == target_id for item in result.get("feedback", [])):
            raise LearningError("LEARNING_OPERATION_RESULT_INTEGRITY_HOLD")
    elif operation == "select":
        try:
            run = LearningService._read(connection, target_id, "run")
        except NotFoundError as error:
            raise LearningError("LEARNING_OPERATION_RESULT_INTEGRITY_HOLD") from error
        if run["project_id"] != project_id or run["cycle_id"] != result["cycle_id"]:
            raise LearningError("LEARNING_OPERATION_RESULT_INTEGRITY_HOLD")


def _validate_request_digest(operation, request_key, stored_digest, result):
    if not isinstance(stored_digest, str) or _DIGEST.fullmatch(stored_digest) is None:
        raise LearningError("LEARNING_OPERATION_REQUEST_INTEGRITY_HOLD")
    # Other action bodies are not retained in full by learning_requests. Do not
    # invent reconstruction from later events or claim their raw response is known.
    if operation not in {"create", "train"}:
        return "LEDGER_SHA_ONLY"
    request_type, field = (
        (CreateLearningCycle, "request") if operation == "create"
        else (RunLearningRound, "approval")
    )
    try:
        request = request_type.model_validate(result[field])
        observed = _sha(request.model_dump(mode="json"))
        if request.request_key != request_key or not hmac.compare_digest(observed, stored_digest):
            raise ValueError("binding mismatch")
    except (KeyError, TypeError, ValueError) as error:
        raise LearningError("LEARNING_OPERATION_REQUEST_INTEGRITY_HOLD") from error
    return "MATCHED_STORED_VALIDATED_REQUEST"


def read_learning_operation(
    product,
    actor: str,
    project_id: str,
    operation: str,
    request_key: str,
    target_id: str,
) -> dict:
    """Resolve one actor-owned request without executing or replaying anything.

    No LearningService instance is constructed: absent learning tables remain
    absent. Reads share one SQLite snapshot, including a membership recheck. A
    foreign project's operation is indistinguishable from an unknown request.
    """
    project = product.store.get_project(actor, project_id)
    if (
        not isinstance(actor, str) or not 1 <= len(actor) <= 256
        or not isinstance(project_id, str) or _IDENTIFIER.fullmatch(project_id) is None
        or not isinstance(operation, str) or operation not in _RESULT_KINDS
        or not isinstance(request_key, str) or _REQUEST_KEY.fullmatch(request_key) is None
        or not isinstance(target_id, str) or _IDENTIFIER.fullmatch(target_id) is None
    ):
        raise LearningError("LEARNING_OPERATION_INPUT_INVALID")
    response = {
        "schema_version": "visiondata-gate.learning-operation.v1",
        "project_id": project_id,
        "operation": operation,
        "request_key": request_key,
        "target_id": target_id,
        "lookup_status": "NOT_FOUND",
        "request_sha256": None,
        "request_digest_semantics": "SERVER_CANONICAL_VALIDATED_REQUEST",
        "request_digest_verification": "NOT_AVAILABLE",
        "result_semantics": "CURRENT_RESULT",
        "result_kind": None,
        "result_id": None,
        "result_receipt_sha256": None,
        "current_result": None,
        "execution_status": "UNKNOWN_NOT_PROOF_OF_NO_WRITE",
        "automatic_retry_allowed": False,
    }
    with product.store._connection() as connection:
        connection.execute("BEGIN")
        product.store._require_membership(connection, project.workspace_id, actor)
        tables = {
            row[0] for row in connection.execute(
                "SELECT name FROM sqlite_master WHERE type='table' AND name IN ('learning_requests','learning_records')"
            ).fetchall()
        }
        if not tables:
            return _seal(response)
        if tables != {"learning_requests", "learning_records"}:
            raise LearningError("LEARNING_OPERATION_STORAGE_INTEGRITY_HOLD")
        row = connection.execute(
            """SELECT requests.request_sha, requests.result_id, records.kind
               FROM learning_requests AS requests
               JOIN learning_records AS records ON records.id=requests.result_id
               WHERE requests.scope=? AND requests.operation=? AND requests.actor=?
                 AND requests.request_key=? AND records.project_id=?""",
            (target_id, operation, actor, request_key, project_id),
        ).fetchone()
        if row is None:
            return _seal(response)
        kind = _RESULT_KINDS[operation]
        if row["kind"] != kind:
            raise LearningError("LEARNING_OPERATION_RESULT_INTEGRITY_HOLD")
        result = LearningService._read(connection, row["result_id"], kind)
        _validate_result_scope(connection, operation, target_id, result, project_id)
        digest_verification = _validate_request_digest(operation, request_key, row["request_sha"], result)
        response.update(
            lookup_status="FOUND",
            request_sha256=row["request_sha"],
            request_digest_verification=digest_verification,
            result_kind=kind,
            result_id=row["result_id"],
            result_receipt_sha256=result["receipt_sha256"],
            current_result=result,
            execution_status="PENDING" if result.get("status") in {"RUNNING", "FINALIZING"} else "RESULT_AVAILABLE",
        )
        return _seal(response)
