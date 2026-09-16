"""Re-evaluate frozen public-model scores; no model, dataset, or Champion writes."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

from visiondata_gate.anomaly_operating_point import (
    OperatingPolicy,
    select_operating_point,
    evaluate_operating_point,
    confusion_metrics,
)
from visiondata_gate.audit_envelope import canonical_jcs_bytes


def audit_run(run: Path, policy: OperatingPolicy) -> dict:
    source = run / "private/worker_result.json"
    raw = source.read_bytes()
    result = json.loads(raw)
    channel = result["checkpoint"]["selected_image_aggregation"]
    records = [
        {
            "source_sample_id": r["source_sample_id"],
            "split_role": r["split_role"],
            "product_label": r["product_label"],
            "image_scores": {channel: r["image_score"]},
        }
        for r in result["per_sample_predictions"]
    ]
    calibration = [r for r in records if r["split_role"] == "calibration"]
    evaluation = [r for r in records if r["split_role"] == "heldout_development"]
    selection = select_operating_point(calibration, policy)
    assessment = evaluate_operating_point(selection, evaluation)
    old_threshold = result["checkpoint"]["image_threshold"]
    candidate = selection["diagnostic_candidate"]
    # Only calibration members are eligible for this diagnostic review queue.
    queue = []
    for row in calibration:
        score = row["image_scores"][channel]
        actual = row["product_label"] == "anomaly"
        predicted = score >= candidate["threshold"]
        if actual != predicted:
            queue.append(
                {
                    "source_sample_id": row["source_sample_id"],
                    "split_role": "calibration",
                    "reason": "MISSED_REFERENCE_ANOMALY"
                    if actual
                    else "FALSE_ALARM_ON_REFERENCE_NORMAL",
                    "next_action": "HUMAN_DIAGNOSIS_REQUIRED",
                    "label_change_authorized": False,
                    "automatic_training_inclusion": False,
                }
            )
    return {
        "model_seed": result["model_seed"],
        "model_pack_sha256": result["checkpoint"]["sha256"],
        "source_predictions_sha256": hashlib.sha256(raw).hexdigest(),
        "baseline": {
            "threshold": old_threshold,
            "metrics": confusion_metrics(evaluation, channel, old_threshold),
        },
        "selection": selection,
        "assessment": assessment,
        "calibration_review_queue": queue,
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run", type=Path, action="append", required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--min-recall", type=float, required=True)
    parser.add_argument("--max-fpr", type=float, required=True)
    args = parser.parse_args()
    if args.output.exists():
        raise ValueError("OUTPUT_ALREADY_EXISTS")
    policy = OperatingPolicy(args.min_recall, args.max_fpr)
    report = {
        "schema_version": "visiondata-gate.operating-point-audit.v1",
        "scope": "RETROSPECTIVE_DEVELOPMENT_DIAGNOSTIC_NOT_FRESH_TEST_VALIDATION",
        "historical_score_channel_only": True,
        "training_executed": False,
        "weights_modified": False,
        "production_release_allowed": False,
        "policy_basis": "EXPLICIT_EXPERIMENT_TARGET_NOT_CUSTOMER_ACCEPTANCE",
        "runs": [audit_run(run, policy) for run in args.run],
    }
    report["receipt_sha256"] = hashlib.sha256(canonical_jcs_bytes(report)).hexdigest()
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open("x", encoding="utf-8", newline="\n") as stream:
        json.dump(report, stream, ensure_ascii=False, indent=2, sort_keys=True)
        stream.write("\n")
    print(
        json.dumps(
            {
                "receipt_sha256": report["receipt_sha256"],
                "runs": [
                    {
                        "seed": r["model_seed"],
                        "selection_status": r["selection"]["status"],
                        "baseline": r["baseline"]["metrics"],
                        "diagnostic_evaluation": r["assessment"]["metrics"],
                        "assessment_status": r["assessment"]["status"],
                    }
                    for r in report["runs"]
                ],
            },
            ensure_ascii=False,
        )
    )


if __name__ == "__main__":
    main()


