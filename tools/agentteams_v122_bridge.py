#!/usr/bin/env python3
"""Export legacy resources and operate the gated Hosted AgentTeams bridge."""

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
from visiondata_gate.agentteams_transport import (  # noqa: E402
    HostedProjectSubmission,
    hosted_agentteams_from_environment,
    verify_hosted_agentteams_receipt,
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
    probe_hosted = commands.add_parser(
        "probe-hosted",
        help="collect read-only v1.2.3 Controller/Team/Worker evidence",
    )
    probe_hosted.add_argument("--output", type=Path, required=True)
    submit = commands.add_parser(
        "submit-project",
        help="register a project and send an approved, idempotent Leader ingress",
    )
    submit.add_argument("--output", type=Path, required=True)
    submit.add_argument("--source-run-id", required=True)
    submit.add_argument("--title", required=True)
    submit.add_argument("--goal-file", type=Path, required=True)
    submit.add_argument("--project-id")
    submit.add_argument("--requester")
    submit.add_argument("--approval-id", required=True)
    submit.add_argument("--wait-for-execution", action="store_true")
    validate_hosted = commands.add_parser(
        "validate-hosted-receipt",
        help="offline-verify a Hosted allowlisted-projection receipt bundle",
    )
    validate_hosted.add_argument("--receipt", type=Path, required=True)
    validate_hosted.add_argument("--output", type=Path)
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

    if args.command == "validate-receipt":
        receipt_path = args.receipt.resolve()
        receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
        validation = validate_runtime_receipt(receipt, receipt_path=receipt_path)
        encoded = canonical_json_bytes(validation)
        if args.output:
            with args.output.resolve().open("xb") as handle:
                handle.write(encoded)
        print(encoded.decode("utf-8"), end="")
        return 0 if validation["status"] == "PASS" else 2

    if args.command == "validate-hosted-receipt":
        try:
            validation = verify_hosted_agentteams_receipt(args.receipt.resolve())
            encoded = canonical_json_bytes(validation.model_dump(mode="json"))
            if args.output:
                with args.output.resolve().open("xb") as handle:
                    handle.write(encoded)
        except (KeyError, OSError, TypeError, ValueError, RuntimeError) as error:
            print(
                json.dumps(
                    {
                        "status": "FAIL",
                        "error_type": type(error).__name__,
                        "message": "Hosted receipt validation could not be completed",
                        "secret_exposure_status": "UNKNOWN",
                    },
                    ensure_ascii=False,
                    indent=2,
                )
            )
            return 2
        print(encoded.decode("utf-8"), end="")
        return 0 if validation.status == "PASS" else 2

    try:
        transport = hosted_agentteams_from_environment()
        if transport is None:
            raise PermissionError(
                "VISIONDATA_AGENTTEAMS_MODE is off; no Hosted request was made"
            )
        if args.command == "probe-hosted":
            receipt = transport.collect_runtime_evidence(args.output)
        else:
            goal = args.goal_file.resolve().read_text(encoding="utf-8").strip()
            submission = HostedProjectSubmission(
                source_run_id=args.source_run_id,
                title=args.title,
                goal=goal,
                project_id=args.project_id,
                requester=args.requester,
                wait_for_remote_execution=args.wait_for_execution,
            )
            receipt = transport.submit_project(
                args.output,
                submission,
                approval_id=args.approval_id,
            )
    except (OSError, ValueError, PermissionError, RuntimeError) as error:
        print(
            json.dumps(
                {
                    "status": "FAIL",
                    "error_type": type(error).__name__,
                    "message": str(error),
                    "secret_exposure_status": "UNKNOWN",
                },
                ensure_ascii=False,
                indent=2,
            )
        )
        return 2
    print(
        json.dumps(
            {
                "status": receipt.status,
                "operation_status": receipt.operation_status,
                "project_id": receipt.project_id,
                "controller_connected": receipt.controller_connected,
                "team_ready": receipt.team_ready,
                "remote_task_execution_observed": (
                    receipt.remote_task_execution_observed
                ),
                "matrix_assignment_verified": receipt.matrix_assignment_verified,
                "local_runtime_connection_status": (
                    receipt.local_runtime_connection_status
                ),
                "output": str(args.output.resolve()),
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0 if receipt.status == "PASS" else 2


if __name__ == "__main__":
    raise SystemExit(main())
