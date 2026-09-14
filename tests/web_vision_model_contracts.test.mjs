import assert from 'node:assert/strict';
import test from 'node:test';
import { registerHooks } from 'node:module';
import * as domain from '../web/src/visionModelDomain.ts';
import { scope, sha, seal, model, runtime, dataset, run, manifest, capabilities, list, operation, response, createRequest, approval, digest, poolProjection, poolDataset, feedbackFixture } from './web_vision_model_fixtures.mjs';
import { setIdentitySession, clearIdentitySession } from '../web/src/identitySession.ts';
const stub = 'data:text/javascript,' + encodeURIComponent(`export class OperatorApiError extends Error { constructor(code,message,status){super(message);this.code=code;this.status=status;} } export function operatorFetch(...args){return globalThis.__visionTransport(...args);}`);
const hooks = registerHooks({ resolve(specifier, context, next) { if ((context.parentURL?.endsWith('/data/visionModelApi.ts') || context.parentURL?.endsWith('/data/dataPoolApi.ts')) && specifier === './api') return { url: stub, shortCircuit: true }; return next(specifier, context); } });
const api = await import('../web/src/data/visionModelApi.ts'); hooks.deregister();
function identity(id = scope.actorId) { setIdentitySession({ user_id: id, display_name: 'Synthetic user', login_name: 'vision.test', email: null, created_at: '2026-09-13T00:00:00Z', platform_role: 'USER', status: 'ACTIVE' }, 'synthetic-token-only-never-a-real-credential-0000000000'); }
const hold = { code: 'VISION_CONTRACT_HOLD' };

test('all actual resource schemas validate with JCS, strong ETag and content SHA', async () => {
  for (const [kind, make] of Object.entries({ model, runtime, dataset, run })) { const value = await make();
    assert.equal((await domain.validateVisionRecord(value, scope, kind, value.resource_id, `"${value.receipt_sha256}"`, value.receipt_sha256)).resource_id, value.resource_id);
    for (const etag of [null, '', value.receipt_sha256, `W/"${value.receipt_sha256}"`, `"${sha('f')}"`]) await assert.rejects(domain.validateVisionRecord(value, scope, kind, undefined, etag, value.receipt_sha256), hold);
    await assert.rejects(domain.validateVisionRecord(value, scope, kind, undefined, `"${value.receipt_sha256}"`, null), hold);
    await assert.rejects(domain.validateVisionRecord({ ...value, created_by: 'different' }, scope, kind), hold);
  }
});
test('project mismatch, authority widening, wrong kind and private path fields fail closed', async () => {
  for (const change of [{ project_id: 'project_other' }, { production_release_allowed: true }, { machine_write_permitted: true }, { weights_path: 'C:/private/user.pt' }])
    await assert.rejects(domain.validateVisionRecord(await seal({ ...await model(), ...change }), scope, 'model'), hold);
  await assert.rejects(domain.validateVisionRecord(await model(), scope, 'run'), hold);
  await assert.rejects(domain.validateVisionRecord(await model(), scope, 'model', 'vision_model_other'), hold);
});
test('list seal, nested seals, duplicate resource IDs and project ownership are all checked', async () => {
  const item = await model(); const value = await list([item]);
  assert.equal((await domain.validateVisionList(value, scope, 'model', `"${value.receipt_sha256}"`, value.receipt_sha256)).length, 1);
  for (const altered of [await list([item, item]), await list([{ ...item, display_name: 'tampered' }]), await list([await seal({ ...item, project_id: 'another' })])])
    await assert.rejects(domain.validateVisionList(altered, scope, 'model', `"${altered.receipt_sha256}"`, altered.receipt_sha256), hold);
});
test('dataset derived ID is excluded only from its nested digest; split counts and pixels stay bound', async () => {
  const value = await dataset(); assert.equal((await domain.validateVisionRecord(value, scope, 'dataset')).dataset_id, value.dataset_id);
  for (const mutate of [d => { d.dataset_id = 'detds_wrong'; }, d => { d.split_counts.train = 4; }, d => { d.samples[1].pixel_sha256 = d.samples[0].pixel_sha256; }]) {
    const record = await dataset(); mutate(record.dataset_receipt); record.dataset_receipt = await seal(record.dataset_receipt, ['dataset_id']); record.dataset_receipt_sha256 = record.dataset_receipt.receipt_sha256;
    await assert.rejects(domain.validateVisionRecord(await seal(record), scope, 'dataset'), hold);
  }
});
test('manifest needs explicit boxes, true review and fixed three-way split; comments are not ground truth', async () => {
  assert.equal((await domain.parseDetectionManifest(JSON.stringify(manifest()))).manifest.samples.length, 3);
  const mutations = [m => { m.samples[1].split = 'train'; }, m => { m.samples[1].group_id = m.samples[0].group_id; }, m => { m.samples[1].image_sha256 = m.samples[0].image_sha256; },
    m => { m.samples[0].reviewed = false; }, m => { m.samples[0].boxes = []; }, m => { m.samples[0].boxes[0].class_id = 1; }, m => { m.samples[0].boxes[0].x_center = .01; },
    m => { m.samples[0].category = 'defect'; delete m.samples[0].boxes; }, m => { m.samples[0].image_path = '../private.png'; }, m => { m.samples[0].image_path = 'C:/private.png'; }];
  for (const change of mutations) { const value = manifest(); change(value); await assert.rejects(domain.parseDetectionManifest(JSON.stringify(value)), hold); }
  const normal = manifest(); normal.samples[0].boxes = []; normal.samples[0].normal_attested = true; assert.equal((await domain.parseDetectionManifest(JSON.stringify(normal))).manifest.samples[0].normal_attested, true);
});
test('candidate success with zero metrics is valid but missing checkpoint or production/test claims are rejected', async () => {
  const value = await run(); assert.equal((await domain.validateVisionRecord(value, scope, 'run')).result.candidate['metrics/mAP50-95(B)'], 0);
  assert.match(domain.visionStatusLabel('SUCCEEDED_CANDIDATE'), /未达标判定/);
  for (const change of [r => { delete r.result.checkpoint; }, r => { r.result.test_evaluation = 'PASSED'; }, r => { r.result.production_approved = true; }, r => { r.pretrained_claimed = true; }, r => { r.adaptation = 'TTT'; }, r => { r.device = 'cuda'; }]) {
    const bad = await run(); change(bad); await assert.rejects(domain.validateVisionRecord(await seal(bad), scope, 'run'), hold);
  }
});
test('all bounded training parameters, weights trust and separate pickle authority are enforced before transport', async () => {
  identity(); let calls = 0; globalThis.__visionTransport = () => { calls++; throw new Error('unexpected transport'); };
  const request = await createRequest(); const valid = await api.prepareVisionMutation(scope, 'create_training_run', request); assert.equal(valid.kind, 'run'); assert.equal(calls, 0);
  for (const mutation of [r => { r.training.epochs = 6; }, r => { r.training.imgsz = 65; }, r => { r.training.threads = 5; }, r => { r.training.max_seconds = 601; }, r => { r.training.batch = 0; },
    r => { r.adaptation = 'TTT'; }, r => { r.ultralytics_license_acknowledged = false; }, r => { r.operator_attests_training_authorized = false; },
    r => { r.initial_model_id = 'vision_model_test'; }, r => { r.initialization = 'REGISTERED_WEIGHTS'; r.initial_model_id = 'vision_model_test'; r.expected_weights_sha256 = sha(); r.operator_attests_trusted_weights = true; }]) {
    const bad = structuredClone(request); mutation(bad); await assert.rejects(api.prepareVisionMutation(scope, 'create_training_run', bad), { code: 'VISION_REQUEST_NOT_SENT' });
  }
  assert.equal(calls, 0);
});
test('dataset request hashes original JSON object without silently adding defaults', async () => {
  identity(); const input = manifest(); delete input.samples[0].normal_attested;
  const request = { ...approval, source_root: 'C:/synthetic-fixtures', manifest: input, expected_manifest_sha256: await digest(input), operator_attests_data_authorized: true };
  const prepared = await api.prepareVisionMutation(scope, 'register_dataset', request);
  assert.equal(Object.hasOwn(JSON.parse(prepared.body).manifest.samples[0], 'normal_attested'), false);
  await assert.rejects(api.prepareVisionMutation(scope, 'register_dataset', { ...request, expected_manifest_sha256: sha() }), { code: 'VISION_REQUEST_NOT_SENT' });
});
test('local path registration rejects remote/UNC path and unsigned authorization', async () => {
  identity(); const request = { ...approval, display_name: 'Local weights', weights_path: 'C:/synthetic/model.pt', expected_weights_sha256: sha(), task_type: 'detect', license_id: 'AGPL-3.0', source_description: 'Synthetic source', operator_attests_read_authorized: true };
  await api.prepareVisionMutation(scope, 'register_model', request);
  for (const weights_path of ['https://example.test/model.pt', '//host/share/model.pt', '\\\\host\\share\\model.pt', 'relative/model.pt'])
    await assert.rejects(api.prepareVisionMutation(scope, 'register_model', { ...request, weights_path }), { code: 'VISION_REQUEST_NOT_SENT' });
  await assert.rejects(api.prepareVisionMutation(scope, 'register_model', { ...request, operator_attests_read_authorized: false }), { code: 'VISION_REQUEST_NOT_SENT' });
});
test('actual operation names are URL encoded and GET reconciliation cannot replay POST', async () => {
  identity(); const pending = { operation: 'cancel:vision_run_test', requestKey: 'vision_unknown_request_1234' }; const resource = await run('RUNNING'); const calls = [];
  globalThis.__visionTransport = (path, init) => { calls.push({ path, init }); return responseValue; }; const responseValue = response(await operation(pending, resource));
  assert.equal((await api.getVisionOperation(scope, pending)).auto_replayed, false);
  assert.equal(calls[0].path, `/v1/projects/${scope.projectId}/vision-operations/cancel%3Avision_run_test/${pending.requestKey}`);
  assert.equal(calls[0].init, undefined);
  const wrong = await operation({ ...pending, requestKey: 'different_request_key' }, resource);
  await assert.rejects(domain.validateVisionOperationReceipt(wrong, scope, pending, `"${wrong.receipt_sha256}"`, wrong.receipt_sha256), hold);
});
test('metadata-only lock is actor/workspace/project scoped and forbids payload or credential fields', () => {
  const key = domain.visionPendingStorageKey(scope); assert.match(key, new RegExp(`${scope.actorId}:${scope.workspaceId}:${scope.projectId}$`));
  assert.notEqual(key, domain.visionPendingStorageKey({ ...scope, actorId: 'usr_other' }));
  assert.deepEqual(domain.parseVisionPending(JSON.stringify({ operation: 'register_model', requestKey: 'vision_unknown_request_1234' })), { operation: 'register_model', requestKey: 'vision_unknown_request_1234' });
  for (const extra of [{ weights_path: 'C:/secret.pt' }, { note: 'private text' }, { access_token: 'secret' }]) assert.throws(() => domain.parseVisionPending(JSON.stringify({ operation: 'register_model', requestKey: 'vision_unknown_request_1234', ...extra })), hold);
});
test('API refuses missing actor and detects identity changes across async dispatch', async () => {
  clearIdentitySession(); await assert.rejects(api.prepareVisionMutation(scope, 'create_training_run', await createRequest()), { code: 'VISION_REQUEST_NOT_SENT' });
  identity(); globalThis.__visionTransport = async () => { identity('usr_other'); return response(await capabilities()); };
  await assert.rejects(api.getVisionCapabilities(scope), hold); identity();
});
test('POST binds response to authorization SHA and never retries malformed success receipts', async () => {
  identity(); const input = await createRequest(); const prepared = await api.prepareVisionMutation(scope, 'create_training_run', input); let calls = 0;
  globalThis.__visionTransport = async () => { calls++; return response(await run('QUEUED')); };
  assert.equal((await api.sendVisionMutation(prepared)).status, 'QUEUED');
  globalThis.__visionTransport = async () => { calls++; return response(await seal({ ...await run('QUEUED'), authorization_sha256: sha('f') })); };
  let caught; try { await api.sendVisionMutation(prepared); } catch (error) { caught = error; }
  assert.equal(caught.code, 'VISION_CONTRACT_HOLD'); assert.equal(api.visionWriteKnownRejected(caught), false); assert.equal(calls, 2);
  assert.equal(api.visionErrorMessage(new Error('C:/private/weights.pt raw traceback')).includes('C:/private'), false);
});
test('pool bridge uses current signed version and exact class/group/normal bindings without source paths', async () => {
  identity(); const projection = await poolProjection(), record = await poolDataset();
  globalThis.__visionTransport = () => response(projection);
  assert.equal((await api.getVisionPool(scope, 'pool_test', 'poolv_test')).current_version.version_id, 'poolv_test');
  await assert.rejects(api.getVisionPool(scope, 'pool_test', 'poolv_old'), hold);
  assert.equal((await domain.validateVisionRecord(record, scope, 'dataset')).pool_binding.pool_id, 'pool_test');
  const request = { ...approval, pool_id: 'pool_test', version_id: 'poolv_test', expected_pool_receipt_sha256: projection.pool.receipt_sha256, expected_version_receipt_sha256: projection.current_version.receipt_sha256,
    class_names: ['defect'], groups: record.pool_binding.groups, normal_sample_ids: [], operator_attests_data_authorized: true };
  const prepared = await api.prepareVisionMutation(scope, 'register_pool_dataset', request);
  assert.equal(prepared.path, `/v1/projects/${scope.projectId}/vision-datasets/from-data-pool`); assert.equal(prepared.body.includes('source_root'), false);
  globalThis.__visionTransport = () => response(record); assert.equal((await api.sendVisionMutation(prepared)).dataset_id, record.dataset_id);
  for (const change of [b => { b.coordinate_frame.mask_conversion = true; }, b => { b.groups.train_sample = 'changed'; }, b => { b.normal_sample_ids = ['train_sample']; }, b => { b.detection_manifest_sha256 = sha(); }]) {
    const bad = await poolDataset(); change(bad.pool_binding); bad.pool_binding = await seal(bad.pool_binding);
    await assert.rejects(domain.validateVisionRecord(await seal(bad), scope, 'dataset'), hold);
  }
});
test('validation feedback binds val member, checkpoint, fixed protocol and sealed detail without judging labels', async () => {
  identity(); const fixture = await feedbackFixture(); globalThis.__visionTransport = () => response(fixture.list);
  const [item] = await api.getVisionFeedback(scope, fixture.run); assert.equal(item.detail.fn, 1); assert.equal(item.label_truth_authority, false); assert.equal(item.issue_closed, false);
  for (const change of [v => { v.split = 'train'; }, v => { v.issue_closed = true; }, v => { v.classification = 'LABEL_ERROR'; }, v => { v.detail.fn = 2; }, v => { v.training_ingestion_allowed = true; }]) {
    const bad = structuredClone(item); change(bad); await assert.rejects(domain.validateVisionRecord(await seal(bad), scope, 'feedback'), hold);
  }
  const wrongRun = { ...fixture.run, result: { ...fixture.run.result, validation_feedback_protocol: { ...fixture.run.result.validation_feedback_protocol, confidence_threshold: .5 } } };
  await assert.rejects(domain.validateVisionFeedbackList(fixture.list, scope, wrongRun, `"${fixture.list.receipt_sha256}"`, fixture.list.receipt_sha256), hold);
});
test('triage uses feedback resource ID in operation ledger but run ID only in route context', async () => {
  identity(); const fixture = await feedbackFixture(); const request = { ...approval, expected_run_sha256: fixture.run.receipt_sha256, expected_feedback_sha256: fixture.feedback.receipt_sha256, operator_attests_reviewed: true, classification: 'HARD_SAMPLE' };
  const name = `triage_feedback:${fixture.feedback.feedback_id}`;
  await assert.rejects(api.prepareVisionMutation(scope, name, request), { code: 'VISION_REQUEST_NOT_SENT' });
  const prepared = await api.prepareVisionMutation(scope, name, request, { runId: fixture.run.run_id });
  assert.ok(prepared.path.endsWith(`/vision-training-runs/${fixture.run.run_id}/feedback/${fixture.feedback.feedback_id}/triage`));
  assert.equal(Object.hasOwn(JSON.parse(prepared.body), 'run_id'), false);
  const triaged = await seal({ ...fixture.feedback, status: 'TRIAGED_FOR_REVIEW', classification: 'HARD_SAMPLE' }); globalThis.__visionTransport = () => response(triaged);
  assert.equal((await api.sendVisionMutation(prepared)).classification, 'HARD_SAMPLE');
  const op = await operation(prepared.pending, triaged); assert.equal((await domain.validateVisionOperationReceipt(op, scope, prepared.pending, `"${op.receipt_sha256}"`, op.receipt_sha256)).resource.feedback_id, triaged.feedback_id);
});
test('next training feedback IDs require exact receipts and empty defaults are canonicalized explicitly', async () => {
  identity(); const request = await createRequest(), fixture = await feedbackFixture();
  assert.deepEqual(request.responds_to_feedback_ids, []); assert.deepEqual(request.expected_feedback_receipts, {});
  const related = { ...request, responds_to_feedback_ids: [fixture.feedback.feedback_id], expected_feedback_receipts: { [fixture.feedback.feedback_id]: fixture.feedback.receipt_sha256 } };
  assert.equal((await api.prepareVisionMutation(scope, 'create_training_run', related)).kind, 'run');
  await assert.rejects(api.prepareVisionMutation(scope, 'create_training_run', { ...related, expected_feedback_receipts: {} }), { code: 'VISION_REQUEST_NOT_SENT' });
  await assert.rejects(api.prepareVisionMutation(scope, 'create_training_run', { ...related, responds_to_feedback_ids: [...related.responds_to_feedback_ids, ...related.responds_to_feedback_ids] }), { code: 'VISION_REQUEST_NOT_SENT' });
});
