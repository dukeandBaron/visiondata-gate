"""Exercise real Git snapshots and malicious/tampered technical bundles."""

from __future__ import annotations

import hashlib
import importlib.util
import json
import os
from pathlib import Path
import stat
import subprocess
import zipfile

import pytest


TOOL_PATH = Path(__file__).resolve().parents[1] / "tools/build_finals_technical_bundle.py"


@pytest.fixture
def tool():
    assert TOOL_PATH.is_file(), "The technical bundle builder must exist"
    spec = importlib.util.spec_from_file_location("finals_technical_bundle", TOOL_PATH)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def git(root, *args):
    return subprocess.check_output(
        ["git", "-C", str(root), *args], stderr=subprocess.PIPE
    ).decode("utf-8").strip()


@pytest.fixture
def repository(tmp_path):
    root = tmp_path / "repo"
    root.mkdir()
    git(root, "init", "--quiet")
    git(root, "config", "user.email", "fixture@example.invalid")
    git(root, "config", "user.name", "Synthetic Fixture")
    git(root, "config", "core.autocrlf", "false")
    files = {
        "README.md": "# Synthetic source\n[guide](docs/guide.md)\n",
        "LICENSE": "Synthetic test license\n",
        "pyproject.toml": "[project]\nname = 'synthetic-fixture'\nversion = '0.1'\n",
        "uv.lock": "version = 1\n",
        "docs/guide.md": "# Guide\n[home](../README.md)\n",
        "src/example.py": "VALUE = 1\n",
        "tools/check.py": "print('synthetic')\n",
    }
    for name, text in files.items():
        path = root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8", newline="\n")
    git(root, "add", ".")
    git(root, "commit", "--quiet", "-m", "synthetic fixture")
    return root


def build(tool, repository, tmp_path, **kwargs):
    target = tmp_path / "technical.zip"
    result = tool.build_bundle(repository, target, **kwargs)
    return target, result


def rewrite_zip(source, target, mutate):
    with zipfile.ZipFile(source) as archive:
        rows = [(entry.filename, archive.read(entry)) for entry in archive.infolist()]
    with zipfile.ZipFile(target, "w") as archive:
        for name, data in mutate(rows):
            entry = zipfile.ZipInfo(name)
            # Constructor normalizes backslashes on Windows; retain hostile input.
            entry.filename = name
            archive.writestr(entry, data)


def test_frozen_source_is_repeatable_and_is_not_a_submission_claim(tool, repository, tmp_path):
    first, result = build(tool, repository, tmp_path)
    second = tmp_path / "same-input.zip"
    tool.build_bundle(repository, second)
    assert first.read_bytes() == second.read_bytes()
    assert result["integrity_status"] == "INTEGRITY_VERIFIED"
    assert result["capability_validation"] == "NOT_RUN_BY_BUNDLER"
    with zipfile.ZipFile(first) as archive:
        identity = json.loads(archive.read("SOURCE_IDENTITY.json"))
        assert identity["source_commit"] == git(repository, "rev-parse", "HEAD")
        assert identity["source_state"] == "CLEAN_COMMIT"
        assert "source/docs/guide.md" in archive.namelist()
        assert archive.read("source/src/example.py") == b"VALUE = 1\n"
        assert not any(".git/" in name for name in archive.namelist())
    assert tool.verify_bundle(first)["source_state"] == "CLEAN_COMMIT"


def test_untracked_data_and_forbidden_tracked_files_never_enter_bundle(tool, repository, tmp_path):
    (repository / "customer-photo.png").write_bytes(b"private not tracked")
    private_dir = repository / "output"
    private_dir.mkdir()
    (private_dir / "private.sqlite").write_bytes(b"SQLite format 3\x00private")
    git(repository, "add", "output/private.sqlite")
    git(repository, "commit", "--quiet", "-m", "forbidden fixture")
    path, _ = build(tool, repository, tmp_path)
    with zipfile.ZipFile(path) as archive:
        assert not any("private.sqlite" in n or "customer-photo" in n for n in archive.namelist())


def test_dirty_source_is_refused_unless_explicitly_labelled(tool, repository, tmp_path):
    (repository / "src/example.py").write_text("VALUE = 2\n", encoding="utf-8")
    with pytest.raises(tool.BundleError, match="dirty"):
        build(tool, repository, tmp_path)
    path, result = build(tool, repository, tmp_path, allow_dirty=True)
    assert result["source_state"] == "PATCHED_WORKTREE"
    with zipfile.ZipFile(path) as archive:
        assert archive.read("source/src/example.py") == (repository / "src/example.py").read_bytes()
        assert json.loads(archive.read("SOURCE_IDENTITY.json"))["source_state"] == "PATCHED_WORKTREE"


def test_allow_dirty_includes_staged_new_files_and_omits_deleted_files(tool, repository, tmp_path):
    (repository / "src/new.py").write_text("NEW = True\n", encoding="utf-8")
    git(repository, "add", "src/new.py")
    (repository / "src/example.py").unlink()
    path, _ = build(tool, repository, tmp_path, allow_dirty=True)
    with zipfile.ZipFile(path) as archive:
        assert "source/src/new.py" in archive.namelist()
        assert "source/src/example.py" not in archive.namelist()


def test_output_is_never_overwritten(tool, repository, tmp_path):
    path, _ = build(tool, repository, tmp_path)
    before = path.read_bytes()
    with pytest.raises(tool.BundleError, match="exists"):
        tool.build_bundle(repository, path)
    assert path.read_bytes() == before


def test_public_evidence_requires_review_and_records_no_local_path(tool, repository, tmp_path):
    evidence = tmp_path / "synthetic-receipt.json"
    evidence.write_text('{"source_mode":"SYNTHETIC","status":"HOLD"}', encoding="utf-8")
    files = [("demo-receipt.json", evidence)]
    with pytest.raises(tool.BundleError, match="review"):
        build(tool, repository, tmp_path, evidence=files)
    path, _ = build(tool, repository, tmp_path, evidence=files, public_evidence_reviewed=True)
    with zipfile.ZipFile(path) as archive:
        assert archive.read("evidence/demo-receipt.json") == evidence.read_bytes()
        identity = archive.read("SOURCE_IDENTITY.json").decode("utf-8")
        assert str(tmp_path) not in identity
        assert "PUBLIC_SYNTHETIC_REVIEW_DECLARED" in identity


@pytest.mark.parametrize("name,content", [
    ("private.sqlite", b"SQLite format 3\x00data"),
    ("private.json", b"SQLite format 3\x00data"),
    ("photo.png", b"image bytes"),
    # Construct synthetic privacy markers at runtime; no real private content in Git.
    ("receipt.json", b'{"path":"C:/' + b'Users/alice/private/data"}'),
    ("receipt.md", b"-----BEGIN " + b"PRIVATE KEY-----"),
    ("receipt.json", b'{"broken":'),
    ("receipt.json", b'{"status":"PASS","status":"FAIL"}'),
])
def test_private_or_invalid_evidence_is_rejected(tool, repository, tmp_path, name, content):
    evidence = tmp_path / name
    evidence.write_bytes(content)
    with pytest.raises(tool.BundleError):
        build(tool, repository, tmp_path, evidence=[(name, evidence)], public_evidence_reviewed=True)
    assert not (tmp_path / "technical.zip").exists()


@pytest.mark.parametrize("mutation", ["modify", "remove", "extra"])
def test_zip_member_tampering_is_detected(tool, repository, tmp_path, mutation):
    path, _ = build(tool, repository, tmp_path)
    target = tmp_path / f"{mutation}.zip"

    def mutate(rows):
        if mutation == "modify":
            return [(n, b"VALUE = 9\n" if n == "source/src/example.py" else d) for n, d in rows]
        if mutation == "remove":
            return [(n, d) for n, d in rows if n != "source/src/example.py"]
        return [*rows, ("source/extra.py", b"unbound")]

    rewrite_zip(path, target, mutate)
    with pytest.raises(tool.BundleError):
        tool.verify_bundle(target)


@pytest.mark.parametrize("name", ["../escape", "/absolute", "C:/drive", "source\\backslash", "source/x:stream", "source/CON.txt", "source/x. "])
def test_unsafe_member_names_are_rejected(tool, repository, tmp_path, name):
    path, _ = build(tool, repository, tmp_path)
    target = tmp_path / "unsafe.zip"
    rewrite_zip(path, target, lambda rows: [*rows, (name, b"bad")])
    with pytest.raises(tool.BundleError, match="path"):
        tool.verify_bundle(target)


def test_case_collisions_and_duplicate_members_are_rejected(tool, repository, tmp_path):
    path, _ = build(tool, repository, tmp_path)
    target = tmp_path / "case.zip"
    rewrite_zip(path, target, lambda rows: [*rows, ("SOURCE/README.md", b"other")])
    with pytest.raises(tool.BundleError, match="collision"):
        tool.verify_bundle(target)
    duplicate = tmp_path / "duplicate.zip"
    with pytest.warns(UserWarning, match="Duplicate"):
        rewrite_zip(path, duplicate, lambda rows: [*rows, rows[0]])
    with pytest.raises(tool.BundleError, match="collision"):
        tool.verify_bundle(duplicate)


def test_zip_symlink_is_rejected(tool, repository, tmp_path):
    path, _ = build(tool, repository, tmp_path)
    target = tmp_path / "symlink.zip"
    rewrite_zip(path, target, lambda rows: rows)
    with zipfile.ZipFile(target, "a") as archive:
        entry = zipfile.ZipInfo("source/link")
        entry.create_system = 3
        entry.external_attr = (stat.S_IFLNK | 0o777) << 16
        archive.writestr(entry, "../../private")
    with pytest.raises(tool.BundleError, match="symlink"):
        tool.verify_bundle(target)


def test_git_symlink_mode_is_rejected_even_on_windows(tool, repository, tmp_path):
    blob = git(repository, "rev-parse", "HEAD:README.md")
    git(repository, "update-index", "--add", "--cacheinfo", f"120000,{blob},docs/link")
    git(repository, "commit", "--quiet", "-m", "symlink fixture")
    with pytest.raises(tool.BundleError, match="symlink"):
        build(tool, repository, tmp_path, allow_dirty=True)


def test_unpacked_directory_is_verified_and_extra_files_are_rejected(tool, repository, tmp_path):
    path, _ = build(tool, repository, tmp_path)
    directory = tmp_path / "extracted"
    with zipfile.ZipFile(path) as archive:
        archive.extractall(directory)
    assert tool.verify_bundle(directory)["integrity_status"] == "INTEGRITY_VERIFIED"
    (directory / "extra.json").write_text("{}", encoding="utf-8")
    with pytest.raises(tool.BundleError, match="members"):
        tool.verify_bundle(directory)


def test_directory_symlink_is_rejected(tool, repository, tmp_path):
    path, _ = build(tool, repository, tmp_path)
    directory = tmp_path / "extracted"
    with zipfile.ZipFile(path) as archive:
        archive.extractall(directory)
    try:
        os.symlink(tmp_path, directory / "link", target_is_directory=True)
    except OSError:
        pytest.skip("This account cannot create symlinks")
    with pytest.raises(tool.BundleError, match="symlink|reparse"):
        tool.verify_bundle(directory)


def test_manifest_summary_tampering_is_rejected(tool, repository, tmp_path):
    path, _ = build(tool, repository, tmp_path)
    target = tmp_path / "bad-manifest.zip"

    def mutate(rows):
        changed = []
        for name, data in rows:
            if name == "BUNDLE_MANIFEST.json":
                obj = json.loads(data)
                obj["payload_sha256"] = "0" * 64
                data = json.dumps(obj).encode("utf-8")
            changed.append((name, data))
        return changed

    rewrite_zip(path, target, mutate)
    with pytest.raises(tool.BundleError, match="digest"):
        tool.verify_bundle(target)


def test_expected_archive_digest_is_checked(tool, repository, tmp_path):
    path, _ = build(tool, repository, tmp_path)
    digest = hashlib.sha256(path.read_bytes()).hexdigest()
    assert tool.verify_bundle(path, expected_sha256=digest)["zip_sha256"] == digest
    with pytest.raises(tool.BundleError, match="digest"):
        tool.verify_bundle(path, expected_sha256="0" * 64)


def test_git_uses_external_absolute_executable_not_repository_or_cwd(tool, repository, monkeypatch):
    calls = []
    monkeypatch.chdir(repository)
    monkeypatch.setenv("PATH", str(repository) + os.pathsep + "." + os.pathsep + os.environ["PATH"])
    (repository / ("git.exe" if os.name == "nt" else "git")).write_bytes(b"not a trusted tool")
    monkeypatch.setattr(tool.subprocess, "check_output", lambda command, **kwargs: calls.append((command, kwargs)) or b"ok")
    assert tool.git(repository, "rev-parse", "HEAD") == b"ok"
    executable = Path(calls[0][0][0])
    assert executable.is_absolute()
    assert not executable.is_relative_to(repository)
    assert calls[0][1]["shell"] is False
    assert calls[0][1]["timeout"] == 60


def test_git_refuses_only_repository_and_relative_search_paths(tool, repository, monkeypatch):
    monkeypatch.chdir(repository)
    monkeypatch.setenv("PATH", str(repository) + os.pathsep + ".")
    (repository / ("git.exe" if os.name == "nt" else "git")).write_bytes(b"untrusted")
    monkeypatch.setattr(tool.subprocess, "check_output", lambda *args, **kwargs: pytest.fail("Must not launch repository executable"))
    with pytest.raises(tool.BundleError, match="Git"):
        tool.git(repository, "rev-parse", "HEAD")
