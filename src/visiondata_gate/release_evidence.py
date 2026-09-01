"""Executable RC3 release-evidence pipeline.

The helpers in this module turn a clean, committed Git tree into local release
evidence.  They deliberately keep test execution, deterministic packaging,
and attestation generation separate from the incident kernel.

All generated files must live in an ignored project-local namespace.  A
failure leaves that namespace in place for diagnosis and never emits a PASS
attestation.
"""

from __future__ import annotations

import os
import re
import stat
import subprocess
import zipfile
from collections.abc import Callable, Sequence
from pathlib import Path, PurePosixPath
from typing import Any
from xml.etree import ElementTree

from .audit_envelope import canonical_jcs_bytes
from .evidence import sha256_file
from .package import (
    DEFAULT_MAX_FILE_SIZE,
    audit_submission_zip,
    build_deterministic_zip,
    validate_archive_path,
)
from .release_attestation import (
    RC3_REQUIRED_PATHS,
    ArtifactBinding,
    BuilderIdentity,
    CleanExtractAudit,
    CleanExtractReceipt,
    FullTestInputs,
    FullTestReceipt,
    FullTestResult,
    GitSourceState,
    ReleaseAttestationError,
    ReleaseBuildReceipt,
    Sha256Digest,
    build_release_attestation,
    detect_release_toolchain,
    get_clean_git_source_state,
    verify_release_attestation,
    write_release_attestation,
)


FULL_TEST_COMMAND_PREFIX = (
    "uv",
    "run",
    "--frozen",
    "python",
    "-m",
    "pytest",
    "-q",
)
DEFAULT_BUILDER_ID = "local://visiondata-gate/release-builder"
MAX_JUNIT_BYTES = 64 * 1024 * 1024
MAX_GIT_ARCHIVE_BYTES = 512 * 1024 * 1024
FULL_TEST_TIMEOUT_SECONDS = 60 * 60
BUILD_TIMEOUT_SECONDS = 20 * 60

CommandRunner = Callable[..., subprocess.CompletedProcess[str]]


class ReleaseEvidenceError(ReleaseAttestationError):
    """Raised when executable release-evidence generation fails closed."""


def _clean_source(root: Path) -> GitSourceState:
    try:
        return get_clean_git_source_state(root)
    except ReleaseAttestationError as exc:
        raise ReleaseEvidenceError(str(exc)) from exc


def _reject_output_links(root: Path, relative: str, *, label: str) -> None:
    current = root
    for part in PurePosixPath(relative).parts:
        current = current / part
        if not current.exists():
            continue
        try:
            is_junction = current.is_junction()
        except (AttributeError, OSError):
            is_junction = False
        try:
            is_symlink = current.is_symlink()
        except OSError:
            is_symlink = False
        if is_symlink or is_junction:
            raise ReleaseEvidenceError(f"{label} contains a symlink or junction")


def _relative_output_path(root: Path, value: str | Path, *, label: str) -> str:
    supplied = Path(value)
    candidate = supplied if supplied.is_absolute() else root / supplied
    try:
        relative = candidate.absolute().relative_to(root).as_posix()
    except ValueError as exc:
        raise ReleaseEvidenceError(
            f"{label} must stay inside the project root"
        ) from exc
    if (
        not relative
        or relative.startswith("/")
        or "\\" in relative
        or any(
            part in {"", ".", ".."} or ":" in part
            for part in PurePosixPath(relative).parts
        )
    ):
        raise ReleaseEvidenceError(f"{label} is not a stable POSIX relative path")
    try:
        validate_archive_path(relative)
    except ValueError as exc:
        raise ReleaseEvidenceError(
            f"{label} violates the portable path contract"
        ) from exc
    _reject_output_links(root, relative, label=label)
    return relative


def _path_from_relative(root: Path, relative: str) -> Path:
    return root.joinpath(*PurePosixPath(relative).parts)


def _artifact_binding(root: Path, path: Path) -> ArtifactBinding:
    relative = _relative_output_path(root, path, label="artifact")
    if not path.is_file() or path.stat().st_size <= 0:
        raise ReleaseEvidenceError(f"required artifact is missing or empty: {relative}")
    return ArtifactBinding(
        path=relative,
        digest=Sha256Digest(sha256=sha256_file(path)),
        size_bytes=path.stat().st_size,
    )


def _write_model_jcs(path: Path, model: Any) -> str:
    if path.exists():
        raise ReleaseEvidenceError(f"refusing to overwrite release evidence: {path}")
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = model.model_dump(mode="json", by_alias=True, exclude_none=False)
    path.write_bytes(canonical_jcs_bytes(payload))
    return sha256_file(path)


def _run_text_command(
    command: Sequence[str],
    *,
    cwd: Path,
    timeout: int,
    runner: CommandRunner = subprocess.run,
) -> subprocess.CompletedProcess[str]:
    try:
        return runner(
            list(command),
            cwd=cwd,
            check=False,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="strict",
            timeout=timeout,
            env={
                name: value
                for name, value in os.environ.items()
                if not name.upper().startswith("GIT_")
            },
        )
    except (OSError, subprocess.TimeoutExpired, UnicodeError) as exc:
        raise ReleaseEvidenceError(
            f"release command could not complete: {exc}"
        ) from exc


def _require_ignored_namespace(root: Path, relative: str) -> None:
    result = _run_text_command(
        ["git", "check-ignore", "-q", "--", relative],
        cwd=root,
        timeout=30,
    )
    if result.returncode != 0:
        raise ReleaseEvidenceError(
            "release output namespace must be covered by the repository .gitignore"
        )


def parse_pytest_junit(path: str | Path) -> dict[str, int]:
    """Return fail-closed aggregate counts from one pytest JUnit XML file."""

    junit = Path(path)
    if not junit.is_file():
        raise ReleaseEvidenceError("pytest did not produce the required JUnit file")
    size = junit.stat().st_size
    if size <= 0 or size > MAX_JUNIT_BYTES:
        raise ReleaseEvidenceError("JUnit file size is outside the accepted boundary")
    try:
        root = ElementTree.parse(junit).getroot()
    except (ElementTree.ParseError, OSError) as exc:
        raise ReleaseEvidenceError(f"JUnit XML is unreadable: {exc}") from exc

    if root.tag == "testsuite":
        suites = [root]
    elif root.tag == "testsuites":
        suites = list(root.findall("testsuite"))
    else:
        raise ReleaseEvidenceError("JUnit root must be testsuite or testsuites")
    if not suites:
        raise ReleaseEvidenceError("JUnit XML contains no test suites")

    totals = {"tests": 0, "failures": 0, "errors": 0, "skipped": 0}
    for suite in suites:
        for name in totals:
            raw = suite.attrib.get(name, "0")
            if not re.fullmatch(r"[0-9]+", raw):
                raise ReleaseEvidenceError(f"JUnit {name} count is invalid")
            totals[name] += int(raw)
    passed = totals["tests"] - totals["failures"] - totals["errors"] - totals["skipped"]
    if totals["tests"] <= 0 or passed < 0:
        raise ReleaseEvidenceError("JUnit aggregate counts are inconsistent")
    return {
        "passed": passed,
        "failed": totals["failures"],
        "errors": totals["errors"],
        "skipped": totals["skipped"],
    }


def _warning_count(output: str) -> int:
    matches = [int(value) for value in re.findall(r"(?m)(\d+) warnings?\b", output)]
    return max(matches, default=0)


def run_full_regression(
    *,
    project_root: str | Path,
    junit_path: str | Path,
    runner: CommandRunner = subprocess.run,
    timeout: int = FULL_TEST_TIMEOUT_SECONDS,
) -> FullTestReceipt:
    """Execute the unfiltered repository test command and bind its JUnit bytes."""

    root = Path(project_root).resolve(strict=True)
    source = _clean_source(root)
    pytest_addopts = os.environ.get("PYTEST_ADDOPTS", "")
    if pytest_addopts:
        raise ReleaseEvidenceError(
            "PYTEST_ADDOPTS must be unset or empty for a full-test receipt"
        )
    junit_relative = _relative_output_path(root, junit_path, label="JUnit path")
    junit = _path_from_relative(root, junit_relative)
    if junit.exists():
        raise ReleaseEvidenceError(f"refusing to overwrite JUnit artifact: {junit}")
    junit.parent.mkdir(parents=True, exist_ok=True)
    command = [*FULL_TEST_COMMAND_PREFIX, f"--junitxml={junit_relative}"]
    completed = _run_text_command(
        command,
        cwd=root,
        timeout=timeout,
        runner=runner,
    )
    counts = parse_pytest_junit(junit)
    if completed.returncode != 0 or counts["failed"] or counts["errors"]:
        raise ReleaseEvidenceError(
            "full repository regression did not pass; no PASS receipt was emitted"
        )
    if _clean_source(root) != source:
        raise ReleaseEvidenceError("Git source drifted during full regression")
    return FullTestReceipt(
        source=source,
        inputs=FullTestInputs(
            uv_lock_sha256=sha256_file(root / "uv.lock"),
            sbom_sha256=sha256_file(root / "docs" / "SBOM.cdx.json"),
        ),
        junit=_artifact_binding(root, junit),
        result=FullTestResult(
            command_argv=command,
            passed=counts["passed"],
            failed=0,
            errors=0,
            skipped=counts["skipped"],
            warnings=_warning_count(completed.stdout + "\n" + completed.stderr),
        ),
    )


def _safe_extract_git_archive(archive_path: Path, destination: Path) -> None:
    total = 0
    seen: set[str] = set()
    with zipfile.ZipFile(archive_path, mode="r") as archive:
        for info in archive.infolist():
            name = info.filename.rstrip("/")
            if not name:
                continue
            try:
                validate_archive_path(name)
            except ValueError as exc:
                raise ReleaseEvidenceError(
                    f"Git archive contains an unsafe path: {exc}"
                ) from exc
            relative = _relative_output_path(
                destination, destination / name, label="Git archive member"
            )
            folded = relative.casefold()
            if folded in seen:
                raise ReleaseEvidenceError("Git archive contains colliding paths")
            seen.add(folded)
            mode = (info.external_attr >> 16) & 0xFFFF
            if stat.S_IFMT(mode) == stat.S_IFLNK:
                raise ReleaseEvidenceError("Git archive contains a symbolic link")
            if info.file_size > DEFAULT_MAX_FILE_SIZE:
                raise ReleaseEvidenceError("Git archive member exceeds the file limit")
            total += info.file_size
            if total > MAX_GIT_ARCHIVE_BYTES:
                raise ReleaseEvidenceError("Git archive exceeds the extraction limit")
            target = destination.joinpath(*PurePosixPath(relative).parts)
            if info.is_dir():
                target.mkdir(parents=True, exist_ok=True)
                continue
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(archive.read(info))


def build_rc3_candidate(
    *,
    project_root: str | Path,
    workspace: str | Path,
    output: str | Path,
    required_paths: Sequence[str] = RC3_REQUIRED_PATHS,
) -> dict[str, Any]:
    """Build one candidate from a clean ``git archive HEAD`` source snapshot."""

    root = Path(project_root).resolve(strict=True)
    source = _clean_source(root)
    workspace_relative = _relative_output_path(root, workspace, label="workspace")
    output_relative = _relative_output_path(root, output, label="candidate output")
    workspace_path = _path_from_relative(root, workspace_relative)
    output_path = _path_from_relative(root, output_relative)
    try:
        output_path.relative_to(workspace_path)
    except ValueError as exc:
        raise ReleaseEvidenceError(
            "candidate output must stay inside its workspace"
        ) from exc
    if workspace_path.exists():
        raise ReleaseEvidenceError(
            f"refusing to reuse build workspace: {workspace_path}"
        )
    _require_ignored_namespace(root, workspace_relative)
    workspace_path.mkdir(parents=True)
    archive_path = workspace_path / "source-tree.zip"
    export = _run_text_command(
        [
            "git",
            "archive",
            "--format=zip",
            f"--output={archive_path}",
            source.commit,
        ],
        cwd=root,
        timeout=BUILD_TIMEOUT_SECONDS,
    )
    if export.returncode != 0 or not archive_path.is_file():
        raise ReleaseEvidenceError("git archive failed; candidate was not built")
    source_dir = workspace_path / "source"
    source_dir.mkdir()
    _safe_extract_git_archive(archive_path, source_dir)
    build = build_deterministic_zip(source_dir, output_path)
    audit = audit_submission_zip(output_path, required_paths=list(required_paths))
    if not audit.ok:
        detail = "; ".join(f"{issue.code}:{issue.path}" for issue in audit.issues[:5])
        raise ReleaseEvidenceError(f"candidate package audit failed: {detail}")
    if _clean_source(root) != source:
        raise ReleaseEvidenceError("Git source drifted during candidate build")
    return {
        "status": "PASS_LOCAL_CANDIDATE",
        "source": source.model_dump(mode="json"),
        "workspace": workspace_relative,
        "artifact": _artifact_binding(root, output_path).model_dump(mode="json"),
        "build": build.to_dict(),
        "audit": audit.to_dict(),
        "submission_eligible": False,
    }


def _build_receipt(
    *,
    root: Path,
    source: GitSourceState,
    command: list[str],
    invocation_id: str,
    workspace: str,
    output: Path,
    builder: BuilderIdentity,
) -> ReleaseBuildReceipt:
    return ReleaseBuildReceipt(
        source=source,
        inputs=FullTestInputs(
            uv_lock_sha256=sha256_file(root / "uv.lock"),
            sbom_sha256=sha256_file(root / "docs" / "SBOM.cdx.json"),
        ),
        invocation_id=invocation_id,
        workspace=workspace,
        command_argv=command,
        output=_artifact_binding(root, output),
        builder=builder,
    )


def build_rc3_release_evidence(
    *,
    project_root: str | Path,
    release_id: str,
    output_root: str | Path,
    builder_id: str = DEFAULT_BUILDER_ID,
    full_test_runner: CommandRunner = subprocess.run,
    candidate_runner: CommandRunner = subprocess.run,
    required_paths: Sequence[str] = RC3_REQUIRED_PATHS,
) -> dict[str, Any]:
    """Run full regression, two builds, clean audit, and unsigned attestation."""

    root = Path(project_root).resolve(strict=True)
    source = _clean_source(root)
    if (
        not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._:/@+-]{2,159}", release_id)
        or "//" in release_id
    ):
        raise ReleaseEvidenceError("release_id uses an invalid identifier syntax")
    normalized_required_paths = tuple(sorted(set(required_paths)))
    if normalized_required_paths != tuple(sorted(RC3_REQUIRED_PATHS)):
        raise ReleaseEvidenceError(
            "required paths must equal the frozen RC3 submission policy"
        )
    namespace = _relative_output_path(root, output_root, label="release namespace")
    namespace_path = _path_from_relative(root, namespace)
    if namespace_path.exists():
        raise ReleaseEvidenceError(
            f"refusing to reuse release evidence namespace: {namespace_path}"
        )
    _require_ignored_namespace(root, namespace)
    namespace_path.mkdir(parents=True)

    junit_relative = f"{namespace}/full-test.junit.xml"
    full_receipt = run_full_regression(
        project_root=root,
        junit_path=junit_relative,
        runner=full_test_runner,
    )
    full_receipt_path = namespace_path / "full-test.receipt.json"
    _write_model_jcs(full_receipt_path, full_receipt)

    toolchain = detect_release_toolchain()
    builder = BuilderIdentity(builder_id=builder_id, toolchain=toolchain)
    build_records: list[tuple[str, Path, Path, ReleaseBuildReceipt]] = []
    for ordinal in (1, 2):
        workspace = f"{namespace}/build-{ordinal}"
        output_relative = f"{workspace}/VisionData_Gate_RC3.zip"
        output = _path_from_relative(root, output_relative)
        command = [
            "uv",
            "run",
            "--frozen",
            "python",
            "tools/build_rc3_candidate.py",
            "--project-root",
            ".",
            "--workspace",
            workspace,
            "--output",
            output_relative,
        ]
        completed = _run_text_command(
            command,
            cwd=root,
            timeout=BUILD_TIMEOUT_SECONDS,
            runner=candidate_runner,
        )
        if completed.returncode != 0 or not output.is_file():
            raise ReleaseEvidenceError(
                f"candidate build {ordinal} failed; no release receipt was emitted"
            )
        audit = audit_submission_zip(
            output,
            required_paths=list(normalized_required_paths),
        )
        if not audit.ok:
            raise ReleaseEvidenceError(f"candidate build {ordinal} failed live audit")
        receipt = _build_receipt(
            root=root,
            source=source,
            command=command,
            invocation_id=f"{release_id}/build-{ordinal}",
            workspace=workspace,
            output=output,
            builder=builder,
        )
        receipt_path = namespace_path / f"build-{ordinal}.receipt.json"
        _write_model_jcs(receipt_path, receipt)
        build_records.append((workspace, output, receipt_path, receipt))

    first_output = build_records[0][1]
    second_output = build_records[1][1]
    if first_output.stat().st_size != second_output.stat().st_size or sha256_file(
        first_output
    ) != sha256_file(second_output):
        raise ReleaseEvidenceError("two candidate builds are not byte-identical")

    first_audit = audit_submission_zip(
        first_output,
        required_paths=list(normalized_required_paths),
    )
    clean_receipt = CleanExtractReceipt(
        source=source,
        candidate=_artifact_binding(root, first_output),
        required_paths=list(normalized_required_paths),
        audit=CleanExtractAudit(
            entry_count=first_audit.entry_count,
            verified_file_count=first_audit.verified_file_count,
        ),
    )
    clean_receipt_path = namespace_path / "clean-extract.receipt.json"
    _write_model_jcs(clean_receipt_path, clean_receipt)

    if _clean_source(root) != source:
        raise ReleaseEvidenceError("Git source drifted before attestation build")
    attestation = build_release_attestation(
        project_root=root,
        release_id=release_id,
        candidate_zip=first_output,
        reproducible_zip=second_output,
        full_test_receipt=full_receipt_path,
        clean_extract_receipt=clean_receipt_path,
        build_one_receipt=build_records[0][2],
        build_two_receipt=build_records[1][2],
        builder_id=builder_id,
        toolchain=toolchain,
    )
    attestation_path = namespace_path / "release.attestation.json"
    attestation_sha256 = write_release_attestation(
        attestation_path,
        attestation,
        project_root=root,
    )
    verified = verify_release_attestation(
        project_root=root,
        attestation_path=attestation_path,
    )
    return {
        "status": "PASS_LOCAL_RC3_RELEASE_CANDIDATE",
        "release_id": release_id,
        "source": source.model_dump(mode="json"),
        "full_test": {
            "passed": full_receipt.result.passed,
            "skipped": full_receipt.result.skipped,
            "warnings": full_receipt.result.warnings,
            "junit_sha256": full_receipt.junit.digest.sha256,
        },
        "candidate_sha256": sha256_file(first_output),
        "two_builds_byte_identical": True,
        "attestation": {
            "path": _relative_output_path(
                root,
                attestation_path,
                label="attestation",
            ),
            "sha256": attestation_sha256,
            "statement_digest": attestation.statement_digest.value,
            "verification_status": verified.status,
        },
        "signature": "NOT_CONFIGURED",
        "trusted_timestamp": "NOT_CONFIGURED",
        "external_anchor": "NOT_CONFIGURED",
        "submission_eligible": False,
        "official_status": "NOT_EVALUATED",
    }


__all__ = [
    "BUILD_TIMEOUT_SECONDS",
    "DEFAULT_BUILDER_ID",
    "FULL_TEST_COMMAND_PREFIX",
    "FULL_TEST_TIMEOUT_SECONDS",
    "ReleaseEvidenceError",
    "build_rc3_candidate",
    "build_rc3_release_evidence",
    "parse_pytest_junit",
    "run_full_regression",
]
