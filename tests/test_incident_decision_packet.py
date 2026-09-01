from __future__ import annotations

import io
import hashlib
import json
import zipfile
from datetime import UTC, datetime
from pathlib import Path

import pytest

from visiondata_gate.demo_fixtures import build_fixture_industrial_incident_request
from visiondata_gate.evidence import canonical_json_bytes
from visiondata_gate.governed_context import assemble_incident_context
from visiondata_gate.incident_control_plane import build_incident_control_plane
from visiondata_gate.incident_decision_packet import (
    IndustrialQualityDecisionPacketV1,
    IndustrialQualityDecisionPacketV3,
    build_decision_packet_exports,
    build_industrial_quality_decision_packet,
    verify_industrial_quality_decision_packet,
    write_decision_packet_exports,
)
from visiondata_gate.industrial_incident import (
    build_industrial_incident_case,
    parse_industrial_incident_case,
)
from visiondata_gate.industrial_incident_benchmark import _gate_context
from visiondata_gate.site_pack import load_factory_site_pack
from visiondata_gate.worker_selection import (
    AgentBehaviorReceiptV1,
    verify_agent_behavior_receipt,
)

SITE_PACK_ROOT = Path(__file__).parents[1] / "examples" / "site_packs"


def _packet(*, owner: str = "quality-manager-01"):
    case = build_industrial_incident_case(
        build_fixture_industrial_incident_request(),
        _gate_context(),
    )
    control_plane = build_incident_control_plane(case)
    site_pack = load_factory_site_pack(SITE_PACK_ROOT / "factory_a_line_01")
    assembled = assemble_incident_context(
        case=case,
        site_pack=site_pack,
        memory_cards=[],
        as_of=datetime(2026, 8, 26, 11, 0, tzinfo=UTC),
        legacy_only=True,
    )
    packet = build_industrial_quality_decision_packet(
        case,
        control_plane=control_plane,
        named_quality_owner_id=owner,
        named_quality_owner_role="QualityManager",
        site_pack=site_pack,
        context_receipt=assembled.receipt,
    )
    return case, control_plane, packet


def test_decision_packet_preserves_disposition_and_delivers_named_actions() -> None:
    case, control_plane, packet = _packet()

    verify_industrial_quality_decision_packet(
        packet,
        case=case,
        control_plane=control_plane,
    )
    assert packet.disposition == case.status.value
    assert isinstance(packet, IndustrialQualityDecisionPacketV3)
    assert packet.schema_version == (
        "visiondata-gate.industrial-quality-decision-packet.v3"
    )
    assert packet.planning_belief_ledger == case.planning_belief_ledger
    assert packet.worker_selection_receipt == case.worker_selection_receipt
    assert packet.recommendation == case.recommendation.value
    assert packet.root_cause_status == "NOT_ESTABLISHED"
    assert packet.named_quality_owner_id == "quality-manager-01"
    assert len(packet.competing_hypotheses) == 6
    assert packet.action_contracts
    assert all(item.accountable_owner_id for item in packet.action_contracts)
    assert all(item.source_evidence_refs for item in packet.action_contracts)
    assert all(
        item.machine_action_permitted is False for item in packet.action_contracts
    )
    assert packet.production_release_allowed is False
    assert packet.machine_write_permitted is False
    assert packet.metrics.action_owner_coverage == 1.0
    assert packet.metrics.unresolved_risk_visibility == 1.0


def test_packet_tamper_is_detected() -> None:
    _case, _control_plane, packet = _packet()
    tampered = packet.model_copy(update={"recommendation_reason": "伪造结论"})

    with pytest.raises(ValueError, match="SHA-256"):
        verify_industrial_quality_decision_packet(tampered)


def test_pre_v5_case_still_projects_to_decision_packet_v1() -> None:
    current, _current_control_plane, _current_packet = _packet()
    payload = current.model_dump(mode="json")
    payload["schema_version"] = "visiondata-gate.industrial-incident-case.v4"
    payload.pop("planning_belief_ledger")
    payload.pop("worker_selection_receipt")
    payload.pop("parent_belief_revision_receipt")
    payload.pop("worker_execution_plan_receipt")
    payload.pop("council_arbitration_receipt")
    payload.pop("autonomy_guard_receipt")
    stable = dict(payload)
    stable.pop("case_sha256")
    payload["case_sha256"] = hashlib.sha256(canonical_json_bytes(stable)).hexdigest()
    legacy = parse_industrial_incident_case(payload)
    control_plane = build_incident_control_plane(legacy)

    packet = build_industrial_quality_decision_packet(
        legacy,
        control_plane=control_plane,
        named_quality_owner_id="quality-manager-legacy",
    )

    assert isinstance(packet, IndustrialQualityDecisionPacketV1)
    assert packet.schema_version == (
        "visiondata-gate.industrial-quality-decision-packet.v1"
    )
    verify_industrial_quality_decision_packet(
        packet,
        case=legacy,
        control_plane=control_plane,
    )
    legacy_exports = build_decision_packet_exports(packet)
    assert legacy_exports.agent_behavior_receipt_json is None
    with zipfile.ZipFile(io.BytesIO(legacy_exports.audit_bundle_zip)) as archive:
        assert "agent_behavior_receipt.json" not in archive.namelist()


def test_exports_are_deterministic_safe_and_machine_readable() -> None:
    _case, _control_plane, packet = _packet(owner="<script>alert(1)</script>")
    first = build_decision_packet_exports(packet)
    second = build_decision_packet_exports(packet)

    assert first.audit_bundle_zip == second.audit_bundle_zip
    assert first.receipt.audit_bundle_sha256 == second.receipt.audit_bundle_sha256
    html = first.decision_packet_html.decode("utf-8")
    assert "<script>alert(1)</script>" not in html
    assert "&lt;script&gt;alert(1)&lt;/script&gt;" in html
    assert "Root cause: NOT_ESTABLISHED" in html
    assert first.evidence_request_csv.startswith(b"\xef\xbb\xbf")
    with zipfile.ZipFile(io.BytesIO(first.audit_bundle_zip)) as archive:
        assert archive.namelist() == [
            "agent_behavior_receipt.json",
            "capa_action_list.json",
            "decision_packet.html",
            "decision_packet.json",
            "evidence_request_list.csv",
            "manifest.json",
        ]
        behavior_bytes = archive.read("agent_behavior_receipt.json")
        behavior = AgentBehaviorReceiptV1.model_validate_json(behavior_bytes)
        verify_agent_behavior_receipt(
            behavior,
            selection=packet.worker_selection_receipt,
        )
        assert behavior.source_selection_receipt_sha256 == (
            packet.worker_selection_receipt.receipt_sha256
        )
        assert behavior.selected_worker_ids
        assert behavior.execution_outcomes_included is False
        assert behavior.model_decision_authority is False
        assert behavior.production_release_allowed is False
        manifest = json.loads(archive.read("manifest.json"))
        assert manifest["artifacts"]["agent_behavior_receipt.json"]["sha256"] == (
            hashlib.sha256(behavior_bytes).hexdigest()
        )
        assert all(
            info.date_time == (1980, 1, 1, 0, 0, 0) for info in archive.infolist()
        )
        assert all(
            info.compress_type == zipfile.ZIP_STORED for info in archive.infolist()
        )
        assert b'raw_source_assets_included":false' in archive.read("manifest.json")


def test_export_writer_persists_behavior_sidecar_idempotently(tmp_path: Path) -> None:
    _case, _control_plane, packet = _packet()
    exports = build_decision_packet_exports(packet)

    write_decision_packet_exports(tmp_path, exports)
    write_decision_packet_exports(tmp_path, exports)

    behavior_path = tmp_path / "agent_behavior_receipt.json"
    assert behavior_path.read_bytes() == exports.agent_behavior_receipt_json

    behavior_path.write_bytes(b"tampered")
    with pytest.raises(FileExistsError, match="agent_behavior_receipt.json"):
        write_decision_packet_exports(tmp_path, exports)
