from __future__ import annotations

import importlib.util
import json
import re
import sys
from pathlib import Path
from types import ModuleType

PROJECT_ROOT = Path(__file__).resolve().parents[1]
GENERATOR_PATH = PROJECT_ROOT / "tools" / "generate_supply_chain_artifacts.py"
FILE_URL_PREFIX = "file:" + "/" * 3
WINDOWS_USER_PREFIX = "/".join(("C:", "Users")) + "/"
WINDOWS_USER_BACKSLASH_PREFIX = "\\".join(("C:", "Users")) + "\\"
POSIX_USER_PREFIX = "/" + "Users" + "/"


def _load_generator() -> ModuleType:
    assert GENERATOR_PATH.is_file(), "supply-chain generator is missing"
    spec = importlib.util.spec_from_file_location(
        "visiondata_gate_supply_chain_generator_test",
        GENERATOR_PATH,
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def _write_metadata(
    site_packages: Path,
    *,
    name: str,
    version: str,
    license_expression: str | None = None,
    license_value: str | None = None,
    classifiers: tuple[str, ...] = (),
    direct_url: str | None = None,
) -> None:
    stem = re.sub(r"[-_.]+", "_", name)
    dist_info = site_packages / f"{stem}-{version}.dist-info"
    dist_info.mkdir(parents=True)
    lines = ["Metadata-Version: 2.4", f"Name: {name}", f"Version: {version}"]
    if license_expression is not None:
        lines.append(f"License-Expression: {license_expression}")
    if license_value is not None:
        lines.append(f"License: {license_value}")
    lines.extend(f"Classifier: {classifier}" for classifier in classifiers)
    (dist_info / "METADATA").write_text(
        "\n".join(lines) + "\n\n",
        encoding="utf-8",
        newline="\n",
    )
    if direct_url is not None:
        (dist_info / "direct_url.json").write_text(
            json.dumps(
                {"url": direct_url, "dir_info": {"editable": True}},
                sort_keys=True,
            ),
            encoding="utf-8",
            newline="\n",
        )


def _write_supply_chain_fixture(project: Path) -> None:
    (project / "uv.lock").write_text(
        """\
version = 1
revision = 3
requires-python = ">=3.12"

[[package]]
name = "demo-root"
version = "1.0.0"
source = { editable = "." }
dependencies = [{ name = "direct-lib" }]

[package.optional-dependencies]
qa = [{ name = "ambiguous-lib" }]

[[package]]
name = "direct-lib"
version = "2.0.0"
source = { registry = "https://pypi.org/simple" }
dependencies = [
  { name = "conditional-lib", marker = "sys_platform == 'win32'" },
  { name = "transitive-lib" },
]

[[package]]
name = "conditional-lib"
version = "5.0.0"
source = { registry = "https://pypi.org/simple" }

[[package]]
name = "ambiguous-lib"
version = "3.0.0"
source = { registry = "https://pypi.org/simple" }

[[package]]
name = "transitive-lib"
version = "4.0.0"
source = { registry = "https://pypi.org/simple" }
""",
        encoding="utf-8",
        newline="\n",
    )
    site_packages = project / ".venv" / "Lib" / "site-packages"
    _write_metadata(
        site_packages,
        name="demo-root",
        version="1.0.0",
        direct_url=f"{FILE_URL_PREFIX}{WINDOWS_USER_PREFIX}alice/private/demo-root",
    )
    _write_metadata(
        site_packages,
        name="direct-lib",
        version="2.0.0",
        license_expression="MIT",
    )
    _write_metadata(
        site_packages,
        name="ambiguous-lib",
        version="3.0.0",
        classifiers=("License :: OSI Approved :: BSD License",),
    )
    _write_metadata(
        site_packages,
        name="transitive-lib",
        version="4.0.0",
        classifiers=("License :: OSI Approved :: Apache Software License",),
    )
    _write_metadata(
        site_packages,
        name="conditional-lib",
        version="5.0.0",
        license_expression="MIT",
    )
    _write_metadata(
        site_packages,
        name="unrelated-global-package",
        version="99.0.0",
        license_expression="MIT",
    )


def _generate_artifacts(tmp_path: Path) -> dict[str, object]:
    generator = _load_generator()
    project = tmp_path / "project"
    project.mkdir()
    _write_supply_chain_fixture(project)

    first_sbom = tmp_path / "first" / "SBOM.cdx.json"
    first_inventory = tmp_path / "first" / "LICENSES.md"
    second_sbom = tmp_path / "second" / "SBOM.cdx.json"
    second_inventory = tmp_path / "second" / "LICENSES.md"
    first = generator.generate_supply_chain_artifacts(
        project_root=project,
        lock_path=project / "uv.lock",
        venv_path=project / ".venv",
        sbom_path=first_sbom,
        inventory_path=first_inventory,
    )
    second = generator.generate_supply_chain_artifacts(
        project_root=project,
        lock_path=project / "uv.lock",
        venv_path=project / ".venv",
        sbom_path=second_sbom,
        inventory_path=second_inventory,
    )
    return {
        "first": first,
        "second": second,
        "sbom_bytes": first_sbom.read_bytes(),
        "second_sbom_bytes": second_sbom.read_bytes(),
        "inventory_bytes": first_inventory.read_bytes(),
        "second_inventory_bytes": second_inventory.read_bytes(),
    }


def _property(component: dict[str, object], name: str) -> str:
    properties = component.get("properties", [])
    assert isinstance(properties, list)
    values = [item["value"] for item in properties if item.get("name") == name]
    assert len(values) == 1
    assert isinstance(values[0], str)
    return values[0]


def test_generator_is_byte_deterministic_and_uses_only_locked_packages(
    tmp_path: Path,
) -> None:
    generated_artifacts = _generate_artifacts(tmp_path)
    assert generated_artifacts["sbom_bytes"] == generated_artifacts["second_sbom_bytes"]
    assert (
        generated_artifacts["inventory_bytes"]
        == generated_artifacts["second_inventory_bytes"]
    )
    assert generated_artifacts["first"] == generated_artifacts["second"]

    sbom = json.loads(generated_artifacts["sbom_bytes"])
    root = sbom["metadata"]["component"]
    names = {root["name"], *(component["name"] for component in sbom["components"])}
    assert names == {
        "ambiguous-lib",
        "conditional-lib",
        "demo-root",
        "direct-lib",
        "transitive-lib",
    }
    assert "unrelated-global-package" not in names
    assert generated_artifacts["first"]["component_count"] == 5
    assert generated_artifacts["first"]["review_required_count"] == 3


def test_sbom_has_minimum_cyclonedx_fields_and_relationships(
    tmp_path: Path,
) -> None:
    generated_artifacts = _generate_artifacts(tmp_path)
    sbom = json.loads(generated_artifacts["sbom_bytes"])
    assert sbom["bomFormat"] == "CycloneDX"
    assert sbom["specVersion"] == "1.6"
    assert sbom["version"] == 1
    assert [component["name"] for component in sbom["components"]] == [
        "ambiguous-lib",
        "conditional-lib",
        "direct-lib",
        "transitive-lib",
    ]

    root = sbom["metadata"]["component"]
    components = {component["name"]: component for component in sbom["components"]}
    all_components = [root, *sbom["components"]]
    assert all(
        {"bom-ref", "name", "purl", "type", "version"} <= set(component)
        for component in all_components
    )
    assert all(
        component["purl"].startswith("pkg:pypi/") for component in all_components
    )
    assert _property(root, "visiondata-gate:relationship") == "internal-root"
    assert _property(root, "visiondata-gate:lock-source") == "local-project"
    assert (
        _property(components["direct-lib"], "visiondata-gate:relationship") == "direct"
    )
    assert (
        _property(components["ambiguous-lib"], "visiondata-gate:relationship")
        == "direct"
    )
    assert (
        _property(components["transitive-lib"], "visiondata-gate:relationship")
        == "transitive"
    )
    assert (
        _property(components["conditional-lib"], "visiondata-gate:license-evidence")
        == "conditional dependency; installed METADATA intentionally not used"
    )
    assert (
        _property(components["conditional-lib"], "visiondata-gate:metadata-source")
        == "uv.lock conditional edge"
    )

    refs = {component["bom-ref"] for component in all_components}
    dependency_refs = {item["ref"] for item in sbom["dependencies"]}
    assert dependency_refs == refs
    assert all(set(item["dependsOn"]) <= refs for item in sbom["dependencies"])


def test_license_inventory_marks_ambiguity_and_removes_local_paths(
    tmp_path: Path,
) -> None:
    generated_artifacts = _generate_artifacts(tmp_path)
    inventory = generated_artifacts["inventory_bytes"].decode("utf-8")
    sbom_text = generated_artifacts["sbom_bytes"].decode("utf-8")
    combined = inventory + sbom_text

    assert "REVIEW_REQUIRED" in inventory
    assert "不构成法律审查" in inventory
    assert "不替代项目顶层 `LICENSE` / `NOTICE`" in inventory
    assert "License-Expression: MIT" in inventory
    assert "License :: OSI Approved :: BSD License" in inventory
    assert "long text (" not in inventory
    assert "unrelated-global-package" not in inventory
    assert FILE_URL_PREFIX not in combined
    assert WINDOWS_USER_PREFIX not in combined
    assert WINDOWS_USER_BACKSLASH_PREFIX not in combined
    assert POSIX_USER_PREFIX not in combined
    assert ".venv/Lib/" not in combined
    assert ".venv/lib/python" not in combined
    assert ".venv/site-packages/" in combined
