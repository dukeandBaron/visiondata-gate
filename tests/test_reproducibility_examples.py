from __future__ import annotations

import json
from pathlib import Path
import subprocess
import sys

import rfc8785

from visiondata_gate.prompt_injection_evaluation import (
    build_prompt_injection_evaluation_receipt,
)


REPO_ROOT = Path(__file__).resolve().parents[1]
EXAMPLE_ROOT = REPO_ROOT / "examples" / "reproducibility"


def test_checked_in_dynamic_subset_matches_fresh_source_rebuild() -> None:
    completed = subprocess.run(
        [
            sys.executable,
            str(REPO_ROOT / "tools" / "run_dynamic_benchmark_v3_subset.py"),
            str(EXAMPLE_ROOT / "DYNAMICBENCH_V3_REPRO_SUBSET.json"),
            "--verify-only",
        ],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    assert completed.returncode == 0, completed.stderr


def test_checked_in_prompt_injection_receipt_matches_fixed_v2_builder() -> None:
    path = EXAMPLE_ROOT / "PROMPT_INJECTION_V2_FIXED_SET.json"
    stored = json.loads(path.read_text(encoding="utf-8"))
    rebuilt = build_prompt_injection_evaluation_receipt()

    assert stored == rebuilt
    assert rfc8785.dumps(stored) == rfc8785.dumps(rebuilt)
    assert stored["attack"]["fixed_denominator"] == 12
    assert stored["attack"]["blocked_count"] == 12
    assert stored["benign_utility"]["fixed_denominator"] == 6
    assert stored["benign_utility"]["allowed_count"] == 6
    assert stored["raw_attack_text_retained"] is False
