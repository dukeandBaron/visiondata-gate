"""Run the reproducible test denominator shipped by the public mirror."""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
PUBLIC_TEST_MODULES = (
    "tests/test_identity_service.py",
    "tests/test_identity_api.py",
    "tests/test_identity_router.py",
    "tests/test_identity_platform_integration.py",
    "tests/test_identity_review_regressions.py",
    "tests/test_data_pool.py",
    "tests/test_data_pool_api.py",
    "tests/test_local_model_registry.py",
    "tests/test_vision_model_api.py",
    "tests/test_vision_feedback.py",
    "tests/test_vision_feedback_lifecycle.py",
    "tests/test_vision_data_pool_bridge.py",
    "tests/test_learning_contracts.py",
    "tests/test_learning_dataset.py",
    "tests/test_learning_evaluation.py",
    "tests/test_public_platform_delivery.py",
    "tests/test_operator_exact_duplicate_capa.py",
    "tests/test_compute_handoff.py",
    "tests/test_operator_snapshot_acceptance_requirements.py",
    "tests/test_operator_snapshot_annotation_roundtrip.py",
    "tests/test_agent_runtime.py",
    "tests/test_runtime_safety.py",
    "tests/test_api.py",
    "tests/test_incident_interaction_api.py",
    "tests/test_private_industrial_validation.py",
    "tests/test_public_repository_tools.py",
    "tests/test_public_docs.py",
    "tests/test_semifinal_demo.py",
    "tests/test_web_private_industrial_validation.py",
    "tests/test_web_source.py",
)


def main() -> int:
    missing = [
        relative
        for relative in PUBLIC_TEST_MODULES
        if not (PROJECT_ROOT / relative).is_file()
    ]
    if missing:
        print(
            json.dumps(
                {
                    "status": "HOLD_PUBLIC_TEST_SUITE",
                    "reason": "required public test module is missing",
                    "missing": missing,
                },
                ensure_ascii=False,
                indent=2,
            )
        )
        return 2
    result = subprocess.run(
        [sys.executable, "-m", "pytest", "-q", *PUBLIC_TEST_MODULES],
        cwd=PROJECT_ROOT,
        check=False,
    )
    return result.returncode


if __name__ == "__main__":
    raise SystemExit(main())
