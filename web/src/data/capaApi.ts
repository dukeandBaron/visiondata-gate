import type {
  CapaOutcomeAssessment,
  ControlledCapaCase,
  GovernedOutcomeEnvelope,
  IndustrialDeliveryReceipt,
} from "../capaDomain";
import { OperatorApiError, operatorFetch } from "./api";
import {
  governedOutcomeRootSha256,
  pythonCanonicalSha256FromJson,
  pythonCanonicalSha256FromJsonValue,
} from "./capaIntegrity";

const sha256Pattern = /^[0-9a-f]{64}$/;

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

function requireCapaContract(condition: boolean, message: string): asserts condition {
  if (!condition) {
    throw new OperatorApiError("CAPA_CONTRACT_DRIFT", message, 502);
  }
}

function requireResponseSha(response: Response, expected: string, headerName = "X-Content-SHA256") {
  const observed = response.headers.get(headerName)?.trim().toLowerCase() ?? "";
  const rawEtag = response.headers.get("ETag")?.trim() ?? "";
  const etag = rawEtag.match(/^"([0-9a-fA-F]{64})"$/)?.[1]?.toLowerCase() ?? "";
  requireCapaContract(sha256Pattern.test(observed), `${headerName} 缺失或无效`);
  requireCapaContract(observed === expected, `${headerName} 与响应工件摘要不一致`);
  requireCapaContract(sha256Pattern.test(etag), "ETag 缺失、为弱验证器或无效");
  requireCapaContract(etag === expected, "ETag 与响应工件摘要不一致");
}

async function readJsonResponse(response: Response): Promise<{ payload: unknown; source: string }> {
  const source = await response.text();
  try {
    return { payload: JSON.parse(source) as unknown, source };
  } catch {
    throw new OperatorApiError("CAPA_CONTRACT_DRIFT", "受控回执不是有效 JSON", 502);
  }
}

async function computeCanonicalSha(
  source: string,
  omittedTopLevelKeys: readonly string[] = [],
): Promise<string> {
  try {
    return await pythonCanonicalSha256FromJson(source, omittedTopLevelKeys);
  } catch (error) {
    const detail = error instanceof Error ? error.message : "canonical JSON 校验失败";
    throw new OperatorApiError("CAPA_CONTRACT_DRIFT", detail, 502);
  }
}

async function computeOutcomeRoot(value: unknown): Promise<string> {
  try {
    return await governedOutcomeRootSha256(value);
  } catch (error) {
    const detail = error instanceof Error ? error.message : "Outcome Root 校验失败";
    throw new OperatorApiError("CAPA_CONTRACT_DRIFT", detail, 502);
  }
}

function validateIndustrialDelivery(value: unknown, taskId: string): IndustrialDeliveryReceipt {
  requireCapaContract(isRecord(value), "工业交付回执不是对象");
  requireCapaContract(
    value.schema_version === "visiondata-gate.industrial-delivery.v3",
    "工业交付回执必须是 v3",
  );
  requireCapaContract(value.task_id === taskId, "工业交付回执 task 作用域不一致");
  requireCapaContract(Array.isArray(value.multi_source_fusion) && value.multi_source_fusion.length >= 6, "六源融合证据不完整");
  requireCapaContract(Array.isArray(value.evidence_fusion_matrix), "证据融合矩阵缺失");
  requireCapaContract(Array.isArray(value.risk_clusters), "风险簇缺失");
  requireCapaContract(Array.isArray(value.executable_work_orders), "可执行工单缺失");
  requireCapaContract(Array.isArray(value.remediation_plans) && value.remediation_plans.length >= 1, "整改方案缺失");
  requireCapaContract(value.autonomy_level === "L2_recommendation_only", "Agent 自主权边界漂移");
  requireCapaContract(value.production_human_approval_required === true, "生产人工闸门缺失");
  requireCapaContract(value.production_approval_status === "pending", "前端不得展示生产已放行");
  for (const plan of value.remediation_plans) {
    requireCapaContract(isRecord(plan), "整改方案结构无效");
    requireCapaContract(typeof plan.plan_id === "string" && plan.plan_id.length > 0, "整改方案 ID 缺失");
    requireCapaContract(typeof plan.plan_sha256 === "string" && sha256Pattern.test(plan.plan_sha256), "整改方案 SHA 无效");
    requireCapaContract(plan.production_release_allowed === false, "整改方案越权声明生产放行");
    requireCapaContract(plan.same_contract_child_run_required === true, "整改方案缺少同合同复验约束");
  }
  return value as unknown as IndustrialDeliveryReceipt;
}

function validateOutcomeAssessment(value: unknown, taskId: string, caseId: string): CapaOutcomeAssessment {
  requireCapaContract(isRecord(value), "CAPA Outcome 不是对象");
  requireCapaContract(value.schema_version === "visiondata-gate.capa-outcome-assessment.v1", "CAPA Outcome schema 漂移");
  requireCapaContract(value.parent_task_id === taskId && value.case_id === caseId, "CAPA Outcome 作用域不一致");
  requireCapaContract(typeof value.assessment_sha256 === "string" && sha256Pattern.test(value.assessment_sha256), "CAPA Outcome SHA 无效");
  requireCapaContract(Array.isArray(value.plan_observations) && value.plan_observations.length > 0, "CAPA Outcome 缺少方案观测");
  for (const observation of value.plan_observations) {
    requireCapaContract(isRecord(observation) && observation.production_release_allowed === false, "方案观测越权声明生产放行");
  }
  return value as unknown as CapaOutcomeAssessment;
}

function validateGovernedOutcome(value: unknown, taskId: string, caseId: string): GovernedOutcomeEnvelope {
  requireCapaContract(isRecord(value), "Governed Outcome 不是对象");
  requireCapaContract(value.schema_version === "visiondata-gate.governed-outcome-envelope.v1", "Governed Outcome schema 漂移");
  requireCapaContract(isRecord(value.subject) && value.subject.parent_task_id === taskId && value.subject.capa_case_id === caseId, "Governed Outcome 作用域不一致");
  requireCapaContract(isRecord(value.result), "Governed Outcome 结果边界缺失");
  requireCapaContract(value.result.production_release_allowed === false, "Governed Outcome 越权声明生产放行");
  requireCapaContract(value.result.machine_write_permitted === false, "Governed Outcome 越权声明设备写入");
  requireCapaContract(isRecord(value.outcome_root) && typeof value.outcome_root.value === "string" && sha256Pattern.test(value.outcome_root.value), "Outcome Root 无效");
  requireCapaContract(value.outcome_root.algorithm === "sha256", "Outcome Root 算法漂移");
  requireCapaContract(value.outcome_root.canonicalization_profile === "rfc8785-jcs-v1", "Outcome Root canonicalization 漂移");
  requireCapaContract(value.outcome_root.framing_profile === "visiondata-gate-outcome-domain-frame-v1", "Outcome Root framing 漂移");
  requireCapaContract(value.outcome_root.hash_domain === "visiondata-gate/outcome/root/v1", "Outcome Root domain 漂移");
  return value as unknown as GovernedOutcomeEnvelope;
}

const controlledCapaStatuses = new Set([
  "SELECTED",
  "APPROVED",
  "DERIVED_VERSION_READY",
  "CHILD_RUN_COMPLETED",
  "RECOVERED_TO_HUMAN_REVIEW",
  "STILL_BLOCKED",
  "TRANSFERRED_TO_INVESTIGATION",
]);

function validateControlledCapaCase(
  value: unknown,
  taskId: string,
  expectedCaseId?: string,
): ControlledCapaCase {
  requireCapaContract(isRecord(value), "CAPA Case 不是对象");
  requireCapaContract(value.schema_version === "visiondata-gate.capa-case.v1", "CAPA Case schema 漂移");
  requireCapaContract(typeof value.case_id === "string", "CAPA Case ID 缺失");
  requireCapaContract(value.parent_task_id === taskId, "CAPA Case Parent Task 作用域不一致");
  if (expectedCaseId !== undefined) {
    requireCapaContract(value.case_id === expectedCaseId, "CAPA Case 深链接绑定不一致");
  }
  requireCapaContract(typeof value.status === "string" && controlledCapaStatuses.has(value.status), "CAPA Case 状态无效");
  requireCapaContract(isRecord(value.selection), "CAPA Selection 缺失");
  requireCapaContract(value.selection.case_id === value.case_id && value.selection.parent_task_id === taskId, "CAPA Selection 作用域不一致");
  requireCapaContract(typeof value.selection.selection_sha256 === "string" && sha256Pattern.test(value.selection.selection_sha256), "CAPA Selection SHA 无效");
  requireCapaContract(isRecord(value.selection.plan), "CAPA Plan 缺失");
  requireCapaContract(value.selection.plan.production_release_allowed === false, "CAPA Plan 越权声明生产放行");
  requireCapaContract(value.selection.plan.same_contract_child_run_required === true, "CAPA Plan 缺少同合同 Child Run");
  requireCapaContract(isRecord(value.initial_queue), "CAPA 初始责任队列缺失");
  requireCapaContract(value.initial_queue.case_id === value.case_id && value.initial_queue.parent_task_id === taskId, "CAPA 初始责任队列作用域不一致");
  requireCapaContract(typeof value.initial_queue.queue_sha256 === "string" && sha256Pattern.test(value.initial_queue.queue_sha256), "CAPA 初始责任队列 SHA 无效");
  if (value.approval !== null) {
    requireCapaContract(isRecord(value.approval), "CAPA Approval 无效");
    requireCapaContract(value.approval.case_id === value.case_id && value.approval.parent_task_id === taskId, "CAPA Approval 作用域不一致");
    requireCapaContract(value.approval.operator_attests_derived_processing === true, "CAPA Approval 缺少具名确认");
    requireCapaContract(value.approval.source_mutation_permitted === false, "CAPA Approval 越权允许源数据修改");
    requireCapaContract(typeof value.approval.binding_sha256 === "string" && sha256Pattern.test(value.approval.binding_sha256), "CAPA Approval SHA 无效");
  }
  if (value.execution !== null) {
    requireCapaContract(isRecord(value.execution), "CAPA Execution 无效");
    requireCapaContract(value.execution.case_id === value.case_id && value.execution.parent_task_id === taskId, "CAPA Execution 作用域不一致");
    requireCapaContract(value.execution.parent_immutable === true, "CAPA Execution 未保持 Parent 不可变");
    requireCapaContract(typeof value.execution.child_task_id === "string", "CAPA Execution 缺少 Child Task");
    requireCapaContract(typeof value.execution.receipt_sha256 === "string" && sha256Pattern.test(value.execution.receipt_sha256), "CAPA Execution SHA 无效");
  }
  if (value.recovery !== null) {
    requireCapaContract(isRecord(value.recovery), "CAPA Recovery 无效");
    requireCapaContract(value.recovery.case_id === value.case_id && value.recovery.parent_task_id === taskId, "CAPA Recovery 作用域不一致");
    requireCapaContract(value.recovery.production_release_allowed === false, "CAPA Recovery 越权声明生产放行");
    requireCapaContract(typeof value.recovery.receipt_sha256 === "string" && sha256Pattern.test(value.recovery.receipt_sha256), "CAPA Recovery SHA 无效");
  }
  return value as unknown as ControlledCapaCase;
}

async function readControlledCapaResponse(
  response: Response,
  taskId: string,
  caseId?: string,
): Promise<ControlledCapaCase> {
  const body = await readJsonResponse(response);
  const payload = validateControlledCapaCase(body.payload, taskId, caseId);
  const contentSha256 = await computeCanonicalSha(body.source);
  requireResponseSha(response, contentSha256);
  return payload;
}

export async function listControlledCapaCases(taskId: string): Promise<ControlledCapaCase[]> {
  const response = await operatorFetch(
    `/v1/tasks/${encodeURIComponent(taskId)}/capa-cases`,
  );
  const source = await response.text();
  let value: unknown;
  try {
    value = JSON.parse(source) as unknown;
  } catch {
    throw new OperatorApiError("CAPA_CONTRACT_DRIFT", "CAPA Case 列表不是有效 JSON", 502);
  }
  requireCapaContract(Array.isArray(value), "CAPA Case 列表不是数组");
  const payload = value.map((item) => validateControlledCapaCase(item, taskId));
  const contentSha256 = await pythonCanonicalSha256FromJsonValue(source);
  requireResponseSha(response, contentSha256);
  return payload;
}

export async function getControlledCapaCase(
  taskId: string,
  caseId: string,
): Promise<ControlledCapaCase> {
  const response = await operatorFetch(
    `/v1/tasks/${encodeURIComponent(taskId)}/capa-cases/${encodeURIComponent(caseId)}`,
  );
  return readControlledCapaResponse(response, taskId, caseId);
}

export type ControlledCapaReadStatus =
  | "VERIFIED"
  | "NOT_CREATED"
  | "STALE_HOLD"
  | "RETRYABLE_UNAVAILABLE"
  | "CONTRACT_HOLD";

export interface ControlledCapaReadState {
  status: ControlledCapaReadStatus;
  value?: ControlledCapaCase;
  retainedVerifiedValue?: ControlledCapaCase;
  error?: OperatorApiError;
  retryable: boolean;
}

export async function readControlledCapaCase(
  taskId: string,
  caseId: string,
  previous?: ControlledCapaCase,
): Promise<ControlledCapaReadState> {
  const retained =
    previous?.parent_task_id === taskId && previous.case_id === caseId
      ? previous
      : undefined;
  try {
    return {
      status: "VERIFIED",
      value: await getControlledCapaCase(taskId, caseId),
      retryable: false,
    };
  } catch (caught: unknown) {
    const error =
      caught instanceof OperatorApiError
        ? caught
        : new OperatorApiError(
            "CAPA_READ_FAILED",
            caught instanceof Error ? caught.message : "CAPA Case 读取失败",
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

export async function getIndustrialDelivery(taskId: string): Promise<IndustrialDeliveryReceipt> {
  const response = await operatorFetch(
    `/v1/tasks/${encodeURIComponent(taskId)}/industrial-delivery`,
  );
  const body = await readJsonResponse(response);
  const payload = validateIndustrialDelivery(body.payload, taskId);
  const contentSha = await computeCanonicalSha(body.source);
  requireResponseSha(response, contentSha);
  return payload;
}

export async function selectControlledCapaPlan(input: {
  taskId: string;
  planId: string;
  planSha256: string;
  note: string;
  idempotencyKey: string;
}): Promise<ControlledCapaCase> {
  const response = await operatorFetch(
    `/v1/tasks/${encodeURIComponent(input.taskId)}/capa-cases`,
    {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        plan_id: input.planId,
        plan_sha256: input.planSha256,
        note: input.note,
        idempotency_key: input.idempotencyKey,
      }),
    },
  );
  return readControlledCapaResponse(response, input.taskId);
}

export async function getCapaOutcomeAssessment(
  taskId: string,
  caseId: string,
): Promise<CapaOutcomeAssessment> {
  const response = await operatorFetch(
    `/v1/tasks/${encodeURIComponent(taskId)}/capa-cases/${encodeURIComponent(caseId)}/outcome-assessment`,
  );
  const body = await readJsonResponse(response);
  const payload = validateOutcomeAssessment(body.payload, taskId, caseId);
  const computedSha = await computeCanonicalSha(body.source, ["assessment_sha256"]);
  requireCapaContract(computedSha === payload.assessment_sha256, "CAPA Outcome payload SHA 与内嵌摘要不一致");
  requireResponseSha(response, computedSha);
  return payload;
}

export async function getGovernedOutcomeEnvelope(
  taskId: string,
  caseId: string,
): Promise<GovernedOutcomeEnvelope> {
  const response = await operatorFetch(
    `/v1/tasks/${encodeURIComponent(taskId)}/capa-cases/${encodeURIComponent(caseId)}/governed-outcome-envelope`,
  );
  const body = await readJsonResponse(response);
  const payload = validateGovernedOutcome(body.payload, taskId, caseId);
  const computedRoot = await computeOutcomeRoot(body.payload);
  requireCapaContract(computedRoot === payload.outcome_root.value, "Governed Outcome payload 与 Outcome Root 不一致");
  requireResponseSha(response, computedRoot);
  return payload;
}

export async function approveControlledCapaCase(
  taskId: string,
  caseId: string,
  note: string,
  approvedWorkOrderIds: string[],
): Promise<ControlledCapaCase> {
  const response = await operatorFetch(
    `/v1/tasks/${encodeURIComponent(taskId)}/capa-cases/${encodeURIComponent(caseId)}/approval`,
    {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        note,
        approved_work_order_ids: approvedWorkOrderIds,
        operator_attests_derived_processing: true,
        source_mutation_permitted: false,
        raw_redistribution_allowed: false,
        max_copied_images: 240,
      }),
    },
  );
  return readControlledCapaResponse(response, taskId, caseId);
}

export async function executeControlledCapaCase(
  taskId: string,
  caseId: string,
  reviewerIdentity: string,
  note: string,
  expectedApprovalBindingSha256: string,
): Promise<ControlledCapaCase> {
  const response = await operatorFetch(
    `/v1/tasks/${encodeURIComponent(taskId)}/capa-cases/${encodeURIComponent(caseId)}/execute`,
    {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        reviewer_identity: reviewerIdentity,
        note,
        expected_approval_binding_sha256: expectedApprovalBindingSha256,
        operator_attests_derived_processing: true,
        source_mutation_permitted: false,
        raw_redistribution_allowed: false,
      }),
    },
  );
  return readControlledCapaResponse(response, taskId, caseId);
}
