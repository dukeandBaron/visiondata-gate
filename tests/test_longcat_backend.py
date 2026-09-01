from __future__ import annotations

from contextlib import contextmanager
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import threading
from typing import Any, Iterator

from visiondata_gate.contracts import EvidenceStatus, Finding, Severity
from visiondata_gate.model_backends import build_council_with_backend
from visiondata_gate.runtime_models import ModelBackendKind, RuntimeConfig


class _LongCatHandler(BaseHTTPRequestHandler):
    server: Any

    def log_message(self, *_args: object) -> None:
        return None

    def _json(self, payload: dict[str, Any]) -> None:
        raw = json.dumps(payload).encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(raw)))
        self.end_headers()
        self.wfile.write(raw)

    def do_GET(self) -> None:
        self.server.get_count += 1
        self._json({"object": "list", "data": [{"id": self.server.model_id}]})

    def do_POST(self) -> None:
        self.server.post_count += 1
        length = int(self.headers["Content-Length"])
        request = json.loads(self.rfile.read(length))
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
            "challenge": "What additional evidence is required?",
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


@contextmanager
def _server(model_id: str) -> Iterator[tuple[ThreadingHTTPServer, str]]:
    server = ThreadingHTTPServer(("127.0.0.1", 0), _LongCatHandler)
    server.model_id = model_id
    server.get_count = 0
    server.post_count = 0
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield server, f"http://127.0.0.1:{server.server_port}/v1/chat/completions"
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)


def _finding() -> Finding:
    return Finding(
        finding_id="longcat-fixture",
        code="MISSING_ANNOTATION",
        severity=Severity.HIGH,
        tool="annotation_integrity",
        sample_ids=["sample-a"],
        summary="Required annotation is missing.",
        evidence={"reason": "missing_file"},
        evidence_status=EvidenceStatus.VERIFIED,
        recommended_action="relabel",
    )


def test_longcat_profile_probes_model_identity_before_chat() -> None:
    model = "meituan-longcat/LongCat-Flash-Chat"
    with _server(model) as (server, endpoint):
        built = build_council_with_backend(
            RuntimeConfig(
                backend=ModelBackendKind.LONGCAT_OPENAI_COMPATIBLE,
                endpoint=endpoint,
                model=model,
                max_model_calls=1,
                model_timeout_seconds=2.0,
            ),
            [_finding()],
            [],
            {"finding_count": 1},
            [],
        )

    assert built.backend_connected is True
    assert built.model_calls == 1
    assert built.backend_identity_receipt is not None
    assert built.backend_identity_receipt.status == "CONTRACT_CONNECTED_LOCAL_TEST"
    assert built.backend_identity_receipt.configured_model_reported is True
    assert built.backend_identity_receipt.model_response_accepted is True
    assert len(built.transport_receipts) == 2
    assert server.get_count == 1
    assert server.post_count == 1


def test_longcat_model_identity_mismatch_fails_before_chat() -> None:
    with _server("different-model") as (server, endpoint):
        built = build_council_with_backend(
            RuntimeConfig(
                backend=ModelBackendKind.LONGCAT_OPENAI_COMPATIBLE,
                endpoint=endpoint,
                model="meituan-longcat/LongCat-Flash-Chat",
                max_model_calls=1,
                model_timeout_seconds=2.0,
            ),
            [_finding()],
            [],
            {"finding_count": 1},
            [],
        )

    assert built.backend_connected is False
    assert built.model_calls == 0
    assert built.fallback_used is True
    assert built.backend_identity_receipt is not None
    assert built.backend_identity_receipt.status == "REAL_BACKEND_NOT_CONNECTED"
    assert server.get_count == 1
    assert server.post_count == 0
