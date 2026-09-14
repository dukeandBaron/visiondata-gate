"""Exercise public incident command serialization without any model network call."""

import gc
import threading
from concurrent.futures import ThreadPoolExecutor

import pytest

from visiondata_gate.product_service import ProductService


@pytest.mark.parametrize("same_case", [False, True])
def test_resume_only_serializes_decision_for_its_own_case(
    tmp_path, monkeypatch, same_case
):
    service = ProductService(tmp_path / "product", recover_interrupted=False)
    resume_started, release_resume, decision_entered = (
        threading.Event() for _ in range(3)
    )

    def resume(*args, **kwargs):
        resume_started.set()
        assert release_resume.wait(5)
        return "resumed"

    def decision(*args, **kwargs):
        decision_entered.set()
        return "decided"

    monkeypatch.setattr(service, "_resume_industrial_incident_case", resume)
    monkeypatch.setattr(service, "_record_industrial_incident_decision", decision)
    try:
        with ThreadPoolExecutor(max_workers=2) as pool:
            first = pool.submit(
                service.resume_industrial_incident_case, "actor", "task", "case-a", None
            )
            assert resume_started.wait(2)
            second = pool.submit(
                service.record_industrial_incident_decision,
                "actor",
                "task",
                "case-a" if same_case else "case-b",
                None,
            )
            try:
                assert decision_entered.wait(0.5) is not same_case
            finally:
                release_resume.set()
            assert first.result(3) == "resumed"
            assert second.result(3) == "decided"
    finally:
        release_resume.set()
        service.close(wait=True)


def test_unused_case_locks_do_not_accumulate(tmp_path):
    service = ProductService(tmp_path / "product", recover_interrupted=False)
    try:
        for i in range(200):
            with service._incident_case_lock("task", f"case-{i}"):
                pass
        gc.collect()
        assert len(service._incident_case_locks) == 0
    finally:
        service.close(wait=True)
