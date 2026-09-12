"""Project-scoped local visual artifacts and explicitly authorized CPU training.

Registration streams bytes only. Model loading is a separate named permission;
Python and Ultralytics stay in the selected external runtime, outside core deps.
"""

from __future__ import annotations

from contextlib import contextmanager
from datetime import UTC, datetime
import hashlib
import hmac
import json
from pathlib import Path
import shutil
import stat
import threading
from typing import Literal
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, Field, model_validator

from .audit_envelope import canonical_jcs_bytes
from .execution_recovery import task_execution_lock
from .task_store import NotFoundError, ProductStoreError


SHA = r"^[0-9a-f]{64}$"
OPAQUE = r"^[A-Za-z0-9_-]{1,120}$"


class VisionModelError(ProductStoreError):
    code = "vision_model_hold"


class VisionRequest(BaseModel):
    model_config = ConfigDict(
        extra="forbid", str_strip_whitespace=True, allow_inf_nan=False
    )
    request_key: str = Field(pattern=r"^[A-Za-z0-9_-]{12,100}$")
    reviewer_identity: str = Field(min_length=2, max_length=160)
    note: str = Field(min_length=8, max_length=1000)

    @model_validator(mode="before")
    @classmethod
    def literal_authority(cls, value):
        if isinstance(value, dict):
            for key, grant in value.items():
                if (
                    key.startswith("operator_attests_")
                    or key == "ultralytics_license_acknowledged"
                ) and type(grant) is not bool:
                    raise ValueError("authority grants must be explicit JSON booleans")
        return value


class RegisterVisionModel(VisionRequest):
    display_name: str = Field(min_length=1, max_length=120)
    weights_path: str = Field(min_length=1, max_length=2048)
    expected_weights_sha256: str = Field(pattern=SHA)
    task_type: Literal["detect", "segment"]
    license_id: str = Field(min_length=1, max_length=120)
    source_description: str = Field(min_length=4, max_length=500)
    operator_attests_read_authorized: Literal[True]


class RegisterVisionRuntime(VisionRequest):
    display_name: str = Field(min_length=1, max_length=120)
    executable_path: str = Field(min_length=1, max_length=2048)
    expected_executable_sha256: str = Field(pattern=SHA)
    operator_attests_trusted_runtime: Literal[True]
    operator_attests_execution_authorized: Literal[True]


class ProbeVisionRuntime(VisionRequest):
    expected_runtime_sha256: str = Field(pattern=SHA)
    operator_attests_trusted_runtime: Literal[True]
    operator_attests_execution_authorized: Literal[True]
    import_check: bool = False


class RegisterDetectionDataset(VisionRequest):
    source_root: str = Field(min_length=1, max_length=2048)
    manifest: dict
    expected_manifest_sha256: str = Field(pattern=SHA)
    operator_attests_data_authorized: Literal[True]


class VisionTrainingBudget(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)
    epochs: int = Field(default=1, ge=1, le=5, strict=True)
    imgsz: int = Field(default=64, ge=64, le=320, multiple_of=32, strict=True)
    batch: int = Field(default=2, ge=2, le=8, strict=True)
    seed: int = Field(default=0, ge=0, le=2147483647, strict=True)
    max_seconds: int = Field(default=120, ge=10, le=600, strict=True)
    threads: int = Field(default=2, ge=1, le=4, strict=True)


class RegisterPoolDetectionDataset(VisionRequest):
    pool_id: str = Field(pattern=OPAQUE)
    version_id: str = Field(pattern=OPAQUE)
    expected_pool_receipt_sha256: str = Field(pattern=SHA)
    expected_version_receipt_sha256: str = Field(pattern=SHA)
    class_names: list[str] = Field(min_length=1, max_length=64)
    groups: dict[str, str] = Field(min_length=1, max_length=64)
    normal_sample_ids: list[str] = Field(default_factory=list, max_length=64)
    operator_attests_data_authorized: Literal[True]


class CreateVisionTrainingRun(VisionRequest):
    runtime_id: str = Field(pattern=OPAQUE)
    expected_runtime_sha256: str = Field(pattern=SHA)
    dataset_id: str = Field(pattern=OPAQUE)
    expected_dataset_receipt_sha256: str = Field(pattern=SHA)
    initialization: Literal["ARCHITECTURE_RANDOM", "REGISTERED_WEIGHTS"]
    initial_model_id: str | None = Field(default=None, pattern=OPAQUE)
    expected_weights_sha256: str | None = Field(default=None, pattern=SHA)
    architecture: Literal["yolo26n"] = "yolo26n"
    training: VisionTrainingBudget = Field(default_factory=VisionTrainingBudget)
    operator_attests_training_authorized: Literal[True]
    operator_attests_trusted_runtime: Literal[True]
    operator_attests_trusted_weights: bool = False
    operator_attests_pickle_load_risk: bool = False
    ultralytics_license_acknowledged: Literal[True]
    adaptation: Literal["OFF"] = "OFF"
    responds_to_feedback_ids: list[str] = Field(default_factory=list, max_length=64)
    expected_feedback_receipts: dict[str, str] = Field(
        default_factory=dict, max_length=64
    )

    @model_validator(mode="after")
    def require_loading_authority(self):
        if len(set(self.responds_to_feedback_ids)) != len(
            self.responds_to_feedback_ids
        ) or set(self.responds_to_feedback_ids) != set(self.expected_feedback_receipts):
            raise ValueError(
                "feedback IDs must be unique and exactly match expected receipts"
            )
        if any(
            not key.startswith("vfeedback_") or len(key) != 34
            for key in self.responds_to_feedback_ids
        ):
            raise ValueError("invalid visual feedback identifier")
        if any(
            len(value) != 64 or any(c not in "0123456789abcdef" for c in value)
            for value in self.expected_feedback_receipts.values()
        ):
            raise ValueError("invalid visual feedback digest")
        if self.initialization == "REGISTERED_WEIGHTS":
            if not (
                self.initial_model_id
                and self.expected_weights_sha256
                and self.operator_attests_trusted_weights
                and self.operator_attests_pickle_load_risk
            ):
                raise ValueError(
                    "registered weights require separate named trusted pickle-load authority"
                )
        elif (
            self.initial_model_id is not None
            or self.expected_weights_sha256 is not None
        ):
            raise ValueError("random initialization cannot silently load a checkpoint")
        return self


class VisionRunAction(VisionRequest):
    expected_run_sha256: str = Field(pattern=SHA)
    operator_attests_reviewed: Literal[True]


class SelectVisionModel(VisionRunAction):
    action: Literal["APPROVE_SANDBOX", "REJECT"]
    expected_candidate_weights_sha256: str = Field(pattern=SHA)


class ReviewVisionFeedback(VisionRunAction):
    expected_feedback_sha256: str = Field(pattern=SHA)
    classification: Literal[
        "MODEL_ERROR", "LABEL_REVIEW_REQUIRED", "HARD_SAMPLE", "UNKNOWN"
    ]


def _sha(value) -> str:
    return hashlib.sha256(canonical_jcs_bytes(value)).hexdigest()


def _seal(value: dict) -> dict:
    stable = {key: item for key, item in value.items() if key != "receipt_sha256"}
    return stable | {"receipt_sha256": _sha(stable)}


def _now() -> str:
    return datetime.now(UTC).isoformat()


def _dataset_content_identity(dataset: dict) -> str:
    receipt = dataset["dataset_receipt"]
    rows = [
        {key: sample[key] for key in ("pixel_sha256", "label_sha256", "split")}
        for sample in receipt["samples"]
    ]
    return _sha(
        {"class_names": receipt["class_names"], "samples": sorted(rows, key=_sha)}
    )


def _file(path: str | Path, expected: str, error: str) -> Path:
    candidate = Path(path).expanduser()
    if not candidate.is_absolute():
        raise VisionModelError("ABSOLUTE_LOCAL_PATH_REQUIRED")
    for member in (candidate, *candidate.parents):
        try:
            info = member.lstat()
        except OSError:
            raise VisionModelError("LOCAL_FILE_UNAVAILABLE") from None
        if stat.S_ISLNK(info.st_mode) or getattr(info, "st_file_attributes", 0) & 0x400:
            raise VisionModelError("LOCAL_LINK_FORBIDDEN")
    digest = hashlib.sha256()
    try:
        with candidate.open("rb") as stream:
            before = candidate.stat()
            if not stat.S_ISREG(before.st_mode) or before.st_size > 2 * 1024**3:
                raise VisionModelError("FILE_SIZE_OR_TYPE_UNSUPPORTED")
            while chunk := stream.read(1024 * 1024):
                digest.update(chunk)
            after = candidate.stat()
    except OSError:
        raise VisionModelError("LOCAL_FILE_UNAVAILABLE") from None
    if (before.st_size, before.st_mtime_ns, before.st_ino) != (
        after.st_size,
        after.st_mtime_ns,
        after.st_ino,
    ) or not hmac.compare_digest(expected, digest.hexdigest()):
        raise VisionModelError(error)
    return candidate.resolve(strict=True)


class LocalVisionModelService:
    """Use existing project membership, transactions and explicit per-request work."""

    def __init__(self, product):
        self.product = product
        self.root = product.product_root / "vision_models"

    def _authorize(self, actor, project):
        self.product.store.get_project(actor, project)
        if self.root.exists() and (self.root.is_symlink() or self.root.is_junction()):
            raise VisionModelError("REGISTRY_ROOT_LINK_FORBIDDEN")
        self.root.mkdir(exist_ok=True)
        with self.product.store._connection(immediate=True) as conn:
            conn.execute(
                "CREATE TABLE IF NOT EXISTS vision_records (id TEXT PRIMARY KEY, project_id TEXT NOT NULL, kind TEXT NOT NULL, body TEXT NOT NULL, private_body TEXT NOT NULL)"
            )
            conn.execute(
                "CREATE TABLE IF NOT EXISTS vision_requests (project_id TEXT NOT NULL, actor TEXT NOT NULL, operation TEXT NOT NULL, request_key TEXT NOT NULL, request_sha TEXT NOT NULL, result_id TEXT NOT NULL, PRIMARY KEY(project_id, actor, operation, request_key))"
            )
            conn.execute(
                "CREATE TABLE IF NOT EXISTS vision_split_members (project_id TEXT NOT NULL, kind TEXT NOT NULL, value TEXT NOT NULL, split TEXT NOT NULL, PRIMARY KEY(project_id,kind,value))"
            )

    def _membership(self, conn, actor, project):
        row = conn.execute(
            "SELECT workspace_id FROM projects WHERE project_id=?", (project,)
        ).fetchone()
        if row is None:
            raise NotFoundError("visual project unavailable")
        self.product.store._require_membership(conn, row[0], actor)

    def _read(self, conn, project, identifier, kind=None):
        row = conn.execute(
            "SELECT kind,body,private_body FROM vision_records WHERE id=? AND project_id=?",
            (identifier, project),
        ).fetchone()
        if row is None or (kind and row[0] != kind):
            raise NotFoundError("visual resource unavailable")
        value = json.loads(row[1])
        if value != _seal(value):
            raise VisionModelError("REGISTRY_RECEIPT_MISMATCH")
        return value, json.loads(row[2])

    def _put(self, conn, value, kind, private=None, *, replace=False):
        identifier = value["resource_id"]
        sealed = _seal(value)
        if replace:
            conn.execute(
                "UPDATE vision_records SET body=? WHERE id=? AND project_id=?",
                (json.dumps(sealed), identifier, value["project_id"]),
            )
        else:
            conn.execute(
                "INSERT INTO vision_records VALUES (?,?,?,?,?)",
                (
                    identifier,
                    value["project_id"],
                    kind,
                    json.dumps(sealed),
                    json.dumps(private or {}),
                ),
            )
        return sealed

    def _base(self, project, kind, actor, request):
        identifier = kind + "_" + uuid4().hex[:24]
        return {
            "schema_version": f"visiondata-gate.{kind}.v1",
            "resource_id": identifier,
            "project_id": project,
            "created_by": actor,
            "reviewer_identity": request.reviewer_identity,
            "created_at": _now(),
            "production_release_allowed": False,
            "machine_write_permitted": False,
        }

    @contextmanager
    def _operation(self, actor, project, operation, request):
        type(request).model_validate(request.model_dump(mode="json"))
        self._authorize(actor, project)
        with task_execution_lock(
            self.product.product_root,
            f"vision:{project}:{actor}:{operation}:{request.request_key}",
        ) as acquired:
            if not acquired:
                raise VisionModelError("OPERATION_IN_PROGRESS")
            with self.product.store._connection() as conn:
                row = conn.execute(
                    "SELECT request_sha,result_id FROM vision_requests WHERE project_id=? AND actor=? AND operation=? AND request_key=?",
                    (project, actor, operation, request.request_key),
                ).fetchone()
                if row and row[0] != _sha(request.model_dump(mode="json")):
                    raise VisionModelError("IDEMPOTENCY_CONFLICT")
                existing = self._read(conn, project, row[1])[0] if row else None
            try:
                yield existing
            except (OSError, ValueError, TypeError, KeyError):
                raise VisionModelError(
                    "VISION_INPUT_OR_RUNTIME_CONTRACT_INVALID"
                ) from None

    def _remember(self, conn, actor, project, operation, request, result):
        self._membership(conn, actor, project)
        conn.execute(
            "INSERT INTO vision_requests VALUES (?,?,?,?,?,?)",
            (
                project,
                actor,
                operation,
                request.request_key,
                _sha(request.model_dump(mode="json")),
                result["resource_id"],
            ),
        )

    def _list(self, actor, project, kind):
        self._authorize(actor, project)
        with self.product.store._connection() as conn:
            ids = conn.execute(
                "SELECT id FROM vision_records WHERE project_id=? AND kind=? ORDER BY id",
                (project, kind),
            ).fetchall()
            items = [self._read(conn, project, row[0], kind)[0] for row in ids]
        return _seal(
            {
                "schema_version": "visiondata-gate.vision-list.v1",
                "project_id": project,
                "items": items,
            }
        )

    def _get(self, actor, project, identifier, kind):
        self._authorize(actor, project)
        with self.product.store._connection() as conn:
            return self._read(conn, project, identifier, kind)[0]

    def list_models(self, actor, project):
        return self._list(actor, project, "model")

    def list_runtimes(self, actor, project):
        return self._list(actor, project, "runtime")

    def list_datasets(self, actor, project):
        return self._list(actor, project, "dataset")

    def list_runs(self, actor, project):
        return self._list(actor, project, "run")

    def get_model(self, actor, project, identifier):
        return self._get(actor, project, identifier, "model")

    def get_run(self, actor, project, identifier):
        return self._get(actor, project, identifier, "run")

    def capabilities(self, actor, project):
        models = self.list_models(actor, project)["items"]
        runtimes = self.list_runtimes(actor, project)["items"]
        datasets = self.list_datasets(actor, project)["items"]
        ready_runtimes = [
            r
            for r in runtimes
            if r["probe"].get("status") == "ready" and r["probe"].get("runtime_sha256")
        ]
        return _seal(
            {
                "schema_version": "visiondata-gate.vision-capabilities.v1",
                "project_id": project,
                "model_domain": "LOCAL_VISUAL_MODELS",
                "llm_provider_managed": False,
                "supported_registration_tasks": ["detect", "segment"],
                "executable_training_tasks": ["detect"],
                "training_device": "CPU_ONLY",
                "initializations": ["ARCHITECTURE_RANDOM", "REGISTERED_WEIGHTS"],
                "ttt_status": "DISABLED_NOT_IMPLEMENTED",
                "weight_download_allowed": False,
                "registered_model_count": len(models),
                "registered_runtime_count": len(runtimes),
                "registered_dataset_count": len(datasets),
                "training_ready": bool(ready_runtimes and datasets),
                "training_authorization_required": True,
                "license_boundary": "ULTRALYTICS_AGPL_3_0_OR_ENTERPRISE_REVIEW_REQUIRED",
                "production_release_allowed": False,
                "industrial_effectiveness_status": "NOT_EVALUATED",
            }
        )

    def register_model(self, actor, project, request: RegisterVisionModel):
        request = RegisterVisionModel.model_validate(request.model_dump(mode="json"))
        with self._operation(actor, project, "register_model", request) as existing:
            if existing:
                return existing
            path = _file(
                request.weights_path, request.expected_weights_sha256, "WEIGHTS_CHANGED"
            )
            if path.suffix.lower() not in {".pt", ".onnx", ".safetensors"}:
                raise VisionModelError("MODEL_FORMAT_UNSUPPORTED")
            value = self._base(project, "vision_model", actor, request)
            value.update(
                model_id=value["resource_id"],
                display_name=request.display_name,
                task_type=request.task_type,
                weights_sha256=request.expected_weights_sha256,
                file_bytes=path.stat().st_size,
                format=path.suffix.lower()[1:],
                license_id=request.license_id,
                license_status="OPERATOR_DECLARED_NOT_LEGAL_VERIFICATION",
                source_description=request.source_description,
                status="REGISTERED_NOT_LOADED",
                loaded=False,
            )
            with self.product.store._connection(immediate=True) as conn:
                result = self._put(conn, value, "model", {"weights_path": str(path)})
                self._remember(conn, actor, project, "register_model", request, result)
            return result

    def register_runtime(self, actor, project, request: RegisterVisionRuntime):
        from .learning_yolo_backend import probe_vision_runtime

        with self._operation(actor, project, "register_runtime", request) as existing:
            if existing:
                return existing
            path = _file(
                request.executable_path,
                request.expected_executable_sha256,
                "RUNTIME_CHANGED",
            )
            value = self._base(project, "vision_runtime", actor, request)
            probe = probe_vision_runtime(
                path,
                request.expected_executable_sha256,
                self.root / "probes" / value["resource_id"],
                import_check=False,
            )
            value.update(
                runtime_id=value["resource_id"],
                display_name=request.display_name,
                executable_sha256=request.expected_executable_sha256,
                runtime_sha256=probe.get("runtime_sha256") or _sha(probe),
                probe=probe,
                status=(
                    "METADATA_PROBED_IMPORT_NOT_TESTED"
                    if probe.get("status") == "ready"
                    else "UNAVAILABLE"
                ),
            )
            with self.product.store._connection(immediate=True) as conn:
                result = self._put(
                    conn, value, "runtime", {"executable_path": str(path)}
                )
                self._remember(
                    conn, actor, project, "register_runtime", request, result
                )
            return result

    def probe_runtime(self, actor, project, identifier, request: ProbeVisionRuntime):
        from .learning_yolo_backend import probe_vision_runtime

        with self._operation(
            actor, project, "probe_runtime:" + identifier, request
        ) as existing:
            if existing:
                return existing
            with self.product.store._connection() as conn:
                runtime, private = self._read(conn, project, identifier, "runtime")
            if request.expected_runtime_sha256 != runtime["runtime_sha256"]:
                raise VisionModelError("STALE_RUNTIME")
            probe = probe_vision_runtime(
                Path(private["executable_path"]),
                runtime["executable_sha256"],
                self.root / "probes" / ("probe_" + uuid4().hex),
                import_check=request.import_check,
            )
            if (
                probe.get("runtime_sha256", request.expected_runtime_sha256)
                != request.expected_runtime_sha256
            ):
                raise VisionModelError("RUNTIME_CHANGED")
            with self.product.store._connection(immediate=True) as conn:
                result = self._put(
                    conn,
                    runtime
                    | {
                        "probe": probe,
                        "status": "PROBED"
                        if probe.get("status") == "ready"
                        else "UNAVAILABLE",
                    },
                    "runtime",
                    replace=True,
                )
                self._remember(
                    conn, actor, project, "probe_runtime:" + identifier, request, result
                )
            return result

    def register_dataset(self, actor, project, request: RegisterDetectionDataset):
        from .learning_detection_dataset import freeze_detection_dataset

        with self._operation(actor, project, "register_dataset", request) as existing:
            if existing:
                return existing
            value = self._base(project, "vision_dataset", actor, request)
            output = self.root / "datasets" / value["resource_id"]
            output.parent.mkdir(parents=True, exist_ok=True)
            receipt = freeze_detection_dataset(
                Path(request.source_root),
                request.manifest,
                output,
                request.expected_manifest_sha256,
            )
            value.update(
                dataset_id=value["resource_id"],
                dataset_receipt=receipt,
                dataset_receipt_sha256=receipt["receipt_sha256"],
                status="FROZEN_REVIEWED_DETECTION_DATASET",
            )
            return self._publish_dataset(
                actor, project, "register_dataset", request, value, output
            )

    def _publish_dataset(self, actor, project, operation, request, value, output):
        with self.product.store._connection(immediate=True) as conn:
            self._verify_pool_transaction(
                conn, actor, project, {"pool_binding": value.get("pool_binding")}
            )
            for sample in value["dataset_receipt"]["samples"]:
                for kind, key in (
                    ("pixel", sample["pixel_sha256"]),
                    ("group", _sha(sample["group_id"])),
                ):
                    old = conn.execute(
                        "SELECT split FROM vision_split_members WHERE project_id=? AND kind=? AND value=?",
                        (project, kind, key),
                    ).fetchone()
                    if old and old[0] != sample["split"]:
                        raise VisionModelError("PROJECT_HELDOUT_REUSE_FORBIDDEN")
                    conn.execute(
                        "INSERT OR IGNORE INTO vision_split_members VALUES (?,?,?,?)",
                        (project, kind, key, sample["split"]),
                    )
            private = {
                "dataset_root": str(output),
                "pool_binding": value.get("pool_binding"),
            }
            result = self._put(conn, value, "dataset", private)
            self._remember(conn, actor, project, operation, request, result)
        return result

    def register_pool_dataset(
        self, actor, project, request: RegisterPoolDetectionDataset
    ):
        from .learning_detection_dataset import (
            freeze_detection_dataset,
            manifest_sha256,
        )
        from .vision_data_pool_bridge import pool_detection_input, verify_pool_binding

        with self._operation(
            actor, project, "register_pool_dataset", request
        ) as existing:
            if existing:
                return existing
            source_root, manifest, binding = pool_detection_input(
                self.product, actor, project, request
            )
            value = self._base(project, "vision_dataset", actor, request)
            output = self.root / "datasets" / value["resource_id"]
            output.parent.mkdir(parents=True, exist_ok=True)
            receipt = freeze_detection_dataset(
                source_root, manifest, output, manifest_sha256(manifest)
            )
            verify_pool_binding(self.product, actor, project, binding)
            value.update(
                dataset_id=value["resource_id"],
                dataset_receipt=receipt,
                dataset_receipt_sha256=receipt["receipt_sha256"],
                pool_binding=binding,
                status="FROZEN_REVIEWED_DETECTION_DATASET",
            )
            return self._publish_dataset(
                actor, project, "register_pool_dataset", request, value, output
            )

    def _verify_dataset_source(self, actor, project, private):
        binding = private.get("pool_binding")
        if binding is not None:
            from .vision_data_pool_bridge import verify_pool_binding

            verify_pool_binding(self.product, actor, project, binding)

    def _verify_pool_transaction(self, connection, actor, project, private):
        binding = private.get("pool_binding")
        if binding is not None:
            from .vision_data_pool_bridge import verify_pool_binding_in_connection

            verify_pool_binding_in_connection(connection, actor, project, binding)

    def _feedback_inputs(self, connection, project, request, dataset):
        for identifier in request.responds_to_feedback_ids:
            feedback, _ = self._read(connection, project, identifier, "feedback")
            if (
                feedback["receipt_sha256"]
                != request.expected_feedback_receipts[identifier]
                or feedback["status"] != "TRIAGED_FOR_REVIEW"
                or feedback["classification"] == "UNKNOWN"
            ):
                raise VisionModelError("FEEDBACK_NOT_CURRENT_OR_TRIAGED")
            if feedback["dataset_receipt_sha256"] == dataset["dataset_receipt_sha256"]:
                raise VisionModelError("FEEDBACK_REQUIRES_NEW_DATA_VERSION")
            previous, _ = self._read(
                connection, project, feedback["dataset_id"], "dataset"
            )
            if _dataset_content_identity(previous) == _dataset_content_identity(
                dataset
            ):
                raise VisionModelError("FEEDBACK_REQUIRES_CHANGED_IMAGES_OR_LABELS")
            previous_pool = previous.get("pool_binding")
            if previous_pool is not None:
                new_pool = dataset.get("pool_binding")
                if (
                    new_pool is None
                    or new_pool["version_id"] == previous_pool["version_id"]
                    or new_pool["task_id"] == previous_pool["task_id"]
                ):
                    raise VisionModelError("FEEDBACK_REQUIRES_NEW_POOL_AND_GATE")

    def create_training_run(self, actor, project, request: CreateVisionTrainingRun):
        from .learning_detection_dataset import verify_detection_dataset

        request = CreateVisionTrainingRun.model_validate(
            request.model_dump(mode="json")
        )
        with self._operation(
            actor, project, "create_training_run", request
        ) as existing:
            if existing:
                return existing
            with self.product.store._connection() as conn:
                runtime, runtime_private = self._read(
                    conn, project, request.runtime_id, "runtime"
                )
                dataset, dataset_private = self._read(
                    conn, project, request.dataset_id, "dataset"
                )
                model, model_private = (
                    self._read(conn, project, request.initial_model_id, "model")
                    if request.initial_model_id
                    else (None, {})
                )
                self._feedback_inputs(conn, project, request, dataset)
            if runtime["runtime_sha256"] != request.expected_runtime_sha256:
                raise VisionModelError("STALE_RUNTIME")
            if runtime["probe"].get("status") != "ready":
                raise VisionModelError("RUNTIME_UNAVAILABLE")
            if (
                dataset["dataset_receipt_sha256"]
                != request.expected_dataset_receipt_sha256
            ):
                raise VisionModelError("STALE_DATASET")
            self._verify_dataset_source(actor, project, dataset_private)
            verify_detection_dataset(
                Path(dataset_private["dataset_root"]),
                request.expected_dataset_receipt_sha256,
            )
            _file(
                runtime_private["executable_path"],
                runtime["executable_sha256"],
                "RUNTIME_CHANGED",
            )
            if model is not None:
                if model["task_type"] != "detect" or model["format"] != "pt":
                    raise VisionModelError("YOLO_DETECTION_CHECKPOINT_REQUIRED")
                if model["weights_sha256"] != request.expected_weights_sha256:
                    raise VisionModelError("STALE_WEIGHTS")
                if model["license_id"].upper() in {"UNKNOWN", "UNSPECIFIED", "NONE"}:
                    raise VisionModelError("WEIGHTS_LICENSE_UNRESOLVED")
                _file(
                    model_private["weights_path"],
                    request.expected_weights_sha256,
                    "WEIGHTS_CHANGED",
                )
            value = self._base(project, "vision_run", actor, request)
            value.update(
                run_id=value["resource_id"],
                status="QUEUED",
                runtime_id=request.runtime_id,
                runtime_sha256=request.expected_runtime_sha256,
                dataset_id=request.dataset_id,
                dataset_receipt_sha256=request.expected_dataset_receipt_sha256,
                initial_model_id=request.initial_model_id,
                initialization=request.initialization,
                pretrained_claimed=False,
                architecture="yolo26n",
                device="cpu",
                training=request.training.model_dump(),
                adaptation="OFF",
                ttt_status="DISABLED_NOT_IMPLEMENTED",
                authorization_sha256=_sha(request.model_dump(mode="json")),
                cancel_requested=False,
                candidate_model_id=None,
                selection="PENDING",
                result=None,
                error_code=None,
                responds_to_feedback_ids=list(request.responds_to_feedback_ids),
                feedback_ids=[],
                feedback_status="NOT_EVALUATED",
            )
            private = {
                "runtime": runtime,
                "runtime_private": runtime_private,
                "dataset_private": dataset_private,
                "model_private": model_private,
                "request": request.model_dump(mode="json"),
            }
            with self.product.store._connection(immediate=True) as conn:
                self._verify_pool_transaction(conn, actor, project, dataset_private)
                self._feedback_inputs(conn, project, request, dataset)
                active = conn.execute(
                    "SELECT body FROM vision_records WHERE kind='run' AND project_id=?",
                    (project,),
                ).fetchall()
                if any(
                    json.loads(row[0])["status"] in {"QUEUED", "RUNNING"}
                    for row in active
                ):
                    raise VisionModelError("PROJECT_TRAINING_ALREADY_ACTIVE")
                result = self._put(conn, value, "run", private)
                self._remember(
                    conn, actor, project, "create_training_run", request, result
                )
            threading.Thread(
                target=self._execute_run,
                args=(actor, project, value["run_id"]),
                name="vision-cpu-" + value["run_id"],
                daemon=False,
            ).start()
            return result

    def _cancelled(self, project, identifier):
        with self.product.store._connection() as conn:
            run, _ = self._read(conn, project, identifier, "run")
        return run["cancel_requested"] or run["status"] != "RUNNING"

    def _execute_run(self, actor, project, identifier):
        from .learning_detection_dataset import verify_detection_dataset
        from .learning_yolo_backend import YoloTrainingConfig, run_yolo_training

        with task_execution_lock(
            self.product.product_root, "vision-run:" + identifier
        ) as acquired:
            if not acquired:
                return
            try:
                self._authorize(actor, project)
                with self.product.store._connection(immediate=True) as conn:
                    run, private = self._read(conn, project, identifier, "run")
                    if run["status"] != "QUEUED":
                        return
                    self._membership(conn, actor, project)
                    self._verify_pool_transaction(
                        conn, actor, project, private["dataset_private"]
                    )
                    dataset, _ = self._read(conn, project, run["dataset_id"], "dataset")
                    self._feedback_inputs(
                        conn,
                        project,
                        CreateVisionTrainingRun.model_validate(private["request"]),
                        dataset,
                    )
                    run = self._put(
                        conn,
                        run | {"status": "RUNNING", "started_at": _now()},
                        "run",
                        replace=True,
                    )
                dataset_root = Path(private["dataset_private"]["dataset_root"])
                self._verify_dataset_source(actor, project, private["dataset_private"])
                verify_detection_dataset(dataset_root, run["dataset_receipt_sha256"])
                job_root = self.root / "runs" / identifier
                inputs = job_root / "dataset"
                inputs.parent.mkdir(parents=True, exist_ok=False)
                shutil.copytree(dataset_root, inputs)
                result = run_yolo_training(
                    executable=Path(private["runtime_private"]["executable_path"]),
                    expected_executable_sha256=private["runtime"]["executable_sha256"],
                    expected_runtime_sha256=run["runtime_sha256"],
                    dataset_root=inputs,
                    output_root=job_root / "execution",
                    config=YoloTrainingConfig(**run["training"]),
                    initial_weights=(
                        Path(private["model_private"]["weights_path"])
                        if private["model_private"]
                        else None
                    ),
                    expected_weights_sha256=private["request"][
                        "expected_weights_sha256"
                    ],
                    cancelled=lambda: self._cancelled(project, identifier),
                )
                verify_detection_dataset(dataset_root, run["dataset_receipt_sha256"])
                self.product.store.get_project(actor, project)
                self._verify_dataset_source(actor, project, private["dataset_private"])
                with self.product.store._connection(immediate=True) as conn:
                    current, _ = self._read(conn, project, identifier, "run")
                    self._membership(conn, actor, project)
                    self._verify_pool_transaction(
                        conn, actor, project, private["dataset_private"]
                    )
                    status = {
                        "completed": "SUCCEEDED_CANDIDATE",
                        "cancelled": "CANCELLED",
                        "timed_out": "TIMED_OUT",
                    }.get(result.get("status"), "FAILED")
                    if current["cancel_requested"]:
                        status = "CANCELLED"
                    candidate_id = None
                    feedback_ids = []
                    feedback_status = "NOT_AVAILABLE_LEGACY_RESULT"
                    if status == "SUCCEEDED_CANDIDATE":
                        checkpoint = result["checkpoint"]
                        path = job_root / "execution" / checkpoint["relative_path"]
                        path.resolve().relative_to(job_root.resolve())
                        _file(path, checkpoint["sha256"], "CHECKPOINT_CHANGED")
                        request = CreateVisionTrainingRun.model_validate(
                            private["request"]
                        )
                        candidate = self._base(project, "vision_model", actor, request)
                        candidate_id = candidate["resource_id"]
                        candidate.update(
                            model_id=candidate_id,
                            display_name="YOLO26 candidate",
                            task_type="detect",
                            format="pt",
                            weights_sha256=checkpoint["sha256"],
                            file_bytes=path.stat().st_size,
                            license_id="AGPL-3.0_OR_ENTERPRISE_REVIEW_REQUIRED",
                            license_status="OPERATOR_ACKNOWLEDGED_NOT_LEGAL_VERIFICATION",
                            source_description="Locally generated checkpoint",
                            status="CANDIDATE_REQUIRES_HUMAN_REVIEW",
                            loaded=False,
                            training_run_id=identifier,
                            parent_model_id=run["initial_model_id"],
                            dataset_id=run["dataset_id"],
                        )
                        self._put(conn, candidate, "model", {"weights_path": str(path)})
                        from .vision_feedback import build_vision_feedback

                        dataset, _ = self._read(
                            conn, project, run["dataset_id"], "dataset"
                        )
                        self._feedback_inputs(conn, project, request, dataset)
                        for feedback in build_vision_feedback(
                            project,
                            identifier,
                            run["dataset_id"],
                            dataset["dataset_receipt"],
                            result,
                        ):
                            self._put(conn, feedback, "feedback")
                            feedback_ids.append(feedback["feedback_id"])
                        if result.get("validation_feedback_protocol") is not None:
                            feedback_status = (
                                "VAL_DISAGREEMENTS_REQUIRE_HUMAN_REVIEW"
                                if feedback_ids
                                else "NO_VAL_DISAGREEMENT_AT_FIXED_PROTOCOL"
                            )
                    self._put(
                        conn,
                        current
                        | {
                            "status": status,
                            "result": result,
                            "candidate_model_id": candidate_id,
                            "finished_at": _now(),
                            "feedback_ids": feedback_ids,
                            "feedback_status": feedback_status,
                        },
                        "run",
                        replace=True,
                    )
            except Exception:
                with self.product.store._connection(immediate=True) as conn:
                    run, _ = self._read(conn, project, identifier, "run")
                    self._put(
                        conn,
                        run
                        | {
                            "status": "CANCELLED"
                            if run["cancel_requested"]
                            else "FAILED",
                            "error_code": "TRAINING_EVIDENCE_OR_EXECUTION_FAILED",
                            "finished_at": _now(),
                        },
                        "run",
                        replace=True,
                    )

    def _run_action(self, actor, project, identifier, request, operation):
        with self._operation(
            actor, project, operation + ":" + identifier, request
        ) as existing:
            if existing:
                return existing
            if operation == "selection":
                with self.product.store._connection() as connection:
                    _run, source = self._read(connection, project, identifier, "run")
                self._verify_dataset_source(actor, project, source["dataset_private"])
            with self.product.store._connection(immediate=True) as conn:
                run, private = self._read(conn, project, identifier, "run")
                if request.expected_run_sha256 != run["receipt_sha256"]:
                    raise VisionModelError("STALE_RUN")
                if operation == "cancel":
                    if run["status"] not in {"QUEUED", "RUNNING"}:
                        raise VisionModelError("RUN_ALREADY_TERMINAL")
                    changes = {"cancel_requested": True}
                    if run["status"] == "QUEUED":
                        changes["status"] = "CANCELLED"
                elif operation == "recover":
                    if run["status"] not in {"QUEUED", "RUNNING"}:
                        raise VisionModelError("RUN_NOT_INTERRUPTED")
                    changes = {
                        "status": "INTERRUPTED_HOLD",
                        "cancel_requested": True,
                        "error_code": "NEW_AUTHORIZATION_REQUIRED_NO_AUTO_REPLAY",
                    }
                else:
                    if (
                        run["status"] != "SUCCEEDED_CANDIDATE"
                        or run["selection"] != "PENDING"
                    ):
                        raise VisionModelError("CANDIDATE_NOT_SELECTABLE")
                    self._verify_pool_transaction(
                        conn, actor, project, private["dataset_private"]
                    )
                    model, model_private = self._read(
                        conn, project, run["candidate_model_id"], "model"
                    )
                    if (
                        model["weights_sha256"]
                        != request.expected_candidate_weights_sha256
                    ):
                        raise VisionModelError("STALE_CANDIDATE")
                    _file(
                        model_private["weights_path"],
                        model["weights_sha256"],
                        "CHECKPOINT_CHANGED",
                    )
                    from .learning_detection_dataset import verify_detection_dataset

                    verify_detection_dataset(
                        Path(private["dataset_private"]["dataset_root"]),
                        run["dataset_receipt_sha256"],
                    )
                    changes = {
                        "selection": request.action,
                        "selected_by": actor,
                        "selected_at": _now(),
                        "selection_reviewer": request.reviewer_identity,
                        "selection_note": request.note,
                    }
                    self._put(
                        conn, model | {"status": request.action}, "model", replace=True
                    )
                result = self._put(conn, run | changes, "run", replace=True)
                self._remember(
                    conn, actor, project, operation + ":" + identifier, request, result
                )
            return result

    def cancel_run(self, actor, project, identifier, request: VisionRunAction):
        return self._run_action(actor, project, identifier, request, "cancel")

    def recover_run(self, actor, project, identifier, request: VisionRunAction):
        self._authorize(actor, project)
        with task_execution_lock(
            self.product.product_root, "vision-run:" + identifier
        ) as acquired:
            if not acquired:
                raise VisionModelError("EXECUTION_OWNER_ACTIVE")
            return self._run_action(actor, project, identifier, request, "recover")

    def select_model(self, actor, project, identifier, request: SelectVisionModel):
        return self._run_action(actor, project, identifier, request, "selection")

    def list_feedback(self, actor, project, identifier):
        self.get_run(actor, project, identifier)
        result = self._list(actor, project, "feedback")
        return _seal(
            result
            | {
                "run_id": identifier,
                "items": [
                    item for item in result["items"] if item["run_id"] == identifier
                ],
            }
        )

    def triage_feedback(
        self, actor, project, run_id, feedback_id, request: ReviewVisionFeedback
    ):
        with self._operation(
            actor, project, "triage_feedback:" + feedback_id, request
        ) as existing:
            if existing:
                if existing["run_id"] != run_id:
                    raise NotFoundError("visual feedback unavailable")
                return existing
            with self.product.store._connection(immediate=True) as conn:
                run, _ = self._read(conn, project, run_id, "run")
                feedback, _ = self._read(conn, project, feedback_id, "feedback")
                if feedback["run_id"] != run_id or feedback_id not in run.get(
                    "feedback_ids", []
                ):
                    raise NotFoundError("visual feedback unavailable")
                if (
                    run["receipt_sha256"] != request.expected_run_sha256
                    or feedback["receipt_sha256"] != request.expected_feedback_sha256
                ):
                    raise VisionModelError("STALE_RUN_OR_FEEDBACK")
                if (
                    run["status"] != "SUCCEEDED_CANDIDATE"
                    or feedback["status"] != "PENDING_HUMAN_REVIEW"
                ):
                    raise VisionModelError("FEEDBACK_NOT_REVIEWABLE")
                value = feedback | {
                    "status": "TRIAGED_FOR_REVIEW",
                    "classification": request.classification,
                    "reviewed_by": actor,
                    "reviewer_identity": request.reviewer_identity,
                    "review_note": request.note,
                    "reviewed_at": _now(),
                    "issue_closed": False,
                    "training_ingestion_allowed": False,
                }
                result = self._put(conn, value, "feedback", replace=True)
                self._remember(
                    conn,
                    actor,
                    project,
                    "triage_feedback:" + feedback_id,
                    request,
                    result,
                )
            return result

    def get_operation(self, actor, project, operation, request_key):
        self._authorize(actor, project)
        with self.product.store._connection() as conn:
            row = conn.execute(
                "SELECT result_id FROM vision_requests WHERE project_id=? AND actor=? AND operation=? AND request_key=?",
                (project, actor, operation, request_key),
            ).fetchone()
            if row is None:
                raise NotFoundError("visual operation unavailable")
            resource, _ = self._read(conn, project, row[0])
        return _seal(
            {
                "schema_version": "visiondata-gate.vision-operation.v1",
                "project_id": project,
                "operation": operation,
                "request_key": request_key,
                "resource_id": row[0],
                "resource": resource,
                "auto_replayed": False,
            }
        )
