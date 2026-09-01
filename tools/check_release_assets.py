#!/usr/bin/env python3
"""Validate hashes for the detached GOAI RC2 release assets."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
from pathlib import Path
from typing import Any


PROJECT_ROOT = Path(__file__).resolve().parents[1]
CHECKSUMS_PATH = PROJECT_ROOT / "release" / "SHA256SUMS.txt"
DELIVERABLES_DIR = PROJECT_ROOT / "deliverables"
RECEIPT_PATH = (
    DELIVERABLES_DIR / "VisionData_Gate_GOAI_BoundlessAgents_RC2_20260816.receipt.json"
)
EXPECTED_ASSETS = {
    "GOAI_VisionDataGate_BoundlessAgents_20260816.pdf",
    "GOAI_VisionDataGate_BoundlessAgents_20260816.pptx",
    "VisionDataGate_GOAI_FinalDemo_20260813.mp4",
    "VisionData_Gate_GOAI_BoundlessAgents_RC2_20260816.receipt.json",
    "VisionData_Gate_GOAI_BoundlessAgents_RC2_20260816.zip",
}
CHECKSUM_LINE = re.compile(r"^(?P<sha256>[0-9a-f]{64})  (?P<name>[^/\\]+)$")


class ReleaseAssetValidationError(RuntimeError):
    """Raised when a release attachment or checksum entry is inconsistent."""


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise ReleaseAssetValidationError(message)


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _load_checksums(path: Path) -> dict[str, str]:
    entries: dict[str, str] = {}
    for line_number, raw_line in enumerate(
        path.read_text(encoding="utf-8").splitlines(), 1
    ):
        match = CHECKSUM_LINE.fullmatch(raw_line)
        _require(match is not None, f"invalid checksum line {line_number}")
        assert match is not None
        name = match.group("name")
        _require(name not in entries, f"duplicate checksum entry: {name}")
        entries[name] = match.group("sha256")
    _require(set(entries) == EXPECTED_ASSETS, "release asset set drift")
    return entries


def validate_release_assets(*, require_all: bool = False) -> dict[str, Any]:
    checksums = _load_checksums(CHECKSUMS_PATH)
    receipt = json.loads(RECEIPT_PATH.read_text(encoding="utf-8"))
    candidate = receipt["candidate"]
    candidate_name = Path(candidate["path"]).name
    _require(candidate_name in EXPECTED_ASSETS, "receipt candidate name drift")
    _require(
        checksums[candidate_name] == candidate["sha256"],
        "candidate checksum differs from detached receipt",
    )

    validated: list[str] = []
    receipt_backed: list[str] = []
    total_bytes = 0
    for name, expected_digest in checksums.items():
        path = DELIVERABLES_DIR / name
        if path.is_file():
            observed_digest = _sha256(path)
            _require(observed_digest == expected_digest, f"asset hash drift: {name}")
            if name == candidate_name:
                _require(
                    path.stat().st_size == candidate["bytes"], "candidate size drift"
                )
            validated.append(name)
            total_bytes += path.stat().st_size
            continue

        _require(not require_all, f"required release asset is missing: {name}")
        _require(name == candidate_name, f"tracked release asset is missing: {name}")
        receipt_backed.append(name)

    return {
        "status": "PASS",
        "asset_count": len(checksums),
        "byte_verified_asset_count": len(validated),
        "receipt_backed_asset_count": len(receipt_backed),
        "byte_verified_total_bytes": total_bytes,
        "candidate_sha256": candidate["sha256"],
        "require_all": require_all,
    }


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--require-all",
        action="store_true",
        help="fail unless every listed Release attachment exists locally",
    )
    return parser


def main() -> int:
    args = build_parser().parse_args()
    print(
        json.dumps(
            validate_release_assets(require_all=args.require_all),
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
