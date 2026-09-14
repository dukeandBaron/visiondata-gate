"""Standard-library, fail-closed dependency and coverage evidence gates.

Python 3.12+, explicit UTF-8 and typed public functions. Never runs commands,
updates a baseline, installs packages, or reports input paths/registry secrets.
"""

from __future__ import annotations

import argparse
from fractions import Fraction
import json
from pathlib import Path
import re
import sys
import tomllib
from typing import cast
from xml.etree import ElementTree

from defusedxml import ElementTree as SafeElementTree


MAX_BYTES = 8 * 1024 * 1024
SCHEMA = "visiondata-gate.quality-coverage-profile.v1"
COVERAGE_VERSION = "7.16.0"


class QualityGateError(ValueError):
    """Sanitized evidence-contract failure, safe to print in public CI."""


def _read(path: Path) -> str:
    with path.open("rb") as stream:
        raw = stream.read(MAX_BYTES + 1)
    if not raw or len(raw) > MAX_BYTES:
        raise QualityGateError("artifact is empty or exceeds the 8 MiB limit")
    text = raw.decode("utf-8-sig")
    if "\x00" in text:
        raise QualityGateError("artifact must be UTF-8 text without NUL characters")
    return text


def _mapping(value: object) -> dict[str, object]:
    if not isinstance(value, dict) or not all(isinstance(key, str) for key in value):
        raise QualityGateError("required object is missing or malformed")
    return cast(dict[str, object], value)


def _integer(value: object) -> int:
    if type(value) is not int or value < 0:
        raise QualityGateError("counts must be non-negative integers")
    return value


def _json_pairs(pairs: list[tuple[str, object]]) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            raise QualityGateError("duplicate JSON keys are forbidden")
        result[key] = value
    return result


def _reject_constant(value: str) -> object:
    del value
    raise QualityGateError("non-finite JSON numbers are forbidden")


def _json(path: Path) -> dict[str, object]:
    return _mapping(
        json.loads(
            _read(path), object_pairs_hook=_json_pairs, parse_constant=_reject_constant
        )
    )


def export_dependencies(lock: Path, output: Path) -> int:
    """Export all locked public registry pairs, refusing private sources/overwrite."""
    data = tomllib.loads(_read(lock))
    packages = data.get("package")
    if not isinstance(packages, list):
        raise QualityGateError("lock package inventory is missing")
    entries: set[str] = set()
    for item in packages:
        package = _mapping(item)
        source = _mapping(package.get("source"))
        if set(source) == {"editable"}:
            continue
        registry = source.get("registry")
        if (
            set(source) != {"registry"}
            or not isinstance(registry, str)
            or registry.rstrip("/") != "https://pypi.org/simple"
        ):
            raise QualityGateError("non-public or unsupported dependency source")
        name, version = package.get("name"), package.get("version")
        if (
            not isinstance(name, str)
            or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]*", name)
            or not isinstance(version, str)
            or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9.!+_-]*", version)
        ):
            raise QualityGateError("invalid dependency name or pinned version")
        entries.add(f"{name}=={version}")
    if not entries:
        raise QualityGateError("public dependency inventory is empty")
    if not output.is_absolute():
        raise QualityGateError("dependency output must be an absolute path")
    output.parent.mkdir(parents=True, exist_ok=True)
    with output.open("x", encoding="utf-8", newline="\n") as stream:
        stream.write("\n".join(sorted(entries)) + "\n")
    return len(entries)


def _floor_pair(value: object) -> tuple[int, int]:
    if not isinstance(value, list) or len(value) != 2:
        raise QualityGateError("fraction floor must contain two integer counts")
    hit, total = (_integer(item) for item in value)
    if hit > total:
        raise QualityGateError("fraction numerator exceeds denominator")
    return hit, total


def _check_fraction(hit: int, total: int, baseline: tuple[int, int]) -> None:
    base_hit, base_total = baseline
    if hit > total or total < base_total:
        raise QualityGateError("coverage denominator shrank or counts are inconsistent")
    if base_total and (
        not total or Fraction(hit, total) < Fraction(base_hit, base_total)
    ):
        raise QualityGateError("coverage is below its exact fraction floor")


def _expected_cases(value: object) -> set[str]:
    if not isinstance(value, list) or not value:
        raise QualityGateError("expected testcase inventory is missing")
    cases: set[str] = set()
    for item in value:
        if not isinstance(item, str) or "::" not in item:
            raise QualityGateError("expected testcase identity is malformed")
        classname, name = item.split("::", 1)
        if not classname or not name or item in cases:
            raise QualityGateError(
                "expected testcase identities are empty or duplicated"
            )
        cases.add(item)
    return cases


def _xml_count(element: ElementTree.Element, name: str) -> int:
    text = element.get(name)
    if text is None or not re.fullmatch(r"[0-9]+", text):
        raise QualityGateError("JUnit aggregate count is missing or malformed")
    return int(text)


def _check_junit(path: Path, expected: set[str]) -> None:
    text = _read(path)
    if re.search(r"<!\s*(?:DOCTYPE|ENTITY)\b", text, flags=re.IGNORECASE):
        raise QualityGateError("XML DOCTYPE and ENTITY declarations are forbidden")
    root = SafeElementTree.fromstring(text, forbid_dtd=True)
    if root.tag not in {"testsuites", "testsuite"}:
        raise QualityGateError("JUnit root is unsupported")
    suites = list(root.iter("testsuite"))
    if not suites:
        raise QualityGateError("JUnit has no test suites")
    for element in root.iter():
        if element.tag in {"failure", "error", "skipped"}:
            raise QualityGateError("JUnit includes failed, errored, or skipped tests")
        if element.tag != "testsuite" and any(
            child.tag == "testcase" for child in element
        ):
            raise QualityGateError(
                "JUnit testcase must belong directly to a test suite"
            )
    for suite in suites:
        if any(_xml_count(suite, key) for key in ("failures", "errors", "skipped")):
            raise QualityGateError("JUnit aggregate failure, error, or skip is nonzero")
        if _xml_count(suite, "tests") != len(list(suite.iter("testcase"))):
            raise QualityGateError("JUnit aggregate tests disagree with actual cases")
    if root.tag == "testsuites":
        for key in ("failures", "errors", "skipped"):
            if root.get(key) is not None and _xml_count(root, key) != 0:
                raise QualityGateError("JUnit root aggregate is not successful")
        if root.get("tests") is not None and _xml_count(root, "tests") != len(
            list(root.iter("testcase"))
        ):
            raise QualityGateError("JUnit root testcase aggregate is inconsistent")
    actual: set[str] = set()
    for case in root.iter("testcase"):
        classname, name = case.get("classname"), case.get("name")
        if not classname or not name:
            raise QualityGateError("JUnit testcase identity is missing")
        identity = f"{classname}::{name}"
        if identity in actual:
            raise QualityGateError("JUnit contains duplicate testcase identities")
        actual.add(identity)
    if actual != expected:
        raise QualityGateError("JUnit actual testcase inventory differs from profile")


def check_coverage(coverage: Path, junit: Path, profile: Path) -> int:
    """Require exact scope/case identity and monotonic fraction/count evidence."""
    config, report = _json(profile), _json(coverage)
    if (
        config.get("schema_version") != SCHEMA
        or config.get("coverage_version") != COVERAGE_VERSION
    ):
        raise QualityGateError("coverage profile schema or tool version is unsupported")
    meta = _mapping(report.get("meta"))
    if (
        meta.get("version") != COVERAGE_VERSION
        or meta.get("branch_coverage") is not True
    ):
        raise QualityGateError(
            "coverage tool version or branch measurement is incorrect"
        )
    floors = _mapping(config.get("floors"))
    files: dict[str, object] = {}
    for path, value in _mapping(report.get("files")).items():
        normalized = path.replace("\\", "/")
        if normalized in files:
            raise QualityGateError("duplicate normalized coverage path")
        files[normalized] = value
    if not floors or set(floors) != set(files):
        raise QualityGateError("coverage module scope differs from profile")
    for key, raw_floor in floors.items():
        floor = _mapping(raw_floor)
        summary = _mapping(_mapping(files[key]).get("summary"))
        for prefix, total_key, hit_key, missing_key in (
            ("lines", "num_statements", "covered_lines", "missing_lines"),
            ("branches", "num_branches", "covered_branches", "missing_branches"),
        ):
            total, hit, missing = (
                _integer(summary.get(name))
                for name in (total_key, hit_key, missing_key)
            )
            if hit + missing != total:
                raise QualityGateError("coverage hit/missing counts are inconsistent")
            _check_fraction(hit, total, _floor_pair(floor.get(prefix)))
        if _integer(summary.get("excluded_lines")) > _integer(
            floor.get("excluded_lines")
        ):
            raise QualityGateError("coverage exclusion count increased")
    expected = _expected_cases(config.get("expected_cases"))
    _check_junit(junit, expected)
    return len(expected)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    export = commands.add_parser("export-dependencies")
    export.add_argument("--lock", type=Path, required=True)
    export.add_argument("--output", type=Path, required=True)
    coverage = commands.add_parser("coverage")
    coverage.add_argument("--coverage", type=Path, required=True)
    coverage.add_argument("--junit", type=Path, required=True)
    coverage.add_argument("--profile", type=Path, required=True)
    args = parser.parse_args(argv)
    try:
        if args.command == "export-dependencies":
            count = export_dependencies(args.lock, args.output)
            print(f"PASS: exported {count} locked public dependency versions")
        else:
            count = check_coverage(args.coverage, args.junit, args.profile)
            print(f"PASS: coverage fractions and {count} exact testcases verified")
    except QualityGateError as error:
        print(f"FAIL: {error}", file=sys.stderr)
        return 1
    except (OSError, UnicodeError, ValueError, ElementTree.ParseError):
        print(
            "FAIL: evidence could not be read, parsed, or safely written",
            file=sys.stderr,
        )
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
