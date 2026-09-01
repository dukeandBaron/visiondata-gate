"""Real-asset public proxy benchmark for bounded Agent tool recovery.

The benchmark uses read-only VisA images plus frozen programmatic governance
truth. Product anomaly labels never enter the Agent or Judge. Its primary
comparison is deliberately strong: a fixed exhaustive pipeline with the same
per-tool retry budget as the Agent versus contract-aware bounded recovery. A
single-attempt fixed pipeline is retained only as a secondary reference.

The fixed strong baseline retries every typed tool error uniformly. The Agent
retries only transient timeout/connection errors and suppresses retries after
permission or response-integrity failures. Inputs, contracts, injected faults,
tools, retry budgets, truth, and Policy Judge are paired.

This is a fault-intervention benchmark, not a factory failure-rate estimate.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
import hashlib
import hmac
import importlib.metadata
import json
from itertools import product
from math import sqrt
from pathlib import Path
import platform
from typing import Any, cast, Literal

from PIL import Image
import rfc8785

from .agent_runtime import execute_tool_with_bounded_retry
from .contracts import (
    BatchContract,
    BatchManifest,
    CoverageContract,
    Finding,
    GateDecision,
    GateResult,
    QualityThresholds,
    SampleRecord,
    ToolTrace,
)
from .governance_effectiveness_v2 import (
    CreatePairedStrategyComparisonV2Request,
    GovernanceStrategyObservationV2,
    GovernanceTruthBindingV2,
    PairedGovernanceEpisodeV2,
    PairedStrategyComparisonV2Report,
    build_paired_strategy_comparison_v2_report,
    verify_paired_strategy_comparison_v2_report,
)
from .policy import apply_policy
from .public_governance_bench import (
    CreateProgrammaticGovernanceCase,
    ProgrammaticGovernanceInjectionManifest,
    ProgrammaticGovernanceTruthReceipt,
    PublicSourceBinding,
    VisaSourceIndex,
    VisaSourceSample,
    build_programmatic_governance_manifest,
    build_programmatic_truth_receipt,
    canonical_public_bench_json_bytes,
    governance_truth_binding_from_public_receipt,
    verify_public_source_binding,
    verify_programmatic_governance_manifest,
    verify_programmatic_truth_receipt,
    verify_visa_source_index,
)
from .runtime_models import ScenarioProfile
from .tools import (
    MetricValue,
    ToolResult,
    build_batch_fingerprint,
    build_tool_error_trace,
    build_tool_request_sha256,
    execute_tool_gateway,
    run_tool,
    tool_catalog,
    tool_contract_catalog,
    validate_tool_response,
)


SCHEMA_VERSION = "visiondata-gate.public-runtime-retry-benchmark.v2"
LEGACY_SCHEMA_VERSION = "visiondata-gate.public-runtime-retry-benchmark.v1"
BENCHMARK_ID = "Public-GovernanceBench-v1-runtime-recovery-v2"
LEGACY_BENCHMARK_ID = "Public-GovernanceBench-v1-runtime-recovery"
PUBLIC_SCOPE = "PUBLIC_INDUSTRIAL_PROXY_WITH_PROGRAMMATIC_GOVERNANCE_TRUTH"
TOOL_ORDER = (
    "image_quality",
    "duplicate_leakage",
    "annotation_integrity",
    "coverage_matrix",
)
RAW_TOOL_METRIC_NAMES = {
    "image_quality": (
        "sample_count",
        "decoded_image_count",
        "decode_failure_count",
        "invalid_dimension_count",
        "underexposed_count",
        "overexposed_count",
        "low_sharpness_count",
        "mean_luma_min",
        "mean_luma_max",
        "sharpness_min",
        "sharpness_max",
    ),
    "duplicate_leakage": (
        "sample_count",
        "hashed_file_count",
        "perceptual_eligible_count",
        "decode_skipped_count",
        "exact_duplicate_group_count",
        "exact_duplicate_pair_count",
        "cross_split_exact_pair_count",
        "cross_split_compared_pair_count",
        "cross_split_near_pair_count",
    ),
    "annotation_integrity": (
        "sample_count",
        "annotation_path_count",
        "decoded_mask_count",
        "missing_annotation_count",
        "annotation_dimension_mismatch_count",
        "mask_fraction_out_of_range_count",
        "mask_fraction_min",
        "mask_fraction_max",
    ),
    "coverage_matrix": (
        "expected_cell_count",
        "observed_cell_count",
        "missing_cell_count",
        "minimum_observed_cell_count",
        "required_min_per_cell",
    ),
}
SCORED_POLICY_FINDING_CODES = (
    "EXACT_DUPLICATE",
    "CROSS_SPLIT_EXACT_DUPLICATE",
)
FRAME_MAGIC = b"VISIONDATA_GATE_PUBLIC_RUNTIME_BENCHMARK_V1\x00"
IMPLEMENTATION_RECEIPT_SCHEMA_VERSION = (
    "visiondata-gate.public-runtime-implementation-identity.v1"
)
EPISODE_EVIDENCE_SCHEMA_VERSION = "visiondata-gate.public-runtime-episode-evidence.v1"
EXECUTION_EVIDENCE_SCHEMA_VERSION = (
    "visiondata-gate.public-runtime-execution-evidence.v1"
)
LATENCY_COMPARISON_STATUS = "NOT_MEASURED_SEQUENTIAL_ORDER_BIAS"
IMPLEMENTATION_COMPONENTS = (
    "public_runtime_benchmark.py",
    "agent_runtime.py",
    "tools.py",
    "policy.py",
    "governance_effectiveness_v2.py",
    "public_governance_bench.py",
    "contracts.py",
    "duplicates.py",
    "quality.py",
    "annotations.py",
    "coverage.py",
    "audit_envelope.py",
    "runtime_models.py",
    "agents.py",
    "runtime_safety.py",
    "product_models.py",
    "evidence.py",
)
IMPLEMENTATION_PROJECT_ARTIFACTS = ("pyproject.toml", "uv.lock")
IMPLEMENTATION_DISTRIBUTIONS = ("Pillow", "numpy", "pydantic", "rfc8785")
CLAIM_BOUNDARY = (
    "This benchmark measures deterministic governance behavior on read-only VisA "
    "assets with frozen programmatic governance truth and injected runtime faults. "
    "It is not a production fault-rate estimate, product anomaly benchmark, customer "
    "acceptance result, external competitor execution, or production authorization."
)

FaultMode = Literal[
    "NONE",
    "TRANSIENT_TIMEOUT_ONCE",
    "PERMISSION_DENIED_PERSISTENT",
    "TOOL_RESPONSE_INTEGRITY_PERSISTENT",
]
ExecutionStrategy = Literal[
    "FIXED_SINGLE_ATTEMPT",
    "FIXED_UNIFORM_BOUNDED_RETRY",
    "DYNAMIC_CONTRACT_AWARE_RETRY",
]
EXECUTION_TO_GOVERNANCE_STRATEGY = {
    "FIXED_SINGLE_ATTEMPT": "FIXED_RULE_PIPELINE",
    "FIXED_UNIFORM_BOUNDED_RETRY": "FIXED_EXHAUSTIVE_PIPELINE",
    "DYNAMIC_CONTRACT_AWARE_RETRY": "DYNAMIC_EVIDENCE_AGENT",
}


@dataclass(frozen=True)
class _EpisodeSpec:
    episode_id: str
    truth_disposition: Literal["RELEASE_ALLOWED", "BLOCK_REQUIRED"]
    primary: VisaSourceSample
    secondary: VisaSourceSample | None
    fault_mode: FaultMode
    target_tool: str | None


class _InjectedFaultRunner:
    def __init__(self, mode: FaultMode, target_tool: str | None) -> None:
        self.mode = mode
        self.target_tool = target_tool
        self.calls: dict[str, int] = {}
        self.attempts: list[dict[str, Any]] = []

    def _record_attempt(
        self,
        *,
        tool_name: str,
        outcome: Literal["TOOL_RESPONSE", "INJECTED_EXCEPTION", "MALFORMED_RESPONSE"],
        fault_applied: bool,
        response: object | None = None,
        exception: Exception | None = None,
    ) -> None:
        stable = {
            "sequence": len(self.attempts) + 1,
            "tool_name": tool_name,
            "tool_attempt": self.calls[tool_name],
            "configured_fault_mode": self.mode,
            "configured_target_tool": self.target_tool,
            "fault_applied": fault_applied,
            "outcome": outcome,
            "response": _json_value(response) if response is not None else None,
            "gateway_response": None,
            "exception_type": type(exception).__name__ if exception else None,
            "exception_message": str(exception) if exception else None,
            "host_paths_serialized": False,
        }
        self.attempts.append(stable)

    def bind_gateway_response(self, response: ToolResult) -> None:
        """Seal the gateway-owned result onto the raw physical call evidence."""

        if not self.attempts:
            raise RuntimeError("cannot bind a gateway response without an attempt")
        attempt = self.attempts[-1]
        if attempt.get("gateway_response") is not None or "attempt_sha256" in attempt:
            raise RuntimeError("physical attempt gateway response was already bound")
        attempt["gateway_response"] = _json_value(response)
        attempt["attempt_sha256"] = _digest("physical-tool-attempt", attempt)

    def __call__(self, tool_name: str, *args: Any, **kwargs: Any) -> object:
        self.calls[tool_name] = self.calls.get(tool_name, 0) + 1
        if tool_name == self.target_tool:
            if self.mode == "TRANSIENT_TIMEOUT_ONCE" and self.calls[tool_name] == 1:
                error = TimeoutError("injected one-shot public benchmark timeout")
                self._record_attempt(
                    tool_name=tool_name,
                    outcome="INJECTED_EXCEPTION",
                    fault_applied=True,
                    exception=error,
                )
                raise error
            if self.mode == "PERMISSION_DENIED_PERSISTENT":
                error = PermissionError("injected persistent permission denial")
                self._record_attempt(
                    tool_name=tool_name,
                    outcome="INJECTED_EXCEPTION",
                    fault_applied=True,
                    exception=error,
                )
                raise error
            if self.mode == "TOOL_RESPONSE_INTEGRITY_PERSISTENT":
                response = {"injected": "malformed persistent tool response"}
                self._record_attempt(
                    tool_name=tool_name,
                    outcome="MALFORMED_RESPONSE",
                    fault_applied=True,
                    response=response,
                )
                return response
        response = run_tool(tool_name, *args, **kwargs)
        self._record_attempt(
            tool_name=tool_name,
            outcome="TOOL_RESPONSE",
            fault_applied=False,
            response=response,
        )
        return response


def _json_value(value: Any) -> Any:
    if hasattr(value, "model_dump"):
        return value.model_dump(mode="json")
    if isinstance(value, dict):
        return {str(key): _json_value(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_json_value(item) for item in value]
    return value


def _canonical_bytes(value: Any) -> bytes:
    return rfc8785.dumps(_json_value(value))


def _digest(domain: str, value: Any) -> str:
    domain_bytes = domain.encode("utf-8")
    payload = _canonical_bytes(value)
    framed = b"".join(
        (
            FRAME_MAGIC,
            len(domain_bytes).to_bytes(2, "big"),
            domain_bytes,
            len(payload).to_bytes(8, "big"),
            payload,
        )
    )
    return hashlib.sha256(framed).hexdigest()


def build_public_runtime_implementation_receipt() -> dict[str, Any]:
    """Bind a run to exact dirty-worktree source bytes without exposing paths."""

    source_dir = Path(__file__).resolve(strict=True).parent
    project_root = source_dir.parents[1]

    def identity(label: str, path: Path) -> dict[str, Any]:
        resolved = path.resolve(strict=True)
        return {
            "artifact": label,
            "sha256": hashlib.sha256(resolved.read_bytes()).hexdigest(),
            "size_bytes": resolved.stat().st_size,
        }

    components = [
        identity(f"src/visiondata_gate/{name}", source_dir / name)
        for name in IMPLEMENTATION_COMPONENTS
    ]
    project_artifacts = [
        identity(name, project_root / name) for name in IMPLEMENTATION_PROJECT_ARTIFACTS
    ]
    distributions = [
        {
            "distribution": name,
            "version": importlib.metadata.version(name),
        }
        for name in IMPLEMENTATION_DISTRIBUTIONS
    ]
    stable = {
        "schema_version": IMPLEMENTATION_RECEIPT_SCHEMA_VERSION,
        "component_count": len(components),
        "components": components,
        "project_artifact_count": len(project_artifacts),
        "project_artifacts": project_artifacts,
        "runtime_environment": {
            "python_implementation": platform.python_implementation(),
            "python_version": platform.python_version(),
            "distributions": distributions,
        },
        "execution_contract": {
            "fixed_primary": "FIXED_UNIFORM_BOUNDED_RETRY",
            "dynamic": "DYNAMIC_CONTRACT_AWARE_RETRY",
            "single_attempt_role": "SECONDARY_REFERENCE_ONLY",
            "configured_max_retries_per_tool": 1,
        },
        "host_paths_serialized": False,
    }
    return {
        **stable,
        "receipt_sha256": _digest("implementation-identity-receipt", stable),
    }


def validate_public_runtime_implementation_receipt(
    receipt: dict[str, Any],
    *,
    verify_current_sources: bool = False,
) -> None:
    expected_top_keys = {
        "schema_version",
        "component_count",
        "components",
        "project_artifact_count",
        "project_artifacts",
        "runtime_environment",
        "execution_contract",
        "host_paths_serialized",
        "receipt_sha256",
    }
    if set(receipt) != expected_top_keys:
        raise ValueError("public runtime implementation receipt fields drifted")
    if receipt.get("schema_version") != IMPLEMENTATION_RECEIPT_SCHEMA_VERSION:
        raise ValueError("public runtime implementation receipt schema mismatch")
    if receipt.get("host_paths_serialized") is not False:
        raise ValueError("public runtime implementation receipt exposed host paths")
    stable = {key: value for key, value in receipt.items() if key != "receipt_sha256"}
    expected = _digest("implementation-identity-receipt", stable)
    observed = receipt.get("receipt_sha256")
    if not isinstance(observed, str) or not hmac.compare_digest(expected, observed):
        raise ValueError("public runtime implementation receipt digest mismatch")
    components = receipt.get("components")
    if not isinstance(components, list) or receipt.get("component_count") != len(
        components
    ):
        raise ValueError("public runtime implementation component count drifted")
    expected_names = [
        f"src/visiondata_gate/{name}" for name in IMPLEMENTATION_COMPONENTS
    ]
    observed_names = [item.get("artifact") for item in components]
    if observed_names != expected_names:
        raise ValueError("public runtime implementation component set drifted")
    project_artifacts = receipt.get("project_artifacts")
    if (
        not isinstance(project_artifacts, list)
        or receipt.get("project_artifact_count") != len(project_artifacts)
        or [item.get("artifact") for item in project_artifacts]
        != list(IMPLEMENTATION_PROJECT_ARTIFACTS)
    ):
        raise ValueError("public runtime project artifact set drifted")
    for component in [*components, *project_artifacts]:
        if set(component) != {"artifact", "sha256", "size_bytes"}:
            raise ValueError("public runtime implementation artifact fields drifted")
        digest = component.get("sha256")
        size_bytes = component.get("size_bytes")
        if (
            not isinstance(digest, str)
            or len(digest) != 64
            or not isinstance(size_bytes, int)
            or size_bytes < 1
        ):
            raise ValueError("public runtime implementation component is malformed")
        try:
            int(digest, 16)
        except ValueError as error:
            raise ValueError(
                "public runtime implementation component digest is malformed"
            ) from error
    environment = receipt.get("runtime_environment")
    if not isinstance(environment, dict) or set(environment) != {
        "python_implementation",
        "python_version",
        "distributions",
    }:
        raise ValueError("public runtime implementation environment fields drifted")
    if not all(
        isinstance(environment.get(key), str) and environment[key]
        for key in ("python_implementation", "python_version")
    ):
        raise ValueError("public runtime Python identity is malformed")
    distributions = environment.get("distributions")
    if not isinstance(distributions, list) or [
        item.get("distribution") for item in distributions
    ] != list(IMPLEMENTATION_DISTRIBUTIONS):
        raise ValueError("public runtime dependency identity set drifted")
    for distribution in distributions:
        if set(distribution) != {"distribution", "version"} or not isinstance(
            distribution.get("version"), str
        ):
            raise ValueError("public runtime dependency identity is malformed")
    execution_contract = receipt.get("execution_contract")
    expected_execution_contract = {
        "fixed_primary": "FIXED_UNIFORM_BOUNDED_RETRY",
        "dynamic": "DYNAMIC_CONTRACT_AWARE_RETRY",
        "single_attempt_role": "SECONDARY_REFERENCE_ONLY",
        "configured_max_retries_per_tool": 1,
    }
    if execution_contract != expected_execution_contract:
        raise ValueError("public runtime implementation execution contract drifted")
    if verify_current_sources:
        current = build_public_runtime_implementation_receipt()
        if _canonical_bytes(current) != _canonical_bytes(receipt):
            raise ValueError(
                "current public runtime implementation differs from receipt"
            )


def _load_model(path: str | Path, model_type: type[Any]) -> Any:
    source = Path(path).expanduser().resolve(strict=True)
    return model_type.model_validate_json(source.read_text(encoding="utf-8"))


def _build_episode_specs(
    source_index: VisaSourceIndex,
    *,
    clean_case_count: int,
    block_case_count: int,
    transient_fraction: float,
    non_retryable_fraction: float,
) -> list[_EpisodeSpec]:
    if clean_case_count < 1 or block_case_count < 1:
        raise ValueError("public runtime benchmark requires both truth classes")
    if not 0.0 <= transient_fraction <= 1.0:
        raise ValueError("transient_fraction must be within [0, 1]")
    if not 0.0 <= non_retryable_fraction <= 1.0:
        raise ValueError("non_retryable_fraction must be within [0, 1]")
    if transient_fraction + non_retryable_fraction > 1.0:
        raise ValueError("runtime fault fractions cannot sum above 1")
    classes = ("pcb1", "pcb2", "pcb3", "pcb4")
    pools = {
        object_class: sorted(
            (
                item
                for item in source_index.samples
                if item.object_class == object_class
                and item.split == "train"
                and item.product_label == "normal"
                and item.mask_relative_path is None
            ),
            key=lambda item: (item.image_sha256, item.source_sample_id),
        )
        for object_class in classes
    }
    required_per_class = {
        object_class: sum(
            2 if index < clean_case_count else 1
            for index in range(clean_case_count + block_case_count)
            if classes[index % len(classes)] == object_class
        )
        for object_class in classes
    }
    for object_class, required in required_per_class.items():
        if len(pools[object_class]) < required:
            raise ValueError(
                f"VisA {object_class} has insufficient frozen normal samples"
            )

    cursors = {item: 0 for item in classes}
    specs: list[_EpisodeSpec] = []
    fault_clean = round(clean_case_count * transient_fraction)
    fault_block = round(block_case_count * transient_fraction)
    non_retryable_clean = round(clean_case_count * non_retryable_fraction)
    non_retryable_block = round(block_case_count * non_retryable_fraction)
    for index in range(clean_case_count + block_case_count):
        is_clean = index < clean_case_count
        ordinal = index if is_clean else index - clean_case_count
        object_class = classes[index % len(classes)]
        cursor = cursors[object_class]
        pool = pools[object_class]
        if cursor >= len(pool):
            raise ValueError(f"VisA {object_class} exhausted frozen normal samples")
        primary = pool[cursor]
        secondary: VisaSourceSample | None = None
        if is_clean:
            secondary_index = cursor + 1
            while (
                secondary_index < len(pool)
                and pool[secondary_index].image_sha256 == primary.image_sha256
            ):
                secondary_index += 1
            if secondary_index >= len(pool):
                raise ValueError(
                    f"VisA {object_class} lacks a distinct-SHA clean control pair"
                )
            secondary = pool[secondary_index]
            cursors[object_class] = secondary_index + 1
        else:
            cursors[object_class] = cursor + 1
        transient_count = fault_clean if is_clean else fault_block
        non_retryable_count = non_retryable_clean if is_clean else non_retryable_block
        if ordinal < transient_count:
            fault_mode: FaultMode = "TRANSIENT_TIMEOUT_ONCE"
        elif ordinal < transient_count + non_retryable_count:
            non_retryable_ordinal = ordinal - transient_count
            parity = non_retryable_ordinal + (0 if is_clean else 1)
            fault_mode = (
                "PERMISSION_DENIED_PERSISTENT"
                if parity % 2 == 0
                else "TOOL_RESPONSE_INTEGRITY_PERSISTENT"
            )
        else:
            fault_mode = "NONE"
        target = TOOL_ORDER[ordinal % len(TOOL_ORDER)] if fault_mode != "NONE" else None
        specs.append(
            _EpisodeSpec(
                episode_id=(
                    f"visa-clean-{ordinal + 1:04d}"
                    if is_clean
                    else f"visa-block-{ordinal + 1:04d}"
                ),
                truth_disposition=("RELEASE_ALLOWED" if is_clean else "BLOCK_REQUIRED"),
                primary=primary,
                secondary=secondary,
                fault_mode=fault_mode,
                target_tool=target,
            )
        )
    return specs


def _programmatic_case_requests(
    specs: list[_EpisodeSpec],
) -> list[CreateProgrammaticGovernanceCase]:
    requests: list[CreateProgrammaticGovernanceCase] = []
    for spec in specs:
        parameter_payload = {
            "episode_id": spec.episode_id,
            "governance_truth_scope": "EXACT_CROSS_SPLIT_DUPLICATE_ONLY",
            "primary_source_sample_id": spec.primary.source_sample_id,
            "secondary_source_sample_id": (
                spec.secondary.source_sample_id if spec.secondary else None
            ),
            "injection": (
                "none"
                if spec.truth_disposition == "RELEASE_ALLOWED"
                else "same_source_asset_referenced_across_train_and_test"
            ),
        }
        requests.append(
            CreateProgrammaticGovernanceCase(
                unit_id=spec.episode_id,
                source_sample_id=spec.primary.source_sample_id,
                case_type=(
                    "CLEAN_CONTROL"
                    if spec.truth_disposition == "RELEASE_ALLOWED"
                    else "EXACT_CROSS_SPLIT_DUPLICATE"
                ),
                parameters_sha256=_digest("episode-parameters", parameter_payload),
            )
        )
    return requests


def _episode_manifest_and_contract(
    dataset_root: Path,
    spec: _EpisodeSpec,
) -> tuple[BatchManifest, BatchContract]:
    if (
        spec.secondary is not None
        and spec.secondary.image_sha256 == spec.primary.image_sha256
    ):
        raise ValueError("clean-control pair must bind distinct source SHA-256 values")
    primary_path = dataset_root / spec.primary.image_relative_path
    with Image.open(primary_path) as image:
        width, height = image.size
    second = spec.secondary or spec.primary
    if spec.secondary is not None:
        with Image.open(dataset_root / spec.secondary.image_relative_path) as image:
            if image.size != (width, height):
                raise ValueError("clean-control pair changed native dimensions")
    manifest = BatchManifest(
        batch_id=spec.episode_id,
        seed=20260829,
        samples=[
            SampleRecord(
                sample_id=f"{spec.episode_id}-train",
                relative_path=spec.primary.image_relative_path,
                split="train",
                category=spec.primary.object_class,
                view="front",
                condition="nominal",
                source_sample_id=spec.primary.source_sample_id,
            ),
            SampleRecord(
                sample_id=f"{spec.episode_id}-test",
                relative_path=second.image_relative_path,
                split="test",
                category=spec.primary.object_class,
                view="front",
                condition="nominal",
                source_sample_id=second.source_sample_id,
            ),
        ],
    )
    contract = BatchContract(
        contract_id="visa-public-runtime-recovery-v1",
        required_splits=["train", "test"],
        annotations_required=False,
        thresholds=QualityThresholds(
            expected_width=width,
            expected_height=height,
            min_mean_luma=0,
            max_mean_luma=255,
            min_sharpness=0,
            min_mask_fraction=0,
            max_mask_fraction=1,
            near_duplicate_hamming=0,
        ),
        coverage=CoverageContract(
            categories=[spec.primary.object_class],
            views=["front"],
            conditions=["nominal"],
            min_per_cell=1,
            splits=["train", "test"],
        ),
        policy_version="gate-policy-public-runtime-recovery-v1",
    )
    return manifest, contract


def _aggregate(
    manifest: BatchManifest,
    results: list[ToolResult],
) -> tuple[list[Finding], list[ToolTrace], dict[str, MetricValue]]:
    findings: list[Finding] = []
    traces: list[ToolTrace] = []
    metrics: dict[str, MetricValue] = {
        "sample_count": len(manifest.samples),
        "tool_count": len(results),
        "tool_error_count": sum(item[1].status != "ok" for item in results),
    }
    for tool_findings, trace, tool_metrics in results:
        findings.extend(tool_findings)
        traces.append(trace)
        metrics.update(tool_metrics)
    findings.sort(key=lambda item: (item.tool, item.finding_id))
    traces.sort(key=lambda item: item.sequence)
    metrics["finding_count"] = len(findings)
    return findings, traces, metrics


def _execute_tool_with_uniform_bounded_retry(
    tool_name: str,
    dataset_root: Path,
    manifest: BatchManifest,
    contract: BatchContract,
    *,
    runner: _InjectedFaultRunner,
    batch_fingerprint: str,
    configured_max_retries: int,
) -> tuple[ToolResult, int]:
    """Strong fixed baseline: retry every typed error within the same budget."""

    tool_contract = next(
        item
        for item in tool_contract_catalog(include_optional=False)
        if item.name == tool_name
    )
    retry_budget = min(configured_max_retries, tool_contract.max_retries)
    retry_count = 0
    while True:
        result = execute_tool_gateway(
            tool_name,
            dataset_root,
            manifest,
            contract,
            runner=runner,
            batch_fingerprint=batch_fingerprint,
        )
        runner.bind_gateway_response(result)
        if result[1].status != "error" or retry_count >= retry_budget:
            return result, retry_count
        retry_count += 1


def _execute_strategy(
    dataset_root: Path,
    manifest: BatchManifest,
    contract: BatchContract,
    spec: _EpisodeSpec,
    *,
    strategy: ExecutionStrategy,
) -> dict[str, Any]:
    runner = _InjectedFaultRunner(spec.fault_mode, spec.target_tool)
    fingerprint = build_batch_fingerprint(dataset_root, manifest)
    results: list[ToolResult] = []
    retry_counts: dict[str, int] = {}
    for tool_name in TOOL_ORDER:
        if strategy == "DYNAMIC_CONTRACT_AWARE_RETRY":
            result, retry_count = execute_tool_with_bounded_retry(
                tool_name,
                dataset_root,
                manifest,
                contract,
                include_optional=False,
                runner=runner,
                batch_fingerprint=fingerprint,
                configured_max_retries=1,
            )
        elif strategy == "FIXED_UNIFORM_BOUNDED_RETRY":
            result, retry_count = _execute_tool_with_uniform_bounded_retry(
                tool_name,
                dataset_root,
                manifest,
                contract,
                runner=runner,
                batch_fingerprint=fingerprint,
                configured_max_retries=1,
            )
        else:
            result = execute_tool_gateway(
                tool_name,
                dataset_root,
                manifest,
                contract,
                runner=runner,
                batch_fingerprint=fingerprint,
            )
            runner.bind_gateway_response(result)
            retry_count = 0
        results.append(result)
        retry_counts[tool_name] = retry_count
    findings, traces, metrics = _aggregate(manifest, results)
    scored_findings = [
        item for item in findings if item.code in SCORED_POLICY_FINDING_CODES
    ]
    gate = apply_policy(
        manifest,
        contract,
        scored_findings,
        traces,
        metrics,
        scenario_profile=ScenarioProfile.GENERIC,
        run_id=f"public-{strategy.lower()}-{spec.episode_id}",
    )
    return {
        "execution_strategy": strategy,
        "gate": gate,
        "traces": traces,
        "findings": findings,
        "scored_findings": scored_findings,
        "out_of_scope_finding_count": len(findings) - len(scored_findings),
        "out_of_scope_findings": [
            item for item in findings if item.code not in SCORED_POLICY_FINDING_CODES
        ],
        "metrics": metrics,
        "retry_counts": retry_counts,
        "runner_calls": dict(sorted(runner.calls.items())),
        "physical_attempts": runner.attempts,
        "physical_tool_call_count": sum(runner.calls.values()),
        "batch_fingerprint_sha256": fingerprint,
        "latency_ms": None,
    }


def _build_execution_evidence(execution: dict[str, Any]) -> dict[str, Any]:
    strategy = execution["execution_strategy"]
    governance_strategy = EXECUTION_TO_GOVERNANCE_STRATEGY[strategy]
    gate_body = execution["gate"].model_dump(mode="json")
    all_findings = [item.model_dump(mode="json") for item in execution["findings"]]
    scored_findings = [
        item.model_dump(mode="json") for item in execution["scored_findings"]
    ]
    out_of_scope_findings = [
        item.model_dump(mode="json") for item in execution["out_of_scope_findings"]
    ]
    stable = {
        "schema_version": EXECUTION_EVIDENCE_SCHEMA_VERSION,
        "execution_strategy": strategy,
        "governance_strategy": governance_strategy,
        "configured_max_retries_per_tool": (
            0 if strategy == "FIXED_SINGLE_ATTEMPT" else 1
        ),
        "retry_policy": (
            "NEVER_RETRY"
            if strategy == "FIXED_SINGLE_ATTEMPT"
            else "RETRY_ALL_TYPED_ERRORS"
            if strategy == "FIXED_UNIFORM_BOUNDED_RETRY"
            else "RETRY_TIMEOUT_OR_CONNECTION_ONLY"
        ),
        "gate": gate_body,
        "gate_sha256": _digest("gate-decision", gate_body),
        "tool_traces": [item.model_dump(mode="json") for item in execution["traces"]],
        "all_findings": all_findings,
        "scored_findings": scored_findings,
        "out_of_scope_findings": out_of_scope_findings,
        "metrics": _json_value(execution["metrics"]),
        "retry_counts": dict(sorted(execution["retry_counts"].items())),
        "runner_calls": dict(sorted(execution["runner_calls"].items())),
        "physical_tool_call_count": execution["physical_tool_call_count"],
        "physical_attempts": execution["physical_attempts"],
        "batch_fingerprint_sha256": execution["batch_fingerprint_sha256"],
        "wall_clock_latency_ms": None,
        "latency_comparison_status": LATENCY_COMPARISON_STATUS,
        "actual_model_call_count": 0,
        "actual_model_token_count": 0,
        "host_paths_serialized": False,
    }
    return {
        **stable,
        "execution_receipt_sha256": _digest("strategy-execution-evidence", stable),
    }


def _build_episode_evidence(
    *,
    spec: _EpisodeSpec,
    manifest: BatchManifest,
    contract: BatchContract,
    truth: Any,
    executions: list[dict[str, Any]],
) -> dict[str, Any]:
    manifest_body = manifest.model_dump(mode="json")
    contract_body = contract.model_dump(mode="json")
    stable = {
        "schema_version": EPISODE_EVIDENCE_SCHEMA_VERSION,
        "episode_id": spec.episode_id,
        "source_scope": PUBLIC_SCOPE,
        "input_manifest": manifest_body,
        "input_manifest_sha256": _digest("input-manifest", manifest_body),
        "input_contract": contract_body,
        "input_contract_sha256": _digest("input-contract", contract_body),
        "truth": _json_value(truth),
        "truth_disposition": spec.truth_disposition,
        "governance_truth_scope": "EXACT_CROSS_SPLIT_DUPLICATE_ONLY",
        "source_samples": {
            "primary_source_sample_id": spec.primary.source_sample_id,
            "primary_image_sha256": spec.primary.image_sha256,
            "secondary_source_sample_id": (
                spec.secondary.source_sample_id if spec.secondary else None
            ),
            "secondary_image_sha256": (
                spec.secondary.image_sha256 if spec.secondary else None
            ),
        },
        "fault_injection": {
            "fault_mode": spec.fault_mode,
            "target_tool": spec.target_tool,
            "injection_scope": "EVALUATOR_ONLY_WITHHELD_FROM_AGENT_AND_POLICY",
            "persistent": spec.fault_mode
            in {
                "PERMISSION_DENIED_PERSISTENT",
                "TOOL_RESPONSE_INTEGRITY_PERSISTENT",
            },
        },
        "required_evidence_gap_ids": _required_gaps(spec),
        "executions": {
            item["execution_strategy"]: _build_execution_evidence(item)
            for item in executions
        },
        "host_paths_serialized": False,
    }
    return {
        **stable,
        "episode_receipt_sha256": _digest("public-runtime-episode-evidence", stable),
    }


def _require_exact_keys(
    value: dict[str, Any], expected: set[str], *, label: str
) -> None:
    if set(value) != expected:
        raise ValueError(f"{label} fields drifted")


def _source_index_batch_fingerprint(
    manifest: BatchManifest,
    source_index: VisaSourceIndex,
) -> str:
    """Rebuild the tool-layer batch fingerprint without reading image bytes."""

    digests_by_path: dict[str, str] = {}
    for sample in source_index.samples:
        existing = digests_by_path.setdefault(
            sample.image_relative_path,
            sample.image_sha256,
        )
        if existing != sample.image_sha256:
            raise ValueError("source index maps one image path to multiple digests")
        if sample.mask_relative_path is not None and sample.mask_sha256 is not None:
            existing = digests_by_path.setdefault(
                sample.mask_relative_path,
                sample.mask_sha256,
            )
            if existing != sample.mask_sha256:
                raise ValueError("source index maps one mask path to multiple digests")
    references = {
        path
        for sample in manifest.samples
        for path in (sample.relative_path, sample.annotation_path)
        if path is not None
    }
    files: list[dict[str, str | bool]] = []
    for relative_path in sorted(references):
        digest = digests_by_path.get(relative_path)
        if digest is None:
            raise ValueError("manifest asset is absent from the detached source index")
        files.append(
            {
                "relative_path": relative_path,
                "exists": True,
                "sha256": digest,
            }
        )
    encoded = json.dumps(
        {
            "manifest": manifest.model_dump(mode="json"),
            "files": files,
        },
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _tool_result_from_evidence_body(
    body: object,
    *,
    label: str,
) -> ToolResult:
    if not isinstance(body, list) or len(body) != 3:
        raise ValueError(f"{label} must contain Finding[], ToolTrace, and metrics")
    finding_body, trace_body, metrics = body
    if not isinstance(finding_body, list) or not isinstance(metrics, dict):
        raise ValueError(f"{label} has malformed findings or metrics")
    findings = [Finding.model_validate(item) for item in finding_body]
    trace = ToolTrace.model_validate(trace_body)
    return findings, trace, cast(dict[str, MetricValue], metrics)


def _serialized_result_digest_matches(
    tool_name: str,
    findings: list[Finding],
    trace: ToolTrace,
    metrics: dict[str, MetricValue],
) -> bool:
    """Replay the legacy result digest after JCS normalized 0.0 to 0."""

    metric_prefix = next(
        str(item["metric_prefix"])
        for item in tool_catalog(include_optional=False)
        if item["name"] == tool_name
    )
    prefix = f"{metric_prefix}_" if metric_prefix else ""
    float_metric_names = {
        "image_quality": {
            "mean_luma_min",
            "mean_luma_max",
            "sharpness_min",
            "sharpness_max",
        },
        "annotation_integrity": {
            "mask_fraction_min",
            "mask_fraction_max",
        },
    }.get(tool_name, set())
    returned_to_raw = {
        (
            raw_key
            if not prefix or raw_key.startswith(prefix)
            else f"{prefix}{raw_key}"
        ): raw_key
        for raw_key in RAW_TOOL_METRIC_NAMES[tool_name]
    }
    if set(metrics) != set(returned_to_raw):
        return False
    raw_keys: list[str] = []
    value_choices: list[tuple[MetricValue, ...]] = []
    returned_keys = sorted(metrics)
    for key in returned_keys:
        raw_key = returned_to_raw[key]
        raw_keys.append(raw_key)
        value = metrics[key]
        if (
            raw_key in float_metric_names
            and isinstance(value, int)
            and not isinstance(value, bool)
        ):
            value_choices.append((value, float(value)))
        else:
            value_choices.append((value,))
    finding_payload = [item.model_dump(mode="json") for item in findings]
    for raw_values in product(*value_choices):
        raw_metrics = dict(zip(raw_keys, raw_values, strict=True))
        encoded = json.dumps(
            {"findings": finding_payload, "metrics": raw_metrics},
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        ).encode("utf-8")
        if hmac.compare_digest(
            hashlib.sha256(encoded).hexdigest(), trace.result_sha256
        ):
            return True
    return False


def _validate_physical_attempt(
    attempt: dict[str, Any],
    *,
    fault_mode: FaultMode,
    target_tool: str | None,
    manifest: BatchManifest,
    contract: BatchContract,
    expected_request_sha256: str,
) -> ToolResult:
    _require_exact_keys(
        attempt,
        {
            "sequence",
            "tool_name",
            "tool_attempt",
            "configured_fault_mode",
            "configured_target_tool",
            "fault_applied",
            "outcome",
            "response",
            "gateway_response",
            "exception_type",
            "exception_message",
            "host_paths_serialized",
            "attempt_sha256",
        },
        label="physical tool attempt",
    )
    stable = {key: value for key, value in attempt.items() if key != "attempt_sha256"}
    if attempt.get("attempt_sha256") != _digest("physical-tool-attempt", stable):
        raise ValueError("physical tool attempt seal mismatch")
    if attempt.get("host_paths_serialized") is not False:
        raise ValueError("physical tool attempt exposed host paths")
    if (
        attempt.get("configured_fault_mode") != fault_mode
        or attempt.get("configured_target_tool") != target_tool
        or attempt.get("tool_name") not in TOOL_ORDER
    ):
        raise ValueError("physical tool attempt fault binding drifted")
    outcome = attempt.get("outcome")
    if outcome == "TOOL_RESPONSE":
        if (
            attempt.get("response") is None
            or attempt.get("exception_type") is not None
            or attempt.get("exception_message") is not None
            or attempt.get("fault_applied") is not False
        ):
            raise ValueError("successful physical tool attempt is malformed")
    elif outcome == "INJECTED_EXCEPTION":
        if (
            attempt.get("response") is not None
            or not isinstance(attempt.get("exception_type"), str)
            or not isinstance(attempt.get("exception_message"), str)
            or attempt.get("fault_applied") is not True
        ):
            raise ValueError("exception physical tool attempt is malformed")
    elif outcome == "MALFORMED_RESPONSE":
        if (
            attempt.get("response") is None
            or attempt.get("exception_type") is not None
            or attempt.get("exception_message") is not None
            or attempt.get("fault_applied") is not True
        ):
            raise ValueError("malformed-response physical attempt is malformed")
    else:
        raise ValueError("physical tool attempt outcome drifted")
    is_target = attempt.get("tool_name") == target_tool
    tool_attempt = attempt.get("tool_attempt")
    if fault_mode == "NONE" or not is_target:
        expected_fault = False
        expected_outcome = "TOOL_RESPONSE"
        expected_exception = None
    elif fault_mode == "TRANSIENT_TIMEOUT_ONCE" and tool_attempt == 1:
        expected_fault = True
        expected_outcome = "INJECTED_EXCEPTION"
        expected_exception = "TimeoutError"
    elif fault_mode == "TRANSIENT_TIMEOUT_ONCE":
        expected_fault = False
        expected_outcome = "TOOL_RESPONSE"
        expected_exception = None
    elif fault_mode == "PERMISSION_DENIED_PERSISTENT":
        expected_fault = True
        expected_outcome = "INJECTED_EXCEPTION"
        expected_exception = "PermissionError"
    else:
        expected_fault = True
        expected_outcome = "MALFORMED_RESPONSE"
        expected_exception = None
    if (
        attempt.get("fault_applied") is not expected_fault
        or outcome != expected_outcome
        or attempt.get("exception_type") != expected_exception
    ):
        raise ValueError("physical tool attempt differs from injected fault protocol")

    tool_name = str(attempt["tool_name"])
    gateway_result = _tool_result_from_evidence_body(
        attempt.get("gateway_response"),
        label="physical attempt gateway response",
    )
    gateway_findings, gateway_trace, gateway_metrics = gateway_result
    if (
        gateway_trace.tool != tool_name
        or gateway_trace.input_sha256 != expected_request_sha256
    ):
        raise ValueError("physical attempt gateway response lost request binding")
    verification_root = Path(__file__).resolve().parent
    if outcome == "TOOL_RESPONSE":
        raw_result = _tool_result_from_evidence_body(
            attempt.get("response"),
            label="successful physical response",
        )
        response_error = validate_tool_response(
            tool_name,
            verification_root,
            manifest,
            contract,
            raw_result,
            expected_request_sha256=expected_request_sha256,
        )
        serialized_digest_reconciles = (
            response_error == f"result digest mismatch for {tool_name}"
            and _serialized_result_digest_matches(
                tool_name,
                raw_result[0],
                raw_result[1],
                raw_result[2],
            )
        )
        if response_error is not None and not serialized_digest_reconciles:
            raise ValueError(
                "successful physical response failed semantic validation: "
                f"{response_error}"
            )
        expected_gateway_result = raw_result
    elif outcome == "INJECTED_EXCEPTION":
        expected_gateway_result = (
            [],
            build_tool_error_trace(
                tool_name,
                f"{attempt['exception_type']}: tool execution failed",
                input_sha256=expected_request_sha256,
            ),
            {},
        )
    else:
        response_error = validate_tool_response(
            tool_name,
            verification_root,
            manifest,
            contract,
            attempt.get("response"),
            expected_request_sha256=expected_request_sha256,
        )
        if response_error is None:
            raise ValueError("malformed physical response unexpectedly validated")
        expected_gateway_result = (
            [],
            build_tool_error_trace(
                tool_name,
                f"ToolResponseIntegrityError: {response_error}",
                input_sha256=expected_request_sha256,
            ),
            {},
        )
    if _canonical_bytes(gateway_result) != _canonical_bytes(expected_gateway_result):
        raise ValueError("physical attempt gateway response is not raw-call-derived")
    if gateway_trace.finding_ids != [item.finding_id for item in gateway_findings]:
        raise ValueError("physical attempt gateway findings lost trace linkage")
    if not isinstance(gateway_metrics, dict):
        raise ValueError("physical attempt gateway metrics are malformed")
    return gateway_result


def _validate_execution_evidence(
    execution: dict[str, Any],
    *,
    episode_id: str,
    manifest: BatchManifest,
    contract: BatchContract,
    fault_mode: FaultMode,
    target_tool: str | None,
    expected_batch_fingerprint_sha256: str,
) -> None:
    _require_exact_keys(
        execution,
        {
            "schema_version",
            "execution_strategy",
            "governance_strategy",
            "configured_max_retries_per_tool",
            "retry_policy",
            "gate",
            "gate_sha256",
            "tool_traces",
            "all_findings",
            "scored_findings",
            "out_of_scope_findings",
            "metrics",
            "retry_counts",
            "runner_calls",
            "physical_tool_call_count",
            "physical_attempts",
            "batch_fingerprint_sha256",
            "wall_clock_latency_ms",
            "latency_comparison_status",
            "actual_model_call_count",
            "actual_model_token_count",
            "host_paths_serialized",
            "execution_receipt_sha256",
        },
        label="strategy execution evidence",
    )
    stable = {
        key: value
        for key, value in execution.items()
        if key != "execution_receipt_sha256"
    }
    if execution.get("execution_receipt_sha256") != _digest(
        "strategy-execution-evidence", stable
    ):
        raise ValueError("strategy execution evidence seal mismatch")
    strategy = execution.get("execution_strategy")
    if strategy not in EXECUTION_TO_GOVERNANCE_STRATEGY:
        raise ValueError("strategy execution identity drifted")
    if (
        execution.get("governance_strategy")
        != EXECUTION_TO_GOVERNANCE_STRATEGY[strategy]
    ):
        raise ValueError("strategy governance identity drifted")
    expected_budget = 0 if strategy == "FIXED_SINGLE_ATTEMPT" else 1
    expected_retry_policy = (
        "NEVER_RETRY"
        if strategy == "FIXED_SINGLE_ATTEMPT"
        else "RETRY_ALL_TYPED_ERRORS"
        if strategy == "FIXED_UNIFORM_BOUNDED_RETRY"
        else "RETRY_TIMEOUT_OR_CONNECTION_ONLY"
    )
    if (
        execution.get("configured_max_retries_per_tool") != expected_budget
        or execution.get("retry_policy") != expected_retry_policy
        or execution.get("latency_comparison_status") != LATENCY_COMPARISON_STATUS
        or execution.get("actual_model_call_count") != 0
        or execution.get("actual_model_token_count") != 0
        or execution.get("host_paths_serialized") is not False
    ):
        raise ValueError("strategy execution contract drifted")
    if execution.get("batch_fingerprint_sha256") != (expected_batch_fingerprint_sha256):
        raise ValueError("strategy batch fingerprint differs from detached source")
    if execution.get("wall_clock_latency_ms") is not None:
        raise ValueError("strategy latency must remain null and NOT_MEASURED")

    traces = [ToolTrace.model_validate(item) for item in execution["tool_traces"]]
    if [item.tool for item in traces] != list(TOOL_ORDER):
        raise ValueError("strategy execution ToolTrace order drifted")
    all_findings = [Finding.model_validate(item) for item in execution["all_findings"]]
    scored = [Finding.model_validate(item) for item in execution["scored_findings"]]
    out_of_scope = [
        Finding.model_validate(item) for item in execution["out_of_scope_findings"]
    ]
    if any(item.code not in SCORED_POLICY_FINDING_CODES for item in scored) or any(
        item.code in SCORED_POLICY_FINDING_CODES for item in out_of_scope
    ):
        raise ValueError("strategy finding scope partition drifted")

    def finding_map(items: list[Finding]) -> dict[str, dict[str, Any]]:
        result = {item.finding_id: item.model_dump(mode="json") for item in items}
        if len(result) != len(items):
            raise ValueError("strategy finding IDs are not unique")
        return result

    if finding_map(all_findings) != {
        **finding_map(scored),
        **finding_map(out_of_scope),
    }:
        raise ValueError("strategy all/scored/out-of-scope findings do not reconcile")
    metrics = execution.get("metrics")
    if not isinstance(metrics, dict):
        raise ValueError("strategy aggregate metrics are malformed")
    gate = GateResult.model_validate(execution["gate"])
    gate_body = gate.model_dump(mode="json")
    if execution.get("gate_sha256") != _digest("gate-decision", gate_body):
        raise ValueError("strategy Gate seal mismatch")
    expected_run_id = f"public-{str(strategy).lower()}-{episode_id}"
    if gate.run_id != expected_run_id:
        raise ValueError("strategy Gate run ID drifted from execution identity")

    retry_counts = execution.get("retry_counts")
    runner_calls = execution.get("runner_calls")
    attempts = execution.get("physical_attempts")
    if (
        not isinstance(retry_counts, dict)
        or set(retry_counts) != set(TOOL_ORDER)
        or not isinstance(runner_calls, dict)
        or set(runner_calls) != set(TOOL_ORDER)
        or not isinstance(attempts, list)
    ):
        raise ValueError("strategy retry evidence is malformed")
    per_tool_seen = {tool: 0 for tool in TOOL_ORDER}
    final_results: dict[str, ToolResult] = {}
    verification_root = Path(__file__).resolve().parent
    request_sha256_by_tool = {
        tool: build_tool_request_sha256(
            tool,
            verification_root,
            manifest,
            contract,
            batch_fingerprint=expected_batch_fingerprint_sha256,
        )
        for tool in TOOL_ORDER
    }
    for sequence, attempt in enumerate(attempts, start=1):
        if not isinstance(attempt, dict) or attempt.get("sequence") != sequence:
            raise ValueError("physical tool attempt sequence drifted")
        attempt_tool = attempt.get("tool_name")
        if attempt_tool not in request_sha256_by_tool:
            raise ValueError("physical tool attempt names an unknown tool")
        attempt_result = _validate_physical_attempt(
            attempt,
            fault_mode=fault_mode,
            target_tool=target_tool,
            manifest=manifest,
            contract=contract,
            expected_request_sha256=request_sha256_by_tool[str(attempt_tool)],
        )
        tool_name = attempt["tool_name"]
        per_tool_seen[tool_name] += 1
        final_results[tool_name] = attempt_result
        if attempt.get("tool_attempt") != per_tool_seen[tool_name]:
            raise ValueError("physical per-tool attempt sequence drifted")
    if runner_calls != per_tool_seen or execution.get(
        "physical_tool_call_count"
    ) != len(attempts):
        raise ValueError("physical tool call counts do not reconcile")
    expected_retries = {
        tool: max(0, int(runner_calls[tool]) - 1) for tool in TOOL_ORDER
    }
    if retry_counts != expected_retries:
        raise ValueError("strategy retry counts do not reconcile with attempts")
    expected_target_retries = 0
    if target_tool is not None:
        if strategy == "FIXED_UNIFORM_BOUNDED_RETRY":
            expected_target_retries = 1
        elif (
            strategy == "DYNAMIC_CONTRACT_AWARE_RETRY"
            and fault_mode == "TRANSIENT_TIMEOUT_ONCE"
        ):
            expected_target_retries = 1
    if any(
        count != (expected_target_retries if tool == target_tool else 0)
        for tool, count in retry_counts.items()
    ):
        raise ValueError("strategy retry behavior differs from the frozen protocol")

    if set(final_results) != set(TOOL_ORDER):
        raise ValueError("strategy attempts do not yield one final result per tool")
    rebuilt_findings, rebuilt_traces, rebuilt_metrics = _aggregate(
        manifest,
        [final_results[tool] for tool in TOOL_ORDER],
    )
    rebuilt_scored = [
        item for item in rebuilt_findings if item.code in SCORED_POLICY_FINDING_CODES
    ]
    rebuilt_out_of_scope = [
        item
        for item in rebuilt_findings
        if item.code not in SCORED_POLICY_FINDING_CODES
    ]
    evidence_bodies = {
        "tool_traces": [item.model_dump(mode="json") for item in traces],
        "all_findings": [item.model_dump(mode="json") for item in all_findings],
        "scored_findings": [item.model_dump(mode="json") for item in scored],
        "out_of_scope_findings": [
            item.model_dump(mode="json") for item in out_of_scope
        ],
        "metrics": metrics,
    }
    rebuilt_bodies = {
        "tool_traces": [item.model_dump(mode="json") for item in rebuilt_traces],
        "all_findings": [item.model_dump(mode="json") for item in rebuilt_findings],
        "scored_findings": [item.model_dump(mode="json") for item in rebuilt_scored],
        "out_of_scope_findings": [
            item.model_dump(mode="json") for item in rebuilt_out_of_scope
        ],
        "metrics": rebuilt_metrics,
    }
    if _canonical_bytes(evidence_bodies) != _canonical_bytes(rebuilt_bodies):
        raise ValueError(
            "strategy summaries are not derived from physical attempt responses"
        )
    rebuilt_gate = apply_policy(
        manifest,
        contract,
        rebuilt_scored,
        rebuilt_traces,
        rebuilt_metrics,
        scenario_profile=ScenarioProfile.GENERIC,
        run_id=expected_run_id,
    )
    if _canonical_bytes(rebuilt_gate) != _canonical_bytes(gate):
        raise ValueError("strategy Gate is not physical-attempt-derived")


def _validate_episode_evidence(
    episode: dict[str, Any],
    *,
    source_index: VisaSourceIndex,
) -> None:
    _require_exact_keys(
        episode,
        {
            "schema_version",
            "episode_id",
            "source_scope",
            "input_manifest",
            "input_manifest_sha256",
            "input_contract",
            "input_contract_sha256",
            "truth",
            "truth_disposition",
            "governance_truth_scope",
            "source_samples",
            "fault_injection",
            "required_evidence_gap_ids",
            "executions",
            "host_paths_serialized",
            "episode_receipt_sha256",
        },
        label="public runtime episode evidence",
    )
    stable = {
        key: value for key, value in episode.items() if key != "episode_receipt_sha256"
    }
    if episode.get("episode_receipt_sha256") != _digest(
        "public-runtime-episode-evidence", stable
    ):
        raise ValueError("public runtime episode evidence seal mismatch")
    if (
        episode.get("schema_version") != EPISODE_EVIDENCE_SCHEMA_VERSION
        or episode.get("source_scope") != PUBLIC_SCOPE
        or episode.get("governance_truth_scope") != "EXACT_CROSS_SPLIT_DUPLICATE_ONLY"
        or episode.get("host_paths_serialized") is not False
    ):
        raise ValueError("public runtime episode evidence contract drifted")
    manifest = BatchManifest.model_validate(episode["input_manifest"])
    contract = BatchContract.model_validate(episode["input_contract"])
    if episode.get("input_manifest_sha256") != _digest(
        "input-manifest", manifest.model_dump(mode="json")
    ) or episode.get("input_contract_sha256") != _digest(
        "input-contract", contract.model_dump(mode="json")
    ):
        raise ValueError("public runtime episode input body binding drifted")
    if manifest.batch_id != episode.get("episode_id") or len(manifest.samples) != 2:
        raise ValueError("public runtime episode manifest grain drifted")
    expected_batch_fingerprint = _source_index_batch_fingerprint(
        manifest,
        source_index,
    )
    truth = GovernanceTruthBindingV2.model_validate(episode["truth"])
    truth_disposition = episode.get("truth_disposition")
    if truth.status != "ADJUDICATED" or truth.disposition != truth_disposition:
        raise ValueError("public runtime episode truth body drifted")
    fault = episode.get("fault_injection")
    if not isinstance(fault, dict):
        raise ValueError("public runtime episode fault body is missing")
    _require_exact_keys(
        fault,
        {"fault_mode", "target_tool", "injection_scope", "persistent"},
        label="public runtime fault injection",
    )
    fault_mode = fault.get("fault_mode")
    if fault_mode not in {
        "NONE",
        "TRANSIENT_TIMEOUT_ONCE",
        "PERMISSION_DENIED_PERSISTENT",
        "TOOL_RESPONSE_INTEGRITY_PERSISTENT",
    }:
        raise ValueError("public runtime episode fault mode drifted")
    fault_mode = cast(FaultMode, fault_mode)
    target_tool = fault.get("target_tool")
    if (
        fault.get("injection_scope") != "EVALUATOR_ONLY_WITHHELD_FROM_AGENT_AND_POLICY"
        or fault.get("persistent")
        != (
            fault_mode
            in {
                "PERMISSION_DENIED_PERSISTENT",
                "TOOL_RESPONSE_INTEGRITY_PERSISTENT",
            }
        )
        or (fault_mode == "NONE" and target_tool is not None)
        or (fault_mode != "NONE" and target_tool not in TOOL_ORDER)
    ):
        raise ValueError("public runtime episode fault contract drifted")
    if episode.get("required_evidence_gap_ids") != _required_gaps_for(
        truth_disposition, fault_mode
    ):
        raise ValueError("public runtime episode required-gap contract drifted")
    executions = episode.get("executions")
    if not isinstance(executions, dict) or set(executions) != set(
        EXECUTION_TO_GOVERNANCE_STRATEGY
    ):
        raise ValueError("public runtime episode strategy set drifted")
    for strategy, execution in executions.items():
        if (
            not isinstance(execution, dict)
            or execution.get("execution_strategy") != strategy
        ):
            raise ValueError("public runtime episode execution key drifted")
        _validate_execution_evidence(
            execution,
            episode_id=str(episode["episode_id"]),
            manifest=manifest,
            contract=contract,
            fault_mode=fault_mode,
            target_tool=target_tool,
            expected_batch_fingerprint_sha256=expected_batch_fingerprint,
        )

    source_samples = episode.get("source_samples")
    if not isinstance(source_samples, dict):
        raise ValueError("public runtime episode source sample binding is missing")
    _require_exact_keys(
        source_samples,
        {
            "primary_source_sample_id",
            "primary_image_sha256",
            "secondary_source_sample_id",
            "secondary_image_sha256",
        },
        label="public runtime source sample binding",
    )
    indexed = {item.source_sample_id: item for item in source_index.samples}
    primary = indexed.get(source_samples["primary_source_sample_id"])
    secondary_id = source_samples["secondary_source_sample_id"]
    secondary = indexed.get(secondary_id) if secondary_id else None
    if (
        primary is None
        or primary.image_sha256 != source_samples["primary_image_sha256"]
    ):
        raise ValueError("public runtime primary source-index binding drifted")
    manifest_sources = [item.source_sample_id for item in manifest.samples]
    manifest_paths = [item.relative_path for item in manifest.samples]
    if truth_disposition == "RELEASE_ALLOWED":
        if (
            secondary is None
            or secondary.image_sha256 != source_samples["secondary_image_sha256"]
            or secondary.image_sha256 == primary.image_sha256
            or manifest_sources
            != [primary.source_sample_id, secondary.source_sample_id]
            or manifest_paths
            != [primary.image_relative_path, secondary.image_relative_path]
        ):
            raise ValueError("public runtime clean-control source binding drifted")
    elif (
        secondary_id is not None
        or source_samples["secondary_image_sha256"] is not None
        or manifest_sources != [primary.source_sample_id, primary.source_sample_id]
        or manifest_paths != [primary.image_relative_path, primary.image_relative_path]
    ):
        raise ValueError("public runtime exact-duplicate source binding drifted")


def _system_disposition(
    decision: GateDecision,
) -> Literal["RELEASED", "BLOCKED", "HUMAN_REVIEW"]:
    if decision is GateDecision.PASS:
        return "RELEASED"
    if decision is GateDecision.DEFER:
        return "HUMAN_REVIEW"
    return "BLOCKED"


def _required_gaps_for(
    truth_disposition: Literal["RELEASE_ALLOWED", "BLOCK_REQUIRED"],
    fault_mode: FaultMode,
) -> list[str]:
    gaps: list[str] = []
    if truth_disposition == "BLOCK_REQUIRED":
        gaps.append("cross_split_duplicate_measurement")
    if fault_mode == "TRANSIENT_TIMEOUT_ONCE":
        gaps.extend(("complete_required_tool_set", "transient_tool_recovery"))
    elif fault_mode == "PERMISSION_DENIED_PERSISTENT":
        gaps.extend(
            (
                "permission_fault_fail_closed",
                "non_retryable_retry_suppression",
            )
        )
    elif fault_mode == "TOOL_RESPONSE_INTEGRITY_PERSISTENT":
        gaps.extend(
            (
                "tool_response_integrity_fail_closed",
                "non_retryable_retry_suppression",
            )
        )
    return sorted(gaps)


def _required_gaps(spec: _EpisodeSpec) -> list[str]:
    return _required_gaps_for(spec.truth_disposition, spec.fault_mode)


def _observation(
    episode_evidence: dict[str, Any],
    execution_strategy: ExecutionStrategy,
) -> GovernanceStrategyObservationV2:
    execution = episode_evidence["executions"][execution_strategy]
    strategy = execution["governance_strategy"]
    findings = [Finding.model_validate(item) for item in execution["all_findings"]]
    traces = [ToolTrace.model_validate(item) for item in execution["tool_traces"]]
    retries = execution["retry_counts"]
    required = list(episode_evidence["required_evidence_gap_ids"])
    fault_mode = episode_evidence["fault_injection"]["fault_mode"]
    finding_codes = {item.code for item in findings}
    all_tools_ok = all(item.status == "ok" for item in traces)
    retry_count = sum(retries.values())
    detected: set[str] = set()
    covered: set[str] = set()
    if "CROSS_SPLIT_EXACT_DUPLICATE" in finding_codes:
        detected.add("cross_split_duplicate_measurement")
        covered.add("cross_split_duplicate_measurement")
    if fault_mode == "TRANSIENT_TIMEOUT_ONCE":
        detected.update(("complete_required_tool_set", "transient_tool_recovery"))
        if all_tools_ok:
            covered.add("complete_required_tool_set")
        if retry_count > 0 and all_tools_ok:
            covered.add("transient_tool_recovery")
    elif fault_mode in {
        "PERMISSION_DENIED_PERSISTENT",
        "TOOL_RESPONSE_INTEGRITY_PERSISTENT",
    }:
        containment_gap = (
            "permission_fault_fail_closed"
            if fault_mode == "PERMISSION_DENIED_PERSISTENT"
            else "tool_response_integrity_fail_closed"
        )
        detected.update((containment_gap, "non_retryable_retry_suppression"))
        if _system_disposition(
            GateResult.model_validate(execution["gate"]).decision
        ) != ("RELEASED"):
            covered.add(containment_gap)
        if retry_count == 0:
            covered.add("non_retryable_retry_suppression")
    covered &= set(required)
    detected &= set(required)
    gate = GateResult.model_validate(execution["gate"])
    return GovernanceStrategyObservationV2(
        strategy=strategy,
        system_disposition=_system_disposition(gate.decision),
        decision_receipt_sha256=execution["gate_sha256"],
        trace_receipt_sha256=execution["execution_receipt_sha256"],
        replan_triggered=False,
        replan_count=0,
        selected_worker_count=0,
        selected_worker_ids=[],
        worker_selection_evidence_status="NOT_APPLICABLE",
        detected_evidence_gap_ids=sorted(detected),
        covered_required_gap_ids=sorted(covered),
        unresolved_required_gap_ids=sorted(set(required) - covered),
        tool_call_count=int(execution["physical_tool_call_count"]),
        redundant_tool_call_count=(
            retry_count
            if strategy == "FIXED_EXHAUSTIVE_PIPELINE"
            and fault_mode
            in {
                "PERMISSION_DENIED_PERSISTENT",
                "TOOL_RESPONSE_INTEGRITY_PERSISTENT",
            }
            else 0
        ),
        latency_ms=None,
        actual_model_call_count=0,
        actual_model_token_count=0,
        provider_billed_api_cost_cny=0.0,
    )


def _runtime_summary(
    fault_modes: list[FaultMode],
    primary_episodes: list[PairedGovernanceEpisodeV2],
    reference_episodes: list[PairedGovernanceEpisodeV2],
) -> dict[str, Any]:
    transient = [
        item
        for item in primary_episodes
        if "transient_tool_recovery" in item.required_evidence_gap_ids
    ]
    non_retryable = [
        item
        for item in primary_episodes
        if "non_retryable_retry_suppression" in item.required_evidence_gap_ids
    ]

    def governance_correct(item: PairedGovernanceEpisodeV2, *, dynamic: bool) -> bool:
        observation = item.dynamic_observation if dynamic else item.fixed_observation
        if item.truth.disposition == "RELEASE_ALLOWED":
            return observation.system_disposition == "RELEASED"
        return observation.system_disposition != "RELEASED"

    fault_mode_counts = {
        mode: sum(fault_mode == mode for fault_mode in fault_modes)
        for mode in (
            "NONE",
            "TRANSIENT_TIMEOUT_ONCE",
            "PERMISSION_DENIED_PERSISTENT",
            "TOOL_RESPONSE_INTEGRITY_PERSISTENT",
        )
    }

    return {
        "episode_count": len(primary_episodes),
        "transient_fault_episode_count": len(transient),
        "non_retryable_fault_episode_count": len(non_retryable),
        "fault_mode_counts": fault_mode_counts,
        "single_attempt_governance_correct_count": sum(
            governance_correct(item, dynamic=False) for item in reference_episodes
        ),
        "fixed_uniform_governance_correct_count": sum(
            governance_correct(item, dynamic=False) for item in primary_episodes
        ),
        "dynamic_governance_correct_count": sum(
            governance_correct(item, dynamic=True) for item in primary_episodes
        ),
        "single_attempt_transient_recovery_count": sum(
            "transient_tool_recovery" in item.fixed_observation.covered_required_gap_ids
            for item in reference_episodes
            if "transient_tool_recovery" in item.required_evidence_gap_ids
        ),
        "fixed_uniform_transient_recovery_count": sum(
            "transient_tool_recovery" in item.fixed_observation.covered_required_gap_ids
            for item in transient
        ),
        "dynamic_transient_recovery_count": sum(
            "transient_tool_recovery"
            in item.dynamic_observation.covered_required_gap_ids
            for item in transient
        ),
        "fixed_uniform_non_retryable_retry_count": sum(
            int(item.fixed_observation.redundant_tool_call_count or 0)
            for item in non_retryable
        ),
        "dynamic_non_retryable_retry_count": sum(
            item.dynamic_observation.tool_call_count - len(TOOL_ORDER)
            for item in non_retryable
        ),
        "single_attempt_tool_call_count": sum(
            item.fixed_observation.tool_call_count for item in reference_episodes
        ),
        "fixed_uniform_tool_call_count": sum(
            item.fixed_observation.tool_call_count for item in primary_episodes
        ),
        "dynamic_tool_call_count": sum(
            item.dynamic_observation.tool_call_count for item in primary_episodes
        ),
        "single_attempt_model_call_count": 0,
        "fixed_uniform_model_call_count": 0,
        "dynamic_model_call_count": 0,
        "primary_decision_disposition_match_count": sum(
            item.fixed_observation.system_disposition
            == item.dynamic_observation.system_disposition
            for item in primary_episodes
        ),
        "unsafe_release_count": sum(
            item.truth.disposition == "BLOCK_REQUIRED"
            and observation.system_disposition == "RELEASED"
            for primary, reference in zip(
                primary_episodes, reference_episodes, strict=True
            )
            for item, observation in (
                (reference, reference.fixed_observation),
                (primary, primary.fixed_observation),
                (primary, primary.dynamic_observation),
            )
        ),
    }


def _wilson_95(numerator: int, denominator: int) -> tuple[float | None, float | None]:
    if denominator == 0:
        return None, None
    z = 1.959963984540054
    p = numerator / denominator
    z2 = z * z
    scale = 1 + z2 / denominator
    center = (p + z2 / (2 * denominator)) / scale
    margin = z * sqrt(p * (1 - p) / denominator + z2 / (4 * denominator**2)) / scale
    return max(0.0, center - margin), min(1.0, center + margin)


def _stratified_governance_metrics(
    episode_evidence_records: list[dict[str, Any]],
    primary_episodes: list[PairedGovernanceEpisodeV2],
    reference_episodes: list[PairedGovernanceEpisodeV2],
) -> dict[str, Any]:
    primary_by_id = {item.episode_id: item for item in primary_episodes}
    reference_by_id = {item.episode_id: item for item in reference_episodes}
    rows: list[dict[str, Any]] = []
    strategy_observations = {
        "FIXED_SINGLE_ATTEMPT": lambda episode_id: (
            reference_by_id[episode_id].fixed_observation
        ),
        "FIXED_UNIFORM_BOUNDED_RETRY": lambda episode_id: (
            primary_by_id[episode_id].fixed_observation
        ),
        "DYNAMIC_CONTRACT_AWARE_RETRY": lambda episode_id: (
            primary_by_id[episode_id].dynamic_observation
        ),
    }
    for fault_mode in (
        "NONE",
        "TRANSIENT_TIMEOUT_ONCE",
        "PERMISSION_DENIED_PERSISTENT",
        "TOOL_RESPONSE_INTEGRITY_PERSISTENT",
    ):
        for truth_disposition in ("RELEASE_ALLOWED", "BLOCK_REQUIRED"):
            matching = [
                item
                for item in episode_evidence_records
                if item["fault_injection"]["fault_mode"] == fault_mode
                and item["truth_disposition"] == truth_disposition
            ]
            for execution_strategy, observation_for in strategy_observations.items():
                observations = [
                    observation_for(item["episode_id"]) for item in matching
                ]
                if truth_disposition == "RELEASE_ALLOWED":
                    metric_id = "exact_cross_split_false_block_rate"
                    numerator = sum(
                        item.system_disposition != "RELEASED" for item in observations
                    )
                else:
                    metric_id = "exact_cross_split_false_release_rate"
                    numerator = sum(
                        item.system_disposition == "RELEASED" for item in observations
                    )
                denominator = len(observations)
                lower, upper = _wilson_95(numerator, denominator)
                rows.append(
                    {
                        "fault_mode": fault_mode,
                        "truth_disposition": truth_disposition,
                        "execution_strategy": execution_strategy,
                        "governance_strategy": EXECUTION_TO_GOVERNANCE_STRATEGY[
                            execution_strategy
                        ],
                        "metric_id": metric_id,
                        "status": "MEASURED" if denominator else "NOT_MEASURED",
                        "numerator": numerator,
                        "denominator": denominator,
                        "value": numerator / denominator if denominator else None,
                        "wilson_95_lower": lower,
                        "wilson_95_upper": upper,
                    }
                )
    return {
        "schema_version": "visiondata-gate.public-runtime-stratified-metrics.v1",
        "governance_truth_scope": "EXACT_CROSS_SPLIT_DUPLICATE_ONLY",
        "stratification_axes": ["fault_mode", "truth_disposition", "strategy"],
        "row_count": len(rows),
        "rows": rows,
        "overall_distribution_status": (
            "ARTIFICIALLY_MIXED_INTERVENTION_DISTRIBUTION_NOT_PREVALENCE_WEIGHTED"
        ),
        "overall_rate_use": "DESCRIPTIVE_FOR_THIS_CONFIGURED_MIX_ONLY",
        "latency_comparison_status": LATENCY_COMPARISON_STATUS,
    }


def _strategy_protocols() -> dict[str, Any]:
    return {
        "governance_truth_scope": "EXACT_CROSS_SPLIT_DUPLICATE_ONLY",
        "scored_policy_finding_codes": list(SCORED_POLICY_FINDING_CODES),
        "out_of_scope_natural_findings": (
            "retained as tool evidence but not scored as false blocks"
        ),
        "latency_comparison_status": LATENCY_COMPARISON_STATUS,
        "dynamic_capability_claim": (
            "CONTRACT_AWARE_BOUNDED_RECOVERY_NOT_WORKER_REPLANNING"
        ),
        "primary_comparison": (
            "FIXED_UNIFORM_BOUNDED_RETRY_vs_DYNAMIC_CONTRACT_AWARE_RETRY"
        ),
        "fixed_uniform_bounded_retry": {
            "governance_strategy_id": "FIXED_EXHAUSTIVE_PIPELINE",
            "tool_schedule": list(TOOL_ORDER),
            "retry_rule": "retry every typed tool error",
            "configured_max_retries_per_tool": 1,
            "uses_fault_classification": False,
        },
        "dynamic_contract_aware_retry": {
            "governance_strategy_id": "DYNAMIC_EVIDENCE_AGENT",
            "tool_schedule": list(TOOL_ORDER),
            "retry_rule": "retry only timeout or connection typed errors",
            "configured_max_retries_per_tool": 1,
            "uses_fault_classification": True,
            "worker_replan_claimed": False,
        },
        "single_attempt_reference": {
            "governance_strategy_id": "FIXED_RULE_PIPELINE",
            "tool_schedule": list(TOOL_ORDER),
            "retry_rule": "never retry",
            "role": "SECONDARY_REFERENCE_ONLY",
        },
        "paired_invariants": [
            "same_input_manifest",
            "same_batch_contract",
            "same_programmatic_truth",
            "same_fault_mode_and_target",
            "same_tool_implementations",
            "same_policy_judge",
            "same_configured_retry_budget_for_primary_pair",
        ],
        "non_retryable_faults": [
            "PERMISSION_DENIED_PERSISTENT",
            "TOOL_RESPONSE_INTEGRITY_PERSISTENT",
        ],
    }


def _paired_episode(
    *,
    episode_evidence: dict[str, Any],
    fixed_execution_strategy: Literal[
        "FIXED_SINGLE_ATTEMPT", "FIXED_UNIFORM_BOUNDED_RETRY"
    ],
) -> PairedGovernanceEpisodeV2:
    required = list(episode_evidence["required_evidence_gap_ids"])
    fault_mode = episode_evidence["fault_injection"]["fault_mode"]
    return PairedGovernanceEpisodeV2(
        episode_id=episode_evidence["episode_id"],
        source_scope=PUBLIC_SCOPE,
        input_contract_sha256=episode_evidence["input_contract_sha256"],
        input_manifest_sha256=episode_evidence["input_manifest_sha256"],
        truth=episode_evidence["truth"],
        required_evidence_gap_ids=required,
        conflict_tags=(["runtime_tool_fault"] if fault_mode != "NONE" else []),
        complex_conflict=len(required) >= 2,
        fixed_observation=_observation(episode_evidence, fixed_execution_strategy),
        dynamic_observation=_observation(
            episode_evidence, "DYNAMIC_CONTRACT_AWARE_RETRY"
        ),
    )


def build_public_runtime_retry_benchmark(
    *,
    dataset_root: str | Path,
    source_binding: PublicSourceBinding,
    source_index: VisaSourceIndex,
    clean_case_count: int,
    block_case_count: int,
    transient_fraction: float,
    non_retryable_fraction: float = 0.0,
    evaluated_at: datetime,
) -> tuple[
    dict[str, Any],
    ProgrammaticGovernanceInjectionManifest,
    ProgrammaticGovernanceTruthReceipt,
    dict[str, Any],
]:
    """Execute and seal strong-primary and single-attempt-reference pairs."""

    implementation_receipt = build_public_runtime_implementation_receipt()
    validate_public_runtime_implementation_receipt(implementation_receipt)
    verify_public_source_binding(source_binding)
    verify_visa_source_index(source_index, source_binding=source_binding)
    root = Path(dataset_root).expanduser().resolve(strict=True)
    specs = _build_episode_specs(
        source_index,
        clean_case_count=clean_case_count,
        block_case_count=block_case_count,
        transient_fraction=transient_fraction,
        non_retryable_fraction=non_retryable_fraction,
    )
    programmatic_manifest = build_programmatic_governance_manifest(
        source_index,
        source_binding=source_binding,
        dataset_root=root,
        deterministic_seed=20260829,
        created_at=evaluated_at,
        cases=_programmatic_case_requests(specs),
    )
    truth_receipt = build_programmatic_truth_receipt(programmatic_manifest)
    primary_episodes: list[PairedGovernanceEpisodeV2] = []
    reference_episodes: list[PairedGovernanceEpisodeV2] = []
    episode_evidence_records: list[dict[str, Any]] = []
    protocol_records: list[dict[str, Any]] = []
    for spec in specs:
        manifest, contract = _episode_manifest_and_contract(root, spec)
        single_attempt = _execute_strategy(
            root,
            manifest,
            contract,
            spec,
            strategy="FIXED_SINGLE_ATTEMPT",
        )
        fixed_uniform = _execute_strategy(
            root,
            manifest,
            contract,
            spec,
            strategy="FIXED_UNIFORM_BOUNDED_RETRY",
        )
        dynamic = _execute_strategy(
            root,
            manifest,
            contract,
            spec,
            strategy="DYNAMIC_CONTRACT_AWARE_RETRY",
        )
        truth = governance_truth_binding_from_public_receipt(
            truth_receipt, unit_id=spec.episode_id
        )
        episode_evidence = _build_episode_evidence(
            spec=spec,
            manifest=manifest,
            contract=contract,
            truth=truth,
            executions=[single_attempt, fixed_uniform, dynamic],
        )
        episode_evidence_records.append(episode_evidence)
        primary_episodes.append(
            _paired_episode(
                episode_evidence=episode_evidence,
                fixed_execution_strategy="FIXED_UNIFORM_BOUNDED_RETRY",
            )
        )
        reference_episodes.append(
            _paired_episode(
                episode_evidence=episode_evidence,
                fixed_execution_strategy="FIXED_SINGLE_ATTEMPT",
            )
        )
        source_samples = episode_evidence["source_samples"]
        fault = episode_evidence["fault_injection"]
        protocol_records.append(
            {
                "episode_id": episode_evidence["episode_id"],
                "episode_receipt_sha256": episode_evidence["episode_receipt_sha256"],
                "fault_mode": fault["fault_mode"],
                "target_tool": fault["target_tool"],
                "truth_disposition": episode_evidence["truth_disposition"],
                **source_samples,
            }
        )

    primary_request = CreatePairedStrategyComparisonV2Request(
        comparison_id="visa-public-runtime-retry-v2-fixed-uniform-vs-dynamic",
        source_scope=PUBLIC_SCOPE,
        baseline_strategy="FIXED_EXHAUSTIVE_PIPELINE",
        dataset_identity_sha256=source_index.index_sha256,
        source_benchmark_sha256=truth_receipt.receipt_sha256,
        episodes=primary_episodes,
        evaluated_at=evaluated_at.isoformat(),
        note=(
            "Primary paired VisA public proxy comparison uses equal retry budgets; "
            "truth and faults are withheld from the Agent and Judge inputs."
        ),
    )
    reference_request = CreatePairedStrategyComparisonV2Request(
        comparison_id="visa-public-runtime-retry-v2-single-attempt-reference",
        source_scope=PUBLIC_SCOPE,
        baseline_strategy="FIXED_RULE_PIPELINE",
        dataset_identity_sha256=source_index.index_sha256,
        source_benchmark_sha256=truth_receipt.receipt_sha256,
        episodes=reference_episodes,
        evaluated_at=evaluated_at.isoformat(),
        note=(
            "Secondary single-attempt reference only; it is not the primary baseline "
            "for Agent advantage claims."
        ),
    )
    paired = build_paired_strategy_comparison_v2_report(primary_request)
    reference_paired = build_paired_strategy_comparison_v2_report(reference_request)
    verify_paired_strategy_comparison_v2_report(paired)
    verify_paired_strategy_comparison_v2_report(reference_paired)
    strategy_protocols = _strategy_protocols()
    stratified_metrics = _stratified_governance_metrics(
        episode_evidence_records,
        primary_episodes,
        reference_episodes,
    )
    report_without_seal = {
        "schema_version": SCHEMA_VERSION,
        "benchmark_id": BENCHMARK_ID,
        "status": "PASS",
        "dataset_identity_sha256": source_index.index_sha256,
        "source_binding_sha256": source_binding.binding_sha256,
        "programmatic_manifest_sha256": programmatic_manifest.manifest_sha256,
        "truth_receipt_sha256": truth_receipt.receipt_sha256,
        "governance_truth_scope": "EXACT_CROSS_SPLIT_DUPLICATE_ONLY",
        "implementation_receipt_sha256": implementation_receipt["receipt_sha256"],
        "protocol_records": protocol_records,
        "protocol_records_sha256": _digest("protocol-records", protocol_records),
        "episode_evidence_records": episode_evidence_records,
        "episode_evidence_records_sha256": _digest(
            "episode-evidence-records", episode_evidence_records
        ),
        "strategy_protocols": strategy_protocols,
        "strategy_protocols_sha256": _digest("strategy-protocols", strategy_protocols),
        "runtime_summary": _runtime_summary(
            [spec.fault_mode for spec in specs],
            primary_episodes,
            reference_episodes,
        ),
        "stratified_governance_metrics": stratified_metrics,
        "stratified_governance_metrics_sha256": _digest(
            "stratified-governance-metrics", stratified_metrics
        ),
        "paired_strategy_comparison": paired.model_dump(mode="json"),
        "single_attempt_reference_comparison": reference_paired.model_dump(mode="json"),
        "raw_images_transmitted": False,
        "source_dataset_mutated": False,
        "product_labels_used_as_governance_truth": False,
        "production_release_allowed": False,
        "claim_boundary": CLAIM_BOUNDARY,
    }
    report = {
        **report_without_seal,
        "report_sha256": _digest("public-runtime-report", report_without_seal),
    }
    ending_implementation_receipt = build_public_runtime_implementation_receipt()
    if not hmac.compare_digest(
        implementation_receipt["receipt_sha256"],
        ending_implementation_receipt["receipt_sha256"],
    ):
        raise RuntimeError("public runtime implementation changed during execution")
    validate_public_runtime_retry_benchmark(
        report,
        implementation_receipt=implementation_receipt,
        source_binding=source_binding,
        source_index=source_index,
        programmatic_manifest=programmatic_manifest,
        truth_receipt=truth_receipt,
    )
    return report, programmatic_manifest, truth_receipt, implementation_receipt


def validate_public_runtime_retry_benchmark(
    report: dict[str, Any],
    *,
    implementation_receipt: dict[str, Any] | None = None,
    source_binding: PublicSourceBinding | None = None,
    source_index: VisaSourceIndex | None = None,
    programmatic_manifest: ProgrammaticGovernanceInjectionManifest | None = None,
    truth_receipt: ProgrammaticGovernanceTruthReceipt | None = None,
    verify_current_sources: bool = False,
) -> None:
    schema_version = report.get("schema_version")
    if schema_version not in {SCHEMA_VERSION, LEGACY_SCHEMA_VERSION}:
        raise ValueError("public runtime benchmark schema mismatch")
    expected_benchmark_id = (
        BENCHMARK_ID if schema_version == SCHEMA_VERSION else LEGACY_BENCHMARK_ID
    )
    if report.get("benchmark_id") != expected_benchmark_id:
        raise ValueError("public runtime benchmark identity mismatch")
    payload = {key: value for key, value in report.items() if key != "report_sha256"}
    expected = _digest("public-runtime-report", payload)
    observed = report.get("report_sha256")
    if not isinstance(observed, str) or not hmac.compare_digest(expected, observed):
        raise ValueError("public runtime benchmark digest mismatch")
    paired = PairedStrategyComparisonV2Report.model_validate(
        report.get("paired_strategy_comparison")
    )
    verify_paired_strategy_comparison_v2_report(
        paired,
        allow_legacy_false_block_verdict=(schema_version == LEGACY_SCHEMA_VERSION),
    )
    summary = report.get("runtime_summary")
    if not isinstance(summary, dict):
        raise ValueError("public runtime benchmark summary is missing")
    if summary.get("episode_count") != len(paired.request.episodes):
        raise ValueError("public runtime benchmark denominator drifted")
    if summary.get("unsafe_release_count") != 0:
        raise ValueError("public runtime benchmark observed an unsafe release")
    if report.get("claim_boundary") != CLAIM_BOUNDARY:
        raise ValueError("public runtime benchmark claim boundary drifted")
    if report.get("status") != "PASS":
        raise ValueError("public runtime benchmark status drifted")
    for false_boundary in (
        "raw_images_transmitted",
        "source_dataset_mutated",
        "product_labels_used_as_governance_truth",
        "production_release_allowed",
    ):
        if report.get(false_boundary) is not False:
            raise ValueError(
                f"public runtime boundary must remain false: {false_boundary}"
            )
    if schema_version == LEGACY_SCHEMA_VERSION:
        return
    _require_exact_keys(
        report,
        {
            "schema_version",
            "benchmark_id",
            "status",
            "dataset_identity_sha256",
            "source_binding_sha256",
            "programmatic_manifest_sha256",
            "truth_receipt_sha256",
            "governance_truth_scope",
            "implementation_receipt_sha256",
            "protocol_records",
            "protocol_records_sha256",
            "episode_evidence_records",
            "episode_evidence_records_sha256",
            "strategy_protocols",
            "strategy_protocols_sha256",
            "runtime_summary",
            "stratified_governance_metrics",
            "stratified_governance_metrics_sha256",
            "paired_strategy_comparison",
            "single_attempt_reference_comparison",
            "raw_images_transmitted",
            "source_dataset_mutated",
            "product_labels_used_as_governance_truth",
            "production_release_allowed",
            "claim_boundary",
            "report_sha256",
        },
        label="public runtime v2 report",
    )
    if report.get("governance_truth_scope") != "EXACT_CROSS_SPLIT_DUPLICATE_ONLY":
        raise ValueError("public runtime governance truth scope drifted")
    detached = (
        implementation_receipt,
        source_binding,
        source_index,
        programmatic_manifest,
        truth_receipt,
    )
    if any(item is None for item in detached):
        raise ValueError("public runtime v2 validation requires all detached receipts")
    assert implementation_receipt is not None
    assert source_binding is not None
    assert source_index is not None
    assert programmatic_manifest is not None
    assert truth_receipt is not None
    validate_public_runtime_implementation_receipt(
        implementation_receipt,
        verify_current_sources=verify_current_sources,
    )
    receipt_sha256 = report.get("implementation_receipt_sha256")
    if not hmac.compare_digest(
        str(receipt_sha256), implementation_receipt["receipt_sha256"]
    ):
        raise ValueError("public runtime implementation receipt binding mismatch")
    verify_public_source_binding(source_binding)
    verify_visa_source_index(source_index, source_binding=source_binding)
    verify_programmatic_governance_manifest(
        programmatic_manifest,
        source_index=source_index,
        source_binding=source_binding,
    )
    verify_programmatic_truth_receipt(
        truth_receipt,
        manifest=programmatic_manifest,
    )
    detached_bindings = {
        "dataset_identity_sha256": source_index.index_sha256,
        "source_binding_sha256": source_binding.binding_sha256,
        "programmatic_manifest_sha256": programmatic_manifest.manifest_sha256,
        "truth_receipt_sha256": truth_receipt.receipt_sha256,
    }
    if any(report.get(key) != value for key, value in detached_bindings.items()):
        raise ValueError("public runtime detached evidence binding mismatch")

    episode_records = report.get("episode_evidence_records")
    if not isinstance(episode_records, list) or not episode_records:
        raise ValueError("public runtime episode evidence records are missing")
    expected_episode_records_sha256 = _digest(
        "episode-evidence-records", episode_records
    )
    if report.get("episode_evidence_records_sha256") != (
        expected_episode_records_sha256
    ):
        raise ValueError("public runtime episode evidence aggregate seal mismatch")
    episode_ids: list[str] = []
    for episode_record in episode_records:
        if not isinstance(episode_record, dict):
            raise ValueError("public runtime episode evidence record is malformed")
        _validate_episode_evidence(episode_record, source_index=source_index)
        episode_ids.append(str(episode_record["episode_id"]))
    if len(episode_ids) != len(set(episode_ids)):
        raise ValueError("public runtime episode evidence IDs are not unique")

    rebuilt_primary_episodes = [
        _paired_episode(
            episode_evidence=item,
            fixed_execution_strategy="FIXED_UNIFORM_BOUNDED_RETRY",
        )
        for item in episode_records
    ]
    rebuilt_reference_episodes = [
        _paired_episode(
            episode_evidence=item,
            fixed_execution_strategy="FIXED_SINGLE_ATTEMPT",
        )
        for item in episode_records
    ]
    reference = PairedStrategyComparisonV2Report.model_validate(
        report.get("single_attempt_reference_comparison")
    )
    primary_request = CreatePairedStrategyComparisonV2Request(
        comparison_id="visa-public-runtime-retry-v2-fixed-uniform-vs-dynamic",
        source_scope=PUBLIC_SCOPE,
        baseline_strategy="FIXED_EXHAUSTIVE_PIPELINE",
        dataset_identity_sha256=source_index.index_sha256,
        source_benchmark_sha256=truth_receipt.receipt_sha256,
        episodes=rebuilt_primary_episodes,
        evaluated_at=paired.request.evaluated_at,
        note=(
            "Primary paired VisA public proxy comparison uses equal retry budgets; "
            "truth and faults are withheld from the Agent and Judge inputs."
        ),
    )
    reference_request = CreatePairedStrategyComparisonV2Request(
        comparison_id="visa-public-runtime-retry-v2-single-attempt-reference",
        source_scope=PUBLIC_SCOPE,
        baseline_strategy="FIXED_RULE_PIPELINE",
        dataset_identity_sha256=source_index.index_sha256,
        source_benchmark_sha256=truth_receipt.receipt_sha256,
        episodes=rebuilt_reference_episodes,
        evaluated_at=paired.request.evaluated_at,
        note=(
            "Secondary single-attempt reference only; it is not the primary baseline "
            "for Agent advantage claims."
        ),
    )
    rebuilt_paired = build_paired_strategy_comparison_v2_report(primary_request)
    rebuilt_reference = build_paired_strategy_comparison_v2_report(reference_request)
    if _canonical_bytes(rebuilt_paired) != _canonical_bytes(paired):
        raise ValueError(
            "public runtime primary comparison is not evidence-rebuildable"
        )
    if _canonical_bytes(rebuilt_reference) != _canonical_bytes(reference):
        raise ValueError(
            "public runtime reference comparison is not evidence-rebuildable"
        )

    expected_protocol_records = []
    for item in episode_records:
        expected_protocol_records.append(
            {
                "episode_id": item["episode_id"],
                "episode_receipt_sha256": item["episode_receipt_sha256"],
                "fault_mode": item["fault_injection"]["fault_mode"],
                "target_tool": item["fault_injection"]["target_tool"],
                "truth_disposition": item["truth_disposition"],
                **item["source_samples"],
            }
        )
    protocol_records = report.get("protocol_records")
    if protocol_records != expected_protocol_records or report.get(
        "protocol_records_sha256"
    ) != _digest("protocol-records", expected_protocol_records):
        raise ValueError("public runtime protocol records are not evidence-derived")

    fault_modes = [
        cast(FaultMode, item["fault_injection"]["fault_mode"])
        for item in episode_records
    ]
    expected_summary = _runtime_summary(
        fault_modes,
        rebuilt_primary_episodes,
        rebuilt_reference_episodes,
    )
    if _canonical_bytes(summary) != _canonical_bytes(expected_summary):
        raise ValueError("public runtime summary does not reconcile with evidence")
    expected_stratified = _stratified_governance_metrics(
        episode_records,
        rebuilt_primary_episodes,
        rebuilt_reference_episodes,
    )
    if report.get("stratified_governance_metrics") != expected_stratified or report.get(
        "stratified_governance_metrics_sha256"
    ) != _digest("stratified-governance-metrics", expected_stratified):
        raise ValueError("public runtime stratified metrics are not evidence-derived")

    strategy_protocols = report.get("strategy_protocols")
    if strategy_protocols != _strategy_protocols() or report.get(
        "strategy_protocols_sha256"
    ) != _digest("strategy-protocols", strategy_protocols):
        raise ValueError("public runtime strategy protocol drifted")

    truth_by_unit = {item.unit_id: item for item in truth_receipt.units}
    manifest_cases = {item.unit_id: item for item in programmatic_manifest.cases}
    if set(episode_ids) != set(truth_by_unit) or set(episode_ids) != set(
        manifest_cases
    ):
        raise ValueError("public runtime episode set differs from detached truth")
    for episode_record in episode_records:
        unit = truth_by_unit.get(episode_record["episode_id"])
        if unit is None or (
            episode_record["truth"]["disposition"] != unit.disposition
            or episode_record["truth"]["status"] != unit.status
            or episode_record["truth"]["adjudication_receipt_sha256"]
            != truth_receipt.receipt_sha256
        ):
            raise ValueError("public runtime episode truth differs from detached truth")
        case = manifest_cases.get(episode_record["episode_id"])
        if (
            case is None
            or case.source_sample_id
            != episode_record["source_samples"]["primary_source_sample_id"]
        ):
            raise ValueError("public runtime episode lost programmatic case binding")


def write_public_runtime_retry_benchmark(
    output_dir: str | Path,
    *,
    dataset_root: str | Path,
    source_binding_path: str | Path,
    source_index_path: str | Path,
    clean_case_count: int,
    block_case_count: int,
    transient_fraction: float,
    non_retryable_fraction: float = 0.0,
    evaluated_at: datetime,
    overwrite: bool = False,
) -> dict[str, Path]:
    output = Path(output_dir).expanduser().resolve()
    output.mkdir(parents=True, exist_ok=True)
    paths = {
        "report": output / "public_runtime_retry_benchmark.json",
        "programmatic_manifest": output / "programmatic_manifest.json",
        "truth_receipt": output / "programmatic_truth_receipt.json",
        "implementation_receipt": output / "implementation_identity_receipt.json",
    }
    if not overwrite and any(item.exists() for item in paths.values()):
        raise FileExistsError("refusing to overwrite public runtime benchmark")
    binding = _load_model(source_binding_path, PublicSourceBinding)
    index = _load_model(source_index_path, VisaSourceIndex)
    report, manifest, truth, implementation = build_public_runtime_retry_benchmark(
        dataset_root=dataset_root,
        source_binding=binding,
        source_index=index,
        clean_case_count=clean_case_count,
        block_case_count=block_case_count,
        transient_fraction=transient_fraction,
        non_retryable_fraction=non_retryable_fraction,
        evaluated_at=evaluated_at,
    )
    paths["report"].write_bytes(_canonical_bytes(report) + b"\n")
    paths["programmatic_manifest"].write_bytes(
        canonical_public_bench_json_bytes(manifest) + b"\n"
    )
    paths["truth_receipt"].write_bytes(canonical_public_bench_json_bytes(truth) + b"\n")
    paths["implementation_receipt"].write_bytes(
        _canonical_bytes(implementation) + b"\n"
    )
    validate_public_runtime_retry_benchmark(
        report,
        implementation_receipt=implementation,
        source_binding=binding,
        source_index=index,
        programmatic_manifest=manifest,
        truth_receipt=truth,
    )
    return paths


def verify_public_runtime_retry_benchmark_bundle(
    output_dir: str | Path,
    *,
    source_binding_path: str | Path,
    source_index_path: str | Path,
    verify_current_sources: bool = True,
) -> dict[str, Any]:
    """Verify an existing bundle without re-running image tools or fault injection."""

    output = Path(output_dir).expanduser().resolve(strict=True)
    if not output.is_dir():
        raise ValueError("public runtime benchmark bundle must be a directory")
    paths = {
        "report": output / "public_runtime_retry_benchmark.json",
        "programmatic_manifest": output / "programmatic_manifest.json",
        "truth_receipt": output / "programmatic_truth_receipt.json",
        "implementation_receipt": output / "implementation_identity_receipt.json",
    }
    missing = [name for name, path in paths.items() if not path.is_file()]
    if missing:
        raise FileNotFoundError(
            "public runtime benchmark bundle is incomplete: " + ", ".join(missing)
        )
    report = json.loads(paths["report"].read_text(encoding="utf-8"))
    implementation = json.loads(
        paths["implementation_receipt"].read_text(encoding="utf-8")
    )
    source_binding = _load_model(source_binding_path, PublicSourceBinding)
    source_index = _load_model(source_index_path, VisaSourceIndex)
    programmatic_manifest = _load_model(
        paths["programmatic_manifest"],
        ProgrammaticGovernanceInjectionManifest,
    )
    truth_receipt = _load_model(
        paths["truth_receipt"],
        ProgrammaticGovernanceTruthReceipt,
    )
    validate_public_runtime_retry_benchmark(
        report,
        implementation_receipt=implementation,
        source_binding=source_binding,
        source_index=source_index,
        programmatic_manifest=programmatic_manifest,
        truth_receipt=truth_receipt,
        verify_current_sources=verify_current_sources,
    )
    return report


__all__ = [
    "BENCHMARK_ID",
    "CLAIM_BOUNDARY",
    "IMPLEMENTATION_RECEIPT_SCHEMA_VERSION",
    "SCHEMA_VERSION",
    "build_public_runtime_implementation_receipt",
    "build_public_runtime_retry_benchmark",
    "validate_public_runtime_implementation_receipt",
    "validate_public_runtime_retry_benchmark",
    "verify_public_runtime_retry_benchmark_bundle",
    "write_public_runtime_retry_benchmark",
]
