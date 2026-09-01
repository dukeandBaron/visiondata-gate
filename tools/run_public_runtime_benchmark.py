from __future__ import annotations

import argparse
from datetime import datetime
import json
from pathlib import Path

from visiondata_gate.public_runtime_benchmark import (
    verify_public_runtime_retry_benchmark_bundle,
    write_public_runtime_retry_benchmark,
)


def _aware_timestamp(value: str) -> datetime:
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise argparse.ArgumentTypeError("--evaluated-at requires an explicit offset")
    return parsed


def main() -> int:
    parser = argparse.ArgumentParser(
        description=("Run or verify the paired VisA public runtime recovery benchmark.")
    )
    parser.add_argument(
        "--verify-only",
        action="store_true",
        help="Verify an existing bundle without executing image tools.",
    )
    parser.add_argument("--dataset-root")
    parser.add_argument("--source-binding", required=True)
    parser.add_argument("--source-index", required=True)
    parser.add_argument("--output-dir", required=True)
    parser.add_argument("--clean-cases", type=int, default=300)
    parser.add_argument("--block-cases", type=int, default=300)
    parser.add_argument("--transient-fraction", type=float, default=0.5)
    parser.add_argument("--non-retryable-fraction", type=float, default=0.0)
    parser.add_argument("--evaluated-at", type=_aware_timestamp)
    parser.add_argument("--overwrite", action="store_true")
    args = parser.parse_args()

    if args.verify_only:
        verification_mode = "VERIFY_ONLY"
        report = verify_public_runtime_retry_benchmark_bundle(
            args.output_dir,
            source_binding_path=args.source_binding,
            source_index_path=args.source_index,
            verify_current_sources=True,
        )
    else:
        if args.dataset_root is None:
            parser.error("--dataset-root is required unless --verify-only is set")
        if args.evaluated_at is None:
            parser.error("--evaluated-at is required unless --verify-only is set")
        verification_mode = "RUN_AND_VERIFY"
        write_public_runtime_retry_benchmark(
            args.output_dir,
            dataset_root=args.dataset_root,
            source_binding_path=args.source_binding,
            source_index_path=args.source_index,
            clean_case_count=args.clean_cases,
            block_case_count=args.block_cases,
            transient_fraction=args.transient_fraction,
            non_retryable_fraction=args.non_retryable_fraction,
            evaluated_at=args.evaluated_at,
            overwrite=args.overwrite,
        )
        # Independent disk reload plus semantic replay; image tools are not re-run.
        report = verify_public_runtime_retry_benchmark_bundle(
            args.output_dir,
            source_binding_path=args.source_binding,
            source_index_path=args.source_index,
            verify_current_sources=True,
        )
    output = Path(args.output_dir).expanduser().resolve(strict=True)
    report_path = output / "public_runtime_retry_benchmark.json"
    implementation_path = output / "implementation_identity_receipt.json"
    summary = report["runtime_summary"]
    print(
        json.dumps(
            {
                "status": report["status"],
                "verification_mode": verification_mode,
                "semantic_replay": "PASS",
                "current_source_identity": "PASS",
                "report": str(report_path),
                "report_sha256": report["report_sha256"],
                "episode_count": summary["episode_count"],
                "fixed_uniform_governance_correct_count": summary[
                    "fixed_uniform_governance_correct_count"
                ],
                "dynamic_governance_correct_count": summary[
                    "dynamic_governance_correct_count"
                ],
                "fixed_uniform_transient_recovery_count": summary[
                    "fixed_uniform_transient_recovery_count"
                ],
                "dynamic_transient_recovery_count": summary[
                    "dynamic_transient_recovery_count"
                ],
                "fixed_uniform_non_retryable_retry_count": summary[
                    "fixed_uniform_non_retryable_retry_count"
                ],
                "dynamic_non_retryable_retry_count": summary[
                    "dynamic_non_retryable_retry_count"
                ],
                "implementation_receipt": str(implementation_path),
                "implementation_receipt_sha256": report[
                    "implementation_receipt_sha256"
                ],
                "unsafe_release_count": summary["unsafe_release_count"],
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
