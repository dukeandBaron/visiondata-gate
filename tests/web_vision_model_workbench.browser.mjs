/** Real visual-model forms + real JCS/API validators; transport/data/accounts are isolated synthetic doubles. */
import assert from 'node:assert/strict';
import { before, after, test } from 'node:test';
import { createRequire } from 'node:module';
import { existsSync, mkdirSync, readFileSync } from 'node:fs';
import { fileURLToPath, pathToFileURL } from 'node:url';
import path from 'node:path';
import { scope, sha, model, normalityModel, inferenceAsset, normalityInference, normalityPngBase64, previewInference, normalityFeedback, normalityFollowupImport, normalityFollowupWorkOrder, tttCapabilities, tttInference, tttFailure, seal, runtime, dataset, run, manifest, capabilities, poolProjection, poolDataset, feedbackFixture, newDetectionDataset } from './web_vision_model_fixtures.mjs';
const root = fileURLToPath(new URL('..', import.meta.url)), webRoot = path.join(root, 'web');
const require = createRequire(path.join(webRoot, 'package.json'));
const { build, transformWithOxc } = await import(pathToFileURL(require.resolve('vite')).href);
const { chromium } = await import(pathToFileURL(process.env.VDG_PLAYWRIGHT_MODULE || require.resolve('playwright')).href);
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
   if(suffix==='vision-ttt-capabilities')return response(db.tttCapabilities);
   if(suffix==='vision-ttt-failures')return response({schema_version:'visiondata-gate.vision-list.v1',project_id:window.__scope.projectId,items:db.tttFailures||[]});
   if(suffix.startsWith('normality-feedback/')&&suffix.endsWith('/followup'))return response({schema_version:'visiondata-gate.normality-followup-list.v1',project_id:window.__scope.projectId,feedback_id:suffix.split('/')[1],imports:db.followupImports||[],work_orders:db.followupOrders||[],issue_closed:false,label_truth_authority:false,training_ingestion_allowed:false,production_release_allowed:false,machine_write_permitted:false,annotation_created:false});
   if(suffix.startsWith('normality-feedback/')&&suffix.endsWith('/annotations')){const imported=db.followupImports.find(row=>row.import_id===suffix.split('/')[3]);return response({schema_version:'visiondata-gate.normality-followup-annotations.v1',project_id:window.__scope.projectId,workspace_id:window.__scope.workspaceId,feedback_id:imported.feedback_id,import_id:imported.import_id,operator_asset_id:imported.operator_asset_id,asset_sha256:imported.image_sha256,revision:db.manualAnnotations?.length?1:0,document_sha256:'1'.repeat(64),annotations:db.manualAnnotations||[],issue_closed:false,label_truth_authority:false,training_ingestion_allowed:false,production_release_allowed:false,machine_write_permitted:false,annotation_created:false});}
   if(suffix.startsWith('vision-inferences/')&&suffix.endsWith('/heatmap')){
     if(window.__delayHeatmap)await new Promise(resolve=>{window.__releaseHeatmap=resolve;});
     if(init.signal?.aborted)throw new DOMException('cancelled','AbortError');
     const item=db.inferences.find(item=>item.inference_id===suffix.split('/')[1]);
     const bytes=Uint8Array.from(atob(db.png),c=>c.charCodeAt(0));
     return new Response(bytes,{headers:{'Content-Type':'image/png','Content-Length':String(bytes.length),ETag:'"'+item.heatmap.sha256+'"','X-Content-SHA256':window.__corruptHeatmap?'0'.repeat(64):item.heatmap.sha256}});
   }
   if(suffix.startsWith('vision-inferences/')&&suffix.endsWith('/feedback'))return response({schema_version:'visiondata-gate.vision-list.v1',project_id:window.__scope.projectId,inference_id:suffix.split('/')[1],items:db.normalityFeedback||[]});
   if(suffix.startsWith('vision-training-runs/')&&suffix.endsWith('/feedback')){const id=suffix.split('/')[1];return response({schema_version:'visiondata-gate.vision-list.v1',project_id:window.__scope.projectId,run_id:id,items:(db.feedback||[]).filter(item=>item.run_id===id)});}
   for(const [route,key] of Object.entries({'vision-models':'models','vision-runtimes':'runtimes','vision-datasets':'datasets','vision-training-runs':'runs','vision-inference-assets':'inferenceAssets','vision-inferences':'inferences'})){
    if(suffix===route)return response({schema_version:'visiondata-gate.vision-list.v1',project_id:window.__scope.projectId,items:db[key]});
    if(suffix.startsWith(route+'/')){const item=db[key].find(v=>v.resource_id===suffix.slice(route.length+1));if(item)return response(item);}
   }
   if(suffix.startsWith('vision-operations/')||suffix.startsWith('normality-followup-operations/')){const [,operation,request_key]=suffix.split('/');const item=window.__ledger[operation+':'+request_key];if(!item)throw new OperatorApiError('HTTP_404','not found',404);
    return response({schema_version:'visiondata-gate.vision-operation.v1',project_id:window.__scope.projectId,operation,request_key,resource_id:item.resource_id,resource:item,auto_replayed:false});}
   throw new OperatorApiError('HTTP_404','not found',404);
 }
 let resource,operation;
 if(suffix.startsWith('normality-feedback/')&&suffix.endsWith('/followup-import')){operation='import_normality_followup:'+suffix.split('/')[1];resource=await sealed({...db.followupImportTemplate,reviewer_identity:request.reviewer_identity,note:request.note});db.followupImports=[resource];}
 else if(suffix.startsWith('normality-feedback/')&&suffix.endsWith('/followup-work-orders')){operation='create_normality_followup_work_order:'+suffix.split('/')[1];const imported=db.followupImports.find(row=>row.import_id===request.import_id);resource=await sealed({...db.followupOrderTemplate,import_sha256:imported.receipt_sha256,annotation_id:request.annotation_id,annotation_revision:request.expected_annotation_revision,annotation_document_sha256:request.expected_annotation_document_sha256,reviewer_identity:request.reviewer_identity,note:request.note,assignee:request.assignee});db.followupOrders=[resource];}
 else if(suffix==='vision-models'){operation='register_model';resource=await sealed({...db.modelTemplate,resource_id:'vision_model_new',model_id:'vision_model_new',display_name:request.display_name,weights_sha256:request.expected_weights_sha256,task_type:request.task_type});db.models.push(resource);}
 else if(suffix==='vision-model-packs'){operation='register_normality_model_pack';resource=await sealed({...db.normalityModelTemplate,display_name:request.display_name,model_pack_sha256:request.expected_model_pack_sha256,weights_sha256:request.expected_model_pack_sha256,backbone_weights_sha256:request.expected_backbone_weights_sha256,source_binding_sha256:request.expected_source_binding_sha256,source_index_sha256:request.expected_source_index_sha256});db.models.push(resource);}
 else if(suffix.startsWith('vision-models/')&&suffix.endsWith('/sandbox-approval')){const id=suffix.split('/')[1];operation='approve_normality_model_pack:'+id;const index=db.models.findIndex(v=>v.resource_id===id);resource=await sealed({...db.approvedNormalityTemplate,resource_id:id,model_id:id,display_name:db.models[index].display_name,receipt_sha256:undefined});db.models[index]=resource;}
 else if(suffix==='vision-inference-assets'){operation='register_inference_asset';resource=await sealed({...db.inferenceAssetTemplate,display_name:request.display_name,image_sha256:request.expected_image_sha256});db.inferenceAssets.push(resource);}
 else if(suffix.startsWith('vision-models/')&&suffix.endsWith('/inferences')){const id=suffix.split('/')[1];operation='run_normality_inference:'+id;resource=await sealed({...db.inferenceTemplate,model_id:id,asset_id:request.asset_id,model_pack_sha256:request.expected_model_pack_sha256,backbone_weights_sha256:request.expected_backbone_weights_sha256,source_binding_sha256:request.expected_source_binding_sha256,source_index_sha256:request.expected_source_index_sha256,runtime_sha256:request.expected_runtime_sha256,image_sha256:request.expected_image_sha256});db.inferences.push(resource);}
 else if(suffix.startsWith('vision-models/')&&suffix.endsWith('/ttt-inferences')){operation='run_normality_ttt:'+suffix.split('/')[1];
   if(window.__tttFail){resource=await sealed({...db.tttFailure,authorization_sha256:await hash(request)});db.tttFailures=[resource];}
   else {resource=await sealed({...db.tttInference,ttt:{...db.tttInference.ttt,budget:request.budget}});db.inferences=[resource];}}
 else if(suffix.startsWith('vision-inferences/')&&suffix.endsWith('/feedback')){const id=suffix.split('/')[1],item=db.inferences.find(v=>v.inference_id===id);operation='review_normality_inference:'+id;resource=await sealed({...db.normalityFeedbackTemplate,inference_id:id,inference_sha256:item.receipt_sha256,classification:request.classification,reviewer_identity:request.reviewer_identity,note:request.note,followup_work_item_type:{MODEL_SIGNAL_CONFIRMED:'MODEL_SIGNAL_REVIEW',LIKELY_FALSE_POSITIVE:'FALSE_POSITIVE_INVESTIGATION',NEEDS_LABEL_REVIEW:'LABEL_REVIEW',INSUFFICIENT_EVIDENCE:'EVIDENCE_COLLECTION'}[request.classification]});db.normalityFeedback=[resource];}
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
async function openPage({ unknown = false, unsupported = false, pending = null, query = '', width = 1400, importedRuntime = false } = {}) {
  const page = await browser.newPage({ viewport: { width, height: 1100 } }); page.setDefaultTimeout(7000);
  await page.route('http://localhost:43441/**', route => route.fulfill({ body: '<!doctype html><html><head></head><body><div id="root"></div></body></html>', contentType: 'text/html' }));
  await page.goto(`http://localhost:43441/models?tab=vision${query}`);
  const m = await model(), n = await normalityModel(), na = await normalityModel('APPROVE_SANDBOX'), ia = await inferenceAsset(), ni = await previewInference(), r = await runtime(importedRuntime ? 'PASSED' : 'NOT_RUN'), d = await dataset(), tr = await run();
  await page.evaluate(({ scope, db, unknown, unsupported, pending }) => {
    window.__scope = scope; window.__db = db; window.__calls = []; window.__ledger = {}; window.__unknownPost = unknown; window.__unsupported = unsupported;
    window.__product = { activeWorkspace: { workspace_id: scope.workspaceId }, activeProject: { project_id: scope.projectId, name: '合成项目' }, registerScopeChangeGuard: () => () => {} };
    if (pending) localStorage.setItem(`vision-model:pending:${scope.actorId}:${scope.workspaceId}:${scope.projectId}`, JSON.stringify(pending));
  }, { scope, db: { models: [m], runtimes: [r], datasets: [d], runs: [], inferenceAssets: [], inferences: [], modelTemplate: m, normalityModelTemplate: n, approvedNormalityTemplate: na,
    inferenceAssetTemplate: ia, inferenceTemplate: ni, png: normalityPngBase64, normalityFeedbackTemplate: await normalityFeedback(ni), followupImportTemplate: await normalityFollowupImport(), followupOrderTemplate: await normalityFollowupWorkOrder(), tttCapabilities: await tttCapabilities(), tttInference: await tttInference(), tttFailure: await tttFailure(), runtimeTemplate: r, datasetTemplate: d, runTemplate: tr, capabilities: await capabilities(), poolProjection: await poolProjection(), poolDataset: await poolDataset() }, unknown, unsupported, pending });
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

test('normality surface is truthful when the current workspace has no pack, asset or inference', async () => {
  const page = await openPage(); try {
    await tab(page, 'Normality 推理'); const target = page.locator('.vision-models__form-panel');
    assert.match(await target.innerText(), /HOLD：当前项目没有已批准的 Normality 模型包/);
    assert.match(await target.innerText(), /CONNECTOR_NOT_CONFIGURED/);
    assert.equal((await writes(page)).length, 0);
    assert.equal(await target.getByRole('button', { name: '执行一次本地沙箱推理' }).isEnabled(), false);
  } finally { await page.close(); }
});

test('normality pack registration and sandbox approval are separate explicit operations', async () => {
  const page = await openPage({ importedRuntime: true }); try {
    await tab(page, 'Normality 推理'); const pack = page.locator('.vision-models__normality-pack');
    await pack.getByLabel('模型包名称').fill('登记的 Normality 包');
    await pack.getByLabel('模型包绝对路径').fill('C:/synthetic/normality/model-pack.pt'); await pack.getByLabel('模型包 SHA-256').fill(sha('a'));
    await pack.getByLabel('目标运行目录').fill('C:/synthetic/normality/seed_20260913');
    for (const [index, value] of ['seed_20260911', 'seed_20260912', 'seed_20260913'].entries()) await pack.getByLabel(`稳定性运行目录 ${index + 1}`).fill(`C:/synthetic/normality/${value}`);
    await pack.getByLabel('稳定性摘要 JSON').fill('C:/synthetic/normality/model_stability_summary.json'); await pack.getByLabel('稳定性摘要 SHA-256').fill(sha('4'));
    await pack.getByLabel('来源绑定 JSON').fill('C:/synthetic/normality/source_binding.json'); await pack.getByLabel('来源绑定文件 SHA-256').fill(sha('5')); await pack.getByLabel('来源绑定内容 SHA-256').fill(sha('c'));
    await pack.getByLabel('来源索引 JSON').fill('C:/synthetic/normality/source_index.json'); await pack.getByLabel('来源索引文件 SHA-256').fill(sha('6')); await pack.getByLabel('来源索引内容 SHA-256').fill(sha('d'));
    await pack.getByLabel('Backbone 权重绝对路径').fill('C:/synthetic/normality/backbone.pt'); await pack.getByLabel('Backbone 权重 SHA-256').fill(sha('b'));
    await review(pack); await checked(pack, '我授权读取上述本地证据'); await checked(pack, '我仅授权 weights-only'); await checked(pack, '我已核查 Ultralytics');
    await pack.getByRole('button', { name: '核验并登记 Normality 模型包' }).click(); await page.getByRole('button', { name: /登记的 Normality 包/ }).waitFor();
    await page.getByRole('button', { name: /登记的 Normality 包/ }).click(); const approval = page.locator('.vision-models__normality-approval');
    await approval.getByLabel('沙箱运行环境').selectOption('vision_runtime_test'); await review(approval);
    for (const label of ['我已复核模型包证据', '我信任所选运行环境', '我授权执行模型包验证', '我信任绑定的权重', '我仅授权 weights-only', '我已核查 Ultralytics']) await checked(approval, label);
    await approval.getByRole('button', { name: '批准为本地沙箱模型' }).click(); await page.getByText('LOCAL_SANDBOX_ONLY', { exact: true }).waitFor();
    const posts = await writes(page); assert.equal(posts.length, 2); assert.ok(posts[0].path.endsWith('/vision-model-packs')); assert.ok(posts[1].path.endsWith('/sandbox-approval'));
  } finally { await page.close(); }
});

test('approved normality model previews verified pixels and persists named feedback with GET readback (synthetic API)', async () => {
  const page = await openPage({ importedRuntime: true }); try {
    const approved = await normalityModel('APPROVE_SANDBOX'); await page.evaluate(approved => { window.__db.models.push(approved); }, approved);
    await page.getByRole('button', { name: '刷新状态（仅 GET）' }).click(); await tab(page, 'Normality 推理');
    const asset = page.locator('.vision-models__normality-asset'); await asset.getByLabel('输入图像名称').fill('待判定图像'); await asset.getByLabel('输入图像绝对路径').fill('C:/synthetic/images/part.png');
    await asset.getByLabel('输入图像 SHA-256').fill(sha('8')); await review(asset); await checked(asset, '我授权读取该本地图像');
    await asset.getByRole('button', { name: '冻结为推理输入资产' }).click(); await page.getByText(/FROZEN_LOCAL_INFERENCE_ASSET/).waitFor();
    const inference = page.locator('.vision-models__normality-inference'); await inference.getByLabel('Normality 模型包').selectOption('vision_normality_model_test');
    await inference.getByLabel('冻结输入资产').selectOption('vision_inference_asset_test'); await review(inference);
    for (const label of ['我授权本次本地 CPU 推理', '我信任沙箱运行环境', '我信任绑定的权重', '我仅授权 weights-only']) await checked(inference, label);
    await inference.getByRole('button', { name: '执行一次本地沙箱推理' }).click(); await page.getByRole('button', { name: /异常信号/ }).waitFor();
    await page.getByRole('button', { name: /异常信号/ }).click(); const details = page.locator('.vision-models__details');
    assert.match(await details.innerText(), /0\.750000/); assert.match(await details.innerText(), /0\.500000/);
    await details.getByRole('button', { name: '读取并校验热图（仅 GET）' }).click();
    const img = details.getByRole('img', { name: '已校验的 Normality 热图' }); await img.waitFor();
    await page.waitForFunction(() => document.querySelector('.vision-models__heatmap-evidence img')?.naturalWidth === 1);
    assert.match(await img.getAttribute('src'), /^blob:/); const writesBeforeDraft = (await writes(page)).length;
    const draft = details.locator('.vision-models__normality-review'); await draft.getByLabel('人工信号分类').selectOption('NEEDS_LABEL_REVIEW'); await review(draft);
    await checked(draft, '我已阅读推理与热图证据'); await draft.getByRole('button', { name: '保存具名复核反馈' }).click();
    await details.getByText('已保存并回读 · RECORDED_FOR_HUMAN_FOLLOWUP', { exact: true }).waitFor(); assert.equal((await writes(page)).length, writesBeforeDraft + 1);
    assert.equal(await page.evaluate(() => window.__calls.some(call => call.method === 'GET' && call.path.endsWith('/vision-inferences/vision_inference_test/feedback'))), true);
    assert.equal(await page.evaluate(() => JSON.stringify(localStorage).includes('NEEDS_LABEL_REVIEW')), false);
  } finally { await page.close(); }
});

async function openInference() {
  const page = await openPage();
  await page.evaluate(() => { window.__db.inferences = [window.__db.inferenceTemplate]; window.__createdUrls = []; window.__revokedUrls = [];
    const create = URL.createObjectURL.bind(URL), revoke = URL.revokeObjectURL.bind(URL);
    URL.createObjectURL = blob => { const url = create(blob); window.__createdUrls.push(url); return url; };
    URL.revokeObjectURL = url => { window.__revokedUrls.push(url); revoke(url); }; });
  await page.getByRole('button', { name: '刷新状态（仅 GET）' }).click(); await tab(page, 'Normality 推理');
  await page.getByRole('button', { name: /异常信号/ }).click(); return page;
}
test('normality preview URLs are revoked on record change and late cancelled responses cannot recreate them (synthetic API)', async () => {
  const page = await openInference(); try {
    await page.getByRole('button', { name: '读取并校验热图（仅 GET）' }).click(); await page.getByRole('img', { name: '已校验的 Normality 热图' }).waitFor();
    await tab(page, '训练'); assert.equal(await page.evaluate(() => window.__revokedUrls.length), 1);
    await tab(page, 'Normality 推理'); await page.getByRole('button', { name: /异常信号/ }).click();
    await page.evaluate(() => { window.__delayHeatmap = true; }); await page.getByRole('button', { name: '读取并校验热图（仅 GET）' }).click();
    await page.waitForFunction(() => Boolean(window.__releaseHeatmap)); await tab(page, '训练'); await page.evaluate(() => window.__releaseHeatmap());
    await page.waitForFunction(() => window.__createdUrls.length === window.__revokedUrls.length);
    assert.equal(await page.getByRole('img').count(), 0); assert.equal(await page.evaluate(() => window.__createdUrls.length), 1);
  } finally { await page.close(); }
});
test('corrupt PNG stays HOLD and unknown feedback is reconciled by GET without a second POST (synthetic API)', async () => {
  const page = await openInference(); try {
    await page.evaluate(() => { window.__corruptHeatmap = true; }); await page.getByRole('button', { name: '读取并校验热图（仅 GET）' }).click();
    await page.locator('.vision-models__heatmap-evidence').getByRole('alert').waitFor(); assert.equal(await page.getByRole('img').count(), 0);
    const form = page.locator('.vision-models__normality-review'); await review(form); await checked(form, '我已阅读推理与热图证据');
    await page.evaluate(() => { window.__unknownPost = true; }); await form.getByRole('button', { name: '保存具名复核反馈' }).click();
    await page.getByText('写入结果待确认 · UNKNOWN', { exact: true }).waitFor(); assert.equal((await writes(page)).length, 1);
    assert.equal(await form.getByRole('button', { name: '保存具名复核反馈' }).isEnabled(), false);
    await page.getByRole('button', { name: '使用原 request_key 仅 GET 对账' }).click();
    await page.getByText('已保存并回读 · RECORDED_FOR_HUMAN_FOLLOWUP', { exact: true }).waitFor(); assert.equal((await writes(page)).length, 1);
  } finally { await page.close(); }
});
test('already-approved normality packs expose an independently authorized revalidation action (synthetic API)', async () => {
  const page = await openPage({ importedRuntime: true }); try {
    await page.evaluate(() => { window.__db.models.push(window.__db.approvedNormalityTemplate); });
    await page.getByRole('button', { name: '刷新状态（仅 GET）' }).click(); await tab(page, 'Normality 推理');
    await page.getByRole('button', { name: /Bound normality pack/ }).click();
    const form = page.locator('.vision-models__normality-approval'), submit = form.getByRole('button', { name: '重新核验沙箱批准' });
    assert.equal(await submit.isEnabled(), false); assert.equal((await writes(page)).length, 0);
    await form.getByLabel('沙箱运行环境').selectOption('vision_runtime_test'); await review(form);
    for (const label of ['我已复核模型包证据', '我信任所选运行环境', '我授权执行模型包验证', '我信任绑定的权重', '我仅授权 weights-only', '我已核查 Ultralytics']) await checked(form, label);
    await submit.click(); await page.getByRole('status').filter({ hasText: '操作已收到' }).waitFor(); assert.equal((await writes(page)).length, 1);
  } finally { await page.close(); }
});

test('TTT has a separate explicitly authorized bounded form and measured outcome, with no implicit adaptation (synthetic API)', async () => {
  const page = await openPage({ importedRuntime: true }); try {
    const base = await inferenceAsset(), extra = await Promise.all([['replay_1', '1'], ['guard_normal', '2'], ['guard_anomaly', '3']].map(async ([id, digit]) => seal({ ...base, asset_id: id, resource_id: id, display_name: id, image_sha256: sha(digit) })));
    await page.evaluate(extra => { window.__db.models.push(window.__db.approvedNormalityTemplate); window.__db.inferenceAssets = [window.__db.inferenceAssetTemplate, ...extra]; window.__db.capabilities.ttt_status = 'NORMALITY_EPISODIC_AVAILABLE'; window.__db.capabilities.ttt_scope = 'NORMALITY_ONLY_EPISODIC_NO_PERSISTENCE'; }, extra);
    await page.getByRole('button', { name: '刷新状态（仅 GET）' }).click(); await tab(page, 'Normality 推理');
    await page.getByRole('button', { name: '读取 TTT 能力（仅 GET）' }).click(); const form = page.locator('.vision-models__normality-ttt');
    const submit = form.getByRole('button', { name: '按独立授权执行一次 TTT' }); assert.equal(await submit.isEnabled(), false); assert.equal((await writes(page)).length, 0);
    await form.getByLabel('Normality 模型包').selectOption('vision_normality_model_test'); await form.getByLabel('冻结输入资产').selectOption('vision_inference_asset_test');
    await form.getByLabel('TTT 用途 replay_1').selectOption('replay'); await form.getByLabel('TTT 用途 guard_normal').selectOption('guard_normal'); await form.getByLabel('TTT 用途 guard_anomaly').selectOption('guard_anomaly');
    await form.getByLabel('TTT 步数').fill('2'); await form.getByLabel('TTT 最长秒数').fill('30'); await review(form);
    for (const label of ['我授权本次本地 CPU 推理', '我信任沙箱运行环境', '我信任绑定的权重', '我仅授权 weights-only', '我单独授权本次有界 TTT', '我确认 replay 图像', '我已具名复核 guard']) await checked(form, label);
    await submit.click(); await page.getByText('ACCEPTED_EPISODIC', { exact: true }).waitFor(); assert.equal((await writes(page)).length, 1);
    assert.match(await page.locator('.vision-models__ttt-result').innerText(), /不等于工业效果提升/);
    const out = path.join(root, 'output/playwright/vision-models'); mkdirSync(out, { recursive: true }); await page.screenshot({ path: path.join(out, 'ttt-desktop.png'), fullPage: true });
  } finally { await page.close(); }
});

test('TTT unknown worker failure only GET reconciles an unmeasured receipt and never fabricates a score (synthetic API)', async () => {
  const page = await openPage({ importedRuntime: true }); try {
    const base = await inferenceAsset(), extra = await Promise.all([['replay_1', '1'], ['guard_normal', '2'], ['guard_anomaly', '3']].map(async ([id, digit]) => seal({ ...base, asset_id: id, resource_id: id, display_name: id, image_sha256: sha(digit) })));
    await page.evaluate(extra => { window.__db.models.push(window.__db.approvedNormalityTemplate); window.__db.inferenceAssets = [window.__db.inferenceAssetTemplate, ...extra]; window.__db.capabilities.ttt_status = 'NORMALITY_EPISODIC_AVAILABLE'; window.__db.capabilities.ttt_scope = 'NORMALITY_ONLY_EPISODIC_NO_PERSISTENCE'; window.__tttFail = true; window.__unknownPost = true; }, extra);
    await page.getByRole('button', { name: '刷新状态（仅 GET）' }).click(); await tab(page, 'Normality 推理'); await page.getByRole('button', { name: '读取 TTT 能力（仅 GET）' }).click();
    const form = page.locator('.vision-models__normality-ttt'); await form.getByLabel('Normality 模型包').selectOption('vision_normality_model_test'); await form.getByLabel('冻结输入资产').selectOption('vision_inference_asset_test');
    await form.getByLabel('TTT 用途 replay_1').selectOption('replay'); await form.getByLabel('TTT 用途 guard_normal').selectOption('guard_normal'); await form.getByLabel('TTT 用途 guard_anomaly').selectOption('guard_anomaly'); await review(form);
    for (const label of ['我授权本次本地 CPU 推理', '我信任沙箱运行环境', '我信任绑定的权重', '我仅授权 weights-only', '我单独授权本次有界 TTT', '我确认 replay 图像', '我已具名复核 guard']) await checked(form, label);
    await form.getByRole('button', { name: '按独立授权执行一次 TTT' }).click(); await page.getByText('写入结果待确认 · UNKNOWN', { exact: true }).waitFor(); assert.equal((await writes(page)).length, 1);
    await page.getByRole('button', { name: '使用原 request_key 仅 GET 对账' }).click(); await page.getByRole('heading', { name: 'TTT 已失败关闭 · FAILED_CLOSED' }).waitFor();
    const failure = page.locator('.vision-models__ttt-failure'); assert.match(await failure.innerText(), /NOT_MEASURED/); assert.equal(await failure.getByRole('img').count(), 0); assert.equal((await writes(page)).length, 1);
    await page.getByRole('button', { name: '刷新状态（仅 GET）' }).click(); await failure.waitFor(); assert.equal((await writes(page)).length, 1);
    assert.match(await page.getByRole('navigation', { name: '视觉模型流程' }).getByRole('button', { name: /Normality 推理/ }).innerText(), /6$/);
  } finally { await page.close(); }
});

test('TTT rollback renders baseline-effective identity without claiming persistent learning (synthetic API)', async () => {
  const page = await openPage(); try {
    const inference = await tttInference('ROLLED_BACK'); await page.evaluate(inference => { window.__db.inferences = [inference]; }, inference);
    await page.getByRole('button', { name: '刷新状态（仅 GET）' }).click(); await tab(page, 'Normality 推理'); await page.getByRole('button', { name: /异常信号/ }).click();
    await page.getByText('ROLLED_BACK', { exact: true }).waitFor(); assert.match(await page.locator('.vision-models__ttt-result').innerText(), /当前分数与热图使用原模型/);
    assert.equal((await writes(page)).length, 0);
  } finally { await page.close(); }
});

test('account/project remount revokes private heatmap URLs before another scope renders (synthetic API)', async () => {
  const page = await openInference(); try {
    await page.getByRole('button', { name: '读取并校验热图（仅 GET）' }).click(); await page.getByRole('img', { name: '已校验的 Normality 热图' }).waitFor();
    await page.evaluate(() => { window.__scope = { ...window.__scope, projectId: 'project_other', actorId: 'actor_other' };
      window.__product = { ...window.__product, activeProject: { project_id: 'project_other', name: '另一个项目' } };
      window.__identity.setIdentitySession({user_id:'actor_other',display_name:'Other synthetic operator',login_name:'other.test',email:null,created_at:'2026-09-13T00:00:00Z',platform_role:'USER',status:'ACTIVE'},'synthetic-token-only-000000000000000000000000'); window.__mount(); });
    await page.waitForFunction(() => window.__revokedUrls.length === 1); assert.equal(await page.getByRole('img', { name: '已校验的 Normality 热图' }).count(), 0);
  } finally { await page.close(); }
});

test('normality followup imports a real workbook asset then requires an existing manual box before a named OPEN order (synthetic API)', async () => {
  const page = await openInference(); try {
    await page.evaluate(() => { window.__db.inferenceAssets = [window.__db.inferenceAssetTemplate]; window.__db.normalityFeedback = [window.__db.normalityFeedbackTemplate]; });
    await page.getByRole('button', { name: '读取人工反馈（仅 GET）' }).click();
    const followup = page.locator('.vision-models__normality-followup'); await followup.getByRole('button', { name: '读取真实后续状态（仅 GET）' }).click();
    const importForm = followup.locator('.vision-models__followup-import'); await review(importForm);
    await checked(importForm, '我授权把这条推理的已验封原图导入'); await checked(importForm, '本次导入不创建标签');
    await importForm.getByRole('button', { name: '具名导入到真实工作簿' }).click();
    await followup.getByRole('button', { name: '读取真实后续状态（仅 GET）' }).click();
    const link = followup.getByRole('link', { name: '打开真实待标注资产' }); await link.waitFor(); assert.equal(await link.getAttribute('href'), '/workspace?asset=img_followup_synthetic');
    await followup.getByRole('button', { name: '读取已保存人工框（仅 GET）' }).click(); await followup.getByText(/尚无已保存人工框/).waitFor();
    assert.equal((await writes(page)).length, 1);
    await page.evaluate(() => { window.__db.manualAnnotations = [{ annotation_id: 'manual_box_1', label: '人工待核区域', x: .1, y: .1, width: .3, height: .2, source: 'MANUAL' }]; });
    await followup.getByRole('button', { name: '读取已保存人工框（仅 GET）' }).click();
    const form = followup.locator('.vision-models__followup-order'); await form.getByLabel('已保存人工框').selectOption('manual_box_1'); await form.getByLabel('复核工单负责人').fill('Human reviewer'); await review(form);
    for (const label of ['我授权为上述已有人工框创建真实 OPEN 工单', '我已复核原图、人工框与当前标注版本', '本次发单不修改标签']) await checked(form, label);
    await page.evaluate(() => { window.__unknownPost = true; }); await form.getByRole('button', { name: '具名创建真实复核工单' }).click();
    await page.getByText('写入结果待确认 · UNKNOWN', { exact: true }).waitFor(); assert.equal((await writes(page)).length, 2);
    await page.getByRole('button', { name: '使用原 request_key 仅 GET 对账' }).click();
    await followup.getByRole('button', { name: '读取真实后续状态（仅 GET）' }).click(); await followup.getByText('真实工单已建立 · OPEN', { exact: true }).waitFor();
    assert.match(await followup.innerText(), /已关联真实人工框和 OPEN 工单/);
    assert.equal((await writes(page)).length, 2); assert.equal(await page.evaluate(() => window.__calls.some(call => call.method === 'PUT')), false);
    const post = (await writes(page))[1].request; assert.equal('annotations' in post, false); assert.equal('bbox' in post, false);
    const out = path.join(root, 'output/playwright/vision-models'); mkdirSync(out, { recursive: true }); await page.screenshot({ path: path.join(out, 'normality-real-followup-desktop.png'), fullPage: true });
  } finally { await page.close(); }
});

test('legacy failed import probe displays NOT_MEASURED without blocking read-only workbench or enabling training (synthetic API)', async () => {
  const page = await openPage(); try {
    const failed = await seal({ ...await runtime(), status: 'UNAVAILABLE', probe: { status: 'failed', error_code: 'YOLO_CHILD_EXECUTION_FAILED', error_type: 'ModuleNotFoundError' } });
    await page.evaluate(failed => { window.__db.runtimes[0] = failed; }, failed);
    await page.getByRole('button', { name: '刷新状态（仅 GET）' }).click(); await page.getByRole('button', { name: /Python metadata fixture/ }).click();
    const details = page.locator('.vision-models__details'); await details.getByText(/NOT_MEASURED/).waitFor(); assert.match(await details.innerText(), /ModuleNotFoundError/);
    await details.getByRole('heading', { name: '显式复查此运行环境' }).waitFor(); assert.equal((await writes(page)).length, 0);
    await tab(page, '训练'); const target = form(page); await target.getByLabel('运行环境', { exact: true }).selectOption('vision_runtime_test'); await target.getByLabel('冻结数据集', { exact: true }).selectOption('vision_dataset_test'); await review(target);
    await checked(target, '我已核查 Ultralytics'); await checked(target, '我信任所选 Python'); await checked(target, '我授权按上述数据集');
    assert.equal(await target.getByRole('button', { name: '按本次授权启动 CPU 训练' }).isEnabled(), false);
  } finally { await page.close(); }
});
