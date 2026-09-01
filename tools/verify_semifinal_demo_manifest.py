#!/usr/bin/env python3
"""Verify the isolated semifinal demo manifest before launching the Web UI.

The frozen contract lives in :mod:`visiondata_gate.semifinal_manifest` so this
pre-launch verifier and the reviewer API execute the same acceptance logic.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

from visiondata_gate.semifinal_manifest import (
    ManifestContractError,
    verify_manifest,
    verify_product_state,
)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--expected-product-root", type=Path)
    args = parser.parse_args()
    manifest_path = args.manifest.expanduser().resolve()
    try:
        payload = json.loads(manifest_path.read_text(encoding="utf-8"))
        manifest = verify_manifest(
            payload,
            manifest_path=manifest_path,
            expected_product_root=args.expected_product_root,
        )
        manifest = verify_product_state(manifest)
    except (OSError, json.JSONDecodeError, ManifestContractError) as exc:
        print(f"SEMIFINAL_DEMO_MANIFEST_INVALID: {exc}", file=sys.stderr)
        return 2
    print(json.dumps(manifest, ensure_ascii=False, sort_keys=True, indent=2))
    return 0


__all__ = [
    "ManifestContractError",
    "main",
    "verify_manifest",
    "verify_product_state",
]


if __name__ == "__main__":
    raise SystemExit(main())
