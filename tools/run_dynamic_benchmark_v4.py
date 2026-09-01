#!/usr/bin/env python3
"""Execute and seal DynamicBench-v4 through ProductService/Incident v6."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import sys
import tempfile


PROJECT_ROOT = Path(__file__).resolve().parents[1]
SRC_ROOT = PROJECT_ROOT / "src"
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))

from visiondata_gate.benchmarks.dynamic_benchmark_v4 import (  # noqa: E402
    load_dynamic_benchmark_v4_report,
    write_dynamic_benchmark_v4_report,
)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--output",
        type=Path,
        default=(
            PROJECT_ROOT
            / "10_reports"
            / "DYNAMICBENCH_V4_PRODUCT_RUNTIME_20260829.json"
        ),
    )
    parser.add_argument(
        "--v3-report",
        type=Path,
        default=(
            PROJECT_ROOT / "10_reports" / "DYNAMICBENCH_V3_REPLANNING_20260829.json"
        ),
    )
    parser.add_argument(
        "--scratch-root",
        type=Path,
        default=None,
        help="empty directory used for ProductService state; omitted means temporary",
    )
    parser.add_argument("--force", action="store_true")
    return parser


def _execute(args: argparse.Namespace, scratch: Path) -> dict[str, object]:
    output = write_dynamic_benchmark_v4_report(
        args.output,
        scratch_root=scratch,
        v3_report_path=args.v3_report,
        overwrite=args.force,
    )
    report = load_dynamic_benchmark_v4_report(output)
    return {
        "ok": True,
        "status": report["status"],
        "benchmark_id": report["benchmark_id"],
        "output": str(output),
        "file_sha256": hashlib.sha256(output.read_bytes()).hexdigest(),
        "sealed_report_sha256": report["sealed_report_sha256"],
        "metrics": report["metrics"],
        "claim_boundary": report["claim_boundary"],
    }


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        if args.scratch_root is not None:
            result = _execute(args, args.scratch_root)
        else:
            with tempfile.TemporaryDirectory(prefix="visiondata-gate-v4-") as temporary:
                result = _execute(args, Path(temporary))
    except (OSError, RuntimeError, ValueError) as error:
        result = {
            "ok": False,
            "status": "FAIL",
            "error_type": type(error).__name__,
            "error": str(error),
        }
        sys.stdout.write(json.dumps(result, ensure_ascii=False, sort_keys=True) + "\n")
        return 2
    sys.stdout.write(json.dumps(result, ensure_ascii=False, sort_keys=True) + "\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
