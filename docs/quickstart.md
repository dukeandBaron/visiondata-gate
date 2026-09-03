# Quickstart

VisionData Gate can run in two deliberately separate modes:

- **Local workbench** — FastAPI + React, writable local project state, operator-gated actions.
- **Public replay** — static, read-only synthetic evidence with no backend, account, API key, or customer data.

The same evidence contracts are used in both modes; only the authority and data source change.

## Requirements

- Windows 10/11
- Python 3.12
- [uv](https://docs.astral.sh/uv/)
- Node.js 22 or newer

The React source is portable to macOS and Linux. Prebuilt, signed desktop packages are not currently distributed.

## Install

```powershell
git clone https://github.com/dukeandBaron/visiondata-gate-public.git
cd visiondata-gate-public
.\setup_env.ps1
```

The setup command installs the lockfile-pinned Python and Web dependencies in the project directory.

## Start the workbench

```powershell
.\run_workbench.ps1 -Install
```

The launcher creates an ephemeral local session and starts both services on loopback addresses:

| Surface | Default address |
|---|---|
| Operator Workbench | `http://127.0.0.1:4173/workspace` |
| API health | `http://127.0.0.1:8787/v1/health` |
| OpenAPI | `http://127.0.0.1:8787/docs` |

For hot reload:

```powershell
.\run_workbench.ps1 -Mode Dev -Install
```

## Run the guided synthetic case

```powershell
.\run_demo.ps1 -Install
```

This command prepares an isolated synthetic project, verifies its manifest, and opens the exact Review deep link. It never grants production authority and never converts an unresolved Child Run into a production `PASS`.

The hosted [Live Demo](https://dukeandbaron.github.io/visiondata-gate-public/) is a static `PUBLIC_SYNTHETIC_REPLAY`. It does not call the local API or accept writes.

## Use authorized local data

Local directories are disabled until the operator configures a narrow server-side allowlist in the ignored `.env.local` file:

```dotenv
VISIONDATA_LOCAL_SOURCE_ALLOW_ROOTS=D:\authorized-data\vision
```

Do not allowlist a drive root, user profile, or unrelated shared directory. Registration still requires an explicit purpose, rights basis, read-only confirmation, and `raw_redistribution_allowed=false`. Paths are accepted as local input but omitted from public evidence.

See [API reference](api_reference.md) for the data-source and task lifecycle.

## Bring your own planner

Provider Profiles are workspace-scoped and optional. Keys are accepted only by the loopback service, stored server-side, and never returned by the API or compiled into the browser bundle. Keep the runtime in `off` or `shadow` mode until the provider probe and policy review succeed.

## Verify the checkout

```powershell
uv run ruff check .
uv run ruff format --check .
uv run python tools/check_markdown_links.py --root .
uv run python tools/run_public_test_suite.py

cd web
npm run check
```

The public test suite validates contracts shipped in the mirror. It is not a customer acceptance test or a production qualification.

## Next steps

- [Architecture](architecture.md)
- [API reference](api_reference.md)
- [Audit envelope](audit_envelope.md)
- [Compliance and data boundaries](compliance.md)
- [Benchmarks](../benchmarks/README.md)
