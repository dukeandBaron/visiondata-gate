/** Isolated workbook interactions; API and canvas/import children are test doubles.
 * No user's data, server, credentials or models are accessed.
 * node --test tests/web_business_context.browser.mjs
 * VDG_PLAYWRIGHT_MODULE may point to an existing playwright-core/index.mjs.
 */
import assert from 'node:assert/strict';
import { before, after, test } from 'node:test';
import { createRequire } from 'node:module';
import { existsSync } from 'node:fs';
import { fileURLToPath, pathToFileURL } from 'node:url';
import path from 'node:path';

const root = fileURLToPath(new URL('..', import.meta.url));
const webRoot = path.join(root, 'web');
const require = createRequire(path.join(webRoot, 'package.json'));
const { build, transformWithOxc } = await import(pathToFileURL(require.resolve('vite')).href);
const { chromium } = await import(pathToFileURL(process.env.VDG_PLAYWRIGHT_MODULE || require.resolve('playwright')).href);
let browser, bundle;

const modules = new Map([
  ['\0business-context', `export function useProduct() { return window.__testProduct; }`],
  ['\0business-api', `
    import {canonicalizeJcs,sha256HexUtf8} from '/src/data/jcs.ts';
    export class OperatorApiError extends Error {constructor(code,message=code,status=503){super(message);this.code=code;this.status=status;}}
    export async function listOperatorImages() { return window.__testAssets; }
    export async function loadOperatorAnnotations(_workspace, id) { return { revision: 0, document_sha256: 'b'.repeat(64), annotations: [], asset_id: id }; }
    export async function loadOperatorPreview() { return URL.createObjectURL(new Blob(['test'], {type:'image/png'})); }
    export async function listOperatorAnalysisRuns() { return []; }
    export async function listOperatorCopilotTurns() { return []; }
    export async function uploadOperatorImages(_workspace, _project, files) {
      window.__writes.upload += 1;
      return { assets: [{...window.__testAssets[0], asset_id:'asset-upload', original_name:files[0].name}], uploaded_count:1 };
    }
    export async function authorizeOperatorProjectSnapshot(input) { window.__writes.snapshot.push(input); return { source_id:'source-test', data_profile:{ project_id:'project-test', acceptance_requirements_sha256:await sha256HexUtf8(canonicalizeJcs(input.acceptanceRequirements)) } }; }
    export async function listLocalTaskSources() { return []; }
    export async function listAgentTasks() { return [{task_id:'task-test',goal:'Reviewed test task',execution_status:'COMPLETED'}]; }
    async function seal(value) { return {...value, receipt_sha256:await sha256HexUtf8(canonicalizeJcs(value))}; }
    export async function operatorFetch(url, options={}) {
      const scope={task_id:'task-test',workspace_id:'workspace-test',project_id:'project-test'};
      if(url.endsWith('/compute-preflight')) {
        if(window.__computeReadFail)throw new OperatorApiError('HTTP_503','Synthetic read failure',503);
        const value=await seal({schema_version:'visiondata-gate.compute-preflight.v1',...scope,eligibility:'READY_FOR_OFFLINE_HANDOFF',blockers:[],binding:{...scope,snapshot_id:'snapshot-test'},adapter:{kind:'OFFLINE_EXPORT',live_submission_available:false,device_validation:'NOT_TESTED'},production_release_allowed:false});
        if(window.__computeTamper)value.binding.snapshot_id='changed';
        return new Response(JSON.stringify(value));
      }
      if(options.method==='POST') {
        window.__computePosts=(window.__computePosts||0)+1;
        window.__computeRecord=await seal({schema_version:'visiondata-gate.compute-handoff.v1',...scope,handoff_id:'compute-test',prepared_by:'test-reviewer',prepared_at:'2026-09-11T00:00:00Z',status:'PREPARED_NOT_SUBMITTED',request:JSON.parse(options.body),binding:{...scope,snapshot_id:'snapshot-test'},remote_job_id:null,remote_execution_verified:false,dataset_bytes_exported:false,production_release_allowed:false,machine_write_permitted:false});
        if(window.__computeUnknown)throw new OperatorApiError('HTTP_503','Synthetic unknown write result',503);
        if(window.__computeTamperWrite)return new Response(JSON.stringify({...window.__computeRecord,status:'RUNNING'}));
        return new Response(JSON.stringify(window.__computeRecord));
      }
      if(url.endsWith('/export'))return new Response(JSON.stringify(window.__computeRecord));
      return new Response(JSON.stringify(await seal({schema_version:'visiondata-gate.compute-handoff-list.v1',...scope,items:window.__computeRecord?[{read_status:'VERIFIED',record:window.__computeRecord}]:[]})));
    }
    export async function saveOperatorAnnotations() { throw new Error('Unexpected save'); }
    export async function createOperatorAnalysisRun() { throw new Error('Unexpected analysis'); }
    export async function createOperatorCopilotTurn() { throw new Error('Unexpected copilot'); }
    export async function createOperatorWorkOrder() { throw new Error('Unexpected work order'); }
  `],
  ['\0business-canvas.tsx', `export function InteractiveImageCanvas({onAnnotationsChange}) { return <button onClick={() => onAnnotationsChange([{annotation_id:'box-test',label:'test',x:1,y:1,width:5,height:5}])}>Test edit box</button>; }`],
  ['\0business-panel.tsx', `export function OperatorAgentPanel() { return <div>Test agent boundary</div>; }`],
  ['\0business-tour.tsx', `export function OperatorWorkspaceTour() { return null; }`],
  ['\0business-import.tsx', `export function DatasetImportDialog({onImported}) { return <button onClick={() => onImported({workspaceId:'workspace-test', projectId:'project-test', assets:[{...window.__testAssets[0], asset_id:'asset-dataset', original_name:'dataset-test.png'}], selectedImageCount:1, rejectedImageCount:0, annotationFileCount:0, importedBoxCount:0, warnings:[], datasetName:'Test dataset'})}>Test finish dataset import</button>; }`],
  ['\0business-entry.tsx', `
    import {createRoot} from 'react-dom/client';
    import {MemoryRouter, Routes, Route, useLocation} from 'react-router-dom';
    import {ImageWorkspacePage} from '/src/pages/ImageWorkspacePage.tsx';
    import {ComputeHandoffPage} from '/src/pages/ComputeHandoffPage.tsx';
    import '/src/styles/tokens.css';
    import '/src/styles/index.css';
    function Location() { const location = useLocation(); return <output data-testid="location">{location.pathname + location.search}</output>; }
    createRoot(document.getElementById('root')).render(<MemoryRouter initialEntries={[window.__testRoute]}><Location/><Routes><Route path="/workspace" element={<ImageWorkspacePage/>}/><Route path="/compute" element={<ComputeHandoffPage/>}/><Route path="*" element={<div>Test destination</div>}/></Routes></MemoryRouter>);
  `],
]);

before(async () => {
  const result = await build({root:webRoot, configFile:false, logLevel:'error', define:{'process.env.NODE_ENV':JSON.stringify('production')},
    build:{write:false,minify:false,lib:{entry:'/__business_entry.tsx',name:'BusinessContextTest',formats:['iife']}},
    plugins:[{name:'isolated-business-context', enforce:'pre', resolveId(id, importer) {
      if(id==='./api' && importer?.endsWith('/data/computeApi.ts'))return '\0business-api';
      if(id.endsWith('__business_entry.tsx')) return '\0business-entry.tsx';
      for(const [suffix, target] of [['/ProductContext','context'],['/data/api','api'],['/components/InteractiveImageCanvas','canvas.tsx'],['/components/OperatorAgentPanel','panel.tsx'],['/components/DatasetImportDialog','import.tsx'],['/components/OperatorWorkspaceTour','tour.tsx']]) {
        if(id.endsWith(suffix)) return '\0business-' + target;
      }
    }, load(id) {return modules.get(id);}, transform(code,id) {
      if(id.startsWith('\0business-') && id.endsWith('.tsx')) return transformWithOxc(code,id.slice(1),{lang:'tsx',jsx:{runtime:'automatic'}});
    }}],
  });
  const output = (Array.isArray(result) ? result[0] : result).output;
  bundle = {js:output.find(item => item.type==='chunk').code, css:output.filter(item=>item.type==='asset'&&item.fileName.endsWith('.css')).map(item=>item.source).join('\n')};
  const executablePath = process.env.VDG_BROWSER_EXECUTABLE || ['C:/Program Files (x86)/Microsoft/Edge/Application/msedge.exe','C:/Program Files/Google/Chrome/Application/chrome.exe'].find(existsSync);
  browser = await chromium.launch({headless:true, ...(executablePath ? {executablePath} : {})});
});
after(async () => {await browser?.close();});

async function scenario(purpose, compute=false) {
  const page = await browser.newPage({viewport:{width:1600,height:1000}});
  page.setDefaultTimeout(8000);
  const errors=[];
  page.on('pageerror', error=>errors.push(error.message));
  await page.route('**/*', route=>route.abort());
  await page.route('http://localhost/test', route=>route.fulfill({contentType:'text/html',body:'<!doctype html><html><body><div id="root"></div></body></html>'}));
  await page.goto('http://localhost/test');
  await page.evaluate(({purpose,compute})=>{
    window.__testRoute = compute?'/compute?task=task-test':'/workspace?purpose=' + encodeURIComponent(purpose);
    window.__testProduct = {activeWorkspace:{workspace_id:'workspace-test',name:'Test workspace'}, activeProject:{project_id:'project-test',name:'Test project',source_kind:'local_authorized_directory'},workspaceLoading:false,registerScopeChangeGuard:()=>()=>{}};
    window.__testAssets = ['one','two'].map((id)=>({asset_id:'asset-'+id,workspace_id:'workspace-test',project_id:'project-test',original_name:id+'.png',source_sha256:'a'.repeat(64),width:32,height:32,format:'PNG',byte_size:99,annotation_count:0,inspection:{black_clip_ratio:0,white_clip_ratio:0,contrast_std:30,edge_energy:10,mean_luma:90}}));
    window.__writes={upload:0,snapshot:[]};
  },{purpose,compute});
  await page.addStyleTag({content:bundle.css});
  await page.addScriptTag({content:bundle.js});
  if(compute)await page.getByRole('heading',{name:'将这一版数据交给计算环境',exact:true}).waitFor();
  else await page.getByRole('button',{name:'Test edit box',exact:true}).waitFor();
  return {page,errors};
}

test('workbook selection, upload and dataset import retain the actual chosen purpose',async()=>{
  const {page,errors}=await scenario('annotation-rework');
  try {
    await page.getByRole('button',{name:/two.png/}).click();
    assert.match(await page.getByTestId('location').innerText(),/purpose=annotation-rework&asset=asset-two/);
    await page.locator('input[type=file]').setInputFiles({name:'upload-test.png',mimeType:'image/png',buffer:Buffer.from('synthetic API fixture, not image validation')});
    await page.getByRole('button',{name:/upload-test.png/}).waitFor();
    await page.getByTestId('location').filter({hasText:/asset=asset-upload/}).waitFor();
    assert.match(await page.getByTestId('location').innerText(),/purpose=annotation-rework&asset=asset-upload/);
    await page.getByRole('button',{name:'导入数据集',exact:true}).click();
    await page.getByRole('button',{name:'Test finish dataset import',exact:true}).click();
    await page.getByTestId('location').filter({hasText:/asset=asset-dataset/}).waitFor();
    assert.match(await page.getByTestId('location').innerText(),/purpose=annotation-rework&asset=asset-dataset/);
    assert.deepEqual(await page.evaluate(()=>window.__writes),{upload:1,snapshot:[]});
    assert.deepEqual(errors,[]);
  } finally {await page.close();}
});

test('leaving the task context respects unsaved annotation confirmation',async()=>{
  const {page,errors}=await scenario('annotation-rework');
  try {
    await page.getByRole('button',{name:'Test edit box',exact:true}).click();
    page.once('dialog',dialog=>dialog.dismiss());
    await page.getByRole('button',{name:'操作指引',exact:true}).click();
    assert.match(await page.getByTestId('location').innerText(),/^\/workspace/);
    assert.equal(await page.getByRole('button',{name:/保存标注/}).isEnabled(),true);
    page.once('dialog',dialog=>dialog.accept());
    await page.getByRole('button',{name:'操作指引',exact:true}).click();
    await page.getByTestId('location').filter({hasText:/^\/start\?/}).waitFor();
    assert.equal(await page.getByTestId('location').innerText(),'/start?purpose=annotation-rework');
    assert.deepEqual(errors,[]);
  } finally {await page.close();}
});

test('snapshot handoff requires explicit review before binding source and purpose',async()=>{
  const {page,errors}=await scenario('dataset-reuse');
  try {
    await page.getByText('本次交付要求与下一步',{exact:true}).click();
    assert.match(await page.locator('.business-task-context').innerText(),/累计项目快照/);
    await page.screenshot({path:path.join(root,'output/playwright/scoring-business-workbook-context.png')});
    await page.getByRole('button',{name:'冻结项目并交给 Agent',exact:true}).click();
    const dialog=page.getByRole('dialog',{name:'这批图像，按什么标准检查？'});
    await dialog.waitFor();
    await page.getByLabel('数据类别与框标签词表',{exact:true}).fill('sample');
    await page.getByLabel('复核人姓名',{exact:true}).fill('Test Reviewer');
    await page.getByLabel('采用的标注规范与复核说明',{exact:true}).fill('Reviewed under synthetic test requirements');
    await page.getByRole('checkbox').check();
    await page.getByRole('button',{name:'确认要求并冻结快照',exact:true}).click();
    await dialog.getByRole('alert').waitFor();
    assert.equal((await page.evaluate(()=>window.__writes.snapshot)).length,0);
    for(const id of ['asset-one','asset-two']) {
      await page.getByLabel('类别 '+id,{exact:true}).selectOption('sample');
      await page.getByLabel('标注要求 '+id,{exact:true}).selectOption('OPTIONAL');
    }
    await page.getByRole('checkbox').check();
    await page.screenshot({path:path.join(root,'output/playwright/explicit-snapshot-acceptance.png')});
    await page.getByRole('button',{name:'确认要求并冻结快照',exact:true}).click();
    await page.getByTestId('location').filter({hasText:/^\/command-center/}).waitFor();
    assert.equal(await page.getByTestId('location').innerText(),'/command-center?create=1&source=source-test&purpose=dataset-reuse');
    const snapshots=await page.evaluate(()=>window.__writes.snapshot);
    assert.equal(snapshots.length,1);
    assert.deepEqual(Object.keys(snapshots[0]).sort(),['acceptanceRequirements','displayName','projectId','workspaceId']);
    assert.equal(snapshots[0].acceptanceRequirements.samples.length,2);
    assert.equal(snapshots[0].acceptanceRequirements.samples[0].human_review.expected_annotation_revision,0);
    assert.equal('purpose' in snapshots[0],false);
    assert.deepEqual(errors,[]);
  } finally {await page.close();}
});

test('unknown workbook purpose remains recoverable without changing data',async()=>{
  const {page,errors}=await scenario('unknown');
  try {
    assert.equal(await page.getByText('链接中的业务任务不存在',{exact:true}).isVisible(),true);
    await page.getByRole('button',{name:/two.png/}).click();
    await page.getByRole('button',{name:'收起业务指引',exact:true}).click();
    await page.locator('.business-task-context').waitFor({state:'detached'});
    assert.equal(await page.getByTestId('location').innerText(),'/workspace?asset=asset-two');
    assert.equal(await page.getByRole('button',{name:/two.png/}).isVisible(),true);
    assert.deepEqual(await page.evaluate(()=>window.__writes),{upload:0,snapshot:[]});
    assert.deepEqual(errors,[]);
  } finally {await page.close();}
});

test('compute unknown write is reconciled by GET without replay and stale refresh blocks export',async()=>{
  const {page,errors}=await scenario('',true);
  try {
    await page.getByRole('button',{name:'核验输入与已有申请',exact:true}).click();
    await page.getByRole('heading',{name:'可准备离线交接',exact:true}).waitFor();
    await page.getByLabel('CANN 版本要求',{exact:true}).fill('test-9.0');
    await page.getByLabel('固定镜像引用（必须含 @sha256）',{exact:true}).fill('example.invalid/runtime@sha256:'+'a'.repeat(64));
    await page.getByLabel('人工复核与交接说明',{exact:true}).fill('Synthetic reviewed dataset handoff, no external execution');
    await page.getByRole('checkbox').check();
    await page.evaluate(()=>{window.__computeUnknown=true;});
    await page.getByRole('button',{name:'保存离线交接申请',exact:true}).click();
    await page.getByRole('alert').waitFor();
    await page.getByRole('button',{name:'仅查询准备结果',exact:true}).click();
    await page.getByText('已通过 GET 找到该准备记录',{exact:false}).waitFor();
    assert.equal(await page.evaluate(()=>window.__computePosts),1);
    const pending=page.waitForEvent('download');
    await page.getByRole('button',{name:'导出元数据合同',exact:true}).click();
    await (await pending).saveAs(path.join(root,'output/playwright/compute-ui-synthetic-export.json'));
    await page.screenshot({path:path.join(root,'output/playwright/compute-handoff-page.png')});
    await page.evaluate(()=>{window.__computeReadFail=true;});
    await page.getByRole('button',{name:'核验输入与已有申请',exact:true}).click();
    await page.getByRole('heading',{name:'上次读取已过期 · 不可使用',exact:true}).waitFor();
    assert.equal(await page.getByRole('button',{name:'导出元数据合同',exact:true}).isDisabled(),true);
    assert.equal(await page.getByText('冻结输入、逐样本复核、五类工具和 PASS 已核验。',{exact:false}).count(),0);
    assert.equal(await page.evaluate(()=>window.__computePosts),1);
    assert.deepEqual(errors,[]);
  } finally {await page.close();}
});

test('compute response digest mismatch cannot establish eligibility',async()=>{
  const {page,errors}=await scenario('',true);
  try {
    await page.evaluate(()=>{window.__computeTamper=true;});
    await page.getByRole('button',{name:'核验输入与已有申请',exact:true}).click();
    await page.getByRole('alert').waitFor();
    assert.match(await page.getByRole('alert').innerText(),/摘要核验失败/);
    assert.equal(await page.getByRole('button',{name:'保存离线交接申请',exact:true}).isDisabled(),true);
    assert.deepEqual(errors,[]);
  } finally {await page.close();}
});

test('invalid prepare response remains unknown and must reconcile instead of replay',async()=>{
  const {page}=await scenario('',true);
  try {
    await page.getByRole('button',{name:'核验输入与已有申请',exact:true}).click();
    await page.getByRole('heading',{name:'可准备离线交接',exact:true}).waitFor();
    await page.getByLabel('CANN 版本要求',{exact:true}).fill('test-9.0');
    await page.getByLabel('固定镜像引用（必须含 @sha256）',{exact:true}).fill('example.invalid/runtime@sha256:'+'b'.repeat(64));
    await page.getByLabel('人工复核与交接说明',{exact:true}).fill('Synthetic reviewed compute request for response validation');
    await page.getByRole('checkbox').check();
    await page.evaluate(()=>{window.__computeTamperWrite=true;});
    await page.getByRole('button',{name:'保存离线交接申请',exact:true}).click();
    await page.getByRole('button',{name:'仅查询准备结果',exact:true}).waitFor();
    assert.equal(await page.getByRole('button',{name:'保存离线交接申请',exact:true}).isDisabled(),true);
    await page.getByRole('button',{name:'仅查询准备结果',exact:true}).click();
    await page.getByText('已通过 GET 找到该准备记录',{exact:false}).waitFor();
    assert.equal(await page.evaluate(()=>window.__computePosts),1);
  } finally {await page.close();}
});
