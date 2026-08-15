"""Deterministic tool orchestration with optional governance checks."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping
from itertools import product
from pathlib import Path
from collections.abc import Callable
from typing import Any, TypeVar

from pydantic import BaseModel

from .annotations import inspect_annotations
from .contracts import (
    BatchContract,
    BatchManifest,
    Finding,
    Severity,
    ToolContract,
    ToolTrace,
)
from .coverage import inspect_coverage
from .duplicates import _MAX_NEAR_DUPLICATE_MAE, inspect_duplicates
from .quality import (
    _canonical_sha256,
    _new_finding,
    _resolve_sample_path,
    _validated_root,
    inspect_image_quality,
)


_ModelT = TypeVar("_ModelT", bound=BaseModel)


ToolSpec = tuple[
    str,  # name
    str,  # metric prefix
    Callable[..., tuple[list[Finding], dict[str, int | float | str]]],  # implementation
    str,  # permission
]

_TOOL_WHITELIST: tuple[ToolSpec, ...] = (
    ("image_quality", "quality", inspect_image_quality, "dataset:read"),
    ("duplicate_leakage", "duplicates", inspect_duplicates, "dataset:read"),
    ("annotation_integrity", "annotation", inspect_annotations, "annotation:read"),
    ("coverage_matrix", "coverage", inspect_coverage, "manifest:read"),
)

# populated after inspect_contract_governance is defined
# populated after inspect_contract_governance is defined
_OPTIONAL_TOOLS: tuple[ToolSpec, ...] = ()

_REGISTERED_TRACE_ADAPTERS = {
    "local-deterministic",
    "external-readonly-omni-v1",
}


def tool_contract_catalog(*, include_optional: bool = False) -> list[ToolContract]:
    """Return the typed adapter contracts for the active allowlisted tools.

    This is the source of truth for permission, side-effect and migration
    fields.  A tool may be replaced behind this contract, but a replacement
    must preserve the canonical ToolTrace/Finding output and replay behavior.
    """

    contracts = {
        "image_quality": ToolContract(
            name="image_quality",
            version="1.0.0",
            input_schema="BatchManifest + BatchContract.thresholds",
            output_schema="ToolTrace + Finding[] + quality metrics",
            permission_scope="dataset:read / read_batch_emit_finding",
            side_effect_level="L0_none",
            idempotency="input_manifest_digest + contract parameters",
            max_retries=1,
            audit_fields=[
                "sequence",
                "input_sha256",
                "parameters",
                "result_sha256",
                "finding_ids",
            ],
            mcp_migration_target="mcp-tool.v1",
            migration_cost="medium",
        ),
        "duplicate_leakage": ToolContract(
            name="duplicate_leakage",
            version="1.0.0",
            input_schema="BatchManifest + BatchContract.thresholds.near_duplicate_hamming",
            output_schema="ToolTrace + Finding[] + duplicate metrics",
            permission_scope="dataset:read / read_batch_emit_finding",
            side_effect_level="L0_none",
            idempotency="input_manifest_digest + contract parameters",
            max_retries=1,
            audit_fields=[
                "sequence",
                "input_sha256",
                "parameters",
                "result_sha256",
                "finding_ids",
            ],
            mcp_migration_target="mcp-tool.v1",
            migration_cost="medium",
        ),
        "annotation_integrity": ToolContract(
            name="annotation_integrity",
            version="1.0.0",
            input_schema="BatchManifest + BatchContract.annotation policy",
            output_schema="ToolTrace + Finding[] + annotation metrics",
            permission_scope="annotation:read / read_batch_emit_finding",
            side_effect_level="L0_none",
            idempotency="input_manifest_digest + contract parameters",
            max_retries=1,
            audit_fields=[
                "sequence",
                "input_sha256",
                "parameters",
                "result_sha256",
                "finding_ids",
            ],
            mcp_migration_target="mcp-tool.v1",
            migration_cost="medium",
        ),
        "coverage_matrix": ToolContract(
            name="coverage_matrix",
            version="1.0.0",
            input_schema="BatchManifest + BatchContract.coverage",
            output_schema="ToolTrace + Finding[] + coverage metrics",
            permission_scope="manifest:read / read_batch_emit_finding",
            side_effect_level="L0_none",
            idempotency="input_manifest_digest + contract parameters",
            max_retries=1,
            audit_fields=[
                "sequence",
                "input_sha256",
                "parameters",
                "result_sha256",
                "finding_ids",
            ],
            mcp_migration_target="mcp-tool.v1",
            migration_cost="low",
        ),
        "governance_audit": ToolContract(
            name="governance_audit",
            version="1.0.0",
            input_schema="BatchManifest + BatchContract + ScenarioProfile",
            output_schema="ToolTrace + Finding[] + governance metrics",
            permission_scope="contract:read / read_contract_emit_finding",
            side_effect_level="L0_none",
            idempotency="input_contract_digest + manifest digest",
            max_retries=1,
            audit_fields=[
                "sequence",
                "input_sha256",
                "parameters",
                "result_sha256",
                "finding_ids",
            ],
            mcp_migration_target="mcp-tool.v1",
            migration_cost="medium",
        ),
    }
    names = [item[0] for item in _catalog(include_optional)]
    return [contracts[name] for name in names]


def tool_contract_digest(tool_name: str, *, include_optional: bool = False) -> str:
    """Return the canonical digest that binds a trace to its tool contract."""

    for contract in tool_contract_catalog(include_optional=include_optional):
        if contract.name == tool_name:
            return _canonical_sha256(contract.model_dump(mode="json"))
    raise ValueError(f"tool contract is not registered: {tool_name}")


def validate_tool_contract_trace(
    trace: ToolTrace, *, include_optional: bool = False
) -> str | None:
    """Return a bounded error when a tool trace is not contract-bound.

    The runtime turns this error into a failed ToolTrace, so Policy Judge
    reaches ``DEFER`` instead of trusting a result from an unregistered or
    drifted adapter.  ``None`` means the binding is valid.
    """

    try:
        expected = next(
            item
            for item in tool_contract_catalog(include_optional=include_optional)
            if item.name == trace.tool
        )
    except StopIteration:
        return f"unregistered tool contract: {trace.tool}"
    if trace.adapter not in _REGISTERED_TRACE_ADAPTERS:
        return f"unsupported adapter for {trace.tool}: {trace.adapter}"
    if trace.contract_version != expected.version:
        return (
            f"tool contract version drift for {trace.tool}: "
            f"{trace.contract_version} != {expected.version}"
        )
    expected_digest = tool_contract_digest(
        trace.tool, include_optional=include_optional
    )
    if trace.contract_digest != expected_digest:
        return f"tool contract digest drift for {trace.tool}"
    return None


def _load_model(
    value: _ModelT | str | Path | Mapping[str, Any],
    model_type: type[_ModelT],
) -> _ModelT:
    if isinstance(value, BaseModel):
        # Revalidation is intentional: model_copy/model_construct can bypass
        # validators, including the path traversal gate.
        payload: Any = value.model_dump(mode="json")
    elif isinstance(value, Mapping):
        payload = dict(value)
    elif isinstance(value, (str, Path)):
        path = Path(value).expanduser().resolve()
        if not path.exists():
            raise FileNotFoundError(path)
        if not path.is_file():
            raise IsADirectoryError(path)
        payload = json.loads(path.read_text(encoding="utf-8"))
    else:
        raise TypeError(
            f"expected {model_type.__name__}, mapping, or JSON path; got {type(value).__name__}"
        )
    return model_type.model_validate(payload)


def _file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _metric_name(metric_prefix: str, key: str) -> str:
    """Prevent accidental duplicated metric namespaces."""
    if not metric_prefix:
        return key
    prefix = f"{metric_prefix}_"
    return key if key.startswith(prefix) else f"{prefix}{key}"


def _batch_fingerprint(root: Path, manifest: BatchManifest) -> str:
    files: list[dict[str, str | bool]] = []
    references: set[str] = set()
    for sample in manifest.samples:
        references.add(sample.relative_path)
        if sample.annotation_path is not None:
            references.add(sample.annotation_path)
    for relative_path in sorted(references):
        path = _resolve_sample_path(root, relative_path)
        if not path.exists():
            files.append({"relative_path": relative_path, "exists": False})
            continue
        if not path.is_file():
            raise IsADirectoryError(path)
        files.append(
            {
                "relative_path": relative_path,
                "exists": True,
                "sha256": _file_sha256(path),
            }
        )
    return _canonical_sha256(
        {
            "manifest": manifest.model_dump(mode="json"),
            "files": files,
        }
    )


def inspect_contract_governance(
    batch_root: str | Path,
    manifest: BatchManifest,
    contract: BatchContract | None = None,
) -> tuple[list[Finding], dict[str, int | float | str]]:
    """Run compact governance checks for contract-policy alignment.

    This tool is optional: it audits the manifest against contract expectations
    before trust transfer to downstream recommendations.
    """

    _validated_root(batch_root)
    validated_manifest = _load_model(manifest, BatchManifest)
    active_contract = (
        _load_model(contract, BatchContract)
        if contract is not None
        else BatchContract()
    )

    findings: list[Finding] = []

    coverage = active_contract.coverage
    expected_cells = set(
        product(
            coverage.splits, coverage.categories, coverage.views, coverage.conditions
        )
    )
    # Coverage cells are defined over ``CoverageContract.splits``.  A batch
    # may legitimately carry validation/test rows with the same category/view
    # labels; those rows are governed by ``required_splits`` but must not be
    # misclassified as unknown coverage cells.  Keeping the two contracts
    # separate prevents the industrial governance worker from generating a
    # non-actionable investigation order for every held-out split.
    observed_cells = {
        (sample.split, sample.category, sample.view, sample.condition)
        for sample in validated_manifest.samples
        if sample.split in set(coverage.splits)
    }
    missing_cells = sorted(expected_cells - observed_cells)
    unknown_cells = sorted(observed_cells - expected_cells)

    required_splits_ok = set(
        sample.split for sample in validated_manifest.samples
    ).issubset(set(active_contract.required_splits))
    missing_annotation_path_count = 0
    if active_contract.annotations_required:
        missing_annotation_path_count = sum(
            1 for sample in validated_manifest.samples if sample.annotation_path is None
        )

    if missing_cells:
        findings.append(
            _new_finding(
                tool="governance_audit",
                code="GOVERNANCE_SCOPE_GAP",
                severity=Severity.HIGH,
                sample_ids=[],
                summary="Manifest cells are incomplete versus contract coverage definition.",
                evidence={
                    "missing_cells": [
                        {
                            "split": split,
                            "category": category,
                            "view": view,
                            "condition": condition,
                            # Keep governance findings structurally compatible
                            # with coverage_matrix findings.  The repair
                            # orchestrator must be able to distinguish an
                            # observed-but-underfilled cell from a fully
                            # missing cell without inventing counts.
                            "observed_count": sum(
                                1
                                for sample in validated_manifest.samples
                                if sample.split == split
                                and sample.category == category
                                and sample.view == view
                                and sample.condition == condition
                            ),
                            "required_count": coverage.min_per_cell,
                        }
                        for split, category, view, condition in missing_cells
                    ],
                    "coverage_cell_count": len(expected_cells),
                },
                recommended_action="investigate",
            )
        )

    if unknown_cells:
        findings.append(
            _new_finding(
                tool="governance_audit",
                code="GOVERNANCE_SCOPE_UNKNOWN",
                severity=Severity.HIGH,
                sample_ids=[],
                summary="Manifest contains contract-unknown coverage values.",
                evidence={
                    "unknown_cells": [
                        {
                            "split": split,
                            "category": category,
                            "view": view,
                            "condition": condition,
                        }
                        for split, category, view, condition in unknown_cells
                    ]
                },
                recommended_action="investigate",
            )
        )

    if not required_splits_ok:
        findings.append(
            _new_finding(
                tool="governance_audit",
                code="GOVERNANCE_REQUIRED_SPLIT_MISMATCH",
                severity=Severity.CRITICAL,
                sample_ids=[],
                summary="Observed split values are outside contract required_splits.",
                evidence={
                    "required_splits": active_contract.required_splits,
                    "observed_splits": sorted(
                        {sample.split for sample in validated_manifest.samples}
                    ),
                },
                recommended_action="investigate",
            )
        )

    if missing_annotation_path_count:
        missing_samples = [
            sample.sample_id
            for sample in validated_manifest.samples
            if sample.annotation_path is None
        ]
        findings.append(
            _new_finding(
                tool="governance_audit",
                code="GOVERNANCE_ANNOTATION_PATH_MISSING",
                severity=Severity.HIGH,
                sample_ids=missing_samples,
                summary="Contract requires annotations but manifest rows omit annotation_path.",
                evidence={
                    "missing_annotation_count": missing_annotation_path_count,
                    "sample_ids": missing_samples,
                    "annotations_required": active_contract.annotations_required,
                },
                recommended_action="investigate",
            )
        )

    expected_required_per_cell = coverage.min_per_cell * len(expected_cells)
    observed_cells_with_counts = len(observed_cells)
    observed_required_cells = len(
        {
            (sample.split, sample.category, sample.view, sample.condition)
            for sample in validated_manifest.samples
        }
        & expected_cells
    )

    metrics: dict[str, int | float | str] = {
        "coverage_cell_count": len(expected_cells),
        "observed_cells": observed_cells_with_counts,
        "observed_required_cells": observed_required_cells,
        "missing_cell_count": len(missing_cells),
        "unknown_cell_count": len(unknown_cells),
        "required_split_ok": int(required_splits_ok),
        "annotation_path_missing_count": missing_annotation_path_count,
        "required_cells_total": expected_required_per_cell,
    }
    return findings, metrics


def _trace_parameters(tool: str, contract: BatchContract) -> dict[str, Any]:
    if tool == "image_quality":
        return contract.thresholds.model_dump(mode="json")
    if tool == "duplicate_leakage":
        return {
            "near_duplicate_hamming": contract.thresholds.near_duplicate_hamming,
            "thumbnail_mean_abs_difference_max": _MAX_NEAR_DUPLICATE_MAE,
            "cross_split_only_for_near_duplicates": True,
        }
    if tool == "annotation_integrity":
        return {
            "annotations_required": contract.annotations_required,
            "expected_width": contract.thresholds.expected_width,
            "expected_height": contract.thresholds.expected_height,
            "min_mask_fraction": contract.thresholds.min_mask_fraction,
            "max_mask_fraction": contract.thresholds.max_mask_fraction,
        }
    if tool == "coverage_matrix":
        return contract.coverage.model_dump(mode="json")
    if tool == "governance_audit":
        return {
            "required_splits": contract.required_splits,
            "annotations_required": contract.annotations_required,
            "coverage_cells": len(
                list(
                    product(
                        contract.coverage.splits,
                        contract.coverage.categories,
                        contract.coverage.views,
                        contract.coverage.conditions,
                    )
                )
            ),
        }
    raise ValueError(f"tool is not whitelisted: {tool}")


def _catalog(include_optional_tools: bool) -> list[ToolSpec]:
    tools = list(_TOOL_WHITELIST)
    if include_optional_tools:
        tools.extend(
            (
                (
                    "governance_audit",
                    "governance",
                    inspect_contract_governance,
                    "contract:read",
                ),
            )
        )
    return tools


def tool_catalog(*, include_optional: bool = False) -> list[dict[str, str | int]]:
    """Describe allowlisted capabilities without exposing implementation callables."""

    descriptions = {
        "image_quality": "Image decode/quality checks.",
        "duplicate_leakage": "Exact and near-duplicate leak checks.",
        "annotation_integrity": "Annotation path and mask checks.",
        "coverage_matrix": "Coverage matrix completeness checks.",
        "governance_audit": "Contract and manifest governance alignment checks.",
    }
    return [
        {
            "sequence": index,
            "name": name,
            "metric_prefix": prefix,
            "permission": permission,
            "scope": "optional" if name == "governance_audit" else "core",
            "description": descriptions[name],
        }
        for index, (name, prefix, _function, permission) in enumerate(
            _catalog(include_optional), start=1
        )
    ]


def run_tool(
    tool_name: str,
    batch_root: str | Path,
    manifest: BatchManifest | str | Path | Mapping[str, Any],
    contract: BatchContract | str | Path | Mapping[str, Any],
    *,
    include_optional: bool = False,
) -> tuple[list[Finding], ToolTrace, dict[str, int | float | str]]:
    """Execute one allowlisted tool for one scheduled worker."""

    catalog = {
        name: (prefix, function)
        for name, prefix, function, _ in _catalog(include_optional)
    }
    if tool_name not in catalog:
        raise ValueError(f"tool is not whitelisted: {tool_name}")
    metric_prefix, tool_function = catalog[tool_name]
    sequence = next(
        index
        for index, item in enumerate(_catalog(include_optional), start=1)
        if item[0] == tool_name
    )
    root = _validated_root(batch_root)
    validated_manifest = _load_model(manifest, BatchManifest)
    validated_contract = _load_model(contract, BatchContract)
    batch_sha256 = _batch_fingerprint(root, validated_manifest)
    parameters = _trace_parameters(tool_name, validated_contract)
    input_sha256 = _canonical_sha256(
        {
            "tool": tool_name,
            "batch_sha256": batch_sha256,
            "contract": validated_contract.model_dump(mode="json"),
            "parameters": parameters,
            "optional": include_optional,
        }
    )
    tool_findings, tool_metrics = tool_function(
        root,
        validated_manifest,
        validated_contract,
    )
    validated_findings = [
        Finding.model_validate(item.model_dump(mode="json")) for item in tool_findings
    ]
    result_sha256 = _canonical_sha256(
        {
            "findings": [item.model_dump(mode="json") for item in validated_findings],
            "metrics": tool_metrics,
        }
    )
    trace = ToolTrace(
        sequence=sequence,
        tool=tool_name,
        status="ok",
        input_sha256=input_sha256,
        parameters=parameters,
        result_sha256=result_sha256,
        finding_ids=[item.finding_id for item in validated_findings],
        contract_version=next(
            item.version
            for item in tool_contract_catalog(include_optional=include_optional)
            if item.name == tool_name
        ),
        contract_digest=tool_contract_digest(
            tool_name, include_optional=include_optional
        ),
        adapter="local-deterministic",
    )
    metrics = {
        _metric_name(metric_prefix, key): value
        for key, value in sorted(tool_metrics.items())
    }
    return validated_findings, trace, metrics


def run_all_tools(
    batch_root: str | Path,
    manifest: BatchManifest | str | Path | Mapping[str, Any],
    contract: BatchContract | str | Path | Mapping[str, Any],
    *,
    include_optional_tools: bool = False,
) -> tuple[list[Finding], list[ToolTrace], dict[str, int | float | str]]:
    """Run allowlisted tools and return typed findings, traces, and metrics."""

    root = _validated_root(batch_root)
    validated_manifest = _load_model(manifest, BatchManifest)
    validated_contract = _load_model(contract, BatchContract)
    batch_sha256 = _batch_fingerprint(root, validated_manifest)
    contract_payload = validated_contract.model_dump(mode="json")

    tool_specs = _catalog(include_optional_tools)
    findings: list[Finding] = []
    traces: list[ToolTrace] = []
    aggregate_metrics: dict[str, int | float | str] = {
        "sample_count": len(validated_manifest.samples),
        "tool_count": len(tool_specs),
        "tool_error_count": 0,
    }

    for sequence, (tool_name, metric_prefix, tool_function, _permission) in enumerate(
        tool_specs, start=1
    ):
        parameters = _trace_parameters(tool_name, validated_contract)
        input_sha256 = _canonical_sha256(
            {
                "tool": tool_name,
                "batch_sha256": batch_sha256,
                "contract": contract_payload,
                "parameters": parameters,
                "optional": include_optional_tools,
            }
        )
        tool_findings, tool_metrics = tool_function(
            root,
            validated_manifest,
            validated_contract,
        )
        validated_findings = [
            Finding.model_validate(item.model_dump(mode="json"))
            for item in tool_findings
        ]
        result_sha256 = _canonical_sha256(
            {
                "findings": [
                    item.model_dump(mode="json") for item in validated_findings
                ],
                "metrics": tool_metrics,
            }
        )
        traces.append(
            ToolTrace(
                sequence=sequence,
                tool=tool_name,
                status="ok",
                input_sha256=input_sha256,
                parameters=parameters,
                result_sha256=result_sha256,
                finding_ids=[item.finding_id for item in validated_findings],
                error=None,
                contract_version=next(
                    item.version
                    for item in tool_contract_catalog(
                        include_optional=include_optional_tools
                    )
                    if item.name == tool_name
                ),
                contract_digest=tool_contract_digest(
                    tool_name, include_optional=include_optional_tools
                ),
                adapter="local-deterministic",
            )
        )
        findings.extend(validated_findings)
        for key, value in sorted(tool_metrics.items()):
            aggregate_metrics[_metric_name(metric_prefix, key)] = value

    aggregate_metrics["finding_count"] = len(findings)
    return findings, traces, aggregate_metrics


__all__ = [
    "run_all_tools",
    "run_tool",
    "tool_catalog",
    "tool_contract_catalog",
    "tool_contract_digest",
    "validate_tool_contract_trace",
    "inspect_contract_governance",
]
