"""Labelled local fixtures for UI rehearsal, benchmarks, and tests.

This module is deliberately outside the industrial incident core.  It builds
simulated evidence contracts for deterministic local exercises and must never
be treated as factory evidence.
"""

from __future__ import annotations

import hashlib
from datetime import UTC, datetime, timedelta

from .evidence import canonical_json_bytes
from .incident_runtime_profile import IncidentRuntimeProfile
from .industrial_incident import (
    IndustrialIncidentRequest,
    IndustrialIncidentRequestV3,
    IndustrialIncidentTrigger,
    IncidentTriggerKind,
    ManufacturingRecordAuthorityStatus,
    OfflineVisionRunReceipt,
    OPCUAMachineVisionContext,
    OPCUANodeObservation,
    OPCUAOfflineSnapshot,
    OPCUASnapshotMode,
    OPCUAValueSeverity,
    ProcessSignalExpectation,
    ProductionChangeKind,
    VisionSolutionManifest,
    build_batch_trace_record,
    build_production_change_record,
)


def _require_aware(value: datetime) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("timestamp must include an explicit UTC offset")
    return value


def _sha256(value: object) -> str:
    return hashlib.sha256(canonical_json_bytes(value)).hexdigest()


def build_fixture_industrial_incident_request(
    *,
    triggered_at: datetime | None = None,
    revision: int = 1,
) -> IndustrialIncidentRequest:
    """Build a visibly simulated request for UI and API contract rehearsal.

    The fixture intentionally contains process-window and solution-baseline
    drift so the coordinator must dispatch multiple specialist workers.  It is
    never presented as factory evidence.
    """

    if revision < 1 or revision > 12:
        raise ValueError("fixture revision must be between 1 and 12")
    event_time = triggered_at or (
        datetime(2026, 8, 26, 8, 10, tzinfo=UTC) + timedelta(minutes=revision - 1)
    )
    event_time = _require_aware(event_time)
    revision_label = f"r{revision}"
    solution = VisionSolutionManifest(
        source_profile="VISIONMASTER_COMPATIBLE_OFFLINE_EXPORT",
        solution_id="fixture-connector-pin-v2",
        solution_version="2.4.1-fixture",
        product_id="fixture-product-A",
        recipe_id="fixture-recipe-A-17",
        configuration_id="fixture-cfg-17",
        exported_at=event_time - timedelta(minutes=10),
        algorithm_graph_sha256=_sha256("fixture-algorithm-graph"),
        model_artifact_sha256=_sha256("fixture-model-artifact"),
        camera_config_sha256=_sha256("fixture-camera-config"),
        lighting_config_sha256=_sha256("fixture-lighting-config"),
        calibration_receipt_sha256=_sha256("fixture-calibration"),
        rulepack_sha256=_sha256("fixture-rulepack"),
        dataset_version_id="fixture-derived-v1",
    )
    solution_sha256 = _sha256(solution)
    snapshot = OPCUAOfflineSnapshot(
        source_mode=OPCUASnapshotMode.FIXTURE_REPLAY,
        captured_at=event_time,
        server_application_uri_sha256=_sha256("fixture-server-application-uri"),
        node_whitelist_sha256=_sha256("fixture-node-whitelist"),
        allowlisted_aliases=["line.speed"],
        machine_vision_context=OPCUAMachineVisionContext(
            product_id="fixture-product-A",
            part_id="fixture-part-00042",
            recipe_id="fixture-recipe-A-17",
            configuration_id="fixture-cfg-17",
            job_id=f"fixture-job-20260826-42-{revision_label}",
            result_id=f"fixture-result-20260826-42-{revision_label}",
            creation_time=event_time - timedelta(seconds=1),
            result_state="Completed",
            is_simulated=True,
            lot_reference="fixture-lot-20260826-A",
            lot_reference_authority="OPERATOR_ATTESTATION",
        ),
        observations=[
            OPCUANodeObservation(
                semantic_alias="line.speed",
                namespace_uri="urn:visiondata-gate:fixture:line-a",
                browse_path="FixtureLineA/Process/Speed",
                node_id_sha256=_sha256("fixture-process-speed-node"),
                data_type="Double",
                engineering_unit="mm/s",
                value=96.0,
                status_code="Good",
                severity=OPCUAValueSeverity.GOOD,
                source_timestamp=event_time - timedelta(seconds=2),
                server_timestamp=event_time - timedelta(seconds=1),
            )
        ],
        operator_attests_authorized_export=True,
    )
    offline_run = OfflineVisionRunReceipt(
        source_profile="VISIONMASTER_COMPATIBLE_OFFLINE_EXPORT",
        run_id=f"fixture-run-20260826-42-{revision_label}",
        solution_manifest_sha256=solution_sha256,
        product_id="fixture-product-A",
        part_id="fixture-part-00042",
        recipe_id="fixture-recipe-A-17",
        configuration_id="fixture-cfg-17",
        job_id=f"fixture-job-20260826-42-{revision_label}",
        result_id=f"fixture-result-20260826-42-{revision_label}",
        batch_id="fixture-batch-20260826-A",
        lot_reference="fixture-lot-20260826-A",
        work_order_id="fixture-work-order-20260826-42",
        line_id="fixture-line-A",
        started_at=event_time - timedelta(seconds=8),
        completed_at=event_time - timedelta(seconds=1),
        execution_state="Completed",
        input_count=100,
        ok_count=89,
        ng_count=11,
        is_simulated=True,
        sample_index_sha256=_sha256(f"fixture-sample-index-{revision_label}"),
        result_summary_sha256=_sha256(f"fixture-result-summary-{revision_label}"),
    )
    batch_trace_record = build_batch_trace_record(
        record_id=f"fixture-batch-record-{revision_label}",
        source_kind="MES_EXPORT",
        source_system_id_sha256=_sha256("fixture-mes-system"),
        source_record_sha256=_sha256(f"fixture-batch-source-{revision_label}"),
        source_authorization_sha256=_sha256("fixture-batch-authorization"),
        authority_status=ManufacturingRecordAuthorityStatus.VERIFIED,
        batch_id="fixture-batch-20260826-A",
        lot_reference="fixture-lot-20260826-A",
        work_order_id="fixture-work-order-20260826-42",
        line_id="fixture-line-A",
        product_id="fixture-product-A",
        part_id="fixture-part-00042",
        recipe_id="fixture-recipe-A-17",
        configuration_id="fixture-cfg-17",
        production_window_start=event_time - timedelta(minutes=30),
        production_window_end=event_time,
        exported_at=event_time + timedelta(seconds=1),
        operator_attests_authorized_export=True,
        is_simulated=True,
    )
    production_change_record = build_production_change_record(
        record_id=f"fixture-change-record-{revision_label}",
        change_order_id="fixture-change-order-20260826-42",
        change_kind=ProductionChangeKind.PRODUCT_CHANGEOVER,
        change_status="APPROVED_EFFECTIVE",
        source_kind="APPROVED_OFFLINE_EXPORT",
        source_system_id_sha256=_sha256("fixture-mes-system"),
        source_record_sha256=_sha256(f"fixture-change-source-{revision_label}"),
        source_authorization_sha256=_sha256("fixture-change-authorization"),
        authority_status=ManufacturingRecordAuthorityStatus.VERIFIED,
        line_id="fixture-line-A",
        work_order_id="fixture-work-order-20260826-42",
        batch_id="fixture-batch-20260826-A",
        lot_reference="fixture-lot-20260826-A",
        effective_at=event_time - timedelta(minutes=20),
        recorded_at=event_time - timedelta(minutes=19),
        exported_at=event_time - timedelta(minutes=18),
        previous_product_id="fixture-product-legacy",
        new_product_id="fixture-product-A",
        operator_attests_authorized_export=True,
        is_simulated=True,
    )
    return IndustrialIncidentRequestV3(
        trigger=IndustrialIncidentTrigger(
            trigger_kind=IncidentTriggerKind.NG_RATE_DRIFT,
            triggered_at=event_time,
            operator_message=(
                "FIXTURE：换型后 NG 率由 2% 上升到 11%，请判断补证、处置与复验动作。"
            ),
            product_id="fixture-product-A",
            part_id="fixture-part-00042",
            recipe_id="fixture-recipe-A-17",
            configuration_id="fixture-cfg-17",
            batch_id="fixture-batch-20260826-A",
            lot_reference="fixture-lot-20260826-A",
            work_order_id="fixture-work-order-20260826-42",
            line_id="fixture-line-A",
            baseline_ng_rate=0.02,
            observed_ng_rate=0.11,
            sample_count=100,
        ),
        opcua_snapshot=snapshot,
        vision_solution=solution,
        offline_run=offline_run,
        batch_trace_record=batch_trace_record,
        production_change_records=[production_change_record],
        process_signal_expectations=[
            ProcessSignalExpectation(
                semantic_alias="line.speed",
                engineering_unit="mm/s",
                minimum=75.0,
                maximum=90.0,
            )
        ],
        baseline_solution_manifest_sha256=_sha256("fixture-approved-baseline"),
        runtime_profile=IncidentRuntimeProfile(),
        operator_attests_inputs_authorized=True,
    )


__all__ = ["build_fixture_industrial_incident_request"]
