#!/usr/bin/env python3
"""Validate the public release and print a path-free reviewer receipt."""

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
    load_submission_release,
)


def _write_json(payload: dict[str, object]) -> None:
    """Write canonical UTF-8 bytes without inheriting a legacy console codec."""

    sys.stdout.buffer.write(canonical_json_text(payload).encode("utf-8"))


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Validate a VisionData Gate public release."
    )
    parser.add_argument("--release-id", default=DEFAULT_RELEASE_ID)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    release_dir = PROJECT_ROOT / "evidence" / "submission" / args.release_id
    try:
        release = load_submission_release(release_dir)
    except (OSError, ReleaseValidationError, ValueError) as exc:
        _write_json({"ok": False, "error_type": type(exc).__name__, "error": str(exc)})
        return 2
    omni = release.manifest["evidence_namespaces"]["Omni-180-v1"]
    arch = release.manifest["evidence_namespaces"]["ArchBench-v2"]
    scenario = release.scenario_delivery_receipt
    _write_json(
        {
            "ok": True,
            "release_id": release.manifest["release_id"],
            "track": "Boundless Agents / AI+工业制造",
            "architecture_records": arch["record_count"],
            "omni_fixed_denominator": omni["selected_image_count"],
            "dynamic_workers": omni["worker_count"],
            "work_orders": omni["work_order_count"],
            "scenario_status": scenario["status"],
            "proof_ladder": {
                key: value["status"] for key, value in scenario["proof_ladder"].items()
            },
            "agentteams": release.manifest["agentteams"]["connection_status"],
            "quality_status": release.manifest["quality_gates"]["status"],
        }
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
