from __future__ import annotations

import hashlib
import json
import subprocess
import sys
import zipfile
from dataclasses import dataclass
from pathlib import Path
from types import SimpleNamespace

import pytest

import tools.build_submission_upload_bundle as upload_bundle
from visiondata_gate.audit_envelope import canonical_jcs_bytes
from visiondata_gate.release_attestation import GitSourceState


PROJECT_ROOT = Path(__file__).resolve().parents[1]


def _git(root: Path, *arguments: str) -> str:
    result = subprocess.run(
        ["git", "-C", str(root), *arguments],
        check=True,
        capture_output=True,
        text=True,
        encoding="utf-8",
    )
    return result.stdout.strip()


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _binding(root: Path, path: Path) -> SimpleNamespace:
    return SimpleNamespace(
        path=path.relative_to(root).as_posix(),
        size_bytes=path.stat().st_size,
        digest=SimpleNamespace(sha256=_sha256(path)),
    )


def _write_public_source_zip(
    path: Path,
    *,
    root: Path,
    source: GitSourceState,
    schema_version: str = upload_bundle.PUBLIC_MIRROR_SCHEMA,
    extra_files: dict[str, bytes] | None = None,
) -> None:
    tracked = _git(root, "ls-files").splitlines()
    files = {
        relative: (root / relative).read_bytes()
        for relative in tracked
        if upload_bundle.public_export_selected(relative)
    }
    for generated, source_path in upload_bundle.PUBLIC_GENERATED_FILE_SOURCES.items():
        files[generated] = files[source_path]
    files.update(extra_files or {})
    snapshot = hashlib.sha256()
    entries = []
    for relative, data in sorted(files.items()):
        digest = hashlib.sha256(data).hexdigest()
        entry: dict[str, str | int] = {
            "path": relative,
            "sha256": digest,
            "size_bytes": len(data),
        }
        generated_source = upload_bundle.PUBLIC_GENERATED_FILE_SOURCES.get(relative)
        if generated_source is not None:
            entry["source"] = generated_source
        entries.append(entry)
        snapshot.update(relative.encode("utf-8"))
        snapshot.update(b"\0")
        snapshot.update(digest.encode("ascii"))
        snapshot.update(b"\0")
    manifest = {
        "schema_version": schema_version,
        "source_commit_oid": source.commit,
        "source_tree_oid": source.tree,
        "source_worktree_clean": True,
        "source_history_included": False,
        "private_release_evidence_included": False,
        "customer_data_included": False,
        "personal_data_included": False,
        "tracked_source_only": True,
        "file_count": len(entries),
        "snapshot_sha256": snapshot.hexdigest(),
        "files": entries,
    }
    with zipfile.ZipFile(path, mode="w", compression=zipfile.ZIP_DEFLATED) as archive:
        for relative, data in sorted(files.items()):
            source_info = zipfile.ZipInfo(relative)
            source_info.create_system = 3
            source_info.external_attr = 0o100644 << 16
            archive.writestr(source_info, data)
        manifest_info = zipfile.ZipInfo("PUBLIC_MIRROR_MANIFEST.json")
        manifest_info.create_system = 3
        manifest_info.external_attr = 0o100644 << 16
        archive.writestr(
            manifest_info,
            json.dumps(manifest, ensure_ascii=False, indent=2).encode("utf-8"),
        )


@dataclass
class UploadFixture:
    root: Path
    source: GitSourceState
    paths: dict[str, Path]
    attestation: SimpleNamespace
    verification: SimpleNamespace

    def arguments(self, **overrides: Path) -> dict[str, Path]:
        values = {"project_root": self.root, "output": self.root / "bundles/final"}
        values.update(self.paths)
        values.update(overrides)
        return values


def _build_fixture(tmp_path: Path) -> UploadFixture:
    root = tmp_path / "project"
    artifacts = root / "artifacts"
    media = root / "media"
    docs = root / "docs"
    public_src = root / "src"
    templates = root / "tools/templates"
    artifacts.mkdir(parents=True)
    media.mkdir()
    docs.mkdir()
    public_src.mkdir()
    templates.mkdir(parents=True)
    (root / ".gitignore").write_text(
        "artifacts/\nbundles/\n",
        encoding="utf-8",
        newline="\n",
    )
    roadshow_pptx = media / "roadshow.pptx"
    roadshow_pdf = media / "roadshow.pdf"
    demo_video = media / "demo.mp4"
    roadshow_pptx.write_bytes(b"tracked-pptx-fixture")
    roadshow_pdf.write_bytes(b"tracked-pdf-fixture")
    demo_video.write_bytes(b"tracked-mp4-fixture")
    (root / "README.md").write_bytes(b"# Public fixture\n")
    (public_src / "public_demo.py").write_bytes(b"PUBLIC_REPLAY_ONLY = True\n")
    (templates / "public-pages.yml").write_bytes(b"name: Pages\n")
    _git(root, "init")
    _git(root, "config", "user.email", "upload-test@example.invalid")
    _git(root, "config", "user.name", "Upload Bundle Test")
    _git(root, "add", ".gitignore", "README.md", "media", "docs", "src", "tools")
    _git(root, "commit", "-m", "fixture")
    source = upload_bundle.get_clean_git_source_state(root)

    candidate_zip = artifacts / "candidate.zip"
    with zipfile.ZipFile(candidate_zip, mode="w") as archive:
        archive.writestr("README.txt", b"candidate")
    public_source_zip = artifacts / "public-source.zip"
    _write_public_source_zip(public_source_zip, root=root, source=source)
    full_test_junit = artifacts / "full-test.junit.xml"
    full_test_junit.write_bytes(
        b'<testsuites tests="1" failures="0" errors="0" skipped="0" />'
    )
    full_test_receipt = artifacts / "full-test.receipt.json"
    full_test_receipt.write_bytes(
        canonical_jcs_bytes(
            {
                "schema_version": "visiondata-gate.full-test-receipt.v2",
                "status": "PASS",
                "scope": "FULL_REPOSITORY",
                "source": source.model_dump(mode="json"),
                "inputs": {"uv_lock_sha256": "a" * 64, "sbom_sha256": "b" * 64},
                "junit": {
                    "path": "artifacts/full-test.junit.xml",
                    "digest": {"sha256": _sha256(full_test_junit)},
                    "size_bytes": full_test_junit.stat().st_size,
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
                    "pytest_addopts": "",
                    "exit_code": 0,
                    "passed": 1,
                    "failed": 0,
                    "errors": 0,
                    "skipped": 0,
                    "warnings": 0,
                },
                "claim_boundary": (
                    "LOCAL_FULL_REGRESSION_RESULT_NOT_EXTERNAL_CERTIFICATION"
                ),
            }
        )
    )
    clean_extract_receipt = artifacts / "clean-extract.receipt.json"
    build_one_receipt = artifacts / "build-one.receipt.json"
    build_two_receipt = artifacts / "build-two.receipt.json"
    for index, receipt in enumerate(
        (clean_extract_receipt, build_one_receipt, build_two_receipt),
        start=1,
    ):
        receipt.write_bytes(f'{{"fixture":{index}}}'.encode())
    release_attestation = artifacts / "release-attestation.json"
    release_attestation.write_bytes(b'{"fixture":"attestation"}')

    candidate_binding = _binding(root, candidate_zip)
    subject = SimpleNamespace(
        name=candidate_binding.path,
        digest=candidate_binding.digest,
    )
    materials = [
        SimpleNamespace(kind=kind, **vars(_binding(root, path)))
        for kind, path in (
            ("full_test_receipt", full_test_receipt),
            ("clean_extract_receipt", clean_extract_receipt),
            ("build_one_receipt", build_one_receipt),
            ("build_two_receipt", build_two_receipt),
        )
    ]
    statement_digest = SimpleNamespace(value="d" * 64)
    predicate = SimpleNamespace(
        source=source,
        release_id="release-fixture",
        materials=materials,
        reproducibility=SimpleNamespace(
            build_one=SimpleNamespace(artifact=candidate_binding)
        ),
    )
    attestation = SimpleNamespace(
        statement=SimpleNamespace(subject=[subject], predicate=predicate),
        statement_digest=statement_digest,
    )
    verification = SimpleNamespace(
        status="PASS_LOCAL_INTEGRITY",
        subject=subject,
        statement_digest=statement_digest,
    )
    return UploadFixture(
        root=root,
        source=source,
        paths={
            "candidate_zip": candidate_zip,
            "public_source_zip": public_source_zip,
            "roadshow_pptx": roadshow_pptx,
            "roadshow_pdf": roadshow_pdf,
            "demo_video": demo_video,
            "release_attestation": release_attestation,
            "full_test_receipt": full_test_receipt,
            "clean_extract_receipt": clean_extract_receipt,
            "build_one_receipt": build_one_receipt,
            "build_two_receipt": build_two_receipt,
            "full_test_junit": full_test_junit,
        },
        attestation=attestation,
        verification=verification,
    )


def _bind_attestation(
    monkeypatch: pytest.MonkeyPatch,
    fixture: UploadFixture,
) -> None:
    monkeypatch.setattr(
        upload_bundle,
        "verify_release_attestation",
        lambda **_: fixture.verification,
    )
    monkeypatch.setattr(
        upload_bundle,
        "load_release_attestation",
        lambda _: fixture.attestation,
    )


def test_assemble_upload_bundle_is_source_bound_canonical_and_complete(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fixture = _build_fixture(tmp_path)
    _bind_attestation(monkeypatch, fixture)

    result = upload_bundle.assemble_upload_bundle(**fixture.arguments())

    destination = fixture.root / "bundles/final"
    assert result.attachment_count == 11
    assert result.checksums_entry_count == 12
    assert {path.name for path in destination.iterdir()} == {
        path.name for path in fixture.paths.values()
    } | {upload_bundle.MANIFEST_NAME, upload_bundle.CHECKSUMS_NAME}

    manifest_data = (destination / upload_bundle.MANIFEST_NAME).read_bytes()
    manifest = json.loads(manifest_data)
    assert canonical_jcs_bytes(manifest) == manifest_data
    assert manifest["source"] == {
        "commit": fixture.source.commit,
        "tree": fixture.source.tree,
        "dirty": False,
    }
    assert manifest["release"]["submission_eligible"] is False
    assert manifest["release"]["official_status"] == "NOT_EVALUATED"
    assert manifest["privacy_boundary"] == {
        "attachment_privacy_evaluation": "NOT_EVALUATED_BY_THIS_TOOL",
        "bundle_metadata_absolute_paths_included": False,
        "credential_status": "NOT_EVALUATED",
        "personal_identity_status": "NOT_EVALUATED",
    }
    assert str(tmp_path).encode() not in manifest_data

    checksum_lines = (
        (destination / upload_bundle.CHECKSUMS_NAME)
        .read_text(encoding="utf-8")
        .splitlines()
    )
    assert len(checksum_lines) == 12
    for line in checksum_lines:
        digest, filename = line.split("  ", maxsplit=1)
        assert _sha256(destination / filename) == digest


def test_bundle_rejects_stale_attestation_source(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fixture = _build_fixture(tmp_path)
    _bind_attestation(monkeypatch, fixture)
    fixture.attestation.statement.predicate.source = fixture.source.model_copy(
        update={"commit": "f" * len(fixture.source.commit)}
    )

    with pytest.raises(upload_bundle.UploadBundleError) as error:
        upload_bundle.assemble_upload_bundle(**fixture.arguments())

    assert error.value.code == "attestation_source_mismatch"
    assert not (fixture.root / "bundles/final").exists()


def test_bundle_rejects_public_mirror_v1(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fixture = _build_fixture(tmp_path)
    _bind_attestation(monkeypatch, fixture)
    _write_public_source_zip(
        fixture.paths["public_source_zip"],
        root=fixture.root,
        source=fixture.source,
        schema_version="visiondata-gate.public-mirror.v1",
    )

    with pytest.raises(upload_bundle.UploadBundleError) as error:
        upload_bundle.assemble_upload_bundle(**fixture.arguments())

    assert error.value.code == "public_source_boundary_mismatch"


def test_bundle_rejects_self_consistent_public_zip_not_bound_to_git(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fixture = _build_fixture(tmp_path)
    _bind_attestation(monkeypatch, fixture)
    _write_public_source_zip(
        fixture.paths["public_source_zip"],
        root=fixture.root,
        source=fixture.source,
        extra_files={"src/untracked-secret.txt": b"self-consistent-but-untracked"},
    )

    with pytest.raises(upload_bundle.UploadBundleError) as error:
        upload_bundle.assemble_upload_bundle(**fixture.arguments())

    assert error.value.code == "public_source_manifest_mismatch"


@pytest.mark.parametrize(
    ("member_name", "mode", "expected_code"),
    [
        (".GIT/config", 0o100644, "public_source_git_history_rejected"),
        ("nested/.git/config", 0o100644, "public_source_git_history_rejected"),
        ("redirect/", 0o120777, "public_source_entry_rejected"),
        ("named-pipe", 0o010644, "public_source_entry_rejected"),
    ],
)
def test_public_source_zip_rejects_git_and_special_entries(
    tmp_path: Path,
    member_name: str,
    mode: int,
    expected_code: str,
) -> None:
    fixture = _build_fixture(tmp_path)
    archive_path = fixture.paths["public_source_zip"]
    with zipfile.ZipFile(archive_path, mode="w") as archive:
        info = zipfile.ZipInfo(member_name)
        info.create_system = 3
        info.external_attr = mode << 16
        archive.writestr(info, b"malicious-entry")
    item = upload_bundle._resolve_input(
        fixture.root,
        "public_source_zip",
        archive_path,
    )

    with pytest.raises(upload_bundle.UploadBundleError) as error:
        upload_bundle._validate_public_source_zip(
            item,
            fixture.source,
            expected_files=upload_bundle._expected_public_source_files(fixture.root),
        )

    assert error.value.code == expected_code


def test_bundle_rejects_duplicate_attachment_basename(tmp_path: Path) -> None:
    fixture = _build_fixture(tmp_path)
    duplicate = fixture.root / "artifacts/alternate/candidate.zip"
    duplicate.parent.mkdir()
    duplicate.write_bytes(b"different-file")

    with pytest.raises(upload_bundle.UploadBundleError) as error:
        upload_bundle.assemble_upload_bundle(
            **fixture.arguments(public_source_zip=duplicate)
        )

    assert error.value.code == "duplicate_attachment_basename"


@pytest.mark.parametrize(
    ("override", "expected_code"),
    [
        ("suffix", "input_suffix_rejected"),
        ("input_outside", "input_outside_project"),
        ("output_outside", "output_outside_project"),
        ("output_exists", "output_must_not_exist"),
    ],
)
def test_bundle_rejects_unsafe_input_and_output_boundaries(
    tmp_path: Path,
    override: str,
    expected_code: str,
) -> None:
    fixture = _build_fixture(tmp_path)
    arguments = fixture.arguments()
    if override == "suffix":
        rejected = fixture.root / "artifacts/candidate.txt"
        rejected.write_bytes(b"not-a-zip")
        arguments["candidate_zip"] = rejected
    elif override == "input_outside":
        rejected = tmp_path / "outside.zip"
        rejected.write_bytes(b"outside")
        arguments["candidate_zip"] = rejected
    elif override == "output_outside":
        arguments["output"] = tmp_path / "outside/bundle"
    else:
        existing = fixture.root / "bundles/final"
        existing.mkdir(parents=True)

    with pytest.raises(upload_bundle.UploadBundleError) as error:
        upload_bundle.assemble_upload_bundle(**arguments)

    assert error.value.code == expected_code


def test_bundle_rejects_redirecting_input_component(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fixture = _build_fixture(tmp_path)
    redirected = fixture.root / "artifacts/redirected/candidate.zip"
    redirected.parent.mkdir()
    redirected.write_bytes(b"redirected")
    original = upload_bundle._is_redirecting_path

    def fake_redirect(path: Path) -> bool:
        return path.name == "redirected" or original(path)

    monkeypatch.setattr(upload_bundle, "_is_redirecting_path", fake_redirect)
    with pytest.raises(upload_bundle.UploadBundleError) as error:
        upload_bundle.assemble_upload_bundle(
            **fixture.arguments(candidate_zip=redirected)
        )

    assert error.value.code == "input_link_rejected"


def test_cli_failure_is_redacted(tmp_path: Path) -> None:
    fixture = _build_fixture(tmp_path)
    outside = tmp_path / "sensitive-user-name/outside"
    command = [
        sys.executable,
        str(PROJECT_ROOT / "tools/build_submission_upload_bundle.py"),
        "--project-root",
        str(fixture.root),
        "--output",
        str(outside),
    ]
    for option, path in (
        ("--candidate-zip", fixture.paths["candidate_zip"]),
        ("--public-source-zip", fixture.paths["public_source_zip"]),
        ("--pptx", fixture.paths["roadshow_pptx"]),
        ("--pdf", fixture.paths["roadshow_pdf"]),
        ("--video", fixture.paths["demo_video"]),
        ("--attestation", fixture.paths["release_attestation"]),
        ("--full-test-receipt", fixture.paths["full_test_receipt"]),
        ("--clean-extract-receipt", fixture.paths["clean_extract_receipt"]),
        ("--build-one-receipt", fixture.paths["build_one_receipt"]),
        ("--build-two-receipt", fixture.paths["build_two_receipt"]),
        ("--full-test-junit", fixture.paths["full_test_junit"]),
    ):
        command.extend((option, str(path)))

    result = subprocess.run(command, check=False, capture_output=True)

    assert result.returncode == 2
    payload = json.loads(result.stdout)
    assert payload == {
        "official_status": "NOT_EVALUATED",
        "ok": False,
        "reason_code": "output_outside_project",
        "status": "HOLD_UPLOAD_BUNDLE",
        "submission_eligible": False,
        "values_disclosed": False,
    }
    assert str(tmp_path).encode() not in result.stdout
    assert result.stderr == b""

    secret_argument = str(tmp_path / "private-user/api-key-secret")
    parse_failure = subprocess.run(
        [
            sys.executable,
            str(PROJECT_ROOT / "tools/build_submission_upload_bundle.py"),
            "--unknown-sensitive-option",
            secret_argument,
        ],
        check=False,
        capture_output=True,
    )
    assert parse_failure.returncode == 2
    parse_payload = json.loads(parse_failure.stdout)
    assert parse_payload["reason_code"] == "cli_arguments_invalid"
    assert secret_argument.encode() not in parse_failure.stdout
    assert parse_failure.stderr == b""
