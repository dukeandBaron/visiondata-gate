import test from 'node:test';
import assert from 'node:assert/strict';
import * as domain from '../web/src/dataPoolDomain.ts';
import { existsSync } from 'node:fs';
import { registerHooks } from 'node:module';
import { spawnSync } from 'node:child_process';
import { fileURLToPath } from 'node:url';
import { validateLearningReadiness } from '../web/src/learningDomain.ts';
import { poolPendingStorageKey, readPoolPendingWrite, persistPoolPendingWrite, clearPoolPendingWrite, validatePoolPendingWrite, validateCreateDataPoolRequest, poolMemberCanQualify } from '../web/src/dataPoolDomain.ts';

// Synthetic memory-only storage; no user's browser, database or training data is used.
function storage() {
  const map = new Map();
  return { getItem: key => map.get(key) ?? null, setItem: (key, value) => map.set(key, value), removeItem: key => map.delete(key) };
}
const scope = { workspaceId: 'workspace_test', projectId: 'project_test' };
const pending = { requestKey: 'request_test_1234', operation: 'create', targetId: 'task_test', requestSha256: 'a'.repeat(64) };
const hold = { code: 'DATA_POOL_CONTRACT_HOLD' };

test('pending writes are bound to account, workspace and project without storing credentials', () => {
  const key = poolPendingStorageKey('reviewer_test', scope);
  assert.notEqual(key, poolPendingStorageKey('other_reviewer', scope));
  assert.notEqual(key, poolPendingStorageKey('reviewer_test', { ...scope, projectId: 'project_other' }));
  assert.throws(() => poolPendingStorageKey('', scope), hold);
  assert.throws(() => validatePoolPendingWrite({ ...pending, sessionToken: 'do-not-store' }), hold);
});
test('pending request is persisted before dispatch and cannot be overwritten', () => {
  const store = storage(); persistPoolPendingWrite(store, 'lock', pending);
  assert.deepEqual(readPoolPendingWrite(store, 'lock'), pending);
  assert.throws(() => persistPoolPendingWrite(store, 'lock', { ...pending, requestKey: 'different_request_1234' }), hold);
  assert.deepEqual(readPoolPendingWrite(store, 'lock'), pending);
});
test('corrupt or unavailable storage fails closed instead of clearing a possible write', () => {
  const store = storage(); store.setItem('lock', '{malformed');
  assert.deepEqual(readPoolPendingWrite(store, 'lock'), { corrupt: true });
  assert.throws(() => persistPoolPendingWrite(store, 'lock', pending), hold);
  assert.deepEqual(readPoolPendingWrite({ getItem() { throw new Error('unavailable'); } }, 'lock'), { corrupt: true });
});
test('a cleared lock must match the exact original request and read back as removed', () => {
  const store = storage(); persistPoolPendingWrite(store, 'lock', pending);
  assert.throws(() => clearPoolPendingWrite(store, 'lock', { ...pending, targetId: 'task_other' }), hold);
  clearPoolPendingWrite(store, 'lock', pending);
  assert.equal(readPoolPendingWrite(store, 'lock'), null);
});
test('pool requests require explicit member decisions and never accept client labels or paths', () => {
  const row = { sample_id:'sample_train',expected_asset_sha256:'a'.repeat(64),expected_annotation_revision:2,expected_annotation_sha256:'b'.repeat(64),disposition:'QUALIFIED_CANDIDATE',repair_action:'NONE',repair_result:'NOT_APPLICABLE',decision_note:'Reviewed exact frozen member.' };
  const request = { request_key:'request_pool_1234',expected_readiness_sha256:'c'.repeat(64),reviewer_name:'Named reviewer',review_note:'Reviewed every member in the frozen task.',operator_attests_reviewed:true,members:[row] };
  assert.deepEqual(validateCreateDataPoolRequest(request), request);
  for (const patch of [{disposition:''},{disposition:'GOOD'},{disposition:'REPAIR_REQUIRED'},{label_truth_authority:true},{root_path:'C:/private'}]) {
    assert.throws(()=>validateCreateDataPoolRequest({...request,members:[{...row,...patch}]}),hold);
  }
  assert.throws(()=>validateCreateDataPoolRequest({...request,members:[row,row]}),hold);
  assert.throws(()=>validateCreateDataPoolRequest({...request,operator_attests_reviewed:false}),hold);
});
test('qualification guard excludes global, unmapped, tool, coverage and unknown evidence', () => {
  const row={sample_id:'sample_train',readiness_state:'GATE_ELIGIBLE_NOT_TRAINING_APPROVED',annotation_requirement:'REQUIRED',finding_refs:[]};
  const readiness={projection_status:'VERIFIED',global_findings:[],unmapped_finding_refs:[],blockers:[],preflight_eligibility:'READY_FOR_OFFLINE_HANDOFF',members:[row]};
  assert.equal(poolMemberCanQualify(readiness,'sample_train'),true);
  assert.equal(poolMemberCanQualify(readiness,'unknown'),false);
  for(const patch of [{global_findings:[{}]},{unmapped_finding_refs:[{}]},{projection_status:'UNVERIFIED'}, ...['DETERMINISTIC_TOOL_FAILURE','REQUIRED_TOOL_EVIDENCE_INCOMPLETE','COVERAGE_GAP'].map(code=>({blockers:[code]}))]) assert.equal(poolMemberCanQualify({...readiness,...patch},'sample_train'),false);
  assert.equal(poolMemberCanQualify({...readiness,members:[{...row,annotation_requirement:'UNKNOWN'}]},'sample_train'),false);
});
test('a batch hold alone never makes the unmentioned remainder qualified',()=>{
  const row={sample_id:'sample_train',readiness_state:'BLOCKED_BY_BATCH',annotation_requirement:'REQUIRED',finding_refs:[]};
  const value={projection_status:'VERIFIED',global_findings:[],unmapped_finding_refs:[],blockers:['GATE_NOT_PASS'],preflight_eligibility:'HOLD',members:[row]};
  assert.equal(poolMemberCanQualify(value,'sample_train'),false);
  const mapped={...value,members:[row,{...row,sample_id:'sample_bad',readiness_state:'NEEDS_ATTENTION',finding_refs:[{code:'BLUR'}]}]};
  assert.equal(poolMemberCanQualify(mapped,'sample_train'),true);
  assert.equal(poolMemberCanQualify(mapped,'sample_bad'),false);
});
test('normal unmasked members need explicit optional policy and verified empty frozen annotations',()=>{
  const row={sample_id:'normal_train',readiness_state:'MASK_REQUIRED_FOR_REFERENCE_TRAINER',annotation_requirement:'OPTIONAL',mask_available:false,finding_refs:[]};
  const readiness={projection_status:'VERIFIED',global_findings:[],unmapped_finding_refs:[],blockers:[],preflight_eligibility:'READY_FOR_OFFLINE_HANDOFF',members:[row]};
  assert.equal(poolMemberCanQualify(readiness,'normal_train'),false);
  assert.equal(poolMemberCanQualify(readiness,'normal_train',{annotation_count:0,mask_sha256:null}),true);
  assert.equal(poolMemberCanQualify(readiness,'normal_train',{annotation_count:1,mask_sha256:null}),false);
  assert.equal(poolMemberCanQualify({...readiness,members:[{...row,annotation_requirement:'REQUIRED'}]},'normal_train',{annotation_count:0,mask_sha256:null}),false);
});
const digest = value => domain.dataPoolDigest(value);
const sealed = async value => {const body={...value};delete body.receipt_sha256;return {...body,receipt_sha256:await digest(body)};};
export async function projectionFixture() {
  const finding=[];
  const version=await sealed({schema_version:'visiondata-gate.data-pool-version.v1',version_id:'poolv_test',pool_id:'pool_test',version_number:1,parent_version_id:null,parent_version_sha256:null,source_task_id:'task_test',workspace_id:scope.workspaceId,project_id:scope.projectId,source_id:'source_test',snapshot_id:'snapshot_test',snapshot_receipt_sha256:'a'.repeat(64),batch_manifest_sha256:'a'.repeat(64),batch_contract_sha256:'a'.repeat(64),gate_result_sha256:'a'.repeat(64),readiness_receipt_sha256:'a'.repeat(64),preflight_receipt_sha256:'a'.repeat(64),status:'REVIEWED_ALL_QUALIFIED_REFERENCE',qualified_count:1,repair_count:0,hold_count:0,members:[{sample_id:'sample_train',source_task_id:'task_test',split:'train',category:'part',annotation_requirement:'REQUIRED',readiness_state:'GATE_ELIGIBLE_NOT_TRAINING_APPROVED',asset_sha256:'a'.repeat(64),annotation_revision:2,annotation_sha256:'b'.repeat(64),mask_sha256:'c'.repeat(64),finding_refs:finding,repair_cause_codes:[],disposition:'QUALIFIED_CANDIDATE',repair_action:'NONE',repair_result:'NOT_APPLICABLE',decision_note:'Explicit frozen review',label_truth_authority:false}],global_finding_refs:[],unmapped_finding_refs:[],readiness_blockers:[],human_review:{reviewer_name:'Named reviewer',review_note:'Every frozen member reviewed.',reviewed_by:'reviewer_test',operator_attests_reviewed:true},created_at:'2026-09-13T00:00:00Z',label_truth_authority:false,training_ingestion_allowed:false,production_release_allowed:false});
  const pool=await sealed({schema_version:'visiondata-gate.data-pool.v1',pool_id:'pool_test',workspace_id:scope.workspaceId,project_id:scope.projectId,origin_task_id:'task_test',current_task_id:'task_test',origin_source_id:'source_test',current_source_id:'source_test',origin_snapshot_id:'snapshot_test',current_snapshot_id:'snapshot_test',version_ids:['poolv_test'],current_version_id:'poolv_test',created_by:'reviewer_test',created_at:'2026-09-13T00:00:00Z',label_truth_authority:false,production_release_allowed:false});
  return sealed({schema_version:'visiondata-gate.data-pool-projection.v1',pool,current_version:version,read_status:'CURRENT',stale_reasons:[],training_ingestion_allowed:false,production_release_allowed:false});
}
test('projection verifies all nested SHA receipts, strong ETag and current source/version identity',async()=>{
  assert.equal(typeof domain.validateDataPoolProjection,'function');
  const value=await projectionFixture();
  assert.equal((await domain.validateDataPoolProjection(value,scope,'pool_test',`"${value.receipt_sha256}"`)).pool.pool_id,'pool_test');
  for(const etag of [null,'',value.receipt_sha256,`W/"${value.receipt_sha256}"`]) await assert.rejects(domain.validateDataPoolProjection(value,scope,'pool_test',etag),hold);
  await assert.rejects(domain.validateDataPoolProjection({...value,read_status:'STALE_HOLD'},scope),hold);
  const wrong=await sealed({...value,pool:await sealed({...value.pool,current_source_id:'source_other'})});
  await assert.rejects(domain.validateDataPoolProjection(wrong,scope),hold);
});
test('freshly rehashed privilege escalation, fake counts and cross-account scope still fail',async()=>{
  assert.equal(typeof domain.validateDataPoolProjection,'function');
  const value=await projectionFixture();
  for(const patch of [{qualified_count:2},{training_ingestion_allowed:true},{label_truth_authority:true},{status:'GOOD'},{project_id:'project_other'}]) {
    const forged=await sealed({...value,current_version:await sealed({...value.current_version,...patch})});
    await assert.rejects(domain.validateDataPoolProjection(forged,scope),hold);
  }
});
test('API validates local requests before dispatch, sends once and verifies content/ETag',async()=>{
  assert.equal(existsSync(new URL('../web/src/data/dataPoolApi.ts',import.meta.url)),true);
  const stub='data:text/javascript,'+encodeURIComponent(`export class OperatorApiError extends Error {constructor(code,message,status){super(message);this.code=code;this.status=status;}} export function operatorFetch(...args){return globalThis.__dataPoolTransport(...args);}`);
  const hooks=registerHooks({resolve(specifier,context,next){if(context.parentURL?.endsWith('/data/dataPoolApi.ts')&&['./api','./api.ts'].includes(specifier))return {url:stub,shortCircuit:true};return next(specifier,context);}});
  const api=await import('../web/src/data/dataPoolApi.ts');hooks.deregister();let calls=[];
  const value=await projectionFixture();globalThis.__dataPoolTransport=async(...args)=>{calls.push(args);return new Response(JSON.stringify(value),{headers:{'Content-Type':'application/json',ETag:`"${value.receipt_sha256}"`,'X-Content-SHA256':value.receipt_sha256}});};
  await assert.rejects(api.createDataPool(scope,'task_test',{}),{code:'DATA_POOL_REQUEST_NOT_SENT'});assert.equal(calls.length,0);
  assert.equal((await api.getDataPool(scope,'pool_test')).pool.pool_id,'pool_test');assert.equal(calls.length,1);
  globalThis.__dataPoolTransport=async()=>new Response(JSON.stringify(value),{headers:{'Content-Type':'application/json'}});
  await assert.rejects(api.getDataPool(scope,'pool_test'),{code:'DATA_POOL_CONTRACT_HOLD'});
});
test('the frontend projection fixture roundtrips through the actual Python DTO without changing sealed content',async()=>{
  const executable=process.env.VDG_PYTHON_EXECUTABLE
    || ['../.venv/Scripts/python.exe','../.venv/bin/python'].map(relative=>fileURLToPath(new URL(relative,import.meta.url))).find(existsSync)
    || (process.platform==='win32'?'python':'python3');
  const value=await projectionFixture();
  const result=spawnSync(executable,['-c','import json,sys; from visiondata_gate.data_pool import DataPoolProjection; print(json.dumps(DataPoolProjection.model_validate(json.load(sys.stdin)).model_dump(mode="json")))'],{cwd:fileURLToPath(new URL('..',import.meta.url)),input:JSON.stringify(value),encoding:'utf8',timeout:30000});
  assert.equal(result.status,0,result.stderr);assert.deepEqual(JSON.parse(result.stdout),value);
});
test('a derivation can only be a full reference or a new source awaiting its new Gate',async()=>{
  const full=await sealed({schema_version:'visiondata-gate.data-pool-derivation.v1',derivation_id:'poold_test',pool_id:'pool_test',version_id:'poolv_test',workspace_id:scope.workspaceId,project_id:scope.projectId,source_task_id:'task_test',qualified_sample_ids:['sample_train'],excluded_sample_ids:[],materialization_mode:'FULL_SNAPSHOT_REFERENCE',parent_source_id:'source_test',derived_source_id:null,derived_snapshot_id:'snapshot_test',derived_snapshot_receipt_sha256:null,new_source_authorization_created:false,new_gate_required:false,plan_approval_required:false,new_gate_status:'NOT_APPLICABLE',source_authorization_status:'ACTIVE',created_by:'reviewer_test',created_at:'2026-09-13T00:00:00Z',human_review_note:'Explicit bounded derivation.',training_ingestion_allowed:false,label_truth_authority:false,production_release_allowed:false});
  assert.equal((await domain.validateDataPoolDerivation(full,scope,'pool_test','poolv_test')).materialization_mode,'FULL_SNAPSHOT_REFERENCE');
  const subset=await sealed({...full,materialization_mode:'DERIVED_QUALIFIED_SUBSET',excluded_sample_ids:['sample_repair'],derived_source_id:'source_new',derived_snapshot_receipt_sha256:'d'.repeat(64),new_source_authorization_created:true,new_gate_required:true,plan_approval_required:true,new_gate_status:'NOT_STARTED'});
  assert.equal((await domain.validateDataPoolDerivation(subset,scope)).new_gate_status,'NOT_STARTED');
  for(const patch of [{new_gate_status:'PASS'},{training_ingestion_allowed:true},{new_gate_required:false},{derived_source_id:'source_test'},{qualified_sample_ids:['sample_repair']}])await assert.rejects(domain.validateDataPoolDerivation(await sealed({...subset,...patch}),scope),hold);
});
test('operation lookup binds the original target/key and NOT_FOUND never proves no write',async()=>{
  const value=await sealed({schema_version:'visiondata-gate.data-pool-operation.v1',project_id:scope.projectId,operation:'create',target_id:'task_test',request_key:'request_pool_1234',lookup_status:'NOT_FOUND',execution_status:'UNKNOWN_NOT_PROOF_OF_NO_WRITE',result_type:null,result_id:null,current_result:null,result_semantics:'CURRENT_RESULT',automatic_retry_allowed:false});
  assert.equal((await domain.validateDataPoolOperation(value,scope,'create','request_pool_1234','task_test')).automatic_retry_allowed,false);
  await assert.rejects(domain.validateDataPoolOperation(value,scope,'create','request_other_1234','task_test'),hold);
  const forged=await sealed({...value,execution_status:'COMPLETED'});await assert.rejects(domain.validateDataPoolOperation(forged,scope,'create','request_pool_1234','task_test'),hold);
  const found=await sealed({...value,lookup_status:'FOUND',execution_status:'COMPLETED',result_type:'pool',result_id:'pool_test',current_result:await projectionFixture()});
  assert.equal((await domain.validateDataPoolOperation(found,scope,'create','request_pool_1234','task_test')).lookup_status,'FOUND');
});
test('the final sealed readiness DTO permits only a clean mapped-finding complement',async()=>{
  const finding={finding_id:'finding_blur',code:'BLUR',severity:'high',finding_sha256:'c'.repeat(64)};
  const value=await sealed({schema_version:'visiondata-gate.learning-readiness.v1',task_id:'task_test',workspace_id:scope.workspaceId,project_id:scope.projectId,projection_status:'VERIFIED',preflight_receipt_sha256:'a'.repeat(64),preflight_eligibility:'HOLD',blockers:['GATE_NOT_PASS'],members:['train','val','test'].map(split=>({sample_id:`sample_${split}`,split,category:'part',annotation_requirement:'REQUIRED',mask_available:true,readiness_state:split==='val'?'NEEDS_ATTENTION':'BLOCKED_BY_BATCH',finding_refs:split==='val'?[finding]:[]})),global_findings:[],unmapped_finding_refs:[],training_authorized:false,production_release_allowed:false,annotation_review_basis:'OPERATOR_ATTESTATION_NOT_INDEPENDENT_TRUTH',required_dataset_validation:['GROUP_DECLARATIONS','BINARY_MASK_VALUES','TRAIN_VAL_TEST_COVERAGE','GROUP_AND_PIXEL_SPLIT_ISOLATION','IMAGE_MASK_SHAPES_AND_RESOURCE_LIMITS'],claim_boundary:'Frozen readiness only; candidates still require an independent new Gate and training authorization.'});
  const checked=await validateLearningReadiness(value,scope,'task_test',`"${value.receipt_sha256}"`);
  assert.equal(poolMemberCanQualify(checked,'sample_train'),true);
  assert.equal(poolMemberCanQualify(checked,'sample_test'),true);
  assert.equal(poolMemberCanQualify(checked,'sample_val'),false);
  for(const patch of [{global_findings:[finding]},{unmapped_finding_refs:[finding]},{blockers:['GATE_NOT_PASS','DETERMINISTIC_TOOL_FAILURE']},{blockers:['GATE_NOT_PASS','REQUIRED_TOOL_EVIDENCE_INCOMPLETE']},{blockers:[]},{preflight_eligibility:'READY_FOR_OFFLINE_HANDOFF'},{members:value.members.map(row=>({...row,readiness_state:'BLOCKED_BY_BATCH',finding_refs:[]}))}]){
    const negative=await sealed({...value,...patch});
    const valid=await validateLearningReadiness(negative,scope,'task_test',`"${negative.receipt_sha256}"`);
    assert.equal(poolMemberCanQualify(valid,'sample_train'),false);
  }
  assert.equal(checked.training_authorized,false);
});
