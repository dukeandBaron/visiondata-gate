from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from visiondata_gate.api import create_app
from visiondata_gate.incident_model_planner import IncidentModelMode
from visiondata_gate.incident_runtime_profile import IncidentRuntimeProfile
from visiondata_gate.product_models import (
    CreateProjectRequest,
    CreateTaskRequest,
    CreateUserRequest,
    CreateWorkspaceRequest,
)
from visiondata_gate.product_service import ProductService, ProductServiceError
from visiondata_gate.provider_profiles import (
    InMemoryProviderSecretStore,
    ProviderConnectionTestRequest,
    ProviderConnectionTestResult,
    ProviderKind,
    ProviderProfileCreateRequest,
)
from visiondata_gate.task_store import ConflictError, NotFoundError


def _fixture_secret(label: str) -> str:
    return f"fixture-{label}-secret"


class _SwitchableSecretStore(InMemoryProviderSecretStore):
    def __init__(self) -> None:
        super().__init__()
        self.fail_put = False

    def put(self, profile_id: str, secret_value: str) -> None:
        if self.fail_put:
            raise OSError("fixture secret store failure")
        super().put(profile_id, secret_value)


def _tenant(
    service: ProductService,
    *,
    name: str,
) -> tuple[str, str, str]:
    user = service.create_user(CreateUserRequest(display_name=name))
    workspace = service.create_workspace(
        CreateWorkspaceRequest(
            name=f"{name} Workspace",
            owner_user_id=user.user_id,
        )
    )
    project = service.create_project(
        user.user_id,
        CreateProjectRequest(
            workspace_id=workspace.workspace_id,
            name=f"{name} Project",
        ),
    )
    return user.user_id, workspace.workspace_id, project.project_id


def _profile_request(
    workspace_id: str,
    *,
    display_name: str = "My DeepSeek",
    api_key: str = _fixture_secret("deepseek"),
    make_default: bool = True,
) -> ProviderProfileCreateRequest:
    return ProviderProfileCreateRequest(
        workspace_id=workspace_id,
        display_name=display_name,
        provider_kind=ProviderKind.DEEPSEEK,
        base_url="https://api.deepseek.com",
        model="deepseek-chat",
        api_key=api_key,
        default_planner_mode="shadow",
        make_default=make_default,
    )


def test_provider_profiles_are_secret_free_user_private_and_workspace_scoped(
    tmp_path: Path,
) -> None:
    secret_store = InMemoryProviderSecretStore()
    service = ProductService(
        tmp_path / "product",
        recover_interrupted=False,
        provider_secret_store=secret_store,
    )
    user_a, workspace_a, _ = _tenant(service, name="Operator A")
    user_b, _, _ = _tenant(service, name="Operator B")
    second_workspace = service.create_workspace(
        CreateWorkspaceRequest(name="A Secondary", owner_user_id=user_a)
    )
    secret = _fixture_secret("deepseek")
    request = _profile_request(workspace_a, api_key=secret)

    first = service.create_provider_profile(user_a, request)
    second = service.create_provider_profile(
        user_a,
        _profile_request(
            workspace_a,
            display_name="Backup DeepSeek",
            api_key=_fixture_secret("backup"),
            make_default=False,
        ),
    )
    isolated = service.create_provider_profile(
        user_a,
        _profile_request(
            second_workspace.workspace_id,
            display_name="Secondary Workspace Provider",
            api_key=_fixture_secret("secondary"),
        ),
    )

    assert secret_store.get(first.profile_id) == secret
    assert secret not in repr(request)
    assert secret not in request.model_dump_json()
    assert secret not in first.model_dump_json()
    assert first.owner_user_id == user_a
    assert [
        item.profile_id for item in service.list_provider_profiles(user_a, workspace_a)
    ] == [
        first.profile_id,
        second.profile_id,
    ]
    assert service.list_provider_profiles(user_a, second_workspace.workspace_id) == [
        isolated
    ]
    with pytest.raises(NotFoundError, match="workspace not found"):
        service.list_provider_profiles(user_b, workspace_a)

    persisted_bytes = b"".join(
        path.read_bytes()
        for path in (tmp_path / "product").rglob("*")
        if path.is_file()
    )
    assert secret.encode("utf-8") not in persisted_bytes

    selected = service.set_default_provider_profile(user_a, second.profile_id)
    assert selected.is_default is True
    assert (
        service.provider_profile_registry.get_default(user_a, workspace_a) == selected
    )

    revoked = service.revoke_provider_profile(user_a, second.profile_id)
    assert revoked.status.value == "REVOKED"
    assert secret_store.get(second.profile_id) is None
    assert [
        item.profile_id for item in service.list_provider_profiles(user_a, workspace_a)
    ] == [first.profile_id]
    service.close(wait=True)


def test_custom_provider_blocks_loopback_ssrf_before_transport(tmp_path: Path) -> None:
    service = ProductService(
        tmp_path / "product",
        recover_interrupted=False,
        provider_secret_store=InMemoryProviderSecretStore(),
    )
    user_id, workspace_id, _ = _tenant(service, name="SSRF Operator")

    result = service.test_provider_connection(
        user_id,
        ProviderConnectionTestRequest(
            workspace_id=workspace_id,
            display_name="Blocked Private Endpoint",
            provider_kind=ProviderKind.OPENAI_COMPATIBLE,
            base_url="https://127.0.0.1:9443",
            model="private-model",
            api_key=_fixture_secret("private"),
            timeout_seconds=1,
            max_retries=0,
        ),
    )

    assert result.status == "BLOCKED"
    assert result.reason_code == "DESTINATION_POLICY_REJECTED"
    assert result.secrets_retained is False
    service.close(wait=True)


def test_failed_secret_staging_does_not_publish_profile_or_clear_old_default(
    tmp_path: Path,
) -> None:
    secret_store = _SwitchableSecretStore()
    service = ProductService(
        tmp_path / "product",
        recover_interrupted=False,
        provider_secret_store=secret_store,
    )
    user_id, workspace_id, _ = _tenant(service, name="Atomic Provider")
    original = service.create_provider_profile(
        user_id,
        _profile_request(workspace_id, api_key=_fixture_secret("original")),
    )
    secret_store.fail_put = True

    with pytest.raises(ProductServiceError, match="could not be stored securely"):
        service.create_provider_profile(
            user_id,
            _profile_request(
                workspace_id,
                display_name="Must Not Publish",
                api_key=_fixture_secret("failed-staging"),
            ),
        )

    profiles = service.list_provider_profiles(user_id, workspace_id)
    assert profiles == [original]
    assert (
        service.provider_profile_registry.get_default(user_id, workspace_id) == original
    )
    assert secret_store.get(original.profile_id) == _fixture_secret("original")
    service.close(wait=True)


def test_case_bound_byok_profile_builds_only_the_owners_workspace_planner(
    tmp_path: Path,
) -> None:
    secret_store = InMemoryProviderSecretStore()
    service = ProductService(
        tmp_path / "product",
        recover_interrupted=False,
        provider_secret_store=secret_store,
    )
    user_a, workspace_a, project_a = _tenant(service, name="Planner A")
    user_b, workspace_b, _ = _tenant(service, name="Planner B")
    profile_a = service.create_provider_profile(
        user_a,
        _profile_request(workspace_a, api_key=_fixture_secret("planner-a")),
    )
    profile_b = service.create_provider_profile(
        user_b,
        _profile_request(workspace_b, api_key=_fixture_secret("planner-b")),
    )
    task = service.create_task(
        user_a,
        CreateTaskRequest(
            project_id=project_a,
            goal="Use the selected customer provider for evidence-gap planning.",
        ),
        auto_start=False,
    )
    runtime_profile = IncidentRuntimeProfile(
        model_profile_id="workspace-byok",
        provider_profile_id=profile_a.profile_id,
        planner_mode=IncidentModelMode.SHADOW,
        max_output_tokens=700,
        context_budget_tokens=4096,
    )

    planner = service._workspace_provider_planner(user_a, task, runtime_profile)

    assert planner.config.endpoint == "https://api.deepseek.com/v1/chat/completions"
    assert planner.config.model == "deepseek-chat"
    assert planner.config.mode is IncidentModelMode.SHADOW
    assert planner.config.max_tokens == 700
    assert planner.config.context_budget_tokens == 4096

    foreign_profile = runtime_profile.model_copy(
        update={"provider_profile_id": profile_b.profile_id}
    )
    with pytest.raises(NotFoundError, match="provider profile not found"):
        service._workspace_provider_planner(user_a, task, foreign_profile)

    second_workspace = service.create_workspace(
        CreateWorkspaceRequest(name="Planner A Secondary", owner_user_id=user_a)
    )
    wrong_workspace_profile = service.create_provider_profile(
        user_a,
        _profile_request(
            second_workspace.workspace_id,
            display_name="Wrong Workspace",
            api_key=_fixture_secret("wrong-workspace"),
        ),
    )
    wrong_workspace_runtime = runtime_profile.model_copy(
        update={"provider_profile_id": wrong_workspace_profile.profile_id}
    )
    with pytest.raises(ConflictError, match="does not belong"):
        service._workspace_provider_planner(user_a, task, wrong_workspace_runtime)
    service.close(wait=True)


def test_provider_api_crud_is_secret_free_and_remote_management_is_denied(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    secret_store = InMemoryProviderSecretStore()
    service = ProductService(
        tmp_path / "product",
        recover_interrupted=False,
        provider_secret_store=secret_store,
    )
    user_id, workspace_id, _ = _tenant(service, name="API Operator")
    app = create_app(service, enable_account_bootstrap=True)
    client = TestClient(app)
    secret = _fixture_secret("api")

    def connected(config, *, api_key):
        assert api_key == secret
        return ProviderConnectionTestResult(
            status="CONNECTED",
            reason_code="PROVIDER_CHAT_COMPLETION_OK",
            provider_kind=config.provider_kind,
            endpoint_host=config.endpoint_host,
            model=config.model,
            latency_ms=12.5,
            tested_at="2026-08-29T00:00:00Z",
            exchange_receipt_sha256="a" * 64,
        )

    monkeypatch.setattr(
        "visiondata_gate.product_service.probe_provider_connection",
        connected,
    )
    headers = {"X-Actor-User-Id": user_id}
    payload = {
        "workspace_id": workspace_id,
        "display_name": "API DeepSeek",
        "provider_kind": "deepseek",
        "base_url": "https://api.deepseek.com",
        "model": "deepseek-chat",
        "api_key": secret,
        "default_planner_mode": "shadow",
        "make_default": True,
    }

    probe = client.post(
        "/v1/provider-profiles/test-connection",
        headers=headers,
        json={**payload, "make_default": False},
    )
    assert probe.status_code == 200
    assert probe.json()["status"] == "CONNECTED"
    assert secret not in probe.text

    created = client.post("/v1/provider-profiles", headers=headers, json=payload)
    assert created.status_code == 201
    profile_id = created.json()["profile_id"]
    assert created.headers["cache-control"] == "no-store"
    assert secret not in created.text
    assert secret_store.get(profile_id) == secret

    listed = client.get(
        "/v1/provider-profiles",
        headers=headers,
        params={"workspace_id": workspace_id},
    )
    assert listed.status_code == 200
    assert listed.headers["cache-control"] == "no-store"
    assert [item["profile_id"] for item in listed.json()] == [profile_id]
    assert secret not in listed.text

    saved_probe = client.post(
        f"/v1/provider-profiles/{profile_id}/test-connection",
        headers=headers,
    )
    assert saved_probe.status_code == 200
    assert saved_probe.json()["secrets_retained"] is False

    invalid = client.post(
        "/v1/provider-profiles",
        headers=headers,
        json={**payload, "model": "invalid model value"},
    )
    assert invalid.status_code == 422
    assert invalid.json()["error"]["message"] == (
        "the request did not satisfy the accepted schema"
    )
    assert secret not in invalid.text

    monkeypatch.delenv("VISIONDATA_BYOK_ALLOW_REMOTE_MANAGEMENT", raising=False)
    remote_client = TestClient(app, client=("198.51.100.10", 50000))
    denied = remote_client.post(
        "/v1/provider-profiles/test-connection",
        headers=headers,
        json={**payload, "make_default": False},
    )
    assert denied.status_code == 403
    assert secret not in denied.text
    denied_list = remote_client.get(
        "/v1/provider-profiles",
        headers=headers,
        params={"workspace_id": workspace_id},
    )
    assert denied_list.status_code == 403

    revoked = client.delete(f"/v1/provider-profiles/{profile_id}", headers=headers)
    assert revoked.status_code == 200
    assert revoked.json()["status"] == "REVOKED"
    assert secret_store.get(profile_id) is None
    service.close(wait=True)
