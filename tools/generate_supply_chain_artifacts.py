#!/usr/bin/env python3
"""Generate deterministic, offline supply-chain evidence from uv.lock and .venv."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
import tomllib
from collections import defaultdict, deque
from email.parser import BytesParser
from email.policy import default
from pathlib import Path
from typing import Any
from urllib.parse import quote


PROJECT_ROOT = Path(__file__).resolve().parents[1]
RELATIONSHIP_PROPERTY = "visiondata-gate:relationship"
LOCK_SOURCE_PROPERTY = "visiondata-gate:lock-source"
METADATA_SOURCE_PROPERTY = "visiondata-gate:metadata-source"
LICENSE_EVIDENCE_PROPERTY = "visiondata-gate:license-evidence"
LICENSE_REVIEW_PROPERTY = "visiondata-gate:license-review"
DIRECT_GROUPS_PROPERTY = "visiondata-gate:direct-groups"
REVIEW_REQUIRED = "REVIEW_REQUIRED"

_KNOWN_LICENSE_VALUES = {
    "apache 2.0": "Apache-2.0",
    "apache license 2.0": "Apache-2.0",
    "apache-2.0": "Apache-2.0",
    "bsd 2-clause": "BSD-2-Clause",
    "bsd 3-clause": "BSD-3-Clause",
    "bsd-2-clause": "BSD-2-Clause",
    "bsd-3-clause": "BSD-3-Clause",
    "3-clause bsd license": "BSD-3-Clause",
    "isc": "ISC",
    "mit": "MIT",
    "mit license": "MIT",
    "mpl-2.0": "MPL-2.0",
    "mozilla public license 2.0": "MPL-2.0",
    "psf-2.0": "PSF-2.0",
    "zlib": "Zlib",
}

_KNOWN_LICENSE_CLASSIFIERS = {
    "License :: OSI Approved :: Apache Software License": "Apache-2.0",
    "License :: OSI Approved :: MIT License": "MIT",
    "License :: OSI Approved :: Mozilla Public License 2.0 (MPL 2.0)": ("MPL-2.0"),
}


def _normalize_name(name: str) -> str:
    return re.sub(r"[-_.]+", "-", name).casefold()


def _purl(name: str, version: str) -> str:
    normalized = _normalize_name(name)
    return f"pkg:pypi/{quote(normalized, safe='-._~')}@{quote(version, safe='-._~')}"


def _canonical_json_bytes(value: Any) -> bytes:
    text = json.dumps(
        value,
        allow_nan=False,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    )
    return (text + "\n").encode("utf-8")


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _relative_source(path: Path, project_root: Path) -> str:
    try:
        return path.resolve().relative_to(project_root.resolve()).as_posix()
    except ValueError:
        return "installed-metadata"


def _lock_source(source: dict[str, Any]) -> str:
    if "editable" in source or "path" in source:
        return "local-project"
    if "registry" in source:
        return f"registry:{source['registry']}"
    if "git" in source:
        return f"git:{source['git']}"
    return "uv.lock:unspecified-source"


def _dependency_names(package: dict[str, Any], *, include_optional: bool) -> set[str]:
    names = {
        _normalize_name(item["name"])
        for item in package.get("dependencies", [])
        if isinstance(item, dict) and isinstance(item.get("name"), str)
    }
    if include_optional:
        for dependencies in package.get("optional-dependencies", {}).values():
            names.update(
                _normalize_name(item["name"])
                for item in dependencies
                if isinstance(item, dict) and isinstance(item.get("name"), str)
            )
    return names


def _read_installed_metadata(
    venv_path: Path,
    project_root: Path,
) -> dict[tuple[str, str], list[dict[str, Any]]]:
    candidates = [venv_path / "Lib" / "site-packages"]
    if (venv_path / "lib").is_dir():
        candidates.extend(sorted((venv_path / "lib").glob("python*/site-packages")))
    records: dict[tuple[str, str], list[dict[str, Any]]] = defaultdict(list)
    for site_packages in candidates:
        if not site_packages.is_dir():
            continue
        metadata_paths = sorted(site_packages.glob("*.dist-info/METADATA"))
        metadata_paths.extend(sorted(site_packages.glob("*.egg-info/PKG-INFO")))
        for metadata_path in metadata_paths:
            message = BytesParser(policy=default).parsebytes(metadata_path.read_bytes())
            name = message.get("Name")
            version = message.get("Version")
            if not name or not version:
                continue
            records[(_normalize_name(name), version)].append(
                {
                    "classifiers": sorted(
                        classifier
                        for classifier in message.get_all("Classifier", [])
                        if classifier.startswith("License ::")
                    ),
                    "license": message.get("License"),
                    "license_expression": message.get("License-Expression"),
                    "source": _relative_source(metadata_path, project_root),
                }
            )
    return records


def _license_value_expression(value: str | None) -> str | None:
    if value is None:
        return None
    normalized = re.sub(r"\s+", " ", value.strip()).casefold()
    return _KNOWN_LICENSE_VALUES.get(normalized)


def _license_evidence(metadata_records: list[dict[str, Any]]) -> dict[str, Any]:
    if len(metadata_records) != 1:
        detail = (
            "installed METADATA missing"
            if not metadata_records
            else "multiple METADATA records"
        )
        return {
            "classifiers": [],
            "evidence": detail,
            "expression": None,
            "metadata_source": "not-found" if not metadata_records else "ambiguous",
            "review": REVIEW_REQUIRED,
        }

    metadata = metadata_records[0]
    expression = (metadata.get("license_expression") or "").strip()
    classifiers = metadata["classifiers"]
    license_value = metadata.get("license")
    evidence_parts: list[str] = []
    if expression and expression.casefold() not in {"unknown", "n/a"}:
        evidence_parts.append(f"License-Expression: {expression}")
        evidence_parts.extend(f"Classifier: {item}" for item in classifiers)
        return {
            "classifiers": classifiers,
            "evidence": "; ".join(evidence_parts),
            "expression": expression,
            "metadata_source": metadata["source"],
            "review": "OK",
        }

    mapped_license = _license_value_expression(license_value)
    if license_value:
        stripped = re.sub(r"\s+", " ", license_value.strip())
        evidence_parts.append(
            f"License: {stripped}"
            if len(stripped) <= 120
            else f"License: long text ({len(stripped)} chars)"
        )
    evidence_parts.extend(f"Classifier: {item}" for item in classifiers)
    if mapped_license is not None:
        return {
            "classifiers": classifiers,
            "evidence": "; ".join(evidence_parts),
            "expression": mapped_license,
            "metadata_source": metadata["source"],
            "review": "OK",
        }

    mapped_classifiers = {
        _KNOWN_LICENSE_CLASSIFIERS[item]
        for item in classifiers
        if item in _KNOWN_LICENSE_CLASSIFIERS
    }
    unmapped_classifiers = [
        item for item in classifiers if item not in _KNOWN_LICENSE_CLASSIFIERS
    ]
    if len(mapped_classifiers) == 1 and not unmapped_classifiers and not license_value:
        return {
            "classifiers": classifiers,
            "evidence": "; ".join(evidence_parts),
            "expression": next(iter(mapped_classifiers)),
            "metadata_source": metadata["source"],
            "review": "OK",
        }

    return {
        "classifiers": classifiers,
        "evidence": "; ".join(evidence_parts) or "no license metadata",
        "expression": None,
        "metadata_source": metadata["source"],
        "review": REVIEW_REQUIRED,
    }


def _properties(values: dict[str, str]) -> list[dict[str, str]]:
    return [{"name": name, "value": value} for name, value in sorted(values.items())]


def _component(
    package: dict[str, Any],
    *,
    relationship: str,
    direct_groups: tuple[str, ...],
    metadata_records: list[dict[str, Any]],
    scope: str,
) -> tuple[dict[str, Any], dict[str, Any]]:
    name = package["name"]
    version = package["version"]
    purl = _purl(name, version)
    license_info = _license_evidence(metadata_records)
    property_values = {
        LICENSE_EVIDENCE_PROPERTY: license_info["evidence"],
        LICENSE_REVIEW_PROPERTY: license_info["review"],
        LOCK_SOURCE_PROPERTY: _lock_source(package.get("source", {})),
        METADATA_SOURCE_PROPERTY: license_info["metadata_source"],
        RELATIONSHIP_PROPERTY: relationship,
    }
    if direct_groups:
        property_values[DIRECT_GROUPS_PROPERTY] = ",".join(direct_groups)
    licenses = (
        [{"expression": license_info["expression"]}]
        if license_info["expression"] is not None
        else [{"license": {"name": REVIEW_REQUIRED}}]
    )
    component = {
        "bom-ref": purl,
        "licenses": licenses,
        "name": name,
        "properties": _properties(property_values),
        "purl": purl,
        "scope": scope,
        "type": "application" if relationship == "internal-root" else "library",
        "version": version,
    }
    inventory = {
        "classifiers": license_info["classifiers"],
        "evidence": license_info["evidence"],
        "expression": license_info["expression"],
        "metadata_source": license_info["metadata_source"],
        "name": name,
        "purl": purl,
        "relationship": relationship,
        "review": license_info["review"],
        "version": version,
    }
    return component, inventory


def _markdown_cell(value: Any) -> str:
    return str(value).replace("\\", "\\\\").replace("|", "\\|").replace("\n", " ")


def _inventory_bytes(rows: list[dict[str, Any]]) -> bytes:
    review_count = sum(row["review"] == REVIEW_REQUIRED for row in rows)
    lines = [
        "# 第三方许可证元数据清单（自动生成）",
        "",
        "> 本文件由 `uv.lock` 与项目 `.venv` 中已安装的 `METADATA` 离线生成，仅是可审计的元数据清单；不构成法律审查，也不替代项目顶层 `LICENSE` / `NOTICE`。",
        "",
        f"- 锁定组件总数（含内部根项目）：`{len(rows)}`",
        f"- `REVIEW_REQUIRED`：`{review_count}`",
        "- 数据范围：只枚举 `uv.lock` 中的项目及锁定依赖；`.venv` 中不在锁内的分发包不会进入本表。",
        "- 重建方式：`python tools/generate_supply_chain_artifacts.py`；不需要联网。",
        "",
        "| 关系 | 名称 | 版本 | PURL | 许可表达式 / classifiers | 元数据来源 | 复核状态 |",
        "|---|---|---|---|---|---|---|",
    ]
    for row in rows:
        license_display = row["evidence"]
        source = f"uv.lock; {row['metadata_source']}"
        values = [
            row["relationship"],
            row["name"],
            row["version"],
            row["purl"],
            license_display,
            source,
            row["review"],
        ]
        lines.append(
            "| " + " | ".join(_markdown_cell(value) for value in values) + " |"
        )
    return ("\n".join(lines) + "\n").encode("utf-8")


def generate_supply_chain_artifacts(
    *,
    project_root: str | Path,
    lock_path: str | Path,
    venv_path: str | Path,
    sbom_path: str | Path,
    inventory_path: str | Path,
) -> dict[str, Any]:
    project = Path(project_root).resolve(strict=True)
    lock_file = Path(lock_path)
    venv = Path(venv_path)
    sbom_output = Path(sbom_path)
    inventory_output = Path(inventory_path)
    lock = tomllib.loads(lock_file.read_text(encoding="utf-8"))
    packages = lock.get("package")
    if not isinstance(packages, list) or not packages:
        raise ValueError("uv.lock contains no package records")

    by_name: dict[str, dict[str, Any]] = {}
    for package in packages:
        if not isinstance(package, dict):
            raise ValueError("uv.lock package record is not a table")
        name = package.get("name")
        version = package.get("version")
        if not isinstance(name, str) or not isinstance(version, str):
            raise ValueError("uv.lock package record lacks name/version")
        normalized = _normalize_name(name)
        if normalized in by_name:
            raise ValueError(f"ambiguous duplicate package name in uv.lock: {name}")
        by_name[normalized] = package

    roots = [
        package
        for package in packages
        if package.get("source", {}).get("editable") == "."
    ]
    if len(roots) != 1:
        raise ValueError("uv.lock must contain exactly one editable root project")
    root = roots[0]
    root_name = _normalize_name(root["name"])

    dependency_graph: dict[str, set[str]] = {}
    for normalized, package in by_name.items():
        dependencies = _dependency_names(
            package,
            include_optional=normalized == root_name,
        )
        missing = sorted(dependencies - set(by_name))
        if missing:
            raise ValueError(
                f"uv.lock references missing dependencies for {package['name']}: {missing}"
            )
        dependency_graph[normalized] = dependencies

    direct_groups: dict[str, set[str]] = defaultdict(set)
    for dependency in root.get("dependencies", []):
        direct_groups[_normalize_name(dependency["name"])].add("required")
    for group, dependencies in sorted(root.get("optional-dependencies", {}).items()):
        for dependency in dependencies:
            direct_groups[_normalize_name(dependency["name"])].add(f"optional:{group}")

    required_reachable: set[str] = set()
    queue: deque[str] = deque(
        sorted(_normalize_name(item["name"]) for item in root.get("dependencies", []))
    )
    while queue:
        current = queue.popleft()
        if current in required_reachable:
            continue
        required_reachable.add(current)
        queue.extend(sorted(dependency_graph[current] - required_reachable))

    metadata = _read_installed_metadata(venv, project)
    component_by_name: dict[str, dict[str, Any]] = {}
    inventory_by_name: dict[str, dict[str, Any]] = {}
    for normalized, package in sorted(
        by_name.items(),
        key=lambda item: (item[0], item[1]["version"]),
    ):
        if normalized == root_name:
            relationship = "internal-root"
            scope = "required"
        elif normalized in direct_groups:
            relationship = "direct"
            scope = "required" if normalized in required_reachable else "optional"
        else:
            relationship = "transitive"
            scope = "required" if normalized in required_reachable else "optional"
        key = (normalized, package["version"])
        component, inventory = _component(
            package,
            relationship=relationship,
            direct_groups=tuple(sorted(direct_groups.get(normalized, set()))),
            metadata_records=metadata.get(key, []),
            scope=scope,
        )
        component_by_name[normalized] = component
        inventory_by_name[normalized] = inventory

    root_component = component_by_name[root_name]
    external_components = [
        component_by_name[name]
        for name in sorted(component_by_name)
        if name != root_name
    ]
    dependency_records = []
    for name in sorted(component_by_name):
        dependency_records.append(
            {
                "dependsOn": sorted(
                    component_by_name[dependency]["bom-ref"]
                    for dependency in dependency_graph[name]
                ),
                "ref": component_by_name[name]["bom-ref"],
            }
        )

    sbom = {
        "$schema": "https://cyclonedx.org/schema/bom-1.6.schema.json",
        "bomFormat": "CycloneDX",
        "components": external_components,
        "dependencies": dependency_records,
        "metadata": {
            "component": root_component,
            "properties": _properties(
                {
                    "visiondata-gate:generated-from": "uv.lock + .venv installed METADATA",
                    "visiondata-gate:legal-review": "NOT_PERFORMED",
                    "visiondata-gate:offline-rebuild": "true",
                    "visiondata-gate:top-level-license-notice": "NOT_REPLACED",
                }
            ),
        },
        "specVersion": "1.6",
        "version": 1,
    }
    sbom_bytes = _canonical_json_bytes(sbom)
    inventory_rows = [inventory_by_name[root_name]] + [
        inventory_by_name[name]
        for name in sorted(inventory_by_name)
        if name != root_name
    ]
    inventory_bytes = _inventory_bytes(inventory_rows)

    sbom_output.parent.mkdir(parents=True, exist_ok=True)
    inventory_output.parent.mkdir(parents=True, exist_ok=True)
    sbom_output.write_bytes(sbom_bytes)
    inventory_output.write_bytes(inventory_bytes)
    return {
        "component_count": len(component_by_name),
        "inventory_sha256": _sha256(inventory_bytes),
        "review_required_count": sum(
            row["review"] == REVIEW_REQUIRED for row in inventory_rows
        ),
        "sbom_sha256": _sha256(sbom_bytes),
    }


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Generate offline deterministic CycloneDX and license metadata evidence."
    )
    parser.add_argument("--project-root", type=Path, default=PROJECT_ROOT)
    parser.add_argument("--lock", type=Path)
    parser.add_argument("--venv", type=Path)
    parser.add_argument("--sbom", type=Path)
    parser.add_argument("--inventory", type=Path)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    project = args.project_root.resolve(strict=True)
    result = generate_supply_chain_artifacts(
        project_root=project,
        lock_path=args.lock or project / "uv.lock",
        venv_path=args.venv or project / ".venv",
        sbom_path=args.sbom or project / "docs" / "SBOM.cdx.json",
        inventory_path=(
            args.inventory
            or project / "docs" / "THIRD_PARTY_LICENSE_INVENTORY.generated.md"
        ),
    )
    sys.stdout.buffer.write(_canonical_json_bytes(result))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
