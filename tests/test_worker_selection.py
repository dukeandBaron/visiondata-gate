from __future__ import annotations

import pytest

from visiondata_gate.worker_selection import (
    AgentBehaviorReceiptV1,
    BlockingSeverity,
    MeasuredCostBucket,
    WorkerCandidate,
    build_agent_behavior_receipt,
    build_worker_selection_receipt,
    verify_agent_behavior_receipt,
    verify_worker_selection_receipt,
)


def _candidate(
    worker_id: str,
    *,
    eligible: bool = True,
    severity: BlockingSeverity = BlockingSeverity.WARNING,
    discrimination: int = 1,
    unresolved: int = 1,
    cost: MeasuredCostBucket = MeasuredCostBucket.MEDIUM,
) -> WorkerCandidate:
    return WorkerCandidate(
        worker_id=worker_id,
        eligible=eligible,
        ineligibility_reasons=[] if eligible else ["NOT_ALLOWLISTED"],
        blocking_severity=severity,
        discriminated_hypothesis_ids=[f"H-{index}" for index in range(discrimination)],
        unresolved_evidence_refs=[f"E-{index}" for index in range(unresolved)],
        measured_cost_bucket=cost,
    )


def test_selector_applies_eligibility_then_lexicographic_priority() -> None:
    candidates = [
        _candidate(
            "ineligible-high",
            eligible=False,
            severity=BlockingSeverity.BLOCKING,
            discrimination=9,
            unresolved=9,
            cost=MeasuredCostBucket.LOW,
        ),
        _candidate("warning-many", discrimination=4, unresolved=4),
        _candidate("blocking-expensive", severity=BlockingSeverity.BLOCKING),
        _candidate(
            "blocking-cheap",
            severity=BlockingSeverity.BLOCKING,
            cost=MeasuredCostBucket.LOW,
        ),
    ]

    receipt = build_worker_selection_receipt(candidates, worker_budget=2)

    assert receipt.selected_worker_ids == ["blocking-cheap", "blocking-expensive"]
    assert receipt.ranking[-1].worker_id == "ineligible-high"
    assert receipt.ranking[-1].eligible is False
    verify_worker_selection_receipt(receipt)


def test_selector_is_order_invariant_and_receipt_is_tamper_evident() -> None:
    candidates = [
        _candidate("worker-b"),
        _candidate("worker-a"),
        _candidate("worker-c"),
    ]

    first = build_worker_selection_receipt(candidates, worker_budget=1)
    second = build_worker_selection_receipt(list(reversed(candidates)), worker_budget=1)

    assert first == second
    assert first.selected_worker_ids == ["worker-a"]

    tampered = first.model_copy(update={"selected_worker_ids": ["worker-c"]})
    with pytest.raises(ValueError, match="disposition mismatch"):
        verify_worker_selection_receipt(tampered)


def test_selector_rejects_duplicate_worker_ids() -> None:
    with pytest.raises(ValueError, match="must be unique"):
        build_worker_selection_receipt(
            [_candidate("duplicate"), _candidate("duplicate")], worker_budget=1
        )


def test_agent_behavior_receipt_explains_selected_and_rejected_workers() -> None:
    candidates = [
        _candidate(
            "blocking",
            severity=BlockingSeverity.BLOCKING,
            discrimination=2,
            unresolved=2,
        ),
        _candidate("within-budget", discrimination=2, unresolved=1),
        _candidate("budget-rejected", discrimination=1, unresolved=1),
        _candidate("ineligible", eligible=False, unresolved=1),
    ]
    selection = build_worker_selection_receipt(candidates, worker_budget=2)

    behavior = build_agent_behavior_receipt(selection)

    assert isinstance(behavior, AgentBehaviorReceiptV1)
    assert behavior.source_selection_receipt_sha256 == selection.receipt_sha256
    assert behavior.digest_contract == "RFC8785_JCS_SHA256_LENGTH_PREFIX_DOMAIN_V1"
    assert behavior.selected_worker_ids == ["blocking", "within-budget"]
    assert behavior.rejected_worker_ids == ["budget-rejected", "ineligible"]
    assert behavior.worker_budget == 2
    assert behavior.used_worker_budget == 2
    assert behavior.unused_worker_budget == 0
    assert behavior.eligible_worker_count == 3
    assert behavior.selected[0].reason_codes == [
        "ELIGIBLE_BY_POLICY",
        "SELECTED_WITHIN_WORKER_BUDGET",
    ]
    rejected = {item.worker_id: item for item in behavior.rejected}
    assert rejected["budget-rejected"].reason_codes == ["WORKER_BUDGET_EXHAUSTED"]
    assert rejected["ineligible"].reason_codes == ["NOT_ALLOWLISTED"]
    assert all(item.evidence_refs for item in (*behavior.selected, *behavior.rejected))
    assert all(
        item.discriminated_hypothesis_ids
        for item in (*behavior.selected, *behavior.rejected)
    )
    assert behavior.evidence_ref_count == 2
    assert behavior.execution_outcomes_included is False
    assert behavior.model_decision_authority is False
    assert behavior.production_release_allowed is False
    verify_agent_behavior_receipt(behavior, selection=selection)


def test_agent_behavior_receipt_is_order_stable_and_tamper_evident() -> None:
    candidates = [
        _candidate("worker-b"),
        _candidate("worker-a"),
        _candidate("worker-c", eligible=False),
    ]
    first_selection = build_worker_selection_receipt(candidates, worker_budget=1)
    second_selection = build_worker_selection_receipt(
        list(reversed(candidates)), worker_budget=1
    )
    first = build_agent_behavior_receipt(first_selection)
    second = build_agent_behavior_receipt(second_selection)

    assert first == second

    tampered = first.model_copy(update={"worker_budget": 2})
    with pytest.raises(ValueError, match="deterministic replay"):
        verify_agent_behavior_receipt(tampered, selection=first_selection)


@pytest.mark.parametrize("invalid_budget", [True, 1.0, "1"])
def test_selector_rejects_non_integer_worker_budget(invalid_budget: object) -> None:
    with pytest.raises(ValueError, match="non-negative integer"):
        build_worker_selection_receipt(
            [_candidate("worker-a")],
            worker_budget=invalid_budget,  # type: ignore[arg-type]
        )


def test_behavior_receipt_reconciles_zero_and_unused_worker_budget() -> None:
    empty_selection = build_worker_selection_receipt([], worker_budget=0)
    empty_behavior = build_agent_behavior_receipt(empty_selection)
    assert empty_behavior.used_worker_budget == 0
    assert empty_behavior.unused_worker_budget == 0
    assert empty_behavior.selected == []
    assert empty_behavior.rejected == []
    verify_agent_behavior_receipt(empty_behavior, selection=empty_selection)

    oversized_selection = build_worker_selection_receipt(
        [_candidate("only-worker")], worker_budget=3
    )
    oversized_behavior = build_agent_behavior_receipt(oversized_selection)
    assert oversized_behavior.used_worker_budget == 1
    assert oversized_behavior.unused_worker_budget == 2
    verify_agent_behavior_receipt(oversized_behavior, selection=oversized_selection)


def test_worker_id_is_ascii_safe_for_cross_runtime_tie_breaking() -> None:
    with pytest.raises(ValueError):
        _candidate("工作器")
