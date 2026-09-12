"""Governed, versioned member pools over one frozen source snapshot at a time.

A pool is an evidence projection, not a good/bad classifier. It persists named
human review over a verified ProductService task and can materialize only a
qualified proper subset. Derived subsets remain blocked pending a new Gate.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
import hashlib
import hmac
import json
import os
from pathlib import Path
import re
from typing import Any, Literal

from pydantic import Field, field_validator, model_validator

from .audit_envelope import canonical_jcs_bytes
from .evidence import write_canonical_json
from .learning_projection import learning_readiness
from .operator_snapshot import (
    MaterializedOperatorProjectSnapshot,
    OperatorProjectSnapshotReceipt,
    materialize_operator_snapshot_subset,
    profile_operator_project_snapshot,
)
from .product_models import (
    AuthorizeLocalSourceRequest,
    LocalSourceAdapterKind,
    ProductModel,
)
from .task_store import NotFoundError, ProductStoreError


SHA = r"^[0-9a-f]{64}$"
SAFE_ID = r"^[A-Za-z0-9][A-Za-z0-9_.:-]{0,159}$"
REQUEST_KEY = r"^[A-Za-z0-9_-]{12,100}$"
SAFE_MEMBER_COMPLEMENT_BLOCKERS = frozenset({"GATE_NOT_PASS"})
QUALIFIED_READINESS_STATES = frozenset(
    {"GATE_ELIGIBLE_NOT_TRAINING_APPROVED"}
)

MemberDisposition = Literal[
    "QUALIFIED_CANDIDATE", "REPAIR_REQUIRED", "UNVERIFIED_HOLD"
]
RepairAction = Literal[
    "NONE", "RELABEL", "RECAPTURE", "REMOVE_OR_REPARTITION", "INVESTIGATE"
]
RepairResult = Literal["NOT_APPLICABLE", "PENDING", "EVIDENCE_LINKED_NOT_VERIFIED"]
VersionStatus = Literal[
    "REVIEWED_ALL_QUALIFIED_REFERENCE",
    "REVIEWED_ACTION_REQUIRED",
    "REVIEWED_WITH_HOLD",
]


class DataPoolError(ProductStoreError):
    code = "data_pool_hold"


class DataPoolMemberDecision(ProductModel):
    sample_id: str = Field(pattern=SAFE_ID)
    expected_asset_sha256: str = Field(pattern=SHA)
    expected_annotation_revision: int = Field(ge=0, strict=True)
    expected_annotation_sha256: str = Field(pattern=SHA)
    disposition: MemberDisposition
    repair_action: RepairAction
    repair_result: RepairResult
    decision_note: str = Field(min_length=8, max_length=1000)

    @model_validator(mode="after")
    def validate_action_result(self) -> "DataPoolMemberDecision":
        if self.disposition == "QUALIFIED_CANDIDATE" and (
            self.repair_action != "NONE" or self.repair_result != "NOT_APPLICABLE"
        ):
            raise ValueError("qualified members cannot claim a repair")
        if self.disposition == "REPAIR_REQUIRED" and (
            self.repair_action == "NONE" or self.repair_result == "NOT_APPLICABLE"
        ):
            raise ValueError("repair-required members need a pending action")
        if self.disposition == "UNVERIFIED_HOLD" and (
            self.repair_action != "INVESTIGATE"
            or self.repair_result == "NOT_APPLICABLE"
        ):
            raise ValueError("unverified members must remain under investigation")
        return self


class CreateDataPoolRequest(ProductModel):
    request_key: str = Field(pattern=REQUEST_KEY)
    expected_readiness_sha256: str = Field(pattern=SHA)
    reviewer_name: str = Field(min_length=2, max_length=120)
    review_note: str = Field(min_length=8, max_length=2000)
    operator_attests_reviewed: Literal[True]
    members: list[DataPoolMemberDecision] = Field(min_length=1, max_length=10_000)

    @field_validator("members")
    @classmethod
    def unique_sorted_members(
        cls, values: list[DataPoolMemberDecision]
    ) -> list[DataPoolMemberDecision]:
        identifiers = [item.sample_id for item in values]
        if len(identifiers) != len(set(identifiers)):
            raise ValueError("data-pool member decisions must be unique")
        return sorted(values, key=lambda item: item.sample_id)


class CreateDataPoolVersionRequest(CreateDataPoolRequest):
    expected_pool_sha256: str = Field(pattern=SHA)
    expected_parent_version_sha256: str = Field(pattern=SHA)
    source_task_id: str | None = Field(default=None, pattern=SAFE_ID)


class DeriveDataPoolVersionRequest(ProductModel):
    request_key: str = Field(pattern=REQUEST_KEY)
    expected_pool_sha256: str = Field(pattern=SHA)
    expected_version_sha256: str = Field(pattern=SHA)
    review_note: str = Field(min_length=8, max_length=2000)
    operator_attests_reviewed: Literal[True]


class DataPoolFindingRef(ProductModel):
    finding_id: str
    code: str
    severity: str
    finding_sha256: str = Field(pattern=SHA)


class DataPoolMemberRecord(ProductModel):
    sample_id: str
    source_task_id: str
    split: Literal["train", "val", "test"]
    category: str
    annotation_requirement: Literal[
        "REQUIRED", "OPTIONAL", "NOT_APPLICABLE", "UNKNOWN"
    ]
    readiness_state: str
    asset_sha256: str = Field(pattern=SHA)
    annotation_revision: int = Field(ge=0)
    annotation_sha256: str = Field(pattern=SHA)
    mask_sha256: str | None = Field(default=None, pattern=SHA)
    finding_refs: list[DataPoolFindingRef]
    repair_cause_codes: list[str]
    disposition: MemberDisposition
    repair_action: RepairAction
    repair_result: RepairResult
    decision_note: str
    label_truth_authority: Literal[False] = False


class DataPoolHumanReview(ProductModel):
    reviewer_name: str
    review_note: str
    reviewed_by: str
    operator_attests_reviewed: Literal[True]


class DataPoolVersionRecord(ProductModel):
    schema_version: Literal["visiondata-gate.data-pool-version.v1"] = (
        "visiondata-gate.data-pool-version.v1"
    )
    version_id: str
    pool_id: str
    version_number: int = Field(ge=1)
    parent_version_id: str | None
    parent_version_sha256: str | None = Field(default=None, pattern=SHA)
    source_task_id: str
    workspace_id: str
    project_id: str
    source_id: str
    snapshot_id: str
    snapshot_receipt_sha256: str = Field(pattern=SHA)
    batch_manifest_sha256: str = Field(pattern=SHA)
    batch_contract_sha256: str = Field(pattern=SHA)
    gate_result_sha256: str = Field(pattern=SHA)
    readiness_receipt_sha256: str = Field(pattern=SHA)
    preflight_receipt_sha256: str | None = Field(default=None, pattern=SHA)
    status: VersionStatus
    qualified_count: int = Field(ge=0)
    repair_count: int = Field(ge=0)
    hold_count: int = Field(ge=0)
    members: list[DataPoolMemberRecord]
    global_finding_refs: list[DataPoolFindingRef]
    unmapped_finding_refs: list[DataPoolFindingRef]
    readiness_blockers: list[str]
    human_review: DataPoolHumanReview
    created_at: str
    label_truth_authority: Literal[False] = False
    training_ingestion_allowed: Literal[False] = False
    production_release_allowed: Literal[False] = False
    receipt_sha256: str = Field(pattern=SHA)

    @model_validator(mode="after")
    def validate_counts(self) -> "DataPoolVersionRecord":
        expected = (
            sum(item.disposition == "QUALIFIED_CANDIDATE" for item in self.members),
            sum(item.disposition == "REPAIR_REQUIRED" for item in self.members),
            sum(item.disposition == "UNVERIFIED_HOLD" for item in self.members),
        )
        if expected != (self.qualified_count, self.repair_count, self.hold_count):
            raise ValueError("data-pool counts do not match the member ledger")
        return self


class DataPoolRecord(ProductModel):
    schema_version: Literal["visiondata-gate.data-pool.v1"] = (
        "visiondata-gate.data-pool.v1"
    )
    pool_id: str
    workspace_id: str
    project_id: str
    origin_task_id: str
    current_task_id: str
    origin_source_id: str
    current_source_id: str
    origin_snapshot_id: str
    current_snapshot_id: str
    version_ids: list[str]
    current_version_id: str
    created_by: str
    created_at: str
    label_truth_authority: Literal[False] = False
    production_release_allowed: Literal[False] = False
    receipt_sha256: str = Field(pattern=SHA)


class DataPoolProjection(ProductModel):
    schema_version: Literal["visiondata-gate.data-pool-projection.v1"] = (
        "visiondata-gate.data-pool-projection.v1"
    )
    pool: DataPoolRecord
    current_version: DataPoolVersionRecord
    read_status: Literal["CURRENT", "STALE_HOLD"]
    stale_reasons: list[str]
    training_ingestion_allowed: Literal[False] = False
    production_release_allowed: Literal[False] = False
    receipt_sha256: str = Field(pattern=SHA)


class DataPoolVersionProjection(ProductModel):
    schema_version: Literal["visiondata-gate.data-pool-version-projection.v1"] = (
        "visiondata-gate.data-pool-version-projection.v1"
    )
    version: DataPoolVersionRecord
    read_status: Literal["CURRENT", "STALE_HOLD"]
    stale_reasons: list[str]
    training_ingestion_allowed: Literal[False] = False
    production_release_allowed: Literal[False] = False
    receipt_sha256: str = Field(pattern=SHA)


class DataPoolDerivationRecord(ProductModel):
    schema_version: Literal["visiondata-gate.data-pool-derivation.v1"] = (
        "visiondata-gate.data-pool-derivation.v1"
    )
    derivation_id: str
    pool_id: str
    version_id: str
    workspace_id: str
    project_id: str
    source_task_id: str
    qualified_sample_ids: list[str]
    excluded_sample_ids: list[str]
    materialization_mode: Literal[
        "FULL_SNAPSHOT_REFERENCE", "DERIVED_QUALIFIED_SUBSET"
    ]
    parent_source_id: str
    derived_source_id: str | None
    derived_snapshot_id: str
    derived_snapshot_receipt_sha256: str | None = Field(default=None, pattern=SHA)
    new_source_authorization_created: bool
    new_gate_required: bool
    plan_approval_required: bool
    new_gate_status: Literal["NOT_APPLICABLE", "NOT_STARTED"]
    source_authorization_status: Literal["ACTIVE"]
    created_by: str
    created_at: str
    human_review_note: str
    training_ingestion_allowed: Literal[False] = False
    label_truth_authority: Literal[False] = False
    production_release_allowed: Literal[False] = False
    receipt_sha256: str = Field(pattern=SHA)

    @model_validator(mode="after")
    def validate_mode(self) -> "DataPoolDerivationRecord":
        subset = self.materialization_mode == "DERIVED_QUALIFIED_SUBSET"
        derived = (
            self.derived_source_id is not None
            and self.derived_snapshot_receipt_sha256 is not None
            and self.new_source_authorization_created
            and self.new_gate_required
            and self.plan_approval_required
            and self.new_gate_status == "NOT_STARTED"
        )
        if subset != derived:
            raise ValueError("derivation mode and authority fields diverge")
        if not subset and self.new_gate_status != "NOT_APPLICABLE":
            raise ValueError("full snapshot references cannot claim a new Gate")
        return self


class DataPoolListReceipt(ProductModel):
    schema_version: Literal["visiondata-gate.data-pool-list.v1"] = (
        "visiondata-gate.data-pool-list.v1"
    )
    task_id: str
    workspace_id: str
    project_id: str
    items: list[DataPoolProjection]
    receipt_sha256: str = Field(pattern=SHA)


class DataPoolOperationReceipt(ProductModel):
    schema_version: Literal["visiondata-gate.data-pool-operation.v1"] = (
        "visiondata-gate.data-pool-operation.v1"
    )
    project_id: str
    operation: Literal["create", "version", "derive"]
    target_id: str
    request_key: str
    lookup_status: Literal["FOUND", "NOT_FOUND"]
    execution_status: Literal["COMPLETED", "UNKNOWN_NOT_PROOF_OF_NO_WRITE"]
    result_type: Literal["pool", "version", "derivation"] | None
    result_id: str | None
    current_result: dict[str, Any] | None
    result_semantics: Literal["CURRENT_RESULT"] = "CURRENT_RESULT"
    automatic_retry_allowed: Literal[False] = False
    receipt_sha256: str = Field(pattern=SHA)


def _sha(value: Any) -> str:
    return hashlib.sha256(canonical_jcs_bytes(value)).hexdigest()


def _seal(value: dict[str, Any]) -> dict[str, Any]:
    stable = {key: item for key, item in value.items() if key != "receipt_sha256"}
    return {**stable, "receipt_sha256": _sha(stable)}


def _seal_as(model: type[ProductModel], stable: dict[str, Any]) -> dict[str, Any]:
    return model.model_validate(_seal(stable)).model_dump(mode="json")


def _verify_record(value: dict[str, Any], model: type[ProductModel]) -> dict[str, Any]:
    record = model.model_validate(value).model_dump(mode="json")
    expected = _seal(record)["receipt_sha256"]
    if not hmac.compare_digest(record["receipt_sha256"], expected):
        raise DataPoolError("DATA_POOL_RECORD_INTEGRITY_HOLD")
    return record


def _now() -> str:
    return datetime.now(UTC).isoformat(timespec="milliseconds")


def _value(value: Any) -> Any:
    return getattr(value, "value", value)


def _record_id(prefix: str, payload: dict[str, Any]) -> str:
    return prefix + "_" + _sha(payload)[:20]


@dataclass(frozen=True)
class FreshDataPoolContext:
    pool: dict[str, Any]
    version: dict[str, Any]
    task: Any
    source_root: Path
    snapshot: OperatorProjectSnapshotReceipt
    manifest: Any
    contract: Any
    gate: Any
    readiness: dict[str, Any]


@dataclass(frozen=True)
class _TaskContext:
    task: Any
    source_root: Path
    snapshot: OperatorProjectSnapshotReceipt
    manifest: Any
    contract: Any
    gate: Any
    readiness: dict[str, Any]
    source: Any


class DataPoolService:
    def __init__(self, product: Any) -> None:
        self.product = product

    @staticmethod
    def _ensure_tables(connection: Any) -> None:
        connection.executescript(
            """
            CREATE TABLE IF NOT EXISTS governed_data_pools_v1 (
                pool_id TEXT PRIMARY KEY,
                origin_task_id TEXT NOT NULL UNIQUE,
                current_task_id TEXT NOT NULL,
                workspace_id TEXT NOT NULL,
                project_id TEXT NOT NULL,
                record_json TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS governed_data_pool_versions_v1 (
                version_id TEXT PRIMARY KEY,
                pool_id TEXT NOT NULL,
                version_number INTEGER NOT NULL,
                source_task_id TEXT NOT NULL,
                actor_id TEXT NOT NULL,
                request_key TEXT NOT NULL,
                request_sha256 TEXT NOT NULL,
                record_json TEXT NOT NULL,
                UNIQUE(pool_id, version_number),
                UNIQUE(pool_id, actor_id, request_key)
            );
            CREATE TABLE IF NOT EXISTS governed_data_pool_derivations_v1 (
                derivation_id TEXT PRIMARY KEY,
                pool_id TEXT NOT NULL,
                version_id TEXT NOT NULL UNIQUE,
                actor_id TEXT NOT NULL,
                request_key TEXT NOT NULL,
                request_sha256 TEXT NOT NULL,
                record_json TEXT NOT NULL,
                UNIQUE(version_id, actor_id, request_key)
            );
            CREATE TABLE IF NOT EXISTS governed_data_pool_operations_v1 (
                workspace_id TEXT NOT NULL,
                project_id TEXT NOT NULL,
                actor_id TEXT NOT NULL,
                operation TEXT NOT NULL,
                target_id TEXT NOT NULL,
                request_key TEXT NOT NULL,
                request_sha256 TEXT NOT NULL,
                result_type TEXT NOT NULL,
                result_id TEXT NOT NULL,
                PRIMARY KEY (
                    workspace_id, actor_id, operation, target_id, request_key
                )
            );
            """
        )

    def _task_context(self, actor: str, task_id: str) -> _TaskContext:
        task = self.product.store.get_task(actor, task_id)
        if task.source_id is None:
            raise DataPoolError("SOURCE_AUTHORIZATION_REQUIRED")
        source = self.product.store.get_local_source_authorization(
            actor, task.source_id
        )
        if source.status != "active":
            raise DataPoolError("SOURCE_AUTHORIZATION_INACTIVE")
        context_task, _batch_root, manifest, contract, gate = (
            self.product._annotation_context(actor, task_id)
        )
        visual_task, source_root, snapshot, _profile = (
            self.product._operator_snapshot_visual_context(actor, task_id)
        )
        for candidate in (context_task, visual_task):
            if any(
                getattr(candidate, field) != getattr(task, field)
                for field in ("task_id", "workspace_id", "project_id", "source_id")
            ):
                raise DataPoolError("FROZEN_CONTEXT_IDENTITY_HOLD")
        if (
            snapshot.workspace_id != task.workspace_id
            or snapshot.project_id != task.project_id
        ):
            raise DataPoolError("SNAPSHOT_SCOPE_HOLD")
        readiness = learning_readiness(self.product, actor, task_id)
        if not isinstance(readiness, dict) or not isinstance(
            readiness.get("receipt_sha256"), str
        ):
            raise DataPoolError("READINESS_UNAVAILABLE")
        if not hmac.compare_digest(
            readiness["receipt_sha256"], _seal(readiness)["receipt_sha256"]
        ):
            raise DataPoolError("READINESS_INTEGRITY_HOLD")
        return _TaskContext(
            task=task,
            source_root=source_root,
            snapshot=snapshot,
            manifest=manifest,
            contract=contract,
            gate=gate,
            readiness=readiness,
            source=source,
        )

    @staticmethod
    def _read_json(row: Any, model: type[ProductModel]) -> dict[str, Any]:
        try:
            raw = json.loads(row["record_json"])
        except (KeyError, TypeError, json.JSONDecodeError) as error:
            raise DataPoolError("DATA_POOL_RECORD_INTEGRITY_HOLD") from error
        return _verify_record(raw, model)

    def _pool_row(self, connection: Any, pool_id: str) -> Any:
        self._ensure_tables(connection)
        row = connection.execute(
            "SELECT * FROM governed_data_pools_v1 WHERE pool_id=?", (pool_id,)
        ).fetchone()
        if row is None:
            raise NotFoundError("data pool not found")
        return row

    def _version_row(self, connection: Any, version_id: str) -> Any:
        self._ensure_tables(connection)
        row = connection.execute(
            "SELECT * FROM governed_data_pool_versions_v1 WHERE version_id=?",
            (version_id,),
        ).fetchone()
        if row is None:
            raise NotFoundError("data pool version not found")
        return row

    def _derivation_row(self, connection: Any, derivation_id: str) -> Any:
        self._ensure_tables(connection)
        row = connection.execute(
            "SELECT * FROM governed_data_pool_derivations_v1 WHERE derivation_id=?",
            (derivation_id,),
        ).fetchone()
        if row is None:
            raise NotFoundError("data pool derivation not found")
        return row

    @staticmethod
    def _assert_active_source(connection: Any, source_id: str) -> None:
        row = connection.execute(
            "SELECT status, authorization_valid_until "
            "FROM local_source_authorizations WHERE source_id=?",
            (source_id,),
        ).fetchone()
        if row is None or row["status"] != "active":
            raise DataPoolError("SOURCE_AUTHORIZATION_INACTIVE")
        valid_until = row["authorization_valid_until"]
        if valid_until and datetime.fromisoformat(
            str(valid_until).replace("Z", "+00:00")
        ) <= datetime.now(UTC):
            raise DataPoolError("SOURCE_AUTHORIZATION_INACTIVE")

    def _operation(
        self,
        connection: Any,
        *,
        workspace_id: str,
        actor: str,
        operation: str,
        target_id: str,
        request_key: str,
    ) -> Any:
        self._ensure_tables(connection)
        return connection.execute(
            """
            SELECT * FROM governed_data_pool_operations_v1
            WHERE workspace_id=? AND actor_id=? AND operation=?
              AND target_id=? AND request_key=?
            """,
            (workspace_id, actor, operation, target_id, request_key),
        ).fetchone()

    @staticmethod
    def _check_replay(row: Any, request_sha256: str) -> tuple[str, str] | None:
        if row is None:
            return None
        if not hmac.compare_digest(str(row["request_sha256"]), request_sha256):
            raise DataPoolError("IDEMPOTENCY_CONFLICT")
        return str(row["result_type"]), str(row["result_id"])

    @staticmethod
    def _insert_operation(
        connection: Any,
        *,
        workspace_id: str,
        project_id: str,
        actor: str,
        operation: str,
        target_id: str,
        request_key: str,
        request_sha256: str,
        result_type: str,
        result_id: str,
    ) -> None:
        connection.execute(
            """
            INSERT INTO governed_data_pool_operations_v1 VALUES (?,?,?,?,?,?,?,?,?)
            """,
            (
                workspace_id,
                project_id,
                actor,
                operation,
                target_id,
                request_key,
                request_sha256,
                result_type,
                result_id,
            ),
        )

    @staticmethod
    def _record_json(value: dict[str, Any]) -> str:
        return json.dumps(value, ensure_ascii=False, separators=(",", ":"))

    @staticmethod
    def _finding_refs(values: Any) -> list[dict[str, Any]]:
        try:
            return [
                DataPoolFindingRef.model_validate(item).model_dump(mode="json")
                for item in values
            ]
        except (TypeError, ValueError) as error:
            raise DataPoolError("READINESS_FINDING_INTEGRITY_HOLD") from error

    def _build_version(
        self,
        *,
        actor: str,
        pool_id: str,
        version_number: int,
        parent_version: dict[str, Any] | None,
        context: _TaskContext,
        request: CreateDataPoolRequest,
    ) -> dict[str, Any]:
        readiness = context.readiness
        if not hmac.compare_digest(
            request.expected_readiness_sha256, readiness["receipt_sha256"]
        ):
            raise DataPoolError("STALE_READINESS")
        decisions = {item.sample_id: item for item in request.members}
        samples = {item.sample_id: item for item in context.manifest.samples}
        assets = {item.asset_id: item for item in context.snapshot.assets}
        projected = {item["sample_id"]: item for item in readiness["members"]}
        if not (
            set(decisions) == set(samples) == set(assets) == set(projected)
            and len(decisions) == len(request.members)
        ):
            raise DataPoolError("MEMBER_SET_MISMATCH")

        global_refs = self._finding_refs(readiness["global_findings"])
        unmapped_refs = self._finding_refs(readiness["unmapped_finding_refs"])
        blockers = sorted(set(readiness["blockers"]))
        unsafe_blockers = sorted(
            set(blockers) - set(SAFE_MEMBER_COMPLEMENT_BLOCKERS)
        )
        global_hold = bool(
            readiness["projection_status"] != "VERIFIED"
            or global_refs
            or unmapped_refs
            or unsafe_blockers
        )
        mapped_finding_member_ids = {
            item["sample_id"] for item in readiness["members"] if item["finding_refs"]
        }
        member_records: list[dict[str, Any]] = []
        for sample_id in sorted(decisions):
            decision = decisions[sample_id]
            sample = samples[sample_id]
            asset = assets[sample_id]
            member = projected[sample_id]
            if (
                decision.expected_asset_sha256 != asset.source_sha256
                or decision.expected_annotation_revision != asset.annotation_revision
                or not hmac.compare_digest(
                    decision.expected_annotation_sha256,
                    asset.annotation_document_sha256,
                )
            ):
                raise DataPoolError("MEMBER_IDENTITY_STALE")
            finding_refs = self._finding_refs(member["finding_refs"])
            readiness_state = str(member["readiness_state"])
            reviewed_empty_annotation = (
                readiness_state == "MASK_REQUIRED_FOR_REFERENCE_TRAINER"
                and _value(context.gate.decision) == "PASS"
                and member["annotation_requirement"] in {"OPTIONAL", "NOT_APPLICABLE"}
                and asset.annotation_count == 0
                and asset.mask_relative_path is None
                and asset.mask_sha256 is None
            )
            clean_batch_complement = (
                readiness_state == "BLOCKED_BY_BATCH"
                and readiness["preflight_eligibility"] == "HOLD"
                and blockers == ["GATE_NOT_PASS"]
                and bool(mapped_finding_member_ids - {sample_id})
            )
            qualified_by_evidence = (
                not global_hold
                and not finding_refs
                and (
                    readiness_state in QUALIFIED_READINESS_STATES
                    or reviewed_empty_annotation
                    or clean_batch_complement
                )
            )
            if (
                decision.disposition == "QUALIFIED_CANDIDATE"
                and not qualified_by_evidence
            ):
                raise DataPoolError("QUALIFICATION_REQUIRES_MEMBER_EVIDENCE")
            if decision.disposition == "REPAIR_REQUIRED" and not finding_refs:
                raise DataPoolError("REPAIR_REQUIRES_MAPPED_FINDING")
            if decision.disposition == "UNVERIFIED_HOLD":
                causes = {
                    *(item["code"] for item in finding_refs),
                    *(item["code"] for item in global_refs),
                    *unsafe_blockers,
                    f"READINESS_{readiness_state}",
                }
            elif decision.disposition == "REPAIR_REQUIRED":
                causes = {item["code"] for item in finding_refs}
            else:
                causes = set()
            record = DataPoolMemberRecord(
                sample_id=sample_id,
                source_task_id=context.task.task_id,
                split=sample.split,
                category=sample.category,
                annotation_requirement=member["annotation_requirement"],
                readiness_state=readiness_state,
                asset_sha256=asset.source_sha256,
                annotation_revision=asset.annotation_revision,
                annotation_sha256=asset.annotation_document_sha256,
                mask_sha256=asset.mask_sha256,
                finding_refs=finding_refs,
                repair_cause_codes=sorted(causes),
                disposition=decision.disposition,
                repair_action=decision.repair_action,
                repair_result=decision.repair_result,
                decision_note=decision.decision_note,
                label_truth_authority=False,
            ).model_dump(mode="json")
            member_records.append(record)

        qualified = sum(
            item["disposition"] == "QUALIFIED_CANDIDATE" for item in member_records
        )
        repair = sum(item["disposition"] == "REPAIR_REQUIRED" for item in member_records)
        hold = sum(item["disposition"] == "UNVERIFIED_HOLD" for item in member_records)
        status: VersionStatus
        if hold:
            status = "REVIEWED_WITH_HOLD"
        elif repair:
            status = "REVIEWED_ACTION_REQUIRED"
        else:
            status = "REVIEWED_ALL_QUALIFIED_REFERENCE"
        parent_id = parent_version["version_id"] if parent_version else None
        parent_sha = parent_version["receipt_sha256"] if parent_version else None
        request_sha = _sha(request.model_dump(mode="json"))
        version_id = _record_id(
            "poolv",
            {
                "pool_id": pool_id,
                "version_number": version_number,
                "parent_version_sha256": parent_sha,
                "source_task_id": context.task.task_id,
                "readiness_receipt_sha256": readiness["receipt_sha256"],
                "request_sha256": request_sha,
            },
        )
        stable = {
            "schema_version": "visiondata-gate.data-pool-version.v1",
            "version_id": version_id,
            "pool_id": pool_id,
            "version_number": version_number,
            "parent_version_id": parent_id,
            "parent_version_sha256": parent_sha,
            "source_task_id": context.task.task_id,
            "workspace_id": context.task.workspace_id,
            "project_id": context.task.project_id,
            "source_id": context.task.source_id,
            "snapshot_id": context.snapshot.snapshot_id,
            "snapshot_receipt_sha256": context.snapshot.receipt_sha256,
            "batch_manifest_sha256": context.snapshot.batch_manifest_sha256,
            "batch_contract_sha256": context.snapshot.batch_contract_sha256,
            "gate_result_sha256": _sha(context.gate.model_dump(mode="json")),
            "readiness_receipt_sha256": readiness["receipt_sha256"],
            "preflight_receipt_sha256": readiness["preflight_receipt_sha256"],
            "status": status,
            "qualified_count": qualified,
            "repair_count": repair,
            "hold_count": hold,
            "members": member_records,
            "global_finding_refs": global_refs,
            "unmapped_finding_refs": unmapped_refs,
            "readiness_blockers": blockers,
            "human_review": {
                "reviewer_name": request.reviewer_name,
                "review_note": request.review_note,
                "reviewed_by": actor,
                "operator_attests_reviewed": True,
            },
            "created_at": _now(),
            "label_truth_authority": False,
            "training_ingestion_allowed": False,
            "production_release_allowed": False,
        }
        return _seal_as(DataPoolVersionRecord, stable)

    @staticmethod
    def _freshness_reasons(
        pool: dict[str, Any],
        version: dict[str, Any],
        context: _TaskContext,
    ) -> list[str]:
        reasons: list[str] = []
        expected = {
            "source_task_id": context.task.task_id,
            "workspace_id": context.task.workspace_id,
            "project_id": context.task.project_id,
            "source_id": context.task.source_id,
            "snapshot_id": context.snapshot.snapshot_id,
            "snapshot_receipt_sha256": context.snapshot.receipt_sha256,
            "batch_manifest_sha256": context.snapshot.batch_manifest_sha256,
            "batch_contract_sha256": context.snapshot.batch_contract_sha256,
            "gate_result_sha256": _sha(context.gate.model_dump(mode="json")),
            "readiness_receipt_sha256": context.readiness["receipt_sha256"],
        }
        for field, value in expected.items():
            if version[field] != value:
                reasons.append(f"{field.upper()}_DRIFT")
        if (
            pool["workspace_id"] != context.task.workspace_id
            or pool["project_id"] != context.task.project_id
        ):
            reasons.append("POOL_SCOPE_DRIFT")
        if version["version_id"] == pool["current_version_id"] and (
            pool["current_task_id"] != context.task.task_id
            or pool["current_source_id"] != context.task.source_id
            or pool["current_snapshot_id"] != context.snapshot.snapshot_id
        ):
            reasons.append("POOL_CURRENT_BINDING_DRIFT")
        return sorted(set(reasons))

    def create_pool(
        self, actor: str, task_id: str, request: CreateDataPoolRequest
    ) -> dict[str, Any]:
        request = CreateDataPoolRequest.model_validate(request.model_dump(mode="json"))
        context = self._task_context(actor, task_id)
        request_sha = _sha(request.model_dump(mode="json"))
        pool_id = _record_id(
            "pool",
            {
                "task_id": task_id,
                "workspace_id": context.task.workspace_id,
                "project_id": context.task.project_id,
                "source_id": context.task.source_id,
                "snapshot_receipt_sha256": context.snapshot.receipt_sha256,
            },
        )
        with self.product.store._connection(immediate=True) as connection:
            self._ensure_tables(connection)
            self.product.store._require_membership(
                connection, context.task.workspace_id, actor
            )
            self._assert_active_source(connection, context.task.source_id)
            replay = self._check_replay(
                self._operation(
                    connection,
                    workspace_id=context.task.workspace_id,
                    actor=actor,
                    operation="create",
                    target_id=task_id,
                    request_key=request.request_key,
                ),
                request_sha,
            )
            if replay is not None:
                replay_pool_id = replay[1]
            else:
                existing = connection.execute(
                    "SELECT pool_id FROM governed_data_pools_v1 WHERE origin_task_id=?",
                    (task_id,),
                ).fetchone()
                if existing is not None:
                    raise DataPoolError("DATA_POOL_ALREADY_EXISTS_USE_NEW_VERSION")
                version = self._build_version(
                    actor=actor,
                    pool_id=pool_id,
                    version_number=1,
                    parent_version=None,
                    context=context,
                    request=request,
                )
                created_at = _now()
                pool = _seal_as(
                    DataPoolRecord,
                    {
                        "schema_version": "visiondata-gate.data-pool.v1",
                        "pool_id": pool_id,
                        "workspace_id": context.task.workspace_id,
                        "project_id": context.task.project_id,
                        "origin_task_id": task_id,
                        "current_task_id": task_id,
                        "origin_source_id": context.task.source_id,
                        "current_source_id": context.task.source_id,
                        "origin_snapshot_id": context.snapshot.snapshot_id,
                        "current_snapshot_id": context.snapshot.snapshot_id,
                        "version_ids": [version["version_id"]],
                        "current_version_id": version["version_id"],
                        "created_by": actor,
                        "created_at": created_at,
                        "label_truth_authority": False,
                        "production_release_allowed": False,
                    },
                )
                connection.execute(
                    "INSERT INTO governed_data_pool_versions_v1 VALUES (?,?,?,?,?,?,?,?)",
                    (
                        version["version_id"],
                        pool_id,
                        1,
                        task_id,
                        actor,
                        request.request_key,
                        request_sha,
                        self._record_json(version),
                    ),
                )
                connection.execute(
                    "INSERT INTO governed_data_pools_v1 VALUES (?,?,?,?,?,?)",
                    (
                        pool_id,
                        task_id,
                        task_id,
                        context.task.workspace_id,
                        context.task.project_id,
                        self._record_json(pool),
                    ),
                )
                self._insert_operation(
                    connection,
                    workspace_id=context.task.workspace_id,
                    project_id=context.task.project_id,
                    actor=actor,
                    operation="create",
                    target_id=task_id,
                    request_key=request.request_key,
                    request_sha256=request_sha,
                    result_type="pool",
                    result_id=pool_id,
                )
                replay_pool_id = pool_id
        return self.get_pool(actor, replay_pool_id)

    def get_pool(self, actor: str, pool_id: str) -> dict[str, Any]:
        with self.product.store._connection() as connection:
            pool_row = self._pool_row(connection, pool_id)
            self.product.store._require_membership(
                connection, str(pool_row["workspace_id"]), actor
            )
            pool = self._read_json(pool_row, DataPoolRecord)
            version = self._read_json(
                self._version_row(connection, pool["current_version_id"]),
                DataPoolVersionRecord,
            )
        context = self._task_context(actor, version["source_task_id"])
        reasons = self._freshness_reasons(pool, version, context)
        stable = {
            "schema_version": "visiondata-gate.data-pool-projection.v1",
            "pool": pool,
            "current_version": version,
            "read_status": "STALE_HOLD" if reasons else "CURRENT",
            "stale_reasons": reasons,
            "training_ingestion_allowed": False,
            "production_release_allowed": False,
        }
        return _seal_as(DataPoolProjection, stable)

    def get_version(self, actor: str, version_id: str) -> dict[str, Any]:
        with self.product.store._connection() as connection:
            version_row = self._version_row(connection, version_id)
            version = self._read_json(version_row, DataPoolVersionRecord)
            pool_row = self._pool_row(connection, version["pool_id"])
            self.product.store._require_membership(
                connection, str(pool_row["workspace_id"]), actor
            )
            pool = self._read_json(pool_row, DataPoolRecord)
        context = self._task_context(actor, version["source_task_id"])
        reasons = self._freshness_reasons(pool, version, context)
        return _seal_as(
            DataPoolVersionProjection,
            {
                "schema_version": (
                    "visiondata-gate.data-pool-version-projection.v1"
                ),
                "version": version,
                "read_status": "STALE_HOLD" if reasons else "CURRENT",
                "stale_reasons": reasons,
                "training_ingestion_allowed": False,
                "production_release_allowed": False,
            },
        )

    def list_task_pools(self, actor: str, task_id: str) -> dict[str, Any]:
        task = self.product.store.get_task(actor, task_id)
        with self.product.store._connection() as connection:
            self._ensure_tables(connection)
            self.product.store._require_membership(
                connection, task.workspace_id, actor
            )
            rows = connection.execute(
                """
                SELECT pool_id FROM governed_data_pools_v1
                WHERE origin_task_id=? OR current_task_id=?
                ORDER BY pool_id
                """,
                (task_id, task_id),
            ).fetchall()
        items = [self.get_pool(actor, str(row["pool_id"])) for row in rows]
        return _seal_as(
            DataPoolListReceipt,
            {
                "schema_version": "visiondata-gate.data-pool-list.v1",
                "task_id": task_id,
                "workspace_id": task.workspace_id,
                "project_id": task.project_id,
                "items": items,
            },
        )

    def create_version(
        self,
        actor: str,
        pool_id: str,
        request: CreateDataPoolVersionRequest,
    ) -> dict[str, Any]:
        request = CreateDataPoolVersionRequest.model_validate(
            request.model_dump(mode="json")
        )
        current_projection = self.get_pool(actor, pool_id)
        if current_projection["read_status"] != "CURRENT":
            raise DataPoolError("STALE_DATA_POOL")
        pool = current_projection["pool"]
        parent = current_projection["current_version"]
        if (
            not hmac.compare_digest(
                request.expected_pool_sha256, pool["receipt_sha256"]
            )
            or not hmac.compare_digest(
                request.expected_parent_version_sha256, parent["receipt_sha256"]
            )
        ):
            raise DataPoolError("STALE_DATA_POOL_VERSION")
        source_task_id = request.source_task_id or parent["source_task_id"]
        context = self._task_context(actor, source_task_id)
        if (
            context.task.workspace_id != pool["workspace_id"]
            or context.task.project_id != pool["project_id"]
        ):
            raise DataPoolError("CROSS_SCOPE_VERSION_FORBIDDEN")
        request_sha = _sha(request.model_dump(mode="json"))
        with self.product.store._connection(immediate=True) as connection:
            self._ensure_tables(connection)
            self.product.store._require_membership(
                connection, pool["workspace_id"], actor
            )
            self._assert_active_source(connection, context.task.source_id)
            replay = self._check_replay(
                self._operation(
                    connection,
                    workspace_id=pool["workspace_id"],
                    actor=actor,
                    operation="version",
                    target_id=pool_id,
                    request_key=request.request_key,
                ),
                request_sha,
            )
            if replay is None:
                stored_pool = self._read_json(
                    self._pool_row(connection, pool_id), DataPoolRecord
                )
                if not hmac.compare_digest(
                    stored_pool["receipt_sha256"], pool["receipt_sha256"]
                ):
                    raise DataPoolError("STALE_DATA_POOL")
                version = self._build_version(
                    actor=actor,
                    pool_id=pool_id,
                    version_number=parent["version_number"] + 1,
                    parent_version=parent,
                    context=context,
                    request=request,
                )
                updated_pool = _seal_as(
                    DataPoolRecord,
                    {
                        **{
                            key: value
                            for key, value in stored_pool.items()
                            if key != "receipt_sha256"
                        },
                        "current_task_id": context.task.task_id,
                        "current_source_id": context.task.source_id,
                        "current_snapshot_id": context.snapshot.snapshot_id,
                        "version_ids": [
                            *stored_pool["version_ids"],
                            version["version_id"],
                        ],
                        "current_version_id": version["version_id"],
                    },
                )
                connection.execute(
                    "INSERT INTO governed_data_pool_versions_v1 VALUES (?,?,?,?,?,?,?,?)",
                    (
                        version["version_id"],
                        pool_id,
                        version["version_number"],
                        context.task.task_id,
                        actor,
                        request.request_key,
                        request_sha,
                        self._record_json(version),
                    ),
                )
                connection.execute(
                    """
                    UPDATE governed_data_pools_v1
                    SET current_task_id=?, record_json=? WHERE pool_id=?
                    """,
                    (
                        context.task.task_id,
                        self._record_json(updated_pool),
                        pool_id,
                    ),
                )
                self._insert_operation(
                    connection,
                    workspace_id=pool["workspace_id"],
                    project_id=pool["project_id"],
                    actor=actor,
                    operation="version",
                    target_id=pool_id,
                    request_key=request.request_key,
                    request_sha256=request_sha,
                    result_type="version",
                    result_id=version["version_id"],
                )
        return self.get_pool(actor, pool_id)

    def _recover_or_materialize_subset(
        self,
        context: _TaskContext,
        retained_ids: set[str],
        *,
        created_at: str,
    ) -> MaterializedOperatorProjectSnapshot:
        identity = {
            "schema_version": "visiondata-gate.operator-snapshot-subset.v1",
            "parent_receipt_sha256": context.snapshot.receipt_sha256,
            "retained_asset_ids": sorted(retained_ids),
        }
        snapshot_id = "opsnap_" + _sha(identity)[:20]
        snapshots_root = (
            self.product.product_root / "operator_project_snapshots"
        ).resolve(strict=True)
        destination = snapshots_root / snapshot_id
        if not destination.exists():
            return materialize_operator_snapshot_subset(
                context.source_root,
                snapshots_root=snapshots_root,
                retained_asset_ids=retained_ids,
                expected_receipt_sha256=context.snapshot.receipt_sha256,
                created_at=created_at,
            )
        try:
            profile = profile_operator_project_snapshot(destination)
            receipt = OperatorProjectSnapshotReceipt.model_validate_json(
                (destination / "operator_project_snapshot_receipt.json").read_bytes()
            )
        except (OSError, ValueError) as error:
            raise DataPoolError("DERIVED_SNAPSHOT_PARTIAL_HOLD") from error
        parent_assets = {item.asset_id: item for item in context.snapshot.assets}
        if (
            receipt.snapshot_id != snapshot_id
            or {item.asset_id for item in receipt.assets} != retained_ids
            or any(item != parent_assets[item.asset_id] for item in receipt.assets)
        ):
            raise DataPoolError("DERIVED_SNAPSHOT_BINDING_HOLD")
        return MaterializedOperatorProjectSnapshot(destination, receipt, profile)

    def _authorize_subset_source(
        self,
        actor: str,
        context: _TaskContext,
        pool_id: str,
        subset: MaterializedOperatorProjectSnapshot,
    ) -> Any:
        normalized = os.path.normcase(str(subset.root)).replace("\\", "/")
        profile = dict(subset.source_profile)
        request = AuthorizeLocalSourceRequest(
            workspace_id=context.task.workspace_id,
            display_name=f"Data Pool {pool_id} qualified subset",
            root_path=str(subset.root),
            source_archive_sha256=subset.receipt.receipt_sha256,
            adapter_kind=LocalSourceAdapterKind.OPERATOR_PROJECT_SNAPSHOT,
            purpose=(
                "Private reviewed Data Pool subset pending an independent Gate run."
            ),
            rights_basis=context.source.rights_basis,
            residency="product_local_private_data_pool_subset",
            operator_attests_authorized_use=True,
            read_only=True,
            raw_redistribution_allowed=False,
            authorization_valid_until=context.source.authorization_valid_until,
            source_path_retention_policy=context.source.source_path_retention_policy,
            redacted_receipt_retention_days=(
                context.source.redacted_receipt_retention_days
            ),
            derived_artifact_retention_days=(
                context.source.derived_artifact_retention_days
            ),
            post_revocation_source_bytes=context.source.post_revocation_source_bytes,
        )
        source = self.product.store.create_local_source_authorization(
            actor,
            request,
            resolved_root=subset.root,
            root_path_sha256=hashlib.sha256(
                normalized.encode("utf-8")
            ).hexdigest(),
            data_profile=profile,
        )
        receipt_path = (
            self.product.product_root
            / "source_authorizations"
            / source.source_id
            / "authorization_receipt.json"
        )
        if not receipt_path.exists():
            write_canonical_json(receipt_path, source)
        for event in self.product.store.list_source_authorization_events(
            actor, source.source_id
        ):
            self.product._persist_source_authorization_event(event)
        return source

    def derive_version(
        self,
        actor: str,
        pool_id: str,
        version_id: str,
        request: DeriveDataPoolVersionRequest,
    ) -> dict[str, Any]:
        request = DeriveDataPoolVersionRequest.model_validate(
            request.model_dump(mode="json")
        )
        projection = self.get_pool(actor, pool_id)
        if projection["read_status"] != "CURRENT":
            raise DataPoolError("STALE_DATA_POOL")
        pool = projection["pool"]
        version = projection["current_version"]
        if version["version_id"] != version_id:
            raise DataPoolError("ONLY_CURRENT_VERSION_CAN_DERIVE")
        if (
            not hmac.compare_digest(
                request.expected_pool_sha256, pool["receipt_sha256"]
            )
            or not hmac.compare_digest(
                request.expected_version_sha256, version["receipt_sha256"]
            )
        ):
            raise DataPoolError("STALE_DATA_POOL_VERSION")
        request_sha = _sha(request.model_dump(mode="json"))
        with self.product.store._connection(immediate=True) as connection:
            self._ensure_tables(connection)
            self.product.store._require_membership(
                connection, pool["workspace_id"], actor
            )
            replay = self._check_replay(
                self._operation(
                    connection,
                    workspace_id=pool["workspace_id"],
                    actor=actor,
                    operation="derive",
                    target_id=version_id,
                    request_key=request.request_key,
                ),
                request_sha,
            )
        if replay is not None:
            return self.get_derivation(actor, replay[1])

        context = self._task_context(actor, version["source_task_id"])
        qualified = sorted(
            item["sample_id"]
            for item in version["members"]
            if item["disposition"] == "QUALIFIED_CANDIDATE"
        )
        all_ids = sorted(item.sample_id for item in context.manifest.samples)
        if not qualified:
            raise DataPoolError("NO_QUALIFIED_MEMBERS")
        if not set(qualified).issubset(set(all_ids)):
            raise DataPoolError("QUALIFIED_MEMBER_BINDING_HOLD")
        created_at = _now()
        derived_source = None
        if qualified == all_ids:
            mode = "FULL_SNAPSHOT_REFERENCE"
            derived_snapshot_id = context.snapshot.snapshot_id
            derived_snapshot_receipt_sha256 = None
            new_source_created = False
            new_gate_required = False
            plan_approval_required = False
            new_gate_status = "NOT_APPLICABLE"
        else:
            mode = "DERIVED_QUALIFIED_SUBSET"
            subset = self._recover_or_materialize_subset(
                context, set(qualified), created_at=created_at
            )
            derived_source = self._authorize_subset_source(
                actor, context, pool_id, subset
            )
            derived_snapshot_id = subset.receipt.snapshot_id
            derived_snapshot_receipt_sha256 = subset.receipt.receipt_sha256
            new_source_created = True
            new_gate_required = True
            plan_approval_required = True
            new_gate_status = "NOT_STARTED"
        derivation_id = _record_id(
            "poold",
            {
                "pool_id": pool_id,
                "version_id": version_id,
                "request_sha256": request_sha,
                "qualified_sample_ids": qualified,
            },
        )
        derivation = _seal_as(
            DataPoolDerivationRecord,
            {
                "schema_version": "visiondata-gate.data-pool-derivation.v1",
                "derivation_id": derivation_id,
                "pool_id": pool_id,
                "version_id": version_id,
                "workspace_id": pool["workspace_id"],
                "project_id": pool["project_id"],
                "source_task_id": version["source_task_id"],
                "qualified_sample_ids": qualified,
                "excluded_sample_ids": sorted(set(all_ids) - set(qualified)),
                "materialization_mode": mode,
                "parent_source_id": version["source_id"],
                "derived_source_id": (
                    derived_source.source_id if derived_source is not None else None
                ),
                "derived_snapshot_id": derived_snapshot_id,
                "derived_snapshot_receipt_sha256": derived_snapshot_receipt_sha256,
                "new_source_authorization_created": new_source_created,
                "new_gate_required": new_gate_required,
                "plan_approval_required": plan_approval_required,
                "new_gate_status": new_gate_status,
                "source_authorization_status": "ACTIVE",
                "created_by": actor,
                "created_at": created_at,
                "human_review_note": request.review_note,
                "training_ingestion_allowed": False,
                "label_truth_authority": False,
                "production_release_allowed": False,
            },
        )
        with self.product.store._connection(immediate=True) as connection:
            self._ensure_tables(connection)
            self.product.store._require_membership(
                connection, pool["workspace_id"], actor
            )
            self._assert_active_source(connection, version["source_id"])
            if derived_source is not None:
                self._assert_active_source(connection, derived_source.source_id)
            stored_pool = self._read_json(
                self._pool_row(connection, pool_id), DataPoolRecord
            )
            stored_version = self._read_json(
                self._version_row(connection, version_id), DataPoolVersionRecord
            )
            if (
                stored_pool["current_version_id"] != version_id
                or not hmac.compare_digest(
                    stored_pool["receipt_sha256"], pool["receipt_sha256"]
                )
                or not hmac.compare_digest(
                    stored_version["receipt_sha256"], version["receipt_sha256"]
                )
            ):
                raise DataPoolError("DATA_POOL_CHANGED_DURING_DERIVATION")
            replay = self._check_replay(
                self._operation(
                    connection,
                    workspace_id=pool["workspace_id"],
                    actor=actor,
                    operation="derive",
                    target_id=version_id,
                    request_key=request.request_key,
                ),
                request_sha,
            )
            if replay is None:
                existing = connection.execute(
                    "SELECT derivation_id FROM governed_data_pool_derivations_v1 "
                    "WHERE version_id=?",
                    (version_id,),
                ).fetchone()
                if existing is not None:
                    raise DataPoolError("DATA_POOL_VERSION_ALREADY_DERIVED")
                connection.execute(
                    "INSERT INTO governed_data_pool_derivations_v1 "
                    "VALUES (?,?,?,?,?,?,?)",
                    (
                        derivation_id,
                        pool_id,
                        version_id,
                        actor,
                        request.request_key,
                        request_sha,
                        self._record_json(derivation),
                    ),
                )
                self._insert_operation(
                    connection,
                    workspace_id=pool["workspace_id"],
                    project_id=pool["project_id"],
                    actor=actor,
                    operation="derive",
                    target_id=version_id,
                    request_key=request.request_key,
                    request_sha256=request_sha,
                    result_type="derivation",
                    result_id=derivation_id,
                )
        return self.get_derivation(actor, derivation_id)

    def get_derivation(self, actor: str, derivation_id: str) -> dict[str, Any]:
        with self.product.store._connection() as connection:
            row = self._derivation_row(connection, derivation_id)
            record = self._read_json(row, DataPoolDerivationRecord)
            pool_row = self._pool_row(connection, record["pool_id"])
            self.product.store._require_membership(
                connection, str(pool_row["workspace_id"]), actor
            )
        version_view = self.get_version(actor, record["version_id"])
        if version_view["read_status"] != "CURRENT":
            raise DataPoolError("STALE_DATA_POOL_VERSION")
        source_id = record["derived_source_id"] or record["parent_source_id"]
        source = self.product.store.get_local_source_authorization(actor, source_id)
        if source.status != "active":
            raise DataPoolError("SOURCE_AUTHORIZATION_INACTIVE")
        return record

    def read_operation(
        self,
        actor: str,
        project_id: str,
        operation: str,
        request_key: str,
        target_id: str,
    ) -> dict[str, Any]:
        if operation not in {"create", "version", "derive"}:
            raise DataPoolError("DATA_POOL_OPERATION_UNKNOWN")
        if (
            re.fullmatch(REQUEST_KEY, request_key) is None
            or re.fullmatch(SAFE_ID, target_id) is None
        ):
            raise DataPoolError("DATA_POOL_OPERATION_ID_INVALID")
        project = self.product.store.get_project(actor, project_id)
        with self.product.store._connection() as connection:
            self._ensure_tables(connection)
            self.product.store._require_membership(
                connection, project.workspace_id, actor
            )
            row = self._operation(
                connection,
                workspace_id=project.workspace_id,
                actor=actor,
                operation=operation,
                target_id=target_id,
                request_key=request_key,
            )
            if row is not None and row["project_id"] != project_id:
                raise NotFoundError("data pool operation not found")
        if row is None:
            stable = {
                "schema_version": "visiondata-gate.data-pool-operation.v1",
                "project_id": project_id,
                "operation": operation,
                "target_id": target_id,
                "request_key": request_key,
                "lookup_status": "NOT_FOUND",
                "execution_status": "UNKNOWN_NOT_PROOF_OF_NO_WRITE",
                "result_type": None,
                "result_id": None,
                "current_result": None,
                "result_semantics": "CURRENT_RESULT",
                "automatic_retry_allowed": False,
            }
            return _seal_as(DataPoolOperationReceipt, stable)
        result_type = str(row["result_type"])
        result_id = str(row["result_id"])
        if result_type == "pool":
            current = self.get_pool(actor, result_id)
        elif result_type == "version":
            current = self.get_version(actor, result_id)
        elif result_type == "derivation":
            current = self.get_derivation(actor, result_id)
        else:
            raise DataPoolError("DATA_POOL_OPERATION_RESULT_INVALID")
        return _seal_as(
            DataPoolOperationReceipt,
            {
                "schema_version": "visiondata-gate.data-pool-operation.v1",
                "project_id": project_id,
                "operation": operation,
                "target_id": target_id,
                "request_key": request_key,
                "lookup_status": "FOUND",
                "execution_status": "COMPLETED",
                "result_type": result_type,
                "result_id": result_id,
                "current_result": current,
                "result_semantics": "CURRENT_RESULT",
                "automatic_retry_allowed": False,
            },
        )


def load_fresh_data_pool_context(
    product: Any,
    actor: str,
    pool_id: str,
    version_id: str | None = None,
    *,
    require_current: bool = True,
    require_all_qualified: bool = False,
    require_gate_pass: bool = False,
) -> FreshDataPoolContext:
    """Return verified source facts for a downstream bridge, never raw DB trust."""

    service = DataPoolService(product)
    projection = service.get_pool(actor, pool_id)
    if projection["read_status"] != "CURRENT":
        raise DataPoolError("STALE_DATA_POOL")
    pool = projection["pool"]
    selected_version_id = version_id or pool["current_version_id"]
    if require_current and selected_version_id != pool["current_version_id"]:
        raise DataPoolError("NONCURRENT_DATA_POOL_VERSION")
    version_view = service.get_version(actor, selected_version_id)
    if version_view["read_status"] != "CURRENT":
        raise DataPoolError("STALE_DATA_POOL_VERSION")
    version = version_view["version"]
    if version["pool_id"] != pool_id:
        raise DataPoolError("DATA_POOL_VERSION_BINDING_HOLD")
    context = service._task_context(actor, version["source_task_id"])
    if require_all_qualified and (
        version["repair_count"] != 0
        or version["hold_count"] != 0
        or version["qualified_count"] != len(version["members"])
    ):
        raise DataPoolError("DATA_POOL_NOT_ALL_QUALIFIED")
    if require_gate_pass:
        readiness = context.readiness
        strict = (
            _value(context.gate.decision) == "PASS"
            and readiness["projection_status"] == "VERIFIED"
            and readiness["preflight_eligibility"] == "READY_FOR_OFFLINE_HANDOFF"
            and not readiness["blockers"]
            and not readiness["global_findings"]
            and not readiness["unmapped_finding_refs"]
            and all(
                not item["finding_refs"]
                and item["readiness_state"]
                in {
                    "GATE_ELIGIBLE_NOT_TRAINING_APPROVED",
                    "MASK_REQUIRED_FOR_REFERENCE_TRAINER",
                }
                for item in readiness["members"]
            )
        )
        if not strict:
            raise DataPoolError("DATA_POOL_GATE_PASS_REQUIRED")
    return FreshDataPoolContext(
        pool=pool,
        version=version,
        task=context.task,
        source_root=context.source_root,
        snapshot=context.snapshot,
        manifest=context.manifest,
        contract=context.contract,
        gate=context.gate,
        readiness=context.readiness,
    )


__all__ = [
    "CreateDataPoolRequest",
    "CreateDataPoolVersionRequest",
    "DataPoolDerivationRecord",
    "DataPoolError",
    "DataPoolListReceipt",
    "DataPoolMemberDecision",
    "DataPoolMemberRecord",
    "DataPoolOperationReceipt",
    "DataPoolProjection",
    "DataPoolRecord",
    "DataPoolService",
    "DataPoolVersionProjection",
    "DataPoolVersionRecord",
    "DeriveDataPoolVersionRequest",
    "FreshDataPoolContext",
    "load_fresh_data_pool_context",
]
