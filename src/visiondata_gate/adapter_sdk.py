"""Minimal read-only Adapter SDK and offline conformance verifier."""

from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path
from typing import Any, Literal

from pydantic import Field, model_validator

from .evidence import canonical_json_bytes, sha256_file, write_canonical_json
from .product_models import ProductModel


class AdapterManifest(ProductModel):
    schema_version: Literal["visiondata-gate.adapter-manifest.v1"]
    adapter_id: str = Field(pattern=r"^[a-z0-9][a-z0-9._-]+$")
    adapter_version: str = Field(pattern=r"^[0-9]+\.[0-9]+\.[0-9]+$")
    entrypoint: str = Field(pattern=r"^[a-zA-Z_][a-zA-Z0-9_.]*:[a-zA-Z_][a-zA-Z0-9_]*$")
    source_kinds: list[str] = Field(min_length=1)
    capabilities: list[str] = Field(min_length=1)
    input_contract_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    output_schema_ref: Literal["schemas/adapter-observation.schema.json"]
    read_only: Literal[True]
    raw_bytes_export_allowed: Literal[False]
    network_access_required: bool
    timeout_ms: int = Field(ge=1, le=300000)
    license_spdx: str = Field(min_length=2)
    claim_boundary: str = Field(min_length=20)


class AdapterFinding(ProductModel):
    finding_id: str = Field(min_length=1)
    tool: str = Field(min_length=1)
    code: str = Field(min_length=1)
    severity: Literal["low", "medium", "high", "critical"]
    summary: str = Field(min_length=1)
    redacted_sample_ids: list[str] = Field(default_factory=list)
    evidence_span: list[str] = Field(min_length=1)
    reason_trace: list[str] = Field(min_length=1)
    source_refs: list[str] = Field(min_length=1)
    result_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    recommended_action: str = Field(min_length=1)


class AdapterObservation(ProductModel):
    schema_version: Literal["visiondata-gate.adapter-observation.v1"]
    adapter_id: str
    adapter_version: str
    invocation_id: str = Field(min_length=1)
    input_snapshot_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    status: Literal["OK", "DEFER", "ERROR"]
    findings: list[AdapterFinding]
    metrics: dict[str, int | float | str | bool]
    tool_trace_ref: str = Field(min_length=1)
    raw_payload_included: Literal[False]
    error_class: str | None = None
    claim_boundary: str = Field(min_length=20)

    @model_validator(mode="after")
    def validate_status_semantics(self) -> "AdapterObservation":
        if self.status == "ERROR" and not self.error_class:
            raise ValueError("ERROR observations require a path-redacted error_class")
        if self.status == "OK" and self.error_class is not None:
            raise ValueError("OK observations cannot carry an error_class")
        finding_ids = [item.finding_id for item in self.findings]
        if len(finding_ids) != len(set(finding_ids)):
            raise ValueError("finding_id values must be unique")
        return self


_FORBIDDEN_KEY_FRAGMENTS = (
    "api_key",
    "password",
    "secret",
    "access_token",
    "refresh_token",
    "root_path",
    "payload_bytes",
    "image_bytes",
    "file_bytes",
    "raw_content",
)
_WINDOWS_ABSOLUTE = re.compile(r"^[a-zA-Z]:[\\/]")


def _unsafe_payload_reasons(value: Any, *, key_path: str = "$") -> list[str]:
    reasons: list[str] = []
    if isinstance(value, dict):
        for key, child in value.items():
            normalized = str(key).casefold()
            if any(fragment in normalized for fragment in _FORBIDDEN_KEY_FRAGMENTS):
                reasons.append(f"forbidden_key:{key_path}.{key}")
            reasons.extend(_unsafe_payload_reasons(child, key_path=f"{key_path}.{key}"))
    elif isinstance(value, list):
        for index, child in enumerate(value):
            reasons.extend(
                _unsafe_payload_reasons(child, key_path=f"{key_path}[{index}]")
            )
    elif isinstance(value, str):
        if (
            _WINDOWS_ABSOLUTE.match(value)
            or value.startswith("/")
            or value.startswith("\\\\")
        ):
            reasons.append(f"absolute_path:{key_path}")
    return reasons


def _json_object(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError("document root must be an object")
    return value


def build_adapter_conformance_receipt(
    manifest_path: str | Path,
    observation_path: str | Path,
) -> dict[str, Any]:
    manifest_source = Path(manifest_path).expanduser().resolve(strict=True)
    observation_source = Path(observation_path).expanduser().resolve(strict=True)
    checks: list[dict[str, str]] = []

    def check(check_id: str, passed: bool, note: str) -> None:
        checks.append(
            {"check_id": check_id, "status": "PASS" if passed else "FAIL", "note": note}
        )

    try:
        raw_manifest = _json_object(manifest_source)
        manifest = AdapterManifest.model_validate(raw_manifest)
        check("manifest_schema", True, "Strict manifest schema accepted.")
    except (OSError, ValueError, json.JSONDecodeError):
        raw_manifest = {}
        manifest = None
        check("manifest_schema", False, "Manifest schema validation failed.")
    try:
        raw_observation = _json_object(observation_source)
        observation = AdapterObservation.model_validate(raw_observation)
        check("observation_schema", True, "Strict observation schema accepted.")
    except (OSError, ValueError, json.JSONDecodeError):
        raw_observation = {}
        observation = None
        check("observation_schema", False, "Observation schema validation failed.")

    unsafe = [
        *_unsafe_payload_reasons(raw_manifest),
        *_unsafe_payload_reasons(raw_observation),
    ]
    check(
        "path_and_secret_redaction",
        not unsafe,
        (
            "No absolute path, raw-byte field, or credential-like key was found."
            if not unsafe
            else f"Detected {len(unsafe)} forbidden path or key location(s)."
        ),
    )
    if manifest is not None and observation is not None:
        identity_matches = (
            manifest.adapter_id == observation.adapter_id
            and manifest.adapter_version == observation.adapter_version
        )
        check(
            "adapter_identity_binding",
            identity_matches,
            "Observation identity matches the reviewed manifest."
            if identity_matches
            else "Observation identity does not match the manifest.",
        )
        check(
            "read_only_boundary",
            manifest.read_only
            and not manifest.raw_bytes_export_allowed
            and not observation.raw_payload_included,
            "Adapter and observation both preserve the read-only/no-raw-export boundary.",
        )
        evidence_complete = all(
            item.evidence_span and item.reason_trace and item.source_refs
            for item in observation.findings
        )
        check(
            "finding_evidence_lineage",
            evidence_complete,
            "Every finding carries evidence_span, reason_trace, and source_refs.",
        )
        check(
            "input_snapshot_binding",
            len(observation.input_snapshot_sha256) == 64,
            "Observation is bound to one SHA-256 input snapshot.",
        )
    else:
        for check_id, note in (
            ("adapter_identity_binding", "Skipped because a schema failed."),
            ("read_only_boundary", "Skipped because a schema failed."),
            ("finding_evidence_lineage", "Skipped because a schema failed."),
            ("input_snapshot_binding", "Skipped because a schema failed."),
        ):
            check(check_id, False, note)

    stable = {
        "schema_version": "visiondata-gate.adapter-conformance.v1",
        "status": "PASS"
        if all(item["status"] == "PASS" for item in checks)
        else "FAIL",
        "manifest_sha256": sha256_file(manifest_source),
        "observation_sha256": sha256_file(observation_source),
        "checks": checks,
        "actual_model_call_count": 0,
        "network_probe_performed": False,
        "claim_boundary": (
            "This offline receipt verifies schema, identity, redaction, read-only, and "
            "evidence-lineage contracts. It does not prove adapter accuracy, source "
            "authorization, hosted connectivity, or production safety."
        ),
    }
    stable["receipt_sha256"] = hashlib.sha256(canonical_json_bytes(stable)).hexdigest()
    return stable


def verify_adapter_conformance(
    manifest_path: str | Path,
    observation_path: str | Path,
    *,
    output: str | Path | None = None,
) -> dict[str, Any]:
    receipt = build_adapter_conformance_receipt(manifest_path, observation_path)
    if output is not None:
        write_canonical_json(Path(output).expanduser().resolve(), receipt)
    return receipt


__all__ = [
    "AdapterFinding",
    "AdapterManifest",
    "AdapterObservation",
    "build_adapter_conformance_receipt",
    "verify_adapter_conformance",
]
