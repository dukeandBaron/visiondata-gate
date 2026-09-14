import { canonicalizeJcs, sha256HexUtf8 } from './data/jcs.ts';

/** Pure learning contracts. This module deliberately has no browser/API dependency. */
export interface LearningScope { workspaceId: string; projectId: string }
export type LearningCycleStatus = 'READY' | 'RUNNING' | 'AWAITING_REVIEW' | 'AWAITING_DATA' | 'HOLD_REQUIRES_NEW_PROTOCOL' | 'STOPPED' | 'FINALIZING' | 'FINALIZED';
export type LearningRunStatus = 'RUNNING' | 'COMPLETED' | 'FAILED' | 'CANCELLED' | 'INTERRUPTED';
export type LearningClassification = 'LABEL_ERROR' | 'HARD_SAMPLE' | 'DISTRIBUTION_SHIFT' | 'INSUFFICIENT_EVIDENCE';
export interface LearningTrainingConfig { epochs: number; learning_rate: number; l2: number; max_wall_seconds: number; seed: number }
export interface LearningEvaluationPolicy {
  threshold: number; max_false_negative_rate: number; max_false_positive_rate: number;
  min_dice: number; min_dice_gain: number; max_category_dice_regression: number; max_p95_latency_ms: number;
}
interface LearningRequest { request_key: string; review_note: string }
export interface NormalMaskAttestation {
  reviewer_name: string; review_note: string; expected_asset_sha256: string;
  expected_annotation_revision: number; expected_annotation_sha256: string; operator_attests_no_foreground: true;
}
interface LearningDatasetAuthorization extends LearningRequest {
  expected_preflight_sha256: string; groups: Record<string, string>; operator_attests_training_authorized: true;
  normal_mask_attestations?: Record<string, NormalMaskAttestation>;
}
export interface CreateLearningRequest extends LearningDatasetAuthorization {
  training?: Partial<LearningTrainingConfig>; evaluation?: Partial<LearningEvaluationPolicy>;
  max_rounds?: number; max_total_epochs?: number; max_total_wall_seconds?: number;
}
export interface RoundLearningRequest extends LearningDatasetAuthorization { task_id: string; expected_cycle_sha256: string; responds_to_feedback_ids?: string[] }
export interface CycleLearningRequest extends LearningRequest { expected_cycle_sha256: string; operator_attests_reviewed: true }
export interface FeedbackLearningRequest extends CycleLearningRequest { classification: LearningClassification; followup_task_id?: string | null }
export interface SelectionLearningRequest extends CycleLearningRequest {
  expected_run_sha256: string;
  expected_continual_retention_receipt_sha256?: string;
  action: 'APPROVE_SANDBOX' | 'APPROVE_SANDBOX_CONTINUAL' | 'REJECT';
}
export interface FeedbackFollowupRequest extends CycleLearningRequest {
  expected_run_sha256: string; task_id: string; expected_preflight_sha256: string; sample_ids: string[];
}
export interface LearningBinding {
  task_id: string; workspace_id: string; project_id: string; source_id: string; snapshot_id: string;
  snapshot_receipt_sha256: string; acceptance_requirements_sha256: string; batch_manifest_sha256: string;
  batch_contract_sha256: string; batch_digest_sha256: string; gate_result_sha256: string;
  sample_count: number; intended_use: string;
}
export interface LearningSample {
  sample_id: string; split: 'train' | 'val' | 'test'; category: string; group_id: string;
  image_path: string; mask_path: string; image_sha256: string; mask_sha256: string;
  pixel_sha256: string; mask_pixel_sha256: string; width: number; height: number;
  mask_origin?: 'EXPLICIT_HUMAN_ZERO_MASK'; normal_attestation_sha256?: string;
}
export interface LearningDataset {
  schema_version: 'visiondata-gate.learning-dataset.v1'; dataset_id: string; binding: LearningBinding;
  samples: LearningSample[]; split_fingerprints: Record<'train' | 'val' | 'test', string>;
  labels_sha256: string; receipt_sha256: string;
  normal_mask_attestations?: Record<string, NormalMaskAttestation>;
}
export interface LearningMetrics {
  tp: number; fp: number; tn: number; fn: number; dice: number | null;
  false_negative_rate: number | null; false_positive_rate: number | null; error_rate: number | null;
}
interface LearningPredictionMetrics extends LearningMetrics { prediction_sha256: string; prediction_mask_sha256: string }
export interface LearningSampleEvidence {
  sample_id: string; category: string; group_id: string; truth_mask_sha256: string;
  candidate: LearningPredictionMetrics; baseline: LearningPredictionMetrics; error_candidate: boolean;
  review_status: 'PENDING_HUMAN_REVIEW'; annotation_error_confirmed: false;
}
export interface LearningEvaluation {
  schema_version: 'visiondata-gate.learning-evaluation.v1'; split: 'val' | 'test'; policy: LearningEvaluationPolicy;
  aggregate: { candidate: LearningMetrics; baseline: LearningMetrics };
  categories: Record<string, { candidate: LearningMetrics; baseline: LearningMetrics }>;
  sample_results: LearningSampleEvidence[];
  latency: {
    scope: 'LOCAL_CPU_OBSERVATION_ONLY'; timer: 'time.perf_counter'; measurement: 'predict_call_only';
    model_order: ['candidate', 'baseline']; observations_per_sample: 1; warmup_runs: 0;
    quantile_method: 'linear'; benchmark_claim: false;
    candidate: { sample_count: number; p95_ms: number }; baseline: { sample_count: number; p95_ms: number };
  };
  decision: 'HOLD' | 'ELIGIBLE'; blockers: string[]; observed_elapsed_seconds: number;
}
export interface LearningFeedback {
  feedback_id: string; status: 'PENDING_HUMAN_REVIEW' | 'TRIAGED_NOT_AUTO_INGESTED';
  evidence: LearningSampleEvidence; classification: LearningClassification | null;
  next_action: 'INVESTIGATE' | 'RELABEL_AND_NEW_EVALUATION_PROTOCOL' | 'COLLECT_SIMILAR_TRAINING_EXAMPLES' | 'RECAPTURE_REPRESENTATIVE_TRAINING_DATA';
  training_ingestion_allowed: false; followup_task_id: string | null; reviewed_by?: string; review_note?: string;
  followup_status?: 'NEW_GATE_EVIDENCE_LINKED_NOT_ISSUE_CLOSED'; followup?: LearningFeedbackFollowup;
}
export interface LearningFeedbackFollowup {
  binding: LearningBinding; preflight_receipt_sha256: string; sample_ids: string[];
  members: { sample_id: string; split: 'train' | 'val' | 'test'; image_sha256: string; annotation_revision: number; annotation_document_sha256: string; mask_sha256: string | null }[];
  reviewed_by: string; review_note: string; at: string; issue_closed: false; training_ingestion_allowed: false;
  boundary: string; receipt_sha256: string;
}
export interface LearningTraining {
  loss_before: number; loss_after: number; epochs_completed: number; training_sample_ids: string[];
  training_pixel_count: number; elapsed_seconds: number; initial_model_sha256: string;
  optimizer: 'full_batch_gradient_descent'; device: 'CPU';
}
export interface LearningRun {
  schema_version: 'visiondata-gate.learning-run.v1'; run_id: string; cycle_id: string; project_id: string;
  round_number: number; retry_of_run_id: string | null; feedback_parent_run_id: string | null;
  previous_run_id?: string | null;
  responds_to_feedback_ids: string[]; feedback_response_boundary: string; status: LearningRunStatus;
  dataset_id: string; dataset_receipt_sha256: string; dataset_storage_key: string; binding: LearningBinding;
  initial_model_id: string; initial_model_sha256: string; configuration: LearningTrainingConfig; approval: RoundLearningRequest;
  approved_by: string; started_at: string; feedback: LearningFeedback[];
  selection: {
    action: 'APPROVE_SANDBOX' | 'APPROVE_SANDBOX_CONTINUAL' | 'REJECT'; actor: string;
    note: string; evaluation_sha256: string; continual_retention_receipt_sha256?: string; at: string;
  } | null;
  cancel_requested: boolean; production_release_allowed: false; remote_execution_verified: false; receipt_sha256: string;
  completed_at?: string; training?: LearningTraining; model_id?: string; model_sha256?: string;
  evaluation?: LearningEvaluation; evaluation_sha256?: string; elapsed_seconds?: number; failure_code?: string; failure_type?: string;
}
export interface LearningCycle {
  schema_version: 'visiondata-gate.learning-cycle.v1'; cycle_id: string; project_id: string; workspace_id: string;
  created_by: string; created_at: string; updated_at: string; revision: number; status: LearningCycleStatus;
  request: LearningDatasetAuthorization & { training: LearningTrainingConfig; evaluation: LearningEvaluationPolicy; max_rounds: number; max_total_epochs: number; max_total_wall_seconds: number };
  dataset: LearningDataset; dataset_storage_key: string; evaluation_fingerprints: { val: string; test: string };
  initial_model_id: string; champion_model_id: string; approved_model_ids: string[]; round_ids: string[];
  epochs_reserved: number; wall_seconds_reserved: number; events: { event: string; actor: string; at: string }[];
  production_release_allowed: false; machine_write_permitted: false; remote_execution_verified: false;
  scope: 'LOCAL_SUPERVISED_REFERENCE_MODEL_SANDBOX'; receipt_sha256: string;
  final_evaluation?: LearningEvaluation; final_evaluation_sha256?: string;
  final_candidate_model_id?: string; final_candidate_model_sha256?: string;
  final_baseline_model_id?: string; final_baseline_model_sha256?: string; final_candidate_accepted?: boolean;
  final_test_failure?: 'FINAL_TEST_FAILED_NOT_RETRIED';
}
export interface LearningFindingRef { finding_id: string; code: string; severity: 'critical' | 'high' | 'medium' | 'low'; finding_sha256: string }
export type LearningReadinessState = 'UNVERIFIED_FINDING_IDENTITY' | 'UNVERIFIED_TOOL_FAILURE' | 'UNVERIFIED' | 'NEEDS_ATTENTION' | 'MASK_REQUIRED_FOR_REFERENCE_TRAINER' | 'BLOCKED_BY_BATCH' | 'GATE_ELIGIBLE_NOT_TRAINING_APPROVED';
export interface LearningReadiness {
  schema_version: 'visiondata-gate.learning-readiness.v1'; task_id: string; project_id: string; workspace_id: string;
  projection_status: 'UNVERIFIED' | 'VERIFIED'; preflight_receipt_sha256: string | null;
  preflight_eligibility: 'UNVERIFIED' | 'HOLD' | 'READY_FOR_OFFLINE_HANDOFF'; blockers: string[];
  members: { sample_id: string; split: 'train' | 'val' | 'test'; category: string; annotation_requirement: 'REQUIRED' | 'OPTIONAL' | 'NOT_APPLICABLE' | 'UNKNOWN'; mask_available: boolean | null; readiness_state: LearningReadinessState; finding_refs: LearningFindingRef[] }[];
  global_findings: LearningFindingRef[]; unmapped_finding_refs: LearningFindingRef[]; training_authorized: false;
  production_release_allowed: false; annotation_review_basis: 'OPERATOR_ATTESTATION_NOT_INDEPENDENT_TRUTH';
  required_dataset_validation: string[]; claim_boundary: string; receipt_sha256: string;
}
export type LearningOperationName = 'create' | 'train' | 'feedback' | 'followup' | 'select' | 'rollback' | 'cancel' | 'recover' | 'finalize';
export type LearningOperationKind = LearningOperationName;
export interface LearningOperation {
  schema_version: 'visiondata-gate.learning-operation.v1'; project_id: string; operation: LearningOperationName;
  request_key: string; target_id: string; lookup_status: 'NOT_FOUND' | 'FOUND'; request_sha256: string | null;
  request_digest_semantics: 'SERVER_CANONICAL_VALIDATED_REQUEST';
  request_digest_verification: 'NOT_AVAILABLE' | 'LEDGER_SHA_ONLY' | 'MATCHED_STORED_VALIDATED_REQUEST';
  result_semantics: 'CURRENT_RESULT'; result_kind: 'cycle' | 'run' | null; result_id: string | null;
  result_receipt_sha256: string | null; current_result: LearningCycle | LearningRun | null;
  execution_status: 'UNKNOWN_NOT_PROOF_OF_NO_WRITE' | 'PENDING' | 'RESULT_AVAILABLE';
  automatic_retry_allowed: false; receipt_sha256: string;
}

export class LearningContractError extends Error {
  readonly code = 'LEARNING_CONTRACT_HOLD';
  constructor(message: string) { super(message); this.name = 'LearningContractError'; }
}
function ensure(condition: unknown, message = '学习回执字段不符合已知合同。'): asserts condition {
  if (!condition) throw new LearningContractError(message);
}
function object(value: unknown): Record<string, unknown> {
  ensure(value !== null && typeof value === 'object' && !Array.isArray(value));
  ensure(Object.getPrototypeOf(value) === Object.prototype || Object.getPrototypeOf(value) === null);
  return value as Record<string, unknown>;
}
function shape(value: unknown, required: readonly string[], optional: readonly string[] = []): Record<string, unknown> {
  const row = object(value); const allowed = new Set([...required, ...optional]);
  ensure(required.every(key => Object.hasOwn(row, key)) && Object.keys(row).every(key => allowed.has(key)));
  return row;
}
function text(value: unknown, max = 2000, min = 1): asserts value is string {
  ensure(typeof value === 'string' && value.trim().length >= min && value.length <= max && !/[\u0000-\u0008\u000b\u000c\u000e-\u001f]/.test(value));
}
function identifier(value: unknown): asserts value is string { ensure(typeof value === 'string' && /^[A-Za-z0-9_-]{1,120}$/.test(value)); }
function sha(value: unknown): asserts value is string { ensure(typeof value === 'string' && /^[0-9a-f]{64}$/.test(value), '学习回执缺少有效 SHA-256。'); }
function number(value: unknown, min = 0, max = Number.MAX_SAFE_INTEGER, integer = false): asserts value is number {
  ensure(typeof value === 'number' && Number.isFinite(value) && value >= min && value <= max && (!integer || Number.isSafeInteger(value)));
}
function member<T extends string>(value: unknown, values: readonly T[]): asserts value is T { ensure(typeof value === 'string' && (values as readonly string[]).includes(value), '学习回执包含未知状态。'); }
function array(value: unknown, max = 10000): unknown[] { ensure(Array.isArray(value) && value.length <= max); return value; }
function ids(value: unknown, max = 10000): string[] { const result = array(value, max); result.forEach(identifier); ensure(new Set(result).size === result.length); return result as string[]; }
function nullableId(value: unknown): void { if (value !== null) identifier(value); }
function timestamp(value: unknown): void { text(value, 80); ensure(/^\d{4}-\d{2}-\d{2}T.*(?:Z|[+-]\d{2}:\d{2})$/.test(value) && Number.isFinite(Date.parse(value))); }
function scopeCheck(value: Record<string, unknown>, scope: LearningScope): void {
  identifier(scope.projectId); identifier(scope.workspaceId);
  ensure(value.project_id === scope.projectId && value.workspace_id === scope.workspaceId, '学习回执不属于当前工作区与项目。');
}
async function hash(value: unknown): Promise<string> {
  try { return await sha256HexUtf8(canonicalizeJcs(value)); }
  catch { throw new LearningContractError('学习回执无法执行 JCS / SHA-256 核验。'); }
}
async function receipt(row: Record<string, unknown>, etag?: string | null, excluded: readonly string[] = ['receipt_sha256']): Promise<void> {
  sha(row.receipt_sha256);
  const body = Object.fromEntries(Object.entries(row).filter(([key]) => !excluded.includes(key)));
  ensure(await hash(body) === row.receipt_sha256, '学习回执摘要不匹配，必须重新读取并对账。');
  // undefined is reserved for list items. A missing header on an individual response is a HOLD.
  if (etag !== undefined) ensure(etag === `"${row.receipt_sha256}"`, '学习响应 ETag 未绑定当前回执。');
}
const trainingKeys = ['epochs', 'learning_rate', 'l2', 'max_wall_seconds', 'seed'] as const;
const policyKeys = ['threshold', 'max_false_negative_rate', 'max_false_positive_rate', 'min_dice', 'min_dice_gain', 'max_category_dice_regression', 'max_p95_latency_ms'] as const;
function trainingConfig(value: unknown, full = true): void {
  const row = shape(value, full ? trainingKeys : [], full ? [] : trainingKeys);
  if ('epochs' in row) number(row.epochs, 1, 500, true);
  if ('learning_rate' in row) number(row.learning_rate, 0.0001, 2);
  if ('l2' in row) number(row.l2, 0, 1);
  if ('max_wall_seconds' in row) number(row.max_wall_seconds, 0.01, 120);
  if ('seed' in row) number(row.seed, 0, Number.MAX_SAFE_INTEGER, true);
}
function evaluationPolicy(value: unknown, full = true): void {
  const row = shape(value, full ? policyKeys : [], full ? [] : policyKeys);
  for (const key of policyKeys) {
    if (!(key in row)) continue;
    number(row[key], 0, key === 'max_p95_latency_ms' ? 60000 : 1);
    if (key === 'threshold') ensure(row[key] > 0 && row[key] < 1);
    if (key === 'max_p95_latency_ms') ensure(row[key] > 0);
  }
}
const baseKeys = ['request_key', 'review_note'] as const;
const authorizationKeys = [...baseKeys, 'expected_preflight_sha256', 'groups', 'operator_attests_training_authorized'] as const;
const cycleRequestKeys = [...baseKeys, 'expected_cycle_sha256', 'operator_attests_reviewed'] as const;
const classificationActions = {
  LABEL_ERROR: 'RELABEL_AND_NEW_EVALUATION_PROTOCOL', HARD_SAMPLE: 'COLLECT_SIMILAR_TRAINING_EXAMPLES',
  DISTRIBUTION_SHIFT: 'RECAPTURE_REPRESENTATIVE_TRAINING_DATA', INSUFFICIENT_EVIDENCE: 'INVESTIGATE',
} as const;
const classifications = Object.keys(classificationActions) as LearningClassification[];
function baseRequest(row: Record<string, unknown>): void {
  ensure(typeof row.request_key === 'string' && /^[A-Za-z0-9_-]{12,100}$/.test(row.request_key)); text(row.review_note, 2000, 8);
}
function authorizeDataset(row: Record<string, unknown>): void {
  baseRequest(row); sha(row.expected_preflight_sha256); ensure(row.operator_attests_training_authorized === true, '必须明确确认本地训练授权。');
  const groups = object(row.groups); ensure(Object.keys(groups).length >= 1 && Object.keys(groups).length <= 64);
  for (const [key, value] of Object.entries(groups)) { text(key, 512); text(value, 120); }
  if ('normal_mask_attestations' in row) normalAttestations(row.normal_mask_attestations);
}
function normalAttestations(value: unknown): Record<string, NormalMaskAttestation> {
  const declarations = object(value); ensure(Object.keys(declarations).length <= 64);
  for (const [sampleId, value] of Object.entries(declarations)) {
    text(sampleId, 512);
    const item = shape(value, ['reviewer_name', 'review_note', 'expected_asset_sha256', 'expected_annotation_revision', 'expected_annotation_sha256', 'operator_attests_no_foreground']);
    text(item.reviewer_name, 120, 2); text(item.review_note, 2000, 8); sha(item.expected_asset_sha256); sha(item.expected_annotation_sha256);
    number(item.expected_annotation_revision, 0, Number.MAX_SAFE_INTEGER, true); ensure(item.operator_attests_no_foreground === true, '正常图零掩膜需要明确人工声明。');
  }
  return declarations as Record<string, NormalMaskAttestation>;
}
function authorizeCycle(row: Record<string, unknown>): void {
  baseRequest(row); sha(row.expected_cycle_sha256); ensure(row.operator_attests_reviewed === true, '必须明确确认人工复核。');
}
export function validateCreateLearningRequest(value: unknown): CreateLearningRequest {
  const row = shape(value, authorizationKeys, ['training', 'evaluation', 'max_rounds', 'max_total_epochs', 'max_total_wall_seconds', 'normal_mask_attestations']);
  authorizeDataset(row);
  if ('training' in row) trainingConfig(row.training, false);
  if ('evaluation' in row) evaluationPolicy(row.evaluation, false);
  if ('max_rounds' in row) number(row.max_rounds, 1, 10, true);
  if ('max_total_epochs' in row) number(row.max_total_epochs, 1, 2000, true);
  if ('max_total_wall_seconds' in row) { number(row.max_total_wall_seconds, 0, 600); ensure(row.max_total_wall_seconds > 0); }
  return row as unknown as CreateLearningRequest;
}
export function validateRoundLearningRequest(value: unknown): RoundLearningRequest {
  const row = shape(value, [...authorizationKeys, 'task_id', 'expected_cycle_sha256'], ['normal_mask_attestations', 'responds_to_feedback_ids']);
  authorizeDataset(row); identifier(row.task_id); sha(row.expected_cycle_sha256);
  if ('responds_to_feedback_ids' in row) { const references = ids(row.responds_to_feedback_ids, 64); ensure(references.every(value => /^feedback_[0-9a-f]{24}$/.test(value))); }
  return row as unknown as RoundLearningRequest;
}
export function validateCycleLearningRequest(value: unknown): CycleLearningRequest {
  const row = shape(value, cycleRequestKeys); authorizeCycle(row); return row as unknown as CycleLearningRequest;
}
export function validateFeedbackLearningRequest(value: unknown): FeedbackLearningRequest {
  const row = shape(value, [...cycleRequestKeys, 'classification'], ['followup_task_id']);
  authorizeCycle(row); member(row.classification, classifications);
  if ('followup_task_id' in row) nullableId(row.followup_task_id);
  return row as unknown as FeedbackLearningRequest;
}
export function validateSelectionLearningRequest(value: unknown): SelectionLearningRequest {
  const row = shape(value, [...cycleRequestKeys, 'expected_run_sha256', 'action'], ['expected_continual_retention_receipt_sha256']);
  authorizeCycle(row); sha(row.expected_run_sha256); member(row.action, ['APPROVE_SANDBOX', 'APPROVE_SANDBOX_CONTINUAL', 'REJECT']);
  const continual = row.action === 'APPROVE_SANDBOX_CONTINUAL';
  ensure(continual === ('expected_continual_retention_receipt_sha256' in row), '持续学习沙箱选择必须绑定且只绑定一份 Retention Receipt。');
  if (continual) sha(row.expected_continual_retention_receipt_sha256);
  return row as unknown as SelectionLearningRequest;
}
function sampleIds(value: unknown): string[] {
  const members = array(value, 64); ensure(members.length > 0); members.forEach(item => text(item, 512));
  ensure(new Set(members).size === members.length); return members as string[];
}
export function validateFeedbackFollowupRequest(value: unknown): FeedbackFollowupRequest {
  const row = shape(value, [...cycleRequestKeys, 'expected_run_sha256', 'task_id', 'expected_preflight_sha256', 'sample_ids']);
  authorizeCycle(row); sha(row.expected_run_sha256); identifier(row.task_id); sha(row.expected_preflight_sha256); sampleIds(row.sample_ids);
  return row as unknown as FeedbackFollowupRequest;
}
function binding(value: unknown, scope: LearningScope): LearningBinding {
  const row = shape(value, ['task_id', 'workspace_id', 'project_id', 'source_id', 'snapshot_id', 'snapshot_receipt_sha256', 'acceptance_requirements_sha256', 'batch_manifest_sha256', 'batch_contract_sha256', 'batch_digest_sha256', 'gate_result_sha256', 'sample_count', 'intended_use']);
  scopeCheck(row, scope);
  for (const key of ['task_id', 'source_id', 'snapshot_id']) identifier(row[key]);
  for (const key of ['snapshot_receipt_sha256', 'acceptance_requirements_sha256', 'batch_manifest_sha256', 'batch_contract_sha256', 'batch_digest_sha256', 'gate_result_sha256']) sha(row[key]);
  number(row.sample_count, 1, 64, true); text(row.intended_use, 16000);
  return row as unknown as LearningBinding;
}
function utf8Compare(left: string, right: string): number {
  const a = new TextEncoder().encode(left); const b = new TextEncoder().encode(right);
  for (let index = 0; index < Math.min(a.length, b.length); index += 1) { const delta = a[index]! - b[index]!; if (delta) return delta; }
  return a.length - b.length;
}
export async function validateLearningDataset(value: unknown, scope: LearningScope): Promise<LearningDataset> {
  const row = shape(value, ['schema_version', 'dataset_id', 'binding', 'samples', 'split_fingerprints', 'labels_sha256', 'receipt_sha256'], ['normal_mask_attestations']);
  ensure(row.schema_version === 'visiondata-gate.learning-dataset.v1');
  const bound = binding(row.binding, scope); const samples = array(row.samples, 64);
  ensure(samples.length === bound.sample_count && samples.length >= 3);
  const attestations = 'normal_mask_attestations' in row ? normalAttestations(row.normal_mask_attestations) : {};
  if ('normal_mask_attestations' in row) ensure(Object.keys(attestations).length > 0);
  const normalMembers = new Set<string>();
  const sampleIds = new Set<string>(); const groupSplits = new Map<string, string>(); const pixelSplits = new Map<string, string>(); let pixels = 0;
  for (const [index, sample] of samples.entries()) {
    const item = shape(sample, ['sample_id', 'split', 'category', 'group_id', 'image_path', 'mask_path', 'image_sha256', 'mask_sha256', 'pixel_sha256', 'mask_pixel_sha256', 'width', 'height'], ['mask_origin', 'normal_attestation_sha256']);
    for (const key of ['sample_id', 'category', 'group_id'] as const) { text(item[key], 512); ensure(!/^(?:[A-Za-z]:|[\\/])/.test(item[key]) && !/[\u0000-\u001f]/.test(item[key])); }
    member(item.split, ['train', 'val', 'test']);
    ensure(!sampleIds.has(item.sample_id as string)); sampleIds.add(item.sample_id as string);
    ensure(item.image_path === `images/${String(index).padStart(4, '0')}.image` && item.mask_path === `masks/${String(index).padStart(4, '0')}.mask`);
    for (const key of ['image_sha256', 'mask_sha256', 'pixel_sha256', 'mask_pixel_sha256']) sha(item[key]);
    if ('mask_origin' in item || 'normal_attestation_sha256' in item) {
      ensure(item.mask_origin === 'EXPLICIT_HUMAN_ZERO_MASK'); sha(item.normal_attestation_sha256);
      const attestation = attestations[item.sample_id as string]; ensure(attestation && attestation.expected_asset_sha256 === item.image_sha256);
      ensure(await hash(attestation) === item.normal_attestation_sha256, '正常图声明摘要与冻结样本不一致。'); normalMembers.add(item.sample_id as string);
    } else ensure(!Object.hasOwn(attestations, item.sample_id as string));
    number(item.width, 1, 256, true); number(item.height, 1, 256, true); pixels += item.width * item.height;
    for (const [map, key] of [[groupSplits, item.group_id], [pixelSplits, item.pixel_sha256]] as const) {
      const id = key as string; ensure(!map.has(id) || map.get(id) === item.split, '数据集存在跨分区泄漏。'); map.set(id, item.split);
    }
  }
  ensure(pixels <= 1_000_000);
  ensure(normalMembers.size === Object.keys(attestations).length);
  const fingerprints = shape(row.split_fingerprints, ['train', 'val', 'test']);
  const records = samples as LearningSample[];
  for (const split of ['train', 'val', 'test'] as const) {
    sha(fingerprints[split]);
    const members = records.filter(sample => sample.split === split).map(sample => ({ group_id: sample.group_id, category: sample.category, pixel_sha256: sample.pixel_sha256, mask_pixel_sha256: sample.mask_pixel_sha256 }));
    ensure(members.length > 0); members.sort((a, b) => utf8Compare(canonicalizeJcs(a), canonicalizeJcs(b)));
    ensure(await hash(members) === fingerprints[split], '数据集分区指纹不匹配。');
  }
  sha(row.labels_sha256);
  ensure(await hash(records.map(({ sample_id, mask_sha256, mask_pixel_sha256 }) => ({ sample_id, mask_sha256, mask_pixel_sha256 }))) === row.labels_sha256, '数据集标签指纹不匹配。');
  await receipt(row, undefined, ['dataset_id', 'receipt_sha256']);
  ensure(row.dataset_id === `dataset_${String(row.receipt_sha256).slice(0, 24)}`, '数据集标识未绑定回执。');
  return row as unknown as LearningDataset;
}
const countKeys = ['tp', 'fp', 'tn', 'fn'] as const;
const metricKeys = ['dice', 'false_negative_rate', 'false_positive_rate', 'error_rate'] as const;
function metrics(value: unknown, prediction = false): LearningMetrics {
  const row = shape(value, [...countKeys, ...metricKeys, ...(prediction ? ['prediction_sha256', 'prediction_mask_sha256'] : [])]);
  for (const key of countKeys) number(row[key], 0, 1_000_000, true);
  const { tp, fp, tn, fn } = row as unknown as LearningMetrics;
  const expected = [2 * tp + fp + fn ? 2 * tp / (2 * tp + fp + fn) : null, tp + fn ? fn / (tp + fn) : null, fp + tn ? fp / (fp + tn) : null, tp + fp + tn + fn ? (fp + fn) / (tp + fp + tn + fn) : null];
  metricKeys.forEach((key, index) => {
    const measured = row[key]; const calculated = expected[index];
    if (calculated === null) ensure(measured === null, '未测得指标不能替换为零或预设效果。');
    else { number(measured, 0, 1); ensure(Math.abs(measured - calculated!) < 1e-12, '评估指标与像素计数不一致。'); }
  });
  if (prediction) { sha(row.prediction_sha256); sha(row.prediction_mask_sha256); }
  return row as unknown as LearningMetrics;
}
function metricPair(value: unknown): { candidate: LearningMetrics; baseline: LearningMetrics } {
  const row = shape(value, ['candidate', 'baseline']); metrics(row.candidate); metrics(row.baseline);
  return row as unknown as { candidate: LearningMetrics; baseline: LearningMetrics };
}
function sampleEvidence(value: unknown): LearningSampleEvidence {
  const row = shape(value, ['sample_id', 'category', 'group_id', 'truth_mask_sha256', 'candidate', 'baseline', 'error_candidate', 'review_status', 'annotation_error_confirmed']);
  for (const key of ['sample_id', 'category', 'group_id']) text(row[key], 512);
  sha(row.truth_mask_sha256); const candidate = metrics(row.candidate, true); metrics(row.baseline, true);
  ensure(row.error_candidate === Boolean(candidate.fp + candidate.fn) && row.review_status === 'PENDING_HUMAN_REVIEW' && row.annotation_error_confirmed === false, '错误候选不能自动认定为标注错误。');
  return row as unknown as LearningSampleEvidence;
}
export function validateLearningEvaluation(value: unknown, expectedSplit?: 'val' | 'test'): LearningEvaluation {
  const row = shape(value, ['schema_version', 'split', 'policy', 'aggregate', 'categories', 'sample_results', 'latency', 'decision', 'blockers', 'observed_elapsed_seconds']);
  ensure(row.schema_version === 'visiondata-gate.learning-evaluation.v1'); member(row.split, ['val', 'test']);
  if (expectedSplit) ensure(row.split === expectedSplit, '学习评估分区不匹配。');
  evaluationPolicy(row.policy); const aggregate = metricPair(row.aggregate); const categories = object(row.categories);
  ensure(Object.keys(categories).length >= 1 && Object.keys(categories).length <= 64);
  for (const [category, pair] of Object.entries(categories)) { text(category, 512); metricPair(pair); }
  const samples = array(row.sample_results, 64); samples.forEach(sampleEvidence);
  ensure(row.split === 'test' ? samples.length === 0 : samples.length > 0, '最终测试不得泄露逐样本反馈。');
  ensure(new Set(samples.map(sample => object(sample).sample_id)).size === samples.length);
  const latency = shape(row.latency, ['scope', 'timer', 'measurement', 'model_order', 'observations_per_sample', 'warmup_runs', 'quantile_method', 'benchmark_claim', 'candidate', 'baseline']);
  ensure(latency.scope === 'LOCAL_CPU_OBSERVATION_ONLY' && latency.timer === 'time.perf_counter' && latency.measurement === 'predict_call_only' && latency.observations_per_sample === 1 && latency.warmup_runs === 0 && latency.quantile_method === 'linear' && latency.benchmark_claim === false, '本地单次耗时观测不能升级为设备性能结论。');
  ensure(JSON.stringify(latency.model_order) === '["candidate","baseline"]');
  for (const model of ['candidate', 'baseline']) {
    const observation = shape(latency[model], ['sample_count', 'p95_ms']); number(observation.sample_count, 1, 64, true); number(observation.p95_ms);
    if (row.split === 'val') ensure(observation.sample_count === samples.length);
  }
  number(row.observed_elapsed_seconds); member(row.decision, ['HOLD', 'ELIGIBLE']);
  const blockers = array(row.blockers, 1000); blockers.forEach(item => text(item, 2000));
  ensure(row.decision === 'HOLD' ? blockers.length > 0 : blockers.length === 0, '评估决定与阻断证据不一致。');
  if (row.decision === 'ELIGIBLE') {
    const policy = row.policy as unknown as LearningEvaluationPolicy;
    const candidate = aggregate.candidate; const baseline = aggregate.baseline;
    for (const pair of [aggregate, ...Object.values(categories).map(metricPair)]) for (const model of [pair.candidate, pair.baseline]) for (const key of ['dice', 'false_negative_rate', 'false_positive_rate'] as const) ensure(model[key] !== null, '缺少实测证据，不能放行候选模型。');
    ensure(candidate.false_negative_rate! <= policy.max_false_negative_rate && candidate.false_positive_rate! <= policy.max_false_positive_rate && candidate.dice! >= policy.min_dice && candidate.dice! - baseline.dice! > 0 && candidate.dice! - baseline.dice! >= policy.min_dice_gain, '候选效果不满足冻结评估策略。');
    for (const pair of Object.values(categories).map(metricPair)) ensure(pair.baseline.dice! - pair.candidate.dice! <= policy.max_category_dice_regression);
    ensure((latency.candidate as { p95_ms: number }).p95_ms <= policy.max_p95_latency_ms);
  }
  return row as unknown as LearningEvaluation;
}
async function feedback(value: unknown, scope: LearningScope): Promise<LearningFeedback> {
  const row = shape(value, ['feedback_id', 'status', 'evidence', 'classification', 'next_action', 'training_ingestion_allowed', 'followup_task_id'], ['reviewed_by', 'review_note', 'followup_status', 'followup']);
  identifier(row.feedback_id); const evidence = sampleEvidence(row.evidence); ensure(evidence.error_candidate);
  member(row.status, ['PENDING_HUMAN_REVIEW', 'TRIAGED_NOT_AUTO_INGESTED']);
  ensure(row.training_ingestion_allowed === false, '错误反馈不得自动进入训练集。'); nullableId(row.followup_task_id);
  if (row.status === 'PENDING_HUMAN_REVIEW') ensure(row.classification === null && row.next_action === 'INVESTIGATE' && row.followup_task_id === null && !('reviewed_by' in row) && !('review_note' in row));
  else {
    member(row.classification, classifications); ensure(row.next_action === classificationActions[row.classification]); text(row.reviewed_by, 512); text(row.review_note, 2000, 8);
  }
  if ('followup' in row || 'followup_status' in row) {
    ensure(row.status === 'TRIAGED_NOT_AUTO_INGESTED' && row.followup_status === 'NEW_GATE_EVIDENCE_LINKED_NOT_ISSUE_CLOSED');
    const linked = shape(row.followup, ['binding', 'preflight_receipt_sha256', 'sample_ids', 'members', 'reviewed_by', 'review_note', 'at', 'issue_closed', 'training_ingestion_allowed', 'boundary', 'receipt_sha256']);
    const bound = binding(linked.binding, scope); ensure(bound.task_id === row.followup_task_id); sha(linked.preflight_receipt_sha256);
    const declared = sampleIds(linked.sample_ids); const members = array(linked.members, 64); ensure(members.length === declared.length);
    for (const [index, memberValue] of members.entries()) {
      const item = shape(memberValue, ['sample_id', 'split', 'image_sha256', 'annotation_revision', 'annotation_document_sha256', 'mask_sha256']);
      ensure(item.sample_id === declared[index]); member(item.split, ['train', 'val', 'test']); sha(item.image_sha256); sha(item.annotation_document_sha256);
      number(item.annotation_revision, 0, Number.MAX_SAFE_INTEGER, true); if (item.mask_sha256 !== null) sha(item.mask_sha256);
    }
    text(linked.reviewed_by, 512); text(linked.review_note, 2000, 8); timestamp(linked.at); text(linked.boundary);
    ensure(linked.issue_closed === false && linked.training_ingestion_allowed === false, '关联新证据不等于问题解决或自动训练授权。');
    await receipt(linked);
  }
  return row as unknown as LearningFeedback;
}
export async function validateLearningCycle(value: unknown, scope: LearningScope, cycleId?: string, etag?: string | null): Promise<LearningCycle> {
  const finalKeys = ['final_candidate_model_id', 'final_candidate_model_sha256', 'final_baseline_model_id', 'final_baseline_model_sha256', 'final_candidate_accepted'];
  const row = shape(value, ['schema_version', 'cycle_id', 'project_id', 'workspace_id', 'created_by', 'created_at', 'updated_at', 'revision', 'status', 'request', 'dataset', 'dataset_storage_key', 'evaluation_fingerprints', 'initial_model_id', 'champion_model_id', 'approved_model_ids', 'round_ids', 'epochs_reserved', 'wall_seconds_reserved', 'events', 'production_release_allowed', 'machine_write_permitted', 'remote_execution_verified', 'scope', 'receipt_sha256'], ['final_evaluation', 'final_evaluation_sha256', 'final_test_failure', ...finalKeys]);
  ensure(row.schema_version === 'visiondata-gate.learning-cycle.v1'); scopeCheck(row, scope); identifier(row.cycle_id);
  if (cycleId !== undefined) ensure(row.cycle_id === cycleId, '学习周期标识不匹配。');
  member(row.status, ['READY', 'RUNNING', 'AWAITING_REVIEW', 'AWAITING_DATA', 'HOLD_REQUIRES_NEW_PROTOCOL', 'STOPPED', 'FINALIZING', 'FINALIZED']);
  ensure(row.production_release_allowed === false && row.machine_write_permitted === false && row.remote_execution_verified === false && row.scope === 'LOCAL_SUPERVISED_REFERENCE_MODEL_SANDBOX', '学习周期越过本地沙盒权限。');
  text(row.created_by, 512); timestamp(row.created_at); timestamp(row.updated_at); number(row.revision, 0, Number.MAX_SAFE_INTEGER, true);
  validateCreateLearningRequest(row.request); const request = object(row.request); trainingConfig(request.training); evaluationPolicy(request.evaluation);
  number(request.max_rounds, 1, 10, true); number(request.max_total_epochs, 1, 2000, true); number(request.max_total_wall_seconds, Number.MIN_VALUE, 600);
  const dataset = await validateLearningDataset(row.dataset, scope); identifier(row.dataset_storage_key);
  const fingerprints = shape(row.evaluation_fingerprints, ['val', 'test']);
  ensure(fingerprints.val === dataset.split_fingerprints.val && fingerprints.test === dataset.split_fingerprints.test, '冻结评估分区发生漂移。');
  identifier(row.initial_model_id); identifier(row.champion_model_id); const approved = ids(row.approved_model_ids, 11); const rounds = ids(row.round_ids, request.max_rounds);
  ensure(approved.includes(row.initial_model_id) && approved.includes(row.champion_model_id));
  number(row.epochs_reserved, 0, request.max_total_epochs, true); number(row.wall_seconds_reserved, 0, request.max_total_wall_seconds + 1e-9);
  if (rounds.length === 0) ensure(row.status !== 'RUNNING' && row.status !== 'AWAITING_REVIEW');
  for (const event of array(row.events)) { const item = shape(event, ['event', 'actor', 'at']); text(item.event, 120); text(item.actor, 512); timestamp(item.at); }
  if (row.status === 'FINALIZED') ensure('final_evaluation' in row && 'final_evaluation_sha256' in row);
  if ('final_evaluation' in row || 'final_evaluation_sha256' in row) {
    ensure(row.status === 'FINALIZED'); validateLearningEvaluation(row.final_evaluation, 'test'); sha(row.final_evaluation_sha256);
    ensure(await hash(row.final_evaluation) === row.final_evaluation_sha256, '最终测试摘要不匹配。');
  }
  if ('final_test_failure' in row) ensure(row.status === 'STOPPED' && row.final_test_failure === 'FINAL_TEST_FAILED_NOT_RETRIED');
  if (finalKeys.some(key => key in row)) {
    ensure(row.status === 'FINALIZED' && finalKeys.every(key => key in row));
    identifier(row.final_candidate_model_id); identifier(row.final_baseline_model_id); sha(row.final_candidate_model_sha256); sha(row.final_baseline_model_sha256);
    ensure(approved.includes(row.final_candidate_model_id) && approved.includes(row.final_baseline_model_id));
    ensure(row.final_candidate_accepted === (object(row.final_evaluation).decision === 'ELIGIBLE'));
    ensure(row.champion_model_id === (row.final_candidate_accepted ? row.final_candidate_model_id : row.final_baseline_model_id), '最终测试未接受的候选不得保留为沙箱冠军。');
  }
  await receipt(row, etag); return row as unknown as LearningCycle;
}
export async function validateLearningRun(value: unknown, scope: LearningScope, cycleId: string, runId?: string, etag?: string | null): Promise<LearningRun> {
  const row = shape(value, ['schema_version', 'run_id', 'cycle_id', 'project_id', 'round_number', 'retry_of_run_id', 'feedback_parent_run_id', 'responds_to_feedback_ids', 'feedback_response_boundary', 'status', 'dataset_id', 'dataset_receipt_sha256', 'dataset_storage_key', 'binding', 'initial_model_id', 'initial_model_sha256', 'configuration', 'approval', 'approved_by', 'started_at', 'feedback', 'selection', 'cancel_requested', 'production_release_allowed', 'remote_execution_verified', 'receipt_sha256'], ['completed_at', 'training', 'model_id', 'model_sha256', 'evaluation', 'evaluation_sha256', 'elapsed_seconds', 'failure_code', 'failure_type', 'previous_run_id']);
  ensure(row.schema_version === 'visiondata-gate.learning-run.v1'); identifier(cycleId); identifier(row.run_id);
  ensure(row.project_id === scope.projectId && row.cycle_id === cycleId && (runId === undefined || row.run_id === runId), '学习轮次不属于当前项目、周期或轮次。');
  const bound = binding(row.binding, scope); member(row.status, ['RUNNING', 'COMPLETED', 'FAILED', 'CANCELLED', 'INTERRUPTED']);
  ensure(row.production_release_allowed === false && row.remote_execution_verified === false, '学习轮次越过本地执行权限。');
  number(row.round_number, 1, 10, true); nullableId(row.retry_of_run_id); nullableId(row.feedback_parent_run_id); ids(row.responds_to_feedback_ids, 64); text(row.feedback_response_boundary);
  sha(row.dataset_receipt_sha256); ensure(row.dataset_id === `dataset_${row.dataset_receipt_sha256.slice(0, 24)}`); identifier(row.dataset_storage_key);
  identifier(row.initial_model_id); sha(row.initial_model_sha256); trainingConfig(row.configuration); const approval = validateRoundLearningRequest(row.approval);
  if ('previous_run_id' in row) nullableId(row.previous_run_id);
  if (approval.responds_to_feedback_ids !== undefined) ensure(JSON.stringify(row.responds_to_feedback_ids) === JSON.stringify(approval.responds_to_feedback_ids), '反馈关联必须来自该轮显式请求。');
  ensure(approval.task_id === bound.task_id); text(row.approved_by, 512); timestamp(row.started_at); ensure(typeof row.cancel_requested === 'boolean');
  if ('completed_at' in row) { timestamp(row.completed_at); ensure(row.status !== 'RUNNING'); }
  if ('elapsed_seconds' in row) { number(row.elapsed_seconds); ensure(row.status !== 'RUNNING'); }
  if ('failure_code' in row || 'failure_type' in row) {
    ensure(row.status === 'FAILED' || row.status === 'CANCELLED');
    ensure(row.failure_code === 'LOCAL_EXECUTION_FAILED'); text(row.failure_type, 120);
  }
  const items = await Promise.all(array(row.feedback, 64).map(item => feedback(item, scope))); ensure(new Set(items.map(item => item.feedback_id)).size === items.length);
  if (row.status === 'COMPLETED') {
    timestamp(row.completed_at); identifier(row.model_id); sha(row.model_sha256); sha(row.evaluation_sha256); number(row.elapsed_seconds);
    const evaluation = validateLearningEvaluation(row.evaluation, 'val'); ensure(await hash(evaluation) === row.evaluation_sha256, '轮次评估摘要不匹配。');
    const training = shape(row.training, ['loss_before', 'loss_after', 'epochs_completed', 'training_sample_ids', 'training_pixel_count', 'elapsed_seconds', 'initial_model_sha256', 'optimizer', 'device']);
    number(training.loss_before); number(training.loss_after); number(training.epochs_completed, 1, 500, true); number(training.training_pixel_count, 1, 1_000_000, true); number(training.elapsed_seconds);
    const sampleIds = array(training.training_sample_ids, 64); ensure(sampleIds.length > 0); sampleIds.forEach(item => text(item, 512)); ensure(new Set(sampleIds).size === sampleIds.length);
    ensure(training.initial_model_sha256 === row.initial_model_sha256 && training.epochs_completed === object(row.configuration).epochs && training.optimizer === 'full_batch_gradient_descent' && training.device === 'CPU');
    const errors = evaluation.sample_results.filter(sample => sample.error_candidate);
    ensure(errors.length === items.length && errors.every(sample => items.some(item => canonicalizeJcs(item.evidence) === canonicalizeJcs(sample))), '反馈未绑定该轮验证样本证据。');
  } else {
    ensure(items.length === 0 && row.selection === null);
    for (const key of ['training', 'model_id', 'model_sha256', 'evaluation', 'evaluation_sha256']) ensure(!(key in row), '未完成轮次不能携带已完成模型或评估。');
    if (row.status !== 'RUNNING') timestamp(row.completed_at);
    if (row.status === 'INTERRUPTED') ensure(row.cancel_requested === true);
    if (row.status === 'FAILED' || row.status === 'CANCELLED') { ensure(row.failure_code === 'LOCAL_EXECUTION_FAILED'); text(row.failure_type, 120); number(row.elapsed_seconds); }
  }
  if (row.selection !== null) {
    const selection = shape(row.selection, ['action', 'actor', 'note', 'evaluation_sha256', 'at'], ['continual_retention_receipt_sha256']); member(selection.action, ['APPROVE_SANDBOX', 'APPROVE_SANDBOX_CONTINUAL', 'REJECT']);
    text(selection.actor, 512); text(selection.note, 2000, 8); timestamp(selection.at); ensure(selection.evaluation_sha256 === row.evaluation_sha256 && items.every(item => item.status === 'TRIAGED_NOT_AUTO_INGESTED'));
    const continual = selection.action === 'APPROVE_SANDBOX_CONTINUAL';
    ensure(continual === ('continual_retention_receipt_sha256' in selection), '持续学习选择回执缺少或错误携带 Retention Receipt。');
    if (continual) sha(selection.continual_retention_receipt_sha256);
    if (selection.action === 'APPROVE_SANDBOX' || continual) ensure(object(row.evaluation).decision === 'ELIGIBLE');
  }
  await receipt(row, etag); return row as unknown as LearningRun;
}

function findingRefs(value: unknown): LearningFindingRef[] {
  return array(value).map(item => {
    const row = shape(item, ['finding_id', 'code', 'severity', 'finding_sha256']); text(row.finding_id, 512); text(row.code, 512);
    member(row.severity, ['critical', 'high', 'medium', 'low']); sha(row.finding_sha256); return row as unknown as LearningFindingRef;
  });
}
export async function validateLearningReadiness(value: unknown, scope: LearningScope, taskId: string, etag?: string | null): Promise<LearningReadiness> {
  const row = shape(value, ['schema_version', 'task_id', 'project_id', 'workspace_id', 'projection_status', 'preflight_receipt_sha256', 'preflight_eligibility', 'blockers', 'members', 'global_findings', 'unmapped_finding_refs', 'training_authorized', 'production_release_allowed', 'annotation_review_basis', 'required_dataset_validation', 'claim_boundary', 'receipt_sha256']);
  ensure(row.schema_version === 'visiondata-gate.learning-readiness.v1'); scopeCheck(row, scope); identifier(taskId); ensure(row.task_id === taskId);
  member(row.projection_status, ['UNVERIFIED', 'VERIFIED']); member(row.preflight_eligibility, ['UNVERIFIED', 'HOLD', 'READY_FOR_OFFLINE_HANDOFF']);
  if (row.preflight_receipt_sha256 === null) ensure(row.preflight_eligibility === 'UNVERIFIED'); else sha(row.preflight_receipt_sha256);
  const blockers = array(row.blockers); blockers.forEach(value => ensure(typeof value === 'string' && /^[A-Z][A-Z0-9_]{0,100}$/.test(value)));
  ensure(new Set(blockers).size === blockers.length);
  const members = array(row.members); const memberIds = new Set<string>();
  let unverified = members.length === 0;
  for (const value of members) {
    const item = shape(value, ['sample_id', 'split', 'category', 'annotation_requirement', 'mask_available', 'readiness_state', 'finding_refs']);
    text(item.sample_id, 512); text(item.category, 512); member(item.split, ['train', 'val', 'test']);
    member(item.annotation_requirement, ['REQUIRED', 'OPTIONAL', 'NOT_APPLICABLE', 'UNKNOWN']);
    ensure(typeof item.mask_available === 'boolean' || item.mask_available === null);
    member(item.readiness_state, ['UNVERIFIED_FINDING_IDENTITY', 'UNVERIFIED_TOOL_FAILURE', 'UNVERIFIED', 'NEEDS_ATTENTION', 'MASK_REQUIRED_FOR_REFERENCE_TRAINER', 'BLOCKED_BY_BATCH', 'GATE_ELIGIBLE_NOT_TRAINING_APPROVED']);
    const refs = findingRefs(item.finding_refs); ensure(!memberIds.has(item.sample_id)); memberIds.add(item.sample_id);
    if (item.readiness_state.startsWith('UNVERIFIED')) unverified = true;
    if (item.readiness_state === 'GATE_ELIGIBLE_NOT_TRAINING_APPROVED') ensure(row.preflight_eligibility === 'READY_FOR_OFFLINE_HANDOFF' && item.mask_available === true && refs.length === 0);
    if (item.readiness_state === 'MASK_REQUIRED_FOR_REFERENCE_TRAINER') ensure(item.mask_available === false);
    if (item.readiness_state === 'NEEDS_ATTENTION') ensure(refs.length > 0);
  }
  ensure(row.projection_status === (unverified ? 'UNVERIFIED' : 'VERIFIED'));
  findingRefs(row.global_findings); findingRefs(row.unmapped_finding_refs);
  ensure(row.training_authorized === false && row.production_release_allowed === false && row.annotation_review_basis === 'OPERATOR_ATTESTATION_NOT_INDEPENDENT_TRUTH', '准备情况不得授予训练或标签真值权限。');
  ensure(JSON.stringify(row.required_dataset_validation) === JSON.stringify(['GROUP_DECLARATIONS', 'BINARY_MASK_VALUES', 'TRAIN_VAL_TEST_COVERAGE', 'GROUP_AND_PIXEL_SPLIT_ISOLATION', 'IMAGE_MASK_SHAPES_AND_RESOURCE_LIMITS']));
  text(row.claim_boundary, 4000); await receipt(row, etag); return row as unknown as LearningReadiness;
}
const operationKinds: Record<LearningOperationName, 'cycle' | 'run'> = { create: 'cycle', train: 'run', feedback: 'run', followup: 'run', select: 'cycle', rollback: 'cycle', cancel: 'cycle', recover: 'cycle', finalize: 'cycle' };
export async function validateLearningOperation(value: unknown, scope: LearningScope, operation: LearningOperationName, requestKey: string, targetId: string, etag?: string | null): Promise<LearningOperation> {
  const row = shape(value, ['schema_version', 'project_id', 'operation', 'request_key', 'target_id', 'lookup_status', 'request_sha256', 'request_digest_semantics', 'request_digest_verification', 'result_semantics', 'result_kind', 'result_id', 'result_receipt_sha256', 'current_result', 'execution_status', 'automatic_retry_allowed', 'receipt_sha256']);
  identifier(scope.workspaceId); identifier(scope.projectId); identifier(targetId); ensure(/^[A-Za-z0-9_-]{12,100}$/.test(requestKey));
  member(operation, Object.keys(operationKinds) as LearningOperationName[]);
  ensure(row.schema_version === 'visiondata-gate.learning-operation.v1' && row.project_id === scope.projectId && row.operation === operation && row.request_key === requestKey && row.target_id === targetId, '学习操作回执未绑定指定请求与目标。');
  member(row.lookup_status, ['NOT_FOUND', 'FOUND']);
  ensure(row.automatic_retry_allowed === false && row.request_digest_semantics === 'SERVER_CANONICAL_VALIDATED_REQUEST' && row.result_semantics === 'CURRENT_RESULT', '对账不得自动重发，也不代表原响应已复原。');
  if (row.lookup_status === 'NOT_FOUND') {
    for (const key of ['request_sha256', 'result_kind', 'result_id', 'result_receipt_sha256', 'current_result']) ensure(row[key] === null);
    ensure(row.request_digest_verification === 'NOT_AVAILABLE' && row.execution_status === 'UNKNOWN_NOT_PROOF_OF_NO_WRITE');
  } else {
    sha(row.request_sha256); sha(row.result_receipt_sha256); identifier(row.result_id); ensure(row.result_kind === operationKinds[operation]);
    const current = object(row.current_result); identifier(current.cycle_id);
    const result = row.result_kind === 'cycle'
      ? await validateLearningCycle(current, scope, current.cycle_id)
      : await validateLearningRun(current, scope, current.cycle_id, row.result_id);
    ensure(row.result_id === (row.result_kind === 'cycle' ? result.cycle_id : (result as LearningRun).run_id) && row.result_receipt_sha256 === result.receipt_sha256);
    ensure(row.execution_status === (['RUNNING', 'FINALIZING'].includes(result.status) ? 'PENDING' : 'RESULT_AVAILABLE'));
    if (['train', 'rollback', 'cancel', 'recover', 'finalize'].includes(operation)) ensure(result.cycle_id === targetId);
    if (operation === 'select') ensure((result as LearningCycle).round_ids.includes(targetId));
    if (operation === 'feedback' || operation === 'followup') ensure((result as LearningRun).feedback.some(item => item.feedback_id === targetId));
    if (operation === 'create' || operation === 'train') {
      ensure(row.request_digest_verification === 'MATCHED_STORED_VALIDATED_REQUEST');
      // The server hashes a validated request with defaults. Reconstruct only the
      // canonical request for this check; never modify or re-seal the response.
      const request = operation === 'create' ? (result as LearningCycle).request : (result as LearningRun).approval;
      const canonicalRequest = { ...request, normal_mask_attestations: request.normal_mask_attestations ?? {}, ...(operation === 'train' ? { responds_to_feedback_ids: (request as RoundLearningRequest).responds_to_feedback_ids ?? [] } : {}) };
      ensure(request.request_key === requestKey && await hash(canonicalRequest) === row.request_sha256, '服务端规范化请求摘要不匹配。');
    } else ensure(row.request_digest_verification === 'LEDGER_SHA_ONLY');
  }
  await receipt(row, etag); return row as unknown as LearningOperation;
}
