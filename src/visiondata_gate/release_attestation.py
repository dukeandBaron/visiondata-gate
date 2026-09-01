"""Fail-closed RC3 release attestation contracts.

This module emits an in-toto-style Statement whose subject is the candidate
release ZIP.  Raw files use ordinary SHA-256 digests.  The complete Statement
is additionally serialized with RFC 8785 JCS and hashed inside a fixed,
length-prefixed domain frame.

The v1 protocol is intentionally unsigned.  It provides deterministic local
integrity binding only; it does not provide signer identity, a trusted time, an
external transparency anchor, or competition submission authorization.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import os
import platform
import re
import subprocess
import tempfile
import zipfile
from collections.abc import Mapping, Sequence
from importlib import metadata
from pathlib import Path, PurePosixPath
from typing import Annotated, Any, Literal, TypeVar

from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator
from pydantic import model_validator

from .audit_envelope import canonical_jcs_bytes
from .evidence import sha256_file
from .package import (
    DEFAULT_SUBMISSION_REQUIRED_PATHS,
    MANIFEST_SCHEMA,
    audit_submission_zip,
    validate_archive_path,
)


ATTESTATION_SCHEMA = "visiondata-gate.release-attestation-envelope.v1"
STATEMENT_TYPE = "https://in-toto.io/Statement/v1"
PREDICATE_TYPE = "https://visiondata-gate.local/attestation/release/v1"
PREDICATE_SCHEMA = "visiondata-gate.release-attestation-predicate.v1"
FULL_TEST_RECEIPT_SCHEMA = "visiondata-gate.full-test-receipt.v2"
CLEAN_EXTRACT_RECEIPT_SCHEMA = "visiondata-gate.clean-extract-receipt.v1"
RELEASE_BUILD_RECEIPT_SCHEMA = "visiondata-gate.release-build-receipt.v1"
VERIFICATION_SCHEMA = "visiondata-gate.release-attestation-verification.v1"

RELEASE_CANONICALIZATION_PROFILE = "rfc8785-jcs-v1"
RELEASE_FRAMING_PROFILE = "visiondata-gate-release-domain-frame-v1"
RELEASE_STATEMENT_DOMAIN = "visiondata-gate/release-attestation/statement/v1"
RELEASE_FRAME_MAGIC = b"visiondata-gate.release-attestation-frame.v1\x00"

_SHA256_PATTERN = r"^[0-9a-f]{64}$"
_GIT_OBJECT_PATTERN = r"^[0-9a-f]{40,64}$"
_REQUIRED_MATERIAL_KINDS = (
    "uv_lock",
    "sbom",
    "full_test_receipt",
    "clean_extract_receipt",
    "build_one_receipt",
    "build_two_receipt",
)
_REQUIRED_TOOLCHAIN_KEYS = frozenset({"git", "python", "uv", "visiondata-gate"})
RC3_REQUIRED_PATHS = tuple(sorted(DEFAULT_SUBMISSION_REQUIRED_PATHS))
_SUBPROCESS_TIMEOUT_SECONDS = 30

Sha256Hex = Annotated[str, Field(pattern=_SHA256_PATTERN)]
GitObjectHex = Annotated[str, Field(pattern=_GIT_OBJECT_PATTERN)]


class ReleaseAttestationError(ValueError):
    """Raised when an attestation input or verification gate fails closed."""


class _StrictModel(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
        frozen=True,
        populate_by_name=True,
        strict=True,
        str_strip_whitespace=False,
    )


def _validate_stable_relative_path(value: str) -> str:
    if not value or "\x00" in value or "\\" in value:
        raise ValueError("path must be a non-empty POSIX relative path")
    if value.startswith("/") or re.match(r"^[A-Za-z]:", value):
        raise ValueError("absolute and drive-qualified paths are forbidden")
    parsed = PurePosixPath(value)
    if parsed.as_posix() != value:
        raise ValueError("path is not in normalized POSIX form")
    if any(part in {"", ".", ".."} or ":" in part for part in parsed.parts):
        raise ValueError("path contains an unsafe or ambiguous component")
    try:
        return validate_archive_path(value)
    except ValueError as exc:
        raise ValueError(f"path violates the portable path contract: {exc}") from exc


def _validate_identifier(value: str, *, label: str) -> str:
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._:/@+-]{2,255}", value):
        raise ValueError(f"{label} uses an invalid identifier syntax")
    return value


class Sha256Digest(_StrictModel):
    sha256: Sha256Hex


class ArtifactBinding(_StrictModel):
    path: str
    digest: Sha256Digest
    size_bytes: int = Field(ge=1)

    @field_validator("path")
    @classmethod
    def validate_path(cls, value: str) -> str:
        return _validate_stable_relative_path(value)


class InTotoSubject(_StrictModel):
    name: str
    digest: Sha256Digest

    @field_validator("name")
    @classmethod
    def validate_name(cls, value: str) -> str:
        return _validate_stable_relative_path(value)


class GitSourceState(_StrictModel):
    commit: GitObjectHex
    tree: GitObjectHex
    dirty: Literal[False] = False


class MaterialBinding(_StrictModel):
    kind: Literal[
        "uv_lock",
        "sbom",
        "full_test_receipt",
        "clean_extract_receipt",
        "build_one_receipt",
        "build_two_receipt",
    ]
    path: str
    digest: Sha256Digest
    size_bytes: int = Field(ge=1)

    @field_validator("path")
    @classmethod
    def validate_path(cls, value: str) -> str:
        return _validate_stable_relative_path(value)


class FullTestInputs(_StrictModel):
    uv_lock_sha256: Sha256Hex
    sbom_sha256: Sha256Hex


class FullTestResult(_StrictModel):
    command_argv: list[str] = Field(min_length=1, max_length=64)
    cwd: Literal["."] = "."
    pytest_addopts: Literal[""] = ""
    exit_code: Literal[0] = 0
    passed: int = Field(ge=1)
    failed: Literal[0] = 0
    errors: Literal[0] = 0
    skipped: int = Field(ge=0)
    warnings: int = Field(ge=0)

    @field_validator("command_argv")
    @classmethod
    def validate_command(cls, value: list[str]) -> list[str]:
        if any(not isinstance(item, str) or not item.strip() for item in value):
            raise ValueError("test command contains an empty argument")
        expected_prefix = [
            "uv",
            "run",
            "--frozen",
            "python",
            "-m",
            "pytest",
            "-q",
        ]
        if (
            value[: len(expected_prefix)] != expected_prefix
            or len(value) != len(expected_prefix) + 1
            or not value[-1].startswith("--junitxml=")
        ):
            raise ValueError(
                "full test command must be the exact repository-wide pytest command "
                "plus one --junitxml output binding"
            )
        return value


class FullTestReceipt(_StrictModel):
    schema_version: Literal["visiondata-gate.full-test-receipt.v2"] = (
        FULL_TEST_RECEIPT_SCHEMA
    )
    status: Literal["PASS"] = "PASS"
    scope: Literal["FULL_REPOSITORY"] = "FULL_REPOSITORY"
    source: GitSourceState
    inputs: FullTestInputs
    junit: ArtifactBinding
    result: FullTestResult
    claim_boundary: Literal[
        "LOCAL_FULL_REGRESSION_RESULT_NOT_EXTERNAL_CERTIFICATION"
    ] = "LOCAL_FULL_REGRESSION_RESULT_NOT_EXTERNAL_CERTIFICATION"

    @model_validator(mode="after")
    def validate_junit_command_binding(self) -> FullTestReceipt:
        expected = f"--junitxml={self.junit.path}"
        if self.result.command_argv[-1:] != [expected]:
            raise ValueError(
                "full test command must end with the receipt-bound --junitxml path"
            )
        return self


class CleanExtractAudit(_StrictModel):
    ok: Literal[True] = True
    clean_extract_verified: Literal[True] = True
    required_paths_verified: Literal[True] = True
    credential_scan_passed: Literal[True] = True
    private_path_scan_passed: Literal[True] = True
    entry_count: int = Field(ge=1)
    verified_file_count: int = Field(ge=1)
    issue_count: Literal[0] = 0

    @model_validator(mode="after")
    def validate_counts(self) -> CleanExtractAudit:
        if self.verified_file_count > self.entry_count:
            raise ValueError("verified_file_count exceeds entry_count")
        return self


class CleanExtractAuditTool(_StrictModel):
    implementation: Literal["visiondata_gate.package.audit_submission_zip"] = (
        "visiondata_gate.package.audit_submission_zip"
    )
    manifest_schema: Literal["visiondata-gate.submission-manifest.v1"] = MANIFEST_SCHEMA


class CleanExtractReceipt(_StrictModel):
    schema_version: Literal["visiondata-gate.clean-extract-receipt.v1"] = (
        CLEAN_EXTRACT_RECEIPT_SCHEMA
    )
    status: Literal["PASS"] = "PASS"
    source: GitSourceState
    candidate: ArtifactBinding
    required_paths: list[str] = Field(min_length=1, max_length=1024)
    audit_tool: CleanExtractAuditTool = Field(default_factory=CleanExtractAuditTool)
    audit: CleanExtractAudit
    claim_boundary: Literal["LOCAL_CLEAN_EXTRACT_AUDIT_NOT_EXTERNAL_CERTIFICATION"] = (
        "LOCAL_CLEAN_EXTRACT_AUDIT_NOT_EXTERNAL_CERTIFICATION"
    )

    @field_validator("required_paths")
    @classmethod
    def validate_required_paths(cls, value: list[str]) -> list[str]:
        normalized = [_validate_stable_relative_path(item) for item in value]
        if normalized != sorted(set(normalized)):
            raise ValueError("required_paths must be sorted and unique")
        if tuple(normalized) != RC3_REQUIRED_PATHS:
            raise ValueError(
                "required_paths must equal the frozen RC3 submission policy"
            )
        return normalized


class BuilderIdentity(_StrictModel):
    builder_id: str = Field(min_length=3, max_length=256)
    toolchain: dict[str, str] = Field(min_length=1, max_length=32)
    identity_assurance: Literal[
        "REQUIRED_VERSIONS_LOCALLY_PROBED_IDENTITY_NOT_AUTHENTICATED"
    ] = "REQUIRED_VERSIONS_LOCALLY_PROBED_IDENTITY_NOT_AUTHENTICATED"

    @field_validator("builder_id")
    @classmethod
    def validate_builder_id(cls, value: str) -> str:
        return _validate_identifier(value, label="builder_id")

    @field_validator("toolchain")
    @classmethod
    def validate_toolchain(cls, value: dict[str, str]) -> dict[str, str]:
        missing = sorted(_REQUIRED_TOOLCHAIN_KEYS - set(value))
        if missing:
            raise ValueError(
                "toolchain is missing required keys: " + ", ".join(missing)
            )
        normalized: dict[str, str] = {}
        for name, version in value.items():
            if not re.fullmatch(r"[a-z0-9][a-z0-9._+-]{0,63}", name):
                raise ValueError(f"invalid toolchain name: {name}")
            if (
                not version
                or version != version.strip()
                or len(version) > 160
                or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._+()\-]{0,159}", version)
            ):
                raise ValueError(f"invalid toolchain version for {name}")
            normalized[name] = version
        return dict(sorted(normalized.items()))


class ReleaseBuildReceipt(_StrictModel):
    schema_version: Literal["visiondata-gate.release-build-receipt.v1"] = (
        RELEASE_BUILD_RECEIPT_SCHEMA
    )
    status: Literal["PASS"] = "PASS"
    source: GitSourceState
    inputs: FullTestInputs
    invocation_id: str = Field(min_length=3, max_length=256)
    workspace: str
    clean_workspace: Literal[True] = True
    command_argv: list[str] = Field(min_length=6, max_length=64)
    output: ArtifactBinding
    builder: BuilderIdentity
    claim_boundary: Literal[
        "LOCAL_BUILD_INVOCATION_RECEIPT_NOT_AUTHENTICATED_BY_EXTERNAL_BUILDER"
    ] = "LOCAL_BUILD_INVOCATION_RECEIPT_NOT_AUTHENTICATED_BY_EXTERNAL_BUILDER"

    @field_validator("invocation_id")
    @classmethod
    def validate_invocation_id(cls, value: str) -> str:
        return _validate_identifier(value, label="invocation_id")

    @field_validator("workspace")
    @classmethod
    def validate_workspace(cls, value: str) -> str:
        return _validate_stable_relative_path(value)

    @field_validator("command_argv")
    @classmethod
    def validate_build_command(cls, value: list[str]) -> list[str]:
        if any(not isinstance(item, str) or not item.strip() for item in value):
            raise ValueError("build command contains an empty argument")
        if value[:4] != ["uv", "run", "--frozen", "python"]:
            raise ValueError("release build must run through uv --frozen python")
        if not value[4].startswith("tools/") or not value[4].endswith(".py"):
            raise ValueError("script build command must name a tools/*.py entrypoint")
        return value

    @model_validator(mode="after")
    def validate_output_workspace(self) -> ReleaseBuildReceipt:
        prefix = self.workspace.rstrip("/") + "/"
        if not self.output.path.startswith(prefix):
            raise ValueError("build output must be inside its declared workspace")
        for option, expected in (
            ("--workspace", self.workspace),
            ("--output", self.output.path),
        ):
            if self.command_argv.count(option) != 1:
                raise ValueError(f"build command must contain exactly one {option}")
            index = self.command_argv.index(option)
            if index + 1 >= len(self.command_argv):
                raise ValueError(f"build command is missing the {option} value")
            if self.command_argv[index + 1] != expected:
                raise ValueError(f"build command {option} binding drifted")
        return self


class BuildOutputBinding(_StrictModel):
    invocation_id: str = Field(min_length=3, max_length=256)
    workspace: str
    receipt_path: str
    receipt_sha256: Sha256Hex
    artifact: ArtifactBinding

    @field_validator("invocation_id")
    @classmethod
    def validate_invocation_id(cls, value: str) -> str:
        return _validate_identifier(value, label="invocation_id")

    @field_validator("workspace", "receipt_path")
    @classmethod
    def validate_relative_path(cls, value: str) -> str:
        return _validate_stable_relative_path(value)

    @model_validator(mode="after")
    def validate_workspace_binding(self) -> BuildOutputBinding:
        prefix = self.workspace.rstrip("/") + "/"
        if not self.artifact.path.startswith(prefix):
            raise ValueError("build artifact is outside its declared workspace")
        return self


class ReproducibilityResult(_StrictModel):
    status: Literal["PASS"] = "PASS"
    method: Literal["BYTE_FOR_BYTE_SHA256_MATCH"] = "BYTE_FOR_BYTE_SHA256_MATCH"
    build_one: BuildOutputBinding
    build_two: BuildOutputBinding
    byte_identical: Literal[True] = True
    claim_boundary: Literal[
        "TWO_DECLARED_BUILD_OUTPUTS_MATCH_NO_INDEPENDENT_BUILDER_ATTESTATION"
    ] = "TWO_DECLARED_BUILD_OUTPUTS_MATCH_NO_INDEPENDENT_BUILDER_ATTESTATION"

    @model_validator(mode="after")
    def validate_match(self) -> ReproducibilityResult:
        if self.build_one.invocation_id == self.build_two.invocation_id:
            raise ValueError("two-build invocation IDs must be distinct")
        first_workspace = tuple(
            part.casefold() for part in PurePosixPath(self.build_one.workspace).parts
        )
        second_workspace = tuple(
            part.casefold() for part in PurePosixPath(self.build_two.workspace).parts
        )
        overlap = (
            first_workspace == second_workspace
            or first_workspace == second_workspace[: len(first_workspace)]
            or second_workspace == first_workspace[: len(second_workspace)]
        )
        if overlap:
            raise ValueError("two-build workspaces must be distinct and non-nested")
        if self.build_one.receipt_path.casefold() == (
            self.build_two.receipt_path.casefold()
        ):
            raise ValueError("two-build receipt paths must be distinct")
        if self.build_one.artifact.path.casefold() == (
            self.build_two.artifact.path.casefold()
        ):
            raise ValueError("two-build artifact paths must be distinct")
        if self.build_one.artifact.digest != self.build_two.artifact.digest:
            raise ValueError("two-build ZIP SHA-256 values differ")
        if self.build_one.artifact.size_bytes != self.build_two.artifact.size_bytes:
            raise ValueError("two-build ZIP sizes differ")
        return self


class FullTestSummary(_StrictModel):
    status: Literal["PASS"] = "PASS"
    receipt_sha256: Sha256Hex
    junit_sha256: Sha256Hex
    passed: int = Field(ge=1)
    failed: Literal[0] = 0
    errors: Literal[0] = 0
    skipped: int = Field(ge=0)
    warnings: int = Field(ge=0)


class CleanExtractSummary(_StrictModel):
    status: Literal["PASS"] = "PASS"
    receipt_sha256: Sha256Hex
    candidate_zip_sha256: Sha256Hex
    entry_count: int = Field(ge=1)
    verified_file_count: int = Field(ge=1)
    issue_count: Literal[0] = 0
    required_paths: list[str] = Field(min_length=1, max_length=1024)

    @field_validator("required_paths")
    @classmethod
    def validate_required_paths(cls, value: list[str]) -> list[str]:
        normalized = [_validate_stable_relative_path(item) for item in value]
        if normalized != sorted(set(normalized)):
            raise ValueError("required_paths must be sorted and unique")
        return normalized


class VerificationEvidence(_StrictModel):
    full_test: FullTestSummary
    clean_extract: CleanExtractSummary


class TrustBoundary(_StrictModel):
    signature: Literal["NOT_CONFIGURED"] = "NOT_CONFIGURED"
    trusted_timestamp: Literal["NOT_CONFIGURED"] = "NOT_CONFIGURED"
    external_anchor: Literal["NOT_CONFIGURED"] = "NOT_CONFIGURED"
    assurance: Literal["DIGEST_INTEGRITY_ONLY_NO_SIGNER_IDENTITY_OR_TRUSTED_TIME"] = (
        "DIGEST_INTEGRITY_ONLY_NO_SIGNER_IDENTITY_OR_TRUSTED_TIME"
    )


class ReleasePredicate(_StrictModel):
    schema_version: Literal["visiondata-gate.release-attestation-predicate.v1"] = (
        PREDICATE_SCHEMA
    )
    release_id: str = Field(min_length=3, max_length=160)
    source: GitSourceState
    materials: list[MaterialBinding] = Field(min_length=6, max_length=6)
    verification: VerificationEvidence
    reproducibility: ReproducibilityResult
    builder: BuilderIdentity
    trust: TrustBoundary = Field(default_factory=TrustBoundary)
    submission_eligible: Literal[False] = False
    claim_boundary: Literal[
        "LOCAL_UNSIGNED_INTEGRITY_STATEMENT_NOT_OFFICIAL_SUBMISSION_OR_RELEASE_APPROVAL"
    ] = "LOCAL_UNSIGNED_INTEGRITY_STATEMENT_NOT_OFFICIAL_SUBMISSION_OR_RELEASE_APPROVAL"

    @field_validator("release_id")
    @classmethod
    def validate_release_id(cls, value: str) -> str:
        return _validate_identifier(value, label="release_id")

    @model_validator(mode="after")
    def validate_material_bindings(self) -> ReleasePredicate:
        kinds = tuple(item.kind for item in self.materials)
        if kinds != _REQUIRED_MATERIAL_KINDS:
            raise ValueError("materials use an invalid order or required set")
        if len({item.path for item in self.materials}) != len(self.materials):
            raise ValueError("materials contain duplicate paths")
        by_kind = {item.kind: item for item in self.materials}
        if by_kind["uv_lock"].path != "uv.lock":
            raise ValueError("uv_lock must bind the repository-root uv.lock")
        if by_kind["sbom"].path != "docs/SBOM.cdx.json":
            raise ValueError("sbom must bind docs/SBOM.cdx.json")
        if (
            by_kind["full_test_receipt"].digest.sha256
            != self.verification.full_test.receipt_sha256
        ):
            raise ValueError("full-test receipt summary is not hash-bound")
        if (
            by_kind["clean_extract_receipt"].digest.sha256
            != self.verification.clean_extract.receipt_sha256
        ):
            raise ValueError("clean-extract receipt summary is not hash-bound")
        if (
            by_kind["build_one_receipt"].digest.sha256
            != self.reproducibility.build_one.receipt_sha256
            or by_kind["build_one_receipt"].path
            != self.reproducibility.build_one.receipt_path
        ):
            raise ValueError("build-one receipt is not hash-bound")
        if (
            by_kind["build_two_receipt"].digest.sha256
            != self.reproducibility.build_two.receipt_sha256
            or by_kind["build_two_receipt"].path
            != self.reproducibility.build_two.receipt_path
        ):
            raise ValueError("build-two receipt is not hash-bound")
        candidate = self.reproducibility.build_one.artifact.digest.sha256
        if self.verification.clean_extract.candidate_zip_sha256 != candidate:
            raise ValueError("clean-extract summary is not candidate-bound")
        return self


class ReleaseStatement(_StrictModel):
    statement_type: Literal["https://in-toto.io/Statement/v1"] = Field(
        default=STATEMENT_TYPE,
        alias="_type",
    )
    subject: list[InTotoSubject] = Field(min_length=1, max_length=1)
    predicate_type: Literal["https://visiondata-gate.local/attestation/release/v1"] = (
        Field(default=PREDICATE_TYPE, alias="predicateType")
    )
    predicate: ReleasePredicate

    @model_validator(mode="after")
    def validate_subject_binding(self) -> ReleaseStatement:
        subject = self.subject[0]
        candidate = self.predicate.reproducibility.build_one.artifact
        if subject.name != candidate.path or subject.digest != candidate.digest:
            raise ValueError("in-toto subject is not bound to build_one")
        if not subject.name.casefold().endswith(".zip"):
            raise ValueError("release subject must be a ZIP file")
        return self


class StatementDigest(_StrictModel):
    algorithm: Literal["sha256"] = "sha256"
    canonicalization_profile: Literal["rfc8785-jcs-v1"] = (
        RELEASE_CANONICALIZATION_PROFILE
    )
    framing_profile: Literal["visiondata-gate-release-domain-frame-v1"] = (
        RELEASE_FRAMING_PROFILE
    )
    hash_domain: Literal["visiondata-gate/release-attestation/statement/v1"] = (
        RELEASE_STATEMENT_DOMAIN
    )
    value: Sha256Hex


class ReleaseAttestation(_StrictModel):
    schema_version: Literal["visiondata-gate.release-attestation-envelope.v1"] = (
        ATTESTATION_SCHEMA
    )
    statement: ReleaseStatement
    statement_digest: StatementDigest


class AttestationVerificationResult(_StrictModel):
    schema_version: Literal["visiondata-gate.release-attestation-verification.v1"] = (
        VERIFICATION_SCHEMA
    )
    status: Literal["PASS_LOCAL_INTEGRITY"] = "PASS_LOCAL_INTEGRITY"
    release_id: str
    subject: InTotoSubject
    statement_digest: StatementDigest
    material_count: Literal[6] = 6
    git_clean: Literal[True] = True
    two_declared_outputs: Literal["BYTE_IDENTICAL"] = "BYTE_IDENTICAL"
    signature: Literal["NOT_CONFIGURED"] = "NOT_CONFIGURED"
    trusted_timestamp: Literal["NOT_CONFIGURED"] = "NOT_CONFIGURED"
    external_anchor: Literal["NOT_CONFIGURED"] = "NOT_CONFIGURED"
    submission_eligible: Literal[False] = False
    official_status: Literal["NOT_EVALUATED"] = "NOT_EVALUATED"


class _ResolvedFile(_StrictModel):
    absolute_path: Path
    relative_path: str
    sha256: Sha256Hex
    size_bytes: int = Field(ge=1)


ModelT = TypeVar("ModelT", bound=BaseModel)


def _parse_unique_json(data: bytes, *, artifact_name: str) -> Any:
    def unique_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
        result: dict[str, Any] = {}
        for key, value in pairs:
            if key in result:
                raise ReleaseAttestationError(
                    f"duplicate JSON member in {artifact_name}: {key}"
                )
            result[key] = value
        return result

    def reject_constant(value: str) -> None:
        raise ReleaseAttestationError(
            f"non-finite JSON number in {artifact_name}: {value}"
        )

    try:
        text = data.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise ReleaseAttestationError(f"{artifact_name} is not valid UTF-8") from exc
    try:
        return json.loads(
            text,
            object_pairs_hook=unique_object,
            parse_constant=reject_constant,
        )
    except ReleaseAttestationError:
        raise
    except (json.JSONDecodeError, RecursionError) as exc:
        raise ReleaseAttestationError(
            f"invalid JSON in {artifact_name}: {exc}"
        ) from exc


def _model_payload(model: BaseModel) -> dict[str, Any]:
    return model.model_dump(mode="json", by_alias=True)


def _load_canonical_model(
    path: Path,
    model_type: type[ModelT],
    *,
    artifact_name: str,
) -> tuple[ModelT, bytes]:
    try:
        data = path.read_bytes()
    except OSError as exc:
        raise ReleaseAttestationError(f"cannot read {artifact_name}: {exc}") from exc
    parsed = _parse_unique_json(data, artifact_name=artifact_name)
    try:
        model = model_type.model_validate(parsed)
    except ValidationError as exc:
        raise ReleaseAttestationError(
            f"{artifact_name} schema validation failed: {exc}"
        ) from exc
    expected = canonical_jcs_bytes(_model_payload(model))
    if not hmac.compare_digest(data, expected):
        raise ReleaseAttestationError(
            f"{artifact_name} is not byte-canonical RFC 8785 JCS"
        )
    return model, data


def _resolve_project_root(project_root: str | Path) -> Path:
    try:
        root = Path(project_root).resolve(strict=True)
    except OSError as exc:
        raise ReleaseAttestationError(f"project root does not exist: {exc}") from exc
    if not root.is_dir():
        raise ReleaseAttestationError("project root is not a directory")
    return root


def _resolve_input_file(
    root: Path,
    value: str | Path,
    *,
    label: str,
) -> _ResolvedFile:
    supplied = Path(value)
    candidate = supplied if supplied.is_absolute() else root / supplied
    try:
        lexical_relative = candidate.absolute().relative_to(root).as_posix()
    except ValueError as exc:
        raise ReleaseAttestationError(
            f"required {label} must stay inside the project root"
        ) from exc
    try:
        lexical_stable = _validate_stable_relative_path(lexical_relative)
    except ValueError as exc:
        raise ReleaseAttestationError(f"unsafe {label} path: {exc}") from exc
    _reject_link_components(root, lexical_stable, label=label)
    try:
        resolved = candidate.resolve(strict=True)
    except OSError as exc:
        raise ReleaseAttestationError(f"required {label} is missing: {exc}") from exc
    if not resolved.is_file():
        raise ReleaseAttestationError(f"required {label} is not a regular file")
    try:
        relative = resolved.relative_to(root).as_posix()
    except ValueError as exc:
        raise ReleaseAttestationError(
            f"required {label} must stay inside the project root"
        ) from exc
    try:
        stable = _validate_stable_relative_path(relative)
    except ValueError as exc:
        raise ReleaseAttestationError(f"unsafe {label} path: {exc}") from exc
    _reject_link_components(root, stable, label=label)
    size = resolved.stat().st_size
    if size <= 0:
        raise ReleaseAttestationError(f"required {label} is empty")
    return _ResolvedFile(
        absolute_path=resolved,
        relative_path=stable,
        sha256=sha256_file(resolved),
        size_bytes=size,
    )


def _resolve_attested_file(root: Path, value: str, *, label: str) -> Path:
    try:
        stable = _validate_stable_relative_path(value)
    except ValueError as exc:
        raise ReleaseAttestationError(f"unsafe attested {label} path: {exc}") from exc
    _reject_link_components(root, stable, label=label)
    parts = PurePosixPath(stable).parts
    try:
        resolved = root.joinpath(*parts).resolve(strict=True)
    except OSError as exc:
        raise ReleaseAttestationError(f"attested {label} is missing: {exc}") from exc
    try:
        resolved.relative_to(root)
    except ValueError as exc:
        raise ReleaseAttestationError(
            f"attested {label} resolves outside the project root"
        ) from exc
    if not resolved.is_file():
        raise ReleaseAttestationError(f"attested {label} is not a regular file")
    return resolved


def _reject_link_components(root: Path, relative: str, *, label: str) -> None:
    current = root
    for part in PurePosixPath(relative).parts:
        current /= part
        try:
            is_junction = current.is_junction()
        except (AttributeError, OSError):
            is_junction = False
        try:
            is_symlink = current.is_symlink()
        except OSError:
            is_symlink = False
        if is_symlink or is_junction:
            raise ReleaseAttestationError(
                f"{label} path contains a symlink or junction"
            )


def _subprocess_env_without_git_overrides() -> dict[str, str]:
    """Keep the host environment while removing repository-routing overrides."""

    return {
        name: value
        for name, value in os.environ.items()
        if not name.upper().startswith("GIT_")
    }


def _run_git(root: Path, arguments: Sequence[str]) -> bytes:
    try:
        completed = subprocess.run(
            ["git", "-C", str(root), *arguments],
            check=False,
            capture_output=True,
            env=_subprocess_env_without_git_overrides(),
            timeout=_SUBPROCESS_TIMEOUT_SECONDS,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise ReleaseAttestationError(f"git is unavailable: {exc}") from exc
    if completed.returncode != 0:
        detail = completed.stderr.decode("utf-8", errors="replace").strip()
        raise ReleaseAttestationError(
            f"git {' '.join(arguments)} failed: {detail or completed.returncode}"
        )
    return completed.stdout


def _probe_version(arguments: Sequence[str], *, label: str) -> str:
    try:
        completed = subprocess.run(
            list(arguments),
            check=False,
            capture_output=True,
            text=True,
            encoding="utf-8",
            env=_subprocess_env_without_git_overrides(),
            errors="strict",
            timeout=_SUBPROCESS_TIMEOUT_SECONDS,
        )
    except (OSError, subprocess.TimeoutExpired, UnicodeError) as exc:
        raise ReleaseAttestationError(f"cannot probe {label} version: {exc}") from exc
    if completed.returncode != 0:
        raise ReleaseAttestationError(
            f"cannot probe {label} version: exit {completed.returncode}"
        )
    tokens = completed.stdout.strip().split()
    if len(tokens) < 2:
        raise ReleaseAttestationError(f"unexpected {label} version output")
    return tokens[-1] if label == "git" else tokens[1]


def detect_release_toolchain() -> dict[str, str]:
    """Probe the four required local release-tool versions."""

    try:
        project_version = metadata.version("visiondata-gate")
    except metadata.PackageNotFoundError as exc:
        raise ReleaseAttestationError(
            "installed visiondata-gate package metadata is unavailable"
        ) from exc
    observed = {
        "git": _probe_version(["git", "--version"], label="git"),
        "python": platform.python_version(),
        "uv": _probe_version(["uv", "--version"], label="uv"),
        "visiondata-gate": project_version,
    }
    try:
        return BuilderIdentity(
            builder_id="local://toolchain/probe",
            toolchain=observed,
        ).toolchain
    except ValidationError as exc:
        raise ReleaseAttestationError(f"invalid observed toolchain: {exc}") from exc


def _assert_toolchain(builder: BuilderIdentity) -> None:
    observed = detect_release_toolchain()
    for name in sorted(_REQUIRED_TOOLCHAIN_KEYS):
        if not hmac.compare_digest(builder.toolchain[name], observed[name]):
            raise ReleaseAttestationError(
                f"declared {name} version does not match the local toolchain"
            )


def _git_source_state(root: Path) -> GitSourceState:
    top_level_raw = _run_git(root, ["rev-parse", "--show-toplevel"])
    top_level = Path(top_level_raw.decode("utf-8").strip()).resolve(strict=True)
    if top_level != root:
        raise ReleaseAttestationError("project root must equal the Git worktree root")

    status = _run_git(
        root,
        [
            "status",
            "--porcelain=v1",
            "-z",
            "--untracked-files=all",
            "--ignore-submodules=none",
        ],
    )
    if status:
        entry_count = status.count(b"\x00")
        raise ReleaseAttestationError(
            "git worktree is dirty; release attestation is fail-closed "
            f"({entry_count} status entries)"
        )
    indexed = _run_git(root, ["ls-files", "-v", "-z"])
    hidden_index_flags = []
    for record in indexed.split(b"\x00"):
        if not record:
            continue
        tag = record[:1]
        if tag == b"S" or (b"a" <= tag <= b"z"):
            hidden_index_flags.append(tag)
    if hidden_index_flags:
        raise ReleaseAttestationError(
            "git index contains skip-worktree or assume-unchanged entries; "
            "release attestation is fail-closed "
            f"({len(hidden_index_flags)} entries)"
        )
    commit = _run_git(root, ["rev-parse", "HEAD"]).decode("ascii").strip()
    tree = _run_git(root, ["rev-parse", "HEAD^{tree}"]).decode("ascii").strip()
    try:
        return GitSourceState(commit=commit, tree=tree, dirty=False)
    except ValidationError as exc:
        raise ReleaseAttestationError(f"invalid Git object identity: {exc}") from exc


def get_clean_git_source_state(project_root: str | Path) -> GitSourceState:
    """Return the strict clean Git identity for a repository-root path."""

    root = _resolve_project_root(project_root)
    return _git_source_state(root)


def _artifact_binding(value: _ResolvedFile) -> ArtifactBinding:
    return ArtifactBinding(
        path=value.relative_path,
        digest=Sha256Digest(sha256=value.sha256),
        size_bytes=value.size_bytes,
    )


def _material_binding(kind: str, value: _ResolvedFile) -> MaterialBinding:
    return MaterialBinding(
        kind=kind,
        path=value.relative_path,
        digest=Sha256Digest(sha256=value.sha256),
        size_bytes=value.size_bytes,
    )


def _validate_zip(value: _ResolvedFile, *, label: str) -> None:
    if not value.relative_path.casefold().endswith(".zip"):
        raise ReleaseAttestationError(f"{label} must use a .zip filename")
    if not zipfile.is_zipfile(value.absolute_path):
        raise ReleaseAttestationError(f"{label} is not a valid ZIP archive")


def _validate_uv_lock(path: Path) -> None:
    try:
        text = path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError) as exc:
        raise ReleaseAttestationError(f"uv.lock is unreadable: {exc}") from exc
    if not re.search(r"(?m)^version\s*=\s*\d+\s*$", text):
        raise ReleaseAttestationError("uv.lock is missing its version declaration")
    if "[[package]]" not in text:
        raise ReleaseAttestationError("uv.lock contains no locked package records")


def _validate_sbom(path: Path) -> None:
    try:
        data = path.read_bytes()
    except OSError as exc:
        raise ReleaseAttestationError(f"SBOM is unreadable: {exc}") from exc
    parsed = _parse_unique_json(data, artifact_name="SBOM")
    if not isinstance(parsed, dict):
        raise ReleaseAttestationError("SBOM must be a JSON object")
    if parsed.get("bomFormat") != "CycloneDX":
        raise ReleaseAttestationError("SBOM is not a CycloneDX document")
    if not isinstance(parsed.get("specVersion"), str):
        raise ReleaseAttestationError("SBOM is missing specVersion")
    components = parsed.get("components")
    if not isinstance(components, list) or not components:
        raise ReleaseAttestationError("SBOM contains no component records")
    metadata = parsed.get("metadata")
    if not isinstance(metadata, dict):
        raise ReleaseAttestationError("SBOM is missing metadata")
    raw_properties = metadata.get("properties")
    if not isinstance(raw_properties, list):
        raise ReleaseAttestationError("SBOM metadata is missing lock bindings")
    properties: dict[str, str] = {}
    for item in raw_properties:
        if not isinstance(item, dict):
            raise ReleaseAttestationError("SBOM metadata property is malformed")
        name = item.get("name")
        value = item.get("value")
        if (
            not isinstance(name, str)
            or not isinstance(value, str)
            or name in properties
        ):
            raise ReleaseAttestationError(
                "SBOM metadata property is invalid or duplicated"
            )
        properties[name] = value

    project_root = path.parent.parent
    lock_files = (
        "uv.lock",
        "web/package-lock.json",
        "web/src-tauri/Cargo.lock",
    )
    required_ecosystems: set[str] = set()
    for relative in lock_files:
        lock_path = project_root / relative
        if not lock_path.is_file():
            continue
        expected = sha256_file(lock_path)
        key = f"visiondata-gate:lock-sha256:{relative}"
        if not hmac.compare_digest(properties.get(key, ""), expected):
            raise ReleaseAttestationError(f"SBOM does not bind the current {relative}")
        required_ecosystems.add(
            {
                "uv.lock": "python",
                "web/package-lock.json": "npm",
                "web/src-tauri/Cargo.lock": "cargo",
            }[relative]
        )

    observed_ecosystems: set[str] = set()
    metadata_component = metadata.get("component")
    all_components = [metadata_component, *components]
    for component in all_components:
        if not isinstance(component, dict):
            continue
        for item in component.get("properties", []):
            if (
                isinstance(item, dict)
                and item.get("name") == "visiondata-gate:ecosystem"
                and isinstance(item.get("value"), str)
            ):
                observed_ecosystems.add(item["value"])
    if not required_ecosystems.issubset(observed_ecosystems):
        missing = sorted(required_ecosystems - observed_ecosystems)
        raise ReleaseAttestationError(
            f"SBOM omits locked ecosystems: {', '.join(missing)}"
        )


def _assert_source_binding(
    receipt_source: GitSourceState,
    observed_source: GitSourceState,
    *,
    label: str,
) -> None:
    if receipt_source != observed_source:
        raise ReleaseAttestationError(f"{label} does not bind the current Git source")


def _assert_file_binding(
    path: Path,
    binding: ArtifactBinding | MaterialBinding,
    *,
    label: str,
) -> None:
    observed_size = path.stat().st_size
    if observed_size != binding.size_bytes:
        raise ReleaseAttestationError(f"{label} size does not match the attestation")
    observed_sha256 = sha256_file(path)
    if not hmac.compare_digest(observed_sha256, binding.digest.sha256):
        raise ReleaseAttestationError(f"{label} SHA-256 does not match the attestation")


def _assert_full_test_receipt(
    receipt: FullTestReceipt,
    *,
    root: Path,
    source: GitSourceState,
    uv_lock_sha256: str,
    sbom_sha256: str,
) -> None:
    _assert_source_binding(receipt.source, source, label="full-test receipt")
    if not hmac.compare_digest(receipt.inputs.uv_lock_sha256, uv_lock_sha256):
        raise ReleaseAttestationError("full-test receipt does not bind uv.lock")
    if not hmac.compare_digest(receipt.inputs.sbom_sha256, sbom_sha256):
        raise ReleaseAttestationError("full-test receipt does not bind the SBOM")
    junit_path = _resolve_attested_file(
        root,
        receipt.junit.path,
        label="full-test JUnit artifact",
    )
    _assert_file_binding(
        junit_path,
        receipt.junit,
        label="full-test JUnit artifact",
    )


def _assert_clean_extract_receipt(
    receipt: CleanExtractReceipt,
    *,
    source: GitSourceState,
    candidate: ArtifactBinding,
) -> None:
    _assert_source_binding(receipt.source, source, label="clean-extract receipt")
    if receipt.candidate != candidate:
        raise ReleaseAttestationError(
            "clean-extract receipt does not bind the candidate ZIP"
        )


def _assert_clean_extract_audit(
    receipt: CleanExtractReceipt,
    *,
    candidate_path: Path,
    candidate: ArtifactBinding,
    label: str,
) -> None:
    observed = audit_submission_zip(
        candidate_path,
        required_paths=receipt.required_paths,
    )
    if not observed.ok or not observed.clean_extract_verified or observed.issues:
        issue_codes = sorted({issue.code for issue in observed.issues})
        detail = ",".join(issue_codes) if issue_codes else "unknown"
        raise ReleaseAttestationError(
            f"{label} failed live package and clean-extract audit: {detail}"
        )
    if observed.zip_sha256 is None or not hmac.compare_digest(
        observed.zip_sha256,
        candidate.digest.sha256,
    ):
        raise ReleaseAttestationError(f"{label} live audit ZIP digest drifted")
    if tuple(receipt.required_paths) != observed.required_paths:
        raise ReleaseAttestationError(f"{label} required-path audit scope drifted")
    if (
        receipt.audit.entry_count != observed.entry_count
        or receipt.audit.verified_file_count != observed.verified_file_count
    ):
        raise ReleaseAttestationError(
            f"{label} receipt counts do not match the live clean-extract audit"
        )


def _assert_build_receipt(
    receipt: ReleaseBuildReceipt,
    *,
    source: GitSourceState,
    uv_lock_sha256: str,
    sbom_sha256: str,
    builder: BuilderIdentity,
    expected_output: ArtifactBinding,
    root: Path,
    label: str,
) -> None:
    _assert_source_binding(receipt.source, source, label=label)
    if not hmac.compare_digest(receipt.inputs.uv_lock_sha256, uv_lock_sha256):
        raise ReleaseAttestationError(f"{label} does not bind uv.lock")
    if not hmac.compare_digest(receipt.inputs.sbom_sha256, sbom_sha256):
        raise ReleaseAttestationError(f"{label} does not bind the SBOM")
    if receipt.builder != builder:
        raise ReleaseAttestationError(f"{label} builder identity/toolchain drifted")
    if receipt.output != expected_output:
        raise ReleaseAttestationError(f"{label} does not bind its ZIP output")
    entrypoint = receipt.command_argv[4]
    entrypoint_path = _resolve_attested_file(
        root,
        entrypoint,
        label=f"{label} build entrypoint",
    )
    tracked = _run_git(root, ["ls-files", "--error-unmatch", "--", entrypoint])
    if not tracked.strip() or not entrypoint_path.is_file():
        raise ReleaseAttestationError(f"{label} build entrypoint is not Git-tracked")


def _domain_frame(payload: bytes) -> bytes:
    domain = RELEASE_STATEMENT_DOMAIN.encode("utf-8")
    if len(domain) > 0xFFFF:
        raise ReleaseAttestationError("release hash domain is too long")
    return b"".join(
        (
            RELEASE_FRAME_MAGIC,
            len(domain).to_bytes(2, "big"),
            domain,
            len(payload).to_bytes(8, "big"),
            payload,
        )
    )


def domain_separated_statement_sha256(statement: ReleaseStatement) -> str:
    """Return the v1 domain-separated SHA-256 for one canonical Statement."""

    payload = canonical_jcs_bytes(_model_payload(statement))
    return hashlib.sha256(_domain_frame(payload)).hexdigest()


def release_attestation_bytes(attestation: ReleaseAttestation) -> bytes:
    """Serialize an attestation as exact RFC 8785 JCS bytes."""

    return canonical_jcs_bytes(_model_payload(attestation))


def build_release_attestation(
    *,
    project_root: str | Path,
    release_id: str,
    candidate_zip: str | Path,
    reproducible_zip: str | Path,
    full_test_receipt: str | Path,
    clean_extract_receipt: str | Path,
    build_one_receipt: str | Path,
    build_two_receipt: str | Path,
    builder_id: str,
    toolchain: Mapping[str, str],
) -> ReleaseAttestation:
    """Build a deterministic unsigned v1 release attestation.

    Every required artifact must exist inside a clean Git worktree.  The two
    ZIP files must be distinct paths with byte-identical SHA-256 values.
    """

    root = _resolve_project_root(project_root)
    candidate = _resolve_input_file(root, candidate_zip, label="candidate ZIP")
    reproduced = _resolve_input_file(
        root,
        reproducible_zip,
        label="second-build ZIP",
    )
    uv_lock = _resolve_input_file(root, "uv.lock", label="uv.lock")
    sbom = _resolve_input_file(root, "docs/SBOM.cdx.json", label="SBOM")
    full_receipt_file = _resolve_input_file(
        root,
        full_test_receipt,
        label="full-test receipt",
    )
    clean_receipt_file = _resolve_input_file(
        root,
        clean_extract_receipt,
        label="clean-extract receipt",
    )
    build_one_receipt_file = _resolve_input_file(
        root,
        build_one_receipt,
        label="build-one receipt",
    )
    build_two_receipt_file = _resolve_input_file(
        root,
        build_two_receipt,
        label="build-two receipt",
    )

    _validate_zip(candidate, label="candidate ZIP")
    _validate_zip(reproduced, label="second-build ZIP")
    if candidate.relative_path == reproduced.relative_path:
        raise ReleaseAttestationError("two-build ZIP paths must be distinct")
    try:
        same_file = os.path.samefile(candidate.absolute_path, reproduced.absolute_path)
    except OSError as exc:
        raise ReleaseAttestationError(
            f"cannot compare two-build file identities: {exc}"
        ) from exc
    if same_file:
        raise ReleaseAttestationError(
            "two-build ZIP paths refer to the same underlying file"
        )
    if not hmac.compare_digest(candidate.sha256, reproduced.sha256):
        raise ReleaseAttestationError(
            "two-build ZIP SHA-256 values differ; release is fail-closed"
        )
    if candidate.size_bytes != reproduced.size_bytes:
        raise ReleaseAttestationError(
            "two-build ZIP sizes differ; release is fail-closed"
        )

    source = _git_source_state(root)
    _validate_uv_lock(uv_lock.absolute_path)
    _validate_sbom(sbom.absolute_path)
    try:
        builder = BuilderIdentity(
            builder_id=builder_id,
            toolchain=dict(toolchain),
        )
    except ValidationError as exc:
        raise ReleaseAttestationError(f"invalid builder identity: {exc}") from exc
    _assert_toolchain(builder)
    full_receipt, _ = _load_canonical_model(
        full_receipt_file.absolute_path,
        FullTestReceipt,
        artifact_name="full-test receipt",
    )
    clean_receipt, _ = _load_canonical_model(
        clean_receipt_file.absolute_path,
        CleanExtractReceipt,
        artifact_name="clean-extract receipt",
    )
    build_one_receipt_model, _ = _load_canonical_model(
        build_one_receipt_file.absolute_path,
        ReleaseBuildReceipt,
        artifact_name="build-one receipt",
    )
    build_two_receipt_model, _ = _load_canonical_model(
        build_two_receipt_file.absolute_path,
        ReleaseBuildReceipt,
        artifact_name="build-two receipt",
    )
    candidate_binding = _artifact_binding(candidate)
    reproduced_binding = _artifact_binding(reproduced)
    _assert_full_test_receipt(
        full_receipt,
        root=root,
        source=source,
        uv_lock_sha256=uv_lock.sha256,
        sbom_sha256=sbom.sha256,
    )
    _assert_clean_extract_receipt(
        clean_receipt,
        source=source,
        candidate=candidate_binding,
    )
    _assert_clean_extract_audit(
        clean_receipt,
        candidate_path=candidate.absolute_path,
        candidate=candidate_binding,
        label="candidate ZIP",
    )
    _assert_clean_extract_audit(
        clean_receipt,
        candidate_path=reproduced.absolute_path,
        candidate=reproduced_binding,
        label="second-build ZIP",
    )
    _assert_build_receipt(
        build_one_receipt_model,
        source=source,
        uv_lock_sha256=uv_lock.sha256,
        sbom_sha256=sbom.sha256,
        builder=builder,
        expected_output=candidate_binding,
        root=root,
        label="build-one receipt",
    )
    _assert_build_receipt(
        build_two_receipt_model,
        source=source,
        uv_lock_sha256=uv_lock.sha256,
        sbom_sha256=sbom.sha256,
        builder=builder,
        expected_output=reproduced_binding,
        root=root,
        label="build-two receipt",
    )

    try:
        reproducibility = ReproducibilityResult(
            build_one=BuildOutputBinding(
                invocation_id=build_one_receipt_model.invocation_id,
                workspace=build_one_receipt_model.workspace,
                receipt_path=build_one_receipt_file.relative_path,
                receipt_sha256=build_one_receipt_file.sha256,
                artifact=candidate_binding,
            ),
            build_two=BuildOutputBinding(
                invocation_id=build_two_receipt_model.invocation_id,
                workspace=build_two_receipt_model.workspace,
                receipt_path=build_two_receipt_file.relative_path,
                receipt_sha256=build_two_receipt_file.sha256,
                artifact=reproduced_binding,
            ),
        )
        materials = [
            _material_binding("uv_lock", uv_lock),
            _material_binding("sbom", sbom),
            _material_binding("full_test_receipt", full_receipt_file),
            _material_binding("clean_extract_receipt", clean_receipt_file),
            _material_binding("build_one_receipt", build_one_receipt_file),
            _material_binding("build_two_receipt", build_two_receipt_file),
        ]
        verification = VerificationEvidence(
            full_test=FullTestSummary(
                receipt_sha256=full_receipt_file.sha256,
                junit_sha256=full_receipt.junit.digest.sha256,
                passed=full_receipt.result.passed,
                failed=0,
                errors=0,
                skipped=full_receipt.result.skipped,
                warnings=full_receipt.result.warnings,
            ),
            clean_extract=CleanExtractSummary(
                receipt_sha256=clean_receipt_file.sha256,
                candidate_zip_sha256=candidate.sha256,
                entry_count=clean_receipt.audit.entry_count,
                verified_file_count=clean_receipt.audit.verified_file_count,
                issue_count=0,
                required_paths=clean_receipt.required_paths,
            ),
        )
        statement = ReleaseStatement(
            subject=[
                InTotoSubject(
                    name=candidate.relative_path,
                    digest=Sha256Digest(sha256=candidate.sha256),
                )
            ],
            predicate=ReleasePredicate(
                release_id=release_id,
                source=source,
                materials=materials,
                verification=verification,
                reproducibility=reproducibility,
                builder=builder,
            ),
        )
        statement_digest = StatementDigest(
            value=domain_separated_statement_sha256(statement)
        )
        attestation = ReleaseAttestation(
            statement=statement,
            statement_digest=statement_digest,
        )
    except ValidationError as exc:
        raise ReleaseAttestationError(
            f"release attestation input validation failed: {exc}"
        ) from exc

    final_source = _git_source_state(root)
    if final_source != source:
        raise ReleaseAttestationError("Git source drifted during attestation build")
    for resolved, binding, label in (
        (candidate, candidate_binding, "candidate ZIP"),
        (reproduced, reproduced_binding, "second-build ZIP"),
        (uv_lock, _material_binding("uv_lock", uv_lock), "uv.lock"),
        (sbom, _material_binding("sbom", sbom), "SBOM"),
        (
            full_receipt_file,
            _material_binding("full_test_receipt", full_receipt_file),
            "full-test receipt",
        ),
        (
            clean_receipt_file,
            _material_binding("clean_extract_receipt", clean_receipt_file),
            "clean-extract receipt",
        ),
        (
            build_one_receipt_file,
            _material_binding("build_one_receipt", build_one_receipt_file),
            "build-one receipt",
        ),
        (
            build_two_receipt_file,
            _material_binding("build_two_receipt", build_two_receipt_file),
            "build-two receipt",
        ),
    ):
        _assert_file_binding(resolved.absolute_path, binding, label=label)
    if _git_source_state(root) != source:
        raise ReleaseAttestationError("Git source drifted during attestation build")
    return attestation


def write_release_attestation(
    path: str | Path,
    attestation: ReleaseAttestation,
    *,
    project_root: str | Path,
    overwrite: bool = False,
) -> str:
    """Atomically write exact JCS bytes and return their raw file SHA-256."""

    root = _resolve_project_root(project_root)
    observed_source = _git_source_state(root)
    if attestation.statement.predicate.source != observed_source:
        raise ReleaseAttestationError(
            "attestation source does not match the clean output worktree"
        )
    supplied = Path(path)
    destination = supplied if supplied.is_absolute() else root / supplied
    destination = destination.absolute()
    try:
        relative_output = destination.relative_to(root).as_posix()
    except ValueError:
        relative_output = None
    if relative_output is not None:
        try:
            safe_output = _validate_stable_relative_path(relative_output)
        except ValueError as exc:
            raise ReleaseAttestationError(
                f"unsafe attestation output path: {exc}"
            ) from exc
        _reject_link_components(root, safe_output, label="attestation output")
        try:
            ignored = subprocess.run(
                [
                    "git",
                    "-c",
                    "core.excludesFile=",
                    "-C",
                    str(root),
                    "check-ignore",
                    "--no-index",
                    "-q",
                    "--",
                    safe_output,
                ],
                check=False,
                capture_output=True,
                env=_subprocess_env_without_git_overrides(),
                timeout=_SUBPROCESS_TIMEOUT_SECONDS,
            )
        except (OSError, subprocess.TimeoutExpired) as exc:
            raise ReleaseAttestationError(
                f"cannot verify attestation output ignore policy: {exc}"
            ) from exc
        if ignored.returncode != 0:
            raise ReleaseAttestationError(
                "attestation output inside the worktree must be explicitly ignored"
            )
    if destination.exists() and not overwrite:
        raise ReleaseAttestationError(
            "attestation output exists; explicit overwrite is required"
        )
    if destination.exists() and destination.is_dir():
        raise ReleaseAttestationError("attestation output is a directory")
    destination.parent.mkdir(parents=True, exist_ok=True)
    data = release_attestation_bytes(attestation)
    temporary_name: str | None = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="wb",
            dir=destination.parent,
            prefix=f".{destination.name}.",
            suffix=".tmp",
            delete=False,
        ) as handle:
            temporary_name = handle.name
            handle.write(data)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary_name, destination)
        temporary_name = None
    except OSError as exc:
        raise ReleaseAttestationError(f"cannot write attestation: {exc}") from exc
    finally:
        if temporary_name is not None:
            try:
                Path(temporary_name).unlink(missing_ok=True)
            except OSError:
                pass
    final_source = _git_source_state(root)
    if final_source != observed_source:
        raise ReleaseAttestationError(
            "Git source drifted while writing the release attestation"
        )
    return hashlib.sha256(data).hexdigest()


def load_release_attestation(path: str | Path) -> ReleaseAttestation:
    """Load a schema-strict, byte-canonical release attestation."""

    source = Path(path)
    model, _ = _load_canonical_model(
        source,
        ReleaseAttestation,
        artifact_name="release attestation",
    )
    return model


def verify_release_attestation(
    *,
    project_root: str | Path,
    attestation_path: str | Path,
) -> AttestationVerificationResult:
    """Verify self-digest, Git state, materials, receipts, and both ZIPs."""

    root = _resolve_project_root(project_root)
    attestation = load_release_attestation(attestation_path)
    statement = attestation.statement
    expected_statement_digest = domain_separated_statement_sha256(statement)
    if not hmac.compare_digest(
        expected_statement_digest,
        attestation.statement_digest.value,
    ):
        raise ReleaseAttestationError(
            "release Statement domain-separated digest verification failed"
        )

    observed_source = _git_source_state(root)
    predicate = statement.predicate
    if predicate.source != observed_source:
        raise ReleaseAttestationError(
            "attested Git commit/tree does not match the clean worktree"
        )
    _assert_toolchain(predicate.builder)

    build_one = predicate.reproducibility.build_one.artifact
    build_two = predicate.reproducibility.build_two.artifact
    build_one_path = _resolve_attested_file(
        root,
        build_one.path,
        label="candidate ZIP",
    )
    build_two_path = _resolve_attested_file(
        root,
        build_two.path,
        label="second-build ZIP",
    )
    try:
        same_file = os.path.samefile(build_one_path, build_two_path)
    except OSError as exc:
        raise ReleaseAttestationError(
            f"cannot compare attested two-build file identities: {exc}"
        ) from exc
    if same_file:
        raise ReleaseAttestationError(
            "attested two-build paths refer to the same underlying file"
        )
    _assert_file_binding(build_one_path, build_one, label="candidate ZIP")
    _assert_file_binding(build_two_path, build_two, label="second-build ZIP")
    if not zipfile.is_zipfile(build_one_path) or not zipfile.is_zipfile(build_two_path):
        raise ReleaseAttestationError("one or both attested release ZIPs are invalid")

    material_paths: dict[str, Path] = {}
    for material in predicate.materials:
        material_path = _resolve_attested_file(
            root,
            material.path,
            label=material.kind,
        )
        _assert_file_binding(material_path, material, label=material.kind)
        material_paths[material.kind] = material_path

    _validate_uv_lock(material_paths["uv_lock"])
    _validate_sbom(material_paths["sbom"])
    full_receipt, _ = _load_canonical_model(
        material_paths["full_test_receipt"],
        FullTestReceipt,
        artifact_name="full-test receipt",
    )
    clean_receipt, _ = _load_canonical_model(
        material_paths["clean_extract_receipt"],
        CleanExtractReceipt,
        artifact_name="clean-extract receipt",
    )
    build_one_receipt_model, _ = _load_canonical_model(
        material_paths["build_one_receipt"],
        ReleaseBuildReceipt,
        artifact_name="build-one receipt",
    )
    build_two_receipt_model, _ = _load_canonical_model(
        material_paths["build_two_receipt"],
        ReleaseBuildReceipt,
        artifact_name="build-two receipt",
    )
    material_by_kind = {item.kind: item for item in predicate.materials}
    _assert_full_test_receipt(
        full_receipt,
        root=root,
        source=observed_source,
        uv_lock_sha256=material_by_kind["uv_lock"].digest.sha256,
        sbom_sha256=material_by_kind["sbom"].digest.sha256,
    )
    _assert_clean_extract_receipt(
        clean_receipt,
        source=observed_source,
        candidate=build_one,
    )
    _assert_clean_extract_audit(
        clean_receipt,
        candidate_path=build_one_path,
        candidate=build_one,
        label="candidate ZIP",
    )
    _assert_clean_extract_audit(
        clean_receipt,
        candidate_path=build_two_path,
        candidate=build_two,
        label="second-build ZIP",
    )
    _assert_build_receipt(
        build_one_receipt_model,
        source=observed_source,
        uv_lock_sha256=material_by_kind["uv_lock"].digest.sha256,
        sbom_sha256=material_by_kind["sbom"].digest.sha256,
        builder=predicate.builder,
        expected_output=build_one,
        root=root,
        label="build-one receipt",
    )
    _assert_build_receipt(
        build_two_receipt_model,
        source=observed_source,
        uv_lock_sha256=material_by_kind["uv_lock"].digest.sha256,
        sbom_sha256=material_by_kind["sbom"].digest.sha256,
        builder=predicate.builder,
        expected_output=build_two,
        root=root,
        label="build-two receipt",
    )
    reproduction = predicate.reproducibility
    if (
        reproduction.build_one.invocation_id != build_one_receipt_model.invocation_id
        or reproduction.build_one.workspace != build_one_receipt_model.workspace
        or reproduction.build_two.invocation_id != build_two_receipt_model.invocation_id
        or reproduction.build_two.workspace != build_two_receipt_model.workspace
    ):
        raise ReleaseAttestationError(
            "reproducibility result does not match its build receipts"
        )

    full_summary = predicate.verification.full_test
    if (
        full_summary.junit_sha256 != full_receipt.junit.digest.sha256
        or full_summary.passed != full_receipt.result.passed
        or full_summary.skipped != full_receipt.result.skipped
        or full_summary.warnings != full_receipt.result.warnings
    ):
        raise ReleaseAttestationError("full-test summary does not match its receipt")
    clean_summary = predicate.verification.clean_extract
    if (
        clean_summary.entry_count != clean_receipt.audit.entry_count
        or clean_summary.verified_file_count != clean_receipt.audit.verified_file_count
        or clean_summary.required_paths != clean_receipt.required_paths
    ):
        raise ReleaseAttestationError(
            "clean-extract summary does not match its receipt"
        )

    for material in predicate.materials:
        _assert_file_binding(
            material_paths[material.kind],
            material,
            label=material.kind,
        )
    _assert_file_binding(build_one_path, build_one, label="candidate ZIP")
    _assert_file_binding(build_two_path, build_two, label="second-build ZIP")
    if _git_source_state(root) != observed_source:
        raise ReleaseAttestationError("Git source drifted during verification")

    return AttestationVerificationResult(
        release_id=predicate.release_id,
        subject=statement.subject[0],
        statement_digest=attestation.statement_digest,
        submission_eligible=False,
    )


__all__ = [
    "ATTESTATION_SCHEMA",
    "AttestationVerificationResult",
    "CLEAN_EXTRACT_RECEIPT_SCHEMA",
    "CleanExtractReceipt",
    "FULL_TEST_RECEIPT_SCHEMA",
    "FullTestReceipt",
    "get_clean_git_source_state",
    "RELEASE_BUILD_RECEIPT_SCHEMA",
    "RC3_REQUIRED_PATHS",
    "ReleaseAttestation",
    "ReleaseAttestationError",
    "ReleaseBuildReceipt",
    "build_release_attestation",
    "detect_release_toolchain",
    "domain_separated_statement_sha256",
    "load_release_attestation",
    "release_attestation_bytes",
    "verify_release_attestation",
    "write_release_attestation",
]
