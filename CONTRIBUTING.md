# Contributing to VisionData Gate

VisionData Gate welcomes fixes and reusable industrial-data governance improvements. Contributions must preserve the project's evidence-first and fail-closed boundaries.

## Before opening a pull request

1. Do not include customer data, factory images, masks, device frames, access tokens, API keys, local databases, absolute machine paths, or personal identifiers.
2. Use synthetic fixtures under `sample_data/` or add a documented, redistributable public fixture.
3. Keep AI recommendations advisory. Production release authority and machine write permission must remain human-controlled and disabled by default.
4. Add or update tests for contract, recovery, privacy, and failure behavior.

## Local checks

The [React workbench](docs/INTERFACE_SUPPORT.md) is the primary interactive UI.
Use the [portable source quickstart](docs/CROSS_PLATFORM_QUICKSTART.md) without
PowerShell, or keep the existing Windows launchers. API/contract changes must
update their consumers and failure-path tests; do not promise feature parity for
legacy analysis surfaces or change archived benchmark protocols.

```text
uv sync --all-extras --locked
uv run python -m pytest tests/test_policy_agents.py tests/test_evidence_state.py tests/test_audit_envelope.py
uv run ruff check .
uv run ruff format --check .

npm --prefix web ci
npm --prefix web run typecheck
npm --prefix web run build
```

Public-mirror changes must also pass:

The commands above are a portable core slice, not the full authority test suite.
The authority's release tests require their matching private/frozen artifacts;
do not claim a public checkout reproduced them. Run additional tests for the
specific feature changed and the public-safe quality workflow.

```powershell
python tools\check_public_repository.py --history
python tools\check_public_pages.py
```

The public repository exposes only `PUBLIC_SYNTHETIC_REPLAY`. A successful public build is not customer acceptance, production deployment, or official competition evaluation.

Changes intended for release should add an [Unreleased changelog entry](CHANGELOG.md)
and pass the [release preparation checks](docs/RELEASE_PREPARATION.md). Existing
quality baselines are measured scopes, not permission to waive failures or claim
unmeasured 95% coverage. Do not move public import paths or root launch scripts
without a compatibility plan and tests for the old entry points.

The [implemented quality gates](docs/ENGINEERING_QUALITY_IMPLEMENTATION.md) use an
independently locked `quality/` tool environment. Validate contributor hooks with
`uv run --no-sync --with-requirements quality/requirements.txt pre-commit validate-config .pre-commit-config.yaml`.
Installing those hooks is explicit; this change does not install them automatically.
Type-debt and Bandit findings remain visible HOLDs, not silently ignored checks.
