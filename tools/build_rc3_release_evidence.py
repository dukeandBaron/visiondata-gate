#!/usr/bin/env python3
"""Run the fail-closed RC3 full-test and dual-build evidence pipeline."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
SRC_ROOT = PROJECT_ROOT / "src"
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))

from visiondata_gate.evidence import canonical_json_text  # noqa: E402
from visiondata_gate.release_evidence import (  # noqa: E402
    DEFAULT_BUILDER_ID,
    ReleaseEvidenceError,
    build_rc3_release_evidence,
)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Require a clean committed tree, run the unfiltered full regression, "
            "bind JUnit SHA-256, produce two isolated deterministic builds, audit "
            "clean extraction, and emit an unsigned local attestation."
        )
    )
    parser.add_argument("--project-root", type=Path, default=PROJECT_ROOT)
    parser.add_argument("--release-id", required=True)
    parser.add_argument(
        "--output-root",
        type=Path,
        required=True,
        help="new, ignored project-local evidence namespace",
    )
    parser.add_argument("--builder-id", default=DEFAULT_BUILDER_ID)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        result = build_rc3_release_evidence(
            project_root=args.project_root,
            release_id=args.release_id,
            output_root=args.output_root,
            builder_id=args.builder_id,
        )
    except (OSError, ValueError, ReleaseEvidenceError) as exc:
        sys.stdout.write(
            canonical_json_text(
                {
                    "ok": False,
                    "status": "FAIL",
                    "error_type": type(exc).__name__,
                    "error": str(exc),
                    "submission_eligible": False,
                    "official_status": "NOT_EVALUATED",
                }
            )
        )
        return 2
    result["ok"] = True
    sys.stdout.write(canonical_json_text(result))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
