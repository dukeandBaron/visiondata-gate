from __future__ import annotations

from pathlib import Path
from typing import Literal

import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError

import visiondata_gate.api as api_module
import visiondata_gate.product_service as product_service_module
from visiondata_gate.agentteams_transport import (
    AgentTeamsTransportMode,
    HostedAgentTeamsReceipt,
    HostedProjectSubmission,
)
from visiondata_gate.api import create_app
from visiondata_gate.product_models import (
    CreateProjectRequest,
    CreateTaskRequest,
    CreateUserRequest,
    CreateWorkspaceRequest,
    SubmitHostedAgentTeamsTaskRequest,
)
from visiondata_gate.product_service import (
    HostedAgentTeamsUnavailableError,
    ProductService,
    get_product_service,
)
from visiondata_gate.task_store import NotFoundError


def _receipt(
    operation: Literal["probe", "submit_project"],
    *,
    source_run_id: str | None = None,
    approval_id: str | None = None,
) -> HostedAgentTeamsReceipt:
    submitted = operation == "submit_project"
    return HostedAgentTeamsReceipt(
        observed_at="2026-08-28T00:00:00.000Z",
        operation=operation,
        status="PASS",
        operation_status=(
            "LEADER_INGRESS_SENT" if submitted else "CONTROL_PLANE_READY"
        ),
        mode=(
            AgentTeamsTransportMode.GATED
            if submitted
            else AgentTeamsTransportMode.SHADOW
        ),
        team_name="visiondata-gate",
        expected_workers=[],
        observed_workers=[],
        expected_skill_assignments={},
        observed_skill_assignments={},
        checks={},
        controller_connected=True,
        team_ready=True,
        workers_ready=True,
        skill_specs_verified=True,
        project_registered=submitted,
        leader_ingress_sent=submitted,
        workflow_observed=submitted,
        project_id="prj-hosted" if submitted else None,
        source_run_id=source_run_id,
        goal_sha256="a" * 64 if submitted else None,
        approval_id=approval_id,
        matrix_transaction_sha256="c" * 64 if submitted else None,
        evidence_projections={},
        transport_receipts=[],
        reasons=[],
        boundary="fake transport receipt for product integration tests",
        receipt_sha256="b" * 64,
    )


class _FakeHostedAgentTeamsTransport:
    def __init__(self) -> None:
        self.probe_output_dirs: list[Path] = []
        self.submissions: list[tuple[Path, HostedProjectSubmission, str]] = []

    @staticmethod
    def _mark_output(output_dir: Path, operation: str) -> None:
        assert output_dir.is_dir()
        (output_dir / f"fake-{operation}-receipt.json").write_text(
            "{}\n", encoding="utf-8"
        )

    def collect_runtime_evidence(self, output_dir: Path) -> HostedAgentTeamsReceipt:
        self.probe_output_dirs.append(output_dir)
        self._mark_output(output_dir, "probe")
        return _receipt("probe")

    def submit_project(
        self,
        output_dir: Path,
        submission: HostedProjectSubmission,
        *,
        approval_id: str,
    ) -> HostedAgentTeamsReceipt:
        self.submissions.append((output_dir, submission, approval_id))
        self._mark_output(output_dir, "submission")
        return _receipt(
            "submit_project",
            source_run_id=submission.source_run_id,
            approval_id=approval_id,
        )


def _tenant(
    service: ProductService, name: str = "Hosted Owner"
) -> tuple[str, str, str, str]:
    user = service.create_user(CreateUserRequest(display_name=name))
    workspace = service.create_workspace(
        CreateWorkspaceRequest(name=f"{name} Workspace", owner_user_id=user.user_id)
    )
    project = service.create_project(
        user.user_id,
        CreateProjectRequest(
            workspace_id=workspace.workspace_id,
            name=f"{name} Project",
        ),
    )
    task = service.create_task(
        user.user_id,
        CreateTaskRequest(
            project_id=project.project_id,
            goal="Audit the visible industrial dataset and deliver bounded evidence.",
        ),
        auto_start=False,
    )
    return user.user_id, workspace.workspace_id, project.project_id, task.task_id


def test_hosted_transport_off_fails_closed_without_allocating_evidence(
    tmp_path: Path,
) -> None:
    service = ProductService(tmp_path / "product", recover_interrupted=False)
    actor, workspace_id, _, task_id = _tenant(service)
    request = SubmitHostedAgentTeamsTaskRequest(approval_id="approval-rc3")

    with pytest.raises(HostedAgentTeamsUnavailableError):
        service.probe_hosted_agentteams(actor, workspace_id)
    with pytest.raises(HostedAgentTeamsUnavailableError):
        service.submit_task_to_hosted_agentteams(actor, task_id, request)

    client = TestClient(
        create_app(service, enable_account_bootstrap=False, ensure_demo_tenant=False)
    )
    headers = {"X-Actor-User-Id": actor}
    probe = client.post(
        f"/v1/workspaces/{workspace_id}/hosted-agentteams/probes",
        headers=headers,
    )
    submit = client.post(
        f"/v1/tasks/{task_id}/hosted-agentteams/submissions",
        headers=headers,
        json=request.model_dump(mode="json"),
    )
    assert probe.status_code == submit.status_code == 409
    assert probe.json()["error"]["code"] == "hosted_agentteams_not_configured"
    assert submit.json()["error"]["code"] == "hosted_agentteams_not_configured"
    assert service.health().data_sources["hosted_agentteams"] == "not_configured"
    assert not (service.product_root / "hosted_agentteams").exists()
    service.close(wait=True)


def test_hosted_transport_enforces_actor_visibility_before_network_or_output(
    tmp_path: Path,
) -> None:
    transport = _FakeHostedAgentTeamsTransport()
    service = ProductService(
        tmp_path / "product",
        hosted_agentteams=transport,  # type: ignore[arg-type]
        recover_interrupted=False,
    )
    _, workspace_id, _, task_id = _tenant(service, "Owner A")
    other_actor, _, _, _ = _tenant(service, "Owner B")

    with pytest.raises(NotFoundError):
        service.probe_hosted_agentteams(other_actor, workspace_id)
    with pytest.raises(NotFoundError):
        service.submit_task_to_hosted_agentteams(
            other_actor,
            task_id,
            SubmitHostedAgentTeamsTaskRequest(approval_id="approval-owner-b"),
        )

    assert transport.probe_output_dirs == []
    assert transport.submissions == []
    assert not (service.product_root / "hosted_agentteams").exists()
    service.close(wait=True)


def test_probe_and_gated_task_submit_bind_parameters_and_immutable_attempt_dirs(
    tmp_path: Path,
) -> None:
    transport = _FakeHostedAgentTeamsTransport()
    service = ProductService(
        tmp_path / "product",
        hosted_agentteams=transport,  # type: ignore[arg-type]
        recover_interrupted=False,
    )
    actor, workspace_id, _, task_id = _tenant(service)

    first_probe = service.probe_hosted_agentteams(actor, workspace_id)
    second_probe = service.probe_hosted_agentteams(actor, workspace_id)
    submit_request = SubmitHostedAgentTeamsTaskRequest(
        approval_id="quality-lead-approval-20260828",
        wait_for_remote_execution=True,
    )
    submitted = service.submit_task_to_hosted_agentteams(actor, task_id, submit_request)

    assert first_probe.operation == second_probe.operation == "probe"
    assert len(transport.probe_output_dirs) == 2
    assert transport.probe_output_dirs[0] != transport.probe_output_dirs[1]
    output_dir, submission, approval_id = transport.submissions[0]
    assert output_dir not in transport.probe_output_dirs
    assert submission.source_run_id == task_id
    assert submission.goal == service.get_task(actor, task_id).goal
    assert submission.requester == actor
    assert submission.wait_for_remote_execution is True
    assert submission.title.endswith(f"[{task_id}]")
    assert approval_id == submit_request.approval_id
    assert submitted.approval_id == submit_request.approval_id
    assert service.health().data_sources["hosted_agentteams"] == (
        "configured_not_probed"
    )
    hosted_root = (service.product_root / "hosted_agentteams").resolve()
    for attempt in [*transport.probe_output_dirs, output_dir]:
        attempt.resolve().relative_to(hosted_root)
        assert len(list(attempt.iterdir())) == 1
    service.close(wait=True)


def test_hosted_api_is_scoped_gated_and_does_not_expose_local_paths(
    tmp_path: Path,
) -> None:
    transport = _FakeHostedAgentTeamsTransport()
    service = ProductService(
        tmp_path / "private-product-root",
        hosted_agentteams=transport,  # type: ignore[arg-type]
        recover_interrupted=False,
    )
    actor, workspace_id, _, task_id = _tenant(service)
    client = TestClient(
        create_app(service, enable_account_bootstrap=False, ensure_demo_tenant=False)
    )
    headers = {"X-Actor-User-Id": actor}

    probe = client.post(
        f"/v1/workspaces/{workspace_id}/hosted-agentteams/probes",
        headers=headers,
    )
    submit = client.post(
        f"/v1/tasks/{task_id}/hosted-agentteams/submissions",
        headers=headers,
        json={"approval_id": "quality-lead-api-approval"},
    )
    invalid = client.post(
        f"/v1/tasks/{task_id}/hosted-agentteams/submissions",
        headers=headers,
        json={"approval_id": "not a plain named approval"},
    )

    assert probe.status_code == 200
    assert probe.json()["operation"] == "probe"
    assert (
        probe.headers["x-hosted-agentteams-receipt-sha256"]
        == (probe.json()["receipt_sha256"])
    )
    assert probe.headers["etag"] == f'"{probe.json()["receipt_sha256"]}"'
    assert probe.headers["cache-control"] == "private, no-store"
    assert submit.status_code == 201
    assert submit.json()["operation"] == "submit_project"
    assert (
        submit.headers["x-hosted-agentteams-receipt-sha256"]
        == (submit.json()["receipt_sha256"])
    )
    assert submit.headers["etag"] == f'"{submit.json()["receipt_sha256"]}"'
    assert invalid.status_code == 422
    response_text = probe.text + submit.text
    assert str(service.product_root) not in response_text
    assert "private-product-root" not in response_text
    openapi = client.get("/openapi.json").json()
    assert "/v1/workspaces/{workspace_id}/hosted-agentteams/probes" in openapi["paths"]
    assert "/v1/tasks/{task_id}/hosted-agentteams/submissions" in openapi["paths"]
    assert "not configured by default" in openapi["info"]["description"]
    service.close(wait=True)


def test_off_environment_short_circuits_hosted_factory_for_app_and_cache(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    def unexpected_factory() -> None:
        raise AssertionError("off mode must not construct the Hosted transport")

    monkeypatch.setenv("VISIONDATA_AGENTTEAMS_MODE", "off")
    monkeypatch.setenv("VISIONDATA_PRODUCT_ROOT", str(tmp_path / "api-product"))
    monkeypatch.setattr(
        api_module, "hosted_agentteams_from_environment", unexpected_factory
    )
    with TestClient(create_app(ensure_demo_tenant=False)) as client:
        assert client.get("/v1/health").status_code == 200

    monkeypatch.setattr(
        product_service_module,
        "hosted_agentteams_from_environment",
        unexpected_factory,
    )
    cached_root = (tmp_path / "cached-product").resolve()
    service = get_product_service(cached_root)
    try:
        assert service.hosted_agentteams is None
    finally:
        service.close(wait=True)
        product_service_module._default_services.pop(cached_root, None)


def test_explicit_environment_mode_constructs_optional_app_transport(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    transport = _FakeHostedAgentTeamsTransport()
    factory_calls = 0

    def configured_factory() -> _FakeHostedAgentTeamsTransport:
        nonlocal factory_calls
        factory_calls += 1
        return transport

    monkeypatch.setenv("VISIONDATA_AGENTTEAMS_MODE", "shadow")
    monkeypatch.setenv("VISIONDATA_PRODUCT_ROOT", str(tmp_path / "api-product"))
    monkeypatch.setattr(
        api_module, "hosted_agentteams_from_environment", configured_factory
    )
    app = create_app(ensure_demo_tenant=False)
    with TestClient(app) as client:
        assert (
            client.get("/v1/health").json()["data_sources"]["hosted_agentteams"]
            == "configured_not_probed"
        )

    assert factory_calls == 1
    assert app.state.product_service.hosted_agentteams is transport


def test_named_hosted_approval_contract_rejects_ambiguous_values() -> None:
    with pytest.raises(ValidationError):
        SubmitHostedAgentTeamsTaskRequest(approval_id="quality lead approved")
    with pytest.raises(ValidationError):
        SubmitHostedAgentTeamsTaskRequest(approval_id="<approval>")
