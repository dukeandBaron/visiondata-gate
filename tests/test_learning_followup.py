import pytest

from tests import test_learning_lifecycle as support
from visiondata_gate.learning_service import LearningError, LearningService

learning_input = support.learning_input


def test_feedback_links_exact_new_gate_members_without_claiming_issue_closed(
    learning_input,
):
    from visiondata_gate.learning_contracts import FeedbackFollowup

    client, product, (task_id, preflight, groups) = learning_input
    service = LearningService(product)
    cycle, run = support.create_and_run(service, task_id, preflight, groups)
    assert run["status"] == "COMPLETED", run
    assert run["feedback"]
    cycle = support.review_and_select(service, cycle["cycle_id"], run)
    task2, preflight2, groups2 = support.make_task(
        client,
        product,
        project_id=cycle["project_id"],
        variant=2,
        previous_task_id=task_id,
        previous_groups=groups,
    )
    run = service.get_run(support.ACTOR, run["run_id"])
    members = product._annotation_context(support.ACTOR, task2)[2].samples
    new_ids = [member.sample_id for member in members if member.sample_id not in groups]
    payload = FeedbackFollowup(
        request_key="feedback-followup-001",
        expected_cycle_sha256=cycle["receipt_sha256"],
        expected_run_sha256=run["receipt_sha256"],
        review_note="Reviewed newly collected synthetic members addressing model error",
        operator_attests_reviewed=True,
        task_id=task2,
        expected_preflight_sha256=preflight2["receipt_sha256"],
        sample_ids=new_ids,
    )
    item = run["feedback"][0]
    updated = service.link_feedback(
        support.ACTOR, cycle["cycle_id"], run["run_id"], item["feedback_id"], payload
    )
    linked = updated["feedback"][0]["followup"]
    assert linked["binding"] == preflight2["binding"]
    assert set(linked["sample_ids"]) == set(new_ids)
    assert linked["issue_closed"] is False
    assert linked["training_ingestion_allowed"] is False
    assert (
        updated["feedback"][0]["followup_status"]
        == "NEW_GATE_EVIDENCE_LINKED_NOT_ISSUE_CLOSED"
    )
    assert (
        service.link_feedback(
            support.ACTOR,
            cycle["cycle_id"],
            run["run_id"],
            item["feedback_id"],
            payload,
        )
        == updated
    )
    current = service.get_cycle(support.ACTOR, cycle["cycle_id"])
    with pytest.raises(LearningError, match="FOLLOWUP_MEMBER_UNKNOWN"):
        service.link_feedback(
            support.ACTOR,
            cycle["cycle_id"],
            run["run_id"],
            item["feedback_id"],
            payload.model_copy(
                update={
                    "request_key": "bad-feedback-member-002",
                    "sample_ids": ["not-a-real-member"],
                    "expected_cycle_sha256": current["receipt_sha256"],
                    "expected_run_sha256": updated["receipt_sha256"],
                }
            ),
        )
    from visiondata_gate.learning_contracts import RunLearningRound

    current = service.get_cycle(support.ACTOR, cycle["cycle_id"])
    next_run = service.run_round(
        support.ACTOR,
        cycle["cycle_id"],
        RunLearningRound(
            request_key="explicit-feedback-next-round",
            task_id=task2,
            groups=groups2,
            expected_preflight_sha256=preflight2["receipt_sha256"],
            expected_cycle_sha256=current["receipt_sha256"],
            responds_to_feedback_ids=[item["feedback_id"]],
            operator_attests_training_authorized=True,
            review_note="Explicitly train the new Gate-bound members associated with this feedback",
        ),
    )
    assert next_run["status"] == "COMPLETED", next_run
    assert next_run["responds_to_feedback_ids"] == [item["feedback_id"]]
    assert linked["issue_closed"] is False
