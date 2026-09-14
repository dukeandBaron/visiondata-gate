# Isolated quality tools

This virtual uv project locks development/security tools independently from the
application's `uv.lock`. It is not a PyPI package and does not grant permission to
upgrade application dependencies during a release freeze.

From the repository root:

```text
uv sync --project quality --locked
uv run --project quality --no-sync pyright --project quality/pyright-gate.json
uv run --project quality --no-sync pyright --project quality/pyright-debt.json
```

The blocking type profile checks five declared modules: two strict and three
basic. The separate eight-module debt profile currently reports errors; it is
not a hidden all-project PASS. Python 3.13 CI explicitly overrides the checker
version. Neither profile suppresses an entire diagnostic category.

`requirements.txt` is a hash-bearing export of this lock for `uv run --no-sync
--with-requirements quality/requirements.txt ...` overlays on the already locked
application environment. This does not synchronize or mutate the running
application `.venv`. Regenerate it only from the reviewed quality lock:

```text
uv export --project quality --locked --no-emit-project --format requirements-txt --output-file quality/requirements.txt
```

Coverage uses a frozen, public-safe test slice and per-file exact line/branch
fractions. The verifier requires the actual JUnit case identities, successful
tests, no skips, unchanged module scope, and no increased exclusions. This is a
non-regression floor, not 95% coverage or adequate coverage of all CAPA/release
execution. The wider release coverage baseline is local-only because its tests
depend on artifacts excluded from the public repository.

Security scans remain fail-closed. Bandit `1.9.4` scans all Python under `src`,
`desktop`, and `tools`, writes the complete JSON report, and does not use
`--exit-zero`, a global rule skip, or `continue-on-error`. The reviewed baseline
at `quality/bandit-baseline.json` contains only the 226 existing Low findings;
its normalized findings list is SHA-256 bound. The comparison gate normalizes
Windows and POSIX path separators, permits resolved findings to disappear, and
rejects every new Low finding plus every current Medium or High finding.

Reproduce the gate from the repository root:

```text
uv sync --project quality --locked --python 3.12
uv run --project quality --no-sync python -m bandit -r src desktop tools -f json -o output/security/bandit.json
uv run --project quality --no-sync python tools/check_bandit_baseline.py check --report output/security/bandit.json --baseline quality/bandit-baseline.json --bandit-version 1.9.4
```

Bandit returns `1` while reviewed Low findings remain; CI preserves the full
report and delegates the final pass/fail decision to the baseline comparison.
Scanner execution errors (`>1`), malformed reports, baseline drift, tool-version
drift, and new findings remain blocking. A baseline change requires explicit
review and regeneration with the `freeze` subcommand; it is never updated by CI.

Known-vulnerability lookup sends public locked package identifiers, not source,
images, private registry URLs, or credentials. A registry or scanner failure is
not an all-clear.

Hosted workflow execution, CodeQL results, pre-commit installation in a user's
checkout, package publication and production approval remain separate actions.

This private repository currently preserves CodeQL SARIF as a workflow artifact
with `upload: false`; code-scanning publication is unavailable until the
repository feature is enabled. A successful CodeQL job therefore means analysis
and artifact retention completed, not that findings were published to GitHub's
Security tab or independently triaged.

Dependabot currently reports `GHSA-wrw7-89jp-8q8g` against `glib 0.18.5` in
`web/src-tauri/Cargo.lock`. `cargo tree --target all -i glib@0.18.5` traces it to
Tauri 2.11.5's Linux GTK/WebKit stack; the Windows target does not compile that
dependency. The patched `glib 0.20` line is not compatible with the current GTK
0.18 graph, so the alert remains open pending an upstream Tauri migration. It
must not be dismissed or described as remediated by a lockfile-only edit.
