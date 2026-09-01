from __future__ import annotations

import hashlib
import json
import threading
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import UTC, datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any

from visiondata_gate.demo_fixtures import build_fixture_industrial_incident_request
from visiondata_gate.governed_context import assemble_incident_context
from visiondata_gate.industrial_incident import build_industrial_incident_case
from visiondata_gate.industrial_incident_benchmark import _gate_context
from visiondata_gate.multimodal_advisor import (
    DEEPSEEK_API_HOST,
    DEEPSEEK_OPENAI_BASE_URL,
    DEFAULT_MULTIMODAL_ADVISOR_ENDPOINT,
    AdvisorImageInput,
    MultimodalAdvisorMode,
    MultimodalCaseAdvisor,
    MultimodalCaseAdvisorConfig,
    verify_multimodal_advisor_receipt,
)
from visiondata_gate.site_pack import load_factory_site_pack

SITE_PACK_ROOT = Path(__file__).parents[1] / "examples" / "site_packs"


def test_safe_defaults_target_declared_deepseek_base_without_authorizing_remote() -> (
    None
):
    config = MultimodalCaseAdvisorConfig()
    assert DEEPSEEK_OPENAI_BASE_URL == "https://api.deepseek.com"
    assert DEFAULT_MULTIMODAL_ADVISOR_ENDPOINT == (
        "https://api.deepseek.com/chat/completions"
    )
    assert config.remote_endpoint_hosts == [DEEPSEEK_API_HOST]
    assert config.mode is MultimodalAdvisorMode.OFF
    assert config.allow_remote_model is False
    assert config.allow_image_transmission is False


def _context():
    case = build_industrial_incident_case(
        build_fixture_industrial_incident_request(),
        _gate_context(),
    )
    pack = load_factory_site_pack(SITE_PACK_ROOT / "factory_a_line_01")
    return assemble_incident_context(
        case=case,
        site_pack=pack,
        memory_cards=[],
        as_of=datetime(2026, 8, 26, 10, 0, tzinfo=UTC),
        legacy_only=True,
    ).context


def _image(tmp_path: Path, *, authorized: bool) -> AdvisorImageInput:
    path = tmp_path / "roi.png"
    path.write_bytes(b"\x89PNG\r\n\x1a\nfixture-roi-evidence")
    digest = hashlib.sha256(path.read_bytes()).hexdigest()
    return AdvisorImageInput(
        evidence_id="image-roi-001",
        local_path=str(path),
        media_type="image/png",
        expected_sha256=digest,
        transmission_authorized=authorized,
        purpose="异常区域与同工位正常参考的受限视觉比较",
    )


def _proposal(context, *, worker: str | None = None) -> dict[str, Any]:
    hypothesis = context.current_hypotheses[0].hypothesis_id
    gap = context.current_evidence_gaps[0]
    chosen_worker = worker or (
        context.available_tools[0] if context.available_tools else None
    )
    workers = []
    if chosen_worker is not None:
        workers.append(
            {
                "worker_role": chosen_worker,
                "reason": "补充当前案件的可验证视觉证据。",
                "supporting_image_evidence_ids": ["image-roi-001"],
                "expected_output": "生成绑定当前案件的确定性 Worker Receipt。",
            }
        )
    return {
        "schema_version": "visiondata-gate.multimodal-case-proposal.v1",
        "visual_observations": [
            {
                "observation": "ROI 中存在局部高亮，但该观察不能建立根因。",
                "image_evidence_ids": ["image-roi-001"],
                "confidence": "MEDIUM",
                "qualification": "MODEL_SUGGESTION_ONLY",
            }
        ],
        "evidence_gaps": [
            {
                "evidence_ref": gap,
                "reason": "需要当前批次证据区分竞争假设。",
                "related_hypothesis_ids": [hypothesis],
            }
        ],
        "recommended_workers": workers,
        "operator_questions": [
            {
                "question": "能否提供同产品同相机的当前正常参考？",
                "expected_evidence_ref": gap,
                "related_hypothesis_ids": [hypothesis],
            }
        ],
        "delivery_summary": "模型只观察到局部高亮，建议继续补证，不能据此认定根因。",
        "summary_evidence_ids": ["image-roi-001"],
        "current_case_fact_authority": "none",
        "decision_authority": "none",
        "root_cause_claimed": False,
        "capa_approval_claimed": False,
        "production_release_recommended": False,
        "equipment_control_requested": False,
    }


class _Handler(BaseHTTPRequestHandler):
    server: Any

    def log_message(self, *_args: object) -> None:
        return None

    def do_POST(self) -> None:
        length = int(self.headers["Content-Length"])
        request = json.loads(self.rfile.read(length))
        self.server.request_seen = request
        self.server.authorization_seen = self.headers.get("Authorization")
        text_contract = json.loads(request["messages"][1]["content"][0]["text"])
        context = self.server.context
        proposal = _proposal(context)
        if self.server.mutate is not None:
            self.server.mutate(proposal)
        payload = {
            "model": "deepseek-v4-flash-vision-exp",
            "usage": {
                "prompt_tokens": 150,
                "completion_tokens": 90,
                "total_tokens": 240,
            },
            "choices": [{"message": {"content": json.dumps(proposal)}}],
        }
        assert text_contract["advisor_contract"]["context_sha256"] == (
            context.context_sha256
        )
        raw = json.dumps(payload).encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(raw)))
        self.end_headers()
        self.wfile.write(raw)


@contextmanager
def _server(context, *, mutate=None) -> Iterator[tuple[ThreadingHTTPServer, str]]:
    server = ThreadingHTTPServer(("127.0.0.1", 0), _Handler)
    server.context = context
    server.mutate = mutate
    server.request_seen = None
    server.authorization_seen = None
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield server, f"http://127.0.0.1:{server.server_port}/v1/chat/completions"
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)


def test_off_mode_binds_images_without_call_or_transmission(tmp_path: Path) -> None:
    advisor = MultimodalCaseAdvisor(
        MultimodalCaseAdvisorConfig(mode=MultimodalAdvisorMode.OFF)
    )
    result = advisor.advise(
        context=_context(),
        images=[_image(tmp_path, authorized=False)],
    )

    verify_multimodal_advisor_receipt(result.receipt)
    assert result.receipt.status == "DISABLED"
    assert result.receipt.model_call_count == 0
    assert result.receipt.transmitted_image_count == 0
    assert result.receipt.image_evidence[0].local_path_retained is False
    assert result.validated_worker_order == ()


def test_replay_mode_accepts_only_context_bound_allowlisted_proposal(
    tmp_path: Path,
) -> None:
    context = _context()
    replay = tmp_path / "advisor-replay.json"
    replay.write_text(json.dumps(_proposal(context)), encoding="utf-8")
    advisor = MultimodalCaseAdvisor(
        MultimodalCaseAdvisorConfig(
            mode=MultimodalAdvisorMode.REPLAY,
            replay_path=str(replay),
        )
    )
    result = advisor.advise(
        context=context,
        images=[_image(tmp_path, authorized=False)],
    )

    verify_multimodal_advisor_receipt(result.receipt)
    assert result.receipt.status == "ACCEPTED"
    assert result.receipt.connection_status == "REPLAY_ONLY"
    assert result.receipt.model_call_count == 0
    assert result.receipt.transmitted_image_count == 0
    assert result.receipt.proposal is not None
    assert result.receipt.proposal.root_cause_claimed is False


def test_gated_local_contract_transmits_only_explicitly_authorized_image(
    tmp_path: Path,
) -> None:
    context = _context()
    with _server(context) as (server, endpoint):
        advisor = MultimodalCaseAdvisor(
            MultimodalCaseAdvisorConfig(
                mode=MultimodalAdvisorMode.GATED,
                endpoint=endpoint,
                allow_image_transmission=True,
            ),
            api_key="fixture-secret",
        )
        result = advisor.advise(
            context=context,
            images=[_image(tmp_path, authorized=True)],
        )

    verify_multimodal_advisor_receipt(result.receipt)
    assert result.receipt.status == "ACCEPTED"
    assert result.receipt.connection_status == "CONTRACT_CONNECTED_LOCAL_TEST"
    assert result.receipt.model_call_count == 1
    assert result.receipt.transmitted_image_count == 1
    assert result.receipt.usage.total_tokens == 240
    assert server.authorization_seen == "Bearer fixture-secret"
    content = server.request_seen["messages"][1]["content"]
    assert [item["type"] for item in content] == ["text", "image_url"]
    assert content[1]["image_url"]["url"].startswith("data:image/png;base64,")
    assert "fixture-secret" not in result.receipt.model_dump_json()


def test_gated_mode_fails_closed_before_network_without_image_authority(
    tmp_path: Path,
) -> None:
    context = _context()
    with _server(context) as (server, endpoint):
        advisor = MultimodalCaseAdvisor(
            MultimodalCaseAdvisorConfig(
                mode=MultimodalAdvisorMode.GATED,
                endpoint=endpoint,
                allow_image_transmission=True,
            )
        )
        result = advisor.advise(
            context=context,
            images=[_image(tmp_path, authorized=False)],
        )

    assert result.receipt.status == "REJECTED"
    assert result.receipt.validation_errors == ["IMAGE_TRANSMISSION_NOT_AUTHORIZED"]
    assert result.receipt.model_call_count == 0
    assert result.receipt.transmitted_image_count == 0
    assert server.request_seen is None


def test_unknown_image_reference_rejects_entire_advice(tmp_path: Path) -> None:
    context = _context()

    def mutate(proposal: dict[str, Any]) -> None:
        proposal["summary_evidence_ids"] = ["invented-image"]

    with _server(context, mutate=mutate) as (_server_instance, endpoint):
        advisor = MultimodalCaseAdvisor(
            MultimodalCaseAdvisorConfig(
                mode=MultimodalAdvisorMode.GATED,
                endpoint=endpoint,
                allow_image_transmission=True,
            )
        )
        result = advisor.advise(
            context=context,
            images=[_image(tmp_path, authorized=True)],
        )

    assert result.receipt.status == "REJECTED"
    assert "UNKNOWN_IMAGE_EVIDENCE_ID" in result.receipt.validation_errors
    assert result.receipt.proposal is None
    assert result.validated_worker_order == ()
