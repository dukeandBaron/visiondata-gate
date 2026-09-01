"""Connection adapters for VGGT/OmniVGGT normalized geometry evidence.

The upstream projects expose Python inference entrypoints, not one shared HTTP
API.  This module therefore defines a narrow VisionData Gate protocol that a
trusted local runner or separately deployed service can implement.  Protocol
contract tests and real checkpoint-bound runs remain distinct statuses.
"""

from __future__ import annotations

import base64
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal
import urllib.parse

from pydantic import BaseModel, ConfigDict, Field, field_validator

from .contracts import BatchContract, BatchManifest
from .evidence import canonical_json_bytes, sha256_bytes, sha256_file
from .geometry_consistency import GeometryEvidenceBundle
from .network_resilience import (
    HTTPClientPolicy,
    HTTPExchangeReceipt,
    HTTPTransportError,
    ResilientJSONClient,
)
from .pipeline import compute_batch_digest


class GeometryBackendModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class GeometryBackendConfig(GeometryBackendModel):
    backend: Literal["vggt", "omnivggt"]
    endpoint: str
    allowed_hosts: list[str] = Field(default_factory=list)
    allow_remote: bool = False
    allow_image_upload: bool = False
    execution_mode: Literal["contract_test", "real"] = "contract_test"
    expected_checkpoint_sha256: str | None = Field(
        default=None, min_length=64, max_length=64, pattern=r"^[0-9a-f]{64}$"
    )
    timeout_seconds: float = Field(default=30.0, ge=0.01, le=120.0)
    max_retries: int = Field(default=1, ge=0, le=3)
    backoff_seconds: float = Field(default=0.05, ge=0.0, le=10.0)
    circuit_failure_threshold: int = Field(default=2, ge=1, le=10)
    circuit_recovery_seconds: float = Field(default=5.0, ge=0.01, le=300.0)
    max_upload_bytes: int = Field(default=20_000_000, ge=1, le=100_000_000)

    @field_validator("allowed_hosts")
    @classmethod
    def normalize_hosts(cls, values: list[str]) -> list[str]:
        normalized = [value.strip().casefold().rstrip(".") for value in values]
        if any(not value for value in normalized):
            raise ValueError("allowed_hosts cannot contain blank values")
        if len(normalized) != len(set(normalized)):
            raise ValueError("allowed_hosts must be unique")
        return normalized


class GeometryBackendInfo(GeometryBackendModel):
    schema_version: Literal["visiondata-gate.geometry-backend-info.v1"] = (
        "visiondata-gate.geometry-backend-info.v1"
    )
    backend: Literal["vggt", "omnivggt"]
    backend_version: str = Field(min_length=1)
    checkpoint_sha256: str = Field(
        min_length=64, max_length=64, pattern=r"^[0-9a-f]{64}$"
    )
    ready: bool
    output_schema: Literal["visiondata-gate.geometry-evidence.v1"] = (
        "visiondata-gate.geometry-evidence.v1"
    )


class GeometryBackendConnectionReceipt(GeometryBackendModel):
    schema_version: Literal["visiondata-gate.geometry-backend-connection.v1"] = (
        "visiondata-gate.geometry-backend-connection.v1"
    )
    backend: Literal["vggt", "omnivggt"]
    connector_type: Literal["http", "local_callable"]
    status: Literal[
        "CONTRACT_CONNECTED_LOCAL_TEST",
        "REAL_BACKEND_CONNECTED",
        "REAL_BACKEND_NOT_CONNECTED",
    ]
    execution_mode: Literal["contract_test", "real"]
    endpoint_scope: Literal["none", "local", "remote"]
    input_batch_sha256: str = Field(min_length=64, max_length=64)
    expected_checkpoint_sha256: str | None = Field(
        default=None, min_length=64, max_length=64
    )
    observed_checkpoint_sha256: str | None = Field(
        default=None, min_length=64, max_length=64
    )
    checkpoint_hash_match: bool = False
    backend_version: str | None = None
    image_count: int = Field(ge=0)
    upload_bytes: int = Field(ge=0)
    evidence_sha256: str | None = Field(default=None, min_length=64, max_length=64)
    transport_receipts: list[HTTPExchangeReceipt] = Field(default_factory=list)
    error_type: str | None = None
    raw_paths_retained: Literal[False] = False
    raw_images_retained_in_receipt: Literal[False] = False
    boundary_notice: str = (
        "CONTRACT_CONNECTED_LOCAL_TEST proves only this adapter protocol. "
        "REAL_BACKEND_CONNECTED additionally requires explicit real mode and a matching "
        "expected checkpoint SHA-256; neither status proves industrial accuracy."
    )


@dataclass(frozen=True)
class GeometryBackendRun:
    evidence: GeometryEvidenceBundle | None
    receipt: GeometryBackendConnectionReceipt


GeometryRunner = Callable[
    [Path, BatchManifest, BatchContract, str, str],
    GeometryEvidenceBundle | Mapping[str, Any],
]


def _endpoint_parts(config: GeometryBackendConfig) -> tuple[str, str, bool, str]:
    parsed = urllib.parse.urlsplit(config.endpoint.strip())
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        raise ValueError("geometry endpoint must be an absolute http(s) URL")
    if parsed.username or parsed.password or parsed.query or parsed.fragment:
        raise ValueError(
            "geometry endpoint cannot contain credentials, query, or fragment"
        )
    host = (parsed.hostname or "").casefold().rstrip(".")
    local = host in {"127.0.0.1", "localhost", "::1"}
    if not local:
        if not config.allow_remote:
            raise PermissionError("remote geometry endpoint is disabled")
        if not config.allow_image_upload:
            raise PermissionError(
                "remote geometry endpoint requires explicit image-upload consent"
            )
        if config.execution_mode != "real":
            raise PermissionError("remote geometry contract tests are not allowed")
        if parsed.scheme != "https":
            raise PermissionError("remote geometry endpoint requires HTTPS")
        if host not in set(config.allowed_hosts):
            raise PermissionError("remote geometry endpoint host is not allowlisted")
    if config.execution_mode == "real" and config.expected_checkpoint_sha256 is None:
        raise ValueError("real geometry mode requires expected_checkpoint_sha256")
    base = config.endpoint.rstrip("/")
    scope = "local" if local else "remote"
    return f"{base}/model-info", f"{base}/infer", local, scope


def _build_request_payload(
    batch_root: Path,
    manifest: BatchManifest,
    contract: BatchContract,
    *,
    max_upload_bytes: int,
) -> tuple[dict[str, Any], str, int]:
    root = batch_root.expanduser().resolve(strict=True)
    batch_sha256 = compute_batch_digest(root, manifest, contract)
    images: list[dict[str, str]] = []
    total_bytes = 0
    for sample in manifest.samples:
        path = (root / sample.relative_path).resolve(strict=True)
        try:
            path.relative_to(root)
        except ValueError as error:
            raise PermissionError("manifest path escaped batch root") from error
        raw = path.read_bytes()
        total_bytes += len(raw)
        if total_bytes > max_upload_bytes:
            raise ValueError("geometry request exceeds max_upload_bytes")
        images.append(
            {
                "sample_id": sample.sample_id,
                "content_sha256": sha256_bytes(raw),
                "content_base64": base64.b64encode(raw).decode("ascii"),
            }
        )
    return (
        {
            "schema_version": "visiondata-gate.geometry-inference-request.v1",
            "input_batch_sha256": batch_sha256,
            "contract_sha256": sha256_bytes(
                canonical_json_bytes(contract.model_dump(mode="json"))
            ),
            "images": images,
        },
        batch_sha256,
        total_bytes,
    )


def _failed_receipt(
    config: GeometryBackendConfig,
    *,
    batch_sha256: str,
    image_count: int,
    upload_bytes: int,
    scope: str = "none",
    transports: list[HTTPExchangeReceipt] | None = None,
    error_type: str,
    observed_checkpoint_sha256: str | None = None,
    backend_version: str | None = None,
) -> GeometryBackendConnectionReceipt:
    endpoint_scope = scope if scope in {"local", "remote"} else "none"
    return GeometryBackendConnectionReceipt(
        backend=config.backend,
        connector_type="http",
        status="REAL_BACKEND_NOT_CONNECTED",
        execution_mode=config.execution_mode,
        endpoint_scope=endpoint_scope,
        input_batch_sha256=batch_sha256,
        expected_checkpoint_sha256=config.expected_checkpoint_sha256,
        observed_checkpoint_sha256=observed_checkpoint_sha256,
        checkpoint_hash_match=False,
        backend_version=backend_version,
        image_count=image_count,
        upload_bytes=upload_bytes,
        transport_receipts=transports or [],
        error_type=error_type,
    )


def run_http_geometry_backend(
    config: GeometryBackendConfig,
    batch_root: str | Path,
    manifest: BatchManifest,
    contract: BatchContract,
) -> GeometryBackendRun:
    """Probe identity, upload a bounded batch, and validate normalized output."""

    root = Path(batch_root)
    batch_sha256 = "0" * 64
    upload_bytes = 0
    transports: list[HTTPExchangeReceipt] = []
    scope = "none"
    try:
        request_payload, batch_sha256, upload_bytes = _build_request_payload(
            root,
            manifest,
            contract,
            max_upload_bytes=config.max_upload_bytes,
        )
        info_endpoint, infer_endpoint, local, scope = _endpoint_parts(config)
        parsed = urllib.parse.urlsplit(config.endpoint)
        host = (parsed.hostname or "").casefold().rstrip(".")
        allowed_hosts = [host] if local else list(config.allowed_hosts)
        client = ResilientJSONClient(
            HTTPClientPolicy(
                allowed_hosts=allowed_hosts,
                allow_local=local,
                timeout_seconds=config.timeout_seconds,
                max_retries=config.max_retries,
                backoff_seconds=config.backoff_seconds,
                circuit_failure_threshold=config.circuit_failure_threshold,
                circuit_recovery_seconds=config.circuit_recovery_seconds,
                max_response_bytes=20_000_000,
            )
        )
        try:
            info_result = client.request_json(info_endpoint, method="GET")
        except HTTPTransportError as error:
            transports.append(error.receipt)
            raise ConnectionError("geometry identity probe failed") from error
        transports.append(info_result.receipt)
        info = GeometryBackendInfo.model_validate(info_result.payload)
        if not info.ready or info.backend != config.backend:
            raise ValueError("geometry backend identity or readiness mismatch")
        if (
            config.expected_checkpoint_sha256 is not None
            and info.checkpoint_sha256 != config.expected_checkpoint_sha256
        ):
            raise ValueError("geometry checkpoint hash mismatch")
        try:
            inference_result = client.request_json(
                infer_endpoint, method="POST", payload=request_payload
            )
        except HTTPTransportError as error:
            transports.append(error.receipt)
            raise ConnectionError("geometry inference request failed") from error
        transports.append(inference_result.receipt)
        candidate = inference_result.payload.get("evidence", inference_result.payload)
        if not isinstance(candidate, Mapping):
            raise ValueError("geometry inference response is not an evidence object")
        evidence = GeometryEvidenceBundle.model_validate(dict(candidate))
        if evidence.backend != info.backend:
            raise ValueError("geometry response backend drift")
        if evidence.backend_version != info.backend_version:
            raise ValueError("geometry response version drift")
        if evidence.checkpoint_sha256 != info.checkpoint_sha256:
            raise ValueError("geometry response checkpoint drift")
        if evidence.input_batch_sha256 != batch_sha256:
            raise ValueError("geometry response input hash mismatch")
        if evidence.image_count != len(manifest.samples):
            raise ValueError("geometry response image count mismatch")
        evidence_sha256 = sha256_bytes(
            canonical_json_bytes(evidence.model_dump(mode="json"))
        )
        status = (
            "REAL_BACKEND_CONNECTED"
            if config.execution_mode == "real"
            else "CONTRACT_CONNECTED_LOCAL_TEST"
        )
        receipt = GeometryBackendConnectionReceipt(
            backend=config.backend,
            connector_type="http",
            status=status,
            execution_mode=config.execution_mode,
            endpoint_scope=scope,
            input_batch_sha256=batch_sha256,
            expected_checkpoint_sha256=config.expected_checkpoint_sha256,
            observed_checkpoint_sha256=info.checkpoint_sha256,
            checkpoint_hash_match=(
                config.expected_checkpoint_sha256 == info.checkpoint_sha256
                if config.expected_checkpoint_sha256 is not None
                else config.execution_mode == "contract_test"
            ),
            backend_version=info.backend_version,
            image_count=len(manifest.samples),
            upload_bytes=upload_bytes,
            evidence_sha256=evidence_sha256,
            transport_receipts=transports,
        )
        return GeometryBackendRun(evidence=evidence, receipt=receipt)
    except Exception as error:
        return GeometryBackendRun(
            evidence=None,
            receipt=_failed_receipt(
                config,
                batch_sha256=batch_sha256,
                image_count=len(manifest.samples),
                upload_bytes=upload_bytes,
                scope=scope,
                transports=transports,
                error_type=type(error).__name__,
            ),
        )


def run_local_geometry_runner(
    runner: GeometryRunner,
    *,
    backend: Literal["vggt", "omnivggt"],
    backend_version: str,
    checkpoint_path: str | Path,
    batch_root: str | Path,
    manifest: BatchManifest,
    contract: BatchContract,
    execution_mode: Literal["contract_test", "real"] = "contract_test",
) -> GeometryBackendRun:
    """Invoke a trusted in-process runner; never imports or shells out by name."""

    root = Path(batch_root).expanduser().resolve(strict=True)
    checkpoint = Path(checkpoint_path).expanduser().resolve(strict=True)
    checkpoint_sha256 = sha256_file(checkpoint)
    batch_sha256 = compute_batch_digest(root, manifest, contract)
    try:
        raw = runner(root, manifest, contract, batch_sha256, checkpoint_sha256)
        evidence = (
            raw
            if isinstance(raw, GeometryEvidenceBundle)
            else GeometryEvidenceBundle.model_validate(dict(raw))
        )
        if (
            evidence.backend != backend
            or evidence.backend_version != backend_version
            or evidence.input_batch_sha256 != batch_sha256
            or evidence.checkpoint_sha256 != checkpoint_sha256
            or evidence.image_count != len(manifest.samples)
        ):
            raise ValueError("local geometry runner output identity mismatch")
        evidence_sha256 = sha256_bytes(
            canonical_json_bytes(evidence.model_dump(mode="json"))
        )
        receipt = GeometryBackendConnectionReceipt(
            backend=backend,
            connector_type="local_callable",
            status=(
                "REAL_BACKEND_CONNECTED"
                if execution_mode == "real"
                else "CONTRACT_CONNECTED_LOCAL_TEST"
            ),
            execution_mode=execution_mode,
            endpoint_scope="local",
            input_batch_sha256=batch_sha256,
            expected_checkpoint_sha256=checkpoint_sha256,
            observed_checkpoint_sha256=checkpoint_sha256,
            checkpoint_hash_match=True,
            backend_version=backend_version,
            image_count=len(manifest.samples),
            upload_bytes=0,
            evidence_sha256=evidence_sha256,
        )
        return GeometryBackendRun(evidence=evidence, receipt=receipt)
    except Exception as error:
        return GeometryBackendRun(
            evidence=None,
            receipt=GeometryBackendConnectionReceipt(
                backend=backend,
                connector_type="local_callable",
                status="REAL_BACKEND_NOT_CONNECTED",
                execution_mode=execution_mode,
                endpoint_scope="local",
                input_batch_sha256=batch_sha256,
                expected_checkpoint_sha256=checkpoint_sha256,
                observed_checkpoint_sha256=checkpoint_sha256,
                checkpoint_hash_match=True,
                backend_version=backend_version,
                image_count=len(manifest.samples),
                upload_bytes=0,
                error_type=type(error).__name__,
            ),
        )


__all__ = [
    "GeometryBackendConfig",
    "GeometryBackendConnectionReceipt",
    "GeometryBackendInfo",
    "GeometryBackendRun",
    "GeometryRunner",
    "run_http_geometry_backend",
    "run_local_geometry_runner",
]
