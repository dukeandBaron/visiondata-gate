"""CLI contract for the reproducible registry-owned normality smoke."""

from __future__ import annotations

from pathlib import Path
import subprocess
import sys

import pytest


def test_registry_smoke_cli_is_parameterized_and_requires_explicit_authority():
    root = Path(__file__).resolve().parents[1]
    tool = root / "tools" / "run_normality_registry_smoke.py"
    completed = subprocess.run(
        [sys.executable, str(tool), "--help"],
        cwd=root,
        capture_output=True,
        text=True,
        timeout=20,
        check=False,
    )

    assert completed.returncode == 0, completed.stderr
    for option in (
        "--run-dir",
        "--target-run-dir",
        "--stability-summary",
        "--source-binding",
        "--source-index",
        "--backbone-weights",
        "--runtime-python",
        "--normal-image",
        "--anomaly-image",
        "--output",
        "--reviewer-identity",
        "--authorize-local-execution",
        "--authorize-weights-only-load",
        "--acknowledge-ultralytics-license-review",
    ):
        assert option in completed.stdout
    source = tool.read_text(encoding="utf-8")
    assert "F:/" not in source
    assert "E:/" not in source


def test_smoke_receipt_requires_one_inference_backend_identity():
    from tools import run_normality_registry_smoke as smoke

    projection = getattr(smoke, "_inference_backend_projection", None)
    assert callable(projection), "smoke backend identity projection is missing"
    backend_sha = "a" * 64
    approved = {
        "sandbox_validation": {"inference_backend_sha256": backend_sha}
    }
    results = {
        "normal": {"inference_backend_sha256": backend_sha},
        "anomaly": {"inference_backend_sha256": backend_sha},
    }

    assert projection(approved, results) == backend_sha
    results["anomaly"]["inference_backend_sha256"] = "b" * 64
    with pytest.raises(ValueError, match="SMOKE_INFERENCE_BACKEND_IDENTITY_MISMATCH"):
        projection(approved, results)
