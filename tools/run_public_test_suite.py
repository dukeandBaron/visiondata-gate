"""Run the reproducible test denominator shipped by the public mirror."""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
PUBLIC_TEST_MODULES = (
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
