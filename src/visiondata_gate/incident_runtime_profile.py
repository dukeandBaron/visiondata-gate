"""Secret-free, case-bound runtime settings for the industrial incident Agent.

The browser selects only allowlisted profile identifiers and bounded knobs.  API
endpoints, credentials, provider permissions, and model identity remain server
policy.  A profile is embedded in the immutable incident request so changing a
workspace draft can never mutate an existing case or child run.
"""

from __future__ import annotations

import hashlib
import os
import re
from enum import Enum
from pathlib import Path
from typing import Literal, Mapping

from pydantic import Field, field_validator, model_validator

from .evidence import canonical_json_bytes
from .incident_model_planner import (
    DEFAULT_INCIDENT_MODEL_ENDPOINT,
    DEFAULT_INCIDENT_MODEL_NAME,
    DEEPSEEK_API_HOST,
    INCIDENT_MODEL_API_KEY_ENV,
    INCIDENT_MODEL_BASE_URL_ENV,
    INCIDENT_MODEL_ENDPOINT_ENV,
    IncidentModelMode,
    IncidentModelPlanner,
    IncidentModelPlannerConfig,
)
from .product_models import ProductModel
from .provider_config import resolve_chat_completions_endpoint


_PROVIDER_PROFILE_ID_PATTERN = re.compile(r"^prv_[0-9a-f]{20}$")


def _sha256(value: object) -> str:
    return hashlib.sha256(canonical_json_bytes(value)).hexdigest()


def _parse_bool(value: str | None, *, default: bool = False) -> bool:
    if value is None:
        return default
    normalized = value.strip().casefold()
    if normalized in {"1", "true", "yes", "on"}:
        return True
    if normalized in {"0", "false", "no", "off"}:
        return False
    return default


class IncidentMemoryMode(str, Enum):
    OFF = "off"
    APPROVED_SITE = "approved_site"


class IncidentRuntimeProfile(ProductModel):
    """User-adjustable settings that are safe to persist with a case.

    ``context_budget_tokens`` is a request budget enforced before the model
    call.  It is deliberately not advertised as the provider's maximum context
    window, which remains unverified until the provider returns a capability.
    """

    schema_version: Literal["visiondata-gate.incident-runtime-profile.v1"] = (
        "visiondata-gate.incident-runtime-profile.v1"
    )
    model_profile_id: Literal[
        "deterministic-off",
        "deepseek-chat",
        "deepseek-replay",
        "workspace-byok",
    ] = "deterministic-off"
    provider_profile_id: str | None = Field(default=None, max_length=24)
    planner_mode: IncidentModelMode = IncidentModelMode.OFF
    temperature: float = Field(default=0.0, ge=0.0, le=0.3)
    max_output_tokens: int = Field(default=900, ge=200, le=2_000)
    context_budget_tokens: int = Field(default=8_192, ge=1_024, le=32_768)
    memory_mode: IncidentMemoryMode = IncidentMemoryMode.OFF
    memory_top_k: int = Field(default=0, ge=0, le=12)
    site_profile_id: str | None = Field(default=None, max_length=120)
    human_approval_required: Literal[True] = True
    structured_output_schema: Literal["visiondata-gate.incident-model-plan.v1"] = (
        "visiondata-gate.incident-model-plan.v1"
    )

    @field_validator("site_profile_id")
    @classmethod
    def normalize_site_profile_id(cls, value: str | None) -> str | None:
        if value is None:
            return None
        normalized = value.strip().casefold()
        if not normalized:
            return None
        if any(
            character not in "abcdefghijklmnopqrstuvwxyz0123456789-_."
            for character in normalized
        ):
            raise ValueError("site_profile_id contains unsupported characters")
        return normalized

    @field_validator("provider_profile_id")
    @classmethod
    def normalize_provider_profile_id(cls, value: str | None) -> str | None:
        if value is None:
            return None
        normalized = value.strip().casefold()
        if not normalized:
            return None
        if not _PROVIDER_PROFILE_ID_PATTERN.fullmatch(normalized):
            raise ValueError("provider_profile_id is invalid")
        return normalized

    @model_validator(mode="after")
    def validate_runtime_boundary(self) -> IncidentRuntimeProfile:
        if self.planner_mode is IncidentModelMode.OFF:
            if self.model_profile_id != "deterministic-off":
                raise ValueError("off mode requires deterministic-off model profile")
            if self.temperature != 0:
                raise ValueError("off mode requires temperature=0")
        elif self.planner_mode is IncidentModelMode.REPLAY:
            if self.model_profile_id != "deepseek-replay":
                raise ValueError("replay mode requires deepseek-replay model profile")
            if self.temperature != 0:
                raise ValueError("replay mode requires temperature=0")
        else:
            if self.model_profile_id not in {"deepseek-chat", "workspace-byok"}:
                raise ValueError(
                    "shadow/gated modes require deepseek-chat or workspace-byok "
                    "model profile"
                )
            if self.planner_mode is IncidentModelMode.GATED and self.temperature != 0:
                raise ValueError("gated mode requires deterministic temperature=0")

        if self.model_profile_id != "workspace-byok" and self.provider_profile_id:
            raise ValueError(
                "provider_profile_id is only valid for workspace-byok model profile"
            )

        if self.memory_mode is IncidentMemoryMode.OFF:
            if self.memory_top_k != 0 or self.site_profile_id is not None:
                raise ValueError("memory off requires top_k=0 and no site profile")
        elif self.memory_top_k < 1 or self.site_profile_id is None:
            raise ValueError("approved-site memory requires site profile and top_k>=1")
        return self

    def profile_sha256(self) -> str:
        return _sha256(self.model_dump(mode="json"))


class ModelProfileCapability(ProductModel):
    profile_id: str
    label: str
    provider_kind: Literal[
        "deterministic",
        "deepseek_openai_compatible",
        "local_replay",
    ]
    configured_model: str
    supported_modes: list[IncidentModelMode]
    availability: Literal["AVAILABLE", "BLOCKED", "NOT_CONFIGURED"]
    reason_codes: list[str]
    temperature_min: float = Field(ge=0.0, le=0.3)
    temperature_max: float = Field(ge=0.0, le=0.3)
    max_output_tokens: int = Field(ge=200, le=2_000)
    model_context_limit: int | None = None
    context_limit_status: Literal["NOT_APPLICABLE", "UNVERIFIED"]
    raw_image_transmission_supported: Literal[False] = False


class MemoryProfileCapability(ProductModel):
    profile_id: str
    label: str
    availability: Literal["AVAILABLE", "NOT_CONFIGURED"]
    reason_codes: list[str]
    scope: Literal["site_approved_historical_reference_only"] = (
        "site_approved_historical_reference_only"
    )
    may_set_current_case_fact: Literal[False] = False


class IncidentRuntimeCapabilities(ProductModel):
    schema_version: Literal["visiondata-gate.incident-runtime-capabilities.v1"] = (
        "visiondata-gate.incident-runtime-capabilities.v1"
    )
    model_profiles: list[ModelProfileCapability]
    memory_profiles: list[MemoryProfileCapability]
    configurable_fields: list[str]
    frozen_fields: list[str]
    server_policy_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    secrets_exposed: Literal[False] = False
    production_decision_authority: Literal["human_only"] = "human_only"


class IncidentRuntimeProfileBinding(ProductModel):
    schema_version: Literal["visiondata-gate.incident-runtime-profile-binding.v1"] = (
        "visiondata-gate.incident-runtime-profile-binding.v1"
    )
    case_id: str
    case_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    profile: IncidentRuntimeProfile
    profile_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    planner_config_sha256: str | None = Field(default=None, pattern=r"^[0-9a-f]{64}$")
    planner_connection_status: str
    governed_context_receipt_sha256: str | None = Field(
        default=None, pattern=r"^[0-9a-f]{64}$"
    )
    governed_memory_planning_input_sha256: str | None = Field(
        default=None,
        pattern=r"^[0-9a-f]{64}$",
    )
    governed_memory_retrieval_receipt_sha256: str | None = Field(
        default=None,
        pattern=r"^[0-9a-f]{64}$",
    )
    selected_memory_count: int = Field(ge=0, le=12)
    rejected_memory_count: int = Field(ge=0)
    model_context_limit: int | None = None
    context_limit_status: Literal["NOT_APPLICABLE", "UNVERIFIED"]
    binding_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    secrets_retained: Literal[False] = False
    raw_images_transmitted: Literal[False] = False
    production_decision_authority: Literal["human_only"] = "human_only"


def build_incident_runtime_capabilities(
    *,
    environment: Mapping[str, str] | None = None,
    memory_profile_ids: list[str] | None = None,
) -> IncidentRuntimeCapabilities:
    source = os.environ if environment is None else environment
    configured_model = source.get(
        "VISIONDATA_INCIDENT_MODEL_NAME", DEFAULT_INCIDENT_MODEL_NAME
    ).strip()
    key = source.get(INCIDENT_MODEL_API_KEY_ENV, "").strip()
    remote_authorized = _parse_bool(
        source.get("VISIONDATA_INCIDENT_MODEL_ALLOW_REMOTE")
    )
    remote_reasons: list[str] = []
    if not remote_authorized:
        remote_reasons.append("REMOTE_CALL_NOT_AUTHORIZED")
    if key in {"", "YOUR_API_KEY"}:
        remote_reasons.append("API_KEY_NOT_CONFIGURED")
    replay_path = source.get("VISIONDATA_INCIDENT_MODEL_REPLAY_PATH", "").strip()
    replay_available = bool(replay_path) and Path(replay_path).expanduser().is_file()
    memories = sorted(set(memory_profile_ids or []))
    stable = {
        "model_profiles": [
            {
                "profile_id": "deterministic-off",
                "label": "确定性证据策略（不调用模型）",
                "provider_kind": "deterministic",
                "configured_model": "none",
                "supported_modes": [IncidentModelMode.OFF],
                "availability": "AVAILABLE",
                "reason_codes": [],
                "temperature_min": 0.0,
                "temperature_max": 0.0,
                "max_output_tokens": 2_000,
                "model_context_limit": None,
                "context_limit_status": "NOT_APPLICABLE",
                "raw_image_transmission_supported": False,
            },
            {
                "profile_id": "deepseek-chat",
                "label": "DeepSeek 证据缺口规划器",
                "provider_kind": "deepseek_openai_compatible",
                "configured_model": configured_model or DEFAULT_INCIDENT_MODEL_NAME,
                "supported_modes": [IncidentModelMode.SHADOW, IncidentModelMode.GATED],
                "availability": "AVAILABLE" if not remote_reasons else "BLOCKED",
                "reason_codes": remote_reasons,
                "temperature_min": 0.0,
                "temperature_max": 0.3,
                "max_output_tokens": 2_000,
                "model_context_limit": None,
                "context_limit_status": "UNVERIFIED",
                "raw_image_transmission_supported": False,
            },
            {
                "profile_id": "deepseek-replay",
                "label": "本地模型回执 Replay",
                "provider_kind": "local_replay",
                "configured_model": configured_model or DEFAULT_INCIDENT_MODEL_NAME,
                "supported_modes": [IncidentModelMode.REPLAY],
                "availability": "AVAILABLE" if replay_available else "NOT_CONFIGURED",
                "reason_codes": []
                if replay_available
                else ["REPLAY_FILE_NOT_CONFIGURED"],
                "temperature_min": 0.0,
                "temperature_max": 0.0,
                "max_output_tokens": 2_000,
                "model_context_limit": None,
                "context_limit_status": "NOT_APPLICABLE",
                "raw_image_transmission_supported": False,
            },
        ],
        "memory_profiles": [
            {
                "profile_id": profile_id,
                "label": f"{profile_id} · 已批准历史经验",
                "availability": "AVAILABLE",
                "reason_codes": [],
                "scope": "site_approved_historical_reference_only",
                "may_set_current_case_fact": False,
            }
            for profile_id in memories
        ],
        "configurable_fields": [
            "model_profile_id",
            "provider_profile_id",
            "planner_mode",
            "temperature",
            "max_output_tokens",
            "context_budget_tokens",
            "memory_mode",
            "memory_top_k",
            "site_profile_id",
        ],
        "frozen_fields": [
            "provider_endpoint",
            "api_key",
            "remote_host_allowlist",
            "structured_output_schema",
            "frozen_policy_judge",
            "production_decision_authority",
        ],
        "secrets_exposed": False,
        "production_decision_authority": "human_only",
    }
    return IncidentRuntimeCapabilities(
        **stable,
        server_policy_sha256=_sha256(stable),
    )


def planner_from_runtime_profile(
    profile: IncidentRuntimeProfile,
    *,
    environment: Mapping[str, str] | None = None,
) -> IncidentModelPlanner | None:
    """Resolve a safe profile against server-owned provider policy."""

    if profile.planner_mode is IncidentModelMode.OFF:
        return None
    source = os.environ if environment is None else environment
    if profile.planner_mode is IncidentModelMode.REPLAY:
        replay_path = source.get("VISIONDATA_INCIDENT_MODEL_REPLAY_PATH")
        if not replay_path:
            raise ValueError("replay model profile is not configured on the server")
        configured_model = (
            source.get("VISIONDATA_INCIDENT_MODEL_NAME", "").strip()
            or DEFAULT_INCIDENT_MODEL_NAME
        )
        config = IncidentModelPlannerConfig(
            mode=IncidentModelMode.REPLAY,
            model=configured_model,
            replay_path=replay_path,
            temperature=profile.temperature,
            max_tokens=profile.max_output_tokens,
            context_budget_tokens=profile.context_budget_tokens,
        )
        return IncidentModelPlanner(config)

    allowed_hosts = [
        item.strip()
        for item in source.get(
            "VISIONDATA_INCIDENT_MODEL_ALLOWED_HOSTS", DEEPSEEK_API_HOST
        ).split(",")
        if item.strip()
    ]
    configured_model = (
        source.get("VISIONDATA_INCIDENT_MODEL_NAME", "").strip()
        or DEFAULT_INCIDENT_MODEL_NAME
    )
    config = IncidentModelPlannerConfig(
        mode=profile.planner_mode,
        endpoint=resolve_chat_completions_endpoint(
            explicit_endpoint=source.get(INCIDENT_MODEL_ENDPOINT_ENV),
            base_url=source.get(INCIDENT_MODEL_BASE_URL_ENV),
            default_endpoint=DEFAULT_INCIDENT_MODEL_ENDPOINT,
        ),
        model=configured_model,
        allow_remote_model=_parse_bool(
            source.get("VISIONDATA_INCIDENT_MODEL_ALLOW_REMOTE")
        ),
        remote_endpoint_hosts=allowed_hosts,
        timeout_seconds=float(
            source.get("VISIONDATA_INCIDENT_MODEL_TIMEOUT_SECONDS", "20")
        ),
        max_retries=int(source.get("VISIONDATA_INCIDENT_MODEL_MAX_RETRIES", "1")),
        max_recommended_workers=int(
            source.get(
                "VISIONDATA_INCIDENT_MODEL_MAX_RECOMMENDED_WORKERS",
                "4",
            )
        ),
        temperature=profile.temperature,
        max_tokens=profile.max_output_tokens,
        context_budget_tokens=profile.context_budget_tokens,
    )
    return IncidentModelPlanner(
        config,
        api_key=source.get(INCIDENT_MODEL_API_KEY_ENV),
    )


def build_runtime_profile_binding(
    *,
    case_id: str,
    case_sha256: str,
    profile: IncidentRuntimeProfile,
    planner_config_sha256: str | None,
    planner_connection_status: str,
    governed_context_receipt_sha256: str | None,
    selected_memory_count: int,
    rejected_memory_count: int,
    governed_memory_planning_input_sha256: str | None = None,
    governed_memory_retrieval_receipt_sha256: str | None = None,
) -> IncidentRuntimeProfileBinding:
    stable = {
        "schema_version": "visiondata-gate.incident-runtime-profile-binding.v1",
        "case_id": case_id,
        "case_sha256": case_sha256,
        "profile": profile,
        "profile_sha256": profile.profile_sha256(),
        "planner_config_sha256": planner_config_sha256,
        "planner_connection_status": planner_connection_status,
        "governed_context_receipt_sha256": governed_context_receipt_sha256,
        "governed_memory_planning_input_sha256": (
            governed_memory_planning_input_sha256
        ),
        "governed_memory_retrieval_receipt_sha256": (
            governed_memory_retrieval_receipt_sha256
        ),
        "selected_memory_count": selected_memory_count,
        "rejected_memory_count": rejected_memory_count,
        "model_context_limit": None,
        "context_limit_status": (
            "NOT_APPLICABLE"
            if profile.planner_mode in {IncidentModelMode.OFF, IncidentModelMode.REPLAY}
            else "UNVERIFIED"
        ),
        "secrets_retained": False,
        "raw_images_transmitted": False,
        "production_decision_authority": "human_only",
    }
    return IncidentRuntimeProfileBinding(
        **stable,
        binding_sha256=_sha256(stable),
    )


__all__ = [
    "IncidentMemoryMode",
    "IncidentRuntimeCapabilities",
    "IncidentRuntimeProfile",
    "IncidentRuntimeProfileBinding",
    "MemoryProfileCapability",
    "ModelProfileCapability",
    "build_incident_runtime_capabilities",
    "build_runtime_profile_binding",
    "planner_from_runtime_profile",
]
