import assert from 'node:assert/strict';
import test from 'node:test';
import { registerHooks } from 'node:module';
import * as domain from '../web/src/visionModelDomain.ts';
import { setIdentitySession } from '../web/src/identitySession.ts';
import { scope, sha, seal, list, operation, response, normalityModel, inferenceAsset, normalityInference,
  registerNormalityPackRequest, approveNormalityPackRequest, registerInferenceAssetRequest, runNormalityInferenceRequest } from './web_vision_model_fixtures.mjs';

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
