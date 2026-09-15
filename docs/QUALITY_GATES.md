# Quality gates and validation scope

The public CI workflow is `quality.yml`: Ubuntu and Windows × Python 3.12 and
3.13, an asserted interpreter version, locked dependencies, default-rule lint,
selected type checks, and a fixed branch-coverage slice. It is **not** the
historical full-release freeze regression. A successful test count 不是覆盖率.

The coverage command uses `--cov-branch`; exact tests and per-file denominators
are checked by `tools/check_engineering_quality.py`. See
[implementation and measured floors](ENGINEERING_QUALITY_IMPLEMENTATION.md).

Independent contributor hooks run Ruff lint and formatting checks without
rewriting files. Whole-tree formatting still has existing debt (67 files in the
2026-09-16 local check); it is not silently ignored or described as passing.
Full-tree strict typing, clean-machine desktop installation, industrial
false-release/false-block rates and external user adoption require separate
evidence. Where missing, use `NOT_MEASURED` / `HOLD_UNMEASURED_GATES`.

Archived submission-package tests require their exact private release inputs.
Running the public checkout alone cannot certify an old package. These tests
remain in the source and failures remain visible; public CI names its selected
scope instead of skipping failures and calling the result a full-suite PASS.
