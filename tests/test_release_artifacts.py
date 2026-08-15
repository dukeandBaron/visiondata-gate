from __future__ import annotations

import hashlib
import json
import os
import subprocess
import sys
from pathlib import Path, PurePosixPath


PROJECT_ROOT = Path(__file__).resolve().parents[1]


def test_release_checker_writes_utf8_under_legacy_stdout_codec() -> None:
    """Reproduce the Windows cp1252 failure that previously produced false-green CI."""

    environment = os.environ.copy()
    environment["PYTHONIOENCODING"] = "cp1252"
    process = subprocess.run(
        [sys.executable, "tools/check_release_consistency.py"],
        cwd=PROJECT_ROOT,
        env=environment,
        capture_output=True,
        timeout=30,
        check=False,
    )

    assert process.returncode == 0, process.stderr.decode("utf-8", errors="replace")
    payload = json.loads(process.stdout.decode("utf-8", errors="strict"))
    assert payload["ok"] is True
    assert payload["track"] == "Boundless Agents / AI+工业制造"


def test_ci_release_validators_are_independent_fail_fast_steps() -> None:
    workflow = (PROJECT_ROOT / ".github" / "workflows" / "ci.yml").read_text(
        encoding="utf-8"
    )

    assert 'PYTHONUTF8: "1"' in workflow
    assert "- name: Validate submission evidence" in workflow
    assert "- name: Validate reviewer website projection" in workflow
    assert "- name: Validate detached release assets" in workflow
    assert "run: uv run python tools/check_release_consistency.py" in workflow
    assert "run: uv run python tools/check_website_data.py" in workflow
    assert "run: uv run python tools/check_release_assets.py" in workflow
    assert "- name: Validate release evidence" not in workflow


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _project_member(relative_path: str) -> Path:
    member = PurePosixPath(relative_path)
    assert relative_path == member.as_posix()
    assert not member.is_absolute()
    assert ".." not in member.parts
    return PROJECT_ROOT.joinpath(*member.parts)


def test_historical_video_qa_is_paired_with_historical_mp4() -> None:
    """Keep the superseded v1 demo auditable without treating it as current."""

    qa_path = PROJECT_ROOT / "deliverables" / "_qa" / "video_qa.json"
    historical_video = (
        PROJECT_ROOT / "deliverables" / "VisionDataGate_GOAI_AutoDemo_20260810.mp4"
    )
    historical_sheet = PROJECT_ROOT / "deliverables" / "_qa" / "video_contact_sheet.png"
    if not qa_path.is_file():
        # Curated submission candidates intentionally exclude all three
        # historical artifacts. A partial pair would be an audit defect.
        assert not historical_video.exists()
        assert not historical_sheet.exists()
        return

    qa = json.loads(qa_path.read_text(encoding="utf-8"))
    video_path = _project_member(qa["video_file"])
    contact_sheet = _project_member(qa["contact_sheet"])

    assert qa["schema_version"] == "visiondata-gate.video-qa.v1"
    assert qa["status"] == "PASS"
    assert qa["checks"] and all(qa["checks"].values())
    assert video_path.is_file()
    assert contact_sheet.is_file()
    assert video_path.stat().st_size == qa["file_size_bytes"]
    assert _sha256(video_path) == qa["sha256"]
    assert video_path.read_bytes()[4:8] == b"ftyp"
    assert qa["codec"].startswith("h264")
    assert qa["resolution"] == [1920, 1080]
    assert qa["fps"] == 30.0
    assert 169.9 <= qa["duration_seconds"] <= 170.1
    assert qa["decode"]["decoded_frame_count"] == 5100
    assert qa["decode"]["full_decode_exit_code"] == 0
    assert qa["audio"]["present"] is True
    assert qa["anonymity"]["contains_absolute_local_paths"] is False
    assert not qa["anonymity"]["forbidden_binary_hits"]
    assert not qa["anonymity"]["forbidden_metadata_hits"]


def test_final_video_qa_is_paired_with_frozen_final_artifacts() -> None:
    qa_path = PROJECT_ROOT / "deliverables" / "_qa" / "final_video_qa_20260813.json"
    expected_video_member = "deliverables/VisionDataGate_GOAI_FinalDemo_20260813.mp4"
    expected_contact_sheet_member = (
        "deliverables/_qa/final_video_contact_sheet_20260813.png"
    )
    video_path = _project_member(expected_video_member)
    contact_sheet_path = _project_member(expected_contact_sheet_member)
    if not qa_path.is_file():
        # The Boundless Agents RC intentionally excludes the pre-RC video and
        # its QA pair.  A complete absence is valid; any partial pair is not.
        assert not video_path.exists()
        assert not contact_sheet_path.exists()
        return

    qa = json.loads(qa_path.read_text(encoding="utf-8"))
    expected_video_sha256 = (
        "399cc2f26e1eb07634ec7a9e41dd499a43452d50c2f08d36245f1e956d8b2ad2"
    )
    expected_contact_sheet_sha256 = (
        "536f64d1b62adfddb832d11e6d1fc2890a19e9bbd1f1862ad372c4984f8b80ba"
    )

    assert qa["schema_version"] == "visiondata-gate.video-qa.v2"
    assert qa["status"] == "PASS"
    assert qa["video_file"] == expected_video_member
    assert qa["contact_sheet"] == expected_contact_sheet_member
    assert qa["sha256"] == expected_video_sha256
    assert qa["file_size_bytes"] == 12_826_648
    assert qa["checks"] == {
        "anonymous_payload_scan": True,
        "audio_is_aac": True,
        "audio_is_audible": True,
        "codec_is_h264": True,
        "contact_sheet_created": True,
        "duration_is_170_seconds": True,
        "fps_is_30": True,
        "full_decode_passed": True,
        "resolution_is_1920x1080": True,
        "ten_scene_frames_extracted": True,
    }

    assert video_path == _project_member(qa["video_file"])
    assert contact_sheet_path == _project_member(qa["contact_sheet"])
    assert video_path.is_file()
    assert video_path.stat().st_size == 12_826_648
    assert _sha256(video_path) == expected_video_sha256
    assert video_path.read_bytes()[4:8] == b"ftyp"
    assert contact_sheet_path.is_file()
    assert contact_sheet_path.stat().st_size == 407_911
    assert _sha256(contact_sheet_path) == expected_contact_sheet_sha256
    assert contact_sheet_path.read_bytes()[:8] == b"\x89PNG\r\n\x1a\n"

    assert qa["resolution"] == [1920, 1080]
    assert qa["fps"] == 30.0
    assert qa["duration_seconds"] == 170.02
    assert qa["decode"] == {
        "decoded_frame_count": 5100,
        "errors": [],
        "exit_code": 0,
        "sample_timestamps_seconds": [
            6,
            21,
            39,
            57,
            76,
            95,
            114,
            133,
            150,
            164,
        ],
        "sampled_frame_count": 10,
    }
    assert qa["anonymity"] == {"forbidden_hits": []}
    assert qa["boundary"] == (
        "Synthetic local engineering demo; not customer, factory, production, "
        "hosted AgentTeams, or official submission evidence."
    )


def test_frozen_supply_chain_outputs_match_offline_regeneration(
    tmp_path: Path,
) -> None:
    generated_sbom = tmp_path / "SBOM.cdx.json"
    generated_inventory = tmp_path / "THIRD_PARTY_LICENSE_INVENTORY.generated.md"
    command = [
        sys.executable,
        str(PROJECT_ROOT / "tools" / "generate_supply_chain_artifacts.py"),
        "--project-root",
        str(PROJECT_ROOT),
        "--sbom",
        str(generated_sbom),
        "--inventory",
        str(generated_inventory),
    ]
    process = subprocess.run(
        command,
        cwd=PROJECT_ROOT,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="strict",
        timeout=60,
        check=False,
    )

    assert process.returncode == 0, process.stderr
    result = json.loads(process.stdout)
    frozen_sbom = PROJECT_ROOT / "docs" / "SBOM.cdx.json"
    frozen_inventory = (
        PROJECT_ROOT / "docs" / "THIRD_PARTY_LICENSE_INVENTORY.generated.md"
    )
    assert generated_sbom.read_bytes() == frozen_sbom.read_bytes()
    assert generated_inventory.read_bytes() == frozen_inventory.read_bytes()
    assert result == {
        "component_count": 55,
        "inventory_sha256": _sha256(frozen_inventory),
        "review_required_count": 0,
        "sbom_sha256": _sha256(frozen_sbom),
    }
