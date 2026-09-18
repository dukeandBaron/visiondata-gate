/** Synthetic records matching local_model_registry.py; never load models or user data. */
import { canonicalizeJcs, sha256HexUtf8 } from '../web/src/data/jcs.ts';
export const scope = { workspaceId: 'workspace_vision_test', projectId: 'project_vision_test', actorId: 'usr_vision_test' };
export const sha = (letter = 'a') => letter.repeat(64);
export const digest = value => sha256HexUtf8(canonicalizeJcs(value));
export async function seal(value, excludes = []) { const body = { ...value }; delete body.receipt_sha256; excludes.forEach(key => delete body[key]); return { ...value, receipt_sha256: await digest(body) }; }
export function manifest() { return { schema_version: 'visiondata-gate.detection-dataset.v1', source_version: 'synthetic-detection-v1', class_names: ['defect'], samples: ['train', 'val', 'test'].map((split, index) => ({
  sample_id: `${split}_sample`, image_path: `images/${split}.png`, image_sha256: sha(['a', 'b', 'c'][index]), split,
  group_id: `group_${split}`, annotation_revision: 1, boxes: [{ class_id: 0, x_center: .5, y_center: .5, width: .25, height: .25 }], reviewer_name: 'Synthetic reviewer', reviewed: true, normal_attested: false,
})) }; }
function base(kind) { return { schema_version: `visiondata-gate.vision_${kind}.v1`, resource_id: `vision_${kind}_test`, [`${kind}_id`]: `vision_${kind}_test`,
  project_id: scope.projectId, created_by: scope.actorId, reviewer_identity: 'Synthetic reviewer', created_at: '2026-09-13T00:00:00Z', production_release_allowed: false, machine_write_permitted: false }; }
export async function model() { return seal({ ...base('model'), display_name: 'Local YOLO26n test', task_type: 'detect', weights_sha256: sha(), file_bytes: 1234,
  format: 'pt', license_id: 'AGPL-3.0', license_status: 'OPERATOR_DECLARED_NOT_LEGAL_VERIFICATION', source_description: 'Synthetic owned fixture', status: 'REGISTERED_NOT_LOADED', loaded: false }); }
export async function normalityModel(status = 'MODEL_PACK_EVIDENCE_VERIFIED') {
  const approved = status === 'APPROVE_SANDBOX';
  return seal({ ...base('model'), resource_id: 'vision_normality_model_test', model_id: 'vision_normality_model_test', display_name: 'Bound normality pack', model_kind: 'YOLO26_NORMALITY_MODEL_PACK', task_type: 'normality', format: 'pt',
    model_pack_schema_version: 'visiondata-gate.yolo26-normality-model-pack.v2', model_pack_sha256: sha('a'), weights_sha256: sha('a'), backbone_weights_sha256: sha('b'),
    source_binding_sha256: sha('c'), source_index_sha256: sha('d'), architecture: 'yolo26n', feature_layers: [4, 6, 9], split_seed: 20260913, model_seed: 20260913,
    stability_schema_version: 'visiondata-gate.model-stability.v4', verification_implementation: { stability_module_sha256: sha('e'), outcome_policy_module_sha256: sha('f'), outcome_policy_function: 'classify_experiment_outcome' },
    stability_run_artifact_sha256: { seed_20260911: { 'RUN_RECEIPT.json': sha('1') }, seed_20260912: { 'RUN_RECEIPT.json': sha('2') }, seed_20260913: { 'RUN_RECEIPT.json': sha('3') } },
    stability_status: 'PUBLIC_PROXY_STABLE', stability_eligible: true, stability_blockers: [], evidence_file_sha256: { model_pack: sha('a'), stability_summary: sha('4'), source_binding_file: sha('5'), source_index_file: sha('6'), backbone_weights: sha('b') },
    license_id: 'AGPL-3.0_OR_ENTERPRISE_REVIEW_REQUIRED', license_status: 'OPERATOR_ACKNOWLEDGED_NOT_LEGAL_VERIFICATION', status,
    usage_scope: approved ? 'LOCAL_SANDBOX_ONLY' : 'SANDBOX_CANDIDATE', sandbox_eligible: true,
    sandbox_runtime_id: approved ? 'vision_runtime_test' : null, sandbox_runtime_sha256: approved ? sha('c') : null,
    ...(approved ? { sandbox_validation: { status: 'VALIDATED_FOR_LOCAL_SANDBOX', model_pack_sha256: sha('a'), backbone_weights_sha256: sha('b'), source_binding_sha256: sha('c'), source_index_sha256: sha('d'), runtime_sha256: sha('c'), inference_backend_sha256: sha('7'), model_pack_schema_version: 'visiondata-gate.yolo26-normality-model-pack.v2', production_release_allowed: false } } : {}),
    loaded: false, storage_scope: 'REGISTRY_OWNED_CONTENT_ADDRESSED' });
}
function inferenceBase(kind, identifier) { return { schema_version: `visiondata-gate.${kind}.v1`, resource_id: identifier, project_id: scope.projectId, created_by: scope.actorId,
  reviewer_identity: 'Synthetic reviewer', created_at: '2026-09-13T00:00:00Z', production_release_allowed: false, machine_write_permitted: false }; }
export async function inferenceAsset() { const identifier = 'vision_inference_asset_test'; return seal({ ...inferenceBase('vision_inference_asset', identifier), asset_id: identifier,
  display_name: 'Frozen local image', image_sha256: sha('8'), image_bytes: 2048, image_width: 256, image_height: 192, format: 'png', storage_scope: 'REGISTRY_OWNED_CONTENT_ADDRESSED', status: 'FROZEN_LOCAL_INFERENCE_ASSET' }); }
export async function normalityInference() { const identifier = 'vision_inference_test'; return seal({ ...inferenceBase('vision_inference', identifier), inference_id: identifier,
  model_id: 'vision_normality_model_test', asset_id: 'vision_inference_asset_test', runtime_id: 'vision_runtime_test', model_pack_sha256: sha('a'), backbone_weights_sha256: sha('b'),
  source_binding_sha256: sha('c'), source_index_sha256: sha('d'), runtime_sha256: sha('c'), inference_backend_sha256: sha('7'), image_sha256: sha('8'),
  status: 'COMPLETED_LOCAL_SANDBOX_INFERENCE', image_score: 0.75, image_threshold: 0.5, pixel_threshold: 1.5, predicted_anomaly: true, positive_pixel_fraction: 0.125,
  heatmap_artifact_id: 'normality_heatmap_0123456789abcdef01234567', heatmap: { sha256: sha('9'), bytes: 4096, width: 64, height: 64, format: 'png' }, device: 'cpu',
  decision_scope: 'MODEL_SIGNAL_ONLY_NOT_GATE_OR_PRODUCTION_DECISION', review_required: true, gate_decision: 'NOT_ISSUED' }); }
export function registerNormalityPackRequest() { return { ...approval, display_name: 'Bound normality pack', model_pack_path: 'C:/synthetic/normality/model-pack.pt', expected_model_pack_sha256: sha('a'),
  run_directory: 'C:/synthetic/normality/seed_20260913', stability_run_directories: ['C:/synthetic/normality/seed_20260911', 'C:/synthetic/normality/seed_20260912', 'C:/synthetic/normality/seed_20260913'],
  target_model_seed: 20260913, stability_summary_path: 'C:/synthetic/normality/model_stability_summary.json', expected_stability_summary_sha256: sha('4'),
  source_binding_path: 'C:/synthetic/normality/source_binding.json', expected_source_binding_file_sha256: sha('5'), expected_source_binding_sha256: sha('c'),
  source_index_path: 'C:/synthetic/normality/source_index.json', expected_source_index_file_sha256: sha('6'), expected_source_index_sha256: sha('d'),
  backbone_weights_path: 'C:/synthetic/normality/backbone.pt', expected_backbone_weights_sha256: sha('b'), operator_attests_read_authorized: true,
  operator_attests_weights_only_load_authorized: true, ultralytics_license_acknowledged: true }; }
export async function approveNormalityPackRequest() { const value = await normalityModel(); return { ...approval, action: 'APPROVE_SANDBOX', expected_model_receipt_sha256: value.receipt_sha256,
  expected_model_pack_sha256: value.model_pack_sha256, expected_backbone_weights_sha256: value.backbone_weights_sha256, expected_source_binding_sha256: value.source_binding_sha256,
  expected_source_index_sha256: value.source_index_sha256, runtime_id: 'vision_runtime_test', expected_runtime_sha256: sha('c'), operator_attests_reviewed: true,
  operator_attests_trusted_runtime: true, operator_attests_execution_authorized: true, operator_attests_trusted_weights: true,
  operator_attests_weights_only_load_authorized: true, ultralytics_license_acknowledged: true }; }
export function registerInferenceAssetRequest() { return { ...approval, display_name: 'Frozen local image', image_path: 'C:/synthetic/images/part.png', expected_image_sha256: sha('8'), operator_attests_read_authorized: true }; }
export async function runNormalityInferenceRequest() { const value = await normalityModel('APPROVE_SANDBOX'), asset = await inferenceAsset(); return { ...approval,
  expected_model_receipt_sha256: value.receipt_sha256, expected_model_pack_sha256: value.model_pack_sha256, expected_backbone_weights_sha256: value.backbone_weights_sha256,
  expected_source_binding_sha256: value.source_binding_sha256, expected_source_index_sha256: value.source_index_sha256, expected_runtime_sha256: value.sandbox_runtime_sha256,
  asset_id: asset.asset_id, expected_asset_receipt_sha256: asset.receipt_sha256, expected_image_sha256: asset.image_sha256, max_seconds: 120,
  operator_attests_execution_authorized: true, operator_attests_trusted_runtime: true, operator_attests_trusted_weights: true, operator_attests_weights_only_load_authorized: true }; }
export async function runtime(importStatus = 'NOT_RUN') { return seal({ ...base('runtime'), display_name: 'Python metadata fixture', executable_sha256: sha('b'), runtime_sha256: sha('c'), status: importStatus === 'PASSED' ? 'PROBED' : 'METADATA_PROBED_IMPORT_NOT_TESTED',
  probe: { status: 'ready', import_status: importStatus, runtime_sha256: sha('c'), executable_sha256: sha('b'), python_version: [3, 12, 0], packages: { torch: '2.6.0', torchvision: '0.21.0', ultralytics: '8.4.33', numpy: '2.2.6' } } }); }
export async function dataset() {
  const input = manifest(); const receipt = await seal({ schema_version: 'visiondata-gate.detection-dataset-receipt.v1', source_version: input.source_version, class_names: input.class_names,
    manifest_sha256: await digest(input), samples: input.samples.map((sample, index) => ({ ...sample, image_path: `images/${sample.split}/${sample.sample_id}.png`,
      label_path: `labels/${sample.split}/${sample.sample_id}.txt`, pixel_sha256: sha(['d', 'e', 'f'][index]), label_sha256: sha(), width: 64, height: 64 })),
    split_counts: { train: 1, val: 1, test: 1 }, data_yaml_sha256: sha() });
  receipt.dataset_id = `detds_${receipt.receipt_sha256.slice(0, 24)}`;
  return seal({ ...base('dataset'), dataset_receipt_sha256: receipt.receipt_sha256, dataset_receipt: receipt, status: 'FROZEN_REVIEWED_DETECTION_DATASET' });
}
export const approval = { request_key: 'vision_test_request_1234', reviewer_identity: 'Synthetic reviewer', note: 'Explicit synthetic test authorization' };
export async function createRequest() { const d = await dataset(); return { ...approval, runtime_id: 'vision_runtime_test', expected_runtime_sha256: sha('c'), dataset_id: d.dataset_id,
  expected_dataset_receipt_sha256: d.dataset_receipt_sha256, initialization: 'ARCHITECTURE_RANDOM', initial_model_id: null, expected_weights_sha256: null, architecture: 'yolo26n',
  training: { epochs: 1, imgsz: 64, batch: 2, seed: 0, max_seconds: 120, threads: 2 }, operator_attests_training_authorized: true, operator_attests_trusted_runtime: true,
  operator_attests_trusted_weights: false, operator_attests_pickle_load_risk: false, ultralytics_license_acknowledged: true, adaptation: 'OFF', responds_to_feedback_ids: [], expected_feedback_receipts: {} }; }
export async function run(status = 'SUCCEEDED_CANDIDATE') {
  const request = await createRequest(); return seal({ ...base('run'), status, runtime_id: request.runtime_id, runtime_sha256: request.expected_runtime_sha256,
    dataset_id: request.dataset_id, dataset_receipt_sha256: request.expected_dataset_receipt_sha256, initial_model_id: null, initialization: request.initialization, pretrained_claimed: false,
    architecture: 'yolo26n', device: 'cpu', training: request.training, adaptation: 'OFF', ttt_status: 'DISABLED_NOT_IMPLEMENTED', authorization_sha256: await digest(request), cancel_requested: false,
    candidate_model_id: status === 'SUCCEEDED_CANDIDATE' ? 'vision_model_candidate_test' : null, selection: 'PENDING', error_code: null,
    result: status === 'SUCCEEDED_CANDIDATE' ? { status: 'completed', device: 'cpu', production_approved: false, test_evaluation: 'NOT_RUN', baseline: { 'metrics/mAP50-95(B)': 0 }, candidate: { 'metrics/mAP50-95(B)': 0 },
      actual_epochs: 1, training_samples: 1, validation_samples: 1, checkpoint: { relative_path: 'train/weights/last.pt', sha256: sha('f'), bytes: 1000, round_trip: 'VERIFIED', selection: 'last_epoch' } } : null });
}
export async function capabilities() { return seal({ schema_version: 'visiondata-gate.vision-capabilities.v1', project_id: scope.projectId, model_domain: 'LOCAL_VISUAL_MODELS', llm_provider_managed: false,
  supported_registration_tasks: ['detect', 'segment', 'normality'], executable_training_tasks: ['detect'], executable_inference_tasks: ['normality'], training_device: 'CPU_ONLY', normality_runtime: 'EXTERNAL_RUNTIME_REQUIRED', initializations: ['ARCHITECTURE_RANDOM', 'REGISTERED_WEIGHTS'], ttt_status: 'DISABLED_NOT_IMPLEMENTED',
  weight_download_allowed: false, registered_model_count: 1, registered_runtime_count: 1, registered_dataset_count: 1, training_ready: true, training_authorization_required: true,
  sandbox_approved_normality_model_count: 0, registered_inference_asset_count: 0, completed_normality_inference_count: 0,
  license_boundary: 'ULTRALYTICS_AGPL_3_0_OR_ENTERPRISE_REVIEW_REQUIRED', production_release_allowed: false, industrial_effectiveness_status: 'NOT_EVALUATED' }); }
export async function list(items) { return seal({ schema_version: 'visiondata-gate.vision-list.v1', project_id: scope.projectId, items }); }
export async function operation(pending, resource) { return seal({ schema_version: 'visiondata-gate.vision-operation.v1', project_id: scope.projectId, operation: pending.operation,
  request_key: pending.requestKey, resource_id: resource.resource_id, resource, auto_replayed: false }); }
export function response(value, headers = {}) { return new Response(JSON.stringify(value), { headers: { 'Content-Type': 'application/json', ETag: `"${value.receipt_sha256}"`, 'X-Content-SHA256': value.receipt_sha256, 'Cache-Control': 'private, no-store', ...headers } }); }
export async function poolProjection() {
  const members = manifest().samples.map(sample => ({ sample_id: sample.sample_id, source_task_id: 'task_pool_test', split: sample.split, category: 'defect', annotation_requirement: 'REQUIRED',
    readiness_state: 'GATE_ELIGIBLE_NOT_TRAINING_APPROVED', asset_sha256: sample.image_sha256, annotation_revision: 1, annotation_sha256: sha(), mask_sha256: sha(), finding_refs: [], repair_cause_codes: [],
    disposition: 'QUALIFIED_CANDIDATE', repair_action: 'NONE', repair_result: 'NOT_APPLICABLE', decision_note: 'Reviewed explicit synthetic labels', label_truth_authority: false }));
  const version = await seal({ schema_version: 'visiondata-gate.data-pool-version.v1', version_id: 'poolv_test', pool_id: 'pool_test', version_number: 1, parent_version_id: null, parent_version_sha256: null,
    source_task_id: 'task_pool_test', workspace_id: scope.workspaceId, project_id: scope.projectId, source_id: 'source_test', snapshot_id: 'snapshot_test', snapshot_receipt_sha256: sha(), batch_manifest_sha256: sha(),
    batch_contract_sha256: sha(), gate_result_sha256: sha(), readiness_receipt_sha256: sha(), preflight_receipt_sha256: sha(), status: 'REVIEWED_ALL_QUALIFIED_REFERENCE', qualified_count: 3, repair_count: 0, hold_count: 0,
    members, global_finding_refs: [], unmapped_finding_refs: [], readiness_blockers: [], human_review: { reviewer_name: 'Synthetic reviewer', review_note: 'All explicit source labels were reviewed', reviewed_by: scope.actorId, operator_attests_reviewed: true },
    created_at: '2026-09-13T00:00:00Z', label_truth_authority: false, training_ingestion_allowed: false, production_release_allowed: false });
  const pool = await seal({ schema_version: 'visiondata-gate.data-pool.v1', pool_id: 'pool_test', workspace_id: scope.workspaceId, project_id: scope.projectId, origin_task_id: 'task_pool_test', current_task_id: 'task_pool_test',
    origin_source_id: 'source_test', current_source_id: 'source_test', origin_snapshot_id: 'snapshot_test', current_snapshot_id: 'snapshot_test', version_ids: ['poolv_test'], current_version_id: 'poolv_test', created_by: scope.actorId,
    created_at: '2026-09-13T00:00:00Z', label_truth_authority: false, production_release_allowed: false });
  return seal({ schema_version: 'visiondata-gate.data-pool-projection.v1', pool, current_version: version, read_status: 'CURRENT', stale_reasons: [], training_ingestion_allowed: false, production_release_allowed: false });
}
export async function poolDataset() {
  const projection = await poolProjection(); const record = await dataset(); const input = manifest(); input.source_version = 'poolv_test';
  let d = { ...record.dataset_receipt, source_version: 'poolv_test', manifest_sha256: await digest(input) }; delete d.dataset_id;
  d = await seal(d); d.dataset_id = `detds_${d.receipt_sha256.slice(0, 24)}`;
  const frame = { schema_version: 'visiondata-gate.operator-detection-frame.v1', input_coordinates: 'normalized_xywh', input_origin: 'top_left', output_coordinates: 'normalized_center_xywh', image_frame: 'frozen_original_width_height', mask_conversion: false };
  const binding = await seal({ schema_version: 'visiondata-gate.pool-detection-binding.v1', project_id: scope.projectId, task_id: 'task_pool_test', source_id: 'source_test', pool_id: 'pool_test', version_id: 'poolv_test',
    pool_receipt_sha256: projection.pool.receipt_sha256, version_receipt_sha256: projection.current_version.receipt_sha256, snapshot_id: 'snapshot_test', snapshot_receipt_sha256: sha(), source_profile_sha256: sha(), batch_manifest_sha256: sha(), batch_contract_sha256: sha(),
    gate_result_sha256: sha(), readiness_receipt_sha256: sha(), class_names: ['defect'], class_mapping_sha256: await digest(['defect']), groups: Object.fromEntries(input.samples.map(s => [s.sample_id, s.group_id])), normal_sample_ids: [], coordinate_frame: frame,
    coordinate_frame_sha256: await digest(frame), annotation_bindings_sha256: sha(), detection_manifest_sha256: d.manifest_sha256, sample_count: 3, production_release_allowed: false, label_truth_authority: false });
  return seal({ ...record, dataset_receipt: d, dataset_receipt_sha256: d.receipt_sha256, pool_binding: binding });
}
export async function feedbackFixture() {
  const original = await run(), d = await dataset(); const sample = d.dataset_receipt.samples.find(row => row.split === 'val');
  const detail = { sample_id: sample.sample_id, image_sha256: sample.image_sha256, label_sha256: sample.label_sha256, prediction_boxes: [], ground_truth_boxes: [{ class_id: 0, xyxy: [.375, .375, .625, .625] }],
    tp: 0, fp: 0, fn: 1, matched_ious: [], matches: [], reason_codes: ['FALSE_NEGATIVE_CANDIDATE'], review_required: true };
  const protocol = { schema_version: 'visiondata-gate.validation-feedback.v1', split: 'val', confidence_threshold: .25, iou_threshold: .5, max_detections: 300,
    matching: 'class_aware_greedy_iou_descending', prediction_order: 'confidence_descending_then_class_and_coordinates', tie_break: 'prediction_index_then_ground_truth_index',
    dataset_sha256: sha('d'), checkpoint_sha256: original.result.checkpoint.sha256, runtime_sha256: original.runtime_sha256, sample_count: 1, review_required: true,
    label_truth_status: 'REFERENCE_LABELS_NOT_ADJUDICATED', interpretation: 'Fixed operating-point disagreements, not aggregate mAP or adjudicated label errors' };
  const identifier = `vfeedback_${(await digest({ run_id: original.run_id, sample: detail, protocol })).slice(0, 24)}`;
  const feedback = await seal({ schema_version: 'visiondata-gate.vision-feedback.v1', resource_id: identifier, feedback_id: identifier, project_id: scope.projectId, run_id: original.run_id, dataset_id: d.dataset_id,
    dataset_receipt_sha256: d.dataset_receipt_sha256, sample_id: sample.sample_id, split: 'val', image_sha256: detail.image_sha256, label_sha256: detail.label_sha256,
    checkpoint_sha256: original.result.checkpoint.sha256, protocol_sha256: await digest(protocol), detail, status: 'PENDING_HUMAN_REVIEW', classification: null,
    issue_closed: false, label_truth_authority: false, training_ingestion_allowed: false, production_release_allowed: false });
  const updated = await seal({ ...original, responds_to_feedback_ids: [], feedback_ids: [identifier], feedback_status: 'VAL_DISAGREEMENTS_REQUIRE_HUMAN_REVIEW',
    result: { ...original.result, dataset_sha256: sha('d'), runtime_sha256: original.runtime_sha256, validation_feedback_protocol: protocol, validation_samples_detail: [detail] } });
  return { run: updated, feedback, list: await seal({ ...await list([feedback]), run_id: updated.run_id }) };
}
export async function newDetectionDataset() {
  const original = await dataset(), input = manifest(); input.source_version = 'new-reviewed-data-v2';
  const receipt = await seal({ ...original.dataset_receipt, source_version: input.source_version, manifest_sha256: await digest(input) }, ['dataset_id']);
  receipt.dataset_id = `detds_${receipt.receipt_sha256.slice(0, 24)}`;
  return seal({ ...original, resource_id: 'vision_dataset_new', dataset_id: 'vision_dataset_new', dataset_receipt: receipt, dataset_receipt_sha256: receipt.receipt_sha256 });
}
