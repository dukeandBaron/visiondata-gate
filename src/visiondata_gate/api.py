"""FastAPI transport for the local VisionData Gate product service."""

import os
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Annotated

from fastapi import Depends, FastAPI, Header, Query, Request, Response, status
from fastapi.responses import FileResponse, JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

from .product_models import (
    CreateProjectRequest,
    CreateTaskRequest,
    CreateUserRequest,
    CreateWorkspaceRequest,
    ErrorDetail,
    ErrorEnvelope,
    HealthResponse,
    ProjectRecord,
    TaskEventRecord,
    TaskRecord,
    UserRecord,
    WorkspaceRecord,
)
from .product_service import (
    ArtifactUnavailableError,
    ProductService,
    ProductServiceError,
    UnsupportedSourceError,
)
from .task_store import ConflictError, NotFoundError, ProductStoreError


def _error_response(code: str, message: str, status_code: int) -> JSONResponse:
    return JSONResponse(
        status_code=status_code,
        content=ErrorEnvelope(error=ErrorDetail(code=code, message=message)).model_dump(
            mode="json"
        ),
    )


_NOT_FOUND_RESPONSE = {
    "model": ErrorEnvelope,
    "description": "The requested resource is not visible to this actor.",
}
_CONFLICT_RESPONSE = {
    "model": ErrorEnvelope,
    "description": "The requested operation conflicts with product state.",
}


def create_app(
    service: ProductService | None = None,
    *,
    enable_account_bootstrap: bool = False,
    ensure_demo_tenant: bool = True,
) -> FastAPI:
    product_root = Path(
        os.environ.get(
            "VISIONDATA_PRODUCT_ROOT",
            Path.cwd() / "output" / "product",
        )
    )
    owns_service = service is None
    product_service = service or ProductService(product_root, recover_interrupted=False)
    if ensure_demo_tenant:
        product_service.ensure_default_tenant()

    @asynccontextmanager
    async def lifespan(_app: FastAPI):
        yield
        if owns_service:
            product_service.close(wait=True)

    app = FastAPI(
        title="VisionData Gate API",
        version="0.2.0",
        summary="Auditable data-release Agent tasks for local enterprise evaluation",
        description=(
            "Local multi-workspace prototype. It has no production authentication, "
            "customer deployment, or hosted AgentTeams connection."
        ),
        docs_url="/docs",
        redoc_url=None,
        lifespan=lifespan,
    )
    app.state.product_service = product_service

    def service_dep(request: Request) -> ProductService:
        return request.app.state.product_service

    Service = Annotated[ProductService, Depends(service_dep)]
    Actor = Annotated[str, Header(alias="X-Actor-User-Id", min_length=1)]

    @app.exception_handler(NotFoundError)
    def not_found(_request: Request, exc: NotFoundError) -> JSONResponse:
        return _error_response(exc.code, str(exc), status.HTTP_404_NOT_FOUND)

    @app.exception_handler(ConflictError)
    def conflict(_request: Request, exc: ConflictError) -> JSONResponse:
        return _error_response(exc.code, str(exc), status.HTTP_409_CONFLICT)

    @app.exception_handler(UnsupportedSourceError)
    def unsupported_source(
        _request: Request, exc: UnsupportedSourceError
    ) -> JSONResponse:
        return _error_response(exc.code, str(exc), status.HTTP_409_CONFLICT)

    @app.exception_handler(ArtifactUnavailableError)
    def artifact_unavailable(
        _request: Request, exc: ArtifactUnavailableError
    ) -> JSONResponse:
        return _error_response(exc.code, str(exc), status.HTTP_409_CONFLICT)

    @app.exception_handler(ProductStoreError)
    @app.exception_handler(ProductServiceError)
    def product_error(_request: Request, exc: Exception) -> JSONResponse:
        return _error_response(
            getattr(exc, "code", "product_error"),
            "the requested product operation could not be completed",
            status.HTTP_409_CONFLICT,
        )

    @app.exception_handler(StarletteHTTPException)
    def http_error(_request: Request, exc: StarletteHTTPException) -> JSONResponse:
        code = {
            status.HTTP_404_NOT_FOUND: "not_found",
            status.HTTP_405_METHOD_NOT_ALLOWED: "method_not_allowed",
        }.get(exc.status_code, "http_error")
        message = {
            status.HTTP_404_NOT_FOUND: "the requested API route was not found",
            status.HTTP_405_METHOD_NOT_ALLOWED: "the requested method is not allowed",
        }.get(exc.status_code, "the HTTP request could not be completed")
        return _error_response(code, message, exc.status_code)

    @app.get("/v1/health", response_model=HealthResponse, tags=["system"])
    def health(product: Service) -> HealthResponse:
        return product.health()

    if enable_account_bootstrap:

        @app.post(
            "/v1/users",
            response_model=UserRecord,
            status_code=status.HTTP_201_CREATED,
            responses={409: _CONFLICT_RESPONSE},
            tags=["accounts"],
        )
        def create_user(payload: CreateUserRequest, product: Service) -> UserRecord:
            return product.create_user(payload)

        @app.get("/v1/users", response_model=list[UserRecord], tags=["accounts"])
        def list_users(actor: Actor, product: Service) -> list[UserRecord]:
            return [user for user in product.list_users() if user.user_id == actor]

        @app.post(
            "/v1/workspaces",
            response_model=WorkspaceRecord,
            status_code=status.HTTP_201_CREATED,
            responses={404: _NOT_FOUND_RESPONSE},
            tags=["workspaces"],
        )
        def create_workspace(
            payload: CreateWorkspaceRequest, actor: Actor, product: Service
        ) -> WorkspaceRecord:
            if actor != payload.owner_user_id:
                raise NotFoundError("workspace owner not found")
            return product.create_workspace(payload)

    @app.get(
        "/v1/workspaces",
        response_model=list[WorkspaceRecord],
        tags=["workspaces"],
    )
    def list_workspaces(actor: Actor, product: Service) -> list[WorkspaceRecord]:
        return product.list_workspaces(actor)

    @app.post(
        "/v1/projects",
        response_model=ProjectRecord,
        status_code=status.HTTP_201_CREATED,
        responses={404: _NOT_FOUND_RESPONSE},
        tags=["projects"],
    )
    def create_project(
        payload: CreateProjectRequest, actor: Actor, product: Service
    ) -> ProjectRecord:
        return product.create_project(actor, payload)

    @app.get(
        "/v1/projects",
        response_model=list[ProjectRecord],
        responses={404: _NOT_FOUND_RESPONSE},
        tags=["projects"],
    )
    def list_projects(
        workspace_id: Annotated[str, Query(min_length=1)],
        actor: Actor,
        product: Service,
    ) -> list[ProjectRecord]:
        return product.list_projects(actor, workspace_id)

    @app.post(
        "/v1/tasks",
        response_model=TaskRecord,
        status_code=status.HTTP_202_ACCEPTED,
        responses={404: _NOT_FOUND_RESPONSE, 409: _CONFLICT_RESPONSE},
        tags=["tasks"],
    )
    def create_task(
        payload: CreateTaskRequest,
        actor: Actor,
        product: Service,
        response: Response,
        idempotency_key: Annotated[
            str | None, Header(alias="Idempotency-Key", max_length=120)
        ] = None,
    ) -> TaskRecord:
        task = product.create_task(
            actor, payload, idempotency_key=idempotency_key, auto_start=True
        )
        response.headers["Location"] = f"/v1/tasks/{task.task_id}"
        return task

    @app.get("/v1/tasks", response_model=list[TaskRecord], tags=["tasks"])
    def list_tasks(
        actor: Actor,
        product: Service,
        workspace_id: str | None = None,
        project_id: str | None = None,
        limit: Annotated[int, Query(ge=1, le=200)] = 100,
    ) -> list[TaskRecord]:
        return product.list_tasks(
            actor,
            workspace_id=workspace_id,
            project_id=project_id,
            limit=limit,
        )

    @app.get(
        "/v1/tasks/{task_id}",
        response_model=TaskRecord,
        responses={404: _NOT_FOUND_RESPONSE},
        tags=["tasks"],
    )
    def get_task(task_id: str, actor: Actor, product: Service) -> TaskRecord:
        return product.get_task(actor, task_id)

    @app.get(
        "/v1/tasks/{task_id}/events",
        response_model=list[TaskEventRecord],
        responses={404: _NOT_FOUND_RESPONSE},
        tags=["tasks"],
    )
    def get_task_events(
        task_id: str, actor: Actor, product: Service
    ) -> list[TaskEventRecord]:
        return product.list_events(actor, task_id)

    @app.get(
        "/v1/tasks/{task_id}/trace",
        response_class=FileResponse,
        responses={
            200: {
                "description": "Canonical runtime trace JSON download.",
                "content": {
                    "application/json": {
                        "schema": {"type": "string", "format": "binary"}
                    }
                },
            },
            404: _NOT_FOUND_RESPONSE,
            409: _CONFLICT_RESPONSE,
        },
        tags=["artifacts"],
    )
    def get_trace(task_id: str, actor: Actor, product: Service) -> FileResponse:
        path = product.trace_path(actor, task_id)
        task = product.get_task(actor, task_id)
        return FileResponse(
            path,
            media_type="application/json",
            filename=f"{task_id}-runtime-trace.json",
            headers={"ETag": f'"{task.trace_sha256}"'},
        )

    @app.get(
        "/v1/tasks/{task_id}/evidence",
        response_class=FileResponse,
        responses={
            200: {
                "description": "Immutable evidence ZIP download.",
                "content": {
                    "application/zip": {
                        "schema": {"type": "string", "format": "binary"}
                    }
                },
            },
            404: _NOT_FOUND_RESPONSE,
            409: _CONFLICT_RESPONSE,
        },
        tags=["artifacts"],
    )
    def get_evidence(task_id: str, actor: Actor, product: Service) -> FileResponse:
        path = product.evidence_path(actor, task_id)
        task = product.get_task(actor, task_id)
        return FileResponse(
            path,
            media_type="application/zip",
            filename=f"{task_id}-evidence.zip",
            headers={
                "ETag": f'"{task.evidence_sha256}"',
                "X-Evidence-SHA256": task.evidence_sha256 or "",
            },
        )

    return app


app = create_app()


__all__ = ["app", "create_app"]
