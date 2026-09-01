from __future__ import annotations

import json
import hashlib
from typing import Any

from visiondata_gate.contracts import (
    EvidenceStatus,
    Finding,
    Severity,
    ToolTrace,
)
from visiondata_gate.grounding import (
    build_evidence_fact_index,
    validate_model_advisory,
)
from visiondata_gate.model_backends import build_council_with_backend
from visiondata_gate.network_resilience import HTTPExchangeReceipt, HTTPJSONResult
from visiondata_gate.runtime_models import ModelBackendKind, RuntimeConfig


def _evidence() -> tuple[list[Finding], list[ToolTrace], dict[str, int]]:
    finding = Finding(
        finding_id="finding-demo",
        code="MISSING_ANNOTATION",
        severity=Severity.HIGH,
        tool="annotation_integrity",
        sample_ids=["sample-a"],
        summary="Required annotation is missing for sample-a.",
        evidence={"reason": "missing_file"},
        evidence_status=EvidenceStatus.VERIFIED,
        recommended_action="relabel",
    )
    trace = ToolTrace(
        sequence=3,
        tool="annotation_integrity",
        status="ok",
        input_sha256="a" * 64,
        result_sha256="b" * 64,
        finding_ids=[finding.finding_id],
    )
    return [finding], [trace], {"sample_count": 1, "finding_count": 1}


def _payload(ref: str, span: str, statement: str) -> dict[str, Any]:
    return {
        "schema_version": "visiondata-gate.model-advisory.v1",
        "decision_authority": "none",
        "claims": [
            {
                "kind": "observation",
                "statement": statement,
                "citations": [{"evidence_ref": ref, "evidence_span": span}],
            }
        ],
        "challenge": "Should the missing annotation be relabelled and rechecked?",
        "advisory_recommendation": "QUARANTINE",
        "confidence_axes": {
            "E": "high",
            "T": "high",
            "A": "medium",
            "M": "low",
        },
        "limitations": ["Advisory only."],
    }


def test_grounding_accepts_existing_ref_exact_span_and_supported_number() -> None:
    findings, traces, metrics = _evidence()
    _, lookup = build_evidence_fact_index(findings, traces, metrics, [])
    fact = lookup["metric:sample_count"]

    response, receipt = validate_model_advisory(
        _payload(
            "metric:sample_count",
            fact.text,
            "sample_count has value 1.",
        ),
        role_id="ai_data_contract",
        allowed_refs=["metric:sample_count"],
        fact_lookup=lookup,
    )

    assert response is not None
    assert receipt.status == "accepted"
    assert receipt.output_accepted is True
    assert receipt.valid_citation_count == 1
    assert receipt.unsupported_claim_count == 0


def test_grounding_rejects_unknown_reference_and_nonexistent_span() -> None:
    findings, traces, metrics = _evidence()
    _, lookup = build_evidence_fact_index(findings, traces, metrics, [])

    response, receipt = validate_model_advisory(
        _payload("finding:invented", "invented source", "invented source failed"),
        role_id="ai_red_team_auditor",
        allowed_refs=["finding:finding-demo"],
        fact_lookup=lookup,
    )

    assert response is None
    assert receipt.status == "grounding_rejected"
    assert receipt.checks[0].invalid_refs == ["finding:invented"]


def test_grounding_rejects_numeric_tampering_even_with_real_citation() -> None:
    findings, traces, metrics = _evidence()
    _, lookup = build_evidence_fact_index(findings, traces, metrics, [])
    fact = lookup["metric:sample_count"]

    response, receipt = validate_model_advisory(
        _payload(
            "metric:sample_count",
            fact.text,
            "sample_count has value 999.",
        ),
        role_id="ai_data_contract",
        allowed_refs=["metric:sample_count"],
        fact_lookup=lookup,
    )

    assert response is None
    assert receipt.checks[0].unsupported_numeric_literals == ["999"]
    assert "numeric_literal_not_in_cited_span" in receipt.checks[0].issues


def test_grounding_rejects_production_authority_claim() -> None:
    findings, traces, metrics = _evidence()
    _, lookup = build_evidence_fact_index(findings, traces, metrics, [])
    fact = lookup["finding:finding-demo"]

    response, receipt = validate_model_advisory(
        _payload(
            "finding:finding-demo",
            fact.text,
            "The missing annotation means this batch is production ready.",
        ),
        role_id="ai_repair_safety",
        allowed_refs=["finding:finding-demo"],
        fact_lookup=lookup,
    )

    assert response is None
    assert "unsupported_production_or_acceptance_authority" in receipt.checks[0].issues


def test_grounding_rejects_extra_decision_field_at_schema_boundary() -> None:
    findings, traces, metrics = _evidence()
    _, lookup = build_evidence_fact_index(findings, traces, metrics, [])
    fact = lookup["finding:finding-demo"]
    payload = _payload(
        "finding:finding-demo",
        fact.text,
        "MISSING_ANNOTATION is reported for sample-a.",
    )
    payload["final_decision"] = "PASS"

    response, receipt = validate_model_advisory(
        payload,
        role_id="ai_data_contract",
        allowed_refs=["finding:finding-demo"],
        fact_lookup=lookup,
    )

    assert response is None
    assert receipt.status == "schema_rejected"
    assert receipt.schema_valid is False


def _http_result(payload: dict[str, Any]) -> HTTPJSONResult:
    raw = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    return HTTPJSONResult(
        payload=payload,
        receipt=HTTPExchangeReceipt(
            request_id="a" * 32,
            endpoint_id="http://127.0.0.1:11434/v1/chat/completions",
            endpoint_scope="local",
            method="POST",
            status="SUCCESS",
            request_sha256="b" * 64,
            response_sha256=hashlib.sha256(raw).hexdigest(),
            attempts=[],
            attempt_count=0,
            retry_count=0,
            circuit_before="closed",
            circuit_after="closed",
        ),
        raw_bytes=raw,
    )


def test_local_openai_adapter_records_transport_and_grounding_receipt(
    monkeypatch: Any,
) -> None:
    findings, traces, metrics = _evidence()
    _, lookup = build_evidence_fact_index(findings, traces, metrics, [])
    fact = lookup["metric:sample_count"]
    content = _payload(
        "metric:sample_count",
        fact.text,
        "sample_count has value 1.",
    )
    monkeypatch.setattr(
        "visiondata_gate.network_resilience.ResilientJSONClient.request_json",
        lambda *_args, **_kwargs: _http_result(
            {"choices": [{"message": {"content": json.dumps(content)}}]}
        ),
    )
    config = RuntimeConfig(
        backend=ModelBackendKind.OPENAI_COMPATIBLE,
        endpoint="http://127.0.0.1:11434/v1/chat/completions",
        model="local-test-model",
        max_model_calls=1,
    )

    built = build_council_with_backend(config, findings, traces, metrics, [])

    assert built.model_calls == 1
    assert built.backend_connected is True
    assert built.grounding_receipt is not None
    assert built.grounding_receipt.connected is True
    assert built.grounding_receipt.accepted_output_count == 1
    assert built.grounding_receipt.citation_validity == 1.0


def test_remote_model_without_explicit_key_is_not_called(monkeypatch: Any) -> None:
    called = False

    def _unexpected(*_args: object, **_kwargs: object) -> None:
        nonlocal called
        called = True

    monkeypatch.setattr(
        "visiondata_gate.network_resilience.ResilientJSONClient.request_json",
        _unexpected,
    )
    config = RuntimeConfig(
        backend=ModelBackendKind.OPENAI_COMPATIBLE,
        endpoint="https://example.invalid/v1/chat/completions",
        model="remote-test-model",
        allow_remote_model=True,
    )

    built = build_council_with_backend(config, [], [], {}, [], api_key=None)

    assert called is False
    assert built.model_calls == 0
    assert built.backend_connected is False
    assert built.grounding_receipt is not None
    assert built.grounding_receipt.connected is False


def test_grounding_rejects_incomplete_confidence_axes() -> None:
    findings, traces, metrics = _evidence()
    _, lookup = build_evidence_fact_index(findings, traces, metrics, [])
    fact = lookup["metric:sample_count"]
    payload = _payload(
        "metric:sample_count",
        fact.text,
        "sample_count has value 1.",
    )
    payload["confidence_axes"].pop("M")

    response, receipt = validate_model_advisory(
        payload,
        role_id="ai_data_contract",
        allowed_refs=["metric:sample_count"],
        fact_lookup=lookup,
    )

    assert response is None
    assert receipt.status == "schema_rejected"


def test_grounding_rejects_authority_claim_hidden_in_challenge() -> None:
    findings, traces, metrics = _evidence()
    _, lookup = build_evidence_fact_index(findings, traces, metrics, [])
    fact = lookup["metric:sample_count"]
    payload = _payload(
        "metric:sample_count",
        fact.text,
        "sample_count has value 1.",
    )
    payload["challenge"] = "This batch is approved for production."

    response, receipt = validate_model_advisory(
        payload,
        role_id="ai_data_contract",
        allowed_refs=["metric:sample_count"],
        fact_lookup=lookup,
    )

    assert response is None
    assert receipt.status == "schema_rejected"
