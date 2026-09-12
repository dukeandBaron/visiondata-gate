"""Explicit offline product copies with full-byte verification and absent targets.

Snapshots contain private user data. This is not a submission/public export or
a transactional online backup. Stop writers and explicitly attest offline use.
"""

from __future__ import annotations

import argparse
from contextlib import closing
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import re
import shutil
import sqlite3
import tempfile


MANIFEST = ".vdg-backup.json"


class BackupError(RuntimeError):
    pass


def _digest(path: Path) -> str:
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def _canonical(value: object) -> bytes:
    return json.dumps(
        value, sort_keys=True, separators=(",", ":"), ensure_ascii=True
    ).encode()


def _linked(path: Path) -> bool:
    return path.is_symlink() or path.is_junction()


def _root(path: Path) -> Path:
    if _linked(path) or not path.is_dir():
        raise BackupError("Source must be an existing regular directory.")
    return path.resolve(strict=True)


def _target(source: Path, target: Path) -> Path:
    if target.exists() or target.is_symlink():
        raise BackupError("Destination already exists; nothing was overwritten.")
    target = target.resolve(strict=False)
    if target == source or source in target.parents or target in source.parents:
        raise BackupError("Source and destination overlap.")
    target.parent.mkdir(parents=True, exist_ok=True)
    return target


def _inventory(root: Path, *, snapshot: bool = False) -> list[dict]:
    records = []
    for path in sorted(root.rglob("*")):
        if _linked(path):
            raise BackupError("Linked files/directories are not allowed in a backup.")
        if path.is_dir():
            continue
        if not path.is_file():
            raise BackupError("Backup input contains a non-regular file.")
        relative = path.relative_to(root).as_posix()
        if relative == MANIFEST:
            if snapshot:
                continue
            raise BackupError("Product input contains a reserved backup manifest.")
        if path.name.endswith(("-wal", "-journal")) and path.stat().st_size:
            raise BackupError(
                "Database has pending WAL/journal data; stop writers before offline backup."
            )
        records.append(
            {"path": relative, "sha256": _digest(path), "size": path.stat().st_size}
        )
        if len(records) > 100_000:
            raise BackupError("Backup exceeds the supported file-count limit.")
    return records


def _offline_product(root: Path) -> None:
    db = root / "product.sqlite3"
    if not db.is_file():
        raise BackupError(
            "Product database is missing; an empty workspace was not created."
        )
    try:
        for path in root.glob("*.sqlite3"):
            if _linked(path):
                raise BackupError("Linked database files are not allowed.")
            for suffix in ("-wal", "-journal"):
                journal = path.with_name(path.name + suffix)
                if journal.is_file() and journal.stat().st_size:
                    raise BackupError(
                        "Database has pending WAL/journal data; stop writers before offline backup."
                    )
            with closing(
                sqlite3.connect(path.as_uri() + "?mode=ro&immutable=1", uri=True)
            ) as connection:
                if connection.execute("PRAGMA quick_check").fetchall() != [("ok",)]:
                    raise BackupError("Database integrity check failed.")
                if path == db:
                    active = connection.execute(
                        "SELECT COUNT(*) FROM agent_tasks WHERE execution_status IN ('RUNNING','VERIFYING')"
                    ).fetchone()[0]
                    if active:
                        raise BackupError(
                            "RUNNING/VERIFYING tasks remain; resolve execution before backup."
                        )
                    learning_table = connection.execute(
                        "SELECT 1 FROM sqlite_master WHERE type='table' AND name='learning_records'"
                    ).fetchone()
                    if learning_table:
                        for row in connection.execute(
                            "SELECT record_json FROM learning_records WHERE kind IN ('cycle','run')"
                        ):
                            try:
                                record = json.loads(row[0])
                                if not isinstance(record, dict) or not isinstance(
                                    record.get("status"), str
                                ):
                                    raise ValueError("missing lifecycle state")
                            except (ValueError, TypeError) as error:
                                raise BackupError(
                                    "The learning lifecycle state cannot be verified."
                                ) from error
                            if record["status"] in {"RUNNING", "FINALIZING"}:
                                raise BackupError(
                                    "RUNNING/FINALIZING learning work remains; resolve execution before backup."
                                )
    except sqlite3.Error as error:
        raise BackupError("Product database cannot be verified.") from error


def _remove_staging(path: Path, parent: Path) -> None:
    # Only our freshly-created, resolved staging directory can be removed.
    resolved = path.resolve(strict=True)
    if resolved.parent != parent.resolve(strict=True) or not resolved.name.startswith(
        ".vdg-backup-"
    ):
        raise BackupError("Staging cleanup scope validation failed.")
    shutil.rmtree(resolved)


def _copy(records: list[dict], source: Path, target: Path) -> None:
    for record in records:
        relative = PurePosixPath(record["path"])
        member = source.joinpath(*relative.parts)
        destination = target.joinpath(*relative.parts)
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(member, destination)
        if _digest(destination) != record["sha256"]:
            raise BackupError("Copied file integrity check failed.")


def create_backup(source: Path, destination: Path, *, attest_offline: bool) -> dict:
    if not attest_offline:
        raise BackupError("Explicit offline confirmation is required.")
    source = _root(source)
    destination = _target(source, destination)
    _offline_product(source)
    before = _inventory(source)
    staging = Path(
        tempfile.mkdtemp(prefix=".vdg-backup-", dir=destination.parent)
    ).resolve()
    try:
        _copy(before, source, staging)
        _offline_product(staging)
        if _inventory(staging) != before:
            raise BackupError("Staging integrity changed before backup publication.")
        if _inventory(source) != before:
            raise BackupError("Source changed while copying; backup was not published.")
        stable = {
            "schema_version": "visiondata-gate.offline-product-backup.v1",
            "private_data": True,
            "operator_attests_offline": True,
            "consistency": "OFFLINE_BYTES_VERIFIED",
            "file_count": len(before),
            "files": before,
        }
        receipt = {
            **stable,
            "receipt_sha256": hashlib.sha256(_canonical(stable)).hexdigest(),
        }
        (staging / MANIFEST).write_bytes(_canonical(receipt))
        if destination.exists():
            raise BackupError("Destination already exists; backup was not published.")
        os.rename(staging, destination)
        return receipt
    except BaseException:
        if staging.exists():
            _remove_staging(staging, destination.parent)
        raise


def _unique_json(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise BackupError("Duplicate backup manifest member.")
        result[key] = value
    return result


def verify_backup(snapshot: Path) -> dict:
    root = _root(snapshot)
    manifest = root / MANIFEST
    if (
        _linked(manifest)
        or not manifest.is_file()
        or manifest.stat().st_size > 32_000_000
    ):
        raise BackupError("Backup manifest is missing or unsupported.")
    try:
        record = json.loads(manifest.read_bytes(), object_pairs_hook=_unique_json)
        digest = record["receipt_sha256"]
        stable = {k: v for k, v in record.items() if k != "receipt_sha256"}
        if (
            not isinstance(digest, str)
            or hashlib.sha256(_canonical(stable)).hexdigest() != digest
        ):
            raise BackupError("Backup manifest integrity check failed.")
        if (
            record["schema_version"] != "visiondata-gate.offline-product-backup.v1"
            or record["private_data"] is not True
        ):
            raise BackupError("Unsupported backup manifest contract.")
        records = record["files"]
        if (
            not isinstance(records, list)
            or len(records) != record["file_count"]
            or len(records) > 100_000
        ):
            raise BackupError("Backup manifest count mismatch.")
        seen = set()
        for item in records:
            name = item["path"]
            path = PurePosixPath(name)
            if (
                not isinstance(name, str)
                or path.is_absolute()
                or "\\" in name
                or ":" in name
                or ".." in path.parts
                or path.as_posix() != name
                or name == MANIFEST
                or name.casefold() in seen
            ):
                raise BackupError("Unsafe or duplicate backup member path.")
            if (
                not re.fullmatch("[0-9a-f]{64}", item["sha256"])
                or type(item["size"]) is not int
                or item["size"] < 0
            ):
                raise BackupError("Invalid backup file identity.")
            seen.add(name.casefold())
        if _inventory(root, snapshot=True) != records:
            raise BackupError("Backup file integrity or member set changed.")
        _offline_product(root)
        return record
    except (OSError, ValueError, KeyError, TypeError) as error:
        if isinstance(error, BackupError):
            raise
        raise BackupError("Backup manifest cannot be verified.") from error


def restore_backup(snapshot: Path, destination: Path) -> dict:
    snapshot = _root(snapshot)
    receipt = verify_backup(snapshot)
    destination = _target(snapshot, destination)
    staging = Path(
        tempfile.mkdtemp(prefix=".vdg-backup-", dir=destination.parent)
    ).resolve()
    try:
        _copy(receipt["files"], snapshot, staging)
        _offline_product(staging)
        if (
            _inventory(staging) != receipt["files"]
            or verify_backup(snapshot) != receipt
        ):
            raise BackupError("Backup changed during restore.")
        if destination.exists():
            raise BackupError("Destination already exists; restore was not published.")
        os.rename(staging, destination)
        return receipt
    except BaseException:
        if staging.exists():
            _remove_staging(staging, destination.parent)
        raise


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=["backup", "verify", "restore"])
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument("--destination", type=Path)
    parser.add_argument("--attest-offline", action="store_true")
    args = parser.parse_args()
    try:
        if args.action == "verify":
            receipt = verify_backup(args.source)
        else:
            if args.destination is None:
                raise BackupError("An explicit destination is required.")
            receipt = (
                create_backup(
                    args.source, args.destination, attest_offline=args.attest_offline
                )
                if args.action == "backup"
                else restore_backup(args.source, args.destination)
            )
        print(
            json.dumps(
                {
                    "status": "VERIFIED",
                    "private_data": True,
                    "file_count": receipt["file_count"],
                    "receipt_sha256": receipt["receipt_sha256"],
                }
            )
        )
        return 0
    except (BackupError, OSError) as error:
        print(
            json.dumps(
                {
                    "status": "NOT_VERIFIED",
                    "reason": str(error)
                    if isinstance(error, BackupError)
                    else "Filesystem operation failed.",
                }
            )
        )
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
