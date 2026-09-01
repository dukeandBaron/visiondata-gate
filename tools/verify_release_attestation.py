#!/usr/bin/env python3
"""Verify a strict, unsigned RC3 release attestation."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
SRC_ROOT = PROJECT_ROOT / "src"
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))

from visiondata_gate.evidence import canonical_json_text  # noqa: E402
from visiondata_gate.release_attestation import (  # noqa: E402
    ReleaseAttestationError,
    verify_release_attestation,
)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Fail closed unless the JCS Statement digest, clean Git source, "
            "candidate ZIPs, required materials, and receipts all match."
        )
    )
    parser.add_argument("--project-root", type=Path, default=PROJECT_ROOT)
    parser.add_argument("--attestation", type=Path, required=True)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    root = args.project_root.resolve(strict=False)
    attestation = (
        args.attestation if args.attestation.is_absolute() else root / args.attestation
    )
    try:
        result = verify_release_attestation(
            project_root=root,
            attestation_path=attestation,
        )
    except (OSError, ReleaseAttestationError, ValueError) as exc:
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

    payload = result.model_dump(mode="json")
    payload["ok"] = True
    sys.stdout.write(canonical_json_text(payload))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
