"""Real synthetic HTTP learning receipts consumed by the TypeScript validators.

Only pytest-owned images, masks and ProductService storage are used. This is one
cross-language contract test, not a browser, device or industrial-effectiveness
claim. No receipt is invented or re-sealed on the JavaScript side.
"""

from __future__ import annotations

import json
from pathlib import Path
import shutil
import subprocess

import pytest

from tests import test_learning_api as http_helpers
from tests import test_learning_lifecycle as lifecycle


learning_input = lifecycle.learning_input
HEADERS = lifecycle.HEADERS

_VALIDATE_REAL_RECEIPTS = r"""
import assert from 'node:assert/strict';
import { pathToFileURL } from 'node:url';

const domain = await import(pathToFileURL(process.argv[1]).href);
let source = '';
for await (const chunk of process.stdin) source += chunk;
const { scope, records } = JSON.parse(source);
const stages = [];
for (const { stage, kind, value, etag } of records) {
  try {
    let validated;
    if (kind === 'cycle') {
      validated = await domain.validateLearningCycle(value, scope, value.cycle_id, etag);
    } else if (kind === 'run') {
      validated = await domain.validateLearningRun(value, scope, value.cycle_id, value.run_id, etag);
    } else if (kind === 'readiness') {
      validated = await domain.validateLearningReadiness(value, scope, value.task_id, etag);
    } else if (kind === 'operation') {
      validated = await domain.validateLearningOperation(
        value, scope, value.operation, value.request_key, value.target_id, etag,
      );
    } else {
      assert.fail(`Unsupported actual receipt kind: ${kind}`);
    }
    assert.deepEqual(validated, value);
    stages.push(stage);
  } catch (error) {
    throw new Error(`Actual backend receipt rejected at ${stage}: ${error.message}`, { cause: error });
  }
}
assert.ok(stages.includes('created'));
assert.ok(stages.includes('readiness'));
assert.ok(stages.includes('completed'));
assert.ok(stages.some(stage => stage.startsWith('feedback-')));
assert.ok(stages.includes('selected'));
assert.ok(stages.includes('selected-run'));
assert.ok(stages.includes('finalized'));
assert.ok(stages.includes('operation-create'));
process.stdout.write(JSON.stringify({ verified_receipts: records.length, stages }));
"""


@pytest.mark.tier_integration
def test_real_backend_learning_receipts_pass_web_contract(learning_input):
    """Exercise actual Gate -> train -> triage -> selection -> final test JSON."""
    node = shutil.which("node")
    assert node, "NODE_REQUIRED: cross-language contract validation was not run"
    client, _product, (task_id, preflight, groups) = learning_input
    records = []

    def capture(response, stage, kind="cycle", expected_status=200):
        value = http_helpers._sealed(response, expected_status)
        records.append(
            {
                "stage": stage,
                "kind": kind,
                "value": value,
                "etag": response.headers["etag"],
            }
        )
        return value

    assert preflight["eligibility"] == "READY_FOR_OFFLINE_HANDOFF"
    assert preflight["binding"]["sample_count"] == 4
    readiness = capture(
        client.get(f"/v1/tasks/{task_id}/learning-readiness", headers=HEADERS),
        "readiness",
        "readiness",
    )
    assert readiness["task_id"] == task_id
    assert readiness["projection_status"] == "VERIFIED"
    assert readiness["preflight_receipt_sha256"] == preflight["receipt_sha256"]
    assert readiness["training_authorized"] is False
    assert len(readiness["members"]) == 4
    cycle = capture(
        client.post(
            f"/v1/tasks/{task_id}/learning-cycles",
            headers=HEADERS,
            json=http_helpers._create_payload(
                preflight,
                groups,
                training={"epochs": 250, "learning_rate": 1.5},
                max_total_epochs=800,
            ),
        ),
        "created",
        expected_status=201,
    )
    cycle_path = f"/v1/learning-cycles/{cycle['cycle_id']}"
    run = capture(
        client.post(
            cycle_path + "/rounds",
            headers=HEADERS,
            json={
                **http_helpers._create_payload(
                    preflight, groups, request_key="cross-language-round-001"
                ),
                "task_id": task_id,
                "expected_cycle_sha256": cycle["receipt_sha256"],
            },
        ),
        "completed",
        "run",
    )
    assert run["status"] == "COMPLETED", run
    assert run["training"]["loss_after"] < run["training"]["loss_before"]
    assert run["evaluation"]["decision"] == "ELIGIBLE"
    assert run["feedback"], "Synthetic fixture must exercise actual model errors"
    for index, item in enumerate(list(run["feedback"])):
        cycle = capture(client.get(cycle_path, headers=HEADERS), f"review-base-{index}")
        run = capture(
            client.post(
                cycle_path + f"/runs/{run['run_id']}/feedback/{item['feedback_id']}",
                headers=HEADERS,
                json=http_helpers._action(
                    cycle,
                    "review-" + item["feedback_id"],
                    classification="HARD_SAMPLE",
                ),
            ),
            f"feedback-{index}",
            "run",
        )
    assert all(
        item["status"] == "TRIAGED_NOT_AUTO_INGESTED" for item in run["feedback"]
    )
    cycle = capture(client.get(cycle_path, headers=HEADERS), "selection-base")
    cycle = capture(
        client.post(
            cycle_path + f"/runs/{run['run_id']}/selection",
            headers=HEADERS,
            json=http_helpers._action(
                cycle,
                "cross-language-selection-001",
                expected_run_sha256=run["receipt_sha256"],
                action="APPROVE_SANDBOX",
            ),
        ),
        "selected",
    )
    assert cycle["champion_model_id"] == run["model_id"]
    capture(
        client.get(f"/v1/learning-runs/{run['run_id']}", headers=HEADERS),
        "selected-run",
        "run",
    )
    final = capture(
        client.post(
            cycle_path + "/finalize",
            headers=HEADERS,
            json=http_helpers._action(cycle, "cross-language-finalize-001"),
        ),
        "finalized",
    )
    assert final["status"] == "FINALIZED"
    assert final["final_evaluation"]["split"] == "test"
    assert final["final_evaluation"]["sample_results"] == []
    assert final["production_release_allowed"] is False
    operation = capture(
        client.get(
            f"/v1/projects/{final['project_id']}/learning-operations/create/"
            "api-cycle-create-0001",
            headers=HEADERS,
            params={"target_id": task_id},
        ),
        "operation-create",
        "operation",
    )
    assert operation["operation"] == "create"
    assert operation["request_key"] == "api-cycle-create-0001"
    assert operation["target_id"] == task_id
    assert operation["lookup_status"] == "FOUND"
    assert (
        operation["request_digest_verification"] == "MATCHED_STORED_VALIDATED_REQUEST"
    )
    assert operation["current_result"] == final
    assert operation["automatic_retry_allowed"] is False
    scope = {"workspaceId": final["workspace_id"], "projectId": final["project_id"]}
    root = Path(__file__).resolve().parents[1]
    completed = subprocess.run(
        [
            node,
            "--input-type=module",
            "-e",
            _VALIDATE_REAL_RECEIPTS,
            str(root / "web" / "src" / "learningDomain.ts"),
        ],
        input=json.dumps({"scope": scope, "records": records}),
        capture_output=True,
        text=True,
        encoding="utf-8",
        timeout=30,
        check=False,
        cwd=root,
    )
    assert completed.returncode == 0, completed.stderr
    result = json.loads(completed.stdout)
    assert result["verified_receipts"] == len(records)
    assert result["stages"] == [record["stage"] for record in records]
