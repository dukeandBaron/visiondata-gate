#!/usr/bin/env python3
"""Build the redacted, cross-hashed GOAI submission release."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
SRC_ROOT = PROJECT_ROOT / "src"
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))

from visiondata_gate.evidence import canonical_json_text  # noqa: E402
from visiondata_gate.release import (  # noqa: E402
    DEFAULT_RELEASE_ID,
    ReleaseValidationError,
    build_submission_release,
)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Validate and stage ArchBench-v2, Omni-180-v1, and Synthetic-v3 "
            "as one public GOAI release."
        )
    )
    parser.add_argument("--benchmark", type=Path, required=True)
    parser.add_argument("--dynamic-plan", type=Path, required=True)
    parser.add_argument("--gate-result", type=Path, required=True)
    parser.add_argument("--omni-receipt", type=Path, required=True)
    parser.add_argument(
        "--synthetic-summary",
        type=Path,
        default=PROJECT_ROOT
        / "07_results"
        / "frozen_demo_20260809"
        / "evidence"
        / "demo_summary.json",
    )
    parser.add_argument("--release-id", default=DEFAULT_RELEASE_ID)
    parser.add_argument("--qa-passed", type=int)
    parser.add_argument("--qa-skipped", type=int)
    parser.add_argument("--qa-warnings", type=int)
    parser.add_argument(
        "--ruff-status", choices=("PASS", "FAIL", "PENDING"), default="PENDING"
    )
    parser.add_argument(
        "--format-status", choices=("PASS", "FAIL", "PENDING"), default="PENDING"
    )
    parser.add_argument(
        "--compileall-status", choices=("PASS", "FAIL", "PENDING"), default="PENDING"
    )
    parser.add_argument("--pptx", type=Path)
    parser.add_argument("--pdf", type=Path)
    parser.add_argument("--video", type=Path)
    parser.add_argument("--force", action="store_true")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    output_dir = PROJECT_ROOT / "evidence" / "submission" / args.release_id
    deliverables = {
        label: path
        for label, path in {
            "roadshow_pptx": args.pptx,
            "roadshow_pdf": args.pdf,
            "demo_video": args.video,
        }.items()
        if path is not None
    }
    try:
        release = build_submission_release(
            project_root=PROJECT_ROOT,
            output_dir=output_dir,
            architecture_benchmark_path=args.benchmark,
            dynamic_plan_path=args.dynamic_plan,
            omni_gate_path=args.gate_result,
            omni_receipt_path=args.omni_receipt,
            synthetic_summary_path=args.synthetic_summary,
            release_id=args.release_id,
            qa_passed=args.qa_passed,
            qa_skipped=args.qa_skipped,
            qa_warnings=args.qa_warnings,
            ruff_status=args.ruff_status,
            format_status=args.format_status,
            compileall_status=args.compileall_status,
            deliverables=deliverables,
            overwrite=args.force,
        )
    except (OSError, ReleaseValidationError, ValueError) as exc:
        sys.stdout.write(
            canonical_json_text(
                {"ok": False, "error_type": type(exc).__name__, "error": str(exc)}
            )
        )
        return 2
    sys.stdout.write(
        canonical_json_text(
            {
                "ok": True,
                "release_id": release.manifest["release_id"],
                "quality_status": release.manifest["quality_gates"]["status"],
                "evidence_namespaces": sorted(release.manifest["evidence_namespaces"]),
                "artifact_count": len(release.manifest["artifacts"]) + 1,
            }
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
