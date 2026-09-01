"""Local protocol evaluation for LongCat, VGGT, and OmniVGGT connectors."""

from __future__ import annotations

from contextlib import contextmanager
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
from pathlib import Path
import tempfile
import threading
from typing import Any, Iterator

from PIL import Image

from .contracts import (
    BatchContract,
    BatchManifest,
    CoverageContract,
    EvidenceStatus,
    Finding,
    SampleRecord,
    Severity,
)
from .evidence import canonical_json_bytes, sha256_bytes
from .geometry_backends import GeometryBackendConfig, run_http_geometry_backend
from .model_backends import build_council_with_backend
from .runtime_models import ModelBackendKind, RuntimeConfig


_LONGCAT_MODEL = "meituan-longcat/LongCat-Flash-Chat"


class _BackendHandler(BaseHTTPRequestHandler):
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
        self.server.counts[self.path] = self.server.counts.get(self.path, 0) + 1
        if self.path == "/longcat/v1/models":
            self._json({"object": "list", "data": [{"id": _LONGCAT_MODEL}]})
            return
        backend = "omnivggt" if self.path.startswith("/omnivggt/") else "vggt"
        self._json(
            {
                "schema_version": "visiondata-gate.geometry-backend-info.v1",
                "backend": backend,
                "backend_version": "contract-eval-v1",
                "checkpoint_sha256": "d" * 64,
                "ready": True,
                "output_schema": "visiondata-gate.geometry-evidence.v1",
            }
        )

    def do_POST(self) -> None:
        self.server.counts[self.path] = self.server.counts.get(self.path, 0) + 1
        length = int(self.headers["Content-Length"])
        request = json.loads(self.rfile.read(length))
        if self.path == "/longcat/v1/chat/completions":
            envelope = json.loads(request["messages"][1]["content"])
            fact = envelope["untrusted_evidence_facts"][0]
            content = {
                "schema_version": "visiondata-gate.model-advisory.v1",
                "decision_authority": "none",
                "claims": [
                    {
                        "kind": "observation",
                        "statement": fact["text"],
                        "citations": [
                            {
                                "evidence_ref": fact["ref"],
                                "evidence_span": fact["text"],
                            }
                        ],
                    }
                ],
                "challenge": "What evidence remains missing?",
                "advisory_recommendation": "DEFER",
                "confidence_axes": {
                    "E": "high",
                    "T": "medium",
                    "A": "medium",
                    "M": "low",
                },
                "limitations": ["Advisory only."],
            }
            self._json({"choices": [{"message": {"content": json.dumps(content)}}]})
            return

        backend = "omnivggt" if self.path.startswith("/omnivggt/") else "vggt"
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
                    "backend": backend,
                    "backend_version": "contract-eval-v1",
                    "input_batch_sha256": request["input_batch_sha256"],
                    "image_count": len(views),
                    "views": views,
                    "checkpoint_sha256": "d" * 64,
                    "output_format": "normalized-json-v1",
                }
            }
        )


@contextmanager
def _server() -> Iterator[tuple[ThreadingHTTPServer, str]]:
    server = ThreadingHTTPServer(("127.0.0.1", 0), _BackendHandler)
    server.counts = {}
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield server, f"http://127.0.0.1:{server.server_port}"
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)


def _fixture(root: Path) -> tuple[Path, BatchManifest, BatchContract]:
    batch = root / "batch"
    batch.mkdir()
    samples: list[SampleRecord] = []
    for index in range(2):
        relative = f"images/view-{index}.png"
        path = batch / relative
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
    manifest = BatchManifest(batch_id="backend-contract-eval", seed=17, samples=samples)
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
    return batch, manifest, contract


def _finding() -> Finding:
    return Finding(
        finding_id="backend-contract-finding",
        code="MISSING_ANNOTATION",
        severity=Severity.HIGH,
        tool="annotation_integrity",
        sample_ids=["sample-0"],
        summary="Required annotation is missing.",
        evidence={"reason": "missing_file"},
        evidence_status=EvidenceStatus.VERIFIED,
        recommended_action="relabel",
    )


def build_backend_contract_evaluation_receipt() -> dict[str, Any]:
    """Run three local protocol fixtures while preserving real-backend status."""

    cases: list[dict[str, Any]] = []
    with tempfile.TemporaryDirectory(prefix="vdg-backend-contract-") as temporary:
        batch, manifest, contract = _fixture(Path(temporary))
        with _server() as (server, root):
            longcat = build_council_with_backend(
                RuntimeConfig(
                    backend=ModelBackendKind.LONGCAT_OPENAI_COMPATIBLE,
                    endpoint=f"{root}/longcat/v1/chat/completions",
                    model=_LONGCAT_MODEL,
                    max_model_calls=1,
                    model_timeout_seconds=2.0,
                ),
                [_finding()],
                [],
                {"finding_count": 1},
                [],
            )
            longcat_identity = longcat.backend_identity_receipt
            longcat_passed = bool(
                longcat.backend_connected
                and longcat_identity is not None
                and longcat_identity.status == "CONTRACT_CONNECTED_LOCAL_TEST"
                and longcat_identity.configured_model_reported
                and longcat_identity.model_response_accepted
            )
            cases.append(
                {
                    "case_id": "longcat-openai-compatible",
                    "expected": "CONTRACT_CONNECTED_LOCAL_TEST",
                    "observed": (
                        longcat_identity.status
                        if longcat_identity
                        else "MISSING_RECEIPT"
                    ),
                    "passed": longcat_passed,
                    "identity_receipt": (
                        longcat_identity.model_dump(mode="json")
                        if longcat_identity
                        else None
                    ),
                    "transport_receipts": [
                        item.model_dump(mode="json")
                        for item in longcat.transport_receipts
                    ],
                }
            )

            for backend in ("vggt", "omnivggt"):
                connected = run_http_geometry_backend(
                    GeometryBackendConfig(
                        backend=backend,
                        endpoint=f"{root}/{backend}",
                    ),
                    batch,
                    manifest,
                    contract,
                )
                cases.append(
                    {
                        "case_id": f"{backend}-normalized-geometry-http",
                        "expected": "CONTRACT_CONNECTED_LOCAL_TEST",
                        "observed": connected.receipt.status,
                        "passed": (
                            connected.receipt.status == "CONTRACT_CONNECTED_LOCAL_TEST"
                            and connected.evidence is not None
                            and connected.receipt.checkpoint_hash_match
                        ),
                        "connection_receipt": connected.receipt.model_dump(mode="json"),
                    }
                )

            request_counts = dict(sorted(server.counts.items()))

    denominator = len(cases)
    passed_count = sum(bool(item["passed"]) for item in cases)
    return {
        "schema_version": "visiondata-gate.backend-contract-evaluation.v1",
        "status": (
            "PASS_LOCAL_CONTRACTS_ONLY" if passed_count == denominator else "FAIL_LOCAL"
        ),
        "fixed_denominator": denominator,
        "contract_connected_count": passed_count,
        "contract_connection_rate": passed_count / denominator,
        "real_backend_connected_count": 0,
        "real_backend_status": "REAL_BACKEND_NOT_CONNECTED",
        "cases": cases,
        "request_counts": request_counts,
        "case_set_sha256": sha256_bytes(
            canonical_json_bytes(
                [
                    {"case_id": item["case_id"], "expected": item["expected"]}
                    for item in cases
                ]
            )
        ),
        "boundary_notice": (
            "All three adapters used local protocol fixtures. No LongCat weights, VGGT "
            "checkpoint, OmniVGGT checkpoint, GPU job, paid API, or external service was run."
        ),
    }


__all__ = ["build_backend_contract_evaluation_receipt"]
