from __future__ import annotations

import argparse
from pathlib import Path

from visiondata_gate.dynamic_benchmark_v2 import (
    load_worker_selection_benchmark_report,
    write_worker_selection_benchmark_report,
)


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Run the fixed DynamicBench-v2 Worker-selection benchmark."
    )
    parser.add_argument("output", type=Path, help="Canonical JSON report path")
    args = parser.parse_args()

    output = write_worker_selection_benchmark_report(args.output)
    report = load_worker_selection_benchmark_report(output)
    print(
        f"status={report['status']} records={len(report['records'])} "
        f"sha256={report['records_sha256']} output={output}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
