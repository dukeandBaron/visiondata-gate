import { operatorFetch, OperatorApiError } from "./api";
import { detachedJcsSha256 } from "./jcs";

export interface ComputeScope {taskId:string;workspaceId:string;projectId:string}
export interface ComputePreflight {
  schema_version:"visiondata-gate.compute-preflight.v1";task_id:string;workspace_id:string;project_id:string;
  eligibility:"HOLD"|"READY_FOR_OFFLINE_HANDOFF";blockers:string[];binding:Record<string,string|number>|null;
  adapter:{kind:"OFFLINE_EXPORT";live_submission_available:false;device_validation:"NOT_TESTED"};production_release_allowed:false;receipt_sha256:string;
}
export interface ComputeRequest {
  request_key:string;expected_preflight_sha256:string;review_note:string;operator_attests_reviewed:true;workload:"TRAINING"|"EVALUATION";
  resources:{runtime_image:string;cann_version:string;npu_count:number;cpu_cores:number;memory_gib:number;max_wall_seconds:number};
}
export interface ComputeRecord {
  schema_version:"visiondata-gate.compute-handoff.v1";handoff_id:string;task_id:string;workspace_id:string;project_id:string;
  prepared_by:string;prepared_at:string;status:"PREPARED_NOT_SUBMITTED";request:ComputeRequest;binding:Record<string,string|number>;
  remote_job_id:null;remote_execution_verified:false;dataset_bytes_exported:false;production_release_allowed:false;machine_write_permitted:false;receipt_sha256:string;
}
export interface ComputeList {schema_version:"visiondata-gate.compute-handoff-list.v1";task_id:string;workspace_id:string;project_id:string;items:Array<{read_status:"VERIFIED"|"STALE_HOLD";record:ComputeRecord}>;receipt_sha256:string}
function ensure(value:unknown,message:string):asserts value {if(!value)throw new OperatorApiError("COMPUTE_CONTRACT_HOLD",message,409);}
function object(value:unknown):value is Record<string,unknown>{return Boolean(value)&&typeof value==='object'&&!Array.isArray(value);}
async function verified(value:unknown,scope:ComputeScope,schema:string):Promise<Record<string,unknown>>{
  ensure(object(value)&&value.schema_version===schema,"算力交接响应格式不匹配。");
  ensure(value.task_id===scope.taskId&&value.workspace_id===scope.workspaceId&&value.project_id===scope.projectId,"算力交接响应不属于当前任务。");
  ensure(typeof value.receipt_sha256==='string'&&/^[0-9a-f]{64}$/.test(value.receipt_sha256)&&await detachedJcsSha256(value,'receipt_sha256')===value.receipt_sha256,"算力交接摘要核验失败。");
  return value;
}
export async function validateComputeRecord(value:unknown,scope:ComputeScope):Promise<ComputeRecord>{
  const row=await verified(value,scope,'visiondata-gate.compute-handoff.v1');
  ensure(row.status==='PREPARED_NOT_SUBMITTED'&&row.remote_job_id===null&&row.remote_execution_verified===false&&row.dataset_bytes_exported===false&&row.production_release_allowed===false&&row.machine_write_permitted===false,"算力记录越过离线准备权限。");
  ensure(typeof row.handoff_id==='string'&&object(row.request)&&object(row.binding)&&row.binding.task_id===scope.taskId,"算力记录缺少输入绑定。");
  return row as unknown as ComputeRecord;
}
export async function getComputePreflight(scope:ComputeScope):Promise<ComputePreflight>{
  const response=await operatorFetch(`/v1/tasks/${encodeURIComponent(scope.taskId)}/compute-preflight`);
  const value=await verified(await response.json(),scope,'visiondata-gate.compute-preflight.v1');
  ensure(['HOLD','READY_FOR_OFFLINE_HANDOFF'].includes(String(value.eligibility))&&Array.isArray(value.blockers)&&value.blockers.every(item=>typeof item==='string')&&object(value.adapter)&&value.adapter.kind==='OFFLINE_EXPORT'&&value.adapter.live_submission_available===false&&value.adapter.device_validation==='NOT_TESTED'&&value.production_release_allowed===false,"算力预检状态不完整。");
  ensure(value.eligibility==='HOLD'?value.blockers.length>0:value.blockers.length===0&&object(value.binding),"算力预检缺少绑定或阻断理由。");
  return value as unknown as ComputePreflight;
}
export async function getComputeHandoffs(scope:ComputeScope):Promise<ComputeList>{
  const response=await operatorFetch(`/v1/tasks/${encodeURIComponent(scope.taskId)}/compute-handoffs`);
  const value=await verified(await response.json(),scope,'visiondata-gate.compute-handoff-list.v1');
  ensure(Array.isArray(value.items),"算力交接列表不可读取。");
  for(const item of value.items){ensure(object(item)&&['VERIFIED','STALE_HOLD'].includes(String(item.read_status)),"算力交接读取状态未知。");await validateComputeRecord(item.record,scope);}
  return value as unknown as ComputeList;
}
export async function prepareCompute(scope:ComputeScope,request:ComputeRequest):Promise<ComputeRecord>{
  const response=await operatorFetch(`/v1/tasks/${encodeURIComponent(scope.taskId)}/compute-handoffs`,{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(request)});
  return validateComputeRecord(await response.json(),scope);
}
export async function exportCompute(scope:ComputeScope,handoffId:string):Promise<ComputeRecord>{
  const response=await operatorFetch(`/v1/tasks/${encodeURIComponent(scope.taskId)}/compute-handoffs/${encodeURIComponent(handoffId)}/export`);
  return validateComputeRecord(await response.json(),scope);
}
