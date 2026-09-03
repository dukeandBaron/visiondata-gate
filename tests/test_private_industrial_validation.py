from __future__ import annotations

import hashlib
import json
from pathlib import Path

from fastapi.testclient import TestClient
import pytest

from visiondata_gate.api import create_app
from visiondata_gate.private_industrial_validation import (
    DEFAULT_VISA_COMPACT_RECEIPT_PATH,
    DYNAMIC_CAPABILITY_CLAIM,
    PrivateIndustrialValidationSource,
    global_industrial_validation_scope,
    verify_private_industrial_validation_summary,
)
from visiondata_gate.product_service import ProductService


pytestmark = pytest.mark.tier_integration


def _copy_compact_receipt(tmp_path: Path) -> Path:
    destination = tmp_path / "visa_public_proxy_summary.v1.json"
    destination.write_bytes(DEFAULT_VISA_COMPACT_RECEIPT_PATH.read_bytes())
    return destination


def _project(source: PrivateIndustrialValidationSource):
    return source.project(scope=global_industrial_validation_scope())


def test_projection_separates_public_proxy_offline_and_factory_tracks() -> None:
    projection = _project(PrivateIndustrialValidationSource())

    assert projection.status == "HOLD"
    assert projection.availability == (
        "CURRENT_PUBLIC_PROXY_WITH_HISTORICAL_OFFLINE_EVIDENCE"
    )
    assert projection.verification_status == "VERIFIED_BOUNDED_PROJECTION"
    assert projection.production_release_allowed is False
    assert projection.machine_write_permitted is False
    assert projection.read_only is True
    verify_private_industrial_validation_summary(projection)

    visa = projection.visa_public_proxy
    assert visa is not None
    assert visa.evidence_track == (
        "PUBLIC_INDUSTRIAL_PROXY_WITH_PROGRAMMATIC_GOVERNANCE_TRUTH"
    )
    assert visa.evidence_origin == "CURRENT_ENVIRONMENT_RECOMPUTED_RECEIPT"
    assert visa.recomputable_now is True
    assert visa.status == "VERIFIED_CURRENT_ENVIRONMENT_RECOMPUTED"
    assert visa.benchmark_file_sha256 == (
        "d9aea6dff535220e35f0dba0a93271314c082fe10be7ca570f73d01f37966ae6"
    )
    assert visa.benchmark_report_sha256 == (
        "1e332d3852100c00db60ed739fa5219b198c6e608ecb3e3a977c8aa9dc5cfa2c"
    )
    assert visa.implementation_receipt_sha256 == (
        "7966b61b18bafd7a17f23427e6b50bd0ee30849ab7e60343dcc54b9a408896bf"
    )
    assert visa.dynamic_capability_claim == DYNAMIC_CAPABILITY_CLAIM
    assert visa.core_component_binding.status == "MATCHED"
    assert visa.core_component_binding.matched_count == 17
    assert visa.core_component_binding.total_count == 17
    assert visa.project_environment_binding.status == "MATCHED"
    assert visa.project_environment_binding.matched_count == 2
    assert visa.project_environment_binding.total_count == 2
    assert visa.project_environment_binding.mismatched_artifacts == []

    assert [group.scenario_group for group in visa.scenario_groups] == [
        "NORMAL_NO_FAULT",
        "TRANSIENT_RECOVERABLE_FAULT",
        "PERSISTENT_FAULT_SAFETY_COST",
    ]
    assert [group.episode_denominator for group in visa.scenario_groups] == [
        300,
        150,
        150,
    ]
    assert sum(group.episode_denominator for group in visa.scenario_groups) == 600
    transient_dynamic = visa.scenario_groups[1].strategies[2]
    assert transient_dynamic.transient_recovery_rate.numerator == 150
    assert transient_dynamic.transient_recovery_rate.denominator == 150
    persistent_dynamic = visa.scenario_groups[2].strategies[2]
    assert persistent_dynamic.non_retryable_retry_rate.numerator == 0
    assert persistent_dynamic.non_retryable_retry_rate.denominator == 150

    omni = projection.omni_offline_validation
    assert omni.evidence_track == "DATASET_OFFLINE_VALIDATION"
    assert omni.recomputable_now is False
    assert omni.factory_shadow_equivalent is False
    assert (
        omni.source_profile_image_count,
        omni.source_profile_mask_count,
        omni.fixed_gate_sample_count,
        omni.parent_finding_count,
        omni.child_finding_count,
        omni.finding_count_delta,
        omni.verified_closed_responsibility_count,
        omni.open_responsibility_count,
    ) == (4464, 1439, 180, 49, 33, -16, 6, 43)

    factory = projection.factory_shadow_metrics
    assert factory.evidence_track == "FACTORY_SHADOW_METRICS"
    assert factory.status == "NOT_MEASURED_PENDING_ADJUDICATION"
    for metric in (
        factory.false_release_rate,
        factory.false_block_rate,
        factory.remediation_pass_rate,
    ):
        assert metric.status == "NOT_MEASURED_PENDING_ADJUDICATION"
        assert metric.numerator is None
        assert metric.denominator is None
        assert metric.value is None
        assert metric.wilson_95_lower is None
        assert metric.wilson_95_upper is None


def test_missing_compact_receipt_fails_closed_without_proxy_metrics(
    tmp_path: Path,
) -> None:
    source = PrivateIndustrialValidationSource(
        visa_compact_receipt_path=tmp_path / "missing.json"
    )

    projection = _project(source)

    assert projection.status == "HOLD"
    assert projection.verification_status == "FAILED_CLOSED"
    assert projection.availability == (
        "PUBLIC_PROXY_UNAVAILABLE_WITH_HISTORICAL_OFFLINE_EVIDENCE"
    )
    assert projection.visa_public_proxy is None
    assert "VISA_COMPACT_RECEIPT_MISSING" in projection.failure_codes


def test_compact_receipt_file_sha_drift_fails_closed(tmp_path: Path) -> None:
    receipt = _copy_compact_receipt(tmp_path)
    receipt.write_bytes(receipt.read_bytes() + b"\n")

    projection = _project(
        PrivateIndustrialValidationSource(visa_compact_receipt_path=receipt)
    )

    assert projection.verification_status == "FAILED_CLOSED"
    assert projection.availability == (
        "PUBLIC_PROXY_UNAVAILABLE_WITH_HISTORICAL_OFFLINE_EVIDENCE"
    )
    assert projection.visa_public_proxy is None
    assert "VISA_COMPACT_RECEIPT_CONTENT_SHA256_MISMATCH" in projection.failure_codes


def test_compact_receipt_internal_seal_tamper_fails_closed(tmp_path: Path) -> None:
    receipt = _copy_compact_receipt(tmp_path)
    payload = json.loads(receipt.read_text(encoding="utf-8"))
    payload["scenario_groups"][0]["strategies"][0]["physical_tool_call_count"] += 1
    receipt.write_text(
        json.dumps(payload, ensure_ascii=False, separators=(",", ":")),
        encoding="utf-8",
    )
    tampered_file_sha256 = hashlib.sha256(receipt.read_bytes()).hexdigest()

    projection = _project(
        PrivateIndustrialValidationSource(
            visa_compact_receipt_path=receipt,
            expected_visa_compact_receipt_content_sha256=tampered_file_sha256,
        )
    )

    assert projection.verification_status == "FAILED_CLOSED"
    assert projection.availability == (
        "PUBLIC_PROXY_UNAVAILABLE_WITH_HISTORICAL_OFFLINE_EVIDENCE"
    )
    assert projection.visa_public_proxy is None
    assert "VISA_COMPACT_RECEIPT_CONTRACT_INVALID" in projection.failure_codes


def test_api_binds_projection_digest_and_enforces_workspace_visibility(
    tmp_path: Path,
) -> None:
    service = ProductService(tmp_path / "product", recover_interrupted=False)
    try:
        client = TestClient(
            create_app(
                service,
                enable_account_bootstrap=True,
                ensure_demo_tenant=False,
            )
        )
        owner = client.post("/v1/users", json={"display_name": "Evidence Owner"})
        assert owner.status_code == 201
        owner_id = owner.json()["user_id"]
        owner_headers = {"X-Actor-User-Id": owner_id}
        workspace = client.post(
            "/v1/workspaces",
            headers=owner_headers,
            json={"name": "Evidence Workspace", "owner_user_id": owner_id},
        )
        assert workspace.status_code == 201
        workspace_id = workspace.json()["workspace_id"]
        project = client.post(
            "/v1/projects",
            headers=owner_headers,
            json={"workspace_id": workspace_id, "name": "Evidence Project"},
        )
        assert project.status_code == 201
        project_id = project.json()["project_id"]

        global_response = client.get(
            "/v1/review/evaluation-evidence/industrial-validation"
        )
        assert global_response.status_code == 200
        global_payload = global_response.json()
        assert global_payload["scope"]["scope_kind"] == "GLOBAL_REVIEW"
        assert global_response.headers["etag"] == (
            f'"{global_payload["projection_sha256"]}"'
        )
        assert (
            global_response.headers["x-content-sha256"]
            == (global_payload["projection_sha256"])
        )
        assert global_response.headers["cache-control"] == "private, no-store"
        assert (
            client.head(
                "/v1/review/evaluation-evidence/industrial-validation"
            ).status_code
            == 405
        )
        conditional = client.get(
            "/v1/review/evaluation-evidence/industrial-validation",
            headers={"If-None-Match": global_response.headers["etag"]},
        )
        assert conditional.status_code == 200
        assert (
            conditional.json()["projection_sha256"]
            == (global_payload["projection_sha256"])
        )

        scoped_response = client.get(
            f"/v1/workspaces/{workspace_id}/evaluation-evidence/industrial-validation",
            headers=owner_headers,
            params={"project_id": project_id},
        )
        assert scoped_response.status_code == 200
        scoped_payload = scoped_response.json()
        assert scoped_payload["scope"] == {
            "scope_kind": "PROJECT_REFERENCE",
            "workspace_id": workspace_id,
            "project_id": project_id,
            "association_status": "REFERENCE_ONLY_NOT_PROJECT_DERIVED",
            "read_only": True,
        }
        assert scoped_response.headers["etag"] == (
            f'"{scoped_payload["projection_sha256"]}"'
        )
        assert (
            scoped_response.headers["x-content-sha256"]
            == (scoped_payload["projection_sha256"])
        )

        intruder = client.post("/v1/users", json={"display_name": "Intruder"})
        assert intruder.status_code == 201
        hidden = client.get(
            f"/v1/workspaces/{workspace_id}/evaluation-evidence/industrial-validation",
            headers={"X-Actor-User-Id": intruder.json()["user_id"]},
        )
        assert hidden.status_code == 404
        assert (
            client.post(
                "/v1/review/evaluation-evidence/industrial-validation"
            ).status_code
            == 405
        )
    finally:
        service.close(wait=True)


def test_current_receipt_fails_closed_when_project_identity_drifts(
    tmp_path: Path,
) -> None:
    projection = _project(PrivateIndustrialValidationSource(project_root=tmp_path))

    assert projection.status == "HOLD"
    assert projection.verification_status == "FAILED_CLOSED"
    assert projection.availability == (
        "PUBLIC_PROXY_UNAVAILABLE_WITH_HISTORICAL_OFFLINE_EVIDENCE"
    )
    assert projection.visa_public_proxy is None
    assert "VISA_CURRENT_CORE_COMPONENT_BINDING_NOT_MATCHED" in projection.failure_codes
    assert "VISA_PROJECT_ENVIRONMENT_BINDING_NOT_MATCHED" in projection.failure_codes


def test_scoped_api_returns_503_when_private_session_is_not_configured(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("VISIONDATA_INSECURE_TEST_ACTOR_HEADER_BYPASS", "false")
    service = ProductService(tmp_path / "product", recover_interrupted=False)
    try:
        client = TestClient(
            create_app(
                service,
                enable_account_bootstrap=False,
                ensure_demo_tenant=True,
            )
        )
        response = client.get(
            "/v1/workspaces/wsp_local_demo/evaluation-evidence/industrial-validation",
            headers={"X-Actor-User-Id": "usr_local_demo"},
        )

        assert response.status_code == 503
        assert response.json()["error"]["code"] == "local_session_not_configured"
    finally:
        service.close(wait=True)


def test_projection_json_does_not_disclose_host_paths_or_user_name() -> None:
    projection = _project(PrivateIndustrialValidationSource())
    serialized = projection.model_dump_json()

    assert "F:\\" not in serialized
    assert "C:\\" not in serialized
    assert str(Path.cwd()) not in serialized
    assert "living" not in serialized.casefold()
