"""Non-destructive reserve-backed repair simulation.

This module deliberately has no corruption-manifest input.  Repair decisions
come only from explicit work orders and the public reserve manifest.
"""

from __future__ import annotations

import os
import shutil
import tempfile
import time
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path, PurePosixPath

from .contracts import BatchManifest, SampleRecord, WorkOrder


class RepairError(RuntimeError):
    """Raised when a simulated repair cannot be completed safely."""


@dataclass(frozen=True)
class RepairResult:
    """Artifacts produced by a successful non-destructive repair simulation."""

    output_root: Path
    manifest_path: Path
    manifest: BatchManifest
    completed_work_orders: list[WorkOrder]
    replacement_map: dict[str, str]


def _existing_directory(path: str | Path, *, label: str) -> Path:
    candidate = Path(path)
    if candidate.is_symlink():
        raise RepairError(f"{label} must not be a symlink: {candidate}")
    try:
        resolved = candidate.resolve(strict=True)
    except OSError as exc:
        raise RepairError(f"{label} does not exist: {candidate}") from exc
    if not resolved.is_dir():
        raise RepairError(f"{label} is not a directory: {candidate}")
    return resolved


def _relative_parts(value: str) -> tuple[str, ...]:
    path = PurePosixPath(value.replace("\\", "/"))
    if path.is_absolute() or not path.parts or ".." in path.parts:
        raise RepairError(f"unsafe manifest path: {value}")
    return path.parts


def _safe_source_file(root: Path, relative_path: str, *, label: str) -> Path:
    current = root
    for part in _relative_parts(relative_path):
        current = current / part
        if current.is_symlink():
            raise RepairError(f"{label} traverses a symlink: {relative_path}")

    try:
        resolved = current.resolve(strict=True)
    except OSError as exc:
        raise RepairError(f"{label} is missing: {relative_path}") from exc
    if not resolved.is_relative_to(root):
        raise RepairError(f"{label} escapes its declared root: {relative_path}")
    if not resolved.is_file():
        raise RepairError(f"{label} is not a regular file: {relative_path}")
    return resolved


def _load_reserve_manifest(path: str | Path) -> tuple[Path, BatchManifest]:
    manifest_path = Path(path)
    if manifest_path.is_symlink():
        raise RepairError(f"reserve manifest must not be a symlink: {manifest_path}")
    try:
        resolved = manifest_path.resolve(strict=True)
    except OSError as exc:
        raise RepairError(f"reserve manifest does not exist: {manifest_path}") from exc
    if not resolved.is_file():
        raise RepairError(f"reserve manifest is not a file: {manifest_path}")

    reserve_root = _existing_directory(resolved.parent, label="reserve root")
    try:
        reserve = BatchManifest.model_validate_json(
            resolved.read_text(encoding="utf-8")
        )
    except (OSError, ValueError) as exc:
        raise RepairError(f"reserve manifest is invalid: {manifest_path}") from exc
    return reserve_root, reserve


def _compatible_unlinked_reserve(reserve: SampleRecord, target: SampleRecord) -> bool:
    return (
        reserve.source_sample_id is None
        and reserve.split == target.split
        and reserve.category == target.category
        and reserve.view == target.view
        and reserve.condition == target.condition
    )


def _select_reserve(
    target: SampleRecord,
    reserve_samples: Sequence[SampleRecord],
    used_reserve_ids: set[str],
) -> SampleRecord:
    available = [
        sample for sample in reserve_samples if sample.sample_id not in used_reserve_ids
    ]
    linked = sorted(
        (sample for sample in available if sample.source_sample_id == target.sample_id),
        key=lambda sample: sample.sample_id,
    )
    if len(linked) > 1:
        raise RepairError(
            f"reserve manifest has ambiguous replacements for {target.sample_id}"
        )
    if linked:
        return linked[0]

    same_id = [
        sample
        for sample in available
        if sample.source_sample_id is None and sample.sample_id == target.sample_id
    ]
    if same_id:
        return same_id[0]

    compatible = sorted(
        (
            sample
            for sample in available
            if _compatible_unlinked_reserve(sample, target)
        ),
        key=lambda sample: sample.sample_id,
    )
    if compatible:
        return compatible[0]
    raise RepairError(f"no matching reserve sample for target {target.sample_id}")


def _select_coverage_reserve(
    cell: dict[str, str | int],
    reserve_samples: Sequence[SampleRecord],
    used_reserve_ids: set[str],
) -> SampleRecord:
    compatible = sorted(
        (
            sample
            for sample in reserve_samples
            if sample.sample_id not in used_reserve_ids
            and sample.source_sample_id is None
            and sample.split == cell["split"]
            and sample.category == cell["category"]
            and sample.view == cell["view"]
            and sample.condition == cell["condition"]
        ),
        key=lambda sample: sample.sample_id,
    )
    if not compatible:
        descriptor = "/".join(
            str(cell[key]) for key in ("split", "category", "view", "condition")
        )
        raise RepairError(f"no unlinked reserve sample for coverage cell {descriptor}")
    return compatible[0]


def _coverage_cells(order: WorkOrder) -> list[dict[str, str | int]]:
    if not (
        {"COVERAGE_GAP", "GOVERNANCE_SCOPE_GAP"}
        & {code.upper() for code in order.reason_codes}
    ):
        raise RepairError(f"work order {order.work_order_id} has no target sample IDs")
    raw_cells = order.replacement_requirements.get("missing_cells")
    if not isinstance(raw_cells, list) or not raw_cells:
        raise RepairError(
            f"coverage work order {order.work_order_id} has no missing_cells"
        )

    additions: list[dict[str, str | int]] = []
    for raw_cell in raw_cells:
        if not isinstance(raw_cell, dict):
            raise RepairError(
                f"coverage work order {order.work_order_id} has an invalid cell"
            )
        try:
            split = raw_cell["split"]
            category = raw_cell["category"]
            view = raw_cell["view"]
            condition = raw_cell["condition"]
            observed = raw_cell["observed_count"]
            required = raw_cell["required_count"]
        except KeyError as exc:
            raise RepairError(
                f"coverage work order {order.work_order_id} has an incomplete cell"
            ) from exc
        if not all(
            isinstance(value, str) and value
            for value in (split, category, view, condition)
        ):
            raise RepairError(
                f"coverage work order {order.work_order_id} has invalid cell labels"
            )
        if (
            isinstance(observed, bool)
            or isinstance(required, bool)
            or not isinstance(observed, int)
            or not isinstance(required, int)
            or observed < 0
            or required < 1
        ):
            raise RepairError(
                f"coverage work order {order.work_order_id} has invalid cell counts"
            )
        for _ in range(max(0, required - observed)):
            additions.append(
                {
                    "split": split,
                    "category": category,
                    "view": view,
                    "condition": condition,
                    "observed_count": observed,
                    "required_count": required,
                }
            )
    if not additions:
        raise RepairError(
            f"coverage work order {order.work_order_id} requires no additions"
        )
    return additions


def _destination_path(root: Path, relative_path: str) -> Path:
    return root.joinpath(*_relative_parts(relative_path))


def _publish_staging_directory(staging: Path, destination: Path) -> None:
    """Publish one complete staging tree without accepting partial output.

    Windows directory rename can transiently fail with ``ERROR_ACCESS_DENIED``
    while antivirus or indexers briefly hold a newly written file.  Retry only
    that known transient case, while continuously proving that the destination
    is still absent.  All other failures remain fail closed.
    """

    attempts = 5 if os.name == "nt" else 1
    for attempt in range(attempts):
        if destination.exists() or destination.is_symlink():
            raise RepairError(f"output root already exists: {destination}")
        try:
            os.rename(staging, destination)
            return
        except PermissionError as exc:
            if os.name != "nt" or getattr(exc, "winerror", None) != 5:
                raise
            if attempt == attempts - 1:
                raise RepairError(
                    "atomic repair publication remained unavailable after bounded "
                    "Windows retries"
                ) from exc
            time.sleep(0.05 * (attempt + 1))


def _resolved_new_output(
    output_root: str | Path, *, batch_root: Path, reserve_root: Path
) -> tuple[Path, Path]:
    requested = Path(output_root)
    if requested.exists() or requested.is_symlink():
        raise RepairError(f"output root already exists: {requested}")
    try:
        parent = requested.parent.resolve(strict=True)
    except OSError as exc:
        raise RepairError(f"output parent does not exist: {requested.parent}") from exc
    if not parent.is_dir():
        raise RepairError(f"output parent is not a directory: {requested.parent}")
    if requested.parent.is_symlink():
        raise RepairError(f"output parent must not be a symlink: {requested.parent}")

    output = (parent / requested.name).resolve(strict=False)
    if output.is_relative_to(batch_root) or output.is_relative_to(reserve_root):
        raise RepairError("output root must be outside the source and reserve roots")
    return parent, output


def simulate_repair(
    batch_root: str | Path,
    manifest: BatchManifest,
    reserve_manifest: str | Path,
    work_orders: Sequence[WorkOrder],
    *,
    output_root: str | Path,
) -> RepairResult:
    """Create a sanitized repaired batch without modifying either input root.

    Only files named by ``manifest`` are copied.  A corruption manifest or any
    other hidden fixture file therefore cannot enter the repaired batch.
    Automated repair fails closed for investigation-only orders, unknown
    targets, missing payloads, unsafe paths, or unavailable reserve samples.
    """

    source_root = _existing_directory(batch_root, label="batch root")
    reserve_root, reserve = _load_reserve_manifest(reserve_manifest)
    output_parent, resolved_output = _resolved_new_output(
        output_root, batch_root=source_root, reserve_root=reserve_root
    )

    orders = list(work_orders)
    targets_by_id = {sample.sample_id: sample for sample in manifest.samples}
    target_ids: list[str] = []
    coverage_cells: list[dict[str, str | int]] = []
    for order in orders:
        if order.action == "INVESTIGATE":
            raise RepairError(
                f"work order {order.work_order_id} requires investigation and "
                "cannot be simulated"
            )
        if not order.sample_ids:
            coverage_cells.extend(_coverage_cells(order))
            continue
        for sample_id in order.sample_ids:
            if sample_id not in targets_by_id:
                raise RepairError(
                    f"work order {order.work_order_id} references unknown target "
                    f"sample {sample_id}"
                )
        linked_target_ids = [
            sample_id
            for sample_id in order.sample_ids
            if any(
                reserve_sample.source_sample_id == sample_id
                for reserve_sample in reserve.samples
            )
        ]
        already_targeted = any(
            sample_id in target_ids for sample_id in order.sample_ids
        )
        if len(order.sample_ids) > 1 and (linked_target_ids or already_targeted):
            actionable_ids = linked_target_ids
        else:
            actionable_ids = list(order.sample_ids)
        if not actionable_ids and not already_targeted:
            raise RepairError(
                f"work order {order.work_order_id} has no matching reserve target"
            )
        for sample_id in actionable_ids:
            if sample_id not in target_ids:
                target_ids.append(sample_id)

    # ``coverage_matrix`` and ``governance_audit`` can independently report
    # the same missing contract cell.  They represent two evidence paths for
    # one remediation, not two samples to invent.  Collapse duplicate cells
    # before consuming reserve payloads; retain the most conservative deficit
    # if the tools disagree on their counts.
    deduped_coverage: dict[tuple[str, str, str, str], dict[str, str | int]] = {}
    for cell in coverage_cells:
        key = tuple(
            str(cell[name]) for name in ("split", "category", "view", "condition")
        )
        existing = deduped_coverage.get(key)
        if existing is None:
            deduped_coverage[key] = dict(cell)
            continue
        existing["observed_count"] = min(
            int(existing["observed_count"]), int(cell["observed_count"])
        )
        existing["required_count"] = max(
            int(existing["required_count"]), int(cell["required_count"])
        )
    coverage_cells = [deduped_coverage[key] for key in sorted(deduped_coverage)]

    used_reserve_ids: set[str] = set()
    replacements: dict[str, SampleRecord] = {}
    replacement_map: dict[str, str] = {}
    for sample_id in target_ids:
        reserve_sample = _select_reserve(
            targets_by_id[sample_id], reserve.samples, used_reserve_ids
        )
        used_reserve_ids.add(reserve_sample.sample_id)
        replacements[sample_id] = reserve_sample
        replacement_map[sample_id] = reserve_sample.sample_id

    repaired_samples: list[SampleRecord] = []
    copy_plan: list[tuple[Path, str]] = []
    destinations: set[str] = set()
    for target in manifest.samples:
        replacement = replacements.get(target.sample_id)
        source_record = replacement or target
        payload_root = reserve_root if replacement is not None else source_root

        image_source = _safe_source_file(
            payload_root,
            source_record.relative_path,
            label=f"image payload for {target.sample_id}",
        )
        if target.relative_path in destinations:
            raise RepairError(f"duplicate output path: {target.relative_path}")
        destinations.add(target.relative_path)
        copy_plan.append((image_source, target.relative_path))

        if target.annotation_path is not None:
            if source_record.annotation_path is None:
                raise RepairError(
                    f"reserve sample {source_record.sample_id} has no annotation "
                    f"for target {target.sample_id}"
                )
            annotation_source = _safe_source_file(
                payload_root,
                source_record.annotation_path,
                label=f"annotation payload for {target.sample_id}",
            )
            if target.annotation_path in destinations:
                raise RepairError(f"duplicate output path: {target.annotation_path}")
            destinations.add(target.annotation_path)
            copy_plan.append((annotation_source, target.annotation_path))

        if replacement is None:
            repaired_samples.append(target)
        else:
            repaired_samples.append(
                target.model_copy(update={"source_sample_id": replacement.sample_id})
            )

    existing_sample_ids = {sample.sample_id for sample in repaired_samples}
    coverage_index = 1
    for cell in coverage_cells:
        reserve_sample = _select_coverage_reserve(
            cell, reserve.samples, used_reserve_ids
        )
        used_reserve_ids.add(reserve_sample.sample_id)
        while True:
            new_sample_id = f"coverage-add-{coverage_index:03d}"
            coverage_index += 1
            if new_sample_id not in existing_sample_ids:
                break
        existing_sample_ids.add(new_sample_id)

        image_relative = f"images/{new_sample_id}.png"
        annotation_relative = f"masks/{new_sample_id}.png"
        if reserve_sample.annotation_path is None:
            raise RepairError(
                f"coverage reserve sample {reserve_sample.sample_id} has no annotation"
            )
        added_sample = SampleRecord.model_validate(
            {
                "sample_id": new_sample_id,
                "relative_path": image_relative,
                "annotation_path": annotation_relative,
                "split": cell["split"],
                "category": cell["category"],
                "view": cell["view"],
                "condition": cell["condition"],
                "source_sample_id": reserve_sample.sample_id,
            }
        )
        image_source = _safe_source_file(
            reserve_root,
            reserve_sample.relative_path,
            label=f"coverage image payload for {new_sample_id}",
        )
        annotation_source = _safe_source_file(
            reserve_root,
            reserve_sample.annotation_path,
            label=f"coverage annotation payload for {new_sample_id}",
        )
        for source, relative_path in (
            (image_source, image_relative),
            (annotation_source, annotation_relative),
        ):
            if relative_path in destinations:
                raise RepairError(f"duplicate output path: {relative_path}")
            destinations.add(relative_path)
            copy_plan.append((source, relative_path))
        repaired_samples.append(added_sample)
        replacement_map[new_sample_id] = reserve_sample.sample_id

    repaired_manifest = BatchManifest.model_validate(
        manifest.model_dump(mode="python") | {"samples": repaired_samples}
    )
    completed_orders = [
        WorkOrder.model_validate(
            order.model_dump(mode="python") | {"status": "simulated_complete"}
        )
        for order in orders
    ]

    staging = Path(tempfile.mkdtemp(prefix=".visiondata-repair-", dir=output_parent))
    try:
        for source, relative_path in copy_plan:
            destination = _destination_path(staging, relative_path)
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(source, destination)

        staging_manifest = staging / "manifest.json"
        staging_manifest.write_text(
            repaired_manifest.model_dump_json(indent=2) + "\n",
            encoding="utf-8",
            newline="\n",
        )
        # The destination was already proven absent by _resolved_new_output.
        # os.replace(directory, directory) raises WinError 5 on some Windows
        # filesystems even when no destination exists; os.rename preserves the
        # same no-overwrite publish contract and works on those systems.
        _publish_staging_directory(staging, resolved_output)
    except Exception:
        if staging.exists():
            shutil.rmtree(staging)
        raise

    manifest_path = resolved_output / "manifest.json"
    return RepairResult(
        output_root=resolved_output,
        manifest_path=manifest_path,
        manifest=repaired_manifest,
        completed_work_orders=completed_orders,
        replacement_map=replacement_map,
    )


__all__ = ["RepairError", "RepairResult", "simulate_repair"]
