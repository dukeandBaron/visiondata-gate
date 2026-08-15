#!/usr/bin/env python3
"""Build and immediately audit a deterministic VisionData Gate submission ZIP."""

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
    PackageSecurityError,
    audit_submission_zip,
    build_deterministic_zip,
)
from visiondata_gate.release import (  # noqa: E402
    DEFAULT_RELEASE_ID,
    ReleaseValidationError,
    load_submission_release,
)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Build a fixed-order, fixed-metadata VisionData Gate submission-candidate ZIP."
        )
    )
    parser.add_argument(
        "--source",
        type=Path,
        default=PROJECT_ROOT,
        help="source directory (default: project root)",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=(
            PROJECT_ROOT
            / "deliverables"
            / "VisionData_Gate_GOAI_BoundlessAgents_RC2_20260816.zip"
        ),
        help="destination ZIP",
    )
    parser.add_argument(
        "--required",
        action="append",
        default=None,
        metavar="POSIX_PATH",
        help="required path after clean extraction; repeat to override defaults",
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="replace an existing destination ZIP",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    required = (
        tuple(args.required) if args.required else DEFAULT_SUBMISSION_REQUIRED_PATHS
    )
    try:
        load_submission_release(
            PROJECT_ROOT / "evidence" / "submission" / DEFAULT_RELEASE_ID
        )
        build = build_deterministic_zip(
            args.source,
            args.output,
            overwrite=args.force,
        )
        audit = audit_submission_zip(args.output, required_paths=required)
    except (OSError, ValueError, PackageSecurityError, ReleaseValidationError) as exc:
        payload = {
            "ok": False,
            "error_type": type(exc).__name__,
            "error": str(exc),
        }
        sys.stdout.write(canonical_json_text(payload))
        return 2

    payload = {"ok": audit.ok, "build": build.to_dict(), "audit": audit.to_dict()}
    sys.stdout.write(canonical_json_text(payload))
    return 0 if audit.ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
