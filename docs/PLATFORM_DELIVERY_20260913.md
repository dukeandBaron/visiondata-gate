# VisionData Gate — platform source update, 2026-09-13

This is the public description of a local-platform source candidate. It distinguishes implemented paths, development verification and unfinished release work. It does not certify every route, a new installation, a public deployment or industrial performance.

## What changed

| Area | Current source behavior | Boundary |
|---|---|---|
| Local accounts | First administrator setup, registration approval, login/logout, password and session management, account status and workspace membership | Loopback accounts, not enterprise SSO/MFA or audited public multitenancy |
| Desktop Web navigation | Graphite palette, five primary workflow destinations, expandable secondary routes, account/mode-scoped open pages, command search | No mobile product; not a complete audit of every historical page |
| Image workbook | Real file import, persisted boxes/labels, image evidence and pixel-profile interactions | No fabricated detection confidence or automatic label-truth claim |
| Task review | Backend-persisted plan, selected/rejected workers, reasons, budget and evidence; recoverable read states | Logs summarize actual execution, not private chain-of-thought or staged conversations |
| Remediation | CAPA approval, immutable parent, derived version and independent Child recheck | A saved work order or data-pool note does not prove a repair executed |
| Data pools | Full-member reviewed versions, qualified candidates, repair causes, evidence HOLD, new-source derivation and new task binding | No cross-snapshot union, automatic label truth or automatic training ingestion |
| Model center | Separate Agent Provider and local vision model/runtime/dataset management | No automatic dependency installation or weight download |
| Feedback loop | Authorized CPU detect training, validation feedback, human classification, explicit next-run association and manual selection | Candidate success does not imply better metrics, issue closure or production approval |

The five primary routes are `/workspace`, `/command-center`, `/data-pools`, `/models`, and `/capa`. Settings links to the model center rather than duplicating its editor. Integration pages prioritize actual source management; workflows without an executable adapter remain clearly labeled contracts.

## Authentication and actual authority

Before first setup, a launcher-owned startup capability authorizes local initialization. After setup, private business APIs require a real user Bearer; a startup capability does not read project data. Tokens are kept in browser memory rather than persistent browser storage.

Account approval does not join existing workspaces. Workspace ownership controls membership; a platform administrator does not implicitly own all projects. An ACTIVE user may explicitly create a new isolated workspace. Health and identity-status endpoints remain different from authenticated business access.

The source launcher recognizes the post-setup login requirement. An available local service is not evidence that a user is authenticated or that a factory is connected. See [Identity API](IDENTITY_API_CONTRACT.md).

## What closes the data loop

1. Import authorized images; save and review actual annotations and train/val/test purposes.
2. Freeze the source, approve a task, and measure with bounded professional tools.
3. Review each member against persisted findings. Unknown evidence remains HOLD.
4. Repair or recapture into a working copy; preserve the parent and produce a new version and independent Gate.
5. Bind a new pool review version to that new task. An unchanged old task does not become repaired through a note.
6. The model-data bridge requires the current complete pool, all-qualified review, Gate PASS and unchanged image/annotation identities.
7. Explicitly authorize training in a registered trusted external environment.
8. Review validation errors, obtain or revise new training data, and run another authorized round with new data and explicit feedback references.

Product NG and data usability are separate labels. A correctly captured defect is not discarded simply because the product is defective. `QUALIFIED_CANDIDATE` is not label truth, an automatic training approval or a production release.

A derived qualified subset still needs its own task/plan approval/Gate. When all members are qualified, the system references the existing full snapshot rather than claiming to have created new data. Validation/test membership cannot be silently relabeled as training data.

See [Workflow](PRIVATE_AGENT_PLATFORM_WORKFLOW.md), [Data-pool API](DATA_POOL_API_CONTRACT.md), [Training bridge](VISION_DATA_POOL_ADAPTER.md), and [Vision-model API](VISION_MODEL_API_CONTRACT.md).

## Evidence available from development

The development verification covers actual HTTP-backed isolated account/project/image/annotation interactions, pixel-profile operations, navigation and settings, plus scoped source and state contracts. These are local isolated test environments, not the user's production database.

Backend verification covers account authorization/lifecycle, current-source data-pool guards, model registration, bounded execution and feedback binding. The source includes the relevant tests so a public candidate can run its own checks. Their presence does not mean a new public checkout has already passed all tests.

A small two-round synthetic CPU detect run produced checkpoints and validation feedback. The training split grew from 4 to 6 samples while validation and test stayed at 2 each; round two initialized from round one's weights. **Both rounds had mAP 0; the second candidate was rejected.** This is an engineering-loop result, not a claimed detector improvement. No private raw receipt, dataset, checkpoint or user path is included as proof here.

Current executable visual training is CPU detect with at most 64 samples and bounded epochs, image size, threads and time. Registered segmentation metadata does not mean segmentation training exists. No TTT, GPU/NPU/CANN execution, customer efficacy or production approval is claimed.

Public benchmark evidence is documented separately in [Benchmarks](../benchmarks/README.md). Do not add its denominators to the above training example or treat synthetic terminal-state accuracy as detector accuracy.

## Build identity and what it does not prove

```text
package_version: 0.1.0
build_id: windows-platform-rebuild-20260913-03
frozen_source_content_sha256:
  41ebaac83ea726ad192a9850108cc4da422bdacf73a535a555c70d4a9f639f1d
```

This is the independent installer source freeze selected for runtime alignment. It contains explicitly listed working-tree content; the base Git commit alone cannot identify it. The digest is not the public repository tree hash or installer hash. The publication process must verify runtime files individually and identify public-only documentation differences.

The installer is being built separately. This source description does not announce an available executable or a successful extraction/installation. The package version remains 0.1.0, so same-version upgrades need their own validation. Core packaging includes local Tauri/Spring/FastAPI components; the optional Python/Torch/Ultralytics environment and weights remain external.

## HOLD and recovery rules

| Condition | Expected behavior |
|---|---|
| Verified projection cannot be refreshed | Mark stale/HOLD; never retain an unqualified PASS label |
| Result missing or API unavailable | Distinguish not-created, retryable unavailable and contract HOLD; provide a read/retry path |
| CAPA, pool or training write has an unknown outcome | Explicit GET reconciliation using the original operation identity; no automatic write replay |
| Source/annotation/pool version changes | Require re-freeze and recheck; do not bless old evidence |
| Training cancelled, failed or interrupted | Preserve the result and require an explicit new authorized request; no hidden restart |
| Browser-only static build | No local login/model APIs, backend upload or training execution |

Unfinished release matters: package-specific smoke and installed GUI, clean Windows machine, same-version upgrade, code signing, full Maven/JRE-inclusive SBOM, and current public CI/deployment/Release artifacts. These are separate gates, not one blanket “done.”

Unverified business matters: customer adoption, reduced delivery hours, NG-rate improvement, ROI, large-scale throughput and field safety acceptance. Production authority remains human-only with `production_release_allowed=false`.

The CANN/Ascend surface prepares governed job metadata only: `PREPARED_NOT_SUBMITTED`. It is neither NPU allocation nor a scheduler/driver integration receipt.

## Source navigation

- [Quickstart](quickstart.md)
- [Publication boundary](PUBLICATION_BOUNDARY.md)
- [Claim scope](CLAIM_SCOPE.md)
- [Windows installer contract](WINDOWS_INSTALLER.md)
- [Architecture](architecture.md)
- [API overview](api_reference.md)
