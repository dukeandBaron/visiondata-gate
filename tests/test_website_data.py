from __future__ import annotations

import importlib.util
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]


def _load_validator():
    path = PROJECT_ROOT / "tools" / "check_website_data.py"
    spec = importlib.util.spec_from_file_location("check_website_data", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_judge_website_matches_frozen_release() -> None:
    receipt = _load_validator().validate_website_data()
    assert receipt["status"] == "PASS"
    assert receipt["pilot_denominator"] == 180
    assert receipt["dynamic_trigger_count"] == 3
    assert receipt["rule_check_count"] == 8
    assert receipt["architecture_record_count"] == 288
