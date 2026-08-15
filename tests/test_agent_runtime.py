from __future__ import annotations

import json

from visiondata_gate.agent_runtime import build_task_graph, run_agentic_demo
from visiondata_gate.agentteams_contract import build_agentteams_contract
from visiondata_gate.contracts import GateDecision
from visiondata_gate.knowledge import retrieve_knowledge
from visiondata_gate.model_backends import build_council_with_backend
from visiondata_gate.runtime_canvas import build_runtime_canvas
from visiondata_gate.runtime_models import (
    ModelBackendKind,
    RuntimeConfig,
    RuntimeStatus,
    ScenarioProfile,
)


def test_task_graph_has_explicit_workers_dependencies_and_permissions() -> None:
    tasks = build_task_graph("initial")
    ids = {task.task_id for task in tasks}

    assert len(tasks) == 10
    assert {
        "initial.tool.image_quality",
        "initial.tool.duplicate_leakage",
        "initial.tool.annotation_integrity",
        "initial.tool.coverage_matrix",
    } <= ids
    council = next(task for task in tasks if task.task_id == "initial.council")
    judge = next(task for task in tasks if task.task_id == "initial.judge")
    assert len(council.dependencies) == 4
    assert judge.dependencies == ["initial.council"]
    assert all(task.permission_scope for task in tasks)


def test_task_graph_adds_optional_tool_task_for_non_generic_scenario() -> None:
    optional = build_task_graph("initial", include_optional=True)
    assert len(optional) == 11
    assert any(task.task_id == "initial.tool.governance_audit" for task in optional)


def test_agentteams_contract_has_manager_leader_workers_and_reusable_skills() -> None:
    snapshot = build_agentteams_contract(
        ScenarioProfile.INDUSTRIAL,
        allowed_tools=[
            "image_quality",
            "duplicate_leakage",
            "annotation_integrity",
            "coverage_matrix",
        ],
        include_optional=True,
        run_id="test",
    )

    assert snapshot.connection_status == "mapped_not_connected"
    assert snapshot.matrix_connected is False
    assert snapshot.manager_agent_id == "manager.gate"
    assert snapshot.leader_agent_id == "leader.release-gate"
    assert len(snapshot.worker_agent_ids) >= 4
    assert {item.role_type for item in snapshot.identities} >= {
        "manager",
        "team_leader",
        "worker",
        "reviewer",
        "judge",
    }
    assert len(snapshot.skills) >= 5
    assert all(
        skill.input_contract and skill.output_contract for skill in snapshot.skills
    )


def test_semantic_retrieval_returns_project_policy_sources() -> None:
    hits = retrieve_knowledge("跨 split 重复泄漏后如何发布和复验", limit=6)

    assert hits
    assert any(item.scope == "duplicate_leakage" for item in hits)
    assert all(item.source.startswith("project-policy://") for item in hits)


def test_remote_model_is_blocked_without_permission_and_falls_back() -> None:
    config = RuntimeConfig(
        backend=ModelBackendKind.OPENAI_COMPATIBLE,
        model="unreachable-test-model",
        endpoint="http://example.invalid/v1/chat/completions",
        allow_remote_model=False,
    )

    built = build_council_with_backend(config, [], [], {}, [])

    assert built.fallback_used is True
    assert built.backend_connected is False
    assert built.model_calls == 0
    assert "deterministic-fallback" in built.council.backend


def test_agentic_demo_runs_router_workers_judge_memory_and_delivery(tmp_path) -> None:
    run = run_agentic_demo(
        tmp_path / "run",
        seed=20260810,
        config=RuntimeConfig(),
        memory_path=tmp_path / "memory" / "runtime.json",
    )

    assert run.initial_result.decision is GateDecision.RECAPTURE
    assert len(run.initial_result.findings) == 12
    assert run.repaired_result.decision is GateDecision.PASS
    assert run.evaluation.f1 == 1.0
    assert run.evaluation.post_repair_correct_pass is True
    assert run.runtime_trace.status is RuntimeStatus.SUCCESS
    assert run.runtime_trace.tool_call_count == 8
    assert run.runtime_trace.model_call_count == 0
    assert len(run.runtime_trace.tasks) == 22
    assert len(run.runtime_trace.events) >= 30
    assert {event.stage.value for event in run.runtime_trace.events} >= {
        "router",
        "planner",
        "tool",
        "council",
        "judge",
        "repair",
        "delivery",
    }
    assert len(run.runtime_trace.memory.long_term) == 2
    assert run.runtime_trace_path.is_file()
    assert run.memory_path.is_file()
    summary = json.loads(run.summary_path.read_text(encoding="utf-8"))
    assert summary["runtime"]["event_count"] == len(run.runtime_trace.events)
    assert (
        summary["runtime"]["task_binding_count"]
        == run.runtime_trace.agentteams.task_binding_count
    )
    assert run.runtime_trace.agentteams is not None
    assert run.runtime_trace.agentteams.task_binding_count == len(
        run.runtime_trace.tasks
    )
    assert run.evidence_dir.joinpath("agentteams_mapping.json").is_file()
    assert run.evidence_dir.joinpath("approval_handoff.json").is_file()
    assert run.evidence_dir.joinpath("tool_ablation_receipt.json").is_file()
    assert run.runtime_trace.approval_handoff is not None
    assert run.runtime_trace.approval_handoff.mode == "external_authorization_required"
    assert run.runtime_trace.approval_handoff.status == "blocked"
    assert len(run.runtime_trace.agentteams.context_flow) >= 5
    assert run.runtime_trace.memory.semantic
    assert run.runtime_trace.memory.semantic[0].source_version
    assert all(event.collaboration.get("team_id") for event in run.runtime_trace.events)
    assert any(
        item.source_task_id == "system.repair" and item.task_id == "verification.intake"
        for item in run.runtime_trace.context_transfers
    )
    assert len(run.runtime_trace.skill_executions) == len(run.runtime_trace.tasks)
    assert all(
        item.qualification_status == "qualified"
        for item in run.runtime_trace.skill_executions
    )
    assert run.evidence_dir.joinpath("skill_qualification_receipt.json").is_file()

    canvas = build_runtime_canvas(run.runtime_trace)
    assert '<canvas id="runtimeCanvas"' in canvas
    assert "Router · Workers · Model · Tools · Judge · Memory" in canvas
    assert run.runtime_trace.run_id in canvas
    assert "<script>" in canvas
    assert "AgentTeams" in canvas
    assert "mapped_not_connected" in canvas


def test_missing_worker_permission_stays_deferred_without_fake_repair(tmp_path) -> None:
    run = run_agentic_demo(
        tmp_path / "restricted",
        seed=20260811,
        config=RuntimeConfig(
            allowed_tools=["image_quality"],
            persist_memory=False,
        ),
    )

    assert run.initial_result.decision is GateDecision.DEFER
    assert run.repaired_result.decision is GateDecision.DEFER
    assert run.runtime_trace.status is RuntimeStatus.WARNING
    assert run.repair.completed_work_orders == []
    assert run.repair.output_root == run.dataset_paths["batch_root"]
    assert any(task.status is RuntimeStatus.SKIPPED for task in run.runtime_trace.tasks)
    assert any(
        event.status is RuntimeStatus.WARNING and event.stage.value == "repair"
        for event in run.runtime_trace.events
    )
    assert any(
        item.qualification_status == "deferred"
        and item.rollback_action != "none_required"
        for item in run.runtime_trace.skill_executions
    )
    assert run.evidence_dir.joinpath("approval_handoff.json").is_file()
