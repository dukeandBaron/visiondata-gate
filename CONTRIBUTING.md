# Contributing to VisionData Gate

VisionData Gate welcomes fixes and reusable industrial-data governance improvements. Contributions must preserve the project's evidence-first and fail-closed boundaries.

## Before opening a pull request

1. Do not include customer data, factory images, masks, device frames, access tokens, API keys, local databases, absolute machine paths, or personal identifiers.
2. Use synthetic fixtures under `sample_data/` or add a documented, redistributable public fixture.
3. Keep AI recommendations advisory. Production release authority and machine write permission must remain human-controlled and disabled by default.
4. Add or update tests for contract, recovery, privacy, and failure behavior.

## Local checks

```powershell
uv sync --all-extras --locked
uv run python tools/run_public_test_suite.py
uv run ruff check .
uv run ruff format --check .

cd web
npm ci
npm run typecheck
npm run build
```

After committing a public-mirror change, build a new allowlisted snapshot into
an absent directory outside this checkout. The exporter runs the privacy,
manifest and local-link gates before making the destination visible:

```powershell
uv run python tools\export_public_repository.py `
  --destination ..\visiondata-gate-public-audit
```

The public repository's own GitHub workflows then rescan its complete public
history, run the Python contract/API suite, and build the React Pages artifact.
It exposes only `PUBLIC_SYNTHETIC_REPLAY`. A successful public build is not
customer acceptance, production deployment, or official competition evaluation.

The private release and benchmark tiers bind frozen evidence that is
deliberately not redistributed. Their test source remains visible for audit,
but a public clone must not synthesize missing private receipts to make those
tiers pass.
