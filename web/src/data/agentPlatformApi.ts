import { operatorFetch, OperatorApiError } from "./api";
import { pythonCanonicalSha256FromJson } from "./capaIntegrity";

export interface AgentPlatformScope {
  workspaceId: string;
  projectId: string;
}

export interface AgentPlatformTask {
  task_id: string;
  goal: string;
  execution_status: string;
  final_decision: string | null;
  updated_at: string;
}

export interface AgentPlatformOverview {
  schema_version: "visiondata-gate.agent-platform.v1";
  workspace_id: string;
  project_id: string;
  scope: { mode: "LOCAL_WORKSPACE"; production_authentication: false };
  capabilities: Array<{
    capability_id: string;
    name: string;
    kind: "TOOL" | "RUNTIME" | "PLANNER";
    status: "REGISTERED_LOCAL" | "REQUIRES_CONFIGURATION";
    description: string;
  }>;
  providers: { configured_count: number; enabled_count: number; connection_status: "NOT_PROBED" };
  tasks: AgentPlatformTask[];
  task_count: number;
  task_limit: number;
  tasks_truncated: boolean;
  receipt_sha256: string;
}

export interface TaskExecutionRecoveryProjection {
  schema_version: "visiondata-gate.task-execution-recovery.v1";
  task_id: string;
  workspace_id: string;
  project_id: string;
  execution_status: string;
  classification: "OWNED_RUNNING" | "INTERRUPTED" | "LEGACY_UNKNOWN" | "NOT_APPLICABLE";
  can_recover: boolean;
  reason_codes: string[];
  task_snapshot_sha256: string;
  receipt_sha256: string;
}

export interface TaskExecutionRecoveryReceipt {
  schema_version: "visiondata-gate.task-execution-recovery-receipt.v1";
  task_id: string;
  workspace_id: string;
  project_id: string;
  replacement_task_id: string;
  original_snapshot_sha256: string;
  failed_task_snapshot_sha256: string;
  replacement_task_snapshot_sha256: string;
  reviewer_identity: string;
  note: string;
  recovered_by: string;
  recovered_at: string;
  requires_new_plan_approval: true;
  auto_started: false;
  receipt_sha256: string;
}

type UsageCompleteness = "COMPLETE" | "PARTIAL" | "NOT_REPORTED" | "NOT_APPLICABLE" | "UNAVAILABLE";
export interface ModelUsageRecord {
  source_kind: "TASK_CORE" | "INCIDENT_CASE" | "INCIDENT_PLANNER";
  case_id: string | null;
  case_sha256: string | null;
  source_receipt_sha256: string | null;
  transport_receipt_sha256: string | null;
  origin: "REMOTE" | "LOCAL" | "REPLAY" | "ZERO_CALLS" | "UNKNOWN";
  planner_mode: string | null;
  outcome: "NO_CALL" | "RESPONSE_RECORDED" | "TRANSPORT_FAILED" | "CIRCUIT_BLOCKED" | "UNKNOWN";
  logical_model_calls: number | null;
  transport_attempts: number | null;
  successful_responses: number | null;
  input_tokens: number | null;
  output_tokens: number | null;
  total_tokens: number | null;
  estimated_input_tokens: number | null;
  unreported_attempt_count: number;
  usage_completeness: UsageCompleteness;
  token_scope: "PROVIDER_FINAL_RESPONSE" | "PROVEN_NO_REMOTE_CALL" | "UNAVAILABLE";
}

export interface TaskModelUsageReport {
  schema_version: "visiondata-gate.task-model-usage.v1";
  task_id: string;
  workspace_id: string;
  project_id: string;
  task_request_sha256: string;
  task_evidence_sha256: string | null;
  task_trace_sha256: string | null;
  records: ModelUsageRecord[];
  summary: {
    accounting_scope: "TASK_CORE_AND_SAVED_INCIDENT_PLANNERS_REMOTE_ONLY";
    call_status: "ZERO_CALLS" | "CALLS_RECORDED" | "UNKNOWN";
    logical_model_calls: number | null;
    transport_attempts: number | null;
    successful_responses: number | null;
    local_model_calls: number | null;
    replay_receipt_count: number;
    input_tokens: number | null;
    output_tokens: number | null;
    total_tokens: number | null;
    usage_completeness: UsageCompleteness;
    unreported_receipt_count: number;
    unreported_attempt_count: number;
    pricing_status: "NOT_CONFIGURED";
    cost: null;
    currency: null;
  };
  unavailable_reasons: string[];
  includes_secrets_or_prompts: false;
  estimates_counted_as_usage: false;
  boundary_notice: string;
  receipt_sha256: string;
}

const shaPattern = /^[0-9a-f]{64}$/;

function record(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

function requireContract(value: unknown, message: string): asserts value {
  if (!value) throw new OperatorApiError("PLATFORM_CONTRACT_HOLD", message, 502);
}

function string(value: unknown): value is string {
  return typeof value === "string" && value.trim().length > 0;
}

function count(value: unknown): value is number {
  return typeof value === "number" && Number.isSafeInteger(value) && value >= 0;
}

function nullableCount(value: unknown): value is number | null {
  return value === null || count(value);
}

function nullableSha(value: unknown): value is string | null {
  return value === null || (typeof value === "string" && shaPattern.test(value));
}

const completeness = ["COMPLETE", "PARTIAL", "NOT_REPORTED", "NOT_APPLICABLE", "UNAVAILABLE"];
const usageCounters = ["logical_model_calls", "transport_attempts", "successful_responses", "input_tokens", "output_tokens", "total_tokens"];

function requireScope(value: Record<string, unknown>, scope: AgentPlatformScope, taskId?: string) {
  requireContract(value.workspace_id === scope.workspaceId && value.project_id === scope.projectId,
    "响应不属于当前工作空间和项目，已停止展示。");
  if (taskId !== undefined) requireContract(value.task_id === taskId, "响应任务身份不匹配，已停止展示。");
}

async function verifiedReceipt(response: Response, header: string): Promise<Record<string, unknown>> {
  const source = await response.text();
  let value: unknown;
  try { value = JSON.parse(source); } catch {
    throw new OperatorApiError("PLATFORM_CONTRACT_HOLD", "平台响应不是有效 JSON。", 502);
  }
  requireContract(record(value), "平台响应结构无效。");
  requireContract(typeof value.receipt_sha256 === "string" && shaPattern.test(value.receipt_sha256), "平台回执摘要缺失。");
  let computed: string;
  try { computed = await pythonCanonicalSha256FromJson(source, ["receipt_sha256"]); } catch {
    throw new OperatorApiError("PLATFORM_CONTRACT_HOLD", "平台回执无法完成规范化校验。", 502);
  }
  requireContract(computed === value.receipt_sha256, "平台回执内容与摘要不一致。");
  requireContract(response.headers.get(header)?.trim().toLowerCase() === computed, "平台响应 SHA 头与内容不一致。");
  requireContract(response.headers.get("ETag")?.trim() === `"${computed}"`, "平台响应缺少一致的强 ETag。");
  return value;
}

export async function getAgentPlatform(scope: AgentPlatformScope): Promise<AgentPlatformOverview> {
  const response = await operatorFetch(
    `/v1/workspaces/${encodeURIComponent(scope.workspaceId)}/agent-platform?project_id=${encodeURIComponent(scope.projectId)}`,
  );
  const value = await verifiedReceipt(response, "X-Agent-Platform-SHA256");
  requireScope(value, scope);
  requireContract(value.schema_version === "visiondata-gate.agent-platform.v1", "平台合同版本不匹配。");
  requireContract(record(value.scope) && value.scope.mode === "LOCAL_WORKSPACE" && value.scope.production_authentication === false,
    "本地工作空间身份边界发生变化。");
  requireContract(Array.isArray(value.capabilities), "工具能力清单缺失。");
  const capabilityIds = new Set<string>();
  for (const capability of value.capabilities) {
    requireContract(record(capability) && string(capability.capability_id) && string(capability.name)
      && typeof capability.kind === "string" && ["TOOL", "RUNTIME", "PLANNER"].includes(capability.kind)
      && typeof capability.status === "string" && ["REGISTERED_LOCAL", "REQUIRES_CONFIGURATION"].includes(capability.status)
      && typeof capability.description === "string", "工具能力结构无效。");
    requireContract(!capabilityIds.has(capability.capability_id), "工具能力身份重复。");
    capabilityIds.add(capability.capability_id);
  }
  requireContract(record(value.providers) && count(value.providers.configured_count) && count(value.providers.enabled_count)
    && value.providers.enabled_count <= value.providers.configured_count && value.providers.connection_status === "NOT_PROBED",
  "模型配置状态无效；配置不能作为连接实测。");
  requireContract(value.task_limit === 200 && count(value.task_count)
    && value.tasks_truncated === (value.task_count > value.task_limit)
    && Array.isArray(value.tasks) && value.tasks.length === Math.min(value.task_count, value.task_limit), "任务列表边界无效。");
  const taskIds = new Set<string>();
  for (const task of value.tasks) {
    requireContract(record(task) && string(task.task_id) && string(task.goal) && string(task.execution_status)
      && (task.final_decision === null || string(task.final_decision)) && string(task.updated_at), "任务摘要结构无效。");
    requireContract(!taskIds.has(task.task_id), "任务列表存在重复身份。");
    taskIds.add(task.task_id);
  }
  return value as unknown as AgentPlatformOverview;
}

export async function getTaskExecutionRecovery(scope: AgentPlatformScope, taskId: string): Promise<TaskExecutionRecoveryProjection> {
  const response = await operatorFetch(`/v1/tasks/${encodeURIComponent(taskId)}/execution-recovery`);
  const value = await verifiedReceipt(response, "X-Execution-Recovery-SHA256");
  requireScope(value, scope, taskId);
  requireContract(value.schema_version === "visiondata-gate.task-execution-recovery.v1", "执行恢复合同版本不匹配。");
  requireContract(string(value.execution_status) && typeof value.classification === "string"
    && ["OWNED_RUNNING", "INTERRUPTED", "LEGACY_UNKNOWN", "NOT_APPLICABLE"].includes(value.classification), "执行恢复状态无效。");
  requireContract(typeof value.can_recover === "boolean" && (!value.can_recover || value.classification === "INTERRUPTED"), "执行恢复权限与状态不一致。");
  requireContract(Array.isArray(value.reason_codes) && value.reason_codes.every(string), "执行恢复依据缺失。");
  requireContract(typeof value.task_snapshot_sha256 === "string" && shaPattern.test(value.task_snapshot_sha256), "执行恢复缺少任务快照绑定。");
  return value as unknown as TaskExecutionRecoveryProjection;
}

export async function recoverTaskExecution(scope: AgentPlatformScope, taskId: string, input: {
  expectedSnapshotSha256: string;
  reviewerIdentity: string;
  note: string;
  operatorAttestsRecovery: true;
}): Promise<TaskExecutionRecoveryReceipt> {
  requireContract(shaPattern.test(input.expectedSnapshotSha256) && input.reviewerIdentity.trim().length >= 2
    && input.note.trim().length >= 2 && input.operatorAttestsRecovery === true, "恢复需要当前快照、具名说明和人工确认。");
  const response = await operatorFetch(`/v1/tasks/${encodeURIComponent(taskId)}/execution-recovery`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ expected_snapshot_sha256: input.expectedSnapshotSha256,
      reviewer_identity: input.reviewerIdentity.trim(), note: input.note.trim(), operator_attests_recovery: true }),
  });
  const value = await verifiedReceipt(response, "X-Execution-Recovery-SHA256");
  requireScope(value, scope, taskId);
  requireContract(value.schema_version === "visiondata-gate.task-execution-recovery-receipt.v1", "执行恢复回执版本不匹配。");
  requireContract(value.original_snapshot_sha256 === input.expectedSnapshotSha256
    && typeof value.failed_task_snapshot_sha256 === "string" && shaPattern.test(value.failed_task_snapshot_sha256)
    && typeof value.replacement_task_snapshot_sha256 === "string" && shaPattern.test(value.replacement_task_snapshot_sha256), "恢复回执与原任务快照不匹配。");
  requireContract(string(value.replacement_task_id) && value.replacement_task_id !== taskId
    && value.requires_new_plan_approval === true && value.auto_started === false, "恢复回执未保持新任务人工审批边界。");
  requireContract(value.reviewer_identity === input.reviewerIdentity.trim() && value.note === input.note.trim()
    && string(value.recovered_by) && string(value.recovered_at), "恢复回执的具名记录不匹配。");
  return value as unknown as TaskExecutionRecoveryReceipt;
}

export async function getTaskModelUsage(scope: AgentPlatformScope, taskId: string): Promise<TaskModelUsageReport> {
  const response = await operatorFetch(`/v1/tasks/${encodeURIComponent(taskId)}/model-usage`);
  const value = await verifiedReceipt(response, "X-Model-Usage-SHA256");
  requireScope(value, scope, taskId);
  requireContract(value.schema_version === "visiondata-gate.task-model-usage.v1", "模型用量合同版本不匹配。");
  requireContract(typeof value.task_request_sha256 === "string" && shaPattern.test(value.task_request_sha256)
    && nullableSha(value.task_evidence_sha256) && nullableSha(value.task_trace_sha256), "模型用量缺少任务证据绑定。");
  requireContract(value.includes_secrets_or_prompts === false && value.estimates_counted_as_usage === false
    && typeof value.boundary_notice === "string", "模型用量隐私或估算边界无效。");
  requireContract(Array.isArray(value.unavailable_reasons) && value.unavailable_reasons.every(string), "模型用量缺失原因无效。");
  requireContract(Array.isArray(value.records), "模型调用记录缺失。");
  for (const item of value.records) {
    requireContract(record(item) && typeof item.source_kind === "string" && ["TASK_CORE", "INCIDENT_CASE", "INCIDENT_PLANNER"].includes(item.source_kind)
      && typeof item.origin === "string" && ["REMOTE", "LOCAL", "REPLAY", "ZERO_CALLS", "UNKNOWN"].includes(item.origin)
      && typeof item.outcome === "string" && ["NO_CALL", "RESPONSE_RECORDED", "TRANSPORT_FAILED", "CIRCUIT_BLOCKED", "UNKNOWN"].includes(item.outcome), "模型调用记录状态无效。");
    requireContract(usageCounters.every((key) => nullableCount(item[key])) && nullableCount(item.estimated_input_tokens)
      && count(item.unreported_attempt_count), "模型调用数值无效，未知值必须保持 null。");
    requireContract(typeof item.usage_completeness === "string" && completeness.includes(item.usage_completeness)
      && typeof item.token_scope === "string" && ["PROVIDER_FINAL_RESPONSE", "PROVEN_NO_REMOTE_CALL", "UNAVAILABLE"].includes(item.token_scope), "模型调用统计范围无效。");
    requireContract(nullableSha(item.case_sha256) && nullableSha(item.source_receipt_sha256) && nullableSha(item.transport_receipt_sha256)
      && (item.case_id === null || string(item.case_id)) && (item.planner_mode === null || string(item.planner_mode)), "模型调用来源绑定无效。");
  }
  const summary = value.summary;
  requireContract(record(summary) && summary.accounting_scope === "TASK_CORE_AND_SAVED_INCIDENT_PLANNERS_REMOTE_ONLY"
    && typeof summary.call_status === "string" && ["ZERO_CALLS", "CALLS_RECORDED", "UNKNOWN"].includes(summary.call_status), "模型用量统计范围缺失。");
  requireContract(usageCounters.every((key) => nullableCount(summary[key])) && nullableCount(summary.local_model_calls)
    && count(summary.replay_receipt_count) && count(summary.unreported_receipt_count) && count(summary.unreported_attempt_count), "模型用量数值无效。");
  requireContract(typeof summary.usage_completeness === "string" && completeness.includes(summary.usage_completeness)
    && summary.pricing_status === "NOT_CONFIGURED" && summary.cost === null && summary.currency === null, "模型用量完整性或计价边界无效。");
  return value as unknown as TaskModelUsageReport;
}
