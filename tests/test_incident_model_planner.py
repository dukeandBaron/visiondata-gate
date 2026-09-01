from __future__ import annotations

import hashlib
import json
import threading
from collections.abc import Iterator
from contextlib import contextmanager
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any

import pytest

from visiondata_gate.demo_fixtures import build_fixture_industrial_incident_request
from visiondata_gate.evidence import canonical_json_bytes
from visiondata_gate.incident_model_planner import (
    DEEPSEEK_API_HOST,
    DEEPSEEK_OPENAI_BASE_URL,
    DEFAULT_INCIDENT_MODEL_ENDPOINT,
    DEFAULT_INCIDENT_MODEL_NAME,
    IncidentModelMode,
    IncidentModelPlanner,
    IncidentModelPlannerConfig,
    incident_model_planner_from_environment,
    verify_incident_model_planner_receipt,
)
from visiondata_gate.incident_runtime_profile import IncidentRuntimeProfile
from visiondata_gate.industrial_incident import (
    IndustrialGateContext,
    build_industrial_incident_case,
    verify_industrial_incident_case,
)


def _digest(label: str) -> str:
    return hashlib.sha256(label.encode("utf-8")).hexdigest()


def _proposal(contract: dict[str, Any]) -> dict[str, Any]:
    hypothesis_id = contract["allowed_hypothesis_ids"][0]
    missing_ref = contract["allowed_missing_evidence_ids"][0]
    receipt_id = contract["available_receipt_ids"][0]
    worker_role = list(contract["allowed_worker_reason_codes"])[-1]
    reason_code = contract["allowed_worker_reason_codes"][worker_role][0]
    return {
        "schema_version": "visiondata-gate.incident-model-plan.v1",
        "decision_authority": "none",
        "hypotheses_to_discriminate": [hypothesis_id],
        "missing_evidence": [
            {
                "evidence_ref": missing_ref,
                "reason": "This evidence can discriminate the open hypotheses.",
                "related_hypothesis_ids": [hypothesis_id],
            }
        ],
        "recommended_workers": [
            {
                "worker_role": worker_role,
                "reason_codes": [reason_code],
                "supporting_receipt_ids": [receipt_id],
            }
        ],
        "supporting_receipt_ids": [receipt_id],
        "counterevidence_questions": [
            "What observation would contradict the leading explanation?"
        ],
        "summary": "Advisory evidence-gap priority only.",
        "root_cause_claimed": False,
        "capa_approval_claimed": False,
        "production_release_recommended": False,
        "equipment_control_requested": False,
    }


class _PlannerHandler(BaseHTTPRequestHandler):
    server: Any

    def log_message(self, *_args: object) -> None:
        return None

    def do_POST(self) -> None:
        length = int(self.headers["Content-Length"])
        request = json.loads(self.rfile.read(length))
        self.server.path_seen = self.path
        self.server.authorization_seen = self.headers.get("Authorization")
        self.server.request_seen = request
        if self.server.response_status != 200:
            raw = b'{"error":"fixture failure"}'
            self.send_response(self.server.response_status)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(raw)))
            self.end_headers()
            self.wfile.write(raw)
            return
        user = json.loads(request["messages"][1]["content"])
        contract = user["planner_contract"]
        response_proposal = _proposal(contract)
        if self.server.mutate_response is not None:
            self.server.mutate_response(response_proposal)
        content = json.dumps(response_proposal)
        payload = {
            "model": self.server.model_id,
            "usage": {
                "prompt_tokens": 120,
                "completion_tokens": 80,
                "total_tokens": 200,
            },
            "choices": [{"message": {"content": content}}],
        }
        raw = json.dumps(payload).encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(raw)))
        self.end_headers()
        self.wfile.write(raw)


@contextmanager
def _server(
    *,
    mutate_response: Any = None,
    response_status: int = 200,
) -> Iterator[tuple[ThreadingHTTPServer, str]]:
    server = ThreadingHTTPServer(("127.0.0.1", 0), _PlannerHandler)
    server.model_id = DEFAULT_INCIDENT_MODEL_NAME
    server.mutate_response = mutate_response
    server.response_status = response_status
    server.path_seen = None
    server.authorization_seen = None
    server.request_seen = None
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        endpoint = f"http://127.0.0.1:{server.server_port}/gateway/v1/chat/completions"
        yield server, endpoint
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)


def _planner_inputs() -> dict[str, Any]:
    return {
        "case_id": "incident_0123456789abcdef0123",
        "evidence_bundle_sha256": _digest("evidence-bundle"),
        "trigger_kind": "NG_RATE_DRIFT",
        "candidate_issues": [
            {
                "issue_code": "SIGNAL_BAD",
                "severity": "BLOCKING",
                "evidence_source": "opcua-offline-snapshot",
                "summary": "Signal quality is not usable.",
                "worker_role": "SignalIntegrityAgent",
            },
            {
                "issue_code": "TRACE_MISMATCH",
                "severity": "BLOCKING",
                "evidence_source": "offline-vision-run-receipt",
                "summary": "Identifiers do not correlate.",
                "worker_role": "TraceabilityAgent",
            },
        ],
        "candidate_hypotheses": [
            {
                "hypothesis_id": "H-EVIDENCE-FAILURE",
                "status": "SUPPORTED",
                "statement": "Evidence qualification may have failed.",
                "unresolved_evidence_refs": ["opcua-offline-snapshot"],
                "next_discriminating_test": "Re-export the snapshot.",
            }
        ],
        "available_receipt_ids": [
            "opcua-offline-snapshot",
            "offline-vision-run-receipt",
        ],
        "allowed_missing_evidence_ids": ["opcua-offline-snapshot"],
        "worker_reason_codes": {
            "SignalIntegrityAgent": ["SIGNAL_BAD"],
            "TraceabilityAgent": ["TRACE_MISMATCH"],
        },
        "remaining_worker_budget": 2,
    }


def _gate_context() -> IndustrialGateContext:
    return IndustrialGateContext(
        task_id="task_0123456789abcdef",
        gate_final_decision="QUARANTINE",
        task_evidence_sha256=_digest("task-evidence"),
        industrial_delivery_sha256=_digest("industrial-delivery"),
        source_profile_sha256=_digest("source-profile"),
        source_authorization_event_sha256=_digest("source-authorization"),
        source_kind="synthetic_demo",
        source_authorization_status="NOT_APPLICABLE",
        dynamic_response_count=3,
        open_work_order_count=2,
        remediation_plan_ids=["plan-containment", "plan-recapture"],
        model_call_count=0,
    )


def test_environment_defaults_to_off_without_reading_a_key() -> None:
    default_config = IncidentModelPlannerConfig()
    assert DEEPSEEK_OPENAI_BASE_URL == "https://api.deepseek.com"
    assert DEFAULT_INCIDENT_MODEL_ENDPOINT == (
        "https://api.deepseek.com/chat/completions"
    )
    assert default_config.remote_endpoint_hosts == [DEEPSEEK_API_HOST]
    assert default_config.allow_remote_model is False
    assert incident_model_planner_from_environment({}) is None
    assert (
        incident_model_planner_from_environment(
            {"VISIONDATA_INCIDENT_MODEL_API_KEY": "YOUR_API_KEY"}
        )
        is None
    )


def test_remote_mode_requires_explicit_authorization_and_key() -> None:
    with pytest.raises(ValueError, match="not authorized"):
        incident_model_planner_from_environment(
            {"VISIONDATA_INCIDENT_MODEL_MODE": "shadow"}
        )

    with pytest.raises(ValueError, match="requires VISIONDATA_INCIDENT_MODEL_API_KEY"):
        incident_model_planner_from_environment(
            {
                "VISIONDATA_INCIDENT_MODEL_MODE": "shadow",
                "VISIONDATA_INCIDENT_MODEL_ALLOW_REMOTE": "true",
                "VISIONDATA_INCIDENT_MODEL_ENDPOINT": (DEFAULT_INCIDENT_MODEL_ENDPOINT),
            }
        )


def test_gated_local_contract_applies_only_validated_worker_priority() -> None:
    with _server() as (server, endpoint):
        planner = IncidentModelPlanner(
            IncidentModelPlannerConfig(
                mode=IncidentModelMode.GATED,
                endpoint=endpoint,
                model=DEFAULT_INCIDENT_MODEL_NAME,
                max_recommended_workers=2,
            ),
            api_key="fixture-secret",
        )
        result = planner.plan(**_planner_inputs())

    verify_incident_model_planner_receipt(result.receipt)
    assert result.receipt.status == "ACCEPTED"
    assert result.receipt.connection_status == "CONTRACT_CONNECTED_LOCAL_TEST"
    assert result.receipt.gating_effect == "PRIORITY_APPLIED"
    assert result.applied_worker_order == ("TraceabilityAgent",)
    assert result.receipt.model_call_count == 1
    assert result.receipt.usage.total_tokens == 200
    assert result.receipt.usage.cost_status == "TOKENS_REPORTED_COST_NOT_COMPUTED"
    assert result.receipt.secrets_retained is False
    assert "fixture-secret" not in result.receipt.model_dump_json()
    assert server.path_seen == "/gateway/v1/chat/completions"
    assert server.authorization_seen == "Bearer fixture-secret"
    assert server.request_seen["model"] == DEFAULT_INCIDENT_MODEL_NAME
    assert server.request_seen["temperature"] == 0.0
    assert server.request_seen["max_tokens"] == 900


def test_planner_receipt_seals_the_preplanning_memory_retrieval_digest() -> None:
    memory_input_sha256 = _digest("governed-memory-input")
    retrieval_sha256 = _digest("governed-memory-retrieval")
    governed_memory = {
        "schema_version": "visiondata-gate.governed-memory-planning-input.v1",
        "input_sha256": memory_input_sha256,
        "retrieval_receipt_sha256": retrieval_sha256,
        "query_scope": {
            "site_id": "factory-a-line-01",
            "product_family": None,
            "line_id": "fixture-line-A",
            "station_id": None,
            "camera_id": None,
        },
        "accepted_historical_references": [
            {
                "memory_id": "memory_0123456789abcdef0123",
                "memory_sha256": _digest("accepted-memory"),
                "memory_type": "INVESTIGATION_HINT",
                "pattern": "historical recipe drift pattern",
                "recommended_first_check": "verify current recipe evidence",
                "avoid_first_action": "do not claim root cause",
                "source_case_ids": ["incident_0123456789abcdefabcd"],
                "historical_reference_only": True,
                "may_set_current_case_fact": False,
                "current_case_fact_eligible": False,
            }
        ],
        "selected_memory_count": 1,
        "rejected_memory_count": 2,
        "allowed_effects": [
            "MISSING_EVIDENCE_PRIORITIZATION",
            "COUNTEREVIDENCE_QUESTION",
            "ALLOWLISTED_WORKER_PRIORITY",
        ],
        "current_case_fact_authority": "none",
        "root_cause_authority": "none",
        "decision_authority": "none",
        "policy_judge_input": False,
        "machine_action_permitted": False,
    }
    inputs = _planner_inputs()
    inputs["governed_memory"] = governed_memory
    inputs["available_receipt_ids"].append(
        f"governed-memory-retrieval:{retrieval_sha256}"
    )

    with _server() as (server, endpoint):
        planner = IncidentModelPlanner(
            IncidentModelPlannerConfig(
                mode=IncidentModelMode.GATED,
                endpoint=endpoint,
            )
        )
        result = planner.plan(**inputs)

    verify_incident_model_planner_receipt(result.receipt)
    contract = json.loads(server.request_seen["messages"][1]["content"])[
        "planner_contract"
    ]
    assert contract["governed_memory"] == governed_memory
    assert result.receipt.governed_memory_input_sha256 == memory_input_sha256
    assert result.receipt.governed_memory_retrieval_receipt_sha256 == retrieval_sha256
    assert (
        result.receipt.planner_input_sha256
        == hashlib.sha256(canonical_json_bytes(contract)).hexdigest()
    )
    assert result.receipt.proposal is not None
    assert result.receipt.proposal.root_cause_claimed is False
    assert result.receipt.proposal.production_release_recommended is False


def test_shadow_plan_is_recorded_but_cannot_change_priority() -> None:
    with _server() as (_server_instance, endpoint):
        planner = IncidentModelPlanner(
            IncidentModelPlannerConfig(
                mode=IncidentModelMode.SHADOW,
                endpoint=endpoint,
            )
        )
        result = planner.plan(**_planner_inputs())

    assert result.receipt.status == "ACCEPTED"
    assert result.receipt.gating_effect == "SHADOW_ONLY"
    assert result.receipt.recommended_worker_order == ["TraceabilityAgent"]
    assert result.receipt.applied_worker_order == []
    assert result.applied_worker_order == ()


def test_unknown_receipt_id_rejects_entire_plan_and_falls_back() -> None:
    def mutate(payload: dict[str, Any]) -> None:
        payload["supporting_receipt_ids"] = ["invented-receipt"]

    with _server(mutate_response=mutate) as (_server_instance, endpoint):
        planner = IncidentModelPlanner(
            IncidentModelPlannerConfig(
                mode=IncidentModelMode.GATED,
                endpoint=endpoint,
            )
        )
        result = planner.plan(**_planner_inputs())

    assert result.receipt.status == "REJECTED"
    assert result.receipt.connection_status == "CONTRACT_CONNECTED_LOCAL_TEST"
    assert result.receipt.gating_effect == "DETERMINISTIC_FALLBACK"
    assert "UNKNOWN_SUPPORTING_RECEIPT_ID" in result.receipt.validation_errors
    assert result.receipt.proposal is None
    assert result.applied_worker_order == ()


def test_transport_failure_cannot_affect_worker_priority() -> None:
    with _server(response_status=503) as (_server_instance, endpoint):
        planner = IncidentModelPlanner(
            IncidentModelPlannerConfig(
                mode=IncidentModelMode.GATED,
                endpoint=endpoint,
                max_retries=0,
            )
        )
        result = planner.plan(**_planner_inputs())

    assert result.receipt.status == "TRANSPORT_FAILED"
    assert result.receipt.connection_status == "REAL_BACKEND_NOT_CONNECTED"
    assert result.receipt.gating_effect == "DETERMINISTIC_FALLBACK"
    assert result.receipt.transport_receipt is not None
    assert result.receipt.transport_receipt.status == "HTTP_ERROR"
    assert result.applied_worker_order == ()


def test_context_budget_boundary_is_auditable_and_overflow_makes_zero_calls() -> None:
    inputs = _planner_inputs()
    inputs["candidate_issues"][0]["summary"] = "x" * 8_000
    probe = IncidentModelPlanner(
        IncidentModelPlannerConfig(
            mode=IncidentModelMode.SHADOW,
            endpoint="http://127.0.0.1:9/chat/completions",
            context_budget_tokens=32_768,
        )
    )
    estimated = probe.estimate_input_tokens(**inputs)
    assert 1_024 < estimated < 32_768

    with _server() as (allowed_server, endpoint):
        allowed = IncidentModelPlanner(
            IncidentModelPlannerConfig(
                mode=IncidentModelMode.SHADOW,
                endpoint=endpoint,
                context_budget_tokens=estimated,
            )
        ).plan(**inputs)
    assert allowed_server.request_seen is not None
    assert allowed.receipt.model_call_count == 1
    assert allowed.receipt.estimated_input_tokens == estimated
    assert allowed.receipt.context_budget_tokens == estimated
    assert allowed.receipt.context_truncated is False

    with _server() as (blocked_server, endpoint):
        blocked = IncidentModelPlanner(
            IncidentModelPlannerConfig(
                mode=IncidentModelMode.SHADOW,
                endpoint=endpoint,
                context_budget_tokens=estimated - 1,
            )
        ).plan(**inputs)
    assert blocked_server.request_seen is None
    assert blocked.receipt.model_call_count == 0
    assert blocked.receipt.gating_effect == "DETERMINISTIC_FALLBACK"
    assert blocked.receipt.validation_errors == ["CONTEXT_BUDGET_EXCEEDED"]
    assert blocked.receipt.estimated_input_tokens == estimated
    assert blocked.receipt.context_budget_tokens == estimated - 1
    assert blocked.receipt.context_truncated is False


def test_replay_is_network_free_and_deterministic(tmp_path: Path) -> None:
    inputs = _planner_inputs()
    contract = {
        "allowed_hypothesis_ids": ["H-EVIDENCE-FAILURE"],
        "allowed_missing_evidence_ids": ["opcua-offline-snapshot"],
        "available_receipt_ids": [
            "offline-vision-run-receipt",
            "opcua-offline-snapshot",
        ],
        "allowed_worker_reason_codes": {
            "SignalIntegrityAgent": ["SIGNAL_BAD"],
            "TraceabilityAgent": ["TRACE_MISMATCH"],
        },
    }
    replay_path = tmp_path / "planner-response.json"
    replay_path.write_text(
        json.dumps(_proposal(contract), sort_keys=True),
        encoding="utf-8",
    )
    planner = IncidentModelPlanner(
        IncidentModelPlannerConfig(
            mode=IncidentModelMode.REPLAY,
            replay_path=str(replay_path),
            max_recommended_workers=2,
        )
    )

    first = planner.plan(**inputs)
    second = planner.plan(**inputs)

    assert first.receipt.connection_status == "REPLAY_ONLY"
    assert first.receipt.model_call_count == 0
    assert first.receipt.usage.cost_status == "NOT_APPLICABLE_REPLAY"
    assert first.receipt.transport_receipt is None
    assert first.receipt.receipt_sha256 == second.receipt.receipt_sha256
    assert first.applied_worker_order == ("TraceabilityAgent",)


def test_incident_case_binds_model_receipt_without_granting_authority() -> None:
    with _server() as (_server_instance, endpoint):
        planner = IncidentModelPlanner(
            IncidentModelPlannerConfig(
                mode=IncidentModelMode.GATED,
                endpoint=endpoint,
            ),
            api_key="fixture-secret",
        )
        request = build_fixture_industrial_incident_request().model_copy(
            update={
                "runtime_profile": IncidentRuntimeProfile(
                    model_profile_id="deepseek-chat",
                    planner_mode=IncidentModelMode.GATED,
                )
            }
        )
        case = build_industrial_incident_case(
            request,
            _gate_context(),
            model_planner=planner,
        )

    verify_industrial_incident_case(case)
    assert case.model_planner_receipt is not None
    assert case.model_planner_receipt.status == "ACCEPTED"
    assert case.external_model_call_count == 1
    assert case.planning_mode == "bounded_model_planner_loop_v3"
    assert case.root_cause_status == "NOT_ESTABLISHED"
    assert case.production_release_allowed is False
    assert case.machine_write_permitted is False
    assert case.direct_equipment_control_permitted is False
    assert "fixture-secret" not in case.model_dump_json()
    assert any(
        item.agent_role == "EvidenceGapCounterevidencePlannerAgent"
        for item in case.agent_actions
    )


def test_checked_in_replay_matches_the_frozen_fixture_contract() -> None:
    replay_path = (
        Path(__file__).resolve().parents[1]
        / "examples"
        / "incident_model_replay.fixture.json"
    )
    planner = IncidentModelPlanner(
        IncidentModelPlannerConfig(
            mode=IncidentModelMode.REPLAY,
            replay_path=str(replay_path),
        )
    )
    request = build_fixture_industrial_incident_request().model_copy(
        update={
            "runtime_profile": IncidentRuntimeProfile(
                model_profile_id="deepseek-replay",
                planner_mode=IncidentModelMode.REPLAY,
            )
        }
    )
    case = build_industrial_incident_case(
        request,
        _gate_context(),
        model_planner=planner,
    )

    assert case.model_planner_receipt is not None
    assert case.model_planner_receipt.status == "ACCEPTED"
    assert case.model_planner_receipt.connection_status == "REPLAY_ONLY"
    assert case.model_planner_receipt.model_call_count == 0


def test_legacy_v5_case_without_optional_planner_field_still_verifies() -> None:
    current = build_industrial_incident_case(
        build_fixture_industrial_incident_request(),
        _gate_context(),
    )
    legacy_payload = current.model_dump(mode="json")
    legacy_payload["schema_version"] = "visiondata-gate.industrial-incident-case.v5"
    for field_name in (
        "parent_belief_revision_receipt",
        "worker_execution_plan_receipt",
        "council_arbitration_receipt",
        "autonomy_guard_receipt",
    ):
        legacy_payload.pop(field_name)
    legacy_payload.pop("model_planner_receipt")
    legacy_payload.pop("case_sha256")
    legacy_sha256 = hashlib.sha256(canonical_json_bytes(legacy_payload)).hexdigest()
    legacy_payload["case_sha256"] = legacy_sha256

    loaded = type(current).model_validate(legacy_payload)

    assert loaded.model_planner_receipt is None
    verify_industrial_incident_case(loaded)
