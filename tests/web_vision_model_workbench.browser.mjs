/** Real visual-model forms + real JCS/API validators; transport/data/accounts are isolated synthetic doubles. */
import assert from 'node:assert/strict';
import { before, after, test } from 'node:test';
import { createRequire } from 'node:module';
import { existsSync, mkdirSync, readFileSync } from 'node:fs';
import { fileURLToPath, pathToFileURL } from 'node:url';
import path from 'node:path';
import { scope, sha, model, runtime, dataset, run, manifest, capabilities, poolProjection, poolDataset, feedbackFixture, newDetectionDataset } from './web_vision_model_fixtures.mjs';
const root = fileURLToPath(new URL('..', import.meta.url)), webRoot = path.join(root, 'web');
const require = createRequire(path.join(webRoot, 'package.json'));
const { build, transformWithOxc } = await import(pathToFileURL(require.resolve('vite')).href);
const cached = 'D:/Users/living/.npm-cache/_npx/31e32ef8478fbf80/node_modules/playwright-core/index.mjs';
const { chromium } = await import(pathToFileURL(process.env.VDG_PLAYWRIGHT_MODULE || (existsSync(cached) ? cached : require.resolve('playwright'))).href);
let browser, bundle, css;
const mock = `
import {canonicalizeJcs,sha256HexUtf8} from '/src/data/jcs.ts';
export class OperatorApiError extends Error{constructor(code,message,status){super(message);this.code=code;this.status=status;}}
const hash=v=>sha256HexUtf8(canonicalizeJcs(v));
const sealed=async v=>{const b={...v};delete b.receipt_sha256;return {...b,receipt_sha256:await hash(b)};};
const response=async v=>{const s=await sealed(v);return new Response(JSON.stringify(s),{headers:{'Content-Type':'application/json','ETag':'"'+s.receipt_sha256+'"','X-Content-SHA256':s.receipt_sha256}});};
export async function operatorFetch(path,init={}){
 const method=init.method||'GET',request=init.body?JSON.parse(init.body):null;
 window.__calls.push({path,method,request});
 if(window.__unsupported)throw new OperatorApiError('HTTP_404','C:/private/backend/path',404);
 if(method==='GET'&&path==='/v1/data-pools/pool_test')return response(window.__db.poolProjection);
 const prefix='/v1/projects/'+window.__scope.projectId+'/';
 if(!path.startsWith(prefix))throw new OperatorApiError('HTTP_404','wrong project',404);
 const suffix=decodeURIComponent(path.slice(prefix.length)),db=window.__db;
 if(method==='GET'){
   if(suffix==='vision-capabilities')return response(db.capabilities);
   if(suffix.startsWith('vision-training-runs/')&&suffix.endsWith('/feedback')){const id=suffix.split('/')[1];return response({schema_version:'visiondata-gate.vision-list.v1',project_id:window.__scope.projectId,run_id:id,items:(db.feedback||[]).filter(item=>item.run_id===id)});}
   for(const [route,key] of Object.entries({'vision-models':'models','vision-runtimes':'runtimes','vision-datasets':'datasets','vision-training-runs':'runs'})){
    if(suffix===route)return response({schema_version:'visiondata-gate.vision-list.v1',project_id:window.__scope.projectId,items:db[key]});
    if(suffix.startsWith(route+'/')){const item=db[key].find(v=>v.resource_id===suffix.slice(route.length+1));if(item)return response(item);}
   }
   if(suffix.startsWith('vision-operations/')){const [,operation,request_key]=suffix.split('/');const item=window.__ledger[operation+':'+request_key];if(!item)throw new OperatorApiError('HTTP_404','not found',404);
    return response({schema_version:'visiondata-gate.vision-operation.v1',project_id:window.__scope.projectId,operation,request_key,resource_id:item.resource_id,resource:item,auto_replayed:false});}
   throw new OperatorApiError('HTTP_404','not found',404);
 }
 let resource,operation;
 if(suffix==='vision-models'){operation='register_model';resource=await sealed({...db.modelTemplate,resource_id:'vision_model_new',model_id:'vision_model_new',display_name:request.display_name,weights_sha256:request.expected_weights_sha256,task_type:request.task_type});db.models.push(resource);}
 else if(suffix==='vision-runtimes'){operation='register_runtime';resource=await sealed({...db.runtimeTemplate,resource_id:'vision_runtime_new',runtime_id:'vision_runtime_new',display_name:request.display_name,executable_sha256:request.expected_executable_sha256,probe:{...db.runtimeTemplate.probe,executable_sha256:request.expected_executable_sha256}});db.runtimes.push(resource);}
 else if(suffix.startsWith('vision-runtimes/')&&suffix.endsWith('/probe')){const id=suffix.split('/')[1];operation='probe_runtime:'+id;const index=db.runtimes.findIndex(v=>v.resource_id===id);resource=await sealed({...db.runtimes[index],probe:{...db.runtimes[index].probe,import_status:request.import_check?'PASSED':'NOT_RUN'}});db.runtimes[index]=resource;}
 else if(suffix==='vision-datasets'){operation='register_dataset';resource=db.datasetTemplate;db.datasets=[resource];}
 else if(suffix==='vision-datasets/from-data-pool'){operation='register_pool_dataset';resource=db.poolDataset;db.datasets=[resource];}
 else if(suffix==='vision-training-runs'){operation='create_training_run';resource=await sealed({...db.runTemplate,resource_id:'vision_run_created_test',run_id:'vision_run_created_test',status:'QUEUED',result:null,candidate_model_id:null,authorization_sha256:await hash(request),runtime_id:request.runtime_id,runtime_sha256:request.expected_runtime_sha256,dataset_id:request.dataset_id,dataset_receipt_sha256:request.expected_dataset_receipt_sha256,initialization:request.initialization,initial_model_id:request.initial_model_id,training:request.training,responds_to_feedback_ids:request.responds_to_feedback_ids,feedback_ids:[],feedback_status:'NOT_EVALUATED'});db.runs=[...db.runs.filter(item=>item.run_id!==resource.run_id),resource];}
 else if(suffix.startsWith('vision-training-runs/')&&suffix.endsWith('/triage')){const id=suffix.split('/')[3];operation='triage_feedback:'+id;const index=db.feedback.findIndex(item=>item.feedback_id===id);resource=await sealed({...db.feedback[index],status:'TRIAGED_FOR_REVIEW',classification:request.classification});db.feedback[index]=resource;}
 else if(suffix.startsWith('vision-training-runs/')){const [,id,action]=suffix.split('/');operation=action+':'+id;const index=db.runs.findIndex(v=>v.resource_id===id);const current=db.runs[index];
   resource=await sealed({...current,...(action==='selection'?{selection:request.action}:action==='recover'?{status:'INTERRUPTED_HOLD',cancel_requested:true}:{cancel_requested:true})});db.runs[index]=resource;}
 else throw new OperatorApiError('HTTP_404','unknown POST',404);
 window.__ledger[operation+':'+request.request_key]=resource;
 if(window.__unknownPost){window.__unknownPost=false;throw new OperatorApiError('HTTP_503','C:/private/raw-weights.pt',503);}
 return response(resource);
}
`;
const entry = `
import {createRoot} from 'react-dom/client';import {MemoryRouter} from 'react-router-dom';
import {VisionModelWorkbench} from '/src/components/VisionModelWorkbench.tsx';
import * as identity from '/src/identitySession.ts';
const root=createRoot(document.getElementById('root'));window.__identity=identity;
window.__mount=()=>root.render(<MemoryRouter key={window.__scope.actorId+window.__scope.projectId} initialEntries={[window.location.pathname+window.location.search]}><VisionModelWorkbench/></MemoryRouter>);
identity.setIdentitySession({user_id:window.__scope.actorId,display_name:'Synthetic operator',login_name:'vision.test',email:null,created_at:'2026-09-13T00:00:00Z',platform_role:'USER',status:'ACTIVE'},'synthetic-token-only-000000000000000000000000');window.__mount();
`;
before(async () => {
  const result = await build({ root: webRoot, configFile: false, logLevel: 'error', define: { 'process.env.NODE_ENV': JSON.stringify('production') },
    build: { write: false, minify: false, lib: { entry: '/__vision_workbench_test.tsx', name: 'VisionTest', formats: ['iife'] } },
    plugins: [{ name: 'isolated-vision-tests', enforce: 'pre', resolveId(id) {
      if (id.endsWith('__vision_workbench_test.tsx')) return '\0vision-entry.tsx';
      if (id.endsWith('/ProductContext')) return '\0vision-context';
      if (id === './api' || id.endsWith('/data/api')) return '\0vision-transport';
    }, load(id) { if (id === '\0vision-entry.tsx') return entry; if (id === '\0vision-context') return 'export function useProduct(){return window.__product;}'; if (id === '\0vision-transport') return mock; },
    transform(code, id) { if (id === '\0vision-entry.tsx') return transformWithOxc(code, id.slice(1), { lang: 'tsx', jsx: { runtime: 'automatic' } }); } }],
  });
  const output = (Array.isArray(result) ? result[0] : result).output;
  bundle = output.find(item => item.type === 'chunk').code;
  css = readFileSync(path.join(webRoot, 'src/styles/tokens.css'), 'utf8') + output.filter(item => item.type === 'asset' && item.fileName.endsWith('.css')).map(item => item.source).join('\n');
  const executablePath = process.env.VDG_BROWSER_EXECUTABLE || ['C:/Program Files (x86)/Microsoft/Edge/Application/msedge.exe', 'C:/Program Files/Google/Chrome/Application/chrome.exe'].find(existsSync);
  browser = await chromium.launch({ headless: true, ...(executablePath ? { executablePath } : {}) });
});
after(async () => { await browser?.close(); });
async function openPage({ unknown = false, unsupported = false, pending = null, query = '', width = 1400 } = {}) {
  const page = await browser.newPage({ viewport: { width, height: 1100 } }); page.setDefaultTimeout(7000);
  await page.route('http://localhost:43441/**', route => route.fulfill({ body: '<!doctype html><html><head></head><body><div id="root"></div></body></html>', contentType: 'text/html' }));
  await page.goto(`http://localhost:43441/models?tab=vision${query}`);
  const m = await model(), r = await runtime(), d = await dataset(), tr = await run();
  await page.evaluate(({ scope, db, unknown, unsupported, pending }) => {
    window.__scope = scope; window.__db = db; window.__calls = []; window.__ledger = {}; window.__unknownPost = unknown; window.__unsupported = unsupported;
    window.__product = { activeWorkspace: { workspace_id: scope.workspaceId }, activeProject: { project_id: scope.projectId, name: '合成项目' }, registerScopeChangeGuard: () => () => {} };
    if (pending) localStorage.setItem(`vision-model:pending:${scope.actorId}:${scope.workspaceId}:${scope.projectId}`, JSON.stringify(pending));
  }, { scope, db: { models: [m], runtimes: [r], datasets: [d], runs: [], modelTemplate: m, runtimeTemplate: r, datasetTemplate: d, runTemplate: tr, capabilities: await capabilities(), poolProjection: await poolProjection(), poolDataset: await poolDataset() }, unknown, unsupported, pending });
  await page.addStyleTag({ content: `*{box-sizing:border-box}body{margin:0;background:#090c10;padding:24px}${css}` });
  await page.addScriptTag({ content: bundle });
  await page.getByRole('heading', { name: '把模型放进可复核的训练流程' }).waitFor();
  if (!unsupported) await page.getByRole('button', { name: query.includes('pool=') ? /synthetic-detection-v1/ : /Python metadata fixture/ }).waitFor();
  return page;
}
async function tab(page, name) { await page.getByRole('navigation', { name: '视觉模型流程' }).getByRole('button', { name: new RegExp(name) }).click(); }
function form(page) { return page.locator('.vision-models__form-panel form'); }
async function review(target) { await target.getByLabel('具名复核人', { exact: true }).fill('合成复核员'); await target.getByLabel('本次操作说明').fill('这是独立合成测试的具名授权说明'); }
async function checked(target, label) { await target.getByLabel(label, { exact: false }).check(); }
async function writes(page) { return page.evaluate(() => window.__calls.filter(call => call.method === 'POST')); }

test('four real stages are read-only on open, and unsupported backend holds without mock UI data', async () => {
  const page = await openPage(); try {
    assert.equal((await writes(page)).length, 0);
    await tab(page, '训练'); assert.match(await form(page).innerText(), /非预训练/);
    assert.equal(await form(page).getByRole('button', { name: '按本次授权启动 CPU 训练' }).isEnabled(), false);
    await tab(page, '数据'); assert.match(await form(page).innerText(), /验证 \/ 测试数据不会回灌训练/);
    const out = path.join(root, 'output/playwright/vision-models'); mkdirSync(out, { recursive: true });
    await page.screenshot({ path: path.join(out, 'dataset-desktop.png'), fullPage: true });
  } finally { await page.close(); }
  const offline = await openPage({ unsupported: true }); try { await offline.getByRole('alert').waitFor(); assert.match(await offline.getByRole('alert').innerText(), /HOLD/); assert.equal((await writes(offline)).length, 0); assert.equal((await offline.locator('body').innerText()).includes('C:/private'), false); } finally { await offline.close(); }
});
test('runtime registration and explicit import probe require separate attestations and never store interpreter path', async () => {
  const page = await openPage(); try {
    const target = form(page); await target.getByLabel('环境名称').fill('新合成环境'); await target.getByLabel('Python 解释器绝对路径').fill('C:/synthetic-private/python.exe'); await target.getByLabel('解释器 SHA-256').fill(sha('b')); await review(target);
    const submit = target.getByRole('button', { name: '登记并探测环境元数据' }); assert.equal(await submit.isEnabled(), false);
    await checked(target, '我确认该解释器'); await checked(target, '我授权本次执行该解释器'); await submit.click();
    await page.getByRole('button', { name: /新合成环境/ }).waitFor();
    const posts = await writes(page); assert.equal(posts.length, 1); assert.equal(posts[0].request.operator_attests_trusted_runtime, true);
    await page.getByRole('button', { name: /新合成环境/ }).click();
    const probe = page.locator('.vision-models__details form'); await review(probe); await checked(probe, '我确认此登记环境可信'); await checked(probe, '我授权本次执行环境探测'); await checked(probe, '额外授权真实导入');
    await probe.getByRole('button', { name: '执行真实库导入与 CPU 探测' }).click();
    await page.getByText('PASSED', { exact: true }).waitFor();
    const calls = await writes(page); assert.equal(calls[1].request.import_check, true);
    assert.equal(await page.evaluate(() => JSON.stringify({ ...localStorage, ...sessionStorage }).includes('synthetic-private')), false);
  } finally { await page.close(); }
});
test('dataset JSON import computes actual JCS digest and refuses category-only labels', async () => {
  const page = await openPage(); try {
    await tab(page, '数据'); const target = form(page); const bad = manifest(); delete bad.samples[0].boxes; bad.samples[0].category = 'defect';
    await target.getByLabel('检测清单 JSON').setInputFiles({ name: 'invalid.json', mimeType: 'application/json', buffer: Buffer.from(JSON.stringify(bad)) });
    await target.getByRole('alert').waitFor(); assert.equal((await writes(page)).length, 0);
    await target.getByLabel('检测清单 JSON').setInputFiles({ name: 'reviewed.json', mimeType: 'application/json', buffer: Buffer.from(JSON.stringify(manifest())) });
    await target.getByText('结构检查通过 · 尚未冻结').waitFor(); await target.getByLabel('图像源目录绝对路径').fill('C:/synthetic-private/detection'); await review(target); await checked(target, '我确认清单中的检测框');
    await target.getByRole('button', { name: '核验源文件并登记数据集' }).click();
    await page.getByRole('status').filter({ hasText: '操作已收到' }).waitFor();
    const calls = await writes(page); assert.equal(calls.length, 1); assert.equal(calls[0].request.expected_manifest_sha256, (await dataset()).dataset_receipt.manifest_sha256);
    assert.equal(await page.evaluate(() => JSON.stringify(localStorage).includes('detection')), false);
  } finally { await page.close(); }
});
test('random architecture training remains non-pretrained, then zero-metric candidate requires human sandbox selection', async () => {
  const page = await openPage(); try {
    await tab(page, '训练'); const target = form(page); await target.getByLabel('运行环境', { exact: true }).selectOption('vision_runtime_test'); await target.getByLabel('冻结数据集', { exact: true }).selectOption('vision_dataset_test'); await review(target);
    await checked(target, '我已核查 Ultralytics'); await checked(target, '我信任所选 Python'); await checked(target, '我授权按上述数据集');
    await target.getByRole('button', { name: '按本次授权启动 CPU 训练' }).click();
    await page.getByRole('button', { name: /已授权 · 等待执行/ }).waitFor(); const posts = await writes(page); assert.equal(posts.length, 1);
    assert.equal(posts[0].request.initial_model_id, null); assert.equal(posts[0].request.operator_attests_pickle_load_risk, false); assert.equal(posts[0].request.adaptation, 'OFF');
    await page.evaluate(() => { window.__db.runs = [window.__db.runTemplate]; }); await page.getByRole('button', { name: '刷新状态（仅 GET）' }).click();
    await page.getByRole('button', { name: /候选已生成/ }).click(); const detail = page.locator('.vision-models__details');
    assert.match(await detail.innerText(), /0.00000/); assert.match(await detail.innerText(), /不自动代表精度通过/);
    const selection = detail.getByRole('button', { name: '人工选用候选（仅沙箱）' }); assert.equal(await selection.isEnabled(), false);
    await review(detail); await checked(detail, '我已阅读当前运行回执'); await selection.click();
    await detail.getByText('APPROVE_SANDBOX', { exact: true }).waitFor();
    const all = await writes(page); assert.equal(all.length, 2); assert.equal(all[1].request.expected_candidate_weights_sha256, sha('f'));
  } finally { await page.close(); }
});
test('registered .pt training requires trusted-weights and distinct pickle-load checkbox', async () => {
  const page = await openPage(); try {
    await tab(page, '训练'); const target = form(page); await target.getByLabel('运行环境', { exact: true }).selectOption('vision_runtime_test'); await target.getByLabel('冻结数据集', { exact: true }).selectOption('vision_dataset_test');
    await target.getByLabel('初始化方式').selectOption('REGISTERED_WEIGHTS'); await target.getByLabel('本地初始权重').selectOption('vision_model_test'); await review(target);
    await checked(target, '我已核查 Ultralytics'); await checked(target, '我信任所选 Python'); await checked(target, '我授权按上述数据集'); await checked(target, '我确认所选权重来自可信来源');
    const submit = target.getByRole('button', { name: '按本次授权启动 CPU 训练' }); assert.equal(await submit.isEnabled(), false);
    await checked(target, '我单独确认 .pt'); await submit.click(); await page.getByRole('button', { name: /已授权 · 等待执行/ }).waitFor();
    const [call] = await writes(page); assert.equal(call.request.operator_attests_pickle_load_risk, true); assert.equal(call.request.operator_attests_trusted_weights, true); assert.equal(call.request.expected_weights_sha256, sha());
  } finally { await page.close(); }
});
test('unknown POST retains actor-scoped minimal lock, refresh cannot clear it, exact GET operation reconciles without replay', async () => {
  const page = await openPage({ unknown: true }); try {
    await tab(page, '权重'); const target = form(page); await target.getByLabel('模型名称').fill('Unknown fixture'); await target.getByLabel('权重绝对路径').fill('C:/synthetic-private/model.pt'); await target.getByLabel('权重 SHA-256').fill(sha()); await target.getByLabel('来源说明').fill('Local synthetic fixture'); await review(target);
    await checked(target, '我授权本次读取该本地权重'); await checked(target, '我已核查 AGPL-3.0'); await target.getByRole('button', { name: '只登记权重元数据' }).click();
    await page.getByText('写入结果待确认 · UNKNOWN').waitFor(); const stored = await page.evaluate(() => Object.entries(localStorage));
    assert.equal(stored.length, 1); assert.equal(stored[0][0], `vision-model:pending:${scope.actorId}:${scope.workspaceId}:${scope.projectId}`);
    const pending = JSON.parse(stored[0][1]); assert.deepEqual(Object.keys(pending).sort(), ['operation', 'requestKey']); assert.equal(pending.operation, 'register_model'); assert.equal(stored[0][1].includes('synthetic-private'), false);
    await page.getByRole('button', { name: '刷新状态（仅 GET）' }).click(); await page.getByRole('button', { name: /Unknown fixture/ }).waitFor(); assert.equal(await page.getByText('写入结果待确认 · UNKNOWN').count(), 1);
    await page.getByRole('button', { name: '使用原 request_key 仅 GET 对账' }).click(); await page.getByText('原请求已由 GET 对账确认。没有重发 POST，也没有重新训练。').waitFor();
    assert.equal((await writes(page)).length, 1); assert.equal(await page.evaluate(() => Object.keys(localStorage).length), 0);
    const reads = await page.evaluate(() => window.__calls.filter(call => call.path.includes('/vision-operations/'))); assert.equal(reads.length, 1); assert.equal(reads[0].method, 'GET'); assert.ok(reads[0].path.endsWith(`/register_model/${pending.requestKey}`));
    assert.equal((await page.locator('body').innerText()).includes('raw-weights.pt'), false);
  } finally { await page.close(); }
});
test('reopened minimal lock forbids writes until confirmed', async () => {
  const page = await openPage({ pending: { operation: 'create_training_run', requestKey: 'vision_existing_unknown_key' } });
  try {
    await tab(page, '数据');
    await page.getByText('写入结果待确认 · UNKNOWN').waitFor(); assert.equal((await writes(page)).length, 0);
    assert.equal(await form(page).getByRole('button', { name: '核验源文件并登记数据集' }).isEnabled(), false);
    await page.getByRole('button', { name: '使用原 request_key 仅 GET 对账' }).click(); await page.getByRole('alert').waitFor();
    assert.equal(await page.getByText('写入结果待确认 · UNKNOWN').count(), 1); assert.equal((await writes(page)).length, 0);
  } finally { await page.close(); }
});
test('pool bridge reads pinned current version, requires all explicit groups and posts no path or inferred boxes', async () => {
  const page = await openPage({ query: '&pool=pool_test&version=poolv_test' }); try {
    const target = page.locator('.vision-models__pool-form'); assert.equal((await writes(page)).length, 0);
    await target.getByRole('button', { name: '读取指定数据池版本（仅 GET）' }).click(); await target.getByText('poolv_test', { exact: true }).waitFor();
    await target.getByLabel('冻结类别词表').fill('defect'); await review(target);
    for (const split of ['train', 'val', 'test']) await target.getByLabel(`采集组 · ${split}_sample`).fill(`group_${split}`);
    const submit = target.getByRole('button', { name: '从已复核池版本登记检测数据集' }); assert.equal(await submit.isEnabled(), false);
    await checked(target, '我已复核固定词表'); await submit.click();
    await page.getByRole('status').filter({ hasText: '操作已收到' }).waitFor();
    const [call] = await writes(page); assert.equal(call.path, `/v1/projects/${scope.projectId}/vision-datasets/from-data-pool`);
    assert.deepEqual(Object.keys(call.request.groups).sort(), ['test_sample', 'train_sample', 'val_sample']); assert.deepEqual(call.request.normal_sample_ids, []);
    assert.equal(Object.hasOwn(call.request, 'source_root'), false); assert.equal(Object.hasOwn(call.request, 'boxes'), false);
    const out = path.join(root, 'output/playwright/vision-models'); mkdirSync(out, { recursive: true }); await page.screenshot({ path: path.join(out, 'pool-bridge-desktop.png'), fullPage: true });
  } finally { await page.close(); }
  const stale = await openPage({ query: '&pool=pool_test&version=poolv_old' }); try {
    await stale.getByRole('button', { name: '读取指定数据池版本（仅 GET）' }).click(); await stale.getByRole('alert').waitFor();
    assert.match(await stale.getByRole('alert').innerText(), /旧版本链接不会自动切换/); assert.equal((await writes(stale)).length, 0);
  } finally { await stale.close(); }
});
test('cancel and recover are explicit version-bound actions, not training retries', async () => {
  for (const action of ['cancel', 'recover']) {
    const page = await openPage(); try {
      await page.evaluate(run => { window.__db.runs = [run]; }, await run('RUNNING'));
      await page.getByRole('button', { name: '刷新状态（仅 GET）' }).click(); await tab(page, '训练'); await page.getByRole('button', { name: /CPU 训练中/ }).click();
      const detail = page.locator('.vision-models__details'); await review(detail); await checked(detail, '我已阅读当前运行回执');
      await detail.getByRole('button', { name: action === 'cancel' ? '申请取消本次训练' : '核查执行归属并记录中断' }).click();
      await page.getByRole('status').filter({ hasText: '操作已收到' }).waitFor();
      const posts = await writes(page); assert.equal(posts.length, 1); assert.ok(posts[0].path.endsWith(`/vision_run_test/${action}`)); assert.equal(posts[0].request.expected_run_sha256, (await run('RUNNING')).receipt_sha256);
    } finally { await page.close(); }
  }
});
test('account remount clears private form inputs and does not inherit another actor pending lock', async () => {
  const pending = { operation: 'register_model', requestKey: 'vision_previous_actor_request' };
  const page = await openPage({ pending }); try {
    await page.getByText('写入结果待确认 · UNKNOWN').waitFor();
    await page.evaluate(() => {
      window.__scope.actorId = 'usr_vision_other';
      window.__identity.setIdentitySession({ user_id: 'usr_vision_other', display_name: 'Other synthetic user', login_name: 'vision.other', email: null, created_at: '2026-09-13T00:00:00Z', platform_role: 'USER', status: 'ACTIVE' }, 'synthetic-other-token-only-0000000000000000000000');
      window.__mount();
    });
    await page.getByRole('button', { name: /Python metadata fixture/ }).waitFor(); await tab(page, '权重');
    assert.equal(await page.getByText('写入结果待确认 · UNKNOWN').count(), 0); assert.equal(await form(page).getByLabel('权重绝对路径').inputValue(), '');
    const keys = await page.evaluate(() => Object.keys(localStorage)); assert.deepEqual(keys, [`vision-model:pending:${scope.actorId}:${scope.workspaceId}:${scope.projectId}`]);
    const text = await page.locator('body').innerText(); assert.equal(text.includes('synthetic-other-token'), false); assert.equal((await writes(page)).length, 0);
  } finally { await page.close(); }
});
test('a held same-account project Web Lock prevents a second tab mutation before transport', async () => {
  const page = await openPage(); try {
    await tab(page, '权重'); const target = form(page); await target.getByLabel('模型名称').fill('Competing fixture'); await target.getByLabel('权重绝对路径').fill('C:/synthetic-private/model.pt'); await target.getByLabel('权重 SHA-256').fill(sha()); await target.getByLabel('来源说明').fill('Local synthetic source'); await review(target);
    await checked(target, '我授权本次读取该本地权重'); await checked(target, '我已核查 AGPL-3.0');
    await page.evaluate(() => { void navigator.locks.request(`vision-model:pending:${window.__scope.actorId}:${window.__scope.workspaceId}:${window.__scope.projectId}`, () => new Promise(resolve => { window.__releaseVisionLock = resolve; })); });
    await page.waitForFunction(() => typeof window.__releaseVisionLock === 'function'); await target.getByRole('button', { name: '只登记权重元数据' }).click();
    await page.getByRole('alert').waitFor(); assert.match(await page.getByRole('alert').innerText(), /另一个页面正在写入/); assert.equal((await writes(page)).length, 0);
    await page.evaluate(() => window.__releaseVisionLock());
  } finally { await page.close(); }
});
test('validation disagreements require human triage and next-run association needs new data without val ingestion', async () => {
  const fixture = await feedbackFixture(), nextDataset = await newDetectionDataset(); const page = await openPage(); try {
    await page.evaluate(({ fixture, nextDataset }) => { window.__db.runs = [fixture.run]; window.__db.feedback = [fixture.feedback]; window.__db.datasets.push(nextDataset); }, { fixture, nextDataset });
    await page.getByRole('button', { name: '刷新状态（仅 GET）' }).click(); await tab(page, '训练'); await page.getByRole('button', { name: /候选已生成/ }).click();
    await page.getByRole('button', { name: '读取本轮验证反馈（仅 GET）' }).click(); const card = page.locator('.vision-models__feedback-card'); await card.getByText('val_sample · val').waitFor();
    assert.match(await card.innerText(), /漏检候选 FN/); assert.match(await card.innerText(), /未获得独立真值认证/);
    assert.equal((await writes(page)).length, 0);
    const out = path.join(root, 'output/playwright/vision-models'); mkdirSync(out, { recursive: true }); await page.screenshot({ path: path.join(out, 'validation-feedback-desktop.png'), fullPage: true });
    await card.getByLabel('人工反馈分类', { exact: true }).selectOption('HARD_SAMPLE'); await review(card); await checked(card, '我已复核预测与参考标签证据'); await card.getByRole('button', { name: '记录人工反馈分类' }).click();
    await card.getByText(/已人工分类：HARD_SAMPLE/).waitFor();
    const target = form(page); await target.getByLabel('运行环境', { exact: true }).selectOption('vision_runtime_test'); await target.getByLabel('冻结数据集', { exact: true }).selectOption('vision_dataset_test');
    await target.getByLabel(new RegExp('val_sample · HARD_SAMPLE')).check(); await target.getByText(/回应反馈必须选择不同 SHA 的新数据集/).waitFor();
    assert.equal(await target.getByRole('button', { name: '按本次授权启动 CPU 训练' }).isEnabled(), false);
    await target.getByLabel('冻结数据集', { exact: true }).selectOption('vision_dataset_new'); await review(target);
    await checked(target, '我已核查 Ultralytics'); await checked(target, '我信任所选 Python'); await checked(target, '我授权按上述数据集');
    await target.getByRole('button', { name: '按本次授权启动 CPU 训练' }).click(); await page.getByRole('button', { name: /已授权 · 等待执行/ }).waitFor();
    const posts = await writes(page); assert.equal(posts.length, 2); assert.ok(posts[0].path.endsWith(`/feedback/${fixture.feedback.feedback_id}/triage`));
    assert.deepEqual(posts[1].request.responds_to_feedback_ids, [fixture.feedback.feedback_id]); assert.equal(posts[1].request.dataset_id, 'vision_dataset_new');
    assert.equal(Object.keys(posts[1].request.expected_feedback_receipts).length, 1); assert.equal(Object.hasOwn(posts[1].request, 'training_samples'), false);
    const stored = await page.evaluate(() => window.__db.feedback[0]); assert.equal(stored.issue_closed, false); assert.equal(stored.training_ingestion_allowed, false);
  } finally { await page.close(); }
});
test('unknown triage reconciles the actual feedback operation by GET and keeps issue open', async () => {
  const fixture = await feedbackFixture(); const page = await openPage({ unknown: true }); try {
    await page.evaluate(fixture => { window.__db.runs = [fixture.run]; window.__db.feedback = [fixture.feedback]; }, fixture);
    await page.getByRole('button', { name: '刷新状态（仅 GET）' }).click(); await tab(page, '训练'); await page.getByRole('button', { name: /候选已生成/ }).click();
    await page.getByRole('button', { name: '读取本轮验证反馈（仅 GET）' }).click(); const card = page.locator('.vision-models__feedback-card'); await card.getByText('val_sample · val').waitFor();
    await card.getByLabel('人工反馈分类', { exact: true }).selectOption('LABEL_REVIEW_REQUIRED'); await review(card); await checked(card, '我已复核预测与参考标签证据'); await card.getByRole('button', { name: '记录人工反馈分类' }).click();
    await page.getByText('写入结果待确认 · UNKNOWN').waitFor();
    await page.getByRole('button', { name: '使用原 request_key 仅 GET 对账' }).click(); await card.getByText(/已人工分类：LABEL_REVIEW_REQUIRED/).waitFor();
    assert.equal((await writes(page)).length, 1);
    const calls = await page.evaluate(() => window.__calls.filter(call => call.path.includes('/vision-operations/')));
    assert.equal(calls.length, 1); assert.ok(calls[0].path.includes(`/triage_feedback%3A${fixture.feedback.feedback_id}/`)); assert.equal(calls[0].method, 'GET');
    assert.equal(await page.evaluate(() => window.__db.feedback[0].issue_closed), false); assert.equal(await page.evaluate(() => Object.keys(localStorage).length), 0);
  } finally { await page.close(); }
});
