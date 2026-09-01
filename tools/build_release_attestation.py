#!/usr/bin/env python3
"""Build a strict, unsigned RC3 release attestation."""

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
    build_release_attestation,
    write_release_attestation,
)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Build an RFC 8785 JCS, domain-separated, in-toto-style release "
            "attestation. The v1 output is deliberately unsigned and never "
            "marks a package submission-eligible."
        )
    )
    parser.add_argument("--project-root", type=Path, default=PROJECT_ROOT)
    parser.add_argument("--release-id", required=True)
    parser.add_argument("--candidate-zip", type=Path, required=True)
    parser.add_argument("--second-build-zip", type=Path, required=True)
    parser.add_argument("--full-test-receipt", type=Path, required=True)
    parser.add_argument("--clean-extract-receipt", type=Path, required=True)
    parser.add_argument("--build-one-receipt", type=Path, required=True)
    parser.add_argument("--build-two-receipt", type=Path, required=True)
    parser.add_argument("--builder-id", required=True)
    parser.add_argument(
        "--toolchain",
        action="append",
        required=True,
        metavar="NAME=VERSION",
        help=(
            "tool version; repeat for git, python, uv, visiondata-gate, and "
            "any additional build tools. Required versions are probed locally."
        ),
    )
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--force", action="store_true")
    return parser


def _parse_toolchain(values: list[str]) -> dict[str, str]:
    result: dict[str, str] = {}
    for value in values:
        name, separator, version = value.partition("=")
        if not separator or not name or not version:
            raise ReleaseAttestationError(
                f"invalid --toolchain value {value!r}; expected NAME=VERSION"
            )
        if name in result:
            raise ReleaseAttestationError(f"duplicate toolchain name: {name}")
        result[name] = version
    return result


def _inside(root: Path, value: Path) -> Path:
    return value if value.is_absolute() else root / value


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    root = args.project_root.resolve(strict=False)
    try:
        attestation = build_release_attestation(
            project_root=root,
            release_id=args.release_id,
            candidate_zip=_inside(root, args.candidate_zip),
            reproducible_zip=_inside(root, args.second_build_zip),
            full_test_receipt=_inside(root, args.full_test_receipt),
            clean_extract_receipt=_inside(root, args.clean_extract_receipt),
            build_one_receipt=_inside(root, args.build_one_receipt),
            build_two_receipt=_inside(root, args.build_two_receipt),
            builder_id=args.builder_id,
            toolchain=_parse_toolchain(args.toolchain),
        )
        output = _inside(root, args.output)
        output_sha256 = write_release_attestation(
            output,
            attestation,
            project_root=root,
            overwrite=args.force,
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
                }
            )
        )
        return 2

    sys.stdout.write(
        canonical_json_text(
            {
                "ok": True,
                "status": "PASS_LOCAL_UNSIGNED_ATTESTATION",
                "output": str(output.resolve()),
                "output_sha256": output_sha256,
                "statement_digest": attestation.statement_digest.value,
                "signature": "NOT_CONFIGURED",
                "trusted_timestamp": "NOT_CONFIGURED",
                "external_anchor": "NOT_CONFIGURED",
                "submission_eligible": False,
                "official_status": "NOT_EVALUATED",
            }
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
