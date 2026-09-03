# Benchmarks

This directory contains final, portable benchmark evidence. Development diaries, release checklists, presentation scripts, and private-data artifacts are intentionally excluded.

Each evidence track has its own input, denominator, and claim boundary. Results must not be merged into one accuracy number.

## Published evidence

| Track | Denominator | Observed result | Supported claim |
|---|---:|---|---|
| DynamicBench-v3 | 8 synthetic fixtures × 2 strategies | Correct terminal state `8/8` dynamic vs `4/8` fixed; unsafe release `0/8` for both; tool calls `14 vs 24`; recoverable tool faults `2/2 vs 0/2` | Bounded re-planning handles the frozen conflict/failure protocol with fewer calls |
| VisA public governance proxy | 600 source-bound episodes | Dynamic and bounded fixed retry both `525/600`; unsafe release `0`; dynamic avoids 150 non-retryable retries | Contract-aware recovery reduces known-useless retries under the programmatic protocol |

DynamicBench's four fixed-baseline errors are conservative HOLD outcomes caused by missing evidence, not unsafe releases. The VisA proxy does not show higher dynamic accuracy; it shows equal terminal quality with less retry waste in the persistent-fault group.

## Files

- [`dynamicbench-v3-report.json`](dynamicbench-v3-report.json) — full sealed fixture, record, metric, and digest set.
- [`visa-public-proxy-summary.json`](visa-public-proxy-summary.json) — compact source-bound summary; raw VisA images are not redistributed.

## Reproduce DynamicBench-v3

```powershell
uv run python tools/run_dynamic_benchmark_v3.py output/dynamicbench-v3-report.json
uv run pytest -q tests/test_dynamic_benchmark_v3.py
```

Compare the generated report with the published report by verifying the embedded RFC 8785 JCS, domain-separated record, metric, comparison, and sealed-report digests. Output belongs under the ignored `output/` directory.

## Boundaries

These reports do not establish defect-detection accuracy, real-factory prevalence, customer acceptance, a production SLO, or ROI. External model call count in DynamicBench-v3 is zero. See [Compliance and Data Boundaries](../docs/compliance.md).
