import { canonicalizeJcs, sha256HexUtf8 } from './data/jcs.ts';

/** Local visual-model contracts, deliberately separate from LLM providers. */
export interface VisionScope { workspaceId: string; projectId: string; actorId: string }
export type VisionKind = 'model' | 'runtime' | 'dataset' | 'run' | 'inference_asset' | 'inference' | 'ttt_failure';
export type VisionOperation = 'register_model' | 'register_normality_model_pack' | 'register_runtime' | 'register_dataset' | 'register_pool_dataset'
  | 'register_inference_asset' | 'create_training_run' | `probe_runtime:${string}` | `cancel:${string}` | `recover:${string}` | `selection:${string}`
  | `approve_normality_model_pack:${string}` | `run_normality_inference:${string}`;
export type VisionMutationOperation = VisionOperation | `triage_feedback:${string}` | `review_normality_inference:${string}` | `run_normality_ttt:${string}`
  | `import_normality_followup:${string}` | `create_normality_followup_work_order:${string}`;
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
    runtime_sha256: string; executable_sha256: string; packages: Record<string, string | null>; python_version: number[] }
    | { status: 'failed'; error_code: string; error_type: string; import_status?: never; runtime_sha256?: never; executable_sha256?: never; packages?: never; python_version?: never };
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
  ttt_backend_sha256?: string; ttt?: VisionTttReport;
}
export interface VisionTttBudget { steps: number; learning_rate: number; max_seconds: number; seed: number }
export interface VisionTttMatrix { tp: number; tn: number; fp: number; fn: number }
export interface VisionTttGuardPolicy { min_true_positive: 1; min_true_negative: 1; max_fp_increase: 0; max_fn_increase: 0 }
export interface VisionTttReport {
  schema_version: 'visiondata-gate.normality-ttt.v1'; strategy: 'EPISODIC_MASKED_STUDENT'; status: 'ACCEPTED_EPISODIC' | 'ROLLED_BACK';
  rollback_reason: string | null; steps_completed: number; objective_before: number | null; objective_after: number | null; budget: VisionTttBudget; implementation_sha256: string;
  parameter_sha256_before: string; parameter_sha256_after: string; attempted_parameter_sha256: string; effective_parameter_sha256: string;
  backbone_sha256_before: string; backbone_sha256_after: string; guard_before: VisionTttMatrix; guard_after: VisionTttMatrix | null; effective_guard: VisionTttMatrix;
  loss_curve: { step: number; loss: number; reconstruction_loss: number; replay_loss: number; anchor_loss: number; gradient_norm: number }[];
  input_groups: Record<'adaptation' | 'replay' | 'guard', { count: number; sha256: string[] }>;
  reset_after_episode: true; persistent_learning: false; parent_pack_unchanged: true; thresholds_unchanged: true; industrial_benefit_validated: false;
  guard_policy: VisionTttGuardPolicy;
}
export interface VisionTttCapabilities {
  schema_version: 'visiondata-gate.normality-ttt-capabilities.v1'; project_id: string; strategy: 'EPISODIC_MASKED_STUDENT'; implementation_sha256: string;
  max_steps: 8; max_learning_rate: .01; min_learning_rate: .00001; max_seconds: 120; max_adaptation_assets: 7; max_replay_assets: 8; max_guard_assets: 16;
  production_release_allowed: false; machine_write_permitted: false; persistent_learning: false; industrial_benefit_validated: false; guard_policy: VisionTttGuardPolicy; receipt_sha256: string;
}
export interface VisionTttFailure extends VisionBase {
  schema_version: 'visiondata-gate.vision_ttt_failure.v1'; failure_id: string; model_id: string; asset_id: string;
  model_pack_sha256: string; image_sha256: string; authorization_sha256: string; ttt_backend_sha256: string;
  status: 'FAILED_CLOSED'; failure_code: string; measurements_available: false; retry_policy: 'NEW_EXPLICIT_AUTHORIZATION_REQUIRED';
}
export type NormalityFeedbackClassification = 'MODEL_SIGNAL_CONFIRMED' | 'LIKELY_FALSE_POSITIVE' | 'NEEDS_LABEL_REVIEW' | 'INSUFFICIENT_EVIDENCE';
export interface NormalityFeedback extends VisionBase {
  schema_version: 'visiondata-gate.normality-feedback.v1'; feedback_id: string; inference_id: string; model_id: string; asset_id: string;
  inference_sha256: string; image_sha256: string; model_pack_sha256: string; heatmap_sha256: string; heatmap_artifact_id: string;
  note: string; classification: NormalityFeedbackClassification; status: 'RECORDED_FOR_HUMAN_FOLLOWUP';
  followup_work_item_type: 'MODEL_SIGNAL_REVIEW' | 'FALSE_POSITIVE_INVESTIGATION' | 'LABEL_REVIEW' | 'EVIDENCE_COLLECTION';
  followup_work_item_created: false; issue_closed: false; label_truth_authority: false; training_ingestion_allowed: false;
}
export interface NormalityFollowupBase extends VisionBase {
  workspace_id: string; note: string; feedback_id: string; feedback_sha256: string; inference_id: string; inference_sha256: string;
  vision_asset_id: string; vision_asset_sha256: string; image_sha256: string; operator_asset_id: string; operator_source_sha256: string;
  image_width: number; image_height: number; coordinate_frame: 'DECODED_PIXELS_EXIF_IDENTITY'; annotation_created: false;
  issue_closed: false; label_truth_authority: false; training_ingestion_allowed: false;
}
export interface NormalityFollowupImport extends NormalityFollowupBase {
  schema_version: 'visiondata-gate.normality-followup-import.v1'; import_id: string; status: 'ASSET_IMPORTED_AWAITING_HUMAN_ANNOTATION'; work_order_created: false;
}
export interface NormalityFollowupWorkOrder extends NormalityFollowupBase {
  schema_version: 'visiondata-gate.normality-followup-work-order.v1'; binding_id: string; import_id: string; import_sha256: string;
  annotation_id: string; annotation_revision: number; annotation_document_sha256: string; work_order_id: string; work_order_document_sha256: string; crop_sha256: string;
  assignee: string; status: 'OPEN'; work_order_created: true;
}
export interface NormalityFollowupList { imports: NormalityFollowupImport[]; work_orders: NormalityFollowupWorkOrder[] }
export interface NormalityFollowupAnnotations {
  import_id: string; operator_asset_id: string; asset_sha256: string; revision: number; document_sha256: string;
  annotations: { annotation_id: string; label: string; x: number; y: number; width: number; height: number; source: 'MANUAL' | 'IMPORTED' }[];
}
export type NormalityFollowupKind = 'normality_followup_import' | 'normality_followup_work_order';
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
export type VisionRecord = VisionModel | VisionRuntime | VisionDataset | VisionRun | VisionInferenceAsset | VisionInference | VisionFeedback | NormalityFeedback | VisionTttFailure | NormalityFollowupImport | NormalityFollowupWorkOrder;
export interface VisionCapabilities {
  schema_version: string; project_id: string; receipt_sha256: string; model_domain: 'LOCAL_VISUAL_MODELS';
  llm_provider_managed: false; training_device: 'CPU_ONLY'; executable_training_tasks: ['detect']; executable_inference_tasks: ['normality'];
  supported_registration_tasks: ('detect' | 'segment' | 'normality')[]; normality_runtime: 'EXTERNAL_RUNTIME_REQUIRED';
  ttt_status: 'DISABLED_NOT_IMPLEMENTED' | 'NORMALITY_EPISODIC_AVAILABLE'; ttt_scope?: 'NORMALITY_ONLY_EPISODIC_NO_PERSISTENCE'; weight_download_allowed: false; training_ready: boolean;
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
    || /^(probe_runtime|cancel|recover|selection|approve_normality_model_pack|run_normality_inference|review_normality_inference|run_normality_ttt|import_normality_followup|create_normality_followup_work_order):[A-Za-z0-9_-]{1,120}$/.test(operation)
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
export async function validateVisionRecord(value: unknown, scope: VisionScope, kind?: VisionKind | 'feedback' | 'normality_feedback' | NormalityFollowupKind, expectedId?: string, etag?: string | null, contentSha?: string | null): Promise<VisionRecord> {
  validateVisionScope(scope); const v = await verifyVisionSeal(value, etag, contentSha);
  if (v.schema_version === 'visiondata-gate.vision-feedback.v1') {
    visionEnsure((!kind || kind === 'feedback') && (!expectedId || v.resource_id === expectedId)); return validateVisionFeedback(v, scope);
  }
  if (v.schema_version === 'visiondata-gate.normality-feedback.v1') {
    visionEnsure((!kind || kind === 'normality_feedback') && (!expectedId || v.resource_id === expectedId)); return validateNormalityFeedback(v, scope);
  }
  if (v.schema_version === 'visiondata-gate.normality-followup-import.v1' || v.schema_version === 'visiondata-gate.normality-followup-work-order.v1') {
    visionEnsure((!kind || kind === (v.schema_version.endsWith('import.v1') ? 'normality_followup_import' : 'normality_followup_work_order')) && (!expectedId || v.resource_id === expectedId));
    return validateNormalityFollowupRecord(v, scope);
  }
  if (v.schema_version === 'visiondata-gate.vision_ttt_failure.v1') {
    visionEnsure((!kind || kind === 'ttt_failure') && (!expectedId || v.resource_id === expectedId));
    fields(v, ['schema_version', 'resource_id', 'failure_id', 'project_id', 'model_id', 'asset_id', 'model_pack_sha256', 'image_sha256', 'authorization_sha256', 'ttt_backend_sha256', 'status', 'failure_code', 'measurements_available', 'retry_policy', 'created_by', 'reviewer_identity', 'created_at', 'production_release_allowed', 'machine_write_permitted', 'receipt_sha256']);
    visionEnsure(v.project_id === scope.projectId && v.resource_id === v.failure_id && v.status === 'FAILED_CLOSED' && v.measurements_available === false
      && v.retry_policy === 'NEW_EXPLICIT_AUTHORIZATION_REQUIRED' && v.production_release_allowed === false && v.machine_write_permitted === false);
    for (const key of ['failure_id', 'model_id', 'asset_id', 'created_by']) visionId(v[key]);
    for (const key of ['model_pack_sha256', 'image_sha256', 'authorization_sha256', 'ttt_backend_sha256']) visionSha(v[key]);
    text(v.reviewer_identity, 2, 160); text(v.created_at); visionEnsure(Number.isFinite(Date.parse(v.created_at)));
    visionEnsure(['TTT_WORKER_TIMEOUT', 'TTT_WORKER_FAILED', 'TTT_EXECUTION_FAILED', 'TTT_AUTHORITY_OR_INPUT_CHANGED', 'TTT_RESULT_CONTRACT_INVALID'].includes(String(v.failure_code))); return v as unknown as VisionTttFailure;
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
    const p = visionObject(v.probe);
    if (p.status === 'failed') {
      fields(p, ['status', 'error_code', 'error_type']); visionEnsure(v.status === 'UNAVAILABLE');
      visionEnsure(typeof p.error_code === 'string' && /^(YOLO|RUNTIME)_[A-Z0-9_]{1,100}$/.test(p.error_code)
        && ['ModuleNotFoundError', 'ImportError', 'RuntimeError', 'ValueError', 'TypeError', 'OSError', 'PermissionError', 'FileNotFoundError', 'TimeoutError', 'AttributeError', 'AssertionError', 'MemoryError'].includes(String(p.error_type)));
    } else {
      visionEnsure(['ready', 'unavailable'].includes(String(p.status)) && ['NOT_RUN', 'PASSED', 'FAILED'].includes(String(p.import_status)));
      visionEnsure(p.runtime_sha256 === v.runtime_sha256 && p.executable_sha256 === v.executable_sha256);
      const packages = visionObject(p.packages); visionEnsure(Object.values(packages).every(item => item === null || typeof item === 'string'));
      visionEnsure(Array.isArray(p.python_version) && p.python_version.length === 3); p.python_version.forEach(n => integer(n, 0, 100));
    }
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
  if (actual === 'inference' && (v.ttt !== undefined || v.ttt_backend_sha256 !== undefined)) {
    visionSha(v.ttt_backend_sha256); validateTttReport(v.ttt, v.ttt_backend_sha256, String(v.image_sha256));
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
  visionEnsure((v.ttt_status === 'DISABLED_NOT_IMPLEMENTED' || (v.ttt_status === 'NORMALITY_EPISODIC_AVAILABLE' && v.ttt_scope === 'NORMALITY_ONLY_EPISODIC_NO_PERSISTENCE')) && v.weight_download_allowed === false && v.production_release_allowed === false && v.training_authorization_required === true && v.industrial_effectiveness_status === 'NOT_EVALUATED' && typeof v.training_ready === 'boolean');
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
  visionEnsure(isNormalityFollowupOperation(pending.operation) ? resource.schema_version === (pending.operation.startsWith('import_normality_followup:') ? 'visiondata-gate.normality-followup-import.v1' : 'visiondata-gate.normality-followup-work-order.v1')
    : pending.operation.startsWith('run_normality_ttt:') ? ['visiondata-gate.vision_inference.v1', 'visiondata-gate.vision_ttt_failure.v1'].includes(resource.schema_version)
    : resource.schema_version === (pending.operation.startsWith('review_normality_inference:') ? 'visiondata-gate.normality-feedback.v1' : pending.operation.startsWith('triage_feedback:') ? 'visiondata-gate.vision-feedback.v1' : `visiondata-gate.vision_${expectedKinds[pending.operation.split(':')[0] ?? '']}.v1`));
  if (/^(probe_runtime|cancel|recover|selection|approve_normality_model_pack|triage_feedback):/.test(pending.operation)) visionEnsure(resource.resource_id === pending.operation.split(':')[1]);
  if (pending.operation.startsWith('run_normality_inference:')) visionEnsure('inference_id' in resource && 'model_id' in resource && resource.model_id === pending.operation.split(':')[1]);
  if (pending.operation.startsWith('review_normality_inference:')) visionEnsure('inference_id' in resource && resource.inference_id === pending.operation.split(':')[1]);
  if (pending.operation.startsWith('run_normality_ttt:')) visionEnsure('model_id' in resource && resource.model_id === pending.operation.split(':')[1] && (resource.schema_version === 'visiondata-gate.vision_ttt_failure.v1' || ('ttt' in resource && resource.ttt)));
  if (isNormalityFollowupOperation(pending.operation)) visionEnsure('feedback_id' in resource && resource.feedback_id === pending.operation.split(':')[1]);
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
  } else if (name === 'run_normality_inference' || name === 'run_normality_ttt') {
    fields(v, [...common, 'expected_model_receipt_sha256', 'expected_model_pack_sha256', 'expected_backbone_weights_sha256', 'expected_source_binding_sha256',
      'expected_source_index_sha256', 'expected_runtime_sha256', 'asset_id', 'expected_asset_receipt_sha256', 'expected_image_sha256', 'max_seconds',
      'operator_attests_execution_authorized', 'operator_attests_trusted_runtime', 'operator_attests_trusted_weights', 'operator_attests_weights_only_load_authorized',
      ...(name === 'run_normality_ttt' ? ['expected_ttt_implementation_sha256', 'adaptation_assets', 'replay_assets', 'guard_assets', 'budget', 'operator_attests_ttt_authorized', 'operator_attests_replay_normal', 'operator_attests_guard_labels_reviewed'] : [])]);
    for (const key of ['expected_model_receipt_sha256', 'expected_model_pack_sha256', 'expected_backbone_weights_sha256', 'expected_source_binding_sha256',
      'expected_source_index_sha256', 'expected_runtime_sha256', 'expected_asset_receipt_sha256', 'expected_image_sha256']) visionSha(v[key]);
    visionId(v.asset_id); integer(v.max_seconds, 5, 300); visionEnsure(v.operator_attests_execution_authorized === true && v.operator_attests_trusted_runtime === true
      && v.operator_attests_trusted_weights === true && v.operator_attests_weights_only_load_authorized === true);
    if (name === 'run_normality_ttt') {
      visionSha(v.expected_ttt_implementation_sha256); const budget = validateTttBudget(v.budget); visionEnsure(budget.max_seconds <= v.max_seconds);
      visionEnsure(v.operator_attests_ttt_authorized === true && v.operator_attests_replay_normal === true && v.operator_attests_guard_labels_reviewed === true);
      const ids = new Set([String(v.asset_id)]), hashes = new Set([String(v.expected_image_sha256)]);
      for (const [name, min, max] of [['adaptation_assets', 0, 7], ['replay_assets', 1, 8], ['guard_assets', 2, 16]] as const) {
        const rows = v[name]; visionEnsure(Array.isArray(rows) && rows.length >= min && rows.length <= max);
        for (const raw of rows) { const row = visionObject(raw); fields(row, ['asset_id', 'expected_asset_receipt_sha256', 'expected_image_sha256', ...(name === 'guard_assets' ? ['reference_label'] : [])]);
          visionId(row.asset_id); visionSha(row.expected_asset_receipt_sha256); visionSha(row.expected_image_sha256);
          visionEnsure(!ids.has(row.asset_id) && !hashes.has(row.expected_image_sha256)); ids.add(row.asset_id); hashes.add(row.expected_image_sha256);
          if (name === 'guard_assets') visionEnsure(row.reference_label === 'normal' || row.reference_label === 'anomaly'); }
      }
      visionEnsure(new Set((v.guard_assets as { reference_label: string }[]).map(row => row.reference_label)).size === 2);
    }
  } else if (name === 'review_normality_inference') {
    fields(v, [...common, 'expected_inference_sha256', 'operator_attests_reviewed', 'classification']);
    visionSha(v.expected_inference_sha256); visionEnsure(v.operator_attests_reviewed === true && Object.hasOwn(normalityFollowupTypes, String(v.classification)));
  } else if (isNormalityFollowupOperation(operation)) {
    const order = name === 'create_normality_followup_work_order';
    fields(v, [...common, 'expected_feedback_sha256', 'expected_inference_sha256', 'expected_asset_sha256', 'expected_image_sha256', 'operator_attests_no_label_or_training_authority',
      ...(order ? ['import_id', 'expected_import_sha256', 'annotation_id', 'expected_annotation_revision', 'expected_annotation_document_sha256', 'assignee', 'operator_attests_create_work_order', 'operator_attests_reviewed_evidence'] : ['operator_attests_import_authorized'])]);
    for (const key of ['expected_feedback_sha256', 'expected_inference_sha256', 'expected_asset_sha256', 'expected_image_sha256']) visionSha(v[key]); visionEnsure(v.operator_attests_no_label_or_training_authority === true);
    if (order) { visionId(v.import_id); visionId(v.annotation_id); visionSha(v.expected_import_sha256); visionSha(v.expected_annotation_document_sha256); integer(v.expected_annotation_revision, 1, Number.MAX_SAFE_INTEGER); text(v.assignee, 1, 120); visionEnsure(v.operator_attests_create_work_order === true && v.operator_attests_reviewed_evidence === true); }
    else visionEnsure(v.operator_attests_import_authorized === true);
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

const normalityFollowupTypes = { MODEL_SIGNAL_CONFIRMED: 'MODEL_SIGNAL_REVIEW', LIKELY_FALSE_POSITIVE: 'FALSE_POSITIVE_INVESTIGATION', NEEDS_LABEL_REVIEW: 'LABEL_REVIEW', INSUFFICIENT_EVIDENCE: 'EVIDENCE_COLLECTION' } as const;
function validateNormalityFeedback(v: Record<string, unknown>, scope: VisionScope): NormalityFeedback {
  fields(v, ['schema_version', 'resource_id', 'feedback_id', 'project_id', 'inference_id', 'model_id', 'asset_id', 'inference_sha256', 'image_sha256', 'model_pack_sha256', 'heatmap_sha256', 'heatmap_artifact_id', 'created_by', 'reviewer_identity', 'note', 'created_at', 'classification', 'status', 'followup_work_item_type', 'followup_work_item_created', 'issue_closed', 'label_truth_authority', 'training_ingestion_allowed', 'production_release_allowed', 'machine_write_permitted', 'receipt_sha256']);
  visionEnsure(v.project_id === scope.projectId && v.resource_id === v.feedback_id && v.status === 'RECORDED_FOR_HUMAN_FOLLOWUP');
  for (const key of ['resource_id', 'inference_id', 'model_id', 'asset_id', 'heatmap_artifact_id', 'created_by']) visionId(v[key]);
  for (const key of ['inference_sha256', 'image_sha256', 'model_pack_sha256', 'heatmap_sha256']) visionSha(v[key]);
  text(v.reviewer_identity, 2, 160); text(v.note, 8, 1000); text(v.created_at); visionEnsure(Number.isFinite(Date.parse(v.created_at)));
  visionEnsure(Object.hasOwn(normalityFollowupTypes, String(v.classification)) && v.followup_work_item_type === normalityFollowupTypes[v.classification as NormalityFeedbackClassification]);
  for (const key of ['followup_work_item_created', 'issue_closed', 'label_truth_authority', 'training_ingestion_allowed', 'production_release_allowed', 'machine_write_permitted']) visionEnsure(v[key] === false);
  return v as unknown as NormalityFeedback;
}
export async function validateNormalityFeedbackList(value: unknown, scope: VisionScope, inference: VisionInference, etag: string | null, contentSha: string | null): Promise<NormalityFeedback[]> {
  const v = await verifyVisionSeal(value, etag, contentSha);
  visionEnsure(v.schema_version === 'visiondata-gate.vision-list.v1' && v.project_id === scope.projectId && v.inference_id === inference.inference_id && Array.isArray(v.items));
  const items = await Promise.all(v.items.map(item => validateVisionRecord(item, scope, 'normality_feedback') as Promise<NormalityFeedback>));
  visionEnsure(new Set(items.map(item => item.feedback_id)).size === items.length);
  for (const item of items) visionEnsure(item.inference_id === inference.inference_id && item.inference_sha256 === inference.receipt_sha256 && item.model_id === inference.model_id
    && item.asset_id === inference.asset_id && item.image_sha256 === inference.image_sha256 && item.model_pack_sha256 === inference.model_pack_sha256
    && item.heatmap_sha256 === inference.heatmap.sha256 && item.heatmap_artifact_id === inference.heatmap_artifact_id);
  return items;
}

export function visionStatusLabel(status: VisionRunStatus): string {
  return { QUEUED: '已授权 · 等待执行', RUNNING: 'CPU 训练中', SUCCEEDED_CANDIDATE: '候选已生成 · 效果未达标判定', FAILED: '执行失败', CANCELLED: '已取消', TIMED_OUT: '预算超时', INTERRUPTED_HOLD: '执行中断 · HOLD' }[status];
}

export function validateTttBudget(value: unknown): VisionTttBudget {
  const v = visionObject(value); fields(v, ['steps', 'learning_rate', 'max_seconds', 'seed']); integer(v.steps, 1, 8); integer(v.max_seconds, 5, 120); integer(v.seed, 0, 2147483647);
  visionEnsure(typeof v.learning_rate === 'number' && Number.isFinite(v.learning_rate) && v.learning_rate >= .00001 && v.learning_rate <= .01); return v as unknown as VisionTttBudget;
}

export function isNormalityFollowupOperation(operation: string): boolean { return /^(import_normality_followup|create_normality_followup_work_order):/.test(operation); }
function followupGates(v: Record<string, unknown>) { for (const key of ['issue_closed', 'label_truth_authority', 'training_ingestion_allowed', 'production_release_allowed', 'machine_write_permitted', 'annotation_created']) visionEnsure(v[key] === false); }
function validateNormalityFollowupRecord(v: Record<string, unknown>, scope: VisionScope): NormalityFollowupImport | NormalityFollowupWorkOrder {
  visionEnsure(v.project_id === scope.projectId && v.workspace_id === scope.workspaceId && v.created_by === scope.actorId && v.coordinate_frame === 'DECODED_PIXELS_EXIF_IDENTITY' && v.annotation_created === false); followupGates(v);
  for (const key of ['resource_id', 'feedback_id', 'inference_id', 'vision_asset_id', 'operator_asset_id']) visionId(v[key]);
  for (const key of ['feedback_sha256', 'inference_sha256', 'vision_asset_sha256', 'image_sha256', 'operator_source_sha256']) visionSha(v[key]); visionEnsure(v.operator_source_sha256 === v.image_sha256);
  integer(v.image_width, 1, 8192); integer(v.image_height, 1, 8192); text(v.reviewer_identity, 2, 160); text(v.note, 8, 1000); text(v.created_at); visionEnsure(Number.isFinite(Date.parse(v.created_at)));
  if (v.schema_version === 'visiondata-gate.normality-followup-import.v1') visionEnsure(v.import_id === v.resource_id && v.status === 'ASSET_IMPORTED_AWAITING_HUMAN_ANNOTATION' && v.work_order_created === false);
  else {
    visionEnsure(v.binding_id === v.resource_id && v.status === 'OPEN' && v.work_order_created === true);
    for (const key of ['import_id', 'annotation_id', 'work_order_id']) visionId(v[key]);
    for (const key of ['import_sha256', 'annotation_document_sha256', 'work_order_document_sha256', 'crop_sha256']) visionSha(v[key]); integer(v.annotation_revision, 1, Number.MAX_SAFE_INTEGER); text(v.assignee, 1, 120);
  }
  return v as unknown as NormalityFollowupImport | NormalityFollowupWorkOrder;
}
export async function validateNormalityFollowupList(value: unknown, scope: VisionScope, feedback: NormalityFeedback, etag: string | null, contentSha: string | null): Promise<NormalityFollowupList> {
  const v = await verifyVisionSeal(value, etag, contentSha); visionEnsure(v.schema_version === 'visiondata-gate.normality-followup-list.v1' && v.project_id === scope.projectId && v.feedback_id === feedback.feedback_id && Array.isArray(v.imports) && Array.isArray(v.work_orders)); followupGates(v);
  const imports = await Promise.all(v.imports.map(row => validateVisionRecord(row, scope, 'normality_followup_import') as Promise<NormalityFollowupImport>));
  const orders = await Promise.all(v.work_orders.map(row => validateVisionRecord(row, scope, 'normality_followup_work_order') as Promise<NormalityFollowupWorkOrder>));
  for (const row of [...imports, ...orders]) visionEnsure(row.feedback_id === feedback.feedback_id && row.feedback_sha256 === feedback.receipt_sha256 && row.inference_id === feedback.inference_id && row.inference_sha256 === feedback.inference_sha256 && row.image_sha256 === feedback.image_sha256 && row.vision_asset_id === feedback.asset_id);
  visionEnsure(new Set(imports.map(row => row.import_id)).size === imports.length && new Set(orders.map(row => row.binding_id)).size === orders.length);
  for (const order of orders) visionEnsure(imports.some(row => row.import_id === order.import_id && row.receipt_sha256 === order.import_sha256 && row.operator_asset_id === order.operator_asset_id));
  return { imports, work_orders: orders };
}
export async function validateNormalityFollowupAnnotations(value: unknown, scope: VisionScope, imported: NormalityFollowupImport, etag: string | null, contentSha: string | null): Promise<NormalityFollowupAnnotations> {
  const v = await verifyVisionSeal(value, etag, contentSha); visionEnsure(v.schema_version === 'visiondata-gate.normality-followup-annotations.v1' && v.project_id === scope.projectId && v.workspace_id === scope.workspaceId
    && v.feedback_id === imported.feedback_id && v.import_id === imported.import_id && v.operator_asset_id === imported.operator_asset_id && v.asset_sha256 === imported.image_sha256); followupGates(v);
  integer(v.revision, 0, Number.MAX_SAFE_INTEGER); visionSha(v.document_sha256); visionEnsure(Array.isArray(v.annotations) && v.annotations.length <= 500);
  for (const raw of v.annotations) { const row = visionObject(raw); visionId(row.annotation_id); text(row.label, 1, 120); visionEnsure(row.source === 'MANUAL' || row.source === 'IMPORTED');
    for (const key of ['x', 'y', 'width', 'height']) visionEnsure(typeof row[key] === 'number' && Number.isFinite(row[key]) && row[key] >= 0 && row[key] <= 1);
    visionEnsure(Number(row.width) > 0 && Number(row.height) > 0 && Number(row.x) + Number(row.width) <= 1.000000001 && Number(row.y) + Number(row.height) <= 1.000000001); }
  visionEnsure(new Set(v.annotations.map(row => (row as { annotation_id: string }).annotation_id)).size === v.annotations.length); return v as unknown as NormalityFollowupAnnotations;
}
export async function validateVisionTttCapabilities(value: unknown, scope: VisionScope, etag: string | null, contentSha: string | null): Promise<VisionTttCapabilities> {
  validateVisionScope(scope); const v = await verifyVisionSeal(value, etag, contentSha);
  visionEnsure(v.schema_version === 'visiondata-gate.normality-ttt-capabilities.v1' && v.project_id === scope.projectId && v.strategy === 'EPISODIC_MASKED_STUDENT'); visionSha(v.implementation_sha256);
  visionEnsure(v.max_steps === 8 && v.max_learning_rate === .01 && v.min_learning_rate === .00001 && v.max_seconds === 120 && v.max_adaptation_assets === 7 && v.max_replay_assets === 8 && v.max_guard_assets === 16
    && v.production_release_allowed === false && v.machine_write_permitted === false && v.persistent_learning === false && v.industrial_benefit_validated === false); validateTttGuardPolicy(v.guard_policy); return v as unknown as VisionTttCapabilities;
}
function validateTttGuardPolicy(value: unknown) { const v = visionObject(value); fields(v, ['min_true_positive', 'min_true_negative', 'max_fp_increase', 'max_fn_increase']); visionEnsure(v.min_true_positive === 1 && v.min_true_negative === 1 && v.max_fp_increase === 0 && v.max_fn_increase === 0); }
function validateTttMatrix(value: unknown): VisionTttMatrix {
  const v = visionObject(value); fields(v, ['tp', 'tn', 'fp', 'fn']); for (const key of ['tp', 'tn', 'fp', 'fn']) integer(v[key], 0, 16);
  visionEnsure(Number(v.tp) + Number(v.fn) > 0 && Number(v.tn) + Number(v.fp) > 0); return v as unknown as VisionTttMatrix;
}
function validateTttReport(value: unknown, implementation: string, imageSha: string): VisionTttReport {
  const v = visionObject(value); visionEnsure(v.schema_version === 'visiondata-gate.normality-ttt.v1' && v.strategy === 'EPISODIC_MASKED_STUDENT' && ['ACCEPTED_EPISODIC', 'ROLLED_BACK'].includes(String(v.status))
    && v.implementation_sha256 === implementation && v.reset_after_episode === true && v.persistent_learning === false && v.parent_pack_unchanged === true && v.thresholds_unchanged === true && v.industrial_benefit_validated === false);
  validateTttGuardPolicy(v.guard_policy);
  for (const key of ['parameter_sha256_before', 'parameter_sha256_after', 'attempted_parameter_sha256', 'effective_parameter_sha256', 'backbone_sha256_before', 'backbone_sha256_after']) visionSha(v[key]);
  visionEnsure(v.backbone_sha256_before === v.backbone_sha256_after && v.parameter_sha256_after === v.attempted_parameter_sha256);
  const budget = validateTttBudget(v.budget); integer(v.steps_completed, 0, budget.steps);
  visionEnsure(Array.isArray(v.loss_curve) && v.loss_curve.length === v.steps_completed);
  v.loss_curve.forEach((raw, index) => { const row = visionObject(raw); visionEnsure(row.step === index + 1);
    for (const key of ['loss', 'reconstruction_loss', 'replay_loss', 'anchor_loss', 'gradient_norm']) visionEnsure(typeof row[key] === 'number' && Number.isFinite(row[key]) && row[key] >= 0);
    visionEnsure(Number(row.gradient_norm) > 0); });
  const finiteObjective = (number: unknown) => typeof number === 'number' && Number.isFinite(number) && number >= 0;
  if (v.steps_completed === 0) visionEnsure(v.objective_before === null && v.objective_after === null);
  else visionEnsure(finiteObjective(v.objective_before) && v.objective_before === visionObject(v.loss_curve[0]).loss && (v.objective_after === null || finiteObjective(v.objective_after)));
  const groups = visionObject(v.input_groups), seen = new Set<string>(); let guards = 0;
  for (const [name, min, max] of [['adaptation', 1, 8], ['replay', 1, 8], ['guard', 2, 16]] as const) {
    const group = visionObject(groups[name]); fields(group, ['count', 'sha256']); integer(group.count, min, max); visionEnsure(Array.isArray(group.sha256) && group.sha256.length === group.count);
    for (const hash of group.sha256) { visionSha(hash); visionEnsure(!seen.has(hash)); seen.add(hash); }
    if (name === 'adaptation') visionEnsure(group.sha256.includes(imageSha)); if (name === 'guard') guards = group.count;
  }
  const before = validateTttMatrix(v.guard_before), effective = validateTttMatrix(v.effective_guard), after = v.guard_after === null ? null : validateTttMatrix(v.guard_after);
  visionEnsure(before.tp + before.tn + before.fp + before.fn === guards);
  for (const matrix of [effective, ...(after ? [after] : [])]) visionEnsure(matrix.tp + matrix.fn === before.tp + before.fn && matrix.tn + matrix.fp === before.tn + before.fp);
  if (v.status === 'ACCEPTED_EPISODIC') {
    visionEnsure(finiteObjective(v.objective_before) && finiteObjective(v.objective_after) && Number(v.objective_after) < Number(v.objective_before));
    visionEnsure(v.rollback_reason === null && v.steps_completed === budget.steps && v.parameter_sha256_before !== v.parameter_sha256_after && v.effective_parameter_sha256 === v.parameter_sha256_after
      && before.tp >= 1 && before.tn >= 1 && after && after.fp <= before.fp && after.fn <= before.fn && (['tp', 'tn', 'fp', 'fn'] as const).every(key => effective[key] === after[key]));
  } else visionEnsure(typeof v.rollback_reason === 'string' && /^[A-Z0-9_]{1,120}$/.test(v.rollback_reason) && v.effective_parameter_sha256 === v.parameter_sha256_before && (['tp', 'tn', 'fp', 'fn'] as const).every(key => effective[key] === before[key]));
  return v as unknown as VisionTttReport;
}
