from __future__ import annotations

from tools.check_public_pages import validate_manifest


def test_public_workbench_matches_sha_bound_replay_contract() -> None:
    receipt = validate_manifest()
    assert receipt["schema_version"] == "visiondata-gate.public-replay.v1"
    assert receipt["source_mode"] == "PUBLIC_SYNTHETIC_REPLAY"
    assert len(receipt["manifest_sha256"]) == 64
    assert receipt["production_release_allowed"] is False
