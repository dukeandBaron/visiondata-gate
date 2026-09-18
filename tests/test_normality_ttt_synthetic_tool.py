"""Evidence verification must remain fail-closed under optimized Python."""

from __future__ import annotations

import ast
import copy
import json
from pathlib import Path
import runpy
import subprocess
import sys

import pytest


TOOL = Path(__file__).resolve().parents[1] / "tools" / "run_normality_ttt_synthetic.py"


def _tool():
    names = {
        node.name
        for node in ast.parse(TOOL.read_text("utf-8")).body
        if isinstance(node, ast.FunctionDef)
    }
    assert "_validate_episodes" in names, "optimization-safe episode checks missing"
    return runpy.run_path(str(TOOL))


def _evidence():
    return dict(
        accepted={
            "status": "ACCEPTED_EPISODIC",
            "objective_before": 1.0,
            "objective_after": 0.9,
            "attempted_parameter_sha256": "candidate",
            "backbone_sha256_before": "frozen",
            "backbone_sha256_after": "frozen",
        },
        repeated={"attempted_parameter_sha256": "candidate"},
        rejected={"rollback_reason": "TTT_GUARD_REGRESSION"},
        selected_digest="parent",
        parent_before="parent",
        parent_after="parent",
        unqualified=[
            {
                "rollback_reason": "TTT_GUARD_BASELINE_UNQUALIFIED",
                "steps_completed": 0,
                "objective_before": None,
                "objective_after": None,
            }
        ],
    )


def test_valid_evidence_is_accepted_without_importing_torch():
    previous = "torch" in sys.modules
    namespace = _tool()
    namespace["_validate_episodes"](**_evidence())
    namespace["_validate_bootstrap"](1, {"error_code": "TTT_REQUEST_INVALID"})
    assert ("torch" in sys.modules) == previous


@pytest.mark.parametrize(
    "group,field,value,code",
    [
        ("accepted", "status", "ROLLED_BACK", "TTT_SYNTHETIC_EXPECTED_ACCEPTED"),
        ("accepted", "objective_after", 1.1, "TTT_SYNTHETIC_OBJECTIVE_NOT_IMPROVED"),
        (
            "repeated",
            "attempted_parameter_sha256",
            "different",
            "TTT_SYNTHETIC_REPEAT_MISMATCH",
        ),
        (
            "rejected",
            "rollback_reason",
            "other",
            "TTT_SYNTHETIC_EXPECTED_GUARD_ROLLBACK",
        ),
        (None, "parent_after", "changed", "TTT_SYNTHETIC_PARENT_CHANGED"),
        (
            "accepted",
            "backbone_sha256_after",
            "changed",
            "TTT_SYNTHETIC_BACKBONE_CHANGED",
        ),
        (
            "unqualified",
            "rollback_reason",
            "other",
            "TTT_SYNTHETIC_EXPECTED_UNQUALIFIED_GUARD",
        ),
        ("unqualified", "steps_completed", 1, "TTT_SYNTHETIC_UNQUALIFIED_UPDATED"),
        (
            "unqualified",
            "objective_before",
            1.0,
            "TTT_SYNTHETIC_UNMEASURED_OBJECTIVE_PRESENT",
        ),
        (
            "unqualified",
            "objective_after",
            0.9,
            "TTT_SYNTHETIC_UNMEASURED_OBJECTIVE_PRESENT",
        ),
    ],
)
def test_each_evidence_failure_is_explicit(group, field, value, code):
    evidence = copy.deepcopy(_evidence())
    target = (
        evidence
        if group is None
        else (evidence["unqualified"][0] if group == "unqualified" else evidence[group])
    )
    target[field] = value
    with pytest.raises(RuntimeError, match=code):
        _tool()["_validate_episodes"](**evidence)


@pytest.mark.parametrize("flags", [[], ["-O"]])
def test_optimized_python_cannot_bypass_a_failed_evidence_check(flags):
    _tool()
    evidence = _evidence()
    evidence["accepted"]["status"] = "ROLLED_BACK"
    code = """
import json, runpy, sys
namespace = runpy.run_path(sys.argv[1])
namespace['_validate_episodes'](**json.loads(sys.argv[2]))
"""
    completed = subprocess.run(
        [sys.executable, *flags, "-I", "-c", code, str(TOOL), json.dumps(evidence)],
        capture_output=True,
        text=True,
        timeout=20,
    )
    assert completed.returncode != 0
    assert "RuntimeError: TTT_SYNTHETIC_EXPECTED_ACCEPTED" in completed.stderr


@pytest.mark.parametrize(
    "exit_code,error_code", [(0, "TTT_REQUEST_INVALID"), (1, "wrong")]
)
def test_bootstrap_failure_is_not_printed_as_verified(exit_code, error_code):
    with pytest.raises(RuntimeError, match="TTT_SYNTHETIC_BOOTSTRAP_MISMATCH"):
        _tool()["_validate_bootstrap"](exit_code, {"error_code": error_code})


def test_evidence_tool_has_no_optimization_removable_asserts():
    tree = ast.parse(TOOL.read_text("utf-8"))
    assert not any(isinstance(node, ast.Assert) for node in ast.walk(tree))
