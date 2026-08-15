"""Fail-closed AgentTeams v1.2.2 deployment and receipt adapter.

The domain runtime can be executed locally without AgentTeams, but the GOAI
Agent Infra track requires more than a prose-level mapping.  This module makes
the official ``agentteams.io/v1beta1`` resources, custom Skill distribution
plan, and transport evidence gate explicit.  A static contract pass never
upgrades connectivity: ``connected`` is only emitted after raw Team status,
Matrix assignment, and Skill assignment payloads are hash-verified.
"""

from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path
from typing import Any, Mapping, Sequence

from .evidence import canonical_json_bytes, sha256_file
from .runtime_models import AgentTeamsSnapshot


AGENTTEAMS_VERSION = "v1.2.2"
AGENTTEAMS_COMMIT = "aa650ccacc2ba6171d1b0b5efd2a49b1472abe5d"
AGENTTEAMS_API_VERSION = "agentteams.io/v1beta1"
AGENTTEAMS_REPOSITORY = "https://github.com/agentscope-ai/AgentTeams"

_PROJECT_ROOT = Path(__file__).resolve().parents[2]
_SKILL_ROOT = _PROJECT_ROOT / "skills"
_SKILL_NAME = re.compile(r"^name:\s*([a-z0-9][a-z0-9-]*)\s*$", re.MULTILINE)
_SKILL_DESCRIPTION = re.compile(r"^description:\s*(\S.+)\s*$", re.MULTILINE)


def _sha256_payload(payload: object) -> str:
    return hashlib.sha256(canonical_json_bytes(payload)).hexdigest()


def _worker_specs() -> list[dict[str, object]]:
    return [
        {
            "name": "visiondata-release-lead",
            "role": "team_leader",
            "identity": "Release Gate Team Leader; decomposes the typed DAG and delegates all domain work.",
            "skills": ["parallel-evidence-audit"],
        },
        {
            "name": "visiondata-image-quality",
            "role": "worker",
            "identity": "Image-quality evidence Worker; emits typed measurements and never writes release decisions.",
            "skills": ["parallel-evidence-audit"],
        },
        {
            "name": "visiondata-duplicate-leakage",
            "role": "worker",
            "identity": "Duplicate and cross-split leakage Worker; emits ToolTrace and Finding references only.",
            "skills": ["parallel-evidence-audit"],
        },
        {
            "name": "visiondata-annotation-integrity",
            "role": "worker",
            "identity": "Annotation-integrity Worker; checks mask presence and geometry under a read-only contract.",
            "skills": ["parallel-evidence-audit"],
        },
        {
            "name": "visiondata-coverage-matrix",
            "role": "worker",
            "identity": "Coverage-matrix Worker; reports missing contract cells without inventing samples.",
            "skills": ["parallel-evidence-audit"],
        },
        {
            "name": "visiondata-ai-council",
            "role": "worker",
            "identity": "Evidence Council Worker; advisory, citation-bound, and explicitly not an independent human expert.",
            "skills": ["evidence-grounded-council"],
        },
        {
            "name": "visiondata-policy-judge",
            "role": "worker",
            "identity": "Fail-closed Policy Judge Worker; sole writer of GateDecision under frozen rules.",
            "skills": ["fail-closed-policy"],
        },
        {
            "name": "visiondata-repair-operator",
            "role": "worker",
            "identity": "Reserve-only repair Worker; preserves the original batch and triggers same-contract recheck.",
            "skills": ["reserve-repair-recheck"],
        },
        {
            "name": "visiondata-audit-clerk",
            "role": "worker",
            "identity": "Evidence delivery Worker; serializes canonical artifacts and cannot change the decision.",
            "skills": ["reserve-repair-recheck"],
        },
    ]


def _yaml_scalar(value: str) -> str:
    return json.dumps(value, ensure_ascii=False)


def build_agentteams_resources_yaml(
    *, model: str = "qwen3.5-plus", runtime: str = "qwenpaw"
) -> str:
    """Build official ``Worker`` and ``Team`` resources without credentials."""

    documents: list[str] = []
    for worker in _worker_specs():
        skills = ", ".join(str(item) for item in worker["skills"])
        documents.append(
            "\n".join(
                [
                    f"apiVersion: {AGENTTEAMS_API_VERSION}",
                    "kind: Worker",
                    "metadata:",
                    f"  name: {worker['name']}",
                    "spec:",
                    f"  model: {_yaml_scalar(model)}",
                    f"  runtime: {runtime}",
                    f"  identity: {_yaml_scalar(str(worker['identity']))}",
                    "  agents: |",
                    "    Execute only assigned VisionData Gate tasks.",
                    "    Return typed artifact references; do not claim production authorization.",
                    f"  skills: [{skills}]",
                    "  state: Running",
                ]
            )
        )

    members = []
    for worker in _worker_specs():
        members.extend(
            [
                f"    - name: {worker['name']}",
                f"      role: {worker['role']}",
            ]
        )
    documents.append(
        "\n".join(
            [
                f"apiVersion: {AGENTTEAMS_API_VERSION}",
                "kind: Team",
                "metadata:",
                "  name: visiondata-gate",
                "spec:",
                "  description: Industrial-vision data release gate with evidence-bound Workers and a fail-closed Judge.",
                "  peerMentions: true",
                "  heartbeatEvery: 30m",
                "  workerMembers:",
                *members,
            ]
        )
    )
    return "\n---\n".join(documents) + "\n"


def _read_skill_metadata(skill_name: str) -> dict[str, object]:
    path = _SKILL_ROOT / skill_name / "SKILL.md"
    text = path.read_text(encoding="utf-8") if path.is_file() else ""
    name_match = _SKILL_NAME.search(text)
    description_match = _SKILL_DESCRIPTION.search(text)
    return {
        "name": skill_name,
        "path": path.relative_to(_PROJECT_ROOT).as_posix(),
        "present": path.is_file(),
        "frontmatter_name": name_match.group(1) if name_match else None,
        "description_present": bool(description_match),
        "sha256": sha256_file(path) if path.is_file() else None,
    }


def build_skill_distribution_plan() -> dict[str, object]:
    skills = sorted(
        {str(skill) for worker in _worker_specs() for skill in worker["skills"]}
        | {"contract-intake"}
    )
    metadata = [_read_skill_metadata(name) for name in skills]
    assignments = [
        {"worker": worker["name"], "skills": worker["skills"]}
        for worker in _worker_specs()
    ]
    return {
        "schema_version": "visiondata-gate.agentteams-skill-distribution.v1",
        "agentteams_version": AGENTTEAMS_VERSION,
        "manager_skill": "contract-intake",
        "worker_assignments": assignments,
        "skills": metadata,
        "distribution_contract": (
            "Upload each complete Skill directory to the AgentTeams Manager workspace, "
            "validate SKILL.md, assign names through Worker.spec.skills, then export the "
            "observed assignments. Dashboard-only files do not prove spec.skills assignment."
        ),
    }


def _raw_receipt_check(
    receipt: Mapping[str, Any], receipt_path: Path | None
) -> tuple[dict[str, bool], list[str]]:
    raw = receipt.get("raw_evidence", {})
    raw = raw if isinstance(raw, Mapping) else {}
    base = receipt_path.parent if receipt_path is not None else Path.cwd()
    checks: dict[str, bool] = {}
    resolved: list[str] = []
    for key in ("team_status", "matrix_assignment", "skill_assignments"):
        item = raw.get(key, {})
        item = item if isinstance(item, Mapping) else {}
        relative = item.get("path")
        expected = item.get("sha256")
        candidate = (
            (base / str(relative)).resolve() if relative else base / "__missing__"
        )
        checks[f"raw_{key}_present"] = candidate.is_file()
        checks[f"raw_{key}_hash_matches"] = bool(
            candidate.is_file()
            and isinstance(expected, str)
            and len(expected) == 64
            and sha256_file(candidate) == expected
        )
        if candidate.is_file():
            resolved.append(str(candidate))
    return checks, resolved


def validate_runtime_receipt(
    receipt: Mapping[str, Any] | None, *, receipt_path: Path | None = None
) -> dict[str, object]:
    """Validate a real AgentTeams/Matrix export; absence stays explicitly open."""

    if receipt is None:
        return {
            "status": "OPEN",
            "connection_status": "mapped_not_connected",
            "matrix_connected": False,
            "checks": {},
            "raw_evidence_paths": [],
            "reasons": [
                "No external AgentTeams runtime receipt was supplied.",
                "Static CR/Skill conformance cannot prove Team Room or Matrix execution.",
            ],
        }

    team = receipt.get("team", {})
    team = team if isinstance(team, Mapping) else {}
    assignment = receipt.get("assignment", {})
    assignment = assignment if isinstance(assignment, Mapping) else {}
    skill_assignments = receipt.get("skill_assignments", [])
    skill_assignments = (
        skill_assignments if isinstance(skill_assignments, Sequence) else []
    )
    member_names = {str(item["name"]) for item in _worker_specs()}
    observed_workers = {
        str(item.get("worker"))
        for item in skill_assignments
        if isinstance(item, Mapping)
    }
    raw_checks, raw_paths = _raw_receipt_check(receipt, receipt_path)
    team_room_id = str(team.get("team_room_id", ""))
    event_id = str(assignment.get("event_id", ""))
    total_workers = team.get("total_workers")
    ready_workers = team.get("ready_workers")
    checks = {
        "schema_matches": receipt.get("schema_version")
        == "visiondata-gate.agentteams-runtime-receipt.v1",
        "official_commit_matches": receipt.get("agentteams_commit")
        == AGENTTEAMS_COMMIT,
        "team_name_matches": team.get("name") == "visiondata-gate",
        "team_active": team.get("phase") == "Active",
        "team_room_id_present": team_room_id.startswith("!"),
        "leader_ready": team.get("leader_ready") is True,
        "all_workers_ready": isinstance(total_workers, int)
        and isinstance(ready_workers, int)
        and total_workers >= 3
        and ready_workers == total_workers,
        "assignment_room_matches": assignment.get("room_id") == team_room_id,
        "assignment_event_id_present": event_id.startswith("$"),
        "assignment_exactly_once": assignment.get("event_count") == 1,
        "assignment_retry_reused": assignment.get("retry_reused") is True,
        "skill_assignments_cover_team": member_names <= observed_workers,
        **raw_checks,
    }
    passed = all(checks.values())
    return {
        "status": "PASS" if passed else "FAIL",
        "connection_status": "connected" if passed else "mapped_not_connected",
        "matrix_connected": passed,
        "checks": checks,
        "raw_evidence_paths": raw_paths,
        "reasons": []
        if passed
        else [key for key, value in checks.items() if not value],
    }


def build_agentteams_conformance_receipt(
    snapshot: AgentTeamsSnapshot,
    *,
    resources_sha256: str,
    skill_plan: Mapping[str, Any],
    runtime_receipt: Mapping[str, Any] | None = None,
    runtime_receipt_path: Path | None = None,
) -> dict[str, object]:
    workers = _worker_specs()
    leader_count = sum(item["role"] == "team_leader" for item in workers)
    skill_rows = skill_plan.get("skills", [])
    skill_rows = skill_rows if isinstance(skill_rows, Sequence) else []
    static_checks = {
        "official_api_version_pinned": AGENTTEAMS_API_VERSION
        == "agentteams.io/v1beta1",
        "official_commit_pinned": len(AGENTTEAMS_COMMIT) == 40,
        "one_team_leader": leader_count == 1,
        "at_least_three_domain_workers": len(workers) - leader_count >= 3,
        "policy_judge_is_explicit_worker": any(
            item["name"] == "visiondata-policy-judge" for item in workers
        ),
        "all_declared_skills_present": bool(skill_rows)
        and all(
            bool(item.get("present"))
            for item in skill_rows
            if isinstance(item, Mapping)
        ),
        "all_skill_frontmatter_names_match": bool(skill_rows)
        and all(
            item.get("name") == item.get("frontmatter_name")
            for item in skill_rows
            if isinstance(item, Mapping)
        ),
        "all_skill_descriptions_present": bool(skill_rows)
        and all(
            bool(item.get("description_present"))
            for item in skill_rows
            if isinstance(item, Mapping)
        ),
        "local_snapshot_remains_truthful": snapshot.connection_status
        == "mapped_not_connected"
        and snapshot.matrix_connected is False,
    }
    runtime_validation = validate_runtime_receipt(
        runtime_receipt, receipt_path=runtime_receipt_path
    )
    return {
        "schema_version": "visiondata-gate.agentteams-conformance.v1",
        "official_contract": {
            "repository": AGENTTEAMS_REPOSITORY,
            "version": AGENTTEAMS_VERSION,
            "commit": AGENTTEAMS_COMMIT,
            "api_version": AGENTTEAMS_API_VERSION,
            "verified_source_files": [
                "README.md",
                "docs/zh-cn/usage/resource-management.md",
                "agentteams-controller/config/crd/teams.agentteams.io.yaml",
                "agentteams-controller/config/crd/workers.agentteams.io.yaml",
                "tests/test-21-team-project-dag.sh",
                "tests/test-24-skills-management.sh",
            ],
        },
        "local_run_id": snapshot.task_id,
        "resources_sha256": resources_sha256,
        "skill_plan_sha256": _sha256_payload(skill_plan),
        "resource_summary": {
            "team": "visiondata-gate",
            "worker_resource_count": len(workers),
            "team_leader_count": leader_count,
            "domain_worker_count": len(workers) - leader_count,
            "runtime": "qwenpaw",
            "model": "qwen3.5-plus",
        },
        "static_checks": static_checks,
        "static_status": "PASS" if all(static_checks.values()) else "FAIL",
        "runtime_validation": runtime_validation,
        "overall_status": (
            "PASS"
            if all(static_checks.values()) and runtime_validation["status"] == "PASS"
            else "PARTIAL"
            if all(static_checks.values())
            else "FAIL"
        ),
        "connection_status": runtime_validation["connection_status"],
        "matrix_connected": runtime_validation["matrix_connected"],
        "required_external_inputs": [
            "Docker Desktop/Engine or a Kubernetes cluster",
            "an authorized OpenAI-compatible model endpoint and API key",
            "AgentTeams Team.status and member readiness export",
            "raw Matrix assignment event with exactly-once retry evidence",
            "observed Worker.spec.skills assignment export",
        ],
        "boundary": (
            "PASS requires hash-matched raw runtime payloads. A valid YAML resource "
            "plan or local TeamHarness trace alone never becomes an AgentTeams/Matrix receipt."
        ),
    }


def write_agentteams_v122_bundle(
    output_dir: Path,
    snapshot: AgentTeamsSnapshot,
    *,
    runtime_receipt_path: Path | None = None,
) -> dict[str, Path]:
    output_dir.mkdir(parents=True, exist_ok=True)
    resources_path = output_dir / "agentteams_v122_resources.yaml"
    skill_plan_path = output_dir / "agentteams_v122_skill_distribution.json"
    conformance_path = output_dir / "agentteams_v122_conformance.json"
    resources_path.write_text(build_agentteams_resources_yaml(), encoding="utf-8")
    skill_plan = build_skill_distribution_plan()
    skill_plan_path.write_bytes(canonical_json_bytes(skill_plan))

    runtime_receipt = None
    if runtime_receipt_path is not None and runtime_receipt_path.is_file():
        runtime_receipt = json.loads(runtime_receipt_path.read_text(encoding="utf-8"))
    conformance = build_agentteams_conformance_receipt(
        snapshot,
        resources_sha256=sha256_file(resources_path),
        skill_plan=skill_plan,
        runtime_receipt=runtime_receipt,
        runtime_receipt_path=runtime_receipt_path,
    )
    conformance_path.write_bytes(canonical_json_bytes(conformance))
    return {
        "resources": resources_path,
        "skill_distribution": skill_plan_path,
        "conformance": conformance_path,
    }


__all__ = [
    "AGENTTEAMS_API_VERSION",
    "AGENTTEAMS_COMMIT",
    "AGENTTEAMS_REPOSITORY",
    "AGENTTEAMS_VERSION",
    "build_agentteams_conformance_receipt",
    "build_agentteams_resources_yaml",
    "build_skill_distribution_plan",
    "validate_runtime_receipt",
    "write_agentteams_v122_bundle",
]
