from __future__ import annotations

import argparse
from pathlib import Path

from visiondata_gate.dynamic_benchmark_v3 import (
    load_dynamic_replanning_benchmark_report,
    write_dynamic_replanning_benchmark_report,
)


def main() -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Run the frozen DynamicBench-v3 fixed-rule versus dynamic-replanning "
            "comparison."
        )
    )
    parser.add_argument("output", type=Path, help="Canonical JSON report path")
    args = parser.parse_args()

    output = write_dynamic_replanning_benchmark_report(args.output)
    report = load_dynamic_replanning_benchmark_report(output)
    fixed = report["metrics"]["fixed_rule_baseline"]
    dynamic = report["metrics"]["dynamic_replanning_contract"]
    print(
        f"status={report['status']} fixtures={len(report['fixture_manifest'])} "
        f"records={len(report['records'])} "
        f"fixed_correct={fixed['correct_terminal_disposition_count']}/8 "
        f"dynamic_correct={dynamic['correct_terminal_disposition_count']}/8 "
        f"unsafe_release={fixed['unsafe_release_count']}+"
        f"{dynamic['unsafe_release_count']} "
        f"sha256={report['sealed_report_sha256']} output={output}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
