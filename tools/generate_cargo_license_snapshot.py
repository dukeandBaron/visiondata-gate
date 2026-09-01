#!/usr/bin/env python3
"""Project Cargo license metadata into a path-free, lock-bound snapshot."""

from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
from pathlib import Path
from typing import Any


PROJECT_ROOT = Path(__file__).resolve().parents[1]
TARGET = "x86_64-pc-windows-msvc"


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def generate(project_root: Path, output: Path) -> dict[str, Any]:
    project = project_root.resolve(strict=True)
    manifest = project / "web" / "src-tauri" / "Cargo.toml"
    lock = project / "web" / "src-tauri" / "Cargo.lock"
    completed = subprocess.run(
        [
            "cargo",
            "metadata",
            "--locked",
            "--offline",
            "--filter-platform",
            TARGET,
            "--format-version",
            "1",
            "--manifest-path",
            str(manifest),
        ],
        cwd=project,
        check=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        encoding="utf-8",
        errors="strict",
    )
    metadata = json.loads(completed.stdout)
    packages = metadata.get("packages")
    if not isinstance(packages, list) or not packages:
        raise ValueError("cargo metadata returned no packages")
    projected: list[dict[str, Any]] = []
    identities: set[tuple[str, str, str]] = set()
    identity_by_id: dict[str, tuple[str, str, str]] = {}
    for package in packages:
        name = package.get("name")
        version = package.get("version")
        source = package.get("source") or "local-workspace"
        license_expression = package.get("license")
        license_file_present = bool(package.get("license_file"))
        if not all(
            isinstance(value, str) and value for value in (name, version, source)
        ):
            raise ValueError("cargo metadata package lacks a stable identity")
        if license_expression is not None and not isinstance(license_expression, str):
            raise ValueError(f"cargo license is not text: {name} {version}")
        identity = (name, version, source)
        if identity in identities:
            raise ValueError(f"duplicate cargo package identity: {identity}")
        identities.add(identity)
        package_id = package.get("id")
        if not isinstance(package_id, str) or not package_id:
            raise ValueError(f"cargo metadata package lacks an id: {identity}")
        identity_by_id[package_id] = identity
        projected.append(
            {
                "dependencies": [],
                "license_expression": license_expression,
                "license_file_present": license_file_present,
                "name": name,
                "source": source,
                "version": version,
            }
        )
    projected_by_identity = {
        (item["name"], item["version"], item["source"]): item for item in projected
    }
    resolve = metadata.get("resolve")
    nodes = resolve.get("nodes") if isinstance(resolve, dict) else None
    if not isinstance(nodes, list):
        raise ValueError("cargo metadata returned no resolved dependency graph")
    for node in nodes:
        package_id = node.get("id") if isinstance(node, dict) else None
        if package_id not in identity_by_id:
            raise ValueError("cargo resolve node does not map to a projected package")
        dependency_ids = node.get("dependencies", [])
        if not isinstance(dependency_ids, list):
            raise ValueError("cargo resolve dependencies must be a list")
        dependencies: list[dict[str, str]] = []
        for dependency_id in dependency_ids:
            if dependency_id not in identity_by_id:
                raise ValueError("cargo dependency does not map to a projected package")
            name, version, source = identity_by_id[dependency_id]
            dependencies.append({"name": name, "source": source, "version": version})
        dependencies.sort(
            key=lambda item: (item["name"], item["version"], item["source"])
        )
        projected_by_identity[identity_by_id[package_id]]["dependencies"] = dependencies
    projected.sort(key=lambda item: (item["name"], item["version"], item["source"]))
    document = {
        "schema_version": "visiondata-gate.cargo-license-snapshot.v1",
        "cargo_lock_sha256": _sha256(lock),
        "target": TARGET,
        "path_fields_included": False,
        "author_fields_included": False,
        "package_count": len(projected),
        "packages": projected,
    }
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(
        json.dumps(document, ensure_ascii=False, sort_keys=True, indent=2) + "\n",
        encoding="utf-8",
        newline="\n",
    )
    return {
        "cargo_lock_sha256": document["cargo_lock_sha256"],
        "output_sha256": _sha256(output),
        "package_count": document["package_count"],
        "review_required_count": sum(
            not item["license_expression"] for item in projected
        ),
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--project-root", type=Path, default=PROJECT_ROOT)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    project = args.project_root.resolve(strict=True)
    result = generate(
        project,
        args.output or project / "docs" / "CARGO_LICENSES.locked.json",
    )
    print(json.dumps(result, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
