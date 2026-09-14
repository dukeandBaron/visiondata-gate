from __future__ import annotations

from copy import deepcopy

import pytest

from tests.test_learning_lifecycle import ACTOR, make_task
from visiondata_gate.learning_projection import learning_readiness


pytest_plugins = ("tests.test_learning_lifecycle",)


def _qualified_request(product, task_id: str, *, request_key: str):
    from visiondata_gate.data_pool import CreateDataPoolRequest

    readiness = learning_readiness(product, ACTOR, task_id)
    snapshot = product._operator_snapshot_visual_context(ACTOR, task_id)[2]
    return CreateDataPoolRequest(
        request_key=request_key,
        expected_readiness_sha256=readiness["receipt_sha256"],
        reviewer_name="Synthetic pool reviewer",
        review_note="Review every frozen member for the governed candidate pool",
        operator_attests_reviewed=True,
        members=[
            {
                "sample_id": asset.asset_id,
                "expected_asset_sha256": asset.source_sha256,
                "expected_annotation_revision": asset.annotation_revision,
                "expected_annotation_sha256": asset.annotation_document_sha256,
                "disposition": "QUALIFIED_CANDIDATE",
                "repair_action": "NONE",
                "repair_result": "NOT_APPLICABLE",
                "decision_note": "No member-level finding remains in the frozen Gate evidence",
            }
            for asset in snapshot.assets
        ],
    )


def test_pool_versions_preserve_reviewed_members_and_full_selection_is_reference(
    learning_input,
) -> None:
    from visiondata_gate.data_pool import (
        CreateDataPoolVersionRequest,
        DataPoolService,
        DeriveDataPoolVersionRequest,
    )

    _client, product, (task_id, _preflight, _groups) = learning_input
    service = DataPoolService(product)
    create = _qualified_request(product, task_id, request_key="pool-create-0001")

    projection = service.create_pool(ACTOR, task_id, create)
    assert service.create_pool(ACTOR, task_id, create) == projection
    assert projection["read_status"] == "CURRENT"
    assert projection["pool"]["origin_task_id"] == task_id
    assert projection["pool"]["current_task_id"] == task_id
    assert projection["pool"]["version_ids"] == [
        projection["current_version"]["version_id"]
    ]
    assert projection["current_version"]["qualified_count"] == 4
    assert projection["current_version"]["repair_count"] == 0
    assert projection["current_version"]["hold_count"] == 0
    assert projection["current_version"]["label_truth_authority"] is False
    assert projection["training_ingestion_allowed"] is False

    first = projection["current_version"]
    version_payload = create.model_dump(mode="json")
    version_payload.update(
        request_key="pool-version-0001",
        expected_pool_sha256=projection["pool"]["receipt_sha256"],
        expected_parent_version_sha256=first["receipt_sha256"],
        review_note="Repeat the explicit member review without changing frozen evidence",
    )
    version_request = CreateDataPoolVersionRequest(**version_payload)
    second = service.create_version(ACTOR, projection["pool"]["pool_id"], version_request)
    assert second["current_version"]["version_number"] == 2
    assert second["current_version"]["parent_version_id"] == first["version_id"]
    assert service.get_version(ACTOR, first["version_id"])["version"][
        "version_id"
    ] == first["version_id"]

    derive_request = DeriveDataPoolVersionRequest(
        request_key="pool-derive-0001",
        expected_pool_sha256=second["pool"]["receipt_sha256"],
        expected_version_sha256=second["current_version"]["receipt_sha256"],
        review_note="Keep the unchanged full snapshot as an explicit reference",
        operator_attests_reviewed=True,
    )
    derived = service.derive_version(
        ACTOR,
        second["pool"]["pool_id"],
        second["current_version"]["version_id"],
        derive_request,
    )
    assert service.derive_version(
        ACTOR,
        second["pool"]["pool_id"],
        second["current_version"]["version_id"],
        derive_request,
    ) == derived
    assert derived["materialization_mode"] == "FULL_SNAPSHOT_REFERENCE"
    assert derived["new_source_authorization_created"] is False
    assert derived["derived_source_id"] is None
    assert derived["new_gate_required"] is False
    assert derived["training_ingestion_allowed"] is False
    assert derived["production_release_allowed"] is False


def test_global_or_unmapped_evidence_cannot_create_a_qualified_complement(
    learning_input, monkeypatch
) -> None:
    from visiondata_gate import data_pool as module
    from visiondata_gate.data_pool import DataPoolError, DataPoolService

    _client, product, (task_id, _preflight, _groups) = learning_input
    observed = learning_readiness(product, ACTOR, task_id)
    unsafe = deepcopy(observed)
    unsafe["global_findings"] = [
        {
            "finding_id": "global-finding",
            "code": "COVERAGE_GAP",
            "severity": "high",
            "finding_sha256": "a" * 64,
        }
    ]
    unsafe["receipt_sha256"] = module._seal(unsafe)["receipt_sha256"]
    monkeypatch.setattr(module, "learning_readiness", lambda *_args: unsafe)
    request = _qualified_request(product, task_id, request_key="pool-global-hold-0001")
    request = request.model_copy(
        update={"expected_readiness_sha256": unsafe["receipt_sha256"]}
    )

    with pytest.raises(DataPoolError, match="QUALIFICATION_REQUIRES_MEMBER_EVIDENCE"):
        DataPoolService(product).create_pool(ACTOR, task_id, request)


def test_pool_request_key_conflict_fails_without_second_version(learning_input) -> None:
    from visiondata_gate.data_pool import DataPoolError, DataPoolService

    _client, product, (task_id, _preflight, _groups) = learning_input
    service = DataPoolService(product)
    request = _qualified_request(product, task_id, request_key="pool-conflict-0001")
    first = service.create_pool(ACTOR, task_id, request)
    changed = request.model_copy(update={"review_note": "A different review payload is not a retry"})

    with pytest.raises(DataPoolError, match="IDEMPOTENCY_CONFLICT"):
        service.create_pool(ACTOR, task_id, changed)
    assert service.get_pool(ACTOR, first["pool"]["pool_id"])["pool"][
        "version_ids"
    ] == first["pool"]["version_ids"]


def test_revoked_source_rejects_pool_reads(learning_input) -> None:
    from visiondata_gate.data_pool import DataPoolError, DataPoolService
    from visiondata_gate.product_models import RevokeLocalSourceAuthorizationRequest

    _client, product, (task_id, _preflight, _groups) = learning_input
    service = DataPoolService(product)
    projection = service.create_pool(
        ACTOR,
        task_id,
        _qualified_request(product, task_id, request_key="pool-revoke-create-01"),
    )
    source = product.get_local_source_authorization(
        ACTOR, projection["pool"]["current_source_id"]
    )
    product.revoke_local_source_authorization(
        ACTOR,
        source.source_id,
        RevokeLocalSourceAuthorizationRequest(
            reason="Explicitly revoke the source before any further pool read",
            expected_latest_event_sha256=source.latest_authorization_event_sha256,
        ),
    )

    with pytest.raises(DataPoolError, match="SOURCE_AUTHORIZATION_INACTIVE"):
        service.get_pool(ACTOR, projection["pool"]["pool_id"])


def test_qualified_subset_requires_new_gate_before_bridge_can_consume_it(
    learning_input,
) -> None:
    from visiondata_gate.data_pool import (
        CreateDataPoolVersionRequest,
        DataPoolError,
        DataPoolService,
        DeriveDataPoolVersionRequest,
        load_fresh_data_pool_context,
    )
    from visiondata_gate.product_models import (
        CreateTaskRequest,
        TaskInterventionAction,
        TaskInterventionRequest,
    )

    _client, product, (task_id, _preflight, _groups) = learning_input
    service = DataPoolService(product)
    create = _qualified_request(product, task_id, request_key="pool-subset-create-001")
    projection = service.create_pool(ACTOR, task_id, create)
    member_payloads = [
        item.model_dump(mode="json") for item in create.members
    ]
    readiness_members = {
        item["sample_id"]: item
        for item in learning_readiness(product, ACTOR, task_id)["members"]
    }
    held = next(
        item
        for item in member_payloads
        if readiness_members[item["sample_id"]]["split"] == "train"
    )
    held.update(
        disposition="UNVERIFIED_HOLD",
        repair_action="INVESTIGATE",
        repair_result="PENDING",
        decision_note="Hold this otherwise eligible member for named human investigation",
    )
    version = CreateDataPoolVersionRequest(
        request_key="pool-subset-version-01",
        expected_readiness_sha256=create.expected_readiness_sha256,
        reviewer_name=create.reviewer_name,
        review_note="Create a proper qualified subset while retaining the held member",
        operator_attests_reviewed=True,
        members=member_payloads,
        expected_pool_sha256=projection["pool"]["receipt_sha256"],
        expected_parent_version_sha256=projection["current_version"]["receipt_sha256"],
    )
    projection = service.create_version(
        ACTOR, projection["pool"]["pool_id"], version
    )
    derivation = service.derive_version(
        ACTOR,
        projection["pool"]["pool_id"],
        projection["current_version"]["version_id"],
        DeriveDataPoolVersionRequest(
            request_key="pool-subset-derive-001",
            expected_pool_sha256=projection["pool"]["receipt_sha256"],
            expected_version_sha256=projection["current_version"]["receipt_sha256"],
            review_note="Materialize only the explicitly qualified proper subset",
            operator_attests_reviewed=True,
        ),
    )
    assert derivation["materialization_mode"] == "DERIVED_QUALIFIED_SUBSET"
    assert derivation["new_source_authorization_created"] is True
    assert derivation["new_gate_required"] is True
    assert derivation["plan_approval_required"] is True
    assert derivation["new_gate_status"] == "NOT_STARTED"
    assert derivation["training_ingestion_allowed"] is False
    with pytest.raises(DataPoolError, match="DATA_POOL_NOT_ALL_QUALIFIED"):
        load_fresh_data_pool_context(
            product,
            ACTOR,
            projection["pool"]["pool_id"],
            require_all_qualified=True,
            require_gate_pass=True,
        )

    child = product.create_task(
        ACTOR,
        CreateTaskRequest(
            project_id=projection["pool"]["project_id"],
            goal="Independently Gate the reviewed Data Pool subset",
            source_kind="local_authorized_directory",
            source_id=derivation["derived_source_id"],
            plan_approval_required=True,
        ),
        auto_start=False,
    )
    product.intervene_task(
        ACTOR,
        child.task_id,
        TaskInterventionRequest(
            action=TaskInterventionAction.APPROVE_PLAN,
            note="Named reviewer approves only the independent subset Gate plan",
        ),
        start_approved_task=False,
    )
    completed_child = product.run_task_sync(child.task_id)
    assert completed_child.execution_status.value == "COMPLETED", (
        completed_child.error_code,
        completed_child.error_message,
        completed_child.current_phase,
        completed_child.final_decision,
    )
    next_create = _qualified_request(
        product, child.task_id, request_key="unused-version-request"
    )
    updated = service.get_pool(ACTOR, projection["pool"]["pool_id"])
    next_version = CreateDataPoolVersionRequest(
        request_key="pool-child-version-001",
        expected_readiness_sha256=next_create.expected_readiness_sha256,
        reviewer_name=next_create.reviewer_name,
        review_note="Bind the independently rechecked child task as the next pool version",
        operator_attests_reviewed=True,
        members=next_create.members,
        expected_pool_sha256=updated["pool"]["receipt_sha256"],
        expected_parent_version_sha256=updated["current_version"]["receipt_sha256"],
        source_task_id=child.task_id,
    )
    final = service.create_version(
        ACTOR, updated["pool"]["pool_id"], next_version
    )
    assert final["pool"]["origin_task_id"] == task_id
    assert final["pool"]["current_task_id"] == child.task_id
    assert final["current_version"]["parent_version_id"] == updated[
        "current_version"
    ]["version_id"]
    fresh = load_fresh_data_pool_context(
        product,
        ACTOR,
        final["pool"]["pool_id"],
        require_current=True,
        require_all_qualified=True,
        require_gate_pass=True,
    )
    assert fresh.task.task_id == child.task_id
    assert fresh.version["qualified_count"] == len(fresh.version["members"])


def test_reviewed_empty_annotation_and_clean_member_complement_can_be_candidates(
    learning_input, monkeypatch
) -> None:
    from visiondata_gate import data_pool as module
    from visiondata_gate.data_pool import DataPoolError, DataPoolService

    client, product, _existing = learning_input
    task_id, _preflight, _groups = make_task(
        client, product, include_normal=True
    )
    request = _qualified_request(
        product, task_id, request_key="pool-empty-annotation-01"
    )
    readiness = learning_readiness(product, ACTOR, task_id)
    assert any(
        item["readiness_state"] == "MASK_REQUIRED_FOR_REFERENCE_TRAINER"
        for item in readiness["members"]
    )
    created = DataPoolService(product).create_pool(ACTOR, task_id, request)
    assert created["current_version"]["qualified_count"] == 5
    assert all(
        item["label_truth_authority"] is False
        for item in created["current_version"]["members"]
    )

    second_task, _preflight, _groups = make_task(client, product, include_normal=True)
    unsafe = learning_readiness(product, ACTOR, second_task)
    target = next(
        item
        for item in unsafe["members"]
        if item["readiness_state"] == "MASK_REQUIRED_FOR_REFERENCE_TRAINER"
    )
    target["readiness_state"] = "BLOCKED_BY_BATCH"
    unsafe["blockers"] = ["GATE_NOT_PASS"]
    unsafe["receipt_sha256"] = module._seal(unsafe)["receipt_sha256"]
    monkeypatch.setattr(module, "learning_readiness", lambda *_args: unsafe)
    invalid_complement = _qualified_request(
        product, second_task, request_key="pool-batch-blocked-01"
    ).model_copy(update={"expected_readiness_sha256": unsafe["receipt_sha256"]})
    with pytest.raises(
        DataPoolError, match="QUALIFICATION_REQUIRES_MEMBER_EVIDENCE"
    ):
        DataPoolService(product).create_pool(
            ACTOR, second_task, invalid_complement
        )

    affected = next(
        item for item in unsafe["members"] if item["sample_id"] != target["sample_id"]
    )
    for item in unsafe["members"]:
        if not item["finding_refs"]:
            item["readiness_state"] = "BLOCKED_BY_BATCH"
    affected["readiness_state"] = "NEEDS_ATTENTION"
    affected["finding_refs"] = [
        {
            "finding_id": "member-finding",
            "code": "LOW_SHARPNESS",
            "severity": "high",
            "finding_sha256": "b" * 64,
        }
    ]
    unsafe["preflight_eligibility"] = "HOLD"
    unsafe["receipt_sha256"] = module._seal(unsafe)["receipt_sha256"]
    valid_payload = _qualified_request(
        product, second_task, request_key="pool-batch-complement-01"
    ).model_dump(mode="json")
    valid_payload["expected_readiness_sha256"] = unsafe["receipt_sha256"]
    for decision in valid_payload["members"]:
        if decision["sample_id"] == affected["sample_id"]:
            decision.update(
                disposition="REPAIR_REQUIRED",
                repair_action="RECAPTURE",
                repair_result="PENDING",
                decision_note="Mapped sharpness finding requires recapture",
            )
    from visiondata_gate.data_pool import CreateDataPoolRequest

    complemented = DataPoolService(product).create_pool(
        ACTOR, second_task, CreateDataPoolRequest(**valid_payload)
    )
    assert complemented["current_version"]["qualified_count"] == 4
    assert complemented["current_version"]["repair_count"] == 1
    assert complemented["training_ingestion_allowed"] is False
