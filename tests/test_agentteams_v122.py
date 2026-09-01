from __future__ import annotations

import hashlib
import json

from visiondata_gate.agentteams_contract import build_agentteams_contract
from visiondata_gate.agentteams_v122 import (
    AGENTTEAMS_API_VERSION,
    AGENTTEAMS_COMMIT,
    build_agentteams_conformance_receipt,
    build_agentteams_resources_yaml,
    build_skill_distribution_plan,
    validate_runtime_receipt,
)
from visiondata_gate.evidence import canonical_json_bytes, sha256_file
from visiondata_gate.runtime_models import ScenarioProfile


def _snapshot():
    return build_agentteams_contract(
        ScenarioProfile.INDUSTRIAL,
        allowed_tools=[
            "image_quality",
            "duplicate_leakage",
            "annotation_integrity",
            "coverage_matrix",
            "governance_audit",
        ],
        include_optional=True,
        run_id="v122-test",
    )


def test_v122_resources_match_official_cr_shape_and_unique_leader() -> None:
    payload = build_agentteams_resources_yaml()
    assert AGENTTEAMS_API_VERSION in payload
    assert payload.count("kind: Worker") == 9
    assert payload.count("kind: Team") == 1
    assert payload.count("role: team_leader") == 1
    assert payload.count("role: worker") == 8
    assert "name: visiondata-policy-judge" in payload
    assert "skills: [fail-closed-policy]" in payload
    assert "apiKey" not in payload
    assert "password" not in payload.lower()


def test_skill_distribution_plan_has_agentteams_required_metadata() -> None:
    plan = build_skill_distribution_plan()
    assert plan["agentteams_version"] == "v1.2.2"
    assert plan["worker_assignments"]
    assert all(item["present"] for item in plan["skills"])
    assert all(item["name"] == item["frontmatter_name"] for item in plan["skills"])
    assert all(item["description_present"] for item in plan["skills"])
    assert all(len(item["sha256"]) == 64 for item in plan["skills"])


def test_static_conformance_stays_partial_without_runtime_receipt() -> None:
    resources = build_agentteams_resources_yaml().encode("utf-8")
    plan = build_skill_distribution_plan()
    receipt = build_agentteams_conformance_receipt(
        _snapshot(),
        resources_sha256=hashlib.sha256(resources).hexdigest(),
        skill_plan=plan,
    )
    assert receipt["static_status"] == "PASS"
    assert receipt["runtime_validation"]["status"] == "OPEN"
    assert receipt["overall_status"] == "PARTIAL"
    assert receipt["connection_status"] == "mapped_not_connected"
    assert receipt["matrix_connected"] is False


def test_runtime_receipt_requires_hash_bound_raw_evidence(tmp_path) -> None:
    raw_dir = tmp_path / "agentteams_runtime_raw"
    raw_dir.mkdir()
    team_path = raw_dir / "team-status.json"
    event_path = raw_dir / "matrix-assignment.json"
    skills_path = raw_dir / "skill-assignments.json"
    assignments = build_skill_distribution_plan()["worker_assignments"]
    team_raw = {
        "name": "visiondata-gate",
        "phase": "Active",
        "teamRoomID": "!visiondata:example.test",
        "leaderReady": True,
        "readyWorkers": 9,
        "totalWorkers": 9,
    }
    event_raw = {
        "room_id": "!visiondata:example.test",
        "event_id": "$assignment-event",
        "event_count": 1,
        "retry_reused": True,
    }
    team_path.write_bytes(canonical_json_bytes(team_raw))
    event_path.write_bytes(canonical_json_bytes(event_raw))
    skills_path.write_bytes(canonical_json_bytes(assignments))

    receipt = {
        "schema_version": "visiondata-gate.agentteams-runtime-receipt.v1",
        "agentteams_version": "v1.2.2",
        "agentteams_commit": AGENTTEAMS_COMMIT,
        "team": {
            "name": "visiondata-gate",
            "phase": "Active",
            "team_room_id": "!visiondata:example.test",
            "leader_ready": True,
            "ready_workers": 9,
            "total_workers": 9,
        },
        "assignment": {
            "room_id": "!visiondata:example.test",
            "event_id": "$assignment-event",
            "event_count": 1,
            "retry_reused": True,
        },
        "skill_assignments": assignments,
        "raw_evidence": {
            "team_status": {
                "path": "agentteams_runtime_raw/team-status.json",
                "sha256": sha256_file(team_path),
            },
            "matrix_assignment": {
                "path": "agentteams_runtime_raw/matrix-assignment.json",
                "sha256": sha256_file(event_path),
            },
            "skill_assignments": {
                "path": "agentteams_runtime_raw/skill-assignments.json",
                "sha256": sha256_file(skills_path),
            },
        },
    }
    receipt_path = tmp_path / "agentteams_runtime_receipt.external.json"
    receipt_path.write_bytes(canonical_json_bytes(receipt))

    valid = validate_runtime_receipt(receipt, receipt_path=receipt_path)
    assert valid["status"] == "PASS"
    assert valid["connection_status"] == "connected"
    assert valid["matrix_connected"] is True

    receipt["raw_evidence"]["matrix_assignment"]["sha256"] = "0" * 64
    invalid = validate_runtime_receipt(receipt, receipt_path=receipt_path)
    assert invalid["status"] == "FAIL"
    assert invalid["connection_status"] == "mapped_not_connected"
    assert invalid["matrix_connected"] is False
    assert "raw_matrix_assignment_hash_matches" in invalid["reasons"]


def test_runtime_receipt_rejects_semantic_raw_mismatch_and_path_escape(
    tmp_path,
) -> None:
    raw_dir = tmp_path / "raw"
    raw_dir.mkdir()
    outside = tmp_path.parent / f"{tmp_path.name}-outside.json"
    outside.write_text('{"phase":"Active"}', encoding="utf-8")
    team_path = raw_dir / "team.json"
    matrix_path = raw_dir / "matrix.json"
    skills_path = raw_dir / "skills.json"
    team_path.write_text('{"name":"wrong-team"}', encoding="utf-8")
    matrix_path.write_text("{}", encoding="utf-8")
    skills_path.write_text("[]", encoding="utf-8")
    receipt = {
        "schema_version": "visiondata-gate.agentteams-runtime-receipt.v1",
        "agentteams_version": "v1.2.2",
        "agentteams_commit": AGENTTEAMS_COMMIT,
        "team": {
            "name": "visiondata-gate",
            "phase": "Active",
            "team_room_id": "!visiondata:example.test",
            "leader_ready": True,
            "ready_workers": 9,
            "total_workers": 9,
        },
        "assignment": {
            "room_id": "!visiondata:example.test",
            "event_id": "$assignment-event",
            "event_count": 1,
            "retry_reused": True,
        },
        "skill_assignments": build_skill_distribution_plan()["worker_assignments"],
        "raw_evidence": {
            "team_status": {
                "path": str(outside),
                "sha256": sha256_file(outside),
            },
            "matrix_assignment": {
                "path": "raw/matrix.json",
                "sha256": sha256_file(matrix_path),
            },
            "skill_assignments": {
                "path": "raw/skills.json",
                "sha256": sha256_file(skills_path),
            },
        },
    }
    receipt_path = tmp_path / "receipt.json"
    receipt_path.write_bytes(canonical_json_bytes(receipt))

    result = validate_runtime_receipt(receipt, receipt_path=receipt_path)

    assert result["status"] == "FAIL"
    assert result["checks"]["raw_team_status_path_contained"] is False
    assert result["checks"]["raw_skill_assignments_match_summary"] is False


def test_agent_demo_persists_partial_v122_conformance(tmp_path) -> None:
    from visiondata_gate.agent_runtime import run_agentic_demo
    from visiondata_gate.runtime_models import RuntimeConfig

    run = run_agentic_demo(
        tmp_path / "run",
        seed=20260823,
        config=RuntimeConfig(scenario_profile=ScenarioProfile.INDUSTRIAL),
        memory_path=tmp_path / "memory.json",
    )
    path = run.evidence_dir / "agentteams_v122_conformance.json"
    resources_path = run.evidence_dir / "agentteams_v122_resources.yaml"
    skill_path = run.evidence_dir / "agentteams_v122_skill_distribution.json"
    assert path.is_file() and resources_path.is_file() and skill_path.is_file()
    payload = json.loads(path.read_text(encoding="utf-8"))
    assert payload["static_status"] == "PASS"
    assert payload["runtime_validation"]["status"] == "OPEN"
    assert payload["connection_status"] == "mapped_not_connected"
    assert payload["resources_sha256"] == sha256_file(resources_path)
