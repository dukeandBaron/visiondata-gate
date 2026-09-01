"""Build persistent happy-path and fail-closed reviewer evidence runs."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from typing import Any

from visiondata_gate.agent_runtime import run_agentic_demo
from visiondata_gate.evidence import write_canonical_json
from visiondata_gate.package import audit_submission_zip, build_deterministic_zip
from visiondata_gate.runtime_models import RuntimeConfig, ScenarioProfile


_POSTHOC_VALIDATION_ARTIFACTS = (
    "agent_eval_intervention_receipt.json",
    "tool_fault_intervention_receipt.json",
    "tool_replay_receipt.json",
    "tool_ablation_receipt.json",
)


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _scenario_row(name: str, run: Any, archive: Path, audit: Any) -> dict[str, Any]:
    runtime_audit = json.loads(
        (run.evidence_dir / "runtime_contract_audit.json").read_text(encoding="utf-8")
    )
    skill_receipt = json.loads(
        (run.evidence_dir / "skill_qualification_receipt.json").read_text(
            encoding="utf-8"
        )
    )
    agentteams_receipt = json.loads(
        (run.evidence_dir / "agentteams_v122_conformance.json").read_text(
            encoding="utf-8"
        )
    )
    claim_scope = json.loads(
        (run.evidence_dir / "claim_scope_receipt.json").read_text(encoding="utf-8")
    )
    prohibited_claims = {
        item["claim_id"]: item for item in claim_scope["prohibited_claims"]
    }
    return {
        "scenario": name,
        "run_id": run.runtime_trace.run_id,
        "execution_config_sha256": run.runtime_trace.execution_config_sha256,
        "input_sha256": run.initial_result.input_sha256,
        "contract_id": run.initial_result.contract_id,
        "policy_version": run.initial_result.policy_version,
        "initial_decision": run.initial_result.decision.value,
        "verification_decision": run.repaired_result.decision.value,
        "completed_work_order_count": len(run.repair.completed_work_orders),
        "task_count": len(run.runtime_trace.tasks),
        "event_count": len(run.runtime_trace.events),
        "context_transfer_count": len(run.runtime_trace.context_transfers),
        "deferred_context_transfer_count": sum(
            item.status == "deferred" for item in run.runtime_trace.context_transfers
        ),
        "skill_execution_count": len(run.runtime_trace.skill_executions),
        "deferred_skill_execution_count": sum(
            item.qualification_status == "deferred"
            for item in run.runtime_trace.skill_executions
        ),
        "runtime_contract_audit": runtime_audit["status"],
        "skill_qualification": skill_receipt["status"],
        "agentteams_static_status": agentteams_receipt["static_status"],
        "agentteams_runtime_status": agentteams_receipt["runtime_validation"]["status"],
        "agentteams_connection_status": agentteams_receipt["connection_status"],
        "hosted_agentteams_connected_observed": prohibited_claims[
            "hosted_agentteams_connected"
        ]["observed"],
        "claim_scope_schema_version": claim_scope["schema_version"],
        "posthoc_validation_artifacts_present": sorted(
            name
            for name in _POSTHOC_VALIDATION_ARTIFACTS
            if (run.evidence_dir / name).exists()
        ),
        "archive": archive.name,
        "archive_sha256": _sha256(archive),
        "archive_entry_count": audit.entry_count,
        "archive_audit_ok": audit.ok,
        "archive_audit_issue_count": len(audit.issues),
    }


def build_suite(output_root: Path, *, seed: int) -> dict[str, Any]:
    output_root = output_root.resolve()
    output_root.mkdir(parents=True, exist_ok=True)
    required = (
        "agent_runtime_trace.json",
        "agentteams_mapping.json",
        "approval_handoff.json",
        "demo_summary.json",
        "initial/gate_result.json",
        "repaired/gate_result.json",
        "runtime_contract_audit.json",
        "skill_qualification_receipt.json",
        "proof_index.json",
        "agentteams_v122_resources.yaml",
        "agentteams_v122_skill_distribution.json",
        "agentteams_v122_conformance.json",
        "claim_scope_receipt.json",
    )
    scenarios = [
        (
            "happy_path",
            RuntimeConfig(
                scenario_profile=ScenarioProfile.INDUSTRIAL,
                persist_memory=False,
            ),
        ),
        (
            "missing_worker_fail_closed",
            RuntimeConfig(
                scenario_profile=ScenarioProfile.INDUSTRIAL,
                allowed_tools=["image_quality"],
                persist_memory=False,
            ),
        ),
    ]
    rows: list[dict[str, Any]] = []
    for name, config in scenarios:
        run = run_agentic_demo(
            output_root / name,
            seed=seed,
            config=config,
            memory_path=output_root / name / "runtime_memory.json",
        )
        archive = output_root / f"{name}.evidence.zip"
        build_deterministic_zip(run.evidence_dir, archive, overwrite=True)
        audit = audit_submission_zip(archive, required_paths=required)
        if not audit.ok:
            raise RuntimeError(f"scenario archive audit failed: {name}")
        rows.append(_scenario_row(name, run, archive, audit))

    by_name = {item["scenario"]: item for item in rows}
    happy = by_name["happy_path"]
    negative = by_name["missing_worker_fail_closed"]
    checks = {
        "same_seed_input": happy["input_sha256"] == negative["input_sha256"],
        "same_contract": happy["contract_id"] == negative["contract_id"],
        "same_policy": happy["policy_version"] == negative["policy_version"],
        "fault_injection_config_differs": (
            happy["execution_config_sha256"] != negative["execution_config_sha256"]
        ),
        "run_identity_does_not_collide": happy["run_id"] != negative["run_id"],
        "happy_path_repair_pass": (
            happy["initial_decision"] == "RECAPTURE"
            and happy["verification_decision"] == "PASS"
        ),
        "missing_worker_stays_deferred": (
            negative["initial_decision"] == "DEFER"
            and negative["verification_decision"] == "DEFER"
        ),
        "missing_worker_has_no_fake_repair": (
            negative["completed_work_order_count"] == 0
        ),
        "negative_context_is_deferred": (
            negative["deferred_context_transfer_count"] > 0
        ),
        "negative_skill_is_deferred": (negative["deferred_skill_execution_count"] > 0),
        "both_runtime_audits_pass": all(
            item["runtime_contract_audit"] == "PASS" for item in rows
        ),
        "both_skill_qualifications_pass": all(
            item["skill_qualification"] == "PASS" for item in rows
        ),
        "both_agentteams_static_contracts_pass": all(
            item["agentteams_static_status"] == "PASS" for item in rows
        ),
        "both_agentteams_runtimes_remain_open": all(
            item["agentteams_runtime_status"] == "OPEN"
            and item["agentteams_connection_status"] == "mapped_not_connected"
            for item in rows
        ),
        "claim_scope_blocks_false_connectivity": all(
            item["claim_scope_schema_version"]
            == "visiondata-gate.claim-scope-receipt.v1"
            and item["hosted_agentteams_connected_observed"] is False
            for item in rows
        ),
        "normal_runs_exclude_posthoc_validation": all(
            not item["posthoc_validation_artifacts_present"] for item in rows
        ),
        "both_archives_pass": all(item["archive_audit_ok"] for item in rows),
    }
    payload = {
        "schema_version": "visiondata-gate.reviewer-scenario-suite.v1",
        "seed": seed,
        "status": "PASS" if all(checks.values()) else "PARTIAL",
        "checks": checks,
        "scenarios": rows,
        "boundary": (
            "This suite compares deterministic synthetic runtime scenarios under one "
            "frozen contract. Posthoc mutation, tool-fault, replay, and ablation receipts "
            "remain separate explicit validation commands. The suite does not prove "
            "production incident rates, customer validation, or hosted AgentTeams connectivity."
        ),
    }
    write_canonical_json(output_root / "scenario_suite_receipt.json", payload)
    return payload


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--seed", type=int, default=20260812)
    args = parser.parse_args()
    payload = build_suite(args.output, seed=args.seed)
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    return 0 if payload["status"] == "PASS" else 2


if __name__ == "__main__":
    raise SystemExit(main())
