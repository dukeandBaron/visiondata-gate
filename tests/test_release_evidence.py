from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest

import visiondata_gate.release_attestation as release_attestation_module
import visiondata_gate.release_evidence as release_evidence_module
from visiondata_gate.evidence import sha256_file
from visiondata_gate.package import build_deterministic_zip
from visiondata_gate.release_evidence import (
    ReleaseEvidenceError,
    build_rc3_candidate,
    build_rc3_release_evidence,
    parse_pytest_junit,
    run_full_regression,
)


COMPACT_REQUIRED_PATHS = ("NOTICE", "README.md")


def _git(root: Path, *arguments: str) -> str:
    completed = subprocess.run(
        ["git", "-C", str(root), *arguments],
        check=True,
        capture_output=True,
        text=True,
        encoding="utf-8",
    )
    return completed.stdout.strip()


def _write_junit(path: Path, *, failures: int = 0, errors: int = 0) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        '<?xml version="1.0" encoding="utf-8"?>'
        '<testsuites name="pytest">'
        f'<testsuite name="pytest" tests="4" failures="{failures}" '
        f'errors="{errors}" skipped="1" />'
        "</testsuites>",
        encoding="utf-8",
        newline="",
    )


def _build_clean_project(tmp_path: Path) -> Path:
    root = tmp_path / "project"
    (root / "docs").mkdir(parents=True)
    (root / "tools").mkdir()
    (root / ".gitignore").write_text("deliverables/\n", encoding="utf-8")
    (root / "README.md").write_text("# release fixture\n", encoding="utf-8")
    (root / "NOTICE").write_text("release fixture\n", encoding="utf-8")
    (root / "uv.lock").write_text(
        'version = 1\nrevision = 3\n\n[[package]]\nname = "demo"\nversion = "1"\n',
        encoding="utf-8",
    )
    uv_lock_sha256 = sha256_file(root / "uv.lock")
    (root / "docs" / "SBOM.cdx.json").write_text(
        json.dumps(
            {
                "bomFormat": "CycloneDX",
                "components": [{"name": "demo", "type": "application", "version": "1"}],
                "metadata": {
                    "component": {
                        "name": "demo",
                        "properties": [
                            {
                                "name": "visiondata-gate:ecosystem",
                                "value": "python",
                            }
                        ],
                        "type": "application",
                        "version": "1",
                    },
                    "properties": [
                        {
                            "name": "visiondata-gate:lock-sha256:uv.lock",
                            "value": uv_lock_sha256,
                        }
                    ],
                },
                "specVersion": "1.6",
                "version": 1,
            },
            separators=(",", ":"),
            sort_keys=True,
        ),
        encoding="utf-8",
    )
    (root / "tools" / "build_rc3_candidate.py").write_text(
        '"""Tracked test build entrypoint."""\n',
        encoding="utf-8",
    )
    _git(root, "init")
    _git(root, "config", "user.email", "release-test@example.invalid")
    _git(root, "config", "user.name", "Release Test")
    _git(root, "add", ".")
    _git(root, "commit", "-m", "fixture")
    assert _git(root, "status", "--porcelain=v1") == ""
    return root


def test_parse_pytest_junit_aggregates_counts(tmp_path: Path) -> None:
    junit = tmp_path / "pytest.xml"
    _write_junit(junit)
    assert parse_pytest_junit(junit) == {
        "passed": 3,
        "failed": 0,
        "errors": 0,
        "skipped": 1,
    }


def test_parse_pytest_junit_rejects_inconsistent_counts(tmp_path: Path) -> None:
    junit = tmp_path / "pytest.xml"
    junit.write_text(
        '<testsuites><testsuite tests="1" failures="2" /></testsuites>',
        encoding="utf-8",
    )
    with pytest.raises(ReleaseEvidenceError, match="counts are inconsistent"):
        parse_pytest_junit(junit)


def test_run_full_regression_binds_exact_junit(
    tmp_path: Path,
) -> None:
    root = _build_clean_project(tmp_path)

    def fake_runner(
        command: list[str], **kwargs: object
    ) -> subprocess.CompletedProcess[str]:
        junit_argument = command[-1]
        assert junit_argument.startswith("--junitxml=")
        _write_junit(root / junit_argument.partition("=")[2])
        return subprocess.CompletedProcess(command, 0, "3 passed, 1 skipped\n", "")

    receipt = run_full_regression(
        project_root=root,
        junit_path="deliverables/rc3/full-test.junit.xml",
        runner=fake_runner,
    )
    junit = root / receipt.junit.path
    assert receipt.schema_version == "visiondata-gate.full-test-receipt.v2"
    assert receipt.result.passed == 3
    assert receipt.result.command_argv[-1] == (
        "--junitxml=deliverables/rc3/full-test.junit.xml"
    )
    assert receipt.junit.digest.sha256 == sha256_file(junit)


def test_run_full_regression_does_not_emit_pass_for_failure(
    tmp_path: Path,
) -> None:
    root = _build_clean_project(tmp_path)

    def fake_runner(
        command: list[str], **kwargs: object
    ) -> subprocess.CompletedProcess[str]:
        _write_junit(root / command[-1].partition("=")[2], failures=1)
        return subprocess.CompletedProcess(command, 1, "1 failed\n", "")

    with pytest.raises(ReleaseEvidenceError, match="did not pass"):
        run_full_regression(
            project_root=root,
            junit_path="deliverables/rc3/full-test.junit.xml",
            runner=fake_runner,
        )


def test_build_rc3_candidate_uses_clean_git_snapshot(tmp_path: Path) -> None:
    root = _build_clean_project(tmp_path)
    result = build_rc3_candidate(
        project_root=root,
        workspace="deliverables/rc3/build-one",
        output="deliverables/rc3/build-one/candidate.zip",
        required_paths=COMPACT_REQUIRED_PATHS,
    )
    assert result["status"] == "PASS_LOCAL_CANDIDATE"
    assert result["audit"]["ok"] is True
    assert result["submission_eligible"] is False
    with pytest.raises(ReleaseEvidenceError, match="reuse build workspace"):
        build_rc3_candidate(
            project_root=root,
            workspace="deliverables/rc3/build-one",
            output="deliverables/rc3/build-one/candidate.zip",
            required_paths=COMPACT_REQUIRED_PATHS,
        )


def test_release_pipeline_binds_full_test_dual_build_and_attestation(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    root = _build_clean_project(tmp_path)
    monkeypatch.setattr(
        release_attestation_module,
        "RC3_REQUIRED_PATHS",
        COMPACT_REQUIRED_PATHS,
    )
    monkeypatch.setattr(
        release_evidence_module,
        "RC3_REQUIRED_PATHS",
        COMPACT_REQUIRED_PATHS,
    )

    def fake_full_test(
        command: list[str],
        **kwargs: object,
    ) -> subprocess.CompletedProcess[str]:
        _write_junit(root / command[-1].partition("=")[2])
        return subprocess.CompletedProcess(
            command,
            0,
            "3 passed, 1 skipped, 2 warnings\n",
            "",
        )

    def fake_candidate(
        command: list[str],
        **kwargs: object,
    ) -> subprocess.CompletedProcess[str]:
        workspace = command[command.index("--workspace") + 1]
        output = command[command.index("--output") + 1]
        (root / workspace).mkdir(parents=True)
        build_deterministic_zip(root, root / output)
        return subprocess.CompletedProcess(command, 0, "{}", "")

    result = build_rc3_release_evidence(
        project_root=root,
        release_id="vdg-rc3-test",
        output_root="deliverables/rc3-test",
        full_test_runner=fake_full_test,
        candidate_runner=fake_candidate,
        required_paths=COMPACT_REQUIRED_PATHS,
    )
    assert result["status"] == "PASS_LOCAL_RC3_RELEASE_CANDIDATE"
    assert result["two_builds_byte_identical"] is True
    assert result["submission_eligible"] is False
    assert result["full_test"]["warnings"] == 2
    assert result["attestation"]["verification_status"] == "PASS_LOCAL_INTEGRITY"


def test_release_pipeline_fails_before_output_on_dirty_tree(tmp_path: Path) -> None:
    root = _build_clean_project(tmp_path)
    (root / "README.md").write_text("dirty\n", encoding="utf-8")
    namespace = root / "deliverables" / "should-not-exist"
    with pytest.raises(ReleaseEvidenceError, match="worktree is dirty"):
        build_rc3_release_evidence(
            project_root=root,
            release_id="vdg-rc3-test",
            output_root="deliverables/should-not-exist",
            required_paths=COMPACT_REQUIRED_PATHS,
        )
    assert not namespace.exists()
