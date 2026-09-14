import sqlite3
import json
import hashlib
from contextlib import closing
from pathlib import Path

import pytest

from visiondata_gate import product_backup as backup


def product(root):
    root.mkdir()
    with sqlite3.connect(root / "product.sqlite3") as connection:
        connection.execute("CREATE TABLE agent_tasks(execution_status TEXT)")
    (root / "source.bin").write_bytes(b"private local bytes")
    return root


def test_offline_backup_restore_verifies_bytes_without_overwriting(tmp_path):
    source = product(tmp_path / "product")
    snapshot = tmp_path / "snapshot"
    restored = tmp_path / "restored"
    receipt = backup.create_backup(source, snapshot, attest_offline=True)
    assert receipt["file_count"] == 2
    assert receipt["private_data"] is True
    assert str(source) not in str(receipt)
    backup.restore_backup(snapshot, restored)
    assert (restored / "source.bin").read_bytes() == b"private local bytes"
    with pytest.raises(backup.BackupError, match="exists"):
        backup.restore_backup(snapshot, restored)


def test_backup_requires_explicit_offline_confirmation(tmp_path):
    source = product(tmp_path / "product")
    with pytest.raises(backup.BackupError, match="offline"):
        backup.create_backup(source, tmp_path / "snapshot", attest_offline=False)
    assert not (tmp_path / "snapshot").exists()


def test_tampered_or_extra_backup_files_are_rejected(tmp_path):
    source = product(tmp_path / "product")
    snapshot = tmp_path / "snapshot"
    backup.create_backup(source, snapshot, attest_offline=True)
    (snapshot / "source.bin").write_bytes(b"changed")
    with pytest.raises(backup.BackupError, match="integrity"):
        backup.restore_backup(snapshot, tmp_path / "restored")
    assert not (tmp_path / "restored").exists()


def test_running_task_cannot_be_backed_up_as_offline(tmp_path):
    source = product(tmp_path / "product")
    with sqlite3.connect(source / "product.sqlite3") as connection:
        connection.execute("INSERT INTO agent_tasks VALUES ('RUNNING')")
    with pytest.raises(backup.BackupError, match="RUNNING"):
        backup.create_backup(source, tmp_path / "snapshot", attest_offline=True)


def test_source_change_during_copy_prevents_publication(tmp_path, monkeypatch):
    source = product(tmp_path / "product")
    original = backup.shutil.copyfile

    def copying(src, dst):
        result = original(src, dst)
        if Path(src).name == "source.bin":
            Path(src).write_bytes(b"new bytes after copy")
        return result

    monkeypatch.setattr(backup.shutil, "copyfile", copying)
    with pytest.raises(backup.BackupError, match="changed"):
        backup.create_backup(source, tmp_path / "snapshot", attest_offline=True)
    assert not (tmp_path / "snapshot").exists()


def test_backup_cannot_nest_inside_product(tmp_path):
    source = product(tmp_path / "product")
    with pytest.raises(backup.BackupError, match="overlap"):
        backup.create_backup(source, source / "snapshot", attest_offline=True)


def test_backup_rejects_pending_wal_and_extra_members(tmp_path):
    source = product(tmp_path / "product")
    wal = source / "product.sqlite3-wal"
    wal.write_bytes(b"pending-write")
    with pytest.raises(backup.BackupError, match="WAL"):
        backup.create_backup(source, tmp_path / "blocked", attest_offline=True)
    # This file was created by this test, not a live database writer.
    wal.unlink()
    snapshot = tmp_path / "snapshot"
    backup.create_backup(source, snapshot, attest_offline=True)
    (snapshot / "unexpected.bin").write_bytes(b"extra")
    with pytest.raises(backup.BackupError, match="integrity"):
        backup.verify_backup(snapshot)


def test_restore_rejects_resealed_path_escape(tmp_path):
    source = product(tmp_path / "product")
    snapshot = tmp_path / "snapshot"
    backup.create_backup(source, snapshot, attest_offline=True)
    path = snapshot / backup.MANIFEST
    manifest = json.loads(path.read_bytes())
    manifest["files"][0]["path"] = "../outside.sqlite3"
    stable = {key: value for key, value in manifest.items() if key != "receipt_sha256"}
    manifest["receipt_sha256"] = hashlib.sha256(backup._canonical(stable)).hexdigest()
    path.write_bytes(backup._canonical(manifest))
    with pytest.raises(backup.BackupError, match="Unsafe"):
        backup.restore_backup(snapshot, tmp_path / "restored")
    assert not (tmp_path / "restored").exists()


def test_backup_rejects_linked_member(tmp_path):
    source = product(tmp_path / "product")
    link = source / "external.bin"
    target = tmp_path / "external.bin"
    target.write_bytes(b"outside")
    try:
        link.symlink_to(target)
    except OSError:
        pytest.skip("Creating symlinks is unavailable for this Windows user")
    with pytest.raises(backup.BackupError, match="Linked"):
        backup.create_backup(source, tmp_path / "snapshot", attest_offline=True)


def test_staging_change_after_copy_is_not_published_as_verified(tmp_path, monkeypatch):
    source = product(tmp_path / "product")
    check = backup._offline_product

    def check_and_change(root):
        check(root)
        if root.name.startswith(".vdg-backup-"):
            (root / "source.bin").write_bytes(b"changed after copy verification")

    monkeypatch.setattr(backup, "_offline_product", check_and_change)
    with pytest.raises(backup.BackupError, match="integrity"):
        backup.create_backup(source, tmp_path / "snapshot", attest_offline=True)
    assert not (tmp_path / "snapshot").exists()


def test_closed_wal_database_backup_does_not_create_sidecars(tmp_path):
    source = tmp_path / "wal-product"
    source.mkdir()
    with closing(sqlite3.connect(source / "product.sqlite3")) as connection:
        connection.execute("PRAGMA journal_mode=WAL")
        connection.execute("CREATE TABLE agent_tasks(execution_status TEXT)")
        connection.commit()
    before = backup._inventory(source)
    snapshot = tmp_path / "snapshot"
    backup.create_backup(source, snapshot, attest_offline=True)
    assert backup._inventory(source) == before
    backup.verify_backup(snapshot)
    backup.restore_backup(snapshot, tmp_path / "restored")
    assert backup._inventory(tmp_path / "restored") == before
