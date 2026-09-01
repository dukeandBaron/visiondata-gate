"""Build one path-redacted CAPA feasibility assessment from sealed local evidence."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

from visiondata_gate.evidence import canonical_json_bytes
from visiondata_gate.product_service import ProductService


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--product-root", required=True)
    parser.add_argument("--actor-user-id", required=True)
    parser.add_argument("--parent-task-id", required=True)
    parser.add_argument("--case-id", required=True)
    parser.add_argument("--output", required=True)
    args = parser.parse_args()

    service = ProductService(args.product_root, recover_interrupted=False)
    try:
        assessment = service.capa_outcome_assessment(
            args.actor_user_id, args.parent_task_id, args.case_id
        )
    finally:
        service.close(wait=True)

    data = canonical_json_bytes(assessment)
    output = Path(args.output).expanduser().resolve(strict=False)
    output.parent.mkdir(parents=True, exist_ok=True)
    try:
        with output.open("xb") as handle:
            handle.write(data)
    except FileExistsError:
        if output.read_bytes() != data:
            raise RuntimeError("immutable assessment output already differs")
    digest = hashlib.sha256(data).hexdigest()
    print(
        json.dumps(
            {
                "status": "PASS",
                "output": str(output),
                "output_sha256": digest,
                "release_feasibility_status": (assessment.release_feasibility_status),
                "observed_release_candidate_found": (
                    assessment.observed_release_candidate_found
                ),
                "minimum_observed_relative_effort_points": (
                    assessment.minimum_observed_relative_effort_points
                ),
            },
            ensure_ascii=False,
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
