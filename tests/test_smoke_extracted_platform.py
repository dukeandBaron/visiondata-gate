"""Contracts for post-build validation of one extracted Windows platform."""

from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest


TOOL = (
    Path(__file__).resolve().parents[1]
    / "tools"
    / "smoke_extracted_platform.py"
)


def _load_tool():
    spec = importlib.util.spec_from_file_location("smoke_extracted_platform", TOOL)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_http_plan_has_exactly_120_balanced_gateway_requests() -> None:
    tool = _load_tool()

    plan = tool.http_request_plan("prj_industrial_vision")

    assert len(plan) == 120
    assert {item["kind"] for item in plan} == {
        "health",
        "workspaces",
        "projects",
        "vision_capabilities",
    }
    assert all(sum(item["kind"] == kind for item in plan) == 30 for kind in {
        "health", "workspaces", "projects", "vision_capabilities"
    })
    assert all(item["path"].startswith("/v1/") for item in plan)


def test_resource_binding_projection_is_compact_and_manifest_bound() -> None:
    tool = _load_tool()
    inputs = {
        "backend_executable": {"sha256": "1" * 64, "size": 10},
        "backend_resources": {
            "content_sha256": "2" * 64,
            "file_count": 7,
            "total_bytes": 100,
            "files": [{"path": "private-build-path", "sha256": "3" * 64}],
        },
        "gateway_jar": {"sha256": "4" * 64, "size": 20},
        "java_runtime": {
            "content_sha256": "5" * 64,
            "file_count": 9,
            "total_bytes": 200,
            "files": [{"path": "private-runtime-path", "sha256": "6" * 64}],
        },
    }

    projection = tool.resource_binding_projection(
        inputs,
        build_manifest_sha256="7" * 64,
        installer_sha256="8" * 64,
    )

    assert projection["status"] == "PASS_EXTRACTED_RESOURCES_BOUND"
    assert projection["build_manifest_sha256"] == "7" * 64
    assert projection["installer_sha256"] == "8" * 64
    assert projection["backend"]["content_sha256"] == "2" * 64
    assert projection["java_runtime"]["file_count"] == 9
    assert "files" not in projection["backend"]
    assert "files" not in projection["java_runtime"]


def test_packaged_learning_requires_two_rounds_and_no_source_fallback() -> None:
    tool = _load_tool()
    manifest_sha = "a" * 64
    payload = {
        "status": "PASS_PACKAGED_LEARNING",
        "source_fallback": False,
        "runtime_execution": "SPECIFIED_PACKAGED_EXE_JRE_JAR_ONLY",
        "workflow_transport": "SPRING_WEBFLUX_GATEWAY_HTTP_ONLY",
        "bound_build_manifest_sha256": manifest_sha,
        "http_request_count": 78,
        "rounds": [
            {"round_number": 1, "status": "COMPLETED"},
            {"round_number": 2, "status": "COMPLETED"},
        ],
        "round_two_continued_first_candidate": True,
        "holdout_fingerprints_preserved": True,
        "runtime_artifact_bytes_unchanged": True,
        "process_cleanup": {"all_owned_processes_exited": True},
        "production_release_allowed": False,
        "machine_write_permitted": False,
        "industrial_performance_verified": False,
    }

    projection = tool.validate_packaged_learning(payload, manifest_sha)

    assert projection["round_count"] == 2
    assert projection["http_request_count"] == 78
    assert projection["source_fallback"] is False

    payload["source_fallback"] = True
    with pytest.raises(tool.PostValidationError, match="SOURCE_FALLBACK_FORBIDDEN"):
        tool.validate_packaged_learning(payload, manifest_sha)


def test_packaged_learning_rejects_single_round_or_manifest_drift() -> None:
    tool = _load_tool()
    base = {
        "status": "PASS_PACKAGED_LEARNING",
        "source_fallback": False,
        "runtime_execution": "SPECIFIED_PACKAGED_EXE_JRE_JAR_ONLY",
        "workflow_transport": "SPRING_WEBFLUX_GATEWAY_HTTP_ONLY",
        "bound_build_manifest_sha256": "b" * 64,
        "http_request_count": 40,
        "rounds": [{"round_number": 1, "status": "COMPLETED"}],
        "round_two_continued_first_candidate": False,
        "holdout_fingerprints_preserved": True,
        "runtime_artifact_bytes_unchanged": True,
        "process_cleanup": {"all_owned_processes_exited": True},
        "production_release_allowed": False,
        "machine_write_permitted": False,
        "industrial_performance_verified": False,
    }
    with pytest.raises(tool.PostValidationError, match="TWO_LEARNING_ROUNDS_REQUIRED"):
        tool.validate_packaged_learning(base, "b" * 64)
    base["rounds"].append({"round_number": 2, "status": "COMPLETED"})
    base["round_two_continued_first_candidate"] = True
    with pytest.raises(tool.PostValidationError, match="BUILD_MANIFEST_BINDING_MISMATCH"):
        tool.validate_packaged_learning(base, "c" * 64)

