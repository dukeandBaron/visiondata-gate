from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
WEB_SRC = ROOT / "web" / "src"


def _source(relative_path: str) -> str:
    return (WEB_SRC / relative_path).read_text(encoding="utf-8")


def test_public_facade_is_manifest_bound_and_fail_closed() -> None:
    landing = _source("pages/PublicLandingPage.tsx")
    public_app = _source("public/PublicApp.tsx")
    shell = _source("components/AppShell.tsx")
    main = _source("main.tsx")
    styles = _source("styles/public-facade.css")
    html = (ROOT / "web" / "index.html").read_text(encoding="utf-8")

    assert "usePublicReplayManifest()" in landing
    assert 'state.status === "VERIFIED"' in landing
    assert "FAIL CLOSED" in landing
    assert "NO VERIFIED FACTS · NO PASS" in landing
    assert "production_release_allowed=false" in landing
    assert "LOCAL-FIRST · INDUSTRIAL VISION GOVERNANCE" in landing
    assert "03 / OPERATOR WORKBENCH" in landing
    assert "BACKEND</span><strong>NOT CONNECTED" in landing
    assert "CUSTOMER DATA</span><strong>NOT INCLUDED" in landing
    assert "Evidence review" in landing
    assert "GOAI 2026 · 复赛" not in landing
    assert "REVIEWER PROOF MAP" not in landing
    assert "FROZEN RC3 BASELINE" not in landing
    assert "OFFICIAL SUBMISSION" not in landing
    assert "manifest.manifest_sha256" in landing
    assert "manifest.worker_selection.budget" in landing
    assert "missing_evidence" in landing

    assert '<Route path="/" element={<PublicLandingPage />} />' in public_app
    assert 'to={publicReplayMode ? "/" : "/workspace"}' in shell
    assert 'publicReplayMode && item.path === "/review" ? "验证档案"' in shell
    assert 'publicReplayMode ? "Public Operator"' in shell
    assert 'location.pathname === "/review" ? "当前复核" : "审计复核"' in shell
    assert "document.documentElement.dataset.runtimeMode = publicReplayMode" in main
    assert 'data-runtime-mode="public-replay"' in styles
    assert ".facade-gate-spine::before" in styles

    assert 'property="og:title"' in html
    assert 'property="og:image"' in html
    assert "%BASE_URL%favicon.svg" in html


def test_public_replay_rc5_is_retryable_legible_and_truth_bounded() -> None:
    runtime = _source("publicReplay.ts")
    landing = _source("pages/PublicLandingPage.tsx")
    replay = _source("pages/PublicReplayPage.tsx")
    styles = _source("styles/index.css")
    facade_styles = _source("styles/public-facade.css")

    assert "const [attempt, setAttempt] = useState(0)" in runtime
    assert 'setState({ status: "LOADING" })' in runtime
    assert "}, [attempt])" in runtime
    assert "return { ...state, retry }" in runtime
    assert "onClick={state.retry}" in replay
    assert "onRetry={state.retry}" in landing
    assert "重新加载并核验公开清单" in replay
    assert "重新加载并核验" in landing

    assert "PRIVATE_OFFLINE_VALIDATION" in landing
    assert "PUBLIC_SYNTHETIC_REPLAY" in landing
    assert "NO_FACTORY_TRUTH" in landing
    assert "不声明真实工厂误放行率或生产 PASS" in landing

    assert "SyntheticClosureComparison" in replay
    assert "manifest.triggering_evidence.map" in replay
    assert "POST-REPAIR MEASUREMENTS · NOT PUBLISHED IN THIS MANIFEST" in replay
    assert "TOOL_FAULT_RECEIPT · NOT INCLUDED" in replay
    assert "不宣称工具故障恢复率" in replay
    assert "ReviewBoundaryLedger" in replay
    assert "production_release_allowed=false" in replay

    assert ".public-closure-comparison__track::before" in styles
    assert ".public-replay-failure .action-button" in styles
    assert ".public-replay-page .panel-header p" in styles
    assert ".public-replay-page .public-review-table code" in styles
    assert ".facade-validation-ledger" in facade_styles
    assert ".facade-dossier__retry" in facade_styles


def test_governance_private_industrial_validation_is_live_fail_closed_and_scoped() -> (
    None
):
    governance = _source("pages/GovernancePage.tsx")
    panel = _source("components/PrivateIndustrialValidationPanel.tsx")
    api = _source("data/privateIndustrialValidationApi.ts")
    public_replay = _source("pages/PublicReplayPage.tsx")

    assert "PrivateIndustrialValidationPanel" in governance
    assert 'id="private-industrial-validation"' in panel
    assert "workspaceId={activeWorkspace?.workspace_id}" in governance
    assert "projectId={activeProject?.project_id}" in governance
    assert 'apiConnected={connection.api === "CONNECTED"}' in governance

    assert "/evaluation-evidence/industrial-validation?" in api
    assert "domainJcsSha256" in api
    assert "visiondata-gate.private-industrial-validation.v1\\0" in api
    assert 'domainJcsSha256("industrial-validation-projection", stable)' in api
    assert 'domainJcsSha256(\n        "visa-scenario-groups"' in api
    assert 'response.headers.get("X-Content-SHA256")' in api
    assert 'normalizedEtag(response.headers.get("ETag"))' in api
    assert "INDUSTRIAL_VALIDATION_CONTRACT_DRIFT" in api
    assert "字段集合漂移" in api
    assert '"mismatched_artifacts", "missing_artifacts"' in api
    assert '"transient_recovery_rate", "non_retryable_retry_rate"' in api
    assert (
        '"source_artifact_name", "source_report_file_sha256", "capa_receipt_sha256"'
        in api
    )
    assert '"customer_shadow_execution_receipt_sha256"' in api
    assert "summary.visa_public_proxy === null" in api

    assert "404、503、网络故障或合同漂移" in panel
    assert "重新读取并核验" in panel
    assert "NO FIXTURE FALLBACK · NO EMBEDDED METRICS" in panel
    assert "DATASET_OFFLINE_VALIDATION ≠ FACTORY_SHADOW_METRICS" in panel
    assert "NORMAL_NO_FAULT" in panel
    assert "TRANSIENT_RECOVERABLE_FAULT" in panel
    assert "PERSISTENT_FAULT_SAFETY_COST" in panel
    assert "actual_factory_truth" in panel
    assert "recomputable_now" in panel
    assert "PrivateIndustrialValidationPanel" not in public_replay


def test_canvas_annotation_selection_and_hover_are_bidirectional() -> None:
    page = _source("pages/ImageWorkspacePage.tsx")
    canvas = _source("components/InteractiveImageCanvas.tsx")
    styles = _source("styles/index.css")

    assert "onHighlightedAnnotationChange?.(" in canvas
    assert "annotationAtPoint(annotations, point.normalized)?.annotation_id" in canvas
    assert "onHighlightedAnnotationChange={setHighlightedAnnotationId}" in page
    assert "annotation.annotation_id === highlightedAnnotationId" in page
    assert '"is-highlighted"' in page
    assert ".annotation-ledger button.is-highlighted" in styles

    assert "handleSelectedAnnotationChange" in page
    assert 'setInspectorTab("PROPERTIES")' in page
    assert 'target?.scrollIntoView({ block: "nearest", behavior: "smooth" })' in page
    assert "[inspectorTab, selectedAnnotationId]" in page
    assert "onSelectedAnnotationChange={handleSelectedAnnotationChange}" in page


def test_operator_agent_panel_is_an_auditable_actionable_copilot() -> None:
    page = _source("pages/ImageWorkspacePage.tsx")
    panel = _source("components/OperatorAgentPanel.tsx")
    styles = _source("styles/index.css")

    for view in (
        '"OVERVIEW"',
        '"PLAN"',
        '"TRACE"',
        '"KNOWLEDGE"',
        '"DELIVERY"',
        '"COPILOT"',
    ):
        assert view in panel

    assert "RECORDED EXECUTION PLAN" in panel
    assert "DETERMINISTIC TOOL ROSTER" in panel
    assert "KNOWLEDGE BOUNDARY" in panel
    assert "NEXT CONTROLLED ACTION" in panel
    assert "不显示模型私有思维链" in panel
    assert "run.raw_images_transmitted" in panel
    assert "run.model_call_count" in panel
    assert "traceStale" in panel
    assert "onCreateWorkOrder" in panel
    assert "selectedAnnotationLabel" in panel

    assert "selectedAnnotationLabel={selectedAnnotation?.label}" in page
    assert "openWorkOrderReview(selectedAnnotationId)" in page
    assert 'onOpenEvidence={() => navigate("/evidence")}' in page
    assert 'onOpenTaskWorkbench={() => navigate("/command-center")}' in page
    assert ".agent-panel-nav" in styles
    assert ".agent-action-dock" in styles
    assert ".agent-trace-filters" in styles
    assert 'role="tablist"' in panel
    assert 'role="tab"' in panel
    assert 'role="tabpanel"' in panel
    assert 'event.key === "ArrowRight"' in panel
    assert 'event.key === "ArrowLeft"' in panel
    assert "onActiveViewChange(nextView.key)" in panel
    assert "navigator.clipboard.writeText(JSON.stringify(run, null, 2))" in panel
    assert "复制完整 Trace 回执" in panel
    assert "agent-event__chevron" in panel
    assert ".agent-boundary__title" in styles
    assert ".agent-event[open] .agent-event__chevron" in styles


def test_operator_inspector_is_resizable_persistent_and_keeps_agent_view() -> None:
    page = _source("pages/ImageWorkspacePage.tsx")
    styles = _source("styles/index.css")

    assert (
        'INSPECTOR_WIDTH_STORAGE_KEY = "visiondata-gate.operator-inspector-width"'
        in page
    )
    assert "window.localStorage.getItem(INSPECTOR_WIDTH_STORAGE_KEY)" in page
    assert (
        "window.localStorage.setItem(INSPECTOR_WIDTH_STORAGE_KEY, String(next))" in page
    )
    assert 'role="separator"' in page
    assert 'aria-orientation="vertical"' in page
    assert "onPointerDown={startInspectorResize}" in page
    assert "onKeyDown={resizeInspectorWithKeyboard}" in page
    assert (
        "onDoubleClick={() => persistInspectorWidth(DEFAULT_INSPECTOR_WIDTH)}" in page
    )
    assert '"--operator-inspector-width": inspectorWidth + "px"' in page
    assert "const [agentPanelView, setAgentPanelView]" in page
    assert "activeView={agentPanelView}" in page
    assert "onActiveViewChange={setAgentPanelView}" in page

    assert "var(--operator-inspector-width, 430px)" in styles
    assert ".operator-inspector-resizer" in styles
    assert "html.is-resizing-inspector" in styles
    assert "cursor: col-resize" in styles


def test_dirty_workbook_registers_a_cancellable_product_scope_guard() -> None:
    context = _source("ProductContext.tsx")
    shell = _source("components/AppShell.tsx")
    page = _source("pages/ImageWorkspacePage.tsx")

    assert (
        "registerScopeChangeGuard: (guard: ScopeChangeGuard) => () => void" in context
    )
    assert "scopeChangeGuardsRef.current.add(guard)" in context
    assert '!canChangeScope({ kind: "WORKSPACE", workspaceId })' in context
    assert 'kind: "PROJECT"' in context
    assert "if (selectProject(project.project_id)) navigate" in shell

    assert "registerScopeChangeGuard((change) =>" in page
    assert "if (!dirtyRef.current) return true" in page
    assert "window.confirm(" in page
    assert "if (confirmed) invalidateWorkbookContext()" in page


def test_async_workbook_writes_are_bound_to_the_current_context() -> None:
    page = _source("pages/ImageWorkspacePage.tsx")

    assert "interface WorkbookAsyncContext" in page
    assert "generation: contextGenerationRef.current" in page
    assert "context.projectId === activeProjectIdRef.current" in page
    assert "context.assetId === selectedAssetIdRef.current" in page
    assert "context.analysisRunId === analysisRunIdRef.current" in page
    assert (
        "const requestContext = captureWorkbookContext(selectedAsset.asset_id)" in page
    )
    assert "if (!isWorkbookContextCurrent(requestContext)) return undefined" in page
    assert "if (!isWorkbookContextCurrent(requestContext)) return" in page
    assert page.count("isWorkbookContextCurrent(requestContext)") >= 12


def test_command_center_is_a_live_scoped_agent_task_workbench() -> None:
    page = _source("pages/CommandCenterPage.tsx")
    api = _source("data/api.ts")
    domain = _source("agentDomain.ts")
    styles = _source("styles/index.css")

    assert "../data/fixtures" not in page
    assert "listAgentTasks(workspaceId, projectId)" in page
    assert "scopeGenerationRef" in page
    assert "detailGenerationRef" in page
    assert "task.project_id !== activeProject.project_id" in page
    assert "task.workspace_id !== activeWorkspace.workspace_id" in page

    assert "operatorFetch(`/v1/tasks?${query.toString()}`)" in api
    assert 'operatorFetch("/v1/tasks", {' in api
    assert "/plan`" in api
    assert "/preflight`" in api
    assert "/events`" in api
    assert "/interventions`" in api
    assert "/industrial-incidents`" in api
    assert "/goal3-handoff`" in api
    assert '"X-Goal3-Handoff-SHA256"' in api
    assert 'operatorFetch("/v1/industrial-incidents/runtime-capabilities")' in api
    assert "detachedJcsSha256(" in api
    assert '"GOAL3_HANDOFF_PAYLOAD_DRIFT"' in api

    assert "setPlanApprovalRequired] = useState(true)" in page
    for tool in (
        "image_quality",
        "duplicate_leakage",
        "annotation_integrity",
        "coverage_matrix",
        "governance_audit",
    ):
        assert tool in domain
    assert "具名人工动作 · append-only" in page
    assert "不显示私有思维链" in page
    assert "尚无真实 Incident Case，不模拟" in page
    assert "planning_belief_ledger" in domain
    assert "worker_selection_receipt" in domain
    assert 'receipt.status === "FAILED"' in page
    assert "前端不提供故障注入按钮" in page
    assert "machine_write=false" in page
    assert "production_release=false" in page
    assert "Task 已绑定服务端核验的不可变来源摘要" in page
    assert "source_binding_sha256" in domain
    assert "preferredSourceId" in page
    assert "submissionIdentityRef" in page
    assert '"Idempotency-Key": input.idempotencyKey' in api
    assert "createAgentReverification" in page
    assert "getGoal3HandoffReceipt(taskId)" in page
    assert "GOAL → GOAL3 HANDOFF" in page
    assert "导入授权证据并建立 Incident" in page
    assert "import=1" in page
    assert "Goal3HandoffReceipt" in domain
    assert "cancel_plan" in page
    assert ".agent-workbench" in styles
    assert ".agent-goal3-handoff__rail > span:not(:last-child)::after" in styles
    assert "rgba(245, 249, 255, 0.82)" in styles
    assert "grid-template-columns: 258px minmax(470px, 1fr) 368px" in styles


def test_hosted_agentteams_web_bridge_is_explicit_typed_and_fail_closed() -> None:
    domain = _source("agentDomain.ts")
    api = _source("data/api.ts")
    integrations = _source("pages/IntegrationsPage.tsx")
    command_center = _source("pages/CommandCenterPage.tsx")
    main = _source("main.tsx")
    hosted_styles = _source("styles/hosted-agentteams.css")

    assert "export interface HostedAgentTeamsReceipt" in domain
    assert 'schema_version: "visiondata-gate.agentteams-hosted-receipt.v2"' in domain
    assert "hosted_runtime_verified: false" in domain
    assert 'local_runtime_connection_status: "mapped_not_connected"' in domain
    assert "wait_for_remote_execution: boolean" in domain
    assert "matrix_transaction_sha256: string | null" in domain
    assert "evidence_projections: Record<string" in domain
    assert 'evidence_mode: "allowlisted_projection"' in domain
    assert "exact_wire_retained: false" in domain
    assert "opaque_remote_values_retained: false" in domain
    assert 'provider_version: "v1.2.3"' in domain

    assert "getHostedAgentTeamsHealthStatus" in api
    assert "/hosted-agentteams/probes`" in api
    assert "/hosted-agentteams/submissions`" in api
    assert "approval_id: input.approvalId" in api
    assert "wait_for_remote_execution: false" in api
    assert "function isHostedAgentTeamsReceipt(" in api
    assert "value.hosted_runtime_verified === false" in api
    assert "value.skill_runtime_verified === false" in api
    assert "value.matrix_assignment_verified === false" in api
    assert (
        'value.schema_version === "visiondata-gate.agentteams-hosted-receipt.v2"' in api
    )
    assert "isSha256(value.matrix_transaction_sha256)" in api
    assert "isHostedEvidenceProjections(value.evidence_projections)" in api
    assert 'value.evidence_mode === "allowlisted_projection"' in api
    assert "value.exact_wire_retained === false" in api
    assert "value.opaque_remote_values_retained === false" in api
    assert 'value.local_runtime_connection_status === "mapped_not_connected"' in api
    assert '"HOSTED_AGENTTEAMS_CONTRACT_DRIFT"' in api
    assert '"X-Hosted-AgentTeams-Receipt-SHA256"' in api
    assert '"HOSTED_AGENTTEAMS_ETAG_BINDING_DRIFT"' in api

    assert "getHostedAgentTeamsHealthStatus()" in integrations
    assert "const receipt = await probeHostedAgentTeams(workspaceId)" in integrations
    assert "onClick={() => void probeHostedTransport()}" in integrations
    assert "NOT_CONFIGURED" in integrations
    assert "CONFIGURED_NOT_PROBED" in integrations
    assert "HOSTED TRANSPORT CUSTODY" in integrations
    assert "hostedProbeReceipt.receipt_sha256" in integrations
    assert "hostedProbeReceipt.hosted_runtime_verified" in integrations
    assert integrations.count("probeHostedAgentTeams(workspaceId)") == 1

    assert "function HostedAgentTeamsDialog(" in command_center
    assert "hostedApprovalIdPattern" in command_center
    assert "具名 approval_id" in command_center
    assert "REMOTE WRITE · EXPLICIT HUMAN GATE" in command_center
    assert "我确认执行这次远程写操作" in command_center
    assert "submitHostedAgentTeamsTask({ taskId, approvalId })" in command_center
    assert "hostedReceipt.receipt_sha256" in command_center
    assert "hosted_runtime_verified=false" in command_center
    assert "wait_for_remote_execution</span><strong>false" in command_center

    assert 'import "./styles/hosted-agentteams.css"' in main
    assert ".hosted-transport-rail" in hosted_styles
    assert ".hosted-agentteams-submit-form" in hosted_styles


def test_vite_proxy_rejects_cross_site_requests_before_session_injection() -> None:
    vite = (ROOT / "web" / "vite.config.ts").read_text(encoding="utf-8")
    api = _source("data/api.ts")
    bootstrap = _source("platform/browserSession.ts")
    launcher = (ROOT / "run_workbench.ps1").read_text(encoding="utf-8")

    assert 'new Set(["POST", "PUT", "PATCH", "DELETE"])' in vite
    assert 'request.headers["sec-fetch-site"]' in vite
    assert 'fetchSite === "cross-site"' in vite
    assert 'origin === "null" || origin !== expectedOrigin' in vite
    assert '"cross_site_request_rejected"' in vite
    assert "VISIONDATA_WEB_SESSION_TOKEN" not in vite
    assert "headers: sessionToken" not in vite
    assert '"X-VisionData-Session-Token"' in api
    assert "resolveBrowserSessionBootstrap" in api
    assert "visiondata_session" in bootstrap
    assert "window.history.replaceState" in bootstrap
    assert "#visiondata_session=$SessionToken" in launcher
    assert "VISIONDATA_WEB_SESSION_TOKEN" not in launcher
    assert "will not disclose a new" in launcher


def test_tauri_backend_readiness_is_bound_to_child_only_startup_secret() -> None:
    tauri = (ROOT / "web" / "src-tauri" / "src" / "lib.rs").read_text(encoding="utf-8")
    api = (ROOT / "src" / "visiondata_gate" / "api.py").read_text(encoding="utf-8")

    assert 'env("VISIONDATA_DESKTOP_STARTUP_SECRET", startup_secret)' in tauri
    assert "probe_backend_identity(port, &challenge)" in tauri
    assert "expected_startup_proof(startup_secret, &challenge)" in tauri
    assert "GET /v1/desktop/readiness?challenge={challenge}" in tauri
    assert "SHA256_BLOCK_BYTES" in tauri
    assert "inner_pad" in tauri
    assert "outer_pad" in tauri
    assert '"/v1/desktop/readiness"' in api
    assert "hmac.new(" in api
    assert "desktop_startup_secret.encode" in api


def test_governance_shadow_metrics_and_source_registration_use_real_api() -> None:
    governance = _source("pages/GovernancePage.tsx")
    integrations = _source("pages/IntegrationsPage.tsx")
    api = _source("data/api.ts")
    styles = _source("styles/index.css")

    assert "listAgentTasks(workspaceId, projectId)" in governance
    assert "listIndustrialShadowEvaluations(task.task_id)" in governance
    assert "createShadowEvaluationManifestV2(" in governance
    assert "getProjectGovernanceEffectiveness(projectId)" in governance
    assert "false_release_rate" in governance
    assert "verified_remediation_pass_rate" in governance
    assert "units 至少需要 1 条逐单元记录" in governance
    assert "公开 Omni、Synthetic 或页面 fixture 不会自动计入这里" in governance
    assert "../data/fixtures" not in governance
    assert "getAgentReleaseReadiness(latestCompletedTask.task_id)" in governance
    assert "Readiness Report SHA-256 · live" in governance

    assert "/industrial-shadow-evaluations`" in api
    assert "/industrial-shadow-evaluation-manifests`" in api
    assert 'method: "POST"' in api
    assert 'operatorFetch("/v1/data-sources/local-authorizations"' in api
    assert "authorizeLocalTaskSource" in integrations
    assert "listSourceAuthorizationEvents" in integrations
    assert "revokeLocalTaskSource" in integrations
    assert "expectedLatestEventSha256" in integrations
    assert "永久撤销此授权" in integrations
    assert "../data/fixtures" not in integrations
    assert "../data/integrationCatalog" in integrations
    assert "登记只读来源" in integrations
    assert "查看合同与状态" in integrations
    assert ".shadow-evaluation-form" in styles
    assert ".integration-source-form" in styles
    assert ".integration-source-ledger" in styles


def test_workbook_project_snapshot_handoff_uses_the_live_product_api() -> None:
    page = _source("pages/ImageWorkspacePage.tsx")
    api = _source("data/api.ts")

    assert "authorizeOperatorProjectSnapshot" in page
    assert 'operatorFetch(\n    "/v1/data-sources/operator-project-snapshots"' in api
    assert "await save()" in page
    assert "activeProjectIdRef.current !== handoffProjectId" in page
    assert "operator_snapshot_receipt_sha256" in page
    assert "冻结项目并交给 Agent" in page
    assert "command-center?create=1&source=" in page


def test_product_context_reconnects_without_reloading_the_workbench() -> None:
    context = _source("ProductContext.tsx")
    shell = _source("components/AppShell.tsx")

    assert "refreshConnection: () => Promise<void>" in context
    assert "connectionProbeRef" in context
    assert 'connection.api === "CONNECTED" ? 30_000 : 5_000' in context
    assert 'window.addEventListener("online", refreshWhenOnline)' in context
    assert (
        'document.addEventListener("visibilitychange", refreshWhenVisible)' in context
    )
    assert (
        'aria-label={publicReplayMode ? "公开静态回放状态" : "重新检测本地 API"}'
        in shell
    )
    assert "onClick={() => void refreshConnection()}" in shell
    assert "data/fixtures" not in context
    assert (
        "if (publicReplayMode) {\n      setScopeLoading(false);\n      return;" in shell
    )
    assert 'aria-label="搜索或运行命令"' in shell


def test_product_context_prefers_real_projects_but_keeps_isolated_demo_usable() -> None:
    context = _source("ProductContext.tsx")

    assert "function pickPreferredProject(" in context
    assert "projects.find((item) => item.project_id === activeProjectId)" in context
    assert 'projects.find((item) => item.source_kind !== "synthetic_demo")' in context
    assert "projects[0]" in context
    assert "pickPreferredProject(nextProjects, activeProjectId)" in context
    assert 'pickPreferredProject(nextProjects, "")' in context


def test_reviewer_page_reads_current_project_authoritative_summary() -> None:
    page = _source("pages/ReviewPage.tsx")

    assert "../data/fixtures" not in page
    assert (
        "listAgentTasks(activeWorkspace.workspace_id, activeProject.project_id)" in page
    )
    assert "listAgentTaskEvents(task.task_id)" in page
    assert "getAgentReleaseReadiness(task.task_id)" in page
    assert 'readiness?.evidence_integrity === "VERIFIED"' in page
    assert "getAgentTaskLineage(task.task_id)" in page
    assert "listIndustrialIncidentV5(taskId)" in page
    assert "listAgentCapaLineageRecords(taskId)" in page
    assert "getProjectGovernanceEffectiveness(activeProject.project_id)" in page
    assert 'activeProject?.source_kind === "synthetic_demo"' in page
    assert "<ReviewSyntheticAssetProof assets={live.assets}" in page
    assert "<ReviewInteractionBridge" in page
    assert "incidentsUnavailable={incidentsUnavailable}" in page
    assert "SAMPLE SCOPE · SYNTHETIC" in page
    assert "评审页不生成跨单位总准确率" in page
    assert "接口失败时保持缺失，不用 fixture 补位" in page
    assert "本页不会发送业务写请求" in page


def test_reviewer_route_frontloads_demo_story_and_preserves_accessibility() -> None:
    page = _source("pages/ReviewPage.tsx")
    manifest = _source("components/SemifinalManifestEvidence.tsx")
    shell = _source("components/AppShell.tsx")
    styles = _source("styles/index.css")
    manifest_styles = _source("styles/semifinal-manifest.css")
    evaluation_styles = _source("styles/evaluation-evidence.css")

    manifest_position = page.index("<SemifinalManifestEvidence")
    visual_position = page.index("<ReviewSyntheticAssetProof")
    interaction_position = page.index("<ReviewInteractionBridge")
    dynamic_bench_position = page.index("<EvaluationEvidencePanel")
    assert (
        manifest_position
        < visual_position
        < interaction_position
        < dynamic_bench_position
    )

    assert "semifinal-manifest is-compact" in manifest
    assert "CHAIN VERIFIED" in manifest
    assert "OUTCOME · HOLD" in manifest
    assert "dataStatus={status}" in manifest

    assert 'className="skip-to-content" href="#main-content"' in shell
    assert 'id="main-content"' in shell
    assert ".skip-to-content:focus-visible" in styles

    assert ".review-page :where(button, select, summary)" in styles
    assert (
        ".review-page .semifinal-manifest__actions button { min-height: 44px; }"
        in manifest_styles
    )
    assert (
        ".review-page .evaluation-evidence__actions button { min-height: 44px; }"
        in evaluation_styles
    )


def test_evidence_vault_downloads_real_sha_bound_server_artifacts() -> None:
    page = _source("pages/EvidencePage.tsx")
    styles = _source("styles/index.css")

    assert "../data/fixtures" not in page
    assert "type ArtifactTarget =" in page
    for target in (
        '"evidenceZip"',
        '"runtimeTrace"',
        '"decisionPacketHtml"',
        '"auditBundle"',
    ):
        assert target in page

    assert 'globalThis.crypto.subtle.digest("SHA-256", bytes)' in page
    assert "const bytes = await response.arrayBuffer()" in page
    assert "computedSha !== returnedByteSha" in page
    assert "returnedSha !== options.expectedSha256" in page
    for header in (
        "X-Evidence-SHA256",
        "X-Trace-SHA256",
        "X-Decision-Packet-SHA256",
        "X-Audit-Bundle-SHA256",
    ):
        assert header in page

    assert "/evidence`" in page
    assert "/trace`" in page
    assert "/decision-packet.html`" in page
    assert "/decision-packet/audit-bundle`" in page
    assert "verifyResponseBytes: false" not in page
    assert page.count("verifyResponseBytes: true") == 4
    assert 'byteShaHeader: "X-Content-SHA256"' in page

    assert "artifactScopeKey" in page
    assert "artifactScopeRef.current !== expectedScope" in page
    assert "artifactDownloadGenerations.current[target] !== generation" in page
    assert "setArtifactDownloads(initialArtifactDownloads())" in page
    assert "selectedIncidentKey" in page
    assert "服务端未返回有效的" in page
    assert "浏览器字节 SHA 与服务端响应头不一致" in page
    assert ".live-evidence-artifact-result.is-success" in styles
    assert ".live-evidence-artifact-result.is-danger" in styles


def test_live_incident_workbench_wires_human_decision_resume_and_capa() -> None:
    route = _source("pages/CaseWorkbenchPage.tsx")
    inbox = _source("pages/CasesPage.tsx")
    workbench = _source("components/LiveIncidentWorkbench.tsx")
    capa = _source("components/ControlledCapaWorkbench.tsx")
    api = _source("data/api.ts")
    domain = _source("agentDomain.ts")
    styles = _source("styles/index.css")
    interaction_styles = _source("styles/incident-interaction.css")

    assert "industrialIncidentIdPattern" in route
    assert "<LiveIncidentWorkbench" in route
    assert "?task=${encodeURIComponent(selected.task.task_id)}" in inbox
    assert "进入案件工作台" in inbox
    assert 'searchParams.get("import") === "1"' in inbox
    assert "initialTaskId={requestedTaskId || undefined}" in inbox
    assert "Goal → Goal3 交接被拒绝" in inbox
    assert "getGoal3HandoffReceipt(task.task_id)" in inbox
    assert 'selectedHandoff?.handoff_status === "READY_FOR_INCIDENT_INTAKE"' in inbox
    assert "tasks={importableTasks}" in inbox
    assert "handoffs={goal3Handoffs}" in inbox
    assert "currentHandoff.receipt_sha256" in inbox
    assert '"X-Goal3-Handoff-SHA256": expectedGoal3HandoffSha256' in api
    assert ".incident-import-handoff" in styles

    assert "../data/fixtures" not in workbench
    assert "getAgentTask(taskId)" in workbench
    assert "task.workspace_id !== activeWorkspace.workspace_id" in workbench
    assert "task.project_id !== activeProject.project_id" in workbench
    assert "getIndustrialIncident(taskId, caseId)" in workbench
    assert "listIndustrialIncidentDecisions(taskId, caseId)" in workbench
    assert "recordIndustrialIncidentDecision" in workbench
    assert "resumeIndustrialIncident" in workbench
    assert "getIndustrialIncidentCommand" in workbench
    assert "anticipatedIncidentCommandId" in workbench
    assert 'status: "PENDING"' in workbench
    assert "显式查询命令" in workbench
    assert "禁止自动重放" in workbench
    assert 'commandReconciliation?.status === "PENDING"' in workbench
    assert "operator_attests_inputs_authorized" in workbench
    assert "raw_industrial_data_redistribution_allowed" in workbench
    assert "SIMULATED EVIDENCE" in workbench
    assert "不得视为真实工厂影子证据" in workbench
    assert "生产放行或设备控制" in workbench

    assert "X-Incident-Case-SHA256" in api
    assert "X-Incident-Decision-SHA256" in api
    assert "X-Incident-Command-Id" in api
    assert "incidentCommandId" in api
    assert "getIndustrialIncidentCommand" in api
    assert "industrial-incident-commands" in api
    assert 'requireBoundResponseSha(response, "X-Content-SHA256", contentSha256)' in api
    assert "REQUEST_TIMEOUT" in api
    assert "NETWORK_UNAVAILABLE" in api
    assert "requireBoundResponseSha" in api
    assert "INCIDENT_SCOPE_DRIFT" in api
    assert "IndustrialIncidentDecisionReceipt" in domain
    assert "IndustrialIncidentCommandResult" in domain
    assert "IndustrialIncidentCommandReceipt" in domain

    assert 'searchParams.get("task")' in capa
    assert 'searchParams.get("case")' in capa
    assert "深链接 CAPA 不属于当前 workspace / project" in capa
    assert ".live-incident-grid" in styles
    assert ".live-incident-simulated" in styles
    assert ".live-incident-command-reconcile" in interaction_styles
    assert ".live-incident-command-reconcile.is-rejected" in interaction_styles


def test_incident_transport_disconnect_is_unknown_and_requires_reconciliation() -> None:
    api = _source("data/api.ts")
    workbench = _source("components/LiveIncidentWorkbench.tsx")

    assert '"NETWORK_UNAVAILABLE"' in api
    assert "本地 API 连接中断" in api
    assert "结果未知" in api
    assert "禁止自动重放" in api
    assert "value.status === 0" in workbench
    assert 'value.code === "NETWORK_UNAVAILABLE"' in workbench
    assert "unknownCommandOutcomeDetail(caught)" in workbench
    assert "WRITE RESULT UNKNOWN / HOLD" in workbench
    assert "保留原命令标识并等待显式对账" in workbench


def test_incident_review_and_capa_reads_are_sha_bound_and_recoverable() -> None:
    api = _source("data/api.ts")
    capa_api = _source("data/capaApi.ts")
    domain = _source("agentDomain.ts")
    integrity = _source("data/capaIntegrity.ts")

    assert "export interface IncidentReviewProjection" in domain
    assert "triggering_evidence" in domain
    assert "competing_hypotheses" in domain
    assert "missing_evidence_refs" in domain
    assert 'transport_source_mode: "LIVE"' in domain
    assert 'evidence_source_mode: "REPLAY" | "OFFLINE_EXPORT"' in domain

    assert "getIndustrialIncidentReviewProjection" in api
    assert "readIndustrialIncidentReviewProjection" in api
    assert "reviewProjection" in api
    assert "missing_linked_capa_case_ids" in api
    assert "decision.case_sha256 === decisionScopeCaseSha256" in api
    assert "node.evidence_sha256 === capa.child_evidence_sha256" in api
    assert 'status: "NOT_CREATED"' in api
    assert 'status: "STALE_HOLD"' in api
    assert 'status: "RETRYABLE_UNAVAILABLE"' in api
    assert "error.status === 503" in api
    assert "retainedVerifiedValue" in api
    assert "projection_sha256" in api
    assert "pythonCanonicalSha256FromJsonValue(source)" in api
    assert "payload.filter(isIndustrialIncident)" not in api
    assert 'schemaVersion === "visiondata-gate.industrial-incident-case.v5"' in api
    assert 'schemaVersion === "visiondata-gate.industrial-incident-case.v6"' in api
    assert 'rawEtag.match(/^"([0-9a-fA-F]{64})"$/)' in api

    assert "export async function getControlledCapaCase" in capa_api
    assert "export async function readControlledCapaCase" in capa_api
    assert "error.status === 404 && retained === undefined" in capa_api
    assert "error.status === 503" in capa_api
    assert "validateControlledCapaCase" in capa_api
    assert "retainedVerifiedValue" in capa_api
    assert "pythonCanonicalSha256FromJsonValue" in integrity


def test_industrial_delivery_capa_outcome_bridge_is_typed_scoped_and_fail_closed() -> (
    None
):
    domain = _source("capaDomain.ts")
    api = _source("data/capaApi.ts")
    integrity = _source("data/capaIntegrity.ts")
    workbench = _source("components/ControlledCapaWorkbench.tsx")
    styles = _source("styles/capa-delivery.css")

    for contract in (
        "IndustrialDeliveryReceipt",
        "IndustrialEvidenceFusionEntry",
        "IndustrialRiskCluster",
        "IndustrialRemediationPlan",
        "CapaOutcomeAssessment",
        "GovernedOutcomeEnvelope",
    ):
        assert f"export interface {contract}" in domain

    for api_function in (
        "getIndustrialDelivery",
        "selectControlledCapaPlan",
        "getCapaOutcomeAssessment",
        "getGovernedOutcomeEnvelope",
    ):
        assert f"export async function {api_function}" in api

    assert "X-Content-SHA256" in api
    assert "ETag" in api
    assert "value.result.production_release_allowed === false" in api
    assert "value.result.machine_write_permitted === false" in api
    assert "value.subject.parent_task_id === taskId" in api
    assert "value.subject.capa_case_id === caseId" in api
    assert "pythonCanonicalSha256FromJson(source, omittedTopLevelKeys)" in api
    assert "const contentSha = await computeCanonicalSha(body.source)" in api
    assert 'computeCanonicalSha(body.source, ["assessment_sha256"])' in api
    assert "governedOutcomeRootSha256(value)" in api
    assert "computedRoot === payload.outcome_root.value" in api
    assert "new LosslessJsonParser(source).parse()" in integrity
    assert "serializePythonCanonical" in integrity
    assert "serializeJcs" in integrity
    assert 'const outcomeRootDomain = "visiondata-gate/outcome/root/v1"' in integrity

    assert "../data/fixtures" not in workbench
    assert 'task.source_kind === "local_authorized_directory"' in workbench
    assert "SIX-SOURCE EVIDENCE" in workbench
    assert "RISK CLUSTERS" in workbench
    assert "CANDIDATE REMEDIATION PLANS" in workbench
    assert "具名选择并创建 CAPA" in workbench
    assert '"ASSESSMENT_VERIFIED"' in workbench
    assert 'selected.capa.status === "DERIVED_VERSION_READY"' in workbench
    assert "核验派生回执并继续 Child Run" in workbench
    assert "不会重建或覆盖派生版本" in workbench
    assert "CAPA ASSESSMENT SHA VERIFIED · GOVERNED OUTCOME HOLD" in workbench
    assert "OUTCOME AUTHORITY UNAVAILABLE / HOLD" in workbench
    assert "GOVERNED OUTCOME · SHA VERIFIED" in workbench
    assert "SERVER-SEALED OPTIONS" in workbench
    assert "SERVER-SIGNED" not in workbench
    assert "已验签" not in workbench
    assert "scopeIdentityRef" in workbench
    assert "mutationRequestRef" in workbench
    assert "WRITE RESULT UNKNOWN / HOLD" in workbench
    assert "不会自动重放" in workbench
    assert "machine_write_permitted=false" in workbench
    assert ".controlled-capa-plan-compare" in styles
    assert "@media (max-width: 760px)" in styles


def test_live_incident_goal3_authority_bridge_fails_closed() -> None:
    workbench = _source("components/LiveIncidentWorkbench.tsx")
    api = _source("data/api.ts")
    domain = _source("agentDomain.ts")
    styles = _source("styles/incident-interaction.css")

    for contract in (
        "IncidentPhaseEvent",
        "IncidentControlPlaneBundle",
        "IncidentRuntimeProfileBinding",
        "GovernedAuditEnvelope",
        "IndustrialIncidentAuthoritySnapshot",
    ):
        assert f"export interface {contract}" in domain

    for api_function in (
        "listIndustrialIncidentPhaseEvents",
        "getIndustrialIncidentControlPlane",
        "getIndustrialIncidentAuditEnvelope",
        "getIndustrialIncidentRuntimeProfileBinding",
        "getIndustrialIncidentAuthoritySnapshot",
    ):
        assert f"export async function {api_function}" in api

    for endpoint in (
        "/phase-events`",
        "/control-plane`",
        "/audit-envelope`",
        "/runtime-profile-binding`",
    ):
        assert endpoint in api
    assert "await Promise.all([" in api
    assert "isIncidentPhaseEventChain" in api
    assert "INCIDENT_AUTHORITY_CROSS_BINDING_DRIFT" in api
    assert 'requireBoundResponseSha(response, "X-Audit-Root-SHA256"' in api
    assert 'response.headers.get("X-Signature-Status")' in api
    assert "packet.production_release_allowed === false" in api
    assert "packet.machine_write_permitted === false" in api
    assert "value.secrets_retained === false" in api
    assert 'value.production_decision_authority === "human_only"' in api

    assert "getIndustrialIncidentAuthoritySnapshot({" in workbench
    assert "Promise.allSettled([" in workbench
    assert "<IncidentAuthorityBridge" in workbench
    assert "四个只读接口并发核验" in workbench
    assert "不显示隐藏思维链" in workbench
    assert "UNAVAILABLE · FAIL CLOSED" in workbench
    assert "不使用 fixture 补位" in workbench
    assert "production_release=false" in workbench
    assert "machine_write=false" in workbench
    assert "authority=human_only" in workbench
    for stage in (
        'label: "Intake"',
        'label: "Planner"',
        'label: "Tool"',
        'label: "Council / Ledger"',
        'label: "Policy Judge"',
        'label: "Delivery"',
    ):
        assert stage in workbench

    assert ".incident-authority-bridge" in styles
    assert ".incident-authority-stages" in styles
    assert "background: rgba(255, 255, 255, 0.86)" in styles
    assert ".incident-authority-bridge--unavailable" in styles


def test_live_incident_renders_sha_verified_frozen_task_visuals() -> None:
    workbench = _source("components/LiveIncidentWorkbench.tsx")
    panel = _source("components/TaskVisualEvidencePanel.tsx")
    canvas = _source("components/InteractiveImageCanvas.tsx")
    api = _source("data/api.ts")
    styles = _source("styles/index.css")

    assert "<TaskVisualEvidencePanel" in workbench
    assert 'scope.task.source_kind === "synthetic_demo"' in workbench
    assert "Task 冻结视觉分母未声明" in workbench
    assert "不会请求只适用于已授权真实来源的 Task Visual Evidence" in workbench
    assert "expectedWorkspaceId={scope.task.workspace_id}" in workbench
    assert "expectedProjectId={scope.task.project_id}" in workbench
    assert "../data/fixtures" not in panel
    assert "getTaskVisualEvidence(taskId)" in panel
    assert "loadTaskVisualEvidencePreview(selected)" in panel
    assert "loadTaskVisualEvidenceMask(selected)" in panel
    assert "payload.workspace_id !== expectedWorkspaceId" in panel
    assert "payload.project_id !== expectedProjectId" in panel
    assert "<InteractiveImageCanvas" in panel
    assert "readOnly" in panel
    assert 'if (readOnly && tool === "BOX")' in canvas
    assert 'if (key === "b" && !readOnly)' in canvas

    assert "/visual-evidence`" in api
    assert '"X-Visual-Evidence-SHA256"' in api
    assert '"X-Content-SHA256"' in api
    assert 'globalThis.crypto.subtle.digest("SHA-256", bytes)' in api
    assert "TASK_VISUAL_EVIDENCE_BYTE_DRIFT" in api
    assert ".task-visual-evidence__layout" in styles
    assert ".task-visual-evidence__canvas" in styles


def test_reviewer_interaction_bridge_fails_closed_on_case_binding_drift() -> None:
    bridge = _source("components/ReviewInteractionBridge.tsx")

    assert "incident.task_id === taskId" in bridge
    assert "getIndustrialIncidentInteractionReceipt(taskId, child.case_id)" in bridge
    assert "value.parent_case_id !== child.parent_case_id" in bridge
    assert "value.parent_case_sha256 !== child.parent_case_sha256" in bridge
    assert "value.decision_id !== child.authorizing_decision_id" in bridge
    assert "value.decision_sha256 !== child.authorizing_decision_sha256" in bridge
    assert "value.child_case_sha256 !== child.case_sha256" in bridge
    assert "<IncidentInteractionTimeline" in bridge
    assert "FAIL CLOSED" in bridge
    assert "页面不会伪造多轮交互" in bridge
    assert "retryToken" in bridge
    assert "setRetryToken((value) => value + 1)" in bridge
    assert "重试只读 GET" in bridge


def test_reviewer_synthetic_assets_are_byte_verified_and_not_task_evidence() -> None:
    proof = _source("components/ReviewSyntheticAssetProof.tsx")
    api = _source("data/api.ts")

    assert 'asset.original_name === "synthetic-fixture-before.png"' in proof
    assert 'asset.original_name === "synthetic-fixture-recheck.png"' in proof
    assert "loadOperatorPreview(asset)" in proof
    assert "不是 Task 冻结视觉分母" in proof
    assert "factory effect · NOT CLAIMED" in proof
    assert (
        'requireBoundResponseSha(response, "X-Content-SHA256", asset.preview_sha256)'
        in api
    )
    assert "observedSha256 !== asset.preview_sha256" in api
    assert "OPERATOR_PREVIEW_BYTE_DRIFT" in api
    assert "new Blob([bytes], { type: asset.content_type })" in api


def test_dynamicbench_evaluation_evidence_web_projection_is_strict_and_read_only() -> (
    None
):
    domain = _source("evaluationEvidenceDomain.ts")
    api = _source("data/evaluationEvidenceApi.ts")
    panel = _source("components/EvaluationEvidencePanel.tsx")
    review = _source("pages/ReviewPage.tsx")
    governance = _source("pages/GovernancePage.tsx")
    main = _source("main.tsx")
    styles = _source("styles/evaluation-evidence.css")

    assert "DynamicBenchEvaluationEvidenceProjection" in domain
    assert 'kind: "GLOBAL_REVIEW"' in domain
    assert 'kind: "PROJECT_REFERENCE"' in domain
    assert "production_release_allowed: false" in domain
    assert (
        'factory_shadow_metrics_status: "NOT_MEASURED_PENDING_ADJUDICATION"' in domain
    )
    assert "benchmark_truth_feedback_to_agent_runtime: false" in domain

    assert "rejectUnexpectedKeys(projection, projectionKeys" in api
    assert (
        'projection.schema_version === "visiondata-gate.dynamicbench-evaluation-evidence-projection.v1"'
        in api
    )
    assert 'common.schema_version === "visiondata-gate.dynamic-benchmark.v3"' in api
    assert 'common.schema_version === "visiondata-gate.dynamic-benchmark.v4"' in api
    assert (
        "ProductService.run_task_sync->ProductService.create_industrial_incident_case->IncidentKernelV6"
        in api
    )
    assert 'projection.factory_metrics_status === "NOT_MEASURED_BY_DYNAMICBENCH"' in api
    assert "projection.production_release_allowed === false" in api
    assert "projection.benchmark_truth_feedback_to_agent_runtime === false" in api
    assert 'response.headers.get("X-Evaluation-Evidence-SHA256")' in api
    assert 'response.headers.get("ETag")' in api
    assert "/v1/review/evaluation-evidence/dynamicbench" in api
    assert "/evaluation-evidence/dynamicbench${suffix}" in api

    assert "getDynamicBenchEvaluationEvidence(scope)" in panel
    assert "HOLD · EVALUATION EVIDENCE UNAVAILABLE" in panel
    assert "页面不使用 fixture、文档数字或浏览器计算结果补位" in panel
    assert "v3Metrics.dynamic_replanning_correct_terminal_disposition_count" in panel
    assert "v3Metrics.fixed_rule_correct_terminal_disposition_count" in panel
    assert "v3Metrics.dynamic_replanning_total_tool_call_count" in panel
    assert "v3Metrics.fixed_rule_total_tool_call_count" in panel
    assert "v4Metrics.tool_failure_recovered_fail_closed_count" in panel
    assert "v4Metrics.tool_failure_fixture_count" in panel
    assert "8/8" not in panel
    assert "4/8" not in panel
    assert "14 vs 24" not in panel
    assert "2/2" not in panel

    assert "<EvaluationEvidencePanel" in review
    assert 'kind: "GLOBAL_REVIEW"' in review
    assert 'href="#dynamicbench-evidence"' in governance
    assert "<EvaluationEvidencePanel" in governance
    assert 'kind: "PROJECT_REFERENCE"' in governance
    assert "./styles/evaluation-evidence.css" in main
    assert ".evaluation-evidence__seam" in styles
    assert "rgba(244, 248, 252, 0.78)" in styles
    assert "@media (max-width: 860px)" in styles
    assert ":focus-visible" in styles
