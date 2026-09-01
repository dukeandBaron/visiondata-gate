"""Fail-closed geometry evidence adapter for optional VGGT/OmniVGGT runs.

The VisionData Gate core does not import either model.  A model runner emits a
small, hash-bound JSON receipt and this module checks that receipt against the
frozen batch.  This keeps model installation, GPU scheduling, and model output
formats outside the release gate while still giving the Policy Judge typed
geometry findings when a real run is available.

The adapter is deliberately a *secondary evidence layer*: geometry evidence
can tighten a gate, but it cannot turn a data-contract PASS into product or
production acceptance.  A missing optional receipt is ``NOT_TESTED``; a
malformed or hash-mismatched receipt is fail-closed when the caller includes
the trace in a gate.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
import hashlib
import json
from pathlib import Path
from typing import Any, Literal

from PIL import Image, UnidentifiedImageError
from pydantic import BaseModel, Field

from .contracts import (
    BatchContract,
    BatchManifest,
    EvidenceStatus,
    Finding,
    GateResult,
    Severity,
    ToolContract,
    ToolTrace,
)
from .evidence import (
    canonical_json_bytes,
    sha256_bytes,
    sha256_file,
    write_canonical_json,
)
from .pipeline import compute_batch_digest, run_gate
from .agents import build_council
from .policy import apply_policy
from .runtime_models import ScenarioProfile


GEOMETRY_EVIDENCE_SCHEMA = "visiondata-gate.geometry-evidence.v1"
GEOMETRY_TRACE_ADAPTER = "external-readonly-geometry-v1"


class _GeometryModel(BaseModel):
    """Local strict base without changing the frozen BatchContract schema."""

    model_config = {"extra": "forbid"}


class GeometryThresholds(_GeometryModel):
    """Policy thresholds for the normalized geometry receipt.

    These are review thresholds, not trained-model calibration claims.  A
    project may pass a different threshold object, but the object is always
    included in the trace input digest.
    """

    min_depth_valid_fraction: float = Field(default=0.90, ge=0.0, le=1.0)
    max_depth_outlier_fraction: float = Field(default=0.10, ge=0.0, le=1.0)
    min_depth_confidence_mean: float = Field(default=0.35, ge=0.0, le=1.0)
    max_reprojection_error_px: float = Field(default=2.50, ge=0.0)
    min_track_visibility_fraction: float = Field(default=0.60, ge=0.0, le=1.0)
    min_track_count: int = Field(default=10, ge=0)
    min_view_coverage: float = Field(default=1.0, ge=0.0, le=1.0)
    require_depth_metrics: bool = True


class GeometryViewEvidence(_GeometryModel):
    """One normalized view record produced by a VGGT-family runner."""

    sample_id: str = Field(min_length=1)
    width: int = Field(ge=1)
    height: int = Field(ge=1)
    depth_width: int | None = Field(default=None, ge=1)
    depth_height: int | None = Field(default=None, ge=1)
    depth_valid_fraction: float | None = Field(default=None, ge=0.0, le=1.0)
    depth_outlier_fraction: float | None = Field(default=None, ge=0.0, le=1.0)
    depth_confidence_mean: float | None = Field(default=None, ge=0.0, le=1.0)
    reprojection_error_px: float | None = Field(default=None, ge=0.0)
    track_count: int | None = Field(default=None, ge=0)
    track_visibility_fraction: float | None = Field(default=None, ge=0.0, le=1.0)
    camera_valid: bool = True


class GeometryEvidenceBundle(_GeometryModel):
    """Portable model-output contract consumed by the adapter."""

    schema_version: Literal[GEOMETRY_EVIDENCE_SCHEMA] = GEOMETRY_EVIDENCE_SCHEMA
    backend: Literal["vggt", "omnivggt"]
    backend_version: str = Field(min_length=1)
    input_batch_sha256: str = Field(
        min_length=64, max_length=64, pattern=r"^[0-9a-f]{64}$"
    )
    image_count: int = Field(ge=1)
    views: list[GeometryViewEvidence] = Field(min_length=1)
    checkpoint_sha256: str | None = Field(
        default=None, min_length=64, max_length=64, pattern=r"^[0-9a-f]{64}$"
    )
    output_format: Literal["normalized-json-v1"] = "normalized-json-v1"


@dataclass(frozen=True)
class GeometryConsistencyRun:
    """Result of one optional geometry adapter invocation."""

    status: Literal[
        "PASS_LOCAL",
        "FINDINGS",
        "NOT_TESTED",
        "OPTIONAL_BACKEND_NOT_CONNECTED",
        "ERROR",
    ]
    evidence_path: Path | None
    evidence_sha256: str | None
    findings: tuple[Finding, ...]
    trace: ToolTrace
    metrics: dict[str, int | float | str]
    bundle: GeometryEvidenceBundle | None = None
    error: str | None = None


@dataclass(frozen=True)
class GeometryGateRun:
    """Base gate plus optional geometry evidence and final Policy Judge result."""

    output_root: Path
    base_gate_result: GateResult
    gate_result: GateResult
    geometry: GeometryConsistencyRun
    receipt_path: Path
    receipt_sha256: str
    followup_plan_path: Path
    followup_plan_sha256: str


def geometry_tool_contract() -> ToolContract:
    """Return the optional external-readonly tool contract.

    It is not part of the frozen core tool catalog.  Callers that explicitly
    include geometry can use ``validate_tool_contract_trace(...,
    include_geometry=True)`` to bind this trace like the core tools.
    """

    return ToolContract(
        name="geometry_consistency",
        version="1.0.0",
        input_schema="BatchManifest + BatchContract + GeometryEvidenceBundle + GeometryThresholds",
        output_schema="ToolTrace + Finding[] + geometry metrics",
        permission_scope="geometry:evidence:read / read_geometry_emit_finding",
        side_effect_level="L0_none",
        idempotency="batch digest + evidence bytes digest + geometry thresholds",
        max_retries=0,
        failure_policy="fail_closed",
        audit_fields=[
            "sequence",
            "input_sha256",
            "parameters",
            "result_sha256",
            "finding_ids",
            "adapter",
        ],
        mcp_migration_target="mcp-tool.v1",
        migration_cost="medium",
    )


def geometry_tool_contract_digest() -> str:
    payload = json.dumps(
        geometry_tool_contract().model_dump(mode="json"),
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")
    # ``tools.tool_contract_digest`` uses the same no-trailing-newline
    # canonicalization for the frozen core contracts.
    return sha256_bytes(payload)


def validate_geometry_tool_trace(trace: ToolTrace) -> str | None:
    """Validate the optional geometry trace without enabling it by default."""

    expected = geometry_tool_contract()
    if trace.tool != expected.name:
        return f"unexpected geometry trace tool: {trace.tool}"
    if trace.adapter != GEOMETRY_TRACE_ADAPTER:
        return f"unsupported geometry adapter: {trace.adapter}"
    if trace.contract_version != expected.version:
        return "geometry tool contract version drift"
    if trace.contract_digest != geometry_tool_contract_digest():
        return "geometry tool contract digest drift"
    return None


def _load_bundle(
    value: GeometryEvidenceBundle | str | Path | Mapping[str, Any],
) -> tuple[GeometryEvidenceBundle, Path | None, str]:
    if isinstance(value, GeometryEvidenceBundle):
        bundle = GeometryEvidenceBundle.model_validate(value.model_dump(mode="json"))
        raw = canonical_json_bytes(bundle.model_dump(mode="json"))
        return bundle, None, sha256_bytes(raw)
    if isinstance(value, Mapping):
        bundle = GeometryEvidenceBundle.model_validate(dict(value))
        raw = canonical_json_bytes(bundle.model_dump(mode="json"))
        return bundle, None, sha256_bytes(raw)
    path = Path(value).expanduser().resolve(strict=True)
    if not path.is_file():
        raise IsADirectoryError(path)
    raw = path.read_bytes()
    payload = json.loads(raw.decode("utf-8"))
    bundle = GeometryEvidenceBundle.model_validate(payload)
    return bundle, path, sha256_bytes(raw)


def _finding_id(code: str, sample_ids: list[str], evidence: Mapping[str, Any]) -> str:
    payload = {
        "code": code,
        "sample_ids": sorted(sample_ids),
        "evidence": dict(evidence),
    }
    return f"geometry-{hashlib.sha256(canonical_json_bytes(payload)).hexdigest()[:16]}"


def _finding(
    *,
    code: str,
    severity: Severity,
    sample_ids: list[str],
    summary: str,
    evidence: Mapping[str, Any],
    recommended_action: str,
    evidence_status: EvidenceStatus = EvidenceStatus.VERIFIED,
) -> Finding:
    return Finding(
        finding_id=_finding_id(code, sample_ids, evidence),
        code=code,
        severity=severity,
        tool="geometry_consistency",
        sample_ids=sorted(sample_ids),
        summary=summary,
        evidence=dict(evidence),
        evidence_status=evidence_status,
        recommended_action=recommended_action,
    )


def _safe_image_size(
    batch_root: Path, manifest: BatchManifest, sample_id: str
) -> tuple[int, int] | None:
    sample = next(
        (item for item in manifest.samples if item.sample_id == sample_id), None
    )
    if sample is None:
        return None
    candidate = batch_root.joinpath(
        *sample.relative_path.replace("\\", "/").split("/")
    ).resolve()
    try:
        candidate.relative_to(batch_root.resolve())
        with Image.open(candidate) as image:
            return image.size
    except (FileNotFoundError, OSError, UnidentifiedImageError, ValueError):
        return None


def inspect_geometry_consistency(
    batch_root: str | Path,
    manifest: BatchManifest,
    contract: BatchContract,
    evidence: GeometryEvidenceBundle | str | Path | Mapping[str, Any],
    *,
    thresholds: GeometryThresholds | None = None,
) -> tuple[
    list[Finding],
    dict[str, int | float | str],
    GeometryEvidenceBundle,
    str,
    Path | None,
]:
    """Check a normalized VGGT/OmniVGGT receipt against the frozen batch."""

    root = Path(batch_root).expanduser().resolve(strict=True)
    if not root.is_dir():
        raise NotADirectoryError(root)
    manifest_model = BatchManifest.model_validate(manifest.model_dump(mode="json"))
    contract_model = BatchContract.model_validate(contract.model_dump(mode="json"))
    bundle, evidence_path, evidence_sha256 = _load_bundle(evidence)
    active = thresholds or GeometryThresholds()
    expected_batch_sha256 = compute_batch_digest(root, manifest_model, contract_model)

    findings: list[Finding] = []
    expected_ids = {item.sample_id for item in manifest_model.samples}
    observed_ids = [item.sample_id for item in bundle.views]
    observed_set = set(observed_ids)
    duplicate_ids = sorted(
        {item for item in observed_ids if observed_ids.count(item) > 1}
    )
    missing_ids = sorted(expected_ids - observed_set)
    unknown_ids = sorted(observed_set - expected_ids)
    hash_match = bundle.input_batch_sha256 == expected_batch_sha256

    if not hash_match:
        findings.append(
            _finding(
                code="GEOMETRY_INPUT_HASH_MISMATCH",
                severity=Severity.CRITICAL,
                sample_ids=[],
                summary="Geometry output is bound to a different batch or contract.",
                evidence={
                    "expected_batch_sha256": expected_batch_sha256,
                    "observed_batch_sha256": bundle.input_batch_sha256,
                },
                recommended_action="investigate source batch and rerun geometry backend",
                evidence_status=EvidenceStatus.UNSUPPORTED,
            )
        )
    if bundle.image_count != len(manifest_model.samples):
        findings.append(
            _finding(
                code="GEOMETRY_VIEW_COUNT_MISMATCH",
                severity=Severity.HIGH,
                sample_ids=[],
                summary="Geometry receipt image count differs from the frozen manifest.",
                evidence={
                    "expected_image_count": len(manifest_model.samples),
                    "observed_image_count": bundle.image_count,
                },
                recommended_action="recapture missing views or regenerate the receipt",
            )
        )
    if duplicate_ids:
        findings.append(
            _finding(
                code="GEOMETRY_DUPLICATE_VIEW_ID",
                severity=Severity.HIGH,
                sample_ids=duplicate_ids,
                summary="Geometry receipt contains duplicate view identifiers.",
                evidence={"duplicate_sample_ids": duplicate_ids},
                recommended_action="investigate view-to-sample mapping before release",
            )
        )
    if missing_ids:
        findings.append(
            _finding(
                code="GEOMETRY_SAMPLE_MISSING",
                severity=Severity.HIGH,
                sample_ids=missing_ids,
                summary="One or more manifest images have no geometry evidence.",
                evidence={"missing_sample_ids": missing_ids},
                recommended_action="recapture or rerun the missing views",
            )
        )
    if unknown_ids:
        findings.append(
            _finding(
                code="GEOMETRY_UNKNOWN_SAMPLE",
                severity=Severity.HIGH,
                sample_ids=unknown_ids,
                summary="Geometry receipt references samples outside the frozen manifest.",
                evidence={"unknown_sample_ids": unknown_ids},
                recommended_action="investigate input mapping and discard stale output",
            )
        )

    if (
        len(observed_set & expected_ids) / max(len(expected_ids), 1)
        < active.min_view_coverage
    ):
        findings.append(
            _finding(
                code="GEOMETRY_VIEW_COVERAGE_LOW",
                severity=Severity.HIGH,
                sample_ids=sorted(observed_set & expected_ids),
                summary="Geometry evidence does not cover the required view fraction.",
                evidence={
                    "observed_view_coverage": round(
                        len(observed_set & expected_ids) / max(len(expected_ids), 1), 6
                    ),
                    "min_view_coverage": active.min_view_coverage,
                },
                recommended_action="recapture missing views before downstream inspection",
            )
        )

    for view in bundle.views:
        if view.sample_id not in expected_ids:
            continue
        actual_size = _safe_image_size(root, manifest_model, view.sample_id)
        if actual_size is not None and actual_size != (view.width, view.height):
            findings.append(
                _finding(
                    code="GEOMETRY_IMAGE_SIZE_MISMATCH",
                    severity=Severity.HIGH,
                    sample_ids=[view.sample_id],
                    summary="Geometry view dimensions do not match the source image.",
                    evidence={
                        "sample_id": view.sample_id,
                        "source_size": list(actual_size),
                        "geometry_size": [view.width, view.height],
                    },
                    recommended_action="rerun geometry inference on the exact source bytes",
                )
            )

        if not view.camera_valid:
            findings.append(
                _finding(
                    code="GEOMETRY_CAMERA_INVALID",
                    severity=Severity.HIGH,
                    sample_ids=[view.sample_id],
                    summary="Camera parameters for a geometry view are marked invalid.",
                    evidence={"sample_id": view.sample_id},
                    recommended_action="investigate camera calibration or recapture view",
                )
            )

        if active.require_depth_metrics:
            missing_metrics = [
                name
                for name, value in (
                    ("depth_width", view.depth_width),
                    ("depth_height", view.depth_height),
                    ("depth_valid_fraction", view.depth_valid_fraction),
                    ("depth_outlier_fraction", view.depth_outlier_fraction),
                    ("depth_confidence_mean", view.depth_confidence_mean),
                )
                if value is None
            ]
            if missing_metrics:
                findings.append(
                    _finding(
                        code="GEOMETRY_METRIC_MISSING",
                        severity=Severity.HIGH,
                        sample_ids=[view.sample_id],
                        summary="Geometry receipt omits required depth metrics.",
                        evidence={
                            "sample_id": view.sample_id,
                            "missing_metrics": missing_metrics,
                        },
                        recommended_action="rerun the backend with normalized depth evidence",
                        evidence_status=EvidenceStatus.UNSUPPORTED,
                    )
                )
        if (
            view.depth_width is not None
            and view.depth_height is not None
            and (view.depth_width, view.depth_height) != (view.width, view.height)
        ):
            findings.append(
                _finding(
                    code="GEOMETRY_DEPTH_SHAPE_MISMATCH",
                    severity=Severity.HIGH,
                    sample_ids=[view.sample_id],
                    summary="Depth evidence is not spatially aligned with the RGB view.",
                    evidence={
                        "sample_id": view.sample_id,
                        "image_size": [view.width, view.height],
                        "depth_size": [view.depth_width, view.depth_height],
                    },
                    recommended_action="regenerate aligned depth output or recapture view",
                )
            )
        if (
            view.depth_valid_fraction is not None
            and view.depth_valid_fraction < active.min_depth_valid_fraction
        ):
            findings.append(
                _finding(
                    code="GEOMETRY_DEPTH_VALID_FRACTION_LOW",
                    severity=Severity.HIGH,
                    sample_ids=[view.sample_id],
                    summary="Valid depth coverage is below the review threshold.",
                    evidence={
                        "sample_id": view.sample_id,
                        "value": view.depth_valid_fraction,
                        "threshold": active.min_depth_valid_fraction,
                    },
                    recommended_action="recapture view or investigate reflective/occluded regions",
                )
            )
        if (
            view.depth_outlier_fraction is not None
            and view.depth_outlier_fraction > active.max_depth_outlier_fraction
        ):
            findings.append(
                _finding(
                    code="GEOMETRY_DEPTH_OUTLIER_HIGH",
                    severity=Severity.HIGH,
                    sample_ids=[view.sample_id],
                    summary="Depth outlier fraction is above the review threshold.",
                    evidence={
                        "sample_id": view.sample_id,
                        "value": view.depth_outlier_fraction,
                        "threshold": active.max_depth_outlier_fraction,
                    },
                    recommended_action="investigate depth outliers and recapture if needed",
                )
            )
        if (
            view.depth_confidence_mean is not None
            and view.depth_confidence_mean < active.min_depth_confidence_mean
        ):
            findings.append(
                _finding(
                    code="GEOMETRY_DEPTH_CONFIDENCE_LOW",
                    severity=Severity.MEDIUM,
                    sample_ids=[view.sample_id],
                    summary="Mean depth confidence is below the review threshold.",
                    evidence={
                        "sample_id": view.sample_id,
                        "value": view.depth_confidence_mean,
                        "threshold": active.min_depth_confidence_mean,
                    },
                    recommended_action="investigate geometry confidence before using the result",
                )
            )
        if (
            view.reprojection_error_px is not None
            and view.reprojection_error_px > active.max_reprojection_error_px
        ):
            findings.append(
                _finding(
                    code="GEOMETRY_REPROJECTION_ERROR_HIGH",
                    severity=Severity.HIGH,
                    sample_ids=[view.sample_id],
                    summary="Multi-view reprojection error is above the review threshold.",
                    evidence={
                        "sample_id": view.sample_id,
                        "value_px": view.reprojection_error_px,
                        "threshold_px": active.max_reprojection_error_px,
                    },
                    recommended_action="investigate camera/view alignment or recapture",
                )
            )
        if view.track_count is not None and view.track_count < active.min_track_count:
            findings.append(
                _finding(
                    code="GEOMETRY_TRACK_COUNT_LOW",
                    severity=Severity.MEDIUM,
                    sample_ids=[view.sample_id],
                    summary="The view has too few tracked 3D points for a stable check.",
                    evidence={
                        "sample_id": view.sample_id,
                        "value": view.track_count,
                        "threshold": active.min_track_count,
                    },
                    recommended_action="capture more overlapping views or investigate texture",
                )
            )
        if (
            view.track_visibility_fraction is not None
            and view.track_visibility_fraction < active.min_track_visibility_fraction
        ):
            findings.append(
                _finding(
                    code="GEOMETRY_TRACK_VISIBILITY_LOW",
                    severity=Severity.MEDIUM,
                    sample_ids=[view.sample_id],
                    summary="Track visibility across views is below the review threshold.",
                    evidence={
                        "sample_id": view.sample_id,
                        "value": view.track_visibility_fraction,
                        "threshold": active.min_track_visibility_fraction,
                    },
                    recommended_action="increase view overlap or investigate occlusion",
                )
            )

    metrics: dict[str, int | float | str] = {
        "geometry_backend": bundle.backend,
        "geometry_backend_version": bundle.backend_version,
        "geometry_input_hash_match": int(hash_match),
        "geometry_expected_view_count": len(expected_ids),
        "geometry_observed_view_count": len(bundle.views),
        "geometry_matched_view_count": len(observed_set & expected_ids),
        "geometry_view_coverage": round(
            len(observed_set & expected_ids) / max(len(expected_ids), 1), 6
        ),
        "geometry_duplicate_view_count": len(duplicate_ids),
        "geometry_missing_view_count": len(missing_ids),
        "geometry_unknown_view_count": len(unknown_ids),
        "geometry_finding_count": len(findings),
        "geometry_evidence_sha256": evidence_sha256,
        "geometry_thresholds_sha256": sha256_bytes(
            canonical_json_bytes(active.model_dump(mode="json"))
        ),
    }
    return findings, metrics, bundle, evidence_sha256, evidence_path


def _trace(
    *,
    status: Literal["ok", "error", "skipped"],
    input_sha256: str,
    result_sha256: str,
    findings: list[Finding],
    parameters: Mapping[str, Any],
    error: str | None = None,
) -> ToolTrace:
    return ToolTrace(
        sequence=90,
        tool="geometry_consistency",
        status=status,
        input_sha256=input_sha256,
        parameters=dict(parameters),
        result_sha256=result_sha256,
        finding_ids=[item.finding_id for item in findings],
        error=error,
        contract_version=geometry_tool_contract().version,
        contract_digest=geometry_tool_contract_digest(),
        adapter=GEOMETRY_TRACE_ADAPTER,
    )


def run_geometry_consistency(
    batch_root: str | Path,
    manifest: BatchManifest,
    contract: BatchContract,
    evidence: GeometryEvidenceBundle | str | Path | Mapping[str, Any] | None,
    *,
    thresholds: GeometryThresholds | None = None,
    required: bool = False,
    backend_connection_status: str | None = None,
) -> GeometryConsistencyRun:
    """Run the optional adapter and emit a hash-bound ToolTrace.

    ``required=False`` makes an absent receipt a clean ``NOT_TESTED`` state
    without changing the core gate.  Once a receipt is supplied, parse or
    contract errors are represented by an ``error`` trace and should be
    included in the final gate so Policy Judge fails closed.
    """

    active = thresholds or GeometryThresholds()
    try:
        batch_sha256 = compute_batch_digest(batch_root, manifest, contract)
    except Exception as error:
        payload = {"status": "error", "message": type(error).__name__}
        digest = sha256_bytes(canonical_json_bytes(payload))
        trace = _trace(
            status="error",
            input_sha256=digest,
            result_sha256=digest,
            findings=[],
            parameters={
                "thresholds": active.model_dump(mode="json"),
                "required": required,
            },
            error=f"{type(error).__name__}: batch digest failed",
        )
        return GeometryConsistencyRun(
            "ERROR",
            None,
            None,
            (),
            trace,
            {"geometry_status": "ERROR"},
            error=trace.error,
        )

    if evidence is None:
        payload = {
            "batch_sha256": batch_sha256,
            "thresholds": active.model_dump(mode="json"),
            "required": required,
            "status": "missing",
        }
        digest = sha256_bytes(canonical_json_bytes(payload))
        trace = _trace(
            status="skipped",
            input_sha256=digest,
            result_sha256=digest,
            findings=[],
            parameters={
                "thresholds": active.model_dump(mode="json"),
                "required": required,
            },
            error="geometry evidence was not provided",
        )
        status = "NOT_TESTED" if required else "OPTIONAL_BACKEND_NOT_CONNECTED"
        return GeometryConsistencyRun(
            status,
            None,
            None,
            (),
            trace,
            {"geometry_status": status, "geometry_backend_connected": 0},
            error=trace.error,
        )

    try:
        bundle, evidence_path, evidence_sha256 = _load_bundle(evidence)
        findings, metrics, bundle, evidence_sha256, inspected_path = (
            inspect_geometry_consistency(
                batch_root,
                manifest,
                contract,
                bundle,
                thresholds=active,
            )
        )
        evidence_path = evidence_path or inspected_path
        input_sha256 = sha256_bytes(
            canonical_json_bytes(
                {
                    "batch_sha256": batch_sha256,
                    "evidence_sha256": evidence_sha256,
                    "thresholds": active.model_dump(mode="json"),
                }
            )
        )
        result_sha256 = sha256_bytes(
            canonical_json_bytes(
                {
                    "findings": [item.model_dump(mode="json") for item in findings],
                    "metrics": metrics,
                }
            )
        )
        trace = _trace(
            status="ok",
            input_sha256=input_sha256,
            result_sha256=result_sha256,
            findings=findings,
            parameters={
                "backend": bundle.backend,
                "backend_version": bundle.backend_version,
                "thresholds": active.model_dump(mode="json"),
            },
        )
        status: Literal["PASS_LOCAL", "FINDINGS"] = (
            "PASS_LOCAL" if not findings else "FINDINGS"
        )
        metrics = {
            **metrics,
            "geometry_status": status,
            "geometry_backend_connected": int(
                backend_connection_status
                in {"CONTRACT_CONNECTED_LOCAL_TEST", "REAL_BACKEND_CONNECTED"}
            ),
            "geometry_evidence_receipt_connected": 1,
            "geometry_backend_connection_status": (
                backend_connection_status or "UNVERIFIED_NORMALIZED_RECEIPT"
            ),
        }
        return GeometryConsistencyRun(
            status,
            evidence_path,
            evidence_sha256,
            tuple(findings),
            trace,
            metrics,
            bundle=bundle,
        )
    except Exception as error:
        evidence_path = None
        evidence_sha256 = None
        if isinstance(evidence, (str, Path)):
            candidate = Path(evidence).expanduser().resolve()
            if candidate.is_file():
                evidence_path = candidate
                evidence_sha256 = sha256_file(candidate)
        payload = {
            "batch_sha256": batch_sha256,
            "evidence_sha256": evidence_sha256,
            "error_type": type(error).__name__,
            "thresholds": active.model_dump(mode="json"),
        }
        digest = sha256_bytes(canonical_json_bytes(payload))
        trace = _trace(
            status="error",
            input_sha256=digest,
            result_sha256=digest,
            findings=[],
            parameters={
                "thresholds": active.model_dump(mode="json"),
                "required": required,
            },
            error=f"{type(error).__name__}: geometry evidence validation failed",
        )
        return GeometryConsistencyRun(
            "ERROR",
            evidence_path,
            evidence_sha256,
            (),
            trace,
            {"geometry_status": "ERROR", "geometry_backend_connected": 0},
            error=trace.error,
        )


def build_geometry_followup_plan(
    findings: list[Finding] | tuple[Finding, ...],
) -> dict[str, Any]:
    """Create a plan-only Dynamic Leader branch from geometry findings."""

    branch_by_code = {
        "GEOMETRY_INPUT_HASH_MISMATCH": "input-reconciliation",
        "GEOMETRY_METRIC_MISSING": "geometry-output-normalization",
        "GEOMETRY_DEPTH_SHAPE_MISMATCH": "depth-alignment-reconciliation",
        "GEOMETRY_DEPTH_VALID_FRACTION_LOW": "depth-recapture",
        "GEOMETRY_DEPTH_OUTLIER_HIGH": "depth-recapture",
        "GEOMETRY_DEPTH_CONFIDENCE_LOW": "geometry-confidence-review",
        "GEOMETRY_REPROJECTION_ERROR_HIGH": "view-geometry-reconciliation",
        "GEOMETRY_TRACK_COUNT_LOW": "view-overlap-recapture",
        "GEOMETRY_TRACK_VISIBILITY_LOW": "view-overlap-recapture",
        "GEOMETRY_VIEW_COVERAGE_LOW": "view-coverage-recapture",
        "GEOMETRY_CAMERA_INVALID": "camera-calibration-review",
    }
    tasks: list[dict[str, Any]] = []
    for index, finding in enumerate(
        sorted(findings, key=lambda item: item.finding_id), start=1
    ):
        tasks.append(
            {
                "task_id": f"geometry-followup-{index:02d}",
                "branch_type": branch_by_code.get(
                    finding.code, "geometry-investigation"
                ),
                "dispatch_basis": "intermediate_evidence",
                "status": "planned",
                "finding_id": finding.finding_id,
                "reason_code": finding.code,
                "sample_ids": finding.sample_ids,
                "execution_boundary": "plan_only_no_external_mutation",
            }
        )
    return {
        "schema_version": "visiondata-gate.geometry-dynamic-plan.v1",
        "mode": "evidence_triggered_plan" if tasks else "no_followup",
        "planner": "geometry-consistency-leader",
        "dynamic_task_count": len(tasks),
        "branch_types": sorted({item["branch_type"] for item in tasks}),
        "dynamic_tasks": tasks,
        "boundary_notice": "This is a plan-only adapter; no recapture, model rerun, or production write was executed.",
    }


def run_geometry_gate(
    batch_root: str | Path,
    manifest: BatchManifest | str | Path,
    contract: BatchContract | str | Path | None,
    geometry_evidence: GeometryEvidenceBundle | str | Path | Mapping[str, Any] | None,
    output_root: str | Path,
    *,
    thresholds: GeometryThresholds | None = None,
    required: bool = True,
    scenario_profile: ScenarioProfile = ScenarioProfile.INDUSTRIAL,
    backend_connection_receipt: Mapping[str, Any] | None = None,
) -> GeometryGateRun:
    """Run the ordinary gate and explicitly merge optional geometry evidence.

    The core path is unchanged.  When a receipt is valid, the geometry trace
    and findings are merged before a fresh Council/Policy Judge pass.  A
    missing receipt is only merged when ``required=True``; this makes the
    ``NOT_TESTED`` boundary explicit instead of silently reusing old output.
    """

    manifest_model = (
        manifest
        if isinstance(manifest, BatchManifest)
        else BatchManifest.model_validate_json(
            Path(manifest).read_text(encoding="utf-8")
        )
    )
    contract_model = (
        BatchContract()
        if contract is None
        else (
            contract
            if isinstance(contract, BatchContract)
            else BatchContract.model_validate_json(
                Path(contract).read_text(encoding="utf-8")
            )
        )
    )
    base = run_gate(
        batch_root,
        manifest_model,
        contract_model,
        scenario_profile=scenario_profile,
    )
    geometry = run_geometry_consistency(
        batch_root,
        manifest_model,
        contract_model,
        geometry_evidence,
        thresholds=thresholds,
        required=required,
        backend_connection_status=(
            str(backend_connection_receipt.get("status"))
            if backend_connection_receipt is not None
            else None
        ),
    )

    include_geometry = geometry.trace.status != "skipped" or required
    if include_geometry:
        findings = [*base.findings, *geometry.findings]
        traces = [*base.tool_trace, geometry.trace]
        metrics = {**base.metrics, **geometry.metrics}
        final_input_sha256 = sha256_bytes(
            canonical_json_bytes(
                {
                    "base_input_sha256": base.input_sha256,
                    "geometry_input_sha256": geometry.trace.input_sha256,
                    "geometry_trace_result_sha256": geometry.trace.result_sha256,
                }
            )
        )
        council = build_council(findings, traces, metrics)
        final = apply_policy(
            manifest_model,
            contract_model,
            findings,
            traces,
            metrics,
            council,
            scenario_profile=scenario_profile,
            input_sha256=final_input_sha256,
            run_id=f"geometry-gate-{final_input_sha256[:16]}",
        )
    else:
        final = base

    root = Path(output_root).expanduser().resolve()
    root.mkdir(parents=True, exist_ok=True)
    gate_result_path = root / "gate_result.json"
    gate_result_sha256 = write_canonical_json(gate_result_path, final)
    trace_path = root / "geometry_trace.json"
    trace_sha256 = write_canonical_json(trace_path, geometry.trace)
    followup_plan = build_geometry_followup_plan(geometry.findings)
    followup_path = root / "geometry_dynamic_plan.json"
    followup_sha256 = write_canonical_json(followup_path, followup_plan)
    receipt = {
        "schema_version": "visiondata-gate.geometry-gate-receipt.v1",
        "status": geometry.status,
        "required": required,
        "decision": final.decision.value,
        "base_gate_result_sha256": sha256_bytes(
            canonical_json_bytes(base.model_dump(mode="json"))
        ),
        "gate_result_sha256": gate_result_sha256,
        "geometry_trace_sha256": trace_sha256,
        "geometry_evidence_sha256": geometry.evidence_sha256,
        "geometry_backend": geometry.bundle.backend if geometry.bundle else None,
        "backend_connection_status": (
            backend_connection_receipt.get("status")
            if backend_connection_receipt is not None
            else "REAL_BACKEND_NOT_CONNECTED"
        ),
        "backend_connection_receipt_sha256": (
            sha256_bytes(canonical_json_bytes(dict(backend_connection_receipt)))
            if backend_connection_receipt is not None
            else None
        ),
        "geometry_finding_count": len(geometry.findings),
        "dynamic_plan_sha256": followup_sha256,
        "boundary_notice": "Geometry is optional secondary evidence; PASS_LOCAL does not claim product acceptance, production authorization, or official competition submission.",
    }
    receipt_path = root / "geometry_gate_receipt.json"
    receipt_sha256 = write_canonical_json(receipt_path, receipt)
    return GeometryGateRun(
        output_root=root,
        base_gate_result=base,
        gate_result=final,
        geometry=geometry,
        receipt_path=receipt_path,
        receipt_sha256=receipt_sha256,
        followup_plan_path=followup_path,
        followup_plan_sha256=followup_sha256,
    )


__all__ = [
    "GEOMETRY_EVIDENCE_SCHEMA",
    "GEOMETRY_TRACE_ADAPTER",
    "GeometryConsistencyRun",
    "GeometryEvidenceBundle",
    "GeometryGateRun",
    "GeometryThresholds",
    "GeometryViewEvidence",
    "build_geometry_followup_plan",
    "geometry_tool_contract",
    "geometry_tool_contract_digest",
    "inspect_geometry_consistency",
    "run_geometry_consistency",
    "run_geometry_gate",
    "validate_geometry_tool_trace",
]
