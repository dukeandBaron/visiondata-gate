"""Authenticated project routes for optional, locally managed vision models."""

from __future__ import annotations

import hashlib
import hmac
import ipaddress
import re
from collections.abc import Callable

from fastapi import APIRouter, Depends, FastAPI, HTTPException, Request, Response
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from fastapi.routing import APIRoute

from .audit_envelope import canonical_jcs_bytes
from .local_model_registry import (
    ApproveNormalityModelPack,
    CreateVisionTrainingRun,
    LocalVisionModelService,
    ProbeVisionRuntime,
    RegisterNormalityModelPack,
    RegisterDetectionDataset,
    RegisterVisionInferenceAsset,
    RegisterPoolDetectionDataset,
    RegisterVisionModel,
    RegisterVisionRuntime,
    ReviewVisionFeedback,
    ReviewNormalityInference,
    RunNormalityInference,
    SelectVisionModel,
    VisionModelError,
    VisionRunAction,
)

_PRIVATE_HEADERS = {"Cache-Control": "private, no-store"}


class _PrivateVisionRoute(APIRoute):
    """Keep supplied paths and arbitrary extra fields out of validation errors."""

    def get_route_handler(self) -> Callable:
        original = super().get_route_handler()

        async def handler(request: Request) -> Response:
            try:
                return await original(request)
            except RequestValidationError:
                return JSONResponse(
                    status_code=422,
                    headers=_PRIVATE_HEADERS,
                    content={
                        "error": {
                            "code": "vision_request_invalid",
                            "message": "the vision request does not match its contract",
                        }
                    },
                )

        return handler


def _require_loopback(request: Request) -> None:
    """Require the connection peer, without trusting forwarded header values."""
    try:
        address = ipaddress.ip_address(request.client.host if request.client else "")
    except ValueError:
        address = None
    if isinstance(address, ipaddress.IPv6Address) and address.ipv4_mapped:
        address = address.ipv4_mapped
    if address is None or not address.is_loopback:
        raise HTTPException(
            status_code=403,
            headers=_PRIVATE_HEADERS,
            detail={
                "code": "vision_local_access_required",
                "message": "this vision operation requires a local connection",
            },
        )


def _bind_receipt(value: dict, response: Response) -> dict:
    digest = value.get("receipt_sha256")
    if not isinstance(digest, str) or re.fullmatch(r"[0-9a-f]{64}", digest) is None:
        raise VisionModelError("VISION_RESPONSE_RECEIPT_INVALID")
    actual = hashlib.sha256(
        canonical_jcs_bytes(
            {key: item for key, item in value.items() if key != "receipt_sha256"}
        )
    ).hexdigest()
    if not hmac.compare_digest(digest, actual):
        raise VisionModelError("VISION_RESPONSE_RECEIPT_INVALID")
    response.headers["ETag"] = f'"{digest}"'
    response.headers["X-Content-SHA256"] = digest
    response.headers.update(_PRIVATE_HEADERS)
    return value


def install_vision_model_routes(
    app: FastAPI,
    actor_dependency: Callable,
    product_dependency: Callable,
) -> None:
    """Install routes without instantiating storage, loading models, or probing.

    The host supplies the authenticated principal and ProductService. The service
    checks project ownership for every call. Host NotFoundError handlers remain
    authoritative; validation and vision-contract failures never echo input paths.
    Training creation returns a queued receipt; execution is owned by the service.
    """

    @app.exception_handler(VisionModelError)
    def vision_error(_request: Request, _error: VisionModelError) -> JSONResponse:
        return JSONResponse(
            status_code=409,
            headers=_PRIVATE_HEADERS,
            content={
                "error": {
                    "code": "vision_model_hold",
                    "message": (
                        "the vision operation could not satisfy its current "
                        "authority, runtime, or evidence contract"
                    ),
                }
            },
        )

    router = APIRouter(
        prefix="/v1/projects/{project_id}",
        tags=["vision-models"],
        route_class=_PrivateVisionRoute,
    )
    local_only = [Depends(_require_loopback)]

    @router.get("/vision-capabilities")
    def capabilities(
        project_id: str,
        response: Response,
        actor: str = Depends(actor_dependency),
        product=Depends(product_dependency),
    ) -> dict:
        return _bind_receipt(
            LocalVisionModelService(product).capabilities(actor, project_id), response
        )

    @router.get("/vision-models")
    def list_models(
        project_id: str,
        response: Response,
        actor: str = Depends(actor_dependency),
        product=Depends(product_dependency),
    ) -> dict:
        return _bind_receipt(
            LocalVisionModelService(product).list_models(actor, project_id), response
        )

    @router.post("/vision-models", status_code=201, dependencies=local_only)
    def register_model(
        project_id: str,
        request: RegisterVisionModel,
        response: Response,
        actor: str = Depends(actor_dependency),
        product=Depends(product_dependency),
    ) -> dict:
        return _bind_receipt(
            LocalVisionModelService(product).register_model(actor, project_id, request),
            response,
        )

    @router.post("/vision-model-packs", status_code=201, dependencies=local_only)
    def register_normality_model_pack(
        project_id: str,
        request: RegisterNormalityModelPack,
        response: Response,
        actor: str = Depends(actor_dependency),
        product=Depends(product_dependency),
    ) -> dict:
        return _bind_receipt(
            LocalVisionModelService(product).register_normality_model_pack(
                actor, project_id, request
            ),
            response,
        )

    @router.get("/vision-models/{model_id}")
    def get_model(
        project_id: str,
        model_id: str,
        response: Response,
        actor: str = Depends(actor_dependency),
        product=Depends(product_dependency),
    ) -> dict:
        return _bind_receipt(
            LocalVisionModelService(product).get_model(actor, project_id, model_id),
            response,
        )

    @router.post(
        "/vision-models/{model_id}/sandbox-approval", dependencies=local_only
    )
    def approve_normality_model_pack(
        project_id: str,
        model_id: str,
        request: ApproveNormalityModelPack,
        response: Response,
        actor: str = Depends(actor_dependency),
        product=Depends(product_dependency),
    ) -> dict:
        return _bind_receipt(
            LocalVisionModelService(product).approve_normality_model_pack(
                actor, project_id, model_id, request
            ),
            response,
        )

    @router.get("/vision-inference-assets")
    def list_inference_assets(
        project_id: str,
        response: Response,
        actor: str = Depends(actor_dependency),
        product=Depends(product_dependency),
    ) -> dict:
        return _bind_receipt(
            LocalVisionModelService(product).list_inference_assets(
                actor, project_id
            ),
            response,
        )

    @router.post(
        "/vision-inference-assets", status_code=201, dependencies=local_only
    )
    def register_inference_asset(
        project_id: str,
        request: RegisterVisionInferenceAsset,
        response: Response,
        actor: str = Depends(actor_dependency),
        product=Depends(product_dependency),
    ) -> dict:
        return _bind_receipt(
            LocalVisionModelService(product).register_inference_asset(
                actor, project_id, request
            ),
            response,
        )

    @router.get("/vision-inference-assets/{asset_id}")
    def get_inference_asset(
        project_id: str,
        asset_id: str,
        response: Response,
        actor: str = Depends(actor_dependency),
        product=Depends(product_dependency),
    ) -> dict:
        return _bind_receipt(
            LocalVisionModelService(product).get_inference_asset(
                actor, project_id, asset_id
            ),
            response,
        )

    @router.get("/vision-inferences")
    def list_inferences(
        project_id: str,
        response: Response,
        actor: str = Depends(actor_dependency),
        product=Depends(product_dependency),
    ) -> dict:
        return _bind_receipt(
            LocalVisionModelService(product).list_inferences(actor, project_id),
            response,
        )

    @router.get("/vision-inferences/{inference_id}")
    def get_inference(
        project_id: str,
        inference_id: str,
        response: Response,
        actor: str = Depends(actor_dependency),
        product=Depends(product_dependency),
    ) -> dict:
        return _bind_receipt(
            LocalVisionModelService(product).get_inference(
                actor, project_id, inference_id
            ),
            response,
        )

    @router.post(
        "/vision-models/{model_id}/inferences",
        status_code=201,
        dependencies=local_only,
    )
    def run_normality_inference(
        project_id: str,
        model_id: str,
        request: RunNormalityInference,
        response: Response,
        actor: str = Depends(actor_dependency),
        product=Depends(product_dependency),
    ) -> dict:
        return _bind_receipt(
            LocalVisionModelService(product).run_normality_inference(
                actor, project_id, model_id, request
            ),
            response,
        )

    @router.get("/vision-inferences/{inference_id}/heatmap")
    def get_inference_heatmap(
        project_id: str,
        inference_id: str,
        actor: str = Depends(actor_dependency),
        product=Depends(product_dependency),
    ) -> Response:
        content, digest = LocalVisionModelService(product).get_inference_heatmap(
            actor, project_id, inference_id
        )
        if not hmac.compare_digest(hashlib.sha256(content).hexdigest(), digest):
            raise VisionModelError("VISION_HEATMAP_RESPONSE_IDENTITY_INVALID")
        return Response(
            content=content,
            media_type="image/png",
            headers=_PRIVATE_HEADERS | {
                "ETag": f'"{digest}"',
                "X-Content-SHA256": digest,
                "X-Content-Type-Options": "nosniff",
            },
        )

    @router.get("/vision-inferences/{inference_id}/feedback")
    def list_normality_feedback(
        project_id: str,
        inference_id: str,
        response: Response,
        actor: str = Depends(actor_dependency),
        product=Depends(product_dependency),
    ) -> dict:
        return _bind_receipt(
            LocalVisionModelService(product).list_normality_feedback(
                actor, project_id, inference_id
            ),
            response,
        )

    @router.post(
        "/vision-inferences/{inference_id}/feedback",
        status_code=201,
        dependencies=local_only,
    )
    def review_normality_inference(
        project_id: str,
        inference_id: str,
        request: ReviewNormalityInference,
        response: Response,
        actor: str = Depends(actor_dependency),
        product=Depends(product_dependency),
    ) -> dict:
        return _bind_receipt(
            LocalVisionModelService(product).review_normality_inference(
                actor, project_id, inference_id, request
            ),
            response,
        )

    @router.get("/vision-runtimes")
    def list_runtimes(
        project_id: str,
        response: Response,
        actor: str = Depends(actor_dependency),
        product=Depends(product_dependency),
    ) -> dict:
        return _bind_receipt(
            LocalVisionModelService(product).list_runtimes(actor, project_id), response
        )

    @router.post("/vision-runtimes", status_code=201, dependencies=local_only)
    def register_runtime(
        project_id: str,
        request: RegisterVisionRuntime,
        response: Response,
        actor: str = Depends(actor_dependency),
        product=Depends(product_dependency),
    ) -> dict:
        return _bind_receipt(
            LocalVisionModelService(product).register_runtime(
                actor, project_id, request
            ),
            response,
        )

    @router.post("/vision-runtimes/{runtime_id}/probe", dependencies=local_only)
    def probe_runtime(
        project_id: str,
        runtime_id: str,
        request: ProbeVisionRuntime,
        response: Response,
        actor: str = Depends(actor_dependency),
        product=Depends(product_dependency),
    ) -> dict:
        return _bind_receipt(
            LocalVisionModelService(product).probe_runtime(
                actor, project_id, runtime_id, request
            ),
            response,
        )

    @router.get("/vision-datasets")
    def list_datasets(
        project_id: str,
        response: Response,
        actor: str = Depends(actor_dependency),
        product=Depends(product_dependency),
    ) -> dict:
        return _bind_receipt(
            LocalVisionModelService(product).list_datasets(actor, project_id), response
        )

    @router.post("/vision-datasets", status_code=201, dependencies=local_only)
    def register_dataset(
        project_id: str,
        request: RegisterDetectionDataset,
        response: Response,
        actor: str = Depends(actor_dependency),
        product=Depends(product_dependency),
    ) -> dict:
        return _bind_receipt(
            LocalVisionModelService(product).register_dataset(
                actor, project_id, request
            ),
            response,
        )

    @router.post(
        "/vision-datasets/from-data-pool", status_code=201, dependencies=local_only
    )
    def register_pool_dataset(
        project_id: str,
        request: RegisterPoolDetectionDataset,
        response: Response,
        actor: str = Depends(actor_dependency),
        product=Depends(product_dependency),
    ) -> dict:
        return _bind_receipt(
            LocalVisionModelService(product).register_pool_dataset(
                actor, project_id, request
            ),
            response,
        )

    @router.get("/vision-training-runs")
    def list_runs(
        project_id: str,
        response: Response,
        actor: str = Depends(actor_dependency),
        product=Depends(product_dependency),
    ) -> dict:
        return _bind_receipt(
            LocalVisionModelService(product).list_runs(actor, project_id), response
        )

    @router.post("/vision-training-runs", status_code=202, dependencies=local_only)
    def create_training_run(
        project_id: str,
        request: CreateVisionTrainingRun,
        response: Response,
        actor: str = Depends(actor_dependency),
        product=Depends(product_dependency),
    ) -> dict:
        return _bind_receipt(
            LocalVisionModelService(product).create_training_run(
                actor, project_id, request
            ),
            response,
        )

    @router.get("/vision-training-runs/{run_id}")
    def get_run(
        project_id: str,
        run_id: str,
        response: Response,
        actor: str = Depends(actor_dependency),
        product=Depends(product_dependency),
    ) -> dict:
        return _bind_receipt(
            LocalVisionModelService(product).get_run(actor, project_id, run_id),
            response,
        )

    @router.get("/vision-training-runs/{run_id}/feedback")
    def list_feedback(
        project_id: str,
        run_id: str,
        response: Response,
        actor: str = Depends(actor_dependency),
        product=Depends(product_dependency),
    ) -> dict:
        return _bind_receipt(
            LocalVisionModelService(product).list_feedback(actor, project_id, run_id),
            response,
        )

    @router.post(
        "/vision-training-runs/{run_id}/feedback/{feedback_id}/triage",
        dependencies=local_only,
    )
    def triage_feedback(
        project_id: str,
        run_id: str,
        feedback_id: str,
        request: ReviewVisionFeedback,
        response: Response,
        actor: str = Depends(actor_dependency),
        product=Depends(product_dependency),
    ) -> dict:
        return _bind_receipt(
            LocalVisionModelService(product).triage_feedback(
                actor, project_id, run_id, feedback_id, request
            ),
            response,
        )

    @router.post("/vision-training-runs/{run_id}/cancel", dependencies=local_only)
    def cancel_run(
        project_id: str,
        run_id: str,
        request: VisionRunAction,
        response: Response,
        actor: str = Depends(actor_dependency),
        product=Depends(product_dependency),
    ) -> dict:
        return _bind_receipt(
            LocalVisionModelService(product).cancel_run(
                actor, project_id, run_id, request
            ),
            response,
        )

    @router.post("/vision-training-runs/{run_id}/recover", dependencies=local_only)
    def recover_run(
        project_id: str,
        run_id: str,
        request: VisionRunAction,
        response: Response,
        actor: str = Depends(actor_dependency),
        product=Depends(product_dependency),
    ) -> dict:
        return _bind_receipt(
            LocalVisionModelService(product).recover_run(
                actor, project_id, run_id, request
            ),
            response,
        )

    @router.post("/vision-training-runs/{run_id}/selection", dependencies=local_only)
    def select_model(
        project_id: str,
        run_id: str,
        request: SelectVisionModel,
        response: Response,
        actor: str = Depends(actor_dependency),
        product=Depends(product_dependency),
    ) -> dict:
        return _bind_receipt(
            LocalVisionModelService(product).select_model(
                actor, project_id, run_id, request
            ),
            response,
        )

    @router.get("/vision-operations/{operation}/{request_key}")
    def get_operation(
        project_id: str,
        operation: str,
        request_key: str,
        response: Response,
        actor: str = Depends(actor_dependency),
        product=Depends(product_dependency),
    ) -> dict:
        return _bind_receipt(
            LocalVisionModelService(product).get_operation(
                actor, project_id, operation, request_key
            ),
            response,
        )

    app.include_router(router)
    from .normality_adaptation_api import install_normality_ttt_routes

    install_normality_ttt_routes(app, actor_dependency, product_dependency)
