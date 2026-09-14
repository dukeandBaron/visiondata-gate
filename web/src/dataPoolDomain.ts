import { canonicalizeJcs, sha256HexUtf8 } from './data/jcs.ts';
import type { LearningReadiness } from './learningDomain.ts';

export interface DataPoolScope { workspaceId: string; projectId: string }
export type PoolDisposition = 'QUALIFIED_CANDIDATE' | 'REPAIR_REQUIRED' | 'UNVERIFIED_HOLD';
export type PoolRepairAction = 'NONE' | 'RELABEL' | 'RECAPTURE' | 'REMOVE_OR_REPARTITION' | 'INVESTIGATE';
export type PoolRepairResult = 'NOT_APPLICABLE' | 'PENDING' | 'EVIDENCE_LINKED_NOT_VERIFIED';
export interface PoolMemberReview {
  sample_id: string;
  expected_asset_sha256: string;
  expected_annotation_revision: number;
  expected_annotation_sha256: string;
  disposition: PoolDisposition;
  repair_action: PoolRepairAction;
  repair_result: PoolRepairResult;
  decision_note: string;
}
export interface CreateDataPoolRequest {
  request_key: string;
  expected_readiness_sha256: string;
  reviewer_name: string;
  review_note: string;
  operator_attests_reviewed: true;
  members: PoolMemberReview[];
}
export interface CreatePoolVersionRequest extends CreateDataPoolRequest {
  expected_pool_sha256: string;
  expected_parent_version_sha256: string;
  source_task_id?: string | null;
}
export interface DeriveDataPoolRequest {
  request_key: string;
  expected_pool_sha256: string;
  expected_version_sha256: string;
  review_note: string;
  operator_attests_reviewed: true;
}
export class DataPoolContractError extends Error {
  readonly code = 'DATA_POOL_CONTRACT_HOLD';
  constructor(message = '数据池回执不符合已知合同。') { super(message); this.name = 'DataPoolContractError'; }
}
function ensure(condition: unknown, message?: string): asserts condition {
  if (!condition) throw new DataPoolContractError(message);
}
function object(value: unknown): Record<string, unknown> {
  ensure(value !== null && typeof value === 'object' && !Array.isArray(value));
  ensure(Object.getPrototypeOf(value) === Object.prototype || Object.getPrototypeOf(value) === null);
  return value as Record<string, unknown>;
}
function shape(value: unknown, required: readonly string[], optional: readonly string[] = []): Record<string, unknown> {
  const row = object(value), keys = new Set([...required, ...optional]);
  ensure(required.every(key => Object.hasOwn(row, key)) && Object.keys(row).every(key => keys.has(key)));
  return row;
}
function identifier(value: unknown): asserts value is string {
  ensure(typeof value === 'string' && /^[A-Za-z0-9_-]{1,120}$/.test(value), '数据池标识无效。');
}
function sha(value: unknown): asserts value is string {
  ensure(typeof value === 'string' && /^[0-9a-f]{64}$/.test(value), '数据池缺少有效的 SHA-256。');
}
function text(value: unknown, max = 2000, min = 1): asserts value is string {
  ensure(typeof value === 'string' && value.trim().length >= min && value.length <= max
    && !/[\u0000-\u0008\u000b\u000c\u000e-\u001f]/.test(value));
}
function member<T extends string>(value: unknown, values: readonly T[]): asserts value is T {
  ensure(typeof value === 'string' && (values as readonly string[]).includes(value), '数据池包含未知状态。');
}
function requestKey(value: unknown): asserts value is string {
  ensure(typeof value === 'string' && /^[A-Za-z0-9_-]{12,100}$/.test(value));
}
const createKeys = ['request_key', 'expected_readiness_sha256', 'reviewer_name', 'review_note', 'operator_attests_reviewed', 'members'];
function reviewedRequest(row: Record<string, unknown>): void {
  requestKey(row.request_key); text(row.review_note, 2000, 8);
  ensure(row.operator_attests_reviewed === true, '必须明确确认已逐成员复核。');
}
export function validatePoolMemberReview(value: unknown): PoolMemberReview {
  const row = shape(value, ['sample_id', 'expected_asset_sha256', 'expected_annotation_revision', 'expected_annotation_sha256', 'disposition', 'repair_action', 'repair_result', 'decision_note']);
  safeId(row.sample_id); sha(row.expected_asset_sha256); sha(row.expected_annotation_sha256);
  ensure(Number.isSafeInteger(row.expected_annotation_revision) && Number(row.expected_annotation_revision) >= 0);
  member(row.disposition, ['QUALIFIED_CANDIDATE', 'REPAIR_REQUIRED', 'UNVERIFIED_HOLD']);
  member(row.repair_action, ['NONE', 'RELABEL', 'RECAPTURE', 'REMOVE_OR_REPARTITION', 'INVESTIGATE']);
  member(row.repair_result, ['NOT_APPLICABLE', 'PENDING', 'EVIDENCE_LINKED_NOT_VERIFIED']);
  text(row.decision_note, 1000, 8);
  if (row.disposition === 'QUALIFIED_CANDIDATE') ensure(row.repair_action === 'NONE' && row.repair_result === 'NOT_APPLICABLE');
  if (row.disposition === 'REPAIR_REQUIRED') ensure(row.repair_action !== 'NONE' && row.repair_result !== 'NOT_APPLICABLE');
  if (row.disposition === 'UNVERIFIED_HOLD') ensure(row.repair_action === 'INVESTIGATE' && row.repair_result !== 'NOT_APPLICABLE');
  return row as unknown as PoolMemberReview;
}
function createRequest(row: Record<string, unknown>): void {
  reviewedRequest(row); text(row.reviewer_name, 120, 2); sha(row.expected_readiness_sha256);
  ensure(Array.isArray(row.members) && row.members.length > 0 && row.members.length <= 10000);
  const members = row.members.map(validatePoolMemberReview);
  ensure(new Set(members.map(item => item.sample_id)).size === members.length, '复核清单不能重复样本。');
}
export function validateCreateDataPoolRequest(value: unknown): CreateDataPoolRequest {
  const row = shape(value, createKeys); createRequest(row); return row as unknown as CreateDataPoolRequest;
}
export function validateCreatePoolVersionRequest(value: unknown): CreatePoolVersionRequest {
  const row = shape(value, [...createKeys, 'expected_pool_sha256', 'expected_parent_version_sha256'], ['source_task_id']);
  createRequest(row); sha(row.expected_pool_sha256); sha(row.expected_parent_version_sha256);
  if (row.source_task_id !== undefined && row.source_task_id !== null) safeId(row.source_task_id);
  return row as unknown as CreatePoolVersionRequest;
}
export function validateDeriveDataPoolRequest(value: unknown): DeriveDataPoolRequest {
  const row = shape(value, ['request_key', 'expected_pool_sha256', 'expected_version_sha256', 'review_note', 'operator_attests_reviewed']);
  reviewedRequest(row); sha(row.expected_pool_sha256); sha(row.expected_version_sha256);
  return row as unknown as DeriveDataPoolRequest;
}
export async function dataPoolDigest(value: unknown): Promise<string> {
  try { return await sha256HexUtf8(canonicalizeJcs(value)); }
  catch { throw new DataPoolContractError('无法核验数据池 JCS / SHA-256。'); }
}
/** UI eligibility is only a guard; selecting a disposition still requires human action. */
export function poolMemberCanQualify(readiness: LearningReadiness, sampleId: string, asset?: { annotation_count:number; mask_sha256?:string|null }): boolean {
  const row = readiness.members.find(item => item.sample_id === sampleId);
  if (!row || readiness.projection_status !== 'VERIFIED' || readiness.global_findings.length
    || readiness.unmapped_finding_refs.length || row.finding_refs.length || row.annotation_requirement === 'UNKNOWN'
    || readiness.blockers.some(code => code !== 'GATE_NOT_PASS')) return false;
  if (readiness.preflight_eligibility === 'READY_FOR_OFFLINE_HANDOFF') {
    return row.readiness_state === 'GATE_ELIGIBLE_NOT_TRAINING_APPROVED'
      || (row.readiness_state==='MASK_REQUIRED_FOR_REFERENCE_TRAINER'&&row.mask_available===false
        &&['OPTIONAL','NOT_APPLICABLE'].includes(row.annotation_requirement)&&asset?.annotation_count===0&&asset.mask_sha256==null);
  }
  return readiness.preflight_eligibility === 'HOLD' && readiness.blockers.includes('GATE_NOT_PASS')
    && readiness.members.some(item => item.finding_refs.length > 0)
    && row.readiness_state === 'BLOCKED_BY_BATCH';
}

export interface PoolFindingRef { finding_id: string; code: string; severity: string; finding_sha256: string }
export interface PoolMemberRecord {
  sample_id: string; source_task_id: string; split:'train'|'val'|'test'; category:string;
  annotation_requirement:'REQUIRED'|'OPTIONAL'|'NOT_APPLICABLE'|'UNKNOWN'; readiness_state:string;
  asset_sha256:string; annotation_revision:number; annotation_sha256:string; mask_sha256:string|null;
  finding_refs:PoolFindingRef[]; repair_cause_codes:string[]; disposition:PoolDisposition;
  repair_action:PoolRepairAction; repair_result:PoolRepairResult; decision_note:string; label_truth_authority:false;
}
export interface DataPoolVersion {
  schema_version:'visiondata-gate.data-pool-version.v1'; version_id:string; pool_id:string; version_number:number;
  parent_version_id:string|null; parent_version_sha256:string|null; source_task_id:string; workspace_id:string; project_id:string;
  source_id:string; snapshot_id:string; snapshot_receipt_sha256:string; batch_manifest_sha256:string; batch_contract_sha256:string;
  gate_result_sha256:string; readiness_receipt_sha256:string; preflight_receipt_sha256:string|null;
  status:'REVIEWED_ALL_QUALIFIED_REFERENCE'|'REVIEWED_ACTION_REQUIRED'|'REVIEWED_WITH_HOLD';
  qualified_count:number; repair_count:number; hold_count:number; members:PoolMemberRecord[];
  global_finding_refs:PoolFindingRef[]; unmapped_finding_refs:PoolFindingRef[]; readiness_blockers:string[];
  human_review:{reviewer_name:string;review_note:string;reviewed_by:string;operator_attests_reviewed:true}; created_at:string;
  label_truth_authority:false; training_ingestion_allowed:false; production_release_allowed:false; receipt_sha256:string;
}
export interface DataPoolRecord {
  schema_version:'visiondata-gate.data-pool.v1'; pool_id:string; workspace_id:string; project_id:string;
  origin_task_id:string; current_task_id:string; origin_source_id:string; current_source_id:string;
  origin_snapshot_id:string; current_snapshot_id:string; version_ids:string[]; current_version_id:string;
  created_by:string;created_at:string;label_truth_authority:false;production_release_allowed:false;receipt_sha256:string;
}
interface PoolReadState { read_status:'CURRENT'|'STALE_HOLD'; stale_reasons:string[]; training_ingestion_allowed:false;production_release_allowed:false;receipt_sha256:string }
export interface DataPoolProjection extends PoolReadState {schema_version:'visiondata-gate.data-pool-projection.v1';pool:DataPoolRecord;current_version:DataPoolVersion}
export interface PoolVersionProjection extends PoolReadState {schema_version:'visiondata-gate.data-pool-version-projection.v1';version:DataPoolVersion}
export interface DataPoolDerivation {
  schema_version:'visiondata-gate.data-pool-derivation.v1';derivation_id:string;pool_id:string;version_id:string;workspace_id:string;project_id:string;source_task_id:string;
  qualified_sample_ids:string[];excluded_sample_ids:string[];materialization_mode:'FULL_SNAPSHOT_REFERENCE'|'DERIVED_QUALIFIED_SUBSET';
  parent_source_id:string;derived_source_id:string|null;derived_snapshot_id:string;derived_snapshot_receipt_sha256:string|null;
  new_source_authorization_created:boolean;new_gate_required:boolean;plan_approval_required:boolean;new_gate_status:'NOT_APPLICABLE'|'NOT_STARTED';source_authorization_status:'ACTIVE';
  created_by:string;created_at:string;human_review_note:string;training_ingestion_allowed:false;label_truth_authority:false;production_release_allowed:false;receipt_sha256:string;
}
export interface DataPoolOperation {
  schema_version:'visiondata-gate.data-pool-operation.v1';project_id:string;operation:'create'|'version'|'derive';target_id:string;request_key:string;
  lookup_status:'FOUND'|'NOT_FOUND';execution_status:'COMPLETED'|'UNKNOWN_NOT_PROOF_OF_NO_WRITE';result_type:'pool'|'version'|'derivation'|null;
  result_id:string|null;current_result:DataPoolProjection|PoolVersionProjection|DataPoolDerivation|null;result_semantics:'CURRENT_RESULT';automatic_retry_allowed:false;receipt_sha256:string;
}
function safeId(value:unknown):asserts value is string {ensure(typeof value==='string'&&/^[A-Za-z0-9][A-Za-z0-9_.:-]{0,159}$/.test(value));}
function integer(value:unknown,min=0):asserts value is number {ensure(Number.isSafeInteger(value)&&Number(value)>=min);}
function array(value:unknown):unknown[] {ensure(Array.isArray(value)&&value.length<=10000);return value;}
function strings(value:unknown):string[] {const result=array(value);result.forEach(item=>text(item,1000));ensure(new Set(result).size===result.length);return result as string[];}
function ids(value:unknown):string[] {const result=strings(value);result.forEach(safeId);return result;}
function timestamp(value:unknown):void {text(value,80);ensure(/^\d{4}-\d{2}-\d{2}T.*(?:Z|[+-]\d{2}:\d{2})$/.test(value)&&Number.isFinite(Date.parse(value)));}
function scopeCheck(row:Record<string,unknown>,scope:DataPoolScope):void {identifier(scope.workspaceId);identifier(scope.projectId);ensure(row.workspace_id===scope.workspaceId&&row.project_id===scope.projectId,'数据池不属于当前工作空间和项目。');}
async function receipt(row:Record<string,unknown>,etag?:string|null):Promise<void> {sha(row.receipt_sha256);const body={...row};delete body.receipt_sha256;ensure(await dataPoolDigest(body)===row.receipt_sha256,'数据池回执摘要不匹配。');if(etag!==undefined)ensure(etag===`"${row.receipt_sha256}"`,'数据池必须带匹配的强 ETag。');}
function findings(value:unknown):PoolFindingRef[] {return array(value).map(item=>{const row=shape(item,['finding_id','code','severity','finding_sha256']);text(row.finding_id,512);text(row.code,512);member(row.severity,['critical','high','medium','low']);sha(row.finding_sha256);return row as unknown as PoolFindingRef;});}
function readState(row:Record<string,unknown>):void {member(row.read_status,['CURRENT','STALE_HOLD']);const reasons=strings(row.stale_reasons);ensure((row.read_status==='CURRENT')===(reasons.length===0));ensure(row.training_ingestion_allowed===false&&row.production_release_allowed===false);}
function poolMember(value:unknown,taskId:string):PoolMemberRecord {
  const row=shape(value,['sample_id','source_task_id','split','category','annotation_requirement','readiness_state','asset_sha256','annotation_revision','annotation_sha256','mask_sha256','finding_refs','repair_cause_codes','disposition','repair_action','repair_result','decision_note','label_truth_authority']);
  safeId(row.sample_id);ensure(row.source_task_id===taskId);member(row.split,['train','val','test']);text(row.category,512);member(row.annotation_requirement,['REQUIRED','OPTIONAL','NOT_APPLICABLE','UNKNOWN']);
  member(row.readiness_state,['UNVERIFIED_FINDING_IDENTITY','UNVERIFIED_TOOL_FAILURE','UNVERIFIED','NEEDS_ATTENTION','MASK_REQUIRED_FOR_REFERENCE_TRAINER','BLOCKED_BY_BATCH','GATE_ELIGIBLE_NOT_TRAINING_APPROVED']);
  sha(row.asset_sha256);sha(row.annotation_sha256);integer(row.annotation_revision);if(row.mask_sha256!==null)sha(row.mask_sha256);findings(row.finding_refs);strings(row.repair_cause_codes);ensure(row.label_truth_authority===false);
  validatePoolMemberReview({sample_id:row.sample_id,expected_asset_sha256:row.asset_sha256,expected_annotation_revision:row.annotation_revision,expected_annotation_sha256:row.annotation_sha256,disposition:row.disposition,repair_action:row.repair_action,repair_result:row.repair_result,decision_note:row.decision_note});
  if(row.disposition==='QUALIFIED_CANDIDATE')ensure((row.finding_refs as unknown[]).length===0&&( ['GATE_ELIGIBLE_NOT_TRAINING_APPROVED','BLOCKED_BY_BATCH'].includes(String(row.readiness_state))
    ||(row.readiness_state==='MASK_REQUIRED_FOR_REFERENCE_TRAINER'&&['OPTIONAL','NOT_APPLICABLE'].includes(String(row.annotation_requirement))&&row.mask_sha256===null))&&row.annotation_requirement!=='UNKNOWN');
  if(row.disposition==='REPAIR_REQUIRED')ensure((row.finding_refs as unknown[]).length>0);
  return row as unknown as PoolMemberRecord;
}
export async function validateDataPoolVersion(value:unknown,scope:DataPoolScope,versionId?:string):Promise<DataPoolVersion> {
  const row=shape(value,['schema_version','version_id','pool_id','version_number','parent_version_id','parent_version_sha256','source_task_id','workspace_id','project_id','source_id','snapshot_id','snapshot_receipt_sha256','batch_manifest_sha256','batch_contract_sha256','gate_result_sha256','readiness_receipt_sha256','preflight_receipt_sha256','status','qualified_count','repair_count','hold_count','members','global_finding_refs','unmapped_finding_refs','readiness_blockers','human_review','created_at','label_truth_authority','training_ingestion_allowed','production_release_allowed','receipt_sha256']);
  ensure(row.schema_version==='visiondata-gate.data-pool-version.v1');scopeCheck(row,scope);safeId(row.version_id);if(versionId!==undefined)ensure(row.version_id===versionId);safeId(row.pool_id);safeId(row.source_task_id);safeId(row.source_id);safeId(row.snapshot_id);integer(row.version_number,1);
  if(row.version_number===1)ensure(row.parent_version_id===null&&row.parent_version_sha256===null);else{safeId(row.parent_version_id);sha(row.parent_version_sha256);ensure(row.parent_version_id!==row.version_id);}
  for(const key of ['snapshot_receipt_sha256','batch_manifest_sha256','batch_contract_sha256','gate_result_sha256','readiness_receipt_sha256'])sha(row[key]);if(row.preflight_receipt_sha256!==null)sha(row.preflight_receipt_sha256);
  const members=array(row.members).map(item=>poolMember(item,row.source_task_id as string));ensure(members.length>0&&new Set(members.map(item=>item.sample_id)).size===members.length);
  for(const [field,state] of [['qualified_count','QUALIFIED_CANDIDATE'],['repair_count','REPAIR_REQUIRED'],['hold_count','UNVERIFIED_HOLD']] as const){integer(row[field]);ensure(row[field]===members.filter(item=>item.disposition===state).length);}
  ensure(row.status===(Number(row.hold_count)>0?'REVIEWED_WITH_HOLD':Number(row.repair_count)>0?'REVIEWED_ACTION_REQUIRED':'REVIEWED_ALL_QUALIFIED_REFERENCE'));
  const global=findings(row.global_finding_refs),unmapped=findings(row.unmapped_finding_refs),blockers=strings(row.readiness_blockers);
  if(Number(row.qualified_count)>0)ensure(global.length===0&&unmapped.length===0&&blockers.every(code=>code==='GATE_NOT_PASS'));
  if(members.some(item=>item.disposition==='QUALIFIED_CANDIDATE'&&item.readiness_state==='MASK_REQUIRED_FOR_REFERENCE_TRAINER'))ensure(blockers.length===0&&row.preflight_receipt_sha256!==null);
  const review=shape(row.human_review,['reviewer_name','review_note','reviewed_by','operator_attests_reviewed']);text(review.reviewer_name,120,2);text(review.review_note,2000,8);text(review.reviewed_by,512);ensure(review.operator_attests_reviewed===true);timestamp(row.created_at);
  ensure(row.label_truth_authority===false&&row.training_ingestion_allowed===false&&row.production_release_allowed===false);await receipt(row);return row as unknown as DataPoolVersion;
}
export async function validateDataPoolProjection(value:unknown,scope:DataPoolScope,poolId?:string,etag?:string|null):Promise<DataPoolProjection> {
  const row=shape(value,['schema_version','pool','current_version','read_status','stale_reasons','training_ingestion_allowed','production_release_allowed','receipt_sha256']);ensure(row.schema_version==='visiondata-gate.data-pool-projection.v1');readState(row);
  const pool=shape(row.pool,['schema_version','pool_id','workspace_id','project_id','origin_task_id','current_task_id','origin_source_id','current_source_id','origin_snapshot_id','current_snapshot_id','version_ids','current_version_id','created_by','created_at','label_truth_authority','production_release_allowed','receipt_sha256']);
  ensure(pool.schema_version==='visiondata-gate.data-pool.v1');scopeCheck(pool,scope);for(const key of ['pool_id','origin_task_id','current_task_id','origin_source_id','current_source_id','origin_snapshot_id','current_snapshot_id','current_version_id'])safeId(pool[key]);if(poolId!==undefined)ensure(pool.pool_id===poolId);
  const versions=ids(pool.version_ids);ensure(versions.length>0&&versions.at(-1)===pool.current_version_id);text(pool.created_by,512);timestamp(pool.created_at);ensure(pool.label_truth_authority===false&&pool.production_release_allowed===false);await receipt(pool);
  const version=await validateDataPoolVersion(row.current_version,scope,pool.current_version_id as string);ensure(version.pool_id===pool.pool_id&&version.source_task_id===pool.current_task_id&&version.source_id===pool.current_source_id&&version.snapshot_id===pool.current_snapshot_id&&version.version_number===versions.length);
  await receipt(row,etag);return row as unknown as DataPoolProjection;
}
export async function validatePoolVersionProjection(value:unknown,scope:DataPoolScope,versionId?:string,etag?:string|null):Promise<PoolVersionProjection> {
  const row=shape(value,['schema_version','version','read_status','stale_reasons','training_ingestion_allowed','production_release_allowed','receipt_sha256']);ensure(row.schema_version==='visiondata-gate.data-pool-version-projection.v1');readState(row);await validateDataPoolVersion(row.version,scope,versionId);await receipt(row,etag);return row as unknown as PoolVersionProjection;
}
export async function validateDataPoolList(value:unknown,scope:DataPoolScope,taskId:string,etag?:string|null):Promise<DataPoolProjection[]> {
  const row=shape(value,['schema_version','task_id','workspace_id','project_id','items','receipt_sha256']);ensure(row.schema_version==='visiondata-gate.data-pool-list.v1'&&row.task_id===taskId);scopeCheck(row,scope);
  const items=await Promise.all(array(row.items).map(item=>validateDataPoolProjection(item,scope)));ensure(new Set(items.map(item=>item.pool.pool_id)).size===items.length);ensure(items.every(item=>item.pool.origin_task_id===taskId||item.pool.current_task_id===taskId));await receipt(row,etag);return items;
}
export async function validateDataPoolDerivation(value:unknown,scope:DataPoolScope,poolId?:string,versionId?:string,etag?:string|null):Promise<DataPoolDerivation> {
  const row=shape(value,['schema_version','derivation_id','pool_id','version_id','workspace_id','project_id','source_task_id','qualified_sample_ids','excluded_sample_ids','materialization_mode','parent_source_id','derived_source_id','derived_snapshot_id','derived_snapshot_receipt_sha256','new_source_authorization_created','new_gate_required','plan_approval_required','new_gate_status','source_authorization_status','created_by','created_at','human_review_note','training_ingestion_allowed','label_truth_authority','production_release_allowed','receipt_sha256']);
  ensure(row.schema_version==='visiondata-gate.data-pool-derivation.v1');scopeCheck(row,scope);for(const key of ['derivation_id','pool_id','version_id','source_task_id','parent_source_id','derived_snapshot_id'])safeId(row[key]);if(poolId!==undefined)ensure(row.pool_id===poolId);if(versionId!==undefined)ensure(row.version_id===versionId);
  const qualified=ids(row.qualified_sample_ids),excluded=ids(row.excluded_sample_ids);ensure(qualified.length>0&&excluded.every(item=>!qualified.includes(item)));member(row.materialization_mode,['FULL_SNAPSHOT_REFERENCE','DERIVED_QUALIFIED_SUBSET']);
  if(row.materialization_mode==='DERIVED_QUALIFIED_SUBSET'){safeId(row.derived_source_id);sha(row.derived_snapshot_receipt_sha256);ensure(excluded.length>0&&row.derived_source_id!==row.parent_source_id&&row.new_source_authorization_created===true&&row.new_gate_required===true&&row.plan_approval_required===true&&row.new_gate_status==='NOT_STARTED');}
  else ensure(excluded.length===0&&row.derived_source_id===null&&row.derived_snapshot_receipt_sha256===null&&row.new_source_authorization_created===false&&row.new_gate_required===false&&row.plan_approval_required===false&&row.new_gate_status==='NOT_APPLICABLE');
  ensure(row.source_authorization_status==='ACTIVE'&&row.training_ingestion_allowed===false&&row.label_truth_authority===false&&row.production_release_allowed===false);text(row.created_by,512);timestamp(row.created_at);text(row.human_review_note,2000,8);await receipt(row,etag);return row as unknown as DataPoolDerivation;
}
export async function validateDataPoolOperation(value:unknown,scope:DataPoolScope,operation:PendingPoolWrite['operation'],request:string,targetId:string,etag?:string|null):Promise<DataPoolOperation> {
  const row=shape(value,['schema_version','project_id','operation','target_id','request_key','lookup_status','execution_status','result_type','result_id','current_result','result_semantics','automatic_retry_allowed','receipt_sha256']);ensure(row.schema_version==='visiondata-gate.data-pool-operation.v1'&&row.project_id===scope.projectId&&row.operation===operation&&row.request_key===request&&row.target_id===targetId);ensure(row.result_semantics==='CURRENT_RESULT'&&row.automatic_retry_allowed===false);member(row.lookup_status,['FOUND','NOT_FOUND']);
  if(row.lookup_status==='NOT_FOUND')ensure(row.execution_status==='UNKNOWN_NOT_PROOF_OF_NO_WRITE'&&row.result_type===null&&row.result_id===null&&row.current_result===null);
  else{ensure(row.execution_status==='COMPLETED'&&row.result_type===({create:'pool',version:'version',derive:'derivation'} as const)[operation]);safeId(row.result_id);
    if(operation==='create'){const current=await validateDataPoolProjection(row.current_result,scope,row.result_id);ensure(current.pool.origin_task_id===targetId);}
    else if(operation==='version'){const current=await validatePoolVersionProjection(row.current_result,scope,row.result_id);ensure(current.version.pool_id===targetId);}
    else{const current=await validateDataPoolDerivation(row.current_result,scope,undefined,targetId);ensure(current.derivation_id===row.result_id);}}
  await receipt(row,etag);return row as unknown as DataPoolOperation;
}

/** Only non-secret request identities are persisted; never labels, notes or tokens. */
export interface PendingPoolWrite {
  requestKey: string;
  operation: 'create' | 'version' | 'derive';
  targetId: string;
  requestSha256: string;
}
export type PoolPendingState = PendingPoolWrite | { corrupt: true } | null;
export function poolPendingStorageKey(actorId: string, scope: DataPoolScope): string {
  identifier(actorId); identifier(scope.workspaceId); identifier(scope.projectId);
  return `visiondata:data-pool:pending:${actorId}:${scope.workspaceId}:${scope.projectId}`;
}
export function validatePoolPendingWrite(value: unknown): PendingPoolWrite {
  const row = shape(value, ['requestKey', 'operation', 'targetId', 'requestSha256']);
  ensure(typeof row.requestKey === 'string' && /^[A-Za-z0-9_-]{12,100}$/.test(row.requestKey));
  ensure(row.operation === 'create' || row.operation === 'version' || row.operation === 'derive'); identifier(row.targetId); sha(row.requestSha256);
  return row as unknown as PendingPoolWrite;
}
export function readPoolPendingWrite(storage: Pick<Storage, 'getItem'>, key: string): PoolPendingState {
  try {
    const value = storage.getItem(key);
    return value === null ? null : validatePoolPendingWrite(JSON.parse(value));
  } catch { return { corrupt: true }; }
}
export function persistPoolPendingWrite(storage: Pick<Storage, 'setItem' | 'getItem'>, key: string, pending: PendingPoolWrite): void {
  validatePoolPendingWrite(pending);
  ensure(readPoolPendingWrite(storage, key) === null, '已存在待对账请求，不能覆盖或重发。');
  storage.setItem(key, JSON.stringify(pending));
  const stored = readPoolPendingWrite(storage, key);
  ensure(stored !== null && !('corrupt' in stored) && stored.requestKey === pending.requestKey
    && stored.operation === pending.operation && stored.targetId === pending.targetId
    && stored.requestSha256 === pending.requestSha256, '无法持久保存写入标识，请求未发送。');
}
export function clearPoolPendingWrite(storage: Pick<Storage, 'getItem' | 'removeItem'>, key: string, pending: PendingPoolWrite): void {
  const stored = readPoolPendingWrite(storage, key);
  ensure(stored !== null && !('corrupt' in stored)
    && canonicalizeJcs(stored) === canonicalizeJcs(pending), '待对账请求已变化，保留写入锁。');
  storage.removeItem(key);
  ensure(storage.getItem(key) === null, '待对账标识未清除，继续保留 HOLD。');
}
