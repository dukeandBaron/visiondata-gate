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

Changes to the public surface of the canonical repository must also pass:

The commands above are a portable core slice, not the full authority test suite.
The authority's release tests require their matching private/frozen artifacts;
do not claim a public checkout reproduced them. Run additional tests for the
specific feature changed and the public-safe quality workflow.

```powershell
python tools\check_public_repository.py --history
python tools\check_public_pages.py
```

The static site exposes `PUBLIC_SYNTHETIC_REPLAY`; a source checkout can run the local writable application with its own account and workspace controls. A successful static build is not customer acceptance, production deployment, or official competition evaluation. Source licensing and repository visibility are separate; do not publish private data or unreviewed history through a contribution.

## Reusable contributions

Start with the [core map](src/visiondata_gate/README.md), [Skill catalogue](skills/README.md), [Schema catalogue](schemas/README.md) and [executable example](examples/reuse/README.md). A Skill/contract contribution should include a minimal synthetic input, expected output, exact version, failure case and verification method. A Markdown Skill alone is not an installed plugin or an authorization boundary.

Document compatibility and migration using [VERSIONING](docs/VERSIONING.md). New optional fields also need consumer tests when strict field checking is used. Preserve applicable upstream notices and describe modifications according to [LICENSING](docs/LICENSING.md); this project does not add a CLA, mandatory DCO or new license restriction in this change.

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

## Reproduction and open-source evidence

Use the [open-source readiness map](docs/OPEN_SOURCE_READINESS.md) to distinguish
public source, documented reusable contracts, actual execution, publication, and
independent third-party reproduction. The official 7+8 criteria are not a score
awarded by this repository; Stars, Forks and download counters do not establish
successful adoption.

Submit results with the [reproduction issue template](.github/ISSUE_TEMPLATE/reproduction.md).
Include the exact commit/tree, environment and lockfile, commands actually run,
exit status, public output hashes, failures and unrun steps. Declare whether you
are a maintainer, a teammate or an independent third-party executor, and whether
the maintainer operated any steps for you. Do not create or solicit fabricated
adoption reports; an honest partial or failed run is useful evidence. A template
or maintainer rerun is not an external clean-clone receipt.

Reusable changes should include one runnable synthetic input/output example, a
failure case, compatibility or migration notes, and applicable third-party
license/distribution details. Keep private data and unauthorized weights outside
public materials. Never bypass authentication, human authority or the history
privacy gate to make a reproduction or deployment appear successful.

For changes to these documents and templates, run the bounded checks below and
record any additional feature tests separately:

```text
uv run --no-sync python -m pytest tests/test_open_source_readiness.py tests/test_adoption_docs.py tests/test_public_api_surface.py tests/test_reuse_metadata_example.py -q
```
