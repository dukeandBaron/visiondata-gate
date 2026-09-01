"""Unified product service used by both the Streamlit workspace and REST API."""

from __future__ import annotations

import hashlib
import hmac
import json
import os
import threading
import uuid
from collections.abc import Callable, Iterable, Mapping
from concurrent.futures import Future, ThreadPoolExecutor
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Literal

from .acceptance import AcceptanceScorecard, build_acceptance_scorecard
from .agent_runtime import AgenticDemoRun, run_agentic_demo
from .agentteams_transport import (
    HostedAgentTeamsReceipt,
    HostedAgentTeamsTransport,
    HostedProjectSubmission,
    hosted_agentteams_from_environment,
)
from .annotation_roundtrip import (
    AnnotationExportBundle,
    AnnotationExportRecord,
    AnnotationImportPackage,
    AnnotationProvider,
    AnnotationReceiptIntegrity,
    AnnotationRoundtripReceipt,
    build_annotation_export,
    import_revisions_and_recheck,
    write_annotation_export,
)
from .approved_experience import (
    SourceCaseEvidenceBinding,
    load_memory_admission_store,
    verify_source_case_evidence_binding,
)
from .audit_envelope import (
    GovernedAuditAnchor,
    GovernedAuditEnvelope,
    build_governed_audit_anchor,
    build_governed_audit_envelope,
    canonical_jcs_bytes,
    parse_governed_audit_anchor_json,
    parse_governed_audit_envelope_json,
    verify_governed_audit_anchor,
    verify_governed_audit_envelope,
)
from .capa import (
    ApproveRemediationPlanRequest,
    CapaApprovalBinding,
    CapaCaseReport,
    CapaCaseSelection,
    CapaExecutionAuthorization,
    CapaExecutionReceipt,
    CapaOutcomeAssessment,
    CapaRecoveryReceipt,
    CapaResponsibilityQueue,
    CapaStatus,
    DerivedDataVersionReceipt,
    DerivedVersionBuild,
    ExecuteRemediationPlanRequest,
    ResponsibilityStatus,
    SelectRemediationPlanRequest,
    build_capa_outcome_assessment,
    build_operator_snapshot_derived_version,
    verify_child_run_closure,
    build_omni_derived_version,
    build_responsibility_queue,
    seal_model,
    verify_sealed_model,
)
from .case_replay import CausalReplayReport, build_causal_replay_report
from .contracts import BatchContract, BatchManifest, EvaluationResult, GateResult
from .evidence import canonical_json_bytes, sha256_file, write_canonical_json
from .grounding import LLMGroundingReceipt
from .incident_commands import (
    IncidentCommandAdmission,
    IncidentCommandKind,
    IncidentCommandReceipt,
    IncidentCommandTerminal,
    build_incident_command_admission,
    build_incident_command_receipt,
    build_incident_command_terminal,
    incident_command_id,
    normalize_incident_idempotency_key,
    resolve_incident_idempotency_key,
    verify_incident_command_admission,
    verify_incident_command_terminal,
)
from .incident_control_plane import (
    IncidentControlPlaneBundle,
    build_incident_control_plane,
    verify_incident_control_plane,
)
from .incident_decision_packet import (
    DecisionPacketExports,
    IndustrialQualityDecisionPacket,
    build_decision_packet_exports,
    build_industrial_quality_decision_packet,
)
from .incident_review_projection import (
    IncidentReviewProjection,
    build_incident_review_projection,
)
from .incident_interaction import (
    IncidentInteractionReceipt,
    build_incident_interaction_receipt,
    verify_incident_interaction_receipt,
)
from .incident_model_planner import (
    IncidentModelPlanner,
    IncidentModelPlannerConfig,
    incident_model_planner_from_environment,
)
from .incident_runtime_profile import (
    IncidentMemoryMode,
    IncidentRuntimeCapabilities,
    IncidentRuntimeProfile,
    IncidentRuntimeProfileBinding,
    build_incident_runtime_capabilities,
    build_runtime_profile_binding,
    planner_from_runtime_profile,
)
from .governed_context import (
    AssembledIncidentContext,
    DEFAULT_HYBRID_RETRIEVAL_PROFILE_V2,
    GovernedMemoryPlanningInput,
    HybridMemoryRetrievalReceiptV3,
    MemoryProcessingTimeSource,
    assemble_incident_context,
    build_governed_memory_planning_input,
    load_approved_memory_store,
    verify_assembled_incident_context,
    verify_memory_retrieval_command_admission_binding,
)
from .governed_outcome import (
    GovernedOutcomeEnvelope,
    build_governed_outcome_envelope,
    parse_governed_outcome_envelope_json,
    verify_governed_outcome_envelope,
)
from .goal3_bridge import Goal3HandoffReceipt, build_goal3_handoff_receipt
from .governance_effectiveness import (
    CreateIndustrialShadowEvaluationRequest,
    CreateShadowEvaluationManifestV2Request,
    IndustrialShadowEvaluationReceipt,
    ProjectGovernanceEffectivenessSummary,
    ShadowEvaluationManifestV2,
    ShadowEvaluationReceipt,
    build_industrial_shadow_evaluation_receipt,
    build_project_governance_effectiveness_summary,
    build_shadow_evaluation_manifest_v2,
    shadow_evaluation_manifest_v2_request_sha256,
    shadow_evaluation_request_sha256,
    verify_industrial_shadow_evaluation_receipt,
    verify_project_governance_effectiveness_summary,
    verify_shadow_evaluation_manifest_v2,
)
from .industrial_delivery import (
    IndustrialDeliveryReceipt,
    build_industrial_delivery_receipt,
)
from .industrial_incident import (
    PHASE_EVENT_INCIDENT_CASE_SCHEMA_VERSIONS,
    IncidentCapaEvidence,
    IncidentHumanDecision,
    IncidentPhaseEvent,
    IncidentWorkerRegistry,
    IndustrialGateContext,
    IndustrialIncidentCase,
    IndustrialIncidentDecisionConsumptionReceipt,
    IndustrialIncidentDecisionReceipt,
    IndustrialIncidentDecisionRequest,
    IndustrialIncidentRequest,
    build_incident_decision_consumption_receipt,
    build_incident_phase_events,
    build_industrial_incident_case,
    build_industrial_incident_decision_receipt,
    incident_case_requires_governed_audit_envelope,
    industrial_incident_planning_subject_sha256,
    incident_runtime_profile,
    parse_industrial_incident_case_json,
    reuse_incident_case_verification,
    verify_incident_decision_consumption_receipt,
    verify_incident_phase_events,
    verify_industrial_incident_case,
    verify_industrial_incident_decision_receipt,
)
from .lineage import (
    CreateReverificationRequest,
    TaskLineageReport,
    build_task_lineage_report,
    task_contract_sha256,
)
from .omni_adapter import profile_omni_source
from .operator_snapshot import (
    OperatorProjectSnapshotReceipt,
    materialize_operator_project_snapshot,
    profile_operator_project_snapshot,
)
from .operator_workspace import OperatorImageStore
from .package import audit_submission_zip, build_deterministic_zip
from .product_models import (
    PUBLIC_TOOL_NAMES,
    AuthorizeLocalSourceRequest,
    AuthorizeOperatorProjectSnapshotRequest,
    CreateProjectRequest,
    CreateTaskRequest,
    CreateUserRequest,
    CreateWorkspaceRequest,
    DataSourceKind,
    HealthResponse,
    LocalSourceAdapterKind,
    LocalSourceAuthorizationReceipt,
    ProjectRecord,
    RevokeLocalSourceAuthorizationRequest,
    SourceAuthorizationEventReceipt,
    SubmitHostedAgentTeamsTaskRequest,
    TaskEventRecord,
    TaskExecutionStatus,
    TaskInterventionAction,
    TaskInterventionRecord,
    TaskInterventionRequest,
    TaskPlanApprovalBinding,
    TaskPlanPreview,
    TaskPlanStep,
    TaskRecord,
    UserRecord,
    WorkspaceRecord,
)
from .product_runs import (
    ProductTaskRun,
    normalize_agentic_run,
    run_omni_product_task,
    run_operator_snapshot_product_task,
    verify_product_task_run,
)
from .provider_profiles import (
    ProviderConnectionTestRequest,
    ProviderConnectionTestResult,
    ProviderProfileCreateRequest,
    ProviderProfileRecord,
    ProviderProfileRegistry,
    ProviderSecretStore,
    WindowsDPAPIProviderSecretStore,
    new_provider_profile_id,
    probe_provider_connection,
    profile_to_resolved_config,
    resolve_provider_config,
)
from .readiness import (
    ReadinessCheck,
    TaskPreflightReport,
    TaskReleaseReadinessReport,
    build_task_preflight_report,
    build_task_release_readiness_report,
)
from .rulepack import (
    build_rule_pack_runtime_binding,
    verify_rule_pack_runtime_binding,
)
from .runtime_models import ModelBackendKind, RuntimeConfig, RuntimeTrace
from .runtime_safety import (
    RuntimeAction,
    RuntimeActorKind,
    RuntimeInvariantContext,
    build_runtime_invariant_receipt,
)
from .site_pack import FactorySitePack, load_factory_site_pack, verify_factory_site_pack
from .task_store import (
    ConflictError,
    IncidentCommandBindingConflict,
    IncidentCommandScopeOccupied,
    NotFoundError,
    ProductStoreError,
    TaskStore,
)
from .visual_evidence import (
    TaskVisualEvidenceManifest,
    build_task_visual_evidence_manifest,
)
from .task_store import (
    IncidentCommandOperation as StoreIncidentCommandOperation,
)
from .task_store import (
    IncidentCommandStatus as StoreIncidentCommandStatus,
)


class ProductServiceError(RuntimeError):
    code = "service_error"


class UnsupportedSourceError(ProductServiceError):
    code = "source_not_connected"


class ArtifactUnavailableError(ProductServiceError):
    code = "artifact_unavailable"


class RoundtripValidationError(ProductServiceError):
    code = "roundtrip_validation_failed"


class RulePackDriftError(ProductServiceError):
    code = "rule_pack_drift"


class HostedAgentTeamsUnavailableError(ProductServiceError):
    code = "hosted_agentteams_not_configured"


class HostedAgentTeamsOperationError(ProductServiceError):
    code = "hosted_agentteams_operation_failed"


class IncidentCommandUncertainError(ProductServiceError):
    code = "incident_command_uncertain"

    def __init__(self, command_id: str) -> None:
        self.command_id = command_id
        super().__init__(
            f"incident command {command_id} has an admission receipt but no terminal "
            "receipt; automatic replay is blocked"
        )


class IncidentIdempotencyConflictError(ProductServiceError):
    code = "incident_idempotency_conflict"


class IncidentCommandRejectedError(ProductServiceError):
    code = "incident_command_rejected"

    def __init__(self, command_id: str, error_code: str, message: str) -> None:
        self.command_id = command_id
        self.code = error_code
        super().__init__(message)


Runner = Callable[..., AgenticDemoRun | ProductTaskRun]


def _now() -> str:
    return datetime.now(UTC).isoformat(timespec="milliseconds")


def _create_once_bytes(path: Path, data: bytes) -> bool:
    """Atomically publish complete bytes without ever replacing the target."""

    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.parent / f".{path.name}.{uuid.uuid4().hex}.tmp"
    try:
        with temporary.open("xb") as handle:
            handle.write(data)
            handle.flush()
            os.fsync(handle.fileno())
        try:
            os.link(temporary, path)
            return True
        except FileExistsError:
            return False
    finally:
        try:
            temporary.unlink()
        except FileNotFoundError:
            pass


def _write_once_json(path: Path, value: Any) -> str:
    """Atomically persist an immutable artifact or verify an exact replay."""

    data = canonical_json_bytes(value)
    digest = hashlib.sha256(data).hexdigest()
    created = _create_once_bytes(path, data)
    if not created and path.read_bytes() != data:
        raise ConflictError(f"immutable artifact already differs: {path.name}")
    return digest


def _write_once_jcs_json(path: Path, value: Any) -> str:
    """Atomically persist a new-protocol RFC 8785 JSON artifact."""

    data = canonical_jcs_bytes(value)
    digest = hashlib.sha256(data).hexdigest()
    created = _create_once_bytes(path, data)
    if not created and path.read_bytes() != data:
        raise ConflictError(f"immutable artifact already differs: {path.name}")
    return digest


class ProductService:
    """Own task lifecycle, execution, persistence, and artifact boundaries."""

    def __init__(
        self,
        product_root: str | Path,
        *,
        runner: Runner = run_agentic_demo,
        max_workers: int = 1,
        recover_interrupted: bool = False,
        local_source_allow_roots: Iterable[str | Path] | None = None,
        incident_model_planner: IncidentModelPlanner | None = None,
        incident_worker_registry: IncidentWorkerRegistry | None = None,
        incident_site_profiles: Mapping[str, str | Path] | None = None,
        approved_memory_store_path: str | Path | None = None,
        governed_memory_admission_store_path: str | Path | None = None,
        memory_admission_mode: Literal["strict_envelope_v1", "legacy_card_v1"]
        | None = None,
        memory_source_case_registry: Mapping[str, SourceCaseEvidenceBinding]
        | None = None,
        omni_rulepack_path: str | Path | None = None,
        hosted_agentteams: HostedAgentTeamsTransport | None = None,
        provider_profile_registry: ProviderProfileRegistry | None = None,
        provider_secret_store: ProviderSecretStore | None = None,
    ) -> None:
        configured_rulepack = omni_rulepack_path
        if isinstance(configured_rulepack, str) and not configured_rulepack.strip():
            configured_rulepack = None
        self.omni_rulepack_path: Path | None = None
        self.omni_rulepack_source_sha256: str | None = None
        if configured_rulepack is not None:
            resolved_rulepack = (
                Path(configured_rulepack).expanduser().resolve(strict=True)
            )
            if not resolved_rulepack.is_file():
                raise ValueError("Omni Rule Pack path must be a file")
            source_sha256_before = sha256_file(resolved_rulepack)
            runtime_binding = verify_rule_pack_runtime_binding(
                build_rule_pack_runtime_binding(resolved_rulepack)
            )
            source_sha256_after = sha256_file(resolved_rulepack)
            if not (
                hmac.compare_digest(source_sha256_before, source_sha256_after)
                and hmac.compare_digest(
                    source_sha256_after, runtime_binding.source_sha256
                )
            ):
                raise ValueError("Omni Rule Pack source drifted during initialization")
            self.omni_rulepack_path = resolved_rulepack
            self.omni_rulepack_source_sha256 = source_sha256_after
        self.product_root = Path(product_root).expanduser().resolve()
        self.product_root.mkdir(parents=True, exist_ok=True)
        self.store = TaskStore(self.product_root / "product.sqlite3")
        self.provider_profile_registry = (
            provider_profile_registry
            or ProviderProfileRegistry(self.product_root / "provider_profiles.sqlite3")
        )
        self.provider_secret_store = (
            provider_secret_store
            if provider_secret_store is not None
            else WindowsDPAPIProviderSecretStore(
                self.product_root / "private" / "provider_secrets"
            )
        )
        self.runner = runner
        self.incident_model_planner = incident_model_planner
        self.incident_worker_registry = incident_worker_registry
        self.hosted_agentteams = hosted_agentteams
        project_root = (
            Path(
                os.environ.get(
                    "VISIONDATA_RESOURCE_ROOT",
                    Path(__file__).resolve().parents[2],
                )
            )
            .expanduser()
            .resolve()
        )
        configured_site_profiles = incident_site_profiles
        if configured_site_profiles is None:
            example_site_root = project_root / "examples" / "site_packs"
            configured_site_profiles = (
                {
                    path.name.replace("_", "-"): path
                    for path in example_site_root.iterdir()
                    if path.is_dir()
                }
                if example_site_root.is_dir()
                else {}
            )
        resolved_site_profiles: dict[str, Path] = {}
        for profile_id, value in configured_site_profiles.items():
            normalized_id = profile_id.strip().casefold()
            if not normalized_id:
                raise ValueError("incident site profile ID cannot be blank")
            root = Path(value).expanduser().resolve(strict=True)
            if not root.is_dir():
                raise ValueError("incident site profile must be a directory")
            resolved_site_profiles[normalized_id] = root
        self.incident_site_profiles = resolved_site_profiles

        configured_mode = (
            memory_admission_mode
            or os.environ.get(
                "VISIONDATA_MEMORY_ADMISSION_MODE",
                "strict_envelope_v1",
            ).strip()
        )
        if configured_mode not in {"strict_envelope_v1", "legacy_card_v1"}:
            raise ValueError("unsupported governed-memory admission mode")
        if (
            governed_memory_admission_store_path is not None
            and approved_memory_store_path is not None
        ):
            raise ValueError(
                "strict admission store and legacy approved-memory store are mutually "
                "exclusive"
            )
        if (
            governed_memory_admission_store_path is not None
            and configured_mode != "strict_envelope_v1"
        ):
            raise ValueError("governed admission store requires strict_envelope_v1")
        if (
            approved_memory_store_path is not None
            and configured_mode != "legacy_card_v1"
        ):
            raise ValueError(
                "bare approved-memory store requires explicit legacy_card_v1 mode"
            )
        configured_memory_store = (
            governed_memory_admission_store_path or approved_memory_store_path
        )
        if configured_memory_store is None:
            environment_key = (
                "VISIONDATA_MEMORY_ADMISSION_STORE"
                if configured_mode == "strict_envelope_v1"
                else "VISIONDATA_APPROVED_MEMORY_STORE"
            )
            environment_memory_store = os.environ.get(environment_key, "").strip()
            if environment_memory_store:
                configured_memory_store = environment_memory_store
            elif configured_mode == "legacy_card_v1":
                example_memory_store = (
                    project_root
                    / "examples"
                    / "governed_memory"
                    / "approved_memory.jsonl"
                )
                if example_memory_store.is_file():
                    configured_memory_store = example_memory_store
        self.memory_admission_mode = configured_mode
        self.memory_source_case_registry = dict(memory_source_case_registry or {})
        for case_id, binding in self.memory_source_case_registry.items():
            verify_source_case_evidence_binding(binding)
            if case_id != binding.case_id:
                raise ValueError(
                    "memory source case registry key does not match binding"
                )
        self.approved_memory_store_path = (
            Path(configured_memory_store).expanduser().resolve(strict=True)
            if configured_memory_store is not None
            else None
        )
        if (
            self.approved_memory_store_path is not None
            and not self.approved_memory_store_path.is_file()
        ):
            raise ValueError("approved memory store must be a file")
        self.governed_memory_ready = bool(
            self.approved_memory_store_path is not None
            and (
                self.memory_admission_mode == "legacy_card_v1"
                or self.memory_source_case_registry
            )
        )
        configured_roots = local_source_allow_roots
        if configured_roots is None:
            configured_roots = [
                value
                for value in os.environ.get(
                    "VISIONDATA_LOCAL_SOURCE_ALLOW_ROOTS", ""
                ).split(os.pathsep)
                if value.strip()
            ]
        resolved_roots: list[Path] = []
        for value in configured_roots:
            root = Path(value).expanduser().resolve(strict=True)
            if not root.is_dir():
                raise ValueError("local source allow roots must be directories")
            if root not in resolved_roots:
                resolved_roots.append(root)
        self.local_source_allow_roots = tuple(resolved_roots)
        self._executor = ThreadPoolExecutor(
            max_workers=max_workers,
            thread_name_prefix="visiondata-product",
        )
        self._futures: dict[str, Future[None]] = {}
        self._future_lock = threading.Lock()
        self._incident_lock = threading.Lock()
        if recover_interrupted:
            self.store.recover_interrupted()

    def _verified_omni_rulepack_path(self) -> Path | None:
        if self.omni_rulepack_path is None:
            return None
        expected_sha256 = self.omni_rulepack_source_sha256
        if expected_sha256 is None:
            raise RulePackDriftError("configured Omni Rule Pack lost its pinned digest")
        try:
            current_sha256 = sha256_file(self.omni_rulepack_path)
        except OSError as error:
            raise RulePackDriftError(
                "configured Omni Rule Pack is unavailable after service initialization"
            ) from error
        if not hmac.compare_digest(current_sha256, expected_sha256):
            raise RulePackDriftError(
                "configured Omni Rule Pack changed after service initialization"
            )
        return self.omni_rulepack_path

    def close(self, *, wait: bool = False) -> None:
        self._executor.shutdown(wait=wait, cancel_futures=False)

    def health(self) -> HealthResponse:
        return HealthResponse(
            data_sources={
                DataSourceKind.SYNTHETIC_DEMO.value: "connected",
                DataSourceKind.LOCAL_AUTHORIZED_DIRECTORY.value: (
                    "connected_readonly_allowlist"
                    if self.local_source_allow_roots
                    else "not_connected"
                ),
                DataSourceKind.EXTERNAL_RESIDENCY_REFERENCE.value: "not_connected",
                "cvat_annotation": "contract_ready_not_connected",
                "fiftyone_annotation": "contract_ready_not_connected",
                "longcat_council": "adapter_ready_real_backend_not_connected",
                "hosted_agentteams": (
                    "configured_not_probed"
                    if self.hosted_agentteams is not None
                    else "not_configured"
                ),
                "incident_model_planner": (
                    self.incident_model_planner.health_label()
                    if self.incident_model_planner is not None
                    else "off"
                ),
                "incident_runtime_profiles": "case_bound_contract_ready",
                "governed_site_memory": (
                    (
                        "strict_admission_chain_available"
                        if self.memory_admission_mode == "strict_envelope_v1"
                        else "legacy_card_sha_only_explicitly_enabled"
                    )
                    if self.incident_site_profiles and self.governed_memory_ready
                    else "contract_ready_not_connected"
                ),
                "vggt_geometry": "adapter_ready_real_backend_not_connected",
                "omnivggt_geometry": "adapter_ready_real_backend_not_connected",
            }
        )

    def _require_hosted_agentteams(self) -> HostedAgentTeamsTransport:
        if self.hosted_agentteams is None:
            raise HostedAgentTeamsUnavailableError(
                "Hosted AgentTeams is not configured; no network request was made"
            )
        return self.hosted_agentteams

    def _hosted_agentteams_output_dir(
        self,
        *,
        workspace_id: str,
        subject_id: str,
        operation: str,
    ) -> Path:
        """Reserve one opaque, immutable-attempt directory inside product_root."""

        if operation not in {"probe", "submit_project"}:
            raise ValueError("unknown Hosted AgentTeams operation")
        scope = hashlib.sha256(
            canonical_json_bytes(
                {
                    "workspace_id": workspace_id,
                    "subject_id": subject_id,
                }
            )
        ).hexdigest()[:32]
        product_root = self.product_root.resolve(strict=False)
        hosted_root = (product_root / "hosted_agentteams").resolve(strict=False)
        try:
            hosted_root.relative_to(product_root)
        except ValueError as error:
            raise ArtifactUnavailableError(
                "Hosted AgentTeams evidence root escaped product root"
            ) from error
        destination = (hosted_root / operation / scope / uuid.uuid4().hex).resolve(
            strict=False
        )
        try:
            destination.relative_to(hosted_root)
        except ValueError as error:
            raise ArtifactUnavailableError(
                "Hosted AgentTeams evidence path escaped product root"
            ) from error
        destination.mkdir(parents=True, exist_ok=False)
        return destination

    def probe_hosted_agentteams(
        self, actor_user_id: str, workspace_id: str
    ) -> HostedAgentTeamsReceipt:
        """Probe the configured control plane after enforcing workspace visibility."""

        if not any(
            workspace.workspace_id == workspace_id
            for workspace in self.store.list_workspaces(actor_user_id)
        ):
            raise NotFoundError("workspace not found")
        transport = self._require_hosted_agentteams()
        output_dir = self._hosted_agentteams_output_dir(
            workspace_id=workspace_id,
            subject_id=workspace_id,
            operation="probe",
        )
        try:
            return transport.collect_runtime_evidence(output_dir)
        except (OSError, PermissionError, RuntimeError, ValueError) as error:
            raise HostedAgentTeamsOperationError(
                "Hosted AgentTeams probe failed closed"
            ) from error

    def submit_task_to_hosted_agentteams(
        self,
        actor_user_id: str,
        task_id: str,
        request: SubmitHostedAgentTeamsTaskRequest,
    ) -> HostedAgentTeamsReceipt:
        """Submit a visible task only after an explicit named approval gate."""

        task = self.store.get_task(actor_user_id, task_id)
        project = self.store.get_project(actor_user_id, task.project_id)
        transport = self._require_hosted_agentteams()
        submission = HostedProjectSubmission(
            source_run_id=task.task_id,
            title=f"{project.name} [{task.task_id}]",
            goal=task.goal,
            requester=actor_user_id,
            wait_for_remote_execution=request.wait_for_remote_execution,
        )
        output_dir = self._hosted_agentteams_output_dir(
            workspace_id=task.workspace_id,
            subject_id=task.task_id,
            operation="submit_project",
        )
        try:
            return transport.submit_project(
                output_dir,
                submission,
                approval_id=request.approval_id,
            )
        except (OSError, PermissionError, RuntimeError, ValueError) as error:
            raise HostedAgentTeamsOperationError(
                "Hosted AgentTeams task submission failed closed"
            ) from error

    def incident_runtime_capabilities(self) -> IncidentRuntimeCapabilities:
        memory_profiles = (
            sorted(self.incident_site_profiles) if self.governed_memory_ready else []
        )
        return build_incident_runtime_capabilities(
            memory_profile_ids=memory_profiles,
        )

    def ensure_default_tenant(
        self,
    ) -> tuple[UserRecord, WorkspaceRecord, ProjectRecord]:
        return self.store.ensure_default_tenant()

    def create_user(self, request: CreateUserRequest) -> UserRecord:
        return self.store.create_user(request)

    def list_users(self) -> list[UserRecord]:
        return self.store.list_users()

    def create_workspace(self, request: CreateWorkspaceRequest) -> WorkspaceRecord:
        return self.store.create_workspace(request)

    def list_workspaces(self, actor_user_id: str) -> list[WorkspaceRecord]:
        return self.store.list_workspaces(actor_user_id)

    def _require_provider_workspace(
        self, actor_user_id: str, workspace_id: str
    ) -> WorkspaceRecord:
        workspace = next(
            (
                item
                for item in self.store.list_workspaces(actor_user_id)
                if item.workspace_id == workspace_id
            ),
            None,
        )
        if workspace is None:
            raise NotFoundError("workspace not found")
        return workspace

    def create_provider_profile(
        self,
        actor_user_id: str,
        request: ProviderProfileCreateRequest,
    ) -> ProviderProfileRecord:
        self._require_provider_workspace(actor_user_id, request.workspace_id)
        resolved = resolve_provider_config(request)
        secret_value = (
            request.api_key.get_secret_value().strip() if request.api_key else None
        )
        if secret_value and not self.provider_secret_store.available:
            raise ProductServiceError("secure provider secret storage is unavailable")
        profile_id = new_provider_profile_id()
        try:
            if secret_value:
                self.provider_secret_store.put(profile_id, secret_value)
        except (OSError, RuntimeError, ValueError) as error:
            raise ProductServiceError(
                "provider secret could not be stored securely"
            ) from error
        try:
            return self.provider_profile_registry.create(
                owner_user_id=actor_user_id,
                request=request,
                resolved=resolved,
                secret_configured=bool(secret_value),
                profile_id=profile_id,
            )
        except Exception:
            if secret_value:
                try:
                    self.provider_secret_store.delete(profile_id)
                except (OSError, RuntimeError, ValueError) as cleanup_error:
                    raise ProductServiceError(
                        "provider metadata failed and staged secret cleanup failed"
                    ) from cleanup_error
            raise

    def list_provider_profiles(
        self, actor_user_id: str, workspace_id: str
    ) -> list[ProviderProfileRecord]:
        self._require_provider_workspace(actor_user_id, workspace_id)
        return self.provider_profile_registry.list_for_owner(
            actor_user_id, workspace_id
        )

    def _provider_profile_for_actor(
        self, actor_user_id: str, profile_id: str
    ) -> ProviderProfileRecord:
        profile = self.provider_profile_registry.get_for_owner(
            actor_user_id, profile_id
        )
        if profile is None:
            raise NotFoundError("provider profile not found")
        self._require_provider_workspace(actor_user_id, profile.workspace_id)
        return profile

    def set_default_provider_profile(
        self, actor_user_id: str, profile_id: str
    ) -> ProviderProfileRecord:
        self._provider_profile_for_actor(actor_user_id, profile_id)
        profile = self.provider_profile_registry.set_default(actor_user_id, profile_id)
        if profile is None:
            raise NotFoundError("provider profile not found")
        return profile

    def revoke_provider_profile(
        self, actor_user_id: str, profile_id: str
    ) -> ProviderProfileRecord:
        self._provider_profile_for_actor(actor_user_id, profile_id)
        try:
            self.provider_secret_store.delete(profile_id)
        except (OSError, RuntimeError, ValueError) as error:
            raise ProductServiceError(
                "provider secret could not be revoked securely"
            ) from error
        profile = self.provider_profile_registry.revoke(actor_user_id, profile_id)
        if profile is None:
            raise NotFoundError("provider profile not found")
        return profile

    def test_provider_connection(
        self,
        actor_user_id: str,
        request: ProviderConnectionTestRequest,
    ) -> ProviderConnectionTestResult:
        self._require_provider_workspace(actor_user_id, request.workspace_id)
        resolved = resolve_provider_config(request)
        secret_value = (
            request.api_key.get_secret_value().strip() if request.api_key else None
        )
        return probe_provider_connection(resolved, api_key=secret_value)

    def test_saved_provider_connection(
        self, actor_user_id: str, profile_id: str
    ) -> ProviderConnectionTestResult:
        profile = self._provider_profile_for_actor(actor_user_id, profile_id)
        endpoint = self.provider_profile_registry.endpoint_for_profile(
            actor_user_id, profile_id
        )
        if endpoint is None:
            raise NotFoundError("provider profile not found")
        try:
            secret_value = self.provider_secret_store.get(profile_id)
        except (OSError, RuntimeError, ValueError) as error:
            raise ConflictError("provider secret could not be decrypted") from error
        if profile.secret_configured and not secret_value:
            raise ConflictError("provider secret is unavailable or was revoked")
        result = probe_provider_connection(
            profile_to_resolved_config(profile, endpoint=endpoint),
            api_key=secret_value,
        )
        self.provider_profile_registry.record_test(
            actor_user_id, profile_id, result.status
        )
        return result

    def create_project(
        self, actor_user_id: str, request: CreateProjectRequest
    ) -> ProjectRecord:
        return self.store.create_project(actor_user_id, request)

    def list_projects(
        self, actor_user_id: str, workspace_id: str
    ) -> list[ProjectRecord]:
        return self.store.list_projects(actor_user_id, workspace_id)

    def get_project(self, actor_user_id: str, project_id: str) -> ProjectRecord:
        return self.store.get_project(actor_user_id, project_id)

    def _require_allowlisted_local_root(self, value: str | Path) -> Path:
        if not self.local_source_allow_roots:
            raise UnsupportedSourceError(
                "no server-local source allow root is configured"
            )
        try:
            candidate = Path(value).expanduser().resolve(strict=True)
        except (OSError, RuntimeError) as exc:
            raise UnsupportedSourceError(
                "the requested local source directory is unavailable"
            ) from exc
        if not candidate.is_dir():
            raise UnsupportedSourceError(
                "the requested local source is not a directory"
            )
        for allowed_root in self.local_source_allow_roots:
            try:
                candidate.relative_to(allowed_root)
                return candidate
            except ValueError:
                continue
        raise UnsupportedSourceError(
            "the requested local source is outside the server allowlist"
        )

    def _execution_source_root(self, binding: Any) -> Path:
        """Resolve either an operator-allowlisted source or a private derived copy."""

        if (
            binding.receipt.adapter_kind
            is LocalSourceAdapterKind.OPERATOR_PROJECT_SNAPSHOT
            and binding.receipt.derived_version_id is None
        ):
            try:
                candidate = Path(binding.root_path).expanduser().resolve(strict=True)
                snapshot_root = (
                    self.product_root / "operator_project_snapshots"
                ).resolve(strict=False)
                candidate.relative_to(snapshot_root)
            except (OSError, RuntimeError, ValueError) as exc:
                raise UnsupportedSourceError(
                    "the operator project snapshot escaped its private product root"
                ) from exc
            if not candidate.is_dir() or candidate.is_symlink():
                raise UnsupportedSourceError(
                    "the operator project snapshot is unavailable"
                )
            return candidate
        if binding.receipt.derived_version_id is None:
            return self._require_allowlisted_local_root(binding.root_path)
        try:
            candidate = Path(binding.root_path).expanduser().resolve(strict=True)
            derived_root = (self.product_root / "derived_versions").resolve(
                strict=False
            )
            candidate.relative_to(derived_root)
        except (OSError, RuntimeError, ValueError) as exc:
            raise UnsupportedSourceError(
                "the derived source escaped the private product-derived root"
            ) from exc
        if not candidate.is_dir():
            raise UnsupportedSourceError("the private derived source is unavailable")
        return candidate

    @staticmethod
    def _profile_bound_source(binding: Any, source_root: Path) -> dict[str, Any]:
        if (
            binding.receipt.adapter_kind
            is LocalSourceAdapterKind.OPERATOR_PROJECT_SNAPSHOT
        ):
            profile = profile_operator_project_snapshot(
                source_root,
                expected_receipt_sha256=binding.receipt.source_archive_sha256,
            )
        else:
            profile = profile_omni_source(
                source_root,
                source_archive_sha256=binding.receipt.source_archive_sha256,
            )
        if binding.receipt.derived_version_id is None:
            return profile
        frozen = binding.receipt.data_profile
        profile.pop("profile_sha256", None)
        for key in (
            "source_assets_copied_into_product",
            "derived_version_id",
            "derived_from_source_id",
            "derived_manifest_sha256",
        ):
            if key in frozen:
                profile[key] = frozen[key]
        profile["profile_sha256"] = hashlib.sha256(
            canonical_json_bytes(profile)
        ).hexdigest()
        return profile

    @staticmethod
    def _local_source_binding_digest(
        receipt: LocalSourceAuthorizationReceipt,
    ) -> str:
        if receipt.derived_version_id is not None:
            value = receipt.data_profile.get("profile_sha256")
        else:
            value = receipt.data_profile.get(
                "operator_snapshot_receipt_sha256",
                receipt.data_profile.get("profile_sha256"),
            )
        if not isinstance(value, str):
            raise ArtifactUnavailableError("task source binding digest is unavailable")
        return value

    def authorize_local_source(
        self, actor_user_id: str, request: AuthorizeLocalSourceRequest
    ) -> LocalSourceAuthorizationReceipt:
        resolved_root = self._require_allowlisted_local_root(request.root_path)
        if request.adapter_kind is not LocalSourceAdapterKind.OMNI_AD_30_RELEASE:
            raise UnsupportedSourceError(
                "the requested local source adapter is unsupported"
            )
        try:
            data_profile = profile_omni_source(
                resolved_root,
                source_archive_sha256=request.source_archive_sha256,
            )
        except (OSError, RuntimeError, StopIteration, ValueError) as exc:
            raise UnsupportedSourceError(
                "the local source did not satisfy the selected read-only adapter"
            ) from exc
        normalized_path = os.path.normcase(str(resolved_root)).replace("\\", "/")
        root_path_sha256 = hashlib.sha256(normalized_path.encode("utf-8")).hexdigest()
        receipt = self.store.create_local_source_authorization(
            actor_user_id,
            request,
            resolved_root=resolved_root,
            root_path_sha256=root_path_sha256,
            data_profile=data_profile,
        )
        receipt_path = (
            self.product_root
            / "source_authorizations"
            / receipt.source_id
            / "authorization_receipt.json"
        )
        if not receipt_path.exists():
            write_canonical_json(receipt_path, receipt)
        for event in self.store.list_source_authorization_events(
            actor_user_id, receipt.source_id
        ):
            self._persist_source_authorization_event(event)
        return receipt

    def authorize_operator_project_snapshot(
        self,
        actor_user_id: str,
        request: AuthorizeOperatorProjectSnapshotRequest,
        operator_store: OperatorImageStore,
    ) -> LocalSourceAuthorizationReceipt:
        """Materialize and authorize one actor/project-scoped immutable snapshot."""

        project = self.store.get_project(actor_user_id, request.project_id)
        if (
            project.workspace_id != request.workspace_id
            or project.source_kind is not DataSourceKind.LOCAL_AUTHORIZED_DIRECTORY
        ):
            raise UnsupportedSourceError(
                "operator snapshot project is not an eligible local-source project"
            )
        try:
            snapshot = materialize_operator_project_snapshot(
                operator_store,
                actor_user_id=actor_user_id,
                workspace_id=request.workspace_id,
                project_id=request.project_id,
                snapshots_root=self.product_root / "operator_project_snapshots",
            )
        except (OSError, RuntimeError, ValueError) as exc:
            raise UnsupportedSourceError(
                "the operator project could not be materialized as a verified snapshot"
            ) from exc
        normalized_path = os.path.normcase(str(snapshot.root)).replace("\\", "/")
        source_request = AuthorizeLocalSourceRequest(
            workspace_id=request.workspace_id,
            display_name=request.display_name,
            root_path=str(snapshot.root),
            source_archive_sha256=snapshot.receipt.receipt_sha256,
            adapter_kind=LocalSourceAdapterKind.OPERATOR_PROJECT_SNAPSHOT,
            purpose=request.purpose,
            rights_basis=request.rights_basis,
            residency="product_local_private_operator_snapshot",
            operator_attests_authorized_use=True,
            read_only=True,
            raw_redistribution_allowed=False,
        )
        receipt = self.store.create_local_source_authorization(
            actor_user_id,
            source_request,
            resolved_root=snapshot.root,
            root_path_sha256=hashlib.sha256(
                normalized_path.encode("utf-8")
            ).hexdigest(),
            data_profile=snapshot.source_profile,
        )
        receipt_path = (
            self.product_root
            / "source_authorizations"
            / receipt.source_id
            / "authorization_receipt.json"
        )
        if not receipt_path.exists():
            write_canonical_json(receipt_path, receipt)
        for event in self.store.list_source_authorization_events(
            actor_user_id, receipt.source_id
        ):
            self._persist_source_authorization_event(event)
        return receipt

    def _persist_source_authorization_event(
        self, event: SourceAuthorizationEventReceipt
    ) -> None:
        event_path = (
            self.product_root
            / "source_authorizations"
            / event.source_id
            / "events"
            / f"{event.sequence:04d}-{event.event_id}.json"
        )
        if event_path.exists():
            existing = json.loads(event_path.read_text(encoding="utf-8"))
            if not hmac.compare_digest(
                str(existing.get("event_sha256", "")), event.event_sha256
            ):
                raise ArtifactUnavailableError(
                    "source authorization event artifact conflicts with the ledger"
                )
            return
        write_canonical_json(event_path, event)

    def list_source_authorization_events(
        self, actor_user_id: str, source_id: str
    ) -> list[SourceAuthorizationEventReceipt]:
        events = self.store.list_source_authorization_events(actor_user_id, source_id)
        for event in events:
            self._persist_source_authorization_event(event)
        return events

    def revoke_local_source_authorization(
        self,
        actor_user_id: str,
        source_id: str,
        request: RevokeLocalSourceAuthorizationRequest,
    ) -> SourceAuthorizationEventReceipt:
        event = self.store.revoke_local_source_authorization(
            actor_user_id, source_id, request
        )
        self._persist_source_authorization_event(event)
        return event

    def get_local_source_authorization(
        self, actor_user_id: str, source_id: str
    ) -> LocalSourceAuthorizationReceipt:
        receipt = self.store.get_local_source_authorization(actor_user_id, source_id)
        self.list_source_authorization_events(actor_user_id, source_id)
        return receipt

    def list_local_source_authorizations(
        self, actor_user_id: str, workspace_id: str
    ) -> list[LocalSourceAuthorizationReceipt]:
        receipts = self.store.list_local_source_authorizations(
            actor_user_id, workspace_id
        )
        for receipt in receipts:
            self.list_source_authorization_events(actor_user_id, receipt.source_id)
        return receipts

    def _live_source_profile_status(
        self, task: TaskRecord
    ) -> tuple[
        str,
        str | None,
        str | None,
    ]:
        """Compare the authorized source snapshot without exposing its local path."""

        if task.source_kind is DataSourceKind.SYNTHETIC_DEMO:
            return "NOT_APPLICABLE", None, None
        if (
            task.source_kind is not DataSourceKind.LOCAL_AUTHORIZED_DIRECTORY
            or not task.source_id
        ):
            return "UNAVAILABLE", None, None
        try:
            binding = self.store.get_local_source_binding_unscoped(task.source_id)
            frozen_value = binding.receipt.data_profile.get("profile_sha256")
            frozen = frozen_value if isinstance(frozen_value, str) else None
            if binding.receipt.status != "active" or frozen is None:
                return "UNAVAILABLE", frozen, None
            source_root = self._execution_source_root(binding)
            current_profile = self._profile_bound_source(binding, source_root)
            current_value = current_profile.get("profile_sha256")
            current = current_value if isinstance(current_value, str) else None
            if current is None:
                return "UNAVAILABLE", frozen, None
            return (
                "MATCHED" if hmac.compare_digest(frozen, current) else "CHANGED",
                frozen,
                current,
            )
        except (
            NotFoundError,
            OSError,
            RuntimeError,
            StopIteration,
            UnsupportedSourceError,
            ValueError,
        ):
            return "UNAVAILABLE", None, None

    def task_preflight(self, actor_user_id: str, task_id: str) -> TaskPreflightReport:
        """Evaluate run prerequisites before any source read or tool execution."""

        task = self.store.get_task(actor_user_id, task_id)
        preview = self.task_plan_preview(actor_user_id, task_id)
        interventions = self.store.list_interventions(actor_user_id, task_id)
        source_status, frozen_profile, current_profile = (
            self._live_source_profile_status(task)
        )
        source_authorization_status = "UNAVAILABLE"
        source_authorization_event_sha256: str | None = None
        if task.source_kind is DataSourceKind.SYNTHETIC_DEMO:
            source_authorization_status = "NOT_APPLICABLE"
        elif task.source_id is not None:
            try:
                source_receipt = self.store.get_local_source_authorization(
                    actor_user_id, task.source_id
                )
                source_authorization_status = source_receipt.status.upper()
                source_authorization_event_sha256 = (
                    source_receipt.latest_authorization_event_sha256
                )
            except (ConflictError, NotFoundError):
                source_authorization_status = "UNAVAILABLE"
        lifecycle_ready = task.execution_status is TaskExecutionStatus.PLANNED
        checks = [
            ReadinessCheck(
                key="task_lifecycle",
                label="任务生命周期",
                status="PASS" if lifecycle_ready else "BLOCKED",
                summary=(
                    "任务处于已规划状态，可进入运行门禁。"
                    if lifecycle_ready
                    else "只有已规划且未执行的任务可以通过运行前门禁。"
                ),
                evidence_ref=f"task:{task.task_id}",
                evidence_sha256=task.request_sha256,
            )
        ]
        if task.source_kind is DataSourceKind.SYNTHETIC_DEMO:
            checks.extend(
                [
                    ReadinessCheck(
                        key="source_authorization",
                        label="数据来源授权",
                        status="PASS",
                        summary="使用仓库内置合成演示数据，不读取外部目录。",
                        evidence_ref="data-source:synthetic-demo",
                    ),
                    ReadinessCheck(
                        key="source_snapshot",
                        label="输入快照一致性",
                        status="NOT_APPLICABLE",
                        summary="合成演示数据由运行时确定性生成，不使用外部授权快照。",
                        evidence_ref="data-source:synthetic-demo",
                    ),
                ]
            )
        else:
            source_matched = (
                source_status == "MATCHED" and source_authorization_status == "ACTIVE"
            )
            checks.extend(
                [
                    ReadinessCheck(
                        key="source_authorization",
                        label="数据来源授权",
                        status="PASS" if source_matched else "BLOCKED",
                        summary=(
                            "只读授权仍有效，服务端路径保持脱敏。"
                            if source_matched
                            else "授权来源当前不可验证或已失效，禁止开始运行。"
                        ),
                        evidence_ref=f"data-source:{task.source_id or 'unbound'}",
                        evidence_sha256=source_authorization_event_sha256,
                    ),
                    ReadinessCheck(
                        key="source_snapshot",
                        label="输入快照一致性",
                        status="PASS" if source_matched else "BLOCKED",
                        summary=(
                            "当前来源画像与授权时冻结画像一致。"
                            if source_matched
                            else "当前来源画像与冻结快照不一致或无法读取，必须重新授权。"
                        ),
                        evidence_ref="source-profile:live-redacted",
                        evidence_sha256=current_profile,
                    ),
                ]
            )

        unknown_tools = sorted(set(task.allowed_tools) - set(PUBLIC_TOOL_NAMES))
        checks.extend(
            [
                ReadinessCheck(
                    key="tool_contract",
                    label="工具白名单",
                    status="BLOCKED" if unknown_tools else "PASS",
                    summary=(
                        f"发现未登记工具：{', '.join(unknown_tools)}。"
                        if unknown_tools
                        else f"{len(task.allowed_tools)} 个工具均在冻结白名单内。"
                    ),
                    evidence_ref=f"task-request:{task.request_sha256}",
                    evidence_sha256=task.request_sha256,
                ),
                ReadinessCheck(
                    key="runtime_backend",
                    label="执行后端",
                    status="PASS",
                    summary="当前任务使用确定性 Runtime；外部 LLM 不是执行前提。",
                    evidence_ref="runtime-backend:deterministic",
                ),
            ]
        )

        plan_approval = next(
            (
                item
                for item in interventions
                if item.action is TaskInterventionAction.APPROVE_PLAN
            ),
            None,
        )
        approval_current = False
        approval_reason = "工具运行前仍需具名操作人批准计划。"
        if plan_approval is not None:
            approval_current, approval_reason = self._approval_binding_is_current(
                task=task,
                preview=preview,
                approval=plan_approval,
                source_status=source_status,
                frozen_profile_sha256=frozen_profile,
                current_profile_sha256=current_profile,
                current_source_authorization_event_sha256=(
                    source_authorization_event_sha256
                ),
            )
        if task.plan_approval_required:
            checks.append(
                ReadinessCheck(
                    key="human_plan_approval",
                    label="人工计划批准",
                    status=(
                        "PASS"
                        if approval_current
                        else "BLOCKED"
                        if plan_approval is not None
                        else "PENDING"
                    ),
                    summary=approval_reason,
                    evidence_ref=(
                        f"task-intervention:{plan_approval.intervention_id}"
                        "#/approval_binding"
                        if plan_approval is not None
                        else "task-interventions:append-only"
                    ),
                    evidence_sha256=(
                        plan_approval.approval_binding.binding_sha256
                        if plan_approval is not None
                        and plan_approval.approval_binding is not None
                        else None
                    ),
                )
            )
        else:
            checks.append(
                ReadinessCheck(
                    key="human_plan_approval",
                    label="人工计划批准",
                    status="NOT_APPLICABLE",
                    summary="本任务未启用运行前人工批准；生产最终权限仍只属于人。",
                    evidence_ref="task-plan:approval-not-required",
                )
            )
        checks.append(
            ReadinessCheck(
                key="production_authority",
                label="生产权限边界",
                status="PASS",
                summary="Agent 无源数据写权限、设备控制权限或生产放行权限。",
                evidence_ref="task-plan:human-only-production-authority",
                evidence_sha256=preview.plan_sha256,
            )
        )

        prerequisite_ready = lifecycle_ready and not any(
            item.status == "BLOCKED" for item in checks
        )
        approval_pending = any(item.status == "PENDING" for item in checks)
        execution_ready = prerequisite_ready and not approval_pending
        if not lifecycle_ready:
            overall_status = "NOT_RUNNABLE"
        elif not prerequisite_ready:
            overall_status = "BLOCKED"
        elif approval_pending:
            overall_status = "AWAITING_HUMAN_APPROVAL"
        else:
            overall_status = "READY_TO_RUN"
        return build_task_preflight_report(
            task_id=task.task_id,
            source_id=task.source_id,
            source_binding_sha256=preview.source_binding_sha256,
            lifecycle_status=task.execution_status,
            overall_status=overall_status,
            prerequisite_ready=prerequisite_ready,
            execution_ready=execution_ready,
            source_profile_status=source_status,
            frozen_source_profile_sha256=frozen_profile,
            current_source_profile_sha256=current_profile,
            source_authorization_status=source_authorization_status,
            source_authorization_event_sha256=(source_authorization_event_sha256),
            plan_sha256=preview.plan_sha256,
            checks=checks,
            production_authority="human_only",
        )

    @staticmethod
    def _seal_approval_binding(
        *,
        task: TaskRecord,
        preview: TaskPlanPreview,
        preflight: TaskPreflightReport,
    ) -> TaskPlanApprovalBinding:
        if preflight.source_profile_status == "MATCHED":
            source_profile_sha256 = preflight.current_source_profile_sha256
            if (
                source_profile_sha256 is None
                or source_profile_sha256 != preflight.frozen_source_profile_sha256
                or preflight.source_authorization_status != "ACTIVE"
                or preflight.source_authorization_event_sha256 is None
            ):
                raise ConflictError(
                    "source profile and authorization event are not stable enough "
                    "to bind plan approval"
                )
            source_profile_status = "MATCHED"
        elif preflight.source_profile_status == "NOT_APPLICABLE":
            source_profile_sha256 = None
            source_profile_status = "NOT_APPLICABLE"
        else:
            raise ConflictError("source profile cannot be bound to plan approval")
        stable = {
            "schema_version": "visiondata-gate.task-plan-approval-binding.v2",
            "request_sha256": task.request_sha256,
            "before_snapshot_sha256": preview.before_snapshot_sha256,
            "plan_sha256": preview.plan_sha256,
            "contract_sha256": task_contract_sha256(task),
            "source_profile_status": source_profile_status,
            "source_profile_sha256": source_profile_sha256,
            "source_authorization_event_sha256": (
                preflight.source_authorization_event_sha256
            ),
        }
        binding_sha256 = hashlib.sha256(canonical_json_bytes(stable)).hexdigest()
        return TaskPlanApprovalBinding(**stable, binding_sha256=binding_sha256)

    @staticmethod
    def _approval_binding_is_current(
        *,
        task: TaskRecord,
        preview: TaskPlanPreview,
        approval: TaskInterventionRecord,
        source_status: str,
        frozen_profile_sha256: str | None,
        current_profile_sha256: str | None,
        current_source_authorization_event_sha256: str | None,
    ) -> tuple[bool, str]:
        binding = approval.approval_binding
        if binding is None:
            return False, "旧批准缺少来源与规则合同绑定，已失败关闭。"
        payload = binding.model_dump(mode="json", exclude={"binding_sha256"})
        observed = hashlib.sha256(canonical_json_bytes(payload)).hexdigest()
        if not hmac.compare_digest(observed, binding.binding_sha256):
            return False, "批准绑定摘要不一致，旧批准已失效。"
        if not (
            hmac.compare_digest(binding.request_sha256, task.request_sha256)
            and hmac.compare_digest(
                binding.before_snapshot_sha256, preview.before_snapshot_sha256
            )
            and hmac.compare_digest(binding.plan_sha256, preview.plan_sha256)
            and hmac.compare_digest(binding.contract_sha256, task_contract_sha256(task))
        ):
            return False, "任务、计划或规则合同已变化，旧批准已失效。"
        if source_status == "NOT_APPLICABLE":
            source_current = (
                binding.source_profile_status == "NOT_APPLICABLE"
                and binding.source_profile_sha256 is None
                and binding.source_authorization_event_sha256 is None
            )
        elif source_status == "MATCHED":
            source_current = (
                binding.source_profile_status == "MATCHED"
                and current_profile_sha256 is not None
                and frozen_profile_sha256 is not None
                and hmac.compare_digest(
                    binding.source_profile_sha256 or "", current_profile_sha256
                )
                and hmac.compare_digest(current_profile_sha256, frozen_profile_sha256)
                and current_source_authorization_event_sha256 is not None
                and binding.source_authorization_event_sha256 is not None
                and hmac.compare_digest(
                    binding.source_authorization_event_sha256,
                    current_source_authorization_event_sha256,
                )
            )
        else:
            source_current = False
        if not source_current:
            return False, "来源快照已变化或不可验证，旧批准已失效。"
        return True, "具名操作人批准已绑定当前来源、任务、计划与规则合同。"

    @staticmethod
    def request_sha256(
        request: CreateTaskRequest,
        scenario_profile: str,
        *,
        source_binding_sha256: str | None = None,
    ) -> str:
        payload = request.model_dump(mode="json")
        payload["scenario_profile"] = scenario_profile
        if source_binding_sha256 is not None:
            payload = {
                "schema_version": "visiondata-gate.task-request-source-binding.v1",
                "task_request": payload,
                "source_id": request.source_id,
                "source_binding_sha256": source_binding_sha256,
            }
        return hashlib.sha256(canonical_json_bytes(payload)).hexdigest()

    def create_task(
        self,
        actor_user_id: str,
        request: CreateTaskRequest,
        *,
        idempotency_key: str | None = None,
        auto_start: bool = True,
    ) -> TaskRecord:
        return self._create_validated_task(
            actor_user_id,
            request,
            idempotency_key=idempotency_key,
            auto_start=auto_start,
        )

    def _create_validated_task(
        self,
        actor_user_id: str,
        request: CreateTaskRequest,
        *,
        idempotency_key: str | None,
        auto_start: bool,
        lineage_parent_task_id: str | None = None,
        lineage_contract_sha256: str | None = None,
        lineage_note: str | None = None,
    ) -> TaskRecord:
        project = self.store.get_project(actor_user_id, request.project_id)
        if request.source_kind is not project.source_kind:
            raise UnsupportedSourceError(
                "task data source must match the project's frozen data source"
            )
        source_binding_sha256: str | None = None
        if project.source_kind is DataSourceKind.SYNTHETIC_DEMO:
            if request.source_id is not None:
                raise UnsupportedSourceError(
                    "synthetic tasks cannot bind a local source authorization"
                )
        elif project.source_kind is DataSourceKind.LOCAL_AUTHORIZED_DIRECTORY:
            if request.source_id is None:
                raise UnsupportedSourceError(
                    "an active local source authorization is required"
                )
            receipt = self.store.get_local_source_authorization(
                actor_user_id, request.source_id
            )
            if (
                receipt.workspace_id != project.workspace_id
                or receipt.status != "active"
            ):
                raise UnsupportedSourceError(
                    "the local source authorization is not active for this workspace"
                )
            binding = self.store.get_local_source_binding_unscoped(receipt.source_id)
            source_root = self._execution_source_root(binding)
            current_profile = self._profile_bound_source(binding, source_root)
            frozen_profile = receipt.data_profile.get("profile_sha256")
            observed_profile = current_profile.get("profile_sha256")
            if not isinstance(frozen_profile, str):
                raise UnsupportedSourceError(
                    "the local source frozen profile digest is unavailable"
                )
            # Operator snapshots are private immutable product assets.  Reject
            # a broken snapshot before creating a task.  In-place authorized
            # directories retain the older two-stage contract: the Task may be
            # created, while Preflight and execution expose/stop on drift.
            if (
                receipt.adapter_kind is LocalSourceAdapterKind.OPERATOR_PROJECT_SNAPSHOT
                and not (
                    isinstance(observed_profile, str)
                    and hmac.compare_digest(frozen_profile, observed_profile)
                )
            ):
                raise UnsupportedSourceError(
                    "the local source failed its frozen profile binding"
                )
            try:
                source_binding_sha256 = self._local_source_binding_digest(receipt)
            except ArtifactUnavailableError as error:
                raise UnsupportedSourceError(
                    "the local source binding digest is unavailable"
                ) from error
        else:
            raise UnsupportedSourceError(
                "this data source is reserved but is not connected or authorized"
            )
        scenario = request.scenario_profile or project.scenario_profile
        effective_tools = list(request.allowed_tools)
        if scenario.value != "generic" and "governance_audit" not in effective_tools:
            effective_tools.append("governance_audit")
        effective_request = request.model_copy(
            update={
                "scenario_profile": scenario,
                "source_kind": project.source_kind,
                "allowed_tools": effective_tools,
            }
        )
        normalized_key = None
        if idempotency_key is not None:
            normalized_key = idempotency_key.strip()
            if not normalized_key:
                raise ProductServiceError("idempotency key cannot be blank")
        if lineage_parent_task_id is None:
            request_hash = self.request_sha256(
                effective_request,
                scenario.value,
                source_binding_sha256=source_binding_sha256,
            )
        else:
            request_hash = hashlib.sha256(
                canonical_json_bytes(
                    {
                        "schema_version": (
                            "visiondata-gate.reverification-request-binding.v2"
                        ),
                        "task_request": effective_request.model_dump(mode="json"),
                        "parent_task_id": lineage_parent_task_id,
                        "contract_sha256": lineage_contract_sha256,
                        "source_binding_sha256": source_binding_sha256,
                        "note": lineage_note,
                    }
                )
            ).hexdigest()
        task, created = self.store.create_task(
            actor_user_id,
            effective_request,
            scenario_profile=scenario.value,
            request_sha256=request_hash,
            idempotency_key=normalized_key,
            lineage_parent_task_id=lineage_parent_task_id,
            lineage_contract_sha256=lineage_contract_sha256,
            lineage_note=lineage_note,
        )
        if (
            auto_start
            and task.execution_status is TaskExecutionStatus.PLANNED
            and not task.plan_approval_required
        ):
            self.start_task(task.task_id)
        return task

    def create_reverification_task(
        self,
        actor_user_id: str,
        parent_task_id: str,
        request: CreateReverificationRequest,
        *,
        idempotency_key: str | None = None,
    ) -> TaskRecord:
        """Create a human-gated child run while keeping the parent immutable."""

        parent = self.store.get_task(actor_user_id, parent_task_id)
        if parent.execution_status is not TaskExecutionStatus.COMPLETED:
            raise ConflictError("re-verification requires a completed parent task")
        # Verify the parent bytes before persisting their digest into the edge.
        self.evidence_path(actor_user_id, parent_task_id)
        if parent.source_kind is DataSourceKind.SYNTHETIC_DEMO:
            if request.source_id is not None:
                raise UnsupportedSourceError(
                    "synthetic re-verification cannot bind a local source"
                )
            source_id = None
        elif parent.source_kind is DataSourceKind.LOCAL_AUTHORIZED_DIRECTORY:
            source_id = request.source_id or parent.source_id
            if source_id is None:
                raise UnsupportedSourceError(
                    "local re-verification requires an active source authorization"
                )
        else:
            raise UnsupportedSourceError(
                "the parent source type is not connected for re-verification"
            )
        prefix = f"同合同复验（父任务 {parent.task_id}）："
        goal = prefix + parent.goal[: max(0, 1200 - len(prefix))]
        child_request = CreateTaskRequest(
            project_id=parent.project_id,
            goal=goal,
            seed=parent.seed,
            scenario_profile=parent.scenario_profile,
            source_kind=parent.source_kind,
            source_id=source_id,
            plan_approval_required=True,
            allowed_tools=list(parent.allowed_tools),
        )
        contract_sha256 = task_contract_sha256(parent)
        return self._create_validated_task(
            actor_user_id,
            child_request,
            idempotency_key=idempotency_key,
            auto_start=False,
            lineage_parent_task_id=parent.task_id,
            lineage_contract_sha256=contract_sha256,
            lineage_note=request.note,
        )

    def task_lineage(self, actor_user_id: str, task_id: str) -> TaskLineageReport:
        tasks, edges = self.store.get_task_lineage(actor_user_id, task_id)
        for item in tasks:
            if item.execution_status is TaskExecutionStatus.COMPLETED:
                self.evidence_path(actor_user_id, item.task_id)
        source_bindings: dict[str, str] = {}
        for item in tasks:
            if not item.source_id or item.source_id in source_bindings:
                continue
            source = self.store.get_local_source_authorization(
                actor_user_id, item.source_id
            )
            source_bindings[item.source_id] = self._local_source_binding_digest(source)
        try:
            return build_task_lineage_report(
                focus_task_id=task_id,
                tasks=tasks,
                edges=edges,
                source_binding_sha256_by_id=source_bindings,
            )
        except ValueError as error:
            raise ArtifactUnavailableError(
                "task lineage failed integrity validation"
            ) from error

    @staticmethod
    def _build_task_plan_preview(
        task: TaskRecord,
        *,
        before_snapshot_sha256: str,
        source_binding_sha256: str | None,
    ) -> TaskPlanPreview:
        measurement_tools = [
            name for name in task.allowed_tools if name != "governance_audit"
        ]
        steps = [
            TaskPlanStep(
                step_id="plan.intent-and-contract",
                phase="intake",
                agent_role="Leader",
                objective="理解任务目标并冻结来源、工具权限与工业规则边界。",
            ),
            TaskPlanStep(
                step_id="plan.multi-source-measurement",
                phase="initial",
                agent_role="Evidence Worker Pool",
                objective="并行读取图像、标注、manifest 和 metadata，生成可哈希测量。",
                tool_names=measurement_tools,
            ),
            TaskPlanStep(
                step_id="plan.evidence-reconciliation",
                phase="verification",
                agent_role="Dynamic Leader",
                objective="仅在漂移、冲突或分辨率组变化出现时增派只读补证 Worker。",
                tool_names=[
                    name for name in task.allowed_tools if name == "governance_audit"
                ],
            ),
            TaskPlanStep(
                step_id="plan.policy-judgement",
                phase="verification",
                agent_role="Frozen Policy Judge",
                objective="依据冻结规则生成 fail-closed 裁决、解释和工单。",
            ),
            TaskPlanStep(
                step_id="plan.delivery-and-human-handoff",
                phase="delivery",
                agent_role="Evidence Delivery",
                objective="交付证据包、工业回执和人工最终审批边界。",
                human_gate=True,
            ),
        ]
        stable_plan = {
            "schema_version": "visiondata-gate.task-plan-preview.v2",
            "task_id": task.task_id,
            "request_sha256": task.request_sha256,
            "goal": task.goal,
            "scenario_profile": task.scenario_profile,
            "source_kind": task.source_kind,
            "source_id": task.source_id,
            "source_binding_sha256": source_binding_sha256,
            "allowed_tools": task.allowed_tools,
            "approval_required": task.plan_approval_required,
            "steps": steps,
            "dynamic_replanning_policy": (
                "Intermediate evidence may dispatch bounded read-only follow-ups; "
                "unobserved branches are not executed and no source mutation is allowed."
            ),
            "production_authority": "human_only",
            "claim_boundary": (
                "This is a deterministic execution preview, not proof that the task has "
                "run or that production release has been approved."
            ),
        }
        plan_sha256 = hashlib.sha256(canonical_json_bytes(stable_plan)).hexdigest()
        return TaskPlanPreview(
            **stable_plan,
            before_snapshot_sha256=before_snapshot_sha256,
            plan_sha256=plan_sha256,
        )

    def _task_source_binding_sha256(self, task: TaskRecord) -> str | None:
        if task.source_id is None:
            return None
        receipt = self.store.get_local_source_authorization(
            task.created_by, task.source_id
        )
        return self._local_source_binding_digest(receipt)

    def task_plan_preview(self, actor_user_id: str, task_id: str) -> TaskPlanPreview:
        task = self.store.get_task(actor_user_id, task_id)
        return self._build_task_plan_preview(
            task,
            before_snapshot_sha256=self.store.task_snapshot_sha256(task),
            source_binding_sha256=self._task_source_binding_sha256(task),
        )

    def intervene_task(
        self,
        actor_user_id: str,
        task_id: str,
        request: TaskInterventionRequest,
        *,
        start_approved_task: bool = True,
    ) -> TaskInterventionRecord:
        approval_binding: TaskPlanApprovalBinding | None = None
        if request.action is TaskInterventionAction.APPROVE_PLAN:
            preflight = self.task_preflight(actor_user_id, task_id)
            if not preflight.prerequisite_ready:
                raise ConflictError(
                    "task preflight prerequisites are blocked; inspect the preflight "
                    "report before approving execution"
                )
        task = self.store.get_task(actor_user_id, task_id)
        preview = self.task_plan_preview(actor_user_id, task_id)
        if request.action is TaskInterventionAction.APPROVE_PLAN:
            approval_binding = self._seal_approval_binding(
                task=task,
                preview=preview,
                preflight=preflight,
            )
        record = self.store.record_intervention(
            actor_user_id,
            task_id,
            request,
            plan_sha256=preview.plan_sha256,
            expected_snapshot_sha256=preview.before_snapshot_sha256,
            approval_binding=approval_binding,
        )
        if (
            request.action is TaskInterventionAction.APPROVE_PLAN
            and start_approved_task
        ):
            self.start_task(task_id)
        return record

    def list_interventions(
        self, actor_user_id: str, task_id: str
    ) -> list[TaskInterventionRecord]:
        return self.store.list_interventions(actor_user_id, task_id)

    def start_task(self, task_id: str) -> None:
        with self._future_lock:
            existing = self._futures.get(task_id)
            if existing is not None and not existing.done():
                return
            future = self._executor.submit(self._execute_task, task_id)
            self._futures[task_id] = future
        future.add_done_callback(
            lambda completed, run_id=task_id: self._discard_future(run_id, completed)
        )

    def _discard_future(self, task_id: str, expected: Future[None]) -> None:
        with self._future_lock:
            if self._futures.get(task_id) is expected:
                self._futures.pop(task_id, None)

    def run_task_sync(self, task_id: str) -> TaskRecord:
        before = self.store.get_task_unscoped(task_id)
        self._execute_task(task_id)
        after = self.store.get_task_unscoped(task_id)
        if (
            before.execution_status is TaskExecutionStatus.PLANNED
            and before.plan_approval_required
            and after.execution_status is TaskExecutionStatus.PLANNED
        ):
            raise ConflictError(
                "task plan approval is required and must be current before execution"
            )
        return after

    def _task_root(self, task: TaskRecord) -> Path:
        return (
            self.product_root
            / "runs"
            / task.workspace_id
            / task.project_id
            / task.task_id
            / "attempt-001"
        ).resolve()

    def _relative(self, path: Path) -> str:
        resolved = path.resolve(strict=False)
        try:
            return resolved.relative_to(self.product_root).as_posix()
        except ValueError as exc:
            raise ArtifactUnavailableError(
                "artifact path escaped product root"
            ) from exc

    def _execute_task(self, task_id: str) -> None:
        planned_task = self.store.get_task_unscoped(task_id)
        planned_snapshot_sha256 = self.store.task_snapshot_sha256(planned_task)
        if planned_task.plan_approval_required:
            preflight = self.task_preflight(planned_task.created_by, task_id)
            if not preflight.execution_ready:
                return
        if not self.store.claim_task(task_id):
            return
        try:
            task = self.store.get_task_unscoped(task_id)
            task_root = self._task_root(task)
            if task_root.exists():
                raise ArtifactUnavailableError(
                    "the immutable task output directory already exists"
                )
            config = RuntimeConfig(
                backend=ModelBackendKind.DETERMINISTIC,
                scenario_profile=task.scenario_profile,
                allowed_tools=task.allowed_tools,
                persist_memory=True,
            )

            def on_event(event: Any) -> None:
                self.store.append_event(task_id, event)
                if str(event.phase) == "verification":
                    self.store.set_verifying_if_running(task_id)

            if task.source_kind is DataSourceKind.LOCAL_AUTHORIZED_DIRECTORY:
                if not task.source_id:
                    raise UnsupportedSourceError(
                        "the task lost its local source authorization binding"
                    )
                binding = self.store.get_local_source_binding_unscoped(task.source_id)
                if binding.receipt.status != "active":
                    raise UnsupportedSourceError(
                        "the bound source authorization is revoked or expired"
                    )
                source_root = self._execution_source_root(binding)
                current_profile = self._profile_bound_source(binding, source_root)
                if current_profile.get(
                    "profile_sha256"
                ) != binding.receipt.data_profile.get("profile_sha256"):
                    raise UnsupportedSourceError(
                        "the authorized local source profile changed before execution"
                    )
                if (
                    binding.receipt.adapter_kind
                    is LocalSourceAdapterKind.OPERATOR_PROJECT_SNAPSHOT
                ):
                    run = run_operator_snapshot_product_task(
                        task_root,
                        source_root=source_root,
                        source_receipt=binding.receipt,
                        seed=task.seed,
                        goal=task.goal,
                        config=config,
                        event_sink=on_event,
                    )
                else:
                    omni_rulepack_path = self._verified_omni_rulepack_path()
                    run = run_omni_product_task(
                        task_root,
                        source_root=source_root,
                        source_receipt=binding.receipt,
                        seed=task.seed,
                        goal=task.goal,
                        config=config,
                        event_sink=on_event,
                        rulepack_path=omni_rulepack_path,
                        expected_rulepack_source_sha256=(
                            self.omni_rulepack_source_sha256
                        ),
                    )
            else:
                raw_run = self.runner(
                    task_root,
                    seed=task.seed,
                    goal=task.goal,
                    config=config,
                    memory_path=task_root / "runtime_memory.json",
                    event_sink=on_event,
                )
                run = (
                    raw_run
                    if isinstance(raw_run, ProductTaskRun)
                    else normalize_agentic_run(raw_run)
                )
            if run.evidence_dir.resolve(strict=True) != (
                task_root / "evidence"
            ).resolve(strict=True):
                raise ArtifactUnavailableError(
                    "Agent kernel evidence is not bound to the current immutable task root"
                )
            expected_runtime_kind = "synthetic_demo"
            if task.source_kind is DataSourceKind.LOCAL_AUTHORIZED_DIRECTORY:
                source = self.store.get_local_source_authorization(
                    task.created_by, task.source_id or ""
                )
                expected_runtime_kind = (
                    "operator_project_snapshot"
                    if source.adapter_kind
                    is LocalSourceAdapterKind.OPERATOR_PROJECT_SNAPSHOT
                    else "authorized_local_readonly"
                )
            if run.kernel_receipt.runtime_kind != expected_runtime_kind:
                raise ArtifactUnavailableError(
                    "Agent kernel runtime kind does not match the task source contract"
                )
            verify_product_task_run(run)
            self.store.reconcile_events(task_id, list(run.events))
            task_plan = self._build_task_plan_preview(
                planned_task,
                before_snapshot_sha256=planned_snapshot_sha256,
                source_binding_sha256=self._task_source_binding_sha256(planned_task),
            )
            write_canonical_json(run.evidence_dir / "task_plan_preview.json", task_plan)
            interventions = self.store.list_interventions(
                planned_task.created_by, task_id
            )
            write_canonical_json(
                run.evidence_dir / "task_intervention_timeline.json",
                {
                    "schema_version": "visiondata-gate.task-intervention-timeline.v1",
                    "task_id": task_id,
                    "append_only": True,
                    "interventions": interventions,
                    "claim_boundary": (
                        "The embedded timeline is frozen at evidence-package creation. "
                        "Post-run review actions remain available through the task API."
                    ),
                },
            )
            required_paths = (
                *run.required_evidence_paths,
                "task_plan_preview.json",
                "task_intervention_timeline.json",
            )
            industrial_receipt = build_industrial_delivery_receipt(
                task, run.evidence_dir
            )
            write_canonical_json(
                run.evidence_dir / "industrial_delivery_receipt.json",
                industrial_receipt,
            )
            required_paths = (*required_paths, "industrial_delivery_receipt.json")
            # Packaging is a separate concern from runtime completion. Recheck the
            # typed kernel contract after product-side enrichment so a mutated core
            # artifact can never be hidden inside a structurally valid ZIP.
            verify_product_task_run(run)
            evidence_zip = task_root / "VisionDataGate_TaskEvidence.zip"
            build_deterministic_zip(run.evidence_dir, evidence_zip, overwrite=False)
            audit = audit_submission_zip(evidence_zip, required_paths=required_paths)
            if not audit.ok:
                raise ArtifactUnavailableError(
                    f"task evidence audit failed with {len(audit.issues)} issue(s)"
                )
            final = TaskExecutionStatus.COMPLETED
            current = self.store.get_task_unscoped(task_id).execution_status
            if current is TaskExecutionStatus.RUNNING:
                self.store.set_verifying_if_running(task_id)
            self.store.transition_task(
                task_id,
                final,
                current_phase="completed",
                fields={
                    "initial_decision": run.initial_decision.value,
                    "final_decision": run.final_decision.value,
                    "runtime_status": run.runtime_status.value,
                    "artifact_root_rel": self._relative(task_root),
                    "trace_rel": self._relative(run.runtime_trace_path),
                    "trace_sha256": sha256_file(run.runtime_trace_path),
                    "evidence_zip_rel": self._relative(evidence_zip),
                    "evidence_sha256": sha256_file(evidence_zip),
                    "completed_at": _now(),
                },
            )
        except Exception as exc:
            current = self.store.get_task_unscoped(task_id)
            if current.execution_status in {
                TaskExecutionStatus.RUNNING,
                TaskExecutionStatus.VERIFYING,
            }:
                self.store.transition_task(
                    task_id,
                    TaskExecutionStatus.FAILED,
                    current_phase="failed",
                    fields={
                        "error_code": type(exc).__name__,
                        "error_message": str(exc)[:500],
                        "completed_at": _now(),
                    },
                )

    def get_task(self, actor_user_id: str, task_id: str) -> TaskRecord:
        return self.store.get_task(actor_user_id, task_id)

    def industrial_delivery_receipt(
        self, actor_user_id: str, task_id: str
    ) -> IndustrialDeliveryReceipt:
        task = self.store.get_task(actor_user_id, task_id)
        if task.execution_status is not TaskExecutionStatus.COMPLETED:
            raise ArtifactUnavailableError(
                "industrial delivery receipt requires a completed task"
            )
        payload = self.read_evidence_zip_json(
            actor_user_id, task_id, "industrial_delivery_receipt.json"
        )
        try:
            return IndustrialDeliveryReceipt.model_validate(payload)
        except ValueError as error:
            raise ArtifactUnavailableError(
                "industrial delivery receipt failed schema validation"
            ) from error

    def _operator_snapshot_visual_context(
        self,
        actor_user_id: str,
        task_id: str,
    ) -> tuple[
        TaskRecord,
        Path,
        OperatorProjectSnapshotReceipt,
        str,
    ]:
        """Resolve one task's frozen Operator snapshot without exposing its path."""

        task = self.store.get_task(actor_user_id, task_id)
        if task.execution_status is not TaskExecutionStatus.COMPLETED:
            raise ArtifactUnavailableError(
                "task visual evidence requires a completed immutable task"
            )
        if (
            task.source_kind is not DataSourceKind.LOCAL_AUTHORIZED_DIRECTORY
            or task.source_id is None
        ):
            raise ArtifactUnavailableError(
                "task visual evidence requires an authorized Operator snapshot"
            )
        binding = self.store.get_local_source_binding_unscoped(task.source_id)
        if (
            binding.receipt.adapter_kind
            is not LocalSourceAdapterKind.OPERATOR_PROJECT_SNAPSHOT
        ):
            raise ArtifactUnavailableError(
                "task visual evidence is unavailable for this source adapter"
            )
        source_root = self._execution_source_root(binding)
        try:
            profile = self._profile_bound_source(binding, source_root)
            observed_profile_sha256 = profile.get("profile_sha256")
            frozen_profile_sha256 = binding.receipt.data_profile.get("profile_sha256")
            if not (
                isinstance(observed_profile_sha256, str)
                and isinstance(frozen_profile_sha256, str)
                and hmac.compare_digest(
                    observed_profile_sha256,
                    frozen_profile_sha256,
                )
            ):
                raise ValueError("operator snapshot profile binding drifted")
            snapshot = OperatorProjectSnapshotReceipt.model_validate(
                self.read_evidence_zip_json(
                    actor_user_id,
                    task_id,
                    "operator_project_snapshot_receipt.json",
                )
            )
        except (OSError, RuntimeError, ValueError) as error:
            raise ArtifactUnavailableError(
                "task visual evidence failed frozen snapshot validation"
            ) from error
        if not (
            snapshot.workspace_id == task.workspace_id
            and snapshot.project_id == task.project_id
            and hmac.compare_digest(
                snapshot.receipt_sha256,
                binding.receipt.source_archive_sha256,
            )
            and hmac.compare_digest(
                snapshot.receipt_sha256,
                str(
                    binding.receipt.data_profile.get(
                        "operator_snapshot_receipt_sha256",
                        "",
                    )
                ),
            )
        ):
            raise ArtifactUnavailableError(
                "task visual evidence failed task/source identity binding"
            )
        return task, source_root, snapshot, observed_profile_sha256

    def task_visual_evidence_manifest(
        self,
        actor_user_id: str,
        task_id: str,
    ) -> TaskVisualEvidenceManifest:
        """Project sample previews and measurements from sealed task evidence."""

        task, _source_root, snapshot, source_profile_sha256 = (
            self._operator_snapshot_visual_context(actor_user_id, task_id)
        )
        delivery = self.industrial_delivery_receipt(actor_user_id, task_id)
        try:
            return build_task_visual_evidence_manifest(
                task=task,
                snapshot=snapshot,
                delivery=delivery,
                source_profile_sha256=source_profile_sha256,
            )
        except ValueError as error:
            raise ArtifactUnavailableError(
                "task visual evidence projection failed validation"
            ) from error

    def task_visual_evidence_path(
        self,
        actor_user_id: str,
        task_id: str,
        sample_id: str,
        *,
        variant: str,
    ) -> tuple[Path, str, str]:
        """Resolve one exact frozen preview or mask and verify its byte digest."""

        _task, source_root, snapshot, _profile_sha256 = (
            self._operator_snapshot_visual_context(actor_user_id, task_id)
        )
        asset = next(
            (item for item in snapshot.assets if item.asset_id == sample_id),
            None,
        )
        if asset is None:
            raise NotFoundError("task visual evidence sample not found")
        if variant == "preview":
            relative_path = asset.preview_relative_path
            expected_sha256 = asset.preview_sha256
            media_type = "image/jpeg"
        elif variant == "mask" and asset.mask_relative_path and asset.mask_sha256:
            relative_path = asset.mask_relative_path
            expected_sha256 = asset.mask_sha256
            media_type = "image/png"
        elif variant == "mask":
            raise NotFoundError("task visual evidence mask not found")
        else:
            raise NotFoundError("task visual evidence variant not found")
        try:
            candidate = (source_root / relative_path).resolve(strict=True)
            candidate.relative_to(source_root)
        except (OSError, RuntimeError, ValueError) as error:
            raise ArtifactUnavailableError(
                "task visual evidence member escaped its frozen snapshot"
            ) from error
        if not candidate.is_file() or candidate.is_symlink():
            raise ArtifactUnavailableError("task visual evidence member is unavailable")
        observed_sha256 = sha256_file(candidate)
        if not hmac.compare_digest(observed_sha256, expected_sha256):
            raise ArtifactUnavailableError(
                "task visual evidence member failed byte integrity validation"
            )
        return candidate, media_type, observed_sha256

    @staticmethod
    def _validate_incident_case_id(case_id: str) -> None:
        suffix = case_id.removeprefix("incident_")
        if (
            not case_id.startswith("incident_")
            or len(suffix) != 20
            or any(character not in "0123456789abcdef" for character in suffix)
        ):
            raise NotFoundError("industrial incident case not found")

    def _incident_task_root(self, task: TaskRecord) -> Path:
        root = (
            self.product_root
            / "industrial_incidents"
            / task.workspace_id
            / task.project_id
            / task.task_id
        ).resolve(strict=False)
        try:
            root.relative_to(
                (self.product_root / "industrial_incidents").resolve(strict=False)
            )
        except ValueError as error:
            raise ArtifactUnavailableError(
                "industrial incident path escaped product root"
            ) from error
        return root

    def _incident_case_root(self, task: TaskRecord, case_id: str) -> Path:
        self._validate_incident_case_id(case_id)
        return self._incident_task_root(task) / case_id

    def _incident_audit_anchor_path(
        self,
        task: TaskRecord,
        case_id: str,
    ) -> Path:
        self._validate_incident_case_id(case_id)
        return (
            self._incident_task_root(task)
            / "governed_audit_anchors"
            / f"{case_id}.json"
        )

    def _workspace_provider_planner(
        self,
        actor_user_id: str,
        task: TaskRecord,
        profile: IncidentRuntimeProfile,
    ) -> IncidentModelPlanner:
        if profile.provider_profile_id is not None:
            provider = self._provider_profile_for_actor(
                actor_user_id, profile.provider_profile_id
            )
            if provider.workspace_id != task.workspace_id:
                raise ConflictError(
                    "selected BYOK provider profile does not belong to the task workspace"
                )
        else:
            provider = self.provider_profile_registry.get_default(
                actor_user_id, task.workspace_id
            )
        if provider is None:
            raise ConflictError(
                "workspace BYOK runtime requires a default provider profile"
            )
        endpoint = self.provider_profile_registry.endpoint_for_profile(
            actor_user_id, provider.profile_id
        )
        if endpoint is None:
            raise ConflictError("default provider profile endpoint is unavailable")
        try:
            secret_value = self.provider_secret_store.get(provider.profile_id)
        except (OSError, RuntimeError, ValueError) as error:
            raise ConflictError(
                "default provider secret could not be decrypted"
            ) from error
        if provider.secret_configured and not secret_value:
            raise ConflictError("default provider secret is unavailable or revoked")
        resolved = profile_to_resolved_config(provider, endpoint=endpoint)
        config = IncidentModelPlannerConfig(
            mode=profile.planner_mode,
            endpoint=resolved.endpoint,
            model=resolved.model,
            allow_remote_model=not resolved.allow_local,
            remote_endpoint_hosts=[resolved.endpoint_host],
            timeout_seconds=resolved.timeout_seconds,
            max_retries=resolved.max_retries,
            temperature=profile.temperature,
            max_tokens=profile.max_output_tokens,
            context_budget_tokens=profile.context_budget_tokens,
        )
        return IncidentModelPlanner(config, api_key=secret_value)

    def _planner_for_incident_request(
        self,
        actor_user_id: str,
        task: TaskRecord,
        request: IndustrialIncidentRequest,
    ) -> IncidentModelPlanner | None:
        profile = incident_runtime_profile(request)
        if profile is None:
            return self.incident_model_planner
        if profile.model_profile_id == "workspace-byok":
            return self._workspace_provider_planner(actor_user_id, task, profile)
        if profile.memory_mode is IncidentMemoryMode.APPROVED_SITE:
            if profile.site_profile_id not in self.incident_site_profiles:
                raise ConflictError(
                    "requested governed-memory site profile is not available"
                )
            if not self.governed_memory_ready:
                raise ConflictError("approved governed-memory store is not configured")
        try:
            return planner_from_runtime_profile(profile)
        except ValueError as error:
            raise ConflictError(str(error)) from error

    @staticmethod
    def _incident_memory_query_terms(
        request: IndustrialIncidentRequest,
    ) -> list[str]:
        trigger = request.trigger
        return [
            trigger.trigger_kind.value,
            trigger.operator_message,
            trigger.product_id,
            trigger.recipe_id,
            trigger.configuration_id,
            *(value for value in (trigger.part_id, trigger.line_id) if value),
            *(item.semantic_alias for item in request.process_signal_expectations),
            *(item.title for item in request.knowledge_references),
        ][:32]

    def _prepare_incident_governed_memory(
        self,
        task: TaskRecord,
        request: IndustrialIncidentRequest,
        gate_context: IndustrialGateContext,
        *,
        command_admission: IncidentCommandAdmission,
        authorizing_decision: IndustrialIncidentDecisionReceipt | None = None,
    ) -> tuple[FactorySitePack | None, GovernedMemoryPlanningInput | None]:
        profile = incident_runtime_profile(request)
        if profile is None or profile.memory_mode is IncidentMemoryMode.OFF:
            return None, None
        assert profile.site_profile_id is not None
        site_root = self.incident_site_profiles.get(profile.site_profile_id)
        if site_root is None or self.approved_memory_store_path is None:
            raise ConflictError("governed-memory profile became unavailable")
        site_pack = load_factory_site_pack(site_root)
        if self.memory_admission_mode == "strict_envelope_v1":
            cards, admission_receipt = load_memory_admission_store(
                self.approved_memory_store_path,
                expected_workspace_id=task.workspace_id,
                expected_project_id=task.project_id,
                source_case_registry=self.memory_source_case_registry,
            )
            admission_status: Literal[
                "STRICT_PROMOTION_CHAIN_VERIFIED",
                "LEGACY_CARD_EXPLICITLY_ALLOWED",
            ] = "STRICT_PROMOTION_CHAIN_VERIFIED"
            admission_store_sha256 = admission_receipt.store_sha256
        else:
            cards = load_approved_memory_store(self.approved_memory_store_path)
            admission_status = "LEGACY_CARD_EXPLICITLY_ALLOWED"
            admission_store_sha256 = hashlib.sha256(
                self.approved_memory_store_path.read_bytes()
            ).hexdigest()
        planning_subject_sha256 = industrial_incident_planning_subject_sha256(
            request,
            gate_context,
            authorizing_decision=authorizing_decision,
        )
        try:
            verify_incident_command_admission(command_admission)
        except ValueError as error:
            raise ConflictError(
                "governed memory requires a valid command admission"
            ) from error
        request_sha256 = hashlib.sha256(canonical_json_bytes(request)).hexdigest()
        if command_admission.task_id != task.task_id or not hmac.compare_digest(
            command_admission.request_sha256,
            request_sha256,
        ):
            raise ConflictError("governed-memory admission lost task/request binding")
        processing_time_source = MemoryProcessingTimeSource(
            source_kind="INCIDENT_COMMAND_ADMISSION",
            source_id=command_admission.command_id,
            source_sha256=command_admission.admission_sha256,
        )
        planning_input = build_governed_memory_planning_input(
            planning_subject_sha256=planning_subject_sha256,
            site_pack=site_pack,
            memory_cards=cards,
            line_id=request.trigger.line_id,
            as_of=request.trigger.triggered_at,
            processing_time=command_admission.admitted_at,
            processing_time_source=processing_time_source,
            query_terms=self._incident_memory_query_terms(request),
            memory_limit=profile.memory_top_k,
            retrieval_profile=DEFAULT_HYBRID_RETRIEVAL_PROFILE_V2,
            memory_admission_status=admission_status,
            memory_admission_store_sha256=admission_store_sha256,
        )
        retrieval = planning_input.retrieval_receipt
        if not isinstance(retrieval, HybridMemoryRetrievalReceiptV3):
            raise ConflictError("new governed-memory planning requires a v3 receipt")
        try:
            verification = verify_memory_retrieval_command_admission_binding(
                retrieval,
                command_id=command_admission.command_id,
                admission_sha256=command_admission.admission_sha256,
                admitted_at=command_admission.admitted_at,
            )
        except ValueError as error:
            raise ConflictError(
                "governed-memory clock lost command admission binding"
            ) from error
        if verification.source_binding_evidence != "COMMAND_ADMISSION_VERIFIED":
            raise ConflictError("governed-memory command admission was not verified")
        return site_pack, planning_input

    def _assemble_incident_runtime_context(
        self,
        case: IndustrialIncidentCase,
        *,
        site_pack: FactorySitePack | None,
        planning_input: GovernedMemoryPlanningInput | None,
    ) -> AssembledIncidentContext | None:
        profile = incident_runtime_profile(case.request)
        if profile is None or profile.memory_mode is IncidentMemoryMode.OFF:
            if site_pack is not None or planning_input is not None:
                raise ConflictError("memory-off incident received governed memory")
            return None
        if site_pack is None or planning_input is None:
            raise ConflictError("governed-memory pre-planning input is unavailable")
        assembled = assemble_incident_context(
            case=case,
            site_pack=site_pack,
            memory_cards=[],
            memory_limit=profile.memory_top_k,
            planning_input=planning_input,
        )
        return assembled

    def _persist_incident_runtime_artifacts(
        self,
        task: TaskRecord,
        case: IndustrialIncidentCase,
        *,
        site_pack: FactorySitePack | None,
        assembled_context: AssembledIncidentContext | None,
    ) -> IncidentRuntimeProfileBinding | None:
        profile = incident_runtime_profile(case.request)
        if profile is None:
            return None
        planner_receipt = case.model_planner_receipt
        selected_count = (
            len(assembled_context.retrieval_receipt.selected)
            if assembled_context is not None
            else 0
        )
        rejected_count = (
            len(assembled_context.retrieval_receipt.rejected)
            if assembled_context is not None
            else 0
        )
        binding = build_runtime_profile_binding(
            case_id=case.case_id,
            case_sha256=case.case_sha256,
            profile=profile,
            planner_config_sha256=(
                planner_receipt.config_sha256 if planner_receipt is not None else None
            ),
            planner_connection_status=(
                planner_receipt.connection_status
                if planner_receipt is not None
                else "OFF"
            ),
            governed_context_receipt_sha256=(
                assembled_context.receipt.receipt_sha256
                if assembled_context is not None
                else None
            ),
            selected_memory_count=selected_count,
            rejected_memory_count=rejected_count,
            governed_memory_planning_input_sha256=(
                assembled_context.planning_input.input_sha256
                if assembled_context is not None
                and assembled_context.planning_input is not None
                else None
            ),
            governed_memory_retrieval_receipt_sha256=(
                assembled_context.retrieval_receipt.receipt_sha256
                if assembled_context is not None
                else None
            ),
        )
        root = self._incident_case_root(task, case.case_id) / "runtime"
        _write_once_json(root / "profile_binding.json", binding)
        if site_pack is not None and assembled_context is not None:
            _write_once_json(root / "site_pack.json", site_pack)
            _write_once_json(root / "governed_context.json", assembled_context)
        return binding

    def _read_incident_runtime_artifacts(
        self,
        task: TaskRecord,
        case: IndustrialIncidentCase,
    ) -> tuple[
        IncidentRuntimeProfileBinding | None,
        FactorySitePack | None,
        AssembledIncidentContext | None,
    ]:
        root = self._incident_case_root(task, case.case_id) / "runtime"
        binding_path = root / "profile_binding.json"
        profile = incident_runtime_profile(case.request)
        if not binding_path.is_file():
            if profile is not None:
                raise ArtifactUnavailableError(
                    "v3 industrial incident case is incomplete: runtime profile "
                    "binding is missing"
                )
            return None, None, None
        try:
            binding = IncidentRuntimeProfileBinding.model_validate_json(
                binding_path.read_bytes()
            )
        except ValueError as error:
            raise ArtifactUnavailableError(
                "incident runtime profile binding failed schema validation"
            ) from error
        if (
            binding.case_id != case.case_id
            or not hmac.compare_digest(binding.case_sha256, case.case_sha256)
            or profile is None
            or binding.profile != profile
            or not hmac.compare_digest(
                binding.profile_sha256,
                profile.profile_sha256(),
            )
        ):
            raise ArtifactUnavailableError(
                "incident runtime profile binding lost immutable case linkage"
            )
        binding_payload = binding.model_dump(mode="json")
        stored_binding_sha = binding_payload.pop("binding_sha256")
        if not hmac.compare_digest(
            stored_binding_sha,
            hashlib.sha256(canonical_json_bytes(binding_payload)).hexdigest(),
        ):
            legacy_binding_payload = dict(binding_payload)
            if (
                binding.governed_memory_planning_input_sha256 is None
                and binding.governed_memory_retrieval_receipt_sha256 is None
            ):
                legacy_binding_payload.pop(
                    "governed_memory_planning_input_sha256",
                    None,
                )
                legacy_binding_payload.pop(
                    "governed_memory_retrieval_receipt_sha256",
                    None,
                )
            if not hmac.compare_digest(
                stored_binding_sha,
                hashlib.sha256(
                    canonical_json_bytes(legacy_binding_payload)
                ).hexdigest(),
            ):
                raise ArtifactUnavailableError(
                    "incident runtime profile binding failed SHA-256 validation"
                )
        planner_receipt = case.model_planner_receipt
        expected_planner_config_sha256 = (
            planner_receipt.config_sha256 if planner_receipt is not None else None
        )
        expected_planner_connection_status = (
            planner_receipt.connection_status if planner_receipt is not None else "OFF"
        )
        if (
            binding.planner_config_sha256 != expected_planner_config_sha256
            or binding.planner_connection_status != expected_planner_connection_status
        ):
            raise ArtifactUnavailableError(
                "incident runtime profile binding lost planner linkage"
            )

        governed_path = root / "governed_context.json"
        site_path = root / "site_pack.json"
        if not governed_path.is_file() and not site_path.is_file():
            if (
                binding.governed_context_receipt_sha256 is not None
                or binding.governed_memory_planning_input_sha256 is not None
                or binding.governed_memory_retrieval_receipt_sha256 is not None
                or binding.selected_memory_count != 0
                or binding.rejected_memory_count != 0
            ):
                raise ArtifactUnavailableError(
                    "runtime binding references absent governed memory artifacts"
                )
            return binding, None, None
        if not governed_path.is_file() or not site_path.is_file():
            raise ArtifactUnavailableError(
                "incident governed context artifacts are incomplete"
            )
        try:
            site_pack = FactorySitePack.model_validate_json(site_path.read_bytes())
            assembled = AssembledIncidentContext.model_validate_json(
                governed_path.read_bytes()
            )
            verify_factory_site_pack(site_pack)
            verify_assembled_incident_context(
                assembled,
                case=case,
                site_pack=site_pack,
            )
        except ValueError as error:
            raise ArtifactUnavailableError(
                "incident governed context failed integrity validation"
            ) from error
        if (
            binding.governed_context_receipt_sha256 != assembled.receipt.receipt_sha256
            or binding.governed_memory_planning_input_sha256
            != (
                assembled.planning_input.input_sha256
                if assembled.planning_input is not None
                else None
            )
            or binding.governed_memory_retrieval_receipt_sha256
            != assembled.retrieval_receipt.receipt_sha256
            or binding.selected_memory_count
            != len(assembled.retrieval_receipt.selected)
            or binding.rejected_memory_count
            != len(assembled.retrieval_receipt.rejected)
        ):
            raise ArtifactUnavailableError(
                "incident governed context lost runtime profile binding"
            )
        return binding, site_pack, assembled

    @staticmethod
    def _validate_incident_command_id(command_id: str) -> None:
        suffix = command_id.removeprefix("incident_command_")
        if (
            not command_id.startswith("incident_command_")
            or len(suffix) != 24
            or any(character not in "0123456789abcdef" for character in suffix)
        ):
            raise NotFoundError("industrial incident command not found")

    def _incident_command_root(self, task: TaskRecord, command_id: str) -> Path:
        self._validate_incident_command_id(command_id)
        return self._incident_task_root(task) / "commands" / command_id

    @staticmethod
    def _read_incident_command_admission(
        path: Path,
    ) -> IncidentCommandAdmission:
        if not path.is_file():
            raise NotFoundError("industrial incident command not found")
        try:
            admission = IncidentCommandAdmission.model_validate_json(
                path.read_text(encoding="utf-8")
            )
            verify_incident_command_admission(admission)
            return admission
        except (OSError, ValueError) as error:
            raise ArtifactUnavailableError(
                "industrial incident command admission failed integrity validation"
            ) from error

    @staticmethod
    def _read_incident_command_terminal(
        path: Path,
        *,
        admission: IncidentCommandAdmission,
    ) -> IncidentCommandTerminal | None:
        if not path.is_file():
            return None
        try:
            terminal = IncidentCommandTerminal.model_validate_json(
                path.read_text(encoding="utf-8")
            )
            verify_incident_command_terminal(terminal, admission=admission)
            return terminal
        except (OSError, ValueError) as error:
            raise ArtifactUnavailableError(
                "industrial incident command terminal failed integrity validation"
            ) from error

    def _admit_incident_command(
        self,
        *,
        task: TaskRecord,
        actor_user_id: str,
        operation: IncidentCommandKind,
        target_case_id: str | None,
        idempotency_key: str,
        request: object,
        expected_case_sha256: str | None,
    ) -> tuple[IncidentCommandAdmission, IncidentCommandTerminal | None, bool]:
        normalized_key = normalize_incident_idempotency_key(idempotency_key)
        command_id = incident_command_id(
            task_id=task.task_id,
            operation=operation,
            target_case_id=target_case_id,
            idempotency_key=normalized_key,
        )
        candidate = build_incident_command_admission(
            command_id=command_id,
            operation=operation,
            task_id=task.task_id,
            target_case_id=target_case_id,
            actor_user_id=actor_user_id,
            idempotency_key=normalized_key,
            request=request,
            expected_case_sha256=expected_case_sha256,
        )
        root = self._incident_command_root(task, command_id)
        admission_path = root / "admission.json"
        data = canonical_json_bytes(candidate)
        admitted_now = _create_once_bytes(admission_path, data)
        if admitted_now:
            admission = candidate
        else:
            admission = self._read_incident_command_admission(admission_path)
            binding_fields = (
                "operation",
                "task_id",
                "target_case_id",
                "actor_user_id",
                "idempotency_key_sha256",
                "request_sha256",
                "expected_case_sha256",
            )
            if any(
                getattr(admission, field) != getattr(candidate, field)
                for field in binding_fields
            ):
                raise IncidentIdempotencyConflictError(
                    "incident idempotency key is already bound to another command"
                )
        terminal = self._read_incident_command_terminal(
            root / "terminal.json",
            admission=admission,
        )
        scope_key = (
            f"task:{task.task_id}"
            if target_case_id is None
            else f"case:{target_case_id}"
        )
        try:
            _store_record, store_claimed_now = self.store.claim_incident_command(
                actor_user_id,
                command_id=admission.command_id,
                task_id=task.task_id,
                scope_key=scope_key,
                operation=StoreIncidentCommandOperation(admission.operation.value),
                idempotency_key_sha256=admission.idempotency_key_sha256,
                request_sha256=admission.request_sha256,
                expected_case_sha256=admission.expected_case_sha256,
            )
        except (IncidentCommandBindingConflict, IncidentCommandScopeOccupied) as error:
            # This command never acquired the transactional effect scope, so it is
            # safe to seal a local REJECTED receipt without changing SQLite state.
            if admitted_now and terminal is None:
                rejected = build_incident_command_terminal(
                    admission,
                    status="REJECTED",
                    error_code=error.code,
                    error_message=str(error)[:500],
                )
                _write_once_json(root / "terminal.json", rejected)
            raise

        if terminal is not None:
            self.store.finish_incident_command(
                actor_user_id,
                task.task_id,
                admission.command_id,
                status=StoreIncidentCommandStatus(terminal.status),
                resource_type=terminal.resource_kind,
                resource_id=terminal.resource_id,
                resource_sha256=terminal.resource_sha256,
                error_code=terminal.error_code,
                error_message=terminal.error_message,
            )
            return admission, terminal, False

        if not admitted_now or not store_claimed_now:
            if store_claimed_now and not admitted_now:
                self.store.mark_incident_command_uncertain(
                    actor_user_id,
                    task.task_id,
                    admission.command_id,
                    error_code="TERMINAL_RECEIPT_MISSING",
                    error_message=(
                        "an admission existed before the transactional claim; "
                        "automatic replay is prohibited"
                    ),
                )
            raise IncidentCommandUncertainError(command_id)
        return admission, None, True

    @staticmethod
    def _raise_rejected_incident_command(
        terminal: IncidentCommandTerminal,
    ) -> None:
        raise IncidentCommandRejectedError(
            terminal.command_id,
            terminal.error_code or "incident_command_rejected",
            terminal.error_message or "incident command was rejected",
        )

    def _persist_rejected_incident_command(
        self,
        task: TaskRecord,
        admission: IncidentCommandAdmission,
        error: Exception,
    ) -> None:
        error_code = getattr(error, "code", "incident_command_rejected")
        message = str(error).strip() or "incident command was rejected"
        terminal = build_incident_command_terminal(
            admission,
            status="REJECTED",
            error_code=str(error_code)[:120],
            error_message=message[:500],
        )
        self._persist_incident_command_terminal(task, admission, terminal)

    def _mark_incident_command_uncertain(
        self,
        task: TaskRecord,
        admission: IncidentCommandAdmission,
        error: Exception,
    ) -> None:
        """Record unknown effect state without obscuring the original failure."""

        terminal_path = (
            self._incident_command_root(task, admission.command_id) / "terminal.json"
        )
        if terminal_path.is_file():
            # A complete immutable terminal receipt is stronger than a transient
            # SQLite synchronization failure; replay will re-validate it.
            return
        try:
            self.store.mark_incident_command_uncertain(
                admission.actor_user_id,
                task.task_id,
                admission.command_id,
                error_code="COMMAND_EFFECT_OUTCOME_UNKNOWN",
                error_message=(str(error).strip() or type(error).__name__)[:500],
            )
        except ProductStoreError:
            # The admission-without-terminal artifact still fails closed even if
            # the control-plane status update itself is unavailable.
            return

    def _load_completed_incident_case(
        self,
        actor_user_id: str,
        task: TaskRecord,
        terminal: IncidentCommandTerminal,
    ) -> IndustrialIncidentCase:
        if terminal.status == "REJECTED":
            self._raise_rejected_incident_command(terminal)
        if terminal.resource_kind != "incident_case" or not terminal.resource_id:
            raise ArtifactUnavailableError(
                "completed incident command has an invalid case resource binding"
            )
        case = self.get_industrial_incident_case(
            actor_user_id, task.task_id, terminal.resource_id
        )
        if not terminal.resource_sha256 or not hmac.compare_digest(
            terminal.resource_sha256, case.case_sha256
        ):
            raise ArtifactUnavailableError(
                "completed incident command case resource failed SHA-256 binding"
            )
        return case

    def _load_completed_incident_decision(
        self,
        actor_user_id: str,
        task: TaskRecord,
        case_id: str,
        terminal: IncidentCommandTerminal,
    ) -> IndustrialIncidentDecisionReceipt:
        if terminal.status == "REJECTED":
            self._raise_rejected_incident_command(terminal)
        if terminal.resource_kind != "incident_decision" or not terminal.resource_id:
            raise ArtifactUnavailableError(
                "completed incident command has an invalid decision resource binding"
            )
        receipt = next(
            (
                item
                for item in self.list_industrial_incident_decisions(
                    actor_user_id, task.task_id, case_id
                )
                if item.decision_id == terminal.resource_id
            ),
            None,
        )
        if (
            receipt is None
            or not terminal.resource_sha256
            or not hmac.compare_digest(
                terminal.resource_sha256, receipt.decision_sha256
            )
        ):
            raise ArtifactUnavailableError(
                "completed incident command decision resource failed SHA-256 binding"
            )
        return receipt

    def _persist_incident_command_terminal(
        self,
        task: TaskRecord,
        admission: IncidentCommandAdmission,
        terminal: IncidentCommandTerminal,
    ) -> IncidentCommandTerminal:
        verify_incident_command_terminal(terminal, admission=admission)
        root = self._incident_command_root(task, admission.command_id)
        _write_once_json(root / "terminal.json", terminal)
        stored = self._read_incident_command_terminal(
            root / "terminal.json",
            admission=admission,
        )
        if stored is None:
            raise ArtifactUnavailableError(
                "industrial incident command terminal was not persisted"
            )
        self.store.finish_incident_command(
            admission.actor_user_id,
            task.task_id,
            admission.command_id,
            status=StoreIncidentCommandStatus(stored.status),
            resource_type=stored.resource_kind,
            resource_id=stored.resource_id,
            resource_sha256=stored.resource_sha256,
            error_code=stored.error_code,
            error_message=stored.error_message,
        )
        return stored

    def get_incident_command_receipt(
        self,
        actor_user_id: str,
        task_id: str,
        command_id: str,
    ) -> IncidentCommandReceipt:
        task = self.store.get_task(actor_user_id, task_id)
        root = self._incident_command_root(task, command_id)
        admission = self._read_incident_command_admission(root / "admission.json")
        if admission.task_id != task.task_id:
            raise ArtifactUnavailableError(
                "industrial incident command failed task binding"
            )
        terminal = self._read_incident_command_terminal(
            root / "terminal.json",
            admission=admission,
        )
        return build_incident_command_receipt(admission, terminal)

    @staticmethod
    def _read_incident_case(path: Path) -> IndustrialIncidentCase:
        if not path.is_file():
            raise NotFoundError("industrial incident case not found")
        try:
            case = parse_industrial_incident_case_json(path.read_text(encoding="utf-8"))
            verify_industrial_incident_case(case)
            return case
        except (OSError, ValueError) as error:
            raise ArtifactUnavailableError(
                "industrial incident case failed integrity validation"
            ) from error

    def _persist_incident_phase_events(
        self, task: TaskRecord, case: IndustrialIncidentCase
    ) -> list[IncidentPhaseEvent]:
        events = build_incident_phase_events(case)
        root = self._incident_case_root(task, case.case_id) / "phase_events"
        for event in events:
            _write_once_json(
                root / f"{event.sequence:04d}_{event.event_id}.json", event
            )
        return events

    def _persist_incident_control_plane(
        self, task: TaskRecord, case: IndustrialIncidentCase
    ) -> IncidentControlPlaneBundle:
        bundle = build_incident_control_plane(case)
        root = self._incident_case_root(task, case.case_id)
        _write_once_json(root / "control_plane.json", bundle)
        return bundle

    def _incident_lineage_artifacts(
        self,
        task: TaskRecord,
        case: IndustrialIncidentCase,
    ) -> tuple[
        IndustrialIncidentCase | None,
        IndustrialIncidentDecisionReceipt | None,
    ]:
        if case.parent_case_id is None:
            return None, None
        if case.authorizing_decision_id is None:
            raise ArtifactUnavailableError(
                "industrial incident child is missing its authorizing decision"
            )
        parent_root = self._incident_case_root(task, case.parent_case_id)
        parent = self._read_incident_case(parent_root / "case.json")
        decision = self._read_incident_decision(
            parent_root / "decisions" / f"{case.authorizing_decision_id}.json",
            case=parent,
        )
        return parent, decision

    def _persist_governed_audit_envelope(
        self,
        task: TaskRecord,
        case: IndustrialIncidentCase,
        *,
        issuer_actor_id: str,
        phase_events: list[IncidentPhaseEvent],
        control_plane: IncidentControlPlaneBundle,
        parent_case: IndustrialIncidentCase | None,
        authorizing_decision: IndustrialIncidentDecisionReceipt | None,
        runtime_profile_binding: IncidentRuntimeProfileBinding | None,
        site_pack: FactorySitePack | None,
        governed_context: AssembledIncidentContext | None,
    ) -> GovernedAuditEnvelope:
        envelope = build_governed_audit_envelope(
            case,
            phase_events=phase_events,
            issuer_actor_id=issuer_actor_id,
            workspace_id=task.workspace_id,
            project_id=task.project_id,
            control_plane=control_plane,
            parent_case=parent_case,
            authorizing_decision=authorizing_decision,
            runtime_profile_binding=runtime_profile_binding,
            site_pack=site_pack,
            governed_context=governed_context,
        )
        root = self._incident_case_root(task, case.case_id) / "audit"
        _write_once_jcs_json(root / "governed_audit_envelope.json", envelope)
        return envelope

    def _persist_governed_audit_anchor(
        self,
        task: TaskRecord,
        case: IndustrialIncidentCase,
        envelope: GovernedAuditEnvelope,
    ) -> GovernedAuditAnchor:
        anchor = build_governed_audit_anchor(case, envelope)
        _write_once_jcs_json(
            self._incident_audit_anchor_path(task, case.case_id),
            anchor,
        )
        return anchor

    def _read_governed_audit_anchor(
        self,
        task: TaskRecord,
        case: IndustrialIncidentCase,
    ) -> GovernedAuditAnchor:
        path = self._incident_audit_anchor_path(task, case.case_id)
        if not path.is_file():
            raise NotFoundError("industrial incident audit anchor not found")
        try:
            anchor = parse_governed_audit_anchor_json(path.read_bytes())
            verify_governed_audit_anchor(anchor, case=case)
            return anchor
        except (OSError, ValueError) as error:
            raise ArtifactUnavailableError(
                "industrial incident audit anchor failed integrity validation"
            ) from error

    def _read_governed_audit_envelope(
        self,
        task: TaskRecord,
        case: IndustrialIncidentCase,
        *,
        phase_events: list[IncidentPhaseEvent],
        runtime_profile_binding: IncidentRuntimeProfileBinding | None,
        site_pack: FactorySitePack | None,
        governed_context: AssembledIncidentContext | None,
    ) -> GovernedAuditEnvelope:
        case_root = self._incident_case_root(task, case.case_id)
        path = case_root / "audit" / "governed_audit_envelope.json"
        if not path.is_file():
            raise NotFoundError("industrial incident audit envelope not found")
        parent, decision = self._incident_lineage_artifacts(task, case)
        control_plane = self._read_incident_control_plane(
            case_root / "control_plane.json",
            case=case,
        )
        try:
            envelope = parse_governed_audit_envelope_json(path.read_bytes())
            verify_governed_audit_envelope(
                envelope,
                case=case,
                phase_events=phase_events,
                control_plane=control_plane,
                parent_case=parent,
                authorizing_decision=decision,
                runtime_profile_binding=runtime_profile_binding,
                site_pack=site_pack,
                governed_context=governed_context,
                expected_workspace_id=task.workspace_id,
                expected_project_id=task.project_id,
            )
            return envelope
        except (OSError, ValueError) as error:
            raise ArtifactUnavailableError(
                "industrial incident audit envelope failed integrity validation"
            ) from error

    @staticmethod
    def _read_incident_control_plane(
        path: Path,
        *,
        case: IndustrialIncidentCase,
    ) -> IncidentControlPlaneBundle:
        if not path.is_file():
            raise NotFoundError("industrial incident control plane not found")
        try:
            bundle = IncidentControlPlaneBundle.model_validate_json(
                path.read_text(encoding="utf-8")
            )
            verify_incident_control_plane(bundle, case=case)
            return bundle
        except (OSError, ValueError) as error:
            raise ArtifactUnavailableError(
                "industrial incident control plane failed integrity validation"
            ) from error

    def _read_incident_phase_events(
        self, task: TaskRecord, case: IndustrialIncidentCase
    ) -> list[IncidentPhaseEvent]:
        root = self._incident_case_root(task, case.case_id) / "phase_events"
        if not root.is_dir():
            return []
        try:
            events = [
                IncidentPhaseEvent.model_validate_json(path.read_text(encoding="utf-8"))
                for path in sorted(root.glob("*.json"))
                if path.is_file()
            ]
            verify_incident_phase_events(case, events)
            return events
        except (OSError, ValueError) as error:
            raise ArtifactUnavailableError(
                "industrial incident phase events failed integrity validation"
            ) from error

    @staticmethod
    def _read_incident_decision(
        path: Path, *, case: IndustrialIncidentCase
    ) -> IndustrialIncidentDecisionReceipt:
        try:
            receipt = IndustrialIncidentDecisionReceipt.model_validate_json(
                path.read_text(encoding="utf-8")
            )
            verify_industrial_incident_decision_receipt(receipt, case=case)
            return receipt
        except (OSError, ValueError) as error:
            raise ArtifactUnavailableError(
                "industrial incident decision failed integrity validation"
            ) from error

    @staticmethod
    def _read_incident_consumption(
        path: Path,
    ) -> IndustrialIncidentDecisionConsumptionReceipt | None:
        if not path.is_file():
            return None
        try:
            receipt = IndustrialIncidentDecisionConsumptionReceipt.model_validate_json(
                path.read_text(encoding="utf-8")
            )
            verify_incident_decision_consumption_receipt(receipt)
            return receipt
        except (OSError, ValueError) as error:
            raise ArtifactUnavailableError(
                "industrial incident decision consumption failed integrity validation"
            ) from error

    def _industrial_gate_context(
        self,
        actor_user_id: str,
        task: TaskRecord,
        *,
        linked_capa_case_id: str | None = None,
    ) -> IndustrialGateContext:
        if task.execution_status is not TaskExecutionStatus.COMPLETED:
            raise ConflictError("industrial incident requires a completed Gate task")
        if task.evidence_sha256 is None:
            raise ArtifactUnavailableError("completed Gate task has no evidence digest")

        source_kind = task.source_kind.value
        source_profile = self.read_optional_evidence_zip_json(
            actor_user_id, task.task_id, "source_profile.json"
        )
        profile_candidate = (
            source_profile.get("profile_sha256") if source_profile is not None else None
        )
        source_profile_sha256 = (
            profile_candidate
            if isinstance(profile_candidate, str)
            and len(profile_candidate) == 64
            and all(character in "0123456789abcdef" for character in profile_candidate)
            else hashlib.sha256(
                canonical_json_bytes(
                    source_profile
                    or {
                        "task_id": task.task_id,
                        "source_kind": source_kind,
                        "profile": "not_embedded",
                    }
                )
            ).hexdigest()
        )

        if task.source_kind is DataSourceKind.LOCAL_AUTHORIZED_DIRECTORY:
            if task.source_id is None:
                raise ArtifactUnavailableError(
                    "local Gate task lost its source authorization binding"
                )
            try:
                source_receipt = self.store.get_local_source_authorization(
                    actor_user_id, task.source_id
                )
                status_candidate = source_receipt.status.upper()
                source_authorization_status = (
                    status_candidate
                    if status_candidate in {"ACTIVE", "REVOKED", "EXPIRED"}
                    else "UNAVAILABLE"
                )
                source_authorization_event_sha256 = (
                    source_receipt.latest_authorization_event_sha256
                    or hashlib.sha256(
                        canonical_json_bytes(
                            {
                                "source_id": task.source_id,
                                "status": "UNAVAILABLE",
                            }
                        )
                    ).hexdigest()
                )
            except (ConflictError, NotFoundError):
                source_authorization_status = "UNAVAILABLE"
                source_authorization_event_sha256 = hashlib.sha256(
                    canonical_json_bytes(
                        {"source_id": task.source_id, "status": "UNAVAILABLE"}
                    )
                ).hexdigest()
            delivery = self.industrial_delivery_receipt(actor_user_id, task.task_id)
            industrial_delivery_sha256 = hashlib.sha256(
                canonical_json_bytes(delivery)
            ).hexdigest()
            dynamic_response_count = len(delivery.dynamic_responses)
            open_work_order_count = sum(
                item.status not in {"VERIFIED_CLOSED", "CLOSED"}
                for item in delivery.executable_work_orders
            )
            remediation_plan_ids = [item.plan_id for item in delivery.remediation_plans]
            model_call_count = delivery.model_call_count
            risk_cluster_count = len(delivery.risk_clusters)
        else:
            source_authorization_status = (
                "NOT_APPLICABLE"
                if task.source_kind is DataSourceKind.SYNTHETIC_DEMO
                else "UNAVAILABLE"
            )
            source_authorization_event_sha256 = hashlib.sha256(
                canonical_json_bytes(
                    {
                        "task_id": task.task_id,
                        "source_kind": source_kind,
                        "authorization": source_authorization_status,
                    }
                )
            ).hexdigest()
            industrial_delivery_sha256 = hashlib.sha256(
                canonical_json_bytes(
                    {
                        "task_id": task.task_id,
                        "task_evidence_sha256": task.evidence_sha256,
                        "fixture_context_only": True,
                    }
                )
            ).hexdigest()
            dynamic_response_count = 0
            open_work_order_count = 0
            remediation_plan_ids = []
            trace = self.read_trace(actor_user_id, task.task_id)
            raw_model_count = trace.get("model_call_count", 0)
            model_call_count = (
                raw_model_count
                if isinstance(raw_model_count, int) and raw_model_count >= 0
                else 0
            )
            risk_cluster_count = 0

        child_run_status = "NOT_STARTED"
        capa_evidence: IncidentCapaEvidence | None = None
        if linked_capa_case_id is not None:
            if task.source_kind is not DataSourceKind.LOCAL_AUTHORIZED_DIRECTORY:
                raise ConflictError(
                    "exact CAPA evidence requires an authorized local task"
                )
            report = self.get_capa_case(
                actor_user_id, task.task_id, linked_capa_case_id
            )
            recovery_status = (
                report.recovery.status
                if report.recovery is not None
                else "NOT_EXECUTED"
            )
            if recovery_status == "TRANSFERRED_TO_INVESTIGATION":
                child_run_status = "TRANSFERRED_TO_INVESTIGATION"
            elif report.recovery is not None or report.execution is not None:
                child_run_status = "COMPLETED"
            elif report.approval is not None or report.derived_version is not None:
                child_run_status = "RUNNING"
            capa_evidence = IncidentCapaEvidence(
                capa_case_id=report.case_id,
                remediation_plan_id=report.selection.plan.plan_id,
                selection_sha256=report.selection.selection_sha256,
                approval_binding_sha256=(
                    report.approval.binding_sha256
                    if report.approval is not None
                    else None
                ),
                derived_version_receipt_sha256=(
                    report.derived_version.receipt_sha256
                    if report.derived_version is not None
                    else None
                ),
                execution_receipt_sha256=(
                    report.execution.receipt_sha256
                    if report.execution is not None
                    else None
                ),
                recovery_receipt_sha256=(
                    report.recovery.receipt_sha256
                    if report.recovery is not None
                    else None
                ),
                child_task_id=(
                    report.recovery.child_task_id
                    if report.recovery is not None
                    else None
                ),
                child_evidence_sha256=(
                    report.recovery.child_evidence_sha256
                    if report.recovery is not None
                    else None
                ),
                recovery_status=recovery_status,
                recovery_success=(
                    report.recovery.recovery_success
                    if report.recovery is not None
                    else False
                ),
            )

        return IndustrialGateContext(
            task_id=task.task_id,
            gate_final_decision=task.final_decision or "UNKNOWN",
            task_evidence_sha256=task.evidence_sha256,
            industrial_delivery_sha256=industrial_delivery_sha256,
            source_profile_sha256=source_profile_sha256,
            source_authorization_event_sha256=(source_authorization_event_sha256),
            source_kind=source_kind,
            source_authorization_status=source_authorization_status,
            dynamic_response_count=dynamic_response_count,
            open_work_order_count=open_work_order_count,
            remediation_plan_ids=remediation_plan_ids,
            model_call_count=model_call_count,
            risk_cluster_count=risk_cluster_count,
            child_run_status=child_run_status,
            capa_evidence=capa_evidence,
        )

    @reuse_incident_case_verification
    def create_industrial_incident_case(
        self,
        actor_user_id: str,
        task_id: str,
        request: IndustrialIncidentRequest,
        *,
        idempotency_key: str | None = None,
    ) -> IndustrialIncidentCase:
        task = self.store.get_task(actor_user_id, task_id)
        resolved_key = resolve_incident_idempotency_key(idempotency_key, request)
        admission, terminal, _admitted_now = self._admit_incident_command(
            task=task,
            actor_user_id=actor_user_id,
            operation=IncidentCommandKind.CREATE_CASE,
            target_case_id=None,
            idempotency_key=resolved_key,
            request=request,
            expected_case_sha256=None,
        )
        if terminal is not None:
            return self._load_completed_incident_case(actor_user_id, task, terminal)

        try:
            context = self._industrial_gate_context(actor_user_id, task)
            site_pack, governed_memory = self._prepare_incident_governed_memory(
                task,
                request,
                context,
                command_admission=admission,
            )
            model_planner = self._planner_for_incident_request(
                actor_user_id, task, request
            )
            case = build_industrial_incident_case(
                request,
                context,
                model_planner=model_planner,
                governed_memory=governed_memory,
                worker_registry=self.incident_worker_registry,
            )
            assembled_context = self._assemble_incident_runtime_context(
                case,
                site_pack=site_pack,
                planning_input=governed_memory,
            )
        except ValueError as error:
            conflict = ConflictError(str(error))
            self._persist_rejected_incident_command(task, admission, conflict)
            raise conflict from error
        except (ProductServiceError, ConflictError, NotFoundError) as error:
            self._persist_rejected_incident_command(task, admission, error)
            raise

        # From the first immutable business write onward, any exception leaves the
        # admission without a terminal receipt. A later retry is therefore blocked
        # as UNCERTAIN instead of risking a duplicate side effect.
        try:
            root = self._incident_case_root(task, case.case_id)
            _write_once_json(root / "case.json", case)
            runtime_binding = self._persist_incident_runtime_artifacts(
                task,
                case,
                site_pack=site_pack,
                assembled_context=assembled_context,
            )
            phase_events = self._persist_incident_phase_events(task, case)
            control_plane = self._persist_incident_control_plane(task, case)
            envelope = self._persist_governed_audit_envelope(
                task,
                case,
                issuer_actor_id=actor_user_id,
                phase_events=phase_events,
                control_plane=control_plane,
                parent_case=None,
                authorizing_decision=None,
                runtime_profile_binding=runtime_binding,
                site_pack=site_pack,
                governed_context=assembled_context,
            )
            self._persist_governed_audit_anchor(task, case, envelope)
            stored = self.get_industrial_incident_case(
                actor_user_id, task_id, case.case_id
            )
            terminal = build_incident_command_terminal(
                admission,
                status="COMPLETED",
                resource_kind="incident_case",
                resource_id=stored.case_id,
                resource_sha256=stored.case_sha256,
            )
            self._persist_incident_command_terminal(task, admission, terminal)
            return stored
        except Exception as error:
            self._mark_incident_command_uncertain(task, admission, error)
            raise

    @reuse_incident_case_verification
    def get_industrial_incident_case(
        self, actor_user_id: str, task_id: str, case_id: str
    ) -> IndustrialIncidentCase:
        task = self.store.get_task(actor_user_id, task_id)
        case = self._read_incident_case(
            self._incident_case_root(task, case_id) / "case.json"
        )
        if case.task_id != task.task_id:
            raise ArtifactUnavailableError(
                "industrial incident case failed task binding"
            )
        try:
            command_binding = self.store.get_completed_incident_case_binding(
                actor_user_id,
                task_id,
                case_id,
            )
        except ProductStoreError as error:
            raise ArtifactUnavailableError(
                "industrial incident case command binding is unavailable"
            ) from error
        if (
            command_binding is not None
            and command_binding.resource_sha256 is not None
            and not hmac.compare_digest(
                command_binding.resource_sha256,
                case.case_sha256,
            )
        ):
            raise ArtifactUnavailableError(
                "industrial incident case failed immutable command binding"
            )
        schema_requires_anchor = incident_case_requires_governed_audit_envelope(case)
        anchor_path = self._incident_audit_anchor_path(task, case_id)
        anchor: GovernedAuditAnchor | None = None
        if schema_requires_anchor and not anchor_path.is_file():
            raise ArtifactUnavailableError(
                "governed industrial incident audit anchor is required but missing"
            )
        if schema_requires_anchor or anchor_path.is_file():
            try:
                anchor = self._read_governed_audit_anchor(task, case)
            except NotFoundError as error:
                raise ArtifactUnavailableError(
                    "governed industrial incident audit anchor is unavailable"
                ) from error
        runtime_binding, site_pack, governed_context = (
            self._read_incident_runtime_artifacts(task, case)
        )
        phase_root = self._incident_case_root(task, case_id) / "phase_events"
        phase_events: list[IncidentPhaseEvent] = []
        if case.schema_version in PHASE_EVENT_INCIDENT_CASE_SCHEMA_VERSIONS:
            if not phase_root.is_dir():
                raise ArtifactUnavailableError(
                    "versioned industrial incident case is incomplete: "
                    "phase events are missing"
                )
            phase_events = self._read_incident_phase_events(task, case)
        elif phase_root.is_dir():
            phase_events = self._read_incident_phase_events(task, case)
        envelope_path = (
            self._incident_case_root(task, case_id)
            / "audit"
            / "governed_audit_envelope.json"
        )
        envelope_required = schema_requires_anchor or anchor is not None
        if envelope_required and not envelope_path.is_file():
            raise ArtifactUnavailableError(
                "governed industrial incident audit envelope is required but missing"
            )
        if envelope_required or envelope_path.is_file():
            try:
                envelope = self._read_governed_audit_envelope(
                    task,
                    case,
                    phase_events=phase_events,
                    runtime_profile_binding=runtime_binding,
                    site_pack=site_pack,
                    governed_context=governed_context,
                )
            except NotFoundError as error:
                raise ArtifactUnavailableError(
                    "governed industrial incident audit envelope is unavailable"
                ) from error
            if anchor is not None:
                try:
                    verify_governed_audit_anchor(
                        anchor,
                        case=case,
                        envelope=envelope,
                    )
                except ValueError as error:
                    raise ArtifactUnavailableError(
                        "governed industrial incident audit anchor binding failed"
                    ) from error
        return case

    @reuse_incident_case_verification
    def get_industrial_incident_audit_envelope(
        self,
        actor_user_id: str,
        task_id: str,
        case_id: str,
    ) -> GovernedAuditEnvelope:
        task = self.store.get_task(actor_user_id, task_id)
        case = self.get_industrial_incident_case(actor_user_id, task_id, case_id)
        runtime_binding, site_pack, governed_context = (
            self._read_incident_runtime_artifacts(task, case)
        )
        phase_events = self._read_incident_phase_events(task, case)
        try:
            envelope = self._read_governed_audit_envelope(
                task,
                case,
                phase_events=phase_events,
                runtime_profile_binding=runtime_binding,
                site_pack=site_pack,
                governed_context=governed_context,
            )
        except NotFoundError as error:
            raise ArtifactUnavailableError(
                "industrial incident case has no governed audit envelope"
            ) from error
        anchor_path = self._incident_audit_anchor_path(task, case.case_id)
        schema_requires_anchor = incident_case_requires_governed_audit_envelope(case)
        anchor: GovernedAuditAnchor | None = None
        if schema_requires_anchor or anchor_path.is_file():
            try:
                anchor = self._read_governed_audit_anchor(task, case)
            except NotFoundError as error:
                raise ArtifactUnavailableError(
                    "industrial incident case has no governed audit anchor"
                ) from error
        if anchor is not None:
            try:
                verify_governed_audit_anchor(
                    anchor,
                    case=case,
                    envelope=envelope,
                )
            except ValueError as error:
                raise ArtifactUnavailableError(
                    "governed industrial incident audit anchor binding failed"
                ) from error
        return envelope

    @reuse_incident_case_verification
    def get_industrial_incident_runtime_profile_binding(
        self,
        actor_user_id: str,
        task_id: str,
        case_id: str,
    ) -> IncidentRuntimeProfileBinding:
        task = self.store.get_task(actor_user_id, task_id)
        case = self.get_industrial_incident_case(actor_user_id, task_id, case_id)
        binding, _site_pack, _assembled_context = self._read_incident_runtime_artifacts(
            task, case
        )
        if binding is None:
            raise ArtifactUnavailableError(
                "industrial incident case has no runtime profile binding"
            )
        return binding

    @reuse_incident_case_verification
    def get_industrial_incident_governed_context(
        self,
        actor_user_id: str,
        task_id: str,
        case_id: str,
    ) -> AssembledIncidentContext:
        task = self.store.get_task(actor_user_id, task_id)
        case = self.get_industrial_incident_case(actor_user_id, task_id, case_id)
        _binding, _site_pack, assembled_context = self._read_incident_runtime_artifacts(
            task, case
        )
        if assembled_context is None:
            raise ArtifactUnavailableError(
                "industrial incident case has no governed context"
            )
        return assembled_context

    @reuse_incident_case_verification
    def list_industrial_incident_cases(
        self, actor_user_id: str, task_id: str
    ) -> list[IndustrialIncidentCase]:
        task = self.store.get_task(actor_user_id, task_id)
        root = self._incident_task_root(task)
        if not root.is_dir():
            return []
        cases = [
            self.get_industrial_incident_case(actor_user_id, task_id, path.name)
            for path in sorted(root.iterdir())
            if path.is_dir() and path.name.startswith("incident_")
        ]
        return sorted(cases, key=lambda item: (item.case_version, item.case_id))

    def goal3_handoff_receipt(
        self, actor_user_id: str, task_id: str
    ) -> Goal3HandoffReceipt:
        """Project the live Goal -> Goal3 boundary without creating side effects."""

        task = self.store.get_task(actor_user_id, task_id)
        if task.execution_status is TaskExecutionStatus.COMPLETED:
            try:
                self.evidence_path(actor_user_id, task_id)
                evidence_integrity: Literal["VERIFIED", "UNAVAILABLE", "FAILED"] = (
                    "VERIFIED"
                )
            except ArtifactUnavailableError:
                evidence_integrity = (
                    "FAILED" if task.evidence_sha256 is not None else "UNAVAILABLE"
                )
        else:
            evidence_integrity = "UNAVAILABLE"

        incidents = self.list_industrial_incident_cases(actor_user_id, task_id)
        return build_goal3_handoff_receipt(
            task=task,
            task_evidence_integrity=evidence_integrity,
            incidents=incidents,
        )

    @reuse_incident_case_verification
    def list_industrial_incident_phase_events(
        self, actor_user_id: str, task_id: str, case_id: str
    ) -> list[IncidentPhaseEvent]:
        task = self.store.get_task(actor_user_id, task_id)
        case = self.get_industrial_incident_case(actor_user_id, task_id, case_id)
        return self._read_incident_phase_events(task, case)

    @reuse_incident_case_verification
    def get_industrial_incident_control_plane(
        self,
        actor_user_id: str,
        task_id: str,
        case_id: str,
    ) -> IncidentControlPlaneBundle:
        task = self.store.get_task(actor_user_id, task_id)
        case = self.get_industrial_incident_case(actor_user_id, task_id, case_id)
        root = self._incident_case_root(task, case.case_id)
        return self._read_incident_control_plane(
            root / "control_plane.json",
            case=case,
        )

    @reuse_incident_case_verification
    def get_industrial_incident_decision_packet(
        self,
        actor_user_id: str,
        task_id: str,
        case_id: str,
    ) -> IndustrialQualityDecisionPacket:
        """Project one immutable incident into a named-owner delivery contract."""

        task = self.store.get_task(actor_user_id, task_id)
        case = self.get_industrial_incident_case(actor_user_id, task_id, case_id)
        control_plane = self.get_industrial_incident_control_plane(
            actor_user_id,
            task_id,
            case_id,
        )
        _runtime_binding, site_pack, assembled_context = (
            self._read_incident_runtime_artifacts(task, case)
        )
        decisions = self.list_industrial_incident_decisions(
            actor_user_id,
            task_id,
            case_id,
        )
        owner_id = decisions[-1].actor_user_id if decisions else actor_user_id
        return build_industrial_quality_decision_packet(
            case,
            control_plane=control_plane,
            named_quality_owner_id=owner_id,
            named_quality_owner_role="QualityManager",
            site_pack=site_pack,
            context_receipt=(
                assembled_context.receipt if assembled_context is not None else None
            ),
        )

    @reuse_incident_case_verification
    def get_industrial_incident_review_projection(
        self,
        actor_user_id: str,
        task_id: str,
        case_id: str,
    ) -> IncidentReviewProjection:
        """Return a sealed read model over existing Incident lifecycle facts."""

        case = self.get_industrial_incident_case(actor_user_id, task_id, case_id)
        related_cases = self.list_industrial_incident_cases(actor_user_id, task_id)
        decision_scope_case_id = case.parent_case_id or case.case_id
        decisions = self.list_industrial_incident_decisions(
            actor_user_id,
            task_id,
            decision_scope_case_id,
        )
        try:
            return build_incident_review_projection(
                case=case,
                related_cases=related_cases,
                decisions=decisions,
                control_plane=self.get_industrial_incident_control_plane(
                    actor_user_id,
                    task_id,
                    case_id,
                ),
                capa_cases=self.list_capa_cases(actor_user_id, task_id),
                task_lineage=self.task_lineage(actor_user_id, task_id),
            )
        except ValueError as error:
            raise ArtifactUnavailableError(
                "industrial incident review projection failed verified cross-binding"
            ) from error

    @reuse_incident_case_verification
    def get_industrial_incident_decision_packet_exports(
        self,
        actor_user_id: str,
        task_id: str,
        case_id: str,
    ) -> DecisionPacketExports:
        packet = self.get_industrial_incident_decision_packet(
            actor_user_id,
            task_id,
            case_id,
        )
        return build_decision_packet_exports(packet)

    @reuse_incident_case_verification
    def list_industrial_incident_decisions(
        self, actor_user_id: str, task_id: str, case_id: str
    ) -> list[IndustrialIncidentDecisionReceipt]:
        task = self.store.get_task(actor_user_id, task_id)
        case = self.get_industrial_incident_case(actor_user_id, task_id, case_id)
        root = self._incident_case_root(task, case_id) / "decisions"
        if not root.is_dir():
            return []
        return [
            self._read_incident_decision(path, case=case)
            for path in sorted(root.glob("incident_decision_*.json"))
            if path.is_file()
        ]

    @reuse_incident_case_verification
    def resume_industrial_incident_case(
        self,
        actor_user_id: str,
        task_id: str,
        case_id: str,
        request: IndustrialIncidentRequest,
        *,
        idempotency_key: str | None = None,
    ) -> IndustrialIncidentCase:
        with self._incident_lock:
            return self._resume_industrial_incident_case(
                actor_user_id,
                task_id,
                case_id,
                request,
                idempotency_key=idempotency_key,
            )

    def _resume_industrial_incident_case(
        self,
        actor_user_id: str,
        task_id: str,
        case_id: str,
        request: IndustrialIncidentRequest,
        *,
        idempotency_key: str | None,
    ) -> IndustrialIncidentCase:
        task = self.store.get_task(actor_user_id, task_id)
        command_parent = self.get_industrial_incident_case(
            actor_user_id, task_id, case_id
        )
        command_expected_case_sha256 = (
            request.expected_parent_case_sha256 or command_parent.case_sha256
        )
        resolved_key = resolve_incident_idempotency_key(idempotency_key, request)
        try:
            admission, terminal, _admitted_now = self._admit_incident_command(
                task=task,
                actor_user_id=actor_user_id,
                operation=IncidentCommandKind.RESUME_CASE,
                target_case_id=case_id,
                idempotency_key=resolved_key,
                request=request,
                expected_case_sha256=command_expected_case_sha256,
            )
        except IncidentCommandScopeOccupied as error:
            consumption = self._read_incident_consumption(
                self._incident_case_root(task, case_id) / "resume_consumption.json"
            )
            if consumption is not None:
                raise ConflictError(
                    "incident parent already advanced to a different immutable child"
                ) from error
            raise
        if terminal is not None:
            return self._load_completed_incident_case(actor_user_id, task, terminal)

        try:
            parent = self.get_industrial_incident_case(actor_user_id, task_id, case_id)
            decisions = self.list_industrial_incident_decisions(
                actor_user_id, task_id, case_id
            )
            if not decisions:
                raise ConflictError(
                    "incident is paused for a named human decision before resume"
                )
            authorizing_decision = next(
                (
                    item
                    for item in decisions
                    if item.decision_id == request.authorizing_decision_id
                ),
                None,
            )
            if authorizing_decision is None:
                raise ConflictError(
                    "requested authorizing incident decision was not found"
                )
            if request.expected_parent_case_sha256 is None or not hmac.compare_digest(
                request.expected_parent_case_sha256, parent.case_sha256
            ):
                raise ConflictError(
                    "incident resume does not bind the current parent case version"
                )
            context = self._industrial_gate_context(
                actor_user_id,
                task,
                linked_capa_case_id=authorizing_decision.linked_capa_case_id,
            )
            site_pack, governed_memory = self._prepare_incident_governed_memory(
                task,
                request,
                context,
                command_admission=admission,
                authorizing_decision=authorizing_decision,
            )
            model_planner = self._planner_for_incident_request(
                actor_user_id, task, request
            )
            child = build_industrial_incident_case(
                request,
                context,
                parent_case=parent,
                authorizing_decision=authorizing_decision,
                model_planner=model_planner,
                governed_memory=governed_memory,
                worker_registry=self.incident_worker_registry,
            )
            assembled_context = self._assemble_incident_runtime_context(
                child,
                site_pack=site_pack,
                planning_input=governed_memory,
            )
            consumption = build_incident_decision_consumption_receipt(
                parent_case=parent,
                decision=authorizing_decision,
                child_case=child,
            )
            interaction = build_incident_interaction_receipt(
                parent_case=parent,
                decision=authorizing_decision,
                child_case=child,
                consumption=consumption,
            )
        except ValueError as error:
            conflict = ConflictError(str(error))
            self._persist_rejected_incident_command(task, admission, conflict)
            raise conflict from error
        except (ProductServiceError, ConflictError, NotFoundError) as error:
            self._persist_rejected_incident_command(task, admission, error)
            raise

        parent_root = self._incident_case_root(task, parent.case_id)
        existing_consumption = self._read_incident_consumption(
            parent_root / "resume_consumption.json"
        )
        if existing_consumption is not None and (
            existing_consumption.consumption_sha256 != consumption.consumption_sha256
        ):
            conflict = ConflictError(
                "incident parent already advanced to a different immutable child"
            )
            self._persist_rejected_incident_command(task, admission, conflict)
            raise conflict

        # Commit the child completely before consuming the authorizing decision.
        # If writing the case or its event chain fails, the immutable admission is
        # left without a terminal result and the parent is not falsely advanced.
        try:
            root = self._incident_case_root(task, child.case_id)
            _write_once_json(root / "case.json", child)
            runtime_binding = self._persist_incident_runtime_artifacts(
                task,
                child,
                site_pack=site_pack,
                assembled_context=assembled_context,
            )
            phase_events = self._persist_incident_phase_events(task, child)
            control_plane = self._persist_incident_control_plane(task, child)
            envelope = self._persist_governed_audit_envelope(
                task,
                child,
                issuer_actor_id=actor_user_id,
                phase_events=phase_events,
                control_plane=control_plane,
                parent_case=parent,
                authorizing_decision=authorizing_decision,
                runtime_profile_binding=runtime_binding,
                site_pack=site_pack,
                governed_context=assembled_context,
            )
            self._persist_governed_audit_anchor(task, child, envelope)
            _write_once_json(root / "interaction" / "receipt.json", interaction)
            stored = self.get_industrial_incident_case(
                actor_user_id, task_id, child.case_id
            )
            _write_once_json(parent_root / "resume_consumption.json", consumption)
            terminal = build_incident_command_terminal(
                admission,
                status="COMPLETED",
                resource_kind="incident_case",
                resource_id=stored.case_id,
                resource_sha256=stored.case_sha256,
            )
            self._persist_incident_command_terminal(task, admission, terminal)
            return stored
        except Exception as error:
            self._mark_incident_command_uncertain(task, admission, error)
            raise

    @reuse_incident_case_verification
    def get_industrial_incident_interaction_receipt(
        self,
        actor_user_id: str,
        task_id: str,
        child_case_id: str,
    ) -> IncidentInteractionReceipt:
        """Return one verified pause/decision/resume receipt for a child Case."""

        task = self.store.get_task(actor_user_id, task_id)
        child = self.get_industrial_incident_case(
            actor_user_id,
            task_id,
            child_case_id,
        )
        if child.parent_case_id is None or child.authorizing_decision_id is None:
            raise ArtifactUnavailableError(
                "root industrial incident case has no multi-turn interaction receipt"
            )
        parent = self.get_industrial_incident_case(
            actor_user_id,
            task_id,
            child.parent_case_id,
        )
        decisions = self.list_industrial_incident_decisions(
            actor_user_id,
            task_id,
            parent.case_id,
        )
        decision = next(
            (
                item
                for item in decisions
                if item.decision_id == child.authorizing_decision_id
            ),
            None,
        )
        if decision is None:
            raise ArtifactUnavailableError(
                "industrial incident interaction lost its authorizing decision"
            )
        consumption = self._read_incident_consumption(
            self._incident_case_root(task, parent.case_id) / "resume_consumption.json"
        )
        if consumption is None:
            raise ArtifactUnavailableError(
                "industrial incident interaction lost its decision consumption"
            )
        path = (
            self._incident_case_root(task, child.case_id)
            / "interaction"
            / "receipt.json"
        )
        if not path.is_file():
            raise ArtifactUnavailableError(
                "industrial incident child case has no interaction receipt"
            )
        try:
            receipt = IncidentInteractionReceipt.model_validate_json(path.read_bytes())
            verify_incident_interaction_receipt(
                receipt,
                parent_case=parent,
                decision=decision,
                child_case=child,
                consumption=consumption,
            )
        except ValueError as error:
            raise ArtifactUnavailableError(
                "industrial incident interaction receipt failed semantic verification"
            ) from error
        return receipt

    @reuse_incident_case_verification
    def record_industrial_incident_decision(
        self,
        actor_user_id: str,
        task_id: str,
        case_id: str,
        request: IndustrialIncidentDecisionRequest,
        *,
        idempotency_key: str | None = None,
    ) -> IndustrialIncidentDecisionReceipt:
        with self._incident_lock:
            return self._record_industrial_incident_decision(
                actor_user_id,
                task_id,
                case_id,
                request,
                idempotency_key=idempotency_key,
            )

    def _record_industrial_incident_decision(
        self,
        actor_user_id: str,
        task_id: str,
        case_id: str,
        request: IndustrialIncidentDecisionRequest,
        *,
        idempotency_key: str | None,
    ) -> IndustrialIncidentDecisionReceipt:
        task = self.store.get_task(actor_user_id, task_id)
        resolved_key = resolve_incident_idempotency_key(idempotency_key, request)
        try:
            admission, terminal, _admitted_now = self._admit_incident_command(
                task=task,
                actor_user_id=actor_user_id,
                operation=IncidentCommandKind.RECORD_DECISION,
                target_case_id=case_id,
                idempotency_key=resolved_key,
                request=request,
                expected_case_sha256=request.bound_case_sha256,
            )
        except IncidentCommandScopeOccupied as error:
            if self.list_industrial_incident_decisions(actor_user_id, task_id, case_id):
                raise ConflictError(
                    "incident case already has a different active human decision"
                ) from error
            raise
        if terminal is not None:
            return self._load_completed_incident_decision(
                actor_user_id, task, case_id, terminal
            )

        try:
            case = self.get_industrial_incident_case(actor_user_id, task_id, case_id)
            if not hmac.compare_digest(request.bound_case_sha256, case.case_sha256):
                raise ConflictError("incident decision does not bind the current case")
            existing_decisions = self.list_industrial_incident_decisions(
                actor_user_id, task_id, case_id
            )
            if existing_decisions:
                existing = existing_decisions[0]
                if (
                    existing.actor_user_id == actor_user_id
                    and existing.decision is request.decision
                    and existing.note == request.note
                    and existing.selected_remediation_plan_id
                    == request.selected_remediation_plan_id
                ):
                    replay_terminal = build_incident_command_terminal(
                        admission,
                        status="COMPLETED",
                        resource_kind="incident_decision",
                        resource_id=existing.decision_id,
                        resource_sha256=existing.decision_sha256,
                    )
                    self._persist_incident_command_terminal(
                        task, admission, replay_terminal
                    )
                    return existing
                raise ConflictError(
                    "incident case already has a different active human decision"
                )

            plan = None
            if request.decision is IncidentHumanDecision.SELECT_REMEDIATION_PLAN:
                plan_id = request.selected_remediation_plan_id
                delivery = self.industrial_delivery_receipt(actor_user_id, task_id)
                plan = next(
                    (
                        item
                        for item in delivery.remediation_plans
                        if item.plan_id == plan_id
                    ),
                    None,
                )
                if plan is None or plan.plan_id not in case.linked_remediation_plan_ids:
                    raise ConflictError(
                        "selected remediation plan is not in the incident evidence"
                    )
        except (ProductServiceError, ConflictError, NotFoundError) as error:
            self._persist_rejected_incident_command(task, admission, error)
            raise

        # CAPA selection is an externally visible workflow side effect. From this
        # line forward, failures deliberately leave the command UNCERTAIN.
        try:
            linked_capa_case_id: str | None = None
            if plan is not None:
                capa = self.select_remediation_plan(
                    actor_user_id,
                    task_id,
                    SelectRemediationPlanRequest(
                        plan_id=plan.plan_id,
                        plan_sha256=plan.plan_sha256,
                        note=request.note,
                        idempotency_key=f"incident:{case.case_sha256}",
                    ),
                )
                linked_capa_case_id = capa.case_id

            receipt = build_industrial_incident_decision_receipt(
                case,
                request,
                actor_user_id=actor_user_id,
                decided_at=datetime.now(UTC),
                linked_capa_case_id=linked_capa_case_id,
            )
            root = self._incident_case_root(task, case_id) / "decisions"
            _write_once_json(root / f"{receipt.decision_id}.json", receipt)
            stored = self._read_incident_decision(
                root / f"{receipt.decision_id}.json", case=case
            )
            terminal = build_incident_command_terminal(
                admission,
                status="COMPLETED",
                resource_kind="incident_decision",
                resource_id=stored.decision_id,
                resource_sha256=stored.decision_sha256,
            )
            self._persist_incident_command_terminal(task, admission, terminal)
            return stored
        except ValueError as error:
            wrapped = ArtifactUnavailableError(
                "incident decision could not be sealed after command admission"
            )
            self._mark_incident_command_uncertain(task, admission, wrapped)
            raise wrapped from error
        except Exception as error:
            self._mark_incident_command_uncertain(task, admission, error)
            raise

    @staticmethod
    def _validate_capa_case_id(case_id: str) -> None:
        suffix = case_id.removeprefix("capa_")
        if not case_id.startswith("capa_") or not suffix.isalnum() or len(suffix) != 20:
            raise NotFoundError("CAPA case not found")

    def _capa_case_root(self, task: TaskRecord, case_id: str) -> Path:
        self._validate_capa_case_id(case_id)
        root = (
            self.product_root
            / "capa_cases"
            / task.workspace_id
            / task.project_id
            / task.task_id
            / case_id
        ).resolve(strict=False)
        try:
            root.relative_to((self.product_root / "capa_cases").resolve(strict=False))
        except ValueError as error:
            raise ArtifactUnavailableError(
                "CAPA case path escaped product root"
            ) from error
        return root

    @staticmethod
    def _read_capa_model(path: Path, model_type: Any) -> Any:
        if not path.is_file():
            return None
        try:
            model = model_type.model_validate_json(path.read_text(encoding="utf-8"))
            seal_fields = {
                CapaCaseSelection: "selection_sha256",
                CapaResponsibilityQueue: "queue_sha256",
                CapaApprovalBinding: "binding_sha256",
                CapaExecutionAuthorization: "authorization_sha256",
                DerivedDataVersionReceipt: "receipt_sha256",
                CapaExecutionReceipt: "receipt_sha256",
                CapaRecoveryReceipt: "receipt_sha256",
                CapaOutcomeAssessment: "assessment_sha256",
            }
            verify_sealed_model(model, seal_fields[model_type])
            return model
        except (OSError, ValueError) as error:
            raise ArtifactUnavailableError(
                f"CAPA artifact failed integrity validation: {path.name}"
            ) from error

    def select_remediation_plan(
        self,
        actor_user_id: str,
        parent_task_id: str,
        request: SelectRemediationPlanRequest,
    ) -> CapaCaseReport:
        parent = self.store.get_task(actor_user_id, parent_task_id)
        if parent.execution_status is not TaskExecutionStatus.COMPLETED:
            raise ConflictError("CAPA requires a completed parent Gate task")
        if parent.source_kind is not DataSourceKind.LOCAL_AUTHORIZED_DIRECTORY:
            raise ConflictError(
                "CAPA derived versions require an authorized local source"
            )
        self.evidence_path(actor_user_id, parent_task_id)
        delivery = self.industrial_delivery_receipt(actor_user_id, parent_task_id)
        plan = next(
            (
                item
                for item in delivery.remediation_plans
                if item.plan_id == request.plan_id
                and hmac.compare_digest(item.plan_sha256, request.plan_sha256)
            ),
            None,
        )
        if plan is None:
            raise ConflictError("requested remediation plan is not in parent evidence")
        case_id = (
            "capa_"
            + hashlib.sha256(
                canonical_json_bytes(
                    {
                        "parent_task_id": parent.task_id,
                        "plan_sha256": plan.plan_sha256,
                        "idempotency_key": request.idempotency_key,
                    }
                )
            ).hexdigest()[:20]
            if request.idempotency_key is not None
            else f"capa_{uuid.uuid4().hex[:20]}"
        )
        if request.idempotency_key is not None:
            existing_selection = (
                self._capa_case_root(parent, case_id) / "selection.json"
            )
            if existing_selection.is_file():
                existing = self.get_capa_case(actor_user_id, parent_task_id, case_id)
                if not hmac.compare_digest(
                    existing.selection.plan.plan_sha256, plan.plan_sha256
                ):
                    raise ConflictError(
                        "CAPA idempotency key already binds another plan"
                    )
                return existing
        created_at = _now()
        delivery_sha256 = hashlib.sha256(canonical_json_bytes(delivery)).hexdigest()
        stable = {
            "schema_version": "visiondata-gate.capa-selection.v1",
            "case_id": case_id,
            "parent_task_id": parent.task_id,
            "parent_request_sha256": parent.request_sha256,
            "parent_evidence_sha256": parent.evidence_sha256,
            "industrial_delivery_sha256": delivery_sha256,
            "plan": plan,
            "selected_by": actor_user_id,
            "selection_note": request.note,
            "created_at": created_at,
        }
        selection = seal_model(CapaCaseSelection, stable, "selection_sha256")
        queue = build_responsibility_queue(
            case_id=case_id,
            parent_task_id=parent.task_id,
            work_orders=delivery.executable_work_orders,
            selected_work_order_ids=plan.selected_work_order_ids,
        )
        root = self._capa_case_root(parent, case_id)
        _write_once_json(root / "selection.json", selection)
        _write_once_json(root / "responsibility_queue.initial.json", queue)
        return self.get_capa_case(actor_user_id, parent_task_id, case_id)

    def get_capa_case(
        self, actor_user_id: str, parent_task_id: str, case_id: str
    ) -> CapaCaseReport:
        parent = self.store.get_task(actor_user_id, parent_task_id)
        root = self._capa_case_root(parent, case_id)
        selection = self._read_capa_model(root / "selection.json", CapaCaseSelection)
        initial_queue = self._read_capa_model(
            root / "responsibility_queue.initial.json", CapaResponsibilityQueue
        )
        if selection is None or initial_queue is None:
            raise NotFoundError("CAPA case not found")
        if not (
            selection.case_id == case_id
            and selection.parent_task_id == parent.task_id
            and selection.parent_request_sha256 == parent.request_sha256
            and selection.parent_evidence_sha256 == parent.evidence_sha256
            and selection.plan.task_id == parent.task_id
            and initial_queue.case_id == case_id
            and initial_queue.parent_task_id == parent.task_id
            and initial_queue.phase == "initial"
        ):
            raise ArtifactUnavailableError("CAPA selection binding failed")
        approval = self._read_capa_model(root / "approval.json", CapaApprovalBinding)
        execution_authorization = self._read_capa_model(
            root / "execution_authorization.json", CapaExecutionAuthorization
        )
        derived = self._read_capa_model(
            root / "derived_version.json", DerivedDataVersionReceipt
        )
        execution = self._read_capa_model(root / "execution.json", CapaExecutionReceipt)
        final_queue = self._read_capa_model(
            root / "responsibility_queue.final.json", CapaResponsibilityQueue
        )
        recovery = self._read_capa_model(root / "recovery.json", CapaRecoveryReceipt)
        if approval is not None and not (
            approval.case_id == case_id
            and approval.parent_task_id == parent.task_id
            and approval.parent_request_sha256 == selection.parent_request_sha256
            and approval.parent_evidence_sha256 == selection.parent_evidence_sha256
            and approval.industrial_delivery_sha256
            == selection.industrial_delivery_sha256
            and approval.selection_sha256 == selection.selection_sha256
            and approval.remediation_plan_id == selection.plan.plan_id
            and approval.remediation_plan_sha256 == selection.plan.plan_sha256
            and approval.responsibility_queue_sha256 == initial_queue.queue_sha256
        ):
            raise ArtifactUnavailableError("CAPA approval binding failed")
        if execution_authorization is not None and not (
            approval is not None
            and execution_authorization.case_id == case_id
            and execution_authorization.parent_task_id == parent.task_id
            and execution_authorization.approval_binding_sha256
            == approval.binding_sha256
            and execution_authorization.source_mutation_permitted is False
            and execution_authorization.raw_redistribution_allowed is False
        ):
            raise ArtifactUnavailableError(
                "CAPA execution authorization binding failed"
            )
        if derived is not None and not (
            approval is not None
            and derived.case_id == case_id
            and derived.parent_task_id == parent.task_id
            and derived.parent_source_id == approval.source_id
            and derived.remediation_plan_id == approval.remediation_plan_id
            and derived.remediation_plan_sha256 == approval.remediation_plan_sha256
            and derived.approval_binding_sha256 == approval.binding_sha256
            and derived.original_selection_count <= approval.max_copied_images
            and (
                approval.planned_copy_count is None
                or derived.original_selection_count == approval.planned_copy_count
            )
        ):
            raise ArtifactUnavailableError("CAPA derived-version binding failed")
        if execution is not None and not (
            approval is not None
            and derived is not None
            and execution.case_id == case_id
            and execution.parent_task_id == parent.task_id
            and execution.derived_version_id == derived.version_id
            and execution.remediation_plan_sha256 == approval.remediation_plan_sha256
            and execution.capa_approval_binding_sha256 == approval.binding_sha256
            and execution.parent_evidence_sha256_before
            == selection.parent_evidence_sha256
            and execution.parent_evidence_sha256_after
            == selection.parent_evidence_sha256
            and execution.parent_source_profile_sha256_before
            == execution.parent_source_profile_sha256_after
            and execution.parent_immutable is True
            and (
                (
                    execution.schema_version == "visiondata-gate.capa-execution.v1"
                    and execution_authorization is None
                )
                or (
                    execution.schema_version == "visiondata-gate.capa-execution.v2"
                    and execution_authorization is not None
                    and execution.execution_authorization_sha256
                    == execution_authorization.authorization_sha256
                )
            )
        ):
            raise ArtifactUnavailableError("CAPA execution binding failed")
        execution_child: TaskRecord | None = None
        if execution is not None:
            try:
                execution_child = self.store.get_task(
                    actor_user_id,
                    execution.child_task_id,
                )
                child_lineage = self.task_lineage(
                    actor_user_id,
                    execution.child_task_id,
                )
            except NotFoundError as error:
                raise ArtifactUnavailableError(
                    "CAPA execution child task or lineage is unavailable"
                ) from error
            if not (
                execution_child.execution_status is TaskExecutionStatus.COMPLETED
                and execution_child.evidence_sha256 is not None
                and hmac.compare_digest(
                    execution.child_evidence_sha256,
                    execution_child.evidence_sha256,
                )
                and child_lineage.root_task_id == parent.task_id
                and child_lineage.focus_task_id == execution_child.task_id
                and hmac.compare_digest(
                    execution.child_lineage_report_sha256,
                    child_lineage.report_sha256,
                )
                and any(
                    edge.parent_task_id == parent.task_id
                    and edge.child_task_id == execution_child.task_id
                    for edge in child_lineage.edges
                )
            ):
                raise ArtifactUnavailableError(
                    "CAPA execution child evidence or lineage binding failed"
                )
        if final_queue is not None and not (
            execution is not None
            and final_queue.case_id == case_id
            and final_queue.parent_task_id == parent.task_id
            and final_queue.phase == "final"
        ):
            raise ArtifactUnavailableError("CAPA final-queue binding failed")
        if final_queue is not None:
            initial_items = {item.work_order_id: item for item in initial_queue.items}
            final_items = {item.work_order_id: item for item in final_queue.items}
            if set(initial_items) != set(final_items) or any(
                initial_items[work_order_id].model_dump(
                    mode="json",
                    exclude={"status", "status_reason", "result_refs"},
                )
                != final_items[work_order_id].model_dump(
                    mode="json",
                    exclude={"status", "status_reason", "result_refs"},
                )
                for work_order_id in initial_items
            ):
                raise ArtifactUnavailableError(
                    "CAPA final queue changed responsibility item identity"
                )
        if recovery is not None and not (
            execution is not None
            and execution_child is not None
            and derived is not None
            and final_queue is not None
            and recovery.case_id == case_id
            and recovery.parent_task_id == parent.task_id
            and recovery.child_task_id == execution.child_task_id
            and recovery.parent_evidence_sha256
            == execution.parent_evidence_sha256_after
            and recovery.child_evidence_sha256 == execution.child_evidence_sha256
            and recovery.parent_decision == parent.final_decision
            and recovery.child_decision == execution_child.final_decision
            and recovery.derived_version_receipt_sha256 == derived.receipt_sha256
            and recovery.responsibility_queue_sha256 == final_queue.queue_sha256
            and recovery.selected_work_order_count
            == sum(item.selected for item in final_queue.items)
            and recovery.verified_closed_work_order_count
            == sum(
                item.selected and item.status is ResponsibilityStatus.VERIFIED_CLOSED
                for item in final_queue.items
            )
            and recovery.remaining_work_order_count == final_queue.open_count
        ):
            raise ArtifactUnavailableError("CAPA recovery binding failed")
        if recovery is not None:
            status = CapaStatus(recovery.status)
        elif execution is not None:
            status = CapaStatus.CHILD_RUN_COMPLETED
        elif derived is not None:
            status = CapaStatus.DERIVED_VERSION_READY
        elif approval is not None:
            status = CapaStatus.APPROVED
        else:
            status = CapaStatus.SELECTED
        return CapaCaseReport(
            case_id=case_id,
            parent_task_id=parent.task_id,
            status=status,
            selection=selection,
            approval=approval,
            initial_queue=initial_queue,
            execution_authorization=execution_authorization,
            derived_version=derived,
            execution=execution,
            final_queue=final_queue,
            recovery=recovery,
        )

    def list_capa_cases(
        self, actor_user_id: str, parent_task_id: str
    ) -> list[CapaCaseReport]:
        parent = self.store.get_task(actor_user_id, parent_task_id)
        root = (
            self.product_root
            / "capa_cases"
            / parent.workspace_id
            / parent.project_id
            / parent.task_id
        )
        if not root.is_dir():
            return []
        reports = [
            self.get_capa_case(actor_user_id, parent_task_id, path.name)
            for path in sorted(root.iterdir())
            if path.is_dir() and path.name.startswith("capa_")
        ]
        return reports

    def capa_causal_replay(
        self, actor_user_id: str, parent_task_id: str, case_id: str
    ) -> CausalReplayReport:
        """Project verified parent/CAPA/child evidence into a read-only T0-T4 view."""

        parent = self.store.get_task(actor_user_id, parent_task_id)
        report = self.get_capa_case(actor_user_id, parent_task_id, case_id)

        def verify_archive_members(
            task: TaskRecord, required_paths: tuple[str, ...]
        ) -> None:
            archive_path = self.evidence_path(actor_user_id, task.task_id)
            try:
                audit = audit_submission_zip(
                    archive_path,
                    required_paths=required_paths,
                )
            except (OSError, ValueError) as error:
                raise ArtifactUnavailableError(
                    "causal replay evidence archive could not be audited"
                ) from error
            if (
                not audit.ok
                or audit.zip_sha256 is None
                or task.evidence_sha256 is None
                or not hmac.compare_digest(audit.zip_sha256, task.evidence_sha256)
            ):
                raise ArtifactUnavailableError(
                    "causal replay evidence failed ZIP or member integrity validation"
                )

        verify_archive_members(
            parent,
            (
                "initial/gate_result.json",
                "final/gate_result.json",
                "dynamic_leader_plan.json",
            ),
        )
        try:
            parent_initial_gate = GateResult.model_validate(
                self.read_evidence_zip_json(
                    actor_user_id,
                    parent_task_id,
                    "initial/gate_result.json",
                )
            )
            parent_final_gate = GateResult.model_validate(
                self.read_evidence_zip_json(
                    actor_user_id,
                    parent_task_id,
                    "final/gate_result.json",
                )
            )
            dynamic_leader_plan = self.read_evidence_zip_json(
                actor_user_id,
                parent_task_id,
                "dynamic_leader_plan.json",
            )
            if (
                parent.initial_decision != parent_initial_gate.decision.value
                or parent.final_decision != parent_final_gate.decision.value
                or dynamic_leader_plan.get("initial_decision")
                != parent_initial_gate.decision.value
                or dynamic_leader_plan.get("final_decision")
                != parent_final_gate.decision.value
            ):
                raise ValueError("parent replay decision binding failed")

            child: TaskRecord | None = None
            child_final_gate: GateResult | None = None
            if report.recovery is not None:
                try:
                    child = self.store.get_task(
                        actor_user_id,
                        report.recovery.child_task_id,
                    )
                except NotFoundError as error:
                    raise ArtifactUnavailableError(
                        "CAPA replay child task binding is unavailable"
                    ) from error
                if child.execution_status is not TaskExecutionStatus.COMPLETED:
                    raise ValueError("CAPA replay child task is not completed")
                lineage = self.task_lineage(actor_user_id, child.task_id)
                if not any(
                    edge.parent_task_id == parent.task_id
                    and edge.child_task_id == child.task_id
                    for edge in lineage.edges
                ):
                    raise ValueError("CAPA replay child lineage binding failed")
                verify_archive_members(child, ("final/gate_result.json",))
                child_final_gate = GateResult.model_validate(
                    self.read_evidence_zip_json(
                        actor_user_id,
                        child.task_id,
                        "final/gate_result.json",
                    )
                )
                if child.final_decision != child_final_gate.decision.value:
                    raise ValueError("CAPA replay child decision binding failed")

            return build_causal_replay_report(
                parent_task=parent,
                parent_initial_gate=parent_initial_gate,
                parent_final_gate=parent_final_gate,
                dynamic_leader_plan=dynamic_leader_plan,
                capa_report=report,
                child_task=child,
                child_final_gate=child_final_gate,
            )
        except (TypeError, ValueError) as error:
            raise ArtifactUnavailableError(
                "causal replay evidence failed schema or binding validation"
            ) from error

    def capa_outcome_assessment(
        self, actor_user_id: str, parent_task_id: str, case_id: str
    ) -> CapaOutcomeAssessment:
        report = self.get_capa_case(actor_user_id, parent_task_id, case_id)
        delivery = self.industrial_delivery_receipt(actor_user_id, parent_task_id)
        try:
            computed = build_capa_outcome_assessment(report, delivery.remediation_plans)
        except ValueError as exc:
            raise ArtifactUnavailableError(str(exc)) from exc
        parent = self.store.get_task(actor_user_id, parent_task_id)
        path = self._capa_case_root(parent, case_id) / "outcome_assessment.json"
        stored = self._read_capa_model(path, CapaOutcomeAssessment)
        if stored is not None:
            if canonical_json_bytes(stored) != canonical_json_bytes(computed):
                raise ArtifactUnavailableError(
                    "stored CAPA outcome assessment differs from bound evidence"
                )
            return stored
        return computed

    def _incident_binding_for_capa(
        self,
        actor_user_id: str,
        parent_task_id: str,
        capa_case_id: str,
    ) -> tuple[IndustrialIncidentCase, IndustrialIncidentDecisionReceipt]:
        matches: list[
            tuple[IndustrialIncidentCase, IndustrialIncidentDecisionReceipt]
        ] = []
        for incident in self.list_industrial_incident_cases(
            actor_user_id, parent_task_id
        ):
            for decision in self.list_industrial_incident_decisions(
                actor_user_id, parent_task_id, incident.case_id
            ):
                if decision.linked_capa_case_id == capa_case_id:
                    matches.append((incident, decision))
        if len(matches) != 1:
            raise ArtifactUnavailableError(
                "governed outcome requires exactly one Incident decision bound to "
                "the CAPA case"
            )
        return matches[0]

    def get_governed_outcome_envelope(
        self,
        actor_user_id: str,
        parent_task_id: str,
        case_id: str,
    ) -> GovernedOutcomeEnvelope:
        """Return one verified Incident-to-CAPA-to-child reviewer entry."""

        parent = self.store.get_task(actor_user_id, parent_task_id)
        report = self.get_capa_case(actor_user_id, parent_task_id, case_id)
        if report.execution is None or report.recovery is None:
            raise ArtifactUnavailableError(
                "governed outcome requires a completed CAPA child Run"
            )
        assessment = self.capa_outcome_assessment(
            actor_user_id, parent_task_id, case_id
        )
        incident, decision = self._incident_binding_for_capa(
            actor_user_id, parent_task_id, case_id
        )
        incident_envelope = self.get_industrial_incident_audit_envelope(
            actor_user_id, parent_task_id, incident.case_id
        )
        child = self.store.get_task(actor_user_id, report.execution.child_task_id)
        if child.execution_status is not TaskExecutionStatus.COMPLETED:
            raise ArtifactUnavailableError(
                "governed outcome child task is not completed"
            )
        if not parent.evidence_sha256 or not child.evidence_sha256:
            raise ArtifactUnavailableError(
                "governed outcome evidence archive binding is unavailable"
            )
        parent_evidence_sha256 = sha256_file(
            self.evidence_path(actor_user_id, parent_task_id)
        )
        child_evidence_sha256 = sha256_file(
            self.evidence_path(actor_user_id, child.task_id)
        )
        lineage = self.task_lineage(actor_user_id, child.task_id)
        if not (
            lineage.root_task_id == parent.task_id
            and lineage.focus_task_id == child.task_id
            and hmac.compare_digest(
                lineage.report_sha256, report.execution.child_lineage_report_sha256
            )
        ):
            raise ArtifactUnavailableError(
                "governed outcome child lineage binding failed"
            )
        try:
            parent_gate = GateResult.model_validate(
                self.read_evidence_zip_json(
                    actor_user_id, parent_task_id, "gate_result.json"
                )
            )
            child_gate = GateResult.model_validate(
                self.read_evidence_zip_json(
                    actor_user_id, child.task_id, "gate_result.json"
                )
            )
            computed = build_governed_outcome_envelope(
                issuer_actor_id=decision.actor_user_id,
                workspace_id=parent.workspace_id,
                project_id=parent.project_id,
                parent_gate=parent_gate,
                parent_evidence_sha256=parent_evidence_sha256,
                incident_case=incident,
                incident_audit_envelope=incident_envelope,
                incident_decision=decision,
                capa_report=report,
                child_gate=child_gate,
                child_evidence_sha256=child_evidence_sha256,
                outcome_assessment=assessment,
            )
            verify_governed_outcome_envelope(computed)
        except ValueError as error:
            raise ArtifactUnavailableError(
                f"governed outcome source binding failed: {error}"
            ) from error

        path = self._capa_case_root(parent, case_id) / "governed_outcome_envelope.json"
        if path.is_file():
            try:
                stored = parse_governed_outcome_envelope_json(path.read_bytes())
            except (OSError, UnicodeError, ValueError) as error:
                raise ArtifactUnavailableError(
                    "stored governed outcome envelope failed integrity validation"
                ) from error
            if not hmac.compare_digest(
                canonical_jcs_bytes(stored), canonical_jcs_bytes(computed)
            ):
                raise ArtifactUnavailableError(
                    "stored governed outcome envelope differs from bound evidence"
                )
            return stored

        _write_once_jcs_json(path, computed)
        try:
            stored = parse_governed_outcome_envelope_json(path.read_bytes())
        except (OSError, UnicodeError, ValueError) as error:
            raise ArtifactUnavailableError(
                "persisted governed outcome envelope failed integrity validation"
            ) from error
        if not hmac.compare_digest(
            canonical_jcs_bytes(stored), canonical_jcs_bytes(computed)
        ):
            raise ArtifactUnavailableError(
                "persisted governed outcome envelope differs from bound evidence"
            )
        return stored

    def approve_remediation_plan(
        self,
        actor_user_id: str,
        parent_task_id: str,
        case_id: str,
        request: ApproveRemediationPlanRequest,
    ) -> CapaCaseReport:
        report = self.get_capa_case(actor_user_id, parent_task_id, case_id)
        if report.approval is not None:
            raise ConflictError("CAPA plan already has a terminal approval")
        plan = report.selection.plan
        if request.approved_work_order_ids != plan.selected_work_order_ids:
            raise ConflictError(
                "approval must bind the exact ordered work-order set in the selected plan"
            )
        parent = self.store.get_task(actor_user_id, parent_task_id)
        self.evidence_path(actor_user_id, parent_task_id)
        source_status, frozen_profile, current_profile = (
            self._live_source_profile_status(parent)
        )
        if (
            source_status != "MATCHED"
            or frozen_profile is None
            or current_profile is None
            or not hmac.compare_digest(frozen_profile, current_profile)
        ):
            raise ConflictError("parent source changed before CAPA approval")
        delivery = self.industrial_delivery_receipt(actor_user_id, parent_task_id)
        delivery_sha256 = hashlib.sha256(canonical_json_bytes(delivery)).hexdigest()
        if not hmac.compare_digest(
            delivery_sha256, report.selection.industrial_delivery_sha256
        ):
            raise ConflictError("parent industrial delivery changed before approval")
        current_plan = next(
            (
                item
                for item in delivery.remediation_plans
                if item.plan_id == plan.plan_id
                and hmac.compare_digest(item.plan_sha256, plan.plan_sha256)
            ),
            None,
        )
        if current_plan is None or canonical_json_bytes(
            current_plan
        ) != canonical_json_bytes(plan):
            raise ConflictError(
                "selected remediation plan is no longer in parent evidence"
            )
        if parent.source_id is None:
            raise ConflictError("parent source authorization binding is missing")
        source_receipt = self.store.get_local_source_authorization(
            actor_user_id, parent.source_id
        )
        if source_receipt.status != "active":
            raise ConflictError("parent source authorization is no longer active")
        try:
            if (
                source_receipt.adapter_kind
                is LocalSourceAdapterKind.OPERATOR_PROJECT_SNAPSHOT
            ):
                snapshot_receipt = OperatorProjectSnapshotReceipt.model_validate(
                    self.read_evidence_zip_json(
                        actor_user_id,
                        parent_task_id,
                        "operator_project_snapshot_receipt.json",
                    )
                )
                if not hmac.compare_digest(
                    snapshot_receipt.receipt_sha256,
                    source_receipt.source_archive_sha256,
                ):
                    raise ArtifactUnavailableError(
                        "parent Operator snapshot receipt binding changed"
                    )
                planned_copy_count = snapshot_receipt.asset_count
            else:
                gate_receipt = self.read_evidence_zip_json(
                    actor_user_id, parent_task_id, "omni_gate_receipt.json"
                )
                planned_copy_count = int(gate_receipt["selected_image_count"])
        except (ArtifactUnavailableError, KeyError, TypeError, ValueError) as error:
            raise ArtifactUnavailableError(
                "parent Gate selection count is unavailable for CAPA approval"
            ) from error
        if planned_copy_count < 1:
            raise ArtifactUnavailableError(
                "parent Gate selection count is invalid for CAPA approval"
            )
        if planned_copy_count > request.max_copied_images:
            raise ConflictError(
                "approved image copy budget is smaller than the frozen Gate selection"
            )
        approved_at = _now()
        stable = {
            "schema_version": "visiondata-gate.capa-approval-binding.v3",
            "case_id": case_id,
            "parent_task_id": parent.task_id,
            "parent_request_sha256": parent.request_sha256,
            "parent_evidence_sha256": parent.evidence_sha256,
            "industrial_delivery_sha256": delivery_sha256,
            "selection_sha256": report.selection.selection_sha256,
            "remediation_plan_id": plan.plan_id,
            "remediation_plan_sha256": plan.plan_sha256,
            "rule_contract_sha256": task_contract_sha256(parent),
            "source_id": parent.source_id,
            "source_profile_sha256": current_profile,
            "source_authorization_event_sha256": (
                source_receipt.latest_authorization_event_sha256
            ),
            "responsibility_queue_sha256": report.initial_queue.queue_sha256,
            "approved_work_order_ids": request.approved_work_order_ids,
            "approved_by": actor_user_id,
            "approval_note": request.note,
            "operator_attests_derived_processing": True,
            "source_mutation_permitted": False,
            "raw_redistribution_allowed": False,
            "planned_copy_count": planned_copy_count,
            "max_copied_images": request.max_copied_images,
            "approved_at": approved_at,
        }
        approval = seal_model(CapaApprovalBinding, stable, "binding_sha256")
        root = self._capa_case_root(parent, case_id)
        _write_once_json(root / "approval.json", approval)
        return self.get_capa_case(actor_user_id, parent_task_id, case_id)

    def _recover_published_derived_version(
        self,
        *,
        parent: TaskRecord,
        parent_binding: Any,
        case_id: str,
        version_id: str,
        approval: CapaApprovalBinding,
        expected_receipt: DerivedDataVersionReceipt | None,
    ) -> DerivedVersionBuild:
        """Re-verify an atomically published derived version after interruption.

        The derived-version directory contains its own sealed receipt and private
        manifest.  Those artifacts are the recovery source of truth; a case-local
        receipt or source-authorization row is never reconstructed from filenames
        alone.
        """

        version_root = (
            self.product_root
            / "derived_versions"
            / parent.workspace_id
            / parent.project_id
            / case_id
            / version_id
        ).resolve(strict=False)
        derived_root_boundary = (self.product_root / "derived_versions").resolve(
            strict=False
        )
        try:
            version_root.relative_to(derived_root_boundary)
            resolved_version_root = version_root.resolve(strict=True)
            resolved_version_root.relative_to(derived_root_boundary)
        except (OSError, RuntimeError, ValueError) as error:
            raise ArtifactUnavailableError(
                "published CAPA derived version escaped the private product root"
            ) from error
        if not resolved_version_root.is_dir() or resolved_version_root.is_symlink():
            raise ArtifactUnavailableError(
                "published CAPA derived version is unavailable"
            )

        receipt_path = resolved_version_root / "derived_version_receipt.json"
        manifest_path = resolved_version_root / "private_manifest.json"
        try:
            recovered = DerivedDataVersionReceipt.model_validate_json(
                receipt_path.read_bytes()
            )
            verify_sealed_model(recovered, "receipt_sha256")
        except (OSError, UnicodeError, ValueError) as error:
            raise ArtifactUnavailableError(
                "published CAPA derived-version receipt failed integrity validation"
            ) from error
        if expected_receipt is not None and not hmac.compare_digest(
            canonical_json_bytes(recovered), canonical_json_bytes(expected_receipt)
        ):
            raise ArtifactUnavailableError(
                "case and published derived-version receipts disagree"
            )
        if not (
            recovered.case_id == case_id
            and recovered.version_id == version_id
            and recovered.parent_task_id == parent.task_id
            and recovered.parent_source_id == approval.source_id
            and recovered.remediation_plan_id == approval.remediation_plan_id
            and hmac.compare_digest(
                recovered.remediation_plan_sha256,
                approval.remediation_plan_sha256,
            )
            and hmac.compare_digest(
                recovered.approval_binding_sha256,
                approval.binding_sha256,
            )
        ):
            raise ArtifactUnavailableError(
                "published CAPA derived-version binding failed"
            )
        try:
            manifest_sha256 = sha256_file(manifest_path)
        except OSError as error:
            raise ArtifactUnavailableError(
                "published CAPA private manifest is unavailable"
            ) from error
        if not hmac.compare_digest(manifest_sha256, recovered.private_manifest_sha256):
            raise ArtifactUnavailableError(
                "published CAPA private manifest failed integrity validation"
            )

        if (
            parent_binding.receipt.adapter_kind
            is LocalSourceAdapterKind.OPERATOR_PROJECT_SNAPSHOT
        ):
            source_roots = sorted(
                path
                for path in resolved_version_root.iterdir()
                if path.is_dir() and not path.is_symlink()
            )
            if len(source_roots) != 1:
                raise ArtifactUnavailableError(
                    "published Operator derived version has an ambiguous source root"
                )
            derived_root = source_roots[0].resolve(strict=True)
            source_archive_sha256 = parent_binding.receipt.source_archive_sha256
            source_profile = profile_operator_project_snapshot(
                derived_root,
                expected_receipt_sha256=source_archive_sha256,
            )
        else:
            derived_root = (resolved_version_root / "source").resolve(strict=True)
            if not derived_root.is_dir() or derived_root.is_symlink():
                raise ArtifactUnavailableError(
                    "published Omni derived source root is unavailable"
                )
            source_archive_sha256 = recovered.derived_content_sha256
            source_profile = profile_omni_source(
                derived_root,
                source_archive_sha256=source_archive_sha256,
            )
        derived_root.relative_to(resolved_version_root)
        source_profile.pop("profile_sha256", None)
        source_profile.update(
            {
                "source_assets_copied_into_product": True,
                "derived_version_id": version_id,
                "derived_from_source_id": approval.source_id,
                "derived_manifest_sha256": recovered.private_manifest_sha256,
            }
        )
        source_profile["profile_sha256"] = hashlib.sha256(
            canonical_json_bytes(source_profile)
        ).hexdigest()
        normalized_path = str(derived_root).casefold().replace("\\", "/")
        root_path_sha256 = hashlib.sha256(normalized_path.encode("utf-8")).hexdigest()
        if not (
            hmac.compare_digest(root_path_sha256, recovered.root_path_sha256)
            and hmac.compare_digest(
                str(source_profile["profile_sha256"]),
                recovered.derived_source_profile_sha256,
            )
        ):
            raise ArtifactUnavailableError(
                "published CAPA derived source profile failed integrity validation"
            )
        return DerivedVersionBuild(
            receipt=recovered,
            derived_root=derived_root,
            source_profile=source_profile,
        )

    def execute_remediation_plan(
        self,
        actor_user_id: str,
        parent_task_id: str,
        case_id: str,
        request: ExecuteRemediationPlanRequest | None = None,
    ) -> CapaCaseReport:
        report = self.get_capa_case(actor_user_id, parent_task_id, case_id)
        if report.recovery is not None:
            return report
        if report.approval is None:
            raise ConflictError("CAPA execution requires a hash-bound human approval")
        parent = self.store.get_task(actor_user_id, parent_task_id)
        if not parent.source_id or not parent.evidence_sha256:
            raise ConflictError("parent source or evidence binding is unavailable")
        parent_evidence_path = self.evidence_path(actor_user_id, parent_task_id)
        parent_evidence_before = sha256_file(parent_evidence_path)
        parent_binding = self.store.get_local_source_binding_unscoped(parent.source_id)
        if parent_binding.receipt.status != "active":
            raise ConflictError("source authorization invalidated the CAPA approval")
        if (
            report.approval.source_authorization_event_sha256 is None
            or not hmac.compare_digest(
                report.approval.source_authorization_event_sha256,
                parent_binding.receipt.latest_authorization_event_sha256,
            )
        ):
            raise ConflictError(
                "source authorization event invalidated the CAPA approval"
            )
        source_status, frozen_profile, current_profile = (
            self._live_source_profile_status(parent)
        )
        if (
            source_status != "MATCHED"
            or current_profile is None
            or frozen_profile is None
            or not hmac.compare_digest(
                current_profile, report.approval.source_profile_sha256
            )
        ):
            raise ConflictError("source drift invalidated the CAPA approval")
        delivery = self.industrial_delivery_receipt(actor_user_id, parent_task_id)
        delivery_sha256 = hashlib.sha256(canonical_json_bytes(delivery)).hexdigest()
        approval = report.approval
        if not (
            hmac.compare_digest(approval.parent_evidence_sha256, parent_evidence_before)
            and hmac.compare_digest(
                approval.industrial_delivery_sha256, delivery_sha256
            )
            and hmac.compare_digest(
                approval.remediation_plan_sha256, report.selection.plan.plan_sha256
            )
            and hmac.compare_digest(
                approval.rule_contract_sha256, task_contract_sha256(parent)
            )
        ):
            raise ConflictError("CAPA approval binding is stale or inconsistent")
        case_root = self._capa_case_root(parent, case_id)
        execution_authorization = report.execution_authorization
        if request is None and execution_authorization is not None:
            raise ConflictError(
                "CAPA execution has a named authorization and cannot downgrade to a "
                "legacy internal execution"
            )
        if request is not None:
            if not hmac.compare_digest(
                request.expected_approval_binding_sha256, approval.binding_sha256
            ):
                raise ConflictError(
                    "CAPA execution confirmation does not bind the current approval"
                )
            if execution_authorization is None:
                authorization_stable = {
                    "schema_version": (
                        "visiondata-gate.capa-execution-authorization.v1"
                    ),
                    "case_id": case_id,
                    "parent_task_id": parent_task_id,
                    "approval_binding_sha256": approval.binding_sha256,
                    "actor_user_id": actor_user_id,
                    "reviewer_identity": request.reviewer_identity,
                    "execution_note": request.note,
                    "operator_attests_derived_processing": True,
                    "source_mutation_permitted": False,
                    "raw_redistribution_allowed": False,
                    "authorized_at": _now(),
                }
                execution_authorization = seal_model(
                    CapaExecutionAuthorization,
                    authorization_stable,
                    "authorization_sha256",
                )
                _write_once_json(
                    case_root / "execution_authorization.json",
                    execution_authorization,
                )
            elif not (
                execution_authorization.actor_user_id == actor_user_id
                and execution_authorization.reviewer_identity
                == request.reviewer_identity
                and execution_authorization.execution_note == request.note
                and hmac.compare_digest(
                    execution_authorization.approval_binding_sha256,
                    request.expected_approval_binding_sha256,
                )
            ):
                raise ConflictError(
                    "CAPA execution already has a different immutable authorization"
                )
        capa_invariant_receipt = build_runtime_invariant_receipt(
            RuntimeInvariantContext(
                action=RuntimeAction.EXECUTE_CAPA,
                actor_kind=RuntimeActorKind.HUMAN,
                input_sha256=(
                    execution_authorization.authorization_sha256
                    if execution_authorization is not None
                    else approval.binding_sha256
                ),
                named_human_approver=(
                    execution_authorization.actor_user_id
                    if execution_authorization is not None
                    else approval.approved_by
                ),
                machine_write_permitted=False,
                production_release_allowed=False,
            )
        )
        if not capa_invariant_receipt.allowed:
            raise ConflictError("runtime invariants blocked CAPA execution")
        _write_once_jcs_json(
            case_root / "runtime_invariant.execute_capa.json",
            capa_invariant_receipt,
        )
        parent_source_root = self._execution_source_root(parent_binding)
        version_id = (
            "drv_"
            + hashlib.sha256(
                canonical_json_bytes(
                    {
                        "case_id": case_id,
                        "plan_sha256": report.selection.plan.plan_sha256,
                        "source_profile_sha256": current_profile,
                    }
                )
            ).hexdigest()[:20]
        )
        derived_version_root = (
            self.product_root
            / "derived_versions"
            / parent.workspace_id
            / parent.project_id
            / case_id
            / version_id
        )
        if derived_version_root.exists() or report.derived_version is not None:
            build = self._recover_published_derived_version(
                parent=parent,
                parent_binding=parent_binding,
                case_id=case_id,
                version_id=version_id,
                approval=approval,
                expected_receipt=report.derived_version,
            )
        else:
            created_at = _now()
            if (
                parent_binding.receipt.adapter_kind
                is LocalSourceAdapterKind.OPERATOR_PROJECT_SNAPSHOT
            ):
                build = build_operator_snapshot_derived_version(
                    source_root=parent_source_root,
                    output_version_root=derived_version_root,
                    parent_source_id=parent.source_id,
                    parent_source_archive_sha256=(
                        parent_binding.receipt.source_archive_sha256
                    ),
                    parent_task_id=parent.task_id,
                    case_id=case_id,
                    version_id=version_id,
                    plan=report.selection.plan,
                    approval=approval,
                    work_orders=delivery.executable_work_orders,
                    created_at=created_at,
                )
            else:
                build = build_omni_derived_version(
                    source_root=parent_source_root,
                    output_root=derived_version_root / "source",
                    parent_source_id=parent.source_id,
                    parent_source_archive_sha256=(
                        parent_binding.receipt.source_archive_sha256
                    ),
                    parent_task_id=parent.task_id,
                    case_id=case_id,
                    version_id=version_id,
                    plan=report.selection.plan,
                    approval=approval,
                    work_orders=delivery.executable_work_orders,
                    seed=parent.seed,
                    created_at=created_at,
                )
        _write_once_json(case_root / "derived_version.json", build.receipt)
        derived_source_archive_sha256 = (
            parent_binding.receipt.source_archive_sha256
            if parent_binding.receipt.adapter_kind
            is LocalSourceAdapterKind.OPERATOR_PROJECT_SNAPSHOT
            else build.receipt.derived_content_sha256
        )
        source_request = AuthorizeLocalSourceRequest(
            workspace_id=parent.workspace_id,
            display_name=f"CAPA 派生版本 {version_id}",
            root_path=str(build.derived_root),
            source_archive_sha256=derived_source_archive_sha256,
            adapter_kind=parent_binding.receipt.adapter_kind,
            purpose="仅用于已批准 CAPA 方案的私有同合同 child Run 复验。",
            rights_basis=(
                "继承父来源的本地授权边界；操作者已批准派生处理，禁止原始资产再分发。"
            ),
            residency="product_local_private_derived_version",
            operator_attests_authorized_use=True,
            read_only=True,
            raw_redistribution_allowed=False,
        )
        derived_source = self.store.create_local_source_authorization(
            actor_user_id,
            source_request,
            resolved_root=build.derived_root,
            root_path_sha256=build.receipt.root_path_sha256,
            data_profile=build.source_profile,
        )
        derived_profile_sha256 = derived_source.data_profile.get("profile_sha256")
        if not (
            derived_source.status == "active"
            and derived_source.read_only is True
            and derived_source.raw_redistribution_allowed is False
            and derived_source.derived_version_id == version_id
            and isinstance(derived_profile_sha256, str)
            and hmac.compare_digest(
                derived_profile_sha256,
                build.receipt.derived_source_profile_sha256,
            )
        ):
            raise ConflictError(
                "recovered CAPA derived-source authorization is unavailable or stale"
            )
        recovered_binding = self.store.get_local_source_binding_unscoped(
            derived_source.source_id
        )
        recovered_root = self._execution_source_root(recovered_binding)
        recovered_profile = self._profile_bound_source(
            recovered_binding, recovered_root
        )
        observed_recovered_profile = recovered_profile.get("profile_sha256")
        if not (
            recovered_root == build.derived_root
            and isinstance(observed_recovered_profile, str)
            and hmac.compare_digest(
                observed_recovered_profile,
                build.receipt.derived_source_profile_sha256,
            )
        ):
            raise ArtifactUnavailableError(
                "recovered CAPA derived source failed live profile validation"
            )
        source_receipt_path = (
            self.product_root
            / "source_authorizations"
            / derived_source.source_id
            / "authorization_receipt.json"
        )
        _write_once_json(source_receipt_path, derived_source)
        for event in self.store.list_source_authorization_events(
            actor_user_id, derived_source.source_id
        ):
            self._persist_source_authorization_event(event)

        child_run_invariant_receipt = build_runtime_invariant_receipt(
            RuntimeInvariantContext(
                action=RuntimeAction.EXECUTE_CHILD_RUN,
                actor_kind=RuntimeActorKind.SYSTEM,
                input_sha256=build.receipt.receipt_sha256,
                parent_case_sha256=parent_evidence_before,
                parent_source_readonly=True,
                machine_write_permitted=False,
                production_release_allowed=False,
            )
        )
        if not child_run_invariant_receipt.allowed:
            raise ConflictError("runtime invariants blocked CAPA Child Run")
        _write_once_jcs_json(
            case_root / "runtime_invariant.child_run.json",
            child_run_invariant_receipt,
        )

        if report.execution is not None:
            if report.execution.derived_source_id != derived_source.source_id:
                raise ArtifactUnavailableError(
                    "CAPA execution and recovered derived source disagree"
                )
            child = self.store.get_task(actor_user_id, report.execution.child_task_id)
        else:
            child = None
            for attempt in range(1, 4):
                suffix = "" if attempt == 1 else f"-retry-{attempt:02d}"
                candidate = self.create_reverification_task(
                    actor_user_id,
                    parent_task_id,
                    CreateReverificationRequest(
                        note=(
                            f"CAPA {case_id}; plan {report.selection.plan.plan_id}; "
                            f"derived version {version_id}; approval "
                            f"{approval.binding_sha256}; child attempt {attempt}"
                        ),
                        source_id=derived_source.source_id,
                    ),
                    idempotency_key=f"capa-child-{case_id}{suffix}",
                )
                if candidate.source_id != derived_source.source_id:
                    raise ArtifactUnavailableError(
                        "CAPA child task lost its recovered derived-source binding"
                    )
                if candidate.execution_status in {
                    TaskExecutionStatus.FAILED,
                    TaskExecutionStatus.CANCELLED,
                    TaskExecutionStatus.ARCHIVED,
                }:
                    continue
                if candidate.execution_status in {
                    TaskExecutionStatus.RUNNING,
                    TaskExecutionStatus.VERIFYING,
                }:
                    raise ConflictError(
                        "CAPA child Run outcome is still unknown; inspect the existing "
                        "task before an explicit retry"
                    )
                child = candidate
                break
            if child is None:
                raise ConflictError(
                    "three bounded CAPA child attempts are terminal; create a new "
                    "CAPA case after human investigation"
                )

        approvals = [
            item
            for item in self.list_interventions(actor_user_id, child.task_id)
            if item.action is TaskInterventionAction.APPROVE_PLAN
        ]
        if len(approvals) > 1:
            raise ArtifactUnavailableError(
                "CAPA child task has ambiguous plan approvals"
            )
        if approvals:
            child_approval = approvals[0]
        elif child.execution_status is TaskExecutionStatus.PLANNED:
            child_approval = self.intervene_task(
                actor_user_id,
                child.task_id,
                TaskInterventionRequest(
                    action=TaskInterventionAction.APPROVE_PLAN,
                    note=(
                        f"执行已绑定 CAPA 方案 {approval.remediation_plan_sha256} "
                        "的派生版本复验。"
                    ),
                ),
                start_approved_task=False,
            )
        else:
            raise ArtifactUnavailableError(
                "completed CAPA child task lost its plan approval binding"
            )
        if child_approval.approval_binding is None:
            raise ConflictError("child plan approval binding is missing")

        if child.execution_status is TaskExecutionStatus.PLANNED:
            completed_child = self.run_task_sync(child.task_id)
        else:
            completed_child = child
        if completed_child.execution_status is not TaskExecutionStatus.COMPLETED:
            raise ConflictError("CAPA child Run did not complete successfully")
        child_evidence_path = self.evidence_path(actor_user_id, child.task_id)
        lineage = self.task_lineage(actor_user_id, child.task_id)
        parent_evidence_after = sha256_file(
            self.evidence_path(actor_user_id, parent_task_id)
        )
        source_status_after, _, profile_after = self._live_source_profile_status(parent)
        parent_immutable = (
            source_status_after == "MATCHED"
            and profile_after is not None
            and hmac.compare_digest(current_profile, profile_after)
            and hmac.compare_digest(parent_evidence_before, parent_evidence_after)
        )
        if not parent_immutable:
            raise ConflictError(
                "parent source or evidence changed during CAPA execution"
            )
        if report.execution is None:
            execution_stable = {
                "schema_version": (
                    "visiondata-gate.capa-execution.v2"
                    if execution_authorization is not None
                    else "visiondata-gate.capa-execution.v1"
                ),
                "case_id": case_id,
                "parent_task_id": parent_task_id,
                "child_task_id": completed_child.task_id,
                "derived_version_id": version_id,
                "derived_source_id": derived_source.source_id,
                "remediation_plan_sha256": report.selection.plan.plan_sha256,
                "capa_approval_binding_sha256": approval.binding_sha256,
                "child_plan_approval_binding_sha256": (
                    child_approval.approval_binding.binding_sha256
                ),
                "parent_evidence_sha256_before": parent_evidence_before,
                "parent_evidence_sha256_after": parent_evidence_after,
                "parent_source_profile_sha256_before": current_profile,
                "parent_source_profile_sha256_after": profile_after,
                "parent_immutable": True,
                "child_evidence_sha256": sha256_file(child_evidence_path),
                "child_lineage_report_sha256": lineage.report_sha256,
                "execution_authorization_sha256": None,
                "executed_at": _now(),
            }
            if execution_authorization is not None:
                execution_stable["execution_authorization_sha256"] = (
                    execution_authorization.authorization_sha256
                )
            execution = seal_model(
                CapaExecutionReceipt, execution_stable, "receipt_sha256"
            )
            _write_once_json(case_root / "execution.json", execution)
        else:
            execution = report.execution

        parent_gate = GateResult.model_validate(
            self.read_evidence_zip_json(
                actor_user_id, parent_task_id, "gate_result.json"
            )
        )
        child_gate = GateResult.model_validate(
            self.read_evidence_zip_json(
                actor_user_id, child.task_id, "gate_result.json"
            )
        )
        child_codes = {finding.code for finding in child_gate.findings}
        unresolved_ids = set(build.receipt.unresolved_work_order_ids)
        selected_ids = set(report.selection.plan.selected_work_order_ids)
        status_by_work_order: dict[
            str, tuple[ResponsibilityStatus, str, list[str]]
        ] = {}
        for order in delivery.executable_work_orders:
            if order.work_order_id not in selected_ids:
                continue
            codes = {span.code for span in order.evidence_span}
            if order.work_order_id in unresolved_ids:
                status = (
                    ResponsibilityStatus.AWAITING_HUMAN_INVESTIGATION
                    if order.action == "INVESTIGATE"
                    else ResponsibilityStatus.BLOCKED_NO_REPLACEMENT
                )
                reason = "派生版本无法执行该动作，风险保持打开。"
            elif codes.isdisjoint(child_codes):
                status = ResponsibilityStatus.VERIFIED_CLOSED
                reason = "child Run 未再次发现该工单绑定的 finding code。"
            else:
                status = ResponsibilityStatus.RECHECK_FAILED
                reason = "child Run 仍发现该工单绑定的 finding code。"
            status_by_work_order[order.work_order_id] = (
                status,
                reason,
                [
                    f"child-task:{child.task_id}",
                    f"child-evidence:{completed_child.evidence_sha256}",
                ],
            )
        final_queue = build_responsibility_queue(
            case_id=case_id,
            parent_task_id=parent_task_id,
            work_orders=delivery.executable_work_orders,
            selected_work_order_ids=report.selection.plan.selected_work_order_ids,
            phase="final",
            status_by_work_order=status_by_work_order,
        )
        closed_selected = sum(
            item.selected and item.status is ResponsibilityStatus.VERIFIED_CLOSED
            for item in final_queue.items
        )
        investigation_open = any(
            item.status is ResponsibilityStatus.AWAITING_HUMAN_INVESTIGATION
            for item in final_queue.items
        )
        child_verification = verify_child_run_closure(
            parent_findings=parent_gate.findings,
            child_findings=child_gate.findings,
            parent_contract_id=parent_gate.contract_id,
            child_contract_id=child_gate.contract_id,
            child_decision=child_gate.decision.value,
            parent_evidence_sha256=parent_evidence_after,
            child_evidence_sha256=completed_child.evidence_sha256,
        )
        recovered = (
            child_gate.decision.value == "PASS"
            and final_queue.open_count == 0
            and child_verification.is_zero_regression
        )
        if recovered:
            recovery_status = "RECOVERED_TO_HUMAN_REVIEW"
            required_action = (
                "由具名质量责任人独立复核 child Run 证据后决定是否进入企业放行流程。"
            )
        elif child_gate.decision.value == "DEFER" or investigation_open:
            recovery_status = "TRANSFERRED_TO_INVESTIGATION"
            required_action = "补充根因、反证或授权证据；不得继续自动整改或放行。"
        else:
            recovery_status = "STILL_BLOCKED"
            required_action = "根据失败复验的责任队列选择新方案并创建新的派生版本。"
        parent_codes = {finding.code for finding in parent_gate.findings}
        recovery_stable = {
            "schema_version": "visiondata-gate.capa-recovery.v2",
            "case_id": case_id,
            "parent_task_id": parent_task_id,
            "child_task_id": child.task_id,
            "status": recovery_status,
            "parent_decision": parent_gate.decision.value,
            "child_decision": child_gate.decision.value,
            "parent_finding_count": len(parent_gate.findings),
            "child_finding_count": len(child_gate.findings),
            "parent_finding_codes": sorted(parent_codes),
            "child_finding_codes": sorted(child_codes),
            "resolved_finding_codes": sorted(parent_codes - child_codes),
            "new_finding_codes": sorted(child_codes - parent_codes),
            "child_verification": child_verification,
            "selected_work_order_count": len(selected_ids),
            "verified_closed_work_order_count": closed_selected,
            "remaining_work_order_count": final_queue.open_count,
            "recovery_success": recovered,
            "production_release_allowed": False,
            "required_human_action": required_action,
            "parent_evidence_sha256": parent_evidence_after,
            "child_evidence_sha256": completed_child.evidence_sha256,
            "derived_version_receipt_sha256": build.receipt.receipt_sha256,
            "responsibility_queue_sha256": final_queue.queue_sha256,
            "recovered_at": _now(),
            "claim_boundary": CapaRecoveryReceipt.model_fields[
                "claim_boundary"
            ].default,
        }
        recovery = seal_model(CapaRecoveryReceipt, recovery_stable, "receipt_sha256")
        _write_once_json(case_root / "responsibility_queue.final.json", final_queue)
        _write_once_json(case_root / "recovery.json", recovery)
        completed_report = self.get_capa_case(actor_user_id, parent_task_id, case_id)
        assessment = build_capa_outcome_assessment(
            completed_report, delivery.remediation_plans
        )
        _write_once_json(case_root / "outcome_assessment.json", assessment)
        return completed_report

    def task_release_readiness(
        self, actor_user_id: str, task_id: str
    ) -> TaskReleaseReadinessReport:
        """Revalidate whether a completed run is safe to present for human review.

        The immutable evidence remains unchanged.  This live gate adds the missing
        temporal question: does the currently authorized source still match the input
        identity against which that evidence was produced?
        """

        task = self.store.get_task(actor_user_id, task_id)
        if task.execution_status is not TaskExecutionStatus.COMPLETED:
            raise ArtifactUnavailableError(
                "release readiness requires a completed task"
            )

        evidence_integrity = "VERIFIED"
        delivery: IndustrialDeliveryReceipt | None = None
        try:
            self.evidence_path(actor_user_id, task_id)
            delivery_payload = self.read_evidence_zip_json(
                actor_user_id, task_id, "industrial_delivery_receipt.json"
            )
            delivery = IndustrialDeliveryReceipt.model_validate(delivery_payload)
        except (ArtifactUnavailableError, json.JSONDecodeError, ValueError):
            evidence_integrity = "FAILED"

        source_status, frozen_profile, current_profile = (
            self._live_source_profile_status(task)
        )
        source_freshness = {
            "MATCHED": "CURRENT",
            "CHANGED": "STALE",
            "UNAVAILABLE": "UNAVAILABLE",
            "NOT_APPLICABLE": "NOT_APPLICABLE",
        }[source_status]
        final_decision = task.final_decision or "UNKNOWN"
        open_work_orders = (
            len(delivery.executable_work_orders) if delivery is not None else None
        )

        checks = [
            ReadinessCheck(
                key="evidence_integrity",
                label="证据包完整性",
                status="PASS" if evidence_integrity == "VERIFIED" else "BLOCKED",
                summary=(
                    "证据 ZIP 与任务记录中的 SHA-256 一致，工业回执可解析。"
                    if evidence_integrity == "VERIFIED"
                    else "证据 ZIP 缺失、摘要不一致或工业回执无法解析，禁止依赖该结果。"
                ),
                evidence_ref="VisionDataGate_TaskEvidence.zip",
                evidence_sha256=task.evidence_sha256,
            )
        ]
        if source_freshness == "NOT_APPLICABLE":
            checks.append(
                ReadinessCheck(
                    key="source_freshness",
                    label="输入快照新鲜度",
                    status="NOT_APPLICABLE",
                    summary="合成演示运行不构成真实数据的生产放行依据。",
                    evidence_ref="data-source:synthetic-demo",
                )
            )
        else:
            source_current = source_freshness == "CURRENT"
            checks.append(
                ReadinessCheck(
                    key="source_freshness",
                    label="输入快照新鲜度",
                    status="PASS" if source_current else "BLOCKED",
                    summary=(
                        "当前授权来源仍与运行时冻结画像一致。"
                        if source_current
                        else "来源已变化或当前不可验证；旧裁决不得复用于新数据。"
                    ),
                    evidence_ref="source-profile:live-redacted",
                    evidence_sha256=current_profile,
                )
            )

        gate_passed = final_decision == "PASS"
        checks.append(
            ReadinessCheck(
                key="gate_decision",
                label="门禁裁决",
                status="PASS" if gate_passed else "BLOCKED",
                summary=(
                    "冻结规则裁决为 PASS，可进入独立人工审阅。"
                    if gate_passed
                    else f"冻结规则裁决为 {final_decision}，必须先完成整改与复验。"
                ),
                evidence_ref="industrial_delivery_receipt.json#/final_decision",
            )
        )
        if open_work_orders is None:
            work_order_status = "BLOCKED"
            work_order_summary = "证据回执不可用，无法确认剩余工单数量。"
        elif open_work_orders:
            work_order_status = "BLOCKED"
            work_order_summary = f"仍有 {open_work_orders} 张工单需要责任人处理并复验。"
        else:
            work_order_status = "PASS"
            work_order_summary = "没有未闭环工单；仍需独立人工审核生产边界。"
        checks.extend(
            [
                ReadinessCheck(
                    key="work_order_closure",
                    label="整改工单闭环",
                    status=work_order_status,
                    summary=work_order_summary,
                    evidence_ref="industrial_delivery_receipt.json#/executable_work_orders",
                ),
                ReadinessCheck(
                    key="production_human_approval",
                    label="生产人工审批",
                    status="PENDING",
                    summary="系统没有生产放行权限；具名责任人和企业流程必须独立审批。",
                    evidence_ref="industrial_delivery_receipt.json#/production_approval_status",
                ),
            ]
        )

        if evidence_integrity != "VERIFIED":
            overall_status = "BLOCKED_EVIDENCE_INTEGRITY"
            required_action = "恢复并核验原证据包；不得用无法校验的结果作任何放行判断。"
        elif source_freshness in {"STALE", "UNAVAILABLE"}:
            overall_status = "BLOCKED_SOURCE_STALE"
            required_action = "重新授权当前数据快照并创建新任务；不得沿用旧裁决。"
        elif task.source_kind is DataSourceKind.SYNTHETIC_DEMO:
            overall_status = "DEMO_ONLY"
            required_action = "仅用于演示闭环；真实批次必须单独授权、运行和人工审核。"
        elif not gate_passed or open_work_orders:
            overall_status = "BLOCKED_GATE_DECISION"
            required_action = (
                "按责任队列完成整改，保留修改前后哈希，并按同一合同重新运行。"
            )
        else:
            overall_status = "READY_FOR_HUMAN_REVIEW"
            required_action = "由具名责任人独立复核证据、业务风险与企业安全流程。"

        return build_task_release_readiness_report(
            task_id=task.task_id,
            overall_status=overall_status,
            final_gate_decision=final_decision,
            evidence_sha256=task.evidence_sha256,
            evidence_integrity=evidence_integrity,
            source_freshness=source_freshness,
            frozen_source_profile_sha256=frozen_profile,
            current_source_profile_sha256=current_profile,
            open_work_order_count=open_work_orders,
            checks=checks,
            required_human_action=required_action,
        )

    def list_tasks(
        self,
        actor_user_id: str,
        *,
        workspace_id: str | None = None,
        project_id: str | None = None,
        limit: int = 100,
    ) -> list[TaskRecord]:
        return self.store.list_tasks(
            actor_user_id,
            workspace_id=workspace_id,
            project_id=project_id,
            limit=limit,
        )

    def list_events(self, actor_user_id: str, task_id: str) -> list[TaskEventRecord]:
        return self.store.list_events(actor_user_id, task_id)

    def _artifact_path(
        self,
        actor_user_id: str,
        task_id: str,
        field: str,
        hash_field: str,
    ) -> Path:
        task = self.store.get_task(actor_user_id, task_id)
        if task.execution_status is not TaskExecutionStatus.COMPLETED:
            raise ArtifactUnavailableError("task artifacts are not ready")
        relative = getattr(task, field)
        if not relative:
            raise ArtifactUnavailableError("task artifact is missing")
        candidate = (self.product_root / relative).resolve(strict=False)
        try:
            candidate.relative_to(self._task_root(task))
        except ValueError as exc:
            raise ArtifactUnavailableError(
                "task artifact escaped immutable task root"
            ) from exc
        if not candidate.is_file():
            raise ArtifactUnavailableError("task artifact is not a regular file")
        expected = getattr(task, hash_field)
        if not expected:
            raise ArtifactUnavailableError("task artifact digest is missing")
        observed = sha256_file(candidate)
        if not hmac.compare_digest(observed, expected):
            raise ArtifactUnavailableError("task artifact integrity check failed")
        return candidate

    def trace_path(self, actor_user_id: str, task_id: str) -> Path:
        return self._artifact_path(actor_user_id, task_id, "trace_rel", "trace_sha256")

    def evidence_path(self, actor_user_id: str, task_id: str) -> Path:
        return self._artifact_path(
            actor_user_id, task_id, "evidence_zip_rel", "evidence_sha256"
        )

    def evidence_member_path(
        self, actor_user_id: str, task_id: str, relative_path: str
    ) -> Path:
        """Resolve one evidence member without accepting a client filesystem path."""

        relative = Path(relative_path)
        if (
            relative.is_absolute()
            or not relative.parts
            or any(part in {"", ".", ".."} for part in relative.parts)
        ):
            raise ArtifactUnavailableError("invalid evidence member")
        evidence_root = self.trace_path(actor_user_id, task_id).parent.resolve(
            strict=True
        )
        candidate = (evidence_root / relative).resolve(strict=False)
        try:
            candidate.relative_to(evidence_root)
        except ValueError as exc:
            raise ArtifactUnavailableError(
                "evidence member escaped task evidence"
            ) from exc
        if not candidate.is_file():
            raise ArtifactUnavailableError("evidence member is missing")
        return candidate

    def read_evidence_zip_json(
        self, actor_user_id: str, task_id: str, relative_path: str
    ) -> dict[str, Any]:
        """Read structured evidence only from the SHA-verified immutable ZIP."""

        import zipfile

        normalized = Path(relative_path).as_posix()
        if (
            normalized.startswith("/")
            or normalized in {"", ".", ".."}
            or ".." in Path(normalized).parts
            or not normalized.casefold().endswith(".json")
        ):
            raise ArtifactUnavailableError("invalid evidence ZIP member")
        archive_path = self.evidence_path(actor_user_id, task_id)
        try:
            with zipfile.ZipFile(archive_path) as archive:
                payload = json.loads(archive.read(normalized).decode("utf-8"))
        except (KeyError, UnicodeDecodeError, zipfile.BadZipFile) as exc:
            raise ArtifactUnavailableError(
                "evidence ZIP member is unavailable"
            ) from exc
        if not isinstance(payload, dict):
            raise ArtifactUnavailableError("evidence JSON must be an object")
        return payload

    def read_optional_evidence_zip_json(
        self, actor_user_id: str, task_id: str, relative_path: str
    ) -> dict[str, Any] | None:
        """Read an optional JSON member without hiding corruption as absence."""

        import zipfile

        normalized = Path(relative_path).as_posix()
        if (
            normalized.startswith("/")
            or normalized in {"", ".", ".."}
            or ".." in Path(normalized).parts
            or not normalized.casefold().endswith(".json")
        ):
            raise ArtifactUnavailableError("invalid evidence ZIP member")
        archive_path = self.evidence_path(actor_user_id, task_id)
        try:
            with zipfile.ZipFile(archive_path) as archive:
                if normalized not in archive.namelist():
                    return None
                payload = json.loads(archive.read(normalized).decode("utf-8"))
        except (UnicodeDecodeError, zipfile.BadZipFile, json.JSONDecodeError) as exc:
            raise ArtifactUnavailableError(
                "optional evidence ZIP member is malformed"
            ) from exc
        if not isinstance(payload, dict):
            raise ArtifactUnavailableError("evidence JSON must be an object")
        return payload

    def read_evidence_zip_bytes(
        self, actor_user_id: str, task_id: str, relative_path: str
    ) -> bytes:
        """Read one safe member after the evidence ZIP digest is verified."""

        import zipfile

        normalized = Path(relative_path).as_posix()
        if (
            normalized.startswith("/")
            or normalized in {"", ".", ".."}
            or ".." in Path(normalized).parts
        ):
            raise ArtifactUnavailableError("invalid evidence ZIP member")
        archive_path = self.evidence_path(actor_user_id, task_id)
        try:
            with zipfile.ZipFile(archive_path) as archive:
                return archive.read(normalized)
        except (KeyError, zipfile.BadZipFile) as exc:
            raise ArtifactUnavailableError(
                "evidence ZIP member is unavailable"
            ) from exc

    def read_evidence_json(
        self, actor_user_id: str, task_id: str, relative_path: str
    ) -> dict[str, Any]:
        path = self.evidence_member_path(actor_user_id, task_id, relative_path)
        if path.suffix.casefold() != ".json":
            raise ArtifactUnavailableError("requested evidence member is not JSON")
        payload = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(payload, dict):
            raise ArtifactUnavailableError("evidence JSON must be an object")
        return payload

    def _annotation_context(
        self, actor_user_id: str, task_id: str
    ) -> tuple[TaskRecord, Path, BatchManifest, BatchContract, GateResult]:
        task = self.store.get_task(actor_user_id, task_id)
        if task.execution_status is not TaskExecutionStatus.COMPLETED:
            raise ArtifactUnavailableError(
                "annotation remediation requires a completed gate task"
            )
        # Verify the immutable evidence ZIP before trusting its GateResult.
        gate_result = GateResult.model_validate(
            self.read_evidence_zip_json(
                actor_user_id, task_id, "initial/gate_result.json"
            )
        )
        task_root = self._task_root(task)
        batch_root = (task_root / "dataset" / "batch").resolve(strict=True)
        try:
            batch_root.relative_to(task_root)
        except ValueError as error:
            raise ArtifactUnavailableError(
                "task batch escaped immutable task root"
            ) from error
        manifest_path = batch_root / "batch_manifest.json"
        if not manifest_path.is_file():
            raise ArtifactUnavailableError("task batch manifest is missing")
        manifest = BatchManifest.model_validate_json(
            manifest_path.read_text(encoding="utf-8")
        )
        contract = BatchContract()
        return task, batch_root, manifest, contract, gate_result

    def _roundtrip_root(self, task: TaskRecord, provider: AnnotationProvider) -> Path:
        root = (
            self.product_root
            / "annotation_roundtrips"
            / task.workspace_id
            / task.project_id
            / task.task_id
            / provider.value
        ).resolve(strict=False)
        try:
            root.relative_to(self.product_root)
        except ValueError as error:
            raise ArtifactUnavailableError(
                "annotation roundtrip root escaped product root"
            ) from error
        return root

    def create_annotation_export(
        self,
        actor_user_id: str,
        task_id: str,
        provider: AnnotationProvider,
    ) -> AnnotationExportRecord:
        task, batch_root, manifest, contract, gate_result = self._annotation_context(
            actor_user_id, task_id
        )
        bundle = build_annotation_export(
            task_id=task.task_id,
            batch_root=batch_root,
            manifest=manifest,
            contract=contract,
            gate_result=gate_result,
            provider=provider,
        )
        root = self._roundtrip_root(task, provider)
        export_path = root / "annotation_export.json"
        if export_path.is_file():
            observed = AnnotationExportBundle.model_validate_json(
                export_path.read_text(encoding="utf-8")
            )
            if observed != bundle:
                raise RoundtripValidationError(
                    "existing annotation export does not match current frozen task"
                )
            return AnnotationExportRecord(
                bundle=observed, export_sha256=sha256_file(export_path)
            )
        root.mkdir(parents=True, exist_ok=True)
        return write_annotation_export(export_path, bundle)

    def import_annotation_revisions(
        self,
        actor_user_id: str,
        task_id: str,
        package: AnnotationImportPackage,
    ) -> AnnotationRoundtripReceipt:
        task, batch_root, manifest, contract, _gate_result = self._annotation_context(
            actor_user_id, task_id
        )
        export = self.create_annotation_export(actor_user_id, task_id, package.provider)
        if package.export_id != export.bundle.export_id:
            raise RoundtripValidationError(
                "import export_id does not match the task's frozen export"
            )
        import_sha256 = hashlib.sha256(canonical_json_bytes(package)).hexdigest()
        import_root = (
            self._roundtrip_root(task, package.provider) / "imports" / import_sha256
        )
        receipt_id = f"annrt-{import_sha256[:20]}"
        receipt_path = import_root / f"{receipt_id}.receipt.json"
        if receipt_path.is_file():
            receipt = next(
                (
                    item
                    for item in self.list_annotation_roundtrips(actor_user_id, task_id)
                    if item.receipt_id == receipt_id
                ),
                None,
            )
            if receipt is None:
                raise ArtifactUnavailableError(
                    "annotation receipt could not be reloaded"
                )
            if receipt.import_sha256 != import_sha256:
                raise RoundtripValidationError(
                    "existing annotation receipt failed its import hash binding"
                )
            return receipt
        try:
            return import_revisions_and_recheck(
                export=export,
                package=package,
                batch_root=batch_root,
                manifest=manifest,
                contract=contract,
                scenario_profile=task.scenario_profile,
                output_root=import_root / "rechecked_batch",
            )
        except (ValueError, FileExistsError) as error:
            raise RoundtripValidationError(str(error)) from error

    def list_annotation_roundtrips(
        self, actor_user_id: str, task_id: str
    ) -> list[AnnotationRoundtripReceipt]:
        task = self.store.get_task(actor_user_id, task_id)
        receipts: list[AnnotationRoundtripReceipt] = []
        for provider in AnnotationProvider:
            root = self._roundtrip_root(task, provider) / "imports"
            if not root.is_dir():
                continue
            for path in sorted(root.glob("*/*.receipt.json")):
                receipt = AnnotationRoundtripReceipt.model_validate_json(
                    path.read_text(encoding="utf-8")
                )
                integrity_path = path.with_name(
                    path.name.replace(".receipt.json", ".integrity.json")
                )
                if not integrity_path.is_file():
                    raise ArtifactUnavailableError(
                        "annotation receipt integrity sidecar is missing"
                    )
                integrity = AnnotationReceiptIntegrity.model_validate_json(
                    integrity_path.read_text(encoding="utf-8")
                )
                if (
                    integrity.receipt_id != receipt.receipt_id
                    or sha256_file(path) != integrity.receipt_sha256
                ):
                    raise ArtifactUnavailableError(
                        "annotation receipt integrity check failed"
                    )
                if receipt.task_id != task.task_id:
                    raise ArtifactUnavailableError(
                        "annotation receipt task binding failed"
                    )
                if receipt.provider is not provider:
                    raise ArtifactUnavailableError(
                        "annotation receipt provider binding failed"
                    )
                if path.parent.name != receipt.import_sha256:
                    raise ArtifactUnavailableError(
                        "annotation receipt import hash binding failed"
                    )
                if (
                    receipt.receipt_id != f"annrt-{receipt.import_sha256[:20]}"
                    or path.name != f"{receipt.receipt_id}.receipt.json"
                ):
                    raise ArtifactUnavailableError(
                        "annotation receipt ID binding failed"
                    )
                import_path = path.parent / "annotation_import.json"
                if (
                    not import_path.is_file()
                    or sha256_file(import_path) != receipt.import_sha256
                ):
                    raise ArtifactUnavailableError(
                        "annotation import artifact integrity failed"
                    )
                export_path = (
                    self._roundtrip_root(task, provider) / "annotation_export.json"
                )
                if (
                    not export_path.is_file()
                    or sha256_file(export_path) != receipt.export_sha256
                ):
                    raise ArtifactUnavailableError(
                        "annotation export artifact integrity failed"
                    )
                if receipt.same_contract_recheck_performed:
                    recheck_root = path.parent / "rechecked_batch"
                    manifest_path = recheck_root / "batch_manifest.json"
                    result_path = recheck_root / "recheck_gate_result.json"
                    if (
                        not receipt.recheck_manifest_sha256
                        or not receipt.recheck_gate_result_sha256
                        or not manifest_path.is_file()
                        or not result_path.is_file()
                        or sha256_file(manifest_path) != receipt.recheck_manifest_sha256
                        or sha256_file(result_path)
                        != receipt.recheck_gate_result_sha256
                    ):
                        raise ArtifactUnavailableError(
                            "annotation recheck artifact integrity failed"
                        )
                    recheck_result = GateResult.model_validate_json(
                        result_path.read_text(encoding="utf-8")
                    )
                    if (
                        recheck_result.contract_id != receipt.recheck_contract_id
                        or recheck_result.input_sha256 != receipt.recheck_input_sha256
                        or recheck_result.decision.value != receipt.recheck_decision
                    ):
                        raise ArtifactUnavailableError(
                            "annotation recheck receipt binding failed"
                        )
                receipts.append(receipt)
        receipts.sort(key=lambda item: item.receipt_id)
        return receipts

    def acceptance_scorecard(
        self,
        actor_user_id: str,
        task_id: str,
        *,
        roundtrip_receipt_id: str | None = None,
    ) -> AcceptanceScorecard:
        task = self.store.get_task(actor_user_id, task_id)
        if task.execution_status is not TaskExecutionStatus.COMPLETED:
            raise ArtifactUnavailableError(
                "acceptance scorecard requires a completed task"
            )
        trace = RuntimeTrace.model_validate(
            self.read_evidence_zip_json(
                actor_user_id, task_id, "agent_runtime_trace.json"
            )
        )
        evaluation_payload = self.read_optional_evidence_zip_json(
            actor_user_id, task_id, "initial/evaluation.json"
        )
        grounding_payload = self.read_optional_evidence_zip_json(
            actor_user_id, task_id, "llm_grounding_receipt.json"
        )
        try:
            evaluation = (
                EvaluationResult.model_validate(evaluation_payload)
                if evaluation_payload is not None
                else None
            )
            grounding = (
                LLMGroundingReceipt.model_validate(grounding_payload)
                if grounding_payload is not None
                else None
            )
        except ValueError as error:
            raise ArtifactUnavailableError(
                "acceptance evidence member failed schema validation"
            ) from error
        receipts = self.list_annotation_roundtrips(actor_user_id, task_id)
        roundtrip = None
        if roundtrip_receipt_id is not None:
            if not roundtrip_receipt_id.startswith("annrt-"):
                raise RoundtripValidationError("invalid annotation receipt ID")
            roundtrip = next(
                (item for item in receipts if item.receipt_id == roundtrip_receipt_id),
                None,
            )
            if roundtrip is None:
                raise RoundtripValidationError("annotation receipt was not found")
        elif len(receipts) == 1:
            roundtrip = receipts[0]
        elif receipts:
            raise RoundtripValidationError(
                "multiple annotation receipts exist; specify roundtrip_receipt_id"
            )
        scorecard = build_acceptance_scorecard(
            task_id=task.task_id,
            runtime_trace=trace,
            evaluation=evaluation,
            grounding_receipt=grounding,
            roundtrip_receipt=roundtrip,
            data_source=task.source_kind.value,
        )
        payload_digest = hashlib.sha256(canonical_json_bytes(scorecard)).hexdigest()
        scorecard_path = (
            self.product_root
            / "acceptance_scorecards"
            / task.workspace_id
            / task.project_id
            / task.task_id
            / f"{payload_digest}.json"
        ).resolve(strict=False)
        try:
            scorecard_path.relative_to(self.product_root)
        except ValueError as error:
            raise ArtifactUnavailableError(
                "acceptance scorecard escaped product root"
            ) from error
        if scorecard_path.is_file():
            if sha256_file(scorecard_path) != payload_digest:
                raise ArtifactUnavailableError(
                    "acceptance scorecard integrity check failed"
                )
        else:
            write_canonical_json(scorecard_path, scorecard)
        return scorecard

    def _shadow_evaluation_root(self, task: TaskRecord) -> Path:
        root = (
            self.product_root
            / "shadow_evaluations"
            / task.workspace_id
            / task.project_id
            / task.task_id
        ).resolve(strict=False)
        try:
            root.relative_to(self.product_root)
        except ValueError as error:
            raise ArtifactUnavailableError(
                "shadow evaluation root escaped product root"
            ) from error
        return root

    def create_industrial_shadow_evaluation(
        self,
        actor_user_id: str,
        task_id: str,
        request: CreateIndustrialShadowEvaluationRequest,
    ) -> IndustrialShadowEvaluationReceipt:
        """Persist an evaluation-plane receipt without mutating Agent evidence."""

        task = self.store.get_task(actor_user_id, task_id)
        if task.execution_status is not TaskExecutionStatus.COMPLETED:
            raise ConflictError(
                "industrial shadow evaluation requires a completed immutable task"
            )
        if (
            task.source_kind is not DataSourceKind.LOCAL_AUTHORIZED_DIRECTORY
            or task.source_id is None
        ):
            raise ConflictError(
                "industrial shadow evaluation requires an authorized local source task"
            )
        if not task.evidence_sha256 or not task.final_decision:
            raise ArtifactUnavailableError(
                "completed task lacks immutable evidence or a final Gate decision"
            )
        source = self.get_local_source_authorization(actor_user_id, task.source_id)
        if source.workspace_id != task.workspace_id:
            raise ConflictError("shadow source and task workspace do not match")
        if source.status != "active":
            raise ConflictError(
                "shadow evaluation cannot be registered against an inactive source grant"
            )

        request_sha256 = shadow_evaluation_request_sha256(
            request,
            task_id=task.task_id,
            task_request_sha256=task.request_sha256,
            task_evidence_sha256=task.evidence_sha256,
            source_authorization_event_sha256=(
                source.latest_authorization_event_sha256
            ),
        )
        receipt_id = f"shadow_{request_sha256[:20]}"
        path = self._shadow_evaluation_root(task) / f"{receipt_id}.json"
        if path.is_file():
            try:
                existing = IndustrialShadowEvaluationReceipt.model_validate_json(
                    path.read_text(encoding="utf-8")
                )
                verify_industrial_shadow_evaluation_receipt(existing)
            except (OSError, ValueError) as error:
                raise ArtifactUnavailableError(
                    "stored industrial shadow evaluation failed integrity validation"
                ) from error
            if existing.request_sha256 != request_sha256:
                raise ConflictError("shadow evaluation receipt identity collision")
            return existing

        receipt = build_industrial_shadow_evaluation_receipt(
            request=request,
            workspace_id=task.workspace_id,
            project_id=task.project_id,
            task_id=task.task_id,
            source_id=task.source_id,
            source_authorization_event_sha256=(
                source.latest_authorization_event_sha256
            ),
            task_request_sha256=task.request_sha256,
            task_evidence_sha256=task.evidence_sha256,
            task_final_decision=task.final_decision,
            created_by=actor_user_id,
            created_at=_now(),
        )
        persisted_sha256 = _write_once_json(path, receipt)
        if not hmac.compare_digest(persisted_sha256, sha256_file(path)):
            raise ArtifactUnavailableError(
                "industrial shadow evaluation persistence verification failed"
            )
        return receipt

    def list_industrial_shadow_evaluations(
        self,
        actor_user_id: str,
        task_id: str,
    ) -> list[IndustrialShadowEvaluationReceipt]:
        """List only hash-valid receipts bound to the requested visible task."""

        task = self.store.get_task(actor_user_id, task_id)
        root = self._shadow_evaluation_root(task)
        if not root.is_dir():
            return []
        receipts: list[IndustrialShadowEvaluationReceipt] = []
        for path in sorted(root.glob("shadow_*.json")):
            try:
                receipt = IndustrialShadowEvaluationReceipt.model_validate_json(
                    path.read_text(encoding="utf-8")
                )
                verify_industrial_shadow_evaluation_receipt(receipt)
            except (OSError, ValueError) as error:
                raise ArtifactUnavailableError(
                    "stored industrial shadow evaluation failed integrity validation"
                ) from error
            if not (
                receipt.task_id == task.task_id
                and receipt.workspace_id == task.workspace_id
                and receipt.project_id == task.project_id
                and path.stem == receipt.receipt_id
            ):
                raise ArtifactUnavailableError(
                    "stored industrial shadow evaluation scope binding failed"
                )
            receipts.append(receipt)
        receipts.sort(key=lambda item: (item.created_at, item.receipt_id))
        return receipts

    def create_shadow_evaluation_manifest_v2(
        self,
        actor_user_id: str,
        task_id: str,
        request: CreateShadowEvaluationManifestV2Request,
    ) -> ShadowEvaluationManifestV2:
        """Persist server-derived per-unit metrics outside the Agent evidence plane."""

        task = self.store.get_task(actor_user_id, task_id)
        if task.execution_status is not TaskExecutionStatus.COMPLETED:
            raise ConflictError(
                "shadow v2 evaluation requires a completed immutable task"
            )
        if (
            task.source_kind is not DataSourceKind.LOCAL_AUTHORIZED_DIRECTORY
            or task.source_id is None
        ):
            raise ConflictError(
                "shadow v2 evaluation requires an authorized local source task"
            )
        if not task.evidence_sha256 or not task.final_decision:
            raise ArtifactUnavailableError(
                "completed task lacks immutable evidence or a final Gate decision"
            )
        source = self.get_local_source_authorization(actor_user_id, task.source_id)
        if source.workspace_id != task.workspace_id:
            raise ConflictError("shadow v2 source and task workspace do not match")
        if source.status != "active":
            raise ConflictError(
                "shadow v2 evaluation cannot use an inactive source grant"
            )

        request_sha256 = shadow_evaluation_manifest_v2_request_sha256(
            request,
            workspace_id=task.workspace_id,
            project_id=task.project_id,
            task_id=task.task_id,
            source_id=task.source_id,
            source_authorization_event_sha256=(
                source.latest_authorization_event_sha256
            ),
            task_request_sha256=task.request_sha256,
            task_evidence_sha256=task.evidence_sha256,
            task_final_decision=task.final_decision,
        )
        receipt_id = f"shadowv2_{request_sha256[:20]}"
        path = self._shadow_evaluation_root(task) / f"{receipt_id}.json"
        if path.is_symlink():
            raise ArtifactUnavailableError(
                "stored shadow v2 evaluation cannot be a symlink"
            )
        if path.is_file():
            try:
                existing = ShadowEvaluationManifestV2.model_validate_json(
                    path.read_text(encoding="utf-8")
                )
                verify_shadow_evaluation_manifest_v2(existing)
            except (OSError, ValueError) as error:
                raise ArtifactUnavailableError(
                    "stored shadow v2 evaluation failed integrity validation"
                ) from error
            if existing.request_sha256 != request_sha256:
                raise ConflictError("shadow v2 evaluation receipt identity collision")
            return existing

        receipt = build_shadow_evaluation_manifest_v2(
            request=request,
            workspace_id=task.workspace_id,
            project_id=task.project_id,
            task_id=task.task_id,
            source_id=task.source_id,
            source_authorization_event_sha256=(
                source.latest_authorization_event_sha256
            ),
            task_request_sha256=task.request_sha256,
            task_evidence_sha256=task.evidence_sha256,
            task_final_decision=task.final_decision,
            created_by=actor_user_id,
            created_at=_now(),
        )
        persisted_sha256 = _write_once_json(path, receipt)
        if not hmac.compare_digest(persisted_sha256, sha256_file(path)):
            raise ArtifactUnavailableError(
                "shadow v2 evaluation persistence verification failed"
            )
        return receipt

    def list_shadow_evaluation_manifests_v2(
        self,
        actor_user_id: str,
        task_id: str,
    ) -> list[ShadowEvaluationManifestV2]:
        """List only semantically valid per-unit receipts in the visible task scope."""

        task = self.store.get_task(actor_user_id, task_id)
        root = self._shadow_evaluation_root(task)
        if not root.is_dir():
            return []
        receipts: list[ShadowEvaluationManifestV2] = []
        for path in sorted(root.glob("shadowv2_*.json")):
            if path.is_symlink():
                raise ArtifactUnavailableError(
                    "stored shadow v2 evaluation cannot be a symlink"
                )
            try:
                receipt = ShadowEvaluationManifestV2.model_validate_json(
                    path.read_text(encoding="utf-8")
                )
                verify_shadow_evaluation_manifest_v2(receipt)
            except (OSError, ValueError) as error:
                raise ArtifactUnavailableError(
                    "stored shadow v2 evaluation failed integrity validation"
                ) from error
            if not (
                receipt.task_id == task.task_id
                and receipt.workspace_id == task.workspace_id
                and receipt.project_id == task.project_id
                and path.stem == receipt.receipt_id
            ):
                raise ArtifactUnavailableError(
                    "stored shadow v2 evaluation scope binding failed"
                )
            receipts.append(receipt)
        receipts.sort(key=lambda item: (item.created_at, item.receipt_id))
        return receipts

    def project_governance_effectiveness(
        self,
        actor_user_id: str,
        project_id: str,
    ) -> ProjectGovernanceEffectivenessSummary:
        """Aggregate all visible project receipts with unit-safe denominators."""

        project = self.store.get_project(actor_user_id, project_id)
        project_root = (
            self.product_root
            / "shadow_evaluations"
            / project.workspace_id
            / project.project_id
        ).resolve(strict=False)
        try:
            project_root.relative_to(self.product_root)
        except ValueError as error:
            raise ArtifactUnavailableError(
                "project governance evidence root escaped product root"
            ) from error

        task_ids: set[str] = set()
        if project_root.is_dir():
            receipt_paths = sorted(
                [
                    *project_root.glob("*/shadow_*.json"),
                    *project_root.glob("*/shadowv2_*.json"),
                ]
            )
            for path in receipt_paths:
                if path.is_symlink() or path.parent.is_symlink():
                    raise ArtifactUnavailableError(
                        "project governance evidence cannot contain symlinks"
                    )
                resolved = path.resolve(strict=True)
                try:
                    resolved.relative_to(project_root)
                except ValueError as error:
                    raise ArtifactUnavailableError(
                        "project governance receipt escaped project scope"
                    ) from error
                task_ids.add(path.parent.name)

        receipts: list[ShadowEvaluationReceipt] = []
        for task_id in sorted(task_ids):
            task = self.store.get_task(actor_user_id, task_id)
            if (
                task.workspace_id != project.workspace_id
                or task.project_id != project.project_id
            ):
                raise ArtifactUnavailableError(
                    "project governance receipt task binding failed"
                )
            receipts.extend(
                self.list_industrial_shadow_evaluations(actor_user_id, task_id)
            )
            receipts.extend(
                self.list_shadow_evaluation_manifests_v2(actor_user_id, task_id)
            )
        try:
            summary = build_project_governance_effectiveness_summary(
                workspace_id=project.workspace_id,
                project_id=project.project_id,
                receipts=receipts,
            )
            verify_project_governance_effectiveness_summary(summary)
        except ValueError as error:
            raise ArtifactUnavailableError(
                "project governance effectiveness failed integrity validation"
            ) from error
        return summary

    def read_trace(self, actor_user_id: str, task_id: str) -> dict[str, Any]:
        return json.loads(self.trace_path(actor_user_id, task_id).read_text("utf-8"))


_default_services: dict[Path, ProductService] = {}
_default_lock = threading.Lock()


def _hosted_agentteams_from_explicit_environment() -> HostedAgentTeamsTransport | None:
    mode = os.environ.get("VISIONDATA_AGENTTEAMS_MODE", "off").strip().casefold()
    if mode in {"", "off"}:
        return None
    return hosted_agentteams_from_environment()


def get_product_service(
    product_root: str | Path, *, recover_interrupted: bool = False
) -> ProductService:
    """Return a process-local service without mutating another process's runs.

    Startup recovery is deliberately opt-in.  A Streamlit and API process may
    share the same SQLite database during local evaluation, so assuming that a
    RUNNING row is stale merely because this process started would be unsafe.
    """

    root = Path(product_root).expanduser().resolve()
    with _default_lock:
        service = _default_services.get(root)
        if service is None:
            service = ProductService(
                root,
                recover_interrupted=recover_interrupted,
                incident_model_planner=incident_model_planner_from_environment(),
                omni_rulepack_path=(
                    os.environ.get("VISIONDATA_OMNI_RULEPACK_PATH", "").strip() or None
                ),
                hosted_agentteams=_hosted_agentteams_from_explicit_environment(),
            )
            _default_services[root] = service
    return service


__all__ = [
    "ArtifactUnavailableError",
    "ConflictError",
    "HostedAgentTeamsOperationError",
    "HostedAgentTeamsUnavailableError",
    "IncidentCommandRejectedError",
    "IncidentCommandUncertainError",
    "IncidentIdempotencyConflictError",
    "NotFoundError",
    "ProductService",
    "ProductServiceError",
    "RulePackDriftError",
    "RoundtripValidationError",
    "UnsupportedSourceError",
    "get_product_service",
]
