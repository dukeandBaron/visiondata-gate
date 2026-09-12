"""Offline snapshots must not silently preserve active learning lifecycle state."""

import json
import hashlib
import sqlite3

import pytest

from tests.test_product_backup import product
from visiondata_gate import product_backup as backup


def _learning_record(root, kind, status):
    with sqlite3.connect(root / "product.sqlite3") as connection:
        connection.execute(
            "CREATE TABLE learning_records (id TEXT PRIMARY KEY, kind TEXT, "
            "cycle_id TEXT, project_id TEXT, record_json TEXT)"
        )
        connection.execute(
            "INSERT INTO learning_records VALUES (?,?,?,?,?)",
            (
                "fixture-id",
                kind,
                "fixture-cycle",
                "fixture-project",
                json.dumps({"status": status}),
            ),
        )


@pytest.mark.parametrize(
    "kind,status", [("cycle", "RUNNING"), ("cycle", "FINALIZING"), ("run", "RUNNING")]
)
def test_offline_backup_rejects_learning_work_even_without_active_agent_tasks(
    tmp_path, kind, status
):
    source = product(tmp_path / "product")
    _learning_record(source, kind, status)
    destination = tmp_path / "snapshot"
    with pytest.raises(backup.BackupError, match="learning"):
        backup.create_backup(source, destination, attest_offline=True)
    assert not destination.exists()


@pytest.mark.parametrize("kind,status", [("cycle", "FINALIZED"), ("run", "FAILED")])
def test_offline_backup_allows_completed_or_explicitly_failed_learning(
    tmp_path, kind, status
):
    source = product(tmp_path / "product")
    _learning_record(source, kind, status)
    destination = tmp_path / "snapshot"
    receipt = backup.create_backup(source, destination, attest_offline=True)
    assert receipt["consistency"] == "OFFLINE_BYTES_VERIFIED"
    assert backup.verify_backup(destination) == receipt


@pytest.mark.parametrize("action", ["verify", "restore"])
def test_legacy_byte_valid_snapshot_with_active_learning_is_not_accepted(
    tmp_path, action
):
    source = product(tmp_path / "product")
    _learning_record(source, "cycle", "FINALIZED")
    snapshot = tmp_path / "snapshot"
    receipt = backup.create_backup(source, snapshot, attest_offline=True)
    # This is an entirely test-owned snapshot, modeling an older byte-valid export.
    with sqlite3.connect(snapshot / "product.sqlite3") as connection:
        connection.execute(
            "UPDATE learning_records SET record_json=?",
            (json.dumps({"status": "FINALIZING"}),),
        )
    for record in receipt["files"]:
        path = snapshot / record["path"]
        record.update(sha256=backup._digest(path), size=path.stat().st_size)
    stable = {key: value for key, value in receipt.items() if key != "receipt_sha256"}
    receipt["receipt_sha256"] = hashlib.sha256(backup._canonical(stable)).hexdigest()
    (snapshot / backup.MANIFEST).write_bytes(backup._canonical(receipt))
    with pytest.raises(backup.BackupError, match="learning"):
        if action == "verify":
            backup.verify_backup(snapshot)
        else:
            backup.restore_backup(snapshot, tmp_path / "restored")
    assert not (tmp_path / "restored").exists()
