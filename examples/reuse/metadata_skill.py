# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 VisionData Gate contributors
"""Invoke the real industrial Skill SDK using only synthetic counts.

No files, network clients, model weights or production interfaces are supplied
to the Skill. This demonstrates a trusted in-process contract, not an OS sandbox.
"""

from __future__ import annotations

import argparse
import hashlib
import json

from visiondata_gate.industrial_skills import (
    IndustrialEvidenceSpan,
    IndustrialMeasurement,
    IndustrialSkillInvocation,
    IndustrialSkillReceipt,
    IndustrialSourceSnapshot,
    build_default_industrial_skill_registry,
    verify_industrial_skill_receipt,
)


def run_example(
    metadata_count: int = 12, observed_count: int = 14
) -> IndustrialSkillReceipt:
    """Return a verifiable count-comparison receipt, without writing any output."""
    for value in (metadata_count, observed_count):
        if (
            isinstance(value, bool)
            or not isinstance(value, int)
            or not 0 <= value <= 1_000_000
        ):
            raise ValueError(
                "Each synthetic count must be a non-negative integer no greater than 1000000"
            )
    fixture = {
        "scope": "SYNTHETIC_LOCAL_SDK_EXAMPLE",
        "metrics": {
            "metadata_image_count": metadata_count,
            "tree_image_count": observed_count,
        },
    }
    fixture_bytes = json.dumps(fixture, sort_keys=True, separators=(",", ":")).encode(
        "utf-8"
    )
    source = IndustrialSourceSnapshot(
        source_id="synthetic-reuse-counts",
        source_kind="redacted_batch_snapshot",
        source_version="example-1",
        snapshot_sha256=hashlib.sha256(fixture_bytes).hexdigest(),
    )
    measurements = tuple(
        IndustrialMeasurement(
            name=name,
            value=value,
            unit="images",
            measurement_version="1.0.0",
            evidence_span=IndustrialEvidenceSpan(
                source_id=source.source_id,
                source_version=source.source_version,
                snapshot_sha256=source.snapshot_sha256,
                span_kind="metric",
                selector=f"/metrics/{name}",
            ),
        )
        for name, value in fixture["metrics"].items()
    )
    invocation = IndustrialSkillInvocation(
        invocation_id="synthetic-count-audit-1",
        source=source,
        measurements=measurements,
    )
    receipt = build_default_industrial_skill_registry().invoke(
        "visiondata-gate.metadata-count-drift", "1.0.0", invocation
    )
    if not verify_industrial_skill_receipt(receipt):
        raise RuntimeError("The SDK receipt failed verification")
    return receipt


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--metadata-count", type=int, default=12)
    parser.add_argument("--observed-count", type=int, default=14)
    args = parser.parse_args(argv)
    try:
        receipt = run_example(args.metadata_count, args.observed_count)
    except ValueError as error:
        parser.error(str(error))
    if receipt.outcome.status != "OK":
        print(json.dumps({"scope": "SYNTHETIC_LOCAL_SDK_EXAMPLE", "status": "DEFER"}))
        return 1
    decision = receipt.outcome.observations[0].decision
    print(
        json.dumps(
            {
                "scope": "SYNTHETIC_LOCAL_SDK_EXAMPLE",
                "status": receipt.outcome.status,
                "skill_id": receipt.manifest.skill_id,
                "skill_version": receipt.manifest.skill_version,
                "absolute_count_delta": decision.observed_value,
                "is_anomaly": decision.is_anomaly,
                "receipt_verified": True,
                "receipt_sha256": receipt.receipt_sha256,
                "production_release_allowed": False,
            },
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
