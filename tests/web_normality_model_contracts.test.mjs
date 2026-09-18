import assert from 'node:assert/strict';
import test from 'node:test';
import { registerHooks } from 'node:module';
import * as domain from '../web/src/visionModelDomain.ts';
import { setIdentitySession } from '../web/src/identitySession.ts';
import { scope, sha, seal, list, operation, response, normalityModel, inferenceAsset, normalityInference,
  registerNormalityPackRequest, approveNormalityPackRequest, registerInferenceAssetRequest, runNormalityInferenceRequest,
  approval, normalityFeedback, normalityPngBase64, previewInference } from './web_vision_model_fixtures.mjs';
import { capabilities, runtime, tttCapabilities, tttRequest, tttInference, tttFailure, normalityFollowupImport, normalityFollowupWorkOrder, followupRequest } from './web_vision_model_fixtures.mjs';

const stub = 'data:text/javascript,' + encodeURIComponent(`export class OperatorApiError extends Error { constructor(code,message,status){super(message);this.code=code;this.status=status;} } export function operatorFetch(...args){return globalThis.__visionTransport(...args);}`);
const hooks = registerHooks({ resolve(specifier, context, next) { if ((context.parentURL?.endsWith('/data/visionModelApi.ts') || context.parentURL?.endsWith('/data/dataPoolApi.ts')) && specifier === './api') return { url: stub, shortCircuit: true }; return next(specifier, context); } });
const api = await import('../web/src/data/visionModelApi.ts'); hooks.deregister();
const hold = { code: 'VISION_CONTRACT_HOLD' };
function identity() { setIdentitySession({ user_id: scope.actorId, display_name: 'Synthetic user', login_name: 'vision.test', email: null, created_at: '2026-09-13T00:00:00Z', platform_role: 'USER', status: 'ACTIVE' }, 'synthetic-token-only-never-a-real-credential-0000000000'); }

test('normality model, inference asset and inference receipts validate without widening production authority', async () => {
  const model = await normalityModel('APPROVE_SANDBOX'), asset = await inferenceAsset(), inference = await normalityInference();
  assert.equal((await domain.validateVisionRecord(model, scope, 'model')).task_type, 'normality');
  assert.equal((await domain.validateVisionRecord(asset, scope, 'inference_asset')).status, 'FROZEN_LOCAL_INFERENCE_ASSET');
  const result = await domain.validateVisionRecord(inference, scope, 'inference');
  assert.equal(result.predicted_anomaly, true); assert.equal(result.gate_decision, 'NOT_ISSUED'); assert.equal(result.review_required, true);
  const first = await normalityModel(), secondSource = await normalityModel('APPROVE_SANDBOX');
  const second = await seal({ ...secondSource, resource_id: 'vision_model_approved_test', model_id: 'vision_model_approved_test' });
  const mixed = await list([first, second]);
  assert.equal((await domain.validateVisionList(mixed, scope, 'model', `"${mixed.receipt_sha256}"`, mixed.receipt_sha256)).length, 2);
});

test('rejecting a previously approved pack preserves historical sandbox binding but disables execution', async () => {
  const approved = await normalityModel('APPROVE_SANDBOX');
  const rejected = await seal({ ...approved, status: 'REJECT', usage_scope: 'RESEARCH_ONLY', sandbox_eligible: false });
  const value = await domain.validateVisionRecord(rejected, scope, 'model');
  assert.equal(value.status, 'REJECT'); assert.equal(value.sandbox_runtime_id, 'vision_runtime_test'); assert.equal(value.sandbox_eligible, false);
});

test('normality identity, thresholds, heatmap receipt and human-review boundary fail closed on tampering', async () => {
  const mutations = [
    value => { value.model_pack_sha256 = sha('0'); }, value => { value.model_pack_path = 'C:/private/model.pt'; },
  ];
  for (const change of mutations) { const value = await normalityModel('APPROVE_SANDBOX'); change(value); await assert.rejects(domain.validateVisionRecord(await seal(value), scope, 'model'), hold); }
  for (const change of [value => { value.predicted_anomaly = false; }, value => { value.heatmap.width = 0; }, value => { value.gate_decision = 'PASS'; }, value => { value.review_required = false; }, value => { value.decision_scope = 'PRODUCTION_DECISION'; }]) {
    const value = await normalityInference(); change(value); await assert.rejects(domain.validateVisionRecord(await seal(value), scope, 'inference'), hold);
  }
});

test('normality endpoints are explicit, locally validated and retain exact operation names for reconciliation', async () => {
  identity(); let calls = 0; globalThis.__visionTransport = () => { calls++; throw new Error('unexpected transport'); };
  const pack = await api.prepareVisionMutation(scope, 'register_normality_model_pack', registerNormalityPackRequest());
  assert.ok(pack.path.endsWith('/vision-model-packs')); assert.equal(pack.kind, 'model');
  const approve = await api.prepareVisionMutation(scope, 'approve_normality_model_pack:vision_normality_model_test', await approveNormalityPackRequest());
  assert.ok(approve.path.endsWith('/vision-models/vision_normality_model_test/sandbox-approval')); assert.equal(approve.targetId, 'vision_normality_model_test');
  const asset = await api.prepareVisionMutation(scope, 'register_inference_asset', registerInferenceAssetRequest());
  assert.ok(asset.path.endsWith('/vision-inference-assets')); assert.equal(asset.kind, 'inference_asset');
  const infer = await api.prepareVisionMutation(scope, 'run_normality_inference:vision_normality_model_test', await runNormalityInferenceRequest());
  assert.ok(infer.path.endsWith('/vision-models/vision_normality_model_test/inferences')); assert.equal(infer.kind, 'inference'); assert.equal(calls, 0);
  await assert.rejects(api.prepareVisionMutation(scope, 'register_inference_asset', { ...registerInferenceAssetRequest(), operator_attests_read_authorized: false }), { code: 'VISION_REQUEST_NOT_SENT' });
  await assert.rejects(api.prepareVisionMutation(scope, 'run_normality_inference:vision_normality_model_test', { ...await runNormalityInferenceRequest(), operator_attests_execution_authorized: false }), { code: 'VISION_REQUEST_NOT_SENT' });
  const receipt = await operation(infer.pending, await normalityInference());
  assert.equal((await domain.validateVisionOperationReceipt(receipt, scope, infer.pending, `"${receipt.receipt_sha256}"`, receipt.receipt_sha256)).resource.resource_id, 'vision_inference_test');
});

test('normality reads and writes bind server results to the selected model, asset and immutable digests', async () => {
  identity(); const model = await normalityModel('APPROVE_SANDBOX'), asset = await inferenceAsset(), inference = await normalityInference();
  const reads = [];
  globalThis.__visionTransport = path => { reads.push(path); if (path.endsWith('/vision-inference-assets')) return response({}); if (path.endsWith('/vision-inferences')) return response({}); throw new Error('unexpected'); };
  const assetsList = await list([asset]), inferenceList = await list([inference]); let call = 0;
  globalThis.__visionTransport = path => { reads.push(path); return response(call++ === 0 ? assetsList : inferenceList); };
  assert.equal((await api.listVisionInferenceAssets(scope))[0].asset_id, asset.asset_id);
  assert.equal((await api.listVisionInferences(scope))[0].inference_id, inference.inference_id);
  const prepared = await api.prepareVisionMutation(scope, 'run_normality_inference:vision_normality_model_test', await runNormalityInferenceRequest());
  globalThis.__visionTransport = () => response(inference);
  assert.equal((await api.sendVisionMutation(prepared)).image_score, 0.75);
  const changed = await seal({ ...inference, model_id: 'vision_model_other' }); globalThis.__visionTransport = () => response(changed);
  await assert.rejects(api.sendVisionMutation(prepared), hold);
  assert.ok(reads.some(path => path.endsWith('/vision-inference-assets'))); assert.ok(reads.some(path => path.endsWith('/vision-inferences')));
});

test('unknown inference reconciliation rejects a sealed receipt for a different model', async () => {
  const pending = { operation: 'run_normality_inference:vision_normality_model_test', requestKey: 'normality-unknown-reconcile' };
  const wrong = await seal({ ...await normalityInference(), model_id: 'vision_model_other' });
  const receipt = await operation(pending, wrong);
  await assert.rejects(domain.validateVisionOperationReceipt(receipt, scope, pending, `"${receipt.receipt_sha256}"`, receipt.receipt_sha256), hold);
});

test('normality feedback POST is explicit, scope bound, sealed and reconciles without replay', async () => {
  identity(); const inference = await normalityInference(), item = await normalityFeedback(inference);
  const input = { ...approval, expected_inference_sha256: inference.receipt_sha256, operator_attests_reviewed: true, classification: item.classification };
  const pending = { operation: `review_normality_inference:${inference.inference_id}`, requestKey: input.request_key };
  assert.equal((await domain.validateVisionRecord(item, scope, 'normality_feedback')).feedback_id, item.feedback_id);
  const prepared = await api.prepareVisionMutation(scope, pending.operation, input);
  assert.equal(prepared.path, `/v1/projects/${scope.projectId}/vision-inferences/${inference.inference_id}/feedback`);
  let posts = 0; globalThis.__visionTransport = (path, init) => { assert.equal(init.method, 'POST'); posts++; return response(item); };
  assert.equal((await api.sendVisionMutation(prepared)).inference_sha256, inference.receipt_sha256); assert.equal(posts, 1);
  const listValue = await seal({ schema_version: 'visiondata-gate.vision-list.v1', project_id: scope.projectId, inference_id: inference.inference_id, items: [item] });
  globalThis.__visionTransport = () => response(listValue);
  assert.equal((await api.getNormalityFeedback(scope, inference))[0].feedback_id, item.feedback_id);
  const reconciled = await operation(pending, item); globalThis.__visionTransport = () => response(reconciled);
  assert.equal((await api.getVisionOperation(scope, pending)).resource.feedback_id, item.feedback_id); assert.equal(posts, 1);
  for (const patch of [{ production_release_allowed: true }, { training_ingestion_allowed: true }, { issue_closed: true }, { followup_work_item_created: true }, { followup_work_item_type: 'LABEL_TRUTH' }]) {
    await assert.rejects(domain.validateVisionRecord(await seal({ ...item, ...patch }), scope, 'normality_feedback'), hold);
  }
  const wrong = await seal({ ...item, inference_sha256: sha('0') }); globalThis.__visionTransport = () => response(wrong);
  await assert.rejects(api.sendVisionMutation(prepared), hold);
  const awaitedWrongList = await seal({ ...listValue, items: [wrong] });
  globalThis.__visionTransport = () => response(awaitedWrongList);
  await assert.rejects(api.getNormalityFeedback(scope, inference), hold);
  await assert.rejects(api.prepareVisionMutation(scope, pending.operation, { ...input, operator_attests_reviewed: false }), { code: 'VISION_REQUEST_NOT_SENT' });
});

test('heatmap GET verifies actual PNG bytes, headers, dimensions and cancelled reads before handing out a blob', async () => {
  identity(); const inference = await previewInference(), bytes = Buffer.from(normalityPngBase64, 'base64');
  const headers = { 'Content-Type': 'image/png', 'Content-Length': String(bytes.length), ETag: `"${inference.heatmap.sha256}"`, 'X-Content-SHA256': inference.heatmap.sha256 };
  const calls = []; globalThis.__visionTransport = (path, init) => { calls.push({ path, init }); return new Response(bytes, { headers }); };
  assert.equal(typeof api.getVisionHeatmap, 'function');
  const blob = await api.getVisionHeatmap(scope, inference); assert.equal(blob.type, 'image/png'); assert.equal(blob.size, bytes.length);
  assert.equal(calls[0].path, `/v1/projects/${scope.projectId}/vision-inferences/${inference.inference_id}/heatmap`); assert.equal(calls[0].init.headers.Accept, 'image/png');
  for (const altered of [{ ETag: `W/"${inference.heatmap.sha256}"` }, { 'Content-Type': 'image/svg+xml' }, { 'X-Content-SHA256': sha('0') }, { 'Content-Length': '999' }]) {
    globalThis.__visionTransport = () => new Response(bytes, { headers: { ...headers, ...altered } }); await assert.rejects(api.getVisionHeatmap(scope, inference), hold);
  }
  const bad = Buffer.from(bytes); bad[bad.length - 1] ^= 1;
  globalThis.__visionTransport = () => new Response(bad, { headers }); await assert.rejects(api.getVisionHeatmap(scope, inference), hold);
  const controller = new AbortController(); let release;
  globalThis.__visionTransport = () => new Promise(resolve => { release = resolve; });
  const late = api.getVisionHeatmap(scope, inference, controller.signal); controller.abort(); release(new Response(bytes, { headers }));
  await assert.rejects(late);
});

test('global capabilities distinguish Normality-only episodic TTT from disabled detect adaptation', async () => {
  const value = await seal({ ...await capabilities(), ttt_status: 'NORMALITY_EPISODIC_AVAILABLE', ttt_scope: 'NORMALITY_ONLY_EPISODIC_NO_PERSISTENCE' });
  assert.equal((await domain.validateVisionCapabilities(value, scope, `"${value.receipt_sha256}"`, value.receipt_sha256)).ttt_status, 'NORMALITY_EPISODIC_AVAILABLE');
  const wrong = await seal({ ...value, ttt_scope: 'ALL_MODELS_AUTOMATIC' });
  await assert.rejects(domain.validateVisionCapabilities(wrong, scope, `"${wrong.receipt_sha256}"`, wrong.receipt_sha256), hold);
});
test('TTT requires independent bounded authorization, disjoint hashes and both human guard classes before sending', async () => {
  identity(); const input = await tttRequest(), operation = 'run_normality_ttt:vision_normality_model_test';
  const prepared = await api.prepareVisionMutation(scope, operation, input); assert.ok(prepared.path.endsWith('/vision-models/vision_normality_model_test/ttt-inferences'));
  for (const changed of [{ operator_attests_ttt_authorized: false }, { budget: { ...input.budget, steps: 9 } }, { budget: { ...input.budget, max_seconds: 121 } },
    { replay_assets: [{ ...input.replay_assets[0], expected_image_sha256: input.expected_image_sha256 }] }, { guard_assets: input.guard_assets.map(item => ({ ...item, reference_label: 'normal' })) }]) {
    await assert.rejects(api.prepareVisionMutation(scope, operation, { ...input, ...changed }), { code: 'VISION_REQUEST_NOT_SENT' });
  }
});
test('TTT capabilities, measured accepted/rollback reports and explicit unmeasured failures preserve all boundaries', async () => {
  identity(); const cap = await tttCapabilities(); globalThis.__visionTransport = () => response(cap); assert.equal((await api.getVisionTttCapabilities(scope)).max_steps, 8);
  for (const status of ['ACCEPTED_EPISODIC', 'ROLLED_BACK']) {
    const value = await tttInference(status); assert.equal((await domain.validateVisionRecord(value, scope, 'inference')).ttt.status, status);
    for (const changed of [{ persistent_learning: true }, { parent_pack_unchanged: false }, { effective_parameter_sha256: sha('0') }, { backbone_sha256_after: sha('0') }]) {
      await assert.rejects(domain.validateVisionRecord(await seal({ ...value, ttt: { ...value.ttt, ...changed } }), scope, 'inference'), hold);
    }
  }
  const input = await tttRequest(), prepared = await api.prepareVisionMutation(scope, 'run_normality_ttt:vision_normality_model_test', input), failure = await tttFailure();
  globalThis.__visionTransport = () => response(failure); assert.equal((await api.sendVisionMutation(prepared)).measurements_available, false);
  const receipt = await operation(prepared.pending, failure); globalThis.__visionTransport = () => response(receipt);
  assert.equal((await api.getVisionOperation(scope, prepared.pending)).resource.status, 'FAILED_CLOSED');
  const wrong = await seal({ ...failure, image_score: 0 }); await assert.rejects(domain.validateVisionRecord(wrong, scope, 'ttt_failure'), hold);
  await assert.rejects(domain.validateVisionRecord(await seal({ ...failure, failure_code: 'TTT_UNRECOGNIZED' }), scope, 'ttt_failure'), hold);
});
test('TTT guard policy and industrial boundary cannot be weakened in capabilities or measured reports', async () => {
  const cap = await tttCapabilities(), value = await tttInference();
  const wrongCap = await seal({ ...cap, guard_policy: { min_true_positive: 0, min_true_negative: 1, max_fp_increase: 0, max_fn_increase: 0 } });
  await assert.rejects(domain.validateVisionTttCapabilities(wrongCap, scope, `"${wrongCap.receipt_sha256}"`, wrongCap.receipt_sha256), hold);
  const wrong = await seal({ ...value, ttt: { ...value.ttt, guard_policy: { min_true_positive: 1, min_true_negative: 1, max_fp_increase: 1, max_fn_increase: 0 } } });
  await assert.rejects(domain.validateVisionRecord(wrong, scope, 'inference'), hold);
});

test('accepted TTT receipt cannot claim a performed step with missing gradients', async () => {
  const value = await tttInference();
  for (const update of [curve => { curve[0].gradient_norm = 0; }]) {
    const ttt = structuredClone(value.ttt); update(ttt.loss_curve);
    await assert.rejects(domain.validateVisionRecord(await seal({ ...value, ttt }), scope, 'inference'), hold);
  }
});

test('accepted TTT requires a separately measured post-update objective, not the last pre-update loss', async () => {
  const value = await tttInference();
  const bad = await seal({ ...value, ttt: { ...value.ttt, objective_before: 2, objective_after: 3 } });
  await assert.rejects(domain.validateVisionRecord(bad, scope, 'inference'), hold);
  const good = await seal({ ...value, ttt: { ...value.ttt, objective_before: 2, objective_after: 1, loss_curve: value.ttt.loss_curve.map((row, index) => ({ ...row, loss: index === 1 ? 3 : 2 })) } });
  assert.equal((await domain.validateVisionRecord(good, scope, 'inference')).ttt.objective_after, 1);
  for (const patch of [{ objective_before: null, objective_after: 1 }, { objective_before: 2, objective_after: null }, { objective_before: 3, objective_after: 1 }]) {
    await assert.rejects(domain.validateVisionRecord(await seal({ ...value, ttt: { ...value.ttt, ...patch } }), scope, 'inference'), hold);
  }
});
test('rolled-back TTT preserves null post-update objective when not measured and never fabricates zero-step measurements', async () => {
  const value = await tttInference('ROLLED_BACK');
  const partial = await seal({ ...value, ttt: { ...value.ttt, objective_before: 2, objective_after: null } });
  assert.equal((await domain.validateVisionRecord(partial, scope, 'inference')).ttt.objective_after, null);
  const zeroTtt = { ...value.ttt, steps_completed: 0, loss_curve: [], objective_before: null, objective_after: null };
  assert.equal((await domain.validateVisionRecord(await seal({ ...value, ttt: zeroTtt }), scope, 'inference')).ttt.steps_completed, 0);
  await assert.rejects(domain.validateVisionRecord(await seal({ ...value, ttt: { ...zeroTtt, objective_before: 0 } }), scope, 'inference'), hold);
});
test('normality followup imports and real work-order bindings require exact lineage and independent non-label authority', async () => {
  identity(); const imported = await normalityFollowupImport(), order = await normalityFollowupWorkOrder(imported);
  for (const [operation, input, value, suffix] of [[`import_normality_followup:${imported.feedback_id}`, await followupRequest(), imported, 'followup-import'], [`create_normality_followup_work_order:${imported.feedback_id}`, await followupRequest(true), order, 'followup-work-orders']]) {
    const prepared = await api.prepareVisionMutation(scope, operation, input); assert.ok(prepared.path.endsWith(`/normality-feedback/${imported.feedback_id}/${suffix}`));
    globalThis.__visionTransport = () => response(value); assert.equal((await api.sendVisionMutation(prepared)).resource_id, value.resource_id);
    const ledger = await operationFixture(prepared.pending, value); let path; globalThis.__visionTransport = p => { path = p; return response(ledger); };
    assert.equal((await api.getVisionOperation(scope, prepared.pending)).resource.resource_id, value.resource_id); assert.ok(path.includes('/normality-followup-operations/'));
    await assert.rejects(api.prepareVisionMutation(scope, operation, { ...input, operator_attests_no_label_or_training_authority: false }), { code: 'VISION_REQUEST_NOT_SENT' });
    await assert.rejects(domain.validateVisionRecord(await seal({ ...value, annotation_created: true }), scope), hold);
    await assert.rejects(domain.validateVisionRecord(await seal({ ...value, workspace_id: 'workspace_other' }), scope), hold);
  }
});
const operationFixture = operation;
test('followup GET projections bind the current actor, registry lineage and genuine saved annotation revision', async () => {
  identity(); const imported = await normalityFollowupImport(), feedback = await normalityFeedback(await previewInference()), order = await normalityFollowupWorkOrder(imported);
  const gates = { issue_closed: false, label_truth_authority: false, training_ingestion_allowed: false, production_release_allowed: false, machine_write_permitted: false, annotation_created: false };
  const value = await seal({ schema_version: 'visiondata-gate.normality-followup-list.v1', project_id: scope.projectId, feedback_id: feedback.feedback_id, imports: [imported], work_orders: [order], ...gates });
  globalThis.__visionTransport = () => response(value); assert.equal((await api.getNormalityFollowup(scope, feedback)).work_orders[0].work_order_id, order.work_order_id);
  const state = await seal({ schema_version: 'visiondata-gate.normality-followup-annotations.v1', project_id: scope.projectId, workspace_id: scope.workspaceId, feedback_id: feedback.feedback_id, import_id: imported.import_id,
    operator_asset_id: imported.operator_asset_id, asset_sha256: imported.image_sha256, revision: 1, document_sha256: sha('1'), annotations: [{ annotation_id: 'manual_box_1', label: 'Human selected region', x: .1, y: .1, width: .2, height: .2, source: 'MANUAL' }], ...gates });
  globalThis.__visionTransport = () => response(state); assert.equal((await api.getNormalityFollowupAnnotations(scope, imported)).annotations.length, 1);
  for (const patch of [{ asset_sha256: sha('0') }, { workspace_id: 'wrong_workspace' }, { import_id: 'wrong_import' }, { label_truth_authority: true }, { annotation_created: true }]) {
    globalThis.__visionTransport = async () => response(await seal({ ...state, ...patch })); await assert.rejects(api.getNormalityFollowupAnnotations(scope, imported), hold);
  }
  const wrongImport = await seal({ ...imported, created_by: 'other_actor' });
  globalThis.__visionTransport = async () => response(await seal({ ...value, imports: [wrongImport] })); await assert.rejects(api.getNormalityFollowup(scope, feedback), hold);
  const wrongOrder = await seal({ ...order, import_sha256: sha('0') });
  globalThis.__visionTransport = async () => response(await seal({ ...value, work_orders: [wrongOrder] })); await assert.rejects(api.getNormalityFollowup(scope, feedback), hold);
});
test('legacy failed runtime probe remains readable without invented metadata or execution authority', async () => {
  const value = await seal({ ...await runtime(), status: 'UNAVAILABLE', probe: { status: 'failed', error_code: 'YOLO_CHILD_EXECUTION_FAILED', error_type: 'ModuleNotFoundError' } });
  const actual = await domain.validateVisionRecord(value, scope, 'runtime'); assert.equal(actual.probe.status, 'failed'); assert.equal(actual.probe.python_version, undefined); assert.equal(actual.probe.import_status, undefined);
  for (const change of [v => { v.status = 'PROBED'; }, v => { v.probe.error_code = 'C:/private/dependency'; }, v => { v.probe.error_type = 'ModuleNotFoundError: C:/private/path'; }, v => { v.probe.import_status = 'PASSED'; }]) {
    const copy = structuredClone(value); change(copy); await assert.rejects(domain.validateVisionRecord(await seal(copy), scope, 'runtime'), hold);
  }
});
