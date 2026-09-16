from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
WEB = ROOT / "web" / "src"


def _read(path: str) -> str:
    return (WEB / path).read_text(encoding="utf-8")


def test_review_first_screen_uses_persisted_facts_for_four_responsibilities() -> None:
    review = _read("pages/ReviewPage.tsx")

    assert "TaskResponsibilityRail" in review
    for label in ("Agent 组织", "确定性工具", "具名人员", "系统回读"):
        assert label in review
    for fact in (
        "workerSelection",
        "completedToolEvents",
        "humanReviewReceipt",
        "live.readiness",
    ):
        assert fact in review
    assert review.count('"UNKNOWN" as const') >= 4


def test_capa_replaces_the_old_duplicate_flow_with_request_readback_states() -> None:
    workbench = _read("components/ControlledCapaWorkbench.tsx")

    assert "CapaRequestReadbackRail" in workbench
    for state in (
        "NOT_REQUESTED",
        "REQUEST_UNKNOWN",
        "SERVER_VERIFIED",
        "READBACK_VERIFIED",
    ):
        assert state in workbench
    assert "WRITE RESULT UNKNOWN / HOLD" in workbench
    assert "不会自动重放" in workbench
    assert "unknownMutationTaskRef" in workbench
    assert "reconciledTaskIds.has(unknownMutationTaskRef.current)" in workbench
    assert 'className="controlled-capa-flow"' not in workbench


def test_runs_exposes_recovery_actions_without_promoting_human_review_to_pass() -> None:
    runs = _read("pages/RunsPage.tsx")

    assert "RunRecoveryRail" in runs
    for state in (
        "WAITING",
        "UNKNOWN",
        "BLOCKED",
        "HUMAN_REVIEW",
    ):
        assert state in runs
    assert "/platform?task=" in runs
    assert "/integrations" in runs
    assert "/capa?task=" in runs
    assert "READY_FOR_HUMAN_REVIEW" not in runs.split(
        "function statusTone", 1
    )[1].split("function isActiveTask", 1)[0].split("return \"success\"", 1)[0]


def test_compact_rails_reuse_existing_tokens_and_are_not_card_grids() -> None:
    component = _read("components/FinalsTaskRails.tsx")
    styles = _read("styles/index.css")

    assert "StatusBadge" in component
    assert "finals-task-rail" in component
    assert "finals-task-rail" in styles
    assert "var(--" in styles
    rail_styles = styles.split(".finals-task-rail {", 1)[1].split(".capa-readback-rail {", 1)[0]
    assert "display: flex" in rail_styles
    assert "repeat(4" not in rail_styles


def test_identity_login_pattern_is_valid_under_modern_html_unicode_sets() -> None:
    access = _read("components/IdentityAccessScreen.tsx")

    assert 'pattern={"[A-Za-z0-9][A-Za-z0-9._\\\\-]{2,63}"}' in access
    assert 'pattern="[A-Za-z0-9][A-Za-z0-9._-]{2,63}"' not in access


def test_review_slice_uses_accessible_contrast_and_non_nested_landmarks() -> None:
    review = _read("pages/ReviewPage.tsx")
    ui = _read("components/ui.tsx")
    styles = _read("styles/index.css")

    assert '<aside className="review-case-briefing"' not in review
    assert '<aside className={`claim-boundary' not in ui
    assert ".linear-samples summary," in styles
    assert "color: var(--muted-2);" in styles
