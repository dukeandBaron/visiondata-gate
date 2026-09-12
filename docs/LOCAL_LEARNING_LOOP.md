# Local reference-learning loop

This is a **synthetic local HTTP reference workflow**, not reinforcement
learning, industrial model validation, a UI feature, or a new desktop installer.
The model is a six-weight NumPy CPU binary pixel logistic regressor using
`R/255, G/255, B/255, x, y, bias`. Training performs actual full-batch gradient
descent on labeled training pixels. Validation and final test use actual model
predictions and the unchanged default evaluation policy.

All human declarations made by this demonstration are explicitly marked
`SYNTHETIC_TEST_ACTOR`. They test the approval protocol; they are **not real
human acceptance, an industrial annotation review, or production authority**.

## Run from the existing project environment

From the project root, choose a directory name that has never been used:

```powershell
.venv/Scripts/python.exe tools/run_learning_demo.py --output-root output/learning-demo-01
```

The generic entry point is:

```text
python tools/run_learning_demo.py --output-root <new-directory>
```

The parent directory must already exist. Existing output directories, symbolic
links, and Windows junction/reparse paths are refused. Reruns require a fresh
directory name; the script does not delete or overwrite previous data, including
partial failed runs. Use `--timeout-seconds 360` when a slower machine needs more
time; the allowed whole-demo budget is 30–600 seconds, default 240.

The existing environment needs `httpx`, Pillow, NumPy, Uvicorn, and the project's
normal dependencies. The script does not install packages, import tests, use
`TestClient`, or silently replace a failed HTTP step with a direct service call.
The API must have `install_learning_routes` registered in `create_app`.

## What actually runs

1. Create one entirely new output root. Start an owned Uvicorn subprocess on an
   available `127.0.0.1` port with all ProductService state under that root.
   Verify health reports session-token-bound authentication, a bad token receives
   `401`, and the valid random token can access the private project API.
2. Through actual HTTP requests, create a project and upload four generated
   64×64 RGB PNGs: two train, one val, one test. Add normalized boxes
   `(x=.25, y=.25, width=.25, height=.25)`, matching each known synthetic square
   at pixels `[16:32,16:32]`. Preserve the resulting actual image SHA, annotation
   revision, and document SHA in the simulated H2 declarations.
3. Freeze the authorized operator-project snapshot. Create a task with all five
   tools (`image_quality`, `duplicate_leakage`, `annotation_integrity`,
   `coverage_matrix`, `governance_audit`) and `plan_approval_required=true`.
   Read its plan, submit `approve_plan`, wait for the actual `COMPLETED` state,
   and require actual compute preflight `READY_FOR_OFFLINE_HANDOFF`.
   This preflight does not itself run CANN, a remote worker, or an industrial model.
4. Create a learning cycle and run actual local CPU training. The demo uses
   **250 epochs, learning rate 1.5**, two maximum rounds, 1,000 maximum total
   epochs, and 120 seconds of cycle wall-time reservations. The per-round
   training bound is 20 seconds. The default evaluation thresholds are not relaxed.
5. For every actual validation error candidate, submit a clearly simulated
   `HARD_SAMPLE` review based on the known generated labels. No held-out example
   is automatically ingested as training data. Select `APPROVE_SANDBOX` only if
   the actual evaluation decision is `ELIGIBLE`; otherwise submit `REJECT` and
   retain the currently approved model.
6. Append two newly generated train images to the same project, retaining all
   original samples, val/test splits, groups, and original H2 declarations.
   Freeze a new source snapshot and run a second explicitly approved five-tool
   Gate task. Execute a second training round from the currently approved
   checkpoint. Verify its initial model SHA equals that checkpoint's actual SHA,
   its dataset ID changed, and the frozen val/test fingerprints did not change.
   If the first candidate was approved, this is genuine continuation from its
   trained weights. Otherwise the receipt explicitly shows continuation from the
   earlier approved baseline; the script does not claim a first-round promotion.
7. Review second-round error candidates and conditionally select/reject the model
   using the same policy. Finalize the cycle once with the held-out test. Require
   `FINALIZED`, `split=test`, and an empty per-sample test-feedback list. No further
   training or model selection is performed after consuming final test evidence.

The program retrieves fresh cycle and run receipts before state-changing review
and selection requests. Their current `receipt_sha256` values are the authority
bindings; stale receipts are not reused after feedback changes. Learning API
responses must return an ETag matching their receipt SHA.

**Two rounds do not promise two improvements or two promotions.** Loss, model
hashes, Dice, false-negative/false-positive rates, category regressions, latency,
feedback, and selection outcomes come only from actual responses. A successful
protocol run may correctly reject a later candidate. The status
`COMPLETED_REFERENCE_WORKFLOW` means the complete demonstration protocol finished,
not that industrial effectiveness, model promotion, or production release passed.

## HTTP surface used

| Purpose | Endpoint |
| --- | --- |
| Upload and annotate | `POST /v1/operator-workspaces/{workspace}/assets`; `PUT /v1/operator-workspaces/{workspace}/assets/{asset}/annotations` |
| Freeze labeled snapshot | `POST /v1/data-sources/operator-project-snapshots` |
| Create and approve Gate task | `POST /v1/tasks`; `POST /v1/tasks/{task}/interventions` with `approve_plan` |
| Read actual input gate | `GET /v1/tasks/{task}/compute-preflight` |
| Create cycle | `POST /v1/tasks/{task}/learning-cycles` |
| Train a round | `POST /v1/learning-cycles/{cycle}/rounds` |
| Read current receipts | `GET /v1/learning-cycles/{cycle}`; `GET /v1/learning-runs/{run}`; `GET /v1/learning-models/{model}` |
| Simulated feedback review | `POST /v1/learning-cycles/{cycle}/runs/{run}/feedback/{feedback}` |
| Conditional model selection | `POST /v1/learning-cycles/{cycle}/runs/{run}/selection` |
| Seal final test | `POST /v1/learning-cycles/{cycle}/finalize` |

Cycle creation/round execution requires an explicit training attestation, exact
group map, and current compute-preflight SHA. Feedback, selection, and finalizing
require reviewed declarations and current cycle SHA; selection also requires
current run SHA. Request schemas reject unsupported fields and arbitrary commands.

The underlying dataset guard is capped at 64 samples, 256×256 per image,
1,000,000 total image pixels, and 4 MiB per input file. It requires binary
masks (original annotation masks, or the explicitly attested learning copies
described below), each split nonempty, exact group coverage, and no cross-split group or
decoded-image leakage. The demo stays far below these limits: four initial then
six cumulative samples. The model allows at most 500 epochs per round; API cycle
contracts cap rounds at 10, total epochs at 2,000, and total reserved wall time at
600 seconds. The demonstration's own bounds above are intentionally smaller.

## Normal negatives and feedback evidence

Missing annotations alone are never treated as proof that an image has no
defects. `normal_mask_attestations` is an explicit per-member declaration with
reviewer, note, image SHA, annotation revision, annotation-document SHA, and
`operator_attests_no_foreground=true`. The service verifies these against the
actual frozen snapshot and requires empty original annotations. Only then may
the data freezer generate a zero-mask PNG inside the learning copy. It does not
alter the source snapshot or add a fictitious bounding box. The receipt records
`mask_origin=EXPLICIT_HUMAN_ZERO_MASK` and the declaration digest. Full normal-only
training input is still rejected by this binary supervised reference trainer
when positive pixels are absent.

`learning-readiness` projects actual Gate findings and tool status per member;
it does not equate defect labels with bad data or failed tools with good data.
`feedback/{feedback_id}/followup` binds a reviewed feedback item to a new checked
Gate and exact frozen members. The next round's `responds_to_feedback_ids` is
explicit: no errors are automatically declared addressed. Each provided ID must
have matching new-Gate evidence and training membership. `issue_closed=false`
remains: a linked dataset is not proof a label/model error has been fixed.

The scoped `learning-operations` GET reconciles writes by actor, project,
operation, target and request key. It returns the current verified result,
not a byte-identical replay of the first response. `NOT_FOUND` never means that
retrying a POST is safe; `automatic_retry_allowed=false` is explicit.

The final test compares the selected candidate to its prior approved parent
model, records both IDs and weight hashes, and retains the old baseline if the
candidate fails the final policy. `FINALIZED` means the one-shot test result was
sealed, not that a model passed. Consumed test pixels/groups cannot be reused
through a new cycle in the same project. Interrupted local execution can be
explicitly recovered after its lease; retrying needs a new authorization and
preserves the original failed/interrupted run and charged budget.

The current source web workbench has a `/learning` integration maintained by
Goal 1. See [workbench behavior](QUALITY_LEARNING_WORKBENCH.md) and the exact
[backend contract](LEARNING_API_HANDOFF.md). This does not update an older
installed desktop binary or publish the current dirty worktree.

## Outputs, isolation, and shutdown

`LEARNING_DEMO_RECEIPT.json` contains only selected actual result fields:
Gate task/preflight/approval hashes, dataset IDs and hashes, model hashes, real
training loss, aggregate/category validation/test metrics, feedback classifications,
selection actions, cycle state, and process-cleanup outcome. It contains no raw
image bytes, tokens, raw HTTP responses, command lines, or local absolute paths.
The terminal prints a small summary and the receipt file's actual SHA-256.

All synthetic operator uploads, frozen snapshots, local SQLite ledgers, model
weights, and training records remain under the new `product` subdirectory. Treat
that directory as a local working artifact; this command does not publish or
upload it. Failed runs preserve whatever was generated for scoped diagnosis.

The child receives an environment allowlist, not the caller's model/private
configuration, provider credentials, proxy settings, `PYTHONPATH`, or arbitrary
`VISIONDATA_*` values. Model and hosted transports are explicitly off; resource
and app-data locations are isolated under the output root. The session token is
random, passed only through the child environment and in-memory HTTP headers,
and is neither printed nor included in the receipt. The HTTP client ignores
environment proxies and redirects and uses only the owned loopback origin.
This is not a system-wide firewall or external network-traffic audit.

The generated PNGs are uploaded to local loopback only:
`raw_images_transmitted=false` means **no external-model/remote raw-image
transmission**, not absence of the local HTTP upload.

Shutdown first sends a private parent-owned stdin signal so Uvicorn performs its
normal graceful shutdown and closes ProductService. A bounded fallback may stop
only that exact owned subprocess if it does not exit; that makes the demo's final
status `FAILED`. The script never searches for or stops another user's process.

These boundaries remain false/not run regardless of training results:

```text
real_human_acceptance=false
industrial_performance_verified=false
reinforcement_learning=false
remote_execution_verified=false
remote_job_submitted=false
production_release_allowed=false
machine_write_permitted=false
native_gui_validation=NOT_RUN
installer_validation=NOT_RUN
```

Exit `0` means `COMPLETED_REFERENCE_WORKFLOW` with graceful owned-child shutdown.
Exit `2` means refusal or failure; inspect the receipt's safe `failure_stage` and
`failure_code` when a receipt was produced. No frontend, desktop binary, or
installer is rebuilt or updated by this demonstration.
