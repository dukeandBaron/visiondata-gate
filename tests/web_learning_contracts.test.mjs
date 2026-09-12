import test from 'node:test';
import assert from 'node:assert/strict';
import { existsSync } from 'node:fs';
import { registerHooks } from 'node:module';
import { canonicalizeJcs, sha256HexUtf8 } from '../web/src/data/jcs.ts';

// Synthetic contract fixtures only: no training, network, or database access.
const domain = existsSync(new URL('../web/src/learningDomain.ts', import.meta.url))
  ? await import('../web/src/learningDomain.ts') : {};
// Intercept only the transport import: never import api.ts or initialize browser runtime in Node.
const transportStub = 'data:text/javascript,' + encodeURIComponent(`
  export class OperatorApiError extends Error {
    constructor(code, message, status) { super(message); this.code = code; this.status = status; }
  }
  export function operatorFetch(...args) { return globalThis.__learningContractTransport(...args); }
`);
const hooks = registerHooks({ resolve(specifier, context, nextResolve) {
  if (context.parentURL?.endsWith('/data/learningApi.ts') && ['./api', './api.ts'].includes(specifier)) return { url: transportStub, shortCircuit: true };
  return nextResolve(specifier, context);
} });
const api = existsSync(new URL('../web/src/data/learningApi.ts', import.meta.url)) ? await import('../web/src/data/learningApi.ts') : {};
hooks.deregister();
const scope = { workspaceId: 'workspace_a', projectId: 'project_a' };
const sha = (letter = 'a') => letter.repeat(64);
const digest = value => sha256HexUtf8(canonicalizeJcs(value));
const sealed = async value => {
  const body = { ...value }; delete body.receipt_sha256;
  return { ...body, receipt_sha256: await digest(body) };
};
function validator(name) {
  assert.equal(typeof domain[name], 'function', `${name} must implement the learning contract`);
  return domain[name];
}
const hold = { code: 'LEARNING_CONTRACT_HOLD' };
const notSent = { code: 'LEARNING_REQUEST_NOT_SENT', status: 422 };
const training = { epochs: 2, learning_rate: 0.5, l2: 0, max_wall_seconds: 20, seed: 0 };
const policy = { threshold: 0.5, max_false_negative_rate: 0.2, max_false_positive_rate: 0.2, min_dice: 0.7, min_dice_gain: 0.001, max_category_dice_regression: 0, max_p95_latency_ms: 1000 };
const authorization = { request_key: 'fixture_key_12345', review_note: 'Synthetic reviewed fixture', expected_preflight_sha256: sha(), groups: { train_1: 'group_train', val_1: 'group_val', test_1: 'group_test' }, operator_attests_training_authorized: true };
const request = { ...authorization, training, evaluation: policy, max_rounds: 3, max_total_epochs: 500, max_total_wall_seconds: 120 };
const binding = { task_id: 'task_a', workspace_id: scope.workspaceId, project_id: scope.projectId, source_id: 'source_a', snapshot_id: 'snapshot_a', snapshot_receipt_sha256: sha(), acceptance_requirements_sha256: sha(), batch_manifest_sha256: sha(), batch_contract_sha256: sha(), batch_digest_sha256: sha(), gate_result_sha256: sha(), sample_count: 3, intended_use: 'Synthetic contract verification' };
async function dataset() {
  const samples = ['train', 'val', 'test'].map((split, index) => ({ sample_id: `${split}_1`, split, category: 'part', group_id: `group_${split}`, image_path: `images/000${index}.image`, mask_path: `masks/000${index}.mask`, image_sha256: sha(), mask_sha256: sha(), pixel_sha256: sha(['a', 'b', 'c'][index]), mask_pixel_sha256: sha(), width: 2, height: 2 }));
  const split_fingerprints = {};
  for (const sample of samples) split_fingerprints[sample.split] = await digest([{ group_id: sample.group_id, category: sample.category, pixel_sha256: sample.pixel_sha256, mask_pixel_sha256: sample.mask_pixel_sha256 }]);
  const body = { schema_version: 'visiondata-gate.learning-dataset.v1', binding: { ...binding }, samples, split_fingerprints, labels_sha256: await digest(samples.map(({ sample_id, mask_sha256, mask_pixel_sha256 }) => ({ sample_id, mask_sha256, mask_pixel_sha256 }))) };
  const receipt_sha256 = await digest(body);
  return { ...body, dataset_id: `dataset_${receipt_sha256.slice(0, 24)}`, receipt_sha256 };
}
async function cycle() {
  const data = await dataset();
  return sealed({ schema_version: 'visiondata-gate.learning-cycle.v1', cycle_id: 'cycle_a', project_id: scope.projectId, workspace_id: scope.workspaceId, created_by: 'reviewer', created_at: '2026-09-12T12:00:00.000+00:00', updated_at: '2026-09-12T12:00:00.000+00:00', revision: 0, status: 'READY', request, dataset: data, dataset_storage_key: 'dataset_storage_a', evaluation_fingerprints: { val: data.split_fingerprints.val, test: data.split_fingerprints.test }, initial_model_id: 'model_initial', champion_model_id: 'model_initial', approved_model_ids: ['model_initial'], round_ids: [], epochs_reserved: 0, wall_seconds_reserved: 0, events: [], production_release_allowed: false, machine_write_permitted: false, remote_execution_verified: false, scope: 'LOCAL_SUPERVISED_REFERENCE_MODEL_SANDBOX' });
}
function metrics(tp, fp, tn, fn) {
  return { tp, fp, tn, fn, dice: 2 * tp + fp + fn ? 2 * tp / (2 * tp + fp + fn) : null, false_negative_rate: tp + fn ? fn / (tp + fn) : null, false_positive_rate: fp + tn ? fp / (fp + tn) : null, error_rate: tp + fp + tn + fn ? (fp + fn) / (tp + fp + tn + fn) : null };
}
function evaluation(split = 'val') {
  const pair = { candidate: metrics(1, 0, 2, 1), baseline: metrics(1, 1, 1, 1) };
  const sample = { sample_id: 'val_1', category: 'part', group_id: 'group_val', truth_mask_sha256: sha(), candidate: { ...pair.candidate, prediction_sha256: sha(), prediction_mask_sha256: sha() }, baseline: { ...pair.baseline, prediction_sha256: sha(), prediction_mask_sha256: sha() }, error_candidate: true, review_status: 'PENDING_HUMAN_REVIEW', annotation_error_confirmed: false };
  return { schema_version: 'visiondata-gate.learning-evaluation.v1', split, policy, aggregate: pair, categories: { part: pair }, sample_results: split === 'val' ? [sample] : [], latency: { scope: 'LOCAL_CPU_OBSERVATION_ONLY', timer: 'time.perf_counter', measurement: 'predict_call_only', model_order: ['candidate', 'baseline'], observations_per_sample: 1, warmup_runs: 0, quantile_method: 'linear', benchmark_claim: false, candidate: { sample_count: 1, p95_ms: 1 }, baseline: { sample_count: 1, p95_ms: 1 } }, decision: 'HOLD', blockers: ['FALSE_NEGATIVE_RATE_EXCEEDED', 'MIN_DICE_NOT_MET'], observed_elapsed_seconds: 0.01 };
}
async function run(status = 'COMPLETED') {
  const data = await dataset();
  const body = { schema_version: 'visiondata-gate.learning-run.v1', run_id: 'run_a', cycle_id: 'cycle_a', project_id: scope.projectId, round_number: 1, retry_of_run_id: null, feedback_parent_run_id: null, responds_to_feedback_ids: [], feedback_response_boundary: 'New data is bound to prior feedback; this is not automatic verification that each issue was fixed.', status, dataset_id: data.dataset_id, dataset_receipt_sha256: data.receipt_sha256, dataset_storage_key: 'dataset_storage_a', binding: { ...binding }, initial_model_id: 'model_initial', initial_model_sha256: sha(), configuration: training, approval: { ...authorization, task_id: binding.task_id, expected_cycle_sha256: sha() }, approved_by: 'reviewer', started_at: '2026-09-12T12:00:00.000+00:00', feedback: [], selection: null, cancel_requested: false, production_release_allowed: false, remote_execution_verified: false };
  if (status === 'COMPLETED') {
    const observed = evaluation();
    Object.assign(body, { completed_at: '2026-09-12T12:00:01.000+00:00', training: { loss_before: 0.7, loss_after: 0.6, epochs_completed: 2, training_sample_ids: ['train_1'], training_pixel_count: 4, elapsed_seconds: 0.02, initial_model_sha256: sha(), optimizer: 'full_batch_gradient_descent', device: 'CPU' }, model_id: 'model_candidate', model_sha256: sha(), evaluation: observed, evaluation_sha256: await digest(observed), elapsed_seconds: 0.03, feedback: [{ feedback_id: 'feedback_a', status: 'PENDING_HUMAN_REVIEW', evidence: observed.sample_results[0], classification: null, next_action: 'INVESTIGATE', training_ingestion_allowed: false, followup_task_id: null }] });
  } else if (status !== 'RUNNING') Object.assign(body, { completed_at: '2026-09-12T12:00:01.000+00:00', ...(status === 'INTERRUPTED' ? { cancel_requested: true } : { failure_code: 'LOCAL_EXECUTION_FAILED', failure_type: 'ValueError', elapsed_seconds: 0.03 }) });
  return sealed(body);
}

test('cycle receipt checks JCS and strong ETag while list items need no ETag', async () => {
  const validate = validator('validateLearningCycle'); const value = await cycle();
  assert.equal((await validate(value, scope, 'cycle_a', `"${value.receipt_sha256}"`)).status, 'READY');
  assert.equal((await validate(value, scope)).receipt_sha256, value.receipt_sha256);
  for (const etag of [null, '', value.receipt_sha256, `W/"${value.receipt_sha256}"`, `"${sha('f')}"`]) await assert.rejects(validate(value, scope, 'cycle_a', etag), hold);
  await assert.rejects(validate({ ...value, revision: 1 }, scope), hold);
});

test('cycle scope, IDs, statuses and local-only authority fail closed even with fresh hashes', async () => {
  const validate = validator('validateLearningCycle');
  for (const change of [{ project_id: 'project_other' }, { workspace_id: 'workspace_other' }, { cycle_id: 'cycle_other' }, { status: 'DEPLOYED' }, { production_release_allowed: true }, { remote_execution_verified: true }, { machine_write_permitted: true }, { scope: 'PRODUCTION' }, { revision: -1 }]) await assert.rejects(validate(await sealed({ ...await cycle(), ...change }), scope, 'cycle_a'), hold);
});

test('dataset hashes exclude both derived fields and bind workspace, split isolation, and dimensions', async () => {
  const validate = validator('validateLearningDataset'); const value = await dataset();
  assert.equal((await validate(value, scope)).dataset_id, value.dataset_id);
  await assert.rejects(validate({ ...value, dataset_id: 'dataset_other' }, scope), hold);
  const wrong = await dataset(); wrong.binding.workspace_id = 'workspace_other';
  await assert.rejects(validate(wrong, scope), hold);
  const duplicate = await dataset(); duplicate.samples[1].group_id = duplicate.samples[0].group_id;
  await assert.rejects(validate(duplicate, scope), hold);
  const dimension = await dataset(); dimension.samples[0].width = 257;
  await assert.rejects(validate(dimension, scope), hold);
});

test('run checks project, nested workspace, cycle and run scope, and preserves non-completion states', async () => {
  const validate = validator('validateLearningRun');
  for (const state of ['RUNNING', 'COMPLETED', 'FAILED', 'CANCELLED', 'INTERRUPTED']) assert.equal((await validate(await run(state), scope, 'cycle_a', 'run_a')).status, state);
  for (const change of [{ project_id: 'project_other' }, { cycle_id: 'cycle_other' }, { run_id: 'run_other' }, { binding: { ...binding, workspace_id: 'workspace_other' } }, { status: 'PASSED' }, { production_release_allowed: true }, { remote_execution_verified: true }]) await assert.rejects(validate(await sealed({ ...await run(), ...change }), scope, 'cycle_a', 'run_a'), hold);
});

test('completed run requires real bound evaluation, training and matching dataset receipt identity', async () => {
  const validate = validator('validateLearningRun');
  for (const key of ['evaluation', 'training', 'model_id', 'evaluation_sha256']) {
    const value = await run(); delete value[key]; await assert.rejects(validate(await sealed(value), scope, 'cycle_a'), hold);
  }
  const changed = await run(); changed.evaluation.aggregate.candidate.dice = 1;
  await assert.rejects(validate(await sealed(changed), scope, 'cycle_a'), hold);
  await assert.rejects(validate(await sealed({ ...await run(), dataset_id: 'dataset_other' }), scope, 'cycle_a'), hold);
});

test('feedback is human triage only and cannot silently become confirmed labels or auto-ingested training data', async () => {
  const validate = validator('validateLearningRun');
  for (const change of [{ training_ingestion_allowed: true }, { status: 'AUTO_APPROVED' }, { classification: 'LABEL_ERROR' }, { evidence: { ...evaluation().sample_results[0], annotation_error_confirmed: true } }]) {
    const value = await run(); Object.assign(value.feedback[0], change);
    await assert.rejects(validate(await sealed(value), scope, 'cycle_a'), hold);
  }
  const reviewed = await run(); Object.assign(reviewed.feedback[0], { status: 'TRIAGED_NOT_AUTO_INGESTED', classification: 'HARD_SAMPLE', next_action: 'COLLECT_SIMILAR_TRAINING_EXAMPLES', reviewed_by: 'reviewer', review_note: 'Human assessed this evidence', followup_task_id: 'task_followup' });
  assert.equal((await validate(await sealed(reviewed), scope, 'cycle_a')).feedback[0].classification, 'HARD_SAMPLE');
});

test('evaluation preserves null metrics, rejects false eligible gates and test sample disclosure', () => {
  const validate = validator('validateLearningEvaluation');
  assert.equal(validate(evaluation(), 'val').decision, 'HOLD');
  const missing = evaluation(); missing.aggregate.candidate = metrics(0, 0, 4, 0); missing.categories.part.candidate = missing.aggregate.candidate;
  assert.equal(validate(missing, 'val').aggregate.candidate.dice, null);
  for (const change of [{ decision: 'PASS' }, { decision: 'ELIGIBLE', blockers: [] }, { blockers: [] }, { split: 'test' }]) assert.throws(() => validate({ ...evaluation(), ...change }, 'val'), hold);
  assert.throws(() => validate({ ...evaluation('test'), sample_results: evaluation().sample_results }, 'test'), hold);
  assert.throws(() => validate({ ...evaluation(), latency: { ...evaluation().latency, benchmark_claim: true } }), hold);
});

test('finalized cycle requires a hashed aggregate-only test evaluation', async () => {
  const validate = validator('validateLearningCycle'); const value = await cycle(); const final_evaluation = evaluation('test');
  const final = await sealed({ ...value, status: 'FINALIZED', final_evaluation, final_evaluation_sha256: await digest(final_evaluation) });
  assert.equal((await validate(final, scope)).final_evaluation.split, 'test');
  await assert.rejects(validate(await sealed({ ...value, status: 'FINALIZED' }), scope), hold);
  await assert.rejects(validate(await sealed({ ...final, final_evaluation_sha256: sha('f') }), scope), hold);
});

test('write requests retain request_key and revision hashes without adding authority or defaults', () => {
  const create = validator('validateCreateLearningRequest'); const round = validator('validateRoundLearningRequest'); const action = validator('validateCycleLearningRequest'); const feedback = validator('validateFeedbackLearningRequest'); const selection = validator('validateSelectionLearningRequest');
  assert.deepEqual(create(authorization), authorization);
  const actionRequest = { request_key: 'fixture_key_12345', review_note: 'Explicit human review note', expected_cycle_sha256: sha(), operator_attests_reviewed: true };
  assert.deepEqual(action(actionRequest), actionRequest);
  assert.equal(round({ ...authorization, task_id: 'task_a', expected_cycle_sha256: sha('b') }).expected_cycle_sha256, sha('b'));
  assert.equal(feedback({ ...actionRequest, classification: 'HARD_SAMPLE', followup_task_id: null }).followup_task_id, null);
  assert.equal(selection({ ...actionRequest, expected_run_sha256: sha('c'), action: 'REJECT' }).expected_run_sha256, sha('c'));
  for (const change of [{ operator_attests_training_authorized: false }, { expected_preflight_sha256: 'stale' }, { request_key: 'short' }, { groups: {} }, { training: { epochs: 501 } }, { production_release_allowed: true }]) assert.throws(() => create({ ...authorization, ...change }), hold);
  assert.throws(() => selection({ ...actionRequest, expected_run_sha256: sha(), action: 'DEPLOY' }), hold);
});

function endpoint(name) { assert.equal(typeof api[name], 'function', `${name} must implement the learning API`); return api[name]; }
function respond(value, headers = {}) { return new Response(JSON.stringify(value), { status: 200, headers: { 'Content-Type': 'application/json', ...(value.receipt_sha256 ? { ETag: `"${value.receipt_sha256}"` } : {}), ...headers } }); }
test('read APIs bind routes and per-item receipts, and a corrupt list fails as a whole', async () => {
  const list = endpoint('listLearningCycles'); const getCycle = endpoint('getLearningCycle'); const getRun = endpoint('getLearningRun'); const calls = [];
  const c = await cycle(); const r = await run();
  globalThis.__learningContractTransport = async (...args) => { calls.push(args); return respond(args[0].includes('/projects/') ? [c] : args[0].includes('/learning-runs/') ? r : c); };
  assert.equal((await list(scope)).length, 1); assert.equal((await getCycle(scope, 'cycle_a')).cycle_id, 'cycle_a'); assert.equal((await getRun(scope, 'cycle_a', 'run_a')).run_id, 'run_a');
  assert.deepEqual(calls.map(call => call[0]), ['/v1/projects/project_a/learning-cycles', '/v1/learning-cycles/cycle_a', '/v1/learning-runs/run_a']);
  globalThis.__learningContractTransport = async () => respond([c, { ...c, project_id: 'foreign' }]);
  await assert.rejects(list(scope), hold);
  globalThis.__learningContractTransport = async () => respond(c, { ETag: '' });
  await assert.rejects(getCycle(scope, 'cycle_a'), hold);
});

test('all authorized write endpoints preserve JSON request keys, hashes and explicit human choices', async () => {
  const create = endpoint('createLearningCycle'); const round = endpoint('runLearningRound'); const review = endpoint('reviewLearningFeedback'); const select = endpoint('selectLearningModel'); const action = endpoint('learningCycleAction');
  const c = await cycle(); const r = await run(); const selected = await sealed({ ...c, status: 'AWAITING_DATA', round_ids: ['run_a'] });
  const reviewed = structuredClone(r); Object.assign(reviewed.feedback[0], { status: 'TRIAGED_NOT_AUTO_INGESTED', classification: 'HARD_SAMPLE', next_action: 'COLLECT_SIMILAR_TRAINING_EXAMPLES', reviewed_by: 'reviewer', review_note: 'Explicit human review note' }); const reviewedReceipt = await sealed(reviewed);
  const calls = []; globalThis.__learningContractTransport = async (...args) => { calls.push(args); return respond(args[0].endsWith('/rounds') ? r : args[0].includes('/feedback/') ? reviewedReceipt : args[0].endsWith('/selection') ? selected : c); };
  const a = { request_key: authorization.request_key, review_note: 'Explicit human review note', expected_cycle_sha256: sha(), operator_attests_reviewed: true };
  const q = { ...authorization, task_id: 'task_a', expected_cycle_sha256: sha() };
  const f = { ...a, classification: 'HARD_SAMPLE', followup_task_id: null }; const s = { ...a, expected_run_sha256: sha(), action: 'REJECT' };
  await create(scope, 'task_a', request); await round(scope, 'cycle_a', q); await review(scope, 'cycle_a', 'run_a', 'feedback_a', f); await select(scope, 'cycle_a', 'run_a', s);
  for (const verb of ['cancel', 'recover', 'finalize']) await action(scope, 'cycle_a', verb, a);
  assert.deepEqual(calls.map(call => call[0]), ['/v1/tasks/task_a/learning-cycles', '/v1/learning-cycles/cycle_a/rounds', '/v1/learning-cycles/cycle_a/runs/run_a/feedback/feedback_a', '/v1/learning-cycles/cycle_a/runs/run_a/selection', ...['cancel', 'recover', 'finalize'].map(verb => `/v1/learning-cycles/cycle_a/${verb}`)]);
  assert.deepEqual(calls.map(call => JSON.parse(call[1].body)), [request, q, f, s, a, a, a]);
  assert.ok(calls.every(call => call[1].method === 'POST'));
});

test('client rejects invalid write requests before dispatch and never replays uncertain transport outcomes', async () => {
  const create = endpoint('createLearningCycle'); const action = endpoint('learningCycleAction'); let calls = 0;
  globalThis.__learningContractTransport = async () => { calls++; throw Object.assign(new Error('Connection interrupted'), { code: 'NETWORK_UNAVAILABLE', status: 0 }); };
  await assert.rejects(create(scope, 'task_a', { ...request, operator_attests_training_authorized: false }), notSent); assert.equal(calls, 0);
  await assert.rejects(action(scope, 'cycle_a', 'deploy', {}), notSent); assert.equal(calls, 0);
  await assert.rejects(create(scope, 'task_a', request), { code: 'NETWORK_UNAVAILABLE', status: 0 }); assert.equal(calls, 1);
  globalThis.__learningContractTransport = async () => { calls++; return new Response('{broken'); };
  await assert.rejects(create(scope, 'task_a', request), hold); assert.equal(calls, 2);
});

test('run status does not hide malformed or contradictory optional completion and failure fields', async () => {
  const validate = validator('validateLearningRun');
  for (const change of [{ completed_at: 12 }, { failure_code: 'LOCAL_EXECUTION_FAILED' }, { elapsed_seconds: 'unknown' }]) await assert.rejects(validate(await sealed({ ...await run('RUNNING'), ...change }), scope, 'cycle_a'), hold);
  await assert.rejects(validate(await sealed({ ...await run(), failure_code: 'LOCAL_EXECUTION_FAILED' }), scope, 'cycle_a'), hold);
  await assert.rejects(validate(await sealed({ ...await run('INTERRUPTED'), elapsed_seconds: -1 }), scope, 'cycle_a'), hold);
});

test('feedback normalizes outgoing review text without mutating the caller request', async () => {
  const review = endpoint('reviewLearningFeedback'); const value = await run();
  Object.assign(value.feedback[0], { status: 'TRIAGED_NOT_AUTO_INGESTED', classification: 'HARD_SAMPLE', next_action: 'COLLECT_SIMILAR_TRAINING_EXAMPLES', reviewed_by: 'reviewer', review_note: 'Explicit human review note' });
  const receipt = await sealed(value); let sent;
  globalThis.__learningContractTransport = async (_path, init) => { sent = JSON.parse(init.body); return respond(receipt); };
  const request = { request_key: authorization.request_key, review_note: '  Explicit human review note  ', expected_cycle_sha256: sha(), operator_attests_reviewed: true, classification: 'HARD_SAMPLE' };
  assert.equal((await review(scope, 'cycle_a', 'run_a', 'feedback_a', request)).feedback[0].review_note, request.review_note.trim());
  assert.equal(sent.review_note, request.review_note.trim());
  assert.equal(request.review_note, '  Explicit human review note  ');
});

test('all write APIs classify invalid request, route scope and serialization as known not sent', async () => {
  const create = endpoint('createLearningCycle'); const round = endpoint('runLearningRound'); const review = endpoint('reviewLearningFeedback'); const select = endpoint('selectLearningModel'); const action = endpoint('learningCycleAction');
  let calls = 0; globalThis.__learningContractTransport = async () => { calls++; throw new Error('Must not dispatch'); };
  const base = { request_key: authorization.request_key, review_note: '   short   ', expected_cycle_sha256: sha(), operator_attests_reviewed: true };
  const requests = [
    () => create(scope, 'task_a', { ...request, review_note: base.review_note }),
    () => round(scope, 'cycle_a', { ...authorization, task_id: 'task_a', expected_cycle_sha256: sha(), review_note: base.review_note }),
    () => review(scope, 'cycle_a', 'run_a', 'feedback_a', { ...base, classification: 'HARD_SAMPLE' }),
    () => select(scope, 'cycle_a', 'run_a', { ...base, expected_run_sha256: sha(), action: 'REJECT' }),
    ...['cancel', 'recover', 'finalize'].map(verb => () => action(scope, 'cycle_a', verb, base)),
    () => create({ ...scope, workspaceId: '../foreign' }, 'task_a', request),
    () => create(scope, '../foreign', request),
    () => round(scope, '../foreign', { ...authorization, task_id: 'task_a', expected_cycle_sha256: sha() }),
    () => review(scope, 'cycle_a', '../foreign', 'feedback_a', { ...base, review_note: 'Explicit human review', classification: 'HARD_SAMPLE' }),
  ];
  const groups = Object.defineProperty({ ...request.groups }, 'toJSON', { value: () => { throw new Error('Cannot serialize group mapping'); } });
  requests.push(() => create(scope, 'task_a', { ...request, groups }));
  for (const operation of requests) { await assert.rejects(operation(), notSent); assert.equal(calls, 0); }
});

test('all writes normalize backend string fields before validation and preserve collection groups', async () => {
  const c = await cycle(); const r = await run(); const selected = await sealed({ ...c, status: 'AWAITING_DATA', round_ids: ['run_a'] });
  const reviewed = structuredClone(r); Object.assign(reviewed.feedback[0], { status: 'TRIAGED_NOT_AUTO_INGESTED', classification: 'HARD_SAMPLE', next_action: 'COLLECT_SIMILAR_TRAINING_EXAMPLES', reviewed_by: 'reviewer', review_note: 'Explicit human review note', followup_task_id: 'task_followup' }); const reviewedReceipt = await sealed(reviewed);
  const calls = []; globalThis.__learningContractTransport = async (...args) => { calls.push(args); return respond(args[0].endsWith('/rounds') ? r : args[0].includes('/feedback/') ? reviewedReceipt : args[0].endsWith('/selection') ? selected : c); };
  const padded = { request_key: ` ${authorization.request_key} `, review_note: '  Explicit human review note\n', expected_cycle_sha256: ` ${sha()} `, operator_attests_reviewed: true };
  const groups = { ...authorization.groups, train_1: ' group_train ' };
  await api.createLearningCycle(scope, 'task_a', { ...request, request_key: padded.request_key, review_note: padded.review_note, expected_preflight_sha256: ` ${sha()} ` });
  await api.runLearningRound(scope, 'cycle_a', { ...authorization, request_key: padded.request_key, review_note: padded.review_note, expected_preflight_sha256: ` ${sha()} `, groups, task_id: ' task_a ', expected_cycle_sha256: padded.expected_cycle_sha256 });
  await api.reviewLearningFeedback(scope, 'cycle_a', 'run_a', 'feedback_a', { ...padded, classification: 'HARD_SAMPLE', followup_task_id: ' task_followup ' });
  await api.selectLearningModel(scope, 'cycle_a', 'run_a', { ...padded, expected_run_sha256: ` ${sha()} `, action: 'REJECT' });
  for (const verb of ['cancel', 'recover', 'finalize']) await api.learningCycleAction(scope, 'cycle_a', verb, padded);
  const bodies = calls.map(call => JSON.parse(call[1].body));
  assert.ok(bodies.every(body => body.review_note === 'Explicit human review note' && body.request_key === authorization.request_key));
  assert.deepEqual(bodies[1].groups, groups); assert.equal(bodies[1].task_id, 'task_a');
  assert.equal(bodies[1].expected_preflight_sha256, sha()); assert.equal(bodies[1].expected_cycle_sha256, sha());
  assert.equal(bodies[2].followup_task_id, 'task_followup'); assert.equal(bodies[3].expected_run_sha256, sha());
});

const normalAttestation = { reviewer_name: 'Human reviewer', review_note: 'No foreground after actual annotation review', expected_asset_sha256: sha(), expected_annotation_revision: 0, expected_annotation_sha256: sha('b'), operator_attests_no_foreground: true };
test('new normalized request defaults and previous-run lineage coexist with legacy receipts', async () => {
  const cycleValue = await cycle(); cycleValue.request = { ...cycleValue.request, normal_mask_attestations: {} };
  assert.deepEqual(await validator('validateLearningCycle')(await sealed(cycleValue), scope), await sealed(cycleValue));
  const runValue = await run(); runValue.approval = { ...runValue.approval, normal_mask_attestations: {}, responds_to_feedback_ids: [] }; runValue.previous_run_id = null;
  assert.deepEqual(await validator('validateLearningRun')(await sealed(runValue), scope, 'cycle_a'), await sealed(runValue));
  assert.equal(validator('validateCreateLearningRequest')({ ...request, normal_mask_attestations: { train_1: normalAttestation } }).normal_mask_attestations.train_1.expected_annotation_revision, 0);
  assert.throws(() => validator('validateCreateLearningRequest')({ ...request, normal_mask_attestations: { train_1: { ...normalAttestation, operator_attests_no_foreground: false } } }), hold);
  assert.throws(() => validator('validateRoundLearningRequest')({ ...runValue.approval, responds_to_feedback_ids: ['feedback_fake'] }), hold);
  const mismatched = { ...runValue, responds_to_feedback_ids: ['feedback_' + 'a'.repeat(24)] };
  await assert.rejects(validator('validateLearningRun')(await sealed(mismatched), scope, 'cycle_a'), hold);
});

test('normal-mask dataset declarations remain inside the original digest and sample binding', async () => {
  const value = await dataset(); value.normal_mask_attestations = { train_1: normalAttestation };
  value.samples[0].mask_origin = 'EXPLICIT_HUMAN_ZERO_MASK'; value.samples[0].normal_attestation_sha256 = await digest(normalAttestation);
  const sealDataset = async value => { const body = { ...value }; delete body.dataset_id; delete body.receipt_sha256; const receipt_sha256 = await digest(body); return { ...body, dataset_id: `dataset_${receipt_sha256.slice(0, 24)}`, receipt_sha256 }; };
  const receipt = await sealDataset(value);
  assert.deepEqual(await validator('validateLearningDataset')(receipt, scope), receipt);
  for (const change of [{ normal_attestation_sha256: sha('f') }, { mask_origin: 'AUTO_ZERO_MASK' }, { image_sha256: sha('f') }]) {
    const changed = structuredClone(value); Object.assign(changed.samples[0], change);
    await assert.rejects(validator('validateLearningDataset')(await sealDataset(changed), scope), hold);
  }
  const removed = structuredClone(receipt); delete removed.normal_mask_attestations;
  await assert.rejects(validator('validateLearningDataset')(removed, scope), hold);
});

async function readiness() {
  return sealed({ schema_version: 'visiondata-gate.learning-readiness.v1', task_id: 'task_a', project_id: scope.projectId, workspace_id: scope.workspaceId, projection_status: 'VERIFIED', preflight_receipt_sha256: sha(), preflight_eligibility: 'READY_FOR_OFFLINE_HANDOFF', blockers: [], members: ['train', 'val', 'test'].map(split => ({ sample_id: `${split}_1`, split, category: 'part', annotation_requirement: 'REQUIRED', mask_available: true, readiness_state: 'GATE_ELIGIBLE_NOT_TRAINING_APPROVED', finding_refs: [] })), global_findings: [], unmapped_finding_refs: [], training_authorized: false, production_release_allowed: false, annotation_review_basis: 'OPERATOR_ATTESTATION_NOT_INDEPENDENT_TRUTH', required_dataset_validation: ['GROUP_DECLARATIONS', 'BINARY_MASK_VALUES', 'TRAIN_VAL_TEST_COVERAGE', 'GROUP_AND_PIXEL_SPLIT_ISOLATION', 'IMAGE_MASK_SHAPES_AND_RESOURCE_LIMITS'], claim_boundary: 'Frozen Gate projection is not training approval or independent label truth.', receipt_sha256: '' });
}
async function linkedRun() {
  const value = await run();
  const followup = await sealed({ binding: { ...binding, task_id: 'task_followup', source_id: 'source_new' }, preflight_receipt_sha256: sha('b'), sample_ids: ['new_train'], members: [{ sample_id: 'new_train', split: 'train', image_sha256: sha(), annotation_revision: 1, annotation_document_sha256: sha('b'), mask_sha256: null }], reviewed_by: 'reviewer', review_note: 'Human-linked new Gate members', at: '2026-09-12T12:00:00.000+00:00', issue_closed: false, training_ingestion_allowed: false, boundary: 'New evidence is not proof of fixing the original model error.' });
  Object.assign(value.feedback[0], { status: 'TRIAGED_NOT_AUTO_INGESTED', classification: 'HARD_SAMPLE', next_action: 'COLLECT_SIMILAR_TRAINING_EXAMPLES', reviewed_by: 'reviewer', review_note: 'Explicit human review note', followup_task_id: 'task_followup', followup_status: 'NEW_GATE_EVIDENCE_LINKED_NOT_ISSUE_CLOSED', followup });
  return sealed(value);
}
async function operation(operation = 'create', current_result = null, target_id = 'task_a') {
  let request_sha256 = null;
  if (current_result && operation === 'create') request_sha256 = await digest({ ...current_result.request, normal_mask_attestations: current_result.request.normal_mask_attestations ?? {} });
  else if (current_result && operation === 'train') request_sha256 = await digest({ ...current_result.approval, normal_mask_attestations: current_result.approval.normal_mask_attestations ?? {}, responds_to_feedback_ids: current_result.approval.responds_to_feedback_ids ?? [] });
  else if (current_result) request_sha256 = sha();
  return sealed({ schema_version: 'visiondata-gate.learning-operation.v1', project_id: scope.projectId, operation, request_key: authorization.request_key, target_id, lookup_status: current_result ? 'FOUND' : 'NOT_FOUND', request_sha256, request_digest_semantics: 'SERVER_CANONICAL_VALIDATED_REQUEST', request_digest_verification: current_result ? ['create', 'train'].includes(operation) ? 'MATCHED_STORED_VALIDATED_REQUEST' : 'LEDGER_SHA_ONLY' : 'NOT_AVAILABLE', result_semantics: 'CURRENT_RESULT', result_kind: current_result ? current_result.run_id ? 'run' : 'cycle' : null, result_id: current_result ? current_result.run_id ?? current_result.cycle_id : null, result_receipt_sha256: current_result?.receipt_sha256 ?? null, current_result, execution_status: current_result ? ['RUNNING', 'FINALIZING'].includes(current_result.status) ? 'PENDING' : 'RESULT_AVAILABLE' : 'UNKNOWN_NOT_PROOF_OF_NO_WRITE', automatic_retry_allowed: false });
}
test('readiness verifies sample findings without granting training or claiming independent label truth', async () => {
  const validate = validator('validateLearningReadiness'); const value = await readiness();
  assert.deepEqual(await validate(value, scope, 'task_a', `"${value.receipt_sha256}"`), value);
  for (const change of [{ workspace_id: 'foreign' }, { task_id: 'foreign' }, { training_authorized: true }, { projection_status: 'PASS' }, { annotation_review_basis: 'INDEPENDENT_TRUTH' }]) await assert.rejects(validate(await sealed({ ...value, ...change }), scope, 'task_a'), hold);
  const changed = structuredClone(value); changed.members[0].readiness_state = 'GOOD_DATA';
  await assert.rejects(validate(await sealed(changed), scope, 'task_a'), hold);
  const unresolved = await sealed({ ...value, projection_status: 'UNVERIFIED', preflight_receipt_sha256: null, preflight_eligibility: 'UNVERIFIED', members: [], blockers: ['PREFLIGHT_UNAVAILABLE'] });
  assert.equal((await validate(unresolved, scope, 'task_a')).training_authorized, false);
});
test('operation receipts bind targets and current results; NOT_FOUND never permits automatic retry', async () => {
  const validate = validator('validateLearningOperation');
  const missing = await operation(); assert.equal((await validate(missing, scope, 'create', authorization.request_key, 'task_a')).execution_status, 'UNKNOWN_NOT_PROOF_OF_NO_WRITE');
  const found = await operation('create', await cycle()); assert.equal((await validate(found, scope, 'create', authorization.request_key, 'task_a')).lookup_status, 'FOUND');
  for (const change of [{ automatic_retry_allowed: true }, { target_id: 'foreign' }, { project_id: 'foreign' }, { request_key: 'other_request_key' }, { execution_status: 'RESULT_AVAILABLE' }]) await assert.rejects(validate(await sealed({ ...missing, ...change }), scope, 'create', authorization.request_key, 'task_a'), hold);
  await assert.rejects(validate(await sealed({ ...found, request_sha256: sha('f') }), scope, 'create', authorization.request_key, 'task_a'), hold);
  const pending = await operation('train', await run('RUNNING'), 'cycle_a'); assert.equal((await validate(pending, scope, 'train', authorization.request_key, 'cycle_a')).execution_status, 'PENDING');
  await assert.rejects(validate(await sealed({ ...pending, execution_status: 'RESULT_AVAILABLE' }), scope, 'train', authorization.request_key, 'cycle_a'), hold);
});
test('human-linked followup checks its own receipt, scope and members but never closes the issue', async () => {
  const validate = validator('validateLearningRun'); const value = await linkedRun();
  assert.deepEqual(await validate(value, scope, 'cycle_a'), value);
  for (const change of [{ issue_closed: true }, { training_ingestion_allowed: true }, { binding: { ...value.feedback[0].followup.binding, project_id: 'foreign' } }, { sample_ids: ['not-a-member'] }]) {
    const changed = structuredClone(value); changed.feedback[0].followup = await sealed({ ...changed.feedback[0].followup, ...change });
    await assert.rejects(validate(await sealed(changed), scope, 'cycle_a'), hold);
  }
});
test('new readiness, operation and followup endpoints use verified contracts and known-not-sent validation', async () => {
  const ready = endpoint('getLearningReadiness'); const lookup = endpoint('getLearningOperation'); const link = endpoint('linkLearningFeedback');
  const readyValue = await readiness(); const op = await operation(); const linked = await linkedRun(); const calls = [];
  globalThis.__learningContractTransport = async (...args) => { calls.push(args); return respond(args[0].includes('/learning-readiness') ? readyValue : args[0].includes('/learning-operations/') ? op : linked); };
  await ready(scope, 'task_a'); await lookup(scope, 'create', authorization.request_key, 'task_a');
  const request = { request_key: authorization.request_key, review_note: '  Human-linked new Gate members ', expected_cycle_sha256: sha(), expected_run_sha256: sha(), operator_attests_reviewed: true, task_id: 'task_followup', expected_preflight_sha256: sha('b'), sample_ids: ['new_train'] };
  await link(scope, 'cycle_a', 'run_a', 'feedback_a', request);
  assert.deepEqual(calls.map(call => call[0]), ['/v1/tasks/task_a/learning-readiness', `/v1/projects/project_a/learning-operations/create/${authorization.request_key}?target_id=task_a`, '/v1/learning-cycles/cycle_a/runs/run_a/feedback/feedback_a/followup']);
  assert.equal(JSON.parse(calls[2][1].body).review_note, request.review_note.trim());
  await assert.rejects(link(scope, 'cycle_a', 'run_a', 'feedback_a', { ...request, sample_ids: [] }), notSent); assert.equal(calls.length, 3);
});

test('final candidate acceptance bundle binds final test decision and a retained or reverted champion', async () => {
  const validate = validator('validateLearningCycle'); const final_evaluation = evaluation('test');
  const value = await sealed({ ...await cycle(), status: 'FINALIZED', approved_model_ids: ['model_initial', 'model_candidate'], final_evaluation, final_evaluation_sha256: await digest(final_evaluation), final_candidate_model_id: 'model_candidate', final_candidate_model_sha256: sha('b'), final_baseline_model_id: 'model_initial', final_baseline_model_sha256: sha('c'), final_candidate_accepted: false });
  assert.deepEqual(await validate(value, scope), value);
  for (const change of [{ final_candidate_accepted: true }, { champion_model_id: 'model_candidate', approved_model_ids: ['model_initial', 'model_candidate'] }, { final_baseline_model_id: 'foreign_model' }]) await assert.rejects(validate(await sealed({ ...value, ...change }), scope), hold);
  const partial = { ...value }; delete partial.final_candidate_model_sha256;
  await assert.rejects(validate(await sealed(partial), scope), hold);
});

test('normal-mask attestation strings are normalized before sending without changing groups or caller data', async () => {
  const padded = Object.fromEntries(Object.entries(normalAttestation).map(([key, value]) => [key, typeof value === 'string' ? ` ${value} ` : value]));
  const input = { ...request, normal_mask_attestations: { train_1: padded } }; let sent;
  const value = await cycle(); value.request = { ...value.request, normal_mask_attestations: { train_1: normalAttestation } }; const receipt = await sealed(value);
  globalThis.__learningContractTransport = async (_path, init) => { sent = JSON.parse(init.body); return respond(receipt); };
  await api.createLearningCycle(scope, 'task_a', input);
  assert.deepEqual(sent.normal_mask_attestations, { train_1: normalAttestation });
  assert.deepEqual(sent.groups, input.groups); assert.deepEqual(input.normal_mask_attestations, { train_1: padded });
});
