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
import io
import json
import os
from pathlib import Path
import re
import stat
import time
from typing import Any, Callable, Iterable, Literal
import xml.etree.ElementTree as ET
import zipfile

from PIL import Image, UnidentifiedImageError

from .agent_core import AgentRuntimeSignal, AgentRuntimeSignalSink
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
    sha256_file,
    write_canonical_json,
    write_evidence_artifacts,
)
from .industrial_skills import (
    IndustrialEvidenceSpan,
    IndustrialMeasurement,
    IndustrialSkillInvocation,
    IndustrialSourceSnapshot,
    build_default_industrial_skill_registry,
    verify_industrial_skill_receipt,
)
from .policy import apply_policy
from .quality import _new_finding, inspect_image_quality
from .rulepack import (
    RulePackRuntimeBinding,
    build_rule_pack_runtime_binding,
    verify_rule_pack_runtime_binding,
)
from .runtime_models import RuntimeStage, RuntimeStatus, ScenarioProfile
from .tools import inspect_contract_governance, tool_contract_digest


_SHA256_RE = re.compile(r"[0-9a-f]{64}")
_REQUIRED_METADATA_HEADERS = (
    "数据集名称",
    "样本总数",
    "good(train)",
    "good(test)",
    "NG(test)",
)
_XLSX_MAX_FILE_BYTES = 16 * 1024 * 1024
_XLSX_MAX_ZIP_MEMBERS = 256
_XLSX_MAX_DECLARED_UNCOMPRESSED_BYTES = 64 * 1024 * 1024
_XLSX_MAX_TARGET_MEMBER_BYTES = 8 * 1024 * 1024
_XLSX_MAX_TARGET_TOTAL_BYTES = 12 * 1024 * 1024
_XLSX_MAX_COMPRESSION_RATIO = 100
_XLSX_MAX_ROWS = 4_096
_XLSX_MAX_COLUMN_INDEX = 255
_XLSX_MAX_CELLS = 65_536
_XLSX_MAX_SHARED_STRINGS = 65_536
_XLSX_MAX_SHARED_TEXT_BYTES = 4 * 1024 * 1024
_XLSX_MAX_TEXT_BYTES = 64 * 1024
_XLSX_MAX_XML_NODES = 262_144
_XLSX_SHEET = "xl/worksheets/sheet1.xml"
_XLSX_SHARED_STRINGS = "xl/sharedStrings.xml"


class OmniSourceBoundaryError(ValueError):
    """Reject a source path without serializing the private path into errors."""


def _is_reparse_path(path: Path) -> bool:
    try:
        metadata = path.lstat()
    except OSError as error:
        raise OmniSourceBoundaryError(
            "authorized source path is unavailable"
        ) from error
    attributes = int(getattr(metadata, "st_file_attributes", 0))
    reparse_flag = int(getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0x400))
    is_junction = getattr(os.path, "isjunction", lambda _value: False)
    try:
        junction = bool(is_junction(path))
    except OSError as error:
        raise OmniSourceBoundaryError(
            "authorized source path is unavailable"
        ) from error
    return bool(path.is_symlink() or junction or attributes & reparse_flag)


def _validate_source_path(
    path: Path,
    *,
    source_root: Path,
    expected: Literal["file", "directory"] | None = None,
) -> Path:
    root = source_root.resolve(strict=True)
    lexical = Path(os.path.abspath(path))
    try:
        relative = lexical.relative_to(root)
    except ValueError as error:
        raise OmniSourceBoundaryError(
            "authorized source descendant escaped its source root"
        ) from error
    current = root
    for part in relative.parts:
        current = current / part
        if _is_reparse_path(current):
            raise OmniSourceBoundaryError(
                "authorized source descendants cannot be links or reparse points"
            )
    try:
        resolved = lexical.resolve(strict=True)
        resolved.relative_to(root)
        metadata = resolved.lstat()
    except (OSError, RuntimeError, ValueError) as error:
        raise OmniSourceBoundaryError(
            "authorized source descendant failed containment validation"
        ) from error
    if expected == "file" and not stat.S_ISREG(metadata.st_mode):
        raise OmniSourceBoundaryError("authorized source member must be a regular file")
    if expected == "directory" and not stat.S_ISDIR(metadata.st_mode):
        raise OmniSourceBoundaryError("authorized source member must be a directory")
    return resolved


def _optional_source_directory(path: Path, *, source_root: Path) -> Path | None:
    try:
        path.lstat()
    except FileNotFoundError:
        return None
    except OSError as error:
        raise OmniSourceBoundaryError(
            "authorized source path is unavailable"
        ) from error
    return _validate_source_path(path, source_root=source_root, expected="directory")


def _source_children(directory: Path, *, source_root: Path) -> list[Path]:
    safe_directory = _validate_source_path(
        directory, source_root=source_root, expected="directory"
    )
    try:
        children = [Path(entry.path) for entry in os.scandir(safe_directory)]
    except OSError as error:
        raise OmniSourceBoundaryError(
            "authorized source directory cannot be read"
        ) from error
    return [
        _validate_source_path(child, source_root=source_root)
        for child in sorted(children, key=lambda value: value.name)
    ]


def _metadata_workbook(dataset_root: Path) -> Path:
    workbooks = [
        child
        for child in _source_children(dataset_root, source_root=dataset_root)
        if child.suffix.casefold() == ".xlsx" and child.is_file()
    ]
    if len(workbooks) != 1:
        raise ValueError("expected exactly one bounded Omni metadata workbook")
    return _validate_source_path(
        workbooks[0], source_root=dataset_root, expected="file"
    )


@dataclass(frozen=True)
class OmniSmokeRun:
    summary_path: Path
    summary_sha256: str
    summary: dict[str, Any]


@dataclass(frozen=True)
class OmniGateRun:
    output_root: Path
    initial_result: GateResult
    initial_gate_result_path: Path
    initial_gate_result_sha256: str
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
    source_root: Path


@dataclass(frozen=True)
class _OmniFollowupContext:
    dataset_root: Path
    metadata_path: Path
    selected: list[_ImageRecord]
    sample_by_path: dict[str, SampleRecord]
    dimension_groups: dict[tuple[int, int] | None, list[_ImageRecord]]
    structure: dict[str, Any]
    source_archive_sha256: str
    selection_manifest_sha256: str
    runtime_rulepack: RulePackRuntimeBinding | None


@dataclass(frozen=True)
class _FollowupCandidate:
    task_id: str
    worker_id: str
    tool_name: str
    trigger: str
    trigger_rule_id: str
    worker_capability: str
    input_refs: list[str]
    linked_finding_ids: list[str]
    risk_priority: int
    expected_evidence_gain: int
    estimated_cost_units: int
    stop_condition: str
    decision_effect: str
    execute: Callable[[], tuple[dict[str, Any], list[Finding]]]


def _emit_agent_signal(
    sink: AgentRuntimeSignalSink | None,
    *,
    phase: Literal["system", "initial", "verification"],
    stage: RuntimeStage,
    actor: str,
    action: str,
    status: RuntimeStatus,
    summary: str,
    task_id: str | None = None,
    tool_name: str | None = None,
    evidence_refs: Iterable[str] = (),
    duration_ms: float = 0.0,
) -> None:
    if sink is None:
        return
    sink(
        AgentRuntimeSignal(
            phase=phase,
            stage=stage,
            actor=actor,
            action=action,
            status=status,
            summary=summary,
            task_id=task_id,
            tool_name=tool_name,
            evidence_refs=list(evidence_refs),
            duration_ms=duration_ms,
        )
    )


class _FollowupFailClosedError(RuntimeError):
    """Carry path-free evidence from a Worker that must not report success."""

    def __init__(self, reason_code: str, outputs: dict[str, Any]) -> None:
        super().__init__(reason_code)
        self.reason_code = reason_code
        self.outputs = outputs


def _hash_text(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _discover_dataset_root(root: str | Path) -> Path:
    supplied = Path(root).expanduser()
    if _is_reparse_path(supplied):
        raise OmniSourceBoundaryError(
            "authorized source root cannot be a link or reparse point"
        )
    try:
        candidate = supplied.resolve(strict=True)
    except (OSError, RuntimeError) as error:
        raise OmniSourceBoundaryError(
            "authorized source root is unavailable"
        ) from error
    _validate_source_path(candidate, source_root=candidate, expected="directory")
    candidates = [
        candidate,
        *[
            path
            for path in _source_children(candidate, source_root=candidate)
            if path.is_dir()
        ],
    ]
    matches: list[Path] = []
    for path in candidates:
        children = _source_children(path, source_root=candidate)
        workbooks = [
            child
            for child in children
            if child.is_file() and child.suffix.casefold() == ".xlsx"
        ]
        if len(workbooks) == 1 and any(child.is_dir() for child in children):
            matches.append(path)
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
        value = "".join(
            node.text or "" for node in cell.findall(f".//{{{namespace}}}t")
        )
        if len(value.encode("utf-8")) > _XLSX_MAX_TEXT_BYTES:
            raise ValueError("metadata workbook cell text budget exceeded")
        return value
    if value_node is None or value_node.text is None:
        return None
    raw = value_node.text
    if len(raw.encode("utf-8")) > _XLSX_MAX_TEXT_BYTES:
        raise ValueError("metadata workbook cell text budget exceeded")
    if cell_type == "s":
        try:
            return shared_strings[int(raw)]
        except (IndexError, ValueError) as error:
            raise ValueError(
                "metadata workbook shared string index is invalid"
            ) from error
    if cell_type in {"str", "b"}:
        return raw
    try:
        numeric = float(raw)
    except ValueError:
        return raw
    return int(numeric) if numeric.is_integer() else numeric


def _column_index(reference: str) -> int:
    match = re.fullmatch(r"([A-Za-z]{1,3})([1-9][0-9]{0,6})", reference)
    if match is None:
        raise ValueError("metadata workbook cell reference is invalid")
    letters = match.group(1).upper()
    result = 0
    for char in letters:
        result = result * 26 + (ord(char) - ord("A") + 1)
    index = result - 1
    if index > _XLSX_MAX_COLUMN_INDEX:
        raise ValueError("metadata workbook column budget exceeded")
    return index


def _read_xlsx_member(
    bundle: zipfile.ZipFile,
    info: zipfile.ZipInfo,
    *,
    remaining_total: int,
) -> bytes:
    limit = min(_XLSX_MAX_TARGET_MEMBER_BYTES, remaining_total)
    chunks: list[bytes] = []
    total = 0
    with bundle.open(info, "r") as handle:
        while True:
            chunk = handle.read(min(64 * 1024, limit - total + 1))
            if not chunk:
                break
            total += len(chunk)
            if total > limit:
                raise ValueError("metadata workbook expanded XML budget exceeded")
            chunks.append(chunk)
    payload = b"".join(chunks)
    try:
        decoded = payload.decode("utf-8-sig")
    except UnicodeDecodeError as error:
        raise ValueError("metadata workbook XML must use UTF-8") from error
    if re.search(r"<!\s*(?:DOCTYPE|ENTITY)\b", decoded, flags=re.IGNORECASE):
        raise ValueError("metadata workbook XML declarations are not allowed")
    return payload


def _xml_local_name(tag: str) -> str:
    return tag.rsplit("}", 1)[-1]


def _parse_shared_strings(payload: bytes) -> list[str]:
    shared_strings: list[str] = []
    text_bytes = 0
    node_count = 0
    try:
        events = ET.iterparse(io.BytesIO(payload), events=("end",))
        for _event, element in events:
            node_count += 1
            if node_count > _XLSX_MAX_XML_NODES:
                raise ValueError("metadata workbook XML node budget exceeded")
            if _xml_local_name(element.tag) != "si":
                continue
            value = "".join(
                child.text or ""
                for child in element.iter()
                if _xml_local_name(child.tag) == "t"
            )
            encoded_length = len(value.encode("utf-8"))
            if encoded_length > _XLSX_MAX_TEXT_BYTES:
                raise ValueError("metadata workbook shared string budget exceeded")
            text_bytes += encoded_length
            if text_bytes > _XLSX_MAX_SHARED_TEXT_BYTES:
                raise ValueError("metadata workbook shared text budget exceeded")
            shared_strings.append(value)
            if len(shared_strings) > _XLSX_MAX_SHARED_STRINGS:
                raise ValueError("metadata workbook shared string count exceeded")
            element.clear()
    except ET.ParseError as error:
        raise ValueError("metadata workbook shared strings XML is invalid") from error
    return shared_strings


def _parse_count_sheet(
    payload: bytes,
    *,
    shared_strings: list[str],
) -> dict[str, dict[str, int]]:
    result: dict[str, dict[str, int]] = {}
    indexes: dict[str, int] | None = None
    row_count = 0
    cell_count = 0
    node_count = 0
    try:
        events = ET.iterparse(io.BytesIO(payload), events=("end",))
        for _event, element in events:
            node_count += 1
            if node_count > _XLSX_MAX_XML_NODES:
                raise ValueError("metadata workbook XML node budget exceeded")
            if _xml_local_name(element.tag) != "row":
                continue
            row_count += 1
            if row_count > _XLSX_MAX_ROWS:
                raise ValueError("metadata workbook row budget exceeded")
            values: dict[int, Any] = {}
            namespace = element.tag.partition("}")[0].removeprefix("{")
            for cell in element:
                if _xml_local_name(cell.tag) != "c":
                    continue
                cell_count += 1
                if cell_count > _XLSX_MAX_CELLS:
                    raise ValueError("metadata workbook cell budget exceeded")
                reference = cell.attrib.get("r")
                if reference is None:
                    raise ValueError("metadata workbook cell reference is missing")
                values[_column_index(reference)] = _xlsx_cell_value(
                    cell,
                    namespace=namespace,
                    shared_strings=shared_strings,
                )
            if indexes is None:
                header_by_index = {
                    index: str(value).strip() if value is not None else ""
                    for index, value in values.items()
                }
                missing = [
                    header
                    for header in _REQUIRED_METADATA_HEADERS
                    if header not in header_by_index.values()
                ]
                if missing:
                    raise ValueError(
                        "metadata workbook is missing required count columns"
                    )
                indexes = {
                    header: next(
                        index
                        for index, value in header_by_index.items()
                        if value == header
                    )
                    for header in _REQUIRED_METADATA_HEADERS
                }
                element.clear()
                continue
            category_value = values.get(indexes["数据集名称"])
            if category_value is None:
                element.clear()
                continue
            category = str(category_value).strip()
            if not category or category in result:
                raise ValueError(
                    "metadata workbook has blank or duplicate category names"
                )
            counts: dict[str, int] = {}
            for output_key, header in (
                ("total", "样本总数"),
                ("train_good", "good(train)"),
                ("test_good", "good(test)"),
                ("test_anomaly", "NG(test)"),
            ):
                value = values.get(indexes[header])
                if not isinstance(value, (int, float)):
                    raise ValueError("metadata workbook contains a non-numeric count")
                counts[output_key] = int(value)
            result[category] = counts
            element.clear()
    except ET.ParseError as error:
        raise ValueError("metadata workbook worksheet XML is invalid") from error
    if indexes is None:
        raise ValueError("metadata workbook is empty")
    if not result:
        raise ValueError("metadata workbook contains no category rows")
    return result


def _load_official_counts(metadata_path: Path) -> dict[str, dict[str, int]]:
    safe_path = _validate_source_path(
        metadata_path,
        source_root=metadata_path.parent,
        expected="file",
    )
    if safe_path.stat().st_size > _XLSX_MAX_FILE_BYTES:
        raise ValueError("metadata workbook file budget exceeded")
    try:
        with zipfile.ZipFile(safe_path) as bundle:
            members = bundle.infolist()
            if len(members) > _XLSX_MAX_ZIP_MEMBERS:
                raise ValueError("metadata workbook member budget exceeded")
            names = [member.filename for member in members]
            if len(names) != len(set(names)):
                raise ValueError("metadata workbook contains duplicate members")
            if any(member.flag_bits & 0x1 for member in members):
                raise ValueError("encrypted metadata workbook members are unsupported")
            if sum(member.file_size for member in members) > (
                _XLSX_MAX_DECLARED_UNCOMPRESSED_BYTES
            ):
                raise ValueError("metadata workbook expanded size budget exceeded")
            for member in members:
                if (
                    member.file_size
                    and member.file_size / max(member.compress_size, 1)
                    > _XLSX_MAX_COMPRESSION_RATIO
                ):
                    raise ValueError(
                        "metadata workbook compression ratio budget exceeded"
                    )
            by_name = {member.filename: member for member in members}
            sheet_info = by_name.get(_XLSX_SHEET)
            if sheet_info is None:
                raise ValueError("metadata workbook has no first worksheet")
            targets = [sheet_info]
            shared_info = by_name.get(_XLSX_SHARED_STRINGS)
            if shared_info is not None:
                targets.append(shared_info)
            if any(
                member.file_size > _XLSX_MAX_TARGET_MEMBER_BYTES for member in targets
            ):
                raise ValueError("metadata workbook target member budget exceeded")
            actual_total = 0
            shared_strings: list[str] = []
            if shared_info is not None:
                shared_payload = _read_xlsx_member(
                    bundle,
                    shared_info,
                    remaining_total=_XLSX_MAX_TARGET_TOTAL_BYTES - actual_total,
                )
                actual_total += len(shared_payload)
                shared_strings = _parse_shared_strings(shared_payload)
            sheet_payload = _read_xlsx_member(
                bundle,
                sheet_info,
                remaining_total=_XLSX_MAX_TARGET_TOTAL_BYTES - actual_total,
            )
            return _parse_count_sheet(
                sheet_payload,
                shared_strings=shared_strings,
            )
    except zipfile.BadZipFile as error:
        raise ValueError("metadata workbook ZIP structure is invalid") from error


def _png_files(directory: Path, *, source_root: Path) -> list[Path]:
    safe_directory = _optional_source_directory(directory, source_root=source_root)
    if safe_directory is None:
        return []
    return [
        _validate_source_path(path, source_root=source_root, expected="file")
        for path in _source_children(safe_directory, source_root=source_root)
        if path.is_file() and path.suffix.casefold() == ".png"
    ]


def _scan_dataset(
    dataset_root: Path,
    official_counts: dict[str, dict[str, int]],
) -> tuple[list[_ImageRecord], dict[str, Any]]:
    dataset_root = _validate_source_path(
        dataset_root,
        source_root=dataset_root,
        expected="directory",
    )
    actual_categories = {
        path.name
        for path in _source_children(dataset_root, source_root=dataset_root)
        if path.is_dir()
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
        _validate_source_path(
            category_root, source_root=dataset_root, expected="directory"
        )
        for path in _png_files(
            category_root / "train" / "good", source_root=dataset_root
        ):
            relative = path.relative_to(dataset_root).as_posix()
            records.append(
                _ImageRecord(
                    category,
                    "train",
                    "good",
                    path,
                    relative,
                    None,
                    dataset_root,
                )
            )
            counts["train_good"] += 1
        test_root = category_root / "test"
        safe_test_root = _optional_source_directory(test_root, source_root=dataset_root)
        if safe_test_root is not None:
            for state_root in sorted(
                path
                for path in _source_children(safe_test_root, source_root=dataset_root)
                if path.is_dir()
            ):
                state = state_root.name
                for path in _png_files(state_root, source_root=dataset_root):
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
                            dataset_root,
                        )
                    )
                    counts["test_good" if is_good else "test_anomaly"] += 1
        ground_truth_root = category_root / "ground_truth"
        safe_ground_truth_root = _optional_source_directory(
            ground_truth_root, source_root=dataset_root
        )
        if safe_ground_truth_root is not None:
            for state_root in sorted(
                path
                for path in _source_children(
                    safe_ground_truth_root, source_root=dataset_root
                )
                if path.is_dir()
            ):
                for path in _png_files(state_root, source_root=dataset_root):
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


def profile_omni_source(
    root: str | Path,
    *,
    source_archive_sha256: str,
) -> dict[str, Any]:
    """Return a path- and category-redacted profile for source authorization.

    The profile performs only read operations.  It deliberately records the
    supplied archive digest as an operator-provided identity rather than
    re-hashing a multi-gigabyte archive during every authorization request.
    """

    if not _SHA256_RE.fullmatch(source_archive_sha256):
        raise ValueError("source_archive_sha256 must be a lowercase SHA-256 digest")
    dataset_root = _discover_dataset_root(root)
    metadata_path = _metadata_workbook(dataset_root)
    official_counts = _load_official_counts(metadata_path)
    records, structure = _scan_dataset(dataset_root, official_counts)
    tree_identity: list[dict[str, Any]] = []
    for record in records:
        image_path = _validate_source_path(
            record.path, source_root=dataset_root, expected="file"
        )
        annotation_size: int | None = None
        if record.annotation_path is not None:
            annotation_candidate = dataset_root / record.annotation_path
            try:
                annotation_path = _validate_source_path(
                    annotation_candidate,
                    source_root=dataset_root,
                    expected="file",
                )
            except OmniSourceBoundaryError:
                if annotation_candidate.exists():
                    raise
            else:
                annotation_size = annotation_path.stat().st_size
        tree_identity.append(
            {
                "relative_path": record.relative_path,
                "image_size_bytes": image_path.stat().st_size,
                "annotation_relative_path": record.annotation_path,
                "annotation_size_bytes": annotation_size,
            }
        )
    profile: dict[str, Any] = {
        "schema_version": "visiondata-gate.omni-source-profile.v1",
        "adapter_kind": "omni_ad_30_release",
        "redacted": True,
        "source_archive_sha256": source_archive_sha256,
        "category_count": int(structure["category_count"]),
        "metadata_category_count": int(structure["metadata_category_count"]),
        "source_image_count": int(structure["image_count"]),
        "source_mask_count": int(structure["mask_count"]),
        "metadata_image_count": int(structure["metadata_image_count"]),
        "metadata_count_delta_total": int(
            structure["metadata_count_deltas"].get("total", 0)
        ),
        "metadata_mismatch_category_count": int(
            structure["metadata_mismatch_category_count"]
        ),
        "source_tree_manifest_sha256": hashlib.sha256(
            canonical_json_bytes(tree_identity)
        ).hexdigest(),
        "metadata_file_sha256": sha256_file(metadata_path),
        "missing_mask_count": int(structure["missing_mask_count"]),
        "extra_mask_count": int(structure["extra_mask_count"]),
        "training_normal_only": bool(structure["training_normal_only"]),
        "source_assets_copied_into_product": False,
    }
    profile["profile_sha256"] = hashlib.sha256(
        canonical_json_bytes(profile)
    ).hexdigest()
    return profile


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


def _image_size(
    path: Path,
    *,
    source_root: Path | None = None,
) -> tuple[int, int] | None:
    try:
        safe_path = (
            _validate_source_path(path, source_root=source_root, expected="file")
            if source_root is not None
            else path
        )
        with Image.open(safe_path) as image:
            image.load()
            return image.size
    except (OmniSourceBoundaryError, UnidentifiedImageError, SyntaxError, OSError):
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


def _gate_measurement_contract(
    *,
    width: int,
    height: int,
    runtime_rulepack: RulePackRuntimeBinding | None = None,
) -> BatchContract:
    """Return the frozen pixel policy used for one native-size group."""

    thresholds = runtime_rulepack.thresholds if runtime_rulepack is not None else {}
    return BatchContract(
        contract_id="omni-readonly-native-size-measurement-v1",
        required_splits=["train", "test"],
        annotations_required=False,
        thresholds=QualityThresholds(
            expected_width=max(width, 16),
            expected_height=max(height, 16),
            min_mean_luma=float(thresholds.get("min_mean_luma", 35.0)),
            max_mean_luma=float(thresholds.get("max_mean_luma", 225.0)),
            min_sharpness=float(thresholds.get("min_sharpness", 18.0)),
            min_mask_fraction=float(thresholds.get("min_mask_fraction", 0.002)),
            max_mask_fraction=float(thresholds.get("max_mask_fraction", 0.65)),
            near_duplicate_hamming=int(thresholds.get("near_duplicate_hamming", 4)),
        ),
        coverage=CoverageContract(
            categories=["bounded-group"],
            views=["catalog"],
            conditions=["observed"],
            min_per_cell=int(thresholds.get("min_coverage_per_cell", 1)),
            splits=["train", "test"],
        ),
        policy_version="omni-readonly-native-size-measurement-v1",
    )


def _gate_policy_contract(
    category_aliases: list[str],
    runtime_rulepack: RulePackRuntimeBinding | None = None,
) -> BatchContract:
    """Return the cross-group industrial policy contract.

    Pixel dimensions are enforced by the native-size measurement contracts.
    The policy contract governs split, annotation, coverage, evidence, and
    scenario-level checks after those measurements are aggregated.
    """

    thresholds = runtime_rulepack.thresholds if runtime_rulepack is not None else {}
    return BatchContract(
        contract_id="omni-readonly-variable-resolution-gate-v1",
        required_splits=["train", "test"],
        annotations_required=False,
        thresholds=QualityThresholds(
            expected_width=16,
            expected_height=16,
            min_mean_luma=float(thresholds.get("min_mean_luma", 35.0)),
            max_mean_luma=float(thresholds.get("max_mean_luma", 225.0)),
            min_sharpness=float(thresholds.get("min_sharpness", 18.0)),
            min_mask_fraction=float(thresholds.get("min_mask_fraction", 0.002)),
            max_mask_fraction=float(thresholds.get("max_mask_fraction", 0.65)),
            near_duplicate_hamming=int(thresholds.get("near_duplicate_hamming", 4)),
        ),
        coverage=CoverageContract(
            categories=category_aliases,
            views=["catalog"],
            conditions=["observed"],
            min_per_cell=int(thresholds.get("min_coverage_per_cell", 1)),
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


def _followup_trace(
    *,
    sequence: int,
    candidate: _FollowupCandidate,
    status: str,
    outputs: dict[str, Any],
    finding_ids: list[str],
    duration_ms: float,
    error: str | None,
) -> ToolTrace:
    input_payload = {
        "task_id": candidate.task_id,
        "trigger": candidate.trigger,
        "trigger_rule_id": candidate.trigger_rule_id,
        "worker_capability": candidate.worker_capability,
        "input_refs": sorted(candidate.input_refs),
        "dispatch_protocol": "contract-net-evidence-bid-v1",
    }
    result_payload = {
        "outputs": outputs,
        "finding_ids": sorted(finding_ids),
        "error": error,
    }
    return ToolTrace(
        sequence=sequence,
        tool=candidate.tool_name,
        status=status,  # type: ignore[arg-type]
        input_sha256=hashlib.sha256(canonical_json_bytes(input_payload)).hexdigest(),
        parameters={
            "followup_task_id": candidate.task_id,
            "trigger_rule_id": candidate.trigger_rule_id,
            "worker_capability": candidate.worker_capability,
            "dispatch_protocol": "contract-net-evidence-bid-v1",
            "risk_priority": candidate.risk_priority,
            "expected_evidence_gain": candidate.expected_evidence_gain,
            "budget_cost_units": candidate.estimated_cost_units,
            "duration_ms": round(duration_ms, 3),
            "stop_condition": candidate.stop_condition,
            "parent_evidence_refs": sorted(candidate.input_refs),
            "decision_effect": candidate.decision_effect,
        },
        result_sha256=hashlib.sha256(canonical_json_bytes(result_payload)).hexdigest(),
        finding_ids=sorted(finding_ids),
        error=error,
        contract_version="1.0.0",
        contract_digest=tool_contract_digest(
            candidate.tool_name, include_optional=True
        ),
        adapter="external-readonly-omni-v1",
    )


def _dynamic_task_receipt(
    *,
    candidate: _FollowupCandidate,
    trace: ToolTrace,
    outputs: dict[str, Any],
    status: str,
    duration_ms: float,
    initial_decision: str,
    award_rank: int,
) -> dict[str, Any]:
    skill_receipt_ref = outputs.get("skill_receipt_sha256")
    skill_receipt_refs = (
        [f"industrial-skill-receipt:{skill_receipt_ref}"]
        if isinstance(skill_receipt_ref, str)
        and _SHA256_RE.fullmatch(skill_receipt_ref)
        else []
    )
    return {
        "task_id": candidate.task_id,
        "worker_id": candidate.worker_id,
        "trigger": candidate.trigger,
        "trigger_rule_id": candidate.trigger_rule_id,
        "worker_capability": candidate.worker_capability,
        "dispatch_basis": "intermediate_evidence",
        "dispatch_protocol": "contract-net-evidence-bid-v1",
        "award_rank": award_rank,
        "status": status,
        "input_refs": sorted(candidate.input_refs),
        "outputs": outputs,
        "result_sha256": trace.result_sha256,
        "tool_trace_ref": f"trace:{trace.sequence}:{trace.tool}",
        "tool_trace_result_sha256": trace.result_sha256,
        "new_evidence_refs": [
            f"finding:{finding_id}" for finding_id in trace.finding_ids
        ]
        + [f"trace:{trace.sequence}:{trace.result_sha256}"]
        + skill_receipt_refs,
        "duration_ms": round(duration_ms, 3),
        "budget": {
            "estimated_cost_units": candidate.estimated_cost_units,
            "consumed_cost_units": (
                candidate.estimated_cost_units if status == "completed" else 0
            ),
        },
        "stop_condition": candidate.stop_condition,
        "decision_before_followup": initial_decision,
        "decision_effect": candidate.decision_effect,
    }


def _semantic_plan_payload(value: Any) -> Any:
    """Remove operational timing without weakening semantic replay identity.

    Wall-clock duration is useful operational evidence, but it changes between
    otherwise identical read-only runs.  The semantic dispatch hash therefore
    excludes only ``duration_ms`` while preserving awards, status, inputs,
    outputs, budgets, findings, and stop conditions.  The full operational
    payload is hashed separately at the call site.
    """

    if isinstance(value, dict):
        return {
            key: _semantic_plan_payload(item)
            for key, item in value.items()
            if key != "duration_ms"
        }
    if isinstance(value, list):
        return [_semantic_plan_payload(item) for item in value]
    return value


def _dynamic_leader_followups(
    initial_result: GateResult,
    *,
    context: _OmniFollowupContext,
    followup_tool_budget: int,
) -> tuple[
    list[dict[str, Any]],
    list[Finding],
    list[ToolTrace],
    dict[str, int | str],
]:
    """Execute evidence-triggered follow-ups under a bounded Contract-Net award.

    The Leader first observes intermediate evidence, ranks bids by risk and
    expected evidence gain, then awards only the frozen budget.  Awarded Workers
    perform fresh read-only computation and append independent ``ToolTrace``
    records.  Rejected or failed high-risk work creates non-success traces, so
    the Frozen Judge reaches ``DEFER`` instead of silently releasing.
    """

    candidates: list[_FollowupCandidate] = []
    additional_findings: list[Finding] = []

    def trigger_enabled(trigger_id: str) -> bool:
        return (
            context.runtime_rulepack is None
            or trigger_id in context.runtime_rulepack.dynamic_trigger_capabilities
        )

    def trigger_capability(trigger_id: str, default: str) -> str:
        if context.runtime_rulepack is None:
            return default
        return context.runtime_rulepack.dynamic_trigger_capabilities[trigger_id]

    def trigger_cost(trigger_id: str) -> int:
        if context.runtime_rulepack is None:
            return 1
        return context.runtime_rulepack.dynamic_trigger_max_cost_units[trigger_id]

    metadata_findings = [
        item for item in initial_result.findings if item.code == "METADATA_COUNT_DRIFT"
    ]
    if metadata_findings and trigger_enabled("metadata-count-drift"):

        def execute_metadata_reconciliation() -> tuple[dict[str, Any], list[Finding]]:
            official_counts = _load_official_counts(context.metadata_path)
            _records, observed = _scan_dataset(context.dataset_root, official_counts)
            stable = all(
                observed[key] == context.structure[key]
                for key in (
                    "image_count",
                    "mask_count",
                    "metadata_image_count",
                    "metadata_mismatch_category_count",
                    "metadata_count_deltas",
                )
            )
            tree_image_count = int(observed["image_count"])
            metadata_image_count = int(observed["metadata_image_count"])
            observed_delta_images = abs(tree_image_count - metadata_image_count)
            source = IndustrialSourceSnapshot(
                source_id="omni-gate-source",
                source_kind="authorized_metadata_snapshot",
                source_version="omni-authorized-source-snapshot-v1",
                snapshot_sha256=context.source_archive_sha256,
            )
            invocation_id_sha256 = hashlib.sha256(
                canonical_json_bytes(
                    {
                        "source_archive_sha256": context.source_archive_sha256,
                        "selection_manifest_sha256": (
                            context.selection_manifest_sha256
                        ),
                        "tree_image_count": tree_image_count,
                        "metadata_image_count": metadata_image_count,
                    }
                )
            ).hexdigest()

            def measurement(
                name: str,
                value: int,
                *,
                span_kind: Literal["metric", "metadata"],
            ) -> IndustrialMeasurement:
                return IndustrialMeasurement(
                    name=name,
                    value=float(value),
                    unit="images",
                    measurement_version="1.0.0",
                    evidence_span=IndustrialEvidenceSpan(
                        source_id=source.source_id,
                        source_version=source.source_version,
                        snapshot_sha256=source.snapshot_sha256,
                        span_kind=span_kind,
                        selector=f"/metrics/{name}",
                    ),
                )

            invocation = IndustrialSkillInvocation(
                invocation_id=f"metadata-reconciliation-{invocation_id_sha256[:24]}",
                source=source,
                measurements=(
                    measurement(
                        "metadata_image_count",
                        metadata_image_count,
                        span_kind="metadata",
                    ),
                    measurement(
                        "tree_image_count",
                        tree_image_count,
                        span_kind="metric",
                    ),
                ),
            )
            skill_id = "visiondata-gate.metadata-count-drift"
            skill_version = "1.0.0"
            receipt = build_default_industrial_skill_registry().invoke(
                skill_id,
                skill_version,
                invocation,
            )
            receipt_binding_verified = (
                receipt.invocation == invocation
                and receipt.manifest.skill_id == skill_id
                and receipt.manifest.skill_version == skill_version
                and receipt.outcome.skill_id == skill_id
                and receipt.outcome.skill_version == skill_version
            )
            receipt_verified = (
                verify_industrial_skill_receipt(receipt) and receipt_binding_verified
            )
            observation = (
                receipt.outcome.observations[0]
                if len(receipt.outcome.observations) == 1
                else None
            )
            observation_verified = bool(
                observation is not None
                and observation.measurement_name == "metadata_count_absolute_delta"
                and observation.unit == "images"
                and observation.decision.observed_value == float(observed_delta_images)
            )
            outputs: dict[str, Any] = {
                "independent_rescan_matches_initial": stable,
                "metadata_mismatch_category_count": observed[
                    "metadata_mismatch_category_count"
                ],
                "aggregate_count_deltas": observed["metadata_count_deltas"],
                "tree_image_count": tree_image_count,
                "metadata_image_count": metadata_image_count,
                "observed_delta_images": observed_delta_images,
                "skill_id": receipt.manifest.skill_id,
                "skill_version": receipt.manifest.skill_version,
                "skill_algorithm_version": receipt.manifest.algorithm_version,
                "skill_outcome_status": receipt.outcome.status,
                "skill_observation_reason_code": (
                    observation.reason_code if observation is not None else None
                ),
                "skill_reported_delta_images": (
                    observation.decision.observed_value
                    if observation is not None
                    else None
                ),
                "skill_receipt_sha256": receipt.receipt_sha256,
                "skill_receipt_verified": receipt_verified,
                "skill_receipt_verification_status": (
                    "VERIFIED" if receipt_verified else "FAILED"
                ),
                "skill_observation_verified": observation_verified,
                "skill_manifest_sha256": receipt.manifest_sha256,
                "skill_invocation_sha256": receipt.invocation_sha256,
                "skill_outcome_sha256": receipt.outcome_sha256,
                "skill_receipt": receipt.model_dump(mode="json"),
                "resolution": (
                    "investigation_required" if stable else "defer_evidence_changed"
                ),
            }
            failure_reason: str | None = None
            if not receipt_verified:
                failure_reason = "SKILL_RECEIPT_VERIFICATION_FAILED"
            elif receipt.outcome.status == "DEFER":
                failure_reason = "SKILL_OUTCOME_DEFER"
            elif not observation_verified:
                failure_reason = "SKILL_OBSERVATION_BINDING_FAILED"
            if failure_reason is not None:
                outputs["skill_integration_status"] = "FAIL_CLOSED"
                outputs["skill_failure_reason"] = failure_reason
                outputs["resolution"] = "defer_skill_failure"
                raise _FollowupFailClosedError(failure_reason, outputs)
            outputs["skill_integration_status"] = "ACCEPTED"
            outputs["skill_failure_reason"] = None
            return outputs, []

        candidates.append(
            _FollowupCandidate(
                task_id="followup.metadata-reconciliation",
                worker_id="worker.metadata-reconciliation",
                tool_name="governance_audit",
                trigger="observed METADATA_COUNT_DRIFT after the first evidence wave",
                trigger_rule_id="metadata-count-drift",
                worker_capability=trigger_capability(
                    "metadata-count-drift",
                    "industrial-metadata-reconciliation",
                ),
                input_refs=[f"finding:{item.finding_id}" for item in metadata_findings]
                + [f"sha256:{context.source_archive_sha256}"],
                linked_finding_ids=[item.finding_id for item in metadata_findings],
                risk_priority=3,
                expected_evidence_gain=3,
                estimated_cost_units=trigger_cost("metadata-count-drift"),
                stop_condition=(
                    "stop after one independent metadata/tree rescan; never auto-repair"
                ),
                decision_effect=(
                    "preserve INVESTIGATE work order; automated repair is forbidden"
                ),
                execute=execute_metadata_reconciliation,
            )
        )

    native_group_count = len(context.dimension_groups)
    if native_group_count > 1 and trigger_enabled("native-resolution-groups"):
        initial_quality_findings = [
            item for item in initial_result.findings if item.tool == "image_quality"
        ]

        def execute_resolution_reconciliation() -> tuple[dict[str, Any], list[Finding]]:
            observed: list[Finding] = []
            decoded_count = 0
            errors: list[str] = []
            for size, group in sorted(
                context.dimension_groups.items(), key=lambda item: item[0] or (0, 0)
            ):
                width, height = size or (16, 16)
                subset = BatchManifest(
                    batch_id="omni-followup-native-resolution",
                    seed=0,
                    samples=[
                        context.sample_by_path[item.relative_path] for item in group
                    ],
                )
                try:
                    findings, metrics = inspect_image_quality(
                        context.dataset_root,
                        subset,
                        _gate_measurement_contract(
                            width=width,
                            height=height,
                            runtime_rulepack=context.runtime_rulepack,
                        ),
                    )
                    observed.extend(
                        _redacted_finding(item, salt=context.source_archive_sha256)
                        for item in findings
                    )
                    decoded_count += int(metrics.get("decoded_image_count", 0))
                except Exception as exc:  # bounded, path-redacted failure class only
                    errors.append(type(exc).__name__)
            if errors:
                raise RuntimeError("native resolution follow-up tool failed")
            observed_ids = sorted(item.finding_id for item in observed)
            initial_ids = sorted(item.finding_id for item in initial_quality_findings)
            consistent = observed_ids == initial_ids
            findings: list[Finding] = []
            if not consistent:
                findings.append(
                    _new_finding(
                        tool="governance_audit",
                        code="NATIVE_RESOLUTION_EVIDENCE_INCOMPLETE",
                        severity=Severity.HIGH,
                        sample_ids=[],
                        summary=(
                            "Independent native-resolution evidence did not reproduce "
                            "the first-wave quality finding set."
                        ),
                        evidence={
                            "native_resolution_group_count": native_group_count,
                            "initial_finding_count": len(initial_ids),
                            "followup_finding_count": len(observed_ids),
                        },
                        recommended_action=(
                            "defer and investigate resolution-group evidence drift"
                        ),
                    )
                )
            return (
                {
                    "native_resolution_group_count": native_group_count,
                    "rechecked_image_count": decoded_count,
                    "quality_finding_set_reproduced": consistent,
                    "group_policy": "measure_per_native_size_then_reconcile",
                    "resolution": (
                        "supplemental_evidence_accepted" if consistent else "defer"
                    ),
                },
                findings,
            )

        quality_traces = [
            trace
            for trace in initial_result.tool_trace
            if trace.tool == "image_quality"
        ]
        candidates.append(
            _FollowupCandidate(
                task_id="followup.native-resolution-reconciliation",
                worker_id="worker.native-resolution-reconciler",
                tool_name="image_quality",
                trigger="more than one native resolution group was discovered at intake",
                trigger_rule_id="native-resolution-groups",
                worker_capability=trigger_capability(
                    "native-resolution-groups",
                    "native-resolution-quality-reconciliation",
                ),
                input_refs=[
                    f"trace:{trace.sequence}:{trace.tool}" for trace in quality_traces
                ],
                linked_finding_ids=[
                    item.finding_id for item in initial_quality_findings
                ],
                risk_priority=2,
                expected_evidence_gain=2,
                estimated_cost_units=trigger_cost("native-resolution-groups"),
                stop_condition=(
                    "stop after one independent pass over every selected native-size group"
                ),
                decision_effect=(
                    "accept group-aware quality evidence only if the finding set reproduces"
                ),
                execute=execute_resolution_reconciliation,
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

        def execute_conflict_adjudication() -> tuple[dict[str, Any], list[Finding]]:
            linked_findings = {item.finding_id for item in initial_result.findings}
            linkage_complete = all(
                str(order.replacement_requirements.get("source_finding_id", ""))
                in linked_findings
                for order in relevant_orders
            )
            action_precedence = [
                action
                for action in (
                    "INVESTIGATE",
                    "REMOVE_OR_REPARTITION",
                    "RELABEL",
                    "RECAPTURE",
                )
                if any(action in actions for actions in conflicts.values())
            ]
            return (
                {
                    "conflict_sample_count": len(conflict_samples),
                    "work_order_count": len(relevant_orders),
                    "source_finding_linkage_complete": linkage_complete,
                    "safe_action_precedence": action_precedence,
                    "finding_id": finding.finding_id,
                    "resolution": "investigation_required",
                },
                [],
            )

        if trigger_enabled("cross-tool-action-conflict"):
            candidates.append(
                _FollowupCandidate(
                    task_id="followup.cross-tool-conflict-adjudication",
                    worker_id="worker.remediation-conflict-adjudicator",
                    tool_name="governance_audit",
                    trigger=(
                        "the first Judge pass attached multiple actions to one sample"
                    ),
                    trigger_rule_id="cross-tool-action-conflict",
                    worker_capability=trigger_capability(
                        "cross-tool-action-conflict",
                        "industrial-remediation-conflict-adjudication",
                    ),
                    input_refs=[
                        f"work-order:{order.work_order_id}" for order in relevant_orders
                    ],
                    linked_finding_ids=[finding.finding_id],
                    risk_priority=3,
                    expected_evidence_gain=2,
                    estimated_cost_units=trigger_cost("cross-tool-action-conflict"),
                    stop_condition=(
                        "stop after work-order linkage and safe action precedence "
                        "are resolved"
                    ),
                    decision_effect=(
                        "route conflicting actions to investigation before any "
                        "remediation"
                    ),
                    execute=execute_conflict_adjudication,
                )
            )

    ranked = sorted(
        candidates,
        key=lambda item: (
            -item.risk_priority,
            -item.expected_evidence_gain,
            item.estimated_cost_units,
            item.task_id,
        ),
    )
    awarded: list[_FollowupCandidate] = []
    rejected: list[_FollowupCandidate] = []
    remaining_budget = followup_tool_budget
    for candidate in ranked:
        if candidate.estimated_cost_units <= remaining_budget:
            awarded.append(candidate)
            remaining_budget -= candidate.estimated_cost_units
        else:
            rejected.append(candidate)
    executions: dict[str, tuple[dict[str, Any], list[Finding], float, str | None]] = {}

    def execute_one(
        candidate: _FollowupCandidate,
    ) -> tuple[dict[str, Any], list[Finding], float, str | None]:
        started = time.perf_counter()
        try:
            outputs, findings = candidate.execute()
            return outputs, findings, (time.perf_counter() - started) * 1000, None
        except _FollowupFailClosedError as exc:
            return (
                exc.outputs,
                [],
                (time.perf_counter() - started) * 1000,
                exc.reason_code,
            )
        except Exception as exc:  # record class only; never serialize source paths
            return (
                {"resolution": "defer_followup_error"},
                [],
                (time.perf_counter() - started) * 1000,
                type(exc).__name__,
            )

    if awarded:
        with ThreadPoolExecutor(
            max_workers=len(awarded),
            thread_name_prefix="omni-leader-followup",
        ) as pool:
            futures = {pool.submit(execute_one, item): item for item in awarded}
            for future, candidate in [(future, futures[future]) for future in futures]:
                executions[candidate.task_id] = future.result()

    tasks: list[dict[str, Any]] = []
    traces: list[ToolTrace] = []
    for award_rank, candidate in enumerate(ranked, start=1):
        sequence = len(initial_result.tool_trace) + award_rank
        if candidate in rejected:
            finding = _new_finding(
                tool="governance_audit",
                code="FOLLOWUP_BUDGET_EXHAUSTED",
                severity=Severity.HIGH,
                sample_ids=[],
                summary="A high-risk evidence follow-up was not executed within budget.",
                evidence={
                    "task_id": candidate.task_id,
                    "followup_tool_budget": followup_tool_budget,
                    "candidate_count": len(ranked),
                },
                recommended_action="defer and allocate a reviewed follow-up budget",
            )
            additional_findings.append(finding)
            outputs = {"resolution": "not_executed_budget_exhausted"}
            trace = _followup_trace(
                sequence=sequence,
                candidate=candidate,
                status="skipped",
                outputs=outputs,
                finding_ids=[finding.finding_id],
                duration_ms=0.0,
                error="followup_budget_exhausted",
            )
            receipt_status = "budget_exhausted"
            duration_ms = 0.0
        else:
            outputs, new_findings, duration_ms, error = executions[candidate.task_id]
            additional_findings.extend(new_findings)
            if error is not None:
                finding = _new_finding(
                    tool="governance_audit",
                    code="FOLLOWUP_TOOL_ERROR",
                    severity=Severity.HIGH,
                    sample_ids=[],
                    summary="An awarded evidence follow-up failed before completion.",
                    evidence={"task_id": candidate.task_id, "error_type": error},
                    recommended_action="defer and investigate the failed follow-up tool",
                )
                additional_findings.append(finding)
                new_findings = [*new_findings, finding]
            finding_ids = sorted(
                {
                    *candidate.linked_finding_ids,
                    *(item.finding_id for item in new_findings),
                }
            )
            trace = _followup_trace(
                sequence=sequence,
                candidate=candidate,
                status="ok" if error is None else "error",
                outputs=outputs,
                finding_ids=finding_ids,
                duration_ms=duration_ms,
                error=error,
            )
            receipt_status = "completed" if error is None else "failed"
        traces.append(trace)
        task = _dynamic_task_receipt(
            candidate=candidate,
            trace=trace,
            outputs=outputs,
            status=receipt_status,
            duration_ms=duration_ms,
            initial_decision=initial_result.decision.value,
            award_rank=award_rank,
        )
        task["dispatch_index"] = award_rank
        task["dispatch_mode"] = "bounded_parallel_after_initial_judge"
        task["planned_before_initial_evidence"] = False
        tasks.append(task)

    budget_summary: dict[str, int | str] = {
        "protocol": "contract-net-evidence-bid-v1",
        "budget_limit_units": followup_tool_budget,
        "candidate_count": len(ranked),
        "awarded_count": len(awarded),
        "completed_count": sum(item["status"] == "completed" for item in tasks),
        "failed_count": sum(item["status"] == "failed" for item in tasks),
        "budget_exhausted_count": len(rejected),
        "consumed_units": sum(
            int(item["budget"]["consumed_cost_units"]) for item in tasks
        ),
    }
    return tasks, additional_findings, traces, budget_summary


def _full_decode_summary(
    dataset_root: Path,
    records: Iterable[_ImageRecord],
) -> dict[str, int]:
    checked = 0
    failures = 0
    signatures: set[tuple[int, int, str]] = set()
    for record in sorted(records, key=lambda item: item.relative_path):
        checked += 1
        try:
            path = _validate_source_path(
                record.path,
                source_root=dataset_root,
                expected="file",
            )
            with Image.open(path) as image:
                image.verify()
            with Image.open(path) as image:
                signatures.add((image.width, image.height, image.mode))
        except (
            OmniSourceBoundaryError,
            UnidentifiedImageError,
            SyntaxError,
            OSError,
        ):
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
    metadata_path = _metadata_workbook(dataset_root)
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
        dimension_groups[
            _image_size(record.path, source_root=record.source_root)
        ].append(record)

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
        _full_decode_summary(dataset_root, records)
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
    followup_tool_budget: int = 3,
    rulepack_path: str | Path | None = None,
    agent_signal_sink: AgentRuntimeSignalSink | None = None,
) -> OmniGateRun:
    """Run organizer bytes through Workers, Council, and industrial Policy Gate."""

    if not _SHA256_RE.fullmatch(source_archive_sha256):
        raise ValueError("source_archive_sha256 must be a lowercase SHA-256 digest")
    if per_bucket < 1 or per_bucket > 20:
        raise ValueError("per_bucket must be between 1 and 20")
    if followup_tool_budget < 0 or followup_tool_budget > 8:
        raise ValueError("followup_tool_budget must be between 0 and 8")
    runtime_rulepack: RulePackRuntimeBinding | None = None
    rulepack_source_sha256: str | None = None
    if rulepack_path is not None:
        resolved_rulepack = Path(rulepack_path).expanduser().resolve(strict=True)
        runtime_rulepack = verify_rule_pack_runtime_binding(
            build_rule_pack_runtime_binding(resolved_rulepack)
        )
        rulepack_source_sha256 = sha256_file(resolved_rulepack)
        if rulepack_source_sha256 != runtime_rulepack.source_sha256:
            raise ValueError("rule pack source digest drifted during activation")
    dataset_root = _discover_dataset_root(root)
    metadata_path = _metadata_workbook(dataset_root)
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
    _emit_agent_signal(
        agent_signal_sink,
        phase="initial",
        stage=RuntimeStage.INTAKE,
        actor="Authorized Source Intake",
        action="freeze_readonly_selection",
        status=RuntimeStatus.SUCCESS,
        summary="已冻结授权来源的只读抽样清单并绑定来源与选择摘要。",
        task_id="intake.authorized-source",
        evidence_refs=[
            f"source_archive_sha256:{source_archive_sha256}",
            f"selection_manifest_sha256:{selection_manifest_sha256}",
        ],
    )
    sample_by_path = {
        record.relative_path: sample
        for record, sample in zip(selected, raw_manifest.samples, strict=True)
    }
    dimension_groups: dict[tuple[int, int] | None, list[_ImageRecord]] = defaultdict(
        list
    )
    for record in selected:
        dimension_groups[
            _image_size(record.path, source_root=record.source_root)
        ].append(record)

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
    _emit_agent_signal(
        agent_signal_sink,
        phase="initial",
        stage=RuntimeStage.PLANNER,
        actor="Deterministic Leader",
        action="plan_initial_evidence_wave",
        status=RuntimeStatus.SUCCESS,
        summary="按冻结合同规划五类只读证据工具；此阶段不调用外部模型。",
        task_id="plan.initial-evidence",
        evidence_refs=[f"selection_manifest_sha256:{selection_manifest_sha256}"],
    )
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
        contract = _gate_measurement_contract(
            width=width,
            height=height,
            runtime_rulepack=runtime_rulepack,
        )
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
    policy_contract = _gate_policy_contract(category_aliases, runtime_rulepack)
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

    for trace in traces:
        _emit_agent_signal(
            agent_signal_sink,
            phase="initial",
            stage=RuntimeStage.TOOL,
            actor=f"Deterministic Worker · {trace.tool}",
            action="execute_readonly_measurement",
            status=(
                RuntimeStatus.SUCCESS if trace.status == "ok" else RuntimeStatus.ERROR
            ),
            summary=(f"{trace.tool} 已完成只读测量并生成输入、结果与 finding 绑定。"),
            task_id=f"tool.{trace.tool}",
            tool_name=trace.tool,
            evidence_refs=[
                f"tool_input_sha256:{trace.input_sha256}",
                f"tool_result_sha256:{trace.result_sha256}",
            ],
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
                "rule_pack_binding_sha256": (
                    runtime_rulepack.binding_sha256
                    if runtime_rulepack is not None
                    else None
                ),
                "tool_result_sha256": [trace.result_sha256 for trace in traces],
            }
        )
    ).hexdigest()
    initial_council = build_council(findings, traces, aggregate_metrics)
    _emit_agent_signal(
        agent_signal_sink,
        phase="initial",
        stage=RuntimeStage.COUNCIL,
        actor="Deterministic Evidence Council",
        action="cross_examine_typed_evidence",
        status=RuntimeStatus.SUCCESS,
        summary=(
            "确定性角色解释器已对 ToolTrace 做交叉质询；它不是外部模型调用或独立专家证据。"
        ),
        task_id="council.initial-evidence",
        evidence_refs=[f"council_backend:{initial_council.backend}"],
    )
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
        runtime_rulepack=runtime_rulepack,
    )
    _emit_agent_signal(
        agent_signal_sink,
        phase="initial",
        stage=RuntimeStage.JUDGE,
        actor="Frozen Policy Judge",
        action="issue_initial_decision",
        status=RuntimeStatus.SUCCESS,
        summary=f"冻结策略基于已执行工具证据签发首轮 {initial_result.decision.value}。",
        task_id="judge.initial",
        evidence_refs=[f"gate_input_sha256:{initial_result.input_sha256}"],
    )
    _emit_agent_signal(
        agent_signal_sink,
        phase="verification",
        stage=RuntimeStage.PLANNER,
        actor="Dynamic Leader",
        action="evaluate_evidence_triggered_followups",
        status=RuntimeStatus.SUCCESS,
        summary="根据首轮中间证据、能力白名单和预算评估动态补证分支。",
        task_id="plan.dynamic-followups",
        evidence_refs=[f"initial_run_id:{initial_result.run_id}"],
    )
    dynamic_tasks, followup_findings, followup_traces, followup_budget = (
        _dynamic_leader_followups(
            initial_result,
            context=_OmniFollowupContext(
                dataset_root=dataset_root,
                metadata_path=metadata_path,
                selected=selected,
                sample_by_path=sample_by_path,
                dimension_groups=dict(dimension_groups),
                structure=structure,
                source_archive_sha256=source_archive_sha256,
                selection_manifest_sha256=selection_manifest_sha256,
                runtime_rulepack=runtime_rulepack,
            ),
            followup_tool_budget=followup_tool_budget,
        )
    )
    for task in dynamic_tasks:
        trace_reference = str(task["tool_trace_ref"])
        followup_tool_name = trace_reference.rsplit(":", 1)[-1]
        _emit_agent_signal(
            agent_signal_sink,
            phase="verification",
            stage=RuntimeStage.TOOL,
            actor=str(task["worker_id"]),
            action="execute_evidence_followup",
            status=(
                RuntimeStatus.SUCCESS
                if task["status"] == "completed"
                else RuntimeStatus.WARNING
                if task["status"] in {"skipped", "deferred"}
                else RuntimeStatus.ERROR
            ),
            summary=f"动态补证任务 {task['task_id']} 已生成有界执行回执。",
            task_id=str(task["task_id"]),
            tool_name=followup_tool_name,
            evidence_refs=[
                *list(task["input_refs"]),
                f"result_sha256:{task['result_sha256']}",
            ],
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
    traces.extend(followup_traces)
    aggregate_metrics["finding_count"] = len(findings)
    aggregate_metrics["tool_count"] = len(traces)
    aggregate_metrics["tool_error_count"] = sum(
        trace.status != "ok" for trace in traces
    )
    aggregate_metrics["leader_dynamic_task_count"] = len(dynamic_tasks)
    aggregate_metrics["leader_replan_count"] = int(bool(dynamic_tasks))
    aggregate_metrics["leader_followup_finding_count"] = len(followup_findings)
    aggregate_metrics["leader_followup_tool_trace_count"] = len(followup_traces)
    aggregate_metrics["leader_followup_budget_exhausted_count"] = int(
        followup_budget["budget_exhausted_count"]
    )
    dispatch_plan = {
        "schema_version": "visiondata-gate.dynamic-leader-plan.v2",
        "planner": "leader.release-gate",
        "mode": "evidence_triggered_replan",
        "control_loop": "observe-orient-decide-act-verify",
        "dispatch_protocol": "contract-net-evidence-bid-v1",
        "jidoka_policy": (
            "stop and DEFER on failed, skipped, unsupported, or budget-exhausted evidence"
        ),
        "static_task_count": 5,
        "dynamic_task_count": len(dynamic_tasks),
        "replan_count": int(bool(dynamic_tasks)),
        "initial_decision": initial_result.decision.value,
        "dynamic_tasks": dynamic_tasks,
        "followup_budget": followup_budget,
        "rule_pack_runtime_status": (
            "ACTIVATED" if runtime_rulepack is not None else "NOT_CONFIGURED"
        ),
        "rule_pack_source_sha256": rulepack_source_sha256,
        "rule_pack_binding": (
            runtime_rulepack.model_dump(mode="json")
            if runtime_rulepack is not None
            else None
        ),
        "branch_types": sorted(
            task["task_id"].removeprefix("followup.") for task in dynamic_tasks
        ),
        "claim_boundary": (
            "Dynamic tasks are deterministic, read-only AI Workers dispatched from "
            "intermediate evidence. They do not grant production authority."
        ),
        "hash_contract": {
            "canonicalization": "visiondata_gate.evidence.canonical_json_bytes",
            "semantic_hash_excludes": ["duration_ms"],
            "operational_hash_scope": "complete dispatch plan including duration_ms",
        },
    }
    semantic_dispatch_plan = _semantic_plan_payload(dispatch_plan)
    if not isinstance(semantic_dispatch_plan, dict):  # defensive typing invariant
        raise TypeError("semantic dispatch plan must be an object")
    semantic_dispatch_plan_sha256 = hashlib.sha256(
        canonical_json_bytes(semantic_dispatch_plan)
    ).hexdigest()
    operational_dispatch_plan_sha256 = hashlib.sha256(
        canonical_json_bytes(dispatch_plan)
    ).hexdigest()
    followup_trace_bindings = [
        {
            "sequence": trace.sequence,
            "tool": trace.tool,
            "status": trace.status,
            "input_sha256": trace.input_sha256,
            "result_sha256": trace.result_sha256,
            "finding_ids": sorted(trace.finding_ids),
        }
        for trace in followup_traces
    ]
    final_input_sha256 = hashlib.sha256(
        canonical_json_bytes(
            {
                "initial_input_sha256": initial_result.input_sha256,
                "semantic_dispatch_plan_sha256": semantic_dispatch_plan_sha256,
                "followup_finding_ids": [item.finding_id for item in followup_findings],
                "followup_trace_bindings": followup_trace_bindings,
            }
        )
    ).hexdigest()
    council = build_council(findings, traces, aggregate_metrics)
    _emit_agent_signal(
        agent_signal_sink,
        phase="verification",
        stage=RuntimeStage.COUNCIL,
        actor="Deterministic Evidence Council",
        action="review_followup_evidence",
        status=RuntimeStatus.SUCCESS,
        summary=(
            "确定性角色解释器已复核首轮与动态补证证据；最终放行仍由冻结策略裁决。"
        ),
        task_id="council.verification",
        evidence_refs=[
            f"council_backend:{council.backend}",
            f"semantic_dispatch_plan_sha256:{semantic_dispatch_plan_sha256}",
        ],
    )
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
        runtime_rulepack=runtime_rulepack,
    )
    _emit_agent_signal(
        agent_signal_sink,
        phase="verification",
        stage=RuntimeStage.JUDGE,
        actor="Frozen Policy Judge",
        action="issue_final_decision",
        status=RuntimeStatus.SUCCESS,
        summary=f"冻结策略签发最终 {gate_result.decision.value}，生产授权仍保持 human_only。",
        task_id="judge.final",
        evidence_refs=[f"gate_input_sha256:{gate_result.input_sha256}"],
    )
    leader_plan = {
        **dispatch_plan,
        # Backwards-compatible name now explicitly denotes the stable semantic hash.
        "dispatch_plan_sha256": semantic_dispatch_plan_sha256,
        "semantic_dispatch_plan_sha256": semantic_dispatch_plan_sha256,
        "operational_dispatch_plan_sha256": operational_dispatch_plan_sha256,
        "followup_trace_bindings": followup_trace_bindings,
        "final_decision": gate_result.decision.value,
        "decision_changed": (
            gate_result.decision.value != initial_result.decision.value
        ),
        "stage_gates": [
            {
                "gate": "G1_INITIAL_EVIDENCE",
                "status": "PASS"
                if all(trace.status == "ok" for trace in initial_result.tool_trace)
                else "STOP",
            },
            {
                "gate": "G2_FOLLOWUP_BUDGET",
                "status": (
                    "PASS"
                    if int(followup_budget["budget_exhausted_count"]) == 0
                    else "STOP"
                ),
            },
            {
                "gate": "G3_FROZEN_JUDGE",
                "status": "COMPLETED",
                "decision": gate_result.decision.value,
            },
            {
                "gate": "G4_PRODUCTION_AUTHORITY",
                "status": "HUMAN_APPROVAL_REQUIRED",
            },
        ],
    }
    output_root = Path(output).expanduser().resolve()
    output_root.mkdir(parents=True, exist_ok=True)
    initial_gate_result_path = output_root / "initial_gate_result.json"
    initial_gate_result_sha256 = write_canonical_json(
        initial_gate_result_path, initial_result
    )
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
        "leader_followup_tool_trace_count": len(followup_traces),
        "leader_followup_budget": followup_budget,
        "rule_pack_runtime_status": (
            "ACTIVATED" if runtime_rulepack is not None else "NOT_CONFIGURED"
        ),
        "rule_pack_source_sha256": rulepack_source_sha256,
        "rule_pack_binding_sha256": (
            runtime_rulepack.binding_sha256 if runtime_rulepack is not None else None
        ),
        "dispatch_plan_sha256": semantic_dispatch_plan_sha256,
        "semantic_dispatch_plan_sha256": semantic_dispatch_plan_sha256,
        "operational_dispatch_plan_sha256": operational_dispatch_plan_sha256,
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
    _emit_agent_signal(
        agent_signal_sink,
        phase="verification",
        stage=RuntimeStage.DELIVERY,
        actor="Evidence Delivery",
        action="seal_redacted_gate_artifacts",
        status=RuntimeStatus.SUCCESS,
        summary="已完成证据写入、摘要绑定和来源路径泄漏检查。",
        task_id="delivery.gate-evidence",
        evidence_refs=[
            f"gate_result_sha256:{gate_result_sha256}",
            f"dynamic_leader_plan_sha256:{leader_plan_sha256}",
            f"omni_gate_receipt_sha256:{receipt_sha256}",
        ],
    )
    return OmniGateRun(
        output_root=output_root,
        initial_result=initial_result,
        initial_gate_result_path=initial_gate_result_path,
        initial_gate_result_sha256=initial_gate_result_sha256,
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
    "profile_omni_source",
    "run_omni_readonly_gate",
    "run_omni_readonly_smoke",
]
