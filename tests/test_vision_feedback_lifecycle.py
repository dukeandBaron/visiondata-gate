"""Real project/dataset persistence with explicitly synthetic model feedback."""

from __future__ import annotations

import copy
import json

import pytest
from pydantic import ValidationError

from tests.test_vision_feedback import feedback_result
from tests.test_vision_training_lifecycle import (
    _dataset,
    _execute,
    _launch,
    _named,
    _no_candidates,
    _request,
    context as context,
)
from visiondata_gate import learning_yolo_backend as backend
from visiondata_gate import local_model_registry as registry
from visiondata_gate.product_models import CreateProjectRequest
from visiondata_gate.task_store import NotFoundError


def _install_feedback(context, monkeypatch, *, clear=False, mutate=None):
    original_backend = backend.run_yolo_training

    def produce(**kwargs):
        result = original_backend(**kwargs)
        frozen = json.loads(
            (kwargs["dataset_root"] / "dataset.json").read_text("utf-8")
        )
        result["dataset_sha256"] = backend._dataset_receipt(kwargs["dataset_root"])[
            "sha256"
        ]
        result["runtime_sha256"] = kwargs["expected_runtime_sha256"]
        result = feedback_result(frozen, clear=clear, base=result)
        if mutate:
            mutate(result)
        return result

    monkeypatch.setattr(backend, "run_yolo_training", produce)


def _completed(context, monkeypatch, **options):
    _install_feedback(context, monkeypatch, **options)
    finished = _execute(context, _launch(context))
    assert finished["status"] == "SUCCEEDED_CANDIDATE"
    return finished


def _items(context, run):
    return context.service.list_feedback(context.actor, context.project, run["run_id"])[
        "items"
    ]


def _review(run, item, classification="MODEL_ERROR", **updates):
    return registry.ReviewVisionFeedback(
        **_named(
            "feedback-review-0001",
            expected_run_sha256=run["receipt_sha256"],
            expected_feedback_sha256=item["receipt_sha256"],
            operator_attests_reviewed=True,
            classification=classification,
        )
        | updates
    )


def _triage(context, run, item, classification="MODEL_ERROR", **updates):
    return context.service.triage_feedback(
        context.actor,
        context.project,
        run["run_id"],
        item["feedback_id"],
        _review(run, item, classification, **updates),
    )


def _respond(context, feedback, dataset=None):
    updates = {
        "request_key": "feedback-response-0001",
        "responds_to_feedback_ids": [feedback["feedback_id"]],
        "expected_feedback_receipts": {
            feedback["feedback_id"]: feedback["receipt_sha256"]
        },
    }
    if dataset is not None:
        updates.update(
            dataset_id=dataset["dataset_id"],
            expected_dataset_receipt_sha256=dataset["dataset_receipt_sha256"],
        )
    request = _request(context, **updates)
    return context.service.create_training_run(context.actor, context.project, request)


def _assert_only_original_candidate(context):
    models = context.service.list_models(context.actor, context.project)["items"]
    assert len(models) == 1
    assert models[0]["status"] == "CANDIDATE_REQUIRES_HUMAN_REVIEW"
    assert models[0]["production_release_allowed"] is False


def test_false_negative_persists_with_human_triage_idempotency(context, monkeypatch):
    run = _completed(context, monkeypatch)
    assert run["feedback_status"] == "VAL_DISAGREEMENTS_REQUIRE_HUMAN_REVIEW"
    (item,) = _items(context, run)
    assert run["feedback_ids"] == [item["feedback_id"]]
    assert item["detail"]["fn"] == 1
    assert item["status"] == "PENDING_HUMAN_REVIEW"
    reviewed = _triage(context, run, item)
    assert _triage(context, run, item) == reviewed
    assert reviewed["status"] == "TRIAGED_FOR_REVIEW"
    assert reviewed["classification"] == "MODEL_ERROR"
    for key in (
        "issue_closed",
        "label_truth_authority",
        "training_ingestion_allowed",
        "production_release_allowed",
    ):
        assert reviewed[key] is False
    _assert_only_original_candidate(context)


def test_clear_val_is_explicit_and_creates_no_feedback(context, monkeypatch):
    run = _completed(context, monkeypatch, clear=True)
    assert run["feedback_status"] == "NO_VAL_DISAGREEMENT_AT_FIXED_PROTOCOL"
    assert run["feedback_ids"] == []
    assert _items(context, run) == []


def test_missing_protocol_is_explicit_legacy_not_available(context):
    run = _execute(context, _launch(context))
    assert run["status"] == "SUCCEEDED_CANDIDATE"
    assert run["feedback_status"] == "NOT_AVAILABLE_LEGACY_RESULT"
    assert _items(context, run) == []


@pytest.mark.parametrize(
    "tamper",
    [
        "protocol",
        "split",
        "truth",
        "class",
        "fp",
        "image_sha",
        "checkpoint_sha",
        "compact",
    ],
)
def test_bad_feedback_rejects_model_publication_atomically(
    context, monkeypatch, tamper
):
    def corrupt(result):
        protocol = result["validation_feedback_protocol"]
        row = result["validation_samples_detail"][0]
        if tamper == "protocol":
            protocol["schema_version"] = "unsupported-protocol.v99"
        elif tamper == "split":
            protocol["split"] = "test"
        elif tamper == "truth":
            row["ground_truth_boxes"][0]["xyxy"][0] = 0.1
        elif tamper == "class":
            row["prediction_boxes"] = [
                {"class_id": 1, "xyxy": [0.1, 0.1, 0.5, 0.5], "confidence": 0.9}
            ]
        elif tamper == "fp":
            row["fp"] = 20
        elif tamper == "image_sha":
            row["image_sha256"] = "0" * 64
        elif tamper == "checkpoint_sha":
            protocol["checkpoint_sha256"] = "0" * 64
        else:
            result["validation_feedback_candidates"][0]["fn"] = 0

        # A forged detail and compact summary can agree. Counts and member SHA
        # must still be recomputed from the frozen source rather than trusted.
        if tamper in {"fp", "image_sha"}:
            key = "fp" if tamper == "fp" else "image_sha256"
            result["validation_feedback_candidates"][0][key] = row[key]

    _install_feedback(context, monkeypatch, mutate=corrupt)
    run = _execute(context, _launch(context))
    assert run["status"] == "FAILED"
    assert run["candidate_model_id"] is None
    assert _items(context, run) == []
    _no_candidates(context)


@pytest.mark.parametrize("field", ["expected_run_sha256", "expected_feedback_sha256"])
def test_triage_requires_current_run_and_feedback_sha(context, monkeypatch, field):
    run = _completed(context, monkeypatch)
    (item,) = _items(context, run)
    with pytest.raises(registry.VisionModelError, match="STALE_RUN_OR_FEEDBACK"):
        _triage(context, run, item, **{field: "0" * 64})
    assert _items(context, run) == [item]
    _assert_only_original_candidate(context)


def test_triage_scope_stays_bound_even_on_idempotent_replay(context, monkeypatch):
    run = _completed(context, monkeypatch)
    (item,) = _items(context, run)
    request = _review(run, item)
    reviewed = _triage(context, run, item)
    other_run = _launch(context, request_key="other-run-start-0001")
    with pytest.raises(NotFoundError):
        context.service.triage_feedback(
            context.actor,
            context.project,
            other_run["run_id"],
            item["feedback_id"],
            request,
        )
    other_project = context.product.create_project(
        context.actor,
        CreateProjectRequest(
            workspace_id=context.workspace, name="Other feedback project"
        ),
    ).project_id
    with pytest.raises(NotFoundError):
        context.service.list_feedback(context.actor, other_project, run["run_id"])
    assert _items(context, run) == [reviewed]
    assert _items(context, other_run) == []
    _assert_only_original_candidate(context)


@pytest.mark.parametrize("classification", [None, "UNKNOWN"])
def test_unreviewed_or_unknown_feedback_cannot_authorize_response(
    context, monkeypatch, classification
):
    run = _completed(context, monkeypatch)
    (item,) = _items(context, run)
    if classification:
        item = _triage(context, run, item, classification)
    with pytest.raises(
        registry.VisionModelError, match="FEEDBACK_NOT_CURRENT_OR_TRIAGED"
    ):
        _respond(context, item)
    assert len(context.pending) == 1
    _assert_only_original_candidate(context)


def test_different_registration_id_cannot_disguise_identical_dataset_receipt(
    context, monkeypatch
):
    run = _completed(context, monkeypatch)
    item = _triage(context, run, _items(context, run)[0])
    duplicate = _dataset(context, "dataset-copy-0000001")
    assert duplicate["dataset_id"] != run["dataset_id"]
    assert duplicate["dataset_receipt_sha256"] == run["dataset_receipt_sha256"]
    with pytest.raises(
        registry.VisionModelError, match="FEEDBACK_REQUIRES_NEW_DATA_VERSION"
    ):
        _respond(context, item, duplicate)
    assert len(context.pending) == 1
    _assert_only_original_candidate(context)


def test_response_accepts_changed_reviewed_labels_and_keeps_holdout_assignments(
    context, monkeypatch
):
    run = _completed(context, monkeypatch)
    item = _triage(context, run, _items(context, run)[0], "LABEL_REVIEW_REQUIRED")
    changed = copy.deepcopy(context.manifest)
    changed["source_version"] = "synthetic-lifecycle-v2-reviewed"
    changed["samples"][0]["annotation_revision"] = 2
    changed["samples"][0]["boxes"][0]["width"] = 0.4
    dataset = _dataset(context, "dataset-revised-0001", changed)
    original_splits = {
        (row["sample_id"], row["group_id"], row["split"])
        for row in context.manifest["samples"]
    }
    assert {
        (row["sample_id"], row["group_id"], row["split"])
        for row in dataset["dataset_receipt"]["samples"]
    } == original_splits
    response = _respond(context, item, dataset)
    assert response["status"] == "QUEUED"
    assert response["responds_to_feedback_ids"] == [item["feedback_id"]]
    assert response["dataset_receipt_sha256"] != run["dataset_receipt_sha256"]
    assert _items(context, run)[0]["issue_closed"] is False
    _assert_only_original_candidate(context)


def test_source_version_text_alone_cannot_claim_a_new_training_dataset(
    context, monkeypatch
):
    run = _completed(context, monkeypatch)
    item = _triage(context, run, _items(context, run)[0])
    renamed = copy.deepcopy(context.manifest)
    renamed["source_version"] = "renamed-only-no-real-data-change"
    dataset = _dataset(context, "dataset-renamed-0001", renamed)
    assert dataset["dataset_receipt_sha256"] != run["dataset_receipt_sha256"]
    with pytest.raises(
        registry.VisionModelError, match="FEEDBACK_REQUIRES_CHANGED_IMAGES_OR_LABELS"
    ):
        _respond(context, item, dataset)
    assert len(context.pending) == 1
    _assert_only_original_candidate(context)


def test_response_ids_and_expected_receipts_must_match_exactly(context):
    request = _request(context)
    identifier = "vfeedback_" + "a" * 24
    invalid_bindings = (
        {"responds_to_feedback_ids": [identifier], "expected_feedback_receipts": {}},
        {
            "responds_to_feedback_ids": [],
            "expected_feedback_receipts": {identifier: "a" * 64},
        },
        {
            "responds_to_feedback_ids": [identifier, identifier],
            "expected_feedback_receipts": {identifier: "a" * 64},
        },
        {
            "responds_to_feedback_ids": [identifier],
            "expected_feedback_receipts": {identifier: "not-a-sha"},
        },
    )
    for binding in invalid_bindings:
        with pytest.raises(ValidationError):
            context.service.create_training_run(
                context.actor, context.project, request.model_copy(update=binding)
            )
    assert not context.pending
    _no_candidates(context)
