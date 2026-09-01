# Contributing to VisionData Gate

VisionData Gate welcomes fixes and reusable industrial-data governance improvements. Contributions must preserve the project's evidence-first and fail-closed boundaries.

## Before opening a pull request

1. Do not include customer data, factory images, masks, device frames, access tokens, API keys, local databases, absolute machine paths, or personal identifiers.
2. Use synthetic fixtures under `sample_data/` or add a documented, redistributable public fixture.
3. Keep AI recommendations advisory. Production release authority and machine write permission must remain human-controlled and disabled by default.
4. Add or update tests for contract, recovery, privacy, and failure behavior.

## Local checks

```powershell
uv sync --frozen
uv run python -m pytest
uv run ruff check .
uv run ruff format --check .

cd web
npm ci
npm run typecheck
npm run build
```

Public-mirror changes must also pass:

```powershell
python tools\check_public_repository.py --history
python tools\check_public_pages.py
```

The public repository exposes only `PUBLIC_SYNTHETIC_REPLAY`. A successful public build is not customer acceptance, production deployment, or official competition evaluation.
