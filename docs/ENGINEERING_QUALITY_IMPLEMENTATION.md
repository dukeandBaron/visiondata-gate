# Implemented engineering quality gates

This is the implemented follow-up to the original authority baseline in
`QUALITY_GATES.md`. It keeps application dependencies separate from the QA
toolchain, measures rather than invents coverage, and distinguishes configured
GitHub jobs from locally executed checks. Snapshot date: 2026-09-12.

## What changed

| Area | Executable implementation | Current boundary |
| --- | --- | --- |
| Python type checks | `quality/pyright-gate.json`: 2 strict + 3 basic modules, zero diagnostics locally | The separate 8-module debt profile has 58 errors; not full-tree strict PASS |
| Platform checks | Ubuntu/Windows × Python 3.12/3.13, selected interpreter asserted in authority CI | Hosted jobs have not been run for this working-tree change |
| Coverage | Fixed public-compatible 48-case lane, coverage.py branch JSON/XML and exact JUnit identity verification | Four-module non-regression floor, not 95% or full CAPA/release coverage |
| Dependency vulnerabilities | pip-audit over all 63 public registry name/version pairs in application lock | No known findings at measurement time; excludes source, Cargo/npm and unknown future CVEs |
| Python static security | Bandit independent blocking job with full report retained | Final local scan: 217 alerts, 0 HIGH / 11 MEDIUM / 206 LOW; `BANDIT_TRIAGE_HOLD` |
| Semantic security | SHA-pinned CodeQL Python + JavaScript/TypeScript workflow | Configured, not locally/hosted executed; no Java/Rust coverage claim |
| Dependency updates | Dependabot for app uv, QA uv, npm, Cargo and GitHub Actions | Update PRs, no automatic merge or release |
| Contributor checks | Local pre-commit hooks reuse separately locked Ruff; no automatic rewrite | Configuration validated; hooks were not installed into the user's checkout |

Ruff's existing default rules are now explicit in root `pyproject.toml`. The
suggested wider rule set produced substantial existing debt; mass formatting,
Enum migration and blanket ignores were not used to manufacture a clean tree.

## Locked tool isolation

The independent virtual project in `quality/` pins Pyright 1.1.414, pytest 9.1.1,
pytest-cov 7.1.0, coverage 7.16.0, pip-audit 2.10.1, Bandit 1.9.4, Ruff 0.16.7 and
pre-commit 4.6.2. Its `uv.lock` pins transitive dependencies, and its hash-bearing
requirements export is checked against the lock in CI. No application package
version or application `uv.lock` was changed for these tools.

Prepare the existing application environment as described in
[Quickstart](CROSS_PLATFORM_QUICKSTART.md), then run:

```text
uv lock --check
uv lock --project quality --check
uv run --no-sync --with-requirements quality/requirements.txt pyright --project quality/pyright-gate.json
uv run --no-sync --with-requirements quality/requirements.txt pre-commit validate-config .pre-commit-config.yaml
```

The overlay command does not synchronize the running application `.venv`.
Installation of contributor Git hooks is an explicit user action:

```text
uv run --no-sync --with-requirements quality/requirements.txt pre-commit install
```

## Coverage: an honest starting floor

The `quality/coverage-profile.json` profile binds exact testcase identities and
these measured integer fractions, not rounded display percentages:

| Module | Covered lines / total | Covered branches / total |
| --- | ---: | ---: |
| policy | 332 / 379 | 108 / 156 |
| evidence_state | 121 / 132 | 27 / 36 |
| audit_envelope | 286 / 413 | 57 / 142 |
| capa | 337 / 782 | 9 / 192 |

The CAPA tests in this slice cover two pure Child-closure contracts, not all
derived-version execution. Its low branch floor is a visible testing gap, not
an adequacy certificate. Release builder tests depend on non-public artifacts
and are not falsely included in the public-compatible gate. Broader authority
coverage was measured separately; no whole-repository 95% claim is made.

The quality workflow contains the complete 48-case command. The result verifier
requires every declared file, nonnegative integer counts, exact fractions that
do not decrease, no shrinking denominators, no new exclusions, successful JUnit
suites with zero failures/errors/skips, and the exact testcase identity set.
Windows path separators normalize to the same relative module names; duplicate
path aliases are rejected. Malformed, oversized, DTD-bearing or incomplete
reports fail closed. A passing count alone is insufficient.

After generating reports using the workflow's command:

```text
uv run --no-sync python tools/check_engineering_quality.py coverage --coverage output/quality/coverage.json --junit output/quality/pytest.xml --profile quality/coverage-profile.json
```

## Visible type and security debt

The broader basic probe remains runnable and intentionally returns nonzero:

```text
uv run --no-sync --with-requirements quality/requirements.txt pyright --project quality/pyright-debt.json
```

Initial diagnostic distribution: release 45, policy 7, CAPA 4, evidence_state 1,
evidence_state_contracts 1. Contracts, product_models and audit_envelope were
basic-clean. Backend identity and provider endpoint configuration were strict-clean.
These are checker diagnostics, not 58 proven runtime defects. Accurate narrowing
and generic return types require a separately verified source patch; whole error
categories are not suppressed.

Bandit alerts likewise require per-finding triage. Fixed parameterized SQL can
trigger syntactic warnings; XML input guards and URL allowlists need actual
context review. New quality XML parsing has byte/encoding/DTD and structure tests,
but a raw scanner warning is retained rather than globally ignored. The workflow
keeps Bandit's nonzero status and uploads evidence with `if: always()`.

The dependency exporter emits only pinned public package names/versions; it
refuses unsupported/private registry sources and refuses to overwrite output.
The security workflow audits these versions with resolution disabled. Scanner
network failures, missing reports and unknown dependencies are not all-clear.

## No publication or product-safety promotion

Only the listed QA configuration files are added to the public export allowlist;
tool environments, caches and local diagnostic directories remain excluded.
Before publication, review the public candidate and run its actual CI. The
current authority tree still contains unrelated user/team changes. Nothing here
signs a release, uploads to PyPI, updates an installed GUI, closes a data-quality
issue, runs a production model or changes human-only authority.
