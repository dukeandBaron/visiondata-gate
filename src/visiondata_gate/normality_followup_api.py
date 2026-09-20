"""Authenticated local-only human followup bridge routes; dependencies stay host-owned."""

from fastapi import APIRouter, Depends, Response
from fastapi.responses import JSONResponse

from .local_model_registry import VisionModelError
from .normality_followup_service import (
    CreateNormalityFollowupWorkOrder,
    FollowupWriteOutcomeUnknown,
    ImportNormalityFollowup,
    NormalityFollowupService,
)
from .operator_workspace import OperatorWorkspaceError
from .vision_model_api import _PrivateVisionRoute, _bind_receipt, _require_loopback


class _FollowupRoute(_PrivateVisionRoute):
    def get_route_handler(self):
        original = super().get_route_handler()

        async def handler(request):
            try:
                return await original(request)
            except FollowupWriteOutcomeUnknown:
                return JSONResponse(
                    status_code=503,
                    headers={"Cache-Control": "private, no-store"},
                    content={
                        "error": {
                            "code": "normality_followup_outcome_unknown",
                            "message": "A durable followup intent exists. Keep the original request key and use GET reconciliation; do not submit a new request.",
                        }
                    },
                )
            except (
                VisionModelError,
                OperatorWorkspaceError,
                OSError,
                ValueError,
                TypeError,
                KeyError,
            ):
                return JSONResponse(
                    status_code=409,
                    headers={"Cache-Control": "private, no-store"},
                    content={
                        "error": {
                            "code": "normality_followup_hold",
                            "message": "Human followup evidence, authority or storage changed. Refresh and reconcile. "
                            "Non-identity EXIF images require a normalized new asset and new inference.",
                        }
                    },
                )

        return handler


def install_normality_followup_routes(
    app, actor_dependency, product_dependency, operator_store_dependency
):
    router = APIRouter(
        prefix="/v1/projects/{project_id}",
        tags=["normality-followup"],
        route_class=_FollowupRoute,
    )

    def service(
        product=Depends(product_dependency), store=Depends(operator_store_dependency)
    ):
        return NormalityFollowupService(product, store)

    @router.post(
        "/normality-feedback/{feedback_id}/followup-import",
        status_code=201,
        dependencies=[Depends(_require_loopback)],
    )
    def import_asset(
        project_id: str,
        feedback_id: str,
        request: ImportNormalityFollowup,
        response: Response,
        actor: str = Depends(actor_dependency),
        bridge=Depends(service),
    ):
        return _bind_receipt(
            bridge.import_feedback(actor, project_id, feedback_id, request), response
        )

    @router.post(
        "/normality-feedback/{feedback_id}/followup-work-orders",
        status_code=201,
        dependencies=[Depends(_require_loopback)],
    )
    def work_order(
        project_id: str,
        feedback_id: str,
        request: CreateNormalityFollowupWorkOrder,
        response: Response,
        actor: str = Depends(actor_dependency),
        bridge=Depends(service),
    ):
        return _bind_receipt(
            bridge.create_work_order(actor, project_id, feedback_id, request), response
        )

    @router.get("/normality-feedback/{feedback_id}/followup")
    def read_followup(
        project_id: str,
        feedback_id: str,
        response: Response,
        actor: str = Depends(actor_dependency),
        bridge=Depends(service),
    ):
        return _bind_receipt(
            bridge.list_followup(actor, project_id, feedback_id), response
        )

    @router.get(
        "/normality-feedback/{feedback_id}/followup-imports/{import_id}/annotations"
    )
    def annotations(
        project_id: str,
        feedback_id: str,
        import_id: str,
        response: Response,
        actor: str = Depends(actor_dependency),
        bridge=Depends(service),
    ):
        return _bind_receipt(
            bridge.annotations(actor, project_id, feedback_id, import_id), response
        )

    @router.get("/normality-followup-operations/{operation}/{request_key}")
    def operation(
        project_id: str,
        operation: str,
        request_key: str,
        response: Response,
        actor: str = Depends(actor_dependency),
        bridge=Depends(service),
    ):
        return _bind_receipt(
            bridge.get_followup_operation(actor, project_id, operation, request_key),
            response,
        )

    app.include_router(router)
