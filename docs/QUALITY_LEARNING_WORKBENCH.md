# Data disposition and local learning workbench

## What is connected

The authenticated desktop-web route `/learning` consumes the existing local
learning HTTP API. It is linked from the task workspace, navigation and offline
compute page. It does not appear as a live mutation feature in public replay.

The page can:

- Select a completed task and read its actual compute preflight and full frozen
  visual-evidence membership. Workspace, project, task, source, snapshot receipt
  and member count must agree before the input form becomes usable.
- Ask the reviewer for a real collection group for every sample. It never makes
  up independent groups from image IDs. The server remains authoritative for
  split leakage, binary masks, resource limits and active source authorization.
- Create a learning cycle without training. Running a bounded local CPU round
  requires a separate explicit authorization and the current cycle/preflight SHA.
- Show train/val/test members, category labels, collection groups, image digests,
  model lineage, measured metrics, pending feedback and the real cycle state.
- Open the original round's frozen preview and mask on demand. These are bound
  to the source snapshot and their bytes are checked by the existing image API.
  The mask is an annotation artifact, not a model prediction. Failed refreshes
  clear the old preview rather than presenting it as current evidence.
- Record human feedback as `LABEL_ERROR`, `HARD_SAMPLE`, `DISTRIBUTION_SHIFT` or
  `INSUFFICIENT_EVIDENCE`; display the actual backend response and refresh the
  cycle before another action. No review moves val/test members into train.
- Read `learning-readiness` for per-sample action states and batch blockers.
  Filter checked, needs-attention and unverified members without labelling all
  defect images as bad data or counting findings as affected-image totals.
- Submit explicit named normal-negative declarations bound to the frozen image
  SHA, annotation revision and document SHA. The backend creates verified zero-mask
  learning copies only for actual empty-annotation samples, without changing originals.
- Link reviewed feedback to a new checked task and its specific frozen samples.
  A later round explicitly selects which verified links it responds to; nothing
  is automatically marked fixed or blindly copied from the previous round.
- Offer explicit sandbox model selection/rejection, next-round input, stopping,
  interruption recovery and one-time final-test sealing when backend state permits.

The reference learner is a bounded six-weight pixel logistic model on local CPU.
This is not a general industrial segmentation trainer, factory deployment,
reinforcement learning, or a live CANN/NPU connection. `FINALIZED` means the final
test is sealed; its evaluation can still be `HOLD`.

## Three different questions

| Question | Fact shown by the workbench | What must not be inferred |
| --- | --- | --- |
| Does this product image show a defect? | The declared category and reviewed annotation | A defective product image is not automatically unusable data. |
| May this data version be used for this purpose? | Frozen task/acceptance/Gate binding and learning dataset membership | Batch PASS alone is not universal per-sample quality certification. |
| Did the model predict correctly? | Real validation prediction metrics and human feedback classification | Prediction error alone does not prove an annotation error. |

No new browser-only good/bad ledger is created. Workbook heuristic filters and
learning feedback counts are not a persisted quality-release decision, and
finding counts must not be reported as numbers of repaired images.

## Recovery and authority

Single learning responses require a matching strong ETag and recomputed JCS
receipt hash. Cycle lists validate every member. Dataset hashing has a distinct
contract: both `dataset_id` and `receipt_sha256` are omitted from its hash body.
Unknown fields/states/scope drift fail closed; `null` metrics remain unmeasured.

The page saves the request identity before sending a POST, in this browser's
local persistent storage, scoped to workspace/project. Same-origin Web Locks
prevent simultaneous writes from this browser's other windows; storage changes
invalidate the other window's action eligibility. This is not a server-side or
cross-browser global lock. Stored identifiers contain no credentials, images or
review text. Do not clear storage to work around an ambiguous write.

After a timeout, 5xx or invalid response, only explicit GET reconciliation is
offered through `/v1/projects/{project}/learning-operations/{operation}/{key}`
with its exact target ID. `NOT_FOUND` does not prove no write occurred; `PENDING`
remains locked. Only a verified `FOUND / RESULT_AVAILABLE` clears the pending
identity, followed by another cycle refresh before actions become eligible.
Matching text/classification alone is not a unique operation receipt. Pre-dispatch
validation failures are separately marked `LEARNING_REQUEST_NOT_SENT`; response
validation failures stay unknown. Failed reads mark historical values `STALE_HOLD`
and disable actions. Same-project background connection updates preserve unsaved
forms; switching project removes the previous project's editable content.

## Goal 1 / Goal 2 integration and remaining boundary

Goal 2 owns `learning_projection.py`, `learning_operations.py`, the normal-mask
authority and feedback-followup backend. Goal 1 owns this UI, strict client
consumption and cross-language/browser tests. The four seams found in the first
audit now have consumed contracts:

| Seam | Backend fact consumed |
| --- | --- |
| Sample action states | `GET /v1/tasks/{task}/learning-readiness`, with sample findings, global blockers and unverified states |
| New-version feedback evidence | `POST .../feedback/{feedback}/followup`, new Gate binding and exact sample/revision identities |
| Normal negative masks | `normal_mask_attestations`, actual `EXPLICIT_HUMAN_ZERO_MASK` copies with declaration hashes |
| Unknown writes | Exact actor/project/operation/key/target GET lookup, sealed current-result pointer |

**Issue resolution remains a deliberate HOLD.** The new linkage is
`NEW_GATE_EVIDENCE_LINKED_NOT_ISSUE_CLOSED` with `issue_closed=false`. It proves
that a person linked specific new checked data, not that every model error was
causally solved. Generic automated relabeling, universal data-goodness scoring,
automatic CAPA closure, industrial accuracy gains and live NPU execution are not
claimed. Label-error feedback still requires a new evaluation protocol. The
final-test decision and retained/reverted champion are displayed separately from
the fact that a cycle was sealed.

Update DTO/validator/tests together when a backend contract changes; do not simply
bypass validation to make a new field display.

## How to inspect locally

Start the existing configured local workbench and open `/learning` (or select
“数据与学习闭环” in navigation). Choose an actual project; no sample cycle is
created on page load. From a task, the button carries its real `task` query ID.

Verification commands from the repository root:

```text
npm run typecheck --prefix web
npm run build --prefix web
node --test tests/web_learning_contracts.test.mjs
node --test tests/web_learning_loop.browser.mjs
.venv/Scripts/python.exe -m pytest tests/test_learning_api.py tests/test_learning_lifecycle.py tests/test_learning_dataset.py -q
.venv/Scripts/python.exe -m pytest tests/test_learning_web_contract.py -q
```

The browser component tests use synthetic API doubles; they are not industrial
model validation or installed-GUI evidence. Backend tests use isolated generated
samples and test stores. No customer images, remote compute or production release
are part of those checks.
