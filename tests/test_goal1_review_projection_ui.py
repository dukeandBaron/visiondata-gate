from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
WEB = ROOT / "web" / "src"


def _read(path: str) -> str:
    return (WEB / path).read_text(encoding="utf-8")


def test_review_projection_panel_consumes_goal2_read_contracts_fail_closed() -> None:
    panel = _read("components/IncidentReviewProjectionPanel.tsx")

    assert "readIndustrialIncidentReviewProjection" in panel
    assert "readControlledCapaCase" in panel
    assert "previousProjectionRef.current" in panel
    assert "previousCapaRef.current" in panel
    for status in (
        "VERIFIED",
        "NOT_CREATED",
        "STALE_HOLD",
        "RETRYABLE_UNAVAILABLE",
        "CONTRACT_HOLD",
    ):
        assert status in panel
    assert "STALE DISPLAY" in panel
    assert "不再视为 PASS" in panel
    assert "LOCAL API TRANSPORT" in panel
    assert "LIVE 仅表示当前本地 API 读取" in panel
    assert "FACTORY CONNECTION" in panel
    assert "NOT CLAIMED" in panel
    assert "REPLAY" in panel
    assert "OFFLINE_EXPORT" in panel
    assert "GET 对账" in panel
    assert "不会自动重放任何写请求" in panel
    assert "selectedWorkerTriggerReasons" in panel
    assert "trigger.worker_role" in panel
    assert (
        "triggerReasonCodes={selectedWorkerTriggerReasons.get(worker.worker_id)}"
        in panel
    )
    assert "TRIGGER REASONS" in panel
    assert "EXCLUSION REASONS" in panel

    for forbidden_write in (
        "selectControlledCapaPlan",
        "approveControlledCapaCase",
        "executeControlledCapaCase",
    ):
        assert forbidden_write not in panel


def test_reviewer_and_case_workbench_share_persisted_projection_surface() -> None:
    review = _read("pages/ReviewPage.tsx")
    workbench = _read("components/LiveIncidentWorkbench.tsx")
    panel = _read("components/IncidentReviewProjectionPanel.tsx")
    styles = _read("styles/incident-review-projection.css")

    assert "<IncidentReviewProjectionPanel" in review
    assert 'surface="reviewer"' in review
    assert "<IncidentReviewProjectionPanel" in workbench
    assert 'surface="workbench"' in workbench
    assert "initialProjection={scope.authoritySnapshot?.reviewProjection}" in workbench

    for persisted_fact in (
        "selected_workers",
        "rejected_workers",
        "triggering_evidence",
        "competing_hypotheses",
        "missing_evidence_refs",
        "what_would_change_decision",
        "parent_case",
        "human_decisions",
        "child_cases",
        "capa_cases",
        "task_lineage_nodes",
    ):
        assert persisted_fact in panel

    assert "capaMatchesProjection" in panel
    assert "CHAIN VERIFIED" in panel
    assert "Child Task · NOT_CREATED" in panel
    assert ".incident-review-source-rail" in styles
    assert ".incident-review-case-flow" in styles
    assert ":focus-visible" in styles
    assert "@media (prefers-reduced-motion: reduce)" in styles


def test_browser_runtime_probes_the_standard_same_origin_api_proxy() -> None:
    api = _read("data/api.ts")

    assert "configuredBrowserApiBaseUrl || window.location.origin" in api
    assert "`${runtime.apiBaseUrl}/v1/workspaces`" in api
    assert "runtimeAuthorizationHeaders(runtime)" in api


def test_reviewer_worker_reasons_and_live_replay_failures_are_recoverable() -> None:
    review = _read("pages/ReviewPage.tsx")
    workbench = _read("pages/CaseWorkbenchPage.tsx")
    projection = _read("components/IncidentReviewProjectionPanel.tsx")
    domain = _read("agentDomain.ts")
    api = _read("data/api.ts")

    assert "receipt: incident?.worker_receipts.find" in review
    assert "receipt?.trigger_reason_codes.length" in review
    assert "receipt.trigger_reason_codes.join" in review
    assert "按确定性策略入选" not in review

    assert "reason_codes: string[];" in domain
    assert "agent_behavior_receipt_sha256: string;" in domain
    assert "isStringArray(value.reason_codes)" in api
    assert "isSha256(value.agent_behavior_receipt_sha256)" in api
    assert "SELECTION POLICY REASONS" in projection
    assert "worker.reason_codes.map" in projection
    assert "EXECUTION TRIGGER REASONS" in projection
    assert "projection.agent_behavior_receipt_sha256" in projection

    assert "replayRefreshToken" in workbench
    assert "setReplayRefreshToken((value) => value + 1)" in workbench
    assert "重试只读回放 GET" in workbench


def test_reviewer_mobile_actions_keep_44px_touch_targets() -> None:
    review_styles = _read("styles/index.css")
    projection_styles = _read("styles/incident-review-projection.css")

    assert (
        """  .review-page .review-case-question > button {
    min-height: 44px;
  }"""
        in review_styles
    )
    assert (
        """@media (max-width: 720px) {
  .incident-review-projection--reviewer .incident-review-projection__heading-actions button,
  .incident-review-projection--reviewer .incident-review-no-projection > button {
    min-height: 44px;
  }
}"""
        in projection_styles
    )
