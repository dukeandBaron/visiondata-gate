from __future__ import annotations

import pytest

from visiondata_gate.incident_model_planner import (
    incident_model_planner_from_environment,
)
from visiondata_gate.multimodal_advisor import (
    multimodal_case_advisor_from_environment,
)
from visiondata_gate.provider_config import resolve_chat_completions_endpoint


def test_gateway_root_derives_v1_chat_completions_endpoint() -> None:
    assert (
        resolve_chat_completions_endpoint(
            explicit_endpoint="",
            base_url="https://gw.opentoken.io",
            default_endpoint="https://default.invalid/chat/completions",
        )
        == "https://gw.opentoken.io/v1/chat/completions"
    )
    assert (
        resolve_chat_completions_endpoint(
            explicit_endpoint=None,
            base_url="https://gw.opentoken.io/openai/v1/",
            default_endpoint="https://default.invalid/chat/completions",
        )
        == "https://gw.opentoken.io/openai/v1/chat/completions"
    )


def test_explicit_endpoint_wins_and_invalid_base_url_is_rejected() -> None:
    assert (
        resolve_chat_completions_endpoint(
            explicit_endpoint="https://gw.opentoken.io/custom/chat/completions",
            base_url="https://ignored.invalid",
            default_endpoint="https://default.invalid/chat/completions",
        )
        == "https://gw.opentoken.io/custom/chat/completions"
    )
    with pytest.raises(ValueError, match="cannot contain credentials"):
        resolve_chat_completions_endpoint(
            explicit_endpoint=None,
            base_url=("https://placeholder:replace_me" + "@" + "gw.opentoken.io"),
            default_endpoint="https://default.invalid/chat/completions",
        )


def test_incident_planner_accepts_operator_gateway_base_without_exposing_key() -> None:
    planner = incident_model_planner_from_environment(
        {
            "VISIONDATA_INCIDENT_MODEL_MODE": "shadow",
            "VISIONDATA_INCIDENT_MODEL_BASE_URL": "https://gw.opentoken.io",
            "VISIONDATA_INCIDENT_MODEL_NAME": "provider-model-id",
            "VISIONDATA_INCIDENT_MODEL_ALLOWED_HOSTS": "gw.opentoken.io",
            "VISIONDATA_INCIDENT_MODEL_ALLOW_REMOTE": "true",
            "VISIONDATA_INCIDENT_MODEL_API_KEY": "fixture-secret",
        }
    )
    assert planner is not None
    assert planner.config.endpoint == "https://gw.opentoken.io/v1/chat/completions"
    assert planner.config.model == "provider-model-id"
    assert "fixture-secret" not in planner.config.model_dump_json()


def test_multimodal_advisor_accepts_gateway_base_but_keeps_transmission_disabled() -> (
    None
):
    advisor = multimodal_case_advisor_from_environment(
        {
            "VISIONDATA_MULTIMODAL_ADVISOR_MODE": "gated",
            "VISIONDATA_MULTIMODAL_ADVISOR_BASE_URL": "https://gw.opentoken.io",
            "VISIONDATA_MULTIMODAL_ADVISOR_MODEL": "provider-vision-model-id",
            "VISIONDATA_MULTIMODAL_ADVISOR_ALLOWED_HOSTS": "gw.opentoken.io",
            "VISIONDATA_MULTIMODAL_ADVISOR_ALLOW_REMOTE": "true",
            "VISIONDATA_MULTIMODAL_ADVISOR_ALLOW_IMAGE_TRANSMISSION": "false",
            "VISIONDATA_MULTIMODAL_ADVISOR_API_KEY": "fixture-secret",
        }
    )
    assert advisor.config.endpoint == "https://gw.opentoken.io/v1/chat/completions"
    assert advisor.config.allow_image_transmission is False
    assert "fixture-secret" not in advisor.config.model_dump_json()
