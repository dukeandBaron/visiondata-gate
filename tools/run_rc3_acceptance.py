"""Run the fixed local RC3 component acceptance and write a sealed report."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
SRC_ROOT = REPOSITORY_ROOT / "src"
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))


def main() -> int:
    from visiondata_gate.evidence import write_canonical_json
    from visiondata_gate.rc3_acceptance import (
        build_rc3_reference_acceptance,
        verify_rc3_acceptance_report,
    )

    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--output",
        type=Path,
        default=REPOSITORY_ROOT
        / "10_reports"
        / "RC3_CAPABILITY_ACCEPTANCE_20260826.json",
    )
    args = parser.parse_args()
    report = build_rc3_reference_acceptance(REPOSITORY_ROOT)
    verify_rc3_acceptance_report(report)
    output = args.output.expanduser().resolve()
    digest = write_canonical_json(output, report)
    print(
        json.dumps(
            {
                "component_status": report.component_status,
                "submission_status": report.submission_status,
                "hard_gate_failures": report.hard_gate_failures,
                "real_image_data_integration_status": (
                    report.real_image_data_integration_status
                ),
                "real_image_integration_reexecuted_in_this_protocol": (
                    report.real_image_integration_reexecuted_in_this_protocol
                ),
                "live_factory_system_connection_status": (
                    report.live_factory_system_connection_status
                ),
                "report_sha256": report.report_sha256,
                "file_sha256": digest,
                "output": str(output),
            },
            ensure_ascii=False,
            sort_keys=True,
        )
    )
    return 0 if report.component_status == "PASS_COMPONENT_CONTRACTS" else 2


if __name__ == "__main__":
    raise SystemExit(main())
