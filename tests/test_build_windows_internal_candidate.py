"""Create-only contracts for the parameterized Windows internal candidate ZIP."""

from __future__ import annotations

import hashlib
import importlib.util
import json
from pathlib import Path, PurePosixPath
import subprocess
import sys
import zipfile

import pytest


ROOT = Path(__file__).resolve().parents[1]
TOOL = ROOT / "tools" / "build_windows_internal_candidate.py"
EXPECTED_MEMBERS = {
    "installer/VisionData Gate_0.1.0_x64-setup.exe",
    "README_INTERNAL_CANDIDATE.md",
    "SHA256SUMS.txt",
    "evidence/BUILD_MANIFEST.json",
    "evidence/BUILD_SOURCE_IDENTITY.json",
    "evidence/VALIDATION_SUMMARY.json",
    "evidence/VALIDATION_RECEIPT.json",
}


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _write_json(path: Path, value: dict) -> None:
    path.write_text(
        json.dumps(value, sort_keys=True, separators=(",", ":")) + "\n",
        encoding="utf-8",
    )


def _load_tool():
    assert TOOL.is_file(), "parameterized internal candidate builder is missing"
    spec = importlib.util.spec_from_file_location(
        "build_windows_internal_candidate", TOOL
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _candidate_inputs(tmp_path: Path) -> dict:
    installer = tmp_path / "build-05-installer.exe"
    installer.write_bytes(b"synthetic unsigned NSIS installer")
    installer_sha = _sha(installer)
    build_manifest = tmp_path / "BUILD_MANIFEST.json"
    _write_json(
        build_manifest,
        {
            "schema_version": "visiondata-gate.staged-learning-build.v1",
            "status": "BUILD_COMPLETE_VALIDATION_PENDING",
            "source_content_sha256": "a" * 64,
            "artifacts": {
                "installer": {
                    "path": "VisionData Gate_0.1.0_x64-setup.exe",
                    "sha256": installer_sha,
                    "size": installer.stat().st_size,
                }
            },
            "code_signed": False,
            "clean_machine_validation": "NOT_RUN",
            "production_release_allowed": False,
            "external_runtime_model_capability": {
                "capability": "EXTERNAL_RUNTIME_REQUIRED",
                "model_pack_bundled": False,
                "torch_bundled": False,
                "torchvision_bundled": False,
                "ultralytics_bundled": False,
                "yolo_weights_bundled": False,
                "production_release_allowed": False,
            },
        },
    )
    build_sha = _sha(build_manifest)
    validation_summary = tmp_path / "VALIDATION_SUMMARY.json"
    _write_json(
        validation_summary,
        {
            "schema_version": "visiondata-gate.packaged-learning-smoke.v1",
            "status": "PASS_PACKAGED_LEARNING",
            "bound_build_manifest_sha256": build_sha,
            "clean_machine_validation": "NOT_RUN",
            "industrial_performance_verified": False,
            "machine_write_permitted": False,
            "production_release_allowed": False,
        },
    )
    validation_receipt = tmp_path / "VALIDATION_RECEIPT.json"
    _write_json(
        validation_receipt,
        {
            "schema_version": (
                "visiondata-gate.installed-normality-http-smoke.v1"
            ),
            "status": "PASS_INSTALLED_NORMALITY_HTTP_SMOKE",
            "installer_sha256": installer_sha,
            "clean_machine_validation": "NOT_RUN",
            "industrial_performance_verified": False,
            "machine_write_permitted": False,
            "production_release_allowed": False,
        },
    )
    return {
        "installer": installer,
        "expected_installer_sha256": installer_sha,
        "build_manifest": build_manifest,
        "expected_build_manifest_sha256": build_sha,
        "validation_summary": validation_summary,
        "expected_validation_summary_sha256": _sha(validation_summary),
        "validation_receipt": validation_receipt,
        "expected_validation_receipt_sha256": _sha(validation_receipt),
        "build_id": "windows-platform-rebuild-20260914-05",
        "package_version": "0.1.0",
    }


def _checksum_map(raw: bytes) -> dict[str, str]:
    rows = {}
    for line in raw.decode("utf-8").splitlines():
        digest, name = line.split("  ", 1)
        rows[name] = digest
    return rows


def test_internal_candidate_is_deterministic_fixed_and_self_verifying(
    tmp_path: Path,
) -> None:
    tool = _load_tool()
    inputs = _candidate_inputs(tmp_path)
    first = tmp_path / "candidate-a.zip"
    second = tmp_path / "candidate-b.zip"

    first_result = tool.build_internal_candidate(
        **inputs, output_zip=first
    )
    second_result = tool.build_internal_candidate(
        **inputs, output_zip=second
    )

    assert first_result["status"] == "CREATED_INTERNAL_CANDIDATE_RELEASE_HOLD"
    assert first_result["sha256"] == second_result["sha256"]
    assert first.read_bytes() == second.read_bytes()
    assert first_result["production_release_allowed"] is False
    assert "output_path" not in first_result
    with zipfile.ZipFile(first) as archive:
        assert archive.testzip() is None
        assert set(archive.namelist()) == EXPECTED_MEMBERS
        assert all(
            not PurePosixPath(name).is_absolute()
            and ".." not in PurePosixPath(name).parts
            for name in archive.namelist()
        )
        assert archive.read(
            "installer/VisionData Gate_0.1.0_x64-setup.exe"
        ) == inputs["installer"].read_bytes()
        identity = json.loads(
            archive.read("evidence/BUILD_SOURCE_IDENTITY.json")
        )
        assert identity["build_id"] == inputs["build_id"]
        assert identity["source_content_sha256"] == "a" * 64
        assert identity["installer"]["sha256"] == inputs[
            "expected_installer_sha256"
        ]
        boundaries = identity["release_boundaries"]
        assert boundaries == {
            "candidate_scope": "INTERNAL_ONLY",
            "clean_machine_validation": "NOT_RUN",
            "external_runtime_required": True,
            "industrial_validation": "HOLD",
            "license_review_required": True,
            "model_pack_bundled": False,
            "production_release_allowed": False,
            "signature_status": "NOT_SIGNED",
        }
        readme = archive.read("README_INTERNAL_CANDIDATE.md").decode("utf-8")
        for statement in (
            "NotSigned",
            "External Runtime Required",
            "No Model Pack Bundled",
            "production_release_allowed=false",
            "clean-machine validation=NOT_RUN",
            "industrial validation=HOLD",
            "license review required",
        ):
            assert statement in readme
        checksums = _checksum_map(archive.read("SHA256SUMS.txt"))
        assert set(checksums) == EXPECTED_MEMBERS - {"SHA256SUMS.txt"}
        for name, expected in checksums.items():
            assert hashlib.sha256(archive.read(name)).hexdigest() == expected
        serialized = b"".join(
            archive.read(name)
            for name in archive.namelist()
            if not name.endswith(".exe")
        )
        assert str(tmp_path).encode("utf-8") not in serialized
        assert not any(
            name.lower().endswith((".pt", ".db", ".sqlite", ".sqlite3", ".log"))
            for name in archive.namelist()
        )


def test_internal_candidate_never_overwrites_existing_output(tmp_path: Path) -> None:
    tool = _load_tool()
    inputs = _candidate_inputs(tmp_path)
    output = tmp_path / "existing.zip"
    output.write_bytes(b"preserve-existing-candidate")
    before = output.read_bytes()

    with pytest.raises(tool.CandidateError, match="OUTPUT_ALREADY_EXISTS"):
        tool.build_internal_candidate(**inputs, output_zip=output)

    assert output.read_bytes() == before


@pytest.mark.parametrize(
    ("mutation", "error_code"),
    [
        ("installer_digest", "INSTALLER_SHA256_MISMATCH"),
        ("manifest_installer", "BUILD_MANIFEST_INSTALLER_MISMATCH"),
        ("production_authority", "PRODUCTION_AUTHORITY_WIDENED"),
        ("private_path", "PRIVATE_OR_ABSOLUTE_PATH_FORBIDDEN"),
        ("credential", "PRIVATE_OR_CREDENTIAL_DATA_FORBIDDEN"),
    ],
)
def test_internal_candidate_fails_closed_before_creating_output(
    tmp_path: Path, mutation: str, error_code: str
) -> None:
    tool = _load_tool()
    inputs = _candidate_inputs(tmp_path)
    if mutation == "installer_digest":
        inputs["expected_installer_sha256"] = "0" * 64
    elif mutation == "manifest_installer":
        manifest = json.loads(inputs["build_manifest"].read_text(encoding="utf-8"))
        manifest["artifacts"]["installer"]["sha256"] = "0" * 64
        _write_json(inputs["build_manifest"], manifest)
        inputs["expected_build_manifest_sha256"] = _sha(inputs["build_manifest"])
        summary = json.loads(
            inputs["validation_summary"].read_text(encoding="utf-8")
        )
        summary["bound_build_manifest_sha256"] = inputs[
            "expected_build_manifest_sha256"
        ]
        _write_json(inputs["validation_summary"], summary)
        inputs["expected_validation_summary_sha256"] = _sha(
            inputs["validation_summary"]
        )
    elif mutation == "production_authority":
        receipt = json.loads(
            inputs["validation_receipt"].read_text(encoding="utf-8")
        )
        receipt["production_release_allowed"] = True
        _write_json(inputs["validation_receipt"], receipt)
        inputs["expected_validation_receipt_sha256"] = _sha(
            inputs["validation_receipt"]
        )
    elif mutation == "private_path":
        receipt = json.loads(
            inputs["validation_receipt"].read_text(encoding="utf-8")
        )
        receipt["debug_source"] = r"E:\private\customer.sqlite3"
        _write_json(inputs["validation_receipt"], receipt)
        inputs["expected_validation_receipt_sha256"] = _sha(
            inputs["validation_receipt"]
        )
    else:
        receipt = json.loads(
            inputs["validation_receipt"].read_text(encoding="utf-8")
        )
        receipt["api_key"] = "sk-private-test-value"
        _write_json(inputs["validation_receipt"], receipt)
        inputs["expected_validation_receipt_sha256"] = _sha(
            inputs["validation_receipt"]
        )
    output = tmp_path / "must-not-exist.zip"

    with pytest.raises(tool.CandidateError, match=error_code):
        tool.build_internal_candidate(**inputs, output_zip=output)

    assert not output.exists()


def test_internal_candidate_cli_is_parameterized_and_not_build_03_bound() -> None:
    assert TOOL.is_file(), "parameterized internal candidate builder is missing"
    completed = subprocess.run(
        [sys.executable, str(TOOL), "--help"],
        cwd=ROOT,
        capture_output=True,
        text=True,
        timeout=20,
        check=False,
    )

    assert completed.returncode == 0, completed.stderr
    for option in (
        "--installer",
        "--installer-sha256",
        "--build-manifest",
        "--build-manifest-sha256",
        "--validation-summary",
        "--validation-summary-sha256",
        "--validation-receipt",
        "--validation-receipt-sha256",
        "--build-id",
        "--package-version",
        "--output-zip",
    ):
        assert option in completed.stdout
    source = TOOL.read_text(encoding="utf-8")
    assert "windows-platform-rebuild-20260913-03" not in source
    assert ".rename(" not in source
    assert "shutil.move(" not in source
    assert "os.replace(" not in source
