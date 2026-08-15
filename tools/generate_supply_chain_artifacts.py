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

# Exact-version resolutions for locked distributions whose Core Metadata is
# ambiguous, contains an entire license body, or is intentionally unavailable
# on one CI platform because the dependency is marker-gated.  Each resolution
# was checked against the license file shipped in the named wheel.  Version
# pinning is deliberate: a dependency upgrade returns to REVIEW_REQUIRED until
# its new distribution is reviewed.
_FROZEN_LICENSE_RESOLUTIONS = {
    ("visiondata-gate", "0.1.0"): {
        "expression": "Apache-2.0",
        "evidence": "owner-confirmed top-level LICENSE",
        "source": "LICENSE",
    },
    ("altair", "6.2.2"): {
        "expression": "BSD-3-Clause",
        "evidence": "wheel LICENSE SHA-256 648332da6631555f71f18305b96e9a2c409e73d73613b6c96587cdc0a449e054",
        "source": "manual-audit:altair-6.2.2.dist-info/licenses/LICENSE",
    },
    ("colorama", "0.4.6"): {
        "expression": "BSD-3-Clause",
        "evidence": "wheel LICENSE SHA-256 cac35c02686e5d04a5a7140bfb3b36e73aed496656e891102e428886d7930318",
        "source": "manual-audit:colorama-0.4.6.dist-info/licenses/LICENSE.txt",
    },
    ("itsdangerous", "2.2.0"): {
        "expression": "BSD-3-Clause",
        "evidence": "wheel LICENSE SHA-256 63af09891b6be8ad1a4252ed43af0f4efba7fc948e228367bed7f3c5ae0b09d7",
        "source": "manual-audit:itsdangerous-2.2.0.dist-info/LICENSE.txt",
    },
    ("jinja2", "3.1.6"): {
        "expression": "BSD-3-Clause",
        "evidence": "wheel LICENSE SHA-256 3b49dcee4105eb37bac10faf1be260408fe85d252b8e9df2e0979fc1e094437b",
        "source": "manual-audit:jinja2-3.1.6.dist-info/licenses/LICENSE.txt",
    },
    ("numpy", "2.2.6"): {
        "expression": "BSD-3-Clause",
        "evidence": "wheel LICENSE and bundled notices SHA-256 14256cc3a2c9d32ac284da96b937feb44f72dd90bee2317ac3020166846ad99d",
        "source": "manual-audit:numpy-2.2.6.dist-info/LICENSE.txt",
    },
    ("pandas", "2.3.3"): {
        "expression": "BSD-3-Clause",
        "evidence": "wheel LICENSE SHA-256 533eb6d0b98e5be3ddd12dce97be35dd11282f5c47cdf8d08c81756fd5d70a26",
        "source": "manual-audit:pandas-2.3.3.dist-info/LICENSE",
    },
    ("python-dateutil", "2.9.0.post0"): {
        "expression": "Apache-2.0 OR BSD-3-Clause",
        "evidence": "wheel dual-license file SHA-256 ba00f51a0d92823b5a1cde27d8b5b9d2321e67ed8da9bc163eff96d5e17e577e",
        "source": "manual-audit:python_dateutil-2.9.0.post0.dist-info/LICENSE",
    },
    ("watchdog", "6.0.0"): {
        "expression": "Apache-2.0",
        "evidence": "wheel LICENSE SHA-256 cfc7749b96f63bd31c3c42b5c471bf756814053e847c10f3eb003417bc523d30",
        "source": "manual-audit:watchdog-6.0.0.dist-info/LICENSE",
    },
}

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
        relative = path.resolve().relative_to(project_root.resolve())
    except ValueError:
        return "installed-metadata"

    # Virtual-environment layouts differ by platform:
    # Windows uses .venv/Lib/site-packages while POSIX uses
    # .venv/lib/pythonX.Y/site-packages.  Persist a logical location so an
    # offline rebuild has identical bytes on both platforms.
    for index, part in enumerate(relative.parts):
        if part.casefold() == "site-packages":
            metadata_member = Path(*relative.parts[index + 1 :]).as_posix()
            return f".venv/site-packages/{metadata_member}"
    return relative.as_posix()


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


def _license_evidence(
    metadata_records: list[dict[str, Any]],
    *,
    missing_detail: str | None = None,
    missing_source: str | None = None,
) -> dict[str, Any]:
    if len(metadata_records) != 1:
        detail = (
            missing_detail or "installed METADATA missing"
            if not metadata_records
            else "multiple METADATA records"
        )
        return {
            "classifiers": [],
            "evidence": detail,
            "expression": None,
            "metadata_source": (
                missing_source or "not-found" if not metadata_records else "ambiguous"
            ),
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
            f"License: {stripped}" if len(stripped) <= 120 else "License: long text"
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
    conditional_only: bool,
    metadata_records: list[dict[str, Any]],
    scope: str,
) -> tuple[dict[str, Any], dict[str, Any]]:
    name = package["name"]
    version = package["version"]
    purl = _purl(name, version)
    license_info = _license_evidence(
        [] if conditional_only else metadata_records,
        missing_detail=(
            "conditional dependency; installed METADATA intentionally not used"
            if conditional_only
            else None
        ),
        missing_source="uv.lock conditional edge" if conditional_only else None,
    )
    frozen_resolution = _FROZEN_LICENSE_RESOLUTIONS.get(
        (_normalize_name(name), version)
    )
    if license_info["review"] == REVIEW_REQUIRED and frozen_resolution is not None:
        license_info = {
            "classifiers": license_info["classifiers"],
            "evidence": frozen_resolution["evidence"],
            "expression": frozen_resolution["expression"],
            "metadata_source": frozen_resolution["source"],
            "review": "OK",
        }
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
        "> 本文件由 `uv.lock`、项目 `.venv` 中已安装的 `METADATA` 与精确版本许可证人工复核表离线生成；它是可审计的工程清单，不构成法律意见。项目授权见顶层 `LICENSE` / `NOTICE`，依赖说明见 `docs/THIRD_PARTY_NOTICES.md`。",
        "",
        f"- 锁定组件总数（含内部根项目）：`{len(rows)}`",
        f"- `REVIEW_REQUIRED`：`{review_count}`",
        "- 数据范围：只枚举 `uv.lock` 中的项目及锁定依赖；`.venv` 中不在锁内的分发包不会进入本表。",
        "- 条件依赖：仅通过 marker 入边引用的组件不读取当前平台安装 METADATA，避免跨平台借用许可证据。",
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

    conditional_dependencies: set[str] = set()
    unconditional_dependencies: set[str] = set()
    for normalized, package in by_name.items():
        dependencies = list(package.get("dependencies", []))
        if normalized == root_name:
            for optional in package.get("optional-dependencies", {}).values():
                dependencies.extend(optional)
        for dependency in dependencies:
            dependency_name = _normalize_name(dependency["name"])
            if dependency.get("marker"):
                conditional_dependencies.add(dependency_name)
            else:
                unconditional_dependencies.add(dependency_name)
    conditional_only_dependencies = (
        conditional_dependencies - unconditional_dependencies
    )

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
            conditional_only=normalized in conditional_only_dependencies,
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
                    "visiondata-gate:generated-from": "uv.lock + .venv installed METADATA + exact-version manual license resolutions",
                    "visiondata-gate:legal-review": "OWNER_CONFIRMED_NOT_LEGAL_ADVICE",
                    "visiondata-gate:offline-rebuild": "true",
                    "visiondata-gate:top-level-license-notice": "APACHE-2.0_AND_NOTICE_PRESENT",
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
