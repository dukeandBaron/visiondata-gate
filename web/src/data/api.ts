import type {
  CausalReplayReport,
  CausalReplayStep,
  CausalReplayStepId,
  ProviderConnectionTestResult,
  ProviderProfileInput,
  ProviderProfileRecord,
  ProjectRecord,
  ProjectSourceKind,
  ReviewerSnapshotApi,
  RuntimeConnectionState,
  ScenarioProfile,
  WorkspaceRecord,
} from "../domain";
import type {
  BoundingBoxAnnotation,
  OperatorAnalysisRun,
  OperatorAnnotationState,
  OperatorCopilotTurn,
  OperatorImageAsset,
  OperatorImageUploadBatch,
  OperatorWorkOrder,
  OperatorWorkOrderStatus,
} from "../operatorDomain";
import type {
  AgentCapaLineageRecord,
  AgentIntervention,
  AgentInterventionAction,
  AgentReleaseReadiness,
  AgentRuntimeCapabilities,
  AgentTask,
  AgentTaskEvent,
  AgentTaskLineageReport,
  AgentTaskPlan,
  AgentTaskPreflight,
  GovernedAuditEnvelope,
  GovernedIncidentContext,
  Goal3HandoffReceipt,
  HostedAgentTeamsHTTPExchangeReceipt,
  HostedAgentTeamsOperation,
  HostedAgentTeamsReceipt,
  IncidentInteractionReceipt,
  IncidentControlPlaneBundle,
  IncidentPhaseEvent,
  IncidentRuntimeProfileBinding,
  IndustrialIncident,
  IndustrialIncidentAuthoritySnapshot,
  IndustrialIncidentCommandReceipt,
  IndustrialIncidentCommandResult,
  IndustrialIncidentDecisionReceipt,
  IndustrialIncidentHumanDecision,
  IndustrialQualityDecisionPacket,
  IncidentReviewProjection,
  LocalTaskSource,
  PublicAgentTool,
  SourceAuthorizationEvent,
} from "../agentDomain";
import type {
  CreateIndustrialShadowEvaluationInput,
  CreateShadowEvaluationManifestV2Input,
  IndustrialShadowEvaluationReceipt,
  ProjectGovernanceEffectivenessSummary,
  ShadowEvaluationManifestV2,
} from "../governanceDomain";
import type {
  TaskVisualEvidenceItem,
  TaskVisualEvidenceManifest,
  TaskVisualEvidenceMeasurement,
} from "../visualEvidenceDomain";
import { resolveDesktopRuntimeConfig } from "../platform/bridge";
import { resolveBrowserSessionBootstrap } from "../platform/browserSession";
import {
  pythonCanonicalSha256FromJson,
  pythonCanonicalSha256FromJsonValue,
} from "./capaIntegrity";
import { detachedJcsSha256 } from "./jcs";

const requestTimeoutMs = 2_500;

function normalizedBase(value: string | undefined): string {
  return (value ?? "").trim().replace(/\/$/, "");
}

const configuredBrowserApiBaseUrl = normalizedBase(
  import.meta.env.VITE_VISIONDATA_API_BASE_URL,
);
// The standard workbench launcher exposes the API through Vite's same-origin
// /v1 proxy.  Treat an omitted cross-origin override as same-origin instead of
// reporting a healthy proxied API as "not configured".
const browserApiBaseUrl =
  configuredBrowserApiBaseUrl || window.location.origin;
const reviewerBaseUrl = normalizedBase(import.meta.env.VITE_VISIONDATA_REVIEWER_BASE_URL);
export const operatorActorUserId =
  import.meta.env.VITE_VISIONDATA_ACTOR_USER_ID?.trim() || "usr_local_demo";

interface ApiRuntime {
  apiBaseUrl: string;
  sessionToken?: string;
  desktop: boolean;
}

let apiRuntimePromise: Promise<ApiRuntime> | undefined;

function resolveApiRuntime(): Promise<ApiRuntime> {
  apiRuntimePromise ??= resolveDesktopRuntimeConfig().then((desktop) => {
    const browser = desktop ? undefined : resolveBrowserSessionBootstrap();
    return {
      apiBaseUrl: desktop?.apiBaseUrl ?? browserApiBaseUrl,
      sessionToken: desktop?.sessionToken ?? browser?.sessionToken,
      desktop: desktop !== undefined,
    };
  });
  return apiRuntimePromise;
}

function runtimeAuthorizationHeaders(runtime: ApiRuntime): Record<string, string> {
  if (!runtime.sessionToken) return {};
  return runtime.desktop
    ? {
        "X-VisionData-Desktop-Token": runtime.sessionToken,
        "X-Actor-User-Id": operatorActorUserId,
      }
    : {
        "X-VisionData-Session-Token": runtime.sessionToken,
        "X-Actor-User-Id": operatorActorUserId,
      };
}

async function fetchJson<T>(
  url: string,
  authorizationHeaders: Record<string, string> = {},
): Promise<T> {
  const controller = new AbortController();
  const timeout = window.setTimeout(() => controller.abort(), requestTimeoutMs);
  try {
    const response = await fetch(url, {
      method: "GET",
      headers: {
        Accept: "application/json",
        ...authorizationHeaders,
      },
      credentials: "omit",
      cache: "no-store",
      signal: controller.signal,
    });
    if (!response.ok) {
      throw new Error(`HTTP_${response.status}`);
    }
    return (await response.json()) as T;
  } finally {
    window.clearTimeout(timeout);
  }
}

function isReviewerSnapshot(value: unknown): value is ReviewerSnapshotApi {
  if (!value || typeof value !== "object") return false;
  const snapshot = value as Partial<ReviewerSnapshotApi>;
  return (
    snapshot.schema_version === "visiondata-gate.reviewer-workbench.v1" &&
    !!snapshot.case &&
    !!snapshot.public_pilot &&
    !!snapshot.synthetic_visual &&
    Array.isArray(snapshot.phases) &&
    !!snapshot.runtime &&
    typeof snapshot.snapshot_integrity?.sha256 === "string"
  );
}

export interface RuntimeProbeResult {
  connection: RuntimeConnectionState;
  reviewerSnapshot?: ReviewerSnapshotApi;
}

export async function probeRuntimeConnections(): Promise<RuntimeProbeResult> {
  const checkedAt = new Date().toISOString();
  const runtime = await resolveApiRuntime();
  const attempts = runtime.desktop ? 40 : 1;
  const apiProbe = runtime.apiBaseUrl
    ? (async () => {
        for (let attempt = 0; attempt < attempts; attempt += 1) {
          try {
            await fetchJson<Record<string, unknown>>(
              `${runtime.apiBaseUrl}/v1/workspaces`,
              runtimeAuthorizationHeaders(runtime),
            );
            return "CONNECTED" as const;
          } catch {
            if (attempt + 1 < attempts) {
              await new Promise((resolve) => window.setTimeout(resolve, 250));
            }
          }
        }
        return "UNAVAILABLE" as const;
      })()
    : Promise.resolve("UNAVAILABLE" as const);

  const reviewerProbe = reviewerBaseUrl
    ? fetchJson<unknown>(`${reviewerBaseUrl}/api/reviewer/snapshot`)
        .then((snapshot) => (isReviewerSnapshot(snapshot) ? snapshot : undefined))
        .catch(() => undefined)
    : Promise.resolve(undefined);

  const [api, reviewerSnapshot] = await Promise.all([apiProbe, reviewerProbe]);
  return {
    connection: {
      api,
      reviewer: reviewerSnapshot ? "CONNECTED" : "FALLBACK",
      apiBaseUrl: runtime.apiBaseUrl || "not configured",
      reviewerBaseUrl: reviewerBaseUrl || "frozen fallback",
      checkedAt,
      reviewerSnapshotSha256: reviewerSnapshot?.snapshot_integrity.sha256,
    },
    reviewerSnapshot,
  };
}

export async function listWorkspaces(): Promise<WorkspaceRecord[]> {
  const response = await operatorFetch("/v1/workspaces");
  return (await response.json()) as WorkspaceRecord[];
}

export async function listProjects(workspaceId: string): Promise<ProjectRecord[]> {
  const response = await operatorFetch(
    `/v1/projects?workspace_id=${encodeURIComponent(workspaceId)}`,
  );
  return (await response.json()) as ProjectRecord[];
}

export async function createProject(
  workspaceId: string,
  input: {
    name: string;
    description?: string;
    scenarioProfile?: ScenarioProfile;
    sourceKind?: ProjectSourceKind;
  },
): Promise<ProjectRecord> {
  const response = await operatorFetch("/v1/projects", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      workspace_id: workspaceId,
      name: input.name,
      description: input.description ?? "",
      scenario_profile: input.scenarioProfile ?? "industrial",
      source_kind: input.sourceKind ?? "local_authorized_directory",
    }),
  });
  return (await response.json()) as ProjectRecord;
}

export async function listAgentTasks(
  workspaceId: string,
  projectId: string,
): Promise<AgentTask[]> {
  const query = new URLSearchParams({
    workspace_id: workspaceId,
    project_id: projectId,
    limit: "200",
  });
  const response = await operatorFetch(`/v1/tasks?${query.toString()}`);
  return (await response.json()) as AgentTask[];
}

export async function createAgentTask(input: {
  projectId: string;
  goal: string;
  scenarioProfile: ScenarioProfile;
  sourceKind: ProjectSourceKind;
  sourceId?: string;
  planApprovalRequired: boolean;
  allowedTools: PublicAgentTool[];
  idempotencyKey: string;
}): Promise<AgentTask> {
  const response = await operatorFetch("/v1/tasks", {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
      "Idempotency-Key": input.idempotencyKey,
    },
    body: JSON.stringify({
      project_id: input.projectId,
      goal: input.goal,
      scenario_profile: input.scenarioProfile,
      source_kind: input.sourceKind,
      ...(input.sourceId ? { source_id: input.sourceId } : {}),
      plan_approval_required: input.planApprovalRequired,
      allowed_tools: input.allowedTools,
    }),
  });
  return (await response.json()) as AgentTask;
}

export async function createAgentReverification(input: {
  taskId: string;
  note: string;
  sourceId?: string;
  idempotencyKey: string;
}): Promise<AgentTask> {
  const response = await operatorFetch(
    `/v1/tasks/${encodeURIComponent(input.taskId)}/reverifications`,
    {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
        "Idempotency-Key": input.idempotencyKey,
      },
      body: JSON.stringify({
        note: input.note,
        ...(input.sourceId ? { source_id: input.sourceId } : {}),
      }),
    },
  );
  return (await response.json()) as AgentTask;
}

export async function getAgentTask(taskId: string): Promise<AgentTask> {
  const response = await operatorFetch(`/v1/tasks/${encodeURIComponent(taskId)}`);
  return (await response.json()) as AgentTask;
}

export async function getGoal3HandoffReceipt(
  taskId: string,
): Promise<Goal3HandoffReceipt> {
  const response = await operatorFetch(
    `/v1/tasks/${encodeURIComponent(taskId)}/goal3-handoff`,
  );
  const payload = (await response.json()) as unknown;
  if (!isGoal3HandoffReceipt(payload, taskId)) {
    throw new OperatorApiError(
      "INVALID_GOAL3_HANDOFF_RESPONSE",
      "Goal 到 Goal3 的交接回执未通过前端作用域与安全合同校验",
      502,
    );
  }
  requireBoundResponseSha(
    response,
    "X-Goal3-Handoff-SHA256",
    payload.receipt_sha256,
  );
  let computedSha256: string;
  try {
    computedSha256 = await detachedJcsSha256(
      payload as unknown as Record<string, unknown>,
      "receipt_sha256",
    );
  } catch (caught) {
    throw new OperatorApiError(
      "INVALID_GOAL3_HANDOFF_JCS",
      caught instanceof Error
        ? `Goal 到 Goal3 的交接回执无法执行 JCS 校验：${caught.message}`
        : "Goal 到 Goal3 的交接回执无法执行 JCS 校验",
      502,
    );
  }
  if (computedSha256 !== payload.receipt_sha256) {
    throw new OperatorApiError(
      "GOAL3_HANDOFF_PAYLOAD_DRIFT",
      "Goal 到 Goal3 的交接回执内容与 JCS SHA-256 不一致",
      502,
    );
  }
  return payload;
}

export type HostedAgentTeamsHealthStatus =
  | "NOT_CONFIGURED"
  | "CONFIGURED_NOT_PROBED";

/** Reads local API configuration only. This function never performs a remote probe. */
export async function getHostedAgentTeamsHealthStatus(): Promise<HostedAgentTeamsHealthStatus> {
  const response = await operatorFetch("/v1/health");
  const payload = await response.json() as unknown;
  if (!isRecord(payload) || !isRecord(payload.data_sources)) {
    throw new OperatorApiError(
      "HOSTED_AGENTTEAMS_HEALTH_CONTRACT_DRIFT",
      "Hosted AgentTeams 本地健康状态未通过前端合同校验",
      502,
    );
  }
  const status = payload.data_sources.hosted_agentteams;
  if (status === "not_configured") return "NOT_CONFIGURED";
  if (status === "configured_not_probed") return "CONFIGURED_NOT_PROBED";
  throw new OperatorApiError(
    "HOSTED_AGENTTEAMS_HEALTH_CONTRACT_DRIFT",
    "Hosted AgentTeams 本地健康状态包含未知值",
    502,
  );
}

export async function probeHostedAgentTeams(
  workspaceId: string,
): Promise<HostedAgentTeamsReceipt> {
  const response = await operatorFetch(
    `/v1/workspaces/${encodeURIComponent(workspaceId)}/hosted-agentteams/probes`,
    { method: "POST" },
    120_000,
  );
  return readHostedAgentTeamsReceipt(response, { operation: "probe" });
}

export async function submitHostedAgentTeamsTask(input: {
  taskId: string;
  approvalId: string;
}): Promise<HostedAgentTeamsReceipt> {
  if (!/^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$/.test(input.approvalId)) {
    throw new OperatorApiError(
      "INVALID_HOSTED_AGENTTEAMS_APPROVAL_ID",
      "approval_id 只能使用字母、数字、点、下划线与连字符",
      400,
    );
  }
  const response = await operatorFetch(
    `/v1/tasks/${encodeURIComponent(input.taskId)}/hosted-agentteams/submissions`,
    {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        approval_id: input.approvalId,
        wait_for_remote_execution: false,
      }),
    },
    120_000,
  );
  return readHostedAgentTeamsReceipt(response, {
    operation: "submit_project",
    sourceRunId: input.taskId,
    approvalId: input.approvalId,
  });
}

export async function getAgentTaskLineage(
  taskId: string,
): Promise<AgentTaskLineageReport> {
  const response = await operatorFetch(
    `/v1/tasks/${encodeURIComponent(taskId)}/lineage`,
  );
  const source = await response.text();
  const payload = JSON.parse(source) as unknown;
  if (!isAgentTaskLineageReport(payload)) {
    throw new OperatorApiError(
      "TASK_LINEAGE_CONTRACT_DRIFT",
      "Task lineage 响应未通过前端合同校验",
      502,
    );
  }
  const computedSha256 = await pythonCanonicalSha256FromJson(source, [
    "report_sha256",
  ]);
  if (computedSha256 !== payload.report_sha256) {
    throw new OperatorApiError(
      "TASK_LINEAGE_SHA_DRIFT",
      "Task lineage 内容与内嵌 SHA-256 不一致",
      409,
    );
  }
  requireBoundResponseSha(response, "X-Content-SHA256", payload.report_sha256);
  return payload;
}

export async function getAgentTaskPlan(taskId: string): Promise<AgentTaskPlan> {
  const response = await operatorFetch(
    `/v1/tasks/${encodeURIComponent(taskId)}/plan`,
  );
  return (await response.json()) as AgentTaskPlan;
}

export async function getAgentTaskPreflight(
  taskId: string,
): Promise<AgentTaskPreflight> {
  const response = await operatorFetch(
    `/v1/tasks/${encodeURIComponent(taskId)}/preflight`,
  );
  return (await response.json()) as AgentTaskPreflight;
}

export async function listAgentTaskEvents(
  taskId: string,
): Promise<AgentTaskEvent[]> {
  const response = await operatorFetch(
    `/v1/tasks/${encodeURIComponent(taskId)}/events`,
  );
  return (await response.json()) as AgentTaskEvent[];
}

export async function listAgentInterventions(
  taskId: string,
): Promise<AgentIntervention[]> {
  const response = await operatorFetch(
    `/v1/tasks/${encodeURIComponent(taskId)}/interventions`,
  );
  return (await response.json()) as AgentIntervention[];
}

export async function createAgentIntervention(
  taskId: string,
  action: AgentInterventionAction,
  note: string,
): Promise<AgentIntervention> {
  const response = await operatorFetch(
    `/v1/tasks/${encodeURIComponent(taskId)}/interventions`,
    {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ action, note }),
    },
  );
  return (await response.json()) as AgentIntervention;
}

export async function listIndustrialIncidents(
  taskId: string,
): Promise<IndustrialIncident[]> {
  const response = await operatorFetch(
    `/v1/tasks/${encodeURIComponent(taskId)}/industrial-incidents`,
  );
  const source = await response.text();
  let payload: unknown;
  try {
    payload = JSON.parse(source) as unknown;
  } catch {
    throw new OperatorApiError(
      "INVALID_INCIDENT_LIST_RESPONSE",
      "工业案件列表不是有效 JSON",
      502,
    );
  }
  if (
    !Array.isArray(payload) ||
    !payload.every(
      (item) => isIndustrialIncident(item) && item.task_id === taskId,
    )
  ) {
    throw new OperatorApiError(
      "INVALID_INCIDENT_LIST_RESPONSE",
      "工业案件列表包含未通过 Task 作用域或安全合同校验的案件",
      502,
    );
  }
  const contentSha256 = await pythonCanonicalSha256FromJsonValue(source);
  requireBoundResponseSha(response, "X-Content-SHA256", contentSha256);
  return payload;
}

export async function getIndustrialIncident(
  taskId: string,
  caseId: string,
): Promise<IndustrialIncident> {
  const response = await operatorFetch(
    `/v1/tasks/${encodeURIComponent(taskId)}/industrial-incidents/${encodeURIComponent(caseId)}`,
  );
  const payload = (await response.json()) as unknown;
  if (!isIndustrialIncident(payload)) {
    throw new OperatorApiError(
      "INVALID_INCIDENT_RESPONSE",
      "工业案件响应未通过前端安全合同校验",
      502,
    );
  }
  if (payload.task_id !== taskId || payload.case_id !== caseId) {
    throw new OperatorApiError(
      "INCIDENT_SCOPE_DRIFT",
      "工业案件响应与请求的 Task / Case 作用域不一致",
      409,
    );
  }
  requireBoundResponseSha(response, "X-Incident-Case-SHA256", payload.case_sha256);
  return payload;
}

export async function listIndustrialIncidentPhaseEvents(
  taskId: string,
  caseId: string,
  expectedCaseSha256: string,
): Promise<IncidentPhaseEvent[]> {
  const response = await operatorFetch(
    `/v1/tasks/${encodeURIComponent(taskId)}/industrial-incidents/${encodeURIComponent(caseId)}/phase-events`,
  );
  const source = await response.text();
  const payload = JSON.parse(source) as unknown;
  if (!isIncidentPhaseEventChain(payload, caseId, expectedCaseSha256)) {
    throw new OperatorApiError(
      "INVALID_INCIDENT_PHASE_EVENTS",
      "阶段事件未通过 Case 作用域、连续序号或 SHA-256 前序链校验",
      502,
    );
  }
  const contentSha256 = await pythonCanonicalSha256FromJsonValue(source);
  requireBoundResponseSha(response, "X-Content-SHA256", contentSha256);
  return payload;
}

export async function getIndustrialIncidentControlPlane(
  taskId: string,
  caseId: string,
  expectedCaseSha256: string,
): Promise<IncidentControlPlaneBundle> {
  const response = await operatorFetch(
    `/v1/tasks/${encodeURIComponent(taskId)}/industrial-incidents/${encodeURIComponent(caseId)}/control-plane`,
  );
  const source = await response.text();
  const payload = JSON.parse(source) as unknown;
  if (!isIncidentControlPlane(payload, caseId, expectedCaseSha256)) {
    throw new OperatorApiError(
      "INVALID_INCIDENT_CONTROL_PLANE",
      "控制平面未通过 Case、Plan Tree、Authority Ledger 与安全边界校验",
      502,
    );
  }
  const computedSha256 = await pythonCanonicalSha256FromJson(source, [
    "bundle_sha256",
  ]);
  if (computedSha256 !== payload.bundle_sha256) {
    throw new OperatorApiError(
      "INCIDENT_CONTROL_PLANE_SHA_DRIFT",
      "控制平面内容与内嵌 SHA-256 不一致",
      409,
    );
  }
  requireBoundResponseSha(response, "X-Content-SHA256", payload.bundle_sha256);
  return payload;
}

export async function getIndustrialIncidentDecisionPacket(
  taskId: string,
  caseId: string,
  expectedCaseSha256: string,
): Promise<IndustrialQualityDecisionPacket> {
  const response = await operatorFetch(
    `/v1/tasks/${encodeURIComponent(taskId)}/industrial-incidents/${encodeURIComponent(caseId)}/decision-packet`,
  );
  const source = await response.text();
  const payload = JSON.parse(source) as unknown;
  if (!isIndustrialQualityDecisionPacket(payload, caseId, expectedCaseSha256)) {
    throw new OperatorApiError(
      "INVALID_INCIDENT_DECISION_PACKET",
      "Decision Packet 未通过 Case、Worker、证据缺口或安全边界校验",
      502,
    );
  }
  const computedSha256 = await pythonCanonicalSha256FromJson(source, [
    "packet_sha256",
  ]);
  if (computedSha256 !== payload.packet_sha256) {
    throw new OperatorApiError(
      "INCIDENT_DECISION_PACKET_SHA_DRIFT",
      "Decision Packet 内容与内嵌 SHA-256 不一致",
      409,
    );
  }
  requireBoundResponseSha(
    response,
    "X-Decision-Packet-SHA256",
    payload.packet_sha256,
  );
  return payload;
}

export async function getIndustrialIncidentAuditEnvelope(input: {
  taskId: string;
  caseId: string;
  expectedCaseSha256: string;
  expectedWorkspaceId: string;
  expectedProjectId: string;
}): Promise<GovernedAuditEnvelope> {
  const response = await operatorFetch(
    `/v1/tasks/${encodeURIComponent(input.taskId)}/industrial-incidents/${encodeURIComponent(input.caseId)}/audit-envelope`,
  );
  const payload = (await response.json()) as unknown;
  if (!isGovernedAuditEnvelope(payload, input)) {
    throw new OperatorApiError(
      "INVALID_INCIDENT_AUDIT_ENVELOPE",
      "审计封套未通过 Task、Workspace、Project、Case 或 fail-closed 边界校验",
      502,
    );
  }
  requireBoundResponseSha(response, "X-Audit-Root-SHA256", payload.audit_root.value);
  if (response.headers.get("X-Signature-Status") !== payload.signature.status) {
    throw new OperatorApiError(
      "AUDIT_SIGNATURE_STATUS_DRIFT",
      "审计签名状态响应头与封套实体不一致",
      409,
    );
  }
  return payload;
}

export async function getIndustrialIncidentRuntimeProfileBinding(
  taskId: string,
  caseId: string,
  expectedCaseSha256: string,
): Promise<IncidentRuntimeProfileBinding> {
  const response = await operatorFetch(
    `/v1/tasks/${encodeURIComponent(taskId)}/industrial-incidents/${encodeURIComponent(caseId)}/runtime-profile-binding`,
  );
  const source = await response.text();
  const payload = JSON.parse(source) as unknown;
  if (!isIncidentRuntimeProfileBinding(payload, caseId, expectedCaseSha256)) {
    throw new OperatorApiError(
      "INVALID_INCIDENT_RUNTIME_PROFILE_BINDING",
      "运行档案未通过 Case、SHA-256、密钥保留或人工权限边界校验",
      502,
    );
  }
  const computedSha256 = await pythonCanonicalSha256FromJson(source, [
    "binding_sha256",
  ]);
  if (computedSha256 !== payload.binding_sha256) {
    throw new OperatorApiError(
      "INCIDENT_RUNTIME_PROFILE_SHA_DRIFT",
      "运行档案绑定内容与内嵌 SHA-256 不一致",
      409,
    );
  }
  requireBoundResponseSha(response, "X-Content-SHA256", payload.binding_sha256);
  return payload;
}

export async function getIndustrialIncidentAuthoritySnapshot(input: {
  taskId: string;
  caseId: string;
  caseSha256: string;
  workspaceId: string;
  projectId: string;
  caseStatus: string;
  recommendation: string;
}): Promise<IndustrialIncidentAuthoritySnapshot> {
  const [
    phaseEvents,
    controlPlane,
    decisionPacket,
    reviewProjection,
    auditEnvelope,
    runtimeProfileBinding,
  ] =
    await Promise.all([
      listIndustrialIncidentPhaseEvents(
        input.taskId,
        input.caseId,
        input.caseSha256,
      ),
      getIndustrialIncidentControlPlane(
        input.taskId,
        input.caseId,
        input.caseSha256,
      ),
      getIndustrialIncidentDecisionPacket(
        input.taskId,
        input.caseId,
        input.caseSha256,
      ),
      getIndustrialIncidentReviewProjection(input.taskId, input.caseId),
      getIndustrialIncidentAuditEnvelope({
        taskId: input.taskId,
        caseId: input.caseId,
        expectedCaseSha256: input.caseSha256,
        expectedWorkspaceId: input.workspaceId,
        expectedProjectId: input.projectId,
      }),
      getIndustrialIncidentRuntimeProfileBinding(
        input.taskId,
        input.caseId,
        input.caseSha256,
      ),
    ]);

  assertIncidentAuthorityCrossBindings({
    phaseEvents,
    controlPlane,
    decisionPacket,
    reviewProjection,
    auditEnvelope,
    runtimeProfileBinding,
    expectedStatus: input.caseStatus,
    expectedRecommendation: input.recommendation,
  });
  return {
    phaseEvents,
    controlPlane,
    decisionPacket,
    reviewProjection,
    auditEnvelope,
    runtimeProfileBinding,
  };
}

export async function getIndustrialIncidentCommand(
  taskId: string,
  commandId: string,
): Promise<IndustrialIncidentCommandReceipt> {
  if (!incidentCommandIdPattern.test(commandId)) {
    throw new OperatorApiError(
      "INVALID_INCIDENT_COMMAND_ID",
      "Incident Command ID 格式无效，已拒绝未绑定查询",
      400,
    );
  }
  const response = await operatorFetch(
    `/v1/tasks/${encodeURIComponent(taskId)}/industrial-incident-commands/${encodeURIComponent(commandId)}`,
  );
  const source = await response.text();
  let payload: unknown;
  try {
    payload = JSON.parse(source) as unknown;
  } catch {
    throw new OperatorApiError(
      "INVALID_INCIDENT_COMMAND_RESPONSE",
      "Incident Command 对账回执不是有效 JSON",
      502,
    );
  }
  if (!isIndustrialIncidentCommandReceipt(payload, taskId, commandId)) {
    throw new OperatorApiError(
      "INVALID_INCIDENT_COMMAND_RESPONSE",
      "Incident Command 对账回执未通过作用域与终态合同校验",
      502,
    );
  }
  const contentSha256 = await pythonCanonicalSha256FromJsonValue(source);
  requireBoundResponseSha(response, "X-Content-SHA256", contentSha256);
  return payload;
}

export async function getIndustrialIncidentInteractionReceipt(
  taskId: string,
  childCaseId: string,
): Promise<IncidentInteractionReceipt> {
  const response = await operatorFetch(
    `/v1/tasks/${encodeURIComponent(taskId)}/industrial-incidents/${encodeURIComponent(childCaseId)}/interaction-receipt`,
  );
  const payload = (await response.json()) as unknown;
  if (!isIncidentInteractionReceipt(payload, taskId, childCaseId)) {
    throw new OperatorApiError(
      "INVALID_INCIDENT_INTERACTION_RESPONSE",
      "三轮 Agent / 人工交互回执未通过前端安全合同校验",
      502,
    );
  }
  requireBoundResponseSha(
    response,
    "X-Incident-Interaction-SHA256",
    payload.receipt_sha256,
  );
  return payload;
}

export async function getIndustrialIncidentGovernedContext(
  taskId: string,
  caseId: string,
  expectedCaseSha256: string,
): Promise<GovernedIncidentContext> {
  const response = await operatorFetch(
    `/v1/tasks/${encodeURIComponent(taskId)}/industrial-incidents/${encodeURIComponent(caseId)}/governed-context`,
  );
  const source = await response.text();
  const payload = JSON.parse(source) as unknown;
  if (!isGovernedIncidentContext(payload)) {
    throw new OperatorApiError(
      "INVALID_GOVERNED_CONTEXT_RESPONSE",
      "受治理记忆上下文未通过前端安全合同校验",
      502,
    );
  }
  if (
    payload.context.case_id !== caseId ||
    payload.receipt.case_id !== caseId ||
    payload.context.case_sha256 !== expectedCaseSha256 ||
    payload.receipt.case_sha256 !== expectedCaseSha256
  ) {
    throw new OperatorApiError(
      "GOVERNED_CONTEXT_SCOPE_DRIFT",
      "受治理记忆上下文与当前 Task / Case 摘要不一致",
      409,
    );
  }
  const contentSha256 = await pythonCanonicalSha256FromJsonValue(source);
  requireBoundResponseSha(response, "X-Content-SHA256", contentSha256);
  return payload;
}

export async function getIndustrialIncidentReviewProjection(
  taskId: string,
  caseId: string,
): Promise<IncidentReviewProjection> {
  const response = await operatorFetch(
    `/v1/tasks/${encodeURIComponent(taskId)}/industrial-incidents/${encodeURIComponent(caseId)}/review-projection`,
  );
  const source = await response.text();
  let payload: unknown;
  try {
    payload = JSON.parse(source) as unknown;
  } catch {
    throw new OperatorApiError(
      "INVALID_INCIDENT_REVIEW_PROJECTION",
      "案件评审投影不是有效 JSON",
      502,
    );
  }
  if (!isIncidentReviewProjection(payload, taskId, caseId)) {
    throw new OperatorApiError(
      "INVALID_INCIDENT_REVIEW_PROJECTION",
      "案件评审投影未通过 Worker、证据、Parent/Human/Child 或安全边界校验",
      502,
    );
  }
  const computedSha256 = await pythonCanonicalSha256FromJson(source, [
    "projection_sha256",
  ]);
  if (computedSha256 !== payload.projection_sha256) {
    throw new OperatorApiError(
      "INCIDENT_REVIEW_PROJECTION_SHA_DRIFT",
      "案件评审投影内容与内嵌 SHA-256 不一致",
      409,
    );
  }
  requireBoundResponseSha(
    response,
    "X-Content-SHA256",
    payload.projection_sha256,
  );
  return payload;
}

export type IncidentReviewReadStatus =
  | "VERIFIED"
  | "NOT_CREATED"
  | "STALE_HOLD"
  | "RETRYABLE_UNAVAILABLE"
  | "CONTRACT_HOLD";

export interface IncidentReviewReadState {
  status: IncidentReviewReadStatus;
  value?: IncidentReviewProjection;
  retainedVerifiedValue?: IncidentReviewProjection;
  error?: OperatorApiError;
  retryable: boolean;
}

export async function readIndustrialIncidentReviewProjection(
  taskId: string,
  caseId: string,
  previous?: IncidentReviewProjection,
): Promise<IncidentReviewReadState> {
  const retained =
    previous?.task_id === taskId && previous.case_id === caseId
      ? previous
      : undefined;
  try {
    return {
      status: "VERIFIED",
      value: await getIndustrialIncidentReviewProjection(taskId, caseId),
      retryable: false,
    };
  } catch (caught: unknown) {
    const error =
      caught instanceof OperatorApiError
        ? caught
        : new OperatorApiError(
            "INCIDENT_REVIEW_READ_FAILED",
            caught instanceof Error ? caught.message : "案件评审投影读取失败",
            0,
          );
    if (error.status === 404 && retained === undefined) {
      return { status: "NOT_CREATED", error, retryable: true };
    }
    if (error.status === 404 || error.status === 409) {
      return {
        status: "STALE_HOLD",
        retainedVerifiedValue: retained,
        error,
        retryable: true,
      };
    }
    if (
      error.status === 0 ||
      error.status === 503 ||
      error.code === "NETWORK_UNAVAILABLE" ||
      error.code === "REQUEST_TIMEOUT"
    ) {
      return {
        status: "RETRYABLE_UNAVAILABLE",
        retainedVerifiedValue: retained,
        error,
        retryable: true,
      };
    }
    return {
      status: "CONTRACT_HOLD",
      retainedVerifiedValue: retained,
      error,
      retryable: true,
    };
  }
}

export async function createIndustrialIncident(
  taskId: string,
  payload: Record<string, unknown>,
  idempotencyKey: string,
  expectedGoal3HandoffSha256?: string,
): Promise<IndustrialIncident> {
  if (
    expectedGoal3HandoffSha256 !== undefined &&
    !sha256Pattern.test(expectedGoal3HandoffSha256)
  ) {
    throw new OperatorApiError(
      "INVALID_GOAL3_HANDOFF_SHA256",
      "Goal3 handoff SHA-256 格式无效",
      400,
    );
  }
  const response = await operatorFetch(
    `/v1/tasks/${encodeURIComponent(taskId)}/industrial-incidents`,
    {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
        "Idempotency-Key": idempotencyKey,
        ...(expectedGoal3HandoffSha256
          ? { "X-Goal3-Handoff-SHA256": expectedGoal3HandoffSha256 }
          : {}),
      },
      body: JSON.stringify(payload),
    },
  );
  const commandId = requireIncidentCommandId(response);
  const incident = (await response.json()) as unknown;
  if (!isIndustrialIncident(incident) || incident.task_id !== taskId) {
    throw new OperatorApiError(
      "INVALID_INCIDENT_RESPONSE",
      "新建工业案件响应未通过作用域与安全合同校验",
      502,
      commandId,
    );
  }
  requireBoundResponseSha(response, "X-Incident-Case-SHA256", incident.case_sha256);
  return incident;
}

export async function listIndustrialIncidentDecisions(
  taskId: string,
  caseId: string,
): Promise<IndustrialIncidentDecisionReceipt[]> {
  const response = await operatorFetch(
    `/v1/tasks/${encodeURIComponent(taskId)}/industrial-incidents/${encodeURIComponent(caseId)}/decisions`,
  );
  const source = await response.text();
  const payload = JSON.parse(source) as unknown;
  if (!Array.isArray(payload) || !payload.every((item) => isIncidentDecision(item, taskId, caseId))) {
    throw new OperatorApiError(
      "INVALID_INCIDENT_DECISION_RESPONSE",
      "人工决定账本未通过前端合同校验",
      502,
    );
  }
  const contentSha256 = await pythonCanonicalSha256FromJsonValue(source);
  requireBoundResponseSha(response, "X-Content-SHA256", contentSha256);
  return payload;
}

export async function recordIndustrialIncidentDecision(input: {
  taskId: string;
  caseId: string;
  boundCaseSha256: string;
  decision: IndustrialIncidentHumanDecision;
  note: string;
  selectedRemediationPlanId?: string;
  idempotencyKey: string;
}): Promise<IndustrialIncidentCommandResult<IndustrialIncidentDecisionReceipt>> {
  const response = await operatorFetch(
    `/v1/tasks/${encodeURIComponent(input.taskId)}/industrial-incidents/${encodeURIComponent(input.caseId)}/decisions`,
    {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
        "Idempotency-Key": input.idempotencyKey,
      },
      body: JSON.stringify({
        bound_case_sha256: input.boundCaseSha256,
        decision: input.decision,
        note: input.note,
        ...(input.selectedRemediationPlanId
          ? { selected_remediation_plan_id: input.selectedRemediationPlanId }
          : {}),
        operator_attests_reviewed_evidence: true,
        production_release_requested: false,
        equipment_control_requested: false,
      }),
    },
  );
  const commandId = requireIncidentCommandId(response);
  const value = (await response.json()) as unknown;
  if (!isIncidentDecision(value, input.taskId, input.caseId)) {
    throw new OperatorApiError(
      "INVALID_INCIDENT_DECISION_RESPONSE",
      "人工决定写入响应未通过前端合同校验",
      502,
      commandId,
    );
  }
  return {
    value,
    commandId,
    resourceLocation: response.headers.get("Location") ?? undefined,
    resourceSha256: requireBoundResponseSha(
      response,
      "X-Incident-Decision-SHA256",
      value.decision_sha256,
    ),
  };
}

export async function resumeIndustrialIncident(input: {
  taskId: string;
  caseId: string;
  payload: Record<string, unknown>;
  idempotencyKey: string;
}): Promise<IndustrialIncidentCommandResult<IndustrialIncident>> {
  const response = await operatorFetch(
    `/v1/tasks/${encodeURIComponent(input.taskId)}/industrial-incidents/${encodeURIComponent(input.caseId)}/resume`,
    {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
        "Idempotency-Key": input.idempotencyKey,
      },
      body: JSON.stringify(input.payload),
    },
    120_000,
  );
  const commandId = requireIncidentCommandId(response);
  const value = (await response.json()) as unknown;
  if (
    !isIndustrialIncident(value) ||
    value.task_id !== input.taskId ||
    value.parent_case_id !== input.caseId
  ) {
    throw new OperatorApiError(
      "INVALID_INCIDENT_RESUME_RESPONSE",
      "工业案件恢复响应未通过 Parent / Child 作用域校验",
      502,
      commandId,
    );
  }
  return {
    value,
    commandId,
    resourceLocation: response.headers.get("Location") ?? undefined,
    resourceSha256: requireBoundResponseSha(
      response,
      "X-Incident-Case-SHA256",
      value.case_sha256,
    ),
  };
}

// Compatibility alias for existing consumers; the implementation accepts v5 and v6.
export const listIndustrialIncidentV5 = listIndustrialIncidents;

export async function listAgentCapaLineageRecords(
  taskId: string,
): Promise<AgentCapaLineageRecord[]> {
  const response = await operatorFetch(
    `/v1/tasks/${encodeURIComponent(taskId)}/capa-cases`,
  );
  return (await response.json()) as AgentCapaLineageRecord[];
}

export async function getAgentRuntimeCapabilities(): Promise<AgentRuntimeCapabilities> {
  const response = await operatorFetch("/v1/industrial-incidents/runtime-capabilities");
  return (await response.json()) as AgentRuntimeCapabilities;
}

function providerProfilePayload(input: ProviderProfileInput): Record<string, unknown> {
  return {
    workspace_id: input.workspaceId,
    display_name: input.displayName,
    provider_kind: input.providerKind,
    base_url: input.baseUrl.trim() || null,
    model: input.model,
    ...(input.apiKey ? { api_key: input.apiKey } : {}),
    default_planner_mode: input.defaultPlannerMode,
    timeout_seconds: input.timeoutSeconds ?? 20,
    max_retries: input.maxRetries ?? 1,
    max_output_tokens: input.maxOutputTokens ?? 900,
    context_budget_tokens: input.contextBudgetTokens ?? 8192,
    make_default: input.makeDefault ?? true,
  };
}

export async function listProviderProfiles(
  workspaceId: string,
): Promise<ProviderProfileRecord[]> {
  const response = await operatorFetch(
    `/v1/provider-profiles?workspace_id=${encodeURIComponent(workspaceId)}`,
  );
  return (await response.json()) as ProviderProfileRecord[];
}

export async function testProviderConnection(
  input: ProviderProfileInput,
): Promise<ProviderConnectionTestResult> {
  const response = await operatorFetch(
    "/v1/provider-profiles/test-connection",
    {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ ...providerProfilePayload(input), make_default: false }),
    },
    125_000,
  );
  return (await response.json()) as ProviderConnectionTestResult;
}

export async function createProviderProfile(
  input: ProviderProfileInput,
): Promise<ProviderProfileRecord> {
  const response = await operatorFetch(
    "/v1/provider-profiles",
    {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(providerProfilePayload(input)),
    },
  );
  return (await response.json()) as ProviderProfileRecord;
}

export async function testSavedProviderConnection(
  profileId: string,
): Promise<ProviderConnectionTestResult> {
  const response = await operatorFetch(
    `/v1/provider-profiles/${encodeURIComponent(profileId)}/test-connection`,
    { method: "POST" },
    125_000,
  );
  return (await response.json()) as ProviderConnectionTestResult;
}

export async function setDefaultProviderProfile(
  profileId: string,
): Promise<ProviderProfileRecord> {
  const response = await operatorFetch(
    `/v1/provider-profiles/${encodeURIComponent(profileId)}/default`,
    { method: "PUT" },
  );
  return (await response.json()) as ProviderProfileRecord;
}

export async function revokeProviderProfile(
  profileId: string,
): Promise<ProviderProfileRecord> {
  const response = await operatorFetch(
    `/v1/provider-profiles/${encodeURIComponent(profileId)}`,
    { method: "DELETE" },
  );
  return (await response.json()) as ProviderProfileRecord;
}

export async function getAgentReleaseReadiness(
  taskId: string,
): Promise<AgentReleaseReadiness> {
  const response = await operatorFetch(
    `/v1/tasks/${encodeURIComponent(taskId)}/release-readiness`,
  );
  return (await response.json()) as AgentReleaseReadiness;
}

export async function listLocalTaskSources(
  workspaceId: string,
): Promise<LocalTaskSource[]> {
  const response = await operatorFetch(
    `/v1/data-sources?workspace_id=${encodeURIComponent(workspaceId)}`,
  );
  return (await response.json()) as LocalTaskSource[];
}

export async function authorizeLocalTaskSource(input: {
  workspaceId: string;
  displayName: string;
  rootPath: string;
  sourceArchiveSha256: string;
  purpose: string;
  rightsBasis: string;
}): Promise<LocalTaskSource> {
  const response = await operatorFetch("/v1/data-sources/local-authorizations", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      workspace_id: input.workspaceId,
      display_name: input.displayName,
      root_path: input.rootPath,
      source_archive_sha256: input.sourceArchiveSha256,
      adapter_kind: "omni_ad_30_release",
      purpose: input.purpose,
      rights_basis: input.rightsBasis,
      residency: "server_local_in_place",
      operator_attests_authorized_use: true,
      read_only: true,
      raw_redistribution_allowed: false,
    }),
  }, 120_000);
  return (await response.json()) as LocalTaskSource;
}

export async function authorizeOperatorProjectSnapshot(input: {
  workspaceId: string;
  projectId: string;
  displayName?: string;
}): Promise<LocalTaskSource> {
  const response = await operatorFetch(
    "/v1/data-sources/operator-project-snapshots",
    {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        workspace_id: input.workspaceId,
        project_id: input.projectId,
        display_name: input.displayName ?? "工作簿受控快照",
        operator_attests_authorized_use: true,
      }),
    },
    120_000,
  );
  return (await response.json()) as LocalTaskSource;
}

export async function listSourceAuthorizationEvents(
  sourceId: string,
): Promise<SourceAuthorizationEvent[]> {
  const response = await operatorFetch(
    `/v1/data-sources/${encodeURIComponent(sourceId)}/authorization-events`,
  );
  return (await response.json()) as SourceAuthorizationEvent[];
}

export async function revokeLocalTaskSource(input: {
  sourceId: string;
  reason: string;
  expectedLatestEventSha256: string;
}): Promise<SourceAuthorizationEvent> {
  const response = await operatorFetch(
    `/v1/data-sources/${encodeURIComponent(input.sourceId)}/revocations`,
    {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        reason: input.reason,
        expected_latest_event_sha256: input.expectedLatestEventSha256,
      }),
    },
  );
  return (await response.json()) as SourceAuthorizationEvent;
}

export async function listIndustrialShadowEvaluations(
  taskId: string,
): Promise<IndustrialShadowEvaluationReceipt[]> {
  const response = await operatorFetch(
    `/v1/tasks/${encodeURIComponent(taskId)}/industrial-shadow-evaluations`,
  );
  return (await response.json()) as IndustrialShadowEvaluationReceipt[];
}

export async function getProjectGovernanceEffectiveness(
  projectId: string,
): Promise<ProjectGovernanceEffectivenessSummary> {
  const response = await operatorFetch(
    `/v1/projects/${encodeURIComponent(projectId)}/governance-effectiveness`,
  );
  return (await response.json()) as ProjectGovernanceEffectivenessSummary;
}

export async function createIndustrialShadowEvaluation(
  taskId: string,
  input: CreateIndustrialShadowEvaluationInput,
): Promise<IndustrialShadowEvaluationReceipt> {
  const response = await operatorFetch(
    `/v1/tasks/${encodeURIComponent(taskId)}/industrial-shadow-evaluations`,
    {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(input),
    },
  );
  return (await response.json()) as IndustrialShadowEvaluationReceipt;
}

export async function listShadowEvaluationManifestsV2(
  taskId: string,
): Promise<ShadowEvaluationManifestV2[]> {
  const response = await operatorFetch(
    `/v1/tasks/${encodeURIComponent(taskId)}/industrial-shadow-evaluation-manifests`,
  );
  return (await response.json()) as ShadowEvaluationManifestV2[];
}

export async function createShadowEvaluationManifestV2(
  taskId: string,
  input: CreateShadowEvaluationManifestV2Input,
): Promise<ShadowEvaluationManifestV2> {
  const response = await operatorFetch(
    `/v1/tasks/${encodeURIComponent(taskId)}/industrial-shadow-evaluation-manifests`,
    {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(input),
    },
  );
  return (await response.json()) as ShadowEvaluationManifestV2;
}

interface ApiErrorEnvelope {
  error?: {
    code?: string;
    message?: string;
  };
}

export class OperatorApiError extends Error {
  readonly code: string;
  readonly status: number;
  readonly incidentCommandId: string | undefined;

  constructor(
    code: string,
    message: string,
    status: number,
    incidentCommandId?: string,
  ) {
    super(message);
    this.name = "OperatorApiError";
    this.code = code;
    this.status = status;
    this.incidentCommandId = incidentCommandId;
  }
}

const incidentCommandIdPattern = /^incident_command_[0-9a-f]{24}$/;

function apiEndpoint(apiBaseUrl: string, path: string): string {
  return `${apiBaseUrl}${path.startsWith("/") ? path : `/${path}`}`;
}

export async function operatorFetch(
  path: string,
  init: RequestInit = {},
  timeoutMs = 30_000,
): Promise<Response> {
  const runtime = await resolveApiRuntime();
  const controller = new AbortController();
  const timeout = window.setTimeout(() => controller.abort(), timeoutMs);
  const headers = new Headers(init.headers);
  if (!headers.has("Accept")) headers.set("Accept", "application/json");
  if (runtime.sessionToken) {
    headers.set("X-Actor-User-Id", operatorActorUserId);
    headers.set(
      runtime.desktop
        ? "X-VisionData-Desktop-Token"
        : "X-VisionData-Session-Token",
      runtime.sessionToken,
    );
  }
  try {
    const response = await fetch(apiEndpoint(runtime.apiBaseUrl, path), {
      ...init,
      headers,
      credentials: "omit",
      cache: "no-store",
      signal: controller.signal,
    });
    if (!response.ok) {
      const payload = (await response.json().catch(() => ({}))) as ApiErrorEnvelope;
      const incidentCommandId = response.headers.get("X-Incident-Command-Id")?.trim();
      throw new OperatorApiError(
        payload.error?.code ?? `HTTP_${response.status}`,
        payload.error?.message ?? "本地工作台请求失败",
        response.status,
        incidentCommandId && incidentCommandIdPattern.test(incidentCommandId)
          ? incidentCommandId
          : undefined,
      );
    }
    return response;
  } catch (caught) {
    if (caught instanceof OperatorApiError) throw caught;
    if (caught instanceof DOMException && caught.name === "AbortError") {
      throw new OperatorApiError(
        "REQUEST_TIMEOUT",
        "请求超时；写操作结果未知时必须按 Incident Command ID 对账，禁止自动重放。",
        0,
      );
    }
    // Browsers report DNS failures, connection resets, refused connections and
    // offline transitions as an untyped TypeError.  Once a POST has been
    // dispatched, none of those failures proves that the server did not commit
    // the command.  Normalize every non-HTTP transport failure so write callers
    // can retain their deterministic command id and fail closed into explicit
    // reconciliation instead of treating the request as safely failed.
    throw new OperatorApiError(
      "NETWORK_UNAVAILABLE",
      "本地 API 连接中断；若这是写操作，结果未知，必须保留原命令标识并显式对账，禁止自动重放。",
      0,
    );
  } finally {
    window.clearTimeout(timeout);
  }
}

const causalReplayStepIds = ["T0", "T1", "T2", "T3", "T4"] as const;
const causalReplayStepIdSet = new Set<string>(causalReplayStepIds);
const sha256Pattern = /^[0-9a-f]{64}$/;
const goal3HandoffStatuses = new Set([
  "WAITING_FOR_TASK_COMPLETION",
  "BLOCKED_TASK_TERMINAL",
  "BLOCKED_EVIDENCE_INTEGRITY",
  "READY_FOR_INCIDENT_INTAKE",
  "INCIDENT_CHAIN_ACTIVE",
]);

function isStringArray(value: unknown): value is string[] {
  return Array.isArray(value) && value.every((item) => typeof item === "string");
}

const hostedOperationStatuses = new Set([
  "CONFIGURED_NOT_CONNECTED",
  "CONTROLLER_CONNECTED",
  "CONTROL_PLANE_READY",
  "PROJECT_REGISTERED",
  "LEADER_INGRESS_SENT",
  "REMOTE_EXECUTION_OBSERVED",
]);
const hostedExchangeStatuses = new Set([
  "SUCCESS",
  "RECOVERED",
  "TIMEOUT",
  "HTTP_ERROR",
  "TRANSPORT_ERROR",
  "REDIRECT_BLOCKED",
  "INVALID_RESPONSE",
  "CIRCUIT_OPEN",
]);
const hostedAttemptStatuses = new Set([
  "success",
  "http_error",
  "timeout",
  "transport_error",
  "redirect_blocked",
  "invalid_response",
]);
const hostedCircuitStates = new Set(["closed", "open", "half_open"]);

function isNullableString(value: unknown): value is string | null {
  return value === null || typeof value === "string";
}

function isBooleanRecord(value: unknown): value is Record<string, boolean> {
  return isRecord(value) && Object.values(value).every((item) => typeof item === "boolean");
}

function isStringListRecord(value: unknown): value is Record<string, string[]> {
  return isRecord(value) && Object.values(value).every(isStringArray);
}

function isHostedAgentTeamsHTTPAttempt(value: unknown): boolean {
  if (!isRecord(value)) return false;
  return (
    Number.isInteger(value.attempt) &&
    Number(value.attempt) >= 1 &&
    typeof value.status === "string" &&
    hostedAttemptStatuses.has(value.status) &&
    typeof value.duration_ms === "number" &&
    Number.isFinite(value.duration_ms) &&
    value.duration_ms >= 0 &&
    typeof value.retryable === "boolean" &&
    (value.http_status === null ||
      (Number.isInteger(value.http_status) && Number(value.http_status) >= 100 && Number(value.http_status) <= 599)) &&
    isNullableString(value.error_type) &&
    typeof value.backoff_ms === "number" &&
    Number.isFinite(value.backoff_ms) &&
    value.backoff_ms >= 0
  );
}

function isHostedAgentTeamsHTTPExchangeReceipt(
  value: unknown,
): value is HostedAgentTeamsHTTPExchangeReceipt {
  if (!isRecord(value) || !Array.isArray(value.attempts)) return false;
  return (
    value.schema_version === "visiondata-gate.http-exchange.v1" &&
    typeof value.request_id === "string" &&
    value.request_id.length >= 16 &&
    value.request_id.length <= 64 &&
    typeof value.endpoint_id === "string" &&
    value.endpoint_id.length > 0 &&
    (value.endpoint_scope === "local" || value.endpoint_scope === "remote") &&
    (value.method === "GET" || value.method === "POST" || value.method === "PUT") &&
    typeof value.status === "string" &&
    hostedExchangeStatuses.has(value.status) &&
    isSha256(value.request_sha256) &&
    (value.response_sha256 === null || isSha256(value.response_sha256)) &&
    value.attempts.every(isHostedAgentTeamsHTTPAttempt) &&
    Number.isInteger(value.attempt_count) &&
    Number(value.attempt_count) === value.attempts.length &&
    Number.isInteger(value.retry_count) &&
    Number(value.retry_count) >= 0 &&
    Number(value.retry_count) <= Number(value.attempt_count) &&
    typeof value.circuit_before === "string" &&
    hostedCircuitStates.has(value.circuit_before) &&
    typeof value.circuit_after === "string" &&
    hostedCircuitStates.has(value.circuit_after) &&
    value.secrets_retained === false &&
    value.redirects_followed === false
  );
}

function isHostedWorker(value: unknown): boolean {
  return (
    isRecord(value) &&
    typeof value.name === "string" && value.name.length > 0 &&
    (value.phase === "Running" || value.phase === "UNEXPECTED") &&
    (value.role === "team_leader" || value.role === "worker" || value.role === "UNEXPECTED") &&
    typeof value.team === "string" &&
    isStringArray(value.skills) &&
    typeof value.matrix_user_id_present === "boolean" &&
    typeof value.room_id_present === "boolean"
  );
}

const hostedEvidenceKinds = new Set([
  "version",
  "team",
  "workers",
  "project",
  "matrix_ingress",
  "workflow",
]);

function isHostedEvidenceProjections(value: unknown): boolean {
  if (!isRecord(value)) return false;
  return Object.entries(value).every(([label, item]) => (
    isRecord(item) &&
    hostedEvidenceKinds.has(label) &&
    typeof item.path === "string" &&
    item.path.length > 0 &&
    isSha256(item.projection_sha256) &&
    Number.isInteger(item.projection_bytes) &&
    Number(item.projection_bytes) >= 1 &&
    isSha256(item.source_response_sha256) &&
    Number.isInteger(item.source_response_bytes) &&
    Number(item.source_response_bytes) >= 1 &&
    item.evidence_kind === label &&
    item.media_type === "application/json"
  ));
}

function isHostedWorkflowStatusCounts(value: unknown): boolean {
  if (!isRecord(value)) return false;
  const keys = [
    "pending",
    "delegated",
    "blocked",
    "revision",
    "in_progress",
    "completed",
    "other",
  ];
  return Object.keys(value).length === keys.length && keys.every((key) => (
    Number.isInteger(value[key]) && Number(value[key]) >= 0
  ));
}

function isHostedAgentTeamsReceipt(
  value: unknown,
  expected: {
    operation: HostedAgentTeamsOperation;
    sourceRunId?: string;
    approvalId?: string;
  },
): value is HostedAgentTeamsReceipt {
  if (!isRecord(value)) return false;
  const submitBindingValid = expected.operation === "submit_project"
    ? (
        value.mode === "gated" &&
        value.source_run_id === expected.sourceRunId &&
        value.approval_id === expected.approvalId &&
        isSha256(value.goal_sha256) &&
        isSha256(value.matrix_transaction_sha256)
      )
    : (
        value.source_run_id === null &&
        value.approval_id === null &&
        value.goal_sha256 === null &&
        value.matrix_transaction_sha256 === null
      );
  return (
    value.schema_version === "visiondata-gate.agentteams-hosted-receipt.v2" &&
    typeof value.observed_at === "string" &&
    !Number.isNaN(Date.parse(value.observed_at)) &&
    value.operation === expected.operation &&
    (value.status === "PASS" || value.status === "PARTIAL" || value.status === "FAIL") &&
    typeof value.operation_status === "string" &&
    hostedOperationStatuses.has(value.operation_status) &&
    value.provider_repository === "https://github.com/agentscope-ai/AgentTeams" &&
    value.provider_version === "v1.2.3" &&
    value.provider_commit === "223ddc2b8073e4c8b93bcbb15e1d717f196c04d9" &&
    value.controller_reported_version === null &&
    (value.mode === "shadow" || value.mode === "gated") &&
    typeof value.team_name === "string" &&
    value.team_name.length > 0 &&
    isStringArray(value.expected_workers) &&
    new Set(value.expected_workers).size === value.expected_workers.length &&
    Array.isArray(value.observed_workers) &&
    value.observed_workers.every(isHostedWorker) &&
    isStringListRecord(value.expected_skill_assignments) &&
    isStringListRecord(value.observed_skill_assignments) &&
    isBooleanRecord(value.checks) &&
    typeof value.controller_connected === "boolean" &&
    typeof value.team_ready === "boolean" &&
    typeof value.workers_ready === "boolean" &&
    typeof value.skill_specs_verified === "boolean" &&
    value.skill_files_verified === false &&
    value.skill_runtime_verified === false &&
    typeof value.project_registered === "boolean" &&
    typeof value.leader_ingress_sent === "boolean" &&
    typeof value.workflow_observed === "boolean" &&
    typeof value.remote_task_execution_observed === "boolean" &&
    value.matrix_assignment_verified === false &&
    value.hosted_runtime_verified === false &&
    isNullableString(value.project_id) &&
    submitBindingValid &&
    typeof value.wait_for_remote_execution === "boolean" &&
    value.leader_ingress_event_id === null &&
    (value.matrix_transaction_sha256 === null || isSha256(value.matrix_transaction_sha256)) &&
    isHostedWorkflowStatusCounts(value.workflow_status_counts) &&
    isHostedEvidenceProjections(value.evidence_projections) &&
    Array.isArray(value.transport_receipts) &&
    value.transport_receipts.every(isHostedAgentTeamsHTTPExchangeReceipt) &&
    isStringArray(value.reasons) &&
    typeof value.boundary === "string" &&
    value.boundary.length > 0 &&
    value.secrets_retained === false &&
    value.evidence_mode === "allowlisted_projection" &&
    value.exact_wire_retained === false &&
    value.opaque_remote_values_retained === false &&
    value.local_runtime_connection_status === "mapped_not_connected" &&
    isSha256(value.receipt_sha256)
  );
}

async function readHostedAgentTeamsReceipt(
  response: Response,
  expected: {
    operation: HostedAgentTeamsOperation;
    sourceRunId?: string;
    approvalId?: string;
  },
): Promise<HostedAgentTeamsReceipt> {
  const payload = await response.json() as unknown;
  if (!isHostedAgentTeamsReceipt(payload, expected)) {
    throw new OperatorApiError(
      "HOSTED_AGENTTEAMS_CONTRACT_DRIFT",
      "Hosted AgentTeams 回执未通过前端作用域与安全合同校验",
      502,
    );
  }
  requireBoundResponseSha(
    response,
    "X-Hosted-AgentTeams-Receipt-SHA256",
    payload.receipt_sha256,
  );
  const etag = response.headers
    .get("ETag")
    ?.trim()
    .replace(/^W\//, "")
    .replace(/^\"|\"$/g, "")
    .toLowerCase() ?? "";
  if (etag !== payload.receipt_sha256) {
    throw new OperatorApiError(
      "HOSTED_AGENTTEAMS_ETAG_BINDING_DRIFT",
      "Hosted AgentTeams ETag 与不可变回执摘要不一致",
      409,
    );
  }
  return payload;
}

function isTaskVisualEvidenceMeasurement(
  value: unknown,
): value is TaskVisualEvidenceMeasurement {
  return (
    isRecord(value) &&
    typeof value.source_kind === "string" &&
    typeof value.finding_id === "string" &&
    typeof value.code === "string" &&
    typeof value.tool === "string" &&
    typeof value.evidence_ref === "string" &&
    typeof value.evidence_sha256 === "string" &&
    sha256Pattern.test(value.evidence_sha256) &&
    isRecord(value.observed)
  );
}

function isTaskVisualEvidenceItem(value: unknown): value is TaskVisualEvidenceItem {
  return (
    isRecord(value) &&
    typeof value.sample_id === "string" &&
    typeof value.original_name === "string" &&
    Number.isInteger(value.width) &&
    Number(value.width) > 0 &&
    Number.isInteger(value.height) &&
    Number(value.height) > 0 &&
    typeof value.source_sha256 === "string" &&
    sha256Pattern.test(value.source_sha256) &&
    typeof value.preview_sha256 === "string" &&
    sha256Pattern.test(value.preview_sha256) &&
    Number.isInteger(value.annotation_revision) &&
    Number(value.annotation_revision) >= 0 &&
    typeof value.annotation_document_sha256 === "string" &&
    sha256Pattern.test(value.annotation_document_sha256) &&
    Number.isInteger(value.annotation_count) &&
    Number(value.annotation_count) >= 0 &&
    (value.mask_sha256 === null ||
      value.mask_sha256 === undefined ||
      (typeof value.mask_sha256 === "string" && sha256Pattern.test(value.mask_sha256))) &&
    typeof value.preview_url === "string" &&
    value.preview_url.startsWith("/v1/tasks/") &&
    (value.mask_url === null ||
      value.mask_url === undefined ||
      (typeof value.mask_url === "string" && value.mask_url.startsWith("/v1/tasks/"))) &&
    typeof value.affected === "boolean" &&
    isStringArray(value.finding_ids) &&
    isStringArray(value.issue_codes) &&
    isStringArray(value.tools) &&
    isStringArray(value.work_order_ids) &&
    Array.isArray(value.measurements) &&
    value.measurements.every(isTaskVisualEvidenceMeasurement) &&
    typeof value.item_sha256 === "string" &&
    sha256Pattern.test(value.item_sha256)
  );
}

function isTaskVisualEvidenceManifest(
  value: unknown,
): value is TaskVisualEvidenceManifest {
  return (
    isRecord(value) &&
    value.schema_version === "visiondata-gate.task-visual-evidence.v1" &&
    typeof value.task_id === "string" &&
    /^tsk_[0-9a-f]{20}$/.test(value.task_id) &&
    typeof value.workspace_id === "string" &&
    typeof value.project_id === "string" &&
    typeof value.source_id === "string" &&
    typeof value.task_request_sha256 === "string" &&
    sha256Pattern.test(value.task_request_sha256) &&
    typeof value.task_evidence_sha256 === "string" &&
    sha256Pattern.test(value.task_evidence_sha256) &&
    typeof value.source_profile_sha256 === "string" &&
    sha256Pattern.test(value.source_profile_sha256) &&
    typeof value.operator_snapshot_receipt_sha256 === "string" &&
    sha256Pattern.test(value.operator_snapshot_receipt_sha256) &&
    Number.isInteger(value.visual_count) &&
    Number.isInteger(value.affected_count) &&
    Array.isArray(value.items) &&
    value.items.length === value.visual_count &&
    value.items.every(isTaskVisualEvidenceItem) &&
    value.read_only === true &&
    value.raw_images_transmitted === false &&
    value.production_release_allowed === false &&
    typeof value.manifest_sha256 === "string" &&
    sha256Pattern.test(value.manifest_sha256) &&
    typeof value.claim_boundary === "string"
  );
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

function isGoal3HandoffReceipt(
  value: unknown,
  taskId: string,
): value is Goal3HandoffReceipt {
  if (!isRecord(value)) return false;
  const hasLatest = value.latest_case_id !== null;
  const latestValid = hasLatest
    ? (
        typeof value.latest_case_id === "string" &&
        /^incident_[0-9a-f]{20}$/.test(value.latest_case_id) &&
        isSha256(value.latest_case_sha256) &&
        Number.isInteger(value.latest_case_version) &&
        Number(value.latest_case_version) >= 1 &&
        typeof value.latest_case_status === "string" &&
        typeof value.latest_case_recommendation === "string"
      )
    : (
        value.latest_case_sha256 === null &&
        value.latest_case_version === null &&
        value.latest_case_status === null &&
        value.latest_case_recommendation === null
      );
  const intakeContractSatisfied =
    value.task_execution_status === "COMPLETED" &&
    value.task_evidence_integrity === "VERIFIED";
  const statusContractSatisfied =
    (value.handoff_status === "READY_FOR_INCIDENT_INTAKE"
      ? !hasLatest && value.incident_intake_permitted === true
      : true) &&
    (value.handoff_status === "INCIDENT_CHAIN_ACTIVE"
      ? hasLatest && value.incident_intake_permitted === true
      : true) &&
    (value.handoff_status === "WAITING_FOR_TASK_COMPLETION" ||
    value.handoff_status === "BLOCKED_TASK_TERMINAL" ||
    value.handoff_status === "BLOCKED_EVIDENCE_INTEGRITY"
      ? value.incident_intake_permitted === false
      : true);
  return (
    value.schema_version === "visiondata-gate.goal3-handoff.v1" &&
    value.task_id === taskId &&
    typeof value.workspace_id === "string" &&
    typeof value.project_id === "string" &&
    isSha256(value.task_request_sha256) &&
    typeof value.task_execution_status === "string" &&
    agentTaskStatuses.has(value.task_execution_status) &&
    (value.task_final_decision === null || typeof value.task_final_decision === "string") &&
    (value.task_evidence_sha256 === null || isSha256(value.task_evidence_sha256)) &&
    (value.task_evidence_integrity === "VERIFIED" ||
      value.task_evidence_integrity === "UNAVAILABLE" ||
      value.task_evidence_integrity === "FAILED") &&
    typeof value.source_kind === "string" &&
    projectSourceKinds.has(value.source_kind) &&
    typeof value.handoff_status === "string" &&
    goal3HandoffStatuses.has(value.handoff_status) &&
    typeof value.incident_intake_permitted === "boolean" &&
    value.incident_intake_permitted === intakeContractSatisfied &&
    Number.isInteger(value.incident_count) &&
    Number(value.incident_count) >= 0 &&
    hasLatest === (Number(value.incident_count) > 0) &&
    latestValid &&
    statusContractSatisfied &&
    value.required_input_schema === "visiondata-gate.industrial-incident-request.v3" &&
    Array.isArray(value.accepted_replay_schemas) &&
    value.accepted_replay_schemas.every((item) => (
      item === "visiondata-gate.industrial-incident-request.v1" ||
      item === "visiondata-gate.industrial-incident-request.v2"
    )) &&
    typeof value.next_action === "string" &&
    value.human_authority_required === true &&
    value.production_release_allowed === false &&
    value.machine_write_permitted === false &&
    isSha256(value.receipt_sha256) &&
    typeof value.claim_boundary === "string"
  );
}

const incidentHumanDecisions = new Set<IndustrialIncidentHumanDecision>([
  "CONTINUE_HOLD",
  "ESCALATE_INVESTIGATION",
  "SELECT_REMEDIATION_PLAN",
  "REQUEST_REVERIFICATION",
  "REJECT_RECOMMENDATION",
]);

function requireBoundResponseSha(
  response: Response,
  headerName: string,
  expectedSha256: string,
): string {
  const observed = response.headers.get(headerName)?.trim().toLowerCase() ?? "";
  const rawEtag = response.headers.get("ETag")?.trim() ?? "";
  const etagMatch = rawEtag.match(/^"([0-9a-fA-F]{64})"$/);
  const incidentCommandId = response.headers.get("X-Incident-Command-Id")?.trim();
  const preservedCommandId =
    incidentCommandId && incidentCommandIdPattern.test(incidentCommandId)
      ? incidentCommandId
      : undefined;
  if (!sha256Pattern.test(observed)) {
    throw new OperatorApiError(
      "MISSING_RESPONSE_INTEGRITY_HEADER",
      `${headerName} 缺失或不是有效 SHA-256`,
      502,
      preservedCommandId,
    );
  }
  if (observed !== expectedSha256) {
    throw new OperatorApiError(
      "RESPONSE_INTEGRITY_BINDING_DRIFT",
      `${headerName} 与响应实体中的不可变摘要不一致`,
      409,
      preservedCommandId,
    );
  }
  if (!etagMatch) {
    throw new OperatorApiError(
      "MISSING_STRONG_RESPONSE_ETAG",
      "ETag 缺失、为弱验证器或不是有效 SHA-256",
      502,
      preservedCommandId,
    );
  }
  if (etagMatch[1]?.toLowerCase() !== expectedSha256) {
    throw new OperatorApiError(
      "RESPONSE_ETAG_BINDING_DRIFT",
      "ETag 与响应实体中的不可变摘要不一致",
      409,
      preservedCommandId,
    );
  }
  return observed;
}

function requireIncidentCommandId(response: Response): string {
  const commandId = response.headers.get("X-Incident-Command-Id")?.trim() ?? "";
  if (!incidentCommandIdPattern.test(commandId)) {
    throw new OperatorApiError(
      "MISSING_INCIDENT_COMMAND_ID",
      "写操作缺少可追踪的 Incident Command ID",
      502,
    );
  }
  return commandId;
}

function isIndustrialIncidentCommandReceipt(
  value: unknown,
  taskId: string,
  commandId: string,
): value is IndustrialIncidentCommandReceipt {
  if (!isRecord(value)) return false;
  const targetCaseIdValid =
    value.target_case_id === null ||
    (typeof value.target_case_id === "string" &&
      /^incident_[0-9a-f]{20}$/.test(value.target_case_id));
  const expectedCaseShaValid =
    value.expected_case_sha256 === null ||
    (typeof value.expected_case_sha256 === "string" &&
      sha256Pattern.test(value.expected_case_sha256));
  const commonValid =
    value.schema_version === "visiondata-gate.incident-command-receipt.v1" &&
    value.command_id === commandId &&
    value.task_id === taskId &&
    ["CREATE_CASE", "RECORD_DECISION", "RESUME_CASE"].includes(String(value.operation)) &&
    targetCaseIdValid &&
    typeof value.actor_user_id === "string" &&
    value.actor_user_id.length > 0 &&
    typeof value.idempotency_key_sha256 === "string" &&
    sha256Pattern.test(value.idempotency_key_sha256) &&
    typeof value.request_sha256 === "string" &&
    sha256Pattern.test(value.request_sha256) &&
    expectedCaseShaValid &&
    typeof value.admission_sha256 === "string" &&
    sha256Pattern.test(value.admission_sha256) &&
    typeof value.admitted_at === "string" &&
    value.admitted_at.length > 0 &&
    typeof value.boundary_notice === "string" &&
    value.boundary_notice.length > 0;
  if (!commonValid) return false;

  if (value.status === "COMPLETED") {
    return (
      typeof value.terminal_sha256 === "string" &&
      sha256Pattern.test(value.terminal_sha256) &&
      (value.resource_kind === "incident_case" ||
        value.resource_kind === "incident_decision") &&
      typeof value.resource_id === "string" &&
      value.resource_id.length > 0 &&
      typeof value.resource_sha256 === "string" &&
      sha256Pattern.test(value.resource_sha256) &&
      value.error_code === null &&
      value.error_message === null &&
      typeof value.terminal_at === "string" &&
      value.terminal_at.length > 0
    );
  }
  if (value.status === "REJECTED") {
    return (
      typeof value.terminal_sha256 === "string" &&
      sha256Pattern.test(value.terminal_sha256) &&
      value.resource_kind === null &&
      value.resource_id === null &&
      value.resource_sha256 === null &&
      typeof value.error_code === "string" &&
      value.error_code.length > 0 &&
      (value.error_message === null || typeof value.error_message === "string") &&
      typeof value.terminal_at === "string" &&
      value.terminal_at.length > 0
    );
  }
  return (
    value.status === "UNCERTAIN" &&
    value.terminal_sha256 === null &&
    value.resource_kind === null &&
    value.resource_id === null &&
    value.resource_sha256 === null &&
    typeof value.error_code === "string" &&
    value.error_code.length > 0 &&
    (value.error_message === null || typeof value.error_message === "string") &&
    value.terminal_at === null
  );
}

const incidentPhaseNames = new Set(["PLAN", "ACT", "OBSERVE", "EVALUATE", "INTERRUPT"]);
const incidentPhaseStatuses = new Set(["SUCCEEDED", "FAILED", "STOPPED", "PAUSED"]);
const incidentPlanNodeTypes = new Set([
  "SEQUENCE",
  "PARALLEL",
  "FALLBACK",
  "GUARD",
  "INTERRUPT",
  "REVALIDATE",
  "WORKER",
]);
const incidentPlanNodeStatuses = new Set([
  "COMPLETED",
  "PAUSED",
  "SKIPPED",
  "FAILED",
  "BLOCKED",
]);
const incidentModelProfiles = new Set([
  "deterministic-off",
  "deepseek-chat",
  "deepseek-replay",
  "workspace-byok",
]);
const incidentPlannerModes = new Set(["off", "shadow", "gated", "replay"]);
const incidentGovernanceArtifactTypes = [
  "RUNTIME_PROFILE_BINDING",
  "SITE_PACK",
  "GOVERNED_CONTEXT",
  "CONTROL_PLANE",
] as const;

function isIncidentPhaseEventPayload(
  value: unknown,
  caseId: string,
  caseSha256: string,
): value is IncidentPhaseEvent {
  if (!isRecord(value)) return false;
  return (
    value.schema_version === "visiondata-gate.incident-phase-event.v1" &&
    /^incident_event_[0-9a-f]{20}$/.test(String(value.event_id)) &&
    value.case_id === caseId &&
    value.case_sha256 === caseSha256 &&
    Number.isInteger(value.sequence) &&
    Number(value.sequence) >= 1 &&
    Number.isInteger(value.iteration) &&
    Number(value.iteration) >= 1 &&
    typeof value.phase === "string" &&
    incidentPhaseNames.has(value.phase) &&
    typeof value.invocation_id === "string" &&
    /^(?:worker|phase)_invocation_[0-9a-f]{20}$/.test(value.invocation_id) &&
    typeof value.actor === "string" &&
    value.actor.length > 0 &&
    isSha256(value.input_sha256) &&
    isSha256(value.output_sha256) &&
    typeof value.status === "string" &&
    incidentPhaseStatuses.has(value.status) &&
    (value.error_code === null || typeof value.error_code === "string") &&
    typeof value.retryable === "boolean" &&
    (value.prev_event_sha256 === null || isSha256(value.prev_event_sha256)) &&
    isSha256(value.event_sha256)
  );
}

function isIncidentPhaseEventChain(
  value: unknown,
  caseId: string,
  caseSha256: string,
): value is IncidentPhaseEvent[] {
  if (
    !Array.isArray(value) ||
    value.length === 0 ||
    !value.every((event) => isIncidentPhaseEventPayload(event, caseId, caseSha256))
  ) {
    return false;
  }
  const chainIsContiguous = value.every((event, index) => {
    const previous = value[index - 1];
    return (
      event.sequence === index + 1 &&
      (index === 0
        ? event.prev_event_sha256 === null
        : previous !== undefined && event.prev_event_sha256 === previous.event_sha256)
    );
  });
  const observedPhases = new Set(value.map((event) => event.phase));
  return (
    chainIsContiguous &&
    ["PLAN", "ACT", "OBSERVE", "EVALUATE", "INTERRUPT"].every((phase) =>
      observedPhases.has(phase as IncidentPhaseEvent["phase"]),
    )
  );
}

function isIncidentPlanNode(value: unknown): boolean {
  if (!isRecord(value)) return false;
  return (
    typeof value.node_id === "string" &&
    /^plan_node_[0-9a-f]{20}$/.test(value.node_id) &&
    typeof value.node_type === "string" &&
    incidentPlanNodeTypes.has(value.node_type) &&
    Number.isInteger(value.sequence) &&
    Number(value.sequence) >= 1 &&
    typeof value.goal === "string" &&
    value.goal.length > 0 &&
    typeof value.selected === "boolean" &&
    typeof value.status === "string" &&
    incidentPlanNodeStatuses.has(value.status) &&
    isSha256(value.node_sha256)
  );
}

function isIncidentAuthorityState(
  value: unknown,
  caseId: string,
  caseSha256: string,
  status: "ACTIVE" | "INTERRUPTED",
): boolean {
  if (!isRecord(value)) return false;
  const allowedEffects = value.allowed_effects;
  const forbiddenEffects = value.forbidden_effects;
  return (
    value.schema_version === "visiondata-gate.incident-authority-state.v1" &&
    value.case_id === caseId &&
    value.case_sha256 === caseSha256 &&
    Number.isInteger(value.authority_epoch) &&
    Number(value.authority_epoch) >= 1 &&
    value.status === status &&
    isStringArray(allowedEffects) &&
    allowedEffects.every((effect) =>
      ["READ_CASE_EVIDENCE", "RETURN_WORKER_RECEIPT"].includes(effect),
    ) &&
    isStringArray(forbiddenEffects) &&
    ["WRITE_EQUIPMENT", "RELEASE_PRODUCTION", "APPROVE_CAPA"].every((effect) =>
      forbiddenEffects.includes(effect),
    ) &&
    isSha256(value.state_sha256)
  );
}

function isIncidentHypothesisContrast(value: unknown): boolean {
  if (!isRecord(value)) return false;
  return (
    typeof value.hypothesis_id === "string" &&
    typeof value.category === "string" &&
    typeof value.status === "string" &&
    isStringArray(value.supporting_issue_codes) &&
    isStringArray(value.contradicting_issue_codes) &&
    isStringArray(value.unresolved_evidence_refs) &&
    typeof value.next_discriminating_test === "string"
  );
}

function isIncidentActionContrast(value: unknown): boolean {
  if (!isRecord(value)) return false;
  return (
    [
      "CURRENT_RECOMMENDATION",
      "PRODUCTION_RELEASE",
      "CLOSE_AS_ROOT_CAUSE_ESTABLISHED",
      "EXECUTE_CAPA_WITHOUT_OWNER",
    ].includes(String(value.action)) &&
    ["SELECTED", "REJECTED", "DEFERRED"].includes(String(value.disposition)) &&
    typeof value.rationale === "string" &&
    value.rationale.length > 0 &&
    isStringArray(value.evidence_refs) &&
    isStringArray(value.change_conditions)
  );
}

function isIncidentControlPlane(
  value: unknown,
  caseId: string,
  caseSha256: string,
): value is IncidentControlPlaneBundle {
  if (!isRecord(value)) return false;
  const tree = value.plan_tree;
  const authority = value.authority_ledger;
  const packet = value.decision_packet;
  if (!isRecord(tree) || !isRecord(authority) || !isRecord(packet)) return false;

  const nodes = tree.nodes;
  const selectedPath = tree.selected_path_node_ids;
  if (
    tree.schema_version !== "visiondata-gate.typed-incident-plan-tree.v1" ||
    tree.case_id !== caseId ||
    tree.case_sha256 !== caseSha256 ||
    typeof tree.root_node_id !== "string" ||
    !Array.isArray(nodes) ||
    nodes.length < 7 ||
    !nodes.every(isIncidentPlanNode) ||
    !isStringArray(selectedPath) ||
    !selectedPath.every((nodeId) =>
      nodes.some((node) => isRecord(node) && node.node_id === nodeId),
    ) ||
    !nodes.some((node) => isRecord(node) && node.node_id === tree.root_node_id) ||
    !Number.isInteger(tree.dynamic_worker_budget) ||
    !Number.isInteger(tree.dynamic_workers_executed) ||
    !Number.isInteger(tree.remaining_worker_budget) ||
    Number(tree.dynamic_workers_executed) + Number(tree.remaining_worker_budget) !==
      Number(tree.dynamic_worker_budget) ||
    tree.execution_semantics !== "OBSERVED_CASE_PROJECTION_V1" ||
    !isSha256(tree.tree_sha256)
  ) {
    return false;
  }

  const initialState = authority.initial_state;
  const currentState = authority.current_state;
  const grants = authority.capability_grants;
  const acceptedReceipts = authority.accepted_receipts;
  if (
    authority.schema_version !== "visiondata-gate.incident-authority-ledger.v1" ||
    authority.case_id !== caseId ||
    authority.case_sha256 !== caseSha256 ||
    !isIncidentAuthorityState(initialState, caseId, caseSha256, "ACTIVE") ||
    !isIncidentAuthorityState(currentState, caseId, caseSha256, "INTERRUPTED") ||
    !isRecord(initialState) ||
    !isRecord(currentState) ||
    Number(currentState.authority_epoch) !== Number(initialState.authority_epoch) + 1 ||
    !Array.isArray(grants) ||
    !grants.every(
      (grant) =>
        isRecord(grant) &&
        grant.case_id === caseId &&
        grant.case_sha256 === caseSha256 &&
        grant.authority_epoch === initialState.authority_epoch &&
        grant.machine_write_permitted === false &&
        grant.production_release_permitted === false &&
        isSha256(grant.grant_sha256),
    ) ||
    !Array.isArray(acceptedReceipts) ||
    acceptedReceipts.length !== grants.length ||
    !acceptedReceipts.every(
      (receipt) =>
        isRecord(receipt) &&
        receipt.outcome === "ACCEPTED" &&
        receipt.reason_code === "AUTHORIZED_AT_EPOCH" &&
        isSha256(receipt.check_sha256),
    ) ||
    typeof authority.interrupt_reason !== "string" ||
    !isSha256(authority.ledger_sha256)
  ) {
    return false;
  }

  const selectedWorkers = packet.selected_workers;
  const hypotheses = packet.hypothesis_contrasts;
  const actionContrasts = packet.action_contrasts;
  return (
    value.schema_version === "visiondata-gate.incident-control-plane.v1" &&
    value.case_id === caseId &&
    value.case_sha256 === caseSha256 &&
    packet.schema_version === "visiondata-gate.contrastive-decision-packet.v1" &&
    packet.case_id === caseId &&
    packet.case_sha256 === caseSha256 &&
    typeof packet.current_status === "string" &&
    typeof packet.current_recommendation === "string" &&
    typeof packet.recommendation_reason === "string" &&
    isStringArray(packet.observed_facts) &&
    packet.observed_facts.length > 0 &&
    isStringArray(packet.qualified_evidence_refs) &&
    packet.qualified_evidence_refs.length > 0 &&
    isStringArray(packet.blocking_issue_codes) &&
    Array.isArray(hypotheses) &&
    hypotheses.length >= 6 &&
    hypotheses.every(isIncidentHypothesisContrast) &&
    Array.isArray(selectedWorkers) &&
    selectedWorkers.every(
      (worker) =>
        isRecord(worker) &&
        typeof worker.worker_role === "string" &&
        typeof worker.invocation_id === "string" &&
        isStringArray(worker.trigger_reason_codes) &&
        worker.trigger_reason_codes.length > 0 &&
        isSha256(worker.receipt_sha256) &&
        (worker.result === "SUCCEEDED" || worker.result === "FAILED"),
    ) &&
    Array.isArray(actionContrasts) &&
    actionContrasts.length >= 4 &&
    actionContrasts.every(isIncidentActionContrast) &&
    isStringArray(packet.missing_evidence_refs) &&
    isStringArray(packet.what_would_change_decision) &&
    packet.what_would_change_decision.length > 0 &&
    (packet.maximum_causal_claim_level === "L1_ASSOCIATED" ||
      packet.maximum_causal_claim_level === "L4_INTERVENTION_SUPPORTED") &&
    packet.root_cause_status === "NOT_ESTABLISHED" &&
    packet.production_release_allowed === false &&
    packet.machine_write_permitted === false &&
    packet.plan_tree_sha256 === tree.tree_sha256 &&
    packet.authority_ledger_sha256 === authority.ledger_sha256 &&
    isSha256(packet.packet_sha256) &&
    isSha256(value.bundle_sha256) &&
    typeof value.claim_boundary === "string"
  );
}

function isIncidentReviewWorker(value: unknown, expectedSelected: boolean): boolean {
  if (!isRecord(value)) return false;
  return (
    typeof value.worker_id === "string" &&
    typeof value.eligible === "boolean" &&
    value.selected === expectedSelected &&
    (value.rank === null || (Number.isInteger(value.rank) && Number(value.rank) >= 1)) &&
    isStringArray(value.reason_codes) &&
    value.reason_codes.length > 0 &&
    ["NONE", "WARNING", "BLOCKING"].includes(String(value.blocking_severity)) &&
    isStringArray(value.discriminated_hypothesis_ids) &&
    isStringArray(value.unresolved_evidence_refs) &&
    ["LOW", "MEDIUM", "HIGH", "UNKNOWN"].includes(
      String(value.measured_cost_bucket),
    ) &&
    isStringArray(value.exclusion_reasons) &&
    (expectedSelected ? value.eligible && value.exclusion_reasons.length === 0 : true)
  );
}

function isIndustrialQualityDecisionPacket(
  value: unknown,
  caseId: string,
  caseSha256: string,
): value is IndustrialQualityDecisionPacket {
  if (!isRecord(value)) return false;
  const evidenceIndex = value.evidence_index;
  const hypotheses = value.competing_hypotheses;
  const schemaVersion = value.schema_version;
  const requiresWorkerSelection =
    schemaVersion === "visiondata-gate.industrial-quality-decision-packet.v2" ||
    schemaVersion === "visiondata-gate.industrial-quality-decision-packet.v3";
  return (
    (schemaVersion === "visiondata-gate.industrial-quality-decision-packet.v1" ||
      requiresWorkerSelection) &&
    value.case_id === caseId &&
    value.case_sha256 === caseSha256 &&
    Number.isInteger(value.case_version) &&
    Number(value.case_version) >= 1 &&
    isSha256(value.control_plane_sha256) &&
    typeof value.disposition === "string" &&
    typeof value.recommendation === "string" &&
    typeof value.recommendation_reason === "string" &&
    value.root_cause_status === "NOT_ESTABLISHED" &&
    typeof value.named_quality_owner_id === "string" &&
    typeof value.named_quality_owner_role === "string" &&
    Array.isArray(evidenceIndex) &&
    evidenceIndex.length >= 6 &&
    evidenceIndex.every(
      (evidence) =>
        isRecord(evidence) &&
        typeof evidence.evidence_ref === "string" &&
        typeof evidence.evidence_type === "string" &&
        isSha256(evidence.evidence_sha256) &&
        typeof evidence.qualification === "string" &&
        typeof evidence.role_in_decision === "string" &&
        typeof evidence.current_case_eligible === "boolean",
    ) &&
    Array.isArray(hypotheses) &&
    hypotheses.length >= 6 &&
    hypotheses.every(isIncidentHypothesisContrast) &&
    isStringArray(value.current_evidence_gaps) &&
    isStringArray(value.unresolved_risk_codes) &&
    (!requiresWorkerSelection || isWorkerSelectionReceipt(value.worker_selection_receipt)) &&
    typeof value.child_run_status === "string" &&
    Number.isInteger(value.external_model_call_count) &&
    Number(value.external_model_call_count) >= 0 &&
    typeof value.opcua_connection_status === "string" &&
    typeof value.visionmaster_connection_status === "string" &&
    value.human_approval_required === true &&
    value.production_release_allowed === false &&
    value.machine_write_permitted === false &&
    value.direct_equipment_control_permitted === false &&
    isSha256(value.packet_sha256) &&
    typeof value.claim_boundary === "string"
  );
}

function isIncidentReviewCaseLink(value: unknown): boolean {
  if (!isRecord(value)) return false;
  return (
    typeof value.case_id === "string" &&
    /^incident_[0-9a-f]{20}$/.test(value.case_id) &&
    isSha256(value.case_sha256) &&
    Number.isInteger(value.case_version) &&
    Number(value.case_version) >= 1 &&
    typeof value.status === "string" &&
    typeof value.recommendation === "string" &&
    isNullableString(value.parent_case_id) &&
    (value.parent_case_sha256 === null || isSha256(value.parent_case_sha256)) &&
    isNullableString(value.authorizing_decision_id) &&
    (value.authorizing_decision_sha256 === null ||
      isSha256(value.authorizing_decision_sha256))
  );
}

function isIncidentReviewProjection(
  value: unknown,
  taskId: string,
  caseId: string,
): value is IncidentReviewProjection {
  if (!isRecord(value)) return false;
  const current = value.current_case;
  const parent = value.parent_case;
  const selected = value.selected_workers;
  const rejected = value.rejected_workers;
  const triggers = value.triggering_evidence;
  const hypotheses = value.competing_hypotheses;
  const children = value.child_cases;
  const decisions = value.human_decisions;
  const capas = value.capa_cases;
  const taskNodes = value.task_lineage_nodes;
  if (
    !isIncidentReviewCaseLink(current) ||
    !isRecord(current) ||
    (parent !== null && !isIncidentReviewCaseLink(parent)) ||
    !Array.isArray(selected) ||
    !Array.isArray(rejected) ||
    !Array.isArray(triggers) ||
    !Array.isArray(hypotheses) ||
    !Array.isArray(children) ||
    !Array.isArray(decisions) ||
    !Array.isArray(capas) ||
    !Array.isArray(taskNodes)
  ) {
    return false;
  }
  const workerIds = [
    ...selected.flatMap((item) =>
      isRecord(item) && typeof item.worker_id === "string" ? [item.worker_id] : [],
    ),
    ...rejected.flatMap((item) =>
      isRecord(item) && typeof item.worker_id === "string" ? [item.worker_id] : [],
    ),
  ];
  const decisionScopeCaseId = isRecord(parent) ? parent.case_id : caseId;
  const decisionScopeCaseSha256 = isRecord(parent)
    ? parent.case_sha256
    : value.case_sha256;
  const linkedCapaIds = new Set(
    decisions.flatMap((decision) =>
      isRecord(decision) && typeof decision.linked_capa_case_id === "string"
        ? [decision.linked_capa_case_id]
        : [],
    ),
  );
  return (
    value.schema_version === "visiondata-gate.incident-review-projection.v1" &&
    value.task_id === taskId &&
    value.case_id === caseId &&
    isSha256(value.case_sha256) &&
    current.case_id === caseId &&
    current.case_sha256 === value.case_sha256 &&
    value.transport_source_mode === "LIVE" &&
    (value.evidence_source_mode === "REPLAY" ||
      value.evidence_source_mode === "OFFLINE_EXPORT") &&
    value.factory_live_connection_claimed === false &&
    Number.isInteger(value.worker_budget) &&
    Number(value.worker_budget) >= 0 &&
    selected.length <= Number(value.worker_budget) &&
    selected.every((item) => isIncidentReviewWorker(item, true)) &&
    rejected.every((item) => isIncidentReviewWorker(item, false)) &&
    new Set(workerIds).size === workerIds.length &&
    triggers.length === selected.length &&
    selected.every(
      (worker) =>
        isRecord(worker) &&
        triggers.some(
          (trigger) =>
            isRecord(trigger) && trigger.worker_role === worker.worker_id,
        ),
    ) &&
    triggers.every(
      (trigger) =>
        isRecord(trigger) &&
        selected.some(
          (worker) =>
            isRecord(worker) && worker.worker_id === trigger.worker_role,
        ) &&
        typeof trigger.worker_role === "string" &&
        typeof trigger.invocation_id === "string" &&
        (trigger.status === "SUCCEEDED" || trigger.status === "FAILED") &&
        isStringArray(trigger.trigger_reason_codes) &&
        trigger.trigger_reason_codes.length > 0 &&
        isStringArray(trigger.input_evidence_sha256) &&
        trigger.input_evidence_sha256.length > 0 &&
        trigger.input_evidence_sha256.every(isSha256) &&
        isSha256(trigger.receipt_sha256),
    ) &&
    hypotheses.length >= 6 &&
    hypotheses.every(isIncidentHypothesisContrast) &&
    isStringArray(value.missing_evidence_refs) &&
    isStringArray(value.what_would_change_decision) &&
    value.what_would_change_decision.length > 0 &&
    (parent === null
      ? current.parent_case_id === null && current.parent_case_sha256 === null
      : isRecord(parent) &&
        current.parent_case_id === parent.case_id &&
        current.parent_case_sha256 === parent.case_sha256) &&
    children.every(
      (child) =>
        isIncidentReviewCaseLink(child) &&
        isRecord(child) &&
        child.parent_case_id === caseId &&
        child.parent_case_sha256 === value.case_sha256,
    ) &&
    decisions.every(
      (decision) =>
        isRecord(decision) &&
        typeof decision.decision_id === "string" &&
        decision.case_id === decisionScopeCaseId &&
        decision.case_sha256 === decisionScopeCaseSha256 &&
        typeof decision.actor_user_id === "string" &&
        typeof decision.decision === "string" &&
        isNullableString(decision.linked_capa_case_id) &&
        isSha256(decision.decision_sha256) &&
        decision.production_release_allowed === false &&
        decision.equipment_control_allowed === false,
    ) &&
    capas.every(
      (capa) =>
        isRecord(capa) &&
        typeof capa.case_id === "string" &&
        linkedCapaIds.has(capa.case_id) &&
        typeof capa.status === "string" &&
        isSha256(capa.selection_sha256) &&
        (capa.approval_binding_sha256 === null ||
          isSha256(capa.approval_binding_sha256)) &&
        isNullableString(capa.child_task_id) &&
        (capa.child_evidence_sha256 === null ||
          isSha256(capa.child_evidence_sha256)) &&
        (capa.child_lineage_report_sha256 === null ||
          isSha256(capa.child_lineage_report_sha256)) &&
        (capa.execution_receipt_sha256 === null ||
          isSha256(capa.execution_receipt_sha256)) &&
        (capa.recovery_receipt_sha256 === null ||
          isSha256(capa.recovery_receipt_sha256)) &&
        (capa.child_task_id === null
          ? capa.child_evidence_sha256 === null &&
            capa.child_lineage_report_sha256 === null &&
            capa.execution_receipt_sha256 === null
          : capa.approval_binding_sha256 !== null &&
            capa.child_evidence_sha256 !== null &&
            capa.child_lineage_report_sha256 !== null &&
            capa.execution_receipt_sha256 !== null &&
            taskNodes.some(
              (node) =>
                isRecord(node) &&
                node.task_id === capa.child_task_id &&
                node.parent_task_id === taskId &&
                node.evidence_sha256 === capa.child_evidence_sha256,
            )),
    ) &&
    isStringArray(value.missing_linked_capa_case_ids) &&
    value.missing_linked_capa_case_ids.every(
      (missingCaseId) =>
        linkedCapaIds.has(missingCaseId) &&
        !capas.some(
          (capa) => isRecord(capa) && capa.case_id === missingCaseId,
        ),
    ) &&
    capas.length + value.missing_linked_capa_case_ids.length ===
      linkedCapaIds.size &&
    taskNodes.length >= 1 &&
    taskNodes.some(
      (node) => isRecord(node) && node.task_id === taskId,
    ) &&
    taskNodes.every(
      (node) =>
        isRecord(node) &&
        typeof node.task_id === "string" &&
        isNullableString(node.parent_task_id) &&
        Number.isInteger(node.depth) &&
        Number(node.depth) >= 0 &&
        typeof node.execution_status === "string" &&
        isNullableString(node.final_decision) &&
        (node.evidence_sha256 === null || isSha256(node.evidence_sha256)),
    ) &&
    isSha256(value.task_lineage_report_sha256) &&
    isSha256(value.worker_selection_receipt_sha256) &&
    isSha256(value.agent_behavior_receipt_sha256) &&
    isSha256(value.control_plane_bundle_sha256) &&
    isSha256(value.contrastive_decision_packet_sha256) &&
    value.production_release_allowed === false &&
    value.machine_write_permitted === false &&
    isSha256(value.projection_sha256) &&
    typeof value.claim_boundary === "string"
  );
}

function isIncidentRuntimeProfileBinding(
  value: unknown,
  caseId: string,
  caseSha256: string,
): value is IncidentRuntimeProfileBinding {
  if (!isRecord(value) || !isRecord(value.profile)) return false;
  const profile = value.profile;
  const nullableDigests = [
    value.planner_config_sha256,
    value.governed_context_receipt_sha256,
    value.governed_memory_planning_input_sha256,
    value.governed_memory_retrieval_receipt_sha256,
  ];
  const profileModeIsConsistent =
    (profile.planner_mode === "off" && profile.model_profile_id === "deterministic-off") ||
    (profile.planner_mode === "replay" && profile.model_profile_id === "deepseek-replay") ||
    (["shadow", "gated"].includes(String(profile.planner_mode)) &&
      ["deepseek-chat", "workspace-byok"].includes(String(profile.model_profile_id)));
  const memoryModeIsConsistent =
    (profile.memory_mode === "off" &&
      profile.memory_top_k === 0 &&
      profile.site_profile_id === null) ||
    (profile.memory_mode === "approved_site" &&
      Number.isInteger(profile.memory_top_k) &&
      Number(profile.memory_top_k) >= 1 &&
      typeof profile.site_profile_id === "string");
  return (
    value.schema_version === "visiondata-gate.incident-runtime-profile-binding.v1" &&
    value.case_id === caseId &&
    value.case_sha256 === caseSha256 &&
    profile.schema_version === "visiondata-gate.incident-runtime-profile.v1" &&
    typeof profile.model_profile_id === "string" &&
    incidentModelProfiles.has(profile.model_profile_id) &&
    (profile.provider_profile_id === null || typeof profile.provider_profile_id === "string") &&
    typeof profile.planner_mode === "string" &&
    incidentPlannerModes.has(profile.planner_mode) &&
    profileModeIsConsistent &&
    typeof profile.temperature === "number" &&
    Number.isInteger(profile.max_output_tokens) &&
    Number.isInteger(profile.context_budget_tokens) &&
    (profile.memory_mode === "off" || profile.memory_mode === "approved_site") &&
    memoryModeIsConsistent &&
    profile.human_approval_required === true &&
    profile.structured_output_schema === "visiondata-gate.incident-model-plan.v1" &&
    isSha256(value.profile_sha256) &&
    nullableDigests.every((digest) => digest === null || isSha256(digest)) &&
    typeof value.planner_connection_status === "string" &&
    Number.isInteger(value.selected_memory_count) &&
    Number(value.selected_memory_count) >= 0 &&
    Number.isInteger(value.rejected_memory_count) &&
    Number(value.rejected_memory_count) >= 0 &&
    (value.model_context_limit === null || Number.isInteger(value.model_context_limit)) &&
    (value.context_limit_status === "NOT_APPLICABLE" ||
      value.context_limit_status === "UNVERIFIED") &&
    isSha256(value.binding_sha256) &&
    value.secrets_retained === false &&
    value.raw_images_transmitted === false &&
    value.production_decision_authority === "human_only"
  );
}

function isIncidentAuditDigest(value: unknown, expectedDomain?: string): boolean {
  if (!isRecord(value)) return false;
  return (
    value.algorithm === "sha256" &&
    value.canonicalization_profile === "rfc8785-jcs-v1" &&
    value.framing_profile === "visiondata-gate-domain-frame-v1" &&
    typeof value.hash_domain === "string" &&
    (expectedDomain === undefined || value.hash_domain === expectedDomain) &&
    isSha256(value.value)
  );
}

function isGovernedAuditEnvelope(
  value: unknown,
  expected: {
    taskId: string;
    caseId: string;
    expectedCaseSha256: string;
    expectedWorkspaceId: string;
    expectedProjectId: string;
  },
): value is GovernedAuditEnvelope {
  if (
    !isRecord(value) ||
    !isRecord(value.protocol) ||
    !isRecord(value.issuer) ||
    !isRecord(value.subject) ||
    !isRecord(value.result) ||
    !isRecord(value.signature)
  ) {
    return false;
  }
  const protocol = value.protocol;
  const issuer = value.issuer;
  const subject = value.subject;
  const result = value.result;
  const signature = value.signature;
  const phaseEvents = value.phase_events;
  const governance = value.governance;
  return (
    value.schema_version === "visiondata-gate.governed-audit-envelope.v1" &&
    protocol.protocol_id === "visiondata-gate.governed-audit-envelope.v1" &&
    protocol.digest_algorithm === "sha256" &&
    protocol.canonicalization_profile === "rfc8785-jcs-v1" &&
    protocol.framing_profile === "visiondata-gate-domain-frame-v1" &&
    issuer.issuer_type === "VISIONDATA_GATE_PRODUCT_SERVICE" &&
    issuer.workspace_id === expected.expectedWorkspaceId &&
    issuer.project_id === expected.expectedProjectId &&
    issuer.identity_assurance === "LOCAL_APPLICATION_RECORD_ONLY" &&
    subject.subject_type === "IndustrialIncidentCase" &&
    subject.case_id === expected.caseId &&
    subject.task_id === expected.taskId &&
    subject.legacy_case_sha256 === expected.expectedCaseSha256 &&
    isIncidentAuditDigest(
      subject.audit_digest,
      "visiondata-gate/industrial-incident-case/audit/v1",
    ) &&
    Array.isArray(phaseEvents) &&
    phaseEvents.length > 0 &&
    phaseEvents.every(
      (event, index) =>
        isRecord(event) &&
        event.sequence === index + 1 &&
        typeof event.event_id === "string" &&
        isSha256(event.legacy_event_sha256) &&
        isIncidentAuditDigest(
          event.audit_digest,
          "visiondata-gate/industrial-incident-phase-event/audit/v1",
        ),
    ) &&
    Array.isArray(governance) &&
    governance.length === incidentGovernanceArtifactTypes.length &&
    governance.every(
      (artifact, index) =>
        isRecord(artifact) &&
        artifact.artifact_type === incidentGovernanceArtifactTypes[index] &&
        (artifact.status === "BOUND" || artifact.status === "NOT_APPLICABLE") &&
        (artifact.status === "BOUND"
          ? isSha256(artifact.legacy_sha256) && isIncidentAuditDigest(artifact.audit_digest)
          : artifact.legacy_sha256 === null && artifact.audit_digest === null),
    ) &&
    result.schema_version === "visiondata-gate.incident-policy-contract.v1" &&
    typeof result.case_status === "string" &&
    typeof result.recommendation === "string" &&
    result.root_cause_status === "NOT_ESTABLISHED" &&
    result.human_approval_required === true &&
    result.production_release_allowed === false &&
    result.machine_write_permitted === false &&
    result.direct_equipment_control_permitted === false &&
    isIncidentAuditDigest(
      result.policy_contract_fingerprint,
      "visiondata-gate/industrial-policy-contract/audit/v1",
    ) &&
    signature.status === "NOT_CONFIGURED" &&
    signature.signature_algorithm === null &&
    signature.key_id === null &&
    signature.signature_value === null &&
    signature.trusted_timestamp === null &&
    signature.assurance_boundary ===
      "DIGEST_INTEGRITY_ONLY_NO_SIGNER_IDENTITY_OR_TRUSTED_TIME" &&
    value.claim_boundary ===
      "TAMPER_EVIDENT_DETERMINISTIC_LINEAGE_NOT_CAUSAL_PROOF_OR_CERTIFICATION" &&
    isIncidentAuditDigest(
      value.audit_root,
      "visiondata-gate/industrial-case-audit-root/v1",
    )
  );
}

function assertIncidentAuthorityCrossBindings(input: {
  phaseEvents: IncidentPhaseEvent[];
  controlPlane: IncidentControlPlaneBundle;
  decisionPacket: IndustrialQualityDecisionPacket;
  reviewProjection: IncidentReviewProjection;
  auditEnvelope: GovernedAuditEnvelope;
  runtimeProfileBinding: IncidentRuntimeProfileBinding;
  expectedStatus: string;
  expectedRecommendation: string;
}): void {
  const phaseBindingsMatch = input.auditEnvelope.phase_events.every((binding, index) => {
    const event = input.phaseEvents[index];
    return (
      event !== undefined &&
      binding.sequence === event.sequence &&
      binding.event_id === event.event_id &&
      binding.legacy_event_sha256 === event.event_sha256
    );
  });
  const controlBinding = input.auditEnvelope.governance.find(
    (artifact) => artifact.artifact_type === "CONTROL_PLANE",
  );
  const runtimeBinding = input.auditEnvelope.governance.find(
    (artifact) => artifact.artifact_type === "RUNTIME_PROFILE_BINDING",
  );
  const dispositionMatches =
    input.controlPlane.decision_packet.current_status === input.expectedStatus &&
    input.controlPlane.decision_packet.current_recommendation ===
      input.expectedRecommendation &&
    input.decisionPacket.disposition === input.expectedStatus &&
    input.decisionPacket.recommendation === input.expectedRecommendation &&
    input.auditEnvelope.result.case_status === input.expectedStatus &&
    input.auditEnvelope.result.recommendation === input.expectedRecommendation;
  if (
    input.auditEnvelope.phase_events.length !== input.phaseEvents.length ||
    !phaseBindingsMatch ||
    controlBinding?.status !== "BOUND" ||
    controlBinding.legacy_sha256 !== input.controlPlane.bundle_sha256 ||
    input.decisionPacket.control_plane_sha256 !== input.controlPlane.bundle_sha256 ||
    input.reviewProjection.control_plane_bundle_sha256 !==
      input.controlPlane.bundle_sha256 ||
    input.reviewProjection.contrastive_decision_packet_sha256 !==
      input.controlPlane.decision_packet.packet_sha256 ||
    input.reviewProjection.current_case.status !== input.expectedStatus ||
    input.reviewProjection.current_case.recommendation !==
      input.expectedRecommendation ||
    runtimeBinding?.status !== "BOUND" ||
    runtimeBinding.legacy_sha256 !== input.runtimeProfileBinding.binding_sha256 ||
    !dispositionMatches
  ) {
    throw new OperatorApiError(
      "INCIDENT_AUTHORITY_CROSS_BINDING_DRIFT",
      "Goal 3 权威回执之间的阶段、评审投影、控制平面、运行档案或裁决 SHA 绑定不一致",
      409,
    );
  }
}

function isWorkerSelectionReceipt(value: unknown): boolean {
  if (!isRecord(value)) return false;
  const candidates = value.candidates;
  const ranking = value.ranking;
  const selectedWorkerIds = value.selected_worker_ids;
  if (
    value.schema_version !== "visiondata-gate.worker-selection-receipt.v1" ||
    typeof value.policy_id !== "string" ||
    typeof value.ordering_contract !== "string" ||
    !Number.isInteger(value.worker_budget) ||
    Number(value.worker_budget) < 0 ||
    !Array.isArray(candidates) ||
    !Array.isArray(ranking) ||
    candidates.length !== ranking.length ||
    !isStringArray(selectedWorkerIds) ||
    selectedWorkerIds.length > Number(value.worker_budget) ||
    !isSha256(value.input_sha256) ||
    !isSha256(value.receipt_sha256)
  ) {
    return false;
  }
  const candidateIds = new Set<string>();
  const candidatesValid = candidates.every((candidate) => {
    if (!isRecord(candidate) || typeof candidate.worker_id !== "string") return false;
    candidateIds.add(candidate.worker_id);
    return (
      typeof candidate.eligible === "boolean" &&
      isStringArray(candidate.ineligibility_reasons) &&
      ["NONE", "WARNING", "BLOCKING"].includes(String(candidate.blocking_severity)) &&
      isStringArray(candidate.discriminated_hypothesis_ids) &&
      isStringArray(candidate.unresolved_evidence_refs) &&
      ["LOW", "MEDIUM", "HIGH", "UNKNOWN"].includes(
        String(candidate.measured_cost_bucket),
      ) &&
      (candidate.eligible
        ? candidate.ineligibility_reasons.length === 0
        : candidate.ineligibility_reasons.length > 0)
    );
  });
  if (!candidatesValid || candidateIds.size !== candidates.length) return false;
  const selectedFromRanking: string[] = [];
  const rankingValid = ranking.every((entry) => {
    if (!isRecord(entry) || typeof entry.worker_id !== "string") return false;
    if (entry.selected) selectedFromRanking.push(entry.worker_id);
    return (
      candidateIds.has(entry.worker_id) &&
      typeof entry.eligible === "boolean" &&
      typeof entry.selected === "boolean" &&
      (entry.rank === null || (Number.isInteger(entry.rank) && Number(entry.rank) >= 1)) &&
      Number.isInteger(entry.blocking_severity_rank) &&
      Number.isInteger(entry.hypothesis_discrimination_count) &&
      Number.isInteger(entry.unresolved_evidence_count) &&
      Number.isInteger(entry.measured_cost_rank) &&
      isStringArray(entry.exclusion_reasons) &&
      (entry.selected ? entry.eligible && entry.exclusion_reasons.length === 0 : true)
    );
  });
  return (
    rankingValid &&
    selectedFromRanking.length === selectedWorkerIds.length &&
    selectedFromRanking.every((workerId) => selectedWorkerIds.includes(workerId))
  );
}

function isEvidenceBeliefLedger(value: unknown): boolean {
  if (!isRecord(value)) return false;
  const snapshots = value.snapshots;
  const freshness = value.source_authorization_freshness;
  return (
    value.schema_version === "visiondata-gate.evidence-belief-ledger.v2" &&
    typeof value.case_id === "string" &&
    isSha256(value.evidence_bundle_sha256) &&
    isRecord(freshness) &&
    ["CURRENT", "STALE", "REVOKED", "UNKNOWN"].includes(
      String(freshness.freshness_status),
    ) &&
    isSha256(freshness.facts_sha256) &&
    Number.isInteger(value.hypothesis_count) &&
    Number(value.hypothesis_count) >= 0 &&
    Number.isInteger(value.evidence_edge_count) &&
    Number(value.evidence_edge_count) >= 0 &&
    Array.isArray(snapshots) &&
    snapshots.length === value.hypothesis_count &&
    snapshots.every(
      (snapshot) =>
        isRecord(snapshot) &&
        typeof snapshot.hypothesis_id === "string" &&
        isStringArray(snapshot.supporting_evidence_refs) &&
        isStringArray(snapshot.contradicting_evidence_refs) &&
        isStringArray(snapshot.unresolved_evidence_refs) &&
        snapshot.unresolved_evidence_refs.length === snapshot.unresolved_evidence_count &&
        isSha256(snapshot.snapshot_sha256),
    ) &&
    isSha256(value.ledger_sha256)
  );
}

function isIncidentEvidenceIssue(value: unknown): boolean {
  if (!isRecord(value)) return false;
  return (
    typeof value.issue_code === "string" &&
    (value.severity === "BLOCKING" || value.severity === "WARNING") &&
    typeof value.evidence_source === "string" &&
    typeof value.summary === "string" &&
    typeof value.required_evidence_or_action === "string" &&
    typeof value.worker_role === "string" &&
    typeof value.blocks_disposition === "boolean" &&
    (value.producer_type === "WORKER_RECEIPT" ||
      value.producer_type === "DETERMINISTIC_PREFLIGHT") &&
    isNullableString(value.producer_invocation_id) &&
    (value.producer_receipt_sha256 === null || isSha256(value.producer_receipt_sha256)) &&
    isStringArray(value.input_evidence_refs)
  );
}

function isIncidentWorkerReceipt(value: unknown): boolean {
  if (!isRecord(value)) return false;
  return (
    value.schema_version === "visiondata-gate.incident-worker-receipt.v1" &&
    typeof value.invocation_id === "string" &&
    Number.isInteger(value.iteration) &&
    Number(value.iteration) >= 1 &&
    typeof value.worker_role === "string" &&
    typeof value.worker_version === "string" &&
    (value.status === "SUCCEEDED" || value.status === "FAILED") &&
    Number.isInteger(value.attempt) &&
    Number(value.attempt) >= 1 &&
    isStringArray(value.trigger_reason_codes) &&
    value.trigger_reason_codes.length > 0 &&
    isStringArray(value.input_evidence_sha256) &&
    value.input_evidence_sha256.length > 0 &&
    value.input_evidence_sha256.every(isSha256) &&
    isStringArray(value.tool_contracts) &&
    value.tool_contracts.length > 0 &&
    Array.isArray(value.output_issues) &&
    value.output_issues.every(isIncidentEvidenceIssue) &&
    isStringArray(value.observations) &&
    isSha256(value.output_artifact_sha256) &&
    isNullableString(value.error_code) &&
    typeof value.retryable === "boolean" &&
    isSha256(value.receipt_sha256)
  );
}

function isIncidentAgentAction(value: unknown): boolean {
  if (!isRecord(value)) return false;
  return (
    Number.isInteger(value.sequence) &&
    Number(value.sequence) >= 1 &&
    Number.isInteger(value.iteration) &&
    Number(value.iteration) >= 1 &&
    typeof value.agent_role === "string" &&
    typeof value.action === "string" &&
    ["COMPLETED", "DISPATCHED", "PENDING_HUMAN", "STOPPED", "FAILED"].includes(
      String(value.status),
    ) &&
    typeof value.dynamic === "boolean" &&
    isStringArray(value.reason_codes) &&
    isStringArray(value.input_refs) &&
    typeof value.expected_output === "string" &&
    isStringArray(value.tool_contracts) &&
    (value.output_receipt_sha256 === null || isSha256(value.output_receipt_sha256)) &&
    value.machine_action_permitted === false
  );
}

function isIndustrialIncident(value: unknown): value is IndustrialIncident {
  if (!isRecord(value)) return false;
  const request = value.request;
  const opcuaSnapshot = isRecord(request) ? request.opcua_snapshot : undefined;
  const schemaVersion = value.schema_version;
  const requestSchema = isRecord(request) ? request.schema_version : undefined;
  return (
    (schemaVersion === "visiondata-gate.industrial-incident-case.v5" ||
      schemaVersion === "visiondata-gate.industrial-incident-case.v6") &&
    typeof value.case_id === "string" &&
    /^incident_[0-9a-f]{20}$/.test(value.case_id) &&
    typeof value.incident_root_id === "string" &&
    /^incident_[0-9a-f]{20}$/.test(value.incident_root_id) &&
    Number.isInteger(value.case_version) &&
    Number(value.case_version) >= 1 &&
    typeof value.task_id === "string" &&
    isRecord(request) &&
    (requestSchema === "visiondata-gate.industrial-incident-request.v1" ||
      requestSchema === "visiondata-gate.industrial-incident-request.v2" ||
      requestSchema === "visiondata-gate.industrial-incident-request.v3") &&
    isRecord(opcuaSnapshot) &&
    (opcuaSnapshot.source_mode === "FIXTURE_REPLAY" ||
      opcuaSnapshot.source_mode === "OFFLINE_EXPORT") &&
    request.operator_attests_inputs_authorized === true &&
    request.raw_industrial_data_redistribution_allowed === false &&
    (value.parent_case_id === null || typeof value.parent_case_id === "string") &&
    (value.parent_case_sha256 === null || isSha256(value.parent_case_sha256)) &&
    (value.authorizing_decision_id === null ||
      typeof value.authorizing_decision_id === "string") &&
    (value.authorizing_decision_sha256 === null ||
      isSha256(value.authorizing_decision_sha256)) &&
    isEvidenceBeliefLedger(value.planning_belief_ledger) &&
    isWorkerSelectionReceipt(value.worker_selection_receipt) &&
    Array.isArray(value.evidence_issues) &&
    value.evidence_issues.every(isIncidentEvidenceIssue) &&
    Array.isArray(value.agent_actions) &&
    value.agent_actions.every(isIncidentAgentAction) &&
    Array.isArray(value.worker_receipts) &&
    value.worker_receipts.every(isIncidentWorkerReceipt) &&
    Array.isArray(value.operator_questions) &&
    Array.isArray(value.linked_remediation_plan_ids) &&
    isRecord(value.decision_summary) &&
    isRecord(value.loop_control) &&
    value.human_approval_required === true &&
    value.production_release_allowed === false &&
    value.machine_write_permitted === false &&
    value.direct_equipment_control_permitted === false &&
    typeof value.evidence_bundle_sha256 === "string" &&
    sha256Pattern.test(value.evidence_bundle_sha256) &&
    typeof value.context_sha256 === "string" &&
    sha256Pattern.test(value.context_sha256) &&
    typeof value.case_sha256 === "string" &&
    sha256Pattern.test(value.case_sha256)
  );
}

function isIncidentInteractionTurn(value: unknown, sequence: number): boolean {
  if (!isRecord(value)) return false;
  return (
    value.sequence === sequence &&
    (value.actor_kind === "AGENT" || value.actor_kind === "HUMAN") &&
    typeof value.actor_id === "string" &&
    value.actor_id.length > 0 &&
    typeof value.action === "string" &&
    value.action.length > 0 &&
    Array.isArray(value.input_refs) &&
    value.input_refs.every((item) => typeof item === "string") &&
    Array.isArray(value.output_refs) &&
    value.output_refs.every((item) => typeof item === "string") &&
    value.observable_only === true
  );
}

function isIncidentQuestionResolution(value: unknown): boolean {
  if (!isRecord(value)) return false;
  return (
    typeof value.question_id === "string" &&
    /^question_[0-9a-f]{12}$/.test(value.question_id) &&
    typeof value.expected_evidence_type === "string" &&
    [
      "ANSWERED_BY_ADMITTED_EVIDENCE",
      "SATISFIED_BY_NAMED_HUMAN_DECISION",
      "REMAINS_OPEN",
    ].includes(String(value.disposition)) &&
    Array.isArray(value.supporting_refs) &&
    value.supporting_refs.every((item) => typeof item === "string") &&
    value.auto_closed_from_free_text === false
  );
}

function isIncidentInteractionReceipt(
  value: unknown,
  taskId: string,
  childCaseId: string,
): value is IncidentInteractionReceipt {
  if (!isRecord(value)) return false;
  const turns = value.turns;
  const resolutions = value.question_resolutions;
  const answered = value.answered_by_evidence_count;
  const human = value.satisfied_by_human_decision_count;
  const open = value.remaining_open_question_count;
  return (
    value.schema_version === "visiondata-gate.incident-interaction-receipt.v1" &&
    typeof value.interaction_id === "string" &&
    /^interaction_[0-9a-f]{20}$/.test(value.interaction_id) &&
    value.task_id === taskId &&
    typeof value.parent_case_id === "string" &&
    /^incident_[0-9a-f]{20}$/.test(value.parent_case_id) &&
    value.child_case_id === childCaseId &&
    /^incident_[0-9a-f]{20}$/.test(value.child_case_id) &&
    typeof value.decision_id === "string" &&
    /^incident_decision_[0-9a-f]{20}$/.test(value.decision_id) &&
    isSha256(value.parent_case_sha256) &&
    isSha256(value.decision_sha256) &&
    isSha256(value.child_case_sha256) &&
    isSha256(value.consumption_sha256) &&
    Array.isArray(turns) &&
    turns.length === 3 &&
    turns.every((turn, index) => isIncidentInteractionTurn(turn, index + 1)) &&
    Array.isArray(value.admitted_evidence_refs) &&
    value.admitted_evidence_refs.every((item) => typeof item === "string") &&
    Array.isArray(resolutions) &&
    resolutions.every(isIncidentQuestionResolution) &&
    Number.isInteger(answered) &&
    Number(answered) >= 0 &&
    Number.isInteger(human) &&
    Number(human) >= 0 &&
    Number.isInteger(open) &&
    Number(open) >= 0 &&
    Number(answered) + Number(human) + Number(open) === resolutions.length &&
    (value.interaction_status === "RESUMED_ALL_QUESTIONS_RESOLVED" ||
      value.interaction_status === "RESUMED_WITH_OPEN_QUESTIONS") &&
    (Number(open) === 0
      ? value.interaction_status === "RESUMED_ALL_QUESTIONS_RESOLVED"
      : value.interaction_status === "RESUMED_WITH_OPEN_QUESTIONS") &&
    value.multi_turn_state_transition_verified === true &&
    value.hidden_chain_of_thought_retained === false &&
    value.production_release_allowed === false &&
    value.machine_write_permitted === false &&
    isSha256(value.receipt_sha256) &&
    typeof value.claim_boundary === "string"
  );
}

function isGovernedIncidentContext(value: unknown): value is GovernedIncidentContext {
  if (!isRecord(value)) return false;
  const context = value.context;
  const receipt = value.receipt;
  const retrieval = value.retrieval_receipt;
  const planningInput = value.planning_input;
  if (!isRecord(context) || !isRecord(receipt) || !isRecord(retrieval)) return false;
  const selected = retrieval.selected;
  const rejected = retrieval.rejected;
  const channels = retrieval.channel_receipts;
  return (
    context.schema_version === "visiondata-gate.incident-advisor-context.v1" &&
    typeof context.case_id === "string" &&
    typeof context.case_sha256 === "string" &&
    sha256Pattern.test(context.case_sha256) &&
    typeof context.context_sha256 === "string" &&
    sha256Pattern.test(context.context_sha256) &&
    context.historical_memory_used_as_current_fact === false &&
    receipt.schema_version === "visiondata-gate.context-receipt.v1" &&
    typeof receipt.receipt_sha256 === "string" &&
    sha256Pattern.test(receipt.receipt_sha256) &&
    typeof receipt.memory_retrieval_receipt_sha256 === "string" &&
    receipt.memory_retrieval_receipt_sha256 === retrieval.receipt_sha256 &&
    receipt.cross_site_memory_leakage_count === 0 &&
    receipt.stale_memory_acceptance_count === 0 &&
    receipt.historical_memory_used_as_fact_count === 0 &&
    receipt.may_set_current_case_fact === false &&
    receipt.raw_prompt_retained === false &&
    receipt.raw_image_retained === false &&
    (retrieval.schema_version === "visiondata-gate.memory-retrieval-receipt.v1" ||
      retrieval.schema_version === "visiondata-gate.memory-retrieval-receipt.v2") &&
    typeof retrieval.receipt_sha256 === "string" &&
    sha256Pattern.test(retrieval.receipt_sha256) &&
    Number.isInteger(retrieval.selected_count) &&
    Number.isInteger(retrieval.rejected_count) &&
    Array.isArray(selected) &&
    selected.length === retrieval.selected_count &&
    Array.isArray(rejected) &&
    rejected.length === retrieval.rejected_count &&
    retrieval.may_set_current_case_fact === false &&
    (channels === undefined || Array.isArray(channels)) &&
    (planningInput === null ||
      (isRecord(planningInput) &&
        planningInput.schema_version === "visiondata-gate.governed-memory-planning-input.v1" &&
        planningInput.current_case_fact_authority === "none" &&
        planningInput.root_cause_authority === "none" &&
        planningInput.decision_authority === "none" &&
        planningInput.policy_judge_input === false &&
        planningInput.machine_action_permitted === false &&
        typeof planningInput.input_sha256 === "string" &&
        sha256Pattern.test(planningInput.input_sha256)))
  );
}

function isIncidentDecision(
  value: unknown,
  taskId: string,
  caseId: string,
): value is IndustrialIncidentDecisionReceipt {
  if (!isRecord(value)) return false;
  return (
    value.schema_version === "visiondata-gate.industrial-incident-decision.v1" &&
    typeof value.decision_id === "string" &&
    /^incident_decision_[0-9a-f]{20}$/.test(value.decision_id) &&
    value.task_id === taskId &&
    value.case_id === caseId &&
    typeof value.case_sha256 === "string" &&
    sha256Pattern.test(value.case_sha256) &&
    typeof value.decision === "string" &&
    incidentHumanDecisions.has(value.decision as IndustrialIncidentHumanDecision) &&
    typeof value.note === "string" &&
    typeof value.actor_user_id === "string" &&
    typeof value.decided_at === "string" &&
    value.production_release_allowed === false &&
    value.equipment_control_allowed === false &&
    typeof value.decision_sha256 === "string" &&
    sha256Pattern.test(value.decision_sha256)
  );
}

const agentTaskStatuses = new Set([
  "CREATED",
  "PLANNED",
  "RUNNING",
  "VERIFYING",
  "COMPLETED",
  "FAILED",
  "CANCELLED",
  "ARCHIVED",
]);
const projectSourceKinds = new Set([
  "synthetic_demo",
  "local_authorized_directory",
  "external_residency_reference",
]);

function isSha256(value: unknown): value is string {
  return typeof value === "string" && sha256Pattern.test(value);
}

function isAgentTaskLineageNode(value: unknown): boolean {
  if (!isRecord(value)) return false;
  return (
    typeof value.task_id === "string" &&
    isNullableString(value.parent_task_id) &&
    Number.isInteger(value.depth) &&
    Number(value.depth) >= 0 &&
    (value.relation === "initial" || value.relation === "reverification") &&
    typeof value.execution_status === "string" &&
    agentTaskStatuses.has(value.execution_status) &&
    isNullableString(value.final_decision) &&
    isSha256(value.request_sha256) &&
    (value.evidence_sha256 === null || isSha256(value.evidence_sha256)) &&
    typeof value.source_kind === "string" &&
    projectSourceKinds.has(value.source_kind) &&
    isNullableString(value.source_id) &&
    typeof value.created_at === "string" &&
    isNullableString(value.completed_at) &&
    typeof value.is_focus === "boolean"
  );
}

function isAgentTaskLineageEdge(value: unknown): boolean {
  if (!isRecord(value)) return false;
  return (
    value.schema_version === "visiondata-gate.task-lineage-edge.v1" &&
    typeof value.child_task_id === "string" &&
    typeof value.parent_task_id === "string" &&
    typeof value.root_task_id === "string" &&
    value.relation === "reverification" &&
    Number.isInteger(value.depth) &&
    Number(value.depth) >= 1 &&
    isSha256(value.parent_request_sha256) &&
    isSha256(value.parent_evidence_sha256) &&
    isSha256(value.contract_sha256) &&
    typeof value.created_by === "string" &&
    typeof value.note === "string" &&
    typeof value.created_at === "string" &&
    isSha256(value.edge_sha256)
  );
}

function isAgentTaskLineageReport(value: unknown): value is AgentTaskLineageReport {
  if (!isRecord(value)) return false;
  return (
    value.schema_version === "visiondata-gate.task-lineage.v1" &&
    typeof value.root_task_id === "string" &&
    typeof value.focus_task_id === "string" &&
    typeof value.latest_task_id === "string" &&
    isSha256(value.contract_sha256) &&
    Number.isInteger(value.node_count) &&
    Number(value.node_count) >= 1 &&
    Number.isInteger(value.edge_count) &&
    Number(value.edge_count) >= 0 &&
    Array.isArray(value.nodes) &&
    value.nodes.length >= 1 &&
    value.nodes.every(isAgentTaskLineageNode) &&
    Array.isArray(value.edges) &&
    value.edges.every(isAgentTaskLineageEdge) &&
    isSha256(value.report_sha256) &&
    typeof value.claim_boundary === "string"
  );
}

function isNullableNonNegativeInteger(value: unknown): value is number | null {
  return value === null || (Number.isInteger(value) && Number(value) >= 0);
}

function isSha256Record(value: unknown): value is Record<string, string> {
  return (
    isRecord(value) &&
    Object.values(value).every(
      (item) => typeof item === "string" && sha256Pattern.test(item),
    )
  );
}

function isCausalReplayStep(
  value: unknown,
  expectedStepId: CausalReplayStepId,
  expectedSequence: number,
): value is CausalReplayStep {
  if (!isRecord(value)) return false;
  const decision = value.decision;
  return (
    value.step_id === expectedStepId &&
    value.sequence === expectedSequence &&
    typeof value.label === "string" &&
    (value.status === "COMPLETED" || value.status === "PENDING" || value.status === "BLOCKED") &&
    typeof value.occurred === "boolean" &&
    typeof value.actor === "string" &&
    (decision === null || typeof decision === "string") &&
    isNullableNonNegativeInteger(value.finding_count) &&
    isNullableNonNegativeInteger(value.work_order_count) &&
    isNullableNonNegativeInteger(value.responsibility_closed) &&
    isNullableNonNegativeInteger(value.responsibility_open) &&
    isNullableNonNegativeInteger(value.dynamic_worker_count) &&
    isNullableNonNegativeInteger(value.regressed_atomic_finding_count) &&
    Array.isArray(value.evidence_refs) &&
    value.evidence_refs.length > 0 &&
    value.evidence_refs.every((item) => typeof item === "string") &&
    isSha256Record(value.evidence_digests) &&
    typeof value.summary === "string" &&
    value.source_scope === "SHA_VERIFIED_LOCAL_PRODUCT_EVIDENCE"
  );
}

function isCausalReplayReport(value: unknown): value is CausalReplayReport {
  if (!isRecord(value) || !Array.isArray(value.steps) || value.steps.length !== 5) {
    return false;
  }
  return (
    value.schema_version === "visiondata-gate.causal-replay.v1" &&
    typeof value.parent_task_id === "string" &&
    typeof value.capa_case_id === "string" &&
    (value.child_task_id === null || typeof value.child_task_id === "string") &&
    typeof value.current_step_id === "string" &&
    causalReplayStepIdSet.has(value.current_step_id) &&
    value.steps.every((step, index) => {
      const expectedStepId = causalReplayStepIds[index];
      return expectedStepId !== undefined && isCausalReplayStep(step, expectedStepId, index);
    }) &&
    value.read_only === true &&
    value.production_release_allowed === false &&
    typeof value.report_sha256 === "string" &&
    sha256Pattern.test(value.report_sha256) &&
    typeof value.claim_boundary === "string"
  );
}

export async function getCapaCausalReplay(
  parentTaskId: string,
  capaCaseId: string,
): Promise<CausalReplayReport> {
  const response = await operatorFetch(
    `/v1/tasks/${encodeURIComponent(parentTaskId)}/capa-cases/${encodeURIComponent(capaCaseId)}/causal-replay`,
  );
  const payload = (await response.json()) as unknown;
  if (!isCausalReplayReport(payload)) {
    throw new OperatorApiError(
      "INVALID_CAUSAL_REPLAY_RESPONSE",
      "因果回放响应未通过前端合同校验",
      502,
    );
  }
  if (payload.parent_task_id !== parentTaskId || payload.capa_case_id !== capaCaseId) {
    throw new OperatorApiError(
      "CAUSAL_REPLAY_BINDING_DRIFT",
      "因果回放与请求的 Parent Task / CAPA Case 绑定不一致",
      409,
    );
  }
  return payload;
}

export async function getTaskVisualEvidence(
  taskId: string,
): Promise<TaskVisualEvidenceManifest> {
  const response = await operatorFetch(
    `/v1/tasks/${encodeURIComponent(taskId)}/visual-evidence`,
  );
  const payload = (await response.json()) as unknown;
  if (!isTaskVisualEvidenceManifest(payload)) {
    throw new OperatorApiError(
      "INVALID_TASK_VISUAL_EVIDENCE_RESPONSE",
      "任务视觉证据响应未通过前端合同校验",
      502,
    );
  }
  if (payload.task_id !== taskId) {
    throw new OperatorApiError(
      "TASK_VISUAL_EVIDENCE_SCOPE_DRIFT",
      "任务视觉证据与请求 Task 绑定不一致",
      409,
    );
  }
  requireBoundResponseSha(
    response,
    "X-Visual-Evidence-SHA256",
    payload.manifest_sha256,
  );
  return payload;
}

async function sha256ArrayBuffer(bytes: ArrayBuffer): Promise<string> {
  if (!globalThis.crypto?.subtle) {
    throw new OperatorApiError(
      "WEB_CRYPTO_UNAVAILABLE",
      "当前浏览器无法校验视觉证据 SHA-256",
      500,
    );
  }
  const digest = await globalThis.crypto.subtle.digest("SHA-256", bytes);
  return Array.from(new Uint8Array(digest), (value) =>
    value.toString(16).padStart(2, "0"),
  ).join("");
}

async function loadTaskVisualEvidenceImage(
  url: string,
  expectedSha256: string,
  mediaType: "image/jpeg" | "image/png",
): Promise<string> {
  const response = await operatorFetch(url, {
    headers: { Accept: mediaType },
  });
  requireBoundResponseSha(response, "X-Content-SHA256", expectedSha256);
  const bytes = await response.arrayBuffer();
  const observedSha256 = await sha256ArrayBuffer(bytes);
  if (observedSha256 !== expectedSha256) {
    throw new OperatorApiError(
      "TASK_VISUAL_EVIDENCE_BYTE_DRIFT",
      "视觉证据字节 SHA-256 与冻结清单不一致",
      409,
    );
  }
  return URL.createObjectURL(new Blob([bytes], { type: mediaType }));
}

export function loadTaskVisualEvidencePreview(
  item: TaskVisualEvidenceItem,
): Promise<string> {
  return loadTaskVisualEvidenceImage(
    item.preview_url,
    item.preview_sha256,
    "image/jpeg",
  );
}

export function loadTaskVisualEvidenceMask(
  item: TaskVisualEvidenceItem,
): Promise<string | undefined> {
  if (!item.mask_url || !item.mask_sha256) return Promise.resolve(undefined);
  return loadTaskVisualEvidenceImage(item.mask_url, item.mask_sha256, "image/png");
}

export async function listOperatorImages(
  workspaceId: string,
  projectId?: string,
  includeUnassigned = false,
): Promise<OperatorImageAsset[]> {
  const query = new URLSearchParams();
  if (projectId) query.set("project_id", projectId);
  if (includeUnassigned) query.set("include_unassigned", "true");
  const suffix = query.size ? `?${query.toString()}` : "";
  const response = await operatorFetch(
    `/v1/operator-workspaces/${encodeURIComponent(workspaceId)}/assets${suffix}`,
  );
  return (await response.json()) as OperatorImageAsset[];
}

export async function uploadOperatorImages(
  workspaceId: string,
  projectId: string,
  files: File[],
): Promise<OperatorImageUploadBatch> {
  const body = new FormData();
  files.forEach((file) => body.append("files", file, file.name));
  const response = await operatorFetch(
    `/v1/operator-workspaces/${encodeURIComponent(workspaceId)}/assets?project_id=${encodeURIComponent(projectId)}`,
    { method: "POST", body },
    120_000,
  );
  return (await response.json()) as OperatorImageUploadBatch;
}

export async function loadOperatorPreview(asset: OperatorImageAsset): Promise<string> {
  const response = await operatorFetch(asset.preview_url, {
    headers: { Accept: asset.content_type },
  });
  requireBoundResponseSha(response, "X-Content-SHA256", asset.preview_sha256);
  const bytes = await response.arrayBuffer();
  const observedSha256 = await sha256ArrayBuffer(bytes);
  if (observedSha256 !== asset.preview_sha256) {
    throw new OperatorApiError(
      "OPERATOR_PREVIEW_BYTE_DRIFT",
      "工作簿预览字节 SHA-256 与资产清单不一致",
      409,
    );
  }
  return URL.createObjectURL(new Blob([bytes], { type: asset.content_type }));
}

export async function loadOperatorAnnotations(
  workspaceId: string,
  assetId: string,
): Promise<OperatorAnnotationState> {
  const response = await operatorFetch(
    `/v1/operator-workspaces/${encodeURIComponent(workspaceId)}/assets/${encodeURIComponent(assetId)}/annotations`,
  );
  return (await response.json()) as OperatorAnnotationState;
}

export async function saveOperatorAnnotations(
  workspaceId: string,
  assetId: string,
  expectedRevision: number,
  annotations: BoundingBoxAnnotation[],
): Promise<OperatorAnnotationState> {
  const response = await operatorFetch(
    `/v1/operator-workspaces/${encodeURIComponent(workspaceId)}/assets/${encodeURIComponent(assetId)}/annotations`,
    {
      method: "PUT",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ expected_revision: expectedRevision, annotations }),
    },
  );
  return (await response.json()) as OperatorAnnotationState;
}

export async function listOperatorAnalysisRuns(
  workspaceId: string,
  assetId: string,
): Promise<OperatorAnalysisRun[]> {
  const response = await operatorFetch(
    `/v1/operator-workspaces/${encodeURIComponent(workspaceId)}/assets/${encodeURIComponent(assetId)}/analysis-runs`,
  );
  return (await response.json()) as OperatorAnalysisRun[];
}

export async function createOperatorAnalysisRun(
  workspaceId: string,
  assetId: string,
): Promise<OperatorAnalysisRun> {
  const response = await operatorFetch(
    `/v1/operator-workspaces/${encodeURIComponent(workspaceId)}/assets/${encodeURIComponent(assetId)}/analysis-runs`,
    { method: "POST" },
  );
  return (await response.json()) as OperatorAnalysisRun;
}

export async function listOperatorCopilotTurns(
  workspaceId: string,
  assetId: string,
  analysisRunId: string,
): Promise<OperatorCopilotTurn[]> {
  const response = await operatorFetch(
    `/v1/operator-workspaces/${encodeURIComponent(workspaceId)}/assets/${encodeURIComponent(assetId)}/analysis-runs/${encodeURIComponent(analysisRunId)}/copilot-turns`,
  );
  return (await response.json()) as OperatorCopilotTurn[];
}

export async function createOperatorCopilotTurn(
  workspaceId: string,
  assetId: string,
  analysisRunId: string,
  question: string,
): Promise<OperatorCopilotTurn> {
  const response = await operatorFetch(
    `/v1/operator-workspaces/${encodeURIComponent(workspaceId)}/assets/${encodeURIComponent(assetId)}/analysis-runs/${encodeURIComponent(analysisRunId)}/copilot-turns`,
    {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ question }),
    },
  );
  return (await response.json()) as OperatorCopilotTurn;
}

export async function listOperatorWorkOrders(
  workspaceId: string,
  projectId?: string,
  includeUnassigned = false,
): Promise<OperatorWorkOrder[]> {
  const query = new URLSearchParams();
  if (projectId) query.set("project_id", projectId);
  if (includeUnassigned) query.set("include_unassigned", "true");
  const suffix = query.size ? `?${query.toString()}` : "";
  const response = await operatorFetch(
    `/v1/operator-workspaces/${encodeURIComponent(workspaceId)}/work-orders${suffix}`,
  );
  return (await response.json()) as OperatorWorkOrder[];
}

export async function createOperatorWorkOrder(
  workspaceId: string,
  assetId: string,
  annotationId: string,
  expectedAnnotationRevision: number,
  options: {
    assignee: string;
    note: string;
    operatorAttestsReviewedEvidence: true;
  },
): Promise<OperatorWorkOrder> {
  const response = await operatorFetch(
    `/v1/operator-workspaces/${encodeURIComponent(workspaceId)}/assets/${encodeURIComponent(assetId)}/work-orders`,
    {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        annotation_id: annotationId,
        expected_annotation_revision: expectedAnnotationRevision,
        assignee: options.assignee,
        note: options.note,
        operator_attests_reviewed_evidence:
          options.operatorAttestsReviewedEvidence,
      }),
    },
  );
  return (await response.json()) as OperatorWorkOrder;
}

export async function updateOperatorWorkOrder(
  workspaceId: string,
  workOrderId: string,
  expectedRevision: number,
  status: OperatorWorkOrderStatus,
  assignee: string,
  note: string,
  operatorAttestsReviewedEvidence: true,
  verification?: {
    annotationRevision: number;
    annotationSha256: string;
  },
): Promise<OperatorWorkOrder> {
  const response = await operatorFetch(
    `/v1/operator-workspaces/${encodeURIComponent(workspaceId)}/work-orders/${encodeURIComponent(workOrderId)}`,
    {
      method: "PUT",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        expected_revision: expectedRevision,
        status,
        assignee,
        note,
        operator_attests_reviewed_evidence: operatorAttestsReviewedEvidence,
        ...(status === "CLOSED" && verification
          ? {
              verification_annotation_revision: verification.annotationRevision,
              verification_annotation_sha256: verification.annotationSha256,
            }
          : {}),
      }),
    },
  );
  return (await response.json()) as OperatorWorkOrder;
}

export async function loadOperatorWorkOrderCrop(
  workOrder: OperatorWorkOrder,
): Promise<string> {
  const response = await operatorFetch(workOrder.crop_url, {
    headers: { Accept: "image/jpeg" },
  });
  return URL.createObjectURL(await response.blob());
}
