from __future__ import annotations

import hashlib
import io
import json
import zipfile
from collections.abc import Iterator
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from visiondata_gate.api import create_app
from visiondata_gate.contracts import GateDecision
from visiondata_gate.demo_fixtures import build_fixture_industrial_incident_request
from visiondata_gate.evidence import canonical_json_bytes, write_canonical_json
from visiondata_gate.incident_commands import (
    IncidentCommandKind,
    IncidentCommandStatus,
    incident_command_id,
)
from visiondata_gate.industrial_incident import (
    IncidentHumanDecision,
    IndustrialIncidentDecisionRequest,
)
from visiondata_gate.product_models import (
    CreateProjectRequest,
    CreateTaskRequest,
    CreateUserRequest,
    CreateWorkspaceRequest,
    TaskRecord,
)
from visiondata_gate.product_service import (
    ArtifactUnavailableError,
    IncidentCommandUncertainError,
    IncidentIdempotencyConflictError,
    ProductService,
)
from visiondata_gate.task_store import ConflictError, IncidentCommandStateConflict
from visiondata_gate.worker_selection import AgentBehaviorReceiptV1
from tests.support.product_run_stub import (
    LifecycleProductRunner,
    make_product_lifecycle_stub_runner,
)


def _setup(service: ProductService) -> tuple[str, str]:
    user = service.create_user(CreateUserRequest(display_name="Command Owner"))
    workspace = service.create_workspace(
        CreateWorkspaceRequest(name="Command Tests", owner_user_id=user.user_id)
    )
    project = service.create_project(
        user.user_id,
        CreateProjectRequest(
            workspace_id=workspace.workspace_id,
            name="Incident Command Gate",
        ),
    )
    return user.user_id, project.project_id


def _fake_runner(
    final_decision: GateDecision = GateDecision.PASS,
) -> LifecycleProductRunner:
    """Return a contract-valid lifecycle stub, never Agent E2E evidence."""

    return make_product_lifecycle_stub_runner(final_decision)


@pytest.fixture
def incident_environment(
    tmp_path: Path,
) -> Iterator[tuple[ProductService, str, TaskRecord]]:
    service = ProductService(
        tmp_path / "product",
        runner=_fake_runner(),
        recover_interrupted=False,
    )
    actor, project_id = _setup(service)
    task = service.create_task(
        actor,
        CreateTaskRequest(
            project_id=project_id,
            goal="为命令幂等、恢复和资源绑定测试建立已完成父任务。",
        ),
        auto_start=False,
    )
    task = service.run_task_sync(task.task_id)
    try:
        yield service, actor, task
    finally:
        service.close(wait=True)


def _command_id(
    task_id: str,
    operation: IncidentCommandKind,
    idempotency_key: str,
    *,
    target_case_id: str | None = None,
) -> str:
    return incident_command_id(
        task_id=task_id,
        operation=operation,
        target_case_id=target_case_id,
        idempotency_key=idempotency_key,
    )


def _decision_request(case_sha256: str) -> IndustrialIncidentDecisionRequest:
    return IndustrialIncidentDecisionRequest(
        bound_case_sha256=case_sha256,
        decision=IncidentHumanDecision.CONTINUE_HOLD,
        note="已复核命令测试证据，继续 HOLD 并仅以新证据创建下一版本。",
        operator_attests_reviewed_evidence=True,
    )


def test_create_same_key_and_request_replays_the_same_case(
    incident_environment: tuple[ProductService, str, TaskRecord],
) -> None:
    service, actor, task = incident_environment
    request = build_fixture_industrial_incident_request()
    key = "incident-create-replay-001"

    first = service.create_industrial_incident_case(
        actor,
        task.task_id,
        request,
        idempotency_key=key,
    )
    replay = service.create_industrial_incident_case(
        actor,
        task.task_id,
        request,
        idempotency_key=key,
    )

    assert replay.case_id == first.case_id
    assert replay.case_sha256 == first.case_sha256
    assert [
        item.case_id
        for item in service.list_industrial_incident_cases(actor, task.task_id)
    ] == [first.case_id]
    command = service.get_incident_command_receipt(
        actor,
        task.task_id,
        _command_id(task.task_id, IncidentCommandKind.CREATE_CASE, key),
    )
    assert command.status is IncidentCommandStatus.COMPLETED
    assert command.resource_id == first.case_id
    assert command.resource_sha256 == first.case_sha256


def test_same_key_with_a_different_request_is_an_idempotency_conflict(
    incident_environment: tuple[ProductService, str, TaskRecord],
) -> None:
    service, actor, task = incident_environment
    key = "incident-create-conflict-001"
    first = service.create_industrial_incident_case(
        actor,
        task.task_id,
        build_fixture_industrial_incident_request(revision=1),
        idempotency_key=key,
    )

    with pytest.raises(IncidentIdempotencyConflictError) as captured:
        service.create_industrial_incident_case(
            actor,
            task.task_id,
            build_fixture_industrial_incident_request(revision=2),
            idempotency_key=key,
        )

    assert captured.value.code == "incident_idempotency_conflict"
    assert [
        item.case_id
        for item in service.list_industrial_incident_cases(actor, task.task_id)
    ] == [first.case_id]


def test_admission_without_terminal_blocks_replay_and_creates_no_case(
    incident_environment: tuple[ProductService, str, TaskRecord],
) -> None:
    service, actor, task = incident_environment
    request = build_fixture_industrial_incident_request()
    key = "incident-admission-only-001"
    admission, terminal, admitted_now = service._admit_incident_command(
        task=task,
        actor_user_id=actor,
        operation=IncidentCommandKind.CREATE_CASE,
        target_case_id=None,
        idempotency_key=key,
        request=request,
        expected_case_sha256=None,
    )
    command_root = service._incident_command_root(task, admission.command_id)

    assert admitted_now is True
    assert terminal is None
    assert (command_root / "admission.json").is_file()
    assert not (command_root / "terminal.json").exists()
    assert service.list_industrial_incident_cases(actor, task.task_id) == []

    with pytest.raises(IncidentCommandUncertainError) as captured:
        service.create_industrial_incident_case(
            actor,
            task.task_id,
            request,
            idempotency_key=key,
        )

    assert captured.value.command_id == admission.command_id
    assert service.list_industrial_incident_cases(actor, task.task_id) == []
    receipt = service.get_incident_command_receipt(
        actor,
        task.task_id,
        admission.command_id,
    )
    assert receipt.status is IncidentCommandStatus.UNCERTAIN
    assert receipt.resource_id is None


@pytest.mark.parametrize("tamper_kind", ["terminal_resource_sha", "case_resource"])
def test_completed_command_resource_tampering_fails_closed(
    incident_environment: tuple[ProductService, str, TaskRecord],
    tamper_kind: str,
) -> None:
    service, actor, task = incident_environment
    request = build_fixture_industrial_incident_request()
    key = f"incident-resource-tamper-{tamper_kind}"
    case = service.create_industrial_incident_case(
        actor,
        task.task_id,
        request,
        idempotency_key=key,
    )
    command_id = _command_id(task.task_id, IncidentCommandKind.CREATE_CASE, key)

    if tamper_kind == "terminal_resource_sha":
        terminal_path = (
            service._incident_command_root(task, command_id) / "terminal.json"
        )
        terminal_payload = json.loads(terminal_path.read_text(encoding="utf-8"))
        terminal_payload["resource_sha256"] = "f" * 64
        terminal_stable = dict(terminal_payload)
        terminal_stable.pop("terminal_sha256")
        terminal_payload["terminal_sha256"] = hashlib.sha256(
            canonical_json_bytes(terminal_stable)
        ).hexdigest()
        write_canonical_json(terminal_path, terminal_payload)
        expected_error = "another terminal outcome"
        expected_exception = IncidentCommandStateConflict
    else:
        case_path = service._incident_case_root(task, case.case_id) / "case.json"
        case_payload = json.loads(case_path.read_text(encoding="utf-8"))
        case_payload["recommendation_reason"] = "tampered resource"
        write_canonical_json(case_path, case_payload)
        expected_error = "case failed integrity validation"
        expected_exception = ArtifactUnavailableError

    with pytest.raises(expected_exception, match=expected_error):
        service.create_industrial_incident_case(
            actor,
            task.task_id,
            request,
            idempotency_key=key,
        )


def test_v3_case_without_phase_event_directory_fails_closed(
    incident_environment: tuple[ProductService, str, TaskRecord],
    tmp_path: Path,
) -> None:
    service, actor, task = incident_environment
    case = service.create_industrial_incident_case(
        actor,
        task.task_id,
        build_fixture_industrial_incident_request(),
        idempotency_key="incident-missing-events-001",
    )
    case_root = service._incident_case_root(task, case.case_id)
    phase_root = case_root / "phase_events"
    moved_phase_root = tmp_path / f"{case.case_id}_phase_events_moved"
    phase_root.rename(moved_phase_root)

    assert moved_phase_root.is_dir()
    assert not phase_root.exists()
    with pytest.raises(ArtifactUnavailableError, match="phase events are missing"):
        service.get_industrial_incident_case(actor, task.task_id, case.case_id)


def test_incident_api_exposes_command_headers_and_receipts_for_all_posts(
    incident_environment: tuple[ProductService, str, TaskRecord],
) -> None:
    service, actor, task = incident_environment
    base_headers = {"X-Actor-User-Id": actor}
    request = build_fixture_industrial_incident_request()

    with TestClient(create_app(service, ensure_demo_tenant=False)) as client:
        created = client.post(
            f"/v1/tasks/{task.task_id}/industrial-incidents",
            headers={**base_headers, "Idempotency-Key": "api-create-command-001"},
            json=request.model_dump(mode="json"),
        )
        assert created.status_code == 201
        create_command_id = created.headers["X-Incident-Command-Id"]
        case = created.json()
        assert created.headers["X-Incident-Case-SHA256"] == case["case_sha256"]
        assert created.headers["etag"] == f'"{case["case_sha256"]}"'
        assert created.headers["cache-control"] == "private, no-store"
        fetched_case = client.get(
            f"/v1/tasks/{task.task_id}/industrial-incidents/{case['case_id']}",
            headers=base_headers,
        )
        assert fetched_case.status_code == 200
        assert fetched_case.headers["X-Incident-Case-SHA256"] == case["case_sha256"]
        assert fetched_case.headers["cache-control"] == "private, no-store"
        create_receipt = client.get(
            f"/v1/tasks/{task.task_id}/industrial-incident-commands/"
            f"{create_command_id}",
            headers=base_headers,
        )
        assert create_receipt.status_code == 200
        assert create_receipt.json()["status"] == "COMPLETED"
        assert create_receipt.json()["resource_id"] == case["case_id"]
        create_receipt_sha256 = hashlib.sha256(
            canonical_json_bytes(create_receipt.json())
        ).hexdigest()
        assert create_receipt.headers["X-Content-SHA256"] == create_receipt_sha256
        assert create_receipt.headers["etag"] == f'"{create_receipt_sha256}"'
        assert create_receipt.headers["cache-control"] == "private, no-store"
        control_plane = client.get(
            f"/v1/tasks/{task.task_id}/industrial-incidents/"
            f"{case['case_id']}/control-plane",
            headers=base_headers,
        )
        assert control_plane.status_code == 200
        assert control_plane.json()["case_sha256"] == case["case_sha256"]
        assert (
            control_plane.json()["decision_packet"]["production_release_allowed"]
            is False
        )

        decision_request = _decision_request(case["case_sha256"])
        decided = client.post(
            f"/v1/tasks/{task.task_id}/industrial-incidents/"
            f"{case['case_id']}/decisions",
            headers={
                **base_headers,
                "Idempotency-Key": "api-decision-command-001",
            },
            json=decision_request.model_dump(mode="json"),
        )
        assert decided.status_code == 201
        assert (
            decided.headers["X-Incident-Decision-SHA256"]
            == decided.json()["decision_sha256"]
        )
        assert decided.headers["cache-control"] == "private, no-store"
        decision_command_id = decided.headers["X-Incident-Command-Id"]
        decision_receipt = client.get(
            f"/v1/tasks/{task.task_id}/industrial-incident-commands/"
            f"{decision_command_id}",
            headers=base_headers,
        )
        assert decision_receipt.status_code == 200
        assert decision_receipt.json()["status"] == "COMPLETED"
        assert decision_receipt.json()["resource_id"] == decided.json()["decision_id"]

        resume_request = build_fixture_industrial_incident_request(
            revision=2
        ).model_copy(
            update={
                "supersedes_case_id": case["case_id"],
                "expected_parent_case_sha256": case["case_sha256"],
                "authorizing_decision_id": decided.json()["decision_id"],
            }
        )
        resumed = client.post(
            f"/v1/tasks/{task.task_id}/industrial-incidents/{case['case_id']}/resume",
            headers={**base_headers, "Idempotency-Key": "api-resume-command-001"},
            json=resume_request.model_dump(mode="json"),
        )
        assert resumed.status_code == 201
        assert (
            resumed.headers["X-Incident-Case-SHA256"] == resumed.json()["case_sha256"]
        )
        assert resumed.headers["cache-control"] == "private, no-store"
        resume_command_id = resumed.headers["X-Incident-Command-Id"]
        resume_receipt = client.get(
            f"/v1/tasks/{task.task_id}/industrial-incident-commands/"
            f"{resume_command_id}",
            headers=base_headers,
        )
        assert resume_receipt.status_code == 200
        assert resume_receipt.json()["status"] == "COMPLETED"
        assert resume_receipt.json()["resource_id"] == resumed.json()["case_id"]
        resumed_control_plane = client.get(
            f"/v1/tasks/{task.task_id}/industrial-incidents/"
            f"{resumed.json()['case_id']}/control-plane",
            headers=base_headers,
        )
        assert resumed_control_plane.status_code == 200
        assert (
            resumed_control_plane.json()["case_sha256"] == resumed.json()["case_sha256"]
        )
        assert (
            resumed_control_plane.json()["authority_ledger"]["current_state"][
                "authority_epoch"
            ]
            == 4
        )

    assert len({create_command_id, decision_command_id, resume_command_id}) == 3


def test_resume_replay_does_not_create_a_second_child(
    incident_environment: tuple[ProductService, str, TaskRecord],
) -> None:
    service, actor, task = incident_environment
    parent = service.create_industrial_incident_case(
        actor,
        task.task_id,
        build_fixture_industrial_incident_request(),
        idempotency_key="resume-parent-create-001",
    )
    decision = service.record_industrial_incident_decision(
        actor,
        task.task_id,
        parent.case_id,
        _decision_request(parent.case_sha256),
        idempotency_key="resume-parent-decision-001",
    )
    resumed_request = build_fixture_industrial_incident_request(revision=2).model_copy(
        update={
            "supersedes_case_id": parent.case_id,
            "expected_parent_case_sha256": parent.case_sha256,
            "authorizing_decision_id": decision.decision_id,
        }
    )
    key = "resume-child-command-001"

    first_child = service.resume_industrial_incident_case(
        actor,
        task.task_id,
        parent.case_id,
        resumed_request,
        idempotency_key=key,
    )
    replayed_child = service.resume_industrial_incident_case(
        actor,
        task.task_id,
        parent.case_id,
        resumed_request,
        idempotency_key=key,
    )

    assert replayed_child.case_id == first_child.case_id
    assert replayed_child.case_sha256 == first_child.case_sha256
    cases = service.list_industrial_incident_cases(actor, task.task_id)
    assert {item.case_id for item in cases} == {parent.case_id, first_child.case_id}
    assert len(cases) == 2
    command = service.get_incident_command_receipt(
        actor,
        task.task_id,
        _command_id(
            task.task_id,
            IncidentCommandKind.RESUME_CASE,
            key,
            target_case_id=parent.case_id,
        ),
    )
    assert command.status is IncidentCommandStatus.COMPLETED
    assert command.resource_id == first_child.case_id


def test_two_service_instances_admit_only_one_decision_writer(
    incident_environment: tuple[ProductService, str, TaskRecord],
) -> None:
    first_service, actor, task = incident_environment
    case = first_service.create_industrial_incident_case(
        actor,
        task.task_id,
        build_fixture_industrial_incident_request(),
        idempotency_key="cross-process-parent-001",
    )
    second_service = ProductService(
        first_service.product_root,
        runner=_fake_runner(),
        recover_interrupted=False,
    )
    requests = [
        _decision_request(case.case_sha256),
        _decision_request(case.case_sha256).model_copy(
            update={
                "note": (
                    "第二个质量责任人请求用于验证跨实例单写者；该请求不得覆盖首个决定。"
                )
            }
        ),
    ]

    def attempt(
        service: ProductService,
        request: IndustrialIncidentDecisionRequest,
        key: str,
    ) -> str:
        try:
            service.record_industrial_incident_decision(
                actor,
                task.task_id,
                case.case_id,
                request,
                idempotency_key=key,
            )
            return "COMPLETED"
        except ConflictError:
            return "CONFLICT"

    try:
        with ThreadPoolExecutor(max_workers=2) as executor:
            outcomes = list(
                executor.map(
                    lambda arguments: attempt(*arguments),
                    [
                        (first_service, requests[0], "cross-process-decision-a"),
                        (second_service, requests[1], "cross-process-decision-b"),
                    ],
                )
            )
        assert sorted(outcomes) == ["COMPLETED", "CONFLICT"]
        decisions = first_service.list_industrial_incident_decisions(
            actor, task.task_id, case.case_id
        )
        assert len(decisions) == 1
    finally:
        second_service.close(wait=True)


def test_failure_after_case_write_becomes_uncertain_and_is_not_replayed(
    incident_environment: tuple[ProductService, str, TaskRecord],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    service, actor, task = incident_environment
    request = build_fixture_industrial_incident_request()
    key = "case-write-crash-boundary-001"
    original = service._persist_incident_phase_events

    def fail_after_case_write(*_args: object, **_kwargs: object) -> list[object]:
        raise RuntimeError("injected failure after immutable case write")

    monkeypatch.setattr(
        service, "_persist_incident_phase_events", fail_after_case_write
    )
    with pytest.raises(RuntimeError, match="injected failure"):
        service.create_industrial_incident_case(
            actor,
            task.task_id,
            request,
            idempotency_key=key,
        )
    monkeypatch.setattr(service, "_persist_incident_phase_events", original)

    command_id = _command_id(task.task_id, IncidentCommandKind.CREATE_CASE, key)
    command = service.get_incident_command_receipt(actor, task.task_id, command_id)
    assert command.status is IncidentCommandStatus.UNCERTAIN
    assert command.resource_id is None
    with pytest.raises(IncidentCommandUncertainError):
        service.create_industrial_incident_case(
            actor,
            task.task_id,
            request,
            idempotency_key=key,
        )


def test_incident_api_delivers_decision_packet_html_and_audit_bundle(
    incident_environment: tuple[ProductService, str, TaskRecord],
) -> None:
    service, actor, task = incident_environment
    case = service.create_industrial_incident_case(
        actor,
        task.task_id,
        build_fixture_industrial_incident_request(),
        idempotency_key="incident-decision-delivery-001",
    )
    client = TestClient(create_app(service))
    headers = {"X-Actor-User-Id": actor}
    base = (
        f"/v1/tasks/{task.task_id}/industrial-incidents/{case.case_id}/decision-packet"
    )

    packet = client.get(base, headers=headers)
    assert packet.status_code == 200
    assert packet.json()["case_sha256"] == case.case_sha256
    assert packet.json()["named_quality_owner_id"] == actor
    assert packet.json()["production_release_allowed"] is False

    rendered = client.get(base + ".html", headers=headers)
    assert rendered.status_code == 200
    assert (
        rendered.headers["x-decision-packet-sha256"] == (packet.json()["packet_sha256"])
    )
    assert "NOT_ESTABLISHED" in rendered.text

    bundle = client.get(base + "/audit-bundle", headers=headers)
    assert bundle.status_code == 200
    assert bundle.headers["x-audit-bundle-sha256"]
    with zipfile.ZipFile(io.BytesIO(bundle.content)) as archive:
        assert "decision_packet.json" in archive.namelist()
        assert "evidence_request_list.csv" in archive.namelist()
        behavior_bytes = archive.read("agent_behavior_receipt.json")
        behavior = AgentBehaviorReceiptV1.model_validate_json(behavior_bytes)
        assert (
            behavior.source_selection_receipt_sha256
            == (packet.json()["worker_selection_receipt"]["receipt_sha256"])
        )
        manifest = json.loads(archive.read("manifest.json"))
        assert manifest["artifacts"]["agent_behavior_receipt.json"]["sha256"] == (
            hashlib.sha256(behavior_bytes).hexdigest()
        )
        assert behavior.production_release_allowed is False
