from __future__ import annotations

import hashlib

from visiondata_gate.audit_envelope import canonical_jcs_bytes

from tests import test_learning_lifecycle as lifecycle


HEADERS = lifecycle.HEADERS
learning_input = lifecycle.learning_input


def _sealed(response, expected_status=200):
    assert response.status_code == expected_status, response.text
    value = response.json()
    stable = {key: item for key, item in value.items() if key != "receipt_sha256"}
    digest = hashlib.sha256(canonical_jcs_bytes(stable)).hexdigest()
    assert value["receipt_sha256"] == digest
    assert response.headers["etag"] == f'"{digest}"'
    assert response.headers["x-content-sha256"] == digest
    assert response.headers["cache-control"] == "private, no-store"
    return value


def _create_cycle(client, task_id, preflight, groups):
    return _sealed(
        client.post(
            f"/v1/tasks/{task_id}/learning-cycles",
            headers=HEADERS,
            json={
                "request_key": "continual-api-cycle-0001",
                "expected_preflight_sha256": preflight["receipt_sha256"],
                "groups": groups,
                "operator_attests_training_authorized": True,
                "review_note": "Authorize synthetic continual-learning API test",
                "training": {"epochs": 250, "learning_rate": 1.5},
                "max_total_epochs": 800,
            },
        ),
        201,
    )


def _train_candidate(client, task_id, preflight, groups, cycle):
    cycle_path = f"/v1/learning-cycles/{cycle['cycle_id']}"
    run = _sealed(
        client.post(
            cycle_path + "/rounds",
            headers=HEADERS,
            json={
                "request_key": "continual-api-round-0001",
                "expected_preflight_sha256": preflight["receipt_sha256"],
                "groups": groups,
                "operator_attests_training_authorized": True,
                "review_note": "Run one synthetic candidate for retention binding",
                "task_id": task_id,
                "expected_cycle_sha256": cycle["receipt_sha256"],
            },
        )
    )
    assert run["status"] == "COMPLETED"
    assert run["evaluation"]["decision"] == "ELIGIBLE"
    for feedback in run["feedback"]:
        cycle = _sealed(client.get(cycle_path, headers=HEADERS))
        run = _sealed(
            client.post(
                cycle_path
                + f"/runs/{run['run_id']}/feedback/{feedback['feedback_id']}",
                headers=HEADERS,
                json={
                    "request_key": "review-" + feedback["feedback_id"],
                    "expected_cycle_sha256": cycle["receipt_sha256"],
                    "review_note": "Human reviewed this synthetic hard sample",
                    "operator_attests_reviewed": True,
                    "classification": "HARD_SAMPLE",
                },
            )
        )
    return _sealed(client.get(cycle_path, headers=HEADERS)), run


def _retention_payload(run, *, forgotten=False):
    final_capsules_auroc = 0.70 if forgotten else 0.89
    return {
        "request_key": (
            "continual-retention-hold-0001"
            if forgotten
            else "continual-retention-pass-0001"
        ),
        "review_note": "Bind an independent synthetic two-object retention matrix",
        "parent_model_id": run["initial_model_id"],
        "parent_model_sha256": run["initial_model_sha256"],
        "candidate_model_id": run["model_id"],
        "candidate_model_sha256": run["model_sha256"],
        "evidence_scope": "SYNTHETIC_CONTRACT_FIXTURE",
        "retention_dataset_sha256": "c" * 64,
        "retention_membership_sha256": "d" * 64,
        "evaluator_sha256": "e" * 64,
        "base_backbone_sha256": "9" * 64,
        "object_sequence": ["capsules", "pcb"],
        "policy": {
            "strategy": "REPLAY_DISTILLATION",
            "minimum_replay_samples_per_prior_object": 4,
            "require_frozen_backbone": True,
            "require_teacher_distillation": True,
            "metrics": [
                {
                    "metric_id": "image_auroc",
                    "direction": "HIGHER_IS_BETTER",
                    "max_average_forgetting": 0.03,
                    "max_worst_object_forgetting": 0.05,
                    "minimum_final_score": 0.80,
                },
                {
                    "metric_id": "normal_false_positive_rate",
                    "direction": "LOWER_IS_BETTER",
                    "max_average_forgetting": 0.02,
                    "max_worst_object_forgetting": 0.03,
                    "maximum_final_score": 0.15,
                },
            ],
        },
        "stages": [
            {
                "stage_index": 0,
                "trained_object_id": "capsules",
                "stage_model_sha256": run["initial_model_sha256"],
                "backbone_sha256": "9" * 64,
                "object_metrics": {
                    "capsules": {
                        "image_auroc": 0.90,
                        "normal_false_positive_rate": 0.08,
                    }
                },
                "replay_sample_counts": {},
                "replay_manifest_sha256": None,
                "teacher_model_sha256": None,
            },
            {
                "stage_index": 1,
                "trained_object_id": "pcb",
                "stage_model_sha256": run["model_sha256"],
                "backbone_sha256": "9" * 64,
                "object_metrics": {
                    "capsules": {
                        "image_auroc": final_capsules_auroc,
                        "normal_false_positive_rate": 0.09,
                    },
                    "pcb": {
                        "image_auroc": 0.87,
                        "normal_false_positive_rate": 0.10,
                    },
                },
                "replay_sample_counts": {"capsules": 4},
                "replay_manifest_sha256": "1" * 64,
                "teacher_model_sha256": run["initial_model_sha256"],
            },
        ],
        "operator_attests_independent_evaluation": True,
        "operator_attests_replay_buffer_authorized": True,
    }


def test_continual_retention_api_binds_eligible_receipt_to_model_selection(
    learning_input,
):
    client, _product, (task_id, preflight, groups) = learning_input
    cycle = _create_cycle(client, task_id, preflight, groups)
    cycle, run = _train_candidate(client, task_id, preflight, groups, cycle)
    endpoint = (
        f"/v1/projects/{cycle['project_id']}/continual-retention/evaluations"
    )
    outsider = client.post(
        endpoint,
        headers={"X-Actor-User-Id": "outsider"},
        json=_retention_payload(run),
    )
    assert outsider.status_code == 404
    receipt = _sealed(
        client.post(endpoint, headers=HEADERS, json=_retention_payload(run)),
        201,
    )
    assert receipt["sandbox_promotion_eligible"] is True
    assert (
        _sealed(
            client.get(
                endpoint + f"/{receipt['receipt_sha256']}", headers=HEADERS
            )
        )
        == receipt
    )

    selected = _sealed(
        client.post(
            f"/v1/learning-cycles/{cycle['cycle_id']}/runs/{run['run_id']}/selection",
            headers=HEADERS,
            json={
                "request_key": "continual-model-select-0001",
                "expected_cycle_sha256": cycle["receipt_sha256"],
                "expected_run_sha256": run["receipt_sha256"],
                "expected_continual_retention_receipt_sha256": receipt[
                    "receipt_sha256"
                ],
                "action": "APPROVE_SANDBOX_CONTINUAL",
                "review_note": "Approve only after the bound retention gate",
                "operator_attests_reviewed": True,
            },
        )
    )
    assert selected["champion_model_id"] == run["model_id"]
    selected_run = _sealed(
        client.get(f"/v1/learning-runs/{run['run_id']}", headers=HEADERS)
    )
    assert selected_run["selection"][
        "continual_retention_receipt_sha256"
    ] == receipt["receipt_sha256"]
    assert selected_run["production_release_allowed"] is False


def test_continual_selection_rejects_a_forgetting_hold_receipt(learning_input):
    client, _product, (task_id, preflight, groups) = learning_input
    cycle = _create_cycle(client, task_id, preflight, groups)
    cycle, run = _train_candidate(client, task_id, preflight, groups, cycle)
    endpoint = (
        f"/v1/projects/{cycle['project_id']}/continual-retention/evaluations"
    )
    receipt = _sealed(
        client.post(
            endpoint,
            headers=HEADERS,
            json=_retention_payload(run, forgotten=True),
        ),
        201,
    )
    assert receipt["decision"] == "HOLD_CATASTROPHIC_FORGETTING"

    response = client.post(
        f"/v1/learning-cycles/{cycle['cycle_id']}/runs/{run['run_id']}/selection",
        headers=HEADERS,
        json={
            "request_key": "continual-model-hold-0001",
            "expected_cycle_sha256": cycle["receipt_sha256"],
            "expected_run_sha256": run["receipt_sha256"],
            "expected_continual_retention_receipt_sha256": receipt[
                "receipt_sha256"
            ],
            "action": "APPROVE_SANDBOX_CONTINUAL",
            "review_note": "Attempting selection must preserve the HOLD",
            "operator_attests_reviewed": True,
        },
    )
    assert response.status_code == 409
    assert response.json()["error"]["code"] == "learning_hold"
    current = _sealed(
        client.get(f"/v1/learning-cycles/{cycle['cycle_id']}", headers=HEADERS)
    )
    assert current["champion_model_id"] == cycle["initial_model_id"]
    assert current["status"] == "AWAITING_REVIEW"
