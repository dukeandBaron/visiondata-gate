"""FastAPI transport for VisionData Gate and its optional hosted transport."""

import hashlib
import hmac
import os
import secrets
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Annotated

from fastapi import (
    Depends,
    FastAPI,
    File,
    Header,
    HTTPException,
    Query,
    Request,
    Response,
    UploadFile,
    status,
)
from fastapi.middleware.cors import CORSMiddleware
from fastapi.exceptions import RequestValidationError
from fastapi.responses import FileResponse, JSONResponse, PlainTextResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

from .acceptance import AcceptanceScorecard
from .annotation_roundtrip import (
    AnnotationExportRecord,
    AnnotationImportPackage,
    AnnotationProvider,
    AnnotationRoundtripReceipt,
)
from .agentteams_transport import (
    HostedAgentTeamsReceipt,
    hosted_agentteams_from_environment,
)
from .audit_envelope import GovernedAuditEnvelope
from .capa import (
    ApproveRemediationPlanRequest,
    CapaCaseReport,
    CapaOutcomeAssessment,
    ExecuteRemediationPlanRequest,
    SelectRemediationPlanRequest,
)
from .case_replay import CausalReplayReport
from .evaluation_evidence import (
    DynamicBenchEvaluationEvidenceProjection,
    DynamicBenchEvaluationEvidenceSource,
    global_evaluation_evidence_scope,
    scoped_evaluation_evidence_scope,
)
from .evidence import canonical_json_bytes
from .incident_commands import (
    IncidentCommandKind,
    IncidentCommandReceipt,
    incident_command_id,
    resolve_incident_idempotency_key,
)
from .incident_control_plane import IncidentControlPlaneBundle
from .incident_decision_packet import IndustrialQualityDecisionPacket
from .incident_review_projection import IncidentReviewProjection
from .incident_model_planner import incident_model_planner_from_environment
from .incident_runtime_profile import (
    IncidentRuntimeCapabilities,
    IncidentRuntimeProfileBinding,
)
from .private_industrial_validation import (
    PrivateIndustrialValidationSource,
    PrivateIndustrialValidationSummary,
    global_industrial_validation_scope,
    scoped_industrial_validation_scope,
)
from .governed_context import AssembledIncidentContext
from .governed_outcome import GovernedOutcomeEnvelope
from .goal3_bridge import Goal3HandoffReceipt
from .governance_effectiveness import (
    CreateIndustrialShadowEvaluationRequest,
    CreateShadowEvaluationManifestV2Request,
    IndustrialShadowEvaluationReceipt,
    ProjectGovernanceEffectivenessSummary,
    ShadowEvaluationManifestV2,
)
from .industrial_delivery import IndustrialDeliveryReceipt
from .incident_interaction import IncidentInteractionReceipt
from .industrial_incident import (
    IncidentPhaseEvent,
    IndustrialIncidentCase,
    IndustrialIncidentDecisionReceipt,
    IndustrialIncidentDecisionRequest,
    IndustrialIncidentRequest,
)
from .lineage import (
    CreateReverificationRequest,
    TaskLineageReport,
)
from .operator_workspace import (
    CreateOperatorCopilotTurnRequest,
    CreateOperatorWorkOrderRequest,
    MAX_UPLOAD_BATCH_BYTES,
    MAX_UPLOAD_BYTES,
    MAX_UPLOAD_FILES,
    OperatorAnnotationState,
    OperatorAnalysisRunState,
    OperatorCopilotTurnState,
    OperatorImageAsset,
    OperatorImageStore,
    OperatorImageUploadBatch,
    OperatorWorkOrderState,
    OperatorWorkspaceError,
    SaveAnnotationsRequest,
    UpdateOperatorWorkOrderRequest,
)
from .product_models import (
    AuthorizeLocalSourceRequest,
    AuthorizeOperatorProjectSnapshotRequest,
    CreateProjectRequest,
    CreateTaskRequest,
    CreateUserRequest,
    CreateWorkspaceRequest,
    ErrorDetail,
    ErrorEnvelope,
    HealthResponse,
    LocalSourceAuthorizationReceipt,
    ProjectRecord,
    RevokeLocalSourceAuthorizationRequest,
    SourceAuthorizationEventReceipt,
    SubmitHostedAgentTeamsTaskRequest,
    TaskEventRecord,
    TaskInterventionRecord,
    TaskInterventionRequest,
    TaskPlanPreview,
    TaskRecord,
    UserRecord,
    WorkspaceRecord,
)
from .product_service import (
    ArtifactUnavailableError,
    IncidentCommandUncertainError,
    ProductService,
    ProductServiceError,
    UnsupportedSourceError,
)
from .provider_profiles import (
    ProviderConnectionTestRequest,
    ProviderConnectionTestResult,
    ProviderProfileCreateRequest,
    ProviderProfileRecord,
)
from .readiness import TaskPreflightReport, TaskReleaseReadinessReport
from .semifinal_manifest import (
    SemifinalDemoManifestProjection,
    SemifinalDemoManifestSource,
)
from .task_store import ConflictError, NotFoundError, ProductStoreError
from .visual_evidence import TaskVisualEvidenceManifest


def _error_response(code: str, message: str, status_code: int) -> JSONResponse:
    return JSONResponse(
        status_code=status_code,
        content=ErrorEnvelope(error=ErrorDetail(code=code, message=message)).model_dump(
            mode="json"
        ),
    )


def _canonical_content_sha256(value: object) -> str:
    return hashlib.sha256(canonical_json_bytes(value)).hexdigest()


def _bind_sha256_response(
    response: Response,
    digest: str,
    *,
    header_name: str = "X-Content-SHA256",
) -> None:
    """Bind a JSON response to one strong SHA-256 entity validator."""

    response.headers["ETag"] = f'"{digest}"'
    response.headers[header_name] = digest
    response.headers["Cache-Control"] = "private, no-store"


_NOT_FOUND_RESPONSE = {
    "model": ErrorEnvelope,
    "description": "The requested resource is not visible to this actor.",
}
_CONFLICT_RESPONSE = {
    "model": ErrorEnvelope,
    "description": "The requested operation conflicts with product state.",
}

_SESSION_TOKEN_MIN_LENGTH = 32
_DEFAULT_SESSION_ACTOR = "usr_local_demo"


def _strict_env_bool(name: str, *, default: bool = False) -> bool:
    raw = os.environ.get(name)
    if raw is None or not raw.strip():
        return default
    normalized = raw.strip().casefold()
    if normalized in {"1", "true", "yes", "on"}:
        return True
    if normalized in {"0", "false", "no", "off"}:
        return False
    raise ValueError(f"{name} must be true or false")


def _session_security_from_environment() -> tuple[str, str, bool, str, str]:
    generic_token = os.environ.get("VISIONDATA_SESSION_TOKEN", "").strip()
    desktop_token = os.environ.get("VISIONDATA_DESKTOP_SESSION_TOKEN", "").strip()
    if (
        generic_token
        and desktop_token
        and not secrets.compare_digest(generic_token, desktop_token)
    ):
        raise ValueError(
            "VISIONDATA_SESSION_TOKEN and VISIONDATA_DESKTOP_SESSION_TOKEN "
            "cannot disagree"
        )
    session_token = generic_token or desktop_token
    if session_token and len(session_token) < _SESSION_TOKEN_MIN_LENGTH:
        raise ValueError(
            f"local session tokens must contain at least {_SESSION_TOKEN_MIN_LENGTH} "
            "characters"
        )
    actor = os.environ.get(
        "VISIONDATA_SESSION_ACTOR_USER_ID", _DEFAULT_SESSION_ACTOR
    ).strip()
    if (
        not actor
        or len(actor) > 256
        or any(ord(character) < 0x21 or ord(character) == 0x7F for character in actor)
    ):
        raise ValueError(
            "VISIONDATA_SESSION_ACTOR_USER_ID must be one printable token of at "
            "most 256 characters"
        )
    test_bypass = _strict_env_bool("VISIONDATA_INSECURE_TEST_ACTOR_HEADER_BYPASS")
    desktop_startup_secret = os.environ.get(
        "VISIONDATA_DESKTOP_STARTUP_SECRET", ""
    ).strip()
    if desktop_startup_secret and not desktop_token:
        raise ValueError(
            "VISIONDATA_DESKTOP_STARTUP_SECRET requires "
            "VISIONDATA_DESKTOP_SESSION_TOKEN"
        )
    if desktop_startup_secret and (
        len(desktop_startup_secret) < _SESSION_TOKEN_MIN_LENGTH
        or any(
            ord(character) < 0x21 or ord(character) == 0x7F
            for character in desktop_startup_secret
        )
    ):
        raise ValueError(
            "VISIONDATA_DESKTOP_STARTUP_SECRET must contain at least "
            f"{_SESSION_TOKEN_MIN_LENGTH} printable token characters"
        )
    return (
        session_token,
        actor,
        test_bypass,
        desktop_token,
        desktop_startup_secret,
    )


def create_app(
    service: ProductService | None = None,
    *,
    enable_account_bootstrap: bool = False,
    ensure_demo_tenant: bool = True,
    evaluation_evidence_source: DynamicBenchEvaluationEvidenceSource | None = None,
    industrial_validation_source: PrivateIndustrialValidationSource | None = None,
) -> FastAPI:
    (
        session_token,
        session_actor,
        insecure_test_actor_bypass,
        desktop_session_token,
        desktop_startup_secret,
    ) = _session_security_from_environment()
    product_root = Path(
        os.environ.get(
            "VISIONDATA_PRODUCT_ROOT",
            Path.cwd() / "output" / "product",
        )
    )
    owns_service = service is None
    if service is None:
        hosted_mode = (
            os.environ.get("VISIONDATA_AGENTTEAMS_MODE", "off").strip().casefold()
        )
        hosted_agentteams = (
            None if hosted_mode in {"", "off"} else hosted_agentteams_from_environment()
        )
        product_service = ProductService(
            product_root,
            recover_interrupted=False,
            incident_model_planner=incident_model_planner_from_environment(),
            omni_rulepack_path=(
                os.environ.get("VISIONDATA_OMNI_RULEPACK_PATH", "").strip() or None
            ),
            hosted_agentteams=hosted_agentteams,
        )
    else:
        product_service = service
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
        summary="Auditable data-release tasks with an optional hosted Agent transport",
        description=(
            "Local multi-workspace prototype with an optional, explicitly configured "
            "Hosted AgentTeams transport. The transport is not configured by default, "
            "and configuration alone is not proof of a live connection, customer "
            "deployment, production authentication, or production authority."
        ),
        docs_url="/docs",
        redoc_url=None,
        lifespan=lifespan,
    )
    app.state.product_service = product_service
    app.state.evaluation_evidence_source = (
        evaluation_evidence_source or DynamicBenchEvaluationEvidenceSource()
    )
    app.state.industrial_validation_source = (
        industrial_validation_source or PrivateIndustrialValidationSource()
    )
    app.state.operator_image_store = OperatorImageStore(
        product_service.product_root / "operator_workspace"
    )
    configured_origins = {
        value.strip()
        for value in os.environ.get("VISIONDATA_WEB_ORIGINS", "").split(",")
        if value.strip()
    }
    configured_origins.update(
        {
            "http://127.0.0.1:4173",
            "http://127.0.0.1:5173",
            "http://localhost:4173",
            "http://localhost:5173",
        }
    )
    unsafe_browser_methods = {"POST", "PUT", "PATCH", "DELETE"}
    app.add_middleware(
        CORSMiddleware,
        allow_origins=sorted(configured_origins),
        allow_credentials=False,
        allow_methods=["GET", "POST", "PUT", "DELETE", "OPTIONS"],
        allow_headers=[
            "Accept",
            "Content-Type",
            "Idempotency-Key",
            "X-Actor-User-Id",
            "X-Goal3-Handoff-SHA256",
            "X-VisionData-Desktop-Token",
            "X-VisionData-Session-Token",
        ],
        expose_headers=[
            "ETag",
            "X-Content-SHA256",
            "X-Evidence-SHA256",
            "X-Trace-SHA256",
            "X-Incident-Case-SHA256",
            "X-Incident-Decision-SHA256",
            "X-Incident-Interaction-SHA256",
            "X-Decision-Packet-SHA256",
            "X-Audit-Bundle-SHA256",
            "X-Audit-Root-SHA256",
            "X-Signature-Status",
            "X-Incident-Command-Id",
            "X-Visual-Evidence-SHA256",
            "X-Evaluation-Evidence-SHA256",
            "X-Hosted-AgentTeams-Receipt-SHA256",
            "X-Semifinal-Manifest-SHA256",
            "X-Goal3-Handoff-SHA256",
        ],
    )

    @app.middleware("http")
    async def require_bound_local_session(request: Request, call_next) -> Response:
        public_system_routes = {"/v1/health"}
        if desktop_startup_secret:
            public_system_routes.add("/v1/desktop/readiness")
        protected = (
            request.method != "OPTIONS"
            and request.url.path.startswith("/v1/")
            and request.url.path not in public_system_routes
        )
        if not protected:
            return await call_next(request)
        if request.method in unsafe_browser_methods:
            origin = request.headers.get("Origin", "").strip()
            fetch_site = request.headers.get("Sec-Fetch-Site", "").strip().casefold()
            if fetch_site == "cross-site" or (
                origin and origin not in configured_origins
            ):
                return _error_response(
                    "cross_site_request_rejected",
                    "Cross-site browser requests cannot use local session authority.",
                    status.HTTP_403_FORBIDDEN,
                )
        if session_token:
            generic = request.headers.get("X-VisionData-Session-Token", "")
            desktop = request.headers.get("X-VisionData-Desktop-Token", "")
            supplied = generic or desktop
            if generic and desktop and not secrets.compare_digest(generic, desktop):
                supplied = ""
            if not secrets.compare_digest(supplied, session_token):
                return _error_response(
                    "local_session_required",
                    "A valid local session is required.",
                    status.HTTP_401_UNAUTHORIZED,
                )
        elif not insecure_test_actor_bypass:
            return _error_response(
                "local_session_not_configured",
                "Private API routes are disabled until a local session is configured.",
                status.HTTP_503_SERVICE_UNAVAILABLE,
            )
        return await call_next(request)

    if desktop_session_token:
        if desktop_startup_secret:

            @app.get(
                "/v1/desktop/readiness",
                response_class=PlainTextResponse,
                include_in_schema=False,
            )
            def desktop_readiness(
                challenge: Annotated[
                    str,
                    Query(
                        min_length=32,
                        max_length=128,
                        pattern=r"^[0-9a-f]+$",
                    ),
                ],
            ) -> str:
                """Prove that the listener is the child that received the secret.

                The startup secret never crosses the socket. A process that wins the
                loopback-port race sees only a random challenge and cannot forge the
                HMAC expected by the desktop host.
                """

                return hmac.new(
                    desktop_startup_secret.encode("ascii"),
                    challenge.encode("ascii"),
                    hashlib.sha256,
                ).hexdigest()

        @app.post(
            "/v1/desktop/shutdown",
            status_code=status.HTTP_202_ACCEPTED,
            include_in_schema=False,
        )
        def request_desktop_shutdown(request: Request):
            supplied = request.headers.get("X-VisionData-Desktop-Token", "")
            if not secrets.compare_digest(supplied, desktop_session_token):
                return _error_response(
                    "desktop_session_required",
                    "An authenticated desktop session is required.",
                    status.HTTP_403_FORBIDDEN,
                )
            callback = getattr(request.app.state, "desktop_shutdown_callback", None)
            if not callable(callback):
                return {"status": "SHUTDOWN_NOT_AVAILABLE"}
            callback()
            return {"status": "SHUTTING_DOWN"}

    def service_dep(request: Request) -> ProductService:
        return request.app.state.product_service

    def operator_store_dep(request: Request) -> OperatorImageStore:
        return request.app.state.operator_image_store

    def evaluation_evidence_source_dep(
        request: Request,
    ) -> DynamicBenchEvaluationEvidenceSource:
        return request.app.state.evaluation_evidence_source

    def industrial_validation_source_dep(
        request: Request,
    ) -> PrivateIndustrialValidationSource:
        return request.app.state.industrial_validation_source

    Service = Annotated[ProductService, Depends(service_dep)]
    OperatorStore = Annotated[OperatorImageStore, Depends(operator_store_dep)]
    EvaluationEvidenceSource = Annotated[
        DynamicBenchEvaluationEvidenceSource,
        Depends(evaluation_evidence_source_dep),
    ]
    IndustrialValidationSource = Annotated[
        PrivateIndustrialValidationSource,
        Depends(industrial_validation_source_dep),
    ]

    def authenticated_actor(
        actor_header: Annotated[
            str | None,
            Header(alias="X-Actor-User-Id", max_length=256),
        ] = None,
    ) -> str:
        if session_token:
            if actor_header is not None and not secrets.compare_digest(
                actor_header, session_actor
            ):
                raise HTTPException(
                    status_code=status.HTTP_403_FORBIDDEN,
                    detail="actor header does not match the authenticated local session",
                )
            return session_actor
        if insecure_test_actor_bypass:
            candidate = (actor_header or "").strip()
            if not candidate:
                raise HTTPException(
                    status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                    detail="X-Actor-User-Id is required by the explicit test bypass",
                )
            return candidate
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="local session authentication is not configured",
        )

    Actor = Annotated[str, Depends(authenticated_actor)]

    def require_local_provider_management(request: Request) -> None:
        client_host = request.client.host if request.client is not None else ""
        allow_remote = os.environ.get(
            "VISIONDATA_BYOK_ALLOW_REMOTE_MANAGEMENT", "false"
        ).strip().casefold() in {"1", "true", "yes", "on"}
        if not allow_remote and client_host not in {
            "127.0.0.1",
            "::1",
            "localhost",
            "testclient",
        }:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="provider credential management is restricted to loopback",
            )

    LocalProviderManagement = Annotated[
        None, Depends(require_local_provider_management)
    ]

    @app.exception_handler(NotFoundError)
    def not_found(_request: Request, exc: NotFoundError) -> JSONResponse:
        return _error_response(exc.code, str(exc), status.HTTP_404_NOT_FOUND)

    @app.exception_handler(RequestValidationError)
    def request_validation_error(
        _request: Request, _exc: RequestValidationError
    ) -> JSONResponse:
        # Never echo request inputs: provider validation errors may contain API keys.
        return _error_response(
            "invalid_request",
            "the request did not satisfy the accepted schema",
            status.HTTP_422_UNPROCESSABLE_ENTITY,
        )

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

    @app.exception_handler(IncidentCommandUncertainError)
    def incident_command_uncertain(
        _request: Request, exc: IncidentCommandUncertainError
    ) -> JSONResponse:
        response = _error_response(exc.code, str(exc), status.HTTP_409_CONFLICT)
        response.headers["X-Incident-Command-Id"] = exc.command_id
        return response

    @app.exception_handler(ProductStoreError)
    @app.exception_handler(ProductServiceError)
    def product_error(_request: Request, exc: Exception) -> JSONResponse:
        return _error_response(
            getattr(exc, "code", "product_error"),
            "the requested product operation could not be completed",
            status.HTTP_409_CONFLICT,
        )

    @app.exception_handler(OperatorWorkspaceError)
    def operator_workspace_error(
        _request: Request, exc: OperatorWorkspaceError
    ) -> JSONResponse:
        return _error_response(exc.code, str(exc), exc.status_code)

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
        authentication = (
            "session_token_bound_principal"
            if session_token
            else (
                "test_actor_header_bypass"
                if insecure_test_actor_bypass
                else "not_configured_fail_closed"
            )
        )
        return product.health().model_copy(update={"authentication": authentication})

    @app.get(
        "/v1/review/semifinal-demo-manifest",
        response_model=SemifinalDemoManifestProjection,
        tags=["review", "artifacts"],
        description=(
            "Reverify the isolated semifinal manifest against its closed contract "
            "and the ProductRoot currently served. Missing or drifted evidence "
            "returns a SHA-bound HOLD projection and never gains release authority."
        ),
    )
    def get_semifinal_demo_manifest(
        product: Service,
        response: Response,
    ) -> SemifinalDemoManifestProjection:
        projection = SemifinalDemoManifestSource(product.product_root).project(
            product_service=product
        )
        response.headers["ETag"] = f'"{projection.projection_sha256}"'
        response.headers["X-Content-SHA256"] = projection.projection_sha256
        if projection.manifest_sha256 is not None:
            response.headers["X-Semifinal-Manifest-SHA256"] = projection.manifest_sha256
        response.headers["Cache-Control"] = "private, no-store"
        return projection

    def bind_evaluation_projection_headers(
        response: Response,
        projection: DynamicBenchEvaluationEvidenceProjection,
    ) -> None:
        response.headers["ETag"] = f'"{projection.projection_sha256}"'
        response.headers["X-Evaluation-Evidence-SHA256"] = projection.projection_sha256
        response.headers["Cache-Control"] = "no-store"

    @app.get(
        "/v1/review/evaluation-evidence/dynamicbench",
        response_model=DynamicBenchEvaluationEvidenceProjection,
        tags=["review", "evaluation"],
        description=(
            "Read-only global reviewer projection of reverified frozen DynamicBench "
            "v3 orchestration evidence and v4 ProductService/Incident-v6 path "
            "evidence. It never reports factory metrics or production authority."
        ),
    )
    def get_global_dynamicbench_evaluation_evidence(
        source: EvaluationEvidenceSource,
        response: Response,
    ) -> DynamicBenchEvaluationEvidenceProjection:
        projection = source.project(scope=global_evaluation_evidence_scope())
        bind_evaluation_projection_headers(response, projection)
        return projection

    @app.get(
        "/v1/review/evaluation-evidence/industrial-validation",
        response_model=PrivateIndustrialValidationSummary,
        tags=["review", "evaluation", "governance"],
        description=(
            "Read-only reviewer projection that keeps current-environment RC5 VisA "
            "public-proxy evidence, historical Omni offline validation, and "
            "unmeasured factory shadow metrics in separate evidence tracks."
        ),
    )
    def get_global_industrial_validation_evidence(
        source: IndustrialValidationSource,
        response: Response,
    ) -> PrivateIndustrialValidationSummary:
        projection = source.project(scope=global_industrial_validation_scope())
        _bind_sha256_response(response, projection.projection_sha256)
        return projection

    def require_visible_workspace(
        actor: str, workspace_id: str, product: ProductService
    ) -> None:
        if not any(
            workspace.workspace_id == workspace_id
            for workspace in product.list_workspaces(actor)
        ):
            raise NotFoundError("workspace not found")

    def require_project_in_workspace(
        actor: str,
        workspace_id: str,
        project_id: str | None,
        product: ProductService,
    ) -> None:
        if project_id is None:
            return
        project = product.get_project(actor, project_id)
        if project.workspace_id != workspace_id:
            raise NotFoundError("project not found in workspace")

    @app.post(
        "/v1/workspaces/{workspace_id}/hosted-agentteams/probes",
        response_model=HostedAgentTeamsReceipt,
        responses={404: _NOT_FOUND_RESPONSE, 409: _CONFLICT_RESPONSE},
        tags=["hosted-agentteams"],
        description=(
            "Perform a remote read-only control-plane probe and persist a new immutable "
            "evidence attempt. The endpoint never submits a project or delegates work."
        ),
    )
    def probe_hosted_agentteams(
        workspace_id: str,
        response: Response,
        actor: Actor,
        product: Service,
    ) -> HostedAgentTeamsReceipt:
        receipt = product.probe_hosted_agentteams(actor, workspace_id)
        response.headers["ETag"] = f'"{receipt.receipt_sha256}"'
        response.headers["X-Hosted-AgentTeams-Receipt-SHA256"] = receipt.receipt_sha256
        response.headers["Cache-Control"] = "private, no-store"
        return receipt

    @app.get(
        "/v1/operator-workspaces/{workspace_id}/assets",
        response_model=list[OperatorImageAsset],
        responses={404: _NOT_FOUND_RESPONSE, 409: _CONFLICT_RESPONSE},
        tags=["operator-workspace"],
    )
    def list_operator_images(
        workspace_id: str,
        actor: Actor,
        product: Service,
        store: OperatorStore,
        project_id: Annotated[str | None, Query(min_length=1)] = None,
        include_unassigned: bool = False,
    ) -> list[OperatorImageAsset]:
        require_visible_workspace(actor, workspace_id, product)
        require_project_in_workspace(actor, workspace_id, project_id, product)
        return store.list_assets(
            actor,
            workspace_id,
            project_id=project_id,
            include_unassigned=include_unassigned,
        )

    @app.post(
        "/v1/operator-workspaces/{workspace_id}/assets",
        response_model=OperatorImageUploadBatch,
        status_code=status.HTTP_201_CREATED,
        responses={404: _NOT_FOUND_RESPONSE, 409: _CONFLICT_RESPONSE},
        tags=["operator-workspace"],
    )
    async def upload_operator_images(
        workspace_id: str,
        actor: Actor,
        product: Service,
        store: OperatorStore,
        files: Annotated[
            list[UploadFile],
            File(description="One or more local industrial image files."),
        ],
        project_id: Annotated[str | None, Query(min_length=1)] = None,
    ) -> OperatorImageUploadBatch:
        require_visible_workspace(actor, workspace_id, product)
        require_project_in_workspace(actor, workspace_id, project_id, product)
        if not files:
            raise OperatorWorkspaceError(
                "empty_upload_batch", "select at least one image"
            )
        if len(files) > MAX_UPLOAD_FILES:
            raise OperatorWorkspaceError(
                "upload_batch_too_large",
                f"a single upload may contain at most {MAX_UPLOAD_FILES} images",
                status_code=413,
            )
        prepared: list[tuple[str | None, bytes]] = []
        total_bytes = 0
        try:
            for upload in files:
                data = await upload.read(MAX_UPLOAD_BYTES + 1)
                total_bytes += len(data)
                if total_bytes > MAX_UPLOAD_BATCH_BYTES:
                    raise OperatorWorkspaceError(
                        "upload_batch_bytes_too_large",
                        "the combined upload batch exceeds the local safety limit",
                        status_code=413,
                    )
                store.validate_image_upload(data)
                prepared.append((upload.filename, data))
        finally:
            for upload in files:
                await upload.close()
        assets = [
            store.add_image(
                actor,
                workspace_id,
                project_id=project_id,
                filename=filename,
                data=data,
            )
            for filename, data in prepared
        ]
        return OperatorImageUploadBatch(
            workspace_id=workspace_id,
            project_id=project_id,
            uploaded_count=len(assets),
            assets=assets,
        )

    def operator_image_response(
        workspace_id: str,
        asset_id: str,
        actor: str,
        product: ProductService,
        store: OperatorImageStore,
        *,
        variant: str,
    ) -> FileResponse:
        require_visible_workspace(actor, workspace_id, product)
        normalized_variant = "preview" if variant == "preview" else "source"
        path, media_type, digest = store.file_variant(
            actor, workspace_id, asset_id, normalized_variant
        )
        response = FileResponse(path, media_type=media_type)
        response.headers["ETag"] = f'"{digest}"'
        response.headers["X-Content-SHA256"] = digest
        response.headers["Cache-Control"] = "private, max-age=31536000, immutable"
        return response

    @app.get(
        "/v1/operator-workspaces/{workspace_id}/assets/{asset_id}/content",
        responses={404: _NOT_FOUND_RESPONSE, 409: _CONFLICT_RESPONSE},
        tags=["operator-workspace"],
    )
    def get_operator_image_content(
        workspace_id: str,
        asset_id: str,
        actor: Actor,
        product: Service,
        store: OperatorStore,
    ) -> FileResponse:
        return operator_image_response(
            workspace_id, asset_id, actor, product, store, variant="source"
        )

    @app.get(
        "/v1/operator-workspaces/{workspace_id}/assets/{asset_id}/preview",
        responses={404: _NOT_FOUND_RESPONSE, 409: _CONFLICT_RESPONSE},
        tags=["operator-workspace"],
    )
    def get_operator_image_preview(
        workspace_id: str,
        asset_id: str,
        actor: Actor,
        product: Service,
        store: OperatorStore,
    ) -> FileResponse:
        return operator_image_response(
            workspace_id, asset_id, actor, product, store, variant="preview"
        )

    @app.get(
        "/v1/operator-workspaces/{workspace_id}/assets/{asset_id}/annotations",
        response_model=OperatorAnnotationState,
        responses={404: _NOT_FOUND_RESPONSE, 409: _CONFLICT_RESPONSE},
        tags=["operator-workspace"],
    )
    def get_operator_annotations(
        workspace_id: str,
        asset_id: str,
        actor: Actor,
        product: Service,
        store: OperatorStore,
    ) -> OperatorAnnotationState:
        require_visible_workspace(actor, workspace_id, product)
        return store.get_annotations(actor, workspace_id, asset_id)

    @app.put(
        "/v1/operator-workspaces/{workspace_id}/assets/{asset_id}/annotations",
        response_model=OperatorAnnotationState,
        responses={404: _NOT_FOUND_RESPONSE, 409: _CONFLICT_RESPONSE},
        tags=["operator-workspace"],
    )
    def save_operator_annotations(
        workspace_id: str,
        asset_id: str,
        payload: SaveAnnotationsRequest,
        actor: Actor,
        product: Service,
        store: OperatorStore,
    ) -> OperatorAnnotationState:
        require_visible_workspace(actor, workspace_id, product)
        return store.save_annotations(actor, workspace_id, asset_id, payload)

    @app.get(
        "/v1/operator-workspaces/{workspace_id}/assets/{asset_id}/analysis-runs",
        response_model=list[OperatorAnalysisRunState],
        responses={404: _NOT_FOUND_RESPONSE, 409: _CONFLICT_RESPONSE},
        tags=["operator-workspace"],
    )
    def list_operator_analysis_runs(
        workspace_id: str,
        asset_id: str,
        actor: Actor,
        product: Service,
        store: OperatorStore,
    ) -> list[OperatorAnalysisRunState]:
        require_visible_workspace(actor, workspace_id, product)
        return store.list_analysis_runs(actor, workspace_id, asset_id)

    @app.post(
        "/v1/operator-workspaces/{workspace_id}/assets/{asset_id}/analysis-runs",
        response_model=OperatorAnalysisRunState,
        status_code=status.HTTP_201_CREATED,
        responses={404: _NOT_FOUND_RESPONSE, 409: _CONFLICT_RESPONSE},
        tags=["operator-workspace"],
    )
    def create_operator_analysis_run(
        workspace_id: str,
        asset_id: str,
        actor: Actor,
        product: Service,
        store: OperatorStore,
    ) -> OperatorAnalysisRunState:
        require_visible_workspace(actor, workspace_id, product)
        return store.create_analysis_run(actor, workspace_id, asset_id)

    @app.get(
        (
            "/v1/operator-workspaces/{workspace_id}/assets/{asset_id}/"
            "analysis-runs/{analysis_run_id}/copilot-turns"
        ),
        response_model=list[OperatorCopilotTurnState],
        responses={404: _NOT_FOUND_RESPONSE, 409: _CONFLICT_RESPONSE},
        tags=["operator-workspace"],
    )
    def list_operator_copilot_turns(
        workspace_id: str,
        asset_id: str,
        analysis_run_id: str,
        actor: Actor,
        product: Service,
        store: OperatorStore,
    ) -> list[OperatorCopilotTurnState]:
        require_visible_workspace(actor, workspace_id, product)
        return store.list_copilot_turns(actor, workspace_id, asset_id, analysis_run_id)

    @app.post(
        (
            "/v1/operator-workspaces/{workspace_id}/assets/{asset_id}/"
            "analysis-runs/{analysis_run_id}/copilot-turns"
        ),
        response_model=OperatorCopilotTurnState,
        status_code=status.HTTP_201_CREATED,
        responses={404: _NOT_FOUND_RESPONSE, 409: _CONFLICT_RESPONSE},
        tags=["operator-workspace"],
    )
    def create_operator_copilot_turn(
        workspace_id: str,
        asset_id: str,
        analysis_run_id: str,
        payload: CreateOperatorCopilotTurnRequest,
        actor: Actor,
        product: Service,
        store: OperatorStore,
    ) -> OperatorCopilotTurnState:
        require_visible_workspace(actor, workspace_id, product)
        return store.create_copilot_turn(
            actor, workspace_id, asset_id, analysis_run_id, payload
        )

    @app.get(
        "/v1/operator-workspaces/{workspace_id}/work-orders",
        response_model=list[OperatorWorkOrderState],
        responses={404: _NOT_FOUND_RESPONSE, 409: _CONFLICT_RESPONSE},
        tags=["operator-workspace"],
    )
    def list_operator_work_orders(
        workspace_id: str,
        actor: Actor,
        product: Service,
        store: OperatorStore,
        project_id: Annotated[str | None, Query(min_length=1)] = None,
        include_unassigned: bool = False,
    ) -> list[OperatorWorkOrderState]:
        require_visible_workspace(actor, workspace_id, product)
        require_project_in_workspace(actor, workspace_id, project_id, product)
        return store.list_work_orders(
            actor,
            workspace_id,
            project_id=project_id,
            include_unassigned=include_unassigned,
        )

    @app.post(
        "/v1/operator-workspaces/{workspace_id}/assets/{asset_id}/work-orders",
        response_model=OperatorWorkOrderState,
        status_code=status.HTTP_201_CREATED,
        responses={404: _NOT_FOUND_RESPONSE, 409: _CONFLICT_RESPONSE},
        tags=["operator-workspace"],
    )
    def create_operator_work_order(
        workspace_id: str,
        asset_id: str,
        payload: CreateOperatorWorkOrderRequest,
        actor: Actor,
        product: Service,
        store: OperatorStore,
    ) -> OperatorWorkOrderState:
        require_visible_workspace(actor, workspace_id, product)
        return store.create_work_order(actor, workspace_id, asset_id, payload)

    @app.put(
        "/v1/operator-workspaces/{workspace_id}/work-orders/{work_order_id}",
        response_model=OperatorWorkOrderState,
        responses={404: _NOT_FOUND_RESPONSE, 409: _CONFLICT_RESPONSE},
        tags=["operator-workspace"],
    )
    def update_operator_work_order(
        workspace_id: str,
        work_order_id: str,
        payload: UpdateOperatorWorkOrderRequest,
        actor: Actor,
        product: Service,
        store: OperatorStore,
    ) -> OperatorWorkOrderState:
        require_visible_workspace(actor, workspace_id, product)
        return store.update_work_order(actor, workspace_id, work_order_id, payload)

    @app.get(
        "/v1/operator-workspaces/{workspace_id}/work-orders/{work_order_id}/crop",
        responses={404: _NOT_FOUND_RESPONSE, 409: _CONFLICT_RESPONSE},
        tags=["operator-workspace"],
    )
    def get_operator_work_order_crop(
        workspace_id: str,
        work_order_id: str,
        actor: Actor,
        product: Service,
        store: OperatorStore,
    ) -> FileResponse:
        require_visible_workspace(actor, workspace_id, product)
        path, digest = store.work_order_crop(actor, workspace_id, work_order_id)
        response = FileResponse(path, media_type="image/jpeg")
        response.headers["ETag"] = f'"{digest}"'
        response.headers["X-Content-SHA256"] = digest
        response.headers["Cache-Control"] = "private, max-age=31536000, immutable"
        return response

    @app.get(
        "/v1/industrial-incidents/runtime-capabilities",
        response_model=IncidentRuntimeCapabilities,
        tags=["industrial-incidents"],
    )
    def industrial_incident_runtime_capabilities(
        product: Service,
    ) -> IncidentRuntimeCapabilities:
        return product.incident_runtime_capabilities()

    @app.get(
        "/v1/provider-profiles",
        response_model=list[ProviderProfileRecord],
        responses={404: _NOT_FOUND_RESPONSE},
        tags=["provider-profiles"],
    )
    def list_provider_profiles(
        workspace_id: Annotated[str, Query(min_length=1, max_length=160)],
        actor: Actor,
        product: Service,
        _local_management: LocalProviderManagement,
        response: Response,
    ) -> list[ProviderProfileRecord]:
        response.headers["Cache-Control"] = "no-store"
        return product.list_provider_profiles(actor, workspace_id)

    @app.post(
        "/v1/provider-profiles/test-connection",
        response_model=ProviderConnectionTestResult,
        responses={404: _NOT_FOUND_RESPONSE, 409: _CONFLICT_RESPONSE},
        tags=["provider-profiles"],
    )
    def test_provider_connection(
        payload: ProviderConnectionTestRequest,
        actor: Actor,
        product: Service,
        _local_management: LocalProviderManagement,
        response: Response,
    ) -> ProviderConnectionTestResult:
        response.headers["Cache-Control"] = "no-store"
        return product.test_provider_connection(actor, payload)

    @app.post(
        "/v1/provider-profiles",
        response_model=ProviderProfileRecord,
        status_code=status.HTTP_201_CREATED,
        responses={404: _NOT_FOUND_RESPONSE, 409: _CONFLICT_RESPONSE},
        tags=["provider-profiles"],
    )
    def create_provider_profile(
        payload: ProviderProfileCreateRequest,
        actor: Actor,
        product: Service,
        _local_management: LocalProviderManagement,
        response: Response,
    ) -> ProviderProfileRecord:
        profile = product.create_provider_profile(actor, payload)
        response.headers["Location"] = f"/v1/provider-profiles/{profile.profile_id}"
        response.headers["Cache-Control"] = "no-store"
        return profile

    @app.post(
        "/v1/provider-profiles/{profile_id}/test-connection",
        response_model=ProviderConnectionTestResult,
        responses={404: _NOT_FOUND_RESPONSE, 409: _CONFLICT_RESPONSE},
        tags=["provider-profiles"],
    )
    def test_saved_provider_connection(
        profile_id: str,
        actor: Actor,
        product: Service,
        _local_management: LocalProviderManagement,
        response: Response,
    ) -> ProviderConnectionTestResult:
        response.headers["Cache-Control"] = "no-store"
        return product.test_saved_provider_connection(actor, profile_id)

    @app.put(
        "/v1/provider-profiles/{profile_id}/default",
        response_model=ProviderProfileRecord,
        responses={404: _NOT_FOUND_RESPONSE},
        tags=["provider-profiles"],
    )
    def set_default_provider_profile(
        profile_id: str,
        actor: Actor,
        product: Service,
        _local_management: LocalProviderManagement,
        response: Response,
    ) -> ProviderProfileRecord:
        response.headers["Cache-Control"] = "no-store"
        return product.set_default_provider_profile(actor, profile_id)

    @app.delete(
        "/v1/provider-profiles/{profile_id}",
        response_model=ProviderProfileRecord,
        responses={404: _NOT_FOUND_RESPONSE, 409: _CONFLICT_RESPONSE},
        tags=["provider-profiles"],
    )
    def revoke_provider_profile(
        profile_id: str,
        actor: Actor,
        product: Service,
        _local_management: LocalProviderManagement,
        response: Response,
    ) -> ProviderProfileRecord:
        response.headers["Cache-Control"] = "no-store"
        return product.revoke_provider_profile(actor, profile_id)

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

    @app.get(
        "/v1/workspaces/{workspace_id}/evaluation-evidence/dynamicbench",
        response_model=DynamicBenchEvaluationEvidenceProjection,
        responses={404: _NOT_FOUND_RESPONSE},
        tags=["workspaces", "projects", "evaluation"],
        description=(
            "Return the same global frozen evidence as a read-only workspace or "
            "project reference. Scope checks grant visibility only; they do not turn "
            "DynamicBench into project-derived or factory-derived evidence."
        ),
    )
    def get_scoped_dynamicbench_evaluation_evidence(
        workspace_id: str,
        actor: Actor,
        product: Service,
        source: EvaluationEvidenceSource,
        response: Response,
        project_id: Annotated[str | None, Query(min_length=1)] = None,
    ) -> DynamicBenchEvaluationEvidenceProjection:
        require_visible_workspace(actor, workspace_id, product)
        require_project_in_workspace(actor, workspace_id, project_id, product)
        projection = source.project(
            scope=scoped_evaluation_evidence_scope(
                workspace_id=workspace_id,
                project_id=project_id,
            )
        )
        bind_evaluation_projection_headers(response, projection)
        return projection

    @app.get(
        "/v1/workspaces/{workspace_id}/evaluation-evidence/industrial-validation",
        response_model=PrivateIndustrialValidationSummary,
        responses={404: _NOT_FOUND_RESPONSE},
        tags=["workspaces", "projects", "evaluation", "governance"],
        description=(
            "Return the global bounded industrial-validation evidence as a read-only "
            "workspace or project reference; the association is not project-derived."
        ),
    )
    def get_scoped_industrial_validation_evidence(
        workspace_id: str,
        actor: Actor,
        product: Service,
        source: IndustrialValidationSource,
        response: Response,
        project_id: Annotated[str | None, Query(min_length=1)] = None,
    ) -> PrivateIndustrialValidationSummary:
        require_visible_workspace(actor, workspace_id, product)
        require_project_in_workspace(actor, workspace_id, project_id, product)
        projection = source.project(
            scope=scoped_industrial_validation_scope(
                workspace_id=workspace_id,
                project_id=project_id,
            )
        )
        _bind_sha256_response(response, projection.projection_sha256)
        return projection

    @app.get(
        "/v1/projects/{project_id}/governance-effectiveness",
        response_model=ProjectGovernanceEffectivenessSummary,
        responses={404: _NOT_FOUND_RESPONSE, 409: _CONFLICT_RESPONSE},
        tags=["projects", "evaluation", "governance"],
    )
    def get_project_governance_effectiveness(
        project_id: str,
        actor: Actor,
        product: Service,
    ) -> ProjectGovernanceEffectivenessSummary:
        return product.project_governance_effectiveness(actor, project_id)

    @app.post(
        "/v1/data-sources/local-authorizations",
        response_model=LocalSourceAuthorizationReceipt,
        status_code=status.HTTP_201_CREATED,
        responses={404: _NOT_FOUND_RESPONSE, 409: _CONFLICT_RESPONSE},
        tags=["data-sources"],
    )
    def authorize_local_source(
        payload: AuthorizeLocalSourceRequest,
        actor: Actor,
        product: Service,
    ) -> LocalSourceAuthorizationReceipt:
        return product.authorize_local_source(actor, payload)

    @app.post(
        "/v1/data-sources/operator-project-snapshots",
        response_model=LocalSourceAuthorizationReceipt,
        status_code=status.HTTP_201_CREATED,
        responses={404: _NOT_FOUND_RESPONSE, 409: _CONFLICT_RESPONSE},
        tags=["data-sources", "operator-workspace"],
    )
    def authorize_operator_project_snapshot(
        payload: AuthorizeOperatorProjectSnapshotRequest,
        actor: Actor,
        product: Service,
        store: OperatorStore,
    ) -> LocalSourceAuthorizationReceipt:
        return product.authorize_operator_project_snapshot(actor, payload, store)

    @app.get(
        "/v1/data-sources",
        response_model=list[LocalSourceAuthorizationReceipt],
        responses={404: _NOT_FOUND_RESPONSE},
        tags=["data-sources"],
    )
    def list_local_sources(
        workspace_id: Annotated[str, Query(min_length=1)],
        actor: Actor,
        product: Service,
    ) -> list[LocalSourceAuthorizationReceipt]:
        return product.list_local_source_authorizations(actor, workspace_id)

    @app.get(
        "/v1/data-sources/{source_id}",
        response_model=LocalSourceAuthorizationReceipt,
        responses={404: _NOT_FOUND_RESPONSE},
        tags=["data-sources"],
    )
    def get_local_source(
        source_id: str, actor: Actor, product: Service
    ) -> LocalSourceAuthorizationReceipt:
        return product.get_local_source_authorization(actor, source_id)

    @app.get(
        "/v1/data-sources/{source_id}/authorization-events",
        response_model=list[SourceAuthorizationEventReceipt],
        responses={404: _NOT_FOUND_RESPONSE, 409: _CONFLICT_RESPONSE},
        tags=["data-sources"],
    )
    def list_source_authorization_events(
        source_id: str, actor: Actor, product: Service
    ) -> list[SourceAuthorizationEventReceipt]:
        return product.list_source_authorization_events(actor, source_id)

    @app.post(
        "/v1/data-sources/{source_id}/revocations",
        response_model=SourceAuthorizationEventReceipt,
        status_code=status.HTTP_201_CREATED,
        responses={404: _NOT_FOUND_RESPONSE, 409: _CONFLICT_RESPONSE},
        tags=["data-sources"],
    )
    def revoke_local_source(
        source_id: str,
        payload: RevokeLocalSourceAuthorizationRequest,
        actor: Actor,
        product: Service,
    ) -> SourceAuthorizationEventReceipt:
        return product.revoke_local_source_authorization(actor, source_id, payload)

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
        "/v1/tasks/{task_id}/goal3-handoff",
        response_model=Goal3HandoffReceipt,
        responses={404: _NOT_FOUND_RESPONSE, 409: _CONFLICT_RESPONSE},
        tags=["tasks", "industrial-incidents"],
        description=(
            "Return the SHA-bound, read-only handoff state from a Goal task into "
            "Goal3 Incident intake. This endpoint never creates an Incident and "
            "never supplies missing industrial evidence."
        ),
    )
    def get_goal3_handoff(
        task_id: str,
        response: Response,
        actor: Actor,
        product: Service,
    ) -> Goal3HandoffReceipt:
        receipt = product.goal3_handoff_receipt(actor, task_id)
        response.headers["ETag"] = f'"{receipt.receipt_sha256}"'
        response.headers["X-Goal3-Handoff-SHA256"] = receipt.receipt_sha256
        response.headers["Cache-Control"] = "private, no-store"
        return receipt

    @app.post(
        "/v1/tasks/{task_id}/hosted-agentteams/submissions",
        response_model=HostedAgentTeamsReceipt,
        status_code=status.HTTP_201_CREATED,
        responses={404: _NOT_FOUND_RESPONSE, 409: _CONFLICT_RESPONSE},
        tags=["hosted-agentteams"],
        description=(
            "Submit the existing visible task through the explicitly gated Hosted "
            "AgentTeams transport. A named approval_id is mandatory; task creation and "
            "task execution never trigger this endpoint automatically."
        ),
    )
    def submit_task_to_hosted_agentteams(
        task_id: str,
        payload: SubmitHostedAgentTeamsTaskRequest,
        response: Response,
        actor: Actor,
        product: Service,
    ) -> HostedAgentTeamsReceipt:
        receipt = product.submit_task_to_hosted_agentteams(actor, task_id, payload)
        response.headers["ETag"] = f'"{receipt.receipt_sha256}"'
        response.headers["X-Hosted-AgentTeams-Receipt-SHA256"] = receipt.receipt_sha256
        response.headers["Cache-Control"] = "private, no-store"
        return receipt

    @app.get(
        "/v1/tasks/{task_id}/plan",
        response_model=TaskPlanPreview,
        responses={404: _NOT_FOUND_RESPONSE},
        tags=["tasks"],
    )
    def get_task_plan(task_id: str, actor: Actor, product: Service) -> TaskPlanPreview:
        return product.task_plan_preview(actor, task_id)

    @app.get(
        "/v1/tasks/{task_id}/preflight",
        response_model=TaskPreflightReport,
        responses={404: _NOT_FOUND_RESPONSE},
        tags=["tasks"],
    )
    def get_task_preflight(
        task_id: str, actor: Actor, product: Service
    ) -> TaskPreflightReport:
        return product.task_preflight(actor, task_id)

    @app.post(
        "/v1/tasks/{task_id}/reverifications",
        response_model=TaskRecord,
        status_code=status.HTTP_202_ACCEPTED,
        responses={404: _NOT_FOUND_RESPONSE, 409: _CONFLICT_RESPONSE},
        tags=["tasks"],
    )
    def create_task_reverification(
        task_id: str,
        payload: CreateReverificationRequest,
        actor: Actor,
        product: Service,
        response: Response,
        idempotency_key: Annotated[
            str | None, Header(alias="Idempotency-Key", max_length=120)
        ] = None,
    ) -> TaskRecord:
        child = product.create_reverification_task(
            actor,
            task_id,
            payload,
            idempotency_key=idempotency_key,
        )
        response.headers["Location"] = f"/v1/tasks/{child.task_id}"
        return child

    @app.get(
        "/v1/tasks/{task_id}/lineage",
        response_model=TaskLineageReport,
        responses={404: _NOT_FOUND_RESPONSE, 409: _CONFLICT_RESPONSE},
        tags=["tasks"],
    )
    def get_task_lineage(
        task_id: str, response: Response, actor: Actor, product: Service
    ) -> TaskLineageReport:
        report = product.task_lineage(actor, task_id)
        _bind_sha256_response(response, report.report_sha256)
        return report

    @app.post(
        "/v1/tasks/{task_id}/interventions",
        response_model=TaskInterventionRecord,
        status_code=status.HTTP_201_CREATED,
        responses={404: _NOT_FOUND_RESPONSE, 409: _CONFLICT_RESPONSE},
        tags=["tasks"],
    )
    def intervene_task(
        task_id: str,
        payload: TaskInterventionRequest,
        actor: Actor,
        product: Service,
    ) -> TaskInterventionRecord:
        return product.intervene_task(actor, task_id, payload)

    @app.get(
        "/v1/tasks/{task_id}/interventions",
        response_model=list[TaskInterventionRecord],
        responses={404: _NOT_FOUND_RESPONSE},
        tags=["tasks"],
    )
    def get_task_interventions(
        task_id: str, actor: Actor, product: Service
    ) -> list[TaskInterventionRecord]:
        return product.list_interventions(actor, task_id)

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
            headers={
                "ETag": f'"{task.trace_sha256}"',
                "X-Trace-SHA256": task.trace_sha256 or "",
            },
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

    @app.get(
        "/v1/tasks/{task_id}/industrial-delivery",
        response_model=IndustrialDeliveryReceipt,
        responses={404: _NOT_FOUND_RESPONSE, 409: _CONFLICT_RESPONSE},
        tags=["artifacts"],
    )
    def get_industrial_delivery(
        task_id: str, response: Response, actor: Actor, product: Service
    ) -> IndustrialDeliveryReceipt:
        receipt = product.industrial_delivery_receipt(actor, task_id)
        receipt_sha256 = hashlib.sha256(canonical_json_bytes(receipt)).hexdigest()
        response.headers["ETag"] = f'"{receipt_sha256}"'
        response.headers["X-Content-SHA256"] = receipt_sha256
        response.headers["Cache-Control"] = "private, no-store"
        return receipt

    @app.get(
        "/v1/tasks/{task_id}/visual-evidence",
        response_model=TaskVisualEvidenceManifest,
        responses={404: _NOT_FOUND_RESPONSE, 409: _CONFLICT_RESPONSE},
        tags=["artifacts"],
        description=(
            "Return a SHA-bound projection of frozen Operator Snapshot previews and "
            "the deterministic findings measured by the completed task."
        ),
    )
    def get_task_visual_evidence(
        task_id: str,
        response: Response,
        actor: Actor,
        product: Service,
    ) -> TaskVisualEvidenceManifest:
        manifest = product.task_visual_evidence_manifest(actor, task_id)
        response.headers["ETag"] = f'"{manifest.manifest_sha256}"'
        response.headers["X-Visual-Evidence-SHA256"] = manifest.manifest_sha256
        response.headers["Cache-Control"] = "private, no-store"
        return manifest

    @app.get(
        "/v1/tasks/{task_id}/visual-evidence/{sample_id}/preview",
        response_class=FileResponse,
        responses={404: _NOT_FOUND_RESPONSE, 409: _CONFLICT_RESPONSE},
        tags=["artifacts"],
    )
    def get_task_visual_evidence_preview(
        task_id: str,
        sample_id: str,
        actor: Actor,
        product: Service,
    ) -> FileResponse:
        path, media_type, digest = product.task_visual_evidence_path(
            actor,
            task_id,
            sample_id,
            variant="preview",
        )
        return FileResponse(
            path,
            media_type=media_type,
            filename=f"{sample_id}-frozen-preview.jpg",
            headers={
                "ETag": f'"{digest}"',
                "X-Content-SHA256": digest,
                "Cache-Control": "private, no-store",
            },
        )

    @app.get(
        "/v1/tasks/{task_id}/visual-evidence/{sample_id}/mask",
        response_class=FileResponse,
        responses={404: _NOT_FOUND_RESPONSE, 409: _CONFLICT_RESPONSE},
        tags=["artifacts"],
    )
    def get_task_visual_evidence_mask(
        task_id: str,
        sample_id: str,
        actor: Actor,
        product: Service,
    ) -> FileResponse:
        path, media_type, digest = product.task_visual_evidence_path(
            actor,
            task_id,
            sample_id,
            variant="mask",
        )
        return FileResponse(
            path,
            media_type=media_type,
            filename=f"{sample_id}-frozen-mask.png",
            headers={
                "ETag": f'"{digest}"',
                "X-Content-SHA256": digest,
                "Cache-Control": "private, no-store",
            },
        )

    @app.post(
        "/v1/tasks/{task_id}/industrial-incidents",
        response_model=IndustrialIncidentCase,
        status_code=status.HTTP_201_CREATED,
        responses={404: _NOT_FOUND_RESPONSE, 409: _CONFLICT_RESPONSE},
        tags=["industrial-incidents"],
    )
    def create_industrial_incident(
        task_id: str,
        payload: IndustrialIncidentRequest,
        response: Response,
        actor: Actor,
        product: Service,
        idempotency_key: Annotated[
            str | None, Header(alias="Idempotency-Key", max_length=120)
        ] = None,
        expected_goal3_handoff_sha256: Annotated[
            str | None,
            Header(
                alias="X-Goal3-Handoff-SHA256",
                pattern=r"^[0-9a-f]{64}$",
            ),
        ] = None,
    ) -> IndustrialIncidentCase:
        if expected_goal3_handoff_sha256 is not None:
            handoff = product.goal3_handoff_receipt(actor, task_id)
            if not secrets.compare_digest(
                handoff.receipt_sha256,
                expected_goal3_handoff_sha256,
            ):
                raise ConflictError(
                    "Goal3 handoff receipt changed; refresh the task boundary before "
                    "creating an Incident"
                )
            if (
                handoff.handoff_status != "READY_FOR_INCIDENT_INTAKE"
                or not handoff.incident_intake_permitted
            ):
                raise ConflictError(
                    "Goal3 handoff is not ready for a new Incident intake"
                )
        resolved_key = resolve_incident_idempotency_key(idempotency_key, payload)
        command_id = incident_command_id(
            task_id=task_id,
            operation=IncidentCommandKind.CREATE_CASE,
            target_case_id=None,
            idempotency_key=resolved_key,
        )
        case = product.create_industrial_incident_case(
            actor,
            task_id,
            payload,
            idempotency_key=resolved_key,
        )
        response.headers["Location"] = (
            f"/v1/tasks/{task_id}/industrial-incidents/{case.case_id}"
        )
        response.headers["X-Incident-Command-Id"] = command_id
        response.headers["ETag"] = f'"{case.case_sha256}"'
        response.headers["X-Incident-Case-SHA256"] = case.case_sha256
        response.headers["Cache-Control"] = "private, no-store"
        return case

    @app.get(
        "/v1/tasks/{task_id}/industrial-incident-commands/{command_id}",
        response_model=IncidentCommandReceipt,
        responses={404: _NOT_FOUND_RESPONSE, 409: _CONFLICT_RESPONSE},
        tags=["industrial-incidents"],
    )
    def get_industrial_incident_command(
        task_id: str,
        command_id: str,
        response: Response,
        actor: Actor,
        product: Service,
    ) -> IncidentCommandReceipt:
        receipt = product.get_incident_command_receipt(actor, task_id, command_id)
        _bind_sha256_response(response, _canonical_content_sha256(receipt))
        return receipt

    @app.get(
        "/v1/tasks/{task_id}/industrial-incidents",
        response_model=list[IndustrialIncidentCase],
        responses={404: _NOT_FOUND_RESPONSE},
        tags=["industrial-incidents"],
    )
    def list_industrial_incidents(
        task_id: str, response: Response, actor: Actor, product: Service
    ) -> list[IndustrialIncidentCase]:
        cases = product.list_industrial_incident_cases(actor, task_id)
        _bind_sha256_response(response, _canonical_content_sha256(cases))
        return cases

    @app.get(
        "/v1/tasks/{task_id}/industrial-incidents/{case_id}",
        response_model=IndustrialIncidentCase,
        responses={404: _NOT_FOUND_RESPONSE, 409: _CONFLICT_RESPONSE},
        tags=["industrial-incidents"],
    )
    def get_industrial_incident(
        task_id: str,
        case_id: str,
        response: Response,
        actor: Actor,
        product: Service,
    ) -> IndustrialIncidentCase:
        case = product.get_industrial_incident_case(actor, task_id, case_id)
        response.headers["ETag"] = f'"{case.case_sha256}"'
        response.headers["X-Incident-Case-SHA256"] = case.case_sha256
        response.headers["Cache-Control"] = "private, no-store"
        return case

    @app.get(
        "/v1/tasks/{task_id}/industrial-incidents/{case_id}/interaction-receipt",
        response_model=IncidentInteractionReceipt,
        responses={404: _NOT_FOUND_RESPONSE, 409: _CONFLICT_RESPONSE},
        tags=["industrial-incidents"],
    )
    def get_industrial_incident_interaction_receipt(
        task_id: str,
        case_id: str,
        response: Response,
        actor: Actor,
        product: Service,
    ) -> IncidentInteractionReceipt:
        receipt = product.get_industrial_incident_interaction_receipt(
            actor,
            task_id,
            case_id,
        )
        response.headers["ETag"] = f'"{receipt.receipt_sha256}"'
        response.headers["X-Incident-Interaction-SHA256"] = receipt.receipt_sha256
        response.headers["Cache-Control"] = "private, no-store"
        return receipt

    @app.get(
        "/v1/tasks/{task_id}/industrial-incidents/{case_id}/audit-envelope",
        response_model=GovernedAuditEnvelope,
        responses={404: _NOT_FOUND_RESPONSE, 409: _CONFLICT_RESPONSE},
        tags=["industrial-incidents"],
    )
    def get_industrial_incident_audit_envelope(
        task_id: str,
        case_id: str,
        response: Response,
        actor: Actor,
        product: Service,
    ) -> GovernedAuditEnvelope:
        envelope = product.get_industrial_incident_audit_envelope(
            actor,
            task_id,
            case_id,
        )
        response.headers["ETag"] = f'"{envelope.audit_root.value}"'
        response.headers["X-Audit-Root-SHA256"] = envelope.audit_root.value
        response.headers["X-Signature-Status"] = envelope.signature.status
        response.headers["Cache-Control"] = "private, no-store"
        return envelope

    @app.get(
        "/v1/tasks/{task_id}/industrial-incidents/{case_id}/runtime-profile-binding",
        response_model=IncidentRuntimeProfileBinding,
        responses={404: _NOT_FOUND_RESPONSE, 409: _CONFLICT_RESPONSE},
        tags=["industrial-incidents"],
    )
    def get_industrial_incident_runtime_profile_binding(
        task_id: str,
        case_id: str,
        response: Response,
        actor: Actor,
        product: Service,
    ) -> IncidentRuntimeProfileBinding:
        binding = product.get_industrial_incident_runtime_profile_binding(
            actor,
            task_id,
            case_id,
        )
        _bind_sha256_response(response, binding.binding_sha256)
        return binding

    @app.get(
        "/v1/tasks/{task_id}/industrial-incidents/{case_id}/governed-context",
        response_model=AssembledIncidentContext,
        responses={404: _NOT_FOUND_RESPONSE, 409: _CONFLICT_RESPONSE},
        tags=["industrial-incidents"],
    )
    def get_industrial_incident_governed_context(
        task_id: str,
        case_id: str,
        response: Response,
        actor: Actor,
        product: Service,
    ) -> AssembledIncidentContext:
        assembled = product.get_industrial_incident_governed_context(
            actor,
            task_id,
            case_id,
        )
        _bind_sha256_response(response, _canonical_content_sha256(assembled))
        return assembled

    @app.get(
        "/v1/tasks/{task_id}/industrial-incidents/{case_id}/phase-events",
        response_model=list[IncidentPhaseEvent],
        responses={404: _NOT_FOUND_RESPONSE, 409: _CONFLICT_RESPONSE},
        tags=["industrial-incidents"],
    )
    def list_industrial_incident_phase_events(
        task_id: str,
        case_id: str,
        response: Response,
        actor: Actor,
        product: Service,
    ) -> list[IncidentPhaseEvent]:
        events = product.list_industrial_incident_phase_events(actor, task_id, case_id)
        _bind_sha256_response(response, _canonical_content_sha256(events))
        return events

    @app.get(
        "/v1/tasks/{task_id}/industrial-incidents/{case_id}/control-plane",
        response_model=IncidentControlPlaneBundle,
        responses={404: _NOT_FOUND_RESPONSE, 409: _CONFLICT_RESPONSE},
        tags=["industrial-incidents"],
    )
    def get_industrial_incident_control_plane(
        task_id: str,
        case_id: str,
        response: Response,
        actor: Actor,
        product: Service,
    ) -> IncidentControlPlaneBundle:
        bundle = product.get_industrial_incident_control_plane(
            actor,
            task_id,
            case_id,
        )
        _bind_sha256_response(response, bundle.bundle_sha256)
        return bundle

    @app.get(
        "/v1/tasks/{task_id}/industrial-incidents/{case_id}/decision-packet",
        response_model=IndustrialQualityDecisionPacket,
        responses={404: _NOT_FOUND_RESPONSE, 409: _CONFLICT_RESPONSE},
        tags=["industrial-incidents"],
    )
    def get_industrial_incident_decision_packet(
        task_id: str,
        case_id: str,
        response: Response,
        actor: Actor,
        product: Service,
    ) -> IndustrialQualityDecisionPacket:
        packet = product.get_industrial_incident_decision_packet(
            actor,
            task_id,
            case_id,
        )
        _bind_sha256_response(
            response,
            packet.packet_sha256,
            header_name="X-Decision-Packet-SHA256",
        )
        return packet

    @app.get(
        "/v1/tasks/{task_id}/industrial-incidents/{case_id}/review-projection",
        response_model=IncidentReviewProjection,
        responses={404: _NOT_FOUND_RESPONSE, 409: _CONFLICT_RESPONSE},
        tags=["industrial-incidents"],
    )
    def get_industrial_incident_review_projection(
        task_id: str,
        case_id: str,
        response: Response,
        actor: Actor,
        product: Service,
    ) -> IncidentReviewProjection:
        projection = product.get_industrial_incident_review_projection(
            actor,
            task_id,
            case_id,
        )
        _bind_sha256_response(response, projection.projection_sha256)
        return projection

    @app.get(
        "/v1/tasks/{task_id}/industrial-incidents/{case_id}/decision-packet.html",
        responses={404: _NOT_FOUND_RESPONSE, 409: _CONFLICT_RESPONSE},
        tags=["industrial-incidents"],
    )
    def get_industrial_incident_decision_packet_html(
        task_id: str,
        case_id: str,
        actor: Actor,
        product: Service,
    ) -> Response:
        exports = product.get_industrial_incident_decision_packet_exports(
            actor,
            task_id,
            case_id,
        )
        content_sha256 = hashlib.sha256(exports.decision_packet_html).hexdigest()
        return Response(
            content=exports.decision_packet_html,
            media_type="text/html",
            headers={
                "ETag": f'"{content_sha256}"',
                "X-Decision-Packet-SHA256": exports.receipt.packet_sha256,
                "X-Content-SHA256": content_sha256,
                "Cache-Control": "private, no-store",
            },
        )

    @app.get(
        "/v1/tasks/{task_id}/industrial-incidents/{case_id}/decision-packet/audit-bundle",
        responses={404: _NOT_FOUND_RESPONSE, 409: _CONFLICT_RESPONSE},
        tags=["industrial-incidents"],
    )
    def get_industrial_incident_decision_packet_audit_bundle(
        task_id: str,
        case_id: str,
        actor: Actor,
        product: Service,
    ) -> Response:
        exports = product.get_industrial_incident_decision_packet_exports(
            actor,
            task_id,
            case_id,
        )
        return Response(
            content=exports.audit_bundle_zip,
            media_type="application/zip",
            headers={
                "Content-Disposition": (
                    f'attachment; filename="{case_id}-decision-packet.zip"'
                ),
                "ETag": f'"{exports.receipt.audit_bundle_sha256}"',
                "X-Audit-Bundle-SHA256": exports.receipt.audit_bundle_sha256,
            },
        )

    @app.post(
        "/v1/tasks/{task_id}/industrial-incidents/{case_id}/resume",
        response_model=IndustrialIncidentCase,
        status_code=status.HTTP_201_CREATED,
        responses={404: _NOT_FOUND_RESPONSE, 409: _CONFLICT_RESPONSE},
        tags=["industrial-incidents"],
    )
    def resume_industrial_incident(
        task_id: str,
        case_id: str,
        payload: IndustrialIncidentRequest,
        response: Response,
        actor: Actor,
        product: Service,
        idempotency_key: Annotated[
            str | None, Header(alias="Idempotency-Key", max_length=120)
        ] = None,
    ) -> IndustrialIncidentCase:
        resolved_key = resolve_incident_idempotency_key(idempotency_key, payload)
        command_id = incident_command_id(
            task_id=task_id,
            operation=IncidentCommandKind.RESUME_CASE,
            target_case_id=case_id,
            idempotency_key=resolved_key,
        )
        case = product.resume_industrial_incident_case(
            actor,
            task_id,
            case_id,
            payload,
            idempotency_key=resolved_key,
        )
        response.headers["Location"] = (
            f"/v1/tasks/{task_id}/industrial-incidents/{case.case_id}"
        )
        response.headers["X-Incident-Command-Id"] = command_id
        response.headers["ETag"] = f'"{case.case_sha256}"'
        response.headers["X-Incident-Case-SHA256"] = case.case_sha256
        response.headers["Cache-Control"] = "private, no-store"
        return case

    @app.get(
        "/v1/tasks/{task_id}/industrial-incidents/{case_id}/decisions",
        response_model=list[IndustrialIncidentDecisionReceipt],
        responses={404: _NOT_FOUND_RESPONSE, 409: _CONFLICT_RESPONSE},
        tags=["industrial-incidents"],
    )
    def list_industrial_incident_decisions(
        task_id: str,
        case_id: str,
        response: Response,
        actor: Actor,
        product: Service,
    ) -> list[IndustrialIncidentDecisionReceipt]:
        decisions = product.list_industrial_incident_decisions(actor, task_id, case_id)
        _bind_sha256_response(response, _canonical_content_sha256(decisions))
        return decisions

    @app.post(
        "/v1/tasks/{task_id}/industrial-incidents/{case_id}/decisions",
        response_model=IndustrialIncidentDecisionReceipt,
        status_code=status.HTTP_201_CREATED,
        responses={404: _NOT_FOUND_RESPONSE, 409: _CONFLICT_RESPONSE},
        tags=["industrial-incidents"],
    )
    def record_industrial_incident_decision(
        task_id: str,
        case_id: str,
        payload: IndustrialIncidentDecisionRequest,
        response: Response,
        actor: Actor,
        product: Service,
        idempotency_key: Annotated[
            str | None, Header(alias="Idempotency-Key", max_length=120)
        ] = None,
    ) -> IndustrialIncidentDecisionReceipt:
        resolved_key = resolve_incident_idempotency_key(idempotency_key, payload)
        command_id = incident_command_id(
            task_id=task_id,
            operation=IncidentCommandKind.RECORD_DECISION,
            target_case_id=case_id,
            idempotency_key=resolved_key,
        )
        receipt = product.record_industrial_incident_decision(
            actor,
            task_id,
            case_id,
            payload,
            idempotency_key=resolved_key,
        )
        response.headers["Location"] = (
            f"/v1/tasks/{task_id}/industrial-incidents/{case_id}/decisions"
            f"#{receipt.decision_id}"
        )
        response.headers["X-Incident-Command-Id"] = command_id
        response.headers["ETag"] = f'"{receipt.decision_sha256}"'
        response.headers["X-Incident-Decision-SHA256"] = receipt.decision_sha256
        response.headers["Cache-Control"] = "private, no-store"
        return receipt

    @app.post(
        "/v1/tasks/{task_id}/capa-cases",
        response_model=CapaCaseReport,
        status_code=status.HTTP_201_CREATED,
        responses={404: _NOT_FOUND_RESPONSE, 409: _CONFLICT_RESPONSE},
        tags=["remediation"],
    )
    def select_capa_plan(
        task_id: str,
        payload: SelectRemediationPlanRequest,
        response: Response,
        actor: Actor,
        product: Service,
    ) -> CapaCaseReport:
        report = product.select_remediation_plan(actor, task_id, payload)
        response.headers["Location"] = (
            f"/v1/tasks/{task_id}/capa-cases/{report.case_id}"
        )
        _bind_sha256_response(response, _canonical_content_sha256(report))
        return report

    @app.get(
        "/v1/tasks/{task_id}/capa-cases",
        response_model=list[CapaCaseReport],
        responses={404: _NOT_FOUND_RESPONSE},
        tags=["remediation"],
    )
    def list_capa_cases(
        task_id: str, response: Response, actor: Actor, product: Service
    ) -> list[CapaCaseReport]:
        reports = product.list_capa_cases(actor, task_id)
        _bind_sha256_response(response, _canonical_content_sha256(reports))
        return reports

    @app.get(
        "/v1/tasks/{task_id}/capa-cases/{case_id}",
        response_model=CapaCaseReport,
        responses={404: _NOT_FOUND_RESPONSE, 409: _CONFLICT_RESPONSE},
        tags=["remediation"],
    )
    def get_capa_case(
        task_id: str,
        case_id: str,
        response: Response,
        actor: Actor,
        product: Service,
    ) -> CapaCaseReport:
        report = product.get_capa_case(actor, task_id, case_id)
        _bind_sha256_response(response, _canonical_content_sha256(report))
        return report

    @app.get(
        "/v1/tasks/{task_id}/capa-cases/{case_id}/causal-replay",
        response_model=CausalReplayReport,
        responses={404: _NOT_FOUND_RESPONSE, 409: _CONFLICT_RESPONSE},
        tags=["remediation"],
    )
    def get_capa_causal_replay(
        task_id: str,
        case_id: str,
        response: Response,
        actor: Actor,
        product: Service,
    ) -> CausalReplayReport:
        replay = product.capa_causal_replay(actor, task_id, case_id)
        response.headers["ETag"] = f'"{replay.report_sha256}"'
        response.headers["X-Content-SHA256"] = replay.report_sha256
        response.headers["Cache-Control"] = "private, no-store"
        return replay

    @app.get(
        "/v1/tasks/{task_id}/capa-cases/{case_id}/outcome-assessment",
        response_model=CapaOutcomeAssessment,
        responses={404: _NOT_FOUND_RESPONSE, 409: _CONFLICT_RESPONSE},
        tags=["remediation"],
    )
    def get_capa_outcome_assessment(
        task_id: str,
        case_id: str,
        response: Response,
        actor: Actor,
        product: Service,
    ) -> CapaOutcomeAssessment:
        assessment = product.capa_outcome_assessment(actor, task_id, case_id)
        response.headers["ETag"] = f'"{assessment.assessment_sha256}"'
        response.headers["X-Content-SHA256"] = assessment.assessment_sha256
        response.headers["Cache-Control"] = "private, no-store"
        return assessment

    @app.get(
        "/v1/tasks/{task_id}/capa-cases/{case_id}/governed-outcome-envelope",
        response_model=GovernedOutcomeEnvelope,
        responses={404: _NOT_FOUND_RESPONSE, 409: _CONFLICT_RESPONSE},
        tags=["remediation", "audit"],
    )
    def get_governed_outcome_envelope(
        task_id: str,
        case_id: str,
        response: Response,
        actor: Actor,
        product: Service,
    ) -> GovernedOutcomeEnvelope:
        envelope = product.get_governed_outcome_envelope(actor, task_id, case_id)
        response.headers["ETag"] = f'"{envelope.outcome_root.value}"'
        response.headers["X-Content-SHA256"] = envelope.outcome_root.value
        response.headers["Cache-Control"] = "private, no-store"
        return envelope

    @app.post(
        "/v1/tasks/{task_id}/capa-cases/{case_id}/approval",
        response_model=CapaCaseReport,
        responses={404: _NOT_FOUND_RESPONSE, 409: _CONFLICT_RESPONSE},
        tags=["remediation"],
    )
    def approve_capa_plan(
        task_id: str,
        case_id: str,
        payload: ApproveRemediationPlanRequest,
        response: Response,
        actor: Actor,
        product: Service,
    ) -> CapaCaseReport:
        report = product.approve_remediation_plan(actor, task_id, case_id, payload)
        _bind_sha256_response(response, _canonical_content_sha256(report))
        return report

    @app.post(
        "/v1/tasks/{task_id}/capa-cases/{case_id}/execute",
        response_model=CapaCaseReport,
        responses={404: _NOT_FOUND_RESPONSE, 409: _CONFLICT_RESPONSE},
        tags=["remediation"],
    )
    def execute_capa_plan(
        task_id: str,
        case_id: str,
        payload: ExecuteRemediationPlanRequest,
        response: Response,
        actor: Actor,
        product: Service,
    ) -> CapaCaseReport:
        report = product.execute_remediation_plan(actor, task_id, case_id, payload)
        _bind_sha256_response(response, _canonical_content_sha256(report))
        return report

    @app.get(
        "/v1/tasks/{task_id}/release-readiness",
        response_model=TaskReleaseReadinessReport,
        responses={404: _NOT_FOUND_RESPONSE, 409: _CONFLICT_RESPONSE},
        tags=["artifacts"],
    )
    def get_release_readiness(
        task_id: str, actor: Actor, product: Service
    ) -> TaskReleaseReadinessReport:
        return product.task_release_readiness(actor, task_id)

    @app.post(
        "/v1/tasks/{task_id}/annotation-exports/{provider}",
        response_model=AnnotationExportRecord,
        status_code=status.HTTP_201_CREATED,
        responses={404: _NOT_FOUND_RESPONSE, 409: _CONFLICT_RESPONSE},
        tags=["remediation"],
    )
    def create_annotation_export(
        task_id: str,
        provider: AnnotationProvider,
        actor: Actor,
        product: Service,
    ) -> AnnotationExportRecord:
        return product.create_annotation_export(actor, task_id, provider)

    @app.post(
        "/v1/tasks/{task_id}/annotation-imports",
        response_model=AnnotationRoundtripReceipt,
        responses={404: _NOT_FOUND_RESPONSE, 409: _CONFLICT_RESPONSE},
        tags=["remediation"],
    )
    def import_annotation_revisions(
        task_id: str,
        payload: AnnotationImportPackage,
        actor: Actor,
        product: Service,
    ) -> AnnotationRoundtripReceipt:
        return product.import_annotation_revisions(actor, task_id, payload)

    @app.get(
        "/v1/tasks/{task_id}/annotation-roundtrips",
        response_model=list[AnnotationRoundtripReceipt],
        responses={404: _NOT_FOUND_RESPONSE},
        tags=["remediation"],
    )
    def list_annotation_roundtrips(
        task_id: str, actor: Actor, product: Service
    ) -> list[AnnotationRoundtripReceipt]:
        return product.list_annotation_roundtrips(actor, task_id)

    @app.get(
        "/v1/tasks/{task_id}/acceptance-scorecard",
        response_model=AcceptanceScorecard,
        responses={404: _NOT_FOUND_RESPONSE, 409: _CONFLICT_RESPONSE},
        tags=["artifacts"],
    )
    def get_acceptance_scorecard(
        task_id: str,
        actor: Actor,
        product: Service,
        roundtrip_receipt_id: str | None = None,
    ) -> AcceptanceScorecard:
        return product.acceptance_scorecard(
            actor,
            task_id,
            roundtrip_receipt_id=roundtrip_receipt_id,
        )

    @app.post(
        "/v1/tasks/{task_id}/industrial-shadow-evaluations",
        response_model=IndustrialShadowEvaluationReceipt,
        status_code=status.HTTP_201_CREATED,
        responses={404: _NOT_FOUND_RESPONSE, 409: _CONFLICT_RESPONSE},
        tags=["evaluation", "governance"],
    )
    def create_industrial_shadow_evaluation(
        task_id: str,
        payload: CreateIndustrialShadowEvaluationRequest,
        actor: Actor,
        product: Service,
    ) -> IndustrialShadowEvaluationReceipt:
        return product.create_industrial_shadow_evaluation(actor, task_id, payload)

    @app.get(
        "/v1/tasks/{task_id}/industrial-shadow-evaluations",
        response_model=list[IndustrialShadowEvaluationReceipt],
        responses={404: _NOT_FOUND_RESPONSE, 409: _CONFLICT_RESPONSE},
        tags=["evaluation", "governance"],
    )
    def list_industrial_shadow_evaluations(
        task_id: str,
        actor: Actor,
        product: Service,
    ) -> list[IndustrialShadowEvaluationReceipt]:
        return product.list_industrial_shadow_evaluations(actor, task_id)

    @app.post(
        "/v1/tasks/{task_id}/industrial-shadow-evaluation-manifests",
        response_model=ShadowEvaluationManifestV2,
        status_code=status.HTTP_201_CREATED,
        responses={404: _NOT_FOUND_RESPONSE, 409: _CONFLICT_RESPONSE},
        tags=["evaluation", "governance"],
    )
    def create_shadow_evaluation_manifest_v2(
        task_id: str,
        payload: CreateShadowEvaluationManifestV2Request,
        actor: Actor,
        product: Service,
    ) -> ShadowEvaluationManifestV2:
        return product.create_shadow_evaluation_manifest_v2(actor, task_id, payload)

    @app.get(
        "/v1/tasks/{task_id}/industrial-shadow-evaluation-manifests",
        response_model=list[ShadowEvaluationManifestV2],
        responses={404: _NOT_FOUND_RESPONSE, 409: _CONFLICT_RESPONSE},
        tags=["evaluation", "governance"],
    )
    def list_shadow_evaluation_manifests_v2(
        task_id: str,
        actor: Actor,
        product: Service,
    ) -> list[ShadowEvaluationManifestV2]:
        return product.list_shadow_evaluation_manifests_v2(actor, task_id)

    return app


app = create_app()


__all__ = ["app", "create_app"]
