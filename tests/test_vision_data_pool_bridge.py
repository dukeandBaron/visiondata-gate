"""Real reviewed Operator/Gate/pool inputs for the detection-dataset bridge.

Every successful fixture executes the actual Gate and data-pool producer over
test-owned synthetic images. These tests neither fabricate PASS receipts nor
load weights, run a trainer, or claim industrial model performance.
"""

from __future__ import annotations

from copy import deepcopy
import hashlib
from io import BytesIO
import json
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from PIL import Image

from tests.test_data_pool import _qualified_request
from tests.test_learning_lifecycle import (
    ACTOR,
    HEADERS,
    WORKSPACE,
    learning_input as learning_input,
    make_task,
)
from visiondata_gate.audit_envelope import canonical_jcs_bytes
from visiondata_gate.learning_detection_dataset import (
    freeze_detection_dataset,
    manifest_sha256,
)
from visiondata_gate.learning_projection import learning_readiness
from visiondata_gate.local_model_registry import (
    RegisterPoolDetectionDataset,
    VisionModelError,
)
from visiondata_gate.product_models import (
    CreateTaskRequest,
    RevokeLocalSourceAuthorizationRequest,
)
from visiondata_gate.task_store import NotFoundError


def _create_pool(product, task_id: str, *, request_key="bridge-pool-create-0001"):
    from visiondata_gate.data_pool import DataPoolService

    gate = product._annotation_context(ACTOR, task_id)[4]
    assert gate.decision.value == "PASS"
    assert gate.findings == []
    readiness = learning_readiness(product, ACTOR, task_id)
    assert readiness["projection_status"] == "VERIFIED"
    assert readiness["blockers"] == []
    projection = DataPoolService(product).create_pool(
        ACTOR,
        task_id,
        _qualified_request(product, task_id, request_key=request_key),
    )
    assert projection["read_status"] == "CURRENT"
    assert projection["current_version"]["repair_count"] == 0
    assert projection["current_version"]["hold_count"] == 0
    assert projection["training_ingestion_allowed"] is False
    return projection


def _request(projection: dict, groups: dict, **updates) -> dict:
    return {
        "request_key": "bridge-register-dataset-0001",
        "reviewer_identity": "Synthetic detection reviewer",
        "note": "Authorize reviewed synthetic bounding boxes for local data export",
        "pool_id": projection["pool"]["pool_id"],
        "version_id": projection["current_version"]["version_id"],
        "expected_pool_receipt_sha256": projection["pool"]["receipt_sha256"],
        "expected_version_receipt_sha256": projection["current_version"][
            "receipt_sha256"
        ],
        "class_names": ["defect"],
        "groups": dict(groups),
        "normal_sample_ids": [],
        "operator_attests_data_authorized": True,
        **updates,
    }


@pytest.fixture
def reviewed_pool(learning_input):
    client, product, (task_id, _preflight, groups) = learning_input
    projection = _create_pool(product, task_id)
    return client, product, task_id, groups, projection


@pytest.mark.parametrize("request_model", [False, True], ids=["dict", "dto"])
def test_reviewed_pool_exports_real_bbox_manifest_and_revalidates_binding(
    reviewed_pool, tmp_path, request_model
) -> None:
    from visiondata_gate.vision_data_pool_bridge import (
        pool_detection_input,
        verify_pool_binding,
    )

    _client, product, task_id, groups, projection = reviewed_pool
    project_id = projection["pool"]["project_id"]
    payload = _request(projection, groups)
    request = RegisterPoolDetectionDataset(**payload) if request_model else payload
    root, manifest, binding = pool_detection_input(product, ACTOR, project_id, request)
    assert isinstance(root, Path)
    assert root.is_dir()
    assert manifest["schema_version"] == "visiondata-gate.detection-dataset.v1"
    assert manifest["class_names"] == ["defect"]
    assert manifest["source_version"] == projection["current_version"]["version_id"]
    assert len(manifest["samples"]) == 4
    assert {sample["split"] for sample in manifest["samples"]} == {
        "train",
        "val",
        "test",
    }
    assets = {
        asset.asset_id: asset
        for asset in product._operator_snapshot_visual_context(ACTOR, task_id)[2].assets
    }
    assert {row["sample_id"] for row in manifest["samples"]} == set(assets)
    for row in manifest["samples"]:
        asset = assets[row["sample_id"]]
        assert row["image_path"] == asset.source_relative_path
        assert (
            hashlib.sha256((root / row["image_path"]).read_bytes()).hexdigest()
            == (row["image_sha256"])
        )
        assert row["image_sha256"] == asset.source_sha256
        assert row["annotation_revision"] == asset.annotation_revision
        assert row["group_id"] == groups[asset.asset_id]
        assert row["reviewed"] is True
        assert row["normal_attested"] is False
        assert (
            row["reviewer_name"]
            == projection["current_version"]["human_review"]["reviewer_name"]
        )
        assert row["boxes"] == [
            {
                "class_id": 0,
                "x_center": 0.375,
                "y_center": 0.375,
                "width": 0.25,
                "height": 0.25,
            }
        ]
    assert binding["pool_id"] == projection["pool"]["pool_id"]
    assert binding["version_id"] == projection["current_version"]["version_id"]
    assert verify_pool_binding(product, ACTOR, project_id, binding) is None
    receipt = freeze_detection_dataset(
        root, manifest, tmp_path / "frozen_detection", manifest_sha256(manifest)
    )
    assert receipt["split_counts"] == {"train": 2, "val": 1, "test": 1}
    for row in receipt["samples"]:
        assert (tmp_path / "frozen_detection" / row["label_path"]).read_text(
            encoding="ascii"
        ) == "0 0.375 0.375 0.25 0.25\n"


@pytest.mark.parametrize(
    "field,value",
    [
        ("expected_pool_receipt_sha256", "0" * 64),
        ("expected_version_receipt_sha256", "0" * 64),
        ("version_id", "poolv_missing"),
        ("class_names", ["scratch"]),
        ("class_names", ["defect", "scratch"]),
        ("class_names", ["defect", "defect"]),
        ("operator_attests_data_authorized", False),
    ],
)
def test_pool_export_rejects_wrong_frozen_identity_class_map_or_authority(
    reviewed_pool, field, value
) -> None:
    from visiondata_gate.vision_data_pool_bridge import pool_detection_input

    _client, product, _task_id, groups, projection = reviewed_pool
    with pytest.raises(VisionModelError):
        pool_detection_input(
            product,
            ACTOR,
            projection["pool"]["project_id"],
            _request(projection, groups, **{field: value}),
        )


@pytest.mark.parametrize("mutation", ["missing", "extra", "heldout_overlap"])
def test_pool_export_requires_exact_disjoint_group_declarations(
    reviewed_pool, mutation
) -> None:
    from visiondata_gate.vision_data_pool_bridge import pool_detection_input

    _client, product, task_id, groups, projection = reviewed_pool
    changed = dict(groups)
    if mutation == "missing":
        changed.pop(next(iter(changed)))
    elif mutation == "extra":
        changed["img_outside_snapshot"] = "independent-outside"
    else:
        members = product._annotation_context(ACTOR, task_id)[2].samples
        train = next(row.sample_id for row in members if row.split == "train")
        heldout = next(row.sample_id for row in members if row.split == "test")
        changed[heldout] = changed[train]
    with pytest.raises(VisionModelError):
        pool_detection_input(
            product,
            ACTOR,
            projection["pool"]["project_id"],
            _request(projection, changed),
        )


def test_boxed_sample_cannot_be_declared_normal(reviewed_pool) -> None:
    from visiondata_gate.vision_data_pool_bridge import pool_detection_input

    _client, product, _task_id, groups, projection = reviewed_pool
    with pytest.raises(VisionModelError):
        pool_detection_input(
            product,
            ACTOR,
            projection["pool"]["project_id"],
            _request(projection, groups, normal_sample_ids=[next(iter(groups))]),
        )


def test_empty_reviewed_bbox_requires_exact_explicit_normal_attestation(
    learning_input,
) -> None:
    from visiondata_gate.vision_data_pool_bridge import pool_detection_input

    client, product, (_task_id, _preflight, _groups) = learning_input
    task_id, _preflight, groups = make_task(client, product, include_normal=True)
    projection = _create_pool(product, task_id, request_key="bridge-normal-pool-0001")
    project_id = projection["pool"]["project_id"]
    assets = product._operator_snapshot_visual_context(ACTOR, task_id)[2].assets
    normal = next(asset.asset_id for asset in assets if asset.annotation_count == 0)
    for ids in ([], [normal, normal], [normal, "img_outside_snapshot"]):
        with pytest.raises(VisionModelError):
            pool_detection_input(
                product,
                ACTOR,
                project_id,
                _request(projection, groups, normal_sample_ids=ids),
            )
    _root, manifest, _binding = pool_detection_input(
        product,
        ACTOR,
        project_id,
        _request(projection, groups, normal_sample_ids=[normal]),
    )
    row = next(row for row in manifest["samples"] if row["sample_id"] == normal)
    assert row["boxes"] == []
    assert row["normal_attested"] is True
    assert row["reviewed"] is True
    assert len(manifest["samples"]) == 5


@pytest.mark.parametrize("drift", ["new_revision", "same_revision_changed_sha"])
def test_live_annotation_drift_invalidates_export_and_previously_bound_input(
    reviewed_pool, drift
) -> None:
    from visiondata_gate.vision_data_pool_bridge import (
        pool_detection_input,
        verify_pool_binding,
    )

    client, product, task_id, groups, projection = reviewed_pool
    project_id = projection["pool"]["project_id"]
    request = _request(projection, groups)
    _root, _manifest, binding = pool_detection_input(
        product, ACTOR, project_id, request
    )
    asset = product._operator_snapshot_visual_context(ACTOR, task_id)[2].assets[0]
    store = client.app.state.operator_image_store
    before = store.get_annotations(ACTOR, WORKSPACE, asset.asset_id)
    if drift == "new_revision":
        response = client.put(
            f"/v1/operator-workspaces/{WORKSPACE}/assets/{asset.asset_id}/annotations",
            headers=HEADERS,
            json={
                "expected_revision": before.revision,
                "annotations": [
                    row.model_dump(mode="json") for row in before.annotations
                ],
            },
        )
        assert response.status_code == 200, response.text
    else:
        # Test-owned corruption: retain a valid revision chain and revision number
        # while replacing its document. Frozen annotation SHA must still stop it.
        asset_root = store._asset(ACTOR, WORKSPACE, asset.asset_id)[1]
        revision_path = asset_root / "annotations" / f"rev_{before.revision:06d}.json"
        document = json.loads(revision_path.read_text(encoding="utf-8"))
        document["annotations"][0]["x"] = 0.3
        stable = {
            key: value
            for key, value in document.items()
            if key != "revision_payload_sha256"
        }
        document["revision_payload_sha256"] = hashlib.sha256(
            canonical_jcs_bytes(stable)
        ).hexdigest()
        revision_path.write_bytes(canonical_jcs_bytes(document))
    after = store.get_annotations(ACTOR, WORKSPACE, asset.asset_id)
    assert after.document_sha256 != before.document_sha256
    assert after.revision == before.revision + (drift == "new_revision")
    with pytest.raises(VisionModelError):
        pool_detection_input(product, ACTOR, project_id, request)
    with pytest.raises(VisionModelError):
        verify_pool_binding(product, ACTOR, project_id, binding)


def test_new_pool_version_invalidates_prior_export_request_and_binding(
    reviewed_pool,
) -> None:
    from visiondata_gate.data_pool import CreateDataPoolVersionRequest, DataPoolService
    from visiondata_gate.vision_data_pool_bridge import (
        pool_detection_input,
        verify_pool_binding,
    )

    _client, product, task_id, groups, projection = reviewed_pool
    project_id = projection["pool"]["project_id"]
    request = _request(projection, groups)
    _root, _manifest, binding = pool_detection_input(
        product, ACTOR, project_id, request
    )
    review = _qualified_request(
        product, task_id, request_key="bridge-pool-version-0002"
    ).model_dump(mode="json")
    review.update(
        expected_pool_sha256=projection["pool"]["receipt_sha256"],
        expected_parent_version_sha256=projection["current_version"]["receipt_sha256"],
    )
    updated = DataPoolService(product).create_version(
        ACTOR,
        projection["pool"]["pool_id"],
        CreateDataPoolVersionRequest(**review),
    )
    assert updated["current_version"]["version_id"] != request["version_id"]
    with pytest.raises(VisionModelError):
        pool_detection_input(product, ACTOR, project_id, request)
    with pytest.raises(VisionModelError):
        verify_pool_binding(product, ACTOR, project_id, binding)


def test_qualified_subset_cannot_bypass_full_pool_review(reviewed_pool) -> None:
    from visiondata_gate.data_pool import CreateDataPoolVersionRequest, DataPoolService
    from visiondata_gate.vision_data_pool_bridge import pool_detection_input

    _client, product, task_id, groups, initial = reviewed_pool
    request = _qualified_request(
        product, task_id, request_key="bridge-pool-subset-0001"
    ).model_dump(mode="json")
    request["members"][0].update(
        disposition="UNVERIFIED_HOLD",
        repair_action="INVESTIGATE",
        repair_result="PENDING",
        decision_note="Keep this synthetic member held pending another explicit review",
    )
    request.update(
        expected_pool_sha256=initial["pool"]["receipt_sha256"],
        expected_parent_version_sha256=initial["current_version"]["receipt_sha256"],
    )
    projection = DataPoolService(product).create_version(
        ACTOR, initial["pool"]["pool_id"], CreateDataPoolVersionRequest(**request)
    )
    assert projection["current_version"]["qualified_count"] == 3
    assert projection["current_version"]["hold_count"] == 1
    with pytest.raises(VisionModelError):
        pool_detection_input(
            product,
            ACTOR,
            projection["pool"]["project_id"],
            _request(projection, groups),
        )


def test_outsider_cannot_export_or_revalidate_pool(reviewed_pool) -> None:
    from visiondata_gate.vision_data_pool_bridge import (
        pool_detection_input,
        verify_pool_binding,
    )

    _client, product, _task_id, groups, projection = reviewed_pool
    project_id = projection["pool"]["project_id"]
    request = _request(projection, groups)
    _root, _manifest, binding = pool_detection_input(
        product, ACTOR, project_id, request
    )
    with pytest.raises(NotFoundError):
        pool_detection_input(product, "usr_outside_project", project_id, request)
    with pytest.raises(NotFoundError):
        verify_pool_binding(product, "usr_outside_project", project_id, binding)


def test_binding_revalidation_detects_changed_manifest_parameters(
    reviewed_pool,
) -> None:
    from visiondata_gate.vision_data_pool_bridge import (
        pool_detection_input,
        verify_pool_binding,
    )

    _client, product, _task_id, groups, projection = reviewed_pool
    project_id = projection["pool"]["project_id"]
    _root, _manifest, binding = pool_detection_input(
        product, ACTOR, project_id, _request(projection, groups)
    )
    altered = deepcopy(binding)
    altered["class_names"] = ["different_label"]
    with pytest.raises(VisionModelError):
        verify_pool_binding(product, ACTOR, project_id, altered)


def test_authorized_actor_cannot_move_pool_binding_into_another_project(
    reviewed_pool,
) -> None:
    from visiondata_gate.vision_data_pool_bridge import (
        pool_detection_input,
        verify_pool_binding,
    )

    client, product, _task_id, groups, projection = reviewed_pool
    project_id = projection["pool"]["project_id"]
    request = _request(projection, groups)
    _root, _manifest, binding = pool_detection_input(
        product, ACTOR, project_id, request
    )
    response = client.post(
        "/v1/projects",
        headers=HEADERS,
        json={
            "workspace_id": WORKSPACE,
            "name": "Separate synthetic detection project",
            "source_kind": "local_authorized_directory",
            "scenario_profile": "industrial",
        },
    )
    assert response.status_code == 201, response.text
    other_project = response.json()["project_id"]
    assert product.store.get_project(ACTOR, other_project).project_id == other_project
    with pytest.raises(VisionModelError):
        pool_detection_input(product, ACTOR, other_project, request)
    with pytest.raises(VisionModelError):
        verify_pool_binding(product, ACTOR, other_project, binding)


def test_real_pool_http_registration_freezes_labels_and_restores_idempotent_result(
    reviewed_pool,
) -> None:
    from visiondata_gate.learning_detection_dataset import verify_detection_dataset
    from visiondata_gate.local_model_registry import LocalVisionModelService
    from visiondata_gate.vision_model_api import install_vision_model_routes

    _client, product, _task_id, groups, projection = reviewed_pool
    project_id = projection["pool"]["project_id"]
    request = _request(projection, groups)
    app = FastAPI()
    install_vision_model_routes(app, lambda: ACTOR, lambda: product)
    route = f"/v1/projects/{project_id}/vision-datasets"
    with TestClient(app, client=("127.0.0.1", 50000)) as client:
        response = client.post(f"{route}/from-data-pool", json=request)
        assert response.status_code == 201, response.text
        record = response.json()
        assert record["status"] == "FROZEN_REVIEWED_DETECTION_DATASET"
        assert record["pool_binding"]["pool_id"] == request["pool_id"]
        assert record["pool_binding"]["version_id"] == request["version_id"]
        assert record["dataset_receipt"]["split_counts"] == {
            "train": 2,
            "val": 1,
            "test": 1,
        }
        assert record["pool_binding"]["production_release_allowed"] is False
        assert record["pool_binding"]["label_truth_authority"] is False
        stable = {
            key: value for key, value in record.items() if key != "receipt_sha256"
        }
        assert (
            hashlib.sha256(canonical_jcs_bytes(stable)).hexdigest()
            == record["receipt_sha256"]
        )
        assert response.headers["X-Content-SHA256"] == record["receipt_sha256"]
        repeated = client.post(f"{route}/from-data-pool", json=request)
        assert repeated.status_code == 201, repeated.text
        assert repeated.json() == record
        listed = client.get(route)
        assert listed.status_code == 200, listed.text
        assert listed.json()["items"] == [record]
        operation = client.get(
            f"/v1/projects/{project_id}/vision-operations/register_pool_dataset/"
            f"{request['request_key']}"
        )
        assert operation.status_code == 200, operation.text
        assert operation.json()["resource"] == record
        assert operation.json()["resource_id"] == record["dataset_id"]
        conflicting = client.post(
            f"{route}/from-data-pool",
            json=request
            | {"note": "Changed request content is not an idempotent retry"},
        )
        assert conflicting.status_code == 409, conflicting.text
        assert client.get(route).json()["items"] == [record]
    queue = [record]
    while queue:
        value = queue.pop()
        if isinstance(value, dict):
            queue.extend(value.values())
        elif isinstance(value, list):
            queue.extend(value)
        elif isinstance(value, str):
            assert not Path(value).is_absolute(), value
            assert str(product.product_root) not in value
    output = LocalVisionModelService(product).root / "datasets" / record["dataset_id"]
    verified = verify_detection_dataset(output, record["dataset_receipt_sha256"])
    assert verified == record["dataset_receipt"]
    for member in verified["samples"]:
        assert (output / member["label_path"]).read_text(encoding="ascii") == (
            "0 0.375 0.375 0.25 0.25\n"
        )


def test_write_transaction_rechecks_pool_source_and_identity_using_selects_only(
    reviewed_pool,
) -> None:
    from visiondata_gate.identity_service import IdentityError, IdentityService
    from visiondata_gate.vision_data_pool_bridge import (
        pool_detection_input,
        verify_pool_binding_in_connection,
    )

    _client, product, task_id, groups, projection = reviewed_pool
    project_id = projection["pool"]["project_id"]
    _root, _manifest, binding = pool_detection_input(
        product, ACTOR, project_id, _request(projection, groups)
    )
    identity = IdentityService(product)
    identity.setup(
        ACTOR,
        login_name="bridge-transaction-reviewer",
        display_name="Synthetic transaction reviewer",
        password="synthetic transaction test password 123",
        email=None,
    )
    with product.store._connection() as connection:
        assert connection.in_transaction is False
        with pytest.raises(VisionModelError):
            verify_pool_binding_in_connection(connection, ACTOR, project_id, binding)

    changed_pool = deepcopy(projection["pool"])
    changed_pool["current_version_id"] = "poolv_replaced_test_version"
    changed_pool["version_ids"].append(changed_pool["current_version_id"])
    stable = {
        key: value for key, value in changed_pool.items() if key != "receipt_sha256"
    }
    changed_pool["receipt_sha256"] = hashlib.sha256(
        canonical_jcs_bytes(stable)
    ).hexdigest()
    mutations = [
        (
            "pool_head",
            "UPDATE governed_data_pools_v1 SET record_json=? WHERE pool_id=?",
            (json.dumps(changed_pool), binding["pool_id"]),
            VisionModelError,
        ),
        (
            "source_revoked",
            "UPDATE local_source_authorizations SET status='revoked' WHERE source_id=?",
            (binding["source_id"],),
            VisionModelError,
        ),
        (
            "source_expired",
            "UPDATE local_source_authorizations SET authorization_valid_until=? WHERE source_id=?",
            ("2000-01-01T00:00:00+00:00", binding["source_id"]),
            VisionModelError,
        ),
        (
            "workspace_membership_revoked",
            "DELETE FROM workspace_members WHERE workspace_id=? AND user_id=?",
            (WORKSPACE, ACTOR),
            NotFoundError,
        ),
        (
            "account_disabled",
            "UPDATE identity_credentials SET status='DISABLED' WHERE user_id=?",
            (ACTOR,),
            IdentityError,
        ),
        (
            "task_evidence_changed",
            "UPDATE agent_tasks SET evidence_sha256=? WHERE task_id=?",
            ("0" * 64, task_id),
            VisionModelError,
        ),
    ]

    def verify_read_only(connection, expected_error=None):
        statements = []
        connection.set_trace_callback(statements.append)
        try:
            if expected_error is None:
                assert (
                    verify_pool_binding_in_connection(
                        connection, ACTOR, project_id, binding
                    )
                    is None
                )
            else:
                with pytest.raises(expected_error):
                    verify_pool_binding_in_connection(
                        connection, ACTOR, project_id, binding
                    )
        finally:
            connection.set_trace_callback(None)
        assert statements
        assert all(
            statement.lstrip().upper().startswith("SELECT ") for statement in statements
        ), statements
        assert connection.in_transaction is True

    # Every mutation is confined to a savepoint in this test-owned database.
    # No successful producer receipt or PASS decision is synthesized here.
    with product.store._connection(immediate=True) as connection:
        verify_read_only(connection)
        for _name, statement, parameters, expected_error in mutations:
            connection.execute("SAVEPOINT bridge_authority_change")
            try:
                assert connection.execute(statement, parameters).rowcount == 1
                verify_read_only(connection, expected_error)
            finally:
                connection.execute("ROLLBACK TO bridge_authority_change")
                connection.execute("RELEASE bridge_authority_change")
            verify_read_only(connection)


def test_revoked_source_invalidates_export_and_previously_bound_input(
    reviewed_pool,
) -> None:
    from visiondata_gate.vision_data_pool_bridge import (
        pool_detection_input,
        verify_pool_binding,
    )

    _client, product, task_id, groups, projection = reviewed_pool
    project_id = projection["pool"]["project_id"]
    request = _request(projection, groups)
    _root, _manifest, binding = pool_detection_input(
        product, ACTOR, project_id, request
    )
    source_id = product.store.get_task(ACTOR, task_id).source_id
    product.revoke_local_source_authorization(
        ACTOR,
        source_id,
        RevokeLocalSourceAuthorizationRequest(
            reason="Withdraw the test-owned source grant after successful registration",
            expected_latest_event_sha256=product.list_source_authorization_events(
                ACTOR, source_id
            )[-1].event_sha256,
        ),
    )
    with pytest.raises(VisionModelError):
        pool_detection_input(product, ACTOR, project_id, request)
    with pytest.raises(VisionModelError):
        verify_pool_binding(product, ACTOR, project_id, binding)


def test_real_nonpassing_gate_qualified_complement_is_not_a_training_dataset(
    reviewed_pool,
) -> None:
    from visiondata_gate.data_pool import (
        CreateDataPoolRequest,
        DataPoolError,
        DataPoolService,
        load_fresh_data_pool_context,
    )
    from visiondata_gate.compute_handoff import REQUIRED_TOOLS
    from visiondata_gate.vision_data_pool_bridge import pool_detection_input

    client, product, old_task_id, groups, initial_pool = reviewed_pool
    project_id = initial_pool["pool"]["project_id"]
    original = product._operator_snapshot_visual_context(ACTOR, old_task_id)[2]
    samples = [
        row.model_dump(mode="json") for row in original.acceptance_requirements.samples
    ]
    buffer = BytesIO()
    Image.new("RGB", (64, 64), color=(0, 0, 0)).save(buffer, format="PNG")
    response = client.post(
        f"/v1/operator-workspaces/{WORKSPACE}/assets",
        headers=HEADERS,
        params={"project_id": project_id},
        files=[("files", ("synthetic-dark.png", buffer.getvalue(), "image/png"))],
    )
    assert response.status_code == 201, response.text
    dark = response.json()["assets"][0]
    dark_id = dark["asset_id"]
    response = client.put(
        f"/v1/operator-workspaces/{WORKSPACE}/assets/{dark_id}/annotations",
        headers=HEADERS,
        json={
            "expected_revision": 0,
            "annotations": [
                {
                    "annotation_id": "known-dark-target",
                    "label": "defect",
                    "x": 0.25,
                    "y": 0.25,
                    "width": 0.25,
                    "height": 0.25,
                }
            ],
        },
    )
    assert response.status_code == 200, response.text
    annotations = response.json()
    samples.append(
        {
            "asset_id": dark_id,
            "split": "train",
            "category": "defect",
            "annotation_requirement": "REQUIRED",
            "human_review": {
                "reviewer_name": "Synthetic dark frame reviewer",
                "note": "Explicit test box on a deliberately unusable dark image",
                "expected_asset_sha256": dark["source_sha256"],
                "expected_annotation_revision": annotations["revision"],
                "expected_annotation_sha256": annotations["document_sha256"],
                "operator_attests_reviewed": True,
            },
        }
    )
    response = client.post(
        "/v1/data-sources/operator-project-snapshots",
        headers=HEADERS,
        json={
            "workspace_id": WORKSPACE,
            "project_id": project_id,
            "operator_attests_authorized_use": True,
            "acceptance_requirements": {
                "schema_version": "visiondata-gate.operator-acceptance-requirements.v1",
                "purpose_description": "Real nonpassing Gate fixture with mapped dark image findings",
                "category_vocabulary": ["defect"],
                "samples": samples,
            },
        },
    )
    assert response.status_code == 201, response.text
    task = product.create_task(
        ACTOR,
        CreateTaskRequest(
            project_id=project_id,
            goal="Execute the actual Gate over deliberately unusable test imagery",
            source_kind="local_authorized_directory",
            source_id=response.json()["source_id"],
            plan_approval_required=False,
        ),
        auto_start=False,
    )
    product.run_task_sync(task.task_id)
    gate = product._annotation_context(ACTOR, task.task_id)[4]
    assert gate.decision.value != "PASS"
    assert any(dark_id in finding.sample_ids for finding in gate.findings)
    assert all(
        trace.status == "ok" and trace.error is None for trace in gate.tool_trace
    )
    assert REQUIRED_TOOLS.issubset({trace.tool for trace in gate.tool_trace})
    readiness = learning_readiness(product, ACTOR, task.task_id)
    assert readiness["global_findings"] == []
    assert readiness["unmapped_finding_refs"] == []
    assert readiness["projection_status"] == "VERIFIED", readiness
    assert readiness["blockers"] == ["GATE_NOT_PASS"], readiness
    review = _qualified_request(
        product, task.task_id, request_key="bridge-real-failed-gate-0001"
    ).model_dump(mode="json")
    findings = {
        member["sample_id"]: member["finding_refs"] for member in readiness["members"]
    }
    assert {sample_id for sample_id, refs in findings.items() if refs} == {dark_id}
    assert all(
        member["readiness_state"] == "BLOCKED_BY_BATCH"
        for member in readiness["members"]
        if not member["finding_refs"]
    )
    for member in review["members"]:
        if findings[member["sample_id"]]:
            member.update(
                disposition="REPAIR_REQUIRED",
                repair_action="RECAPTURE",
                repair_result="PENDING",
                decision_note="Recapture this test frame because its real Gate quality check failed",
            )
    service = DataPoolService(product)
    assert (
        sum(
            member["disposition"] == "QUALIFIED_CANDIDATE"
            for member in review["members"]
        )
        == 4
    )
    assert (
        sum(member["disposition"] == "REPAIR_REQUIRED" for member in review["members"])
        == 1
    )
    # Member-level qualification permits this verified complement. Training
    # still requires the complete source Gate to pass and every member to qualify.
    projection = service.create_pool(
        ACTOR, task.task_id, CreateDataPoolRequest(**review)
    )
    assert projection["read_status"] == "CURRENT"
    assert projection["current_version"]["qualified_count"] == 4
    assert projection["current_version"]["hold_count"] == 0
    assert projection["current_version"]["repair_count"] == 1
    assert projection["current_version"]["readiness_blockers"] == ["GATE_NOT_PASS"]
    assert projection["training_ingestion_allowed"] is False
    with pytest.raises(DataPoolError, match="DATA_POOL_GATE_PASS_REQUIRED"):
        load_fresh_data_pool_context(
            product,
            ACTOR,
            projection["pool"]["pool_id"],
            require_current=True,
            require_all_qualified=False,
            require_gate_pass=True,
        )
    with pytest.raises(VisionModelError):
        pool_detection_input(
            product,
            ACTOR,
            project_id,
            _request(projection, groups | {dark_id: "independent-dark-train"}),
        )
