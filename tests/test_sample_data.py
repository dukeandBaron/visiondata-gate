from __future__ import annotations

from hashlib import sha256
from pathlib import Path

import numpy as np
from PIL import Image

from visiondata_gate.contracts import QualityThresholds
from visiondata_gate.quality import _sharpness_score


ROOT = Path(__file__).resolve().parents[1]
SAMPLE_ROOT = ROOT / "sample_data"


def _luma_metrics(path: Path) -> tuple[float, float]:
    with Image.open(path) as image:
        luma = np.asarray(image.convert("L"), dtype=np.float32)
    return float(np.mean(luma, dtype=np.float64)), _sharpness_score(luma)


def test_sample_data_sha256_manifest_matches_files() -> None:
    manifest_path = SAMPLE_ROOT / "SHA256SUMS.txt"
    entries = [
        line.split(maxsplit=1) for line in manifest_path.read_text().splitlines()
    ]

    assert len(entries) == 6
    for expected_sha256, relative_path in entries:
        payload = (SAMPLE_ROOT / relative_path).read_bytes()
        assert sha256(payload).hexdigest().casefold() == expected_sha256.casefold()


def test_quality_anomaly_samples_violate_the_named_default_threshold() -> None:
    thresholds = QualityThresholds()
    blur_luma, blur_sharpness = _luma_metrics(
        SAMPLE_ROOT / "quality_anomalies" / "q-blur.png"
    )
    overexposed_luma, _ = _luma_metrics(
        SAMPLE_ROOT / "quality_anomalies" / "q-overexposed.png"
    )
    underexposed_luma, _ = _luma_metrics(
        SAMPLE_ROOT / "quality_anomalies" / "q-underexposed.png"
    )

    assert thresholds.min_mean_luma <= blur_luma <= thresholds.max_mean_luma
    assert blur_sharpness < thresholds.min_sharpness
    assert overexposed_luma > thresholds.max_mean_luma
    assert underexposed_luma < thresholds.min_mean_luma
