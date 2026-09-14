import { operatorFetch, OperatorApiError } from './api';
import {
  LearningContractError, validateCreateLearningRequest, validateRoundLearningRequest,
  validateCycleLearningRequest, validateFeedbackLearningRequest, validateSelectionLearningRequest,
  validateLearningCycle, validateLearningRun, validateLearningReadiness, validateLearningOperation, validateFeedbackFollowupRequest,
} from '../learningDomain.ts';
import type {
  LearningScope, LearningCycle, LearningRun, CreateLearningRequest, RoundLearningRequest,
  CycleLearningRequest, FeedbackLearningRequest, SelectionLearningRequest, LearningReadiness, LearningOperation, LearningOperationName, FeedbackFollowupRequest,
} from '../learningDomain.ts';

/** No retry, background polling, training defaults, or automatic authorization lives here. */
async function contract<T>(operation: () => Promise<T> | T): Promise<T> {
  try { return await operation(); }
  catch (error) {
    if (error instanceof LearningContractError || error instanceof SyntaxError) {
      throw new OperatorApiError('LEARNING_CONTRACT_HOLD', error.message, 409);
    }
    // In particular, transport failures stay distinguishable from known HTTP rejections.
    throw error;
  }
}
function ensure(condition: unknown, message: string): asserts condition {
  if (!condition) throw new LearningContractError(message);
}
function id(value: string): string {
  ensure(typeof value === 'string' && /^[A-Za-z0-9_-]{1,120}$/.test(value), '学习请求标识无效。');
  return encodeURIComponent(value);
}
function scoped(scope: LearningScope): void { id(scope.workspaceId); id(scope.projectId); }
async function payload(response: Response): Promise<unknown> {
  ensure(response.headers.get('Content-Type')?.split(';')[0]?.trim().toLowerCase() === 'application/json', '学习响应不是 JSON 回执。');
  const value: unknown = await response.json();
  const digest = response.headers.get('X-Content-SHA256');
  if (digest !== null) ensure(value !== null && typeof value === 'object' && 'receipt_sha256' in value && value.receipt_sha256 === digest, '学习响应内容摘要头不匹配。');
  return value;
}
function preparePost<T>(scope: LearningScope, route: () => string, request: unknown, validate: (value: unknown) => T): { path: string; body: string; request: T } {
  // Everything in this synchronous block happens before operatorFetch is called.
  // A malformed local request must not leave the UI with an ambiguous-write lock.
  try {
    scoped(scope); const path = route();
    ensure(request !== null && typeof request === 'object' && !Array.isArray(request), '学习请求必须是对象。');
    ensure(Object.getPrototypeOf(request) === Object.prototype || Object.getPrototypeOf(request) === null, '学习请求必须是普通 JSON 对象。');
    const normalized: Record<string, unknown> = { ...request };
    // Mirror the backend's ordinary string fields, not literals or collection groups.
    // Preserve the caller's object and all group IDs/values exactly as provided.
    for (const key of ['request_key', 'review_note', 'expected_preflight_sha256', 'expected_cycle_sha256', 'expected_run_sha256', 'task_id', 'followup_task_id']) {
      if (typeof normalized[key] === 'string') normalized[key] = normalized[key].trim();
    }
    if ('normal_mask_attestations' in normalized) {
      const declarations = normalized.normal_mask_attestations;
      ensure(declarations !== null && typeof declarations === 'object' && !Array.isArray(declarations), '正常图声明必须是逐样本映射。');
      normalized.normal_mask_attestations = Object.fromEntries(Object.entries(declarations).map(([sampleId, value]: [string, unknown]) => {
        ensure(value !== null && typeof value === 'object' && !Array.isArray(value), '正常图声明必须是对象。');
        const declaration: Record<string, unknown> = { ...value };
        for (const key of ['reviewer_name', 'review_note', 'expected_asset_sha256', 'expected_annotation_sha256']) {
          if (typeof declaration[key] === 'string') declaration[key] = declaration[key].trim();
        }
        return [sampleId, declaration];
      }));
    }
    const checked = validate(normalized); const body = JSON.stringify(checked);
    ensure(typeof body === 'string', '学习请求无法编码为 JSON。');
    return { path, body, request: checked };
  } catch (error) {
    const detail = error instanceof LearningContractError ? error.message : '参数、范围或 JSON 编码检查失败。';
    throw new OperatorApiError('LEARNING_REQUEST_NOT_SENT', `学习请求未发送：${detail}`, 422);
  }
}
function post(prepared: { path: string; body: string }, timeoutMs = 30_000): Promise<Response> {
  return operatorFetch(prepared.path, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: prepared.body }, timeoutMs);
}
export function listLearningCycles(scope: LearningScope): Promise<LearningCycle[]> {
  return contract(async () => {
    scoped(scope);
    const response = await operatorFetch(`/v1/projects/${id(scope.projectId)}/learning-cycles`);
    const value = await payload(response);
    ensure(Array.isArray(value), '学习周期列表格式未知。');
    const cycles = await Promise.all(value.map(item => validateLearningCycle(item, scope)));
    ensure(new Set(cycles.map(cycle => cycle.cycle_id)).size === cycles.length, '学习周期列表包含重复标识。');
    return cycles;
  });
}
export function getLearningCycle(scope: LearningScope, cycleId: string): Promise<LearningCycle> {
  return contract(async () => {
    scoped(scope); const response = await operatorFetch(`/v1/learning-cycles/${id(cycleId)}`);
    return validateLearningCycle(await payload(response), scope, cycleId, response.headers.get('ETag'));
  });
}
export function getLearningRun(scope: LearningScope, cycleId: string, runId: string): Promise<LearningRun> {
  return contract(async () => {
    scoped(scope); id(cycleId); const response = await operatorFetch(`/v1/learning-runs/${id(runId)}`);
    return validateLearningRun(await payload(response), scope, cycleId, runId, response.headers.get('ETag'));
  });
}
export function createLearningCycle(scope: LearningScope, taskId: string, request: CreateLearningRequest): Promise<LearningCycle> {
  return contract(async () => {
    const prepared = preparePost(scope, () => `/v1/tasks/${id(taskId)}/learning-cycles`, request, validateCreateLearningRequest);
    const response = await post(prepared);
    const cycle = await validateLearningCycle(await payload(response), scope, undefined, response.headers.get('ETag'));
    ensure(cycle.dataset.binding.task_id === taskId && cycle.request.request_key === prepared.request.request_key && cycle.request.expected_preflight_sha256 === prepared.request.expected_preflight_sha256, '创建回执未绑定本次任务与请求。');
    return cycle;
  });
}
export function runLearningRound(scope: LearningScope, cycleId: string, request: RoundLearningRequest): Promise<LearningRun> {
  return contract(async () => {
    const prepared = preparePost(scope, () => `/v1/learning-cycles/${id(cycleId)}/rounds`, request, validateRoundLearningRequest);
    // The backend permits up to 120 seconds per round. A timeout still means UNKNOWN,
    // never permission to replay the POST; the caller retains request_key for GET reconciliation.
    const response = await post(prepared, 180_000);
    const run = await validateLearningRun(await payload(response), scope, cycleId, undefined, response.headers.get('ETag'));
    ensure(run.binding.task_id === prepared.request.task_id && run.approval.request_key === prepared.request.request_key && run.approval.expected_cycle_sha256 === prepared.request.expected_cycle_sha256 && run.approval.expected_preflight_sha256 === prepared.request.expected_preflight_sha256, '轮次回执未绑定本次任务与批准版本。');
    return run;
  });
}
export function reviewLearningFeedback(scope: LearningScope, cycleId: string, runId: string, feedbackId: string, request: FeedbackLearningRequest): Promise<LearningRun> {
  return contract(async () => {
    const prepared = preparePost(scope, () => `/v1/learning-cycles/${id(cycleId)}/runs/${id(runId)}/feedback/${id(feedbackId)}`, request, validateFeedbackLearningRequest);
    const response = await post(prepared);
    const run = await validateLearningRun(await payload(response), scope, cycleId, runId, response.headers.get('ETag'));
    const reviewed = run.feedback.find(item => item.feedback_id === feedbackId);
    ensure(reviewed?.status === 'TRIAGED_NOT_AUTO_INGESTED' && reviewed.classification === prepared.request.classification && reviewed.review_note === prepared.request.review_note && reviewed.followup_task_id === (prepared.request.followup_task_id ?? null), '人工复核回执未绑定当前反馈与处置选择。');
    return run;
  });
}
export function selectLearningModel(scope: LearningScope, cycleId: string, runId: string, request: SelectionLearningRequest): Promise<LearningCycle> {
  return contract(async () => {
    const prepared = preparePost(scope, () => `/v1/learning-cycles/${id(cycleId)}/runs/${id(runId)}/selection`, request, validateSelectionLearningRequest);
    const response = await post(prepared);
    const cycle = await validateLearningCycle(await payload(response), scope, cycleId, response.headers.get('ETag'));
    ensure(cycle.round_ids.includes(runId), '模型选择回执不包含目标轮次。');
    return cycle;
  });
}
export function learningCycleAction(scope: LearningScope, cycleId: string, action: 'finalize' | 'cancel' | 'recover', request: CycleLearningRequest): Promise<LearningCycle> {
  return contract(async () => {
    const prepared = preparePost(scope, () => {
      ensure(['finalize', 'cancel', 'recover'].includes(action), '学习周期操作未知。');
      return `/v1/learning-cycles/${id(cycleId)}/${action}`;
    }, request, validateCycleLearningRequest);
    const response = await post(prepared, action === 'finalize' ? 180_000 : 30_000);
    return validateLearningCycle(await payload(response), scope, cycleId, response.headers.get('ETag'));
  });
}
export function getLearningReadiness(scope: LearningScope, taskId: string): Promise<LearningReadiness> {
  return contract(async () => {
    scoped(scope); const response = await operatorFetch(`/v1/tasks/${id(taskId)}/learning-readiness`);
    return validateLearningReadiness(await payload(response), scope, taskId, response.headers.get('ETag'));
  });
}
export function getLearningOperation(scope: LearningScope, operation: LearningOperationName, requestKey: string, targetId: string): Promise<LearningOperation> {
  return contract(async () => {
    scoped(scope); ensure(['create', 'train', 'feedback', 'followup', 'select', 'rollback', 'cancel', 'recover', 'finalize'].includes(operation), '学习对账操作未知。');
    ensure(/^[A-Za-z0-9_-]{12,100}$/.test(requestKey), '学习对账请求标识无效。');
    const response = await operatorFetch(`/v1/projects/${id(scope.projectId)}/learning-operations/${operation}/${encodeURIComponent(requestKey)}?target_id=${id(targetId)}`);
    return validateLearningOperation(await payload(response), scope, operation, requestKey, targetId, response.headers.get('ETag'));
  });
}
export function linkLearningFeedback(scope: LearningScope, cycleId: string, runId: string, feedbackId: string, request: FeedbackFollowupRequest): Promise<LearningRun> {
  return contract(async () => {
    const prepared = preparePost(scope, () => `/v1/learning-cycles/${id(cycleId)}/runs/${id(runId)}/feedback/${id(feedbackId)}/followup`, request, validateFeedbackFollowupRequest);
    const response = await post(prepared);
    const run = await validateLearningRun(await payload(response), scope, cycleId, runId, response.headers.get('ETag'));
    const linked = run.feedback.find(item => item.feedback_id === feedbackId)?.followup;
    ensure(linked && linked.binding.task_id === prepared.request.task_id && linked.preflight_receipt_sha256 === prepared.request.expected_preflight_sha256 && linked.review_note === prepared.request.review_note && JSON.stringify(linked.sample_ids) === JSON.stringify(prepared.request.sample_ids), '反馈关联回执未绑定本次新证据与样本选择。');
    return run;
  });
}
