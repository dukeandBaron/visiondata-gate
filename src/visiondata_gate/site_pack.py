"""Strict, vendor-neutral Factory Site Pack and portability contracts."""

from __future__ import annotations

import hashlib
import hmac
import json
import re
from pathlib import Path, PurePosixPath
from typing import Any, Literal
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

import yaml
from pydantic import Field, field_validator, model_validator

from .evidence import canonical_json_bytes, sha256_file
from .product_models import ProductModel

CanonicalEntity = Literal[
    "Product",
    "Batch",
    "WorkOrder",
    "Recipe",
    "InspectionResult",
]
REQUIRED_CANONICAL_ENTITIES = frozenset(
    {"Product", "Batch", "WorkOrder", "Recipe", "InspectionResult"}
)
SITE_PACK_FILES = (
    "site_manifest.yaml",
    "source_mapping.yaml",
    "connector_profiles.yaml",
    "policy_extensions.yaml",
    "output_profile.yaml",
    "approved_memory.jsonl",
)
_SAFE_ID = re.compile(r"^[a-z0-9][a-z0-9._-]{2,119}$")
_SAFE_FIELD = re.compile(r"^[A-Za-z_][A-Za-z0-9_.-]{0,119}$")
_CREDENTIAL_FRAGMENTS = (
    "api_key",
    "password",
    "secret",
    "access_token",
    "private_key",
    "credential",
)
_SAFE_CREDENTIAL_ATTESTATIONS = frozenset({"credentials_included"})


def _sha256(value: object) -> str:
    return hashlib.sha256(canonical_json_bytes(value)).hexdigest()


def _yaml_object(path: Path) -> dict[str, Any]:
    payload = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise TypeError(f"Site Pack document must be an object: {path.name}")
    return payload


def _contains_credential_key(value: object) -> bool:
    if isinstance(value, dict):
        for key, child in value.items():
            normalized = str(key).casefold()
            if normalized not in _SAFE_CREDENTIAL_ATTESTATIONS and any(
                fragment in normalized for fragment in _CREDENTIAL_FRAGMENTS
            ):
                return True
            if _contains_credential_key(child):
                return True
    elif isinstance(value, list):
        return any(_contains_credential_key(item) for item in value)
    return False


def _validate_relative_reference(value: str) -> str:
    normalized = value.replace("\\", "/")
    path = PurePosixPath(normalized)
    if path.is_absolute() or ".." in path.parts or not path.parts:
        raise ValueError(
            "Site Pack connector paths must be relative and traversal-free"
        )
    return path.as_posix()


class SiteManifest(ProductModel):
    schema_version: Literal["visiondata-gate.site-manifest.v1"] = (
        "visiondata-gate.site-manifest.v1"
    )
    site_id: str = Field(pattern=r"^[a-z0-9][a-z0-9._-]{2,119}$")
    pack_version: str = Field(pattern=r"^[0-9]+\.[0-9]+\.[0-9]+$")
    site_name: str = Field(min_length=3, max_length=200)
    timezone: str = Field(min_length=1, max_length=80)
    quality_owner_roles: list[str] = Field(min_length=1, max_length=12)
    supported_case_types: list[
        Literal[
            "POST_CHANGE_NG_SPIKE",
            "NEW_DEFECT_CLUSTER",
            "RECIPE_DRIFT_SUSPECTED",
        ]
    ] = Field(min_length=1)
    production_site_claimed: Literal[False] = False

    @field_validator("timezone")
    @classmethod
    def validate_timezone(cls, value: str) -> str:
        try:
            ZoneInfo(value)
        except ZoneInfoNotFoundError as error:
            raise ValueError("Site Pack timezone is not an IANA timezone") from error
        return value

    @field_validator("quality_owner_roles")
    @classmethod
    def unique_roles(cls, values: list[str]) -> list[str]:
        if len(values) != len(set(values)) or any(
            not value.strip() for value in values
        ):
            raise ValueError("Site Pack owner roles must be unique and non-empty")
        return values


class SourceFieldRule(ProductModel):
    source_field: str = Field(min_length=1, max_length=120)
    aliases: list[str] = Field(default_factory=list, max_length=12)
    required: bool = True
    transform: Literal["string", "upper_string", "lower_string"] = "string"

    @field_validator("source_field")
    @classmethod
    def validate_source_field(cls, value: str) -> str:
        if not _SAFE_FIELD.fullmatch(value):
            raise ValueError("source mapping field contains unsupported characters")
        return value

    @field_validator("aliases")
    @classmethod
    def validate_aliases(cls, values: list[str]) -> list[str]:
        if len(values) != len(set(values)):
            raise ValueError("source field aliases must be unique")
        if any(not _SAFE_FIELD.fullmatch(value) for value in values):
            raise ValueError("source field alias contains unsupported characters")
        return values


class SourceMapping(ProductModel):
    schema_version: Literal["visiondata-gate.source-mapping.v1"] = (
        "visiondata-gate.source-mapping.v1"
    )
    canonical_entities: dict[CanonicalEntity, SourceFieldRule]
    unmapped_fields_policy: Literal["IGNORE_AND_REPORT"] = "IGNORE_AND_REPORT"

    @model_validator(mode="after")
    def require_core_entities(self) -> SourceMapping:
        missing = REQUIRED_CANONICAL_ENTITIES - set(self.canonical_entities)
        if missing:
            raise ValueError(
                "Site Pack is missing canonical mappings: " + ", ".join(sorted(missing))
            )
        candidates = [
            field
            for rule in self.canonical_entities.values()
            for field in [rule.source_field, *rule.aliases]
        ]
        if len(candidates) != len(set(candidates)):
            raise ValueError(
                "one source field cannot map to multiple canonical entities"
            )
        return self


class ConnectorSpec(ProductModel):
    connector_type: Literal[
        "local_directory",
        "json_fixture",
        "csv_fixture",
        "offline_export",
        "rest_reference",
        "opcua_read_only_reference",
        "visionmaster_offline_export",
    ]
    relative_path: str | None = Field(default=None, max_length=240)
    endpoint_alias: str | None = Field(default=None, max_length=120)
    read_only: Literal[True] = True
    credentials_included: Literal[False] = False
    live_connection_claimed: Literal[False] = False

    @field_validator("relative_path")
    @classmethod
    def validate_relative_path(cls, value: str | None) -> str | None:
        return _validate_relative_reference(value) if value is not None else None

    @model_validator(mode="after")
    def validate_reference_shape(self) -> ConnectorSpec:
        local_types = {
            "local_directory",
            "json_fixture",
            "csv_fixture",
            "offline_export",
            "visionmaster_offline_export",
        }
        if self.connector_type in local_types and self.relative_path is None:
            raise ValueError("offline/local connector requires a relative_path")
        if self.connector_type not in local_types and self.endpoint_alias is None:
            raise ValueError("reference connector requires a non-secret endpoint_alias")
        return self


class ConnectorProfiles(ProductModel):
    schema_version: Literal["visiondata-gate.connector-profiles.v1"] = (
        "visiondata-gate.connector-profiles.v1"
    )
    connectors: dict[str, ConnectorSpec] = Field(min_length=1)

    @field_validator("connectors")
    @classmethod
    def validate_connector_ids(
        cls, values: dict[str, ConnectorSpec]
    ) -> dict[str, ConnectorSpec]:
        if any(not _SAFE_ID.fullmatch(key) for key in values):
            raise ValueError("connector identifiers must be stable safe IDs")
        return values


class PolicyExtensions(ProductModel):
    schema_version: Literal["visiondata-gate.policy-extensions.v1"] = (
        "visiondata-gate.policy-extensions.v1"
    )
    extension_version: str = Field(pattern=r"^[0-9]+\.[0-9]+\.[0-9]+$")
    display_labels: dict[str, str] = Field(default_factory=dict, max_length=64)
    investigation_hints: list[str] = Field(default_factory=list, max_length=32)
    frozen_policy_mutation: Literal[False] = False
    equipment_control_enabled: Literal[False] = False
    production_release_enabled: Literal[False] = False


class OutputProfile(ProductModel):
    schema_version: Literal["visiondata-gate.output-profile.v1"] = (
        "visiondata-gate.output-profile.v1"
    )
    profile_version: str = Field(pattern=r"^[0-9]+\.[0-9]+\.[0-9]+$")
    primary_owner_role: str = Field(min_length=1, max_length=120)
    escalation_owner_roles: list[str] = Field(default_factory=list, max_length=12)
    enabled_formats: list[Literal["json", "html", "csv", "zip"]] = Field(min_length=2)
    show_receipt_details_by_default: bool = False

    @field_validator("enabled_formats")
    @classmethod
    def unique_formats(cls, values: list[str]) -> list[str]:
        if len(values) != len(set(values)):
            raise ValueError("output formats must be unique")
        return values


class FactorySitePack(ProductModel):
    schema_version: Literal["visiondata-gate.factory-site-pack.v1"] = (
        "visiondata-gate.factory-site-pack.v1"
    )
    manifest: SiteManifest
    source_mapping: SourceMapping
    connector_profiles: ConnectorProfiles
    policy_extensions: PolicyExtensions
    output_profile: OutputProfile
    file_sha256: dict[str, str]
    approved_memory_store_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    pack_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    claim_boundary: str = (
        "This Site Pack is a reviewed local configuration and mapping contract. It "
        "does not prove a live factory connection, source authorization, customer "
        "deployment, equipment control, or production release."
    )


class SitePackValidationReceipt(ProductModel):
    schema_version: Literal["visiondata-gate.site-pack-validation.v1"] = (
        "visiondata-gate.site-pack-validation.v1"
    )
    site_id: str
    pack_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    status: Literal["PASS"] = "PASS"
    required_file_count: int = Field(ge=6)
    validated_file_count: int = Field(ge=6)
    canonical_required_count: int = Field(ge=5)
    canonical_mapped_count: int = Field(ge=5)
    canonical_schema_coverage: float = Field(ge=0.0, le=1.0)
    unsafe_connector_path_count: Literal[0] = 0
    credential_field_count: Literal[0] = 0
    live_connection_probe_performed: Literal[False] = False
    receipt_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")


class CanonicalMappingResult(ProductModel):
    schema_version: Literal["visiondata-gate.canonical-mapping-result.v1"] = (
        "visiondata-gate.canonical-mapping-result.v1"
    )
    site_id: str
    site_pack_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    source_record_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    status: Literal["PASS", "FAIL_MISSING_REQUIRED_FIELDS"]
    canonical_entities: dict[CanonicalEntity, str]
    mapped_entities: list[CanonicalEntity]
    missing_entities: list[CanonicalEntity]
    ignored_source_fields: list[str]
    canonical_mapping_coverage: float = Field(ge=0.0, le=1.0)
    raw_source_record_retained: Literal[False] = False
    result_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")


class SitePortabilityRecord(ProductModel):
    site_id: str
    pack_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    validation_receipt_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    mapping_result_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    mapping_status: str
    canonical_mapping_coverage: float = Field(ge=0.0, le=1.0)
    missing_field_count: int = Field(ge=0)


class SitePortabilityReport(ProductModel):
    schema_version: Literal["visiondata-gate.site-portability-report.v1"] = (
        "visiondata-gate.site-portability-report.v1"
    )
    protocol: Literal["SAME_CORE_TWO_SITE_PACKS_V1"] = "SAME_CORE_TWO_SITE_PACKS_V1"
    core_implementation_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    site_count: int = Field(ge=2)
    records: list[SitePortabilityRecord] = Field(min_length=2)
    core_code_change_count: Literal[0] = 0
    distinct_core_implementation_count: Literal[1] = 1
    site_pack_validation_rate: float = Field(ge=0.0, le=1.0)
    canonical_field_mapping_coverage: float = Field(ge=0.0, le=1.0)
    replay_consistency: float = Field(ge=0.0, le=1.0)
    time_to_onboard_new_site: Literal["NOT_MEASURED"] = "NOT_MEASURED"
    status: Literal["PASS", "FAIL"]
    report_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")


def load_factory_site_pack(root: str | Path) -> FactorySitePack:
    source = Path(root).expanduser().resolve(strict=True)
    if not source.is_dir():
        raise ValueError("Factory Site Pack root must be a directory")
    paths = {name: source / name for name in SITE_PACK_FILES}
    missing = [name for name, path in paths.items() if not path.is_file()]
    if missing:
        raise ValueError("Factory Site Pack is incomplete: " + ", ".join(missing))
    documents = {
        name: _yaml_object(path)
        for name, path in paths.items()
        if name.endswith(".yaml")
    }
    if any(_contains_credential_key(document) for document in documents.values()):
        raise ValueError("Factory Site Pack must not contain credential-like fields")
    manifest = SiteManifest.model_validate(documents["site_manifest.yaml"])
    source_mapping = SourceMapping.model_validate(documents["source_mapping.yaml"])
    connector_profiles = ConnectorProfiles.model_validate(
        documents["connector_profiles.yaml"]
    )
    policy_extensions = PolicyExtensions.model_validate(
        documents["policy_extensions.yaml"]
    )
    output_profile = OutputProfile.model_validate(documents["output_profile.yaml"])
    file_hashes = {name: sha256_file(path) for name, path in sorted(paths.items())}
    stable = {
        "schema_version": "visiondata-gate.factory-site-pack.v1",
        "manifest": manifest,
        "source_mapping": source_mapping,
        "connector_profiles": connector_profiles,
        "policy_extensions": policy_extensions,
        "output_profile": output_profile,
        "file_sha256": file_hashes,
        "approved_memory_store_sha256": file_hashes["approved_memory.jsonl"],
        "claim_boundary": FactorySitePack.model_fields["claim_boundary"].default,
    }
    return FactorySitePack(**stable, pack_sha256=_sha256(stable))


def verify_factory_site_pack(pack: FactorySitePack) -> None:
    payload = pack.model_dump(mode="json")
    stored = payload.pop("pack_sha256")
    if not hmac.compare_digest(stored, _sha256(payload)):
        raise ValueError("Factory Site Pack failed SHA-256 validation")
    if pack.output_profile.primary_owner_role not in pack.manifest.quality_owner_roles:
        raise ValueError("Site Pack output owner is not an allowed quality owner role")


def build_site_pack_validation_receipt(
    pack: FactorySitePack,
) -> SitePackValidationReceipt:
    verify_factory_site_pack(pack)
    stable = {
        "schema_version": "visiondata-gate.site-pack-validation.v1",
        "site_id": pack.manifest.site_id,
        "pack_sha256": pack.pack_sha256,
        "status": "PASS",
        "required_file_count": len(SITE_PACK_FILES),
        "validated_file_count": len(pack.file_sha256),
        "canonical_required_count": len(REQUIRED_CANONICAL_ENTITIES),
        "canonical_mapped_count": len(
            REQUIRED_CANONICAL_ENTITIES & set(pack.source_mapping.canonical_entities)
        ),
        "canonical_schema_coverage": 1.0,
        "unsafe_connector_path_count": 0,
        "credential_field_count": 0,
        "live_connection_probe_performed": False,
    }
    return SitePackValidationReceipt(**stable, receipt_sha256=_sha256(stable))


def _mapped_value(rule: SourceFieldRule, source: dict[str, Any]) -> str | None:
    for field in [rule.source_field, *rule.aliases]:
        if field in source and source[field] is not None:
            value = str(source[field]).strip()
            if not value:
                continue
            if rule.transform == "upper_string":
                return value.upper()
            if rule.transform == "lower_string":
                return value.lower()
            return value
    return None


def map_source_record(
    pack: FactorySitePack,
    source_record: dict[str, Any],
) -> CanonicalMappingResult:
    verify_factory_site_pack(pack)
    canonical: dict[CanonicalEntity, str] = {}
    used_fields: set[str] = set()
    missing: list[CanonicalEntity] = []
    for entity, rule in pack.source_mapping.canonical_entities.items():
        value = _mapped_value(rule, source_record)
        if value is None:
            if rule.required:
                missing.append(entity)
            continue
        canonical[entity] = value
        for field in [rule.source_field, *rule.aliases]:
            if field in source_record and source_record[field] is not None:
                used_fields.add(field)
                break
    mapped = sorted(canonical)
    coverage = len(mapped) / len(REQUIRED_CANONICAL_ENTITIES)
    stable = {
        "schema_version": "visiondata-gate.canonical-mapping-result.v1",
        "site_id": pack.manifest.site_id,
        "site_pack_sha256": pack.pack_sha256,
        "source_record_sha256": _sha256(source_record),
        "status": "FAIL_MISSING_REQUIRED_FIELDS" if missing else "PASS",
        "canonical_entities": canonical,
        "mapped_entities": mapped,
        "missing_entities": sorted(missing),
        "ignored_source_fields": sorted(set(source_record) - used_fields),
        "canonical_mapping_coverage": round(coverage, 6),
        "raw_source_record_retained": False,
    }
    return CanonicalMappingResult(**stable, result_sha256=_sha256(stable))


def verify_canonical_mapping_result(result: CanonicalMappingResult) -> None:
    payload = result.model_dump(mode="json")
    stored = payload.pop("result_sha256")
    if not hmac.compare_digest(stored, _sha256(payload)):
        raise ValueError("canonical mapping result failed SHA-256 validation")
    if (result.status == "PASS") != (not result.missing_entities):
        raise ValueError("canonical mapping status does not match missing fields")


def run_site_portability_check(
    cases: list[tuple[str | Path, dict[str, Any]]],
) -> SitePortabilityReport:
    if len(cases) < 2:
        raise ValueError("site portability check requires at least two Site Packs")
    records: list[SitePortabilityRecord] = []
    canonical_shapes: list[set[str]] = []
    for root, source_record in cases:
        pack = load_factory_site_pack(root)
        validation = build_site_pack_validation_receipt(pack)
        mapping = map_source_record(pack, source_record)
        verify_canonical_mapping_result(mapping)
        records.append(
            SitePortabilityRecord(
                site_id=pack.manifest.site_id,
                pack_sha256=pack.pack_sha256,
                validation_receipt_sha256=validation.receipt_sha256,
                mapping_result_sha256=mapping.result_sha256,
                mapping_status=mapping.status,
                canonical_mapping_coverage=mapping.canonical_mapping_coverage,
                missing_field_count=len(mapping.missing_entities),
            )
        )
        canonical_shapes.append(set(mapping.canonical_entities))
    validation_rate = sum(record.mapping_status == "PASS" for record in records) / len(
        records
    )
    mapping_coverage = sum(
        record.canonical_mapping_coverage for record in records
    ) / len(records)
    reference_shape = canonical_shapes[0]
    replay_consistency = sum(
        shape == reference_shape for shape in canonical_shapes
    ) / len(canonical_shapes)
    core_sha = sha256_file(Path(__file__).resolve())
    passed = (
        validation_rate == 1.0 and mapping_coverage == 1.0 and replay_consistency == 1.0
    )
    stable = {
        "schema_version": "visiondata-gate.site-portability-report.v1",
        "protocol": "SAME_CORE_TWO_SITE_PACKS_V1",
        "core_implementation_sha256": core_sha,
        "site_count": len(records),
        "records": records,
        "core_code_change_count": 0,
        "distinct_core_implementation_count": 1,
        "site_pack_validation_rate": round(validation_rate, 6),
        "canonical_field_mapping_coverage": round(mapping_coverage, 6),
        "replay_consistency": round(replay_consistency, 6),
        "time_to_onboard_new_site": "NOT_MEASURED",
        "status": "PASS" if passed else "FAIL",
    }
    return SitePortabilityReport(**stable, report_sha256=_sha256(stable))


def load_sample_record(path: str | Path) -> dict[str, Any]:
    source = Path(path).expanduser().resolve(strict=True)
    payload = json.loads(source.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise TypeError("sample site record must be a JSON object")
    return payload


__all__ = [
    "CanonicalMappingResult",
    "ConnectorProfiles",
    "FactorySitePack",
    "OutputProfile",
    "PolicyExtensions",
    "SiteManifest",
    "SitePackValidationReceipt",
    "SitePortabilityReport",
    "SourceMapping",
    "build_site_pack_validation_receipt",
    "load_factory_site_pack",
    "load_sample_record",
    "map_source_record",
    "run_site_portability_check",
    "verify_canonical_mapping_result",
    "verify_factory_site_pack",
]
