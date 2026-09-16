"""Bounded CPU diagnostic using an existing trusted normality pack, no retraining."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import time

from visiondata_gate import normality_inference
from visiondata_gate.anomaly_operating_point import (
    OperatingPolicy,
    select_operating_point,
    evaluate_operating_point,
)
from visiondata_gate.audit_envelope import canonical_jcs_bytes

CHANNELS = ("mean", "top_0_1pct", "top_1pct", "max")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--limit", type=int, default=160)
    args = parser.parse_args()
    if not 1 <= args.limit <= 160 or args.output.exists():
        raise ValueError("FRESH_BOUNDED_OUTPUT_REQUIRED")
    args.output.mkdir(parents=True)
    args.output = args.output.resolve()
    config_dir = args.output / "runtime-config"
    config_dir.mkdir()
    os.environ["YOLO_CONFIG_DIR"] = str(config_dir)
    os.environ["OMP_NUM_THREADS"] = "2"
    normality_inference._deny_network_and_children()
    request_path = args.run / "private/worker_request.json"
    result_path = args.run / "private/worker_result.json"
    request = json.loads(request_path.read_text(encoding="utf-8"))
    result = json.loads(result_path.read_text(encoding="utf-8"))
    source_root = Path(request["dataset_root"]).resolve(strict=True)
    checkpoint = args.run / "private/worker/best_normality_model_pack.pt"
    metadata = result["checkpoint"]["validation_view"]
    loaded = normality_inference._load_normality_pack(
        checkpoint,
        result["checkpoint"]["sha256"],
        metadata["backbone"]["weights_sha256"],
    )
    samples = {s["source_sample_id"]: s for s in request["samples"]}
    predictions = result["per_sample_predictions"][: args.limit]
    records, latency = [], []
    started = time.monotonic()
    for index, prediction in enumerate(predictions):
        if time.monotonic() - started > 600:
            raise RuntimeError("DIAGNOSTIC_WALL_BUDGET_EXCEEDED")
        sample = samples[prediction["source_sample_id"]]
        path = (source_root / sample["image_relative_path"]).resolve(strict=True)
        if not path.is_relative_to(source_root):
            raise ValueError("INPUT_OUTSIDE_DATASET")
        scores = {}
        for channel in CHANNELS:
            loaded["selected_image_aggregation"] = channel
            measured = normality_inference._score_normality_image(
                loaded,
                path,
                sample["image_sha256"],
                args.output / "maps" / f"{index:03d}-{channel}" / "heatmap.png",
            )
            scores[channel] = measured["image_score"]
            latency.append(measured["latency_ms"])
        if abs(scores["mean"] - prediction["image_score"]) > 0.001:
            raise ValueError("BASELINE_REPRODUCTION_DRIFT")
        records.append(
            {
                "source_sample_id": prediction["source_sample_id"],
                "split_role": prediction["split_role"],
                "product_label": prediction["product_label"],
                "image_scores": scores,
            }
        )
        if (index + 1) % 20 == 0:
            print(json.dumps({"scored_images": index + 1}), flush=True)
    report = {
        "scope": "RETROSPECTIVE_FROZEN_MODEL_DIAGNOSTIC",
        "device": "CPU",
        "score_channels": list(CHANNELS),
        "records": records,
        "model_pack_sha256": result["checkpoint"]["sha256"],
        "source_predictions_sha256": hashlib.sha256(
            result_path.read_bytes()
        ).hexdigest(),
        "inference_implementation_sha256": hashlib.sha256(
            Path(normality_inference.__file__).read_bytes()
        ).hexdigest(),
        "elapsed_seconds": time.monotonic() - started,
        "forward_passes": len(latency),
        "training_executed": False,
        "weights_modified": False,
        "production_release_allowed": False,
        "baseline_reproduction_tolerance": 0.001,
        "fresh_test_validation": "NOT_RUN",
    }
    if args.limit == 160:
        calibration = [r for r in records if r["split_role"] == "calibration"]
        evaluation = [r for r in records if r["split_role"] == "heldout_development"]
        selection = select_operating_point(calibration, OperatingPolicy(0.8, 0.2))
        report["selection"] = selection
        report["assessment"] = evaluate_operating_point(selection, evaluation)
    report["receipt_sha256"] = hashlib.sha256(canonical_jcs_bytes(report)).hexdigest()
    with (args.output / "report.json").open("x", encoding="utf-8") as stream:
        json.dump(report, stream, ensure_ascii=False, indent=2)
        stream.write("\n")
    print(
        json.dumps(
            {
                "scored_images": len(records),
                "receipt_sha256": report["receipt_sha256"],
                "assessment": report.get("assessment", {"status": "SMOKE_ONLY"}),
            }
        )
    )


if __name__ == "__main__":
    main()


