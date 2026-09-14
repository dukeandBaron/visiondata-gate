/** Isolated data-pool UI: synthetic API doubles, no real API, images or training. */
import assert from 'node:assert/strict';
import { before, after, test } from 'node:test';
import { createRequire } from 'node:module';
import { existsSync, mkdirSync } from 'node:fs';
import { fileURLToPath, pathToFileURL } from 'node:url';
import path from 'node:path';

const root = fileURLToPath(new URL('..', import.meta.url)), webRoot = path.join(root, 'web');
const require = createRequire(path.join(webRoot, 'package.json'));
const { build, transformWithOxc } = await import(pathToFileURL(require.resolve('vite')).href);
const cached = 'D:/Users/living/.npm-cache/_npx/31e32ef8478fbf80/node_modules/playwright-core/index.mjs';
const modulePath = process.env.VDG_PLAYWRIGHT_MODULE || (existsSync(cached) ? cached : require.resolve('playwright'));
const { chromium } = await import(pathToFileURL(modulePath).href);
let browser, bundle;
const modules = new Map([
  ['\0pool-context', `export function useProduct() { return window.__product; }`],
  ['\0pool-identity', `
    const listeners = new Set();
    export const getIdentitySessionSnapshot = () => window.__identity;
    export const getIdentityActorId = () => window.__identity.user?.user_id;
    export function subscribeIdentitySession(listener) { listeners.add(listener); return () => listeners.delete(listener); }
    window.__changeIdentity = user => { window.__identity = {user, generation:window.__identity.generation+1}; for (const fn of listeners) fn(); };
  `],
  ['\0pool-api', `
    export class OperatorApiError extends Error { constructor(code, message = code, status = 503) { super(message); this.code = code; this.status = status; } }
    export async function listAgentTasks(workspaceId, projectId) { window.__reads.push({kind:'tasks',workspaceId,projectId}); return structuredClone(window.__tasks.filter(row => row.project_id === projectId)); }
    export async function getTaskVisualEvidence(taskId) {return structuredClone(taskId==='task_repaired'?window.__newVisual:window.__visual);}
    export async function operatorFetch() { throw new Error('Actual API forbidden'); }
  `],
  ['\0pool-client', `
    import {OperatorApiError} from '\0pool-api';
    export const normalizeDataPoolRequest = (_operation,request) => structuredClone(request);
    export async function listTaskDataPools(scope,task) {window.__reads.push({kind:'pools',scope,task});return window.__projection&&[window.__projection.pool.origin_task_id,window.__projection.pool.current_task_id].includes(task)?[structuredClone(window.__projection)]:[];}
    export async function getDataPool() {return structuredClone(window.__projection);}
    export async function getDataPoolVersion() {return {version:structuredClone(window.__projection.current_version),read_status:'CURRENT',stale_reasons:[]};}
    export async function createDataPool(scope,task,request) {
      window.__writes.push({operation:'create',request});window.__operationRequest=request.request_key;
      const qualified=request.members.filter(row=>row.disposition==='QUALIFIED_CANDIDATE').length,repair=request.members.filter(row=>row.disposition==='REPAIR_REQUIRED').length,hold=request.members.length-qualified-repair;
      const version={version_id:'poolv_test',pool_id:'pool_test',version_number:1,parent_version_id:null,parent_version_sha256:null,source_task_id:task,source_id:'source_test',snapshot_id:'snapshot_test',receipt_sha256:'d'.repeat(64),readiness_receipt_sha256:request.expected_readiness_sha256,status:hold?'REVIEWED_WITH_HOLD':repair?'REVIEWED_ACTION_REQUIRED':'REVIEWED_ALL_QUALIFIED_REFERENCE',qualified_count:qualified,repair_count:repair,hold_count:hold,members:request.members.map(row=>({...row,asset_sha256:row.expected_asset_sha256,annotation_revision:row.expected_annotation_revision,annotation_sha256:row.expected_annotation_sha256,split:row.sample_id.replace('sample_',''),category:'part',repair_cause_codes:[]})),human_review:{reviewer_name:request.reviewer_name,review_note:request.review_note,reviewed_by:'reviewer_test'}};
      window.__projection={pool:{pool_id:'pool_test',origin_task_id:task,current_task_id:task,current_source_id:'source_test',origin_source_id:'source_test',current_snapshot_id:'snapshot_test',origin_snapshot_id:'snapshot_test',current_version_id:'poolv_test',version_ids:['poolv_test'],receipt_sha256:'e'.repeat(64)},current_version:version,read_status:'CURRENT',stale_reasons:[],receipt_sha256:'f'.repeat(64)};
      if(window.__unknownWrite)throw new OperatorApiError(window.__unknownCode??'HTTP_503','Synthetic ambiguous write',window.__unknownStatus??503);
      return structuredClone(window.__projection);
    }
    export async function createDataPoolVersion(scope,poolId,request){window.__writes.push({operation:'version',request});window.__operationRequest=request.request_key;const previous=window.__projection.current_version;Object.assign(window.__projection.pool,{current_task_id:request.source_task_id,current_source_id:'source_repaired',current_snapshot_id:'snapshot_repaired',current_version_id:'poolv_next',version_ids:['poolv_test','poolv_next'],receipt_sha256:'8'.repeat(64)});window.__projection.current_version={...previous,version_id:'poolv_next',version_number:2,parent_version_id:previous.version_id,parent_version_sha256:previous.receipt_sha256,source_task_id:request.source_task_id,source_id:'source_repaired',snapshot_id:'snapshot_repaired',members:request.members.map(row=>({...row,asset_sha256:row.expected_asset_sha256,annotation_revision:row.expected_annotation_revision,annotation_sha256:row.expected_annotation_sha256,split:row.sample_id.replace('sample_',''),category:'part',repair_cause_codes:[]}))};return structuredClone(window.__projection);}
    export async function deriveDataPool(scope,poolId,versionId,request){window.__writes.push({operation:'derive',request});window.__operationRequest=request.request_key;const rows=window.__projection.current_version.members,subset=rows.some(row=>row.disposition!=='QUALIFIED_CANDIDATE');window.__derivation={derivation_id:'poold_test',pool_id:poolId,version_id:versionId,source_task_id:'task_test',parent_source_id:'source_test',qualified_sample_ids:rows.filter(row=>row.disposition==='QUALIFIED_CANDIDATE').map(row=>row.sample_id),excluded_sample_ids:rows.filter(row=>row.disposition!=='QUALIFIED_CANDIDATE').map(row=>row.sample_id),materialization_mode:subset?'DERIVED_QUALIFIED_SUBSET':'FULL_SNAPSHOT_REFERENCE',derived_source_id:subset?'source_derived':null,new_gate_status:subset?'NOT_STARTED':'NOT_APPLICABLE'};return structuredClone(window.__derivation);}
    export async function getDataPoolOperation(scope,operation,key,targetId) {window.__reads.push({kind:'operation',scope,operation,key,targetId});return key===window.__operationRequest&&!window.__operationNotFound?{lookup_status:'FOUND',execution_status:'COMPLETED',result_type:operation==='derive'?'derivation':operation==='version'?'version':'pool',result_id:operation==='derive'?'poold_test':operation==='version'?'poolv_next':'pool_test',current_result:structuredClone(operation==='derive'?window.__derivation:operation==='version'?{version:window.__projection.current_version,read_status:'CURRENT',stale_reasons:[]}:window.__projection)}:{lookup_status:'NOT_FOUND',execution_status:'UNKNOWN_NOT_PROOF_OF_NO_WRITE',current_result:null};}
  `],
  ['\0pool-learning', `
    export async function getLearningReadiness(scope, taskId) {
      window.__reads.push({kind:'readiness', scope, taskId});
      const value = structuredClone(taskId==='task_repaired'?window.__newReadiness:window.__readiness);
      if(window.__holdReadiness) await new Promise(resolve => { window.__releaseReadiness = resolve; });
      return value;
    }
  `],
  ['\0pool-entry.tsx', `
    import {useState} from 'react'; import {createRoot} from 'react-dom/client'; import {MemoryRouter} from 'react-router-dom';
    import {DataPoolsPage,DataPoolReviewForm} from '${path.join(webRoot, 'src/pages/DataPoolsPage.tsx').replaceAll('\\', '/')}';
    import '${path.join(webRoot, 'src/styles/tokens.css').replaceAll('\\', '/')}';
    function Harness() { const [,render] = useState(0); window.__changeProject = projectId => { window.__product = {...window.__product,activeProject:{project_id:projectId,workspace_id:'workspace_test',name:projectId}}; render(x=>x+1); }; window.__showReview = () => {window.__reviewOnly=true;render(x=>x+1);}; return window.__reviewOnly ? <div className="data-pools-page"><DataPoolReviewForm readiness={window.__readiness} visual={window.__visual} canAct={true} onSubmit={async request=>{window.__writes.push(request);}}/></div> : <DataPoolsPage/>; }
    createRoot(document.getElementById('root')).render(<MemoryRouter initialEntries={['/data-pools']}><Harness/></MemoryRouter>);
  `],
]);
before(async () => {
  const result = await build({ root:webRoot, configFile:false, logLevel:'error', define:{'process.env.NODE_ENV':JSON.stringify('production')},
    build:{write:false,minify:false,lib:{entry:'/__pool_entry.tsx',name:'PoolUITest',formats:['iife']}},
    plugins:[{name:'isolated-pool', enforce:'pre', resolveId(id) {
      if(modules.has(id)) return id; if(id.endsWith('__pool_entry.tsx')) return '\0pool-entry.tsx';
      for(const [suffix,target] of [['/ProductContext','context'],['/identitySession','identity'],['/data/api','api'],['/data/learningApi','learning'],['/data/dataPoolApi','client']]) if(id.endsWith(suffix)) return '\0pool-'+target;
    }, load:id=>modules.get(id), transform(code,id) { if(id.startsWith('\0pool-')&&id.endsWith('.tsx')) return transformWithOxc(code,id.slice(1),{lang:'tsx',jsx:{runtime:'automatic'}}); }}],
  });
  const output = (Array.isArray(result)?result[0]:result).output;
  bundle={js:output.find(row=>row.type==='chunk').code,css:output.filter(row=>row.type==='asset'&&row.fileName.endsWith('.css')).map(row=>row.source).join('\n')};
  const executablePath=process.env.VDG_BROWSER_EXECUTABLE || ['C:/Program Files (x86)/Microsoft/Edge/Application/msedge.exe','C:/Program Files/Google/Chrome/Application/chrome.exe'].find(existsSync);
  browser=await chromium.launch({headless:true,...(executablePath?{executablePath}:{})});
});
after(async()=>{await browser?.close();});
async function scenario() {
  const page=await browser.newPage({viewport:{width:1440,height:1100}}), errors=[];
  page.on('pageerror',error=>errors.push(error.message)); page.setDefaultTimeout(8000);
  await page.route('**/*',route=>route.abort());
  await page.route('http://localhost/pool-test',route=>route.fulfill({contentType:'text/html',body:'<!doctype html><html><body style="margin:0;background:#080a0e"><div id="root"></div></body></html>'}));
  await page.goto('http://localhost/pool-test');
  await page.evaluate(()=>{
    window.__identity={user:{user_id:'reviewer_test',status:'ACTIVE'},generation:1};
    window.__product={activeWorkspace:{workspace_id:'workspace_test'},activeProject:{workspace_id:'workspace_test',project_id:'project_test',name:'Synthetic pool project'},connection:{api:'CONNECTED'}};
    window.__tasks=[{task_id:'task_test',workspace_id:'workspace_test',project_id:'project_test',source_kind:'local_authorized_directory',source_id:'source_test',execution_status:'COMPLETED',final_decision:'PASS',goal:'Synthetic reviewed members'}, {task_id:'synthetic_task',workspace_id:'workspace_test',project_id:'project_test',source_kind:'synthetic_demo',source_id:null,execution_status:'COMPLETED',goal:'Not an authorized source'}];
    window.__readiness={schema_version:'visiondata-gate.learning-readiness.v1',task_id:'task_test',workspace_id:'workspace_test',project_id:'project_test',projection_status:'VERIFIED',preflight_receipt_sha256:'a'.repeat(64),preflight_eligibility:'READY_FOR_OFFLINE_HANDOFF',blockers:[],members:['train','val','test'].map(split=>({sample_id:'sample_'+split,split,category:'synthetic-part',annotation_requirement:'REQUIRED',mask_available:true,readiness_state:'GATE_ELIGIBLE_NOT_TRAINING_APPROVED',finding_refs:[]})),global_findings:[],unmapped_finding_refs:[],training_authorized:false,production_release_allowed:false,annotation_review_basis:'OPERATOR_ATTESTATION_NOT_INDEPENDENT_TRUTH',required_dataset_validation:[],claim_boundary:'Synthetic fixture only',receipt_sha256:'b'.repeat(64)};
    window.__visual={workspace_id:'workspace_test',project_id:'project_test',task_id:'task_test',source_id:'source_test',operator_snapshot_receipt_sha256:'a'.repeat(64),items:['train','val','test'].map(split=>({sample_id:'sample_'+split,source_sha256:'c'.repeat(64),annotation_revision:3,annotation_document_sha256:'d'.repeat(64)}))};
    window.__reads=[]; window.__writes=[];
  });
  await page.addStyleTag({content:bundle.css}); await page.addScriptTag({content:bundle.js});
  await page.getByLabel('数据池来源任务').waitFor();
  await page.waitForFunction(()=>document.querySelector('option[value="task_test"]'));
  return {page,errors};
}
test('task selection is explicit; only completed authorized current-project tasks are offered',async()=>{
  const {page,errors}=await scenario();
  assert.equal(await page.getByLabel('数据池来源任务').inputValue(),'');
  assert.equal(await page.locator('option[value="synthetic_task"]').count(),0);
  assert.equal(await page.evaluate(()=>window.__reads.filter(row=>row.kind==='readiness').length),0);
  await page.getByLabel('数据池来源任务').selectOption('task_test');
  await page.getByRole('heading',{name:'当前冻结成员 · 3 项',exact:true}).waitFor();
  assert.equal(await page.getByRole('link',{name:'sample_train',exact:true}).getAttribute('href'),'/workspace?purpose=annotation-rework&asset=sample_train');
  assert.equal(await page.evaluate(()=>window.__writes.length),0); assert.deepEqual(errors,[]);
  mkdirSync(path.join(root,'output/playwright'),{recursive:true});
  await page.screenshot({path:path.join(root,'output/playwright/data-pools-workbench.png'),fullPage:true}); await page.close();
});
test('global findings remain visible and cannot imply the remaining members passed',async()=>{
  const {page,errors}=await scenario();
  await page.evaluate(()=>{window.__readiness.global_findings=[{finding_id:'global_finding',code:'COVERAGE_GAP',severity:'high',finding_sha256:'c'.repeat(64)}];window.__readiness.blockers=['GATE_NOT_PASS'];window.__readiness.members.forEach(row=>{row.readiness_state='BLOCKED_BY_BATCH';});});
  await page.getByLabel('数据池来源任务').selectOption('task_test');
  await page.getByText('全局问题：COVERAGE_GAP',{exact:true}).waitFor();
  assert.equal(await page.getByText('批次未通过 · 不推断本样本合格',{exact:true}).count(),3);
  assert.equal(await page.evaluate(()=>window.__writes.length),0); assert.deepEqual(errors,[]); await page.close();
});
test('project and identity changes discard old in-flight evidence',async()=>{
  const {page,errors}=await scenario();
  await page.evaluate(()=>{window.__holdReadiness=true;}); await page.getByLabel('数据池来源任务').selectOption('task_test');
  await page.waitForFunction(()=>typeof window.__releaseReadiness==='function');
  await page.evaluate(()=>{window.__changeProject('project_other');window.__releaseReadiness();});
  await page.getByRole('alert').waitFor();
  assert.equal(await page.getByRole('link',{name:'sample_train',exact:true}).count(),0);
  await page.evaluate(()=>window.__changeIdentity(undefined)); await page.getByText('请先登录已启用的账号；未登录不会读取项目数据。',{exact:true}).waitFor();
  assert.equal(await page.getByLabel('数据池来源任务').count(),0); assert.deepEqual(errors,[]); await page.close();
});
test('every disposition starts blank and an explicit full-member review binds image and annotation identities',async()=>{
  const {page,errors}=await scenario(); await page.evaluate(()=>window.__showReview());
  for(const split of ['train','val','test']) assert.equal(await page.getByLabel('成员去向 sample_'+split,{exact:true}).inputValue(),'');
  assert.equal(await page.getByRole('button',{name:'保存数据池审核版本',exact:true}).isDisabled(),true);
  for(const split of ['train','val','test']) {
    await page.getByLabel('成员去向 sample_'+split,{exact:true}).selectOption('QUALIFIED_CANDIDATE');
    await page.getByLabel('处置说明 sample_'+split,{exact:true}).fill('Reviewed this exact frozen member and annotation.');
  }
  await page.getByLabel('数据池复核人',{exact:true}).fill('Synthetic reviewer');
  await page.getByLabel('数据池审核说明',{exact:true}).fill('All frozen members were explicitly reviewed.');
  assert.equal(await page.getByRole('button',{name:'保存数据池审核版本',exact:true}).isDisabled(),true);
  await page.getByLabel('确认逐成员数据池复核',{exact:true}).check();
  await page.getByRole('button',{name:'保存数据池审核版本',exact:true}).click();
  const writes=await page.evaluate(()=>window.__writes); assert.equal(writes.length,1); assert.equal(writes[0].members.length,3);
  for(const row of writes[0].members) { assert.equal(row.expected_asset_sha256,'c'.repeat(64));assert.equal(row.expected_annotation_revision,3);assert.equal(row.expected_annotation_sha256,'d'.repeat(64));assert.equal(row.repair_result,'NOT_APPLICABLE');assert.equal('label' in row,false); }
  assert.deepEqual(errors,[]); await page.close();
});
test('a global finding disables qualified disposition even when the synthetic Gate says PASS',async()=>{
  const {page,errors}=await scenario();
  await page.evaluate(()=>{window.__readiness.global_findings=[{finding_id:'finding_global',code:'COVERAGE_GAP'}];window.__showReview();});
  for(const split of ['train','val','test']) {
    const option=page.getByLabel('成员去向 sample_'+split,{exact:true}).locator('option[value="QUALIFIED_CANDIDATE"]');
    // Playwright's generic isDisabled() does not classify disabled <option>s.
    // Assert the actual native option property; the parent <select> stays usable for HOLD.
    assert.equal(await option.evaluate(node=>node.disabled),true);
  }
  assert.equal(await page.getByRole('button',{name:'保存数据池审核版本',exact:true}).isDisabled(),true);
  assert.equal(await page.evaluate(()=>window.__writes.length),0);assert.deepEqual(errors,[]);await page.close();
});
async function fillIntegratedReview(page) {
  await page.getByLabel('数据池来源任务').selectOption('task_test');
  for(const split of ['train','val','test']){await page.getByLabel('成员去向 sample_'+split,{exact:true}).selectOption('QUALIFIED_CANDIDATE');await page.getByLabel('处置说明 sample_'+split,{exact:true}).fill('Reviewed exact frozen member.');}
  await page.getByLabel('数据池复核人',{exact:true}).fill('Named reviewer');await page.getByLabel('数据池审核说明',{exact:true}).fill('Reviewed every frozen member explicitly.');await page.getByLabel('确认逐成员数据池复核',{exact:true}).check();
}
test('integrated save requires an explicit GET reconciliation; an unknown write stays locked across reload of the view',async()=>{
  const {page,errors}=await scenario();await fillIntegratedReview(page);
  await page.evaluate(()=>{window.__unknownWrite=true;});await page.getByRole('button',{name:'保存数据池审核版本',exact:true}).click();
  await page.getByText('写入结果待对账',{exact:true}).waitFor();
  assert.equal(await page.evaluate(()=>window.__writes.length),1);
  assert.equal(await page.getByRole('button',{name:'保存数据池审核版本',exact:true}).isDisabled(),true);
  await page.evaluate(()=>window.__changeIdentity({user_id:'reviewer_test',status:'ACTIVE'}));
  await page.getByText('写入结果待对账',{exact:true}).waitFor();
  assert.equal(await page.evaluate(()=>window.__writes.length),1);
  await page.evaluate(()=>{window.__operationNotFound=true;});
  await page.getByRole('button',{name:'仅 GET 对账',exact:true}).click();
  await page.getByText('GET 尚未找到原请求完成凭据；保留 HOLD，不重发写入。',{exact:true}).waitFor();
  assert.equal(await page.getByText('写入结果待对账',{exact:true}).count(),1);
  await page.evaluate(()=>{window.__operationNotFound=false;});
  await page.getByRole('button',{name:'仅 GET 对账',exact:true}).click();
  await page.getByText('已通过 GET 核验原请求结果；未重发写入。',{exact:true}).waitFor();
  assert.equal(await page.evaluate(()=>window.__writes.length),1);
  assert.ok((await page.evaluate(()=>window.__reads)).some(row=>row.kind==='operation'));
  assert.deepEqual(errors,[]);await page.close();
});
test('all-qualified derivation is a reference, never a fake new source or auto Gate',async()=>{
  const {page,errors}=await scenario();await fillIntegratedReview(page);await page.getByRole('button',{name:'保存数据池审核版本',exact:true}).click();
  await page.getByText('已通过 GET 核验原请求结果；未重发写入。',{exact:true}).waitFor();
  await page.getByLabel('数据池派生说明',{exact:true}).fill('Reference the complete reviewed frozen snapshot.');await page.getByLabel('确认数据池派生',{exact:true}).check();
  await page.getByRole('button',{name:'派生已复核候选来源',exact:true}).click();
  await page.getByText('全部成员引用原快照 · 未制造新数据版本',{exact:true}).waitFor();
  assert.equal(await page.getByRole('link',{name:'使用该新来源创建 Gate（仍需计划审批）',exact:true}).count(),0);
  await page.evaluate(()=>window.__changeIdentity({user_id:'reviewer_test',status:'ACTIVE'}));
  await page.getByText('全部成员引用原快照 · 未制造新数据版本',{exact:true}).waitFor();
  assert.deepEqual((await page.evaluate(()=>window.__writes)).map(row=>row.operation),['create','derive']);assert.deepEqual(errors,[]);await page.close();
});
test('a reviewed subset only exposes the exact new source Gate entry and leaves NOT_STARTED HOLD',async()=>{
  const {page,errors}=await scenario();
  await page.evaluate(()=>{window.__tasks[0].final_decision='QUARANTINE';window.__readiness.preflight_eligibility='HOLD';window.__readiness.blockers=['GATE_NOT_PASS'];window.__readiness.members.forEach(row=>{row.readiness_state=row.split==='test'?'NEEDS_ATTENTION':'BLOCKED_BY_BATCH';row.finding_refs=row.split==='test'?[{finding_id:'finding_test',code:'BLUR',severity:'high',finding_sha256:'e'.repeat(64)}]:[];});});
  await page.getByLabel('数据池来源任务').selectOption('task_test');
  for(const split of ['train','val'])await page.getByLabel('成员去向 sample_'+split,{exact:true}).selectOption('QUALIFIED_CANDIDATE');
  await page.getByLabel('成员去向 sample_test',{exact:true}).selectOption('REPAIR_REQUIRED');await page.getByLabel('返修动作 sample_test',{exact:true}).selectOption('RECAPTURE');await page.getByLabel('返修结果 sample_test',{exact:true}).selectOption('PENDING');
  for(const split of ['train','val','test'])await page.getByLabel('处置说明 sample_'+split,{exact:true}).fill('Reviewed frozen evidence and preserved original split.');
  await page.getByLabel('数据池复核人',{exact:true}).fill('Named reviewer');await page.getByLabel('数据池审核说明',{exact:true}).fill('Explicitly reviewed partial qualification and mapped repair.');await page.getByLabel('确认逐成员数据池复核',{exact:true}).check();await page.getByRole('button',{name:'保存数据池审核版本',exact:true}).click();
  await page.getByText('已通过 GET 核验原请求结果；未重发写入。',{exact:true}).waitFor();await page.getByLabel('数据池派生说明',{exact:true}).fill('Derive two reviewed candidates for another approved Gate.');await page.getByLabel('确认数据池派生',{exact:true}).check();await page.getByRole('button',{name:'派生已复核候选来源',exact:true}).click();
  await page.getByText('新来源已建立 · 新 Gate 尚未开始 · HOLD',{exact:true}).waitFor();
  assert.equal(await page.getByRole('link',{name:'使用该新来源创建 Gate（仍需计划审批）',exact:true}).getAttribute('href'),'/command-center?source=source_derived&create=1');
  assert.deepEqual((await page.evaluate(()=>window.__writes)).map(row=>row.operation),['create','derive']);assert.deepEqual(errors,[]);await page.close();
});
test('account changes cannot reveal or clear the previous account pending-write lock',async()=>{
  const {page,errors}=await scenario();await fillIntegratedReview(page);await page.evaluate(()=>{window.__unknownWrite=true;});await page.getByRole('button',{name:'保存数据池审核版本',exact:true}).click();await page.getByText('写入结果待对账',{exact:true}).waitFor();
  await page.evaluate(()=>window.__changeIdentity({user_id:'other_reviewer',status:'ACTIVE'}));
  await page.getByLabel('数据池来源任务').waitFor();assert.equal(await page.getByText('写入结果待对账',{exact:true}).count(),0);
  await page.evaluate(()=>window.__changeIdentity({user_id:'reviewer_test',status:'ACTIVE'}));await page.getByText('写入结果待对账',{exact:true}).waitFor();
  assert.equal(await page.evaluate(()=>window.__writes.length),1);assert.deepEqual(errors,[]);await page.close();
});
test('a newer pool version invalidates a previously checked derivation confirmation',async()=>{
  const {page,errors}=await scenario();await fillIntegratedReview(page);await page.getByRole('button',{name:'保存数据池审核版本',exact:true}).click();await page.getByText('已通过 GET 核验原请求结果；未重发写入。',{exact:true}).waitFor();
  await page.getByLabel('数据池派生说明',{exact:true}).fill('This review is for version one only.');await page.getByLabel('确认数据池派生',{exact:true}).check();
  await page.evaluate(()=>{window.__projection.pool.current_version_id='poolv_next';window.__projection.pool.version_ids.push('poolv_next');window.__projection.pool.receipt_sha256='9'.repeat(64);Object.assign(window.__projection.current_version,{version_id:'poolv_next',version_number:2,parent_version_id:'poolv_test',parent_version_sha256:'d'.repeat(64)});});
  await page.getByRole('button',{name:'刷新服务端事实',exact:true}).click();await page.getByRole('heading',{name:'已保存审核版本 · 第 2 版',exact:true}).waitFor();
  assert.equal(await page.getByLabel('确认数据池派生',{exact:true}).isChecked(),false);
  assert.equal(await page.getByRole('button',{name:'派生已复核候选来源',exact:true}).isDisabled(),true);assert.deepEqual(errors,[]);await page.close();
});
test('a backend evidence HOLD after dispatch is not treated as proof of no side effect',async()=>{
  const {page,errors}=await scenario();await fillIntegratedReview(page);await page.evaluate(()=>{window.__unknownWrite=true;window.__unknownCode='data_pool_hold';window.__unknownStatus=409;});await page.getByRole('button',{name:'保存数据池审核版本',exact:true}).click();
  await page.getByRole('alert').waitFor();assert.equal(await page.getByText('写入结果待对账',{exact:true}).count(),1);
  assert.equal(await page.evaluate(()=>window.__writes.length),1);assert.deepEqual(errors,[]);await page.close();
});
test('narrow workbench layouts keep form fields inside the viewport',async()=>{
  const {page,errors}=await scenario();await page.setViewportSize({width:390,height:844});await page.getByLabel('数据池来源任务').selectOption('task_test');await page.getByLabel('成员去向 sample_train',{exact:true}).waitFor();
  const bounds=await page.evaluate(()=>({width:window.innerWidth,scroll:document.documentElement.scrollWidth}));assert.ok(bounds.scroll<=bounds.width,JSON.stringify(bounds));
  assert.deepEqual(errors,[]);await page.close();
});
test('a repaired task creates a complete new reviewed version instead of appending old members',async()=>{
  const {page,errors}=await scenario();await fillIntegratedReview(page);await page.getByRole('button',{name:'保存数据池审核版本',exact:true}).click();await page.getByText('已通过 GET 核验原请求结果；未重发写入。',{exact:true}).waitFor();
  await page.evaluate(()=>{window.__tasks.push({...window.__tasks[0],task_id:'task_repaired',source_id:'source_repaired',goal:'New repaired full snapshot'});window.__newReadiness={...structuredClone(window.__readiness),task_id:'task_repaired',receipt_sha256:'7'.repeat(64)};window.__newVisual={...structuredClone(window.__visual),task_id:'task_repaired',source_id:'source_repaired',operator_snapshot_receipt_sha256:'5'.repeat(64)};window.__newVisual.items.forEach(row=>{row.source_sha256='6'.repeat(64);row.annotation_revision=4;});});
  await page.getByRole('button',{name:'刷新服务端事实',exact:true}).click();await page.getByLabel('数据池来源任务').selectOption('task_repaired');
  await page.getByRole('heading',{name:'重新逐项复核 · 新审核版本',exact:true}).waitFor();
  for(const split of ['train','val','test']){assert.equal(await page.getByLabel('成员去向 sample_'+split,{exact:true}).inputValue(),'');await page.getByLabel('成员去向 sample_'+split,{exact:true}).selectOption('QUALIFIED_CANDIDATE');await page.getByLabel('处置说明 sample_'+split,{exact:true}).fill('Reviewed the new complete frozen data version.');}
  await page.getByLabel('数据池复核人',{exact:true}).fill('Named reviewer');await page.getByLabel('数据池审核说明',{exact:true}).fill('Explicitly reviewed every member from the repaired task.');await page.getByLabel('确认逐成员数据池复核',{exact:true}).check();await page.getByRole('button',{name:'保存新的审核版本',exact:true}).click();
  await page.getByRole('heading',{name:'已保存审核版本 · 第 2 版',exact:true}).waitFor();
  const request=await page.evaluate(()=>window.__writes.find(row=>row.operation==='version').request);assert.equal(request.source_task_id,'task_repaired');assert.equal(request.expected_parent_version_sha256,'d'.repeat(64));assert.equal(request.members.length,3);assert.equal(new Set(request.members.map(row=>row.sample_id)).size,3);assert.ok(request.members.every(row=>row.expected_asset_sha256==='6'.repeat(64)&&row.expected_annotation_revision===4));
  assert.equal(await page.getByRole('link',{name:'查看该版本冻结任务',exact:true}).getAttribute('href'),'/command-center?task=task_repaired');assert.deepEqual(errors,[]);await page.close();
});
