import { operatorFetch, OperatorApiError } from './api';
import { getIdentityActorId } from '../identitySession.ts';
import { getDataPool } from './dataPoolApi.ts';
import {
  VisionContractError, validateVisionScope, validateVisionRequest, validateVisionRecord, validateVisionList,
  validateVisionCapabilities, validateVisionOperationReceipt, validateVisionFeedbackList, visionEnsure, visionId, visionDigest, validateVisionOperation,
} from '../visionModelDomain.ts';
import type { VisionScope, VisionKind, VisionRecord, VisionModel, VisionRuntime, VisionDataset, VisionRun, VisionInferenceAsset, VisionInference,
  VisionCapabilities, VisionMutationOperation, VisionPending, VisionOperationReceipt, VisionFeedback } from '../visionModelDomain.ts';

/** No retries, downloads, implicit probes or training. All mutation calls are explicit. */
const collection: Record<VisionKind, string> = { model: 'vision-models', runtime: 'vision-runtimes', dataset: 'vision-datasets', run: 'vision-training-runs',
  inference_asset: 'vision-inference-assets', inference: 'vision-inferences' };
function scoped(scope: VisionScope) { validateVisionScope(scope); visionEnsure(getIdentityActorId() === scope.actorId); }
function base(scope: VisionScope) { scoped(scope); return `/v1/projects/${encodeURIComponent(scope.projectId)}`; }
function safeId(value: string) { visionId(value); return encodeURIComponent(value); }
async function payload(response: Response): Promise<unknown> {
  visionEnsure(response.headers.get('Content-Type')?.split(';')[0]?.trim().toLowerCase() === 'application/json');
  // Validation failures never surface a server body, absolute path or original parser error.
  try { return await response.json(); } catch { throw new VisionContractError(); }
}
async function read<T>(scope: VisionScope, path: string, check: (value: unknown, response: Response) => Promise<T>): Promise<T> {
  scoped(scope); const response = await operatorFetch(path); scoped(scope); const result = await check(await payload(response), response); scoped(scope); return result;
}
export function getVisionCapabilities(scope: VisionScope): Promise<VisionCapabilities> {
  return read(scope, `${base(scope)}/vision-capabilities`, (v, r) => validateVisionCapabilities(v, scope, r.headers.get('ETag'), r.headers.get('X-Content-SHA256')));
}
export function listVisionRecords(scope: VisionScope, kind: 'model'): Promise<VisionModel[]>;
export function listVisionRecords(scope: VisionScope, kind: 'runtime'): Promise<VisionRuntime[]>;
export function listVisionRecords(scope: VisionScope, kind: 'dataset'): Promise<VisionDataset[]>;
export function listVisionRecords(scope: VisionScope, kind: 'run'): Promise<VisionRun[]>;
export function listVisionRecords(scope: VisionScope, kind: 'inference_asset'): Promise<VisionInferenceAsset[]>;
export function listVisionRecords(scope: VisionScope, kind: 'inference'): Promise<VisionInference[]>;
export function listVisionRecords(scope: VisionScope, kind: VisionKind): Promise<VisionRecord[]> {
  visionEnsure(Object.hasOwn(collection, kind));
  return read(scope, `${base(scope)}/${collection[kind]}`, (v, r) => validateVisionList(v, scope, kind, r.headers.get('ETag'), r.headers.get('X-Content-SHA256')));
}
export function getVisionRun(scope: VisionScope, runId: string): Promise<VisionRun> {
  return read(scope, `${base(scope)}/vision-training-runs/${safeId(runId)}`, async (v, r) => await validateVisionRecord(v, scope, 'run', runId, r.headers.get('ETag'), r.headers.get('X-Content-SHA256')) as VisionRun);
}
export function getVisionModel(scope: VisionScope, modelId: string): Promise<VisionModel> {
  return read(scope, `${base(scope)}/vision-models/${safeId(modelId)}`, async (v, r) => await validateVisionRecord(v, scope, 'model', modelId, r.headers.get('ETag'), r.headers.get('X-Content-SHA256')) as VisionModel);
}
export function listVisionInferenceAssets(scope: VisionScope): Promise<VisionInferenceAsset[]> { return listVisionRecords(scope, 'inference_asset'); }
export function listVisionInferences(scope: VisionScope): Promise<VisionInference[]> { return listVisionRecords(scope, 'inference'); }
export function getVisionInferenceAsset(scope: VisionScope, assetId: string): Promise<VisionInferenceAsset> {
  return read(scope, `${base(scope)}/vision-inference-assets/${safeId(assetId)}`, async (v, r) => await validateVisionRecord(v, scope, 'inference_asset', assetId, r.headers.get('ETag'), r.headers.get('X-Content-SHA256')) as VisionInferenceAsset);
}
export function getVisionInference(scope: VisionScope, inferenceId: string): Promise<VisionInference> {
  return read(scope, `${base(scope)}/vision-inferences/${safeId(inferenceId)}`, async (v, r) => await validateVisionRecord(v, scope, 'inference', inferenceId, r.headers.get('ETag'), r.headers.get('X-Content-SHA256')) as VisionInference);
}
export function getVisionFeedback(scope: VisionScope, run: VisionRun): Promise<VisionFeedback[]> {
  return read(scope, `${base(scope)}/vision-training-runs/${safeId(run.run_id)}/feedback`, (v, r) => validateVisionFeedbackList(v, scope, run, r.headers.get('ETag'), r.headers.get('X-Content-SHA256')));
}
export function getVisionOperation(scope: VisionScope, pending: VisionPending): Promise<VisionOperationReceipt> {
  validateVisionOperation(pending.operation); visionEnsure(/^[A-Za-z0-9_-]{12,100}$/.test(pending.requestKey));
  return read(scope, `${base(scope)}/vision-operations/${encodeURIComponent(pending.operation)}/${encodeURIComponent(pending.requestKey)}`,
    (v, r) => validateVisionOperationReceipt(v, scope, pending, r.headers.get('ETag'), r.headers.get('X-Content-SHA256')));
}
export async function getVisionPool(scope: VisionScope, poolId: string, expectedVersionId?: string | null) {
  scoped(scope); visionId(poolId); if (expectedVersionId) visionId(expectedVersionId);
  const projection = await getDataPool(scope, poolId); scoped(scope);
  // Do not silently advance a deep link from a reviewed old version to a new one.
  visionEnsure(!expectedVersionId || projection.current_version.version_id === expectedVersionId);
  return projection;
}
export interface PreparedVisionMutation {
  readonly scope: VisionScope; readonly pending: VisionPending; readonly path: string; readonly body: string;
  readonly kind: VisionKind | 'feedback'; readonly targetId?: string; readonly runId?: string; readonly request: Readonly<Record<string, unknown>>;
}
export async function prepareVisionMutation(scope: VisionScope, operation: VisionMutationOperation, input: unknown, context?: { runId: string }): Promise<PreparedVisionMutation> {
  // Finish all local validation BEFORE the caller persists its ambiguous-write lock.
  try {
    scoped(scope);
    visionEnsure(input !== null && typeof input === 'object' && !Array.isArray(input));
    // Pydantic strips ordinary DTO strings. The nested manifest must stay byte-semantic JSON, without injected defaults.
    const normalized = Object.fromEntries(Object.entries(input).map(([key, value]) => [key, typeof value === 'string' ? value.trim() : value]));
    const request = await validateVisionRequest(operation, normalized); scoped(scope);
    const [name, targetId] = operation.split(':');
    let kind: VisionKind | 'feedback'; let suffix: string;
    if (name === 'register_model') { kind = 'model'; suffix = collection.model; }
    else if (name === 'register_normality_model_pack') { kind = 'model'; suffix = 'vision-model-packs'; }
    else if (name === 'register_runtime') { kind = 'runtime'; suffix = collection.runtime; }
    else if (name === 'register_dataset') { kind = 'dataset'; suffix = collection.dataset; }
    else if (name === 'register_pool_dataset') { kind = 'dataset'; suffix = `${collection.dataset}/from-data-pool`; }
    else if (name === 'register_inference_asset') { kind = 'inference_asset'; suffix = collection.inference_asset; }
    else if (name === 'create_training_run') { kind = 'run'; suffix = collection.run; }
    else if (name === 'triage_feedback') { visionEnsure(context?.runId && targetId); kind = 'feedback'; suffix = `${collection.run}/${safeId(context.runId)}/feedback/${safeId(targetId)}/triage`; }
    else if (name === 'approve_normality_model_pack') { visionEnsure(targetId); kind = 'model'; suffix = `${collection.model}/${safeId(targetId)}/sandbox-approval`; }
    else if (name === 'run_normality_inference') { visionEnsure(targetId); kind = 'inference'; suffix = `${collection.model}/${safeId(targetId)}/inferences`; }
    else { visionEnsure(targetId); kind = name === 'probe_runtime' ? 'runtime' : 'run'; suffix = `${collection[kind]}/${safeId(targetId)}/${name === 'probe_runtime' ? 'probe' : name}`; }
    const body = JSON.stringify(request);
    return { scope: { ...scope }, pending: { operation, requestKey: String(request.request_key) }, path: `${base(scope)}/${suffix}`, body, kind, targetId, runId: context?.runId, request: JSON.parse(body) as Record<string, unknown> };
  } catch { throw new OperatorApiError('VISION_REQUEST_NOT_SENT', '请求未发送；请检查必填字段、授权与内容摘要。', 422); }
}
export async function sendVisionMutation(prepared: PreparedVisionMutation): Promise<VisionRecord> {
  scoped(prepared.scope);
  const response = await operatorFetch(prepared.path, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: prepared.body }, 180_000);
  scoped(prepared.scope);
  const expectedResultId = prepared.pending.operation.startsWith('run_normality_inference:') ? undefined : prepared.targetId;
  const result = await validateVisionRecord(await payload(response), prepared.scope, prepared.kind, expectedResultId, response.headers.get('ETag'), response.headers.get('X-Content-SHA256'));
  const request = prepared.request;
  if (prepared.pending.operation === 'register_model') visionEnsure((result as VisionModel).weights_sha256 === request.expected_weights_sha256 && (result as VisionModel).task_type === request.task_type);
  if (prepared.pending.operation === 'register_normality_model_pack') {
    const model = result as VisionModel; visionEnsure(model.task_type === 'normality' && model.model_pack_sha256 === request.expected_model_pack_sha256
      && model.backbone_weights_sha256 === request.expected_backbone_weights_sha256 && model.source_binding_sha256 === request.expected_source_binding_sha256
      && model.source_index_sha256 === request.expected_source_index_sha256);
  }
  if (prepared.pending.operation === 'register_runtime') visionEnsure((result as VisionRuntime).executable_sha256 === request.expected_executable_sha256);
  if (prepared.pending.operation === 'register_dataset') visionEnsure((result as VisionDataset).dataset_receipt.manifest_sha256 === request.expected_manifest_sha256);
  if (prepared.pending.operation === 'register_pool_dataset') {
    const binding = (result as VisionDataset).pool_binding;
    visionEnsure(binding && binding.pool_id === request.pool_id && binding.version_id === request.version_id
      && binding.pool_receipt_sha256 === request.expected_pool_receipt_sha256 && binding.version_receipt_sha256 === request.expected_version_receipt_sha256
      && await visionDigest(binding.class_names) === await visionDigest(request.class_names) && await visionDigest(binding.groups) === await visionDigest(request.groups)
      && await visionDigest([...binding.normal_sample_ids].sort()) === await visionDigest([...(request.normal_sample_ids as string[])].sort()));
  }
  if (prepared.pending.operation === 'register_inference_asset') visionEnsure((result as VisionInferenceAsset).image_sha256 === request.expected_image_sha256);
  if (prepared.pending.operation.startsWith('approve_normality_model_pack:')) {
    const model = result as VisionModel; visionEnsure(model.task_type === 'normality' && model.model_id === prepared.targetId && model.status === request.action
      && model.model_pack_sha256 === request.expected_model_pack_sha256 && model.backbone_weights_sha256 === request.expected_backbone_weights_sha256
      && model.source_binding_sha256 === request.expected_source_binding_sha256 && model.source_index_sha256 === request.expected_source_index_sha256
      && (request.action === 'REJECT' || (model.sandbox_runtime_id === request.runtime_id && model.sandbox_runtime_sha256 === request.expected_runtime_sha256)));
  }
  if (prepared.pending.operation.startsWith('run_normality_inference:')) {
    const inference = result as VisionInference; visionEnsure(inference.model_id === prepared.targetId && inference.asset_id === request.asset_id
      && inference.model_pack_sha256 === request.expected_model_pack_sha256 && inference.backbone_weights_sha256 === request.expected_backbone_weights_sha256
      && inference.source_binding_sha256 === request.expected_source_binding_sha256 && inference.source_index_sha256 === request.expected_source_index_sha256
      && inference.runtime_sha256 === request.expected_runtime_sha256 && inference.image_sha256 === request.expected_image_sha256
      && inference.status === 'COMPLETED_LOCAL_SANDBOX_INFERENCE' && inference.gate_decision === 'NOT_ISSUED');
  }
  if (prepared.pending.operation === 'create_training_run') visionEnsure((result as VisionRun).authorization_sha256 === await visionDigest(request)
    && (result as VisionRun).runtime_id === request.runtime_id && (result as VisionRun).runtime_sha256 === request.expected_runtime_sha256
    && (result as VisionRun).dataset_id === request.dataset_id && (result as VisionRun).dataset_receipt_sha256 === request.expected_dataset_receipt_sha256);
  if (prepared.pending.operation.startsWith('probe_runtime:')) visionEnsure((result as VisionRuntime).runtime_sha256 === request.expected_runtime_sha256);
  if (prepared.pending.operation.startsWith('selection:')) visionEnsure((result as VisionRun).selection === request.action);
  if (prepared.pending.operation.startsWith('cancel:')) visionEnsure((result as VisionRun).cancel_requested === true);
  if (prepared.pending.operation.startsWith('recover:')) visionEnsure((result as VisionRun).status === 'INTERRUPTED_HOLD');
  if (prepared.pending.operation.startsWith('triage_feedback:')) visionEnsure((result as VisionFeedback).run_id === prepared.runId && (result as VisionFeedback).status === 'TRIAGED_FOR_REVIEW' && (result as VisionFeedback).classification === request.classification);
  scoped(prepared.scope); return result;
}
export function visionWriteKnownRejected(error: unknown): boolean {
  // A success response with a broken receipt, transport reset or HTTP 5xx stays UNKNOWN.
  return error instanceof OperatorApiError && (error.code === 'VISION_REQUEST_NOT_SENT' || [400, 401, 403, 404, 409, 422].includes(error.status));
}
export function visionErrorMessage(error: unknown): string {
  if (error instanceof VisionContractError) return 'HOLD：回执的 JCS、强 ETag、摘要头或项目绑定不匹配；没有接受该结果。';
  if (error instanceof OperatorApiError) {
    if (error.code === 'VISION_REQUEST_NOT_SENT') return '请求未发送：请检查输入、SHA-256、真实检测框和独立授权。';
    if (error.status === 404) return 'HOLD：当前后端没有此资源或尚未挂载视觉模型接口；不会使用演示数据替代。';
    if (error.status === 401 || error.status === 403) return 'HOLD：当前账号、项目权限或本机连接未通过；请检查登录与本地服务。';
    if (error.status === 409 || error.status === 422) return 'HOLD：版本、运行环境、数据隔离或授权合同未满足；请刷新并复核。';
  }
  return '连接或执行结果未知；写操作必须保留原请求标识，只通过 GET 对账，不自动重发。';
}
