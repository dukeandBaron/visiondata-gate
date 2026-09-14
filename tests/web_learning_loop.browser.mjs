/** Isolated learning-workbench browser interactions using synthetic API doubles.
 * No user's project, data, credentials, model or real API is read or written.
 * node --test tests/web_learning_loop.browser.mjs
 * VDG_PLAYWRIGHT_MODULE may point to an existing playwright-core/index.mjs.
 */
import assert from 'node:assert/strict';
import { before, after, test } from 'node:test';
import { createRequire } from 'node:module';
import { existsSync, mkdirSync } from 'node:fs';
import { fileURLToPath, pathToFileURL } from 'node:url';
import path from 'node:path';

const root = fileURLToPath(new URL('..', import.meta.url));
const webRoot = path.join(root, 'web');
const require = createRequire(path.join(webRoot, 'package.json'));
const { build, transformWithOxc } = await import(pathToFileURL(require.resolve('vite')).href);
const existingPlaywright = 'D:/Users/living/.npm-cache/_npx/31e32ef8478fbf80/node_modules/playwright-core/index.mjs';
const playwrightModule = process.env.VDG_PLAYWRIGHT_MODULE || (existsSync(existingPlaywright) ? existingPlaywright : require.resolve('playwright'));
const { chromium } = await import(pathToFileURL(playwrightModule).href);
let browser, bundle;

const modules = new Map([
  ['\0learning-context', `export function useProduct() { return window.__testProduct; }`],
  ['\0learning-api', `
    export class OperatorApiError extends Error {
      constructor(code, message = code, status = 503) { super(message); this.code = code; this.status = status; }
    }
    export async function listAgentTasks() { return structuredClone(window.__testTasks); }
    export async function getAgentTask(taskId) { return structuredClone(window.__testTasks.find(item => item.task_id === taskId)); }
    export async function getTaskVisualEvidence(taskId) {
      window.__visualReads.push({operation:'manifest', taskId});
      const manifest = structuredClone(window.__frozenManifest);
      if (window.__visualSourceMismatch) manifest.source_id = 'source-unrelated';
      return manifest;
    }
    const syntheticPixel = () => URL.createObjectURL(new Blob([
      Uint8Array.from(atob('iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+jRZkAAAAASUVORK5CYII='), character => character.charCodeAt(0)),
    ], {type:'image/png'}));
    export async function loadTaskVisualEvidencePreview(item) {
      window.__visualReads.push({operation:'preview', sampleId:item.sample_id});
      return syntheticPixel();
    }
    export async function loadTaskVisualEvidenceMask(item) {
      window.__visualReads.push({operation:'mask', sampleId:item.sample_id});
      return syntheticPixel();
    }
    export async function listLocalTaskSources() { return []; }
    export async function operatorFetch() { throw new Error('Real operatorFetch is forbidden in isolated learning tests'); }
  `],
  ['\0learning-compute', `
    export async function getComputePreflight(scope) {
      window.__reads.push({operation:'preflight', scope:structuredClone(scope)});
      return structuredClone(window.__testPreflight);
    }
  `],
  ['\0learning-client', `
    import {OperatorApiError} from '\0learning-api';
    const clone = value => structuredClone(value);
    const read = (operation, scope, id) => {
      window.__reads.push({operation, scope:clone(scope), id, afterWrites:window.__writes.length});
      if (window.__readFailure) throw new OperatorApiError('HTTP_503', 'Synthetic learning read failed', 503);
    };
    export async function listLearningCycles(scope) {
      read('list', scope);
      const projectId = typeof scope === 'string' ? scope : scope.projectId;
      if (projectId !== 'project-test') {
        if (window.__holdOtherProject) await new Promise(resolve => { window.__releaseOtherProject = resolve; });
        return [];
      }
      return [clone(window.__cycle)];
    }
    export async function getLearningCycle(scope, cycleId) {
      read('cycle', scope, cycleId);
      if (scope.projectId !== window.__cycle.project_id || scope.workspaceId !== window.__cycle.workspace_id) {
        throw new OperatorApiError('LEARNING_CONTRACT_HOLD', 'Synthetic cross-project cycle rejected', 409);
      }
      if (cycleId !== window.__cycle.cycle_id) throw new Error('Unexpected synthetic cycle');
      return clone(window.__cycle);
    }
    export async function getLearningRun(scope, cycleId, runId) {
      read('run', scope, runId);
      if (cycleId !== window.__cycle.cycle_id) throw new Error('Unexpected synthetic run cycle');
      if (runId !== window.__run.run_id) throw new Error('Unexpected synthetic run');
      return clone(window.__run);
    }
    export async function getLearningReadiness(scope, taskId) {
      read('readiness', scope, taskId);
      return clone(window.__testReadiness);
    }
    export async function getLearningOperation(scope, operation, key, targetId) {
      read('operation', scope, key);
      window.__operationReads.push({scope:clone(scope),operation,key,targetId});
      const found = ['PENDING','RESULT_AVAILABLE'].includes(window.__operationStatus);
      const result = found ? clone(window.__run) : null;
      if (result && window.__operationStatus === 'PENDING') result.status = 'RUNNING';
      return {
        schema_version:'visiondata-gate.learning-operation.v1',project_id:scope.projectId,
        operation,request_key:key,target_id:targetId,lookup_status:found ? 'FOUND' : 'NOT_FOUND',
        request_sha256:found ? '8'.repeat(64) : null,
        request_digest_semantics:'SERVER_CANONICAL_VALIDATED_REQUEST',
        request_digest_verification:found ? 'LEDGER_SHA_ONLY' : 'NOT_AVAILABLE',
        result_semantics:'CURRENT_RESULT',result_kind:found ? 'run' : null,result_id:found ? result.run_id : null,
        result_receipt_sha256:found ? result.receipt_sha256 : null,current_result:result,
        execution_status:found ? window.__operationStatus : 'UNKNOWN_NOT_PROOF_OF_NO_WRITE',
        automatic_retry_allowed:false,receipt_sha256:'9'.repeat(64),
      };
    }
    export async function reviewLearningFeedback(scope, cycleId, runId, feedbackId, request) {
      window.__writes.push({operation:'feedback', scope:clone(scope), cycleId, runId, feedbackId, request:clone(request)});
      if (request.expected_cycle_sha256 !== window.__cycle.receipt_sha256) throw new Error('Test caught a stale cycle write');
      if (window.__unknownWrite !== 'unpersisted') {
        const feedback = window.__run.feedback.find(item => item.feedback_id === feedbackId);
        Object.assign(feedback, {
          status:'TRIAGED_NOT_AUTO_INGESTED', classification:request.classification,
          next_action:request.classification === 'HARD_SAMPLE' ? 'COLLECT_SIMILAR_TRAINING_EXAMPLES' : 'INVESTIGATE',
          reviewed_by:'synthetic-reviewer', review_note:request.review_note,
          followup_task_id:request.followup_task_id || null, training_ingestion_allowed:false,
        });
        window.__cycle.revision += 1;
        window.__cycle.receipt_sha256 = String(window.__cycle.revision + 1).repeat(64);
        window.__cycle.events.push({event:'FEEDBACK_TRIAGED', actor:'synthetic-reviewer', at:'2026-09-12T00:00:00Z'});
        window.__run.receipt_sha256 = String(window.__cycle.revision + 4).repeat(64);
      }
      if (window.__unknownWrite) throw new OperatorApiError('HTTP_503', 'Synthetic unknown write result', 503);
      return clone(window.__run);
    }
    const unexpected = name => async (...args) => {
      window.__writes.push({operation:name, args:clone(args)});
      throw new Error('Unexpected ' + name + ' mutation in feedback test');
    };
    export async function createLearningCycle(scope, taskId, request) {
      window.__writes.push({operation:'create',scope:clone(scope),taskId,request:clone(request)});
      if (!window.__allowCreate) throw new Error('Unexpected synthetic create');
      const cycle = clone(window.__cycle);
      Object.assign(cycle,{cycle_id:'cycle-created',status:'READY',round_ids:[],request:clone(request)});
      cycle.dataset.normal_mask_attestations = clone(request.normal_mask_attestations || {});
      return cycle;
    }
    export const linkLearningFeedback = unexpected('followup');
    export const runLearningRound = unexpected('round');
    export const selectLearningModel = unexpected('selection');
    export const learningCycleAction = unexpected('cycle-action');
    export const rollbackLearningModel = unexpected('rollback');
    export const cancelLearningCycle = unexpected('cancel');
    export const recoverLearningCycle = unexpected('recover');
    export const finalizeLearningCycle = unexpected('finalize');
    export const getLearningModel = unexpected('model');
  `],
  ['\0learning-entry.tsx', `
    import {useState} from 'react';
    import {createRoot} from 'react-dom/client';
    import {MemoryRouter} from 'react-router-dom';
    import {LearningLoopPage} from '/src/pages/LearningLoopPage.tsx';
    import '/src/styles/tokens.css';
    import '/src/styles/index.css';
    function Harness() {
      const [version, render] = useState(0);
      window.__renderVersion = version;
      window.__rerenderSameScope = () => {
        window.__testProduct = {
          ...window.__testProduct,
          activeWorkspace:{...window.__testProduct.activeWorkspace},
          activeProject:{...window.__testProduct.activeProject},
        };
        render(value => value + 1);
      };
      window.__changeScope = (workspaceId, projectId) => {
        window.__testProduct = {
          ...window.__testProduct,
          activeWorkspace:{workspace_id:workspaceId,name:'Other synthetic workspace'},
          activeProject:{project_id:projectId,workspace_id:workspaceId,name:'Other synthetic project'},
        };
        render(value => value + 1);
      };
      return <LearningLoopPage/>;
    }
    createRoot(document.getElementById('root')).render(<MemoryRouter initialEntries={['/learning']}><Harness/></MemoryRouter>);
  `],
]);

before(async () => {
  const result = await build({
    root:webRoot, configFile:false, logLevel:'error',
    define:{'process.env.NODE_ENV':JSON.stringify('production')},
    build:{write:false,minify:false,lib:{entry:'/__learning_entry.tsx',name:'LearningLoopTest',formats:['iife']}},
    plugins:[{
      name:'isolated-learning-loop', enforce:'pre',
      resolveId(id) {
        if (modules.has(id)) return id;
        if (id.endsWith('__learning_entry.tsx')) return '\0learning-entry.tsx';
        for (const [suffix, target] of [
          ['/ProductContext','context'], ['/data/api','api'],
          ['/data/computeApi','compute'], ['/data/learningApi','client'],
        ]) if (id.endsWith(suffix)) return '\0learning-' + target;
      },
      load(id) { return modules.get(id); },
      transform(code,id) {
        if (id.startsWith('\0learning-') && id.endsWith('.tsx')) {
          return transformWithOxc(code,id.slice(1),{lang:'tsx',jsx:{runtime:'automatic'}});
        }
      },
    }],
  });
  const output = (Array.isArray(result) ? result[0] : result).output;
  bundle = {
    js:output.find(item => item.type === 'chunk').code,
    css:output.filter(item => item.type === 'asset' && item.fileName.endsWith('.css')).map(item => item.source).join('\n'),
  };
  const executablePath = process.env.VDG_BROWSER_EXECUTABLE || [
    'C:/Program Files (x86)/Microsoft/Edge/Application/msedge.exe',
    'C:/Program Files/Google/Chrome/Application/chrome.exe',
  ].find(existsSync);
  browser = await chromium.launch({headless:true,...(executablePath ? {executablePath} : {})});
  mkdirSync(path.join(root,'output/playwright'),{recursive:true});
});
after(async () => { await browser?.close(); });

async function scenario({secondFeedback = false,context = null,selectCycle = true} = {}) {
  const page = context ? await context.newPage() : await browser.newPage({viewport:{width:1600,height:1100}});
  if (context) await page.setViewportSize({width:1600,height:1100});
  page.setDefaultTimeout(8000);
  const errors = [];
  page.on('pageerror', error => errors.push(error.message));
  await page.route('**/*', route => route.abort());
  await page.route('http://localhost/test', route => route.fulfill({
    contentType:'text/html', body:'<!doctype html><html><body><div id="root"></div></body></html>',
  }));
  await page.goto('http://localhost/test');
  await page.evaluate(({secondFeedback}) => {
    const digest = character => character.repeat(64);
    const binding = {
      task_id:'task-test', workspace_id:'workspace-test', project_id:'project-test',
      source_id:'source-test', snapshot_id:'snapshot-test', manifest_sha256:digest('a'),sample_count:3,
      snapshot_receipt_sha256:digest('f'),gate_receipt_sha256:digest('b'), acceptance_requirements_sha256:digest('c'),
    };
    const candidate = {tp:96,fp:2,tn:98,fn:4,dice:0.97,false_negative_rate:0.04,false_positive_rate:0.02};
    const baseline = {tp:75,fp:20,tn:80,fn:25,dice:0.77,false_negative_rate:0.25,false_positive_rate:0.2};
    const evidence = {
      sample_id:'sample-val', category:'synthetic-part', group_id:'group-val',
      truth_mask_sha256:digest('d'), candidate, baseline, error_candidate:true,
      review_status:'PENDING_HUMAN_REVIEW', annotation_error_confirmed:false,
    };
    const feedback = {
      feedback_id:'feedback-test', status:'PENDING_HUMAN_REVIEW', evidence,
      classification:null, next_action:'INVESTIGATE', training_ingestion_allowed:false, followup_task_id:null,
    };
    const samples = ['train','val','test'].map((split, index) => ({
      sample_id:'sample-' + split, split, category:'synthetic-part', group_id:'group-' + split,
      image_path:split + '/synthetic.png', mask_path:split + '/mask.png',
      image_sha256:digest('a'), mask_sha256:digest('b'), pixel_sha256:digest(String(index + 1)),
      mask_pixel_sha256:digest(String(index + 4)), width:20, height:10,
    }));
    window.__testProduct = {
      activeWorkspace:{workspace_id:'workspace-test',name:'Synthetic workspace'},
      activeProject:{project_id:'project-test',workspace_id:'workspace-test',name:'Synthetic project'},
      workspaceLoading:false,registerScopeChangeGuard:() => () => {},
    };
    window.__testTasks = [{
      task_id:'task-test',workspace_id:'workspace-test',project_id:'project-test',
      goal:'Synthetic reviewed task',execution_status:'COMPLETED',status:'PASS',
    }];
    window.__frozenManifest = {
      task_id:'task-test',workspace_id:'workspace-test',project_id:'project-test',source_id:'source-test',
      operator_snapshot_receipt_sha256:binding.snapshot_receipt_sha256,visual_count:samples.length,
      items:samples.map(item => ({
        ...item,source_sha256:item.image_sha256,original_name:item.sample_id + '.png',
        annotation_count:1,annotation_revision:7,annotation_document_sha256:digest('9'),
        preview_url:'synthetic-only-preview',mask_url:'synthetic-only-mask',
      })),
    };
    window.__testPreflight = {
      schema_version:'visiondata-gate.compute-preflight.v1',...binding,
      eligibility:'READY_FOR_OFFLINE_HANDOFF',blockers:[],binding,receipt_sha256:digest('e'),
      adapter:{kind:'OFFLINE_EXPORT',live_submission_available:false,device_validation:'NOT_TESTED'},
      production_release_allowed:false,
    };
    window.__testReadiness = {
      schema_version:'visiondata-gate.learning-readiness.v1',task_id:'task-test',workspace_id:'workspace-test',project_id:'project-test',
      projection_status:'VERIFIED',preflight_receipt_sha256:digest('e'),preflight_eligibility:'READY_FOR_OFFLINE_HANDOFF',blockers:[],
      members:samples.map(item => ({
        sample_id:item.sample_id,split:item.split,category:item.category,annotation_requirement:'REQUIRED',
        mask_available:true,readiness_state:'GATE_ELIGIBLE_NOT_TRAINING_APPROVED',finding_refs:[],
      })),
      global_findings:[],unmapped_finding_refs:[],training_authorized:false,production_release_allowed:false,
      annotation_review_basis:'OPERATOR_ATTESTATION_NOT_INDEPENDENT_TRUTH',required_dataset_validation:[],
      claim_boundary:'Synthetic readiness is not product quality classification or training authorization.',receipt_sha256:digest('6'),
    };
    window.__cycle = {
      schema_version:'visiondata-gate.learning-cycle.v1', cycle_id:'cycle-test',
      workspace_id:'workspace-test',project_id:'project-test',status:'AWAITING_REVIEW',revision:0,
      created_by:'synthetic-reviewer',created_at:'2026-09-12T00:00:00Z',updated_at:'2026-09-12T00:00:00Z',
      request:{
        request_key:'synthetic-create',training:{epochs:10,learning_rate:0.2,max_wall_seconds:20},evaluation:{},
        max_rounds:3,max_total_epochs:100,max_total_wall_seconds:120,
      },
      dataset:{
        schema_version:'visiondata-gate.learning-dataset.v1',dataset_id:'dataset-test',binding,samples,
        receipt_sha256:digest('d'),split_fingerprints:{train:digest('a'),val:digest('b'),test:digest('c')},
        split_counts:{train:1,val:1,test:1},
      },
      evaluation_fingerprints:{val:digest('b'),test:digest('c')},
      initial_model_id:'model-baseline',champion_model_id:'model-baseline',approved_model_ids:['model-baseline'],
      round_ids:['run-test'],epochs_reserved:10,wall_seconds_reserved:20,events:[],receipt_sha256:digest('1'),
      production_release_allowed:false,machine_write_permitted:false,remote_execution_verified:false,
      scope:'LOCAL_SUPERVISED_REFERENCE_MODEL_SANDBOX',
    };
    window.__run = {
      schema_version:'visiondata-gate.learning-run.v1',run_id:'run-test',cycle_id:'cycle-test',project_id:'project-test',
      status:'COMPLETED',round_number:1,dataset_id:'dataset-test',dataset_receipt_sha256:digest('d'),binding,
      initial_model_id:'model-baseline',initial_model_sha256:digest('a'),model_id:'model-candidate',model_sha256:digest('b'),
      configuration:{epochs:10,learning_rate:0.2,max_wall_seconds:20},
      training:{epochs_completed:10,loss_history:[0.7,0.5],initial_loss:0.7,final_loss:0.5,elapsed_seconds:0.2},
      evaluation:{
        schema_version:'visiondata-gate.learning-evaluation.v1',split:'val',decision:'ELIGIBLE',blockers:[],
        aggregate:{candidate,baseline},categories:{'synthetic-part':{candidate,baseline}},sample_results:[evidence],
        latency:{scope:'LOCAL_CPU_OBSERVATION_ONLY',benchmark_claim:false,candidate:{sample_count:1,p95_ms:0.2},baseline:{sample_count:1,p95_ms:0.3}},
      },
      feedback:[feedback],selection:null,feedback_parent_run_id:null,responds_to_feedback_ids:[],
      production_release_allowed:false,remote_execution_verified:false,receipt_sha256:digest('4'),
    };
    if (secondFeedback) {
      window.__run.feedback.push({
        ...structuredClone(feedback), feedback_id:'feedback-second',
        evidence:{...structuredClone(evidence),sample_id:'sample-val-second'},
      });
      window.__cycle.dataset.samples.push({
        ...structuredClone(samples[1]), sample_id:'sample-val-second',group_id:'group-val-second',
      });
      window.__cycle.dataset.split_counts.val += 1;
    }
    window.__reads = [];
    window.__writes = [];
    window.__visualReads = [];
    window.__operationReads = [];
  },{secondFeedback});
  await page.addStyleTag({content:bundle.css});
  await page.addScriptTag({content:bundle.js});
  await page.getByRole('heading',{name:'数据处置与学习闭环',exact:true}).waitFor();
  await page.getByTestId('cycle-cycle-test').waitFor();
  if (selectCycle) {
    await page.getByTestId('cycle-cycle-test').click();
    await page.getByLabel('反馈分类 feedback-test',{exact:true}).waitFor();
  }
  return {page,errors};
}

async function fillReview(page,feedbackId = 'feedback-test') {
  await page.getByLabel('反馈分类 ' + feedbackId,{exact:true}).selectOption('HARD_SAMPLE');
  await page.getByLabel('复核说明 ' + feedbackId,{exact:true}).fill('Synthetic human review: collect similar training examples; keep held-out data fixed.');
  await page.getByLabel('确认复核 ' + feedbackId,{exact:true}).check();
}

async function waitForFeedbackWrites(page,count) {
  await page.waitForFunction(expected => window.__writes.filter(item => item.operation === 'feedback').length === expected,count);
}

test('current scope automatically loads cycle and run evidence without mutation', async () => {
  const {page,errors} = await scenario();
  try {
    const reads = await page.evaluate(() => window.__reads);
    assert.ok(reads.some(item => item.operation === 'list' && item.scope.projectId === 'project-test'));
    assert.ok(reads.some(item => item.operation === 'cycle' && item.id === 'cycle-test'));
    assert.ok(reads.some(item => item.operation === 'run' && item.id === 'run-test'));
    assert.equal(await page.getByLabel('反馈分类 feedback-test',{exact:true}).inputValue(),'');
    assert.equal(await page.getByRole('button',{name:'保存反馈分流',exact:true}).isDisabled(),true);
    assert.deepEqual(await page.evaluate(() => window.__writes),[]);
    assert.deepEqual(errors,[]);
    await page.screenshot({path:path.join(root,'output/playwright/learning-loop-workbench.png'),fullPage:true});
  } finally { await page.close(); }
});

test('feedback needs explicit human review and never ingests held-out validation data', async () => {
  const {page,errors} = await scenario();
  try {
    const save = page.getByRole('button',{name:'保存反馈分流',exact:true});
    await page.getByLabel('反馈分类 feedback-test',{exact:true}).selectOption('HARD_SAMPLE');
    await page.getByLabel('复核说明 feedback-test',{exact:true}).fill('Synthetic reviewed hard sample: collect new similar training images.');
    assert.equal(await save.isDisabled(),true);
    assert.deepEqual(await page.evaluate(() => window.__writes),[]);
    await page.getByLabel('确认复核 feedback-test',{exact:true}).check();
    await save.click();
    await waitForFeedbackWrites(page,1);
    await page.waitForFunction(() => window.__reads.some(item => item.operation === 'run' && item.afterWrites === 1));
    const result = await page.evaluate(() => ({writes:window.__writes,cycle:window.__cycle,run:window.__run}));
    assert.equal(result.writes[0].request.expected_cycle_sha256,'1'.repeat(64));
    assert.equal(result.writes[0].request.operator_attests_reviewed,true);
    assert.equal(result.writes[0].request.classification,'HARD_SAMPLE');
    assert.equal(result.writes[0].scope.projectId,'project-test');
    assert.equal(result.cycle.dataset.samples.find(item => item.sample_id === 'sample-val').split,'val');
    assert.equal(result.run.feedback[0].training_ingestion_allowed,false);
    assert.equal(result.run.feedback[0].status,'TRIAGED_NOT_AUTO_INGESTED');
    assert.equal(result.run.feedback[0].next_action,'COLLECT_SIMILAR_TRAINING_EXAMPLES');
    assert.deepEqual(errors,[]);
  } finally { await page.close(); }
});

test('each subsequent feedback write binds to the refreshed cycle receipt', async () => {
  const {page,errors} = await scenario({secondFeedback:true});
  try {
    await fillReview(page);
    await page.getByRole('button',{name:'保存反馈分流',exact:true}).first().click();
    await waitForFeedbackWrites(page,1);
    await page.waitForFunction(() => window.__reads.some(item => item.operation === 'run' && item.afterWrites === 1));
    await fillReview(page,'feedback-second');
    const buttons = page.getByRole('button',{name:'保存反馈分流',exact:true});
    for (let index = 0; index < await buttons.count(); index += 1) {
      if (await buttons.nth(index).isEnabled()) { await buttons.nth(index).click(); break; }
    }
    await waitForFeedbackWrites(page,2);
    const writes = await page.evaluate(() => window.__writes);
    assert.equal(writes[0].request.expected_cycle_sha256,'1'.repeat(64));
    assert.equal(writes[1].request.expected_cycle_sha256,'2'.repeat(64));
    assert.notEqual(writes[0].request.request_key,writes[1].request.request_key);
    assert.deepEqual(errors,[]);
  } finally { await page.close(); }
});

test('unknown persisted feedback stays locked because matching fields are not request-key evidence', async () => {
  const {page,errors} = await scenario();
  try {
    await fillReview(page);
    await page.evaluate(() => { window.__unknownWrite = 'persisted'; });
    await page.getByRole('button',{name:'保存反馈分流',exact:true}).click();
    await page.getByText('写入结果待对账',{exact:false}).first().waitFor();
    assert.equal(await page.getByRole('button',{name:'保存反馈分流',exact:true}).isDisabled(),true);
    await page.getByRole('button',{name:'仅 GET 对账',exact:true}).click();
    await page.waitForFunction(() => window.__reads.some(item => item.operation === 'run' && item.afterWrites === 1));
    assert.equal(await page.getByRole('button',{name:'仅 GET 对账',exact:true}).isVisible(),true);
    const save = page.getByRole('button',{name:'保存反馈分流',exact:true});
    if (await save.count()) assert.equal(await save.isDisabled(),true);
    assert.equal((await page.evaluate(() => window.__writes)).length,1);
    assert.equal(await page.evaluate(() => window.__cycle.dataset.samples.find(item => item.sample_id === 'sample-val').split),'val');
    assert.deepEqual(errors,[]);
  } finally { await page.close(); }
});

test('unknown write remains locked when successful GET has no matching receipt evidence', async () => {
  const {page,errors} = await scenario();
  try {
    await fillReview(page);
    await page.evaluate(() => { window.__unknownWrite = 'unpersisted'; });
    await page.getByRole('button',{name:'保存反馈分流',exact:true}).click();
    const reconcile = page.getByRole('button',{name:'仅 GET 对账',exact:true});
    await reconcile.waitFor();
    await reconcile.click();
    await page.waitForFunction(() => window.__reads.some(item => item.operation === 'run' && item.afterWrites === 1));
    assert.equal(await reconcile.isVisible(),true);
    assert.equal(await page.getByRole('button',{name:'保存反馈分流',exact:true}).isDisabled(),true);
    const beforeRefresh = await page.evaluate(() => window.__reads.filter(item => item.operation === 'run').length);
    const refresh = page.getByRole('button',{name:'刷新周期与反馈',exact:true});
    if (await refresh.count() && await refresh.isEnabled()) await refresh.click();
    else await reconcile.click();
    await page.waitForFunction(count => window.__reads.filter(item => item.operation === 'run').length > count,beforeRefresh);
    assert.equal(await reconcile.isVisible(),true);
    assert.equal(await page.getByRole('button',{name:'保存反馈分流',exact:true}).isDisabled(),true);
    assert.equal((await page.evaluate(() => window.__writes)).length,1);
    assert.deepEqual(errors,[]);
  } finally { await page.close(); }
});

test('failed refresh marks previous evidence STALE_HOLD and blocks prepared writes', async () => {
  const {page,errors} = await scenario();
  try {
    await fillReview(page);
    assert.equal(await page.getByRole('button',{name:'保存反馈分流',exact:true}).isEnabled(),true);
    await page.evaluate(() => { window.__readFailure = true; });
    await page.getByRole('button',{name:'刷新周期与反馈',exact:true}).click();
    await page.getByText('STALE_HOLD',{exact:false}).first().waitFor();
    const save = page.getByRole('button',{name:'保存反馈分流',exact:true});
    if (await save.count()) assert.equal(await save.isDisabled(),true);
    assert.deepEqual(await page.evaluate(() => window.__writes),[]);
    assert.deepEqual(errors,[]);
  } finally { await page.close(); }
});

test('scope change hides previous cycle, sample and unsaved review before the next read completes', async () => {
  const {page,errors} = await scenario();
  try {
    await fillReview(page);
    await page.evaluate(() => {
      window.__holdOtherProject = true;
      window.__changeScope('workspace-other','project-other');
    });
    await page.waitForFunction(() => window.__reads.some(item => item.operation === 'list' && item.scope.projectId === 'project-other'));
    assert.equal(await page.getByTestId('cycle-cycle-test').count(),0);
    assert.equal(await page.getByLabel('反馈分类 feedback-test',{exact:true}).count(),0);
    assert.equal(await page.getByText('sample-val',{exact:true}).count(),0);
    assert.deepEqual(await page.evaluate(() => window.__writes),[]);
    await page.evaluate(() => window.__releaseOtherProject?.());
    assert.deepEqual(errors,[]);
  } finally { await page.close(); }
});

test('frozen preview is lazy and refuses source mismatch before loading any image or mask', async () => {
  const {page,errors} = await scenario();
  try {
    assert.deepEqual(await page.evaluate(() => window.__visualReads),[]);
    assert.equal(await page.getByRole('img').count(),0);
    await page.evaluate(() => { window.__visualSourceMismatch = true; });
    const open = page.getByRole('button',{name:'查看本轮冻结图与标注',exact:true});
    await open.click();
    await page.getByRole('alert').filter({hasText:'冻结视觉证据与本轮来源不一致，已拒绝显示。'}).waitFor();
    assert.deepEqual(await page.evaluate(() => window.__visualReads),[{operation:'manifest',taskId:'task-test'}]);
    assert.equal(await page.getByRole('img').count(),0);
    assert.deepEqual(await page.evaluate(() => window.__writes),[]);

    await page.evaluate(() => { window.__visualSourceMismatch = false; });
    await open.click();
    await page.getByRole('img',{name:'sample-val 本轮冻结原图预览',exact:true}).waitFor();
    await page.getByRole('img',{name:'sample-val 本轮冻结标注掩膜',exact:true}).waitFor();
    assert.deepEqual(await page.evaluate(() => window.__visualReads),[
      {operation:'manifest',taskId:'task-test'},
      {operation:'manifest',taskId:'task-test'},
      {operation:'preview',sampleId:'sample-val'},
      {operation:'mask',sampleId:'sample-val'},
    ]);
    await page.evaluate(() => { window.__visualSourceMismatch = true; });
    await open.click();
    await page.getByRole('alert').filter({hasText:'冻结视觉证据与本轮来源不一致，已拒绝显示。'}).waitFor();
    assert.equal(await page.getByRole('img').count(),0);
    const visualReads = await page.evaluate(() => window.__visualReads);
    assert.equal(visualReads.filter(item => item.operation === 'manifest').length,3);
    assert.equal(visualReads.filter(item => item.operation === 'preview').length,1);
    assert.equal(visualReads.filter(item => item.operation === 'mask').length,1);
    assert.deepEqual(await page.evaluate(() => window.__writes),[]);
    assert.deepEqual(errors,[]);
  } finally { await page.close(); }
});

test('same-scope parent rerender preserves unfinished human review without rereading or writing', async () => {
  const {page,errors} = await scenario();
  try {
    await fillReview(page);
    const beforeReads = await page.evaluate(() => window.__reads.length);
    const beforeNote = await page.getByLabel('复核说明 feedback-test',{exact:true}).inputValue();
    await page.evaluate(() => window.__rerenderSameScope());
    await page.waitForFunction(() => window.__renderVersion === 1);
    assert.equal(await page.getByLabel('反馈分类 feedback-test',{exact:true}).inputValue(),'HARD_SAMPLE');
    assert.equal(await page.getByLabel('复核说明 feedback-test',{exact:true}).inputValue(),beforeNote);
    assert.equal(await page.getByLabel('确认复核 feedback-test',{exact:true}).isChecked(),true);
    assert.equal(await page.getByRole('button',{name:'保存反馈分流',exact:true}).isEnabled(),true);
    assert.equal(await page.evaluate(() => window.__reads.length),beforeReads);
    assert.deepEqual(await page.evaluate(() => window.__writes),[]);
    assert.deepEqual(errors,[]);
  } finally { await page.close(); }
});

test('unknown write identity survives closing the page and keeps a new same-context page read-only', async () => {
  const context = await browser.newContext();
  try {
    const first = await scenario({context});
    await fillReview(first.page);
    await first.page.evaluate(() => { window.__unknownWrite = 'unpersisted'; });
    await first.page.getByRole('button',{name:'保存反馈分流',exact:true}).click();
    await first.page.getByText('写入结果待对账',{exact:false}).first().waitFor();
    const storedLock = await first.page.evaluate(() => localStorage.getItem('learning:pending:workspace-test:project-test'));
    assert.equal(JSON.parse(storedLock).operation,'feedback');
    assert.equal((await first.page.evaluate(() => window.__writes)).length,1);
    assert.deepEqual(first.errors,[]);
    await first.page.close();

    const reopened = await scenario({context});
    await reopened.page.getByText('写入结果待对账',{exact:false}).first().waitFor();
    assert.equal(await reopened.page.getByLabel('反馈分类 feedback-test',{exact:true}).isDisabled(),true);
    assert.equal(await reopened.page.getByRole('button',{name:'保存反馈分流',exact:true}).isDisabled(),true);
    assert.equal(await reopened.page.evaluate(() => localStorage.getItem('learning:pending:workspace-test:project-test')),storedLock);
    assert.deepEqual(await reopened.page.evaluate(() => window.__writes),[]);
    const beforeReads = await reopened.page.evaluate(() => window.__reads.length);
    await reopened.page.getByRole('button',{name:'仅 GET 对账',exact:true}).click();
    await reopened.page.waitForFunction(count => window.__reads.length > count,beforeReads);
    assert.equal(await reopened.page.getByRole('button',{name:'保存反馈分流',exact:true}).isDisabled(),true);
    assert.equal(await reopened.page.evaluate(() => localStorage.getItem('learning:pending:workspace-test:project-test')),storedLock);
    assert.deepEqual(await reopened.page.evaluate(() => window.__writes),[]);
    assert.deepEqual(reopened.errors,[]);
  } finally { await context.close(); }
});

test('readiness filters show admission evidence without converting it into good or bad product labels', async () => {
  const {page,errors} = await scenario({selectCycle:false});
  try {
    await page.evaluate(() => {
      window.__testPreflight.eligibility = 'HOLD';
      window.__testPreflight.blockers = ['SYNTHETIC_BATCH_HOLD'];
      window.__testReadiness.preflight_eligibility = 'HOLD';
      window.__testReadiness.blockers = ['SYNTHETIC_BATCH_HOLD'];
      window.__testReadiness.members[1].readiness_state = 'NEEDS_ATTENTION';
      window.__testReadiness.members[1].finding_refs = [{finding_id:'finding-val',code:'SYNTHETIC_ANNOTATION_REVIEW',severity:'medium',finding_sha256:'7'.repeat(64)}];
      window.__testReadiness.members[2].readiness_state = 'UNVERIFIED_TOOL_FAILURE';
      window.__testReadiness.global_findings = [{finding_id:'finding-batch',code:'SYNTHETIC_BATCH_HOLD',severity:'high',finding_sha256:'8'.repeat(64)}];
    });
    await page.locator('.learning-input').getByRole('combobox').selectOption('task-test');
    await page.getByRole('button',{name:'核验来源与样本',exact:true}).click();
    const table = page.locator('.learning-readiness');
    await table.getByRole('heading',{name:'这批数据，分别需要做什么？',exact:true}).waitFor();
    assert.match(await table.innerText(),/这是用途准入状态，不是产品良品 \/ 不良品分类/);
    await table.getByRole('button',{name:'检查通过',exact:true}).click();
    assert.equal(await table.getByRole('link',{name:'sample-train',exact:true}).count(),1);
    assert.equal(await table.getByRole('link',{name:'sample-val',exact:true}).count(),0);
    await table.getByRole('button',{name:'需要处理',exact:true}).click();
    assert.equal(await table.getByRole('link',{name:'sample-val',exact:true}).count(),1);
    assert.match(await table.innerText(),/SYNTHETIC_ANNOTATION_REVIEW/);
    await table.getByRole('button',{name:'待补证 / 批次阻断',exact:true}).click();
    assert.equal(await table.getByRole('link',{name:'sample-test',exact:true}).count(),1);
    assert.match(await table.innerText(),/不作好坏判断/);
    assert.match(await table.innerText(),/不能把它们计作某几张坏图片/);
    assert.equal(await page.getByRole('button',{name:'创建学习周期（不训练）',exact:true}).count(),0);
    assert.deepEqual(await page.evaluate(() => window.__writes),[]);
    assert.deepEqual(errors,[]);
  } finally { await page.close(); }
});

test('normal negative sample requires named explicit review and binds current image and annotation hashes before create', async () => {
  const {page,errors} = await scenario({selectCycle:false});
  try {
    await page.evaluate(() => {
      window.__allowCreate = true;
      const item = window.__frozenManifest.items.find(row => row.sample_id === 'sample-train');
      item.mask_sha256 = null;
      item.annotation_count = 0;
      const member = window.__testReadiness.members.find(row => row.sample_id === 'sample-train');
      member.mask_available = false;
      member.readiness_state = 'MASK_REQUIRED_FOR_REFERENCE_TRAINER';
    });
    await page.locator('.learning-input').getByRole('combobox').selectOption('task-test');
    await page.getByRole('button',{name:'核验来源与样本',exact:true}).click();
    await page.getByLabel('采集组 sample-train',{exact:true}).waitFor();
    for (const split of ['train','val','test']) await page.getByLabel('采集组 sample-' + split,{exact:true}).fill('actual-group-' + split);
    await page.getByLabel('数据复核与训练授权说明',{exact:true}).fill('Synthetic reviewed groups and authorization for freezing only, without training.');
    await page.getByRole('checkbox',{name:/我确认采集组及标签经过复核/}).check();
    const create = page.getByRole('button',{name:'创建学习周期（不训练）',exact:true});
    assert.equal(await create.isDisabled(),true);
    assert.deepEqual(await page.evaluate(() => window.__writes),[]);
    await page.getByLabel('具名复核人',{exact:true}).fill('Synthetic Reviewer');
    await page.getByLabel('无前景缺陷的复核依据',{exact:true}).fill('Manually reviewed the frozen normal sample and its empty annotation; no target foreground is present.');
    assert.equal(await create.isDisabled(),true);
    await page.getByRole('checkbox',{name:'我确认此冻结版本无目标前景缺陷，允许生成全零掩膜副本。',exact:true}).check();
    await create.click();
    await page.waitForFunction(() => window.__writes.length === 1);
    const result = await page.evaluate(() => ({write:window.__writes[0],item:window.__frozenManifest.items[0]}));
    assert.equal(result.write.operation,'create');
    assert.equal(result.write.taskId,'task-test');
    assert.equal(result.write.request.expected_preflight_sha256,'e'.repeat(64));
    assert.deepEqual(Object.keys(result.write.request.normal_mask_attestations),['sample-train']);
    assert.deepEqual(result.write.request.normal_mask_attestations['sample-train'],{
      reviewer_name:'Synthetic Reviewer',
      review_note:'Manually reviewed the frozen normal sample and its empty annotation; no target foreground is present.',
      expected_asset_sha256:result.item.source_sha256,
      expected_annotation_revision:result.item.annotation_revision,
      expected_annotation_sha256:result.item.annotation_document_sha256,
      operator_attests_no_foreground:true,
    });
    assert.deepEqual(result.write.request.groups,{'sample-train':'actual-group-train','sample-val':'actual-group-val','sample-test':'actual-group-test'});
    assert.deepEqual(errors,[]);
  } finally { await page.close(); }
});

test('exact request GET returning PENDING never unlocks or replays an unknown feedback write', async () => {
  const {page,errors} = await scenario();
  try {
    await fillReview(page);
    await page.evaluate(() => { window.__unknownWrite = 'unpersisted'; window.__operationStatus = 'PENDING'; });
    await page.getByRole('button',{name:'保存反馈分流',exact:true}).click();
    await page.getByRole('button',{name:'仅 GET 对账',exact:true}).click();
    await page.getByText('原请求已找到，服务端仍在执行。',{exact:false}).waitFor();
    const result = await page.evaluate(() => ({writes:window.__writes,lookups:window.__operationReads}));
    assert.equal(result.writes.length,1);
    assert.deepEqual(result.lookups,[{
      scope:{workspaceId:'workspace-test',projectId:'project-test'},operation:'feedback',
      key:result.writes[0].request.request_key,targetId:'feedback-test',
    }]);
    assert.equal(await page.getByRole('button',{name:'保存反馈分流',exact:true}).isDisabled(),true);
    assert.notEqual(await page.evaluate(() => localStorage.getItem('learning:pending:workspace-test:project-test')),null);
    assert.deepEqual(errors,[]);
  } finally { await page.close(); }
});

test('exact request GET result clears the unknown lock without POST and requires another fresh read before action', async () => {
  const {page,errors} = await scenario({secondFeedback:true});
  try {
    await fillReview(page);
    await page.evaluate(() => { window.__unknownWrite = 'persisted'; window.__operationStatus = 'RESULT_AVAILABLE'; });
    await page.getByRole('button',{name:'保存反馈分流',exact:true}).first().click();
    await page.getByRole('button',{name:'仅 GET 对账',exact:true}).click();
    await page.getByText('已通过 GET 找到原请求回执，未重放写入。',{exact:false}).waitFor();
    assert.equal(await page.getByLabel('反馈分类 feedback-second',{exact:true}).isDisabled(),true);
    assert.equal(await page.evaluate(() => localStorage.getItem('learning:pending:workspace-test:project-test')),null);
    const result = await page.evaluate(() => ({writes:window.__writes,lookups:window.__operationReads}));
    assert.equal(result.writes.length,1);
    assert.deepEqual(result.lookups,[{
      scope:{workspaceId:'workspace-test',projectId:'project-test'},operation:'feedback',
      key:result.writes[0].request.request_key,targetId:'feedback-test',
    }]);
    await page.getByRole('button',{name:'刷新周期与反馈',exact:true}).click();
    await page.waitForFunction(() => !document.querySelector('select[aria-label="反馈分类 feedback-second"]')?.disabled && !document.querySelector('select[aria-label="反馈分类 feedback-second"]')?.closest('fieldset')?.disabled);
    assert.equal(await page.getByLabel('反馈分类 feedback-second',{exact:true}).isEnabled(),true);
    assert.equal((await page.evaluate(() => window.__writes)).length,1);
    assert.deepEqual(errors,[]);
  } finally { await page.close(); }
});
