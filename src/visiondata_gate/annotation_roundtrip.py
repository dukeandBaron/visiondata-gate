"""CVAT/FiftyOne remediation export, revision import, and same-contract recheck.

The core package does not require either external product.  It emits portable
JSON contracts, can probe CVAT reachability and identity read-only, and only
permits external ID binding after a connected, authenticated, hashed receipt.
Imported annotation bytes are decoded, hashed, mapped back to the original
sample/work order, and rechecked on a copy under the frozen contract.
"""

from __future__ import annotations

import base64
import binascii
import hashlib
import hmac
import io
import json
import math
import shutil
import urllib.error
import urllib.parse
import urllib.request
from enum import Enum
from pathlib import Path
from typing import Any, Literal, Mapping

from PIL import Image, UnidentifiedImageError
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from .contracts import BatchContract, BatchManifest, GateResult, SampleRecord, WorkOrder
from .evidence import (
    canonical_json_bytes,
    sha256_bytes,
    sha256_file,
    write_canonical_json,
)
from .pipeline import compute_batch_digest, run_gate
from .runtime_models import ScenarioProfile


class RoundtripModel(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


class AnnotationProvider(str, Enum):
    CVAT = "cvat"
    FIFTYONE = "fiftyone"


class ConnectorState(str, Enum):
    CONTRACT_READY_NOT_CONNECTED = "contract_ready_not_connected"
    LOCAL_ADAPTER_AVAILABLE = "local_adapter_available"
    LOCAL_CONTRACT_VERIFIED = "local_contract_verified"
    EXTERNAL_CONNECTED = "external_connected"


class ConnectorProbeReceipt(RoundtripModel):
    schema_version: Literal["visiondata-gate.connector-probe.v1"] = (
        "visiondata-gate.connector-probe.v1"
    )
    provider: AnnotationProvider
    endpoint_scope: Literal["none", "local", "remote"]
    connected: bool
    authenticated: bool
    read_only: Literal[True] = True
    server_version: str | None = None
    response_sha256: str | None = Field(default=None, min_length=64, max_length=64)
    error_type: str | None = None
    boundary_notice: str = (
        "A successful read-only probe proves endpoint reachability only; it does not "
        "prove dataset authorization, task write permission, or production deployment."
    )

    @model_validator(mode="after")
    def connection_flags_are_consistent(self) -> ConnectorProbeReceipt:
        if self.authenticated and not self.connected:
            raise ValueError("an authenticated probe must also be connected")
        if self.connected:
            if self.endpoint_scope == "none":
                raise ValueError("a connected probe must identify its endpoint scope")
            if self.response_sha256 is None:
                raise ValueError("a connected probe requires a response hash")
        return self


class AnnotationSampleMapping(RoundtripModel):
    internal_sample_id: str = Field(min_length=1)
    external_sample_key: str = Field(min_length=1)
    image_relative_path: str = Field(min_length=1)
    annotation_relative_path: str = Field(min_length=1)
    split: str = Field(min_length=1)
    category: str = Field(min_length=1)
    image_sha256: str = Field(min_length=64, max_length=64)
    prior_annotation_sha256: str | None = Field(
        default=None, min_length=64, max_length=64
    )
    annotation_version: str = Field(min_length=1)
    work_order_ids: list[str] = Field(default_factory=list)


class AnnotationTaskMapping(RoundtripModel):
    work_order_id: str = Field(min_length=1)
    action: str = Field(min_length=1)
    reason_codes: list[str] = Field(default_factory=list)
    sample_ids: list[str] = Field(default_factory=list)
    eligible_for_annotation_return: bool
    external_task_id: str | None = None


class AnnotationExportBundle(RoundtripModel):
    schema_version: Literal["visiondata-gate.annotation-export.v1"] = (
        "visiondata-gate.annotation-export.v1"
    )
    export_id: str = Field(min_length=1)
    task_id: str = Field(min_length=1)
    provider: AnnotationProvider
    connector_state: ConnectorState
    external_connected: bool = False
    batch_id: str = Field(min_length=1)
    contract_id: str = Field(min_length=1)
    source_input_sha256: str = Field(min_length=64, max_length=64)
    samples: list[AnnotationSampleMapping] = Field(default_factory=list)
    tasks: list[AnnotationTaskMapping] = Field(default_factory=list)
    provider_payload: dict[str, Any] = Field(default_factory=dict)
    boundary_notice: str = (
        "This package is a remediation adapter contract. External task IDs remain empty "
        "until a verified connector binds them; export creation alone is not a CVAT or "
        "FiftyOne connection receipt."
    )

    @model_validator(mode="after")
    def external_binding_is_consistent(self) -> AnnotationExportBundle:
        external_ids = [item.external_task_id for item in self.tasks]
        if self.external_connected:
            if self.connector_state is not ConnectorState.EXTERNAL_CONNECTED:
                raise ValueError(
                    "external connection flag requires EXTERNAL_CONNECTED state"
                )
            if not self.tasks or any(not item for item in external_ids):
                raise ValueError(
                    "external connection requires every task ID to be bound"
                )
        else:
            if self.connector_state is ConnectorState.EXTERNAL_CONNECTED:
                raise ValueError(
                    "EXTERNAL_CONNECTED state requires external_connected=true"
                )
            if any(item is not None for item in external_ids):
                raise ValueError("unconnected exports cannot contain external task IDs")
        return self


class AnnotationExportRecord(RoundtripModel):
    bundle: AnnotationExportBundle
    export_sha256: str = Field(min_length=64, max_length=64)

    @model_validator(mode="after")
    def export_digest_matches_bundle(self) -> AnnotationExportRecord:
        observed = sha256_bytes(canonical_json_bytes(self.bundle))
        if not hmac.compare_digest(self.export_sha256, observed):
            raise ValueError("export_sha256 does not match the canonical bundle")
        return self


class AnnotationRevision(RoundtripModel):
    work_order_id: str = Field(min_length=1)
    internal_sample_id: str = Field(min_length=1)
    external_sample_key: str = Field(min_length=1)
    external_task_id: str | None = None
    source_image_sha256: str = Field(min_length=64, max_length=64)
    prior_annotation_sha256: str | None = Field(
        default=None, min_length=64, max_length=64
    )
    annotation_version: str = Field(min_length=1, max_length=120)
    annotation_content_base64: str = Field(min_length=1, max_length=8_000_000)


class AnnotationImportPackage(RoundtripModel):
    schema_version: Literal["visiondata-gate.annotation-import.v1"] = (
        "visiondata-gate.annotation-import.v1"
    )
    export_id: str = Field(min_length=1)
    provider: AnnotationProvider
    revisions: list[AnnotationRevision] = Field(min_length=1, max_length=500)

    @field_validator("revisions")
    @classmethod
    def unique_revision_samples(
        cls, values: list[AnnotationRevision]
    ) -> list[AnnotationRevision]:
        keys = [item.internal_sample_id for item in values]
        if len(keys) != len(set(keys)):
            raise ValueError("only one revision per internal sample is allowed")
        return values


class AnnotationRevisionCheck(RoundtripModel):
    internal_sample_id: str = Field(min_length=1)
    work_order_id: str = Field(min_length=1)
    accepted: bool
    returned_annotation_sha256: str | None = Field(
        default=None, min_length=64, max_length=64
    )
    stored_relative_path: str | None = None
    issues: list[str] = Field(default_factory=list)


class AnnotationRoundtripReceipt(RoundtripModel):
    schema_version: Literal["visiondata-gate.annotation-roundtrip-receipt.v1"] = (
        "visiondata-gate.annotation-roundtrip-receipt.v1"
    )
    receipt_id: str = Field(min_length=1)
    task_id: str = Field(min_length=1)
    export_id: str = Field(min_length=1)
    provider: AnnotationProvider
    connector_state: ConnectorState
    external_connected: bool
    export_sha256: str = Field(min_length=64, max_length=64)
    import_sha256: str = Field(min_length=64, max_length=64)
    submitted_revision_count: int = Field(ge=0)
    accepted_revision_count: int = Field(ge=0)
    roundtrip_fidelity: float = Field(ge=0.0, le=1.0)
    eligible_work_order_count: int = Field(ge=0)
    closed_work_order_count: int = Field(ge=0)
    closed_work_order_ids: list[str] = Field(default_factory=list)
    unresolved_work_order_ids: list[str] = Field(default_factory=list)
    remediation_closure_rate: float | None = Field(default=None, ge=0.0, le=1.0)
    same_contract_recheck_performed: bool
    recheck_contract_id: str | None = None
    recheck_input_sha256: str | None = Field(default=None, min_length=64, max_length=64)
    recheck_decision: str | None = None
    recheck_manifest_sha256: str | None = Field(
        default=None, min_length=64, max_length=64
    )
    recheck_gate_result_sha256: str | None = Field(
        default=None, min_length=64, max_length=64
    )
    original_input_unchanged: bool
    checks: list[AnnotationRevisionCheck] = Field(default_factory=list)
    boundary_notice: str = (
        "LOCAL_CONTRACT_VERIFIED proves the JSON/hash/recheck roundtrip on local bytes. "
        "It does not prove an external CVAT/FiftyOne service was connected; that requires "
        "external_connected=true and a separate successful connector probe."
    )

    @model_validator(mode="after")
    def receipt_counts_and_artifacts_are_consistent(
        self,
    ) -> AnnotationRoundtripReceipt:
        expected_state = (
            ConnectorState.EXTERNAL_CONNECTED
            if self.external_connected
            else ConnectorState.LOCAL_CONTRACT_VERIFIED
        )
        if self.connector_state is not expected_state:
            raise ValueError("roundtrip connector state is inconsistent")
        if self.accepted_revision_count > self.submitted_revision_count:
            raise ValueError("accepted revisions exceed submitted revisions")
        if len(self.checks) != self.submitted_revision_count:
            raise ValueError("revision check count does not match submitted revisions")
        expected_fidelity = (
            self.accepted_revision_count / self.submitted_revision_count
            if self.submitted_revision_count
            else 0.0
        )
        if not math.isclose(self.roundtrip_fidelity, expected_fidelity, abs_tol=1e-12):
            raise ValueError("roundtrip fidelity does not match revision counts")
        if len(self.closed_work_order_ids) != len(set(self.closed_work_order_ids)):
            raise ValueError("closed work-order IDs must be unique")
        if len(self.unresolved_work_order_ids) != len(
            set(self.unresolved_work_order_ids)
        ):
            raise ValueError("unresolved work-order IDs must be unique")
        if set(self.closed_work_order_ids) & set(self.unresolved_work_order_ids):
            raise ValueError("closed and unresolved work-order IDs overlap")
        if self.closed_work_order_count != len(self.closed_work_order_ids):
            raise ValueError("closed work-order count does not match its ID list")
        if self.eligible_work_order_count != (
            len(self.closed_work_order_ids) + len(self.unresolved_work_order_ids)
        ):
            raise ValueError(
                "eligible work-order count does not match receipt ID lists"
            )
        expected_closure = (
            self.closed_work_order_count / self.eligible_work_order_count
            if self.eligible_work_order_count
            else None
        )
        if expected_closure is None:
            if self.remediation_closure_rate is not None:
                raise ValueError(
                    "closure rate requires an eligible work-order denominator"
                )
        elif self.remediation_closure_rate is None or not math.isclose(
            self.remediation_closure_rate, expected_closure, abs_tol=1e-12
        ):
            raise ValueError("closure rate does not match work-order counts")
        artifact_fields = (
            self.recheck_contract_id,
            self.recheck_input_sha256,
            self.recheck_decision,
            self.recheck_manifest_sha256,
            self.recheck_gate_result_sha256,
        )
        if self.same_contract_recheck_performed:
            if self.accepted_revision_count == 0 or any(
                value is None for value in artifact_fields
            ):
                raise ValueError(
                    "performed recheck requires accepted bytes and all hashes"
                )
            if not self.original_input_unchanged:
                raise ValueError("performed recheck requires an unchanged source input")
        elif self.accepted_revision_count or any(
            value is not None for value in artifact_fields
        ):
            raise ValueError(
                "unperformed recheck cannot claim accepted bytes or artifacts"
            )
        return self


class AnnotationReceiptIntegrity(RoundtripModel):
    schema_version: Literal["visiondata-gate.annotation-receipt-integrity.v1"] = (
        "visiondata-gate.annotation-receipt-integrity.v1"
    )
    receipt_id: str = Field(min_length=1)
    receipt_sha256: str = Field(min_length=64, max_length=64)


_MAX_ANNOTATION_BYTES = 5_000_000
_MAX_PROBE_RESPONSE_BYTES = 1_000_000


def _is_local_endpoint(endpoint: str) -> bool:
    host = (urllib.parse.urlparse(endpoint).hostname or "").casefold()
    return host in {"127.0.0.1", "localhost", "::1"}


def _read_probe_response(response: Any) -> bytes:
    raw = response.read(_MAX_PROBE_RESPONSE_BYTES + 1)
    if len(raw) > _MAX_PROBE_RESPONSE_BYTES:
        raise ValueError("connector probe response exceeds size limit")
    return raw


class _NoCvatProbeRedirectHandler(urllib.request.HTTPRedirectHandler):
    """Reject every CVAT probe redirect before credentials can change origin."""

    def redirect_request(
        self,
        req: urllib.request.Request,
        fp: Any,
        code: int,
        msg: str,
        headers: Any,
        newurl: str,
    ) -> None:
        del req, fp, code, msg, headers, newurl
        return None


def _open_cvat_probe_request(
    request: urllib.request.Request,
    *,
    timeout_seconds: float,
) -> Any:
    opener = urllib.request.build_opener(_NoCvatProbeRedirectHandler())
    return opener.open(request, timeout=timeout_seconds)


def probe_cvat_endpoint(
    endpoint: str,
    *,
    token: str | None = None,
    allow_remote: bool = False,
    timeout_seconds: float = 5.0,
) -> ConnectorProbeReceipt:
    """Perform one bounded read-only CVAT server probe without storing secrets."""

    base = endpoint.strip().rstrip("/")
    parsed = urllib.parse.urlparse(base)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        raise ValueError("CVAT endpoint must be an absolute http(s) URL")
    local = _is_local_endpoint(base)
    if not local and not allow_remote:
        raise PermissionError("remote CVAT probes are disabled by policy")
    if not local and parsed.scheme != "https":
        raise PermissionError("remote CVAT endpoint must use HTTPS")
    headers = {"Accept": "application/json"}
    if token:
        headers["Authorization"] = f"Token {token}"
    about_request = urllib.request.Request(
        f"{base}/api/server/about", headers=headers, method="GET"
    )
    try:
        with _open_cvat_probe_request(
            about_request, timeout_seconds=timeout_seconds
        ) as response:
            about_raw = _read_probe_response(response)
            payload = json.loads(about_raw.decode("utf-8"))
    except (
        OSError,
        urllib.error.URLError,
        UnicodeDecodeError,
        json.JSONDecodeError,
        ValueError,
    ) as error:
        return ConnectorProbeReceipt(
            provider=AnnotationProvider.CVAT,
            endpoint_scope="local" if local else "remote",
            connected=False,
            authenticated=False,
            error_type=type(error).__name__,
        )
    version = None
    if isinstance(payload, dict):
        version = str(payload.get("version") or payload.get("name") or "unknown")
    authenticated = False
    auth_raw: bytes | None = None
    auth_error: str | None = None
    if token:
        auth_request = urllib.request.Request(
            f"{base}/api/users/self", headers=headers, method="GET"
        )
        try:
            with _open_cvat_probe_request(
                auth_request, timeout_seconds=timeout_seconds
            ) as response:
                auth_raw = _read_probe_response(response)
                auth_payload = json.loads(auth_raw.decode("utf-8"))
                if not isinstance(auth_payload, dict):
                    raise ValueError("CVAT identity response must be a JSON object")
        except (
            OSError,
            urllib.error.URLError,
            UnicodeDecodeError,
            json.JSONDecodeError,
            ValueError,
        ) as error:
            auth_error = f"authentication_probe_failed:{type(error).__name__}"
        else:
            authenticated = True
    digest_material = about_raw + (b"\n" + auth_raw if auth_raw is not None else b"")
    return ConnectorProbeReceipt(
        provider=AnnotationProvider.CVAT,
        endpoint_scope="local" if local else "remote",
        connected=True,
        authenticated=authenticated,
        server_version=version,
        response_sha256=sha256_bytes(digest_material),
        error_type=auth_error,
    )


def probe_fiftyone_library() -> ConnectorProbeReceipt:
    """Report optional local library availability without opening a dataset."""

    try:
        import fiftyone as fo  # type: ignore[import-not-found]
    except (ImportError, OSError) as error:
        return ConnectorProbeReceipt(
            provider=AnnotationProvider.FIFTYONE,
            endpoint_scope="none",
            connected=False,
            authenticated=False,
            error_type=type(error).__name__,
        )
    version = str(getattr(fo, "__version__", "unknown"))
    return ConnectorProbeReceipt(
        provider=AnnotationProvider.FIFTYONE,
        endpoint_scope="local",
        connected=False,
        authenticated=False,
        server_version=version,
        response_sha256=sha256_bytes(version.encode("utf-8")),
        boundary_notice=(
            "The local FiftyOne adapter library is importable, but no dataset, App "
            "session, cloud workspace, identity, or external annotation service was "
            "opened. Library availability is not an external connection receipt."
        ),
    )


def _relative_parts(value: str) -> tuple[str, ...]:
    normalized = value.replace("\\", "/")
    parts = tuple(normalized.split("/"))
    if not parts or any(part in {"", ".", ".."} for part in parts):
        raise ValueError(f"unsafe relative path: {value}")
    if normalized.startswith("/") or any(":" in part for part in parts):
        raise ValueError(f"unsafe relative path: {value}")
    return parts


def _safe_member(root: Path, relative: str, *, must_exist: bool) -> Path:
    resolved_root = root.expanduser().resolve(strict=True)
    candidate = resolved_root.joinpath(*_relative_parts(relative)).resolve(strict=False)
    try:
        candidate.relative_to(resolved_root)
    except ValueError as error:
        raise ValueError(f"path escaped batch root: {relative}") from error
    if must_exist and not candidate.is_file():
        raise FileNotFoundError(candidate)
    return candidate


def _suggested_annotation_path(sample: SampleRecord) -> str:
    digest = hashlib.sha256(sample.sample_id.encode("utf-8")).hexdigest()[:20]
    return f"annotations/returned-{digest}.png"


def _sample_work_orders(sample_id: str, work_orders: list[WorkOrder]) -> list[str]:
    return sorted(
        item.work_order_id for item in work_orders if sample_id in item.sample_ids
    )


def _provider_payload(
    provider: AnnotationProvider,
    *,
    export_id: str,
    samples: list[AnnotationSampleMapping],
    tasks: list[AnnotationTaskMapping],
) -> dict[str, Any]:
    if provider is AnnotationProvider.CVAT:
        return {
            "contract": "cvat-rest-task-spec.v1",
            "client_request_id": export_id,
            "task_specs": [
                {
                    "client_task_key": item.work_order_id,
                    "name": f"VisionData Gate {item.work_order_id}",
                    "action": item.action,
                    "asset_refs": [
                        {
                            "external_sample_key": sample.external_sample_key,
                            "image_relative_path": sample.image_relative_path,
                            "image_sha256": sample.image_sha256,
                        }
                        for sample in samples
                        if sample.internal_sample_id in item.sample_ids
                    ],
                    "labels": [{"name": "foreground", "type": "mask"}],
                }
                for item in tasks
            ],
        }
    return {
        "contract": "fiftyone-sample-patch.v1",
        "dataset_key": export_id,
        "samples": [
            {
                "external_sample_key": item.external_sample_key,
                "filepath_ref": item.image_relative_path,
                "image_sha256": item.image_sha256,
                "tags": ["visiondata-gate", *item.work_order_ids],
                "fields": {
                    "annotation_path_ref": item.annotation_relative_path,
                    "annotation_version": item.annotation_version,
                },
            }
            for item in samples
        ],
    }


def build_annotation_export(
    *,
    task_id: str,
    batch_root: str | Path,
    manifest: BatchManifest,
    contract: BatchContract,
    gate_result: GateResult,
    provider: AnnotationProvider,
) -> AnnotationExportBundle:
    """Map gate work orders and sample hashes into a portable adapter bundle."""

    root = Path(batch_root).expanduser().resolve(strict=True)
    if contract.contract_id != gate_result.contract_id:
        raise ValueError("gate result contract does not match export contract")
    observed_input = compute_batch_digest(root, manifest, contract)
    if observed_input != gate_result.input_sha256:
        raise ValueError("gate result input hash does not match current batch bytes")
    work_orders = list(gate_result.work_orders)
    referenced_ids = sorted(
        {sample_id for item in work_orders for sample_id in item.sample_ids}
    )
    manifest_by_id = {item.sample_id: item for item in manifest.samples}
    unknown = sorted(set(referenced_ids) - set(manifest_by_id))
    if unknown:
        raise ValueError(f"work orders reference unknown samples: {', '.join(unknown)}")

    samples: list[AnnotationSampleMapping] = []
    for sample_id in referenced_ids:
        sample = manifest_by_id[sample_id]
        image_path = _safe_member(root, sample.relative_path, must_exist=True)
        annotation_relative = sample.annotation_path or _suggested_annotation_path(
            sample
        )
        annotation_path = _safe_member(root, annotation_relative, must_exist=False)
        prior_digest = (
            sha256_file(annotation_path) if annotation_path.is_file() else None
        )
        samples.append(
            AnnotationSampleMapping(
                internal_sample_id=sample.sample_id,
                external_sample_key=f"vdg:{sample.sample_id}",
                image_relative_path=sample.relative_path,
                annotation_relative_path=annotation_relative,
                split=sample.split,
                category=sample.category,
                image_sha256=sha256_file(image_path),
                prior_annotation_sha256=prior_digest,
                annotation_version=(
                    f"sha256:{prior_digest}" if prior_digest else "missing"
                ),
                work_order_ids=_sample_work_orders(sample.sample_id, work_orders),
            )
        )

    tasks = [
        AnnotationTaskMapping(
            work_order_id=item.work_order_id,
            action=item.action,
            reason_codes=list(item.reason_codes),
            sample_ids=list(item.sample_ids),
            eligible_for_annotation_return=(
                item.action == "RELABEL" and bool(item.sample_ids)
            ),
        )
        for item in sorted(work_orders, key=lambda value: value.work_order_id)
    ]
    export_material = {
        "task_id": task_id,
        "provider": provider.value,
        "batch_id": gate_result.batch_id,
        "contract_id": gate_result.contract_id,
        "source_input_sha256": gate_result.input_sha256,
        "sample_ids": referenced_ids,
        "work_order_ids": [item.work_order_id for item in tasks],
    }
    export_id = (
        "annexp-"
        + hashlib.sha256(canonical_json_bytes(export_material)).hexdigest()[:20]
    )
    return AnnotationExportBundle(
        export_id=export_id,
        task_id=task_id,
        provider=provider,
        connector_state=ConnectorState.CONTRACT_READY_NOT_CONNECTED,
        external_connected=False,
        batch_id=gate_result.batch_id,
        contract_id=gate_result.contract_id,
        source_input_sha256=gate_result.input_sha256,
        samples=samples,
        tasks=tasks,
        provider_payload=_provider_payload(
            provider, export_id=export_id, samples=samples, tasks=tasks
        ),
    )


def write_annotation_export(
    path: str | Path, bundle: AnnotationExportBundle
) -> AnnotationExportRecord:
    digest = write_canonical_json(path, bundle)
    return AnnotationExportRecord(bundle=bundle, export_sha256=digest)


def bind_external_task_ids(
    bundle: AnnotationExportBundle,
    task_ids: Mapping[str, str],
    probe: ConnectorProbeReceipt,
) -> AnnotationExportBundle:
    """Bind provider task IDs only after a successful matching probe."""

    if probe.provider is not bundle.provider:
        raise ValueError("connector probe provider does not match export provider")
    if not probe.connected:
        raise PermissionError("cannot bind external IDs without a connected probe")
    if not probe.authenticated:
        raise PermissionError("cannot bind external IDs without an authenticated probe")
    if probe.response_sha256 is None:
        raise PermissionError(
            "cannot bind external IDs without a hashed probe response"
        )
    expected = {item.work_order_id for item in bundle.tasks}
    if set(task_ids) != expected:
        raise ValueError("external task mapping must cover every exported work order")
    if any(not str(value).strip() for value in task_ids.values()):
        raise ValueError("external task IDs cannot be blank")
    tasks = [
        item.model_copy(update={"external_task_id": str(task_ids[item.work_order_id])})
        for item in bundle.tasks
    ]
    return bundle.model_copy(
        update={
            "tasks": tasks,
            "connector_state": ConnectorState.EXTERNAL_CONNECTED,
            "external_connected": True,
        }
    )


def _decode_annotation(value: str) -> bytes:
    try:
        raw = base64.b64decode(value.encode("ascii"), validate=True)
    except (UnicodeEncodeError, binascii.Error) as error:
        raise ValueError("annotation payload is not strict base64") from error
    if not raw:
        raise ValueError("annotation payload is empty")
    if len(raw) > _MAX_ANNOTATION_BYTES:
        raise ValueError("annotation payload exceeds size limit")
    return raw


def _validate_mask(raw: bytes, contract: BatchContract) -> list[str]:
    expected = (
        contract.thresholds.expected_width,
        contract.thresholds.expected_height,
    )
    try:
        with Image.open(io.BytesIO(raw)) as image:
            observed = image.size
            image_format = image.format
            image_mode = image.mode
            if observed != expected:
                return ["annotation_dimensions_mismatch"]
            issues: list[str] = []
            if image_format != "PNG":
                issues.append("annotation_format_not_png")
            if image_mode not in {"1", "L", "P"}:
                issues.append("annotation_mask_mode_invalid")
            image.verify()
    except (UnidentifiedImageError, SyntaxError, OSError):
        return ["annotation_decode_failed"]
    return issues


def _copy_batch(
    source_root: Path,
    destination: Path,
    manifest: BatchManifest,
) -> None:
    if destination.exists():
        raise FileExistsError(destination)
    destination.mkdir(parents=True)
    for sample in manifest.samples:
        for relative in [sample.relative_path, sample.annotation_path]:
            if relative is None:
                continue
            source = _safe_member(source_root, relative, must_exist=False)
            if not source.is_file():
                continue
            target = destination.joinpath(*_relative_parts(relative))
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(source, target)


def import_revisions_and_recheck(
    *,
    export: AnnotationExportRecord,
    package: AnnotationImportPackage,
    batch_root: str | Path,
    manifest: BatchManifest,
    contract: BatchContract,
    scenario_profile: ScenarioProfile,
    output_root: str | Path,
) -> AnnotationRoundtripReceipt:
    """Validate returned bytes, preserve the source batch, and rerun the gate."""

    bundle = export.bundle
    observed_export_sha256 = sha256_bytes(canonical_json_bytes(bundle))
    if not hmac.compare_digest(export.export_sha256, observed_export_sha256):
        raise ValueError("annotation export hash does not match its bundle")
    if package.export_id != bundle.export_id:
        raise ValueError("import export_id does not match the frozen export")
    if package.provider is not bundle.provider:
        raise ValueError("import provider does not match the frozen export")
    if contract.contract_id != bundle.contract_id:
        raise ValueError("recheck contract does not match the frozen export")
    if manifest.batch_id != bundle.batch_id:
        raise ValueError("recheck manifest batch does not match the frozen export")
    source_root = Path(batch_root).expanduser().resolve(strict=True)
    if not source_root.is_dir():
        raise NotADirectoryError(source_root)
    destination = Path(output_root).expanduser().resolve(strict=False)
    try:
        destination.relative_to(source_root)
    except ValueError:
        pass
    else:
        raise ValueError("recheck output root must be outside the source batch")
    original_digest_before = compute_batch_digest(source_root, manifest, contract)
    if not hmac.compare_digest(original_digest_before, bundle.source_input_sha256):
        raise ValueError("source batch changed after annotation export")
    import_sha256 = sha256_bytes(canonical_json_bytes(package))
    receipt_id = f"annrt-{import_sha256[:20]}"
    write_canonical_json(destination.parent / "annotation_import.json", package)

    sample_map = {item.internal_sample_id: item for item in bundle.samples}
    task_map = {item.work_order_id: item for item in bundle.tasks}
    accepted: dict[str, tuple[AnnotationRevision, bytes]] = {}
    checks: list[AnnotationRevisionCheck] = []
    for revision in package.revisions:
        issues: list[str] = []
        mapping = sample_map.get(revision.internal_sample_id)
        task = task_map.get(revision.work_order_id)
        raw: bytes | None = None
        if mapping is None:
            issues.append("unknown_internal_sample_id")
        if task is None:
            issues.append("unknown_work_order_id")
        elif not task.eligible_for_annotation_return:
            issues.append("work_order_not_annotation_return_eligible")
        elif revision.internal_sample_id not in task.sample_ids:
            issues.append("sample_not_mapped_to_work_order")
        if mapping is not None:
            if revision.external_sample_key != mapping.external_sample_key:
                issues.append("external_sample_key_mismatch")
            if revision.source_image_sha256 != mapping.image_sha256:
                issues.append("source_image_sha256_mismatch")
            if revision.prior_annotation_sha256 != mapping.prior_annotation_sha256:
                issues.append("prior_annotation_sha256_mismatch")
            if revision.annotation_version == mapping.annotation_version:
                issues.append("annotation_version_not_advanced")
        if task is not None and bundle.external_connected:
            if revision.external_task_id != task.external_task_id:
                issues.append("external_task_id_mismatch")
        try:
            raw = _decode_annotation(revision.annotation_content_base64)
        except ValueError as error:
            issues.append(str(error).replace(" ", "_"))
        if raw is not None:
            issues.extend(_validate_mask(raw, contract))
        returned_digest = sha256_bytes(raw) if raw is not None else None
        if not issues and mapping is not None and raw is not None:
            accepted[revision.internal_sample_id] = (revision, raw)
        checks.append(
            AnnotationRevisionCheck(
                internal_sample_id=revision.internal_sample_id,
                work_order_id=revision.work_order_id,
                accepted=not issues,
                returned_annotation_sha256=returned_digest,
                stored_relative_path=(
                    mapping.annotation_relative_path
                    if not issues and mapping is not None
                    else None
                ),
                issues=issues,
            )
        )

    revised_manifest = manifest
    recheck = None
    if accepted:
        _copy_batch(source_root, destination, manifest)
        updates = {
            sample_id: sample_map[sample_id].annotation_relative_path
            for sample_id in accepted
        }
        revised_samples = [
            item.model_copy(
                update={
                    "annotation_path": updates.get(item.sample_id, item.annotation_path)
                }
            )
            for item in manifest.samples
        ]
        revised_manifest = manifest.model_copy(update={"samples": revised_samples})
        for sample_id, (_revision, raw) in accepted.items():
            relative = sample_map[sample_id].annotation_relative_path
            target = destination.joinpath(*_relative_parts(relative))
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(raw)
        recheck_manifest_sha256 = write_canonical_json(
            destination / "batch_manifest.json", revised_manifest
        )
        recheck = run_gate(
            destination,
            revised_manifest,
            contract,
            scenario_profile=scenario_profile,
        )
        recheck_gate_result_sha256 = write_canonical_json(
            destination / "recheck_gate_result.json", recheck
        )
    else:
        recheck_manifest_sha256 = None
        recheck_gate_result_sha256 = None

    original_digest_after = compute_batch_digest(source_root, manifest, contract)
    if not hmac.compare_digest(original_digest_before, original_digest_after):
        raise ValueError("source batch changed during annotation recheck")
    eligible_tasks = [
        item for item in bundle.tasks if item.eligible_for_annotation_return
    ]
    accepted_ids = set(accepted)
    closed_tasks: list[AnnotationTaskMapping] = []
    if recheck is not None:
        for item in eligible_tasks:
            all_samples_accepted = bool(item.sample_ids) and set(item.sample_ids) <= (
                accepted_ids
            )
            original_reason_remains = any(
                finding.code in item.reason_codes
                and (
                    not finding.sample_ids
                    or bool(set(finding.sample_ids) & set(item.sample_ids))
                )
                for finding in recheck.findings
            )
            if all_samples_accepted and not original_reason_remains:
                closed_tasks.append(item)
    closed_ids = sorted(item.work_order_id for item in closed_tasks)
    unresolved_ids = sorted(
        item.work_order_id for item in eligible_tasks if item not in closed_tasks
    )
    receipt = AnnotationRoundtripReceipt(
        receipt_id=receipt_id,
        task_id=bundle.task_id,
        export_id=bundle.export_id,
        provider=bundle.provider,
        connector_state=(
            ConnectorState.EXTERNAL_CONNECTED
            if bundle.external_connected
            else ConnectorState.LOCAL_CONTRACT_VERIFIED
        ),
        external_connected=bundle.external_connected,
        export_sha256=export.export_sha256,
        import_sha256=import_sha256,
        submitted_revision_count=len(package.revisions),
        accepted_revision_count=len(accepted),
        roundtrip_fidelity=(len(accepted) / len(package.revisions)),
        eligible_work_order_count=len(eligible_tasks),
        closed_work_order_count=len(closed_tasks),
        closed_work_order_ids=closed_ids,
        unresolved_work_order_ids=unresolved_ids,
        remediation_closure_rate=(
            len(closed_tasks) / len(eligible_tasks) if eligible_tasks else None
        ),
        same_contract_recheck_performed=recheck is not None,
        recheck_contract_id=contract.contract_id if recheck is not None else None,
        recheck_input_sha256=recheck.input_sha256 if recheck is not None else None,
        recheck_decision=recheck.decision.value if recheck is not None else None,
        recheck_manifest_sha256=recheck_manifest_sha256,
        recheck_gate_result_sha256=recheck_gate_result_sha256,
        original_input_unchanged=True,
        checks=checks,
    )
    receipt_path = destination.parent / f"{receipt_id}.receipt.json"
    receipt_sha256 = write_canonical_json(receipt_path, receipt)
    write_canonical_json(
        destination.parent / f"{receipt_id}.integrity.json",
        AnnotationReceiptIntegrity(
            receipt_id=receipt_id,
            receipt_sha256=receipt_sha256,
        ),
    )
    return receipt


__all__ = [
    "AnnotationExportBundle",
    "AnnotationExportRecord",
    "AnnotationImportPackage",
    "AnnotationProvider",
    "AnnotationRevision",
    "AnnotationReceiptIntegrity",
    "AnnotationRoundtripReceipt",
    "ConnectorProbeReceipt",
    "ConnectorState",
    "bind_external_task_ids",
    "build_annotation_export",
    "import_revisions_and_recheck",
    "probe_cvat_endpoint",
    "probe_fiftyone_library",
    "write_annotation_export",
]
