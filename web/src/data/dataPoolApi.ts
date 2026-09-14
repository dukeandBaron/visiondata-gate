import { operatorFetch, OperatorApiError } from './api';
import {
  DataPoolContractError, validateCreateDataPoolRequest, validateCreatePoolVersionRequest, validateDeriveDataPoolRequest,
  validateDataPoolProjection, validatePoolVersionProjection, validateDataPoolList, validateDataPoolDerivation, validateDataPoolOperation,
} from '../dataPoolDomain.ts';
import type { DataPoolScope, CreateDataPoolRequest, CreatePoolVersionRequest, DeriveDataPoolRequest, PendingPoolWrite } from '../dataPoolDomain.ts';

// Auth remains in operatorFetch. No retries, polling, worker dispatch or training here.
function id(value:string):string {
  if(typeof value!=='string'||!/^[A-Za-z0-9][A-Za-z0-9_.:-]{0,159}$/.test(value))throw new DataPoolContractError('数据池请求标识无效。');
  return encodeURIComponent(value);
}
function scoped(scope:DataPoolScope):void {id(scope.workspaceId);id(scope.projectId);}
async function contract<T>(action:()=>Promise<T>):Promise<T> {
  try{return await action();}catch(error){if(error instanceof DataPoolContractError||error instanceof SyntaxError)throw new OperatorApiError('DATA_POOL_CONTRACT_HOLD',error.message,409);throw error;}
}
async function payload(response:Response):Promise<unknown> {
  if(response.headers.get('Content-Type')?.split(';')[0]?.trim().toLowerCase()!=='application/json')throw new DataPoolContractError('数据池响应不是 JSON 回执。');
  const value:unknown=await response.json(),digest=response.headers.get('X-Content-SHA256');
  if(digest!==null&&(!value||typeof value!=='object'||!('receipt_sha256'in value)||value.receipt_sha256!==digest))throw new DataPoolContractError('数据池内容摘要头不匹配。');
  return value;
}
export function normalizeDataPoolRequest(operation:PendingPoolWrite['operation'],value:unknown):CreateDataPoolRequest|CreatePoolVersionRequest|DeriveDataPoolRequest {
  try {
    if(!value||typeof value!=='object'||Array.isArray(value)||(Object.getPrototypeOf(value)!==Object.prototype&&Object.getPrototypeOf(value)!==null))throw new DataPoolContractError('请求必须是普通 JSON 对象。');
    const row:Record<string,unknown>={...value};
    for(const [key,item]of Object.entries(row))if(typeof item==='string')row[key]=item.trim();
    if(Array.isArray(row.members))row.members=row.members.map(item=>{
      if(!item||typeof item!=='object'||Array.isArray(item))throw new DataPoolContractError('成员请求无效。');
      return Object.fromEntries(Object.entries(item).map(([key,value])=>[key,typeof value==='string'?value.trim():value]));
    }).sort((a,b)=>String(a.sample_id)<String(b.sample_id)?-1:String(a.sample_id)>String(b.sample_id)?1:0);
    if(operation==='version')row.source_task_id??=null;
    const checked=operation==='create'?validateCreateDataPoolRequest(row):operation==='version'?validateCreatePoolVersionRequest(row):validateDeriveDataPoolRequest(row);
    JSON.stringify(checked);return checked;
  }catch(error){throw new OperatorApiError('DATA_POOL_REQUEST_NOT_SENT',`数据池请求未发送：${error instanceof Error?error.message:'本地检查失败。'}`,422);}
}
async function write<T>(scope:DataPoolScope,route:()=>string,operation:PendingPoolWrite['operation'],request:unknown,validate:(value:unknown,etag:string|null)=>Promise<T>):Promise<T> {
  let path:string,body:string;
  try{scoped(scope);path=route();body=JSON.stringify(normalizeDataPoolRequest(operation,request));}
  catch(error){if(error instanceof OperatorApiError)throw error;throw new OperatorApiError('DATA_POOL_REQUEST_NOT_SENT','数据池范围或请求标识无效；未发送。',422);}
  return contract(async()=>{const response=await operatorFetch(path,{method:'POST',headers:{'Content-Type':'application/json'},body});return validate(await payload(response),response.headers.get('ETag'));});
}
export function getDataPool(scope:DataPoolScope,poolId:string) {
  return contract(async()=>{scoped(scope);const response=await operatorFetch(`/v1/data-pools/${id(poolId)}`);return validateDataPoolProjection(await payload(response),scope,poolId,response.headers.get('ETag'));});
}
export function getDataPoolVersion(scope:DataPoolScope,versionId:string) {
  return contract(async()=>{scoped(scope);const response=await operatorFetch(`/v1/data-pool-versions/${id(versionId)}`);return validatePoolVersionProjection(await payload(response),scope,versionId,response.headers.get('ETag'));});
}
export function listTaskDataPools(scope:DataPoolScope,taskId:string) {
  return contract(async()=>{scoped(scope);const response=await operatorFetch(`/v1/tasks/${id(taskId)}/data-pools`);return validateDataPoolList(await payload(response),scope,taskId,response.headers.get('ETag'));});
}
export function createDataPool(scope:DataPoolScope,taskId:string,request:CreateDataPoolRequest) {
  return write(scope,()=>`/v1/tasks/${id(taskId)}/data-pools`,'create',request,(value,etag)=>validateDataPoolProjection(value,scope,undefined,etag));
}
export function createDataPoolVersion(scope:DataPoolScope,poolId:string,request:CreatePoolVersionRequest) {
  return write(scope,()=>`/v1/data-pools/${id(poolId)}/versions`,'version',request,(value,etag)=>validateDataPoolProjection(value,scope,poolId,etag));
}
export function deriveDataPool(scope:DataPoolScope,poolId:string,versionId:string,request:DeriveDataPoolRequest) {
  return write(scope,()=>`/v1/data-pools/${id(poolId)}/versions/${id(versionId)}/derive`,'derive',request,(value,etag)=>validateDataPoolDerivation(value,scope,poolId,versionId,etag));
}
export function getDataPoolOperation(scope:DataPoolScope,operation:PendingPoolWrite['operation'],requestKey:string,targetId:string) {
  return contract(async()=>{
    scoped(scope);if(!['create','version','derive'].includes(operation)||!/^[A-Za-z0-9_-]{12,100}$/.test(requestKey))throw new DataPoolContractError('数据池对账参数无效。');
    const response=await operatorFetch(`/v1/projects/${id(scope.projectId)}/data-pool-operations/${operation}/${id(requestKey)}?target_id=${id(targetId)}`);
    return validateDataPoolOperation(await payload(response),scope,operation,requestKey,targetId,response.headers.get('ETag'));
  });
}
