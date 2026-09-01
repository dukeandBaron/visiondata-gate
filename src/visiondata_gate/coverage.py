"""Contract coverage-matrix checks."""

from __future__ import annotations

from itertools import product
from pathlib import Path

from .contracts import BatchContract, BatchManifest, Finding, Severity
from .quality import _new_finding, _validated_root


TOOL_NAME = "coverage_matrix"


def inspect_coverage(
    batch_root: str | Path,
    manifest: BatchManifest,
    contract: BatchContract | None = None,
) -> tuple[list[Finding], dict[str, int | float | str]]:
    _validated_root(batch_root)
    validated_manifest = BatchManifest.model_validate(manifest.model_dump(mode="json"))
    active_contract = BatchContract.model_validate(
        (contract or BatchContract()).model_dump(mode="json")
    )
    coverage = active_contract.coverage

    expected_cells = list(
        product(
            coverage.splits, coverage.categories, coverage.views, coverage.conditions
        )
    )
    counts: dict[tuple[str, str, str, str], int] = {cell: 0 for cell in expected_cells}
    for sample in validated_manifest.samples:
        key = (sample.split, sample.category, sample.view, sample.condition)
        if key in counts:
            counts[key] += 1

    missing_cells = [
        cell for cell in expected_cells if counts[cell] < coverage.min_per_cell
    ]
    findings: list[Finding] = []
    if missing_cells:
        serialized_cells = [
            {
                "split": split,
                "category": category,
                "view": view,
                "condition": condition,
                "observed_count": counts[(split, category, view, condition)],
                "required_count": coverage.min_per_cell,
            }
            for split, category, view, condition in missing_cells
        ]
        evidence = {
            "missing_cells": serialized_cells,
            "expected_cell_count": len(expected_cells),
            "min_per_cell": coverage.min_per_cell,
        }
        findings.append(
            _new_finding(
                tool=TOOL_NAME,
                code="COVERAGE_GAP",
                severity=Severity.HIGH,
                sample_ids=[],
                summary="The batch does not satisfy every required coverage cell.",
                evidence=evidence,
                recommended_action="recapture",
            )
        )

    observed_cell_count = sum(
        value >= coverage.min_per_cell for value in counts.values()
    )
    metrics: dict[str, int | float | str] = {
        "expected_cell_count": len(expected_cells),
        "observed_cell_count": observed_cell_count,
        "missing_cell_count": len(missing_cells),
        "minimum_observed_cell_count": min(counts.values()) if counts else 0,
        "required_min_per_cell": coverage.min_per_cell,
    }
    return findings, metrics


def run_coverage_tool(
    batch_root: str | Path,
    manifest: BatchManifest,
    contract: BatchContract | None = None,
) -> tuple[list[Finding], dict[str, int | float | str]]:
    return inspect_coverage(batch_root, manifest, contract)
