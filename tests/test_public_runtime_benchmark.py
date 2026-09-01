from __future__ import annotations

from datetime import UTC, datetime
from copy import deepcopy
import hashlib
import json
from pathlib import Path
import subprocess
import sys

from PIL import Image, ImageDraw
from PIL.PngImagePlugin import PngInfo
import pytest

import visiondata_gate.public_runtime_benchmark as benchmark_module
from visiondata_gate.public_governance_bench import (
    OFFICIAL_VISA_1CLS_HEADER,
    build_public_source_binding,
    build_visa_source_index,
    official_visa_1cls_column_mapping,
    visa_csv_header_sha256,
)
from visiondata_gate.public_runtime_benchmark import (
    build_public_runtime_retry_benchmark,
    validate_public_runtime_implementation_receipt,
    validate_public_runtime_retry_benchmark,
    verify_public_runtime_retry_benchmark_bundle,
    write_public_runtime_retry_benchmark,
)
from visiondata_gate.governance_effectiveness_v2 import (
    CreatePairedStrategyComparisonV2Request,
    GovernanceStrategyObservationV2,
    GovernanceTruthBindingV2,
    PairedGovernanceEpisodeV2,
    build_paired_strategy_comparison_v2_report,
)
from visiondata_gate.tools import run_tool


NOW = datetime(2026, 8, 29, 12, 30, tzinfo=UTC)


def _digest(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _reseal_public_report(report: dict) -> None:  # type: ignore[type-arg]
    payload = {key: value for key, value in report.items() if key != "report_sha256"}
    report["report_sha256"] = benchmark_module._digest("public-runtime-report", payload)


def _reseal_implementation_receipt(receipt: dict) -> None:  # type: ignore[type-arg]
    stable = {key: value for key, value in receipt.items() if key != "receipt_sha256"}
    receipt["receipt_sha256"] = benchmark_module._digest(
        "implementation-identity-receipt", stable
    )


def _rebuild_paired_report(report: dict, key: str) -> None:  # type: ignore[type-arg]
    request = CreatePairedStrategyComparisonV2Request.model_validate(
        report[key]["request"]
    )
    report[key] = build_paired_strategy_comparison_v2_report(request).model_dump(
        mode="json"
    )
    _reseal_public_report(report)


def _reseal_report_from_episode_evidence(report: dict) -> None:  # type: ignore[type-arg]
    records = report["episode_evidence_records"]
    for episode in records:
        for execution in episode["executions"].values():
            stable_execution = {
                key: value
                for key, value in execution.items()
                if key != "execution_receipt_sha256"
            }
            execution["execution_receipt_sha256"] = benchmark_module._digest(
                "strategy-execution-evidence",
                stable_execution,
            )
        stable_episode = {
            key: value
            for key, value in episode.items()
            if key != "episode_receipt_sha256"
        }
        episode["episode_receipt_sha256"] = benchmark_module._digest(
            "public-runtime-episode-evidence",
            stable_episode,
        )
    report["episode_evidence_records_sha256"] = benchmark_module._digest(
        "episode-evidence-records",
        records,
    )
    primary_episodes = [
        benchmark_module._paired_episode(
            episode_evidence=item,
            fixed_execution_strategy="FIXED_UNIFORM_BOUNDED_RETRY",
        )
        for item in records
    ]
    reference_episodes = [
        benchmark_module._paired_episode(
            episode_evidence=item,
            fixed_execution_strategy="FIXED_SINGLE_ATTEMPT",
        )
        for item in records
    ]
    evaluated_at = report["paired_strategy_comparison"]["request"]["evaluated_at"]
    primary_request = CreatePairedStrategyComparisonV2Request(
        comparison_id="visa-public-runtime-retry-v2-fixed-uniform-vs-dynamic",
        source_scope=benchmark_module.PUBLIC_SCOPE,
        baseline_strategy="FIXED_EXHAUSTIVE_PIPELINE",
        dataset_identity_sha256=report["dataset_identity_sha256"],
        source_benchmark_sha256=report["truth_receipt_sha256"],
        episodes=primary_episodes,
        evaluated_at=evaluated_at,
        note=(
            "Primary paired VisA public proxy comparison uses equal retry budgets; "
            "truth and faults are withheld from the Agent and Judge inputs."
        ),
    )
    reference_request = CreatePairedStrategyComparisonV2Request(
        comparison_id="visa-public-runtime-retry-v2-single-attempt-reference",
        source_scope=benchmark_module.PUBLIC_SCOPE,
        baseline_strategy="FIXED_RULE_PIPELINE",
        dataset_identity_sha256=report["dataset_identity_sha256"],
        source_benchmark_sha256=report["truth_receipt_sha256"],
        episodes=reference_episodes,
        evaluated_at=evaluated_at,
        note=(
            "Secondary single-attempt reference only; it is not the primary baseline "
            "for Agent advantage claims."
        ),
    )
    report["paired_strategy_comparison"] = build_paired_strategy_comparison_v2_report(
        primary_request
    ).model_dump(mode="json")
    report["single_attempt_reference_comparison"] = (
        build_paired_strategy_comparison_v2_report(reference_request).model_dump(
            mode="json"
        )
    )
    report["protocol_records"] = [
        {
            "episode_id": item["episode_id"],
            "episode_receipt_sha256": item["episode_receipt_sha256"],
            "fault_mode": item["fault_injection"]["fault_mode"],
            "target_tool": item["fault_injection"]["target_tool"],
            "truth_disposition": item["truth_disposition"],
            **item["source_samples"],
        }
        for item in records
    ]
    report["protocol_records_sha256"] = benchmark_module._digest(
        "protocol-records",
        report["protocol_records"],
    )
    fault_modes = [item["fault_injection"]["fault_mode"] for item in records]
    report["runtime_summary"] = benchmark_module._runtime_summary(
        fault_modes,
        primary_episodes,
        reference_episodes,
    )
    report["stratified_governance_metrics"] = (
        benchmark_module._stratified_governance_metrics(
            records,
            primary_episodes,
            reference_episodes,
        )
    )
    report["stratified_governance_metrics_sha256"] = benchmark_module._digest(
        "stratified-governance-metrics",
        report["stratified_governance_metrics"],
    )
    _reseal_public_report(report)


def _fixture(  # type: ignore[no-untyped-def]
    tmp_path: Path, *, perceptually_identical: bool = False
):
    root = tmp_path / "visa"
    rows = ["object,split,label,image,mask"]
    for object_index, object_class in enumerate(("pcb1", "pcb2", "pcb3", "pcb4")):
        image_dir = root / object_class / "Data" / "Images" / "Normal"
        image_dir.mkdir(parents=True)
        for sample_index in range(4):
            path = image_dir / f"{sample_index:04d}.PNG"
            image = Image.new("RGB", (64, 64), color=(240, 240, 240))
            draw = ImageDraw.Draw(image)
            x = (
                4
                + object_index * 10
                + (0 if perceptually_identical else sample_index * 2)
            )
            draw.rectangle((x, 4, min(x + 5, 63), 59), fill=(10, 10, 10))
            draw.line(
                (
                    0,
                    3 if perceptually_identical else sample_index * 8 + 3,
                    63,
                    63 - object_index * 5,
                ),
                fill=(80, 20, 160),
            )
            metadata = PngInfo()
            metadata.add_text("fixture-sample", str(sample_index))
            image.save(path, pnginfo=metadata)
            relative = path.relative_to(root).as_posix()
            rows.append(f"{object_class},train,normal,{relative},")
    split_dir = root / "split_csv"
    split_dir.mkdir()
    (split_dir / "1cls.csv").write_text("\n".join(rows) + "\n", encoding="utf-8")
    (root / "LICENSE-DATASET").write_text("CC BY 4.0", encoding="utf-8")
    binding = build_public_source_binding(
        dataset_version="test-fixture",
        source_homepage_url="https://github.com/amazon-science/spot-diff",
        source_archive_sha256=_digest("archive"),
        license_text_sha256=_digest("license"),
        attribution_text_sha256=_digest("attribution"),
        bound_at=NOW,
    )
    index = build_visa_source_index(
        root,
        source_binding=binding,
        split_csv_relative_path="split_csv/1cls.csv",
        expected_csv_header_sha256=visa_csv_header_sha256(OFFICIAL_VISA_1CLS_HEADER),
        column_mapping=official_visa_1cls_column_mapping(),
    )
    return root, binding, index


def _validate_v2(
    report,
    binding,
    index,
    manifest,
    truth,
    implementation,  # type: ignore[no-untyped-def]
) -> None:
    validate_public_runtime_retry_benchmark(
        report,
        implementation_receipt=implementation,
        source_binding=binding,
        source_index=index,
        programmatic_manifest=manifest,
        truth_receipt=truth,
    )


def test_public_runtime_retry_benchmark_uses_real_assets_and_paired_truth(
    tmp_path: Path,
) -> None:
    root, binding, index = _fixture(tmp_path)

    report, manifest, truth, implementation = build_public_runtime_retry_benchmark(
        dataset_root=root,
        source_binding=binding,
        source_index=index,
        clean_case_count=4,
        block_case_count=4,
        transient_fraction=0.25,
        non_retryable_fraction=0.5,
        evaluated_at=NOW,
    )

    _validate_v2(report, binding, index, manifest, truth, implementation)
    assert manifest.case_count == 8
    assert truth.release_allowed_count == 4
    assert truth.block_required_count == 4
    assert report["source_dataset_mutated"] is False
    assert report["product_labels_used_as_governance_truth"] is False
    assert report["governance_truth_scope"] == "EXACT_CROSS_SPLIT_DUPLICATE_ONLY"
    expected_components = [
        f"src/visiondata_gate/{name}"
        for name in benchmark_module.IMPLEMENTATION_COMPONENTS
    ]
    assert implementation["component_count"] == len(expected_components)
    assert [item["artifact"] for item in implementation["components"]] == (
        expected_components
    )
    assert report["implementation_receipt_sha256"] == implementation["receipt_sha256"]
    for episode in report["episode_evidence_records"]:
        for execution in episode["executions"].values():
            assert execution["wall_clock_latency_ms"] is None
            assert (
                execution["latency_comparison_status"]
                == "NOT_MEASURED_SEQUENTIAL_ORDER_BIAS"
            )
            assert all(
                isinstance(attempt["gateway_response"], list)
                and len(attempt["gateway_response"]) == 3
                for attempt in execution["physical_attempts"]
            )
    summary = report["runtime_summary"]
    assert summary["episode_count"] == 8
    assert summary["transient_fault_episode_count"] == 2
    assert summary["non_retryable_fault_episode_count"] == 4
    assert summary["single_attempt_governance_correct_count"] == 5
    assert summary["fixed_uniform_governance_correct_count"] == 6
    assert summary["dynamic_governance_correct_count"] == 6
    assert summary["single_attempt_transient_recovery_count"] == 0
    assert summary["fixed_uniform_transient_recovery_count"] == 2
    assert summary["dynamic_transient_recovery_count"] == 2
    assert summary["fixed_uniform_non_retryable_retry_count"] == 4
    assert summary["dynamic_non_retryable_retry_count"] == 0
    assert summary["single_attempt_tool_call_count"] == 32
    assert summary["fixed_uniform_tool_call_count"] == 38
    assert summary["dynamic_tool_call_count"] == 34
    assert summary["primary_decision_disposition_match_count"] == 8
    assert summary["unsafe_release_count"] == 0

    paired = report["paired_strategy_comparison"]
    assert paired["request"]["baseline_strategy"] == "FIXED_EXHAUSTIVE_PIPELINE"
    assert paired["overall_fixed"]["false_release_rate"]["value"] == 0.0
    assert paired["overall_dynamic"]["false_release_rate"]["value"] == 0.0
    assert paired["overall_fixed"]["false_block_rate"]["value"] == 0.5
    assert paired["overall_dynamic"]["false_block_rate"]["value"] == 0.5
    assert paired["complex_fixed"]["redundant_tool_call_count"] == 4
    assert paired["complex_dynamic"]["redundant_tool_call_count"] == 0
    assert paired["complex_conflict_verdict"] == "DYNAMIC_EFFICIENCY_ADVANTAGE"

    reference = report["single_attempt_reference_comparison"]
    assert reference["overall_fixed"]["false_block_rate"]["value"] == 0.75
    assert reference["overall_dynamic"]["false_block_rate"]["value"] == 0.5
    assert reference["complex_conflict_verdict"] == "DYNAMIC_FALSE_BLOCK_REDUCTION"
    assert all(
        item["dynamic_observation"]["replan_count"] == 0
        for item in paired["request"]["episodes"]
    )


def test_public_runtime_retry_benchmark_rejects_digest_tampering(
    tmp_path: Path,
) -> None:
    root, binding, index = _fixture(tmp_path)
    report, manifest, truth, implementation = build_public_runtime_retry_benchmark(
        dataset_root=root,
        source_binding=binding,
        source_index=index,
        clean_case_count=1,
        block_case_count=1,
        transient_fraction=1.0,
        non_retryable_fraction=0.0,
        evaluated_at=NOW,
    )
    report["runtime_summary"]["unsafe_release_count"] = 1

    with pytest.raises(ValueError, match="digest mismatch"):
        validate_public_runtime_retry_benchmark(report)

    report, manifest, truth, implementation = build_public_runtime_retry_benchmark(
        dataset_root=root,
        source_binding=binding,
        source_index=index,
        clean_case_count=1,
        block_case_count=1,
        transient_fraction=0.0,
        non_retryable_fraction=0.0,
        evaluated_at=NOW,
    )
    semantic_tamper = deepcopy(report)
    semantic_tamper["runtime_summary"]["dynamic_tool_call_count"] += 1
    payload = {
        key: value for key, value in semantic_tamper.items() if key != "report_sha256"
    }
    semantic_tamper["report_sha256"] = benchmark_module._digest(
        "public-runtime-report", payload
    )
    with pytest.raises(ValueError, match="summary does not reconcile"):
        _validate_v2(semantic_tamper, binding, index, manifest, truth, implementation)

    boundary_tamper = deepcopy(report)
    boundary_tamper["raw_images_transmitted"] = True
    payload = {
        key: value for key, value in boundary_tamper.items() if key != "report_sha256"
    }
    boundary_tamper["report_sha256"] = benchmark_module._digest(
        "public-runtime-report", payload
    )
    with pytest.raises(ValueError, match="boundary must remain false"):
        _validate_v2(boundary_tamper, binding, index, manifest, truth, implementation)


def test_public_runtime_exact_truth_scope_does_not_score_natural_near_duplicate(
    tmp_path: Path,
) -> None:
    root, binding, index = _fixture(tmp_path, perceptually_identical=True)
    specs = benchmark_module._build_episode_specs(
        index,
        clean_case_count=1,
        block_case_count=1,
        transient_fraction=0.0,
        non_retryable_fraction=0.0,
    )
    clean_spec = specs[0]
    clean_manifest, clean_contract = benchmark_module._episode_manifest_and_contract(
        root, clean_spec
    )
    findings, _, _ = run_tool("duplicate_leakage", root, clean_manifest, clean_contract)
    codes = {item.code for item in findings}
    assert "CROSS_SPLIT_NEAR_DUPLICATE" in codes
    assert "CROSS_SPLIT_EXACT_DUPLICATE" not in codes

    report, manifest, truth, implementation = build_public_runtime_retry_benchmark(
        dataset_root=root,
        source_binding=binding,
        source_index=index,
        clean_case_count=1,
        block_case_count=1,
        transient_fraction=0.0,
        non_retryable_fraction=0.0,
        evaluated_at=NOW,
    )
    _validate_v2(report, binding, index, manifest, truth, implementation)
    clean_episode = report["paired_strategy_comparison"]["request"]["episodes"][0]
    assert clean_episode["truth"]["disposition"] == "RELEASE_ALLOWED"
    assert clean_episode["fixed_observation"]["system_disposition"] == "RELEASED"
    assert clean_episode["dynamic_observation"]["system_disposition"] == "RELEASED"
    assert (
        report["paired_strategy_comparison"]["overall_dynamic"]["false_block_rate"][
            "value"
        ]
        == 0.0
    )


def test_public_runtime_v2_binds_detached_implementation_identity(
    tmp_path: Path,
) -> None:
    root, binding, index = _fixture(tmp_path)
    report, manifest, truth, implementation = build_public_runtime_retry_benchmark(
        dataset_root=root,
        source_binding=binding,
        source_index=index,
        clean_case_count=1,
        block_case_count=1,
        transient_fraction=0.0,
        non_retryable_fraction=0.0,
        evaluated_at=NOW,
    )
    with pytest.raises(ValueError, match="requires all detached receipts"):
        validate_public_runtime_retry_benchmark(report)

    tampered_implementation = deepcopy(implementation)
    tampered_implementation["components"][0]["sha256"] = "0" * 64
    with pytest.raises(ValueError, match="implementation receipt digest mismatch"):
        _validate_v2(
            report,
            binding,
            index,
            manifest,
            truth,
            tampered_implementation,
        )

    tampered_truth = truth.model_copy(update={"receipt_sha256": "0" * 64})
    with pytest.raises(
        ValueError, match="programmatic governance truth receipt failed SHA-256"
    ):
        _validate_v2(
            report,
            binding,
            index,
            manifest,
            tampered_truth,
            implementation,
        )


def test_public_runtime_v2_rejects_resealed_disposition_forgery(
    tmp_path: Path,
) -> None:
    root, binding, index = _fixture(tmp_path)
    report, manifest, truth, implementation = build_public_runtime_retry_benchmark(
        dataset_root=root,
        source_binding=binding,
        source_index=index,
        clean_case_count=2,
        block_case_count=2,
        transient_fraction=0.0,
        non_retryable_fraction=1.0,
        evaluated_at=NOW,
    )
    tampered = deepcopy(report)
    episodes = tampered["paired_strategy_comparison"]["request"]["episodes"]
    target = next(
        item
        for item in episodes
        if item["dynamic_observation"]["system_disposition"] == "HUMAN_REVIEW"
    )
    target["dynamic_observation"]["system_disposition"] = "RELEASED"
    _rebuild_paired_report(tampered, "paired_strategy_comparison")

    with pytest.raises(ValueError, match="not evidence-rebuildable"):
        _validate_v2(tampered, binding, index, manifest, truth, implementation)


def test_public_runtime_v2_rejects_resealed_latency_forgery(
    tmp_path: Path,
) -> None:
    root, binding, index = _fixture(tmp_path)
    report, manifest, truth, implementation = build_public_runtime_retry_benchmark(
        dataset_root=root,
        source_binding=binding,
        source_index=index,
        clean_case_count=1,
        block_case_count=1,
        transient_fraction=0.0,
        non_retryable_fraction=0.0,
        evaluated_at=NOW,
    )
    tampered = deepcopy(report)
    observation = tampered["paired_strategy_comparison"]["request"]["episodes"][0][
        "dynamic_observation"
    ]
    assert observation["latency_ms"] is None
    observation["latency_ms"] = 1.0
    _rebuild_paired_report(tampered, "paired_strategy_comparison")

    with pytest.raises(ValueError, match="not evidence-rebuildable"):
        _validate_v2(tampered, binding, index, manifest, truth, implementation)


def test_public_runtime_v2_rejects_resealed_wall_clock_latency_forgery(
    tmp_path: Path,
) -> None:
    root, binding, index = _fixture(tmp_path)
    report, manifest, truth, implementation = build_public_runtime_retry_benchmark(
        dataset_root=root,
        source_binding=binding,
        source_index=index,
        clean_case_count=1,
        block_case_count=1,
        transient_fraction=0.0,
        non_retryable_fraction=0.0,
        evaluated_at=NOW,
    )
    tampered = deepcopy(report)
    execution = tampered["episode_evidence_records"][0]["executions"][
        "DYNAMIC_CONTRACT_AWARE_RETRY"
    ]
    assert execution["wall_clock_latency_ms"] is None
    execution["wall_clock_latency_ms"] = 123.456
    _reseal_report_from_episode_evidence(tampered)

    with pytest.raises(ValueError, match="latency must remain null"):
        _validate_v2(tampered, binding, index, manifest, truth, implementation)


def test_public_runtime_v2_rejects_resealed_gate_run_id_forgery(
    tmp_path: Path,
) -> None:
    root, binding, index = _fixture(tmp_path)
    report, manifest, truth, implementation = build_public_runtime_retry_benchmark(
        dataset_root=root,
        source_binding=binding,
        source_index=index,
        clean_case_count=1,
        block_case_count=1,
        transient_fraction=0.0,
        non_retryable_fraction=0.0,
        evaluated_at=NOW,
    )
    tampered = deepcopy(report)
    execution = tampered["episode_evidence_records"][0]["executions"][
        "DYNAMIC_CONTRACT_AWARE_RETRY"
    ]
    execution["gate"]["run_id"] = "public-forged-run-id"
    execution["gate_sha256"] = benchmark_module._digest(
        "gate-decision",
        execution["gate"],
    )
    _reseal_report_from_episode_evidence(tampered)

    with pytest.raises(ValueError, match="run ID drifted"):
        _validate_v2(tampered, binding, index, manifest, truth, implementation)


def test_public_runtime_v2_rejects_donor_summary_over_injected_attempts(
    tmp_path: Path,
) -> None:
    root, binding, index = _fixture(tmp_path)
    report, manifest, truth, implementation = build_public_runtime_retry_benchmark(
        dataset_root=root,
        source_binding=binding,
        source_index=index,
        clean_case_count=4,
        block_case_count=4,
        transient_fraction=0.0,
        non_retryable_fraction=0.5,
        evaluated_at=NOW,
    )
    tampered = deepcopy(report)
    records = tampered["episode_evidence_records"]
    target = next(
        item
        for item in records
        if item["truth_disposition"] == "RELEASE_ALLOWED"
        and item["fault_injection"]["fault_mode"] == "PERMISSION_DENIED_PERSISTENT"
    )
    donor = next(
        item
        for item in records
        if item["truth_disposition"] == "RELEASE_ALLOWED"
        and item["fault_injection"]["fault_mode"] == "NONE"
    )
    target_execution = target["executions"]["DYNAMIC_CONTRACT_AWARE_RETRY"]
    donor_execution = donor["executions"]["DYNAMIC_CONTRACT_AWARE_RETRY"]
    expected_target_run_id = target_execution["gate"]["run_id"]
    assert target_execution["gate"]["decision"] == "DEFER"
    assert donor_execution["gate"]["decision"] == "PASS"
    assert any(
        attempt["outcome"] == "INJECTED_EXCEPTION"
        and attempt["exception_type"] == "PermissionError"
        for attempt in target_execution["physical_attempts"]
    )
    for key in (
        "gate",
        "gate_sha256",
        "tool_traces",
        "all_findings",
        "scored_findings",
        "out_of_scope_findings",
        "metrics",
    ):
        target_execution[key] = deepcopy(donor_execution[key])
    target_execution["gate"]["run_id"] = expected_target_run_id
    target_execution["gate_sha256"] = benchmark_module._digest(
        "gate-decision",
        target_execution["gate"],
    )
    _reseal_report_from_episode_evidence(tampered)
    forged_episode = next(
        item
        for item in tampered["paired_strategy_comparison"]["request"]["episodes"]
        if item["episode_id"] == target["episode_id"]
    )
    assert forged_episode["dynamic_observation"]["system_disposition"] == "RELEASED"

    with pytest.raises(ValueError, match="not derived from physical attempt"):
        _validate_v2(tampered, binding, index, manifest, truth, implementation)

    gateway_forged = deepcopy(tampered)
    forged_target = next(
        item
        for item in gateway_forged["episode_evidence_records"]
        if item["episode_id"] == target["episode_id"]
    )
    forged_donor = next(
        item
        for item in gateway_forged["episode_evidence_records"]
        if item["episode_id"] == donor["episode_id"]
    )
    target_tool = forged_target["fault_injection"]["target_tool"]
    forged_target_execution = forged_target["executions"][
        "DYNAMIC_CONTRACT_AWARE_RETRY"
    ]
    forged_donor_execution = forged_donor["executions"]["DYNAMIC_CONTRACT_AWARE_RETRY"]
    injected_attempt = next(
        item
        for item in forged_target_execution["physical_attempts"]
        if item["outcome"] == "INJECTED_EXCEPTION"
    )
    donor_attempt = next(
        item
        for item in forged_donor_execution["physical_attempts"]
        if item["tool_name"] == target_tool
    )
    expected_request_sha256 = injected_attempt["gateway_response"][1]["input_sha256"]
    injected_attempt["gateway_response"] = deepcopy(donor_attempt["gateway_response"])
    injected_attempt["gateway_response"][1]["input_sha256"] = expected_request_sha256
    stable_attempt = {
        key: value for key, value in injected_attempt.items() if key != "attempt_sha256"
    }
    injected_attempt["attempt_sha256"] = benchmark_module._digest(
        "physical-tool-attempt",
        stable_attempt,
    )
    _reseal_report_from_episode_evidence(gateway_forged)

    with pytest.raises(ValueError, match="not raw-call-derived"):
        _validate_v2(
            gateway_forged,
            binding,
            index,
            manifest,
            truth,
            implementation,
        )


def test_public_runtime_implementation_identity_rejects_semantic_forgery() -> None:
    implementation = benchmark_module.build_public_runtime_implementation_receipt()
    validate_public_runtime_implementation_receipt(
        implementation,
        verify_current_sources=True,
    )

    extra_field = deepcopy(implementation)
    extra_field["host_name"] = "forged-host"
    _reseal_implementation_receipt(extra_field)
    with pytest.raises(ValueError, match="fields drifted"):
        validate_public_runtime_implementation_receipt(extra_field)

    host_path_claim = deepcopy(implementation)
    host_path_claim["host_paths_serialized"] = True
    _reseal_implementation_receipt(host_path_claim)
    with pytest.raises(ValueError, match="exposed host paths"):
        validate_public_runtime_implementation_receipt(host_path_claim)

    dependency_drift = deepcopy(implementation)
    dependency_drift["runtime_environment"]["distributions"][0]["version"] = (
        "0.0.0-forged"
    )
    _reseal_implementation_receipt(dependency_drift)
    with pytest.raises(ValueError, match="differs from receipt"):
        validate_public_runtime_implementation_receipt(
            dependency_drift,
            verify_current_sources=True,
        )

    source_drift = deepcopy(implementation)
    source_drift["components"][0]["sha256"] = "f" * 64
    _reseal_implementation_receipt(source_drift)
    with pytest.raises(ValueError, match="differs from receipt"):
        validate_public_runtime_implementation_receipt(
            source_drift,
            verify_current_sources=True,
        )


def test_public_runtime_verify_only_replays_existing_bundle_without_tools(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    root, binding, index = _fixture(tmp_path)
    binding_path = tmp_path / "source_binding.json"
    index_path = tmp_path / "source_index.json"
    binding_path.write_text(binding.model_dump_json(), encoding="utf-8")
    index_path.write_text(index.model_dump_json(), encoding="utf-8")
    output = tmp_path / "bundle"
    write_public_runtime_retry_benchmark(
        output,
        dataset_root=root,
        source_binding_path=binding_path,
        source_index_path=index_path,
        clean_case_count=1,
        block_case_count=1,
        transient_fraction=0.0,
        non_retryable_fraction=0.0,
        evaluated_at=NOW,
    )

    def forbidden_execution(*args, **kwargs):  # type: ignore[no-untyped-def]
        raise AssertionError("verify-only must not execute image tools")

    monkeypatch.setattr(benchmark_module, "_execute_strategy", forbidden_execution)
    verified = verify_public_runtime_retry_benchmark_bundle(
        output,
        source_binding_path=binding_path,
        source_index_path=index_path,
        verify_current_sources=True,
    )
    assert verified["status"] == "PASS"
    assert verified["runtime_summary"]["episode_count"] == 2

    project_root = Path(__file__).resolve().parents[1]
    completed = subprocess.run(
        [
            sys.executable,
            str(project_root / "tools" / "run_public_runtime_benchmark.py"),
            "--verify-only",
            "--source-binding",
            str(binding_path),
            "--source-index",
            str(index_path),
            "--output-dir",
            str(output),
        ],
        cwd=project_root,
        check=True,
        capture_output=True,
        text=True,
        encoding="utf-8",
    )
    cli_receipt = json.loads(completed.stdout)
    assert cli_receipt["verification_mode"] == "VERIFY_ONLY"
    assert cli_receipt["semantic_replay"] == "PASS"
    assert cli_receipt["current_source_identity"] == "PASS"


def _portable_legacy_v1_report() -> dict:  # type: ignore[type-arg]
    def observation(strategy: str) -> GovernanceStrategyObservationV2:
        return GovernanceStrategyObservationV2(
            strategy=strategy,
            system_disposition="RELEASED",
            decision_receipt_sha256="a" * 64,
            trace_receipt_sha256="b" * 64,
            replan_triggered=False,
            replan_count=0,
            selected_worker_count=0,
            selected_worker_ids=[],
            worker_selection_evidence_status="NOT_APPLICABLE",
            detected_evidence_gap_ids=[],
            covered_required_gap_ids=[],
            unresolved_required_gap_ids=[],
            tool_call_count=4,
            redundant_tool_call_count=0,
            latency_ms=None,
            actual_model_call_count=0,
            actual_model_token_count=0,
            provider_billed_api_cost_cny=0.0,
        )

    episode = PairedGovernanceEpisodeV2(
        episode_id="portable-v1-clean-control",
        source_scope=benchmark_module.PUBLIC_SCOPE,
        input_contract_sha256="c" * 64,
        input_manifest_sha256="d" * 64,
        truth=GovernanceTruthBindingV2(
            status="ADJUDICATED",
            disposition="RELEASE_ALLOWED",
            method="FROZEN_PROGRAMMATIC_GOVERNANCE_INJECTION",
            adjudication_receipt_sha256="e" * 64,
        ),
        required_evidence_gap_ids=[],
        conflict_tags=[],
        complex_conflict=False,
        fixed_observation=observation("FIXED_RULE_PIPELINE"),
        dynamic_observation=observation("DYNAMIC_EVIDENCE_AGENT"),
    )
    request = CreatePairedStrategyComparisonV2Request(
        comparison_id="portable-public-runtime-v1-golden",
        source_scope=benchmark_module.PUBLIC_SCOPE,
        baseline_strategy="FIXED_RULE_PIPELINE",
        dataset_identity_sha256="f" * 64,
        source_benchmark_sha256="1" * 64,
        episodes=[episode],
        evaluated_at=NOW.isoformat(),
        note="Portable legacy compatibility fixture with no external file dependency.",
    )
    paired = build_paired_strategy_comparison_v2_report(request)
    stable = {
        "schema_version": benchmark_module.LEGACY_SCHEMA_VERSION,
        "benchmark_id": benchmark_module.LEGACY_BENCHMARK_ID,
        "status": "PASS",
        "runtime_summary": {"episode_count": 1, "unsafe_release_count": 0},
        "paired_strategy_comparison": paired.model_dump(mode="json"),
        "raw_images_transmitted": False,
        "source_dataset_mutated": False,
        "product_labels_used_as_governance_truth": False,
        "production_release_allowed": False,
        "claim_boundary": benchmark_module.CLAIM_BOUNDARY,
    }
    return {
        **stable,
        "report_sha256": benchmark_module._digest("public-runtime-report", stable),
    }


def test_public_runtime_portable_v1_golden_remains_verifiable() -> None:
    report = _portable_legacy_v1_report()
    assert report["report_sha256"] == (
        "f6cb60e27b1d9f50a793f19d910dac3288c16704b9e39a5aad54c0868e3a7ad7"
    )
    validate_public_runtime_retry_benchmark(report)
