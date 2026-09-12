# Local learning: operation and recovery

VisionData Gate governs the data-to-model feedback loop. It is a data gate and
an evidence workbench, not an autonomous production inspection controller.
The local reference learner is a six-weight NumPy pixel classifier. It executes
real supervised optimization but is not reinforcement learning or a substitute
for validation of an industrial segmentation model.

## Run a cycle from the workspace

1. In the image workspace, upload your authorized images and save/review the
   actual annotations. Declare the task, label vocabulary, expected annotations
   and train/validation/test assignment. A picture of a defective part can still
   be valuable, correctly annotated training data.
2. Freeze the reviewed input and explicitly approve the Gate task. Open the
   learning workspace for that completed task. The server's readiness record
   must match the project, snapshot and current preflight digest.
3. Supply the actual collection groups. Do not invent separate groups to bypass
   train/validation/test separation. For genuinely normal images without masks,
   explicitly review and attest the current image and empty annotation version;
   the server may then create a zero mask in the learning copy only.
4. Create the cycle with a budget that admits at least one round. This does not
   start training. Authorize a separate bounded round to produce a candidate,
   parent-model/data lineage, validation metrics and reviewable errors.
5. Review each model error. Label errors, valid hard samples, distribution shift
   and insufficient evidence imply different data actions. Model error alone
   never proves the label is wrong. Select or reject the candidate explicitly;
   selection is sandbox-only.
6. If another round is needed, collect or correct **training** data, approve a new
   Gate, and link its exact members to reviewed feedback. Explicitly select the
   feedback IDs for the next round. Validation/test members remain held out.
7. Seal the final test once. `FINALIZED` means the protocol is closed, not that
   the candidate passed. A failed final policy retains/restores the baseline.

Current reference limits are 64 samples, 256 × 256 pixels per image, one million
total pixels, binary masks and nonempty train/validation/test splits. These are
intentional bounds of this trainer, not limits of all image-workspace uploads.

## Interruption is not the same as a slow request

Training and final-test evaluation hold the same cycle-scoped operating-system
lock from reservation through result publication. Recovery first checks the
registered execution owner and must acquire that lock. A live owner raises
`EXECUTION_OWNER_ACTIVE` internally; the API keeps its compatible `learning_hold`
code and supplies an allowlisted message explaining that the cycle is still
running. Refreshing or waiting is appropriate, not forcing another round.
Training recovery additionally retains its execution lease.

If an older cycle has no registered owner, recovery holds with the internal
reason `EXECUTION_OWNERSHIP_UNKNOWN` and an explicit legacy-ownership message.
An absent lock is not evidence that an older
executor has stopped. Preserve the existing product state and diagnose that
cycle rather than editing its status or reusing its test set.

A stopped final evaluation keeps the test set consumed. Do not delete
`learning_consumed_tests`, modify the ledger, or retry the final test until a
favorable result appears. A genuinely new evaluation protocol requires new
independent evaluation evidence.

An ambiguous HTTP write is different again: use the workspace's exact
request-key GET reconciliation. `NOT_FOUND` is not proof of no write;
`PENDING` does not authorize retry. Do not clear browser storage to bypass an
unknown-write hold.

## Backup and privacy

Offline backup, verification and restore reject unresolved learning
`RUNNING` / `FINALIZING` records, including otherwise byte-consistent old
snapshots. Complete or explicitly recover the original execution first.
Source images, private databases, keys, generated models and partial learning
directories are not public release assets. Failed creation can leave unreferenced
generated copies; those are retained for diagnosis, never automatically deleted.

The desktop candidate must carry its own FastAPI executable, Spring gateway and
Java runtime. Release builds do not use development-machine resource fallbacks.
Package HTTP verification, native GUI operation, actual installation and a
clean-machine check are distinct evidence levels; consult the candidate's own
receipt before distributing it.

For exact endpoints and hash contracts see [the API handoff](LEARNING_API_HANDOFF.md).
For display semantics see [the learning workbench](QUALITY_LEARNING_WORKBENCH.md).
