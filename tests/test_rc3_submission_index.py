from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path, PurePosixPath
from typing import Any

from visiondata_gate.package import DEFAULT_SUBMISSION_REQUIRED_PATHS


PROJECT_ROOT = Path(__file__).resolve().parents[1]
INDEX_PATH = (
    PROJECT_ROOT
    / "evidence"
    / "submission"
    / "vdg-20260831-rc3"
    / "evidence_index.json"
)
EXPECTED_ARTIFACTS = {
    "10_reports/DYNAMICBENCH_V2_WORKER_SELECTION_20260828.json",
    "10_reports/DYNAMICBENCH_V3_REPLANNING_20260829.json",
    "10_reports/DYNAMICBENCH_V4_PRODUCT_RUNTIME_20260829.json",
    "10_reports/dynamic_vs_fixed_exhaustive_paired_comparison.json",
    "10_reports/dynamic_vs_fixed_rule_paired_comparison.json",
    "deliverables/GOAI_VisionDataGate_Semifinal_RC3_20260831.pdf",
    "deliverables/GOAI_VisionDataGate_Semifinal_RC3_20260831.pptx",
    "deliverables/VisionDataGate_GOAI_Semifinal_RC3_20260831.mp4",
    "deliverables/_qa/semifinal_rc3_video_contact_sheet_20260831.png",
    "deliverables/_qa/semifinal_rc3_video_qa_20260831.json",
    "docs/DEMO_90S_SCRIPT_RC3.md",
    "docs/GOAI_SEMIFINAL_OFFICIAL_FEEDBACK_CLOSURE_20260831.md",
    "evidence/submission/vdg-20260831-rc3/goal3/goal3_acceptance_summary.json",
}
FORBIDDEN_CURRENT_STATE_TEXT = (
    "DO_NOT_SUBMIT_RC3",
    "HOLD_AS_RELEASE_TREE",
    "NOT_RUN_AFTER_CURRENT_CHANGES",
    "COLLECT_ONLY_CURRENT_DIRTY_TREE",
    "release_state=NOT_FROZEN",
)


def _strict_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    value: dict[str, Any] = {}
    for key, item in pairs:
        assert key not in value, f"duplicate JSON member: {key}"
        value[key] = item
    return value


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _safe_project_member(value: str) -> Path:
    assert "\\" not in value
    relative = PurePosixPath(value)
    assert not relative.is_absolute()
    assert relative.parts
    assert all(part not in {"", ".", ".."} for part in relative.parts)
    assert ":" not in relative.parts[0]
    target = (PROJECT_ROOT / relative).resolve(strict=True)
    target.relative_to(PROJECT_ROOT)
    assert target.is_file()
    return target


def test_rc3_evidence_index_is_current_safe_and_byte_bound() -> None:
    raw = INDEX_PATH.read_text(encoding="utf-8")
    payload = json.loads(raw, object_pairs_hook=_strict_object)

    assert payload["schema_version"] == (
        "visiondata-gate.rc3-submission-evidence-index.v2"
    )
    assert payload["local_release_decision"] == ("PASS_LOCAL_RC3_RELEASE_CANDIDATE")
    assert payload["release_candidate_ready"] is True
    assert payload["submission_eligible"] is False
    assert payload["official_submission"] == "PENDING"
    assert payload["official_evaluation"] == "NOT_EVALUATED"
    assert payload["production_release_allowed"] is False
    assert payload["factory_shadow_metrics"] == ("NOT_MEASURED_PENDING_ADJUDICATION")
    assert not any(token in raw for token in FORBIDDEN_CURRENT_STATE_TEXT)

    artifacts = payload["artifacts"]
    assert isinstance(artifacts, list)
    paths = [item["path"] for item in artifacts]
    assert paths == sorted(paths)
    assert set(paths) == EXPECTED_ARTIFACTS
    assert len(paths) == len(set(paths))
    assert EXPECTED_ARTIFACTS <= set(DEFAULT_SUBMISSION_REQUIRED_PATHS)

    for artifact in artifacts:
        target = _safe_project_member(artifact["path"])
        assert artifact["bytes"] == target.stat().st_size
        assert re.fullmatch(r"[0-9a-f]{64}", artifact["sha256"])
        assert artifact["sha256"] == _sha256(target)
        assert isinstance(artifact["kind"], str) and artifact["kind"]
        assert isinstance(artifact["claim_boundary"], str)
        assert len(artifact["claim_boundary"]) >= 20

    release_binding = payload["release_binding"]
    assert release_binding == {
        "attestation_in_submission_zip": False,
        "candidate_zip_sha256": "BOUND_BY_DETACHED_RELEASE_ATTESTATION",
        "full_junit_sha256": "BOUND_BY_DETACHED_RELEASE_ATTESTATION",
        "git_commit_and_tree": "BOUND_BY_DETACHED_RELEASE_ATTESTATION",
        "verification_status_required": "PASS_LOCAL_INTEGRITY",
    }
    private = payload["private_pilot_evidence"]
    assert private["status"] == "WITHHELD_PUBLIC_EXPORT_NOT_AUTHORIZED"
    assert private["raw_receipts_packaged"] is False
    assert private["source_assets_packaged"] is False
