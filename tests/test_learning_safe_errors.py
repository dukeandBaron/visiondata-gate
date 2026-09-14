"""Workspace errors explain only allowlisted state, never arbitrary exceptions."""

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from visiondata_gate.learning_api import install_learning_routes
from visiondata_gate.learning_service import LearningError


@pytest.mark.parametrize(
    "reason,fragment",
    [
        ("EXECUTION_OWNER_ACTIVE", "仍在执行"),
        ("EXECUTION_OWNERSHIP_UNKNOWN", "旧版"),
        ("EXECUTION_LEASE_NOT_EXPIRED", "等待"),
        ("NOT_CURRENT_CANDIDATE", "候选"),
        ("CYCLE_BUDGET_EXHAUSTED", "预算"),
    ],
)
def test_known_learning_state_is_actionable_without_changing_error_code(
    reason, fragment
):
    app = FastAPI()
    install_learning_routes(app, lambda: None, lambda: None)

    @app.get("/test-error")
    def fail():
        raise LearningError(reason)

    with TestClient(app) as client:
        response = client.get("/test-error")
    assert response.status_code == 409
    assert response.json()["error"]["code"] == "learning_hold"
    assert fragment in response.json()["error"]["message"]
    assert response.headers["cache-control"] == "private, no-store"


def test_nonallowlisted_exception_is_never_echoed():
    app = FastAPI()
    install_learning_routes(app, lambda: None, lambda: None)

    @app.get("/test-error")
    def fail():
        raise LearningError("EXECUTION_OWNER_ACTIVE E:/private/path key=secret")

    with TestClient(app) as client:
        response = client.get("/test-error")
    assert response.status_code == 409
    assert "secret" not in response.text
    assert "E:/" not in response.text
    assert "仍在执行" not in response.text
