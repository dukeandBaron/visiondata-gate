"""Read-only, path-redacted intake adapter for the Omni-AD-30 release.

The adapter deliberately keeps the organizer dataset outside the project tree.
It builds an in-memory, deterministically sampled ``BatchManifest``, calls the
existing VisionData Gate measurement workers, and writes only aggregate
evidence.  No source image, mask, category name, sample identifier, or source
path is serialized into the report.
"""

from __future__ import annotations

from collections import Counter, defaultdict
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
import hashlib
import json
from pathlib import Path
import re
from typing import Any, Iterable
import xml.etree.ElementTree as ET
import zipfile

from PIL import Image, UnidentifiedImageError

from .agents import build_council
from .annotations import inspect_annotations
from .contracts import (
    BatchContract,
    BatchManifest,
    CoverageContract,
    Finding,
    GateResult,
    QualityThresholds,
    SampleRecord,
    Severity,
    ToolTrace,
)
from .coverage import inspect_coverage
from .duplicates import inspect_duplicates
from .evidence import (
    canonical_json_bytes,
    write_canonical_json,
    write_evidence_artifacts,
)
from .policy import apply_policy
from .quality import _new_finding, inspect_image_quality
from .runtime_models import ScenarioProfile
from .tools import inspect_contract_governance, tool_contract_digest


_SHA256_RE = re.compile(r"[0-9a-f]{64}")
_REQUIRED_METADATA_HEADERS = (
    "数据集名称",
    "样本总数",
    "good(train)",
    "good(test)",
    "NG(test)",
)


@dataclass(frozen=True)
class OmniSmokeRun:
    summary_path: Path
    summary_sha256: str
    summary: dict[str, Any]


@dataclass(frozen=True)
class OmniGateRun:
    output_root: Path
    gate_result: GateResult
    gate_result_path: Path
    gate_result_sha256: str
    receipt_path: Path
    receipt_sha256: str
    leader_plan_path: Path
    leader_plan_sha256: str


@dataclass(frozen=True)
class _ImageRecord:
    category: str
    split: str
    state: str
    path: Path
    relative_path: str
    annotation_path: str | None


def _hash_text(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _discover_dataset_root(root: str | Path) -> Path:
    candidate = Path(root).expanduser().resolve(strict=True)
    if not candidate.is_dir():
        raise NotADirectoryError(candidate)
    candidates = [
        candidate,
        *sorted(path for path in candidate.iterdir() if path.is_dir()),
    ]
    matches = [
        path
        for path in candidates
        if len(list(path.glob("*.xlsx"))) == 1
        and any(child.is_dir() for child in path.iterdir())
    ]
    if len(matches) != 1:
        raise ValueError(
            "expected exactly one bounded Omni dataset root with one XLSX file"
        )
    return matches[0]


def _xlsx_cell_value(
    cell: ET.Element,
    *,
    namespace: str,
    shared_strings: list[str],
) -> str | float | int | None:
    cell_type = cell.attrib.get("t")
    value_node = cell.find(f"{{{namespace}}}v")
    if cell_type == "inlineStr":
        return "".join(node.text or "" for node in cell.findall(f".//{{{namespace}}}t"))
    if value_node is None or value_node.text is None:
        return None
    raw = value_node.text
    if cell_type == "s":
        return shared_strings[int(raw)]
    if cell_type in {"str", "b"}:
        return raw
    try:
        numeric = float(raw)
    except ValueError:
        return raw
    return int(numeric) if numeric.is_integer() else numeric


def _column_index(reference: str) -> int:
    letters = "".join(char for char in reference if char.isalpha()).upper()
    result = 0
    for char in letters:
        result = result * 26 + (ord(char) - ord("A") + 1)
    return result - 1


def _load_official_counts(metadata_path: Path) -> dict[str, dict[str, int]]:
    with zipfile.ZipFile(metadata_path) as bundle:
        shared_strings: list[str] = []
        if "xl/sharedStrings.xml" in bundle.namelist():
            shared_root = ET.fromstring(bundle.read("xl/sharedStrings.xml"))
            shared_namespace = shared_root.tag.partition("}")[0].removeprefix("{")
            for item in shared_root.findall(f"{{{shared_namespace}}}si"):
                shared_strings.append(
                    "".join(
                        node.text or ""
                        for node in item.findall(f".//{{{shared_namespace}}}t")
                    )
                )
        sheet_name = "xl/worksheets/sheet1.xml"
        if sheet_name not in bundle.namelist():
            raise ValueError("metadata workbook has no first worksheet")
        sheet_root = ET.fromstring(bundle.read(sheet_name))
    namespace = sheet_root.tag.partition("}")[0].removeprefix("{")
    rows: list[list[Any]] = []
    for row in sheet_root.findall(f".//{{{namespace}}}row"):
        values: dict[int, Any] = {}
        for cell in row.findall(f"{{{namespace}}}c"):
            reference = cell.attrib.get("r", "A1")
            values[_column_index(reference)] = _xlsx_cell_value(
                cell,
                namespace=namespace,
                shared_strings=shared_strings,
            )
        width = max(values, default=-1) + 1
        rows.append([values.get(index) for index in range(width)])
    if not rows:
        raise ValueError("metadata workbook is empty")
    headers = [str(value).strip() if value is not None else "" for value in rows[0]]
    missing = [header for header in _REQUIRED_METADATA_HEADERS if header not in headers]
    if missing:
        raise ValueError("metadata workbook is missing required count columns")
    indexes = {header: headers.index(header) for header in _REQUIRED_METADATA_HEADERS}
    result: dict[str, dict[str, int]] = {}
    for row in rows[1:]:
        if indexes["数据集名称"] >= len(row) or row[indexes["数据集名称"]] is None:
            continue
        category = str(row[indexes["数据集名称"]]).strip()
        if not category or category in result:
            raise ValueError("metadata workbook has blank or duplicate category names")
        counts: dict[str, int] = {}
        for output_key, header in (
            ("total", "样本总数"),
            ("train_good", "good(train)"),
            ("test_good", "good(test)"),
            ("test_anomaly", "NG(test)"),
        ):
            index = indexes[header]
            if index >= len(row) or not isinstance(row[index], (int, float)):
                raise ValueError("metadata workbook contains a non-numeric count")
            counts[output_key] = int(row[index])
        result[category] = counts
    if not result:
        raise ValueError("metadata workbook contains no category rows")
    return result


def _png_files(directory: Path) -> list[Path]:
    if not directory.is_dir():
        return []
    return sorted(
        path
        for path in directory.iterdir()
        if path.is_file() and path.suffix.casefold() == ".png"
    )


def _scan_dataset(
    dataset_root: Path,
    official_counts: dict[str, dict[str, int]],
) -> tuple[list[_ImageRecord], dict[str, Any]]:
    actual_categories = {
        path.name
        for path in dataset_root.iterdir()
        if path.is_dir() and not path.is_symlink()
    }
    official_categories = set(official_counts)
    records: list[_ImageRecord] = []
    actual_by_category: dict[str, Counter[str]] = {}
    mask_keys: set[tuple[str, str, str]] = set()
    anomaly_keys: set[tuple[str, str, str]] = set()
    duplicate_mask_key_count = 0

    for category in sorted(actual_categories & official_categories):
        category_root = dataset_root / category
        counts: Counter[str] = Counter()
        for path in _png_files(category_root / "train" / "good"):
            relative = path.relative_to(dataset_root).as_posix()
            records.append(
                _ImageRecord(category, "train", "good", path, relative, None)
            )
            counts["train_good"] += 1
        test_root = category_root / "test"
        if test_root.is_dir():
            for state_root in sorted(
                path for path in test_root.iterdir() if path.is_dir()
            ):
                state = state_root.name
                for path in _png_files(state_root):
                    relative = path.relative_to(dataset_root).as_posix()
                    is_good = state.casefold() == "good"
                    annotation_path = None
                    if not is_good:
                        annotation = category_root / "ground_truth" / state / path.name
                        annotation_path = annotation.relative_to(
                            dataset_root
                        ).as_posix()
                        anomaly_keys.add((category, state, path.stem))
                    records.append(
                        _ImageRecord(
                            category,
                            "test",
                            state,
                            path,
                            relative,
                            annotation_path,
                        )
                    )
                    counts["test_good" if is_good else "test_anomaly"] += 1
        ground_truth_root = category_root / "ground_truth"
        if ground_truth_root.is_dir():
            for state_root in sorted(
                path for path in ground_truth_root.iterdir() if path.is_dir()
            ):
                for path in _png_files(state_root):
                    key = (category, state_root.name, path.stem)
                    duplicate_mask_key_count += int(key in mask_keys)
                    mask_keys.add(key)
        counts["total"] = (
            counts["train_good"] + counts["test_good"] + counts["test_anomaly"]
        )
        actual_by_category[category] = counts

    mismatch_categories = 0
    aggregate_deltas: Counter[str] = Counter()
    for category in sorted(actual_categories & official_categories):
        official = official_counts[category]
        actual = actual_by_category[category]
        deltas = {key: actual[key] - official[key] for key in official}
        if any(deltas.values()):
            mismatch_categories += 1
        aggregate_deltas.update(deltas)

    totals = Counter()
    for counts in actual_by_category.values():
        totals.update(counts)
    metadata_totals = Counter()
    for counts in official_counts.values():
        metadata_totals.update(counts)
    structure = {
        "category_count": len(actual_categories & official_categories),
        "metadata_category_count": len(official_categories),
        "category_missing_from_tree_count": len(
            official_categories - actual_categories
        ),
        "category_missing_from_metadata_count": len(
            actual_categories - official_categories
        ),
        "image_count": len(records),
        "train_good_count": totals["train_good"],
        "test_good_count": totals["test_good"],
        "test_anomaly_count": totals["test_anomaly"],
        "mask_count": len(mask_keys),
        "training_normal_only": all(
            record.split != "train" or record.state.casefold() == "good"
            for record in records
        ),
        "missing_mask_count": len(anomaly_keys - mask_keys),
        "extra_mask_count": len(mask_keys - anomaly_keys),
        "duplicate_mask_key_count": duplicate_mask_key_count,
        "metadata_image_count": metadata_totals["total"],
        "metadata_mismatch_category_count": mismatch_categories,
        "metadata_count_deltas": dict(sorted(aggregate_deltas.items())),
    }
    return records, structure


def _bucket(record: _ImageRecord) -> str:
    if record.split == "train":
        return "train_good"
    return "test_good" if record.state.casefold() == "good" else "test_anomaly"


def _select_records(
    records: Iterable[_ImageRecord],
    *,
    per_bucket: int,
    seed: int,
) -> tuple[list[_ImageRecord], int]:
    groups: dict[tuple[str, str], list[_ImageRecord]] = defaultdict(list)
    for record in records:
        groups[(record.category, _bucket(record))].append(record)
    selected: list[_ImageRecord] = []
    missing_bucket_count = 0
    categories = sorted({record.category for record in records})
    for category in categories:
        for bucket in ("train_good", "test_good", "test_anomaly"):
            group = groups.get((category, bucket), [])
            if not group:
                missing_bucket_count += 1
                continue
            ordered = sorted(
                group,
                key=lambda item: _hash_text(f"{seed}\0{item.relative_path}"),
            )
            selected.extend(ordered[:per_bucket])
    return selected, missing_bucket_count


def _sample_record(record: _ImageRecord, *, seed: int) -> SampleRecord:
    alias = f"category-{_hash_text(record.category)[:12]}"
    identity = str(seed) + "\0" + record.relative_path
    sample_id = f"omni-{_hash_text(identity)[:20]}"
    return SampleRecord(
        sample_id=sample_id,
        relative_path=record.relative_path,
        split=record.split,
        category=alias,
        view="catalog",
        condition="observed",
        annotation_path=record.annotation_path,
    )


def _image_size(path: Path) -> tuple[int, int] | None:
    try:
        with Image.open(path) as image:
            image.load()
            return image.size
    except (UnidentifiedImageError, SyntaxError, OSError):
        return None


def _neutral_contract(
    *,
    width: int,
    height: int,
    categories: list[str] | None = None,
) -> BatchContract:
    return BatchContract(
        required_splits=["train", "test"],
        annotations_required=False,
        thresholds=QualityThresholds(
            expected_width=max(width, 16),
            expected_height=max(height, 16),
            min_mean_luma=0.0,
            max_mean_luma=255.0,
            min_sharpness=0.0,
            min_mask_fraction=0.0,
            max_mask_fraction=1.0,
            near_duplicate_hamming=0,
        ),
        coverage=CoverageContract(
            categories=categories or ["bounded-smoke"],
            views=["catalog"],
            conditions=["observed"],
            min_per_cell=1,
            splits=["train", "test"],
        ),
        policy_version="omni-readonly-smoke-v1",
    )


def _gate_measurement_contract(*, width: int, height: int) -> BatchContract:
    """Return the frozen pixel policy used for one native-size group."""

    return BatchContract(
        contract_id="omni-readonly-native-size-measurement-v1",
        required_splits=["train", "test"],
        annotations_required=False,
        thresholds=QualityThresholds(
            expected_width=max(width, 16),
            expected_height=max(height, 16),
            min_mean_luma=35.0,
            max_mean_luma=225.0,
            min_sharpness=18.0,
            min_mask_fraction=0.002,
            max_mask_fraction=0.65,
            near_duplicate_hamming=4,
        ),
        coverage=CoverageContract(
            categories=["bounded-group"],
            views=["catalog"],
            conditions=["observed"],
            min_per_cell=1,
            splits=["train", "test"],
        ),
        policy_version="omni-readonly-native-size-measurement-v1",
    )


def _gate_policy_contract(category_aliases: list[str]) -> BatchContract:
    """Return the cross-group industrial policy contract.

    Pixel dimensions are enforced by the native-size measurement contracts.
    The policy contract governs split, annotation, coverage, evidence, and
    scenario-level checks after those measurements are aggregated.
    """

    return BatchContract(
        contract_id="omni-readonly-variable-resolution-gate-v1",
        required_splits=["train", "test"],
        annotations_required=False,
        thresholds=QualityThresholds(
            expected_width=16,
            expected_height=16,
            min_mean_luma=35.0,
            max_mean_luma=225.0,
            min_sharpness=18.0,
            min_mask_fraction=0.002,
            max_mask_fraction=0.65,
            near_duplicate_hamming=4,
        ),
        coverage=CoverageContract(
            categories=category_aliases,
            views=["catalog"],
            conditions=["observed"],
            min_per_cell=1,
            splits=["train", "test"],
        ),
        policy_version="omni-industrial-readonly-gate-v1",
    )


def _redacted_manifest(manifest: BatchManifest) -> BatchManifest:
    samples = []
    for sample in manifest.samples:
        samples.append(
            sample.model_copy(
                update={
                    "relative_path": f"objects/{sample.sample_id}.asset",
                    "annotation_path": (
                        f"annotations/{sample.sample_id}.asset"
                        if sample.annotation_path is not None
                        else None
                    ),
                }
            )
        )
    return manifest.model_copy(update={"samples": samples})


def _redact_evidence(value: Any, *, salt: str, key: str = "") -> Any:
    if isinstance(value, dict):
        return {
            name: _redact_evidence(item, salt=salt, key=name)
            for name, item in sorted(value.items())
        }
    if isinstance(value, list):
        return [_redact_evidence(item, salt=salt, key=key) for item in value]
    if key in {"relative_path", "annotation_path"} and isinstance(value, str):
        return f"object-ref-{_hash_text(salt + chr(0) + value)[:24]}"
    if key in {"relative_paths", "annotation_paths"} and isinstance(value, str):
        return f"object-ref-{_hash_text(salt + chr(0) + value)[:24]}"
    if key == "sha256" and isinstance(value, str):
        return f"digest-ref-{_hash_text(salt + chr(0) + value)[:24]}"
    return value


def _redacted_finding(finding: Finding, *, salt: str) -> Finding:
    evidence = _redact_evidence(finding.evidence, salt=salt)
    return _new_finding(
        tool=finding.tool,
        code=finding.code,
        severity=finding.severity,
        sample_ids=finding.sample_ids,
        summary=finding.summary,
        evidence=evidence,
        recommended_action=finding.recommended_action,
    )


def _counter_metrics(
    target: Counter[str], metrics: dict[str, int | float | str]
) -> None:
    target.update(
        {
            key: int(value)
            for key, value in metrics.items()
            if key.endswith("_count") and isinstance(value, (int, float))
        }
    )


def _aggregate_trace(
    *,
    sequence: int,
    tool: str,
    source_archive_sha256: str,
    selection_manifest_sha256: str,
    parameters: dict[str, Any],
    findings: list[Finding],
    metrics: dict[str, int | float | str],
    errors: list[str],
) -> ToolTrace:
    input_payload = {
        "tool": tool,
        "source_archive_sha256": source_archive_sha256,
        "selection_manifest_sha256": selection_manifest_sha256,
        "parameters": parameters,
    }
    result_payload = {
        "findings": [item.model_dump(mode="json") for item in findings],
        "metrics": metrics,
        "errors": sorted(errors),
    }
    return ToolTrace(
        sequence=sequence,
        tool=tool,
        status="error" if errors else "ok",
        input_sha256=hashlib.sha256(canonical_json_bytes(input_payload)).hexdigest(),
        parameters=parameters,
        result_sha256=hashlib.sha256(canonical_json_bytes(result_payload)).hexdigest(),
        finding_ids=[item.finding_id for item in findings],
        error="|".join(sorted(errors)) if errors else None,
        contract_version="1.0.0",
        contract_digest=tool_contract_digest(tool, include_optional=True),
        adapter="external-readonly-omni-v1",
    )


def _dynamic_task_receipt(
    *,
    task_id: str,
    worker_id: str,
    trigger: str,
    input_refs: list[str],
    outputs: dict[str, Any],
    decision_effect: str,
) -> dict[str, Any]:
    result_sha256 = hashlib.sha256(canonical_json_bytes(outputs)).hexdigest()
    return {
        "task_id": task_id,
        "worker_id": worker_id,
        "trigger": trigger,
        "dispatch_basis": "intermediate_evidence",
        "status": "completed",
        "input_refs": sorted(input_refs),
        "outputs": outputs,
        "result_sha256": result_sha256,
        "decision_effect": decision_effect,
    }


def _dynamic_leader_followups(
    initial_result: GateResult,
    *,
    structure: dict[str, Any],
    native_group_count: int,
    source_archive_sha256: str,
) -> tuple[list[dict[str, Any]], list[Finding]]:
    """Dispatch evidence-dependent follow-up workers after the first Judge pass.

    These branches cannot be known from the static tool catalog alone: they are
    activated only by observed metadata drift, native-resolution fan-out, or
    incompatible actions attached to the same redacted sample.  The workers are
    deterministic and read-only; their receipts bind the replan to its inputs.
    """

    task_builders: list[Any] = []
    additional_findings: list[Finding] = []
    metadata_findings = [
        item for item in initial_result.findings if item.code == "METADATA_COUNT_DRIFT"
    ]
    if metadata_findings:
        outputs = {
            "metadata_mismatch_category_count": structure[
                "metadata_mismatch_category_count"
            ],
            "aggregate_count_deltas": structure["metadata_count_deltas"],
            "tree_image_count": structure["image_count"],
            "metadata_image_count": structure["metadata_image_count"],
            "resolution": "investigation_required",
        }
        task_builders.append(
            lambda outputs=outputs, metadata_findings=metadata_findings: (
                _dynamic_task_receipt(
                    task_id="followup.metadata-reconciliation",
                    worker_id="worker.metadata-reconciliation",
                    trigger="observed METADATA_COUNT_DRIFT after the first evidence wave",
                    input_refs=[
                        f"finding:{item.finding_id}" for item in metadata_findings
                    ]
                    + [f"sha256:{source_archive_sha256}"],
                    outputs=outputs,
                    decision_effect=(
                        "preserve INVESTIGATE work order; automated repair is forbidden"
                    ),
                )
            )
        )

    if native_group_count > 1:
        quality_traces = [
            trace
            for trace in initial_result.tool_trace
            if trace.tool == "image_quality"
        ]
        trace_ok = bool(quality_traces) and all(
            trace.status == "ok" for trace in quality_traces
        )
        outputs = {
            "native_resolution_group_count": native_group_count,
            "quality_trace_complete": trace_ok,
            "group_policy": "measure_per_native_size_then_reconcile",
            "resolution": "supplemental_evidence_accepted" if trace_ok else "defer",
        }
        task_builders.append(
            lambda outputs=outputs, quality_traces=quality_traces, trace_ok=trace_ok: (
                _dynamic_task_receipt(
                    task_id="followup.native-resolution-reconciliation",
                    worker_id="worker.native-resolution-reconciler",
                    trigger=(
                        "more than one native resolution group was discovered at intake"
                    ),
                    input_refs=[
                        f"trace:{trace.sequence}:{trace.tool}"
                        for trace in quality_traces
                    ],
                    outputs=outputs,
                    decision_effect=(
                        "accept group-aware quality evidence"
                        if trace_ok
                        else "force DEFER because group evidence is incomplete"
                    ),
                )
            )
        )
        if not trace_ok:
            additional_findings.append(
                _new_finding(
                    tool="governance_audit",
                    code="NATIVE_RESOLUTION_EVIDENCE_INCOMPLETE",
                    severity=Severity.HIGH,
                    sample_ids=[],
                    summary=(
                        "Native-resolution groups were observed without complete "
                        "group-aware quality evidence."
                    ),
                    evidence={"native_resolution_group_count": native_group_count},
                    recommended_action="investigate missing resolution-group evidence",
                )
            )

    actions_by_sample: dict[str, set[str]] = defaultdict(set)
    reasons_by_sample: dict[str, set[str]] = defaultdict(set)
    for order in initial_result.work_orders:
        for sample_id in order.sample_ids:
            actions_by_sample[sample_id].add(order.action)
            reasons_by_sample[sample_id].update(order.reason_codes)
    conflicts = {
        sample_id: sorted(actions)
        for sample_id, actions in actions_by_sample.items()
        if len(actions) > 1
    }
    if conflicts:
        conflict_samples = sorted(conflicts)
        finding = _new_finding(
            tool="governance_audit",
            code="CROSS_TOOL_ACTION_CONFLICT",
            severity=Severity.HIGH,
            sample_ids=conflict_samples,
            summary=(
                "Multiple verified tools propose incompatible remediation actions "
                "for the same redacted sample."
            ),
            evidence={
                "conflict_sample_count": len(conflict_samples),
                "action_sets": [conflicts[sample_id] for sample_id in conflict_samples],
                "reason_code_sets": [
                    sorted(reasons_by_sample[sample_id])
                    for sample_id in conflict_samples
                ],
            },
            recommended_action=(
                "investigate and sequence remediation before any automated repair"
            ),
        )
        additional_findings.append(finding)
        relevant_orders = [
            order
            for order in initial_result.work_orders
            if set(order.sample_ids) & set(conflict_samples)
        ]
        task_builders.append(
            lambda relevant_orders=relevant_orders, conflict_samples=conflict_samples, finding=finding: (
                _dynamic_task_receipt(
                    task_id="followup.cross-tool-conflict-adjudication",
                    worker_id="worker.remediation-conflict-adjudicator",
                    trigger=(
                        "the first Judge pass attached multiple actions to one sample"
                    ),
                    input_refs=[
                        f"work-order:{order.work_order_id}" for order in relevant_orders
                    ],
                    outputs={
                        "conflict_sample_count": len(conflict_samples),
                        "finding_id": finding.finding_id,
                        "resolution": "investigation_required",
                    },
                    decision_effect=(
                        "add CROSS_TOOL_ACTION_CONFLICT and route the affected samples "
                        "to investigation"
                    ),
                )
            )
        )
    tasks: list[dict[str, Any]] = []
    if task_builders:
        with ThreadPoolExecutor(
            max_workers=len(task_builders),
            thread_name_prefix="omni-leader-followup",
        ) as pool:
            tasks = [
                future.result()
                for future in [pool.submit(job) for job in task_builders]
            ]
        tasks.sort(key=lambda item: str(item["task_id"]))
        for dispatch_index, task in enumerate(tasks, start=1):
            task["dispatch_index"] = dispatch_index
            task["dispatch_mode"] = "parallel_after_initial_judge"
            task["planned_before_initial_evidence"] = False
    return tasks, additional_findings


def _full_decode_summary(dataset_root: Path) -> dict[str, int]:
    checked = 0
    failures = 0
    signatures: set[tuple[int, int, str]] = set()
    for path in sorted(dataset_root.glob("*/*/*/*.png")):
        checked += 1
        try:
            with Image.open(path) as image:
                image.verify()
            with Image.open(path) as image:
                signatures.add((image.width, image.height, image.mode))
        except (UnidentifiedImageError, SyntaxError, OSError):
            failures += 1
    return {
        "checked_count": checked,
        "failure_count": failures,
        "image_signature_group_count": len(signatures),
    }


def run_omni_readonly_smoke(
    root: str | Path,
    output: str | Path,
    *,
    source_archive_sha256: str,
    per_bucket: int = 2,
    seed: int = 20260813,
    full_decode: bool = False,
) -> OmniSmokeRun:
    """Run a fixed-denominator real-data smoke without copying source assets."""

    if not _SHA256_RE.fullmatch(source_archive_sha256):
        raise ValueError("source_archive_sha256 must be a lowercase SHA-256 digest")
    if per_bucket < 1 or per_bucket > 20:
        raise ValueError("per_bucket must be between 1 and 20")
    dataset_root = _discover_dataset_root(root)
    metadata_path = next(iter(dataset_root.glob("*.xlsx")))
    official_counts = _load_official_counts(metadata_path)
    records, structure = _scan_dataset(dataset_root, official_counts)
    selected, missing_bucket_count = _select_records(
        records,
        per_bucket=per_bucket,
        seed=seed,
    )
    samples = [_sample_record(record, seed=seed) for record in selected]
    manifest = BatchManifest(
        batch_id=f"omni-readonly-smoke-{seed}",
        seed=seed,
        samples=samples,
    )
    sample_by_path = {
        record.relative_path: sample
        for record, sample in zip(selected, samples, strict=True)
    }
    dimension_groups: dict[tuple[int, int] | None, list[_ImageRecord]] = defaultdict(
        list
    )
    for record in selected:
        dimension_groups[_image_size(record.path)].append(record)

    finding_codes: Counter[str] = Counter()
    quality_metrics: Counter[str] = Counter()
    duplicate_metrics: Counter[str] = Counter()
    annotation_metrics: Counter[str] = Counter()
    worker_errors: list[str] = []
    worker_calls = 0

    for size, group in sorted(
        dimension_groups.items(), key=lambda item: item[0] or (0, 0)
    ):
        width, height = size or (16, 16)
        subset = BatchManifest(
            batch_id=manifest.batch_id,
            seed=seed,
            samples=[sample_by_path[item.relative_path] for item in group],
        )
        contract = _neutral_contract(width=width, height=height)
        try:
            findings, metrics = inspect_image_quality(dataset_root, subset, contract)
            finding_codes.update(item.code for item in findings)
            quality_metrics.update(
                {
                    key: int(value)
                    for key, value in metrics.items()
                    if key.endswith("_count")
                }
            )
        except Exception as exc:  # fail closed and redact source context
            worker_errors.append(f"image_quality:{type(exc).__name__}")
        worker_calls += 1
        try:
            findings, metrics = inspect_duplicates(dataset_root, subset, contract)
            finding_codes.update(item.code for item in findings)
            duplicate_metrics.update(
                {
                    key: int(value)
                    for key, value in metrics.items()
                    if key.endswith("_count")
                }
            )
        except Exception as exc:  # fail closed and redact source context
            worker_errors.append(f"duplicate_leakage:{type(exc).__name__}")
        worker_calls += 1

        anomaly_samples = [
            sample_by_path[item.relative_path]
            for item in group
            if item.annotation_path is not None
        ]
        if anomaly_samples:
            anomaly_manifest = BatchManifest(
                batch_id=manifest.batch_id,
                seed=seed,
                samples=anomaly_samples,
            )
            annotation_contract = contract.model_copy(
                update={"annotations_required": True}
            )
            try:
                findings, metrics = inspect_annotations(
                    dataset_root,
                    anomaly_manifest,
                    annotation_contract,
                )
                finding_codes.update(item.code for item in findings)
                annotation_metrics.update(
                    {
                        key: int(value)
                        for key, value in metrics.items()
                        if key.endswith("_count")
                    }
                )
            except Exception as exc:  # fail closed and redact source context
                worker_errors.append(f"annotation_integrity:{type(exc).__name__}")
            worker_calls += 1

    category_aliases = sorted({sample.category for sample in manifest.samples})
    coverage_contract = _neutral_contract(
        width=16,
        height=16,
        categories=category_aliases,
    )
    try:
        findings, coverage_metrics = inspect_coverage(
            dataset_root,
            manifest,
            coverage_contract,
        )
        finding_codes.update(item.code for item in findings)
    except Exception as exc:  # fail closed and redact source context
        coverage_metrics = {"missing_cell_count": -1}
        worker_errors.append(f"coverage_matrix:{type(exc).__name__}")
    worker_calls += 1

    metadata_drift = bool(
        structure["metadata_mismatch_category_count"]
        or structure["category_missing_from_tree_count"]
        or structure["category_missing_from_metadata_count"]
    )
    if metadata_drift:
        finding_codes["METADATA_COUNT_DRIFT"] += 1
    structure_failure = bool(
        not structure["training_normal_only"]
        or structure["missing_mask_count"]
        or structure["extra_mask_count"]
        or structure["duplicate_mask_key_count"]
    )
    decode = (
        _full_decode_summary(dataset_root)
        if full_decode
        else {
            "checked_count": len(selected),
            "failure_count": quality_metrics["decode_failure_count"],
            "image_signature_group_count": len(
                {size for size in dimension_groups if size is not None}
            ),
        }
    )
    blockers = ["BOUNDED_SMOKE_NOT_FULL_RELEASE", "PRODUCTION_AUTHORIZATION_REQUIRED"]
    if metadata_drift:
        blockers.append("METADATA_COUNT_DRIFT")
    if structure_failure:
        blockers.append("DATASET_STRUCTURE_INTEGRITY_FAILURE")
    if decode["failure_count"]:
        blockers.append("IMAGE_DECODE_FAILURE")
    if worker_errors:
        blockers.append("TOOL_EXECUTION_FAILURE")
    if missing_bucket_count:
        blockers.append("SMOKE_BUCKET_MISSING")

    payload = {
        "schema_version": "visiondata-gate.omni-readonly-smoke.v1",
        "redacted": True,
        "completion_state": "REAL_DATA_SMOKE_COMPLETED",
        "data_bytes_usable_for_local_readonly_development": not (
            structure_failure or decode["failure_count"] or worker_errors
        ),
        "release_decision": "DEFER",
        "source": {
            "kind": "organizer_omni_ad_30_release",
            "archive_sha256": source_archive_sha256,
            "source_assets_copied_into_project": False,
        },
        "scope": {
            "mode": "external_read_only",
            "seed": seed,
            "per_category_bucket_limit": per_bucket,
            "selected_image_count": len(selected),
            "selected_category_count": len(category_aliases),
            "selected_bucket_count": 3 * len(category_aliases),
            "missing_bucket_count": missing_bucket_count,
            "full_dataset_decode_requested": full_decode,
        },
        "dataset_structure": structure,
        "decode_audit": decode,
        "tool_execution": {
            "tools": [
                "image_quality",
                "duplicate_leakage",
                "annotation_integrity",
                "coverage_matrix",
            ],
            "worker_call_count": worker_calls,
            "worker_error_codes": sorted(worker_errors),
            "quality_count_metrics": dict(sorted(quality_metrics.items())),
            "duplicate_count_metrics": dict(sorted(duplicate_metrics.items())),
            "annotation_count_metrics": dict(sorted(annotation_metrics.items())),
            "coverage_count_metrics": {
                key: value
                for key, value in sorted(coverage_metrics.items())
                if key.endswith("_count")
            },
            "finding_code_counts": dict(sorted(finding_codes.items())),
        },
        "selection_manifest_sha256": hashlib.sha256(
            canonical_json_bytes(manifest)
        ).hexdigest(),
        "blockers": sorted(set(blockers)),
        "claim_boundary": (
            "This proves a bounded, read-only smoke on organizer-provided bytes. "
            "It is not a full release decision, customer-site validation, model-accuracy "
            "result, production deployment, or organizer endorsement."
        ),
    }
    output_path = Path(output).expanduser().resolve()
    output_path.parent.mkdir(parents=True, exist_ok=True)
    digest = write_canonical_json(output_path, payload)
    serialized = output_path.read_text(encoding="utf-8")
    forbidden = [str(dataset_root), ".png"]
    quoted_category_names = [
        json.dumps(category, ensure_ascii=False) for category in official_counts
    ]
    if any(item in serialized for item in [*forbidden, *quoted_category_names]):
        output_path.unlink(missing_ok=True)
        raise RuntimeError("redaction invariant failed; report was removed")
    return OmniSmokeRun(output_path, digest, payload)


def run_omni_readonly_gate(
    root: str | Path,
    output: str | Path,
    *,
    source_archive_sha256: str,
    per_bucket: int = 2,
    seed: int = 20260813,
) -> OmniGateRun:
    """Run organizer bytes through Workers, Council, and industrial Policy Gate."""

    if not _SHA256_RE.fullmatch(source_archive_sha256):
        raise ValueError("source_archive_sha256 must be a lowercase SHA-256 digest")
    if per_bucket < 1 or per_bucket > 20:
        raise ValueError("per_bucket must be between 1 and 20")
    dataset_root = _discover_dataset_root(root)
    metadata_path = next(iter(dataset_root.glob("*.xlsx")))
    official_counts = _load_official_counts(metadata_path)
    records, structure = _scan_dataset(dataset_root, official_counts)
    selected, missing_bucket_count = _select_records(
        records, per_bucket=per_bucket, seed=seed
    )
    raw_manifest = BatchManifest(
        batch_id=f"omni-readonly-gate-{seed}",
        seed=seed,
        samples=[_sample_record(record, seed=seed) for record in selected],
    )
    manifest = _redacted_manifest(raw_manifest)
    selection_manifest_sha256 = hashlib.sha256(
        canonical_json_bytes(manifest)
    ).hexdigest()
    sample_by_path = {
        record.relative_path: sample
        for record, sample in zip(selected, raw_manifest.samples, strict=True)
    }
    dimension_groups: dict[tuple[int, int] | None, list[_ImageRecord]] = defaultdict(
        list
    )
    for record in selected:
        dimension_groups[_image_size(record.path)].append(record)

    findings_by_tool: dict[str, list[Finding]] = {
        name: []
        for name in (
            "image_quality",
            "duplicate_leakage",
            "annotation_integrity",
            "coverage_matrix",
            "governance_audit",
        )
    }
    metrics_by_tool: dict[str, Counter[str]] = {
        name: Counter()
        for name in (
            "image_quality",
            "duplicate_leakage",
            "annotation_integrity",
        )
    }
    errors_by_tool: dict[str, list[str]] = {name: [] for name in findings_by_tool}
    native_group_count = 0
    for size, group in sorted(
        dimension_groups.items(), key=lambda item: item[0] or (0, 0)
    ):
        native_group_count += 1
        width, height = size or (16, 16)
        subset = BatchManifest(
            batch_id=raw_manifest.batch_id,
            seed=seed,
            samples=[sample_by_path[item.relative_path] for item in group],
        )
        contract = _gate_measurement_contract(width=width, height=height)
        for tool_name, implementation in (
            ("image_quality", inspect_image_quality),
            ("duplicate_leakage", inspect_duplicates),
        ):
            try:
                group_findings, group_metrics = implementation(
                    dataset_root, subset, contract
                )
                findings_by_tool[tool_name].extend(
                    _redacted_finding(
                        item,
                        salt=source_archive_sha256,
                    )
                    for item in group_findings
                )
                _counter_metrics(metrics_by_tool[tool_name], group_metrics)
            except Exception as exc:  # fail closed without leaking source context
                errors_by_tool[tool_name].append(type(exc).__name__)

        anomaly_samples = [
            sample_by_path[item.relative_path]
            for item in group
            if item.annotation_path is not None
        ]
        if anomaly_samples:
            annotation_manifest = BatchManifest(
                batch_id=raw_manifest.batch_id,
                seed=seed,
                samples=anomaly_samples,
            )
            annotation_contract = contract.model_copy(
                update={"annotations_required": True}
            )
            try:
                group_findings, group_metrics = inspect_annotations(
                    dataset_root, annotation_manifest, annotation_contract
                )
                findings_by_tool["annotation_integrity"].extend(
                    _redacted_finding(
                        item,
                        salt=source_archive_sha256,
                    )
                    for item in group_findings
                )
                _counter_metrics(metrics_by_tool["annotation_integrity"], group_metrics)
            except Exception as exc:  # fail closed without leaking source context
                errors_by_tool["annotation_integrity"].append(type(exc).__name__)

    category_aliases = sorted({sample.category for sample in manifest.samples})
    policy_contract = _gate_policy_contract(category_aliases)
    try:
        coverage_findings, coverage_metrics = inspect_coverage(
            dataset_root, raw_manifest, policy_contract
        )
        findings_by_tool["coverage_matrix"].extend(
            _redacted_finding(item, salt=source_archive_sha256)
            for item in coverage_findings
        )
    except Exception as exc:  # fail closed without leaking source context
        coverage_metrics = {"missing_cell_count": -1}
        errors_by_tool["coverage_matrix"].append(type(exc).__name__)

    try:
        governance_findings, governance_metrics = inspect_contract_governance(
            dataset_root, raw_manifest, policy_contract
        )
        findings_by_tool["governance_audit"].extend(
            _redacted_finding(item, salt=source_archive_sha256)
            for item in governance_findings
        )
    except Exception as exc:  # fail closed without leaking source context
        governance_metrics = {"missing_cell_count": -1, "unknown_cell_count": -1}
        errors_by_tool["governance_audit"].append(type(exc).__name__)

    metadata_drift = bool(
        structure["metadata_mismatch_category_count"]
        or structure["category_missing_from_tree_count"]
        or structure["category_missing_from_metadata_count"]
    )
    if metadata_drift:
        findings_by_tool["governance_audit"].append(
            _new_finding(
                tool="governance_audit",
                code="METADATA_COUNT_DRIFT",
                severity=Severity.HIGH,
                sample_ids=[],
                summary="Organizer metadata counts differ from the extracted asset tree.",
                evidence={
                    "mismatch_category_count": structure[
                        "metadata_mismatch_category_count"
                    ],
                    "aggregate_count_deltas": structure["metadata_count_deltas"],
                    "source_archive_sha256": source_archive_sha256,
                },
                recommended_action="investigate organizer metadata and freeze counts",
            )
        )
    if missing_bucket_count:
        findings_by_tool["governance_audit"].append(
            _new_finding(
                tool="governance_audit",
                code="SMOKE_BUCKET_MISSING",
                severity=Severity.HIGH,
                sample_ids=[],
                summary="At least one fixed smoke sampling bucket is empty.",
                evidence={"missing_bucket_count": missing_bucket_count},
                recommended_action="investigate dataset coverage",
            )
        )

    aggregate_metrics: dict[str, int | float | str] = {
        "sample_count": len(manifest.samples),
        "tool_count": 5,
        "tool_error_count": sum(bool(value) for value in errors_by_tool.values()),
        "source_image_count": structure["image_count"],
        "source_mask_count": structure["mask_count"],
        "selected_image_count": len(manifest.samples),
        "native_image_signature_group_count": native_group_count,
        "metadata_count_delta_total": structure["metadata_count_deltas"].get(
            "total", 0
        ),
        "metadata_mismatch_category_count": structure[
            "metadata_mismatch_category_count"
        ],
        "training_normal_only": str(structure["training_normal_only"]).lower(),
    }
    for prefix, tool_name in (
        ("quality", "image_quality"),
        ("duplicates", "duplicate_leakage"),
        ("annotation", "annotation_integrity"),
    ):
        for key, value in sorted(metrics_by_tool[tool_name].items()):
            aggregate_metrics[f"{prefix}_{key}"] = value
    for key, value in sorted(coverage_metrics.items()):
        aggregate_metrics[f"coverage_{key}"] = value
    for key, value in sorted(governance_metrics.items()):
        aggregate_metrics[f"governance_{key}"] = value

    traces: list[ToolTrace] = []
    for sequence, tool_name in enumerate(findings_by_tool, start=1):
        parameters: dict[str, Any] = {
            "mode": "external_read_only_variable_resolution",
            "native_size_group_count": native_group_count,
            "selected_image_count": len(manifest.samples),
        }
        if tool_name == "image_quality":
            parameters["threshold_policy"] = "fixed_per-native-size-group"
        elif tool_name == "duplicate_leakage":
            parameters["cross_group_limitation"] = (
                "near-duplicate comparison is bounded within native-size groups"
            )
        elif tool_name == "annotation_integrity":
            parameters["scope"] = "selected_anomaly_samples"
        elif tool_name in {"coverage_matrix", "governance_audit"}:
            parameters["policy_contract"] = policy_contract.contract_id
        trace_metrics = (
            dict(metrics_by_tool[tool_name])
            if tool_name in metrics_by_tool
            else coverage_metrics
            if tool_name == "coverage_matrix"
            else governance_metrics
        )
        traces.append(
            _aggregate_trace(
                sequence=sequence,
                tool=tool_name,
                source_archive_sha256=source_archive_sha256,
                selection_manifest_sha256=selection_manifest_sha256,
                parameters=parameters,
                findings=findings_by_tool[tool_name],
                metrics=trace_metrics,
                errors=errors_by_tool[tool_name],
            )
        )

    findings = sorted(
        [item for values in findings_by_tool.values() for item in values],
        key=lambda item: (item.tool, item.code, item.finding_id),
    )
    aggregate_metrics["finding_count"] = len(findings)
    input_sha256 = hashlib.sha256(
        canonical_json_bytes(
            {
                "source_archive_sha256": source_archive_sha256,
                "selection_manifest_sha256": selection_manifest_sha256,
                "contract": policy_contract,
                "tool_result_sha256": [trace.result_sha256 for trace in traces],
            }
        )
    ).hexdigest()
    initial_council = build_council(findings, traces, aggregate_metrics)
    initial_result = apply_policy(
        manifest,
        policy_contract,
        findings,
        traces,
        aggregate_metrics,
        initial_council,
        scenario_profile=ScenarioProfile.INDUSTRIAL,
        input_sha256=input_sha256,
        run_id=f"omni-gate-initial-{input_sha256[:12]}",
    )
    dynamic_tasks, followup_findings = _dynamic_leader_followups(
        initial_result,
        structure=structure,
        native_group_count=native_group_count,
        source_archive_sha256=source_archive_sha256,
    )
    if followup_findings:
        findings = sorted(
            [*findings, *followup_findings],
            key=lambda item: (item.tool, item.code, item.finding_id),
        )
        governance_trace = next(
            trace for trace in traces if trace.tool == "governance_audit"
        )
        governance_findings = [
            item for item in findings if item.tool == "governance_audit"
        ]
        governance_metrics = {
            **governance_metrics,
            "dynamic_followup_finding_count": len(followup_findings),
        }
        replacement_trace = _aggregate_trace(
            sequence=governance_trace.sequence,
            tool="governance_audit",
            source_archive_sha256=source_archive_sha256,
            selection_manifest_sha256=selection_manifest_sha256,
            parameters={
                **governance_trace.parameters,
                "leader_followup_count": len(dynamic_tasks),
            },
            findings=governance_findings,
            metrics=governance_metrics,
            errors=errors_by_tool["governance_audit"],
        )
        traces = [
            replacement_trace if trace.tool == "governance_audit" else trace
            for trace in traces
        ]
    aggregate_metrics["finding_count"] = len(findings)
    aggregate_metrics["leader_dynamic_task_count"] = len(dynamic_tasks)
    aggregate_metrics["leader_replan_count"] = int(bool(dynamic_tasks))
    aggregate_metrics["leader_followup_finding_count"] = len(followup_findings)
    leader_plan = {
        "schema_version": "visiondata-gate.dynamic-leader-plan.v1",
        "planner": "leader.release-gate",
        "mode": "evidence_triggered_replan",
        "static_task_count": 5,
        "dynamic_task_count": len(dynamic_tasks),
        "replan_count": int(bool(dynamic_tasks)),
        "initial_decision": initial_result.decision.value,
        "dynamic_tasks": dynamic_tasks,
        "branch_types": sorted(
            task["task_id"].removeprefix("followup.") for task in dynamic_tasks
        ),
        "claim_boundary": (
            "Dynamic tasks are deterministic, read-only AI Workers dispatched from "
            "intermediate evidence. They do not grant production authority."
        ),
    }
    leader_plan_sha256 = hashlib.sha256(canonical_json_bytes(leader_plan)).hexdigest()
    final_input_sha256 = hashlib.sha256(
        canonical_json_bytes(
            {
                "initial_input_sha256": input_sha256,
                "leader_plan_sha256": leader_plan_sha256,
                "followup_finding_ids": [item.finding_id for item in followup_findings],
            }
        )
    ).hexdigest()
    council = build_council(findings, traces, aggregate_metrics)
    gate_result = apply_policy(
        manifest,
        policy_contract,
        findings,
        traces,
        aggregate_metrics,
        council,
        scenario_profile=ScenarioProfile.INDUSTRIAL,
        input_sha256=final_input_sha256,
        run_id=f"omni-gate-dynamic-{final_input_sha256[:16]}",
    )
    output_root = Path(output).expanduser().resolve()
    output_root.mkdir(parents=True, exist_ok=True)
    artifacts = write_evidence_artifacts(
        output_root,
        gate_result,
        scenario_profile=ScenarioProfile.INDUSTRIAL,
    )
    gate_result_path = output_root / "gate_result.json"
    gate_result_sha256 = artifacts["gate_result.json"]
    leader_plan_path = output_root / "dynamic_leader_plan.json"
    leader_plan_sha256 = write_canonical_json(leader_plan_path, leader_plan)
    receipt = {
        "schema_version": "visiondata-gate.omni-gate-receipt.v1",
        "redacted": True,
        "completion_state": "REAL_DATA_GATE_COMPLETED",
        "decision": gate_result.decision.value,
        "run_id": gate_result.run_id,
        "source_archive_sha256": source_archive_sha256,
        "selection_manifest_sha256": selection_manifest_sha256,
        "gate_result_sha256": gate_result_sha256,
        "selected_image_count": len(manifest.samples),
        "source_image_count": structure["image_count"],
        "source_mask_count": structure["mask_count"],
        "finding_count": len(findings),
        "work_order_count": len(gate_result.work_orders),
        "failed_rule_check_count": sum(
            check.status.value == "FAIL" for check in gate_result.rule_checks
        ),
        "metadata_count_delta_total": structure["metadata_count_deltas"].get(
            "total", 0
        ),
        "leader_dynamic_task_count": len(dynamic_tasks),
        "leader_replan_count": int(bool(dynamic_tasks)),
        "leader_branch_types": leader_plan["branch_types"],
        "dynamic_leader_plan_sha256": leader_plan_sha256,
        "source_assets_copied_into_project": False,
        "claim_boundary": (
            "This decision is produced by the real VisionData Gate chain on a fixed, "
            "read-only sample of organizer bytes. It is not model accuracy, complete "
            "dataset certification, customer-site validation, production approval, or "
            "organizer endorsement."
        ),
    }
    receipt_path = output_root / "omni_gate_receipt.json"
    receipt_sha256 = write_canonical_json(receipt_path, receipt)

    for path in output_root.iterdir():
        if not path.is_file():
            continue
        serialized = path.read_text(encoding="utf-8", errors="ignore")
        forbidden = [str(dataset_root), ".png"]
        forbidden.extend(
            json.dumps(category, ensure_ascii=False) for category in official_counts
        )
        if any(item in serialized for item in forbidden):
            raise RuntimeError(f"redaction invariant failed for {path.name}")
    return OmniGateRun(
        output_root=output_root,
        gate_result=gate_result,
        gate_result_path=gate_result_path,
        gate_result_sha256=gate_result_sha256,
        receipt_path=receipt_path,
        receipt_sha256=receipt_sha256,
        leader_plan_path=leader_plan_path,
        leader_plan_sha256=leader_plan_sha256,
    )


__all__ = [
    "OmniGateRun",
    "OmniSmokeRun",
    "run_omni_readonly_gate",
    "run_omni_readonly_smoke",
]
