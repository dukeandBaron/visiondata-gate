"""Summarize three sealed VisA YOLO26 public-proxy experiment runs."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys


PROJECT_ROOT = Path(__file__).resolve().parents[1]
SRC_ROOT = PROJECT_ROOT / "src"
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))

from visiondata_gate.model_stability import (  # noqa: E402
    ModelStabilityContractError,
    build_model_stability_summary,
    write_model_stability_artifacts,
)


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Build a fail-closed v4 three-seed stability summary from complete "
            "model, Agent, event, private-result and checkpoint evidence. No "
            "model, torch import or GPU workload is executed."
        )
    )
    parser.add_argument(
        "run_directories",
        nargs=3,
        metavar="RUN_DIR",
        help="run directory containing the complete v4 evidence bundle",
    )
    parser.add_argument(
        "--output",
        required=True,
        help="new or byte-identical output directory for stability artifacts",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        summary = build_model_stability_summary(args.run_directories)
        artifacts = write_model_stability_artifacts(summary, args.output)
    except (ModelStabilityContractError, FileNotFoundError) as exc:
        print(
            json.dumps(
                {
                    "status": "STABILITY_INPUT_REJECTED",
                    "error": str(exc),
                    "production_release_allowed": False,
                },
                ensure_ascii=False,
                sort_keys=True,
            ),
            file=sys.stderr,
        )
        return 2
    print(
        json.dumps(
            {
                "schema_version": summary["schema_version"],
                "status": summary["promotion_gate"]["status"],
                "comparability_status": summary["comparability"]["status"],
                "split_seed": summary["split_seed"],
                "model_seeds": summary["model_seeds"],
                "seeds": summary["seeds"],
                "artifacts": artifacts,
                "production_release_allowed": False,
            },
            ensure_ascii=False,
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
