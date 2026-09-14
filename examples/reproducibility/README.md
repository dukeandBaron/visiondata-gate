# Public reproducibility artifacts

This directory contains public-safe, deterministic JSON evidence only. It contains
no Omni source bytes, customer data, credentials, absolute source paths, or raw
prompt-injection strings.

- `DYNAMICBENCH_V3_REPRO_SUBSET.json` is the frozen `balanced-smoke-a-v1`
  four-fixture/eight-record projection. Regenerate or verify it with
  `tools/run_dynamic_benchmark_v3_subset.py`.
- `PROMPT_INJECTION_V2_FIXED_SET.json` is the v2 fixed attack/benign evaluation
  receipt. Regenerate it with `visiondata-gate prompt-injection-eval`.

Neither artifact is an external benchmark, customer validation, production
telemetry, trusted timestamp, digital signature, or production release.

