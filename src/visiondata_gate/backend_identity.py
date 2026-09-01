"""Typed connection/identity receipts for optional model backends."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from .network_resilience import HTTPExchangeReceipt


class BackendIdentityReceipt(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: Literal["visiondata-gate.backend-identity.v1"] = (
        "visiondata-gate.backend-identity.v1"
    )
    profile: Literal["deterministic", "openai_compatible", "longcat"]
    status: Literal[
        "NOT_APPLICABLE",
        "REAL_BACKEND_NOT_CONNECTED",
        "BACKEND_RESPONDED_IDENTITY_UNVERIFIED",
        "CONTRACT_CONNECTED_LOCAL_TEST",
        "REAL_BACKEND_CONNECTED",
    ]
    execution_mode: Literal["contract_test", "real"]
    endpoint_scope: Literal["none", "local", "remote"]
    configured_model: str = Field(min_length=1)
    reported_model_ids: list[str] = Field(default_factory=list)
    configured_model_reported: bool = False
    identity_strength: Literal[
        "none", "response_only", "endpoint_attested_model_id"
    ] = "none"
    probe_receipt: HTTPExchangeReceipt | None = None
    model_response_accepted: bool = False
    boundary_notice: str = (
        "Endpoint-reported model identity is not a checkpoint hash or an independent "
        "verification of model weights; Frozen Policy Judge authority is unchanged."
    )


def deterministic_identity(model: str) -> BackendIdentityReceipt:
    return BackendIdentityReceipt(
        profile="deterministic",
        status="NOT_APPLICABLE",
        execution_mode="contract_test",
        endpoint_scope="none",
        configured_model=model,
    )


__all__ = ["BackendIdentityReceipt", "deterministic_identity"]
