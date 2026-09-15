import copy
import math
from pathlib import Path

import numpy as np
import pytest

from visiondata_gate.anomaly_operating_point import (
    OperatingPolicy,
    select_operating_point,
    evaluate_operating_point,
    summarize_anomaly_map,
    confusion_metrics,
)


def rows(role="calibration", prefix="c"):
    return [
        {
            "source_sample_id": prefix + str(i),
            "split_role": role,
            "product_label": label,
            "image_scores": {"mean": mean, "local": local},
        }
        for i, (label, mean, local) in enumerate(
            [
                ("normal", 0.6, 0.1),
                ("normal", 0.7, 0.2),
                ("anomaly", 0.2, 0.8),
                ("anomaly", 0.3, 0.9),
            ]
        )
    ]


def test_joint_selection_uses_local_signal_and_separates_evaluation():
    selection = select_operating_point(rows(), OperatingPolicy(0.9, 0))
    assert selection["diagnostic_candidate"]["channel"] == "local"
    result = evaluate_operating_point(selection, rows("heldout_development", "e"))
    assert result["metrics"]["recall"] == 1
    assert result["metrics"]["false_positive_rate"] == 0
    assert result["production_release_allowed"] is False


def test_tied_scores_cannot_fake_feasible_recall():
    samples = rows()
    for row in samples:
        row["image_scores"] = {"mean": 1.0}
    selection = select_operating_point(samples, OperatingPolicy(0.8, 0.1))
    assert selection["status"] == "HOLD_NO_FEASIBLE_OPERATING_POINT"
    assert selection["diagnostic_candidate"]["metrics"]["recall"] == 0
    assert selection["deployable_threshold"] is None


def test_calibration_and_evaluation_overlap_is_rejected():
    selection = select_operating_point(rows(), OperatingPolicy(0.8, 0.1))
    with pytest.raises(ValueError, match="OVERLAP"):
        evaluate_operating_point(selection, rows("heldout_development"))


def test_drifted_receipt_rejected():
    selection = select_operating_point(rows(), OperatingPolicy(0.8, 0.1))
    changed = copy.deepcopy(selection)
    changed["diagnostic_candidate"]["threshold"] = 0
    with pytest.raises(ValueError, match="DRIFT"):
        evaluate_operating_point(changed, rows("heldout_development", "e"))


@pytest.mark.parametrize("bad", [float("nan"), float("inf"), True])
def test_invalid_scores_rejected(bad):
    samples = rows()
    samples[0]["image_scores"]["mean"] = bad
    with pytest.raises(ValueError, match="INVALID_SCORE"):
        select_operating_point(samples, OperatingPolicy(0.8, 0.1))


def test_single_class_cannot_claim_zero_error():
    with pytest.raises(ValueError, match="BOTH_REFERENCE_CLASSES"):
        select_operating_point(rows()[:2], OperatingPolicy(0.8, 0.1))


def test_missing_channel_rejected():
    samples = rows()
    del samples[0]["image_scores"]["local"]
    with pytest.raises(ValueError, match="CHANNEL_SET"):
        select_operating_point(samples, OperatingPolicy(0.8, 0.1))


def test_small_defect_scores_are_not_diluted_in_local_channel():
    heatmap = np.zeros((100, 100))
    heatmap[0, 0] = 100
    result = summarize_anomaly_map(heatmap)
    assert result["mean"] == 0.01
    assert result["top_0_1pct"] == 10
    assert result["max"] == 100


def test_evaluation_failure_cannot_be_promoted():
    selection = select_operating_point(rows(), OperatingPolicy(0.8, 0.1))
    samples = rows("heldout_development", "e")
    for row in samples:
        row["image_scores"]["local"] = 0.9
    result = evaluate_operating_point(selection, samples)
    assert result["status"] == "HOLD_OPERATING_TARGET_NOT_MET"


@pytest.mark.parametrize("cap", [0.0, 0.1, 0.2, 0.5, 1.0])
def test_sorted_sweep_matches_exhaustive_threshold_search(cap):
    rng = np.random.default_rng(123)
    samples = [
        {
            "source_sample_id": str(i),
            "split_role": "calibration",
            "product_label": "normal" if i % 2 else "anomaly",
            "image_scores": {"mean": float(rng.integers(0, 10))},
        }
        for i in range(80)
    ]
    thresholds = sorted({r["image_scores"]["mean"] for r in samples})
    thresholds.append(math.nextafter(thresholds[-1], math.inf))
    feasible = []
    for threshold in thresholds:
        m = confusion_metrics(samples, "mean", threshold)
        if m["false_positive_rate"] <= cap:
            feasible.append(
                (m["recall"], -m["false_positive_rate"], m["f1"], threshold)
            )
    selected = select_operating_point(samples, OperatingPolicy(0.8, cap))
    assert selected["diagnostic_candidate"]["threshold"] == max(feasible)[-1]


def test_public_docs_keep_operating_point_as_a_bounded_diagnostic():
    root = Path(__file__).resolve().parents[1]
    guide = (root / "docs" / "ANOMALY_OPERATING_POINT.md").read_text("utf-8")
    readme = (root / "README.md").read_text("utf-8")
    source_readme = (root / "docs" / "PUBLIC_REPOSITORY_README.md").read_text(
        "utf-8"
    )

    assert "calibration" in guide and "heldout_development" in guide
    assert "production_release_allowed=false" in guide
    assert "PRODUCT_API_NOT_CONNECTED" in guide
    assert "ANOMALY_OPERATING_POINT.md" in readme
    assert "ANOMALY_OPERATING_POINT.md" in source_readme

