"""Governed local learning lifecycle. No scheduler, remote model or device writes.

Numerical execution, frozen data and evaluation live in separate modules. SQLite
transactions reserve bounded work; training runs outside the transaction. Model
selection is human-only and sandbox-only. Final test consumption closes a cycle.
"""

from __future__ import annotations

from contextlib import contextmanager
from datetime import UTC, datetime
import hashlib
import hmac
import json
import os
from pathlib import Path
import re
import time
from uuid import uuid4

from .audit_envelope import canonical_jcs_bytes
from .compute_handoff import compute_preflight
from .continual_learning import (
    ContinualRetentionEvaluationRequest,
    evaluate_continual_retention,
)
from .execution_recovery import task_execution_lock
from .learning_contracts import (
    CreateLearningCycle,
    CycleAction,
    FeedbackReview,
    FeedbackFollowup,
    ModelSelection,
    NormalMaskAttestation,
    RollbackModel,
    RunLearningRound,
)
from .learning_dataset import freeze_dataset, load_dataset
from .learning_engine import TrainingConfig, initial_model, train_model
from .learning_evaluation import EvaluationPolicy, evaluate_models
from .task_store import NotFoundError, ProductStoreError


class LearningError(ProductStoreError):
    code = "learning_hold"


def _sha(value) -> str:
    return hashlib.sha256(canonical_jcs_bytes(value)).hexdigest()


def _seal(value: dict) -> dict:
    stable = {key: item for key, item in value.items() if key != "receipt_sha256"}
    return stable | {"receipt_sha256": _sha(stable)}


def _now() -> str:
    return datetime.now(UTC).isoformat(timespec="milliseconds")


def _id(prefix: str) -> str:
    return prefix + "_" + uuid4().hex[:24]


class LearningService:
    def __init__(self, product):
        self.product = product
        self.root = product.product_root / "learning"
        if self.root.exists() and (self.root.is_symlink() or self.root.is_junction()):
            raise LearningError("LEARNING_ROOT_LINK_FORBIDDEN")
        self.root.mkdir(exist_ok=True)
        with self.product.store._connection(immediate=True) as connection:
            connection.execute("""CREATE TABLE IF NOT EXISTS learning_records (
                id TEXT PRIMARY KEY, kind TEXT NOT NULL, cycle_id TEXT NOT NULL,
                project_id TEXT NOT NULL, record_json TEXT NOT NULL)""")
            connection.execute("""CREATE TABLE IF NOT EXISTS learning_requests (
                scope TEXT NOT NULL, operation TEXT NOT NULL, actor TEXT NOT NULL,
                request_key TEXT NOT NULL, request_sha TEXT NOT NULL, result_id TEXT NOT NULL,
                PRIMARY KEY(scope,operation,actor,request_key))""")
            connection.execute("""CREATE TABLE IF NOT EXISTS learning_holdouts (
                project_id TEXT NOT NULL, kind TEXT NOT NULL, value TEXT NOT NULL,
                PRIMARY KEY(project_id,kind,value))""")
            connection.execute("""CREATE TABLE IF NOT EXISTS learning_consumed_tests (
                project_id TEXT NOT NULL, kind TEXT NOT NULL, value TEXT NOT NULL,
                cycle_id TEXT NOT NULL, PRIMARY KEY(project_id,kind,value))""")
            connection.execute("""CREATE TABLE IF NOT EXISTS learning_execution_owners (
                cycle_id TEXT PRIMARY KEY, owner_json TEXT NOT NULL)""")

    @contextmanager
    def _execution_lock(self, cycle_id):
        """The same OS lock covers reservation, execution, publication and recovery."""
        with task_execution_lock(
            self.product.product_root, "learning:" + cycle_id
        ) as acquired:
            if not acquired:
                raise LearningError("EXECUTION_OWNER_ACTIVE")
            yield

    @staticmethod
    def _record_execution_owner(connection, cycle, operation, run_id=None):
        # Kept outside public cycle/run DTOs so strict clients remain compatible.
        owner = _seal(
            {
                "schema_version": "visiondata-gate.learning-execution-owner.v1",
                "cycle_id": cycle["cycle_id"],
                "project_id": cycle["project_id"],
                "workspace_id": cycle["workspace_id"],
                "operation": operation,
                "run_id": run_id,
                "execution_id": _id("execution"),
                "process_id": os.getpid(),
                "started_at": _now(),
            }
        )
        connection.execute(
            "INSERT OR REPLACE INTO learning_execution_owners VALUES (?,?)",
            (cycle["cycle_id"], json.dumps(owner)),
        )

    @staticmethod
    def _require_execution_owner(connection, cycle):
        """A free lock is not proof that an unregistered legacy executor stopped."""
        row = connection.execute(
            "SELECT owner_json FROM learning_execution_owners WHERE cycle_id=?",
            (cycle["cycle_id"],),
        ).fetchone()
        if row is None:
            raise LearningError("EXECUTION_OWNERSHIP_UNKNOWN")
        try:
            owner = json.loads(row["owner_json"])
            training = cycle["status"] == "RUNNING"
            if not (
                hmac.compare_digest(owner["receipt_sha256"], _seal(owner)["receipt_sha256"])
                and owner["schema_version"] == "visiondata-gate.learning-execution-owner.v1"
                and owner["cycle_id"] == cycle["cycle_id"]
                and owner["project_id"] == cycle["project_id"]
                and owner["workspace_id"] == cycle["workspace_id"]
                and owner["operation"] == ("train" if training else "finalize")
                and owner["run_id"] == (cycle["round_ids"][-1] if training else None)
            ):
                raise ValueError("execution owner binding")
        except (ValueError, TypeError, KeyError, IndexError) as error:
            raise LearningError("EXECUTION_OWNERSHIP_INVALID") from error

    def _path(self, *parts: str) -> Path:
        if self.root.is_symlink() or self.root.is_junction():
            raise LearningError("LEARNING_ROOT_LINK_FORBIDDEN")
        if any(
            not re.fullmatch(r"[A-Za-z0-9_.-]{1,150}", part) or part in {".", ".."}
            for part in parts
        ):
            raise LearningError("ARTIFACT_PATH_FORBIDDEN")
        result = self.root
        for part in parts:
            result = result / part
            if result.exists() and (result.is_symlink() or result.is_junction()):
                raise LearningError("ARTIFACT_LINK_FORBIDDEN")
        if not result.resolve().is_relative_to(self.root.resolve()):
            raise LearningError("ARTIFACT_PATH_FORBIDDEN")
        return result

    def _bound_dataset(self, cycle_id, storage_key, expected):
        dataset, samples = load_dataset(self._path(cycle_id, storage_key))
        # A self-consistent replacement is not the dataset that was authorized.
        if (
            dataset["receipt_sha256"] != expected["receipt_sha256"]
            or dataset["dataset_id"] != expected["dataset_id"]
            or dataset["binding"] != expected["binding"]
        ):
            raise LearningError("APPROVED_DATASET_BINDING_CHANGED")
        return dataset, samples

    @staticmethod
    def _read(connection, identifier: str, kind: str | None = None) -> dict:
        row = connection.execute(
            "SELECT * FROM learning_records WHERE id=?", (identifier,)
        ).fetchone()
        if row is None or (kind and row["kind"] != kind):
            raise NotFoundError("learning record not found")
        try:
            record = json.loads(row["record_json"])
            if (
                not hmac.compare_digest(
                    record["receipt_sha256"], _seal(record)["receipt_sha256"]
                )
                or record["project_id"] != row["project_id"]
                or record["cycle_id"] != row["cycle_id"]
            ):
                raise ValueError("binding")
            if record.get(f"{row['kind']}_id") != identifier:
                raise ValueError("identity")
            return record
        except (ValueError, KeyError, TypeError) as error:
            raise LearningError("LEARNING_RECORD_INTEGRITY_HOLD") from error

    @staticmethod
    def _put(connection, kind: str, record: dict, *, replace=False) -> dict:
        record = _seal(record)
        identifier = record[f"{kind}_id"]
        if replace:
            connection.execute(
                "UPDATE learning_records SET record_json=? WHERE id=?",
                (json.dumps(record), identifier),
            )
        else:
            connection.execute(
                "INSERT INTO learning_records VALUES (?,?,?,?,?)",
                (
                    identifier,
                    kind,
                    record["cycle_id"],
                    record["project_id"],
                    json.dumps(record),
                ),
            )
        return record

    def _owned(self, actor: str, identifier: str, kind: str) -> dict:
        with self.product.store._connection() as connection:
            record = self._read(connection, identifier, kind)
        self.product.store.get_project(actor, record["project_id"])
        return record

    def _authorize_transaction(self, connection, actor: str, cycle: dict) -> None:
        self.product.store._require_membership(connection, cycle["workspace_id"], actor)

    @staticmethod
    def _replay(connection, scope, operation, actor, request):
        row = connection.execute(
            "SELECT * FROM learning_requests WHERE scope=? AND operation=? AND actor=? AND request_key=?",
            (scope, operation, actor, request.request_key),
        ).fetchone()
        if row:
            if row["request_sha"] != _sha(request.model_dump(mode="json")):
                raise LearningError("IDEMPOTENCY_CONFLICT")
            return LearningService._read(connection, row["result_id"])
        return None

    @staticmethod
    def _remember(connection, scope, operation, actor, request, result_id):
        connection.execute(
            "INSERT INTO learning_requests VALUES (?,?,?,?,?,?)",
            (
                scope,
                operation,
                actor,
                request.request_key,
                _sha(request.model_dump(mode="json")),
                result_id,
            ),
        )

    @staticmethod
    def _check_cycle(cycle, expected, *, allow_running=False):
        if not hmac.compare_digest(cycle["receipt_sha256"], expected):
            raise LearningError("STALE_CYCLE")
        if cycle["status"] in {
            "FINALIZED",
            "FINALIZING",
            "HOLD_REQUIRES_NEW_PROTOCOL",
            "STOPPED",
        }:
            raise LearningError("CYCLE_CLOSED")
        if cycle["status"] == "RUNNING" and not allow_running:
            raise LearningError("CYCLE_BUSY")

    def _update_cycle(self, connection, cycle, event, actor):
        cycle = dict(cycle)
        cycle["revision"] += 1
        cycle["updated_at"] = _now()
        cycle["events"] = [
            *cycle["events"],
            {"event": event, "actor": actor, "at": cycle["updated_at"]},
        ]
        return self._put(connection, "cycle", cycle, replace=True)

    def _fresh_input(self, actor, task_id, expected):
        preflight = compute_preflight(self.product, actor, task_id)
        if preflight["eligibility"] != "READY_FOR_OFFLINE_HANDOFF":
            raise LearningError("INPUT_GATE_HOLD:" + ",".join(preflight["blockers"]))
        if not hmac.compare_digest(preflight["receipt_sha256"], expected):
            raise LearningError("STALE_PREFLIGHT")
        _, root, manifest, _, _ = self.product._annotation_context(actor, task_id)
        return preflight, root, manifest

    def _normal_authority(self, actor, task_id, manifest, declarations):
        if not declarations:
            return {}
        snapshot = self.product._operator_snapshot_visual_context(actor, task_id)[2]
        identities = {item.asset_id: item for item in snapshot.assets}
        samples = {item.sample_id: item for item in manifest.samples}
        normalized = {}
        for identifier, raw in declarations.items():
            declaration = NormalMaskAttestation.model_validate(
                raw.model_dump(mode="json")
                if isinstance(raw, NormalMaskAttestation)
                else raw
            )
            asset = identities.get(identifier)
            sample = samples.get(identifier)
            if (
                asset is None
                or sample is None
                or asset.annotation_count != 0
                or asset.mask_relative_path is not None
                or sample.annotation_path is not None
            ):
                raise LearningError("NORMAL_MASK_DECLARATION_CONFLICT")
            if (
                declaration.expected_asset_sha256 != asset.source_sha256
                or declaration.expected_annotation_revision != asset.annotation_revision
                or declaration.expected_annotation_sha256
                != asset.annotation_document_sha256
            ):
                raise LearningError("NORMAL_MASK_ATTESTATION_STALE")
            normalized[identifier] = declaration.model_dump(mode="json")
        return normalized

    def _still_fresh(self, actor, binding):
        current = compute_preflight(self.product, actor, binding["task_id"])
        if (
            current["eligibility"] != "READY_FOR_OFFLINE_HANDOFF"
            or current["binding"] != binding
        ):
            raise LearningError("SOURCE_OR_GATE_CHANGED")

    @staticmethod
    def _source_row_fresh(connection, binding):
        row = connection.execute(
            "SELECT status,authorization_valid_until FROM local_source_authorizations WHERE source_id=? AND workspace_id=?",
            (binding["source_id"], binding["workspace_id"]),
        ).fetchone()
        if row is None or row["status"] != "active":
            raise LearningError("SOURCE_AUTHORIZATION_INACTIVE")
        if row["authorization_valid_until"] and datetime.fromisoformat(
            row["authorization_valid_until"].replace("Z", "+00:00")
        ) <= datetime.now(UTC):
            raise LearningError("SOURCE_AUTHORIZATION_INACTIVE")

    @staticmethod
    def _protect_holdouts(connection, project_id, dataset):
        for sample in dataset["samples"]:
            for kind, value in (
                ("pixel", sample["pixel_sha256"]),
                ("group", sample["group_id"]),
            ):
                if connection.execute(
                    "SELECT 1 FROM learning_consumed_tests WHERE project_id=? AND kind=? AND value=?",
                    (project_id, kind, value),
                ).fetchone():
                    raise LearningError("FINAL_TEST_ALREADY_CONSUMED")
            if sample["split"] == "train":
                for kind, value in (
                    ("pixel", sample["pixel_sha256"]),
                    ("group", sample["group_id"]),
                ):
                    if connection.execute(
                        "SELECT 1 FROM learning_holdouts WHERE project_id=? AND kind=? AND value=?",
                        (project_id, kind, value),
                    ).fetchone():
                        raise LearningError("PREVIOUS_HOLDOUT_CANNOT_ENTER_TRAINING")
        for sample in dataset["samples"]:
            if sample["split"] in {"val", "test"}:
                for kind, value in (
                    ("pixel", sample["pixel_sha256"]),
                    ("group", sample["group_id"]),
                ):
                    connection.execute(
                        "INSERT OR IGNORE INTO learning_holdouts VALUES (?,?,?)",
                        (project_id, kind, value),
                    )

    def _write_model(self, cycle_id, model_id, model):
        path = self._path(cycle_id, model_id + ".json")
        payload = canonical_jcs_bytes(model)
        with path.open("xb") as stream:
            stream.write(payload)
            stream.flush()
            os.fsync(stream.fileno())
        return hashlib.sha256(payload).hexdigest()

    def _model(self, actor, model_id):
        record = self._owned(actor, model_id, "model")
        try:
            payload = self._path(record["cycle_id"], model_id + ".json").read_bytes()
            if hashlib.sha256(payload).hexdigest() != record["model_sha256"]:
                raise ValueError("digest")
            return record, json.loads(payload)
        except (OSError, ValueError) as error:
            raise LearningError("MODEL_ARTIFACT_INTEGRITY_HOLD") from error

    def create_cycle(
        self, actor: str, task_id: str, request: CreateLearningCycle
    ) -> dict:
        task = self.product.store.get_task(actor, task_id)
        with self.product.store._connection() as connection:
            replay = self._replay(connection, task_id, "create", actor, request)
            if replay:
                return replay
        preflight, source, manifest = self._fresh_input(
            actor, task_id, request.expected_preflight_sha256
        )
        normal_attestations = self._normal_authority(
            actor, task_id, manifest, request.normal_mask_attestations
        )
        cycle_id = _id("cycle")
        self._path(cycle_id).mkdir()
        storage_key = _id("dataset")
        dataset = freeze_dataset(
            source,
            manifest,
            preflight["binding"],
            request.groups,
            self._path(cycle_id, storage_key),
            normal_attestations=normal_attestations,
        )
        self._still_fresh(actor, preflight["binding"])
        baseline_id = _id("model")
        baseline = initial_model()
        baseline_sha = self._write_model(cycle_id, baseline_id, baseline)
        cycle = {
            "schema_version": "visiondata-gate.learning-cycle.v1",
            "cycle_id": cycle_id,
            "project_id": task.project_id,
            "workspace_id": task.workspace_id,
            "created_by": actor,
            "created_at": _now(),
            "updated_at": _now(),
            "revision": 0,
            "status": "READY",
            "request": request.model_dump(mode="json"),
            "dataset": dataset,
            "dataset_storage_key": storage_key,
            "evaluation_fingerprints": {
                key: dataset["split_fingerprints"][key] for key in ("val", "test")
            },
            "initial_model_id": baseline_id,
            "champion_model_id": baseline_id,
            "approved_model_ids": [baseline_id],
            "round_ids": [],
            "epochs_reserved": 0,
            "wall_seconds_reserved": 0.0,
            "events": [],
            "production_release_allowed": False,
            "machine_write_permitted": False,
            "remote_execution_verified": False,
            "scope": "LOCAL_SUPERVISED_REFERENCE_MODEL_SANDBOX",
        }
        with self.product.store._connection(immediate=True) as connection:
            self._authorize_transaction(connection, actor, cycle)
            replay = self._replay(connection, task_id, "create", actor, request)
            if replay:
                return replay
            self._source_row_fresh(connection, preflight["binding"])
            self._protect_holdouts(connection, task.project_id, dataset)
            self._put(
                connection,
                "model",
                {
                    "model_id": baseline_id,
                    "cycle_id": cycle_id,
                    "project_id": task.project_id,
                    "model_sha256": baseline_sha,
                    "parent_model_id": None,
                    "dataset_id": None,
                    "run_id": None,
                    "kind": "UNTRAINED_INITIAL_BASELINE",
                    "production_release_allowed": False,
                },
            )
            cycle = self._put(connection, "cycle", cycle)
            self._remember(connection, task_id, "create", actor, request, cycle_id)
            return cycle

    def get_cycle(self, actor, cycle_id):
        return self._owned(actor, cycle_id, "cycle")

    def get_run(self, actor, run_id):
        return self._owned(actor, run_id, "run")

    def get_model(self, actor, model_id):
        record, model = self._model(actor, model_id)
        return _seal(record | {"weights": model})

    def list_cycles(self, actor, project_id):
        self.product.store.get_project(actor, project_id)
        with self.product.store._connection() as connection:
            ids = connection.execute(
                "SELECT id FROM learning_records WHERE kind='cycle' AND project_id=? ORDER BY id",
                (project_id,),
            ).fetchall()
            return [self._read(connection, row["id"], "cycle") for row in ids]

    def _read_continual_retention(self, project_id: str, receipt_sha256: str) -> dict:
        if re.fullmatch(r"[0-9a-f]{64}", receipt_sha256) is None:
            raise NotFoundError("continual retention receipt not found")
        path = self._path("continual-retention", receipt_sha256 + ".json")
        try:
            receipt = json.loads(path.read_bytes())
            if (
                receipt.get("project_id") != project_id
                or not hmac.compare_digest(
                    receipt.get("receipt_sha256", ""),
                    _seal(receipt)["receipt_sha256"],
                )
                or not hmac.compare_digest(
                    receipt["receipt_sha256"], receipt_sha256
                )
            ):
                raise ValueError("receipt binding")
            return receipt
        except FileNotFoundError as error:
            raise NotFoundError("continual retention receipt not found") from error
        except (OSError, ValueError, TypeError, KeyError, json.JSONDecodeError) as error:
            raise LearningError("CONTINUAL_RETENTION_INTEGRITY_HOLD") from error

    def evaluate_continual_retention(
        self,
        actor: str,
        project_id: str,
        request: ContinualRetentionEvaluationRequest,
    ) -> dict:
        self.product.store.get_project(actor, project_id)
        parent_record, _ = self._model(actor, request.parent_model_id)
        candidate_record, _ = self._model(actor, request.candidate_model_id)
        if (
            parent_record["project_id"] != project_id
            or candidate_record["project_id"] != project_id
            or candidate_record.get("parent_model_id") != request.parent_model_id
            or not hmac.compare_digest(
                parent_record["model_sha256"], request.parent_model_sha256
            )
            or not hmac.compare_digest(
                candidate_record["model_sha256"], request.candidate_model_sha256
            )
        ):
            raise LearningError("CONTINUAL_RETENTION_MODEL_BINDING_HOLD")

        receipt = evaluate_continual_retention(
            project_id=project_id,
            evaluated_by=actor,
            request=request,
        )
        directory = self._path("continual-retention")
        if directory.exists() and (
            directory.is_symlink() or directory.is_junction()
        ):
            raise LearningError("ARTIFACT_LINK_FORBIDDEN")
        directory.mkdir(exist_ok=True)
        path = self._path(
            "continual-retention", receipt["receipt_sha256"] + ".json"
        )
        payload = canonical_jcs_bytes(receipt)
        try:
            with path.open("xb") as stream:
                stream.write(payload)
                stream.flush()
                os.fsync(stream.fileno())
        except FileExistsError:
            try:
                if not hmac.compare_digest(path.read_bytes(), payload):
                    raise LearningError("CONTINUAL_RETENTION_IMMUTABILITY_HOLD")
            except OSError as error:
                raise LearningError("CONTINUAL_RETENTION_INTEGRITY_HOLD") from error
        return self._read_continual_retention(project_id, receipt["receipt_sha256"])

    def get_continual_retention(
        self, actor: str, project_id: str, receipt_sha256: str
    ) -> dict:
        self.product.store.get_project(actor, project_id)
        return self._read_continual_retention(project_id, receipt_sha256)

    def run_round(self, actor, cycle_id, request: RunLearningRound):
        self.get_cycle(actor, cycle_id)
        with self.product.store._connection() as connection:
            replay = self._replay(connection, cycle_id, "train", actor, request)
            if replay:
                return replay
        with self._execution_lock(cycle_id):
            return self._run_round_owned(actor, cycle_id, request)

    def _run_round_owned(self, actor, cycle_id, request: RunLearningRound):
        cycle = self.get_cycle(actor, cycle_id)
        with self.product.store._connection() as connection:
            replay = self._replay(connection, cycle_id, "train", actor, request)
            if replay:
                return replay
        self._check_cycle(cycle, request.expected_cycle_sha256)
        if cycle["status"] not in {"READY", "AWAITING_DATA"}:
            raise LearningError("REVIEW_PREVIOUS_ROUND_FIRST")
        cfg = TrainingConfig.model_validate(cycle["request"]["training"])
        if (
            len(cycle["round_ids"]) >= cycle["request"]["max_rounds"]
            or cycle["epochs_reserved"] + cfg.epochs
            > cycle["request"]["max_total_epochs"]
            or cycle["wall_seconds_reserved"] + cfg.max_wall_seconds
            > cycle["request"]["max_total_wall_seconds"]
        ):
            raise LearningError("CYCLE_BUDGET_EXHAUSTED")
        preflight, source, manifest = self._fresh_input(
            actor, request.task_id, request.expected_preflight_sha256
        )
        normal_attestations = self._normal_authority(
            actor, request.task_id, manifest, request.normal_mask_attestations
        )
        if preflight["project_id"] != cycle["project_id"]:
            raise LearningError("CROSS_PROJECT_INPUT_FORBIDDEN")
        previous = (
            self.get_run(actor, cycle["round_ids"][-1]) if cycle["round_ids"] else None
        )
        retry = bool(
            previous
            and previous["status"] in {"FAILED", "CANCELLED", "INTERRUPTED"}
            and preflight["binding"] == cycle["dataset"]["binding"]
            and request.groups == previous["approval"]["groups"]
        )
        if not cycle["round_ids"] or retry:
            if preflight["binding"] != cycle["dataset"][
                "binding"
            ] or request.groups != (
                previous["approval"]["groups"] if retry else cycle["request"]["groups"]
            ):
                raise LearningError("INITIAL_DATASET_BINDING_CHANGED")
            dataset, samples = self._bound_dataset(
                cycle_id, cycle["dataset_storage_key"], cycle["dataset"]
            )
            if normal_attestations != dataset.get("normal_mask_attestations", {}):
                raise LearningError("NORMAL_MASK_AUTHORITY_CHANGED")
            storage_key = cycle["dataset_storage_key"]
        else:
            storage_key = _id("dataset")
            dataset = freeze_dataset(
                source,
                manifest,
                preflight["binding"],
                request.groups,
                self._path(cycle_id, storage_key),
                normal_attestations=normal_attestations,
            )
            dataset, samples = self._bound_dataset(cycle_id, storage_key, dataset)
            if any(
                dataset["split_fingerprints"][key]
                != cycle["evaluation_fingerprints"][key]
                for key in ("val", "test")
            ):
                raise LearningError("FROZEN_EVALUATION_CHANGED")
            if (
                dataset["split_fingerprints"]["train"]
                == cycle["dataset"]["split_fingerprints"]["train"]
            ):
                raise LearningError("NEW_ROUND_REQUIRES_NEW_TRAINING_DATA")
        baseline_record, baseline = self._model(actor, cycle["champion_model_id"])
        feedback_ids = request.responds_to_feedback_ids
        if retry:
            if feedback_ids != previous["approval"].get("responds_to_feedback_ids", []):
                raise LearningError("RETRY_FEEDBACK_BINDING_CHANGED")
        elif feedback_ids:
            references = (
                {item["feedback_id"]: item for item in previous["feedback"]}
                if previous
                else {}
            )
            training_ids = {
                sample.sample_id for sample in samples if sample.split == "train"
            }
            for identifier in feedback_ids:
                item = references.get(identifier)
                followup = item.get("followup", {}) if item else {}
                if (
                    not item
                    or item["status"] == "PENDING_HUMAN_REVIEW"
                    or followup.get("binding") != preflight["binding"]
                    or not set(followup.get("sample_ids", [])).intersection(
                        training_ids
                    )
                ):
                    raise LearningError("FEEDBACK_ASSOCIATION_NOT_VERIFIED")
        self._still_fresh(actor, preflight["binding"])
        run_id = _id("run")
        run = {
            "schema_version": "visiondata-gate.learning-run.v1",
            "run_id": run_id,
            "cycle_id": cycle_id,
            "project_id": cycle["project_id"],
            "round_number": len(cycle["round_ids"]) + 1,
            "retry_of_run_id": previous["run_id"] if retry else None,
            "previous_run_id": previous["run_id"] if previous else None,
            "feedback_parent_run_id": (
                previous.get("feedback_parent_run_id") if retry else previous["run_id"]
            )
            if previous
            else None,
            "responds_to_feedback_ids": feedback_ids,
            "feedback_response_boundary": "New data is bound to prior feedback; this is not automatic verification that each issue was fixed.",
            "status": "RUNNING",
            "dataset_id": dataset["dataset_id"],
            "dataset_receipt_sha256": dataset["receipt_sha256"],
            "dataset_storage_key": storage_key,
            "binding": preflight["binding"],
            "initial_model_id": baseline_record["model_id"],
            "initial_model_sha256": baseline_record["model_sha256"],
            "configuration": cfg.model_dump(mode="json"),
            "approval": request.model_dump(mode="json"),
            "approved_by": actor,
            "started_at": _now(),
            "feedback": [],
            "selection": None,
            "cancel_requested": False,
            "production_release_allowed": False,
            "remote_execution_verified": False,
        }
        with self.product.store._connection(immediate=True) as connection:
            current = self._read(connection, cycle_id, "cycle")
            self._authorize_transaction(connection, actor, current)
            replay = self._replay(connection, cycle_id, "train", actor, request)
            if replay:
                return replay
            self._check_cycle(current, request.expected_cycle_sha256)
            self._source_row_fresh(connection, preflight["binding"])
            self._protect_holdouts(connection, cycle["project_id"], dataset)
            self._record_execution_owner(connection, current, "train", run_id)
            run = self._put(connection, "run", run)
            current.update(
                status="RUNNING",
                dataset=dataset,
                dataset_storage_key=storage_key,
                round_ids=[*current["round_ids"], run_id],
                epochs_reserved=current["epochs_reserved"] + cfg.epochs,
                wall_seconds_reserved=current["wall_seconds_reserved"]
                + cfg.max_wall_seconds,
            )
            self._update_cycle(connection, current, "ROUND_RESERVED", actor)
            self._remember(connection, cycle_id, "train", actor, request, run_id)
        started = time.perf_counter()
        try:
            result = train_model(
                [sample for sample in samples if sample.split == "train"],
                cfg,
                baseline,
                should_cancel=lambda: self.get_run(actor, run_id)["cancel_requested"],
            )
            evaluation = evaluate_models(
                result["model"],
                baseline,
                [s for s in samples if s.split == "val"],
                EvaluationPolicy.model_validate(cycle["request"]["evaluation"]),
            )
            if time.perf_counter() - started > cfg.max_wall_seconds:
                raise LearningError("ROUND_BUDGET_EXCEEDED")
            if (
                result["training"]["initial_model_sha256"]
                != baseline_record["model_sha256"]
            ):
                raise LearningError("TRAINER_BASELINE_BINDING_CHANGED")
            # Check actual frozen copies AND original authorization after execution.
            self._bound_dataset(cycle_id, storage_key, dataset)
            self._model(actor, baseline_record["model_id"])
            self._still_fresh(actor, preflight["binding"])
            model_id = _id("model")
            model_sha = self._write_model(cycle_id, model_id, result["model"])
            feedback = []
            for sample in evaluation["sample_results"]:
                if sample["error_candidate"]:
                    feedback.append(
                        {
                            "feedback_id": _id("feedback"),
                            "status": "PENDING_HUMAN_REVIEW",
                            "evidence": sample,
                            "classification": None,
                            "next_action": "INVESTIGATE",
                            "training_ingestion_allowed": False,
                            "followup_task_id": None,
                        }
                    )
            run.update(
                status="COMPLETED",
                completed_at=_now(),
                training=result["training"],
                model_id=model_id,
                model_sha256=model_sha,
                evaluation=evaluation,
                feedback=feedback,
                evaluation_sha256=_sha(evaluation),
                elapsed_seconds=time.perf_counter() - started,
            )
            with self.product.store._connection(immediate=True) as connection:
                stored = self._read(connection, run_id, "run")
                current = self._read(connection, cycle_id, "cycle")
                self._authorize_transaction(connection, actor, current)
                if (
                    stored["status"] != "RUNNING"
                    or stored["cancel_requested"]
                    or current["status"] != "RUNNING"
                ):
                    raise LearningError("EXECUTION_AUTHORITY_CHANGED")
                self._source_row_fresh(connection, preflight["binding"])
                self._put(
                    connection,
                    "model",
                    {
                        "model_id": model_id,
                        "cycle_id": cycle_id,
                        "project_id": cycle["project_id"],
                        "model_sha256": model_sha,
                        "parent_model_id": baseline_record["model_id"],
                        "run_id": run_id,
                        "dataset_id": dataset["dataset_id"],
                        "dataset_receipt_sha256": dataset["receipt_sha256"],
                        "training_config_sha256": _sha(cfg.model_dump(mode="json")),
                        "kind": "TRAINED_CANDIDATE",
                        "production_release_allowed": False,
                    },
                )
                run = self._put(connection, "run", run, replace=True)
                current["status"] = "AWAITING_REVIEW"
                self._update_cycle(
                    connection, current, "ROUND_EVALUATED_NOT_SELECTED", actor
                )
                return run
        except Exception as error:
            with self.product.store._connection(immediate=True) as connection:
                stored = self._read(connection, run_id, "run")
                current = self._read(connection, cycle_id, "cycle")
                if stored["status"] == "RUNNING":
                    # Do not publish exception strings: filesystem paths may be private.
                    stored.update(
                        status="CANCELLED" if stored["cancel_requested"] else "FAILED",
                        failure_code="LOCAL_EXECUTION_FAILED",
                        failure_type=type(error).__name__,
                        completed_at=_now(),
                        elapsed_seconds=time.perf_counter() - started,
                    )
                    stored = self._put(connection, "run", stored, replace=True)
                    current["status"] = "AWAITING_DATA"
                    self._update_cycle(
                        connection, current, "ROUND_FAILED_NO_MODEL_SELECTED", actor
                    )
                return stored

    def review_feedback(
        self, actor, cycle_id, run_id, feedback_id, request: FeedbackReview
    ):
        cycle = self.get_cycle(actor, cycle_id)
        run = self.get_run(actor, run_id)
        if run["cycle_id"] != cycle_id:
            raise NotFoundError("learning run not found")
        if request.followup_task_id:
            task = self.product.store.get_task(actor, request.followup_task_id)
            if task.project_id != cycle["project_id"]:
                raise LearningError("CROSS_PROJECT_FOLLOWUP")
        with self.product.store._connection(immediate=True) as connection:
            cycle = self._read(connection, cycle_id, "cycle")
            self._authorize_transaction(connection, actor, cycle)
            replay = self._replay(connection, feedback_id, "feedback", actor, request)
            if replay:
                return replay
            self._check_cycle(cycle, request.expected_cycle_sha256)
            run = self._read(connection, run_id, "run")
            if cycle["status"] != "AWAITING_REVIEW" or cycle["round_ids"][-1] != run_id:
                raise LearningError("NOT_CURRENT_REVIEW")
            item = next(
                (
                    item
                    for item in run["feedback"]
                    if item["feedback_id"] == feedback_id
                ),
                None,
            )
            if item is None:
                raise NotFoundError("feedback not found")
            if item["status"] != "PENDING_HUMAN_REVIEW":
                raise LearningError("FEEDBACK_ALREADY_REVIEWED")
            action = {
                "LABEL_ERROR": "RELABEL_AND_NEW_EVALUATION_PROTOCOL",
                "HARD_SAMPLE": "COLLECT_SIMILAR_TRAINING_EXAMPLES",
                "DISTRIBUTION_SHIFT": "RECAPTURE_REPRESENTATIVE_TRAINING_DATA",
                "INSUFFICIENT_EVIDENCE": "INVESTIGATE",
            }[request.classification]
            item.update(
                status="TRIAGED_NOT_AUTO_INGESTED",
                classification=request.classification,
                next_action=action,
                reviewed_by=actor,
                review_note=request.review_note,
                followup_task_id=request.followup_task_id,
            )
            run = self._put(connection, "run", run, replace=True)
            if request.classification in {"LABEL_ERROR", "INSUFFICIENT_EVIDENCE"}:
                cycle["status"] = "HOLD_REQUIRES_NEW_PROTOCOL"
            self._update_cycle(connection, cycle, "FEEDBACK_TRIAGED", actor)
            self._remember(connection, feedback_id, "feedback", actor, request, run_id)
            return run

    def select_model(self, actor, cycle_id, run_id, request: ModelSelection):
        cycle = self.get_cycle(actor, cycle_id)
        run = self.get_run(actor, run_id)
        if run["cycle_id"] != cycle_id:
            raise NotFoundError("learning run not found")
        if run["status"] != "COMPLETED" or not isinstance(run.get("model_id"), str):
            raise LearningError("NOT_CURRENT_CANDIDATE")
        self._still_fresh(actor, run["binding"])
        candidate_record, _ = self._model(actor, run["model_id"])
        baseline_record, _ = self._model(actor, run["initial_model_id"])
        if baseline_record["model_sha256"] != run["initial_model_sha256"]:
            raise LearningError("CANDIDATE_BASELINE_CHANGED")
        self._bound_dataset(
            cycle_id,
            run["dataset_storage_key"],
            {
                "receipt_sha256": run["dataset_receipt_sha256"],
                "dataset_id": run["dataset_id"],
                "binding": run["binding"],
            },
        )
        continual_receipt = None
        if request.action == "APPROVE_SANDBOX_CONTINUAL":
            continual_receipt = self.get_continual_retention(
                actor,
                cycle["project_id"],
                request.expected_continual_retention_receipt_sha256 or "",
            )
            if (
                continual_receipt["parent_model_id"] != run["initial_model_id"]
                or continual_receipt["candidate_model_id"] != run["model_id"]
                or not hmac.compare_digest(
                    continual_receipt["parent_model_sha256"],
                    baseline_record["model_sha256"],
                )
                or not hmac.compare_digest(
                    continual_receipt["candidate_model_sha256"],
                    candidate_record["model_sha256"],
                )
                or continual_receipt["decision"]
                != "ELIGIBLE_FOR_SANDBOX_REVIEW"
                or continual_receipt["sandbox_promotion_eligible"] is not True
                or continual_receipt["production_release_allowed"] is not False
            ):
                raise LearningError("CONTINUAL_RETENTION_HOLD")
        with self.product.store._connection(immediate=True) as connection:
            cycle = self._read(connection, cycle_id, "cycle")
            self._authorize_transaction(connection, actor, cycle)
            replay = self._replay(connection, run_id, "select", actor, request)
            if replay:
                return replay
            self._check_cycle(cycle, request.expected_cycle_sha256)
            run = self._read(connection, run_id, "run")
            if run["receipt_sha256"] != request.expected_run_sha256:
                raise LearningError("STALE_RUN")
            if (
                cycle["status"] != "AWAITING_REVIEW"
                or cycle["round_ids"][-1] != run_id
                or run["status"] != "COMPLETED"
            ):
                raise LearningError("NOT_CURRENT_CANDIDATE")
            if run["initial_model_id"] != cycle["champion_model_id"]:
                raise LearningError("CANDIDATE_BASELINE_CHANGED")
            if any(
                item["status"] == "PENDING_HUMAN_REVIEW" for item in run["feedback"]
            ):
                raise LearningError("FEEDBACK_REVIEW_REQUIRED")
            self._source_row_fresh(connection, run["binding"])
            if request.action in {
                "APPROVE_SANDBOX",
                "APPROVE_SANDBOX_CONTINUAL",
            }:
                if run["evaluation"]["decision"] != "ELIGIBLE":
                    raise LearningError("EVALUATION_HOLD")
                if continual_receipt is not None:
                    current_receipt = self._read_continual_retention(
                        cycle["project_id"], continual_receipt["receipt_sha256"]
                    )
                    if current_receipt != continual_receipt:
                        raise LearningError("CONTINUAL_RETENTION_INTEGRITY_HOLD")
                cycle["champion_model_id"] = run["model_id"]
                cycle["approved_model_ids"] = [
                    *cycle["approved_model_ids"],
                    run["model_id"],
                ]
            selection = {
                "action": request.action,
                "actor": actor,
                "note": request.review_note,
                "evaluation_sha256": run["evaluation_sha256"],
                "at": _now(),
            }
            if continual_receipt is not None:
                selection["continual_retention_receipt_sha256"] = continual_receipt[
                    "receipt_sha256"
                ]
            run["selection"] = selection
            self._put(connection, "run", run, replace=True)
            cycle["status"] = "AWAITING_DATA"
            cycle = self._update_cycle(connection, cycle, request.action, actor)
            self._remember(connection, run_id, "select", actor, request, cycle_id)
            return cycle

    def link_feedback(
        self, actor, cycle_id, run_id, feedback_id, request: FeedbackFollowup
    ):
        cycle = self.get_cycle(actor, cycle_id)
        run = self.get_run(actor, run_id)
        if run["cycle_id"] != cycle_id:
            raise NotFoundError("learning run not found")
        with self.product.store._connection() as connection:
            replay = self._replay(connection, feedback_id, "followup", actor, request)
            if replay:
                return replay
        preflight, _, manifest = self._fresh_input(
            actor, request.task_id, request.expected_preflight_sha256
        )
        if preflight["project_id"] != cycle["project_id"]:
            raise LearningError("CROSS_PROJECT_FOLLOWUP")
        members = {member.sample_id: member for member in manifest.samples}
        if not set(request.sample_ids).issubset(members):
            raise LearningError("FOLLOWUP_MEMBER_UNKNOWN")
        if preflight["binding"]["source_id"] == run["binding"]["source_id"]:
            raise LearningError("FOLLOWUP_REQUIRES_NEW_FROZEN_INPUT")
        snapshot = self.product._operator_snapshot_visual_context(
            actor, request.task_id
        )[2]
        identities = {item.asset_id: item for item in snapshot.assets}
        linked_members = [
            {
                "sample_id": identifier,
                "split": members[identifier].split,
                "image_sha256": identities[identifier].source_sha256,
                "annotation_revision": identities[identifier].annotation_revision,
                "annotation_document_sha256": identities[
                    identifier
                ].annotation_document_sha256,
                "mask_sha256": identities[identifier].mask_sha256,
            }
            for identifier in request.sample_ids
        ]
        with self.product.store._connection(immediate=True) as connection:
            cycle = self._read(connection, cycle_id, "cycle")
            self._authorize_transaction(connection, actor, cycle)
            replay = self._replay(connection, feedback_id, "followup", actor, request)
            if replay:
                return replay
            if cycle["receipt_sha256"] != request.expected_cycle_sha256:
                raise LearningError("STALE_CYCLE")
            if cycle["status"] in {"RUNNING", "FINALIZING"}:
                raise LearningError("CYCLE_BUSY")
            run = self._read(connection, run_id, "run")
            if run["receipt_sha256"] != request.expected_run_sha256:
                raise LearningError("STALE_RUN")
            item = next(
                (
                    item
                    for item in run["feedback"]
                    if item["feedback_id"] == feedback_id
                ),
                None,
            )
            if item is None:
                raise NotFoundError("feedback not found")
            if item["status"] == "PENDING_HUMAN_REVIEW":
                raise LearningError("TRIAGE_FEEDBACK_FIRST")
            self._source_row_fresh(connection, preflight["binding"])
            item["followup_task_id"] = request.task_id
            item["followup_status"] = "NEW_GATE_EVIDENCE_LINKED_NOT_ISSUE_CLOSED"
            item["followup"] = _seal(
                {
                    "binding": preflight["binding"],
                    "preflight_receipt_sha256": preflight["receipt_sha256"],
                    "sample_ids": request.sample_ids,
                    "members": linked_members,
                    "reviewed_by": actor,
                    "review_note": request.review_note,
                    "at": _now(),
                    "issue_closed": False,
                    "training_ingestion_allowed": False,
                    "boundary": "Human-linked new Gate evidence is not proof the model error or label issue was fixed.",
                }
            )
            run = self._put(connection, "run", run, replace=True)
            self._update_cycle(
                connection, cycle, "FEEDBACK_NEW_GATE_EVIDENCE_LINKED", actor
            )
            self._remember(connection, feedback_id, "followup", actor, request, run_id)
            return run

    def rollback(self, actor, cycle_id, request: RollbackModel):
        cycle = self.get_cycle(actor, cycle_id)
        model, _ = self._model(actor, request.model_id)
        if model["cycle_id"] != cycle_id:
            raise LearningError("CROSS_CYCLE_MODEL")
        with self.product.store._connection(immediate=True) as connection:
            cycle = self._read(connection, cycle_id, "cycle")
            self._authorize_transaction(connection, actor, cycle)
            replay = self._replay(connection, cycle_id, "rollback", actor, request)
            if replay:
                return replay
            self._check_cycle(cycle, request.expected_cycle_sha256)
            if cycle["status"] != "AWAITING_DATA":
                raise LearningError("FINISH_CANDIDATE_REVIEW_BEFORE_ROLLBACK")
            if request.model_id not in cycle["approved_model_ids"]:
                raise LearningError("MODEL_NOT_PREVIOUSLY_APPROVED")
            cycle["champion_model_id"] = request.model_id
            cycle = self._update_cycle(
                connection, cycle, "SANDBOX_MODEL_ROLLBACK", actor
            )
            self._remember(connection, cycle_id, "rollback", actor, request, cycle_id)
            return cycle

    def cancel(self, actor, cycle_id, request: CycleAction):
        self.get_cycle(actor, cycle_id)
        with self.product.store._connection(immediate=True) as connection:
            cycle = self._read(connection, cycle_id, "cycle")
            self._authorize_transaction(connection, actor, cycle)
            replay = self._replay(connection, cycle_id, "cancel", actor, request)
            if replay:
                return replay
            self._check_cycle(cycle, request.expected_cycle_sha256, allow_running=True)
            if cycle["status"] == "RUNNING":
                run = self._read(connection, cycle["round_ids"][-1], "run")
                run["cancel_requested"] = True
                self._put(connection, "run", run, replace=True)
            else:
                cycle["status"] = "STOPPED"
            cycle = self._update_cycle(
                connection, cycle, "CANCELLATION_REQUESTED", actor
            )
            self._remember(connection, cycle_id, "cancel", actor, request, cycle_id)
            return cycle

    def recover(self, actor, cycle_id, request: CycleAction):
        """Recover only registered, absent owners; legacy ownership stays on HOLD."""
        self.get_cycle(actor, cycle_id)
        with self.product.store._connection() as connection:
            replay = self._replay(connection, cycle_id, "recover", actor, request)
            if replay:
                return replay
        with self._execution_lock(cycle_id):
            return self._recover_owned(actor, cycle_id, request)

    def _recover_owned(self, actor, cycle_id, request: CycleAction):
        self.get_cycle(actor, cycle_id)
        with self.product.store._connection(immediate=True) as connection:
            cycle = self._read(connection, cycle_id, "cycle")
            self._authorize_transaction(connection, actor, cycle)
            replay = self._replay(connection, cycle_id, "recover", actor, request)
            if replay:
                return replay
            if cycle["receipt_sha256"] != request.expected_cycle_sha256:
                raise LearningError("STALE_CYCLE")
            if cycle["status"] not in {"RUNNING", "FINALIZING"}:
                raise LearningError("NO_INTERRUPTED_WORK")
            self._require_execution_owner(connection, cycle)
            if cycle["status"] == "FINALIZING":
                cycle["status"] = "STOPPED"
            else:
                run = self._read(connection, cycle["round_ids"][-1], "run")
                deadline = (
                    TrainingConfig.model_validate(run["configuration"]).max_wall_seconds
                    + 60
                )
                if (
                    datetime.now(UTC) - datetime.fromisoformat(run["started_at"])
                ).total_seconds() < deadline:
                    raise LearningError("EXECUTION_LEASE_NOT_EXPIRED")
                run.update(
                    status="INTERRUPTED", cancel_requested=True, completed_at=_now()
                )
                self._put(connection, "run", run, replace=True)
                cycle["status"] = "AWAITING_DATA"
            cycle = self._update_cycle(
                connection, cycle, "INTERRUPTED_WORK_NOT_REPLAYED", actor
            )
            self._remember(connection, cycle_id, "recover", actor, request, cycle_id)
            return cycle

    def finalize(self, actor, cycle_id, request: CycleAction):
        self.get_cycle(actor, cycle_id)
        with self.product.store._connection() as connection:
            replay = self._replay(connection, cycle_id, "finalize", actor, request)
            if replay:
                return replay
        with self._execution_lock(cycle_id):
            return self._finalize_owned(actor, cycle_id, request)

    def _finalize_owned(self, actor, cycle_id, request: CycleAction):
        cycle = self.get_cycle(actor, cycle_id)
        with self.product.store._connection() as connection:
            replay = self._replay(connection, cycle_id, "finalize", actor, request)
            if replay:
                return replay
        self._check_cycle(cycle, request.expected_cycle_sha256)
        if cycle["status"] != "AWAITING_DATA":
            raise LearningError("SELECT_OR_REJECT_BEFORE_FINAL_TEST")
        self._still_fresh(actor, cycle["dataset"]["binding"])
        dataset, samples = self._bound_dataset(
            cycle_id, cycle["dataset_storage_key"], cycle["dataset"]
        )
        candidate_record, candidate = self._model(actor, cycle["champion_model_id"])
        baseline_id = candidate_record["parent_model_id"] or cycle["initial_model_id"]
        baseline_record, baseline = self._model(actor, baseline_id)
        with self.product.store._connection(immediate=True) as connection:
            current = self._read(connection, cycle_id, "cycle")
            self._authorize_transaction(connection, actor, current)
            replay = self._replay(connection, cycle_id, "finalize", actor, request)
            if replay:
                return replay
            self._check_cycle(current, request.expected_cycle_sha256)
            self._source_row_fresh(connection, dataset["binding"])
            self._protect_holdouts(connection, current["project_id"], dataset)
            self._record_execution_owner(connection, current, "finalize")
            for sample in dataset["samples"]:
                if sample["split"] == "test":
                    for kind, value in (
                        ("pixel", sample["pixel_sha256"]),
                        ("group", sample["group_id"]),
                    ):
                        connection.execute(
                            "INSERT OR IGNORE INTO learning_consumed_tests VALUES (?,?,?,?)",
                            (current["project_id"], kind, value, cycle_id),
                        )
            current["status"] = "FINALIZING"
            self._update_cycle(
                connection, current, "FINAL_TEST_CONSUMED_NO_MORE_TRAINING", actor
            )
            self._remember(connection, cycle_id, "finalize", actor, request, cycle_id)
        try:
            evaluation = evaluate_models(
                candidate,
                baseline,
                [s for s in samples if s.split == "test"],
                EvaluationPolicy.model_validate(cycle["request"]["evaluation"]),
                split="test",
            )
            self._bound_dataset(
                cycle_id, cycle["dataset_storage_key"], cycle["dataset"]
            )
            self._model(actor, cycle["champion_model_id"])
            self._model(actor, baseline_id)
            self._still_fresh(actor, dataset["binding"])
            with self.product.store._connection(immediate=True) as connection:
                current = self._read(connection, cycle_id, "cycle")
                if current["status"] != "FINALIZING":
                    raise LearningError("FINALIZATION_INTERRUPTED")
                self._authorize_transaction(connection, actor, current)
                self._source_row_fresh(connection, dataset["binding"])
                current.update(
                    status="FINALIZED",
                    final_evaluation=evaluation,
                    final_evaluation_sha256=_sha(evaluation),
                    final_candidate_model_id=candidate_record["model_id"],
                    final_candidate_model_sha256=candidate_record["model_sha256"],
                    final_baseline_model_id=baseline_id,
                    final_baseline_model_sha256=baseline_record["model_sha256"],
                    final_candidate_accepted=evaluation["decision"] == "ELIGIBLE",
                )
                if evaluation["decision"] != "ELIGIBLE":
                    current["champion_model_id"] = baseline_id
                return self._update_cycle(
                    connection, current, "FINAL_EVALUATION_SEALED", actor
                )
        except Exception:
            with self.product.store._connection(immediate=True) as connection:
                current = self._read(connection, cycle_id, "cycle")
                current.update(
                    status="STOPPED", final_test_failure="FINAL_TEST_FAILED_NOT_RETRIED"
                )
                return self._update_cycle(
                    connection, current, "FINAL_TEST_FAILED_CYCLE_CLOSED", actor
                )
