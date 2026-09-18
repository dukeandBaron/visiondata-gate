import { canonicalizeJcs, sha256HexUtf8 } from './data/jcs.ts';

/** Local visual-model contracts, deliberately separate from LLM providers. */
export interface VisionScope { workspaceId: string; projectId: string; actorId: string }
export type VisionKind = 'model' | 'runtime' | 'dataset' | 'run' | 'inference_asset' | 'inference';
export type VisionOperation = 'register_model' | 'register_normality_model_pack' | 'register_runtime' | 'register_dataset' | 'register_pool_dataset'
  | 'register_inference_asset' | 'create_training_run' | `probe_runtime:${string}` | `cancel:${string}` | `recover:${string}` | `selection:${string}`
  | `approve_normality_model_pack:${string}` | `run_normality_inference:${string}`;
export type VisionMutationOperation = VisionOperation | `triage_feedback:${string}`;
export interface VisionPending { operation: VisionMutationOperation; requestKey: string }
export interface VisionApproval { request_key: string; reviewer_identity: string; note: string }
export interface VisionBudget { epochs: number; imgsz: number; batch: number; seed: number; max_seconds: number; threads: number }
export interface VisionBase {
  schema_version: string; resource_id: string; project_id: string; created_by: string;
  reviewer_identity: string; created_at: string; receipt_sha256: string;
  production_release_allowed: false; machine_write_permitted: false;
}
export interface VisionModelBase extends VisionBase {
  model_id: string; display_name: string; weights_sha256: string; format: 'pt' | 'onnx' | 'safetensors';
  license_id: string; license_status: string; loaded: false;
}
export interface VisionDetectionModel extends VisionModelBase {
  task_type: 'detect' | 'segment';
  file_bytes: number; format: 'pt' | 'onnx' | 'safetensors'; license_id: string; license_status: string;
  status: 'REGISTERED_NOT_LOADED' | 'CANDIDATE_REQUIRES_HUMAN_REVIEW' | 'APPROVE_SANDBOX' | 'REJECT'; loaded: false;
  source_description: string; training_run_id?: string;
}
export interface VisionNormalityModel extends VisionModelBase {
  model_kind: 'YOLO26_NORMALITY_MODEL_PACK'; task_type: 'normality'; format: 'pt'; model_pack_schema_version: 'visiondata-gate.yolo26-normality-model-pack.v2';
  model_pack_sha256: string; backbone_weights_sha256: string; source_binding_sha256: string; source_index_sha256: string;
  architecture: string; feature_layers: number[]; split_seed: number; model_seed: 20260913; stability_schema_version: 'visiondata-gate.model-stability.v4';
  verification_implementation: { stability_module_sha256: string; outcome_policy_module_sha256: string; outcome_policy_function: 'classify_experiment_outcome' };
  stability_run_artifact_sha256: Record<string, Record<string, string>>; stability_status: 'PUBLIC_PROXY_STABLE' | 'MODEL_PROMOTION_HOLD'; stability_eligible: boolean;
  stability_blockers: string[]; evidence_file_sha256: Record<string, string>; status: 'MODEL_PACK_EVIDENCE_VERIFIED' | 'RESEARCH_ONLY_HOLD' | 'APPROVE_SANDBOX' | 'REJECT';
  usage_scope: 'SANDBOX_CANDIDATE' | 'RESEARCH_ONLY' | 'LOCAL_SANDBOX_ONLY'; sandbox_eligible: boolean; sandbox_runtime_id: string | null; sandbox_runtime_sha256: string | null;
  sandbox_validation?: Record<string, unknown>; storage_scope: 'REGISTRY_OWNED_CONTENT_ADDRESSED';
}
export type VisionModel = VisionDetectionModel | VisionNormalityModel;
export interface VisionRuntime extends VisionBase {
  runtime_id: string; display_name: string; executable_sha256: string; runtime_sha256: string;
  status: string; probe: { status: 'ready' | 'unavailable'; import_status: 'NOT_RUN' | 'PASSED' | 'FAILED';
    runtime_sha256: string; executable_sha256: string; packages: Record<string, string | null>; python_version: number[] };
}
export interface DetectionBox { class_id: number; x_center: number; y_center: number; width: number; height: number }
export interface DetectionSample {
  sample_id: string; image_path: string; image_sha256: string; split: 'train' | 'val' | 'test';
  group_id: string; annotation_revision: number; boxes: DetectionBox[]; reviewer_name: string; reviewed: true; normal_attested?: boolean;
}
export interface DetectionManifest {
  schema_version: 'visiondata-gate.detection-dataset.v1'; source_version: string; class_names: string[]; samples: DetectionSample[];
}
export interface DetectionReceipt {
  schema_version: 'visiondata-gate.detection-dataset-receipt.v1'; source_version: string; class_names: string[];
  dataset_id: string; manifest_sha256: string; receipt_sha256: string; data_yaml_sha256: string;
  samples: (DetectionSample & { pixel_sha256: string; label_sha256: string; label_path: string; width: number; height: number })[];
  split_counts: Record<'train' | 'val' | 'test', number>;
}
export interface VisionDataset extends VisionBase {
  dataset_id: string; dataset_receipt_sha256: string; status: 'FROZEN_REVIEWED_DETECTION_DATASET'; dataset_receipt: DetectionReceipt;
  pool_binding?: PoolDetectionBinding;
}
export interface PoolDetectionBinding {
  schema_version: 'visiondata-gate.pool-detection-binding.v1'; project_id: string; pool_id: string; version_id: string; task_id: string;
  pool_receipt_sha256: string; version_receipt_sha256: string; class_names: string[]; class_mapping_sha256: string;
  groups: Record<string, string>; normal_sample_ids: string[]; detection_manifest_sha256: string;
  sample_count: number; production_release_allowed: false; label_truth_authority: false; receipt_sha256: string;
}
export type VisionRunStatus = 'QUEUED' | 'RUNNING' | 'SUCCEEDED_CANDIDATE' | 'FAILED' | 'CANCELLED' | 'TIMED_OUT' | 'INTERRUPTED_HOLD';
export interface VisionTrainingResult {
  status: string; device: 'cpu'; production_approved: false; test_evaluation: 'NOT_RUN';
  baseline?: Record<string, number>; candidate?: Record<string, number>; actual_epochs?: number;
  training_samples?: number; validation_samples?: number; elapsed_seconds?: number;
  checkpoint?: { relative_path: string; sha256: string; bytes: number; round_trip: 'VERIFIED'; selection: 'last_epoch' };
  validation_feedback_protocol?: Record<string, unknown>; validation_samples_detail?: FeedbackDetail[];
}
export interface VisionRun extends VisionBase {
  run_id: string; status: VisionRunStatus; runtime_id: string; runtime_sha256: string;
  dataset_id: string; dataset_receipt_sha256: string; initial_model_id: string | null;
  initialization: 'ARCHITECTURE_RANDOM' | 'REGISTERED_WEIGHTS'; pretrained_claimed: false; architecture: 'yolo26n';
  device: 'cpu'; training: VisionBudget; adaptation: 'OFF'; ttt_status: 'DISABLED_NOT_IMPLEMENTED';
  authorization_sha256: string; cancel_requested: boolean; candidate_model_id: string | null;
  selection: 'PENDING' | 'APPROVE_SANDBOX' | 'REJECT'; result: VisionTrainingResult | null; error_code: string | null;
  responds_to_feedback_ids?: string[]; feedback_ids?: string[];
  feedback_status?: 'NOT_EVALUATED' | 'NOT_AVAILABLE_LEGACY_RESULT' | 'VAL_DISAGREEMENTS_REQUIRE_HUMAN_REVIEW' | 'NO_VAL_DISAGREEMENT_AT_FIXED_PROTOCOL';
}
export interface VisionInferenceAsset extends VisionBase {
  schema_version: 'visiondata-gate.vision_inference_asset.v1'; asset_id: string; display_name: string; image_sha256: string; image_bytes: number;
  image_width: number; image_height: number; format: 'png' | 'jpg' | 'jpeg' | 'bmp'; storage_scope: 'REGISTRY_OWNED_CONTENT_ADDRESSED'; status: 'FROZEN_LOCAL_INFERENCE_ASSET';
}
export interface VisionHeatmap { sha256: string; bytes: number; width: number; height: number; format: 'png' }
export interface VisionInference extends VisionBase {
  schema_version: 'visiondata-gate.vision_inference.v1'; inference_id: string; model_id: string; asset_id: string; runtime_id: string;
  model_pack_sha256: string; backbone_weights_sha256: string; source_binding_sha256: string; source_index_sha256: string; runtime_sha256: string;
  inference_backend_sha256: string; image_sha256: string; status: 'COMPLETED_LOCAL_SANDBOX_INFERENCE'; image_score: number; image_threshold: number;
  pixel_threshold: number; predicted_anomaly: boolean; positive_pixel_fraction: number; heatmap_artifact_id: string; heatmap: VisionHeatmap; device: 'cpu';
  decision_scope: 'MODEL_SIGNAL_ONLY_NOT_GATE_OR_PRODUCTION_DECISION'; review_required: true; gate_decision: 'NOT_ISSUED';
}
export type VisionFeedbackClassification = 'MODEL_ERROR' | 'LABEL_REVIEW_REQUIRED' | 'HARD_SAMPLE' | 'UNKNOWN';
export interface FeedbackBox { class_id: number; xyxy: [number, number, number, number]; confidence?: number }
export interface FeedbackDetail {
  sample_id: string; image_sha256: string; label_sha256: string; prediction_boxes: FeedbackBox[]; ground_truth_boxes: FeedbackBox[];
  tp: number; fp: number; fn: number; matched_ious: number[]; matches: { prediction_index: number; ground_truth_index: number; iou: number }[];
  reason_codes: string[]; review_required: true;
}
export interface VisionFeedback {
  schema_version: 'visiondata-gate.vision-feedback.v1'; resource_id: string; feedback_id: string; project_id: string; run_id: string;
  dataset_id: string; dataset_receipt_sha256: string; sample_id: string; split: 'val'; image_sha256: string; label_sha256: string;
  checkpoint_sha256: string; protocol_sha256: string; detail: FeedbackDetail; receipt_sha256: string;
  status: 'PENDING_HUMAN_REVIEW' | 'TRIAGED_FOR_REVIEW'; classification: VisionFeedbackClassification | null;
  issue_closed: false; label_truth_authority: false; training_ingestion_allowed: false; production_release_allowed: false;
}
export type VisionRecord = VisionModel | VisionRuntime | VisionDataset | VisionRun | VisionInferenceAsset | VisionInference | VisionFeedback;
export interface VisionCapabilities {
  schema_version: string; project_id: string; receipt_sha256: string; model_domain: 'LOCAL_VISUAL_MODELS';
  llm_provider_managed: false; training_device: 'CPU_ONLY'; executable_training_tasks: ['detect']; executable_inference_tasks: ['normality'];
  supported_registration_tasks: ('detect' | 'segment' | 'normality')[]; normality_runtime: 'EXTERNAL_RUNTIME_REQUIRED';
  ttt_status: 'DISABLED_NOT_IMPLEMENTED'; weight_download_allowed: false; training_ready: boolean;
  registered_model_count: number; registered_runtime_count: number; registered_dataset_count: number;
  sandbox_approved_normality_model_count: number; registered_inference_asset_count: number; completed_normality_inference_count: number;
  production_release_allowed: false; industrial_effectiveness_status: 'NOT_EVALUATED'; training_authorization_required: true;
}
export interface VisionOperationReceipt {
  schema_version: string; project_id: string; operation: VisionMutationOperation; request_key: string;
  resource_id: string; resource: VisionRecord; auto_replayed: false; receipt_sha256: string;
}
export interface RegisterModelRequest extends VisionApproval {
  display_name: string; weights_path: string; expected_weights_sha256: string; task_type: 'detect' | 'segment';
  license_id: string; source_description: string; operator_attests_read_authorized: true;
}
export interface RegisterNormalityModelPackRequest extends VisionApproval {
  display_name: string; model_pack_path: string; expected_model_pack_sha256: string; run_directory: string; stability_run_directories: string[];
  target_model_seed: 20260913; stability_summary_path: string; expected_stability_summary_sha256: string; source_binding_path: string;
  expected_source_binding_file_sha256: string; expected_source_binding_sha256: string; source_index_path: string; expected_source_index_file_sha256: string;
  expected_source_index_sha256: string; backbone_weights_path: string; expected_backbone_weights_sha256: string; operator_attests_read_authorized: true;
  operator_attests_weights_only_load_authorized: true; ultralytics_license_acknowledged: true;
}
export interface ApproveNormalityModelPackRequest extends VisionApproval {
  action: 'APPROVE_SANDBOX' | 'REJECT'; expected_model_receipt_sha256: string; expected_model_pack_sha256: string; expected_backbone_weights_sha256: string;
  expected_source_binding_sha256: string; expected_source_index_sha256: string; runtime_id: string; expected_runtime_sha256: string; operator_attests_reviewed: true;
  operator_attests_trusted_runtime: true; operator_attests_execution_authorized: true; operator_attests_trusted_weights: true;
  operator_attests_weights_only_load_authorized: true; ultralytics_license_acknowledged: true;
}
export interface RegisterVisionInferenceAssetRequest extends VisionApproval {
  display_name: string; image_path: string; expected_image_sha256: string; operator_attests_read_authorized: true;
}
export interface RunNormalityInferenceRequest extends VisionApproval {
  expected_model_receipt_sha256: string; expected_model_pack_sha256: string; expected_backbone_weights_sha256: string; expected_source_binding_sha256: string;
  expected_source_index_sha256: string; expected_runtime_sha256: string; asset_id: string; expected_asset_receipt_sha256: string; expected_image_sha256: string;
  max_seconds: number; operator_attests_execution_authorized: true; operator_attests_trusted_runtime: true; operator_attests_trusted_weights: true;
  operator_attests_weights_only_load_authorized: true;
}
export interface RegisterRuntimeRequest extends VisionApproval {
  display_name: string; executable_path: string; expected_executable_sha256: string;
  operator_attests_trusted_runtime: true; operator_attests_execution_authorized: true;
}
export interface ProbeRuntimeRequest extends VisionApproval {
  expected_runtime_sha256: string; operator_attests_trusted_runtime: true; operator_attests_execution_authorized: true; import_check: boolean;
}
export interface RegisterDatasetRequest extends VisionApproval {
  source_root: string; manifest: DetectionManifest; expected_manifest_sha256: string; operator_attests_data_authorized: true;
}
export interface RegisterPoolDatasetRequest extends VisionApproval {
  pool_id: string; version_id: string; expected_pool_receipt_sha256: string; expected_version_receipt_sha256: string;
  class_names: string[]; groups: Record<string, string>; normal_sample_ids: string[]; operator_attests_data_authorized: true;
}
export interface CreateVisionRunRequest extends VisionApproval {
  runtime_id: string; expected_runtime_sha256: string; dataset_id: string; expected_dataset_receipt_sha256: string;
  initialization: 'ARCHITECTURE_RANDOM' | 'REGISTERED_WEIGHTS'; initial_model_id: string | null; expected_weights_sha256: string | null;
  architecture: 'yolo26n'; training: VisionBudget; adaptation: 'OFF'; operator_attests_training_authorized: true;
  operator_attests_trusted_runtime: true; operator_attests_trusted_weights: boolean; operator_attests_pickle_load_risk: boolean;
  ultralytics_license_acknowledged: true;
  responds_to_feedback_ids: string[]; expected_feedback_receipts: Record<string, string>;
}
export interface VisionRunActionRequest extends VisionApproval { expected_run_sha256: string; operator_attests_reviewed: true }
export interface SelectVisionRequest extends VisionRunActionRequest { action: 'APPROVE_SANDBOX' | 'REJECT'; expected_candidate_weights_sha256: string }
export interface ReviewVisionFeedbackRequest extends VisionRunActionRequest { expected_feedback_sha256: string; classification: VisionFeedbackClassification }

export class VisionContractError extends Error { readonly code = 'VISION_CONTRACT_HOLD'; constructor() { super('视觉模型回执未满足完整性或范围合同。'); } }
export function visionEnsure(condition: unknown): asserts condition { if (!condition) throw new VisionContractError(); }
export function visionObject(value: unknown): Record<string, unknown> {
  visionEnsure(value !== null && typeof value === 'object' && !Array.isArray(value));
  visionEnsure(Object.getPrototypeOf(value) === Object.prototype || Object.getPrototypeOf(value) === null);
  return value as Record<string, unknown>;
}
export function visionId(value: unknown): asserts value is string { visionEnsure(typeof value === 'string' && /^[A-Za-z0-9_-]{1,120}$/.test(value)); }
export function visionSha(value: unknown): asserts value is string { visionEnsure(typeof value === 'string' && /^[a-f0-9]{64}$/.test(value)); }
function text(value: unknown, min = 1, max = 2048): asserts value is string { visionEnsure(typeof value === 'string' && value.trim().length >= min && value.length <= max); }
function integer(value: unknown, min: number, max: number): asserts value is number { visionEnsure(typeof value === 'number' && Number.isSafeInteger(value) && value >= min && value <= max); }
function fields(value: Record<string, unknown>, required: string[], optional: string[] = []) {
  visionEnsure(required.every(key => Object.hasOwn(value, key)) && Object.keys(value).every(key => required.includes(key) || optional.includes(key)));
}
function portable(value: unknown): asserts value is string {
  text(value, 1, 512); visionEnsure(!/[\\:<>"|?*\x00-\x1f\x7f]/.test(value));
  visionEnsure(value.split('/').every(part => part && !['.', '..'].includes(part) && !/[. ]$/.test(part) && !/^(CON|PRN|AUX|NUL|COM[0-9]|LPT[0-9])(?:\.|$)/i.test(part)));
}
function metadata(value: unknown, max = 160): asserts value is string {
  text(value, 1, max); visionEnsure(value === value.trim() && !/^[\\/]|^[A-Za-z]:|[\x00-\x1f\x7f]/.test(value));
}
function privatePath(value: unknown) {
  text(value); visionEnsure((/^[A-Za-z]:[\\/]/.test(value) || /^\/(?!\/)/.test(value)) && !/[\x00-\x1f\x7f]/.test(value));
}
export function validateVisionScope(scope: VisionScope) { visionId(scope.workspaceId); visionId(scope.projectId); visionId(scope.actorId); }
export function validateVisionOperation(operation: unknown): asserts operation is VisionMutationOperation {
  visionEnsure(typeof operation === 'string' && (/^(register_model|register_normality_model_pack|register_runtime|register_dataset|register_pool_dataset|register_inference_asset|create_training_run)$/.test(operation)
    || /^(probe_runtime|cancel|recover|selection|approve_normality_model_pack|run_normality_inference):[A-Za-z0-9_-]{1,120}$/.test(operation)
    || /^triage_feedback:vfeedback_[0-9a-f]{24}$/.test(operation)));
}
export function visionPendingStorageKey(scope: VisionScope): string { validateVisionScope(scope); return `vision-model:pending:${scope.actorId}:${scope.workspaceId}:${scope.projectId}`; }
export function parseVisionPending(raw: string): VisionPending {
  const value = visionObject(JSON.parse(raw)); fields(value, ['operation', 'requestKey']); validateVisionOperation(value.operation);
  visionEnsure(typeof value.requestKey === 'string' && /^[A-Za-z0-9_-]{12,100}$/.test(value.requestKey));
  return { operation: value.operation, requestKey: value.requestKey };
}
export async function visionDigest(value: unknown): Promise<string> { try { return await sha256HexUtf8(canonicalizeJcs(value)); } catch { throw new VisionContractError(); } }
function noPrivateFields(value: unknown) {
  if (Array.isArray(value)) { value.forEach(noPrivateFields); return; }
  if (value && typeof value === 'object') for (const [key, item] of Object.entries(value)) {
    visionEnsure(!['weights_path', 'executable_path', 'source_root', 'dataset_root', 'model_pack_path', 'run_directory', 'stability_run_directories',
      'stability_summary_path', 'source_binding_path', 'source_index_path', 'backbone_weights_path', 'cas_path', 'output_root', 'heatmap_path',
      'private_body', 'access_token', 'authorization', 'session_token'].includes(key.toLowerCase()));
    if (key.toLowerCase() === 'image_path' && typeof item === 'string') visionEnsure(!(/^[A-Za-z]:[\\/]/.test(item) || /^\//.test(item) || /^\\\\/.test(item)));
    noPrivateFields(item);
  }
}
export async function verifyVisionSeal(value: unknown, etag?: string | null, contentSha?: string | null, exclude: string[] = []): Promise<Record<string, unknown>> {
  const object = visionObject(value); visionSha(object.receipt_sha256); noPrivateFields(object);
  const body = { ...object }; delete body.receipt_sha256; exclude.forEach(key => delete body[key]);
  visionEnsure(await visionDigest(body) === object.receipt_sha256);
  if (etag !== undefined) visionEnsure(etag === `"${object.receipt_sha256}"`);
  if (contentSha !== undefined) visionEnsure(contentSha === object.receipt_sha256);
  return object;
}
export function validateVisionBudget(value: unknown): VisionBudget {
  const v = visionObject(value); fields(v, ['epochs', 'imgsz', 'batch', 'seed', 'max_seconds', 'threads']);
  integer(v.epochs, 1, 5); integer(v.imgsz, 64, 320); visionEnsure(v.imgsz % 32 === 0);
  integer(v.batch, 2, 8); integer(v.seed, 0, 2147483647); integer(v.max_seconds, 10, 600); integer(v.threads, 1, 4);
  return v as unknown as VisionBudget;
}
export function validateDetectionManifest(value: unknown, frozen = false): DetectionManifest {
  const v = visionObject(value);
  if (!frozen) fields(v, ['schema_version', 'source_version', 'class_names', 'samples']);
  visionEnsure(v.schema_version === (frozen ? 'visiondata-gate.detection-dataset-receipt.v1' : 'visiondata-gate.detection-dataset.v1'));
  metadata(v.source_version); visionEnsure(Array.isArray(v.class_names) && v.class_names.length > 0 && v.class_names.length <= 64);
  v.class_names.forEach(name => metadata(name, 96)); visionEnsure(new Set(v.class_names).size === v.class_names.length);
  visionEnsure(Array.isArray(v.samples) && v.samples.length >= 3 && v.samples.length <= 64);
  const ids = new Set<string>(), paths = new Set<string>(); const groups = new Map<string, string>(), images = new Map<string, string>(), pixels = new Map<string, string>();
  const splits = new Set<string>();
  for (const sample of v.samples) {
    const s = visionObject(sample);
    fields(s, ['sample_id', 'image_path', 'image_sha256', 'split', 'group_id', 'annotation_revision', 'boxes', 'reviewer_name', 'reviewed'],
      ['normal_attested', ...(frozen ? ['pixel_sha256', 'label_sha256', 'label_path', 'width', 'height'] : [])]);
    visionEnsure(typeof s.sample_id === 'string' && /^[A-Za-z0-9][A-Za-z0-9_-]{0,95}$/.test(s.sample_id)); portable(s.sample_id);
    portable(s.image_path); visionEnsure(/\.(png|jpe?g|bmp)$/i.test(s.image_path)); visionSha(s.image_sha256);
    visionEnsure(typeof s.split === 'string' && ['train', 'val', 'test'].includes(s.split)); metadata(s.group_id); metadata(s.reviewer_name);
    integer(s.annotation_revision, 0, 2147483647); visionEnsure(s.reviewed === true && Array.isArray(s.boxes) && s.boxes.length <= 256);
    visionEnsure((s.normal_attested ?? false) === (s.boxes.length === 0));
    for (const raw of s.boxes) {
      const b = visionObject(raw); fields(b, ['class_id', 'x_center', 'y_center', 'width', 'height']); integer(b.class_id, 0, v.class_names.length - 1);
      for (const key of ['x_center', 'y_center', 'width', 'height']) visionEnsure(typeof b[key] === 'number' && Number.isFinite(b[key]) && b[key] >= 0 && b[key] <= 1);
      const box = b as unknown as DetectionBox;
      visionEnsure(box.width > 0 && box.height > 0 && box.x_center - box.width / 2 >= 0 && box.x_center + box.width / 2 <= 1 && box.y_center - box.height / 2 >= 0 && box.y_center + box.height / 2 <= 1);
    }
    const sid = s.sample_id.toLowerCase(), path = s.image_path.toLowerCase(); visionEnsure(!ids.has(sid) && !paths.has(path)); ids.add(sid); paths.add(path); splits.add(s.split);
    for (const [map, key] of [[groups, s.group_id], [images, s.image_sha256]] as const) { visionEnsure(!map.has(key) || map.get(key) === s.split); map.set(key, s.split); }
    if (frozen) {
      visionSha(s.pixel_sha256); visionSha(s.label_sha256); portable(s.label_path); integer(s.width, 1, 2048); integer(s.height, 1, 2048);
      visionEnsure(!pixels.has(s.pixel_sha256) || pixels.get(s.pixel_sha256) === s.split); pixels.set(s.pixel_sha256, s.split);
    }
  }
  visionEnsure(splits.size === 3); return v as unknown as DetectionManifest;
}
export async function parseDetectionManifest(textValue: string): Promise<{ manifest: DetectionManifest; sha256: string }> {
  try { visionEnsure(new TextEncoder().encode(textValue).byteLength <= 2 * 1024 * 1024); const manifest = validateDetectionManifest(JSON.parse(textValue)); return { manifest, sha256: await visionDigest(manifest) }; }
  catch { throw new VisionContractError(); }
}
export async function validateVisionRecord(value: unknown, scope: VisionScope, kind?: VisionKind | 'feedback', expectedId?: string, etag?: string | null, contentSha?: string | null): Promise<VisionRecord> {
  validateVisionScope(scope); const v = await verifyVisionSeal(value, etag, contentSha);
  if (v.schema_version === 'visiondata-gate.vision-feedback.v1') {
    visionEnsure((!kind || kind === 'feedback') && (!expectedId || v.resource_id === expectedId)); return validateVisionFeedback(v, scope);
  }
  visionEnsure(v.project_id === scope.projectId && v.production_release_allowed === false && v.machine_write_permitted === false);
  visionId(v.resource_id); visionId(v.created_by); text(v.reviewer_identity, 2, 160); text(v.created_at); visionEnsure(Number.isFinite(Date.parse(v.created_at)));
  if (expectedId !== undefined) visionEnsure(v.resource_id === expectedId);
  const kinds: Record<string, VisionKind> = { 'visiondata-gate.vision_model.v1': 'model', 'visiondata-gate.vision_runtime.v1': 'runtime', 'visiondata-gate.vision_dataset.v1': 'dataset',
    'visiondata-gate.vision_run.v1': 'run', 'visiondata-gate.vision_inference_asset.v1': 'inference_asset', 'visiondata-gate.vision_inference.v1': 'inference' };
  const actual = kinds[String(v.schema_version)]; visionEnsure(actual && (!kind || kind === actual));
  const idField = actual === 'run' ? 'run_id' : actual === 'inference_asset' ? 'asset_id' : `${actual}_id`;
  visionEnsure(v[idField] === v.resource_id);
  if (actual === 'model') {
    text(v.display_name, 1, 120); visionSha(v.weights_sha256); text(v.license_id, 1, 120); text(v.license_status); visionEnsure(v.loaded === false);
    if (v.task_type === 'normality') {
      visionEnsure(v.model_kind === 'YOLO26_NORMALITY_MODEL_PACK' && v.format === 'pt' && v.model_pack_schema_version === 'visiondata-gate.yolo26-normality-model-pack.v2');
      for (const key of ['model_pack_sha256', 'backbone_weights_sha256', 'source_binding_sha256', 'source_index_sha256']) visionSha(v[key]);
      visionEnsure(v.model_pack_sha256 === v.weights_sha256); text(v.architecture, 1, 120);
      visionEnsure(Array.isArray(v.feature_layers) && v.feature_layers.length > 0 && new Set(v.feature_layers).size === v.feature_layers.length); v.feature_layers.forEach(layer => integer(layer, 0, 1000));
      integer(v.split_seed, 0, 2147483647); visionEnsure(v.model_seed === 20260913 && v.stability_schema_version === 'visiondata-gate.model-stability.v4');
      const verifier = visionObject(v.verification_implementation); fields(verifier, ['stability_module_sha256', 'outcome_policy_module_sha256', 'outcome_policy_function']);
      visionSha(verifier.stability_module_sha256); visionSha(verifier.outcome_policy_module_sha256); visionEnsure(verifier.outcome_policy_function === 'classify_experiment_outcome');
      const runs = visionObject(v.stability_run_artifact_sha256); visionEnsure(Object.keys(runs).length === 3);
      for (const [label, artifacts] of Object.entries(runs)) { metadata(label); const bound = visionObject(artifacts); visionEnsure(Object.keys(bound).length > 0); Object.values(bound).forEach(visionSha); }
      visionEnsure(['PUBLIC_PROXY_STABLE', 'MODEL_PROMOTION_HOLD'].includes(String(v.stability_status)) && typeof v.stability_eligible === 'boolean' && Array.isArray(v.stability_blockers));
      v.stability_blockers.forEach(blocker => metadata(blocker, 500)); const evidence = visionObject(v.evidence_file_sha256); visionEnsure(Object.keys(evidence).length >= 5); Object.values(evidence).forEach(visionSha);
      visionEnsure(['MODEL_PACK_EVIDENCE_VERIFIED', 'RESEARCH_ONLY_HOLD', 'APPROVE_SANDBOX', 'REJECT'].includes(String(v.status))
        && ['SANDBOX_CANDIDATE', 'RESEARCH_ONLY', 'LOCAL_SANDBOX_ONLY'].includes(String(v.usage_scope)) && typeof v.sandbox_eligible === 'boolean'
        && v.storage_scope === 'REGISTRY_OWNED_CONTENT_ADDRESSED');
      if (v.status === 'APPROVE_SANDBOX' || (v.status === 'REJECT' && v.sandbox_runtime_id !== null)) {
        visionId(v.sandbox_runtime_id); visionSha(v.sandbox_runtime_sha256);
        visionEnsure(v.status === 'APPROVE_SANDBOX' ? v.usage_scope === 'LOCAL_SANDBOX_ONLY' && v.sandbox_eligible === true : v.usage_scope === 'RESEARCH_ONLY' && v.sandbox_eligible === false);
        const validation = visionObject(v.sandbox_validation); visionEnsure(validation.status === 'VALIDATED_FOR_LOCAL_SANDBOX' && validation.production_release_allowed === false
          && validation.model_pack_schema_version === v.model_pack_schema_version && validation.model_pack_sha256 === v.model_pack_sha256
          && validation.backbone_weights_sha256 === v.backbone_weights_sha256 && validation.source_binding_sha256 === v.source_binding_sha256
          && validation.source_index_sha256 === v.source_index_sha256 && validation.runtime_sha256 === v.sandbox_runtime_sha256);
        visionSha(validation.inference_backend_sha256);
      } else {
        visionEnsure(v.sandbox_runtime_id === null && v.sandbox_runtime_sha256 === null && v.sandbox_validation === undefined);
      }
    } else {
      visionEnsure(['detect', 'segment'].includes(String(v.task_type)) && ['pt', 'onnx', 'safetensors'].includes(String(v.format)));
      integer(v.file_bytes, 1, Number.MAX_SAFE_INTEGER); text(v.source_description, 4, 500);
      visionEnsure(['REGISTERED_NOT_LOADED', 'CANDIDATE_REQUIRES_HUMAN_REVIEW', 'APPROVE_SANDBOX', 'REJECT'].includes(String(v.status)));
    }
  } else if (actual === 'runtime') {
    text(v.display_name, 1, 120); visionSha(v.executable_sha256); visionSha(v.runtime_sha256); text(v.status);
    const p = visionObject(v.probe); visionEnsure(['ready', 'unavailable'].includes(String(p.status)) && ['NOT_RUN', 'PASSED', 'FAILED'].includes(String(p.import_status)));
    visionEnsure(p.runtime_sha256 === v.runtime_sha256 && p.executable_sha256 === v.executable_sha256);
    const packages = visionObject(p.packages); visionEnsure(Object.values(packages).every(item => item === null || typeof item === 'string'));
    visionEnsure(Array.isArray(p.python_version) && p.python_version.length === 3); p.python_version.forEach(n => integer(n, 0, 100));
  } else if (actual === 'dataset') {
    visionEnsure(v.status === 'FROZEN_REVIEWED_DETECTION_DATASET'); visionSha(v.dataset_receipt_sha256);
    const d = await verifyVisionSeal(v.dataset_receipt, undefined, undefined, ['dataset_id']);
    visionEnsure(d.receipt_sha256 === v.dataset_receipt_sha256 && d.dataset_id === `detds_${String(d.receipt_sha256).slice(0, 24)}`);
    validateDetectionManifest(d, true); visionSha(d.manifest_sha256); visionSha(d.data_yaml_sha256);
    const counts = visionObject(d.split_counts); fields(counts, ['train', 'val', 'test']);
    for (const split of ['train', 'val', 'test']) visionEnsure(counts[split] === (d.samples as DetectionSample[]).filter(s => s.split === split).length);
    if (v.pool_binding !== undefined) {
      const b = await verifyVisionSeal(v.pool_binding); visionEnsure(b.schema_version === 'visiondata-gate.pool-detection-binding.v1' && b.project_id === scope.projectId && b.production_release_allowed === false && b.label_truth_authority === false);
      for (const key of ['pool_id', 'version_id', 'task_id', 'source_id', 'snapshot_id']) visionId(b[key]);
      for (const key of ['pool_receipt_sha256', 'version_receipt_sha256', 'snapshot_receipt_sha256', 'source_profile_sha256', 'batch_manifest_sha256', 'batch_contract_sha256', 'gate_result_sha256', 'readiness_receipt_sha256', 'annotation_bindings_sha256']) visionSha(b[key]);
      visionEnsure(b.version_id === d.source_version && b.detection_manifest_sha256 === d.manifest_sha256 && b.sample_count === (d.samples as DetectionSample[]).length);
      visionEnsure(await visionDigest(b.class_names) === await visionDigest(d.class_names) && b.class_mapping_sha256 === await visionDigest(b.class_names));
      const frame = { schema_version: 'visiondata-gate.operator-detection-frame.v1', input_coordinates: 'normalized_xywh', input_origin: 'top_left', output_coordinates: 'normalized_center_xywh', image_frame: 'frozen_original_width_height', mask_conversion: false };
      visionEnsure(await visionDigest(b.coordinate_frame) === await visionDigest(frame) && b.coordinate_frame_sha256 === await visionDigest(frame));
      const groups = visionObject(b.groups); const samples = d.samples as DetectionSample[];
      visionEnsure(Object.keys(groups).length === samples.length && samples.every(sample => groups[sample.sample_id] === sample.group_id));
      visionEnsure(Array.isArray(b.normal_sample_ids) && await visionDigest([...b.normal_sample_ids].sort()) === await visionDigest(samples.filter(sample => sample.normal_attested).map(sample => sample.sample_id).sort()));
    }
  } else if (actual === 'inference_asset') {
    text(v.display_name, 1, 120); visionSha(v.image_sha256); integer(v.image_bytes, 1, 64 * 1024 * 1024); integer(v.image_width, 1, 8192); integer(v.image_height, 1, 8192);
    visionEnsure(['png', 'jpg', 'jpeg', 'bmp'].includes(String(v.format)) && v.storage_scope === 'REGISTRY_OWNED_CONTENT_ADDRESSED' && v.status === 'FROZEN_LOCAL_INFERENCE_ASSET');
  } else if (actual === 'inference') {
    for (const key of ['model_id', 'asset_id', 'runtime_id']) visionId(v[key]);
    for (const key of ['model_pack_sha256', 'backbone_weights_sha256', 'source_binding_sha256', 'source_index_sha256', 'runtime_sha256', 'inference_backend_sha256', 'image_sha256']) visionSha(v[key]);
    visionEnsure(v.status === 'COMPLETED_LOCAL_SANDBOX_INFERENCE' && v.device === 'cpu' && v.decision_scope === 'MODEL_SIGNAL_ONLY_NOT_GATE_OR_PRODUCTION_DECISION'
      && v.review_required === true && v.gate_decision === 'NOT_ISSUED');
    for (const key of ['image_score', 'image_threshold', 'pixel_threshold', 'positive_pixel_fraction']) visionEnsure(typeof v[key] === 'number' && Number.isFinite(v[key]) && v[key] >= 0);
    const imageScore = v.image_score as number, imageThreshold = v.image_threshold as number, positivePixelFraction = v.positive_pixel_fraction as number;
    visionEnsure(positivePixelFraction <= 1 && typeof v.predicted_anomaly === 'boolean' && v.predicted_anomaly === (imageScore >= imageThreshold));
    visionEnsure(typeof v.heatmap_artifact_id === 'string' && /^normality_heatmap_[0-9a-f]{24}$/.test(v.heatmap_artifact_id));
    const heatmap = visionObject(v.heatmap); fields(heatmap, ['sha256', 'bytes', 'width', 'height', 'format']); visionSha(heatmap.sha256);
    integer(heatmap.bytes, 1, Number.MAX_SAFE_INTEGER); integer(heatmap.width, 1, 8192); integer(heatmap.height, 1, 8192); visionEnsure(heatmap.format === 'png');
  } else {
    visionEnsure(['QUEUED', 'RUNNING', 'SUCCEEDED_CANDIDATE', 'FAILED', 'CANCELLED', 'TIMED_OUT', 'INTERRUPTED_HOLD'].includes(String(v.status)));
    visionId(v.runtime_id); visionSha(v.runtime_sha256); visionId(v.dataset_id); visionSha(v.dataset_receipt_sha256); visionSha(v.authorization_sha256);
    visionEnsure(['ARCHITECTURE_RANDOM', 'REGISTERED_WEIGHTS'].includes(String(v.initialization)));
    if (v.initial_model_id !== null) visionId(v.initial_model_id);
    visionEnsure((v.initialization === 'ARCHITECTURE_RANDOM') === (v.initial_model_id === null));
    visionEnsure(v.pretrained_claimed === false && v.architecture === 'yolo26n' && v.device === 'cpu' && v.adaptation === 'OFF' && v.ttt_status === 'DISABLED_NOT_IMPLEMENTED');
    validateVisionBudget(v.training); visionEnsure(typeof v.cancel_requested === 'boolean' && ['PENDING', 'APPROVE_SANDBOX', 'REJECT'].includes(String(v.selection)));
    for (const field of ['responds_to_feedback_ids', 'feedback_ids']) if (v[field] !== undefined) {
      visionEnsure(Array.isArray(v[field]) && v[field].length <= 64 && new Set(v[field]).size === v[field].length);
      (v[field] as unknown[]).forEach(id => visionEnsure(typeof id === 'string' && /^vfeedback_[0-9a-f]{24}$/.test(id)));
    }
    if (v.feedback_status !== undefined) visionEnsure(['NOT_EVALUATED', 'NOT_AVAILABLE_LEGACY_RESULT', 'VAL_DISAGREEMENTS_REQUIRE_HUMAN_REVIEW', 'NO_VAL_DISAGREEMENT_AT_FIXED_PROTOCOL'].includes(String(v.feedback_status)));
    if (v.candidate_model_id !== null) visionId(v.candidate_model_id);
    visionEnsure(v.error_code === null || typeof v.error_code === 'string');
    if (v.result !== null) {
      const r = visionObject(v.result); visionEnsure(r.device === 'cpu' && r.production_approved === false && r.test_evaluation === 'NOT_RUN');
      if (v.status === 'SUCCEEDED_CANDIDATE') {
        visionEnsure(r.status === 'completed' && v.candidate_model_id !== null);
        for (const key of ['baseline', 'candidate']) { const metrics = visionObject(r[key]); visionEnsure(Object.keys(metrics).length > 0 && Object.values(metrics).every(n => typeof n === 'number' && Number.isFinite(n))); }
        visionEnsure(r.actual_epochs === (v.training as VisionBudget).epochs); integer(r.training_samples, 1, 64); integer(r.validation_samples, 1, 64);
        const ck = visionObject(r.checkpoint); portable(ck.relative_path); visionSha(ck.sha256); integer(ck.bytes, 1, Number.MAX_SAFE_INTEGER); visionEnsure(ck.round_trip === 'VERIFIED' && ck.selection === 'last_epoch');
      }
    } else visionEnsure(v.status !== 'SUCCEEDED_CANDIDATE');
  }
  return v as unknown as VisionRecord;
}
export async function validateVisionList(value: unknown, scope: VisionScope, kind: VisionKind, etag: string | null, contentSha: string | null): Promise<VisionRecord[]> {
  const v = await verifyVisionSeal(value, etag, contentSha); visionEnsure(v.schema_version === 'visiondata-gate.vision-list.v1' && v.project_id === scope.projectId && Array.isArray(v.items));
  const items = await Promise.all(v.items.map(item => validateVisionRecord(item, scope, kind)));
  visionEnsure(new Set(items.map(item => item.resource_id)).size === items.length); return items;
}
export async function validateVisionCapabilities(value: unknown, scope: VisionScope, etag: string | null, contentSha: string | null): Promise<VisionCapabilities> {
  validateVisionScope(scope); const v = await verifyVisionSeal(value, etag, contentSha);
  visionEnsure(v.schema_version === 'visiondata-gate.vision-capabilities.v1' && v.project_id === scope.projectId && v.model_domain === 'LOCAL_VISUAL_MODELS' && v.llm_provider_managed === false);
  visionEnsure(v.training_device === 'CPU_ONLY' && Array.isArray(v.supported_registration_tasks) && JSON.stringify(v.supported_registration_tasks) === JSON.stringify(['detect', 'segment', 'normality'])
    && Array.isArray(v.executable_training_tasks) && v.executable_training_tasks.length === 1 && v.executable_training_tasks[0] === 'detect'
    && Array.isArray(v.executable_inference_tasks) && v.executable_inference_tasks.length === 1 && v.executable_inference_tasks[0] === 'normality' && v.normality_runtime === 'EXTERNAL_RUNTIME_REQUIRED');
  visionEnsure(v.ttt_status === 'DISABLED_NOT_IMPLEMENTED' && v.weight_download_allowed === false && v.production_release_allowed === false && v.training_authorization_required === true && v.industrial_effectiveness_status === 'NOT_EVALUATED' && typeof v.training_ready === 'boolean');
  for (const key of ['registered_model_count', 'registered_runtime_count', 'registered_dataset_count', 'sandbox_approved_normality_model_count', 'registered_inference_asset_count', 'completed_normality_inference_count']) integer(v[key], 0, Number.MAX_SAFE_INTEGER);
  return v as unknown as VisionCapabilities;
}
export async function validateVisionOperationReceipt(value: unknown, scope: VisionScope, pending: VisionPending, etag: string | null, contentSha: string | null): Promise<VisionOperationReceipt> {
  const v = await verifyVisionSeal(value, etag, contentSha); validateVisionOperation(pending.operation);
  visionEnsure(v.schema_version === 'visiondata-gate.vision-operation.v1' && v.project_id === scope.projectId && v.operation === pending.operation && v.request_key === pending.requestKey && v.auto_replayed === false);
  visionId(v.resource_id); const resource = await validateVisionRecord(v.resource, scope, undefined, v.resource_id);
  const expectedKinds: Record<string, string> = { register_model: 'model', register_normality_model_pack: 'model', approve_normality_model_pack: 'model',
    register_runtime: 'runtime', register_dataset: 'dataset', register_pool_dataset: 'dataset', register_inference_asset: 'inference_asset',
    run_normality_inference: 'inference', create_training_run: 'run', probe_runtime: 'runtime', cancel: 'run', recover: 'run', selection: 'run' };
  visionEnsure(resource.schema_version === (pending.operation.startsWith('triage_feedback:') ? 'visiondata-gate.vision-feedback.v1' : `visiondata-gate.vision_${expectedKinds[pending.operation.split(':')[0] ?? '']}.v1`));
  if (/^(probe_runtime|cancel|recover|selection|approve_normality_model_pack|triage_feedback):/.test(pending.operation)) visionEnsure(resource.resource_id === pending.operation.split(':')[1]);
  if (pending.operation.startsWith('run_normality_inference:')) visionEnsure('inference_id' in resource && resource.model_id === pending.operation.split(':')[1]);
  return v as unknown as VisionOperationReceipt;
}
export async function validateVisionRequest(operation: VisionMutationOperation, value: unknown): Promise<Record<string, unknown>> {
  validateVisionOperation(operation); const v = visionObject(value); const common = ['request_key', 'reviewer_identity', 'note'];
  visionEnsure(typeof v.request_key === 'string' && /^[A-Za-z0-9_-]{12,100}$/.test(v.request_key)); text(v.reviewer_identity, 2, 160); text(v.note, 8, 1000);
  const name = operation.split(':')[0];
  if (name === 'register_model') {
    fields(v, [...common, 'display_name', 'weights_path', 'expected_weights_sha256', 'task_type', 'license_id', 'source_description', 'operator_attests_read_authorized']);
    text(v.display_name, 1, 120); privatePath(v.weights_path); visionSha(v.expected_weights_sha256); text(v.license_id, 1, 120); text(v.source_description, 4, 500);
    visionEnsure(['detect', 'segment'].includes(String(v.task_type)) && v.operator_attests_read_authorized === true);
  } else if (name === 'register_normality_model_pack') {
    fields(v, [...common, 'display_name', 'model_pack_path', 'expected_model_pack_sha256', 'run_directory', 'stability_run_directories', 'target_model_seed',
      'stability_summary_path', 'expected_stability_summary_sha256', 'source_binding_path', 'expected_source_binding_file_sha256', 'expected_source_binding_sha256',
      'source_index_path', 'expected_source_index_file_sha256', 'expected_source_index_sha256', 'backbone_weights_path', 'expected_backbone_weights_sha256',
      'operator_attests_read_authorized', 'operator_attests_weights_only_load_authorized', 'ultralytics_license_acknowledged']);
    text(v.display_name, 1, 120); for (const key of ['model_pack_path', 'run_directory', 'stability_summary_path', 'source_binding_path', 'source_index_path', 'backbone_weights_path']) privatePath(v[key]);
    for (const key of ['expected_model_pack_sha256', 'expected_stability_summary_sha256', 'expected_source_binding_file_sha256', 'expected_source_binding_sha256',
      'expected_source_index_file_sha256', 'expected_source_index_sha256', 'expected_backbone_weights_sha256']) visionSha(v[key]);
    visionEnsure(Array.isArray(v.stability_run_directories) && v.stability_run_directories.length === 3 && new Set(v.stability_run_directories).size === 3);
    v.stability_run_directories.forEach(privatePath); visionEnsure(v.stability_run_directories.includes(v.run_directory) && v.target_model_seed === 20260913
      && v.operator_attests_read_authorized === true && v.operator_attests_weights_only_load_authorized === true && v.ultralytics_license_acknowledged === true);
  } else if (name === 'approve_normality_model_pack') {
    fields(v, [...common, 'action', 'expected_model_receipt_sha256', 'expected_model_pack_sha256', 'expected_backbone_weights_sha256', 'expected_source_binding_sha256',
      'expected_source_index_sha256', 'runtime_id', 'expected_runtime_sha256', 'operator_attests_reviewed', 'operator_attests_trusted_runtime',
      'operator_attests_execution_authorized', 'operator_attests_trusted_weights', 'operator_attests_weights_only_load_authorized', 'ultralytics_license_acknowledged']);
    visionEnsure(['APPROVE_SANDBOX', 'REJECT'].includes(String(v.action))); for (const key of ['expected_model_receipt_sha256', 'expected_model_pack_sha256', 'expected_backbone_weights_sha256', 'expected_source_binding_sha256', 'expected_source_index_sha256', 'expected_runtime_sha256']) visionSha(v[key]);
    visionId(v.runtime_id); visionEnsure(v.operator_attests_reviewed === true && v.operator_attests_trusted_runtime === true && v.operator_attests_execution_authorized === true
      && v.operator_attests_trusted_weights === true && v.operator_attests_weights_only_load_authorized === true && v.ultralytics_license_acknowledged === true);
  } else if (name === 'register_inference_asset') {
    fields(v, [...common, 'display_name', 'image_path', 'expected_image_sha256', 'operator_attests_read_authorized']); text(v.display_name, 1, 120); privatePath(v.image_path);
    visionSha(v.expected_image_sha256); visionEnsure(v.operator_attests_read_authorized === true);
  } else if (name === 'run_normality_inference') {
    fields(v, [...common, 'expected_model_receipt_sha256', 'expected_model_pack_sha256', 'expected_backbone_weights_sha256', 'expected_source_binding_sha256',
      'expected_source_index_sha256', 'expected_runtime_sha256', 'asset_id', 'expected_asset_receipt_sha256', 'expected_image_sha256', 'max_seconds',
      'operator_attests_execution_authorized', 'operator_attests_trusted_runtime', 'operator_attests_trusted_weights', 'operator_attests_weights_only_load_authorized']);
    for (const key of ['expected_model_receipt_sha256', 'expected_model_pack_sha256', 'expected_backbone_weights_sha256', 'expected_source_binding_sha256',
      'expected_source_index_sha256', 'expected_runtime_sha256', 'expected_asset_receipt_sha256', 'expected_image_sha256']) visionSha(v[key]);
    visionId(v.asset_id); integer(v.max_seconds, 5, 300); visionEnsure(v.operator_attests_execution_authorized === true && v.operator_attests_trusted_runtime === true
      && v.operator_attests_trusted_weights === true && v.operator_attests_weights_only_load_authorized === true);
  } else if (name === 'register_runtime') {
    fields(v, [...common, 'display_name', 'executable_path', 'expected_executable_sha256', 'operator_attests_trusted_runtime', 'operator_attests_execution_authorized']);
    text(v.display_name, 1, 120); privatePath(v.executable_path); visionSha(v.expected_executable_sha256); visionEnsure(v.operator_attests_trusted_runtime === true && v.operator_attests_execution_authorized === true);
  } else if (name === 'probe_runtime') {
    fields(v, [...common, 'expected_runtime_sha256', 'operator_attests_trusted_runtime', 'operator_attests_execution_authorized', 'import_check']);
    visionSha(v.expected_runtime_sha256); visionEnsure(v.operator_attests_trusted_runtime === true && v.operator_attests_execution_authorized === true && typeof v.import_check === 'boolean');
  } else if (name === 'register_dataset') {
    fields(v, [...common, 'source_root', 'manifest', 'expected_manifest_sha256', 'operator_attests_data_authorized']); privatePath(v.source_root);
    validateDetectionManifest(v.manifest); visionSha(v.expected_manifest_sha256); visionEnsure(v.operator_attests_data_authorized === true && await visionDigest(v.manifest) === v.expected_manifest_sha256);
  } else if (name === 'register_pool_dataset') {
    fields(v, [...common, 'pool_id', 'version_id', 'expected_pool_receipt_sha256', 'expected_version_receipt_sha256', 'class_names', 'groups', 'normal_sample_ids', 'operator_attests_data_authorized']);
    visionId(v.pool_id); visionId(v.version_id); visionSha(v.expected_pool_receipt_sha256); visionSha(v.expected_version_receipt_sha256);
    visionEnsure(Array.isArray(v.class_names) && v.class_names.length >= 1 && v.class_names.length <= 64 && new Set(v.class_names).size === v.class_names.length);
    v.class_names.forEach(name => metadata(name, 96));
    const groups = visionObject(v.groups); visionEnsure(Object.keys(groups).length >= 3 && Object.keys(groups).length <= 64);
    for (const [sampleId, group] of Object.entries(groups)) { visionId(sampleId); metadata(group); }
    visionEnsure(Array.isArray(v.normal_sample_ids) && v.normal_sample_ids.length <= 64 && new Set(v.normal_sample_ids).size === v.normal_sample_ids.length);
    v.normal_sample_ids.forEach(sampleId => { visionId(sampleId); visionEnsure(Object.hasOwn(groups, sampleId)); });
    visionEnsure(v.operator_attests_data_authorized === true);
  } else if (name === 'create_training_run') {
    fields(v, [...common, 'runtime_id', 'expected_runtime_sha256', 'dataset_id', 'expected_dataset_receipt_sha256', 'initialization', 'initial_model_id', 'expected_weights_sha256', 'architecture', 'training', 'operator_attests_training_authorized', 'operator_attests_trusted_runtime', 'operator_attests_trusted_weights', 'operator_attests_pickle_load_risk', 'ultralytics_license_acknowledged', 'adaptation', 'responds_to_feedback_ids', 'expected_feedback_receipts']);
    visionId(v.runtime_id); visionId(v.dataset_id); visionSha(v.expected_runtime_sha256); visionSha(v.expected_dataset_receipt_sha256); validateVisionBudget(v.training);
    visionEnsure(v.architecture === 'yolo26n' && v.adaptation === 'OFF' && v.operator_attests_training_authorized === true && v.operator_attests_trusted_runtime === true && v.ultralytics_license_acknowledged === true);
    visionEnsure(typeof v.operator_attests_trusted_weights === 'boolean' && typeof v.operator_attests_pickle_load_risk === 'boolean');
    visionEnsure(Array.isArray(v.responds_to_feedback_ids) && v.responds_to_feedback_ids.length <= 64 && new Set(v.responds_to_feedback_ids).size === v.responds_to_feedback_ids.length);
    const feedback = visionObject(v.expected_feedback_receipts); visionEnsure(Object.keys(feedback).length === v.responds_to_feedback_ids.length);
    for (const identifier of v.responds_to_feedback_ids) { visionEnsure(typeof identifier === 'string' && /^vfeedback_[0-9a-f]{24}$/.test(identifier)); visionSha(feedback[identifier]); }
    if (v.initialization === 'REGISTERED_WEIGHTS') { visionId(v.initial_model_id); visionSha(v.expected_weights_sha256); visionEnsure(v.operator_attests_trusted_weights === true && v.operator_attests_pickle_load_risk === true); }
    else visionEnsure(v.initialization === 'ARCHITECTURE_RANDOM' && v.initial_model_id === null && v.expected_weights_sha256 === null);
  } else {
    fields(v, [...common, 'expected_run_sha256', 'operator_attests_reviewed', ...(name === 'selection' ? ['action', 'expected_candidate_weights_sha256'] : name === 'triage_feedback' ? ['expected_feedback_sha256', 'classification'] : [])]);
    visionSha(v.expected_run_sha256); visionEnsure(v.operator_attests_reviewed === true);
    if (name === 'selection') { visionEnsure(['APPROVE_SANDBOX', 'REJECT'].includes(String(v.action))); visionSha(v.expected_candidate_weights_sha256); }
    if (name === 'triage_feedback') { visionSha(v.expected_feedback_sha256); visionEnsure(['MODEL_ERROR', 'LABEL_REVIEW_REQUIRED', 'HARD_SAMPLE', 'UNKNOWN'].includes(String(v.classification))); }
  }
  await visionDigest(v); return v;
}

function validateFeedbackDetail(value: unknown): FeedbackDetail {
  const d = visionObject(value); visionId(d.sample_id); visionSha(d.image_sha256); visionSha(d.label_sha256);
  const predictions = d.prediction_boxes, truth = d.ground_truth_boxes;
  visionEnsure(Array.isArray(predictions) && predictions.length <= 300 && Array.isArray(truth) && truth.length <= 256);
  for (const [rows, prediction] of [[predictions, true], [truth, false]] as const) for (const raw of rows) {
    const b = visionObject(raw); integer(b.class_id, 0, 63); visionEnsure(Array.isArray(b.xyxy) && b.xyxy.length === 4 && b.xyxy.every(n => typeof n === 'number' && Number.isFinite(n) && n >= 0 && n <= 1));
    const coords = b.xyxy as number[]; visionEnsure(coords[0]! < coords[2]! && coords[1]! < coords[3]!);
    if (prediction) visionEnsure(typeof b.confidence === 'number' && Number.isFinite(b.confidence) && b.confidence >= .25 && b.confidence <= 1);
  }
  integer(d.tp, 0, 256); integer(d.fp, 0, 300); integer(d.fn, 0, 256);
  visionEnsure(d.tp + d.fp === predictions.length && d.tp + d.fn === truth.length && d.review_required === true);
  visionEnsure(Array.isArray(d.matched_ious) && d.matched_ious.length === d.tp && d.matched_ious.every(n => typeof n === 'number' && n >= .5 && n <= 1));
  visionEnsure(Array.isArray(d.matches) && d.matches.length === d.tp);
  const pi = new Set<number>(), gi = new Set<number>();
  for (const [index, raw] of d.matches.entries()) {
    const m = visionObject(raw); integer(m.prediction_index, 0, predictions.length - 1); integer(m.ground_truth_index, 0, truth.length - 1);
    visionEnsure(!pi.has(m.prediction_index) && !gi.has(m.ground_truth_index) && m.iou === d.matched_ious[index]); pi.add(m.prediction_index); gi.add(m.ground_truth_index);
    const p = predictions[m.prediction_index] as FeedbackBox, t = truth[m.ground_truth_index] as FeedbackBox; visionEnsure(p.class_id === t.class_id);
  }
  const reasons = [...(d.fp ? ['FALSE_POSITIVE_CANDIDATE'] : []), ...(d.fn ? ['FALSE_NEGATIVE_CANDIDATE'] : [])];
  visionEnsure(JSON.stringify(d.reason_codes) === JSON.stringify(reasons)); return d as unknown as FeedbackDetail;
}
export function validateVisionFeedback(value: unknown, scope: VisionScope): VisionFeedback {
  const v = visionObject(value); visionEnsure(v.schema_version === 'visiondata-gate.vision-feedback.v1' && v.project_id === scope.projectId && v.split === 'val');
  visionEnsure(typeof v.feedback_id === 'string' && /^vfeedback_[0-9a-f]{24}$/.test(v.feedback_id) && v.resource_id === v.feedback_id);
  for (const key of ['run_id', 'dataset_id', 'sample_id']) visionId(v[key]);
  for (const key of ['dataset_receipt_sha256', 'image_sha256', 'label_sha256', 'checkpoint_sha256', 'protocol_sha256']) visionSha(v[key]);
  visionEnsure(v.issue_closed === false && v.label_truth_authority === false && v.training_ingestion_allowed === false && v.production_release_allowed === false);
  visionEnsure(v.status === 'PENDING_HUMAN_REVIEW' ? v.classification === null : v.status === 'TRIAGED_FOR_REVIEW' && ['MODEL_ERROR', 'LABEL_REVIEW_REQUIRED', 'HARD_SAMPLE', 'UNKNOWN'].includes(String(v.classification)));
  const d = validateFeedbackDetail(v.detail); visionEnsure(d.sample_id === v.sample_id && d.image_sha256 === v.image_sha256 && d.label_sha256 === v.label_sha256 && d.fp + d.fn > 0);
  return v as unknown as VisionFeedback;
}
export async function validateVisionFeedbackList(value: unknown, scope: VisionScope, run: VisionRun, etag: string | null, contentSha: string | null): Promise<VisionFeedback[]> {
  const v = await verifyVisionSeal(value, etag, contentSha); visionEnsure(v.schema_version === 'visiondata-gate.vision-list.v1' && v.project_id === scope.projectId && v.run_id === run.run_id && Array.isArray(v.items));
  const items = await Promise.all(v.items.map(item => validateVisionRecord(item, scope, 'feedback') as Promise<VisionFeedback>));
  visionEnsure(new Set(items.map(item => item.feedback_id)).size === items.length && JSON.stringify(items.map(item => item.feedback_id).sort()) === JSON.stringify([...(run.feedback_ids ?? [])].sort()));
  if (items.length) {
    const protocol = visionObject(run.result?.validation_feedback_protocol);
    visionEnsure(protocol.schema_version === 'visiondata-gate.validation-feedback.v1' && protocol.split === 'val' && protocol.confidence_threshold === .25 && protocol.iou_threshold === .5 && protocol.max_detections === 300
      && protocol.matching === 'class_aware_greedy_iou_descending' && protocol.checkpoint_sha256 === run.result?.checkpoint?.sha256 && protocol.runtime_sha256 === run.runtime_sha256);
    const protocolSha = await visionDigest(protocol); const details = run.result?.validation_samples_detail; visionEnsure(Array.isArray(details));
    for (const item of items) {
      visionEnsure(item.run_id === run.run_id && item.dataset_id === run.dataset_id && item.dataset_receipt_sha256 === run.dataset_receipt_sha256 && item.checkpoint_sha256 === run.result?.checkpoint?.sha256 && item.protocol_sha256 === protocolSha);
      visionEnsure(await visionDigest(item.detail) === await visionDigest(details.find(detail => detail.sample_id === item.sample_id)));
    }
  }
  return items;
}

export function visionStatusLabel(status: VisionRunStatus): string {
  return { QUEUED: '已授权 · 等待执行', RUNNING: 'CPU 训练中', SUCCEEDED_CANDIDATE: '候选已生成 · 效果未达标判定', FAILED: '执行失败', CANCELLED: '已取消', TIMED_OUT: '预算超时', INTERRUPTED_HOLD: '执行中断 · HOLD' }[status];
}
