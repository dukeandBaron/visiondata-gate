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

Security scans retain their real exit status. The initial complete Bandit scan
has unresolved alerts and remains HOLD; there is no blanket `nosec` or
`--exit-zero`. Known-vulnerability lookup sends public locked package identifiers,
not source, images, private registry URLs or credentials. A registry or scanner
failure is not an all-clear.

Hosted workflow execution, CodeQL results, pre-commit installation in a user's
checkout, package publication and production approval remain separate actions.
