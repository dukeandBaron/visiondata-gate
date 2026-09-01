from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import zipfile
from dataclasses import dataclass
from pathlib import Path

import pytest

import visiondata_gate.release_attestation as release_attestation_module
from visiondata_gate.audit_envelope import canonical_jcs_bytes
from visiondata_gate.evidence import sha256_file
from visiondata_gate.release_attestation import (
    RC3_REQUIRED_PATHS,
    ReleaseAttestationError,
    build_release_attestation,
    detect_release_toolchain,
    load_release_attestation,
    release_attestation_bytes,
    verify_release_attestation,
    write_release_attestation,
)
from visiondata_gate.package import (
    DEFAULT_SUBMISSION_REQUIRED_PATHS,
    audit_submission_zip,
    build_deterministic_zip,
)


PROJECT_ROOT = Path(__file__).resolve().parents[1]
PRODUCTION_RC3_REQUIRED_PATHS = RC3_REQUIRED_PATHS
TEST_RC3_REQUIRED_PATHS = ("NOTICE", "README.md")


@pytest.fixture(autouse=True)
def _use_compact_rc3_policy_for_unit_fixtures(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Keep per-test ZIP fixtures small; policy identity is tested separately."""

    monkeypatch.setattr(
        release_attestation_module,
        "RC3_REQUIRED_PATHS",
        TEST_RC3_REQUIRED_PATHS,
    )


@dataclass(frozen=True)
class ReleaseFixture:
    root: Path
    candidate_one: Path
    candidate_two: Path
    junit: Path
    full_test_receipt: Path
    clean_extract_receipt: Path
    build_one_receipt: Path
    build_two_receipt: Path
    source: dict[str, object]
    toolchain: dict[str, str]


def _git(root: Path, *arguments: str) -> str:
    completed = subprocess.run(
        ["git", "-C", str(root), *arguments],
        check=True,
        capture_output=True,
        text=True,
        encoding="utf-8",
    )
    return completed.stdout.strip()


def _write_zip(path: Path, *, payload: bytes = b"release-payload\n") -> None:
    info = zipfile.ZipInfo("README.txt", date_time=(1980, 1, 1, 0, 0, 0))
    info.compress_type = zipfile.ZIP_STORED
    info.create_system = 3
    info.external_attr = 0o100644 << 16
    with zipfile.ZipFile(path, mode="w", compression=zipfile.ZIP_STORED) as archive:
        archive.writestr(info, payload)


def _write_jcs(path: Path, value: object) -> None:
    path.write_bytes(canonical_jcs_bytes(value))


def _build_release_fixture(
    tmp_path: Path,
    *,
    required_paths: tuple[str, ...] = TEST_RC3_REQUIRED_PATHS,
) -> ReleaseFixture:
    root = tmp_path / "project"
    artifacts = root / "artifacts"
    docs = root / "docs"
    tools_dir = root / "tools"
    artifacts.mkdir(parents=True)
    docs.mkdir()
    tools_dir.mkdir()
    (root / ".gitignore").write_text("artifacts/\n", encoding="utf-8")
    (root / "uv.lock").write_text(
        'version = 1\nrevision = 3\n\n[[package]]\nname = "demo"\nversion = "1"\n',
        encoding="utf-8",
    )
    _write_jcs(
        docs / "SBOM.cdx.json",
        {
            "bomFormat": "CycloneDX",
            "components": [{"name": "demo", "type": "application", "version": "1"}],
            "metadata": {
                "component": {
                    "name": "demo",
                    "properties": [
                        {"name": "visiondata-gate:ecosystem", "value": "python"}
                    ],
                    "type": "application",
                },
                "properties": [
                    {
                        "name": "visiondata-gate:lock-sha256:uv.lock",
                        "value": sha256_file(root / "uv.lock"),
                    }
                ],
            },
            "specVersion": "1.6",
            "version": 1,
        },
    )
    (tools_dir / "fixture_builder.py").write_text(
        '"""Tracked fixture build entrypoint."""\n',
        encoding="utf-8",
    )
    _git(root, "init")
    _git(root, "config", "user.email", "release-test@example.invalid")
    _git(root, "config", "user.name", "Release Test")
    # A developer-level global ignore may contain generated SBOM patterns.  The
    # fixture deliberately tracks this required release material regardless.
    _git(root, "add", ".gitignore", "uv.lock", "tools/fixture_builder.py")
    _git(root, "add", "-f", "docs/SBOM.cdx.json")
    _git(root, "commit", "-m", "fixture")

    source: dict[str, object] = {
        "commit": _git(root, "rev-parse", "HEAD"),
        "tree": _git(root, "rev-parse", "HEAD^{tree}"),
        "dirty": False,
    }
    package_source = artifacts / "package-source"
    package_source.mkdir()
    for required_path in required_paths:
        target = package_source.joinpath(*required_path.split("/"))
        target.parent.mkdir(parents=True, exist_ok=True)
        source_file = PROJECT_ROOT.joinpath(*required_path.split("/"))
        if required_paths == PRODUCTION_RC3_REQUIRED_PATHS:
            shutil.copyfile(source_file, target)
        else:
            target.write_text("release fixture payload\n", encoding="utf-8")
    build_one_workspace = artifacts / "build-one"
    build_two_workspace = artifacts / "build-two"
    build_one_workspace.mkdir()
    build_two_workspace.mkdir()
    candidate_one = build_one_workspace / "candidate.zip"
    candidate_two = build_two_workspace / "candidate.zip"
    build_deterministic_zip(package_source, candidate_one)
    build_deterministic_zip(package_source, candidate_two)
    candidate_sha256 = sha256_file(candidate_one)
    package_audit = audit_submission_zip(
        candidate_one,
        required_paths=required_paths,
    )
    assert package_audit.ok
    toolchain = detect_release_toolchain()
    builder = {
        "builder_id": "local://builder/release-test",
        "identity_assurance": (
            "REQUIRED_VERSIONS_LOCALLY_PROBED_IDENTITY_NOT_AUTHENTICATED"
        ),
        "toolchain": toolchain,
    }
    input_binding = {
        "sbom_sha256": sha256_file(docs / "SBOM.cdx.json"),
        "uv_lock_sha256": sha256_file(root / "uv.lock"),
    }

    junit = artifacts / "full-test.junit.xml"
    junit.write_text(
        '<?xml version="1.0" encoding="utf-8"?>'
        '<testsuites tests="322" failures="0" errors="0" skipped="1">'
        '<testsuite name="pytest" tests="322" failures="0" errors="0" '
        'skipped="1" />'
        "</testsuites>",
        encoding="utf-8",
        newline="",
    )
    full_test_receipt = artifacts / "full-test.receipt.json"
    _write_jcs(
        full_test_receipt,
        {
            "claim_boundary": (
                "LOCAL_FULL_REGRESSION_RESULT_NOT_EXTERNAL_CERTIFICATION"
            ),
            "inputs": input_binding,
            "junit": {
                "digest": {"sha256": sha256_file(junit)},
                "path": "artifacts/full-test.junit.xml",
                "size_bytes": junit.stat().st_size,
            },
            "result": {
                "command_argv": [
                    "uv",
                    "run",
                    "--frozen",
                    "python",
                    "-m",
                    "pytest",
                    "-q",
                    "--junitxml=artifacts/full-test.junit.xml",
                ],
                "cwd": ".",
                "errors": 0,
                "exit_code": 0,
                "failed": 0,
                "passed": 321,
                "pytest_addopts": "",
                "skipped": 1,
                "warnings": 0,
            },
            "schema_version": "visiondata-gate.full-test-receipt.v2",
            "scope": "FULL_REPOSITORY",
            "source": source,
            "status": "PASS",
        },
    )
    clean_extract_receipt = artifacts / "clean-extract.receipt.json"
    _write_jcs(
        clean_extract_receipt,
        {
            "audit": {
                "clean_extract_verified": True,
                "credential_scan_passed": True,
                "entry_count": package_audit.entry_count,
                "issue_count": 0,
                "ok": True,
                "private_path_scan_passed": True,
                "required_paths_verified": True,
                "verified_file_count": package_audit.verified_file_count,
            },
            "audit_tool": {
                "implementation": "visiondata_gate.package.audit_submission_zip",
                "manifest_schema": "visiondata-gate.submission-manifest.v1",
            },
            "candidate": {
                "digest": {"sha256": candidate_sha256},
                "path": "artifacts/build-one/candidate.zip",
                "size_bytes": candidate_one.stat().st_size,
            },
            "claim_boundary": ("LOCAL_CLEAN_EXTRACT_AUDIT_NOT_EXTERNAL_CERTIFICATION"),
            "schema_version": "visiondata-gate.clean-extract-receipt.v1",
            "required_paths": list(required_paths),
            "source": source,
            "status": "PASS",
        },
    )
    build_one_receipt = artifacts / "build-one.receipt.json"
    build_two_receipt = artifacts / "build-two.receipt.json"
    for receipt_path, invocation_id, workspace, candidate_path in (
        (
            build_one_receipt,
            "build/one",
            "artifacts/build-one",
            candidate_one,
        ),
        (
            build_two_receipt,
            "build/two",
            "artifacts/build-two",
            candidate_two,
        ),
    ):
        relative_output = candidate_path.relative_to(root).as_posix()
        _write_jcs(
            receipt_path,
            {
                "builder": builder,
                "claim_boundary": (
                    "LOCAL_BUILD_INVOCATION_RECEIPT_NOT_AUTHENTICATED_BY_EXTERNAL_BUILDER"
                ),
                "clean_workspace": True,
                "command_argv": [
                    "uv",
                    "run",
                    "--frozen",
                    "python",
                    "tools/fixture_builder.py",
                    "--workspace",
                    workspace,
                    "--output",
                    relative_output,
                ],
                "inputs": input_binding,
                "invocation_id": invocation_id,
                "output": {
                    "digest": {"sha256": sha256_file(candidate_path)},
                    "path": relative_output,
                    "size_bytes": candidate_path.stat().st_size,
                },
                "schema_version": "visiondata-gate.release-build-receipt.v1",
                "source": source,
                "status": "PASS",
                "workspace": workspace,
            },
        )
    assert _git(root, "status", "--porcelain=v1") == ""
    return ReleaseFixture(
        root=root,
        candidate_one=candidate_one,
        candidate_two=candidate_two,
        junit=junit,
        full_test_receipt=full_test_receipt,
        clean_extract_receipt=clean_extract_receipt,
        build_one_receipt=build_one_receipt,
        build_two_receipt=build_two_receipt,
        source=source,
        toolchain=toolchain,
    )


def _copy_release_fixture(template: ReleaseFixture, root: Path) -> ReleaseFixture:
    """Clone one immutable prepared repository for an isolated mutation test."""

    shutil.copytree(template.root, root, copy_function=shutil.copy2)
    return ReleaseFixture(
        root=root,
        candidate_one=root / "artifacts" / "build-one" / "candidate.zip",
        candidate_two=root / "artifacts" / "build-two" / "candidate.zip",
        junit=root / "artifacts" / "full-test.junit.xml",
        full_test_receipt=root / "artifacts" / "full-test.receipt.json",
        clean_extract_receipt=root / "artifacts" / "clean-extract.receipt.json",
        build_one_receipt=root / "artifacts" / "build-one.receipt.json",
        build_two_receipt=root / "artifacts" / "build-two.receipt.json",
        source=template.source,
        toolchain=template.toolchain,
    )


@pytest.fixture(scope="module")
def release_fixture_template(
    tmp_path_factory: pytest.TempPathFactory,
) -> ReleaseFixture:
    """Build the compact clean Git fixture once; tests only mutate private copies."""

    return _build_release_fixture(tmp_path_factory.mktemp("release-attestation-base"))


@pytest.fixture
def release_fixture(
    tmp_path: Path,
    release_fixture_template: ReleaseFixture,
) -> ReleaseFixture:
    return _copy_release_fixture(release_fixture_template, tmp_path / "project")


def _build(
    fixture: ReleaseFixture,
    *,
    toolchain: dict[str, str] | None = None,
):
    return build_release_attestation(
        project_root=fixture.root,
        release_id="vdg-rc3-test",
        candidate_zip=fixture.candidate_one,
        reproducible_zip=fixture.candidate_two,
        full_test_receipt=fixture.full_test_receipt,
        clean_extract_receipt=fixture.clean_extract_receipt,
        build_one_receipt=fixture.build_one_receipt,
        build_two_receipt=fixture.build_two_receipt,
        builder_id="local://builder/release-test",
        toolchain=toolchain or fixture.toolchain,
    )


def test_rc3_required_path_policy_matches_submission_policy() -> None:
    assert PRODUCTION_RC3_REQUIRED_PATHS == tuple(
        sorted(DEFAULT_SUBMISSION_REQUIRED_PATHS)
    )


def test_attestation_is_jcs_reproducible_and_explicitly_unsigned(
    release_fixture: ReleaseFixture,
) -> None:
    fixture = release_fixture
    first = _build(fixture)
    second = _build(fixture)
    assert release_attestation_bytes(first) == release_attestation_bytes(second)
    assert first.statement.model_dump(mode="json", by_alias=True)["_type"] == (
        "https://in-toto.io/Statement/v1"
    )
    trust = first.statement.predicate.trust
    assert trust.signature == "NOT_CONFIGURED"
    assert trust.trusted_timestamp == "NOT_CONFIGURED"
    assert trust.external_anchor == "NOT_CONFIGURED"
    assert first.statement.predicate.submission_eligible is False

    output = fixture.root / "artifacts" / "release.attestation.json"
    write_release_attestation(output, first, project_root=fixture.root)
    result = verify_release_attestation(
        project_root=fixture.root,
        attestation_path=output,
    )
    assert result.status == "PASS_LOCAL_INTEGRITY"
    assert result.two_declared_outputs == "BYTE_IDENTICAL"
    assert result.submission_eligible is False
    assert result.official_status == "NOT_EVALUATED"


def test_verifier_rejects_candidate_tampering(
    release_fixture: ReleaseFixture,
) -> None:
    fixture = release_fixture
    output = fixture.root / "artifacts" / "release.attestation.json"
    write_release_attestation(
        output,
        _build(fixture),
        project_root=fixture.root,
    )
    fixture.candidate_one.write_bytes(fixture.candidate_one.read_bytes() + b"tamper")
    with pytest.raises(ReleaseAttestationError, match="candidate ZIP"):
        verify_release_attestation(
            project_root=fixture.root,
            attestation_path=output,
        )


def test_verifier_rejects_missing_bound_material(
    release_fixture: ReleaseFixture,
) -> None:
    fixture = release_fixture
    output = fixture.root / "artifacts" / "release.attestation.json"
    write_release_attestation(
        output,
        _build(fixture),
        project_root=fixture.root,
    )
    fixture.full_test_receipt.unlink()
    with pytest.raises(ReleaseAttestationError, match="full_test_receipt is missing"):
        verify_release_attestation(
            project_root=fixture.root,
            attestation_path=output,
        )


def test_verifier_rejects_dirty_worktree(
    release_fixture: ReleaseFixture,
) -> None:
    fixture = release_fixture
    output = fixture.root / "artifacts" / "release.attestation.json"
    write_release_attestation(
        output,
        _build(fixture),
        project_root=fixture.root,
    )
    (fixture.root / "uv.lock").write_text(
        (fixture.root / "uv.lock").read_text(encoding="utf-8") + "# dirty\n",
        encoding="utf-8",
    )
    with pytest.raises(ReleaseAttestationError, match="worktree is dirty"):
        verify_release_attestation(
            project_root=fixture.root,
            attestation_path=output,
        )


def test_builder_rejects_missing_required_artifact(
    release_fixture: ReleaseFixture,
) -> None:
    fixture = release_fixture
    missing = fixture.root / "artifacts" / "missing.receipt.json"
    with pytest.raises(ReleaseAttestationError, match="required full-test receipt"):
        build_release_attestation(
            project_root=fixture.root,
            release_id="vdg-rc3-test",
            candidate_zip=fixture.candidate_one,
            reproducible_zip=fixture.candidate_two,
            full_test_receipt=missing,
            clean_extract_receipt=fixture.clean_extract_receipt,
            build_one_receipt=fixture.build_one_receipt,
            build_two_receipt=fixture.build_two_receipt,
            builder_id="local://builder/release-test",
            toolchain=fixture.toolchain,
        )


def test_builder_rejects_missing_bound_junit(
    release_fixture: ReleaseFixture,
) -> None:
    fixture = release_fixture
    fixture.junit.unlink()
    with pytest.raises(ReleaseAttestationError, match="JUnit artifact is missing"):
        _build(fixture)


def test_builder_rejects_tampered_bound_junit(
    release_fixture: ReleaseFixture,
) -> None:
    fixture = release_fixture
    fixture.junit.write_text("<testsuites />", encoding="utf-8")
    with pytest.raises(
        ReleaseAttestationError,
        match="JUnit artifact (size|SHA-256) does not match",
    ):
        _build(fixture)


def test_verifier_rejects_junit_tampered_after_attestation(
    release_fixture: ReleaseFixture,
) -> None:
    fixture = release_fixture
    output = fixture.root / "artifacts" / "release.attestation.json"
    write_release_attestation(
        output,
        _build(fixture),
        project_root=fixture.root,
    )
    fixture.junit.write_text("<testsuites />", encoding="utf-8")
    with pytest.raises(
        ReleaseAttestationError,
        match="JUnit artifact (size|SHA-256) does not match",
    ):
        verify_release_attestation(
            project_root=fixture.root,
            attestation_path=output,
        )


def test_builder_rejects_junit_command_binding_drift(
    release_fixture: ReleaseFixture,
) -> None:
    fixture = release_fixture
    receipt = json.loads(fixture.full_test_receipt.read_text(encoding="utf-8"))
    receipt["result"]["command_argv"][-1] = "--junitxml=artifacts/other.xml"
    _write_jcs(fixture.full_test_receipt, receipt)
    with pytest.raises(
        ReleaseAttestationError,
        match="receipt-bound --junitxml path",
    ):
        _build(fixture)


def test_builder_rejects_dirty_worktree(release_fixture: ReleaseFixture) -> None:
    fixture = release_fixture
    (fixture.root / "uv.lock").write_text(
        (fixture.root / "uv.lock").read_text(encoding="utf-8") + "# dirty\n",
        encoding="utf-8",
    )
    with pytest.raises(ReleaseAttestationError, match="worktree is dirty"):
        _build(fixture)


def test_builder_rejects_assume_unchanged_index_mask(
    release_fixture: ReleaseFixture,
) -> None:
    fixture = release_fixture
    _git(fixture.root, "update-index", "--assume-unchanged", "uv.lock")
    (fixture.root / "uv.lock").write_text(
        (fixture.root / "uv.lock").read_text(encoding="utf-8") + "# hidden\n",
        encoding="utf-8",
    )
    assert _git(fixture.root, "status", "--porcelain=v1") == ""
    with pytest.raises(ReleaseAttestationError, match="assume-unchanged"):
        _build(fixture)


def test_git_environment_cannot_redirect_repository(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    release_fixture: ReleaseFixture,
) -> None:
    fixture = release_fixture
    monkeypatch.setenv("GIT_DIR", str(fixture.root / "attacker-controlled.git"))
    monkeypatch.setenv("GIT_WORK_TREE", str(tmp_path / "attacker-worktree"))
    output = fixture.root / "artifacts" / "release.attestation.json"

    write_release_attestation(
        output,
        _build(fixture),
        project_root=fixture.root,
    )
    assert (
        verify_release_attestation(
            project_root=fixture.root,
            attestation_path=output,
        ).status
        == "PASS_LOCAL_INTEGRITY"
    )


def test_builder_rejects_two_build_hash_mismatch(
    release_fixture: ReleaseFixture,
) -> None:
    fixture = release_fixture
    _write_zip(fixture.candidate_two, payload=b"different\n")
    with pytest.raises(ReleaseAttestationError, match="SHA-256 values differ"):
        _build(fixture)


def test_builder_rejects_two_paths_to_same_file(
    release_fixture: ReleaseFixture,
) -> None:
    fixture = release_fixture
    fixture.candidate_two.unlink()
    os.link(fixture.candidate_one, fixture.candidate_two)
    with pytest.raises(ReleaseAttestationError, match="same underlying file"):
        _build(fixture)


def test_verifier_rejects_two_paths_to_same_file(
    release_fixture: ReleaseFixture,
) -> None:
    fixture = release_fixture
    output = fixture.root / "artifacts" / "release.attestation.json"
    write_release_attestation(
        output,
        _build(fixture),
        project_root=fixture.root,
    )
    fixture.candidate_two.unlink()
    os.link(fixture.candidate_one, fixture.candidate_two)
    with pytest.raises(ReleaseAttestationError, match="same underlying file"):
        verify_release_attestation(
            project_root=fixture.root,
            attestation_path=output,
        )


def test_builder_reexecutes_clean_extract_instead_of_trusting_receipt(
    release_fixture: ReleaseFixture,
) -> None:
    fixture = release_fixture
    _write_zip(fixture.candidate_one)
    _write_zip(fixture.candidate_two)
    digest = sha256_file(fixture.candidate_one)
    size = fixture.candidate_one.stat().st_size

    clean = json.loads(fixture.clean_extract_receipt.read_text(encoding="utf-8"))
    clean["candidate"]["digest"]["sha256"] = digest
    clean["candidate"]["size_bytes"] = size
    clean["audit"]["entry_count"] = 1
    clean["audit"]["verified_file_count"] = 1
    _write_jcs(fixture.clean_extract_receipt, clean)
    for receipt_path in (fixture.build_one_receipt, fixture.build_two_receipt):
        receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
        receipt["output"]["digest"]["sha256"] = digest
        receipt["output"]["size_bytes"] = size
        _write_jcs(receipt_path, receipt)

    with pytest.raises(ReleaseAttestationError, match="live package.*audit"):
        _build(fixture)


def test_builder_rejects_reduced_required_path_denominator(
    release_fixture: ReleaseFixture,
) -> None:
    fixture = release_fixture
    receipt = json.loads(fixture.clean_extract_receipt.read_text(encoding="utf-8"))
    receipt["required_paths"] = ["README.md"]
    _write_jcs(fixture.clean_extract_receipt, receipt)

    with pytest.raises(ReleaseAttestationError, match="frozen RC3 submission policy"):
        _build(fixture)


def test_builder_rejects_partial_or_disguised_pytest_command(
    release_fixture: ReleaseFixture,
) -> None:
    fixture = release_fixture
    receipt = json.loads(fixture.full_test_receipt.read_text(encoding="utf-8"))
    receipt["result"]["command_argv"] = [
        "uv",
        "run",
        "--frozen",
        "echo",
        "pytest",
        "tests/test_one.py",
    ]
    _write_jcs(fixture.full_test_receipt, receipt)
    with pytest.raises(ReleaseAttestationError, match="repository-wide pytest"):
        _build(fixture)


def test_builder_rejects_pytest_environment_or_cwd_drift(
    release_fixture: ReleaseFixture,
) -> None:
    fixture = release_fixture
    receipt = json.loads(fixture.full_test_receipt.read_text(encoding="utf-8"))
    receipt["result"]["pytest_addopts"] = "-k smoke"
    _write_jcs(fixture.full_test_receipt, receipt)
    with pytest.raises(ReleaseAttestationError, match="schema validation failed"):
        _build(fixture)


def test_builder_rejects_declared_toolchain_drift(
    release_fixture: ReleaseFixture,
) -> None:
    fixture = release_fixture
    drifted = dict(fixture.toolchain)
    drifted["python"] = "0.0.0"
    with pytest.raises(ReleaseAttestationError, match="python version"):
        _build(fixture, toolchain=drifted)


def test_loader_rejects_windows_trailing_dot_alias(
    release_fixture: ReleaseFixture,
) -> None:
    fixture = release_fixture
    attestation = _build(fixture)
    payload = json.loads(release_attestation_bytes(attestation))
    artifact = payload["statement"]["predicate"]["reproducibility"]["build_two"][
        "artifact"
    ]
    artifact["path"] += "."
    output = fixture.root / "artifacts" / "trailing-dot.attestation.json"
    output.write_bytes(canonical_jcs_bytes(payload))
    with pytest.raises(ReleaseAttestationError, match="portable path contract"):
        load_release_attestation(output)


def test_loader_rejects_nested_two_build_workspaces(
    release_fixture: ReleaseFixture,
) -> None:
    fixture = release_fixture
    payload = json.loads(release_attestation_bytes(_build(fixture)))
    build_two = payload["statement"]["predicate"]["reproducibility"]["build_two"]
    build_two["workspace"] = "artifacts/build-one/nested"
    build_two["artifact"]["path"] = "artifacts/build-one/nested/candidate.zip"
    output = fixture.root / "artifacts" / "nested.attestation.json"
    output.write_bytes(canonical_jcs_bytes(payload))

    with pytest.raises(ReleaseAttestationError, match="non-nested"):
        load_release_attestation(output)


def test_writer_rejects_unignored_in_worktree_output(
    release_fixture: ReleaseFixture,
) -> None:
    fixture = release_fixture
    with pytest.raises(ReleaseAttestationError, match="must be explicitly ignored"):
        write_release_attestation(
            fixture.root / "release.attestation.json",
            _build(fixture),
            project_root=fixture.root,
        )


def test_verifier_rejects_statement_self_digest_tampering(
    release_fixture: ReleaseFixture,
) -> None:
    fixture = release_fixture
    output = fixture.root / "artifacts" / "release.attestation.json"
    write_release_attestation(
        output,
        _build(fixture),
        project_root=fixture.root,
    )
    payload = json.loads(output.read_text(encoding="utf-8"))
    payload["statement"]["predicate"]["builder"]["builder_id"] = (
        "local://builder/tampered"
    )
    output.write_bytes(canonical_jcs_bytes(payload))
    with pytest.raises(ReleaseAttestationError, match="Statement.*digest"):
        verify_release_attestation(
            project_root=fixture.root,
            attestation_path=output,
        )


def test_loader_rejects_noncanonical_or_unknown_statement_members(
    release_fixture: ReleaseFixture,
) -> None:
    fixture = release_fixture
    output = fixture.root / "artifacts" / "release.attestation.json"
    attestation = _build(fixture)
    payload = json.loads(release_attestation_bytes(attestation))
    output.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    with pytest.raises(ReleaseAttestationError, match="not byte-canonical"):
        load_release_attestation(output)

    payload["unexpected"] = True
    output.write_bytes(canonical_jcs_bytes(payload))
    with pytest.raises(ReleaseAttestationError, match="schema validation failed"):
        load_release_attestation(output)


def test_build_and_verify_cli_roundtrip(tmp_path: Path) -> None:
    fixture = _build_release_fixture(
        tmp_path,
        required_paths=PRODUCTION_RC3_REQUIRED_PATHS,
    )
    output = fixture.root / "artifacts" / "release.attestation.json"
    build_command = [
        sys.executable,
        str(PROJECT_ROOT / "tools" / "build_release_attestation.py"),
        "--project-root",
        str(fixture.root),
        "--release-id",
        "vdg-rc3-test",
        "--candidate-zip",
        str(fixture.candidate_one),
        "--second-build-zip",
        str(fixture.candidate_two),
        "--full-test-receipt",
        str(fixture.full_test_receipt),
        "--clean-extract-receipt",
        str(fixture.clean_extract_receipt),
        "--build-one-receipt",
        str(fixture.build_one_receipt),
        "--build-two-receipt",
        str(fixture.build_two_receipt),
        "--builder-id",
        "local://builder/release-test",
        "--output",
        str(output),
    ]
    for name, version in fixture.toolchain.items():
        build_command.extend(["--toolchain", f"{name}={version}"])
    built = subprocess.run(
        build_command,
        check=False,
        capture_output=True,
        text=True,
        encoding="utf-8",
    )
    assert built.returncode == 0, built.stdout + built.stderr
    assert json.loads(built.stdout)["submission_eligible"] is False

    verified = subprocess.run(
        [
            sys.executable,
            str(PROJECT_ROOT / "tools" / "verify_release_attestation.py"),
            "--project-root",
            str(fixture.root),
            "--attestation",
            str(output),
        ],
        check=False,
        capture_output=True,
        text=True,
        encoding="utf-8",
    )
    assert verified.returncode == 0, verified.stdout + verified.stderr
    result = json.loads(verified.stdout)
    assert result["status"] == "PASS_LOCAL_INTEGRITY"
    assert result["signature"] == "NOT_CONFIGURED"
    assert result["official_status"] == "NOT_EVALUATED"
