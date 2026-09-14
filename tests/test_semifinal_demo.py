from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys

import pytest

from visiondata_gate.evidence import canonical_json_bytes
from tools.verify_semifinal_demo_manifest import (
    ManifestContractError,
    verify_manifest,
    verify_product_state,
)


PROJECT_ROOT = Path(__file__).resolve().parents[1]
PREPARE_TOOL = PROJECT_ROOT / "tools" / "prepare_semifinal_demo.py"
UI_CHECK_TOOL = PROJECT_ROOT / "tools" / "check_semifinal_review_ui.mjs"


def _prepare(product_root: Path) -> dict[str, object]:
    environment = os.environ.copy()
    environment["PYTHONPATH"] = str(PROJECT_ROOT / "src")
    completed = subprocess.run(
        [
            sys.executable,
            str(PREPARE_TOOL),
            "--product-root",
            str(product_root),
        ],
        cwd=PROJECT_ROOT,
        env=environment,
        check=True,
        capture_output=True,
        text=True,
        encoding="utf-8",
        timeout=120,
    )
    return json.loads(completed.stdout)


def test_semifinal_demo_preparation_is_idempotent_and_fail_closed(
    tmp_path: Path,
) -> None:
    product_root = tmp_path / "isolated-product"

    first = _prepare(product_root)
    second = _prepare(product_root)

    assert second == first
    assert first["status"] == "PASS_LOCAL_DEMO_PREPARED"
    assert first["source_scope"] == "SYNTHETIC_FIXTURE_REPLAY_ONLY"
    assert first["project_source_kind"] == "synthetic_demo"
    assert first["task_execution_status"] == "COMPLETED"
    assert first["task_final_decision"] == "PASS"
    assert first["task_release_readiness_status"] == "DEMO_ONLY"
    assert len(first["task_release_readiness_sha256"]) == 64
    assert set(first["task_release_readiness_sha256"]) <= set("0123456789abcdef")
    assert first["review_start_path"] == f"/review?task={first['task_id']}"
    assert first["decision_kind"] == "CONTINUE_HOLD"
    assert first["child_incident_status"] == "INVESTIGATION_REQUIRED"
    assert first["child_incident_recommendation"] == "CONTINUE_HOLD"
    assert first["interaction_status"] == "RESUMED_WITH_OPEN_QUESTIONS"
    assert first["remaining_open_question_count"] == 1
    assert first["production_release_allowed"] is False
    assert first["machine_write_permitted"] is False
    assert first["customer_validation"] == "NOT_CLAIMED"
    assert first["factory_shadow_metrics"] == "NOT_MEASURED_PENDING_ADJUDICATION"
    assert len(first["visual_assets"]) == 2

    stable = {key: value for key, value in first.items() if key != "manifest_sha256"}
    assert (
        first["manifest_sha256"]
        == hashlib.sha256(canonical_json_bytes(stable)).hexdigest()
    )

    manifest_path = product_root / "semifinal_demo_manifest.json"
    assert json.loads(manifest_path.read_text(encoding="utf-8")) == first
    verified = verify_manifest(
        first,
        manifest_path=manifest_path,
        expected_product_root=product_root,
    )
    assert verify_product_state(verified) == first

    preview_path = (
        product_root
        / "operator_workspace"
        / str(first["actor_user_id"])
        / str(first["workspace_id"])
        / str(first["visual_assets"][0]["asset_id"])
        / "preview.jpg"
    )
    preview_bytes = preview_path.read_bytes()
    preview_path.write_bytes(preview_bytes + b"drift")
    with pytest.raises(ManifestContractError, match="failed closed"):
        verify_product_state(first)
    preview_path.write_bytes(preview_bytes)
    assert verify_product_state(first) == first


def test_semifinal_manifest_verifier_rejects_boundary_or_digest_drift(
    tmp_path: Path,
) -> None:
    product_root = tmp_path / "isolated-product"
    manifest = _prepare(product_root)

    production_drift = {**manifest, "production_release_allowed": True}
    with pytest.raises(ManifestContractError, match="must remain false"):
        verify_manifest(production_drift, expected_product_root=product_root)

    digest_drift = {**manifest, "remaining_open_question_count": 0}
    with pytest.raises(ManifestContractError, match="exactly one open question"):
        verify_manifest(digest_drift, expected_product_root=product_root)


def test_semifinal_launcher_uses_isolated_review_mode() -> None:
    launcher = (PROJECT_ROOT / "run_semifinal_demo.ps1").read_text(encoding="utf-8")
    workbench = (PROJECT_ROOT / "run_workbench.ps1").read_text(encoding="utf-8")
    api = (PROJECT_ROOT / "run_api.ps1").read_text(encoding="utf-8")

    assert "prepare_semifinal_demo.py" in launcher
    assert "verify_semifinal_demo_manifest.py" in launcher
    assert 'task_release_readiness_status -ne "DEMO_ONLY"' in launcher
    assert 'child_incident_recommendation -ne "CONTINUE_HOLD"' in launcher
    assert "--expected-product-root $ResolvedProductRoot" in launcher
    assert "$ManifestJson | ConvertFrom-Json" in launcher
    assert "$EffectiveInstall = $Install.IsPresent -or -not" in launcher
    assert "-Install:$EffectiveInstall" in launcher
    assert "-StartPath $ReviewStartPath" in launcher
    assert "-ProductRoot $ResolvedProductRoot" in launcher
    assert "API port $ApiPort is already in use" in workbench
    assert "Web port $WebPort is already in use" in workbench
    assert "StartPath must target /workspace or /review" in workbench
    assert "$env:VISIONDATA_PRODUCT_ROOT = $ResolvedProductRoot" in api


def test_semifinal_review_css_keeps_narrow_layout_bounded() -> None:
    styles = (PROJECT_ROOT / "web" / "src" / "styles" / "index.css").read_text(
        encoding="utf-8"
    )
    narrow_start = styles.index("@media (max-width: 1080px)")
    mobile_start = styles.index("@media (max-width: 720px)", narrow_start)
    narrow_rules = styles[narrow_start:mobile_start]
    mobile_rules = styles[mobile_start:]

    assert "repeat(6, minmax(0, 1fr))" not in narrow_rules
    assert ".review-checkpoints { grid-template-columns: repeat(2" in narrow_rules
    assert "@media (max-width: 900px)" in narrow_rules
    assert (
        "grid-template-rows: var(--topbar-height) minmax(0, 1fr) 24px" in narrow_rules
    )
    assert ".linear-shell.is-review-route .linear-sidebar" in mobile_rules
    assert ".review-checkpoints {\n    grid-template-columns: 1fr;" in mobile_rules
    assert ".review-brief__header > div:first-child" in mobile_rules
    assert ".linear-statusbar__scope" in mobile_rules
    assert ".review-page .digest button" in mobile_rules


def test_semifinal_review_ui_checker_exposes_zero_dependency_cdp_contract() -> None:
    source = UI_CHECK_TOOL.read_text(encoding="utf-8")

    assert "--url <url>" in source
    assert "--manifest <path>" in source
    assert "--output <path>" in source
    assert "--runs <count>" in source
    assert "--viewports <list>" in source
    assert "390x844,720x900,1036x768,1366x768" in source
    assert "--remote-debugging-port=0" in source
    assert "DevToolsActivePort" in source
    assert "new WebSocket(url)" in source
    assert 'client.send("Page.captureScreenshot"' in source
    assert "computed_column_count" in source
    assert "expected_column_count" in source
    assert "if (width <= 720) return 1" in source
    assert "if (width <= 860) return 2" in source
    assert "if (width <= 1280) return 3" in source
    assert "clipped_item_indices" in source
    assert "below_44px_count" in source
    assert "target_contract_pass" in source
    assert "viewport.width > 720 || layout.controls.below_44px_count === 0" in source
    assert "asset_bundle_sha256" in source
    assert "declared_manifest_sha256" in source
    assert 'task_final_decision: "PASS"' in source
    assert 'task_release_readiness_status: "DEMO_ONLY"' in source
    assert '"task_release_readiness_sha256"' in source
    assert '"task_evidence_sha256",\n    "task_release_readiness_sha256",' in source
    assert 'decision_kind: "CONTINUE_HOLD"' in source
    assert 'child_incident_status: "INVESTIGATION_REQUIRED"' in source
    assert 'child_incident_recommendation: "CONTINUE_HOLD"' in source
    assert '"#dynamicbench-evidence"' in source
    assert '"PASS_LOCAL_EVIDENCE"' in source
    assert '"#semifinal-manifest-evidence"' in source
    assert '"PASS_LOCAL_DEMO_VERIFIED"' in source
    assert '"CHAIN VERIFIED"' in source
    assert '"OUTCOME · HOLD"' in source
    assert "narrative_order_verified" in source
    assert "expectedManifestSha256" in source
    assert "manifest_sha256_visible" in source
    assert 'new URL("/cases", targetUrl)' in source
    assert '".incident-authority-bridge"' in source
    assert '"RECEIPTS VERIFIED"' in source
    assert '".incident-authority-bridge--unavailable"' in source
    assert "authority_case" in source
    assert "authority_screenshot" in source
    assert '"authority-case.png"' in source
    assert "task_final_decision: payload.task_final_decision" in source
    assert (
        "task_release_readiness_sha256: payload.task_release_readiness_sha256" in source
    )
    assert "decision_kind: payload.decision_kind" in source
    assert "child_incident_status: payload.child_incident_status" in source
    assert (
        "child_incident_recommendation: payload.child_incident_recommendation" in source
    )
    assert "taskkill.exe" in source
    assert "taskkill_exact_pid_tree" in source
    assert "realpath(tmpdir())" in source
    assert "playwright" not in source.lower()
    assert "puppeteer" not in source.lower()


def test_review_projection_negative_checker_contract() -> None:
    source = UI_CHECK_TOOL.read_text(encoding="utf-8")

    assert "--review-projection-negative" in source
    assert "visiondata-gate.review-projection-negative-ui-receipt.v1" in source
    assert "review_projection_negative_ui_receipt.json" in source
    for scenario in (
        "MISSING_REASON_CODES",
        "BAD_AGENT_BEHAVIOR_SHA",
        "BAD_STRONG_ETAG",
        "NETWORK_INTERRUPTION",
        "STALE_RETENTION",
    ):
        assert f'id: "{scenario}"' in source
    for expected_status in (
        "CONTRACT_HOLD",
        "STALE_HOLD",
        "RETRYABLE_UNAVAILABLE",
    ):
        assert f'expectedStatus: "{expected_status}"' in source
    for expected_error in (
        "INVALID_INCIDENT_REVIEW_PROJECTION",
        "RESPONSE_ETAG_BINDING_DRIFT",
        "NETWORK_UNAVAILABLE",
        "INCIDENT_REVIEW_PROJECTION_SHA_DRIFT",
    ):
        assert f'expectedErrorCode: "{expected_error}"' in source
    assert "*/v1/tasks/*/industrial-incidents/*/review-projection" in source
    assert 'client.send("Network.enable")' in source
    assert 'client.on("Network.requestWillBeSent"' in source
    assert 'client.on("Network.loadingFailed"' in source
    assert 'client.send("Fetch.enable"' in source
    assert 'requestStage: "Response"' in source
    assert 'client.on("Fetch.requestPaused"' in source
    assert 'client.send("Fetch.getResponseBody"' in source
    assert 'client.send("Fetch.fulfillRequest"' in source
    assert 'client.send("Fetch.failRequest"' in source
    assert 'errorReason: "InternetDisconnected"' in source
    assert 'client.send("Fetch.disable")' in source
    assert "exact_match_count === 1" in source
    assert 'new Set(["POST", "PUT", "PATCH", "DELETE"])' in source
    assert '"STALE DISPLAY"' in source
    assert '"CURRENT PROJECTION"' in source
    assert '"STALE PROJECTION"' in source
    assert '"PASS_EXPECTED_FAIL_CLOSED"' in source
    assert '"PASS_LOCAL_REVIEW_PROJECTION_NEGATIVE_UI"' in source
    assert "expected_fail_closed_behavior_only: true" in source
    assert "production_release_allowed: false" in source
    assert "machine_write_permitted: false" in source
    assert "submission_eligible: false" in source
    assert "playwright" not in source.lower()
    assert "puppeteer" not in source.lower()


def test_semifinal_review_ui_checker_help_is_browser_independent() -> None:
    completed = subprocess.run(
        ["node", str(UI_CHECK_TOOL), "--help"],
        cwd=PROJECT_ROOT,
        check=False,
        capture_output=True,
        text=True,
        encoding="utf-8",
        timeout=20,
    )

    assert completed.returncode == 0
    assert "VisionData Gate semifinal review UI verifier" in completed.stdout
    assert "default: 390x844,720x900,1036x768,1366x768" in completed.stdout
    assert "--review-projection-negative" in completed.stdout
    assert completed.stderr == ""


def test_semifinal_review_ui_checker_always_writes_failure_receipt(
    tmp_path: Path,
) -> None:
    missing_manifest = tmp_path / "missing" / "semifinal_demo_manifest.json"
    output = tmp_path / "receipts" / "ui-failure.json"
    completed = subprocess.run(
        [
            "node",
            str(UI_CHECK_TOOL),
            "--manifest",
            str(missing_manifest),
            "--output",
            str(output),
            "--viewports",
            "560x844,720x900,900x900",
        ],
        cwd=PROJECT_ROOT,
        check=False,
        capture_output=True,
        text=True,
        encoding="utf-8",
        timeout=20,
    )

    assert completed.returncode == 2
    assert output.is_file()
    receipt = json.loads(output.read_text(encoding="utf-8"))
    assert json.loads(completed.stdout) == receipt
    assert receipt["schema_version"] == (
        "visiondata-gate.semifinal-review-ui-receipt.v1"
    )
    assert receipt["status"] == "FAIL_CLOSED"
    assert receipt["browser_runs"] == []
    assert receipt["boundaries"]["local_ui_verification_only"] is True
    assert receipt["boundaries"]["production_release_allowed"] is False
    assert receipt["boundaries"]["machine_write_permitted"] is False
    assert receipt["boundaries"]["submission_eligible"] is False
    assert "ENOENT" in receipt["errors"][0]

    stable = {key: value for key, value in receipt.items() if key != "receipt_sha256"}
    assert (
        receipt["receipt_sha256"]
        == hashlib.sha256(canonical_json_bytes(stable)).hexdigest()
    )


def test_semifinal_review_ui_negative_mode_writes_distinct_failure_receipt(
    tmp_path: Path,
) -> None:
    missing_manifest = tmp_path / "missing" / "semifinal_demo_manifest.json"
    output = tmp_path / "receipts" / "review-projection-negative-failure.json"
    completed = subprocess.run(
        [
            "node",
            str(UI_CHECK_TOOL),
            "--review-projection-negative",
            "--manifest",
            str(missing_manifest),
            "--output",
            str(output),
        ],
        cwd=PROJECT_ROOT,
        check=False,
        capture_output=True,
        text=True,
        encoding="utf-8",
        timeout=20,
    )

    assert completed.returncode == 2
    assert output.is_file()
    receipt = json.loads(output.read_text(encoding="utf-8"))
    assert json.loads(completed.stdout) == receipt
    assert receipt["schema_version"] == (
        "visiondata-gate.review-projection-negative-ui-receipt.v1"
    )
    assert receipt["mode"] == "REVIEW_PROJECTION_NEGATIVE"
    assert receipt["status"] == "FAIL_CLOSED"
    assert receipt["scenario_runs"] == []
    assert receipt["summary"]["required_scenario_count"] == 5
    assert receipt["boundaries"]["production_release_allowed"] is False
    assert receipt["boundaries"]["machine_write_permitted"] is False
    assert receipt["boundaries"]["submission_eligible"] is False
    assert "ENOENT" in receipt["errors"][0]

    stable = {key: value for key, value in receipt.items() if key != "receipt_sha256"}
    assert (
        receipt["receipt_sha256"]
        == hashlib.sha256(canonical_json_bytes(stable)).hexdigest()
    )
