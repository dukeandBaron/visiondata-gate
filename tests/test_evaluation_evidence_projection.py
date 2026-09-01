from __future__ import annotations

import hashlib
import json
from pathlib import Path

from fastapi.testclient import TestClient
import pytest

from visiondata_gate.api import create_app
from visiondata_gate.audit_envelope import canonical_jcs_bytes
from visiondata_gate.benchmarks.dynamic_benchmark_v4 import (
    _HASH_DOMAINS as V4_HASH_DOMAINS,
    _framed_sha256 as v4_framed_sha256,
    validate_dynamic_benchmark_v4_report,
)
from visiondata_gate.evaluation_evidence import (
    DEFAULT_V3_REPORT_PATH,
    DEFAULT_V4_REPORT_PATH,
    DynamicBenchEvaluationEvidenceSource,
    global_evaluation_evidence_scope,
)
from visiondata_gate.evidence import canonical_json_bytes
from visiondata_gate.product_service import ProductService


pytestmark = pytest.mark.tier_integration


def _copy_frozen_reports(tmp_path: Path) -> tuple[Path, Path]:
    v3 = tmp_path / "dynamicbench-v3.json"
    v4 = tmp_path / "dynamicbench-v4.json"
    v3.write_bytes(DEFAULT_V3_REPORT_PATH.read_bytes())
    v4.write_bytes(DEFAULT_V4_REPORT_PATH.read_bytes())
    return v3, v4


def _source(
    v3: Path,
    v4: Path,
    *,
    v3_expected_content_sha256: str | None = None,
    v4_expected_content_sha256: str | None = None,
) -> DynamicBenchEvaluationEvidenceSource:
    overrides: dict[str, str] = {}
    if v3_expected_content_sha256 is not None:
        overrides["v3_expected_content_sha256"] = v3_expected_content_sha256
    if v4_expected_content_sha256 is not None:
        overrides["v4_expected_content_sha256"] = v4_expected_content_sha256
    return DynamicBenchEvaluationEvidenceSource(
        v3_report_path=v3,
        v4_report_path=v4,
        **overrides,
    )


def test_projection_reverifies_and_separates_v3_v4_claims(tmp_path: Path) -> None:
    v3, v4 = _copy_frozen_reports(tmp_path)
    projection = _source(v3, v4).project(scope=global_evaluation_evidence_scope())

    assert projection.status == "PASS_LOCAL_EVIDENCE"
    assert projection.availability == "AVAILABLE"
    assert projection.verification_status == "VERIFIED"
    assert projection.pair_binding_status == "VERIFIED"
    assert projection.failure_codes == []
    assert projection.factory_metrics_status == "NOT_MEASURED_BY_DYNAMICBENCH"
    assert (
        projection.factory_shadow_metrics_status == "NOT_MEASURED_PENDING_ADJUDICATION"
    )
    assert projection.customer_validation_status == "NOT_CLAIMED"
    assert projection.production_release_allowed is False
    assert projection.machine_write_permitted is False
    assert projection.benchmark_truth_feedback_to_agent_runtime is False

    v3_evidence, v4_evidence = projection.reports
    assert v3_evidence.evidence_role == "FROZEN_SYNTHETIC_ORCHESTRATION_COMPARISON"
    assert (
        v4_evidence.evidence_role
        == "FROZEN_SYNTHETIC_PRODUCTSERVICE_INCIDENT_V6_BRIDGE"
    )
    assert v3_evidence.content_sha256 == hashlib.sha256(v3.read_bytes()).hexdigest()
    assert v4_evidence.content_sha256 == hashlib.sha256(v4.read_bytes()).hexdigest()
    assert v3_evidence.core_metrics is not None
    assert v4_evidence.core_metrics is not None
    assert (
        v3_evidence.core_metrics.dynamic_replanning_correct_terminal_disposition_count
        == 8
    )
    assert v3_evidence.core_metrics.unnecessary_tool_call_reduction_count == 14
    assert v4_evidence.core_metrics.product_service_execution_count == 4
    assert v4_evidence.core_metrics.incident_v6_count == 4
    assert v4_evidence.production_deployment_status == "NOT_CONNECTED"
    assert "factory applicability" in (v4_evidence.claim_boundary or "")

    serialized = projection.model_dump(mode="json")
    detached = {
        key: value for key, value in serialized.items() if key != "projection_sha256"
    }
    assert projection.projection_hash_profile == (
        "visiondata-gate.rfc8785-jcs-projection-sha256.v1"
    )
    assert (
        projection.projection_sha256
        == hashlib.sha256(canonical_jcs_bytes(detached)).hexdigest()
    )
    assert "fixture_manifest" not in serialized["reports"][0]
    assert "records" not in serialized["reports"][1]


def test_missing_report_returns_unavailable_hold_without_default_metrics(
    tmp_path: Path,
) -> None:
    missing_v3 = tmp_path / "missing-v3.json"
    v4 = tmp_path / "dynamicbench-v4.json"
    v4.write_bytes(DEFAULT_V4_REPORT_PATH.read_bytes())

    projection = _source(missing_v3, v4).project(
        scope=global_evaluation_evidence_scope()
    )

    assert projection.status == "HOLD"
    assert projection.availability == "UNAVAILABLE"
    assert projection.verification_status == "FAILED_CLOSED"
    assert projection.pair_binding_status == "NOT_VERIFIABLE"
    assert "V3_REPORT_MISSING" in projection.failure_codes
    assert "V3_V4_BINDING_NOT_VERIFIABLE" in projection.failure_codes
    assert projection.reports[0].availability == "UNAVAILABLE"
    assert projection.reports[0].content_sha256 is None
    assert projection.reports[0].sealed_report_sha256 is None
    assert projection.reports[0].core_metrics is None
    assert projection.reports[1].verification_status == "VERIFIED"


def test_changed_v3_file_bytes_break_v4_pair_binding_even_when_v3_contract_is_valid(
    tmp_path: Path,
) -> None:
    v3, v4 = _copy_frozen_reports(tmp_path)
    v3.write_bytes(v3.read_bytes() + b" ")
    changed_v3_sha256 = hashlib.sha256(v3.read_bytes()).hexdigest()

    projection = _source(
        v3,
        v4,
        v3_expected_content_sha256=changed_v3_sha256,
    ).project(scope=global_evaluation_evidence_scope())

    assert [item.verification_status for item in projection.reports] == [
        "VERIFIED",
        "VERIFIED",
    ]
    assert projection.pair_binding_status == "FAILED_CLOSED"
    assert projection.status == "HOLD"
    assert projection.availability == "UNAVAILABLE"
    assert "V3_V4_BINDING_FAILED_CLOSED" in projection.failure_codes


def test_frozen_file_sha_rejects_reformatted_but_self_consistent_report(
    tmp_path: Path,
) -> None:
    v3, v4 = _copy_frozen_reports(tmp_path)
    v3.write_bytes(v3.read_bytes() + b" ")

    projection = _source(v3, v4).project(scope=global_evaluation_evidence_scope())

    assert projection.status == "HOLD"
    assert projection.reports[0].verification_status == "FAILED_CLOSED"
    assert projection.reports[0].verification_error_code == (
        "V3_FROZEN_CONTENT_SHA256_MISMATCH"
    )
    assert projection.reports[0].core_metrics is None


def test_tampered_v4_hash_returns_unavailable_hold(tmp_path: Path) -> None:
    v3, v4 = _copy_frozen_reports(tmp_path)
    payload = json.loads(v4.read_text(encoding="utf-8"))
    payload["metrics"]["passed_count"] = 3
    v4.write_bytes(canonical_json_bytes(payload))
    tampered_v4_sha256 = hashlib.sha256(v4.read_bytes()).hexdigest()

    projection = _source(
        v3,
        v4,
        v4_expected_content_sha256=tampered_v4_sha256,
    ).project(scope=global_evaluation_evidence_scope())

    assert projection.status == "HOLD"
    assert projection.reports[1].availability == "UNAVAILABLE"
    assert projection.reports[1].verification_error_code == (
        "V4_REPORT_CONTRACT_INVALID"
    )
    assert projection.reports[1].core_metrics is None


def test_self_resealed_v4_factory_claim_is_rejected_by_projection_boundary(
    tmp_path: Path,
) -> None:
    v3, v4 = _copy_frozen_reports(tmp_path)
    payload = json.loads(v4.read_text(encoding="utf-8"))
    payload["data_source_status"] = "FACTORY_SHADOW_DATA"
    unsealed = {
        key: value for key, value in payload.items() if key != "sealed_report_sha256"
    }
    payload["sealed_report_sha256"] = v4_framed_sha256(
        V4_HASH_DOMAINS["report"], unsealed
    )
    validate_dynamic_benchmark_v4_report(payload)
    v4.write_bytes(canonical_json_bytes(payload))
    resealed_v4_sha256 = hashlib.sha256(v4.read_bytes()).hexdigest()

    projection = _source(
        v3,
        v4,
        v4_expected_content_sha256=resealed_v4_sha256,
    ).project(scope=global_evaluation_evidence_scope())

    assert projection.status == "HOLD"
    assert projection.reports[1].availability == "UNAVAILABLE"
    assert projection.reports[1].verification_error_code == (
        "V4_REPORT_CONTRACT_INVALID"
    )
    assert projection.factory_metrics_status == "NOT_MEASURED_BY_DYNAMICBENCH"


def test_read_only_api_supports_global_and_tenant_scoped_reference(
    tmp_path: Path,
) -> None:
    v3, v4 = _copy_frozen_reports(tmp_path)
    service = ProductService(tmp_path / "product", recover_interrupted=False)
    client = TestClient(
        create_app(
            service,
            enable_account_bootstrap=True,
            ensure_demo_tenant=False,
            evaluation_evidence_source=_source(v3, v4),
        )
    )
    user = client.post("/v1/users", json={"display_name": "Evidence Reviewer"}).json()
    headers = {"X-Actor-User-Id": user["user_id"]}
    workspace = client.post(
        "/v1/workspaces",
        headers=headers,
        json={"name": "Evidence Workspace", "owner_user_id": user["user_id"]},
    ).json()
    project = client.post(
        "/v1/projects",
        headers=headers,
        json={"workspace_id": workspace["workspace_id"], "name": "Evidence Project"},
    ).json()

    global_response = client.get("/v1/review/evaluation-evidence/dynamicbench")
    assert global_response.status_code == 200
    assert global_response.json()["scope"]["scope_kind"] == "GLOBAL_REVIEW"
    assert global_response.headers["cache-control"] == "no-store"
    assert (
        global_response.headers["x-evaluation-evidence-sha256"]
        == (global_response.json()["projection_sha256"])
    )

    scoped = client.get(
        f"/v1/workspaces/{workspace['workspace_id']}/evaluation-evidence/dynamicbench",
        params={"project_id": project["project_id"]},
        headers=headers,
    )
    assert scoped.status_code == 200
    assert scoped.json()["scope"] == {
        "scope_kind": "PROJECT_REFERENCE",
        "workspace_id": workspace["workspace_id"],
        "project_id": project["project_id"],
        "association_status": "REFERENCE_ONLY_NOT_PROJECT_DERIVED",
        "read_only": True,
    }

    intruder = client.post("/v1/users", json={"display_name": "Other User"}).json()
    hidden = client.get(
        f"/v1/workspaces/{workspace['workspace_id']}/evaluation-evidence/dynamicbench",
        headers={"X-Actor-User-Id": intruder["user_id"]},
    )
    assert hidden.status_code == 404
    assert client.post("/v1/review/evaluation-evidence/dynamicbench").status_code == 405
    service.close(wait=True)
