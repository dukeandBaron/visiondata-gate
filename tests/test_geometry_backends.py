from __future__ import annotations

from contextlib import contextmanager
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
from pathlib import Path
import threading
from typing import Any, Iterator

from PIL import Image
import pytest

from visiondata_gate.contracts import (
    BatchContract,
    BatchManifest,
    CoverageContract,
    SampleRecord,
)
from visiondata_gate.geometry_backends import (
    GeometryBackendConfig,
    run_http_geometry_backend,
    run_local_geometry_runner,
)
from visiondata_gate.geometry_consistency import (
    GeometryEvidenceBundle,
    run_geometry_consistency,
)
from visiondata_gate.pipeline import compute_batch_digest


def _fixture(tmp_path: Path) -> tuple[Path, BatchManifest, BatchContract, str]:
    root = tmp_path / "batch"
    root.mkdir()
    samples = []
    for index in range(2):
        relative = f"images/view-{index}.png"
        path = root / relative
        path.parent.mkdir(exist_ok=True)
        Image.new("RGB", (64, 64), color=(80 + index, 100, 120)).save(path)
        samples.append(
            SampleRecord(
                sample_id=f"sample-{index}",
                relative_path=relative,
                split="train",
                category="part",
                view="front",
                condition="bright",
            )
        )
    manifest = BatchManifest(batch_id="geometry-backend", seed=9, samples=samples)
    contract = BatchContract(
        required_splits=["train"],
        annotations_required=False,
        coverage=CoverageContract(
            categories=["part"],
            views=["front"],
            conditions=["bright"],
            splits=["train"],
        ),
    )
    return root, manifest, contract, compute_batch_digest(root, manifest, contract)


class _GeometryHandler(BaseHTTPRequestHandler):
    server: Any

    def log_message(self, *_args: object) -> None:
        return None

    def _json(self, payload: dict[str, Any], status: int = 200) -> None:
        raw = json.dumps(payload).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(raw)))
        self.end_headers()
        self.wfile.write(raw)

    def do_GET(self) -> None:
        self._json(
            {
                "schema_version": "visiondata-gate.geometry-backend-info.v1",
                "backend": self.server.backend,
                "backend_version": "contract-fixture-v1",
                "checkpoint_sha256": "d" * 64,
                "ready": True,
                "output_schema": "visiondata-gate.geometry-evidence.v1",
            }
        )

    def do_POST(self) -> None:
        length = int(self.headers["Content-Length"])
        request = json.loads(self.rfile.read(length))
        views = [
            {
                "sample_id": item["sample_id"],
                "width": 64,
                "height": 64,
                "depth_width": 64,
                "depth_height": 64,
                "depth_valid_fraction": 0.96,
                "depth_outlier_fraction": 0.01,
                "depth_confidence_mean": 0.85,
                "reprojection_error_px": 1.0,
                "track_count": 20,
                "track_visibility_fraction": 0.8,
            }
            for item in request["images"]
        ]
        self._json(
            {
                "evidence": {
                    "schema_version": "visiondata-gate.geometry-evidence.v1",
                    "backend": self.server.backend,
                    "backend_version": "contract-fixture-v1",
                    "input_batch_sha256": request["input_batch_sha256"],
                    "image_count": len(views),
                    "views": views,
                    "checkpoint_sha256": "d" * 64,
                    "output_format": "normalized-json-v1",
                }
            }
        )


@contextmanager
def _server(backend: str) -> Iterator[str]:
    server = ThreadingHTTPServer(("127.0.0.1", 0), _GeometryHandler)
    server.backend = backend
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{server.server_port}/geometry"
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)


@pytest.mark.parametrize("backend", ["vggt", "omnivggt"])
def test_http_geometry_contract_connects_and_feeds_existing_gate(
    tmp_path: Path, backend: str
) -> None:
    root, manifest, contract, _ = _fixture(tmp_path)
    with _server(backend) as endpoint:
        connected = run_http_geometry_backend(
            GeometryBackendConfig(backend=backend, endpoint=endpoint),
            root,
            manifest,
            contract,
        )

    assert connected.receipt.status == "CONTRACT_CONNECTED_LOCAL_TEST"
    assert connected.receipt.endpoint_scope == "local"
    assert connected.receipt.checkpoint_hash_match is True
    assert len(connected.receipt.transport_receipts) == 2
    assert connected.evidence is not None
    checked = run_geometry_consistency(root, manifest, contract, connected.evidence)
    assert checked.status == "PASS_LOCAL"


def test_real_http_geometry_requires_matching_expected_checkpoint(
    tmp_path: Path,
) -> None:
    root, manifest, contract, _ = _fixture(tmp_path)
    with _server("vggt") as endpoint:
        connected = run_http_geometry_backend(
            GeometryBackendConfig(
                backend="vggt",
                endpoint=endpoint,
                execution_mode="real",
                expected_checkpoint_sha256="e" * 64,
            ),
            root,
            manifest,
            contract,
        )

    assert connected.evidence is None
    assert connected.receipt.status == "REAL_BACKEND_NOT_CONNECTED"
    assert connected.receipt.error_type == "ValueError"


def test_trusted_local_callable_binds_checkpoint_and_input_hash(tmp_path: Path) -> None:
    root, manifest, contract, batch_sha256 = _fixture(tmp_path)
    checkpoint = tmp_path / "checkpoint.bin"
    checkpoint.write_bytes(b"contract-test-checkpoint")

    def runner(
        _root: Path,
        _manifest: BatchManifest,
        _contract: BatchContract,
        observed_batch_sha256: str,
        checkpoint_sha256: str,
    ) -> GeometryEvidenceBundle:
        assert observed_batch_sha256 == batch_sha256
        return GeometryEvidenceBundle(
            backend="vggt",
            backend_version="callable-fixture-v1",
            input_batch_sha256=observed_batch_sha256,
            image_count=2,
            checkpoint_sha256=checkpoint_sha256,
            views=[
                {
                    "sample_id": f"sample-{index}",
                    "width": 64,
                    "height": 64,
                    "depth_width": 64,
                    "depth_height": 64,
                    "depth_valid_fraction": 0.95,
                    "depth_outlier_fraction": 0.01,
                    "depth_confidence_mean": 0.8,
                    "reprojection_error_px": 1.0,
                    "track_count": 20,
                    "track_visibility_fraction": 0.8,
                }
                for index in range(2)
            ],
        )

    connected = run_local_geometry_runner(
        runner,
        backend="vggt",
        backend_version="callable-fixture-v1",
        checkpoint_path=checkpoint,
        batch_root=root,
        manifest=manifest,
        contract=contract,
    )

    assert connected.receipt.status == "CONTRACT_CONNECTED_LOCAL_TEST"
    assert connected.receipt.connector_type == "local_callable"
    assert connected.receipt.checkpoint_hash_match is True
    assert connected.evidence is not None
