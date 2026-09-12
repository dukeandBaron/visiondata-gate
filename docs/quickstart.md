# Quickstart

VisionData Gate has two deliberately separate runtime modes:

- **Local workbench** — FastAPI + React, actual local accounts, project state, image/annotation storage and explicitly authorized workflow actions.
- **Public synthetic replay** — a static build for public examples and browser-local inspection. It has no backend, server account, provider key, customer database or training service.

A public repository includes local application source; that does not deploy its APIs to Pages. See [Publication boundary](PUBLICATION_BOUNDARY.md).

## Requirements

For the Windows source workbench:

- Windows 10/11.
- Python 3.12 and [uv](https://docs.astral.sh/uv/).
- Node.js 22 or newer.

Initial dependency installation needs access to package sources. The React source is portable, but this update does not certify macOS/Linux desktop installation. The current Windows candidate is separately building; do not treat these source instructions as proof of an available signed installer. See [Windows installer](WINDOWS_INSTALLER.md).

Optional visual training requires a separately installed, trusted external Python/Torch/Ultralytics environment and properly licensed weights, if used. Those are not part of the core source-workbench startup requirement.

## Install and start

```powershell
git clone https://github.com/dukeandBaron/visiondata-gate.git
cd visiondata-gate
.\setup_env.ps1
.\run_workbench.ps1 -Install
```

Setup installs the lockfile-pinned core Python and Web dependencies in the project. The launcher starts loopback services and opens the workbench with the one-time startup bootstrap context. Do not share that context or paste startup/session credentials into an issue.

| Surface | Default address |
|---|---|
| Workbench | `http://127.0.0.1:4173/workspace` |
| API health | `http://127.0.0.1:8787/v1/health` |
| OpenAPI | `http://127.0.0.1:8787/docs` |

For hot reload:

```powershell
.\run_workbench.ps1 -Mode Dev -Install
```

Keep the launcher running while using its services. If its ports are occupied, use an unoccupied pair or stop only your own earlier session; do not attach a new startup capability to an unverified listener.

## First account and workspace

1. Use the page opened by the launcher to create the first local administrator. First setup requires the launcher-owned capability and actual loopback access.
2. On subsequent launches, log in with your local account. Model API keys are not login passwords.
3. Additional users can register; their accounts remain PENDING until approved by an administrator. Approval does not automatically join a project or workspace.
4. An ACTIVE user can explicitly create a workspace, or a workspace owner can add that user as a member.
5. Create or select a project inside an authorized workspace.

After setup, all private business APIs require a user Bearer. The startup capability only retains its narrow initialization/lifecycle role; it is not business authentication. A health response does not prove user authentication.

The browser keeps the access token in memory, not persistent browser storage. Refreshing or reopening can require login again. Password replacement revokes sessions; session recovery does not mean restarting approved tasks. See [Identity API](IDENTITY_API_CONTRACT.md) for exact access and error contracts.

## Use the workbook

The five daily destinations are:

| Destination | First useful action |
|---|---|
| Image workbook `/workspace` | Import your images, label actual regions, save and review annotations |
| Work overview `/command-center` | Freeze a source, inspect and approve its task plan, then read results |
| Data pools `/data-pools` | Review qualified candidates, repair items and evidence HOLD against a completed task |
| Models and API `/models` | Configure an explicitly chosen Agent provider or optional visual runtime |
| CAPA `/capa` | Review a remediation work order, approval and independent Child recheck |

For individual files use the image import control; for datasets use the supported COCO, YOLO, VOC or LabelMe import path. Selected bytes are streamed to the loopback API, persisted in the local project, and assigned a server-recomputed SHA-256 identity. This is different from reading a file in a static browser-only example and from transmitting pixels to an external provider.

Saving a box does not certify the label. Mark sample purposes, review requirements and any normal empty-box declarations explicitly before freezing. Product defects and bad data are different concepts: a clear, correctly labeled defective product can be useful training data.

After a repair, create a new source version/task/Gate and bind a new review version in the same data pool to that task. Do not mark the old snapshot repaired through a note. See [Complete workflow](PRIVATE_AGENT_PLATFORM_WORKFLOW.md).

## Model configuration and optional training

The model center separates Agent language-model providers from visual detector weights and training environments.

- Provider profiles are workspace-scoped. Explicitly choose the actual existing model and test its connection. Opening a page does not authorize an external call.
- Keys are accepted only by the local service and stored server-side; never put them in `VITE_*` variables, public logs or repository files.
- For vision training, register a trusted external interpreter and verify its actual capabilities. No weight download or dependency installation occurs automatically.
- A frozen detection dataset must have reviewed annotations, explicit classes/groups and isolated train/val/test membership. The data-pool bridge additionally requires current all-qualified review and complete Gate PASS.
- Explicitly authorize the training budget and, when applicable, trusted weight loading. A `.pt` hash is not a safety guarantee; review its origin and loading risk.
- Current training is bounded CPU detect with at most 64 samples. External Ultralytics AGPL-3.0 / Enterprise obligations still apply.
- Review actual validation feedback and manually select or reject the candidate. Next-round feedback references require new, reviewed training data; do not copy validation/test samples into training.

Training success means a candidate was produced, not that accuracy improved. The current small synthetic two-round engineering example has mAP 0 in both rounds. See [Vision API](VISION_MODEL_API_CONTRACT.md) and [Current delivery](PLATFORM_DELIVERY_20260913.md).

## Guided synthetic case

```powershell
.\run_demo.ps1 -Install
```

This entry prepares an isolated synthetic project and opens its Review deep link. Use it as an isolated workflow exercise, not as customer evidence or permission to bypass authentication on your existing account database. It never grants production authority or converts an unresolved Child into production PASS.

A public replay build is explicitly `PUBLIC_SYNTHETIC_REPLAY`. It may read a user-selected image within the browser, but does not upload that image to a backend, save a server project, log into the local account API or start model training. This document does not assert a new hosted deployment; check the actual [repository](https://github.com/dukeandBaron/visiondata-gate) for published artifacts.

## Use authorized local directories

Server-side directory access is disabled until the operator configures a narrow allowlist in the ignored `.env.local` file. Example only:

```dotenv
VISIONDATA_LOCAL_SOURCE_ALLOW_ROOTS=D:\authorized-data\vision
```

Replace it with a directory you actually own and may use. Do not allowlist a drive root, user profile or unrelated shared directory. Registration still requires an explicit purpose, rights basis, read-only confirmation and `raw_redistribution_allowed=false`. Private local paths are input, not public evidence.

See [API reference](api_reference.md) for source and task lifecycle details.

## Recovery and safe limits

- Local API LIVE means the local service is connected, not a factory endpoint.
- A failed refresh turns an old verified result stale/HOLD; it must not keep an unqualified PASS.
- An unknown write outcome is reconciled with an explicit GET and the original operation identifier. Do not repeatedly press a write action or automatically restart training.
- CANN/Ascend job preparation remains `PREPARED_NOT_SUBMITTED`, with no scheduler/NPU execution claim.
- No PLC/MES/camera writes or production-release permission are granted.

## Verify this checkout

```powershell
uv run ruff check .
uv run ruff format --check .
uv run python tools/check_markdown_links.py --root .
uv run python tools/run_public_test_suite.py

cd web
npm run check
```

These checks target the shipped source and public contracts. Inspect the result for your exact checkout; a command listed here is not evidence that it passed. They do not replace package extraction, installed GUI, clean-machine, performance or customer acceptance tests.

## More detail

- [Current platform delivery](PLATFORM_DELIVERY_20260913.md)
- [Architecture](architecture.md)
- [Identity contract](IDENTITY_API_CONTRACT.md)
- [Data-pool contract](DATA_POOL_API_CONTRACT.md)
- [Audit envelope](audit_envelope.md)
- [Compliance and data boundaries](compliance.md)
- [Claim scope](CLAIM_SCOPE.md)
- [Benchmarks](../benchmarks/README.md)
