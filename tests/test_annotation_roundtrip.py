from __future__ import annotations

import base64
from contextlib import contextmanager
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import io
import json
import sys
import threading
from pathlib import Path
from types import SimpleNamespace
from typing import Any, Iterator

import pytest
from PIL import Image

from visiondata_gate.annotation_roundtrip import (
    AnnotationImportPackage,
    AnnotationProvider,
    AnnotationRevision,
    ConnectorProbeReceipt,
    ConnectorState,
    bind_external_task_ids,
    build_annotation_export,
    import_revisions_and_recheck,
    probe_cvat_endpoint,
    probe_fiftyone_library,
    write_annotation_export,
)
from visiondata_gate.contracts import BatchContract, BatchManifest
from visiondata_gate.generator import generate_demo_dataset
from visiondata_gate.pipeline import compute_batch_digest, run_gate
from visiondata_gate.runtime_models import ScenarioProfile


def _gate_fixture(tmp_path: Path):
    paths = generate_demo_dataset(tmp_path / "dataset", seed=20260820)
    manifest = BatchManifest.model_validate_json(
        paths["batch_manifest"].read_text(encoding="utf-8")
    )
    contract = BatchContract()
    result = run_gate(paths["batch_root"], manifest, contract)
    bundle = build_annotation_export(
        task_id="task-roundtrip-test",
        batch_root=paths["batch_root"],
        manifest=manifest,
        contract=contract,
        gate_result=result,
        provider=AnnotationProvider.CVAT,
    )
    record = write_annotation_export(tmp_path / "annotation_export.json", bundle)
    return paths, manifest, contract, result, record


def _mask_base64(*, mode: str = "L") -> str:
    buffer = io.BytesIO()
    color: int | tuple[int, int, int] = 255 if mode == "L" else (255, 0, 0)
    Image.new(mode, (128, 128), color=color).save(buffer, format="PNG")
    return base64.b64encode(buffer.getvalue()).decode("ascii")


def _valid_revision(record: Any) -> AnnotationRevision:
    task = next(
        item for item in record.bundle.tasks if item.eligible_for_annotation_return
    )
    sample = next(
        item
        for item in record.bundle.samples
        if item.internal_sample_id in task.sample_ids
    )
    return AnnotationRevision(
        work_order_id=task.work_order_id,
        internal_sample_id=sample.internal_sample_id,
        external_sample_key=sample.external_sample_key,
        source_image_sha256=sample.image_sha256,
        prior_annotation_sha256=sample.prior_annotation_sha256,
        annotation_version="review-v2",
        annotation_content_base64=_mask_base64(),
    )


def test_export_maps_gate_work_orders_samples_versions_and_hashes(
    tmp_path: Path,
) -> None:
    paths, manifest, contract, result, record = _gate_fixture(tmp_path)

    assert record.bundle.external_connected is False
    assert record.bundle.connector_state is ConnectorState.CONTRACT_READY_NOT_CONNECTED
    assert record.bundle.source_input_sha256 == result.input_sha256
    assert record.bundle.contract_id == contract.contract_id
    assert record.bundle.tasks
    assert any(item.eligible_for_annotation_return for item in record.bundle.tasks)
    assert record.bundle.samples
    assert record.bundle.provider_payload["contract"] == "cvat-rest-task-spec.v1"
    assert (
        compute_batch_digest(paths["batch_root"], manifest, contract)
        == result.input_sha256
    )
    assert len(record.export_sha256) == 64


def test_export_refuses_gate_result_bound_to_different_bytes(tmp_path: Path) -> None:
    paths, manifest, contract, result, _record = _gate_fixture(tmp_path)
    image = paths["batch_root"] / manifest.samples[0].relative_path
    image.write_bytes(image.read_bytes() + b"tampered")

    with pytest.raises(ValueError, match="input hash"):
        build_annotation_export(
            task_id="task-tampered",
            batch_root=paths["batch_root"],
            manifest=manifest,
            contract=contract,
            gate_result=result,
            provider=AnnotationProvider.CVAT,
        )


def test_external_ids_require_successful_probe_and_full_mapping(tmp_path: Path) -> None:
    _paths, _manifest, _contract, _result, record = _gate_fixture(tmp_path)
    ids = {
        item.work_order_id: f"cvat-{index}"
        for index, item in enumerate(record.bundle.tasks, start=1)
    }
    blocked_probe = ConnectorProbeReceipt(
        provider=AnnotationProvider.CVAT,
        endpoint_scope="local",
        connected=False,
        authenticated=False,
        error_type="ConnectionRefusedError",
    )
    with pytest.raises(PermissionError):
        bind_external_task_ids(record.bundle, ids, blocked_probe)

    unauthenticated_probe = ConnectorProbeReceipt(
        provider=AnnotationProvider.CVAT,
        endpoint_scope="local",
        connected=True,
        authenticated=False,
        server_version="2.40.0",
        response_sha256="b" * 64,
    )
    with pytest.raises(PermissionError, match="authenticated"):
        bind_external_task_ids(record.bundle, ids, unauthenticated_probe)

    connected_probe = ConnectorProbeReceipt(
        provider=AnnotationProvider.CVAT,
        endpoint_scope="local",
        connected=True,
        authenticated=True,
        server_version="2.40.0",
        response_sha256="a" * 64,
    )
    bound = bind_external_task_ids(record.bundle, ids, connected_probe)

    assert bound.external_connected is True
    assert bound.connector_state is ConnectorState.EXTERNAL_CONNECTED
    assert {item.external_task_id for item in bound.tasks} == set(ids.values())


def test_valid_revision_roundtrip_rechecks_same_contract_without_source_mutation(
    tmp_path: Path,
) -> None:
    paths, manifest, contract, _result, record = _gate_fixture(tmp_path)
    source_digest = compute_batch_digest(paths["batch_root"], manifest, contract)
    package = AnnotationImportPackage(
        export_id=record.bundle.export_id,
        provider=record.bundle.provider,
        revisions=[_valid_revision(record)],
    )

    receipt = import_revisions_and_recheck(
        export=record,
        package=package,
        batch_root=paths["batch_root"],
        manifest=manifest,
        contract=contract,
        scenario_profile=ScenarioProfile.GENERIC,
        output_root=tmp_path / "roundtrip" / "rechecked_batch",
    )

    assert receipt.connector_state is ConnectorState.LOCAL_CONTRACT_VERIFIED
    assert receipt.external_connected is False
    assert receipt.accepted_revision_count == 1
    assert receipt.roundtrip_fidelity == 1.0
    assert receipt.same_contract_recheck_performed is True
    assert receipt.recheck_contract_id == contract.contract_id
    assert receipt.recheck_decision in {"PASS", "QUARANTINE", "RECAPTURE", "DEFER"}
    assert receipt.recheck_manifest_sha256
    assert receipt.recheck_gate_result_sha256
    assert receipt.original_input_unchanged is True
    assert receipt.closed_work_order_count == len(receipt.closed_work_order_ids)
    assert receipt.closed_work_order_count + len(receipt.unresolved_work_order_ids) == (
        receipt.eligible_work_order_count
    )
    assert (
        compute_batch_digest(paths["batch_root"], manifest, contract) == source_digest
    )
    assert (
        tmp_path / "roundtrip" / "rechecked_batch" / "recheck_gate_result.json"
    ).is_file()
    assert (tmp_path / "roundtrip" / f"{receipt.receipt_id}.receipt.json").is_file()
    assert (tmp_path / "roundtrip" / f"{receipt.receipt_id}.integrity.json").is_file()
    assert (tmp_path / "roundtrip" / "annotation_import.json").is_file()


def test_tampered_mapping_is_rejected_and_does_not_claim_recheck(
    tmp_path: Path,
) -> None:
    paths, manifest, contract, _result, record = _gate_fixture(tmp_path)
    revision = _valid_revision(record).model_copy(
        update={"source_image_sha256": "f" * 64}
    )
    package = AnnotationImportPackage(
        export_id=record.bundle.export_id,
        provider=record.bundle.provider,
        revisions=[revision],
    )

    receipt = import_revisions_and_recheck(
        export=record,
        package=package,
        batch_root=paths["batch_root"],
        manifest=manifest,
        contract=contract,
        scenario_profile=ScenarioProfile.GENERIC,
        output_root=tmp_path / "rejected" / "rechecked_batch",
    )

    assert receipt.accepted_revision_count == 0
    assert receipt.roundtrip_fidelity == 0.0
    assert receipt.same_contract_recheck_performed is False
    assert receipt.recheck_decision is None
    assert "source_image_sha256_mismatch" in receipt.checks[0].issues
    assert not (tmp_path / "rejected" / "rechecked_batch").exists()


def test_roundtrip_rejects_export_digest_tampering(tmp_path: Path) -> None:
    paths, manifest, contract, _result, record = _gate_fixture(tmp_path)
    package = AnnotationImportPackage(
        export_id=record.bundle.export_id,
        provider=record.bundle.provider,
        revisions=[_valid_revision(record)],
    )
    tampered_record = record.model_copy(update={"export_sha256": "f" * 64})

    with pytest.raises(ValueError, match="export hash"):
        import_revisions_and_recheck(
            export=tampered_record,
            package=package,
            batch_root=paths["batch_root"],
            manifest=manifest,
            contract=contract,
            scenario_profile=ScenarioProfile.GENERIC,
            output_root=tmp_path / "tampered-export" / "rechecked_batch",
        )


def test_roundtrip_rejects_source_drift_after_export(tmp_path: Path) -> None:
    paths, manifest, contract, _result, record = _gate_fixture(tmp_path)
    package = AnnotationImportPackage(
        export_id=record.bundle.export_id,
        provider=record.bundle.provider,
        revisions=[_valid_revision(record)],
    )
    image = paths["batch_root"] / manifest.samples[0].relative_path
    image.write_bytes(image.read_bytes() + b"drift")

    with pytest.raises(ValueError, match="source batch changed"):
        import_revisions_and_recheck(
            export=record,
            package=package,
            batch_root=paths["batch_root"],
            manifest=manifest,
            contract=contract,
            scenario_profile=ScenarioProfile.GENERIC,
            output_root=tmp_path / "drift" / "rechecked_batch",
        )


def test_roundtrip_rejects_rgb_image_as_segmentation_mask(tmp_path: Path) -> None:
    paths, manifest, contract, _result, record = _gate_fixture(tmp_path)
    revision = _valid_revision(record).model_copy(
        update={"annotation_content_base64": _mask_base64(mode="RGB")}
    )
    package = AnnotationImportPackage(
        export_id=record.bundle.export_id,
        provider=record.bundle.provider,
        revisions=[revision],
    )

    receipt = import_revisions_and_recheck(
        export=record,
        package=package,
        batch_root=paths["batch_root"],
        manifest=manifest,
        contract=contract,
        scenario_profile=ScenarioProfile.GENERIC,
        output_root=tmp_path / "rgb-mask" / "rechecked_batch",
    )

    assert receipt.accepted_revision_count == 0
    assert "annotation_mask_mode_invalid" in receipt.checks[0].issues


def test_roundtrip_output_must_be_outside_source_batch(tmp_path: Path) -> None:
    paths, manifest, contract, _result, record = _gate_fixture(tmp_path)
    package = AnnotationImportPackage(
        export_id=record.bundle.export_id,
        provider=record.bundle.provider,
        revisions=[_valid_revision(record)],
    )

    with pytest.raises(ValueError, match="outside the source batch"):
        import_revisions_and_recheck(
            export=record,
            package=package,
            batch_root=paths["batch_root"],
            manifest=manifest,
            contract=contract,
            scenario_profile=ScenarioProfile.GENERIC,
            output_root=paths["batch_root"] / "roundtrip-copy",
        )


class _FakeResponse:
    def __init__(self, payload: dict[str, Any]) -> None:
        self._raw = json.dumps(payload).encode("utf-8")

    def __enter__(self) -> _FakeResponse:
        return self

    def __exit__(self, *_args: object) -> None:
        return None

    def read(self, size: int = -1) -> bytes:
        return self._raw if size < 0 else self._raw[:size]


class _CvatProbeHTTPHandler(BaseHTTPRequestHandler):
    server: Any

    def log_message(self, *_args: object) -> None:
        return None

    def do_GET(self) -> None:
        self.server.requests.append(
            {
                "path": self.path,
                "authorization": self.headers.get("Authorization"),
            }
        )
        location = self.server.redirects.get(self.path)
        if location is not None:
            self.send_response(self.server.redirect_statuses.get(self.path, 302))
            self.send_header("Location", location)
            self.end_headers()
            return
        payload = self.server.responses.get(self.path, {"ok": True})
        raw = json.dumps(payload).encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(raw)))
        self.end_headers()
        self.wfile.write(raw)


@contextmanager
def _cvat_probe_server() -> Iterator[tuple[Any, str]]:
    server = ThreadingHTTPServer(("127.0.0.1", 0), _CvatProbeHTTPHandler)
    server.requests = []
    server.redirects = {}
    server.redirect_statuses = {}
    server.responses = {
        "/api/server/about": {"version": "2.40.0"},
        "/api/users/self": {"id": 7, "username": "reviewer"},
    }
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield server, f"http://127.0.0.1:{server.server_port}"
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)


def test_cvat_probe_is_read_only_and_records_connection(monkeypatch: Any) -> None:
    observed: list[dict[str, Any]] = []

    def _open_probe(request: Any, *, timeout_seconds: float) -> _FakeResponse:
        observed.append(
            {
                "method": request.get_method(),
                "url": request.full_url,
                "timeout": timeout_seconds,
                "authorization": request.get_header("Authorization"),
            }
        )
        if request.full_url.endswith("/api/users/self"):
            return _FakeResponse({"id": 7, "username": "reviewer"})
        return _FakeResponse({"version": "2.40.0"})

    monkeypatch.setattr(
        "visiondata_gate.annotation_roundtrip._open_cvat_probe_request",
        _open_probe,
    )

    receipt = probe_cvat_endpoint("http://127.0.0.1:8080", token="secret")

    assert receipt.connected is True
    assert receipt.authenticated is True
    assert receipt.response_sha256
    assert observed == [
        {
            "method": "GET",
            "url": "http://127.0.0.1:8080/api/server/about",
            "timeout": 5.0,
            "authorization": "Token secret",
        },
        {
            "method": "GET",
            "url": "http://127.0.0.1:8080/api/users/self",
            "timeout": 5.0,
            "authorization": "Token secret",
        },
    ]
    assert "secret" not in receipt.model_dump_json()


def test_cvat_probe_blocks_cross_origin_auth_redirect_without_leaking_token() -> None:
    with (
        _cvat_probe_server() as (target, target_root),
        _cvat_probe_server() as (
            source,
            source_root,
        ),
    ):
        target_url = target_root.replace("127.0.0.1", "localhost")
        source.redirects["/api/users/self"] = f"{target_url}/captured"

        receipt = probe_cvat_endpoint(source_root, token="secret")

    assert receipt.connected is True
    assert receipt.authenticated is False
    assert receipt.error_type == "authentication_probe_failed:HTTPError"
    assert [item["path"] for item in source.requests] == [
        "/api/server/about",
        "/api/users/self",
    ]
    assert all(item["authorization"] == "Token secret" for item in source.requests)
    assert target.requests == []
    assert "secret" not in receipt.model_dump_json()


@pytest.mark.parametrize("status_code", [301, 302, 303, 307, 308])
def test_cvat_probe_blocks_same_origin_redirect_at_first_hop(
    status_code: int,
) -> None:
    with _cvat_probe_server() as (server, root):
        server.redirects["/api/server/about"] = "/api/server/about-v2"
        server.redirect_statuses["/api/server/about"] = status_code
        server.responses["/api/server/about-v2"] = {"version": "2.41.0"}

        receipt = probe_cvat_endpoint(root)

    assert receipt.connected is False
    assert receipt.authenticated is False
    assert receipt.error_type == "HTTPError"
    assert [item["path"] for item in server.requests] == ["/api/server/about"]


def test_cvat_probe_blocks_redirect_loop_at_first_hop() -> None:
    with _cvat_probe_server() as (server, root):
        server.redirects["/api/server/about"] = "/api/server/about"

        receipt = probe_cvat_endpoint(root)

    assert receipt.connected is False
    assert receipt.error_type == "HTTPError"
    assert [item["path"] for item in server.requests] == ["/api/server/about"]


def test_cvat_probe_blocks_over_limit_redirect_chain_at_first_hop() -> None:
    with _cvat_probe_server() as (server, root):
        server.redirects["/api/server/about"] = "/redirect/1"
        for index in range(1, 20):
            server.redirects[f"/redirect/{index}"] = f"/redirect/{index + 1}"

        receipt = probe_cvat_endpoint(root)

    assert receipt.connected is False
    assert receipt.error_type == "HTTPError"
    assert [item["path"] for item in server.requests] == ["/api/server/about"]


def test_remote_cvat_probe_is_blocked_without_explicit_permission() -> None:
    with pytest.raises(PermissionError):
        probe_cvat_endpoint("https://cvat.example.invalid")


def test_fiftyone_library_presence_is_not_external_connection(
    monkeypatch: Any,
) -> None:
    monkeypatch.setitem(sys.modules, "fiftyone", SimpleNamespace(__version__="1.8.0"))

    receipt = probe_fiftyone_library()

    assert receipt.endpoint_scope == "local"
    assert receipt.server_version == "1.8.0"
    assert receipt.connected is False
    assert receipt.authenticated is False
    assert "not an external connection receipt" in receipt.boundary_notice
