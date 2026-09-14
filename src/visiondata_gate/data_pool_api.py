"""Authenticated FastAPI routes for governed Data Pool v1."""

from __future__ import annotations

from collections.abc import Callable
import re

from fastapi import Depends, FastAPI, Request, Response
from fastapi.responses import JSONResponse

from .data_pool import (
    CreateDataPoolRequest,
    CreateDataPoolVersionRequest,
    DataPoolError,
    DataPoolService,
    DeriveDataPoolVersionRequest,
)


_SAFE_MESSAGES = {
    "STALE_READINESS": "数据证据已经变化，请刷新后重新逐项复核。",
    "STALE_DATA_POOL": "数据池证据已经变化，请刷新当前版本。",
    "STALE_DATA_POOL_VERSION": "数据池版本已经变化，请刷新后重新确认。",
    "QUALIFICATION_REQUIRES_MEMBER_EVIDENCE": (
        "该成员缺少可核验的合格依据，已保持返修或待调查状态。"
    ),
    "SOURCE_AUTHORIZATION_INACTIVE": "来源授权已失效，数据池操作已停止。",
    "IDEMPOTENCY_CONFLICT": "同一请求键对应不同内容，操作已拒绝。",
}


def _bind(value: dict, response: Response) -> dict:
    digest = value.get("receipt_sha256")
    if not isinstance(digest, str) or re.fullmatch(r"[0-9a-f]{64}", digest) is None:
        raise DataPoolError("DATA_POOL_RESPONSE_INTEGRITY_HOLD")
    response.headers["ETag"] = f'"{digest}"'
    response.headers["X-Content-SHA256"] = digest
    response.headers["Cache-Control"] = "private, no-store"
    return value


def install_data_pool_routes(
    app: FastAPI,
    actor_dependency: Callable,
    product_dependency: Callable,
) -> None:
    """Use only the host's authenticated actor and ProductService dependencies."""

    @app.exception_handler(DataPoolError)
    def data_pool_error(_request: Request, error: DataPoolError) -> JSONResponse:
        return JSONResponse(
            status_code=409,
            headers={"Cache-Control": "private, no-store"},
            content={
                "error": {
                    "code": "data_pool_hold",
                    "message": _SAFE_MESSAGES.get(
                        str(error),
                        "the data-pool operation did not satisfy its evidence contract",
                    ),
                }
            },
        )

    @app.post("/v1/tasks/{task_id}/data-pools", status_code=201, tags=["data-pool"])
    def create_data_pool(
        task_id: str,
        request: CreateDataPoolRequest,
        response: Response,
        actor: str = Depends(actor_dependency),
        product=Depends(product_dependency),
    ) -> dict:
        return _bind(
            DataPoolService(product).create_pool(actor, task_id, request), response
        )

    @app.get("/v1/tasks/{task_id}/data-pools", tags=["data-pool"])
    def list_data_pools(
        task_id: str,
        response: Response,
        actor: str = Depends(actor_dependency),
        product=Depends(product_dependency),
    ) -> dict:
        return _bind(DataPoolService(product).list_task_pools(actor, task_id), response)

    @app.get("/v1/data-pools/{pool_id}", tags=["data-pool"])
    def get_data_pool(
        pool_id: str,
        response: Response,
        actor: str = Depends(actor_dependency),
        product=Depends(product_dependency),
    ) -> dict:
        return _bind(DataPoolService(product).get_pool(actor, pool_id), response)

    @app.get("/v1/data-pool-versions/{version_id}", tags=["data-pool"])
    def get_data_pool_version(
        version_id: str,
        response: Response,
        actor: str = Depends(actor_dependency),
        product=Depends(product_dependency),
    ) -> dict:
        return _bind(DataPoolService(product).get_version(actor, version_id), response)

    @app.post(
        "/v1/data-pools/{pool_id}/versions",
        status_code=201,
        tags=["data-pool"],
    )
    def create_data_pool_version(
        pool_id: str,
        request: CreateDataPoolVersionRequest,
        response: Response,
        actor: str = Depends(actor_dependency),
        product=Depends(product_dependency),
    ) -> dict:
        return _bind(
            DataPoolService(product).create_version(actor, pool_id, request), response
        )

    @app.post(
        "/v1/data-pools/{pool_id}/versions/{version_id}/derive",
        status_code=201,
        tags=["data-pool"],
    )
    def derive_data_pool_version(
        pool_id: str,
        version_id: str,
        request: DeriveDataPoolVersionRequest,
        response: Response,
        actor: str = Depends(actor_dependency),
        product=Depends(product_dependency),
    ) -> dict:
        return _bind(
            DataPoolService(product).derive_version(
                actor, pool_id, version_id, request
            ),
            response,
        )

    @app.get(
        "/v1/projects/{project_id}/data-pool-operations/"
        "{operation}/{request_key}",
        tags=["data-pool"],
    )
    def get_data_pool_operation(
        project_id: str,
        operation: str,
        request_key: str,
        target_id: str,
        response: Response,
        actor: str = Depends(actor_dependency),
        product=Depends(product_dependency),
    ) -> dict:
        return _bind(
            DataPoolService(product).read_operation(
                actor, project_id, operation, request_key, target_id
            ),
            response,
        )


__all__ = ["install_data_pool_routes"]

