"""Read-only DynamicBench evidence projection for reviewer-facing APIs.

This module is deliberately downstream of both the Agent runtime and the
benchmark runners.  It reads already-frozen reports, invokes their production
validators, and exposes only a curated evidence summary.  Benchmark fixtures,
expected outcomes, and labels are never supplied to ProductService or the
Incident runtime through this projection.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from functools import lru_cache
import hashlib
import hmac
import json
import os
from pathlib import Path
from typing import Any, Literal

from pydantic import Field

from .benchmarks.dynamic_benchmark_v4 import (
    BENCHMARK_ID as V4_BENCHMARK_ID,
    CLAIM_BOUNDARY as V4_CLAIM_BOUNDARY,
    PRODUCTION_ROUTE as V4_PRODUCTION_ROUTE,
    SCHEMA_VERSION as V4_SCHEMA_VERSION,
    validate_dynamic_benchmark_v4_report,
)
from .dynamic_benchmark_v3 import (
    DynamicBenchmarkV3ValidationError,
    validate_dynamic_replanning_benchmark_report,
)
from .audit_envelope import canonical_jcs_bytes
from .product_models import ProductModel


DYNAMICBENCH_V3_REPORT_NAME = "DYNAMICBENCH_V3_REPLANNING_20260829.json"
DYNAMICBENCH_V4_REPORT_NAME = "DYNAMICBENCH_V4_PRODUCT_RUNTIME_20260829.json"
_SOURCE_PROJECT_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_V3_REPORT_PATH = (
    _SOURCE_PROJECT_ROOT / "10_reports" / DYNAMICBENCH_V3_REPORT_NAME
)
DEFAULT_V4_REPORT_PATH = (
    _SOURCE_PROJECT_ROOT / "10_reports" / DYNAMICBENCH_V4_REPORT_NAME
)


def _runtime_report_path(report_name: str) -> Path:
    """Resolve immutable review evidence inside source or packaged resources.

    The desktop entrypoint binds ``VISIONDATA_RESOURCE_ROOT`` to PyInstaller's
    read-only extraction/resource directory before importing the API.  Keeping
    this lookup at source construction time also makes the contract testable
    without changing the benchmark validator or accepting arbitrary filenames.
    """

    configured_root = os.environ.get("VISIONDATA_RESOURCE_ROOT", "").strip()
    resource_root = (
        Path(configured_root).expanduser().resolve()
        if configured_root
        else _SOURCE_PROJECT_ROOT
    )
    return resource_root / "10_reports" / report_name


PROJECTION_SCHEMA_VERSION = (
    "visiondata-gate.dynamicbench-evaluation-evidence-projection.v1"
)
PROJECTION_HASH_PROFILE = "visiondata-gate.rfc8785-jcs-projection-sha256.v1"
V3_SCHEMA_VERSION = "visiondata-gate.dynamic-benchmark.v3"
V3_BENCHMARK_ID = "DynamicBench-v3-dynamic-replanning"
V3_VERDICT = "DYNAMIC_REPLANNING_ADVANTAGE_OBSERVED_IN_FROZEN_LOCAL_FIXTURES"
V4_VERDICT = "PRODUCTION_RUNTIME_BRIDGE_VERIFIED_ON_FROZEN_LOCAL_FIXTURES"
V3_V4_RELATIONSHIP = (
    "V3_PROVES_DETERMINISTIC_PAIRED_ORCHESTRATION;"
    "V4_PROVES_PRODUCTION_RUNTIME_BRIDGE;CLAIMS_MUST_NOT_BE_POOLED"
)
FROZEN_V3_CONTENT_SHA256 = (
    "424be5fc8f51d55bf412b6e73c88a4943bc2d403b1e2d85817b7eb7de9e36d21"
)
FROZEN_V4_CONTENT_SHA256 = (
    "e33d238c48270b5732c6778dcaad2d4ed93cf06d9b3b0d800ca6e84a49cdb99e"
)

PROJECTION_CLAIM_BOUNDARY = (
    "This read-only projection exposes verified DynamicBench evidence from frozen "
    "synthetic fixtures. DynamicBench-v3 is deterministic paired orchestration "
    "evidence; DynamicBench-v4 is ProductService and Incident v6 runtime-path "
    "evidence. Neither report is a factory metric, customer validation, production "
    "deployment, production SLO, or production-release authorization."
)


class DynamicBenchV3CoreMetrics(ProductModel):
    """Curated v3 metrics; no fixture truth or runtime input is exposed."""

    fixture_denominator: int = Field(ge=1)
    paired_record_count: int = Field(ge=1)
    fixed_rule_correct_terminal_disposition_count: int = Field(ge=0)
    dynamic_replanning_correct_terminal_disposition_count: int = Field(ge=0)
    correct_terminal_gain_count: int
    fixed_rule_total_tool_call_count: int = Field(ge=0)
    dynamic_replanning_total_tool_call_count: int = Field(ge=0)
    fixed_rule_unnecessary_tool_call_count: int = Field(ge=0)
    dynamic_replanning_unnecessary_tool_call_count: int = Field(ge=0)
    unnecessary_tool_call_reduction_count: int
    fixed_rule_tool_failure_recovery_rate: float = Field(ge=0.0, le=1.0)
    dynamic_replanning_tool_failure_recovery_rate: float = Field(ge=0.0, le=1.0)
    fixed_rule_evidence_changed_adaptation_rate: float = Field(ge=0.0, le=1.0)
    dynamic_replanning_evidence_changed_adaptation_rate: float = Field(ge=0.0, le=1.0)
    fixed_rule_unsafe_release_count: int = Field(ge=0)
    dynamic_replanning_unsafe_release_count: int = Field(ge=0)
    actual_model_call_count: int = Field(ge=0)


class DynamicBenchV4CoreMetrics(ProductModel):
    """Curated v4 runtime-path metrics from frozen synthetic fixtures."""

    fixed_fixture_denominator: int = Field(ge=1)
    product_service_execution_count: int = Field(ge=0)
    passed_count: int = Field(ge=0)
    incident_v6_count: int = Field(ge=0)
    decision_packet_v3_count: int = Field(ge=0)
    tool_failure_fixture_count: int = Field(ge=0)
    tool_failure_recovered_fail_closed_count: int = Field(ge=0)
    unsafe_production_release_count: int = Field(ge=0)
    actual_external_model_call_count: int = Field(ge=0)


class DynamicBenchReportEvidence(ProductModel):
    version: Literal["v3", "v4"]
    evidence_role: Literal[
        "FROZEN_SYNTHETIC_ORCHESTRATION_COMPARISON",
        "FROZEN_SYNTHETIC_PRODUCTSERVICE_INCIDENT_V6_BRIDGE",
    ]
    source_artifact_name: str = Field(min_length=1)
    availability: Literal["AVAILABLE", "UNAVAILABLE"]
    verification_status: Literal["VERIFIED", "FAILED_CLOSED"]
    verification_error_code: str | None = None
    content_sha256: str | None = Field(default=None, pattern=r"^[0-9a-f]{64}$")
    sealed_report_sha256: str | None = Field(default=None, pattern=r"^[0-9a-f]{64}$")
    schema_version: str | None = None
    benchmark_id: str | None = None
    report_status: Literal["PASS"] | None = None
    verdict: str | None = None
    data_source_status: Literal["FROZEN_SYNTHETIC_FIXTURES"] | None = None
    industrial_effectiveness_status: Literal["NOT_EVALUATED"] | None = None
    production_deployment_status: Literal["NOT_CONNECTED"] | None = None
    production_route: str | None = None
    claim_boundary: str | None = None
    core_metrics: DynamicBenchV3CoreMetrics | DynamicBenchV4CoreMetrics | None = None


class EvaluationEvidenceScope(ProductModel):
    scope_kind: Literal["GLOBAL_REVIEW", "WORKSPACE_REFERENCE", "PROJECT_REFERENCE"]
    workspace_id: str | None = None
    project_id: str | None = None
    association_status: Literal[
        "GLOBAL_FROZEN_REFERENCE",
        "REFERENCE_ONLY_NOT_WORKSPACE_DERIVED",
        "REFERENCE_ONLY_NOT_PROJECT_DERIVED",
    ]
    read_only: Literal[True] = True


class DynamicBenchEvaluationEvidenceProjection(ProductModel):
    schema_version: Literal[
        "visiondata-gate.dynamicbench-evaluation-evidence-projection.v1"
    ] = PROJECTION_SCHEMA_VERSION
    status: Literal["PASS_LOCAL_EVIDENCE", "HOLD"]
    availability: Literal["AVAILABLE", "UNAVAILABLE"]
    verification_status: Literal["VERIFIED", "FAILED_CLOSED"]
    pair_binding_status: Literal["VERIFIED", "FAILED_CLOSED", "NOT_VERIFIABLE"]
    failure_codes: list[str]
    scope: EvaluationEvidenceScope
    reports: list[DynamicBenchReportEvidence] = Field(min_length=2, max_length=2)
    data_scope: Literal["FROZEN_SYNTHETIC_FIXTURES"] = "FROZEN_SYNTHETIC_FIXTURES"
    factory_metrics_status: Literal["NOT_MEASURED_BY_DYNAMICBENCH"] = (
        "NOT_MEASURED_BY_DYNAMICBENCH"
    )
    factory_shadow_metrics_status: Literal["NOT_MEASURED_PENDING_ADJUDICATION"] = (
        "NOT_MEASURED_PENDING_ADJUDICATION"
    )
    customer_validation_status: Literal["NOT_CLAIMED"] = "NOT_CLAIMED"
    production_deployment_status: Literal["NOT_CONNECTED"] = "NOT_CONNECTED"
    production_release_allowed: Literal[False] = False
    machine_write_permitted: Literal[False] = False
    benchmark_truth_feedback_to_agent_runtime: Literal[False] = False
    read_only: Literal[True] = True
    claim_boundary: str = PROJECTION_CLAIM_BOUNDARY
    projection_hash_profile: Literal[
        "visiondata-gate.rfc8785-jcs-projection-sha256.v1"
    ] = PROJECTION_HASH_PROFILE
    projection_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")


@dataclass(frozen=True)
class _ArtifactProjection:
    evidence: DynamicBenchReportEvidence
    report: dict[str, Any] | None


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _unavailable_evidence(
    *,
    version: Literal["v3", "v4"],
    role: Literal[
        "FROZEN_SYNTHETIC_ORCHESTRATION_COMPARISON",
        "FROZEN_SYNTHETIC_PRODUCTSERVICE_INCIDENT_V6_BRIDGE",
    ],
    path: Path,
    error_code: str,
    content_sha256: str | None = None,
) -> _ArtifactProjection:
    return _ArtifactProjection(
        evidence=DynamicBenchReportEvidence(
            version=version,
            evidence_role=role,
            source_artifact_name=path.name,
            availability="UNAVAILABLE",
            verification_status="FAILED_CLOSED",
            verification_error_code=error_code,
            content_sha256=content_sha256,
        ),
        report=None,
    )


def _read_report(path: Path) -> tuple[dict[str, Any] | None, bytes | None, str | None]:
    try:
        resolved = path.expanduser().resolve(strict=True)
    except (FileNotFoundError, OSError):
        return None, None, "REPORT_MISSING"
    if not resolved.is_file():
        return None, None, "REPORT_NOT_REGULAR_FILE"
    try:
        raw = resolved.read_bytes()
    except OSError:
        return None, None, "REPORT_UNREADABLE"
    try:
        decoded = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError):
        return None, raw, "REPORT_INVALID_JSON"
    if not isinstance(decoded, dict):
        return None, raw, "REPORT_INVALID_JSON_OBJECT"
    return decoded, raw, None


def _v3_core_metrics(report: dict[str, Any]) -> DynamicBenchV3CoreMetrics:
    metrics = report["metrics"]
    fixed = metrics["fixed_rule_baseline"]
    dynamic = metrics["dynamic_replanning_contract"]
    comparison = report["comparisons"]
    return DynamicBenchV3CoreMetrics(
        fixture_denominator=fixed["fixed_fixture_denominator"],
        paired_record_count=len(report["records"]),
        fixed_rule_correct_terminal_disposition_count=fixed[
            "correct_terminal_disposition_count"
        ],
        dynamic_replanning_correct_terminal_disposition_count=dynamic[
            "correct_terminal_disposition_count"
        ],
        correct_terminal_gain_count=comparison["correct_terminal_gain_count"],
        fixed_rule_total_tool_call_count=fixed["total_tool_call_count"],
        dynamic_replanning_total_tool_call_count=dynamic["total_tool_call_count"],
        fixed_rule_unnecessary_tool_call_count=fixed["unnecessary_tool_call_count"],
        dynamic_replanning_unnecessary_tool_call_count=dynamic[
            "unnecessary_tool_call_count"
        ],
        unnecessary_tool_call_reduction_count=comparison[
            "unnecessary_tool_call_reduction_count"
        ],
        fixed_rule_tool_failure_recovery_rate=fixed["tool_failure_recovery_rate"],
        dynamic_replanning_tool_failure_recovery_rate=dynamic[
            "tool_failure_recovery_rate"
        ],
        fixed_rule_evidence_changed_adaptation_rate=fixed[
            "evidence_changed_next_step_adaptation_rate"
        ],
        dynamic_replanning_evidence_changed_adaptation_rate=dynamic[
            "evidence_changed_next_step_adaptation_rate"
        ],
        fixed_rule_unsafe_release_count=fixed["unsafe_release_count"],
        dynamic_replanning_unsafe_release_count=dynamic["unsafe_release_count"],
        actual_model_call_count=(
            fixed["actual_model_call_count"] + dynamic["actual_model_call_count"]
        ),
    )


def _v4_core_metrics(report: dict[str, Any]) -> DynamicBenchV4CoreMetrics:
    return DynamicBenchV4CoreMetrics.model_validate(report["metrics"])


@lru_cache(maxsize=8)
def _validated_v3_bytes(
    raw: bytes,
) -> tuple[dict[str, Any], DynamicBenchV3CoreMetrics]:
    report = json.loads(raw.decode("utf-8"))
    if not isinstance(report, dict):
        raise DynamicBenchmarkV3ValidationError(
            "DynamicBench-v3 report must be an object"
        )
    validate_dynamic_replanning_benchmark_report(report)
    return report, _v3_core_metrics(report)


@lru_cache(maxsize=8)
def _validated_v4_bytes(
    raw: bytes,
) -> tuple[dict[str, Any], DynamicBenchV4CoreMetrics]:
    report = json.loads(raw.decode("utf-8"))
    if not isinstance(report, dict):
        raise ValueError("DynamicBench-v4 report must be an object")
    validate_dynamic_benchmark_v4_report(report)
    if not _v4_boundary_is_frozen(report):
        raise ValueError("v4 projection boundary drifted")
    return report, _v4_core_metrics(report)


def _project_v3(path: Path, *, expected_content_sha256: str) -> _ArtifactProjection:
    role = "FROZEN_SYNTHETIC_ORCHESTRATION_COMPARISON"
    report, raw, read_error = _read_report(path)
    digest = _sha256(raw) if raw is not None else None
    if read_error is not None or report is None:
        return _unavailable_evidence(
            version="v3",
            role=role,
            path=path,
            error_code=f"V3_{read_error}",
            content_sha256=digest,
        )
    if digest is None or not hmac.compare_digest(digest, expected_content_sha256):
        return _unavailable_evidence(
            version="v3",
            role=role,
            path=path,
            error_code="V3_FROZEN_CONTENT_SHA256_MISMATCH",
            content_sha256=digest,
        )
    try:
        if raw is None:
            raise ValueError("v3 report bytes unavailable")
        report, metrics = _validated_v3_bytes(raw)
    except Exception:
        # A reviewer endpoint must turn every malformed-report failure into a
        # bounded HOLD; it must never leak validator internals as an HTTP 500.
        return _unavailable_evidence(
            version="v3",
            role=role,
            path=path,
            error_code="V3_REPORT_CONTRACT_INVALID",
            content_sha256=digest,
        )
    return _ArtifactProjection(
        evidence=DynamicBenchReportEvidence(
            version="v3",
            evidence_role=role,
            source_artifact_name=path.name,
            availability="AVAILABLE",
            verification_status="VERIFIED",
            content_sha256=digest,
            sealed_report_sha256=report["sealed_report_sha256"],
            schema_version=report["schema_version"],
            benchmark_id=report["benchmark_id"],
            report_status=report["status"],
            verdict=report["verdict"],
            data_source_status=report["data_source_status"],
            industrial_effectiveness_status=report["industrial_effectiveness_status"],
            claim_boundary=report["claim_boundary"],
            core_metrics=metrics,
        ),
        report=report,
    )


def _v4_boundary_is_frozen(report: dict[str, Any]) -> bool:
    return bool(
        report.get("schema_version") == V4_SCHEMA_VERSION
        and report.get("benchmark_id") == V4_BENCHMARK_ID
        and report.get("verdict") == V4_VERDICT
        and report.get("production_route") == V4_PRODUCTION_ROUTE
        and report.get("data_source_status") == "FROZEN_SYNTHETIC_FIXTURES"
        and report.get("industrial_effectiveness_status") == "NOT_EVALUATED"
        and report.get("production_deployment_status") == "NOT_CONNECTED"
        and report.get("claim_boundary") == V4_CLAIM_BOUNDARY
    )


def _project_v4(path: Path, *, expected_content_sha256: str) -> _ArtifactProjection:
    role = "FROZEN_SYNTHETIC_PRODUCTSERVICE_INCIDENT_V6_BRIDGE"
    report, raw, read_error = _read_report(path)
    digest = _sha256(raw) if raw is not None else None
    if read_error is not None or report is None:
        return _unavailable_evidence(
            version="v4",
            role=role,
            path=path,
            error_code=f"V4_{read_error}",
            content_sha256=digest,
        )
    if digest is None or not hmac.compare_digest(digest, expected_content_sha256):
        return _unavailable_evidence(
            version="v4",
            role=role,
            path=path,
            error_code="V4_FROZEN_CONTENT_SHA256_MISMATCH",
            content_sha256=digest,
        )
    try:
        if raw is None:
            raise ValueError("v4 report bytes unavailable")
        report, metrics = _validated_v4_bytes(raw)
    except Exception:
        # See the v3 branch above: malformed evidence is a state, not a crash.
        return _unavailable_evidence(
            version="v4",
            role=role,
            path=path,
            error_code="V4_REPORT_CONTRACT_INVALID",
            content_sha256=digest,
        )
    return _ArtifactProjection(
        evidence=DynamicBenchReportEvidence(
            version="v4",
            evidence_role=role,
            source_artifact_name=path.name,
            availability="AVAILABLE",
            verification_status="VERIFIED",
            content_sha256=digest,
            sealed_report_sha256=report["sealed_report_sha256"],
            schema_version=report["schema_version"],
            benchmark_id=report["benchmark_id"],
            report_status=report["status"],
            verdict=report["verdict"],
            data_source_status=report["data_source_status"],
            industrial_effectiveness_status=report["industrial_effectiveness_status"],
            production_deployment_status=report["production_deployment_status"],
            production_route=report["production_route"],
            claim_boundary=report["claim_boundary"],
            core_metrics=metrics,
        ),
        report=report,
    )


def _pair_binding_status(
    v3: _ArtifactProjection,
    v4: _ArtifactProjection,
) -> Literal["VERIFIED", "FAILED_CLOSED", "NOT_VERIFIABLE"]:
    if v3.report is None or v4.report is None:
        return "NOT_VERIFIABLE"
    expected = {
        "benchmark_id": V3_BENCHMARK_ID,
        "schema_version": V3_SCHEMA_VERSION,
        "status": "PASS",
        "verdict": V3_VERDICT,
        "sealed_report_sha256": v3.report["sealed_report_sha256"],
        "file_sha256": v3.evidence.content_sha256,
        "relationship": V3_V4_RELATIONSHIP,
    }
    return (
        "VERIFIED"
        if v4.report.get("dynamicbench_v3_comparison_binding") == expected
        else "FAILED_CLOSED"
    )


def global_evaluation_evidence_scope() -> EvaluationEvidenceScope:
    return EvaluationEvidenceScope(
        scope_kind="GLOBAL_REVIEW",
        association_status="GLOBAL_FROZEN_REFERENCE",
    )


def scoped_evaluation_evidence_scope(
    *, workspace_id: str, project_id: str | None = None
) -> EvaluationEvidenceScope:
    if project_id is None:
        return EvaluationEvidenceScope(
            scope_kind="WORKSPACE_REFERENCE",
            workspace_id=workspace_id,
            association_status="REFERENCE_ONLY_NOT_WORKSPACE_DERIVED",
        )
    return EvaluationEvidenceScope(
        scope_kind="PROJECT_REFERENCE",
        workspace_id=workspace_id,
        project_id=project_id,
        association_status="REFERENCE_ONLY_NOT_PROJECT_DERIVED",
    )


@dataclass(frozen=True)
class DynamicBenchEvaluationEvidenceSource:
    """Read and verify the two frozen reports on every projection request."""

    v3_report_path: Path = field(
        default_factory=lambda: _runtime_report_path(DYNAMICBENCH_V3_REPORT_NAME)
    )
    v4_report_path: Path = field(
        default_factory=lambda: _runtime_report_path(DYNAMICBENCH_V4_REPORT_NAME)
    )
    v3_expected_content_sha256: str = FROZEN_V3_CONTENT_SHA256
    v4_expected_content_sha256: str = FROZEN_V4_CONTENT_SHA256

    def project(
        self, *, scope: EvaluationEvidenceScope
    ) -> DynamicBenchEvaluationEvidenceProjection:
        v3 = _project_v3(
            Path(self.v3_report_path),
            expected_content_sha256=self.v3_expected_content_sha256,
        )
        v4 = _project_v4(
            Path(self.v4_report_path),
            expected_content_sha256=self.v4_expected_content_sha256,
        )
        pair_status = _pair_binding_status(v3, v4)
        failure_codes = [
            item.verification_error_code
            for item in (v3.evidence, v4.evidence)
            if item.verification_error_code is not None
        ]
        if pair_status != "VERIFIED":
            failure_codes.append(f"V3_V4_BINDING_{pair_status}")
        verified = (
            v3.evidence.verification_status == "VERIFIED"
            and v4.evidence.verification_status == "VERIFIED"
            and pair_status == "VERIFIED"
        )
        payload: dict[str, Any] = {
            "schema_version": PROJECTION_SCHEMA_VERSION,
            "status": "PASS_LOCAL_EVIDENCE" if verified else "HOLD",
            "availability": "AVAILABLE" if verified else "UNAVAILABLE",
            "verification_status": "VERIFIED" if verified else "FAILED_CLOSED",
            "pair_binding_status": pair_status,
            "failure_codes": failure_codes,
            "scope": scope.model_dump(mode="json"),
            "reports": [
                v3.evidence.model_dump(mode="json"),
                v4.evidence.model_dump(mode="json"),
            ],
            "data_scope": "FROZEN_SYNTHETIC_FIXTURES",
            "factory_metrics_status": "NOT_MEASURED_BY_DYNAMICBENCH",
            "factory_shadow_metrics_status": ("NOT_MEASURED_PENDING_ADJUDICATION"),
            "customer_validation_status": "NOT_CLAIMED",
            "production_deployment_status": "NOT_CONNECTED",
            "production_release_allowed": False,
            "machine_write_permitted": False,
            "benchmark_truth_feedback_to_agent_runtime": False,
            "read_only": True,
            "claim_boundary": PROJECTION_CLAIM_BOUNDARY,
            "projection_hash_profile": PROJECTION_HASH_PROFILE,
        }
        projection_sha256 = _sha256(canonical_jcs_bytes(payload))
        return DynamicBenchEvaluationEvidenceProjection.model_validate(
            {**payload, "projection_sha256": projection_sha256}
        )


__all__ = [
    "DEFAULT_V3_REPORT_PATH",
    "DEFAULT_V4_REPORT_PATH",
    "DYNAMICBENCH_V3_REPORT_NAME",
    "DYNAMICBENCH_V4_REPORT_NAME",
    "DynamicBenchEvaluationEvidenceProjection",
    "DynamicBenchEvaluationEvidenceSource",
    "DynamicBenchReportEvidence",
    "DynamicBenchV3CoreMetrics",
    "DynamicBenchV4CoreMetrics",
    "EvaluationEvidenceScope",
    "FROZEN_V3_CONTENT_SHA256",
    "FROZEN_V4_CONTENT_SHA256",
    "PROJECTION_CLAIM_BOUNDARY",
    "global_evaluation_evidence_scope",
    "scoped_evaluation_evidence_scope",
]
