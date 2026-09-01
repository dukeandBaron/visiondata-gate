#!/usr/bin/env python3
"""Build one clean-source RC3 candidate in an isolated output workspace."""

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
    ReleaseEvidenceError,
    build_rc3_candidate,
)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Export the clean committed Git tree, build a deterministic ZIP, "
            "and run the complete clean-extract package audit."
        )
    )
    parser.add_argument("--project-root", type=Path, default=PROJECT_ROOT)
    parser.add_argument("--workspace", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        result = build_rc3_candidate(
            project_root=args.project_root,
            workspace=args.workspace,
            output=args.output,
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
                }
            )
        )
        return 2
    result["ok"] = True
    sys.stdout.write(canonical_json_text(result))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
