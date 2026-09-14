"""Real registry/DB/dataset lifecycle with explicit synthetic compute doubles.

No test here executes Python runtimes, imports torch, downloads weights, or
establishes real training quality. Backend/runtime doubles implement only their
declared integrity and result contracts so registry state transitions are tested.
"""

from __future__ import annotations

import copy
import hashlib
import json
from pathlib import Path
from types import SimpleNamespace

from PIL import Image
from pydantic import ValidationError
import pytest

from visiondata_gate import learning_yolo_backend as backend
from visiondata_gate import local_model_registry as registry
from visiondata_gate.learning_detection_dataset import manifest_sha256
from visiondata_gate.product_models import (
    CreateProjectRequest,
    CreateUserRequest,
    CreateWorkspaceRequest,
)
from visiondata_gate.product_service import ProductService
from visiondata_gate.task_store import NotFoundError


def _digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def _named(key, **fields):
    return {
        "request_key": key,
        "reviewer_identity": "Named synthetic reviewer",
        "note": "Lifecycle fixture only; no real model compute claim",
        **fields,
    }


@pytest.fixture
def context(tmp_path, monkeypatch):
    product = ProductService(tmp_path / "product", recover_interrupted=False)
    actor = product.create_user(
        CreateUserRequest(display_name="Lifecycle owner")
    ).user_id
    workspace = product.create_workspace(
        CreateWorkspaceRequest(name="Lifecycle", owner_user_id=actor)
    )
    project = product.create_project(
        actor,
        CreateProjectRequest(workspace_id=workspace.workspace_id, name="Detection"),
    ).project_id
    service = registry.LocalVisionModelService(
        product, _test_only_allow_unbound_fixtures=True
    )
    runtime_file = tmp_path / "never-executed-python.exe"
    runtime_file.write_bytes(b"Synthetic runtime identity; must never execute")
    state = SimpleNamespace(
        product=product,
        actor=actor,
        project=project,
        workspace=workspace.workspace_id,
        service=service,
        source=tmp_path / "source",
        runtime_file=runtime_file,
        runtime_sha="a" * 64,
        pending=[],
        probe_calls=[],
        backend_calls=[],
        before_result=None,
    )

    def probe(executable, expected_executable_sha256, work_root, *, import_check=False):
        state.probe_calls.append((executable, import_check))
        if _digest(executable) != expected_executable_sha256:
            raise ValueError("SYNTHETIC_RUNTIME_EXECUTABLE_CHANGED")
        return {
            "status": "ready",
            "runtime_sha256": state.runtime_sha,
            "import_status": "SYNTHETIC_NOT_IMPORTED",
            "evidence_origin": "TEST_DOUBLE_NO_RUNTIME_EXECUTION",
        }

    def training(**kwargs):
        state.backend_calls.append(kwargs)
        observed = probe(
            kwargs["executable"],
            kwargs["expected_executable_sha256"],
            kwargs["output_root"],
        )
        if observed["runtime_sha256"] != kwargs["expected_runtime_sha256"]:
            raise ValueError("SYNTHETIC_RUNTIME_FINGERPRINT_CHANGED")
        if kwargs["initial_weights"] is not None:
            assert (
                _digest(kwargs["initial_weights"]) == kwargs["expected_weights_sha256"]
            )
        output = kwargs["output_root"]
        checkpoint = output / "training" / "weights" / "last.pt"
        checkpoint.parent.mkdir(parents=True)
        checkpoint.write_bytes(b"Synthetic candidate bytes; never a trained checkpoint")
        if state.before_result:
            state.before_result(kwargs)
        return {
            "status": "completed",
            "evidence_origin": "TEST_DOUBLE_NO_TRAINING_EXECUTION",
            "baseline": {"map50": 0.1, "map50_95": 0.05},
            "candidate": {"map50": 0.2, "map50_95": 0.08},
            "test_evaluation": "NOT_RUN",
            "checkpoint": {
                "relative_path": "training/weights/last.pt",
                "sha256": _digest(checkpoint),
                "bytes": checkpoint.stat().st_size,
            },
        }

    monkeypatch.setattr(backend, "probe_vision_runtime", probe)
    monkeypatch.setattr(backend, "run_yolo_training", training)
    monkeypatch.setattr(
        registry.threading.Thread, "start", lambda thread: state.pending.append(thread)
    )
    state.source.mkdir()
    samples = []
    for i, split in enumerate(("train", "val", "test")):
        path = state.source / f"{split}.png"
        Image.new("RGB", (16, 16), (20 + i * 40, 70, 100)).save(path)
        samples.append(
            {
                "sample_id": f"sample-{split}",
                "image_path": path.name,
                "image_sha256": _digest(path),
                "split": split,
                "group_id": f"fixture-part-{split}",
                "annotation_revision": 1,
                "boxes": [
                    {
                        "class_id": 0,
                        "x_center": 0.5,
                        "y_center": 0.5,
                        "width": 0.5,
                        "height": 0.5,
                    }
                ],
                "reviewer_name": "Named synthetic reviewer",
                "reviewed": True,
            }
        )
    state.manifest = {
        "schema_version": "visiondata-gate.detection-dataset.v1",
        "source_version": "synthetic-lifecycle-v1",
        "class_names": ["scratch"],
        "samples": samples,
    }
    yield state
    product.close(wait=True)


def _dataset(context, key="dataset-register-0001", manifest=None, project=None):
    manifest = manifest or context.manifest
    return context.service.register_dataset(
        context.actor,
        project or context.project,
        registry.RegisterDetectionDataset(
            **_named(
                key,
                source_root=str(context.source),
                manifest=manifest,
                expected_manifest_sha256=manifest_sha256(manifest),
                operator_attests_data_authorized=True,
            )
        ),
    )


def _runtime(context, key="runtime-register-0001", project=None):
    return context.service.register_runtime(
        context.actor,
        project or context.project,
        registry.RegisterVisionRuntime(
            **_named(
                key,
                display_name="Synthetic runtime, never executed",
                executable_path=str(context.runtime_file),
                expected_executable_sha256=_digest(context.runtime_file),
                operator_attests_trusted_runtime=True,
                operator_attests_execution_authorized=True,
            )
        ),
    )


def _request(context, **updates):
    runtime = _runtime(context)
    dataset = _dataset(context)
    return registry.CreateVisionTrainingRun(
        **_named(
            "training-launch-0001",
            runtime_id=runtime["runtime_id"],
            expected_runtime_sha256=runtime["runtime_sha256"],
            dataset_id=dataset["dataset_id"],
            expected_dataset_receipt_sha256=dataset["dataset_receipt_sha256"],
            initialization="ARCHITECTURE_RANDOM",
            operator_attests_training_authorized=True,
            operator_attests_trusted_runtime=True,
            ultralytics_license_acknowledged=True,
        )
        | updates
    )


def _launch(context, **updates):
    return context.service.create_training_run(
        context.actor, context.project, _request(context, **updates)
    )


def _execute(context, run):
    context.service._execute_run(context.actor, context.project, run["run_id"])
    return context.service.get_run(context.actor, context.project, run["run_id"])


def _action(run, key="run-action-0000001"):
    return registry.VisionRunAction(
        **_named(
            key,
            expected_run_sha256=run["receipt_sha256"],
            operator_attests_reviewed=True,
        )
    )


def _select(context, run, action="APPROVE_SANDBOX", **updates):
    model = context.service.get_model(
        context.actor, context.project, run["candidate_model_id"]
    )
    return registry.SelectVisionModel(
        **_named(
            "select-candidate-0001",
            expected_run_sha256=run["receipt_sha256"],
            operator_attests_reviewed=True,
            action=action,
            expected_candidate_weights_sha256=model["weights_sha256"],
        )
        | updates
    )


def _no_candidates(context):
    models = context.service.list_models(context.actor, context.project)["items"]
    assert not [model for model in models if model.get("training_run_id")]
    assert all(model["production_release_allowed"] is False for model in models)


def _weights(context, task_type="detect"):
    path = context.source.parent / f"unloaded-{task_type}.pt"
    path.write_bytes(b"Untrusted synthetic registered bytes, never deserialize")
    return context.service.register_model(
        context.actor,
        context.project,
        registry.RegisterVisionModel(
            **_named(
                f"weights-register-{task_type}",
                display_name="Unloaded fixture",
                weights_path=str(path),
                expected_weights_sha256=_digest(path),
                task_type=task_type,
                license_id="AGPL-3.0",
                source_description="Explicit synthetic registry fixture",
                operator_attests_read_authorized=True,
            )
        ),
    )


def test_fresh_dataset_registration_creates_owned_parent(context):
    dataset = _dataset(context)
    assert dataset["status"] == "FROZEN_REVIEWED_DETECTION_DATASET"
    assert dataset["provenance"] == "UNBOUND_EXTERNAL_FIXTURE"
    assert dataset["training_eligible"] is False
    assert dataset["dataset_receipt"]["split_counts"] == {
        "train": 1,
        "val": 1,
        "test": 1,
    }
    _no_candidates(context)


def test_default_service_rejects_unbound_dataset_before_queue_or_backend(context):
    request = _request(context)
    default_service = registry.LocalVisionModelService(context.product)

    with pytest.raises(
        registry.VisionModelError, match="GOVERNED_POOL_DATASET_REQUIRED"
    ):
        default_service.create_training_run(context.actor, context.project, request)

    assert context.backend_calls == []
    assert context.pending == []
    assert default_service.list_runs(context.actor, context.project)["items"] == []
    _no_candidates(context)


def test_default_service_does_not_replay_unbound_fixture_run(context):
    request = _request(context)
    fixture_run = context.service.create_training_run(
        context.actor, context.project, request
    )
    default_service = registry.LocalVisionModelService(context.product)

    with pytest.raises(
        registry.VisionModelError, match="GOVERNED_POOL_DATASET_REQUIRED"
    ):
        default_service.create_training_run(context.actor, context.project, request)

    assert context.backend_calls == []
    assert len(context.pending) == 1
    assert default_service.list_runs(context.actor, context.project)["items"] == [
        fixture_run
    ]


def test_unbound_dataset_does_not_make_capabilities_training_ready(context):
    _runtime(context)
    dataset = _dataset(context)

    capabilities = context.service.capabilities(context.actor, context.project)

    assert dataset["training_eligible"] is False
    assert capabilities["registered_runtime_count"] == 1
    assert capabilities["registered_dataset_count"] == 1
    assert capabilities["training_ready"] is False


def test_launch_is_idempotent_and_persists_before_thread_execution(context):
    request = _request(context)
    first = context.service.create_training_run(context.actor, context.project, request)
    again = context.service.create_training_run(context.actor, context.project, request)
    assert first == again
    assert first["status"] == "QUEUED"
    assert len(context.pending) == 1
    assert context.backend_calls == []
    assert (
        context.service.get_run(context.actor, context.project, first["run_id"])
        == first
    )
    operation = context.service.get_operation(
        context.actor, context.project, "create_training_run", request.request_key
    )
    assert operation["resource"] == first
    assert operation["auto_replayed"] is False
    _no_candidates(context)


def test_restart_get_does_not_replay_queued_training(context):
    run = _launch(context)
    reopened = ProductService(context.product.product_root, recover_interrupted=False)
    try:
        recovered = registry.LocalVisionModelService(reopened)
        assert recovered.get_run(context.actor, context.project, run["run_id"]) == run
        assert recovered.list_runs(context.actor, context.project)["items"] == [run]
        assert len(context.pending) == 1
        assert not context.backend_calls
        _no_candidates(context)
    finally:
        reopened.close(wait=True)


@pytest.mark.parametrize(
    "grant",
    [
        "operator_attests_training_authorized",
        "operator_attests_trusted_runtime",
        "ultralytics_license_acknowledged",
    ],
)
@pytest.mark.parametrize("kind", ["missing", "false", "forged_model_copy"])
def test_training_requires_all_current_grants(context, grant, kind):
    request = _request(context)
    payload = request.model_dump(mode="json")
    if kind == "missing":
        payload.pop(grant)
    else:
        payload[grant] = False
    with pytest.raises(ValidationError):
        invalid = (
            request.model_copy(update={grant: False})
            if kind == "forged_model_copy"
            else registry.CreateVisionTrainingRun.model_validate(payload)
        )
        context.service.create_training_run(context.actor, context.project, invalid)
    assert not context.pending
    assert context.service.list_runs(context.actor, context.project)["items"] == []
    _no_candidates(context)


def test_concurrent_second_run_requires_current_active_job_to_finish(context):
    first = _launch(context)
    with pytest.raises(
        registry.VisionModelError, match="PROJECT_TRAINING_ALREADY_ACTIVE"
    ):
        _launch(context, request_key="training-launch-0002")
    assert len(context.pending) == 1
    assert context.service.list_runs(context.actor, context.project)["items"] == [first]
    _no_candidates(context)


def test_idempotency_key_cannot_change_training_budget(context):
    first = _launch(context)
    with pytest.raises(registry.VisionModelError, match="IDEMPOTENCY_CONFLICT"):
        _launch(context, training={"epochs": 2})
    assert len(context.pending) == 1
    assert (
        context.service.get_run(context.actor, context.project, first["run_id"])
        == first
    )
    _no_candidates(context)


@pytest.mark.parametrize("resource", ["runtime", "dataset"])
def test_resources_cannot_cross_project_boundary(context, resource):
    request = _request(context)
    other = context.product.create_project(
        context.actor,
        CreateProjectRequest(workspace_id=context.workspace, name="Other"),
    ).project_id
    foreign = (
        _runtime(context, project=other)
        if resource == "runtime"
        else _dataset(context, project=other)
    )
    invalid = request.model_copy(update={f"{resource}_id": foreign[f"{resource}_id"]})
    with pytest.raises(NotFoundError):
        context.service.create_training_run(context.actor, context.project, invalid)
    assert not context.pending
    _no_candidates(context)


def test_heldout_pixels_cannot_be_reregistered_as_training(context):
    original = _dataset(context)
    changed = copy.deepcopy(context.manifest)
    changed["source_version"] = "synthetic-lifecycle-v2"
    changed["samples"][0]["split"], changed["samples"][2]["split"] = "test", "train"
    with pytest.raises(
        registry.VisionModelError, match="PROJECT_HELDOUT_REUSE_FORBIDDEN"
    ):
        _dataset(context, "dataset-register-0002", changed)
    assert context.service.list_datasets(context.actor, context.project)["items"] == [
        original
    ]
    _no_candidates(context)


def test_cancel_before_start_never_invokes_backend_or_publishes(context):
    run = _launch(context)
    cancelled = context.service.cancel_run(
        context.actor, context.project, run["run_id"], _action(run)
    )
    assert cancelled["status"] == "CANCELLED"
    assert _execute(context, cancelled)["status"] == "CANCELLED"
    assert not context.backend_calls
    _no_candidates(context)


def test_cancel_during_backend_discards_completed_candidate(context):
    run = _launch(context)

    def cancel_while_running(kwargs):
        live = context.service.get_run(context.actor, context.project, run["run_id"])
        assert live["status"] == "RUNNING"
        context.service.cancel_run(
            context.actor, context.project, run["run_id"], _action(live)
        )
        assert kwargs["cancelled"]() is True

    context.before_result = cancel_while_running
    finished = _execute(context, run)
    assert finished["status"] == "CANCELLED"
    assert finished["candidate_model_id"] is None
    assert len(context.backend_calls) == 1
    _no_candidates(context)


@pytest.mark.parametrize("tamper", ["runtime_bytes", "runtime_metadata", "dataset"])
def test_tampered_queued_inputs_persist_failed_without_candidate(context, tamper):
    run = _launch(context)
    if tamper == "runtime_bytes":
        context.runtime_file.write_bytes(b"Changed executable bytes")
    elif tamper == "runtime_metadata":
        context.runtime_sha = "b" * 64
    else:
        root = context.service.root / "datasets" / run["dataset_id"]
        (root / "labels/train/sample-train.txt").write_text(
            "0 0.5 0.5 0.2 0.2\n", "utf-8"
        )
    finished = _execute(context, run)
    assert finished["status"] == "FAILED"
    assert finished["error_code"] == "TRAINING_EVIDENCE_OR_EXECUTION_FAILED"
    assert finished["candidate_model_id"] is None
    _no_candidates(context)


def test_registered_pt_does_not_grant_loading_authority(context):
    model = _weights(context)
    assert model["loaded"] is False
    with pytest.raises(ValidationError, match="pickle-load authority"):
        _request(
            context,
            initialization="REGISTERED_WEIGHTS",
            initial_model_id=model["model_id"],
            expected_weights_sha256=model["weights_sha256"],
        )
    assert not context.pending
    assert not context.backend_calls
    _no_candidates(context)


def test_segment_checkpoint_cannot_enter_detection_training(context):
    model = _weights(context, "segment")
    with pytest.raises(
        registry.VisionModelError, match="YOLO_DETECTION_CHECKPOINT_REQUIRED"
    ):
        _launch(
            context,
            initialization="REGISTERED_WEIGHTS",
            initial_model_id=model["model_id"],
            expected_weights_sha256=model["weights_sha256"],
            operator_attests_trusted_weights=True,
            operator_attests_pickle_load_risk=True,
        )
    assert not context.pending
    assert not context.backend_calls
    assert (
        context.service.get_model(context.actor, context.project, model["model_id"])[
            "loaded"
        ]
        is False
    )
    _no_candidates(context)


def test_recovery_preserves_original_run_without_auto_execution(context):
    run = _launch(context)
    recovered = context.service.recover_run(
        context.actor, context.project, run["run_id"], _action(run)
    )
    assert recovered["status"] == "INTERRUPTED_HOLD"
    assert recovered["error_code"] == "NEW_AUTHORIZATION_REQUIRED_NO_AUTO_REPLAY"
    assert recovered["dataset_receipt_sha256"] == run["dataset_receipt_sha256"]
    assert _execute(context, recovered) == recovered
    assert not context.backend_calls
    assert len(context.pending) == 1
    _no_candidates(context)


@pytest.mark.parametrize("action", ["APPROVE_SANDBOX", "REJECT"])
def test_selection_requires_actual_candidate_and_current_hashes(context, action):
    run = _launch(context)
    early = registry.SelectVisionModel(
        **_named(
            "early-selection-0001",
            expected_run_sha256=run["receipt_sha256"],
            operator_attests_reviewed=True,
            action=action,
            expected_candidate_weights_sha256="0" * 64,
        )
    )
    with pytest.raises(registry.VisionModelError, match="CANDIDATE_NOT_SELECTABLE"):
        context.service.select_model(
            context.actor, context.project, run["run_id"], early
        )
    _no_candidates(context)
    finished = _execute(context, run)
    assert finished["status"] == "SUCCEEDED_CANDIDATE"
    assert finished["selection"] == "PENDING"
    assert finished["result"]["evidence_origin"] == "TEST_DOUBLE_NO_TRAINING_EXECUTION"
    stale = _select(
        context, finished, action, expected_run_sha256=run["receipt_sha256"]
    )
    with pytest.raises(registry.VisionModelError, match="STALE_RUN"):
        context.service.select_model(
            context.actor, context.project, run["run_id"], stale
        )
    candidate = context.service.get_model(
        context.actor, context.project, finished["candidate_model_id"]
    )
    assert candidate["status"] == "CANDIDATE_REQUIRES_HUMAN_REVIEW"
    selected = context.service.select_model(
        context.actor,
        context.project,
        run["run_id"],
        _select(context, finished, action),
    )
    assert selected["selection"] == action
    model = context.service.get_model(
        context.actor, context.project, finished["candidate_model_id"]
    )
    assert model["status"] == action
    assert model["production_release_allowed"] is False
    assert model["machine_write_permitted"] is False
    assert (
        len(context.service.list_models(context.actor, context.project)["items"]) == 1
    )


def test_selection_refuses_changed_checkpoint_without_approval(context):
    finished = _execute(context, _launch(context))
    request = _select(context, finished)
    checkpoint = (
        context.service.root
        / "runs"
        / finished["run_id"]
        / "execution/training/weights/last.pt"
    )
    checkpoint.write_bytes(b"replacement checkpoint")
    with pytest.raises(registry.VisionModelError, match="CHECKPOINT_CHANGED"):
        context.service.select_model(
            context.actor, context.project, finished["run_id"], request
        )
    assert (
        context.service.get_run(context.actor, context.project, finished["run_id"])[
            "selection"
        ]
        == "PENDING"
    )
    model = context.service.get_model(
        context.actor, context.project, finished["candidate_model_id"]
    )
    assert model["status"] == "CANDIDATE_REQUIRES_HUMAN_REVIEW"
    assert model["production_release_allowed"] is False


def test_budget_must_reject_batch_one_before_queued_job(context):
    with pytest.raises(ValidationError):
        _launch(context, training={"batch": 1})
    assert not context.pending
    assert not context.service.list_runs(context.actor, context.project)["items"]
    _no_candidates(context)


def test_forged_cancel_review_is_revalidated_before_mutation(context):
    run = _launch(context)
    forged = _action(run).model_copy(update={"operator_attests_reviewed": False})
    with pytest.raises(ValidationError):
        context.service.cancel_run(
            context.actor, context.project, run["run_id"], forged
        )
    assert context.service.get_run(context.actor, context.project, run["run_id"]) == run
    _no_candidates(context)


def test_forged_runtime_execution_authority_is_revalidated(context):
    request = registry.RegisterVisionRuntime(
        **_named(
            "runtime-forged-0001",
            display_name="Never execute fixture",
            executable_path=str(context.runtime_file),
            expected_executable_sha256=_digest(context.runtime_file),
            operator_attests_trusted_runtime=True,
            operator_attests_execution_authorized=True,
        )
    ).model_copy(update={"operator_attests_execution_authorized": False})
    with pytest.raises(ValidationError):
        context.service.register_runtime(context.actor, context.project, request)
    assert not context.probe_calls
    assert context.service.list_runtimes(context.actor, context.project)["items"] == []
    _no_candidates(context)


def test_forged_dataset_read_authority_is_revalidated(context):
    request = registry.RegisterDetectionDataset(
        **_named(
            "dataset-forged-0001",
            source_root=str(context.source),
            manifest=context.manifest,
            expected_manifest_sha256=manifest_sha256(context.manifest),
            operator_attests_data_authorized=True,
        )
    ).model_copy(update={"operator_attests_data_authorized": False})
    with pytest.raises(ValidationError):
        context.service.register_dataset(context.actor, context.project, request)
    assert context.service.list_datasets(context.actor, context.project)["items"] == []
    _no_candidates(context)


@pytest.mark.parametrize(
    "field", ["expected_runtime_sha256", "expected_dataset_receipt_sha256"]
)
def test_stale_resource_digest_is_rejected_before_launch(context, field):
    with pytest.raises(registry.VisionModelError, match="STALE_"):
        _launch(context, **{field: "0" * 64})
    assert not context.pending
    assert not context.backend_calls
    _no_candidates(context)


def test_selection_requires_current_candidate_sha(context):
    finished = _execute(context, _launch(context))
    stale = _select(context, finished, expected_candidate_weights_sha256="0" * 64)
    with pytest.raises(registry.VisionModelError, match="STALE_CANDIDATE"):
        context.service.select_model(
            context.actor, context.project, finished["run_id"], stale
        )
    assert (
        context.service.get_run(context.actor, context.project, finished["run_id"])[
            "selection"
        ]
        == "PENDING"
    )
    models = context.service.list_models(context.actor, context.project)["items"]
    assert len(models) == 1
    assert models[0]["status"] == "CANDIDATE_REQUIRES_HUMAN_REVIEW"
    assert models[0]["production_release_allowed"] is False


def test_backend_uses_working_copy_and_preserves_frozen_data(context):
    run = _launch(context)
    frozen = context.service.root / "datasets" / run["dataset_id"]
    original = {
        p.relative_to(frozen).as_posix(): p.read_bytes()
        for p in frozen.rglob("*")
        if p.is_file()
    }

    def simulate_yolo_cache(kwargs):
        assert kwargs["dataset_root"] != frozen
        assert kwargs["initial_weights"] is None
        (kwargs["dataset_root"] / "labels/train.cache").write_bytes(b"Synthetic cache")

    context.before_result = simulate_yolo_cache
    finished = _execute(context, run)
    assert finished["status"] == "SUCCEEDED_CANDIDATE"
    assert finished["result"]["baseline"] == {"map50": 0.1, "map50_95": 0.05}
    assert finished["result"]["candidate"] == {"map50": 0.2, "map50_95": 0.08}
    assert original == {
        p.relative_to(frozen).as_posix(): p.read_bytes()
        for p in frozen.rglob("*")
        if p.is_file()
    }


def test_disabled_training_actor_cannot_publish_candidate(context):
    from visiondata_gate.identity_service import IdentityError, IdentityService

    identity = IdentityService(context.product)
    identity.setup(
        context.actor,
        login_name="synthetic_model_owner",
        display_name="Synthetic model owner",
        password="Test-only-local-credential-5917",
    )
    run = _launch(context)

    def disable_before_result(_kwargs):
        # Inject a persisted revocation while the owned calculation is in flight.
        with context.product.store._connection(immediate=True) as connection:
            connection.execute(
                "UPDATE identity_credentials SET status='DISABLED' WHERE user_id=?",
                (context.actor,),
            )

    context.before_result = disable_before_result
    context.service._execute_run(context.actor, context.project, run["run_id"])
    with pytest.raises(IdentityError):
        context.service.get_run(context.actor, context.project, run["run_id"])
    with context.product.store._connection() as connection:
        row = connection.execute(
            "SELECT body FROM vision_records WHERE id=?", (run["run_id"],)
        ).fetchone()
        persisted = json.loads(row[0])
        assert persisted["status"] == "FAILED"
        assert persisted["candidate_model_id"] is None
        assert (
            connection.execute(
                "SELECT COUNT(*) FROM vision_records WHERE kind='model'"
            ).fetchone()[0]
            == 0
        )
