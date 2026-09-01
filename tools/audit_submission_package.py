#!/usr/bin/env python3
"""Audit a VisionData Gate ZIP without trusting archive member paths."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
SRC_ROOT = PROJECT_ROOT / "src"
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))

from visiondata_gate.evidence import canonical_json_text  # noqa: E402
from visiondata_gate.package import (  # noqa: E402
    DEFAULT_SUBMISSION_REQUIRED_PATHS,
    audit_submission_zip,
)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Verify paths, credentials, deterministic ZIP metadata, manifest hashes, "
            "and a clean extraction."
        )
    )
    parser.add_argument("zip_path", type=Path, help="submission ZIP to audit")
    parser.add_argument(
        "--required",
        action="append",
        default=None,
        metavar="POSIX_PATH",
        help="required path after clean extraction; repeat to override defaults",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    required = (
        tuple(args.required) if args.required else DEFAULT_SUBMISSION_REQUIRED_PATHS
    )
    result = audit_submission_zip(args.zip_path, required_paths=required)
    sys.stdout.write(canonical_json_text(result.to_dict()))
    return 0 if result.ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
