from __future__ import annotations

import hashlib

import pytest
from pydantic import ValidationError

from visiondata_gate.evidence import canonical_json_bytes
from visiondata_gate.incident_model_planner import (
    DEFAULT_INCIDENT_MODEL_ENDPOINT,
    DEFAULT_INCIDENT_MODEL_NAME,
    IncidentModelMode,
)
from visiondata_gate.incident_runtime_profile import (
    IncidentMemoryMode,
    IncidentRuntimeProfile,
    build_incident_runtime_capabilities,
    build_runtime_profile_binding,
    planner_from_runtime_profile,
)


def test_runtime_profile_accepts_only_coherent_mode_and_model_pairs() -> None:
    assert IncidentRuntimeProfile().model_profile_id == "deterministic-off"
    assert (
        IncidentRuntimeProfile(
            model_profile_id="deepseek-chat",
            planner_mode=IncidentModelMode.SHADOW,
            temperature=0.2,
        ).temperature
        == 0.2
    )

    invalid_profiles = [
        {
            "model_profile_id": "deepseek-chat",
            "planner_mode": IncidentModelMode.OFF,
        },
        {
            "model_profile_id": "deepseek-chat",
            "planner_mode": IncidentModelMode.GATED,
            "temperature": 0.1,
        },
        {
            "model_profile_id": "deepseek-replay",
            "planner_mode": IncidentModelMode.REPLAY,
            "temperature": 0.1,
        },
        {
            "memory_mode": IncidentMemoryMode.OFF,
            "memory_top_k": 1,
        },
        {
            "memory_mode": IncidentMemoryMode.APPROVED_SITE,
            "memory_top_k": 1,
        },
    ]
    for payload in invalid_profiles:
        with pytest.raises(ValidationError):
            IncidentRuntimeProfile(**payload)


def test_runtime_profile_accepts_only_scoped_byok_provider_profile_ids() -> None:
    profile = IncidentRuntimeProfile(
        model_profile_id="workspace-byok",
        provider_profile_id="prv_0123456789abcdefabcd",
        planner_mode=IncidentModelMode.SHADOW,
    )

    assert profile.provider_profile_id == "prv_0123456789abcdefabcd"
    with pytest.raises(ValidationError, match="only valid for workspace-byok"):
        IncidentRuntimeProfile(
            model_profile_id="deepseek-chat",
            provider_profile_id="prv_0123456789abcdefabcd",
            planner_mode=IncidentModelMode.SHADOW,
        )
    with pytest.raises(ValidationError, match="provider_profile_id is invalid"):
        IncidentRuntimeProfile(
            model_profile_id="workspace-byok",
            provider_profile_id="../secret",
            planner_mode=IncidentModelMode.SHADOW,
        )


@pytest.mark.parametrize(
    "forbidden_field",
    [
        "api_key",
        "endpoint",
        "provider_host",
        "allow_remote_model",
        "allow_image_transmission",
        "frozen_policy",
        "production_release_authority",
    ],
)
def test_runtime_profile_schema_rejects_client_security_controls(
    forbidden_field: str,
) -> None:
    with pytest.raises(ValidationError, match="Extra inputs"):
        IncidentRuntimeProfile.model_validate({forbidden_field: "not-allowed"})


def test_runtime_profile_sha_is_canonical_and_changes_with_effective_settings() -> None:
    first = IncidentRuntimeProfile.model_validate(
        {
            "planner_mode": "shadow",
            "temperature": 0.2,
            "model_profile_id": "deepseek-chat",
            "max_output_tokens": 700,
            "context_budget_tokens": 4096,
        }
    )
    reordered = IncidentRuntimeProfile.model_validate(
        {
            "context_budget_tokens": 4096,
            "max_output_tokens": 700,
            "model_profile_id": "deepseek-chat",
            "temperature": 0.2,
            "planner_mode": "shadow",
        }
    )
    changed = first.model_copy(update={"temperature": 0.1})

    assert first.profile_sha256() == reordered.profile_sha256()
    assert first.profile_sha256() != changed.profile_sha256()


def test_runtime_capabilities_are_server_adjudicated_and_secret_free(tmp_path) -> None:
    replay_path = tmp_path / "planner-replay.json"
    replay_path.write_text("{}", encoding="utf-8")
    secret = "fixture-runtime-secret"
    capabilities = build_incident_runtime_capabilities(
        environment={
            "VISIONDATA_INCIDENT_MODEL_API_KEY": secret,
            "VISIONDATA_INCIDENT_MODEL_ALLOW_REMOTE": "true",
            "VISIONDATA_INCIDENT_MODEL_NAME": "server-owned-model",
            "VISIONDATA_INCIDENT_MODEL_REPLAY_PATH": str(replay_path),
        },
        memory_profile_ids=["factory-b", "factory-a", "factory-a"],
    )
    serialized = capabilities.model_dump_json()

    by_id = {item.profile_id: item for item in capabilities.model_profiles}
    assert by_id["deepseek-chat"].availability == "AVAILABLE"
    assert by_id["deepseek-chat"].context_limit_status == "UNVERIFIED"
    assert by_id["deepseek-replay"].availability == "AVAILABLE"
    assert [item.profile_id for item in capabilities.memory_profiles] == [
        "factory-a",
        "factory-b",
    ]
    assert capabilities.production_decision_authority == "human_only"
    assert capabilities.secrets_exposed is False
    assert secret not in serialized
    assert str(replay_path) not in serialized
    assert "https://" not in serialized


def test_profile_parameters_reach_server_owned_planner_config_without_network() -> None:
    profile = IncidentRuntimeProfile(
        model_profile_id="deepseek-chat",
        planner_mode=IncidentModelMode.SHADOW,
        temperature=0.2,
        max_output_tokens=777,
        context_budget_tokens=4096,
    )
    planner = planner_from_runtime_profile(
        profile,
        environment={
            "VISIONDATA_INCIDENT_MODEL_API_KEY": "fixture-secret",
            "VISIONDATA_INCIDENT_MODEL_ALLOW_REMOTE": "true",
            "VISIONDATA_INCIDENT_MODEL_NAME": "server-owned-model",
            "VISIONDATA_INCIDENT_MODEL_ENDPOINT": (
                "https://api.deepseek.com/chat/completions"
            ),
            "VISIONDATA_INCIDENT_MODEL_ALLOWED_HOSTS": "api.deepseek.com",
            "VISIONDATA_INCIDENT_MODEL_MAX_RETRIES": "0",
        },
    )

    assert planner is not None
    assert planner.config.temperature == 0.2
    assert planner.config.max_tokens == 777
    assert planner.config.context_budget_tokens == 4096
    assert planner.config.model == "server-owned-model"


def test_runtime_profile_blank_endpoint_and_model_fall_back_without_network() -> None:
    profile = IncidentRuntimeProfile(
        model_profile_id="deepseek-chat",
        planner_mode=IncidentModelMode.SHADOW,
    )
    planner = planner_from_runtime_profile(
        profile,
        environment={
            "VISIONDATA_INCIDENT_MODEL_API_KEY": "fixture-secret",
            "VISIONDATA_INCIDENT_MODEL_ALLOW_REMOTE": "true",
            "VISIONDATA_INCIDENT_MODEL_ENDPOINT": "   ",
            "VISIONDATA_INCIDENT_MODEL_BASE_URL": "",
            "VISIONDATA_INCIDENT_MODEL_NAME": "   ",
            "VISIONDATA_INCIDENT_MODEL_ALLOWED_HOSTS": "api.deepseek.com",
        },
    )

    assert planner is not None
    assert planner.config.endpoint == DEFAULT_INCIDENT_MODEL_ENDPOINT
    assert planner.config.model == DEFAULT_INCIDENT_MODEL_NAME


def test_runtime_profile_normalizes_gateway_base_without_network() -> None:
    profile = IncidentRuntimeProfile(
        model_profile_id="deepseek-chat",
        planner_mode=IncidentModelMode.SHADOW,
    )
    planner = planner_from_runtime_profile(
        profile,
        environment={
            "VISIONDATA_INCIDENT_MODEL_API_KEY": "fixture-secret",
            "VISIONDATA_INCIDENT_MODEL_ALLOW_REMOTE": "true",
            "VISIONDATA_INCIDENT_MODEL_ENDPOINT": "",
            "VISIONDATA_INCIDENT_MODEL_BASE_URL": "https://gw.opentoken.io",
            "VISIONDATA_INCIDENT_MODEL_NAME": "provider-model-id",
            "VISIONDATA_INCIDENT_MODEL_ALLOWED_HOSTS": "gw.opentoken.io",
        },
    )

    assert planner is not None
    assert planner.config.endpoint == ("https://gw.opentoken.io/v1/chat/completions")
    assert planner.config.model == "provider-model-id"


def test_runtime_binding_is_case_bound_reproducible_and_secret_free() -> None:
    profile = IncidentRuntimeProfile()
    first = build_runtime_profile_binding(
        case_id="incident_aaaaaaaaaaaaaaaaaaaa",
        case_sha256="b" * 64,
        profile=profile,
        planner_config_sha256=None,
        planner_connection_status="OFF",
        governed_context_receipt_sha256=None,
        selected_memory_count=0,
        rejected_memory_count=0,
    )
    second = build_runtime_profile_binding(
        case_id="incident_aaaaaaaaaaaaaaaaaaaa",
        case_sha256="b" * 64,
        profile=profile,
        planner_config_sha256=None,
        planner_connection_status="OFF",
        governed_context_receipt_sha256=None,
        selected_memory_count=0,
        rejected_memory_count=0,
    )
    stable = first.model_dump(mode="json")
    stored_sha256 = stable.pop("binding_sha256")

    assert first == second
    assert stored_sha256 == hashlib.sha256(canonical_json_bytes(stable)).hexdigest()
    assert first.profile_sha256 == profile.profile_sha256()
    assert first.raw_images_transmitted is False
    assert first.secrets_retained is False
    assert first.production_decision_authority == "human_only"
