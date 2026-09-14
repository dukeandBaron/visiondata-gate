"""Thin authenticated HTTP routes for the governed local learning service."""

from __future__ import annotations

from collections.abc import Callable
import re

from fastapi import Depends, FastAPI, Request, Response
from fastapi.responses import JSONResponse

from .learning_contracts import (
    CreateLearningCycle,
    CycleAction,
    FeedbackReview,
    FeedbackFollowup,
    ModelSelection,
    RollbackModel,
    RunLearningRound,
)
from .continual_learning import ContinualRetentionEvaluationRequest
from .learning_dataset import DatasetError
from .learning_service import LearningError, LearningService
from .learning_projection import learning_readiness
from .learning_operations import read_learning_operation


_SAFE_LEARNING_MESSAGES = {
    "EXECUTION_OWNER_ACTIVE": "该周期仍在执行，请等待并刷新结果；不要重复训练或强制恢复。",
    "EXECUTION_OWNERSHIP_UNKNOWN": "旧版周期缺少执行归属凭证，无法证明任务已停止；请保留数据并核查运行进程。",
    "EXECUTION_OWNERSHIP_INVALID": "执行归属凭证不匹配，已暂停恢复；请保留当前证据进行核查。",
    "EXECUTION_LEASE_NOT_EXPIRED": "训练保护时限尚未结束，请等待后刷新；系统没有重放训练。",
    "NOT_CURRENT_CANDIDATE": "该运行不是可选择的已完成候选；请刷新当前轮次与评测结果。",
    "CYCLE_BUDGET_EXHAUSTED": "周期剩余预算不足，不能启动下一轮；已有失败尝试仍计入预算。",
    "STALE_CYCLE": "周期已发生变化，请刷新当前结果后重新确认操作。",
    "STALE_RUN": "运行回执已变化，请重新读取并复核当前候选。",
}


def _bind_receipt(value: dict, response: Response) -> dict:
    digest = value.get("receipt_sha256")
    if not isinstance(digest, str) or re.fullmatch(r"[0-9a-f]{64}", digest) is None:
        raise LearningError("LEARNING_RESPONSE_RECEIPT_INVALID")
    response.headers["ETag"] = f'"{digest}"'
    response.headers["X-Content-SHA256"] = digest
    response.headers["Cache-Control"] = "private, no-store"
    return value


def install_learning_routes(
    app: FastAPI,
    actor_dependency: Callable,
    product_dependency: Callable,
) -> None:
    """Reuse the host's authenticated principal and scoped ProductService.

    Registration does not instantiate LearningService or touch its storage.
    NotFoundError deliberately propagates to the host's existing 404 handler.
    """

    @app.exception_handler(LearningError)
    def learning_error(_request: Request, _error: LearningError) -> JSONResponse:
        return JSONResponse(
            status_code=409,
            headers={"Cache-Control": "private, no-store"},
            content={
                "error": {
                    "code": "learning_hold",
                    "message": _SAFE_LEARNING_MESSAGES.get(
                        str(_error),
                        "the learning operation could not satisfy its current authority or evidence contract",
                    ),
                }
            },
        )

    @app.exception_handler(DatasetError)
    def dataset_error(_request: Request, _error: DatasetError) -> JSONResponse:
        return JSONResponse(
            status_code=409,
            headers={"Cache-Control": "private, no-store"},
            content={
                "error": {
                    "code": "learning_dataset_hold",
                    "message": "the learning dataset did not satisfy its integrity or split contract",
                }
            },
        )

    @app.post("/v1/tasks/{task_id}/learning-cycles", status_code=201, tags=["learning"])
    def create_learning_cycle(
        task_id: str,
        request: CreateLearningCycle,
        response: Response,
        actor: str = Depends(actor_dependency),
        product=Depends(product_dependency),
    ) -> dict:
        return _bind_receipt(
            LearningService(product).create_cycle(actor, task_id, request), response
        )

    @app.get("/v1/tasks/{task_id}/learning-readiness", tags=["learning"])
    def read_learning_readiness(
        task_id: str,
        response: Response,
        actor: str = Depends(actor_dependency),
        product=Depends(product_dependency),
    ) -> dict:
        return _bind_receipt(learning_readiness(product, actor, task_id), response)

    @app.get(
        "/v1/projects/{project_id}/learning-operations/{operation}/{request_key}",
        tags=["learning"],
    )
    def get_learning_operation(
        project_id: str,
        operation: str,
        request_key: str,
        target_id: str,
        response: Response,
        actor: str = Depends(actor_dependency),
        product=Depends(product_dependency),
    ) -> dict:
        return _bind_receipt(
            read_learning_operation(
                product, actor, project_id, operation, request_key, target_id
            ),
            response,
        )

    @app.get("/v1/projects/{project_id}/learning-cycles", tags=["learning"])
    def list_project_learning_cycles(
        project_id: str,
        response: Response,
        actor: str = Depends(actor_dependency),
        product=Depends(product_dependency),
    ) -> list[dict]:
        result = LearningService(product).list_cycles(actor, project_id)
        response.headers["Cache-Control"] = "private, no-store"
        return result

    @app.post(
        "/v1/projects/{project_id}/continual-retention/evaluations",
        status_code=201,
        tags=["learning", "governance"],
    )
    def evaluate_continual_retention(
        project_id: str,
        request: ContinualRetentionEvaluationRequest,
        response: Response,
        actor: str = Depends(actor_dependency),
        product=Depends(product_dependency),
    ) -> dict:
        return _bind_receipt(
            LearningService(product).evaluate_continual_retention(
                actor, project_id, request
            ),
            response,
        )

    @app.get(
        "/v1/projects/{project_id}/continual-retention/evaluations/{receipt_sha256}",
        tags=["learning", "governance"],
    )
    def get_continual_retention(
        project_id: str,
        receipt_sha256: str,
        response: Response,
        actor: str = Depends(actor_dependency),
        product=Depends(product_dependency),
    ) -> dict:
        return _bind_receipt(
            LearningService(product).get_continual_retention(
                actor, project_id, receipt_sha256
            ),
            response,
        )

    @app.get("/v1/learning-cycles/{cycle_id}", tags=["learning"])
    def get_learning_cycle(
        cycle_id: str,
        response: Response,
        actor: str = Depends(actor_dependency),
        product=Depends(product_dependency),
    ) -> dict:
        return _bind_receipt(
            LearningService(product).get_cycle(actor, cycle_id), response
        )

    @app.post("/v1/learning-cycles/{cycle_id}/rounds", tags=["learning"])
    def run_learning_round(
        cycle_id: str,
        request: RunLearningRound,
        response: Response,
        actor: str = Depends(actor_dependency),
        product=Depends(product_dependency),
    ) -> dict:
        return _bind_receipt(
            LearningService(product).run_round(actor, cycle_id, request), response
        )

    @app.get("/v1/learning-runs/{run_id}", tags=["learning"])
    def get_learning_run(
        run_id: str,
        response: Response,
        actor: str = Depends(actor_dependency),
        product=Depends(product_dependency),
    ) -> dict:
        return _bind_receipt(LearningService(product).get_run(actor, run_id), response)

    @app.get("/v1/learning-models/{model_id}", tags=["learning"])
    def get_learning_model(
        model_id: str,
        response: Response,
        actor: str = Depends(actor_dependency),
        product=Depends(product_dependency),
    ) -> dict:
        # get_model validates the model bytes, not merely its database record.
        return _bind_receipt(
            LearningService(product).get_model(actor, model_id), response
        )

    @app.post(
        "/v1/learning-cycles/{cycle_id}/runs/{run_id}/selection", tags=["learning"]
    )
    def select_learning_model(
        cycle_id: str,
        run_id: str,
        request: ModelSelection,
        response: Response,
        actor: str = Depends(actor_dependency),
        product=Depends(product_dependency),
    ) -> dict:
        return _bind_receipt(
            LearningService(product).select_model(actor, cycle_id, run_id, request),
            response,
        )

    @app.post(
        "/v1/learning-cycles/{cycle_id}/runs/{run_id}/feedback/{feedback_id}",
        tags=["learning"],
    )
    def review_learning_feedback(
        cycle_id: str,
        run_id: str,
        feedback_id: str,
        request: FeedbackReview,
        response: Response,
        actor: str = Depends(actor_dependency),
        product=Depends(product_dependency),
    ) -> dict:
        return _bind_receipt(
            LearningService(product).review_feedback(
                actor, cycle_id, run_id, feedback_id, request
            ),
            response,
        )

    @app.post("/v1/learning-cycles/{cycle_id}/rollback", tags=["learning"])
    def rollback_learning_model(
        cycle_id: str,
        request: RollbackModel,
        response: Response,
        actor: str = Depends(actor_dependency),
        product=Depends(product_dependency),
    ) -> dict:
        return _bind_receipt(
            LearningService(product).rollback(actor, cycle_id, request), response
        )

    @app.post(
        "/v1/learning-cycles/{cycle_id}/runs/{run_id}/feedback/{feedback_id}/followup",
        tags=["learning"],
    )
    def link_learning_feedback(
        cycle_id: str,
        run_id: str,
        feedback_id: str,
        request: FeedbackFollowup,
        response: Response,
        actor: str = Depends(actor_dependency),
        product=Depends(product_dependency),
    ) -> dict:
        return _bind_receipt(
            LearningService(product).link_feedback(
                actor, cycle_id, run_id, feedback_id, request
            ),
            response,
        )

    @app.post("/v1/learning-cycles/{cycle_id}/cancel", tags=["learning"])
    def cancel_learning_cycle(
        cycle_id: str,
        request: CycleAction,
        response: Response,
        actor: str = Depends(actor_dependency),
        product=Depends(product_dependency),
    ) -> dict:
        return _bind_receipt(
            LearningService(product).cancel(actor, cycle_id, request), response
        )

    @app.post("/v1/learning-cycles/{cycle_id}/recover", tags=["learning"])
    def recover_learning_cycle(
        cycle_id: str,
        request: CycleAction,
        response: Response,
        actor: str = Depends(actor_dependency),
        product=Depends(product_dependency),
    ) -> dict:
        return _bind_receipt(
            LearningService(product).recover(actor, cycle_id, request), response
        )

    @app.post("/v1/learning-cycles/{cycle_id}/finalize", tags=["learning"])
    def finalize_learning_cycle(
        cycle_id: str,
        request: CycleAction,
        response: Response,
        actor: str = Depends(actor_dependency),
        product=Depends(product_dependency),
    ) -> dict:
        return _bind_receipt(
            LearningService(product).finalize(actor, cycle_id, request), response
        )
