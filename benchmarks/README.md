# Benchmarks

This directory contains frozen, public-safe synthetic benchmark reports used by
the read-only evaluation-evidence API and the Windows desktop package.

- `DYNAMICBENCH_V3_REPLANNING_20260829.json` compares dynamic evidence recovery
  with a fixed orchestration policy under the same fixtures, tools, and frozen
  fail-closed judge.
- `DYNAMICBENCH_V4_PRODUCT_RUNTIME_20260829.json` verifies that the benchmark
  contract can traverse the production `ProductService` and Incident runtime
  path without widening release authority.

These reports measure orchestration behavior on deterministic synthetic
fixtures. They are not factory accuracy, customer acceptance, production SLO,
or production-release evidence. See
[`docs/DYNAMICBENCH_V3.md`](../docs/DYNAMICBENCH_V3.md) and
[`docs/DYNAMICBENCH_V4.md`](../docs/DYNAMICBENCH_V4.md) for the protocol and
reproduction boundaries.
