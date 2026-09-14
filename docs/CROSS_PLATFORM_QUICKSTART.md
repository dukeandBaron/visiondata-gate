# Source quickstart without PowerShell

These commands use the checked-out source, not a PyPI release or a native
installer. The primary UI is the [React workbench](INTERFACE_SUPPORT.md).
Python 3.12/3.13 and [uv](https://docs.astral.sh/uv/) are required; the web UI also
requires Node.js 22.12+ and npm. No GPU, external model key or factory data is needed
for the deterministic example.

## 1. Install the locked source environment

From the repository root, in PowerShell, bash or zsh:

```text
uv sync --extra api --extra qa --locked
uv run visiondata-gate --help
```

Use `--locked`, not an unreviewed dependency upgrade. Stop if the lock and project
metadata disagree. The optional Streamlit UI and native packaging toolchain are
not prerequisites for the React source workflow.

## 2. Try the deterministic CLI

Choose an output directory that does not already contain your work:

```text
uv run visiondata-gate demo --output output/quickstart-demo-01 --seed 20260809
```

The demo generates its own synthetic input, checks it, performs supported
demonstration remediation and rechecks the derived result. Inspect the resulting
reports rather than assuming a successful process exit grants production release.
Use a new output name for another run; never point this at customer input folders.

`visiondata-gate serve` is **not** an existing CLI command. Do not substitute
invented commands from a review or disable authentication to launch the API.

## 3. Start the actual browser workbench

```text
npm --prefix web ci
uv run python tools/run_cross_platform_workbench.py --check
uv run python tools/run_cross_platform_workbench.py
```

The launcher uses the existing local API and Vite app, not a new backend. It is
intended to open a browser with a newly created local session; the visible console
URL intentionally omits the session capability. A bare URL copied from the console
is not an authenticated session. See `--help` for ports, data root and headless
checks. Keep the launcher terminal open; stopping it stops only its own services.

The default API/web ports are `8787` / `5173`; choose free alternatives with
`--api-port` and `--web-port`. The default data root is
`output/cross-platform-product`, separate from the established Windows profile.
Use `--product-root` only for the intended local data directory. Per-run runtime
and cache directories are retained; the launcher does not delete user data.

Private images and application records remain in the selected local product root.
The launcher does not install dependencies, read private `.env` credentials,
enable remote model calls or submit CANN jobs. Occupied ports are a refusal, not
permission to kill an existing service. The Vite server is a local developer
server, not an internet deployment.

Windows users can keep using `run_workbench.ps1` / `start_local_workbench.ps1`.
The portable command does not migrate their database, replace their service or
upgrade a previously installed desktop application. Linux/macOS native packaging
and on-device validation remain separate work.

## 4. Verify the source you changed

```text
uv run pytest -q tests/test_cross_platform_workbench.py
npm --prefix web run typecheck
npm --prefix web run build
```

Additional quality gates and their measured scope are documented in the quality
configuration and [contribution guide](../CONTRIBUTING.md). The broader local
development tree, an exported public checkout and a packaged executable may carry
different fixtures; do not substitute one environment's PASS for another.

## Optional: data/model reference learning

If this checkout contains the learning module and demo driver:

```text
uv run python tools/run_learning_demo.py --help
```

This is a bounded local CPU reference workflow. Check the available output-root
and authorization options in its help. It is not a pretrained industrial detector,
and a public checkout missing the module must not be presented as having run it.
