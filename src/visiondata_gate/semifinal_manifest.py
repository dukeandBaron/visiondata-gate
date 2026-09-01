"""Authoritative read-only projection of the isolated semifinal demo manifest.

The demo producer and the API must not maintain separate acceptance rules.  This
module owns the frozen manifest contract, reconciles it with the ProductRoot
actually served by :class:`ProductService`, and emits a bounded RFC 8785 JCS
projection for the reviewer UI.  Missing or drifted evidence is represented as
an explicit HOLD projection; no manifest fields are returned until both passes
have succeeded.
"""

from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
from pathlib import Path
import re
from typing import Any, Literal

from pydantic import Field

from .audit_envelope import canonical_jcs_bytes
from .evidence import canonical_json_bytes
from .operator_workspace import OperatorImageStore
from .product_models import ProductModel
from .product_service import ProductService


SEMIFINAL_MANIFEST_NAME = "semifinal_demo_manifest.json"
SEMIFINAL_MANIFEST_SCHEMA_VERSION = "visiondata-gate.semifinal-demo-manifest.v1"
SEMIFINAL_MANIFEST_CLAIM_BOUNDARY = (
    "This manifest proves an isolated local product/demo path using synthetic "
    "fixture replay. It is not factory shadow evidence, customer acceptance, "
    "production deployment, or production release."
)
SEMIFINAL_PROJECTION_SCHEMA_VERSION = (
    "visiondata-gate.semifinal-demo-manifest-projection.v1"
)
SEMIFINAL_PROJECTION_HASH_PROFILE = "visiondata-gate.rfc8785-jcs-projection-sha256.v1"
SEMIFINAL_PROJECTION_CLAIM_BOUNDARY = (
    "This read-only projection proves that one isolated local semifinal demo "
    "manifest passed its frozen contract and was reconciled with the ProductRoot "
    "currently served. It is synthetic fixture replay only; it is not factory "
    "shadow evidence, customer validation, an official submission receipt, "
    "production deployment, machine authority, or production release."
)

_SHA256 = re.compile(r"^[0-9a-f]{64}$")
_TASK_ID = re.compile(r"^tsk_[0-9a-f]{20}$")
_CASE_ID = re.compile(r"^incident_[0-9a-f]{20}$")
_DECISION_ID = re.compile(r"^incident_decision_[0-9a-f]{20}$")
_INTERACTION_ID = re.compile(r"^interaction_[0-9a-f]{20}$")
_ASSET_ID = re.compile(r"^img_[0-9a-f]{20}$")

_MANIFEST_FIELDS = frozenset(
    {
        "schema_version",
        "status",
        "source_scope",
        "product_root",
        "actor_user_id",
        "workspace_id",
        "project_id",
        "project_source_kind",
        "task_id",
        "review_start_path",
        "task_request_sha256",
        "task_evidence_sha256",
        "task_execution_status",
        "task_final_decision",
        "task_release_readiness_status",
        "task_release_readiness_sha256",
        "event_count",
        "parent_case_id",
        "parent_case_sha256",
        "decision_id",
        "decision_sha256",
        "decision_kind",
        "child_case_id",
        "child_case_sha256",
        "child_incident_status",
        "child_incident_recommendation",
        "interaction_id",
        "interaction_receipt_sha256",
        "interaction_status",
        "remaining_open_question_count",
        "visual_assets",
        "production_release_allowed",
        "machine_write_permitted",
        "customer_validation",
        "factory_shadow_metrics",
        "claim_boundary",
        "manifest_sha256",
    }
)


class ManifestContractError(ValueError):
    """Raised when the demo manifest drifts outside its frozen claim boundary."""


def _unique_json_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    """Build one JSON object while rejecting ambiguous duplicate members."""

    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError(f"duplicate JSON member in semifinal manifest: {key}")
        result[key] = value
    return result


def _reject_non_finite_json_constant(value: str) -> None:
    """Reject NaN and infinities, which are outside the JSON data model."""

    raise ValueError(f"non-finite JSON number in semifinal manifest: {value}")


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise ManifestContractError(message)


def _require_digest(payload: dict[str, Any], field: str) -> None:
    value = payload.get(field)
    _require(
        isinstance(value, str) and _SHA256.fullmatch(value) is not None,
        f"{field} must be a lowercase SHA-256 digest",
    )


def verify_manifest(
    payload: object,
    *,
    manifest_path: Path | None = None,
    expected_product_root: Path | None = None,
) -> dict[str, Any]:
    """Validate the closed manifest schema and its legacy canonical digest."""

    _require(isinstance(payload, dict), "manifest root must be a JSON object")
    manifest = dict(payload)
    missing = sorted(_MANIFEST_FIELDS.difference(manifest))
    unexpected = sorted(set(manifest).difference(_MANIFEST_FIELDS))
    _require(not missing, f"manifest is missing required fields: {missing}")
    _require(not unexpected, f"manifest contains unexpected fields: {unexpected}")

    exact_values = {
        "schema_version": SEMIFINAL_MANIFEST_SCHEMA_VERSION,
        "status": "PASS_LOCAL_DEMO_PREPARED",
        "source_scope": "SYNTHETIC_FIXTURE_REPLAY_ONLY",
        "actor_user_id": "usr_local_demo",
        "project_source_kind": "synthetic_demo",
        "task_execution_status": "COMPLETED",
        "task_final_decision": "PASS",
        "task_release_readiness_status": "DEMO_ONLY",
        "decision_kind": "CONTINUE_HOLD",
        "child_incident_status": "INVESTIGATION_REQUIRED",
        "child_incident_recommendation": "CONTINUE_HOLD",
        "interaction_status": "RESUMED_WITH_OPEN_QUESTIONS",
        "customer_validation": "NOT_CLAIMED",
        "factory_shadow_metrics": "NOT_MEASURED_PENDING_ADJUDICATION",
        "claim_boundary": SEMIFINAL_MANIFEST_CLAIM_BOUNDARY,
    }
    for field, expected in exact_values.items():
        _require(manifest.get(field) == expected, f"{field} must remain {expected}")

    _require(
        manifest.get("production_release_allowed") is False,
        "production_release_allowed must remain false",
    )
    _require(
        manifest.get("machine_write_permitted") is False,
        "machine_write_permitted must remain false",
    )
    _require(
        manifest.get("remaining_open_question_count") == 1,
        "the frozen interaction must retain exactly one open question",
    )
    _require(
        isinstance(manifest.get("event_count"), int)
        and not isinstance(manifest["event_count"], bool)
        and manifest["event_count"] > 0,
        "event_count must be a positive integer",
    )

    id_contracts = {
        "task_id": _TASK_ID,
        "parent_case_id": _CASE_ID,
        "child_case_id": _CASE_ID,
        "decision_id": _DECISION_ID,
        "interaction_id": _INTERACTION_ID,
    }
    for field, pattern in id_contracts.items():
        value = manifest.get(field)
        _require(
            isinstance(value, str) and pattern.fullmatch(value) is not None,
            f"{field} has an invalid immutable identifier",
        )

    _require(
        manifest["parent_case_id"] != manifest["child_case_id"],
        "Parent and Child Case identities must differ",
    )
    _require(
        manifest.get("review_start_path") == f"/review?task={manifest['task_id']}",
        "review_start_path must bind the exact prepared Task",
    )

    for field in (
        "task_request_sha256",
        "task_evidence_sha256",
        "task_release_readiness_sha256",
        "parent_case_sha256",
        "decision_sha256",
        "child_case_sha256",
        "interaction_receipt_sha256",
        "manifest_sha256",
    ):
        _require_digest(manifest, field)

    assets = manifest.get("visual_assets")
    _require(
        isinstance(assets, list) and len(assets) == 2,
        "visual_assets must contain two frozen assets",
    )
    expected_names = {
        "synthetic-fixture-before.png",
        "synthetic-fixture-recheck.png",
    }
    observed_names: set[str] = set()
    observed_ids: set[str] = set()
    for index, raw_asset in enumerate(assets):
        _require(
            isinstance(raw_asset, dict), f"visual_assets[{index}] must be an object"
        )
        asset = dict(raw_asset)
        _require(
            set(asset)
            == {
                "asset_id",
                "filename",
                "source_sha256",
                "preview_sha256",
                "width",
                "height",
            },
            f"visual_assets[{index}] fields drifted from the frozen contract",
        )
        asset_id = asset.get("asset_id")
        _require(
            isinstance(asset_id, str) and _ASSET_ID.fullmatch(asset_id) is not None,
            f"visual_assets[{index}].asset_id is invalid",
        )
        _require(asset_id not in observed_ids, "visual asset ids must be unique")
        observed_ids.add(asset_id)
        filename = asset.get("filename")
        _require(
            filename in expected_names, f"visual_assets[{index}].filename is not frozen"
        )
        observed_names.add(str(filename))
        for field in ("source_sha256", "preview_sha256"):
            value = asset.get(field)
            _require(
                isinstance(value, str) and _SHA256.fullmatch(value) is not None,
                f"visual_assets[{index}].{field} is invalid",
            )
        for field in ("width", "height"):
            value = asset.get(field)
            _require(
                isinstance(value, int) and not isinstance(value, bool) and value > 0,
                f"visual_assets[{index}].{field} must be positive",
            )
    _require(observed_names == expected_names, "the frozen visual asset set drifted")

    product_root_value = manifest.get("product_root")
    _require(isinstance(product_root_value, str), "product_root must be present")
    product_root = Path(product_root_value).expanduser().resolve()
    if expected_product_root is not None:
        _require(
            product_root == expected_product_root.expanduser().resolve(),
            "manifest product_root does not match the launcher's isolated root",
        )
    if manifest_path is not None:
        _require(
            manifest_path.expanduser().resolve().parent == product_root,
            "manifest file is not stored at the declared isolated product root",
        )

    stable = {key: value for key, value in manifest.items() if key != "manifest_sha256"}
    observed_manifest_sha = hashlib.sha256(canonical_json_bytes(stable)).hexdigest()
    _require(
        manifest["manifest_sha256"] == observed_manifest_sha,
        "manifest_sha256 does not match canonical manifest bytes",
    )
    return manifest


def verify_product_state(
    manifest: dict[str, Any],
    *,
    product_service: ProductService | None = None,
) -> dict[str, Any]:
    """Reconcile a valid declaration with the ProductRoot actually served."""

    product_root = Path(manifest["product_root"]).expanduser().resolve(strict=True)
    _require(
        (product_root / "product.sqlite3").is_file(),
        "product database is unavailable",
    )

    owns_service = product_service is None
    service = product_service
    try:
        if service is None:
            service = ProductService(product_root, recover_interrupted=False)
        else:
            _require(
                service.product_root.resolve() == product_root,
                "manifest ProductRoot does not match the service ProductRoot",
            )
        actor_id = str(manifest["actor_user_id"])
        workspace_id = str(manifest["workspace_id"])
        project_id = str(manifest["project_id"])
        task_id = str(manifest["task_id"])

        workspace_ids = {
            item.workspace_id for item in service.list_workspaces(actor_id)
        }
        _require(
            workspace_id in workspace_ids,
            "manifest workspace is not visible to the declared actor",
        )
        project = service.get_project(actor_id, project_id)
        _require(
            project.workspace_id == workspace_id,
            "manifest project failed workspace binding",
        )
        _require(
            project.source_kind.value == manifest["project_source_kind"],
            "manifest project source kind drifted from the product database",
        )

        task = service.get_task(actor_id, task_id)
        task_bindings = {
            "workspace_id": task.workspace_id,
            "project_id": task.project_id,
            "request_sha256": task.request_sha256,
            "evidence_sha256": task.evidence_sha256,
            "execution_status": task.execution_status.value,
            "final_decision": task.final_decision,
        }
        expected_task_bindings = {
            "workspace_id": workspace_id,
            "project_id": project_id,
            "request_sha256": manifest["task_request_sha256"],
            "evidence_sha256": manifest["task_evidence_sha256"],
            "execution_status": manifest["task_execution_status"],
            "final_decision": manifest["task_final_decision"],
        }
        _require(
            task_bindings == expected_task_bindings,
            "manifest Task identity or terminal result drifted from the product database",
        )

        events = service.list_events(actor_id, task_id)
        _require(
            len(events) == manifest["event_count"],
            "manifest event_count drifted from the append-only task ledger",
        )
        readiness = service.task_release_readiness(actor_id, task_id)
        _require(
            readiness.overall_status == manifest["task_release_readiness_status"]
            and readiness.report_sha256 == manifest["task_release_readiness_sha256"]
            and readiness.final_gate_decision == manifest["task_final_decision"]
            and readiness.evidence_integrity == "VERIFIED"
            and readiness.source_freshness == "NOT_APPLICABLE"
            and readiness.production_release_allowed is False,
            "manifest release-readiness identity drifted from live product evidence",
        )

        parent = service.get_industrial_incident_case(
            actor_id,
            task_id,
            str(manifest["parent_case_id"]),
        )
        child = service.get_industrial_incident_case(
            actor_id,
            task_id,
            str(manifest["child_case_id"]),
        )
        _require(
            parent.case_sha256 == manifest["parent_case_sha256"]
            and parent.task_id == task_id
            and parent.parent_case_id is None,
            "manifest Parent Case drifted from immutable incident evidence",
        )
        _require(
            child.case_sha256 == manifest["child_case_sha256"]
            and child.task_id == task_id
            and child.parent_case_id == parent.case_id
            and child.parent_case_sha256 == parent.case_sha256
            and child.authorizing_decision_id == manifest["decision_id"]
            and child.authorizing_decision_sha256 == manifest["decision_sha256"]
            and child.status.value == manifest["child_incident_status"]
            and child.recommendation.value == manifest["child_incident_recommendation"],
            "manifest Child Case drifted from immutable incident evidence",
        )

        decisions = service.list_industrial_incident_decisions(
            actor_id,
            task_id,
            parent.case_id,
        )
        matching_decisions = [
            item for item in decisions if item.decision_id == manifest["decision_id"]
        ]
        _require(
            len(matching_decisions) == 1,
            "manifest named decision is unavailable or ambiguous",
        )
        decision = matching_decisions[0]
        _require(
            decision.decision_sha256 == manifest["decision_sha256"]
            and decision.decision.value == manifest["decision_kind"]
            and decision.actor_user_id == actor_id
            and decision.production_release_allowed is False
            and decision.equipment_control_allowed is False,
            "manifest named decision drifted from the immutable decision receipt",
        )

        interaction = service.get_industrial_incident_interaction_receipt(
            actor_id,
            task_id,
            child.case_id,
        )
        _require(
            interaction.interaction_id == manifest["interaction_id"]
            and interaction.receipt_sha256 == manifest["interaction_receipt_sha256"]
            and interaction.parent_case_sha256 == parent.case_sha256
            and interaction.decision_sha256 == decision.decision_sha256
            and interaction.child_case_sha256 == child.case_sha256
            and interaction.interaction_status == manifest["interaction_status"]
            and interaction.remaining_open_question_count
            == manifest["remaining_open_question_count"]
            and interaction.production_release_allowed is False
            and interaction.machine_write_permitted is False,
            "manifest interaction receipt drifted from its four source artifacts",
        )

        image_store = OperatorImageStore(product_root / "operator_workspace")
        assets = image_store.list_assets(
            actor_id,
            workspace_id,
            project_id=project_id,
        )
        assets_by_id = {item.asset_id: item for item in assets}
        _require(
            len(assets_by_id) == len(manifest["visual_assets"]),
            "isolated visual asset denominator drifted from the manifest",
        )
        for raw_asset in manifest["visual_assets"]:
            asset = assets_by_id.get(raw_asset["asset_id"])
            _require(asset is not None, "manifest visual asset is unavailable")
            assert asset is not None
            _require(
                asset.original_name == raw_asset["filename"]
                and asset.project_id == project_id
                and asset.source_sha256 == raw_asset["source_sha256"]
                and asset.preview_sha256 == raw_asset["preview_sha256"]
                and asset.width == raw_asset["width"]
                and asset.height == raw_asset["height"],
                "manifest visual asset metadata drifted from the local record",
            )
            source_path, _, source_sha256 = image_store.file_variant(
                actor_id,
                workspace_id,
                asset.asset_id,
                "source",
            )
            preview_path, _, preview_sha256 = image_store.file_variant(
                actor_id,
                workspace_id,
                asset.asset_id,
                "preview",
            )
            _require(
                source_path.is_file()
                and preview_path.is_file()
                and source_sha256 == raw_asset["source_sha256"]
                and preview_sha256 == raw_asset["preview_sha256"],
                "manifest visual asset bytes drifted from their SHA-256 bindings",
            )
    except ManifestContractError:
        raise
    except Exception as exc:
        raise ManifestContractError(
            f"product-state reconciliation failed closed: {type(exc).__name__}: {exc}"
        ) from exc
    finally:
        if owns_service and service is not None:
            service.close(wait=True)
    return manifest


class SemifinalVisualAssetProjection(ProductModel):
    asset_id: str = Field(pattern=r"^img_[0-9a-f]{20}$")
    filename: Literal[
        "synthetic-fixture-before.png",
        "synthetic-fixture-recheck.png",
    ]
    source_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    preview_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    width: int = Field(gt=0)
    height: int = Field(gt=0)


class VerifiedSemifinalDemoManifest(ProductModel):
    """Verified manifest fields safe for a reviewer-facing response.

    ``product_root`` is intentionally omitted so the endpoint never publishes a
    workstation path.  The source manifest digest remains present and has already
    been checked against the complete declaration, including that path.
    """

    schema_version: Literal["visiondata-gate.semifinal-demo-manifest.v1"]
    status: Literal["PASS_LOCAL_DEMO_PREPARED"]
    source_scope: Literal["SYNTHETIC_FIXTURE_REPLAY_ONLY"]
    actor_user_id: Literal["usr_local_demo"]
    workspace_id: str = Field(min_length=1)
    project_id: str = Field(min_length=1)
    project_source_kind: Literal["synthetic_demo"]
    task_id: str = Field(pattern=r"^tsk_[0-9a-f]{20}$")
    review_start_path: str = Field(min_length=1)
    task_request_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    task_evidence_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    task_execution_status: Literal["COMPLETED"]
    task_final_decision: Literal["PASS"]
    task_release_readiness_status: Literal["DEMO_ONLY"]
    task_release_readiness_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    event_count: int = Field(gt=0)
    parent_case_id: str = Field(pattern=r"^incident_[0-9a-f]{20}$")
    parent_case_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    decision_id: str = Field(pattern=r"^incident_decision_[0-9a-f]{20}$")
    decision_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    decision_kind: Literal["CONTINUE_HOLD"]
    child_case_id: str = Field(pattern=r"^incident_[0-9a-f]{20}$")
    child_case_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    child_incident_status: Literal["INVESTIGATION_REQUIRED"]
    child_incident_recommendation: Literal["CONTINUE_HOLD"]
    interaction_id: str = Field(pattern=r"^interaction_[0-9a-f]{20}$")
    interaction_receipt_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    interaction_status: Literal["RESUMED_WITH_OPEN_QUESTIONS"]
    remaining_open_question_count: Literal[1]
    visual_assets: list[SemifinalVisualAssetProjection] = Field(
        min_length=2,
        max_length=2,
    )
    production_release_allowed: Literal[False]
    machine_write_permitted: Literal[False]
    customer_validation: Literal["NOT_CLAIMED"]
    factory_shadow_metrics: Literal["NOT_MEASURED_PENDING_ADJUDICATION"]
    claim_boundary: str = Field(min_length=1)
    manifest_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")


class SemifinalDemoManifestProjection(ProductModel):
    schema_version: Literal["visiondata-gate.semifinal-demo-manifest-projection.v1"] = (
        SEMIFINAL_PROJECTION_SCHEMA_VERSION
    )
    status: Literal["PASS_LOCAL_DEMO_VERIFIED", "HOLD"]
    availability: Literal["AVAILABLE", "UNAVAILABLE"]
    verification_status: Literal["VERIFIED", "FAILED_CLOSED"]
    failure_code: (
        Literal[
            "MANIFEST_MISSING",
            "MANIFEST_NOT_REGULAR_FILE",
            "MANIFEST_UNREADABLE",
            "MANIFEST_INVALID_JSON",
            "MANIFEST_CONTRACT_INVALID",
            "PRODUCT_STATE_INVALID",
            "PROJECTION_BUILD_FAILED_CLOSED",
        ]
        | None
    ) = None
    manifest: VerifiedSemifinalDemoManifest | None = None
    manifest_sha256: str | None = Field(default=None, pattern=r"^[0-9a-f]{64}$")
    local_demo_only: Literal[True] = True
    product_root_exposed: Literal[False] = False
    production_release_allowed: Literal[False] = False
    machine_write_permitted: Literal[False] = False
    submission_eligible: Literal[False] = False
    customer_validation: Literal["NOT_CLAIMED"] = "NOT_CLAIMED"
    factory_shadow_metrics: Literal["NOT_MEASURED_PENDING_ADJUDICATION"] = (
        "NOT_MEASURED_PENDING_ADJUDICATION"
    )
    read_only: Literal[True] = True
    claim_boundary: str = SEMIFINAL_PROJECTION_CLAIM_BOUNDARY
    projection_hash_profile: Literal[
        "visiondata-gate.rfc8785-jcs-projection-sha256.v1"
    ] = SEMIFINAL_PROJECTION_HASH_PROFILE
    projection_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")


def _safe_manifest(manifest: dict[str, Any]) -> VerifiedSemifinalDemoManifest:
    return VerifiedSemifinalDemoManifest.model_validate(
        {key: value for key, value in manifest.items() if key != "product_root"}
    )


def _build_projection(
    *,
    manifest: VerifiedSemifinalDemoManifest | None,
    failure_code: str | None,
) -> SemifinalDemoManifestProjection:
    verified = manifest is not None and failure_code is None
    payload: dict[str, Any] = {
        "schema_version": SEMIFINAL_PROJECTION_SCHEMA_VERSION,
        "status": "PASS_LOCAL_DEMO_VERIFIED" if verified else "HOLD",
        "availability": "AVAILABLE" if verified else "UNAVAILABLE",
        "verification_status": "VERIFIED" if verified else "FAILED_CLOSED",
        "failure_code": failure_code,
        "manifest": manifest.model_dump(mode="json") if manifest is not None else None,
        "manifest_sha256": manifest.manifest_sha256 if manifest is not None else None,
        "local_demo_only": True,
        "product_root_exposed": False,
        "production_release_allowed": False,
        "machine_write_permitted": False,
        "submission_eligible": False,
        "customer_validation": "NOT_CLAIMED",
        "factory_shadow_metrics": "NOT_MEASURED_PENDING_ADJUDICATION",
        "read_only": True,
        "claim_boundary": SEMIFINAL_PROJECTION_CLAIM_BOUNDARY,
        "projection_hash_profile": SEMIFINAL_PROJECTION_HASH_PROFILE,
    }
    projection_sha256 = hashlib.sha256(canonical_jcs_bytes(payload)).hexdigest()
    return SemifinalDemoManifestProjection.model_validate(
        {**payload, "projection_sha256": projection_sha256}
    )


@dataclass(frozen=True)
class SemifinalDemoManifestSource:
    """Read and reverify the current ProductRoot manifest on every request."""

    product_root: Path

    def project(
        self,
        *,
        product_service: ProductService,
    ) -> SemifinalDemoManifestProjection:
        expected_root = Path(self.product_root).expanduser().resolve()
        manifest_path = expected_root / SEMIFINAL_MANIFEST_NAME
        try:
            resolved = manifest_path.resolve(strict=True)
        except (FileNotFoundError, OSError):
            return _build_projection(manifest=None, failure_code="MANIFEST_MISSING")
        if not resolved.is_file():
            return _build_projection(
                manifest=None,
                failure_code="MANIFEST_NOT_REGULAR_FILE",
            )
        try:
            raw = resolved.read_bytes()
        except OSError:
            return _build_projection(manifest=None, failure_code="MANIFEST_UNREADABLE")
        try:
            decoded = json.loads(
                raw.decode("utf-8"),
                object_pairs_hook=_unique_json_object,
                parse_constant=_reject_non_finite_json_constant,
            )
        except (UnicodeDecodeError, json.JSONDecodeError, ValueError):
            return _build_projection(
                manifest=None,
                failure_code="MANIFEST_INVALID_JSON",
            )
        try:
            manifest = verify_manifest(
                decoded,
                manifest_path=resolved,
                expected_product_root=expected_root,
            )
        except ManifestContractError:
            return _build_projection(
                manifest=None,
                failure_code="MANIFEST_CONTRACT_INVALID",
            )
        try:
            verify_product_state(manifest, product_service=product_service)
        except ManifestContractError:
            return _build_projection(
                manifest=None,
                failure_code="PRODUCT_STATE_INVALID",
            )
        try:
            safe_manifest = _safe_manifest(manifest)
        except Exception:
            return _build_projection(
                manifest=None,
                failure_code="PROJECTION_BUILD_FAILED_CLOSED",
            )
        return _build_projection(manifest=safe_manifest, failure_code=None)


__all__ = [
    "ManifestContractError",
    "SEMIFINAL_MANIFEST_CLAIM_BOUNDARY",
    "SEMIFINAL_MANIFEST_NAME",
    "SEMIFINAL_MANIFEST_SCHEMA_VERSION",
    "SEMIFINAL_PROJECTION_CLAIM_BOUNDARY",
    "SEMIFINAL_PROJECTION_HASH_PROFILE",
    "SEMIFINAL_PROJECTION_SCHEMA_VERSION",
    "SemifinalDemoManifestProjection",
    "SemifinalDemoManifestSource",
    "VerifiedSemifinalDemoManifest",
    "verify_manifest",
    "verify_product_state",
]
