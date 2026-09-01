from __future__ import annotations

import hashlib
import json
from pathlib import Path

from fastapi.testclient import TestClient
import pytest
import rfc8785

from tests.test_product_service_omni import (
    _authorization,
    _build_source,
    _workspace,
)
from visiondata_gate.api import create_app
from visiondata_gate.governance_effectiveness import (
    CreateIndustrialShadowEvaluationRequest,
    CreateShadowEvaluationManifestV2Request,
    IndustrialShadowBatchIdentity,
    IndustrialShadowEvaluationReceipt,
    ShadowConfusionCounts,
    ShadowEvaluationManifestV2,
    ShadowEvaluationUnitV2,
    ShadowRemediationCounts,
    ShadowV2HashDomain,
    build_industrial_shadow_evaluation_receipt,
    build_project_governance_effectiveness_summary,
    build_shadow_evaluation_manifest_v2,
    shadow_evaluation_request_sha256,
    shadow_v2_domain_separated_sha256,
    verify_industrial_shadow_evaluation_receipt,
    verify_project_governance_effectiveness_summary,
    verify_shadow_evaluation_manifest_v2,
)
from visiondata_gate.product_models import (
    CreateProjectRequest,
    CreateTaskRequest,
    DataSourceKind,
    TaskExecutionStatus,
)
from visiondata_gate.product_service import ArtifactUnavailableError, ProductService


def _request() -> CreateIndustrialShadowEvaluationRequest:
    return CreateIndustrialShadowEvaluationRequest(
        identity=IndustrialShadowBatchIdentity(
            dataset_namespace="authorized-history-v1",
            site_alias="site-a",
            line_alias="line-01",
            station_alias="aoi-07",
            camera_alias="camera-main",
            batch_alias="batch-2026-08-29-a",
            captured_from="2026-08-20T00:00:00+08:00",
            captured_to="2026-08-21T00:00:00+08:00",
        ),
        ground_truth_method="dual_human_adjudication",
        truth_manifest_sha256="1" * 64,
        gate_output_manifest_sha256="2" * 64,
        confusion=ShadowConfusionCounts(
            unit_of_analysis="inspection image",
            true_block_count=17,
            false_release_count=1,
            true_release_count=31,
            false_block_count=3,
        ),
        remediation=ShadowRemediationCounts(
            verified_pass_count=8,
            verified_fail_count=2,
            unresolved_count=2,
        ),
        note="Two quality reviewers reconciled the historical batch labels.",
        operator_attests_authorized_historical_use=True,
        operator_attests_labels_reviewed=True,
    )


def _v2_request() -> CreateShadowEvaluationManifestV2Request:
    evidence_digests = [f"{index:064x}" for index in range(1, 13)]
    return CreateShadowEvaluationManifestV2Request(
        identity=_request().identity,
        unit_of_analysis="inspection image",
        ground_truth_method="dual_human_adjudication",
        units=[
            ShadowEvaluationUnitV2(
                unit_id="unit_0000000000000004",
                truth_disposition="RELEASE",
                gate_disposition="BLOCK",
                truth_evidence_sha256=evidence_digests[0],
                gate_evidence_sha256=evidence_digests[1],
            ),
            ShadowEvaluationUnitV2(
                unit_id="unit_0000000000000002",
                truth_disposition="BLOCK",
                gate_disposition="RELEASE",
                truth_evidence_sha256=evidence_digests[2],
                gate_evidence_sha256=evidence_digests[3],
                remediation_outcome="VERIFIED_FAIL",
                remediation_evidence_sha256=evidence_digests[4],
            ),
            ShadowEvaluationUnitV2(
                unit_id="unit_0000000000000001",
                truth_disposition="BLOCK",
                gate_disposition="BLOCK",
                truth_evidence_sha256=evidence_digests[5],
                gate_evidence_sha256=evidence_digests[6],
                remediation_outcome="VERIFIED_PASS",
                remediation_evidence_sha256=evidence_digests[7],
            ),
            ShadowEvaluationUnitV2(
                unit_id="unit_0000000000000003",
                truth_disposition="RELEASE",
                gate_disposition="RELEASE",
                truth_evidence_sha256=evidence_digests[8],
                gate_evidence_sha256=evidence_digests[9],
                remediation_outcome="UNRESOLVED",
                remediation_evidence_sha256=evidence_digests[10],
            ),
        ],
        note="Per-unit truth and Gate records were reviewed outside the Agent core.",
        operator_attests_authorized_historical_use=True,
        operator_attests_labels_reviewed=True,
    )


@pytest.mark.tier_core
def test_shadow_receipt_keeps_independent_denominators_and_seals_content() -> None:
    receipt = build_industrial_shadow_evaluation_receipt(
        request=_request(),
        workspace_id="wrk_test",
        project_id="prj_test",
        task_id="tsk_1234567890abcdef1234",
        source_id="src_test",
        source_authorization_event_sha256="3" * 64,
        task_request_sha256="4" * 64,
        task_evidence_sha256="5" * 64,
        task_final_decision="RECAPTURE",
        created_by="usr_test",
        created_at="2026-08-29T10:00:00+08:00",
    )

    assert receipt.labelled_unit_count == 52
    assert receipt.false_release_rate.numerator == 1
    assert receipt.false_release_rate.denominator == 18
    assert receipt.false_release_rate.value == pytest.approx(1 / 18)
    assert receipt.false_block_rate.numerator == 3
    assert receipt.false_block_rate.denominator == 34
    assert receipt.verified_remediation_pass_rate.value == pytest.approx(0.8)
    assert receipt.unresolved_remediation_rate.value == pytest.approx(2 / 12)
    assert receipt.measurement_status == "MEASURED"
    assert receipt.raw_images_transmitted is False
    assert receipt.production_release_allowed is False
    verify_industrial_shadow_evaluation_receipt(receipt)

    tampered = receipt.model_copy(
        update={"task_final_decision": "PASS"},
    )
    with pytest.raises(ValueError, match="digest mismatch"):
        verify_industrial_shadow_evaluation_receipt(tampered)

    inconsistent = receipt.model_dump(mode="json")
    inconsistent["confusion"]["false_release_count"] = 2
    inconsistent["confusion"]["true_block_count"] = 16
    with pytest.raises(ValueError, match="counts do not reconcile"):
        IndustrialShadowEvaluationReceipt.model_validate(inconsistent)


@pytest.mark.tier_core
def test_shadow_v1_historical_digest_vectors_remain_byte_compatible() -> None:
    request = _request()
    request_sha256 = shadow_evaluation_request_sha256(
        request,
        task_id="tsk_1234567890abcdef1234",
        task_request_sha256="4" * 64,
        task_evidence_sha256="5" * 64,
        source_authorization_event_sha256="3" * 64,
    )
    receipt = build_industrial_shadow_evaluation_receipt(
        request=request,
        workspace_id="wrk_test",
        project_id="prj_test",
        task_id="tsk_1234567890abcdef1234",
        source_id="src_test",
        source_authorization_event_sha256="3" * 64,
        task_request_sha256="4" * 64,
        task_evidence_sha256="5" * 64,
        task_final_decision="RECAPTURE",
        created_by="usr_test",
        created_at="2026-08-29T10:00:00+08:00",
    )

    assert request_sha256 == (
        "4222adccdd02d10e3cf9285a5eabd5eda908e1a2f6e5537dc5660394695f5a07"
    )
    assert receipt.receipt_sha256 == (
        "8f52c77311ede6b6a68d60719d0b00aead015d377f3e945a1aa449b318c0929f"
    )


@pytest.mark.tier_core
def test_shadow_request_rejects_empty_label_denominator() -> None:
    with pytest.raises(ValueError, match="at least one labelled unit"):
        ShadowConfusionCounts(
            unit_of_analysis="inspection image",
            true_block_count=0,
            false_release_count=0,
            true_release_count=0,
            false_block_count=0,
        )


@pytest.mark.tier_core
def test_shadow_v2_derives_all_counts_from_canonical_per_unit_records() -> None:
    request = _v2_request()
    manifest = build_shadow_evaluation_manifest_v2(
        request=request,
        workspace_id="wrk_test",
        project_id="prj_test",
        task_id="tsk_test",
        source_id="src_test",
        source_authorization_event_sha256="a" * 64,
        task_request_sha256="b" * 64,
        task_evidence_sha256="c" * 64,
        task_final_decision="RECAPTURE",
        created_by="usr_test",
        created_at="2026-08-29T12:00:00+08:00",
    )

    assert [item.unit_id for item in manifest.units] == sorted(
        item.unit_id for item in request.units
    )
    assert manifest.labelled_unit_count == 4
    assert manifest.confusion.true_block_count == 1  # TP: block required and blocked
    assert manifest.confusion.true_release_count == 1  # TN: releasable and released
    assert manifest.confusion.false_block_count == 1  # FP: releasable but blocked
    assert (
        manifest.confusion.false_release_count == 1
    )  # FN: block required but released
    assert manifest.remediation.verified_pass_count == 1
    assert manifest.remediation.verified_fail_count == 1
    assert manifest.remediation.unresolved_count == 1
    assert manifest.false_release_rate.denominator == 2
    assert manifest.false_block_rate.denominator == 2
    assert manifest.verified_remediation_pass_rate.value == pytest.approx(0.5)
    assert manifest.unresolved_remediation_rate.value == pytest.approx(1 / 3)
    assert manifest.server_computed_counts is True
    assert manifest.client_supplied_aggregate_counts_accepted is False
    assert manifest.shadow_labels_enter_agent_core is False
    assert manifest.raw_images_transmitted is False
    assert manifest.production_release_allowed is False
    assert manifest.hash_algorithm == "sha256"
    assert manifest.canonicalization_profile == "rfc8785-jcs-v1"
    assert manifest.framing_profile == "visiondata-gate-shadow-v2-domain-frame-v1"
    assert "domain_length" in manifest.frame_construction
    assert "payload_length" in manifest.frame_construction
    assert "digital signature" in manifest.claim_boundary
    assert "trusted timestamp" in manifest.claim_boundary
    verify_shadow_evaluation_manifest_v2(manifest)

    reordered = request.model_copy(update={"units": list(reversed(request.units))})
    reordered_manifest = build_shadow_evaluation_manifest_v2(
        request=reordered,
        workspace_id="wrk_test",
        project_id="prj_test",
        task_id="tsk_test",
        source_id="src_test",
        source_authorization_event_sha256="a" * 64,
        task_request_sha256="b" * 64,
        task_evidence_sha256="c" * 64,
        task_final_decision="RECAPTURE",
        created_by="usr_test",
        created_at="2026-08-29T12:00:00+08:00",
    )
    assert reordered_manifest == manifest
    assert (
        reordered_manifest.evaluation_manifest_sha256
        == manifest.evaluation_manifest_sha256
    )
    assert reordered_manifest.request_sha256 == manifest.request_sha256

    changed_grain = request.model_copy(update={"unit_of_analysis": "inspection lot"})
    changed_grain_manifest = build_shadow_evaluation_manifest_v2(
        request=changed_grain,
        workspace_id="wrk_test",
        project_id="prj_test",
        task_id="tsk_test",
        source_id="src_test",
        source_authorization_event_sha256="a" * 64,
        task_request_sha256="b" * 64,
        task_evidence_sha256="c" * 64,
        task_final_decision="RECAPTURE",
        created_by="usr_test",
        created_at="2026-08-29T12:00:00+08:00",
    )
    digest_fields = (
        "evaluation_manifest_sha256",
        "truth_manifest_sha256",
        "gate_output_manifest_sha256",
        "remediation_manifest_sha256",
    )
    assert all(
        getattr(changed_grain_manifest, field) != getattr(manifest, field)
        for field in digest_fields
    )


@pytest.mark.tier_core
def test_shadow_v2_jcs_order_and_hash_domains_are_non_interchangeable() -> None:
    first_payload = {"z": [3, 2, 1], "a": {"beta": True, "alpha": 1}}
    reordered_payload = {"a": {"alpha": 1, "beta": True}, "z": [3, 2, 1]}
    domains = list(ShadowV2HashDomain)

    first_digests = {
        domain: shadow_v2_domain_separated_sha256(first_payload, domain)
        for domain in domains
    }
    reordered_digests = {
        domain: shadow_v2_domain_separated_sha256(reordered_payload, domain)
        for domain in domains
    }

    assert first_digests == reordered_digests
    assert len(set(first_digests.values())) == len(domains)

    domain = ShadowV2HashDomain.TRUTH_MANIFEST
    domain_bytes = domain.value.encode("utf-8")
    payload = rfc8785.dumps(first_payload)
    expected_frame = b"".join(
        (
            b"visiondata-gate.shadow-v2-hash-frame.v1\x00",
            len(domain_bytes).to_bytes(2, "big"),
            domain_bytes,
            len(payload).to_bytes(8, "big"),
            payload,
        )
    )
    assert first_digests[domain] == hashlib.sha256(expected_frame).hexdigest()


@pytest.mark.tier_core
def test_shadow_v2_rejects_client_counts_duplicates_and_unbound_remediation() -> None:
    client_aggregate = _v2_request().model_dump(mode="json")
    client_aggregate["confusion"] = {
        "unit_of_analysis": "inspection image",
        "true_block_count": 999,
        "false_release_count": 0,
        "true_release_count": 0,
        "false_block_count": 0,
    }
    with pytest.raises(ValueError, match="Extra inputs are not permitted"):
        CreateShadowEvaluationManifestV2Request.model_validate(client_aggregate)

    duplicate = _v2_request().model_dump(mode="json")
    duplicate["units"][1]["unit_id"] = duplicate["units"][0]["unit_id"]
    with pytest.raises(ValueError, match="unit IDs must be unique"):
        CreateShadowEvaluationManifestV2Request.model_validate(duplicate)

    unbound = _v2_request().model_dump(mode="json")
    unbound["units"][1]["remediation_evidence_sha256"] = None
    with pytest.raises(ValueError, match="requires an evidence digest"):
        CreateShadowEvaluationManifestV2Request.model_validate(unbound)


@pytest.mark.tier_core
def test_shadow_v2_detects_per_unit_semantic_tampering() -> None:
    manifest = build_shadow_evaluation_manifest_v2(
        request=_v2_request(),
        workspace_id="wrk_test",
        project_id="prj_test",
        task_id="tsk_test",
        source_id="src_test",
        source_authorization_event_sha256="a" * 64,
        task_request_sha256="b" * 64,
        task_evidence_sha256="c" * 64,
        task_final_decision="RECAPTURE",
        created_by="usr_test",
        created_at="2026-08-29T12:00:00+08:00",
    )
    tampered = manifest.model_dump(mode="json")
    tampered["units"][0]["gate_disposition"] = "RELEASE"
    with pytest.raises(ValueError, match="derived manifest digest mismatch"):
        ShadowEvaluationManifestV2.model_validate(tampered)

    rebound = manifest.model_dump(mode="json")
    rebound["task_evidence_sha256"] = "d" * 64
    with pytest.raises(ValueError, match="source binding mismatch|binding digest"):
        ShadowEvaluationManifestV2.model_validate(rebound)

    outer_tamper = manifest.model_copy(update={"created_by": "usr_other"})
    with pytest.raises(ValueError, match="evaluation manifest digest mismatch"):
        verify_shadow_evaluation_manifest_v2(outer_tamper)

    profile_tamper = manifest.model_dump(mode="json")
    profile_tamper["canonicalization_profile"] = "python-json-sort-keys"
    with pytest.raises(ValueError, match="rfc8785-jcs-v1"):
        ShadowEvaluationManifestV2.model_validate(profile_tamper)


@pytest.mark.tier_core
def test_project_summary_never_pools_incompatible_analysis_units() -> None:
    first = build_industrial_shadow_evaluation_receipt(
        request=_request(),
        workspace_id="wrk_test",
        project_id="prj_test",
        task_id="tsk_first",
        source_id="src_first",
        source_authorization_event_sha256="3" * 64,
        task_request_sha256="4" * 64,
        task_evidence_sha256="5" * 64,
        task_final_decision="RECAPTURE",
        created_by="usr_test",
        created_at="2026-08-29T10:00:00+08:00",
    )
    second_request = _request().model_copy(
        update={
            "identity": _request().identity.model_copy(
                update={"batch_alias": "batch-2026-08-29-b"}
            ),
            "confusion": ShadowConfusionCounts(
                unit_of_analysis="production lot",
                true_block_count=2,
                false_release_count=1,
                true_release_count=7,
                false_block_count=0,
            ),
        }
    )
    second = build_industrial_shadow_evaluation_receipt(
        request=second_request,
        workspace_id="wrk_test",
        project_id="prj_test",
        task_id="tsk_second",
        source_id="src_second",
        source_authorization_event_sha256="6" * 64,
        task_request_sha256="7" * 64,
        task_evidence_sha256="8" * 64,
        task_final_decision="RECAPTURE",
        created_by="usr_test",
        created_at="2026-08-29T11:00:00+08:00",
    )

    summary = build_project_governance_effectiveness_summary(
        workspace_id="wrk_test",
        project_id="prj_test",
        receipts=[second, first],
    )

    assert summary.confusion_pooling_status == "GROUPED_BY_UNIT"
    assert summary.receipt_count == 2
    assert summary.task_count == 2
    assert summary.labelled_unit_count == 62
    assert [item.unit_of_analysis for item in summary.confusion_groups] == [
        "inspection image",
        "production lot",
    ]
    assert summary.confusion_groups[0].false_release_rate.denominator == 18
    assert summary.confusion_groups[1].false_release_rate.denominator == 3
    assert summary.verified_remediation_pass_rate.numerator == 16
    assert summary.verified_remediation_pass_rate.denominator == 20
    verify_project_governance_effectiveness_summary(summary)

    tampered = summary.model_copy(update={"labelled_unit_count": 63})
    with pytest.raises(ValueError, match="summary digest mismatch"):
        verify_project_governance_effectiveness_summary(tampered)


@pytest.mark.tier_core
def test_project_summary_combines_v1_and_v2_only_within_one_analysis_unit() -> None:
    legacy = build_industrial_shadow_evaluation_receipt(
        request=_request(),
        workspace_id="wrk_test",
        project_id="prj_test",
        task_id="tsk_legacy",
        source_id="src_legacy",
        source_authorization_event_sha256="3" * 64,
        task_request_sha256="4" * 64,
        task_evidence_sha256="5" * 64,
        task_final_decision="RECAPTURE",
        created_by="usr_test",
        created_at="2026-08-29T10:00:00+08:00",
    )
    per_unit = build_shadow_evaluation_manifest_v2(
        request=_v2_request(),
        workspace_id="wrk_test",
        project_id="prj_test",
        task_id="tsk_v2",
        source_id="src_v2",
        source_authorization_event_sha256="a" * 64,
        task_request_sha256="b" * 64,
        task_evidence_sha256="c" * 64,
        task_final_decision="RECAPTURE",
        created_by="usr_test",
        created_at="2026-08-29T11:00:00+08:00",
    )

    summary = build_project_governance_effectiveness_summary(
        workspace_id="wrk_test",
        project_id="prj_test",
        receipts=[per_unit, legacy],
    )

    assert summary.receipt_count == 2
    assert summary.labelled_unit_count == 56
    assert summary.confusion_pooling_status == "SINGLE_UNIT"
    group = summary.confusion_groups[0]
    assert group.false_release_rate.numerator == 2
    assert group.false_release_rate.denominator == 20
    assert group.false_block_rate.numerator == 4
    assert group.false_block_rate.denominator == 36
    assert summary.verified_remediation_pass_rate.numerator == 9
    assert summary.verified_remediation_pass_rate.denominator == 12
    verify_project_governance_effectiveness_summary(summary)


@pytest.mark.tier_integration
def test_product_service_persists_idempotent_shadow_receipt_separately(
    tmp_path: Path,
) -> None:
    allowed = tmp_path / "allowed"
    release, _ = _build_source(allowed)
    product_root = tmp_path / "product"
    service = ProductService(
        product_root,
        local_source_allow_roots=[allowed],
        recover_interrupted=False,
    )
    actor, workspace_id = _workspace(service)
    source = service.authorize_local_source(
        actor,
        _authorization(workspace_id=workspace_id, release=release),
    )
    project = service.create_project(
        actor,
        CreateProjectRequest(
            workspace_id=workspace_id,
            name="Historical Shadow",
            source_kind=DataSourceKind.LOCAL_AUTHORIZED_DIRECTORY,
        ),
    )
    task = service.create_task(
        actor,
        CreateTaskRequest(
            project_id=project.project_id,
            goal="Run one read-only historical industrial batch through the frozen Gate.",
            source_kind=DataSourceKind.LOCAL_AUTHORIZED_DIRECTORY,
            source_id=source.source_id,
        ),
        auto_start=False,
    )
    assert task.execution_status is TaskExecutionStatus.PLANNED
    service.store.transition_task(
        task.task_id,
        TaskExecutionStatus.RUNNING,
        current_phase="running",
    )
    service.store.transition_task(
        task.task_id,
        TaskExecutionStatus.COMPLETED,
        current_phase="completed",
        fields={
            "final_decision": "RECAPTURE",
            "evidence_sha256": "6" * 64,
            "completed_at": "2026-08-29T10:00:00+00:00",
        },
    )

    created = service.create_industrial_shadow_evaluation(
        actor,
        task.task_id,
        _request(),
    )
    replay = service.create_industrial_shadow_evaluation(
        actor,
        task.task_id,
        _request(),
    )
    assert replay == created
    assert service.list_industrial_shadow_evaluations(actor, task.task_id) == [created]
    summary = service.project_governance_effectiveness(actor, project.project_id)
    assert summary.confusion_pooling_status == "SINGLE_UNIT"
    assert summary.receipt_count == 1
    assert summary.confusion_groups[0].false_release_rate.denominator == 18
    assert not (product_root / "runs" / task.task_id / "evidence").exists()

    client = TestClient(create_app(service, ensure_demo_tenant=False))
    headers = {"X-Actor-User-Id": actor}
    listed = client.get(
        f"/v1/tasks/{task.task_id}/industrial-shadow-evaluations",
        headers=headers,
    )
    assert listed.status_code == 200
    assert listed.json()[0]["receipt_id"] == created.receipt_id
    idempotent_post = client.post(
        f"/v1/tasks/{task.task_id}/industrial-shadow-evaluations",
        headers=headers,
        json=_request().model_dump(mode="json"),
    )
    assert idempotent_post.status_code == 201
    assert idempotent_post.json()["receipt_id"] == created.receipt_id
    project_summary = client.get(
        f"/v1/projects/{project.project_id}/governance-effectiveness",
        headers=headers,
    )
    assert project_summary.status_code == 200
    assert project_summary.json()["receipt_count"] == 1
    assert project_summary.json()["confusion_pooling_status"] == "SINGLE_UNIT"

    receipt_path = (
        product_root
        / "shadow_evaluations"
        / workspace_id
        / project.project_id
        / task.task_id
        / f"{created.receipt_id}.json"
    )
    payload = json.loads(receipt_path.read_text(encoding="utf-8"))
    payload["task_final_decision"] = "PASS"
    receipt_path.write_text(json.dumps(payload), encoding="utf-8")
    with pytest.raises(ArtifactUnavailableError, match="integrity"):
        service.list_industrial_shadow_evaluations(actor, task.task_id)


@pytest.mark.tier_integration
def test_shadow_v2_api_persists_recomputes_and_rejects_client_aggregates(
    tmp_path: Path,
) -> None:
    allowed = tmp_path / "allowed"
    release, _ = _build_source(allowed)
    product_root = tmp_path / "product"
    service = ProductService(
        product_root,
        local_source_allow_roots=[allowed],
        recover_interrupted=False,
    )
    actor, workspace_id = _workspace(service)
    source = service.authorize_local_source(
        actor,
        _authorization(workspace_id=workspace_id, release=release),
    )
    project = service.create_project(
        actor,
        CreateProjectRequest(
            workspace_id=workspace_id,
            name="Per-unit Historical Shadow",
            source_kind=DataSourceKind.LOCAL_AUTHORIZED_DIRECTORY,
        ),
    )
    task = service.create_task(
        actor,
        CreateTaskRequest(
            project_id=project.project_id,
            goal="Evaluate a pseudonymous per-unit historical batch after the Gate run.",
            source_kind=DataSourceKind.LOCAL_AUTHORIZED_DIRECTORY,
            source_id=source.source_id,
        ),
        auto_start=False,
    )
    client = TestClient(create_app(service, ensure_demo_tenant=False))
    headers = {"X-Actor-User-Id": actor}
    endpoint = f"/v1/tasks/{task.task_id}/industrial-shadow-evaluation-manifests"

    planned = client.post(
        endpoint,
        headers=headers,
        json=_v2_request().model_dump(mode="json"),
    )
    assert planned.status_code == 409

    service.store.transition_task(
        task.task_id,
        TaskExecutionStatus.RUNNING,
        current_phase="running",
    )
    service.store.transition_task(
        task.task_id,
        TaskExecutionStatus.COMPLETED,
        current_phase="completed",
        fields={
            "final_decision": "RECAPTURE",
            "evidence_sha256": "d" * 64,
            "completed_at": "2026-08-29T12:00:00+00:00",
        },
    )

    created_response = client.post(
        endpoint,
        headers=headers,
        json=_v2_request().model_dump(mode="json"),
    )
    assert created_response.status_code == 201
    created = ShadowEvaluationManifestV2.model_validate(created_response.json())
    assert created.confusion.false_release_count == 1
    assert created.confusion.false_block_count == 1
    assert created.server_computed_counts is True
    assert (
        service.create_shadow_evaluation_manifest_v2(
            actor,
            task.task_id,
            _v2_request(),
        )
        == created
    )

    listed = client.get(endpoint, headers=headers)
    assert listed.status_code == 200
    assert [item["receipt_id"] for item in listed.json()] == [created.receipt_id]
    summary = service.project_governance_effectiveness(actor, project.project_id)
    assert summary.receipt_count == 1
    assert summary.labelled_unit_count == 4
    assert summary.confusion_groups[0].false_release_rate.denominator == 2

    client_counts = _v2_request().model_dump(mode="json")
    client_counts["confusion"] = {
        "unit_of_analysis": "inspection image",
        "true_block_count": 4,
        "false_release_count": 0,
        "true_release_count": 0,
        "false_block_count": 0,
    }
    rejected_counts = client.post(endpoint, headers=headers, json=client_counts)
    assert rejected_counts.status_code == 422

    cors_headers = {
        "Origin": "http://127.0.0.1:4173",
        "Access-Control-Request-Method": "POST",
        "Access-Control-Request-Headers": "Idempotency-Key,X-Actor-User-Id",
    }
    preflight = client.options(endpoint, headers=cors_headers)
    assert preflight.status_code == 200
    allowed_headers = preflight.headers["access-control-allow-headers"].casefold()
    assert "idempotency-key" in allowed_headers
    assert "x-actor-user-id" in allowed_headers

    rejected_preflight = client.options(
        endpoint,
        headers={
            **cors_headers,
            "Access-Control-Request-Headers": "X-Not-An-Allowed-Header",
        },
    )
    assert rejected_preflight.status_code == 400
    cors_health = client.get(
        "/v1/health",
        headers={"Origin": "http://127.0.0.1:4173"},
    )
    exposed_headers = cors_health.headers["access-control-expose-headers"].casefold()
    assert "x-evidence-sha256" in exposed_headers
    assert "x-incident-command-id" in exposed_headers

    receipt_path = (
        product_root
        / "shadow_evaluations"
        / workspace_id
        / project.project_id
        / task.task_id
        / f"{created.receipt_id}.json"
    )
    persisted = json.loads(receipt_path.read_text(encoding="utf-8"))
    persisted["units"][0]["gate_disposition"] = "RELEASE"
    receipt_path.write_text(json.dumps(persisted), encoding="utf-8")
    with pytest.raises(ArtifactUnavailableError, match="integrity"):
        service.list_shadow_evaluation_manifests_v2(actor, task.task_id)
