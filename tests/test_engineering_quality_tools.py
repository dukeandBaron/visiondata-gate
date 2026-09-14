"""Fail-closed engineering gates, tested with tiny local artifacts only."""

from __future__ import annotations

import importlib
import json
from pathlib import Path
from types import ModuleType

import pytest


KEYS = [
    f"src/visiondata_gate/{name}.py"
    for name in ("policy", "evidence_state", "audit_envelope", "capa")
]


def tool() -> ModuleType:
    assert Path("tools/check_engineering_quality.py").is_file(), (
        "quality gate implementation missing"
    )
    return importlib.import_module("tools.check_engineering_quality")


@pytest.fixture
def artifacts(tmp_path: Path) -> tuple[Path, Path, Path]:
    summary = {
        "covered_lines": 2,
        "num_statements": 3,
        "missing_lines": 1,
        "covered_branches": 2,
        "num_branches": 3,
        "missing_branches": 1,
        "excluded_lines": 0,
    }
    coverage = {
        "meta": {"version": "7.16.0", "branch_coverage": True},
        "files": {key: {"summary": dict(summary)} for key in KEYS},
    }
    profile = {
        "schema_version": "visiondata-gate.quality-coverage-profile.v1",
        "coverage_version": "7.16.0",
        "expected_cases": ["suite::test_one"],
        "floors": {
            key: {"lines": [2, 3], "branches": [2, 3], "excluded_lines": 0}
            for key in KEYS
        },
    }
    cov, junit, config = (
        tmp_path / name for name in ("coverage.json", "junit.xml", "profile.json")
    )
    cov.write_text(json.dumps(coverage), encoding="utf-8")
    config.write_text(json.dumps(profile), encoding="utf-8")
    junit.write_text(
        '<testsuites><testsuite tests="1" failures="0" errors="0" skipped="0"><testcase classname="suite" name="test_one"/></testsuite></testsuites>',
        encoding="utf-8",
    )
    return cov, junit, config


def gate(paths: tuple[Path, Path, Path]) -> int:
    cov, junit, profile = paths
    return tool().main(
        [
            "coverage",
            "--coverage",
            str(cov),
            "--junit",
            str(junit),
            "--profile",
            str(profile),
        ]
    )


def test_exact_profile_passes(artifacts: tuple[Path, Path, Path]) -> None:
    assert gate(artifacts) == 0


def test_windows_report_paths_match_portable_profile(artifacts):
    cov = artifacts[0]
    data = json.loads(cov.read_text(encoding="utf-8"))
    data["files"] = {
        key.replace("/", "\\"): value for key, value in data["files"].items()
    }
    cov.write_text(json.dumps(data), encoding="utf-8")
    assert gate(artifacts) == 0


def test_duplicate_windows_and_posix_aliases_fail(artifacts):
    cov = artifacts[0]
    data = json.loads(cov.read_text(encoding="utf-8"))
    data["files"][KEYS[0].replace("/", "\\")] = data["files"][KEYS[0]]
    cov.write_text(json.dumps(data), encoding="utf-8")
    assert gate(artifacts) != 0


@pytest.mark.parametrize(
    "field,value",
    [
        ("covered_lines", -1),
        ("covered_lines", 2.0),
        ("covered_lines", True),
        ("covered_lines", float("nan")),
        ("num_branches", -1),
        ("excluded_lines", 1),
        ("missing_branches", 9),
    ],
)
def test_invalid_counts_fail(
    artifacts: tuple[Path, Path, Path], field: str, value: object
) -> None:
    cov = artifacts[0]
    data = json.loads(cov.read_text(encoding="utf-8"))
    data["files"][KEYS[0]]["summary"][field] = value
    cov.write_text(json.dumps(data), encoding="utf-8")
    assert gate(artifacts) != 0


@pytest.mark.parametrize(
    "field",
    [
        "covered_lines",
        "num_statements",
        "missing_lines",
        "covered_branches",
        "num_branches",
        "missing_branches",
        "excluded_lines",
    ],
)
def test_missing_metric_fails(artifacts: tuple[Path, Path, Path], field: str) -> None:
    cov = artifacts[0]
    data = json.loads(cov.read_text(encoding="utf-8"))
    del data["files"][KEYS[0]]["summary"][field]
    cov.write_text(json.dumps(data), encoding="utf-8")
    assert gate(artifacts) != 0


@pytest.mark.parametrize("change", ["extra", "missing", "version", "branch"])
def test_scope_and_metadata_fail_closed(
    artifacts: tuple[Path, Path, Path], change: str
) -> None:
    cov = artifacts[0]
    data = json.loads(cov.read_text(encoding="utf-8"))
    if change == "extra":
        data["files"]["elsewhere.py"] = data["files"][KEYS[0]]
    elif change == "missing":
        del data["files"][KEYS[0]]
    elif change == "version":
        data["meta"]["version"] = "7.15.0"
    else:
        data["meta"]["branch_coverage"] = False
    cov.write_text(json.dumps(data), encoding="utf-8")
    assert gate(artifacts) != 0


def test_fraction_comparison_does_not_round(artifacts: tuple[Path, Path, Path]) -> None:
    cov = artifacts[0]
    data = json.loads(cov.read_text(encoding="utf-8"))
    data["files"][KEYS[0]]["summary"].update(
        covered_lines=666666, num_statements=1000000, missing_lines=333334
    )
    cov.write_text(json.dumps(data), encoding="utf-8")
    assert gate(artifacts) != 0


def test_smaller_denominator_cannot_game_floor(
    artifacts: tuple[Path, Path, Path],
) -> None:
    cov = artifacts[0]
    data = json.loads(cov.read_text(encoding="utf-8"))
    data["files"][KEYS[0]]["summary"].update(
        covered_lines=2, num_statements=2, missing_lines=0
    )
    cov.write_text(json.dumps(data), encoding="utf-8")
    assert gate(artifacts) != 0


@pytest.mark.parametrize(
    "xml",
    [
        '<testsuite tests="0" failures="1" errors="0" skipped="0"/>',
        '<testsuite tests="1" failures="0" errors="0" skipped="0"><testcase classname="suite" name="test_one"><failure/></testcase></testsuite>',
        '<testsuite tests="1" failures="0" errors="0" skipped="0"><testcase classname="suite" name="test_one"><skipped/></testcase></testsuite>',
        '<testsuite tests="2" failures="0" errors="0" skipped="0"><testcase classname="suite" name="test_one"/><testcase classname="suite" name="test_one"/></testsuite>',
        '<testsuite tests="1" failures="0" errors="0" skipped="0"><testcase classname="suite" name="test_wrong"/></testsuite>',
        '<testsuite tests="1" failures="0" errors="0" skipped="0"/>',
        '<!DOCTYPE x [<!ENTITY bad "x">]><testsuite tests="0" failures="0" errors="0" skipped="0"/>',
        '<testsuite tests="1" failures="0" errors="0"><testcase classname="suite" name="test_one"/></testsuite>',
    ],
)
def test_bad_junit_fails(artifacts: tuple[Path, Path, Path], xml: str) -> None:
    artifacts[1].write_text(xml, encoding="utf-8")
    assert gate(artifacts) != 0


def test_duplicate_expected_cases_fail(artifacts: tuple[Path, Path, Path]) -> None:
    profile = artifacts[2]
    data = json.loads(profile.read_text(encoding="utf-8"))
    data["expected_cases"] *= 2
    profile.write_text(json.dumps(data), encoding="utf-8")
    assert gate(artifacts) != 0


def test_junit_case_outside_suite_fails(artifacts: tuple[Path, Path, Path]) -> None:
    artifacts[1].write_text(
        '<testsuites><testsuite tests="0" failures="0" errors="0" skipped="0"/><testcase classname="suite" name="test_one"/></testsuites>',
        encoding="utf-8",
    )
    assert gate(artifacts) != 0


def test_duplicate_json_keys_fail(artifacts: tuple[Path, Path, Path]) -> None:
    artifacts[0].write_text('{"files": {}, "files": {}}', encoding="utf-8")
    assert gate(artifacts) != 0


@pytest.mark.parametrize("value", [-1, 2.0, True, float("inf")])
def test_bad_profile_counts_fail(
    artifacts: tuple[Path, Path, Path], value: object
) -> None:
    profile = artifacts[2]
    data = json.loads(profile.read_text(encoding="utf-8"))
    data["floors"][KEYS[0]]["lines"][0] = value
    profile.write_text(json.dumps(data), encoding="utf-8")
    assert gate(artifacts) != 0


@pytest.mark.parametrize("index", [0, 1, 2])
def test_missing_artifacts_fail(artifacts: tuple[Path, Path, Path], index: int) -> None:
    artifacts[index].unlink()
    assert gate(artifacts) != 0


@pytest.mark.parametrize("index", [0, 1, 2])
def test_oversized_artifacts_fail(
    artifacts: tuple[Path, Path, Path], index: int
) -> None:
    artifacts[index].write_bytes(b" " * (8 * 1024 * 1024 + 1))
    assert gate(artifacts) != 0


def test_dependency_export_is_sorted_deduplicated_and_non_overwriting(
    tmp_path: Path,
) -> None:
    lock, output = tmp_path / "uv.lock", tmp_path / "deps.txt"
    lock.write_text(
        '[[package]]\nname="zebra"\nversion="2.0"\nsource={registry="https://pypi.org/simple"}\n[[package]]\nname="alpha"\nversion="1.0"\nsource={registry="https://pypi.org/simple"}\n[[package]]\nname="alpha"\nversion="1.0"\nsource={registry="https://pypi.org/simple"}\n[[package]]\nname="project"\nversion="1.0"\nsource={editable="C:/private/local-root"}\n',
        encoding="utf-8",
    )
    args = ["export-dependencies", "--lock", str(lock), "--output", str(output)]
    assert tool().main(args) == 0
    assert output.read_text(encoding="utf-8") == "alpha==1.0\nzebra==2.0\n"
    assert tool().main(args) != 0
    assert output.read_text(encoding="utf-8") == "alpha==1.0\nzebra==2.0\n"


@pytest.mark.parametrize(
    "registry",
    [
        "https://private.example/simple",
        "https://user:replace_me@example.invalid/simple",
        "file:///C:/private/local-root",
        "http://pypi.org/simple",
    ],
)
def test_private_registry_is_rejected_without_leaking(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], registry: str
) -> None:
    lock, output = tmp_path / "uv.lock", tmp_path / "deps.txt"
    lock.write_text(
        f'[[package]]\nname="x"\nversion="1.0"\nsource={{registry="{registry}"}}\n',
        encoding="utf-8",
    )
    assert (
        tool().main(
            ["export-dependencies", "--lock", str(lock), "--output", str(output)]
        )
        != 0
    )
    captured = capsys.readouterr()
    assert registry not in captured.out + captured.err
    assert not output.exists()
