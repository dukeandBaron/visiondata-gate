#!/usr/bin/env python3
"""Export and verify the VisionData Gate AgentTeams v1.2.2 bridge artifacts."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
SRC_ROOT = PROJECT_ROOT / "src"
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))

from visiondata_gate.agentteams_contract import build_agentteams_contract  # noqa: E402
from visiondata_gate.agentteams_v122 import (  # noqa: E402
    build_agentteams_conformance_receipt,
    build_agentteams_resources_yaml,
    build_skill_distribution_plan,
    validate_runtime_receipt,
)
from visiondata_gate.evidence import (  # noqa: E402
    canonical_json_bytes,
    sha256_file,
)
from visiondata_gate.runtime_models import ScenarioProfile  # noqa: E402


def parser() -> argparse.ArgumentParser:
    root = argparse.ArgumentParser(description=__doc__)
    commands = root.add_subparsers(dest="command", required=True)
    export = commands.add_parser("export", help="write official v1.2.2 resources")
    export.add_argument("--output", type=Path, required=True)
    export.add_argument("--model", default="qwen3.5-plus")
    export.add_argument("--runtime", default="qwenpaw")
    validate = commands.add_parser(
        "validate-receipt", help="validate a hash-bound real runtime receipt"
    )
    validate.add_argument("--receipt", type=Path, required=True)
    validate.add_argument("--output", type=Path)
    return root


def main(argv: list[str] | None = None) -> int:
    args = parser().parse_args(argv)
    if args.command == "export":
        output = args.output.resolve()
        output.mkdir(parents=True, exist_ok=True)
        resources_path = output / "agentteams_v122_resources.yaml"
        skill_plan_path = output / "agentteams_v122_skill_distribution.json"
        conformance_path = output / "agentteams_v122_conformance.json"
        resources_path.write_text(
            build_agentteams_resources_yaml(model=args.model, runtime=args.runtime),
            encoding="utf-8",
        )
        skill_plan = build_skill_distribution_plan()
        skill_plan_path.write_bytes(canonical_json_bytes(skill_plan))
        snapshot = build_agentteams_contract(
            ScenarioProfile.INDUSTRIAL,
            allowed_tools=[
                "image_quality",
                "duplicate_leakage",
                "annotation_integrity",
                "coverage_matrix",
                "governance_audit",
            ],
            include_optional=True,
            run_id="deployment-plan",
        )
        receipt = build_agentteams_conformance_receipt(
            snapshot,
            resources_sha256=sha256_file(resources_path),
            skill_plan=skill_plan,
        )
        conformance_path.write_bytes(canonical_json_bytes(receipt))
        payload = {
            "status": receipt["overall_status"],
            "connection_status": receipt["connection_status"],
            "resources": str(resources_path),
            "skill_distribution": str(skill_plan_path),
            "conformance": str(conformance_path),
        }
        print(json.dumps(payload, ensure_ascii=False, indent=2))
        return 0 if receipt["static_status"] == "PASS" else 2

    receipt_path = args.receipt.resolve()
    receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
    validation = validate_runtime_receipt(receipt, receipt_path=receipt_path)
    encoded = canonical_json_bytes(validation)
    if args.output:
        args.output.resolve().write_bytes(encoded)
    print(encoded.decode("utf-8"), end="")
    return 0 if validation["status"] == "PASS" else 2


if __name__ == "__main__":
    raise SystemExit(main())
