"""Local authenticated endpoints for bounded episodic Normality adaptation."""

from fastapi import APIRouter, Depends, Response

from .normality_adaptation_service import NormalityAdaptationService, RunNormalityTtt
from .vision_model_api import _PrivateVisionRoute, _bind_receipt, _require_loopback


def install_normality_ttt_routes(app, actor_dependency, product_dependency):
    router = APIRouter(
        prefix="/v1/projects/{project_id}",
        tags=["normality-ttt"],
        route_class=_PrivateVisionRoute,
    )

    @router.get("/vision-ttt-capabilities")
    def capabilities(
        project_id: str,
        response: Response,
        actor: str = Depends(actor_dependency),
        product=Depends(product_dependency),
    ) -> dict:
        return _bind_receipt(
            NormalityAdaptationService(product).ttt_capabilities(actor, project_id),
            response,
        )

    @router.get("/vision-ttt-failures")
    def failures(
        project_id: str,
        response: Response,
        actor: str = Depends(actor_dependency),
        product=Depends(product_dependency),
    ) -> dict:
        return _bind_receipt(
            NormalityAdaptationService(product).list_failures(actor, project_id),
            response,
        )

    @router.post(
        "/vision-models/{model_id}/ttt-inferences",
        status_code=201,
        dependencies=[Depends(_require_loopback)],
    )
    def run(
        project_id: str,
        model_id: str,
        request: RunNormalityTtt,
        response: Response,
        actor: str = Depends(actor_dependency),
        product=Depends(product_dependency),
    ) -> dict:
        return _bind_receipt(
            NormalityAdaptationService(product).run_ttt(
                actor, project_id, model_id, request
            ),
            response,
        )

    app.include_router(router)
